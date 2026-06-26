"""aa13c3b0 · 因子机构级度量接 sizing/组合独立性/呈现层 **生产路径** 对抗测试（剩余 scope ②③④）。

① 衰减→lifecycle 已 done（见 `test_lifecycle_decay_advisory.py`·card 1b83a5c5）；本文件覆盖卡剩余 ②③④
并钉死 4 条对抗门（卡「对抗测试设计」），每条**种已知坏、门必抓**：

- 对抗 #1（unstable 半衰期**不硬退役**）：跨文件复证 decay advisory 绝不强制退役（status≠ok 不触发硬转移）。
- 对抗 #2（容量 Y 占位**只示意不硬卡** / 真 Y **硬上限**）：`capacity_sizing` 笛卡尔扫
  {status: ok/no_edge/invalid} × {Y: 占位/真} × {proposed </=/> cap} × {mode: research/production}，
  **仅** (ok, 真Y, proposed>cap) 与 (no_edge/invalid, production) 两格 binding。
- 对抗 #3（拥挤**绝不进 sizing**）：sizing 签名**无** crowding 入参（结构隔离）+ 运行期**拒** `CrowdingAdvisory`
  逐槽（防伪）；呈现层 `FactorAdvisoryReport` **接** crowding 且**结构无动作字段**——「呈现接、sizing 拒」。
- 对抗 #4（同族因子**不重复计独立 bet**）：`independent_bet_count` **数族非数列**（相关坍缩、剔零权），
  **==n_eff.point==factor_families.n_families** 交叉校验；阈值/区间锁定不暴露入参（honest-N 不可改小）。

MUT（变异验证门有牙·三态证据见交付报告）：就地削弱 ② placeholder 门 / ③ 剔零权门 / ④ 类型隔离门 → 必转 RED。
"""

from __future__ import annotations

import inspect
import math
from datetime import UTC, datetime
from itertools import product

import numpy as np
import pytest

from app.eval.n_eff import NEffResult, n_eff_from_matrix
from app.factor_factory.factor_advisory import FactorAdvisoryReport, factor_advisory_report
from app.factor_factory.lifecycle import (
    FactorObservation,
    LifecycleManager,
    LifecycleThresholds,
)
from app.factor_factory.lifecycle_metrics import (
    CrowdingAdvisory,
    crowding_advisory,
    factor_families,
    strategy_capacity,
)
from app.factor_factory.registry import FactorRegistry
from app.monitor.closure import monitor_tick
from app.portfolio.capacity_sizing import CapacitySizingDecision, capacity_sizing_cap
from app.portfolio.independence import independent_bet_count

# sizing 动作字段红线词表（与 test_factor_lifecycle_metrics._FORBIDDEN_FIELDS 同口径）。
_FORBIDDEN_FIELDS = (
    "reduce_position", "haircut", "multiplier", "trade_action", "target_weight",
    "position", "weight", "size", "order", "allowed_notional", "binding",
)

# 已知 ok 容量基准配置（真 Y=0.1）：capacity≈1e11（与 test_factor_lifecycle_metrics 同参数族）。
_OK = dict(gross_alpha=0.002, turnover=0.1, adv=1e8, volatility=0.02)
_OK_CAP = strategy_capacity(**_OK, impact_coef=0.1).capacity


def _correlated(n: int, rho: float, seed: int) -> tuple[np.ndarray, np.ndarray]:
    """返回两列总体相关 ρ 的标准正态序列（x, ρ·x+√(1−ρ²)·z）——大 n 下样本相关≈ρ。"""
    rng = np.random.default_rng(seed)
    x = rng.standard_normal(n)
    z = rng.standard_normal(n)
    y = rho * x + math.sqrt(max(0.0, 1.0 - rho * rho)) * z
    return x, y


# ===========================================================================
# 对抗 #1 · unstable 半衰期不硬退役（跨文件复证 advisory 绝不强制退役）
# ===========================================================================


