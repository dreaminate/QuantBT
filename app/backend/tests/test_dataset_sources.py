"""数据平台 v2 · P3 DatasetSource provider 测试。

验证 InventoryDatasetSource 能把磁盘真实布局（per-symbol 文件、时间列名 timestamp/trade_date、
symbol 在文件名/ts_code 列）喂进 FieldCatalog，且 load_panel 拼表非空。
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import polars as pl

from app.data_quality import DatasetRegistry
from app.field_catalog import (
    FieldCatalog,
    FieldRequirement,
    InventoryDatasetSource,
    RegistryDatasetSource,
    register_official_dataset,
)


def _write_inventory(tmp_path: Path, files: list[dict]) -> Path:
    inv = tmp_path / "catalog" / "inventory.json"
    inv.parent.mkdir(parents=True, exist_ok=True)
    inv.write_text(json.dumps({"catalog_version": 3, "files": files}), encoding="utf-8")
    return inv


def test_inventory_source_binance_klines_timestamp_col(tmp_path: Path) -> None:
    """Binance klines CSV：时间列叫 timestamp、有 symbol 列 → 规范化后能拼表。"""
    csv = tmp_path / "BTCUSDT.csv"
    pl.DataFrame(
        {
            "timestamp": ["2024-01-01T00:00:00Z", "2024-01-02T00:00:00Z"],
            "symbol": ["BTCUSDT", "BTCUSDT"],
            "open": [1.0, 2.0], "high": [2.0, 3.0], "low": [0.5, 1.0], "close": [1.5, 2.5],
            "volume": [100.0, 200.0], "funding_rate": [0.0001, 0.0002],
        }
    ).write_csv(csv)
    inv = _write_inventory(
        tmp_path,
        [{"market": "binanceusdm", "interval": "1d", "data_kind": "klines",
          "symbol_key": "BTCUSDT", "file_path": str(csv),
          "columns": ["timestamp", "symbol", "open", "high", "low", "close", "volume", "funding_rate"]}],
    )
    cat = FieldCatalog(sources=[InventoryDatasetSource(inv)])
    uni = cat.available_fields("binanceusdm", interval="1d")
    assert "official_close" in uni.canonical and "official_funding_rate" in uni.canonical
    res = cat.load_panel(FieldRequirement(canonical_ids=["official_close", "official_funding_rate"], market="binanceusdm", interval="1d"))
    assert res.ok and res.row_count == 2
    # source 按 market 约定归到 binance（官方加密源）
    assert res.manifest["official_close"] == "binance"


def test_inventory_source_injects_symbol_from_filename(tmp_path: Path) -> None:
    """A股 OHLCV：CSV 用 trade_date、且无 symbol 列（symbol 在文件名）→ 从 symbol_key 注入。"""
    csv = tmp_path / "000001.SZ.csv"
    pl.DataFrame(
        {"trade_date": ["2024-01-01", "2024-01-02"], "open": [10.0, 11.0], "high": [11.0, 12.0],
         "low": [9.0, 10.0], "close": [10.5, 11.5], "volume": [1000.0, 1100.0]}
    ).write_csv(csv)
    inv = _write_inventory(
        tmp_path,
        [{"market": "stocks_cn", "interval": "1d", "data_kind": "ohlcv",
          "symbol_key": "000001.SZ", "file_path": str(csv),
          "columns": ["trade_date", "open", "high", "low", "close", "volume"]}],
    )
    cat = FieldCatalog(sources=[InventoryDatasetSource(inv)])
    res = cat.load_panel(FieldRequirement(canonical_ids=["official_close"], market="stocks_cn", interval="1d"))
    assert res.ok and res.row_count == 2
    assert set(res.panel.get_column("symbol").unique().to_list()) == {"000001.SZ"}
    assert res.manifest["official_close"] == "tushare"


def test_inventory_aggregates_multi_symbol_files(tmp_path: Path) -> None:
    """同 (market,interval,data_kind) 的多个 per-symbol 文件聚成一个数据集。"""
    for sym in ("AAA", "BBB"):
        pl.DataFrame(
            {"trade_date": ["2024-01-01"], "close": [1.0], "volume": [10.0]}
        ).write_csv(tmp_path / f"{sym}.csv")
    inv = _write_inventory(
        tmp_path,
        [
            {"market": "stocks_cn", "interval": "1d", "data_kind": "ohlcv", "symbol_key": "AAA",
             "file_path": str(tmp_path / "AAA.csv"), "columns": ["trade_date", "close", "volume"]},
            {"market": "stocks_cn", "interval": "1d", "data_kind": "ohlcv", "symbol_key": "BBB",
             "file_path": str(tmp_path / "BBB.csv"), "columns": ["trade_date", "close", "volume"]},
        ],
    )
    cat = FieldCatalog(sources=[InventoryDatasetSource(inv)])
    assert len(cat.list_datasets(market="stocks_cn")) == 1  # 聚成一个
    res = cat.load_panel(FieldRequirement(canonical_ids=["official_close"], market="stocks_cn", interval="1d"))
    assert set(res.panel.get_column("symbol").unique().to_list()) == {"AAA", "BBB"}
    # 按 symbol 过滤
    res2 = cat.load_panel(FieldRequirement(canonical_ids=["official_close"], market="stocks_cn", interval="1d", symbols=["AAA"]))
    assert set(res2.panel.get_column("symbol").unique().to_list()) == {"AAA"}


def test_registry_and_inventory_merge(tmp_path: Path) -> None:
    """registry(爬虫源) + inventory(官方拉数) 合并：两边数据集都在。"""
    reg = DatasetRegistry(tmp_path / "r.jsonl")
    frame = pl.DataFrame(
        [{"ts": datetime(2024, 1, 1, tzinfo=UTC), "symbol": "BTCUSDT", "market": "binanceusdm", "interval": "1d", "mvrv": 2.0}]
    )
    register_official_dataset(reg, source_name="crawler_onchain", market="binanceusdm",
                              data_kind="onchain", frame=frame, interval="1d", data_root=tmp_path)
    csv = tmp_path / "ETHUSDT.csv"
    pl.DataFrame({"timestamp": ["2024-01-01T00:00:00Z"], "symbol": ["ETHUSDT"], "close": [3000.0], "volume": [5.0]}).write_csv(csv)
    inv = _write_inventory(
        tmp_path,
        [{"market": "binanceusdm", "interval": "1d", "data_kind": "klines", "symbol_key": "ETHUSDT",
          "file_path": str(csv), "columns": ["timestamp", "symbol", "close", "volume"]}],
    )
    cat = FieldCatalog(sources=[InventoryDatasetSource(inv), RegistryDatasetSource(reg)])
    uni = cat.available_fields("binanceusdm", interval="1d")
    assert "official_close" in uni.canonical                          # 来自 inventory(官方)
    assert "official_crawler_onchain__mvrv" in uni.freeform           # 来自 registry(爬虫=官方源, 带源命名空间)
