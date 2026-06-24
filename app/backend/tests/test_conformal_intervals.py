"""R23 不确定性预测区间 对抗测试（split conformal / CQR / ACI + abstain）。

设计/推导见 `dev/research/findings/dreaminate/conformal-intervals.md`。门必抓：
- split 边际覆盖 ≥1−α；n<⌈1/α⌉−1 / 非有限 / 区间过宽 → abstain（绝不假区间）。
- 秩用 ⌈(n+1)(1−α)⌉（含 +1 校正）；abstain 阈精确。
- CQR 分数带符号（内为负）、Q̂ 可负、端点交叉 → abstain（绝不交换端点）。
- ACI 方向（漏覆盖→α_t↓→区间宽）；漂移下长程覆盖→1−α 而固定 split 崩。
- 不锁 α：calibrator 存分数、任意 α 可查；α∉(0,1) raise。
"""

from __future__ import annotations

import math

import numpy as np
import pytest

from app.eval.conformal import (
    AdaptiveConformalInference,
    ConformalInterval,
    SplitConformalCalibrator,
    cqr_interval,
    split_conformal_interval,
)


# ===========================================================================
# ① Split conformal
# ===========================================================================


def test_split_conformal_marginal_coverage_meets_target():
    """exchangeable 数据：边际覆盖 ≥1−α（多 seed 均值）。"""
    alpha = 0.1
    covs = []
    for s in range(120):
        rng = np.random.default_rng(s)
        data = rng.standard_normal(400)
        mu = data[:200].mean()
        sc = SplitConformalCalibrator(data[200:300] - mu)
        covs.append(sum(sc.interval(mu, alpha).covers(y) for y in data[300:]) / 100)
    assert np.mean(covs) >= 1 - alpha - 0.01, f"覆盖 {np.mean(covs):.3f} < 目标 {1 - alpha}"


def test_split_abstains_when_calibration_too_small():
    """n<⌈1/α⌉−1（α=0.1→9）→ abstain，绝不退化成全实区间或假区间。"""
    assert split_conformal_interval(np.random.default_rng(0).standard_normal(8), 0.0, 0.1).abstained
    assert not split_conformal_interval(np.random.default_rng(0).standard_normal(9), 0.0, 0.1).abstained


def test_split_abstains_on_nonfinite():
    bad = np.array([1.0, np.nan, 2.0, np.inf] + [0.5] * 20)
    assert split_conformal_interval(bad, 0.0, 0.1).abstained
    assert split_conformal_interval(np.random.default_rng(1).standard_normal(50), float("nan"), 0.1).abstained


def test_split_abstains_when_interval_too_wide():
    """风险治理旋钮：width>max_width → abstain（无信息区间不冒充 ok）。"""
    sc = SplitConformalCalibrator(np.random.default_rng(2).standard_normal(200) * 5)
    iv = sc.interval(0.0, 0.1, max_width=0.01)
    assert iv.abstained and "max_width" in (iv.reason or "")


def test_split_rank_uses_plus_one_correction():
    """秩 = ⌈(n+1)(1−α)⌉（含 +1）；q̂ 恰为该阶序统计量。"""
    sc = SplitConformalCalibrator(np.random.default_rng(3).standard_normal(50))
    iv = sc.interval(0.0, 0.1)
    assert iv.detail["rank_k"] == math.ceil(51 * 0.9) == 46


def test_split_alpha_out_of_range_raises():
    sc = SplitConformalCalibrator(np.random.default_rng(4).standard_normal(50))
    for bad_alpha in (0.0, 1.0, -0.1, 1.5):
        with pytest.raises(ValueError, match="alpha"):
            sc.interval(0.0, bad_alpha)


def test_split_does_not_lock_alpha():
    """不锁 α（R23）：同一 calibrator 任意 α 查、各得不同区间；无内部硬编阈值。"""
    sc = SplitConformalCalibrator(np.random.default_rng(5).standard_normal(500))
    widths = {a: sc.interval(0.0, a).width for a in (0.01, 0.05, 0.1, 0.2)}
    assert widths[0.01] > widths[0.05] > widths[0.1] > widths[0.2]   # α↓ 区间↑（单调嵌套）


# ===========================================================================
# ② CQR
# ===========================================================================


def _hetero(seed, n):
    rng = np.random.default_rng(seed)
    x = rng.uniform(0, 5, n)
    y = np.sin(x) + rng.standard_normal(n) * (0.1 + 0.3 * x)   # 异方差
    qlo = np.sin(x) - 1.64 * (0.1 + 0.3 * x)
    qhi = np.sin(x) + 1.64 * (0.1 + 0.3 * x)
    return x, y, qlo, qhi


