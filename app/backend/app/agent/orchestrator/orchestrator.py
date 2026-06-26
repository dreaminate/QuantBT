"""Agent Orchestrator 核（GOAL §7「Agent Shell→Agent Orchestrator→LLM Gateway→role agent dispatch」）。

把前四件（events / roles / governance / llm_adapter / plan）合成一个编排核：

链路（GOAL §7）：
    Agent Shell → **Agent Orchestrator** → LLM Gateway/ModelRoutingPolicy → role agent dispatch
    → tool/asset/code/math/data ops → 当前台 Canvas 投影 → canonical command → Research Graph

兑现的硬契约：
- **所有 role agent 受 deterministic DAG 管理**：每个 todo 冻结成 `DAGTask`，经 `DurableExecutor`
  跑（pure 节点·durable 复用·replay/fork/rollback）。LLM 永在节点内、绝不当控制器（节点产出不改图结构）。
- **工具只经受治理派发闸**：节点内 role agent 的工具调用全经 `GovernedToolDispatcher`——无节点上下文
  /越权 → 拒（绕过 DAG 自由派发 → 拒）。
- **LLM 全经 LLM Gateway**：role agent 的 LLM 调用经 `GatewayLLMAdapter`（封印 + 落账 + 投影）；
  每条 LLM 结果过 `assert_llm_admissible`（绕过 Gateway 自造 → 不可准入）。
- **写 Research Graph 只经 canonical command**：`propose_graph_write` 唯一图写口 = `graph.apply(command)`。
- **23/24 可见事件投影**到 user 工作流（`EventProjector`）。
- **五形态**：Plan / ReAct / Review / Replay / Repair。

五形态对应方法：`plan()`（Plan）· `dispatch()`（ReAct）·
`admit_verifier_challenge()` / `advise_trust()` / `advise_governance()`（Review）·
`replay()`（Replay）· `repair()`（Repair）。Review 形态三道：`admit_verifier_challenge`（结构独立性）+
`advise_trust`（§13 信任层 **advisory**：反谄媚 / 诚实 / 弱点披露·只标记不阻断·命门仍硬守·见 `trust_advisory.py`）+
`advise_governance`（§8 治理脊柱 **advisory**：七条硬不变量只标记不阻断·secret 不回显·见 `governance_advisory.py`）。

诚实边界（卡面非目标）：不建前端工作流可视化（事件后端投影即可）；不重建 LLM Gateway（已建·只调）；
record/replay store 的深接线（RecordingLLMClient fixture 后端）另卡——本核的 Replay 形态依赖 **kernel
durable 工件复用**（真·零重跑）+ gateway 的 replay_state 标注，fixture 后端接线作为诚实残余上报。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..agent_runtime import AgentRuntime
from ...dag.engine import DAGTask
from ...dag.kernel import DurableExecutor, KernelRunResult
from ...llm.call_record import LLMCallRecord, evaluate_independence, IndependenceVerdict
from ...llm.gateway import GatewaySealedResult, LLMGateway
from ...graph.research_graph import (
    CanonicalCommand,
    COMMAND_TYPES,
    ResearchGraph,
)
from ...qro.envelope import (
    ACTOR_AGENT,
    ACTOR_SCHEDULED_AGENT,
    ACTOR_USER_CONFIRMED_AGENT,
)
from .events import (
    EV_AGENT_PLAN_CREATED,
    EV_APPROVAL_REQUESTED,
    EV_ARTIFACT_PRODUCED,
    EV_ASSET_DIFF_CREATED,
    EV_ASSET_READ,
    EV_CANONICAL_COMMAND_APPLIED,
    EV_CANONICAL_COMMAND_PROPOSED,
    EV_DESK_HANDOFF_CREATED,
    EV_FAILURE_DETECTED,
    EV_RAG_HIT_USED,
    EV_REPAIR_ATTEMPTED,
    EV_ROLE_AGENT_DISPATCHED,
    EV_RUN_VERDICT_PRODUCED,
    EV_TODO_UPDATED,
    EV_TOOL_CALL_FINISHED,
    EV_TOOL_CALL_STARTED,
    EV_VALIDATION_FINISHED,
    EV_VALIDATION_STARTED,
    EV_VERIFIER_CHALLENGE_RAISED,
    EventProjector,
    WorkflowEvent,
)
from .governance import (
    DAGBypassError,
    GovernedToolDispatcher,
    NodeExecutionContext,
    ToolHandler,
)
from .llm_adapter import GatewayLLMAdapter, assert_llm_admissible
from .plan import (
    AcceptanceGate,
    AgentCodeChange,
    AgentCompletion,
    AgentCompletionError,
    AgentPlan,
    AgentTodo,
    MethodologyChoiceRecord,
    PlanError,
    assert_methodology_user_decided,
)
from .roles import (
    ROLE_VERIFIER,
    TOOL_RAG_SEARCH,
    TOOL_RAISE_CHALLENGE,
    TOOL_READ_ASSET,
    get_role,
)
from ...governance import GovernanceSpineGate, SpineEvidence
from ...trust import TrustContext
from .governance_advisory import GovernanceAdvisory, run_governance_advisory
from .trust_advisory import TrustAdvisory, run_trust_advisory

# orchestrator 投放进 kernel context 的句柄键（context 只携非身份基础设施句柄·见 kernel 契约）。
ORCH_CONTEXT_KEY = "_agent_orchestrator_bundle"
ROLE_NODE_OP = "orchestrator_role_node"

MODE_PLAN = "plan"
MODE_REACT = "react"
MODE_REVIEW = "review"
MODE_REPLAY = "replay"
MODE_REPAIR = "repair"
MODES: tuple[str, ...] = (MODE_PLAN, MODE_REACT, MODE_REVIEW, MODE_REPLAY, MODE_REPAIR)

# agent 动作写图允许的 actor 类（GOAL §0/§7：agent 动作如实标来源，绝不冒充 user_manual）。
_AGENT_WRITE_ACTORS: frozenset[str] = frozenset(
    {ACTOR_AGENT, ACTOR_USER_CONFIRMED_AGENT, ACTOR_SCHEDULED_AGENT}
)

# 工具→语义事件映射（GOAL §7 工具/资产/验证投影）：派发闸 on_event 据此投影。
_VALIDATION_TOOLS: frozenset[str] = frozenset(
    {"run_validation", "run_backtest", "compute_ic", "quality_check", "risk_check", "check_consistency"}
)
_DIFF_TOOLS: frozenset[str] = frozenset(
    {"define_factor", "write_math", "build_strategybook", "train_model", "define_signal",
     "write_report", "model_card", "register_data"}
)


class OrchestratorError(RuntimeError):
    pass


class VerifierIndependenceError(OrchestratorError):
    """Verifier 与 Builder 共用同一输出上下文却未标独立性不足（声称独立）→ 拒（GOAL §7）。"""


class GraphWriteAuthorityError(OrchestratorError):
    """图写入 actor 非 agent 动作类（冒充 user_manual / 非法）→ 拒（GOAL §7 写图按来源如实标）。"""


@dataclass
class _OrchBundle:
    """投进 kernel context 的非身份基础设施句柄包（kernel 契约：context 不入 node_id 哈希）。"""

    gateway: LLMGateway
    dispatcher: GovernedToolDispatcher
    projector: EventProjector
    tool_handlers: dict[str, dict[str, ToolHandler]]
    session_id: str
    replay_mode: str
    max_steps: int
    requires_tool_evidence: dict[str, bool]
    sealed_results: list[tuple[str, str, GatewaySealedResult]] = field(default_factory=list)

    def record_sealed(self, task_id: str, role: str, sealed: GatewaySealedResult) -> None:
        self.sealed_results.append((task_id, role, sealed))


@dataclass
class OrchestrationResult:
    kernel_result: KernelRunResult
    events: tuple[WorkflowEvent, ...]
    node_artifacts: dict[str, Any]
    sealed_results: list[tuple[str, str, GatewaySealedResult]]
    succeeded: bool

    def record_for(self, task_id: str) -> LLMCallRecord | None:
        for tid, _role, sealed in self.sealed_results:
            if tid == task_id:
                return sealed.record
        return None

    def event_kinds(self) -> list[str]:
        return [e.kind for e in self.events]


# ───────────────────────── role 节点 op（在 deterministic DAG 内执行一个 role agent）─────────────
def role_node_op(
    *,
    context: dict[str, Any],
    role: str,
    task_id: str,
    instruction: str,
    permitted_tools: list[str],
    difficulty: str,
    risk: str,
    independence: bool,
) -> dict[str, Any]:
    """一个 role agent 在冻结 DAG 节点内的受治理执行（GOAL §7）。

    node_id（治理身份）= task_id（todo id）。LLM 经 Gateway；工具经治理闸（计划外工具即拒并记 violation）；
    跑完查 violation 非空 → raise（kernel 判节点 failed → FailureDetected）；查完成门（声称完成却无工具
    记录 → 拒）；产 artifact。**wrap AgentRuntime·不改其内部**（注入 gateway-backed llm + 注册受治理工具）。
    """

    bundle: _OrchBundle = context[ORCH_CONTEXT_KEY]
    gateway = bundle.gateway
    dispatcher = bundle.dispatcher
    projector = bundle.projector
    role_agent = get_role(role)
    permitted = frozenset(permitted_tools)
    node_id = task_id

    projector.emit(
        EV_ROLE_AGENT_DISPATCHED,
        {"role": role, "task_id": task_id, "home_desk": role_agent.home_desk,
         "permitted_tools": sorted(permitted), "independence_required": bool(independence)},
        role=role, desk=role_agent.home_desk, node_id=node_id,
    )

    capability = role_agent.capability(
        difficulty=difficulty, risk=risk, independence_required=independence,
    )
    adapter = GatewayLLMAdapter(
        gateway, capability,
        session_id=bundle.session_id, replay_mode=bundle.replay_mode,
        on_sealed=lambda s: bundle.record_sealed(task_id, role, s),
    )
    runtime = AgentRuntime(
        llm=adapter,
        max_steps=bundle.max_steps,
        system_prompt=f"You are QuantBT {role} role agent. 在受控权限与 deterministic DAG 内工作。",
    )

    ctx = dispatcher.enter_node(node_id=node_id, task_id=task_id, role=role, permitted_tools=permitted)
    handlers = bundle.tool_handlers.get(role, {})
    # 真 handler 注册进治理闸的注册表；被 wrap 的 AgentRuntime 只拿到「绑定本节点 ctx」的转交闭包。
    # **权限在 dispatch 期由治理闸 authoritative 裁决**（即便误注册一个白名单外工具，dispatch 也拒并
    # 记 violation·防御纵深）——绝不让计划外工具真执行；runtime 内任何工具调用都必经治理闸。
    for tool_name, handler in handlers.items():
        dispatcher.register(tool_name, handler)
        runtime.register_tool(tool_name, dispatcher.bind_node_tool(ctx, tool_name))
    try:
        turn = runtime.run(instruction)
    finally:
        dispatcher.exit_node(ctx)

    # adopt LLM Gateway 5 枚事件进统一流 + 每条 LLM 结果做图准入（绕过 Gateway 自造 → 不可准入）。
    for tid, _r, sealed in bundle.sealed_results:
        if tid != task_id:
            continue
        projector.adopt_gateway_events(sealed.events, role=role, desk=role_agent.home_desk, node_id=node_id)
        assert_llm_admissible(sealed, gateway)

    # 绕过 DAG 自由派发 / 越权 → violation 非空 → raise（节点 failed·FailureDetected）。
    violations = dispatcher.drain_violations(node_id)
    if violations:
        projector.emit(
            EV_FAILURE_DETECTED,
            {"reason": "tool_dispatch_violation", "violations": [v.kind for v in violations],
             "detail": [v.reason for v in violations]},
            role=role, node_id=node_id,
        )
        raise DAGBypassError(
            f"节点 {task_id!r} 检出 {len(violations)} 次越界工具派发（绕过 DAG/越权·GOAL §7 → 节点拒）："
            f"{[v.kind for v in violations]}"
        )

    tool_records = dispatcher.records_for(node_id)
    # 完成门（GOAL §7：声称完成但工具记录缺失 → 拒）。
    try:
        AgentCompletion(
            role=role,
            claims_complete=turn.succeeded,
            tool_records=tuple(r.tool for r in tool_records),
            requires_tool_evidence=bundle.requires_tool_evidence.get(task_id, True),
        )
    except AgentCompletionError as exc:
        projector.emit(EV_FAILURE_DETECTED, {"reason": "completion_without_tool_record", "role": role},
                       role=role, node_id=node_id)
        raise

    artifact = {
        "role": role,
        "task_id": task_id,
        "final_message": turn.final_message,
        "succeeded": turn.succeeded,
        "tool_records": [r.to_dict() for r in tool_records],
        "llm_call_ids": [s.record.call_id for tid, _r, s in bundle.sealed_results if tid == task_id],
    }
    projector.emit(
        EV_ARTIFACT_PRODUCED,
        {"task_id": task_id, "role": role, "n_tool_calls": len(tool_records),
         "n_llm_calls": len(artifact["llm_call_ids"])},
        role=role, desk=role_agent.home_desk, node_id=node_id,
    )
    return artifact


def make_executor(root: Path | str, **kwargs: Any) -> DurableExecutor:
    """造一个已注册 role 节点 op 的 DurableExecutor（run 与 replay 须用指向同一 store 的执行器）。"""

    return DurableExecutor(root, ops={ROLE_NODE_OP: role_node_op}, **kwargs)


# ───────────────────────────────── Orchestrator 核 ──────────────────────────────────────────
class AgentOrchestrator:
    """统一编排核（GOAL §7）。持有 LLM Gateway（唯一 LLM 入口·只调不重建）+ 受治理派发闸 + 事件投影器
    + （可选）Research Graph（唯一图写口 = canonical command）。"""

    def __init__(
        self,
        *,
        gateway: LLMGateway,
        research_graph: ResearchGraph | None = None,
        session_id: str = "orch-session",
        secret_values: tuple[str, ...] = (),
    ) -> None:
        self._gateway = gateway
        self._graph = research_graph
        self._session = session_id
        self._projector = EventProjector(secret_values=secret_values)
        # 派发闸的 on_event → 投影 ToolCallStarted/Finished + 语义事件（AssetRead/RagHitUsed/...）。
        self._dispatcher = GovernedToolDispatcher(on_event=self._tool_event_hook)

    # —— 公共只读句柄 ——
    @property
    def gateway(self) -> LLMGateway:
        return self._gateway

    @property
    def dispatcher(self) -> GovernedToolDispatcher:
        return self._dispatcher

    @property
    def projector(self) -> EventProjector:
        return self._projector

    @property
    def events(self) -> tuple[WorkflowEvent, ...]:
        return self._projector.events

    # —— 工具→语义事件投影（GOAL §7 工具/资产/验证可见）——
    def _tool_event_hook(self, phase: str, data: dict[str, Any], ctx: NodeExecutionContext) -> None:
        tool = data.get("tool", "")
        if phase == "started":
            self._projector.emit(EV_TOOL_CALL_STARTED, {"tool": tool}, role=ctx.role, node_id=ctx.node_id)
            if tool in _VALIDATION_TOOLS:
                self._projector.emit(EV_VALIDATION_STARTED, {"tool": tool}, role=ctx.role, node_id=ctx.node_id)
            return
        # finished
        ok = bool(data.get("ok", True))
        if tool == TOOL_READ_ASSET:
            self._projector.emit(EV_ASSET_READ, {"tool": tool}, role=ctx.role, node_id=ctx.node_id)
        if tool == TOOL_RAG_SEARCH:
            self._projector.emit(EV_RAG_HIT_USED, {"tool": tool}, role=ctx.role, node_id=ctx.node_id)
        if tool in _DIFF_TOOLS:
            self._projector.emit(EV_ASSET_DIFF_CREATED, {"tool": tool}, role=ctx.role, node_id=ctx.node_id)
        if tool in _VALIDATION_TOOLS:
            self._projector.emit(EV_VALIDATION_FINISHED, {"tool": tool, "ok": ok}, role=ctx.role, node_id=ctx.node_id)
        if tool == TOOL_RAISE_CHALLENGE:
            self._projector.emit(EV_VERIFIER_CHALLENGE_RAISED, {"tool": tool}, role=ctx.role, node_id=ctx.node_id)
        self._projector.emit(EV_TOOL_CALL_FINISHED, {"tool": tool, "ok": ok}, role=ctx.role, node_id=ctx.node_id)

    # ───────────────────────── Plan 形态 ─────────────────────────
    def plan(
        self,
        goal: str,
        *,
        todos: list[AgentTodo],
        dependencies: dict[str, list[str]],
        risk_list: list[str] | None = None,
        acceptance_gates: list[AcceptanceGate] | None = None,
        cross_desk_handoff_plan: list[dict[str, Any]] | None = None,
        rollback_points: list[str] | None = None,
    ) -> AgentPlan:
        """Plan 形态（GOAL §7）：产 todo/deps/risk/gates/handoff/rollback。缺 todo/deps/gates → 维持 draft。"""

        plan = AgentPlan(
            goal=goal,
            todos=list(todos),
            dependencies=dict(dependencies),
            risk_list=list(risk_list or []),
            acceptance_gates=list(acceptance_gates or []),
            cross_desk_handoff_plan=list(cross_desk_handoff_plan or []),
            rollback_points=list(rollback_points or []),
        )
        plan.validate()
        self._projector.emit(
            EV_AGENT_PLAN_CREATED,
            {"goal": goal, "status": plan.status, "n_todos": len(plan.todos),
             "n_gates": len(plan.acceptance_gates), "draft_reason": plan.draft_reason},
        )
        for t in plan.todos:
            self._projector.emit(EV_TODO_UPDATED, {"todo_id": t.todo_id, "role": t.role, "deps": list(t.deps)})
        return plan

    # ───────────────────────── ReAct 形态（DAG dispatch）─────────────────────────
    def build_dag(self, plan: AgentPlan, *, instructions: dict[str, str] | None = None) -> list[DAGTask]:
        """把就绪 plan 冻结成 deterministic DAG（每 todo 一个 pure 节点·deps 即 plan.dependencies）。"""

        if not plan.is_ready:
            raise PlanError(
                f"plan 未就绪（{plan.status}：{plan.draft_reason}）——draft 不晋升为可执行 DAG（GOAL §7）"
            )
        instructions = instructions or {}
        tasks: list[DAGTask] = []
        for todo in plan.todos:
            role_agent = get_role(todo.role)
            tasks.append(DAGTask(
                id=todo.todo_id,
                op=ROLE_NODE_OP,
                params={
                    "role": todo.role,
                    "task_id": todo.todo_id,
                    "instruction": instructions.get(todo.todo_id, todo.description),
                    "permitted_tools": sorted(role_agent.permitted_tools),
                    "difficulty": role_agent.default_difficulty,
                    "risk": role_agent.default_risk,
                    "independence": role_agent.independence_capable,
                },
                deps=list(plan.dependencies.get(todo.todo_id, [])),
                kind="pure",
            ))
        return tasks

    def dispatch(
        self,
        plan: AgentPlan,
        *,
        executor: DurableExecutor,
        tool_handlers: dict[str, dict[str, ToolHandler]] | None = None,
        instructions: dict[str, str] | None = None,
        max_steps: int = 4,
        requires_tool_evidence: dict[str, bool] | None = None,
    ) -> OrchestrationResult:
        """ReAct 形态（GOAL §7）：在 deterministic DAG 内串/并行跑 role agent。

        `executor` 须由 `make_executor(root)` 造（已注册 role 节点 op）；run 与后续 replay 须用同一执行器。
        """

        tasks = self.build_dag(plan, instructions=instructions)
        bundle = _OrchBundle(
            gateway=self._gateway, dispatcher=self._dispatcher, projector=self._projector,
            tool_handlers=tool_handlers or {}, session_id=self._session, replay_mode="live",
            max_steps=max_steps, requires_tool_evidence=requires_tool_evidence or {},
        )
        kr = executor.run(tasks, {ORCH_CONTEXT_KEY: bundle})
        return self._finish_run(kr, bundle)

    # ───────────────────────── Replay 形态 ─────────────────────────
    def replay(
        self,
        plan: AgentPlan,
        *,
        executor: DurableExecutor,
        instructions: dict[str, str] | None = None,
        tool_handlers: dict[str, dict[str, ToolHandler]] | None = None,
        max_steps: int = 4,
        requires_tool_evidence: dict[str, bool] | None = None,
    ) -> OrchestrationResult:
        """Replay 形态（GOAL §7）：读已落账 run/artifact。命中 kernel durable 工件 → 节点复用、**零重跑**
        （op 不被调用·零 LLM·零工具派发）。诚实残余：fixture 后端（RecordingLLMClient）深接线另卡。"""

        tasks = self.build_dag(plan, instructions=instructions)
        bundle = _OrchBundle(
            gateway=self._gateway, dispatcher=self._dispatcher, projector=self._projector,
            tool_handlers=tool_handlers or {}, session_id=self._session, replay_mode="replay",
            max_steps=max_steps, requires_tool_evidence=requires_tool_evidence or {},
        )
        kr = executor.replay(tasks, {ORCH_CONTEXT_KEY: bundle})
        return self._finish_run(kr, bundle)

    def _finish_run(self, kr: KernelRunResult, bundle: _OrchBundle) -> OrchestrationResult:
        node_artifacts = {n.task_id: n.result for n in kr.nodes}
        self._projector.emit(
            EV_RUN_VERDICT_PRODUCED,
            {"succeeded": kr.succeeded, "mode": kr.mode,
             "n_nodes": len(kr.nodes),
             "reused": [n.task_id for n in kr.nodes if n.reused],
             "failed": [n.task_id for n in kr.nodes if n.status in ("failed", "halted", "skipped")]},
        )
        return OrchestrationResult(
            kernel_result=kr,
            events=self._projector.events,
            node_artifacts=node_artifacts,
            sealed_results=list(bundle.sealed_results),
            succeeded=kr.succeeded,
        )

    # ───────────────────────── Review 形态（Verifier 独立性）─────────────────────────
    def admit_verifier_challenge(
        self, builder: LLMCallRecord, verifier: LLMCallRecord
    ) -> IndependenceVerdict:
        """Review 形态门（GOAL §7：Verifier 与 Builder 共用同一输出上下文且未标独立性不足 → 拒）。

        裁决复用 gateway 的 `evaluate_independence`（单一源）。共用上下文（同 provider+model）却声称独立
        （satisfied=True）→ 假独立 → 拒。共用上下文但**诚实标 satisfied=False** → 不抛，返回「挑战但独立
        性不足」裁决（honest·非干净独立）。投影 VerifierChallengeRaised。
        """

        verdict = evaluate_independence(builder, verifier)
        self._projector.emit(
            EV_VERIFIER_CHALLENGE_RAISED,
            {"independent": verdict.independent, "reason": verdict.reason,
             "claimed_satisfied": bool(verifier.independence.satisfied)},
            role="verifier_critic",
        )
        shares_context = (builder.provider == verifier.provider and builder.model == verifier.model)
        if shares_context and not verdict.independent and verifier.independence.satisfied:
            raise VerifierIndependenceError(
                "Verifier 与 Builder 共用同一输出上下文（同 provider+model）却声称独立"
                f"（未标独立性不足）——GOAL §7 → 拒：{verdict.reason}"
            )
        return verdict

    def advise_trust(
        self,
        ctx: TrustContext,
        *,
        role: str = ROLE_VERIFIER,
        node_id: str = "",
        target_ref: str = "",
    ) -> TrustAdvisory:
        """Review 形态 · §13 信任层 **advisory**（GOAL §13 + §7）——把第八波 `trust/` 门接进 agent 审查路径。

        对一条待审 agent 产出（研究结论 / 推荐 / review·由 `ctx: TrustContext` 描述其 §13 姿态）跑信任层
        全部硬约束门。**判定零重写**：全权委派 `app.trust.evaluate_trust`（reuse·本层只接线 + 投影）。

        advisory-first（本波纪律）：诚实 / 反谄媚 / 弱点披露 / 责任 / 用户自主等**软门**只**标记**
        （`TrustAdvisory.flagged`）+ 投影一枚 `VerifierChallengeRaised`，**绝不阻断**本编排核既有主流程
        （不改 dispatch/plan/replay/repair 行为·不 block agent）。硬卡 agent = 后续显式决策。

        命门例外（**不在此削弱**·复用 trust 命门）：若 `ctx` 路径带 waiver 触及安全不变量
        （secret / OrderGuard / kill switch / no-silent-mock），`evaluate_trust` 内部 `raise SafetyWaiverError`
        —— 本方法**不吞**（吞 = 把 fail-closed 硬墙降级成 advisory = 削弱命门），投影 `FailureDetected`
        （只投不变量名）后**原样抛出**。安全不变量不在 advisory 域。
        """

        return run_trust_advisory(
            ctx, self._projector, role=role, node_id=node_id, target_ref=target_ref
        )

    def advise_governance(
        self,
        evidence: SpineEvidence,
        *,
        gate: GovernanceSpineGate | None = None,
        role: str = ROLE_VERIFIER,
        node_id: str = "",
        node_ref: str = "",
    ) -> GovernanceAdvisory:
        """Review 形态 · §8 治理脊柱 **advisory**（GOAL §8 治理脊柱 + §7）。

        把 `GovernanceSpineGate` 接进 agent 审查路径。调用方显式构造 `SpineEvidence` 描述待审动作的
        §8 姿态；本方法只做接线和事件投影，判定全权委派 `GovernanceSpineGate.evaluate`。

        advisory-first：canvas / agent_action / plan / code_change / role_action / secret / data_access 任一违反
        只标记 `GovernanceAdvisory.flagged` 并投影 `VerifierChallengeRaised`，不阻断现有 plan / dispatch /
        replay / repair 主流程。硬 enforce 留给后续显式决策。

        secret 可见性边界：`GovernanceSpineGate.evaluate` 当前对 secret 违反返回 `SpineVerdict(allowed=False)`；
        接线层只投 clause id 和计数，不投 evidence surface / verdict_text / violation 文本。若未来底层门以
        `SecretLeakError` 硬停，本层不吞，投不变量名后原样抛出。
        """

        return run_governance_advisory(
            evidence, self._projector, gate=gate, role=role, node_id=node_id, node_ref=node_ref
        )

    # ───────────────────────── Repair 形态 ─────────────────────────
    def repair(self, *, failure_ref: str, code_change: AgentCodeChange) -> AgentCodeChange:
        """Repair 形态（GOAL §7）：定位失败 + 提交修复 diff。`AgentCodeChange` 构造已强制 diff/test/rollback
        （缺即拒）；这里只投影 FailureDetected + RepairAttempted。"""

        self._projector.emit(EV_FAILURE_DETECTED, {"failure_ref": failure_ref, "mode": MODE_REPAIR})
        self._projector.emit(
            EV_REPAIR_ATTEMPTED,
            {"failure_ref": failure_ref, "path": code_change.path,
             "has_diff": bool(code_change.diff), "has_test": bool(code_change.test_result),
             "has_rollback": bool(code_change.rollback_point)},
        )
        return code_change

    # ───────────────────────── 方法学放权（决定权属 user）─────────────────────────
    def record_methodology_choice(self, record: MethodologyChoiceRecord) -> MethodologyChoiceRecord:
        """登记一条方法学放权（GOAL §7）：投影 ApprovalRequested（请 user 拍板·agent 不替决）。"""

        self._projector.emit(
            EV_APPROVAL_REQUESTED,
            {"choice": record.choice, "decided_by": record.decided_by, "decision": record.decision,
             "cost": record.cost, "responsibility_boundary": record.responsibility_boundary},
        )
        return record

    def apply_methodology_choice(self, record: MethodologyChoiceRecord) -> MethodologyChoiceRecord:
        """执行一条方法学放权——decided_by 是 agent/scheduled_agent 自拍 → 拒（GOAL §7：Agent 替 user 拍板
        方法学松紧 → 拒）。只有 user 手动 / user 确认过的动作可 accept。"""

        assert_methodology_user_decided(record)
        return record

    # ───────────────────────── 写 Research Graph（唯一口 = canonical command）─────────────────────────
    def propose_graph_write(
        self,
        *,
        command_type: str,
        actor: str,
        target_desk: str,
        payload: dict[str, Any],
        origin: str = "agent",
    ) -> Any:
        """role agent 写 Research Graph 的**唯一**口（GOAL §7：只经 canonical command 写图）。

        actor 必须是 agent 动作类（agent / user_confirmed_agent / scheduled_agent）——绝不冒充 user_manual。
        构造 `CanonicalCommand`（落点信封自带四类 actor / 命令类型 / 台校验）→ 投影 Proposed →
        `graph.apply(command)`（图的唯一公共写口）→ 投影 Applied。无第二条裸写路径。
        """

        if actor not in _AGENT_WRITE_ACTORS:
            raise GraphWriteAuthorityError(
                f"agent 写图 actor={actor!r} 非 agent 动作类 {sorted(_AGENT_WRITE_ACTORS)}——"
                "agent 动作绝不冒充 user_manual / 非法来源（GOAL §0/§7 写图按来源如实标）"
            )
        if command_type not in COMMAND_TYPES:
            raise OrchestratorError(f"command_type 非法：{command_type!r} ∉ {sorted(COMMAND_TYPES)}")
        if self._graph is None:
            raise OrchestratorError("orchestrator 未挂 Research Graph——无法落 canonical command 写图")

        command = CanonicalCommand(
            command_type=command_type, actor=actor, target_desk=target_desk,
            payload=payload, origin=origin,
        )
        self._projector.emit(
            EV_CANONICAL_COMMAND_PROPOSED,
            {"command_id": command.command_id, "command_type": command_type,
             "target_desk": target_desk, "actor": actor, "origin": origin},
            desk=target_desk,
        )
        result = self._graph.apply(command)
        self._projector.emit(
            EV_CANONICAL_COMMAND_APPLIED,
            {"command_id": command.command_id, "command_type": command_type, "target_desk": target_desk},
            desk=target_desk,
        )
        return result

    def open_handoff(self, *, handoff: Any, actor: str = ACTOR_AGENT) -> Any:
        """开一条跨台交接（GOAL §7 cross-desk handoff）——经 canonical command 落图 + 投影 DeskHandoffCreated。"""

        from ...graph.research_graph import CMD_OPEN_HANDOFF

        result = self.propose_graph_write(
            command_type=CMD_OPEN_HANDOFF, actor=actor,
            target_desk=handoff.from_desk, payload={"handoff": handoff}, origin="agent",
        )
        self._projector.emit(
            EV_DESK_HANDOFF_CREATED,
            {"from_desk": handoff.from_desk, "to_desk": handoff.to_desk,
             "requested_asset": handoff.requested_asset},
            desk=handoff.from_desk,
        )
        return result


__all__ = [
    "AgentOrchestrator",
    "OrchestrationResult",
    "OrchestratorError",
    "VerifierIndependenceError",
    "GraphWriteAuthorityError",
    "ORCH_CONTEXT_KEY",
    "ROLE_NODE_OP",
    "MODES",
    "MODE_PLAN",
    "MODE_REACT",
    "MODE_REVIEW",
    "MODE_REPLAY",
    "MODE_REPAIR",
    "role_node_op",
    "make_executor",
]
