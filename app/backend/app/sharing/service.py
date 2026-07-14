"""Sharing service · 策略发布 / fork / 排行榜（参考聚宽社区）。

数据库与 auth + community 共享同一 sqlite；表前缀 `s_`。

工作流：
1. 用户跑完一个 backtest 得到 run_id（落在 data/artifacts/experiments/）
2. 调 publish_strategy(run_id, ...) 写入 s_strategies 表 → public 列设 1
3. 他人通过 /api/sharing/feed 看到 + 可调用 fork_strategy 复制
   - fork 仅复制 metadata（不复制 run artifact）；新 share 记录 fork_from_share_id
   - fork_count 在原 share 上 +1
4. leaderboard 按 metrics 排序（sharpe / total_return / pbo / dsr 等）
"""

from __future__ import annotations

import json
import secrets
import sqlite3
import threading
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from ..lineage.ids import canonical_json, content_hash


def _now() -> str:
    return datetime.now(UTC).isoformat()


@dataclass
class SharedStrategy:
    share_id: str
    run_id: str
    author_id: str
    title: str
    description: str = ""
    tags: list[str] = field(default_factory=list)
    asset_class: str = ""
    public: bool = True
    fork_from_share_id: str | None = None
    forks: int = 0
    likes: int = 0
    created_at_utc: str = ""
    # 冗余的 metrics（snapshot，避免每次 list 都去读 run.json）
    metric_sharpe: float | None = None
    metric_total_return: float | None = None
    metric_max_drawdown: float | None = None
    metric_pbo: float | None = None
    metric_dsr: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            **asdict(self),
            "shared_asset_ref": shared_strategy_asset_ref(self),
            "permission_ref": shared_strategy_permission(self).permission_ref,
            "source_ref": shared_strategy_source(self).source_ref,
            "status_ref": shared_strategy_status(self).status_ref,
        }


@dataclass(frozen=True)
class SharedAssetPermissionRecord:
    permission_ref: str
    shared_asset_ref: str
    owner_user_id: str
    visibility: str
    may_fork: bool


@dataclass(frozen=True)
class SharedAssetSourceRecord:
    source_ref: str
    shared_asset_ref: str
    owner_user_id: str
    run_id: str
    fork_from_share_id: str | None
    asset_class: str


@dataclass(frozen=True)
class SharedAssetStatusRecord:
    status_ref: str
    shared_asset_ref: str
    owner_user_id: str
    status: str


def shared_strategy_asset_ref(strategy: SharedStrategy) -> str:
    return "shared_asset:" + content_hash(
        {
            "share_id": strategy.share_id,
            "run_id": strategy.run_id,
            "author_id": strategy.author_id,
        }
    )


def shared_strategy_permission(strategy: SharedStrategy) -> SharedAssetPermissionRecord:
    asset_ref = shared_strategy_asset_ref(strategy)
    visibility = "public" if strategy.public else "owner_only"
    payload = {
        "shared_asset_ref": asset_ref,
        "owner_user_id": strategy.author_id,
        "visibility": visibility,
        "may_fork": bool(strategy.public),
    }
    return SharedAssetPermissionRecord(
        permission_ref="permission:" + content_hash(payload),
        **payload,
    )


def shared_strategy_source(strategy: SharedStrategy) -> SharedAssetSourceRecord:
    asset_ref = shared_strategy_asset_ref(strategy)
    payload = {
        "shared_asset_ref": asset_ref,
        "owner_user_id": strategy.author_id,
        "run_id": strategy.run_id,
        "fork_from_share_id": strategy.fork_from_share_id,
        "asset_class": strategy.asset_class,
    }
    return SharedAssetSourceRecord(
        source_ref="source:" + content_hash(payload),
        **payload,
    )


def shared_strategy_status(strategy: SharedStrategy) -> SharedAssetStatusRecord:
    asset_ref = shared_strategy_asset_ref(strategy)
    payload = {
        "shared_asset_ref": asset_ref,
        "owner_user_id": strategy.author_id,
        "status": "published_public" if strategy.public else "published_private",
    }
    return SharedAssetStatusRecord(
        status_ref="status:" + content_hash(payload),
        **payload,
    )


_INIT_LOCK = threading.Lock()
_INITIALIZED: set[str] = set()


