from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from app.portfolio import (
    PortfolioConstraints,
    apply_constraints,
    equal_weight,
    hrp_weights,
    mean_variance,
    optimize_portfolio,
    risk_parity,
)


def _toy_cov() -> pd.DataFrame:
    syms = ["A", "B", "C", "D"]
    rng = np.random.default_rng(0)
    rets = rng.normal(scale=0.01, size=(500, 4))
    return pd.DataFrame(rets, columns=syms).cov()


def test_equal_weight_sums_to_one() -> None:
    w = equal_weight(["A", "B", "C"])
    assert sum(w.values()) == pytest.approx(1.0)


def test_mean_variance_respects_long_only() -> None:
    cov = _toy_cov()
    mu = pd.Series([0.05, -0.02, 0.01, 0.03], index=cov.columns)
    w = mean_variance(mu, cov, short_allowed=False)
    assert min(w.values()) >= -1e-6
    assert sum(w.values()) == pytest.approx(1.0, abs=1e-3)


def test_risk_parity_inverse_sigma() -> None:
    cov = _toy_cov()
    w = risk_parity(cov)
    assert sum(w.values()) == pytest.approx(1.0, abs=1e-6)
    sigma = np.sqrt(np.diag(cov.values))
    # 波动越大权重越小
    largest_sigma_sym = cov.columns[int(np.argmax(sigma))]
    smallest_sigma_sym = cov.columns[int(np.argmin(sigma))]
    assert w[smallest_sigma_sym] >= w[largest_sigma_sym]


def test_hrp_weights_sum_to_one_and_nonneg() -> None:
    cov = _toy_cov()
    w = hrp_weights(cov)
    assert sum(w.values()) == pytest.approx(1.0, abs=1e-6)
    assert all(v >= 0 for v in w.values())


def test_apply_constraints_single_pos_max_and_leverage() -> None:
    raw = {"A": 0.5, "B": 0.5, "C": 0.5}
    out = apply_constraints(raw, PortfolioConstraints(single_pos_max=0.3, leverage_max=1.0))
    assert max(out.values()) <= 0.3 + 1e-6
    assert sum(abs(v) for v in out.values()) <= 1.0 + 1e-6


def test_apply_constraints_short_rejected_when_disabled() -> None:
    raw = {"A": -0.4, "B": 0.5}
    out = apply_constraints(raw, PortfolioConstraints(short_allowed=False))
    assert out["A"] == 0.0


def test_apply_constraints_sector_cap() -> None:
    raw = {"A": 0.3, "B": 0.3, "C": 0.3}
    constraints = PortfolioConstraints(
        single_pos_max=1.0,
        leverage_max=2.0,
        sector_cap=0.5,
        sector_map={"A": "tech", "B": "tech", "C": "fin"},
    )
    out = apply_constraints(raw, constraints)
    tech_sum = abs(out["A"]) + abs(out["B"])
    assert tech_sum <= 0.5 + 1e-6


def test_apply_constraints_pair_corr_cap_drops_redundant() -> None:
    raw = {"A": 0.3, "B": 0.2, "C": 0.1}
    constraints = PortfolioConstraints(
        single_pos_max=1.0,
        leverage_max=2.0,
        pair_corr_cap=0.85,
    )
    out = apply_constraints(raw, constraints, correlations={("A", "B"): 0.9})
    # 保留 |A| > |B|，所以 B 应被置 0
    assert out["B"] == 0.0


def test_optimize_portfolio_dispatch_and_metrics() -> None:
    cov = _toy_cov()
    mu = pd.Series([0.04, 0.02, 0.03, 0.01], index=cov.columns)
    for kind in ("equal_weight", "risk_parity", "hrp"):
        res = optimize_portfolio(kind, mu, cov, PortfolioConstraints(single_pos_max=0.4))
        assert res.optimizer == kind
        assert res.weights
        assert res.expected_volatility >= 0
    res_mvo = optimize_portfolio("mean_variance", mu, cov, PortfolioConstraints(single_pos_max=0.4))
    assert res_mvo.optimizer == "mean_variance"
