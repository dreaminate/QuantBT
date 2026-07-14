from __future__ import annotations

import hashlib
import json
import multiprocessing
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor

import pytest

from app.agent.llm_client import LLMResponse
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
    AgentCapabilityCommitUncertain,
    AgentCapabilityError,
    AgentCapabilityIntegrityError,
    PersistentAgentCapabilityLedger,
    capability_path_for_event_ledger,
    validate_review_capability_evidence,
)
from app.agent.orchestrator.events import PersistentWorkflowEventLedger
from app.agent.orchestrator.orchestrator import (
    AgentOrchestrator,
    OrchestratorError,
    VerifierIndependenceError,
    make_executor,
)
from app.agent.orchestrator.plan import AcceptanceGate, AgentCodeChange, AgentTodo
from app.dag.engine import DAGTask
from app.dag.kernel import DurableExecutor
from app.llm import (
    IndependenceRecord,
    IndependenceVerdict,
    LLMCredentialPool,
    LLMCallRecord,
    LLMGateway,
    LLMModelProfile,
    ModelRoutingPolicy,
    ModelTier,
    ReplayState,
    RoutingMode,
    SecretRef,
)
from app.llm.call_record import (
    bind_review_verifier_record,
    make_review_subject_binding,
)
from app.lineage.ids import canonical_json, content_hash
from app.security import InMemoryKeystore, KeystoreRecord, SecureKeystore


OWNER = "owner-capability"
WORKFLOW = "workflow-capability"
PROMPT_TRIPWIRE = "prompt-capability-tripwire-7b5e4f"
OUTPUT_TRIPWIRE = "output-capability-tripwire-f13a20"
DIFF_TRIPWIRE = "diff-capability-tripwire-94ad10"
TEST_TRIPWIRE = "test-capability-tripwire-50531d"
ROLLBACK_TRIPWIRE = "rollback-capability-tripwire-c908bc"
SECRET_TRIPWIRE = "secret-capability-tripwire-1a5ea4"


def _draft_payload(index: int) -> dict[str, object]:
    return {"source_event_ref": f"event:{index}", "index": index}


def _record_plan_action(
    ledger: PersistentAgentCapabilityLedger,
    index: int,
    *,
    owner: str = OWNER,
    workflow: str = WORKFLOW,
):
    return ledger._record_action(  # noqa: SLF001 - exercise journal mechanics directly.
        owner_user_id=owner,
        workflow_id=workflow,
        capability_kind=CAPABILITY_PLAN,
        source_ref=f"workflow_event:{index}",
        payload=_draft_payload(index),
    )


def _record_plan_action_in_process(path: str, index: int) -> int:
    ledger = PersistentAgentCapabilityLedger(path)
    return _record_plan_action(ledger, index).revision


def test_revision_chain_restart_current_head_and_owner_scope(tmp_path):
    path = tmp_path / "capabilities.jsonl"
    ledger = PersistentAgentCapabilityLedger(path)

    first = _record_plan_action(ledger, 1)
    second = _record_plan_action(ledger, 2)

    assert first.revision == 1
    assert second.revision == 2
    assert second.previous_record_ref == first.record_ref
    assert ledger.validate_current(first.record_ref, owner_user_id=OWNER).accepted is False
    assert ledger.validate_current(second.record_ref, owner_user_id=OWNER).accepted is True

    restarted = PersistentAgentCapabilityLedger(path)
    assert restarted.current_head(
        owner_user_id=OWNER,
        workflow_id=WORKFLOW,
        capability_kind=CAPABILITY_PLAN,
    ) == second
    with pytest.raises(KeyError):
        restarted.record(second.record_ref, owner_user_id="other-owner")


