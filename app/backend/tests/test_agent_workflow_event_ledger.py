from __future__ import annotations

import hashlib
import json
import multiprocessing
import os
from concurrent.futures import ThreadPoolExecutor

import pytest

from app.agent.orchestrator.events import (
    EV_AGENT_PLAN_CREATED,
    EV_TODO_UPDATED,
    EventProjectionError,
    EventProjector,
    PersistentWorkflowEventLedger,
    WorkflowEventIdempotencyError,
    WorkflowEventIntegrityError,
)
from app.agent.orchestrator.orchestrator import AgentOrchestrator
from app.lineage.ids import canonical_json


def _append_workflow_event(path: str, ready, start, result, todo_id: str) -> None:
    try:
        ledger = PersistentWorkflowEventLedger(path)
        projector = EventProjector(
            ledger=ledger,
            owner_user_id="owner-a",
            workflow_id="workflow-a",
        )
        ready.put("ready")
        if not start.wait(10):
            result.put(("error", "start timeout"))
            return
        event = projector.emit(EV_TODO_UPDATED, {"todo_id": todo_id})
        result.put(("ok", event.sequence))
    except Exception as exc:  # noqa: BLE001 - child returns exact status to parent.
        result.put((type(exc).__name__, str(exc)))


def test_workflow_event_ledger_persists_reloads_and_isolates_owner(tmp_path):
    path = tmp_path / "workflow_events.jsonl"
    ledger = PersistentWorkflowEventLedger(path)
    projector = EventProjector(
        ledger=ledger,
        owner_user_id="owner-a",
        workflow_id="workflow-a",
    )
    first = projector.emit(EV_AGENT_PLAN_CREATED, {"status": "ready"})
    second = projector.emit(EV_TODO_UPDATED, {"todo_id": "t1"})

    assert (first.sequence, second.sequence) == (1, 2)
    assert first.event_id.startswith("workflow_event:")
    reopened = PersistentWorkflowEventLedger(path)
    rows = reopened.events(owner_user_id="owner-a", workflow_id="workflow-a")
    assert [event.kind for event in rows] == [EV_AGENT_PLAN_CREATED, EV_TODO_UPDATED]
    assert reopened.events(owner_user_id="owner-b", workflow_id="workflow-a") == ()