def init_sharing_db(db_path: Path) -> None:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    key = str(db_path.resolve()) + "#sharing"
    with _INIT_LOCK:
        if key in _INITIALIZED:
            return
        conn = sqlite3.connect(str(db_path))
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS s_strategies (
                share_id TEXT PRIMARY KEY,
                run_id TEXT NOT NULL,
                author_id TEXT NOT NULL,
                title TEXT NOT NULL,
                description TEXT DEFAULT '',
                tags TEXT,
                asset_class TEXT DEFAULT '',
                public INTEGER DEFAULT 1,
                fork_from_share_id TEXT,
                forks INTEGER DEFAULT 0,
                likes INTEGER DEFAULT 0,
                created_at_utc TEXT NOT NULL,
                metric_sharpe REAL,
                metric_total_return REAL,
                metric_max_drawdown REAL,
                metric_pbo REAL,
                metric_dsr REAL
            );
            CREATE INDEX IF NOT EXISTS idx_shares_author ON s_strategies(author_id);
            CREATE INDEX IF NOT EXISTS idx_shares_public ON s_strategies(public);
            CREATE INDEX IF NOT EXISTS idx_shares_run ON s_strategies(run_id);

            CREATE TABLE IF NOT EXISTS s_publish_idempotency (
                author_id TEXT NOT NULL,
                idempotency_key TEXT NOT NULL,
                request_payload TEXT NOT NULL,
                share_id TEXT NOT NULL UNIQUE,
                created_at_utc TEXT NOT NULL,
                PRIMARY KEY (author_id, idempotency_key),
                FOREIGN KEY (share_id) REFERENCES s_strategies(share_id)
            );

            CREATE TABLE IF NOT EXISTS s_likes (
                user_id TEXT NOT NULL,
                share_id TEXT NOT NULL,
                created_at_utc TEXT NOT NULL,
                PRIMARY KEY (user_id, share_id)
            );
            """
        )
        conn.close()
        _INITIALIZED.add(key)


class SharingService:
    def __init__(self, db_path: Path, run_root: Path) -> None:
        self._db_path = db_path
        self._run_root = run_root
        init_sharing_db(db_path)

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self._db_path), isolation_level=None)
        conn.row_factory = sqlite3.Row
        return conn

    def _snapshot_metrics(self, run_id: str) -> dict[str, float | None]:
        out = {
            "metric_sharpe": None,
            "metric_total_return": None,
            "metric_max_drawdown": None,
            "metric_pbo": None,
            "metric_dsr": None,
        }
        run_dir = self._run_root / run_id
        manifest = run_dir / "run.json"
        if not manifest.exists():
            return out
        try:
            data = json.loads(manifest.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            return out
        m = data.get("metrics") or {}
        out["metric_sharpe"] = _maybe_float(m.get("sharpe"))
        out["metric_total_return"] = _maybe_float(m.get("total_return"))
        out["metric_max_drawdown"] = _maybe_float(m.get("max_drawdown"))
        pbo = m.get("pbo")
        if isinstance(pbo, dict):
            out["metric_pbo"] = _maybe_float(pbo.get("pbo"))
        elif pbo is not None:
            out["metric_pbo"] = _maybe_float(pbo)
        out["metric_dsr"] = _maybe_float(m.get("deflated_sharpe"))
        return out

    def publish_strategy(
        self,
        run_id: str,
        author_id: str,
        title: str,
        *,
        description: str = "",
        tags: list[str] | None = None,
        asset_class: str = "",
        public: bool = True,
        fork_from_share_id: str | None = None,
        idempotency_key: str | None = None,
    ) -> SharedStrategy:
        if not (self._run_root / run_id).exists():
            raise ValueError(f"run_id 不存在: {run_id}")
        normalized_key: str | None = None
        if idempotency_key is not None:
            normalized_key = str(idempotency_key).strip()
            if not normalized_key:
                raise ValueError("idempotency_key 不能为空")
            if len(normalized_key) > 512:
                raise ValueError("idempotency_key 不能超过 512 字符")
        request_payload = canonical_json(
            {
                "run_id": run_id,
                "author_id": author_id,
                "title": title,
                "description": description,
                "tags": tags or [],
                "asset_class": asset_class,
                "public": bool(public),
                "fork_from_share_id": fork_from_share_id,
            }
        )
        metrics = self._snapshot_metrics(run_id)
        conn = self._conn()
        try:
            # Serialize the idempotency claim and the business write in one
            # SQLite transaction.  A concurrent identical retry observes the
            # first committed mapping instead of creating a second share.
            conn.execute("BEGIN IMMEDIATE")
            if normalized_key is not None:
                claim = conn.execute(
                    "SELECT request_payload, share_id FROM s_publish_idempotency "
                    "WHERE author_id=? AND idempotency_key=?",
                    (author_id, normalized_key),
                ).fetchone()
                if claim is not None:
                    if claim["request_payload"] != request_payload:
                        raise ValueError(
                            "idempotency_key 已用于不同的策略发布请求"
                        )
                    existing = conn.execute(
                        "SELECT * FROM s_strategies WHERE share_id=?",
                        (claim["share_id"],),
                    ).fetchone()
                    if existing is None:
                        raise RuntimeError(
                            "idempotency claim references a missing shared strategy"
                        )
                    conn.commit()
                    return _row_to_strategy(existing)

            sid = f"share-{secrets.token_hex(8)}"
            now = _now()
            conn.execute(
                """
                INSERT INTO s_strategies (
                    share_id, run_id, author_id, title, description, tags, asset_class,
                    public, fork_from_share_id, created_at_utc,
                    metric_sharpe, metric_total_return, metric_max_drawdown, metric_pbo, metric_dsr
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    sid, run_id, author_id, title, description, json.dumps(tags or []), asset_class,
                    1 if public else 0, fork_from_share_id, now,
                    metrics["metric_sharpe"], metrics["metric_total_return"], metrics["metric_max_drawdown"],
                    metrics["metric_pbo"], metrics["metric_dsr"],
                ),
            )
            if normalized_key is not None:
                conn.execute(
                    "INSERT INTO s_publish_idempotency "
                    "(author_id, idempotency_key, request_payload, share_id, created_at_utc) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (author_id, normalized_key, request_payload, sid, now),
                )
            if fork_from_share_id:
                conn.execute("UPDATE s_strategies SET forks = forks + 1 WHERE share_id = ?", (fork_from_share_id,))
            row = conn.execute(
                "SELECT * FROM s_strategies WHERE share_id=?", (sid,)
            ).fetchone()
            if row is None:  # pragma: no cover - same-transaction invariant
                raise RuntimeError("shared strategy insert was not observable")
            conn.commit()
            return _row_to_strategy(row)
        except Exception:
            if conn.in_transaction:
                conn.rollback()
            raise
        finally:
            conn.close()

    def fork_strategy(self, share_id: str, new_author_id: str, *, title: str | None = None) -> SharedStrategy:
        original = self.get_strategy(share_id)
        if original is None:
            raise ValueError(f"share_id 不存在: {share_id}")
        new_title = title or f"Fork of {original.title}"
        return self.publish_strategy(
            run_id=original.run_id,
            author_id=new_author_id,
            title=new_title,
            description=f"Fork from {share_id} (run {original.run_id})",
            tags=original.tags + ["forked"],
            asset_class=original.asset_class,
            public=True,
            fork_from_share_id=share_id,
        )

    def get_strategy(self, share_id: str) -> SharedStrategy | None:
        conn = self._conn()
        try:
            row = conn.execute("SELECT * FROM s_strategies WHERE share_id = ?", (share_id,)).fetchone()
            if row is None:
                return None
            return _row_to_strategy(row)
        finally:
            conn.close()

    def _owned_strategy_by_ref(
        self,
        ref: str,
        *,
        owner_user_id: str,
        ref_getter: Any,
    ) -> SharedStrategy:
        owner = str(owner_user_id or "").strip()
        source_ref = str(ref or "").strip()
        if not owner or not source_ref:
            raise KeyError("shared asset ref and owner are required")
        matches = [
            strategy
            for strategy in self.list_strategies(
                author_id=owner,
                public_only=False,
                limit=100_000,
            )
            if ref_getter(strategy) == source_ref
        ]
        if len(matches) != 1:
            raise KeyError("shared asset source is missing, stale, or ambiguous")
        return matches[0]

    def shared_asset(self, ref: str, *, owner_user_id: str) -> SharedStrategy:
        return self._owned_strategy_by_ref(
            ref,
            owner_user_id=owner_user_id,
            ref_getter=shared_strategy_asset_ref,
        )

    def permission(
        self,
        ref: str,
        *,
        owner_user_id: str,
    ) -> SharedAssetPermissionRecord:
        strategy = self._owned_strategy_by_ref(
            ref,
            owner_user_id=owner_user_id,
            ref_getter=lambda item: shared_strategy_permission(item).permission_ref,
        )
        return shared_strategy_permission(strategy)

    def source(self, ref: str, *, owner_user_id: str) -> SharedAssetSourceRecord:
        strategy = self._owned_strategy_by_ref(
            ref,
            owner_user_id=owner_user_id,
            ref_getter=lambda item: shared_strategy_source(item).source_ref,
        )
        return shared_strategy_source(strategy)

    def status(self, ref: str, *, owner_user_id: str) -> SharedAssetStatusRecord:
        strategy = self._owned_strategy_by_ref(
            ref,
            owner_user_id=owner_user_id,
            ref_getter=lambda item: shared_strategy_status(item).status_ref,
        )
        return shared_strategy_status(strategy)

    def list_strategies(
        self,
        *,
        asset_class: str | None = None,
        author_id: str | None = None,
        sort_by: str = "recent",  # recent | sharpe | total_return | likes | forks
        limit: int = 50,
        offset: int = 0,
        public_only: bool = True,
    ) -> list[SharedStrategy]:
        order_map = {
            "recent": "created_at_utc DESC",
            "sharpe": "metric_sharpe DESC",
            "total_return": "metric_total_return DESC",
            "likes": "likes DESC, created_at_utc DESC",
            "forks": "forks DESC, created_at_utc DESC",
            "pbo_low": "metric_pbo ASC, metric_sharpe DESC",
        }
        order = order_map.get(sort_by, order_map["recent"])
        where: list[str] = []
        params: list[Any] = []
        if public_only:
            where.append("public = 1")
        if asset_class:
            where.append("asset_class = ?")
            params.append(asset_class)
        if author_id:
            where.append("author_id = ?")
            params.append(author_id)
        where_clause = ("WHERE " + " AND ".join(where)) if where else ""
        params.extend([limit, offset])
        conn = self._conn()
        try:
            rows = conn.execute(
                f"SELECT * FROM s_strategies {where_clause} ORDER BY {order} LIMIT ? OFFSET ?",
                params,
            ).fetchall()
            return [_row_to_strategy(r) for r in rows]
        finally:
            conn.close()

    def like(self, user_id: str, share_id: str) -> bool:
        conn = self._conn()
        try:
            try:
                conn.execute(
                    "INSERT INTO s_likes (user_id, share_id, created_at_utc) VALUES (?, ?, ?)",
                    (user_id, share_id, _now()),
                )
            except sqlite3.IntegrityError:
                return False
            conn.execute("UPDATE s_strategies SET likes = likes + 1 WHERE share_id = ?", (share_id,))
            return True
        finally:
            conn.close()

    def unlike(self, user_id: str, share_id: str) -> bool:
        conn = self._conn()
        try:
            cur = conn.execute(
                "DELETE FROM s_likes WHERE user_id = ? AND share_id = ?", (user_id, share_id)
            )
            if cur.rowcount > 0:
                conn.execute("UPDATE s_strategies SET likes = MAX(0, likes - 1) WHERE share_id = ?", (share_id,))
                return True
            return False
        finally:
            conn.close()

    def delete_strategy(self, share_id: str, author_id: str) -> bool:
        conn = self._conn()
        try:
            row = conn.execute("SELECT author_id FROM s_strategies WHERE share_id = ?", (share_id,)).fetchone()
            if row is None:
                return False
            if row["author_id"] != author_id:
                raise PermissionError("只能删自己发布的策略")
            conn.execute("DELETE FROM s_strategies WHERE share_id = ?", (share_id,))
            conn.execute("DELETE FROM s_likes WHERE share_id = ?", (share_id,))
            return True
        finally:
            conn.close()


def _maybe_float(v: Any) -> float | None:
    if v is None:
        return None
    try:
        f = float(v)
        if f != f:  # NaN
            return None
        return f
    except (TypeError, ValueError):
        return None


def _row_to_strategy(row: sqlite3.Row) -> SharedStrategy:
    tags: list[str] = []
    if row["tags"]:
        try:
            tags = json.loads(row["tags"])
        except Exception:  # noqa: BLE001
            tags = []
    return SharedStrategy(
        share_id=row["share_id"],
        run_id=row["run_id"],
        author_id=row["author_id"],
        title=row["title"],
        description=row["description"] or "",
        tags=tags,
        asset_class=row["asset_class"] or "",
        public=bool(row["public"]),
        fork_from_share_id=row["fork_from_share_id"],
        forks=row["forks"],
        likes=row["likes"],
        created_at_utc=row["created_at_utc"],
        metric_sharpe=row["metric_sharpe"],
        metric_total_return=row["metric_total_return"],
        metric_max_drawdown=row["metric_max_drawdown"],
        metric_pbo=row["metric_pbo"],
        metric_dsr=row["metric_dsr"],
    )