def test_plaintext_surfaces_and_known_secrets_are_rejected(tmp_path):
    ledger = PersistentAgentCapabilityLedger(
        tmp_path / "capabilities.jsonl", secret_values=(SECRET_TRIPWIRE,)
    )

    with pytest.raises(AgentCapabilityError, match="forbidden plaintext"):
        ledger._record_action(  # noqa: SLF001 - inject forbidden low-level payload.
            owner_user_id=OWNER,
            workflow_id=WORKFLOW,
            capability_kind=CAPABILITY_PLAN,
            source_ref="workflow_event:prompt",
            payload={"raw_prompt": PROMPT_TRIPWIRE},
        )
    with pytest.raises(AgentCapabilityError, match="known plaintext secret"):
        ledger._record_action(  # noqa: SLF001 - inject secret low-level payload.
            owner_user_id=OWNER,
            workflow_id=WORKFLOW,
            capability_kind=CAPABILITY_PLAN,
            source_ref="workflow_event:secret",
            payload={"safe_ref": SECRET_TRIPWIRE},
        )
    assert ledger.records(owner_user_id=OWNER) == ()


def test_tail_rollback_and_row_mutation_fail_closed_across_restart(tmp_path):
    path = tmp_path / "capabilities.jsonl"
    ledger = PersistentAgentCapabilityLedger(path)
    _record_plan_action(ledger, 1)
    first_bytes = path.read_bytes()
    _record_plan_action(ledger, 2)

    path.write_bytes(first_bytes)
    with pytest.raises(AgentCapabilityIntegrityError, match="checkpoint"):
        PersistentAgentCapabilityLedger(path)


def test_in_place_row_mutation_fails_hmac_before_restart_adoption(tmp_path):
    path = tmp_path / "capabilities.jsonl"
    ledger = PersistentAgentCapabilityLedger(path)
    _record_plan_action(ledger, 1)
    raw = path.read_bytes()
    assert b'"index":1' in raw
    path.write_bytes(raw.replace(b'"index":1', b'"index":9', 1))

    with pytest.raises(AgentCapabilityIntegrityError, match="hash chain|HMAC"):
        PersistentAgentCapabilityLedger(path)


def test_failed_checkpoint_write_restores_journal_and_head(tmp_path, monkeypatch):
    path = tmp_path / "capabilities.jsonl"
    ledger = PersistentAgentCapabilityLedger(path)
    _record_plan_action(ledger, 1)
    original_journal = path.read_bytes()
    original_head = ledger.head_path.read_bytes()

    def fail_checkpoint(*_args, **_kwargs):
        raise OSError("injected checkpoint failure")

    monkeypatch.setattr(ledger, "_write_checkpoint", fail_checkpoint)
    with pytest.raises(OSError, match="injected checkpoint failure"):
        _record_plan_action(ledger, 2)

    assert path.read_bytes() == original_journal
    assert ledger.head_path.read_bytes() == original_head
    restarted = PersistentAgentCapabilityLedger(path)
    assert len(restarted.records(owner_user_id=OWNER)) == 1


def test_post_commit_reload_failure_is_reported_as_commit_uncertain(tmp_path, monkeypatch):
    path = tmp_path / "capabilities.jsonl"
    ledger = PersistentAgentCapabilityLedger(path)
    original_reload = ledger._reload_unlocked  # noqa: SLF001
    reload_calls = 0

    def fail_post_commit_reload():
        nonlocal reload_calls
        reload_calls += 1
        if reload_calls == 2:
            raise OSError("injected post-commit verification failure")
        return original_reload()

    monkeypatch.setattr(ledger, "_reload_unlocked", fail_post_commit_reload)
    with pytest.raises(AgentCapabilityCommitUncertain, match="verification failed"):
        _record_plan_action(ledger, 1)

    restarted = PersistentAgentCapabilityLedger(path)
    assert len(restarted.records(owner_user_id=OWNER)) == 1


