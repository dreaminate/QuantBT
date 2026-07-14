from __future__ import annotations

import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest

import app.training.service as training_service_module
from app.approval.gate import ApprovalGateService
from app.approval.schema import ApprovalGate, GateStateError
from app.approval.store import ApprovalGateStore
from app.experiments.store import ExperimentStore, ModelRegistry, RunStore
from app.research_os.goal_semantics import (
    GoalSectionSemanticProofRecord,
    goal_section_semantic_proof_identity,
)
from app.research_os.model_governance import (
    ModelMonitoringProfile,
    ModelRecertificationRecord,
    ModelRiskTier,
    PersistentModelGovernanceRegistry,
    RecertificationTrigger,
)
from app.research_os.model_governance_closure import (
    MODEL_GOVERNANCE_SOURCE_ENTRYPOINT_REF,
    ModelGovernanceClosureError,
    ModelGovernanceClosureSectionAdapter,
    PersistentModelGovernanceClosureRegistry,
    model_governance_closure_semantic_material,
)
from app.research_os.model_recertification_evidence import (
    DependencyKind,
    ModelChallengerResult,
    ModelMonitoringObservation,
    ModelMonitoringRule,
    MonitoringSignalKind,
    ThresholdComparison,
)
from app.training import TrainingRequest, TrainingService
from app.training.schema_drift import compute_dataset_schema, schema_change_event_ref
from app.training.store import TrainingJob


OWNER = "owner-alpha"
REVIEWER = "reviewer-beta"
MODEL = "ridge"


def _panel(features: list[str] | None = None) -> pd.DataFrame:
    names = list(features or ["f1", "f2"])
    values: dict[str, object] = {
        "ts": pd.date_range("2025-01-01", periods=8, freq="D", tz="UTC"),
        "label": [float(index) / 10 for index in range(8)],
    }
    for offset, name in enumerate(names):
        values[name] = [float(index + offset) for index in range(8)]
    return pd.DataFrame(values)


def _request(features: list[str] | None = None) -> TrainingRequest:
    return TrainingRequest(
        name="governed-model",
        model=MODEL,
        task="regression",
        feature_cols=list(features or ["f1", "f2"]),
        label_col="label",
        n_splits=2,
        dataset_id="dataset:governed-model:v1",
    )


