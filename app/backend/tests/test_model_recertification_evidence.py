from __future__ import annotations

import json
import os
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest

import app.research_os.model_recertification_evidence as evidence_module
from app.approval import ApprovalGateService, ApprovalGateStore
from app.approval.schema import GateStateError
from app.experiments.store import ModelRegistry, RunStore
from app.lineage.ledger import Ledger
from app.research_os.model_governance import (
    ModelArtifactManifestEntry,
    ModelArtifactSource,
    ModelGovernancePassport,
    ModelMonitoringProfile,
    ModelRecertificationRecord,
    ModelRiskTier,
    PersistentModelGovernanceRegistry,
    RecertificationTrigger,
    SafeLoadingPolicy,
)
from app.research_os.model_recertification_evidence import (
    DependencyKind,
    ModelChallengerResult,
    ModelDependencyFingerprint,
    ModelEvidenceError,
    ModelMonitoringObservation,
    ModelMonitoringRule,
    MonitoringSignalKind,
    PersistentModelRecertificationEvidenceRegistry,
    ThresholdComparison,
)
from app.research_os.model_recertification_events import (
    ModelRecertificationEvidenceError,
    resolve_current_recertification_requirements,
)
from app.training.service import TrainingRequest
from app.training.store import TrainingJob, TrainingJobStore


OWNER = "owner-evidence"
MODEL = "ridge"
MODEL_CARD = f"model_type_card:{MODEL}"
ACTOR = "training-service"


def _passport(
    version: int,
    job_id: str,
    *,
    vendor_refs: tuple[str, ...] = ("none",),
) -> ModelGovernancePassport:
    run_ref = f"training_run:run-{version}"
    return ModelGovernancePassport(
        model_version_ref=f"model_version:{MODEL}:v{version}",
        model_type_card_ref=MODEL_CARD,
        training_plan_ref=f"training_plan:{job_id}",
        training_run_ref=run_ref,
        model_risk_tier=ModelRiskTier.MEDIUM,
        materiality="governed research model",
        intended_use=("research",),
        prohibited_use=("direct live trading",),
        dataset_refs=("dataset:stable",),
        feature_refs=("feature:x",),
        label_refs=("label:y",),
        training_code_hash="sha256:stable-code",
        artifact_manifest=(
            ModelArtifactManifestEntry(
                artifact_ref=f"model_artifact:{job_id}",
                uri=f"project://{job_id}/model.json",
                source=ModelArtifactSource.PROJECT_PRODUCED,
                content_hash="sha256:stable-artifact",
                producer_run_ref=run_ref,
                sandbox_inspection_ref=f"inspection:{job_id}",
            ),
        ),
        safe_loading_policy=SafeLoadingPolicy(
            sandboxed_load_inspect=True,
            direct_load_allowed=False,
            policy_ref="safe-loader:v1",
        ),
        vendor_dependency_refs=vendor_refs,
        foundation_model_dependency_refs=("none",),
        monitoring_requirements=("drift and performance",),
        recertification_triggers=tuple(RecertificationTrigger),
        validation_dossier_ref=f"validation_dossier:{job_id}",
        challenger_result="not required for medium risk",
        dataset_schema_fingerprint="schema:stable",
        owner_user_id=OWNER,
        recorded_by=ACTOR,
    )


def _job(passport: ModelGovernancePassport, version: int, job_id: str) -> TrainingJob:
    request = TrainingRequest(
        name=f"train-{version}",
        model=MODEL,
        task="regression",
        feature_cols=["feature:x"],
        label_col="label:y",
        asset_class="equity_cn",
    )
    return TrainingJob(
        job_id=job_id,
        name=request.name,
        model=MODEL,
        family="ml",
        task="regression",
        owner_user_id=OWNER,
        status="succeeded",
        request=request.to_dict(),
        run_id=f"run-{version}",
        model_version=version,
        model_passport_ref=passport.passport_id,
        validation_dossier_ref=passport.validation_dossier_ref,
    )


