from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from threading import Barrier
from types import SimpleNamespace

import pytest
from conftest import build_verified_spine_chain
from fastapi.testclient import TestClient

from app import main
from app.research_os import platform_coverage as platform_coverage_module
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
    SPECIFIC_REQUIRED_REFS,
    PlatformCapabilityRecord,
    PlatformCoverageCommitUncertain,
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
    "strategy_goal_ref": "strategy_goal",
    "hypothesis_card_ref": "hypothesis",
    "universe_definition_ref": "universe",
    "regime_scenario_ref": "regime",
    "ingestion_skill_ref": "ingestion_skill",
    "instrument_spec_ref": "instrument_spec",
    "factor_ref": "factor",
    "label_ref": "label",
    "model_passport_ref": "model_passport",
    "validation_dossier_ref": "validation_dossier",
    "signal_contract_ref": "signal_contract",
    "signal_validation_ref": "signal_validation",
    "strategy_book_ref": "strategy_book",
    "portfolio_policy_ref": "portfolio_policy",
    "execution_boundary_ref": "execution_boundary",
    "market_capability_matrix_ref": "market_capability_matrix",
    "backtest_run_ref": "backtest_run",
    "validation_methodology_ref": "validation_methodology",
    "validation_depth_ref": "validation_depth",
    "attribution_ref": "attribution",
    "monitor_ref": "monitor",
    "governed_asset_ref": "governed_asset",
    "lifecycle_transition_ref": "lifecycle_transition",
    "model_promotion_ref": "model_promotion",
    "approval_ref": "approval",
    "recertification_ref": "recertification",
    "dag_run_ref": "dag_run",
    "checkpoint_ref": "checkpoint",
    "replay_ref": "replay",
    "fork_ref": "fork",
    "rollback_ref": "rollback",
    "llm_gateway_ref": "llm_gateway",
    "model_routing_policy_ref": "model_routing_policy",
    "credential_pool_ref": "credential_pool",
    "theory_implementation_binding_ref": "tib",
    "typed_canvas_projection_ref": "typed_canvas_projection",
    "shared_asset_ref": "shared_asset",
    "permission_ref": "permission",
    "source_ref": "source",
    "status_ref": "status",
    "copy_trade_subscription_ref": "copy_trade_subscription",
    "runtime_promotion_ref": "runtime_promotion",
    "risk_gate_ref": "copy_risk_check",
    "execution_audit_ref": "copy_submission_audit",
    "canonical_code_command_ref": "canonical_code_command",
    "consistency_check_ref": "cc",
    "tutorial_asset_ref": "tutorial_asset",
    "weakness_disclosure_ref": "weakness_disclosure",
    "teaching_evidence_ref": "teaching_evidence",
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
            ref=(
                f"{_SPECIFIC_PREFIX_BY_KEY[key]}_platform_{row_slug}_{key}_real"
                if key
                in {
                    "theory_implementation_binding_ref",
                    "consistency_check_ref",
                    "copy_trade_subscription_ref",
                    "risk_gate_ref",
                    "execution_audit_ref",
                }
                else f"{_SPECIFIC_PREFIX_BY_KEY[key]}:platform_{row_slug}_{key}_real"
            ),
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
        keys = SPECIFIC_REQUIRED_REFS.get(row, ())
        records.append(_record(row, specific_refs=_specific(*keys)))
    return tuple(records)


def _real_manifest() -> tuple[PlatformCapabilityRecord, ...]:
    records = []
    for row in REQUIRED_PLATFORM_ROWS:
        keys = SPECIFIC_REQUIRED_REFS.get(row, ())
        records.append(_real_record(row, specific_refs=_real_specific(row, *keys)))
    return tuple(records)


def _payload(records: tuple[PlatformCapabilityRecord, ...]) -> dict:
    return {"records": [platform_capability_record_to_dict(record) for record in records]}


