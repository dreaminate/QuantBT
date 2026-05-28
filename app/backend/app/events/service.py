"""Event 埋点服务 (sqlite，单表)。

设计目标：
- 最小可用：能写入 events + 能 SQL 查询 funnel
- 暂不引入 PostHog/Segment 等 SDK
- 前端通过 POST /api/events/track 主动触发；后端关键事件可在 endpoint 内直接调
"""

from __future__ import annotations

import json
import sqlite3
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from secrets import token_urlsafe
from typing import Any


class EventTrackError(Exception):
    """事件写入校验失败。"""


@dataclass
class EventRecord:
    event_id: str
    user_id: str | None
    anonymous_id: str | None
    session_id: str | None
    event_name: str
    occurred_at: str
    app_version: str | None
    market_mode: str | None
    properties: dict[str, Any]


_SCHEMA = [
    """
    CREATE TABLE IF NOT EXISTS events (
        event_id TEXT PRIMARY KEY,
        user_id TEXT,
        anonymous_id TEXT,
        session_id TEXT,
        event_name TEXT NOT NULL,
        occurred_at TEXT NOT NULL,
        app_version TEXT,
        market_mode TEXT,
        properties TEXT NOT NULL
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_events_user_time ON events(user_id, occurred_at)",
    "CREATE INDEX IF NOT EXISTS idx_events_name_time ON events(event_name, occurred_at)",
    "CREATE INDEX IF NOT EXISTS idx_events_user_name_time ON events(user_id, event_name, occurred_at)",
]


# v0.8.4 baseline 允许的事件名（防止前端瞎传）；v0.8.6 扩 10 条全集
ALLOWED_EVENT_NAMES: set[str] = {
    "run_detail_viewed",
    "risk_metric_expanded",
    "glossary_term_viewed",
    "risk_summary_shown",
    # patch1 §H.b 列出的另外 6 个事件保留 v0.8.6 接入
    "user_registered",
    "first_a_share_demo_started",
    "run_started",
    "run_completed",
    "strategy_parameter_modified",
    "safekey_check_completed",
    "testnet_order_e2e_completed",
    "kill_switch_triggered",
}


def init_events_db(db_path: Path) -> None:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(db_path) as c:
        for stmt in _SCHEMA:
            c.execute(stmt)
        c.commit()


class EventService:
    def __init__(self, db_path: Path) -> None:
        self._db = db_path
        init_events_db(db_path)

    def _conn(self) -> sqlite3.Connection:
        c = sqlite3.connect(self._db)
        c.row_factory = sqlite3.Row
        return c

    def track(
        self,
        event_name: str,
        *,
        user_id: str | None = None,
        anonymous_id: str | None = None,
        session_id: str | None = None,
        app_version: str | None = None,
        market_mode: str | None = None,
        properties: dict[str, Any] | None = None,
    ) -> EventRecord:
        if not event_name or not isinstance(event_name, str):
            raise EventTrackError("event_name 必填")
        if event_name not in ALLOWED_EVENT_NAMES:
            raise EventTrackError(f"event_name {event_name!r} 不在白名单")
        if properties is not None and not isinstance(properties, dict):
            raise EventTrackError("properties 必须是 dict")
        rec = EventRecord(
            event_id="evt_" + token_urlsafe(8),
            user_id=user_id,
            anonymous_id=anonymous_id,
            session_id=session_id,
            event_name=event_name,
            occurred_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            app_version=app_version,
            market_mode=market_mode,
            properties=properties or {},
        )
        with self._conn() as c:
            c.execute(
                "INSERT INTO events (event_id, user_id, anonymous_id, session_id, event_name, occurred_at, app_version, market_mode, properties) VALUES (?,?,?,?,?,?,?,?,?)",
                (
                    rec.event_id,
                    rec.user_id,
                    rec.anonymous_id,
                    rec.session_id,
                    rec.event_name,
                    rec.occurred_at,
                    rec.app_version,
                    rec.market_mode,
                    json.dumps(rec.properties, ensure_ascii=False),
                ),
            )
            c.commit()
        return rec

    def count(self, event_name: str | None = None) -> int:
        with self._conn() as c:
            if event_name:
                row = c.execute("SELECT COUNT(*) FROM events WHERE event_name=?", (event_name,)).fetchone()
            else:
                row = c.execute("SELECT COUNT(*) FROM events").fetchone()
        return int(row[0]) if row else 0

    def recent(self, limit: int = 50) -> list[dict[str, Any]]:
        with self._conn() as c:
            # 同秒插入时用 rowid 作为 tiebreaker，保证 newest-first 稳定
            rows = c.execute(
                "SELECT * FROM events ORDER BY occurred_at DESC, rowid DESC LIMIT ?",
                (limit,),
            ).fetchall()
        out: list[dict[str, Any]] = []
        for r in rows:
            d = dict(r)
            try:
                d["properties"] = json.loads(d["properties"])
            except Exception:  # noqa: BLE001
                d["properties"] = {}
            out.append(d)
        return out


def event_to_dict(rec: EventRecord) -> dict[str, Any]:
    return asdict(rec)


__all__ = ["ALLOWED_EVENT_NAMES", "EventRecord", "EventService", "EventTrackError", "event_to_dict", "init_events_db"]
