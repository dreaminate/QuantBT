"""M8 · 组合优化器。

自实现：
- equal_weight   等权
- mean_variance  Markowitz（scipy.optimize.minimize 二次型）；不收敛 raise（绝不静默回退等权=假绿灯）
- risk_parity    **真·等风险贡献(ERC)**：各标的风险贡献 RC_i=w_i·(Σw)_i 相等（非逆波动近似）
- hrp_weights    Hierarchical Risk Parity (López de Prado 2016)
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

import numpy as np
import pandas as pd
from scipy.cluster.hierarchy import linkage
from scipy.optimize import minimize
from scipy.spatial.distance import squareform

from .constraints import PortfolioConstraints, apply_constraints


OptimizerKind = Literal["equal_weight", "mean_variance", "risk_parity", "hrp"]


class PortfolioOptimizationError(ValueError):
    """优化未达最优（如 mean_variance SLSQP 不收敛）：绝不静默把非解当解（未验证≠已验证）。"""


@dataclass
class PortfolioResult:
    optimizer: OptimizerKind
    weights: dict[str, float]
    expected_return: float
    expected_volatility: float
    constraint_violations: list[str]


def equal_weight(symbols: list[str]) -> dict[str, float]:
    if not symbols:
        return {}
    w = 1.0 / len(symbols)
    return {s: w for s in symbols}


def mean_variance(
    mu: pd.Series,
    cov: pd.DataFrame,
    *,
    risk_aversion: float = 1.0,
    short_allowed: bool = False,
) -> dict[str, float]:
    """最大化 μᵀw - λ/2 wᵀΣw，约束 sum(w) == 1。"""

    syms = list(mu.index)
    n = len(syms)
    if n == 0:
        return {}
    mu_arr = mu.values.astype(float)
    cov_arr = cov.loc[syms, syms].values.astype(float)
    w0 = np.full(n, 1.0 / n)

    def objective(w: np.ndarray) -> float:
        return float(-mu_arr @ w + 0.5 * risk_aversion * w @ cov_arr @ w)

    bounds = [(-1.0, 1.0) if short_allowed else (0.0, 1.0)] * n
    constraints = [{"type": "eq", "fun": lambda w: np.sum(w) - 1.0}]
    res = minimize(objective, w0, method="SLSQP", bounds=bounds, constraints=constraints)
    if not res.success:
        # KKT 未达 → w 无最优性保证；绝不静默返回 w0（等权）冒充 MVO 解（=未验证当已验证假绿灯）。
        raise PortfolioOptimizationError(f"mean_variance SLSQP 未收敛：{res.message}")
    return dict(zip(syms, res.x.tolist()))


def risk_parity(cov: pd.DataFrame, *, max_iter: int = 1000, tol: float = 1e-10) -> dict[str, float]:
    """**真·等风险贡献 (ERC)**：解 w 使各标的风险贡献 RC_i = w_i·(Σw)_i 相等（归一后 RC_i = 1/N）。

    乘性不动点（Maillard-Roncalli-Teïletche 2010）：暖启 w∝1/σ，迭代 w_i ← w_i·(target/RC_i) 后归一，
    直到 max_i|RC_i/总风险 − 1/N| < tol。
    - **对角 Σ（零相关）退化为逆波动 1/σ**——逆波动只是 ERC 的零相关特例；相关非零时 ERC ≠ 逆波动
      （逆波动会让高相关簇悄悄集中风险、违 risk parity 定义；ERC 才真各标的等风险贡献）。
    - 退化（非 PSD/总风险≤0）→ 回落暖启逆波动（不崩）。
    """

    syms = cov.columns.tolist()
    n = len(syms)
    if n == 0:
        return {}
    if n == 1:
        return {syms[0]: 1.0}
    cov_arr = cov.values.astype(float)
    sigma = np.sqrt(np.clip(np.diag(cov_arr), 1e-18, None))
    w = (1.0 / sigma)
    w = w / w.sum()                                      # 暖启=逆波动
    for _ in range(max_iter):
        marginal = cov_arr @ w                           # 边际风险 (Σw)_i
        rc = w * marginal                                # 风险贡献 RC_i（未归一）
        total = float(w @ marginal)                      # 总风险 wᵀΣw
        if total <= 0.0:                                 # 退化 → 守暖启逆波动
            break
        if np.max(np.abs(rc / total - 1.0 / n)) < tol:   # 各 RC 已等 → ERC 收敛
            break
        target = total / n
        rc_safe = np.where(rc <= 0.0, 1e-18, rc)
        # 平方根阻尼（log 空间半步）：满步乘性更新会振荡不收敛；sqrt 阻尼稳定收敛到 ERC 不动点。
        # 平方根阻尼（log 空间半步）：满步乘性更新会振荡不收敛；sqrt 阻尼稳定收敛到 ERC 不动点。
        w = w * np.sqrt(target / rc_safe)                 # 增持欠贡献标的（阻尼）
        w = w / w.sum()
    return dict(zip(syms, w.tolist()))


def hrp_weights(cov: pd.DataFrame) -> dict[str, float]:
    """López de Prado 2016 HRP 实现（cluster → quasi-diag → recursive bisection）。"""

    syms = list(cov.columns)
    n = len(syms)
    if n == 0:
        return {}
    if n == 1:
        return {syms[0]: 1.0}
    corr = _cov_to_corr(cov.values)
    distance = np.sqrt(np.clip((1 - corr) / 2.0, 0, 1))
    np.fill_diagonal(distance, 0)
    condensed = squareform(distance, checks=False)
    link = linkage(condensed, method="single")
    sort_ix = _get_quasi_diag(link)
    sort_ix = [int(i) for i in sort_ix]
    weights = pd.Series(1.0, index=sort_ix)
    clusters = [sort_ix]
    cov_arr = cov.values
    while clusters:
        new_clusters: list[list[int]] = []
        for cluster in clusters:
            if len(cluster) <= 1:
                continue
            split = len(cluster) // 2
            left, right = cluster[:split], cluster[split:]
            var_left = _cluster_variance(cov_arr, left)
            var_right = _cluster_variance(cov_arr, right)
            alpha = 1 - var_left / (var_left + var_right)
            for i in left:
                weights[i] *= alpha
            for i in right:
                weights[i] *= 1 - alpha
            new_clusters.extend([left, right])
        clusters = new_clusters
    weights = weights.reindex(range(n))
    if weights.sum() > 0:
        weights = weights / weights.sum()
    return {syms[i]: float(weights[i]) for i in range(n)}


def _cov_to_corr(cov: np.ndarray) -> np.ndarray:
    std = np.sqrt(np.diag(cov))
    std = np.where(std <= 0, 1e-9, std)
    corr = cov / np.outer(std, std)
    return np.clip(corr, -1, 1)


def _get_quasi_diag(link: np.ndarray) -> list[int]:
    """返回 HRP cluster 顺序。"""

    link = link.astype(int)
    sort_ix = [link[-1, 0], link[-1, 1]]
    n = link.shape[0] + 1
    while max(sort_ix) >= n:
        expanded: list[int] = []
        for i in sort_ix:
            if i >= n:
                idx = i - n
                expanded.extend([link[idx, 0], link[idx, 1]])
            else:
                expanded.append(i)
        sort_ix = expanded
    return sort_ix


def _cluster_variance(cov: np.ndarray, cluster: list[int]) -> float:
    sub = cov[np.ix_(cluster, cluster)]
    inv_var = 1.0 / np.maximum(np.diag(sub), 1e-12)
    w = inv_var / inv_var.sum()
    return float(w @ sub @ w)


def optimize_portfolio(
    optimizer: OptimizerKind,
    expected_returns: pd.Series | None,
    covariance: pd.DataFrame,
    constraints: PortfolioConstraints | None = None,
) -> PortfolioResult:
    constraints = constraints or PortfolioConstraints()
    mvo_fallback = False
    if optimizer == "equal_weight":
        weights = equal_weight(list(covariance.columns))
    elif optimizer == "mean_variance":
        if expected_returns is None:
            raise ValueError("mean_variance 需要 expected_returns")
        try:
            weights = mean_variance(
                expected_returns,
                covariance,
                short_allowed=constraints.short_allowed,
            )
        except PortfolioOptimizationError:
            # 不收敛 → 透明回退等权 + 标 violation（绝不静默把等权冒充 MVO 解）。
            weights = equal_weight(list(covariance.columns))
            mvo_fallback = True
    elif optimizer == "risk_parity":
        weights = risk_parity(covariance)
    elif optimizer == "hrp":
        weights = hrp_weights(covariance)
    else:
        raise ValueError(f"未知优化器: {optimizer}")
    final = apply_constraints(weights, constraints)
    syms = list(final.keys())
    w_arr = np.array([final[s] for s in syms])
    cov_arr = covariance.loc[syms, syms].values
    expected_vol = float(np.sqrt(max(w_arr @ cov_arr @ w_arr, 0.0)))
    expected_ret = float(expected_returns.reindex(syms).fillna(0.0).values @ w_arr) if expected_returns is not None else 0.0
    violations: list[str] = []
    if mvo_fallback:
        violations.append("mvo_not_converged")   # SLSQP 未收敛已透明回退等权（非静默）
    gross = sum(abs(v) for v in final.values())
    if gross > constraints.leverage_max + 1e-6:
        violations.append(f"gross_leverage {gross:.4f} > {constraints.leverage_max}")
    return PortfolioResult(
        optimizer=optimizer,
        weights=final,
        expected_return=expected_ret,
        expected_volatility=expected_vol,
        constraint_violations=violations,
    )


__all__ = [
    "OptimizerKind",
    "PortfolioOptimizationError",
    "PortfolioResult",
    "equal_weight",
    "hrp_weights",
    "mean_variance",
    "optimize_portfolio",
    "risk_parity",
]
