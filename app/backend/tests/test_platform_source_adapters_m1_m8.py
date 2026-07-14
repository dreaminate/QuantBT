from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from types import SimpleNamespace

import pytest

from app.lineage.ids import content_hash
from app.research_os.market_data_contract import DatasetSemanticsRecord, InstrumentSpec
from app.research_os.platform_coverage import (
    PlatformCapabilityRecord,
    PlatformSpecificRef,
)
from app.research_os.platform_source_adapters_m1_m8 import (
    PlatformSourceAdaptersM1M8Context,
    build_platform_source_adapters_m1_m8,
    unavailable_platform_source_rows_m1_m8,
)
from app.research_os.research_design_assets import source_object_hash


OWNER = "owner-platform-m1-m8"


def _binding_graph_rows(
    qro,
    *,
    current_ref: str,
    business_ref: str,
    chain_ref: str,
    entrypoint_ref: str,
):
    historical_qro = SimpleNamespace(
        **{**vars(qro), "mathematical_refs": ()}
    )
    historical = SimpleNamespace(
        command_id=business_ref,
        command_type="upsert_qro",
        actor=OWNER,
        source="api",
        actor_source="user_manual",
        payload={"qro": historical_qro},
        evidence_refs=(),
        tool_record_refs=(),
    )
    current = SimpleNamespace(
        command_id=current_ref,
        command_type="upsert_qro",
        actor=OWNER,
        source="api",
        actor_source="user_manual",
        payload={"qro": qro},
        evidence_refs=(chain_ref, business_ref),
        tool_record_refs=(entrypoint_ref,),
    )
    projection = SimpleNamespace(
        qro_id=qro.qro_id,
        command_id=current_ref,
        owner=OWNER,
        actor=OWNER,
        source="api",
        mathematical_refs=(chain_ref,),
    )
    return (historical, current), projection


def test_builder_keeps_rows_without_typed_owner_sources_unregistered():
    context = PlatformSourceAdaptersM1M8Context()

    adapters, validators = build_platform_source_adapters_m1_m8(context)
    unavailable = unavailable_platform_source_rows_m1_m8(context)

    assert adapters == {}
    assert validators == {}
    assert set(unavailable) == {"M1-M2", "M3", "M4-M5", "M6", "M7-M8"}
    assert any("UniverseDefinition" in item for item in unavailable["M1-M2"])
    assert any("Label" in item for item in unavailable["M4-M5"])
    assert any("PortfolioPolicy" in item for item in unavailable["M7-M8"])
    assert "missing dependency:lifecycle_loader" in unavailable["M6"]