def test_adversarial_1_unstable_decay_never_forces_retirement(tmp_path):
    """种坏：把「随机游走(unstable)/反持久」当硬退役触发器。门必抓——advisory 绝不改硬转移。

    构造水平**稳定**(无水平衰减→无硬转移)但 IC 非持久的 OBSERVATION 因子：硬状态机保持 OBSERVATION，
    decay 诊断如实标非 ok（unstable/no_persistence/…）。**若有人把 decay 接成硬退役→此因子会被误退→RED**。
    """
    reg = FactorRegistry(tmp_path / "u.json")
    f = reg.register("u", "close")
    reg.update_state("u", f.version, "OBSERVATION")
    mgr = LifecycleManager(reg)
    rng = np.random.default_rng(7)
    ic = 0.05 + rng.standard_normal(35) * 0.004        # 水平稳定 +0.05、低自相关（快均值回复）
    for i, v in enumerate(ic):
        mgr.record_observation(FactorObservation(
            factor_id="u", version=f.version,
            observed_at_utc=f"2024-{(i // 28) + 1:02d}-{(i % 28) + 1:02d}T00:00:00+00:00",
            horizon=5, ic_mean=float(v), ic_ir=0.7, rank_ic_mean=float(v) * 0.8, sample_t=4.0,
        ))
    event = mgr.evaluate("u", f.version)
    assert event is None, "水平未衰减却发生硬转移（decay 被误接成硬触发？）"
    diag = mgr.decay_diagnostic("u", f.version)
    assert diag is not None and diag.status != "ok", "非持久 IC 竟标 ok（假绿灯）"
    assert reg.get("u").lifecycle_state == "OBSERVATION", "advisory 把因子硬退役了（门是纸做的）"


# ===========================================================================
# 对抗 #2 · 容量→sizing：Y 占位只示意不硬卡 / 真 Y 硬上限（笛卡尔扫）
# ===========================================================================


def _decision(status: str, y_real: bool, rel: str, mode: str) -> CapacitySizingDecision:
    """按 (status, Y 真伪, proposed 相对 cap, mode) 造一个 sizing 决策。"""
    if status == "ok":
        kw, cap = dict(_OK), _OK_CAP
    elif status == "no_edge":
        kw, cap = dict(_OK, gross_alpha=-0.001), 0.0        # α≤0 → no_edge
    else:  # invalid
        kw, cap = dict(_OK, adv=0.0), float("nan")          # adv=0 → invalid
    proposed = {"<": cap * 0.5, "=": cap, ">": cap * 2.0}[rel] if (status == "ok") else 1e6
    impact = 0.1 if y_real else None
    return capacity_sizing_cap(proposed, mode=mode, impact_coef=impact, **kw)


def test_adversarial_2_capacity_sizing_cartesian_binding_truth_table():
    """**笛卡尔真值表**：binding **仅** (ok,真Y,proposed>cap,*) 与 (no_edge/invalid,*,production)。

    种坏（评审锁定逃逸变异）：`allowed=min(proposed,cap)` **无条件** / 忽略 placeholder / 忽略 mode——
    任一个会让某格 binding 翻转→RED。单点 happy-path 放不过，必须扫全积。
    """
    for status, y_real, rel, mode in product(
        ("ok", "no_edge", "invalid"), (True, False), ("<", "=", ">"), ("research", "production")
    ):
        d = _decision(status, y_real, rel, mode)
        if status == "ok" and y_real and rel == ">":
            assert d.binding and d.allowed_notional == pytest.approx(_OK_CAP) and d.reason == "ok_bound", \
                f"(ok,真Y,>) 应硬上限至容量：{d}"
            assert d.allowed_notional < d.proposed_notional
        elif status == "ok" and (not y_real):
            # Y 占位：任何 proposed 都**只示意不硬卡**（绝不编造硬上限）。
            assert not d.binding and d.allowed_notional == d.proposed_notional, f"(ok,占位Y) 竟硬卡：{d}"
            assert d.reason == "placeholder_advisory" and d.is_placeholder_capacity
        elif status == "ok":  # 真 Y 但 proposed ≤ cap
            assert not d.binding and d.reason == "ok_within_capacity", f"(ok,真Y,≤) 不应缩仓：{d}"
        elif status in ("no_edge", "invalid"):
            if mode == "production":
                assert d.binding and d.allowed_notional == 0.0, f"({status},production) 应 fail-closed=0：{d}"
            else:
                assert not d.binding and d.allowed_notional == d.proposed_notional, \
                    f"({status},research) 不应自动清仓（系统无权替 user 定方法学）：{d}"


