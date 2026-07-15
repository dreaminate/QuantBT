"""M3b · dataset_version (不可变) + freshness 探测 + GE-lite 规则。

参见 QuantBT-GOAL.md §M3 数据治理与 §6.2 数据质量。

设计：
- **dataset_version 不可变**：同一 `dataset_id` 可有多个 version，但每个 version
  一旦写入 registry 就不能再改。registry 落 `data/datasets/registry.jsonl`
  (append-only)；版本号用 ULID-like = `{utc-iso}__{sha256[:8]}`。
- **freshness**：给定 dataset_id 返回 (last_coverage_end, expected_end,
  staleness_seconds, status: green/yellow/red)。期望更新时间按 market：
  A股按交易日历的下一日，加密按当前 UTC（24/7 市场）。
- **GE-lite 规则**：5 类轻量规则（不引入 great_expectations 依赖）：
  not_null / unique / monotonic / value_range / foreign_key。
"""

from __future__ import annotations

import dataclasses
import json
import os
import re
import threading
from collections.abc import Iterable
from dataclasses import asdict, dataclass, field, fields as _dc_fields
from datetime import UTC, datetime, time, timedelta
from pathlib import Path
from typing import Any, Literal

import polars as pl

from .connectors.base import FetchResult

# manifest 落点的 dataset_id 目录名清洗（version_id 自身已是 fs-safe）。
_SAFE_PATH = re.compile(r"[^A-Za-z0-9._-]+")


GE_RuleType = Literal["not_null", "unique", "monotonic", "value_range", "foreign_key"]
FreshnessStatus = Literal["green", "yellow", "red", "unknown"]


@dataclass
class GERule:
    column: str
    rule_type: GE_RuleType
    params: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "GERule":
        return cls(column=data["column"], rule_type=data["rule_type"], params=data.get("params") or {})


@dataclass
class GECheckResult:
    column: str
    rule_type: GE_RuleType
    passed: bool
    failed_count: int
    message: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def run_ge_checks(
    frame: pl.DataFrame,
    rules: list[GERule],
    foreign_provider: dict[str, set[Any]] | None = None,
) -> list[GECheckResult]:
    """运行规则集；foreign_provider 提供 {target_dataset_id: set_of_values}。"""

    results: list[GECheckResult] = []
    if frame is None or frame.is_empty():
        for rule in rules:
            results.append(
                GECheckResult(
                    column=rule.column,
                    rule_type=rule.rule_type,
                    passed=False,
                    failed_count=0,
                    message="dataset 为空，规则无法判定",
                )
            )
        return results
    for rule in rules:
        if rule.column not in frame.columns:
            results.append(
                GECheckResult(
                    column=rule.column,
                    rule_type=rule.rule_type,
                    passed=False,
                    failed_count=frame.height,
                    message=f"列不存在: {rule.column}",
                )
            )
            continue
        column = frame.get_column(rule.column)
        if rule.rule_type == "not_null":
            failed = column.is_null().sum()
            results.append(_ge_result(rule, failed == 0, failed, f"null 数 {failed}"))
        elif rule.rule_type == "unique":
            failed = column.len() - column.n_unique()
            results.append(_ge_result(rule, failed == 0, failed, f"重复 {failed}"))
        elif rule.rule_type == "monotonic":
            order = rule.params.get("order", "asc")
            sorted_col = column.sort(descending=(order != "asc"))
            ok = column.equals(sorted_col)
            results.append(
                _ge_result(rule, ok, 0 if ok else frame.height, f"单调 {order} 失败" if not ok else "ok")
            )
        elif rule.rule_type == "value_range":
            lo = rule.params.get("min")
            hi = rule.params.get("max")
            expr = pl.lit(True)
            if lo is not None:
                expr = expr & (pl.col(rule.column) >= lo)
            if hi is not None:
                expr = expr & (pl.col(rule.column) <= hi)
            failed = frame.filter(~expr).height
            results.append(_ge_result(rule, failed == 0, failed, f"超出范围 {failed}"))
        elif rule.rule_type == "foreign_key":
            target = rule.params.get("target_dataset_id")
            if not foreign_provider or target not in foreign_provider:
                results.append(_ge_result(rule, False, frame.height, f"未提供 {target} 的对照值"))
                continue
            valid = foreign_provider[target]
            failed = sum(1 for v in column.to_list() if v not in valid)
            results.append(_ge_result(rule, failed == 0, failed, f"外键不命中 {failed}"))
        else:
            results.append(_ge_result(rule, False, 0, f"未知规则: {rule.rule_type}"))
    return results


