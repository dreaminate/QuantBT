"""脊柱内核 01 · durable 工件 store（内容寻址，按 node_id 落盘）。

durable execution 的执行层（决策 R11）：`exists(node_id)` 命中即【复用工件、绝不重跑】。
内容寻址——node_id 就是地址（与谱系 content_hash 同哈希族，00-contracts C7）。

诚实边界（R12，刻进实现）：本地开放落盘【无真访问控制边界】，本 store 只做「防自欺 + 触碰留痕」
（记 access 次数/时间），**不防恶意篡改**——谁能写盘谁就能改工件。措辞绝不说「防篡改/安全」。
durable ≠ reproducible：命中复用让重放稳定，不等于重跑能逐位重现（dossier §7）。
"""

from __future__ import annotations

import json
import sqlite3
import threading
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ARTIFACT_STORE_DB_FILENAME = "artifacts.sqlite"


def _now() -> str:
    return datetime.now(UTC).isoformat()


@dataclass
class ArtifactMeta:
    node_id: str
    created_at_utc: str
    access_count: int          # 触碰留痕（R12 防自欺，非防恶意）
    last_access_utc: str | None


class ArtifactStore:
    """按 node_id 内容寻址的工件 store。SQLite 索引 + JSON blob（单用户中低频，blob 入库够用）。"""

    def __init__(self, root: Path | str) -> None:
        self._root = Path(root)
        self._root.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(self._root / ARTIFACT_STORE_DB_FILENAME, check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA busy_timeout=5000")   # 跨连接并发写排队等锁，非立刻报错
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS artifacts (
                node_id TEXT PRIMARY KEY,
                blob TEXT NOT NULL,
                created_at_utc TEXT NOT NULL,
                access_count INTEGER NOT NULL DEFAULT 0,
                last_access_utc TEXT
            )
            """
        )
        self._conn.commit()

    def exists(self, node_id: str) -> bool:
        with self._lock:
            row = self._conn.execute("SELECT 1 FROM artifacts WHERE node_id=?", (node_id,)).fetchone()
        return row is not None

    def put(self, node_id: str, value: Any) -> None:
        """落工件。已存在则【不覆盖】（内容寻址：同 node_id 即同内容，覆盖无意义且可疑）。"""

        blob = json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)
        with self._lock:
            self._conn.execute(
                "INSERT INTO artifacts (node_id, blob, created_at_utc) VALUES (?,?,?) "
                "ON CONFLICT(node_id) DO NOTHING",
                (node_id, blob, _now()),
            )
            self._conn.commit()

    def get(self, node_id: str) -> Any:
        """读工件并记触碰（access_count +1）。不存在 raise KeyError。"""

        with self._lock:
            row = self._conn.execute("SELECT blob FROM artifacts WHERE node_id=?", (node_id,)).fetchone()
            if row is None:
                raise KeyError(f"工件不存在: {node_id}")
            self._conn.execute(
                "UPDATE artifacts SET access_count=access_count+1, last_access_utc=? WHERE node_id=?",
                (_now(), node_id),
            )
            self._conn.commit()
        return json.loads(row[0])

    def discard(self, node_id: str) -> None:
        """丢弃工件（rollback 用：撤销某 pure 节点之后的工件，使其下次重算）。"""

        with self._lock:
            self._conn.execute("DELETE FROM artifacts WHERE node_id=?", (node_id,))
            self._conn.commit()

    def meta(self, node_id: str) -> ArtifactMeta | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT node_id, created_at_utc, access_count, last_access_utc FROM artifacts WHERE node_id=?",
                (node_id,),
            ).fetchone()
        return ArtifactMeta(*row) if row else None

    def close(self) -> None:
        with self._lock:
            self._conn.close()


__all__ = ["ARTIFACT_STORE_DB_FILENAME", "ArtifactMeta", "ArtifactStore"]
