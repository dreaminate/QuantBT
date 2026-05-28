"""v0.8.6 · Mode 2 多轮对话持久化 (sqlite chat_conversations + chat_messages)。

按 GPT Pro patch1 §D.b/d 设计：
- thread 状态: thread_id + user_id + market_mode + active_run_id + active_strategy_id
- 5 步状态机的状态字段挂在 thread metadata
- 消息含 role (system/user/assistant) + content + metadata (RAG retrieval / tool calls)
- 不引入 vector DB，retrieval 走 glossary FTS5 + 本地 BM25 (Day 1 简化)
"""

from __future__ import annotations

import json
import sqlite3
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from secrets import token_urlsafe
from typing import Any, Iterable


class ChatError(Exception):
    """对话相关错误。"""


_SCHEMA = [
    """
    CREATE TABLE IF NOT EXISTS chat_conversations (
        thread_id TEXT PRIMARY KEY,
        user_id TEXT,
        market_mode TEXT,
        active_run_id TEXT,
        active_strategy_id TEXT,
        title TEXT NOT NULL DEFAULT '',
        state TEXT NOT NULL DEFAULT 'ENTER_THREAD',
        created_at_utc TEXT NOT NULL,
        updated_at_utc TEXT NOT NULL,
        metadata TEXT NOT NULL DEFAULT '{}'
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_chat_conv_user ON chat_conversations(user_id, updated_at_utc DESC)",
    """
    CREATE TABLE IF NOT EXISTS chat_messages (
        message_id TEXT PRIMARY KEY,
        thread_id TEXT NOT NULL,
        role TEXT NOT NULL,
        content TEXT NOT NULL,
        metadata TEXT NOT NULL DEFAULT '{}',
        created_at_utc TEXT NOT NULL,
        FOREIGN KEY (thread_id) REFERENCES chat_conversations(thread_id)
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_chat_msg_thread_time ON chat_messages(thread_id, created_at_utc)",
]


VALID_STATES = {
    "ENTER_THREAD",
    "RETRIEVE_CONTEXT",
    "SOCRATIC_DECISION",
    "ANSWER_OR_ACTION",
    "FOLLOW_UP_UPDATE",
}

VALID_MARKET_MODES = {"ashare_research", "binance_paper", "binance_testnet", "binance_live"}

VALID_ROLES = {"system", "user", "assistant", "tool"}


def _utc_now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


@dataclass
class ChatThread:
    thread_id: str
    user_id: str | None
    market_mode: str
    active_run_id: str | None
    active_strategy_id: str | None
    title: str
    state: str
    created_at_utc: str
    updated_at_utc: str
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class ChatMessage:
    message_id: str
    thread_id: str
    role: str
    content: str
    metadata: dict[str, Any]
    created_at_utc: str


def init_chat_db(db_path: Path) -> None:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(db_path) as c:
        for stmt in _SCHEMA:
            c.execute(stmt)
        c.commit()


class ChatService:
    def __init__(self, db_path: Path) -> None:
        self._db = db_path
        init_chat_db(db_path)

    def _conn(self) -> sqlite3.Connection:
        c = sqlite3.connect(self._db)
        c.row_factory = sqlite3.Row
        return c

    # ---------- thread ----------

    def start_thread(
        self,
        *,
        user_id: str | None,
        market_mode: str = "ashare_research",
        active_run_id: str | None = None,
        active_strategy_id: str | None = None,
        title: str = "",
    ) -> ChatThread:
        if market_mode not in VALID_MARKET_MODES:
            raise ChatError(f"market_mode 必须 ∈ {sorted(VALID_MARKET_MODES)}")
        thread_id = "thr_" + token_urlsafe(8)
        now = _utc_now()
        with self._conn() as c:
            c.execute(
                "INSERT INTO chat_conversations (thread_id, user_id, market_mode, active_run_id, active_strategy_id, title, state, created_at_utc, updated_at_utc) VALUES (?,?,?,?,?,?,?,?,?)",
                (thread_id, user_id, market_mode, active_run_id, active_strategy_id, title, "ENTER_THREAD", now, now),
            )
            c.commit()
        return self.get_thread(thread_id)

    def get_thread(self, thread_id: str) -> ChatThread:
        with self._conn() as c:
            r = c.execute("SELECT * FROM chat_conversations WHERE thread_id=?", (thread_id,)).fetchone()
        if not r:
            raise ChatError(f"thread not found: {thread_id}")
        d = dict(r)
        d["metadata"] = json.loads(d.get("metadata") or "{}")
        return ChatThread(**d)

    def list_threads(self, user_id: str, limit: int = 50) -> list[ChatThread]:
        with self._conn() as c:
            rows = c.execute(
                "SELECT * FROM chat_conversations WHERE user_id=? ORDER BY updated_at_utc DESC LIMIT ?",
                (user_id, limit),
            ).fetchall()
        out: list[ChatThread] = []
        for r in rows:
            d = dict(r)
            d["metadata"] = json.loads(d.get("metadata") or "{}")
            out.append(ChatThread(**d))
        return out

    def update_state(self, thread_id: str, state: str) -> None:
        if state not in VALID_STATES:
            raise ChatError(f"state 必须 ∈ {sorted(VALID_STATES)}")
        with self._conn() as c:
            c.execute(
                "UPDATE chat_conversations SET state=?, updated_at_utc=? WHERE thread_id=?",
                (state, _utc_now(), thread_id),
            )
            c.commit()

    def update_active_context(
        self,
        thread_id: str,
        *,
        active_run_id: str | None = None,
        active_strategy_id: str | None = None,
    ) -> None:
        with self._conn() as c:
            sets = []
            args: list[Any] = []
            if active_run_id is not None:
                sets.append("active_run_id=?")
                args.append(active_run_id)
            if active_strategy_id is not None:
                sets.append("active_strategy_id=?")
                args.append(active_strategy_id)
            if not sets:
                return
            sets.append("updated_at_utc=?")
            args.append(_utc_now())
            args.append(thread_id)
            c.execute(f"UPDATE chat_conversations SET {','.join(sets)} WHERE thread_id=?", args)
            c.commit()

    # ---------- messages ----------

    def add_message(
        self,
        thread_id: str,
        role: str,
        content: str,
        *,
        metadata: dict[str, Any] | None = None,
    ) -> ChatMessage:
        if role not in VALID_ROLES:
            raise ChatError(f"role 必须 ∈ {sorted(VALID_ROLES)}")
        # 校验 thread 存在
        self.get_thread(thread_id)
        message_id = "msg_" + token_urlsafe(8)
        now = _utc_now()
        meta_json = json.dumps(metadata or {}, ensure_ascii=False)
        with self._conn() as c:
            c.execute(
                "INSERT INTO chat_messages (message_id, thread_id, role, content, metadata, created_at_utc) VALUES (?,?,?,?,?,?)",
                (message_id, thread_id, role, content, meta_json, now),
            )
            c.execute(
                "UPDATE chat_conversations SET updated_at_utc=? WHERE thread_id=?",
                (now, thread_id),
            )
            c.commit()
        return ChatMessage(
            message_id=message_id,
            thread_id=thread_id,
            role=role,
            content=content,
            metadata=metadata or {},
            created_at_utc=now,
        )

    def list_messages(self, thread_id: str, limit: int = 100) -> list[ChatMessage]:
        with self._conn() as c:
            rows = c.execute(
                "SELECT * FROM chat_messages WHERE thread_id=? ORDER BY created_at_utc ASC, rowid ASC LIMIT ?",
                (thread_id, limit),
            ).fetchall()
        out: list[ChatMessage] = []
        for r in rows:
            d = dict(r)
            d["metadata"] = json.loads(d.get("metadata") or "{}")
            out.append(ChatMessage(**d))
        return out

    def compress_history(self, thread_id: str, *, max_messages: int = 6, max_chars: int = 800) -> str:
        """压缩历史成 800 token-equivalent 字符串供 system prompt 注入。"""
        msgs = self.list_messages(thread_id, limit=100)
        recent = msgs[-max_messages:]
        lines = []
        for m in recent:
            prefix = "用户" if m.role == "user" else "Agent" if m.role == "assistant" else m.role
            lines.append(f"{prefix}: {m.content[:200]}")
        joined = "\n".join(lines)
        return joined[-max_chars:]


def thread_to_dict(t: ChatThread) -> dict[str, Any]:
    return asdict(t)


def message_to_dict(m: ChatMessage) -> dict[str, Any]:
    return asdict(m)


__all__ = [
    "ChatError",
    "ChatMessage",
    "ChatService",
    "ChatThread",
    "VALID_MARKET_MODES",
    "VALID_ROLES",
    "VALID_STATES",
    "init_chat_db",
    "message_to_dict",
    "thread_to_dict",
]
