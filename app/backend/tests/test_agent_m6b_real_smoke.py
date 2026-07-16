"""M6b opt-in real-claude smoke + the anti-fake-green boundary (agent epic finale).

The headline deliverable: a smoke that spawns the REAL subscription ``claude`` and
proves the embedded-agent chain end-to-end — read the canvas, create ONE offline
draft node — with assertions no mock can fake. It is GATED
(``QUANTBT_AGENT_REAL_SMOKE=1`` AND ``preflight().ready``) and CI honestly SKIPs it
(``KNOWN_RUN_GAP`` — never a fake pass, never a silent mock substitution).

The CI-safe tests here pin the honesty MECHANISM so "green CI" cannot lie:
- gate is default-OFF and requires the exact ``"1"`` → CI SKIPs, never spawns/fakes;
- the module never falls back to a stub backend (no silent mock);
- the ground-truth is the STORE, not the event stream — an event-only "I created a
  node" claim is caught because only a real MCP write appends a store row;
- the ``init.mcp_servers`` assertion's SHAPE is verified against the committed REAL
  claude oracle sample (not an assumption).

Mutation contract (RULES §2 种坏门必抓):
- Gate flips to default-on / ``!= "0"`` → the gate test goes RED (CI would try to
  spawn claude and flake).
- Assert on the event stream instead of the store → the ground-truth test goes RED
  (an event-only fake would pass).
"""

from __future__ import annotations

import json
import os
import shutil
from pathlib import Path

import pytest

from app.agent.backends.claude_backend import (
    CANVAS_CREATE_NODE_TOOL,
    CANVAS_READ_TOOL,
    MCP_SERVER_NAME,
    parse_claude_stream_json_lines,
    preflight,
)
from app.agent.backends.events import SessionStarted, ToolResult

FIXTURES = Path(__file__).resolve().parent / "fixtures"
SAMPLE = FIXTURES / "claude_stream_json_sample.jsonl"


def _real_smoke_enabled(value: str | None) -> bool:
    """Explicit opt-in: EXACTLY ``"1"``. Never ``!= "0"`` (that is default-on)."""

    return value == "1"


def _offline_node_landed(store_path: Path, *, owner: str) -> bool:
    """GROUND TRUTH: did a real MCP write append an OFFLINE node row for ``owner``?

    Reads the STORE, not the event stream — an agent (or a fake) can *emit* a
    canvas_create_node tool_result event without any row ever being appended, so
    only this store read distinguishes a real write from a claimed one. Also pins the
    L-D envelope: the landed node must be ``runtime_status=OFFLINE`` (the plan requires
    an OFFLINE node), so a (hypothetical) non-OFFLINE write would not satisfy it.
    """

    from app.research_os.spine import PersistentResearchGraphStore, RuntimeStatus

    if not store_path.exists():
        return False
    store = PersistentResearchGraphStore(store_path)
    offline = store.projection_index(owner=owner, runtime_status=RuntimeStatus.OFFLINE.value)
    return len(offline) >= 1


# --- CI-safe honesty-mechanism tests (always run) --------------------------


def test_gate_is_default_off_and_requires_exact_one():
    assert _real_smoke_enabled(None) is False       # CI: env unset → SKIP
    assert _real_smoke_enabled("0") is False
    assert _real_smoke_enabled("") is False
    assert _real_smoke_enabled("true") is False      # NOT != "0"
    assert _real_smoke_enabled("2") is False
    assert _real_smoke_enabled("1") is True          # explicit opt-in only


def test_smoke_never_falls_back_to_a_stub_backend():
    """No silent mock: this module builds only the real ClaudeBackend."""

    src = Path(__file__).read_text()
    forbidden = "scripted" + "_backend"  # built at runtime so this check isn't self-referential
    assert forbidden not in src, "real-smoke must never import/construct a stub backend"
    assert "ClaudeBackend" in src


def test_init_mcp_servers_shape_verified_against_real_oracle():
    """B4(a)'s assertion SHAPE, verified against the committed REAL claude sample —
    so the opt-in live smoke's ``mcp_servers == (our server,)`` rests on real data,
    not an assumption (deep-opus flagged the shape as otherwise unverified)."""

    events = list(parse_claude_stream_json_lines(SAMPLE.read_text().splitlines()))
    started = next(e for e in events if isinstance(e, SessionStarted))
    assert started.mcp_servers == (MCP_SERVER_NAME,)


def test_ground_truth_store_read_catches_event_only_fakery(tmp_path):
    """A stream can CLAIM canvas_create_node via events while appending NOTHING; the
    smoke asserts the STORE, so the fake is caught. This is the load-bearing check —
    revert the smoke to asserting the event stream and an event-only fake passes."""

    lines = [
        '{"type":"assistant","message":{"content":[{"type":"tool_use","id":"t1",'
        '"name":"mcp__quantbt-agent-canvas__canvas_create_node","input":{}}]}}',
        '{"type":"user","message":{"content":[{"type":"tool_result","tool_use_id":"t1",'
        '"content":"{\\"qro_id\\":\\"faked\\"}"}]}}',
        '{"type":"result","subtype":"success","is_error":false,"result":"done"}',
    ]
    events = list(parse_claude_stream_json_lines(lines))
    # The EVENT stream claims a create...
    assert any(isinstance(e, ToolResult) and "canvas_create_node" in e.tool for e in events)
    # ...but the GROUND TRUTH (store) says nothing landed → fakery caught.
    empty_store = tmp_path / "audit" / "research_graph_commands.jsonl"
    assert _offline_node_landed(empty_store, owner="anyone") is False


