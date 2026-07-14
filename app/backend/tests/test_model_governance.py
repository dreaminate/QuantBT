from __future__ import annotations

import hashlib
import json
import pickle
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient

from app import main as app_main
from app.approval import ApprovalGateService, ApprovalGateStore, EvidenceSnapshot, GateStateError
from app.auth import require_user_dependency
from app.experiments.store import ModelRegistry
from app.lineage.ledger import Ledger
from app.research_os import (
    ModelArtifactFormat,
    ModelArtifactInspectionRecord,
    ModelArtifactManifestEntry,
    ModelArtifactSource,
    ModelGovernancePassport,
    ModelMonitoringProfile,
    ModelRecertificationRecord,
    ModelRiskTier,
    PersistentCompilerIRStore,
    PersistentEntrypointEvidenceRegistry,
    PersistentGoalEntrypointCoverageRegistry,
    PersistentGoalValidationReceiptRegistry,
    PersistentModelGovernanceRegistry,
    RecertificationTrigger,
    ResearchGraphStore,
    SafeLoadingPolicy,
    model_passport_from_dict,
    validate_model_promotion,
)
from app.research_os.goal_proof_ledger import GoalProofLedger
from app.research_os.ref_resolution import build_real_ref_resolver
from app.training import TrainingRequest, TrainingService, schema_drift


class _ConstantPredictor:
    def predict(self, frame):
        return [float(row["f1"] + row["f2"]) for _, row in frame.iterrows()]


def _sha256_file(path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return "sha256:" + h.hexdigest()


def _artifact(**overrides) -> ModelArtifactManifestEntry:
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


def _passport(**overrides) -> ModelGovernancePassport:
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
        "artifact_manifest": (_artifact(),),
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


def _codes(decision) -> set[str]:
    return {violation.code for violation in decision.violations}


def _promotion_evidence(**overrides) -> dict:
    data = EvidenceSnapshot(
        config_hash="cfg_v1_model_governance",
        dataset_version="dataset_version:btc_daily:v1",
        n_eff=5,
        n_trials_raw=5,
        dsr=0.92,
        pbo=0.10,
        bootstrap_ci=(0.4, 1.8),
        bootstrap_estimate=1.0,
        champion_challenger={"verdict": "challenger_wins", "delta_sharpe": 0.3},
        returns_sha256="sha256:returns",
    ).to_dict()
    data.update(overrides)
    return data


def _approval_service(tmp_path):
    return ApprovalGateService(
        ApprovalGateStore(tmp_path / "approval_gates"),
        ledger=Ledger(tmp_path / "ledger"),
    )


def _payload(passport: ModelGovernancePassport) -> dict:
    data = passport.__dict__.copy()
    data["artifact_manifest"] = [artifact.__dict__.copy() for artifact in passport.artifact_manifest]
    data["safe_loading_policy"] = passport.safe_loading_policy.__dict__.copy()
    return data


def _inspection(passport: ModelGovernancePassport, **overrides) -> ModelArtifactInspectionRecord:
    artifact = passport.artifact_manifest[0]
    data = {
        "model_version_ref": passport.model_version_ref,
        "model_passport_ref": passport.passport_id,
        "artifact_ref": artifact.artifact_ref,
        "inspection_ref": artifact.sandbox_inspection_ref,
        "artifact_hash": artifact.content_hash,
        "inspection_status": "accepted",
        "inspection_mode": "metadata_only",
        "inspector_ref": "test-inspector:v1",
        "checks": ("sha256_match",),
        "recorded_by": "test",
    }
    data.update(overrides)
    return ModelArtifactInspectionRecord(**data)


@pytest.fixture(autouse=True)
def _clear_dependency_overrides():
    yield
    app_main.app.dependency_overrides.pop(require_user_dependency, None)


def _patch_goal_proof_stores(tmp_path, monkeypatch, *, graph=None):  # noqa: ANN001
    graph = graph if graph is not None else ResearchGraphStore()
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
            lifecycle_registry=None,
            governance_registry=None,
            rag_index=None,
            spine_chain_registry=None,
            compiler_store=compiler,
            goal_validation_receipt_registry=validations,
            platform_source_evidence_registry=evidence,
        )
    )
    monkeypatch.setattr(app_main, "RESEARCH_GRAPH_STORE", graph)
    monkeypatch.setattr(app_main, "COMPILER_IR_STORE", compiler)
    monkeypatch.setattr(app_main, "GOAL_VALIDATION_RECEIPT_REGISTRY", validations)
    monkeypatch.setattr(app_main, "ENTRYPOINT_EVIDENCE_REGISTRY", evidence)
    monkeypatch.setattr(app_main, "GOAL_ENTRYPOINT_COVERAGE_REGISTRY", coverage)
    return graph


def _assert_ir_receipt_evidence(qro, ir, *expected_refs: str) -> None:  # noqa: ANN001
    assert len(ir.validation_refs) == 1
    assert ir.validation_refs[0].startswith("goal_validation_receipt:")
    receipt = app_main.GOAL_VALIDATION_RECEIPT_REGISTRY.receipt(
        ir.validation_refs[0],
        owner_user_id=qro.owner,
    )
    assert receipt.subject_qro_refs == (qro.qro_id,)
    assert receipt.graph_command_refs == ir.graph_command_refs
    assert receipt.outcome == "passed"
    for ref in expected_refs:
        assert ref in receipt.evidence_refs


def _client_with_model_governance_registry(tmp_path, monkeypatch):
    registry = PersistentModelGovernanceRegistry(tmp_path / "model_governance.jsonl")
    monkeypatch.setattr(app_main, "MODEL_GOVERNANCE_REGISTRY", registry)
    _patch_goal_proof_stores(tmp_path, monkeypatch)
    app_main.app.dependency_overrides[require_user_dependency] = lambda: SimpleNamespace(
        username="u1",
        user_id="u1",
    )
    return TestClient(app_main.app), registry


def _client_with_model_registry(tmp_path, monkeypatch):
    registry = PersistentModelGovernanceRegistry(tmp_path / "model_governance.jsonl")
    model_registry = ModelRegistry(
        tmp_path / "experiments",
        gate_service=_approval_service(tmp_path),
        model_governance_registry=registry,
    )
    monkeypatch.setattr(app_main, "MODEL_GOVERNANCE_REGISTRY", registry)
    _patch_goal_proof_stores(tmp_path, monkeypatch)
    monkeypatch.setattr(app_main, "MODEL_REGISTRY", model_registry)
    app_main.app.dependency_overrides[require_user_dependency] = lambda: SimpleNamespace(
        username="u1",
        user_id="u1",
    )
    return TestClient(app_main.app), registry, model_registry


def _compiler_record_counts() -> tuple[int, int, int, int]:
    return (
        len(app_main.RESEARCH_GRAPH_STORE.commands()),
        len(app_main.COMPILER_IR_STORE.irs()),
        len(app_main.COMPILER_IR_STORE.passes()),
        len(app_main.GOAL_ENTRYPOINT_COVERAGE_REGISTRY.records()),
    )


def _assert_model_governance_compiler_coverage(
    body: dict,
    *,
    qro_type: str,
    entrypoint_ref: str,
    permission_ref: str,
    forbidden_fragments: tuple[str, ...] = (),
):
    assert body["qro_id"]
    assert body["research_graph_command_id"]
    assert body["compiler_ir_ref"]
    assert body["compiler_pass_ref"]
    assert body["entrypoint_coverage_ref"]
    qro = app_main.RESEARCH_GRAPH_STORE.qro(body["qro_id"])
    ir = app_main.COMPILER_IR_STORE.ir(body["compiler_ir_ref"])
    compiler_pass = app_main.COMPILER_IR_STORE.compiler_pass(body["compiler_pass_ref"])
    coverage = app_main.GOAL_ENTRYPOINT_COVERAGE_REGISTRY.coverage(body["entrypoint_coverage_ref"])
    assert getattr(qro.qro_type, "value", qro.qro_type) == qro_type
    assert ir.source_qro_refs == (body["qro_id"],)
    assert ir.graph_command_refs == (body["research_graph_command_id"],)
    assert ir.permission_ref == permission_ref
    assert compiler_pass.input_qro_refs == (body["qro_id"],)
    assert compiler_pass.entry_source == "api"
    assert compiler_pass.actor_source == "user_manual"
    assert compiler_pass.permission_ref == permission_ref
    assert coverage.entry_source == "api"
    assert coverage.entrypoint_ref == entrypoint_ref
    assert coverage.qro_refs == (body["qro_id"],)
    assert coverage.research_graph_command_refs == (body["research_graph_command_id"],)
    assert coverage.compiler_ir_refs == (body["compiler_ir_ref"],)
    assert coverage.compiler_pass_refs == (body["compiler_pass_ref"],)
    assert compiler_pass.direct_graph_mutation is False
    assert compiler_pass.bypassed_permission is False
    assert compiler_pass.raw_llm_output_embedded_as_ir is False
    assert coverage.silent_mock_fallback_used is False
    assert coverage.raw_payload_persisted is False
    compiled_text = f"{qro.__dict__} {ir.__dict__} {compiler_pass.__dict__} {coverage.__dict__}"
    for fragment in forbidden_fragments:
        assert fragment not in compiled_text
    return qro, ir, compiler_pass, coverage