def test_workflow_event_ledger_rejects_tamper_on_restart(tmp_path):
    path = tmp_path / "workflow_events.jsonl"
    projector = EventProjector(
        ledger=PersistentWorkflowEventLedger(path),
        owner_user_id="owner-a",
        workflow_id="workflow-a",
    )
    projector.emit(EV_AGENT_PLAN_CREATED, {"status": "ready"})
    row = json.loads(path.read_text(encoding="utf-8"))
    row["data"]["status"] = "forged"
    path.write_text(json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n", encoding="utf-8")

    with pytest.raises(WorkflowEventIntegrityError, match="identity mismatch|row HMAC mismatch"):
        PersistentWorkflowEventLedger(path)


def test_workflow_event_ledger_rejects_public_rehash_forgery(tmp_path):
    path = tmp_path / "workflow_events.jsonl"
    projector = EventProjector(
        ledger=PersistentWorkflowEventLedger(path),
        owner_user_id="owner-a",
        workflow_id="workflow-a",
    )
    projector.emit(EV_AGENT_PLAN_CREATED, {"status": "ready"})
    row = json.loads(path.read_text(encoding="utf-8"))
    public_payload = {key: value for key, value in row.items() if key != "row_hmac"}
    row["row_hmac"] = hashlib.sha256(canonical_json(public_payload).encode("utf-8")).hexdigest()
    path.write_text(canonical_json(row) + "\n", encoding="utf-8")

    with pytest.raises(WorkflowEventIntegrityError, match="row HMAC mismatch"):
        PersistentWorkflowEventLedger(path)


def test_workflow_event_ledger_detects_tail_deletion_against_protected_head(tmp_path):
    path = tmp_path / "workflow_events.jsonl"
    projector = EventProjector(
        ledger=PersistentWorkflowEventLedger(path),
        owner_user_id="owner-a",
        workflow_id="workflow-a",
    )
    projector.emit(EV_AGENT_PLAN_CREATED, {"status": "ready"})
    projector.emit(EV_TODO_UPDATED, {"todo_id": "t1"})
    rows = path.read_bytes().splitlines(keepends=True)
    path.write_bytes(rows[0])

    with pytest.raises(WorkflowEventIntegrityError, match="checkpoint does not match"):
        PersistentWorkflowEventLedger(path)


def test_workflow_event_projection_rejects_secret_without_partial_write(tmp_path):
    path = tmp_path / "workflow_events.jsonl"
    projector = EventProjector(
        secret_values=("secret-tripwire-123456",),
        ledger=PersistentWorkflowEventLedger(path),
        owner_user_id="owner-a",
        workflow_id="workflow-a",
    )
    with pytest.raises(EventProjectionError):
        projector.emit(EV_TODO_UPDATED, {"note": "secret-tripwire-123456"})
    assert projector.events == ()
    assert path.read_text(encoding="utf-8") == ""


def test_workflow_event_projection_scans_role_in_complete_serialization(tmp_path):
    path = tmp_path / "workflow_events.jsonl"
    ledger = PersistentWorkflowEventLedger(path)
    projector = EventProjector(
        secret_values=("secret-role-tripwire-123456",),
        ledger=ledger,
        owner_user_id="owner-a",
        workflow_id="workflow-a",
    )
    original_head = ledger.head_path.read_bytes()

    with pytest.raises(EventProjectionError):
        projector.emit(
            EV_TODO_UPDATED,
            {"todo_id": "t1"},
            role="secret-role-tripwire-123456",
        )
    assert projector.events == ()
    assert path.read_bytes() == b""
    assert ledger.head_path.read_bytes() == original_head


@pytest.mark.parametrize("secret_field", ["owner", "workflow", "desk", "node"])
def test_workflow_event_projection_scans_every_identity_field(tmp_path, secret_field):
    secret = f"secret-{secret_field}-tripwire-123456"
    path = tmp_path / f"workflow_events_{secret_field}.jsonl"
    ledger = PersistentWorkflowEventLedger(path)
    projector = EventProjector(
        secret_values=(secret,),
        ledger=ledger,
        owner_user_id=secret if secret_field == "owner" else "owner-a",
        workflow_id=secret if secret_field == "workflow" else "workflow-a",
    )
    kwargs = {
        "desk": secret if secret_field == "desk" else "",
        "node_id": secret if secret_field == "node" else "",
    }

    with pytest.raises(EventProjectionError):
        projector.emit(EV_TODO_UPDATED, {"todo_id": "t1"}, **kwargs)
    assert projector.events == ()
    assert path.read_bytes() == b""


def test_workflow_event_fsync_failure_rolls_back_and_does_not_project(tmp_path, monkeypatch):
    from app.agent.orchestrator import events as events_module

    path = tmp_path / "workflow_events.jsonl"
    projector = EventProjector(
        ledger=PersistentWorkflowEventLedger(path),
        owner_user_id="owner-a",
        workflow_id="workflow-a",
    )

    real_fsync = events_module.os.fsync
    failed = False

    def fail_first_fsync(fd):
        nonlocal failed
        if not failed:
            failed = True
            raise OSError("fsync-tripwire")
        return real_fsync(fd)

    monkeypatch.setattr(events_module.os, "fsync", fail_first_fsync)
    with pytest.raises(OSError, match="fsync-tripwire"):
        projector.emit(EV_AGENT_PLAN_CREATED, {"status": "ready"})
    assert projector.events == ()
    assert path.read_bytes() == b""


def test_workflow_event_checkpoint_failure_restores_row_and_projection(tmp_path, monkeypatch):
    path = tmp_path / "workflow_events.jsonl"
    ledger = PersistentWorkflowEventLedger(path)
    projector = EventProjector(
        ledger=ledger,
        owner_user_id="owner-a",
        workflow_id="workflow-a",
    )
    original_head = ledger.head_path.read_bytes()
    real_write_checkpoint = ledger._write_checkpoint

    def fail_after_checkpoint(rows, *, ledger_size):
        real_write_checkpoint(rows, ledger_size=ledger_size)
        raise OSError("checkpoint-tripwire")

    monkeypatch.setattr(ledger, "_write_checkpoint", fail_after_checkpoint)
    with pytest.raises(OSError, match="checkpoint-tripwire"):
        projector.emit(EV_AGENT_PLAN_CREATED, {"status": "ready"})
    assert projector.events == ()
    assert path.read_bytes() == b""
    assert ledger.head_path.read_bytes() == original_head
    assert ledger.events(owner_user_id="owner-a", workflow_id="workflow-a") == ()


def test_workflow_event_idempotency_exact_retry_and_collision(tmp_path):
    path = tmp_path / "workflow_events.jsonl"
    ledger = PersistentWorkflowEventLedger(path)
    projector = EventProjector(
        ledger=ledger,
        owner_user_id="owner-a",
        workflow_id="workflow-a",
    )
    first = projector.emit(
        EV_TODO_UPDATED,
        {"todo_id": "t1"},
        role="planner",
        idempotency_key="todo-t1-created",
    )
    retried = projector.emit(
        EV_TODO_UPDATED,
        {"todo_id": "t1"},
        role="planner",
        idempotency_key="todo-t1-created",
    )
    assert retried == first
    assert len(path.read_bytes().splitlines()) == 1
    assert projector.events == (first,)

    reopened_projector = EventProjector(
        ledger=PersistentWorkflowEventLedger(path),
        owner_user_id="owner-a",
        workflow_id="workflow-a",
    )
    restarted_retry = reopened_projector.emit(
        EV_TODO_UPDATED,
        {"todo_id": "t1"},
        role="planner",
        idempotency_key="todo-t1-created",
    )
    assert restarted_retry == first
    assert reopened_projector.events == (first,)
    assert len(path.read_bytes().splitlines()) == 1

    with pytest.raises(WorkflowEventIdempotencyError, match="idempotency collision"):
        reopened_projector.emit(
            EV_TODO_UPDATED,
            {"todo_id": "changed"},
            role="planner",
            idempotency_key="todo-t1-created",
        )
    assert len(path.read_bytes().splitlines()) == 1
    assert projector.events == (first,)
    assert reopened_projector.events == (first,)


def test_workflow_event_projector_order_matches_durable_sequence_under_threads(tmp_path):
    path = tmp_path / "workflow_events.jsonl"
    ledger = PersistentWorkflowEventLedger(path)
    projector = EventProjector(
        ledger=ledger,
        owner_user_id="owner-a",
        workflow_id="workflow-a",
    )

    def emit(index):
        return projector.emit(
            EV_TODO_UPDATED,
            {"todo_id": f"t{index}"},
            idempotency_key=f"todo-{index}",
        )

    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(emit, range(20)))
    durable = ledger.events(owner_user_id="owner-a", workflow_id="workflow-a")
    assert [event.sequence for event in projector.events] == list(range(1, 21))
    assert [event.event_id for event in projector.events] == [event.event_id for event in durable]


