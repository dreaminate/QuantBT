"""Claude Code headless backend — spawn contract builders (agent M3).

Pure builders (no subprocess is spawned here; M4 does the spawning). Three pieces:

- ``build_agent_argv`` — the claude v2.1.210 headless argv. Always pins
  ``--strict-mcp-config`` (agent sees ONLY our no-key MCP server, never an
  ambient one with venue tools) and always allows the canvas MCP tool.
- ``build_spawn_env`` — **the L-C red-line**. The agent's environment is an
  explicit minimal ALLOWLIST; ``QUANTBT_MASTER_KEY`` and venue/keystore secrets
  never appear, even when they are in the parent environment. This is the fix for
  the ``env=os.environ.copy()`` leak (subscription_cli_llm.py:197/303) that would
  otherwise hand the keystore master key to an agent that can open a Bash shell.
- ``build_mcp_config`` — the ``.mcp.json`` launching the no-key server, whose own
  subprocess env is likewise minimal (no master key).

Red-line floor (dev/research/findings/dreaminate/claude-code-agent-impl-plan-duet-20260716.md §3):
L-C holds because the spawn env is built by allowlist, so no secret we hold is
handed to the agent. What the agent can still reach via the user's own HOME is the
user's own ambient risk (documented, per 放权), NOT a secret we handed over.
"""

from __future__ import annotations

import json
import os
import shutil
from pathlib import Path
from typing import Any, Iterable, Iterator, Mapping

from .base import BackendReadiness, PermissionTier
from .events import (
    AssistantText,
    BackendError,
    BackendEvent,
    Done,
    SessionStarted,
    ToolCall,
    ToolResult,
)

# The no-key MCP server (M1). Server name must match app.agent_mcp.server's
# ``Server("quantbt-agent-canvas")`` so the tool id resolves.
MCP_SERVER_NAME = "quantbt-agent-canvas"
CANVAS_READ_TOOL = f"mcp__{MCP_SERVER_NAME}__canvas_read"
CANVAS_CREATE_NODE_TOOL = f"mcp__{MCP_SERVER_NAME}__canvas_create_node"
# The two canvas MCP tools the agent may auto-use. Both are pre-approved in
# --allowed-tools so a headless (-p) turn can actually create a node — the M5b
# write tool would otherwise hit an unanswerable permission prompt at the default
# tier. Auto-approving canvas_create_node is safe: the store clamps every canvas
# create to an OFFLINE draft (L-D), owner==QB_OWNER, no live/venue reach.
_CANVAS_MCP_TOOLS = (CANVAS_READ_TOOL, CANVAS_CREATE_NODE_TOOL)

# Operational env vars the CLI + its node runtime need to start. Copied from the
# parent env when present. SECRETS ARE DELIBERATELY ABSENT — the keystore master
# key and venue creds are excluded by construction (they are not on this list).
_SPAWN_ENV_ALLOWLIST: frozenset[str] = frozenset(
    {
        "PATH",
        "HOME",
        "USER",
        "LOGNAME",
        "SHELL",
        "TERM",
        "TMPDIR",
        "LANG",
        "LC_ALL",
        "LC_CTYPE",
        "TZ",
        "NVM_DIR",  # locate the nvm-managed node/claude install; not a code hook
        "XDG_CONFIG_HOME",
        "XDG_CACHE_HOME",
        "XDG_DATA_HOME",
    }
)
# NOT allowlisted (cross-vendor floor finding): NODE_OPTIONS / NODE_PATH are node
# code-injection surfaces (``--require <file>`` / module-path redirection). The
# bundled claude CLI does not need them, so we drop them to shrink the surface.

