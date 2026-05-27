from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import polars as pl
import pytest

from app.factor_factory import (
    ExpressionError,
    Factor,
    FactorRegistry,
    OPERATOR_REGISTRY,
    attach_forward_returns,
    compile_expression,
    compute_ic_decay,
    compute_ic_report,
    evaluate_on_panel,
    list_operators,
)


def _panel(n_symbols: int = 3, n_days: int = 80) -> pl.DataFrame:
    rows = []
    base = datetime(2024, 1, 1, tzinfo=UTC)
    rng = [base + timedelta(days=i) for i in range(n_days)]
    for sid in range(n_symbols):
        seed = sid + 1
        prev = 10.0 + sid
        for i, ts in enumerate(rng):
            delta = ((i * (sid + 1)) % 7 - 3) * 0.05  # 周期性 wiggle
            close = prev + delta
            rows.append(
                {
                    "ts": ts,
                    "symbol": f"SYM{sid}",
                    "open": prev,
                    "high": max(prev, close),
                    "low": min(prev, close),
                    "close": close,
                    "volume": 1000 + sid * 100 + i * (seed % 5),
                }
            )
            prev = close
    return pl.DataFrame(rows).sort(["symbol", "ts"])


def test_operator_registry_has_minimum_set() -> None:
    expected = {"ts_lag", "ts_mean", "ts_corr", "cs_rank", "cs_zscore", "log", "abs", "add", "div"}
    assert expected.issubset(OPERATOR_REGISTRY.keys())
    assert len(list_operators()) >= 30


def test_compile_simple_expression_returns_polars_expr() -> None:
    expr = compile_expression("close + 1")
    assert isinstance(expr, pl.Expr)


def test_unknown_operator_raises() -> None:
    with pytest.raises(ExpressionError, match="未知算子"):
        compile_expression("bogus_op(close)")


def test_unknown_column_with_validation() -> None:
    with pytest.raises(ExpressionError, match="未知列"):
        compile_expression("xx + 1", available_columns={"close"})


def test_evaluate_simple_factor_on_panel() -> None:
    panel = _panel()
    out = evaluate_on_panel(panel, "ts_mean(close, 5)", alias="sma5")
    assert out.columns == ["ts", "symbol", "sma5"]
    assert out.height == panel.height
    # 前 4 行因为 rolling 不足应该是 null
    per_symbol_first = out.group_by("symbol", maintain_order=True).head(4)
    assert per_symbol_first["sma5"].null_count() == per_symbol_first.height


def test_evaluate_complex_factor_with_cross_section_rank() -> None:
    panel = _panel()
    formula = "rank(ts_mean(close, 5))"
    out = evaluate_on_panel(panel, formula, alias="rk")
    nonnull = out.drop_nulls("rk")
    assert nonnull.height > 0
    assert nonnull["rk"].max() <= 1.0
    assert nonnull["rk"].min() >= 0.0
    # nested call 走通即可（rolling_corr 在 piecewise-linear fixture 下数值会退化为 NaN）
    nested = evaluate_on_panel(panel, "ts_zscore(close, 20) + ts_pct_change(volume, 5)", alias="nested")
    assert nested.height == panel.height


def test_attach_forward_returns_adds_horizons() -> None:
    panel = _panel()
    out = attach_forward_returns(panel, [1, 5])
    assert "forward_return_h1" in out.columns
    assert "forward_return_h5" in out.columns


def test_ic_report_computes_metrics() -> None:
    panel = _panel(n_symbols=4, n_days=120)
    factor_panel = evaluate_on_panel(panel, "ts_mean(close, 5)", alias="f")
    merged = panel.join(factor_panel, on=["ts", "symbol"])
    report = compute_ic_report(merged, factor_col="f", horizon=5)
    assert report.sample_count > 0
    assert -1 <= report.ic_mean <= 1
    assert isinstance(report.to_dict()["ic_ir"], float | int | type(None))


def test_ic_decay_returns_multiple_horizons() -> None:
    panel = _panel(n_symbols=4, n_days=120)
    factor_panel = evaluate_on_panel(panel, "ts_mean(close, 5)", alias="f")
    merged = panel.join(factor_panel, on=["ts", "symbol"])
    reports = compute_ic_decay(merged, factor_col="f", horizons=[1, 5, 10])
    assert [r.horizon for r in reports] == [1, 5, 10]


def test_factor_registry_versioning(tmp_path: Path) -> None:
    reg = FactorRegistry(tmp_path / "factors.json")
    v1 = reg.register("mom20", "ts_pct_change(close, 20)")
    v2 = reg.register("mom20", "ts_pct_change(close, 20) - ts_mean(volume, 5)")
    assert v1.version == 1
    assert v2.version == 2
    latest = reg.get("mom20")
    assert latest.version == 2
    reg.update_state("mom20", 2, "QUALIFIED")
    assert reg.get("mom20").lifecycle_state == "QUALIFIED"


def test_factor_registry_round_trip(tmp_path: Path) -> None:
    store = tmp_path / "factors.json"
    reg = FactorRegistry(store)
    reg.register("mom20", "ts_pct_change(close, 20)", description="20日动量")
    reg.set_ic_summary("mom20", 1, {"ic_mean": 0.04, "rank_ic_mean": 0.05})
    fresh = FactorRegistry(store)
    factor = fresh.get("mom20")
    assert factor.ic_summary == {"ic_mean": 0.04, "rank_ic_mean": 0.05}
    assert factor.description == "20日动量"
