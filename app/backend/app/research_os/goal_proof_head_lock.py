"""Re-entrant cross-process lock for GOAL proof-head linearization.

Every durable writer that can change the §0-§17 source snapshot derives the
same lock path from the entrypoint coverage ledger.  The process-local RLock
makes nested registry calls safe while the advisory file lock excludes other
processes at the commit linearization point.
"""

from __future__ import annotations

import os
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from ..cross_process_lock import HeldExclusiveFileLock, acquire_exclusive_fd


class _ProofHeadLockState:
    def __init__(self) -> None:
        self.process_lock = threading.RLock()
        self.depth = 0
        self.fd: int | None = None
        self.held: HeldExclusiveFileLock | None = None


_STATE_GUARD = threading.Lock()
_STATES: dict[str, _ProofHeadLockState] = {}


def goal_proof_head_lock_path(entrypoint_ledger_path: str | Path) -> Path:
    ledger = Path(entrypoint_ledger_path).expanduser().absolute()
    return ledger.with_name(f".{ledger.name}.proof-head.lock")


def _state_for(path: Path) -> _ProofHeadLockState:
    key = str(path)
    with _STATE_GUARD:
        state = _STATES.get(key)
        if state is None:
            state = _ProofHeadLockState()
            _STATES[key] = state
        return state


@contextmanager
def acquire_goal_proof_head_lock(
    entrypoint_ledger_path: str | Path,
    *,
    timeout_seconds: float = 30.0,
) -> Iterator[Path]:
    """Hold the shared proof-head lock, re-entrantly within one thread."""

    path = goal_proof_head_lock_path(entrypoint_ledger_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    state = _state_for(path)
    with state.process_lock:
        if state.depth == 0:
            fd = os.open(path, os.O_RDWR | os.O_CREAT, 0o600)
            try:
                os.chmod(path, 0o600)
                held = acquire_exclusive_fd(
                    fd,
                    timeout_seconds=timeout_seconds,
                )
            except Exception:
                os.close(fd)
                raise
            state.fd = fd
            state.held = held
        state.depth += 1
        try:
            yield path
        finally:
            state.depth -= 1
            if state.depth == 0:
                held = state.held
                fd = state.fd
                state.held = None
                state.fd = None
                try:
                    if held is not None:
                        held.release()
                finally:
                    if fd is not None:
                        os.close(fd)


__all__ = [
    "acquire_goal_proof_head_lock",
    "goal_proof_head_lock_path",
]
