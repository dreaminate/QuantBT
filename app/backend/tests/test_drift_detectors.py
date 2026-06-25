"""§5 生产期漂移检测器 对抗测试（rolling-PSR / CUSUM / Page-Hinkley / PSI）。

设计/推导见 `dev/research/findings/dreaminate/drift-detectors.md`。门必抓（种已知坏门必抓）：
- rolling-PSR 跌破下限 → 绩效漂移 breach；短样本/σ≈0 → insufficient_evidence（非 ok 非红绿，R14）。
- CUSUM 冻结基准抓缓慢下降（温水煮青蛙）；方向：绩效轴只下降侧 S⁻ 触发退役、step-up 不退役。
- Page-Hinkley frozen-baseline 抓 step-down；sentinel 证明弃用的全局 running-mean 变体平稳噪声假告警。
- PSI 仅根因：FeatureDriftDiagnosis **无 breach / 无 to_lifecycle_observation / 类型层喂不进 monitor_tick**；
  种「PSI=∞ 剧烈特征漂移但绩效仍 ok」→ 绝不退役；「PSI≈0 但绩效崩」→ 照常退役（绩效轴独立告警）。
- 三态：不可判定恒返回 insufficient_evidence、绝不当 ok（不假绿灯）。
"""

from __future__ import annotations

import numpy as np
import pytest

from app.factor_factory.lifecycle import LifecycleManager, LifecycleThresholds
from app.factor_factory.registry import FactorRegistry
from app.monitor.closure import monitor_tick
from app.monitor.drift import (
    FeatureDriftDiagnosis,
    PerfDriftSignal,
    _page_hinkley_global_mean_variant,
    cusum_drift,
    page_hinkley_drift,
    population_stability_index,
    psi_from_proportions,
    rolling_psr_drift,
)

_MU0, _SD0 = 0.001, 0.01   # 冻结基准（晋级期 OOS）


# ===========================================================================
# ① rolling-PSR
# ===========================================================================


def test_rolling_psr_healthy_edge_ok():
    rng = np.random.default_rng(0)
    sig = rolling_psr_drift(rng.standard_normal(252) * 0.01 + 0.0015)
    assert sig.status == "ok" and not sig.breach and 0.0 <= sig.statistic <= 1.0


def test_rolling_psr_lost_edge_breaches():
    """edge 流失（收益均值≈0）→ PSR 跌破下限 → 绩效漂移 breach。"""
    rng = np.random.default_rng(1)
    sig = rolling_psr_drift(rng.standard_normal(252) * 0.01)   # 零 edge
    assert sig.breach and sig.status == "breach" and sig.statistic < sig.threshold


def test_rolling_psr_short_sample_is_insufficient_not_green():
    """R14/三态：短样本绝不红绿、返回 insufficient_evidence（NaN 统计量、breach=False）。"""
    sig = rolling_psr_drift(np.random.default_rng(2).standard_normal(10))
    assert sig.status == "insufficient_evidence" and not sig.breach


def test_rolling_psr_degenerate_sigma_is_insufficient():
    sig = rolling_psr_drift(np.ones(60) * 0.01)   # σ≈0
    assert sig.status == "insufficient_evidence" and not sig.breach


def test_rolling_psr_detector_forbids_dsr_deflation_params():
    """命门 D1：rolling-PSR 签名绝不暴露 n_trials/var_sr_hat——否则把 DSR 多重检验通缩伪装成 live 退役触发器。"""
    import inspect

    params = set(inspect.signature(rolling_psr_drift).parameters)
    for forbidden in ("n_trials", "var_sr_hat", "trials", "n_trial"):
        assert forbidden not in params, f"rolling-PSR 不得接 {forbidden}（=变回 DSR，违 M-AUTHORITY/GOAL §5）"


# ===========================================================================
# ② CUSUM
# ===========================================================================


def test_cusum_no_drift_ok():
    rng = np.random.default_rng(3)
    sig = cusum_drift(rng.standard_normal(80) * _SD0 + _MU0, baseline_mean=_MU0, baseline_std=_SD0)
    assert sig.status == "ok" and not sig.breach


def test_cusum_catches_slow_decline_frozen_baseline():
    """温水煮青蛙：缓慢线性下降 → 冻结基准 CUSUM S⁻ 越阈 breach。

    这条钉死「μ0 必须是冻结基准、绝不用监控窗自身均值」——若用自身均值，基准跟着漂走，
    此缓降序列永远检测不到（对真钱致命静默 E2）。
    """
    rng = np.random.default_rng(4)
    slow = np.linspace(_MU0, _MU0 - 3 * _SD0, 120) + rng.standard_normal(120) * _SD0 * 0.3
    sig = cusum_drift(slow, baseline_mean=_MU0, baseline_std=_SD0)
    assert sig.breach and sig.detail["peak_s_neg"] > sig.threshold