def _stores(tmp_path: Path):
    governance = PersistentModelGovernanceRegistry(tmp_path / "audit" / "governance.jsonl")
    models = ModelRegistry(
        tmp_path / "experiments",
        model_governance_registry=governance,
    )
    jobs = TrainingJobStore(tmp_path / "training_runs")
    events = models.model_recertification_event_registry
    models.bind_model_recertification_events(events, jobs)
    evidence = models.model_recertification_evidence_registry
    assert isinstance(evidence, PersistentModelRecertificationEvidenceRegistry)
    return governance, models, jobs, events, evidence


def test_monitoring_observation_breaches_emit_typed_events_and_later_rejection_reopens(
    tmp_path: Path,
) -> None:
    governance, _models, jobs, events, evidence = _stores(tmp_path)
    passport = _passport(1, "job-1")
    jobs.create(_job(passport, 1, "job-1"))
    governance.record_passport(passport, owner_user_id=OWNER, recorded_by=ACTOR)
    profile = governance.record_monitoring_profile(
        ModelMonitoringProfile(
            model_version_ref=passport.model_version_ref,
            model_passport_ref=passport.passport_id,
            metric_refs=("metric:r2", "metric:psi"),
            schedule_ref="schedule:batch",
            alert_policy_ref="alert:model",
            drift_signal_refs=("signal:psi",),
            performance_threshold_refs=("threshold:r2",),
            recertification_trigger_refs=tuple(RecertificationTrigger),
            owner_user_id=OWNER,
            recorded_by=ACTOR,
        ),
        owner_user_id=OWNER,
        recorded_by=ACTOR,
    )
    feature_rule = evidence.record_monitoring_rule(
        ModelMonitoringRule(
            owner_user_id=OWNER,
            model_type_card_ref=MODEL_CARD,
            model_version_ref=passport.model_version_ref,
            model_passport_ref=passport.passport_id,
            monitoring_profile_ref=profile.monitoring_profile_id,
            signal_kind=MonitoringSignalKind.FEATURE_DISTRIBUTION,
            signal_ref="signal:psi",
            baseline_value=0.0,
            threshold_value=0.2,
            comparison=ThresholdComparison.ABOVE,
            recorded_by="monitor-policy",
        )
    )
    performance_rule = evidence.record_monitoring_rule(
        ModelMonitoringRule(
            owner_user_id=OWNER,
            model_type_card_ref=MODEL_CARD,
            model_version_ref=passport.model_version_ref,
            model_passport_ref=passport.passport_id,
            monitoring_profile_ref=profile.monitoring_profile_id,
            signal_kind=MonitoringSignalKind.PERFORMANCE,
            signal_ref="threshold:r2",
            baseline_value=0.4,
            threshold_value=0.1,
            comparison=ThresholdComparison.BELOW,
            recorded_by="monitor-policy",
        )
    )
    evidence.record_monitoring_observation(
        ModelMonitoringObservation(
            owner_user_id=OWNER,
            rule_ref=feature_rule.rule_ref,
            observed_value=0.25,
            observation_ref="monitor-batch:1:psi",
            producer_ref="model-monitor:psi:v1",
            recorded_by="model-monitor",
        )
    )
    with pytest.raises(ModelEvidenceError, match="observation_ref is duplicated"):
        evidence.record_monitoring_observation(
            ModelMonitoringObservation(
                owner_user_id=OWNER,
                rule_ref=feature_rule.rule_ref,
                observed_value=0.3,
                observation_ref="monitor-batch:1:psi",
                producer_ref="model-monitor:psi:v1",
                recorded_by="model-monitor",
            )
        )
    evidence.record_monitoring_observation(
        ModelMonitoringObservation(
            owner_user_id=OWNER,
            rule_ref=performance_rule.rule_ref,
            observed_value=0.05,
            observation_ref="monitor-batch:1:r2",
            producer_ref="model-monitor:r2:v1",
            recorded_by="model-monitor",
        )
    )

    detected = events.detect_and_record_current(
        governance=governance,
        owner_user_id=OWNER,
        current_passport_ref=passport.passport_id,
        training_jobs=jobs,
    )
    assert {item.trigger for item in detected} == {
        RecertificationTrigger.FEATURE_DISTRIBUTION_DRIFT,
        RecertificationTrigger.PERFORMANCE_DEGRADATION,
    }
    assert all(item.before_passport_ref == item.after_passport_ref for item in detected)
    statuses = {item.trigger: item for item in events.producer_statuses()}
    assert all(item.available for item in statuses.values())

    accepted = []
    for event in detected:
        accepted.append(
            governance.record_recertification_record(
                ModelRecertificationRecord(
                    model_version_ref=passport.model_version_ref,
                    model_passport_ref=passport.passport_id,
                    trigger=event.trigger,
                    change_event_ref=event.event_ref,
                    evidence_refs=("review:model-monitoring",),
                    decision="accepted",
                    recorded_by="independent-reviewer",
                    owner_user_id=OWNER,
                ),
                owner_user_id=OWNER,
                recorded_by="independent-reviewer",
            )
        )
    resolution = resolve_current_recertification_requirements(
        governance=governance,
        event_registry=events,
        training_jobs=jobs,
        owner_user_id=OWNER,
        current_passport_ref=passport.passport_id,
    )
    assert {item.recertification_record_id for item in resolution.recertification_records} == {
        item.recertification_record_id for item in accepted
    }
    reopened = detected[0]
    governance.record_recertification_record(
        ModelRecertificationRecord(
            model_version_ref=passport.model_version_ref,
            model_passport_ref=passport.passport_id,
            trigger=reopened.trigger,
            change_event_ref=reopened.event_ref,
            evidence_refs=("review:new-negative-evidence",),
            decision="rejected",
            recorded_by="independent-reviewer",
            owner_user_id=OWNER,
        ),
        owner_user_id=OWNER,
        recorded_by="independent-reviewer",
    )
    with pytest.raises(ModelRecertificationEvidenceError, match="does not clear"):
        resolve_current_recertification_requirements(
            governance=governance,
            event_registry=events,
            training_jobs=jobs,
            owner_user_id=OWNER,
            current_passport_ref=passport.passport_id,
        )


