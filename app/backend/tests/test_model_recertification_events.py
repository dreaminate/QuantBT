from __future__ import annotations

import inspect
import json
import os
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path

import pytest

from app.approval import ApprovalGateService, ApprovalGateStore, GateStateError
from app.experiments.store import ModelRegistry
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
from app.research_os.model_recertification_events import (
    ModelChangeState,
    ModelRecertificationChangeEvent,
    ModelRecertificationEventError,
    ModelRecertificationEvidenceError,
    PersistentModelRecertificationEventRegistry,
    producer_statuses,
    resolve_current_recertification_requirements,
)
from app.research_os.model_recertification_evidence import (
    DependencyKind,
    PersistentModelRecertificationEvidenceRegistry,
)
from app.research_os.spine import RuntimeStatus
from app.training.service import TrainingRequest
from app.training.store import TrainingJob, TrainingJobStore


OWNER = "owner-a"
ACTOR = "training-service"
MODEL = "ridge"
MODEL_CARD = f"model_type_card:{MODEL}"


def _passport(
    *,
    owner: str,
    version: int,
    job_id: str,
    code_hash: str = "sha256:training-code-a",
    artifact_hash: str = "sha256:artifact-a",
    runtime: RuntimeStatus | str = RuntimeStatus.OFFLINE,
    vendor_dependencies: tuple[str, ...] = ("none",),
    foundation_dependencies: tuple[str, ...] = ("none",),
    feature_refs: tuple[str, ...] = ("feature:x",),
) -> ModelGovernancePassport:
    run_ref = f"training_run:run-{owner}-{version}"
    return ModelGovernancePassport(
        model_version_ref=f"model_version:{MODEL}:v{version}",
        model_type_card_ref=MODEL_CARD,
        training_plan_ref=f"training_plan:{job_id}",
        training_run_ref=run_ref,
        model_risk_tier=ModelRiskTier.MEDIUM,
        materiality="research regression model",
        intended_use=("research review",),
        prohibited_use=("direct live order placement",),
        dataset_refs=(f"dataset:{version}",),
        feature_refs=feature_refs,
        label_refs=("label:y",),
        training_code_hash=code_hash,
        artifact_manifest=(
            ModelArtifactManifestEntry(
                artifact_ref=f"model_artifact:{job_id}",
                uri=f"project://{job_id}/model.json",
                source=ModelArtifactSource.PROJECT_PRODUCED,
                content_hash=artifact_hash,
                producer_run_ref=run_ref,
                sandbox_inspection_ref=f"inspection:{job_id}",
            ),
        ),
        safe_loading_policy=SafeLoadingPolicy(
            sandboxed_load_inspect=True,
            direct_load_allowed=False,
            policy_ref="test-safe-loader",
        ),
        vendor_dependency_refs=vendor_dependencies,
        foundation_model_dependency_refs=foundation_dependencies,
        monitoring_requirements=("performance degradation monitor",),
        recertification_triggers=tuple(RecertificationTrigger),
        validation_dossier_ref=f"validation_dossier:{job_id}",
        challenger_result="not required for medium risk",
        dataset_schema_fingerprint="schema:stable",
        target_runtime=runtime,
        owner_user_id=owner,
        recorded_by=ACTOR,
    )


def _job(
    passport: ModelGovernancePassport,
    *,
    owner: str,
    version: int,
    job_id: str,
    asset_class: str,
) -> TrainingJob:
    request = TrainingRequest(
        name=f"train-v{version}",
        model=MODEL,
        task="regression",
        feature_cols=list(passport.feature_refs),
        label_col="label:y",
        asset_class=asset_class,
    )
    return TrainingJob(
        job_id=job_id,
        name=request.name,
        model=MODEL,
        family="ml",
        task="regression",
        owner_user_id=owner,
        status="succeeded",
        request=request.to_dict(),
        run_id=f"run-{owner}-{version}",
        model_version=version,
        model_passport_ref=passport.passport_id,
        validation_dossier_ref=passport.validation_dossier_ref,
    )


