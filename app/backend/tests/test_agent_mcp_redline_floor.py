"""Red-line floor proof for the no-key agent MCP server (agent M1).

Guards L-A (non-registration) + L-B (no-import) from
dev/research/findings/dreaminate/claude-code-agent-impl-plan-duet-20260716.md §3.

The L-B purity check runs in a FRESH interpreter on purpose: pytest's own
process has already imported app.main / keystore via other tests, so
``sys.modules`` here is polluted. Only a clean subprocess proves that importing
the server *alone* pulls in no key/venue module.

Mutation contract (RULES §2 种坏门必抓):
- Register any extra tool in ``_TOOL_NAMES`` / ``build_tools`` → the L-A tests go RED.
- Add ``import app.security.keystore`` (or any venue/key import) to the server
  module → ``test_import_loads_no_key_or_venue_module`` goes RED.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[1]

# Substrings that must never appear in a loaded module name after importing the
# no-key server. Covers keystore, key broker, order placement, venue gateways.
_DANGER_SUBSTRINGS = (
    "keystore",
    "keybroker",
    "key_broker",
    "place_order",
    "trading_credentials",
    "order_guard",
    "ccxt",
    "binance",
    "vnpy",
    "easytrader",
    "ths_trader",
)

# Probe script: import ONLY the server module in a clean interpreter, then report
# any danger module that loaded + the registered tool names. Emits one JSON line.
_PROBE = r"""
import json, sys
import app.agent_mcp.server as srv
danger = sorted(
    m for m in sys.modules
    if any(s in m.lower() for s in %(danger)r)
)
print(json.dumps({
    "danger": danger,
    "tools": sorted(srv.registered_tool_names()),
    "total_modules": len(sys.modules),
}))
"""


def _run_probe() -> dict:
    env = dict(os.environ)
    env["QUANTBT_RUNTIME_MODE"] = "test"
    env.setdefault("BACKTEST_DATA_ROOT", env.get("BACKTEST_DATA_ROOT", "/tmp"))
    # Fresh interpreter rooted at the backend so ``import app...`` resolves.
    existing = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = str(BACKEND_ROOT) + (os.pathsep + existing if existing else "")
    proc = subprocess.run(
        [sys.executable, "-c", _PROBE % {"danger": _DANGER_SUBSTRINGS}],
        cwd=str(BACKEND_ROOT),
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert proc.returncode == 0, f"probe failed:\nSTDOUT:{proc.stdout}\nSTDERR:{proc.stderr}"
    return json.loads(proc.stdout.strip().splitlines()[-1])


def test_import_loads_no_key_or_venue_module():
    """L-B: importing the server in a clean interpreter loads zero key/venue modules."""

    report = _run_probe()
    assert report["danger"] == [], (
        "L-B floor breach: importing app.agent_mcp.server loaded key/venue "
        f"modules: {report['danger']}"
    )


def test_probe_registers_exactly_canvas_read():
    """L-A: the clean interpreter reports the tool reach is exactly {canvas_read}."""

    report = _run_probe()
    assert report["tools"] == ["canvas_read"], (
        f"L-A floor breach: agent tool reach drifted to {report['tools']}"
    )


def test_registered_tool_names_is_exactly_canvas_read():
    """L-A (in-process): the registry constant is exactly {canvas_read}."""

    from app.agent_mcp import server

    assert server.registered_tool_names() == frozenset({"canvas_read"})


def test_dispatch_rejects_venue_and_order_tools():
    """L-A: the dispatcher refuses every name outside the registry — no silent pass."""

    from app.agent_mcp import server

    for forbidden in ("place_order", "canvas_create_node", "read_keystore", "submit_order", ""):
        with pytest.raises(ValueError):
            server._dispatch(forbidden, {})


def test_build_tools_names_match_registry():
    """The served MCP tool list may not drift from the L-A registry constant."""

    pytest.importorskip("mcp")
    from app.agent_mcp import server

    served = {tool.name for tool in server.build_tools()}
    assert served == set(server.registered_tool_names())


def test_canvas_read_is_read_only_and_returns_projection_shape():
    """canvas_read returns the projection envelope; empty store → no nodes."""

    from app.agent_mcp import server

    result = server.canvas_read({})
    assert set(result.keys()) == {"nodes", "count"}
    assert isinstance(result["nodes"], list)
    assert result["count"] == len(result["nodes"])


def test_canvas_read_tolerates_none_arguments():
    """A None argument bag (MCP may pass null) must not crash the read."""

    from app.agent_mcp import server

    result = server.canvas_read(None)
    assert result["count"] == len(result["nodes"])


def test_first_store_construction_is_cross_process_lock_guarded(monkeypatch):
    """Regression: the FIRST store read must hold the cross-process write lock.

    Cross-vendor review proved a bare (unlocked) construction tears on the
    writer's mid-append partial tail — ``_load_existing`` fails-closed and
    ``canvas_read`` raises. The fix constructs the singleton inside spine's
    cross-process lock. Mutation: drop the ``with _persistent_research_graph_write_lock``
    wrapper in ``_store`` and this test goes RED (the lock is never entered).
    """

    import contextlib

    from app.agent_mcp import server

    entered = {"count": 0}
    real_lock = server._persistent_research_graph_write_lock

    @contextlib.contextmanager
    def _spy_lock(path):
        entered["count"] += 1
        with real_lock(path):
            yield

    monkeypatch.setattr(server, "_persistent_research_graph_write_lock", _spy_lock)

    # Force a cold singleton so canvas_read triggers construction.
    prior = server._STORE
    server._STORE = None
    try:
        server.canvas_read({})
        assert entered["count"] >= 1, (
            "first store construction did not acquire the cross-process write lock — "
            "unlocked _load_existing can tear on a concurrent append"
        )
    finally:
        server._STORE = prior
