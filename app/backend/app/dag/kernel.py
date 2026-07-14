"""脊柱内核 01 · DurableExecutor：确定性图调度 + durable 复用 + effectful 不可幂等边界。

五件事（设计 01 §1.1）：
1. **节点内容寻址身份**：复用 `lineage.ids.node_id`（T-012 单一身份源，**绝不另造**第二套），
   node_id = sha256(canonical_json(structure, inputs, sorted(upstream)))[:16]，与谱系 content_hash 同族。
2. **durable execution**（R11）：`store.exists(node_id)` 命中即【读工件、绝不重跑】（含 LLM 节点）。
   选边 durable 不奢望 reproducible（dossier §7：商用 LLM temp=0 也不逐位可复现）。
3. **replay / fork / rollback** 三语义，checkpoint_id == node_id（00-contracts C5）。
4. **节点分类纪律**：`pure` 自由 replay/fork/rollback；`effectful`（触达券商/资金）在
   **replay/fork/rollback 三条路径一律 HALT_AT_BOUNDARY** → 发 reconcile 事件交对账，**绝不重发副作用**。
5. **LLM 永在节点内、绝不当控制器**：调度只认【运行前冻结的静态 deps】，节点产出绝不能改图结构。

诚实边界（R7/dossier §7）：内核唯一硬锁是 effectful 边界（动钱/不可逆）；pure 侧 replay/fork 全放开。
裁决/报告措辞禁说「reproducible/可信/安全/组织独立」（见 render_report）。
内核**不拥有** honest-N 计数（那是部件03 试验账本）——只产 node_id 并对每次 attempt 发通知
（`on_attempt`），**红线：durable 复用绝不能反过来把 N 改小**（复用省 compute ≠ 少计一次 attempt）。

**`context` 契约（复核 #1，刻进纪律）**：op 被调用时拿到 `task.params` + 运行期 `context`。
**node_id 只哈希 params/structure/upstream，不哈希 context**——因此 `context` 只可携带【非身份】
的基础设施句柄（venue 客户端 / sink / 连接），**绝不可携带影响产出的数据输入**（如 seed/数据切片）。
一切影响产出的输入【必须】走 `task.params`（才会进 node_id 内容寻址）。把数据塞进 context 会造成
「不同输入撞同一 node_id → 复用错工件」的假命中（最危险）。effectful 路径另由 effect_idempotency_key
把关，不会因此重发单，但 pure 路径会取到陈旧工件——故此契约是硬纪律。
"""

from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, Callable, Iterable

from ..lineage.ids import DECORATIVE_KEYS, canonical_json, node_id as _ids_node_id
from .artifact_store import ArtifactStore
from .effect_ledger import EffectIdempotencyViolation, EffectLedger
from .engine import DAGTask, _OP_VERSIONS, _OPS, _topological_sort


# 内核操作模式（决定 effectful 节点在「非正向执行」路径上的行为）。
_RUN = "run"          # 正向执行（含崩溃后续跑）：effectful 已消费→复用；未消费→执行副作用
_REPLAY = "replay"    # 重放：effectful 已消费且有工件→复用；否则 HALT（不在重放路径触达券商）
_FORK = "fork"        # what-if：改了的子图里 effectful 一律 HALT（绝不在假设分支动钱）
_CAPABILITY_KIND_BY_MODE = {
    _RUN: "dag_checkpoint",
    _REPLAY: "dag_replay",
    _FORK: "dag_fork",
    "rollback": "dag_rollback",
}

logger = logging.getLogger(__name__)

# 报告措辞黑名单（R7/dossier §7：内核给 durable 证据，绝不渲染成「结论可信」）。
_BANNED_REPORT_WORDS = ("reproducible", "可信", "安全", "组织独立")


def _io_normalize(params: Any) -> Any:
    """归一节点输入：剔除纯装饰键（与 config_hash 共用 `ids.DECORATIVE_KEYS` 单一源）。

    安全方向（设计开放问题 #1）：漏排装饰键 → 顶多 cache miss 多算一次（安全）；
    错排真实键 → 假命中复用了不该复用的工件（最危险）。故只剔已知装饰键，宁可少剔。
    """

    if isinstance(params, dict):
        return {k: v for k, v in params.items() if k not in DECORATIVE_KEYS}
    return params