def _m3_fixture():
    skill = SimpleNamespace(
        skill_id="ingestion_skill:bars:v1",
        source_ref="datasource:bars",
        schema_mapping_ref="schema_map:bars:v1",
        pit_bitemporal_rules_ref="pit:bars:v1",
        output_dataset_id="bars",
        owner=OWNER,
        version="v1",
        lifecycle_state="active",
    )
    source = SimpleNamespace(source_ref=skill.source_ref)
    update = SimpleNamespace(
        update_ref="ingestion_update:bars:v1",
        skill_ref=skill.skill_id,
        skill_version=skill.version,
        dataset_version_ref="dataset_version:bars:version-1",
        checksum="sha256-bars",
        lineage_ref="lineage:bars:v1",
        source_ref=skill.source_ref,
        known_at_ref="known_at:bars:v1",
        effective_at_ref="effective_at:bars:v1",
        row_count=10,
        recorded_by=OWNER,
    )
    pit = SimpleNamespace(
        rule_ref=skill.pit_bitemporal_rules_ref,
        skill_id=skill.skill_id,
        source_ref=skill.source_ref,
        field_mapping_ref="field_mapping:bars:v1",
        schema_probe_ref="schema_probe:bars:v1",
        recorded_by=OWNER,
    )
    dataset = DatasetSemanticsRecord(
        dataset_ref="dataset:bars:v1",
        source_ref=skill.source_ref,
        version="version-1",
        known_at_ref=update.known_at_ref,
        effective_at_ref=update.effective_at_ref,
        pit_bitemporal_rules_ref=pit.rule_ref,
        quality_status="passed",
        lineage_refs=(
            update.update_ref,
            update.lineage_ref,
            pit.rule_ref,
            pit.field_mapping_ref,
            pit.schema_probe_ref,
        ),
        freshness_status="fresh",
        checksum=update.checksum,
    )
    instrument = InstrumentSpec(
        instrument_ref="instrument:BTCUSDT",
        asset_class="crypto_spot",
        instrument_type="spot",
        currency="USD",
        exchange_calendar_ref="calendar:crypto:247",
        symbol_mapping_ref=skill.schema_mapping_ref,
    )
    version = SimpleNamespace(
        dataset_id=skill.output_dataset_id,
        version_id=dataset.version,
        sha256=dataset.checksum,
        row_count=update.row_count,
        metadata={
            "ingestion_skill_id": skill.skill_id,
            "ingestion_skill_version": skill.version,
            "source_ref": skill.source_ref,
        },
    )
    qro = SimpleNamespace(
        qro_id="qro:dataset:bars:v1",
        qro_type="Dataset",
        owner=OWNER,
        mathematical_refs=("math_spine_chain:bars:v1",),
        input_contract={
            "entry_source": "api",
            "dataset_ref": dataset.dataset_ref,
            "source_ref": dataset.source_ref,
            "version": dataset.version,
            "record_hash": content_hash(dataset.to_dict()),
        },
        output_contract={
            "status": "dataset_semantics_recorded",
            "dataset_ref": dataset.dataset_ref,
            "known_at_ref": dataset.known_at_ref,
            "effective_at_ref": dataset.effective_at_ref,
            "pit_bitemporal_rules_ref": dataset.pit_bitemporal_rules_ref,
            "quality_status": dataset.quality_status,
            "freshness_status": dataset.freshness_status,
        },
        implementation_hash="market_data_dataset:" + content_hash(dataset.to_dict()),
    )
    graph_rows, graph_projection = _binding_graph_rows(
        qro,
        current_ref="rgcmd:dataset:bars:v1:spine-binding",
        business_ref="rgcmd:dataset:bars:v1",
        chain_ref="math_spine_chain:bars:v1",
        entrypoint_ref="api:research_os.platform.spine_bindings.m3",
    )
    chain = SimpleNamespace(data_semantics_ref=dataset.dataset_ref)
    rag = SimpleNamespace(
        document_id="ragdoc_dataset_bars_v1",
        asset_ref=dataset.dataset_ref,
        permission=SimpleNamespace(
            allowed_users=(OWNER,),
            allowed_assets=(dataset.dataset_ref,),
        ),
    )

    class Graph:
        def qro(self, ref):
            if ref != qro.qro_id:
                raise KeyError(ref)
            return qro

        def commands(self):
            return list(graph_rows)

        def projection_index(self, *, owner):
            return [graph_projection] if owner == OWNER else []

    class Onboarding:
        def ingestion_skill(self, ref, *, owner_user_id):
            if ref != skill.skill_id or owner_user_id != OWNER:
                raise KeyError(ref)
            return skill

        def data_source(self, ref, *, owner_user_id):
            if ref != source.source_ref or owner_user_id != OWNER:
                raise KeyError(ref)
            return source

        def data_connector_pit_bitemporal_rule(self, ref, *, owner_user_id):
            if ref != pit.rule_ref or owner_user_id != OWNER:
                raise KeyError(ref)
            return pit

    class Lifecycle:
        def ingestion_skill_update(self, ref, *, owner_user_id):
            if ref != update.update_ref or owner_user_id != OWNER:
                raise KeyError(ref)
            return update

    class MarketData:
        def dataset(self, ref, *, owner_user_id):
            if ref != dataset.dataset_ref or owner_user_id != OWNER:
                raise KeyError(ref)
            return dataset

        def instrument(self, ref, *, owner_user_id):
            if ref != instrument.instrument_ref or owner_user_id != OWNER:
                raise KeyError(ref)
            return instrument

    class Versions:
        def resolve_version_ref(self, ref):
            if ref != update.dataset_version_ref:
                raise KeyError(ref)
            return version

    class Spine:
        def verified_chain(self, ref, *, owner):
            if ref != "math_spine_chain:bars:v1" or owner != OWNER:
                raise KeyError(ref)
            return chain

    class RAG:
        def document_for_owner(self, ref, *, owner_user_id, require_current):
            if ref != rag.document_id or owner_user_id != OWNER or require_current is not True:
                raise KeyError(ref)
            return rag

    context = PlatformSourceAdaptersM1M8Context(
        research_graph_store=Graph(),
        onboarding_registry=Onboarding(),
        market_data_registry=MarketData(),
        asset_lifecycle_registry=Lifecycle(),
        dataset_registry=Versions(),
        rag_index=RAG(),
        spine_chain_registry=Spine(),
    )
    record = PlatformCapabilityRecord(
        m_row="M3",
        qro_ref=qro.qro_id,
        research_graph_ref="rgcmd:dataset:bars:v1:spine-binding",
        lifecycle_ref=update.update_ref,
        governance_ref="goal_validation_receipt:bars:v1",
        rag_ref=rag.document_id,
        math_spine_ref="math_spine_chain:bars:v1",
        evidence_refs=("evidence:bars:v1",),
        specific_refs=(
            PlatformSpecificRef("ingestion_skill_ref", skill.skill_id),
            PlatformSpecificRef("instrument_spec_ref", instrument.instrument_ref),
        ),
    )
    return context, record, skill, instrument, chain


def test_m3_adapters_bind_one_current_owner_dataset_bundle():
    context, record, skill, instrument, chain = _m3_fixture()
    adapters, validators = build_platform_source_adapters_m1_m8(context)

    assert set(adapters) == {"ingestion_skill_ref", "instrument_spec_ref"}
    assert set(validators) == {"M3"}
    loaded_skill = adapters["ingestion_skill_ref"].load(skill.skill_id, OWNER, record)
    loaded_instrument = adapters["instrument_spec_ref"].load(
        instrument.instrument_ref, OWNER, record
    )
    values = {
        "ingestion_skill_ref": loaded_skill,
        "instrument_spec_ref": loaded_instrument,
    }
    assert adapters["ingestion_skill_ref"].validate_linkage(
        loaded_skill, OWNER, record
    ) == ()
    assert validators["M3"](record, OWNER, values) == ()

    chain.data_semantics_ref = "dataset:other"
    assert "Mathematical Spine" in " ".join(validators["M3"](record, OWNER, values))