def _ge_result(rule: GERule, passed: bool, failed_count: int, message: str) -> GECheckResult:
    return GECheckResult(
        column=rule.column,
        rule_type=rule.rule_type,
        passed=passed,
        failed_count=int(failed_count or 0),
        message=message,
    )


@dataclass
class DatasetVersion:
    dataset_id: str
    version_id: str
    source_name: str
    fetched_at_utc: str
    row_count: int
    coverage_start_utc: str | None
    coverage_end_utc: str | None
    sha256: str
    file_paths: list[str] = field(default_factory=list)
    ge_results: list[dict[str, Any]] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    # —— DataUpdate 信封补字段（GOAL §11「每次数据更新记录」· 卡 B-VERSION-1 余）——
    # 全 optional·默认空：① 旧 registry.jsonl 行（无这些键）经 from_dict 仍解析（缺键填默认）；
    # ② version_id / sha256 不由这些字段决定 → 既有合法写入身份字节不变（向后兼容验收）。
    # 字段↔§11 信封：source_ref / ingestion_skill_version(skill_version) / secret_ref(引用) /
    # known_at·effective_at(PIT) / quality_verdict(由 ge_results 派生) / lineage_id(=lineage) /
    # schema_drift_status(信封槽位)。checksum=sha256、dataset_version=version_id、freshness_status
    # 见下方 note（活算不冻结）。
    source_ref: str | None = None
    ingestion_skill_version: str | None = None
    secret_ref: str | None = None          # 凭据【引用】，绝不明文 key（写时已被 validate_for_write 守门）
    known_at_utc: str | None = None
    effective_at_utc: str | None = None
    quality_verdict: str | None = None     # pass / fail / unknown（None=未跑 GE）
    schema_drift_status: str | None = None  # 信封槽位；真 drift 检测非本卡 scope（诚实留 None）
    lineage_id: str | None = None          # data 级谱系 id（register 内 ids.content_hash 自动派生·恒在场）
    manifest_path: str | None = None       # on-disk manifest 落点（有真实 file_paths 时）
    # 说明：freshness_status 不冻结进不可变记录——它随时间变化，由 compute_freshness(registry)
    # 活算（见本模块 compute_freshness）。把瞬时 freshness 写进不可变行会自欺，故刻意不存。

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "DatasetVersion":
        # 向后/向前兼容：旧行缺新键→默认补；未知键→忽略（不让一行炸全 registry 读取）。
        known = {f.name for f in _dc_fields(cls)}
        return cls(**{k: v for k, v in data.items() if k in known})


def make_version_id(fetched_at_utc: str, sha256: str) -> str:
    safe_ts = fetched_at_utc.replace(":", "").replace("-", "").replace("+", "_").replace(".", "_")
    return f"{safe_ts}__{sha256[:8]}"


def dataset_manifest_root(file_paths: Iterable[str | Path]) -> Path | None:
    """on-disk manifest 的【单一源】root 约定——写侧与读侧 re-verify 必经此函数算根（§1 单一源）。

    写侧 ``DatasetRegistry._write_and_verify_manifest`` 落 manifest 时用它算 root，读侧
    ``factor_factory.panel_source._load_real_panel``（F3 读侧完整性门）re-verify 时用【同一】
    函数算 root——两侧 ``relative_path→sha256`` 的 key 永不漂移。若两侧各算各的 root 而算法一偏，
    ``verify_manifest`` 会把每条 entry 都误判成「文件丢失」→ 假阳性 raise（把好数据判成篡改）。

    规则（与既有写侧逐字节一致，抽取而非新造）：只数**磁盘上真实存在**的文件；单文件=其父目录；
    多文件=commonpath（若 commonpath 落到非目录则升到其父）。无任一存在文件 → None（无可哈希）。
    """

    existing = [Path(fp) for fp in (file_paths or []) if Path(fp).is_file()]
    if not existing:
        return None
    if len(existing) == 1:
        return existing[0].parent
    root = Path(os.path.commonpath([str(p) for p in existing]))
    if not root.is_dir():
        root = root.parent
    return root