def test_cusum_direction_step_down_lights_s_neg_not_s_pos():
    rng = np.random.default_rng(5)
    step = np.concatenate([rng.standard_normal(30) * _SD0 + _MU0,
                           rng.standard_normal(40) * _SD0 + _MU0 - 2 * _SD0])
    sig = cusum_drift(step, baseline_mean=_MU0, baseline_std=_SD0)
    assert sig.breach
    assert sig.detail["peak_s_neg"] > sig.detail["peak_s_pos"]   # 下偏点燃 S⁻，非 S⁺


def test_cusum_step_up_does_not_retire():
    """绩效轴：绩效**上升**（收益变好）绝不触发退役——只有下降侧 S⁻ 才 breach。"""
    rng = np.random.default_rng(6)
    up = np.concatenate([rng.standard_normal(30) * _SD0 + _MU0,
                         rng.standard_normal(40) * _SD0 + _MU0 + 3 * _SD0])
    sig = cusum_drift(up, baseline_mean=_MU0, baseline_std=_SD0)
    assert not sig.breach and sig.status == "ok"


def test_cusum_insufficient_on_zero_baseline_std():
    sig = cusum_drift(np.zeros(30), baseline_mean=_MU0, baseline_std=0.0)
    assert sig.status == "insufficient_evidence" and not sig.breach


# ===========================================================================
# ③ Page-Hinkley
# ===========================================================================


def test_page_hinkley_no_drift_ok():
    rng = np.random.default_rng(7)
    sig = page_hinkley_drift(rng.standard_normal(200) * _SD0 + _MU0, baseline_mean=_MU0, baseline_std=_SD0)
    assert sig.status == "ok" and not sig.breach


def test_page_hinkley_step_down_breaches():
    rng = np.random.default_rng(8)
    s = np.concatenate([rng.standard_normal(50) * _SD0 + _MU0,
                        rng.standard_normal(60) * _SD0 + _MU0 - 2 * _SD0])
    sig = page_hinkley_drift(s, baseline_mean=_MU0, baseline_std=_SD0)
    assert sig.breach and sig.statistic > sig.threshold


def test_page_hinkley_global_mean_variant_false_alarms_proving_design_choice():
    """Sentinel（门有牙 + R5 守门器风险自证）：弃用的全局 running-mean PH 在平稳噪声上假告警 ~100%，
    而生产用的 frozen-baseline 变体几乎不假告警——证明我们弃用前者是对的（deep-opus 实证陷阱）。
    """
    rejected_fa = sum(
        _page_hinkley_global_mean_variant(np.random.default_rng(s).standard_normal(500), delta=0.0, threshold_lambda=8.0)
        for s in range(120)
    )
    assert rejected_fa > 100, f"弃用变体竟不假告警 {rejected_fa}/120？则 sentinel 失判别力"
    chosen_fa = sum(
        page_hinkley_drift(np.random.default_rng(s).standard_normal(500) * _SD0 + _MU0,
                           baseline_mean=_MU0, baseline_std=_SD0).breach
        for s in range(120)
    )
    assert chosen_fa == 0, f"frozen-baseline 变体平稳噪声假告警 {chosen_fa}/120（应 0）"


def test_page_hinkley_insufficient_on_short_sample():
    sig = page_hinkley_drift(np.array([0.001, 0.002]), baseline_mean=_MU0, baseline_std=_SD0)
    assert sig.status == "insufficient_evidence" and not sig.breach


# ===========================================================================
# ④ PSI — 特征轴仅根因
# ===========================================================================


def test_psi_identical_distribution_is_none():
    rng = np.random.default_rng(9)
    base = rng.standard_normal(5000)
    diag = population_stability_index(base, rng.standard_normal(5000))
    assert diag.severity == "none" and diag.psi >= 0.0


def test_psi_shifted_distribution_is_major():
    rng = np.random.default_rng(10)
    diag = population_stability_index(rng.standard_normal(5000), rng.standard_normal(5000) + 1.0)
    assert diag.severity == "major" and diag.psi > 0.25


