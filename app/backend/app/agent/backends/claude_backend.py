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
from typing import Any, Mapping

from .base import BackendReadiness, PermissionTier

# The no-key MCP server (M1). Server name must match app.agent_mcp.server's
# ``Server("quantbt-agent-canvas")`` so the tool id resolves.
MCP_SERVER_NAME = "quantbt-agent-canvas"
CANVAS_READ_TOOL = f"mcp__{MCP_SERVER_NAME}__canvas_read"

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
    # caller passes. Only our canvas MCP tool may be an mcp__ tool. So even if
    # --strict-mcp-config were ever bypassed, --allowed-tools alone cannot grant a
    # second MCP surface (e.g. a venue/order tool). Non-mcp CLI tools pass through.
    #
    # Claude re-splits --allowed-tools on comma OR space. So (a) split each element
    # on commas first (cleanly separates legit tools from a comma-smuggled one),
    # and (b) drop any resulting token that contains "mcp__" ANYWHERE — not just at
    # the start. That catches every smuggling separator: "Bash,mcp__evil__x"
    # (comma) and "Bash mcp__evil__x" (space, dropped whole) both die, while the
    # canvas tool is the sole permitted mcp token and paren specs like "Bash(git *)"
    # (no "mcp__") pass through untouched. Cross-vendor floor finding (rounds 2-3).
    tokens: list[str] = []
    for raw in allowed_tools:
        tokens.extend(part.strip() for part in str(raw).split(",") if part.strip())
    safe_extra = [t for t in tokens if t != CANVAS_READ_TOOL and "mcp__" not in t]
    tools = [CANVAS_READ_TOOL, *safe_extra]
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
