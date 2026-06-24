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
from dataclasses import asdict, dataclass

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


def probabilistic_sharpe_ratio(returns: np.ndarray, sr_benchmark: float = 0.0) -> float:
    """PSR(SR*) = Φ((SR_pp − SR*)·√(n−1)/denom) ∈ [0,1]（Bailey & López de Prado 2012）。

    返回「真 SR 超过基准 SR* 的概率」，含非正态修正（偏度/峰度）。`sr_benchmark` 是
    **per-period** SR 基准（与内部 SR_pp 同单位），默认 0 ——「实盘 edge 是否仍显著为正」，
    用于生产期 rolling-PSR 漂移监控（绩效轴主告警）。

    **刻意不暴露 n_trials / var_sr_hat**（命门 · M-AUTHORITY=A1 / GOAL §5）：把 SR* 设成
    E[max SR over N trials] 即变回 DSR（多重检验通缩）——那是晋级期过拟合闸，绝不能当 live
    单策略退役触发器。本函数只接固定基准，从签名上杜绝该范畴误用。

    **与 DSR 互为交叉校验**（V-path 恒等，实证 <1e-12）：
        deflated_sharpe_ratio(r, N, var_sr_hat=V) == probabilistic_sharpe_ratio(r, _expected_max_sr(N, V))
    两条独立代码路径必须吻合——任何让 PSR 偏离理论的改动都会让 DSR 那侧的断言变红。

    退化输入（n<3 / σ≈0）返回 0.0（与 DSR 守门同口径，便于交叉校验对齐）。注意：PSR 假设收益
    近 IID；自相关序列会令 √(n−1) 高估有效样本、显著性被高估（调用方须在裁决里披露，R5）。
    """

    arr = np.asarray(returns, dtype=float)
    n = arr.size
    if n < 3:
        return 0.0
    if not np.all(np.isfinite(arr)):
        return 0.0   # 非有限值(NaN/inf)安全归零（与退化口径一致，避免 NaN 漏过守门；调用方应先拦）
    sd = arr.std(ddof=1)
    if sd < 1e-12:
        return 0.0
    sr_pp = arr.mean() / sd
    gamma3 = _skew(arr)
    gamma4_minus_3 = _kurt_excess(arr)
    # denom 与 dsr.py V-path 逐字符同构（(g2+2)/4 = (γ4−1)/4），max(1e-12,·) 防病态高阶矩 sqrt(负)。
    denom = math.sqrt(max(1e-12, 1 - gamma3 * sr_pp + (gamma4_minus_3 + 2) / 4.0 * sr_pp ** 2))
    z = (sr_pp - sr_benchmark) * math.sqrt(n - 1) / denom
    return float(norm.cdf(z))


@dataclass(frozen=True)
class MinTRLResult:
    """最小业绩期长度（MinTRL）结果。`min_trl` 实数；inf=never_significant；NaN=insufficient。"""

    min_trl: float              # 达到 confidence 所需最小业绩期（实数）
    min_trl_obs: float          # ⌈min_trl⌉ 整数观测数（用 float 容 inf/nan）
    status: str                 # "ok" | "never_significant" | "insufficient"
    n_observed: int
    confidence: float
    sr_benchmark: float
    sr_per_period: float

    @property
    def sufficient(self) -> bool:
        """已观测业绩期是否达标（status=ok 且 n_observed≥⌈MinTRL⌉）。否则=诚实「证据不足」。"""
        return self.status == "ok" and self.n_observed >= self.min_trl_obs

    def to_dict(self) -> dict:
        d = asdict(self)
        d["sufficient"] = self.sufficient
        return d


def minimum_track_record_length(
    returns: np.ndarray, sr_benchmark: float = 0.0, confidence: float = 0.95,
) -> MinTRLResult:
    """MinTRL = 1 + denom²·(Φ⁻¹(p)/(SR_pp−SR*))²（Bailey & López de Prado 2012）——PSR 的解析反解。

    达到置信 `confidence` 所需的**最小业绩期长度**。`sr_benchmark` per-period（同 PSR）。
    **命门**：denom² 与 `probabilistic_sharpe_ratio` 完全同项同钳 → n=MinTRL 时 PSR(SR*)≡confidence（交叉校验锚）。
    **边界（不假绿灯）**：SR_pp≤SR* → +∞（never_significant，不超基准任何样本都不显著，非"样本不足"）；
    n<3 或非有限 → insufficient（估不出矩，绝不假装算出；R27：N=1 此路诚实判证据不足、DSR 不适用）。
    confidence 须 ∈(0.5,1)（Φ⁻¹>0，否则"最小"语义退化）。注：MinTRL 用短样本自估矩、本身噪声大（"按当前估计"
    的最小长度非保证）；自相关下 √(n−1) 高估有效样本、MinTRL 低估（同 PSR，R5 披露）。
    """

    if not (0.5 < confidence < 1.0):
        raise ValueError(f"confidence 须 ∈(0.5,1)，得 {confidence}（Φ⁻¹(p)>0 方有'最小业绩期'语义）")
    arr = np.asarray(returns, dtype=float)
    n = int(arr.size)
    if n < 3 or not np.all(np.isfinite(arr)):
        return MinTRLResult(float("nan"), float("nan"), "insufficient", n, confidence, sr_benchmark, float("nan"))
    sd = arr.std(ddof=1)
    if sd < 1e-12:
        return MinTRLResult(float("nan"), float("nan"), "insufficient", n, confidence, sr_benchmark, 0.0)
    sr_pp = float(arr.mean() / sd)
    delta = sr_pp - sr_benchmark
    if delta <= 1e-12:   # SR_pp≤SR*：不超基准 → 任何样本都不显著
        return MinTRLResult(float("inf"), float("inf"), "never_significant", n, confidence, sr_benchmark, sr_pp)
    g3 = _skew(arr)
    g4_minus_3 = _kurt_excess(arr)
    denom2 = max(1e-12, 1 - g3 * sr_pp + (g4_minus_3 + 2) / 4.0 * sr_pp ** 2)   # 与 PSR 同项同钳
    zp = float(norm.ppf(confidence))
    min_trl = 1.0 + denom2 * (zp / delta) ** 2
    return MinTRLResult(float(min_trl), float(math.ceil(min_trl)), "ok", n, confidence, sr_benchmark, sr_pp)


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


__all__ = [
    "MinTRLResult",
    "deflated_sharpe_ratio",
    "minimum_track_record_length",
    "probabilistic_sharpe_ratio",
    "sharpe_ratio",
]
