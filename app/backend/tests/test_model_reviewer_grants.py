"""Adversarial tests for exact-gate model reviewer authorization."""

from __future__ import annotations

import json
import multiprocessing as mp
import threading
from datetime import UTC, datetime, timedelta
from pathlib import Path
import pytest

from app.approval import (
    ApprovalGateService,
    ApprovalGateStore,
    ApproverEqualsCreator,
    GateStateError,
)
from app.experiments import (
    PersistentModelReviewerGrantRegistry,
    ReviewerGrantAuthorizationError,
    ReviewerGrantError,
)
from app.experiments.store import ModelRegistry
from app.lineage.ledger import Ledger
from app.research_os import (
    ModelArtifactFormat,
    ModelArtifactManifestEntry,
    ModelArtifactSource,
    ModelGovernancePassport,
    ModelRiskTier,
    PersistentModelGovernanceRegistry,
    RecertificationTrigger,
    SafeLoadingPolicy,
)
from app.training import TrainingJob, TrainingRequest


_GATE_ID = "gate-exact-review"
_OWNER = "owner-alice"
_MODEL = "alpha"
_ASSET = "model-asset-alpha"
_REVIEWER = "reviewer-bob"


def _future(hours: int = 1) -> str:
    return (datetime.now(UTC) + timedelta(hours=hours)).isoformat()


def _issue_direct(
    registry: PersistentModelReviewerGrantRegistry,
    *,
    reviewer: str = _REVIEWER,
    permissions=("view", "approve", "reject"),
):
    return registry.issue_grant(
        gate_id=_GATE_ID,
        owner_user_id=_OWNER,
        model_id=_MODEL,
        model_asset_ref=_ASSET,
        model_version=1,
        reviewer_user_id=reviewer,
        permissions=permissions,
        expires_at_utc=_future(),
        issued_by=_OWNER,
    )


def _concurrent_issue_same_grant(
    path: str,
    ready,
    start,
    results,
) -> None:
    registry = PersistentModelReviewerGrantRegistry(Path(path))
    ready.put(True)
    if not start.wait(timeout=10):
        results.put(("error", "start timeout"))
        return
    try:
        grant = _issue_direct(registry)
    except Exception as exc:  # noqa: BLE001 - subprocess returns exact outcome.
        results.put(("error", type(exc).__name__))
    else:
        results.put(("ok", grant.revision))


