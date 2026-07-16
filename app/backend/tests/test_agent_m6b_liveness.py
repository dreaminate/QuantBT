"""M6b liveness — timeout + cancel guards on ClaudeBackend.run / SessionOrchestrator.

Extends the M4b spawn/parse proof (``test_agent_claude_stream_parser``) with the M6b
liveness contract: while the caller keeps consuming, a spawned claude cannot hang the
turn (IDLE + TOTAL timeout + bounded post-EOF wait), an abnormal EOF is surfaced as an
honest error, and a client cancel deterministically kills the child (explicit generator
close, not GC/refcount timing). A fully-stopped consumer (HTTP disconnect without a
close) is a documented residual — see SessionOrchestrator.stream_events. Design =
cross-vendor duet (deep-opus ‖ codex) plus main-agent adjudication.

pytest-timeout is NOT installed, so every "does it hang?" probe SELF-BOUNDS in a
worker thread with a bounded ``join`` — a regression fails an assertion instead of
hanging the whole suite (project norm: 必带 timeout 兜底).

Mutation contract (RULES §2 种坏门必抓):
- Delete the idle/total deadline in ``run()`` → the hang probe's worker never returns
  → its bounded-join assertion goes RED (does not hang the suite).
- Revert SessionOrchestrator's ``finally: raw.close()`` to the GC-cascade → the cancel
  probe (backend retains its own generator ref, defeating the refcount cascade, then a
  full ``gc.collect()``) leaves ``proc.kill`` unfired → RED.
"""

from __future__ import annotations

import gc
import os
import stat
import threading
import time
from pathlib import Path
from typing import Any, Iterator

import pytest

from app.agent.backends.base import BackendReadiness
from app.agent.backends.claude_backend import (
    ClaudeBackend,
    parse_claude_stream_json_lines,
)
from app.agent.backends.events import (
    AssistantText,
    BackendError,
    BackendEvent,
    Done,
    SessionStarted,
)
from app.agent.session_orchestrator import SessionOrchestrator

FIXTURES = Path(__file__).resolve().parent / "fixtures"
STUB_CLI = FIXTURES / "fake_claude_cli.py"


