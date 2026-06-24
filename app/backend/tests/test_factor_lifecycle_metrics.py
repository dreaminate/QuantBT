"""§3 因子机构级生命周期度量 对抗测试（衰减半衰期 / 容量 / 因子族 / 拥挤）。

设计/推导见 `dev/research/findings/dreaminate/factor-lifecycle-institutional.md`。门必抓：
- 半衰期 h=ln(0.5)/ln(ρ)（ρ=0.5→1、√0.5→2）；**ρ 绝不被 clip**（爆炸/反转诚实判异常，非假有限 h 喂退役）。
- 容量 C=ADV·α²/(τ³Y²σ²)：τ³ 标度（τ翻倍→C/8）；α≤0→no_edge；τ/σ=0→invalid；回代 cost(C)≈α。
- 因子族复用 n_eff 锁定口径：等价/反相关→1 族、独立→N 族，**n_families==n_eff.point 交叉校验**；NaN corr 不填 0。
- 拥挤定性咨询：数据不足→insufficient（非 none）；**结构无任何减仓/动作字段**；elevated 只警示。
"""

from __future__ import annotations

import math

import numpy as np
import pytest

from app.eval.n_eff import n_eff_from_matrix
from app.factor_factory.lifecycle_metrics import (
    CrowdingAdvisory,
    crowding_advisory,
    factor_families,
    ic_decay_half_life,
    strategy_capacity,
)


def _ar1(rho, n=400, seed=0, sigma=0.05):
    rng = np.random.default_rng(seed)
    ic = np.zeros(n)
    for t in range(1, n):
        ic[t] = rho * ic[t - 1] + rng.standard_normal() * sigma
    return ic


# ===========================================================================
# ① 衰减半衰期
# ===========================================================================


def test_decay_half_life_recovers_ar1_persistence():
    d = ic_decay_half_life(_ar1(0.5, n=2000))
    assert d.status == "ok" and abs(d.rho - 0.5) < 0.05 and abs(d.half_life - 1.0) < 0.2


def test_decay_half_life_monotone_in_rho():
    hs = [ic_decay_half_life(_ar1(r, n=3000)).half_life for r in (0.4, 0.6, 0.8, 0.9)]
    for i in range(len(hs) - 1):
        assert hs[i] < hs[i + 1], f"半衰期非单调升 {hs}"


def test_decay_rho_not_clipped_explosive_is_no_decay():
    """命门：爆炸序列（ρ≥1）**绝不** clip 成假有限半衰期 + status=ok——须诚实 no_decay。"""
    explosive = 0.001 * (1.05 ** np.arange(300)) + np.random.default_rng(0).standard_normal(300) * 1e-6
    d = ic_decay_half_life(explosive)
    assert d.status == "no_decay" and not math.isfinite(d.half_life)
    assert d.rho >= 1.0   # ρ 未被夹到 <1


def test_decay_reversal_and_insufficient():
    assert ic_decay_half_life(_ar1(-0.6, n=2000)).status == "reversal"   # ρ≤0 反转
    assert ic_decay_half_life(np.random.default_rng(0).standard_normal(20)).status == "insufficient"
    assert ic_decay_half_life(np.ones(200)).status == "insufficient"      # 方差≈0


def test_decay_random_walk_rarely_fake_ok_multiseed():
    """随机游走（ρ=1）**绝大多数种子**判 unstable/no_decay，绝不对随机游走发自信 status=ok。

    评审纠偏：原单种子(seed0)侥幸通过、seed5 即翻红——改跨种子 sweep（对齐 methodology 多种子纪律）。
    local-to-unity 边界 ρ̂>0.95 降级 unstable 后，ρ=1 的 'ok' 占比应 <10%（残余=有限样本下随机游走「看着像平稳」的
    不可约模糊，honest；机器门不对随机游走发 ok 的硬约束由此守住）。
    """
    ok = sum(ic_decay_half_life(_ar1(1.0, n=300, seed=s)).status == "ok" for s in range(60))
    assert ok / 60 < 0.10, f"随机游走被判 ok 占比 {ok / 60:.2%} 过高（unstable 闸对 local-to-unity 判别力不足）"


def test_decay_legit_persistence_stays_ok_multiseed():
    """对称：真持久因子（ρ=0.9，半衰期~6.6）绝大多数种子仍判 ok（边界不冤杀合法因子）。"""
    ok = sum(ic_decay_half_life(_ar1(0.9, n=2000, seed=s)).status == "ok" for s in range(40))
    assert ok / 40 > 0.9, f"合法持久因子被误判 ok 占比仅 {ok / 40:.2%}（边界过激进冤杀）"


# ===========================================================================
# ② 容量（sqrt-impact）
# ===========================================================================


