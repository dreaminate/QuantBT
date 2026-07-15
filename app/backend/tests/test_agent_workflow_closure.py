from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, replace
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.agent.llm_client import LLMResponse
from app.research_os import (
    AGENT_WORKFLOW_ENTRYPOINT_REF,
    AssetRAGDocument,
    AgentWorkflowClosureError,
    AgentWorkflowClosureSectionAdapter,
    AgentWorkflowClosureSnapshot,
    AgentWorkflowComponentState,
    GoalSectionSemanticProofRecord,
    PersistentCompilerIRStore,
    PersistentAgentWorkflowClosureRegistry,
    PersistentGoalEntrypointCoverageRegistry,
    PersistentGoalValidationReceiptRegistry,
    PersistentResearchAssetRAGIndex,
    RAGPermission,
    ResearchGraphStore,
    build_real_platform_coverage_resolver,
    agent_workflow_closure_semantic_material,
    goal_section_semantic_proof_identity,
    validate_agent_workflow_closure_snapshot,
)
from app.llm import PersistentLLMUseBindingStore, build_agent_llm_gateway
from app.llm.call_record import (
    IndependenceRecord,
    LLMCallRecord,
    ReplayState,
    bind_review_verifier_record,
    evaluate_independence,
    make_review_subject_binding,
)
from app.llm.call_record_store import LLMCallRecordStore
from app.lineage.ids import canonical_json, content_hash
from app.research_os.goal_coverage import GoalEntrypointCoverageRecord
from app.research_os.goal_proof_ledger import GoalProofLedger
from app.agent.orchestrator.events import PersistentWorkflowEventLedger, WorkflowEvent
from app.agent.orchestrator.capability_ledger import (
    CAPABILITY_CODE_CHANGE,
    CAPABILITY_DAG_CHECKPOINT,
    CAPABILITY_DAG_FORK,
    CAPABILITY_DAG_REPLAY,
    CAPABILITY_DAG_ROLLBACK,
    CAPABILITY_PLAN,
    CAPABILITY_REACT,
    CAPABILITY_REPAIR,
    CAPABILITY_REPLAY,
    CAPABILITY_REVIEW,
    AgentCapabilityError,
    PersistentAgentCapabilityLedger,
    validate_review_capability_evidence,
)
from app.security import InMemoryKeystore, KeystoreRecord, SecureKeystore
from app.strategy_goal_store import StrategyGoalStore


OWNER = "owner-a"
WORKFLOW = "agentwf_" + "a" * 64


def _hash(value: str) -> str:
    return "sha256:" + hashlib.sha256(value.encode("utf-8")).hexdigest()


def _digest_ref(prefix: str, value: object) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return f"{prefix}:sha256:{hashlib.sha256(encoded).hexdigest()}"


def _component(
    ref: str,
    *,
    status: str,
    links: dict[str, str],
    owner: str = OWNER,
    revision: str = "1",
    salt: str = "",
) -> AgentWorkflowComponentState:
    return AgentWorkflowComponentState(
        component_ref=ref,
        principal_id=owner,
        revision=revision,
        state_hash=_hash(ref + status + salt),
        status=status,
        links=tuple(links.items()),
    )


def _event(
    sequence: int,
    kind: str,
    *,
    status: str = "recorded",
    extra: dict[str, str] | None = None,
    salt: str = "",
) -> AgentWorkflowComponentState:
    return _component(
        f"workflow_event:{sequence:02d}:{kind}",
        status=status,
        links={
            "workflow_id": WORKFLOW,
            "sequence": str(sequence),
            "kind": kind,
            **(extra or {}),
        },
        salt=salt,
    )


def _capability(
    kind: str,
    *,
    status: str,
    source_ref: str,
    extra: dict[str, str] | None = None,
) -> AgentWorkflowComponentState:
    return _component(
        "agent_capability:" + hashlib.sha256(kind.encode("utf-8")).hexdigest(),
        status=status,
        links={
            "workflow_id": WORKFLOW,
            "capability_kind": kind,
            "previous_record_ref": "",
            "source_ref": source_ref,
            **(extra or {}),
        },
    )


