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

import logging
from typing import Any, Callable, Iterator, Protocol

_log = logging.getLogger(__name__)

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
        # Event-COUNT bound (cross-vendor floor finding): a backend that streams
        # events forever WITHOUT a terminal one is cut off with an honest error once
        # this many events pass. This bounds event count ONLY — not wall-clock, not a
        # zero-output hung backend, and not a stopped consumer (those are the backend's
        # idle/total timeout, and the disconnect residual documented in stream_events).
        # Set high enough that a normal (chunked) turn never approaches it.
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
        #
        # ``raw`` is the backend's OWN generator, whose ``finally`` owns the child
        # process kill. We hold it explicitly and ``close()`` it in ``finally`` so a
        # cancel (client disconnect → GeneratorExit propagates in, it is a
        # BaseException so the ``except Exception`` below does NOT swallow it) or ANY
        # early return deterministically fires run()'s cleanup. Relying on the
        # transitive GeneratorExit → GC cascade would defer the kill whenever a
        # lingering reference (traceback frame / cycle) keeps the wrapper generators
        # alive, leaking a live ``claude`` + its MCP child per disconnect (agent M6b,
        # cross-vendor duet finding).
        # ``raw`` is created INSIDE the try so an EAGER backend whose ``run()`` raises
        # at call time (not a lazy generator) becomes an honest error frame, not an
        # uncaught crash to the transport (cross-vendor floor finding — codex).
        raw = None
        try:
            raw = backend.run(prompt=prompt, owner=owner, **run_kwargs)
            stream = self._with_refresh(raw)
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
        finally:
            # Deterministic child cleanup when THIS generator is closed (explicit
            # close, or ANY early return): closing ``raw`` throws GeneratorExit INTO
            # run() at its yield → run()'s finally → proc.kill(). Idempotent after
            # normal completion; guarded so a non-generator iterator (no ``close``) is
            # a safe no-op; and best-effort so a cleanup error in ``close()`` can never
            # leak to the transport after a terminal frame (both cross-vendor floor
            # findings — codex).
            #
            # HONEST RESIDUAL (do not overclaim): this deterministic reap fires only
            # when THIS generator is actually closed. A real HTTP client disconnect
            # closing it depends on the ASGI server's streaming semantics — Starlette
            # 1.1.0's sync-generator iteration does NOT force the close. And on an
            # abandoned (never-closed) generator the idle/total timeout does NOT reap
            # it either: the deadlines are only CHECKED while the consumer pulls a
            # line, so a stopped consumer means no check runs and neither timeout
            # fires. The child MAY then be blocked by stdout backpressure once our
            # queue+pipe fill (IF it keeps writing) — but a child that goes silent or
            # loops elsewhere is not throttled by us, so there is NO bound on child CPU
            # or process residency here. Our reader thread keeps a low-frequency poll
            # (retry put ~every 0.2s) until the generator is garbage-collected — GC
            # closes it → run()'s finally sets ``stop``, kills the child, joins the
            # reader. L-C/L-D still hold throughout (no key/venue reach). This is a
            # pre-existing resource residual (each abandoned turn = one live-or-blocked
            # claude + its MCP child + a 0.2s-poll reader thread until GC; NO proven
            # cap on CPU/process accumulation before GC), not a security boundary. The
            # idle/total timeout DOES reap the common case (a hung child while we are
            # still consuming). Route-level disconnect hardening (is_disconnected
            # polling) is the real fix — a registered follow-up (see dev/state).
            if raw is not None:
                close = getattr(raw, "close", None)
                if callable(close):
                    try:
                        close()
                    except Exception as close_exc:  # noqa: BLE001 — must not leak to transport
                        # ...but a REAL cleanup failure (e.g. proc.kill/wait) must not be
                        # silently lost — record it so an unreaped child is observable
                        # (cross-vendor R2 finding — codex).
                        _log.warning("agent backend cleanup (close) failed: %s", close_exc)

        # Backend ended without an explicit Done → still emit a terminal frame.
        yield {"event": "done", "data": {"reason": "stream_ended"}}

    def stream_sse(
        self, *, backend: AgentBackend, owner: str, prompt: str, **run_kwargs: Any
    ) -> Iterator[str]:
        """Same as ``stream_events`` but formatted as SSE wire frames."""

        from .workbench_stream import sse_format

        for sse in self.stream_events(backend=backend, owner=owner, prompt=prompt, **run_kwargs):
            yield sse_format(sse["event"], sse["data"])