def _record_pair(
    tmp_path: Path,
    *,
    owner: str = OWNER,
    second_code_hash: str = "sha256:training-code-a",
    second_artifact_hash: str = "sha256:artifact-a",
    before_asset_class: str = "equity_cn",
    after_asset_class: str = "equity_cn",
    second_runtime: RuntimeStatus | str = RuntimeStatus.OFFLINE,
    before_vendor_dependencies: tuple[str, ...] = ("none",),
    second_vendor_dependencies: tuple[str, ...] = ("none",),
    before_feature_refs: tuple[str, ...] = ("feature:x",),
    second_feature_refs: tuple[str, ...] = ("feature:x",),
    job_store: TrainingJobStore | None = None,
    governance: PersistentModelGovernanceRegistry | None = None,
) -> tuple[
    PersistentModelGovernanceRegistry,
    TrainingJobStore,
    ModelGovernancePassport,
    ModelGovernancePassport,
]:
    governance = governance or PersistentModelGovernanceRegistry(
        tmp_path / "governance.jsonl"
    )
    job_store = job_store or TrainingJobStore(tmp_path / "training")
    owner_token = owner.replace("/", "-")
    first_job_id = f"job-{owner_token}-1"
    second_job_id = f"job-{owner_token}-2"
    first = _passport(
        owner=owner,
        version=1,
        job_id=first_job_id,
        vendor_dependencies=before_vendor_dependencies,
        feature_refs=before_feature_refs,
    )
    second = _passport(
        owner=owner,
        version=2,
        job_id=second_job_id,
        code_hash=second_code_hash,
        artifact_hash=second_artifact_hash,
        runtime=second_runtime,
        vendor_dependencies=second_vendor_dependencies,
        feature_refs=second_feature_refs,
    )
    job_store.create(
        _job(
            first,
            owner=owner,
            version=1,
            job_id=first_job_id,
            asset_class=before_asset_class,
        )
    )
    governance.record_passport(first, owner_user_id=owner, recorded_by=ACTOR)
    job_store.create(
        _job(
            second,
            owner=owner,
            version=2,
            job_id=second_job_id,
            asset_class=after_asset_class,
        )
    )
    governance.record_passport(second, owner_user_id=owner, recorded_by=ACTOR)
    return governance, job_store, first, second


def _detect(
    registry: PersistentModelRecertificationEventRegistry,
    governance: PersistentModelGovernanceRegistry,
    jobs: TrainingJobStore,
    current: ModelGovernancePassport,
    *,
    owner: str = OWNER,
):
    return registry.detect_and_record_current(
        governance=governance,
        owner_user_id=owner,
        current_passport_ref=current.passport_id,
        training_jobs=jobs,
    )


def test_no_semantic_change_emits_no_event(tmp_path: Path) -> None:
    evidence = PersistentModelRecertificationEvidenceRegistry(
        tmp_path / "recertification-evidence.jsonl"
    )
    dependency_a = evidence.record_dependency_content(
        owner_user_id=OWNER,
        dependency_kind=DependencyKind.VENDOR,
        dependency_ref="package:a",
        content=b"a==1\n",
        resolver_ref="package-lock:a:v1",
        recorded_by="dependency-resolver",
    )
    dependency_b = evidence.record_dependency_content(
        owner_user_id=OWNER,
        dependency_kind=DependencyKind.VENDOR,
        dependency_ref="package:b",
        content=b"b==1\n",
        resolver_ref="package-lock:b:v1",
        recorded_by="dependency-resolver",
    )
    governance, jobs, _first, second = _record_pair(
        tmp_path,
        before_vendor_dependencies=(dependency_b.fingerprint_ref, dependency_a.fingerprint_ref),
        second_vendor_dependencies=(dependency_a.fingerprint_ref, dependency_b.fingerprint_ref),
    )
    path = tmp_path / "recertification-events.jsonl"
    registry = PersistentModelRecertificationEventRegistry(
        path,
        evidence_registry=evidence,
    )

    assert _detect(registry, governance, jobs, second) == ()
    assert registry.events_for_passport(second.passport_id, owner_user_id=OWNER) == ()
    assert not path.exists()