def test_live_smoke_still_wired_to_ground_truth_and_sse():
    """Pin that the live smoke still CALLS the store ground-truth AND drives the SSE
    orchestrator (not ``backend.run()`` directly) — so removing either from the smoke
    is caught even though the smoke itself is CI-skipped (cross-vendor floor: meta
    tests must pin the helper stays wired, not just that it works)."""

    src = Path(__file__).read_text()
    # Build the marker at runtime so THIS test's source doesn't self-match the search.
    marker = "def " + "test_real_claude_canvas_smoke(tmp_path):"
    body = src[src.index(marker):]  # the smoke is the last function → body is its body
    assert "_offline_node_landed(" in body, "live smoke must call the store ground-truth"
    assert "no node landed" in body, "live smoke must assert on the ground-truth result"
    assert "stream_events(" in body, "live smoke must drive the SSE orchestrator, not backend.run() directly"
    assert "tool_start" in body and "tool_end" in body  # SSE frames the plan requires


def test_ground_truth_positive_control(tmp_path, monkeypatch):
    """The ground-truth read returns True for a node that REALLY landed (positive
    control, so the fakery test above is a discriminating check, not always-False)."""

    from app.agent_mcp import server as mcp_server

    path = tmp_path / "audit" / "research_graph_commands.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(mcp_server, "RESEARCH_GRAPH_COMMANDS_PATH", path)
    monkeypatch.setattr(mcp_server, "_STORE", None)
    monkeypatch.setenv("QB_OWNER", "real-owner")
    mcp_server.canvas_create_node({
        "qro_type": "factor", "market": "ashare_hs300", "universe": "hs300",
        "horizon": "20d", "frequency": "daily", "assumptions": ["a"],
        "known_limits": ["l"], "failure_modes": ["f"], "validation_plan": ["v"],
    })
    assert _offline_node_landed(path, owner="real-owner") is True


# --- The opt-in real-claude smoke (CI honestly SKIPs) -----------------------

REAL_SMOKE = _real_smoke_enabled(os.environ.get("QUANTBT_AGENT_REAL_SMOKE"))


@pytest.mark.skipif(
    not REAL_SMOKE,
    reason="KNOWN_RUN_GAP: opt-in real-claude smoke — set QUANTBT_AGENT_REAL_SMOKE=1 "
    "(and be subscription-authed) to run; CI SKIPs it, never a fake pass",
)
def test_real_claude_canvas_smoke(tmp_path):
    """REAL claude through the SSE orchestrator: read the canvas + create one OFFLINE node."""

    from app.agent.backends.claude_backend import ClaudeBackend
    from app.agent.session_orchestrator import SessionOrchestrator

    rd = preflight()
    if not rd.ready:
        pytest.skip(f"KNOWN_RUN_GAP: claude CLI not subscription-ready ({rd.detail})")

    backend_root = Path(__file__).resolve().parents[1]  # app/backend (holds app/)
    data_root = tmp_path / "data"
    owner = "smoke-owner"
    backend = ClaudeBackend(
        model="claude-sonnet-4-5",
        workspace_dir=tmp_path / "ws",
        data_root=data_root,
        backend_root=backend_root,
        canvas_token="smoke-tok",
        idle_timeout_s=120.0,
        total_timeout_s=300.0,
    )
    # Structurally the REAL backend spawning the REAL binary — never a stub.
    assert isinstance(backend, ClaudeBackend)
    assert shutil.which(backend._cli_path), "claude binary not on PATH"

    prompt = (
        "First call canvas_read to view the research canvas. Then call "
        "canvas_create_node to add ONE offline draft node with qro_type='factor', "
        "market='ashare_hs300', universe='hs300', horizon='20d', frequency='daily', "
        "and assumptions/known_limits/failure_modes/validation_plan each a one-item "
        "list stating a falsifiable hypothesis. Make BOTH tool calls, then stop."
    )
    # Drive the REAL SSE path (SessionOrchestrator → the SSE vocabulary the frontend
    # consumes), NOT backend.run() directly — the plan requires the smoke to cover the
    # SSE tool_start/tool_end/done mapping, not just raw BackendEvents.
    orch = SessionOrchestrator()
    frames = list(orch.stream_events(backend=backend, owner=owner, prompt=prompt))
    names = [f["event"] for f in frames]

    # (a) init.mcp_servers surfaced into the leading say frame — exactly our server.
    say_mcp = next(
        (f["data"].get("mcp_servers") for f in frames
         if f["event"] == "say" and f["data"].get("mcp_servers")),
        None,
    )
    assert say_mcp == [MCP_SERVER_NAME]
    # (b) >=2 tool_use via SSE tool_start frames — canvas_read AND canvas_create_node.
    tool_starts = {f["data"].get("tool") for f in frames if f["event"] == "tool_start"}
    assert CANVAS_READ_TOOL in tool_starts and CANVAS_CREATE_NODE_TOOL in tool_starts
    # SSE tool_start/tool_end/done covered; terminal done, no error frame (no fake fallback).
    assert "tool_end" in names
    assert names[-1] == "done" and "error" not in names
    # (c) GROUND TRUTH: an OFFLINE node actually landed in the store.
    store_path = data_root / "audit" / "research_graph_commands.jsonl"
    assert _offline_node_landed(store_path, owner=owner), "no node landed — fake/incomplete run"

    # Local receipt = falsifiable evidence a human can re-verify; CI never reads it.
    (tmp_path / "agent_real_smoke_receipt.json").write_text(
        json.dumps(
            {
                "mcp_servers": say_mcp,
                "tool_starts": sorted(tool_starts),
                "owner": owner,
                "store": str(store_path),
            },
            ensure_ascii=False,
        )
    )