class _StrictPlatformTestResolver:
    """Explicit unit-test adapter; it is not production proof or a data materializer."""

    def __init__(self, owner: str | None = None):
        self.owner = owner

    def for_owner(self, owner: str):
        return _StrictPlatformTestResolver(owner)

    def _owned(self, ref: str) -> bool:
        value = str(ref or "")
        return bool(
            self.owner
            and (f":{self.owner}:" in value or f"_{self.owner}_" in value)
        )

    def has_qro(self, ref):
        return self._owned(ref)

    def has_research_graph_command(self, ref):
        return self._owned(ref)

    def has_lifecycle_record(self, ref):
        return self._owned(ref)

    def has_governance_record(self, ref):
        return self._owned(ref)

    def has_rag_asset(self, ref):
        return self._owned(ref)

    def has_math_spine_chain(self, ref):
        return self._owned(ref)

    def has_math_spine_member(self, chain_ref, member_type, ref):
        return self._owned(chain_ref) and self._owned(ref)

    def has_platform_evidence(self, record, ref):
        return self._owned(ref) and _row_slug(record.m_row) in ref

    def has_platform_specific_ref(self, key, ref, record):
        del key
        return self._owned(ref) and _row_slug(record.m_row) in ref

    def platform_linkage_violations(self, record):
        row_slug = _row_slug(record.m_row)
        if row_slug not in str(record.qro_ref) or row_slug not in str(record.research_graph_ref):
            return (("qro_ref", str(record.qro_ref), "test row QRO/graph linkage mismatch"),)
        return ()


def _owner_isolated_manifest(owner: str) -> tuple[PlatformCapabilityRecord, ...]:
    records = []
    for row in REQUIRED_PLATFORM_ROWS:
        row_slug = _row_slug(row)
        keys = SPECIFIC_REQUIRED_REFS_FOR_TEST.get(row, ())
        specifics = tuple(
            PlatformSpecificRef(
                key=key,
                ref=(
                    f"tib_{owner}_{row_slug}"
                    if key == "theory_implementation_binding_ref"
                    else f"cc_{owner}_{row_slug}"
                    if key == "consistency_check_ref"
                    else f"{_SPECIFIC_PREFIX_BY_KEY[key]}_{owner}_{row_slug}"
                    if key
                    in {
                        "copy_trade_subscription_ref",
                        "risk_gate_ref",
                        "execution_audit_ref",
                    }
                    else f"{_SPECIFIC_PREFIX_BY_KEY[key]}:{owner}:{row_slug}"
                ),
            )
            for key in keys
        )
        records.append(
            PlatformCapabilityRecord(
                m_row=row,
                qro_ref=f"qro:{owner}:{row_slug}",
                research_graph_ref=f"rgcmd:{owner}:{row_slug}",
                lifecycle_ref=f"lifecycle:{owner}:{row_slug}",
                governance_ref=f"governance:{owner}:{row_slug}",
                rag_ref=f"rag:{owner}:{row_slug}",
                math_spine_ref=f"math:{owner}:{row_slug}",
                evidence_refs=(f"audit:{owner}:{row_slug}",),
                specific_refs=specifics,
            )
        )
    return tuple(records)


def _mutated_owner_manifest(owner: str) -> tuple[PlatformCapabilityRecord, ...]:
    records = list(_owner_isolated_manifest(owner))
    first = records[0]
    records[0] = replace(
        first,
        qro_ref=f"qro:{owner}:{_row_slug(first.m_row)}:revision_2",
        evidence_refs=(f"audit:{owner}:{_row_slug(first.m_row)}:revision_2",),
    )
    return tuple(records)


SPECIFIC_REQUIRED_REFS_FOR_TEST = SPECIFIC_REQUIRED_REFS


def _client_with_platform_registry(tmp_path, monkeypatch, *, resolver=None):
    store = PersistentPlatformCoverageRegistry(
        tmp_path / "platform_coverage_manifest.jsonl", resolver=resolver
    )

    class _ServerDerivedTestProducers:
        @staticmethod
        def record_current_manifest(platform_registry, *, owner_user_id: str):
            return platform_registry.record_manifest(
                _owner_isolated_manifest(owner_user_id),
                owner_user_id=owner_user_id,
            )

    monkeypatch.setattr(main, "PLATFORM_COVERAGE_REGISTRY", store)
    monkeypatch.setattr(
        main,
        "PLATFORM_ROW_PRODUCER_REGISTRY",
        _ServerDerivedTestProducers(),
    )
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
        owner="u1",
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
        actor="u1",
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
        recorded_by="u1",
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

    qro = _mk_qro()
    command_id = research_graph.apply(_mk_command(qro))
    spine, chain, _spine_ledger = build_verified_spine_chain(tmp_path, _mk_chain())
    update = lifecycle.record_ingestion_skill_update(
        _mk_ingestion_update(),
        owner_user_id="u1",
    )
    passport = governance.record_passport(_mk_passport())
    doc = _mk_doc()
    rag.add_for_owner(doc, owner_user_id="u1")

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
    closure = spine.verified_chain_record_refs(chain.chain_ref, owner="u1")
    common["theory_implementation_binding_ref"] = closure.theory_binding_refs[0]
    common["consistency_check_ref"] = closure.consistency_check_refs[0]
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
        keys = SPECIFIC_REQUIRED_REFS.get(row, ())
        specific_refs = list(_real_specific(row, *keys))
        specific_refs = [
            PlatformSpecificRef(key=item.key, ref=common.get(item.key, item.ref))
            for item in specific_refs
        ]
        records.append(
            _backed_record(row, common, specific_refs=tuple(specific_refs))
        )
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