def _snapshot(*, salt: str = "") -> AgentWorkflowClosureSnapshot:
    call_one = "llm_call:terminal:one"
    call_two = "llm_call:terminal:two"
    attempt_one = "llm_call:attempt:one"
    attempt_two = "llm_call:attempt:two"
    binding_one = "llm_gateway_use_binding:one"
    binding_two = "llm_gateway_use_binding:two"
    tool_call_ref = "tool_call:" + "9" * 64
    rag_ref = "rag_usage:agent_workflow:one"
    qro_ref = "qro:agent_workflow:one"
    graph_ref = "research_graph_command:agent_workflow:one"
    ir_ref = "compiler_ir:agent_workflow:one"
    pass_ref = "compiler_pass:agent_workflow:one"
    coverage_ref = "goal_entrypoint_coverage:agent_workflow:one"
    events = (
        _event(1, "AgentPlanCreated"),
        _event(2, "TodoUpdated"),
        _event(3, "RoleAgentDispatched"),
        _event(
            4,
            "ToolCallStarted",
            extra={
                "tool_name": "strategy_goal.create",
                "node_id": "production-turn",
                "tool_call_ref": tool_call_ref,
            },
        ),
        _event(
            5,
            "ToolCallFinished",
            status="succeeded",
            extra={
                "tool_name": "strategy_goal.create",
                "node_id": "production-turn",
                "tool_call_ref": tool_call_ref,
                "ok": "true",
            },
        ),
        _event(
            6,
            "LLMRouteSelected",
            extra={"invocation_id": "orch:one", "attempt_no": "1"},
        ),
        _event(
            7,
            "CredentialPoolSelected",
            extra={"invocation_id": "orch:one", "attempt_no": "1"},
        ),
        _event(
            8,
            "LLMCallStarted",
            extra={"invocation_id": "orch:one", "attempt_no": "1"},
        ),
        _event(
            9,
            "LLMCallFinished",
            extra={
                "invocation_id": "orch:one",
                "attempt_no": "1",
                "call_ref": call_one,
            },
        ),
        _event(
            10,
            "LLMRouteSelected",
            extra={"invocation_id": "orch:two", "attempt_no": "1"},
        ),
        _event(
            11,
            "CredentialPoolSelected",
            extra={"invocation_id": "orch:two", "attempt_no": "1"},
        ),
        _event(
            12,
            "LLMCallStarted",
            extra={"invocation_id": "orch:two", "attempt_no": "1"},
        ),
        _event(
            13,
            "LLMCallFinished",
            extra={
                "invocation_id": "orch:two",
                "attempt_no": "1",
                "call_ref": call_two,
            },
        ),
        _event(14, "RagHitUsed", extra={"usage_ref": rag_ref}),
        _event(15, "ArtifactProduced"),
        _event(
            16,
            "RunVerdictProduced",
            status="succeeded",
            extra={"succeeded": "true"},
        ),
        _event(17, "VerifierChallengeRaised"),
        _event(
            18,
            "RunVerdictProduced",
            status="succeeded",
            extra={"succeeded": "true"},
        ),
        _event(
            19,
            "FailureDetected",
            extra={"failure_ref": "agent_failure:repair-one"},
        ),
        _event(
            20,
            "RepairAttempted",
            extra={"failure_ref": "agent_failure:repair-one"},
        ),
        _event(
            21,
            "RunVerdictProduced",
            status="succeeded",
            extra={"succeeded": "true"},
            salt=salt,
        ),
    )
    terminal_calls = (
        _component(
            call_one,
            status="ok",
            links={
                "workflow_id": WORKFLOW,
                "invocation_id": "orch:one",
                "binding_ref": binding_one,
            },
        ),
        _component(
            call_two,
            status="ok",
            links={
                "workflow_id": WORKFLOW,
                "invocation_id": "orch:two",
                "binding_ref": binding_two,
            },
        ),
    )
    llm_attempts = (
        _component(
            attempt_one,
            status="ok",
            links={
                "workflow_id": WORKFLOW,
                "invocation_id": "orch:one",
                "attempt_no": "1",
                "record_kind": "attempt",
                "terminal_call_ref": call_one,
                "failure_stage": "",
            },
        ),
        _component(
            attempt_two,
            status="ok",
            links={
                "workflow_id": WORKFLOW,
                "invocation_id": "orch:two",
                "attempt_no": "1",
                "record_kind": "attempt",
                "terminal_call_ref": call_two,
                "failure_stage": "",
            },
        ),
    )
    bindings = (
        _component(
            binding_one,
            status="active",
            links={
                "workflow_id": WORKFLOW,
                "invocation_id": "orch:one",
                "terminal_call_ref": call_one,
            },
        ),
        _component(
            binding_two,
            status="active",
            links={
                "workflow_id": WORKFLOW,
                "invocation_id": "orch:two",
                "terminal_call_ref": call_two,
            },
        ),
    )
    dag_checkpoint_ref = _capability(
        "dag_checkpoint",
        status="succeeded",
        source_ref="dag_run:sha256:" + "1" * 64,
    ).component_ref
    dag_replay_ref = _capability(
        "dag_replay",
        status="succeeded",
        source_ref="replay:sha256:" + "2" * 64,
    ).component_ref
    code_change_ref = "agent_code_change:sha256:" + "3" * 64
    permission_ref = "agent_repair_permission:workflow:operation:user_manual"
    capability_heads = (
        _capability(
            "plan",
            status="ready",
            source_ref=events[0].component_ref,
        ),
        _capability(
            "review",
            status="passed",
            source_ref=events[16].component_ref,
            extra={
                "source_event_ref": events[16].component_ref,
                "builder_call_ref": call_one,
                "verifier_call_ref": call_two,
            },
        ),
        _capability(
            "react",
            status="succeeded",
            source_ref=events[15].component_ref,
            extra={
                "source_event_ref": events[15].component_ref,
                "dag_record_ref": dag_checkpoint_ref,
            },
        ),
        _capability(
            "replay",
            status="succeeded",
            source_ref=events[17].component_ref,
            extra={
                "source_event_ref": events[17].component_ref,
                "dag_record_ref": dag_replay_ref,
            },
        ),
        _capability(
            "repair",
            status="recorded",
            source_ref=events[19].component_ref,
            extra={
                "failure_ref": "agent_failure:repair-one",
                "failure_event_ref": events[18].component_ref,
                "repair_event_ref": events[19].component_ref,
                "code_change_ref": code_change_ref,
                "permission_ref": permission_ref,
            },
        ),
        _capability(
            "agent_code_change",
            status="recorded",
            source_ref=code_change_ref,
            extra={
                "source_event_ref": events[19].component_ref,
                "code_change_ref": code_change_ref,
                "permission_ref": permission_ref,
            },
        ),
        _capability(
            "dag_checkpoint",
            status="succeeded",
            source_ref="dag_run:sha256:" + "1" * 64,
        ),
        _capability(
            "dag_replay",
            status="succeeded",
            source_ref="replay:sha256:" + "2" * 64,
        ),
        _capability(
            "dag_fork",
            status="succeeded",
            source_ref="fork:sha256:" + "4" * 64,
            extra={
                "from_task_id": "capability-builder",
                "overrides_ref": "sha256:" + "5" * 64,
            },
        ),
        _capability(
            "dag_rollback",
            status="succeeded",
            source_ref="rollback:sha256:" + "6" * 64,
            extra={"to_task_id": "capability-builder"},
        ),
    )
    return AgentWorkflowClosureSnapshot(
        owner_user_id=OWNER,
        workflow_id=WORKFLOW,
        events=events,
        terminal_calls=terminal_calls,
        llm_attempts=llm_attempts,
        llm_use_bindings=bindings,
        capability_heads=capability_heads,
        rag_usage=_component(
            rag_ref,
            status="accepted",
            links={"workflow_id": WORKFLOW, "qro_ref": qro_ref},
        ),
        qro=_component(
            qro_ref,
            status="current",
            links={
                "workflow_id": WORKFLOW,
                "rag_usage_ref": rag_ref,
                "graph_command_ref": graph_ref,
                "coverage_ref": coverage_ref,
            },
            salt=salt,
        ),
        graph_command=_component(
            graph_ref,
            status="current",
            links={"qro_ref": qro_ref, "coverage_ref": coverage_ref},
        ),
        compiler_ir=_component(
            ir_ref,
            status="current",
            links={
                "qro_ref": qro_ref,
                "graph_command_ref": graph_ref,
                "compiler_pass_ref": pass_ref,
                "coverage_ref": coverage_ref,
            },
        ),
        compiler_pass=_component(
            pass_ref,
            status="passed",
            links={"compiler_ir_ref": ir_ref, "coverage_ref": coverage_ref},
        ),
        entrypoint_coverage=_component(
            coverage_ref,
            status="current",
            links={
                "entry_source": "agent_shell",
                "entrypoint_ref": AGENT_WORKFLOW_ENTRYPOINT_REF,
                "workflow_id": WORKFLOW,
                "rag_usage_ref": rag_ref,
                "qro_ref": qro_ref,
                "graph_command_ref": graph_ref,
                "compiler_ir_ref": ir_ref,
                "compiler_pass_ref": pass_ref,
            },
        ),
    )


class _CoverageRegistry:
    def __init__(self, snapshot: AgentWorkflowClosureSnapshot) -> None:
        self.accepted = True
        self.coverage_record = SimpleNamespace(
            coverage_ref=snapshot.entrypoint_coverage.component_ref,
            entry_source="agent_shell",
            entrypoint_ref=AGENT_WORKFLOW_ENTRYPOINT_REF,
            goal_sections=("§7",),
            qro_refs=(snapshot.qro.component_ref,),
            research_graph_command_refs=(snapshot.graph_command.component_ref,),
            compiler_ir_refs=(snapshot.compiler_ir.component_ref,),
            compiler_pass_refs=(snapshot.compiler_pass.component_ref,),
            validation_refs=("validation:agent_workflow:tool_and_verdict",),
            silent_mock_fallback_used=False,
            raw_payload_persisted=False,
        )

    def coverage(self, coverage_ref: str, *, owner: str):
        if owner != OWNER or coverage_ref != self.coverage_record.coverage_ref:
            raise KeyError(coverage_ref)
        return self.coverage_record

    def validate_real_backing(self, _coverage):
        return SimpleNamespace(accepted=self.accepted)


def _semantic_record(receipt, coverage_registry: _CoverageRegistry):
    validation_refs = coverage_registry.coverage_record.validation_refs
    material = agent_workflow_closure_semantic_material(
        receipt,
        validation_refs=validation_refs,
    )
    values = {
        "section": "§7",
        "subject_ref": material.subject_ref,
        "producer_refs": material.producer_refs,
        "store_refs": material.store_refs,
        "consumer_refs": material.consumer_refs,
        "gate_verdict_refs": material.gate_verdict_refs,
        "test_refs": material.test_refs,
        "entrypoint_coverage_refs": (
            coverage_registry.coverage_record.coverage_ref,
        ),
        "recorded_by": OWNER,
        "claims_section_complete": True,
        "unverified_residuals": (),
    }
    return GoalSectionSemanticProofRecord(
        proof_ref=goal_section_semantic_proof_identity(**values),
        **values,
    )


def test_agent_workflow_closure_persists_reloads_and_semantic_adapter_accepts(tmp_path):
    current = [_snapshot()]
    path = tmp_path / "agent_workflow_closure.jsonl"
    registry = PersistentAgentWorkflowClosureRegistry(
        path,
        resolve_snapshot=lambda owner, workflow: current[0],
    )

    receipt = registry.record_current(OWNER, WORKFLOW)
    assert receipt.record_revision == 1
    assert receipt.previous_receipt_ref == ""
    assert registry.record_current(OWNER, WORKFLOW) == receipt

    reopened = PersistentAgentWorkflowClosureRegistry(
        path,
        resolve_snapshot=lambda owner, workflow: current[0],
    )
    assert reopened.validate_current(receipt.receipt_ref, owner_user_id=OWNER).accepted
    coverage = _CoverageRegistry(current[0])
    decision = AgentWorkflowClosureSectionAdapter(coverage, reopened).validate(
        _semantic_record(receipt, coverage),
        owner=OWNER,
    )
    assert decision.accepted, decision.violations


def test_agent_workflow_closure_rejects_cross_workflow_recombination_and_owner_mismatch():
    snapshot = _snapshot()
    foreign_workflow = "agentwf_" + "b" * 64
    recombined = replace(
        snapshot,
        rag_usage=replace(
            snapshot.rag_usage,
            links=(("qro_ref", snapshot.qro.component_ref), ("workflow_id", foreign_workflow)),
        ),
    )
    decision = validate_agent_workflow_closure_snapshot(
        recombined,
        owner_user_id=OWNER,
        workflow_id=WORKFLOW,
    )
    assert not decision.accepted
    assert "agent_workflow_lineage_mismatch" in {item.code for item in decision.violations}

    owner_mismatch = validate_agent_workflow_closure_snapshot(
        snapshot,
        owner_user_id="owner-b",
        workflow_id=WORKFLOW,
    )
    assert not owner_mismatch.accepted
    assert "agent_workflow_owner_mismatch" in {
        item.code for item in owner_mismatch.violations
    }


