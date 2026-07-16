"""L-D store-level red-line: CANVAS upsert is OFFLINE-only (agent write 命门).

The canvas is a research-intent / draft surface. paper/testnet/live are runtime
states reached only through governed promotion — never by direct creation on the
canvas. Enforced at the STORE layer (ResearchGraphStore.apply CANVAS branch), so
even a malicious/buggy canvas_create_node (M5b) tool cannot land a live node. This
is the store foundation the agent write tool builds on.

Mutation contract (RULES §2 种坏门必抓):
- Delete/invert the ``runtime_status != OFFLINE`` guard in spine.py's CANVAS
  branch → the LIVE/TESTNET/PAPER rejection tests go RED.
"""

from __future__ import annotations

import pytest

from app.research_os.spine import (
    ActorSource,
    EntrySource,
    QRORecord,
    ResearchGraphCommand,
    ResearchGraphError,
    ResearchGraphStore,
    RuntimeStatus,
)


def _qro(owner: str, runtime: RuntimeStatus) -> QRORecord:
    return QRORecord(
        qro_type="Factor",
        owner=owner,
        actor=owner,
        input_contract={},
        output_contract={},
        market="equity",
        universe="hs300",
        horizon="1d",
        frequency="1d",
        lineage=("f",),
        implementation_hash=f"impl:{runtime.value}",
        assumptions=("prices adjusted",),
        known_limits=("capacity unverified",),
        failure_modes=("data stale",),
        validation_plan=("walk-forward",),
        runtime_status=runtime,
    )


def _canvas_cmd(qro: QRORecord, *, actor: str) -> ResearchGraphCommand:
    return ResearchGraphCommand(
        source=EntrySource.CANVAS,
        command_type="upsert_qro",
        actor_source=ActorSource.AGENT,
        actor=actor,
        payload={"qro": qro},
    )


@pytest.mark.parametrize(
    "runtime",
    [
        pytest.param(RuntimeStatus.LIVE, id="rt_live"),
        # custom id avoids the conftest "testnet" keyword auto-skip (conftest.py:658);
        # this checks store REJECTION only — it places no real testnet order.
        pytest.param(RuntimeStatus.TESTNET, id="rt_tnet"),
        pytest.param(RuntimeStatus.PAPER, id="rt_paper"),
        pytest.param(RuntimeStatus.SUSPENDED, id="rt_suspended"),
        pytest.param(RuntimeStatus.RETIRED, id="rt_retired"),
    ],
)
def test_canvas_upsert_rejects_non_offline_runtime(runtime):
    store = ResearchGraphStore()
    qro = _qro("alice", runtime)
    with pytest.raises(ResearchGraphError):
        store.apply(_canvas_cmd(qro, actor="alice"))
    # Nothing landed — the store is unchanged.
    with pytest.raises(KeyError):
        store.qro(qro.qro_id)


def test_canvas_upsert_accepts_offline():
    store = ResearchGraphStore()
    qro = _qro("alice", RuntimeStatus.OFFLINE)
    store.apply(_canvas_cmd(qro, actor="alice"))
    assert store.qro(qro.qro_id).runtime_status == RuntimeStatus.OFFLINE


def test_canvas_offline_invariant_survives_persistent_replay(tmp_path):
    # The guard must hold on the persistent store's replay path too, not just
    # in-memory apply. A LIVE canvas command must never be replayable into being.
    from app.research_os.spine import PersistentResearchGraphStore

    path = tmp_path / "audit" / "research_graph_commands.jsonl"
    store = PersistentResearchGraphStore(path)
    # OFFLINE lands and survives a fresh replay.
    ok = _qro("alice", RuntimeStatus.OFFLINE)
    store.apply(_canvas_cmd(ok, actor="alice"))
    replayed = PersistentResearchGraphStore(path)
    assert replayed.qro(ok.qro_id).runtime_status == RuntimeStatus.OFFLINE
    # LIVE is rejected at apply time, so it never reaches the log to be replayed.
    with pytest.raises(ResearchGraphError):
        store.apply(_canvas_cmd(_qro("alice", RuntimeStatus.LIVE), actor="alice"))


def test_canvas_upsert_still_enforces_owner():
    # The pre-existing owner guard must remain intact alongside the new OFFLINE guard.
    store = ResearchGraphStore()
    qro = _qro("alice", RuntimeStatus.OFFLINE)
    with pytest.raises(ResearchGraphError):
        store.apply(_canvas_cmd(qro, actor="bob"))  # actor != qro.owner


def test_canvas_edit_of_nonoffline_asset_preserves_runtime():
    # Design B (cross-vendor duet correction): a legit canvas EDIT of an existing
    # non-OFFLINE asset must be ALLOWED as long as it preserves runtime — this is
    # the exact case design A ("all CANVAS → OFFLINE") wrongly regressed
    # (set_canvas_parameter edits a PAPER node via replace(), preserving PAPER).
    from dataclasses import replace

    store = ResearchGraphStore()
    paper = _qro("alice", RuntimeStatus.PAPER)
    # Seed via IDE (not canvas-scoped) so a non-OFFLINE asset exists.
    store.apply(
        ResearchGraphCommand(
            source=EntrySource.IDE,
            command_type="upsert_qro",
            actor_source=ActorSource.USER_MANUAL,
            actor="alice",
            payload={"qro": paper},
        )
    )
    # Edit via CANVAS, preserving runtime + qro_id (mirrors main.py:16183-16199).
    edited = replace(paper, version=paper.version + 1, output_contract={"tuned": "yes"}, qro_id=paper.qro_id)
    store.apply(_canvas_cmd(edited, actor="alice"))  # must be allowed
    assert store.qro(paper.qro_id).runtime_status == RuntimeStatus.PAPER


def test_canvas_edit_cannot_escalate_runtime():
    # But a canvas edit MAY NOT transition runtime OFFLINE→LIVE (promotion is governed).
    from dataclasses import replace

    store = ResearchGraphStore()
    off = _qro("alice", RuntimeStatus.OFFLINE)
    store.apply(_canvas_cmd(off, actor="alice"))
    escalated = replace(off, version=off.version + 1, runtime_status=RuntimeStatus.LIVE, qro_id=off.qro_id)
    with pytest.raises(ResearchGraphError):
        store.apply(_canvas_cmd(escalated, actor="alice"))


def test_canvas_create_rejects_nonoffline_environment():
    # Defense-in-depth (design B add-on): OFFLINE runtime but LIVE allowed_environment
    # (a pre-authorize-live vector) is rejected on create.
    from dataclasses import replace

    store = ResearchGraphStore()
    bad = replace(_qro("alice", RuntimeStatus.OFFLINE), allowed_environment=RuntimeStatus.LIVE)
    with pytest.raises(ResearchGraphError):
        store.apply(_canvas_cmd(bad, actor="alice"))
