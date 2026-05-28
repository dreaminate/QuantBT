from __future__ import annotations

import threading
import time

import pytest

from app.jobs import InMemoryJobStore
from app.schemas import JobProgress, JobRecord


def _make_running_job(store: InMemoryJobStore, job_id: str = "j1") -> JobRecord:
    job = JobRecord(
        job_id=job_id,
        job_type="test",
        status="running",
        payload={},
        submitted_at="2024-01-01T00:00:00Z",
        progress=JobProgress(percent=0, stage="run", stage_label="跑", message="跑"),
    )
    with store._lock:
        store._jobs[job_id] = job
        store._revisions[job_id] = 0
    return job


def test_stream_job_yields_initial_snapshot_then_progress() -> None:
    store = InMemoryJobStore()
    _make_running_job(store)
    events: list[dict] = []
    done = threading.Event()

    def _consume() -> None:
        for evt in store.stream_job("j1", timeout_s=0.5):
            events.append(evt)
            if evt["event"] in {"done", "error"}:
                done.set()
                return
            if len(events) > 5:
                done.set()
                return

    t = threading.Thread(target=_consume, daemon=True)
    t.start()
    # 模拟 progress 推进
    time.sleep(0.05)
    store._progress_callback("j1")(50, "stage1", "halfway")
    time.sleep(0.05)
    store._progress_callback("j1")(100, "stage1", "done!")
    time.sleep(0.05)
    store._update_job("j1", status="succeeded")
    done.wait(timeout=3)
    t.join(timeout=3)

    # 至少有 snapshot + 一条 progress + done
    kinds = [e["event"] for e in events]
    assert kinds[0] == "snapshot"
    assert "progress" in kinds
    assert "done" in kinds


def test_stream_unknown_job_emits_error() -> None:
    store = InMemoryJobStore()
    events = list(store.stream_job("nope", timeout_s=0.1))
    assert any(e["event"] == "error" for e in events)


def test_stream_already_finished_job_returns_done() -> None:
    store = InMemoryJobStore()
    job = _make_running_job(store, "fin")
    with store._lock:
        job.status = "succeeded"
    events = list(store.stream_job("fin", timeout_s=0.1))
    kinds = [e["event"] for e in events]
    assert "snapshot" in kinds
    assert "done" in kinds