def test_capacity_tau_cubed_scaling():
    """τ³ 标度（最易写成 τ²）：τ 翻倍 → 容量 /8。"""
    base = strategy_capacity(0.002, 0.1, 1e8, 0.02)
    dbl = strategy_capacity(0.002, 0.2, 1e8, 0.02)
    assert base.status == "ok" and abs(base.capacity / dbl.capacity - 8.0) < 1e-6


def test_capacity_alpha_squared_and_adv_linear():
    base = strategy_capacity(0.002, 0.1, 1e8, 0.02)
    assert abs(strategy_capacity(0.004, 0.1, 1e8, 0.02).capacity / base.capacity - 4.0) < 1e-6   # α²
    assert abs(strategy_capacity(0.002, 0.1, 2e8, 0.02).capacity / base.capacity - 2.0) < 1e-6   # ADV
    assert abs(strategy_capacity(0.002, 0.1, 1e8, 0.04).capacity / base.capacity - 0.25) < 1e-6  # 1/σ²


def test_capacity_no_edge_and_invalid():
    assert strategy_capacity(-0.001, 0.1, 1e8, 0.02).status == "no_edge"
    assert strategy_capacity(0.0, 0.1, 1e8, 0.02).status == "no_edge"
    for bad in [(0.002, 0.0, 1e8, 0.02), (0.002, 0.1, 0.0, 0.02), (0.002, 0.1, 1e8, 0.0)]:
        assert strategy_capacity(*bad).status == "invalid"   # τ/ADV/σ=0 绝不返普通数值
    assert strategy_capacity(float("nan"), 0.1, 1e8, 0.02).status == "invalid"


def test_capacity_cost_at_capacity_equals_alpha():
    """回代自检：cost(C) ≈ α_gross（净 alpha=0 的容量定义）。"""
    a, tau, adv, sig, Y = 0.0015, 0.08, 5e7, 0.015, 0.1
    C = strategy_capacity(a, tau, adv, sig, impact_coef=Y).capacity
    cost = tau * Y * sig * (tau * C / adv) ** 0.5
    assert abs(cost - a) < 1e-9


# ===========================================================================
# ③ 因子族（== n_eff 交叉校验）
# ===========================================================================


def test_factor_families_equivalent_columns_collapse_to_one():
    rng = np.random.default_rng(1)
    col = rng.standard_normal((200, 1)) * 0.01
    assert factor_families(np.repeat(col, 8, axis=1)).n_families == 1
    assert factor_families(np.hstack([col, -col])).n_families == 1   # 反相关 |corr|=1 也 1 族


def test_factor_families_independent_are_n():
    rng = np.random.default_rng(2)
    assert factor_families(rng.standard_normal((400, 6)) * 0.01).n_families == 6


def test_factor_families_equals_neff_cluster_count_cross_check():
    """**命门交叉校验**：因子族数 == n_eff 点估计（同一锁定聚类口径，绑 honest-N R8/R19）。"""
    for s in range(30):
        rng = np.random.default_rng(100 + s)
        rm = rng.standard_normal((300, int(rng.integers(2, 12)))) * 0.01
        assert factor_families(rm).n_families == n_eff_from_matrix(rm).point, f"seed={s} 口径漂移"


def test_factor_families_order_and_sign_invariant():
    rng = np.random.default_rng(3)
    rm = rng.standard_normal((300, 8)) * 0.01
    base = factor_families(rm).n_families
    perm = rng.permutation(8)
    assert factor_families(rm[:, perm]).n_families == base       # 列序无关
    assert factor_families(rm * np.array([1, -1, 1, -1, 1, -1, 1, -1])).n_families == base   # 符号无关


def test_factor_families_zero_variance_column_self_family_not_corr_zero():
    """NaN corr（零方差列）→ 自成一簇，**绝不**填 0 相关把它误并。"""
    rng = np.random.default_rng(4)
    rm = np.hstack([rng.standard_normal((200, 3)) * 0.01, np.ones((200, 1)) * 0.005])  # 末列常量
    ff = factor_families(rm)
    assert ff.n_families == n_eff_from_matrix(rm).point   # 与 n_eff 同处理


# ===========================================================================
# ④ 拥挤（定性咨询 · 命门：禁自动减仓）
# ===========================================================================


_FORBIDDEN_FIELDS = ("reduce_position", "haircut", "multiplier", "trade_action", "target_weight",
                     "position", "weight", "size", "order")


def test_crowding_insufficient_data_is_not_none():
    """数据不足（默认/无篮）→ data_status=insufficient + level=watch，**绝不** none（missing≠不拥挤）。"""
    a = crowding_advisory()
    assert a.data_status == "insufficient" and a.level == "watch"
    assert crowding_advisory(basket_correlation=float("nan"), data_complete=True).data_status == "insufficient"