# Defense-in-depth: even if a future edit widens the allowlist, these keys are
# force-dropped from any spawn/MCP env. Substring match catches KEY/SECRET/TOKEN
# families; the explicit names cover our and common venue secrets.
_SPAWN_ENV_FORBIDDEN_EXACT: frozenset[str] = frozenset(
    {
        "QUANTBT_MASTER_KEY",
        "BINANCE_API_KEY",
        "BINANCE_API_SECRET",
        "OKX_API_KEY",
        "OKX_API_SECRET",
        "TUSHARE_TOKEN",
    }
)
_SPAWN_ENV_FORBIDDEN_SUBSTRINGS: tuple[str, ...] = (
    "MASTER_KEY",
    "API_SECRET",
    "PRIVATE_KEY",
    "SECRET_KEY",
)


def _is_forbidden(key: str) -> bool:
    up = key.upper()
    if up in _SPAWN_ENV_FORBIDDEN_EXACT:
        return True
    return any(sub in up for sub in _SPAWN_ENV_FORBIDDEN_SUBSTRINGS)


def _minimal_base_env(base_env: Mapping[str, str] | None) -> dict[str, str]:
    src = os.environ if base_env is None else base_env
    env = {k: src[k] for k in _SPAWN_ENV_ALLOWLIST if k in src and not _is_forbidden(k)}
    # Force-drop any forbidden key that somehow rode in on the allowlist.
    for key in list(env):
        if _is_forbidden(key):
            del env[key]
    return env


def build_spawn_env(
    *,
    owner: str,
    canvas_token: str,
    data_root: str | Path,
    base_env: Mapping[str, str] | None = None,
) -> dict[str, str]:
    """L-C red-line: the agent's environment, built by allowlist.

    Returns operational vars copied from ``base_env`` (defaults to ``os.environ``)
    PLUS the canvas-scoped identity vars. It NEVER contains ``QUANTBT_MASTER_KEY``
    or a venue/keystore secret, even if the parent env has them.

    ``canvas_token`` is a canvas-scope identifier only — it is not a KeyBroker
    CapabilityToken and cannot be redeemed for a venue key.
    """

    env = _minimal_base_env(base_env)
    env["QB_OWNER"] = str(owner)
    env["QB_CANVAS_TOKEN"] = str(canvas_token)
    env["BACKTEST_DATA_ROOT"] = str(data_root)
    return env


def build_mcp_config(
    *,
    data_root: str | Path,
    backend_root: str | Path,
    owner: str,
    canvas_token: str,
    python_executable: str = "python",
) -> dict[str, Any]:
    """The ``.mcp.json`` object launching the no-key canvas server over stdio.

    The MCP server's own subprocess env is minimal too — same allowlist, so the
    server process never carries the master key (belt for L-B: even if it could
    import keystore it holds no key to decrypt with).
    """

    server_env = build_spawn_env(owner=owner, canvas_token=canvas_token, data_root=data_root)
    server_env["PYTHONPATH"] = str(backend_root)
    server_env["QUANTBT_RUNTIME_MODE"] = "agent"
    return {
        "mcpServers": {
            MCP_SERVER_NAME: {
                "command": python_executable,
                "args": ["-m", "app.agent_mcp.server"],
                "env": server_env,
            }
        }
    }