def test_m3_adapter_rejects_cross_owner_and_same_owner_instrument_recombination():
    context, record, skill, instrument, _chain = _m3_fixture()
    adapters, validators = build_platform_source_adapters_m1_m8(context)

    try:
        adapters["ingestion_skill_ref"].load(skill.skill_id, "other-owner", record)
    except KeyError:
        pass
    else:  # pragma: no cover - explicit assertion keeps the failure readable.
        raise AssertionError("cross-owner IngestionSkill lookup unexpectedly succeeded")

    instrument = instrument.model_copy(update={"symbol_mapping_ref": "schema_map:other"})
    violations = validators["M3"](
        record,
        OWNER,
        {"ingestion_skill_ref": skill, "instrument_spec_ref": instrument},
    )
    assert "M3 instrument schema mapping mismatch" in violations


def _m6_fixture(tmp_path):
    job_id = "trn-platform-m6"
    model_id = "ridge"
    version_number = 1
    model_version_ref = f"model_version:{model_id}:v{version_number}"
    dossier_ref = f"validation_dossier:{job_id}"
    passport_ref = "model_passport_platform_m6"
    run_id = "run-platform-m6"
    binding_graph_ref = "rgcmd:model:platform:m6:spine-binding"
    artifact_path = tmp_path / "model.joblib"
    artifact_path.write_bytes(b"model-bytes")
    artifact_hash = "sha256:" + hashlib.sha256(b"model-bytes").hexdigest()
    request = {
        "asset_class": "crypto_spot",
        "feature_cols": ["f1", "f2"],
        "label_col": "label:y",
    }
    metrics = {"sharpe": 1.2}
    job = SimpleNamespace(
        job_id=job_id,
        owner_user_id=OWNER,
        status="succeeded",
        model=model_id,
        model_version=version_number,
        run_id=run_id,
        model_passport_ref=passport_ref,
        validation_dossier_ref=dossier_ref,
        qro_id="qro:model:platform:m6",
        research_graph_command_id="rgcmd:model:platform:m6",
        artifact_dir=str(tmp_path),
        request=request,
        metrics=metrics,
    )
    dossier = {
        "validation_dossier_ref": dossier_ref,
        "model_version_ref": model_version_ref,
        "training_run_ref": f"training_run:{run_id}",
        "dataset_refs": ["dataset:training:m6"],
        "market_data_use_validation_refs": [],
        "feature_refs": ["f1", "f2"],
        "label_refs": ["label:y"],
        "cv_scheme": "purged_kfold",
        "n_splits": 5,
        "metrics": metrics,
        "artifact_path": str(artifact_path),
        "artifact_hash": artifact_hash,
        "artifact_inspection_ref": "inspection:m6",
        "artifact_inspection_mode": "metadata_only_no_deserialize",
        "result_oos_metrics": {},
        "fold_count": 5,
    }
    (tmp_path / "validation_dossier.json").write_text(
        json.dumps(dossier), encoding="utf-8"
    )
    passport = SimpleNamespace(
        passport_id=passport_ref,
        owner_user_id=OWNER,
        model_version_ref=model_version_ref,
        training_plan_ref=f"training_plan:{job_id}",
        training_run_ref=f"training_run:{run_id}",
        validation_dossier_ref=dossier_ref,
        dataset_refs=("dataset:training:m6",),
        feature_refs=("f1", "f2"),
        label_refs=("label:y",),
        artifact_manifest=(
            SimpleNamespace(
                content_hash=artifact_hash,
                uri=str(artifact_path),
                producer_run_ref=f"training_run:{run_id}",
                sandbox_inspection_ref="inspection:m6",
            ),
        ),
    )
    qro = SimpleNamespace(
        qro_id=job.qro_id,
        qro_type="Model",
        owner=OWNER,
        mathematical_refs=("math_spine_chain:model:m6",),
        input_contract={
            "entry_source": "api",
            "executed_by": "training_service",
            "job_id": job_id,
            "model": model_id,
            "request_hash": content_hash(request),
        },
        output_contract={
            "status": "succeeded",
            "job_id": job_id,
            "model": model_id,
            "model_version": version_number,
            "model_version_ref": model_version_ref,
            "model_passport_ref": passport_ref,
            "validation_dossier_ref": dossier_ref,
            "run_id": run_id,
            "metrics_hash": content_hash(metrics),
        },
        implementation_hash="training_job:"
        + content_hash(
            {
                "job_id": job_id,
                "model_version_ref": model_version_ref,
                "request_hash": content_hash(request),
                "metrics_hash": content_hash(metrics),
            }
        ),
    )
    graph_rows, graph_projection = _binding_graph_rows(
        qro,
        current_ref=binding_graph_ref,
        business_ref=job.research_graph_command_id,
        chain_ref="math_spine_chain:model:m6",
        entrypoint_ref="api:research_os.platform.spine_bindings.m6",
    )
    model_version = SimpleNamespace(
        version=version_number,
        model_passport_ref=passport_ref,
        validation_dossier_ref=dossier_ref,
        source_run_id=run_id,
        model_asset_ref="model_asset:ridge:m6",
        artifact_path=str(artifact_path),
    )
    chain = SimpleNamespace(model_ref=model_version_ref)
    lifecycle = SimpleNamespace(owner_user_id=OWNER, logical_asset_ref=model_version_ref)
    rag = SimpleNamespace(
        document_id="ragdoc_model_m6",
        asset_ref=model_version_ref,
        permission=SimpleNamespace(
            allowed_users=(OWNER,),
            allowed_assets=(model_version_ref,),
        ),
    )

    class Graph:
        def qro(self, ref):
            if ref != qro.qro_id:
                raise KeyError(ref)
            return qro

        def commands(self):
            return list(graph_rows)

        def projection_index(self, *, owner):
            return [graph_projection] if owner == OWNER else []

    class Governance:
        def passport(self, ref, *, owner_user_id):
            if ref != passport_ref or owner_user_id != OWNER:
                raise KeyError(ref)
            return passport

    class Training:
        def get_job(self, ref):
            if ref != job_id:
                raise KeyError(ref)
            return job

    class Models:
        def list_versions(self, ref, *, owner_user_id):
            if ref != model_id or owner_user_id != OWNER:
                raise KeyError(ref)
            return [model_version]

    class Spine:
        def verified_chain(self, ref, *, owner):
            if ref != "math_spine_chain:model:m6" or owner != OWNER:
                raise KeyError(ref)
            return chain

    class RAG:
        def document_for_owner(self, ref, *, owner_user_id, require_current):
            if ref != rag.document_id or owner_user_id != OWNER or require_current is not True:
                raise KeyError(ref)
            return rag

    def load_lifecycle(ref, owner, _record):
        if ref != "lifecycle_transition:model:m6" or owner != OWNER:
            raise KeyError(ref)
        return lifecycle

    context = PlatformSourceAdaptersM1M8Context(
        research_graph_store=Graph(),
        rag_index=RAG(),
        spine_chain_registry=Spine(),
        model_governance_registry=Governance(),
        training_service=Training(),
        model_registry=Models(),
        lifecycle_loader=load_lifecycle,
    )
    record = PlatformCapabilityRecord(
        m_row="M6",
        qro_ref=qro.qro_id,
        research_graph_ref=binding_graph_ref,
        lifecycle_ref="lifecycle_transition:model:m6",
        governance_ref="goal_validation_receipt:model:m6",
        rag_ref=rag.document_id,
        math_spine_ref="math_spine_chain:model:m6",
        evidence_refs=("evidence:model:m6",),
        specific_refs=(
            PlatformSpecificRef("model_passport_ref", passport_ref),
            PlatformSpecificRef("validation_dossier_ref", dossier_ref),
        ),
    )
    return context, record, passport, job, chain, lifecycle


