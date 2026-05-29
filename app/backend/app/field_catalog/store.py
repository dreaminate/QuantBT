"""数据平台 v2 · 字段宇宙持久化表（field_catalog）。

把 FieldCatalog 动态算出的"可用字段宇宙"物化成一张 sqlite 表，服务三件事：
1. **拉取辅助**：Agent 查表即知有哪些字段/来源/数据种类，指导用户拉什么。
2. **写策略**：Agent 拿稳定字段名(official_*/用户字段) + 含义/单位写对策略。
3. **上游推送合并**：官方数据更新(B 通道)落地时的合并目标——manifest 带官方字段定义，
   客户端 ``merge_official`` upsert 进本表，与用户自带字段并存。

主键 (field_id, market)。``sync_from_catalog`` 从动态目录刷新（新字段插入、已有更新 last_seen、
人工/Agent 写的 description 非空则保留）。落 community.db；测试用 ":memory:"。
"""

from __future__ import annotations

import sqlite3
import threading
from datetime import UTC, datetime
from typing import Any

from .canonical import CANONICAL
from .sources import is_official_source


class FieldCatalogStore:
    def __init__(self, db_path: str = ":memory:") -> None:
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._lock = threading.Lock()
        self._init()

    def _init(self) -> None:
        with self._lock:
            try:
                self._conn.execute("PRAGMA journal_mode=WAL")
                self._conn.execute("PRAGMA busy_timeout=5000")
            except Exception:  # noqa: BLE001
                pass
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS field_catalog (
                    field_id      TEXT NOT NULL,
                    market        TEXT NOT NULL,
                    canonical_id  TEXT,
                    is_freeform   INTEGER NOT NULL DEFAULT 0,
                    is_official   INTEGER NOT NULL DEFAULT 0,
                    source        TEXT,
                    data_kind     TEXT,
                    raw_column    TEXT,
                    unit          TEXT NOT NULL DEFAULT '',
                    description   TEXT NOT NULL DEFAULT '',
                    field_group   TEXT NOT NULL DEFAULT '',
                    first_seen_at TEXT,
                    last_seen_at  TEXT,
                    PRIMARY KEY (field_id, market)
                )
                """
            )
            self._conn.commit()

    def upsert(
        self,
        *,
        field_id: str,
        market: str,
        canonical_id: str | None,
        is_freeform: bool,
        is_official: bool,
        source: str | None,
        data_kind: str | None,
        raw_column: str | None,
        unit: str = "",
        description: str = "",
        field_group: str = "",
    ) -> None:
        now = datetime.now(UTC).isoformat()
        with self._lock:
            # 已有 description 非空则保留（人工/Agent 可能补过含义），其余字段刷新，first_seen 不动
            self._conn.execute(
                """
                INSERT INTO field_catalog
                  (field_id, market, canonical_id, is_freeform, is_official, source, data_kind,
                   raw_column, unit, description, field_group, first_seen_at, last_seen_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(field_id, market) DO UPDATE SET
                  canonical_id=excluded.canonical_id,
                  is_freeform=excluded.is_freeform,
                  is_official=excluded.is_official,
                  source=excluded.source,
                  data_kind=excluded.data_kind,
                  raw_column=excluded.raw_column,
                  unit=excluded.unit,
                  description=CASE WHEN field_catalog.description != '' THEN field_catalog.description ELSE excluded.description END,
                  field_group=excluded.field_group,
                  last_seen_at=excluded.last_seen_at
                """,
                (
                    field_id, market, canonical_id, 1 if is_freeform else 0, 1 if is_official else 0,
                    source, data_kind, raw_column, unit, description, field_group, now, now,
                ),
            )
            self._conn.commit()

    def sync_from_catalog(self, catalog) -> int:
        """从动态 FieldCatalog 刷新本表（按 catalog 当前所见的市场逐个 available_fields）。返回 upsert 条数。"""
        datasets = catalog.list_datasets()
        dk_by_ds = {ds.dataset_id: ds.data_kind for ds in datasets}
        markets = sorted({ds.market for ds in datasets if ds.market})
        n = 0
        for market in markets:
            uni = catalog.available_fields(market)
            for is_free, bucket in ((False, uni.canonical), (True, uni.freeform)):
                for fid, e in bucket.items():
                    canonical_id = None if is_free else CANONICAL.resolve(e.raw_column, market)
                    cf = CANONICAL.get(canonical_id) if canonical_id else None
                    self.upsert(
                        field_id=fid,
                        market=market,
                        canonical_id=canonical_id,
                        is_freeform=is_free,
                        is_official=is_official_source(e.source_name),
                        source=e.source_name,
                        data_kind=dk_by_ds.get(e.dataset_id),
                        raw_column=e.raw_column,
                        unit=cf.unit if cf else "",
                        description=cf.description if cf else "",
                        field_group=cf.group if cf else "",
                    )
                    n += 1
        return n

    def merge_official(self, field_defs: list[dict[str, Any]]) -> int:
        """合并上游推送的官方字段定义（来自数据更新 manifest 的 official_fields）。"""
        n = 0
        for d in field_defs:
            fid = d.get("field_id")
            market = d.get("market")
            if not fid or not market:
                continue
            self.upsert(
                field_id=fid,
                market=market,
                canonical_id=d.get("canonical_id"),
                is_freeform=bool(d.get("is_freeform", False)),
                is_official=bool(d.get("is_official", True)),
                source=d.get("source"),
                data_kind=d.get("data_kind"),
                raw_column=d.get("raw_column"),
                unit=d.get("unit", "") or "",
                description=d.get("description", "") or "",
                field_group=d.get("field_group", "") or "",
            )
            n += 1
        return n

    def list(self, *, market: str | None = None, official: bool | None = None) -> list[dict[str, Any]]:
        sql = (
            "SELECT field_id, market, canonical_id, is_freeform, is_official, source, data_kind,"
            " raw_column, unit, description, field_group, first_seen_at, last_seen_at FROM field_catalog"
        )
        clauses: list[str] = []
        params: list[Any] = []
        if market is not None:
            clauses.append("market = ?")
            params.append(market)
        if official is not None:
            clauses.append("is_official = ?")
            params.append(1 if official else 0)
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY market, is_official DESC, field_id"
        with self._lock:
            rows = self._conn.execute(sql, params).fetchall()
        cols = ["field_id", "market", "canonical_id", "is_freeform", "is_official", "source", "data_kind",
                "raw_column", "unit", "description", "field_group", "first_seen_at", "last_seen_at"]
        out = []
        for r in rows:
            d = dict(zip(cols, r, strict=True))
            d["is_freeform"] = bool(d["is_freeform"])
            d["is_official"] = bool(d["is_official"])
            out.append(d)
        return out


__all__ = ["FieldCatalogStore"]
