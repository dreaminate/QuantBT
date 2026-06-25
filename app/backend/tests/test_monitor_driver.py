"""监控调度 driver 接线对抗测试（修复 cron 永不 fire 的端到端假绿灯）。

背景：`_start_production_monitor_scheduler` 只**注册** weekly DAG，`Scheduler.tick()` 是轮询式
（docstring 明载「调用方在 loop 里 every N seconds 调 tick()」）；此前生产**无任何 driver** 去 tick
→ cron=0 9 * * 1 永不到点 fire、退役闭环空转，而 log 称「已启动」=假绿灯。本组测试钉住「生产真有
driver 在 tick」，断 driver 即红。

门必抓：
- driver 真 tick：起 driver(tiny interval) + 装一个已到期 job → 有界等待内必 fire（证 driver 在跑 tick）。
- startup 真接 driver：`startup_event()` 后 driver 线程必活（MUT：startup 不调 `_start_monitor_driver` → 红）。
- env 关生效：QUANTBT_MONITOR_DRIVER=0 → 不起 driver（不替用户拍「是否自动跑」松紧）。
- 幂等：多次 startup 不重复起线程（多 TestClient 不泄漏线程）。
"""

from __future__ import annotations

import time
from datetime import UTC, datetime

import pytest

from app import main
from app.dag.engine import DAGDefinition, DAGTask, Scheduler, register_op

_FIRED: list[datetime] = []


@register_op("test_monitor_driver_probe", version="v1")
def _probe_op(*, context: dict | None = None) -> dict:
    """探针 op：被 driver 经 tick→run_dag 触发时留痕（证 driver 真把到期 job 跑出去）。"""
    _FIRED.append(datetime.now(UTC))
    return {"fired": True}


def _expired_scheduler() -> Scheduler:
    """装一个含『已到期』job 的 scheduler（强制到期写法 mirror test_monitor_closure.py:187）。"""
    sched = Scheduler(strict=False)
    if sched._croniter is None:  # noqa: SLF001  croniter 缺则跳过（与既有测试同口径）
        pytest.skip("croniter 缺，无法测调度 tick")
    defn = DAGDefinition(
        name="test_monitor_driver_dag", schedule="0 9 * * 1",
        tasks=[DAGTask(id="probe", op="test_monitor_driver_probe", kind="pure")],
    )
    sched.add(defn)
    sched._jobs["test_monitor_driver_dag"] = (defn, datetime(2000, 1, 1, tzinfo=UTC))  # noqa: SLF001  强制到期
    return sched


def test_monitor_driver_ticks_due_job_within_bound(monkeypatch):
    """**核心牙**：driver 起来后真周期 tick → 已到期 job 在有界时间内 fire。

    MUT：若 `_monitor_driver_loop` 不调 `sched.tick()`（如被改成 pass）→ job 永不 fire → 本测超时红。
    """
    _FIRED.clear()
    sched = _expired_scheduler()
    monkeypatch.setattr(main, "PRODUCTION_SCHEDULER", sched)
    monkeypatch.setenv("QUANTBT_MONITOR_DRIVER", "1")
    monkeypatch.setenv("QUANTBT_MONITOR_TICK_SECONDS", "0.02")
    main.stop_monitor_driver()  # 清旧
    try:
        thread = main._start_monitor_driver()
        assert thread is not None and thread.is_alive(), "driver 没起来"
        deadline = time.time() + 3.0
        while not _FIRED and time.time() < deadline:
            time.sleep(0.02)
        assert _FIRED, "driver 起了却没 tick 到期 job（driver 没真 tick = cron 永不 fire 的假绿灯复发）"
    finally:
        main.stop_monitor_driver()


def test_startup_event_launches_live_monitor_driver(monkeypatch):
    """**接线牙**：`startup_event()` 真把 driver 起活（MUT：startup 删 `_start_monitor_driver()` → 红）。"""
    monkeypatch.setenv("QUANTBT_MONITOR_DRIVER", "1")
    monkeypatch.setenv("QUANTBT_MONITOR_TICK_SECONDS", "60")  # 慢周期：startup 自带的 weekly scheduler 不会误触发
    main.stop_monitor_driver()
    try:
        main.startup_event()
        thread = main._MONITOR_DRIVER_THREAD
        assert thread is not None and thread.is_alive(), \
            "startup 没起活的监控 driver → 注册的 weekly cron 永不 fire（端到端假绿灯）"
    finally:
        main.stop_monitor_driver()


def test_monitor_driver_env_off_disables(monkeypatch):
    """env 关生效（不替用户拍『是否自动跑』）：QUANTBT_MONITOR_DRIVER=0 → 不起 driver、返 None。"""
    monkeypatch.setenv("QUANTBT_MONITOR_DRIVER", "0")
    main.stop_monitor_driver()
    try:
        assert main._start_monitor_driver() is None
        assert main._MONITOR_DRIVER_THREAD is None or not main._MONITOR_DRIVER_THREAD.is_alive()
    finally:
        main.stop_monitor_driver()


def test_monitor_driver_idempotent(monkeypatch):
    """幂等：多次起 driver 复用同一线程（多 TestClient startup 不泄漏多线程）。"""
    monkeypatch.setenv("QUANTBT_MONITOR_DRIVER", "1")
    monkeypatch.setenv("QUANTBT_MONITOR_TICK_SECONDS", "60")
    main.stop_monitor_driver()
    try:
        t1 = main._start_monitor_driver()
        t2 = main._start_monitor_driver()
        assert t1 is not None and t1 is t2, "重复 startup 起了第二条 driver 线程（非幂等）"
    finally:
        main.stop_monitor_driver()
