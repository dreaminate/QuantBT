"""Behavioral proof for the M5b agent write tool ``canvas_create_node``.

The tool lets the embedded Claude-Code agent create ONE research-graph draft
node. Axis F (user D-CANVAS-NODE-FIELDS): the AGENT supplies all research
content; the TOOL forces the safe envelope (owner=QB_OWNER, AGENT/DRAFT/UNTESTED/
OFFLINE, version=1, content-derived implementation_hash); the STORE re-enforces
the L-D red-line (CANVAS create → OFFLINE only, owner==actor).

These tests exercise the tool's CONTRACT: owner identity comes from the process
env (never from the agent's arguments), the mandatory articulated fields are
really required, the runtime is forced OFFLINE, and a created node is visible to
a separate reader process. The store-level L-D red-line itself (LIVE/TESTNET/
PAPER rejection, edit-preserve/no-escalate) is proven in
``test_agent_canvas_write_redline.py``.

Mutation contract (RULES §2 种坏门必抓):
- Read owner from ``args`` instead of ``QB_OWNER`` → ``test_agent_cannot_choose_foreign_owner`` RED.
- Drop a mandatory-field validator → ``test_missing_mandatory_field_rejected`` RED.
- Force runtime to anything but OFFLINE → ``test_agent_cannot_mint_live`` RED.
- Skip the ``QB_OWNER`` presence check → ``test_qb_owner_absent_rejected`` RED.
"""

from __future__ import annotations

import pytest

from app.research_os.spine import (
    ActorSource,
    DefinitionStatus,
    EvidenceStatus,
    ResearchGraphError,
    RuntimeStatus,
)

# A complete, valid argument bag (agent-supplied research content).
_VALID_ARGS = {
    "qro_type": "Factor",
    "market": "equity",
    "universe": "hs300",
    "horizon": "1d",
    "frequency": "1d",
    "assumptions": ["prices are split/dividend adjusted"],
    "known_limits": ["capacity unverified"],
    "failure_modes": ["data goes stale intraday"],
    "validation_plan": ["walk-forward OOS"],
}

_MANDATORY = (
    "qro_type",
    "market",
    "universe",
    "horizon",
    "frequency",
    "assumptions",
    "known_limits",
    "failure_modes",
    "validation_plan",
)


@pytest.fixture
def canvas(tmp_path, monkeypatch):
    """Point the module store at an isolated log and set the agent's QB_OWNER.

    ``_store()`` is a module-global singleton bound to
    ``RESEARCH_GRAPH_COMMANDS_PATH``. We repoint both at a tmp log and reset the
    singleton so each test writes to a fresh, isolated graph. ``QB_OWNER`` is the
    spawn-env write identity the tool reads (there is no ``owner`` argument).
    """

    from app.agent_mcp import server

    path = tmp_path / "audit" / "research_graph_commands.jsonl"
    monkeypatch.setattr(server, "RESEARCH_GRAPH_COMMANDS_PATH", path)
    monkeypatch.setattr(server, "_STORE", None)
    monkeypatch.setenv("QB_OWNER", "alice")
    return server


def test_create_lands_offline_draft(canvas):
    """Happy path: a full arg bag lands an OFFLINE DRAFT/UNTESTED node owned by QB_OWNER."""

    result = canvas.canvas_create_node(dict(_VALID_ARGS))

    assert set(result) == {
        "qro_id",
        "version",
        "command_id",
        "projection_node_id",
        "owner",
        "runtime_status",
    }
    assert result["owner"] == "alice"
    assert result["version"] == 1
    assert result["runtime_status"] == "offline"
    assert result["projection_node_id"] == f"canvas_node:qro:{result['qro_id']}"

    rec = canvas._store().qro(result["qro_id"])
    assert rec.owner == "alice"
    assert rec.actor == ActorSource.AGENT.value
    assert rec.runtime_status == RuntimeStatus.OFFLINE
    assert rec.allowed_environment == RuntimeStatus.OFFLINE
    assert rec.definition_status == DefinitionStatus.DRAFT
    assert rec.evidence_status == EvidenceStatus.UNTESTED
    assert rec.implementation_hash.startswith("canvas_agent_draft:")
    assert rec.lineage[0] == "canvas_agent_draft"


