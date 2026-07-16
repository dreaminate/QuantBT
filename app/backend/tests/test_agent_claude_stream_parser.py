"""M4b: claude stream-json → BackendEvent parser + ClaudeBackend spawn contract.

Two layers:
- The PURE parser (``parse_claude_stream_json_lines``) is proven against a REAL
  captured claude v2.1.210 sample (``fixtures/claude_stream_json_sample.jsonl``) —
  the oracle — plus targeted edge cases. Using real output as the fixture avoids the
  self-fabricated-oracle trap (a hand-guessed schema whose tests pass against the
  same guess); the live sample caught that ``thinking`` blocks exist and that
  ``tool_result`` omits ``is_error`` on success.
- ``ClaudeBackend.run()`` is proven by spawning a stub CLI (``fixtures/fake_claude_cli.py``)
  that emits canned stream-json — exercising the REAL spawn/stdin/stdout/parse wiring
  and the L-C spawn env (master key absent) without a live subscription.

Mutation contract (RULES §2 种坏门必抓):
- Map ``thinking`` blocks to AssistantText → the thinking-skip test goes RED (internal
  reasoning would leak to the canvas).
- Drop the tool_use_id→name correlation → the tool-name test goes RED.
- Treat a non-success ``result`` as Done → the error-result test goes RED.
- ``os.environ.copy()`` instead of build_spawn_env in run() → the L-C test goes RED.
"""

from __future__ import annotations

import os
import stat
from pathlib import Path

import pytest

from app.agent.backends.claude_backend import (
    ClaudeBackend,
    _coerce_tool_result,
    parse_claude_stream_json_lines,
)
from app.agent.backends.events import (
    AssistantText,
    BackendError,
    Done,
    SessionStarted,
    ToolCall,
    ToolResult,
)

FIXTURES = Path(__file__).resolve().parent / "fixtures"
SAMPLE = FIXTURES / "claude_stream_json_sample.jsonl"
STUB_CLI = FIXTURES / "fake_claude_cli.py"


# --- Pure parser, real-sample oracle ---------------------------------------


def test_parses_real_sample_to_expected_sequence():
    """The committed REAL claude sample → the exact BackendEvent sequence.

    Sanitized-but-schema-faithful: 2 hook-noise system lines + rate_limit are
    skipped; the thinking block is skipped; the tool_result resolves its tool NAME
    from the earlier tool_use; the final result is a Done.
    """

    events = list(parse_claude_stream_json_lines(SAMPLE.read_text().splitlines()))
    kinds = [type(e).__name__ for e in events]
    assert kinds == ["SessionStarted", "ToolCall", "ToolResult", "AssistantText", "Done"]

    assert isinstance(events[0], SessionStarted) and events[0].session_id
    assert isinstance(events[1], ToolCall) and events[1].tool == "Read"
    # tool_result carried only tool_use_id — the parser resolved the NAME from tool_use.
    assert isinstance(events[2], ToolResult) and events[2].tool == "Read"
    assert events[2].is_error is False  # is_error absent on success → False
    assert isinstance(events[3], AssistantText) and events[3].text
    assert isinstance(events[4], Done) and events[4].reason == "success"


def test_thinking_blocks_are_never_surfaced():
    """An assistant message with a thinking block yields NO event for it (only text)."""

    line = (
        '{"type":"assistant","message":{"role":"assistant","content":['
        '{"type":"thinking","thinking":"secret reasoning","signature":"sig"},'
        '{"type":"text","text":"visible"}]}}'
    )
    events = list(parse_claude_stream_json_lines([line]))
    assert [type(e).__name__ for e in events] == ["AssistantText"]
    assert events[0].text == "visible"


