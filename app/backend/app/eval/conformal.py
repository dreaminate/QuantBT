"""R23 · 不确定性预测区间（split conformal / CQR / ACI）+ abstain。

GOAL §4「conformal/CQR/ACI 区间 + abstain（R23）」。设计/推导见
`dev/research/findings/dreaminate/conformal-intervals.md`。决策 R23=A：**合理区间防呆、不锁 α**。

**为什么是它（北极星 #1 数学贯穿 / #2 理论先证明 / #4 命门 / 「能信」）**：conformal 给**分布无关、
有限样本**的边际覆盖保证 P(Y∈C)≥1−α——这是可机器证伪的理论性质（MC 覆盖率掉到 1−α 以下即实现跑偏）。
abstain 让「证据不足」诚实地不给区间，而非吐一个假区间（= §5 漂移检测器「不假绿灯」三态同源）。

**治理（R23=不锁 α）**：`alpha` 永远是调用方传参，**内部绝不硬编 0.1/0.05**；calibrator 存排序分数、
可按任意 α 查（方法学松紧是用户那摊）。abstain 阈值/max_width 是用户风险旋钮、给默认 + 摆代价。

**诚实限界（R5 守门器自身风险明示）**：
- split/CQR 的覆盖保证依赖 **exchangeability**（可交换）；时序/regime drift 违反 → 须用 ACI 或 abstain。
- 只保**边际**覆盖、不保 per-x 条件覆盖。
- ACI 用 clipped-level 工程变体（raw α_t 递推 + 分位 level clip 到 [0,1]）；长程覆盖**实测收敛**、不空引论文界。

文献锚：Vovk; Lei et al. 2018《Distribution-Free Predictive Inference》(split conformal)；
Romano, Patterson & Candès 2019《Conformalized Quantile Regression》(CQR)；
Gibbs & Candès 2021《Adaptive Conformal Inference Under Distribution Shift》(ACI)。
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Literal

import numpy as np


@dataclass(frozen=True)
class ConformalInterval:
    """一次预测的校准区间（或 abstain）。

    abstain（abstained=True）：无法在该 α 下诚实认证覆盖（样本不足 / 非有限 / 空集）——lower/upper=NaN、
    **绝不**返回数值区间冒充 ok（不假绿灯）。有效区间可为有限或 ±inf（ACI 极端保守=全实，合法但无信息）。
    """

    lower: float
    upper: float
    alpha: float                        # 调用方请求的 miscoverage（不锁）
    method: Literal["split", "cqr", "aci"]
    n_cal: int
    abstained: bool
    reason: str | None = None
    detail: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        # 命门②（构造期拒绝矛盾态，非仅 fail-closed）：未 abstain 的区间边界绝不为 NaN
        # （±inf 合法——ACI 极端保守=全实区间）；abstain 的边界须为 NaN（绝不藏数值冒充未认证）。
        if not self.abstained and (math.isnan(self.lower) or math.isnan(self.upper)):
            raise ValueError("未 abstain 的 ConformalInterval 边界不得为 NaN（不假绿灯：矛盾态在构造期即拒）")
        if self.abstained and not (math.isnan(self.lower) and math.isnan(self.upper)):
            raise ValueError("abstain 的 ConformalInterval 边界须为 NaN（绝不藏数值区间冒充未认证）")

    def covers(self, y: float) -> bool:
        """点是否落区间内（abstain 恒 False——未认证绝不算覆盖）。用 ≤ 闭区间（ties 安全）。"""
        if self.abstained or not math.isfinite(y):
            return False
        return self.lower <= y <= self.upper

    @property
    def width(self) -> float:
        if self.abstained:
            return float("nan")
        return self.upper - self.lower

    def to_dict(self) -> dict[str, Any]:
        """序列化（与 eval 其余结果 dataclass 同惯例）。NaN/±inf 边界的 JSON 编码由消费侧决定。"""
        return {
            "lower": self.lower, "upper": self.upper, "width": self.width, "alpha": self.alpha,
            "method": self.method, "n_cal": self.n_cal, "abstained": self.abstained,
            "reason": self.reason, "detail": dict(self.detail),
        }


def _min_calib_for(alpha: float) -> int:
    """该 α 下给有限区间所需最小校准数 = ⌈1/α⌉−1（单一公式源，split/CQR 共用）。"""
    return math.ceil(1.0 / alpha) - 1


def _conformal_rank_quantile(sorted_scores: np.ndarray, alpha: float) -> tuple[float, int, bool]:
    """conformal 秩分位：返回 (q, rank_k, is_infinite)。输入须 **1D 已排序** 序列。

    k = ⌈(n+1)(1−α)⌉（**含 +1 校正**，绝非 ⌈n(1−α)⌉——后者小 n 欠覆盖）。
    1≤k≤n → q=s₍ₖ₎（1-indexed）；k>n → q=+∞（is_infinite=True，split/CQR 须 abstain，ACI 作全实保守）。
    手写 sort+rank，**不用 np.quantile 默认线性插值**（与 conformal 秩语义不一致）。
    """

    n = sorted_scores.size
    k = math.ceil((n + 1) * (1.0 - alpha))
    if k > n:
        return float("inf"), k, True
    # k=max(1,k)：仅 ACI clipped α_eff=1 时 k=0→取最紧 s₍₁₎ 才触达；split/CQR 因 α∈(0,1) 已入口校验，恒 no-op。
    k = max(1, k)
    return float(sorted_scores[k - 1]), k, False


class SplitConformalCalibrator:
    """Split conformal 校准器：存**排序后的**分数，支持任意 α 查询（不锁 α）。

    分数默认 = 绝对残差 |Y−μ̂(X)|（对称区间）。校准集**须与训练/调参集分离**（否则破坏覆盖保证）。
    """

    def __init__(self, residuals: np.ndarray) -> None:
        arr = np.asarray(residuals, dtype=float)
        # 1D 守门（命门）：非 1D 输入若放行，np.sort 保形不展平、秩按首轴索引会产畸形数组「区间」逃出
        # abstain 网（比诚实 abstain 更不诚实）。折进 _finite → interval() 统一 abstain。
        self._valid = bool(arr.ndim == 1 and arr.size > 0 and np.all(np.isfinite(arr)))
        self._scores = np.sort(np.abs(arr)) if self._valid else np.asarray([], dtype=float)

    @property
    def n_cal(self) -> int:
        return int(self._scores.size)

    def min_calib_for(self, alpha: float) -> int:
        """该 α 下给有限区间所需最小校准数 = ⌈1/α⌉−1。"""
        return _min_calib_for(alpha)

    def interval(self, prediction: float, alpha: float, *, max_width: float | None = None) -> ConformalInterval:
        if not (0.0 < alpha < 1.0):
            raise ValueError(f"alpha 须 ∈(0,1)，得 {alpha}（边界 0/1 不在定理域）")
        if not self._valid or self.n_cal == 0:
            return _abstain("split", self.n_cal, alpha, "校准分数为空 / 含非有限值 / 非 1D")
        if not math.isfinite(prediction):
            return _abstain("split", self.n_cal, alpha, "预测点非有限")
        q, k, is_inf = _conformal_rank_quantile(self._scores, alpha)
        if is_inf:
            return _abstain("split", self.n_cal, alpha,
                            f"校准集不足 n={self.n_cal}<{self.min_calib_for(alpha)}（无法在 α={alpha} 给有限区间）")
        lo, hi = prediction - q, prediction + q
        if max_width is not None and (hi - lo) > max_width:
            return _abstain("split", self.n_cal, alpha,
                            f"区间宽 {hi - lo:.4g} > max_width {max_width:.4g}（风险治理旋钮，无信息→abstain）")
        return ConformalInterval(lower=lo, upper=hi, alpha=alpha, method="split", n_cal=self.n_cal,
                                 abstained=False, detail={"q_hat": q, "rank_k": k})


def split_conformal_interval(calib_residuals: np.ndarray, prediction: float, alpha: float,
                             *, max_width: float | None = None) -> ConformalInterval:
    """函数式便捷封装（无状态单次查询）。"""
    return SplitConformalCalibrator(calib_residuals).interval(prediction, alpha, max_width=max_width)


def cqr_interval(
    calib_lo: np.ndarray, calib_hi: np.ndarray, calib_y: np.ndarray,
    pred_lo: float, pred_hi: float, alpha: float, *, max_width: float | None = None,
) -> ConformalInterval:
    """Conformalized Quantile Regression 区间。给定**已算好**的下/上分位预测（模型无关解耦）。

    分数 Eᵢ=max(q_lo(Xᵢ)−Yᵢ, Yᵢ−q_hi(Xᵢ))（带符号：内为负、外为正）。Q̂=Eᵢ 第 ⌈(n+1)(1−α)⌉ 阶。
    区间 [q_lo−Q̂, q_hi+Q̂]；Q̂ 可为负（合法收窄）；若 lower>upper（空集）→ abstain，**绝不静默交换端点**。
    `max_width` 与 split 同口径的风险治理旋钮（超宽→abstain），默认 None（不设）。
    """

    if not (0.0 < alpha < 1.0):
        raise ValueError(f"alpha 须 ∈(0,1)，得 {alpha}")
    lo_c = np.asarray(calib_lo, dtype=float)
    hi_c = np.asarray(calib_hi, dtype=float)
    y_c = np.asarray(calib_y, dtype=float)
    n = int(y_c.size)
    if not (lo_c.ndim == hi_c.ndim == y_c.ndim == 1) or not (lo_c.size == hi_c.size == n) or n == 0:
        return _abstain("cqr", 0, alpha, "校准三数组须等长非空 1D")
    if not (np.all(np.isfinite(lo_c)) and np.all(np.isfinite(hi_c)) and np.all(np.isfinite(y_c))
            and math.isfinite(pred_lo) and math.isfinite(pred_hi)):
        return _abstain("cqr", n, alpha, "校准/预测含非有限值")
    scores = np.sort(np.maximum(lo_c - y_c, y_c - hi_c))     # 带符号；可负
    q, k, is_inf = _conformal_rank_quantile(scores, alpha)
    if is_inf:
        return _abstain("cqr", n, alpha,
                        f"校准集不足 n={n}<{_min_calib_for(alpha)}（无法在 α={alpha} 给有限区间）")
    lo, hi = pred_lo - q, pred_hi + q
    if lo > hi:
        return _abstain("cqr", n, alpha, f"端点交叉 lower={lo:.4g}>upper={hi:.4g}（空集，绝不交换端点）")
    if max_width is not None and (hi - lo) > max_width:
        return _abstain("cqr", n, alpha, f"区间宽 {hi - lo:.4g} > max_width {max_width:.4g}（风险治理旋钮）")
    return ConformalInterval(lower=lo, upper=hi, alpha=alpha, method="cqr", n_cal=n,
                             abstained=False, detail={"Q_hat": q, "rank_k": k})


class AdaptiveConformalInference:
    """ACI（Gibbs & Candès 2021）：时序/分布漂移下在线调 α_t 保**长程**覆盖频率→1−α。

    `target_alpha` 目标 miscoverage（不锁，调用方传）；`gamma` 步长。状态须按策略/标的/模型流隔离。
    用法：每步 `interval(prediction, recent_scores)` 出区间 → 观测 Y → `record(covered)` 更新 α_t。
    **工程变体**：保 raw α_t（递推精确，可漂出 [0,1]）+ 分位查询时把 α_t clip 到 [0,1]（等价于 level=1−α_t
    clip 到 [0,1]）；α_eff→0 即 level→1 → q=∞ 全实保守。长程覆盖**实测验证**收敛、不空引论文界。
    """

    def __init__(self, target_alpha: float, gamma: float = 0.05) -> None:
        if not (0.0 < target_alpha < 1.0):
            raise ValueError(f"target_alpha 须 ∈(0,1)，得 {target_alpha}")
        if gamma <= 0:
            raise ValueError("gamma 须 >0")
        self.target_alpha = float(target_alpha)
        self.gamma = float(gamma)
        self.alpha_t = float(target_alpha)      # raw，可漂出 [0,1]
        self._errors: list[int] = []

    def interval(self, prediction: float, recent_scores: np.ndarray) -> ConformalInterval:
        scores = np.asarray(recent_scores, dtype=float)
        n = int(scores.size)
        if scores.ndim != 1 or n == 0 or not np.all(np.isfinite(scores)) or not math.isfinite(prediction):
            return _abstain("aci", n if scores.ndim == 1 else 0, self.target_alpha, "近窗分数须非空 1D 有限 + 预测有限")
        alpha_eff = min(1.0, max(0.0, self.alpha_t))         # clipped level（工程变体）
        sorted_s = np.sort(np.abs(scores))
        q, k, is_inf = _conformal_rank_quantile(sorted_s, alpha_eff)
        if is_inf:                                           # alpha_eff→0：全实保守（合法、非 abstain）
            return ConformalInterval(lower=float("-inf"), upper=float("inf"), alpha=self.target_alpha,
                                     method="aci", n_cal=n, abstained=False,
                                     detail={"alpha_t": self.alpha_t, "alpha_eff": alpha_eff, "trivial_cover": True})
        lo, hi = prediction - q, prediction + q
        return ConformalInterval(lower=lo, upper=hi, alpha=self.target_alpha, method="aci", n_cal=n,
                                 abstained=False, detail={"alpha_t": self.alpha_t, "alpha_eff": alpha_eff,
                                                          "q_hat": q, "rank_k": k})

    def record(self, covered: bool) -> None:
        """观测后更新：err_t=1[未覆盖]；α_{t+1}=α_t+γ(α−err_t)。漏覆盖→α_t↓→下个区间变宽。"""
        err = 0 if covered else 1
        self._errors.append(err)
        self.alpha_t = self.alpha_t + self.gamma * (self.target_alpha - err)

    @property
    def empirical_miscoverage(self) -> float:
        return float(np.mean(self._errors)) if self._errors else float("nan")

    @property
    def empirical_coverage(self) -> float:
        return 1.0 - self.empirical_miscoverage if self._errors else float("nan")


def _abstain(method: str, n_cal: int, alpha: float, reason: str) -> ConformalInterval:
    return ConformalInterval(lower=float("nan"), upper=float("nan"), alpha=alpha, method=method,  # type: ignore[arg-type]
                             n_cal=n_cal, abstained=True, reason=reason)


__all__ = [
    "AdaptiveConformalInference",
    "ConformalInterval",
    "SplitConformalCalibrator",
    "cqr_interval",
    "split_conformal_interval",
]
