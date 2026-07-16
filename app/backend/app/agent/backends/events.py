"""Backend event union + mapping to the existing SSE vocabulary (agent M4).

The external agent CLI emits a stream (claude ``stream-json``). We normalize it
to a small ``BackendEvent`` union, then map that union onto the SAME SSE event
vocabulary the in-process agent already uses (``say`` / ``tool_start`` /
``tool_end`` / ``done`` / ``error`` — see workbench_stream.project_turn_events).
So the frontend GraphCanvas / workbench consumes one event contract regardless of
which agent produced the turn. This module is PURE (no I/O), hence unit-testable
without spawning anything.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable, Iterator


@dataclass(frozen=True)
class SessionStarted:
    """The backend session began (maps to a leading ``say``)."""

    session_id: str = ""


@dataclass(frozen=True)
class AssistantText:
    """Assistant prose (maps to ``say``)."""

    text: str


@dataclass(frozen=True)
class ToolCall:
    """The agent invoked a tool (maps to ``tool_start``)."""

    tool: str
    tool_input: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ToolResult:
    """A tool returned (maps to ``tool_end``)."""

    tool: str
    result: dict[str, Any] = field(default_factory=dict)
    is_error: bool = False


@dataclass(frozen=True)
class Done:
    """The turn finished (maps to ``done``)."""

    reason: str = "complete"


@dataclass(frozen=True)
class BackendError:
    """The backend errored (maps to ``error``). Honest — never a silent fallback."""

    message: str


BackendEvent = (
    SessionStarted | AssistantText | ToolCall | ToolResult | Done | BackendError
)

# Tools that mutate the research graph across the MCP process boundary. When the
# orchestrator sees one of these succeed it must refresh the API process's store
# (spine cross-process refresh) so the write becomes visible to canvas reads.
CROSS_PROCESS_WRITE_TOOLS: frozenset[str] = frozenset(
    {
        "mcp__quantbt-agent-canvas__canvas_create_node",
        "canvas_create_node",
    }
)


def backend_events_to_sse(events: Iterable[BackendEvent]) -> Iterator[dict[str, Any]]:
    """Map a ``BackendEvent`` stream onto ``{event, data}`` SSE dicts.

    Uses exactly the existing vocabulary so the frontend needs no new handler:
    SessionStarted/AssistantText → ``say``; ToolCall → ``tool_start``;
    ToolResult → ``tool_end`` (lifting ``run_id`` to the top level like
    project_turn_events does); Done → ``done``; BackendError → ``error``.
    """

    for ev in events:
        if isinstance(ev, SessionStarted):
            yield {"event": "say", "data": {"text": f"agent session started: {ev.session_id}".strip()}}
        elif isinstance(ev, AssistantText):
            yield {"event": "say", "data": {"text": ev.text}}
        elif isinstance(ev, ToolCall):
            yield {"event": "tool_start", "data": {"tool": ev.tool}}
        elif isinstance(ev, ToolResult):
            data: dict[str, Any] = {"tool": ev.tool, "result": ev.result, "is_error": ev.is_error}
            if isinstance(ev.result, dict):
                rid = ev.result.get("run_id")
                if rid:
                    data["run_id"] = str(rid)
            yield {"event": "tool_end", "data": data}
        elif isinstance(ev, Done):
            yield {"event": "done", "data": {"reason": ev.reason}}
        elif isinstance(ev, BackendError):
            yield {"event": "error", "data": {"message": ev.message}}
        else:  # pragma: no cover - exhaustive union
            raise TypeError(f"unknown BackendEvent: {type(ev).__name__}")


def is_cross_process_write(ev: BackendEvent) -> bool:
    """A successful canvas-write ToolResult that the API store must refresh for."""

    return (
        isinstance(ev, ToolResult)
        and not ev.is_error
        and ev.tool in CROSS_PROCESS_WRITE_TOOLS
    )
