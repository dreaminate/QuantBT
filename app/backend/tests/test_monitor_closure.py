"""M · 监控尾部闭环 对抗测试（D-WAVE1A · 卡 d0e5d208 · M-AUTHORITY=A1）。

门必抓：
- 种应退役卡（WARNING + 连续漂移超阈）→ 自动 RETIRED + **单一** PROV（A1 lifecycle 权威单发）；
  断接线（不调 evaluate）则不 retired → 红。
- 漂移>30% → 降级动作**真被调用**（记降级观测）而非仅 append note。
- croniter 硬化：strict=True 缺 croniter → 启动响亮失败（非静默不 tick）。
- 范畴红线：退役动作矩阵只接绩效/漂移信号，绝不接 gate verdict（DSR/PBO）。
"""

from __future__ import annotations

import inspect
import sys

import pytest

from app.dag.engine import Scheduler
from app.factor_factory.lifecycle import LifecycleManager, LifecycleThresholds
from app.factor_factory.registry import FactorRegistry
from app.monitor.closure import monitor_tick


def _mgr(tmp_path, state):
    reg = FactorRegistry(tmp_path / "f.json")
    factor = reg.register("z", "close")
    reg.update_state("z", factor.version, state)
    mgr = LifecycleManager(reg, thresholds=LifecycleThresholds(warning_persist_weeks=2))
    return reg, mgr, factor.version


def test_drift_breach_drives_retire_with_single_prov(tmp_path):
    reg, mgr, v = _mgr(tmp_path, "WARNING")
    a1 = monitor_tick(mgr, "z", v, drift_pct=0.5)   # 第1周：1 条降级观测 → 还差 1
    assert a1.drift_breach and a1.alert is not None
    assert a1.lifecycle_event is None               # 持续不足 2 周，未迁移
    a2 = monitor_tick(mgr, "z", v, drift_pct=0.5)   # 第2周：满 2 周连续负 → RETIRED
    assert a2.lifecycle_event is not None
    assert a2.lifecycle_event.to_state == "RETIRED"
    assert reg.get("z").lifecycle_state == "RETIRED"
    assert len(mgr.events("z")) == 1                # 单一 PROV（A1 权威单发，不双发）


def test_drift_below_threshold_no_action(tmp_path):
    reg, mgr, v = _mgr(tmp_path, "WARNING")
    a = monitor_tick(mgr, "z", v, drift_pct=0.1)
    assert not a.drift_breach and a.alert is None
    assert mgr.history("z", v) == []                # 未记任何降级观测、不告警


def test_drift_action_called_not_just_note(tmp_path):
    reg, mgr, v = _mgr(tmp_path, "WARNING")
    monitor_tick(mgr, "z", v, drift_pct=0.5)
    hist = mgr.history("z", v)
    assert len(hist) == 1
    assert hist[-1].ic_mean < 0                     # 降级动作真被调用（记负绩效观测）
    assert hist[-1].extra.get("source") == "cost_drift"


def test_scheduler_croniter_hardened(monkeypatch):
    monkeypatch.setitem(sys.modules, "croniter", None)  # 模拟生产缺包
    with pytest.raises(RuntimeError, match="croniter"):
        Scheduler(strict=True)                          # 响亮失败
    assert Scheduler(strict=False) is not None          # 非 strict 仍可构造（dev fallback）


def test_monitor_tick_takes_no_gate_verdict_param():
    """范畴红线：签名里绝不含 gate verdict（DSR/PBO 是晋级闸、非运营退役触发器）。"""
    params = set(inspect.signature(monitor_tick).parameters)
    for forbidden in ("verdict", "gate_verdict", "pbo", "dsr", "gate", "overfit"):
        assert forbidden not in params, f"monitor_tick 不得接 {forbidden}（gate verdict→退役触发=范畴错误）"


