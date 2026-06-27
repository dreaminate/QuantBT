"""聚宽风 IDE 服务：策略文件 CRUD + 沙箱运行 + 结果落盘。

文件布局：
    data/ide_strategies.db (sqlite, gitignored)
        i_strategies (strategy_id, owner_username, name, code, asset_class, updated_at_utc)
        i_runs (run_id, strategy_id, owner_username, status, started_at_utc,
                finished_at_utc, exit_code, error, stdout_path, result_path)

运行结果落盘到 RUN_ROOT/<run_id>/{stdout.log, stderr.log, result.json}
"""

from __future__ import annotations

import json
import sqlite3
import threading
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from secrets import token_urlsafe
from typing import Any

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
    finished_at_utc: str | None
    exit_code: int | None
    error: str | None
    stdout_excerpt: str
    stderr_excerpt: str
    duration_s: float
    result_keys: list[str]


def _utc_now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


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
        conn.commit()


VALID_ASSET = {"crypto_perp", "crypto_spot", "equity_cn"}


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
        if not owner_username or not name:
            raise IDEError("owner_username / name 必填")
        if asset_class not in VALID_ASSET:
            raise IDEError(f"asset_class 必须 ∈ {sorted(VALID_ASSET)}")
        if len(code) > 1_000_000:
            raise IDEError("策略源码不能超过 1MB")
        if not name.replace("_", "").replace("-", "").isalnum():
            raise IDEError("策略名只能用字母数字 - _")
        refs_json = self._refs_json(market_data_use_validation_refs)
        now = _utc_now()
        with self._conn() as c:
            existing = c.execute(
                "SELECT strategy_id FROM i_strategies WHERE owner_username=? AND name=?",
                (owner_username, name),
            ).fetchone()
            if existing:
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
        market_data_use_validation_refs: list[str] | tuple[str, ...] | None = None,
    ) -> IDERun:
        s = self.get_strategy(owner_username, name)
        run_refs = (
            list(market_data_use_validation_refs)
            if market_data_use_validation_refs is not None
            else list(s.market_data_use_validation_refs)
        )
        run_id = "ide_" + token_urlsafe(8)
        run_dir = self._run_root / run_id
        run_dir.mkdir(parents=True, exist_ok=True)

        started_at = _utc_now()
        with self._conn() as c:
            c.execute(
                "INSERT INTO i_runs (run_id, strategy_id, owner_username, status, started_at_utc, market_data_use_validation_refs) VALUES (?,?,?,?,?,?)",
                (run_id, s.strategy_id, owner_username, "running", started_at, self._refs_json(run_refs)),
            )
            c.commit()

        # 串行化沙箱（避免多个 follower 狂点导致 fork bomb 风险）
        with self._run_lock:
            sandbox_result = run_user_strategy(s.code, work_root=run_dir)

        # 落盘
        (run_dir / "stdout.log").write_text(sandbox_result.stdout)
        (run_dir / "stderr.log").write_text(sandbox_result.stderr)
        result_path: str | None = None
        result_keys: list[str] = []
        if sandbox_result.user_result is not None:
            result_path = str(run_dir / "result.json")
            (run_dir / "result.json").write_text(
                json.dumps(sandbox_result.user_result, default=str, ensure_ascii=False, indent=2),
            )
            result_keys = list(sandbox_result.user_result.keys())

        status = self._classify_status(sandbox_result)
        finished_at = _utc_now()
        with self._conn() as c:
            c.execute(
                "UPDATE i_runs SET status=?, finished_at_utc=?, exit_code=?, error=?, stdout_excerpt=?, stderr_excerpt=?, duration_s=?, result_keys=?, result_path=? WHERE run_id=?",
                (
                    status,
                    finished_at,
                    sandbox_result.exit_code,
                    sandbox_result.error,
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
    "version_to_dict",
]
