from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app import main
from app.auth import require_user_dependency
from app.research_os import (
    ActorSource,
    AssetRAGDocument,
    ConsistencyStatus,
    DefinitionStatus,
    EntrySource,
    EvidenceStatus,
    IngestionSkillUpdateRecord,
    MathematicalSpineChainRecord,
    ModelArtifactFormat,
    ModelArtifactManifestEntry,
    ModelArtifactSource,
    ModelGovernancePassport,
    ModelRiskTier,
    PersistentAssetLifecycleRegistry,
    PersistentMathematicalSpineChainRegistry,
    PersistentModelGovernanceRegistry,
    PersistentResearchAssetRAGIndex,
    PersistentResearchGraphStore,
    QRORecord,
    QROType,
    RAGPermission,
    RAGProjection,
    RecertificationTrigger,
    ResearchGraphCommand,
    RuntimeStatus,
    SafeLoadingPolicy,
)
from app.research_os.platform_coverage import (
    PersistentPlatformCoverageRegistry,
    REQUIRED_PLATFORM_ROWS,
    PlatformCapabilityRecord,
    PlatformRow,
    PlatformSpecificRef,
    RealPlatformCoverageRefResolver,
    platform_capability_record_to_dict,
    set_default_platform_coverage_resolver,
    validate_platform_capability,
    validate_platform_capability_real_backing,
    validate_platform_coverage,
    validate_platform_coverage_real_manifest,
)


@pytest.fixture(autouse=True)
def _fail_closed_default_resolver():
    """Each test starts with the module default resolver unset (fail-closed) and
    restores it afterwards, so a scenario that wires a real resolver cannot leak
    a non-fail-closed default into another test."""

    set_default_platform_coverage_resolver(None)
    yield
    set_default_platform_coverage_resolver(None)


def _codes(decision) -> set[str]:
    return {violation.code for violation in decision.violations}


def _record(row: PlatformRow | str, **overrides) -> PlatformCapabilityRecord:
    data = {
        "m_row": row,
        "qro_ref": f"qro:{row}",
        "research_graph_ref": "research_graph",
        "lifecycle_ref": f"lifecycle:{row}",
        "governance_ref": f"governance:{row}",
        "rag_ref": f"rag:{row}",
        "math_spine_ref": f"math:{row}",
        "evidence_refs": (f"evidence:{row}",),
        "specific_refs": (),
    }
    data.update(overrides)
    return PlatformCapabilityRecord(**data)


def _specific(*keys: str) -> tuple[PlatformSpecificRef, ...]:
    return tuple(PlatformSpecificRef(key=key, ref=f"{key}:001") for key in keys)


_SPECIFIC_PREFIX_BY_KEY = {
    "ingestion_skill_ref": "ingestion_skill",
    "instrument_spec_ref": "instrument_spec",
    "model_passport_ref": "model_passport",
    "validation_dossier_ref": "validation_dossier",
    "signal_contract_ref": "signal_contract",
    "strategy_book_ref": "strategy_book",
    "execution_boundary_ref": "execution_boundary",
    "market_capability_matrix_ref": "market_capability_matrix",
    "llm_gateway_ref": "llm_gateway",
    "model_routing_policy_ref": "model_routing_policy",
    "credential_pool_ref": "credential_pool",
    "theory_implementation_binding_ref": "theory_binding",
    "typed_canvas_projection_ref": "typed_canvas_projection",
    "canonical_code_command_ref": "canonical_code_command",
    "consistency_check_ref": "consistency_check",
    "secret_ref": "secret",
    "kill_switch_ref": "kill_switch",
    "mock_label_ref": "mock_label",
    "asset_category_ref": "asset_category",
}


def _row_slug(row: PlatformRow | str) -> str:
    return str(row.value if hasattr(row, "value") else row).replace("-", "_")


def _real_specific(row: PlatformRow | str, *keys: str) -> tuple[PlatformSpecificRef, ...]:
    row_slug = _row_slug(row)
    return tuple(
        PlatformSpecificRef(
            key=key,
            ref=f"{_SPECIFIC_PREFIX_BY_KEY[key]}:platform_{row_slug}_{key}_real",
        )
        for key in keys
    )


