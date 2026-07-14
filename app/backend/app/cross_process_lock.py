"""Small cross-platform backend for exclusive advisory file locks."""

from __future__ import annotations

import errno
import math
import os
import time
from typing import Any

try:  # pragma: no branch - exactly one backend normally exists per platform.
    import fcntl as _FCNTL  # type: ignore[import-not-found]
except ImportError:  # pragma: no cover - exercised by simulated/Windows tests.
    _FCNTL = None

try:
    import msvcrt as _MSVCRT  # type: ignore[import-not-found]
except ImportError:  # pragma: no cover - normal on POSIX.
    _MSVCRT = None


class CrossProcessLockError(RuntimeError):
    """A cross-process file lock could not be used safely."""


class CrossProcessLockUnavailable(CrossProcessLockError):
    """Neither the POSIX nor Windows lock backend is available."""


class CrossProcessLockTimeout(TimeoutError):
    """The exclusive file lock remained contended through its deadline."""


def _is_contention(error: OSError) -> bool:
    return error.errno in {errno.EACCES, errno.EAGAIN}


def _seed_lock_byte(fd: int) -> None:
    if os.fstat(fd).st_size > 0:
        return
    os.lseek(fd, 0, os.SEEK_SET)
    written = os.write(fd, b"\0")
    if written != 1:
        raise CrossProcessLockError("cross-process lock byte could not be initialized")
    os.fsync(fd)


class HeldExclusiveFileLock:
    """Idempotent OS-lock handle; the caller continues to own the fd."""

    __slots__ = ("_backend", "_fd", "_is_posix", "_released")

    def __init__(self, fd: int, backend: Any, *, is_posix: bool) -> None:
        self._fd = fd
        self._backend = backend
        self._is_posix = is_posix
        self._released = False

    def release(self) -> None:
        if self._released:
            return
        self._released = True
        if self._is_posix:
            self._backend.flock(self._fd, self._backend.LOCK_UN)
            return
        os.lseek(self._fd, 0, os.SEEK_SET)
        self._backend.locking(self._fd, self._backend.LK_UNLCK, 1)


def acquire_exclusive_fd(
    fd: int,
    *,
    timeout_seconds: float | None,
    poll_seconds: float = 0.01,
) -> HeldExclusiveFileLock:
    """Acquire an exclusive byte-zero lock without hiding the caller's deadline."""

    if type(fd) is not int or fd < 0:
        raise ValueError("cross-process lock fd must be a non-negative exact integer")
    if timeout_seconds is not None:
        timeout = float(timeout_seconds)
        if not math.isfinite(timeout) or timeout < 0:
            raise ValueError("cross-process lock timeout must be finite and non-negative")
    else:
        timeout = None
    poll = float(poll_seconds)
    if not math.isfinite(poll) or poll <= 0:
        raise ValueError("cross-process lock poll interval must be positive and finite")

    backend = _FCNTL if _FCNTL is not None else _MSVCRT
    if backend is None:
        raise CrossProcessLockUnavailable(
            "no supported cross-process file-lock backend is available"
        )
    _seed_lock_byte(fd)
    deadline = None if timeout is None else time.monotonic() + timeout
    while True:
        try:
            if backend is _FCNTL:
                backend.flock(fd, backend.LOCK_EX | backend.LOCK_NB)
            else:
                os.lseek(fd, 0, os.SEEK_SET)
                backend.locking(fd, backend.LK_NBLCK, 1)
            return HeldExclusiveFileLock(fd, backend, is_posix=backend is _FCNTL)
        except OSError as exc:
            if not _is_contention(exc):
                raise
            now = time.monotonic()
            if deadline is not None and now >= deadline:
                raise CrossProcessLockTimeout(
                    "cross-process file-lock acquisition timed out"
                ) from exc
            delay = poll if deadline is None else min(poll, max(deadline - now, 0.0))
            time.sleep(delay)


__all__ = [
    "CrossProcessLockError",
    "CrossProcessLockTimeout",
    "CrossProcessLockUnavailable",
    "HeldExclusiveFileLock",
    "acquire_exclusive_fd",
]
