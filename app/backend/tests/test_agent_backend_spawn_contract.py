"""Spawn-contract + L-C red-line proof for the claude backend (agent M3).

The safety-critical claim: the agent we spawn NEVER receives a secret we hold —
no ``QUANTBT_MASTER_KEY``, no venue key — so even an agent with a Bash shell
cannot decrypt the trading keystore or reach a venue via anything we handed it.

Mutation contract (RULES §2 种坏门必抓):
- ``build_spawn_env`` → ``dict(base_env)`` (copy everything) → the master-key /
  venue-secret exclusion tests go RED.
- Drop ``--strict-mcp-config`` from ``build_agent_argv`` → the strict-mcp test RED.
- Add ``QUANTBT_MASTER_KEY`` to ``_SPAWN_ENV_ALLOWLIST`` → exclusion tests RED
  (the forbidden force-drop still catches it — belt and suspenders).
"""

from __future__ import annotations

from app.agent.backends.base import BackendReadiness, PermissionTier
from app.agent.backends.claude_backend import (
    CANVAS_READ_TOOL,
    build_agent_argv,
    build_mcp_config,
    build_spawn_env,
)

_POISONED_ENV = {
    "PATH": "/usr/local/bin:/usr/bin",
    "HOME": "/home/alice",
    "LANG": "en_US.UTF-8",
    "QUANTBT_MASTER_KEY": "MASTER-must-not-leak",
    "BINANCE_API_KEY": "venue-key-must-not-leak",
    "BINANCE_API_SECRET": "venue-secret-must-not-leak",
    "OKX_API_SECRET": "okx-secret",
    "SOME_CUSTOM_API_SECRET": "custom-secret",
    "TUSHARE_TOKEN": "tushare-must-not-leak",
    "RANDOM_MASTER_KEY_THING": "also-secret",
    # A secret whose NAME matches no forbidden substring: only the allowlist
    # (the primary L-C mechanism) can exclude it. If build_spawn_env ever copies
    # the whole parent env, this leaks — proving the allowlist has teeth.
    "COMPANY_DEPLOY_CREDENTIAL": "deploy-only-allowlist-excludes-this",
}


def _argv(**over):
    kwargs = dict(
        mcp_config_path="/tmp/agent/.mcp.json",
        workspace_dir="/tmp/agent/workspace",
        model="claude-sonnet-5",
    )
    kwargs.update(over)
    return build_agent_argv(**kwargs)


# --- L-C red-line: the spawn env withholds every secret we hold ---------------

def test_spawn_env_excludes_master_key_and_venue_secrets():
    env = build_spawn_env(
        owner="alice", canvas_token="canvas-tok", data_root="/data", base_env=_POISONED_ENV
    )
    for forbidden in (
        "QUANTBT_MASTER_KEY",
        "BINANCE_API_KEY",
        "BINANCE_API_SECRET",
        "OKX_API_SECRET",
        "SOME_CUSTOM_API_SECRET",
        "TUSHARE_TOKEN",
        "RANDOM_MASTER_KEY_THING",
        "COMPANY_DEPLOY_CREDENTIAL",  # excluded by the allowlist, not the forbidden list
    ):
        assert forbidden not in env, f"L-C breach: {forbidden} leaked into the agent env"
    # No secret VALUE should survive either.
    leaked_values = {
        "MASTER-must-not-leak",
        "venue-key-must-not-leak",
        "venue-secret-must-not-leak",
        "tushare-must-not-leak",
    }
    assert leaked_values.isdisjoint(set(env.values())), "a secret value leaked into the agent env"


def test_spawn_env_excludes_node_code_injection_vars():
    # Cross-vendor floor finding: NODE_OPTIONS (--require <file>) and NODE_PATH
    # are node code-injection surfaces; they must not ride into the agent env.
    env = build_spawn_env(
        owner="a",
        canvas_token="t",
        data_root="/d",
        base_env={"PATH": "/bin", "NODE_OPTIONS": "--require /evil.js", "NODE_PATH": "/evil/mods"},
    )
    assert "NODE_OPTIONS" not in env
    assert "NODE_PATH" not in env
    assert env["PATH"] == "/bin"