def test_dependency_event_uses_resolved_content_fingerprints_not_declaration_text(
    tmp_path: Path,
) -> None:
    governance, _models, jobs, events, evidence = _stores(tmp_path)
    first_dep = evidence.record_dependency_content(
        owner_user_id=OWNER,
        dependency_kind=DependencyKind.VENDOR,
        dependency_ref="package:pandas",
        content=b"pandas==2.2.0\n",
        resolver_ref="package-lock:requirements:v1",
        recorded_by="dependency-resolver",
    )
    second_dep = evidence.record_dependency_content(
        owner_user_id=OWNER,
        dependency_kind=DependencyKind.VENDOR,
        dependency_ref="package:pandas",
        content=b"pandas==2.3.0\n",
        resolver_ref="package-lock:requirements:v2",
        recorded_by="dependency-resolver",
    )
    first = _passport(1, "job-1", vendor_refs=(first_dep.fingerprint_ref,))
    second = _passport(2, "job-2", vendor_refs=(second_dep.fingerprint_ref,))
    jobs.create(_job(first, 1, "job-1"))
    governance.record_passport(first, owner_user_id=OWNER, recorded_by=ACTOR)
    jobs.create(_job(second, 2, "job-2"))
    governance.record_passport(second, owner_user_id=OWNER, recorded_by=ACTOR)

    detected = events.detect_and_record_current(
        governance=governance,
        owner_user_id=OWNER,
        current_passport_ref=second.passport_id,
        training_jobs=jobs,
    )
    dependency_events = [
        item for item in detected if item.trigger == RecertificationTrigger.DEPENDENCY_UPDATE
    ]
    assert len(dependency_events) == 1
    assert "content_fingerprint" in dependency_events[0].after_state.canonical_state_json
    with pytest.raises(KeyError):
        evidence.dependency_fingerprint(second_dep.fingerprint_ref, owner_user_id="other-owner")