def test_m6_adapters_bind_training_qro_passport_dossier_model_and_lifecycle(tmp_path):
    context, record, passport, _job, _chain, _lifecycle = _m6_fixture(tmp_path)
    adapters, validators = build_platform_source_adapters_m1_m8(context)

    assert set(adapters) == {"model_passport_ref", "validation_dossier_ref"}
    assert set(validators) == {"M6"}
    loaded_passport = adapters["model_passport_ref"].load(
        passport.passport_id, OWNER, record
    )
    dossier = adapters["validation_dossier_ref"].load(
        passport.validation_dossier_ref, OWNER, record
    )
    values = {
        "model_passport_ref": loaded_passport,
        "validation_dossier_ref": dossier,
    }
    assert adapters["validation_dossier_ref"].validate_linkage(
        dossier, OWNER, record
    ) == ()
    assert validators["M6"](record, OWNER, values) == ()


def test_m6_rejects_dossier_drift_and_same_owner_lifecycle_recombination(tmp_path):
    context, record, passport, _job, _chain, lifecycle = _m6_fixture(tmp_path)
    adapters, validators = build_platform_source_adapters_m1_m8(context)
    loaded_passport = adapters["model_passport_ref"].load(
        passport.passport_id, OWNER, record
    )
    dossier = adapters["validation_dossier_ref"].load(
        passport.validation_dossier_ref, OWNER, record
    )
    dossier.dossier["feature_refs"] = ["other_feature"]
    lifecycle.logical_asset_ref = "model_version:other:v1"

    violations = validators["M6"](
        record,
        OWNER,
        {
            "model_passport_ref": loaded_passport,
            "validation_dossier_ref": dossier,
        },
    )
    assert "M6 ValidationDossier features mismatch" in violations
    assert "M6 lifecycle record does not bind the model lineage" in violations


@dataclass
class _StrategyGoal:
    goal_id: str
    title: str


@dataclass
class _HypothesisCard:
    card_id: str
    strategy_goal_ref: str
    statement: str


@dataclass
class _Factor:
    factor_id: str
    version: int
    formula: str


@dataclass
class _SignalContract:
    signal_id: str
    name: str
    horizon: int


