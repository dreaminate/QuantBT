"""GOAL §7 Agent Shell / Multi-Agent Research OS contracts."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any


def _tuple(value: Any) -> tuple[Any, ...]:
    if value is None:
        return ()
    if isinstance(value, tuple):
        return value
    if isinstance(value, list):
        return tuple(value)
    return (value,)


def _present(value: str | None) -> bool:
    return bool(str(value or "").strip())


class AgentWorkflowEventType(str, Enum):
    AGENT_PLAN_CREATED = "AgentPlanCreated"
    TODO_UPDATED = "TodoUpdated"
    ROLE_AGENT_DISPATCHED = "RoleAgentDispatched"
    LLM_ROUTE_SELECTED = "LLMRouteSelected"
    LLM_CALL_STARTED = "LLMCallStarted"
    LLM_CALL_FINISHED = "LLMCallFinished"
    TOOL_CALL_STARTED = "ToolCallStarted"
    TOOL_CALL_FINISHED = "ToolCallFinished"
    RAG_HIT_USED = "RagHitUsed"
    CANONICAL_COMMAND_APPLIED = "CanonicalCommandApplied"
    VALIDATION_STARTED = "ValidationStarted"
    VALIDATION_FINISHED = "ValidationFinished"
    VERIFIER_CHALLENGE_RAISED = "VerifierChallengeRaised"
    ARTIFACT_PRODUCED = "ArtifactProduced"


@dataclass(frozen=True)
class AgentOSViolation:
    code: str
    message: str
    field: str = ""
    ref: str = ""


@dataclass(frozen=True)
class AgentOSDecision:
    accepted: bool
    violations: tuple[AgentOSViolation, ...]


@dataclass(frozen=True)
class AgentWorkflowEventRecord:
    event_ref: str
    event_type: AgentWorkflowEventType | str
    user_visible: bool
    input_refs: tuple[str, ...]
    output_refs: tuple[str, ...]
    audit_ref: str | None

    def __post_init__(self) -> None:
        object.__setattr__(self, "input_refs", _tuple(self.input_refs))
        object.__setattr__(self, "output_refs", _tuple(self.output_refs))


@dataclass(frozen=True)
class AgentPlanRecord:
    plan_ref: str
    todo_refs: tuple[str, ...]
    dependency_refs: tuple[str, ...]
    acceptance_gate_refs: tuple[str, ...]
    rollback_point_refs: tuple[str, ...]
    cross_desk_handoff_refs: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "todo_refs", _tuple(self.todo_refs))
        object.__setattr__(self, "dependency_refs", _tuple(self.dependency_refs))
        object.__setattr__(self, "acceptance_gate_refs", _tuple(self.acceptance_gate_refs))
        object.__setattr__(self, "rollback_point_refs", _tuple(self.rollback_point_refs))
        object.__setattr__(self, "cross_desk_handoff_refs", _tuple(self.cross_desk_handoff_refs))


@dataclass(frozen=True)
class RoleAgentDispatchRecord:
    dispatch_ref: str
    role_agent: str
    desk: str
    visible_event_ref: str | None
    llm_gateway_call_ref: str | None
    model_routing_policy_ref: str | None
    permission_scope_ref: str | None
    tool_permission_ref: str | None
    replay_requirement_ref: str | None
    direct_provider_sdk_call: bool = False
    direct_credential_access: bool = False
    verifier_challenge: bool = False
    verifier_provider_ref: str | None = None
    verifier_model_ref: str | None = None
    verifier_context_ref: str | None = None
    builder_context_ref: str | None = None


@dataclass(frozen=True)
class AgentCodeChangeRecord:
    change_ref: str
    canonical_command_ref: str | None
    diff_ref: str | None
    test_result_refs: tuple[str, ...]
    validation_result_refs: tuple[str, ...]
    rollback_point_ref: str | None
    permission_record_ref: str | None

    def __post_init__(self) -> None:
        object.__setattr__(self, "test_result_refs", _tuple(self.test_result_refs))
        object.__setattr__(self, "validation_result_refs", _tuple(self.validation_result_refs))


@dataclass(frozen=True)
class AgentToolCallRecord:
    tool_call_ref: str
    tool_schema_valid: bool
    visible_event_ref: str | None
    audit_ref: str | None
    permission_scope_ref: str | None
    output_ref: str | None


@dataclass(frozen=True)
class AgentCompletionClaim:
    claim_ref: str
    claims_complete: bool
    tool_record_refs: tuple[str, ...]
    validation_result_refs: tuple[str, ...]
    artifact_refs: tuple[str, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "tool_record_refs", _tuple(self.tool_record_refs))
        object.__setattr__(self, "validation_result_refs", _tuple(self.validation_result_refs))
        object.__setattr__(self, "artifact_refs", _tuple(self.artifact_refs))


def validate_agent_workflow_event(event: AgentWorkflowEventRecord) -> AgentOSDecision:
    violations: list[AgentOSViolation] = []
    if not event.user_visible:
        violations.append(
            AgentOSViolation(
                "agent_workflow_event_not_visible",
                "Agent OS internal progress must project visible workflow events unless a boundary blocks content",
                field="user_visible",
                ref=event.event_ref,
            )
        )
    if not _present(event.audit_ref):
        violations.append(
            AgentOSViolation(
                "agent_workflow_event_missing_audit",
                "Agent workflow events require audit lineage",
                field="audit_ref",
                ref=event.event_ref,
            )
        )
    return AgentOSDecision(accepted=not violations, violations=tuple(violations))


def validate_agent_plan(plan: AgentPlanRecord) -> AgentOSDecision:
    violations: list[AgentOSViolation] = []
    for field_name in ("todo_refs", "dependency_refs", "acceptance_gate_refs", "rollback_point_refs"):
        if not getattr(plan, field_name):
            violations.append(
                AgentOSViolation(
                    "agent_plan_missing_required_section",
                    "AgentPlan requires todo, dependencies, acceptance gates, and rollback points",
                    field=field_name,
                    ref=plan.plan_ref,
                )
            )
    return AgentOSDecision(accepted=not violations, violations=tuple(violations))


def validate_role_agent_dispatch(dispatch: RoleAgentDispatchRecord) -> AgentOSDecision:
    violations: list[AgentOSViolation] = []
    for field_name in (
        "visible_event_ref",
        "llm_gateway_call_ref",
        "model_routing_policy_ref",
        "permission_scope_ref",
        "tool_permission_ref",
        "replay_requirement_ref",
    ):
        if not _present(getattr(dispatch, field_name)):
            violations.append(
                AgentOSViolation(
                    "role_agent_dispatch_missing_governance_ref",
                    "role agent dispatch requires visible event, LLM Gateway, model routing, permissions, and replay refs",
                    field=field_name,
                    ref=dispatch.dispatch_ref,
                )
            )
    if dispatch.direct_provider_sdk_call:
        violations.append(
            AgentOSViolation(
                "role_agent_bypassed_llm_gateway",
                "role agents must call providers through LLM Gateway",
                field="direct_provider_sdk_call",
                ref=dispatch.dispatch_ref,
            )
        )
    if dispatch.direct_credential_access:
        violations.append(
            AgentOSViolation(
                "role_agent_direct_credential_access",
                "role agents cannot read provider credentials or tokens directly",
                field="direct_credential_access",
                ref=dispatch.dispatch_ref,
            )
        )
    if dispatch.verifier_challenge:
        for field_name in ("verifier_provider_ref", "verifier_model_ref", "verifier_context_ref"):
            if not _present(getattr(dispatch, field_name)):
                violations.append(
                    AgentOSViolation(
                        "verifier_independence_record_missing",
                        "verifier challenge evidence requires provider, model, and context records",
                        field=field_name,
                        ref=dispatch.dispatch_ref,
                    )
                )
        if (
            _present(dispatch.builder_context_ref)
            and dispatch.builder_context_ref == dispatch.verifier_context_ref
        ):
            violations.append(
                AgentOSViolation(
                    "verifier_reused_builder_context",
                    "verifier challenge using builder context must be marked independent-insufficient",
                    field="verifier_context_ref",
                    ref=dispatch.dispatch_ref,
                )
            )
    return AgentOSDecision(accepted=not violations, violations=tuple(violations))


def validate_agent_code_change(change: AgentCodeChangeRecord) -> AgentOSDecision:
    violations: list[AgentOSViolation] = []
    for field_name in ("canonical_command_ref", "diff_ref", "rollback_point_ref", "permission_record_ref"):
        if not _present(getattr(change, field_name)):
            violations.append(
                AgentOSViolation(
                    "agent_code_change_missing_required_ref",
                    "Agent code changes require canonical command, diff, permission, and rollback refs",
                    field=field_name,
                    ref=change.change_ref,
                )
            )
    if not change.test_result_refs and not change.validation_result_refs:
        violations.append(
            AgentOSViolation(
                "agent_code_change_missing_test_or_validation",
                "Agent code changes require test or validation result refs",
                field="test_result_refs",
                ref=change.change_ref,
            )
        )
    return AgentOSDecision(accepted=not violations, violations=tuple(violations))


def validate_agent_tool_call(call: AgentToolCallRecord) -> AgentOSDecision:
    violations: list[AgentOSViolation] = []
    if not call.tool_schema_valid:
        violations.append(
            AgentOSViolation(
                "schema_invalid_tool_call_dispatched",
                "schema-invalid tool calls must not dispatch",
                field="tool_schema_valid",
                ref=call.tool_call_ref,
            )
        )
    for field_name in ("visible_event_ref", "audit_ref", "permission_scope_ref", "output_ref"):
        if not _present(getattr(call, field_name)):
            violations.append(
                AgentOSViolation(
                    "agent_tool_call_missing_record",
                    "tool calls require visible event, audit, permission, and output records",
                    field=field_name,
                    ref=call.tool_call_ref,
                )
            )
    return AgentOSDecision(accepted=not violations, violations=tuple(violations))


def validate_agent_completion_claim(claim: AgentCompletionClaim) -> AgentOSDecision:
    violations: list[AgentOSViolation] = []
    if claim.claims_complete:
        if not claim.tool_record_refs:
            violations.append(
                AgentOSViolation(
                    "agent_completion_missing_tool_records",
                    "Agent cannot claim completion without tool records",
                    field="tool_record_refs",
                    ref=claim.claim_ref,
                )
            )
        if not claim.validation_result_refs:
            violations.append(
                AgentOSViolation(
                    "agent_completion_missing_validation",
                    "Agent completion claims require validation result refs",
                    field="validation_result_refs",
                    ref=claim.claim_ref,
                )
            )
        if not claim.artifact_refs:
            violations.append(
                AgentOSViolation(
                    "agent_completion_missing_artifacts",
                    "Agent completion claims require produced artifact refs",
                    field="artifact_refs",
                    ref=claim.claim_ref,
                )
            )
    return AgentOSDecision(accepted=not violations, violations=tuple(violations))


def validate_agent_os_contract(
    *,
    events: tuple[AgentWorkflowEventRecord, ...] = (),
    plans: tuple[AgentPlanRecord, ...] = (),
    dispatches: tuple[RoleAgentDispatchRecord, ...] = (),
    code_changes: tuple[AgentCodeChangeRecord, ...] = (),
    tool_calls: tuple[AgentToolCallRecord, ...] = (),
    completion_claims: tuple[AgentCompletionClaim, ...] = (),
) -> AgentOSDecision:
    violations: list[AgentOSViolation] = []
    for event in events:
        violations.extend(validate_agent_workflow_event(event).violations)
    for plan in plans:
        violations.extend(validate_agent_plan(plan).violations)
    for dispatch in dispatches:
        violations.extend(validate_role_agent_dispatch(dispatch).violations)
    for change in code_changes:
        violations.extend(validate_agent_code_change(change).violations)
    for call in tool_calls:
        violations.extend(validate_agent_tool_call(call).violations)
    for claim in completion_claims:
        violations.extend(validate_agent_completion_claim(claim).violations)
    return AgentOSDecision(accepted=not violations, violations=tuple(violations))


__all__ = [
    "AgentCodeChangeRecord",
    "AgentCompletionClaim",
    "AgentOSDecision",
    "AgentOSViolation",
    "AgentPlanRecord",
    "AgentToolCallRecord",
    "AgentWorkflowEventRecord",
    "AgentWorkflowEventType",
    "RoleAgentDispatchRecord",
    "validate_agent_code_change",
    "validate_agent_completion_claim",
    "validate_agent_os_contract",
    "validate_agent_plan",
    "validate_agent_tool_call",
    "validate_agent_workflow_event",
    "validate_role_agent_dispatch",
]