def test_qb_owner_absent_rejected(canvas, monkeypatch):
    """No write identity in the env → the tool refuses to mint an ownerless node."""

    monkeypatch.delenv("QB_OWNER", raising=False)
    with pytest.raises(ResearchGraphError):
        canvas.canvas_create_node(dict(_VALID_ARGS))


def test_qb_owner_blank_rejected(canvas, monkeypatch):
    """A blank/whitespace QB_OWNER is not a valid identity either."""

    monkeypatch.setenv("QB_OWNER", "   ")
    with pytest.raises(ResearchGraphError):
        canvas.canvas_create_node(dict(_VALID_ARGS))


def test_missing_mandatory_field_rejected(canvas):
    """Every mandatory articulated field is really required — omission is rejected.

    This keeps the assumptions/known_limits/failure_modes/validation_plan gate
    real: the agent cannot mint a research node without stating them.
    """

    for field in _MANDATORY:
        bad = dict(_VALID_ARGS)
        del bad[field]
        with pytest.raises(ResearchGraphError):
            canvas.canvas_create_node(bad)


def test_empty_or_blank_list_field_rejected(canvas):
    """An empty list, or a list of only-blank strings, is not a stated field."""

    for value in ([], ["", "   "]):
        bad = dict(_VALID_ARGS)
        bad["assumptions"] = value
        with pytest.raises(ResearchGraphError):
            canvas.canvas_create_node(bad)


def test_agent_cannot_choose_foreign_owner(canvas):
    """Owner is fixed to QB_OWNER; an ``owner`` in the args is ignored, not honored.

    Mutation target: if the handler read owner from args, the landed node would be
    owned by "bob" and this test would go RED.
    """

    args = dict(_VALID_ARGS)
    args["owner"] = "bob"  # attacker-supplied — must have NO effect
    result = canvas.canvas_create_node(args)
    assert result["owner"] == "alice"
    assert canvas._store().qro(result["qro_id"]).owner == "alice"


def test_agent_cannot_mint_live(canvas):
    """A runtime_status/allowed_environment in the args is ignored — forced OFFLINE.

    The tool never reads runtime from args; even if it did, the store's L-D guard
    rejects a non-OFFLINE canvas create. Here we prove the tool layer forces OFFLINE.
    """

    args = dict(_VALID_ARGS)
    args["runtime_status"] = "live"
    args["allowed_environment"] = "live"
    result = canvas.canvas_create_node(args)
    assert result["runtime_status"] == "offline"
    assert canvas._store().qro(result["qro_id"]).runtime_status == RuntimeStatus.OFFLINE


def test_created_node_visible_to_separate_reader(canvas):
    """A created node is visible via canvas_read AND to a fresh reader store.

    The fresh ``PersistentResearchGraphStore`` at the same log path simulates the
    separate reader process (the embedded agent reads through its own process),
    proving the write is durable and cross-process visible — not just in-memory.
    """

    result = canvas.canvas_create_node(dict(_VALID_ARGS))

    read = canvas.canvas_read({"owner": "alice"})
    assert result["qro_id"] in {n["qro_id"] for n in read["nodes"]}

    from app.research_os.spine import PersistentResearchGraphStore

    fresh = PersistentResearchGraphStore(canvas.RESEARCH_GRAPH_COMMANDS_PATH)
    assert fresh.qro(result["qro_id"]).owner == "alice"
    assert fresh.qro(result["qro_id"]).runtime_status == RuntimeStatus.OFFLINE


def test_dispatch_routes_create_node(canvas):
    """The M5b dispatcher actually routes canvas_create_node to the handler.

    Before M5b the dispatcher raised "no handler wired"; this proves the wiring.
    """

    result = canvas._dispatch("canvas_create_node", dict(_VALID_ARGS))
    assert result["runtime_status"] == "offline"
    assert result["owner"] == "alice"


def test_two_creates_are_distinct_nodes(canvas):
    """Distinct research content → distinct qro_ids (content-derived, no collision)."""

    a = canvas.canvas_create_node(dict(_VALID_ARGS))
    second = dict(_VALID_ARGS)
    second["universe"] = "csi500"
    b = canvas.canvas_create_node(second)
    assert a["qro_id"] != b["qro_id"]
    store = canvas._store()
    assert store.qro(a["qro_id"]).universe == "hs300"
    assert store.qro(b["qro_id"]).universe == "csi500"