def test_spawn_env_passes_operational_vars_and_identity():
    env = build_spawn_env(
        owner="alice", canvas_token="canvas-tok", data_root="/data/root", base_env=_POISONED_ENV
    )
    assert env["PATH"] == "/usr/local/bin:/usr/bin"
    assert env["HOME"] == "/home/alice"
    assert env["QB_OWNER"] == "alice"
    assert env["QB_CANVAS_TOKEN"] == "canvas-tok"
    assert env["BACKTEST_DATA_ROOT"] == "/data/root"


def test_mcp_config_server_env_also_withholds_secrets():
    config = build_mcp_config(
        data_root="/data",
        backend_root="/repo/app/backend",
        owner="alice",
        canvas_token="canvas-tok",
    )
    server = config["mcpServers"]["quantbt-agent-canvas"]
    assert server["args"] == ["-m", "app.agent_mcp.server"]
    # Build with the real os.environ; assert our master key isn't in the server env.
    assert "QUANTBT_MASTER_KEY" not in server["env"]
    assert server["env"]["PYTHONPATH"] == "/repo/app/backend"


# --- argv contract: strict-mcp + canvas tool always; tier only widens CLI ------

def test_argv_pins_strict_mcp_and_canvas_tool():
    argv = _argv()
    assert "--strict-mcp-config" in argv, "agent could load an ambient MCP server with venue tools"
    assert "--mcp-config" in argv and "--add-dir" in argv
    assert "stream-json" in argv
    tools = argv[argv.index("--allowed-tools") + 1]
    assert CANVAS_READ_TOOL in tools


def test_default_tier_is_not_autonomous():
    argv = _argv()
    mode = argv[argv.index("--permission-mode") + 1]
    assert mode == "acceptEdits"
    assert mode != "bypassPermissions"


def test_widening_tier_and_cli_tools_keeps_the_mcp_redline():
    # User opts into full autonomy + a Bash CLI tool (放权). The MCP reach must
    # STILL be strict + canvas-only; the danger of Bash is the user's own env,
    # which build_spawn_env already scrubs of our secrets.
    argv = _argv(tier=PermissionTier.AUTONOMOUS, allowed_tools=("Bash",))
    assert argv[argv.index("--permission-mode") + 1] == "bypassPermissions"
    assert "--strict-mcp-config" in argv
    tools = argv[argv.index("--allowed-tools") + 1].split(",")
    mcp_tools = [t for t in tools if t.startswith("mcp__")]
    assert mcp_tools == [CANVAS_READ_TOOL], "widening tier must not add a second MCP tool"


def test_argv_strips_foreign_mcp_tools_from_allowed_tools():
    # Defense-in-depth (cross-vendor floor finding): a caller passing a foreign
    # mcp__* tool (e.g. a venue/order tool from another server) must never reach
    # --allowed-tools, even though --strict-mcp-config would also neutralize it.
    argv = _argv(allowed_tools=("mcp__evil-server__place_order", "Bash", "mcp__venue__submit_order"))
    tools = argv[argv.index("--allowed-tools") + 1].split(",")
    mcp_tools = [t for t in tools if t.startswith("mcp__")]
    assert mcp_tools == [CANVAS_READ_TOOL], f"foreign MCP tool leaked into allowed-tools: {mcp_tools}"
    assert "Bash" in tools, "non-mcp CLI tools must still pass through"


