"""Orchestrator + SSE-mapping tests for the external agent (agent M4).

Driven by a ScriptedBackend — no subprocess. Proves: BackendEvents map onto the
existing SSE vocabulary; a not-ready backend yields an honest error and never
runs (no fallback to an internal agent); the owner threads into run(); and a
cross-process canvas write triggers exactly one store refresh.

Mutation contract (RULES §2 种坏门必抓):
- Drop the ``if not readiness.ready`` guard in ``stream_events`` → the not-ready
  test goes RED (backend.run would be called, no error frame emitted).
- Drop the ``is_cross_process_write`` refresh hook → the refresh test goes RED.
"""

from __future__ import annotations

from app.agent.backends.events import (
    AssistantText,
    BackendError,
    Done,
    SessionStarted,
    ToolCall,
    ToolResult,
    backend_events_to_sse,
    is_cross_process_write,
)
from app.agent.backends.base import BackendReadiness
from app.agent.backends.scripted_backend import ScriptedBackend
from app.agent.session_orchestrator import SessionOrchestrator


def _ready_readiness():
    return BackendReadiness(
        provider="x", cli="x", cli_installed=True, authed=True, ready=True, detail=""
    )


def _events(dicts):
    return [(d["event"], d["data"]) for d in dicts]


# --- pure event → SSE mapping -------------------------------------------------

def test_event_mapping_covers_vocabulary():
    seq = [
        SessionStarted(session_id="s1"),
        AssistantText(text="hello"),
        ToolCall(tool="canvas_read"),
        ToolResult(tool="canvas_read", result={"count": 2, "run_id": "run-9"}),
        Done(reason="complete"),
        BackendError(message="boom"),
    ]
    out = _events(backend_events_to_sse(seq))
    kinds = [e for e, _ in out]
    assert kinds == ["say", "say", "tool_start", "tool_end", "done", "error"]
    # tool_end lifts run_id to the top level (like project_turn_events).
    tool_end = next(d for e, d in out if e == "tool_end")
    assert tool_end["run_id"] == "run-9"
    assert tool_end["tool"] == "canvas_read"


# --- orchestrator over a scripted backend -------------------------------------

def test_orchestrator_streams_tool_frames_and_terminal_done():
    backend = ScriptedBackend(
        [
            SessionStarted(session_id="s1"),
            AssistantText(text="reading canvas"),
            ToolCall(tool="canvas_read"),
            ToolResult(tool="canvas_read", result={"count": 0}),
            Done(),
        ]
    )
    orch = SessionOrchestrator()
    frames = _events(orch.stream_events(backend=backend, owner="alice", prompt="read"))
    kinds = [e for e, _ in frames]
    assert "tool_start" in kinds and "tool_end" in kinds
    assert kinds[-1] == "done"
    # owner + prompt threaded into run().
    assert backend.run_calls == [{"prompt": "read", "owner": "alice"}]


def test_orchestrator_appends_done_when_backend_omits_it():
    backend = ScriptedBackend([AssistantText(text="hi")])  # no Done
    orch = SessionOrchestrator()
    frames = _events(orch.stream_events(backend=backend, owner="a", prompt="p"))
    assert frames[-1][0] == "done"
    assert frames[-1][1]["reason"] == "stream_ended"


def test_not_ready_backend_errors_and_never_runs():
    backend = ScriptedBackend([Done()], ready=False, detail="登录一次")
    orch = SessionOrchestrator()
    frames = _events(orch.stream_events(backend=backend, owner="a", prompt="p"))
    kinds = [e for e, _ in frames]
    assert kinds[0] == "error", "not-ready must emit an honest error frame first"
    assert "登录一次" in frames[0][1]["message"]
    assert kinds[-1] == "done"
    # No fallback: the backend's run() must NOT have been invoked.
    assert backend.run_calls == [], "not-ready backend must not run (no fallback)"
    # And no tool frames leaked from the scripted (never-run) event list.
    assert "tool_start" not in kinds and "say" not in kinds


def test_cross_process_write_triggers_exactly_one_refresh():
    refreshes = {"n": 0}

    def _refresh():
        refreshes["n"] += 1

    backend = ScriptedBackend(
        [
            ToolResult(tool="canvas_read", result={"count": 1}),  # read: no refresh
            ToolResult(tool="canvas_create_node", result={"qro_id": "q1"}),  # write: refresh
            Done(),
        ]
    )
    orch = SessionOrchestrator(refresh_store=_refresh)
    list(orch.stream_events(backend=backend, owner="a", prompt="p"))
    assert refreshes["n"] == 1, "exactly one refresh for the single canvas write"


def test_errored_write_result_does_not_refresh():
    refreshes = {"n": 0}
    backend = ScriptedBackend(
        [ToolResult(tool="canvas_create_node", result={"error": "denied"}, is_error=True), Done()]
    )
    orch = SessionOrchestrator(refresh_store=lambda: refreshes.__setitem__("n", refreshes["n"] + 1))
    list(orch.stream_events(backend=backend, owner="a", prompt="p"))
    assert refreshes["n"] == 0, "a failed write must not trigger a store refresh"


