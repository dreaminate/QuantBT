"""M13 · 内置百行级 DAG 引擎。

设计目标：
- 不引 Prefect / Dagster；保留它们作为可选适配器位置。
- YAML 或 Python 装饰器都能定义 DAG（这里实现 YAML + dataclass）。
- 依赖（blocks/blockedBy）+ 重试（指数退避）+ 超时 + 幂等键 + SLA 告警。
- cron 触发用 croniter 但作为软依赖；缺它时只能手动 trigger。
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any, Callable, Iterable, Literal

import yaml

if TYPE_CHECKING:                       # 仅类型：kernel import 自 engine，运行期再 import 会循环
    from .kernel import DurableExecutor


logger = logging.getLogger(__name__)


DAGTaskStatus = Literal[
    "pending", "running", "succeeded", "failed", "skipped", "timeout",
    "reused",   # 脊柱内核：durable 命中工件 / effectful 幂等命中，未重跑
    "halted",   # 脊柱内核：effectful 边界在 replay/fork/rollback 被截断（HALT_AT_BOUNDARY）
]

# 节点分类（脊柱内核 01）：pure 可自由 replay/fork/rollback；effectful 触达券商/资金，
# 必带 effect_idempotency_key，且在 replay/fork/rollback 路径一律 HALT，绝不重发副作用。
NodeKind = Literal["pure", "effectful"]


_OPS: dict[str, Callable[..., Any]] = {}
# op 代码版本（脊柱内核：进 node_id 的 structure，op 实现变了 → 工件失效，复核 #3）。
# 声明式 version 优先；未声明则内核按 fn.__code__.co_code 自动指纹（改逻辑即失效，安全方向）。
_OP_VERSIONS: dict[str, str] = {}


def register_op(
    name: str | None = None, *, version: str | None = None
) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    def _decorator(fn: Callable[..., Any]) -> Callable[..., Any]:
        key = name or fn.__name__
        _OPS[key] = fn
        if version is not None:
            _OP_VERSIONS[key] = version
            fn._op_version = version  # type: ignore[attr-defined]
        return fn
    return _decorator


def list_ops() -> list[str]:
    return sorted(_OPS.keys())


@dataclass
class DAGTask:
    id: str
    op: str
    params: dict[str, Any] = field(default_factory=dict)
    deps: list[str] = field(default_factory=list)
    retries: int = 0
    retry_backoff_seconds: float = 1.0
    timeout_seconds: float | None = None
    idempotency_key: str | None = None        # deprecated 别名；effectful 节点会迁移到下面的新字段
    sla_seconds: float | None = None
    # 脊柱内核 01（决策 R10/M17）：节点分类 + effectful 幂等键。默认 pure（安全默认）。
    kind: NodeKind = "pure"
    effect_idempotency_key: str | None = None  # 00-contracts C8

    def __post_init__(self) -> None:
        # 「字段 → 强制约束」升级（任务书核心要求）：effectful 节点不带幂等键 = 会重发单的雷，
        # 构造即拒。pure 节点带 effect 键 = 误标，也拒。旧 idempotency_key 仅对 effectful 迁移。
        if self.kind == "effectful":
            if self.effect_idempotency_key is None and self.idempotency_key is not None:
                self.effect_idempotency_key = self.idempotency_key  # 迁移旧别名
            if not self.effect_idempotency_key:
                raise ValueError(
                    f"effectful 节点 {self.id!r} 必须带 effect_idempotency_key（否则 replay/重试=重发单，M17 雷）"
                )
        elif self.kind == "pure":
            if self.effect_idempotency_key is not None:
                raise ValueError(f"pure 节点 {self.id!r} 不应带 effect_idempotency_key（误标 effectful？）")
        else:
            raise ValueError(f"非法 kind={self.kind!r}，须 ∈ ('pure','effectful')")


@dataclass
class DAGDefinition:
    name: str
    tasks: list[DAGTask]
    schedule: str | None = None  # cron 表达式

    @classmethod
    def from_yaml(cls, text: str) -> "DAGDefinition":
        data = yaml.safe_load(text)
        return cls(
            name=data["name"],
            schedule=data.get("schedule"),
            tasks=[DAGTask(**{k: v for k, v in t.items() if k in DAGTask.__dataclass_fields__}) for t in data["tasks"]],
        )


@dataclass
class DAGTaskResult:
    task_id: str
    status: DAGTaskStatus
    attempts: int
    started_at_utc: str | None
    finished_at_utc: str | None
    result: Any = None
    error: str | None = None
    sla_violated: bool = False
    duration_seconds: float = 0.0


@dataclass
class DAGRunResult:
    dag_name: str
    started_at_utc: str
    finished_at_utc: str
    succeeded: bool
    tasks: list[DAGTaskResult]


def run_dag(
    definition: DAGDefinition,
    *,
    context: dict[str, Any] | None = None,
    executor: "DurableExecutor | None" = None,
) -> DAGRunResult:
    """串行 + topological 执行。生产可换并发，但保持简单。

    脊柱内核 01 接线（T-023，扩展不替换）：传入 `executor`（DurableExecutor）即把这条编排路径
    切到确定性内核——durable 复用 pure 工件、effectful 经统一幂等账去重、replay/fork/rollback 在
    effectful 边界 HALT。`executor=None`（默认）保持现有全量串行语义，既有 DAG 测试零改动。
    身份单一源（C5/C7/C8）：node_id 由内核（lineage.ids）计算，engine 绝不另算第二套。
    """

    if context is None:
        context = {}
    if executor is not None:
        return _run_dag_via_kernel(definition, context, executor)
    ordered = _topological_sort(definition.tasks)
    started = datetime.now(UTC).isoformat()
    results: dict[str, DAGTaskResult] = {}
    succeeded = True
    for task in ordered:
        if any(results.get(d) and results[d].status != "succeeded" for d in task.deps):
            results[task.id] = DAGTaskResult(
                task_id=task.id, status="skipped", attempts=0, started_at_utc=None, finished_at_utc=None,
                error="依赖未成功",
            )
            succeeded = False
            continue
        result = _run_task(task, context)
        results[task.id] = result
        if result.status != "succeeded":
            succeeded = False
    return DAGRunResult(
        dag_name=definition.name,
        started_at_utc=started,
        finished_at_utc=datetime.now(UTC).isoformat(),
        succeeded=succeeded,
        tasks=list(results.values()),
    )


def _run_dag_via_kernel(
    definition: DAGDefinition, context: dict[str, Any], executor: "DurableExecutor"
) -> DAGRunResult:
    """把 DAG 交确定性内核执行，再把 KernelRunResult 映射回 DAGRunResult（对外协议不变）。

    内核 `run` 路径产出的节点状态（succeeded/reused/halted/failed/skipped）全在 DAGTaskStatus 内；
    halted 表示 effectful 边界被截断（未触达券商，待对账），调用方据 `succeeded=False` 即知未全绿。
    """

    started = datetime.now(UTC).isoformat()
    kr = executor.run(definition.tasks, context)
    finished = datetime.now(UTC).isoformat()
    tasks = [
        DAGTaskResult(
            task_id=n.task_id,
            status=n.status,          # type: ignore[arg-type]  # 内核状态 ⊆ DAGTaskStatus
            attempts=1,
            started_at_utc=started,
            finished_at_utc=finished,
            result=n.result,
            error=n.error,
        )
        for n in kr.nodes
    ]
    return DAGRunResult(
        dag_name=definition.name,
        started_at_utc=started,
        finished_at_utc=finished,
        succeeded=kr.succeeded,
        tasks=tasks,
    )


def _run_task(task: DAGTask, context: dict[str, Any]) -> DAGTaskResult:
    if task.op not in _OPS:
        return DAGTaskResult(
            task_id=task.id, status="failed", attempts=0, started_at_utc=None, finished_at_utc=None,
            error=f"未注册 op: {task.op}（已注册 {list_ops()}）",
        )
    fn = _OPS[task.op]
    attempts = 0
    error: str | None = None
    start_iso = datetime.now(UTC).isoformat()
    t0 = time.perf_counter()
    last_result: Any = None
    while attempts <= task.retries:
        attempts += 1
        try:
            if task.timeout_seconds is not None:
                last_result = _run_with_timeout(fn, task.params, context, task.timeout_seconds)
            else:
                last_result = fn(context=context, **task.params)
            duration = time.perf_counter() - t0
            sla_violated = bool(task.sla_seconds and duration > task.sla_seconds)
            return DAGTaskResult(
                task_id=task.id, status="succeeded", attempts=attempts,
                started_at_utc=start_iso, finished_at_utc=datetime.now(UTC).isoformat(),
                result=last_result, sla_violated=sla_violated, duration_seconds=duration,
            )
        except TimeoutError as exc:
            error = f"timeout: {exc}"
            return DAGTaskResult(
                task_id=task.id, status="timeout", attempts=attempts,
                started_at_utc=start_iso, finished_at_utc=datetime.now(UTC).isoformat(),
                error=error, duration_seconds=time.perf_counter() - t0,
            )
        except Exception as exc:  # noqa: BLE001
            error = f"{type(exc).__name__}: {exc}"
            if attempts <= task.retries:
                sleep_s = task.retry_backoff_seconds * (2 ** (attempts - 1))
                logger.warning("task %s 失败，%ss 后重试 #%d: %s", task.id, sleep_s, attempts, error)
                time.sleep(sleep_s)
            else:
                break
    return DAGTaskResult(
        task_id=task.id, status="failed", attempts=attempts,
        started_at_utc=start_iso, finished_at_utc=datetime.now(UTC).isoformat(),
        error=error, duration_seconds=time.perf_counter() - t0,
    )


def _run_with_timeout(fn: Callable[..., Any], params: dict[str, Any], context: dict[str, Any], timeout: float) -> Any:
    result: dict[str, Any] = {}
    error: dict[str, Exception] = {}

    def _runner() -> None:
        try:
            result["v"] = fn(context=context, **params)
        except Exception as exc:  # noqa: BLE001
            error["e"] = exc

    t = threading.Thread(target=_runner, daemon=True)
    t.start()
    t.join(timeout=timeout)
    if t.is_alive():
        raise TimeoutError(f"op > {timeout}s")
    if "e" in error:
        raise error["e"]
    return result.get("v")


def _topological_sort(tasks: Iterable[DAGTask]) -> list[DAGTask]:
    by_id = {t.id: t for t in tasks}
    visited: set[str] = set()
    ordered: list[DAGTask] = []
    temp: set[str] = set()

    def _visit(tid: str) -> None:
        if tid in visited:
            return
        if tid in temp:
            raise ValueError(f"DAG 循环依赖：{tid}")
        temp.add(tid)
        for dep in by_id[tid].deps:
            if dep not in by_id:
                raise ValueError(f"task {tid} 依赖未知 {dep}")
            _visit(dep)
        temp.remove(tid)
        visited.add(tid)
        ordered.append(by_id[tid])

    for t in tasks:
        _visit(t.id)
    return ordered


class Scheduler:
    """轻量 cron 触发器：调用方在 loop 里 every N seconds 调 `tick()`，发到期 DAG 出去执行。"""

    def __init__(self) -> None:
        try:
            from croniter import croniter  # type: ignore[import-not-found]
        except Exception:  # noqa: BLE001
            self._croniter = None
        else:
            self._croniter = croniter
        self._jobs: dict[str, tuple[DAGDefinition, datetime]] = {}

    def add(self, definition: DAGDefinition) -> None:
        if not definition.schedule:
            raise ValueError("DAG 没有 schedule，不能 schedule")
        if self._croniter is None:
            raise RuntimeError("缺少 croniter 包；可手动 run_dag 触发")
        next_fire = self._croniter(definition.schedule, datetime.now(UTC)).get_next(datetime)
        self._jobs[definition.name] = (definition, next_fire)

    def tick(self, now: datetime | None = None) -> list[DAGRunResult]:
        if self._croniter is None:
            return []
        now = now or datetime.now(UTC)
        fired: list[DAGRunResult] = []
        for name, (definition, scheduled_at) in list(self._jobs.items()):
            if scheduled_at <= now:
                fired.append(run_dag(definition))
                next_fire = self._croniter(definition.schedule, now).get_next(datetime)
                self._jobs[name] = (definition, next_fire)
        return fired


__all__ = [
    "DAGDefinition",
    "DAGRunResult",
    "DAGTask",
    "DAGTaskResult",
    "DAGTaskStatus",
    "NodeKind",
    "Scheduler",
    "list_ops",
    "register_op",
    "run_dag",
]