def build_agent_argv(
    *,
    mcp_config_path: str | Path,
    workspace_dir: str | Path,
    model: str,
    tier: PermissionTier = PermissionTier.STANDARD,
    allowed_tools: tuple[str, ...] = (),
    cli_path: str = "claude",
) -> list[str]:
    """Build the headless claude argv. The PROMPT IS NOT HERE — pass it via stdin.

    Cross-vendor floor review proved (claude 2.1.210) that a prompt placed as a
    positional argv arg is parsed as flags: a prompt of ``--mcp-config=/evil.json``
    injects a malicious MCP server *despite* ``--strict-mcp-config`` (which uses
    every ``--mcp-config`` flag it sees). stdin has no such parsing surface, so the
    prompt goes to stdin at spawn time (see ``agent_prompt_via_stdin``).

    Always: ``--strict-mcp-config`` (only our MCP server) and the canvas MCP tool
    in ``--allowed-tools``. ``tier`` sets ``--permission-mode``; ``allowed_tools``
    adds CLI tools (Bash etc.) at the caller's chosen tier. Widening tier/tools
    cannot widen the MCP reach — that is fixed at the server.
    """

    # Guard the only remaining caller-controlled value that sits before a variadic
    # flag: a model that starts with "-" would be parsed as a flag. Reject it.
    if str(model).startswith("-"):
        raise ValueError(f"model must not start with '-' (argv-injection guard): {model!r}")

    # Defense-in-depth atop --strict-mcp-config: strip ANY foreign mcp__* tool a
    # caller passes. Only our TWO canvas MCP tools may be an mcp__ tool. So even if
    # --strict-mcp-config were ever bypassed, --allowed-tools alone cannot grant a
    # second MCP surface (e.g. a venue/order tool). Non-mcp CLI tools pass through.
    #
    # Claude re-splits --allowed-tools on comma OR space. So (a) split each element
    # on commas first (cleanly separates legit tools from a comma-smuggled one),
    # and (b) drop any resulting token that contains "mcp__" ANYWHERE unless it is
    # one of our two canvas tools — not just at the start. That catches every
    # smuggling separator: "Bash,mcp__evil__x" (comma) and "Bash mcp__evil__x"
    # (space, dropped whole) both die, while the canvas tools are the sole permitted
    # mcp tokens and paren specs like "Bash(git *)" (no "mcp__") pass through.
    # Cross-vendor floor finding (rounds 2-3); both canvas tools pre-approved so a
    # headless create-node turn is not blocked on an unanswerable permission prompt.
    tokens: list[str] = []
    for raw in allowed_tools:
        tokens.extend(part.strip() for part in str(raw).split(",") if part.strip())
    safe_extra = [t for t in tokens if t not in _CANVAS_MCP_TOOLS and "mcp__" not in t]
    tools = [*_CANVAS_MCP_TOOLS, *safe_extra]
    return [
        cli_path,
        "-p",
        "--output-format",
        "stream-json",
        "--verbose",
        "--model",
        str(model),
        "--mcp-config",
        str(mcp_config_path),
        "--strict-mcp-config",
        "--add-dir",
        str(workspace_dir),
        "--permission-mode",
        tier.value,
        "--allowed-tools",
        ",".join(tools),
    ]


def agent_prompt_via_stdin(prompt: str) -> str:
    """The prompt to feed the agent over STDIN (never argv — see build_agent_argv).

    Trivial today, but the single seam a spawner uses so no caller is tempted to
    put the prompt back on the command line.
    """

    return str(prompt)


def write_mcp_config(config: dict[str, Any], path: str | Path) -> Path:
    """Serialize an mcp-config dict to ``path`` (0600). Returns the path."""

    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")
    os.chmod(target, 0o600)
    return target


def _readiness_from_report(report: Mapping[str, Any]) -> BackendReadiness:
    """Map a provider_auth_report dict to CLI-backend readiness — honestly.

    This backend SPAWNS the claude CLI, which authenticates via its OWN keychain
    (subscription). It never passes the secrets.yaml API key to the agent. So a
    configured API key alone must NOT report ready — that is a false green the
    generic ``report["ready"]`` would give (cross-vendor floor finding). Readiness
    here requires the CLI installed AND CLI (subscription) auth.
    """

    cli_installed = bool(report.get("cli_installed"))
    cli_authed = bool(report.get("subscription_authed"))
    ready = cli_installed and cli_authed
    return BackendReadiness(
        provider="anthropic",
        cli=str(report.get("cli", "claude")),
        cli_installed=cli_installed,
        authed=cli_authed,
        ready=ready,
        detail=str(report.get("next_action", "")),
    )


