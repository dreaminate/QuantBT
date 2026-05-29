"""数据平台 v2 · 官方数据集接入口测试（爬虫源同构接入）。"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import polars as pl

from app.data_quality import DatasetRegistry
from app.field_catalog import FieldCatalog, register_official_dataset


def test_official_crawler_dataset_visible_and_gated(tmp_path: Path) -> None:
    reg = DatasetRegistry(tmp_path / "r.jsonl")
    frame = pl.DataFrame(
        [
            {"ts": datetime(2024, 1, 1, tzinfo=UTC), "symbol": "BTCUSDT", "market": "binanceusdm",
             "interval": "1d", "mvrv": 2.1, "sopr": 1.05},
            {"ts": datetime(2024, 1, 2, tzinfo=UTC), "symbol": "BTCUSDT", "market": "binanceusdm",
             "interval": "1d", "mvrv": 2.2, "sopr": 1.06},
        ]
    )
    v = register_official_dataset(
        reg,
        source_name="crawler_onchain",
        market="binanceusdm",
        data_kind="onchain_metrics",
        frame=frame,
        interval="1d",
        data_root=tmp_path,
    )
    # 注册带 source_name + 列清单 + 文件落盘
    assert v.source_name == "crawler_onchain"
    assert "mvrv" in (v.metadata.get("columns") or [])
    assert Path(v.file_paths[0]).exists()

    # 官方爬虫源的字段进入"官方加密"可用宇宙（mvrv/sopr 不在词典 → freeform）
    cat = FieldCatalog(reg)
    uni = cat.available_fields("binanceusdm", interval="1d")
    assert "official_mvrv" in uni.freeform   # 爬虫源也是官方源 → official_ 前缀
    assert "official_sopr" in uni.freeform

    # 源开关可屏蔽这个官方爬虫源（P3 接口）
    gated = FieldCatalog(reg, source_filter=lambda s, _m: s != "crawler_onchain")
    assert not gated.available_fields("binanceusdm", interval="1d").freeform
