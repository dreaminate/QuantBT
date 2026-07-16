"""Session orchestrator — drive an external agent backend into SSE (agent M4).

Ties the pieces together: preflight the backend (honest — no silent fallback to
an internal agent), drive ``backend.run()``, map each ``BackendEvent`` onto the
existing SSE vocabulary, and — the cross-process bit — refresh the API process's
research-graph store the moment the agent's (future) canvas write lands, so the
write is visible to the next canvas read (finding §4).

The orchestrator is backend-agnostic (``AgentBackend`` Protocol), so tests drive
it with a ScriptedBackend and assert the SSE frames with no subprocess.
"""

from __future__ import annotations

from typing import Any, Callable, Iterator, Protocol

from .backends.base import BackendReadiness
from .backends.events import (
    BackendEvent,
    backend_events_to_sse,
    is_cross_process_write,
)


class AgentBackend(Protocol):
    """What the orchestrator needs from any agent backend."""

    def preflight(self) -> BackendReadiness: ...

    def run(self, *, prompt: str, owner: str, **kwargs: Any) -> Iterator[BackendEvent]: ...


class SessionOrchestrator:
    """Drive one agent turn → SSE frames.

    ``refresh_store`` is called (once) as each cross-process canvas-write event
    passes, so the API store reflects the agent's write before the ``tool_end``
    frame reaches the frontend (which then re-fetches the projection).
    """

    def __init__(
        self, *, refresh_store: Callable[[], None] | None = None, max_events: int = 100_000
    ) -> None:
        self._refresh = refresh_store
        # Liveness bound (cross-vendor floor finding): a backend that streams
        # forever without a terminal event gets cut off with an honest error, so
        # the SSE response can never hang indefinitely. Set high enough that a
        # normal (chunked) turn never approaches it.
        self._max_events = max_events

    def _with_refresh(self, events: Iterator[BackendEvent]) -> Iterator[BackendEvent]:
        for ev in events:
            if self._refresh is not None and is_cross_process_write(ev):
                self._refresh()
            yield ev

    def stream_events(
        self, *, backend: AgentBackend, owner: str, prompt: str, **run_kwargs: Any
    ) -> Iterator[dict[str, Any]]:
        """Yield ``{event, data}`` SSE dicts for one turn.

        Not-ready → a single honest ``error`` frame then ``done`` — never a
        fallback to an internal agent (RULES §3 honest boundary).
        """

        try:
            readiness = backend.preflight()
        except Exception as exc:  # noqa: BLE001 — a preflight crash must be honest, not a 500
            yield {"event": "error", "data": {"message": f"agent preflight failed: {exc}", "ready": False}}
            yield {"event": "done", "data": {"reason": "error"}}
            return

        if not readiness.ready:
            yield {
                "event": "error",
                "data": {
                    "message": f"agent backend not ready: {readiness.detail}",
                    "ready": False,
                    "provider": readiness.provider,
                },
            }
            yield {"event": "done", "data": {"reason": "not_ready"}}
            return

        # Drive the backend. Terminal semantics are ENFORCED here (cross-vendor
        # floor finding): the FIRST done/error is terminal — trailing events from a
        # malformed backend stream are dropped, and done is never duplicated. Any
        # exception during iteration (run()/refresh() raising) becomes an honest
        # error + terminal done — never a silent crash, never a fallback.
        try:
            stream = self._with_refresh(backend.run(prompt=prompt, owner=owner, **run_kwargs))
            count = 0
            for sse in backend_events_to_sse(stream):
                count += 1
                if count > self._max_events:
                    yield {
                        "event": "error",
                        "data": {
                            "message": f"agent stream exceeded {self._max_events} events without terminating",
                            "reason": "event_limit",
                        },
                    }
                    yield {"event": "done", "data": {"reason": "event_limit"}}
                    return
                if sse["event"] == "error":
                    yield sse
                    yield {"event": "done", "data": {"reason": "error"}}
                    return
                if sse["event"] == "done":
                    yield sse
                    return
                yield sse
        except Exception as exc:  # noqa: BLE001 — honest error, no silent crash / fallback
            yield {"event": "error", "data": {"message": f"agent stream failed: {exc}"}}
            yield {"event": "done", "data": {"reason": "error"}}
            return

        # Backend ended without an explicit Done → still emit a terminal frame.
        yield {"event": "done", "data": {"reason": "stream_ended"}}

    def stream_sse(
        self, *, backend: AgentBackend, owner: str, prompt: str, **run_kwargs: Any
    ) -> Iterator[str]:
        """Same as ``stream_events`` but formatted as SSE wire frames."""

        from .workbench_stream import sse_format

        for sse in self.stream_events(backend=backend, owner=owner, prompt=prompt, **run_kwargs):
            yield sse_format(sse["event"], sse["data"])
