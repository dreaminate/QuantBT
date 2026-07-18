#!/usr/bin/env python3
"""Stub claude CLI for ClaudeBackend.run() tests — emits canned stream-json.

Exercises the REAL spawn/stdin/stdout/parse wiring (and the L-C spawn env) without
a live claude subscription. The MODE is read from the FIRST LINE of the STDIN prompt
(``FAKE_CLAUDE_MODE=<mode>\\n``) — NOT from an env var, because the L-C spawn-env
allowlist deliberately strips any non-allowlisted variable, so an env-based knob
would never reach this process (that stripping is exactly the red-line we want).
Modes:
- ``success`` (default): init → assistant text (reporting what it saw) → tool_use →
  tool_result → result/success, exit 0.
- ``error``: init → result with is_error=True, exit 0.
- ``crash``: init only, then exit 3 (NO terminal event) — tests the honest
  "exited N without terminal → BackendError" path.

The prompt MUST arrive on stdin (argv must NOT carry it — argv-injection floor). The
stub reports, in an assistant text block, the prompt it read from stdin plus whether
forbidden/expected env vars are visible — so the test can assert L-C from the parsed
events (master key absent, QB_OWNER present, prompt-not-in-argv).
"""

import json
import os
import sys


def emit(obj):
    sys.stdout.write(json.dumps(obj, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def main() -> int:
    prompt = sys.stdin.read()
    mode = "success"
    # Mode is carried on the first stdin line so it survives the L-C env allowlist.
    if prompt.startswith("FAKE_CLAUDE_MODE="):
        first, _, rest = prompt.partition("\n")
        mode = first.split("=", 1)[1].strip()
        prompt = rest

    # slow_start:<delay_s> — sleep BEFORE the first line, i.e. a slow-but-healthy spawn
    # (cold start / slow auth). Every other mode emits init first, so this is the only
    # mode that exercises the STARTUP budget as distinct from the IDLE budget. Must be
    # checked before the init emit below — that is the whole point of the mode.
    if mode.startswith("slow_start:"):
        import time as _t

        _t.sleep(float(mode.split(":", 1)[1]))
        mode = "success"

    emit({"type": "system", "subtype": "init", "session_id": "fake-session", "model": "fake",
          "mcp_servers": [{"name": "quantbt-agent-canvas", "status": "connected"}]})

    # M6b timeout probes (mode carried on the stdin line, surviving the L-C allowlist):
    if mode == "hang":
        # init then silence forever → ClaudeBackend's IDLE timeout must kill us. The
        # test self-bounds (worker thread + bounded join) since pytest-timeout is absent.
        # If the (post-mode) prompt body is a path, write our PID there first so a
        # cancel test can assert the REAL spawned child was reaped.
        import time as _t
        pidfile = prompt.strip()
        if pidfile:
            try:
                with open(pidfile, "w") as fh:
                    fh.write(str(os.getpid()))
            except OSError:
                pass
        _t.sleep(3600)
        return 0
    if mode.startswith("drip"):
        # drip:<interval_s>:<count> — a slow but ALIVE stream: <count> assistant-text
        # lines <interval_s> apart, then result/success. Each line resets the idle
        # clock, so a long productive turn must NOT be idle-timed-out.
        import time as _t
        parts = mode.split(":")
        interval = float(parts[1]) if len(parts) > 1 and parts[1] else 0.05
        count = int(parts[2]) if len(parts) > 2 and parts[2] else 5
        for i in range(count):
            _t.sleep(interval)
            emit({"type": "assistant", "message": {"role": "assistant",
                  "content": [{"type": "text", "text": f"drip {i}"}]}})
        emit({"type": "result", "subtype": "success", "is_error": False,
              "result": "done", "session_id": "fake-session"})
        return 0

    if mode == "eof_linger":
        # Emit a normal success stream, then CLOSE stdout at the OS level (fd 1 → the
        # parent's read end sees EOF) but STAY ALIVE — the backend's post-EOF proc.wait
        # must be bounded (eof_grace_s) so a lingering child cannot hang the turn; the
        # finally then reaps us.
        import time as _t
        emit({"type": "result", "subtype": "success", "is_error": False,
              "result": "done", "session_id": "fake-session"})
        sys.stdout.flush()
        os.close(1)  # close the real pipe write-end fd → parent read end EOFs
        _t.sleep(3600)
        return 0

    if mode == "eof_no_terminal":
        # init only (already emitted), NO terminal result — then close stdout at the OS
        # level and STAY ALIVE. An EOF'd-but-alive child with no terminal event is an
        # ABNORMAL end that must surface as an honest BackendError, not a silent
        # stream_ended (cross-vendor R4 finding).
        import time as _t
        sys.stdout.flush()
        os.close(1)
        _t.sleep(3600)
        return 0

    if mode == "crash":
        return 3  # no terminal event emitted → ClaudeBackend must synthesize BackendError

    if mode == "error":
        emit({"type": "result", "subtype": "error_during_execution", "is_error": True,
              "result": "boom", "session_id": "fake-session"})
        return 0

    # success: report what the stub actually saw (proves stdin prompt + L-C env)
    report = {
        "got_prompt": prompt,
        "prompt_in_argv": any("SECRET_PROMPT_MARKER" in a for a in sys.argv),
        "has_master_key": "QUANTBT_MASTER_KEY" in os.environ,
        "has_binance_secret": "BINANCE_API_SECRET" in os.environ,
        "qb_owner": os.environ.get("QB_OWNER", ""),
    }
    emit({"type": "assistant", "message": {"role": "assistant", "content": [
        {"type": "thinking", "thinking": "internal", "signature": "s"},
        {"type": "text", "text": json.dumps(report, ensure_ascii=False)},
    ]}})
    emit({"type": "assistant", "message": {"role": "assistant", "content": [
        {"type": "tool_use", "id": "toolu_fake1", "name": "canvas_read", "input": {"owner": "x"}},
    ]}})
    emit({"type": "user", "message": {"role": "user", "content": [
        {"type": "tool_result", "tool_use_id": "toolu_fake1", "content": "{\"nodes\": [], \"count\": 0}"},
    ]}})
    emit({"type": "result", "subtype": "success", "is_error": False,
          "result": "done", "session_id": "fake-session"})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
