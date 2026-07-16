"""End-to-end functional proof for the no-key agent canvas_read (agent M2).

M1 proved the red-line FLOOR (no-key import isolation, registry, race). M2 proves
the FUNCTION works against real seeded graph data:
- owner A/B isolation (an owner filter never leaks another owner's nodes/edges),
- cross-process visibility (the agent's store instance sees appends made by a
  SEPARATE store instance — the real API-writes / agent-reads topology),
- lineage edges scoped to the projected node set.

Seeds go through spine's own store API (upsert_qro / record_graph_edge commands),
exactly as app.main writes them, so this exercises the real projection path.

Mutation contract (RULES §2 种坏门必抓):
- Drop the ``edge.from/to in projected_ids`` gate in ``canvas_read`` → the
  owner-B edge-isolation assertion goes RED (B would see A's edge).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.research_os.spine import (
    ActorSource,
    EntrySource,
    PersistentResearchGraphStore,
    QRORecord,
    ResearchGraphCommand,
    ResearchGraphEdgeRecord,
)


def _seed_qro(store: PersistentResearchGraphStore, owner: str, tag: str) -> QRORecord:
    """Upsert one Factor QRO for ``owner``; ``tag`` makes the identity unique."""

    qro = QRORecord(
        qro_type="Factor",
        owner=owner,
        actor=owner,
        input_contract={"input": f"factor_{tag}"},
        output_contract={"output": f"factor_{tag}"},
        market="equity",
        universe="hs300",
        horizon="1d",
        frequency="1d",
        lineage=(f"factor_{tag}",),
        implementation_hash=f"implementation:factor:{tag}",
        assumptions=("prices are adjusted",),
        known_limits=("capacity is unverified",),
        failure_modes=("data can be stale",),
        validation_plan=("run walk-forward validation",),
    )
    store.apply(
        ResearchGraphCommand(
            source=EntrySource.CANVAS,
            command_type="upsert_qro",
            actor_source=ActorSource.USER_MANUAL,
            actor=owner,
            payload={"qro": qro},
        )
    )
    return qro


def _seed_edge(
    store: PersistentResearchGraphStore, frm: QRORecord, to: QRORecord, actor: str
) -> ResearchGraphEdgeRecord:
    edge = ResearchGraphEdgeRecord(
        command_ref=f"cmd:edge:{frm.qro_id}:{to.qro_id}",
        from_qro_id=frm.qro_id,
        to_qro_id=to.qro_id,
        relation_type="lineage",
        source_desk="factor",
        actor_source=ActorSource.USER_MANUAL.value,
        actor=actor,
        canonical_command_ref=f"canon:edge:{frm.qro_id}",
        audit_ref=f"audit:edge:{frm.qro_id}",
    )
    store.apply(
        ResearchGraphCommand(
            source=EntrySource.CANVAS,
            command_type="record_graph_edge",
            actor_source=ActorSource.USER_MANUAL,
            actor=actor,
            payload={"edge": edge},
        )
    )
    return edge


@pytest.fixture()
def isolated_agent_store(monkeypatch, tmp_path: Path):
    """Point the agent server at an isolated JSONL + a cold singleton.

    Returns ``(seeding_store, path)`` where ``seeding_store`` is a SEPARATE store
    instance writing the same log the agent reads — modelling the API-writer /
    agent-reader split.
    """

    from app.agent_mcp import server

    path = tmp_path / "audit" / "research_graph_commands.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(server, "RESEARCH_GRAPH_COMMANDS_PATH", path)
    monkeypatch.setattr(server, "_STORE", None)
    seeding_store = PersistentResearchGraphStore(path)
    return seeding_store, path


def test_owner_filter_isolates_nodes(isolated_agent_store):
    """canvas_read(owner=X) returns only X's nodes; no filter returns both."""

    from app.agent_mcp import server

    seeding_store, _ = isolated_agent_store
    _seed_qro(seeding_store, "alice", "a1")
    _seed_qro(seeding_store, "bob", "b1")

    alice = server.canvas_read({"owner": "alice"})
    bob = server.canvas_read({"owner": "bob"})
    everyone = server.canvas_read({})

    assert {n["owner"] for n in alice["nodes"]} == {"alice"}
    assert {n["owner"] for n in bob["nodes"]} == {"bob"}
    assert {n["owner"] for n in everyone["nodes"]} == {"alice", "bob"}
    assert everyone["count"] == 2


def test_cross_process_append_becomes_visible(isolated_agent_store):
    """The agent's store instance sees a QRO appended by a SEPARATE instance."""

    from app.agent_mcp import server

    seeding_store, _ = isolated_agent_store
    _seed_qro(seeding_store, "alice", "first")

    first = server.canvas_read({})
    assert first["count"] == 1

    # A different process/instance appends after the agent's first read.
    _seed_qro(seeding_store, "alice", "second")

    second = server.canvas_read({})
    assert second["count"] == 2, "agent store did not pick up the cross-process append (refresh broken)"


def test_lineage_edges_scoped_to_owner(isolated_agent_store):
    """An edge between two of alice's QROs is visible to alice, never to bob."""

    from app.agent_mcp import server

    seeding_store, _ = isolated_agent_store
    a1 = _seed_qro(seeding_store, "alice", "edge_a1")
    a2 = _seed_qro(seeding_store, "alice", "edge_a2")
    _seed_qro(seeding_store, "bob", "edge_b1")
    edge = _seed_edge(seeding_store, a1, a2, actor="alice")

    alice = server.canvas_read({"owner": "alice"})
    bob = server.canvas_read({"owner": "bob"})

    alice_edge_refs = {e["edge_ref"] for e in alice["edges"]}
    assert edge.edge_ref in alice_edge_refs, "alice must see her own lineage edge"
    assert alice["edges"][0]["relation_type"] == "lineage"
    assert alice["edges"][0]["from_qro_id"] == a1.qro_id
    # bob's projection excludes both endpoints → the edge must not leak.
    assert bob["edge_count"] == 0, "owner-B leaked an edge touching owner-A QROs"


def test_edges_present_shape(isolated_agent_store):
    """Edge dicts carry exactly the semantic lineage fields (no render wiring)."""

    from app.agent_mcp import server

    seeding_store, _ = isolated_agent_store
    a1 = _seed_qro(seeding_store, "alice", "shape1")
    a2 = _seed_qro(seeding_store, "alice", "shape2")
    _seed_edge(seeding_store, a1, a2, actor="alice")

    result = server.canvas_read({})
    assert result["edge_count"] == 1
    assert set(result["edges"][0].keys()) == {
        "edge_ref",
        "from_qro_id",
        "to_qro_id",
        "relation_type",
    }