def _write_pickled_predictor(tmp_path):
    artifact_dir = tmp_path / "artifact"
    artifact_dir.mkdir()
    artifact_path = artifact_dir / "model.pkl"
    with artifact_path.open("wb") as fh:
        pickle.dump(_ConstantPredictor(), fh)
    artifact_hash = _sha256_file(artifact_path)
    inspection_ref = "inspect:model:v1"
    dossier = {
        "validation_dossier_ref": "validation_dossier:momentum:v1",
        "model_version_ref": "model_version:momentum:v1",
        "artifact_path": str(artifact_path),
        "artifact_hash": artifact_hash,
        "artifact_inspection_ref": inspection_ref,
    }
    inspection = {
        "accepted": True,
        "artifact_path": str(artifact_path.resolve()),
        "artifact_hash": artifact_hash,
        "artifact_format": "pickle",
        "inspection_ref": inspection_ref,
        "inspection_mode": "metadata_only_no_deserialize",
        "inspector_ref": "test-inspector:v1",
        "process_isolation": "subprocess",
        "deserialize_executed": False,
        "checks": ["regular_file", "sha256_match", "serialized_deserialize_skipped"],
        "limitations": ["test fixture"],
    }
    (artifact_dir / "validation_dossier.json").write_text(json.dumps(dossier), encoding="utf-8")
    (artifact_dir / "artifact_inspection.json").write_text(json.dumps(inspection), encoding="utf-8")
    return artifact_path, artifact_hash, inspection_ref


def test_model_promotion_accepts_complete_passport():
    decision = validate_model_promotion(_passport())
    assert decision.accepted
    assert decision.violations == ()


def test_model_promotion_rejects_missing_validation_dossier():
    decision = validate_model_promotion(_passport(validation_dossier_ref=None))
    assert not decision.accepted
    assert "missing_validation_dossier_ref" in _codes(decision)


def test_external_pickle_direct_load_is_rejected():
    artifact = _artifact(
        uri="s3://vendor/model.pkl",
        artifact_format=ModelArtifactFormat.PICKLE,
        source=ModelArtifactSource.EXTERNAL,
        direct_load=True,
    )
    decision = validate_model_promotion(_passport(artifact_manifest=(artifact,)))
    assert not decision.accepted
    assert _codes(decision) >= {
        "external_serialized_artifact_blocked",
        "external_pickle_direct_load",
        "unsafe_serialized_direct_load",
    }


def test_high_risk_model_requires_challenger_result():
    decision = validate_model_promotion(
        _passport(model_risk_tier=ModelRiskTier.HIGH, challenger_result=None)
    )
    assert not decision.accepted
    assert "missing_challenger_result" in _codes(decision)


def test_material_model_change_requires_recertification_record():
    decision = validate_model_promotion(
        _passport(recertification_records=()),
        change_events=(RecertificationTrigger.MATERIAL_MODEL_CHANGE,),
    )
    assert not decision.accepted
    assert "material_model_change_without_recertification" in _codes(decision)


def test_torch_artifact_requires_weights_only_policy():
    artifact = _artifact(uri="registry://models/momentum/v1/model.pt", artifact_format=ModelArtifactFormat.TORCH)
    passport = _passport(
        artifact_manifest=(artifact,),
        safe_loading_policy=SafeLoadingPolicy(
            sandboxed_load_inspect=True,
            prefer_safe_tensors=True,
            torch_weights_only=False,
        ),
    )
    decision = validate_model_promotion(passport)
    assert not decision.accepted
    assert "torch_weights_only_required" in _codes(decision)


def test_artifact_requires_sandbox_inspection_ref_when_policy_requires_inspection():
    artifact = _artifact(sandbox_inspection_ref=None)
    decision = validate_model_promotion(_passport(artifact_manifest=(artifact,)))
    assert not decision.accepted
    assert "missing_sandbox_inspection_ref" in _codes(decision)


def test_project_produced_pickle_can_be_governed_with_hash_producer_and_sandbox():
    artifact = _artifact(
        uri="registry://models/momentum/v1/model.pkl",
        artifact_format=ModelArtifactFormat.PICKLE,
        source=ModelArtifactSource.PROJECT_PRODUCED,
        direct_load=False,
    )
    decision = validate_model_promotion(_passport(artifact_manifest=(artifact,)))
    assert decision.accepted


def test_model_passport_from_dict_round_trips_nested_payload():
    passport = model_passport_from_dict(_payload(_passport()))
    assert passport.model_version_ref == "model_version:momentum:v1"
    assert passport.artifact_manifest[0].artifact_ref == "artifact:model:v1"
    assert passport.safe_loading_policy.sandboxed_load_inspect is True


def test_persistent_model_governance_registry_replays_passport(tmp_path):
    path = tmp_path / "model_governance.jsonl"
    passport = _passport()
    registry = PersistentModelGovernanceRegistry(path)

    recorded = registry.record_passport(passport)
    reloaded = PersistentModelGovernanceRegistry(path)

    assert reloaded.passport(recorded.passport_id).model_version_ref == passport.model_version_ref
    assert [a.artifact_ref for a in reloaded.passport(recorded.passport_id).artifact_manifest] == [
        "artifact:model:v1"
    ]


def test_persistent_model_governance_registry_rejects_invalid_passport_without_write(tmp_path):
    path = tmp_path / "model_governance.jsonl"
    registry = PersistentModelGovernanceRegistry(path)

    with pytest.raises(ValueError, match="missing_validation_dossier_ref"):
        registry.record_passport(_passport(validation_dossier_ref=None))

    assert not path.exists()


def test_persistent_model_governance_registry_replays_monitoring_and_recertification(tmp_path):
    path = tmp_path / "model_governance.jsonl"
    registry = PersistentModelGovernanceRegistry(path)
    passport = registry.record_passport(_passport())

    profile = registry.record_monitoring_profile(
        ModelMonitoringProfile(
            model_version_ref=passport.model_version_ref,
            model_passport_ref=passport.passport_id,
            metric_refs=("metric:rolling_dsr",),
            schedule_ref="schedule:weekly",
            alert_policy_ref="alert:model_degradation",
            drift_signal_refs=("drift:feature_distribution",),
            performance_threshold_refs=("threshold:dsr_floor",),
            recertification_trigger_refs=(RecertificationTrigger.PERFORMANCE_DEGRADATION,),
        )
    )
    recertification = registry.record_recertification_record(
        ModelRecertificationRecord(
            model_version_ref=passport.model_version_ref,
            model_passport_ref=passport.passport_id,
            trigger=RecertificationTrigger.PERFORMANCE_DEGRADATION,
            change_event_ref="change_event:perf_drop:001",
            evidence_refs=("validation_dossier:momentum:v2",),
            decision="accepted",
            recorded_by="reviewer",
        )
    )

    reloaded = PersistentModelGovernanceRegistry(path)

    assert reloaded.monitoring_profile(profile.monitoring_profile_id).schedule_ref == "schedule:weekly"
    assert (
        reloaded.recertification_record(recertification.recertification_record_id).change_event_ref
        == "change_event:perf_drop:001"
    )
    assert len(reloaded.monitoring_profiles()) == 1
    assert len(reloaded.recertification_records()) == 1


