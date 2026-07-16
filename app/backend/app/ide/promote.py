"""把 IDE 沙箱 emit_result 提升为正式 Run，复用现有 RunDetail pipeline。

输入：IDE run 的 result.json（用户代码末尾 quantbt.emit_result({...}) 产出）
输出：runs/<new_run_id>/ 目录，含 run.json + portfolio.csv (+ trades.csv +
     strategy.py)，前端 /runs/<id> 三联图能直接读。

emit_result 协议（最小可识别字段）：
    {
      "equity_curve": [{"t": "2026-01-01", "equity": 1.0, "net_return": 0.0, "benchmark_return": 0.0?}, ...],
      "trades": [{"timestamp": ..., "symbol": ..., "side": ..., "quantity": ..., "price": ...}]?,
      "positions": [...]?,
      "attribution": [{"period": ..., "component": ..., "portfolio_weight": ...,
                         "benchmark_weight": ..., "portfolio_return": ...,
                         "benchmark_return": ..., "benchmark_total_return": ...,
                         "allocation_effect": ..., "selection_effect": ...,
                         "interaction_effect": ..., "cost_effect": ...,
                         "net_contribution": ...}]?,
      "metadata": {"strategy_name": ..., "market": "stocks_cn|crypto_perp|crypto_spot",
                   "frequency": "1d|1h|...", "benchmark": "000300.SH|BTC-USDT" }?,
    }

只有 equity_curve 是必需的；其它字段缺省由 metadata 默认值填或留空。
"""

from __future__ import annotations

import csv
import ctypes
import errno
import hashlib
import io
import json
import math
import os
import stat
import statistics
import sys
from dataclasses import dataclass
from pathlib import Path
from secrets import token_urlsafe
from typing import Any, Callable, Iterable, Sequence

from ..lineage.ids import content_hash
from ..lineage.spine import PROMOTION_LABELS
from ..paths import RUN_ROOT
from .promotion_receipt import (
    GENERATED_ARTIFACT_INVENTORY_KEY,
    PromotionCandidateProof,
)
from ..research_os.backtest_artifact_resolver import (
    BacktestArtifactResolutionError,
    canonical_attribution_csv_bytes,
)


class PromoteError(Exception):
    """IDE run 不满足 promote 条件（缺 equity_curve / 长度 < 2 / 数据非法）。"""


class PromoteCommitError(PromoteError):
    """A post-publish formal-promotion commit or compensation failed."""


@dataclass(frozen=True)
class PromotedRun:
    run_id: str
    run_dir: Path
    metrics: dict[str, float]
    gate_verdict: dict | None = None   # T-015 多证据三角裁决（仅当传入 ledger 时有值）
    promotion_receipt_ref: str | None = None
    requested_label: str = "exploratory"


_PROMOTION_PRECOMMIT_REF_FIELDS = (
    "qro_id",
    "research_graph_command_id",
    "compiler_ir_ref",
    "compiler_pass_ref",
    "entrypoint_coverage_ref",
)
_PROMOTION_PRECOMMIT_REF_PREFIXES = {
    "qro_id": "qro_",
    "research_graph_command_id": "rgcmd_",
    "compiler_ir_ref": "compiler_ir:",
    "compiler_pass_ref": "compiler_pass:",
    "entrypoint_coverage_ref": "goal_entrypoint_coverage:",
}


def _validated_promotion_precommit_result(value: Any) -> dict[str, str]:
    """Require the complete canonical QRO -> compiler -> coverage prefix."""

    if not isinstance(value, dict):
        raise PromoteError("promotion precommit result must be a ref mapping")
    if set(value) != set(_PROMOTION_PRECOMMIT_REF_FIELDS):
        raise PromoteError(
            "promotion precommit result requires the exact canonical ref key set"
        )
    normalized: dict[str, str] = {}
    for field_name in _PROMOTION_PRECOMMIT_REF_FIELDS:
        raw = value.get(field_name)
        if not isinstance(raw, str) or not raw.strip() or raw != raw.strip():
            raise PromoteError(
                f"promotion precommit result requires exact {field_name}"
            )
        expected_prefix = _PROMOTION_PRECOMMIT_REF_PREFIXES[field_name]
        if not raw.startswith(expected_prefix) or raw == expected_prefix:
            raise PromoteError(
                f"promotion precommit result {field_name} has an invalid type prefix"
            )
        normalized[field_name] = raw
    if len(set(normalized.values())) != len(normalized):
        raise PromoteError("promotion precommit refs must be globally unique")
    return normalized


def _directory_flags() -> int:
    if not hasattr(os, "O_DIRECTORY") or not hasattr(os, "O_NOFOLLOW"):
        raise PromoteError(
            "safe promotion filesystem operations require O_DIRECTORY and O_NOFOLLOW"
        )
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    if hasattr(os, "O_CLOEXEC"):
        flags |= os.O_CLOEXEC
    return flags


def _open_bound_directory(path: Path, *, label: str) -> tuple[int, os.stat_result]:
    try:
        expected = path.lstat()
    except OSError as exc:
        raise PromoteError(f"{label} is unavailable: {type(exc).__name__}") from exc
    if stat.S_ISLNK(expected.st_mode) or not stat.S_ISDIR(expected.st_mode):
        raise PromoteError(f"{label} must be a real no-follow directory")
    try:
        fd = os.open(path, _directory_flags())
    except OSError as exc:
        raise PromoteError(f"{label} could not be opened: {type(exc).__name__}") from exc
    opened = os.fstat(fd)
    if (
        not stat.S_ISDIR(opened.st_mode)
        or (opened.st_dev, opened.st_ino) != (expected.st_dev, expected.st_ino)
    ):
        os.close(fd)
        raise PromoteError(f"{label} identity changed while opening")
    return fd, expected


def _open_bound_child_directory(
    parent_fd: int,
    name: str,
    *,
    label: str,
    create: bool,
) -> tuple[int, os.stat_result]:
    try:
        expected = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
    except FileNotFoundError:
        if not create:
            raise PromoteError(f"{label} is unavailable")
        try:
            os.mkdir(name, mode=0o700, dir_fd=parent_fd)
        except FileExistsError:
            pass
        expected = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
    if stat.S_ISLNK(expected.st_mode) or not stat.S_ISDIR(expected.st_mode):
        raise PromoteError(f"{label} must be a real no-follow directory")
    try:
        fd = os.open(name, _directory_flags(), dir_fd=parent_fd)
    except OSError as exc:
        raise PromoteError(f"{label} could not be opened: {type(exc).__name__}") from exc
    opened = os.fstat(fd)
    if (
        not stat.S_ISDIR(opened.st_mode)
        or (opened.st_dev, opened.st_ino) != (expected.st_dev, expected.st_ino)
    ):
        os.close(fd)
        raise PromoteError(f"{label} identity changed while opening")
    return fd, expected


def _write_new_bytes_at(directory_fd: int, name: str, payload: bytes) -> None:
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW
    if hasattr(os, "O_CLOEXEC"):
        flags |= os.O_CLOEXEC
    fd = os.open(name, flags, 0o600, dir_fd=directory_fd)
    try:
        with os.fdopen(fd, "wb") as handle:
            fd = -1
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
    finally:
        if fd >= 0:
            os.close(fd)


def _rename_noreplace_at(
    src_dir_fd: int,
    src_name: str,
    dst_dir_fd: int,
    dst_name: str,
) -> None:
    """Atomically rename one direct child without replacing any destination.

    Ordinary ``rename`` is deliberately forbidden here: on both Darwin and
    Linux it may replace an existing empty directory.  The operation therefore
    uses only a kernel no-replace flag and fails closed when that primitive is
    unavailable.
    """

    for field_name, value in (("source", src_name), ("destination", dst_name)):
        raw = str(value or "")
        name = raw.strip()
        if (
            raw != name
            or not name
            or name in {".", ".."}
            or Path(name).name != name
            or "/" in name
            or "\\" in name
            or "\x00" in name
        ):
            raise PromoteError(
                f"promotion no-replace rename {field_name} must be one direct child"
            )

    libc = ctypes.CDLL(None, use_errno=True)
    if sys.platform == "darwin":
        symbol = "renameatx_np"
        flags = 0x00000004  # RENAME_EXCL from <sys/stdio.h>.
    elif sys.platform.startswith("linux"):
        symbol = "renameat2"
        flags = 0x00000001  # RENAME_NOREPLACE from <linux/fs.h>.
    else:
        raise PromoteError(
            "kernel no-replace directory rename is unavailable on this platform"
        )
    try:
        rename_call = getattr(libc, symbol)
    except AttributeError as exc:
        raise PromoteError(
            f"kernel no-replace directory rename primitive {symbol} is unavailable"
        ) from exc
    rename_call.argtypes = (
        ctypes.c_int,
        ctypes.c_char_p,
        ctypes.c_int,
        ctypes.c_char_p,
        ctypes.c_uint,
    )
    rename_call.restype = ctypes.c_int
    ctypes.set_errno(0)
    result = rename_call(
        int(src_dir_fd),
        os.fsencode(src_name),
        int(dst_dir_fd),
        os.fsencode(dst_name),
        flags,
    )
    if result != 0:
        error_number = ctypes.get_errno() or errno.EIO
        raise OSError(
            error_number,
            os.strerror(error_number),
            dst_name,
        )