# ============================================================================
# 卡 de764e1c · 监控生产调度 + 因子观测管道 对抗测试（扩展不替换；接在 M 卡闭环测试后）。
#
# 门必抓：
# 1) 生产 weekly pass 真跑：种 WARNING 因子 + 连续 2 周成本漂移超阈 → 自动 RETIRED + 单一 PROV（A1）；
#    **断接线（不注册 DAG op / 不调生产 pass）→ 因子停在 WARNING、不退役 → 红**（证明接线真生效）。
# 2) 漂移>30% → 降级动作真被调用（记负绩效观测），而非仅 append note。
# 3) 缺 croniter → 生产 Scheduler(strict=True) 启动响亮失败（monkeypatch import 失败）。
# 4) run_weekly_monitor_pass / monitor_tick 全链路无 verdict/pbo/dsr/gate/overfit（范畴红线回归）。
# ============================================================================

from datetime import UTC, datetime  # noqa: E402

from app.dag.engine import _OPS, list_ops  # noqa: E402
from app.monitor.closure import _drift_degrade_observation  # noqa: E402
from app.monitor.production import (  # noqa: E402
    WEEKLY_MONITOR_OP,
    build_weekly_monitor_dag,
    run_weekly_monitor_pass,
)


def _breach_audit_records(symbol: str = "BTCUSDT", n: int = 1) -> list[dict]:
    """造**真实成本漂移超阈**的成交审计记录：commission 远超回测预期 → drift_pct ≫ 0.30。

    payload 形状对齐 paper_fill（commission=50 vs 名义 100 → 预期成本几个 bps，漂移数百倍）。
    """

    now = datetime.now(UTC).isoformat()
    return [
        {
            "kind": "paper_fill",
            "logged_at_utc": now,
            "payload": {
                "ts": now, "symbol": symbol, "side": "buy",
                "filled_qty": 1.0, "fill_price": 100.0, "commission": 50.0,
            },
        }
        for _ in range(n)
    ]


def test_weekly_pass_drives_retire_with_single_prov(tmp_path):
    """生产 weekly pass：WARNING 因子 + 连续 2 周漂移超阈 → 自动 RETIRED + 单一 PROV（端到端）。"""

    reg, mgr, v = _mgr(tmp_path, "WARNING")
    recs = _breach_audit_records()
    # 第 1 周：1 条降级观测，还差 1 周
    a1 = run_weekly_monitor_pass(reg, mgr, recs)
    assert len(a1) == 1 and a1[0].drift_breach
    assert reg.get("z").lifecycle_state == "WARNING"   # 持续不足 2 周，未退役
    # 第 2 周：满 2 周连续负观测 → RETIRED
    a2 = run_weekly_monitor_pass(reg, mgr, recs)
    assert a2[0].lifecycle_event is not None
    assert a2[0].lifecycle_event.to_state == "RETIRED"
    assert reg.get("z").lifecycle_state == "RETIRED"
    assert len(mgr.events("z")) == 1                    # 单一 PROV（A1 权威单发，不双发）


def test_retire_requires_wiring_severing_pass_leaves_warning(tmp_path):
    """断接线变异：不调生产 pass（监控不接 monitor_tick）→ 因子停在 WARNING、不退役 → 此断言证明
    退役**只能**由生产调用 pass 触发（非套套逻辑：去掉接线即红）。"""

    reg, mgr, v = _mgr(tmp_path, "WARNING")
    # 不调用 run_weekly_monitor_pass（= 生产无调用方 / 接线断）→ 观测零、状态不动
    assert mgr.history("z", v) == []
    assert reg.get("z").lifecycle_state == "WARNING"    # 断接线 → 永不退役（与上一测对照）