def test_psi_symmetric_and_nonneg_and_zero_iff_identical():
    """PSI 是 Jeffreys（对称）散度：PSI(a,e)=PSI(e,a)、≥0、=0 ⟺ 同分布。种非对称 KL 会被抓。"""
    e = np.array([0.1, 0.2, 0.3, 0.4])
    a = np.array([0.4, 0.3, 0.2, 0.1])
    p1, _ = psi_from_proportions(e, a)
    p2, _ = psi_from_proportions(a, e)
    assert abs(p1 - p2) < 1e-12 and p1 > 0.0           # 对称 + 非负
    assert psi_from_proportions(e, e)[0] == 0.0        # 恒等 → 0


def test_psi_zero_bucket_flagged_and_finite():
    psi, zb = psi_from_proportions(np.array([0.5, 0.5, 0.0]), np.array([0.3, 0.3, 0.4]))
    assert zb is True and np.isfinite(psi)             # ε 平滑 → 有限值 + zero_bucket 留痕


def test_psi_short_sample_insufficient():
    diag = population_stability_index(np.arange(5.0), np.arange(5.0))
    assert diag.severity == "insufficient_evidence"


def test_psi_diagnosis_has_no_retirement_surface():
    """命门 D2（类型隔离）：FeatureDriftDiagnosis 绝无 breach 字段、绝无 to_lifecycle_observation。"""
    diag = population_stability_index(np.random.default_rng(11).standard_normal(500),
                                      np.random.default_rng(12).standard_normal(500) + 2.0)
    assert not hasattr(diag, "breach")
    assert not hasattr(diag, "to_lifecycle_observation")
    assert diag.axis == "feature"


# ===========================================================================
# 非有限值(NaN/inf) → insufficient_evidence（评审 high 发现回归：绝不静默读 ok）
#   停牌/喂数缺口插 NaN → NaN<floor 恒 False 会绕过数值守门 → 主告警假绿灯=对真钱致命静默。
# ===========================================================================


def test_rolling_psr_nan_is_insufficient_not_ok():
    """种：本应 breach 的零 edge 窗插 3 个 NaN（模拟喂数缺口）→ 必判 insufficient，绝不 ok（假绿灯）。"""
    rng = np.random.default_rng(20)
    bad = rng.standard_normal(120) * 0.01      # 零 edge，干净时 breach
    assert rolling_psr_drift(bad).breach
    bad[[10, 50, 90]] = np.nan
    sig = rolling_psr_drift(bad)
    assert sig.status == "insufficient_evidence" and not sig.breach


def test_cusum_nan_is_insufficient_not_silently_washed():
    """种：CUSUM 序列插 NaN → max(0,NaN)==0 会把 NaN 洗成 0、伪 ok。必判 insufficient。"""
    s = np.concatenate([np.full(10, _MU0), [np.nan], np.full(10, _MU0)])
    sig = cusum_drift(s, baseline_mean=_MU0, baseline_std=_SD0)
    assert sig.status == "insufficient_evidence" and not sig.breach


def test_cusum_nonfinite_baseline_is_insufficient():
    """种：基准本身 NaN（nan<1e-12 恒 False 绕过 σ 守门）→ 必判 insufficient。"""
    sig = cusum_drift(np.full(30, _MU0), baseline_mean=float("nan"), baseline_std=_SD0)
    assert sig.status == "insufficient_evidence" and not sig.breach


def test_page_hinkley_nan_is_insufficient_not_ok():
    """种：PH 序列插 NaN（min/max 吞 NaN）→ 必判 insufficient，绝不 ok。"""
    s = np.concatenate([np.full(30, _MU0), [np.nan], np.full(30, _MU0 - 2 * _SD0)])
    sig = page_hinkley_drift(s, baseline_mean=_MU0, baseline_std=_SD0)
    assert sig.status == "insufficient_evidence" and not sig.breach


def test_psi_nan_is_insufficient_not_fake_severity():
    """种：PSI 样本含 NaN（np.histogram 静默丢弃→低估 PSI）→ 必判 insufficient，绝不伪造 severity。"""
    rng = np.random.default_rng(21)
    e = rng.standard_normal(500)
    a = rng.standard_normal(500) + 2.0
    a[[1, 2, 3]] = np.nan
    diag = population_stability_index(e, a)
    assert diag.severity == "insufficient_evidence"
    # 对称：expected 含 NaN 亦然
    e2 = e.copy(); e2[[4, 5]] = np.inf
    assert population_stability_index(e2, rng.standard_normal(500)).severity == "insufficient_evidence"


# ===========================================================================
# 接线 + 范畴红线（monitor_tick）
# ===========================================================================


def _mgr(tmp_path, state, fname="f.json"):
    reg = FactorRegistry(tmp_path / fname)
    factor = reg.register("z", "close")
    reg.update_state("z", factor.version, state)
    mgr = LifecycleManager(reg, thresholds=LifecycleThresholds(warning_persist_weeks=2))
    return reg, mgr, factor.version


