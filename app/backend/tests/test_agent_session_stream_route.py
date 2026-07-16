"""M4b: GET /api/agent/session/stream — the embedded-agent SSE route.

Mirrors the existing agent_workbench_stream test setup (dependency_overrides for
auth + client.stream for SSE). The route is driven with an INJECTED ScriptedBackend
(via the _build_session_backend factory seam) so no real claude is spawned and the
outcome is deterministic — even though this env has claude authed, tests never touch
a live subscription.

Mutation contract (RULES §2 种坏门必抓):
- Route calls backend.run() even when preflight is not-ready → not-ready test goes RED.
- Route drops the refresh_store hook → cross-process-refresh test goes RED.
- Route doesn't strip/terminate on empty prompt → empty-prompt test goes RED.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

import app.main as main
from app.agent.backends.events import (
    AssistantText,
    Done,
    SessionStarted,
    ToolCall,
    ToolResult,
)
from app.agent.backends.scripted_backend import ScriptedBackend


def _events_from_sse(text: str) -> list[str]:
    """Extract the ordered ``event:`` names from an SSE wire body."""

    names = []
    for block in text.split("\n\n"):
        for line in block.splitlines():
            if line.startswith("event:"):
                names.append(line.split(":", 1)[1].strip())
    return names


@pytest.fixture
def client(monkeypatch):
    main.app.dependency_overrides[main.require_user_dependency] = lambda: SimpleNamespace(
        username="u1", user_id="u1"
    )
    try:
        yield TestClient(main.app)
    finally:
        main.app.dependency_overrides.pop(main.require_user_dependency, None)


def _inject(monkeypatch, backend: ScriptedBackend) -> ScriptedBackend:
    monkeypatch.setattr(main, "_build_session_backend", lambda **kw: backend)
    return backend


def test_happy_path_streams_existing_sse_vocabulary(client, monkeypatch):
    backend = _inject(
        monkeypatch,
        ScriptedBackend(
            [
                SessionStarted(session_id="s1"),
                AssistantText(text="working"),
                ToolCall(tool="canvas_read"),
                ToolResult(tool="canvas_read", result={"nodes": [], "count": 0}),
                Done(reason="success"),
            ]
        ),
    )
    with client.stream("GET", "/api/agent/session/stream", params={"q": "look at my canvas"}) as resp:
        assert resp.status_code == 200
        assert resp.headers["content-type"].startswith("text/event-stream")
        body = "".join(resp.iter_text())

    names = _events_from_sse(body)
    # SessionStarted+AssistantText→say; ToolCall→tool_start; ToolResult→tool_end; Done→done.
    assert names == ["say", "say", "tool_start", "tool_end", "done"]
    # owner + prompt were threaded into the backend run.
    assert backend.run_calls and backend.run_calls[0]["owner"] == "u1"
    assert backend.run_calls[0]["prompt"] == "look at my canvas"


def test_not_ready_is_honest_error_and_never_runs(client, monkeypatch):
    backend = _inject(monkeypatch, ScriptedBackend([Done()], ready=False, detail="claude not logged in"))
    with client.stream("GET", "/api/agent/session/stream", params={"q": "hi"}) as resp:
        body = "".join(resp.iter_text())

    names = _events_from_sse(body)
    assert names == ["error", "done"]
    assert "not ready" in body  # honest reason surfaced
    assert backend.run_calls == []  # run() NEVER called — no fallback to an internal agent


def test_empty_prompt_is_error_then_done(client, monkeypatch):
    backend = _inject(monkeypatch, ScriptedBackend([Done()]))
    with client.stream("GET", "/api/agent/session/stream", params={"q": "   "}) as resp:
        body = "".join(resp.iter_text())
    assert _events_from_sse(body) == ["error", "done"]
    assert backend.run_calls == []  # backend not even constructed-and-run for an empty prompt


def test_canvas_write_triggers_cross_process_refresh_once(client, monkeypatch):
    """A successful canvas_create_node ToolResult refreshes the API store exactly once."""

    calls = {"n": 0}
    monkeypatch.setattr(main.RESEARCH_GRAPH_STORE, "refresh", lambda: calls.__setitem__("n", calls["n"] + 1))
    _inject(
        monkeypatch,
        ScriptedBackend(
            [
                ToolCall(tool="canvas_create_node"),
                ToolResult(tool="canvas_create_node", result={"qro_id": "q1"}, is_error=False),
                # an errored write must NOT refresh
                ToolResult(tool="canvas_create_node", result={"error": "x"}, is_error=True),
                Done(),
            ]
        ),
    )
    with client.stream("GET", "/api/agent/session/stream", params={"q": "create a factor node"}) as resp:
        "".join(resp.iter_text())
    assert calls["n"] == 1  # exactly once: the successful write only