def test_argv_rejects_comma_smuggled_foreign_mcp_tool():
    # Cross-vendor floor (round 3): claude re-splits --allowed-tools on commas, so
    # a single element "Bash,mcp__evil__place_order" must not smuggle a foreign mcp
    # tool past the per-element filter. We split before filtering.
    argv = _argv(allowed_tools=("Bash,mcp__evil__place_order", "Read,mcp__venue__submit"))
    tools = argv[argv.index("--allowed-tools") + 1].split(",")
    mcp_tools = [t for t in tools if t.startswith("mcp__")]
    assert mcp_tools == [CANVAS_READ_TOOL], f"comma-smuggled foreign MCP tool leaked: {mcp_tools}"
    assert "Bash" in tools and "Read" in tools, "the legitimate CLI tools should survive the split"


def test_argv_rejects_space_smuggled_foreign_mcp_and_keeps_paren_specs():
    # claude also space-splits --allowed-tools, so "Bash mcp__evil__x" (one element,
    # a space) must not smuggle a foreign mcp tool either. And a legitimate paren
    # spec like "Bash(git *)" (which contains a space but no mcp__) must survive.
    argv = _argv(allowed_tools=("Bash mcp__evil__place_order", "Bash(git *)"))
    tools = argv[argv.index("--allowed-tools") + 1].split(",")
    mcp_tools = [t for t in tools if "mcp__" in t]
    assert mcp_tools == [CANVAS_READ_TOOL], f"space-smuggled foreign MCP tool leaked: {mcp_tools}"
    assert "Bash(git *)" in tools, "a legitimate paren spec with a space must pass through"


def test_canvas_tool_not_duplicated_when_passed_in_allowed_tools():
    argv = _argv(allowed_tools=(CANVAS_READ_TOOL, "Read"))
    tools = argv[argv.index("--allowed-tools") + 1].split(",")
    assert tools.count(CANVAS_READ_TOOL) == 1


def test_prompt_is_never_a_positional_argv_arg():
    # Cross-vendor floor breach: claude 2.1.210 parses a positional prompt as
    # flags — a prompt of "--mcp-config=/evil.json" injects a malicious MCP server
    # despite --strict-mcp-config. So build_agent_argv takes no prompt at all; the
    # prompt goes via stdin. There is no argv slot for a "-p <value>" pair.
    from app.agent.backends import claude_backend

    argv = _argv()
    # -p is the boolean --print flag; the token after it must be a flag, not a value.
    assert argv[argv.index("-p") + 1].startswith("--")
    # The stdin seam carries the prompt verbatim, off the command line.
    assert claude_backend.agent_prompt_via_stdin("--mcp-config=/evil.json") == "--mcp-config=/evil.json"


def test_model_starting_with_dash_is_rejected():
    import pytest

    with pytest.raises(ValueError):
        _argv(model="--dangerously-skip-permissions")


def test_preflight_readiness_requires_cli_auth_not_api_key():
    # Honesty (cross-vendor floor finding): a configured API key alone must NOT
    # report ready — this backend spawns the CLI (keychain auth) and never passes
    # that key. Only cli_installed AND subscription auth is an honest green.
    from app.agent.backends.claude_backend import _readiness_from_report

    api_key_only = _readiness_from_report(
        {"cli": "claude", "cli_installed": False, "subscription_authed": False, "api_key_configured": True, "ready": True}
    )
    assert api_key_only.ready is False, "API key alone must not report the CLI backend ready"

    cli_authed = _readiness_from_report(
        {"cli": "claude", "cli_installed": True, "subscription_authed": True, "api_key_configured": False, "ready": True}
    )
    assert cli_authed.ready is True

    installed_not_authed = _readiness_from_report(
        {"cli": "claude", "cli_installed": True, "subscription_authed": False, "api_key_configured": True, "ready": True}
    )
    assert installed_not_authed.ready is False


def test_backend_readiness_blocking_reason():
    not_ready = BackendReadiness(
        provider="anthropic", cli="claude", cli_installed=True, authed=False, ready=False, detail="登录一次"
    )
    ready = BackendReadiness(
        provider="anthropic", cli="claude", cli_installed=True, authed=True, ready=True, detail="就绪"
    )
    assert not_ready.blocking_reason == "登录一次"
    assert ready.blocking_reason is None