def test_prepared_operations_survive_restart_and_require_terminal_transition(tmp_path):
    path = tmp_path / "capabilities.jsonl"
    ledger = PersistentAgentCapabilityLedger(path)
    prepared = ledger.prepare_operation(
        owner_user_id=OWNER,
        workflow_id=WORKFLOW,
        target_kind=CAPABILITY_PLAN,
        request_ref="request:prepare-restart",
    )

    restarted = PersistentAgentCapabilityLedger(path)
    assert restarted.unresolved_operations(
        owner_user_id=OWNER,
        workflow_id=WORKFLOW,
    ) == (prepared,)
    capability = _record_plan_action(restarted, 1)
    restarted.commit_operation(
        owner_user_id=OWNER,
        workflow_id=WORKFLOW,
        prepared_record_ref=prepared.record_ref,
        capability_refs=(capability.record_ref,),
    )
    assert PersistentAgentCapabilityLedger(path).unresolved_operations(
        owner_user_id=OWNER,
        workflow_id=WORKFLOW,
    ) == ()

    second = restarted.prepare_operation(
        owner_user_id=OWNER,
        workflow_id=WORKFLOW,
        target_kind=CAPABILITY_REPAIR,
        request_ref="request:abort-restart",
    )
    restarted.abort_operation(
        owner_user_id=OWNER,
        workflow_id=WORKFLOW,
        prepared_record_ref=second.record_ref,
        failure_ref="failure:source-mutation",
    )
    assert PersistentAgentCapabilityLedger(path).unresolved_operations(
        owner_user_id=OWNER,
        workflow_id=WORKFLOW,
    ) == ()


def test_orchestrator_commit_uncertainty_leaves_restart_visible_pending_operation(
    tmp_path,
    monkeypatch,
):
    orchestrator = _event_backed_orchestrator(tmp_path)
    ledger = orchestrator.capability_ledger
    assert ledger is not None

    def fail_commit(**_kwargs):
        raise AgentCapabilityCommitUncertain("injected capability commit uncertainty")

    monkeypatch.setattr(ledger, "commit_operation", fail_commit)
    with pytest.raises(AgentCapabilityCommitUncertain, match="injected"):
        orchestrator.plan(
            "goal",
            todos=[AgentTodo("todo-a", "do work", "factor_engineer")],
            dependencies={"todo-a": []},
            acceptance_gates=[AcceptanceGate("gate-a", "gate", "check")],
        )

    restarted = PersistentAgentCapabilityLedger(ledger.path)
    assert len(
        restarted.records(
            owner_user_id=OWNER,
            workflow_id=WORKFLOW,
            capability_kind=CAPABILITY_PLAN,
        )
    ) == 1
    assert len(
        restarted.unresolved_operations(
            owner_user_id=OWNER,
            workflow_id=WORKFLOW,
        )
    ) == 1


def test_two_instances_serialize_revisions_under_cross_process_lock(tmp_path):
    path = tmp_path / "capabilities.jsonl"
    first = PersistentAgentCapabilityLedger(path)
    second = PersistentAgentCapabilityLedger(path)

    def write(index: int):
        target = first if index % 2 else second
        return _record_plan_action(target, index)

    with ThreadPoolExecutor(max_workers=8) as pool:
        records = list(pool.map(write, range(1, 17)))

    assert sorted(record.revision for record in records) == list(range(1, 17))
    restarted = PersistentAgentCapabilityLedger(path)
    assert restarted.current_head(
        owner_user_id=OWNER,
        workflow_id=WORKFLOW,
        capability_kind=CAPABILITY_PLAN,
    ).revision == 16


def test_spawned_processes_serialize_revisions_and_restart_head(tmp_path):
    path = tmp_path / "capabilities.jsonl"
    PersistentAgentCapabilityLedger(path)
    context = multiprocessing.get_context("spawn")

    with ProcessPoolExecutor(max_workers=4, mp_context=context) as pool:
        revisions = list(
            pool.map(
                _record_plan_action_in_process,
                [str(path)] * 8,
                range(1, 9),
            )
        )

    assert sorted(revisions) == list(range(1, 9))
    restarted = PersistentAgentCapabilityLedger(path)
    assert restarted.current_head(
        owner_user_id=OWNER,
        workflow_id=WORKFLOW,
        capability_kind=CAPABILITY_PLAN,
    ).revision == 8