def _m1_fixture():
    goal = _StrategyGoal("goal-m1", "Owner goal")
    goal_ref = f"strategy_goal:{goal.goal_id}"
    card = _HypothesisCard("hyp-m1", goal_ref, "Momentum persists")
    card_ref = f"hypothesis_card:{card.card_id}"
    universe_ref = "universe:owner-m1"
    regime_ref = "regime:owner-m1"
    qro_ref = "qro:m1:owner"
    graph_ref = "rgcmd:m1:owner"
    binding_graph_ref = "rgcmd:m1:owner:spine-binding"
    linkage = SimpleNamespace(
        qro_ref=qro_ref,
        research_graph_ref=graph_ref,
        lifecycle_ref=card_ref,
    )
    universe = SimpleNamespace(
        universe_definition_ref=universe_ref,
        owner_user_id=OWNER,
    )
    regime = SimpleNamespace(
        regime_scenario_ref=regime_ref,
        universe_definition_ref=universe_ref,
        owner_user_id=OWNER,
    )
    envelope = SimpleNamespace(
        hypothesis_card_ref=card_ref,
        owner_user_id=OWNER,
        card_id=card.card_id,
        source_content_hash=source_object_hash(card),
        strategy_goal_ref=goal_ref,
        universe_definition_ref=universe_ref,
        regime_scenario_ref=regime_ref,
        linkage=linkage,
    )
    qro = SimpleNamespace(
        qro_id=qro_ref,
        qro_type="QuantIntent",
        owner=OWNER,
        mathematical_refs=("spine:m1",),
        output_contract={
            "strategy_goal_ref": goal_ref,
            "strategy_goal_hash": source_object_hash(goal),
            "hypothesis_card_ref": card_ref,
            "universe_definition_ref": universe_ref,
            "regime_scenario_ref": regime_ref,
        },
    )
    graph_rows, graph_projection = _binding_graph_rows(
        qro,
        current_ref=binding_graph_ref,
        business_ref=graph_ref,
        chain_ref="spine:m1",
        entrypoint_ref="api:research_os.platform.spine_bindings.m1_m2",
    )
    lifecycle = SimpleNamespace(asset_type="HypothesisCard", asset_ref=card_ref)
    chain = SimpleNamespace(
        validation_refs=(goal_ref, card_ref),
        evidence_refs=(universe_ref, regime_ref),
    )
    rag = SimpleNamespace(
        document_id="rag:m1",
        asset_ref=card_ref,
        permission=SimpleNamespace(
            allowed_users=(OWNER,),
            allowed_assets=(card_ref,),
        ),
    )

    class Design:
        def hypothesis_envelope(self, ref, *, owner_user_id):
            if ref != card_ref or owner_user_id != OWNER:
                raise KeyError(ref)
            return envelope

        def universe_definition(self, ref, *, owner_user_id):
            if ref != universe_ref or owner_user_id != OWNER:
                raise KeyError(ref)
            return universe

        def regime_scenario(self, ref, *, owner_user_id):
            if ref != regime_ref or owner_user_id != OWNER:
                raise KeyError(ref)
            return regime

    class Goals:
        def get(self, goal_id):
            if goal_id != goal.goal_id:
                raise KeyError(goal_id)
            return goal

    class Cards:
        def get(self, card_id):
            if card_id != card.card_id:
                raise KeyError(card_id)
            return card

    class Graph:
        def qro(self, ref):
            if ref != qro_ref:
                raise KeyError(ref)
            return qro

        def commands(self):
            return list(graph_rows)

        def projection_index(self, *, owner):
            return [graph_projection] if owner == OWNER else []

    class Lifecycle:
        def governed_asset(self, ref, *, owner_user_id):
            if ref != card_ref or owner_user_id != OWNER:
                raise KeyError(ref)
            return lifecycle

    class Spine:
        def verified_chain(self, ref, *, owner):
            if ref != "spine:m1" or owner != OWNER:
                raise KeyError(ref)
            return chain

    class RAG:
        def document_for_owner(self, ref, *, owner_user_id, require_current):
            if (
                ref != rag.document_id
                or owner_user_id != OWNER
                or require_current is not True
            ):
                raise KeyError(ref)
            return rag

    context = PlatformSourceAdaptersM1M8Context(
        research_design_registry=Design(),
        strategy_goal_store=Goals(),
        hypothesis_store=Cards(),
        research_graph_store=Graph(),
        asset_lifecycle_registry=Lifecycle(),
        spine_chain_registry=Spine(),
        rag_index=RAG(),
    )
    record = PlatformCapabilityRecord(
        m_row="M1-M2",
        qro_ref=qro_ref,
        research_graph_ref=binding_graph_ref,
        lifecycle_ref=card_ref,
        governance_ref="review:m1",
        rag_ref=rag.document_id,
        math_spine_ref="spine:m1",
        evidence_refs=("evidence:m1",),
        specific_refs=(
            PlatformSpecificRef("strategy_goal_ref", goal_ref),
            PlatformSpecificRef("hypothesis_card_ref", card_ref),
            PlatformSpecificRef("universe_definition_ref", universe_ref),
            PlatformSpecificRef("regime_scenario_ref", regime_ref),
        ),
    )
    return context, record, goal, card, regime