def test_stage_only_governed_environment_transition_emits_event(tmp_path: Path) -> None:
    governance, models, jobs, events, _evidence = _stores(tmp_path)
    passport = _passport(1, "job-1")
    jobs.create(_job(passport, 1, "job-1"))
    governance.record_passport(passport, owner_user_id=OWNER, recorded_by=ACTOR)
    models.register_version(
        MODEL,
        model_passport_ref=passport.passport_id,
        validation_dossier_ref=passport.validation_dossier_ref,
        owner_user_id=OWNER,
    )
    models._apply_stage_unchecked(MODEL, 1, "staging", owner_user_id=OWNER)
    models._apply_stage_unchecked(MODEL, 1, "production", owner_user_id=OWNER)

    detected = events.detect_and_record_current(
        governance=governance,
        owner_user_id=OWNER,
        current_passport_ref=passport.passport_id,
        training_jobs=jobs,
    )
    assert len(detected) == 1
    event = detected[0]
    assert event.trigger == RecertificationTrigger.NEW_EXECUTION_ENVIRONMENT
    assert event.before_passport_ref == event.after_passport_ref == passport.passport_id
    assert '"governed_stage":"staging"' in event.before_state.canonical_state_json
    assert '"governed_stage":"production"' in event.after_state.canonical_state_json


def test_stage_proposal_is_invalid_after_source_stage_drifts(tmp_path: Path) -> None:
    governance, models, jobs, _events, _evidence = _stores(tmp_path)
    passport = _passport(1, "job-1")
    jobs.create(_job(passport, 1, "job-1"))
    governance.record_passport(passport, owner_user_id=OWNER, recorded_by=ACTOR)
    version = models.register_version(
        MODEL,
        model_passport_ref=passport.passport_id,
        validation_dossier_ref=passport.validation_dossier_ref,
        owner_user_id=OWNER,
    )
    metadata = models._validated_model_passport_metadata(
        version,
        stage="staging",
        model_passport_ref=passport.passport_id,
        owner_user_id=OWNER,
    )
    proposal = SimpleNamespace(
        model_id=version.model_asset_ref,
        version=1,
        from_stage="dev",
        to_stage="staging",
        evidence={
            "owner_user_id": OWNER,
            "logical_model_id": MODEL,
            "model_asset_ref": version.model_asset_ref,
            **metadata,
        },
    )
    models.apply_stage(MODEL, 1, "archived", owner_user_id=OWNER)
    with pytest.raises(GateStateError, match="stage no longer matches"):
        models._validate_promotion_gate_identity(
            proposal,
            MODEL,
            owner_user_id=OWNER,
        )


def test_challenger_result_derives_verdict_and_rejects_same_reviewer(tmp_path: Path) -> None:
    registry = PersistentModelRecertificationEvidenceRegistry(tmp_path / "evidence.jsonl")
    result = registry.record_challenger_result(
        ModelChallengerResult(
            owner_user_id=OWNER,
            model_type_card_ref=MODEL_CARD,
            model_version_ref=f"model_version:{MODEL}:v2",
            model_passport_ref="model-passport:high-risk",
            baseline_run_ref="training_run:baseline",
            challenger_run_ref="training_run:challenger",
            metric_ref="r2",
            baseline_value=0.1,
            challenger_value=0.25,
            minimum_improvement=0.1,
            higher_is_better=True,
            producer_ref="challenger-comparison:v1",
            reviewer_user_id="reviewer-b",
            recorded_by="producer-a",
        )
    )
    assert result.passed
    assert result.improvement == pytest.approx(0.15)
    assert PersistentModelRecertificationEvidenceRegistry(registry.path).challenger_result(
        result.result_ref,
        owner_user_id=OWNER,
    ) == result
    with pytest.raises(ModelEvidenceError, match="independent reviewer"):
        ModelChallengerResult(
            owner_user_id=OWNER,
            model_type_card_ref=MODEL_CARD,
            model_version_ref=f"model_version:{MODEL}:v2",
            model_passport_ref="model-passport:high-risk",
            baseline_run_ref="training_run:baseline",
            challenger_run_ref="training_run:challenger",
            metric_ref="r2",
            baseline_value=0.1,
            challenger_value=0.25,
            minimum_improvement=0.1,
            higher_is_better=True,
            producer_ref="challenger-comparison:v1",
            reviewer_user_id="same-actor",
            recorded_by="same-actor",
        )


