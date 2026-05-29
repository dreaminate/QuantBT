"""数据平台 v2 · 字段目录测试。

验证：可用字段宇宙正确区分 canonical / freeform、排除结构键、别名解析（vol→volume）、
多数据集字段并集、源过滤回调（P3 源开关的接口）。
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import polars as pl

from app.connectors.base import make_wide_fetch_result
from app.data_quality import DatasetRegistry
from app.field_catalog import FieldCatalog


def _register(reg: DatasetRegistry, tmp_path: Path, *, dataset_id, source, market, interval, data_kind, frame):
    path = tmp_path / f"{dataset_id}.parquet"
    frame.write_parquet(path)
    reg.register(
        dataset_id,
        make_wide_fetch_result(frame, source_name=source),
        file_paths=[str(path)],
        metadata={"market": market, "interval": interval, "data_kind": data_kind},
    )


def test_canonical_freeform_and_structural(tmp_path: Path) -> None:
    base = datetime(2024, 1, 1, tzinfo=UTC)
    frame = pl.DataFrame(
        [{"ts": base, "symbol": "000001.SZ", "market": "stocks_cn", "interval": "1d",
          "close": 10.0, "pe_ttm": 15.0, "alpha_news": 0.3}]
    )
    reg = DatasetRegistry(tmp_path / "r.jsonl")
    _register(reg, tmp_path, dataset_id="d1", source="tushare", market="stocks_cn",
              interval="1d", data_kind="daily", frame=frame)
    uni = FieldCatalog(reg).available_fields("stocks_cn", interval="1d")
    assert "official_close" in uni.canonical
    assert "official_pe_ttm" in uni.canonical
    assert "official_tushare__alpha_news" in uni.freeform   # 官方 freeform 带源命名空间
    # 结构键不进字段宇宙
    for key in ("ts", "symbol", "market", "interval"):
        assert key not in uni.canonical and key not in uni.freeform


def test_alias_vol_to_volume_and_crypto_fields(tmp_path: Path) -> None:
    base = datetime(2024, 1, 1, tzinfo=UTC)
    frame = pl.DataFrame(
        [{"ts": base, "symbol": "BTCUSDT", "market": "binanceusdm", "interval": "1h",
          "close": 1.0, "vol": 10.0, "funding_rate": 0.0001}]
    )
    reg = DatasetRegistry(tmp_path / "r.jsonl")
    _register(reg, tmp_path, dataset_id="btc", source="binance_vision", market="binanceusdm",
              interval="1h", data_kind="ohlcv", frame=frame)
    uni = FieldCatalog(reg).available_fields("binanceusdm")
    assert "official_volume" in uni.canonical   # vol → volume 别名解析, 官方源加 official_
    assert "official_funding_rate" in uni.canonical


def test_multi_dataset_union(tmp_path: Path) -> None:
    base = datetime(2024, 1, 1, tzinfo=UTC)
    ohlcv = pl.DataFrame([{"ts": base, "symbol": "000001.SZ", "market": "stocks_cn",
                           "interval": "1d", "close": 10.0, "volume": 100.0}])
    basic = pl.DataFrame([{"ts": base, "symbol": "000001.SZ", "market": "stocks_cn",
                           "interval": "1d", "pe_ttm": 15.0, "total_mv": 9e6}])
    reg = DatasetRegistry(tmp_path / "r.jsonl")
    _register(reg, tmp_path, dataset_id="ohlcv", source="tushare", market="stocks_cn",
              interval="1d", data_kind="daily", frame=ohlcv)
    _register(reg, tmp_path, dataset_id="basic", source="tushare", market="stocks_cn",
              interval="1d", data_kind="daily_basic", frame=basic)
    uni = FieldCatalog(reg).available_fields("stocks_cn", interval="1d")
    assert {"official_close", "official_volume", "official_pe_ttm", "official_total_mv"}.issubset(set(uni.canonical))


def test_source_filter_gates_fields(tmp_path: Path) -> None:
    """P3 源开关接口：source_filter 返回 False 的源，其字段不出现在宇宙里。"""
    base = datetime(2024, 1, 1, tzinfo=UTC)
    frame = pl.DataFrame([{"ts": base, "symbol": "000001.SZ", "market": "stocks_cn",
                           "interval": "1d", "close": 10.0, "pe_ttm": 15.0}])
    reg = DatasetRegistry(tmp_path / "r.jsonl")
    _register(reg, tmp_path, dataset_id="d1", source="tushare", market="stocks_cn",
              interval="1d", data_kind="daily", frame=frame)
    # 屏蔽 tushare 官方源
    cat = FieldCatalog(reg, source_filter=lambda source, _market: source != "tushare")
    uni = cat.available_fields("stocks_cn")
    assert "close" not in uni.canonical
    assert "pe_ttm" not in uni.canonical