@pytest.mark.parametrize("protected_attr", ["key_path", "head_path"])
def test_workflow_event_protected_files_reject_mode_widening(tmp_path, protected_attr):
    path = tmp_path / f"mode_{protected_attr}.jsonl"
    ledger = PersistentWorkflowEventLedger(path)
    projector = EventProjector(
        ledger=ledger, owner_user_id="owner-a", workflow_id="workflow-a"
    )
    projector.emit(EV_AGENT_PLAN_CREATED, {"status": "ready"})
    protected_path = getattr(ledger, protected_attr)
    protected_path.chmod(0o644)

    with pytest.raises(WorkflowEventIntegrityError, match="mode 0600"):
        PersistentWorkflowEventLedger(path)


@pytest.mark.parametrize("protected_attr", ["key_path", "head_path"])
def test_workflow_event_protected_files_reject_symlink(tmp_path, protected_attr):
    path = tmp_path / f"symlink_{protected_attr}.jsonl"
    ledger = PersistentWorkflowEventLedger(path)
    projector = EventProjector(
        ledger=ledger, owner_user_id="owner-a", workflow_id="workflow-a"
    )
    projector.emit(EV_AGENT_PLAN_CREATED, {"status": "ready"})
    protected_path = getattr(ledger, protected_attr)
    target = tmp_path / f"attacker_{protected_attr}"
    target.write_bytes(protected_path.read_bytes())
    target.chmod(0o600)
    protected_path.unlink()
    os.symlink(target, protected_path)

    with pytest.raises(WorkflowEventIntegrityError, match="regular non-symlink"):
        PersistentWorkflowEventLedger(path)


