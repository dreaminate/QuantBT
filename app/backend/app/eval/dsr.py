"""Deflated Sharpe Ratio (Bailey & López de Prado 2014)。

DSR 调整了"多次试验后偶然出现高 SR"的概率偏差。公式：

    DSR = Φ( (SR - μ_SR) * sqrt(T-1) /
              sqrt(1 - γ3 * SR + (γ4 - 1)/4 * SR^2) )

其中 μ_SR ≈ √(2 ln(n_trials)) - (Ω - (1 - Ω) * Ω) / √(2 ln(n_trials))，Ω=Euler。
工程实现里我们用更直接的形式：
- 估计 expected_max_SR 跟试验数和 SR 分布有关
- γ3, γ4 是 returns 的偏度 / 峰度
"""

from __future__ import annotations

import math

import numpy as np
from scipy.stats import norm


def sharpe_ratio(returns: np.ndarray, periods_per_year: int = 252) -> float:
    arr = np.asarray(returns, dtype=float)
    if arr.size < 2 or arr.std(ddof=1) == 0:
        return 0.0
    return float(arr.mean() / arr.std(ddof=1) * math.sqrt(periods_per_year))


def _expected_max_sr(n_trials: int) -> float:
    if n_trials <= 1:
        return 0.0
    euler = 0.5772156649
    a = math.sqrt(2 * math.log(n_trials))
    return a - (euler / a)


def deflated_sharpe_ratio(
    returns: np.ndarray,
    n_trials: int,
    periods_per_year: int = 252,
) -> float:
    """返回 DSR ∈ [0, 1]（高 = 真有效）。"""

    arr = np.asarray(returns, dtype=float)
    n = arr.size
    if n < 3 or n_trials < 1:
        return 0.0
    sr = sharpe_ratio(arr, periods_per_year)
    if sr == 0:
        return 0.0
    sr_per_period = arr.mean() / arr.std(ddof=1) if arr.std(ddof=1) > 0 else 0.0
    if sr_per_period == 0:
        return 0.0
    gamma3 = _skew(arr)
    gamma4_minus_3 = _kurt_excess(arr)
    expected = _expected_max_sr(n_trials)
    denom = math.sqrt(max(1e-12, 1 - gamma3 * sr_per_period + (gamma4_minus_3 + 2) / 4.0 * sr_per_period ** 2))
    z = (sr_per_period - expected / math.sqrt(periods_per_year)) * math.sqrt(n - 1) / denom
    return float(norm.cdf(z))


def _skew(arr: np.ndarray) -> float:
    n = arr.size
    if n < 3:
        return 0.0
    mu = arr.mean()
    sd = arr.std(ddof=1)
    if sd == 0:
        return 0.0
    return float(((arr - mu) ** 3).mean() / sd ** 3)


def _kurt_excess(arr: np.ndarray) -> float:
    n = arr.size
    if n < 4:
        return 0.0
    mu = arr.mean()
    sd = arr.std(ddof=1)
    if sd == 0:
        return 0.0
    return float(((arr - mu) ** 4).mean() / sd ** 4 - 3.0)


__all__ = ["deflated_sharpe_ratio", "sharpe_ratio"]
