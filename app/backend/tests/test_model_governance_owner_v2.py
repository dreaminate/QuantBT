from __future__ import annotations

import json
import multiprocessing as mp
from dataclasses import replace

import pytest

from app.research_os.model_governance import (
    ModelArtifactInspectionRecord,
    ModelArtifactManifestEntry,
    ModelGovernancePassport,
    ModelMonitoringProfile,
    ModelRecertificationRecord,
    ModelRiskTier,
    PersistentModelGovernanceRegistry,
    RecertificationTrigger,
    SafeLoadingPolicy,
)


def _artifact(**overrides) -> ModelArtifactManifestEntry:
    values = {
        "artifact_ref": "artifact:model:v1",
        "uri": "registry://models/owner-v2/model.safetensors",
        "content_hash": "sha256:owner-v2",
        "producer_run_ref": "training_run:owner-v2",
        "sandbox_inspection_ref": "inspection:owner-v2",
    }
    values.update(overrides)
    return ModelArtifactManifestEntry(**values)


def _passport(**overrides) -> ModelGovernancePassport:
    values = {
        "model_version_ref": "model_version:owner-v2",
        "model_type_card_ref": "model_type_card:owner-v2",
        "training_plan_ref": "training_plan:owner-v2",
        "training_run_ref": "training_run:owner-v2",
        "model_risk_tier": ModelRiskTier.MEDIUM,
        "materiality": "owner-scoped governance regression",
        "intended_use": ("research",),
        "prohibited_use": ("unapproved live trading",),
        "dataset_refs": ("dataset_version:owner-v2",),
        "feature_refs": ("feature:owner-v2",),
        "label_refs": ("label:owner-v2",),
        "training_code_hash": "sha256:training-owner-v2",
        "artifact_manifest": (_artifact(),),
        "safe_loading_policy": SafeLoadingPolicy(
            sandboxed_load_inspect=True,
            torch_weights_only=True,
        ),
        "vendor_dependency_refs": ("none",),
        "foundation_model_dependency_refs": ("none",),
        "monitoring_requirements": ("drift",),
        "recertification_triggers": tuple(RecertificationTrigger),
        "validation_dossier_ref": "validation_dossier:owner-v2",
        "challenger_result": "challenger reviewed",
    }
    values.update(overrides)
    return ModelGovernancePassport(**values)


def _inspection(passport: ModelGovernancePassport, **overrides) -> ModelArtifactInspectionRecord:
    artifact = passport.artifact_manifest[0]
    values = {
        "model_version_ref": passport.model_version_ref,
        "model_passport_ref": passport.passport_id,
        "artifact_ref": artifact.artifact_ref,
        "inspection_ref": artifact.sandbox_inspection_ref,
        "artifact_hash": artifact.content_hash,
        "inspection_status": "accepted",
        "inspection_mode": "metadata_only",
        "inspector_ref": "inspector:owner-v2",
        "checks": ("hash_match",),
        "recorded_by": "alice",
    }
    values.update(overrides)
    return ModelArtifactInspectionRecord(**values)


def _monitor(passport: ModelGovernancePassport) -> ModelMonitoringProfile:
    return ModelMonitoringProfile(
        model_version_ref=passport.model_version_ref,
        model_passport_ref=passport.passport_id,
        metric_refs=("metric:drift",),
        schedule_ref="schedule:daily",
        alert_policy_ref="alert:owner-v2",
        recertification_trigger_refs=(RecertificationTrigger.DATA_SCHEMA_CHANGE,),
    )


def _codes(registry: PersistentModelGovernanceRegistry, passport_ref: str) -> set[str]:
    return {
        violation.code
        for violation in registry.model_closure_violations("alice", passport_ref)
    }


def _record_same_passport_concurrently(path: str, ready, start, results) -> None:
    registry = PersistentModelGovernanceRegistry(path)
    ready.put(True)
    if not start.wait(timeout=10):
        results.put(("error", "start timeout"))
        return
    try:
        recorded = registry.record_passport(
            _passport(),
            owner_user_id="alice",
            recorded_by="alice",
        )
    except Exception as exc:  # noqa: BLE001 - subprocess must report exact failure.
        results.put(("error", repr(exc)))
    else:
        results.put(("ok", recorded.passport_id))