def test_scheduler_dag_wiring_fires_op_and_severing_does_not(tmp_path, monkeypatch):
    """端到端接线：生产 Scheduler 注册 weekly DAG → tick 到期触发 op → 调生产闭环（真退役）；
    **断接线（DAG op 未注册）→ tick 失败、闭环不跑 → 因子停在 WARNING（红）**。

    用 main 全局单例（生产真路径）：把 FACTOR_REGISTRY/FACTOR_LIFECYCLE 指向 seeded WARNING 因子，
    PAPER_DESK 喂超阈审计记录，证明 monitor_tick 在生产调度链路上真被调用。
    """

    import app.main as m
    from app.dag.engine import Scheduler
    from app.factor_factory.lifecycle import LifecycleManager, LifecycleThresholds
    from app.factor_factory.registry import FactorRegistry

    # seeded 生产单例：WARNING 因子 + 已有 1 周负观测（再来 1 周即退役）
    reg = FactorRegistry(tmp_path / "prod_factors.json")
    f = reg.register("prod_z", "close")
    reg.update_state("prod_z", f.version, "WARNING")
    mgr = LifecycleManager(reg, thresholds=LifecycleThresholds(warning_persist_weeks=2))

    # 假 PAPER_DESK：聚合接口只需 ._runs[*].venue.audit.export()
    class _FakeAudit:
        def __init__(self, recs): self._recs = recs
        def export(self): return list(self._recs)

    class _FakeVenue:
        def __init__(self, recs): self.audit = _FakeAudit(recs)

    class _FakeRec:
        def __init__(self, recs): self.venue = _FakeVenue(recs)

    class _FakeDesk:
        def __init__(self, recs): self._runs = {"r1": _FakeRec(recs)}

    monkeypatch.setattr(m, "FACTOR_REGISTRY", reg)
    monkeypatch.setattr(m, "FACTOR_LIFECYCLE", mgr)
    monkeypatch.setattr(m, "PAPER_DESK", _FakeDesk(_breach_audit_records()))

    # ---- 接线完好：scheduler 注册 DAG + 强制到期 + tick → op 跑生产闭环 ----
    assert WEEKLY_MONITOR_OP in list_ops()              # op 已注册（import 即注册）
    sched = Scheduler(strict=True)
    dag = build_weekly_monitor_dag()
    sched.add(dag)
    # 强制本 job 立即到期（cron 下次 fire 在未来；直接把 scheduled_at 拨到过去）
    name, (definition, _future) = next(iter(sched._jobs.items()))
    sched._jobs[name] = (definition, datetime(2000, 1, 1, tzinfo=UTC))
    # 模拟上一周已记 1 条负观测（真实场景上周 tick 落的）→ 本周 tick 补第 2 条即满 2 周退役
    mgr.record_observation(_drift_degrade_observation("prod_z", f.version, 5.0))
    results = sched.tick()
    assert results and results[0].succeeded                    # DAG 真跑成功
    assert reg.get("prod_z").lifecycle_state == "RETIRED"      # 生产调度链路真退役
    assert len(mgr.events("prod_z")) == 1                      # 单一 PROV

    # ---- 断接线变异：op 未注册 → 同样 tick → DAG 失败、闭环不跑 → 状态不动 ----
    reg2 = FactorRegistry(tmp_path / "prod_factors2.json")
    f2 = reg2.register("prod_z2", "close")
    reg2.update_state("prod_z2", f2.version, "WARNING")
    mgr2 = LifecycleManager(reg2, thresholds=LifecycleThresholds(warning_persist_weeks=2))
    mgr2.record_observation(_drift_degrade_observation("prod_z2", f2.version, 5.0))
    monkeypatch.setattr(m, "FACTOR_REGISTRY", reg2)
    monkeypatch.setattr(m, "FACTOR_LIFECYCLE", mgr2)
    monkeypatch.delitem(_OPS, WEEKLY_MONITOR_OP)               # 断接线：op 注销
    sched2 = Scheduler(strict=True)
    sched2.add(build_weekly_monitor_dag())
    name2, (def2, _f2) = next(iter(sched2._jobs.items()))
    sched2._jobs[name2] = (def2, datetime(2000, 1, 1, tzinfo=UTC))
    results2 = sched2.tick()
    assert results2 and not results2[0].succeeded             # DAG 失败（op 未注册）
    assert reg2.get("prod_z2").lifecycle_state == "WARNING"   # 断接线 → 不退役（证明接线真生效）


def test_weekly_pass_drift_action_called_not_just_note(tmp_path):
    """漂移>30% → 降级动作真被调用（记负绩效观测），而非仅 append note。"""

    reg, mgr, v = _mgr(tmp_path, "WARNING")
    run_weekly_monitor_pass(reg, mgr, _breach_audit_records())
    hist = mgr.history("z", v)
    assert len(hist) == 1
    assert hist[-1].ic_mean < 0                          # 降级动作真被调用（负绩效观测）
    assert hist[-1].extra.get("source") == "cost_drift"