def _real_record(row: PlatformRow | str, **overrides) -> PlatformCapabilityRecord:
    row_slug = _row_slug(row)
    data = {
        "m_row": row,
        "qro_ref": f"qro_platform_{row_slug}_real",
        "research_graph_ref": f"rgcmd_platform_{row_slug}_real",
        "lifecycle_ref": f"lifecycle_event:platform_{row_slug}_real",
        "governance_ref": f"governance_decision:platform_{row_slug}_real",
        "rag_ref": f"rag_asset:platform_{row_slug}_real",
        "math_spine_ref": f"math_spine_chain:platform_{row_slug}_real",
        "evidence_refs": (f"evidence:platform_{row_slug}_real",),
        "specific_refs": (),
    }
    data.update(overrides)
    return PlatformCapabilityRecord(**data)


def _complete_manifest() -> tuple[PlatformCapabilityRecord, ...]:
    records = []
    for row in REQUIRED_PLATFORM_ROWS:
        keys = {
            PlatformRow.M3.value: ("ingestion_skill_ref", "instrument_spec_ref"),
            PlatformRow.M6.value: ("model_passport_ref", "validation_dossier_ref"),
            PlatformRow.M7_M8.value: ("signal_contract_ref", "strategy_book_ref"),
            PlatformRow.M9.value: ("execution_boundary_ref", "market_capability_matrix_ref"),
            PlatformRow.M14.value: (
                "llm_gateway_ref",
                "model_routing_policy_ref",
                "credential_pool_ref",
                "theory_implementation_binding_ref",
            ),
            PlatformRow.M15.value: ("typed_canvas_projection_ref",),
            PlatformRow.M18.value: ("canonical_code_command_ref", "consistency_check_ref"),
            PlatformRow.M20.value: ("secret_ref", "llm_gateway_ref", "kill_switch_ref"),
            PlatformRow.M21.value: ("mock_label_ref", "asset_category_ref"),
        }.get(row, ())
        records.append(_record(row, specific_refs=_specific(*keys)))
    return tuple(records)


def _real_manifest() -> tuple[PlatformCapabilityRecord, ...]:
    records = []
    for row in REQUIRED_PLATFORM_ROWS:
        keys = {
            PlatformRow.M3.value: ("ingestion_skill_ref", "instrument_spec_ref"),
            PlatformRow.M6.value: ("model_passport_ref", "validation_dossier_ref"),
            PlatformRow.M7_M8.value: ("signal_contract_ref", "strategy_book_ref"),
            PlatformRow.M9.value: ("execution_boundary_ref", "market_capability_matrix_ref"),
            PlatformRow.M14.value: (
                "llm_gateway_ref",
                "model_routing_policy_ref",
                "credential_pool_ref",
                "theory_implementation_binding_ref",
            ),
            PlatformRow.M15.value: ("typed_canvas_projection_ref",),
            PlatformRow.M18.value: ("canonical_code_command_ref", "consistency_check_ref"),
            PlatformRow.M20.value: ("secret_ref", "llm_gateway_ref", "kill_switch_ref"),
            PlatformRow.M21.value: ("mock_label_ref", "asset_category_ref"),
        }.get(row, ())
        records.append(_real_record(row, specific_refs=_real_specific(row, *keys)))
    return tuple(records)


def _payload(records: tuple[PlatformCapabilityRecord, ...]) -> dict:
    return {"records": [platform_capability_record_to_dict(record) for record in records]}


def _client_with_platform_registry(tmp_path, monkeypatch):
    store = PersistentPlatformCoverageRegistry(tmp_path / "platform_coverage_manifest.jsonl")
    monkeypatch.setattr(main, "PLATFORM_COVERAGE_REGISTRY", store)
    main.app.dependency_overrides[require_user_dependency] = lambda: SimpleNamespace(
        username="u1",
        user_id="u1",
    )
    return TestClient(main.app), store


# ---------------------------------------------------------------------------
# Real-backing fixtures: mint genuine records in the genuine backend stores so
# the resolver resolves their ids to real objects (not lexically-shaped strings).
# These reuse the same record shapes as the per-store unit tests.
# ---------------------------------------------------------------------------