def test_agent_workflow_closure_requires_all_current_capability_heads_and_exact_joins():
    snapshot = _snapshot()
    missing = replace(snapshot, capability_heads=snapshot.capability_heads[:-1])
    decision = validate_agent_workflow_closure_snapshot(
        missing,
        owner_user_id=OWNER,
        workflow_id=WORKFLOW,
    )
    assert "agent_workflow_required_capabilities_missing" in {
        item.code for item in decision.violations
    }

    react = next(
        capability
        for capability in snapshot.capability_heads
        if capability.link_map["capability_kind"] == "react"
    )
    broken_react = replace(
        react,
        links=tuple(
            (key, "agent_capability:" + "f" * 64)
            if key == "dag_record_ref"
            else (key, value)
            for key, value in react.links
        ),
    )
    recombined = replace(
        snapshot,
        capability_heads=tuple(
            broken_react if capability is react else capability
            for capability in snapshot.capability_heads
        ),
    )
    decision = validate_agent_workflow_closure_snapshot(
        recombined,
        owner_user_id=OWNER,
        workflow_id=WORKFLOW,
    )
    assert "agent_workflow_capability_relationship_invalid" in {
        item.code for item in decision.violations
    }


def test_agent_workflow_closure_rejects_missing_tool_failure_and_placeholder():
    snapshot = _snapshot()
    without_tools = replace(
        snapshot,
        events=tuple(
            event
            for event in snapshot.events
            if event.link_map["kind"] not in {"ToolCallStarted", "ToolCallFinished"}
        ),
    )
    # Keep the remaining event sequence contiguous so this isolates the tool gate.
    without_tools = replace(
        without_tools,
        events=tuple(
            replace(
                event,
                links=tuple(
                    (key, str(index) if key == "sequence" else value)
                    for key, value in event.links
                ),
            )
            for index, event in enumerate(without_tools.events, start=1)
        ),
    )
    decision = validate_agent_workflow_closure_snapshot(
        without_tools,
        owner_user_id=OWNER,
        workflow_id=WORKFLOW,
    )
    codes = {item.code for item in decision.violations}
    assert "agent_workflow_required_events_missing" in codes
    assert "agent_workflow_successful_tool_missing" in codes

    failed = replace(
        snapshot,
        events=(*snapshot.events[:-1], _event(15, "FailureDetected"), snapshot.events[-1]),
    )
    decision = validate_agent_workflow_closure_snapshot(
        failed,
        owner_user_id=OWNER,
        workflow_id=WORKFLOW,
    )
    assert "agent_workflow_failure_pair_invalid" in {
        item.code for item in decision.violations
    }

    placeholder = replace(
        snapshot,
        qro=replace(snapshot.qro, component_ref="fixture:qro"),
    )
    decision = validate_agent_workflow_closure_snapshot(
        placeholder,
        owner_user_id=OWNER,
        workflow_id=WORKFLOW,
    )
    assert "agent_workflow_component_placeholder" in {
        item.code for item in decision.violations
    }


def _resequence_events(events):
    return tuple(
        replace(
            event,
            links=tuple(
                (key, str(sequence) if key == "sequence" else value)
                for key, value in event.links
            ),
        )
        for sequence, event in enumerate(events, start=1)
    )


def test_agent_workflow_closure_rejects_malformed_llm_and_tool_state_machines():
    snapshot = _snapshot()
    events = list(snapshot.events)

    # Move invocation one's finish before its start while preserving a valid
    # durable sequence. Presence-only validation used to accept this.
    events[7], events[8] = events[8], events[7]
    reordered = replace(snapshot, events=_resequence_events(events))
    decision = validate_agent_workflow_closure_snapshot(
        reordered,
        owner_user_id=OWNER,
        workflow_id=WORKFLOW,
    )
    assert "agent_workflow_llm_state_invalid" in {
        item.code for item in decision.violations
    }

    duplicate_finish = _event(
        99,
        "LLMCallFinished",
        extra={
            "invocation_id": "orch:one",
            "attempt_no": "1",
            "call_ref": "llm_call:terminal:one",
        },
        salt="duplicate-finish",
    )
    duplicated_llm = replace(
        snapshot,
        events=_resequence_events(
            (*snapshot.events[:-1], duplicate_finish, snapshot.events[-1])
        ),
    )
    decision = validate_agent_workflow_closure_snapshot(
        duplicated_llm,
        owner_user_id=OWNER,
        workflow_id=WORKFLOW,
    )
    assert "agent_workflow_llm_state_invalid" in {
        item.code for item in decision.violations
    }

    tool_finish = snapshot.events[4]
    duplicate_tool_finish = replace(
        tool_finish,
        component_ref="workflow_event:duplicate-tool-finish",
        state_hash=_hash("duplicate-tool-finish"),
    )
    duplicated_tool = replace(
        snapshot,
        events=_resequence_events(
            (*snapshot.events[:-1], duplicate_tool_finish, snapshot.events[-1])
        ),
    )
    decision = validate_agent_workflow_closure_snapshot(
        duplicated_tool,
        owner_user_id=OWNER,
        workflow_id=WORKFLOW,
    )
    assert "agent_workflow_tool_pair_invalid" in {
        item.code for item in decision.violations
    }

    unmatched_start = _event(
        100,
        "ToolCallStarted",
        extra={
            "tool_name": "rag.search",
            "node_id": "production-turn",
            "tool_call_ref": "tool_call:" + "8" * 64,
        },
    )
    unmatched = replace(
        snapshot,
        events=_resequence_events(
            (*snapshot.events[:-1], unmatched_start, snapshot.events[-1])
        ),
    )
    decision = validate_agent_workflow_closure_snapshot(
        unmatched,
        owner_user_id=OWNER,
        workflow_id=WORKFLOW,
    )
    assert "agent_workflow_tool_pair_invalid" in {
        item.code for item in decision.violations
    }


def test_agent_workflow_closure_audits_complete_fallback_attempt_chain():
    snapshot = _snapshot()
    call_one = snapshot.terminal_calls[0].component_ref
    fallback_events = _resequence_events(
        (
            *snapshot.events[:8],
            _event(
                9,
                "ProviderFallbackUsed",
                extra={
                    "invocation_id": "orch:one",
                    "from_attempt_no": "1",
                    "to_attempt_no": "2",
                },
            ),
            _event(
                10,
                "CredentialPoolSelected",
                extra={"invocation_id": "orch:one", "attempt_no": "2"},
            ),
            _event(
                11,
                "LLMCallStarted",
                extra={"invocation_id": "orch:one", "attempt_no": "2"},
            ),
            _event(
                12,
                "LLMCallFinished",
                extra={
                    "invocation_id": "orch:one",
                    "attempt_no": "2",
                    "call_ref": call_one,
                },
            ),
            *snapshot.events[9:],
        )
    )
    failed_attempt = replace(
        snapshot.llm_attempts[0],
        status="error",
        links=tuple(
            (key, "provider" if key == "failure_stage" else value)
            for key, value in snapshot.llm_attempts[0].links
        ),
    )
    successful_retry = _component(
        "llm_call:attempt:one:retry",
        status="ok",
        revision="2",
        links={
            "workflow_id": WORKFLOW,
            "invocation_id": "orch:one",
            "attempt_no": "2",
            "record_kind": "attempt",
            "terminal_call_ref": call_one,
            "failure_stage": "",
        },
    )
    fallback_snapshot = replace(
        snapshot,
        events=fallback_events,
        terminal_calls=(
            replace(snapshot.terminal_calls[0], revision="2"),
            snapshot.terminal_calls[1],
        ),
        llm_attempts=(
            failed_attempt,
            successful_retry,
            snapshot.llm_attempts[1],
        ),
    )

    accepted = validate_agent_workflow_closure_snapshot(
        fallback_snapshot,
        owner_user_id=OWNER,
        workflow_id=WORKFLOW,
    )
    assert accepted.accepted, accepted.violations

    omitted_failure = replace(
        fallback_snapshot,
        llm_attempts=(successful_retry, snapshot.llm_attempts[1]),
    )
    rejected = validate_agent_workflow_closure_snapshot(
        omitted_failure,
        owner_user_id=OWNER,
        workflow_id=WORKFLOW,
    )
    assert "agent_workflow_llm_attempt_chain_mismatch" in {
        item.code for item in rejected.violations
    }