def test_high_risk_public_promotion_requires_and_binds_durable_challenger(
    tmp_path: Path,
) -> None:
    governance = PersistentModelGovernanceRegistry(
        tmp_path / "audit" / "governance.jsonl"
    )
    approval_store = ApprovalGateStore(tmp_path / "approval")
    models = ModelRegistry(
        tmp_path / "experiments",
        gate_service=ApprovalGateService(
            approval_store,
            ledger=Ledger(tmp_path / "ledger"),
        ),
        model_governance_registry=governance,
    )
    jobs = TrainingJobStore(tmp_path / "training_runs")
    models.bind_model_recertification_events(
        models.model_recertification_event_registry,
        jobs,
    )
    runs = RunStore(tmp_path / "experiments")
    baseline_run = runs.create_run("experiment:challenger")
    candidate_run = runs.create_run("experiment:challenger")
    runs.update_run(
        baseline_run.run_id,
        status="succeeded",
        metrics={"r2": 0.10},
        finished=True,
    )
    runs.update_run(
        candidate_run.run_id,
        status="succeeded",
        metrics={"r2": 0.25},
        finished=True,
    )
    base = _passport(1, "job-high-risk")
    artifact = replace(
        base.artifact_manifest[0],
        producer_run_ref=f"training_run:{candidate_run.run_id}",
        artifact_id="",
    )
    passport = replace(
        base,
        training_run_ref=f"training_run:{candidate_run.run_id}",
        artifact_manifest=(artifact,),
        model_risk_tier=ModelRiskTier.HIGH,
        challenger_result="challenger_result:caller-minted",
        passport_id="",
    )
    request = TrainingRequest(
        name="high-risk-candidate",
        model=MODEL,
        task="regression",
        feature_cols=["feature:x"],
        label_col="label:y",
        asset_class="equity_cn",
    )
    jobs.create(
        TrainingJob(
            job_id="job-high-risk-baseline",
            name="high-risk baseline",
            model=MODEL,
            family="ml",
            task="regression",
            owner_user_id=OWNER,
            status="succeeded",
            request=request.to_dict(),
            metrics={"r2": 0.10},
            experiment_id="experiment:challenger",
            run_id=baseline_run.run_id,
        )
    )
    jobs.create(
        TrainingJob(
            job_id="job-high-risk",
            name=request.name,
            model=MODEL,
            family="ml",
            task="regression",
            owner_user_id=OWNER,
            status="succeeded",
            request=request.to_dict(),
            metrics={"r2": 0.25},
            experiment_id="experiment:challenger",
            run_id=candidate_run.run_id,
            model_version=1,
            model_passport_ref=passport.passport_id,
            validation_dossier_ref=passport.validation_dossier_ref,
        )
    )
    governance.record_passport(
        passport,
        owner_user_id=OWNER,
        recorded_by=ACTOR,
    )
    models.register_version(
        MODEL,
        artifact_path="high-risk.safetensors",
        source_run_id=candidate_run.run_id,
        metrics={"r2": 0.25},
        model_passport_ref=passport.passport_id,
        validation_dossier_ref=passport.validation_dossier_ref,
        owner_user_id=OWNER,
    )
    promotion_evidence = {
        "config_hash": "cfg-high-risk",
        "dataset_version": "dataset:high-risk:v1",
        "n_eff": 5,
        "n_trials_raw": 5,
        "dsr": 0.92,
        "pbo": 0.10,
        "bootstrap_ci": [0.4, 1.8],
        "bootstrap_estimate": 1.0,
        "champion_challenger": {"verdict": "challenger_wins"},
        "returns_sha256": "sha256:high-risk-returns",
    }

    def promote():
        return models.promote(
            MODEL,
            1,
            "staging",
            created_by=OWNER,
            verification_record_id="verification:high-risk:v1",
            evidence=promotion_evidence,
            strategy_goal_ref="strategy-goal:high-risk",
            model_passport_ref=passport.passport_id,
            owner_user_id=OWNER,
        )

    with pytest.raises(GateStateError, match="durable challenger-result producer"):
        promote()
    assert approval_store.list_pending() == []

    evidence = models.model_recertification_evidence_registry
    misbound = evidence.record_challenger_result(
        ModelChallengerResult(
            owner_user_id=OWNER,
            model_type_card_ref=passport.model_type_card_ref,
            model_version_ref=passport.model_version_ref,
            model_passport_ref=passport.passport_id,
            baseline_run_ref=f"training_run:{candidate_run.run_id}",
            challenger_run_ref=f"training_run:{baseline_run.run_id}",
            metric_ref="r2",
            baseline_value=0.25,
            challenger_value=0.10,
            minimum_improvement=0.10,
            higher_is_better=False,
            producer_ref="challenger-comparison:misbound",
            reviewer_user_id="reviewer-independent",
            recorded_by="challenger-producer",
        )
    )
    head = governance.current_head_hash(
        passport.passport_id,
        owner_user_id=OWNER,
        event_type="model_passport_recorded",
    )
    passport = governance.record_passport(
        replace(passport, challenger_result=misbound.result_ref, passport_id=""),
        owner_user_id=OWNER,
        recorded_by=ACTOR,
        expected_head_hash=head,
    )
    with pytest.raises(
        GateStateError,
        match="does not bind the promoted owner/model/passport",
    ):
        promote()
    assert approval_store.list_pending() == []

    result = evidence.record_challenger_result(
        ModelChallengerResult(
            owner_user_id=OWNER,
            model_type_card_ref=passport.model_type_card_ref,
            model_version_ref=passport.model_version_ref,
            model_passport_ref=passport.passport_id,
            baseline_run_ref=f"training_run:{baseline_run.run_id}",
            challenger_run_ref=f"training_run:{candidate_run.run_id}",
            metric_ref="r2",
            baseline_value=0.10,
            challenger_value=0.25,
            minimum_improvement=0.10,
            higher_is_better=True,
            producer_ref="challenger-comparison:v1",
            reviewer_user_id="reviewer-independent",
            recorded_by="challenger-producer",
        )
    )
    head = governance.current_head_hash(
        passport.passport_id,
        owner_user_id=OWNER,
        event_type="model_passport_recorded",
    )
    passport = governance.record_passport(
        replace(passport, challenger_result=result.result_ref, passport_id=""),
        owner_user_id=OWNER,
        recorded_by=ACTOR,
        expected_head_hash=head,
    )
    gate = promote()
    assert gate.decision == "pending"
    assert gate.evidence["model_challenger_result_ref"] == result.result_ref
    assert gate.evidence["model_challenger_result_record_hash"] == (
        evidence.current_record_hash(result.result_ref, owner_user_id=OWNER)
    )