def op_fingerprint(fn: Callable[..., Any] | None, op_name: str) -> str:
    """op 代码指纹（进 node_id 的 structure，复核 #3）：声明式 version 优先，否则按字节码自动指纹。

    改了 op 实现 → 指纹变 → node_id 变 → 不复用陈旧工件（安全方向：宁可 cache miss 多算）。
    """

    declared = (getattr(fn, "_op_version", None) if fn is not None else None) or _OP_VERSIONS.get(op_name)
    if declared:
        return str(declared)
    code = getattr(fn, "__code__", None)
    if code is not None:
        return hashlib.sha256(code.co_code).hexdigest()[:8]
    return "0"


def compute_node_id(
    task: DAGTask, upstream_ids: Iterable[str] = (), *, op_version: str | None = None
) -> str:
    """节点内容寻址身份。复用 ids.node_id（单一源，绝不另造）。

    structure = {op 名, kind, [op_version]}：
    - kind 入哈希（复核 #5）：pure 与 effectful 同 op+params 不再撞同一 node_id（否则 effectful
      工件被 pure 覆盖 / 重放取到错工件）。
    - op_version（执行器传入，复核 #3）：op 实现变了 → node_id 变 → 不复用陈旧工件。
    inputs = 归一 params（剔装饰键，与 config_hash 共用 ids.DECORATIVE_KEYS）；context 不入哈希（见模块契约）。
    upstream = 上游 node_id（内容寻址，上游变则本节点变）。
    """

    structure: dict[str, Any] = {"op": task.op, "kind": task.kind}
    if op_version is not None:
        structure["op_version"] = op_version
    return _ids_node_id(structure=structure, inputs=_io_normalize(task.params), upstream=sorted(upstream_ids))


@dataclass
class NodeRunResult:
    task_id: str
    node_id: str
    kind: str
    status: str                       # succeeded | reused | halted | failed | skipped | rolled_back
    reused: bool = False
    halted: bool = False
    requires_reconcile: bool = False
    result: Any = None
    error: str | None = None
    effect_idempotency_key: str | None = None


@dataclass
class KernelRunResult:
    mode: str
    succeeded: bool
    nodes: list[NodeRunResult]
    node_id_by_task: dict[str, str]
    events: list[dict[str, Any]] = field(default_factory=list)
    capability_record_ref: str = ""

    def node(self, task_id: str) -> NodeRunResult | None:
        return next((n for n in self.nodes if n.task_id == task_id), None)


