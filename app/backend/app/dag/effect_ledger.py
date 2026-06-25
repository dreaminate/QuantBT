"""脊柱内核 01 · effectful 节点统一幂等账（泛化 copy_trade/beta.py 的 ct_dispatches）。

为什么（决策 R10 / M17 教训）：跟单中继曾绕过幂等护栏重发单。根因是「幂等账只长在跟单这一处」。
内核把 `copy_trade/beta.py:113-152` 的「is_dispatched → record_dispatch + UNIQUE 兜底」三件套
**泛化成单键 `effect_idempotency_key`**，让【所有】触达券商/资金的 effectful 节点（实盘下单/提币/桥/
中继）都走同一道幂等闸——不止跟单。copy_trade 保持现状不回退（它继续用自己的 `ct_dispatches`）；
本账是平行的、口径与 beta.py 一致（00-contracts C8：业务级 client_order_id/transfer_request_id）。

诚实边界：本账只防「同一副作用被重复提交」（幂等），不防「该不该提交」（那是安全门 06 / 审批门 07）。
"""

from __future__ import annotations

import sqlite3
import threading
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

EFFECT_LEDGER_DB_FILENAME = "effect_ledger.sqlite"


class EffectIdempotencyViolation(Exception):
    """record 时 UNIQUE(effect_idempotency_key) 冲突——并发重复提交的兜底信号（同 beta.py:26）。"""


@dataclass
class EffectRecord:
    effect_idempotency_key: str
    node_id: str
    venue_ref: str | None
    recorded_at_utc: str


def _now() -> str:
    return datetime.now(UTC).isoformat()


class EffectLedger:
    """所有 effectful 节点的统一幂等账。SQLite，PRIMARY KEY(effect_idempotency_key)。

    用法与 copy_trade 一致：消费方先 `is_consumed(key)`，命中即跳过（绝不重发副作用）；
    副作用成功后 `record(key, node_id, venue_ref)`；并发竞态由 UNIQUE 主键兜底抛
    `EffectIdempotencyViolation`（已发生的副作用不回滚，仅记冲突供复盘——同 executor.py:156-160）。
    """

    def __init__(self, root: Path | str, *, busy_timeout_ms: int = 5000) -> None:
        self._root = Path(root)
        self._root.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(self._root / EFFECT_LEDGER_DB_FILENAME, check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL")
        # busy_timeout：跨连接（多实例/多进程）并发写时排队等锁，而非立刻 "database is locked"。
        # 对幂等账尤其要紧——record 因锁失败会让副作用「已发生未记账」，重试时可能重发（M17 雷）。
        # 可配（默认 5000=生产不变）：高争用压力测试可调小让 loser 快速失败（不变量 at-most-one 不受影响、
        # 只改 loser 是 OperationalError 还是 IntegrityError；避免负载下 8 连接各等满 5s 把测试饿死，见 pytest.ini timeout）。
        self._conn.execute(f"PRAGMA busy_timeout={int(busy_timeout_ms)}")
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS effect_dispatches (
                effect_idempotency_key TEXT PRIMARY KEY,
                node_id TEXT NOT NULL,
                venue_ref TEXT,
                recorded_at_utc TEXT NOT NULL
            )
            """
        )
        self._conn.commit()

    def is_consumed(self, key: str) -> bool:
        with self._lock:
            row = self._conn.execute(
                "SELECT 1 FROM effect_dispatches WHERE effect_idempotency_key=?", (key,)
            ).fetchone()
        return row is not None

    def record(self, key: str, node_id: str, venue_ref: str | None = None) -> EffectRecord:
        now = _now()
        with self._lock:
            try:
                self._conn.execute(
                    "INSERT INTO effect_dispatches (effect_idempotency_key, node_id, venue_ref, recorded_at_utc) "
                    "VALUES (?,?,?,?)",
                    (key, node_id, venue_ref, now),
                )
                self._conn.commit()
            except sqlite3.IntegrityError as exc:
                raise EffectIdempotencyViolation(
                    f"effect_idempotency_key={key!r} 已记录（疑似并发重复提交）"
                ) from exc
        return EffectRecord(effect_idempotency_key=key, node_id=node_id, venue_ref=venue_ref, recorded_at_utc=now)

    def get(self, key: str) -> EffectRecord | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT effect_idempotency_key, node_id, venue_ref, recorded_at_utc "
                "FROM effect_dispatches WHERE effect_idempotency_key=?",
                (key,),
            ).fetchone()
        return EffectRecord(*row) if row else None

    def close(self) -> None:
        with self._lock:
            self._conn.close()


__all__ = ["EFFECT_LEDGER_DB_FILENAME", "EffectIdempotencyViolation", "EffectLedger", "EffectRecord"]