def test_cqr_marginal_coverage_meets_target():
    x, y, qlo, qhi = _hetero(6, 600)
    covs = [cqr_interval(qlo[:300], qhi[:300], y[:300], qlo[j], qhi[j], 0.1).covers(y[j]) for j in range(300, 600)]
    assert np.mean(covs) >= 0.1 * 0 + 0.9 - 0.03, f"CQR 覆盖 {np.mean(covs):.3f} 不足"


def test_cqr_qhat_can_be_negative_to_narrow():
    """Q̂ 可为负（分位预测过宽时合法收窄）——证 CQR 非「只放大」。"""
    x, y, qlo, qhi = _hetero(7, 600)
    qlo_wide, qhi_wide = np.sin(x) - 5 * (0.1 + 0.3 * x), np.sin(x) + 5 * (0.1 + 0.3 * x)
    iv = cqr_interval(qlo_wide[:300], qhi_wide[:300], y[:300], qlo_wide[350], qhi_wide[350], 0.1)
    assert iv.detail["Q_hat"] < 0


def test_cqr_endpoint_crossing_abstains_not_swaps():
    """Q̂ 极负致 lower>upper（空集）→ abstain，绝不静默交换端点。"""
    # 极宽分位 + 极小 α 让 Q̂ 大负，pred 端点很窄 → 交叉
    n = 200
    rng = np.random.default_rng(8)
    y = rng.standard_normal(n) * 0.01
    qlo = np.full(n, -5.0)
    qhi = np.full(n, 5.0)
    iv = cqr_interval(qlo, qhi, y, pred_lo=-0.001, pred_hi=0.001, alpha=0.1)
    assert iv.abstained and "交叉" in (iv.reason or "")


def test_cqr_abstains_on_nonfinite_and_mismatch():
    assert cqr_interval(np.array([1.0, np.nan]), np.array([2.0, 3.0]), np.array([1.5, 2.5]),
                        0.0, 1.0, 0.1).abstained
    assert cqr_interval(np.array([1.0, 2.0]), np.array([2.0]), np.array([1.5, 2.5]), 0.0, 1.0, 0.1).abstained


# ===========================================================================
# ③ ACI
# ===========================================================================


def test_aci_update_direction():
    """漏覆盖(err=1) → α_t 降（区间将变宽）；覆盖(err=0) → α_t 升。方向搞反必抓。"""
    aci = AdaptiveConformalInference(target_alpha=0.1, gamma=0.05)
    a0 = aci.alpha_t
    aci.record(covered=False)
    assert aci.alpha_t < a0
    a1 = aci.alpha_t
    aci.record(covered=True)
    assert aci.alpha_t > a1


def test_aci_long_run_coverage_under_drift_beats_fixed_split():
    """分布漂移（尺度随时间增）下：ACI 长程覆盖→1−α，而固定 split 严重 mis-cover。"""
    rng = np.random.default_rng(9)
    aci = AdaptiveConformalInference(target_alpha=0.1, gamma=0.05)
    fixed = SplitConformalCalibrator(rng.standard_normal(200))
    window = list(np.abs(rng.standard_normal(100)))
    T = 2500
    aci_cov, fixed_cov = [], []
    for t in range(T):
        scale = 1.0 + 3.0 * t / T
        y = rng.standard_normal() * scale
        iv = aci.interval(0.0, np.array(window[-100:]))
        c = iv.covers(y)
        aci_cov.append(c)
        aci.record(c)
        window.append(abs(y))
        fixed_cov.append(fixed.interval(0.0, 0.1).covers(y))
    aci_c, fixed_c = np.mean(aci_cov), np.mean(fixed_cov)
    assert abs(aci_c - 0.9) < 0.03, f"ACI 长程覆盖 {aci_c:.3f} 未收敛到 0.9"
    assert fixed_c < aci_c - 0.1, f"固定 split 漂移下应明显 mis-cover，得 {fixed_c:.3f}"


def test_aci_trivial_cover_when_alpha_t_drives_level_to_one():
    """连续漏覆盖把 α_t 压到 ≤0 → 全实区间（合法保守、非 abstain，trivial_cover 标记）。"""
    aci = AdaptiveConformalInference(target_alpha=0.1, gamma=0.5)
    for _ in range(5):
        aci.record(covered=False)   # α_t 快速降到负
    iv = aci.interval(0.0, np.abs(np.random.default_rng(10).standard_normal(100)))
    assert not iv.abstained and not math.isfinite(iv.upper) and iv.detail.get("trivial_cover")


def test_aci_abstains_on_empty_or_nonfinite_window():
    aci = AdaptiveConformalInference(target_alpha=0.1)
    assert aci.interval(0.0, np.array([])).abstained
    assert aci.interval(0.0, np.array([1.0, np.nan, 2.0])).abstained


def test_aci_target_alpha_validated():
    for bad in (0.0, 1.0, -0.1):
        with pytest.raises(ValueError):
            AdaptiveConformalInference(target_alpha=bad)


