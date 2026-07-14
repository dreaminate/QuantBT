"""NonceLedger · 下单防重放去重表（T-018 / spine 06，INV-4，补洞 2）。

交易所侧 recvWindow 防不住【本地中继层】重放：被截获的合法中继请求可重放。本表 sqlite PRIMARY
KEY=nonce，第一次 check_and_consume → True 并落痕；重复 → False（REJECT_REPLAY）。触碰即留痕（R12）。
"""

from __future__ import annotations

import sqlite3
import threading
import hashlib
from datetime import UTC, datetime
from pathlib import Path

NONCE_DB_FILENAME = "nonce_ledger.sqlite"


class NonceLedger:
    def __init__(self, root: Path | str) -> None:
        self._root = Path(root)
        self._root.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(self._root / NONCE_DB_FILENAME, check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA busy_timeout=5000")   # 跨连接并发排队等锁，非立刻报错
        self._conn.execute(
            "CREATE TABLE IF NOT EXISTS nonces (nonce TEXT PRIMARY KEY, consumed_at_utc TEXT, context TEXT)"
        )
        self._conn.commit()

    @property
    def ledger_ref(self) -> str:
        canonical_path = str((self._root / NONCE_DB_FILENAME).resolve())
        return "nonce_ledger_" + hashlib.sha256(canonical_path.encode("utf-8")).hexdigest()

    def check_and_consume(self, nonce: str, *, context: str = "") -> bool:
        """第一次见 → True（消费成功）；已见过 → False（重放）。UNIQUE 兜底并发竞态。"""

        with self._lock:
            try:
                self._conn.execute(
                    "INSERT INTO nonces (nonce, consumed_at_utc, context) VALUES (?,?,?)",
                    (nonce, datetime.now(UTC).isoformat(), context),
                )
                self._conn.commit()
                return True
            except sqlite3.IntegrityError:
                return False                      # 已存在 = 重放

    def is_consumed(self, nonce: str) -> bool:
        with self._lock:
            row = self._conn.execute("SELECT 1 FROM nonces WHERE nonce=?", (nonce,)).fetchone()
        return row is not None

    def close(self) -> None:
        with self._lock:
            self._conn.close()


__all__ = ["NONCE_DB_FILENAME", "NonceLedger"]