def preflight(*, secrets_path: Path | None = None, timeout_s: float = 20.0) -> BackendReadiness:
    """Is the claude CLI installed and CLI-authed? Honest readiness, no fallback.

    Reuses ``subscription_cli_llm.provider_auth_report`` (provider=anthropic) but
    gates on CLI subscription auth, not an API key this backend doesn't use.
    """

    from app.agent.subscription_cli_llm import provider_auth_report

    report = provider_auth_report("anthropic", secrets_path=secrets_path, timeout_s=timeout_s)
    return _readiness_from_report(report)


def cli_available(cli_path: str = "claude") -> bool:
    return shutil.which(cli_path) is not None


# --- stream-json → BackendEvent parser (agent M4b) -------------------------
#
# Ground-truth schema (claude v2.1.210, ``-p --output-format stream-json --verbose``,
# whole-message mode — verified by a live sample, NOT assumed):
#   {"type":"system","subtype":"init","session_id":...,"model":...,"mcp_servers":[...]}
#   {"type":"system","subtype":"hook_started"|"hook_response"|"api_retry",...}   (noise)
#   {"type":"assistant","message":{"role":"assistant","content":[
#        {"type":"thinking","thinking":...,"signature":...},   (internal — NEVER surfaced)
#        {"type":"text","text":...},
#        {"type":"tool_use","id":"toolu_...","name":"Read"|"mcp__srv__tool","input":{...}}]}}
#   {"type":"user","message":{"role":"user","content":[
#        {"type":"tool_result","tool_use_id":"toolu_...","content":str|list}]}}
#        — NOTE: ``is_error`` is ABSENT on success (default False); the block carries
#          only ``tool_use_id`` (no tool name), so the parser correlates it back to the
#          name it recorded from the matching ``tool_use``.
#   {"type":"result","subtype":"success"|"error_max_turns"|"error_during_execution",
#        "is_error":bool,"result":str,...}
#   {"type":"rate_limit_event",...}   (noise)


def _try_json_dict(s: str) -> dict[str, Any] | None:
    try:
        value = json.loads(s)
    except (ValueError, TypeError):
        return None
    return value if isinstance(value, dict) else None


def _coerce_tool_result(content: Any) -> dict[str, Any]:
    """Normalize a ``tool_result`` content (str | list-of-blocks | dict) into a dict.

    Canvas tools return a JSON object as text; parsing it keeps ToolResult.result a
    dict so downstream ``run_id`` lifting + dict access work. Non-JSON text (e.g. a
    Read result) is wrapped as ``{"content": ...}`` — the payload is preserved, the
    declared dict type is honored, and nothing is fabricated.
    """

    if isinstance(content, dict):
        return content
    if isinstance(content, str):
        parsed = _try_json_dict(content)
        return parsed if parsed is not None else {"content": content}
    if isinstance(content, list):
        texts = [
            b.get("text", "")
            for b in content
            if isinstance(b, dict) and b.get("type") == "text"
        ]
        if texts:
            joined = "".join(texts)
            parsed = _try_json_dict(joined)
            return parsed if parsed is not None else {"content": joined}
        return {"content": content}
    return {"content": content}


