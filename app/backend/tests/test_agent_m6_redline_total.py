"""M6 red-line TOTAL assertion — the embedded-agent capstone (CI-safe part).

Composes the existing per-milestone floors (L-A/L-B/L-C/L-D) into ONE cross-tier
invariant asserted against the SAME builders ``ClaudeBackend.run`` uses, under a
POISONED parent env. Where the earlier tests each prove one layer, this proves the
layers hold *together*, for *every* PermissionTier, and that no planted credential
reaches any config surface. Design = cross-vendor duet (deep-opus ‖ codex).

The honest boundary this pins (user chose 放权 / keep built-in tools):
- The agent's MCP reach is our no-key server: {canvas_read, canvas_create_node} — no
  money/venue/order tool anywhere (L-A). Under bypassPermissions the agent ALSO has
  claude's built-in tools (Bash/WebFetch) — that is the documented ambient residual.
  The 3 hard red lines (money/venue/A-share-live) still hold because (a) no such MCP
  tool exists and (b) build_spawn_env hands the agent NO secret of ours (L-C), so even
  Bash cannot reach OUR venue creds. This suite asserts THAT floor — not the false
  claim "the agent can only touch the canvas".

Mutation contract (RULES §2 种坏门必抓):
- Add a money/venue-vocabulary tool name to the MCP server → vocabulary test RED.
- Make a tier emit a different --allowed-tools / env / mcp.json → cross-tier test RED.
- Flip the MCP server env QUANTBT_RUNTIME_MODE to "test"/"development" → B2 test RED
  (that would materialize the hardcoded dev master key in a keystore-importing child).
- Let a planted secret reach the spawn env / mcp.json → canary test RED.
"""

from __future__ import annotations

import pytest

from app.agent.backends.base import PermissionTier
from app.agent.backends.claude_backend import (
    CANVAS_CREATE_NODE_TOOL,
    CANVAS_READ_TOOL,
    MCP_SERVER_NAME,
    build_agent_argv,
    build_mcp_config,
    build_spawn_env,
    write_mcp_config,
)


def _test_is_secret_key(key: str) -> bool:
    """INDEPENDENT secret-key predicate — deliberately NOT the production
    ``_is_forbidden``, so a future weakening of the production filter cannot
    false-green this test (cross-vendor floor finding: self-certifying assertion)."""

    up = key.upper()
    exact = {
        "QUANTBT_MASTER_KEY", "BINANCE_API_KEY", "BINANCE_API_SECRET",
        "OKX_API_KEY", "OKX_API_SECRET", "TUSHARE_TOKEN", "ANTHROPIC_API_KEY",
        "ANTHROPIC_AUTH_TOKEN", "CLAUDE_CODE_OAUTH_TOKEN", "COMPANY_DEPLOY_CREDENTIAL",
    }
    subs = ("MASTER_KEY", "API_SECRET", "API_KEY", "PRIVATE_KEY", "SECRET_KEY", "OAUTH", "CREDENTIAL")
    return up in exact or any(s in up for s in subs)

_CANVAS_MCP = [CANVAS_READ_TOOL, CANVAS_CREATE_NODE_TOOL]

# Planted credentials in the parent env — none may reach the child env or mcp.json.
# Covers our secret families PLUS the anthropic/claude subscription-token families
# the earlier spawn-contract test never planted, PLUS a name-innocent secret that
# only the allowlist (not the name filter) excludes.
_POISON = {
    "QUANTBT_MASTER_KEY": "CANARY_MASTER_a1b2c3",
    "BINANCE_API_SECRET": "CANARY_BINANCE_d4e5f6",
    "OKX_API_SECRET": "CANARY_OKX_708192",
    "TUSHARE_TOKEN": "CANARY_TUSHARE_a3b4c5",
    "ANTHROPIC_API_KEY": "CANARY_ANTHROPIC_d6e7f8",
    "ANTHROPIC_AUTH_TOKEN": "CANARY_AUTH_091a2b",
    "CLAUDE_CODE_OAUTH_TOKEN": "CANARY_OAUTH_3c4d5e",
    "COMPANY_DEPLOY_CREDENTIAL": "CANARY_DEPLOY_6f7081",
}
_CANARY_VALUES = frozenset(_POISON.values())
_ALL_TIERS = list(PermissionTier)

# Money/venue/live vocabulary — no agent-reachable tool name may contain any of these.
_FORBIDDEN_VOCAB = (
    "order", "venue", "place", "submit", "promote", "testnet", "mainnet",
    "live", "withdraw", "transfer", "secret", "broker", "leverage", "keystore",
)


@pytest.fixture
def poisoned(monkeypatch, tmp_path):
    """Plant the canaries in os.environ; return the (data_root, workspace, backend_root)."""

    for key, value in _POISON.items():
        monkeypatch.setenv(key, value)
    return tmp_path


