"""聚宽风 IDE 服务：策略文件 CRUD + 沙箱运行 + 结果落盘。

文件布局：
    data/ide_strategies.db (sqlite, gitignored)
        i_strategies (strategy_id, owner_username, name, code, asset_class, updated_at_utc)
        i_runs (run_id, strategy_id, owner_username, status, started_at_utc,
                finished_at_utc, exit_code, error, stdout_path, result_path)

运行结果落盘到 RUN_ROOT/<run_id>/。成功运行还会冻结精确的 strategy.py、
canonical result.json、portfolio.csv 与最后写入的 canonical run.json。
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import math
import sqlite3
import threading
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from secrets import token_urlsafe
from typing import Any

from ..lineage.ids import canonical_json, content_hash
from .sandbox import SandboxResult, cleanup_workdir, run_user_strategy


class IDEError(Exception):
    """所有 IDE 业务异常（404 / 400）。"""


@dataclass
class StrategyFile:
    strategy_id: str
    owner_username: str
    name: str
    code: str
    asset_class: str  # crypto_perp / crypto_spot / equity_cn
    description: str
    updated_at_utc: str
    market_data_use_validation_refs: list[str]


@dataclass
class StrategyVersion:
    """策略草稿一次保存/Fork 留痕的版本史条目（lineage ledger 风：append-only，不可改小）。

    身份单一源：`content_hash` 经 lineage.content_hash 产（见 strategy_graph.strategy_content_hash）。
    `parent_content_hash` 是血缘父锚：Fork 出来的草稿指向被 fork 版本，非 Fork 时为 None。
    """

    version_id: str
    strategy_id: str
    owner_username: str
    content_hash: str
    parent_content_hash: str | None
    parent_strategy_id: str | None
    label: str
    origin: str  # save / fork
    created_at_utc: str


@dataclass
class IDERun:
    run_id: str
    strategy_id: str
    owner_username: str
    status: str  # running / ok / failed / timeout
    started_at_utc: str
    market_data_use_validation_refs: list[str]
    section9_evidence_ref: str | None
    finished_at_utc: str | None
    exit_code: int | None
    error: str | None
    stdout_excerpt: str
    stderr_excerpt: str
    duration_s: float
    result_keys: list[str]


def _utc_now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


_PORTFOLIO_COLUMNS = (
    "timestamp",
    "equity",
    "net_return",
    "benchmark_return",
    "drawdown",
)


def _safe_float(value: Any) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) else None


def _canonical_portfolio_rows(result: dict[str, Any]) -> list[dict[str, Any]]:
    """Derive stable portfolio rows only from the sandbox-emitted result."""

    raw_curve = result.get("equity_curve")
    if not isinstance(raw_curve, list):
        return []
    rows: list[dict[str, Any]] = []
    for index, point in enumerate(raw_curve):
        if not isinstance(point, dict):
            continue
        timestamp = point.get("timestamp") or point.get("t") or point.get("date") or str(index)
        equity = point.get("equity")
        if equity is None:
            equity = point.get("value")
        equity_value = _safe_float(equity)
        if equity_value is None:
            continue
        rows.append(
            {
                "timestamp": str(timestamp),
                "equity": equity_value,
                "net_return": _safe_float(point.get("net_return")),
                "benchmark_return": _safe_float(point.get("benchmark_return")),
                "drawdown": _safe_float(point.get("drawdown")),
            }
        )

    if not rows:
        return []
    for index, row in enumerate(rows):
        if row["net_return"] is not None:
            continue
        if index == 0:
            row["net_return"] = 0.0
            continue
        previous_equity = rows[index - 1]["equity"]
        if previous_equity:
            row["net_return"] = row["equity"] / previous_equity - 1.0

    peak = rows[0]["equity"]
    for row in rows:
        peak = max(peak, row["equity"])
        if row["drawdown"] is None and peak:
            row["drawdown"] = row["equity"] / peak - 1.0
    return rows


def _canonical_portfolio_csv_bytes(result: dict[str, Any]) -> bytes:
    buffer = io.StringIO(newline="")
    writer = csv.DictWriter(
        buffer,
        fieldnames=list(_PORTFOLIO_COLUMNS),
        extrasaction="ignore",
        lineterminator="\n",
    )
    writer.writeheader()
    for row in _canonical_portfolio_rows(result):
        writer.writerow(
            {key: "" if row.get(key) is None else row.get(key) for key in _PORTFOLIO_COLUMNS}
        )
    return buffer.getvalue().encode("utf-8")


def _canonical_json_bytes(value: Any) -> bytes:
    return (canonical_json(value) + "\n").encode("utf-8")


def _sha256_bytes(value: bytes) -> str:
    return "sha256:" + hashlib.sha256(value).hexdigest()


def _schema() -> list[str]:
    return [
        """
        CREATE TABLE IF NOT EXISTS i_strategies (
            strategy_id TEXT PRIMARY KEY,
            owner_username TEXT NOT NULL,
            name TEXT NOT NULL,
            code TEXT NOT NULL,
            asset_class TEXT NOT NULL,
            description TEXT NOT NULL DEFAULT '',
            market_data_use_validation_refs TEXT NOT NULL DEFAULT '[]',
            updated_at_utc TEXT NOT NULL,
            UNIQUE (owner_username, name)
        )
        """,
        "CREATE INDEX IF NOT EXISTS idx_strategies_owner ON i_strategies(owner_username)",
        """
        CREATE TABLE IF NOT EXISTS i_runs (
            run_id TEXT PRIMARY KEY,
            strategy_id TEXT NOT NULL,
            owner_username TEXT NOT NULL,
            status TEXT NOT NULL,
            started_at_utc TEXT NOT NULL,
            market_data_use_validation_refs TEXT NOT NULL DEFAULT '[]',
            section9_evidence_ref TEXT,
            finished_at_utc TEXT,
            exit_code INTEGER,
            error TEXT,
            stdout_excerpt TEXT NOT NULL DEFAULT '',
            stderr_excerpt TEXT NOT NULL DEFAULT '',
            duration_s REAL NOT NULL DEFAULT 0,
            result_keys TEXT NOT NULL DEFAULT '[]',
            result_path TEXT,
            FOREIGN KEY (strategy_id) REFERENCES i_strategies(strategy_id)
        )
        """,
        "CREATE INDEX IF NOT EXISTS idx_runs_owner ON i_runs(owner_username, started_at_utc DESC)",
        """
        CREATE TABLE IF NOT EXISTS i_strategy_versions (
            version_id TEXT PRIMARY KEY,
            strategy_id TEXT NOT NULL,
            owner_username TEXT NOT NULL,
            content_hash TEXT NOT NULL,
            parent_content_hash TEXT,
            parent_strategy_id TEXT,
            label TEXT NOT NULL DEFAULT '',
            origin TEXT NOT NULL DEFAULT 'save',
            created_at_utc TEXT NOT NULL,
            FOREIGN KEY (strategy_id) REFERENCES i_strategies(strategy_id)
        )
        """,
        "CREATE INDEX IF NOT EXISTS idx_versions_sid ON i_strategy_versions(strategy_id, created_at_utc DESC)",
    ]


def init_ide_db(db_path: Path) -> None:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(db_path) as conn:
        for stmt in _schema():
            conn.execute(stmt)
        cols = {row[1] for row in conn.execute("PRAGMA table_info(i_strategies)").fetchall()}
        if "market_data_use_validation_refs" not in cols:
            conn.execute(
                "ALTER TABLE i_strategies ADD COLUMN market_data_use_validation_refs TEXT NOT NULL DEFAULT '[]'"
            )
        run_cols = {row[1] for row in conn.execute("PRAGMA table_info(i_runs)").fetchall()}
        if "market_data_use_validation_refs" not in run_cols:
            conn.execute(
                "ALTER TABLE i_runs ADD COLUMN market_data_use_validation_refs TEXT NOT NULL DEFAULT '[]'"
            )
        if "section9_evidence_ref" not in run_cols:
            conn.execute("ALTER TABLE i_runs ADD COLUMN section9_evidence_ref TEXT")
        conn.commit()


VALID_ASSET = {"crypto_perp", "crypto_spot", "equity_cn"}


def validate_strategy_inputs(
    owner_username: Any,
    name: Any,
    code: Any,
    *,
    asset_class: Any = "crypto_perp",
    description: Any = "",
) -> None:
    """Validate deterministic IDE strategy inputs without touching storage."""

    if (
        not isinstance(owner_username, str)
        or not owner_username
        or not isinstance(name, str)
        or not name
    ):
        raise IDEError("owner_username / name 必填")
    if not isinstance(asset_class, str) or asset_class not in VALID_ASSET:
        raise IDEError(f"asset_class 必须 ∈ {sorted(VALID_ASSET)}")
    if not isinstance(code, str):
        raise IDEError("策略源码必须是字符串")
    if len(code) > 1_000_000:
        raise IDEError("策略源码不能超过 1MB")
    if not name.replace("_", "").replace("-", "").isalnum():
        raise IDEError("策略名只能用字母数字 - _")
    if not isinstance(description, str):
        raise IDEError("策略描述必须是字符串")


class IDEService:
    """同步 service：sqlite + 沙箱 run。

    线程安全：sqlite connection per-call；run 用进程级 lock 串行化（防止用户狂点）。
    """

    def __init__(self, db_path: Path, run_root: Path | None = None) -> None:
        self._db = db_path
        init_ide_db(db_path)
        self._run_root = run_root or db_path.parent / "ide_runs"
        self._run_root.mkdir(parents=True, exist_ok=True)
        self._run_lock = threading.Lock()

    @property
    def run_root(self) -> Path:
        """Read-only root containing immutable per-run source snapshots."""

        return self._run_root

    def _conn(self) -> sqlite3.Connection:
        c = sqlite3.connect(self._db)
        c.row_factory = sqlite3.Row
        return c

    @staticmethod
    def _refs_json(refs: list[str] | tuple[str, ...] | None) -> str:
        return json.dumps([str(ref) for ref in refs or []], ensure_ascii=False)

    @staticmethod
    def _refs_from_json(raw_refs: Any) -> list[str]:
        try:
            parsed_refs = json.loads(raw_refs)
        except (json.JSONDecodeError, TypeError):
            parsed_refs = []
        if not isinstance(parsed_refs, list):
            parsed_refs = []
        return [str(ref) for ref in parsed_refs if str(ref or "").strip()]

    @classmethod
    def _strategy_from_row(cls, row: sqlite3.Row) -> StrategyFile:
        data = dict(row)
        data["market_data_use_validation_refs"] = cls._refs_from_json(
            data.get("market_data_use_validation_refs") or "[]"
        )
        return StrategyFile(**data)

    @classmethod
    def _run_from_row(cls, row: sqlite3.Row) -> IDERun:
        data = dict(row)
        data["result_keys"] = json.loads(data.get("result_keys") or "[]")
        data["market_data_use_validation_refs"] = cls._refs_from_json(
            data.get("market_data_use_validation_refs") or "[]"
        )
        data.pop("result_path", None)
        return IDERun(**data)

    # ---------- strategy CRUD ----------

    def list_strategies(self, owner_username: str) -> list[StrategyFile]:
        with self._conn() as c:
            rows = c.execute(
                "SELECT * FROM i_strategies WHERE owner_username=? ORDER BY updated_at_utc DESC",
                (owner_username,),
            ).fetchall()
        return [self._strategy_from_row(r) for r in rows]

    def get_strategy(self, owner_username: str, name: str) -> StrategyFile:
        with self._conn() as c:
            r = c.execute(
                "SELECT * FROM i_strategies WHERE owner_username=? AND name=?",
                (owner_username, name),
            ).fetchone()
        if not r:
            raise IDEError(f"strategy not found: {name}")
        return self._strategy_from_row(r)

    def get_strategy_by_id(self, strategy_id: str) -> StrategyFile:
        """Internal exact-id getter used after a separate stable-owner envelope check.

        Public API reads remain owner/name scoped.  This getter deliberately does
        not establish authorization by itself; callers must first resolve the
        owner-scoped research-design envelope and then compare the current source
        content hash.
        """

        sid = str(strategy_id or "").strip()
        if not sid:
            raise IDEError("strategy_id is required")
        with self._conn() as c:
            row = c.execute(
                "SELECT * FROM i_strategies WHERE strategy_id=?",
                (sid,),
            ).fetchone()
        if not row:
            raise IDEError(f"strategy not found: {sid}")
        return self._strategy_from_row(row)

    def save_strategy(
        self,
        owner_username: str,
        name: str,
        code: str,
        *,
        asset_class: str = "crypto_perp",
        description: str = "",
        market_data_use_validation_refs: list[str] | tuple[str, ...] | None = None,
    ) -> StrategyFile:
        validate_strategy_inputs(
            owner_username,
            name,
            code,
            asset_class=asset_class,
            description=description,
        )
        refs_json = self._refs_json(market_data_use_validation_refs)
        now = _utc_now()
        with self._conn() as c:
            # Lock before the read so concurrent identical saves cannot both
            # append a version after observing the same prior projection.
            c.execute("BEGIN IMMEDIATE")
            existing = c.execute(
                "SELECT * FROM i_strategies WHERE owner_username=? AND name=?",
                (owner_username, name),
            ).fetchone()
            if existing:
                if (
                    existing["code"] == code
                    and existing["asset_class"] == asset_class
                    and existing["description"] == description
                    and existing["market_data_use_validation_refs"] == refs_json
                ):
                    # An identical retry is a read of the already committed
                    # business object, not a new edit/version.
                    c.commit()
                    return self._strategy_from_row(existing)
                sid = existing["strategy_id"]
                c.execute(
                    "UPDATE i_strategies SET code=?, asset_class=?, description=?, market_data_use_validation_refs=?, updated_at_utc=? WHERE strategy_id=?",
                    (code, asset_class, description, refs_json, now, sid),
                )
            else:
                sid = "stg_" + token_urlsafe(8)
                c.execute(
                    "INSERT INTO i_strategies (strategy_id, owner_username, name, code, asset_class, description, market_data_use_validation_refs, updated_at_utc) VALUES (?,?,?,?,?,?,?,?)",
                    (sid, owner_username, name, code, asset_class, description, refs_json, now),
                )
            # 版本史留痕（append-only，身份经 lineage.content_hash；同一作者草稿谱系）。
            self._record_version_locked(
                c, strategy_id=sid, owner_username=owner_username, name=name, code=code,
                asset_class=asset_class, parent_content_hash=None, parent_strategy_id=None,
                origin="save", now=now,
            )
            c.commit()
        return self.get_strategy(owner_username, name)

    # ---------- 版本史 + Fork（身份锚 lineage/ids.py 单一源） ----------

    def _record_version_locked(
        self,
        conn: sqlite3.Connection,
        *,
        strategy_id: str,
        owner_username: str,
        name: str,
        code: str,
        asset_class: str,
        parent_content_hash: str | None,
        parent_strategy_id: str | None,
        origin: str,
        now: str,
    ) -> str:
        """在已开连接里 append 一条版本史（身份经 strategy_content_hash → lineage.content_hash）。

        延迟 import 防循环（strategy_graph import lineage，service 被 strategy_graph 间接拉）。
        """

        from .strategy_graph import strategy_content_hash

        chash = strategy_content_hash(name=name, code=code, asset_class=asset_class)
        vid = "sv_" + token_urlsafe(8)
        label = f"fork←{parent_strategy_id}" if origin == "fork" else f"save {now}"
        conn.execute(
            "INSERT INTO i_strategy_versions (version_id, strategy_id, owner_username, content_hash, "
            "parent_content_hash, parent_strategy_id, label, origin, created_at_utc) VALUES (?,?,?,?,?,?,?,?,?)",
            (vid, strategy_id, owner_username, chash, parent_content_hash, parent_strategy_id, label, origin, now),
        )
        return chash

    def list_versions(self, owner_username: str, name: str) -> list[StrategyVersion]:
        """读策略的版本史（新→旧）。仅本人可读（owner 命名空间隔离）。"""

        s = self.get_strategy(owner_username, name)  # 触发 404 + owner 校验
        with self._conn() as c:
            rows = c.execute(
                "SELECT version_id, strategy_id, owner_username, content_hash, parent_content_hash, "
                "parent_strategy_id, label, origin, created_at_utc FROM i_strategy_versions "
                "WHERE strategy_id=? AND owner_username=? ORDER BY created_at_utc DESC, rowid DESC",
                (s.strategy_id, owner_username),
            ).fetchall()
        return [StrategyVersion(**dict(r)) for r in rows]

    def fork_strategy(self, owner_username: str, name: str, *, fork_name: str | None = None) -> StrategyFile:
        """策略级 Fork：复制为新草稿，血缘锚定父策略（content_hash 经 lineage 单一源）。

        与模板 fork / 社区分享 fork 不同语义：这里是同一作者把自己某草稿派生出可编辑副本，
        新草稿的版本史首条 origin='fork'、parent_content_hash 指向父策略当前内容指纹。
        """

        parent = self.get_strategy(owner_username, name)
        from .strategy_graph import strategy_content_hash

        parent_chash = strategy_content_hash(
            name=parent.name, code=parent.code, asset_class=parent.asset_class,
        )
        new_name = (fork_name or f"{parent.name}_fork").strip()
        if not new_name.replace("_", "").replace("-", "").isalnum():
            raise IDEError("fork 名只能用字母数字 - _")
        # 名字冲突时追加短后缀，保证 (owner, name) 唯一约束不炸。
        candidate = new_name
        with self._conn() as c:
            for _ in range(50):
                exists = c.execute(
                    "SELECT 1 FROM i_strategies WHERE owner_username=? AND name=?",
                    (owner_username, candidate),
                ).fetchone()
                if not exists:
                    break
                candidate = f"{new_name}_{token_urlsafe(3)}"
            now = _utc_now()
            sid = "stg_" + token_urlsafe(8)
            c.execute(
                "INSERT INTO i_strategies (strategy_id, owner_username, name, code, asset_class, description, market_data_use_validation_refs, updated_at_utc) VALUES (?,?,?,?,?,?,?,?)",
                (sid, owner_username, candidate, parent.code, parent.asset_class,
                 f"fork of {parent.name}", self._refs_json(parent.market_data_use_validation_refs), now),
            )
            self._record_version_locked(
                c, strategy_id=sid, owner_username=owner_username, name=candidate,
                code=parent.code, asset_class=parent.asset_class,
                parent_content_hash=parent_chash, parent_strategy_id=parent.strategy_id,
                origin="fork", now=now,
            )
            c.commit()
        return self.get_strategy(owner_username, candidate)

    def delete_strategy(self, owner_username: str, name: str) -> None:
        with self._conn() as c:
            cur = c.execute(
                "DELETE FROM i_strategies WHERE owner_username=? AND name=?",
                (owner_username, name),
            )
            if cur.rowcount == 0:
                raise IDEError(f"strategy not found: {name}")
            c.commit()

    # ---------- run ----------

    def run_strategy(
        self,
        owner_username: str,
        name: str,
        *,
        owner_user_id: str | None = None,
        market_data_use_validation_refs: list[str] | tuple[str, ...] | None = None,
        section9_evidence_ref: str | None = None,
    ) -> IDERun:
        s = self.get_strategy(owner_username, name)
        stable_owner_user_id = str(owner_user_id or "").strip() or owner_username
        run_refs = (
            list(market_data_use_validation_refs)
            if market_data_use_validation_refs is not None
            else list(s.market_data_use_validation_refs)
        )
        run_id = "ide_" + token_urlsafe(8)
        run_dir = self._run_root / run_id
        run_dir.mkdir(parents=True, exist_ok=False)

        started_at = _utc_now()
        with self._conn() as c:
            c.execute(
                "INSERT INTO i_runs (run_id, strategy_id, owner_username, status, started_at_utc, market_data_use_validation_refs, section9_evidence_ref) VALUES (?,?,?,?,?,?,?)",
                (
                    run_id,
                    s.strategy_id,
                    owner_username,
                    "running",
                    started_at,
                    self._refs_json(run_refs),
                    str(section9_evidence_ref or "").strip() or None,
                ),
            )
            c.commit()

        # 串行化沙箱（避免多个 follower 狂点导致 fork bomb 风险）
        with self._run_lock:
            sandbox_result = run_user_strategy(s.code, work_root=run_dir)

        # 落盘。成功状态只有在精确源码、真实结果和三文件运行工件全部冻结后才成立。
        result_path: str | None = None
        result_keys: list[str] = []
        if isinstance(sandbox_result.user_result, dict):
            result_keys = list(sandbox_result.user_result.keys())
        status = self._classify_status(sandbox_result)
        error = sandbox_result.error
        try:
            (run_dir / "stdout.log").write_text(sandbox_result.stdout, encoding="utf-8")
            (run_dir / "stderr.log").write_text(sandbox_result.stderr, encoding="utf-8")
            if status == "ok":
                if not isinstance(sandbox_result.user_result, dict):
                    raise ValueError("successful sandbox run did not emit a result object")
                self._persist_source_snapshot(
                    run_dir=run_dir,
                    run_id=run_id,
                    strategy=s,
                    owner_user_id=stable_owner_user_id,
                    result=sandbox_result.user_result,
                    started_at=started_at,
                )
                result_path = str(run_dir / "result.json")
            elif sandbox_result.user_result is not None:
                # Preserve legacy failed-run diagnostics, but never mint run.json/strategy.py/portfolio.csv.
                self._write_new_bytes(
                    run_dir / "result.json",
                    _canonical_json_bytes(sandbox_result.user_result),
                )
                result_path = str(run_dir / "result.json")
        except Exception as exc:  # noqa: BLE001 - any persistence gap must fail the run closed.
            if status == "ok":
                for artifact_name in ("run.json", "strategy.py", "portfolio.csv", "result.json"):
                    try:
                        (run_dir / artifact_name).unlink(missing_ok=True)
                    except OSError:
                        pass
                error = f"source snapshot persistence failed: {type(exc).__name__}: {exc}"
                result_path = None
            elif not error:
                error = f"run artifact persistence failed: {type(exc).__name__}: {exc}"
            status = "failed"

        finished_at = _utc_now()
        with self._conn() as c:
            c.execute(
                "UPDATE i_runs SET status=?, finished_at_utc=?, exit_code=?, error=?, stdout_excerpt=?, stderr_excerpt=?, duration_s=?, result_keys=?, result_path=? WHERE run_id=?",
                (
                    status,
                    finished_at,
                    sandbox_result.exit_code,
                    error,
                    sandbox_result.stdout[-4000:],
                    sandbox_result.stderr[-4000:],
                    sandbox_result.duration_s,
                    json.dumps(result_keys),
                    result_path,
                    run_id,
                ),
            )
            c.commit()

        # 清理沙箱 tempdir（保留我们落盘的 run_dir/*.log / result.json）
        if sandbox_result.workdir and sandbox_result.workdir != str(run_dir):
            cleanup_workdir(sandbox_result.workdir)

        return self.get_run(run_id)

    @staticmethod
    def _write_new_bytes(path: Path, payload: bytes) -> None:
        """Create one artifact exactly once; never overwrite an existing snapshot."""

        with path.open("xb") as handle:
            handle.write(payload)

    def _persist_source_snapshot(
        self,
        *,
        run_dir: Path,
        run_id: str,
        strategy: StrategyFile,
        owner_user_id: str,
        result: dict[str, Any],
        started_at: str,
    ) -> None:
        """Freeze one successful IDE run, writing run.json last as the commit marker."""

        from .strategy_graph import strategy_content_hash

        strategy_bytes = strategy.code.encode("utf-8")
        result_bytes = _canonical_json_bytes(result)
        portfolio_bytes = _canonical_portfolio_csv_bytes(result)
        metadata = result.get("metadata") if isinstance(result.get("metadata"), dict) else {}
        metrics = result.get("metrics") if isinstance(result.get("metrics"), dict) else {}
        source = {
            "kind": "ide_sandbox",
            "ide_run_id": run_id,
            "owner_user_id": owner_user_id,
            "owner_username": strategy.owner_username,
            "strategy_name": strategy.name,
            "strategy_asset_class": strategy.asset_class,
            "strategy_content_hash": strategy_content_hash(
                name=strategy.name,
                code=strategy.code,
                asset_class=strategy.asset_class,
            ),
            "strategy_code_content_hash": content_hash(strategy.code),
            "strategy_file_sha256": _sha256_bytes(strategy_bytes),
            "result_content_hash": content_hash(result),
            "result_file_sha256": _sha256_bytes(result_bytes),
            "portfolio_file_sha256": _sha256_bytes(portfolio_bytes),
        }
        run_manifest = {
            "artifact_version": "ide.source_run.v1",
            "run_id": run_id,
            "owner_user_id": owner_user_id,
            "owner_username": strategy.owner_username,
            "strategy_id": strategy.strategy_id,
            "strategy_name": strategy.name,
            "started_at": started_at,
            "status": "completed",
            "market": str(metadata.get("market") or strategy.asset_class),
            "frequency": str(metadata.get("frequency") or "unknown"),
            "metrics": metrics,
            "source": source,
        }
        payloads = (
            ("strategy.py", strategy_bytes),
            ("result.json", result_bytes),
            ("portfolio.csv", portfolio_bytes),
            ("run.json", _canonical_json_bytes(run_manifest)),
        )
        written: list[Path] = []
        try:
            for name, payload in payloads:
                path = run_dir / name
                self._write_new_bytes(path, payload)
                written.append(path)
        except Exception:
            for path in reversed(written):
                try:
                    path.unlink(missing_ok=True)
                except OSError:
                    pass
            raise

    @staticmethod
    def _classify_status(sb: SandboxResult) -> str:
        if sb.timed_out:
            return "timeout"
        if sb.exit_code == 0:
            return "ok"
        return "failed"

    def get_run(self, run_id: str) -> IDERun:
        with self._conn() as c:
            r = c.execute("SELECT * FROM i_runs WHERE run_id=?", (run_id,)).fetchone()
        if not r:
            raise IDEError(f"run not found: {run_id}")
        return self._run_from_row(r)

    def list_runs(self, owner_username: str, *, limit: int = 50) -> list[IDERun]:
        with self._conn() as c:
            rows = c.execute(
                "SELECT * FROM i_runs WHERE owner_username=? ORDER BY started_at_utc DESC LIMIT ?",
                (owner_username, limit),
            ).fetchall()
        out: list[IDERun] = []
        for r in rows:
            out.append(self._run_from_row(r))
        return out

    def get_run_artifact(self, run_id: str, kind: str) -> dict[str, Any]:
        """返回 stdout / stderr / result 的完整内容（带分页就让 frontend 传 offset）。"""
        if kind not in {"stdout", "stderr", "result"}:
            raise IDEError("kind 必须 ∈ {stdout, stderr, result}")
        with self._conn() as c:
            r = c.execute("SELECT run_id, result_path FROM i_runs WHERE run_id=?", (run_id,)).fetchone()
        if not r:
            raise IDEError(f"run not found: {run_id}")
        run_dir = self._run_root / run_id
        if kind == "result":
            rp = r["result_path"]
            if not rp or not Path(rp).exists():
                raise IDEError("no result emitted")
            return {"kind": "result", "body": json.loads(Path(rp).read_text())}
        path = run_dir / f"{kind}.log"
        if not path.exists():
            return {"kind": kind, "body": ""}
        return {"kind": kind, "body": path.read_text()}


def strategy_to_dict(s: StrategyFile) -> dict[str, Any]:
    return asdict(s)


def run_to_dict(r: IDERun) -> dict[str, Any]:
    return asdict(r)


def version_to_dict(v: StrategyVersion) -> dict[str, Any]:
    return asdict(v)


__all__ = [
    "IDEError",
    "IDERun",
    "IDEService",
    "StrategyFile",
    "StrategyVersion",
    "init_ide_db",
    "run_to_dict",
    "strategy_to_dict",
    "validate_strategy_inputs",
    "version_to_dict",
]