def test_adversarial_2_placeholder_and_real_same_capacity_value_only_binding_differs():
    """命门：占位 Y 与显式 Y 的容量**数值相同**（test_factor_lifecycle_metrics:252）——故 placeholder 必在
    call-site 捕获、绝不从值反推。两者同 proposed>cap：真 Y 硬卡、占位只示意。"""
    big = _OK_CAP * 2.0
    real = capacity_sizing_cap(big, impact_coef=0.1, **_OK)
    ph = capacity_sizing_cap(big, **_OK)                       # 省略 impact_coef = 占位
    assert real.capacity == ph.capacity                       # 容量值相同
    assert real.binding and real.allowed_notional == pytest.approx(_OK_CAP)
    assert (not ph.binding) and ph.allowed_notional == big and ph.is_placeholder_capacity
    assert any("示意" in n or "占位" in n for n in ph.notes)   # 诚实标


def test_adversarial_2_degenerate_capacity_never_binds():
    """near-zero τ → 容量 ∝1/τ³ 溢出成 inf；status=ok 但**绝不**在无意义 cap 上 binding（静默假门）。

    种坏：盲 `min(proposed, inf)` 把退化容量也当真 cap。门必抓——非有限 cap → capacity_degenerate、不 binding。
    """
    d = capacity_sizing_cap(1e9, gross_alpha=0.002, turnover=1e-120, adv=1e8, volatility=0.02, impact_coef=0.1)
    assert not math.isfinite(d.capacity)                      # τ=1e-120 → cap=inf
    assert not d.binding and d.allowed_notional == d.proposed_notional and d.reason == "capacity_degenerate"


# ===========================================================================
# 对抗 #3 · 拥挤绝不进 sizing（类型层隔离）+ 呈现层接 crowding 无动作字段
# ===========================================================================


def test_adversarial_3_sizing_signature_has_no_crowding_param_structural_isolation():
    """**结构隔离**（最硬）：capacity_sizing_cap 签名里根本**没有** crowding/level/haircut 任何入参——
    拥挤数学上进不来 sizing。种坏：有人加个 crowding 参数搞 haircut→签名锁 RED。"""
    params = set(inspect.signature(capacity_sizing_cap).parameters)
    assert params == {"proposed_notional", "gross_alpha", "turnover", "adv", "volatility", "impact_coef", "mode"}
    for forbidden in ("crowding", "crowding_advisory", "level", "haircut", "basket_correlation"):
        assert forbidden not in params, f"sizing 竟暴露拥挤口 {forbidden}（拥挤可进 sizing=红线破）"


def test_adversarial_3_sizing_rejects_crowding_advisory_every_slot():
    """**运行期防伪**（逐槽）：把 `CrowdingAdvisory`（及 elevated/insufficient 各态）塞进任一数值槽 → TypeError。
    种坏：sizing 偷读 crowding.level 做减仓→此处必拒、不可静默吞。"""
    crowds = [
        crowding_advisory(basket_correlation=0.9, data_complete=True),    # elevated
        crowding_advisory(),                                              # insufficient
    ]
    slots = ("proposed_notional", "gross_alpha", "turnover", "adv", "volatility", "impact_coef")
    for cr in crowds:
        for slot in slots:
            kwargs = dict(proposed_notional=1e6, gross_alpha=0.002, turnover=0.1, adv=1e8, volatility=0.02)
            kwargs[slot] = cr
            # proposed_notional 是位置参；其余关键字
            with pytest.raises(TypeError, match="拥挤"):
                if slot == "proposed_notional":
                    capacity_sizing_cap(cr, gross_alpha=0.002, turnover=0.1, adv=1e8, volatility=0.02)
                else:
                    capacity_sizing_cap(1e6, **{k: v for k, v in kwargs.items() if k != "proposed_notional"})


def test_adversarial_3_advisory_report_carries_crowding_but_has_no_action_fields():
    """呈现层**接** crowding（「拥挤接呈现层」）——但 `FactorAdvisoryReport` **结构无任何减仓/动作字段**。
    种坏：呈现面板偷加 haircut/target_weight→字段红线 RED；递归扫 to_dict 也不得现身动作词。"""
    cr = crowding_advisory(basket_correlation=0.92, data_complete=True)
    cap = strategy_capacity(**_OK, impact_coef=0.1)
    rep = factor_advisory_report("f1", capacity=cap, crowding=cr)
    assert rep.crowding is cr and rep.crowding.level == "elevated"        # 真的接住了 crowding（呈现）
    fields = set(FactorAdvisoryReport.__dataclass_fields__)
    assert fields == {"factor_id", "decay", "capacity", "crowding"}, f"呈现面板多了字段：{fields}"
    for f in _FORBIDDEN_FIELDS:
        assert not hasattr(rep, f), f"呈现面板竟有动作字段 {f}（拥挤可经呈现层动作=红线破）"

    def _scan(obj, path="to_dict"):
        if isinstance(obj, dict):
            for k, v in obj.items():
                assert str(k) not in _FORBIDDEN_FIELDS, f"to_dict 现动作键 {path}.{k}"
                _scan(v, f"{path}.{k}")
    _scan(rep.to_dict())


