"""生产编排：让 M 卡建的 `monitor.closure.monitor_tick` 闭环在生产真跑（卡 de764e1c）。

D-WAVE1A 残余②：M 卡（d0e5d208）建好了闭环机制（周期 tick → lifecycle 权威 A1 自动降级/退役
+ 单一 PROV）+ croniter 硬化，但**生产无调用方**——`record_observation` 在生产零调用、tick 空转。
本模块补三件事，使「监控驱动动作」在生产真生效：

1. **因子观测记录管道**：从各 paper run 的 `ExecutionAuditLog` 聚合成交记录 →
   `compute_weekly_cost_drift` 算本周成本漂移 → 对每个**活跃**（非 RETIRED）因子喂 `monitor_tick`，
   由 factor lifecycle 权威（A1）评估迁移 + 落单一 PROV。
2. **生产 weekly DAG 节点**（`build_weekly_monitor_dag`，cron 周一早 9 点）+ 注册 op
   `weekly_factor_monitor`，挂到 `main.py` 启动的 `Scheduler(strict=True)`。
3. **响亮失败**：缺 croniter → `Scheduler(strict=True)` 启动 raise（见 dag/engine.py），绝不静默不 tick。

**范畴红线（与 closure.py 同口径，M-AUTHORITY=A1）**：退役动作矩阵只接**绩效/成本漂移**信号
（IC / drift_pct）。本模块绝不向 `monitor_tick` 传 gate verdict / pbo / dsr / gate / overfit
（DSR/PBO 是晋级期过拟合闸，接成运营退役触发器 = 范畴错误）。

**诚实边界（🟡 未验证 ≠ ✅ 已验证）**：
- 生产当前**无真实的周期性 per-factor IC 源**：`Factor.ic_summary` 仅注册期写一次、生产无人按周重算
  （grep 实证：唯一写者 = `set_ic_summary`，仅测试喂）。故生产 `observation=None`——**绝不**把注册期
  陈旧 IC 伪装成「本周观测」（那是 paper-true 假绿灯）。真实周度 IC 重算管道 = 诚实残余，待 mint 新卡；
  本模块留 `ic_provider` 钩子，真源就绪即接。
- `compute_weekly_cost_drift` 产**单一全局** `drift_pct`（审计 payload 无 `factor_id`，无法按因子归因），
  故同一 drift 喂给所有活跃因子——一次成本模型失准会同时触发所有 WARNING 因子降级。按因子归因 = 诚实残余。
- `LifecycleManager._observations` 内存级、不落盘：WARNING→RETIRED 需连续 2 周负观测，若两周之间进程重启
  则观测历史清空、退役不触发。**本卡范畴 = 单调度进程生命周期内闭环**；跨重启观测持久化 = 诚实残余，待新卡。
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Iterable, Sequence
from dataclasses import asdict, dataclass, replace
from datetime import UTC, date, datetime
from typing import TYPE_CHECKING, Any

import numpy as np

from ..dag.engine import DAGDefinition, DAGTask, Scheduler, register_op
from ..execution.base import ExecutionAuditLog
from ..factor_factory.lifecycle import FactorObservation, LifecycleManager
from ..factor_factory.registry import Factor, FactorRegistry
from .closure import DRIFT_DEGRADE_THRESHOLD, MonitorAction, monitor_tick
from .cost_drift import compute_weekly_cost_drift
from .drift import (
    PSR_FLOOR_DEFAULT,
    PerfDriftSignal,
    cusum_drift,
    page_hinkley_drift,
    rolling_psr_drift,
)

if TYPE_CHECKING:  # 仅类型：避免运行期把 paper / polars 包拖进 import 链
    import polars as pl

    from ..paper.desk import PaperDeskService

logger = logging.getLogger(__name__)

# 生产 weekly 监控调度名 + cron（周一 09:00 UTC 跑上周漂移）。
WEEKLY_MONITOR_DAG_NAME = "weekly_factor_monitor"
WEEKLY_MONITOR_OP = "weekly_factor_monitor"
WEEKLY_MONITOR_CRON = "0 9 * * 1"
MONITOR_WEEKLY_OP = "monitor.weekly_tick"
MONITOR_WEEKLY_DAG_NAME = "monitor.weekly_factor_lifecycle"
MONITOR_WEEKLY_CRON = "0 6 * * 1"

# 活跃 = 仍在运营轨道、可被退役的状态（RETIRED 已退役、再喂无意义）。
_ACTIVE_STATES = ("NEW", "QUALIFIED", "PROBATION", "OBSERVATION", "WARNING")
ACTIVE_MONITOR_STATES = frozenset({"QUALIFIED", "PROBATION", "OBSERVATION", "WARNING"})
FORBIDDEN_OBSERVATION_KEYS = frozenset({"pbo", "dsr", "gate", "gate_verdict", "overfit_verdict"})

# ic_provider 契约：给 (factor_id, version) 返回**真实**周期 IC 观测，或 None（无真源时）。
ICProvider = Callable[[str, int], FactorObservation | None]

# perf_provider 契约（卡 554cdcf2 残余①）：给 (factor_id, version) 返回**绩效轴**漂移信号
# （rolling-PSR 主告警 / CUSUM·PH 确证，见 drift.py），或 None（无真实周期收益序列时）。
# 类型恒为 PerfDriftSignal（axis="performance"）——**绝不**返回 FeatureDriftDiagnosis（PSI 特征轴只根因，
# monitor_tick 类型层即拒）。无真源 → None（绝不伪造，诚实优先，与 ic_provider 同范式）。
PerfDriftProvider = Callable[[str, int], PerfDriftSignal | None]


@dataclass
class WeeklyMonitorResult:
    week_iso: str
    drift_pct: float | None
    n_fills: int
    factors_checked: int
    actions: list[dict[str, Any]]
    lifecycle_events: list[dict[str, Any]]
    cost_drift_report: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class MonitorRuntime:
    lifecycle_manager: LifecycleManager
    factor_registry: FactorRegistry
    execution_audit_log: ExecutionAuditLog
    observation_provider: Callable[[], Iterable[FactorObservation]] | None = None
    result_recorder: Callable[[WeeklyMonitorResult, dict[str, Any]], dict[str, Any]] | None = None


_RUNTIME: MonitorRuntime | None = None


def configure_monitor_runtime(
    *,
    lifecycle_manager: LifecycleManager,
    factor_registry: FactorRegistry,
    execution_audit_log: ExecutionAuditLog,
    observation_provider: Callable[[], Iterable[FactorObservation]] | None = None,
    result_recorder: Callable[[WeeklyMonitorResult, dict[str, Any]], dict[str, Any]] | None = None,
) -> MonitorRuntime:
    global _RUNTIME
    _RUNTIME = MonitorRuntime(
        lifecycle_manager=lifecycle_manager,
        factor_registry=factor_registry,
        execution_audit_log=execution_audit_log,
        observation_provider=observation_provider,
        result_recorder=result_recorder,
    )
    return _RUNTIME


def _number(value: Any, field: str) -> float:
    if isinstance(value, bool):
        raise ValueError(f"{field} must be a finite number")
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field} must be a finite number") from exc
    if number != number or number in {float("inf"), float("-inf")}:
        raise ValueError(f"{field} must be a finite number")
    return number


def observation_from_payload(payload: dict[str, Any], *, default_observed_at: str | None = None) -> FactorObservation:
    forbidden = FORBIDDEN_OBSERVATION_KEYS.intersection(payload)
    if forbidden:
        raise ValueError(f"factor observation must not contain gate/overfit fields: {sorted(forbidden)}")
    factor_id = str(payload.get("factor_id") or "").strip()
    if not factor_id:
        raise ValueError("factor_id is required")
    version = int(payload.get("version") or 1)
    observed_at = str(payload.get("observed_at_utc") or default_observed_at or datetime.now(UTC).isoformat())
    return FactorObservation(
        factor_id=factor_id,
        version=version,
        observed_at_utc=observed_at,
        horizon=int(payload.get("horizon") or 0),
        ic_mean=_number(payload.get("ic_mean"), "ic_mean"),
        ic_ir=_number(payload.get("ic_ir"), "ic_ir"),
        rank_ic_mean=_number(payload.get("rank_ic_mean"), "rank_ic_mean"),
        sample_t=_number(payload.get("sample_t"), "sample_t"),
        paper_excess_return=(
            _number(payload.get("paper_excess_return"), "paper_excess_return")
            if payload.get("paper_excess_return") is not None
            else None
        ),
        extra=payload.get("extra") if isinstance(payload.get("extra"), dict) else {},
    )


def _first_number(mapping: dict[str, Any], *keys: str) -> float | None:
    for key in keys:
        if key in mapping and mapping[key] is not None:
            return _number(mapping[key], key)
    return None


def observation_from_factor_ic_summary(factor: Factor, *, observed_at_utc: str) -> FactorObservation | None:
    summary = factor.ic_summary if isinstance(factor.ic_summary, dict) else None
    if not summary:
        return None
    ic_mean = _first_number(summary, "ic_mean", "mean_ic", "ic")
    ic_ir = _first_number(summary, "ic_ir", "icir", "information_coefficient_ir")
    rank_ic_mean = _first_number(summary, "rank_ic_mean", "rank_ic", "rank_mean_ic")
    sample_t = _first_number(summary, "sample_t", "t_stat", "t")
    if ic_mean is None or ic_ir is None or rank_ic_mean is None or sample_t is None:
        return None
    return FactorObservation(
        factor_id=factor.factor_id,
        version=factor.version,
        observed_at_utc=observed_at_utc,
        horizon=int(summary.get("horizon") or 0),
        ic_mean=ic_mean,
        ic_ir=ic_ir,
        rank_ic_mean=rank_ic_mean,
        sample_t=sample_t,
        paper_excess_return=(
            _number(summary.get("paper_excess_return"), "paper_excess_return")
            if summary.get("paper_excess_return") is not None
            else None
        ),
        extra={"source": "factor_registry.ic_summary"},
    )


def active_monitor_factors(registry: FactorRegistry) -> list[Factor]:
    return [factor for factor in registry.list() if str(factor.lifecycle_state).upper() in ACTIVE_MONITOR_STATES]


def observations_from_registry_ic_summary(
    registry: FactorRegistry, *, observed_at_utc: str | None = None
) -> list[FactorObservation]:
    observed_at = observed_at_utc or datetime.now(UTC).isoformat()
    observations: list[FactorObservation] = []
    for factor in active_monitor_factors(registry):
        observation = observation_from_factor_ic_summary(factor, observed_at_utc=observed_at)
        if observation is not None:
            observations.append(observation)
    return observations


def run_weekly_monitor_pass(
    registry: FactorRegistry,
    manager: LifecycleManager,
    audit_records: Iterable[dict[str, Any]],
    *,
    week: date | None = None,
    asset_class: str = "crypto_perp",
    ic_provider: ICProvider | None = None,
    perf_provider: PerfDriftProvider | None = None,
) -> list[MonitorAction]:
    """一次生产 weekly 监控扫描：成本漂移 + 周期观测 → 对每个活跃因子驱动 `monitor_tick`。

    这是**因子观测记录管道 + 生产闭环的唯一逻辑接缝**：闭环是否在生产真跑，取决于本函数是否被
    生产调度调用（见 `run_production_monitor_cycle` + `main.py` startup）。对抗测试「断接线」即
    不注册/不调用本路径 → 因子停在 WARNING、不退役（证明接线真生效，非套套逻辑）。

    诚实：`ic_provider=None` / `perf_provider=None`（生产默认）时**只**喂成本漂移信号（真实测得），
    绝不伪造 per-factor IC、绝不伪造绩效轴漂移。
    范畴红线（M-AUTHORITY=A1）：只向 `monitor_tick` 传**绩效/成本轴**——`observation`（周期 IC）、
    `drift_pct`（成本漂移）、`perf_drift`（rolling-PSR/CUSUM/PH 绩效轴信号）。**绝不**传 gate
    verdict（DSR/PBO 晋级闸）、**绝不**传特征轴 PSI（monitor_tick 类型层即拒）。

    残余①接线：`perf_provider` 是 4 个绩效轴 drift 检测器（rolling-PSR/CUSUM/PH）进入生产的**唯一接缝**
    ——此前 `run_weekly_monitor_pass` 从不传 `perf_drift`，三件套在生产从未求值。对抗测试「断接线」即
    不传 `perf_provider` → 绩效轴退役不触发（证明接线真生效，非套套逻辑）。
    """

    records = list(audit_records)
    report = compute_weekly_cost_drift(records, week=week, asset_class=asset_class)
    drift_pct = report.drift_pct  # 单一全局漂移（无 per-factor 归因，见模块诚实边界）

    actions: list[MonitorAction] = []
    for factor in registry.list():
        if factor.lifecycle_state not in _ACTIVE_STATES:
            continue  # RETIRED 等终态：不再喂观测
        # 真实周期 IC：仅当有真源（ic_provider）才喂；无真源 → None（不伪造，诚实优先）。
        observation = ic_provider(factor.factor_id, factor.version) if ic_provider else None
        # 绩效轴漂移：仅当有真源（perf_provider，真实周期收益序列）才喂；无真源 → None（不伪造）。
        perf_drift = perf_provider(factor.factor_id, factor.version) if perf_provider else None
        # 仅在有真实绩效信号时才把 perf_drift 入参传给 monitor_tick：保持「无真源=不喂」的诚实语义、
        # 也让既有范畴红线白名单测试（无 perf_provider 时入参不含 perf_drift）保持不破。
        tick_kwargs: dict[str, Any] = {"observation": observation, "drift_pct": drift_pct}
        if perf_drift is not None:
            tick_kwargs["perf_drift"] = perf_drift
        action = monitor_tick(manager, factor.factor_id, factor.version, **tick_kwargs)
        actions.append(action)
        if action.lifecycle_event is not None:
            logger.info(
                "weekly_monitor 因子 %s v%d 迁移 %s→%s（%s）",
                factor.factor_id,
                factor.version,
                action.lifecycle_event.from_state,
                action.lifecycle_event.to_state,
                action.lifecycle_event.reason,
            )
        elif action.drift_breach or action.perf_drift_breach:
            logger.warning("weekly_monitor 因子 %s v%d %s", factor.factor_id, factor.version, action.alert)
    return actions


# 收益序列源契约：给 (factor_id, version) 返回该因子**真实周期收益序列**（per-period，非年化），或 None。
ReturnsSource = Callable[[str, int], Sequence[float] | np.ndarray | None]
# 冻结基准源契约：给 (factor_id, version) 返回晋级期 OOS 冻结 (μ0, σ0)，或 None（无冻结基准 → CUSUM/PH 不可判定）。
FrozenBaselineSource = Callable[[str, int], tuple[float, float] | None]


def build_returns_perf_drift_provider(
    returns_source: ReturnsSource,
    baseline_source: FrozenBaselineSource | None = None,
    *,
    psr_floor: float = PSR_FLOOR_DEFAULT,
    require_confirmation: bool = False,
) -> PerfDriftProvider:
    """把真实周期收益序列接成 `perf_provider`：rolling-PSR 主告警 + CUSUM/PH 确证（绩效轴）。

    残余①的**生产可用实现**：4 个绩效轴检测器此前零生产调用方，本工厂让它们在生产真被求值。
    - rolling-PSR = **主告警**（GOAL §12「performance primary alert」+ finding「rolling-PSR 才是主告警」）；
      只接固定 `sr_benchmark`、**绝不暴露 n_trials**（命门：暴露即退化为 DSR 晋级闸，违 M-AUTHORITY=A1）。
    - CUSUM / Page-Hinkley = **确证**：须晋级期 OOS 冻结基准 μ0/σ0（`baseline_source`；温水煮青蛙 E2——
      绝不用监控窗自身均值）。无 `baseline_source`/无冻结基准 → 确证信息不可得，退化为纯 PSR 主告警（诚实）。
    - `require_confirmation`（用户方法学旋钮·默认 False=PSR 主告警单独触发）：True 时 breach 须 PSR 越阈
      **且** CUSUM/PH 任一确证（更特异、误报更少）——摆代价不替拍。

    诚实：`returns_source` 返回 None（无真实周期收益序列）→ provider 返回 None（不伪造绩效轴信号，
    与 `ic_provider` 同范式）。返回类型恒 `PerfDriftSignal`（axis="performance"）——**绝不**返回特征轴
    PSI（结构上 monitor_tick 类型层即拒）。CUSUM/PH 状态落 `detail.confirmatory` 供问责。
    """

    def _provider(factor_id: str, version: int) -> PerfDriftSignal | None:
        raw = returns_source(factor_id, version)
        if raw is None:
            return None  # 无真实周期收益 → 不喂绩效轴（诚实优先）
        returns = np.asarray(raw, dtype=float)
        psr = rolling_psr_drift(returns, psr_floor=psr_floor)  # 主告警（签名不暴露 n_trials）

        confirmatory: dict[str, Any] = {}
        cusum_breach = ph_breach = False
        if baseline_source is not None:
            base = baseline_source(factor_id, version)
            if base is not None:
                mu0, sd0 = float(base[0]), float(base[1])
                cusum = cusum_drift(returns, baseline_mean=mu0, baseline_std=sd0)
                ph = page_hinkley_drift(returns, baseline_mean=mu0, baseline_std=sd0)
                cusum_breach, ph_breach = cusum.breach, ph.breach
                confirmatory = {
                    "cusum": cusum.status, "cusum_breach": cusum.breach,
                    "page_hinkley": ph.status, "page_hinkley_breach": ph.breach,
                }

        breach = (psr.breach and (cusum_breach or ph_breach)) if require_confirmation else psr.breach
        # status 与最终 breach 对齐：require_confirmation 降级时不留「status=breach 但 breach=False」的不一致。
        if breach:
            status = "breach"
        elif psr.status == "insufficient_evidence":
            status = "insufficient_evidence"
        else:
            status = "ok"
        detail = {**psr.detail, "confirmatory": confirmatory}
        if require_confirmation and psr.breach and not breach:
            detail["psr_breach_unconfirmed"] = True
        return replace(psr, status=status, breach=breach, detail=detail)

    return _provider


def build_ic_provider(
    panel_source: Callable[[str, int], "pl.DataFrame | None"],
    *,
    factor_col: str = "factor_value",
    horizon: int = 5,
) -> ICProvider:
    """把每周「因子面板」(ts, symbol, factor_value, forward_return) 接成 `ic_provider`：周度重算 IC。

    残余②的**生产可用实现**：复用既有 `factor_factory.ic.compute_ic_report`（IC/RankIC/IC-IR +
    Newey-West HAC t——重叠 forward 窗诱导自相关的诚实显著性口径，**不另造公式**），把 ICReport 转一条
    周期绩效观测（`FactorObservation`）喂 lifecycle 权威。`sample_t` 取 NW HAC t（None→0.0，绝不虚高）。

    诚实：`panel_source` 返回 None（生产当前无真实周期因子面板源——依赖 data/factor 评估管道、属本卡领地外）
    → provider 返回 None → observation=None，**绝不**把注册期陈旧 IC 伪装成「本周观测」（paper-true 假绿灯）。
    """

    def _provider(factor_id: str, version: int) -> FactorObservation | None:
        panel = panel_source(factor_id, version)
        if panel is None:
            return None  # 无真实周期面板 → 不喂（诚实，绝不伪造 IC）
        from ..factor_factory.ic import compute_ic_report  # 懒导入：默认路径不把 polars 拖进 import 链

        report = compute_ic_report(panel, factor_col, horizon=horizon)
        if report.sample_count <= 0:
            return None  # 面板无有效截面 → 无可信观测（诚实，不造 0 观测）
        return FactorObservation(
            factor_id=factor_id,
            version=version,
            observed_at_utc=datetime.now(UTC).isoformat(),
            horizon=horizon,
            ic_mean=report.ic_mean,
            ic_ir=report.ic_ir,
            rank_ic_mean=report.rank_ic_mean,
            sample_t=report.ic_tstat_nw if report.ic_tstat_nw is not None else 0.0,
            extra={
                "source": "weekly_ic_recompute",
                "sample_count": report.sample_count,
                "ic_tstat_nw": report.ic_tstat_nw,
            },
        )

    return _provider


def collect_paper_audit_records(paper_desk: "PaperDeskService") -> list[dict[str, Any]]:
    """聚合所有 paper run 的 `ExecutionAuditLog` 成交记录（生产成本漂移的真实来源）。

    每个 paper run 持自己的 `ExecutionAuditLog`（`rec.venue.audit`），不另存第二份；
    本函数遍历聚合，喂 `compute_weekly_cost_drift`。
    """

    records: list[dict[str, Any]] = []
    # PaperDeskService._runs：run_id → PaperRunRecord（含 venue.audit）。
    for rec in list(getattr(paper_desk, "_runs", {}).values()):  # noqa: SLF001  生产聚合只读
        venue = getattr(rec, "venue", None)
        audit = getattr(venue, "audit", None)
        if audit is None:
            continue
        records.extend(audit.export())
    return records


def run_production_monitor_cycle(*, week: date | None = None) -> list[MonitorAction]:
    """生产闭环入口：拉 `app.main` 单例 + 聚合审计 → `run_weekly_monitor_pass`。

    懒导入 `app.main`（避免与 main.py 启动期的循环导入；main 在 startup 才注册本调度）。
    这是 DAG op + startup 调用的**生产接缝**；对抗测试「断接线」即不让 startup 注册本周期 →
    因子不退役（端到端红）。
    """

    from .. import main as _main  # 懒导入：破循环（main → 本模块只在 startup 引一次）

    audit_records = collect_paper_audit_records(_main.PAPER_DESK)
    return run_weekly_monitor_pass(
        _main.FACTOR_REGISTRY,
        _main.FACTOR_LIFECYCLE,
        audit_records,
        week=week,
    )


def run_weekly_monitor_tick(
    *,
    lifecycle_manager: LifecycleManager,
    factor_registry: FactorRegistry,
    execution_audit_log: ExecutionAuditLog,
    factor_observations: Iterable[FactorObservation] | None = None,
    week: date | None = None,
    asset_class: str = "crypto_perp",
    drift_threshold: float = DRIFT_DEGRADE_THRESHOLD,
) -> WeeklyMonitorResult:
    audit_records = execution_audit_log.export()
    report = compute_weekly_cost_drift(audit_records, week=week, asset_class=asset_class)
    if factor_observations is None:
        factor_observations = observations_from_registry_ic_summary(factor_registry)
    observations_by_key = {(obs.factor_id, obs.version): obs for obs in factor_observations}

    actions: list[MonitorAction] = []
    for factor in active_monitor_factors(factor_registry):
        observation = observations_by_key.get((factor.factor_id, factor.version))
        actions.append(
            monitor_tick(
                lifecycle_manager,
                factor.factor_id,
                factor.version,
                observation=observation,
                drift_pct=report.drift_pct,
                drift_threshold=drift_threshold,
            )
        )
    events = [action.lifecycle_event.to_dict() for action in actions if action.lifecycle_event is not None]
    return WeeklyMonitorResult(
        week_iso=report.week_iso,
        drift_pct=report.drift_pct,
        n_fills=report.n_fills,
        factors_checked=len(actions),
        actions=[_action_to_dict(action) for action in actions],
        lifecycle_events=events,
        cost_drift_report=report.to_dict(),
    )


def _action_to_dict(action: MonitorAction) -> dict[str, Any]:
    payload = asdict(action)
    if action.lifecycle_event is not None:
        payload["lifecycle_event"] = action.lifecycle_event.to_dict()
    return payload


@register_op(WEEKLY_MONITOR_OP, version="v1")
def _weekly_factor_monitor_op(*, context: dict[str, Any] | None = None) -> dict[str, Any]:
    """DAG op：被 `Scheduler.tick()` 经 `run_dag` 触发（参数仅 context，见 engine.py）。

    薄壳——真逻辑在 `run_production_monitor_cycle`/`run_weekly_monitor_pass`（可测、不依赖全局）。
    返回本次动作摘要（落 DAGTaskResult.result，便于审计/排障）。
    """

    actions = run_production_monitor_cycle()
    migrated = [
        {
            "factor_id": a.factor_id,
            "version": a.version,
            "to_state": a.lifecycle_event.to_state if a.lifecycle_event else None,
            "drift_pct": a.drift_pct,
            "drift_breach": a.drift_breach,
        }
        for a in actions
        if a.lifecycle_event is not None or a.drift_breach
    ]
    return {
        "ran_at_utc": datetime.now(UTC).isoformat(),
        "factors_evaluated": len(actions),
        "events_or_breaches": migrated,
    }


@register_op(MONITOR_WEEKLY_OP, version="1")
def _weekly_monitor_op(context: dict[str, Any] | None = None) -> dict[str, Any]:
    runtime = _RUNTIME
    if runtime is None:
        raise RuntimeError("monitor runtime is not configured")
    observations = (
        list(runtime.observation_provider())
        if runtime.observation_provider is not None
        else observations_from_registry_ic_summary(runtime.factor_registry)
    )
    result = run_weekly_monitor_tick(
        lifecycle_manager=runtime.lifecycle_manager,
        factor_registry=runtime.factor_registry,
        execution_audit_log=runtime.execution_audit_log,
        factor_observations=observations,
    )
    payload = result.to_dict()
    if runtime.result_recorder is not None:
        payload.update(
            runtime.result_recorder(
                result,
                {
                    "scheduled": True,
                    "entry_source": "scheduler",
                    "actor": MONITOR_WEEKLY_OP,
                    "asset_class": "crypto_perp",
                    "trigger": "dag",
                },
            )
        )
    return payload


def build_weekly_monitor_dag(*, schedule: str | None = None) -> DAGDefinition:
    """生产 weekly 监控 DAG（周一早 9 点）：单 pure 节点跑监控扫描。

    kind="pure"：本节点不触达券商/资金（无 place_order 路径），只改 registry 状态 + 落 PROV——
    故绝不标 effectful（effectful 专用于券商幂等边界）。挂 `Scheduler(strict=True)` → 缺 croniter
    启动响亮失败。
    """

    if schedule is not None:
        return DAGDefinition(
            name=MONITOR_WEEKLY_DAG_NAME,
            schedule=schedule,
            tasks=[DAGTask(id="weekly_monitor_tick", op=MONITOR_WEEKLY_OP, kind="pure")],
        )
    return DAGDefinition(
        name=WEEKLY_MONITOR_DAG_NAME,
        schedule=WEEKLY_MONITOR_CRON,
        tasks=[DAGTask(id="weekly_monitor", op=WEEKLY_MONITOR_OP, kind="pure")],
    )


def build_weekly_monitor_scheduler(*, strict: bool = True, schedule: str = MONITOR_WEEKLY_CRON) -> Scheduler:
    scheduler = Scheduler(strict=strict)
    scheduler.add(build_weekly_monitor_dag(schedule=schedule))
    return scheduler


__all__ = [
    "ACTIVE_MONITOR_STATES",
    "FrozenBaselineSource",
    "ICProvider",
    "MONITOR_WEEKLY_CRON",
    "MONITOR_WEEKLY_DAG_NAME",
    "MONITOR_WEEKLY_OP",
    "PerfDriftProvider",
    "ReturnsSource",
    "WEEKLY_MONITOR_CRON",
    "WEEKLY_MONITOR_DAG_NAME",
    "WEEKLY_MONITOR_OP",
    "WeeklyMonitorResult",
    "build_ic_provider",
    "build_returns_perf_drift_provider",
    "build_weekly_monitor_dag",
    "build_weekly_monitor_scheduler",
    "collect_paper_audit_records",
    "configure_monitor_runtime",
    "observation_from_payload",
    "run_production_monitor_cycle",
    "run_weekly_monitor_tick",
    "run_weekly_monitor_pass",
]