def test_owner_scoped_same_ref_and_ambiguous_lookups_fail_closed(tmp_path):
    path = tmp_path / "model_governance.jsonl"
    registry = PersistentModelGovernanceRegistry(path)
    passport = _passport()

    alice = registry.record_passport(
        passport,
        owner_user_id="alice",
        recorded_by="alice",
    )
    bob = registry.record_passport(
        passport,
        owner_user_id="bob",
        recorded_by="bob",
    )

    assert alice.passport_id == bob.passport_id
    assert alice.owner_user_id == "alice"
    assert bob.owner_user_id == "bob"
    assert registry.passport(alice.passport_id, owner_user_id="alice").recorded_by == "alice"
    assert registry.passport(bob.passport_id, owner_user_id="bob").recorded_by == "bob"
    registry.record_monitoring_profile(
        _monitor(alice),
        owner_user_id="alice",
        recorded_by="alice",
    )
    with pytest.raises(ValueError, match="owner_user_id is required"):
        registry.passport(alice.passport_id)
    with pytest.raises(ValueError, match="owner_user_id is required"):
        registry.passports()
    with pytest.raises(ValueError, match="owner_user_id is required"):
        registry.monitoring_profiles()

    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    assert {row["owner_user_id"] for row in rows} == {"alice", "bob"}
    assert all(row["schema_version"] == 2 for row in rows)
    passport_rows = [row for row in rows if row["event_type"] == "model_passport_recorded"]
    assert all(
        row["passport"]["owner_user_id"] == row["owner_user_id"]
        for row in passport_rows
    )


def test_schema_v1_rows_are_quarantined_and_never_satisfy_owner_lookup(tmp_path):
    path = tmp_path / "model_governance.jsonl"
    legacy = {
        "schema_version": 1,
        "event_type": "model_passport_recorded",
        "passport": {"passport_id": _passport().passport_id},
    }
    path.write_text(json.dumps(legacy) + "\n", encoding="utf-8")

    registry = PersistentModelGovernanceRegistry(path)

    assert registry.legacy_quarantined_count == 1
    assert registry.passports(owner_user_id="alice") == []
    with pytest.raises(KeyError):
        registry.passport(_passport().passport_id, owner_user_id="alice")


def test_unknown_future_schema_is_not_silently_quarantined(tmp_path):
    path = tmp_path / "model_governance.jsonl"
    path.write_text(json.dumps({"schema_version": 3}) + "\n", encoding="utf-8")

    with pytest.raises(ValueError, match="invalid persisted model governance row"):
        PersistentModelGovernanceRegistry(path)


def test_explicit_actor_and_owner_cannot_disagree_with_record(tmp_path):
    registry = PersistentModelGovernanceRegistry(tmp_path / "model_governance.jsonl")

    with pytest.raises(ValueError, match="recorded_by does not match"):
        registry.record_passport(
            _passport(recorded_by="mallory"),
            owner_user_id="alice",
            recorded_by="alice",
        )
    with pytest.raises(ValueError, match="owner_user_id does not match"):
        registry.record_passport(
            _passport(owner_user_id="mallory"),
            owner_user_id="alice",
            recorded_by="alice",
        )
    assert not registry.path.exists()


def test_head_compare_and_swap_is_idempotent_and_rejects_stale_replacement(tmp_path):
    path = tmp_path / "model_governance.jsonl"
    registry = PersistentModelGovernanceRegistry(path)
    recorded = registry.record_passport(
        _passport(),
        owner_user_id="alice",
        recorded_by="alice",
    )
    head_one = registry.current_head_hash(
        recorded.passport_id,
        owner_user_id="alice",
        event_type="model_passport_recorded",
    )

    second_process = PersistentModelGovernanceRegistry(path)
    second_process.record_passport(
        _passport(),
        owner_user_id="alice",
        recorded_by="alice",
    )
    assert len(path.read_text(encoding="utf-8").splitlines()) == 1

    replacement = replace(recorded, materiality="reviewed materiality")
    with pytest.raises(ValueError, match="requires expected_head_hash"):
        registry.record_passport(replacement, owner_user_id="alice", recorded_by="alice")
    with pytest.raises(ValueError, match="expected_head_hash is stale"):
        registry.record_passport(
            replacement,
            owner_user_id="alice",
            recorded_by="alice",
            expected_head_hash="model_governance_head_stale",
        )

    updated = registry.record_passport(
        replacement,
        owner_user_id="alice",
        recorded_by="alice",
        expected_head_hash=head_one,
    )
    head_two = registry.current_head_hash(
        updated.passport_id,
        owner_user_id="alice",
        event_type="model_passport_recorded",
    )
    assert head_two != head_one
    assert registry.is_current_head(
        updated.passport_id,
        head_one,
        owner_user_id="alice",
        event_type="model_passport_recorded",
    ) is False
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    assert [row["revision"] for row in rows] == [1, 2]
    assert rows[1]["previous_head_hash"] == rows[0]["head_hash"]