def _mk_qro(**overrides) -> QRORecord:
    data = dict(
        qro_type=QROType.STRATEGY_BOOK,
        owner="dreaminate",
        actor=ActorSource.USER_MANUAL,
        input_contract={"strategy_id": "strategy_platform", "code_hash": "hash_code"},
        output_contract={"strategy_book_ref": "strategy:platform"},
        market="crypto",
        universe="BTCUSDT",
        horizon="30d",
        frequency="1d",
        lineage=("ide", "strategy", "save"),
        implementation_hash="strategy:platform_hash_code",
        assumptions=("strategy source was saved before graph write",),
        known_limits=("platform coverage real-backing unit only",),
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


def _mk_command(qro: QRORecord) -> ResearchGraphCommand:
    return ResearchGraphCommand(
        source=EntrySource.IDE,
        command_type="upsert_qro",
        actor_source=ActorSource.USER_MANUAL,
        actor="dreaminate",
        payload={"qro": qro},
        evidence_refs=("unit:platform_real_backing",),
    )


def _mk_chain(**overrides) -> MathematicalSpineChainRecord:
    data = {
        "chain_ref": "math_spine_chain:platform_real_backing:v1",
        "data_semantics_ref": "dataset_semantics:btc_1d",
        "factor_ref": "factor:momentum_20d",
        "model_ref": "model:momentum_classifier:v1",
        "forecast_ref": "forecast:btc_momentum:v1",
        "signal_contract_ref": "signal_contract:btc_momentum:v1",
        "strategy_book_ref": "strategy_book:btc_momentum:v1",
        "portfolio_policy_ref": "portfolio_policy:btc_momentum:v1",
        "risk_policy_ref": "risk_policy:btc_momentum:v1",
        "execution_policy_ref": "execution_policy:paper_btc:v1",
        "backtest_run_ref": "backtest_run:bt1",
        "attribution_ref": "attribution:bt1",
        "monitor_ref": "monitor:weekly_btc_momentum",
        "theory_binding_refs": ("tbind:momentum", "tbind:portfolio-risk"),
        "consistency_check_refs": ("ccheck:momentum", "ccheck:risk"),
        "methodology_choice_ref": "mchoice:standard",
        "responsibility_boundary_ref": "resp:standard",
        "evidence_refs": ("evidence:bt1", "evidence:monitor"),
        "validation_refs": ("pytest:test_platform_coverage",),
        "consistency_verdict": ConsistencyStatus.ACCEPTED,
        "target_runtime": RuntimeStatus.PAPER,
        "recorded_by": "u1",
    }
    data.update(overrides)
    return MathematicalSpineChainRecord(**data)


def _mk_ingestion_update(**overrides) -> IngestionSkillUpdateRecord:
    data = dict(
        update_ref="ingestion:update:platform_real",
        skill_ref="skill:rest",
        skill_version="v1",
        source_ref="datasource:rest",
        secret_ref="secretref:rest:read",
        dataset_version_ref="dataset_version:btc",
        checksum="sha256:abc",
        lineage_ref="lineage:btc",
        quality_verdict_ref="quality:pass",
        known_at_ref="known_at:ingest_time",
        effective_at_ref="effective_at:bar_close",
        evidence_refs=("connector_check:btc",),
    )
    data.update(overrides)
    return IngestionSkillUpdateRecord(**data)


def _mk_artifact(**overrides) -> ModelArtifactManifestEntry:
    data = {
        "artifact_ref": "artifact:model:v1",
        "uri": "registry://models/momentum/v1/model.safetensors",
        "artifact_format": ModelArtifactFormat.SAFE_TENSORS,
        "source": ModelArtifactSource.PROJECT_PRODUCED,
        "content_hash": "sha256:abc123",
        "producer_run_ref": "training_run:001",
        "sandbox_inspection_ref": "inspect:model:v1",
    }
    data.update(overrides)
    return ModelArtifactManifestEntry(**data)


def _mk_passport(**overrides) -> ModelGovernancePassport:
    data = {
        "model_version_ref": "model_version:momentum:v1",
        "model_type_card_ref": "model_type_card:gbdt",
        "training_plan_ref": "training_plan:momentum",
        "training_run_ref": "training_run:001",
        "model_risk_tier": ModelRiskTier.MEDIUM,
        "materiality": "paper-trading research signal",
        "intended_use": ("forecast next-period relative return",),
        "prohibited_use": ("direct live order placement",),
        "dataset_refs": ("dataset_version:btc_daily:v1",),
        "feature_refs": ("feature:momentum_20d",),
        "label_refs": ("label:forward_return_1d",),
        "training_code_hash": "codehash:train:001",
        "artifact_manifest": (_mk_artifact(),),
        "safe_loading_policy": SafeLoadingPolicy(
            sandboxed_load_inspect=True,
            prefer_safe_tensors=True,
            torch_weights_only=True,
        ),
        "vendor_dependency_refs": ("none",),
        "foundation_model_dependency_refs": ("none",),
        "monitoring_requirements": ("performance degradation monitor",),
        "recertification_triggers": tuple(RecertificationTrigger),
        "validation_dossier_ref": "validation_dossier:momentum:v1",
        "challenger_result": "challenger did not outperform champion",
    }
    data.update(overrides)
    return ModelGovernancePassport(**data)


def _mk_doc(**overrides) -> AssetRAGDocument:
    data = {
        "source_id": "asset:btc-momentum",
        "version": "v1",
        "title": "BTC momentum strategy evidence",
        "body": "BTCUSDT daily momentum backtest uses dataset_version dsver:btc-2023 and TheoryImplementationBinding tbind_mom.",
        "projection": RAGProjection.STRATEGY,
        "asset_ref": "qro:btc-momentum",
        "permission": RAGPermission(
            allowed_users=("u1",), allowed_desks=("strategy",), allowed_assets=("qro:btc-momentum",)
        ),
        "applicability": "crypto daily research and paper only",
        "source_kind": "ValidationDossier",
        "metadata": {"dataset_version": "dsver:btc-2023"},
        "evidence_label": "candidate_context",
    }
    data.update(overrides)
    return AssetRAGDocument(**data)


def _real_backing(tmp_path):
    """Mint one genuine record in each backend store and return the stores, a
    RealPlatformCoverageRefResolver over them, and the dict of the six real ids."""

    research_graph = PersistentResearchGraphStore(tmp_path / "research_graph_commands.jsonl")
    lifecycle = PersistentAssetLifecycleRegistry(tmp_path / "asset_lifecycle.jsonl")
    governance = PersistentModelGovernanceRegistry(tmp_path / "model_governance.jsonl")
    rag = PersistentResearchAssetRAGIndex(tmp_path / "research_asset_rag.jsonl")
    spine = PersistentMathematicalSpineChainRegistry(tmp_path / "mathematical_spine_chains.jsonl")

    qro = _mk_qro()
    command_id = research_graph.apply(_mk_command(qro))
    chain = spine.record_chain(_mk_chain())
    update = lifecycle.record_ingestion_skill_update(_mk_ingestion_update())
    passport = governance.record_passport(_mk_passport())
    doc = _mk_doc()
    rag.add(doc)

    resolver = RealPlatformCoverageRefResolver(
        research_graph_store=research_graph,
        lifecycle_registry=lifecycle,
        governance_registry=governance,
        rag_index=rag,
        spine_chain_registry=spine,
    )
    common = {
        "qro_ref": qro.qro_id,
        "research_graph_ref": command_id,
        "lifecycle_ref": update.update_ref,
        "governance_ref": passport.passport_id,
        "rag_ref": doc.document_id,
        "math_spine_ref": chain.chain_ref,
    }
    return SimpleNamespace(
        research_graph=research_graph,
        lifecycle=lifecycle,
        governance=governance,
        rag=rag,
        spine=spine,
        resolver=resolver,
        common=common,
    )


def _backed_record(row: PlatformRow | str, common: dict, **overrides) -> PlatformCapabilityRecord:
    row_slug = _row_slug(row)
    data = {
        "m_row": row,
        "qro_ref": common["qro_ref"],
        "research_graph_ref": common["research_graph_ref"],
        "lifecycle_ref": common["lifecycle_ref"],
        "governance_ref": common["governance_ref"],
        "rag_ref": common["rag_ref"],
        "math_spine_ref": common["math_spine_ref"],
        "evidence_refs": (f"evidence:platform_{row_slug}_real",),
        "specific_refs": (),
    }
    data.update(overrides)
    return PlatformCapabilityRecord(**data)


def _backed_manifest(common: dict) -> tuple[PlatformCapabilityRecord, ...]:
    records = []
    for row in REQUIRED_PLATFORM_ROWS:
        keys = {
            PlatformRow.M3.value: ("ingestion_skill_ref", "instrument_spec_ref"),
            PlatformRow.M6.value: ("model_passport_ref", "validation_dossier_ref"),
            PlatformRow.M7_M8.value: ("signal_contract_ref", "strategy_book_ref"),
            PlatformRow.M9.value: ("execution_boundary_ref", "market_capability_matrix_ref"),
            PlatformRow.M14.value: (
                "llm_gateway_ref",
                "model_routing_policy_ref",
                "credential_pool_ref",
                "theory_implementation_binding_ref",
            ),
            PlatformRow.M15.value: ("typed_canvas_projection_ref",),
            PlatformRow.M18.value: ("canonical_code_command_ref", "consistency_check_ref"),
            PlatformRow.M20.value: ("secret_ref", "llm_gateway_ref", "kill_switch_ref"),
            PlatformRow.M21.value: ("mock_label_ref", "asset_category_ref"),
        }.get(row, ())
        records.append(_backed_record(row, common, specific_refs=_real_specific(row, *keys)))
    return tuple(records)


def test_platform_capability_requires_common_qro_graph_lifecycle_governance_rag_and_math_refs():
    decision = validate_platform_capability(
        _record(
            PlatformRow.M10,
            qro_ref=None,
            research_graph_ref=None,
            lifecycle_ref=None,
            evidence_refs=(),
        )
    )
    assert not decision.accepted
    assert _codes(decision) >= {
        "platform_capability_missing_common_ref",
        "platform_capability_missing_evidence",
    }


def test_platform_coverage_manifest_requires_every_m_row():
    records = tuple(record for record in _complete_manifest() if record.m_row != PlatformRow.M14.value)
    decision = validate_platform_coverage(records)
    assert not decision.accepted
    assert "platform_capability_row_missing" in _codes(decision)


def test_m14_agent_platform_requires_gateway_routing_credential_pool_and_math_binding():
    decision = validate_platform_capability(_record(PlatformRow.M14))
    assert not decision.accepted
    assert "platform_capability_missing_specific_ref" in _codes(decision)


def test_m21_examples_require_mock_label_and_asset_category_refs():
    decision = validate_platform_capability(_record(PlatformRow.M21, specific_refs=_specific("mock_label_ref")))
    assert not decision.accepted
    assert "platform_capability_missing_specific_ref" in _codes(decision)


def test_complete_platform_coverage_manifest_accepts_all_rows():
    decision = validate_platform_coverage(_complete_manifest())
    assert decision.accepted
    assert decision.violations == ()


def test_real_platform_manifest_requires_registry_shaped_refs():
    decision = validate_platform_coverage_real_manifest(_complete_manifest())
    assert not decision.accepted
    assert "platform_capability_ref_not_backed" in _codes(decision)


def test_real_platform_manifest_lexically_shaped_refs_are_not_enough_without_backing():
    # _real_manifest() refs all carry the registry-shaped prefixes (qro_, rgcmd_,
    # lifecycle_event:, governance_decision:, rag_asset:, math_spine_chain:) and
    # contain no synthetic/placeholder token -- exactly what the old lexical-only
    # gate rubber-stamped as "real backing". With real resolution + the
    # fail-closed default they resolve to nothing, so the manifest is rejected.
    # (Mutation guard: revert the validator to lexical-prefix matching and this
    # assertion turns red, because lexical-only would accept these refs.)
    decision = validate_platform_coverage_real_manifest(_real_manifest())
    assert not decision.accepted
    assert "platform_capability_ref_not_backed" in _codes(decision)


def test_real_platform_manifest_accepts_and_replays_all_rows(tmp_path):
    # Genuine real backing: refs are the ids of records actually minted in the
    # real QRO / research-graph / lifecycle / governance / RAG / spine stores,
    # resolved through RealPlatformCoverageRefResolver -- not lexical strings.
    backing = _real_backing(tmp_path)
    manifest = _backed_manifest(backing.common)

    store = PersistentPlatformCoverageRegistry(
        tmp_path / "platform_coverage_manifest.jsonl", resolver=backing.resolver
    )
    recorded = store.record_manifest(manifest)
    assert len(recorded) == len(REQUIRED_PLATFORM_ROWS)
    assert validate_platform_coverage_real_manifest(
        tuple(store.records()), resolver=backing.resolver
    ).accepted

    reloaded = PersistentPlatformCoverageRegistry(
        tmp_path / "platform_coverage_manifest.jsonl", resolver=backing.resolver
    )
    assert [record.m_row for record in reloaded.records()] == list(REQUIRED_PLATFORM_ROWS)
    assert validate_platform_coverage_real_manifest(
        tuple(reloaded.records()), resolver=backing.resolver
    ).accepted


def test_real_platform_manifest_rejects_synthetic_placeholder_manifest_without_writing(tmp_path):
    store = PersistentPlatformCoverageRegistry(tmp_path / "platform_coverage_manifest.jsonl")

    with pytest.raises(ValueError, match="platform_capability_ref_not_backed"):
        store.record_manifest(_complete_manifest())

    assert store.records() == []
    assert not (tmp_path / "platform_coverage_manifest.jsonl").exists()


def test_real_m14_requires_gateway_routing_credentials_and_theory_binding():
    decision = validate_platform_capability_real_backing(
        _real_record(
            PlatformRow.M14,
            specific_refs=_real_specific(
                PlatformRow.M14,
                "model_routing_policy_ref",
                "credential_pool_ref",
                "theory_implementation_binding_ref",
            ),
        )
    )
    assert not decision.accepted
    assert "platform_capability_missing_specific_ref" in _codes(decision)


def test_real_m21_requires_mock_label_and_asset_category_refs():
    decision = validate_platform_capability_real_backing(
        _real_record(PlatformRow.M21, specific_refs=_real_specific(PlatformRow.M21, "mock_label_ref"))
    )
    assert not decision.accepted
    assert "platform_capability_missing_specific_ref" in _codes(decision)


def test_platform_coverage_api_records_summary_and_rejects_synthetic_manifest(tmp_path, monkeypatch):
    # The frozen endpoint resolves through the module default resolver (the DI
    # seam production wires at startup). Here we wire a resolver backed by real
    # stores holding real records, then post a genuinely-backed manifest.
    backing = _real_backing(tmp_path)
    set_default_platform_coverage_resolver(backing.resolver)
    client, store = _client_with_platform_registry(tmp_path, monkeypatch)
    try:
        synthetic_response = client.post("/api/research-os/platform/coverage_manifest", json=_payload(_complete_manifest()))
        assert synthetic_response.status_code == 422
        assert store.records() == []

        # Lexically-shaped but unbacked manifest is also rejected now (no rubber stamp).
        lexical_response = client.post("/api/research-os/platform/coverage_manifest", json=_payload(_real_manifest()))
        assert lexical_response.status_code == 422
        assert store.records() == []

        response = client.post(
            "/api/research-os/platform/coverage_manifest", json=_payload(_backed_manifest(backing.common))
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["recorded_by"] == "u1"
        assert body["platform_row_total"] == len(REQUIRED_PLATFORM_ROWS)
        assert body["full_platform_coverage"] is True

        summary = client.get("/api/research-os/platform/coverage_summary")
        assert summary.status_code == 200
        data = summary.json()
        assert data["platform_row_total"] == len(REQUIRED_PLATFORM_ROWS)
        assert data["platform_rows_present"] == list(REQUIRED_PLATFORM_ROWS)
        assert data["missing_platform_rows"] == []
        assert data["full_platform_coverage"] is True
    finally:
        main.app.dependency_overrides.pop(require_user_dependency, None)


def test_real_resolver_resolves_minted_records_and_rejects_unknown_ids(tmp_path):
    backing = _real_backing(tmp_path)
    resolver = backing.resolver
    common = backing.common

    # Each minted id resolves to a real object in its real store.
    assert resolver.has_qro(common["qro_ref"]) is True
    assert resolver.has_research_graph_command(common["research_graph_ref"]) is True
    assert resolver.has_lifecycle_record(common["lifecycle_ref"]) is True
    assert resolver.has_governance_record(common["governance_ref"]) is True
    assert resolver.has_rag_asset(common["rag_ref"]) is True
    assert resolver.has_math_spine_chain(common["math_spine_ref"]) is True

    # Lexically-valid-shaped ids that were never minted resolve to nothing.
    assert resolver.has_qro("qro_unbacked0000000000") is False
    assert resolver.has_research_graph_command("rgcmd_unbacked0000000000") is False
    assert resolver.has_lifecycle_record("ingestion:update:unbacked") is False
    assert resolver.has_governance_record("model_passport_unbacked0000") is False
    assert resolver.has_rag_asset("ragdoc_unbacked0000") is False
    assert resolver.has_math_spine_chain("math_spine_chain:unbacked:v1") is False

    # Empty ids never resolve.
    for getter in (
        resolver.has_qro,
        resolver.has_research_graph_command,
        resolver.has_lifecycle_record,
        resolver.has_governance_record,
        resolver.has_rag_asset,
        resolver.has_math_spine_chain,
    ):
        assert getter("") is False


@pytest.mark.parametrize(
    "field_name,unbacked_ref",
    [
        ("qro_ref", "qro_unbacked0000000000"),
        ("research_graph_ref", "rgcmd_unbacked0000000000"),
        ("lifecycle_ref", "lifecycle_event:unbacked_v1"),
        ("governance_ref", "governance_decision:unbacked_v1"),
        ("rag_ref", "rag_asset:unbacked_v1"),
        ("math_spine_ref", "math_spine_chain:unbacked_v1"),
    ],
)
def test_real_backing_gates_each_common_ref_by_resolution(tmp_path, field_name, unbacked_ref):
    # Teeth + per-field mutation guard for all six common refs.
    backing = _real_backing(tmp_path)

    # (a) Control: a genuinely-backed capability is accepted. The real lifecycle/
    #     governance/RAG ids only pass via resolution (they never match the legacy
    #     lexical prefixes), so a lexical-only regression on those fields turns
    #     this assertion red.
    assert validate_platform_capability_real_backing(
        _backed_record(PlatformRow.M10, backing.common), resolver=backing.resolver
    ).accepted

    # (b) Swap exactly this field to an id that PASSES the old lexical prefix but
    #     resolves to nothing -> rejected on this field. A lexical-only regression
    #     on qro/research_graph/math turns this red.
    common = dict(backing.common)
    common[field_name] = unbacked_ref
    decision = validate_platform_capability_real_backing(
        _backed_record(PlatformRow.M10, common), resolver=backing.resolver
    )
    assert not decision.accepted
    assert "platform_capability_ref_not_backed" in _codes(decision)
    assert field_name in {violation.field for violation in decision.violations}


def test_real_backing_rejects_goal_closure_ref_even_if_seeded_in_store(tmp_path):
    # Defends against the recursive fake-green: the removed closure materializer
    # seeded mathematical_spine_chains.jsonl with a math_spine_chain:goal_closure:*
    # record, so a pure resolution check would pass. The token ban rejects the ref
    # up front even though it really resolves in the store.
    backing = _real_backing(tmp_path)
    seeded = backing.spine.record_chain(
        _mk_chain(chain_ref="math_spine_chain:goal_closure:section_0_17:v1")
    )
    assert backing.resolver.has_math_spine_chain(seeded.chain_ref) is True

    seeded_common = dict(backing.common)
    seeded_common["math_spine_ref"] = seeded.chain_ref
    decision = validate_platform_capability_real_backing(
        _backed_record(PlatformRow.M10, seeded_common), resolver=backing.resolver
    )
    assert not decision.accepted
    assert "platform_capability_ref_not_backed" in _codes(decision)
    assert "math_spine_ref" in {violation.field for violation in decision.violations}


def test_real_backing_is_fail_closed_without_resolver(tmp_path):
    # Genuinely-backed refs, but no resolver wired and the module default unset
    # (autouse fixture): nothing is provably backed, so the gate rejects rather
    # than rubber-stamping. Guards against "accept on missing wiring".
    backing = _real_backing(tmp_path)
    decision = validate_platform_capability_real_backing(_backed_record(PlatformRow.M10, backing.common))
    assert not decision.accepted
    assert "platform_capability_ref_not_backed" in _codes(decision)