def _evidence() -> dict:
    return {
        "config_hash": "cfg_reviewer_grant_v2",
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


def _open_gate(
    tmp_path: Path,
    *,
    owner: str = _OWNER,
    created_by: str | None = None,
) -> tuple[ModelRegistry, object]:
    approval = ApprovalGateService(
        ApprovalGateStore(tmp_path / "approval_gates"),
        ledger=Ledger(tmp_path / "ledger"),
    )
    governance = PersistentModelGovernanceRegistry(
        tmp_path / "model_governance.jsonl"
    )
    models = ModelRegistry(
        tmp_path / "experiments",
        gate_service=approval,
        model_governance_registry=governance,
    )
    job_id = f"reviewer-grant:{owner}"
    request = TrainingRequest(
        name="reviewer-grant",
        model=_MODEL,
        task="regression",
        feature_cols=["feature:reviewer-grant"],
        label_col="label:reviewer-grant",
        asset_class="a_share",
    )
    passport = governance.record_passport(
        ModelGovernancePassport(
            model_version_ref=f"model_version:{_MODEL}:v1",
            model_type_card_ref=f"model_type_card:{_MODEL}",
            training_plan_ref=f"training_plan:{job_id}",
            training_run_ref=f"training_run:{job_id}",
            model_risk_tier=ModelRiskTier.MEDIUM,
            materiality="reviewer grant authorization fixture",
            intended_use=("reviewer authorization test",),
            prohibited_use=("direct live order placement",),
            dataset_refs=("dataset:reviewer-grant",),
            feature_refs=tuple(request.feature_cols),
            label_refs=(request.label_col,),
            training_code_hash="sha256:reviewer-grant-code",
            artifact_manifest=(
                ModelArtifactManifestEntry(
                    artifact_ref="artifact:reviewer-grant",
                    uri="registry://models/alpha/v1/model.safetensors",
                    artifact_format=ModelArtifactFormat.SAFE_TENSORS,
                    source=ModelArtifactSource.PROJECT_PRODUCED,
                    content_hash="sha256:reviewer-grant-artifact",
                    producer_run_ref=f"training_run:{job_id}",
                    sandbox_inspection_ref="inspection:reviewer-grant",
                ),
            ),
            safe_loading_policy=SafeLoadingPolicy(
                sandboxed_load_inspect=True,
                prefer_safe_tensors=True,
                torch_weights_only=True,
            ),
            vendor_dependency_refs=("none",),
            foundation_model_dependency_refs=("none",),
            monitoring_requirements=("performance degradation monitor",),
            recertification_triggers=tuple(RecertificationTrigger),
            validation_dossier_ref=f"dossier:{owner}",
            challenger_result="not required for medium risk",
        ),
        owner_user_id=owner,
        recorded_by=owner,
    )
    models._model_recertification_training_jobs.create(
        TrainingJob(
            job_id=job_id,
            name=request.name,
            model=_MODEL,
            family="ml",
            task=request.task,
            owner_user_id=owner,
            status="succeeded",
            request=request.to_dict(),
            run_id=job_id,
            model_version=1,
            model_passport_ref=passport.passport_id,
            validation_dossier_ref=passport.validation_dossier_ref,
        )
    )
    passport_ref = passport.passport_id
    models.register_version(
        _MODEL,
        model_passport_ref=passport_ref,
        validation_dossier_ref=f"dossier:{owner}",
        owner_user_id=owner,
    )
    gate = models.promote(
        _MODEL,
        1,
        "production",
        created_by=created_by or owner,
        verification_record_id="verdict:reviewer-grant",
        evidence=_evidence(),
        strategy_goal_ref="goal:reviewer-grant",
        model_passport_ref=passport_ref,
        owner_user_id=owner,
    )
    assert gate.decision == "pending"
    return models, gate


def test_grant_is_exact_owner_gate_model_version_reviewer_and_permission(tmp_path) -> None:
    registry = PersistentModelReviewerGrantRegistry(tmp_path / "grants.jsonl")
    grant = _issue_direct(registry, permissions=("view",))

    assert grant.schema_version == 2
    assert grant.owner_user_id == _OWNER
    assert grant.gate_id == _GATE_ID
    assert grant.model_id == _MODEL
    assert grant.model_asset_ref == _ASSET
    assert grant.model_version == 1
    assert grant.reviewer_user_id == _REVIEWER
    assert grant.permissions == ("view",)
    assert grant.revision == 1
    assert grant.previous_record_hash == ""
    assert grant.record_hash.startswith("model_reviewer_grant_")

    assert registry.authorize(
        gate_id=_GATE_ID,
        owner_user_id=_OWNER,
        model_id=_MODEL,
        model_asset_ref=_ASSET,
        model_version=1,
        reviewer_user_id=_REVIEWER,
        permission="view",
    ).grant_id == grant.grant_id

    mismatches = (
        {"gate_id": "wrong-gate"},
        {"owner_user_id": "wrong-owner"},
        {"model_id": "wrong-model"},
        {"model_asset_ref": "wrong-asset"},
        {"model_version": 2},
        {"reviewer_user_id": "wrong-reviewer"},
        {"permission": "approve"},
    )
    base = {
        "gate_id": _GATE_ID,
        "owner_user_id": _OWNER,
        "model_id": _MODEL,
        "model_asset_ref": _ASSET,
        "model_version": 1,
        "reviewer_user_id": _REVIEWER,
        "permission": "view",
    }
    for mismatch in mismatches:
        with pytest.raises(
            ReviewerGrantAuthorizationError,
            match="not found or reviewer not authorized",
        ):
            registry.authorize(**{**base, **mismatch})


def test_permissions_are_a_strict_nonempty_subset(tmp_path) -> None:
    registry = PersistentModelReviewerGrantRegistry(tmp_path / "grants.jsonl")

    for invalid in ((), ("view", "admin"), "view"):
        with pytest.raises(ReviewerGrantError, match="permissions"):
            _issue_direct(registry, permissions=invalid)


def test_only_exact_owner_can_issue_or_revoke_and_reviewer_must_differ(tmp_path) -> None:
    registry = PersistentModelReviewerGrantRegistry(tmp_path / "grants.jsonl")
    with pytest.raises(ReviewerGrantError, match="exact owner"):
        registry.issue_grant(
            gate_id=_GATE_ID,
            owner_user_id=_OWNER,
            model_id=_MODEL,
            model_asset_ref=_ASSET,
            model_version=1,
            reviewer_user_id=_REVIEWER,
            permissions=("view",),
            expires_at_utc=_future(),
            issued_by="mallory",
        )
    with pytest.raises(ReviewerGrantError, match="differ from owner"):
        registry.issue_grant(
            gate_id=_GATE_ID,
            owner_user_id=_OWNER,
            model_id=_MODEL,
            model_asset_ref=_ASSET,
            model_version=1,
            reviewer_user_id=" OWNER-ALICE ",
            permissions=("view",),
            expires_at_utc=_future(),
            issued_by=_OWNER,
        )

    grant = _issue_direct(registry)
    with pytest.raises(ReviewerGrantError, match="exact owner"):
        registry.revoke_grant(
            grant.grant_id,
            owner_user_id=_OWNER,
            revoked_by="mallory",
            expected_record_hash=grant.record_hash,
        )


def test_revoked_and_expired_grants_never_authorize_after_restart(tmp_path) -> None:
    path = tmp_path / "grants.jsonl"
    registry = PersistentModelReviewerGrantRegistry(path)
    grant = _issue_direct(registry)
    revoked = registry.revoke_grant(
        grant.grant_id,
        owner_user_id=_OWNER,
        revoked_by=_OWNER,
        expected_record_hash=grant.record_hash,
    )
    assert revoked.status == "revoked"
    assert revoked.revision == 2
    assert revoked.previous_record_hash == grant.record_hash

    reloaded = PersistentModelReviewerGrantRegistry(path)
    assert reloaded.get_for_owner(
        grant.grant_id,
        owner_user_id=_OWNER,
    ).status == "revoked"
    with pytest.raises(ReviewerGrantAuthorizationError):
        reloaded.authorize(
            gate_id=_GATE_ID,
            owner_user_id=_OWNER,
            model_id=_MODEL,
            model_asset_ref=_ASSET,
            model_version=1,
            reviewer_user_id=_REVIEWER,
            permission="approve",
        )
    with pytest.raises(ReviewerGrantError, match="cannot be reissued"):
        _issue_direct(reloaded)

    expiring = PersistentModelReviewerGrantRegistry(tmp_path / "expiring.jsonl")
    current = _issue_direct(expiring)
    with pytest.raises(ReviewerGrantAuthorizationError):
        expiring.authorize(
            gate_id=_GATE_ID,
            owner_user_id=_OWNER,
            model_id=_MODEL,
            model_asset_ref=_ASSET,
            model_version=1,
            reviewer_user_id=_REVIEWER,
            permission="view",
            now_utc=datetime.fromisoformat(current.expires_at_utc)
            + timedelta(seconds=1),
        )


def test_revision_updates_require_current_hash_and_reject_stale_cas(tmp_path) -> None:
    registry = PersistentModelReviewerGrantRegistry(tmp_path / "grants.jsonl")
    grant = _issue_direct(registry, permissions=("view",))
    with pytest.raises(ReviewerGrantError, match="expected_record_hash is stale"):
        registry.issue_grant(
            gate_id=_GATE_ID,
            owner_user_id=_OWNER,
            model_id=_MODEL,
            model_asset_ref=_ASSET,
            model_version=1,
            reviewer_user_id=_REVIEWER,
            permissions=("view", "approve"),
            expires_at_utc=_future(2),
            issued_by=_OWNER,
            expected_record_hash="stale",
        )
    updated = registry.issue_grant(
        gate_id=_GATE_ID,
        owner_user_id=_OWNER,
        model_id=_MODEL,
        model_asset_ref=_ASSET,
        model_version=1,
        reviewer_user_id=_REVIEWER,
        permissions=("view", "approve"),
        expires_at_utc=_future(2),
        issued_by=_OWNER,
        expected_record_hash=grant.record_hash,
    )
    assert updated.revision == 2
    assert updated.previous_record_hash == grant.record_hash


def test_legacy_rows_quarantine_but_schema_v2_corruption_fails_closed(tmp_path) -> None:
    path = tmp_path / "grants.jsonl"
    path.write_text(json.dumps({"schema_version": 1, "gate_id": "legacy"}) + "\n")
    registry = PersistentModelReviewerGrantRegistry(path)
    assert registry.legacy_quarantined_count == 1

    row = _issue_direct(registry).to_dict()
    row["permissions"] = ["view", "admin"]
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(row) + "\n")
    with pytest.raises(ReviewerGrantError, match="invalid persisted reviewer grant row"):
        PersistentModelReviewerGrantRegistry(path)


