"""aa13c3b0 · IC 持久性 AR(1) 半衰期接进 lifecycle 状态机（perf 轴·advisory）对抗测试。

门必抓：
- **命门单一源**：`LifecycleManager.decay_diagnostic` == `lifecycle_metrics.ic_decay_half_life`（绝不重实现漂移）。
- **advisory 绝不硬退役**：非持久（reversal）/随机游走（unstable）IC 不触发硬转移——decay 仅 advisory（slice-4 自律）。
- **诚实 status**：近单位根/随机游走 → status='unstable'，机器绝不对随机游走发 'ok'（不假绿灯）。
- **M-AUTHORITY perf 轴**：转移只吃 perf 轴 IC 观测，注入 gate verdict（DSR/PBO/color）不改判（A1 铁律）。
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import numpy as np

from app.factor_factory.lifecycle import (
    FactorObservation,
    LifecycleManager,
    LifecycleThresholds,
    evaluate_transition,
)
from app.factor_factory.lifecycle_metrics import ic_decay_half_life
from app.factor_factory.registry import FactorRegistry


def _ar1(n: int, rho: float, seed: int, mu: float = 0.0, sigma: float = 0.01) -> np.ndarray:
    rng = np.random.default_rng(seed)
    x = np.empty(n)
    x[0] = mu
    for i in range(1, n):
        x[i] = mu + rho * (x[i - 1] - mu) + rng.standard_normal() * sigma
    return x


def _seed_factor(tmp_path: Path, name: str, ic_series, state: str, *, ir: float = 0.7):
    reg = FactorRegistry(tmp_path / f"{name}.json")
    factor = reg.register(name, "close")
    reg.update_state(name, factor.version, state)
    mgr = LifecycleManager(reg)
    for i, ic in enumerate(ic_series):
        mgr.record_observation(FactorObservation(
            factor_id=name, version=factor.version,
            observed_at_utc=f"2024-{(i // 28) + 1:02d}-{(i % 28) + 1:02d}T00:00:00+00:00",
            horizon=5, ic_mean=float(ic), ic_ir=ir, rank_ic_mean=float(ic) * 0.8, sample_t=4.0,
        ))
    return reg, mgr, factor.version


def test_decay_diagnostic_single_source_matches_lifecycle_metrics(tmp_path):
    """**命门单一源**：decay_diagnostic 与 ic_decay_half_life 逐字段一致——**扫多 ρ 区间**（含 >0.9 近单位根、
    reversal），绝不重实现漂。

    教训（评审/mutation 纠偏）：只测单个 ρ=0.6 会漏掉「仅在某 ρ 区间发散」的重实现 bug（如 clip ρ>0.9）；
    故扫 {0.3,0.6,0.9,0.97} + 反转序列，逐字段（rho/half_life/status/n_obs）全等才算单一源。
    """
    cases = [_ar1(80, rho=r, seed=10 + i, mu=0.02) for i, r in enumerate((0.3, 0.6, 0.9, 0.97))]
    cases.append(0.05 - _ar1(80, rho=0.3, seed=99) * 0.0)        # 近常数（低自相关）触 reversal/unstable 路径
    for j, ic in enumerate(cases):
        _, mgr, v = _seed_factor(tmp_path, f"ss{j}", ic, "OBSERVATION")
        got = mgr.decay_diagnostic(f"ss{j}", v)
        ref = ic_decay_half_life([float(x) for x in ic])
        assert got is not None
        # rho/half_life 可能 NaN（reversal/undefined）→ 用 repr 比，使 NaN==NaN 也算一致
        assert repr(got.rho) == repr(ref.rho) and repr(got.half_life) == repr(ref.half_life), \
            f"case{j} rho/half_life 偏离单一源：got={got.rho}/{got.half_life} ref={ref.rho}/{ref.half_life}"
        assert got.status == ref.status and got.n_obs == ref.n_obs


def test_decay_advisory_does_not_force_retirement(tmp_path):
    """**门有牙·advisory 不硬退役**：IC 水平稳定（无水平衰减）但非持久（快均值回复）的因子，
    decay 诊断标非持久、但**绝不被硬退役/降级**——decay 仅 advisory（种坏：把 decay 当硬触发→此因子误退）。"""
    rng = np.random.default_rng(7)
    ic = 0.05 + rng.standard_normal(35) * 0.004        # 水平稳定 +0.05、低自相关（快均值回复）
    _, mgr, v = _seed_factor(tmp_path, "adv", ic, "OBSERVATION")
    event = mgr.evaluate("adv", v)
    assert event is None                                # 水平未衰减 → 不转移（保持 OBSERVATION）
    diag = mgr.decay_diagnostic("adv", v)
    assert diag is not None and diag.status != "ok"    # 诊断如实标非持久（reversal/unstable/…）
    # 反证：硬退役只由水平衰减规则决定，与 decay 持久性无关
    from app.factor_factory.registry import FactorRegistry as _R
    assert _R(tmp_path / "adv.json").get("adv").lifecycle_state == "OBSERVATION"


def test_decay_diagnostic_random_walk_is_unstable_not_ok(tmp_path):
    """**诚实 status·不假绿灯**：随机游走 IC（ρ≈1）→ status='unstable'/'no_decay'，机器绝不发 'ok'。"""
    ic = _ar1(80, rho=0.985, seed=3, mu=0.0, sigma=0.01)
    _, mgr, v = _seed_factor(tmp_path, "rw", ic, "OBSERVATION")
    diag = mgr.decay_diagnostic("rw", v)
    assert diag is not None and diag.status in ("unstable", "no_decay")
    assert diag.status != "ok", "随机游走被判 ok=假绿灯（机器对随机游走发了硬持久结论）"


def test_decay_diagnostic_insufficient_and_no_history(tmp_path):
    """样本不足 → status='insufficient'（不硬判）；无观测 → None（绝不编造）。"""
    ic = _ar1(10, rho=0.5, seed=4)
    _, mgr, v = _seed_factor(tmp_path, "few", ic, "OBSERVATION")
    diag = mgr.decay_diagnostic("few", v)
    assert diag is not None and diag.status == "insufficient"
    # 无任何观测的因子 → None
    reg2 = FactorRegistry(tmp_path / "empty.json")
    f2 = reg2.register("empty", "close")
    mgr2 = LifecycleManager(reg2)
    assert mgr2.decay_diagnostic("empty", f2.version) is None


def test_transition_is_perf_axis_only_ignores_injected_gate_verdict(tmp_path):
    """**M-AUTHORITY A1**：lifecycle 硬转移只吃 perf 轴 IC 观测——注入 gate verdict（DSR/PBO/color）到
    observation.extra **绝不改判**（退役矩阵绝不接 gate verdict 的铁律，在因子状态机侧同样成立）。"""
    reg = FactorRegistry(tmp_path / "ma.json")
    factor = reg.register("ma", "close")
    reg.update_state("ma", factor.version, "OBSERVATION")
    # 29 健康 + 1 崩塌（触发 OBSERVATION→WARNING 的水平衰减规则）
    base = [FactorObservation(factor_id="ma", version=factor.version,
                              observed_at_utc=f"2024-01-{i + 1:02d}T00:00:00+00:00", horizon=5,
                              ic_mean=0.05, ic_ir=0.7, rank_ic_mean=0.04, sample_t=4.0) for i in range(29)]
    base.append(FactorObservation(factor_id="ma", version=factor.version,
                                  observed_at_utc="2024-01-30T00:00:00+00:00", horizon=5,
                                  ic_mean=0.005, ic_ir=0.1, rank_ic_mean=0.001, sample_t=2.0))
    plain = evaluate_transition(factor, base)
    # 同一序列，但每个观测 extra 注入伪 gate verdict（绿灯+高 DSR+低 PBO，诱导「别退役」）
    poisoned = [FactorObservation(**{**o.to_dict(),
                "extra": {"dsr": 0.99, "pbo": 0.0, "gate_color": "green", "all_agree_positive": True}})
                for o in base]
    poisoned_state = evaluate_transition(factor, poisoned)
    assert plain == poisoned_state == "WARNING", \
        f"注入 gate verdict 改了转移（plain={plain} poisoned={poisoned_state}）→ 退役吃了 gate 轴信号（M-AUTHORITY 破）"