def test_exact_typed_transition_emits_four_obligations_and_exact_getters(
    tmp_path: Path,
) -> None:
    evidence = PersistentModelRecertificationEvidenceRegistry(
        tmp_path / "recertification-evidence.jsonl"
    )
    dependency_v1 = evidence.record_dependency_content(
        owner_user_id=OWNER,
        dependency_kind=DependencyKind.VENDOR,
        dependency_ref="package:model-runtime",
        content=b"model-runtime==1\n",
        resolver_ref="package-lock:model-runtime:v1",
        recorded_by="dependency-resolver",
    )
    dependency_v2 = evidence.record_dependency_content(
        owner_user_id=OWNER,
        dependency_kind=DependencyKind.VENDOR,
        dependency_ref="package:model-runtime",
        content=b"model-runtime==2\n",
        resolver_ref="package-lock:model-runtime:v2",
        recorded_by="dependency-resolver",
    )
    governance, jobs, first, second = _record_pair(
        tmp_path,
        second_code_hash="sha256:training-code-b",
        second_artifact_hash="sha256:artifact-b",
        after_asset_class="crypto_perp",
        second_runtime=RuntimeStatus.PAPER,
        before_vendor_dependencies=(dependency_v1.fingerprint_ref,),
        second_vendor_dependencies=(dependency_v2.fingerprint_ref,),
    )
    registry = PersistentModelRecertificationEventRegistry(
        tmp_path / "recertification-events.jsonl",
        evidence_registry=evidence,
    )

    events = _detect(registry, governance, jobs, second)

    assert {event.trigger for event in events} == {
        RecertificationTrigger.MATERIAL_MODEL_CHANGE,
        RecertificationTrigger.NEW_ASSET_CLASS,
        RecertificationTrigger.NEW_EXECUTION_ENVIRONMENT,
        RecertificationTrigger.DEPENDENCY_UPDATE,
    }
    assert all(event.owner_user_id == OWNER for event in events)
    assert all(event.before_passport_ref == first.passport_id for event in events)
    assert all(event.after_passport_ref == second.passport_id for event in events)
    assert all(event.obligation == "requires_recertification" for event in events)
    assert all(not hasattr(event, "decision") for event in events)
    assert registry.events_for_passport(
        second.passport_id, owner_user_id=OWNER
    ) == events
    assert registry.events_for_model(MODEL_CARD, owner_user_id=OWNER) == events
    for event in events:
        assert registry.event(event.event_ref, owner_user_id=OWNER) == event
        assert registry.current_record_hash(
            event.event_ref, owner_user_id=OWNER
        ).startswith("model_recertification_record_")
        assert event.before_state.state_hash != event.after_state.state_hash
        assert first.passport_id in event.before_state.evidence_refs
        assert second.passport_id in event.after_state.evidence_refs


def test_feature_order_change_is_a_material_model_change(tmp_path: Path) -> None:
    governance, jobs, _first, second = _record_pair(
        tmp_path,
        before_feature_refs=("feature:x", "feature:z"),
        second_feature_refs=("feature:z", "feature:x"),
    )
    registry = PersistentModelRecertificationEventRegistry(
        tmp_path / "recertification-events.jsonl"
    )

    events = _detect(registry, governance, jobs, second)

    assert tuple(event.trigger for event in events) == (
        RecertificationTrigger.MATERIAL_MODEL_CHANGE,
    )


def test_replay_restart_and_concurrent_detection_are_idempotent(tmp_path: Path) -> None:
    governance, jobs, _first, second = _record_pair(
        tmp_path,
        second_code_hash="sha256:training-code-b",
        second_artifact_hash="sha256:artifact-b",
    )
    path = tmp_path / "recertification-events.jsonl"
    first_registry = PersistentModelRecertificationEventRegistry(path)
    second_registry = PersistentModelRecertificationEventRegistry(path)

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(
            pool.map(
                lambda registry: _detect(registry, governance, jobs, second),
                (first_registry, second_registry),
            )
        )

    assert results[0] == results[1]
    assert len(results[0]) == 1
    original = path.read_bytes()
    assert len(path.read_text(encoding="utf-8").splitlines()) == 1

    restarted = PersistentModelRecertificationEventRegistry(path)
    assert _detect(restarted, governance, jobs, second) == results[0]
    assert path.read_bytes() == original