def test_workflow_event_head_and_key_tamper_are_rejected(tmp_path):
    head_path = tmp_path / "head_tamper.jsonl"
    head_ledger = PersistentWorkflowEventLedger(head_path)
    EventProjector(
        ledger=head_ledger, owner_user_id="owner-a", workflow_id="workflow-a"
    ).emit(EV_AGENT_PLAN_CREATED, {"status": "ready"})
    head = json.loads(head_ledger.head_path.read_text(encoding="utf-8"))
    head["row_count"] = 0
    head_ledger.head_path.write_text(canonical_json(head) + "\n", encoding="utf-8")
    with pytest.raises(WorkflowEventIntegrityError, match="checkpoint HMAC mismatch"):
        head_ledger.events(owner_user_id="owner-a", workflow_id="workflow-a")
    with pytest.raises(WorkflowEventIntegrityError, match="checkpoint HMAC mismatch"):
        PersistentWorkflowEventLedger(head_path)

    key_path = tmp_path / "key_tamper.jsonl"
    key_ledger = PersistentWorkflowEventLedger(key_path)
    EventProjector(
        ledger=key_ledger, owner_user_id="owner-a", workflow_id="workflow-a"
    ).emit(EV_AGENT_PLAN_CREATED, {"status": "ready"})
    key_ledger.key_path.write_bytes(os.urandom(32))
    with pytest.raises(WorkflowEventIntegrityError, match="HMAC key changed"):
        key_ledger.events(owner_user_id="owner-a", workflow_id="workflow-a")
    with pytest.raises(WorkflowEventIntegrityError, match="HMAC mismatch"):
        PersistentWorkflowEventLedger(key_path)


def test_orchestrator_requires_explicit_durable_owner_and_workflow(tmp_path):
    ledger = PersistentWorkflowEventLedger(tmp_path / "workflow_events.jsonl")
    with pytest.raises(ValueError, match="owner_user_id"):
        AgentOrchestrator(gateway=object(), event_ledger=ledger, workflow_id="workflow-a")
    with pytest.raises(ValueError, match="workflow_id"):
        AgentOrchestrator(gateway=object(), event_ledger=ledger, owner_user_id="owner-a")


def test_workflow_event_multiprocess_appends_have_contiguous_sequence(tmp_path):
    path = tmp_path / "workflow_events.jsonl"
    PersistentWorkflowEventLedger(path)
    ctx = multiprocessing.get_context("spawn")
    ready = ctx.Queue()
    result = ctx.Queue()
    start = ctx.Event()
    processes = [
        ctx.Process(
            target=_append_workflow_event,
            args=(str(path), ready, start, result, todo_id),
        )
        for todo_id in ("t1", "t2")
    ]
    for process in processes:
        process.start()
    assert [ready.get(timeout=15) for _ in processes] == ["ready", "ready"]
    start.set()
    outcomes = [result.get(timeout=15) for _ in processes]
    for process in processes:
        process.join(timeout=15)
        assert process.exitcode == 0

    assert [status for status, _ in outcomes] == ["ok", "ok"]
    rows = PersistentWorkflowEventLedger(path).events(
        owner_user_id="owner-a",
        workflow_id="workflow-a",
    )
    assert [event.sequence for event in rows] == [1, 2]
    assert {event.data["todo_id"] for event in rows} == {"t1", "t2"}