@pytest.mark.parametrize(
    "row,partial_keys",
    (
        (PlatformRow.M1_M2, ("strategy_goal_ref",)),
        (PlatformRow.M4_M5, ("factor_ref",)),
        (PlatformRow.M7_M8, ("signal_contract_ref", "strategy_book_ref")),
    ),
)
def test_early_platform_rows_require_complete_row_specific_semantics(row, partial_keys):
    decision = validate_platform_capability(
        _record(row, specific_refs=_specific(*partial_keys))
    )
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


def test_owner_enveloped_platform_registry_replays_isolated_unit_adapter_rows(tmp_path):
    resolver = _StrictPlatformTestResolver()
    manifest = _owner_isolated_manifest("u1")

    store = PersistentPlatformCoverageRegistry(
        tmp_path / "platform_coverage_manifest.jsonl", resolver=resolver
    )
    recorded = store.record_manifest(manifest, owner_user_id="u1")
    assert len(recorded) == len(REQUIRED_PLATFORM_ROWS)
    assert store.validate_manifest(
        tuple(store.records(owner_user_id="u1")), owner_user_id="u1"
    ).accepted
    assert store.records(owner_user_id="u2") == []

    reloaded = PersistentPlatformCoverageRegistry(
        tmp_path / "platform_coverage_manifest.jsonl", resolver=resolver
    )
    assert [record.m_row for record in reloaded.records(owner_user_id="u1")] == list(REQUIRED_PLATFORM_ROWS)
    assert reloaded.validate_manifest(
        tuple(reloaded.records(owner_user_id="u1")), owner_user_id="u1"
    ).accepted


def test_platform_registry_keeps_owner_manifests_separate_and_quarantines_v1(tmp_path):
    path = tmp_path / "platform_coverage_manifest.jsonl"
    legacy = {
        "schema_version": 1,
        "event_type": "platform_coverage_manifest_recorded",
        "records": [platform_capability_record_to_dict(record) for record in _complete_manifest()],
    }
    path.write_text(json.dumps(legacy) + "\n", encoding="utf-8")
    resolver = _StrictPlatformTestResolver()
    store = PersistentPlatformCoverageRegistry(path, resolver=resolver)
    assert store.legacy_quarantined_count == 1
    assert store.records(owner_user_id="u1") == []

    store.record_manifest(_owner_isolated_manifest("u1"), owner_user_id="u1")
    store.record_manifest(_owner_isolated_manifest("u2"), owner_user_id="u2")
    assert len(store.records(owner_user_id="u1")) == len(REQUIRED_PLATFORM_ROWS)
    assert len(store.records(owner_user_id="u2")) == len(REQUIRED_PLATFORM_ROWS)
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    assert [row.get("owner_user_id") for row in rows[1:]] == ["u1", "u2"]
    assert {row["schema_version"] for row in rows[1:]} == {2}

    reloaded = PersistentPlatformCoverageRegistry(path, resolver=resolver)
    assert reloaded.legacy_quarantined_count == 1
    assert len(reloaded.records(owner_user_id="u1")) == len(REQUIRED_PLATFORM_ROWS)
    assert len(reloaded.records(owner_user_id="u2")) == len(REQUIRED_PLATFORM_ROWS)


def test_platform_registry_append_normalizes_missing_terminal_newline(tmp_path):
    path = tmp_path / "platform_coverage_manifest.jsonl"
    resolver = _StrictPlatformTestResolver()
    store = PersistentPlatformCoverageRegistry(path, resolver=resolver)
    store.record_manifest(_owner_isolated_manifest("u1"), owner_user_id="u1")
    path.write_bytes(path.read_bytes().rstrip(b"\n"))

    store.record_manifest(_owner_isolated_manifest("u2"), owner_user_id="u2")

    reloaded = PersistentPlatformCoverageRegistry(path, resolver=resolver)
    assert len(reloaded.records(owner_user_id="u1")) == len(REQUIRED_PLATFORM_ROWS)
    assert len(reloaded.records(owner_user_id="u2")) == len(REQUIRED_PLATFORM_ROWS)


