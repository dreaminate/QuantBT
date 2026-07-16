"""No-key stdio MCP server — canvas read + create-node (agent M1 floor + M5b write).

The embedded Claude-Code agent is fed ONLY by this server, so its entire tool
reach is exactly what we register here. The M1 milestone laid the *red-line
floor* and shipped the read-only tool (``canvas_read``); the canvas WRITE tool
(``canvas_create_node``) is added here in M5b, built on top of the store-level
L-D invariant (CANVAS create → OFFLINE only) proven in M5a. Sequencing the
read-only floor first was deliberate: no write tool was registered before the
no-key isolation was cross-vendor verified.

Red-line floor (dev/research/findings/dreaminate/claude-code-agent-impl-plan-duet-20260716.md §3):

- **L-A (non-registration).** ``registered_tool_names()`` is the single source of
  truth for what the agent can call, and it is exactly
  ``{"canvas_read", "canvas_create_node"}``. The dispatcher rejects every other
  name. No venue / key / order-placement tool is registered — not disabled,
  *absent*. The write tool mints only OFFLINE drafts (L-D, store-enforced).
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
import os
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
    ActorSource,
    DefinitionStatus,
    EntrySource,
    EvidenceStatus,
    GovernanceStatus,
    PersistentResearchGraphStore,
    QRORecord,
    ResearchGraphCommand,
    ResearchGraphError,
    ResearchGraphProjectionRecord,
    RuntimeStatus,
    _persistent_research_graph_write_lock,
    content_hash,
)

# L-B note: every name above comes from ``app.research_os.spine`` (which the M1
# floor already imports with 0 danger modules) or ``app.paths`` (os+pathlib).
# ``content_hash`` lives in spine's namespace via its own ``from ..lineage.ids``.
# Binding write-path names adds NO new module to sys.modules — no keystore /
# KeyBroker / place_order — so the write tool keeps L-B (re-proven by the floor test).

CANVAS_READ = "canvas_read"
CANVAS_CREATE_NODE = "canvas_create_node"

# L-A: the agent's entire tool reach. The dispatcher and the MCP ``list_tools``
# handler both derive from this set; nothing else is callable. Exactly these two —
# no venue/order/promotion tool is registered.
_TOOL_NAMES = frozenset({CANVAS_READ, CANVAS_CREATE_NODE})

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


def _edge_to_dict(edge: Any) -> dict[str, Any]:
    """Semantic view of a graph edge — lineage relation only, no render wiring."""

    return {
        "edge_ref": edge.edge_ref,
        "from_qro_id": edge.from_qro_id,
        "to_qro_id": edge.to_qro_id,
        "relation_type": edge.relation_type,
    }


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

    Returns ``{nodes, edges, count, edge_count}``. ``nodes`` are the SEMANTIC
    projection records (type, owner, status axes, lineage, evidence/mathematical
    refs) — what the agent reasons over, NOT the frontend's pixel-layout nodes.
    ``edges`` are lineage relations (``from_qro_id``/``to_qro_id``/``relation_type``)
    restricted to edges whose both endpoints are in the filtered node set, so an
    ``owner`` filter isolates edges too.

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
    # Lineage edges, scoped to the projected QRO set: an edge surfaces only when
    # BOTH endpoints are in the (owner-)filtered node set. So owner-scoping the
    # nodes transitively isolates the edges — owner A never sees an edge that
    # touches owner B's QRO. Mirrors the endpoint's edge gate (main.py:15544).
    projected_ids = {record.qro_id for record in records}
    edges = [
        _edge_to_dict(edge)
        for edge in store.graph_edges()
        if edge.from_qro_id in projected_ids and edge.to_qro_id in projected_ids
    ]
    return {
        "nodes": [_projection_to_dict(r) for r in records],
        "edges": edges,
        "count": len(records),
        "edge_count": len(edges),
    }


def _agent_str_field(args: dict[str, Any], key: str) -> str:
    value = args.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ResearchGraphError(f"canvas_create_node: field {key!r} must be a non-empty string")
    return value.strip()


def _agent_tuple_field(args: dict[str, Any], key: str) -> tuple[str, ...]:
    value = args.get(key)
    if not isinstance(value, list) or not value:
        raise ResearchGraphError(f"canvas_create_node: field {key!r} must be a non-empty list of strings")
    out = tuple(str(x).strip() for x in value if isinstance(x, str) and str(x).strip())
    if not out:
        raise ResearchGraphError(f"canvas_create_node: field {key!r} must contain non-empty entries")
    return out


def canvas_create_node(arguments: dict[str, Any] | None = None) -> dict[str, Any]:
    """Create an OFFLINE research-graph draft node on the canvas (agent write).

    Layered responsibility (Axis F = agent-provides, per user D-EPIC-PRIORITY/A.2):
    - The AGENT supplies the RESEARCH CONTENT: ``qro_type``, ``market``, ``universe``,
      ``horizon``, ``frequency``, and the mandatory articulated fields ``assumptions``
      / ``known_limits`` / ``failure_modes`` / ``validation_plan`` (each a non-empty
      list). Optional ``input_contract``/``output_contract`` dicts, optional
      ``lineage`` refs. The tool never synthesizes placeholder research content —
      an omitted field is rejected (``QRORecord.__post_init__`` + these validators),
      so the mandatory-field gate stays real (not decorative).
    - The TOOL forces the SAFE platform envelope: ``owner = QB_OWNER`` (process env —
      the agent cannot request a foreign owner; there is no ``owner`` argument),
      ``actor = AGENT``, a fresh DRAFT/UNTESTED/OFFLINE draft with
      ``allowed_environment = OFFLINE``, ``version = 1``, a content-derived
      ``implementation_hash``. It never accepts owner/actor/status/qro_id/version.
    - The STORE independently enforces the L-D red-line (CANVAS create → OFFLINE only)
      and owner==actor, so even a bug here cannot land a live node or a foreign owner.
    """

    args = arguments or {}
    owner = str(os.environ.get("QB_OWNER", "")).strip()
    if not owner:
        raise ResearchGraphError("canvas_create_node: QB_OWNER absent in agent env — no write identity")

    qro_type = _agent_str_field(args, "qro_type")
    market = _agent_str_field(args, "market")
    universe = _agent_str_field(args, "universe")
    horizon = _agent_str_field(args, "horizon")
    frequency = _agent_str_field(args, "frequency")
    assumptions = _agent_tuple_field(args, "assumptions")
    known_limits = _agent_tuple_field(args, "known_limits")
    failure_modes = _agent_tuple_field(args, "failure_modes")
    validation_plan = _agent_tuple_field(args, "validation_plan")
    input_contract = args["input_contract"] if isinstance(args.get("input_contract"), dict) else {}
    output_contract = args["output_contract"] if isinstance(args.get("output_contract"), dict) else {}
    extra_lineage = tuple(
        x.strip() for x in (args.get("lineage") or []) if isinstance(x, str) and x.strip()
    )

    implementation_hash = "canvas_agent_draft:" + content_hash(
        {
            "qro_type": qro_type,
            "owner": owner,
            "market": market,
            "universe": universe,
            "horizon": horizon,
            "frequency": frequency,
            "assumptions": assumptions,
            "known_limits": known_limits,
            "failure_modes": failure_modes,
            "validation_plan": validation_plan,
            "input_contract": input_contract,
            "output_contract": output_contract,
        }
    )

    qro = QRORecord(
        qro_type=qro_type,
        owner=owner,
        actor=ActorSource.AGENT.value,
        input_contract=input_contract,
        output_contract=output_contract,
        market=market,
        universe=universe,
        horizon=horizon,
        frequency=frequency,
        lineage=("canvas_agent_draft", *extra_lineage),
        implementation_hash=implementation_hash,
        assumptions=assumptions,
        known_limits=known_limits,
        failure_modes=failure_modes,
        validation_plan=validation_plan,
        definition_status=DefinitionStatus.DRAFT,
        evidence_status=EvidenceStatus.UNTESTED,
        governance_status=GovernanceStatus.UNREVIEWED,
        runtime_status=RuntimeStatus.OFFLINE,
        permission="canvas.agent.create:agent",
        allowed_environment=RuntimeStatus.OFFLINE,
        version=1,
    )
    command = ResearchGraphCommand(
        source=EntrySource.CANVAS,
        command_type="upsert_qro",
        actor_source=ActorSource.AGENT,
        actor=owner,  # store requires command.actor == qro.owner (spine.py:1685)
        payload={"qro": qro},
    )
    command_id = _store().apply(command)
    return {
        "qro_id": qro.qro_id,
        "version": qro.version,
        "command_id": command_id,
        "projection_node_id": f"canvas_node:qro:{qro.qro_id}",
        "owner": owner,
        "runtime_status": qro.runtime_status.value,
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

# Axis F: the agent supplies all research content; there is deliberately NO
# ``owner``/``actor``/``status``/``runtime_status``/``qro_id``/``version`` property —
# the tool forces the safe envelope (owner=QB_OWNER, AGENT/DRAFT/OFFLINE) and the
# store re-enforces L-D. The four articulated lists are ``required`` so an agent
# cannot mint a research node without stating its assumptions/limits/failure
# modes/validation plan (the mandatory-field gate is real, not decorative).
_NONEMPTY_STR_LIST = {"type": "array", "items": {"type": "string"}, "minItems": 1}
_CANVAS_CREATE_NODE_INPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "qro_type": {"type": "string", "description": "QRO type (e.g. factor, model, strategy)."},
        "market": {"type": "string", "description": "Market the node targets."},
        "universe": {"type": "string", "description": "Universe / instrument set."},
        "horizon": {"type": "string", "description": "Research horizon."},
        "frequency": {"type": "string", "description": "Data / rebalancing frequency."},
        "assumptions": {**_NONEMPTY_STR_LIST, "description": "Stated assumptions (>=1)."},
        "known_limits": {**_NONEMPTY_STR_LIST, "description": "Known limitations (>=1)."},
        "failure_modes": {**_NONEMPTY_STR_LIST, "description": "Failure modes (>=1)."},
        "validation_plan": {**_NONEMPTY_STR_LIST, "description": "Validation plan (>=1)."},
        "input_contract": {"type": "object", "description": "Optional input contract."},
        "output_contract": {"type": "object", "description": "Optional output contract."},
        "lineage": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Optional extra lineage refs (canvas_agent_draft is always prepended).",
        },
    },
    "required": [
        "qro_type",
        "market",
        "universe",
        "horizon",
        "frequency",
        "assumptions",
        "known_limits",
        "failure_modes",
        "validation_plan",
    ],
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
                "Read the research-graph canvas projection (read-only). Returns "
                "matching nodes (type, owner, status axes, lineage, evidence/"
                "mathematical refs) plus the lineage edges between them. An "
                "owner filter isolates both nodes and edges. Cannot mutate the "
                "graph or touch keys/venues."
            ),
            inputSchema=_CANVAS_READ_INPUT_SCHEMA,
        ),
        types.Tool(
            name=CANVAS_CREATE_NODE,
            description=(
                "Create one OFFLINE research-graph draft node on the canvas. You "
                "supply the research content (qro_type, market, universe, horizon, "
                "frequency, and the required assumptions/known_limits/failure_modes/"
                "validation_plan lists). Owner is fixed by the environment and the "
                "node is always a DRAFT/UNTESTED/OFFLINE draft — you cannot set "
                "owner, status, runtime, or promote to live. Cannot touch keys/venues."
            ),
            inputSchema=_CANVAS_CREATE_NODE_INPUT_SCHEMA,
        ),
    ]


def _dispatch(name: str, arguments: dict[str, Any] | None) -> dict[str, Any]:
    """L-A dispatcher: only ``canvas_read`` is reachable; everything else errors."""

    if name not in _TOOL_NAMES:
        raise ValueError(f"unknown tool: {name!r} (agent tool reach is {sorted(_TOOL_NAMES)})")
    if name == CANVAS_READ:
        return canvas_read(arguments)
    if name == CANVAS_CREATE_NODE:
        return canvas_create_node(arguments)
    # Unreachable while every name in _TOOL_NAMES is routed above; guards against
    # silent drift if a name is added to the set without a handler.
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