def test_m1_m2_binds_exact_owner_design_bundle_and_rejects_drift_recombination():
    context, record, goal, card, regime = _m1_fixture()
    adapters, validators = build_platform_source_adapters_m1_m8(context)
    values = {
        key: adapters[key].load(ref.ref, OWNER, record)
        for key, ref in ((item.key, item) for item in record.specific_refs)
    }

    assert set(adapters) == {
        "strategy_goal_ref",
        "hypothesis_card_ref",
        "universe_definition_ref",
        "regime_scenario_ref",
    }
    assert validators["M1-M2"](record, OWNER, values) == ()
    with pytest.raises(KeyError):
        adapters["universe_definition_ref"].load(
            values["universe_definition_ref"].universe_definition_ref,
            "other-owner",
            record,
        )

    card.statement = "source changed after envelope"
    with pytest.raises(LookupError, match="content drifted"):
        adapters["hypothesis_card_ref"].load(
            values["hypothesis_card_ref"].hypothesis_card_ref,
            OWNER,
            record,
        )
    card.statement = "Momentum persists"
    regime.universe_definition_ref = "universe:other-same-owner"
    violations = validators["M1-M2"](record, OWNER, values)
    assert "M1-M2 regime universe mismatch" in violations
    regime.universe_definition_ref = values[
        "universe_definition_ref"
    ].universe_definition_ref
    values["hypothesis_card_ref"].envelope.linkage.research_graph_ref = (
        "rgcmd:m1:other-historical"
    )
    assert "M1-M2 graph mismatch" in validators["M1-M2"](
        record,
        OWNER,
        values,
    )
    values["hypothesis_card_ref"].envelope.linkage.research_graph_ref = (
        "rgcmd:m1:owner"
    )
    context.research_graph_store.commands()[1].tool_record_refs = (
        "api:research_os.platform.spine_bindings.other",
    )
    assert any(
        "M1-M2 current platform Spine binding is not observed" in item
        for item in validators["M1-M2"](record, OWNER, values)
    )


def _m4_fixture():
    factor = _Factor("mom", 1, "close / delay(close, 5) - 1")
    factor_ref = "factor:mom:v1"
    label_ref = "label:forward-5d"
    qro_ref = "qro:m4:owner"
    graph_ref = "rgcmd:m4:owner"
    binding_graph_ref = "rgcmd:m4:owner:spine-binding"
    linkage = SimpleNamespace(
        qro_ref=qro_ref,
        research_graph_ref=graph_ref,
        lifecycle_ref=factor_ref,
    )
    envelope = SimpleNamespace(
        factor_ref=factor_ref,
        factor_id=factor.factor_id,
        version=factor.version,
        owner_user_id=OWNER,
        source_content_hash=source_object_hash(factor),
        label_ref=label_ref,
        linkage=linkage,
    )
    label = SimpleNamespace(label_ref=label_ref, owner_user_id=OWNER)
    qro = SimpleNamespace(
        qro_id=qro_ref,
        qro_type="Factor",
        owner=OWNER,
        mathematical_refs=("spine:m4",),
        output_contract={"factor_ref": factor_ref, "label_ref": label_ref},
    )
    graph_rows, graph_projection = _binding_graph_rows(
        qro,
        current_ref=binding_graph_ref,
        business_ref=graph_ref,
        chain_ref="spine:m4",
        entrypoint_ref="api:research_os.platform.spine_bindings.m4_m5",
    )
    lifecycle = SimpleNamespace(
        asset_type="Factor",
        asset_ref=factor_ref,
        evidence_refs=(factor_ref,),
    )
    chain = SimpleNamespace(
        factor_ref=factor_ref,
        validation_refs=(label_ref,),
        evidence_refs=(),
    )
    rag = SimpleNamespace(
        document_id="rag:m4",
        asset_ref=factor_ref,
        metadata={"formula_hash": content_hash({"formula": factor.formula})},
        permission=SimpleNamespace(
            allowed_users=(OWNER,),
            allowed_assets=(factor_ref,),
        ),
    )

    class Design:
        def factor_envelope(self, ref, *, owner_user_id):
            if ref != factor_ref or owner_user_id != OWNER:
                raise KeyError(ref)
            return envelope

        def label_definition(self, ref, *, owner_user_id):
            if ref != label_ref or owner_user_id != OWNER:
                raise KeyError(ref)
            return label

    class Factors:
        def get(self, factor_id, version):
            if (factor_id, version) != (factor.factor_id, factor.version):
                raise KeyError((factor_id, version))
            return factor

    class Graph:
        def qro(self, ref):
            if ref != qro_ref:
                raise KeyError(ref)
            return qro

        def commands(self):
            return list(graph_rows)

        def projection_index(self, *, owner):
            return [graph_projection] if owner == OWNER else []

    class Lifecycle:
        def governed_asset(self, ref, *, owner_user_id):
            if ref != factor_ref or owner_user_id != OWNER:
                raise KeyError(ref)
            return lifecycle

    class Spine:
        def verified_chain(self, ref, *, owner):
            if ref != "spine:m4" or owner != OWNER:
                raise KeyError(ref)
            return chain

    class RAG:
        def document_for_owner(self, ref, *, owner_user_id, require_current):
            if ref != rag.document_id or owner_user_id != OWNER or not require_current:
                raise KeyError(ref)
            return rag

    context = PlatformSourceAdaptersM1M8Context(
        research_design_registry=Design(),
        factor_registry=Factors(),
        research_graph_store=Graph(),
        asset_lifecycle_registry=Lifecycle(),
        spine_chain_registry=Spine(),
        rag_index=RAG(),
    )
    record = PlatformCapabilityRecord(
        m_row="M4-M5",
        qro_ref=qro_ref,
        research_graph_ref=binding_graph_ref,
        lifecycle_ref=factor_ref,
        governance_ref="review:m4",
        rag_ref=rag.document_id,
        math_spine_ref="spine:m4",
        evidence_refs=("evidence:m4",),
        specific_refs=(
            PlatformSpecificRef("factor_ref", factor_ref),
            PlatformSpecificRef("label_ref", label_ref),
        ),
    )
    return context, record, factor, label