def test_tool_use_id_correlated_to_name_across_lines():
    """tool_result (which carries only tool_use_id) resolves to the tool_use name."""

    lines = [
        '{"type":"assistant","message":{"content":[{"type":"tool_use","id":"tu_1","name":"mcp__quantbt-agent-canvas__canvas_create_node","input":{"qro_type":"Factor"}}]}}',
        '{"type":"user","message":{"content":[{"type":"tool_result","tool_use_id":"tu_1","content":"{\\"qro_id\\":\\"q1\\",\\"run_id\\":\\"r9\\"}"}]}}',
    ]
    events = list(parse_claude_stream_json_lines(lines))
    assert isinstance(events[0], ToolCall)
    assert events[0].tool == "mcp__quantbt-agent-canvas__canvas_create_node"
    assert isinstance(events[1], ToolResult)
    assert events[1].tool == "mcp__quantbt-agent-canvas__canvas_create_node"
    # canvas JSON result parsed to a dict so run_id lifting / cross-process detection work.
    assert events[1].result == {"qro_id": "q1", "run_id": "r9"}


def test_tool_result_is_error_present_and_absent():
    """is_error True when present-and-true; False when the key is absent (success shape)."""

    lines = [
        '{"type":"assistant","message":{"content":[{"type":"tool_use","id":"a","name":"Read"},{"type":"tool_use","id":"b","name":"Bash"}]}}',
        '{"type":"user","message":{"content":[{"type":"tool_result","tool_use_id":"a","content":"ok"}]}}',
        '{"type":"user","message":{"content":[{"type":"tool_result","tool_use_id":"b","content":"fail","is_error":true}]}}',
    ]
    events = list(parse_claude_stream_json_lines(lines))
    results = [e for e in events if isinstance(e, ToolResult)]
    assert results[0].is_error is False  # absent → False
    assert results[1].is_error is True


def test_result_error_becomes_backend_error_not_done():
    """A non-success / is_error result is an honest BackendError, never a Done."""

    for line in (
        '{"type":"result","subtype":"error_max_turns","is_error":false,"result":"hit turn cap"}',
        '{"type":"result","subtype":"success","is_error":true,"result":"actually failed"}',
    ):
        events = list(parse_claude_stream_json_lines([line]))
        assert len(events) == 1 and isinstance(events[0], BackendError)


def test_success_result_is_done():
    events = list(parse_claude_stream_json_lines(['{"type":"result","subtype":"success","is_error":false,"result":"ok"}']))
    assert isinstance(events[0], Done) and events[0].reason == "success"


def test_result_without_subtype_is_not_assumed_success(  # cross-vendor floor finding
):
    """A result missing subtype (success not POSITIVELY established) → BackendError, not Done."""

    for line in (
        '{"type":"result","result":"ambiguous"}',          # no subtype at all
        '{"type":"result","subtype":"","is_error":false}',  # blank subtype
    ):
        events = list(parse_claude_stream_json_lines([line]))
        assert len(events) == 1 and isinstance(events[0], BackendError)


def test_non_dict_message_is_skipped_not_crashing(  # cross-vendor floor finding
):
    """Valid JSON whose assistant/user ``message`` is not an object → skipped, no crash."""

    lines = [
        '{"type":"assistant","message":"not an object"}',
        '{"type":"user","message":[1,2,3]}',
        '{"type":"assistant","message":null}',
        '{"type":"result","subtype":"success"}',
    ]
    events = list(parse_claude_stream_json_lines(lines))
    assert [type(e).__name__ for e in events] == ["Done"]


def test_noise_and_malformed_lines_skipped_not_crashing():
    """Hook/rate-limit/unknown/blank/malformed lines are skipped without crashing."""

    lines = [
        "",
        "   ",
        "not json at all {",
        '{"type":"system","subtype":"hook_started"}',
        '{"type":"system","subtype":"api_retry","attempt":1}',
        '{"type":"rate_limit_event","rate_limit_info":{}}',
        '{"type":"some_future_type","foo":1}',
        "[1,2,3]",  # valid json but not a dict
        '{"type":"result","subtype":"success"}',
    ]
    events = list(parse_claude_stream_json_lines(lines))
    assert [type(e).__name__ for e in events] == ["Done"]


