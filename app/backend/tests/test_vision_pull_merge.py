"""binance_vision_pull 多日同年 reload-merge schema bug 回归（DS-1 实装时发现）。

旧 bug：reload 已写分区用 `pl.read_csv(path, try_parse_dates=True)` 把 ISO Z 字符串
timestamp 推断成 Datetime，与新解析的 String timestamp `pl.concat(how="vertical")`
报 SchemaError（多日同年第 2 天起必崩）。修：`_reload_partition_csv` 用
try_parse_dates=False 保持 String。
"""

from __future__ import annotations

import polars as pl
import pytest

from app.binance_vision_pull import _merge_by_timestamp_iso, _reload_partition_csv


def _ohlcv_row(ts: str, close: float) -> pl.DataFrame:
    return pl.DataFrame({
        "timestamp": [ts], "open": [close], "high": [close], "low": [close],
        "close": [close], "volume": [1.0], "close_time": [ts], "symbol": ["BTCUSDT"],
    })


def test_reload_partition_keeps_timestamp_string(tmp_path):
    """reload 必须保持 timestamp 为 String（非 Datetime）——修复核心。"""
    p = tmp_path / "data.csv"
    _ohlcv_row("2023-01-01T00:00:00Z", 16610.3).write_csv(p)
    prev = _reload_partition_csv(p)
    assert prev is not None
    assert prev["timestamp"].dtype == pl.String, "reload 不得把 ISO Z 字符串推断成 Datetime"


def test_multi_day_same_year_merge_no_schema_error(tmp_path):
    """多日同年增量 merge 不报 SchemaError（复现旧 bug：种坏门必抓）。"""
    p = tmp_path / "data.csv"
    _ohlcv_row("2023-01-01T00:00:00Z", 16610.3).write_csv(p)
    prev = _reload_partition_csv(p)
    day2 = _ohlcv_row("2023-01-02T00:00:00Z", 16666.0)
    merged = _merge_by_timestamp_iso(prev, day2)  # 旧 bug 在此 SchemaError
    assert merged.height == 2
    assert set(merged["timestamp"].to_list()) == {"2023-01-01T00:00:00Z", "2023-01-02T00:00:00Z"}


def test_old_behavior_would_raise(tmp_path):
    """佐证旧实现（try_parse_dates=True）确会崩——证明修复对症（修前红/修后绿）。"""
    p = tmp_path / "data.csv"
    _ohlcv_row("2023-01-01T00:00:00Z", 16610.3).write_csv(p)
    bad_prev = pl.read_csv(p, try_parse_dates=True)  # 旧实现：timestamp→Datetime
    day2 = _ohlcv_row("2023-01-02T00:00:00Z", 16666.0)
    with pytest.raises(Exception):  # noqa: B017,PT011  polars vstack SchemaError
        pl.concat([bad_prev, day2], how="vertical")