def test_platform_registry_exact_current_retry_is_byte_identical_and_reopens(tmp_path):
    path = tmp_path / "platform_coverage_manifest.jsonl"
    resolver = _StrictPlatformTestResolver()
    manifest = _owner_isolated_manifest("u1")
    store = PersistentPlatformCoverageRegistry(path, resolver=resolver)

    assert store.record_manifest(manifest, owner_user_id="u1") == manifest
    committed = path.read_bytes()
    assert store.record_manifest(manifest, owner_user_id="u1") == manifest
    assert path.read_bytes() == committed
    assert len(path.read_text(encoding="utf-8").splitlines()) == 1

    reloaded = PersistentPlatformCoverageRegistry(path, resolver=resolver)
    assert tuple(reloaded.records(owner_user_id="u1")) == manifest
    assert path.read_bytes() == committed


def test_platform_registry_rejects_stale_exact_replay_after_current_mutation(tmp_path):
    path = tmp_path / "platform_coverage_manifest.jsonl"
    resolver = _StrictPlatformTestResolver()
    original = _owner_isolated_manifest("u1")
    current = _mutated_owner_manifest("u1")
    store = PersistentPlatformCoverageRegistry(path, resolver=resolver)
    store.record_manifest(original, owner_user_id="u1")
    store.record_manifest(current, owner_user_id="u1")
    before = path.read_bytes()

    with pytest.raises(ValueError, match="stale platform coverage manifest replay"):
        store.record_manifest(original, owner_user_id="u1")

    assert path.read_bytes() == before
    reloaded = PersistentPlatformCoverageRegistry(path, resolver=resolver)
    assert tuple(reloaded.records(owner_user_id="u1")) == current


def test_platform_registry_poisoned_journal_blocks_append_without_changing_bytes(tmp_path):
    path = tmp_path / "platform_coverage_manifest.jsonl"
    store = PersistentPlatformCoverageRegistry(
        path,
        resolver=_StrictPlatformTestResolver(),
    )
    path.write_bytes(b'{"schema_version":2')
    before = path.read_bytes()

    with pytest.raises(ValueError, match="invalid platform coverage row"):
        store.record_manifest(_owner_isolated_manifest("u1"), owner_user_id="u1")

    assert path.read_bytes() == before


def test_platform_registry_json_string_line_separator_is_not_a_record_boundary(tmp_path):
    path = tmp_path / "platform_coverage_manifest.jsonl"
    resolver = _StrictPlatformTestResolver()
    records = list(_owner_isolated_manifest("u1"))
    records[0] = replace(
        records[0],
        evidence_refs=("audit:u1:M1_M2:line\u2028separator",),
    )
    manifest = tuple(records)
    store = PersistentPlatformCoverageRegistry(path, resolver=resolver)

    store.record_manifest(manifest, owner_user_id="u1")

    assert tuple(
        PersistentPlatformCoverageRegistry(path, resolver=resolver).records(
            owner_user_id="u1"
        )
    ) == manifest


def test_platform_registry_first_write_failure_leaves_journal_absent(tmp_path, monkeypatch):
    path = tmp_path / "platform_coverage_manifest.jsonl"
    store = PersistentPlatformCoverageRegistry(
        path,
        resolver=_StrictPlatformTestResolver(),
    )
    monkeypatch.setattr(platform_coverage_module.os, "write", lambda _fd, _payload: 0)

    with pytest.raises(OSError, match="write made no progress"):
        store.record_manifest(_owner_isolated_manifest("u1"), owner_user_id="u1")

    assert not path.exists()


def test_platform_registry_retries_positive_short_writes_until_full_record(tmp_path, monkeypatch):
    path = tmp_path / "platform_coverage_manifest.jsonl"
    resolver = _StrictPlatformTestResolver()
    store = PersistentPlatformCoverageRegistry(path, resolver=resolver)
    store.record_manifest(_owner_isolated_manifest("u1"), owner_user_id="u1")
    real_write = platform_coverage_module.os.write

    def short_write(fd, payload):
        return real_write(fd, payload[:7])

    monkeypatch.setattr(platform_coverage_module.os, "write", short_write)
    store.record_manifest(_owner_isolated_manifest("u2"), owner_user_id="u2")

    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    assert [row["owner_user_id"] for row in rows] == ["u1", "u2"]
    assert len(
        PersistentPlatformCoverageRegistry(path, resolver=resolver).records(
            owner_user_id="u2"
        )
    ) == len(REQUIRED_PLATFORM_ROWS)