def _event_backed_orchestrator(tmp_path, *, workflow: str = WORKFLOW):
    event_path = tmp_path / "events.jsonl"
    events = PersistentWorkflowEventLedger(event_path)
    orchestrator = AgentOrchestrator(
        gateway=object(),
        event_ledger=events,
        owner_user_id=OWNER,
        workflow_id=workflow,
        secret_values=(SECRET_TRIPWIRE,),
    )
    assert orchestrator.capability_ledger is not None
    assert orchestrator.capability_ledger.path == capability_path_for_event_ledger(event_path)
    return orchestrator


def test_plan_persists_exact_hashed_fields_without_plaintext(tmp_path):
    orchestrator = _event_backed_orchestrator(tmp_path)
    plan = orchestrator.plan(
        PROMPT_TRIPWIRE,
        todos=[
            AgentTodo("todo-a", PROMPT_TRIPWIRE, "factor_engineer"),
            AgentTodo("todo-b", "second-sensitive-description", "reporter"),
        ],
        dependencies={"todo-a": [], "todo-b": ["todo-a"]},
        risk_list=["sensitive-risk-description"],
        acceptance_gates=[
            AcceptanceGate(
                "gate-a",
                "sensitive-gate-description",
                "sensitive-falsifiable-check",
            )
        ],
        cross_desk_handoff_plan=[{"desk": "model", "note": "sensitive-handoff"}],
        rollback_points=[ROLLBACK_TRIPWIRE],
    )
    assert plan.is_ready

    ledger = orchestrator.capability_ledger
    assert ledger is not None
    head = ledger.current_head(
        owner_user_id=OWNER,
        workflow_id=WORKFLOW,
        capability_kind=CAPABILITY_PLAN,
    )
    assert head.payload["dependencies"] == [
        {"depends_on": [], "todo_id": "todo-a"},
        {"depends_on": ["todo-a"], "todo_id": "todo-b"},
    ]
    assert head.payload["todos"][1]["todo_id"] == "todo-b"
    assert head.payload["acceptance_gates"][0]["gate_id"] == "gate-a"
    durable_bytes = ledger.path.read_bytes()
    for tripwire in (
        PROMPT_TRIPWIRE,
        b"sensitive-risk-description",
        b"sensitive-gate-description",
        b"sensitive-falsifiable-check",
        b"sensitive-handoff",
        ROLLBACK_TRIPWIRE,
    ):
        token = tripwire if isinstance(tripwire, bytes) else tripwire.encode()
        assert token not in durable_bytes