def test_crowding_levels_from_basket_correlation():
    assert crowding_advisory(basket_correlation=0.85, data_complete=True).level == "elevated"
    assert crowding_advisory(basket_correlation=0.5, data_complete=True).level == "watch"
    assert crowding_advisory(basket_correlation=0.1, data_complete=True).level == "none"
    assert crowding_advisory(basket_correlation=-0.85, data_complete=True).level == "elevated"   # |corr|


def test_crowding_advisory_has_no_action_fields_red_line():
    """命门红线：CrowdingAdvisory 结构上**无任何减仓/动作字段**——绝不自动减仓（GOAL §3）。"""
    a = crowding_advisory(basket_correlation=0.9, data_complete=True)
    fields = set(getattr(CrowdingAdvisory, "__dataclass_fields__", {}))
    assert fields == {"level", "data_status", "evidence"}
    for f in _FORBIDDEN_FIELDS:
        assert not hasattr(a, f), f"拥挤咨询竟有动作字段 {f}（违 GOAL §3 禁自动减仓）"


# ===========================================================================
# codex 顾问 P2 修复回归（零拥挤≠缺失 / IC 不跨缺口拼接 / 因子族阈值锁定）
# ===========================================================================


def test_crowding_zero_correlation_is_valid_none_not_missing():
    """codex P2：basket_correlation=0.0 + data_complete → 有效零相关=none/ok，**绝不**被 falsy 陷阱当 missing。"""
    a = crowding_advisory(basket_correlation=0.0, data_complete=True)
    assert a.level == "none" and a.data_status == "ok"   # 而非 watch/insufficient


def test_decay_does_not_stitch_across_nan_gaps():
    """codex P2：IC 有 NaN 缺口时，ρ 只用 (t−1,t) 两端皆有限的对，**绝不**跨缺口拼接污染。"""
    rng = np.random.default_rng(0)
    ic = np.zeros(400)
    for t in range(1, 400):
        ic[t] = 0.6 * ic[t - 1] + rng.standard_normal() * 0.05
    ic[[50, 51, 120, 200, 201, 202, 300]] = np.nan   # 散布缺口
    d = ic_decay_half_life(ic, min_periods=30)
    # 手算「正确对齐」的 ρ（只取两端皆有限的滞后对）
    x_full, y_full = ic[:-1], ic[1:]
    m = np.isfinite(x_full) & np.isfinite(y_full)
    x, y = x_full[m], y_full[m]
    xm, ym = x.mean(), y.mean()
    rho_correct = float(np.sum((x - xm) * (y - ym)) / np.sum((x - xm) ** 2))
    assert abs(d.rho - rho_correct) < 1e-9, "ρ 与正确对齐不符（疑跨缺口拼接）"
    assert d.n_obs == int(m.sum())   # n_obs = 有效滞后对数（非压扁后长度）


def test_factor_families_threshold_is_locked_no_override():
    """codex P2 + RULES.project「honest-N 不可手动改小」：factor_families **不暴露 corr_threshold 入参**（防放水）。"""
    import inspect

    params = set(inspect.signature(factor_families).parameters) - {"returns_matrix"}
    assert not params, f"factor_families 暴露了可放水的阈值口：{params}"


def test_capacity_delta_locked_no_override():
    """评审 P2：容量 δ=0.5（R18）锁定、**不暴露入参**（可调则自检 cost(C)≈α 对错 δ 循环无效）。"""
    import inspect

    assert "delta" not in inspect.signature(strategy_capacity).parameters


def test_capacity_placeholder_impact_coef_warns():
    """评审 P2：省略 impact_coef → 用占位 0.1 但**诚实告警**（绝不让占位冒充数据驱动容量）。"""
    no_y = strategy_capacity(0.002, 0.1, 1e8, 0.02)              # 省略 Y
    assert no_y.status == "ok" and any("占位" in w for w in no_y.warnings)
    with_y = strategy_capacity(0.002, 0.1, 1e8, 0.02, impact_coef=0.1)   # 显式 Y
    assert not any("占位" in w for w in with_y.warnings)
    assert no_y.capacity == with_y.capacity                      # 值相同（Y 同），仅告警差


def test_crowding_thresholds_locked_no_override():
    """评审 P2：拥挤等级阈值锁定、不暴露入参（防放水压低 elevated 警示）。"""
    import inspect

    params = set(inspect.signature(crowding_advisory).parameters)
    assert params == {"basket_correlation", "data_complete"}


def test_crowding_out_of_range_correlation_not_trusted():
    """越界相关 |corr|>1 = 上游脏值 → 绝不编码成可信 ok（同 missing≠0 精神）。"""
    a = crowding_advisory(basket_correlation=1.5, data_complete=True)
    assert a.data_status == "insufficient" and a.level != "none"
