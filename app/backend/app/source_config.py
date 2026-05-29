"""数据平台 v2 · 数据源开关（市场级 + 源级两层，最大 DIY）。

落 sqlite（生产接 data/community.db；测试用 ":memory:"）。一个 (source_name, market) 是开关原子：
- 源级：``set_source_enabled(name, market, enabled)`` 开关单个 (源, 市场) 单元。
- 市场级：``set_market_enabled(market, enabled)`` 批量开关该市场下所有源（卷积）。

"屏蔽官方数据" = 把官方源（tushare / binance / crawler_*）在某市场标 disabled →
量化流程的可用字段宇宙就看不到它（通过 ``source_filter`` 注入 FieldCatalog）。

kind：``user`` 若 source_name 以 user_ 开头（用户自带源），否则 ``official``（含团队爬虫 crawler_*）。
"""

from __future__ import annotations

import sqlite3
import threading
from collections.abc import Callable
from datetime import UTC, datetime


def _kind_of(name: str) -> str:
    return "user" if str(name).startswith("user_") else "official"


class SourceConfigService:
    def __init__(self, db_path: str = ":memory:") -> None:
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._lock = threading.Lock()
        self._init()

    def _init(self) -> None:
        with self._lock:
            # WAL + busy_timeout：community.db 被 ~15 个服务共享，降低 "database is locked"
            try:
                self._conn.execute("PRAGMA journal_mode=WAL")
                self._conn.execute("PRAGMA busy_timeout=5000")
            except Exception:  # noqa: BLE001 - PRAGMA 失败不应阻断启动
                pass
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS data_sources (
                    name        TEXT NOT NULL,
                    market      TEXT NOT NULL,
                    kind        TEXT NOT NULL DEFAULT 'official',
                    enabled     INTEGER NOT NULL DEFAULT 1,
                    priority    INTEGER NOT NULL DEFAULT 100,
                    label       TEXT NOT NULL DEFAULT '',
                    updated_at  TEXT,
                    PRIMARY KEY (name, market)
                )
                """
            )
            self._conn.commit()

    @staticmethod
    def _mk(market: str | None) -> str:
        return market or ""

    def register(
        self,
        name: str,
        market: str | None,
        *,
        kind: str | None = None,
        priority: int = 100,
        label: str = "",
        enabled: bool = True,
    ) -> None:
        """登记一个 (源, 市场) 单元。已存在则只更新 kind/priority/label，**不覆盖用户已设的 enabled**。"""
        mk = self._mk(market)
        knd = kind or _kind_of(name)
        with self._lock:
            row = self._conn.execute(
                "SELECT kind, priority, label FROM data_sources WHERE name=? AND market=?", (name, mk)
            ).fetchone()
            now = datetime.now(UTC).isoformat()
            if row is None:
                self._conn.execute(
                    "INSERT INTO data_sources (name, market, kind, enabled, priority, label, updated_at)"
                    " VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (name, mk, knd, 1 if enabled else 0, priority, label, now),
                )
                self._conn.commit()
            elif (row[0], row[1], row[2]) != (knd, priority, label):
                # 仅在元数据真有变化时写，避免 sync_from_catalog 每次 GET 都对所有源写放大
                self._conn.execute(
                    "UPDATE data_sources SET kind=?, priority=?, label=?, updated_at=? WHERE name=? AND market=?",
                    (knd, priority, label, now, name, mk),
                )
                self._conn.commit()

    def set_source_enabled(self, name: str, market: str | None, enabled: bool) -> None:
        mk = self._mk(market)
        now = datetime.now(UTC).isoformat()
        with self._lock:
            cur = self._conn.execute(
                "UPDATE data_sources SET enabled=?, updated_at=? WHERE name=? AND market=?",
                (1 if enabled else 0, now, name, mk),
            )
            if cur.rowcount == 0:
                # upsert：未登记源也能被显式开关（否则因 is_enabled permissive 默认放行，"屏蔽"会静默失效）
                self._conn.execute(
                    "INSERT INTO data_sources (name, market, kind, enabled, priority, label, updated_at)"
                    " VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (name, mk, _kind_of(name), 1 if enabled else 0, 100, "", now),
                )
            self._conn.commit()

    def set_market_enabled(self, market: str | None, enabled: bool, *, kind: str | None = None) -> int:
        """市场级开关：批量开关该市场下所有源（可按 kind 过滤，如只关官方）。返回受影响行数。"""
        sql = "UPDATE data_sources SET enabled=?, updated_at=? WHERE market=?"
        params: list = [1 if enabled else 0, datetime.now(UTC).isoformat(), self._mk(market)]
        if kind is not None:
            sql += " AND kind=?"
            params.append(kind)
        with self._lock:
            cur = self._conn.execute(sql, params)
            self._conn.commit()
            return cur.rowcount

    def is_enabled(self, name: str, market: str | None = None) -> bool:
        """未登记的源默认放行（permissive），让新源在配置前即可用；显式禁用才屏蔽。"""
        with self._lock:
            row = self._conn.execute(
                "SELECT enabled FROM data_sources WHERE name=? AND market=?", (name, self._mk(market))
            ).fetchone()
        return True if row is None else bool(row[0])

    def list_sources(self, market: str | None = None) -> list[dict]:
        sql = "SELECT name, market, kind, enabled, priority, label FROM data_sources"
        params: list = []
        if market is not None:
            sql += " WHERE market=?"
            params.append(self._mk(market))
        sql += " ORDER BY market, kind, name"
        with self._lock:
            rows = self._conn.execute(sql, params).fetchall()
        return [
            {"name": r[0], "market": r[1], "kind": r[2], "enabled": bool(r[3]), "priority": r[4], "label": r[5]}
            for r in rows
        ]

    def tree(self) -> list[dict]:
        """市场 → 源 的两层树（给前端源开关 UI）。"""
        by_market: dict[str, dict] = {}
        for s in self.list_sources():
            node = by_market.setdefault(s["market"], {"market": s["market"], "enabled_any": False, "sources": []})
            node["sources"].append(s)
            if s["enabled"]:
                node["enabled_any"] = True
        return list(by_market.values())

    def source_filter(self) -> Callable[[str, str | None], bool]:
        """注入 FieldCatalog 的开关回调。"""
        return lambda name, market: self.is_enabled(name, market)

    def sync_from_catalog(self, catalog) -> None:
        """自动登记 catalog 当前所见的所有 (源, 市场) 单元（enabled_only=False 枚举全部）。"""
        for ds in catalog.list_datasets(enabled_only=False):
            self.register(ds.source_name, ds.market)


__all__ = ["SourceConfigService"]