def test_concurrent_same_grant_issue_serializes_without_fork(tmp_path) -> None:
    path = tmp_path / "grants.jsonl"
    context = mp.get_context("spawn")
    ready = context.Queue()
    start = context.Event()
    results = context.Queue()
    processes = [
        context.Process(
            target=_concurrent_issue_same_grant,
            args=(str(path), ready, start, results),
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

    assert sorted(outcomes) == [
        ("error", "ReviewerGrantError"),
        ("ok", 1),
    ]
    reloaded = PersistentModelReviewerGrantRegistry(path)
    assert reloaded.authorize(
        gate_id=_GATE_ID,
        owner_user_id=_OWNER,
        model_id=_MODEL,
        model_asset_ref=_ASSET,
        model_version=1,
        reviewer_user_id=_REVIEWER,
        permission="approve",
    ).revision == 1


def test_model_registry_reviewer_view_and_approve_require_exact_live_grant(tmp_path) -> None:
    models, gate = _open_gate(tmp_path)
    with pytest.raises(GateStateError) as missing:
        models.promotion_gate_for_reviewer(
            "missing-gate",
            reviewer_user_id=_REVIEWER,
        )
    with pytest.raises(GateStateError) as unauthorized:
        models.promotion_gate_for_reviewer(
            gate.gate_id,
            reviewer_user_id=_REVIEWER,
        )
    assert str(missing.value) == str(unauthorized.value)
    assert str(missing.value) == "promotion gate not found or reviewer not authorized"

    grant = models.grant_promotion_reviewer(
        gate.gate_id,
        model_id=_MODEL,
        owner_user_id=_OWNER,
        reviewer_user_id=_REVIEWER,
        permissions=("view", "approve"),
        expires_at_utc=_future(),
        issued_by=_OWNER,
    )
    assert grant.model_asset_ref == gate.model_id
    assert models.promotion_gate_for_reviewer(
        gate.gate_id,
        reviewer_user_id=_REVIEWER,
    ).gate_id == gate.gate_id
    with pytest.raises(
        GateStateError,
        match="not found or reviewer not authorized",
    ):
        models.approve_promotion_as_reviewer(
            gate.gate_id,
            model_id="wrong-model",
            reviewer_user_id=_REVIEWER,
            reason="independent review checked the wrong model boundary",
        )

    approved = models.approve_promotion_as_reviewer(
        gate.gate_id,
        model_id=_MODEL,
        reviewer_user_id=_REVIEWER,
        reason="independent reviewer checked evidence, scope, and residual risk",
    )
    assert approved.decision == "approved"
    assert approved.approver == _REVIEWER
    assert models.list_versions(_MODEL, owner_user_id=_OWNER)[0].stage == "production"


def test_model_registry_rechecks_revocation_and_permissions_before_decision(tmp_path) -> None:
    models, gate = _open_gate(tmp_path)
    grant = models.grant_promotion_reviewer(
        gate.gate_id,
        model_id=_MODEL,
        owner_user_id=_OWNER,
        reviewer_user_id=_REVIEWER,
        permissions=("view", "reject"),
        expires_at_utc=_future(),
        issued_by=_OWNER,
    )
    with pytest.raises(GateStateError, match="not found or reviewer not authorized"):
        models.approve_promotion_as_reviewer(
            gate.gate_id,
            model_id=_MODEL,
            reviewer_user_id=_REVIEWER,
            reason="view and reject do not imply approve permission",
        )

    models.revoke_promotion_reviewer(
        grant.grant_id,
        owner_user_id=_OWNER,
        revoked_by=_OWNER,
        expected_record_hash=grant.record_hash,
    )
    with pytest.raises(GateStateError, match="not found or reviewer not authorized"):
        models.reject_promotion_as_reviewer(
            gate.gate_id,
            model_id=_MODEL,
            reviewer_user_id=_REVIEWER,
            reason="revoked reviewer must not reject",
        )
    assert gate.decision == "pending"


def test_reviewer_decision_and_owner_revocation_have_one_serial_order(tmp_path) -> None:
    models, gate = _open_gate(tmp_path)
    grant = models.grant_promotion_reviewer(
        gate.gate_id,
        model_id=_MODEL,
        owner_user_id=_OWNER,
        reviewer_user_id=_REVIEWER,
        permissions=("approve",),
        expires_at_utc=_future(),
        issued_by=_OWNER,
    )
    decision_entered = threading.Event()
    release_decision = threading.Event()
    revocation_started = threading.Event()
    outcomes: dict[str, object] = {}
    approval_service = models._gate_service
    original_approve = approval_service.approve

    def held_approve(*args, **kwargs):
        decision_entered.set()
        assert release_decision.wait(timeout=5)
        return original_approve(*args, **kwargs)

    approval_service.approve = held_approve

    def approve() -> None:
        outcomes["approval"] = models.approve_promotion_as_reviewer(
            gate.gate_id,
            model_id=_MODEL,
            reviewer_user_id=_REVIEWER,
            reason="serialized independent review approves after checking evidence",
        )

    def revoke() -> None:
        revocation_started.set()
        outcomes["revocation"] = models.revoke_promotion_reviewer(
            grant.grant_id,
            owner_user_id=_OWNER,
            revoked_by=_OWNER,
            expected_record_hash=grant.record_hash,
        )

    approve_thread = threading.Thread(target=approve)
    revoke_thread = threading.Thread(target=revoke)
    approve_thread.start()
    assert decision_entered.wait(timeout=5)
    revoke_thread.start()
    assert revocation_started.wait(timeout=5)
    revoke_thread.join(timeout=0.1)
    assert revoke_thread.is_alive(), "revocation must wait for the authorized decision"
    release_decision.set()
    approve_thread.join(timeout=5)
    revoke_thread.join(timeout=5)

    assert not approve_thread.is_alive()
    assert not revoke_thread.is_alive()
    assert outcomes["approval"].decision == "approved"
    assert outcomes["revocation"].status == "revoked"
    assert models.list_versions(_MODEL, owner_user_id=_OWNER)[0].stage == "production"


def test_approval_gate_still_enforces_reviewer_differs_from_creator(tmp_path) -> None:
    models, gate = _open_gate(tmp_path, created_by=_REVIEWER)
    models.grant_promotion_reviewer(
        gate.gate_id,
        model_id=_MODEL,
        owner_user_id=_OWNER,
        reviewer_user_id=_REVIEWER,
        permissions=("approve",),
        expires_at_utc=_future(),
        issued_by=_OWNER,
    )

    with pytest.raises(ApproverEqualsCreator):
        models.approve_promotion_as_reviewer(
            gate.gate_id,
            model_id=_MODEL,
            reviewer_user_id=_REVIEWER,
            reason="grant authorization cannot bypass creator separation",
        )
    assert models.list_versions(_MODEL, owner_user_id=_OWNER)[0].stage == "dev"


def test_model_registry_owner_actor_mismatch_and_cross_owner_grant_fail(tmp_path) -> None:
    models, gate = _open_gate(tmp_path)
    with pytest.raises(ReviewerGrantError, match="exact owner"):
        models.grant_promotion_reviewer(
            gate.gate_id,
            model_id=_MODEL,
            owner_user_id=_OWNER,
            reviewer_user_id=_REVIEWER,
            permissions=("view",),
            expires_at_utc=_future(),
            issued_by="mallory",
        )
    with pytest.raises(GateStateError, match="model asset does not match"):
        models.grant_promotion_reviewer(
            gate.gate_id,
            model_id=_MODEL,
            owner_user_id="owner-bob",
            reviewer_user_id=_REVIEWER,
            permissions=("view",),
            expires_at_utc=_future(),
            issued_by="owner-bob",
        )