def _build_current_chain(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    repair_training_hash: bool = True,
    high_risk_with_unbacked_challenger: bool = False,
    high_risk_with_backed_challenger: bool = False,
    with_schema_recertification: bool = False,
) -> SimpleNamespace:
    governance = PersistentModelGovernanceRegistry(tmp_path / "audit" / "model_governance.jsonl")
    approval_store = ApprovalGateStore(tmp_path / "approval")
    gate_service = ApprovalGateService(approval_store)
    experiment_store = ExperimentStore(tmp_path / "experiments")
    run_store = RunStore(tmp_path / "experiments")
    model_registry = ModelRegistry(
        tmp_path / "experiments",
        gate_service=gate_service,
        model_governance_registry=governance,
    )

    def record_training_lineage(job):
        owner = job.owner_user_id
        return {
            "qro_id": f"qro:{owner}:training:{job.job_id}",
            "research_graph_command_id": f"rgcmd:{owner}:training:{job.job_id}",
            "compiler_ir_ref": f"compiler_ir:{owner}:training:{job.job_id}",
            "compiler_pass_ref": f"compiler_pass:{owner}:training:{job.job_id}",
            "entrypoint_coverage_ref": f"goal_entrypoint_coverage:{owner}:training:{job.job_id}",
        }

    service = TrainingService(
        tmp_path / "training_runs",
        experiment_store=experiment_store,
        run_store=run_store,
        model_registry=model_registry,
        model_governance_registry=governance,
        result_recorder=record_training_lineage,
    )
    if not repair_training_hash:
        monkeypatch.setattr(
            training_service_module,
            "model_training_code_hash",
            lambda _plan: "sha256:" + "0" * 64,
        )
    if high_risk_with_unbacked_challenger or high_risk_with_backed_challenger:
        original_record_passport = governance.record_passport

        def record_governed_passport(passport, **kwargs):
            candidate = passport
            if high_risk_with_unbacked_challenger or high_risk_with_backed_challenger:
                candidate = replace(
                    candidate,
                    model_risk_tier=ModelRiskTier.HIGH,
                    challenger_result=(
                        "challenger_result:caller-minted"
                        if high_risk_with_unbacked_challenger
                        else "challenger_result:pending-producer"
                    ),
                    passport_id="",
                )
            return original_record_passport(candidate, **kwargs)

        monkeypatch.setattr(governance, "record_passport", record_governed_passport)

    def fake_result(_request, _code, _panel, job_dir: Path):
        artifact = job_dir / "model.pkl"
        artifact.write_bytes(b"governed-model-artifact-v1")
        return {
            "oos_metrics": {"r2": 0.25},
            "fold_metrics": [],
            "artifact_path": str(artifact),
        }

    def fake_inspection(_artifact_path: Path, *, expected_hash: str):
        return {
            "inspection_ref": "artifact_inspection:governed-model:v1",
            "inspection_mode": "metadata_only_no_deserialize",
            "inspector_ref": "training_artifact_inspector:v1",
            "checks": ["content_hash", "serialized_deserialize_skipped"],
            "limitations": ["not_deserialized"],
            "artifact_hash": expected_hash,
        }

    monkeypatch.setattr(service, "_resolve_result", fake_result)
    monkeypatch.setattr(training_service_module, "inspect_artifact_in_subprocess", fake_inspection)
    recertification = None
    if with_schema_recertification:
        first_job = service.train_now(
            _request(["f1"]),
            _panel(["f1"]),
            owner_user_id=OWNER,
        )
        assert first_job.status == "succeeded", first_job.error
        first_passport = governance.passport(first_job.model_passport_ref, owner_user_id=OWNER)
        next_fingerprint = compute_dataset_schema(
            _panel(["f1", "f2"]),
            ["f1", "f2"],
            "label",
        ).fingerprint
        recertification = governance.record_recertification_record(
            ModelRecertificationRecord(
                model_version_ref=first_passport.model_version_ref,
                model_passport_ref=first_passport.passport_id,
                trigger=RecertificationTrigger.DATA_SCHEMA_CHANGE,
                change_event_ref=schema_change_event_ref(
                    first_passport.model_type_card_ref,
                    first_passport.dataset_schema_fingerprint,
                    next_fingerprint,
                ),
                evidence_refs=("validation_dossier:schema-review:v2",),
                decision="accepted",
                recorded_by=REVIEWER,
                owner_user_id=OWNER,
            ),
            owner_user_id=OWNER,
            recorded_by=REVIEWER,
        )
    job = service.train_now(_request(), _panel(), owner_user_id=OWNER)
    assert job.status == "succeeded", job.error
    passport = governance.passport(job.model_passport_ref, owner_user_id=OWNER)
    material_recertification = None
    if with_schema_recertification:
        events = service._model_recertification_events.detect_and_record_current(
            governance=governance,
            owner_user_id=OWNER,
            current_passport_ref=passport.passport_id,
            training_jobs=service._jobs,
        )
        material_event = next(
            event
            for event in events
            if event.trigger == RecertificationTrigger.MATERIAL_MODEL_CHANGE
        )
        material_recertification = governance.record_recertification_record(
            ModelRecertificationRecord(
                model_version_ref=passport.model_version_ref,
                model_passport_ref=passport.passport_id,
                trigger=RecertificationTrigger.MATERIAL_MODEL_CHANGE,
                change_event_ref=material_event.event_ref,
                evidence_refs=("validation_dossier:material-review:v2",),
                decision="accepted",
                recorded_by=REVIEWER,
                owner_user_id=OWNER,
            ),
            owner_user_id=OWNER,
            recorded_by=REVIEWER,
        )

    profile = governance.record_monitoring_profile(
        ModelMonitoringProfile(
            model_version_ref=passport.model_version_ref,
            model_passport_ref=passport.passport_id,
            metric_refs=("metric:rolling_error", "metric:feature_drift"),
            schedule_ref="schedule:each_batch",
            alert_policy_ref="alert:model-governance",
            drift_signal_refs=("drift:features",),
            performance_threshold_refs=("threshold:r2",),
            recertification_trigger_refs=tuple(RecertificationTrigger),
            owner_user_id=OWNER,
            recorded_by=OWNER,
        ),
        owner_user_id=OWNER,
        recorded_by=OWNER,
    )
    version = next(
        item
        for item in model_registry.list_versions(MODEL, owner_user_id=OWNER)
        if item.version == job.model_version
    )
    challenger_result = None
    if high_risk_with_backed_challenger:
        baseline_run = service._runs.create_run(
            job.experiment_id,
            inputs=job.request,
            tags={"kind": "training", "family": job.family},
        )
        service._runs.update_run(
            baseline_run.run_id,
            status="succeeded",
            metrics={"r2": 0.1},
            finished=True,
        )
        service._jobs.create(
            TrainingJob(
                job_id="challenger-baseline-job",
                name="challenger baseline",
                model=MODEL,
                family=job.family,
                task=job.task,
                owner_user_id=OWNER,
                status="succeeded",
                request=job.request,
                metrics={"r2": 0.1},
                experiment_id=job.experiment_id,
                run_id=baseline_run.run_id,
            )
        )
        evidence = model_registry.model_recertification_evidence_registry
        challenger_result = evidence.record_challenger_result(
            ModelChallengerResult(
                owner_user_id=OWNER,
                model_type_card_ref=passport.model_type_card_ref,
                model_version_ref=passport.model_version_ref,
                model_passport_ref=passport.passport_id,
                baseline_run_ref=f"training_run:{baseline_run.run_id}",
                challenger_run_ref=passport.training_run_ref,
                metric_ref="r2",
                baseline_value=0.1,
                challenger_value=0.25,
                minimum_improvement=0.1,
                higher_is_better=True,
                producer_ref="challenger-comparison:v1",
                reviewer_user_id=REVIEWER,
                recorded_by="challenger-producer",
            )
        )
        head = governance.current_head_hash(
            passport.passport_id,
            owner_user_id=OWNER,
            event_type="model_passport_recorded",
        )
        passport = PersistentModelGovernanceRegistry.record_passport(
            governance,
            replace(
                passport,
                challenger_result=challenger_result.result_ref,
                passport_id="",
            ),
            owner_user_id=OWNER,
            recorded_by=passport.recorded_by,
            expected_head_hash=head,
        )
    if high_risk_with_unbacked_challenger:
        # Deliberately seed an old-style gate so the closure's independent
        # current-policy check is exercised.  Production promotion never takes
        # this branch; ModelRegistry now rejects it before opening a gate.
        passport_metadata = {
            "model_passport_ref": passport.passport_id,
            "validation_dossier_ref": passport.validation_dossier_ref,
        }
    else:
        passport_metadata = model_registry._validated_model_passport_metadata(
            version,
            stage="staging",
            model_passport_ref=passport.passport_id,
            owner_user_id=OWNER,
        )
    gate = ApprovalGate(
        gate_id="gate-model-governance-v1",
        model_id=version.model_asset_ref,
        version=version.version,
        from_stage="dev",
        to_stage="staging",
        channel="confirmatory",
        action_kind="promote_staging",
        created_by=OWNER,
        verification_record_id="verification:model-governance:v1",
        evidence={
            "owner_user_id": OWNER,
            "logical_model_id": MODEL,
            "model_asset_ref": version.model_asset_ref,
            **passport_metadata,
        },
        decision="pending",
    )
    approval_store.append(gate)
    grant = model_registry.grant_promotion_reviewer(
        gate.gate_id,
        model_id=MODEL,
        owner_user_id=OWNER,
        reviewer_user_id=REVIEWER,
        permissions=("view", "approve", "reject"),
        expires_at_utc=(datetime.now(UTC) + timedelta(days=2)).isoformat(),
        issued_by=OWNER,
    )
    gate.approver = REVIEWER
    gate.decision = "approved"
    gate.decision_reason = "Independent review accepted the bound validation dossier."
    gate.decided_at_utc = datetime.now(UTC).isoformat()
    gate.side_effect_executed = True
    gate.side_effect_ref = f"stage:{OWNER}:{MODEL}:v{version.version}:staging"
    gate.evidence = {
        **(gate.evidence or {}),
        "reviewer_grant_id": grant.grant_id,
        "reviewer_grant_record_hash": grant.record_hash,
        "reviewer_user_id": REVIEWER,
    }
    approval_store.append(gate)
    version = model_registry._apply_stage_unchecked(
        MODEL,
        version.version,
        "staging",
        owner_user_id=OWNER,
    )
    closure = PersistentModelGovernanceClosureRegistry(
        tmp_path / "audit" / "model_governance_closure.jsonl",
        governance_registry=governance,
        training_service=service,
        model_registry=model_registry,
    )
    return SimpleNamespace(
        governance=governance,
        approval_store=approval_store,
        gate_service=gate_service,
        model_registry=model_registry,
        service=service,
        job=job,
        passport=passport,
        profile=profile,
        version=version,
        gate=gate,
        grant=grant,
        recertification=recertification,
        material_recertification=material_recertification,
        challenger_result=challenger_result,
        target_version=version.version,
        closure=closure,
        closure_path=closure.path,
    )


