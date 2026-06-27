from __future__ import annotations

from app.research_os.agent_os import (
    AgentCodeChangeRecord,
    AgentCompletionClaim,
    AgentPlanRecord,
    AgentToolCallRecord,
    AgentWorkflowEventRecord,
    AgentWorkflowEventType,
    RoleAgentDispatchRecord,
    validate_agent_code_change,
    validate_agent_completion_claim,
    validate_agent_os_contract,
    validate_agent_plan,
    validate_agent_tool_call,
    validate_agent_workflow_event,
    validate_role_agent_dispatch,
)


def _codes(decision) -> set[str]:
    return {violation.code for violation in decision.violations}


def _event(**overrides) -> AgentWorkflowEventRecord:
    data = {
        "event_ref": "event:plan",
        "event_type": AgentWorkflowEventType.AGENT_PLAN_CREATED,
        "user_visible": True,
        "input_refs": ("qro:001",),
        "output_refs": ("plan:001",),
        "audit_ref": "audit:001",
    }
    data.update(overrides)
    return AgentWorkflowEventRecord(**data)


def _plan(**overrides) -> AgentPlanRecord:
    data = {
        "plan_ref": "plan:001",
        "todo_refs": ("todo:1",),
        "dependency_refs": ("dependency:data_lock",),
        "acceptance_gate_refs": ("gate:validation",),
        "rollback_point_refs": ("rollback:pre_change",),
    }
    data.update(overrides)
    return AgentPlanRecord(**data)


def _dispatch(**overrides) -> RoleAgentDispatchRecord:
    data = {
        "dispatch_ref": "dispatch:math",
        "role_agent": "Mathematical Researcher",
        "desk": "research",
        "visible_event_ref": "event:dispatch",
        "llm_gateway_call_ref": "llm_call:001",
        "model_routing_policy_ref": "routing:math",
        "permission_scope_ref": "permission:research",
        "tool_permission_ref": "tool_permission:math",
        "replay_requirement_ref": "replay:required",
    }
    data.update(overrides)
    return RoleAgentDispatchRecord(**data)


def _code_change(**overrides) -> AgentCodeChangeRecord:
    data = {
        "change_ref": "change:001",
        "canonical_command_ref": "command:code_change",
        "diff_ref": "diff:001",
        "test_result_refs": ("pytest:001",),
        "validation_result_refs": (),
        "rollback_point_ref": "rollback:001",
        "permission_record_ref": "permission:001",
    }
    data.update(overrides)
    return AgentCodeChangeRecord(**data)


def _tool_call(**overrides) -> AgentToolCallRecord:
    data = {
        "tool_call_ref": "tool_call:001",
        "tool_schema_valid": True,
        "visible_event_ref": "event:tool",
        "audit_ref": "audit:tool",
        "permission_scope_ref": "permission:tool",
        "output_ref": "artifact:output",
    }
    data.update(overrides)
    return AgentToolCallRecord(**data)


def test_workflow_event_must_be_visible_and_audited():
    decision = validate_agent_workflow_event(_event(user_visible=False, audit_ref=None))
    assert not decision.accepted
    assert _codes(decision) >= {
        "agent_workflow_event_not_visible",
        "agent_workflow_event_missing_audit",
    }


def test_agent_plan_requires_todo_dependencies_acceptance_gates_and_rollback():
    decision = validate_agent_plan(
        _plan(todo_refs=(), dependency_refs=(), acceptance_gate_refs=(), rollback_point_refs=())
    )
    assert not decision.accepted
    assert "agent_plan_missing_required_section" in _codes(decision)


def test_role_agent_must_use_gateway_permissions_and_replay_not_provider_credentials():
    decision = validate_role_agent_dispatch(
        _dispatch(
            llm_gateway_call_ref=None,
            model_routing_policy_ref=None,
            direct_provider_sdk_call=True,
            direct_credential_access=True,
        )
    )
    assert not decision.accepted
    assert _codes(decision) >= {
        "role_agent_dispatch_missing_governance_ref",
        "role_agent_bypassed_llm_gateway",
        "role_agent_direct_credential_access",
    }


def test_verifier_challenge_requires_independent_provider_model_and_context_records():
    decision = validate_role_agent_dispatch(
        _dispatch(
            verifier_challenge=True,
            verifier_provider_ref=None,
            verifier_model_ref=None,
            verifier_context_ref="context:builder",
            builder_context_ref="context:builder",
        )
    )
    assert not decision.accepted
    assert _codes(decision) >= {
        "verifier_independence_record_missing",
        "verifier_reused_builder_context",
    }


def test_agent_code_change_requires_diff_tests_permission_and_rollback():
    decision = validate_agent_code_change(
        _code_change(diff_ref=None, test_result_refs=(), rollback_point_ref=None)
    )
    assert not decision.accepted
    assert _codes(decision) >= {
        "agent_code_change_missing_required_ref",
        "agent_code_change_missing_test_or_validation",
    }


def test_schema_invalid_tool_call_is_rejected():
    decision = validate_agent_tool_call(_tool_call(tool_schema_valid=False, output_ref=None))
    assert not decision.accepted
    assert _codes(decision) >= {"schema_invalid_tool_call_dispatched", "agent_tool_call_missing_record"}


def test_agent_cannot_claim_completion_without_records():
    decision = validate_agent_completion_claim(
        AgentCompletionClaim(
            claim_ref="claim:complete",
            claims_complete=True,
            tool_record_refs=(),
            validation_result_refs=(),
            artifact_refs=(),
        )
    )
    assert not decision.accepted
    assert _codes(decision) >= {
        "agent_completion_missing_tool_records",
        "agent_completion_missing_validation",
        "agent_completion_missing_artifacts",
    }


def test_complete_agent_os_contract_accepts_audited_flow():
    decision = validate_agent_os_contract(
        events=(_event(),),
        plans=(_plan(),),
        dispatches=(
            _dispatch(
                verifier_challenge=True,
                verifier_provider_ref="provider:openai",
                verifier_model_ref="model:gpt",
                verifier_context_ref="context:critic",
                builder_context_ref="context:builder",
            ),
        ),
        code_changes=(_code_change(),),
        tool_calls=(_tool_call(),),
        completion_claims=(
            AgentCompletionClaim(
                claim_ref="claim:complete",
                claims_complete=True,
                tool_record_refs=("tool_call:001",),
                validation_result_refs=("pytest:001",),
                artifact_refs=("artifact:output",),
            ),
        ),
    )
    assert decision.accepted
    assert decision.violations == ()
