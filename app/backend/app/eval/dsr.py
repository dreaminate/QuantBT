"""Deflated Sharpe Ratio (Bailey & López de Prado 2014)。

DSR 调整了"多次试验后偶然出现高 SR"的概率偏差。公式：

    DSR = Φ( (SR - μ_SR) * sqrt(T-1) /
              sqrt(1 - γ3 * SR + (γ4 - 1)/4 * SR^2) )

其中 μ_SR ≈ √(2 ln(n_trials)) - (Ω - (1 - Ω) * Ω) / √(2 ln(n_trials))，Ω=Euler。
工程实现里我们用更直接的形式：
- 估计 expected_max_SR 跟试验数和 SR 分布有关
- γ3, γ4 是 returns 的偏度 / 峰度

**诚实定位（R5 守门器自身模型风险明示）**：DSR 是显著性阈值的【标度修正】(studentize)，
不是修复 SR 被低估、更不保证"真有效"；它只与你诚实提交的 N（试验数）一样诚实。
`var_sr_hat`（False Strategy Theorem 的横截面方差 V）若不可估则退化为旧极值近似（V 隐含=1），
此时通缩可能不足——调用方须在裁决里明示这点。
"""

from __future__ import annotations

import math

import numpy as np
from scipy.stats import norm

_EULER = 0.5772156649


def sharpe_ratio(returns: np.ndarray, periods_per_year: int = 252) -> float:
    arr = np.asarray(returns, dtype=float)
    if arr.size < 2:
        return 0.0
    sd = arr.std(ddof=1)
    # v0.8.7.1 学术 audit · 用 1e-12 阈值避免浮点噪声 (np.ones * c 的 std ≈ 2e-19)
    if sd < 1e-12:
        return 0.0
    return float(arr.mean() / sd * math.sqrt(periods_per_year))


def _expected_max_sr(n_trials: int, var_sr_hat: float | None = None) -> float:
    """N 次试验下 SR 极大值的期望。

    - `var_sr_hat is None`：旧极值近似 √(2 ln N) − γ/√(2 ln N)（studentized 单位，V 隐含=1）。
    - 给定 V：Bailey-LdP False Strategy Theorem 式(1)，返回【每期 SR 单位】的 E[max]：
      √V·[(1−γ)·Φ⁻¹(1−1/N) + γ·Φ⁻¹(1−1/(N·e))]。
    """

    if n_trials <= 1:
        return 0.0
    if var_sr_hat is None:
        a = math.sqrt(2 * math.log(n_trials))
        return a - (_EULER / a)
    v = max(float(var_sr_hat), 0.0)
    term = (1 - _EULER) * norm.ppf(1 - 1.0 / n_trials) + _EULER * norm.ppf(1 - 1.0 / (n_trials * math.e))
    return float(math.sqrt(v) * term)


def deflated_sharpe_ratio(
    returns: np.ndarray,
    n_trials: int,
    periods_per_year: int = 252,
    *,
    var_sr_hat: float | None = None,
) -> float:
    """返回 DSR ∈ [0, 1]（高 = 在诚实 N 下显著，**非**"真有效/可信"）。

    `var_sr_hat`：试验间 SR 的横截面方差 V（False Strategy Theorem）。None → 退化旧极值近似
    （向后兼容现有调用，通缩可能不足，须披露）。
    """

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
    expected = _expected_max_sr(n_trials, var_sr_hat)
    denom = math.sqrt(max(1e-12, 1 - gamma3 * sr_per_period + (gamma4_minus_3 + 2) / 4.0 * sr_per_period ** 2))
    if var_sr_hat is not None:
        # V 给定：expected 是每期 SR 单位，(SR − E[max]) 再 studentize（量纲一致）。
        z = (sr_per_period - expected) * math.sqrt(n - 1) / denom
    else:
        # V 不可估：用 studentized 形式——SR 的 t 统计量 减 N 个标准正态极大值的期望。
        # 旧实现 `expected/√ppy` 是量纲 hack（通缩强度随年化频率漂移、且 ppy 常被硬编 252）；
        # 这里两边都在 z-score 标度，去掉 ppy 失真（复核 #2）。
        z = sr_per_period * math.sqrt(n - 1) / denom - expected
    return float(norm.cdf(z))


def _skew(arr: np.ndarray) -> float:
    # 标准（有偏）偏度 g1 = m3 / m2^1.5（总体矩），与 scipy.stats.skew(bias=True) 一致。
    # 旧实现用 std(ddof=1) 当分母 = 混合估计量，与教科书/scipy 差 ~((n-1)/n)^1.5，被独立对账探针抓出。
    n = arr.size
    if n < 3:
        return 0.0
    mu = arr.mean()
    m2 = ((arr - mu) ** 2).mean()
    if m2 <= 0:
        return 0.0
    return float(((arr - mu) ** 3).mean() / m2 ** 1.5)


def _kurt_excess(arr: np.ndarray) -> float:
    # 标准（有偏）超额峰度 g2 = m4/m2^2 − 3，与 scipy.stats.kurtosis(fisher=True, bias=True) 一致。
    n = arr.size
    if n < 4:
        return 0.0
    mu = arr.mean()
    m2 = ((arr - mu) ** 2).mean()
    if m2 <= 0:
        return 0.0
    return float(((arr - mu) ** 4).mean() / m2 ** 2 - 3.0)


__all__ = ["deflated_sharpe_ratio", "sharpe_ratio"]