def test_plan_event_failure_happens_before_capability_record(tmp_path, monkeypatch):
    events = PersistentWorkflowEventLedger(tmp_path / "events.jsonl")
    orchestrator = AgentOrchestrator(
        gateway=object(),
        event_ledger=events,
        owner_user_id=OWNER,
        workflow_id=WORKFLOW,
    )
    original_append = events.append
    calls = 0

    def fail_second_append(*args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("injected source-event failure")
        return original_append(*args, **kwargs)

    monkeypatch.setattr(events, "append", fail_second_append)
    with pytest.raises(OSError, match="source-event failure"):
        orchestrator.plan(
            "goal",
            todos=[AgentTodo("todo-a", "do work", "factor_engineer")],
            dependencies={"todo-a": []},
            acceptance_gates=[AcceptanceGate("gate-a", "gate", "check")],
        )

    assert orchestrator.capability_ledger is not None
    assert orchestrator.capability_ledger.records(owner_user_id=OWNER) == ()


def _call_record(
    *,
    call_id: str,
    provider: str,
    model: str,
    context_ref: str,
    owner: str = OWNER,
    workflow: str = WORKFLOW,
    independence: IndependenceRecord | None = None,
) -> LLMCallRecord:
    output = f"output:{call_id}"
    return LLMCallRecord(
        provider=provider,
        model=model,
        auth_ref=f"secretref://{provider}/pool",
        replay_state=ReplayState.LIVE.value,
        owner_user_id=owner,
        workflow_id=workflow,
        invocation_id=f"invocation:{call_id}",
        call_id=call_id,
        prompt_digest=context_ref,
        response_digest=content_hash({"content": output, "tool_calls": []}),
        independence=independence or IndependenceRecord(),
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


def test_review_records_exact_calls_and_rejects_scope_or_fake_independence(tmp_path):
    orchestrator = _event_backed_orchestrator(tmp_path)
    builder = _call_record(
        call_id="call:builder",
        provider="anthropic",
        model="builder-model",
        context_ref="context:builder",
    )
    verifier = _call_record(
        call_id="call:verifier",
        provider="openai",
        model="verifier-model",
        context_ref="context:verifier",
        independence=IndependenceRecord(
            required=True,
            satisfied=True,
            distinct_provider=True,
            distinct_model=True,
            builder_call_id=builder.call_id,
        ),
    )
    subject_binding = _review_subject_binding(builder, verifier)
    verdict = orchestrator.admit_verifier_challenge(
        builder,
        verifier,
        subject_binding=subject_binding,
    )
    assert verdict.independent is True

    ledger = orchestrator.capability_ledger
    assert ledger is not None
    head = ledger.current_head(
        owner_user_id=OWNER,
        workflow_id=WORKFLOW,
        capability_kind=CAPABILITY_REVIEW,
    )
    assert head.payload["builder_call_ref"] == builder.call_id
    assert head.payload["verifier_call_ref"] == verifier.call_id
    assert head.payload["review_subject_ref"] == subject_binding.review_subject_ref
    assert head.payload["independent"] is True

    restarted = PersistentAgentCapabilityLedger(ledger.path)
    restarted_head = restarted.current_head(
        owner_user_id=OWNER,
        workflow_id=WORKFLOW,
        capability_kind=CAPABILITY_REVIEW,
    )
    restarted_verdict = validate_review_capability_evidence(
        owner_user_id=OWNER,
        workflow_id=WORKFLOW,
        builder=builder,
        verifier=verifier,
        payload=restarted_head.payload,
    )
    assert restarted_verdict.independent is True

    other_owner = _call_record(
        call_id="call:other",
        provider="openai",
        model="other-model",
        context_ref="context:other",
        owner="other-owner",
    )
    with pytest.raises(OrchestratorError, match="owner"):
        orchestrator.admit_verifier_challenge(
            builder,
            other_owner,
            subject_binding=subject_binding,
        )
    assert ledger.current_head(
        owner_user_id=OWNER,
        workflow_id=WORKFLOW,
        capability_kind=CAPABILITY_REVIEW,
    ) == head

    isolated = _event_backed_orchestrator(tmp_path / "fake", workflow="workflow-fake")
    liar_builder = _call_record(
        call_id="call:liar-builder",
        provider="openai",
        model="same-model",
        context_ref="context:liar-builder",
        workflow="workflow-fake",
    )
    liar = _call_record(
        call_id="call:liar",
        provider="openai",
        model="same-model",
        context_ref="context:liar",
        workflow="workflow-fake",
        independence=IndependenceRecord(
            required=True,
            satisfied=True,
            builder_call_id=liar_builder.call_id,
        ),
    )
    with pytest.raises(VerifierIndependenceError):
        isolated.admit_verifier_challenge(
            liar_builder,
            liar,
            subject_binding=_review_subject_binding(liar_builder, liar),
        )
    assert isolated.capability_ledger is not None
    with pytest.raises(KeyError):
        isolated.capability_ledger.current_head(
            owner_user_id=OWNER,
            workflow_id="workflow-fake",
            capability_kind=CAPABILITY_REVIEW,
        )


def test_review_producer_recomputes_scope_and_independence(tmp_path):
    ledger = PersistentAgentCapabilityLedger(tmp_path / "capabilities.jsonl")
    builder = _call_record(
        call_id="call:builder",
        provider="anthropic",
        model="builder-model",
        context_ref="context:builder",
    )
    verifier = _call_record(
        call_id="call:verifier",
        provider="openai",
        model="verifier-model",
        context_ref="context:verifier",
        independence=IndependenceRecord(
            required=True,
            satisfied=True,
            distinct_provider=True,
            distinct_model=True,
            builder_call_id=builder.call_id,
        ),
    )
    subject_binding = _review_subject_binding(builder, verifier)

    with pytest.raises(AgentCapabilityError, match="canonical independence"):
        ledger.record_review(
            owner_user_id=OWNER,
            workflow_id=WORKFLOW,
            builder=builder,
            verifier=verifier,
            subject_binding=subject_binding,
            verdict=IndependenceVerdict(False, "forged verdict"),
            source_event_ref="workflow_event:review",
        )
    with pytest.raises(AgentCapabilityError, match="owner/workflow"):
        ledger.record_review(
            owner_user_id="other-owner",
            workflow_id=WORKFLOW,
            builder=builder,
            verifier=verifier,
            subject_binding=subject_binding,
            verdict=IndependenceVerdict(
                True,
                "verifier 与 builder provider/model 不同源——独立性成立",
            ),
            source_event_ref="workflow_event:review",
        )
    assert ledger.records(owner_user_id=OWNER) == ()


def test_repair_records_code_change_and_repair_atomically_after_permission(tmp_path):
    orchestrator = _event_backed_orchestrator(tmp_path)
    change = AgentCodeChange(
        path="factor.py",
        diff=DIFF_TRIPWIRE,
        test_result=TEST_TRIPWIRE,
        rollback_point=ROLLBACK_TRIPWIRE,
    )

    with pytest.raises(OrchestratorError, match="permission_ref"):
        orchestrator.repair(failure_ref="run:failed", code_change=change)
    assert orchestrator.events == ()

    orchestrator.repair(
        failure_ref="run:failed",
        code_change=change,
        permission_ref="permission:repair-1",
    )
    ledger = orchestrator.capability_ledger
    assert ledger is not None
    code_head = ledger.current_head(
        owner_user_id=OWNER,
        workflow_id=WORKFLOW,
        capability_kind=CAPABILITY_CODE_CHANGE,
    )
    repair_head = ledger.current_head(
        owner_user_id=OWNER,
        workflow_id=WORKFLOW,
        capability_kind=CAPABILITY_REPAIR,
    )
    assert code_head.payload["code_change_ref"] == repair_head.payload["code_change_ref"]
    assert code_head.payload["permission_ref"] == "permission:repair-1"
    assert len(ledger.records(owner_user_id=OWNER, workflow_id=WORKFLOW)) == 2
    durable_bytes = ledger.path.read_bytes()
    assert DIFF_TRIPWIRE.encode() not in durable_bytes
    assert TEST_TRIPWIRE.encode() not in durable_bytes
    assert ROLLBACK_TRIPWIRE.encode() not in durable_bytes


def _identity_op(*, context, value):
    return {"value": value}


def _failing_op(*, context, value):
    raise RuntimeError(f"failed:{value}")


def test_kernel_records_successful_checkpoint_replay_fork_and_rollback_heads(tmp_path):
    ledger = PersistentAgentCapabilityLedger(tmp_path / "capabilities.jsonl")
    executor = DurableExecutor(
        tmp_path / "kernel",
        ops={"identity": _identity_op},
        capability_ledger=ledger,
        capability_owner_user_id=OWNER,
        capability_workflow_id=WORKFLOW,
    )
    tasks = [
        DAGTask(id="root", op="identity", params={"value": 1}),
        DAGTask(id="child", op="identity", params={"value": 2}, deps=["root"]),
    ]

    run = executor.run(tasks)
    replay = executor.replay(tasks)
    fork = executor.fork(tasks, from_task_id="root", overrides={"value": 3})
    rollback = executor.rollback(tasks, to_task_id="root")

    assert run.capability_record_ref
    assert replay.capability_record_ref
    assert fork.capability_record_ref
    assert rollback.capability_record_ref
    expected = {
        CAPABILITY_DAG_CHECKPOINT: run.capability_record_ref,
        CAPABILITY_DAG_REPLAY: replay.capability_record_ref,
        CAPABILITY_DAG_FORK: fork.capability_record_ref,
        CAPABILITY_DAG_ROLLBACK: rollback.capability_record_ref,
    }
    source_prefixes = {
        CAPABILITY_DAG_CHECKPOINT: "dag_run:sha256:",
        CAPABILITY_DAG_REPLAY: "replay:sha256:",
        CAPABILITY_DAG_FORK: "fork:sha256:",
        CAPABILITY_DAG_ROLLBACK: "rollback:sha256:",
    }
    for kind, ref in expected.items():
        head = ledger.current_head(
            owner_user_id=OWNER,
            workflow_id=WORKFLOW,
            capability_kind=kind,
        )
        assert head.record_ref == ref
        assert head.source_ref.startswith(source_prefixes[kind])
        assert head.payload["nodes"]
        assert all(
            str(node["checkpoint_ref"]).startswith("checkpoint:")
            for node in head.payload["nodes"]
        )
        assert all(
            str(node["checkpoint_ref"]).startswith("checkpoint:")
            for node in head.payload["node_id_by_task"]
        )

    with pytest.raises(ValueError, match="cannot be rebound"):
        executor.bind_capability_scope(
            ledger=ledger,
            owner_user_id="other-owner",
            workflow_id=WORKFLOW,
        )


def test_failed_kernel_action_does_not_mint_capability(tmp_path):
    ledger = PersistentAgentCapabilityLedger(tmp_path / "capabilities.jsonl")
    executor = DurableExecutor(
        tmp_path / "kernel",
        ops={"fail": _failing_op},
        capability_ledger=ledger,
        capability_owner_user_id=OWNER,
        capability_workflow_id=WORKFLOW,
    )
    result = executor.run([DAGTask(id="bad", op="fail", params={"value": 1})])
    assert result.succeeded is False
    assert result.capability_record_ref == ""
    assert ledger.records(owner_user_id=OWNER) == ()


def test_dag_producer_rejects_unstructured_caller_details(tmp_path):
    ledger = PersistentAgentCapabilityLedger(tmp_path / "capabilities.jsonl")
    tasks = [DAGTask(id="root", op="identity", params={"value": 1})]
    result = DurableExecutor(
        tmp_path / "kernel", ops={"identity": _identity_op}
    ).run(tasks)

    with pytest.raises(AgentCapabilityError, match="caller details"):
        ledger.record_dag_operation(
            owner_user_id=OWNER,
            workflow_id=WORKFLOW,
            mode="run",
            tasks=tasks,
            result=result,
            details={"note": PROMPT_TRIPWIRE},
        )
    assert ledger.records(owner_user_id=OWNER) == ()


class _ReadThenFinishClient:
    provider = "scripted"

    def chat(self, messages, *, tools=None, model=None, temperature=0.2):
        if any(getattr(message, "role", "") == "tool" for message in messages):
            return LLMResponse(content=OUTPUT_TRIPWIRE, tool_calls=[])
        return LLMResponse(
            content="",
            tool_calls=[{"id": "tool:1", "name": "read_asset", "arguments": "{}"}],
        )


def _gateway() -> LLMGateway:
    profile = LLMModelProfile(
        provider="anthropic",
        model="claude-opus-4",
        capability_tier=ModelTier.STRONG.value,
        pool_id="anthropic",
    )
    keystore = SecureKeystore(InMemoryKeystore())
    keystore.store(
        KeystoreRecord(
            name="anthropic",
            api_key="test-key-anthropic-xxxxxxxx",
            api_secret="test-key-anthropic-xxxxxxxx",
        )
    )
    pool = LLMCredentialPool(keystore)
    pool.register(
        "anthropic",
        SecretRef(
            keystore_name="anthropic",
            provider="anthropic",
            auth_kind="api_key",
        ),
        default_model=profile.model,
    )
    return LLMGateway(
        policy=ModelRoutingPolicy([profile], mode=RoutingMode.HYBRID_ADAPTIVE),
        credential_pool=pool,
        client_factory=lambda _credential: _ReadThenFinishClient(),
        strict_degrade=False,
    )


def _tool_handler(_name: str, _args: dict[str, object]):
    return {"ok": True, "output": OUTPUT_TRIPWIRE}


def test_orchestrator_dispatch_and_replay_link_runtime_dag_heads(tmp_path):
    events = PersistentWorkflowEventLedger(tmp_path / "events.jsonl")
    orchestrator = AgentOrchestrator(
        gateway=_gateway(),
        event_ledger=events,
        owner_user_id=OWNER,
        workflow_id=WORKFLOW,
    )
    plan = orchestrator.plan(
        PROMPT_TRIPWIRE,
        todos=[AgentTodo("task-a", PROMPT_TRIPWIRE, "factor_engineer")],
        dependencies={"task-a": []},
        acceptance_gates=[
            AcceptanceGate("gate-a", "tool evidence", "missing tool means fail")
        ],
    )
    executor = make_executor(tmp_path / "kernel")
    handlers = {"factor_engineer": {"read_asset": _tool_handler}}

    dispatched = orchestrator.dispatch(
        plan,
        executor=executor,
        tool_handlers=handlers,
    )
    replayed = orchestrator.replay(
        plan,
        executor=executor,
        tool_handlers=handlers,
    )
    assert dispatched.succeeded is True
    assert replayed.succeeded is True

    ledger = orchestrator.capability_ledger
    assert ledger is not None
    react = ledger.current_head(
        owner_user_id=OWNER,
        workflow_id=WORKFLOW,
        capability_kind=CAPABILITY_REACT,
    )
    replay = ledger.current_head(
        owner_user_id=OWNER,
        workflow_id=WORKFLOW,
        capability_kind=CAPABILITY_REPLAY,
    )
    assert react.payload["dag_record_ref"] == dispatched.kernel_result.capability_record_ref
    assert replay.payload["dag_record_ref"] == replayed.kernel_result.capability_record_ref
    assert all(
        str(node["checkpoint_ref"]).startswith("checkpoint:")
        for node in react.payload["node_checkpoint_refs"]
    )
    assert all(
        str(node["checkpoint_ref"]).startswith("checkpoint:")
        for node in replay.payload["node_checkpoint_refs"]
    )
    assert ledger.current_head(
        owner_user_id=OWNER,
        workflow_id=WORKFLOW,
        capability_kind=CAPABILITY_DAG_REPLAY,
    ).record_ref == replayed.kernel_result.capability_record_ref

    with pytest.raises(AgentCapabilityError, match="wrong workflow or mode"):
        ledger.record_orchestration_mode(
            owner_user_id=OWNER,
            workflow_id=WORKFLOW,
            mode=CAPABILITY_REACT,
            source_event_ref="workflow_event:forged-react",
            dag_record_ref=replayed.kernel_result.capability_record_ref,
            result=replayed,
        )

    durable_bytes = ledger.path.read_bytes()
    assert PROMPT_TRIPWIRE.encode() not in durable_bytes
    assert OUTPUT_TRIPWIRE.encode() not in durable_bytes