def test_is_cross_process_write_predicate():
    assert is_cross_process_write(ToolResult(tool="canvas_create_node", result={}))
    assert is_cross_process_write(
        ToolResult(tool="mcp__quantbt-agent-canvas__canvas_create_node", result={})
    )
    assert not is_cross_process_write(ToolResult(tool="canvas_read", result={}))
    assert not is_cross_process_write(ToolCall(tool="canvas_create_node"))


def test_done_is_terminal_and_drops_trailing_events():
    # Cross-vendor floor: a malformed backend that yields content AFTER Done must
    # not leak past the terminal frame; done must be last and singular.
    backend = ScriptedBackend([Done(), ToolCall(tool="canvas_read"), AssistantText(text="late")])
    orch = SessionOrchestrator()
    frames = _events(orch.stream_events(backend=backend, owner="a", prompt="p"))
    kinds = [e for e, _ in frames]
    assert kinds == ["done"], f"trailing events leaked past terminal done: {kinds}"


def test_multiple_done_is_deduped_to_one_terminal():
    backend = ScriptedBackend([Done(reason="a"), Done(reason="b")])
    orch = SessionOrchestrator()
    kinds = [e for e, _ in _events(orch.stream_events(backend=backend, owner="a", prompt="p"))]
    assert kinds.count("done") == 1


def test_error_event_is_terminal():
    backend = ScriptedBackend([BackendError(message="boom"), ToolCall(tool="canvas_read")])
    orch = SessionOrchestrator()
    frames = _events(orch.stream_events(backend=backend, owner="a", prompt="p"))
    kinds = [e for e, _ in frames]
    assert kinds == ["error", "done"], f"error must be terminal: {kinds}"


def test_exception_during_run_becomes_honest_error_not_crash():
    # A backend that raises mid-stream must yield an honest error + terminal done,
    # never propagate an unhandled exception (which would 500 the SSE stream).
    backend = ScriptedBackend([AssistantText(text="working"), RuntimeError("backend blew up")])
    orch = SessionOrchestrator()
    frames = _events(orch.stream_events(backend=backend, owner="a", prompt="p"))
    kinds = [e for e, _ in frames]
    assert kinds == ["say", "error", "done"], f"crash not converted to honest error: {kinds}"
    assert "backend blew up" in frames[1][1]["message"]


def test_exception_during_refresh_becomes_honest_error():
    def _boom():
        raise RuntimeError("refresh failed")

    backend = ScriptedBackend([ToolResult(tool="canvas_create_node", result={"qro_id": "q1"}), Done()])
    orch = SessionOrchestrator(refresh_store=_boom)
    kinds = [e for e, _ in _events(orch.stream_events(backend=backend, owner="a", prompt="p"))]
    assert "error" in kinds and kinds[-1] == "done"


def test_exception_during_preflight_becomes_honest_error():
    class _PreflightBoom:
        def preflight(self):
            raise RuntimeError("preflight exploded")

        def run(self, **kwargs):  # pragma: no cover - must never be reached
            yield Done()

    orch = SessionOrchestrator()
    frames = _events(orch.stream_events(backend=_PreflightBoom(), owner="a", prompt="p"))
    kinds = [e for e, _ in frames]
    assert kinds == ["error", "done"]
    assert "preflight exploded" in frames[0][1]["message"]


def test_liveness_cap_cuts_off_runaway_finite_stream():
    # Cross-vendor floor: a backend that streams many events without a terminal
    # frame gets cut off honestly, so the SSE can never hang. Finite (20) so this
    # test — and the mutation on it — never actually hang.
    backend = ScriptedBackend([AssistantText(text=f"c{i}") for i in range(20)])  # no Done
    orch = SessionOrchestrator(max_events=5)
    kinds = [e for e, _ in _events(orch.stream_events(backend=backend, owner="a", prompt="p"))]
    assert "error" in kinds, "runaway stream must be cut off with an honest error"
    assert kinds[-1] == "done"
    assert kinds.count("say") <= 6, "must cut near the cap, not stream all 20"


def test_liveness_cap_bounds_an_infinite_stream_without_hanging():
    import itertools

    class _Infinite:
        def preflight(self):
            return _ready_readiness()

        def run(self, **kwargs):
            for i in itertools.count():
                yield AssistantText(text=f"c{i}")

    orch = SessionOrchestrator(max_events=10)
    frames = _events(orch.stream_events(backend=_Infinite(), owner="a", prompt="p"))  # must return
    kinds = [e for e, _ in frames]
    assert kinds[-1] == "done" and "error" in kinds


def test_base_exception_propagates_and_is_not_swallowed():
    import pytest

    class _KbBackend:
        def preflight(self):
            return _ready_readiness()

        def run(self, **kwargs):
            yield AssistantText(text="hi")
            raise KeyboardInterrupt()  # control-flow signal — must NOT become an SSE frame

    orch = SessionOrchestrator()
    with pytest.raises(KeyboardInterrupt):
        list(orch.stream_events(backend=_KbBackend(), owner="a", prompt="p"))


def test_stream_sse_formats_wire_frames():
    backend = ScriptedBackend([AssistantText(text="hi"), Done()])
    orch = SessionOrchestrator()
    wire = list(orch.stream_sse(backend=backend, owner="a", prompt="p"))
    assert all(f.startswith("event: ") and f.endswith("\n\n") for f in wire)
    assert any("event: say" in f for f in wire)
    assert any("event: done" in f for f in wire)
