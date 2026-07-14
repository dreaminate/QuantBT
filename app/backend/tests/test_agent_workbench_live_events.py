from __future__ import annotations

import threading

from app.agent.orchestrator.events import (
    EV_AGENT_PLAN_CREATED,
    EV_FAILURE_DETECTED,
    EV_RUN_VERDICT_PRODUCED,
    PersistentWorkflowEventLedger,
    WorkflowEvent,
)
from app.agent.workbench_stream import (
    iter_durable_workflow_events,
    start_background_workflow,
)


def test_durable_event_is_yielded_before_background_workflow_finishes(tmp_path):
    ledger = PersistentWorkflowEventLedger(tmp_path / "workflow-events.jsonl")
    owner = "workbench-live-owner"
    workflow = "agentwf-live"
    release = threading.Event()

    def operation():
        ledger.append(
            WorkflowEvent(
                kind=EV_AGENT_PLAN_CREATED,
                data={"status": "running"},
            ),
            owner_user_id=owner,
            workflow_id=workflow,
        )
        assert release.wait(2.0), "test did not release the blocked workflow"
        ledger.append(
            WorkflowEvent(
                kind=EV_RUN_VERDICT_PRODUCED,
                data={"verdict": "completed"},
            ),
            owner_user_id=owner,
            workflow_id=workflow,
        )
        return "finished"

    run = start_background_workflow(operation)
    stream = iter_durable_workflow_events(
        run,
        ledger=ledger,
        owner_user_id=owner,
        workflow_id=workflow,
        poll_interval_seconds=0.001,
    )

    first = next(stream)
    assert first.kind == EV_AGENT_PLAN_CREATED
    assert run.done.is_set() is False
    release.set()
    remaining = list(stream)

    assert [event.kind for event in remaining] == [EV_RUN_VERDICT_PRODUCED]
    assert run.done.is_set() is True
    assert run.error is None
    assert run.result == "finished"


def test_background_failure_remains_explicit_after_its_durable_event(tmp_path):
    ledger = PersistentWorkflowEventLedger(tmp_path / "workflow-events.jsonl")
    owner = "workbench-failure-owner"
    workflow = "agentwf-failure"

    def operation():
        ledger.append(
            WorkflowEvent(
                kind=EV_FAILURE_DETECTED,
                data={"reason": "provider_failure", "error_kind": "RuntimeError"},
            ),
            owner_user_id=owner,
            workflow_id=workflow,
        )
        raise RuntimeError("provider failed")

    run = start_background_workflow(operation)
    events = list(
        iter_durable_workflow_events(
            run,
            ledger=ledger,
            owner_user_id=owner,
            workflow_id=workflow,
            poll_interval_seconds=0.001,
        )
    )

    assert [event.kind for event in events] == [EV_FAILURE_DETECTED]
    assert isinstance(run.error, RuntimeError)
    assert str(run.error) == "provider failed"