def _rename_hidden_candidate_for_audit(
    staging_fd: int,
    *,
    candidate_name: str,
    candidate_identity: tuple[int, int],
    phase: str,
) -> str:
    audit_name = f"{candidate_name}.{phase}.{token_urlsafe(16)}"
    try:
        _rename_noreplace_at(
            staging_fd,
            candidate_name,
            staging_fd,
            audit_name,
        )
    except OSError as rename_exc:
        try:
            current = os.stat(
                candidate_name,
                dir_fd=staging_fd,
                follow_symlinks=False,
            )
        except FileNotFoundError as exc:
            raise PromoteError(
                "hidden promotion candidate disappeared after audit rename failure"
            ) from exc
        if (
            stat.S_ISLNK(current.st_mode)
            or not stat.S_ISDIR(current.st_mode)
            or (current.st_dev, current.st_ino) != candidate_identity
        ):
            raise PromoteError(
                "hidden promotion candidate identity changed during audit rename"
            ) from rename_exc
        raise PromoteError(
            "hidden promotion candidate audit rename failed; candidate retained"
        ) from rename_exc
    audited = os.stat(
        audit_name,
        dir_fd=staging_fd,
        follow_symlinks=False,
    )
    if (
        stat.S_ISLNK(audited.st_mode)
        or not stat.S_ISDIR(audited.st_mode)
        or (audited.st_dev, audited.st_ino) != candidate_identity
    ):
        raise PromoteError(
            "hidden promotion candidate audit identity mismatch after rename"
        )
    return audit_name


def _publish_hidden_candidate(
    *,
    run_root_fd: int,
    staging_fd: int,
    candidate_name: str,
    run_id: str,
    candidate_identity: tuple[int, int],
) -> None:
    candidate = os.stat(
        candidate_name,
        dir_fd=staging_fd,
        follow_symlinks=False,
    )
    if (
        stat.S_ISLNK(candidate.st_mode)
        or not stat.S_ISDIR(candidate.st_mode)
        or (candidate.st_dev, candidate.st_ino) != candidate_identity
    ):
        raise PromoteError("hidden promotion candidate identity changed before publish")
    try:
        os.stat(run_id, dir_fd=run_root_fd, follow_symlinks=False)
    except FileNotFoundError:
        pass
    else:
        raise PromoteError("final promoted run path already exists")
    try:
        _rename_noreplace_at(
            staging_fd,
            candidate_name,
            run_root_fd,
            run_id,
        )
    except OSError as exc:
        try:
            retained = os.stat(
                candidate_name,
                dir_fd=staging_fd,
                follow_symlinks=False,
            )
        except FileNotFoundError as missing_exc:
            raise PromoteError(
                "promotion publish rename failed and candidate disappeared"
            ) from missing_exc
        if (
            stat.S_ISLNK(retained.st_mode)
            or not stat.S_ISDIR(retained.st_mode)
            or (retained.st_dev, retained.st_ino) != candidate_identity
        ):
            raise PromoteError(
                "promotion candidate identity changed during publish rename"
            ) from exc
        raise PromoteError(
            "promotion atomic publish rename failed; hidden candidate retained"
        ) from exc
    final = os.stat(run_id, dir_fd=run_root_fd, follow_symlinks=False)
    if (
        stat.S_ISLNK(final.st_mode)
        or not stat.S_ISDIR(final.st_mode)
        or (final.st_dev, final.st_ino) != candidate_identity
    ):
        raise PromoteError("final promoted run identity mismatch after publish")
    try:
        os.stat(
            candidate_name,
            dir_fd=staging_fd,
            follow_symlinks=False,
        )
    except FileNotFoundError:
        pass
    else:
        raise PromoteError("published promotion left a duplicate staging path")


def quarantine_promoted_run(
    promoted: PromotedRun,
    *,
    phase: str,
    expected_run_root: Path,
) -> Path | None:
    """Atomically move one exact visible run below trusted ``.staging``.

    There is deliberately no delete fallback. If the exact inode cannot be
    renamed and verified, the function fails loudly without deleting any path.
    """

    run_dir = Path(promoted.run_dir)
    run_root = Path(expected_run_root)
    raw_run_id = str(promoted.run_id or "")
    run_id = raw_run_id.strip()
    normalized_phase = str(phase or "").strip()
    expected_run_dir = run_root / run_id
    if (
        not run_id
        or raw_run_id != run_id
        or run_id in {".", ".."}
        or Path(run_id).name != run_id
        or run_dir.name != run_id
        or run_dir.parent != run_root
        or run_dir != expected_run_dir
        or Path(os.path.abspath(run_dir))
        != Path(os.path.abspath(expected_run_dir))
    ):
        raise PromoteError("promoted run quarantine identity mismatch")
    if (
        not normalized_phase
        or any(
            char
            not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-"
            for char in normalized_phase
        )
    ):
        raise PromoteError("promoted run quarantine phase is invalid")

    run_root_fd, _root_stat = _open_bound_directory(
        run_root,
        label="expected run root",
    )
    staging_fd: int | None = None
    try:
        try:
            original_stat = os.stat(
                run_id,
                dir_fd=run_root_fd,
                follow_symlinks=False,
            )
        except FileNotFoundError:
            return None
        if stat.S_ISLNK(original_stat.st_mode):
            raise PromoteError("promoted run quarantine refuses a symlink run")
        if not stat.S_ISDIR(original_stat.st_mode):
            raise PromoteError("promoted run quarantine requires a directory run")
        original_identity = (original_stat.st_dev, original_stat.st_ino)

        staging_fd, _staging_stat = _open_bound_child_directory(
            run_root_fd,
            ".staging",
            label="promoted run quarantine staging root",
            create=True,
        )
        quarantine_name = (
            f"{run_id}.{normalized_phase}.{token_urlsafe(16)}"
        )
        quarantine = run_root / ".staging" / quarantine_name
        try:
            _rename_noreplace_at(
                run_root_fd,
                run_id,
                staging_fd,
                quarantine_name,
            )
        except OSError as rename_exc:
            try:
                current = os.stat(
                    run_id,
                    dir_fd=run_root_fd,
                    follow_symlinks=False,
                )
            except FileNotFoundError as exc:
                raise PromoteError(
                    "promoted run disappeared after failed quarantine rename"
                ) from exc
            if (
                stat.S_ISLNK(current.st_mode)
                or not stat.S_ISDIR(current.st_mode)
                or (current.st_dev, current.st_ino) != original_identity
            ):
                raise PromoteError(
                    "promoted run identity changed during quarantine rename"
                ) from rename_exc
            raise PromoteError(
                "promoted run atomic quarantine rename failed; exact run left visible"
            ) from rename_exc

        quarantined = os.stat(
            quarantine_name,
            dir_fd=staging_fd,
            follow_symlinks=False,
        )
        if (
            stat.S_ISLNK(quarantined.st_mode)
            or not stat.S_ISDIR(quarantined.st_mode)
            or (quarantined.st_dev, quarantined.st_ino) != original_identity
        ):
            raise PromoteError("quarantined run identity mismatch after rename")
        try:
            os.stat(run_id, dir_fd=run_root_fd, follow_symlinks=False)
        except FileNotFoundError:
            pass
        else:
            raise PromoteError("promoted run quarantine left a visible run path")
        visible = quarantine.lstat()
        if (visible.st_dev, visible.st_ino) != original_identity:
            raise PromoteError(
                "quarantined run path identity mismatch after rename"
            )
        return quarantine
    finally:
        if staging_fd is not None:
            os.close(staging_fd)
        os.close(run_root_fd)


