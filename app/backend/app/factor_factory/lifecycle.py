"""M11 · 因子五态机生命周期。

来自 QuantBT-GOAL.md §M11：

    NEW   →  QUALIFIED  →  PROBATION  →  OBSERVATION  →  WARNING  →  RETIRED

自动迁移示例阈值（全部参数化，可在 settings 调整）：
- NEW → QUALIFIED：|IC| > 0.03 且 IR > 0.5 且 sample_t > 3
- QUALIFIED → PROBATION：连续 3 个月 IC 不为负（quarter_ic_min > 0）
- PROBATION → OBSERVATION：模拟实盘 1 个月年化 > 基准
- OBSERVATION → WARNING：30 天 IC 衰减 > 50%
- WARNING → RETIRED：连续 2 周 WARNING 不能修复

每次评估都会写入 `lifecycle_event_log`，便于审计追溯。
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from typing import Any, Literal

from .lifecycle_metrics import DecayEstimate, ic_decay_half_life
from .registry import Factor, FactorRegistry, LifecycleState


@dataclass
class LifecycleThresholds:
    abs_ic_qualify: float = 0.03
    ir_qualify: float = 0.5
    t_qualify: float = 3.0
    quarter_ic_min: float = 0.0
    probation_min_months: int = 3
    paper_excess_return: float = 0.0
    observation_ic_decay_pct: float = 0.5
    warning_persist_weeks: int = 2


@dataclass
class FactorObservation:
    """周期性观测：通常一周或一月一次。"""

    factor_id: str
    version: int
    observed_at_utc: str
    horizon: int
    ic_mean: float
    ic_ir: float
    rank_ic_mean: float
    sample_t: float
    paper_excess_return: float | None = None
    extra: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class LifecycleEvent:
    factor_id: str
    version: int
    from_state: LifecycleState
    to_state: LifecycleState
    happened_at_utc: str
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


TransitionOutcome = Literal["promote", "demote", "stay"]


def evaluate_transition(
    factor: Factor,
    history: list[FactorObservation],
    *,
    thresholds: LifecycleThresholds | None = None,
) -> LifecycleState:
    """根据观测历史决定下一个状态。

    简化规则；真实生产可换成更细的 hysteresis 策略（每步降级要看连续多次低于阈值）。
    """

    th = thresholds or LifecycleThresholds()
    if not history:
        return factor.lifecycle_state
    last = history[-1]
    state = factor.lifecycle_state
    if state == "NEW":
        if abs(last.ic_mean) >= th.abs_ic_qualify and last.ic_ir >= th.ir_qualify and last.sample_t >= th.t_qualify:
            return "QUALIFIED"
        return "NEW"
    if state == "QUALIFIED":
        recent = history[-th.probation_min_months :]
        if len(recent) >= th.probation_min_months and all(o.ic_mean >= th.quarter_ic_min for o in recent):
            return "PROBATION"
        return state
    if state == "PROBATION":
        if last.paper_excess_return is not None and last.paper_excess_return > th.paper_excess_return:
            return "OBSERVATION"
        return state
    if state == "OBSERVATION":
        # 30 天 IC 衰减 50%：用历史 30 期均值对比最近一期
        if len(history) >= 30:
            prev = history[-30:-1]
            prev_mean = sum(o.ic_mean for o in prev) / max(len(prev), 1)
            if prev_mean > 0 and last.ic_mean < prev_mean * (1 - th.observation_ic_decay_pct):
                return "WARNING"
        return state
    if state == "WARNING":
        recent = history[-th.warning_persist_weeks :]
        if len(recent) >= th.warning_persist_weeks and all(o.ic_mean < 0 for o in recent):
            return "RETIRED"
        if last.ic_mean >= th.abs_ic_qualify:
            return "OBSERVATION"
        return state
    if state == "RETIRED":
        return state
    return state


class LifecycleManager:
    """把状态迁移与 FactorRegistry 绑定，记录事件日志。"""

    def __init__(self, registry: FactorRegistry, thresholds: LifecycleThresholds | None = None) -> None:
        self._registry = registry
        self._thresholds = thresholds or LifecycleThresholds()
        self._observations: dict[tuple[str, int], list[FactorObservation]] = {}
        self._events: list[LifecycleEvent] = []

    @property
    def thresholds(self) -> LifecycleThresholds:
        return self._thresholds

    def record_observation(self, observation: FactorObservation) -> None:
        key = (observation.factor_id, observation.version)
        self._observations.setdefault(key, []).append(observation)

    def history(self, factor_id: str, version: int) -> list[FactorObservation]:
        return list(self._observations.get((factor_id, version), []))

    def events(self, factor_id: str | None = None) -> list[LifecycleEvent]:
        if factor_id is None:
            return list(self._events)
        return [e for e in self._events if e.factor_id == factor_id]

    def decay_diagnostic(self, factor_id: str, version: int, *, min_periods: int = 30) -> DecayEstimate | None:
        """因子 IC 持久性 AR(1) 半衰期诊断（**perf 轴·advisory**）——复用 `lifecycle_metrics` 单一源。

        h=ln(0.5)/ln(ρ)，ρ=AR(1) 持久系数（见 lifecycle_metrics 与 finding 推导）。**绝不作硬退役依据**
        （slice-4 自律 + 用户方法学护栏）：near-unit-root 弱识别→status='unstable'，随机游走/反转/样本不足
        如实标 unstable/reversal/insufficient，仅供人工/UI/监控自判；**不进 `evaluate_transition` 的硬转移**。
        无观测历史 → None。纯 perf 轴（只读 IC 观测，绝不碰 DSR/PBO gate verdict——M-AUTHORITY 风格）。
        """
        history = self.history(factor_id, version)
        if not history:
            return None
        return ic_decay_half_life([o.ic_mean for o in history], min_periods=min_periods)

    def evaluate(self, factor_id: str, version: int) -> LifecycleEvent | None:
        factor = self._registry.get(factor_id, version)
        history = self.history(factor_id, version)
        # 硬转移**独立**由 evaluate_transition 决定（只吃 perf 轴 IC 观测）；decay 仅作 advisory 注解、绝不改判。
        next_state = evaluate_transition(factor, history, thresholds=self._thresholds)
        if next_state == factor.lifecycle_state:
            return None
        decay = self.decay_diagnostic(factor_id, version)
        if decay is None:
            decay_note = ""
        elif decay.status == "ok":
            decay_note = f"；IC 持久性 h={decay.half_life:.1f}期/ρ={decay.rho:.3f}（advisory·不作硬退役依据）"
        else:
            decay_note = f"；IC 持久性诊断={decay.status}（advisory·不作硬退役依据）"
        event = LifecycleEvent(
            factor_id=factor_id,
            version=version,
            from_state=factor.lifecycle_state,
            to_state=next_state,
            happened_at_utc=datetime.now(UTC).isoformat(),
            reason=f"自动迁移：观测 {len(history)} 期{decay_note}",
        )
        self._registry.update_state(factor_id, version, next_state)
        self._events.append(event)
        return event


__all__ = [
    "FactorObservation",
    "LifecycleEvent",
    "LifecycleManager",
    "LifecycleThresholds",
    "TransitionOutcome",
    "evaluate_transition",
]