def _dependency(index: int) -> ModelDependencyFingerprint:
    return ModelDependencyFingerprint(
        owner_user_id=OWNER,
        dependency_kind=DependencyKind.VENDOR,
        dependency_ref=f"package:dependency-{index}",
        content_fingerprint="sha256:" + f"{index:064x}",
        resolver_ref=f"package-lock:requirements:{index}",
        recorded_by="dependency-resolver",
    )


def test_evidence_ledger_is_restart_tamper_and_concurrency_safe(tmp_path: Path) -> None:
    path = tmp_path / "evidence.jsonl"

    def write(index: int) -> str:
        registry = PersistentModelRecertificationEvidenceRegistry(path)
        return registry.record_dependency_fingerprint(_dependency(index)).fingerprint_ref

    with ThreadPoolExecutor(max_workers=8) as pool:
        refs = list(pool.map(write, range(1, 17)))
    assert len(refs) == len(set(refs)) == 16
    replay = PersistentModelRecertificationEvidenceRegistry(path)
    assert all(
        replay.dependency_fingerprint(ref, owner_user_id=OWNER).fingerprint_ref == ref
        for ref in refs
    )

    rows = path.read_text(encoding="utf-8").splitlines()
    tampered = json.loads(rows[0])
    tampered["record"]["resolver_ref"] = "package-lock:tampered"
    rows[0] = json.dumps(tampered, sort_keys=True)
    path.write_text("\n".join(rows) + "\n", encoding="utf-8")
    with pytest.raises(ModelEvidenceError, match="invalid model evidence row"):
        PersistentModelRecertificationEvidenceRegistry(path)