class DatasetRegistry:
    """append-only JSONL registry。线程安全；多进程下要把 lock 替换成 fcntl。"""

    def __init__(self, store_path: Path) -> None:
        self._path = Path(store_path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        if not self._path.exists():
            self._path.write_text("")
        self._lock = threading.Lock()

    @property
    def store_path(self) -> Path:
        return self._path

    def register(
        self,
        dataset_id: str,
        fetch_result: FetchResult,
        file_paths: list[str] | None = None,
        rules: list[GERule] | None = None,
        metadata: dict[str, Any] | None = None,
        foreign_provider: dict[str, set[Any]] | None = None,
        *,
        source_ref: str | None = None,
        ingestion_skill_version: str | None = None,
        secret_ref: str | None = None,
        known_at_utc: str | None = None,
        effective_at_utc: str | None = None,
        upstream_lineage: list[str] | tuple[str, ...] | None = None,
        schema_drift_status: str | None = None,
        require_provenance: bool = False,
    ) -> DatasetVersion:
        """数据落库唯一单点（intake.py 等所有写路径都汇于此）。扩展不替换：新增信封参数全为
        keyword-only·默认空 → 既有调用（``register(did, fr, file_paths=…, metadata=…)``）字节级不变。

        写时强约束（缺 dataset_version/checksum/篡改 → 拒）+ on-disk manifest 不可变门 +
        data 级 lineage 自动派生，全在 ``self._append`` 落账【之前】完成——任一拒绝即不落账。
        """

        # 1) 把 register 级信封覆盖回写进 FetchResult 的副本 —— 让【单一写时校验源】
        #    validate_for_write 读它自己的字段（含 secret_ref 引用守门 + 可选 provenance 门）。
        overrides: dict[str, Any] = {}
        if source_ref is not None:
            overrides["source_ref"] = source_ref
        if ingestion_skill_version is not None:
            overrides["ingestion_skill_version"] = ingestion_skill_version
        if secret_ref is not None:
            overrides["secret_ref"] = secret_ref
        if known_at_utc is not None:
            overrides["known_at_utc"] = known_at_utc
        if effective_at_utc is not None:
            overrides["effective_at_utc"] = effective_at_utc
        fr = dataclasses.replace(fetch_result, **overrides) if overrides else fetch_result

        # 2) 写时强约束（单源 gate，复用既有 _sha256_of_frame·绝不另造哈希）：
        #    缺身份/缺 checksum/篡改 → 拒；secret_ref 非引用 → 拒；require_provenance 开则缺凭据 → 拒。
        fr.validate_for_write(dataset_id=dataset_id, require_provenance=require_provenance)

        # version_id 只由 frame 内容(sha256) + fetched_at 决定（与既有完全一致），先算出供 manifest/lineage 用。
        version_id = make_version_id(fr.fetched_at_utc, fr.sha256)

        ge_results = []
        if rules:
            ge_results = [r.to_dict() for r in run_ge_checks(fr.frame, rules, foreign_provider)]
        # quality_verdict（§11 信封）由 GE 结果诚实派生：未跑→None，全过→pass，有失败→fail。
        quality_verdict: str | None = None
        if ge_results:
            quality_verdict = "pass" if all(r.get("passed") for r in ge_results) else "fail"

        # 数据平台 v2：把数据集真实列清单落进 metadata["columns"]（FieldCatalog 的真相源之一）。
        meta = dict(metadata or {})
        if "columns" not in meta:
            try:
                meta["columns"] = list(fr.frame.columns)
            except Exception:  # noqa: BLE001
                pass

        # 3) data 级 lineage 自动派生（复用 ids.content_hash·恒在场 → 满足 §16「缺 lineage 即停」：
        #    lineage 是身份的派生属性，不可能缺，无须额外拒绝路径）。
        from .lineage.data_lineage import derive_dataset_lineage  # 惰性 import：零改 data_quality import-time 行为

        lineage_node = derive_dataset_lineage(
            dataset_id=dataset_id,
            dataset_version=version_id,
            checksum=fr.sha256,
            source_ref=fr.source_ref,
            ingestion_skill_version=fr.ingestion_skill_version,
            upstream=tuple(upstream_lineage or ()),
        )

        # 4) on-disk manifest 自动落 + 校验（仅对真实存在的 file_paths）。同 version 内容漂移 →
        #    不可变门 raise DatasetIntegrityError（接活已建门·种坏门必抓）。在落账【前】，拒则不落账。
        manifest_path = self._write_and_verify_manifest(dataset_id, version_id, file_paths)

        version = DatasetVersion(
            dataset_id=dataset_id,
            version_id=version_id,
            source_name=fr.source_name,
            fetched_at_utc=fr.fetched_at_utc,
            row_count=fr.row_count,
            coverage_start_utc=fr.coverage_start_utc,
            coverage_end_utc=fr.coverage_end_utc,
            sha256=fr.sha256,
            file_paths=list(file_paths or []),
            ge_results=ge_results,
            metadata=meta,
            source_ref=fr.source_ref,
            ingestion_skill_version=fr.ingestion_skill_version,
            secret_ref=fr.secret_ref,
            known_at_utc=fr.known_at_utc,
            effective_at_utc=fr.effective_at_utc,
            quality_verdict=quality_verdict,
            schema_drift_status=schema_drift_status,
            lineage_id=lineage_node.lineage_id,
            manifest_path=manifest_path,
        )
        self._append(version)
        return version

    def _manifest_path(self, dataset_id: str, version_id: str) -> Path:
        """on-disk manifest 落点：``<registry 同级>/manifests/<safe dataset_id>/<version_id>.json``。
        与 registry.jsonl 同根、与数据文件目录隔离（不污染 FieldCatalog 的目录扫描）。"""

        safe = _SAFE_PATH.sub("_", str(dataset_id)).strip("._") or "ds"
        return self._path.parent / "manifests" / safe / f"{version_id}.json"

    def _write_and_verify_manifest(
        self, dataset_id: str, version_id: str, file_paths: list[str] | None
    ) -> str | None:
        """对真实存在的 file_paths 落 on-disk manifest（per-file sha256）并校验。

        - 复用 ``data_hash.dataset_hash`` 的 create_manifest/write_manifest/verify_manifest
          （内部 ``_sha256_file`` = 单源文件哈希，**绝不另造**文件哈希），不改 dataset_hash。
        - **不可变门**：``write_manifest`` 对同 (dataset_id, version_id) 若文件 sha256 漂移 →
          raise ``DatasetIntegrityError``（López de Prado §1：dataset_version 内容不可变）。
        - **向后兼容**：无 file_paths / 路径不存在（如既有测试传 ``["a.parquet"]`` 占位）→ no-op、
          返 None，绝不因占位路径炸既有写入。
        """

        from .data_hash.dataset_hash import (  # 惰性 import：零改 import-time 行为·无循环依赖
            DatasetManifest,
            FileEntry,
            create_manifest,
            verify_manifest,
            write_manifest,
        )

        existing = [Path(fp) for fp in (file_paths or []) if Path(fp).is_file()]
        if not existing:
            return None

        # 稳定 root：单一源 = 模块级 dataset_manifest_root（写侧落 manifest 与读侧 F3 re-verify
        # 同一函数算根 → relative_path key 永不漂移）。single=父目录；multi=commonpath（非目录升父）。
        root = dataset_manifest_root(existing)
        if root is None:  # existing 已非空 → 恒非 None；防御式收窄类型（不新增行为分支）
            return None

        entries: list[FileEntry] = []
        total_bytes = 0
        total_rows = 0
        has_rows = False
        for p in existing:
            # 逐文件复用 create_manifest（root=父目录, glob=文件名）拿单源 sha256/size/row_count。
            sub = create_manifest(dataset_id, version_id, root_dir=p.parent, glob_pattern=p.name, recursive=False)
            if not sub.files:
                continue
            fe = sub.files[0]
            rel = p.relative_to(root).as_posix()
            entries.append(FileEntry(relative_path=rel, sha256=fe.sha256, size_bytes=fe.size_bytes, row_count=fe.row_count))
            total_bytes += fe.size_bytes
            if fe.row_count is not None:
                has_rows = True
                total_rows += fe.row_count
        if not entries:
            return None

        manifest = DatasetManifest(
            dataset_id=dataset_id,
            version=version_id,
            files=entries,
            created_at_utc=datetime.now(UTC).isoformat(),
            total_size_bytes=total_bytes,
            total_row_count=total_rows if has_rows else None,
        )
        manifest_path = self._manifest_path(dataset_id, version_id)
        # 不可变门（同 version 漂移 → raise）。首登记=新写；篡改后再登记同 version → 拒。
        write_manifest(manifest, manifest_path)
        # 落后即校验（重算磁盘 vs manifest）——双保险，措辞诚实：检出 sha256 不符即拒。
        ok, mismatches = verify_manifest(manifest_path, root)
        if not ok:
            from .data_hash.dataset_hash import DatasetIntegrityError

            raise DatasetIntegrityError(
                f"on-disk manifest 落后自校验失败 dataset_id={dataset_id} version={version_id}: {mismatches}"
            )
        return str(manifest_path)

    def list_versions(self, dataset_id: str | None = None) -> list[DatasetVersion]:
        items: list[DatasetVersion] = []
        with self._lock:
            for line in self._path.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                data = json.loads(line)
                if dataset_id is None or data["dataset_id"] == dataset_id:
                    items.append(DatasetVersion.from_dict(data))
        return items

    def latest(self, dataset_id: str) -> DatasetVersion | None:
        versions = sorted(
            self.list_versions(dataset_id),
            key=lambda v: v.fetched_at_utc,
        )
        return versions[-1] if versions else None

    @staticmethod
    def _version_ref_candidates(version: DatasetVersion) -> set[str]:
        """Return the exact DatasetVersion identities accepted by production callers."""

        return {
            version.version_id,
            f"dataset_version:{version.version_id}",
            f"dataset_version:{version.dataset_id}:{version.version_id}",
            f"dataset_version:{version.dataset_id}@{version.version_id}",
        }

    def resolve_version_ref(self, ref: str | None) -> DatasetVersion:
        """Resolve one persisted DatasetVersion reference without guessing.

        Supported identities intentionally match the production DatasetVersion reference
        forms: bare ``version_id``, ``dataset_version:<version_id>``, and the two qualified
        ``dataset_version:<dataset_id>:<version_id>`` / ``dataset_version:<dataset_id>@<version_id>``
        forms.  Missing and ambiguous references raise ``ValueError`` so callers cannot
        accidentally treat an arbitrary first registry row as canonical.

        Repeated byte-equivalent append-only rows describe the same record and are
        de-duplicated.  Conflicting rows, including equal version ids across datasets,
        remain ambiguous and fail closed.  This method only reads ``registry.jsonl``.
        """

        ref_text = str(ref or "").strip()
        if not ref_text:
            raise ValueError("dataset_version_ref is required")

        matches = [
            version
            for version in self.list_versions()
            if ref_text in self._version_ref_candidates(version)
        ]
        if not matches:
            raise ValueError(f"dataset_version_ref {ref_text!r} is not recorded")

        distinct: list[DatasetVersion] = []
        for version in matches:
            if version not in distinct:
                distinct.append(version)
        if len(distinct) != 1:
            raise ValueError(f"dataset_version_ref {ref_text!r} is ambiguous")
        return distinct[0]

    def find_version(self, version_id: str) -> DatasetVersion | None:
        """按 version_id 精确查一条【已注册】DatasetVersion（confirmatory 数据身份门用）。

        ``make_version_id`` 不包含 dataset_id，同一批数据可能在多个 dataset 下产生相同
        version_id；这种歧义必须返回 None，不能取 registry 首行。confirmatory 边界门
        （``eval.confirmatory_data_gate``）据此把 dataset_version
        映回注册身份 + known_at(PIT) + lineage，验证「无 PIT/无注册 数据不得进 confirmatory」。
        未命中 / 空 / 歧义 version_id → None（由调用方判拒，不在此造异常）。"""

        version_text = str(version_id or "").strip()
        try:
            resolved = self.resolve_version_ref(version_text)
        except ValueError:
            return None
        return resolved if version_text == resolved.version_id else None

    def list_dataset_ids(self) -> list[str]:
        return sorted({v.dataset_id for v in self.list_versions()})

    def _append(self, version: DatasetVersion) -> None:
        line = json.dumps(version.to_dict(), ensure_ascii=False)
        with self._lock:
            with self._path.open("a", encoding="utf-8") as fh:
                fh.write(line + "\n")


@dataclass
class FreshnessReport:
    dataset_id: str
    status: FreshnessStatus
    expected_end_utc: str
    actual_end_utc: str | None
    staleness_seconds: float | None
    note: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def expected_end_utc(market_kind: str, *, now: datetime | None = None) -> datetime:
    """近似的"应有最新数据时间"。

    - A股 (`stocks_cn` / `indices_cn` / `funds_cn`)：取最近一个工作日 15:30 收盘 +
      30 分钟（结算窗口）。周六周日按周五处理，节假日表暂不嵌入（外接 pandas-mc）。
    - 加密 (`binance*`)：当前 UTC（24/7）。
    - 其它：当前 UTC（保守）。
    """

    now = (now or datetime.now(UTC)).astimezone(UTC)
    if market_kind.startswith("stocks_cn") or market_kind.startswith("indices_cn") or market_kind.startswith("funds_cn"):
        sh_now = now + timedelta(hours=8)
        target = sh_now
        if sh_now.time() < time(16, 0):
            target = target - timedelta(days=1)
        while target.weekday() >= 5:  # Sat=5 Sun=6
            target = target - timedelta(days=1)
        target = datetime.combine(target.date(), time(16, 0))
        return (target - timedelta(hours=8)).replace(tzinfo=UTC)
    return now


def compute_freshness(
    dataset_id: str,
    market_kind: str,
    registry: DatasetRegistry,
    *,
    yellow_threshold_seconds: float = 24 * 3600,
    red_threshold_seconds: float = 7 * 24 * 3600,
    now: datetime | None = None,
) -> FreshnessReport:
    version = registry.latest(dataset_id)
    expected = expected_end_utc(market_kind, now=now)
    if version is None or not version.coverage_end_utc:
        return FreshnessReport(
            dataset_id=dataset_id,
            status="unknown",
            expected_end_utc=expected.isoformat(),
            actual_end_utc=None,
            staleness_seconds=None,
            note="无版本",
        )
    actual = datetime.fromisoformat(version.coverage_end_utc.replace("Z", "+00:00"))
    if actual.tzinfo is None:
        actual = actual.replace(tzinfo=UTC)
    staleness = (expected - actual).total_seconds()
    if staleness < 0:
        status: FreshnessStatus = "green"
    elif staleness <= yellow_threshold_seconds:
        status = "green"
    elif staleness <= red_threshold_seconds:
        status = "yellow"
    else:
        status = "red"
    return FreshnessReport(
        dataset_id=dataset_id,
        status=status,
        expected_end_utc=expected.isoformat(),
        actual_end_utc=actual.isoformat(),
        staleness_seconds=staleness,
        note=f"version {version.version_id}",
    )


__all__ = [
    "DatasetRegistry",
    "DatasetVersion",
    "FreshnessReport",
    "FreshnessStatus",
    "GECheckResult",
    "GE_RuleType",
    "GERule",
    "compute_freshness",
    "dataset_manifest_root",
    "expected_end_utc",
    "make_version_id",
    "run_ge_checks",
]
