"""Owner-v2 persistence and promotion tests for ``ModelRegistry``."""

from __future__ import annotations

import json
import multiprocessing as mp
from pathlib import Path

import pytest

from app.approval import ApprovalGateService, ApprovalGateStore, GateStateError
from app.experiments.store import ModelRegistry
from app.lineage.ledger import Ledger
from app.research_os.model_governance import (
    ModelArtifactManifestEntry,
    ModelGovernancePassport,
    ModelRiskTier,
    PersistentModelGovernanceRegistry,
    RecertificationTrigger,
    SafeLoadingPolicy,
)
from app.training import TrainingService


def _register_same_model_concurrently(
    root: str,
    ready,
    start,
    results,
) -> None:
    registry = ModelRegistry(Path(root))
    ready.put(True)
    if not start.wait(timeout=10):
        results.put(("error", "start timeout"))
        return
    try:
        version = registry.register_version(
            "shared",
            owner_user_id="alice",
        )
    except Exception as exc:  # noqa: BLE001 - subprocess returns exact failure.
        results.put(("error", repr(exc)))
    else:
        results.put(("ok", version.version))


def _passport(owner: str, *, model_id: str = "shared") -> ModelGovernancePassport:
    training_run_ref = f"training_run:{owner}:{model_id}:v1"
    artifact = ModelArtifactManifestEntry(
        artifact_ref=f"artifact:{owner}:{model_id}:v1",
        uri=f"registry://{owner}/{model_id}/v1.safetensors",
        content_hash=f"sha256:{owner}:{model_id}:v1",
        producer_run_ref=training_run_ref,
        sandbox_inspection_ref=f"inspection:{owner}:{model_id}:v1",
    )
    return ModelGovernancePassport(
        model_version_ref=f"model_version:{model_id}:v1",
        model_type_card_ref=f"model_type_card:{model_id}",
        training_plan_ref=f"training_plan:{owner}:{model_id}:v1",
        training_run_ref=training_run_ref,
        model_risk_tier=ModelRiskTier.MEDIUM,
        materiality="owner-scoped model registry test",
        intended_use=("research",),
        prohibited_use=("unapproved live trading",),
        dataset_refs=(f"dataset:{owner}:v1",),
        feature_refs=("feature:f1",),
        label_refs=("label:y",),
        training_code_hash=f"sha256:training:{owner}:{model_id}:v1",
        artifact_manifest=(artifact,),
        safe_loading_policy=SafeLoadingPolicy(
            sandboxed_load_inspect=True,
            torch_weights_only=True,
        ),
        vendor_dependency_refs=("none",),
        foundation_model_dependency_refs=("none",),
        monitoring_requirements=("drift",),
        recertification_triggers=tuple(RecertificationTrigger),
        validation_dossier_ref=f"validation_dossier:{owner}:{model_id}:v1",
        challenger_result="challenger reviewed",
        owner_user_id=owner,
        recorded_by=owner,
    )


def _evidence() -> dict:
    return {
        "config_hash": "cfg_owner_registry_v2",
        "dataset_version": "dataset:v1",
        "n_eff": 5,
        "n_trials_raw": 5,
        "dsr": 0.92,
        "pbo": 0.10,
        "bootstrap_ci": [0.4, 1.8],
        "bootstrap_estimate": 1.0,
        "champion_challenger": {"verdict": "challenger_wins"},
        "returns_sha256": "sha256:returns",
    }


def _approval_service(tmp_path) -> ApprovalGateService:
    return ApprovalGateService(
        ApprovalGateStore(tmp_path / "approval_gates"),
        ledger=Ledger(tmp_path / "ledger"),
    )