def test_cross_owner_events_and_getters_do_not_leak(tmp_path: Path) -> None:
    governance = PersistentModelGovernanceRegistry(tmp_path / "governance.jsonl")
    jobs = TrainingJobStore(tmp_path / "training")
    registry = PersistentModelRecertificationEventRegistry(
        tmp_path / "recertification-events.jsonl"
    )
    governance, jobs, _a_first, a_second = _record_pair(
        tmp_path,
        owner="owner-a",
        second_code_hash="sha256:owner-a-code-b",
        second_artifact_hash="sha256:owner-a-artifact-b",
        governance=governance,
        job_store=jobs,
    )
    governance, jobs, _b_first, b_second = _record_pair(
        tmp_path,
        owner="owner-b",
        second_code_hash="sha256:owner-b-code-b",
        second_artifact_hash="sha256:owner-b-artifact-b",
        governance=governance,
        job_store=jobs,
    )

    a_events = _detect(registry, governance, jobs, a_second, owner="owner-a")
    b_events = _detect(registry, governance, jobs, b_second, owner="owner-b")

    assert len(a_events) == len(b_events) == 1
    assert a_events[0].event_ref != b_events[0].event_ref
    with pytest.raises(KeyError, match="not recorded for owner"):
        registry.event(a_events[0].event_ref, owner_user_id="owner-b")
    assert registry.events_for_passport(
        a_second.passport_id, owner_user_id="owner-b"
    ) == ()
    with pytest.raises(ModelRecertificationEvidenceError, match="not recorded for owner"):
        registry.detect_and_record_current(
            governance=governance,
            owner_user_id="owner-b",
            current_passport_ref=a_second.passport_id,
            training_jobs=jobs,
        )


def test_missing_typed_asset_evidence_fails_closed_without_partial_event(
    tmp_path: Path,
) -> None:
    governance = PersistentModelGovernanceRegistry(tmp_path / "governance.jsonl")
    jobs = TrainingJobStore(tmp_path / "training")
    first = _passport(owner=OWNER, version=1, job_id="job-1")
    second = _passport(
        owner=OWNER,
        version=2,
        job_id="job-2",
        code_hash="sha256:changed",
        artifact_hash="sha256:changed",
    )
    jobs.create(
        _job(
            first,
            owner=OWNER,
            version=1,
            job_id="job-1",
            asset_class="equity_cn",
        )
    )
    governance.record_passport(first, owner_user_id=OWNER, recorded_by=ACTOR)
    governance.record_passport(second, owner_user_id=OWNER, recorded_by=ACTOR)
    path = tmp_path / "recertification-events.jsonl"
    registry = PersistentModelRecertificationEventRegistry(path)

    with pytest.raises(
        ModelRecertificationEvidenceError,
        match="cannot resolve training job job-2",
    ):
        _detect(registry, governance, jobs, second)

    assert not path.exists()
    assert registry.events_for_passport(second.passport_id, owner_user_id=OWNER) == ()


def test_feature_and_performance_configuration_cannot_invent_events(
    tmp_path: Path,
) -> None:
    governance, jobs, _first, second = _record_pair(tmp_path)
    governance.record_monitoring_profile(
        ModelMonitoringProfile(
            model_version_ref=second.model_version_ref,
            model_passport_ref=second.passport_id,
            metric_refs=("metric:production-performance",),
            schedule_ref="schedule:weekly",
            alert_policy_ref="alert:model",
            drift_signal_refs=("configured-feature-drift-signal",),
            performance_threshold_refs=("configured-performance-floor",),
            recertification_trigger_refs=tuple(RecertificationTrigger),
            owner_user_id=OWNER,
            recorded_by=ACTOR,
        ),
        owner_user_id=OWNER,
        recorded_by=ACTOR,
    )
    registry = PersistentModelRecertificationEventRegistry(
        tmp_path / "recertification-events.jsonl"
    )

    assert _detect(registry, governance, jobs, second) == ()
    statuses = {status.trigger: status for status in producer_statuses()}
    assert set(statuses) == set(RecertificationTrigger) - {
        RecertificationTrigger.DATA_SCHEMA_CHANGE
    }
    assert statuses[RecertificationTrigger.FEATURE_DISTRIBUTION_DRIFT].available is False
    assert "configuration, not observations" in statuses[
        RecertificationTrigger.FEATURE_DISTRIBUTION_DRIFT
    ].blocker
    assert statuses[RecertificationTrigger.PERFORMANCE_DEGRADATION].available is False
    assert "factor monitoring is not model evidence" in statuses[
        RecertificationTrigger.PERFORMANCE_DEGRADATION
    ].blocker
    assert "stage change without a new passport" in statuses[
        RecertificationTrigger.NEW_EXECUTION_ENVIRONMENT
    ].limitation
    assert statuses[RecertificationTrigger.DEPENDENCY_UPDATE].available is False
    assert "no durable dependency evidence registry" in statuses[
        RecertificationTrigger.DEPENDENCY_UPDATE
    ].blocker
    assert "trigger" not in inspect.signature(
        PersistentModelRecertificationEventRegistry.detect_and_record_current
    ).parameters

    state_a = ModelChangeState.build({"value": 1}, ("evidence:a",))
    state_b = ModelChangeState.build({"value": 2}, ("evidence:b",))
    with pytest.raises(ModelRecertificationEventError, match="no automatic producer"):
        ModelRecertificationChangeEvent(
            owner_user_id=OWNER,
            model_type_card_ref=MODEL_CARD,
            trigger=RecertificationTrigger.FEATURE_DISTRIBUTION_DRIFT,
            before_passport_ref="passport:a",
            after_passport_ref="passport:b",
            before_model_version_ref="model:a",
            after_model_version_ref="model:b",
            before_state=state_a,
            after_state=state_b,
        )


