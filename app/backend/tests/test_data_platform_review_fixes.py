"""数据平台 v2 · P3.5 复核修复回归测试（覆盖 happy-path fixture 此前系统性绕开的真实路径）。"""

from __future__ import annotations

import json
from pathlib import Path

import polars as pl
import pytest

from app.field_catalog import FieldCatalog, FieldRequirement, InventoryDatasetSource
from app.field_catalog.catalog import _normalize_key_dtypes, _ts_to_utc
from app.field_catalog.mapping import FieldMappingStore, validate_field_id
from app.field_catalog.sources import _infer_source


def _inv(tmp_path: Path, files: list[dict]) -> Path:
    inv = tmp_path / "catalog" / "inventory.json"
    inv.parent.mkdir(parents=True, exist_ok=True)
    inv.write_text(json.dumps({"catalog_version": 3, "files": files}), encoding="utf-8")
    return inv


# ---- B1: ts dtype 鲁棒（整数 epoch / 紧凑 YYYYMMDD / tz-offset 字符串，绝不抛）-----------

def test_ts_to_utc_compact_yyyymmdd() -> None:
    out = _ts_to_utc(pl.Series("ts", [20230401, 20230402], dtype=pl.Int64))
    assert out.dtype == pl.Datetime("us", "UTC")
    assert out[0].year == 2023 and out[0].month == 4 and out[0].day == 1


def test_ts_to_utc_epoch_ms() -> None:
    out = _ts_to_utc(pl.Series("ts", [1672531200000], dtype=pl.Int64))
    assert out[0].year == 2023 and out[0].month == 1 and out[0].day == 1


def test_ts_to_utc_offset_string() -> None:
    out = _ts_to_utc(pl.Series("ts", ["2023-01-01T09:00:00+08:00"]))
    assert out.dtype.time_zone == "UTC"
    assert out[0].hour == 1  # 09:00+08 → 01:00 UTC


def test_normalize_never_raises_on_garbage_ts() -> None:
    out = _normalize_key_dtypes(pl.DataFrame({"ts": ["garbage", "junk"], "symbol": ["X", "Y"]}))
    assert "ts" in out.columns  # 不抛异常


def test_load_panel_survives_compact_date_csv(tmp_path: Path) -> None:
    """Tushare 风格 CSV：trade_date 被读成 Int64 紧凑日期 —— load_panel 不能崩。"""
    csv = tmp_path / "000001.SZ.csv"
    csv.write_text("trade_date,close,volume\n20230401,10.0,100\n20230402,11.0,110\n", encoding="utf-8")
    inv = _inv(tmp_path, [{"market": "stocks_cn", "interval": "1d", "data_kind": "ohlcv", "symbol_key": "000001.SZ",
                           "file_path": str(csv), "columns": ["trade_date", "close", "volume"]}])
    cat = FieldCatalog(sources=[InventoryDatasetSource(inv)])
    res = cat.load_panel(FieldRequirement(canonical_ids=["official_close"], market="stocks_cn", interval="1d"))
    assert res.ok and res.row_count == 2
    assert res.panel.schema["ts"] == pl.Datetime("us", "UTC")


# ---- B2: field_id 写入校验 -------------------------------------------------

def test_validate_field_id_rules() -> None:
    validate_field_id("close", False)            # canonical, ok
    validate_field_id("user_x__c1", True)         # freeform 合法标识符, ok
    with pytest.raises(ValueError):
        validate_field_id("ts", True)             # 结构键
    with pytest.raises(ValueError):
        validate_field_id("user_x.c1", True)      # 点号 → 非标识符
    with pytest.raises(ValueError):
        validate_field_id("not_a_canon", False)   # 非 freeform 必须在词典内


def test_mapping_store_rejects_bad_field_id() -> None:
    from app.field_catalog import FieldMapping

    store = FieldMappingStore(":memory:")
    with pytest.raises(ValueError):
        store.set(FieldMapping(source="user_x", data_kind="ohlcv", raw_column="t", field_id="ts"))


# ---- B3: _infer_source 位置感知 -------------------------------------------

def test_infer_source_position_aware() -> None:
    assert _infer_source("stocks_cn", "data/market/stocks_cn/tushare/daily/x.parquet") == "tushare"
    assert _infer_source("binanceusdm", "data/market/binanceusdm/crawler_onchain/onchain/x.parquet") == "crawler_onchain"
    # 假阳性防护：data_kind 名以 user_ 开头不应误判
    assert _infer_source("stocks_cn", "data/market/stocks_cn/tushare/user_defined_metric/1d/x.parquet") == "tushare"
    # home 目录段 user_alice 在 market 段之前，不应误判
    assert _infer_source("binanceusdm", "/Users/user_alice/q/data/market/binanceusdm/binance/klines/x.csv") == "binance"


# ---- B4: crypto market 命名归一 -------------------------------------------

def test_inventory_crypto_market_normalized_to_binanceusdm(tmp_path: Path) -> None:
    csv = tmp_path / "BTCUSDT.csv"
    pl.DataFrame({"timestamp": ["2024-01-01T00:00:00Z"], "symbol": ["BTCUSDT"], "close": [1.0], "funding_rate": [0.0001]}).write_csv(csv)
    inv = _inv(tmp_path, [{"market": "crypto", "interval": "1d", "data_kind": "klines", "symbol_key": "BTCUSDT",
                           "file_path": str(csv), "columns": ["timestamp", "symbol", "close", "funding_rate"]}])
    cat = FieldCatalog(sources=[InventoryDatasetSource(inv)])
    # 落盘 market="crypto" 被归一为 "binanceusdm"，按 binanceusdm 可查到
    uni = cat.available_fields("binanceusdm")
    assert "official_close" in uni.canonical and "official_funding_rate" in uni.canonical
    # 不再散落在 "crypto" 这个孤儿市场键下
    assert not cat.available_fields("crypto").canonical