_DEFAULT_METADATA = {
    "strategy_name": "IDE 策略",
    "market": "crypto_perp",
    "frequency": "1d",
    "benchmark": "BTC-USDT",
}


def promote_ide_run(
    *,
    ide_run_id: str,
    owner_username: str,
    owner_user_id: str | None = None,
    strategy_name: str,
    strategy_code: str,
    result: dict[str, Any],
    record_name: str | None = None,
    run_root: Path = RUN_ROOT,
    ledger: Any = None,
    returns_store: Any = None,
    extra_metadata: dict[str, Any] | None = None,
    execution_blocks: list[dict[str, Any]] | None = None,
    registry: Any = None,
    producer_status: Any = None,
    market_data_use_validation_refs: Sequence[str] = (),
    llm_call_record_store: Any = None,
    rdp_package_id: str | None = None,
    rdp_store: Any = None,
    reproduction_receipt_store: Any = None,
    require_reproduction_receipt: bool = False,
    attach_advisory_rdp: bool = False,
    requested_label: str = "exploratory",
    promotion_evidence_resolver: Any = None,
    promotion_receipt_registry: Any = None,
    canonical_overfit_registry: Any = None,
    promotion_precommit_hook: Callable[[PromotedRun], Any] | None = None,
    promotion_precommit_compensator: (
        Callable[[PromotedRun, Any], None] | None
    ) = None,
) -> PromotedRun:
    """把 IDE 沙箱结果落到 runs/<id>/，跑 metrics，返回新 run_id。

    raises PromoteError 当 result 不含可识别的 equity_curve。

    T-015 接线（**opt-in，向后兼容**）：传入 `ledger`（T-013 一本账）时跑多证据三角 gate，
    把 dsr/pbo/bootstrap 注入 metrics（让 risk_summary 守门规则从死接活）并把 gate_verdict 写进
    run.json。不传 → 行为与既有完全一致（不记账、不跑 gate）。

    M1 诚实接线（**opt-in，向后兼容**）：传入 `extra_metadata`（如 agent 组装的
    factor_set/model_id/signal_id/portfolio_id/cost_preset）时原样写进 run.json 的
    `assembly_inputs`——让组装意图可追溯、不被静默丢弃。不传 → 不写该键，行为与既有一致。

    §16 执行诚实接线（**opt-in，向后兼容**）：传入 `execution_blocks`（调用方按【真实执行诚实】
    构造的块字典：`mode`∈live/mock/fallback/template + `result_grade` + 诚实标识 mock_marked/
    live_source_ref/fallback_reason/note）时原样写进 run.json 的 `execution_blocks`，供
    `release_gate.promote_assembler` 组装→`evaluate_release` 的 Mock 诚实门核查（§16 致命
    「未注入资产却声称已采用 / template false success」在此被 R4/R5 抓）。不传 → 不写该键、
    行为与既有一致。本函数仅诚实【落数据】，绝不重造分类/判定（单一源 = mock_honesty + evaluate_release）。

    SA-3 promote 门链接线：manifest 组装后、run.json 落盘前，经
    `release_gate.gate_registry.ensure_default_chain()` 把已落地的 §6/§9/§10/§13/§16/§17 check 在
    **真 promote 路径**上跑一次，裁决落进 run.json 的 `promote_gate_chain`。只有组装器从 canonical
    typed inputs 发出的 section 才能生成 producer 绿灯；沙箱 result/metadata 不具备造证据权限。
    没有 canonical 输入时，相关门保持 advisory，并把缺口写入 manifest。

    正式重现闸：任何携带 ``rdp_package_id`` 的晋级都必须从可信 verifier-backed store
    取得当前、内容绑定的 ReproductionReceipt。调用方也可显式设置
    ``require_reproduction_receipt=True``，使缺 RDP 的正式入口在任何副作用前拒绝。未设置该标志且
    未携带 RDP 的调用只保留为旧的 unverified candidate materialization；composition root 不得把它
    暴露为正式晋级成功。
    """

    if not isinstance(requested_label, str):
        raise PromoteError("requested_label must be a string promotion label")
    normalized_requested_label = requested_label.strip()
    if normalized_requested_label not in PROMOTION_LABELS:
        raise PromoteError(
            f"requested_label must be one of {sorted(PROMOTION_LABELS)}"
        )
    if promotion_receipt_registry is not None and (
        not callable(promotion_precommit_hook)
        or not callable(promotion_precommit_compensator)
    ):
        raise PromoteError(
            "durable promotion verification requires QRO precommit hook and "
            "compensator"
        )

    equity_curve = result.get("equity_curve")
    if not isinstance(equity_curve, list) or len(equity_curve) < 2:
        raise PromoteError("emit_result 必须包含 equity_curve 数组（至少 2 个点）")

    rows = _normalize_equity_curve(equity_curve)
    if len(rows) < 2:
        raise PromoteError("equity_curve 解析后有效点不足 2 个")
    attribution_bytes: bytes | None = None
    if "attribution" in result:
        try:
            attribution_bytes = canonical_attribution_csv_bytes(
                result.get("attribution")
            )
        except BacktestArtifactResolutionError as exc:
            raise PromoteError(str(exc)) from exc
    generated_artifact_payloads: dict[str, bytes] = {
        "portfolio.csv": _portfolio_csv_bytes(rows),
    }
    trades_payload = _trades_csv_bytes(result.get("trades", ()))
    if trades_payload is not None:
        generated_artifact_payloads["trades.csv"] = trades_payload
    if attribution_bytes is not None:
        generated_artifact_payloads["attribution.csv"] = attribution_bytes
    if strategy_code:
        generated_artifact_payloads["strategy.py"] = strategy_code.encode("utf-8")

    metadata = _merge_metadata(result.get("metadata"))
    normalized_owner_user_id = str(owner_user_id or "").strip()
    run_id = _make_run_id(owner_username, strategy_name)
    run_dir = run_root / run_id

    metrics = _compute_metrics(rows)

    gate_verdict: dict | None = None
    source_result_content_hash = content_hash(result)

    manifest = {
        "run_id": run_id,
        "strategy_id": f"ide_{owner_username}",
        "strategy_name": strategy_name,
        "started_at": rows[0]["timestamp"],
        "status": "completed",
        "record_name": record_name or f"{strategy_name} · IDE 沙箱",
        "market": metadata["market"],
        "frequency": metadata["frequency"],
        "benchmark": metadata["benchmark"],
        "requested_label": normalized_requested_label,
        "metrics": metrics,
        "source": {
            "kind": "ide_sandbox",
            "ide_run_id": ide_run_id,
            "owner_username": owner_username,
            **(
                {"owner_user_id": normalized_owner_user_id}
                if normalized_owner_user_id
                else {}
            ),
            "result_content_hash": source_result_content_hash,
        },
    }
    manifest[GENERATED_ARTIFACT_INVENTORY_KEY] = {
        artifact_name: {
            "size_bytes": len(payload),
            "sha256": hashlib.sha256(payload).hexdigest(),
        }
        for artifact_name, payload in generated_artifact_payloads.items()
    }
    # M1：落 agent 组装意图（factor_set/model_id/...）于 run.json，使其可追溯、不静默丢弃。
    if extra_metadata:
        manifest["assembly_inputs"] = dict(extra_metadata)
    # §16：落【真实执行诚实】块（live/mock/fallback/template + result_grade）于 run.json，让
    # release_gate.promote_assembler 组装→evaluate_release 能抓「未注入资产却声称已采用 / 模板基线
    # 冒充生产」。纯透传（与 assembly_inputs 同范式·不分类不判定）；不传 → 不写该键、行为不变。
    if execution_blocks:
        manifest["execution_blocks"] = [dict(b) for b in execution_blocks]
    if market_data_use_validation_refs:
        manifest["market_data_use_validation_refs"] = [str(ref) for ref in market_data_use_validation_refs]

    llm_call_records = _resolve_llm_call_records(
        llm_call_record_store,
        refs=(run_id, ide_run_id, f"ide_run:{ide_run_id}", f"strategy:{strategy_name}"),
        owner_user_id=normalized_owner_user_id,
    )
    llm_gateway_secret: bytes | None = None
    if llm_call_records:
        secret = getattr(llm_call_record_store, "seal_secret", None)
        if not isinstance(secret, bytes) or len(secret) < 32:
            raise PromoteError(
                "llm_call_record_store with matching rows must expose its in-memory seal_secret"
            )
        llm_gateway_secret = secret
        manifest["llm_call_record_refs"] = [record.call_id for record in llm_call_records if record.call_id]

    resolved_rdp = None
    rdp_promotion = None
    normalized_rdp_package_id = str(rdp_package_id or "").strip()
    formal_reproduction_required = bool(
        require_reproduction_receipt or promotion_receipt_registry is not None
    )
    if formal_reproduction_required and not normalized_rdp_package_id:
        raise PromoteError(
            "formal IDE promotion requires rdp_package_id"
        )
    if normalized_rdp_package_id:
        if rdp_store is None or not hasattr(rdp_store, "manifest"):
            raise PromoteError("rdp_package_id requires a canonical persisted RDP store")
        if not normalized_owner_user_id:
            raise PromoteError("rdp_package_id requires stable owner_user_id")
        try:
            resolved_rdp = rdp_store.manifest(
                normalized_rdp_package_id,
                owner_user_id=normalized_owner_user_id,
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise PromoteError("rdp_package_id does not resolve to a persisted canonical manifest") from exc
        from ..delivery.rdp import PromotionClaim, RDPManifest

        if not isinstance(resolved_rdp, RDPManifest):
            raise PromoteError("persisted rdp_package_id did not resolve to canonical RDPManifest")
        if resolved_rdp.package_id != normalized_rdp_package_id:
            raise PromoteError("persisted RDP identity does not match rdp_package_id")
        expected_rdp_asset_ref = f"ide_run:{ide_run_id}"
        if resolved_rdp.asset_ref != expected_rdp_asset_ref:
            raise PromoteError(
                "persisted RDP asset_ref must bind the exact IDE source run "
                f"({expected_rdp_asset_ref})"
            )
        rdp_promotion = PromotionClaim(
            asset_ref=expected_rdp_asset_ref,
            asset_kind=resolved_rdp.asset_kind,
            rdp_ref=resolved_rdp.package_id,
            requested_stage="formal_run",
            actor=owner_username,
        )
        manifest["rdp_package_id"] = resolved_rdp.package_id

        # A documentation command is never authority.  Any path that supplies
        # an RDP is asserting formal §17 evidence and therefore must obtain a
        # fresh receipt from the concrete trusted-loader store before mutation.
        from ..research_os.rdp_reproduction import (
            PersistentRDPReproductionReceiptStore,
            reproduction_receipt_violations,
        )

        if not isinstance(
            reproduction_receipt_store,
            PersistentRDPReproductionReceiptStore,
        ):
            raise PromoteError(
                "formal IDE promotion requires the trusted RDP reproduction receipt store"
            )
        try:
            reproduction_receipt = reproduction_receipt_store.record_current(
                owner_user_id=normalized_owner_user_id,
                manifest=resolved_rdp,
                source_result_content_hash=source_result_content_hash,
            )
        except Exception as exc:  # noqa: BLE001 - unavailable/failed verification is red.
            raise PromoteError(
                "current RDP reproduction verification failed: "
                f"{type(exc).__name__}: {exc}"
            ) from exc
        receipt_violations = reproduction_receipt_violations(
            reproduction_receipt,
            manifest=resolved_rdp,
            owner_user_id=normalized_owner_user_id,
            source_result_content_hash=source_result_content_hash,
        )
        if receipt_violations:
            raise PromoteError(
                "current RDP reproduction receipt is invalid: "
                + "; ".join(receipt_violations)
            )
        manifest["rdp_reproduction_receipt"] = reproduction_receipt.to_open_dict()

    if promotion_receipt_registry is not None and (
        ledger is None or canonical_overfit_registry is None
    ):
        raise PromoteError(
            "durable promotion verification requires canonical overfit ledger and DatasetRegistry"
        )

    # Confirmatory overfit evidence is evaluated only after the owner RDP has
    # resolved, so a dataset mismatch cannot pollute the append-only ledger.
    if ledger is not None:
        if canonical_overfit_registry is not None:
            if resolved_rdp is None:
                raise PromoteError(
                    "canonical confirmatory overfit validation requires an owner RDP"
                )
            result_metadata = (
                result.get("metadata")
                if isinstance(result.get("metadata"), dict)
                else {}
            )
            dataset_version = str(
                result_metadata.get("dataset_version") or ""
            ).strip()
            if not dataset_version or dataset_version not in {
                str(ref) for ref in resolved_rdp.dataset_version_refs
            }:
                raise PromoteError(
                    "confirmatory dataset_version must exactly match an RDP dataset_version_ref"
                )
        try:
            gate_verdict = _run_overfit_gate(
                rows=rows,
                result=result,
                metadata=metadata,
                strategy_name=strategy_name,
                strategy_code=strategy_code,
                metrics=metrics,
                ledger=ledger,
                returns_store=returns_store,
                registry=canonical_overfit_registry if canonical_overfit_registry is not None else registry,
            )
        except Exception as exc:  # noqa: BLE001 - failed confirmatory evidence blocks promotion.
            raise PromoteError(
                f"confirmatory overfit validation failed: {type(exc).__name__}"
            ) from exc
        manifest["gate_verdict"] = gate_verdict

    promotion_evidence = None
    if promotion_evidence_resolver is not None:
        try:
            promotion_evidence = promotion_evidence_resolver.resolve(
                owner_user_id=normalized_owner_user_id,
                source_ide_run_id=ide_run_id,
                requested_label=normalized_requested_label,
                rdp=resolved_rdp,
                source_result_content_hash=(
                    source_result_content_hash
                    if promotion_receipt_registry is not None
                    else None
                ),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise PromoteError(
                f"canonical promote evidence resolution failed: {type(exc).__name__}"
            ) from exc
    elif resolved_rdp is not None:
        raise PromoteError(
            "rdp_package_id requires the canonical promotion evidence resolver"
        )

    # Sandbox result/metadata is caller-controlled output, not a canonical
    # evidence store. It may describe a run, but it cannot mint §6 bindings or
    # §10 methodology records. An RDP is emitted only after the supplied ID has
    # resolved through the canonical persisted store above.
    bridge_gaps: list[str] = []
    if gate_verdict is None:
        bridge_gaps.append("overfit:canonical confirmatory verdict absent")
    elif str(gate_verdict.get("color") or "") != "green":
        bridge_gaps.append(
            "overfit:canonical confirmatory verdict is not green"
        )
    if promotion_evidence is not None:
        bridge_gaps.extend(promotion_evidence.honest_gaps)
    else:
        bridge_gaps.extend(
            (
                "section6_mathchain:canonical resolver unavailable",
                "section9_boundary:canonical resolver unavailable",
                "section10:canonical resolver unavailable",
                "section13_trust:canonical resolver unavailable",
                "section16_engineering_standards:canonical resolver unavailable",
                "section17_rdp:canonical resolver unavailable",
            )
        )
    manifest["research_promote_bridge"] = {"honest_gaps": bridge_gaps}

    # —— §6/§10/§17 producer 接线（canonical typed records → run manifest）——
    # §17 may be resolved from its persisted canonical ID above. §6/§10 remain
    # honestly absent until their canonical registries are wired. Assembly
    # failure is fail-closed; evidence boundaries cannot be skipped.
    try:
        from ..release_gate.promote_assembler import assemble_promote_sections

        # §17 advisory-first producer (opt-in · reversible · require_rdp stays False,
        # producer stays non-green): with no persisted canonical RDP, assemble a
        # transparent advisory RDP from the chain artifacts genuinely in scope
        # (run identity + result artifact + any resolved LLMCallRecords) and feed it
        # into the existing honest-empty §17 seam. SA-2 keeps the section advisory
        # (producer not green), so its honest gaps record but never block. Default
        # (flag off) leaves the no-RDP path byte-identical to the prior baseline.
        section_rdp = resolved_rdp
        advisory_rdp_assembly = None
        if section_rdp is None and attach_advisory_rdp:
            from .promotion_evidence import assemble_advisory_rdp

            advisory_rdp_assembly = assemble_advisory_rdp(
                asset_ref=run_id,
                source_ref=f"ide_run:{ide_run_id}",
                artifact=result,
                created_by=owner_username,
                llm_call_records=llm_call_records,
            )
            if advisory_rdp_assembly is not None:
                section_rdp = advisory_rdp_assembly.rdp
                manifest["section17_rdp_advisory"] = {
                    "ok": advisory_rdp_assembly.ok,
                    "honest_gaps": list(advisory_rdp_assembly.honest_gaps),
                    "rejections": [
                        {"gate_id": o.gate_id, "missing": list(o.missing)}
                        for o in advisory_rdp_assembly.validation.rejections
                    ],
                    "note": (
                        "advisory-only §17 RDP: require_rdp=False 且 "
                        "s17_rdp_runjson_producers 未转绿——仅透明披露、不强制 gate"
                        "（enforcement 待用户拍 D-SCOPE-CONSERVATIVE）"
                    ),
                }

        section_assembly = assemble_promote_sections(
            manifest,
            mathchain_claims=(
                promotion_evidence.mathchain_claims
                if promotion_evidence is not None
                else ()
            ),
            factor_library_entries=(
                promotion_evidence.factor_library_entries
                if promotion_evidence is not None
                else ()
            ),
            factor_generators=(
                promotion_evidence.factor_generators
                if promotion_evidence is not None
                else ()
            ),
            signal_protocols=(
                promotion_evidence.signal_protocols
                if promotion_evidence is not None
                else ()
            ),
            strategy_books=(
                promotion_evidence.strategy_books
                if promotion_evidence is not None
                else ()
            ),
            validation_methodologies=(
                promotion_evidence.validation_methodologies
                if promotion_evidence is not None
                else ()
            ),
            validation_depths=(
                promotion_evidence.validation_depths
                if promotion_evidence is not None
                else ()
            ),
            tier_claims=(
                promotion_evidence.tier_claims
                if promotion_evidence is not None
                else ()
            ),
            rdp=section_rdp,
            promotion=rdp_promotion,
            expert_reviews=(
                promotion_evidence.expert_reviews
                if promotion_evidence is not None
                else ()
            ),
            release_gates=(
                promotion_evidence.release_gates
                if promotion_evidence is not None
                else ()
            ),
            release_checks=(
                promotion_evidence.release_checks
                if promotion_evidence is not None
                else ()
            ),
            pressure_runs=(
                promotion_evidence.pressure_runs
                if promotion_evidence is not None
                else ()
            ),
            release_approvals=(
                promotion_evidence.release_approvals
                if promotion_evidence is not None
                else ()
            ),
            mock_records=(
                promotion_evidence.mock_records
                if promotion_evidence is not None
                else ()
            ),
            data_updates=(
                promotion_evidence.data_updates
                if promotion_evidence is not None
                else ()
            ),
            llm_calls=(
                promotion_evidence.llm_calls
                if promotion_evidence is not None
                else ()
            ),
            theory_claims=(
                promotion_evidence.theory_claims
                if promotion_evidence is not None
                else ()
            ),
            fatal_records=(
                promotion_evidence.fatal_records
                if promotion_evidence is not None
                else ()
            ),
            performance_records=(
                promotion_evidence.performance_records
                if promotion_evidence is not None
                else ()
            ),
            verified_producer_keys=(
                promotion_evidence.verified_producer_keys
                if promotion_evidence is not None
                else ()
            ),
        )
        manifest = section_assembly.apply_to(manifest)
        manifest["section_assembly"] = {
            "emitted": list(section_assembly.emitted),
            "absent": list(section_assembly.absent),
            "honest_gaps": list(section_assembly.honest_gaps),
        }
        if promotion_receipt_registry is not None:
            producer_status = section_assembly.producer_status()
        elif producer_status is None and section_assembly.verified_producer_keys:
            producer_status = section_assembly.producer_status()
    except Exception as exc:  # noqa: BLE001 - assembly failure blocks promotion.
        raise PromoteError(f"promote 证据组装失败，拒绝晋级: {type(exc).__name__}") from exc

    # Evaluate release only after canonical section assembly, so §6/§17 inputs
    # and their honest residuals are visible to the release gate.
    try:
        from ..release_gate.promote_assembler import evaluate_run_releasable

        release_evaluation = evaluate_run_releasable(
            manifest,
            owner_user_id=normalized_owner_user_id,
            llm_used=True if llm_call_records else None,
            llm_call_records=llm_call_records or None,
            gateway_secret=llm_gateway_secret,
        ).to_dict()
        unresolved_release_inputs = list(manifest["research_promote_bridge"]["honest_gaps"])
        release_honest_gaps = release_evaluation.get("honest_gaps", ())
        if isinstance(release_honest_gaps, (tuple, list)):
            unresolved_release_inputs.extend(
                str(item) for item in release_honest_gaps if str(item)
            )
        elif release_honest_gaps:
            raise ValueError("release evaluation honest_gaps is malformed")
        unresolved_release_inputs = list(dict.fromkeys(unresolved_release_inputs))
        gate_evaluation_ok = bool(release_evaluation.get("ok"))
        release_ready = gate_evaluation_ok and not unresolved_release_inputs
        manifest["release_verdict"] = {
            **release_evaluation,
            "gate_evaluation_ok": gate_evaluation_ok,
            "ok": release_ready,
            "release_ready": release_ready,
            "readiness": "ready" if release_ready else "unverified",
            "unresolved_required_inputs": unresolved_release_inputs,
            "reason": (
                "release gates rejected the candidate"
                if not gate_evaluation_ok
                else "canonical promote evidence retains unresolved required inputs"
            ),
        }
    except Exception as exc:  # noqa: BLE001 - an unevaluated release cannot be promoted.
        raise PromoteError(f"release 自检失败，拒绝晋级: {type(exc).__name__}") from exc

    # —— SA-3 promote 门链（中心串行·advisory-first·construction-map §4.D）——
    # 把已落地的 §6/§9/§10/§13/§16/§17 checks 经 default_chain 在**真 promote 路径**上跑一次，裁决
    # 落进 run.json 的 `promote_gate_chain`。本轮真实 emitted section 的 producer 由组装器自动标绿，对应门
    # 翻 enforce；未 emitted 的门保持红灯 advisory，继续不误拒 honest-absent。注册收口单一在
    # release_gate.gate_registry（加新门 = 那里加一行·本文件一字不动）。
    # 门链不可执行即 fail-closed；“未评估”不能授权晋级。
    chain_result = None
    try:
        from ..release_gate.gate_registry import ensure_default_chain

        chain = (
            ensure_default_chain(
                reproduction_receipt_store=reproduction_receipt_store
            )
            if resolved_rdp is not None
            else ensure_default_chain()
        )
        chain_result = chain.evaluate(manifest, producer_status=producer_status)
        chain_payload = chain_result.to_dict()
        all_producers_green = bool(chain_payload.get("verdicts")) and all(
            bool(verdict.get("producer_green"))
            for verdict in chain_payload.get("verdicts", ())
            if isinstance(verdict, dict)
        )
        chain_payload["all_registered_producers_green"] = all_producers_green
        chain_payload["release_ready"] = bool(
            not chain_result.rejected
            and all_producers_green
            and manifest["release_verdict"].get("release_ready")
        )
        manifest["promote_gate_chain"] = chain_payload
    except Exception as exc:  # noqa: BLE001 - unevaluated gates cannot authorize promotion.
        raise PromoteError(f"promote 门链执行失败，拒绝晋级: {type(exc).__name__}") from exc

    # enforce 门未过 → 拒晋级。advisory-only 时 rejected 恒 False·此分支不触发（纯记录）。在写 run.json
    # **前**拒：被门链拒的晋级绝不落 run.json（不冒充成功 run·RunDetail 也就不会列出它）。
    if chain_result is not None and chain_result.rejected:
        raise PromoteError(f"promote 门链拒绝晋级（enforce 门未过·SA-3）: {chain_result.reason_text}")
    if promotion_receipt_registry is not None and not bool(
        manifest.get("promote_gate_chain", {}).get("release_ready")
    ):
        raise PromoteError(
            "durable promotion verification requires every registered gate and release verdict to be ready"
        )

    # Build one no-follow hidden candidate. Formal promotion verifies and
    # durably appends its receipt while the candidate remains below .staging;
    # only that authority commit permits the atomic rename into the public root.
    try:
        run_root.lstat()
    except FileNotFoundError:
        try:
            run_root.mkdir(parents=True, exist_ok=False)
        except FileExistsError:
            pass
    run_root_fd, _run_root_stat = _open_bound_directory(
        run_root,
        label="promotion run root",
    )
    staging_fd: int | None = None
    candidate_fd: int | None = None
    promotion_receipt_ref: str | None = None
    try:
        staging_fd, _staging_stat = _open_bound_child_directory(
            run_root_fd,
            ".staging",
            label="promotion staging root",
            create=True,
        )
        candidate_name = f"{run_id}.pending.{token_urlsafe(16)}"
        os.mkdir(candidate_name, mode=0o700, dir_fd=staging_fd)
        candidate_stat = os.stat(
            candidate_name,
            dir_fd=staging_fd,
            follow_symlinks=False,
        )
        candidate_identity = (candidate_stat.st_dev, candidate_stat.st_ino)
        try:
            candidate_fd = os.open(
                candidate_name,
                _directory_flags(),
                dir_fd=staging_fd,
            )
            opened_candidate = os.fstat(candidate_fd)
            if (
                not stat.S_ISDIR(opened_candidate.st_mode)
                or (opened_candidate.st_dev, opened_candidate.st_ino)
                != candidate_identity
            ):
                raise PromoteError(
                    "promotion candidate identity changed while opening"
                )

            for artifact_name, payload in generated_artifact_payloads.items():
                _write_new_bytes_at(
                    candidate_fd,
                    artifact_name,
                    payload,
                )
            manifest_bytes = json.dumps(
                manifest,
                ensure_ascii=False,
                indent=2,
            ).encode("utf-8")
            _write_new_bytes_at(candidate_fd, "run.json", manifest_bytes)
            os.fsync(candidate_fd)

            candidate_proof = PromotionCandidateProof(
                staging_name=candidate_name,
                st_dev=candidate_identity[0],
                st_ino=candidate_identity[1],
                run_manifest_sha256=hashlib.sha256(manifest_bytes).hexdigest(),
            )
            staged_run_dir = run_root / ".staging" / candidate_name
            pending_promoted = PromotedRun(
                run_id=run_id,
                run_dir=staged_run_dir,
                metrics=metrics,
                gate_verdict=gate_verdict,
                requested_label=normalized_requested_label,
            )
        except Exception as exc:
            try:
                _rename_hidden_candidate_for_audit(
                    staging_fd,
                    candidate_name=candidate_name,
                    candidate_identity=candidate_identity,
                    phase="construction_failed",
                )
            except Exception as containment_exc:
                raise PromoteCommitError(
                    "promotion candidate construction failed and exact audit "
                    "containment failed: "
                    f"construction={type(exc).__name__}; "
                    f"containment={type(containment_exc).__name__}"
                ) from containment_exc
            raise
        except BaseException as crash:
            try:
                _rename_hidden_candidate_for_audit(
                    staging_fd,
                    candidate_name=candidate_name,
                    candidate_identity=candidate_identity,
                    phase="construction_failed",
                )
            except BaseException as containment_exc:
                crash.add_note(
                    "promotion candidate construction BaseException exact audit "
                    "containment failed: "
                    f"{type(containment_exc).__name__}"
                )
            raise

        if promotion_receipt_registry is None:
            _publish_hidden_candidate(
                run_root_fd=run_root_fd,
                staging_fd=staging_fd,
                candidate_name=candidate_name,
                run_id=run_id,
                candidate_identity=candidate_identity,
            )
        else:
            identities = {
                "owner_user_id": normalized_owner_user_id,
                "source_ide_run_id": ide_run_id,
                "promoted_run_id": run_id,
                "rdp_package_id": normalized_rdp_package_id,
                "requested_label": normalized_requested_label,
            }
            raw_precommit_result: Any = None
            precommit_result: dict[str, str] | None = None
            precommit_attempted = False
            receipt_record_attempted = False
            publish_attempted = False
            final_validation_attempted = False
            published = False
            try:
                prepare_candidate = getattr(
                    promotion_receipt_registry,
                    "prepare_candidate_current",
                    None,
                )
                record_candidate = getattr(
                    promotion_receipt_registry,
                    "record_candidate_current",
                    None,
                )
                if not callable(prepare_candidate) or not callable(record_candidate):
                    raise TypeError(
                        "promotion receipt registry requires hidden candidate APIs"
                    )
                preview = prepare_candidate(
                    **identities,
                    candidate=candidate_proof,
                )
                pending_promoted = PromotedRun(
                    run_id=run_id,
                    run_dir=staged_run_dir,
                    metrics=metrics,
                    gate_verdict=gate_verdict,
                    promotion_receipt_ref=str(preview.receipt_ref),
                    requested_label=normalized_requested_label,
                )
                precommit_attempted = True
                raw_precommit_result = promotion_precommit_hook(pending_promoted)
                precommit_result = _validated_promotion_precommit_result(
                    raw_precommit_result
                )
                receipt_record_attempted = True
                receipt = record_candidate(
                    **identities,
                    candidate=candidate_proof,
                )
                if str(receipt.receipt_ref) != str(preview.receipt_ref):
                    raise ValueError(
                        "promotion receipt changed between candidate preview and commit"
                    )
                promotion_receipt_ref = str(receipt.receipt_ref)
                publish_attempted = True
                _publish_hidden_candidate(
                    run_root_fd=run_root_fd,
                    staging_fd=staging_fd,
                    candidate_name=candidate_name,
                    run_id=run_id,
                    candidate_identity=candidate_identity,
                )
                published = True
                final_validation_attempted = True
                decision = promotion_receipt_registry.validate_current(
                    promotion_receipt_ref,
                    **identities,
                )
                if getattr(decision, "accepted", False) is not True:
                    codes = tuple(
                        str(getattr(item, "code", "unknown"))
                        for item in tuple(getattr(decision, "violations", ()) or ())
                    )
                    raise ValueError(
                        "final promotion receipt validation failed: "
                        + ",".join(codes or ("unknown",))
                    )
            except Exception as exc:  # noqa: BLE001 - authority failures stay hidden/red.
                containment_error: Exception | None = None
                if published:
                    try:
                        quarantine_promoted_run(
                            PromotedRun(
                                run_id=run_id,
                                run_dir=run_dir,
                                metrics=metrics,
                                gate_verdict=gate_verdict,
                                promotion_receipt_ref=promotion_receipt_ref,
                                requested_label=normalized_requested_label,
                            ),
                            phase="postcommit_validation_failed",
                            expected_run_root=run_root,
                        )
                    except Exception as quarantine_exc:  # noqa: BLE001
                        containment_error = quarantine_exc
                else:
                    try:
                        try:
                            current_candidate = os.stat(
                                candidate_name,
                                dir_fd=staging_fd,
                                follow_symlinks=False,
                            )
                        except FileNotFoundError:
                            final_after_failed_publish = os.stat(
                                run_id,
                                dir_fd=run_root_fd,
                                follow_symlinks=False,
                            )
                            if (
                                stat.S_ISLNK(final_after_failed_publish.st_mode)
                                or not stat.S_ISDIR(
                                    final_after_failed_publish.st_mode
                                )
                                or (
                                    final_after_failed_publish.st_dev,
                                    final_after_failed_publish.st_ino,
                                )
                                != candidate_identity
                            ):
                                raise PromoteError(
                                    "promotion final identity changed after publish failure"
                                )
                            quarantine_promoted_run(
                                PromotedRun(
                                    run_id=run_id,
                                    run_dir=run_dir,
                                    metrics=metrics,
                                    gate_verdict=gate_verdict,
                                    promotion_receipt_ref=promotion_receipt_ref,
                                    requested_label=normalized_requested_label,
                                ),
                                phase="postcommit_validation_failed",
                                expected_run_root=run_root,
                            )
                        else:
                            if (
                                stat.S_ISLNK(current_candidate.st_mode)
                                or not stat.S_ISDIR(current_candidate.st_mode)
                                or (
                                    current_candidate.st_dev,
                                    current_candidate.st_ino,
                                )
                                != candidate_identity
                            ):
                                raise PromoteError(
                                    "hidden promotion candidate identity changed after failure"
                                )
                            _rename_hidden_candidate_for_audit(
                                staging_fd,
                                candidate_name=candidate_name,
                                candidate_identity=candidate_identity,
                                phase="receipt_failed",
                            )
                    except Exception as audit_exc:  # noqa: BLE001
                        containment_error = audit_exc

                compensation_error: Exception | None = None
                if precommit_attempted and promotion_precommit_compensator is not None:
                    try:
                        promotion_precommit_compensator(
                            pending_promoted,
                            precommit_result
                            if precommit_result is not None
                            else raw_precommit_result,
                        )
                    except Exception as compensation_exc:  # noqa: BLE001
                        compensation_error = compensation_exc
                if containment_error is not None:
                    raise PromoteCommitError(
                        "durable promotion failed and artifact containment failed: "
                        f"commit={type(exc).__name__}; "
                        f"containment={type(containment_error).__name__}"
                    ) from containment_error
                if compensation_error is not None:
                    raise PromoteCommitError(
                        "durable promotion failed and precommit compensation failed: "
                        f"commit={type(exc).__name__}; "
                        f"compensation={type(compensation_error).__name__}"
                    ) from compensation_error
                raise PromoteCommitError(
                    f"durable promotion verification failed: {type(exc).__name__}"
                ) from exc
            except BaseException as crash:
                # A hook or append API can durably write its prefix and then
                # raise KeyboardInterrupt/SystemExit (or another non-Exception
                # boundary).  Best-effort cleanup covers the complete formal
                # transaction, but the original BaseException is always
                # re-raised unchanged.
                current_final_is_legitimate = False
                containment_error: BaseException | None = None
                try:
                    try:
                        candidate_after_crash = os.stat(
                            candidate_name,
                            dir_fd=staging_fd,
                            follow_symlinks=False,
                        )
                    except FileNotFoundError:
                        candidate_after_crash = None
                    if candidate_after_crash is not None and (
                        stat.S_ISLNK(candidate_after_crash.st_mode)
                        or not stat.S_ISDIR(candidate_after_crash.st_mode)
                        or (
                            candidate_after_crash.st_dev,
                            candidate_after_crash.st_ino,
                        )
                        != candidate_identity
                    ):
                        raise PromoteError(
                            "promotion candidate identity changed after BaseException"
                        )

                    try:
                        final_after_crash = os.stat(
                            run_id,
                            dir_fd=run_root_fd,
                            follow_symlinks=False,
                        )
                    except FileNotFoundError:
                        final_after_crash = None
                    if final_after_crash is not None and (
                        stat.S_ISLNK(final_after_crash.st_mode)
                        or not stat.S_ISDIR(final_after_crash.st_mode)
                        or (
                            final_after_crash.st_dev,
                            final_after_crash.st_ino,
                        )
                        != candidate_identity
                    ):
                        raise PromoteError(
                            "promotion final identity changed after BaseException"
                        )
                    if (
                        candidate_after_crash is not None
                        and final_after_crash is not None
                    ):
                        raise PromoteError(
                            "promotion candidate exists in staging and final after BaseException"
                        )

                    if final_after_crash is not None:
                        recovery_receipt_ref = str(
                            promotion_receipt_ref
                            or pending_promoted.promotion_receipt_ref
                            or ""
                        ).strip()
                        if recovery_receipt_ref and receipt_record_attempted:
                            try:
                                recovered_decision = (
                                    promotion_receipt_registry.validate_current(
                                        recovery_receipt_ref,
                                        **identities,
                                    )
                                )
                                current_final_is_legitimate = (
                                    getattr(
                                        recovered_decision,
                                        "accepted",
                                        False,
                                    )
                                    is True
                                )
                            except BaseException as verification_crash:
                                crash.add_note(
                                    "BaseException recovery current validation failed: "
                                    f"{type(verification_crash).__name__}"
                                )
                        if not current_final_is_legitimate:
                            quarantine_promoted_run(
                                PromotedRun(
                                    run_id=run_id,
                                    run_dir=run_dir,
                                    metrics=metrics,
                                    gate_verdict=gate_verdict,
                                    promotion_receipt_ref=(
                                        recovery_receipt_ref or None
                                    ),
                                    requested_label=normalized_requested_label,
                                ),
                                phase="postcommit_validation_failed",
                                expected_run_root=run_root,
                            )
                    elif candidate_after_crash is not None:
                        _rename_hidden_candidate_for_audit(
                            staging_fd,
                            candidate_name=candidate_name,
                            candidate_identity=candidate_identity,
                            phase="receipt_failed",
                        )
                    else:
                        raise PromoteError(
                            "promotion candidate disappeared after BaseException"
                        )
                except BaseException as cleanup_exc:
                    containment_error = cleanup_exc

                if (
                    not current_final_is_legitimate
                    and precommit_attempted
                    and promotion_precommit_compensator is not None
                ):
                    try:
                        promotion_precommit_compensator(
                            pending_promoted,
                            precommit_result
                            if precommit_result is not None
                            else raw_precommit_result,
                        )
                    except BaseException as compensation_exc:
                        crash.add_note(
                            "BaseException precommit compensation failed: "
                            f"{type(compensation_exc).__name__}"
                        )
                if containment_error is not None:
                    crash.add_note(
                        "BaseException artifact containment failed: "
                        f"{type(containment_error).__name__}"
                    )
                crash.add_note(
                    "formal promotion stage flags: "
                    f"precommit={precommit_attempted},"
                    f"receipt={receipt_record_attempted},"
                    f"publish={publish_attempted},"
                    f"final_validation={final_validation_attempted}"
                )
                raise
    finally:
        if candidate_fd is not None:
            os.close(candidate_fd)
        if staging_fd is not None:
            os.close(staging_fd)
        os.close(run_root_fd)

    return PromotedRun(
        run_id=run_id,
        run_dir=run_dir,
        metrics=metrics,
        gate_verdict=gate_verdict,
        promotion_receipt_ref=promotion_receipt_ref,
        requested_label=normalized_requested_label,
    )


def _resolve_llm_call_records(
    store: Any,
    *,
    refs: Iterable[str],
    owner_user_id: str,
) -> tuple[Any, ...]:
    """Resolve durable LLMCallRecord rows for any known run/correlation ref.

    Missing store or no matches means "no LLM call evidence", not "no LLM was used".
    """

    if store is None:
        return ()
    if not hasattr(store, "llm_records_for"):
        raise PromoteError("llm_call_record_store must expose owner-scoped llm_records_for")
    owner = str(owner_user_id or "").strip()
    if not owner:
        raise PromoteError("llm_call_record_store requires stable owner_user_id")
    by_call_id: dict[str, Any] = {}
    for ref in refs:
        rows = store.llm_records_for(str(ref), owner_user_id=owner)
        for row in rows:
            call_id = str(getattr(row, "call_id", "") or "")
            if call_id:
                by_call_id[call_id] = row
    return tuple(by_call_id.values())


def _run_overfit_gate(
    *, rows, result, metadata, strategy_name, strategy_code, metrics, ledger, returns_store,
    registry=None,
) -> dict:
    """记账 + 跑三角 gate + 把 dsr/pbo/bootstrap 注入 metrics（就地改 metrics dict）。

    `registry`（B-PIT-CONFIRMATORY）：透传给 evaluate_overfit_gate 的 confirmatory 数据身份门
    （record=True 入账前校验 dataset_version 注册身份 + PIT）；None=不强制（向后兼容）。"""

    from ..eval.gate_runner import asset_class_of, evaluate_overfit_gate, freq_to_ppy

    meta = result.get("metadata") if isinstance(result.get("metadata"), dict) else {}
    returns = [r["net_return"] or 0.0 for r in rows]
    theme = (meta.get("research_theme_id") or strategy_name)
    # CPCV 路径稳健性 q05 接进 promote 真实路径（done 卡 89e7be1e 的最后一公里）：
    # emit 携带 cpcv_distribution（模型 train 的 per-path 分布）则透传给 gate；缺则 None（不编造·行为不变）。
    # cpcv_policy 从 emit metadata 读（默认 report_only 只附报告绝不改裁决——守不替方法学拍板；用户显式
    # cpcv_conservative 才允许脆弱分布 green→yellow advisory）。非法值回落 report_only。
    cpcv_distribution = result.get("cpcv_distribution")
    if not isinstance(cpcv_distribution, dict):
        m_cpcv = meta.get("cpcv_distribution")
        cpcv_distribution = m_cpcv if isinstance(m_cpcv, dict) else None
    cpcv_policy = meta.get("cpcv_policy") or "report_only"
    if cpcv_policy not in ("report_only", "cpcv_conservative"):
        cpcv_policy = "report_only"
    gr = evaluate_overfit_gate(
        returns=returns,
        factor=meta.get("factor_formula") or (strategy_code[:2000] if strategy_code else strategy_name),
        params=meta.get("params") or {},
        universe=metadata["market"],
        dataset_version=str(meta.get("dataset_version") or "unknown"),
        freq=metadata["frequency"],
        label=str(meta.get("label") or "net_return"),
        strategy_goal_ref=str(theme),
        asset_class=asset_class_of(metadata["market"]),
        periods_per_year=freq_to_ppy(metadata["frequency"]),
        ledger=ledger,
        returns_store=returns_store,
        cpcv_distribution=cpcv_distribution,
        cpcv_policy=cpcv_policy,
        record=True,
        registry=registry,
    )
    v = gr.verdict
    # 注入 → risk_summary._rule_dsr/_rule_pbo 真生效（活性证明）。insufficient 时不注入误导单点。
    if v.color != "insufficient_evidence":
        metrics["dsr"] = v.dsr_conservative
        if v.pbo is not None:
            metrics["pbo"] = v.pbo
        metrics["bootstrap_sharpe_lower"] = v.bootstrap_ci[0]
    gv = v.to_dict()
    gv["honest_n"] = gr.honest_n
    gv["config_hash"] = gr.config_hash
    return gv


# -------- helpers --------


def _make_run_id(owner: str, name: str) -> str:
    safe_owner = "".join(ch for ch in owner if ch.isalnum())[:16] or "u"
    safe_name = "".join(ch for ch in name if ch.isalnum() or ch in "-_")[:24] or "s"
    return f"ide_{safe_owner}_{safe_name}_{token_urlsafe(4)}"


def _merge_metadata(meta: Any) -> dict[str, str]:
    out = dict(_DEFAULT_METADATA)
    if isinstance(meta, dict):
        for k in _DEFAULT_METADATA:
            v = meta.get(k)
            if isinstance(v, str) and v.strip():
                out[k] = v.strip()
    return out


def _normalize_equity_curve(raw: list[Any]) -> list[dict[str, Any]]:
    """统一成 {timestamp, equity, net_return, benchmark_return, drawdown}。

    支持的输入点格式：
      {"t": ..., "equity": ...}
      {"timestamp": ..., "equity": ...}
      {"date": ..., "equity": ...}
      {"t": ..., "value": ...}
    """

    rows: list[dict[str, Any]] = []
    for i, p in enumerate(raw):
        if not isinstance(p, dict):
            continue
        ts = p.get("timestamp") or p.get("t") or p.get("date") or str(i)
        eq = p.get("equity")
        if eq is None:
            eq = p.get("value")
        try:
            eq_f = float(eq)
        except (TypeError, ValueError):
            continue
        if not math.isfinite(eq_f):
            continue
        rows.append({
            "timestamp": str(ts),
            "equity": eq_f,
            "net_return": _safe_float(p.get("net_return")),
            "benchmark_return": _safe_float(p.get("benchmark_return")),
            "drawdown": _safe_float(p.get("drawdown")),
        })

    if not rows:
        return rows

    # 计算缺省 net_return
    for i in range(1, len(rows)):
        if rows[i]["net_return"] is None:
            prev = rows[i - 1]["equity"]
            if prev:
                rows[i]["net_return"] = rows[i]["equity"] / prev - 1.0
    if rows[0]["net_return"] is None:
        rows[0]["net_return"] = 0.0

    # drawdown
    peak = rows[0]["equity"]
    for r in rows:
        peak = max(peak, r["equity"])
        if r["drawdown"] is None and peak:
            r["drawdown"] = r["equity"] / peak - 1.0

    return rows


def _safe_float(v: Any) -> float | None:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if math.isfinite(f) else None


def _portfolio_csv_bytes(rows: list[dict[str, Any]]) -> bytes:
    cols = ["timestamp", "equity", "net_return", "benchmark_return", "drawdown"]
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=cols, extrasaction="ignore")
    writer.writeheader()
    for row in rows:
        writer.writerow(
            {key: ("" if row.get(key) is None else row.get(key)) for key in cols}
        )
    return stream.getvalue().encode("utf-8-sig")


def _write_portfolio_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.write_bytes(_portfolio_csv_bytes(rows))


def _trades_csv_bytes(trades: list[Any]) -> bytes | None:
    cleaned = [t for t in trades if isinstance(t, dict)]
    if not cleaned:
        return None
    cols: list[str] = []
    for t in cleaned:
        for k in t.keys():
            if k not in cols:
                cols.append(k)
    if "timestamp" not in cols and "t" in cols:
        cols.insert(0, "timestamp")
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=cols, extrasaction="ignore")
    writer.writeheader()
    for trade in cleaned:
        if "timestamp" not in trade and "t" in trade:
            trade = {**trade, "timestamp": trade["t"]}
        writer.writerow(
            {key: ("" if trade.get(key) is None else trade.get(key)) for key in cols}
        )
    return stream.getvalue().encode("utf-8-sig")


