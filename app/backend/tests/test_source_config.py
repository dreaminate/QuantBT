"""数据平台 v2 · P3 源开关（市场级+源级）测试。"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import polars as pl

from app.connectors.base import make_wide_fetch_result
from app.data_quality import DatasetRegistry
from app.field_catalog import FieldCatalog
from app.source_config import SourceConfigService


def _reg_two_markets(tmp_path: Path) -> DatasetRegistry:
    reg = DatasetRegistry(tmp_path / "r.jsonl")
    f1 = pl.DataFrame([{"ts": datetime(2024, 1, 1, tzinfo=UTC), "symbol": "X", "market": "stocks_cn", "interval": "1d", "close": 10.0, "pe_ttm": 15.0}])
    p1 = tmp_path / "a.parquet"
    f1.write_parquet(p1)
    reg.register("a", make_wide_fetch_result(f1, "tushare"), file_paths=[str(p1)],
                 metadata={"market": "stocks_cn", "interval": "1d", "data_kind": "daily"})
    f2 = pl.DataFrame([{"ts": datetime(2024, 1, 1, tzinfo=UTC), "symbol": "BTCUSDT", "market": "binanceusdm", "interval": "1d", "close": 1.0, "funding_rate": 0.0001}])
    p2 = tmp_path / "b.parquet"
    f2.write_parquet(p2)
    reg.register("b", make_wide_fetch_result(f2, "binance"), file_paths=[str(p2)],
                 metadata={"market": "binanceusdm", "interval": "1d", "data_kind": "klines"})
    return reg


def test_market_level_shield_official_data(tmp_path: Path) -> None:
    reg = _reg_two_markets(tmp_path)
    svc = SourceConfigService(":memory:")
    svc.sync_from_catalog(FieldCatalog(reg))
    names = {(s["name"], s["market"]) for s in svc.list_sources()}
    assert ("tushare", "stocks_cn") in names and ("binance", "binanceusdm") in names

    cat = FieldCatalog(reg, source_filter=svc.source_filter())
    assert "pe_ttm" in cat.available_fields("stocks_cn").canonical

    # 关掉官方 A股（市场级，仅 official）→ 量化流程看不到官方字段
    svc.set_market_enabled("stocks_cn", False, kind="official")
    assert "pe_ttm" not in cat.available_fields("stocks_cn").canonical
    # 加密市场不受影响
    assert "funding_rate" in cat.available_fields("binanceusdm").canonical

    # 源级再单独开回
    svc.set_source_enabled("tushare", "stocks_cn", True)
    assert "pe_ttm" in cat.available_fields("stocks_cn").canonical


def test_unregistered_source_is_permissive() -> None:
    svc = SourceConfigService(":memory:")
    assert svc.is_enabled("never_seen", "stocks_cn") is True


def test_kind_inference_and_tree() -> None:
    svc = SourceConfigService(":memory:")
    svc.register("tushare", "stocks_cn")
    svc.register("user_myapi", "stocks_cn")
    kinds = {s["name"]: s["kind"] for s in svc.list_sources()}
    assert kinds["tushare"] == "official"
    assert kinds["user_myapi"] == "user"
    tree = svc.tree()
    node = next(n for n in tree if n["market"] == "stocks_cn")
    assert len(node["sources"]) == 2