def test_platform_registry_zero_progress_write_leaves_byte_exact_journal(tmp_path, monkeypatch):
    path = tmp_path / "platform_coverage_manifest.jsonl"
    resolver = _StrictPlatformTestResolver()
    store = PersistentPlatformCoverageRegistry(path, resolver=resolver)
    store.record_manifest(_owner_isolated_manifest("u1"), owner_user_id="u1")
    before = path.read_bytes()
    monkeypatch.setattr(platform_coverage_module.os, "write", lambda _fd, _payload: 0)

    with pytest.raises(OSError, match="write made no progress"):
        store.record_manifest(_owner_isolated_manifest("u2"), owner_user_id="u2")

    assert path.read_bytes() == before
    assert store.records(owner_user_id="u2") == []


def test_platform_registry_temp_fsync_failure_leaves_byte_exact_journal(tmp_path, monkeypatch):
    path = tmp_path / "platform_coverage_manifest.jsonl"
    resolver = _StrictPlatformTestResolver()
    store = PersistentPlatformCoverageRegistry(path, resolver=resolver)
    store.record_manifest(_owner_isolated_manifest("u1"), owner_user_id="u1")
    before = path.read_bytes()

    def fail_fsync(_fd):
        raise OSError("forced temp fsync failure")

    monkeypatch.setattr(platform_coverage_module.os, "fsync", fail_fsync)
    with pytest.raises(OSError, match="forced temp fsync failure"):
        store.record_manifest(_owner_isolated_manifest("u2"), owner_user_id="u2")

    assert path.read_bytes() == before


def test_platform_registry_parent_fsync_failure_restores_byte_exact_journal(tmp_path, monkeypatch):
    path = tmp_path / "platform_coverage_manifest.jsonl"
    resolver = _StrictPlatformTestResolver()
    store = PersistentPlatformCoverageRegistry(path, resolver=resolver)
    store.record_manifest(_owner_isolated_manifest("u1"), owner_user_id="u1")
    before = path.read_bytes()
    real_fsync = platform_coverage_module.os.fsync
    calls = 0

    def fail_first_parent_fsync(fd):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("forced parent fsync failure")
        return real_fsync(fd)

    monkeypatch.setattr(platform_coverage_module.os, "fsync", fail_first_parent_fsync)
    with pytest.raises(OSError, match="forced parent fsync failure"):
        store.record_manifest(_owner_isolated_manifest("u2"), owner_user_id="u2")

    assert calls >= 4
    assert path.read_bytes() == before
    assert store.records(owner_user_id="u2") == []


def test_platform_registry_replace_failure_leaves_byte_exact_journal(tmp_path, monkeypatch):
    path = tmp_path / "platform_coverage_manifest.jsonl"
    resolver = _StrictPlatformTestResolver()
    store = PersistentPlatformCoverageRegistry(path, resolver=resolver)
    store.record_manifest(_owner_isolated_manifest("u1"), owner_user_id="u1")
    before = path.read_bytes()

    def fail_replace(_source, _destination):
        raise OSError("forced replace failure")

    monkeypatch.setattr(platform_coverage_module.os, "replace", fail_replace)
    with pytest.raises(OSError, match="forced replace failure"):
        store.record_manifest(_owner_isolated_manifest("u2"), owner_user_id="u2")

    assert path.read_bytes() == before


def test_platform_registry_silent_replace_noop_is_detected_without_changing_bytes(
    tmp_path,
    monkeypatch,
):
    path = tmp_path / "platform_coverage_manifest.jsonl"
    resolver = _StrictPlatformTestResolver()
    store = PersistentPlatformCoverageRegistry(path, resolver=resolver)
    store.record_manifest(_owner_isolated_manifest("u1"), owner_user_id="u1")
    before = path.read_bytes()
    monkeypatch.setattr(
        platform_coverage_module.os,
        "replace",
        lambda _source, _destination: None,
    )

    with pytest.raises(OSError, match="append bytes could not be verified"):
        store.record_manifest(_owner_isolated_manifest("u2"), owner_user_id="u2")

    assert path.read_bytes() == before