# ===========================================================================
# ConformalInterval 语义
# ===========================================================================


def test_interval_covers_semantics():
    iv = ConformalInterval(lower=-1.0, upper=1.0, alpha=0.1, method="split", n_cal=100, abstained=False)
    assert iv.covers(0.0) and iv.covers(1.0) and iv.covers(-1.0)   # 闭区间
    assert not iv.covers(1.5) and not iv.covers(float("nan"))      # 外 / 非有限
    assert iv.width == 2.0


def test_abstained_interval_never_covers():
    """abstain 区间 covers() 恒 False、width=NaN——未认证绝不算覆盖（不假绿灯）。"""
    iv = ConformalInterval(lower=float("nan"), upper=float("nan"), alpha=0.1, method="split",
                           n_cal=3, abstained=True, reason="样本不足")
    assert not iv.covers(0.0) and math.isnan(iv.width)


# ===========================================================================
# 命门加固（评审 medium：非 1D 绕过 abstain 网 + 构造期拒矛盾态 + 序列化）
# ===========================================================================


def test_split_abstains_on_non_1d_input():
    """评审 medium：2D 残差不得绕过 abstain 网产畸形数组「区间」→ 必 abstain（比假区间更不诚实）。"""
    resid_2d = np.random.default_rng(0).standard_normal((50, 3))
    iv = split_conformal_interval(resid_2d, 0.0, 0.1)
    assert iv.abstained
    # 且不会崩、不产数组边界
    assert isinstance(iv.lower, float) and math.isnan(iv.lower)


def test_cqr_abstains_on_non_1d_input():
    y2 = np.random.default_rng(1).standard_normal((100, 2))
    iv = cqr_interval(y2, y2, y2, 0.0, 1.0, 0.1)
    assert iv.abstained


def test_aci_abstains_on_non_1d_window():
    aci = AdaptiveConformalInference(target_alpha=0.1)
    iv = aci.interval(0.0, np.random.default_rng(2).standard_normal((100, 2)))
    assert iv.abstained


def test_conformal_interval_rejects_inconsistent_state():
    """构造期拒矛盾态（命门②升级）：未 abstain 却 NaN 边界、或 abstain 却藏数值 → 构造即 raise。"""
    with pytest.raises(ValueError, match="NaN"):
        ConformalInterval(lower=float("nan"), upper=1.0, alpha=0.1, method="split", n_cal=50, abstained=False)
    with pytest.raises(ValueError, match="NaN"):
        ConformalInterval(lower=0.0, upper=1.0, alpha=0.1, method="split", n_cal=3, abstained=True)
    # ±inf 非 NaN：ACI 全实保守合法（不 raise）
    ok = ConformalInterval(lower=float("-inf"), upper=float("inf"), alpha=0.1, method="aci", n_cal=50, abstained=False)
    assert not ok.abstained


def test_conformal_interval_to_dict():
    iv = ConformalInterval(lower=-1.0, upper=2.0, alpha=0.1, method="split", n_cal=100, abstained=False)
    d = iv.to_dict()
    assert d["lower"] == -1.0 and d["upper"] == 2.0 and d["width"] == 3.0 and d["abstained"] is False


def test_cqr_max_width_abstains():
    """CQR 与 split 同口径 max_width 旋钮：超宽 → abstain（对称化、单一契约）。"""
    x, y, qlo, qhi = _hetero(11, 600)
    iv = cqr_interval(qlo[:300], qhi[:300], y[:300], qlo[350], qhi[350], 0.1, max_width=0.001)
    assert iv.abstained and "max_width" in (iv.reason or "")


def test_cqr_coverage_with_narrow_oracle_exercises_conformal_layer():
    """CQR 层有牙：故意给**过窄** oracle 分位（Q̂ 须显著为正补偿）→ 覆盖仍 ≥1−α（靠 conformal 修正，非 oracle）。"""
    rng = np.random.default_rng(12)
    x = rng.uniform(0, 5, 600)
    y = np.sin(x) + rng.standard_normal(600) * (0.1 + 0.3 * x)
    # 过窄：只用 0.5σ 带（远不足 90%）→ conformal 必须放大
    qlo, qhi = np.sin(x) - 0.5 * (0.1 + 0.3 * x), np.sin(x) + 0.5 * (0.1 + 0.3 * x)
    ivs = [cqr_interval(qlo[:300], qhi[:300], y[:300], qlo[j], qhi[j], 0.1) for j in range(300, 600)]
    assert ivs[0].detail["Q_hat"] > 0           # oracle 过窄 → Q̂>0 放大（conformal 层真在工作）
    assert np.mean([iv.covers(y[j]) for iv, j in zip(ivs, range(300, 600))]) >= 0.9 - 0.03