def test_append_fsync_failure_rolls_back_all_new_events(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    evidence = PersistentModelRecertificationEvidenceRegistry(
        tmp_path / "recertification-evidence.jsonl"
    )
    dependency_v1 = evidence.record_dependency_content(
        owner_user_id=OWNER,
        dependency_kind=DependencyKind.VENDOR,
        dependency_ref="package:model-runtime",
        content=b"model-runtime==1\n",
        resolver_ref="package-lock:model-runtime:v1",
        recorded_by="dependency-resolver",
    )
    dependency_v2 = evidence.record_dependency_content(
        owner_user_id=OWNER,
        dependency_kind=DependencyKind.VENDOR,
        dependency_ref="package:model-runtime",
        content=b"model-runtime==2\n",
        resolver_ref="package-lock:model-runtime:v2",
        recorded_by="dependency-resolver",
    )
    governance, jobs, _first, second = _record_pair(
        tmp_path,
        second_code_hash="sha256:training-code-b",
        second_artifact_hash="sha256:artifact-b",
        after_asset_class="crypto_perp",
        second_runtime=RuntimeStatus.PAPER,
        before_vendor_dependencies=(dependency_v1.fingerprint_ref,),
        second_vendor_dependencies=(dependency_v2.fingerprint_ref,),
    )
    path = tmp_path / "recertification-events.jsonl"
    registry = PersistentModelRecertificationEventRegistry(
        path,
        evidence_registry=evidence,
    )
    import app.research_os.model_recertification_events as event_module

    real_fsync = os.fsync
    calls = 0

    def fail_once(fd: int) -> None:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise OSError("injected append fsync failure")
        real_fsync(fd)

    monkeypatch.setattr(event_module.os, "fsync", fail_once)
    with pytest.raises(OSError, match="injected append fsync failure"):
        _detect(registry, governance, jobs, second)

    assert not path.exists()
    assert registry.events_for_passport(second.passport_id, owner_user_id=OWNER) == ()

    monkeypatch.setattr(event_module.os, "fsync", real_fsync)
    assert len(_detect(registry, governance, jobs, second)) == 4


def test_restart_rejects_tampered_event_row(tmp_path: Path) -> None:
    governance, jobs, _first, second = _record_pair(
        tmp_path,
        second_code_hash="sha256:training-code-b",
        second_artifact_hash="sha256:artifact-b",
    )
    path = tmp_path / "recertification-events.jsonl"
    registry = PersistentModelRecertificationEventRegistry(path)
    assert len(_detect(registry, governance, jobs, second)) == 1
    row = json.loads(path.read_text(encoding="utf-8"))
    row["event"]["after_state"]["state_hash"] = "model_recertification_state_tampered"
    path.write_text(json.dumps(row, sort_keys=True) + "\n", encoding="utf-8")

    with pytest.raises(
        ModelRecertificationEventError,
        match="invalid model recertification event row",
    ):
        PersistentModelRecertificationEventRegistry(path)


def test_event_ref_binds_owner_model_trigger_and_both_states() -> None:
    before = ModelChangeState.build({"value": "before"}, ("evidence:before",))
    after = ModelChangeState.build({"value": "after"}, ("evidence:after",))
    event = ModelRecertificationChangeEvent(
        owner_user_id=OWNER,
        model_type_card_ref=MODEL_CARD,
        trigger=RecertificationTrigger.MATERIAL_MODEL_CHANGE,
        before_passport_ref="passport:before",
        after_passport_ref="passport:after",
        before_model_version_ref="model:v1",
        after_model_version_ref="model:v2",
        before_state=before,
        after_state=after,
    )

    mutations = (
        replace(event, owner_user_id="owner-b", event_ref=""),
        replace(event, model_type_card_ref="model_type_card:other", event_ref=""),
        replace(
            event,
            trigger=RecertificationTrigger.DEPENDENCY_UPDATE,
            event_ref="",
        ),
        replace(
            event,
            after_state=ModelChangeState.build(
                {"value": "different-after"}, ("evidence:after",)
            ),
            event_ref="",
        ),
    )
    assert all(candidate.event_ref != event.event_ref for candidate in mutations)


def test_exact_event_resolution_ignores_passport_claims_and_latest_rejection_reopens(
    tmp_path: Path,
) -> None:
    governance, jobs, first, second = _record_pair(
        tmp_path,
        second_code_hash="sha256:training-code-b",
        second_artifact_hash="sha256:artifact-b",
    )
    registry = PersistentModelRecertificationEventRegistry(
        tmp_path / "recertification-events.jsonl"
    )

    with pytest.raises(
        ModelRecertificationEvidenceError,
        match="recertification required for material_model_change event",
    ):
        resolve_current_recertification_requirements(
            governance=governance,
            event_registry=registry,
            training_jobs=jobs,
            owner_user_id=OWNER,
            current_passport_ref=second.passport_id,
        )

    event = registry.events_for_passport(
        second.passport_id,
        owner_user_id=OWNER,
    )[0]
    # An accepted record for the exact event still cannot clear a different
    # before/after passport binding.
    governance.record_recertification_record(
        ModelRecertificationRecord(
            model_version_ref=first.model_version_ref,
            model_passport_ref=first.passport_id,
            trigger=event.trigger,
            change_event_ref=event.event_ref,
            evidence_refs=("evidence:wrong-transition",),
            decision="accepted",
            recorded_by="reviewer-a",
            owner_user_id=OWNER,
        ),
        owner_user_id=OWNER,
        recorded_by="reviewer-a",
    )
    with pytest.raises(
        ModelRecertificationEvidenceError,
        match="binds the wrong model transition",
    ):
        resolve_current_recertification_requirements(
            governance=governance,
            event_registry=registry,
            training_jobs=jobs,
            owner_user_id=OWNER,
            current_passport_ref=second.passport_id,
        )

    accepted = governance.record_recertification_record(
        ModelRecertificationRecord(
            model_version_ref=second.model_version_ref,
            model_passport_ref=second.passport_id,
            trigger=event.trigger,
            change_event_ref=event.event_ref,
            evidence_refs=("evidence:exact-transition",),
            decision="accepted",
            recorded_by="reviewer-b",
            owner_user_id=OWNER,
        ),
        owner_user_id=OWNER,
        recorded_by="reviewer-b",
    )
    resolution = resolve_current_recertification_requirements(
        governance=governance,
        event_registry=registry,
        training_jobs=jobs,
        owner_user_id=OWNER,
        current_passport_ref=second.passport_id,
    )
    assert resolution.recertification_records == (accepted,)
    assert resolution.requirements[0].change_event_ref == event.event_ref
    assert resolution.requirements[0].event_record_hash == registry.current_record_hash(
        event.event_ref,
        owner_user_id=OWNER,
    )
    assert second.recertification_records == ()

    governance.record_recertification_record(
        ModelRecertificationRecord(
            model_version_ref=second.model_version_ref,
            model_passport_ref=second.passport_id,
            trigger=event.trigger,
            change_event_ref=event.event_ref,
            evidence_refs=("evidence:later-review",),
            decision="rejected",
            recorded_by="reviewer-c",
            owner_user_id=OWNER,
        ),
        owner_user_id=OWNER,
        recorded_by="reviewer-c",
    )
    with pytest.raises(
        ModelRecertificationEvidenceError,
        match="latest exact recertification review does not clear",
    ):
        resolve_current_recertification_requirements(
            governance=governance,
            event_registry=registry,
            training_jobs=jobs,
            owner_user_id=OWNER,
            current_passport_ref=second.passport_id,
        )


def test_model_promotion_requires_and_binds_exact_automatic_event(
    tmp_path: Path,
) -> None:
    governance = PersistentModelGovernanceRegistry(
        tmp_path / "audit" / "model_governance.jsonl"
    )
    jobs = TrainingJobStore(tmp_path / "training_runs")
    gate_service = ApprovalGateService(
        ApprovalGateStore(tmp_path / "approval"),
        ledger=Ledger(tmp_path / "ledger"),
    )
    models = ModelRegistry(
        tmp_path / "experiments",
        gate_service=gate_service,
        model_governance_registry=governance,
    )
    events = models.model_recertification_event_registry
    models.bind_model_recertification_events(events, jobs)
    governance, jobs, _first, second = _record_pair(
        tmp_path,
        second_code_hash="sha256:training-code-b",
        second_artifact_hash="sha256:artifact-b",
        job_store=jobs,
        governance=governance,
    )
    for version, passport in enumerate(
        governance.passports(owner_user_id=OWNER),
        start=1,
    ):
        models.register_version(
            MODEL,
            artifact_path=f"model-v{version}.safetensors",
            model_passport_ref=passport.passport_id,
            validation_dossier_ref=passport.validation_dossier_ref,
            owner_user_id=OWNER,
        )

    evidence = {
        "config_hash": "cfg-recertification-promotion",
        "dataset_version": "dataset:promotion:v2",
        "n_eff": 5,
        "n_trials_raw": 5,
        "dsr": 0.92,
        "pbo": 0.10,
        "bootstrap_ci": [0.4, 1.8],
        "bootstrap_estimate": 1.0,
        "champion_challenger": {"verdict": "challenger_wins"},
        "returns_sha256": "sha256:promotion-returns",
    }
    def promote():
        return models.promote(
            MODEL,
            2,
            "staging",
            created_by=OWNER,
            verification_record_id="verification:recertification:v2",
            evidence=evidence,
            strategy_goal_ref="strategy-goal:recertification",
            model_passport_ref=second.passport_id,
            owner_user_id=OWNER,
        )

    with pytest.raises(
        GateStateError,
        match="recertification required for material_model_change event",
    ):
        promote()
    event = events.events_for_passport(second.passport_id, owner_user_id=OWNER)[0]
    accepted = governance.record_recertification_record(
        ModelRecertificationRecord(
            model_version_ref=second.model_version_ref,
            model_passport_ref=second.passport_id,
            trigger=event.trigger,
            change_event_ref=event.event_ref,
            evidence_refs=("validation_dossier:promotion-review:v2",),
            decision="accepted",
            recorded_by="reviewer-b",
            owner_user_id=OWNER,
        ),
        owner_user_id=OWNER,
        recorded_by="reviewer-b",
    )

    gate = promote()
    assert gate.decision == "pending"
    assert gate.evidence["model_recertification_event_refs"] == [event.event_ref]
    assert gate.evidence["model_recertification_event_record_hashes"] == {
        event.event_ref: events.current_record_hash(
            event.event_ref,
            owner_user_id=OWNER,
        )
    }
    assert gate.evidence["model_recertification_record_refs"] == [
        accepted.recertification_record_id
    ]

    governance.record_recertification_record(
        ModelRecertificationRecord(
            model_version_ref=second.model_version_ref,
            model_passport_ref=second.passport_id,
            trigger=event.trigger,
            change_event_ref=event.event_ref,
            evidence_refs=("validation_dossier:promotion-rejected:v2",),
            decision="rejected",
            recorded_by="reviewer-c",
            owner_user_id=OWNER,
        ),
        owner_user_id=OWNER,
        recorded_by="reviewer-c",
    )
    with pytest.raises(
        GateStateError,
        match="latest exact recertification review does not clear",
    ):
        models.promotion_gate(gate.gate_id, owner_user_id=OWNER)


def test_stage_only_environment_event_is_bound_before_and_after_promotion(
    tmp_path: Path,
) -> None:
    governance = PersistentModelGovernanceRegistry(
        tmp_path / "audit" / "model_governance.jsonl"
    )
    jobs = TrainingJobStore(tmp_path / "training_runs")
    gate_service = ApprovalGateService(
        ApprovalGateStore(tmp_path / "approval"),
        ledger=Ledger(tmp_path / "ledger"),
    )
    models = ModelRegistry(
        tmp_path / "experiments",
        gate_service=gate_service,
        model_governance_registry=governance,
    )
    events = models.model_recertification_event_registry
    models.bind_model_recertification_events(events, jobs)
    passport = _passport(owner=OWNER, version=1, job_id="job-stage-only")
    jobs.create(
        _job(
            passport,
            owner=OWNER,
            version=1,
            job_id="job-stage-only",
            asset_class="equity_cn",
        )
    )
    governance.record_passport(
        passport,
        owner_user_id=OWNER,
        recorded_by=ACTOR,
    )
    models.register_version(
        MODEL,
        artifact_path="model-stage-only.safetensors",
        model_passport_ref=passport.passport_id,
        validation_dossier_ref=passport.validation_dossier_ref,
        owner_user_id=OWNER,
    )
    evidence = {
        "config_hash": "cfg-stage-only",
        "dataset_version": "dataset:stage-only:v1",
        "n_eff": 5,
        "n_trials_raw": 5,
        "dsr": 0.92,
        "pbo": 0.10,
        "bootstrap_ci": [0.4, 1.8],
        "bootstrap_estimate": 1.0,
        "champion_challenger": {"verdict": "challenger_wins"},
        "returns_sha256": "sha256:stage-only-returns",
    }

    staging_gate = models.promote(
        MODEL,
        1,
        "staging",
        created_by=OWNER,
        verification_record_id="verification:stage-only:staging",
        evidence=evidence,
        strategy_goal_ref="strategy-goal:stage-only",
        model_passport_ref=passport.passport_id,
        owner_user_id=OWNER,
    )
    models.approve_promotion(
        staging_gate.gate_id,
        model_id=MODEL,
        owner_user_id=OWNER,
        approver="reviewer-stage",
        reason="Independent review accepted the staging evidence and bounded scope.",
    )

    def promote_production():
        return models.promote(
            MODEL,
            1,
            "production",
            created_by=OWNER,
            verification_record_id="verification:stage-only:production",
            evidence=evidence,
            strategy_goal_ref="strategy-goal:stage-only",
            model_passport_ref=passport.passport_id,
            owner_user_id=OWNER,
        )

    with pytest.raises(
        GateStateError,
        match="recertification required for new_execution_environment event",
    ):
        promote_production()
    stage_event = next(
        item
        for item in events.events_for_passport(
            passport.passport_id,
            owner_user_id=OWNER,
        )
        if item.trigger == RecertificationTrigger.NEW_EXECUTION_ENVIRONMENT
    )
    accepted = governance.record_recertification_record(
        ModelRecertificationRecord(
            model_version_ref=passport.model_version_ref,
            model_passport_ref=passport.passport_id,
            trigger=stage_event.trigger,
            change_event_ref=stage_event.event_ref,
            evidence_refs=("validation_dossier:stage-only:production",),
            decision="accepted",
            recorded_by="reviewer-stage",
            owner_user_id=OWNER,
        ),
        owner_user_id=OWNER,
        recorded_by="reviewer-stage",
    )
    production_gate = promote_production()
    assert production_gate.evidence["model_recertification_event_refs"] == [
        stage_event.event_ref
    ]
    assert production_gate.evidence["model_recertification_record_refs"] == [
        accepted.recertification_record_id
    ]
    approved = models.approve_promotion(
        production_gate.gate_id,
        model_id=MODEL,
        owner_user_id=OWNER,
        approver="reviewer-production",
        reason="Independent review accepted the production environment and rollback boundary.",
        risk_restated="Production promotion remains bounded by monitoring and rollback controls.",
    )
    assert approved.side_effect_executed is True
    replayed = models.promotion_gate(
        production_gate.gate_id,
        owner_user_id=OWNER,
    )
    assert replayed.decision == "approved"
    post_events = events.detect_and_record_current(
        governance=governance,
        owner_user_id=OWNER,
        current_passport_ref=passport.passport_id,
        training_jobs=jobs,
    )
    assert stage_event in post_events