def test_m4_m5_binds_label_factor_and_rejects_source_drift_recombination():
    context, record, factor, label = _m4_fixture()
    adapters, validators = build_platform_source_adapters_m1_m8(context)
    loaded_factor = adapters["factor_ref"].load("factor:mom:v1", OWNER, record)
    loaded_label = adapters["label_ref"].load(label.label_ref, OWNER, record)
    values = {"factor_ref": loaded_factor, "label_ref": loaded_label}

    assert validators["M4-M5"](record, OWNER, values) == ()
    with pytest.raises(KeyError):
        adapters["label_ref"].load(label.label_ref, "other-owner", record)
    factor.formula = "close / delay(close, 20) - 1"
    with pytest.raises(LookupError, match="content drifted"):
        adapters["factor_ref"].load("factor:mom:v1", OWNER, record)
    factor.formula = "close / delay(close, 5) - 1"
    recombined_label = SimpleNamespace(
        label_ref="label:other-same-owner", owner_user_id=OWNER
    )
    assert "M4-M5 Factor/Label binding mismatch" in validators["M4-M5"](
        record,
        OWNER,
        {"factor_ref": loaded_factor, "label_ref": recombined_label},
    )


def _m7_fixture():
    contract = _SignalContract("abc", "Owner signal", 5)
    raw_signal_ref = "sig::abc"
    signal_ref = f"signal_contract:{raw_signal_ref}"
    validation_ref = "signal_validation:abc:oos"
    strategy_ref = "strategy_book:owner-multi-leg"
    policy_ref = "portfolio_policy:owner"
    qro_ref = "qro:m7:owner"
    graph_ref = "rgcmd:m7:owner"
    binding_graph_ref = "rgcmd:m7:owner:spine-binding"
    strategy_payload = {
        "strategy_book_ref": strategy_ref,
        "factor_refs": ["factor:mom:v1"],
        "signal_refs": [raw_signal_ref],
        "legs": [
            {
                "intent_ref": "intent:long",
                "side": "long",
                "instrument_ref": "instrument:BTCUSDT",
            },
            {
                "intent_ref": "intent:hedge",
                "side": "short",
                "instrument_ref": "instrument:ETHUSDT",
            },
        ],
        "default_factor_refs": [],
        "mathematical_refs": ["math:spread"],
        "theory_binding_refs": ["theory:relative_value"],
        "run_config_binding_refs": ["runconfig:m7"],
        "signal_validation_refs": [validation_ref],
    }
    linkage = SimpleNamespace(
        qro_ref=qro_ref,
        research_graph_ref=graph_ref,
        lifecycle_ref=policy_ref,
    )
    signal_envelope = SimpleNamespace(
        signal_contract_ref=signal_ref,
        owner_user_id=OWNER,
        source_content_hash=source_object_hash(contract),
        linkage=SimpleNamespace(qro_ref="qro:signal", research_graph_ref="rg:signal", lifecycle_ref=signal_ref),
    )
    strategy_record = SimpleNamespace(
        strategy_book_ref=strategy_ref,
        owner_user_id=OWNER,
        strategy_book=strategy_payload,
        source_content_hash=content_hash(strategy_payload),
        linkage=SimpleNamespace(qro_ref="qro:strategy", research_graph_ref="rg:strategy", lifecycle_ref=strategy_ref),
    )
    validation = SimpleNamespace(
        validation_id=validation_ref,
        owner_user_id=OWNER,
        signal_ref=raw_signal_ref,
        verdict="accepted",
    )
    policy = SimpleNamespace(
        portfolio_policy_ref=policy_ref,
        owner_user_id=OWNER,
        signal_contract_ref=signal_ref,
        signal_validation_ref=validation_ref,
        strategy_book_ref=strategy_ref,
        signal_contract_source_hash=signal_envelope.source_content_hash,
        strategy_book_source_hash=strategy_record.source_content_hash,
        linkage=linkage,
    )
    qro = SimpleNamespace(
        qro_id=qro_ref,
        qro_type="PortfolioPolicy",
        owner=OWNER,
        mathematical_refs=("spine:m7",),
        output_contract={
            "signal_contract_ref": signal_ref,
            "signal_validation_ref": validation_ref,
            "strategy_book_ref": strategy_ref,
            "portfolio_policy_ref": policy_ref,
        },
    )
    graph_rows, graph_projection = _binding_graph_rows(
        qro,
        current_ref=binding_graph_ref,
        business_ref=graph_ref,
        chain_ref="spine:m7",
        entrypoint_ref="api:research_os.platform.spine_bindings.m7_m8",
    )
    lifecycle = SimpleNamespace(asset_type="PortfolioPolicy", asset_ref=policy_ref)
    chain = SimpleNamespace(
        signal_contract_ref=signal_ref,
        strategy_book_ref=strategy_ref,
        portfolio_policy_ref=policy_ref,
    )
    rag = SimpleNamespace(
        document_id="rag:m7",
        asset_ref=policy_ref,
        permission=SimpleNamespace(
            allowed_users=(OWNER,),
            allowed_assets=(policy_ref,),
        ),
    )

    class Design:
        def signal_contract_envelope(self, ref, *, owner_user_id):
            if ref != signal_ref or owner_user_id != OWNER:
                raise KeyError(ref)
            return signal_envelope

        def strategy_book(self, ref, *, owner_user_id):
            if ref != strategy_ref or owner_user_id != OWNER:
                raise KeyError(ref)
            return strategy_record

        def portfolio_policy(self, ref, *, owner_user_id):
            if ref != policy_ref or owner_user_id != OWNER:
                raise KeyError(ref)
            return policy

    class Contracts:
        def get(self, ref):
            if ref != raw_signal_ref:
                raise KeyError(ref)
            return contract

    class Validations:
        def validation(self, ref, *, owner_user_id):
            if ref != validation_ref or owner_user_id != OWNER:
                raise KeyError(ref)
            return validation

    class Graph:
        def qro(self, ref):
            if ref != qro_ref:
                raise KeyError(ref)
            return qro

        def commands(self):
            return list(graph_rows)

        def projection_index(self, *, owner):
            return [graph_projection] if owner == OWNER else []

    class Lifecycle:
        def governed_asset(self, ref, *, owner_user_id):
            if ref != policy_ref or owner_user_id != OWNER:
                raise KeyError(ref)
            return lifecycle

    class Spine:
        def verified_chain(self, ref, *, owner):
            if ref != "spine:m7" or owner != OWNER:
                raise KeyError(ref)
            return chain

    class RAG:
        def document_for_owner(self, ref, *, owner_user_id, require_current):
            if ref != rag.document_id or owner_user_id != OWNER or not require_current:
                raise KeyError(ref)
            return rag

    context = PlatformSourceAdaptersM1M8Context(
        research_design_registry=Design(),
        signal_contract_registry=Contracts(),
        signal_validation_registry=Validations(),
        research_graph_store=Graph(),
        asset_lifecycle_registry=Lifecycle(),
        spine_chain_registry=Spine(),
        rag_index=RAG(),
    )
    record = PlatformCapabilityRecord(
        m_row="M7-M8",
        qro_ref=qro_ref,
        research_graph_ref=binding_graph_ref,
        lifecycle_ref=policy_ref,
        governance_ref="review:m7",
        rag_ref=rag.document_id,
        math_spine_ref="spine:m7",
        evidence_refs=("evidence:m7",),
        specific_refs=(
            PlatformSpecificRef("signal_contract_ref", signal_ref),
            PlatformSpecificRef("signal_validation_ref", validation_ref),
            PlatformSpecificRef("strategy_book_ref", strategy_ref),
            PlatformSpecificRef("portfolio_policy_ref", policy_ref),
        ),
    )
    return context, record, contract, policy


