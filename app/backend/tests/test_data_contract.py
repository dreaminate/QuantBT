"""数据平台 v2 · 量化流程数据访问契约测试（脊梁守卫）。

验证：宽字段能完整保留 + OHLCV 兼容视图仍是固定 10 列 + FieldRequirement/load_panel
能按 canonical id 解析多列并派生 amount。
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import polars as pl

from app.connectors.base import (
    UNIFIED_OHLCV_COLUMNS,
    make_wide_fetch_result,
    to_ohlcv_view,
)
from app.data_quality import DatasetRegistry
from app.field_catalog import FieldCatalog, FieldRequirement


def _wide_frame(n: int = 6) -> pl.DataFrame:
    base = datetime(2024, 1, 1, tzinfo=UTC)
    rows = []
    for i in range(n):
        rows.append(
            {
                "ts": base + timedelta(days=i),
                "symbol": "000001.SZ",
                "market": "stocks_cn",
                "interval": "1d",
                "open": 10.0 + i,
                "high": 11.0 + i,
                "low": 9.5 + i,
                "close": 10.5 + i,
                "volume": 1000.0 + i,
                "pe_ttm": 15.0 + i,      # canonical（按 id 命中）
                "alpha_news": 0.1 * i,   # 词典外 → freeform
            }
        )
    return pl.DataFrame(rows)


def _catalog(tmp_path: Path) -> FieldCatalog:
    frame = _wide_frame()
    path = tmp_path / "daily.parquet"
    frame.write_parquet(path)
    reg = DatasetRegistry(tmp_path / "registry.jsonl")
    fr = make_wide_fetch_result(frame, source_name="tushare")
    reg.register(
        "cn_000001_daily",
        fr,
        file_paths=[str(path)],
        metadata={"market": "stocks_cn", "interval": "1d", "data_kind": "daily"},
    )
    return FieldCatalog(reg)


def test_wide_fetch_keeps_all_columns_but_view_is_ten_cols() -> None:
    frame = _wide_frame()
    fr = make_wide_fetch_result(frame, "tushare")
    assert "pe_ttm" in fr.frame.columns
    assert "alpha_news" in fr.frame.columns
    # 兼容视图：仍是固定 10 列（与冻结页 / 现有 run 的契约不变）
    assert list(to_ohlcv_view(frame).columns) == list(UNIFIED_OHLCV_COLUMNS)


def test_registry_persists_columns_in_metadata(tmp_path: Path) -> None:
    cat = _catalog(tmp_path)
    cols = cat.dataset_columns("cn_000001_daily")
    assert "pe_ttm" in cols and "alpha_news" in cols


def test_load_panel_resolves_and_derives_amount(tmp_path: Path) -> None:
    cat = _catalog(tmp_path)
    req = FieldRequirement(
        canonical_ids=["close", "volume", "pe_ttm"],
        optional_ids=["amount"],
        market="stocks_cn",
        interval="1d",
    )
    res = cat.load_panel(req)
    assert res.ok and not res.missing
    assert {"ts", "symbol", "close", "volume", "pe_ttm", "amount"}.issubset(set(res.panel.columns))
    assert res.manifest["close"] == "tushare"
    assert res.manifest["pe_ttm"] == "tushare"
    assert res.manifest["amount"] == "derived"
    row0 = res.panel.sort("ts").row(0, named=True)
    assert abs(row0["amount"] - row0["close"] * row0["volume"]) < 1e-6


def test_load_panel_reports_missing_required(tmp_path: Path) -> None:
    cat = _catalog(tmp_path)
    req = FieldRequirement(
        canonical_ids=["close", "roe"],  # roe 该数据集没有
        market="stocks_cn",
        interval="1d",
    )
    res = cat.load_panel(req)
    assert "roe" in res.missing
    assert not res.ok


# --- 复核加固回归（P2.5 修复 blocker/high）---------------------------------


def test_load_panel_cross_dtype_join_parquet_and_csv(tmp_path: Path) -> None:
    """BLOCKER: parquet(tz-aware Datetime) + CSV(Date) 跨源拼表不能抛 SchemaError。"""
    reg = DatasetRegistry(tmp_path / "r.jsonl")
    fa = pl.DataFrame(
        [
            {"ts": datetime(2024, 1, 1, tzinfo=UTC), "symbol": "X", "market": "stocks_cn", "interval": "1d", "close": 10.0, "volume": 100.0},
            {"ts": datetime(2024, 1, 2, tzinfo=UTC), "symbol": "X", "market": "stocks_cn", "interval": "1d", "close": 11.0, "volume": 110.0},
        ]
    )
    pa = tmp_path / "a.parquet"
    fa.write_parquet(pa)
    reg.register("a", make_wide_fetch_result(fa, "tushare"), file_paths=[str(pa)],
                 metadata={"market": "stocks_cn", "interval": "1d", "data_kind": "daily"})

    pb = tmp_path / "b.csv"
    pb.write_text(
        "ts,symbol,market,interval,pe_ttm\n2024-01-01,X,stocks_cn,1d,15.0\n2024-01-02,X,stocks_cn,1d,16.0\n",
        encoding="utf-8",
    )
    fb = pl.read_csv(pb, try_parse_dates=True)  # ts 推断为 Date
    reg.register("b", make_wide_fetch_result(fb, "tushare_basic"), file_paths=[str(pb)],
                 metadata={"market": "stocks_cn", "interval": "1d", "data_kind": "daily_basic"})

    res = FieldCatalog(reg).load_panel(
        FieldRequirement(canonical_ids=["close", "pe_ttm"], market="stocks_cn", interval="1d")
    )
    assert res.ok and not res.missing
    assert {"close", "pe_ttm"}.issubset(set(res.panel.columns))
    assert res.row_count == 2


def test_load_panel_dedups_financial_restatement(tmp_path: Path) -> None:
    """HIGH: 同 (ts,symbol) 多行（财报重述）不得在 join 时行扇出。"""
    reg = DatasetRegistry(tmp_path / "r.jsonl")
    f = pl.DataFrame(
        [
            {"ts": datetime(2023, 12, 31, tzinfo=UTC), "symbol": "X", "market": "stocks_cn", "interval": "1q", "roe": 10.0},
            {"ts": datetime(2023, 12, 31, tzinfo=UTC), "symbol": "X", "market": "stocks_cn", "interval": "1q", "roe": 10.5},
        ]
    )
    p = tmp_path / "fina.parquet"
    f.write_parquet(p)
    reg.register("fina", make_wide_fetch_result(f, "tushare"), file_paths=[str(p)],
                 metadata={"market": "stocks_cn", "interval": "1q", "data_kind": "fina_indicator"})
    res = FieldCatalog(reg).load_panel(FieldRequirement(canonical_ids=["roe"], market="stocks_cn", interval="1q"))
    assert res.row_count == 1
    assert res.panel.select(["ts", "symbol"]).unique().height == 1


def test_amount_partial_coalesce(tmp_path: Path) -> None:
    """HIGH: amount 部分缺失时按行派生，而不是整列跳过。"""
    reg = DatasetRegistry(tmp_path / "r.jsonl")
    f = pl.DataFrame(
        [
            {"ts": datetime(2024, 1, 1, tzinfo=UTC), "symbol": "X", "market": "stocks_cn", "interval": "1d", "close": 10.0, "volume": 100.0, "amount": 999.0},
            {"ts": datetime(2024, 1, 2, tzinfo=UTC), "symbol": "X", "market": "stocks_cn", "interval": "1d", "close": 11.0, "volume": 110.0, "amount": None},
        ]
    )
    p = tmp_path / "d.parquet"
    f.write_parquet(p)
    reg.register("d", make_wide_fetch_result(f, "tushare"), file_paths=[str(p)],
                 metadata={"market": "stocks_cn", "interval": "1d", "data_kind": "daily"})
    res = FieldCatalog(reg).load_panel(
        FieldRequirement(canonical_ids=["close", "volume"], optional_ids=["amount"], market="stocks_cn", interval="1d")
    )
    amounts = res.panel.sort("ts").get_column("amount").to_list()
    assert amounts[0] == 999.0          # 源值保留
    assert abs(amounts[1] - 11.0 * 110.0) < 1e-6  # 缺失行派生


def test_missing_when_symbol_absent(tmp_path: Path) -> None:
    """MEDIUM: 目标 symbol 全缺 → panel 空 → 必需字段报 missing、ok=False。"""
    cat = _catalog(tmp_path)  # 含 000001.SZ
    res = cat.load_panel(FieldRequirement(canonical_ids=["close"], market="stocks_cn", interval="1d", symbols=["NOPE"]))
    assert res.row_count == 0
    assert "close" in res.missing
    assert not res.ok


def test_freeform_ids_are_valid_python_identifiers(tmp_path: Path) -> None:
    """HIGH: freeform 字段 id 必须是合法标识符，因子表达式引擎(ast.Name)才能引用。"""
    cat = _catalog(tmp_path)  # _wide_frame 有 alpha_news → freeform
    uni = cat.available_fields("stocks_cn", interval="1d")
    assert uni.freeform
    for fid in uni.freeform:
        assert fid.isidentifier(), fid