def test_advisory_report_missing_data_is_explicit_not_blank_health():
    """缺数据**显式**呈现（no_history/absent），绝不空白冒充健康（missing≠健康）。"""
    rep = factor_advisory_report("empty")
    d = rep.to_dict()
    assert d["decay"]["status"] == "no_history" and d["capacity"]["status"] == "absent"
    assert d["crowding"]["data_status"] == "absent"


# ===========================================================================
# 对抗 #4 · 因子族→组合独立 bet：数族非数列、剔零权、==n_eff.point
# ===========================================================================


def test_adversarial_4_same_family_factors_not_double_counted():
    """**卡心门**：同族（高相关/反相关/等价）因子**不重复计独立性**。种坏：数持仓列数当独立 bet 数。"""
    x, _ = _correlated(4000, 0.0, 1)
    mat_dup = np.column_stack([x, 0.99 * x, 1.01 * x])           # 3 近等价列
    assert independent_bet_count(mat_dup).point == 1, "3 等价因子被当 3 个独立 bet（同族重复计）"

    x2, y_anti = _correlated(4000, -0.8, 2)                       # |corr|≥0.7 反相关
    assert independent_bet_count(np.column_stack([x2, y_anti])).point == 1, "反相关同族未坍缩"

    x3, y_hi = _correlated(4000, 0.85, 3)                         # 高相关非等价 → 仍坍缩（非「仅 exact dup」）
    assert independent_bet_count(np.column_stack([x3, y_hi])).point == 1, "高相关非等价列未坍缩（疑仅认 exact dup）"

    x4, y_lo = _correlated(4000, 0.30, 4)                         # 弱相关 → 2 独立 bet
    assert independent_bet_count(np.column_stack([x4, y_lo])).point == 2, "弱相关被错误坍缩"


def test_adversarial_4_cross_check_equals_neff_point_and_factor_families():
    """**接 honest-N**：独立 bet 数 ≡ n_eff.point ≡ factor_families.n_families（同一锁定聚类口径·多 seed）。"""
    for seed in range(12):
        rng = np.random.default_rng(100 + seed)
        k = rng.integers(2, 6)
        cols = []
        for _ in range(int(k)):
            base = rng.standard_normal(800)
            reps = rng.integers(1, 4)
            for _ in range(int(reps)):
                cols.append(base + rng.standard_normal(800) * 1e-3)   # 同族近复制
        mat = np.column_stack(cols)
        ib = independent_bet_count(mat)
        assert isinstance(ib, NEffResult)                              # 返 NEffResult（带区间+disclaimer）
        assert ib.point == n_eff_from_matrix(mat).point == factor_families(mat).n_families, \
            f"seed{seed} 独立 bet 口径偏离 n_eff/factor_families 单一源"
        assert ib.low <= ib.point <= ib.high and ib.disclaimer           # 区间诚实度不丢


def test_adversarial_4_zero_weight_columns_excluded():
    """零权因子**非 bet**：剔零权列后再计族。种坏：忘剔零权→把零权因子也计进独立 bet。"""
    x, _ = _correlated(2000, 0.0, 9)
    indep = np.random.default_rng(10).standard_normal(2000)
    mat = np.column_stack([x, 0.99 * x, indep])                    # 列0,1 同族；列2 独立
    # 持仓 {0,1}（剔列2）→ 1 个独立 bet；若忘剔零权→会数成 2（x族+indep）
    assert independent_bet_count(mat, weights=[1.0, 1.0, 0.0]).point == 1
    # 持仓 {0,2}（剔列1）→ 2 个独立 bet
    assert independent_bet_count(mat, weights=[1.0, 0.0, 1.0]).point == 2
    # 全零权 → 0 个独立 bet（绝不编造）
    assert independent_bet_count(mat, weights=[0.0, 0.0, 0.0]).point == 0


