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
from collections.abc import Callable, Iterable
from datetime import UTC, date, datetime
from typing import TYPE_CHECKING, Any

from ..dag.engine import DAGDefinition, DAGTask, register_op
from ..factor_factory.lifecycle import FactorObservation, LifecycleManager
from ..factor_factory.registry import FactorRegistry
from .closure import MonitorAction, monitor_tick
from .cost_drift import compute_weekly_cost_drift

if TYPE_CHECKING:  # 仅类型：避免运行期把 paper 包拖进 import 链
    from ..paper.desk import PaperDeskService

logger = logging.getLogger(__name__)

# 生产 weekly 监控调度名 + cron（周一 09:00 UTC 跑上周漂移）。
WEEKLY_MONITOR_DAG_NAME = "weekly_factor_monitor"
WEEKLY_MONITOR_OP = "weekly_factor_monitor"
WEEKLY_MONITOR_CRON = "0 9 * * 1"

# 活跃 = 仍在运营轨道、可被退役的状态（RETIRED 已退役、再喂无意义）。
_ACTIVE_STATES = ("NEW", "QUALIFIED", "PROBATION", "OBSERVATION", "WARNING")

# ic_provider 契约：给 (factor_id, version) 返回**真实**周期 IC 观测，或 None（无真源时）。
ICProvider = Callable[[str, int], FactorObservation | None]


def run_weekly_monitor_pass(
    registry: FactorRegistry,
    manager: LifecycleManager,
    audit_records: Iterable[dict[str, Any]],
    *,
    week: date | None = None,
    asset_class: str = "crypto_perp",
    ic_provider: ICProvider | None = None,
) -> list[MonitorAction]:
    """一次生产 weekly 监控扫描：成本漂移 + 周期观测 → 对每个活跃因子驱动 `monitor_tick`。

    这是**因子观测记录管道 + 生产闭环的唯一逻辑接缝**：闭环是否在生产真跑，取决于本函数是否被
    生产调度调用（见 `run_production_monitor_cycle` + `main.py` startup）。对抗测试「断接线」即
    不注册/不调用本路径 → 因子停在 WARNING、不退役（证明接线真生效，非套套逻辑）。

    诚实：`ic_provider=None`（生产默认）时**只**喂成本漂移信号（真实测得），绝不伪造 per-factor IC。
    范畴红线：只向 `monitor_tick` 传 `drift_pct`/`observation`（绩效轴），绝不传 gate verdict。
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
        action = monitor_tick(
            manager,
            factor.factor_id,
            factor.version,
            observation=observation,
            drift_pct=drift_pct,
        )
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
        elif action.drift_breach:
            logger.warning("weekly_monitor 因子 %s v%d %s", factor.factor_id, factor.version, action.alert)
    return actions


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


def build_weekly_monitor_dag() -> DAGDefinition:
    """生产 weekly 监控 DAG（周一早 9 点）：单 pure 节点跑监控扫描。

    kind="pure"：本节点不触达券商/资金（无 place_order 路径），只改 registry 状态 + 落 PROV——
    故绝不标 effectful（effectful 专用于券商幂等边界）。挂 `Scheduler(strict=True)` → 缺 croniter
    启动响亮失败。
    """

    return DAGDefinition(
        name=WEEKLY_MONITOR_DAG_NAME,
        schedule=WEEKLY_MONITOR_CRON,
        tasks=[DAGTask(id="weekly_monitor", op=WEEKLY_MONITOR_OP, kind="pure")],
    )


__all__ = [
    "ICProvider",
    "WEEKLY_MONITOR_CRON",
    "WEEKLY_MONITOR_DAG_NAME",
    "WEEKLY_MONITOR_OP",
    "build_weekly_monitor_dag",
    "collect_paper_audit_records",
    "run_production_monitor_cycle",
    "run_weekly_monitor_pass",
]
