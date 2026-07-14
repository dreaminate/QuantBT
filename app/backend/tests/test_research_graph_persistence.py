from __future__ import annotations

import json
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.auth import require_user_dependency
from app.research_os import (
    ActorSource,
    CanvasParameterValueRecord,
    CanvasMutationRecord,
    DefinitionStatus,
    EntrySource,
    EvidenceStatus,
    GraphPatchApplicationRecord,
    PersistentCompilerIRStore,
    PersistentGoalEntrypointCoverageRegistry,
    PersistentResearchGraphStore,
    QROTombstoneRecord,
    QRORecord,
    QROType,
    ResearchGraphCommand,
    ResearchGraphEdgeDeletionRecord,
    ResearchGraphEdgeRecord,
    ResearchGraphError,
    RuntimeStatus,
    make_canvas_layout_record,
)
from app.research_os.entrypoint_evidence import PersistentEntrypointEvidenceRegistry
from app.research_os.goal_proof_ledger import GoalProofLedger
from app.research_os.goal_validation_receipts import (
    PersistentGoalValidationReceiptRegistry,
)
from app.research_os.ref_resolution import build_real_ref_resolver


def _install_goal_proof_stores(main, tmp_path, monkeypatch, graph):  # noqa: ANN001
    proof_ledger = GoalProofLedger(tmp_path / "goal_proof_ledger")
    compiler = PersistentCompilerIRStore(
        tmp_path / "compiler_ir.jsonl",
        proof_ledger=proof_ledger,
        legacy_read_only=True,
    )
    validations = PersistentGoalValidationReceiptRegistry(
        tmp_path / "goal_validation_receipts.jsonl",
        proof_ledger=proof_ledger,
        legacy_read_only=True,
    )
    evidence = PersistentEntrypointEvidenceRegistry(
        tmp_path / "entrypoint_evidence.jsonl",
        research_graph_store=graph,
        compiler_store=compiler,
        validation_receipt_registry=validations,
        proof_ledger=proof_ledger,
        legacy_read_only=True,
    )
    coverage = PersistentGoalEntrypointCoverageRegistry(
        tmp_path / "goal_entrypoint_coverage.jsonl",
        proof_ledger=proof_ledger,
        legacy_read_only=True,
    )
    coverage.set_ref_resolver(
        build_real_ref_resolver(
            research_graph_store=graph,
            lifecycle_registry=main.ASSET_LIFECYCLE_REGISTRY,
            governance_registry=main.MODEL_GOVERNANCE_REGISTRY,
            rag_index=main.RESEARCH_ASSET_RAG_INDEX,
            spine_chain_registry=main.MATHEMATICAL_SPINE_CHAIN_REGISTRY,
            compiler_store=compiler,
            document_store=main.DOCUMENT_INTELLIGENCE_STORE,
            goal_validation_receipt_registry=validations,
            platform_source_evidence_registry=evidence,
        )
    )
    monkeypatch.setattr(main, "RESEARCH_GRAPH_STORE", graph)
    monkeypatch.setattr(main, "COMPILER_IR_STORE", compiler)
    monkeypatch.setattr(main, "GOAL_VALIDATION_RECEIPT_REGISTRY", validations)
    monkeypatch.setattr(main, "ENTRYPOINT_EVIDENCE_REGISTRY", evidence)
    monkeypatch.setattr(main, "GOAL_ENTRYPOINT_COVERAGE_REGISTRY", coverage)
    return compiler, coverage


@pytest.fixture(autouse=True)
def _isolate_compiler_and_goal_coverage_stores(tmp_path, monkeypatch):  # noqa: ANN001
    from app import main

    _install_goal_proof_stores(
        main,
        tmp_path,
        monkeypatch,
        main.RESEARCH_GRAPH_STORE,
    )


def _qro(**overrides) -> QRORecord:
    data = dict(
        qro_type=QROType.STRATEGY_BOOK,
        owner="dreaminate",
        actor=ActorSource.USER_MANUAL,
        input_contract={"strategy_id": "strategy_demo", "code_hash": "hash_code"},
        output_contract={"strategy_book_ref": "strategy:demo"},
        market="crypto",
        universe="BTCUSDT",
        horizon="30d",
        frequency="1d",
        lineage=("ide", "strategy", "save"),
        implementation_hash="strategy:hash_code",
        assumptions=("strategy source was saved before graph write",),
        known_limits=("persistent test fixture only",),
        failure_modes=("command log corruption hides audit history",),
        validation_plan=("reload graph command store",),
        definition_status=DefinitionStatus.IMPLEMENTED,
        evidence_status=EvidenceStatus.EXPLORATORY,
        runtime_status=RuntimeStatus.OFFLINE,
        permission="ide.strategy:user_manual",
        allowed_environment=RuntimeStatus.OFFLINE,
    )
    data.update(overrides)
    return QRORecord(**data)


def _command(qro: QRORecord) -> ResearchGraphCommand:
    return ResearchGraphCommand(
        source=EntrySource.IDE,
        command_type="upsert_qro",
        actor_source=ActorSource.USER_MANUAL,
        actor="dreaminate",
        payload={"qro": qro},
        evidence_refs=("unit:persistence",),
    )


def _canvas_mutation(**overrides) -> CanvasMutationRecord:
    data = dict(
        command_ref="canvas_command:update_strategy:001",
        source_desk="strategy",
        actor_source="user_manual",
        actor="dreaminate",
        target_asset_type="StrategyBook",
        target_ref="strategy:demo",
        field_path="legs.0.signal_ref",
        operation="set_ref",
        canonical_command_ref="research_graph_command:rgcmd_strategy_update",
        audit_ref="audit:canvas:001",
        value_ref="signal:trend:v1",
        value_hash="hash_signal_trend_v1",
        evidence_refs=("unit:canvas_mutation",),
    )
    data.update(overrides)
    return CanvasMutationRecord(**data)


def _graph_edge(**overrides) -> ResearchGraphEdgeRecord:
    data = dict(
        command_ref="canvas_command:graph_edge:001",
        from_qro_id="qro_from",
        to_qro_id="qro_to",
        relation_type="canvas_connect",
        source_desk="strategy",
        actor_source="user_manual",
        actor="dreaminate",
        canonical_command_ref="research_graph_command:graph_edge:001",
        audit_ref="audit:graph_edge:001",
        evidence_refs=("unit:graph_edge",),
    )
    data.update(overrides)
    return ResearchGraphEdgeRecord(**data)


def _graph_edge_deletion(**overrides) -> ResearchGraphEdgeDeletionRecord:
    data = dict(
        command_ref="canvas_command:graph_edge_delete:001",
        edge_ref="rgedge_to_delete",
        source_desk="strategy",
        actor_source="user_manual",
        actor="dreaminate",
        canonical_command_ref="research_graph_command:graph_edge_delete:001",
        audit_ref="audit:graph_edge_delete:001",
        evidence_refs=("unit:graph_edge_delete",),
    )
    data.update(overrides)
    return ResearchGraphEdgeDeletionRecord(**data)


def _qro_tombstone(**overrides) -> QROTombstoneRecord:
    data = dict(
        command_ref="canvas_command:qro_tombstone:001",
        qro_id="qro_to_tombstone",
        source_desk="strategy",
        actor_source="user_manual",
        actor="dreaminate",
        canonical_command_ref="research_graph_command:qro_tombstone:001",
        audit_ref="audit:qro_tombstone:001",
        evidence_refs=("unit:qro_tombstone",),
    )
    data.update(overrides)
    return QROTombstoneRecord(**data)


def _graph_patch_application(**overrides) -> GraphPatchApplicationRecord:
    data = dict(
        command_ref="canvas_command:graph_patch:001",
        target_qro_id="qro_patch_target",
        patch_kind="ghost",
        patch_ref="canvas_patch:ghost:strategy:qro_patch_target:001",
        patch_hash="hash_canvas_patch_001",
        source_desk="strategy",
        actor_source="user_manual",
        actor="dreaminate",
        canonical_command_ref="research_graph_command:graph_patch:001",
        audit_ref="audit:graph_patch:001",
        evidence_refs=("unit:graph_patch",),
    )
    data.update(overrides)
    return GraphPatchApplicationRecord(**data)


def _canvas_parameter_value(**overrides) -> CanvasParameterValueRecord:
    data = dict(
        command_ref="canvas_command:param_value:001",
        target_qro_id="qro_param_target",
        target_asset_type="StrategyBook",
        param_key="turnover",
        param_value="45%/w",
        source_desk="strategy",
        actor_source="user_manual",
        actor="dreaminate",
        canonical_command_ref="research_graph_command:param_value:001",
        audit_ref="audit:param_value:001",
        evidence_refs=("unit:param_value",),
    )
    data.update(overrides)
    return CanvasParameterValueRecord(**data)


def test_persistent_research_graph_store_replays_qro_commands(tmp_path):
    path = tmp_path / "research_graph_commands.jsonl"
    store = PersistentResearchGraphStore(path)
    qro = _qro()
    command = _command(qro)

    command_id = store.apply(command)

    reloaded = PersistentResearchGraphStore(path)
    assert [cmd.command_id for cmd in reloaded.commands()] == [command_id]
    persisted_qro = reloaded.qro(qro.qro_id)
    assert persisted_qro.qro_id == qro.qro_id
    assert persisted_qro.input_contract["code_hash"] == "hash_code"
    assert persisted_qro.lineage == ("ide", "strategy", "save")
    assert persisted_qro.status_axes()["definition"] == "implemented"
    assert persisted_qro.status_axes()["evidence"] == "exploratory"
    [projection] = reloaded.projection_index(qro_type="StrategyBook", evidence_status="exploratory")
    assert projection.qro_id == qro.qro_id
    assert projection.command_id == command_id
    assert projection.input_contract_keys == ("code_hash", "strategy_id")
    assert projection.output_contract_keys == ("strategy_book_ref",)
    assert projection.input_contract_hash
    assert "hash_code" not in json.dumps(projection.to_audit_dict())


def test_persistent_research_graph_store_preserves_nested_contract_shape_across_refresh(tmp_path):
    path = tmp_path / "research_graph_commands.jsonl"
    store = PersistentResearchGraphStore(path)
    qro = _qro(
        input_contract={
            "symbols": ("BTCUSDT", "ETHUSDT"),
            "nested": {"validation_refs": ("validation:one", "validation:two")},
        },
        output_contract={"signal_refs": ("signal:one",)},
    )
    command = _command(qro)

    store.apply(command)
    [before_refresh] = store.commands()
    store.refresh()
    [after_refresh] = store.commands()

    assert qro.input_contract["symbols"] == ["BTCUSDT", "ETHUSDT"]
    assert qro.input_contract["nested"]["validation_refs"] == [
        "validation:one",
        "validation:two",
    ]
    assert qro.output_contract["signal_refs"] == ["signal:one"]
    assert after_refresh == before_refresh == command
    assert store.qro(qro.qro_id) == qro


