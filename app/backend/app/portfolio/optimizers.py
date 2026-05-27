"""M8 · 组合优化器。

自实现：
- equal_weight   等权
- mean_variance  Markowitz（scipy.optimize.minimize 二次型）
- risk_parity    各标的波动率倒数权重 + 1 步对齐
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
    weights = res.x if res.success else w0
    return dict(zip(syms, weights.tolist()))


def risk_parity(cov: pd.DataFrame) -> dict[str, float]:
    """简化版 risk parity：权重 ∝ 1/σ，再归一化到 sum=1。"""

    sigma = np.sqrt(np.diag(cov.values))
    sigma = np.where(sigma <= 0, 1e-9, sigma)
    inv = 1.0 / sigma
    w = inv / inv.sum()
    return dict(zip(cov.columns.tolist(), w.tolist()))


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
    if optimizer == "equal_weight":
        weights = equal_weight(list(covariance.columns))
    elif optimizer == "mean_variance":
        if expected_returns is None:
            raise ValueError("mean_variance 需要 expected_returns")
        weights = mean_variance(
            expected_returns,
            covariance,
            short_allowed=constraints.short_allowed,
        )
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
    "PortfolioResult",
    "equal_weight",
    "hrp_weights",
    "mean_variance",
    "optimize_portfolio",
    "risk_parity",
]