def test_same_model_versions_are_owner_scoped_and_ambiguous_reads_fail(tmp_path) -> None:
    registry = ModelRegistry(tmp_path)

    alice_v1 = registry.register_version(
        "shared",
        artifact_path="alice-v1.pkl",
        owner_user_id="alice",
    )
    alice_v2 = registry.register_version(
        "shared",
        artifact_path="alice-v2.pkl",
        owner_user_id="alice",
    )
    bob_v1 = registry.register_version(
        "shared",
        artifact_path="bob-v1.pkl",
        owner_user_id="bob",
    )

    assert [row.version for row in registry.list_versions("shared", owner_user_id="alice")] == [1, 2]
    assert [row.version for row in registry.list_versions("shared", owner_user_id="bob")] == [1]
    assert alice_v1.owner_user_id == "alice"
    assert bob_v1.owner_user_id == "bob"
    assert alice_v1.model_asset_ref == alice_v2.model_asset_ref
    assert alice_v1.model_asset_ref != bob_v1.model_asset_ref
    assert registry.list_versions("shared", owner_user_id="mallory") == []
    with pytest.raises(ValueError, match="ambiguous lookup"):
        registry.list_versions("shared")
    with pytest.raises(ValueError, match="ambiguous lookup"):
        registry.list_models()

    rows = [
        json.loads(line)
        for line in (tmp_path / "models.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert {row["schema_version"] for row in rows} == {2}
    assert {row["owner_user_id"] for row in rows} == {"alice", "bob"}


def test_concurrent_same_owner_registration_allocates_distinct_versions(tmp_path) -> None:
    context = mp.get_context("spawn")
    ready = context.Queue()
    start = context.Event()
    results = context.Queue()
    processes = [
        context.Process(
            target=_register_same_model_concurrently,
            args=(str(tmp_path), ready, start, results),
        )
        for _ in range(2)
    ]
    for process in processes:
        process.start()
    assert ready.get(timeout=10) is True
    assert ready.get(timeout=10) is True
    start.set()
    outcomes = [results.get(timeout=15) for _ in processes]
    for process in processes:
        process.join(timeout=15)
        assert process.exitcode == 0

    assert sorted(outcomes) == [("ok", 1), ("ok", 2)]
    registry = ModelRegistry(tmp_path)
    assert [
        version.version
        for version in registry.list_versions(
            "shared",
            owner_user_id="alice",
        )
    ] == [1, 2]


def test_mutating_model_registry_methods_require_explicit_owner(tmp_path) -> None:
    registry = ModelRegistry(tmp_path)

    with pytest.raises(ValueError, match="owner_user_id is required"):
        registry.register_version("shared")

    version = registry.register_version("shared", owner_user_id="alice")
    with pytest.raises(ValueError, match="owner_user_id is required"):
        registry.apply_stage("shared", version.version, "archived")
    with pytest.raises(ValueError, match="owner_user_id is required"):
        registry.promote("shared", version.version, "archived")


def test_legacy_ownerless_rows_are_quarantined_and_never_authorize(tmp_path) -> None:
    path = tmp_path / "models.jsonl"
    path.write_text(
        json.dumps(
            {
                "model_id": "legacy",
                "version": 99,
                "stage": "production",
                "created_at_utc": "2025-01-01T00:00:00+00:00",
                "artifact_path": "legacy.pkl",
            }
        )
        + "\n",
        encoding="utf-8",
    )

    registry = ModelRegistry(tmp_path)

    assert registry.legacy_quarantined_count == 1
    assert registry.list_versions("legacy", owner_user_id="alice") == []
    assert registry.list_versions("legacy") == []
    assert registry.list_models(owner_user_id="alice") == []


def test_schema_v2_owner_asset_mismatch_fails_closed(tmp_path) -> None:
    registry = ModelRegistry(tmp_path)
    registry.register_version("shared", owner_user_id="alice")
    path = tmp_path / "models.jsonl"
    row = json.loads(path.read_text(encoding="utf-8").splitlines()[0])
    row["model_asset_ref"] = "model_asset_forged"
    path.write_text(json.dumps(row) + "\n", encoding="utf-8")

    reloaded = ModelRegistry(tmp_path)
    with pytest.raises(
        ValueError,
        match="invalid persisted owner-scoped model version row",
    ):
        reloaded.list_versions("shared", owner_user_id="alice")


def test_training_service_rejects_mismatched_model_governance_registry(tmp_path) -> None:
    attached = PersistentModelGovernanceRegistry(tmp_path / "attached.jsonl")
    supplied = PersistentModelGovernanceRegistry(tmp_path / "supplied.jsonl")
    models = ModelRegistry(
        tmp_path / "experiments",
        model_governance_registry=attached,
    )

    with pytest.raises(ValueError, match="must share identity"):
        TrainingService(
            tmp_path / "training_runs",
            model_registry=models,
            model_governance_registry=supplied,
        )


def test_promotion_and_approval_cannot_cross_owner_boundaries(tmp_path) -> None:
    governance = PersistentModelGovernanceRegistry(
        tmp_path / "model_governance.jsonl"
    )
    approval = _approval_service(tmp_path)
    models = ModelRegistry(
        tmp_path / "experiments",
        gate_service=approval,
        model_governance_registry=governance,
    )
    passports = {}
    for owner in ("alice", "bob"):
        passports[owner] = governance.record_passport(
            _passport(owner),
            owner_user_id=owner,
            recorded_by=owner,
        )
    with pytest.raises(ValueError, match="not recorded for owner=alice"):
        models.register_version(
            "shared",
            artifact_path="forged-cross-owner.safetensors",
            model_passport_ref=passports["bob"].passport_id,
            validation_dossier_ref=passports["bob"].validation_dossier_ref,
            owner_user_id="alice",
        )
    for owner in ("alice", "bob"):
        models.register_version(
            "shared",
            artifact_path=f"{owner}-v1.safetensors",
            model_passport_ref=passports[owner].passport_id,
            validation_dossier_ref=passports[owner].validation_dossier_ref,
            owner_user_id=owner,
        )

    with pytest.raises(GateStateError, match="owner=alice"):
        models.promote(
            "shared",
            1,
            "production",
            created_by="alice-creator",
            verification_record_id="verdict:owner-v2",
            evidence=_evidence(),
            strategy_goal_ref="goal:owner-v2",
            model_passport_ref=passports["bob"].passport_id,
            owner_user_id="alice",
        )

    gate = models.promote(
        "shared",
        1,
        "production",
        created_by="alice-creator",
        verification_record_id="verdict:owner-v2",
        evidence=_evidence(),
        strategy_goal_ref="goal:owner-v2",
        model_passport_ref=passports["alice"].passport_id,
        owner_user_id="alice",
    )
    assert gate.decision == "pending"
    assert gate.evidence["owner_user_id"] == "alice"
    assert gate.evidence["logical_model_id"] == "shared"
    assert models.promotion_gate(
        gate.gate_id,
        owner_user_id="alice",
    ).gate_id == gate.gate_id

    with pytest.raises(GateStateError, match="model asset does not match"):
        models.promotion_gate(gate.gate_id, owner_user_id="bob")
    with pytest.raises(GateStateError, match="model asset does not match"):
        models.approve_promotion(
            gate.gate_id,
            model_id="shared",
            owner_user_id="bob",
            approver="bob-reviewer",
            reason="independent owner review confirms evidence and scope",
        )
    with pytest.raises(GateStateError, match="model asset does not match"):
        models.reject_promotion(
            gate.gate_id,
            model_id="shared",
            owner_user_id="bob",
            approver="bob-reviewer",
            reason="wrong owner must not reject this gate",
        )
    assert approval._store.get(gate.gate_id).decision == "pending"

    approved = models.approve_promotion(
        gate.gate_id,
        model_id="shared",
        owner_user_id="alice",
        approver="alice-reviewer",
        reason="independent owner review confirms evidence and scope",
    )

    assert approved.decision == "approved"
    assert models.list_versions("shared", owner_user_id="alice")[0].stage == "production"
    assert models.list_versions("shared", owner_user_id="bob")[0].stage == "dev"