def _assemble(tier: PermissionTier, root):
    """Build argv + mcp.json + spawn env exactly as ClaudeBackend.run would, per tier."""

    # Fixed paths across tiers (only the tier must differ) so the cross-tier argv
    # comparison isolates the --permission-mode token, not incidental path changes.
    data_root = root / "data"
    workspace = root / "ws"
    backend_root = root / "backend"
    mcp = build_mcp_config(
        data_root=data_root,
        backend_root=backend_root,
        owner="alice",
        canvas_token="cvtok",
        python_executable="python",
    )
    mcp_path = write_mcp_config(mcp, workspace / ".quantbt-agent.mcp.json")
    argv = build_agent_argv(
        mcp_config_path=mcp_path,
        workspace_dir=workspace,
        model="claude-sonnet-4-5",
        tier=tier,
        allowed_tools=(),
    )
    env = build_spawn_env(owner="alice", canvas_token="cvtok", data_root=data_root)
    return argv, mcp, env, mcp_path


def _walk_strings(obj):
    """Recursively yield every string key AND value in a nested dict/list."""

    if isinstance(obj, dict):
        for k, v in obj.items():
            if isinstance(k, str):
                yield k
            yield from _walk_strings(v)
    elif isinstance(obj, (list, tuple)):
        for item in obj:
            yield from _walk_strings(item)
    elif isinstance(obj, str):
        yield obj


def _argv_flag(argv, flag):
    return argv[argv.index(flag) + 1]


# --- Layer enumeration: registry / served / mcp.json ------------------------


def test_registry_served_and_mcpjson_are_the_two_tool_universe(poisoned):
    from app.agent_mcp import server

    assert server.registered_tool_names() == frozenset({"canvas_read", "canvas_create_node"})

    mcp = pytest.importorskip("mcp")  # noqa: F841
    served = {t.name for t in server.build_tools()}
    assert served == {"canvas_read", "canvas_create_node"}

    _, mcp_config, _, _ = _assemble(PermissionTier.STANDARD, poisoned)
    servers = mcp_config["mcpServers"]
    assert list(servers.keys()) == [MCP_SERVER_NAME]  # exactly ONE MCP server
    assert servers[MCP_SERVER_NAME]["args"] == ["-m", "app.agent_mcp.server"]


@pytest.mark.parametrize("tier", _ALL_TIERS, ids=lambda t: t.value)
def test_argv_mcp_subset_is_both_canvas_tools_per_tier(tier, poisoned):
    """Every tier's --allowed-tools MCP subset is exactly the two canvas tools."""

    argv, _, _, _ = _assemble(tier, poisoned)
    assert "--strict-mcp-config" in argv
    assert argv.count("--mcp-config") == 1
    tools = _argv_flag(argv, "--allowed-tools").split(",")
    mcp_tools = [t for t in tools if t.startswith("mcp__")]
    assert mcp_tools == _CANVAS_MCP


def test_tier_changes_only_the_permission_mode(poisoned):
    """Across all tiers: the WRITTEN mcp.json bytes + spawn env are identical; argv
    differs only in the --permission-mode value token. This is the real anti-escalation
    catch — any future tier-conditional flag/tool/secret trips it."""

    baseline = None
    for tier in _ALL_TIERS:
        argv, mcp, env, mcp_path = _assemble(tier, poisoned)
        on_disk = mcp_path.read_bytes()  # the ACTUAL serialized bytes claude will read
        # neutralize the (expected) sole difference: the permission-mode value token
        pm = argv.index("--permission-mode")
        assert argv[pm + 1] == tier.value
        normalized = argv[:pm + 1] + ["<MODE>"] + argv[pm + 2:]
        snapshot = (normalized, mcp, env, on_disk)
        if baseline is None:
            baseline = snapshot
        else:
            assert normalized == baseline[0], f"tier {tier.value} changed argv beyond --permission-mode"
            assert mcp == baseline[1], f"tier {tier.value} changed mcp.json dict"
            assert env == baseline[2], f"tier {tier.value} changed spawn env"
            assert on_disk == baseline[3], f"tier {tier.value} changed the written mcp.json bytes"


# --- Canary / secret exclusion (L-C total) ----------------------------------


@pytest.mark.parametrize("tier", _ALL_TIERS, ids=lambda t: t.value)
def test_no_planted_secret_in_env_or_mcpjson(tier, poisoned):
    """No planted canary VALUE reaches the child env or mcp.json; no forbidden-family
    KEY appears (QB_CANVAS_TOKEN is the one deliberately-persisted exception)."""

    argv, mcp, env, mcp_path = _assemble(tier, poisoned)

    env_strings = set(env.keys()) | set(env.values())
    mcp_strings = set(_walk_strings(mcp))
    argv_strings = set(argv)
    on_disk = mcp_path.read_text()

    for canary in _CANARY_VALUES:
        assert canary not in env_strings, f"canary leaked into spawn env ({tier.value})"
        assert canary not in mcp_strings, f"canary leaked into mcp.json ({tier.value})"
        assert canary not in argv_strings, f"canary leaked into argv ({tier.value})"
        assert canary not in on_disk, f"canary leaked into written mcp.json ({tier.value})"

    # No secret-family env/mcp KEY except the intentional QB_CANVAS_TOKEN — checked
    # with the test's OWN predicate (not production _is_forbidden), so weakening the
    # production filter cannot hide a leaked key from this assertion.
    all_keys = list(env.keys()) + [k for k in _walk_strings(mcp)]
    for key in all_keys:
        if _test_is_secret_key(key):
            assert key == "QB_CANVAS_TOKEN", f"secret-family key present: {key}"
    assert env["QB_CANVAS_TOKEN"] == "cvtok"  # the legitimate canvas-scope id IS present
    assert not _test_is_secret_key("QB_CANVAS_TOKEN")  # sanity: the exemption is real