def test_persistent_research_graph_store_replays_canvas_mutation_commands(tmp_path):
    path = tmp_path / "research_graph_commands.jsonl"
    store = PersistentResearchGraphStore(path)
    qro = _qro()
    store.apply(_command(qro))
    mutation = _canvas_mutation(target_ref=qro.qro_id)
    command = ResearchGraphCommand(
        source=EntrySource.CANVAS,
        command_type="record_canvas_mutation",
        actor_source=ActorSource.USER_MANUAL,
        actor="dreaminate",
        payload={"mutation": mutation},
        evidence_refs=mutation.evidence_refs,
    )

    command_id = store.apply(command)

    reloaded = PersistentResearchGraphStore(path)
    assert [cmd.command_id for cmd in reloaded.commands()] == [
        store.commands()[0].command_id,
        command_id,
    ]
    [persisted] = reloaded.canvas_mutations()
    assert persisted.command_ref == "canvas_command:update_strategy:001"
    assert persisted.canonical_command_ref == "research_graph_command:rgcmd_strategy_update"
    assert persisted.audit_ref == "audit:canvas:001"
    [projection] = reloaded.projection_index()
    assert projection.qro_id == qro.qro_id
    assert projection.qro_version == 1


def test_persistent_research_graph_store_rejects_direct_foreign_canvas_command_atomically(tmp_path):
    path = tmp_path / "research_graph_commands.jsonl"
    store = PersistentResearchGraphStore(path)
    qro = _qro(owner="foreign_owner")
    store.apply(
        ResearchGraphCommand(
            source=EntrySource.IDE,
            command_type="upsert_qro",
            actor_source=ActorSource.AGENT,
            actor="agent_runtime",
            payload={"qro": qro},
            evidence_refs=("unit:foreign_owner_fixture",),
        )
    )
    initial_command_ids = [command.command_id for command in store.commands()]
    initial_bytes = path.read_bytes()
    tombstone = _qro_tombstone(qro_id=qro.qro_id, actor="intruder_owner")

    with pytest.raises(ResearchGraphError, match="different owner"):
        store.apply(
            ResearchGraphCommand(
                source=EntrySource.CANVAS,
                command_type="tombstone_qro",
                actor_source=ActorSource.USER_MANUAL,
                actor="intruder_owner",
                payload={"qro_tombstone": tombstone},
                evidence_refs=tombstone.evidence_refs,
            )
        )
    with pytest.raises(ResearchGraphError, match="cannot transfer ownership"):
        store.apply(
            ResearchGraphCommand(
                source=EntrySource.CANVAS,
                command_type="upsert_qro",
                actor_source=ActorSource.USER_MANUAL,
                actor="intruder_owner",
                payload={
                    "qro": _qro(
                        qro_id=qro.qro_id,
                        owner="intruder_owner",
                        implementation_hash="strategy:intruder_transfer",
                    )
                },
                evidence_refs=("unit:foreign_owner_transfer",),
            )
        )

    assert [command.command_id for command in store.commands()] == initial_command_ids
    assert path.read_bytes() == initial_bytes
    assert store.qro(qro.qro_id).version == qro.version
    assert store.qro_tombstones() == []


@pytest.mark.parametrize(
    "command_type",
    (
        "upsert_qro",
        "tombstone_qro",
        "apply_graph_patch",
        "set_canvas_parameter",
        "record_canvas_mutation",
        "record_canvas_layout",
        "record_graph_edge",
        "delete_graph_edge",
    ),
)
def test_direct_canvas_command_owner_boundary_covers_every_graph_mutation_atomically(tmp_path, command_type):
    path = tmp_path / "research_graph_commands.jsonl"
    store = PersistentResearchGraphStore(path)
    owner = "foreign_owner"
    actor = "intruder_owner"
    from_qro = _qro(owner=owner)
    to_qro = _qro(qro_type=QROType.RISK_POLICY, owner=owner)
    for qro in (from_qro, to_qro):
        store.apply(
            ResearchGraphCommand(
                source=EntrySource.IDE,
                command_type="upsert_qro",
                actor_source=ActorSource.AGENT,
                actor="fixture_agent",
                payload={"qro": qro},
                evidence_refs=("unit:canvas_owner_boundary_fixture",),
            )
        )

    edge = _graph_edge(
        from_qro_id=from_qro.qro_id,
        to_qro_id=to_qro.qro_id,
        actor=owner,
    )
    if command_type == "delete_graph_edge":
        store.apply(
            ResearchGraphCommand(
                source=EntrySource.CANVAS,
                command_type="record_graph_edge",
                actor_source=ActorSource.USER_MANUAL,
                actor=owner,
                payload={"edge": edge},
                evidence_refs=edge.evidence_refs,
            )
        )

    records = {
        "upsert_qro": (
            "qro",
            _qro(
                qro_id=from_qro.qro_id,
                owner=actor,
                implementation_hash="strategy:intruder_transfer",
            ),
        ),
        "tombstone_qro": (
            "qro_tombstone",
            _qro_tombstone(qro_id=from_qro.qro_id, actor=actor),
        ),
        "apply_graph_patch": (
            "patch_application",
            _graph_patch_application(target_qro_id=from_qro.qro_id, actor=actor),
        ),
        "set_canvas_parameter": (
            "parameter_value",
            _canvas_parameter_value(target_qro_id=from_qro.qro_id, actor=actor),
        ),
        "record_canvas_mutation": (
            "mutation",
            _canvas_mutation(target_ref=from_qro.qro_id, actor=actor),
        ),
        "record_canvas_layout": (
            "layout",
            make_canvas_layout_record(
                qro_id=from_qro.qro_id,
                qro_type="StrategyBook",
                node_id=f"canvas_node:qro:{from_qro.qro_id}",
                x=10,
                y=20,
                w=180,
                source_desk="strategy",
                actor_source="user_manual",
                actor=actor,
                mutation_command_ref="canvas_command:owner_boundary:layout",
                canonical_command_ref="research_graph_command:owner_boundary:layout",
                audit_ref="audit:owner_boundary:layout",
                evidence_refs=("unit:canvas_owner_boundary",),
            ),
        ),
        "record_graph_edge": (
            "edge",
            _graph_edge(
                from_qro_id=from_qro.qro_id,
                to_qro_id=to_qro.qro_id,
                actor=actor,
            ),
        ),
        "delete_graph_edge": (
            "edge_deletion",
            _graph_edge_deletion(edge_ref=edge.edge_ref, actor=actor),
        ),
    }
    payload_key, record = records[command_type]
    initial_commands = [command.command_id for command in store.commands()]
    initial_bytes = path.read_bytes()

    with pytest.raises(ResearchGraphError):
        store.apply(
            ResearchGraphCommand(
                source=EntrySource.CANVAS,
                command_type=command_type,
                actor_source=ActorSource.USER_MANUAL,
                actor=actor,
                payload={payload_key: record},
                evidence_refs=("unit:canvas_owner_boundary",),
            )
        )

    assert [command.command_id for command in store.commands()] == initial_commands
    assert path.read_bytes() == initial_bytes


def test_direct_canvas_command_rejects_command_record_actor_mismatch(tmp_path):
    path = tmp_path / "research_graph_commands.jsonl"
    store = PersistentResearchGraphStore(path)
    qro = _qro()
    store.apply(_command(qro))
    mutation = _canvas_mutation(target_ref=qro.qro_id, actor=qro.owner)
    initial_bytes = path.read_bytes()

    with pytest.raises(ResearchGraphError, match="does not match"):
        store.apply(
            ResearchGraphCommand(
                source=EntrySource.CANVAS,
                command_type="record_canvas_mutation",
                actor_source=ActorSource.USER_MANUAL,
                actor="different_actor",
                payload={"mutation": mutation},
                evidence_refs=mutation.evidence_refs,
            )
        )

    assert [command.command_type for command in store.commands()] == ["upsert_qro"]
    assert path.read_bytes() == initial_bytes


def test_canvas_owner_boundary_does_not_change_non_canvas_command_contract(tmp_path):
    store = PersistentResearchGraphStore(tmp_path / "research_graph_commands.jsonl")
    qro = _qro()
    store.apply(_command(qro))
    tombstone = _qro_tombstone(qro_id=qro.qro_id, actor="recording_service")

    store.apply(
        ResearchGraphCommand(
            source=EntrySource.API,
            command_type="tombstone_qro",
            actor_source=ActorSource.AGENT,
            actor="different_service_actor",
            payload={"qro_tombstone": tombstone},
            evidence_refs=tombstone.evidence_refs,
        )
    )

    assert [record.qro_id for record in store.qro_tombstones()] == [qro.qro_id]


def test_persistent_research_graph_store_replays_graph_edge_commands(tmp_path):
    path = tmp_path / "research_graph_commands.jsonl"
    store = PersistentResearchGraphStore(path)
    from_qro = _qro(
        input_contract={"strategy_id": "from_strategy", "code_hash": "hash_from"},
        output_contract={"strategy_book_ref": "strategy:from"},
        implementation_hash="strategy:hash_from",
    )
    to_qro = _qro(
        qro_type=QROType.RISK_POLICY,
        input_contract={"policy_id": "risk_policy", "threshold_ref": "risk_ref"},
        output_contract={"risk_policy_ref": "risk:to"},
        implementation_hash="risk:hash_to",
    )
    edge = _graph_edge(from_qro_id=from_qro.qro_id, to_qro_id=to_qro.qro_id)
    store.apply(_command(from_qro))
    store.apply(_command(to_qro))
    command = ResearchGraphCommand(
        source=EntrySource.CANVAS,
        command_type="record_graph_edge",
        actor_source=ActorSource.USER_MANUAL,
        actor="dreaminate",
        payload={"edge": edge},
        evidence_refs=edge.evidence_refs,
    )

    command_id = store.apply(command)

    reloaded = PersistentResearchGraphStore(path)
    assert [cmd.command_id for cmd in reloaded.commands()] == [
        store.commands()[0].command_id,
        store.commands()[1].command_id,
        command_id,
    ]
    [persisted] = reloaded.graph_edges()
    assert persisted.edge_ref == edge.edge_ref
    assert persisted.from_qro_id == from_qro.qro_id
    assert persisted.to_qro_id == to_qro.qro_id
    assert persisted.relation_type == "canvas_connect"
    assert persisted.canonical_command_ref == "research_graph_command:graph_edge:001"