class DurableExecutor:
    """确定性图内核。run/replay/fork/rollback 共用一套节点身份与 durable 复用，
    唯一硬锁是 effectful 边界在非正向路径 HALT。"""

    def __init__(
        self,
        root: Path | str | None = None,
        *,
        store: ArtifactStore | None = None,
        ledger: EffectLedger | None = None,
        ops: dict[str, Callable[..., Any]] | None = None,
        on_event: Callable[[dict[str, Any]], None] | None = None,
        on_attempt: Callable[[str, str], None] | None = None,
        capability_ledger: Any | None = None,
        capability_owner_user_id: str = "",
        capability_workflow_id: str = "",
    ) -> None:
        if store is None or ledger is None:
            if root is None:
                raise ValueError("DurableExecutor 需要 root 或显式 store+ledger")
            root = Path(root)
            store = store or ArtifactStore(root)
            ledger = ledger or EffectLedger(root)
        self._store = store
        self._ledger = ledger
        self._ops = ops if ops is not None else _OPS   # 默认复用 engine 全局 op 注册表
        self._on_event = on_event
        self._on_attempt = on_attempt
        self._capability_ledger = None
        self._capability_owner_user_id = ""
        self._capability_workflow_id = ""
        if (
            capability_ledger is not None
            or capability_owner_user_id
            or capability_workflow_id
        ):
            self.bind_capability_scope(
                ledger=capability_ledger,
                owner_user_id=capability_owner_user_id,
                workflow_id=capability_workflow_id,
            )

    def _node_id(self, task: DAGTask, upstream_ids: Iterable[str]) -> str:
        """执行器内统一身份口径：含 op 代码指纹（复核 #3）。run/replay/fork/rollback 全走此处，保证一致。"""

        return compute_node_id(task, upstream_ids, op_version=op_fingerprint(self._ops.get(task.op), task.op))

    def bind_capability_scope(
        self,
        *,
        ledger: Any,
        owner_user_id: str,
        workflow_id: str,
    ) -> None:
        """Bind one exact owner/workflow capability sink to this executor.

        An executor cannot be rebound across tenants or workflows.  Callers that
        have no real owner/workflow identity must leave the sink unbound rather
        than insert a service/default identity.
        """

        owner = str(owner_user_id or "").strip()
        workflow = str(workflow_id or "").strip()
        required_methods = (
            "prepare_operation",
            "record_dag_operation",
            "commit_operation",
            "abort_operation",
        )
        if ledger is None or any(
            not callable(getattr(ledger, method, None)) for method in required_methods
        ):
            raise ValueError(
                "capability ledger must expose prepared DAG operation methods"
            )
        if not owner:
            raise ValueError("capability owner_user_id is required")
        if not workflow:
            raise ValueError("capability workflow_id is required")
        if self._capability_ledger is not None:
            if (
                self._capability_ledger is not ledger
                or self._capability_owner_user_id != owner
                or self._capability_workflow_id != workflow
            ):
                raise ValueError("DurableExecutor capability scope cannot be rebound")
            return
        self._capability_ledger = ledger
        self._capability_owner_user_id = owner
        self._capability_workflow_id = workflow

    @staticmethod
    def _capability_failure_ref(exc: BaseException) -> str:
        material = canonical_json({"exception_type": type(exc).__name__})
        return "capability_failure:sha256:" + hashlib.sha256(
            material.encode("utf-8")
        ).hexdigest()

    def _prepare_capability(
        self,
        *,
        mode: str,
        tasks: list[DAGTask],
        details: dict[str, Any] | None = None,
    ) -> Any | None:
        if self._capability_ledger is None:
            return None
        request_material = {
            "mode": mode,
            "tasks": [
                {
                    "task_id": task.id,
                    "op": task.op,
                    "kind": task.kind,
                    "deps": list(task.deps),
                    "params_hash": hashlib.sha256(
                        canonical_json(task.params).encode("utf-8")
                    ).hexdigest(),
                }
                for task in tasks
            ],
            "details": dict(details or {}),
        }
        request_ref = "dag_operation_request:sha256:" + hashlib.sha256(
            canonical_json(request_material).encode("utf-8")
        ).hexdigest()
        return self._capability_ledger.prepare_operation(
            owner_user_id=self._capability_owner_user_id,
            workflow_id=self._capability_workflow_id,
            target_kind=_CAPABILITY_KIND_BY_MODE[mode],
            request_ref=request_ref,
        )

    def _abort_capability(self, prepared: Any | None, exc: BaseException) -> None:
        if prepared is None:
            return
        self._capability_ledger.abort_operation(
            owner_user_id=self._capability_owner_user_id,
            workflow_id=self._capability_workflow_id,
            prepared_record_ref=prepared.record_ref,
            failure_ref=self._capability_failure_ref(exc),
        )

    def _record_capability(
        self,
        *,
        mode: str,
        tasks: list[DAGTask],
        result: KernelRunResult,
        details: dict[str, Any] | None = None,
        prepared: Any | None = None,
    ) -> KernelRunResult:
        # A failed/halted DAG result is useful diagnostic state, but it is not a
        # successful capability and must not mint a green durable record.
        if self._capability_ledger is None:
            return result
        if result.succeeded is not True:
            self._abort_capability(
                prepared,
                RuntimeError(f"DAG operation returned succeeded={result.succeeded!r}"),
            )
            return result
        try:
            record = self._capability_ledger.record_dag_operation(
                owner_user_id=self._capability_owner_user_id,
                workflow_id=self._capability_workflow_id,
                mode=mode,
                tasks=tuple(tasks),
                result=result,
                details=dict(details or {}),
            )
        except Exception as exc:
            if type(exc).__name__ != "AgentCapabilityCommitUncertain":
                self._abort_capability(prepared, exc)
            raise
        result.capability_record_ref = str(record.record_ref)
        if prepared is not None:
            self._capability_ledger.commit_operation(
                owner_user_id=self._capability_owner_user_id,
                workflow_id=self._capability_workflow_id,
                prepared_record_ref=prepared.record_ref,
                capability_refs=(record.record_ref,),
            )
        return result

    # ── 公开操作 ──────────────────────────────────────────────────────────
    def run(self, tasks: list[DAGTask], context: dict[str, Any] | None = None) -> KernelRunResult:
        prepared = self._prepare_capability(mode=_RUN, tasks=tasks)
        try:
            result = self._execute(tasks, context or {}, _RUN)
        except Exception as exc:
            self._abort_capability(prepared, exc)
            raise
        return self._record_capability(
            mode=_RUN, tasks=tasks, result=result, prepared=prepared
        )

    def replay(self, tasks: list[DAGTask], context: dict[str, Any] | None = None) -> KernelRunResult:
        prepared = self._prepare_capability(mode=_REPLAY, tasks=tasks)
        try:
            result = self._execute(tasks, context or {}, _REPLAY)
        except Exception as exc:
            self._abort_capability(prepared, exc)
            raise
        return self._record_capability(
            mode=_REPLAY, tasks=tasks, result=result, prepared=prepared
        )

    def fork(
        self,
        tasks: list[DAGTask],
        *,
        from_task_id: str,
        overrides: dict[str, Any],
        context: dict[str, Any] | None = None,
    ) -> KernelRunResult:
        """what-if：对 from_task 改参数 → 其 node_id 变 → 该节点及下游全成新 node_id（cache miss）。
        改了的子图里 effectful 节点一律 HALT（绝不在假设分支动钱）；上游不变的工件原样复用。"""

        if not any(t.id == from_task_id for t in tasks):
            raise ValueError(f"fork 目标未知: {from_task_id!r}")   # 复核 #4：未知 id 不得静默 no-op
        forked = [
            replace(t, params={**t.params, **overrides}) if t.id == from_task_id else t
            for t in tasks
        ]
        details = {
            "from_task_id": from_task_id,
            "overrides_ref": "sha256:"
            + hashlib.sha256(canonical_json(overrides).encode("utf-8")).hexdigest(),
        }
        prepared = self._prepare_capability(
            mode=_FORK,
            tasks=forked,
            details=details,
        )
        try:
            result = self._execute(forked, context or {}, _FORK)
        except Exception as exc:
            self._abort_capability(prepared, exc)
            raise
        return self._record_capability(
            mode=_FORK,
            tasks=forked,
            result=result,
            details=details,
            prepared=prepared,
        )

    def rollback(
        self, tasks: list[DAGTask], *, to_task_id: str, context: dict[str, Any] | None = None
    ) -> KernelRunResult:
        """回滚到 to_task：丢弃其【下游】pure 工件（使其下次重算）；下游 effectful 已消费的
        **绝不撤单/反向单**，标 halted + requires_reconcile 发 reconcile 事件交对账（R7 硬边界）。
        本方法不执行任何 op（零 venue 调用）。"""

        if to_task_id not in {t.id for t in tasks}:
            raise ValueError(f"rollback 目标未知: {to_task_id!r}")   # 复核 #4：未知 id 不得静默 no-op
        ordered = _topological_sort(tasks)
        node_id_by_task: dict[str, str] = {}
        for task in ordered:
            up = sorted(node_id_by_task[d] for d in task.deps if d in node_id_by_task)
            node_id_by_task[task.id] = self._node_id(task, up)

        descendants = _descendants(tasks, to_task_id)
        nodes: list[NodeRunResult] = []
        events: list[dict[str, Any]] = []
        details = {"to_task_id": to_task_id}
        prepared = self._prepare_capability(
            mode="rollback",
            tasks=tasks,
            details=details,
        )
        try:
            for task in ordered:
                nid = node_id_by_task[task.id]
                if task.id not in descendants:
                    nodes.append(
                        NodeRunResult(
                            task.id, nid, task.kind, status="reused", reused=True
                        )
                    )
                    continue
                if task.kind == "pure":
                    self._store.discard(nid)
                    nodes.append(
                        NodeRunResult(task.id, nid, "pure", status="rolled_back")
                    )
                    self._emit(events, "ROLLED_BACK", nid, task.id)
                else:  # effectful：已消费的副作用不可撤——HALT + 对账，绝不撤单
                    consumed = self._ledger.is_consumed(
                        task.effect_idempotency_key or ""
                    )
                    if consumed:
                        nodes.append(
                            NodeRunResult(
                                task.id,
                                nid,
                                "effectful",
                                status="halted",
                                halted=True,
                                requires_reconcile=True,
                                effect_idempotency_key=task.effect_idempotency_key,
                            )
                        )
                        self._emit(events, "HALT", nid, task.id)
                        self._emit(events, "RECONCILE_REQUIRED", nid, task.id)
                    else:
                        nodes.append(
                            NodeRunResult(
                                task.id,
                                nid,
                                "effectful",
                                status="rolled_back",
                                effect_idempotency_key=task.effect_idempotency_key,
                            )
                        )
        except Exception as exc:
            self._abort_capability(prepared, exc)
            raise
        result = KernelRunResult(mode="rollback", succeeded=True, nodes=nodes,
                                 node_id_by_task=node_id_by_task, events=events)
        return self._record_capability(
            mode="rollback",
            tasks=tasks,
            result=result,
            details=details,
            prepared=prepared,
        )

    # ── 执行核心 ──────────────────────────────────────────────────────────
    def _execute(self, tasks: list[DAGTask], context: dict[str, Any], mode: str) -> KernelRunResult:
        ordered = _topological_sort(tasks)     # 图结构【运行前冻结】：调度只认静态 deps（T-DET-8）
        node_id_by_task: dict[str, str] = {}
        nodes: list[NodeRunResult] = []
        events: list[dict[str, Any]] = []
        dep_ok: dict[str, bool] = {}
        succeeded = True

        for task in ordered:
            up = sorted(node_id_by_task[d] for d in task.deps if d in node_id_by_task)
            nid = self._node_id(task, up)
            node_id_by_task[task.id] = nid

            if any(not dep_ok.get(d, False) for d in task.deps):
                nodes.append(NodeRunResult(task.id, nid, task.kind, status="skipped",
                                           error="依赖未成功或被边界截断"))
                dep_ok[task.id] = False
                succeeded = False
                self._emit(events, "SKIP", nid, task.id)
                continue

            # honest-N 通知：每次 attempt 都通知账本（含 reused），复用绝不少计一次（R1/R8 红线）。
            if self._on_attempt is not None:
                self._on_attempt(nid, task.id)

            self._emit(events, "START", nid, task.id)
            res = self._run_node(task, nid, context, mode)
            nodes.append(res)
            dep_ok[task.id] = res.status in ("succeeded", "reused")
            if res.status in ("failed", "timeout", "halted", "skipped"):
                succeeded = False
            if res.status == "halted":
                self._emit(events, "HALT", nid, task.id)
                if res.requires_reconcile:
                    self._emit(events, "RECONCILE_REQUIRED", nid, task.id)
            elif res.status == "reused":
                self._emit(events, "REUSED", nid, task.id)
            elif res.status == "succeeded":
                self._emit(events, "COMPLETE", nid, task.id)
            elif res.status in ("failed", "timeout"):
                self._emit(events, "FAIL", nid, task.id)

        return KernelRunResult(mode=mode, succeeded=succeeded, nodes=nodes,
                               node_id_by_task=node_id_by_task, events=events)

    def _run_node(self, task: DAGTask, nid: str, context: dict[str, Any], mode: str) -> NodeRunResult:
        if task.kind == "pure":
            return self._run_pure(task, nid, context)
        return self._run_effectful(task, nid, context, mode)

    def _run_pure(self, task: DAGTask, nid: str, context: dict[str, Any]) -> NodeRunResult:
        if self._store.exists(nid):                      # durable 命中：读工件、绝不重跑（含 LLM 节点）
            return NodeRunResult(task.id, nid, "pure", status="reused", reused=True,
                                 result=self._store.get(nid))
        try:
            val = self._call_op(task, context)
        except Exception as exc:  # noqa: BLE001
            return NodeRunResult(task.id, nid, "pure", status="failed", error=f"{type(exc).__name__}: {exc}")
        self._store.put(nid, val)
        # 复核 #2：返回 round-trip 后的工件，保证 run 与 reused/replay 逐字段一致（消除静默不对称）。
        return NodeRunResult(task.id, nid, "pure", status="succeeded", result=self._store.get(nid))

    def _run_effectful(self, task: DAGTask, nid: str, context: dict[str, Any], mode: str) -> NodeRunResult:
        key = task.effect_idempotency_key or ""
        consumed = self._ledger.is_consumed(key)

        if mode == _RUN:
            if consumed:                                  # 幂等命中：返存量、绝不重发副作用（M17）
                val = self._store.get(nid) if self._store.exists(nid) else None
                return NodeRunResult(task.id, nid, "effectful", status="reused", reused=True,
                                     result=val, effect_idempotency_key=key)
            try:
                val = self._call_op(task, context)        # 真副作用（下单/提币/桥）
            except Exception as exc:  # noqa: BLE001
                return NodeRunResult(task.id, nid, "effectful", status="failed",
                                     error=f"{type(exc).__name__}: {exc}", effect_idempotency_key=key)
            # 副作用成功 → 立即记幂等账（尽量缩小「已下单未记账」窗口），再落工件。
            # 记账失败【绝不静默】（money-safety 复核 probe-4）：已发生的副作用无法回滚，
            # 必须记 CRITICAL 并按情形标 reconcile，交对账——绝不假装一切无虞。
            requires_reconcile = False
            try:
                self._ledger.record(key, nid, venue_ref=_venue_ref_of(val))
            except EffectIdempotencyViolation:
                # 并发竞态：键已被另一执行记上 → 未来 is_consumed 命中、不会再发；但本次与并发方
                # 可能各发了一单（双发已发生）→ 记 CRITICAL 供对账（同 copy_trade executor.py:156-160）。
                logger.critical(
                    "effect 幂等竞态：key=%s node=%s 副作用已执行但记账冲突（疑似并发双发，需对账）", key, nid
                )
            except Exception as exc:  # noqa: BLE001  含 sqlite3.OperationalError（锁超时）
                # 副作用【已执行】但记账失败 → 未来 is_consumed 可能为 False 而重发（M17 雷）。
                # 内核无法回滚已发的单：记 CRITICAL + 标 requires_reconcile，绝不让它看起来「干净成功」。
                logger.critical(
                    "effect 记账失败：key=%s node=%s 副作用已执行但未记账，需对账防重发：%s", key, nid, exc
                )
                requires_reconcile = True
            self._store.put(nid, val)
            # 复核 #2：返回 round-trip 后的工件，保证与幂等复用/重放路径逐字段一致。
            res = NodeRunResult(task.id, nid, "effectful", status="succeeded",
                                result=self._store.get(nid), effect_idempotency_key=key)
            res.requires_reconcile = requires_reconcile
            return res

        # _REPLAY / _FORK：effectful 非正向路径——已消费且有工件才复用，否则一律 HALT，绝不触达券商。
        if consumed and self._store.exists(nid):
            return NodeRunResult(task.id, nid, "effectful", status="reused", reused=True,
                                 result=self._store.get(nid), effect_idempotency_key=key)
        return NodeRunResult(task.id, nid, "effectful", status="halted", halted=True,
                             requires_reconcile=True, effect_idempotency_key=key)

    def _call_op(self, task: DAGTask, context: dict[str, Any]) -> Any:
        if task.op not in self._ops:
            raise KeyError(f"未注册 op: {task.op}")
        return self._ops[task.op](context=context, **task.params)

    def _emit(self, events: list[dict[str, Any]], event: str, node_id: str, task_id: str) -> None:
        rec = {"event": event, "node_id": node_id, "task_id": task_id}
        events.append(rec)
        if self._on_event is not None:
            self._on_event(rec)

    # ── 报告（措辞诚实，R7/dossier §7） ──────────────────────────────────
    @staticmethod
    def render_report(result: KernelRunResult) -> str:
        reused = [n.task_id for n in result.nodes if n.reused]
        halted = [n.task_id for n in result.nodes if n.halted]
        # 措辞黑名单（含 reproducible 的否定式都禁）：此处一律用中文「逐位可重现」表述。
        lines = [
            f"内核 {result.mode} 报告（durable 证据，非逐位可重现承诺）：",
            f"- durable 复用工件（未重跑）：{reused or '无'}",
            f"- effectful 边界截断（halted，未触达券商，待对账）：{halted or '无'}",
            "- 未验证：LLM 节点重跑是否逐位漂移（durable 复用 ≠ 逐位可重现，不作此承诺）。",
        ]
        return "\n".join(lines)


def _descendants(tasks: list[DAGTask], root_id: str) -> set[str]:
    """root_id 的全部下游（传递依赖它的节点）。"""

    children: dict[str, list[str]] = {}
    for t in tasks:
        for d in t.deps:
            children.setdefault(d, []).append(t.id)
    out: set[str] = set()
    stack = list(children.get(root_id, []))
    while stack:
        x = stack.pop()
        if x in out:
            continue
        out.add(x)
        stack.extend(children.get(x, []))
    return out


def _venue_ref_of(val: Any) -> str | None:
    if isinstance(val, dict):
        for k in ("venue_ref", "venue_order_id", "order_id"):
            if val.get(k):
                return str(val[k])
    return None


def derive_effect_key(node_id: str, *dims: str) -> str:
    """确定性派生 effect_idempotency_key（设计开放问题 #2：禁 LLM 直接产 key，否则重跑漂移绕过幂等）。

    用法：effect_idempotency_key = derive_effect_key(node_id, client_order_id) 等。
    """

    return "::".join([node_id, *(str(d) for d in dims)])


__all__ = [
    "DurableExecutor",
    "KernelRunResult",
    "NodeRunResult",
    "compute_node_id",
    "derive_effect_key",
]
