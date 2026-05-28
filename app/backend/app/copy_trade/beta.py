"""v0.8.9 · Copy-trade beta gate (W11 跟单灰度)。

用户决策上限: **5 master / 50 follower** beta 阶段开放。
超出 → 进 waitlist 不立刻 enable。

idempotency: signal_id + follower_id 已 dispatched 则拒绝重复（防 master 信号
重发 / 网络重试导致重复下单）。

follower override: master 信号上 leverage 10x，follower 自己设 max_leverage=2x →
SignalRelayer 必须硬截断到 follower 自己的 cap，不接受 master 信号原值。
"""

from __future__ import annotations

import sqlite3
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


class BetaQuotaError(Exception):
    pass


class IdempotencyViolation(Exception):
    pass


BETA_MASTER_QUOTA = 5
BETA_FOLLOWER_QUOTA = 50


_SCHEMA = [
    """
    CREATE TABLE IF NOT EXISTS ct_dispatches (
        idempotency_key TEXT PRIMARY KEY,
        signal_id TEXT NOT NULL,
        follower_id TEXT NOT NULL,
        master_id TEXT NOT NULL,
        dispatched_at_utc TEXT NOT NULL,
        master_leverage REAL,
        follower_applied_leverage REAL,
        clamped INTEGER NOT NULL DEFAULT 0,
        UNIQUE (signal_id, follower_id)
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_dispatches_signal ON ct_dispatches(signal_id)",
    "CREATE INDEX IF NOT EXISTS idx_dispatches_follower ON ct_dispatches(follower_id, dispatched_at_utc DESC)",
    """
    CREATE TABLE IF NOT EXISTS ct_beta_status (
        user_id TEXT NOT NULL,
        role TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'waitlist',
        joined_at_utc TEXT NOT NULL,
        PRIMARY KEY (user_id, role)
    )
    """,
]


@dataclass
class DispatchRecord:
    idempotency_key: str
    signal_id: str
    follower_id: str
    master_id: str
    dispatched_at_utc: str
    master_leverage: float | None
    follower_applied_leverage: float | None
    clamped: bool

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class BetaStatus:
    user_id: str
    role: str  # master / follower
    status: str  # waitlist / enabled / blocked
    joined_at_utc: str
    quota_used: int
    quota_limit: int

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _utc_now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def init_beta_db(db_path: Path) -> None:
    with sqlite3.connect(db_path) as c:
        for stmt in _SCHEMA:
            c.execute(stmt)
        c.commit()


class CopyTradeBetaService:
    def __init__(self, db_path: Path) -> None:
        self._db = db_path
        init_beta_db(db_path)

    def _conn(self) -> sqlite3.Connection:
        c = sqlite3.connect(self._db)
        c.row_factory = sqlite3.Row
        return c

    # ---------- idempotency ----------

    def make_idempotency_key(self, signal_id: str, follower_id: str) -> str:
        return f"{signal_id}::{follower_id}"

    def is_dispatched(self, signal_id: str, follower_id: str) -> bool:
        with self._conn() as c:
            row = c.execute(
                "SELECT 1 FROM ct_dispatches WHERE signal_id=? AND follower_id=?",
                (signal_id, follower_id),
            ).fetchone()
        return row is not None

    def record_dispatch(
        self,
        signal_id: str,
        follower_id: str,
        master_id: str,
        *,
        master_leverage: float | None = None,
        follower_applied_leverage: float | None = None,
        clamped: bool = False,
    ) -> DispatchRecord:
        if self.is_dispatched(signal_id, follower_id):
            raise IdempotencyViolation(
                f"signal_id={signal_id} follower_id={follower_id} already dispatched"
            )
        key = self.make_idempotency_key(signal_id, follower_id)
        now = _utc_now()
        with self._conn() as c:
            c.execute(
                "INSERT INTO ct_dispatches (idempotency_key, signal_id, follower_id, master_id, dispatched_at_utc, master_leverage, follower_applied_leverage, clamped) VALUES (?,?,?,?,?,?,?,?)",
                (key, signal_id, follower_id, master_id, now, master_leverage, follower_applied_leverage, int(clamped)),
            )
            c.commit()
        return DispatchRecord(
            idempotency_key=key, signal_id=signal_id, follower_id=follower_id,
            master_id=master_id, dispatched_at_utc=now,
            master_leverage=master_leverage,
            follower_applied_leverage=follower_applied_leverage,
            clamped=clamped,
        )

    def list_dispatches(self, follower_id: str, *, limit: int = 50) -> list[DispatchRecord]:
        with self._conn() as c:
            rows = c.execute(
                "SELECT * FROM ct_dispatches WHERE follower_id=? ORDER BY dispatched_at_utc DESC LIMIT ?",
                (follower_id, limit),
            ).fetchall()
        return [
            DispatchRecord(
                idempotency_key=r["idempotency_key"],
                signal_id=r["signal_id"],
                follower_id=r["follower_id"],
                master_id=r["master_id"],
                dispatched_at_utc=r["dispatched_at_utc"],
                master_leverage=r["master_leverage"],
                follower_applied_leverage=r["follower_applied_leverage"],
                clamped=bool(r["clamped"]),
            )
            for r in rows
        ]

    # ---------- beta gate ----------

    def apply_for_beta(self, user_id: str, role: str) -> BetaStatus:
        if role not in ("master", "follower"):
            raise ValueError("role must be master or follower")
        with self._conn() as c:
            # 当前已 enabled 的同 role 用户数
            enabled_cnt = c.execute(
                "SELECT COUNT(*) FROM ct_beta_status WHERE role=? AND status='enabled'",
                (role,),
            ).fetchone()[0]
            quota_limit = BETA_MASTER_QUOTA if role == "master" else BETA_FOLLOWER_QUOTA
            target_status = "enabled" if enabled_cnt < quota_limit else "waitlist"

            existing = c.execute(
                "SELECT * FROM ct_beta_status WHERE user_id=? AND role=?",
                (user_id, role),
            ).fetchone()
            if existing:
                return BetaStatus(
                    user_id=user_id, role=role,
                    status=existing["status"],
                    joined_at_utc=existing["joined_at_utc"],
                    quota_used=enabled_cnt,
                    quota_limit=quota_limit,
                )
            now = _utc_now()
            c.execute(
                "INSERT INTO ct_beta_status (user_id, role, status, joined_at_utc) VALUES (?,?,?,?)",
                (user_id, role, target_status, now),
            )
            c.commit()
            return BetaStatus(
                user_id=user_id, role=role, status=target_status, joined_at_utc=now,
                quota_used=enabled_cnt + (1 if target_status == "enabled" else 0),
                quota_limit=quota_limit,
            )

    def get_beta_status(self, user_id: str, role: str) -> BetaStatus | None:
        with self._conn() as c:
            row = c.execute(
                "SELECT * FROM ct_beta_status WHERE user_id=? AND role=?",
                (user_id, role),
            ).fetchone()
            if not row:
                return None
            enabled_cnt = c.execute(
                "SELECT COUNT(*) FROM ct_beta_status WHERE role=? AND status='enabled'",
                (role,),
            ).fetchone()[0]
        quota_limit = BETA_MASTER_QUOTA if role == "master" else BETA_FOLLOWER_QUOTA
        return BetaStatus(
            user_id=row["user_id"], role=row["role"], status=row["status"],
            joined_at_utc=row["joined_at_utc"],
            quota_used=enabled_cnt, quota_limit=quota_limit,
        )

    def is_beta_enabled(self, user_id: str, role: str) -> bool:
        s = self.get_beta_status(user_id, role)
        return s is not None and s.status == "enabled"

    def waitlist_summary(self) -> dict[str, Any]:
        with self._conn() as c:
            rows = c.execute(
                "SELECT role, status, COUNT(*) as cnt FROM ct_beta_status GROUP BY role, status"
            ).fetchall()
        out: dict[str, Any] = {
            "master": {"enabled": 0, "waitlist": 0, "blocked": 0, "quota": BETA_MASTER_QUOTA},
            "follower": {"enabled": 0, "waitlist": 0, "blocked": 0, "quota": BETA_FOLLOWER_QUOTA},
        }
        for r in rows:
            if r["role"] in out:
                out[r["role"]][r["status"]] = r["cnt"]
        return out


def apply_follower_leverage_cap(
    master_leverage: float | None,
    follower_max_leverage: float | None,
) -> tuple[float | None, bool]:
    """硬截断 follower leverage 到自己的 cap。

    返回 (applied_leverage, was_clamped)
    """
    if master_leverage is None:
        return None, False
    if follower_max_leverage is None or follower_max_leverage <= 0:
        return master_leverage, False
    if master_leverage > follower_max_leverage:
        return follower_max_leverage, True
    return master_leverage, False


__all__ = [
    "BETA_FOLLOWER_QUOTA",
    "BETA_MASTER_QUOTA",
    "BetaQuotaError",
    "BetaStatus",
    "CopyTradeBetaService",
    "DispatchRecord",
    "IdempotencyViolation",
    "apply_follower_leverage_cap",
    "init_beta_db",
]