def test_platform_registry_replace_ack_loss_restores_byte_exact_journal(tmp_path, monkeypatch):
    path = tmp_path / "platform_coverage_manifest.jsonl"
    resolver = _StrictPlatformTestResolver()
    store = PersistentPlatformCoverageRegistry(path, resolver=resolver)
    store.record_manifest(_owner_isolated_manifest("u1"), owner_user_id="u1")
    before = path.read_bytes()
    real_replace = platform_coverage_module.os.replace
    calls = 0

    def replace_then_lose_ack(source, destination):
        nonlocal calls
        calls += 1
        real_replace(source, destination)
        if calls == 1:
            raise OSError("forced replace acknowledgement loss")

    monkeypatch.setattr(
        platform_coverage_module.os,
        "replace",
        replace_then_lose_ack,
    )
    with pytest.raises(OSError, match="forced replace acknowledgement loss"):
        store.record_manifest(_owner_isolated_manifest("u2"), owner_user_id="u2")

    assert calls == 2
    assert path.read_bytes() == before
    assert store.records(owner_user_id="u2") == []


def test_platform_registry_failed_ack_loss_rollback_reports_uncertain_full_record(
    tmp_path,
    monkeypatch,
):
    path = tmp_path / "platform_coverage_manifest.jsonl"
    resolver = _StrictPlatformTestResolver()
    store = PersistentPlatformCoverageRegistry(path, resolver=resolver)
    store.record_manifest(_owner_isolated_manifest("u1"), owner_user_id="u1")
    manifest = _owner_isolated_manifest("u2")
    real_replace = platform_coverage_module.os.replace
    calls = 0

    def lose_ack_then_fail_restore(source, destination):
        nonlocal calls
        calls += 1
        if calls == 1:
            real_replace(source, destination)
            raise OSError("forced replace acknowledgement loss")
        raise OSError("forced rollback replace failure")

    monkeypatch.setattr(
        platform_coverage_module.os,
        "replace",
        lose_ack_then_fail_restore,
    )
    with pytest.raises(PlatformCoverageCommitUncertain, match="rollback is unverified"):
        store.record_manifest(manifest, owner_user_id="u2")

    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    assert [row["owner_user_id"] for row in rows] == ["u1", "u2"]
    committed = path.read_bytes()
    monkeypatch.setattr(platform_coverage_module.os, "replace", real_replace)
    assert store.record_manifest(manifest, owner_user_id="u2") == manifest
    assert path.read_bytes() == committed


def test_platform_registry_concurrent_identical_writers_append_single_event(tmp_path):
    path = tmp_path / "platform_coverage_manifest.jsonl"
    resolver = _StrictPlatformTestResolver()
    stores = (
        PersistentPlatformCoverageRegistry(path, resolver=resolver),
        PersistentPlatformCoverageRegistry(path, resolver=resolver),
    )
    manifest = _owner_isolated_manifest("u1")
    barrier = Barrier(2)

    def record(store):
        barrier.wait()
        return store.record_manifest(manifest, owner_user_id="u1")

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(record, stores))

    assert results == [manifest, manifest]
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    assert len(rows) == 1
    assert tuple(stores[0].records(owner_user_id="u1")) == manifest
    assert tuple(stores[1].records(owner_user_id="u1")) == manifest


def test_platform_registry_concurrent_competing_writers_preserve_both_and_current_head(tmp_path):
    path = tmp_path / "platform_coverage_manifest.jsonl"
    resolver = _StrictPlatformTestResolver()
    stores = (
        PersistentPlatformCoverageRegistry(path, resolver=resolver),
        PersistentPlatformCoverageRegistry(path, resolver=resolver),
    )
    manifests = (
        _owner_isolated_manifest("u1"),
        _mutated_owner_manifest("u1"),
    )
    barrier = Barrier(2)

    def record(item):
        store, manifest = item
        barrier.wait()
        return store.record_manifest(manifest, owner_user_id="u1")

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(record, zip(stores, manifests, strict=True)))

    assert results == list(manifests)
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    assert len(rows) == 2
    current_qro_ref = rows[-1]["records"][0]["qro_ref"]
    current = manifests[0] if manifests[0][0].qro_ref == current_qro_ref else manifests[1]
    stale = manifests[1] if current is manifests[0] else manifests[0]
    assert tuple(stores[0].records(owner_user_id="u1")) == current
    assert tuple(stores[1].records(owner_user_id="u1")) == current
    before = path.read_bytes()
    with pytest.raises(ValueError, match="stale platform coverage manifest replay"):
        stores[0].record_manifest(stale, owner_user_id="u1")
    assert path.read_bytes() == before