def test_persistent_model_governance_registry_replays_artifact_inspection(tmp_path):
    path = tmp_path / "model_governance.jsonl"
    registry = PersistentModelGovernanceRegistry(path)
    passport = registry.record_passport(_passport())

    record = registry.record_artifact_inspection(_inspection(passport))
    reloaded = PersistentModelGovernanceRegistry(path)

    replayed = reloaded.artifact_inspection(record.artifact_inspection_record_id)
    assert replayed.inspection_ref == "inspect:model:v1"
    assert replayed.artifact_hash == "sha256:abc123"
    assert len(reloaded.artifact_inspections()) == 1


def test_model_governance_registry_rejects_artifact_inspection_hash_mismatch(tmp_path):
    path = tmp_path / "model_governance.jsonl"
    registry = PersistentModelGovernanceRegistry(path)
    passport = registry.record_passport(_passport())

    with pytest.raises(ValueError, match="artifact inspection hash does not match"):
        registry.record_artifact_inspection(_inspection(passport, artifact_hash="sha256:bad"))

    assert registry.artifact_inspections() == []


def test_model_governance_registry_rejects_accepted_external_pickle_inspection(tmp_path):
    path = tmp_path / "model_governance.jsonl"
    registry = PersistentModelGovernanceRegistry(path)
    artifact = _artifact(
        artifact_format=ModelArtifactFormat.PICKLE,
        source=ModelArtifactSource.EXTERNAL,
        direct_load=False,
    )
    unsafe_passport = _passport(artifact_manifest=(artifact,))

    with pytest.raises(ValueError, match="external_serialized_artifact_blocked"):
        registry.record_passport(unsafe_passport)

    assert not path.exists()


def test_model_governance_api_records_passport_summary(tmp_path, monkeypatch):
    client, _registry = _client_with_model_governance_registry(tmp_path, monkeypatch)

    response = client.post("/api/research-os/model_governance/passports", json=_payload(_passport()))
    assert response.status_code == 200
    assert response.json()["model_version_ref"] == "model_version:momentum:v1"
    assert response.json()["recorded_by"] == "u1"

    summary = client.get("/api/research-os/model_governance/summary")
    assert summary.status_code == 200
    body = summary.json()
    assert body["passport_total"] == 1
    assert body["passports"][0]["artifact_refs"] == ["artifact:model:v1"]
    assert body["passports"][0]["validation_dossier_ref"] == "validation_dossier:momentum:v1"


def test_model_governance_api_records_monitoring_profile_and_recertification(tmp_path, monkeypatch):
    client, registry = _client_with_model_governance_registry(tmp_path, monkeypatch)
    passport = registry.record_passport(
        _passport(), owner_user_id="u1", recorded_by="u1"
    )

    profile = client.post(
        "/api/research-os/model_governance/monitoring_profiles",
        json={
            "model_version_ref": passport.model_version_ref,
            "model_passport_ref": passport.passport_id,
            "metric_refs": ["metric:rolling_dsr"],
            "schedule_ref": "schedule:weekly",
            "alert_policy_ref": "alert:model_degradation",
            "drift_signal_refs": ["drift:feature_distribution"],
            "performance_threshold_refs": ["threshold:dsr_floor"],
            "recertification_trigger_refs": [RecertificationTrigger.PERFORMANCE_DEGRADATION.value],
        },
    )
    assert profile.status_code == 200, profile.text
    profile_body = profile.json()
    assert profile_body["model_passport_ref"] == passport.passport_id
    monitoring_qro, monitoring_ir, _, _ = _assert_model_governance_compiler_coverage(
        profile_body,
        qro_type="Model",
        entrypoint_ref="api:research_os.model_governance.monitoring_profiles",
        permission_ref="model_governance.monitoring_profile:user_manual",
    )
    assert monitoring_qro.input_contract["metric_ref_count"] == 1
    assert monitoring_qro.output_contract["monitoring_profile_id"] == profile_body["monitoring_profile_id"]
    _assert_ir_receipt_evidence(
        monitoring_qro,
        monitoring_ir,
        passport.passport_id,
    )

    recertification = client.post(
        "/api/research-os/model_governance/recertification_records",
        json={
            "model_version_ref": passport.model_version_ref,
            "model_passport_ref": passport.passport_id,
            "trigger": RecertificationTrigger.PERFORMANCE_DEGRADATION.value,
            "change_event_ref": "change_event:perf_drop:001",
            "evidence_refs": ["validation_dossier:momentum:v2"],
            "decision": "accepted",
        },
    )
    assert recertification.status_code == 200, recertification.text
    recertification_body = recertification.json()
    assert recertification_body["recorded_by"] == "u1"
    recertification_qro, recertification_ir, _, _ = _assert_model_governance_compiler_coverage(
        recertification_body,
        qro_type="ValidationDossier",
        entrypoint_ref="api:research_os.model_governance.recertification_records",
        permission_ref="model_governance.recertification:user_manual",
    )
    assert recertification_qro.input_contract["evidence_ref_count"] == 1
    assert recertification_qro.output_contract["decision"] == "accepted"
    _assert_ir_receipt_evidence(
        recertification_qro,
        recertification_ir,
        passport.passport_id,
    )

    summary = client.get("/api/research-os/model_governance/summary")
    assert summary.status_code == 200
    body = summary.json()
    assert body["monitoring_profile_total"] == 1
    assert body["recertification_record_total"] == 1
    assert body["monitoring_profiles"][0]["metric_refs"] == ["metric:rolling_dsr"]
    assert body["recertification_records"][0]["evidence_refs"] == ["validation_dossier:momentum:v2"]


def test_model_governance_api_records_artifact_inspection(tmp_path, monkeypatch):
    client, registry = _client_with_model_governance_registry(tmp_path, monkeypatch)
    passport = registry.record_passport(
        _passport(), owner_user_id="u1", recorded_by="u1"
    )

    response = client.post(
        "/api/research-os/model_governance/artifact_inspections",
        json={
            "model_version_ref": passport.model_version_ref,
            "model_passport_ref": passport.passport_id,
            "artifact_ref": "artifact:model:v1",
            "inspection_ref": "inspect:model:v1",
            "artifact_hash": "sha256:abc123",
            "inspection_status": "accepted",
            "inspection_mode": "metadata_only",
            "inspector_ref": "test-inspector:v1",
            "checks": ["sha256_match"],
            "limitations": ["raw loader stack trace must stay out of compiler"],
        },
    )
    assert response.status_code == 200, response.text
    response_body = response.json()
    assert response_body["inspection_ref"] == "inspect:model:v1"
    qro, ir, _, _ = _assert_model_governance_compiler_coverage(
        response_body,
        qro_type="ValidationDossier",
        entrypoint_ref="api:research_os.model_governance.artifact_inspections",
        permission_ref="model_governance.artifact_inspection:user_manual",
        forbidden_fragments=("raw loader stack trace",),
    )
    assert qro.output_contract["checks_count"] == 1
    assert qro.output_contract["limitations_count"] == 1
    _assert_ir_receipt_evidence(qro, ir, passport.passport_id)

    summary = client.get("/api/research-os/model_governance/summary")
    assert summary.status_code == 200
    body = summary.json()
    assert body["artifact_inspection_total"] == 1
    assert body["artifact_inspections"][0]["artifact_ref"] == "artifact:model:v1"


def test_model_governance_api_rejects_recertification_without_declared_trigger(tmp_path, monkeypatch):
    client, registry = _client_with_model_governance_registry(tmp_path, monkeypatch)
    passport = registry.record_passport(
        _passport(recertification_triggers=(RecertificationTrigger.MATERIAL_MODEL_CHANGE,)),
        owner_user_id="u1",
        recorded_by="u1",
    )

    response = client.post(
        "/api/research-os/model_governance/recertification_records",
        json={
            "model_version_ref": passport.model_version_ref,
            "model_passport_ref": passport.passport_id,
            "trigger": RecertificationTrigger.PERFORMANCE_DEGRADATION.value,
            "change_event_ref": "change_event:perf_drop:001",
            "evidence_refs": ["validation_dossier:momentum:v2"],
            "decision": "accepted",
        },
    )

    assert response.status_code == 422
    assert "recertification trigger not declared" in response.text
    assert registry.recertification_records() == []
    assert _compiler_record_counts() == (0, 0, 0, 0)