def test_perf_drift_breach_records_degradation_and_can_retire(tmp_path):
    """绩效轴漂移 breach 喂 monitor_tick → 记降级观测（真动作），连续 2 周驱动 RETIRED（A1 单一 PROV）。"""
    reg, mgr, v = _mgr(tmp_path, "WARNING")
    bad = rolling_psr_drift(np.random.default_rng(13).standard_normal(252) * 0.01)   # 零 edge → breach
    assert bad.breach
    a1 = monitor_tick(mgr, "z", v, perf_drift=bad)
    assert a1.perf_drift_breach and a1.perf_drift_detector == "rolling_psr"
    assert mgr.history("z", v)[-1].ic_mean < 0                # 降级动作真被调用
    assert a1.lifecycle_event is None                         # 差 1 周
    a2 = monitor_tick(mgr, "z", v, perf_drift=bad)
    assert a2.lifecycle_event is not None and a2.lifecycle_event.to_state == "RETIRED"
    assert len(mgr.events("z")) == 1                          # 单一 PROV


def test_perf_drift_ok_records_nothing(tmp_path):
    reg, mgr, v = _mgr(tmp_path, "WARNING")
    good = rolling_psr_drift(np.random.default_rng(14).standard_normal(252) * 0.01 + 0.0015)
    assert not good.breach
    a = monitor_tick(mgr, "z", v, perf_drift=good)
    assert not a.perf_drift_breach and mgr.history("z", v) == []


def test_non_breach_signal_refuses_to_become_degradation_observation():
    """不假绿灯：ok/insufficient 信号转退化观测 = 调用方逻辑错误，必 raise。"""
    good = PerfDriftSignal(detector="rolling_psr", status="ok", statistic=0.99, threshold=0.9, breach=False)
    with pytest.raises(ValueError, match="非 breach"):
        good.to_lifecycle_observation("z", 1)


def test_psi_diagnosis_cannot_drive_retirement_red_line(tmp_path):
    """命门 D2（最关键对抗）：特征轴 PSI 诊断**喂不进**退役矩阵——类型层 raise，绝不退役。

    种「PSI 剧烈漂移」的 FeatureDriftDiagnosis 直接塞 monitor_tick.perf_drift → TypeError（范畴红线）。
    """
    reg, mgr, v = _mgr(tmp_path, "WARNING")
    psi_diag = population_stability_index(np.random.default_rng(15).standard_normal(500),
                                          np.random.default_rng(16).standard_normal(500) + 3.0)
    assert psi_diag.severity == "major"
    with pytest.raises(TypeError, match="特征轴|performance"):
        monitor_tick(mgr, "z", v, perf_drift=psi_diag)        # type: ignore[arg-type]
    assert reg.get("z").lifecycle_state == "WARNING"          # 绝未因特征漂移退役
    assert mgr.history("z", v) == []


def test_severe_feature_drift_alone_never_retires_but_perf_crash_does(tmp_path):
    """正交性：PSI 大但绩效仍 ok → 不退役；PSI≈0 但绩效崩 → 照常退役（绩效轴独立告警）。"""
    # 绩效仍健康（PSR ok）→ 即便特征剧烈漂移，绩效轴不 breach、不退役
    reg, mgr, v = _mgr(tmp_path, "WARNING")
    healthy = rolling_psr_drift(np.random.default_rng(17).standard_normal(252) * 0.01 + 0.0015)
    monitor_tick(mgr, "z", v, perf_drift=healthy)
    monitor_tick(mgr, "z", v, perf_drift=healthy)
    assert reg.get("z").lifecycle_state == "WARNING"          # 绩效好 → 不退役（特征漂移≠绩效失败）
    # 绩效崩（PSR breach）→ 照常退役
    reg2, mgr2, v2 = _mgr(tmp_path, "WARNING", fname="f2.json")
    crash = rolling_psr_drift(np.random.default_rng(18).standard_normal(252) * 0.01)
    monitor_tick(mgr2, "z", v2, perf_drift=crash)
    a = monitor_tick(mgr2, "z", v2, perf_drift=crash)
    assert a.lifecycle_event is not None and a.lifecycle_event.to_state == "RETIRED"


def test_monitor_tick_still_rejects_gate_verdict_params():
    """范畴红线回归：加 perf_drift 后签名仍绝不含 DSR/PBO gate verdict。"""
    import inspect

    params = set(inspect.signature(monitor_tick).parameters)
    for forbidden in ("verdict", "gate_verdict", "pbo", "dsr", "gate", "overfit"):
        assert forbidden not in params
