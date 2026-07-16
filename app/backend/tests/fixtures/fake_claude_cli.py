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

    emit({"type": "system", "subtype": "init", "session_id": "fake-session", "model": "fake"})

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