def test_strict_platform_manifest_rejects_reused_lineage_duplicate_specific_and_unbacked_evidence():
    resolver = _StrictPlatformTestResolver().for_owner("u1")
    records = list(_owner_isolated_manifest("u1"))
    records[1] = replace(
        records[1],
        qro_ref=records[0].qro_ref,
        research_graph_ref=records[0].research_graph_ref,
    )
    decision = validate_platform_coverage_real_manifest(tuple(records), resolver=resolver)
    assert not decision.accepted
    assert "platform_capability_duplicate_lineage" in _codes(decision)

    duplicate_specific = replace(
        _owner_isolated_manifest("u1")[3],
        specific_refs=(
            PlatformSpecificRef("model_passport_ref", "model_passport:u1:M6"),
            PlatformSpecificRef("model_passport_ref", "model_passport:u1:M6:other"),
            PlatformSpecificRef("validation_dossier_ref", "validation_dossier:u1:M6"),
        ),
    )
    duplicate_decision = validate_platform_capability_real_backing(
        duplicate_specific, resolver=resolver
    )
    assert "platform_capability_duplicate_specific_ref" in _codes(duplicate_decision)

    unbacked_evidence = replace(
        _owner_isolated_manifest("u1")[0],
        evidence_refs=("evidence:looks-real-but-unpersisted",),
    )
    evidence_decision = validate_platform_capability_real_backing(
        unbacked_evidence, resolver=resolver
    )
    assert not evidence_decision.accepted
    assert "evidence_refs" in {v.field for v in evidence_decision.violations}


def test_current_real_platform_backing_remains_unavailable_without_owner_specific_producers(tmp_path):
    backing = _real_backing(tmp_path)
    decision = validate_platform_coverage_real_manifest(
        _backed_manifest(backing.common),
        resolver=backing.resolver.for_owner("u1"),
    )
    assert not decision.accepted
    assert "platform_capability_duplicate_lineage" in _codes(decision)
    assert "platform_capability_ref_not_backed" in _codes(decision)