def test_runtime_mode_is_agent_never_test_or_development(poisoned, monkeypatch):
    """B2: even when the PARENT env is explicitly the risky mode ('test'), the MCP
    server env forces QUANTBT_RUNTIME_MODE='agent' (fail-closed) and the spawn env
    never carries it. A mode of test/development would materialize the hardcoded dev
    master key (mainnet_guards / keystore), so the agent config must never emit it."""

    # Plant the DANGEROUS value in the parent env — the child config must not inherit it.
    monkeypatch.setenv("QUANTBT_RUNTIME_MODE", "test")
    _, mcp, env, _ = _assemble(PermissionTier.STANDARD, poisoned)

    server_env = mcp["mcpServers"][MCP_SERVER_NAME]["env"]
    assert server_env["QUANTBT_RUNTIME_MODE"] == "agent"  # forced, ignores the parent 'test'
    assert server_env["QUANTBT_RUNTIME_MODE"] not in {"test", "development"}
    # The spawn env's allowlist does not include QUANTBT_RUNTIME_MODE, so the parent's
    # 'test' is stripped entirely — the agent process cannot see a test/dev mode.
    assert "QUANTBT_RUNTIME_MODE" not in env


# --- Vocabulary + sealing (L-A total, B5) -----------------------------------


def test_no_money_venue_vocabulary_and_no_registration_surface():
    """B5: no agent-reachable tool name contains money/venue/live vocabulary; the
    registry is a frozenset (sealed) and the server exposes no runtime register hook."""

    from app.agent_mcp import server

    names = set(server.registered_tool_names())
    pytest.importorskip("mcp")
    names |= {t.name for t in server.build_tools()}
    for name in names:
        low = name.lower()
        for bad in _FORBIDDEN_VOCAB:
            assert bad not in low, f"tool {name!r} matches forbidden vocabulary {bad!r}"

    assert isinstance(server._TOOL_NAMES, frozenset)  # sealed, not a mutable set
    # No public WRITE hook that could grow the tool surface at runtime. Match verb
    # forms (register_tool / add_tool / register_handler) — NOT the read-only
    # ``registered_tool_names`` accessor, which merely reports the frozen set.
    _WRITE_HOOKS = ("register_tool", "register_handler", "add_tool", "add_handler", "set_tool")
    for attr in dir(server):
        if attr.startswith("__"):
            continue
        low = attr.lower()
        assert not (
            callable(getattr(server, attr, None)) and any(h in low for h in _WRITE_HOOKS)
        ), f"server exposes a dynamic tool-registration callable: {attr}"


def test_documented_residual_home_present_masterkey_absent(poisoned, monkeypatch):
    """B1 honest boundary: the spawn env DOES carry HOME (claude needs it to reach its
    own keychain — the ambient residual) but NEVER our QUANTBT_MASTER_KEY."""

    monkeypatch.setenv("HOME", "/Users/tester")
    env = build_spawn_env(owner="alice", canvas_token="cvtok", data_root=poisoned / "d")
    assert env.get("HOME") == "/Users/tester"  # ambient residual, by design
    assert "QUANTBT_MASTER_KEY" not in env  # our secret, never handed over
    assert env.get("QUANTBT_MASTER_KEY") is None


# --- Output surface (B6) ----------------------------------------------------


def test_parser_never_surfaces_a_thinking_secret():
    """B6: a stream-json thinking block containing a planted secret produces NO event
    carrying it — internal reasoning (which may quote secrets) never reaches SSE."""

    from app.agent.backends.claude_backend import parse_claude_stream_json_lines

    secret = "CANARY_THINKING_SECRET_zzz999"
    line = (
        '{"type":"assistant","message":{"role":"assistant","content":['
        '{"type":"thinking","thinking":"the key is ' + secret + '","signature":"s"},'
        '{"type":"text","text":"done"}]}}'
    )
    events = list(parse_claude_stream_json_lines([line]))
    for ev in events:
        blob = repr(ev)
        assert secret not in blob, f"thinking secret leaked into {type(ev).__name__}"
    assert [type(e).__name__ for e in events] == ["AssistantText"]
    assert events[0].text == "done"
