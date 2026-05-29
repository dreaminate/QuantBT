"""数据平台 v2 · Tushare 全字段拉取测试（mock SDK，不联网）。

验证：多接口保留宽字段 + ts/symbol/market 规整 + 价格类 OHLCV 兼容视图可用 +
5000 档接口在 2000 档被显式拒绝。
"""

from __future__ import annotations

import pandas as pd
import pytest

from app.connectors.base import UNIFIED_OHLCV_COLUMNS, to_ohlcv_view
from app.connectors.tushare_connector import TushareConnector
from app.connectors.base import FetchRequest


def _conn(monkeypatch, **methods) -> TushareConnector:
    conn = TushareConnector(token="DUMMY")

    class _FakePro:
        def __getattr__(self, name):
            if name in methods:
                return methods[name]
            raise AttributeError(name)

    monkeypatch.setattr(conn, "_client", lambda: _FakePro())
    return conn


def test_daily_keeps_extras_and_ohlcv_view_intact(monkeypatch) -> None:
    def daily(**_kw):
        return pd.DataFrame(
            {
                "ts_code": ["000001.SZ"],
                "trade_date": ["20240102"],
                "open": [1.0], "high": [2.0], "low": [0.5], "close": [1.5],
                "vol": [100.0], "amount": [150.0],
                "pre_close": [1.4], "pct_chg": [7.14],
            }
        )

    conn = _conn(monkeypatch, daily=daily)
    res = conn.fetch(FetchRequest(symbol="000001.SZ", interval="1d", data_kind="ohlcv", market="stocks_cn"))
    cols = res.frame.columns
    assert "volume" in cols and "vol" not in cols          # vol→volume
    assert "pct_chg" in cols and "pre_close" in cols        # 额外列保留
    assert "ts_code" not in cols                            # 冗余列去掉
    # 固定 10 列 OHLCV 兼容视图仍然可用
    assert list(to_ohlcv_view(res.frame).columns) == list(UNIFIED_OHLCV_COLUMNS)
    assert res.row_count == 1


def test_daily_basic_keeps_wide_fundamentals(monkeypatch) -> None:
    def daily_basic(**_kw):
        return pd.DataFrame(
            {
                "ts_code": ["000001.SZ"],
                "trade_date": ["20240102"],
                "close": [10.0], "turnover_rate": [2.5], "pe_ttm": [15.0],
                "pb": [1.2], "total_mv": [9.9e6], "dv_ttm": [1.1],
            }
        )

    conn = _conn(monkeypatch, daily_basic=daily_basic)
    res = conn.fetch(FetchRequest(symbol="000001.SZ", interval="1d", data_kind="daily_basic", market="stocks_cn"))
    cols = set(res.frame.columns)
    assert {"pe_ttm", "pb", "turnover_rate", "total_mv", "dv_ttm"}.issubset(cols)
    assert {"ts", "symbol", "market", "interval"}.issubset(cols)


def test_gated_interface_rejected_on_2000(monkeypatch) -> None:
    conn = _conn(monkeypatch)
    with pytest.raises(NotImplementedError, match="5000"):
        conn.fetch(FetchRequest(symbol="000001.SZ", interval="1d", data_kind="top_inst"))


def test_unsupported_kind_rejected(monkeypatch) -> None:
    conn = _conn(monkeypatch)
    with pytest.raises(NotImplementedError, match="不支持"):
        conn.fetch(FetchRequest(symbol="000001.SZ", interval="1d", data_kind="nonsense_kind"))