def _write_trades_csv(path: Path, trades: list[Any]) -> None:
    payload = _trades_csv_bytes(trades)
    if payload is not None:
        path.write_bytes(payload)


def _compute_metrics(rows: list[dict[str, Any]]) -> dict[str, float]:
    """从 portfolio 序列计算 sharpe / sortino / max_dd / total_return / vol / alpha / beta。"""

    eq = [r["equity"] for r in rows]
    nr = [r["net_return"] or 0.0 for r in rows]
    br = [r["benchmark_return"] for r in rows]

    out: dict[str, float] = {}
    out["total_return"] = (eq[-1] / eq[0] - 1.0) if eq[0] else 0.0
    n = len(rows)
    if n > 1 and eq[0] > 0 and eq[-1] > 0:
        out["annualized_return"] = (eq[-1] / eq[0]) ** (252.0 / n) - 1.0
    out["trade_count"] = 0
    peak = eq[0]
    mdd = 0.0
    for v in eq:
        peak = max(peak, v)
        if peak:
            mdd = min(mdd, v / peak - 1.0)
    out["max_drawdown"] = mdd

    if len(nr) >= 2:
        sd = statistics.pstdev(nr)
        mu = statistics.mean(nr)
        out["volatility"] = sd * math.sqrt(252)
        out["sharpe"] = (mu / sd * math.sqrt(252)) if sd > 0 else 0.0
        downside = [x for x in nr if x < 0]
        if downside:
            dd = statistics.pstdev(downside)
            out["sortino"] = (mu / dd * math.sqrt(252)) if dd > 0 else 0.0
        else:
            out["sortino"] = 0.0

    valid_pairs = [(nr[i], br[i]) for i in range(n) if br[i] is not None]
    if len(valid_pairs) >= 5:
        sx = [p[1] for p in valid_pairs]
        sy = [p[0] for p in valid_pairs]
        mux, muy = statistics.mean(sx), statistics.mean(sy)
        cov = sum((sx[i] - mux) * (sy[i] - muy) for i in range(len(sx))) / len(sx)
        varx = sum((x - mux) ** 2 for x in sx) / len(sx)
        if varx > 0:
            beta = cov / varx
            alpha = (muy - beta * mux) * 252
            out["beta"] = beta
            out["alpha"] = alpha
        # information_ratio = mean(excess) / std(excess) * sqrt(252)
        ex = [sy[i] - sx[i] for i in range(len(sx))]
        if len(ex) >= 2:
            ed = statistics.pstdev(ex)
            em = statistics.mean(ex)
            out["information_ratio"] = (em / ed * math.sqrt(252)) if ed > 0 else 0.0
            bvol = statistics.pstdev(sx) * math.sqrt(252) if len(sx) >= 2 else 0.0
            out["benchmark_volatility"] = bvol
        # 基准累计收益
        w = 1.0
        for x in sx:
            w *= 1.0 + x
        out["benchmark_return"] = w - 1.0

    return out


__all__ = ["PromoteError", "PromotedRun", "promote_ide_run"]