def test_evidence_ledger_rolls_back_failed_fsync(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = tmp_path / "evidence.jsonl"
    registry = PersistentModelRecertificationEvidenceRegistry(path)
    real_fsync = os.fsync
    calls = 0

    def fail_first(fd: int) -> None:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise OSError("forced evidence fsync failure")
        real_fsync(fd)

    monkeypatch.setattr(evidence_module.os, "fsync", fail_first)
    with pytest.raises(OSError, match="forced evidence fsync failure"):
        registry.record_dependency_fingerprint(_dependency(1))
    assert not path.exists()
    monkeypatch.setattr(evidence_module.os, "fsync", real_fsync)
    assert registry.record_dependency_fingerprint(_dependency(1)).fingerprint_ref


def test_evidence_ledger_restores_prior_bytes_after_append_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "evidence.jsonl"
    registry = PersistentModelRecertificationEvidenceRegistry(path)
    first = registry.record_dependency_fingerprint(_dependency(1))
    original = path.read_bytes()
    real_fsync = os.fsync
    calls = 0

    def fail_first(fd: int) -> None:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise OSError("forced existing-ledger fsync failure")
        real_fsync(fd)

    monkeypatch.setattr(evidence_module.os, "fsync", fail_first)
    with pytest.raises(OSError, match="forced existing-ledger fsync failure"):
        registry.record_dependency_fingerprint(_dependency(2))
    assert path.read_bytes() == original
    monkeypatch.setattr(evidence_module.os, "fsync", real_fsync)
    replay = PersistentModelRecertificationEvidenceRegistry(path)
    assert replay.dependency_fingerprint(first.fingerprint_ref, owner_user_id=OWNER) == first
    with pytest.raises(KeyError):
        replay.dependency_fingerprint(_dependency(2).fingerprint_ref, owner_user_id=OWNER)


def test_dependency_file_resolver_detects_source_content_drift(tmp_path: Path) -> None:
    path = tmp_path / "requirements.lock"
    path.write_bytes(b"numpy==2.1.0\n")
    registry = PersistentModelRecertificationEvidenceRegistry(tmp_path / "evidence.jsonl")
    dependency = registry.record_dependency_file(
        path,
        owner_user_id=OWNER,
        dependency_kind=DependencyKind.VENDOR,
        dependency_ref="package:numpy",
        recorded_by="dependency-resolver",
    )
    assert registry.resolve_dependencies(
        (dependency.fingerprint_ref,),
        owner_user_id=OWNER,
        dependency_kind=DependencyKind.VENDOR,
    ) == (dependency,)
    path.write_bytes(b"numpy==2.2.0\n")
    with pytest.raises(ModelEvidenceError, match="content has drifted"):
        registry.resolve_dependencies(
            (dependency.fingerprint_ref,),
            owner_user_id=OWNER,
            dependency_kind=DependencyKind.VENDOR,
        )