def test_cross_process_exact_replay_appends_one_schema_v2_event(tmp_path):
    path = tmp_path / "model_governance.jsonl"
    context = mp.get_context("spawn")
    ready = context.Queue()
    results = context.Queue()
    start = context.Event()
    processes = [
        context.Process(
            target=_record_same_passport_concurrently,
            args=(str(path), ready, start, results),
        )
        for _ in range(2)
    ]
    for process in processes:
        process.start()
    assert [ready.get(timeout=15) for _ in processes] == [True, True]
    start.set()
    outcomes = [results.get(timeout=15) for _ in processes]
    for process in processes:
        process.join(timeout=15)
        assert process.exitcode == 0

    assert {status for status, _value in outcomes} == {"ok"}
    assert len({_value for _status, _value in outcomes}) == 1
    assert len(path.read_text(encoding="utf-8").splitlines()) == 1


def test_forged_identity_hash_and_lineage_cannot_close_model_governance(tmp_path):
    with pytest.raises(ValueError, match="artifact identity"):
        _artifact(artifact_id="model_artifact_forged")

    registry = PersistentModelGovernanceRegistry(tmp_path / "model_governance.jsonl")
    passport = registry.record_passport(
        _passport(
            model_risk_tier=ModelRiskTier.HIGH,
            artifact_manifest=(_artifact(producer_run_ref="training_run:forged"),),
        ),
        owner_user_id="alice",
        recorded_by="alice",
    )
    with pytest.raises(ValueError, match="artifact inspection hash does not match"):
        registry.record_artifact_inspection(
            _inspection(passport, artifact_hash="sha256:forged"),
            owner_user_id="alice",
        )

    codes = _codes(registry, passport.passport_id)
    assert "artifact_lineage_mismatch" in codes
    assert "current_artifact_inspection_missing" in codes
    assert "current_monitoring_profile_missing" in codes
    assert "challenger_evidence_not_durably_resolved" in codes


def test_internal_current_chain_is_exact_but_external_closure_stays_red(tmp_path):
    registry = PersistentModelGovernanceRegistry(tmp_path / "model_governance.jsonl")
    passport = registry.record_passport(
        _passport(recertification_records=("pending:recertification",)),
        change_events=(RecertificationTrigger.DATA_SCHEMA_CHANGE,),
        owner_user_id="alice",
        recorded_by="alice",
    )
    recertification = registry.record_recertification_record(
        ModelRecertificationRecord(
            model_version_ref=passport.model_version_ref,
            model_passport_ref=passport.passport_id,
            trigger=RecertificationTrigger.DATA_SCHEMA_CHANGE,
            change_event_ref="change_event:schema-v2",
            evidence_refs=("validation_dossier:schema-v2",),
            decision="accepted",
            recorded_by="reviewer",
        ),
        owner_user_id="alice",
    )
    passport_head = registry.current_head_hash(
        passport.passport_id,
        owner_user_id="alice",
        event_type="model_passport_recorded",
    )
    passport = registry.record_passport(
        replace(passport, recertification_records=(recertification.recertification_record_id,)),
        change_events=(RecertificationTrigger.DATA_SCHEMA_CHANGE,),
        owner_user_id="alice",
        recorded_by="alice",
        expected_head_hash=passport_head,
    )
    registry.record_monitoring_profile(
        _monitor(passport),
        owner_user_id="alice",
        recorded_by="alice",
    )
    registry.record_artifact_inspection(
        _inspection(passport),
        owner_user_id="alice",
    )

    codes = _codes(registry, passport.passport_id)
    assert codes == {
        "training_plan_not_durably_resolved",
        "training_run_not_durably_resolved",
        "model_version_not_durably_resolved",
        "validation_dossier_not_durably_resolved",
        "artifact_content_not_durably_resolved",
        "promotion_not_durably_resolved",
        "approval_not_durably_resolved",
    }

    registry.record_recertification_record(
        replace(
            recertification,
            decision="rejected",
            recertification_record_id="",
        ),
        owner_user_id="alice",
    )
    assert "current_recertification_missing" in _codes(registry, passport.passport_id)


def test_tampered_schema_v2_head_blocks_replay(tmp_path):
    path = tmp_path / "model_governance.jsonl"
    registry = PersistentModelGovernanceRegistry(path)
    registry.record_passport(
        _passport(),
        owner_user_id="alice",
        recorded_by="alice",
    )
    row = json.loads(path.read_text(encoding="utf-8"))
    row["passport"]["materiality"] = "tampered"
    path.write_text(json.dumps(row) + "\n", encoding="utf-8")

    with pytest.raises(ValueError, match="invalid persisted model governance row"):
        PersistentModelGovernanceRegistry(path)
