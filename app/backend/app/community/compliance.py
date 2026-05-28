"""v0.8.8.1 · 复现社区 post 合规检查 (W10)。

设计：
- 帖子含 attached_run_id 时，自动 snapshot 该 run 的 risk_summary 写入 post metadata
- 拒绝"收益承诺"类关键词（patch2 §A 风险章节："不许收益承诺"）
- 提供 compliance_check 复检 endpoint

不修改 c_posts 主表 schema，扩展信息存到独立 c_post_compliance 表。
"""

from __future__ import annotations

import json
import re
import sqlite3
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


# 禁用关键词（patch2 §A.f）
FORBIDDEN_PROFIT_PATTERNS = [
    r"保证.*收益",
    r"稳赚",
    r"必赚",
    r"包.*年.*[0-9].*%",
    r"100%.*盈利",
    r"无风险.*回报",
]


_SCHEMA = [
    """
    CREATE TABLE IF NOT EXISTS c_post_compliance (
        post_id TEXT PRIMARY KEY,
        attached_run_id TEXT,
        risk_summary_snapshot TEXT,
        forbidden_phrases_found TEXT NOT NULL DEFAULT '[]',
        passed INTEGER NOT NULL DEFAULT 1,
        checked_at_utc TEXT NOT NULL,
        FOREIGN KEY (post_id) REFERENCES c_posts(post_id)
    )
    """,
]


@dataclass
class ComplianceResult:
    post_id: str
    passed: bool
    attached_run_id: str | None
    risk_summary_snapshot: dict[str, Any] | None
    forbidden_phrases_found: list[str]
    checked_at_utc: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _utc_now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def init_compliance_db(db_path: Path) -> None:
    with sqlite3.connect(db_path) as c:
        for stmt in _SCHEMA:
            c.execute(stmt)
        c.commit()


def check_content_for_forbidden(content: str) -> list[str]:
    """检查 post content 是否含被禁的"收益承诺"短语。"""
    found: list[str] = []
    for pattern in FORBIDDEN_PROFIT_PATTERNS:
        if re.search(pattern, content):
            found.append(pattern)
    return found


class ComplianceService:
    def __init__(self, db_path: Path) -> None:
        self._db = db_path
        init_compliance_db(db_path)

    def _conn(self) -> sqlite3.Connection:
        c = sqlite3.connect(self._db)
        c.row_factory = sqlite3.Row
        return c

    def record_compliance(
        self,
        post_id: str,
        *,
        content: str,
        attached_run_id: str | None = None,
        risk_summary: dict[str, Any] | None = None,
    ) -> ComplianceResult:
        forbidden = check_content_for_forbidden(content)
        passed = len(forbidden) == 0
        now = _utc_now()
        with self._conn() as c:
            c.execute(
                "INSERT OR REPLACE INTO c_post_compliance "
                "(post_id, attached_run_id, risk_summary_snapshot, forbidden_phrases_found, passed, checked_at_utc) "
                "VALUES (?,?,?,?,?,?)",
                (
                    post_id,
                    attached_run_id,
                    json.dumps(risk_summary, ensure_ascii=False) if risk_summary else None,
                    json.dumps(forbidden, ensure_ascii=False),
                    int(passed),
                    now,
                ),
            )
            c.commit()
        return ComplianceResult(
            post_id=post_id,
            passed=passed,
            attached_run_id=attached_run_id,
            risk_summary_snapshot=risk_summary,
            forbidden_phrases_found=forbidden,
            checked_at_utc=now,
        )

    def get_compliance(self, post_id: str) -> ComplianceResult | None:
        with self._conn() as c:
            r = c.execute("SELECT * FROM c_post_compliance WHERE post_id=?", (post_id,)).fetchone()
        if not r:
            return None
        return ComplianceResult(
            post_id=r["post_id"],
            passed=bool(r["passed"]),
            attached_run_id=r["attached_run_id"],
            risk_summary_snapshot=json.loads(r["risk_summary_snapshot"]) if r["risk_summary_snapshot"] else None,
            forbidden_phrases_found=json.loads(r["forbidden_phrases_found"] or "[]"),
            checked_at_utc=r["checked_at_utc"],
        )


__all__ = [
    "ComplianceResult",
    "ComplianceService",
    "FORBIDDEN_PROFIT_PATTERNS",
    "check_content_for_forbidden",
    "init_compliance_db",
]