def test_unknown_tool_use_id_falls_back_not_crash():
    line = '{"type":"user","message":{"content":[{"type":"tool_result","tool_use_id":"never_seen","content":"x"}]}}'
    events = list(parse_claude_stream_json_lines([line]))
    assert isinstance(events[0], ToolResult) and events[0].tool == "never_seen"


def test_coerce_tool_result_shapes():
    assert _coerce_tool_result('{"run_id":"r1"}') == {"run_id": "r1"}
    assert _coerce_tool_result("plain text") == {"content": "plain text"}
    assert _coerce_tool_result({"already": "dict"}) == {"already": "dict"}
    assert _coerce_tool_result([{"type": "text", "text": "hi"}]) == {"content": "hi"}


# --- ClaudeBackend.run() spawn contract (via stub CLI) ---------------------


@pytest.fixture
def stub_cli() -> str:
    """Ensure the stub is executable (shebang → python3) and return its path."""

    STUB_CLI.chmod(STUB_CLI.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
    return str(STUB_CLI)


def _backend(stub: str, tmp_path: Path) -> ClaudeBackend:
    return ClaudeBackend(
        model="claude-test",
        workspace_dir=tmp_path / "ws",
        data_root=tmp_path / "data",
        backend_root=tmp_path / "backend",
        canvas_token="canvas-tok",
        cli_path=stub,
    )


def test_run_spawns_stub_and_streams_events(stub_cli, tmp_path, monkeypatch):
    """Real spawn: prompt on STDIN (not argv) + L-C env (no master key) proven via events."""

    # Put a master key + venue secret in the PARENT env — L-C must keep them out.
    monkeypatch.setenv("QUANTBT_MASTER_KEY", "super-secret-master")
    monkeypatch.setenv("BINANCE_API_SECRET", "venue-secret")

    backend = _backend(stub_cli, tmp_path)
    events = list(backend.run(prompt="SECRET_PROMPT_MARKER hello", owner="alice"))

    kinds = [type(e).__name__ for e in events]
    assert kinds == ["SessionStarted", "AssistantText", "ToolCall", "ToolResult", "Done"]

    import json

    report = json.loads(next(e for e in events if isinstance(e, AssistantText)).text)
    assert report["got_prompt"] == "SECRET_PROMPT_MARKER hello"  # prompt arrived via stdin
    assert report["prompt_in_argv"] is False                      # never on argv
    assert report["has_master_key"] is False                      # L-C: master key absent
    assert report["has_binance_secret"] is False                  # L-C: venue secret absent
    assert report["qb_owner"] == "alice"                          # identity injected

    # canvas_read tool_result JSON was parsed to a dict.
    tr = next(e for e in events if isinstance(e, ToolResult))
    assert tr.tool == "canvas_read" and tr.result == {"nodes": [], "count": 0}


def test_run_nonzero_exit_without_terminal_is_backend_error(stub_cli, tmp_path):
    """crash mode: stub emits init then exits 3 with no terminal → honest BackendError.

    Mode goes on the stdin prompt (an env knob would be stripped by the L-C allowlist).
    """

    backend = _backend(stub_cli, tmp_path)
    events = list(backend.run(prompt="FAKE_CLAUDE_MODE=crash\nhi", owner="alice"))
    assert isinstance(events[0], SessionStarted)
    assert isinstance(events[-1], BackendError)
    assert "exited 3" in events[-1].message


def test_run_error_result_is_backend_error(stub_cli, tmp_path):
    backend = _backend(stub_cli, tmp_path)
    events = list(backend.run(prompt="FAKE_CLAUDE_MODE=error\nhi", owner="alice"))
    assert isinstance(events[-1], BackendError) and "boom" in events[-1].message
