from __future__ import annotations

from datetime import UTC, datetime, timedelta

import numpy as np
import polars as pl
import pytest

from app.eval import (
    bootstrap_sharpe_ci,
    brinson_attribution,
    cscv_pbo,
    deflated_sharpe_ratio,
    sharpe_ratio,
)


def test_sharpe_ratio_basic() -> None:
    rng = np.random.default_rng(0)
    r = rng.normal(loc=0.001, scale=0.01, size=252)
    sr = sharpe_ratio(r)
    assert sr > 0


def test_deflated_sharpe_lt_1_for_modest_returns() -> None:
    rng = np.random.default_rng(0)
    r = rng.normal(loc=0.0005, scale=0.01, size=500)
    dsr = deflated_sharpe_ratio(r, n_trials=50)
    assert 0 <= dsr <= 1


def test_deflated_sharpe_low_for_random_walk() -> None:
    rng = np.random.default_rng(0)
    r = rng.normal(loc=0.0, scale=0.01, size=500)
    dsr = deflated_sharpe_ratio(r, n_trials=100)
    assert dsr < 0.5


def test_bootstrap_sharpe_ci_brackets_estimate() -> None:
    rng = np.random.default_rng(0)
    r = rng.normal(loc=0.001, scale=0.01, size=300)
    ci = bootstrap_sharpe_ci(r, n_boot=300, seed=1)
    assert ci.lower < ci.estimate < ci.upper or ci.lower <= ci.estimate <= ci.upper


def test_cscv_pbo_high_for_noise_strategies() -> None:
    rng = np.random.default_rng(0)
    # 200 个完全随机策略 → PBO 期望 ~0.5
    returns = rng.normal(size=(500, 50)) * 0.01
    result = cscv_pbo(returns, s_blocks=8, max_combinations=80)
    assert 0 <= result.pbo <= 1
    assert 0.2 <= result.pbo <= 0.8  # 噪音 → 中位


def test_cscv_pbo_low_for_one_truly_better_strategy() -> None:
    rng = np.random.default_rng(0)
    returns = rng.normal(size=(500, 30)) * 0.01
    returns[:, 0] += 0.005  # 真有 alpha 的策略
    result = cscv_pbo(returns, s_blocks=8, max_combinations=80)
    assert result.pbo < 0.4


def _brinson_panels() -> tuple[pl.DataFrame, pl.DataFrame]:
    base = datetime(2024, 1, 1, tzinfo=UTC)
    days = [base + timedelta(days=i) for i in range(3)]
    sectors = ["tech", "fin"]
    port_rows, bench_rows = [], []
    for d in days:
        port_rows += [
            {"ts": d, "symbol": "AAA", "weight": 0.4, "return": 0.02, "sector": "tech"},
            {"ts": d, "symbol": "BBB", "weight": 0.3, "return": 0.01, "sector": "tech"},
            {"ts": d, "symbol": "CCC", "weight": 0.3, "return": -0.01, "sector": "fin"},
        ]
        bench_rows += [
            {"ts": d, "symbol": "AAA", "weight": 0.2, "return": 0.015, "sector": "tech"},
            {"ts": d, "symbol": "BBB", "weight": 0.3, "return": 0.005, "sector": "tech"},
            {"ts": d, "symbol": "CCC", "weight": 0.5, "return": -0.005, "sector": "fin"},
        ]
    return pl.DataFrame(port_rows), pl.DataFrame(bench_rows)


def test_brinson_attribution_returns_components() -> None:
    port, bench = _brinson_panels()
    res = brinson_attribution(port, bench, group_col="sector")
    assert {"allocation", "selection", "interaction", "active_return"} == set(res.total)
    # 主动收益 ≈ allocation + selection + interaction
    assert abs(res.total["active_return"] - (res.total["allocation"] + res.total["selection"] + res.total["interaction"])) < 1e-9


def test_brinson_missing_columns_rejected() -> None:
    bad = pl.DataFrame({"ts": [datetime(2024, 1, 1, tzinfo=UTC)], "symbol": ["A"]})
    with pytest.raises(ValueError, match="缺少列"):
        brinson_attribution(bad, bad, group_col="sector")