def test_real_platform_manifest_rejects_synthetic_placeholder_manifest_without_writing(tmp_path):
    store = PersistentPlatformCoverageRegistry(tmp_path / "platform_coverage_manifest.jsonl")

    with pytest.raises(ValueError, match="platform_capability_ref_not_backed"):
        store.record_manifest(_complete_manifest(), owner_user_id="u1")

    assert store.records(owner_user_id="u1") == []
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
    resolver = _StrictPlatformTestResolver()
    client, store = _client_with_platform_registry(
        tmp_path, monkeypatch, resolver=resolver
    )
    try:
        synthetic_response = client.post(
            "/api/research-os/platform/coverage_manifest/validate_draft",
            json=_payload(_complete_manifest()),
        )
        assert synthetic_response.status_code == 200
        assert not synthetic_response.json()["accepted_as_current_server_derived_manifest"]
        assert store.records(owner_user_id="u1") == []

        # Lexically-shaped but unbacked manifest is also rejected now (no rubber stamp).
        lexical_response = client.post(
            "/api/research-os/platform/coverage_manifest/validate_draft",
            json=_payload(_real_manifest()),
        )
        assert lexical_response.status_code == 200
        assert not lexical_response.json()["accepted_as_current_server_derived_manifest"]
        assert store.records(owner_user_id="u1") == []

        caller_authored = client.post(
            "/api/research-os/platform/coverage_manifest",
            json=_payload(_owner_isolated_manifest("u1")),
        )
        assert caller_authored.status_code == 422
        assert store.records(owner_user_id="u1") == []

        response = client.post(
            "/api/research-os/platform/coverage_manifest",
            json={},
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

        main.app.dependency_overrides[require_user_dependency] = lambda: SimpleNamespace(
            username="same-display-name",
            user_id="u2",
        )
        foreign_summary = client.get("/api/research-os/platform/coverage_summary")
        assert foreign_summary.status_code == 200
        assert foreign_summary.json()["platform_row_total"] == 0
        assert foreign_summary.json()["full_platform_coverage"] is False
    finally:
        main.app.dependency_overrides.pop(require_user_dependency, None)


def test_real_resolver_resolves_minted_records_and_rejects_unknown_ids(tmp_path):
    backing = _real_backing(tmp_path)
    resolver = backing.resolver.for_owner("u1")
    common = backing.common

    # Each minted id resolves to a real object in its real store.
    assert resolver.has_qro(common["qro_ref"]) is True
    assert resolver.has_research_graph_command(common["research_graph_ref"]) is True
    # Lifecycle v2 is owner-enveloped; only the matching owner can resolve it.
    assert resolver.has_lifecycle_record(common["lifecycle_ref"]) is True
    assert backing.resolver.for_owner("u2").has_lifecycle_record(common["lifecycle_ref"]) is False
    # Governance passports still have no stable owner envelope and stay unavailable.
    assert resolver.has_governance_record(common["governance_ref"]) is False
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


def test_real_resolver_binds_m15_projection_and_m18_code_command_to_row_lineage(tmp_path):
    backing = _real_backing(tmp_path)
    resolver = backing.resolver.for_owner("u1")
    common = backing.common
    [projection] = backing.research_graph.projection_index(owner="u1")

    m15 = _backed_record(
        PlatformRow.M15,
        common,
        specific_refs=(
            PlatformSpecificRef(
                "typed_canvas_projection_ref",
                projection.projection_ref,
            ),
        ),
    )
    assert resolver.has_platform_specific_ref(
        "typed_canvas_projection_ref",
        projection.projection_ref,
        m15,
    )
    assert not resolver.has_platform_specific_ref(
        "typed_canvas_projection_ref",
        projection.projection_ref,
        replace(m15, qro_ref="qro_other_owner_lineage"),
    )

    m18 = _backed_record(
        PlatformRow.M18,
        common,
        specific_refs=(
            PlatformSpecificRef(
                "canonical_code_command_ref",
                common["research_graph_ref"],
            ),
            PlatformSpecificRef(
                "consistency_check_ref",
                common["consistency_check_ref"],
            ),
        ),
    )
    assert resolver.has_platform_specific_ref(
        "canonical_code_command_ref",
        common["research_graph_ref"],
        m18,
    )
    assert not resolver.has_platform_specific_ref(
        "canonical_code_command_ref",
        common["research_graph_ref"],
        replace(m18, research_graph_ref="rgcmd_unrelated"),
    )


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
    # Per-field fail-closed guard. The baseline remains unavailable because
    # lifecycle/governance/evidence producers are not owner-enveloped yet.
    backing = _real_backing(tmp_path)
    resolver = backing.resolver.for_owner("u1")
    assert not validate_platform_capability_real_backing(
        _backed_record(PlatformRow.M10, backing.common), resolver=resolver
    ).accepted

    # (b) Swap exactly this field to an id that PASSES the old lexical prefix but
    #     resolves to nothing -> rejected on this field. A lexical-only regression
    #     on qro/research_graph/math turns this red.
    common = dict(backing.common)
    common[field_name] = unbacked_ref
    decision = validate_platform_capability_real_backing(
        _backed_record(PlatformRow.M10, common), resolver=resolver
    )
    assert not decision.accepted
    assert "platform_capability_ref_not_backed" in _codes(decision)
    assert field_name in {violation.field for violation in decision.violations}


@pytest.mark.parametrize(
    "row",
    (
        PlatformRow.M10,
        PlatformRow.M11,
        PlatformRow.M12,
        PlatformRow.M13,
        PlatformRow.M16,
        PlatformRow.M17,
        PlatformRow.M19,
    ),
)
def test_unimplemented_rows_reject_unrelated_real_common_objects(tmp_path, row):
    backing = _real_backing(tmp_path)
    decision = validate_platform_capability_real_backing(
        _backed_record(row, backing.common),
        resolver=backing.resolver.for_owner("u1"),
    )
    assert not decision.accepted
    fields = {violation.field for violation in decision.violations}
    assert {
        "qro_ref",
        "research_graph_ref",
        "lifecycle_ref",
        "governance_ref",
        "rag_ref",
        "math_spine_ref",
    }.issubset(fields)


def test_real_backing_rejects_goal_closure_ref_even_if_seeded_in_store(tmp_path):
    # Defends against the recursive fake-green: the removed closure materializer
    # seeded mathematical_spine_chains.jsonl with a math_spine_chain:goal_closure:*
    # record, so a pure resolution check would pass. The token ban rejects the ref
    # up front even though it really resolves in the store.
    #
    # SA-4 added a write門 to PersistentMathematicalSpineChainRegistry.record_chain
    # that now fail-closes a goal_closure seed at the public write path, so the seed
    # can no longer enter through record_chain(). We inject it straight into the
    # registry's in-memory index to model a *residual* legacy seed — a line that
    # predates the write門 and still awaits scripts/purge_goal_closure_seeds.py. The
    # platform-coverage token ban must keep rejecting the ref during that residual
    # window; that defense is exactly what this test pins and is unchanged below.
    backing = _real_backing(tmp_path)
    seeded = _mk_chain(chain_ref="math_spine_chain:goal_closure:section_0_17:v1")
    backing.spine._chains[seeded.chain_ref] = seeded
    assert backing.resolver.has_math_spine_chain(seeded.chain_ref) is False

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