def test_persistent_research_graph_store_replays_graph_edge_deletions(tmp_path):
    path = tmp_path / "research_graph_commands.jsonl"
    store = PersistentResearchGraphStore(path)
    from_qro = _qro(
        input_contract={"strategy_id": "from_strategy", "code_hash": "hash_from"},
        output_contract={"strategy_book_ref": "strategy:from"},
        implementation_hash="strategy:hash_from",
    )
    to_qro = _qro(
        qro_type=QROType.RISK_POLICY,
        input_contract={"policy_id": "risk_policy", "threshold_ref": "risk_ref"},
        output_contract={"risk_policy_ref": "risk:to"},
        implementation_hash="risk:hash_to",
    )
    edge = _graph_edge(from_qro_id=from_qro.qro_id, to_qro_id=to_qro.qro_id)
    deletion = _graph_edge_deletion(edge_ref=edge.edge_ref)
    store.apply(_command(from_qro))
    store.apply(_command(to_qro))
    store.apply(
        ResearchGraphCommand(
            source=EntrySource.CANVAS,
            command_type="record_graph_edge",
            actor_source=ActorSource.USER_MANUAL,
            actor="dreaminate",
            payload={"edge": edge},
            evidence_refs=edge.evidence_refs,
        )
    )

    delete_command_id = store.apply(
        ResearchGraphCommand(
            source=EntrySource.CANVAS,
            command_type="delete_graph_edge",
            actor_source=ActorSource.USER_MANUAL,
            actor="dreaminate",
            payload={"edge_deletion": deletion},
            evidence_refs=deletion.evidence_refs,
        )
    )

    reloaded = PersistentResearchGraphStore(path)
    assert reloaded.graph_edges() == []
    [persisted_edge] = reloaded.graph_edges(include_deleted=True)
    assert persisted_edge.edge_ref == edge.edge_ref
    [persisted_deletion] = reloaded.graph_edge_deletions()
    assert persisted_deletion.edge_ref == edge.edge_ref
    assert persisted_deletion.deletion_ref == deletion.deletion_ref
    assert reloaded.commands()[-1].command_id == delete_command_id


def test_persistent_research_graph_store_replays_qro_tombstones(tmp_path):
    path = tmp_path / "research_graph_commands.jsonl"
    store = PersistentResearchGraphStore(path)
    from_qro = _qro(
        input_contract={"strategy_id": "from_strategy", "code_hash": "hash_from"},
        output_contract={"strategy_book_ref": "strategy:from"},
        implementation_hash="strategy:hash_from",
    )
    to_qro = _qro(
        qro_type=QROType.RISK_POLICY,
        input_contract={"policy_id": "risk_policy", "threshold_ref": "risk_ref"},
        output_contract={"risk_policy_ref": "risk:to"},
        implementation_hash="risk:hash_to",
    )
    edge = _graph_edge(from_qro_id=from_qro.qro_id, to_qro_id=to_qro.qro_id)
    tombstone = _qro_tombstone(qro_id=from_qro.qro_id)
    store.apply(_command(from_qro))
    store.apply(_command(to_qro))
    store.apply(
        ResearchGraphCommand(
            source=EntrySource.CANVAS,
            command_type="record_graph_edge",
            actor_source=ActorSource.USER_MANUAL,
            actor="dreaminate",
            payload={"edge": edge},
            evidence_refs=edge.evidence_refs,
        )
    )

    tombstone_command_id = store.apply(
        ResearchGraphCommand(
            source=EntrySource.CANVAS,
            command_type="tombstone_qro",
            actor_source=ActorSource.USER_MANUAL,
            actor="dreaminate",
            payload={"qro_tombstone": tombstone},
            evidence_refs=tombstone.evidence_refs,
        )
    )

    reloaded = PersistentResearchGraphStore(path)
    with pytest.raises(KeyError):
        reloaded.qro(from_qro.qro_id)
    assert reloaded.qro(from_qro.qro_id, include_tombstoned=True).qro_id == from_qro.qro_id
    assert [record.qro_id for record in reloaded.projection_index()] == [to_qro.qro_id]
    assert {record.qro_id for record in reloaded.projection_index(include_tombstoned=True)} == {
        from_qro.qro_id,
        to_qro.qro_id,
    }
    assert reloaded.graph_edges() == []
    [persisted_edge] = reloaded.graph_edges(include_deleted=True)
    assert persisted_edge.edge_ref == edge.edge_ref
    [persisted_tombstone] = reloaded.qro_tombstones()
    assert persisted_tombstone.qro_id == from_qro.qro_id
    assert persisted_tombstone.tombstone_ref == tombstone.tombstone_ref
    assert reloaded.commands()[-1].command_id == tombstone_command_id


def test_persistent_research_graph_store_replays_graph_patch_applications(tmp_path):
    path = tmp_path / "research_graph_commands.jsonl"
    store = PersistentResearchGraphStore(path)
    qro = _qro()
    patch = _graph_patch_application(target_qro_id=qro.qro_id)
    store.apply(_command(qro))

    patch_command_id = store.apply(
        ResearchGraphCommand(
            source=EntrySource.CANVAS,
            command_type="apply_graph_patch",
            actor_source=ActorSource.USER_MANUAL,
            actor="dreaminate",
            payload={"patch_application": patch},
            evidence_refs=patch.evidence_refs,
        )
    )

    reloaded = PersistentResearchGraphStore(path)
    [persisted] = reloaded.graph_patch_applications()
    assert persisted.application_ref == patch.application_ref
    assert persisted.target_qro_id == qro.qro_id
    assert persisted.patch_ref == "canvas_patch:ghost:strategy:qro_patch_target:001"
    assert persisted.patch_hash == "hash_canvas_patch_001"
    assert reloaded.commands()[-1].command_id == patch_command_id


def test_persistent_research_graph_store_replays_canvas_parameter_values(tmp_path):
    path = tmp_path / "research_graph_commands.jsonl"
    store = PersistentResearchGraphStore(path)
    qro = _qro()
    parameter = _canvas_parameter_value(target_qro_id=qro.qro_id)
    store.apply(_command(qro))

    parameter_command_id = store.apply(
        ResearchGraphCommand(
            source=EntrySource.CANVAS,
            command_type="set_canvas_parameter",
            actor_source=ActorSource.USER_MANUAL,
            actor="dreaminate",
            payload={"parameter_value": parameter},
            evidence_refs=parameter.evidence_refs,
        )
    )

    reloaded = PersistentResearchGraphStore(path)
    [persisted] = reloaded.canvas_parameter_values()
    assert persisted.parameter_ref == parameter.parameter_ref
    assert persisted.target_qro_id == qro.qro_id
    assert persisted.param_key == "turnover"
    assert persisted.param_value == "45%/w"
    assert persisted.value_hash == parameter.value_hash
    assert reloaded.commands()[-1].command_id == parameter_command_id