def test_model_governance_closure_records_reloads_and_validates_current(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    chain = _build_current_chain(tmp_path, monkeypatch)

    receipt = chain.closure.record_current(
        owner_user_id=OWNER,
        model_id=MODEL,
        version=1,
    )
    replay = PersistentModelGovernanceClosureRegistry(
        chain.closure_path,
        governance_registry=chain.governance,
        training_service=chain.service,
        model_registry=chain.model_registry,
    )

    assert replay.receipt(receipt.receipt_ref, owner_user_id=OWNER) == receipt
    assert replay.validate_current(receipt.receipt_ref, owner_user_id=OWNER).accepted
    assert replay.record_current(owner_user_id=OWNER, model_id=MODEL, version=1) == receipt
    assert len(chain.closure_path.read_text(encoding="utf-8").splitlines()) == 1
    probes = {item.probe_name: item for item in receipt.snapshot.policy_probes}
    assert not probes["missing_validation_dossier"].accepted
    assert "missing_validation_dossier_ref" in probes["missing_validation_dossier"].violation_codes
    assert "external_serialized_artifact_blocked" in probes["external_pickle_direct_load"].violation_codes
    assert "missing_challenger_result" in probes["high_risk_without_challenger"].violation_codes
    assert "material_model_change_without_recertification" in probes[
        "material_change_without_recertification"
    ].violation_codes
    assert "torch_weights_only_required" in probes["torch_without_weights_only"].violation_codes


def test_model_governance_closure_rejects_training_spec_hash_masquerading_as_code_hash(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    chain = _build_current_chain(tmp_path, monkeypatch, repair_training_hash=False)

    with pytest.raises(ModelGovernanceClosureError, match="executable training source and plan"):
        chain.closure.record_current(owner_user_id=OWNER, model_id=MODEL, version=1)

    assert not chain.closure_path.exists()


def test_model_governance_closure_resolves_training_service_schema_recertification(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    chain = _build_current_chain(
        tmp_path,
        monkeypatch,
        with_schema_recertification=True,
    )

    receipt = chain.closure.record_current(
        owner_user_id=OWNER,
        model_id=MODEL,
        version=chain.target_version,
    )

    assert chain.target_version == 2
    assert chain.recertification.recertification_record_id in {
        item.component_ref
        for item in receipt.snapshot.components
        if item.component_kind == "recertification_record"
    }
    assert chain.material_recertification.recertification_record_id in {
        item.component_ref
        for item in receipt.snapshot.components
        if item.component_kind == "recertification_record"
    }
    assert sum(
        item.component_kind == "recertification_requirement"
        for item in receipt.snapshot.components
    ) == 2
    assert any(
        item.component_kind == "recertification_producer_status"
        for item in receipt.snapshot.components
    )
    assert chain.closure.validate_current(receipt.receipt_ref, owner_user_id=OWNER).accepted


def test_model_governance_closure_rejects_cross_owner_recombination(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    chain = _build_current_chain(tmp_path, monkeypatch)

    with pytest.raises(ModelGovernanceClosureError, match="owner-scoped model version"):
        chain.closure.record_current(
            owner_user_id="owner-gamma",
            model_id=MODEL,
            version=1,
        )

    assert not chain.closure_path.exists()


def test_model_promotion_rejects_caller_minted_high_risk_challenger_before_gate(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with pytest.raises(GateStateError, match="durable challenger-result producer"):
        _build_current_chain(
            tmp_path,
            monkeypatch,
            high_risk_with_unbacked_challenger=True,
        )


def test_model_governance_closure_accepts_content_bound_high_risk_challenger(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    chain = _build_current_chain(
        tmp_path,
        monkeypatch,
        high_risk_with_backed_challenger=True,
    )

    receipt = chain.closure.record_current(
        owner_user_id=OWNER,
        model_id=MODEL,
        version=1,
    )
    assert chain.closure.validate_current(receipt.receipt_ref, owner_user_id=OWNER).accepted


def test_model_governance_closure_rejects_unresolved_external_dependency_ref(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    chain = _build_current_chain(tmp_path, monkeypatch)
    current_head = chain.governance.current_head_hash(
        chain.passport.passport_id,
        owner_user_id=OWNER,
        event_type="model_passport_recorded",
    )
    chain.governance.record_passport(
        replace(chain.passport, vendor_dependency_refs=("vendor:unresolved",)),
        owner_user_id=OWNER,
        recorded_by=chain.passport.recorded_by,
        expected_head_hash=current_head,
    )

    with pytest.raises(ModelGovernanceClosureError, match="durable dependency producer"):
        chain.closure.record_current(owner_user_id=OWNER, model_id=MODEL, version=1)

    assert not chain.closure_path.exists()


def test_model_governance_closure_accepts_content_bound_dependency(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    chain = _build_current_chain(tmp_path, monkeypatch)
    evidence = chain.model_registry.model_recertification_evidence_registry
    dependency = evidence.record_dependency_content(
        owner_user_id=OWNER,
        dependency_kind=DependencyKind.VENDOR,
        dependency_ref="package:numpy",
        content=b"numpy==2.1.0\n",
        resolver_ref="package-lock:requirements:v1",
        recorded_by="dependency-resolver",
    )
    head = chain.governance.current_head_hash(
        chain.passport.passport_id,
        owner_user_id=OWNER,
        event_type="model_passport_recorded",
    )
    chain.governance.record_passport(
        replace(
            chain.passport,
            vendor_dependency_refs=(dependency.fingerprint_ref,),
            passport_id="",
        ),
        owner_user_id=OWNER,
        recorded_by=chain.passport.recorded_by,
        expected_head_hash=head,
    )

    receipt = chain.closure.record_current(
        owner_user_id=OWNER,
        model_id=MODEL,
        version=1,
    )
    assert chain.closure.validate_current(receipt.receipt_ref, owner_user_id=OWNER).accepted


def test_model_governance_closure_detects_artifact_byte_drift(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    chain = _build_current_chain(tmp_path, monkeypatch)
    receipt = chain.closure.record_current(owner_user_id=OWNER, model_id=MODEL, version=1)
    artifact_path = Path(chain.version.artifact_path)

    artifact_path.write_bytes(b"mutated-artifact")

    decision = chain.closure.validate_current(receipt.receipt_ref, owner_user_id=OWNER)
    assert not decision.accepted
    assert decision.violations[0].code == "model_governance_closure_current_resolution_failed"


def test_model_governance_closure_detects_newer_monitoring_profile(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    chain = _build_current_chain(tmp_path, monkeypatch)
    receipt = chain.closure.record_current(owner_user_id=OWNER, model_id=MODEL, version=1)
    chain.governance.record_monitoring_profile(
        ModelMonitoringProfile(
            model_version_ref=chain.passport.model_version_ref,
            model_passport_ref=chain.passport.passport_id,
            metric_refs=("metric:rolling_error:v2",),
            schedule_ref="schedule:hourly",
            alert_policy_ref="alert:model-governance:v2",
            recertification_trigger_refs=tuple(RecertificationTrigger),
            owner_user_id=OWNER,
            recorded_by=OWNER,
        ),
        owner_user_id=OWNER,
        recorded_by=OWNER,
    )

    decision = chain.closure.validate_current(receipt.receipt_ref, owner_user_id=OWNER)
    assert not decision.accepted
    assert {item.code for item in decision.violations} == {
        "model_governance_closure_current_state_drifted"
    }


def test_model_governance_closure_detects_new_monitoring_breach(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    chain = _build_current_chain(tmp_path, monkeypatch)
    receipt = chain.closure.record_current(owner_user_id=OWNER, model_id=MODEL, version=1)
    evidence = chain.model_registry.model_recertification_evidence_registry
    rule = evidence.record_monitoring_rule(
        ModelMonitoringRule(
            owner_user_id=OWNER,
            model_type_card_ref=chain.passport.model_type_card_ref,
            model_version_ref=chain.passport.model_version_ref,
            model_passport_ref=chain.passport.passport_id,
            monitoring_profile_ref=chain.profile.monitoring_profile_id,
            signal_kind=MonitoringSignalKind.PERFORMANCE,
            signal_ref="threshold:r2",
            baseline_value=0.25,
            threshold_value=0.1,
            comparison=ThresholdComparison.BELOW,
            recorded_by="monitor-policy",
        )
    )
    evidence.record_monitoring_observation(
        ModelMonitoringObservation(
            owner_user_id=OWNER,
            rule_ref=rule.rule_ref,
            observed_value=0.05,
            observation_ref="monitor-batch:degraded-r2",
            producer_ref="model-monitor:r2:v1",
            recorded_by="model-monitor",
        )
    )

    decision = chain.closure.validate_current(receipt.receipt_ref, owner_user_id=OWNER)
    assert not decision.accepted
    assert {item.code for item in decision.violations} == {
        "model_governance_closure_current_resolution_failed"
    }


def test_model_governance_closure_binds_latest_training_job_append_head(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    chain = _build_current_chain(tmp_path, monkeypatch)
    receipt = chain.closure.record_current(owner_user_id=OWNER, model_id=MODEL, version=1)

    chain.service._jobs.save(chain.service.get_job(chain.job.job_id))

    decision = chain.closure.validate_current(receipt.receipt_ref, owner_user_id=OWNER)
    assert not decision.accepted
    assert {item.code for item in decision.violations} == {
        "model_governance_closure_current_state_drifted"
    }


def test_model_governance_closure_strictly_rejects_corrupt_backing_jsonl(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    chain = _build_current_chain(tmp_path, monkeypatch)
    models_path = chain.model_registry._store._path
    with models_path.open("a", encoding="utf-8") as handle:
        handle.write('{"schema_version":2')

    with pytest.raises(ModelGovernanceClosureError, match="model registry durable store has invalid JSON"):
        chain.closure.record_current(owner_user_id=OWNER, model_id=MODEL, version=1)

    assert not chain.closure_path.exists()


def test_model_governance_closure_rolls_back_post_commit_toctou(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    chain = _build_current_chain(tmp_path, monkeypatch)
    original_append = chain.closure._atomic_append
    artifact_path = Path(chain.version.artifact_path)

    def append_then_drift(receipt):
        original_append(receipt)
        artifact_path.write_bytes(b"drift-during-commit")

    monkeypatch.setattr(chain.closure, "_atomic_append", append_then_drift)

    with pytest.raises(ModelGovernanceClosureError, match="model artifact bytes"):
        chain.closure.record_current(owner_user_id=OWNER, model_id=MODEL, version=1)

    assert not chain.closure_path.exists()


def test_model_governance_closure_restores_prior_ledger_after_post_commit_drift(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    chain = _build_current_chain(tmp_path, monkeypatch)
    first = chain.closure.record_current(owner_user_id=OWNER, model_id=MODEL, version=1)
    before = chain.closure_path.read_bytes()
    chain.model_registry.revoke_promotion_reviewer(
        chain.grant.grant_id,
        owner_user_id=OWNER,
        revoked_by=OWNER,
        expected_record_hash=chain.grant.record_hash,
    )
    original_append = chain.closure._atomic_append
    artifact_path = Path(chain.version.artifact_path)

    def append_then_drift(receipt):
        original_append(receipt)
        artifact_path.write_bytes(b"drift-after-existing-receipt")

    monkeypatch.setattr(chain.closure, "_atomic_append", append_then_drift)

    with pytest.raises(ModelGovernanceClosureError, match="model artifact bytes"):
        chain.closure.record_current(owner_user_id=OWNER, model_id=MODEL, version=1)

    assert chain.closure_path.read_bytes() == before
    assert chain.closure.receipt(first.receipt_ref, owner_user_id=OWNER) == first


def test_model_governance_closure_removes_first_receipt_when_directory_fsync_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.research_os.model_governance_closure as module

    chain = _build_current_chain(tmp_path, monkeypatch)
    real_fsync = module.os.fsync
    calls = 0

    def fail_first_directory_fsync(fd):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("injected model closure directory fsync failure")
        return real_fsync(fd)

    monkeypatch.setattr(module.os, "fsync", fail_first_directory_fsync)
    with pytest.raises(OSError, match="injected model closure directory fsync failure"):
        chain.closure.record_current(owner_user_id=OWNER, model_id=MODEL, version=1)
    assert not chain.closure_path.exists()


def test_model_governance_closure_restores_prior_bytes_when_directory_fsync_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.research_os.model_governance_closure as module

    chain = _build_current_chain(tmp_path, monkeypatch)
    receipt = chain.closure.record_current(owner_user_id=OWNER, model_id=MODEL, version=1)
    before = chain.closure_path.read_bytes()
    real_fsync = module.os.fsync
    calls = 0

    def fail_first_directory_fsync(fd):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("injected model closure directory fsync failure")
        return real_fsync(fd)

    monkeypatch.setattr(module.os, "fsync", fail_first_directory_fsync)
    with pytest.raises(OSError, match="injected model closure directory fsync failure"):
        chain.closure._atomic_append(receipt)
    assert chain.closure_path.read_bytes() == before


def test_model_governance_closure_normalizes_missing_terminal_newline(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    chain = _build_current_chain(tmp_path, monkeypatch)
    first = chain.closure.record_current(owner_user_id=OWNER, model_id=MODEL, version=1)
    chain.closure_path.write_bytes(chain.closure_path.read_bytes().rstrip(b"\n"))
    revoked = chain.model_registry.revoke_promotion_reviewer(
        chain.grant.grant_id,
        owner_user_id=OWNER,
        revoked_by=OWNER,
        expected_record_hash=chain.grant.record_hash,
    )
    assert revoked.status == "revoked"

    second = chain.closure.record_current(owner_user_id=OWNER, model_id=MODEL, version=1)

    assert second.receipt_ref != first.receipt_ref
    rows = [json.loads(line) for line in chain.closure_path.read_text(encoding="utf-8").splitlines()]
    assert len(rows) == 2
    assert rows[0]["revision"] == 1
    assert rows[1]["revision"] == 2


class _EntrypointRegistry:
    def __init__(self, coverage) -> None:
        self._coverage = coverage

    def coverage(self, coverage_ref: str, *, owner: str):
        if coverage_ref != self._coverage.coverage_ref or owner != self._coverage.recorded_by:
            raise KeyError(coverage_ref)
        return self._coverage

    @staticmethod
    def validate_real_backing(_coverage):
        return SimpleNamespace(accepted=True)


def _semantic_proof(receipt, coverage_ref: str) -> GoalSectionSemanticProofRecord:
    material = model_governance_closure_semantic_material(receipt)
    fields = {
        "section": "§15",
        "subject_ref": material.subject_ref,
        "producer_refs": material.producer_refs,
        "store_refs": material.store_refs,
        "consumer_refs": material.consumer_refs,
        "gate_verdict_refs": material.gate_verdict_refs,
        "test_refs": material.test_refs,
        "entrypoint_coverage_refs": (coverage_ref,),
        "recorded_by": OWNER,
        "claims_section_complete": True,
        "unverified_residuals": (),
    }
    return GoalSectionSemanticProofRecord(
        proof_ref=goal_section_semantic_proof_identity(**fields),
        **fields,
    )


def test_model_governance_section_adapter_requires_exact_current_material(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    chain = _build_current_chain(tmp_path, monkeypatch)
    receipt = chain.closure.record_current(owner_user_id=OWNER, model_id=MODEL, version=1)
    coverage = SimpleNamespace(
        coverage_ref=receipt.snapshot.source_entrypoint_coverage_ref,
        recorded_by=OWNER,
        entry_source="api",
        entrypoint_ref=MODEL_GOVERNANCE_SOURCE_ENTRYPOINT_REF,
        goal_sections=("§0", "§1", "§7", "§8", "§15"),
        qro_refs=(receipt.snapshot.source_qro_ref,),
        research_graph_command_refs=(receipt.snapshot.source_graph_ref,),
        compiler_ir_refs=(receipt.snapshot.source_compiler_ir_ref,),
        compiler_pass_refs=(receipt.snapshot.source_compiler_pass_ref,),
        validation_refs=("goal_validation_receipt:model-governance:v1",),
        silent_mock_fallback_used=False,
        raw_payload_persisted=False,
    )
    adapter = ModelGovernanceClosureSectionAdapter(
        _EntrypointRegistry(coverage),
        chain.closure,
    )
    proof = _semantic_proof(receipt, coverage.coverage_ref)

    assert adapter.validate(proof, owner=OWNER).accepted
    tampered = replace(proof, producer_refs=proof.producer_refs[:-1])
    decision = adapter.validate(tampered, owner=OWNER)
    assert not decision.accepted
    assert any(item.field == "producer_refs" for item in decision.violations)


def test_model_governance_closure_endpoint_appends_only_one_receipt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from fastapi.testclient import TestClient

    from app import main

    chain = _build_current_chain(
        tmp_path,
        monkeypatch,
        with_schema_recertification=True,
    )

    class _ForbiddenDerivedStore:
        def __getattr__(self, name):
            raise AssertionError(f"§15 closure endpoint touched derived store: {name}")

    monkeypatch.setattr(main, "MODEL_GOVERNANCE_CLOSURE_REGISTRY", chain.closure)
    monkeypatch.setattr(main, "RESEARCH_GRAPH_STORE", _ForbiddenDerivedStore())
    monkeypatch.setattr(main, "COMPILER_IR_STORE", _ForbiddenDerivedStore())
    monkeypatch.setattr(main, "GOAL_VALIDATION_RECEIPT_REGISTRY", _ForbiddenDerivedStore())
    monkeypatch.setattr(main, "GOAL_ENTRYPOINT_COVERAGE_REGISTRY", _ForbiddenDerivedStore())
    main.app.dependency_overrides[main.require_user_dependency] = lambda: SimpleNamespace(
        username=OWNER,
        user_id=OWNER,
    )
    try:
        response = TestClient(main.app).post(
            "/api/research-os/goal/model_governance_closure/current",
            json={"model_id": MODEL, "version": chain.target_version},
        )
    finally:
        main.app.dependency_overrides.pop(main.require_user_dependency, None)

    assert response.status_code == 200, response.text
    body = response.json()
    assert set(body) == {
        "receipt_ref",
        "model_id",
        "model_asset_ref",
        "version",
        "stage",
        "passport_ref",
        "source_entrypoint_coverage_ref",
        "recorded_by",
    }
    assert body["source_entrypoint_coverage_ref"] == chain.job.entrypoint_coverage_ref
    assert len(chain.closure_path.read_text(encoding="utf-8").splitlines()) == 1
    receipt = chain.closure.receipt(body["receipt_ref"], owner_user_id=OWNER)
    assert any(
        item.component_kind == "recertification_requirement"
        for item in receipt.snapshot.components
    )
    assert any(
        item.component_kind == "recertification_producer_status"
        for item in receipt.snapshot.components
    )


def test_model_governance_section_adapter_has_no_platform_or_goal_zero_dependency() -> None:
    import app.research_os.model_governance_closure as module

    source = Path(module.__file__).read_text(encoding="utf-8")
    assert "platform_closure" not in source
    assert "§0" not in source
