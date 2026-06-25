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


# ============================================================
# risk_parity 真 ERC + mean_variance 不收敛透明（审计 pass2 #3/#5）
# ============================================================


def _erc_rc_fractions(cov: pd.DataFrame, w: dict) -> np.ndarray:
    wa = np.array([w[s] for s in cov.columns])
    m = cov.values @ wa
    total = float(wa @ m)
    return (wa * m) / total


def test_risk_parity_true_erc_equal_risk_contributions():
    """**命门（theory↔impl）**：相关非零下各标的风险贡献 RC_i 相等（真 ERC），且**逆波动做不到**。

    A,B 相关 0.9（σ 同）、C 独立 → 真 ERC：RC 三者相等；逆波动(此处=等权)让 A,B 各扛≈2×C（RC 不均）。
    MUT（还原 risk_parity 为 1/σ 逆波动）→ RC 不均、本测红。
    """
    cov = pd.DataFrame(
        [[0.01, 0.009, 0.0], [0.009, 0.01, 0.0], [0.0, 0.0, 0.01]],
        index=list("ABC"), columns=list("ABC"),
    )
    w = risk_parity(cov)
    assert sum(w.values()) == pytest.approx(1.0, abs=1e-9)
    rc = _erc_rc_fractions(cov, w)
    assert rc.max() - rc.min() < 1e-6, f"风险贡献不均 {rc}（非真 ERC=逆波动冒充 risk parity）"
    # ERC 应增持独立标的 C、减持相关簇 A/B（逆波动会给等权）
    assert w["C"] > w["A"] and w["C"] > w["B"]
    # sentinel：逆波动(等权)在此 cov 下 RC 显著不均（证 ERC≠逆波动·命门有牙）
    inv_rc = _erc_rc_fractions(cov, {"A": 1 / 3, "B": 1 / 3, "C": 1 / 3})
    assert inv_rc.max() - inv_rc.min() > 0.1


def test_risk_parity_diagonal_reduces_to_inverse_vol():
    """对角 Σ（零相关）→ ERC 退化为逆波动 1/σ（逆波动是 ERC 的零相关特例）。"""
    cov = pd.DataFrame(np.diag([0.04, 0.01, 0.0025]), index=list("ABC"), columns=list("ABC"))
    w = risk_parity(cov)
    inv = 1.0 / np.sqrt(np.diag(cov.values))
    inv = inv / inv.sum()
    for i, s in enumerate("ABC"):
        assert w[s] == pytest.approx(inv[i], abs=1e-6)


def test_mean_variance_raises_on_nonconvergence(monkeypatch):
    """**假绿灯门**：SLSQP 不收敛 → raise PortfolioOptimizationError（绝不静默返回等权冒充 MVO 解）。"""
    from types import SimpleNamespace

    from app.portfolio import optimizers as opt
    monkeypatch.setattr(opt, "minimize",
                        lambda *a, **k: SimpleNamespace(success=False, x=np.full(3, 1 / 3), message="forced"))
    mu = pd.Series([0.05, -0.02, 0.01], index=list("ABC"))
    cov = pd.DataFrame(np.eye(3) * 0.01, index=list("ABC"), columns=list("ABC"))
    with pytest.raises(opt.PortfolioOptimizationError, match="未收敛"):
        opt.mean_variance(mu, cov)


def test_optimize_portfolio_flags_mvo_nonconvergence(monkeypatch):
    """不收敛经 optimize_portfolio → 透明标 'mvo_not_converged' violation + 等权回退（非静默）。

    MUT（还原 mean_variance 静默返回 w0）→ 无 raise、无 violation、本测红。
    """
    from types import SimpleNamespace

    from app.portfolio import optimizers as opt
    monkeypatch.setattr(opt, "minimize",
                        lambda *a, **k: SimpleNamespace(success=False, x=np.full(3, 1 / 3), message="forced"))
    mu = pd.Series([0.05, -0.02, 0.01], index=list("ABC"))
    cov = pd.DataFrame(np.eye(3) * 0.01, index=list("ABC"), columns=list("ABC"))
    res = opt.optimize_portfolio("mean_variance", mu, cov)
    assert "mvo_not_converged" in res.constraint_violations           # 透明标记（非静默）=核心牙
    assert len(res.weights) == 3 and res.optimizer == "mean_variance"  # 回退仍出权重（不崩）


# ============================================================
# HRP 生产路径走审计安全版（奇异检测+收缩 fallback·审计 pass2 #7）
# ============================================================


def _singular_cov() -> pd.DataFrame:
    """奇异协方差：3 资产完全共线（corr=1·min_eig=0）→ is_near_singular 必判奇异（裸 HRP 距离矩阵退化）。"""
    base = np.ones((3, 3)) * 0.04           # 完全共线 → 秩 1 → min_eig=0
    return pd.DataFrame(base, index=list("ABC"), columns=list("ABC"))


def test_optimize_portfolio_hrp_uses_safe_ladder_on_singular_cov():
    """**鲁棒性门**：近奇异协方差经 optimize_portfolio('hrp') → 走审计 fallback ladder 出有限权重 + 透明标 hrp_fallback。

    MUT（hrp 分支退回裸 hrp_weights）→ 近奇异下权重 NaN/极端或无 fallback 标记 → 本测红。
    """
    res = optimize_portfolio("hrp", None, _singular_cov(), PortfolioConstraints(single_pos_max=1.0))
    assert all(np.isfinite(v) for v in res.weights.values())          # 不出 NaN/Inf（审计安全版兜住）
    assert sum(res.weights.values()) == pytest.approx(1.0, abs=1e-6)  # 合法权重
    assert any(v.startswith("hrp_fallback:") for v in res.constraint_violations), \
        "近奇异协方差却无 hrp_fallback 透明标记（疑用了裸 hrp_weights 无防御阶梯）"


def test_optimize_portfolio_hrp_healthy_cov_no_fallback():
    """非奇异协方差 → 走原 HRP、无 fallback 标记（向后兼容·不误标）。"""
    res = optimize_portfolio("hrp", None, _toy_cov(), PortfolioConstraints(single_pos_max=0.6))
    assert all(np.isfinite(v) for v in res.weights.values())
    assert not any(v.startswith("hrp_fallback:") for v in res.constraint_violations)