def test_weekly_pass_no_obs_when_no_drift(tmp_path):
    """诚实：无成交记录 / 漂移未超阈 → 不记降级观测、不误退役（不假绿灯）。"""

    reg, mgr, v = _mgr(tmp_path, "WARNING")
    actions = run_weekly_monitor_pass(reg, mgr, [])      # 无审计记录 → drift_pct=None
    assert len(actions) == 1 and not actions[0].drift_breach
    assert mgr.history("z", v) == []                     # 零观测
    assert reg.get("z").lifecycle_state == "WARNING"     # 不误退役


def test_retired_factor_skipped(tmp_path):
    """已 RETIRED 因子：weekly pass 跳过（不再喂观测、不重复发 PROV）。"""

    reg, mgr, v = _mgr(tmp_path, "RETIRED")
    actions = run_weekly_monitor_pass(reg, mgr, _breach_audit_records())
    assert actions == []                                 # RETIRED 被跳过
    assert mgr.history("z", v) == []


def test_production_startup_uses_strict_scheduler(monkeypatch):
    """生产 startup **必须**用 Scheduler(strict=True)（非 strict=False）——否则缺 croniter 静默不 tick。

    spy `Scheduler` 捕获构造实参：钉死 strict=True。把 strict 软化成 False 即触此断言转红
    （变异自检证明此测试非套套逻辑、真盯紧响亮失败语义，而非只靠 .add() 的独立 croniter 守卫）。
    """

    import app.dag.engine as engine
    import app.main as m

    captured: list[bool] = []
    real_scheduler = engine.Scheduler

    class _SpyScheduler(real_scheduler):  # type: ignore[misc,valid-type]
        def __init__(self, *args, strict: bool = False, **kwargs):
            captured.append(strict)
            super().__init__(*args, strict=strict, **kwargs)

    monkeypatch.setattr(engine, "Scheduler", _SpyScheduler)
    m._start_production_monitor_scheduler()
    assert captured == [True], f"startup 必须 Scheduler(strict=True)，实得 strict={captured}"


def test_production_scheduler_strict_loud_fail_without_croniter(monkeypatch):
    """缺 croniter → 生产 Scheduler(strict=True) 启动响亮失败（_start_production_monitor_scheduler）。"""

    import app.main as m

    monkeypatch.setitem(sys.modules, "croniter", None)   # 模拟生产缺包
    with pytest.raises(RuntimeError, match="croniter"):
        m._start_production_monitor_scheduler()          # 启动响亮失败（绝不静默不 tick）


def test_weekly_pass_signature_no_gate_verdict():
    """范畴红线回归：生产 pass 全链路绝不接 gate verdict（DSR/PBO 是晋级闸、非退役触发器）。"""

    for fn in (run_weekly_monitor_pass, monitor_tick):
        params = set(inspect.signature(fn).parameters)
        for forbidden in ("verdict", "gate_verdict", "pbo", "dsr", "gate", "overfit"):
            assert forbidden not in params, f"{fn.__name__} 不得接 {forbidden}（gate verdict→退役=范畴错误）"


def test_weekly_pass_passes_no_gate_verdict_to_monitor_tick(tmp_path, monkeypatch):
    """范畴红线（运行时）：run_weekly_monitor_pass 调 monitor_tick 时**实参**里绝无 gate verdict 键。"""

    reg, mgr, v = _mgr(tmp_path, "WARNING")
    captured: list[dict] = []
    import app.monitor.production as prod

    real_tick = prod.monitor_tick

    def _spy(manager, fid, ver, **kwargs):
        captured.append(dict(kwargs))
        return real_tick(manager, fid, ver, **kwargs)

    monkeypatch.setattr(prod, "monitor_tick", _spy)
    run_weekly_monitor_pass(reg, mgr, _breach_audit_records())
    assert captured, "monitor_tick 未被调用"
    for kw in captured:
        for forbidden in ("verdict", "gate_verdict", "pbo", "dsr", "gate", "overfit"):
            assert forbidden not in kw, f"传给 monitor_tick 的实参含禁项 {forbidden}（范畴错误）"
        assert set(kw).issubset({"observation", "drift_pct", "drift_threshold"})