def test_agent_workflow_closure_requires_visible_strict_rag_usage():
    snapshot = _snapshot()
    missing_visible_rag = replace(
        snapshot,
        events=_resequence_events(
            tuple(
                event
                for event in snapshot.events
                if event.link_map.get("kind") != "RagHitUsed"
            )
        ),
    )
    decision = validate_agent_workflow_closure_snapshot(
        missing_visible_rag,
        owner_user_id=OWNER,
        workflow_id=WORKFLOW,
    )
    codes = {item.code for item in decision.violations}
    assert "agent_workflow_required_events_missing" in codes
    assert "agent_workflow_visible_rag_mismatch" in codes


def test_agent_workflow_closure_stale_backing_and_revision_chain(tmp_path):
    current = [_snapshot()]
    path = tmp_path / "agent_workflow_closure.jsonl"
    registry = PersistentAgentWorkflowClosureRegistry(
        path,
        resolve_snapshot=lambda owner, workflow: current[0],
    )
    first = registry.record_current(OWNER, WORKFLOW)
    current[0] = _snapshot(salt="changed")

    stale = registry.validate_current(first.receipt_ref, owner_user_id=OWNER)
    assert not stale.accepted
    assert "agent_workflow_backing_changed" in {item.code for item in stale.violations}

    second = registry.record_current(OWNER, WORKFLOW)
    assert second.record_revision == 2
    assert second.previous_receipt_ref == first.receipt_ref
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    assert rows[1]["previous_record_hash"] == rows[0]["record_hash"]

    rows[1]["previous_record_hash"] = "sha256:" + "0" * 64
    path.write_text("\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="invalid persisted agent workflow closure row"):
        PersistentAgentWorkflowClosureRegistry(
            path,
            resolve_snapshot=lambda owner, workflow: current[0],
        )


def test_agent_workflow_closure_detects_toctou_without_partial_write(tmp_path):
    snapshots = iter((_snapshot(), _snapshot(salt="raced")))
    path = tmp_path / "agent_workflow_closure.jsonl"
    registry = PersistentAgentWorkflowClosureRegistry(
        path,
        resolve_snapshot=lambda owner, workflow: next(snapshots),
    )
    with pytest.raises(AgentWorkflowClosureError, match="changed during closure resolution"):
        registry.record_current(OWNER, WORKFLOW)
    assert not path.exists()


def test_agent_workflow_closure_rolls_back_post_commit_toctou(tmp_path, monkeypatch):
    current = [_snapshot()]
    path = tmp_path / "agent_workflow_closure.jsonl"
    registry = PersistentAgentWorkflowClosureRegistry(
        path,
        resolve_snapshot=lambda owner, workflow: current[0],
    )
    original_append = registry._atomic_append

    def append_then_race(row):
        original_append(row)
        current[0] = _snapshot(salt="post-commit-race")

    monkeypatch.setattr(registry, "_atomic_append", append_then_race)
    with pytest.raises(
        AgentWorkflowClosureError,
        match="changed while closure was being committed",
    ):
        registry.record_current(OWNER, WORKFLOW)

    assert not path.exists()
    with pytest.raises(KeyError, match="not recorded for owner"):
        registry.receipt(
            "agent_workflow_closure_receipt:missing",
            owner_user_id=OWNER,
        )


def test_agent_workflow_closure_post_commit_rollback_preserves_prior_journal(
    tmp_path,
    monkeypatch,
):
    current = [_snapshot()]
    path = tmp_path / "agent_workflow_closure.jsonl"
    registry = PersistentAgentWorkflowClosureRegistry(
        path,
        resolve_snapshot=lambda owner, workflow: current[0],
    )
    first = registry.record_current(OWNER, WORKFLOW)
    original_bytes = path.read_bytes()
    current[0] = _snapshot(salt="revision-two")
    original_append = registry._atomic_append

    def append_then_race(row):
        original_append(row)
        current[0] = _snapshot(salt="revision-two-raced")

    monkeypatch.setattr(registry, "_atomic_append", append_then_race)
    with pytest.raises(
        AgentWorkflowClosureError,
        match="changed while closure was being committed",
    ):
        registry.record_current(OWNER, WORKFLOW)

    assert path.read_bytes() == original_bytes
    assert registry.receipt(first.receipt_ref, owner_user_id=OWNER) == first


def test_agent_workflow_closure_append_normalizes_missing_terminal_newline(tmp_path):
    current = [_snapshot()]
    path = tmp_path / "agent_workflow_closure.jsonl"
    registry = PersistentAgentWorkflowClosureRegistry(
        path,
        resolve_snapshot=lambda owner, workflow: current[0],
    )
    registry.record_current(OWNER, WORKFLOW)
    path.write_bytes(path.read_bytes().rstrip(b"\n"))
    current[0] = _snapshot(salt="revision-two")

    second = registry.record_current(OWNER, WORKFLOW)

    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    assert len(rows) == 2
    assert rows[1]["receipt"]["receipt_ref"] == second.receipt_ref
    assert path.read_bytes().endswith(b"\n")


def test_agent_workflow_closure_atomic_replace_failure_leaves_no_receipt(tmp_path, monkeypatch):
    import app.research_os.agent_workflow_closure as closure_module

    path = tmp_path / "agent_workflow_closure.jsonl"
    registry = PersistentAgentWorkflowClosureRegistry(
        path,
        resolve_snapshot=lambda owner, workflow: _snapshot(),
    )

    def fail_replace(_source, _target):
        raise OSError("replace-tripwire")

    monkeypatch.setattr(closure_module.os, "replace", fail_replace)
    with pytest.raises(OSError, match="replace-tripwire"):
        registry.record_current(OWNER, WORKFLOW)
    assert not path.exists()


def test_agent_workflow_closure_quarantines_legacy_but_fails_closed_on_adapter_drift(tmp_path):
    path = tmp_path / "agent_workflow_closure.jsonl"
    path.write_text(json.dumps({"schema_version": 1, "legacy": True}) + "\n", encoding="utf-8")
    current = [_snapshot()]
    registry = PersistentAgentWorkflowClosureRegistry(
        path,
        resolve_snapshot=lambda owner, workflow: current[0],
    )
    assert registry.legacy_quarantined_count == 1
    receipt = registry.record_current(OWNER, WORKFLOW)
    coverage = _CoverageRegistry(current[0])
    record = _semantic_record(receipt, coverage)

    coverage.accepted = False
    decision = AgentWorkflowClosureSectionAdapter(coverage, registry).validate(
        record,
        owner=OWNER,
    )
    assert not decision.accepted
    assert any("failed strict current backing" in item.message for item in decision.violations)

    coverage.accepted = True
    coverage.coverage_record.qro_refs = ("qro:other-workflow",)
    decision = AgentWorkflowClosureSectionAdapter(coverage, registry).validate(
        record,
        owner=OWNER,
    )
    assert not decision.accepted
    assert any("qro_refs" in item.message for item in decision.violations)


def _seed_capability_heads(
    path,
    *,
    owner: str,
    workflow: str,
    events: tuple[WorkflowEvent, ...],
    builder_call_ref: str,
    verifier_call_ref: str,
) -> PersistentAgentCapabilityLedger:
    ledger = PersistentAgentCapabilityLedger(path)

    def event_ref(kind: str, occurrence: int = 0) -> str:
        matches = [event.event_id for event in events if event.kind == kind]
        return matches[occurrence]

    def record(kind: str, source_ref: str, payload: dict):
        return ledger._record_action(  # noqa: SLF001 - seed resolver backing stores.
            owner_user_id=owner,
            workflow_id=workflow,
            capability_kind=kind,
            source_ref=source_ref,
            payload=payload,
        )

    dag_payload = {
        "succeeded": True,
        "graph_ref": "dag_graph:sha256:" + "1" * 64,
        "tasks": [],
        "nodes": [],
        "node_id_by_task": [],
        "events_ref": "dag_events:sha256:" + "2" * 64,
    }
    checkpoint = record(
        CAPABILITY_DAG_CHECKPOINT,
        "dag_run:sha256:" + "3" * 64,
        {**dag_payload, "mode": "run", "details": {}},
    )
    dag_replay = record(
        CAPABILITY_DAG_REPLAY,
        "replay:sha256:" + "4" * 64,
        {**dag_payload, "mode": "replay", "details": {}},
    )
    record(
        CAPABILITY_DAG_FORK,
        "fork:sha256:" + "5" * 64,
        {
            **dag_payload,
            "mode": "fork",
            "details": {
                "from_task_id": "capability-builder",
                "overrides_ref": "sha256:" + "6" * 64,
            },
        },
    )
    record(
        CAPABILITY_DAG_ROLLBACK,
        "rollback:sha256:" + "7" * 64,
        {
            **dag_payload,
            "mode": "rollback",
            "details": {"to_task_id": "capability-builder"},
        },
    )
    plan_event_ref = event_ref("AgentPlanCreated")
    record(
        CAPABILITY_PLAN,
        plan_event_ref,
        {
            "source_event_refs": [plan_event_ref],
            "plan_digest": "plan:sha256:" + "8" * 64,
            "status": "ready",
            "todos": [],
            "dependencies": [],
            "risk_refs": [],
            "acceptance_gates": [],
            "handoff_refs": [],
            "rollback_point_refs": [],
        },
    )
    review_event_ref = event_ref("VerifierChallengeRaised")
    review_builder = _closure_llm_record(
        builder_call_ref,
        owner,
        workflow,
        "invocation-builder",
        provider="anthropic",
        model="builder-model",
        prompt_digest="prompt:sha256:" + "9" * 64,
    )
    review_verifier = _closure_llm_record(
        verifier_call_ref,
        owner,
        workflow,
        "invocation-verifier",
        provider="openai",
        model="verifier-model",
        prompt_digest="prompt:sha256:" + "a" * 64,
        independence=IndependenceRecord(
            required=True,
            satisfied=True,
            distinct_provider=True,
            distinct_model=True,
            builder_call_id=builder_call_ref,
        ),
    )
    review_binding = _review_subject_binding(review_builder, review_verifier)
    record(
        CAPABILITY_REVIEW,
        review_event_ref,
        {
            "source_event_ref": review_event_ref,
            "builder_call_ref": builder_call_ref,
            "builder_provider": "anthropic",
            "builder_model": "builder-model",
            "builder_context_ref": "prompt:sha256:" + "9" * 64,
            "builder_response_ref": review_binding.builder_response_ref,
            "builder_artifact_ref": review_binding.builder_artifact_ref,
            "builder_output_ref": review_binding.builder_output_ref,
            "verifier_call_ref": verifier_call_ref,
            "verifier_provider": "openai",
            "verifier_model": "verifier-model",
            "verifier_context_ref": "prompt:sha256:" + "a" * 64,
            "review_binding_schema_version": review_binding.schema_version,
            "review_criteria_ref": review_binding.review_criteria_ref,
            "review_subject_ref": review_binding.review_subject_ref,
            "verifier_input_ref": review_binding.verifier_input_ref,
            "verifier_prompt_binding_ref": review_binding.verifier_prompt_binding_ref,
            "declared_builder_call_ref": builder_call_ref,
            "independence_required": True,
            "independence_claimed_satisfied": True,
            "distinct_provider": True,
            "distinct_model": True,
            "independent": True,
            "verdict_reason_ref": _digest_ref(
                "review_reason",
                "verifier 与 builder provider/model 不同源——独立性成立",
            ),
        },
    )
    react_event_ref = event_ref("RunVerdictProduced", 0)
    record(
        CAPABILITY_REACT,
        react_event_ref,
        {
            "source_event_ref": react_event_ref,
            "dag_record_ref": checkpoint.record_ref,
            "succeeded": True,
            "node_checkpoint_refs": [],
        },
    )
    replay_event_ref = event_ref("RunVerdictProduced", 1)
    record(
        CAPABILITY_REPLAY,
        replay_event_ref,
        {
            "source_event_ref": replay_event_ref,
            "dag_record_ref": dag_replay.record_ref,
            "succeeded": True,
            "node_checkpoint_refs": [],
        },
    )
    failure_event_ref = event_ref("FailureDetected")
    repair_event_ref = event_ref("RepairAttempted")
    failure_ref = "agent_failure:resolver"
    code_change_ref = "agent_code_change:sha256:" + "c" * 64
    permission_ref = "agent_repair_permission:resolver:user_manual"
    record(
        CAPABILITY_CODE_CHANGE,
        code_change_ref,
        {
            "code_change_ref": code_change_ref,
            "path_ref": "code_path:sha256:" + "d" * 64,
            "diff_ref": "code_diff:sha256:" + "e" * 64,
            "test_result_ref": "code_test:sha256:" + "f" * 64,
            "rollback_point_ref": "code_rollback:sha256:" + "1" * 64,
            "permission_ref": permission_ref,
            "theory_implementation_binding_ref": "",
            "claims_theory_backed": False,
            "source_event_ref": repair_event_ref,
        },
    )
    record(
        CAPABILITY_REPAIR,
        repair_event_ref,
        {
            "source_event_refs": [failure_event_ref, repair_event_ref],
            "failure_ref": failure_ref,
            "code_change_ref": code_change_ref,
            "permission_ref": permission_ref,
        },
    )
    return ledger


def _closure_llm_record(
    call_id: str,
    owner: str,
    workflow: str,
    invocation_id: str,
    *,
    provider: str,
    model: str,
    prompt_digest: str,
    record_kind: str = "terminal",
    independence: IndependenceRecord | None = None,
    started_at: str = "2026-07-12T00:00:00+00:00",
) -> LLMCallRecord:
    output = f"output:{call_id}"
    return LLMCallRecord(
        provider=provider,
        model=model,
        auth_ref=f"secretref://{provider}/closure-test",
        replay_state=ReplayState.LIVE.value,
        owner_user_id=owner,
        workflow_id=workflow,
        invocation_id=invocation_id,
        record_kind=record_kind,
        attempt_no=1,
        independence=independence or IndependenceRecord(),
        call_id=call_id,
        prompt_digest=prompt_digest,
        response_digest=content_hash({"content": output, "tool_calls": []}),
        started_at=started_at,
        status="ok",
    )


def _review_subject_binding(builder: LLMCallRecord, verifier: LLMCallRecord):
    output = f"output:{builder.call_id}"
    output_ref = hashlib.sha256(canonical_json(output).encode("utf-8")).hexdigest()
    binding, _instruction = make_review_subject_binding(
        builder=builder,
        builder_artifact_ref=f"artifact:{builder.call_id}",
        builder_artifact_output_ref=output_ref,
        builder_output=output,
        review_criteria="challenge the exact builder output",
    )
    return bind_review_verifier_record(binding, verifier)


@dataclass(frozen=True)
class _BindingRecord:
    binding_ref: str
    owner_user_id: str
    workflow_id: str
    invocation_id: str
    terminal_call_id: str
    record_revision: int
    state_hash: str


@dataclass(frozen=True)
class _StrictUsage:
    usage_id: str
    owner_user_id: str
    workflow_ref: str
    actor: str
    timestamp: str


@dataclass(frozen=True)
class _QRO:
    qro_id: str
    owner: str
    version: int
    evidence_refs: tuple[str, ...]


@dataclass(frozen=True)
class _GraphCommand:
    command_id: str
    actor: str
    source: str
    actor_source: str
    payload: dict
    version: int = 1


@dataclass(frozen=True)
class _CompilerIR:
    ir_ref: str
    owner: str
    source_qro_refs: tuple[str, ...]
    graph_command_refs: tuple[str, ...]
    compiler_version: str = "governed-compiler-ir.v1"


@dataclass(frozen=True)
class _CompilerPass:
    pass_ref: str
    pass_name: str
    input_ir_refs: tuple[str, ...]
    output_ir_ref: str
    input_qro_refs: tuple[str, ...]
    graph_command_refs: tuple[str, ...]
    actor: str
    status: str = "compiled"


@pytest.mark.parametrize(
    ("poison_field", "poison_value"),
    [
        ("builder_provider", "forged-provider"),
        ("verifier_model", "forged-model"),
        ("builder_context_ref", "prompt:sha256:" + "f" * 64),
        ("verifier_context_ref", "prompt:sha256:" + "e" * 64),
        ("builder_response_ref", "swapped-response:" + "d" * 64),
        ("review_subject_ref", "unrelated-subject:" + "c" * 64),
        ("verifier_prompt_binding_ref", "swapped-prompt-binding:" + "b" * 64),
    ],
)
def test_review_evidence_validator_rejects_persisted_claim_mutations(
    tmp_path,
    poison_field,
    poison_value,
):
    builder = _closure_llm_record(
        "llmcall_" + "b" * 64,
        OWNER,
        WORKFLOW,
        "invocation-builder",
        provider="anthropic",
        model="builder-model",
        prompt_digest="prompt:sha256:" + "1" * 64,
    )
    verifier = _closure_llm_record(
        "llmcall_" + "c" * 64,
        OWNER,
        WORKFLOW,
        "invocation-verifier",
        provider="openai",
        model="verifier-model",
        prompt_digest="prompt:sha256:" + "2" * 64,
        independence=IndependenceRecord(
            required=True,
            satisfied=True,
            distinct_provider=True,
            distinct_model=True,
            builder_call_id=builder.call_id,
        ),
    )
    ledger = PersistentAgentCapabilityLedger(tmp_path / "review-evidence.jsonl")
    subject_binding = _review_subject_binding(builder, verifier)
    record = ledger.record_review(
        owner_user_id=OWNER,
        workflow_id=WORKFLOW,
        builder=builder,
        verifier=verifier,
        subject_binding=subject_binding,
        verdict=evaluate_independence(builder, verifier),
        source_event_ref="workflow_event:review",
    )
    poisoned = {**record.payload, poison_field: poison_value}
    with pytest.raises(AgentCapabilityError, match="contradicts terminal evidence"):
        validate_review_capability_evidence(
            owner_user_id=OWNER,
            workflow_id=WORKFLOW,
            builder=builder,
            verifier=verifier,
            payload=poisoned,
        )


def test_review_evidence_validator_rejects_omitted_subject_binding(tmp_path):
    builder = _closure_llm_record(
        "llmcall_" + "b" * 64,
        OWNER,
        WORKFLOW,
        "invocation-builder",
        provider="anthropic",
        model="builder-model",
        prompt_digest="prompt:sha256:" + "1" * 64,
    )
    verifier = _closure_llm_record(
        "llmcall_" + "c" * 64,
        OWNER,
        WORKFLOW,
        "invocation-verifier",
        provider="openai",
        model="verifier-model",
        prompt_digest="prompt:sha256:" + "2" * 64,
        independence=IndependenceRecord(
            required=True,
            satisfied=True,
            distinct_provider=True,
            distinct_model=True,
            builder_call_id=builder.call_id,
        ),
    )
    ledger = PersistentAgentCapabilityLedger(tmp_path / "review-omitted.jsonl")
    record = ledger.record_review(
        owner_user_id=OWNER,
        workflow_id=WORKFLOW,
        builder=builder,
        verifier=verifier,
        subject_binding=_review_subject_binding(builder, verifier),
        verdict=evaluate_independence(builder, verifier),
        source_event_ref="workflow_event:review",
    )
    omitted = dict(record.payload)
    omitted.pop("review_subject_ref")

    with pytest.raises(AgentCapabilityError, match="invalid schema"):
        validate_review_capability_evidence(
            owner_user_id=OWNER,
            workflow_id=WORKFLOW,
            builder=builder,
            verifier=verifier,
            payload=omitted,
        )


def test_review_evidence_validator_rejects_wrong_declared_builder_metadata(tmp_path):
    builder = _closure_llm_record(
        "llmcall_" + "b" * 64,
        OWNER,
        WORKFLOW,
        "invocation-builder",
        provider="anthropic",
        model="builder-model",
        prompt_digest="prompt:sha256:" + "1" * 64,
    )
    verifier = _closure_llm_record(
        "llmcall_" + "c" * 64,
        OWNER,
        WORKFLOW,
        "invocation-verifier",
        provider="openai",
        model="verifier-model",
        prompt_digest="prompt:sha256:" + "2" * 64,
        independence=IndependenceRecord(
            required=True,
            satisfied=True,
            distinct_provider=True,
            distinct_model=True,
            builder_call_id=builder.call_id,
        ),
    )
    ledger = PersistentAgentCapabilityLedger(tmp_path / "review-builder.jsonl")
    subject_binding = _review_subject_binding(builder, verifier)
    record = ledger.record_review(
        owner_user_id=OWNER,
        workflow_id=WORKFLOW,
        builder=builder,
        verifier=verifier,
        subject_binding=subject_binding,
        verdict=evaluate_independence(builder, verifier),
        source_event_ref="workflow_event:review",
    )
    poisoned_verifier = replace(
        verifier,
        independence=replace(
            verifier.independence,
            builder_call_id="llmcall_" + "d" * 64,
        ),
    )
    with pytest.raises(AgentCapabilityError, match="exact builder call"):
        validate_review_capability_evidence(
            owner_user_id=OWNER,
            workflow_id=WORKFLOW,
            builder=builder,
            verifier=poisoned_verifier,
            payload=record.payload,
        )


def test_main_agent_workflow_resolver_joins_real_store_surfaces_and_mints_current_receipt(
    tmp_path,
    monkeypatch,
):
    import app.main as main

    owner = OWNER
    workflow = WORKFLOW
    builder_call_ref = "llmcall_" + "1" * 64
    verifier_call_ref = "llmcall_" + "2" * 64
    builder_binding_ref = "llm_gateway_use_binding:" + "3" * 64
    verifier_binding_ref = "llm_gateway_use_binding:" + "4" * 64
    usage_ref = "rag_usage_" + "3" * 64
    qro_ref = "qro_" + "4" * 64
    command_ref = "rgcmd_" + "5" * 64
    ir_ref = "compiler_ir:" + "6" * 64
    pass_ref = "compiler_pass:" + "7" * 64
    coverage_ref = "goal_entrypoint_coverage:" + "8" * 64

    event_specs = (
        ("AgentPlanCreated", {}, ""),
        ("TodoUpdated", {}, ""),
        ("RoleAgentDispatched", {}, ""),
        (
            "LLMRouteSelected",
            {"invocation_id": "invocation-builder", "attempt_no": 1},
            "",
        ),
        (
            "CredentialPoolSelected",
            {"invocation_id": "invocation-builder", "attempt_no": 1},
            "",
        ),
        (
            "LLMCallStarted",
            {"invocation_id": "invocation-builder", "attempt_no": 1},
            "",
        ),
        (
            "LLMCallFinished",
            {
                "call_id": builder_call_ref,
                "invocation_id": "invocation-builder",
                "attempt_no": 1,
            },
            "",
        ),
        (
            "ToolCallStarted",
            {"tool": "strategy_goal.create", "tool_call_ref": "tool_call:" + "9" * 64},
            "node-1",
        ),
        (
            "ToolCallFinished",
            {
                "tool": "strategy_goal.create",
                "ok": True,
                "tool_call_ref": "tool_call:" + "9" * 64,
            },
            "node-1",
        ),
        ("RagHitUsed", {"usage_ref": usage_ref}, "node-1"),
        ("ArtifactProduced", {}, ""),
        ("RunVerdictProduced", {"succeeded": True}, ""),
        (
            "LLMRouteSelected",
            {"invocation_id": "invocation-verifier", "attempt_no": 1},
            "",
        ),
        (
            "CredentialPoolSelected",
            {"invocation_id": "invocation-verifier", "attempt_no": 1},
            "",
        ),
        (
            "LLMCallStarted",
            {"invocation_id": "invocation-verifier", "attempt_no": 1},
            "",
        ),
        (
            "LLMCallFinished",
            {
                "call_id": verifier_call_ref,
                "invocation_id": "invocation-verifier",
                "attempt_no": 1,
            },
            "",
        ),
        ("VerifierChallengeRaised", {}, ""),
        ("RunVerdictProduced", {"succeeded": True}, ""),
        ("FailureDetected", {"failure_ref": "agent_failure:resolver"}, ""),
        ("RepairAttempted", {"failure_ref": "agent_failure:resolver"}, ""),
        ("RunVerdictProduced", {"succeeded": True}, ""),
    )
    events = tuple(
        WorkflowEvent(
            kind=kind,
            data=data,
            node_id=node_id,
            event_id="workflow_event:"
            + hashlib.sha256(f"event-{sequence}".encode()).hexdigest(),
            owner_user_id=owner,
            workflow_id=workflow,
            sequence=sequence,
        )
        for sequence, (kind, data, node_id) in enumerate(event_specs, start=1)
    )
    builder_terminal = _closure_llm_record(
        builder_call_ref,
        owner,
        workflow,
        "invocation-builder",
        provider="anthropic",
        model="builder-model",
        prompt_digest="prompt:sha256:" + "9" * 64,
    )
    verifier_terminal = _closure_llm_record(
        verifier_call_ref,
        owner,
        workflow,
        "invocation-verifier",
        provider="openai",
        model="verifier-model",
        prompt_digest="prompt:sha256:" + "a" * 64,
        independence=IndependenceRecord(
            required=True,
            satisfied=True,
            distinct_provider=True,
            distinct_model=True,
            builder_call_id=builder_call_ref,
        ),
        started_at="2026-07-12T00:00:01+00:00",
    )
    builder_attempt = _closure_llm_record(
        "llmattempt_" + "0" * 64,
        owner,
        workflow,
        builder_terminal.invocation_id,
        provider=builder_terminal.provider,
        model=builder_terminal.model,
        prompt_digest=builder_terminal.prompt_digest,
        record_kind="attempt",
    )
    verifier_attempt = _closure_llm_record(
        "llmattempt_" + "1" * 64,
        owner,
        workflow,
        verifier_terminal.invocation_id,
        provider=verifier_terminal.provider,
        model=verifier_terminal.model,
        prompt_digest=verifier_terminal.prompt_digest,
        record_kind="attempt",
        started_at="2026-07-12T00:00:01+00:00",
    )
    bindings = {
        builder_call_ref: _BindingRecord(
            builder_binding_ref,
            owner,
            workflow,
            builder_terminal.invocation_id,
            builder_call_ref,
            1,
            _hash("builder-binding"),
        ),
        verifier_call_ref: _BindingRecord(
            verifier_binding_ref,
            owner,
            workflow,
            verifier_terminal.invocation_id,
            verifier_call_ref,
            1,
            _hash("verifier-binding"),
        ),
    }
    usage = _StrictUsage(
        usage_ref,
        owner,
        workflow,
        "agent",
        "2026-07-12T00:00:01+00:00",
    )
    qro = _QRO(qro_ref, owner, 1, (f"rag_usage:{usage_ref}",))
    command = _GraphCommand(
        command_ref,
        owner,
        "agent_shell",
        "agent",
        {"qro": qro},
    )
    compiler_ir = _CompilerIR(ir_ref, owner, (qro_ref,), (command_ref,))
    compiler_pass = _CompilerPass(
        pass_ref,
        "agent_shell_agent_turn_qro_to_research_report_ir",
        (ir_ref,),
        ir_ref,
        (qro_ref,),
        (command_ref,),
        owner,
    )
    coverage = GoalEntrypointCoverageRecord(
        coverage_ref=coverage_ref,
        entry_source="agent_shell",
        entrypoint_ref=AGENT_WORKFLOW_ENTRYPOINT_REF,
        goal_sections=("§7",),
        qro_refs=(qro_ref,),
        research_graph_command_refs=(command_ref,),
        compiler_ir_refs=(ir_ref,),
        compiler_pass_refs=(pass_ref,),
        evidence_refs=(usage_ref,),
        validation_refs=("runtime_validator:agent_workflow",),
        permission_refs=("permission:agent_workflow",),
        replay_refs=("replay:agent_workflow",),
        recorded_by=owner,
    )

    monkeypatch.setattr(
        main,
        "AGENT_WORKFLOW_EVENT_LEDGER",
        SimpleNamespace(events=lambda **_kwargs: events),
    )
    capability_path = tmp_path / "agent_capabilities.jsonl"
    _seed_capability_heads(
        capability_path,
        owner=owner,
        workflow=workflow,
        events=events,
        builder_call_ref=builder_call_ref,
        # Deliberately persisted poison: one call self-reports as two providers.
        verifier_call_ref=builder_call_ref,
    )
    capability_ledger = PersistentAgentCapabilityLedger(capability_path)
    monkeypatch.setattr(main, "_agent_capability_ledger", lambda: capability_ledger)
    monkeypatch.setattr(
        main,
        "LLM_CALL_RECORD_STORE",
        SimpleNamespace(
            llm_records_for=lambda *_args, **_kwargs: (
                builder_attempt,
                builder_terminal,
                verifier_attempt,
                verifier_terminal,
            )
        ),
    )
    monkeypatch.setattr(
        main,
        "LLM_USE_BINDING_STORE",
        SimpleNamespace(
            binding_for_terminal=lambda call_id, **_kwargs: bindings[call_id],
            validate_current=lambda *_args, **_kwargs: SimpleNamespace(
                accepted=True,
                violations=(),
            ),
        ),
    )
    monkeypatch.setattr(
        main,
        "RESEARCH_ASSET_RAG_INDEX",
        SimpleNamespace(
            strict_usage_for_owner=lambda *_args, **_kwargs: usage,
            validate_current_usage=lambda *_args, **_kwargs: SimpleNamespace(
                accepted=True
            ),
        ),
    )
    monkeypatch.setattr(
        main,
        "RESEARCH_GRAPH_STORE",
        SimpleNamespace(
            commands=lambda: [command],
            qro=lambda ref: qro if ref == qro_ref else (_ for _ in ()).throw(KeyError(ref)),
        ),
    )
    monkeypatch.setattr(
        main,
        "COMPILER_IR_STORE",
        SimpleNamespace(
            canonical_ir=lambda ref, **_kwargs: compiler_ir
            if ref == ir_ref
            else (_ for _ in ()).throw(KeyError(ref)),
            canonical_compiler_pass=lambda ref, **_kwargs: compiler_pass
            if ref == pass_ref
            else (_ for _ in ()).throw(KeyError(ref)),
        ),
    )
    monkeypatch.setattr(
        main,
        "GOAL_ENTRYPOINT_COVERAGE_REGISTRY",
        SimpleNamespace(
            canonical_records=lambda **_kwargs: (coverage,),
            validate_real_backing=lambda _record: SimpleNamespace(accepted=True),
        ),
    )

    poisoned_receipt_path = tmp_path / "agent_workflow_closure_poisoned.jsonl"
    poisoned_registry = PersistentAgentWorkflowClosureRegistry(
        poisoned_receipt_path,
        resolve_snapshot=main._resolve_agent_workflow_closure_snapshot,
    )
    with pytest.raises(ValueError, match="contradicts terminal evidence"):
        poisoned_registry.record_current(owner, workflow)
    assert not poisoned_receipt_path.exists()

    review_event_ref = next(
        event.event_id for event in events if event.kind == "VerifierChallengeRaised"
    )
    capability_ledger.record_review(
        owner_user_id=owner,
        workflow_id=workflow,
        builder=builder_terminal,
        verifier=verifier_terminal,
        subject_binding=_review_subject_binding(builder_terminal, verifier_terminal),
        verdict=evaluate_independence(builder_terminal, verifier_terminal),
        source_event_ref=review_event_ref,
    )
    snapshot = main._resolve_agent_workflow_closure_snapshot(owner, workflow)
    decision = validate_agent_workflow_closure_snapshot(
        snapshot,
        owner_user_id=owner,
        workflow_id=workflow,
    )
    assert decision.accepted, decision.violations
    assert tuple(item.component_ref for item in snapshot.llm_attempts) == (
        builder_attempt.call_id,
        verifier_attempt.call_id,
    )

    prepared = capability_ledger.prepare_operation(
        owner_user_id=owner,
        workflow_id=workflow,
        target_kind=CAPABILITY_PLAN,
        request_ref="request:closure-pending-proof",
    )
    with pytest.raises(ValueError, match="unresolved capability operations"):
        main._resolve_agent_workflow_closure_snapshot(owner, workflow)
    capability_ledger.abort_operation(
        owner_user_id=owner,
        workflow_id=workflow,
        prepared_record_ref=prepared.record_ref,
        failure_ref="failure:closure-pending-proof",
    )

    registry = PersistentAgentWorkflowClosureRegistry(
        tmp_path / "agent_workflow_closure_main.jsonl",
        resolve_snapshot=main._resolve_agent_workflow_closure_snapshot,
    )
    receipt = registry.record_current(owner, workflow)
    assert registry.validate_current(receipt.receipt_ref, owner_user_id=owner).accepted


class _ToolThenFinalProvider:
    """Scripted offline client for route/ledger wiring tests only.

    It is one in-process object behind configured route labels and therefore is
    not evidence of two real providers or remote-backend independence.
    """

    def __init__(self) -> None:
        self.calls = 0
        self.message_batches = []

    def chat(self, messages, *, tools=None, model=None, temperature=0.2):  # noqa: ANN001, ARG002
        self.calls += 1
        self.message_batches.append(tuple(messages))
        if self.calls == 1:
            return LLMResponse(
                content="",
                tool_calls=(
                    {
                        "id": "closure-tool-call",
                        "name": "strategy_goal.create",
                        "arguments": (
                            '{"asset_class":"crypto_perp","objective":"max_calmar",'
                            '"horizon":"daily"}'
                        ),
                    },
                ),
            )
        return LLMResponse(content="grounded workflow complete")


def _sse_done_payload(raw: str) -> dict:
    for block in reversed(raw.split("\n\n")):
        lines = block.splitlines()
        if "event: done" not in lines:
            continue
        return json.loads(next(line[6:] for line in lines if line.startswith("data: ")))
    raise AssertionError("workbench stream did not emit a done event")


def test_workbench_to_agent_workflow_closure_endpoint_uses_scripted_offline_ledger_wiring(
    tmp_path,
    monkeypatch,
):
    import app.main as main

    owner = "user-agent-closure-e2e"
    graph = ResearchGraphStore()
    proof_ledger = GoalProofLedger(tmp_path / "goal_proof_ledger")
    compiler = PersistentCompilerIRStore(
        tmp_path / "compiler_ir.jsonl",
        proof_ledger=proof_ledger,
        legacy_read_only=True,
    )
    validations = PersistentGoalValidationReceiptRegistry(
        tmp_path / "goal_validation_receipts.jsonl",
        proof_ledger=proof_ledger,
        legacy_read_only=True,
    )
    rag = PersistentResearchAssetRAGIndex(tmp_path / "research_asset_rag.jsonl")
    call_store = LLMCallRecordStore(tmp_path / "llm_call_records.jsonl")
    binding_store = PersistentLLMUseBindingStore(
        tmp_path / "llm_use_bindings.jsonl",
        seal_secret=call_store.seal_secret,
        terminal_record_resolver=call_store.resolve_terminal_record,
    )
    event_ledger = PersistentWorkflowEventLedger(tmp_path / "workflow_events.jsonl")
    rag.add_for_owner(
        AssetRAGDocument(
            source_id="source:agent-closure",
            version="v1",
            title="Agent closure candidate context",
            body="portfolio covariance shrinkage candidate research context",
            projection="ResearchRAG",
            asset_ref="asset:agent-closure",
            permission=RAGPermission(
                allowed_users=(owner,),
                allowed_desks=("research",),
                allowed_assets=("asset:agent-closure",),
                permission_tags=("research.read",),
            ),
            applicability="candidate context only",
            source_kind="EvidenceSpan",
            evidence_label="candidate_context",
        ),
        owner_user_id=owner,
    )
    coverage = PersistentGoalEntrypointCoverageRegistry(
        tmp_path / "goal_entrypoint_coverage.jsonl",
        resolver=build_real_platform_coverage_resolver(
            research_graph_store=graph,
            lifecycle_registry=main.ASSET_LIFECYCLE_REGISTRY,
            governance_registry=main.MODEL_GOVERNANCE_REGISTRY,
            rag_index=rag,
            spine_chain_registry=main.MATHEMATICAL_SPINE_CHAIN_REGISTRY,
            compiler_store=compiler,
            document_store=main.DOCUMENT_INTELLIGENCE_STORE,
            goal_validation_receipt_registry=validations,
        ),
        proof_ledger=proof_ledger,
        legacy_read_only=True,
    )
    keystore = SecureKeystore(InMemoryKeystore())
    keystore.store(
        KeystoreRecord(
            name="llm_anthropic",
            api_key="sk-offline-agent-closure-0123456789",
            api_secret="sk-offline-agent-closure-0123456789",
        )
    )
    keystore.store(
        KeystoreRecord(
            name="llm_openai",
            api_key="sk-offline-agent-closure-openai-012345",
            api_secret="sk-offline-agent-closure-openai-012345",
        )
    )
    provider = _ToolThenFinalProvider()

    monkeypatch.setattr(main, "RESEARCH_GRAPH_STORE", graph)
    monkeypatch.setattr(main, "COMPILER_IR_STORE", compiler)
    monkeypatch.setattr(main, "GOAL_VALIDATION_RECEIPT_REGISTRY", validations)
    monkeypatch.setattr(main, "RESEARCH_ASSET_RAG_INDEX", rag)
    monkeypatch.setattr(main, "LLM_CALL_RECORD_STORE", call_store)
    monkeypatch.setattr(main, "LLM_USE_BINDING_STORE", binding_store)
    monkeypatch.setattr(main, "AGENT_WORKFLOW_EVENT_LEDGER", event_ledger)
    monkeypatch.setattr(main, "AGENT_ORCHESTRATOR_ROOT", tmp_path / "agent_kernel")
    monkeypatch.setattr(main, "GOAL_ENTRYPOINT_COVERAGE_REGISTRY", coverage)
    monkeypatch.setattr(main, "STRATEGY_GOAL_STORE", StrategyGoalStore(tmp_path / "goals"))
    monkeypatch.setattr(
        main,
        "_current_agent_gateway",
        lambda run_id=None, *, model_pin=None: build_agent_llm_gateway(
            keystore,
            strict_degrade=False,
            client_factory=lambda _credential: provider,
            seal_secret=call_store.seal_secret,
            use_binding_sink=binding_store.append,
            service_principal_ref="service:agent-closure-test",
            credential_pool_refs={
                "anthropic": "pool:llm:anthropic:default",
                "openai": "pool:llm:openai:default",
            },
            routing_policy_refs={
                "anthropic": "routing:llm:anthropic:default",
                "openai": "routing:llm:openai:default",
            },
        ),
    )
    closure_registry = PersistentAgentWorkflowClosureRegistry(
        tmp_path / "agent_workflow_closure.jsonl",
        resolve_snapshot=main._resolve_agent_workflow_closure_snapshot,
    )
    monkeypatch.setattr(main, "AGENT_WORKFLOW_CLOSURE_REGISTRY", closure_registry)
    main.app.dependency_overrides[main.require_user_dependency] = lambda: SimpleNamespace(
        username="agent-closure-user",
        user_id=owner,
    )
    try:
        client = TestClient(main.app)
        with client.stream(
            "GET",
            "/api/agent/workbench/stream",
            params={
                "q": "build a covariance shrinkage portfolio strategy goal",
                "permission_mode": "auto",
                "request_id": "req-agent-closure-e2e",
                "desk": "research",
                "visible_asset_refs": ["asset:agent-closure"],
                "permission_tags": ["research.read"],
                "projections": ["ResearchRAG"],
                "rag_search": "vector",
            },
        ) as response:
            assert response.status_code == 200
            raw = "".join(response.iter_text())
        done = _sse_done_payload(raw)
        workflow = done["workflow_id"]
        graph_command_count = len(graph.commands())
        coverage_count = len(coverage.records(owner=owner))
        shared_capability_payload = {
            "operation_id": "req-agent-capability-e2e",
            "builder_instruction": "produce bounded capability evidence",
            "verifier_instruction": "independently challenge the exact builder call",
        }
        review = client.post(
            f"/api/agent/workflows/{workflow}/capabilities/review",
            json=shared_capability_payload,
        )
        assert review.status_code == 200, review.text
        assert review.json()["independent"] is True
        verifier_prompts = [
            "\n".join(str(message.content) for message in batch)
            for batch in provider.message_batches
            if any(
                '"builder_output":"grounded workflow complete"'
                in str(message.content)
                and '"review_criteria":"independently challenge the exact builder call"'
                in str(message.content)
                for message in batch
            )
        ]
        assert len(verifier_prompts) == 1
        review_prompt = verifier_prompts[0]
        assert '"builder_output":"grounded workflow complete"' in review_prompt
        assert (
            '"review_criteria":"independently challenge the exact builder call"'
            in review_prompt
        )
        replay = client.post(
            f"/api/agent/workflows/{workflow}/capabilities/replay",
            json=shared_capability_payload,
        )
        assert replay.status_code == 200, replay.text
        fork = client.post(
            f"/api/agent/workflows/{workflow}/capabilities/fork",
            json={
                **shared_capability_payload,
                "fork_instruction": "challenge the bounded evidence under one what-if",
            },
        )
        assert fork.status_code == 200, fork.text
        repair = client.post(
            f"/api/agent/workflows/{workflow}/capabilities/repair",
            json={
                "operation_id": "req-agent-repair-e2e",
                "failure_ref": "agent_failure:e2e",
                "path": "app/example.py",
                "diff": "@@ -1 +1 @@\n-before\n+after",
                "test_result": "focused test passed",
                "rollback_point": "before-agent-repair-e2e",
            },
        )
        assert repair.status_code == 200, repair.text
        rollback = client.post(
            f"/api/agent/workflows/{workflow}/capabilities/rollback",
            json=shared_capability_payload,
        )
        assert rollback.status_code == 200, rollback.text
        assert len(graph.commands()) == graph_command_count
        assert len(coverage.records(owner=owner)) == coverage_count
        result = client.post(
            f"/api/research-os/goal/agent_workflows/{workflow}/closure/current"
        )
    finally:
        main.app.dependency_overrides.pop(main.require_user_dependency, None)

    assert result.status_code == 200, result.text
    body = result.json()
    assert body["workflow_id"] == workflow
    assert body["event_count"] > 0
    assert provider.calls == len(provider.message_batches)
    assert provider.calls >= 6
    assert body["terminal_call_count"] == provider.calls
    assert body["capability_head_count"] == 10
    assert body["source_entrypoint_coverage_ref"].startswith(
        "goal_entrypoint_coverage:"
    )
    assert closure_registry.validate_current(
        body["receipt_ref"],
        owner_user_id=owner,
    ).accepted
