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
from ..factor_factory.lifecycle_metrics import CapacityEstimate
from .drift import PerfDriftSignal

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
    perf_drift_breach: bool = False         # 绩效轴统计漂移(rolling-PSR/CUSUM/PH)是否 breach
    perf_drift_detector: str | None = None  # 触发的绩效轴检测器名
    capacity_advisory: CapacityEstimate | None = None  # ② 容量**只读附证**（advisory）：绝不驱动退役、
    #                                                     绝非 degrade 观测——仅供监控/UI 呈现容量上下文


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
    perf_drift: PerfDriftSignal | None = None,
    capacity_estimate: CapacityEstimate | None = None,
) -> MonitorAction:
    """一次监控闭环：记绩效观测/漂移信号 → lifecycle 权威评估迁移 → 返回动作 + 单一 PROV。

    `observation`=周期 IC/绩效观测；`drift_pct`=本周成本漂移（来自 `cost_drift.compute_weekly_cost_drift`）；
    `perf_drift`=**绩效轴**统计漂移检测器输出（rolling-PSR/CUSUM/Page-Hinkley，见 `drift.py`）。
    漂移超阈 → 发结构化告警 + 记一条降级观测（**动作真被调用，非仅 append note**）。
    迁移与 PROV 由 `manager.evaluate`（A1 权威）单发，绝不在别处重复发。

    **范畴红线（M-AUTHORITY=A1）**：本入参只收**绩效/成本轴**——`PerfDriftSignal`（axis=performance）
    与 cost `drift_pct`。**绝不接** C 的 gate verdict（DSR/PBO 晋级闸）、**绝不接**特征轴 PSI
    （`FeatureDriftDiagnosis` 是不同类型、无 breach、类型层即被拒）。运行期再设防伪一道。

    **证据合并语义**：成本轴 breach 与绩效轴 breach **各记一条**降级观测——同一 tick 同时超阈
    可贡献 2 条负观测（多轴独立证据叠加，由 lifecycle 权威按其连续期规则裁决，非本函数去重）。

    **`capacity_estimate`（②·只读附证）**：可选；给定则**纯附着**到 `MonitorAction.capacity_advisory` 供
    监控/UI 呈现，**绝不**喂观测、**绝不**影响迁移（capacity ≠ 绩效/成本轴、绝非退役触发器；硬上限由
    `portfolio.capacity_sizing` 单独管，不在监控侧动作）。默认 None = 零行为变化、与历史逐位一致。
    """

    breach = drift_pct is not None and abs(drift_pct) > drift_threshold
    if observation is not None:
        manager.record_observation(observation)
    alert: str | None = None
    if breach:
        alert = f"⚠️ 成本漂移 {drift_pct:.0%} 超阈 {drift_threshold:.0%} → 触发降级评估（问责落 PROV）"
        manager.record_observation(_drift_degrade_observation(factor_id, version, float(drift_pct)))

    perf_drift_breach = False
    perf_drift_detector: str | None = None
    if perf_drift is not None:
        # 防伪：只认绩效轴信号（FeatureDriftDiagnosis 无 axis=="performance"、亦无 to_lifecycle_observation）。
        if getattr(perf_drift, "axis", None) != "performance":
            raise TypeError(
                "monitor_tick 只接绩效/成本轴信号；特征轴漂移(PSI)仅根因诊断、绝不驱动退役"
                "（M-AUTHORITY=A1 范畴红线）"
            )
        if perf_drift.breach:
            perf_drift_breach = True
            perf_drift_detector = perf_drift.detector
            alert = (alert + " · " if alert else "") + (
                f"⚠️ 绩效轴漂移 {perf_drift.detector} 越阈"
                f"（stat={perf_drift.statistic:.3g} vs {perf_drift.threshold:.3g}）→ 触发降级评估"
            )
            manager.record_observation(perf_drift.to_lifecycle_observation(factor_id, version))

    event = manager.evaluate(factor_id, version)
    # ② 容量**只读附证**：在权威 evaluate() **之后**纯附着到输出，**绝不**记成观测、**绝不**进退役评估
    #    （capacity 驱动退役 = 范畴错误，同 decay 只 advisory 不硬退役的纪律）。仅供监控/UI 呈现容量上下文。
    return MonitorAction(
        factor_id=factor_id,
        version=version,
        drift_pct=drift_pct,
        drift_breach=breach,
        alert=alert,
        lifecycle_event=event,
        perf_drift_breach=perf_drift_breach,
        perf_drift_detector=perf_drift_detector,
        capacity_advisory=capacity_estimate,
    )


__all__ = ["DRIFT_DEGRADE_THRESHOLD", "MonitorAction", "monitor_tick"]