def test_model_governance_api_rejects_material_change_without_recertification(tmp_path, monkeypatch):
    client, registry = _client_with_model_governance_registry(tmp_path, monkeypatch)
    payload = {
        "passport": _payload(_passport(recertification_records=())),
        "change_events": [RecertificationTrigger.MATERIAL_MODEL_CHANGE.value],
    }

    response = client.post("/api/research-os/model_governance/passports", json=payload)

    assert response.status_code == 422
    assert "material_model_change_without_recertification" in response.text
    assert registry.passports() == []
    assert not registry.path.exists()


def test_model_predict_api_requires_stage_monitoring_and_records_invocation(tmp_path, monkeypatch):
    client, registry, model_registry = _client_with_model_registry(tmp_path, monkeypatch)
    artifact_path, artifact_hash, inspection_ref = _write_pickled_predictor(tmp_path)
    artifact = _artifact(
        uri=str(artifact_path),
        artifact_format=ModelArtifactFormat.PICKLE,
        content_hash=artifact_hash,
        sandbox_inspection_ref=inspection_ref,
        direct_load=False,
    )
    passport = registry.record_passport(
        _passport(
            artifact_manifest=(artifact,),
            feature_refs=("f1", "f2"),
            validation_dossier_ref="validation_dossier:momentum:v1",
        ),
        owner_user_id="u1",
    )
    registry.record_artifact_inspection(
        _inspection(
            passport,
            artifact_hash=artifact_hash,
            inspection_ref=inspection_ref,
            inspection_mode="metadata_only_no_deserialize",
            checks=("sha256_match", "serialized_deserialize_skipped"),
        ),
        owner_user_id="u1",
    )
    profile = registry.record_monitoring_profile(
        ModelMonitoringProfile(
            model_version_ref=passport.model_version_ref,
            model_passport_ref=passport.passport_id,
            metric_refs=("metric:prediction_error",),
            schedule_ref="schedule:per_batch",
            alert_policy_ref="alert:prediction_drift",
        ),
        owner_user_id="u1",
    )
    version = model_registry.register_version(
        "momentum",
        artifact_path=str(artifact_path),
        model_passport_ref=passport.passport_id,
        validation_dossier_ref="validation_dossier:momentum:v1",
        owner_user_id="u1",
    )
    model_registry._apply_stage_unchecked(
        "momentum", version.version, "staging", owner_user_id="u1"
    )

    response = client.post(
        f"/api/models/momentum/versions/{version.version}/predict",
        json={
            "feature_cols": ["f1", "f2"],
            "rows": [{"f1": 1.5, "f2": 2.0}],
            "signal_contract": {
                "name": "Momentum prediction signal",
                "source_lib": "ml",
                "output_kind": "signed_prediction",
                "horizon": 5,
                "leakage": {"oof": True, "purge": True, "embargo": True},
                "train_test_lock_ref": "split_lock:momentum:v1",
                "honest_n_ref": "honest_n:momentum:v1",
                "forecast_time_ref": "time:asof",
                "prediction_horizon_ref": "horizon:5d",
                "unit_ref": "unit:expected_return",
                "direction_semantics_ref": "direction:signed_score",
                "confidence_ref": "confidence:model_score",
                "expires_at_ref": "expiry:next_rebalance",
            },
        },
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["predictions"] == [3.5]
    assert body["monitoring_profile_ref"] == profile.monitoring_profile_id
    assert body["artifact_inspection_ref"] == inspection_ref
    assert body["signal_ref"].startswith("sig::")
    qro, ir, _, _ = _assert_model_governance_compiler_coverage(
        body,
        qro_type="Forecast",
        entrypoint_ref="api:models.predict",
        permission_ref="model_governance.serving_invocation:user_manual",
        forbidden_fragments=("'f1': 1.5", "'f2': 2.0", "'predictions': [3.5]", str(artifact_path)),
    )
    assert qro.input_contract["row_count"] == 1
    assert qro.output_contract["prediction_hash"] == body["prediction_hash"]
    _assert_ir_receipt_evidence(qro, ir, passport.passport_id)
    contracts = client.get("/api/factors/signal_contracts").json()
    assert any(item["signal_ref"] == body["signal_ref"] for item in contracts)

    summary = client.get("/api/research-os/model_governance/summary").json()
    assert summary["serving_invocation_total"] == 1
    invocation = summary["serving_invocations"][0]
    assert invocation["row_count"] == 1
    assert invocation["feature_refs"] == ["f1", "f2"]
    assert invocation["prediction_hash"]
    assert "1.5" not in str(invocation)
    assert "3.5" not in str(invocation)


def test_model_predict_api_rejects_incomplete_signal_protocol(tmp_path, monkeypatch):
    client, registry, model_registry = _client_with_model_registry(tmp_path, monkeypatch)
    artifact_path, artifact_hash, inspection_ref = _write_pickled_predictor(tmp_path)
    artifact = _artifact(
        uri=str(artifact_path),
        artifact_format=ModelArtifactFormat.PICKLE,
        content_hash=artifact_hash,
        sandbox_inspection_ref=inspection_ref,
        direct_load=False,
    )
    passport = registry.record_passport(
        _passport(
            artifact_manifest=(artifact,),
            feature_refs=("f1", "f2"),
            validation_dossier_ref="validation_dossier:momentum:v1",
        ),
        owner_user_id="u1",
        recorded_by="u1",
    )
    registry.record_artifact_inspection(
        _inspection(
            passport,
            artifact_hash=artifact_hash,
            inspection_ref=inspection_ref,
            inspection_mode="metadata_only_no_deserialize",
        ),
        owner_user_id="u1",
    )
    registry.record_monitoring_profile(
        ModelMonitoringProfile(
            model_version_ref=passport.model_version_ref,
            model_passport_ref=passport.passport_id,
            metric_refs=("metric:prediction_error",),
            schedule_ref="schedule:per_batch",
            alert_policy_ref="alert:prediction_drift",
        ),
        owner_user_id="u1",
        recorded_by="u1",
    )
    version = model_registry.register_version(
        "momentum",
        artifact_path=str(artifact_path),
        model_passport_ref=passport.passport_id,
        validation_dossier_ref="validation_dossier:momentum:v1",
        owner_user_id="u1",
    )
    model_registry._apply_stage_unchecked(
        "momentum", version.version, "staging", owner_user_id="u1"
    )

    response = client.post(
        f"/api/models/momentum/versions/{version.version}/predict",
        json={
            "feature_cols": ["f1", "f2"],
            "rows": [{"f1": 1.5, "f2": 2.0}],
            "signal_contract": {
                "output_kind": "signed_prediction",
                "horizon": 5,
                "leakage": {"oof": True, "purge": True, "embargo": True},
                "train_test_lock_ref": "split_lock:momentum:v1",
                "honest_n_ref": "honest_n:momentum:v1",
                "forecast_time_ref": "time:asof",
                "prediction_horizon_ref": "horizon:5d",
                "unit_ref": "unit:expected_return",
                "direction_semantics_ref": "direction:signed_score",
                "confidence_ref": "confidence:model_score",
            },
        },
    )
    assert response.status_code == 422
    assert "signal_protocol_incomplete" in response.text
    assert registry.serving_invocations() == []
    assert _compiler_record_counts() == (0, 0, 0, 0)


def test_model_predict_api_rejects_dev_stage_without_serving_invocation(tmp_path, monkeypatch):
    client, registry, model_registry = _client_with_model_registry(tmp_path, monkeypatch)
    artifact_path, artifact_hash, inspection_ref = _write_pickled_predictor(tmp_path)
    artifact = _artifact(
        uri=str(artifact_path),
        artifact_format=ModelArtifactFormat.PICKLE,
        content_hash=artifact_hash,
        sandbox_inspection_ref=inspection_ref,
        direct_load=False,
    )
    passport = registry.record_passport(
        _passport(artifact_manifest=(artifact,), feature_refs=("f1", "f2")),
        owner_user_id="u1",
        recorded_by="u1",
    )
    registry.record_artifact_inspection(
        _inspection(
            passport,
            artifact_hash=artifact_hash,
            inspection_ref=inspection_ref,
            inspection_mode="metadata_only_no_deserialize",
        ),
        owner_user_id="u1",
    )
    model_registry.register_version(
        "momentum",
        artifact_path=str(artifact_path),
        model_passport_ref=passport.passport_id,
        validation_dossier_ref=passport.validation_dossier_ref,
        owner_user_id="u1",
    )

    response = client.post(
        "/api/models/momentum/versions/1/predict",
        json={"feature_cols": ["f1", "f2"], "rows": [{"f1": 1.5, "f2": 2.0}]},
    )
    assert response.status_code == 422
    assert "staging or production stage" in response.text
    assert registry.serving_invocations() == []
    assert _compiler_record_counts() == (0, 0, 0, 0)


def test_model_registry_promotion_requires_recorded_model_passport_ref(tmp_path):
    registry = PersistentModelGovernanceRegistry(tmp_path / "model_governance.jsonl")
    model_registry = ModelRegistry(
        tmp_path / "experiments",
        gate_service=_approval_service(tmp_path),
        model_governance_registry=registry,
    )
    model_registry.register_version(
        "momentum", artifact_path="a.safetensors", owner_user_id="alice"
    )

    with pytest.raises(GateStateError, match="model_passport_ref"):
        model_registry.promote(
            "momentum",
            1,
            "staging",
            created_by="alice",
            verification_record_id="verdict:001",
            evidence=_promotion_evidence(),
            strategy_goal_ref="theme",
            owner_user_id="alice",
        )


def test_model_registry_promotion_rejects_unrecorded_model_passport_ref(tmp_path):
    model_registry = ModelRegistry(
        tmp_path / "experiments",
        gate_service=_approval_service(tmp_path),
        model_governance_registry=PersistentModelGovernanceRegistry(tmp_path / "model_governance.jsonl"),
    )
    model_registry.register_version(
        "momentum", artifact_path="a.safetensors", owner_user_id="alice"
    )

    with pytest.raises(GateStateError, match="未为 owner=alice 登记"):
        model_registry.promote(
            "momentum",
            1,
            "staging",
            created_by="alice",
            verification_record_id="verdict:001",
            evidence=_promotion_evidence(),
            strategy_goal_ref="theme",
            model_passport_ref="model_passport:missing",
            owner_user_id="alice",
        )


def test_model_registry_promotion_rejects_mismatched_model_passport_ref(tmp_path):
    registry = PersistentModelGovernanceRegistry(tmp_path / "model_governance.jsonl")
    passport = registry.record_passport(
        _passport(model_version_ref="model_version:other:v1"),
        owner_user_id="alice",
        recorded_by="alice",
    )
    model_registry = ModelRegistry(
        tmp_path / "experiments",
        gate_service=_approval_service(tmp_path),
        model_governance_registry=registry,
    )
    model_registry.register_version(
        "momentum", artifact_path="a.safetensors", owner_user_id="alice"
    )

    with pytest.raises(GateStateError, match="不匹配"):
        model_registry.promote(
            "momentum",
            1,
            "staging",
            created_by="alice",
            verification_record_id="verdict:001",
            evidence=_promotion_evidence(),
            strategy_goal_ref="theme",
            model_passport_ref=passport.passport_id,
            owner_user_id="alice",
        )


def test_model_registry_promotion_records_passport_and_dossier_refs_in_gate_evidence(tmp_path):
    registry = PersistentModelGovernanceRegistry(tmp_path / "model_governance.jsonl")
    passport = registry.record_passport(
        _passport(model_version_ref="model_version:momentum:v1"),
        owner_user_id="alice",
        recorded_by="alice",
    )
    model_registry = ModelRegistry(
        tmp_path / "experiments",
        gate_service=_approval_service(tmp_path),
        model_governance_registry=registry,
    )
    model_registry.register_version(
        "momentum", artifact_path="a.safetensors", owner_user_id="alice"
    )

    gate = model_registry.promote(
        "momentum",
        1,
        "staging",
        created_by="alice",
        verification_record_id="verdict:001",
        evidence=_promotion_evidence(),
        strategy_goal_ref="theme",
        model_passport_ref=passport.passport_id,
        owner_user_id="alice",
    )

    assert gate.decision == "pending"
    assert gate.evidence["model_passport_ref"] == passport.passport_id
    assert gate.evidence["validation_dossier_ref"] == "validation_dossier:momentum:v1"


def test_model_promote_api_requires_and_accepts_model_passport_ref(tmp_path, monkeypatch):
    client, registry, model_registry = _client_with_model_registry(tmp_path, monkeypatch)
    model_registry.register_version(
        "momentum", artifact_path="a.safetensors", owner_user_id="u1"
    )

    missing = client.post(
        "/api/models/momentum/promote",
        json={
            "version": 1,
            "stage": "staging",
            "verification_record_id": "verdict:001",
            "evidence": _promotion_evidence(),
            "strategy_goal_ref": "theme",
        },
    )
    assert missing.status_code == 422
    assert "model_passport_ref" in missing.text

    passport = registry.record_passport(
        _passport(model_version_ref="model_version:momentum:v1"),
        owner_user_id="u1",
        recorded_by="u1",
    )
    accepted = client.post(
        "/api/models/momentum/promote",
        json={
            "version": 1,
            "stage": "staging",
            "verification_record_id": "verdict:001",
            "evidence": _promotion_evidence(),
            "strategy_goal_ref": "theme",
            "model_passport_ref": passport.passport_id,
        },
    )

    assert accepted.status_code == 200
    body = accepted.json()
    assert body["decision"] == "pending"
    assert body["evidence"]["model_passport_ref"] == passport.passport_id
    assert body["evidence"]["validation_dossier_ref"] == "validation_dossier:momentum:v1"


def test_model_promote_api_records_model_qro_without_raw_evidence(tmp_path, monkeypatch):
    client, registry, model_registry = _client_with_model_registry(tmp_path, monkeypatch)
    graph = app_main.RESEARCH_GRAPH_STORE
    model_registry.register_version(
        "momentum",
        artifact_path="a.safetensors",
        owner_user_id="u1",
    )
    passport = registry.record_passport(
        _passport(model_version_ref="model_version:momentum:v1"),
        owner_user_id="u1",
        recorded_by="u1",
    )

    response = client.post(
        "/api/models/momentum/promote",
        json={
            "version": 1,
            "stage": "staging",
            "verification_record_id": "verdict:001",
            "evidence": _promotion_evidence(),
            "strategy_goal_ref": "theme",
            "model_passport_ref": passport.passport_id,
        },
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["decision"] == "pending"
    assert body["qro_id"]
    assert body["research_graph_command_id"]
    assert body["compiler_ir_ref"]
    assert body["compiler_pass_ref"]
    assert body["entrypoint_coverage_ref"]
    qro = graph.qro(body["qro_id"])
    assert qro.qro_type == "Model" or getattr(qro.qro_type, "value", None) == "Model"
    assert qro.input_contract["entry_source"] == "api"
    assert qro.input_contract["target_stage"] == "staging"
    assert qro.input_contract["gate_id"] == body["gate_id"]
    assert qro.output_contract["status"] == "promotion_gate_pending"
    assert qro.output_contract["model_version_ref"] == "model_version:momentum:v1"
    assert qro.output_contract["model_passport_ref"] == passport.passport_id
    assert qro.output_contract["validation_dossier_ref"] == "validation_dossier:momentum:v1"
    assert qro.output_contract["evidence_hash"]
    qro_contract_text = str(qro.input_contract) + str(qro.output_contract)
    assert "dsr" not in qro_contract_text
    assert "pbo" not in qro_contract_text
    assert "champion_challenger" not in qro_contract_text
    assert "delta_sharpe" not in qro_contract_text
    ir = app_main.COMPILER_IR_STORE.ir(body["compiler_ir_ref"])
    compiler_pass = app_main.COMPILER_IR_STORE.compiler_pass(body["compiler_pass_ref"])
    coverage = app_main.GOAL_ENTRYPOINT_COVERAGE_REGISTRY.coverage(body["entrypoint_coverage_ref"])
    assert ir.source_qro_refs == (body["qro_id"],)
    assert ir.graph_command_refs == (body["research_graph_command_id"],)
    assert ir.permission_ref == "model_registry.promote:user_manual"
    _assert_ir_receipt_evidence(
        qro,
        ir,
        "validation_dossier:momentum:v1",
        passport.passport_id,
    )
    assert compiler_pass.entry_source == "api"
    assert compiler_pass.actor_source == "user_manual"
    assert coverage.entrypoint_ref == "api:models.promote"
    assert coverage.qro_refs == (body["qro_id"],)
    assert coverage.compiler_ir_refs == (body["compiler_ir_ref"],)
    compiled_text = str(ir.__dict__) + str(compiler_pass.__dict__) + str(coverage.__dict__)
    assert "dsr" not in compiled_text
    assert "pbo" not in compiled_text
    assert "champion_challenger" not in compiled_text
    assert "delta_sharpe" not in compiled_text

    audit = client.get("/api/research-os/graph/commands", params={"limit": 5})
    assert audit.status_code == 200, audit.text
    matching = [
        command["payload"]["qro"]
        for command in audit.json()["commands"]
        if command["payload"].get("qro", {}).get("qro_id") == body["qro_id"]
    ]
    assert matching
    assert matching[0]["output_contract"]["evidence_hash"]
    assert "champion_challenger" not in str(matching[0])
    assert "delta_sharpe" not in str(matching[0])


def test_model_promote_api_records_rejected_model_qro_without_raw_gaps(tmp_path, monkeypatch):
    client, registry, model_registry = _client_with_model_registry(tmp_path, monkeypatch)
    graph = app_main.RESEARCH_GRAPH_STORE
    model_registry.register_version(
        "momentum", artifact_path="a.safetensors", owner_user_id="u1"
    )
    passport = registry.record_passport(
        _passport(model_version_ref="model_version:momentum:v1"),
        owner_user_id="u1",
        recorded_by="u1",
    )

    rejected = client.post(
        "/api/models/momentum/promote",
        json={
            "version": 1,
            "stage": "staging",
            "verification_record_id": "verdict:001",
            "evidence": _promotion_evidence(dsr=0.10, pbo=0.90, bootstrap_ci=(-0.2, 0.4)),
            "strategy_goal_ref": "theme",
            "model_passport_ref": passport.passport_id,
        },
    )

    assert rejected.status_code == 422
    detail = rejected.json()["detail"]
    assert detail["rejected"] is True
    assert detail["gate_id"]
    assert detail["qro_id"]
    assert detail["research_graph_command_id"]
    assert detail["compiler_ir_ref"]
    assert detail["compiler_pass_ref"]
    assert detail["entrypoint_coverage_ref"]
    qro = graph.qro(detail["qro_id"])
    assert qro.output_contract["status"] == "promotion_gate_rejected"
    assert qro.output_contract["decision"] == "rejected"
    assert qro.output_contract["gap_count"] >= 1
    assert qro.output_contract["gaps_hash"]
    assert qro.output_contract["verdict_hash"]
    qro_contract_text = str(qro.input_contract) + str(qro.output_contract)
    assert "三角不同向" not in qro_contract_text
    assert "证据不足" not in qro_contract_text
    assert "dsr" not in qro_contract_text
    assert "pbo" not in qro_contract_text
    assert "champion_challenger" not in qro_contract_text
    ir = app_main.COMPILER_IR_STORE.ir(detail["compiler_ir_ref"])
    compiler_pass = app_main.COMPILER_IR_STORE.compiler_pass(detail["compiler_pass_ref"])
    coverage = app_main.GOAL_ENTRYPOINT_COVERAGE_REGISTRY.coverage(detail["entrypoint_coverage_ref"])
    assert ir.source_qro_refs == (detail["qro_id"],)
    assert ir.graph_command_refs == (detail["research_graph_command_id"],)
    assert ir.permission_ref == "model_registry.promote:user_manual"
    assert compiler_pass.entry_source == "api"
    assert coverage.entrypoint_ref == "api:models.promote"
    compiled_text = str(ir.__dict__) + str(compiler_pass.__dict__) + str(coverage.__dict__)
    assert "证据不足" not in compiled_text
    assert "dsr" not in compiled_text
    assert "pbo" not in compiled_text


def test_model_promotion_approval_records_model_qro_without_reason_payload(tmp_path, monkeypatch):
    client, registry, model_registry = _client_with_model_registry(tmp_path, monkeypatch)
    graph = app_main.RESEARCH_GRAPH_STORE
    model_registry.register_version(
        "momentum",
        artifact_path="a.safetensors",
        owner_user_id="u1",
    )
    passport = registry.record_passport(
        _passport(model_version_ref="model_version:momentum:v1"),
        owner_user_id="u1",
        recorded_by="u1",
    )
    opened = client.post(
        "/api/models/momentum/promote",
        json={
            "version": 1,
            "stage": "staging",
            "created_by": "creator",
            "verification_record_id": "verdict:001",
            "evidence": _promotion_evidence(),
            "strategy_goal_ref": "theme",
            "model_passport_ref": passport.passport_id,
        },
    )
    assert opened.status_code == 200, opened.text
    gate_id = opened.json()["gate_id"]

    granted = client.post(
        f"/api/models/momentum/gates/{gate_id}/reviewer-grants",
        json={
            "reviewer_user_id": "reviewer-u2",
            "permissions": ["view", "approve", "reject"],
            "expires_at_utc": "2099-01-01T00:00:00+00:00",
        },
    )
    assert granted.status_code == 200, granted.text
    app_main.app.dependency_overrides[require_user_dependency] = lambda: SimpleNamespace(
        username="reviewer-u2",
        user_id="reviewer-u2",
    )

    approved = client.post(
        f"/api/models/momentum/gates/{gate_id}/approve",
        json={
            "approver": "reviewer",
            "reason": "Reviewed validation dossier and promotion risk before staging.",
            "risk_restated": "Model remains offline until loading and monitoring checks pass.",
        },
    )

    assert approved.status_code == 200, approved.text
    body = approved.json()
    assert body["decision"] == "approved"
    assert body["side_effect_ref"] == "stage:u1:momentum:v1:staging"
    assert body["qro_id"]
    assert body["research_graph_command_id"]
    assert body["compiler_ir_ref"]
    assert body["compiler_pass_ref"]
    assert body["entrypoint_coverage_ref"]
    qro = graph.qro(body["qro_id"])
    assert qro.output_contract["status"] == "promotion_gate_approved"
    assert qro.output_contract["gate_id"] == gate_id
    assert qro.output_contract["reason_hash"]
    assert qro.output_contract["risk_restated_hash"]
    assert qro.output_contract["side_effect_ref"] == "stage:u1:momentum:v1:staging"
    assert qro.output_contract["approved_by"] == "reviewer-u2"
    assert qro.owner == "u1"
    qro_contract_text = str(qro.input_contract) + str(qro.output_contract)
    assert "Reviewed validation dossier" not in qro_contract_text
    assert "Model remains offline" not in qro_contract_text
    assert "dsr" not in qro_contract_text
    assert "pbo" not in qro_contract_text
    ir = app_main.COMPILER_IR_STORE.ir(body["compiler_ir_ref"])
    compiler_pass = app_main.COMPILER_IR_STORE.compiler_pass(body["compiler_pass_ref"])
    coverage = app_main.GOAL_ENTRYPOINT_COVERAGE_REGISTRY.coverage(body["entrypoint_coverage_ref"])
    assert ir.source_qro_refs == (body["qro_id"],)
    assert ir.graph_command_refs == (body["research_graph_command_id"],)
    assert ir.permission_ref == "model_registry.promotion.approve:user_manual"
    _assert_ir_receipt_evidence(
        qro,
        ir,
        "validation_dossier:momentum:v1",
        passport.passport_id,
    )
    assert compiler_pass.entry_source == "api"
    assert coverage.entrypoint_ref == "api:models.gates.approve"
    compiled_text = str(ir.__dict__) + str(compiler_pass.__dict__) + str(coverage.__dict__)
    assert "Reviewed validation dossier" not in compiled_text
    assert "Model remains offline" not in compiled_text
    assert "dsr" not in compiled_text
    assert "pbo" not in compiled_text
    assert model_registry.list_versions("momentum")[0].stage == "staging"


# ───────────────── C-S15 producer：dataset schema drift → DATA_SCHEMA_CHANGE 重认证 ─────────────────
#
# 训练台是 GOAL §15「data schema change」重认证触发器的 producer。下列测试覆盖：
#   ① schema fingerprint 比对（schema_drift 纯单测：指纹确定性 + dtype 敏感 + diff + change_event_ref 绑定）
#   ② 自动事件发射（schema 变 → 训练后 record_passport 带 DATA_SCHEMA_CHANGE change_event）
#   ③ pre-run recert 门（_train_ml/_run_code 前 fail-closed 阻断未清重认证义务的 schema 变更）
# 变异三态：schema 变无 recert → block（对抗，删门必红）；schema 未变 → 放行；recert 已清 → 放行。


def _schema_map(*features: str, label_dtype: str = "float64", **dtypes: str) -> dict[str, str]:
    base = {f: dtypes.get(f, "float64") for f in features}
    base["label"] = label_dtype
    return base


def test_schema_fingerprint_is_deterministic_and_dtype_sensitive():
    a = schema_drift.compute_dataset_schema(_schema_map("f1", "f2"), ["f1", "f2"], "label")
    a_again = schema_drift.compute_dataset_schema(_schema_map("f1", "f2"), ["f1", "f2"], "label")
    assert a.fingerprint == a_again.fingerprint  # 同 schema → 同指纹（值无关、确定）

    added = schema_drift.compute_dataset_schema(_schema_map("f1", "f2", "f3"), ["f1", "f2", "f3"], "label")
    assert a.fingerprint != added.fingerprint  # 加列 → 变

    retyped = schema_drift.compute_dataset_schema(
        _schema_map("f1", "f2", f2="int64"), ["f1", "f2"], "label"
    )
    assert a.fingerprint != retyped.fingerprint  # 同名改 dtype → 变（dtype 敏感，不可绕过）

    reordered = schema_drift.compute_dataset_schema(_schema_map("f1", "f2"), ["f2", "f1"], "label")
    assert a.fingerprint != reordered.fingerprint  # 特征顺序变 → 变（保守 fail-closed）

    label_changed = schema_drift.compute_dataset_schema(
        _schema_map("f1", "f2", label_dtype="int64"), ["f1", "f2"], "label"
    )
    assert a.fingerprint != label_changed.fingerprint  # label dtype 变 → 变


def test_schema_diff_reports_add_remove_retype_label_and_reorder():
    prev = schema_drift.compute_dataset_schema(_schema_map("f1", "f2"), ["f1", "f2"], "label")
    nxt = schema_drift.compute_dataset_schema(
        _schema_map("f1", "f3", f1="int64"), ["f1", "f3"], "label"
    )
    diff = schema_drift.diff_schemas(prev, nxt)
    assert diff.changed
    assert diff.added == ("f3",)
    assert diff.removed == ("f2",)
    assert diff.retyped == (("f1", "float64", "int64"),)

    unchanged = schema_drift.diff_schemas(prev, prev)
    assert not unchanged.changed
    assert unchanged.describe() == "no_structural_change"

    reordered = schema_drift.diff_schemas(
        prev, schema_drift.compute_dataset_schema(_schema_map("f1", "f2"), ["f2", "f1"], "label")
    )
    assert reordered.reordered and not reordered.added and not reordered.removed


def test_schema_change_event_ref_binds_model_and_both_fingerprints():
    ref = schema_drift.schema_change_event_ref("model_type_card:m", "fp_a", "fp_b")
    assert ref == schema_drift.schema_change_event_ref("model_type_card:m", "fp_a", "fp_b")  # 确定
    # 换模型 / 换任一端指纹 → 不同 ref（一条重认证不能被挪用到别的模型或别的 schema 迁移）
    assert ref != schema_drift.schema_change_event_ref("model_type_card:other", "fp_a", "fp_b")
    assert ref != schema_drift.schema_change_event_ref("model_type_card:m", "fp_x", "fp_b")
    assert ref != schema_drift.schema_change_event_ref("model_type_card:m", "fp_a", "fp_y")


# ---- 训练台端到端（ridge：sklearn 进程内，快、torch 无关）----

_SCHEMA_MODEL = "ridge"
_SCHEMA_MODEL_CARD_REF = f"model_type_card:{_SCHEMA_MODEL}"
_SCHEMA_OWNER = "schema-owner"


def _schema_panel(features, *, n: int = 240, seed: int = 0) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    base = datetime(2024, 1, 1, tzinfo=UTC)
    data: dict[str, object] = {"ts": [base + timedelta(days=i) for i in range(n)]}
    for f in features:
        data[f] = rng.normal(size=n)
    data["label"] = rng.normal(size=n)
    return pd.DataFrame(data)


def _schema_request(features) -> TrainingRequest:
    return TrainingRequest(
        name="schema-drift",
        model=_SCHEMA_MODEL,
        task="regression",
        feature_cols=list(features),
        label_col="label",
        n_splits=4,
    )


def _schema_service(tmp_path):
    registry = PersistentModelGovernanceRegistry(tmp_path / "model_governance.jsonl")
    svc = TrainingService(root=tmp_path / "training_runs", model_governance_registry=registry)
    return svc, registry


def _expected_change_event_ref(prev_fp: str, features) -> str:
    now_fp = schema_drift.compute_dataset_schema(_schema_panel(features), features, "label").fingerprint
    return now_fp, schema_drift.schema_change_event_ref(_SCHEMA_MODEL_CARD_REF, prev_fp, now_fp)


def test_first_governed_training_run_records_schema_fingerprint(tmp_path):
    """① schema fingerprint 真被算出并钉进 passport（producer 落账）。"""
    svc, registry = _schema_service(tmp_path)
    job = svc.train_now(
        _schema_request(["f1", "f2"]),
        _schema_panel(["f1", "f2"]),
        owner_user_id=_SCHEMA_OWNER,
    )
    assert job.status == "succeeded", job.error
    passport = registry.passports(owner_user_id=_SCHEMA_OWNER)[0]
    expected = schema_drift.compute_dataset_schema(
        _schema_panel(["f1", "f2"]), ["f1", "f2"], "label"
    ).fingerprint
    assert passport.dataset_schema_fingerprint == expected
    assert registry.change_events(passport.passport_id, owner_user_id=_SCHEMA_OWNER) == ()


def test_training_pre_run_gate_blocks_data_schema_change_without_recert(tmp_path):
    """③ 变异三态·态一（对抗·种坏必抓）：同模型新 run schema 变、无 recert → 训练开跑前 fail-closed 阻断。

    删除 _execute 里 `recert_plan = self._evaluate_data_schema_recertification(...)` 这行（pre-run 门）
    后本测试必变红：① job2 会变 succeeded（不再失败）② registry 多出第二份 passport
    ③ result.json 会被写出（训练真跑了）。还原即恢复绿。
    """
    svc, registry = _schema_service(tmp_path)

    job1 = svc.train_now(
        _schema_request(["f1", "f2"]),
        _schema_panel(["f1", "f2"]),
        owner_user_id=_SCHEMA_OWNER,
    )
    assert job1.status == "succeeded", job1.error
    assert len(registry.passports(owner_user_id=_SCHEMA_OWNER)) == 1

    # run 2：同模型，加列 f3 → schema 指纹变、无 DATA_SCHEMA_CHANGE 重认证记录 → 必须 fail-closed
    job2 = svc.train_now(
        _schema_request(["f1", "f2", "f3"]),
        _schema_panel(["f1", "f2", "f3"]),
        owner_user_id=_SCHEMA_OWNER,
    )
    assert job2.status == "failed"
    assert job2.error.startswith("DataSchemaRecertificationRequired"), job2.error
    assert "DATA_SCHEMA_CHANGE" in job2.error or "data_schema_change" in job2.error
    # 训练在门前被挡：result.json 未写出、未登记第二份 passport / 第二个版本
    job2_dir = svc._jobs.job_dir(job2.job_id)
    assert not (job2_dir / "result.json").exists()
    assert len(registry.passports(owner_user_id=_SCHEMA_OWNER)) == 1
    assert len(svc._models.list_versions(_SCHEMA_MODEL, owner_user_id=_SCHEMA_OWNER)) == 1


def test_training_passes_when_data_schema_unchanged(tmp_path):
    """变异三态·态二：schema 未变（同特征/同 dtype、数据值不同）→ 正常放行、无重认证事件。"""
    svc, registry = _schema_service(tmp_path)
    job1 = svc.train_now(
        _schema_request(["f1", "f2"]),
        _schema_panel(["f1", "f2"], seed=1),
        owner_user_id=_SCHEMA_OWNER,
    )
    assert job1.status == "succeeded", job1.error
    job2 = svc.train_now(
        _schema_request(["f1", "f2"]),
        _schema_panel(["f1", "f2"], seed=2),
        owner_user_id=_SCHEMA_OWNER,
    )
    assert job2.status == "succeeded", job2.error

    passports = registry.passports(owner_user_id=_SCHEMA_OWNER)
    assert len(passports) == 2
    assert passports[0].dataset_schema_fingerprint == passports[1].dataset_schema_fingerprint
    assert registry.change_events(
        passports[1].passport_id, owner_user_id=_SCHEMA_OWNER
    ) == ()


def test_training_passes_after_data_schema_recertification(tmp_path):
    """变异三态·态三 + ②自动事件发射：schema 变后补一条 accepted DATA_SCHEMA_CHANGE 重认证 →
    下一 run 放行、训练后 passport 带 DATA_SCHEMA_CHANGE change_event + 绑定清账记录。"""
    svc, registry = _schema_service(tmp_path)
    job1 = svc.train_now(
        _schema_request(["f1", "f2"]),
        _schema_panel(["f1", "f2"]),
        owner_user_id=_SCHEMA_OWNER,
    )
    assert job1.status == "succeeded", job1.error
    p1 = registry.passports(owner_user_id=_SCHEMA_OWNER)[0]

    now_fp, change_event_ref = _expected_change_event_ref(p1.dataset_schema_fingerprint, ["f1", "f2", "f3"])
    recert = registry.record_recertification_record(
        ModelRecertificationRecord(
            model_version_ref=p1.model_version_ref,
            model_passport_ref=p1.passport_id,
            trigger=RecertificationTrigger.DATA_SCHEMA_CHANGE,
            change_event_ref=change_event_ref,
            evidence_refs=("validation_dossier:recert:schema:v2",),
            decision="accepted",
            recorded_by="reviewer",
        ),
        owner_user_id=_SCHEMA_OWNER,
        recorded_by="reviewer",
    )

    job2 = svc.train_now(
        _schema_request(["f1", "f2", "f3"]),
        _schema_panel(["f1", "f2", "f3"]),
        owner_user_id=_SCHEMA_OWNER,
    )
    assert job2.status == "succeeded", job2.error

    passports = registry.passports(owner_user_id=_SCHEMA_OWNER)
    assert len(passports) == 2
    p2 = passports[1]
    assert p2.dataset_schema_fingerprint == now_fp
    # ② DATA_SCHEMA_CHANGE change_event 真被发射并登记在 P2 上
    assert registry.change_events(p2.passport_id, owner_user_id=_SCHEMA_OWNER) == (
        RecertificationTrigger.DATA_SCHEMA_CHANGE.value,
    )
    # 清账记录被绑回 passport（record_passport §15 门据此放行）
    assert recert.recertification_record_id in p2.recertification_records


def test_training_gate_not_cleared_by_mismatched_change_event_ref(tmp_path):
    """对抗·防绕过：重认证记录的 change_event_ref 对不上本次 schema 迁移 → 门不认、仍 fail-closed。"""
    svc, registry = _schema_service(tmp_path)
    job1 = svc.train_now(
        _schema_request(["f1", "f2"]),
        _schema_panel(["f1", "f2"]),
        owner_user_id=_SCHEMA_OWNER,
    )
    assert job1.status == "succeeded", job1.error
    p1 = registry.passports(owner_user_id=_SCHEMA_OWNER)[0]

    # 一条 trigger 对、decision 对，但 change_event_ref 指向别的迁移 → 不能清本次的账
    registry.record_recertification_record(
        ModelRecertificationRecord(
            model_version_ref=p1.model_version_ref,
            model_passport_ref=p1.passport_id,
            trigger=RecertificationTrigger.DATA_SCHEMA_CHANGE,
            change_event_ref="data_schema_change:unrelated-transition",
            evidence_refs=("validation_dossier:recert:wrong",),
            decision="accepted",
            recorded_by="reviewer",
        ),
        owner_user_id=_SCHEMA_OWNER,
        recorded_by="reviewer",
    )

    job2 = svc.train_now(
        _schema_request(["f1", "f2", "f3"]),
        _schema_panel(["f1", "f2", "f3"]),
        owner_user_id=_SCHEMA_OWNER,
    )
    assert job2.status == "failed"
    assert job2.error.startswith("DataSchemaRecertificationRequired"), job2.error
    assert len(registry.passports(owner_user_id=_SCHEMA_OWNER)) == 1


def test_training_gate_not_cleared_by_rejected_recertification(tmp_path):
    """对抗·防绕过：change_event_ref 对上，但 decision=rejected（未清账）→ 门仍 fail-closed。"""
    svc, registry = _schema_service(tmp_path)
    job1 = svc.train_now(
        _schema_request(["f1", "f2"]),
        _schema_panel(["f1", "f2"]),
        owner_user_id=_SCHEMA_OWNER,
    )
    assert job1.status == "succeeded", job1.error
    p1 = registry.passports(owner_user_id=_SCHEMA_OWNER)[0]

    _now_fp, change_event_ref = _expected_change_event_ref(p1.dataset_schema_fingerprint, ["f1", "f2", "f3"])
    registry.record_recertification_record(
        ModelRecertificationRecord(
            model_version_ref=p1.model_version_ref,
            model_passport_ref=p1.passport_id,
            trigger=RecertificationTrigger.DATA_SCHEMA_CHANGE,
            change_event_ref=change_event_ref,
            evidence_refs=("validation_dossier:recert:rejected",),
            decision="rejected",
            recorded_by="reviewer",
        ),
        owner_user_id=_SCHEMA_OWNER,
        recorded_by="reviewer",
    )

    job2 = svc.train_now(
        _schema_request(["f1", "f2", "f3"]),
        _schema_panel(["f1", "f2", "f3"]),
        owner_user_id=_SCHEMA_OWNER,
    )
    assert job2.status == "failed"
    assert job2.error.startswith("DataSchemaRecertificationRequired"), job2.error
    assert len(registry.passports(owner_user_id=_SCHEMA_OWNER)) == 1


def test_training_gate_baseline_ignores_fingerprintless_passport(tmp_path):
    """对抗·防 fail-open：在 producer 基线之后塞一份【无 schema 指纹】的 passport（如手动 REST 登记）
    不能把基线抹掉——下一 run schema 变仍以最近【带指纹】的 passport 为基线、照常 fail-closed。"""
    svc, registry = _schema_service(tmp_path)
    job1 = svc.train_now(
        _schema_request(["f1", "f2"]),
        _schema_panel(["f1", "f2"]),
        owner_user_id=_SCHEMA_OWNER,
    )
    assert job1.status == "succeeded", job1.error
    assert registry.passports(owner_user_id=_SCHEMA_OWNER)[0].dataset_schema_fingerprint

    # 同模型卡、但无 dataset_schema_fingerprint 的 passport 成为「最新」一份
    registry.record_passport(
        _passport(
            model_version_ref="model_version:ridge:manual",
            model_type_card_ref=_SCHEMA_MODEL_CARD_REF,
            training_run_ref="training_run:manual",
        ),
        owner_user_id=_SCHEMA_OWNER,
        recorded_by=_SCHEMA_OWNER,
    )
    assert registry.passports(owner_user_id=_SCHEMA_OWNER)[-1].dataset_schema_fingerprint == ""

    # run 2 加列 f3 → 基线仍是 P1（带指纹），无 recert → 仍阻断
    job2 = svc.train_now(
        _schema_request(["f1", "f2", "f3"]),
        _schema_panel(["f1", "f2", "f3"]),
        owner_user_id=_SCHEMA_OWNER,
    )
    assert job2.status == "failed"
    assert job2.error.startswith("DataSchemaRecertificationRequired"), job2.error
