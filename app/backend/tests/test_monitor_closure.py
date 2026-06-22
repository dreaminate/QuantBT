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