def parse_claude_stream_json_lines(lines: Iterable[str]) -> Iterator[BackendEvent]:
    """Map claude ``stream-json`` stdout lines → ``BackendEvent`` stream (PURE, no I/O).

    See the schema comment above. Mapping:
    - ``system``/``init`` → ``SessionStarted``; other ``system`` subtypes skipped.
    - ``assistant`` content blocks: ``text`` → ``AssistantText``; ``tool_use`` →
      ``ToolCall`` (and its ``id``→``name`` is recorded for later correlation);
      ``thinking`` (and unknown blocks) SKIPPED — internal reasoning is never surfaced.
    - ``user`` content ``tool_result`` → ``ToolResult`` with the tool NAME resolved from
      the recorded ``tool_use`` map (the block itself has only ``tool_use_id``);
      ``is_error`` defaults False when absent (its success shape).
    - ``result`` → ``Done(reason=subtype)`` on success, else ``BackendError`` (honest —
      ``is_error`` or a non-``success`` subtype is a real failure, not a done).
    - ``rate_limit_event`` / unknown types / unparseable lines → skipped (a partial
      newline mid-stream must not crash the turn).

    The spawner feeds real subprocess stdout; tests feed captured/sampled fixtures.
    """

    tool_names: dict[str, str] = {}
    for raw in lines:
        line = raw.strip()
        if not line:
            continue
        obj = _try_json_dict(line)
        if obj is None:
            continue  # skip a malformed/partial line — never crash the stream

        etype = obj.get("type")
        if etype == "system":
            if obj.get("subtype") == "init":
                yield SessionStarted(session_id=str(obj.get("session_id", "")))
            continue

        if etype == "assistant":
            message = obj.get("message")
            if not isinstance(message, dict):
                continue  # malformed: message is not an object → skip, don't crash
            for block in message.get("content") or []:
                if not isinstance(block, dict):
                    continue
                btype = block.get("type")
                if btype == "text":
                    text = block.get("text")
                    if isinstance(text, str) and text:
                        yield AssistantText(text=text)
                elif btype == "tool_use":
                    name = str(block.get("name") or "")
                    tid = block.get("id")
                    if isinstance(tid, str) and name:
                        tool_names[tid] = name
                    tinput = block.get("input")
                    yield ToolCall(
                        tool=name,
                        tool_input=tinput if isinstance(tinput, dict) else {},
                    )
                # ``thinking`` and any unknown block type: deliberately skipped.
            continue

        if etype == "user":
            message = obj.get("message")
            if not isinstance(message, dict):
                continue  # malformed: message is not an object → skip, don't crash
            for block in message.get("content") or []:
                if not isinstance(block, dict) or block.get("type") != "tool_result":
                    continue
                tuid = block.get("tool_use_id")
                resolved = tool_names.get(tuid) if isinstance(tuid, str) else None
                yield ToolResult(
                    tool=resolved or (str(tuid) if tuid else "unknown"),
                    result=_coerce_tool_result(block.get("content")),
                    is_error=bool(block.get("is_error")),
                )
            continue

        if etype == "result":
            subtype = str(obj.get("subtype") or "")
            # Success must be POSITIVELY established (cross-vendor floor finding): only
            # subtype=="success" with no is_error is a Done. A missing/other subtype, or
            # is_error, is an honest BackendError — never an assumed success.
            if subtype == "success" and not obj.get("is_error"):
                yield Done(reason="success")
            else:
                detail = obj.get("result") or subtype or "agent result error (unrecognized terminal)"
                yield BackendError(message=str(detail))
            continue

        # rate_limit_event and any other type: skipped.


