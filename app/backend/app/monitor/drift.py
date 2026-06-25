"""§5 生产期漂移检测器（rolling-PSR / CUSUM / Page-Hinkley / PSI）。

GOAL §5：「漂移监控（rolling-PSR/CUSUM/Page-Hinkley/PSI，**绩效轴主告警 / 特征漂移仅根因**，
绝不把 DSR 搬实盘单策略）」。设计/推导见 `dev/research/findings/dreaminate/drift-detectors.md`。

**两层范畴红线（命门）——结构上钉死、非仅注释**：
1. **绩效轴 vs 特征轴隔离**：rolling-PSR / CUSUM / Page-Hinkley 是**绩效轴**信号
   （`PerfDriftSignal`，带 `breach` + `to_lifecycle_observation()`，可喂退役矩阵——M-AUTHORITY=A1
   允许绩效/成本轴）；PSI 是**特征轴**诊断（`FeatureDriftDiagnosis`，**无 breach 字段、无
   to_lifecycle_observation()、是独立类型**）——退役矩阵签名收不下它，编译/类型层即拒。
   特征分布漂移只解释「为何」绩效变化（根因），绝不单独触发退役。
2. **rolling-PSR ≠ DSR**：PSR 检测器只接固定 `sr_benchmark`、**不暴露 n_trials/var_sr_hat**。
   把 SR* 设成 E[max SR over N] 即变回 DSR（多重检验通缩、晋级期过拟合闸），那是范畴错误
   （GOAL §5「绝不把 DSR 搬实盘单策略」）。签名从源头杜绝。

**三态铁律**（= 产品「未验证≠已验证 / 不假绿灯」原则掉转枪口对己）：每个检测器返回
`ok / breach / insufficient_evidence`，**绝不把不可判定（短样本 / σ≈0 / 桶不匹配）当 `ok`**。

**冻结基准（E2 温水煮青蛙陷阱）**：CUSUM / Page-Hinkley 的 μ0/σ0 必须由**晋级期 OOS 冻结基准**
提供，**绝不用监控窗自身均值**（否则基准跟着漂走、缓慢衰减永远检测不到 = 对真钱致命静默）。

文献锚：Bailey & López de Prado 2012《The Sharpe Ratio Efficient Frontier》(PSR)、
Page 1954《Continuous Inspection Schemes》(CUSUM)、Hinkley 1971 (Page-Hinkley)、PSI 业界标准。
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Literal

import numpy as np

from ..eval.dsr import probabilistic_sharpe_ratio
from ..factor_factory.lifecycle import FactorObservation

DriftStatus = Literal["ok", "breach", "insufficient_evidence"]

# 默认阈值（文献缺省；真实生产标定属用户方法学旋钮，见 finding「未验证残余」）。
PSR_FLOOR_DEFAULT = 0.90          # rolling-PSR 跌破 = 实盘 edge 显著性流失
CUSUM_SLACK_K_DEFAULT = 0.5       # σ 单位 slack（≈检测 1σ 位移）
CUSUM_DECISION_H_DEFAULT = 5.0    # σ 单位决策区间（ARL₀ 大）
PH_DELTA_DEFAULT = 0.5            # σ 单位容差（保护性 slack）
PH_LAMBDA_DEFAULT = 10.0          # 累积偏离阈
PSI_MODERATE = 0.10               # 业界标准：<0.1 无显著 / 0.1–0.25 中度 / >0.25 重大
PSI_MAJOR = 0.25
_SIGMA_FLOOR = 1e-12              # 标准差退化地板（与 dsr.py 同口径）


def _all_finite(arr: np.ndarray) -> bool:
    """序列是否全为有限值（无 NaN/inf）。

    **命门**：NaN（停牌 / 喂数缺口）与 σ≈0 同属「不可判定」类。若不显式拦，`NaN < floor`
    恒 False 会绕过所有数值守门，让退化策略 + 喂数缺口在**绩效轴主告警**上读出绿灯
    = 对真钱致命静默（违本模块三态铁律）。所有检测器入口必经此拦 → insufficient_evidence。
    """

    return bool(np.all(np.isfinite(arr)))


@dataclass(frozen=True)
class PerfDriftSignal:
    """**绩效轴**漂移信号——可喂退役矩阵（M-AUTHORITY=A1 允许绩效/成本轴）。

    axis 恒为 "performance"；带 `breach` 与 `to_lifecycle_observation()`。
    """

    detector: str                       # "rolling_psr" | "cusum" | "page_hinkley"
    status: DriftStatus
    statistic: float                    # PSR 值 / max(S⁻) / max PH（不可判定时为 NaN）
    threshold: float
    breach: bool
    detail: dict[str, Any] = field(default_factory=dict)
    axis: Literal["performance"] = "performance"

    def to_lifecycle_observation(self, factor_id: str, version: int) -> FactorObservation:
        """绩效轴 breach → 一条**绩效退化观测**（负 IC 表达退化），喂 lifecycle 权威（A1）。

        ic_mean=-1.0 是**刻意的饱和值**（非 cost_drift 的比例化 -mag）：当前 lifecycle 迁移规则
        只看 ic_mean 符号、不看幅度，越阈程度留在 extra.statistic 供问责，无需比例化。
        仅 breach 可转观测；非 breach 调用 = 调用方逻辑错误（不该把 ok/不足当退化）。
        """

        if not self.breach:
            raise ValueError(
                f"非 breach 的 {self.detector} 信号不可转退化观测（status={self.status}）——"
                "绝不把 ok/insufficient_evidence 当绩效退化（不假绿灯）"
            )
        return FactorObservation(
            factor_id=factor_id,
            version=version,
            observed_at_utc=datetime.now(UTC).isoformat(),
            horizon=0,
            ic_mean=-1.0,           # 负 IC = 绩效退化（与 closure._drift_degrade_observation 同范式）
            ic_ir=-1.0,
            rank_ic_mean=-1.0,
            sample_t=0.0,
            extra={"source": f"drift:{self.detector}", "statistic": self.statistic, "threshold": self.threshold},
        )


def _insufficient(detector: str, threshold: float, reason: str) -> PerfDriftSignal:
    """绩效轴检测器的「不可判定」三态返回（statistic=NaN、breach=False、绝不当 ok）。"""

    return PerfDriftSignal(
        detector=detector, status="insufficient_evidence", statistic=float("nan"),
        threshold=threshold, breach=False, detail={"reason": reason},
    )


@dataclass(frozen=True)
class FeatureDriftDiagnosis:
    """**特征轴**漂移诊断（PSI）——**仅根因**。

    **刻意没有** `breach` 字段、**没有** `to_lifecycle_observation()`、是与 `PerfDriftSignal`
    **不同的类型**（命门 D2）：退役矩阵签名收不下它，从类型层杜绝特征漂移触发退役。
    severity 永远是「诊断级别」、绝非「退役 breach」。
    """

    detector: str                       # "psi"
    psi: float                          # 公开路径恒有限（ε-clip）；NaN=insufficient。undefined 仅纯数学层防御
    severity: Literal["none", "moderate", "major", "undefined", "insufficient_evidence"]
    zero_bucket: bool                   # 出现空桶（已 ε 平滑）；平滑后 PSI 绝不作 breach
    bins: int
    detail: dict[str, Any] = field(default_factory=dict)
    axis: Literal["feature"] = "feature"


# ===========================================================================
# ① rolling-PSR —— 绩效轴主告警
# ===========================================================================


def rolling_psr_drift(
    returns: np.ndarray,
    *,
    sr_benchmark: float = 0.0,
    psr_floor: float = PSR_FLOOR_DEFAULT,
    min_samples: int = 30,
) -> PerfDriftSignal:
    """滚动窗 PSR(SR*) 跌破 `psr_floor` → 绩效漂移 breach（实盘 edge 显著性流失）。

    `sr_benchmark`=per-period 基准 SR（默认 0）。**不接 n_trials/var_sr_hat**（命门：那会变回 DSR）。
    非有限值(NaN/inf) / 短样本 / σ≈0 → `insufficient_evidence`（R14：A股 T+1/涨跌停亦走此口径，绝不红绿）。

    `min_samples=30`：PSR 显著性的 √(n−1) 标度在 n≳30 才稳；更短返回 insufficient（与 floor 无关）。
    **`psr_floor=0.90` 的代价（诚实披露·R5）**：bench=0 下，floor=0.90 要求 z≥1.28，即 252 obs 时
    年化 Sharpe≳1.28 才不 breach——**年化 Sharpe∈(0,1.28) 的合法正 edge 策略会被判 breach**（偏保守/激进）。
    这是用户方法学旋钮（护栏：摆代价不替你拍板）：要少误报就调低 floor（如 0.5=「不再更可能为正」），
    要严就保持。退役不因单次 breach 发生（lifecycle 权威要连续多期），单次误报不直接退役。
    """

    arr = np.asarray(returns, dtype=float)
    n = arr.size
    if n < min_samples:
        return _insufficient("rolling_psr", psr_floor, f"样本不足 n={int(n)}<{min_samples}(R14)")
    if not _all_finite(arr):
        return _insufficient("rolling_psr", psr_floor, "非有限值(NaN/inf)——不可判定，绝不当 ok")
    if float(np.std(arr, ddof=1)) < _SIGMA_FLOOR:
        return _insufficient("rolling_psr", psr_floor, "σ≈0 退化")
    psr = probabilistic_sharpe_ratio(arr, sr_benchmark)
    breach = psr < psr_floor
    return PerfDriftSignal(
        detector="rolling_psr", status="breach" if breach else "ok", statistic=psr,
        threshold=psr_floor, breach=breach, detail={"n": int(n), "sr_benchmark": sr_benchmark},
    )


# ===========================================================================
# ② CUSUM —— 双侧 tabular，冻结基准，绩效轴确证（检测均值下降）
# ===========================================================================


def cusum_drift(
    series: np.ndarray,
    *,
    baseline_mean: float,
    baseline_std: float,
    slack_k: float = CUSUM_SLACK_K_DEFAULT,
    decision_h: float = CUSUM_DECISION_H_DEFAULT,
    min_samples: int = 5,
) -> PerfDriftSignal:
    """双侧 tabular CUSUM（σ 单位）。绩效下降看 S⁻；breach = max(S⁻) > h。

    z_t=(x_t−μ0)/σ0；S⁺=max(0,S⁺+z−k)、S⁻=max(0,S⁻−z−k)。μ0/σ0 须冻结基准（E2）。
    """

    arr = np.asarray(series, dtype=float)
    n = arr.size
    if n < min_samples:
        return _insufficient("cusum", decision_h, f"样本不足 n={int(n)}<{min_samples}")
    if not _all_finite(arr):
        return _insufficient("cusum", decision_h, "非有限值(NaN/inf)——不可判定，绝不当 ok")
    if not (math.isfinite(baseline_mean) and math.isfinite(baseline_std)) or baseline_std < _SIGMA_FLOOR:
        return _insufficient("cusum", decision_h, "baseline_mean/std 非有限或 σ≈0")
    s_pos = 0.0
    s_neg = 0.0
    peak_pos = 0.0
    peak_neg = 0.0
    for x in arr:
        z = (float(x) - baseline_mean) / baseline_std
        s_pos = max(0.0, s_pos + z - slack_k)
        s_neg = max(0.0, s_neg - z - slack_k)
        peak_pos = max(peak_pos, s_pos)
        peak_neg = max(peak_neg, s_neg)
    breach = peak_neg > decision_h   # 绩效轴：只下降侧触发退役
    return PerfDriftSignal(
        detector="cusum", status="breach" if breach else "ok", statistic=peak_neg,
        threshold=decision_h, breach=breach,
        detail={"n": int(n), "peak_s_neg": peak_neg, "peak_s_pos": peak_pos, "slack_k": slack_k},
    )


# ===========================================================================
# ③ Page-Hinkley —— frozen-baseline 变体，绩效轴确证（检测均值下降）
# ===========================================================================


def page_hinkley_drift(
    series: np.ndarray,
    *,
    baseline_mean: float,
    baseline_std: float,
    delta: float = PH_DELTA_DEFAULT,
    threshold_lambda: float = PH_LAMBDA_DEFAULT,
    min_samples: int = 5,
) -> PerfDriftSignal:
    """frozen-baseline Page-Hinkley（σ 单位），检测均值**下降**。breach = max PH > λ。

    m_t = Σ[(μ0−x_i)/σ0 − δ]；M_t=min(M,m_t)；PH_t=m_t−M_t≥0。**刻意不用全局 running-mean**
    （deep-opus 实证陷阱：平稳噪声 √t 假告警 FPR→1，见 sentinel 测试）；frozen-baseline 下 δ 变
    保护 slack、FPR 受控。μ0/σ0 须冻结基准（E2）。
    """

    arr = np.asarray(series, dtype=float)
    n = arr.size
    if n < min_samples:
        return _insufficient("page_hinkley", threshold_lambda, f"样本不足 n={int(n)}<{min_samples}")
    if not _all_finite(arr):
        return _insufficient("page_hinkley", threshold_lambda, "非有限值(NaN/inf)——不可判定，绝不当 ok")
    if not (math.isfinite(baseline_mean) and math.isfinite(baseline_std)) or baseline_std < _SIGMA_FLOOR:
        return _insufficient("page_hinkley", threshold_lambda, "baseline_mean/std 非有限或 σ≈0")
    m = 0.0
    m_min = 0.0
    peak = 0.0
    for x in arr:
        m += (baseline_mean - float(x)) / baseline_std - delta
        m_min = min(m_min, m)
        peak = max(peak, m - m_min)
    breach = peak > threshold_lambda
    return PerfDriftSignal(
        detector="page_hinkley", status="breach" if breach else "ok", statistic=peak,
        threshold=threshold_lambda, breach=breach, detail={"n": int(n), "delta": delta},
    )


def _page_hinkley_global_mean_variant(series: np.ndarray, *, delta: float, threshold_lambda: float) -> bool:
    """【刻意弃用·仅供 sentinel】教科书全局 running-mean PH（检测下降）。

    deep-opus 实证：平稳噪声上 √t 假告警 FPR→1。本函数**绝不**用于生产，只在不变量测试里
    证明「我们弃用它是对的」（门有牙 + R5 守门器自身风险自证）。
    """

    arr = np.asarray(series, dtype=float)
    m = 0.0
    m_max = 0.0
    peak = 0.0
    running_sum = 0.0
    for i, x in enumerate(arr, start=1):
        running_sum += float(x)
        running_mean = running_sum / i
        m += float(x) - running_mean - delta
        m_max = max(m_max, m)
        peak = max(peak, m_max - m)
    return peak > threshold_lambda


# ===========================================================================
# ④ PSI —— 特征轴，仅根因（绝不 breach）
# ===========================================================================


def psi_from_proportions(
    expected_props: np.ndarray,
    actual_props: np.ndarray,
    *,
    epsilon: float = 1e-6,
) -> tuple[float, bool]:
    """给定归一化占比算 PSI = Σ(aᵢ−eᵢ)ln(aᵢ/eᵢ)。返回 (psi, zero_bucket)。

    对称 ε-clip + 重归一化（保对称性 PSI(a,e)=PSI(e,a)）。任一桶被 clip → zero_bucket=True。
    纯数学层（不分桶），供不变量测试钉死理论性质。调用方须传非全零占比：全零经对称 ε-clip 后
    退化为均匀分布、PSI=0 + zero_bucket=True（不抛错；产品路径由上游 min_samples/分桶守门到不了此分支）。
    """

    e = np.asarray(expected_props, dtype=float)
    a = np.asarray(actual_props, dtype=float)
    zero_bucket = bool(np.any(e <= 0) or np.any(a <= 0))
    e = np.clip(e, epsilon, None)
    a = np.clip(a, epsilon, None)
    e = e / e.sum()
    a = a / a.sum()
    return float(np.sum((a - e) * np.log(a / e))), zero_bucket


def _psi_severity(psi: float) -> Literal["none", "moderate", "major", "undefined"]:
    if not math.isfinite(psi):
        return "undefined"
    if psi < PSI_MODERATE:
        return "none"
    if psi < PSI_MAJOR:
        return "moderate"
    return "major"


def population_stability_index(
    expected_sample: np.ndarray,
    actual_sample: np.ndarray,
    *,
    bins: int = 10,
    epsilon: float = 1e-6,
    min_samples: int = 20,
) -> FeatureDriftDiagnosis:
    """特征分布漂移 PSI（**仅根因诊断**）。桶边界由 expected 等频分位**冻结**，actual 用同套边界。

    返回 `FeatureDriftDiagnosis`（无 breach、无 to_lifecycle_observation）——结构上无法喂退役矩阵。
    """

    e_arr = np.asarray(expected_sample, dtype=float)
    a_arr = np.asarray(actual_sample, dtype=float)
    if e_arr.size < min_samples or a_arr.size < min_samples:
        return FeatureDriftDiagnosis(
            detector="psi", psi=float("nan"), severity="insufficient_evidence", zero_bucket=False,
            bins=bins, detail={"n_expected": int(e_arr.size), "n_actual": int(a_arr.size), "min_samples": min_samples},
        )
    if not (_all_finite(e_arr) and _all_finite(a_arr)):
        # 非有限值（NaN/inf）：np.histogram 会静默丢弃 → 低估 PSI（特征轴三态漏网）。判不可判定。
        return FeatureDriftDiagnosis(
            detector="psi", psi=float("nan"), severity="insufficient_evidence", zero_bucket=False,
            bins=bins, detail={"reason": "非有限值(NaN/inf)——不可判定，绝不伪造 severity"},
        )
    # 桶边界从 expected 一次性冻结（等频分位）；actual 用同套边界（否则把分桶变化误当漂移）。
    quantiles = np.linspace(0.0, 1.0, bins + 1)
    edges = np.quantile(e_arr, quantiles)
    edges[0], edges[-1] = -np.inf, np.inf       # 覆盖 actual 越界值
    edges = np.unique(edges)
    if edges.size < 3:                          # expected 近常量、分不出桶
        return FeatureDriftDiagnosis(
            detector="psi", psi=float("nan"), severity="insufficient_evidence", zero_bucket=False,
            bins=bins, detail={"reason": "expected 方差不足、无法分桶"},
        )
    e_counts, _ = np.histogram(e_arr, bins=edges)
    a_counts, _ = np.histogram(a_arr, bins=edges)
    e_props = e_counts / e_counts.sum()
    a_props = a_counts / a_counts.sum()
    psi, zero_bucket = psi_from_proportions(e_props, a_props, epsilon=epsilon)
    return FeatureDriftDiagnosis(
        detector="psi", psi=psi, severity=_psi_severity(psi), zero_bucket=zero_bucket,
        bins=int(edges.size - 1), detail={"n_expected": int(e_arr.size), "n_actual": int(a_arr.size)},
    )


__all__ = [
    "CUSUM_DECISION_H_DEFAULT",
    "CUSUM_SLACK_K_DEFAULT",
    "DriftStatus",
    "FeatureDriftDiagnosis",
    "PH_DELTA_DEFAULT",
    "PH_LAMBDA_DEFAULT",
    "PSI_MAJOR",
    "PSI_MODERATE",
    "PSR_FLOOR_DEFAULT",
    "PerfDriftSignal",
    "cusum_drift",
    "page_hinkley_drift",
    "population_stability_index",
    "psi_from_proportions",
    "rolling_psr_drift",
]