def test_research_graph_projection_index_filters_and_api_do_not_expose_raw_contracts(tmp_path, monkeypatch):
    from app import main

    path = tmp_path / "research_graph_commands.jsonl"
    store = PersistentResearchGraphStore(path)
    store.apply(
        _command(
            _qro(
                evidence_status=EvidenceStatus.SUFFICIENT,
                runtime_status=RuntimeStatus.PAPER,
                input_contract={"strategy_id": "secret_strategy", "prompt": "raw alpha prompt must not leak"},
                output_contract={"strategy_book_ref": "strategy:private"},
            )
        )
    )
    store.apply(
        _command(
            _qro(
                qro_type=QROType.BACKTEST_RUN,
                evidence_status=EvidenceStatus.INSUFFICIENT,
                runtime_status=RuntimeStatus.OFFLINE,
                input_contract={"run_id": "run_private"},
                output_contract={"status": "failed"},
                implementation_hash="run:private",
            )
        )
    )
    monkeypatch.setattr(main, "RESEARCH_GRAPH_STORE", store)

    response = TestClient(main.app).get(
        "/api/research-os/graph/projection_index",
        params={"qro_type": "StrategyBook", "evidence_status": "sufficient", "runtime_status": "paper"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    [projection] = body["projections"]
    assert projection["qro_type"] == "StrategyBook"
    assert projection["status_axes"]["evidence"] == "sufficient"
    assert projection["status_axes"]["runtime"] == "paper"
    assert projection["input_contract_keys"] == ["prompt", "strategy_id"]
    raw = json.dumps(body)
    assert "raw alpha prompt must not leak" not in raw
    assert "strategy:private" not in raw

    canvas = TestClient(main.app).get(
        "/api/research-os/graph/canvas_projection",
        params={"qro_type": "StrategyBook", "evidence_status": "sufficient", "runtime_status": "paper"},
    )
    assert canvas.status_code == 200
    canvas_body = canvas.json()
    assert canvas_body["read_only"] is True
    assert canvas_body["total"] == 1
    assert len(canvas_body["nodes"]) == 2
    assert len(canvas_body["edges"]) == 1
    command_node, qro_node = canvas_body["nodes"]
    assert command_node["locked"] is True
    assert qro_node["locked"] is True
    assert command_node["outs"][0]["id"] == canvas_body["edges"][0]["from"]["port"]
    assert qro_node["ins"][0]["id"] == canvas_body["edges"][0]["to"]["port"]
    assert qro_node["cat"] == "position"
    assert qro_node["state"] == "running"
    raw_canvas = json.dumps(canvas_body)
    assert "raw alpha prompt must not leak" not in raw_canvas
    assert "strategy:private" not in raw_canvas


def test_research_graph_edge_api_creates_qro_topology_and_projection_edge(tmp_path, monkeypatch):
    from app import main

    path = tmp_path / "research_graph_commands.jsonl"
    store = PersistentResearchGraphStore(path)
    from_qro = _qro(
        input_contract={"strategy_id": "secret_source_strategy", "prompt": "source prompt must not leak"},
        output_contract={"strategy_book_ref": "strategy:source_private"},
        implementation_hash="strategy:source_hash",
    )
    to_qro = _qro(
        qro_type=QROType.RISK_POLICY,
        input_contract={"policy_id": "secret_risk_policy"},
        output_contract={"risk_policy_ref": "risk:private"},
        implementation_hash="risk:target_hash",
    )
    store.apply(_command(from_qro))
    store.apply(_command(to_qro))
    monkeypatch.setattr(main, "RESEARCH_GRAPH_STORE", store)
    main.app.dependency_overrides[require_user_dependency] = lambda: SimpleNamespace(username="dreaminate", user_id="dreaminate")
    try:
        response = TestClient(main.app).post(
            "/api/research-os/graph/edges",
            json={
                "command_ref": "canvas_command:strategy_console_graph_edge:001",
                "source_desk": "strategy",
                "actor_source": "user_manual",
                "from_qro_id": from_qro.qro_id,
                "to_qro_id": to_qro.qro_id,
                "relation_type": "canvas_connect",
                "canonical_command_ref": "canonical:strategy_console_graph_edge:001",
                "audit_ref": "audit:strategy_console_graph_edge:001",
                "evidence_refs": ["unit:graph_edge_api"],
                "raw_value": "must not be accepted",
            },
        )
        assert response.status_code == 422
        assert len(store.graph_edges()) == 0

        ok = TestClient(main.app).post(
            "/api/research-os/graph/edges",
            json={
                "command_ref": "canvas_command:strategy_console_graph_edge:001",
                "source_desk": "strategy",
                "actor_source": "user_manual",
                "from_qro_id": from_qro.qro_id,
                "to_qro_id": to_qro.qro_id,
                "relation_type": "canvas_connect",
                "canonical_command_ref": "canonical:strategy_console_graph_edge:001",
                "audit_ref": "audit:strategy_console_graph_edge:001",
                "evidence_refs": ["unit:graph_edge_api"],
            },
        )
    finally:
        main.app.dependency_overrides.pop(require_user_dependency, None)

    assert ok.status_code == 200
    body = ok.json()
    assert body["accepted"] is True
    assert body["command_type"] == "record_graph_edge"
    assert body["from_qro_id"] == from_qro.qro_id
    assert body["to_qro_id"] == to_qro.qro_id
    assert body["projection_edge_id"] == f"canvas_edge:graph:{body['edge_ref']}"
    assert [command.command_type for command in store.commands()] == [
        "upsert_qro",
        "upsert_qro",
        "record_graph_edge",
    ]
    [edge] = store.graph_edges()
    assert edge.edge_ref == body["edge_ref"]
    assert edge.actor == "dreaminate"

    canvas = TestClient(main.app).get("/api/research-os/graph/canvas_projection")
    assert canvas.status_code == 200
    canvas_body = canvas.json()
    graph_edges = [edge for edge in canvas_body["edges"] if edge["id"] == body["projection_edge_id"]]
    assert len(graph_edges) == 1
    [projected] = graph_edges
    assert projected["from"] == {
        "node": f"canvas_node:qro:{from_qro.qro_id}",
        "port": f"out:{from_qro.qro_id}",
    }
    assert projected["to"] == {
        "node": f"canvas_node:qro:{to_qro.qro_id}",
        "port": f"in:{to_qro.qro_id}",
    }
    raw_canvas = json.dumps(canvas_body)
    assert "source prompt must not leak" not in raw_canvas
    assert "strategy:source_private" not in raw_canvas
    assert "risk:private" not in raw_canvas


def test_research_graph_edge_deletion_api_tombstones_projection_edge(tmp_path, monkeypatch):
    from app import main

    path = tmp_path / "research_graph_commands.jsonl"
    store = PersistentResearchGraphStore(path)
    from_qro = _qro(
        input_contract={"strategy_id": "source_strategy"},
        output_contract={"strategy_book_ref": "strategy:source_private"},
        implementation_hash="strategy:source_hash",
    )
    to_qro = _qro(
        qro_type=QROType.RISK_POLICY,
        input_contract={"policy_id": "risk_policy"},
        output_contract={"risk_policy_ref": "risk:private"},
        implementation_hash="risk:target_hash",
    )
    edge = _graph_edge(from_qro_id=from_qro.qro_id, to_qro_id=to_qro.qro_id)
    store.apply(_command(from_qro))
    store.apply(_command(to_qro))
    store.apply(
        ResearchGraphCommand(
            source=EntrySource.CANVAS,
            command_type="record_graph_edge",
            actor_source=ActorSource.USER_MANUAL,
            actor="dreaminate",
            payload={"edge": edge},
            evidence_refs=edge.evidence_refs,
        )
    )
    monkeypatch.setattr(main, "RESEARCH_GRAPH_STORE", store)
    main.app.dependency_overrides[require_user_dependency] = lambda: SimpleNamespace(username="dreaminate", user_id="dreaminate")
    try:
        rejected = TestClient(main.app).post(
            "/api/research-os/graph/edge_deletions",
            json={
                "command_ref": "canvas_command:delete_graph_edge:001",
                "source_desk": "strategy",
                "actor_source": "user_manual",
                "edge_ref": edge.edge_ref,
                "canonical_command_ref": "canonical:delete_graph_edge:001",
                "audit_ref": "audit:delete_graph_edge:001",
                "evidence_refs": ["unit:graph_edge_delete_api"],
                "raw_value": "must not be accepted",
            },
        )
        assert rejected.status_code == 422
        assert len(store.graph_edges()) == 1

        ok = TestClient(main.app).post(
            "/api/research-os/graph/edge_deletions",
            json={
                "command_ref": "canvas_command:delete_graph_edge:001",
                "source_desk": "strategy",
                "actor_source": "user_manual",
                "edge_ref": edge.edge_ref,
                "canonical_command_ref": "canonical:delete_graph_edge:001",
                "audit_ref": "audit:delete_graph_edge:001",
                "evidence_refs": ["unit:graph_edge_delete_api"],
            },
        )
    finally:
        main.app.dependency_overrides.pop(require_user_dependency, None)

    assert ok.status_code == 200
    body = ok.json()
    assert body["accepted"] is True
    assert body["command_type"] == "delete_graph_edge"
    assert body["edge_ref"] == edge.edge_ref
    assert body["projection_edge_id"] == f"canvas_edge:graph:{edge.edge_ref}"
    assert store.graph_edges() == []
    [deleted_edge] = store.graph_edges(include_deleted=True)
    assert deleted_edge.edge_ref == edge.edge_ref
    [deletion] = store.graph_edge_deletions()
    assert deletion.edge_ref == edge.edge_ref
    assert deletion.actor == "dreaminate"
    assert [command.command_type for command in store.commands()] == [
        "upsert_qro",
        "upsert_qro",
        "record_graph_edge",
        "delete_graph_edge",
    ]

    canvas = TestClient(main.app).get("/api/research-os/graph/canvas_projection")
    assert canvas.status_code == 200
    canvas_body = canvas.json()
    assert body["projection_edge_id"] not in {edge["id"] for edge in canvas_body["edges"]}
    raw_canvas = json.dumps(canvas_body)
    assert "strategy:source_private" not in raw_canvas
    assert "risk:private" not in raw_canvas


def test_research_graph_qro_tombstone_api_removes_node_and_related_projection_edges(tmp_path, monkeypatch):
    from app import main

    path = tmp_path / "research_graph_commands.jsonl"
    store = PersistentResearchGraphStore(path)
    from_qro = _qro(
        input_contract={"strategy_id": "secret_source_strategy", "prompt": "source prompt must not leak"},
        output_contract={"strategy_book_ref": "strategy:source_private"},
        implementation_hash="strategy:source_hash",
    )
    to_qro = _qro(
        qro_type=QROType.RISK_POLICY,
        input_contract={"policy_id": "risk_policy"},
        output_contract={"risk_policy_ref": "risk:private"},
        implementation_hash="risk:target_hash",
    )
    edge = _graph_edge(from_qro_id=from_qro.qro_id, to_qro_id=to_qro.qro_id)
    store.apply(_command(from_qro))
    store.apply(_command(to_qro))
    store.apply(
        ResearchGraphCommand(
            source=EntrySource.CANVAS,
            command_type="record_graph_edge",
            actor_source=ActorSource.USER_MANUAL,
            actor="dreaminate",
            payload={"edge": edge},
            evidence_refs=edge.evidence_refs,
        )
    )
    monkeypatch.setattr(main, "RESEARCH_GRAPH_STORE", store)
    main.app.dependency_overrides[require_user_dependency] = lambda: SimpleNamespace(username="dreaminate", user_id="dreaminate")
    try:
        rejected = TestClient(main.app).post(
            "/api/research-os/graph/qro_tombstones",
            json={
                "command_ref": "canvas_command:tombstone_qro:001",
                "source_desk": "strategy",
                "actor_source": "user_manual",
                "qro_id": from_qro.qro_id,
                "canonical_command_ref": "canonical:tombstone_qro:001",
                "audit_ref": "audit:tombstone_qro:001",
                "evidence_refs": ["unit:qro_tombstone_api"],
                "raw_value": "must not be accepted",
            },
        )
        assert rejected.status_code == 422
        assert store.qro_tombstones() == []

        ok = TestClient(main.app).post(
            "/api/research-os/graph/qro_tombstones",
            json={
                "command_ref": "canvas_command:tombstone_qro:001",
                "source_desk": "strategy",
                "actor_source": "user_manual",
                "qro_id": from_qro.qro_id,
                "canonical_command_ref": "canonical:tombstone_qro:001",
                "audit_ref": "audit:tombstone_qro:001",
                "evidence_refs": ["unit:qro_tombstone_api"],
            },
        )
    finally:
        main.app.dependency_overrides.pop(require_user_dependency, None)

    assert ok.status_code == 200
    body = ok.json()
    assert body["accepted"] is True
    assert body["command_type"] == "tombstone_qro"
    assert body["qro_id"] == from_qro.qro_id
    assert body["projection_node_id"] == f"canvas_node:qro:{from_qro.qro_id}"
    with pytest.raises(KeyError):
        store.qro(from_qro.qro_id)
    assert store.qro(from_qro.qro_id, include_tombstoned=True).qro_id == from_qro.qro_id
    [tombstone] = store.qro_tombstones()
    assert tombstone.qro_id == from_qro.qro_id
    assert tombstone.actor == "dreaminate"
    assert store.graph_edges() == []
    [historical_edge] = store.graph_edges(include_deleted=True)
    assert historical_edge.edge_ref == edge.edge_ref
    assert [command.command_type for command in store.commands()] == [
        "upsert_qro",
        "upsert_qro",
        "record_graph_edge",
        "tombstone_qro",
    ]

    canvas = TestClient(main.app).get("/api/research-os/graph/canvas_projection")
    assert canvas.status_code == 200
    canvas_body = canvas.json()
    ids = {node["id"] for node in canvas_body["nodes"]}
    assert body["projection_node_id"] not in ids
    assert f"canvas_node:qro:{to_qro.qro_id}" in ids
    assert f"canvas_edge:graph:{edge.edge_ref}" not in {edge["id"] for edge in canvas_body["edges"]}
    raw_canvas = json.dumps(canvas_body)
    assert "source prompt must not leak" not in raw_canvas
    assert "strategy:source_private" not in raw_canvas
    assert "risk:private" not in raw_canvas


def test_research_graph_patch_application_api_adds_patch_qro_and_projection_edge(tmp_path, monkeypatch):
    from app import main

    path = tmp_path / "research_graph_commands.jsonl"
    store = PersistentResearchGraphStore(path)
    qro = _qro(
        input_contract={"strategy_id": "secret_strategy", "prompt": "raw proposal must not leak"},
        output_contract={"strategy_book_ref": "strategy:private"},
        implementation_hash="strategy:source_hash",
    )
    store.apply(_command(qro))
    _install_goal_proof_stores(main, tmp_path, monkeypatch, store)
    main.app.dependency_overrides[require_user_dependency] = lambda: SimpleNamespace(username="dreaminate", user_id="dreaminate")
    try:
        rejected = TestClient(main.app).post(
            "/api/research-os/graph/patch_applications",
            json={
                "command_ref": "canvas_command:apply_graph_patch:001",
                "source_desk": "strategy",
                "actor_source": "user_manual",
                "target_qro_id": qro.qro_id,
                "patch_kind": "ghost",
                "patch_ref": "canvas_patch:ghost:strategy:qro1:pt_4f1a",
                "patch_hash": "hash_patch_001",
                "canonical_command_ref": "canonical:apply_graph_patch:001",
                "audit_ref": "audit:apply_graph_patch:001",
                "evidence_refs": ["unit:graph_patch_api"],
                "ops": [{"op": "addNode", "title": "must not cross boundary"}],
            },
        )
        assert rejected.status_code == 422
        assert store.graph_patch_applications() == []

        ok = TestClient(main.app).post(
            "/api/research-os/graph/patch_applications",
            json={
                "command_ref": "canvas_command:apply_graph_patch:001",
                "source_desk": "strategy",
                "actor_source": "user_manual",
                "target_qro_id": qro.qro_id,
                "patch_kind": "ghost",
                "patch_ref": "canvas_patch:ghost:strategy:qro1:pt_4f1a",
                "patch_hash": "hash_patch_001",
                "canonical_command_ref": "canonical:apply_graph_patch:001",
                "audit_ref": "audit:apply_graph_patch:001",
                "evidence_refs": ["unit:graph_patch_api"],
            },
        )
    finally:
        main.app.dependency_overrides.pop(require_user_dependency, None)

    assert ok.status_code == 200
    body = ok.json()
    assert body["accepted"] is True
    assert body["command_type"] == "apply_graph_patch"
    assert body["target_qro_id"] == qro.qro_id
    assert body["patch_kind"] == "ghost"
    [patch] = store.graph_patch_applications()
    assert patch.actor == "dreaminate"
    assert patch.patch_ref == "canvas_patch:ghost:strategy:qro1:pt_4f1a"
    [patch_projection] = store.projection_index(qro_type="GraphPatchApplication")
    assert patch_projection.qro_id == body["patch_qro_id"]
    [edge] = store.graph_edges(qro_id=qro.qro_id)
    assert edge.relation_type == "graph_patch_application"
    assert edge.to_qro_id == body["patch_qro_id"]
    assert [command.command_type for command in store.commands()] == [
        "upsert_qro",
        "apply_graph_patch",
        "upsert_qro",
        "record_graph_edge",
    ]

    canvas = TestClient(main.app).get("/api/research-os/graph/canvas_projection")
    assert canvas.status_code == 200
    canvas_body = canvas.json()
    assert body["projection_node_id"] in {node["id"] for node in canvas_body["nodes"]}
    assert body["projection_edge_id"] in {edge["id"] for edge in canvas_body["edges"]}
    raw_canvas = json.dumps(canvas_body)
    assert "raw proposal must not leak" not in raw_canvas
    assert "strategy:private" not in raw_canvas
    assert "pt_4f1a" not in raw_canvas
    assert "hash_patch_001" not in raw_canvas


def test_research_graph_canvas_parameter_value_api_saves_value_and_projects_ref_hash_only(tmp_path, monkeypatch):
    from app import main

    path = tmp_path / "research_graph_commands.jsonl"
    store = PersistentResearchGraphStore(path)
    qro = _qro(
        input_contract={"strategy_id": "secret_strategy"},
        output_contract={"strategy_book_ref": "strategy:private"},
        implementation_hash="strategy:source_hash",
    )
    store.apply(_command(qro))
    _install_goal_proof_stores(main, tmp_path, monkeypatch, store)
    main.app.dependency_overrides[require_user_dependency] = lambda: SimpleNamespace(username="dreaminate", user_id="dreaminate")
    try:
        rejected = TestClient(main.app).post(
            "/api/research-os/graph/canvas_parameter_values",
            json={
                "command_ref": "canvas_command:param_value:001",
                "source_desk": "strategy",
                "actor_source": "user_manual",
                "target_qro_id": qro.qro_id,
                "target_asset_type": "StrategyBook",
                "param_key": "turnover",
                "param_value": "45%/w",
                "canonical_command_ref": "canonical:param_value:001",
                "audit_ref": "audit:param_value:001",
                "evidence_refs": ["unit:param_value_api"],
                "raw_value": "must not be accepted",
            },
        )
        assert rejected.status_code == 422
        assert store.canvas_parameter_values() == []

        ok = TestClient(main.app).post(
            "/api/research-os/graph/canvas_parameter_values",
            json={
                "command_ref": "canvas_command:param_value:001",
                "source_desk": "strategy",
                "actor_source": "user_manual",
                "target_qro_id": qro.qro_id,
                "target_asset_type": "StrategyBook",
                "param_key": "turnover",
                "param_value": "45%/w",
                "canonical_command_ref": "canonical:param_value:001",
                "audit_ref": "audit:param_value:001",
                "evidence_refs": ["unit:param_value_api"],
            },
        )
    finally:
        main.app.dependency_overrides.pop(require_user_dependency, None)

    assert ok.status_code == 200
    body = ok.json()
    assert body["accepted"] is True
    assert body["command_type"] == "set_canvas_parameter"
    assert body["param_key"] == "turnover"
    assert body["qro_id"] == qro.qro_id
    assert body["qro_version"] == 2
    [parameter] = store.canvas_parameter_values()
    assert parameter.actor == "dreaminate"
    assert parameter.param_value == "45%/w"
    updated = store.qro(qro.qro_id)
    assert updated.output_contract["canvas_param_value_ref"] == body["parameter_ref"]
    assert updated.output_contract["canvas_param_value_hash"] == body["value_hash"]
    assert updated.output_contract["canvas_param_key"] == "turnover"
    assert [command.command_type for command in store.commands()] == [
        "upsert_qro",
        "set_canvas_parameter",
        "upsert_qro",
    ]

    canvas = TestClient(main.app).get("/api/research-os/graph/canvas_projection")
    assert canvas.status_code == 200
    raw_canvas = json.dumps(canvas.json())
    assert "45%/w" not in raw_canvas
    assert "strategy:private" not in raw_canvas
    assert body["parameter_ref"] not in raw_canvas
    assert body["value_hash"] not in raw_canvas


def test_research_graph_canvas_mutation_api_records_canonical_command(tmp_path, monkeypatch):
    from app import main

    path = tmp_path / "research_graph_commands.jsonl"
    store = PersistentResearchGraphStore(path)
    qro = _qro()
    store.apply(_command(qro))
    monkeypatch.setattr(main, "RESEARCH_GRAPH_STORE", store)
    main.app.dependency_overrides[require_user_dependency] = lambda: SimpleNamespace(
        username="dreaminate", user_id="dreaminate"
    )
    try:
        response = TestClient(main.app).post(
            "/api/research-os/graph/canvas_mutations",
            json={
                "command_ref": "canvas_command:update_strategy:001",
                "source_desk": "strategy",
                "actor_source": "user_manual",
                "actor": "dreaminate",
                "target_asset_type": "StrategyBook",
                "target_ref": qro.qro_id,
                "field_path": "legs.0.signal_ref",
                "operation": "set_ref",
                "canonical_command_ref": "research_graph_command:rgcmd_strategy_update",
                "audit_ref": "audit:canvas:001",
                "value_ref": "signal:trend:v1",
                "value_hash": "hash_signal_trend_v1",
                "evidence_refs": ["unit:canvas_mutation"],
                "raw_value": "must not be accepted",
            },
        )
        assert response.status_code == 422
        assert [command.command_type for command in store.commands()] == ["upsert_qro"]

        ok = TestClient(main.app).post(
            "/api/research-os/graph/canvas_mutations",
            json={
                "command_ref": "canvas_command:update_strategy:001",
                "source_desk": "strategy",
                "actor_source": "user_manual",
                "actor": "dreaminate",
                "target_asset_type": "StrategyBook",
                "target_ref": qro.qro_id,
                "field_path": "legs.0.signal_ref",
                "operation": "set_ref",
                "canonical_command_ref": "research_graph_command:rgcmd_strategy_update",
                "audit_ref": "audit:canvas:001",
                "value_ref": "signal:trend:v1",
                "value_hash": "hash_signal_trend_v1",
                "evidence_refs": ["unit:canvas_mutation"],
            },
        )
    finally:
        main.app.dependency_overrides.pop(require_user_dependency, None)
    assert ok.status_code == 200
    body = ok.json()
    assert body["accepted"] is True
    assert body["command_type"] == "record_canvas_mutation"
    assert body["research_graph_command_id"].startswith("rgcmd_")
    command = store.commands()[-1]
    assert command.command_type == "record_canvas_mutation"
    [mutation] = store.canvas_mutations()
    assert mutation.value_ref == "signal:trend:v1"


def test_research_graph_canvas_mutation_api_rejects_uncanonical_or_cross_desk_writes(tmp_path, monkeypatch):
    from app import main

    path = tmp_path / "research_graph_commands.jsonl"
    store = PersistentResearchGraphStore(path)
    qro = _qro(qro_type=QROType.FACTOR)
    store.apply(_command(qro))
    monkeypatch.setattr(main, "RESEARCH_GRAPH_STORE", store)
    main.app.dependency_overrides[require_user_dependency] = lambda: SimpleNamespace(
        username="dreaminate", user_id="dreaminate"
    )
    try:
        response = TestClient(main.app).post(
            "/api/research-os/graph/canvas_mutations",
            json={
                "command_ref": "canvas_command:bad_factor_write",
                "source_desk": "strategy",
                "actor_source": "agent",
                "actor": "agent_runtime",
                "target_asset_type": "Factor",
                "target_ref": qro.qro_id,
                "field_path": "formula.expression",
                "operation": "set_text_hash",
                "value_hash": "hash_formula",
            },
        )
    finally:
        main.app.dependency_overrides.pop(require_user_dependency, None)

    assert response.status_code == 422
    detail = response.json()["detail"]
    codes = {violation["code"] for violation in detail["violations"]}
    assert codes >= {
        "canvas_mutation_missing_canonical_command",
        "canvas_mutation_missing_audit_ref",
        "strategy_desk_cannot_write_factor_formula",
    }
    assert [command.command_type for command in store.commands()] == ["upsert_qro"]


def test_research_graph_canvas_writes_reject_foreign_owner_atomically(tmp_path, monkeypatch):
    from app import main

    path = tmp_path / "research_graph_commands.jsonl"
    store = PersistentResearchGraphStore(path)
    from_qro = _qro(owner="foreign_owner")
    to_qro = _qro(qro_type=QROType.RISK_POLICY, owner="foreign_owner")
    edge = _graph_edge(
        from_qro_id=from_qro.qro_id,
        to_qro_id=to_qro.qro_id,
        actor="foreign_owner",
    )
    for qro in (from_qro, to_qro):
        store.apply(
            ResearchGraphCommand(
                source=EntrySource.IDE,
                command_type="upsert_qro",
                actor_source=ActorSource.USER_MANUAL,
                actor="foreign_owner",
                payload={"qro": qro},
                evidence_refs=("unit:foreign_owner_fixture",),
            )
        )
    store.apply(
        ResearchGraphCommand(
            source=EntrySource.CANVAS,
            command_type="record_graph_edge",
            actor_source=ActorSource.USER_MANUAL,
            actor="foreign_owner",
            payload={"edge": edge},
            evidence_refs=edge.evidence_refs,
        )
    )
    monkeypatch.setattr(main, "RESEARCH_GRAPH_STORE", store)
    initial_command_ids = [command.command_id for command in store.commands()]
    initial_versions = {
        from_qro.qro_id: store.qro(from_qro.qro_id).version,
        to_qro.qro_id: store.qro(to_qro.qro_id).version,
    }
    requests = (
        (
            "/api/research-os/graph/edges",
            {
                "command_ref": "canvas_command:foreign_edge:001",
                "source_desk": "strategy",
                "actor_source": "user_manual",
                "from_qro_id": from_qro.qro_id,
                "to_qro_id": to_qro.qro_id,
                "relation_type": "canvas_connect",
                "canonical_command_ref": "canonical:foreign_edge:001",
                "audit_ref": "audit:foreign_edge:001",
                "evidence_refs": ["unit:foreign_owner_rejection"],
            },
        ),
        (
            "/api/research-os/graph/edge_deletions",
            {
                "command_ref": "canvas_command:foreign_edge_delete:001",
                "source_desk": "strategy",
                "actor_source": "user_manual",
                "edge_ref": edge.edge_ref,
                "canonical_command_ref": "canonical:foreign_edge_delete:001",
                "audit_ref": "audit:foreign_edge_delete:001",
                "evidence_refs": ["unit:foreign_owner_rejection"],
            },
        ),
        (
            "/api/research-os/graph/qro_tombstones",
            {
                "command_ref": "canvas_command:foreign_tombstone:001",
                "source_desk": "strategy",
                "actor_source": "user_manual",
                "qro_id": from_qro.qro_id,
                "canonical_command_ref": "canonical:foreign_tombstone:001",
                "audit_ref": "audit:foreign_tombstone:001",
                "evidence_refs": ["unit:foreign_owner_rejection"],
            },
        ),
        (
            "/api/research-os/graph/patch_applications",
            {
                "command_ref": "canvas_command:foreign_patch:001",
                "source_desk": "strategy",
                "actor_source": "user_manual",
                "target_qro_id": from_qro.qro_id,
                "patch_kind": "ghost",
                "patch_ref": "canvas_patch:ghost:foreign:001",
                "patch_hash": "hash_foreign_patch_001",
                "canonical_command_ref": "canonical:foreign_patch:001",
                "audit_ref": "audit:foreign_patch:001",
                "evidence_refs": ["unit:foreign_owner_rejection"],
            },
        ),
        (
            "/api/research-os/graph/canvas_parameter_values",
            {
                "command_ref": "canvas_command:foreign_parameter:001",
                "source_desk": "strategy",
                "actor_source": "user_manual",
                "target_qro_id": from_qro.qro_id,
                "target_asset_type": "StrategyBook",
                "param_key": "turnover",
                "param_value": "45%/w",
                "canonical_command_ref": "canonical:foreign_parameter:001",
                "audit_ref": "audit:foreign_parameter:001",
                "evidence_refs": ["unit:foreign_owner_rejection"],
            },
        ),
        (
            "/api/research-os/graph/canvas_mutations",
            {
                "command_ref": "canvas_command:foreign_audit:001",
                "source_desk": "strategy",
                "actor_source": "user_manual",
                "target_asset_type": "StrategyBook",
                "target_ref": from_qro.qro_id,
                "field_path": "legs.0.signal_ref",
                "operation": "set_ref",
                "canonical_command_ref": "canonical:foreign_audit:001",
                "audit_ref": "audit:foreign_audit:001",
                "value_ref": "signal:foreign:v1",
                "value_hash": "hash_signal_foreign_v1",
                "evidence_refs": ["unit:foreign_owner_rejection"],
            },
        ),
        (
            "/api/research-os/graph/canvas_layouts",
            {
                "command_ref": "canvas_command:foreign_layout:001",
                "source_desk": "strategy",
                "actor_source": "user_manual",
                "target_asset_type": "StrategyBook",
                "target_ref": from_qro.qro_id,
                "node_id": f"canvas_node:qro:{from_qro.qro_id}",
                "x": 100,
                "y": 200,
                "w": 184,
                "canonical_command_ref": "canonical:foreign_layout:001",
                "audit_ref": "audit:foreign_layout:001",
                "evidence_refs": ["unit:foreign_owner_rejection"],
            },
        ),
        (
            "/api/research-os/graph/canvas_asset_mutations",
            {
                "command_ref": "canvas_command:foreign_asset:001",
                "source_desk": "strategy",
                "actor_source": "user_manual",
                "target_asset_type": "StrategyBook",
                "target_ref": from_qro.qro_id,
                "field_path": "output_contract.canvas_param_ref",
                "operation": "set_ref",
                "canonical_command_ref": "canonical:foreign_asset:001",
                "audit_ref": "audit:foreign_asset:001",
                "value_ref": "canvas_param:foreign:001",
                "value_hash": "hash_canvas_param_foreign_001",
                "evidence_refs": ["unit:foreign_owner_rejection"],
            },
        ),
    )
    main.app.dependency_overrides[require_user_dependency] = lambda: SimpleNamespace(
        username="foreign_owner", user_id="intruder_owner"
    )
    try:
        client = TestClient(main.app)
        for endpoint, payload in requests:
            response = client.post(endpoint, json=payload)
            assert response.status_code == 422, (endpoint, response.text)
            assert "different owner" in str(response.json()["detail"]), endpoint
            assert [command.command_id for command in store.commands()] == initial_command_ids, endpoint
            assert store.qro(from_qro.qro_id).version == initial_versions[from_qro.qro_id], endpoint
            assert store.qro(to_qro.qro_id).version == initial_versions[to_qro.qro_id], endpoint
    finally:
        main.app.dependency_overrides.pop(require_user_dependency, None)

    assert [stored.edge_ref for stored in store.graph_edges()] == [edge.edge_ref]
    assert store.graph_edge_deletions() == []
    assert store.qro_tombstones() == []
    assert store.graph_patch_applications() == []
    assert store.canvas_parameter_values() == []
    assert store.canvas_mutations() == []
    assert store.canvas_layouts() == []


def test_research_graph_canvas_asset_mutation_api_updates_qro_version(tmp_path, monkeypatch):
    from app import main

    path = tmp_path / "research_graph_commands.jsonl"
    store = PersistentResearchGraphStore(path)
    qro = _qro(output_contract={"strategy_book_ref": "strategy:demo"})
    store.apply(_command(qro))
    _install_goal_proof_stores(main, tmp_path, monkeypatch, store)
    main.app.dependency_overrides[require_user_dependency] = lambda: SimpleNamespace(username="dreaminate", user_id="dreaminate")
    try:
        rejected = TestClient(main.app).post(
            "/api/research-os/graph/canvas_asset_mutations",
            json={
                "command_ref": "canvas_command:update_strategy:raw",
                "source_desk": "strategy",
                "actor_source": "user_manual",
                "target_asset_type": "StrategyBook",
                "target_ref": qro.qro_id,
                "field_path": "output_contract.canvas_edit_ref",
                "operation": "set_ref",
                "canonical_command_ref": "research_graph_command:strategy_canvas_raw",
                "audit_ref": "audit:canvas:raw",
                "value_ref": "canvas_edit:raw",
                "value_hash": "hash_canvas_edit_raw",
                "raw_value": "SECRET_CANVAS_RAW_PAYLOAD",
                "evidence_refs": ["unit:canvas_asset_mutation_raw"],
            },
        )
        assert rejected.status_code == 422
        assert len(store.commands()) == 1
        assert main.COMPILER_IR_STORE.irs() == []
        assert main.COMPILER_IR_STORE.passes() == []
        assert main.GOAL_ENTRYPOINT_COVERAGE_REGISTRY.records() == []

        response = TestClient(main.app).post(
            "/api/research-os/graph/canvas_asset_mutations",
            json={
                "command_ref": "canvas_command:update_strategy:002",
                "source_desk": "strategy",
                "actor_source": "user_manual",
                "target_asset_type": "StrategyBook",
                "target_ref": qro.qro_id,
                "field_path": "output_contract.canvas_edit_ref",
                "operation": "set_ref",
                "canonical_command_ref": "research_graph_command:strategy_canvas_update",
                "audit_ref": "audit:canvas:002",
                "value_ref": "canvas_edit:strategy:v2",
                "value_hash": "hash_canvas_edit_v2",
                "evidence_refs": ["unit:canvas_asset_mutation"],
            },
        )
    finally:
        main.app.dependency_overrides.pop(require_user_dependency, None)

    assert response.status_code == 200
    body = response.json()
    assert body["accepted"] is True
    assert body["qro_id"] == qro.qro_id
    assert body["qro_version"] == 2
    assert body["mutation_command_id"].startswith("rgcmd_")
    assert body["qro_command_id"].startswith("rgcmd_")
    assert body["compiler_ir_ref"].startswith("compiler_ir:")
    assert body["compiler_pass_ref"].startswith("compiler_pass:")
    assert body["entrypoint_coverage_ref"].startswith("goal_entrypoint_coverage:")
    commands = store.commands()
    assert [command.command_type for command in commands] == [
        "upsert_qro",
        "record_canvas_mutation",
        "upsert_qro",
    ]
    updated = store.qro(qro.qro_id)
    assert updated.version == 2
    assert updated.output_contract["canvas_edit_ref"] == "canvas_edit:strategy:v2"
    assert updated.output_contract["canvas_edit_hash"] == "hash_canvas_edit_v2"
    assert "audit:canvas:002" in updated.evidence_refs
    [projection] = store.projection_index(qro_type="StrategyBook")
    assert projection.qro_version == 2
    assert "canvas_edit:strategy:v2" not in json.dumps(projection.to_audit_dict())
    coverage = main.GOAL_ENTRYPOINT_COVERAGE_REGISTRY.coverage(body["entrypoint_coverage_ref"])
    assert coverage.entry_source == "canvas"
    assert coverage.entrypoint_ref == "canvas:asset_mutation"
    assert coverage.qro_refs == (qro.qro_id,)
    assert coverage.compiler_ir_refs == (body["compiler_ir_ref"],)
    assert coverage.compiler_pass_refs == (body["compiler_pass_ref"],)
    assert coverage.evidence_refs
    assert coverage.permission_refs
    assert coverage.replay_refs


def test_research_graph_canvas_asset_mutation_api_updates_layout_hash_without_ref(tmp_path, monkeypatch):
    from app import main

    path = tmp_path / "research_graph_commands.jsonl"
    store = PersistentResearchGraphStore(path)
    qro = _qro(output_contract={"strategy_book_ref": "strategy:demo"})
    store.apply(_command(qro))
    _install_goal_proof_stores(main, tmp_path, monkeypatch, store)
    main.app.dependency_overrides[require_user_dependency] = lambda: SimpleNamespace(username="dreaminate", user_id="dreaminate")
    try:
        response = TestClient(main.app).post(
            "/api/research-os/graph/canvas_asset_mutations",
            json={
                "command_ref": "canvas_command:layout_strategy:001",
                "source_desk": "strategy",
                "actor_source": "user_manual",
                "target_asset_type": "StrategyBook",
                "target_ref": qro.qro_id,
                "field_path": "output_contract.canvas_layout_hash",
                "operation": "set_hash",
                "canonical_command_ref": "research_graph_command:strategy_canvas_layout",
                "audit_ref": "audit:canvas:layout:001",
                "value_hash": "hash_canvas_layout_1a2b3c",
                "evidence_refs": ["unit:canvas_layout_drag"],
            },
        )
    finally:
        main.app.dependency_overrides.pop(require_user_dependency, None)

    assert response.status_code == 200
    body = response.json()
    assert body["qro_version"] == 2
    assert body["updated_field_path"] == "output_contract.canvas_layout_hash"
    commands = store.commands()
    assert [command.command_type for command in commands] == [
        "upsert_qro",
        "record_canvas_mutation",
        "upsert_qro",
    ]
    updated = store.qro(qro.qro_id)
    assert updated.output_contract["canvas_layout_hash"] == "hash_canvas_layout_1a2b3c"
    assert "unit:canvas_layout_drag" in updated.evidence_refs
    [projection] = store.projection_index(qro_type="StrategyBook")
    assert "canvas_layout_hash" in projection.output_contract_keys
    assert "hash_canvas_layout_1a2b3c" not in json.dumps(projection.to_audit_dict())


def test_research_graph_canvas_asset_mutation_api_records_edge_relation_ref_without_raw_payload(tmp_path, monkeypatch):
    from app import main

    path = tmp_path / "research_graph_commands.jsonl"
    store = PersistentResearchGraphStore(path)
    qro = _qro(output_contract={"strategy_book_ref": "strategy:demo"})
    store.apply(_command(qro))
    _install_goal_proof_stores(main, tmp_path, monkeypatch, store)
    main.app.dependency_overrides[require_user_dependency] = lambda: SimpleNamespace(username="dreaminate", user_id="dreaminate")
    try:
        response = TestClient(main.app).post(
            "/api/research-os/graph/canvas_asset_mutations",
            json={
                "command_ref": "canvas_command:edge_strategy:001",
                "source_desk": "strategy",
                "actor_source": "user_manual",
                "target_asset_type": "StrategyBook",
                "target_ref": qro.qro_id,
                "field_path": "output_contract.canvas_edge_ref",
                "operation": "set_ref",
                "canonical_command_ref": "research_graph_command:strategy_canvas_edge",
                "audit_ref": "audit:canvas:edge:001",
                "value_ref": "canvas_edge:strategy:qro1:e1",
                "value_hash": "hash_canvas_edge_1a2b3c",
                "evidence_refs": ["unit:canvas_edge_relation"],
            },
        )
    finally:
        main.app.dependency_overrides.pop(require_user_dependency, None)

    assert response.status_code == 200
    body = response.json()
    assert body["qro_version"] == 2
    assert body["updated_field_path"] == "output_contract.canvas_edge_ref"
    updated = store.qro(qro.qro_id)
    assert updated.output_contract["canvas_edge_ref"] == "canvas_edge:strategy:qro1:e1"
    assert updated.output_contract["canvas_edge_hash"] == "hash_canvas_edge_1a2b3c"
    assert "unit:canvas_edge_relation" in updated.evidence_refs
    [projection] = store.projection_index(qro_type="StrategyBook")
    assert "canvas_edge_ref" in projection.output_contract_keys
    projection_json = json.dumps(projection.to_audit_dict())
    assert "canvas_edge:strategy:qro1:e1" not in projection_json
    assert "hash_canvas_edge_1a2b3c" not in projection_json


def test_research_graph_canvas_asset_mutation_api_records_param_ref_without_raw_payload(tmp_path, monkeypatch):
    from app import main

    path = tmp_path / "research_graph_commands.jsonl"
    store = PersistentResearchGraphStore(path)
    qro = _qro(output_contract={"strategy_book_ref": "strategy:demo"})
    store.apply(_command(qro))
    _install_goal_proof_stores(main, tmp_path, monkeypatch, store)
    main.app.dependency_overrides[require_user_dependency] = lambda: SimpleNamespace(username="dreaminate", user_id="dreaminate")
    try:
        response = TestClient(main.app).post(
            "/api/research-os/graph/canvas_asset_mutations",
            json={
                "command_ref": "canvas_command:param_strategy:001",
                "source_desk": "strategy",
                "actor_source": "user_manual",
                "target_asset_type": "StrategyBook",
                "target_ref": qro.qro_id,
                "field_path": "output_contract.canvas_param_ref",
                "operation": "set_ref",
                "canonical_command_ref": "research_graph_command:strategy_canvas_param",
                "audit_ref": "audit:canvas:param:001",
                "value_ref": "canvas_param:strategy:qro1:rebalance_window",
                "value_hash": "hash_canvas_param_1a2b3c",
                "evidence_refs": ["unit:canvas_param_writeback"],
            },
        )
    finally:
        main.app.dependency_overrides.pop(require_user_dependency, None)

    assert response.status_code == 200
    body = response.json()
    assert body["qro_version"] == 2
    assert body["updated_field_path"] == "output_contract.canvas_param_ref"
    updated = store.qro(qro.qro_id)
    assert updated.output_contract["canvas_param_ref"] == "canvas_param:strategy:qro1:rebalance_window"
    assert updated.output_contract["canvas_param_hash"] == "hash_canvas_param_1a2b3c"
    assert "unit:canvas_param_writeback" in updated.evidence_refs
    [projection] = store.projection_index(qro_type="StrategyBook")
    assert "canvas_param_ref" in projection.output_contract_keys
    projection_json = json.dumps(projection.to_audit_dict())
    assert "canvas_param:strategy:qro1:rebalance_window" not in projection_json
    assert "hash_canvas_param_1a2b3c" not in projection_json


def test_research_graph_canvas_asset_mutation_api_records_delete_ref_without_raw_payload(tmp_path, monkeypatch):
    from app import main

    path = tmp_path / "research_graph_commands.jsonl"
    store = PersistentResearchGraphStore(path)
    qro = _qro(output_contract={"strategy_book_ref": "strategy:demo"})
    store.apply(_command(qro))
    _install_goal_proof_stores(main, tmp_path, monkeypatch, store)
    main.app.dependency_overrides[require_user_dependency] = lambda: SimpleNamespace(username="dreaminate", user_id="dreaminate")
    try:
        response = TestClient(main.app).post(
            "/api/research-os/graph/canvas_asset_mutations",
            json={
                "command_ref": "canvas_command:delete_strategy:001",
                "source_desk": "strategy",
                "actor_source": "user_manual",
                "target_asset_type": "StrategyBook",
                "target_ref": qro.qro_id,
                "field_path": "output_contract.canvas_delete_ref",
                "operation": "set_ref",
                "canonical_command_ref": "research_graph_command:strategy_canvas_delete",
                "audit_ref": "audit:canvas:delete:001",
                "value_ref": "canvas_delete:strategy:qro1:node:policy",
                "value_hash": "hash_canvas_delete_1a2b3c",
                "evidence_refs": ["unit:canvas_delete_writeback"],
            },
        )
    finally:
        main.app.dependency_overrides.pop(require_user_dependency, None)

    assert response.status_code == 200
    body = response.json()
    assert body["qro_version"] == 2
    assert body["updated_field_path"] == "output_contract.canvas_delete_ref"
    updated = store.qro(qro.qro_id)
    assert updated.output_contract["canvas_delete_ref"] == "canvas_delete:strategy:qro1:node:policy"
    assert updated.output_contract["canvas_delete_hash"] == "hash_canvas_delete_1a2b3c"
    assert "unit:canvas_delete_writeback" in updated.evidence_refs
    [projection] = store.projection_index(qro_type="StrategyBook")
    assert "canvas_delete_ref" in projection.output_contract_keys
    projection_json = json.dumps(projection.to_audit_dict())
    assert "canvas_delete:strategy:qro1:node:policy" not in projection_json
    assert "hash_canvas_delete_1a2b3c" not in projection_json


def test_research_graph_canvas_asset_mutation_api_records_connect_ref_without_raw_payload(tmp_path, monkeypatch):
    from app import main

    path = tmp_path / "research_graph_commands.jsonl"
    store = PersistentResearchGraphStore(path)
    qro = _qro(output_contract={"strategy_book_ref": "strategy:demo"})
    store.apply(_command(qro))
    _install_goal_proof_stores(main, tmp_path, monkeypatch, store)
    main.app.dependency_overrides[require_user_dependency] = lambda: SimpleNamespace(username="dreaminate", user_id="dreaminate")
    try:
        response = TestClient(main.app).post(
            "/api/research-os/graph/canvas_asset_mutations",
            json={
                "command_ref": "canvas_command:connect_strategy:001",
                "source_desk": "strategy",
                "actor_source": "user_manual",
                "target_asset_type": "StrategyBook",
                "target_ref": qro.qro_id,
                "field_path": "output_contract.canvas_connect_ref",
                "operation": "set_ref",
                "canonical_command_ref": "research_graph_command:strategy_canvas_connect",
                "audit_ref": "audit:canvas:connect:001",
                "value_ref": "canvas_connect:strategy:qro1:cmd:out:policy:in",
                "value_hash": "hash_canvas_connect_1a2b3c",
                "evidence_refs": ["unit:canvas_connect_writeback"],
            },
        )
    finally:
        main.app.dependency_overrides.pop(require_user_dependency, None)

    assert response.status_code == 200
    body = response.json()
    assert body["qro_version"] == 2
    assert body["updated_field_path"] == "output_contract.canvas_connect_ref"
    updated = store.qro(qro.qro_id)
    assert updated.output_contract["canvas_connect_ref"] == "canvas_connect:strategy:qro1:cmd:out:policy:in"
    assert updated.output_contract["canvas_connect_hash"] == "hash_canvas_connect_1a2b3c"
    assert "unit:canvas_connect_writeback" in updated.evidence_refs
    [projection] = store.projection_index(qro_type="StrategyBook")
    assert "canvas_connect_ref" in projection.output_contract_keys
    projection_json = json.dumps(projection.to_audit_dict())
    assert "canvas_connect:strategy:qro1:cmd:out:policy:in" not in projection_json
    assert "hash_canvas_connect_1a2b3c" not in projection_json


def test_research_graph_canvas_asset_mutation_api_records_patch_intent_refs_without_raw_payload(tmp_path, monkeypatch):
    from app import main

    path = tmp_path / "research_graph_commands.jsonl"
    store = PersistentResearchGraphStore(path)
    qro = _qro(output_contract={"strategy_book_ref": "strategy:demo"})
    store.apply(_command(qro))
    _install_goal_proof_stores(main, tmp_path, monkeypatch, store)
    main.app.dependency_overrides[require_user_dependency] = lambda: SimpleNamespace(username="dreaminate", user_id="dreaminate")
    try:
        client = TestClient(main.app)
        for expected_version, kind in [(2, "ghost"), (3, "auto")]:
            response = client.post(
                "/api/research-os/graph/canvas_asset_mutations",
                json={
                    "command_ref": f"canvas_command:{kind}_strategy:001",
                    "source_desk": "strategy",
                    "actor_source": "user_manual",
                    "target_asset_type": "StrategyBook",
                    "target_ref": qro.qro_id,
                    "field_path": f"output_contract.canvas_{kind}_ref",
                    "operation": "set_ref",
                    "canonical_command_ref": f"research_graph_command:strategy_canvas_{kind}",
                    "audit_ref": f"audit:canvas:{kind}:001",
                    "value_ref": f"canvas_{kind}:strategy:qro1:patch",
                    "value_hash": f"hash_canvas_{kind}_1a2b3c",
                    "evidence_refs": [f"unit:canvas_{kind}_writeback"],
                },
            )
            assert response.status_code == 200
            body = response.json()
            assert body["qro_version"] == expected_version
            assert body["updated_field_path"] == f"output_contract.canvas_{kind}_ref"
    finally:
        main.app.dependency_overrides.pop(require_user_dependency, None)

    updated = store.qro(qro.qro_id)
    assert updated.output_contract["canvas_ghost_ref"] == "canvas_ghost:strategy:qro1:patch"
    assert updated.output_contract["canvas_ghost_hash"] == "hash_canvas_ghost_1a2b3c"
    assert updated.output_contract["canvas_auto_ref"] == "canvas_auto:strategy:qro1:patch"
    assert updated.output_contract["canvas_auto_hash"] == "hash_canvas_auto_1a2b3c"
    assert "unit:canvas_ghost_writeback" in updated.evidence_refs
    assert "unit:canvas_auto_writeback" in updated.evidence_refs
    [projection] = store.projection_index(qro_type="StrategyBook")
    assert "canvas_ghost_ref" in projection.output_contract_keys
    assert "canvas_auto_ref" in projection.output_contract_keys
    projection_json = json.dumps(projection.to_audit_dict())
    assert "canvas_ghost:strategy:qro1:patch" not in projection_json
    assert "canvas_auto:strategy:qro1:patch" not in projection_json
    assert "hash_canvas_ghost_1a2b3c" not in projection_json
    assert "hash_canvas_auto_1a2b3c" not in projection_json


def test_research_graph_canvas_layout_api_records_layout_and_replays_exact_projection(tmp_path, monkeypatch):
    from app import main

    path = tmp_path / "research_graph_commands.jsonl"
    store = PersistentResearchGraphStore(path)
    qro = _qro(output_contract={"strategy_book_ref": "strategy:demo"})
    store.apply(_command(qro))
    _install_goal_proof_stores(main, tmp_path, monkeypatch, store)
    main.app.dependency_overrides[require_user_dependency] = lambda: SimpleNamespace(username="dreaminate", user_id="dreaminate")
    try:
        response = TestClient(main.app).post(
            "/api/research-os/graph/canvas_layouts",
            json={
                "command_ref": "canvas_command:layout_strategy:002",
                "source_desk": "strategy",
                "actor_source": "user_manual",
                "target_asset_type": "StrategyBook",
                "target_ref": qro.qro_id,
                "node_id": f"canvas_node:qro:{qro.qro_id}",
                "x": 612.5,
                "y": 177.25,
                "w": 208,
                "canonical_command_ref": "research_graph_command:strategy_canvas_layout_exact",
                "audit_ref": "audit:canvas:layout:002",
                "evidence_refs": ["unit:canvas_layout_exact_drag"],
            },
        )
    finally:
        main.app.dependency_overrides.pop(require_user_dependency, None)

    assert response.status_code == 200
    body = response.json()
    assert body["accepted"] is True
    assert body["command_type"] == "record_canvas_layout"
    assert body["layout_ref"].startswith(f"canvas_layout:{qro.qro_id}:hash_canvas_layout_")
    assert body["layout_hash"].startswith("hash_canvas_layout_")
    assert body["updated_field_path"] == "output_contract.canvas_layout_ref"
    assert body["compiler_ir_ref"].startswith("compiler_ir:")
    assert body["compiler_pass_ref"].startswith("compiler_pass:")
    assert body["entrypoint_coverage_ref"].startswith("goal_entrypoint_coverage:")
    commands = store.commands()
    assert [command.command_type for command in commands] == [
        "upsert_qro",
        "record_canvas_layout",
        "record_canvas_mutation",
        "upsert_qro",
    ]
    updated = store.qro(qro.qro_id)
    assert updated.output_contract["canvas_layout_ref"] == body["layout_ref"]
    assert updated.output_contract["canvas_layout_hash"] == body["layout_hash"]
    layout = store.canvas_layout(body["layout_ref"])
    assert layout.qro_id == qro.qro_id
    assert layout.node_id == f"canvas_node:qro:{qro.qro_id}"
    assert layout.x == 612.5
    assert layout.y == 177.25
    assert layout.w == 208
    assert "unit:canvas_layout_exact_drag" in layout.evidence_refs

    canvas = TestClient(main.app).get(
        "/api/research-os/graph/canvas_projection",
        params={"qro_type": "StrategyBook"},
    )
    assert canvas.status_code == 200
    qro_node = next(node for node in canvas.json()["nodes"] if node["id"] == f"canvas_node:qro:{qro.qro_id}")
    assert qro_node["x"] == 612.5
    assert qro_node["y"] == 177.25
    assert qro_node["w"] == 208
    raw_canvas = json.dumps(canvas.json())
    assert body["layout_ref"] not in raw_canvas
    coverage = main.GOAL_ENTRYPOINT_COVERAGE_REGISTRY.coverage(body["entrypoint_coverage_ref"])
    assert coverage.entry_source == "canvas"
    assert coverage.entrypoint_ref == "canvas:layout"
    assert coverage.qro_refs == (qro.qro_id,)
    assert coverage.compiler_ir_refs == (body["compiler_ir_ref"],)
    assert coverage.compiler_pass_refs == (body["compiler_pass_ref"],)
    assert coverage.evidence_refs
    assert body["layout_hash"] not in raw_canvas


def test_research_graph_canvas_layout_replays_after_store_reload(tmp_path, monkeypatch):
    from app import main

    path = tmp_path / "research_graph_commands.jsonl"
    store = PersistentResearchGraphStore(path)
    qro = _qro(output_contract={"strategy_book_ref": "strategy:demo"})
    store.apply(_command(qro))
    _install_goal_proof_stores(main, tmp_path, monkeypatch, store)
    main.app.dependency_overrides[require_user_dependency] = lambda: SimpleNamespace(username="dreaminate", user_id="dreaminate")
    try:
        response = TestClient(main.app).post(
            "/api/research-os/graph/canvas_layouts",
            json={
                "command_ref": "canvas_command:layout_strategy:reload",
                "source_desk": "strategy",
                "actor_source": "user_manual",
                "target_asset_type": "StrategyBook",
                "target_ref": qro.qro_id,
                "node_id": f"canvas_node:qro:{qro.qro_id}",
                "x": 455,
                "y": 99,
                "w": 190,
                "canonical_command_ref": "research_graph_command:strategy_canvas_layout_reload",
                "audit_ref": "audit:canvas:layout:reload",
                "evidence_refs": ["unit:canvas_layout_reload"],
            },
        )
    finally:
        main.app.dependency_overrides.pop(require_user_dependency, None)
    assert response.status_code == 200

    reloaded = PersistentResearchGraphStore(path)
    monkeypatch.setattr(main, "RESEARCH_GRAPH_STORE", reloaded)
    canvas = TestClient(main.app).get(
        "/api/research-os/graph/canvas_projection",
        params={"qro_type": "StrategyBook"},
    )

    assert canvas.status_code == 200
    qro_node = next(node for node in canvas.json()["nodes"] if node["id"] == f"canvas_node:qro:{qro.qro_id}")
    assert qro_node["x"] == 455
    assert qro_node["y"] == 99
    assert qro_node["w"] == 190
    assert [command.command_type for command in reloaded.commands()] == [
        "upsert_qro",
        "record_canvas_layout",
        "record_canvas_mutation",
        "upsert_qro",
    ]


def test_research_graph_canvas_layout_projection_rejects_missing_bound_layout(tmp_path, monkeypatch):
    from app import main

    path = tmp_path / "research_graph_commands.jsonl"
    store = PersistentResearchGraphStore(path)
    qro = _qro(
        output_contract={
            "strategy_book_ref": "strategy:demo",
            "canvas_layout_ref": "canvas_layout:missing:hash_canvas_layout_missing",
            "canvas_layout_hash": "hash_canvas_layout_missing",
        }
    )
    store.apply(_command(qro))
    monkeypatch.setattr(main, "RESEARCH_GRAPH_STORE", store)

    response = TestClient(main.app).get(
        "/api/research-os/graph/canvas_projection",
        params={"qro_type": "StrategyBook"},
    )

    assert response.status_code == 422
    assert "canvas layout ref is missing" in response.json()["detail"]


def test_research_graph_canvas_layout_api_rejects_live_qro_without_commands(tmp_path, monkeypatch):
    from app import main

    path = tmp_path / "research_graph_commands.jsonl"
    store = PersistentResearchGraphStore(path)
    qro = _qro(runtime_status=RuntimeStatus.LIVE, output_contract={"strategy_book_ref": "strategy:live"})
    store.apply(_command(qro))
    monkeypatch.setattr(main, "RESEARCH_GRAPH_STORE", store)
    main.app.dependency_overrides[require_user_dependency] = lambda: SimpleNamespace(username="dreaminate", user_id="dreaminate")
    try:
        response = TestClient(main.app).post(
            "/api/research-os/graph/canvas_layouts",
            json={
                "command_ref": "canvas_command:layout_live:001",
                "source_desk": "strategy",
                "actor_source": "user_manual",
                "target_asset_type": "StrategyBook",
                "target_ref": qro.qro_id,
                "node_id": f"canvas_node:qro:{qro.qro_id}",
                "x": 100,
                "y": 100,
                "w": 184,
                "canonical_command_ref": "research_graph_command:live_canvas_layout",
                "audit_ref": "audit:canvas:layout:live",
                "evidence_refs": ["unit:canvas_layout_live"],
            },
        )
    finally:
        main.app.dependency_overrides.pop(require_user_dependency, None)

    assert response.status_code == 422
    assert "cannot edit live QRO" in response.json()["detail"]
    assert [command.command_type for command in store.commands()] == ["upsert_qro"]


def test_research_graph_canvas_asset_mutation_api_rejects_live_qro(tmp_path, monkeypatch):
    from app import main

    path = tmp_path / "research_graph_commands.jsonl"
    store = PersistentResearchGraphStore(path)
    qro = _qro(runtime_status=RuntimeStatus.LIVE, output_contract={"strategy_book_ref": "strategy:live"})
    store.apply(_command(qro))
    monkeypatch.setattr(main, "RESEARCH_GRAPH_STORE", store)
    main.app.dependency_overrides[require_user_dependency] = lambda: SimpleNamespace(username="dreaminate", user_id="dreaminate")
    try:
        response = TestClient(main.app).post(
            "/api/research-os/graph/canvas_asset_mutations",
            json={
                "command_ref": "canvas_command:update_live:001",
                "source_desk": "strategy",
                "actor_source": "user_manual",
                "target_asset_type": "StrategyBook",
                "target_ref": qro.qro_id,
                "field_path": "output_contract.canvas_edit_ref",
                "operation": "set_ref",
                "canonical_command_ref": "research_graph_command:live_canvas_update",
                "audit_ref": "audit:canvas:live",
                "value_ref": "canvas_edit:strategy:live",
                "evidence_refs": ["unit:canvas_asset_mutation"],
            },
        )
    finally:
        main.app.dependency_overrides.pop(require_user_dependency, None)

    assert response.status_code == 422
    assert "cannot edit live QRO" in response.json()["detail"]
    assert [command.command_type for command in store.commands()] == ["upsert_qro"]


def test_persistent_research_graph_store_rejects_malformed_history(tmp_path):
    path = tmp_path / "research_graph_commands.jsonl"
    path.write_text('{"schema_version": 1, "command": {"command_type": "upsert_qro"}}\n', encoding="utf-8")

    with pytest.raises(ResearchGraphError, match="invalid persisted Research Graph command"):
        PersistentResearchGraphStore(path)
