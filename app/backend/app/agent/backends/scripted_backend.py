"""Scripted / replay backend for orchestrator tests (agent M4).

Drives the orchestrator with a fixed ``BackendEvent`` sequence instead of
spawning a real CLI, so the SSE mapping + orchestration control flow are testable
deterministically with no subprocess. Mirrors how the in-process agent has a
scripted runtime for its workbench-stream tests.
"""

from __future__ import annotations

from typing import Iterable, Iterator

from .base import BackendReadiness
from .events import BackendEvent


class ScriptedBackend:
    """A backend whose ``run`` replays a predetermined event list.

    ``ready`` controls what ``preflight`` reports — set it False to exercise the
    honest not-ready → SSE error path (no fallback).
    """

    def __init__(
        self,
        events: Iterable[BackendEvent],
        *,
        ready: bool = True,
        detail: str = "scripted",
    ) -> None:
        self._events = list(events)
        self._ready = ready
        self._detail = detail
        self.run_calls: list[dict[str, object]] = []

    def preflight(self) -> BackendReadiness:
        return BackendReadiness(
            provider="scripted",
            cli="scripted",
            cli_installed=self._ready,
            authed=self._ready,
            ready=self._ready,
            detail=self._detail,
        )

    def run(self, *, prompt: str, owner: str, **kwargs: object) -> Iterator[BackendEvent]:
        # Record the invocation so tests can assert owner/prompt threading.
        self.run_calls.append({"prompt": prompt, "owner": owner, **kwargs})
        for ev in self._events:
            # An Exception in the script raises mid-stream — exercises the
            # orchestrator's honest error-on-crash path. We deliberately match the
            # orchestrator's ``except Exception`` (NOT BaseException): control-flow
            # signals (KeyboardInterrupt / SystemExit / GeneratorExit / CancelledError)
            # must propagate for clean shutdown/cancellation, never be turned into an
            # SSE frame. So the honest-error contract covers Exception only.
            if isinstance(ev, Exception):
                raise ev
            yield ev
