"""No-key stdio MCP server — canvas-read floor (agent M1).

The embedded Claude-Code agent is fed ONLY by this server, so its entire tool
reach is exactly what we register here. This M1 milestone lays the *red-line
floor* and ships one read-only tool (``canvas_read``); the canvas WRITE tool
(``canvas_create_node``) lands in a later slice, once this floor is
cross-vendor verified. Sequencing the read-only floor first is deliberate: no
write tool is registered before the no-key isolation is proven.

Red-line floor (dev/research/findings/dreaminate/claude-code-agent-impl-plan-duet-20260716.md §3):

- **L-A (non-registration).** ``registered_tool_names()`` is the single source of
  truth for what the agent can call, and it is exactly ``{"canvas_read"}``. The
  dispatcher rejects every other name. No venue / key / order-placement tool is
  registered — not disabled, *absent*.
- **L-B (no-import).** This module imports ONLY ``app.paths`` (os+pathlib) and
  ``app.research_os.spine``. Neither cascades into ``app.security.keystore``,
  ``KeyBroker``, ``place_order``, or any venue gateway. That is why this package
  is a sibling of ``app.agent`` (whose ``__init__`` eagerly loads the LLM/key
  stack) rather than a child of it. Enforced by
  ``tests/test_agent_mcp_redline_floor.py``, which imports this module in a fresh
  interpreter and asserts no key/venue module is in ``sys.modules``.

Runs as an independent stdio process via the official ``mcp`` SDK.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

# L-B: the ONLY two intra-app imports permitted in this module.
# app.paths → os+pathlib only; app.research_os.spine → 0 danger modules (probed).
# ``_persistent_research_graph_write_lock`` is spine's own cross-process file lock
# (spine.py:115) — the same primitive its ``refresh()``/append paths hold. We are a
# second reader of the same JSONL, so we coordinate through spine's lock, not a
# parallel one. Importing it loads no new module (spine is already imported).
from app.paths import DATA_ROOT
from app.research_os.spine import (
    PersistentResearchGraphStore,
    ResearchGraphProjectionRecord,
    _persistent_research_graph_write_lock,
)

CANVAS_READ = "canvas_read"

# L-A: the agent's entire tool reach. The dispatcher and the MCP ``list_tools``
# handler both derive from this set; nothing else is callable.
_TOOL_NAMES = frozenset({CANVAS_READ})

# Same JSONL the API process (app.main) writes to. Captured at import time under
# the active BACKTEST_DATA_ROOT, mirroring app.main:775.
RESEARCH_GRAPH_COMMANDS_PATH = DATA_ROOT / "audit" / "research_graph_commands.jsonl"

_STORE: PersistentResearchGraphStore | None = None


def registered_tool_names() -> frozenset[str]:
    """L-A single source of truth: the exact set of tools the agent may call."""

    return _TOOL_NAMES


def _store() -> PersistentResearchGraphStore:
    """Lazy singleton, every read cross-process lock-guarded.

    The API process holds the writer store and appends under a cross-process
    flock (spine ``_persistent_research_graph_write_lock``). We are a separate
    reader process. ``refresh()`` reloads under that same lock, so later reads
    never tear on the writer's mid-append tail.

    The FIRST read is the subtle one: ``PersistentResearchGraphStore.__init__``
    calls ``_load_existing()`` *without* the lock, and ``_load_existing``
    fails-closed on a partial row — so a bare construction racing the writer's
    mid-append would raise ``ResearchGraphError`` (cross-vendor review proved
    this with a deterministic partial-tail probe). We therefore construct the
    singleton *inside* the same cross-process lock, so even the first read is
    serialized against appends.
    """

    global _STORE
    if _STORE is None:
        with _persistent_research_graph_write_lock(RESEARCH_GRAPH_COMMANDS_PATH):
            _STORE = PersistentResearchGraphStore(RESEARCH_GRAPH_COMMANDS_PATH)
    else:
        _STORE.refresh()
    return _STORE


def _projection_to_dict(record: ResearchGraphProjectionRecord) -> dict[str, Any]:
    return {
        "projection_ref": record.projection_ref,
        "qro_id": record.qro_id,
        "qro_type": record.qro_type,
        "owner": record.owner,
        "market": record.market,
        "universe": record.universe,
        "horizon": record.horizon,
        "frequency": record.frequency,
        "status_axes": dict(record.status_axes),
        "lineage": list(record.lineage),
        "evidence_refs": list(record.evidence_refs),
        "mathematical_refs": list(record.mathematical_refs),
        "permission": record.permission,
        "allowed_environment": record.allowed_environment,
        "qro_version": record.qro_version,
    }


def canvas_read(arguments: dict[str, Any] | None = None) -> dict[str, Any]:
    """Read-only projection of the research-graph canvas.

    Optional string filters (any subset): ``qro_type``, ``owner``, ``market``,
    ``universe``, ``definition_status``, ``evidence_status``, ``runtime_status``.
    Empty / missing filters match everything.

    "Read-only" is scoped precisely: this creates no QRO and appends no command —
    it never mutates a single line of the graph log. It is NOT filesystem-inert,
    though: the store's cross-process protocol ensures the ``audit/`` directory
    exists and creates a ``…jsonl.write.lock`` sidecar (the same coordination
    artifacts the API writer process uses). Those are locks/dirs, not graph data.
    """

    args = arguments or {}
    store = _store()
    records = store.projection_index(
        qro_type=(args.get("qro_type") or None),
        owner=(args.get("owner") or None),
        market=(args.get("market") or None),
        universe=(args.get("universe") or None),
        definition_status=(args.get("definition_status") or None),
        evidence_status=(args.get("evidence_status") or None),
        runtime_status=(args.get("runtime_status") or None),
    )
    return {
        "nodes": [_projection_to_dict(r) for r in records],
        "count": len(records),
    }


# --- MCP wiring (official low-level SDK) -----------------------------------

_CANVAS_READ_INPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "qro_type": {"type": "string", "description": "Filter by QRO type."},
        "owner": {"type": "string", "description": "Filter by owner id."},
        "market": {"type": "string", "description": "Filter by market."},
        "universe": {"type": "string", "description": "Filter by universe."},
        "definition_status": {"type": "string"},
        "evidence_status": {"type": "string"},
        "runtime_status": {"type": "string"},
    },
    "additionalProperties": False,
}


def build_tools() -> list[Any]:
    """Build the MCP ``Tool`` list. Its names MUST equal ``registered_tool_names()``.

    Imported lazily so unit tests that only exercise the floor (registry +
    ``canvas_read``) need not have the ``mcp`` SDK installed.
    """

    import mcp.types as types

    return [
        types.Tool(
            name=CANVAS_READ,
            description=(
                "Read the research-graph canvas projection (read-only). "
                "Returns matching nodes with their status axes, lineage, and "
                "evidence/mathematical refs. Cannot mutate the graph or touch "
                "keys/venues."
            ),
            inputSchema=_CANVAS_READ_INPUT_SCHEMA,
        ),
    ]


def _dispatch(name: str, arguments: dict[str, Any] | None) -> dict[str, Any]:
    """L-A dispatcher: only ``canvas_read`` is reachable; everything else errors."""

    if name not in _TOOL_NAMES:
        raise ValueError(f"unknown tool: {name!r} (agent tool reach is {sorted(_TOOL_NAMES)})")
    if name == CANVAS_READ:
        return canvas_read(arguments)
    # Unreachable while _TOOL_NAMES == {canvas_read}; guards against silent
    # drift if a name is added to the set without a handler.
    raise ValueError(f"no handler wired for tool: {name!r}")


def build_server() -> Any:
    """Construct the low-level MCP ``Server`` with the canvas-read handlers."""

    from mcp.server import Server
    import mcp.types as types

    server = Server("quantbt-agent-canvas")

    @server.list_tools()
    async def _list_tools() -> list[types.Tool]:
        return build_tools()

    @server.call_tool()
    async def _call_tool(name: str, arguments: dict[str, Any] | None) -> list[types.TextContent]:
        result = _dispatch(name, arguments)
        return [types.TextContent(type="text", text=json.dumps(result, ensure_ascii=False))]

    return server


async def _serve() -> None:
    from mcp.server.stdio import stdio_server

    server = build_server()
    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())


def main() -> None:
    """Entry point: run the no-key canvas MCP server over stdio."""

    import anyio

    anyio.run(_serve)


if __name__ == "__main__":  # pragma: no cover - process entry point
    main()