@pytest.fixture
def stub_cli() -> str:
    STUB_CLI.chmod(STUB_CLI.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
    return str(STUB_CLI)


def _backend(stub: str, tmp_path: Path, *, idle: float, total: float) -> ClaudeBackend:
    return ClaudeBackend(
        model="claude-test",
        workspace_dir=tmp_path / "ws",
        data_root=tmp_path / "data",
        backend_root=tmp_path / "backend",
        canvas_token="canvas-tok",
        cli_path=stub,
        idle_timeout_s=idle,
        total_timeout_s=total,
    )


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _drain_in_worker(gen: Iterator[BackendEvent], bound_s: float = 5.0):
    """Consume a run() generator on a worker thread with a bounded join.

    Returns (thread, collected_events, exceptions). The caller asserts the thread
    finished — a broken timeout fails that assertion instead of hanging the suite.
    """

    out: list[BackendEvent] = []
    err: list[BaseException] = []

    def _work() -> None:
        try:
            for ev in gen:
                out.append(ev)
        except BaseException as exc:  # noqa: BLE001 — surface, don't swallow
            err.append(exc)

    t = threading.Thread(target=_work, daemon=True)
    t.start()
    t.join(timeout=bound_s)
    return t, out, err


# --- B4 additive: mcp_servers surfaced from the init line -------------------


def test_parser_surfaces_mcp_servers_dict_shape():
    line = (
        '{"type":"system","subtype":"init","session_id":"s",'
        '"mcp_servers":[{"name":"quantbt-agent-canvas","status":"connected"}]}'
    )
    events = list(parse_claude_stream_json_lines([line]))
    assert isinstance(events[0], SessionStarted)
    assert events[0].mcp_servers == ("quantbt-agent-canvas",)


def test_parser_surfaces_mcp_servers_bare_string_shape():
    # Defensive on the UNVERIFIED shape — a bare list of name strings normalizes too.
    line = '{"type":"system","subtype":"init","session_id":"s","mcp_servers":["quantbt-agent-canvas"]}'
    events = list(parse_claude_stream_json_lines([line]))
    assert events[0].mcp_servers == ("quantbt-agent-canvas",)


def test_parser_mcp_servers_absent_or_malformed_is_empty_tuple():
    for line in (
        '{"type":"system","subtype":"init","session_id":"s"}',
        '{"type":"system","subtype":"init","session_id":"s","mcp_servers":"nope"}',
        '{"type":"system","subtype":"init","session_id":"s","mcp_servers":[{"no_name":1}]}',
    ):
        events = list(parse_claude_stream_json_lines([line]))
        assert isinstance(events[0], SessionStarted)
        assert events[0].mcp_servers == ()


# --- A1 timeout probes ------------------------------------------------------


def test_hang_is_idle_timed_out(stub_cli, tmp_path):
    """init then silence → IDLE timeout kills the child + honest BackendError.

    THE mutation test for A1: delete the deadline and this worker never returns →
    the bounded-join assertion goes RED (instead of hanging the suite).
    """

    backend = _backend(stub_cli, tmp_path, idle=0.5, total=30.0)
    started = time.monotonic()
    # Very generous self-bound (18s) absorbs heavy-CI spawn/join contention (the
    # finally may join two threads at up to 5s each). A real "idle never fires"
    # regression still fails here (the worker would run to the 30s total, past 18s).
    t, out, err = _drain_in_worker(
        backend.run(prompt="FAKE_CLAUDE_MODE=hang\n", owner="alice"), bound_s=18.0
    )
    elapsed = time.monotonic() - started
    kinds = [type(e).__name__ for e in out]
    msgs = [getattr(e, "message", "") for e in out]
    assert not t.is_alive(), f"run() did not terminate — idle timeout regressed; out={kinds}"
    assert not err, f"unexpected exception: {err}"
    assert out and isinstance(out[0], SessionStarted), f"out={kinds}"
    errs = [e for e in out if isinstance(e, BackendError)]
    assert errs, f"no idle-timeout BackendError produced; out={kinds} msgs={msgs}"
    assert "timed out" in errs[-1].message and "no output" in errs[-1].message
    assert elapsed < 16.0  # fired on the ~0.5s idle bound (+load slack), not the 30s total


def test_total_backstop_times_out_a_slow_drip(stub_cli, tmp_path):
    """A drip that never idles but never ends is cut by the TOTAL wall-clock backstop.

    idle=10s is far larger than any drip gap (so idle can NEVER fire, even under heavy
    CPU load that stretches the stub's sleeps), while total=1s is a WALL-CLOCK deadline
    that fires reliably regardless of load. Pins that idle-alone is insufficient
    (slow-drip liveness attack) without a load-sensitive idle-vs-drip margin.
    """

    backend = _backend(stub_cli, tmp_path, idle=10.0, total=1.0)
    t, out, err = _drain_in_worker(
        backend.run(prompt="FAKE_CLAUDE_MODE=drip:0.05:400\nhi", owner="alice"), bound_s=8.0
    )
    assert not t.is_alive(), "run() did not terminate — total backstop regressed"
    assert not err
    assert isinstance(out[-1], BackendError)
    assert "wall-clock" in out[-1].message


def test_child_that_eofs_stdout_but_lingers_does_not_hang(stub_cli, tmp_path):
    """A child that closes stdout (EOF) but stays ALIVE must NOT hang the turn on the
    post-EOF wait: it is bounded by ``eof_grace_s``, then the finally reaps the child.
    Remove that wait timeout → the worker never returns → bounded-join RED. R3 finding.
    """

    backend = ClaudeBackend(
        model="claude-test",
        workspace_dir=tmp_path / "ws",
        data_root=tmp_path / "data",
        backend_root=tmp_path / "backend",
        canvas_token="tok",
        cli_path=stub_cli,
        idle_timeout_s=30.0,
        total_timeout_s=60.0,
        eof_grace_s=0.5,
    )
    t, out, err = _drain_in_worker(
        backend.run(prompt="FAKE_CLAUDE_MODE=eof_linger\nhi", owner="alice"), bound_s=10.0
    )
    assert not t.is_alive(), "run() hung on the post-EOF proc.wait (lingering child)"
    assert not err
    assert any(isinstance(e, Done) for e in out)  # full output consumed (result:success)
    assert not any(isinstance(e, BackendError) for e in out)  # EOF'd-but-alive is not an error


def test_child_that_eofs_with_no_terminal_is_an_honest_error(stub_cli, tmp_path):
    """EOF'd stdout + lingering + NO terminal event = an ABNORMAL end → honest
    BackendError, NOT a silent stream_ended. Cross-vendor R4 finding: the post-EOF
    ``returncode=None`` path was masking an abnormal end as a normal completion.
    Revert the ``if not saw_terminal`` error branch → the run yields no error and the
    orchestrator emits stream_ended → RED.
    """

    backend = ClaudeBackend(
        model="claude-test",
        workspace_dir=tmp_path / "ws",
        data_root=tmp_path / "data",
        backend_root=tmp_path / "backend",
        canvas_token="tok",
        cli_path=stub_cli,
        idle_timeout_s=30.0,
        total_timeout_s=60.0,
        eof_grace_s=0.5,
    )
    t, out, err = _drain_in_worker(
        backend.run(prompt="FAKE_CLAUDE_MODE=eof_no_terminal\nhi", owner="alice"), bound_s=10.0
    )
    assert not t.is_alive(), "run() hung"
    assert not err
    assert isinstance(out[0], SessionStarted)
    assert isinstance(out[-1], BackendError)  # abnormal end is surfaced honestly
    assert "no terminal" in out[-1].message and "did not exit" in out[-1].message


def test_slow_but_alive_stream_is_not_timed_out(stub_cli, tmp_path):
    """A productive drip (line every ~0.1s, idle=5s ≫ any load-stretched gap) must NOT
    idle-timeout — reaches Done. Wide idle margin so CPU load can't false-trip it."""

    backend = _backend(stub_cli, tmp_path, idle=5.0, total=30.0)
    t, out, err = _drain_in_worker(
        backend.run(prompt="FAKE_CLAUDE_MODE=drip:0.1:6\nhi", owner="alice"), bound_s=10.0
    )
    assert not t.is_alive() and not err
    assert isinstance(out[0], SessionStarted)
    assert isinstance(out[-1], Done)
    assert not any(isinstance(e, BackendError) for e in out)
    assert sum(isinstance(e, AssistantText) for e in out) == 6


def test_slow_consumer_does_not_trip_idle_timeout(stub_cli, tmp_path):
    """A slow CONSUMER (pauses > idle between pulls) must NOT idle-timeout.

    Proves the reader-thread decoupling: the reader drains all lines into the queue,
    so a get() after a long consumer pause returns a buffered line at once and the
    idle clock (which runs only inside get()) never counts consumer time. Delete the
    reader thread (read on the generator's own thread) → this goes RED.
    """

    backend = _backend(stub_cli, tmp_path, idle=0.3, total=30.0)
    out: list[BackendEvent] = []
    # Default 'success' mode emits 5 events then exits fast; we pull slowly.
    for ev in backend.run(prompt="SECRET_PROMPT_MARKER hi", owner="alice"):
        out.append(ev)
        time.sleep(0.5)  # > idle between pulls
    assert isinstance(out[0], SessionStarted)
    assert isinstance(out[-1], Done)
    assert not any(isinstance(e, BackendError) for e in out)


def test_full_queue_at_eof_delivers_sentinel_not_spurious_timeout(stub_cli, tmp_path):
    """Fast producer + slow consumer + TINY queue → the queue is full at child-exit.

    The EOF sentinel must still be delivered (blocking put), so a NORMAL completion is
    a Done — NOT a spurious idle timeout after the backlog drains. Cross-vendor floor
    finding (codex). Revert the reader's blocking sentinel put to ``put_nowait`` → the
    sentinel is dropped → a trailing idle BackendError appears → RED.
    """

    backend = ClaudeBackend(
        model="claude-test",
        workspace_dir=tmp_path / "ws",
        data_root=tmp_path / "data",
        backend_root=tmp_path / "backend",
        canvas_token="tok",
        cli_path=stub_cli,
        idle_timeout_s=3.0,  # wide margin: this test is about EOF delivery, not idle timing
        total_timeout_s=30.0,
        queue_maxsize=1,  # force the queue-full-at-EOF path
    )
    out: list[BackendEvent] = []
    for ev in backend.run(prompt="FAKE_CLAUDE_MODE=drip:0:10\nhi", owner="alice"):
        out.append(ev)
        time.sleep(0.15)  # slow consumer keeps the size-1 queue full
    assert isinstance(out[-1], Done), f"expected clean Done, got {out[-1]!r}"
    assert not any(isinstance(e, BackendError) for e in out), "spurious timeout after a normal EOF"
    assert sum(isinstance(e, AssistantText) for e in out) == 10  # no lines lost


# --- A2 cancel --------------------------------------------------------------


class _CancelSpyBackend:
    """Backend whose run() generator sets ``killed`` in its ``finally`` (stands in for
    ``proc.kill``) and — crucially — RETAINS its own generator ref, so the refcount
    cascade cannot close it. Only an EXPLICIT ``close()`` reaches the finally."""

    def __init__(self) -> None:
        self.killed = threading.Event()
        self._gen: Iterator[BackendEvent] | None = None

    def preflight(self) -> BackendReadiness:
        return BackendReadiness(
            provider="test", cli="stub", cli_installed=True, authed=True, ready=True, detail=""
        )

    def run(self, *, prompt: str, owner: str, **kwargs: Any) -> Iterator[BackendEvent]:
        self._gen = self._run_impl()  # backend retains the ref → defeats GC/refcount close
        return self._gen

    def _run_impl(self) -> Iterator[BackendEvent]:
        try:
            i = 0
            while True:
                yield SessionStarted(session_id="s") if i == 0 else AssistantText(text=f"t{i}")
                i += 1
        finally:
            self.killed.set()


def test_cancel_deterministically_kills_via_explicit_close():
    """Closing the orchestrator stream must fire the backend's cleanup — NOT via GC.

    The spy retains its own generator ref and we force a full ``gc.collect()`` before
    asserting, so ONLY the orchestrator's explicit ``raw.close()`` can set ``killed``.
    Revert that finally → ``killed`` stays clear → RED.
    """

    backend = _CancelSpyBackend()
    orch = SessionOrchestrator()
    gen = orch.stream_events(backend=backend, owner="alice", prompt="hi")
    assert next(gen)["event"] == "say"  # session started → child "running"
    assert next(gen)["event"] == "say"  # streaming
    assert not backend.killed.is_set()
    gen.close()  # client disconnect
    gc.collect()  # adversarial: a full GC must NOT be what kills it
    assert backend.killed.is_set(), (
        "cancel did not fire backend cleanup — SessionOrchestrator.stream_events must "
        "explicitly close the backend generator in finally (not rely on GC/refcount)"
    )


def test_cancel_reaps_real_spawned_child(stub_cli, tmp_path):
    """End-to-end: cancel a real spawned (hanging) child via the orchestrator → reaped.

    Long timeouts so CANCEL, not the timeout, ends it. Uses a pidfile the stub writes,
    and self-bounds ``close()`` in a worker so a cleanup deadlock fails (not hangs).
    """

    pidfile = tmp_path / "child.pid"
    backend = _backend(stub_cli, tmp_path, idle=30.0, total=60.0)
    orch = SessionOrchestrator()
    gen = orch.stream_events(backend=backend, owner="alice", prompt=f"FAKE_CLAUDE_MODE=hang\n{pidfile}")
    assert next(gen)["event"] == "say"  # init → child spawned, now hanging
    for _ in range(60):
        if pidfile.exists():
            break
        time.sleep(0.05)
    pid = int(pidfile.read_text())
    assert _pid_alive(pid)

    closer = threading.Thread(target=gen.close, daemon=True)
    closer.start()
    closer.join(timeout=5)
    assert not closer.is_alive(), "gen.close() hung — cancel cleanup deadlocked"

    for _ in range(60):
        if not _pid_alive(pid):
            break
        time.sleep(0.05)
    assert not _pid_alive(pid), "spawned child survived cancel"


class _EagerRaiseBackend:
    """A backend whose ``run()`` raises at CALL time (eager, not a lazy generator)."""

    def preflight(self) -> BackendReadiness:
        return BackendReadiness(
            provider="test", cli="stub", cli_installed=True, authed=True, ready=True, detail=""
        )

    def run(self, *, prompt: str, owner: str, **kwargs: Any):
        raise RuntimeError("sync-run-boom")


class _CloseRaisesBackend:
    """A backend whose generator yields a terminal Done, then RAISES in its finally
    (i.e. ``close()`` raises) — models a cleanup error that must not leak."""

    def preflight(self) -> BackendReadiness:
        return BackendReadiness(
            provider="test", cli="stub", cli_installed=True, authed=True, ready=True, detail=""
        )

    def run(self, *, prompt: str, owner: str, **kwargs: Any) -> Iterator[BackendEvent]:
        def _gen() -> Iterator[BackendEvent]:
            try:
                yield SessionStarted(session_id="s")
                yield Done(reason="success")
            finally:
                raise RuntimeError("close-boom")

        return _gen()


def test_eager_backend_run_raise_becomes_honest_error_not_uncaught():
    """An EAGER backend.run() that raises at call time → honest error+done frame,
    never an uncaught crash to the transport. Move ``raw = backend.run()`` back
    outside the try → RED (RuntimeError escapes list())."""

    frames = list(SessionOrchestrator().stream_events(backend=_EagerRaiseBackend(), owner="a", prompt="hi"))
    names = [f["event"] for f in frames]
    assert names[-1] == "done"
    assert any(f["event"] == "error" for f in frames)
    assert any("sync-run-boom" in str(f["data"]) for f in frames if f["event"] == "error")


def test_close_exception_does_not_leak_after_terminal_done():
    """If the backend's cleanup (``close()``) raises after a terminal Done, the error
    must NOT propagate to the transport. Remove the best-effort try/except around
    ``close()`` → RED (RuntimeError('close-boom') escapes list())."""

    frames = list(SessionOrchestrator().stream_events(backend=_CloseRaisesBackend(), owner="a", prompt="hi"))
    names = [f["event"] for f in frames]
    assert names[-1] == "done"
    assert not any(f["event"] == "error" for f in frames)  # no spurious error from cleanup
