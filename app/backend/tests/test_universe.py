"""M2 · 动态资产池测试（合成面板，point-in-time）。"""

from __future__ import annotations

from datetime import date, timedelta

import polars as pl
import pytest

from app.universe import (
    UniverseRules,
    resolve_universe,
    resolve_universe_series,
    universe_presets,
)

BASE = date(2024, 1, 1)


def _panel() -> pl.DataFrame:
    """A/B/C 各 30 根；D 第 26 根才上市（仅 5 根）。amount: D>A>B>C。"""
    rows: list[dict] = []
    for i in range(30):
        d = BASE + timedelta(days=i)
        rows.append({"ts": d, "symbol": "A", "close": 10.0, "amount": 1000.0})
        rows.append({"ts": d, "symbol": "B", "close": 20.0, "amount": 500.0})
        rows.append({"ts": d, "symbol": "C", "close": 5.0, "amount": 100.0})
    for i in range(25, 30):
        d = BASE + timedelta(days=i)
        rows.append({"ts": d, "symbol": "D", "close": 50.0, "amount": 2000.0})
    return pl.DataFrame(rows)


def _last() -> date:
    return BASE + timedelta(days=29)


def test_rank_top_n() -> None:
    rules = UniverseRules(market="x", rank_by="amount", top_n=2)
    res = resolve_universe(rules, _panel(), _last())
    assert res.symbols == ["D", "A"]  # 按最新 amount 降序
    assert res.n_selected == 2
    assert res.dropped.get("rank") == 2  # B,C 落选


def test_min_history_drops_late_listing() -> None:
    rules = UniverseRules(market="x", rank_by="amount", top_n=2, min_history_days=10)
    res = resolve_universe(rules, _panel(), _last())
    assert res.symbols == ["A", "B"]  # D 仅 5 根被剔
    assert res.dropped.get("history") == 1


def test_min_avg_amount_filter() -> None:
    rules = UniverseRules(market="x", min_avg_amount=300.0, min_history_days=1)
    res = resolve_universe(rules, _panel(), _last())
    assert "C" not in res.symbols  # C 均额 100 < 300
    assert res.dropped.get("amount") == 1


def test_min_price_filter() -> None:
    rules = UniverseRules(market="x", min_price=8.0, min_history_days=1)
    res = resolve_universe(rules, _panel(), _last())
    assert "C" not in res.symbols  # C 收盘 5 < 8
    assert res.dropped.get("price") == 1


def test_exclude_symbols() -> None:
    rules = UniverseRules(market="x", exclude_symbols=["A"], min_history_days=1)
    res = resolve_universe(rules, _panel(), _last())
    assert "A" not in res.symbols
    assert res.dropped.get("excluded") == 1


def test_static_pool() -> None:
    rules = UniverseRules(market="x", static_symbols=["X", "Y", "X", "Z"], exclude_symbols=["Z"])
    res = resolve_universe(rules, _panel(), _last())
    assert res.symbols == ["X", "Y"]  # 去重 + 减排除，保序
    assert res.n_candidates == 3
    assert res.dropped.get("excluded") == 1


def test_st_filter() -> None:
    panel = pl.DataFrame(
        {
            "ts": [BASE, BASE, BASE],
            "symbol": ["A", "B", "C"],
            "close": [10.0, 10.0, 10.0],
            "is_st": [False, True, False],
        }
    )
    rules = UniverseRules(market="x", st_col="is_st")
    res = resolve_universe(rules, panel, BASE)
    assert res.symbols == ["A", "C"]
    assert res.dropped.get("st") == 1


def test_series_is_survivorship_safe() -> None:
    rules = UniverseRules(market="x")  # 全市场（无 top_n）
    early = BASE + timedelta(days=9)   # D 尚未上市
    late = _last()
    series = resolve_universe_series(rules, _panel(), [early, late])
    assert "D" not in series[early]      # 早期日期看不到未来上市的 D
    assert series[early] == ["A", "B", "C"]
    assert "D" in series[late]
    assert series[late] == ["A", "B", "C", "D"]


def test_missing_rank_column_raises() -> None:
    rules = UniverseRules(market="x", rank_by="nope")
    with pytest.raises(ValueError, match="nope"):
        resolve_universe(rules, _panel(), _last())


def test_presets_valid() -> None:
    presets = universe_presets()
    assert {p.id for p in presets} == {"cn_all", "cn_liquid_300", "crypto_top30"}
    for p in presets:
        assert p.rules.market == p.market