def test_adversarial_4_threshold_locked_no_override():
    """honest-N 不可手动改小（组合层）：independent_bet_count **不暴露阈值/区间入参**（仅 returns_matrix+weights）。"""
    params = set(inspect.signature(independent_bet_count).parameters)
    assert params == {"returns_matrix", "weights"}, f"独立 bet 计数暴露了可放水口：{params}"


# ===========================================================================
# ② 监控只读附证 · M-AUTHORITY：capacity 附证绝不改硬转移（绝非退役触发器）
# ===========================================================================


def _warning_factor(tmp_path):
    reg = FactorRegistry(tmp_path / "w.json")
    f = reg.register("w", "close")
    reg.update_state("w", f.version, "WARNING")
    mgr = LifecycleManager(reg, LifecycleThresholds())
    for i in range(2):                                            # 连续 2 期负 IC → WARNING→RETIRED
        mgr.record_observation(FactorObservation(
            factor_id="w", version=f.version,
            observed_at_utc=datetime(2024, 1, i + 1, tzinfo=UTC).isoformat(),
            horizon=5, ic_mean=-0.02, ic_ir=-1.0, rank_ic_mean=-0.02, sample_t=0.0,
        ))
    return reg, mgr, f.version


def test_capacity_advisory_in_monitor_never_changes_transition(tmp_path):
    """**M-AUTHORITY**：monitor_tick 的 capacity 只读附证**绝不**改硬转移——给一个「容量极大、看着健康」的
    CapacityEstimate 也救不回必退役的因子。种坏：capacity 被接成退役触发器→转移被改→RED。"""
    # 不带 capacity：必退役
    reg_a, mgr_a, v_a = _warning_factor(tmp_path / "a")
    act_a = monitor_tick(mgr_a, "w", v_a)
    assert act_a.lifecycle_event is not None and act_a.lifecycle_event.to_state == "RETIRED"
    assert act_a.capacity_advisory is None
    # 带「健康大容量」capacity 附证：转移**完全相同**（附证不改判），且附证被携带
    reg_b, mgr_b, v_b = _warning_factor(tmp_path / "b")
    healthy = strategy_capacity(0.01, 0.05, 1e9, 0.01, impact_coef=0.1)   # 大容量 ok
    act_b = monitor_tick(mgr_b, "w", v_b, capacity_estimate=healthy)
    assert act_b.lifecycle_event is not None and act_b.lifecycle_event.to_state == "RETIRED", \
        "capacity 附证竟改了硬转移（capacity 被误接成退役权威=M-AUTHORITY 破）"
    assert act_b.capacity_advisory is healthy                              # 只读携带供呈现


# ===========================================================================
# ③ 非 island：independent_bets 真接进 portfolio.gate 业务工具（descriptor·不改 verdict）
# ===========================================================================


def test_independent_bets_wired_into_portfolio_gate_tool():
    """③ 真接进**活的非禁区**生产路径：agent `portfolio.gate` 工具返回 independent_bets descriptor
    （组合成分去重族数），且**不改** gate verdict（只读 descriptor、不喂 honest_n）。"""
    from app.agent.agent_runtime import AgentRuntime
    from app.agent.business_tools import register_business_tools

    rt = AgentRuntime(object(), permission_mode="auto")
    register_business_tools(rt, hypothesis_store=None, factor_registry=None, model_registry=None)
    n = 300
    rng = np.random.default_rng(1)
    a = rng.standard_normal(n)
    ar = {
        "A": list(a),
        "B": list(0.99 * a + 1e-6 * rng.standard_normal(n)),       # 与 A 同族
        "C": list(rng.standard_normal(n)),                          # 独立
    }
    out = rt._tools["portfolio.gate"](
        "portfolio.gate",
        {"portfolio_id": "p1", "weights": {"A": 0.4, "B": 0.3, "C": 0.3}, "asset_returns": ar, "markets": ["crypto"]},
    )
    assert out.get("error") is None, out
    ib = out.get("independent_bets")
    assert ib is not None and ib["point"] == 2 and ib["n_held"] == 3, f"A/B 同族应坍缩→2 独立 bet：{ib}"
    assert "disclaimer" in ib
    assert "color" in out and "honest_n" in out                     # verdict 仍在、未被 descriptor 改写
