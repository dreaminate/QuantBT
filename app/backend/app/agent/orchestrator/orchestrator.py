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

import hashlib
import json
import threading
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, Callable

from ..agent_runtime import (
    AgentRAGContextProvider,
    AgentRuntime,
    AgentTurn,
)
from ..tool_schema import TOOL_SCHEMA
from ...dag.engine import DAGTask
from ...dag.kernel import DurableExecutor, KernelRunResult
from ...llm.call_record import (
    IndependenceVerdict,
    LLMCallRecord,
    ReviewSubjectBinding,
    bind_review_verifier_record,
    evaluate_independence,
    make_review_subject_binding,
    validate_review_subject_binding,
)
from ...llm.gateway import GatewaySealedResult, LLMGateway
from ...llm.model_identity import has_independent_model_route
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
from ...research_os.spine import EntrySource, ResearchGraphStore
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
    PersistentWorkflowEventLedger,
    WorkflowEvent,
)
from .capability_ledger import (
    CAPABILITY_PLAN,
    CAPABILITY_REACT,
    CAPABILITY_REPAIR,
    CAPABILITY_REPLAY,
    CAPABILITY_REVIEW,
    AgentCapabilityCommitUncertain,
    PersistentAgentCapabilityLedger,
    capability_path_for_event_ledger,
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
    PLAN_DRAFT,
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


class VerifierIndependenceUnavailable(OrchestratorError):
    """No configured provider/model route can independently challenge the builder."""


class GraphWriteAuthorityError(OrchestratorError):
    """图写入 actor 非 agent 动作类（冒充 user_manual / 非法）→ 拒（GOAL §7 写图按来源如实标）。"""


def _identity_scope_ref(owner_user_id: str, workflow_id: str) -> str:
    """Bind durable node identity to owner/workflow without persisting either plaintext value."""

    owner = str(owner_user_id or "").strip()
    workflow = str(workflow_id or "").strip()
    if not owner or not workflow:
        return ""
    return hashlib.sha256(f"{owner}\x00{workflow}".encode("utf-8")).hexdigest()


def _role_task_scope_ref(
    *,
    role: str,
    task_id: str,
    instruction: str,
    permitted_tools: list[str],
    difficulty: str,
    risk: str,
    independence: bool,
    identity_scope_ref: str,
    runtime_context_ref: str,
    execution_variant_ref: str = "",
    review_subject_task_id: str = "",
) -> str:
    payload = {
        "role": str(role),
        "task_id": str(task_id),
        "instruction": str(instruction),
        "permitted_tools": sorted(str(tool) for tool in permitted_tools),
        "difficulty": str(difficulty),
        "risk": str(risk),
        "independence": bool(independence),
        "identity_scope_ref": str(identity_scope_ref),
        "runtime_context_ref": str(runtime_context_ref),
    }
    if execution_variant_ref:
        payload["execution_variant_ref"] = str(execution_variant_ref)
    if review_subject_task_id:
        payload["review_subject_task_id"] = str(review_subject_task_id)
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _audit_digest(value: Any) -> str:
    """Hash an ephemeral value for durable audit metadata without persisting plaintext."""

    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _tool_schema_name(schema: dict[str, Any]) -> str:
    return str(schema.get("name") or schema.get("function", {}).get("name") or "").strip()


def _role_filtered_tool_schema(
    *,
    permitted_tools: frozenset[str],
    registered_handlers: dict[str, ToolHandler],
    schema_catalog: tuple[dict[str, Any], ...],
) -> tuple[dict[str, Any], ...]:
    """Return only schemas backed by a real registered handler and allowed for the role."""

    live_names = permitted_tools.intersection(registered_handlers)
    return tuple(
        schema
        for schema in schema_catalog
        if _tool_schema_name(schema) in live_names
    )


@dataclass(frozen=True)
class AgentRuntimeContext:
    """Typed, ephemeral inputs forwarded to the role node's ``AgentRuntime``.

    Callable/store handles are deliberately excluded from dataclass comparison and repr. Durable
    node identity receives only a non-plaintext digest derived from execution-relevant primitive
    values, registered tool names, the filtered schema, and handle-presence flags.
    """

    translator: Any | None = field(default=None, repr=False, compare=False)
    permission_mode: str = "auto"
    research_graph: ResearchGraphStore | None = field(default=None, repr=False, compare=False)
    entry_source: EntrySource | str = EntrySource.AGENT_SHELL
    actor: str = "agent_orchestrator"
    owner: str = ""
    rag_context_provider: AgentRAGContextProvider | None = field(
        default=None, repr=False, compare=False
    )
    system_prompt: str | None = field(default=None, repr=False)
    tool_schema: tuple[dict[str, Any], ...] | None = field(default=None, repr=False)

    def __post_init__(self) -> None:
        if self.permission_mode not in {"ask", "auto", "bypass"}:
            raise ValueError("permission_mode must be one of: ask, auto, bypass")
        if not str(self.actor or "").strip():
            raise ValueError("runtime context actor is required")
        if self.tool_schema is not None:
            object.__setattr__(self, "tool_schema", tuple(self.tool_schema))

    def schema_catalog(self) -> tuple[dict[str, Any], ...]:
        return tuple(TOOL_SCHEMA) if self.tool_schema is None else self.tool_schema


def _runtime_context_ref(
    *,
    runtime_context: AgentRuntimeContext,
    role: str,
    registered_tool_names: frozenset[str],
    role_tool_schema: tuple[dict[str, Any], ...],
    resolved_system_prompt: str,
) -> str:
    entry_source = runtime_context.entry_source
    entry_source_value = entry_source.value if isinstance(entry_source, EntrySource) else str(entry_source)
    return _audit_digest(
        {
            "role": role,
            "permission_mode": runtime_context.permission_mode,
            "entry_source": entry_source_value,
            "actor": runtime_context.actor,
            "owner": runtime_context.owner,
            "system_prompt_digest": _audit_digest(resolved_system_prompt),
            "tool_schema_digest": _audit_digest(role_tool_schema),
            "registered_tool_names": sorted(registered_tool_names),
            "translator_bound": runtime_context.translator is not None,
            "research_graph_bound": runtime_context.research_graph is not None,
            "rag_context_provider_bound": runtime_context.rag_context_provider is not None,
        }
    )


@dataclass
class _OrchBundle:
    """Kernel context handles plus identity checked against each frozen DAG task scope."""

    gateway: LLMGateway
    dispatcher: GovernedToolDispatcher
    projector: EventProjector
    tool_handlers: dict[str, dict[str, ToolHandler]]
    session_id: str
    owner_user_id: str
    workflow_id: str
    identity_scope_ref: str
    replay_mode: str
    max_steps: int
    requires_tool_evidence: dict[str, bool]
    runtime_context: AgentRuntimeContext
    record_sink: Callable[[LLMCallRecord], None] | None = None
    sealed_results: list[tuple[str, str, GatewaySealedResult]] = field(default_factory=list)
    live_turns: dict[str, AgentTurn] = field(default_factory=dict)
    node_artifacts: dict[str, dict[str, Any]] = field(default_factory=dict)
    review_subject_bindings: dict[str, ReviewSubjectBinding] = field(default_factory=dict)
    _invocation_steps: dict[str, int] = field(default_factory=dict)
    _invocation_lock: threading.Lock = field(default_factory=threading.Lock)
    _live_turn_lock: threading.Lock = field(default_factory=threading.Lock)
    _review_lock: threading.Lock = field(default_factory=threading.Lock)

    def record_sealed(self, task_id: str, role: str, sealed: GatewaySealedResult) -> None:
        self.sealed_results.append((task_id, role, sealed))

    def record_live_turn(self, task_id: str, turn: AgentTurn) -> None:
        """Keep the plaintext turn only in this run's in-memory context."""

        with self._live_turn_lock:
            self.live_turns[task_id] = turn

    def record_node_artifact(self, task_id: str, artifact: dict[str, Any]) -> None:
        with self._review_lock:
            self.node_artifacts[task_id] = dict(artifact)

    def record_review_subject_binding(
        self, task_id: str, binding: ReviewSubjectBinding
    ) -> None:
        with self._review_lock:
            self.review_subject_bindings[task_id] = binding

    def review_subject_evidence(
        self, task_id: str
    ) -> tuple[LLMCallRecord, AgentTurn, dict[str, Any]]:
        with self._review_lock:
            turn = self.live_turns.get(task_id)
            artifact = self.node_artifacts.get(task_id)
        records = [
            sealed.record
            for sealed_task_id, _role, sealed in self.sealed_results
            if sealed_task_id == task_id
        ]
        if turn is None or artifact is None or not records:
            raise OrchestratorError(
                "review subject requires live builder output, terminal call, and role artifact"
            )
        return records[-1], turn, dict(artifact)

    def next_invocation_id(self, task_scope_ref: str) -> str:
        """Return a stable per-task LLM invocation id without exposing owner/workflow text."""

        task_key = str(task_scope_ref or "").strip()
        if not task_key:
            raise OrchestratorError("role task invocation scope is required")
        with self._invocation_lock:
            step = self._invocation_steps.get(task_key, 0) + 1
            self._invocation_steps[task_key] = step
        return f"orch:{task_key[:24]}:step:{step}"


@dataclass
class OrchestrationResult:
    kernel_result: KernelRunResult
    events: tuple[WorkflowEvent, ...]
    node_artifacts: dict[str, Any]
    sealed_results: list[tuple[str, str, GatewaySealedResult]]
    live_turns: dict[str, AgentTurn]
    review_subject_bindings: dict[str, ReviewSubjectBinding]
    succeeded: bool
    verdict_event_ref: str = ""

    def record_for(self, task_id: str) -> LLMCallRecord | None:
        for tid, _role, sealed in self.sealed_results:
            if tid == task_id:
                return sealed.record
        return None

    def event_kinds(self) -> list[str]:
        return [e.kind for e in self.events]

    def live_final_message_for(self, task_id: str) -> str | None:
        """Return a live plaintext response, or ``None`` for durable replay/no live execution."""

        turn = self.live_turns.get(task_id)
        return turn.final_message if turn is not None else None


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
    identity_scope_ref: str,
    runtime_context_ref: str,
    execution_variant_ref: str = "",
    review_subject_task_id: str = "",
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
    if independence and not str(review_subject_task_id or "").strip():
        raise VerifierIndependenceUnavailable(
            "independence-capable role requires exactly one frozen review subject"
        )
    permitted = frozenset(permitted_tools)
    node_id = task_id
    frozen_scope = str(identity_scope_ref or "").strip()
    if not frozen_scope or frozen_scope != bundle.identity_scope_ref:
        raise OrchestratorError(
            "role DAG task identity scope does not match the orchestrator owner/workflow"
        )
    runtime_context = bundle.runtime_context
    handlers = bundle.tool_handlers.get(role, {})
    executable_handlers = {
        tool_name: handler
        for tool_name, handler in handlers.items()
        if tool_name in permitted
    }
    role_tool_schema = _role_filtered_tool_schema(
        permitted_tools=permitted,
        registered_handlers=executable_handlers,
        schema_catalog=runtime_context.schema_catalog(),
    )
    resolved_system_prompt = runtime_context.system_prompt or (
        f"You are QuantBT {role} role agent. 在受控权限与 deterministic DAG 内工作。"
    )
    expected_runtime_context_ref = _runtime_context_ref(
        runtime_context=runtime_context,
        role=role,
        registered_tool_names=frozenset(executable_handlers),
        role_tool_schema=role_tool_schema,
        resolved_system_prompt=resolved_system_prompt,
    )
    if not runtime_context_ref or runtime_context_ref != expected_runtime_context_ref:
        raise OrchestratorError("role DAG task runtime context does not match the frozen scope")
    effective_instruction = instruction
    review_binding: ReviewSubjectBinding | None = None
    if review_subject_task_id:
        builder_record, builder_turn, builder_artifact = bundle.review_subject_evidence(
            review_subject_task_id
        )
        profiles = tuple(getattr(getattr(gateway, "_policy", None), "profiles", ()))
        if not any(
            has_independent_model_route(
                builder_provider=builder_record.provider,
                builder_model=builder_record.model,
                verifier_provider=str(profile.provider),
                verifier_model=str(profile.model),
            )
            for profile in profiles
        ):
            raise VerifierIndependenceUnavailable(
                "independent verifier unavailable: no configured route has both a "
                "different provider and a recognised different foundation-model family"
            )
        review_binding, effective_instruction = make_review_subject_binding(
            builder=builder_record,
            builder_artifact_ref=_audit_digest(builder_artifact),
            builder_artifact_output_ref=str(
                builder_artifact.get("final_message_digest") or ""
            ),
            builder_output=builder_turn.final_message,
            review_criteria=instruction,
        )
        bundle.record_review_subject_binding(task_id, review_binding)
    task_scope_ref = _role_task_scope_ref(
        role=role,
        task_id=task_id,
        instruction=effective_instruction,
        permitted_tools=permitted_tools,
        difficulty=difficulty,
        risk=risk,
        independence=independence,
        identity_scope_ref=frozen_scope,
        runtime_context_ref=runtime_context_ref,
        execution_variant_ref=execution_variant_ref,
        review_subject_task_id=review_subject_task_id,
    )

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
        owner_user_id=bundle.owner_user_id,
        workflow_id=bundle.workflow_id,
        invocation_id_factory=lambda: bundle.next_invocation_id(task_scope_ref),
        record_sink=bundle.record_sink,
    )
    runtime = AgentRuntime(
        llm=adapter,
        max_steps=bundle.max_steps,
        system_prompt=resolved_system_prompt,
        translator=runtime_context.translator,
        permission_mode=runtime_context.permission_mode,
        research_graph=runtime_context.research_graph,
        entry_source=runtime_context.entry_source,
        actor=runtime_context.actor,
        owner=runtime_context.owner,
        rag_context_provider=runtime_context.rag_context_provider,
        tool_schema=role_tool_schema,
    )

    failure_emitted = False
    try:
        ctx = dispatcher.enter_node(
            node_id=node_id, task_id=task_id, role=role, permitted_tools=permitted
        )
        # 真 handler 注册进治理闸的注册表；被 wrap 的 AgentRuntime 只拿到「绑定本节点 ctx」的转交闭包。
        # **权限在 dispatch 期由治理闸 authoritative 裁决**（即便误注册一个白名单外工具，dispatch 也拒并
        # 记 violation·防御纵深）——绝不让计划外工具真执行；runtime 内任何工具调用都必经治理闸。
        for tool_name, handler in executable_handlers.items():
            dispatcher.register(tool_name, handler)
            runtime.register_tool(tool_name, dispatcher.bind_node_tool(ctx, tool_name))
        try:
            turn = runtime.run(effective_instruction)
        finally:
            dispatcher.exit_node(ctx)
        bundle.record_live_turn(task_id, turn)

        # adopt LLM Gateway 5 枚事件进统一流 + 每条 LLM 结果做图准入（绕过 Gateway 自造 → 不可准入）。
        for tid, _r, sealed in bundle.sealed_results:
            if tid != task_id:
                continue
            projector.adopt_gateway_events(
                sealed.events, role=role, desk=role_agent.home_desk, node_id=node_id
            )
            assert_llm_admissible(sealed, gateway)

        # 绕过 DAG 自由派发 / 越权 → violation 非空 → raise（节点 failed·FailureDetected）。
        violations = dispatcher.drain_violations(node_id)
        if violations:
            projector.emit(
                EV_FAILURE_DETECTED,
                {
                    "reason": "tool_dispatch_violation",
                    "violation_kinds": sorted({v.kind for v in violations}),
                    "violation_count": len(violations),
                },
                role=role,
                node_id=node_id,
            )
            failure_emitted = True
            raise DAGBypassError(
                f"节点 {task_id!r} 检出 {len(violations)} 次越界工具派发（绕过 DAG/越权·GOAL §7 → 节点拒）："
                f"{[v.kind for v in violations]}"
            )

        tool_records = dispatcher.records_for(node_id)
        # 完成门（GOAL §7：声称完成但工具记录缺失 → 拒）。
        AgentCompletion(
            role=role,
            claims_complete=turn.succeeded,
            tool_records=tuple(r.tool for r in tool_records),
            requires_tool_evidence=bundle.requires_tool_evidence.get(task_id, True),
        )
        if review_binding is not None:
            verifier_records = [
                sealed.record
                for sealed_task_id, _role, sealed in bundle.sealed_results
                if sealed_task_id == task_id
            ]
            if not verifier_records:
                raise OrchestratorError("review verifier produced no terminal LLM call")
            review_binding = bind_review_verifier_record(
                review_binding, verifier_records[-1]
            )
            validate_review_subject_binding(
                builder=builder_record,
                verifier=verifier_records[-1],
                binding=review_binding,
            )
            review_verdict = evaluate_independence(
                builder_record,
                verifier_records[-1],
            )
            if not review_verdict.independent:
                error_type = (
                    VerifierIndependenceError
                    if verifier_records[-1].independence.satisfied
                    else VerifierIndependenceUnavailable
                )
                raise error_type(
                    "review verifier final executed route did not satisfy independence: "
                    f"{review_verdict.reason}"
                )
            bundle.record_review_subject_binding(task_id, review_binding)
    except AgentCompletionError as exc:
        projector.emit(
            EV_FAILURE_DETECTED,
            {"reason": "completion_without_tool_record", "error_kind": type(exc).__name__},
            role=role,
            node_id=node_id,
        )
        failure_emitted = True
        raise
    except Exception as exc:
        if not failure_emitted:
            failure_record = adapter.last_failure_record
            failure_data = {
                "reason": "role_node_failed",
                "error_kind": type(exc).__name__,
            }
            if failure_record is not None:
                failure_data.update(
                    {
                        "call_id": str(failure_record.call_id),
                        "llm_status": str(failure_record.status),
                        "failure_stage": str(failure_record.failure_stage),
                        "llm_error_kind": str(failure_record.error_kind),
                    }
                )
            try:
                if adapter.failure_events:
                    projector.adopt_gateway_events(
                        adapter.failure_events,
                        role=role,
                        desk=role_agent.home_desk,
                        node_id=node_id,
                    )
                projector.emit(
                    EV_FAILURE_DETECTED,
                    failure_data,
                    role=role,
                    node_id=node_id,
                )
            except Exception:
                # The original failure remains authoritative if the durable event sink itself is unavailable.
                pass
        raise

    llm_call_ids = [s.record.call_id for tid, _r, s in bundle.sealed_results if tid == task_id]
    tool_record_rows = [record.to_dict() for record in tool_records]
    # DurableExecutor stores this return value. It must remain metadata-only: the live turn,
    # prompt, provider output, tool arguments, and tool results stay in ``bundle.live_turns``.
    artifact = {
        "artifact_schema": "agent_role_metadata_v1",
        "role": role,
        "task_scope_ref": task_scope_ref,
        "status": "succeeded" if turn.succeeded else "incomplete",
        "succeeded": turn.succeeded,
        "tool_call_count": len(tool_records),
        "tool_failure_count": sum(not record.ok for record in tool_records),
        "tool_records_digest": _audit_digest(tool_record_rows),
        "llm_call_count": len(llm_call_ids),
        "llm_call_ids": llm_call_ids,
        "final_message_digest": _audit_digest(turn.final_message),
        "turn_digest": _audit_digest(
            {
                "user_input": turn.user_input,
                "steps": [step.to_dict() for step in turn.steps],
                "final_message": turn.final_message,
                "succeeded": turn.succeeded,
            }
        ),
    }
    projector.emit(
        EV_ARTIFACT_PRODUCED,
        {"task_id": task_id, "role": role, "n_tool_calls": len(tool_records),
         "n_llm_calls": len(llm_call_ids), "artifact_ref": task_scope_ref},
        role=role, desk=role_agent.home_desk, node_id=node_id,
    )
    bundle.record_node_artifact(task_id, artifact)
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
        event_ledger: PersistentWorkflowEventLedger | None = None,
        owner_user_id: str = "",
        workflow_id: str = "",
        record_sink: Callable[[LLMCallRecord], None] | None = None,
        capability_ledger: PersistentAgentCapabilityLedger | None = None,
    ) -> None:
        durable_owner = str(owner_user_id or "").strip()
        durable_workflow = str(workflow_id or "").strip()
        if bool(durable_owner) != bool(durable_workflow):
            missing = "workflow_id" if durable_owner else "owner_user_id"
            raise ValueError(f"{missing} is required when an orchestrator LLM identity is supplied")
        if event_ledger is not None:
            if not durable_owner:
                raise ValueError("owner_user_id is required when event_ledger is supplied")
            if not durable_workflow:
                raise ValueError("workflow_id is required when event_ledger is supplied")
        if capability_ledger is not None and event_ledger is None:
            raise ValueError(
                "event_ledger is required when capability_ledger is supplied"
            )
        self._gateway = gateway
        self._graph = research_graph
        self._session = session_id
        self._owner_user_id = durable_owner
        self._workflow_id = durable_workflow
        self._identity_scope_ref = _identity_scope_ref(durable_owner, durable_workflow)
        self._record_sink = record_sink
        self._capability_ledger = capability_ledger
        if event_ledger is not None and self._capability_ledger is None:
            self._capability_ledger = PersistentAgentCapabilityLedger(
                capability_path_for_event_ledger(event_ledger.path),
                secret_values=secret_values,
            )
        self._projector = EventProjector(
            secret_values=secret_values,
            ledger=event_ledger,
            owner_user_id=durable_owner,
            workflow_id=durable_workflow if event_ledger is not None else (durable_workflow or session_id),
        )
        # 派发闸的 on_event → 投影 ToolCallStarted/Finished + 语义事件（AssetRead/RagHitUsed/...）。
        self._dispatcher = GovernedToolDispatcher(on_event=self._tool_event_hook)

    def _require_role_llm_scope(self) -> None:
        if not self._owner_user_id:
            raise ValueError("owner_user_id is required for role-agent LLM dispatch")
        if not self._workflow_id:
            raise ValueError("workflow_id is required for role-agent LLM dispatch")

    def _bind_executor_capability(self, executor: DurableExecutor) -> None:
        if self._capability_ledger is None:
            return
        executor.bind_capability_scope(
            ledger=self._capability_ledger,
            owner_user_id=self._owner_user_id,
            workflow_id=self._workflow_id,
        )

    def _require_review_record_scope(
        self, builder: LLMCallRecord, verifier: LLMCallRecord
    ) -> None:
        if self._capability_ledger is None:
            return
        for label, record in (("builder", builder), ("verifier", verifier)):
            if record.owner_user_id != self._owner_user_id:
                raise OrchestratorError(
                    f"{label} review record owner does not match orchestrator owner"
                )
            if record.workflow_id != self._workflow_id:
                raise OrchestratorError(
                    f"{label} review record workflow does not match orchestrator workflow"
                )
            if not str(record.call_id or "").strip():
                raise OrchestratorError(f"{label} review record call_id is required")
            if not str(record.prompt_digest or "").strip():
                raise OrchestratorError(
                    f"{label} review record context digest is required"
                )

    def _prepare_capability_operation(
        self,
        *,
        target_kind: str,
        material: Any,
    ) -> Any | None:
        if self._capability_ledger is None:
            return None
        return self._capability_ledger.prepare_operation(
            owner_user_id=self._owner_user_id,
            workflow_id=self._workflow_id,
            target_kind=target_kind,
            request_ref=f"{target_kind}_request:sha256:{_audit_digest(material)}",
        )

    def _abort_capability_operation(
        self,
        prepared: Any | None,
        exc: BaseException,
    ) -> None:
        if prepared is None:
            return
        if isinstance(exc, AgentCapabilityCommitUncertain) or type(exc).__name__.endswith(
            "CommitUncertain"
        ):
            return
        self._capability_ledger.abort_operation(
            owner_user_id=self._owner_user_id,
            workflow_id=self._workflow_id,
            prepared_record_ref=prepared.record_ref,
            failure_ref=f"operation_failure:sha256:{_audit_digest(type(exc).__name__)}",
        )

    def _commit_capability_operation(
        self,
        prepared: Any | None,
        *capability_refs: str,
    ) -> None:
        if prepared is None:
            return
        self._capability_ledger.commit_operation(
            owner_user_id=self._owner_user_id,
            workflow_id=self._workflow_id,
            prepared_record_ref=prepared.record_ref,
            capability_refs=capability_refs,
        )

    def _resolve_runtime_context(
        self, runtime_context: AgentRuntimeContext | None
    ) -> AgentRuntimeContext:
        context = runtime_context or AgentRuntimeContext(owner=self._owner_user_id)
        runtime_owner = str(context.owner or self._owner_user_id).strip()
        if self._owner_user_id and runtime_owner != self._owner_user_id:
            raise ValueError(
                "runtime context owner must match the orchestrator owner_user_id"
            )
        if context.owner != runtime_owner:
            context = replace(context, owner=runtime_owner)
        return context

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
    def capability_ledger(self) -> PersistentAgentCapabilityLedger | None:
        return self._capability_ledger

    @property
    def events(self) -> tuple[WorkflowEvent, ...]:
        return self._projector.events

    # —— 工具→语义事件投影（GOAL §7 工具/资产/验证可见）——
    def _tool_event_hook(self, phase: str, data: dict[str, Any], ctx: NodeExecutionContext) -> None:
        tool = data.get("tool", "")
        tool_call_ref = str(data.get("tool_call_ref") or "")
        if phase == "started":
            self._projector.emit(
                EV_TOOL_CALL_STARTED,
                {"tool": tool, "tool_call_ref": tool_call_ref},
                role=ctx.role,
                node_id=ctx.node_id,
            )
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
        self._projector.emit(
            EV_TOOL_CALL_FINISHED,
            {"tool": tool, "ok": ok, "tool_call_ref": tool_call_ref},
            role=ctx.role,
            node_id=ctx.node_id,
        )

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
        invalid_review_dependencies = [
            todo.todo_id
            for todo in plan.todos
            if get_role(todo.role).independence_capable
            and len(plan.dependencies.get(todo.todo_id, ())) != 1
        ]
        if invalid_review_dependencies:
            plan.status = PLAN_DRAFT
            plan.draft_reason = (
                "independence-capable verifier requires exactly one declared review subject; "
                "invalid todos=" + ",".join(sorted(invalid_review_dependencies))
            )
        prepared = self._prepare_capability_operation(
            target_kind=CAPABILITY_PLAN,
            material=plan.to_dict(),
        )
        capability_record = None
        try:
            plan_event = self._projector.emit(
                EV_AGENT_PLAN_CREATED,
                {"goal_digest": _audit_digest(goal), "status": plan.status, "n_todos": len(plan.todos),
                 "n_gates": len(plan.acceptance_gates), "draft_reason": plan.draft_reason},
            )
            todo_events: list[WorkflowEvent] = []
            for t in plan.todos:
                todo_events.append(
                    self._projector.emit(
                        EV_TODO_UPDATED,
                        {"todo_id": t.todo_id, "role": t.role, "deps": list(t.deps)},
                    )
                )
            if self._capability_ledger is not None:
                capability_record = self._capability_ledger.record_plan(
                    owner_user_id=self._owner_user_id,
                    workflow_id=self._workflow_id,
                    plan=plan,
                    source_event_refs=(
                        plan_event.event_id,
                        *(event.event_id for event in todo_events),
                    ),
                )
        except Exception as exc:
            self._abort_capability_operation(prepared, exc)
            raise
        if capability_record is not None:
            self._commit_capability_operation(prepared, capability_record.record_ref)
        return plan

    # ───────────────────────── ReAct 形态（DAG dispatch）─────────────────────────
    def build_dag(
        self,
        plan: AgentPlan,
        *,
        instructions: dict[str, str] | None = None,
        tool_handlers: dict[str, dict[str, ToolHandler]] | None = None,
        runtime_context: AgentRuntimeContext | None = None,
        execution_variant_ref: str = "",
    ) -> list[DAGTask]:
        """把就绪 plan 冻结成 deterministic DAG（每 todo 一个 pure 节点·deps 即 plan.dependencies）。"""

        if not plan.is_ready:
            raise PlanError(
                f"plan 未就绪（{plan.status}：{plan.draft_reason}）——draft 不晋升为可执行 DAG（GOAL §7）"
            )
        instructions = instructions or {}
        tool_handlers = tool_handlers or {}
        runtime_context = self._resolve_runtime_context(runtime_context)
        tasks: list[DAGTask] = []
        for todo in plan.todos:
            role_agent = get_role(todo.role)
            permitted_tools = frozenset(role_agent.permitted_tools)
            role_handlers = tool_handlers.get(todo.role, {})
            executable_handlers = {
                name: handler
                for name, handler in role_handlers.items()
                if name in permitted_tools
            }
            role_tool_schema = _role_filtered_tool_schema(
                permitted_tools=permitted_tools,
                registered_handlers=executable_handlers,
                schema_catalog=runtime_context.schema_catalog(),
            )
            resolved_system_prompt = runtime_context.system_prompt or (
                f"You are QuantBT {todo.role} role agent. "
                "在受控权限与 deterministic DAG 内工作。"
            )
            runtime_context_ref = _runtime_context_ref(
                runtime_context=runtime_context,
                role=todo.role,
                registered_tool_names=frozenset(executable_handlers),
                role_tool_schema=role_tool_schema,
                resolved_system_prompt=resolved_system_prompt,
            )
            params = {
                "role": todo.role,
                "task_id": todo.todo_id,
                "instruction": instructions.get(todo.todo_id, todo.description),
                "permitted_tools": sorted(permitted_tools),
                "difficulty": role_agent.default_difficulty,
                "risk": role_agent.default_risk,
                "independence": role_agent.independence_capable,
                # DurableExecutor excludes context from node identity. Freeze this
                # non-plaintext scope ref into params to prevent cross-owner reuse.
                "identity_scope_ref": self._identity_scope_ref,
                # Runtime handles stay in the ephemeral bundle. Only this digest of
                # execution-relevant primitives and registered names enters identity.
                "runtime_context_ref": runtime_context_ref,
            }
            dependencies = list(plan.dependencies.get(todo.todo_id, []))
            if role_agent.independence_capable and len(dependencies) != 1:
                raise PlanError(
                    "independence-capable verifier requires exactly one declared review subject: "
                    f"{todo.todo_id} has {len(dependencies)}"
                )
            if role_agent.independence_capable:
                # The single declared upstream node is the only admissible review
                # subject.  role_node_op replaces caller text with a server-built
                # envelope containing that node's exact terminal output.
                params["review_subject_task_id"] = dependencies[0]
            if execution_variant_ref:
                params["execution_variant_ref"] = str(execution_variant_ref)
            tasks.append(DAGTask(
                id=todo.todo_id,
                op=ROLE_NODE_OP,
                params=params,
                deps=dependencies,
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
        runtime_context: AgentRuntimeContext | None = None,
    ) -> OrchestrationResult:
        """ReAct 形态（GOAL §7）：在 deterministic DAG 内串/并行跑 role agent。

        `executor` 须由 `make_executor(root)` 造（已注册 role 节点 op）；run 与后续 replay 须用同一执行器。
        """

        self._require_role_llm_scope()
        resolved_runtime_context = self._resolve_runtime_context(runtime_context)
        tasks = self.build_dag(
            plan,
            instructions=instructions,
            tool_handlers=tool_handlers,
            runtime_context=resolved_runtime_context,
        )
        bundle = _OrchBundle(
            gateway=self._gateway, dispatcher=self._dispatcher, projector=self._projector,
            tool_handlers=tool_handlers or {}, session_id=self._session,
            owner_user_id=self._owner_user_id, workflow_id=self._workflow_id,
            identity_scope_ref=self._identity_scope_ref,
            replay_mode="live", record_sink=self._record_sink,
            max_steps=max_steps, requires_tool_evidence=requires_tool_evidence or {},
            runtime_context=resolved_runtime_context,
        )
        prepared = self._prepare_capability_operation(
            target_kind=CAPABILITY_REACT,
            material={"tasks": [task.id for task in tasks], "mode": "react"},
        )
        capability_record = None
        self._bind_executor_capability(executor)
        try:
            kr = executor.run(tasks, {ORCH_CONTEXT_KEY: bundle})
            result = self._finish_run(kr, bundle)
            if self._capability_ledger is not None and result.succeeded:
                capability_record = self._capability_ledger.record_orchestration_mode(
                    owner_user_id=self._owner_user_id,
                    workflow_id=self._workflow_id,
                    mode=CAPABILITY_REACT,
                    source_event_ref=result.verdict_event_ref,
                    dag_record_ref=kr.capability_record_ref,
                    result=result,
                )
        except Exception as exc:
            self._abort_capability_operation(prepared, exc)
            raise
        if not result.succeeded:
            self._abort_capability_operation(
                prepared,
                OrchestratorError("ReAct orchestration did not succeed"),
            )
        elif capability_record is not None:
            self._commit_capability_operation(prepared, capability_record.record_ref)
        return result

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
        runtime_context: AgentRuntimeContext | None = None,
    ) -> OrchestrationResult:
        """Replay 形态（GOAL §7）：读已落账 run/artifact。命中 kernel durable 工件 → 节点复用、**零重跑**
        （op 不被调用·零 LLM·零工具派发）。诚实残余：fixture 后端（RecordingLLMClient）深接线另卡。"""

        self._require_role_llm_scope()
        resolved_runtime_context = self._resolve_runtime_context(runtime_context)
        tasks = self.build_dag(
            plan,
            instructions=instructions,
            tool_handlers=tool_handlers,
            runtime_context=resolved_runtime_context,
        )
        bundle = _OrchBundle(
            gateway=self._gateway, dispatcher=self._dispatcher, projector=self._projector,
            tool_handlers=tool_handlers or {}, session_id=self._session,
            owner_user_id=self._owner_user_id, workflow_id=self._workflow_id,
            identity_scope_ref=self._identity_scope_ref,
            replay_mode="replay", record_sink=self._record_sink,
            max_steps=max_steps, requires_tool_evidence=requires_tool_evidence or {},
            runtime_context=resolved_runtime_context,
        )
        prepared = self._prepare_capability_operation(
            target_kind=CAPABILITY_REPLAY,
            material={"tasks": [task.id for task in tasks], "mode": "replay"},
        )
        capability_record = None
        self._bind_executor_capability(executor)
        try:
            kr = executor.replay(tasks, {ORCH_CONTEXT_KEY: bundle})
            result = self._finish_run(kr, bundle)
            if self._capability_ledger is not None and result.succeeded:
                capability_record = self._capability_ledger.record_orchestration_mode(
                    owner_user_id=self._owner_user_id,
                    workflow_id=self._workflow_id,
                    mode=CAPABILITY_REPLAY,
                    source_event_ref=result.verdict_event_ref,
                    dag_record_ref=kr.capability_record_ref,
                    result=result,
                )
        except Exception as exc:
            self._abort_capability_operation(prepared, exc)
            raise
        if not result.succeeded:
            self._abort_capability_operation(
                prepared,
                OrchestratorError("Replay orchestration did not succeed"),
            )
        elif capability_record is not None:
            self._commit_capability_operation(prepared, capability_record.record_ref)
        return result

    def fork(
        self,
        plan: AgentPlan,
        *,
        executor: DurableExecutor,
        from_task_id: str,
        overrides: dict[str, Any],
        execution_variant_ref: str,
        instructions: dict[str, str] | None = None,
        tool_handlers: dict[str, dict[str, ToolHandler]] | None = None,
        max_steps: int = 4,
        requires_tool_evidence: dict[str, bool] | None = None,
        runtime_context: AgentRuntimeContext | None = None,
    ) -> OrchestrationResult:
        """Run one explicit what-if branch through the governed DAG kernel."""

        self._require_role_llm_scope()
        variant = str(execution_variant_ref or "").strip()
        if not variant or any(char.isspace() for char in variant):
            raise ValueError("execution_variant_ref must be an opaque reference")
        resolved_runtime_context = self._resolve_runtime_context(runtime_context)
        tasks = self.build_dag(
            plan,
            instructions=instructions,
            tool_handlers=tool_handlers,
            runtime_context=resolved_runtime_context,
            execution_variant_ref=variant,
        )
        bundle = _OrchBundle(
            gateway=self._gateway,
            dispatcher=self._dispatcher,
            projector=self._projector,
            tool_handlers=tool_handlers or {},
            session_id=self._session,
            owner_user_id=self._owner_user_id,
            workflow_id=self._workflow_id,
            identity_scope_ref=self._identity_scope_ref,
            replay_mode="live",
            record_sink=self._record_sink,
            max_steps=max_steps,
            requires_tool_evidence=requires_tool_evidence or {},
            runtime_context=resolved_runtime_context,
        )
        self._bind_executor_capability(executor)
        kr = executor.fork(
            tasks,
            from_task_id=from_task_id,
            overrides=dict(overrides),
            context={ORCH_CONTEXT_KEY: bundle},
        )
        return self._finish_run(kr, bundle)

    def rollback(
        self,
        plan: AgentPlan,
        *,
        executor: DurableExecutor,
        to_task_id: str,
        instructions: dict[str, str] | None = None,
        tool_handlers: dict[str, dict[str, ToolHandler]] | None = None,
        requires_tool_evidence: dict[str, bool] | None = None,
        runtime_context: AgentRuntimeContext | None = None,
    ) -> OrchestrationResult:
        """Discard downstream pure artifacts and expose the reconcile boundary."""

        self._require_role_llm_scope()
        resolved_runtime_context = self._resolve_runtime_context(runtime_context)
        tasks = self.build_dag(
            plan,
            instructions=instructions,
            tool_handlers=tool_handlers,
            runtime_context=resolved_runtime_context,
        )
        bundle = _OrchBundle(
            gateway=self._gateway,
            dispatcher=self._dispatcher,
            projector=self._projector,
            tool_handlers=tool_handlers or {},
            session_id=self._session,
            owner_user_id=self._owner_user_id,
            workflow_id=self._workflow_id,
            identity_scope_ref=self._identity_scope_ref,
            replay_mode="replay",
            record_sink=self._record_sink,
            max_steps=0,
            requires_tool_evidence=requires_tool_evidence or {},
            runtime_context=resolved_runtime_context,
        )
        self._bind_executor_capability(executor)
        kr = executor.rollback(
            tasks,
            to_task_id=to_task_id,
            context={ORCH_CONTEXT_KEY: bundle},
        )
        return self._finish_run(kr, bundle)

    def _finish_run(self, kr: KernelRunResult, bundle: _OrchBundle) -> OrchestrationResult:
        node_artifacts = {n.task_id: n.result for n in kr.nodes}
        verdict_event = self._projector.emit(
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
            live_turns=dict(bundle.live_turns),
            review_subject_bindings=dict(bundle.review_subject_bindings),
            succeeded=kr.succeeded,
            verdict_event_ref=verdict_event.event_id,
        )

    # ───────────────────────── Review 形态（Verifier 独立性）─────────────────────────
    def admit_verifier_challenge(
        self,
        builder: LLMCallRecord,
        verifier: LLMCallRecord,
        *,
        subject_binding: ReviewSubjectBinding,
    ) -> IndependenceVerdict:
        """Review 形态门（GOAL §7：Verifier 与 Builder 共用同一输出上下文且未标独立性不足 → 拒）。

        裁决复用 gateway 的 `evaluate_independence`（单一源）。任何未证明 provider +
        foundation-model family 双重异源却声称 ``satisfied=True`` 的记录都是假独立并拒绝。
        诚实标 ``satisfied=False`` 的不足记录可作为非独立审阅事实返回，但不能让要求独立的 DAG review
        节点成功。投影 VerifierChallengeRaised。
        """

        self._require_review_record_scope(builder, verifier)
        validate_review_subject_binding(
            builder=builder,
            verifier=verifier,
            binding=subject_binding,
        )
        verdict = evaluate_independence(builder, verifier)
        prepared = self._prepare_capability_operation(
            target_kind=CAPABILITY_REVIEW,
            material={
                "builder_call_ref": builder.call_id,
                "verifier_call_ref": verifier.call_id,
                "review_subject_ref": subject_binding.review_subject_ref,
                "independent": verdict.independent,
            },
        )
        capability_record = None
        try:
            review_event = self._projector.emit(
                EV_VERIFIER_CHALLENGE_RAISED,
                {"independent": verdict.independent, "reason": verdict.reason,
                 "claimed_satisfied": bool(verifier.independence.satisfied),
                 "review_subject_ref": subject_binding.review_subject_ref},
                role="verifier_critic",
            )
            if not verdict.independent and verifier.independence.satisfied:
                raise VerifierIndependenceError(
                    "Verifier 未证明 provider + foundation-model family 双重异源却声称独立"
                    f"——GOAL §7 → 拒：{verdict.reason}"
                )
            if self._capability_ledger is not None:
                capability_record = self._capability_ledger.record_review(
                    owner_user_id=self._owner_user_id,
                    workflow_id=self._workflow_id,
                    builder=builder,
                    verifier=verifier,
                    subject_binding=subject_binding,
                    verdict=verdict,
                    source_event_ref=review_event.event_id,
                )
        except Exception as exc:
            self._abort_capability_operation(prepared, exc)
            raise
        if capability_record is not None:
            self._commit_capability_operation(prepared, capability_record.record_ref)
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
    def repair(
        self,
        *,
        failure_ref: str,
        code_change: AgentCodeChange,
        permission_ref: str = "",
    ) -> AgentCodeChange:
        """Repair 形态（GOAL §7）：定位失败 + 提交修复 diff。`AgentCodeChange` 构造已强制 diff/test/rollback
        （缺即拒）；这里只投影 FailureDetected + RepairAttempted。"""

        if self._capability_ledger is not None:
            if not str(permission_ref or "").strip() or any(
                char.isspace() for char in str(permission_ref)
            ):
                raise OrchestratorError(
                    "permission_ref is required for durable AgentCodeChange evidence"
                )
            if not str(failure_ref or "").strip() or any(
                char.isspace() for char in str(failure_ref)
            ):
                raise OrchestratorError(
                    "failure_ref must be an opaque reference for durable repair evidence"
                )
        prepared = self._prepare_capability_operation(
            target_kind=CAPABILITY_REPAIR,
            material={
                "failure_ref": failure_ref,
                "path_ref": _audit_digest(code_change.path),
                "change_ref": _audit_digest(code_change.diff),
                "permission_ref": permission_ref,
            },
        )
        capability_records = None
        try:
            failure_event = self._projector.emit(
                EV_FAILURE_DETECTED, {"failure_ref": failure_ref, "mode": MODE_REPAIR}
            )
            repair_event = self._projector.emit(
                EV_REPAIR_ATTEMPTED,
                {"failure_ref": failure_ref, "path": code_change.path,
                 "has_diff": bool(code_change.diff), "has_test": bool(code_change.test_result),
                 "has_rollback": bool(code_change.rollback_point)},
            )
            if self._capability_ledger is not None:
                capability_records = self._capability_ledger.record_repair(
                    owner_user_id=self._owner_user_id,
                    workflow_id=self._workflow_id,
                    failure_ref=failure_ref,
                    code_change=code_change,
                    permission_ref=permission_ref,
                    source_event_refs=(failure_event.event_id, repair_event.event_id),
                )
        except Exception as exc:
            self._abort_capability_operation(prepared, exc)
            raise
        if capability_records is not None:
            self._commit_capability_operation(
                prepared,
                *(record.record_ref for record in capability_records),
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
    "AgentRuntimeContext",
    "OrchestrationResult",
    "OrchestratorError",
    "VerifierIndependenceError",
    "VerifierIndependenceUnavailable",
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