class ClaudeBackend:
    """Spawn the headless claude CLI and stream its stream-json as ``BackendEvent``.

    Implements the ``AgentBackend`` protocol (``preflight`` + generator ``run``).

    Red-line invariants (agent floor):
    - **L-C**: the spawn env is built by ``build_spawn_env`` (allowlist) — NEVER
      ``os.environ.copy()`` — so ``QUANTBT_MASTER_KEY`` / venue secrets are absent.
    - The prompt goes on **stdin** (``agent_prompt_via_stdin``), never argv (argv-
      injection floor). The MCP config pins the no-key canvas server with
      ``--strict-mcp-config``, so the agent's tool reach is fixed regardless of tier.

    ``cli_path`` / ``python_executable`` are injectable so tests can point at a stub
    CLI that emits canned stream-json — exercising the real spawn/stdin/parse wiring
    without a live claude subscription.
    """

    def __init__(
        self,
        *,
        model: str,
        workspace_dir: str | Path,
        data_root: str | Path,
        backend_root: str | Path,
        canvas_token: str,
        tier: PermissionTier = PermissionTier.STANDARD,
        allowed_tools: tuple[str, ...] = (),
        cli_path: str = "claude",
        python_executable: str = "python",
        secrets_path: Path | None = None,
    ) -> None:
        self._model = model
        self._workspace_dir = Path(workspace_dir)
        self._data_root = data_root
        self._backend_root = backend_root
        self._canvas_token = canvas_token
        self._tier = tier
        self._allowed_tools = allowed_tools
        self._cli_path = cli_path
        self._python_executable = python_executable
        self._secrets_path = secrets_path

    def preflight(self) -> BackendReadiness:
        return preflight(secrets_path=self._secrets_path)

    def run(self, *, prompt: str, owner: str, **kwargs: Any) -> Iterator[BackendEvent]:
        """Spawn claude, feed the prompt on stdin, yield parsed BackendEvents.

        Terminal honesty: a non-zero exit with no ``Done``/``BackendError`` already
        emitted becomes a ``BackendError`` (never a silent success). Control-flow
        exceptions propagate; the process is always cleaned up.
        """

        import subprocess
        import tempfile
        import threading

        self._workspace_dir.mkdir(parents=True, exist_ok=True)
        mcp_config = build_mcp_config(
            data_root=self._data_root,
            backend_root=self._backend_root,
            owner=owner,
            canvas_token=self._canvas_token,
            python_executable=self._python_executable,
        )
        mcp_path = write_mcp_config(mcp_config, self._workspace_dir / ".quantbt-agent.mcp.json")
        argv = build_agent_argv(
            mcp_config_path=mcp_path,
            workspace_dir=self._workspace_dir,
            model=self._model,
            tier=self._tier,
            allowed_tools=self._allowed_tools,
            cli_path=self._cli_path,
        )
        # L-C: allowlist env only — no master key / venue secret ever handed to the agent.
        env = build_spawn_env(
            owner=owner, canvas_token=self._canvas_token, data_root=self._data_root
        )
        # stderr to a temp file (not a PIPE we never drain) so a chatty stderr can
        # never fill its buffer and deadlock the stdout reader.
        stderr_file = tempfile.TemporaryFile(mode="w+")
        proc = subprocess.Popen(  # noqa: S603 — argv is builder-controlled, prompt is on stdin
            argv,
            cwd=str(self._workspace_dir),
            env=env,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=stderr_file,
            text=True,
        )
        def _feed_stdin() -> None:
            # Write the prompt on a SEPARATE thread so a large prompt can never
            # deadlock against the child's stdout: the main thread reads stdout
            # concurrently with this write (cross-vendor floor finding — a prompt
            # bigger than the pipe buffer would otherwise block the writer while
            # claude blocks writing stdout that no one is draining).
            try:
                if proc.stdin is not None:
                    proc.stdin.write(agent_prompt_via_stdin(prompt))
                    proc.stdin.close()
            except (BrokenPipeError, ValueError, OSError):
                pass  # child exited early / stdin already closed — stdout carries the truth

        writer = threading.Thread(target=_feed_stdin, daemon=True)
        saw_terminal = False
        try:
            writer.start()
            for event in parse_claude_stream_json_lines(proc.stdout or []):
                if isinstance(event, (Done, BackendError)):
                    saw_terminal = True
                yield event
            returncode = proc.wait()
            if returncode != 0 and not saw_terminal:
                stderr_file.seek(0)
                tail = (stderr_file.read() or "").strip()[-500:]
                yield BackendError(
                    message=f"claude exited {returncode}: {tail}" if tail else f"claude exited {returncode}"
                )
        finally:
            if proc.poll() is None:
                proc.kill()
                proc.wait()
            writer.join(timeout=5)  # let the stdin feeder unwind (stdin now closed on kill)
            for stream in (proc.stdin, proc.stdout):
                try:
                    if stream is not None:
                        stream.close()
                except Exception:  # noqa: BLE001 — best-effort cleanup
                    pass
            try:
                stderr_file.close()
            except Exception:  # noqa: BLE001
                pass
