"""数据平台 v2 · 字段宇宙持久化表测试。"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import polars as pl

from app.connectors.base import make_wide_fetch_result
from app.data_quality import DatasetRegistry
from app.field_catalog import FieldCatalog, FieldCatalogStore


def _catalog(tmp_path: Path) -> FieldCatalog:
    reg = DatasetRegistry(tmp_path / "r.jsonl")
    fo = pl.DataFrame([{"ts": datetime(2024, 1, 1, tzinfo=UTC), "symbol": "X", "market": "stocks_cn", "interval": "1d", "close": 10.0, "pe_ttm": 15.0}])
    po = tmp_path / "o.parquet"
    fo.write_parquet(po)
    reg.register("o", make_wide_fetch_result(fo, "tushare"), file_paths=[str(po)],
                 metadata={"market": "stocks_cn", "interval": "1d", "data_kind": "daily"})
    fu = pl.DataFrame([{"ts": datetime(2024, 1, 1, tzinfo=UTC), "symbol": "X", "market": "stocks_cn", "interval": "1d", "sentiment": 0.3}])
    pu = tmp_path / "u.parquet"
    fu.write_parquet(pu)
    reg.register("u", make_wide_fetch_result(fu, "user_myapi"), file_paths=[str(pu)],
                 metadata={"market": "stocks_cn", "interval": "1d", "data_kind": "alt"})
    return FieldCatalog(reg)


def test_sync_materializes_official_and_user(tmp_path: Path) -> None:
    store = FieldCatalogStore(":memory:")
    assert store.sync_from_catalog(_catalog(tmp_path)) > 0
    rows = {(r["field_id"], r["market"]): r for r in store.list()}

    oc = rows[("official_close", "stocks_cn")]
    assert oc["is_official"] and oc["canonical_id"] == "close" and oc["description"]
    assert oc["source"] == "tushare" and oc["data_kind"] == "daily" and oc["raw_column"] == "close"

    us = rows[("user_myapi__sentiment", "stocks_cn")]
    assert us["is_freeform"] and not us["is_official"]

    assert all(r["is_official"] for r in store.list(official=True))


def test_sync_preserves_curated_description(tmp_path: Path) -> None:
    store = FieldCatalogStore(":memory:")
    cat = _catalog(tmp_path)
    store.sync_from_catalog(cat)
    store.upsert(field_id="user_myapi__sentiment", market="stocks_cn", canonical_id=None, is_freeform=True,
                 is_official=False, source="user_myapi", data_kind="alt", raw_column="sentiment", description="情绪分")
    store.sync_from_catalog(cat)  # 再 sync 不应覆盖人工写的 description
    row = next(r for r in store.list() if r["field_id"] == "user_myapi__sentiment")
    assert row["description"] == "情绪分"


def test_merge_official_upserts(tmp_path: Path) -> None:
    store = FieldCatalogStore(":memory:")
    store.merge_official([
        {"field_id": "official_funding_rate", "market": "binanceusdm", "canonical_id": "funding_rate",
         "is_freeform": False, "is_official": True, "source": "binance", "data_kind": "funding",
         "raw_column": "last_funding_rate", "unit": "", "description": "资金费率"},
    ])
    rows = store.list(market="binanceusdm", official=True)
    assert any(r["field_id"] == "official_funding_rate" and r["canonical_id"] == "funding_rate" for r in rows)
