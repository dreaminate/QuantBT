"""M · 监控→自动降级/退役/问责 尾部闭环（D-WAVE1A · M-AUTHORITY=A1）。

把齐全但零生产调用方的构件接成闭环：周期 tick → 喂**绩效/成本漂移**观测 → 由 factor lifecycle
**权威**（`LifecycleManager`，A1）评估迁移 → 自动 WARNING/RETIRED + 发**单一** PROV（`LifecycleEvent`）。
退役/降级的权威状态机 = `registry.LifecycleState`（A1）；`hypothesis store.card.status` 作派生视图、
不双发 PROV。

**范畴红线（方法学 voice）**：退役动作矩阵输入只接**绩效/成本漂移**信号（IC / drift_pct），
**绝不接 C 的 gate verdict**（DSR/PBO 是晋级期过拟合闸，接成运营退役触发器 = 范畴错误）。
本模块签名里没有、也绝不加 gate verdict 参数。

croniter 硬化：生产 `Scheduler(strict=True)`（见 dag/engine.py）缺 croniter 启动响亮失败，
绝不让「监控驱动动作」沦为静默不 tick 的 paper-true。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from ..factor_factory.lifecycle import FactorObservation, LifecycleEvent, LifecycleManager

# 成本漂移降级阈值（与 cost_drift.py 的 0.30 告警阈同口径）。
DRIFT_DEGRADE_THRESHOLD = 0.30


@dataclass
class MonitorAction:
    """一次监控闭环的结果（含问责 PROV）。"""

    factor_id: str
    version: int
    drift_pct: float | None
    drift_breach: bool
    alert: str | None                       # 漂移超阈结构化告警（非仅 notes）
    lifecycle_event: LifecycleEvent | None  # A1 权威单一 PROV；None=本次无迁移


def _drift_degrade_observation(factor_id: str, version: int, drift_pct: float) -> FactorObservation:
    """漂移超阈 → 一条**绩效退化观测**（绩效/成本轴；绝不是 gate verdict）。

    用负 IC 表达「该因子的运营绩效在退化」，喂给 lifecycle 权威驱动 WARNING/RETIRED。
    """

    mag = abs(drift_pct)
    return FactorObservation(
        factor_id=factor_id,
        version=version,
        observed_at_utc=datetime.now(UTC).isoformat(),
        horizon=0,
        ic_mean=-mag,
        ic_ir=-1.0,
        rank_ic_mean=-mag,
        sample_t=0.0,
        extra={"source": "cost_drift", "drift_pct": drift_pct},
    )


def monitor_tick(
    manager: LifecycleManager,
    factor_id: str,
    version: int,
    *,
    observation: FactorObservation | None = None,
    drift_pct: float | None = None,
    drift_threshold: float = DRIFT_DEGRADE_THRESHOLD,
) -> MonitorAction:
    """一次监控闭环：记绩效观测/漂移信号 → lifecycle 权威评估迁移 → 返回动作 + 单一 PROV。

    `observation`=周期 IC/绩效观测；`drift_pct`=本周成本漂移（来自 `cost_drift.compute_weekly_cost_drift`）。
    漂移超阈 → 发结构化告警 + 记一条降级观测（**动作真被调用，非仅 append note**）。
    迁移与 PROV 由 `manager.evaluate`（A1 权威）单发，绝不在别处重复发。
    """

    breach = drift_pct is not None and abs(drift_pct) > drift_threshold
    if observation is not None:
        manager.record_observation(observation)
    alert: str | None = None
    if breach:
        alert = f"⚠️ 成本漂移 {drift_pct:.0%} 超阈 {drift_threshold:.0%} → 触发降级评估（问责落 PROV）"
        manager.record_observation(_drift_degrade_observation(factor_id, version, float(drift_pct)))
    event = manager.evaluate(factor_id, version)
    return MonitorAction(
        factor_id=factor_id,
        version=version,
        drift_pct=drift_pct,
        drift_breach=breach,
        alert=alert,
        lifecycle_event=event,
    )


__all__ = ["DRIFT_DEGRADE_THRESHOLD", "MonitorAction", "monitor_tick"]
