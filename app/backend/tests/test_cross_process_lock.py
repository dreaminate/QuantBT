from __future__ import annotations

import builtins
import errno
import importlib.util
import os
from pathlib import Path

import pytest

from app import cross_process_lock


def test_module_imports_and_fails_closed_without_lock_backend(
    monkeypatch,
    tmp_path: Path,
) -> None:
    original_import = builtins.__import__

    def without_lock_backends(name, *args, **kwargs):
        if name in {"fcntl", "msvcrt"}:
            raise ImportError(f"simulated missing {name}")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", without_lock_backends)
    spec = importlib.util.spec_from_file_location(
        "isolated_cross_process_lock",
        Path(cross_process_lock.__file__),
    )
    assert spec is not None and spec.loader is not None
    isolated = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(isolated)
    fd = os.open(tmp_path / "unavailable.lock", os.O_RDWR | os.O_CREAT, 0o600)
    try:
        with pytest.raises(
            isolated.CrossProcessLockUnavailable,
            match="no supported",
        ):
            isolated.acquire_exclusive_fd(fd, timeout_seconds=0)
    finally:
        os.close(fd)


def test_fake_msvcrt_locks_byte_zero_and_seeds_empty_file(
    monkeypatch,
    tmp_path: Path,
) -> None:
    calls: list[tuple[int, int, int]] = []

    class FakeMsvcrt:
        LK_NBLCK = 2
        LK_UNLCK = 3

        @staticmethod
        def locking(fd: int, mode: int, length: int) -> None:
            calls.append((mode, os.lseek(fd, 0, os.SEEK_CUR), os.fstat(fd).st_size))
            assert length == 1

    monkeypatch.setattr(cross_process_lock, "_FCNTL", None)
    monkeypatch.setattr(cross_process_lock, "_MSVCRT", FakeMsvcrt)
    fd = os.open(tmp_path / "windows.lock", os.O_RDWR | os.O_CREAT, 0o600)
    try:
        held = cross_process_lock.acquire_exclusive_fd(fd, timeout_seconds=0.1)
        held.release()
    finally:
        os.close(fd)

    assert calls == [
        (FakeMsvcrt.LK_NBLCK, 0, 1),
        (FakeMsvcrt.LK_UNLCK, 0, 1),
    ]


def test_fake_msvcrt_contention_obeys_exact_deadline(
    monkeypatch,
    tmp_path: Path,
) -> None:
    calls = 0
    clock = [100.0]

    class FakeMsvcrt:
        LK_NBLCK = 2
        LK_UNLCK = 3

        @staticmethod
        def locking(_fd: int, mode: int, _length: int) -> None:
            nonlocal calls
            calls += 1
            assert mode == FakeMsvcrt.LK_NBLCK
            raise OSError(errno.EACCES, "contended")

    monkeypatch.setattr(cross_process_lock, "_FCNTL", None)
    monkeypatch.setattr(cross_process_lock, "_MSVCRT", FakeMsvcrt)
    monkeypatch.setattr(cross_process_lock.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(
        cross_process_lock.time,
        "sleep",
        lambda seconds: clock.__setitem__(0, clock[0] + seconds),
    )
    fd = os.open(tmp_path / "contended.lock", os.O_RDWR | os.O_CREAT, 0o600)
    try:
        with pytest.raises(cross_process_lock.CrossProcessLockTimeout):
            cross_process_lock.acquire_exclusive_fd(
                fd,
                timeout_seconds=0.025,
                poll_seconds=0.01,
            )
    finally:
        os.close(fd)

    assert clock[0] == pytest.approx(100.025)
    assert calls == 4


def test_fake_msvcrt_fatal_error_is_not_retried(
    monkeypatch,
    tmp_path: Path,
) -> None:
    calls = 0

    class FakeMsvcrt:
        LK_NBLCK = 2
        LK_UNLCK = 3

        @staticmethod
        def locking(_fd: int, _mode: int, _length: int) -> None:
            nonlocal calls
            calls += 1
            raise OSError(errno.EBADF, "bad fd")

    monkeypatch.setattr(cross_process_lock, "_FCNTL", None)
    monkeypatch.setattr(cross_process_lock, "_MSVCRT", FakeMsvcrt)
    fd = os.open(tmp_path / "fatal.lock", os.O_RDWR | os.O_CREAT, 0o600)
    try:
        with pytest.raises(OSError) as caught:
            cross_process_lock.acquire_exclusive_fd(fd, timeout_seconds=5)
    finally:
        os.close(fd)

    assert caught.value.errno == errno.EBADF
    assert calls == 1


@pytest.mark.parametrize("contention_errno", [errno.EACCES, errno.EAGAIN])
def test_fake_posix_retries_only_contention_then_unlocks(
    monkeypatch,
    tmp_path: Path,
    contention_errno: int,
) -> None:
    calls: list[int] = []

    class FakeFcntl:
        LOCK_EX = 1
        LOCK_NB = 2
        LOCK_UN = 4

        @staticmethod
        def flock(_fd: int, operation: int) -> None:
            calls.append(operation)
            if len(calls) == 1:
                raise OSError(contention_errno, "contended")

    monkeypatch.setattr(cross_process_lock, "_FCNTL", FakeFcntl)
    monkeypatch.setattr(cross_process_lock, "_MSVCRT", None)
    monkeypatch.setattr(cross_process_lock.time, "sleep", lambda _seconds: None)
    fd = os.open(tmp_path / "posix.lock", os.O_RDWR | os.O_CREAT, 0o600)
    try:
        held = cross_process_lock.acquire_exclusive_fd(fd, timeout_seconds=1)
        held.release()
    finally:
        os.close(fd)

    assert calls == [
        FakeFcntl.LOCK_EX | FakeFcntl.LOCK_NB,
        FakeFcntl.LOCK_EX | FakeFcntl.LOCK_NB,
        FakeFcntl.LOCK_UN,
    ]