def test_m7_m8_binds_real_strategy_book_policy_and_rejects_drift_recombination():
    context, record, contract, policy = _m7_fixture()
    adapters, validators = build_platform_source_adapters_m1_m8(context)
    values = {
        item.key: adapters[item.key].load(item.ref, OWNER, record)
        for item in record.specific_refs
    }

    assert adapters["strategy_book_ref"].source_kind == "research_design_strategy_book"
    assert validators["M7-M8"](record, OWNER, values) == ()
    with pytest.raises(KeyError):
        adapters["strategy_book_ref"].load(
            values["strategy_book_ref"].strategy_book_ref,
            "other-owner",
            record,
        )
    contract.name = "source changed after envelope"
    with pytest.raises(LookupError, match="content drifted"):
        adapters["signal_contract_ref"].load(
            values["signal_contract_ref"].signal_contract_ref,
            OWNER,
            record,
        )
    contract.name = "Owner signal"
    policy.strategy_book_source_hash = "different-owner-source-hash"
    assert "M7-M8 policy strategy source hash mismatch" in validators["M7-M8"](
        record,
        OWNER,
        values,
    )
    policy.strategy_book_source_hash = values[
        "strategy_book_ref"
    ].record.source_content_hash
    policy.linkage.research_graph_ref = "rgcmd:m7:other-historical"
    assert "M7-M8 graph mismatch" in validators["M7-M8"](
        record,
        OWNER,
        values,
    )
