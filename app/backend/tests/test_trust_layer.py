from __future__ import annotations

import base64
import json
from types import SimpleNamespace

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fastapi.testclient import TestClient

from app import main
from app.auth import require_user_dependency
from app.research_os import (
    ExternalExpertReviewRecord,
    ExternalReviewerIdentityRecord,
    FunctionalIndependenceDisclosure,
    PersistentExternalExpertSignatureRegistry,
    PersistentTrustDisclosureRegistry,
    PersistentTrustPressureRunRegistry,
    PersistentTrustReleaseApprovalRegistry,
    PersistentTrustReleaseCheckRegistry,
    PersistentTrustReleaseGateRegistry,
    TrustClaimLabel,
    TrustClaimRecord,
    TrustPressureRunRecord,
    TrustReleaseApprovalRecord,
    TrustReleaseCheckRecord,
    TrustReleaseGateRecord,
    UserAutonomyRecord,
    external_expert_review_signature_payload,
    record_external_expert_review,
    record_trust_pressure_run,
    record_trust_release_approval,
    record_trust_release_check,
    record_trust_release_check_suite,
    validate_external_expert_review,
    validate_external_expert_signature,
    validate_external_reviewer_identity,
    validate_functional_independence,
    validate_trust_claim,
    validate_trust_layer,
    validate_trust_pressure_run,
    validate_trust_release_approval,
    validate_trust_release_check,
    validate_trust_release_gate,
    validate_user_autonomy,
)


def _codes(decision) -> set[str]:
    return {violation.code for violation in decision.violations}


def _claim(**overrides) -> TrustClaimRecord:
    data = {
        "claim_ref": "claim:psr_sufficient",
        "claim_label": TrustClaimLabel.EVIDENCE_SUFFICIENT,
        "evidence_refs": ("validation_dossier:001",),
        "weakness_refs": ("weakness:borrow_cost_sensitivity",),
        "weakness_visible_by_default": True,
    }
    data.update(overrides)
    return TrustClaimRecord(**data)


def _single_user_disclosure(**overrides) -> FunctionalIndependenceDisclosure:
    data = {
        "disclosure_ref": "independence:single_user:001",
        "mode": "single_user",
        "claims_organizational_independence": False,
        "isolated_validation_ref": "validation:isolated:001",
        "immutable_evidence_ref": "artifact_hash:rdp:001",
        "second_confirmation_ref": "confirmation:user:001",
        "alternate_model_verification_ref": "llm_call:critic:001",
    }
    data.update(overrides)
    return FunctionalIndependenceDisclosure(**data)


def _expert_review(**overrides) -> ExternalExpertReviewRecord:
    data = {
        "review_ref": "expert_review:release:v1",
        "release_ref": "release:v1",
        "reviewer_ref": "expert:independent_quant_reviewer",
        "reviewer_independence_ref": "independence:expert:001",
        "artifact_ref": "rdp_package:release:v1",
        "review_protocol_ref": "protocol:trust_release_review:v1",
        "verdict": "approved",
        "source_hash": "sha256:expert-review",
        "evidence_refs": ("evidence:expert-notes",),
        "veto_reason_refs": (),
        "signed_attestation_ref": "attestation:expert-signature:001",
    }
    data.update(overrides)
    return ExternalExpertReviewRecord(**data)


def _user_choice(**overrides) -> UserAutonomyRecord:
    data = {
        "choice_ref": "choice:methodology:001",
        "agent_recommendation_ref": "recommendation:strict_path",
        "tradeoff_refs": ("tradeoff:longer_validation",),
        "alternative_path_refs": ("path:exploratory", "path:strict"),
        "responsibility_boundary_ref": "responsibility:user_waived_theory",
        "user_final_choice_ref": "user_choice:exploratory",
    }
    data.update(overrides)
    return UserAutonomyRecord(**data)


def _release_gate(**overrides) -> TrustReleaseGateRecord:
    data = {
        "release_ref": "release:v1",
        "anti_flattery_pressure_test_ref": "trust_test:anti_flattery",
        "multi_turn_pressure_test_ref": "trust_test:multi_turn",
        "expert_veto_ref": "expert_veto:001",
        "weakness_collapse_check_ref": "weakness_check:001",
        "mock_honesty_check_ref": "mock_check:001",
        "cold_start_honesty_check_ref": "cold_start_check:001",
    }
    data.update(overrides)
    return TrustReleaseGateRecord(**data)


def _release_check(**overrides) -> TrustReleaseCheckRecord:
    data = {
        "check_ref": "trust_test:anti_flattery:001",
        "release_ref": "release:v1",
        "check_kind": "anti_flattery_pressure_test",
        "scenario_ref": "scenario:pushy_green_request",
        "expected_behavior_ref": "behavior:refuse_unearned_green",
        "observed_behavior_ref": "behavior:refuse_unearned_green",
        "verdict": "passed",
        "source_hash": "sha256:trust-check",
        "evidence_refs": ("evidence:trust-check",),
        "validation_result_refs": ("pytest:trust-check",),
    }
    data.update(overrides)
    return TrustReleaseCheckRecord(**data)


def _release_suite_checks(**overrides_by_kind) -> list[dict]:
    base = {
        "anti_flattery_pressure_test": {
            "scenario_ref": "scenario:pushy_green_request",
            "expected_behavior_ref": "behavior:refuse_unearned_green",
            "observed_behavior_ref": "behavior:refuse_unearned_green",
            "evidence_refs": ["evidence:anti-flattery"],
            "validation_result_refs": ["pytest:anti-flattery"],
        },
        "multi_turn_pressure_test": {
            "scenario_ref": "scenario:multi_turn_overclaim",
            "expected_behavior_ref": "behavior:keep_uncertainty_visible",
            "observed_behavior_ref": "behavior:keep_uncertainty_visible",
            "evidence_refs": ["evidence:multi-turn"],
            "validation_result_refs": ["pytest:multi-turn"],
        },
        "expert_veto": {
            "scenario_ref": "scenario:critic_veto",
            "expected_behavior_ref": "behavior:block_release",
            "observed_behavior_ref": "behavior:block_release",
            "evidence_refs": ["evidence:expert-veto"],
            "validation_result_refs": ["pytest:expert-veto"],
        },
        "weakness_collapse_check": {
            "scenario_ref": "scenario:weakness_hidden",
            "expected_behavior_ref": "behavior:keep_weakness_visible",
            "observed_behavior_ref": "behavior:keep_weakness_visible",
            "evidence_refs": ["evidence:weakness"],
            "validation_result_refs": ["pytest:weakness"],
        },
        "mock_honesty_check": {
            "scenario_ref": "scenario:mock_boundary",
            "expected_behavior_ref": "behavior:show_mock_boundary",
            "observed_behavior_ref": "behavior:show_mock_boundary",
            "evidence_refs": ["evidence:mock-honesty"],
            "validation_result_refs": ["pytest:mock-honesty"],
        },
        "cold_start_honesty_check": {
            "scenario_ref": "scenario:cold_start_n1",
            "expected_behavior_ref": "behavior:label_prior_assertion",
            "observed_behavior_ref": "behavior:label_prior_assertion",
            "evidence_refs": ["evidence:cold-start"],
            "validation_result_refs": ["pytest:cold-start"],
        },
    }
    checks: list[dict] = []
    for kind, values in base.items():
        row = {"check_kind": kind, **values}
        row.update(overrides_by_kind.get(kind, {}))
        checks.append(row)
    return checks


def _pressure_run(**overrides) -> TrustPressureRunRecord:
    data = {
        "runner_ref": "trust_pressure_run:release:v1",
        "release_ref": "release:v1",
        "runner_mode": "local_deterministic",
        "source_hash": "sha256:pressure-run",
        "release_gate_ref": "release:v1",
        "check_refs": (
            "trust_test:anti_flattery:001",
            "trust_test:multi_turn:001",
            "expert_veto:001",
            "weakness_check:001",
            "mock_check:001",
            "cold_start_check:001",
        ),
        "scenario_refs": tuple(f"scenario:{row['check_kind']}" for row in _release_suite_checks()),
        "evidence_refs": ("evidence:pressure-run",),
        "validation_result_refs": ("pytest:pressure-run",),
    }
    data.update(overrides)
    return TrustPressureRunRecord(**data)


def _release_approval(**overrides) -> TrustReleaseApprovalRecord:
    data = {
        "approval_ref": "trust_release_approval:release:v1",
        "release_ref": "release:v1",
        "release_gate_ref": "release:v1",
        "pressure_run_ref": "trust_pressure_run:release:v1",
        "expert_review_ref": "expert_review:release:v1",
        "artifact_ref": "rdp_package:release:v1",
        "approval_protocol_ref": "protocol:release-approval:v1",
        "verdict": "approved",
        "source_hash": "sha256:release-approval",
        "evidence_refs": ("evidence:release-approval",),
        "signed_approval_ref": "attestation:release-approval:001",
    }
    data.update(overrides)
    return TrustReleaseApprovalRecord(**data)


def _payload(record) -> dict:
    return record.__dict__.copy()


def _expert_identity(private_key=None, **overrides) -> tuple[ExternalReviewerIdentityRecord, Ed25519PrivateKey]:
    key = private_key or Ed25519PrivateKey.generate()
    public_key_pem = key.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    ).decode("utf-8")
    data = {
        "identity_ref": "expert_identity:independent_quant_reviewer",
        "reviewer_ref": "expert:independent_quant_reviewer",
        "identity_provider_ref": "identity_provider:manual-public-key",
        "public_key_ref": "public_key:independent_quant_reviewer:v1",
        "public_key_pem": public_key_pem,
        "reviewer_independence_ref": "independence:expert:001",
        "evidence_refs": ("identity:evidence:001",),
    }
    data.update(overrides)
    return ExternalReviewerIdentityRecord(**data), key


def _client_with_trust_store(tmp_path, monkeypatch):
    disclosure_store = PersistentTrustDisclosureRegistry(tmp_path / "trust_disclosures.jsonl")
    store = PersistentTrustReleaseGateRegistry(tmp_path / "trust_release_gates.jsonl")
    check_store = PersistentTrustReleaseCheckRegistry(tmp_path / "trust_release_checks.jsonl")
    pressure_store = PersistentTrustPressureRunRegistry(tmp_path / "trust_pressure_runs.jsonl")
    approval_store = PersistentTrustReleaseApprovalRegistry(tmp_path / "trust_release_approvals.jsonl")
    signature_store = PersistentExternalExpertSignatureRegistry(tmp_path / "trust_expert_signatures.jsonl")
    monkeypatch.setattr(main, "TRUST_DISCLOSURE_REGISTRY", disclosure_store)
    monkeypatch.setattr(main, "TRUST_RELEASE_GATE_REGISTRY", store)
    monkeypatch.setattr(main, "TRUST_RELEASE_CHECK_REGISTRY", check_store)
    monkeypatch.setattr(main, "TRUST_PRESSURE_RUN_REGISTRY", pressure_store)
    monkeypatch.setattr(main, "TRUST_RELEASE_APPROVAL_REGISTRY", approval_store)
    monkeypatch.setattr(main, "TRUST_EXPERT_SIGNATURE_REGISTRY", signature_store)
    main.app.dependency_overrides[require_user_dependency] = lambda: SimpleNamespace(
        username="u1",
        user_id="u1",
    )
    return TestClient(main.app), store, check_store, pressure_store, approval_store, disclosure_store


def _seed_release_approval_dependencies(
    *,
    owner_user_id: str = "u1",
    review: ExternalExpertReviewRecord | None = None,
    sign_review: bool = True,
):
    run, gate, checks = record_trust_pressure_run(
        release_ref="release:v1",
        runner_mode="local_deterministic",
        scenarios=_release_suite_checks(),
        evidence_refs=("evidence:pressure-run",),
        validation_result_refs=("pytest:pressure-run",),
        runner_ref="trust_pressure_run:release:v1",
    )
    for check in checks:
        main.TRUST_RELEASE_CHECK_REGISTRY.record_check(
            check, owner_user_id=owner_user_id
        )
    main.TRUST_RELEASE_GATE_REGISTRY.record_gate(gate, owner_user_id=owner_user_id)
    main.TRUST_PRESSURE_RUN_REGISTRY.record_run(run, owner_user_id=owner_user_id)
    expert_review = review or _expert_review()
    main.TRUST_DISCLOSURE_REGISTRY.record_external_expert_review(
        expert_review, owner_user_id=owner_user_id
    )
    signature = None
    if sign_review:
        identity, key = _expert_identity()
        main.TRUST_EXPERT_SIGNATURE_REGISTRY.record_identity(
            identity, owner_user_id=owner_user_id
        )
        signature = main.TRUST_EXPERT_SIGNATURE_REGISTRY.record_signature(
            review=expert_review,
            identity_ref=identity.identity_ref,
            signature_b64=base64.b64encode(
                key.sign(external_expert_review_signature_payload(expert_review))
            ).decode("ascii"),
            attestation_ref=expert_review.signed_attestation_ref,
            owner_user_id=owner_user_id,
        )
    return run, gate, checks, expert_review, signature


def test_strong_claim_requires_evidence():
    decision = validate_trust_claim(_claim(evidence_refs=()))
    assert not decision.accepted
    assert "strong_claim_without_evidence" in _codes(decision)


def test_agent_cannot_turn_wishful_pressure_into_strong_conclusion():
    decision = validate_trust_claim(_claim(pressure_context="user wishful thinking: make it green"))
    assert not decision.accepted
    assert "wishful_pressure_strong_conclusion" in _codes(decision)


def test_weaknesses_and_user_waivers_remain_visible_by_default():
    decision = validate_trust_claim(
        _claim(
            weakness_visible_by_default=False,
            user_waiver_ref="waiver:001",
            waiver_weakness_visible_by_default=False,
        )
    )
    assert not decision.accepted
    assert _codes(decision) >= {"weakness_hidden_by_default", "user_waived_weakness_hidden"}


def test_cold_start_n_one_cannot_be_packaged_as_statistical_evidence():
    decision = validate_trust_claim(_claim(cold_start_n=1))
    assert not decision.accepted
    assert "cold_start_packaged_as_statistical_evidence" in _codes(decision)


def test_single_user_mode_cannot_claim_organizational_independence():
    decision = validate_functional_independence(
        _single_user_disclosure(
            claims_organizational_independence=True,
            alternate_model_verification_ref=None,
        )
    )
    assert not decision.accepted
    assert _codes(decision) >= {
        "single_user_claimed_organizational_independence",
        "functional_independence_ref_missing",
    }


def test_organization_mode_requires_real_process_ref():
    decision = validate_functional_independence(
        FunctionalIndependenceDisclosure(
            disclosure_ref="independence:org:001",
            mode="organization",
            claims_organizational_independence=True,
            isolated_validation_ref="validation:001",
            immutable_evidence_ref="hash:001",
            second_confirmation_ref="confirmation:001",
            alternate_model_verification_ref="critic:001",
            organization_process_ref=None,
        )
    )
    assert not decision.accepted
    assert "organization_independence_process_missing" in _codes(decision)


def test_external_expert_review_requires_external_reviewer_attestation_and_evidence():
    decision = validate_external_expert_review(
        _expert_review(
            reviewer_ref="agent:critic",
            signed_attestation_ref=None,
            evidence_refs=(),
            silent_mock_fallback_used=True,
        )
    )
    assert not decision.accepted
    assert _codes(decision) >= {
        "external_expert_review_not_external",
        "external_expert_review_attestation_missing",
        "external_expert_review_evidence_missing",
        "external_expert_review_silent_mock_fallback",
    }


def test_external_expert_review_producer_hashes_refs_and_accepts_veto():
    record = record_external_expert_review(
        release_ref="release:v1",
        reviewer_ref="expert:independent_quant_reviewer",
        reviewer_independence_ref="independence:expert:001",
        artifact_ref="rdp_package:release:v1",
        review_protocol_ref="protocol:trust_release_review:v1",
        verdict="vetoed",
        evidence_refs=("evidence:expert-notes",),
        veto_reason_refs=("veto:overclaim",),
    )
    assert record.review_ref.startswith("expert_review:")
    assert record.source_hash
    assert validate_external_expert_review(record).accepted


def test_external_reviewer_identity_validates_ed25519_public_key_and_external_reviewer():
    identity, _key = _expert_identity()
    accepted = validate_external_reviewer_identity(identity)
    assert accepted.accepted

    bad_key = validate_external_reviewer_identity(_expert_identity(public_key_pem="not a pem")[0])
    assert not bad_key.accepted
    assert "external_reviewer_identity_bad_public_key" in _codes(bad_key)

    agent_identity = validate_external_reviewer_identity(_expert_identity(reviewer_ref="agent:critic")[0])
    assert not agent_identity.accepted
    assert "external_reviewer_identity_not_external" in _codes(agent_identity)


def test_external_expert_signature_verifies_review_payload_and_rejects_mismatch(tmp_path):
    review = _expert_review()
    identity, key = _expert_identity()
    signature_b64 = base64.b64encode(key.sign(external_expert_review_signature_payload(review))).decode("ascii")
    store = PersistentExternalExpertSignatureRegistry(tmp_path / "trust_expert_signatures.jsonl")
    store.record_identity(identity, owner_user_id="u1")

    record = store.record_signature(
        review=review,
        identity_ref=identity.identity_ref,
        signature_b64=signature_b64,
        attestation_ref=review.signed_attestation_ref,
        owner_user_id="u1",
    )
    assert record.verified_signature_ref.startswith("verified_signature:")
    assert record.verification_hash.startswith("sha16:")
    assert validate_external_expert_signature(record, review=review, identity=identity).accepted

    mismatched_review = _expert_review(review_ref="expert_review:release:v2", reviewer_ref="expert:other")
    decision = validate_external_expert_signature(record, review=mismatched_review, identity=identity)
    assert not decision.accepted
    assert "external_expert_signature_reviewer_mismatch" in _codes(decision)

    with pytest.raises(ValueError, match="external_expert_signature_invalid"):
        store.record_signature(
            review=review,
            identity_ref=identity.identity_ref,
            signature_b64=base64.b64encode(b"bad-signature").decode("ascii"),
            attestation_ref=review.signed_attestation_ref,
            owner_user_id="u1",
        )


def test_agent_cannot_make_user_methodology_or_risk_choice():
    decision = validate_user_autonomy(
        _user_choice(
            user_final_choice_ref=None,
            agent_made_final_choice=True,
            tradeoff_refs=(),
        )
    )
    assert not decision.accepted
    assert _codes(decision) >= {
        "agent_made_user_methodology_or_risk_choice",
        "user_autonomy_options_missing",
    }


def test_non_redline_user_acceptance_should_not_be_blocked():
    decision = validate_user_autonomy(
        _user_choice(system_blocked_after_user_acceptance=True, redline_refs=())
    )
    assert not decision.accepted
    assert "non_redline_user_acceptance_blocked" in _codes(decision)


def test_release_gate_requires_trust_pressure_and_honesty_checks():
    decision = validate_trust_release_gate(
        _release_gate(expert_veto_ref=None, cold_start_honesty_check_ref=None)
    )
    assert not decision.accepted
    assert "trust_release_gate_missing_check" in _codes(decision)


def test_release_check_producer_returns_release_gate_ref_prefixes_and_replays(tmp_path):
    record = record_trust_release_check(
        release_ref="release:v1",
        check_kind="mock_honesty_check",
        scenario_ref="scenario:mock_badge_removed",
        expected_behavior_ref="behavior:show_mock_boundary",
        observed_behavior_ref="behavior:show_mock_boundary",
        evidence_refs=("evidence:mock-honesty",),
        validation_result_refs=("pytest:trust-check",),
    )
    assert record.check_ref.startswith("mock_check:")
    assert record.source_hash
    assert validate_trust_release_check(record).accepted

    path = tmp_path / "trust_release_checks.jsonl"
    store = PersistentTrustReleaseCheckRegistry(path)
    store.record_check(record, owner_user_id="u1")

    reloaded = PersistentTrustReleaseCheckRegistry(path)
    assert reloaded.check(record.check_ref, owner_user_id="u1").check_kind == "mock_honesty_check"
    assert "raw_response" not in str(reloaded.check(record.check_ref, owner_user_id="u1").__dict__)


def test_release_check_rejects_unknown_kind_behavior_mismatch_and_silent_mock(tmp_path):
    assert "trust_release_check_unknown_kind" in _codes(
        validate_trust_release_check(_release_check(check_kind="not_a_release_check"))
    )
    assert "trust_release_check_behavior_mismatch" in _codes(
        validate_trust_release_check(_release_check(observed_behavior_ref="behavior:overclaim"))
    )

    store = PersistentTrustReleaseCheckRegistry(tmp_path / "trust_release_checks.jsonl")
    with pytest.raises(ValueError, match="trust_release_check_silent_mock_fallback"):
        store.record_check(_release_check(silent_mock_fallback_used=True), owner_user_id="u1")

    assert not store.path.exists()


def test_release_check_suite_builds_gate_from_all_six_checks():
    gate, checks = record_trust_release_check_suite(
        release_ref="release:v1",
        checks=_release_suite_checks(),
    )

    assert gate.release_ref == "release:v1"
    assert len(checks) == 6
    assert gate.anti_flattery_pressure_test_ref.startswith("trust_test:anti_flattery:")
    assert gate.multi_turn_pressure_test_ref.startswith("trust_test:multi_turn:")
    assert gate.expert_veto_ref.startswith("expert_veto:")
    assert gate.weakness_collapse_check_ref.startswith("weakness_check:")
    assert gate.mock_honesty_check_ref.startswith("mock_check:")
    assert gate.cold_start_honesty_check_ref.startswith("cold_start_check:")
    assert validate_trust_layer(release_gates=(gate,), release_checks=checks).accepted


def test_trust_pressure_run_builds_checks_gate_and_runner_record():
    run, gate, checks = record_trust_pressure_run(
        release_ref="release:v1",
        runner_mode="local_deterministic",
        scenarios=_release_suite_checks(),
        evidence_refs=("evidence:pressure-run",),
        validation_result_refs=("pytest:pressure-run",),
    )

    assert run.runner_ref.startswith("trust_pressure_run:")
    assert run.release_gate_ref == "release:v1"
    assert len(run.check_refs) == 6
    assert len(checks) == 6
    assert validate_trust_pressure_run(run).accepted
    assert validate_trust_layer(release_gates=(gate,), release_checks=checks, pressure_runs=(run,)).accepted


def test_trust_pressure_run_rejects_unsafe_mode_failed_scenario_and_silent_mock():
    assert "trust_pressure_run_unsafe_mode" in _codes(
        validate_trust_pressure_run(_pressure_run(runner_mode="production"))
    )
    assert "trust_pressure_run_failed_scenario" in _codes(
        validate_trust_pressure_run(_pressure_run(failed_scenario_refs=("scenario:overclaim",)))
    )
    assert "trust_pressure_run_silent_mock_fallback" in _codes(
        validate_trust_pressure_run(_pressure_run(silent_mock_fallback_used=True))
    )

    with pytest.raises(ValueError, match="trust_pressure_run_failed_scenario"):
        record_trust_pressure_run(
            release_ref="release:v1",
            runner_mode="local_deterministic",
            scenarios=_release_suite_checks(
                anti_flattery_pressure_test={"outcome_flags": ["overclaim"]}
            ),
            evidence_refs=("evidence:pressure-run",),
            validation_result_refs=("pytest:pressure-run",),
        )


def test_trust_release_approval_binds_gate_pressure_run_and_expert_review():
    approval = record_trust_release_approval(
        release_ref="release:v1",
        release_gate=_release_gate(),
        pressure_run=_pressure_run(),
        expert_review=_expert_review(),
        artifact_ref="rdp_package:release:v1",
        approval_protocol_ref="protocol:release-approval:v1",
        verdict="approved",
        evidence_refs=("evidence:release-approval",),
        signed_approval_ref="attestation:release-approval:001",
    )

    assert approval.approval_ref.startswith("trust_release_approval:")
    assert approval.release_gate_ref == "release:v1"
    assert approval.pressure_run_ref == "trust_pressure_run:release:v1"
    assert approval.expert_review_ref == "expert_review:release:v1"
    assert validate_trust_release_approval(approval).accepted
    assert validate_trust_layer(
        release_gates=(_release_gate(),),
        pressure_runs=(_pressure_run(),),
        expert_reviews=(_expert_review(),),
        release_approvals=(approval,),
    ).accepted


def test_trust_release_approval_rejects_missing_signature_blockers_mismatch_and_bad_expert():
    assert "trust_release_approval_signature_missing" in _codes(
        validate_trust_release_approval(_release_approval(signed_approval_ref=None))
    )
    assert "trust_release_approval_approved_with_blockers" in _codes(
        validate_trust_release_approval(_release_approval(residual_blocker_refs=("blocker:open-review",)))
    )
    assert "trust_release_approval_blocker_missing" in _codes(
        validate_trust_release_approval(_release_approval(verdict="needs_revision", signed_approval_ref=None))
    )

    with pytest.raises(ValueError, match="trust_release_approval_pressure_run_release_mismatch"):
        record_trust_release_approval(
            release_ref="release:v1",
            release_gate=_release_gate(),
            pressure_run=_pressure_run(release_ref="release:v2"),
            expert_review=_expert_review(),
            artifact_ref="rdp_package:release:v1",
            approval_protocol_ref="protocol:release-approval:v1",
            verdict="approved",
            evidence_refs=("evidence:release-approval",),
            signed_approval_ref="attestation:release-approval:001",
        )

    with pytest.raises(ValueError, match="trust_release_approval_expert_review_not_approved"):
        record_trust_release_approval(
            release_ref="release:v1",
            release_gate=_release_gate(),
            pressure_run=_pressure_run(),
            expert_review=_expert_review(verdict="needs_revision", veto_reason_refs=("reason:revise",), signed_attestation_ref=None),
            artifact_ref="rdp_package:release:v1",
            approval_protocol_ref="protocol:release-approval:v1",
            verdict="approved",
            evidence_refs=("evidence:release-approval",),
            signed_approval_ref="attestation:release-approval:001",
        )


def test_complete_trust_layer_contract_accepts_disclosed_delivery():
    decision = validate_trust_layer(
        claims=(_claim(),),
        independence_disclosures=(_single_user_disclosure(),),
        expert_reviews=(_expert_review(),),
        user_choices=(_user_choice(),),
        release_gates=(_release_gate(),),
        release_checks=(_release_check(),),
        pressure_runs=(_pressure_run(),),
        release_approvals=(_release_approval(),),
    )
    assert decision.accepted
    assert decision.violations == ()


def test_persistent_trust_disclosure_registry_replays_records(tmp_path):
    path = tmp_path / "trust_disclosures.jsonl"
    store = PersistentTrustDisclosureRegistry(path)
    store.record_claim(_claim(), owner_user_id="u1")
    store.record_independence_disclosure(_single_user_disclosure(), owner_user_id="u1")
    store.record_external_expert_review(_expert_review(), owner_user_id="u1")
    store.record_user_autonomy(_user_choice(), owner_user_id="u1")

    reloaded = PersistentTrustDisclosureRegistry(path)
    assert reloaded.claim("claim:psr_sufficient", owner_user_id="u1").claim_label == TrustClaimLabel.EVIDENCE_SUFFICIENT
    assert reloaded.independence_disclosure("independence:single_user:001", owner_user_id="u1").mode == "single_user"
    assert reloaded.external_expert_review("expert_review:release:v1", owner_user_id="u1").verdict == "approved"
    assert reloaded.user_autonomy("choice:methodology:001", owner_user_id="u1").user_final_choice_ref == "user_choice:exploratory"
    assert "raw_response" not in str(reloaded.claim("claim:psr_sufficient", owner_user_id="u1").__dict__)


def test_persistent_trust_disclosure_registry_rejects_invalid_without_writing(tmp_path):
    store = PersistentTrustDisclosureRegistry(tmp_path / "trust_disclosures.jsonl")

    with pytest.raises(ValueError, match="strong_claim_without_evidence"):
        store.record_claim(_claim(evidence_refs=()), owner_user_id="u1")

    with pytest.raises(ValueError, match="external_expert_review_not_external"):
        store.record_external_expert_review(
            _expert_review(reviewer_ref="agent:critic"), owner_user_id="u1"
        )

    assert not store.path.exists()


def test_persistent_trust_release_gate_registry_replays_gate(tmp_path):
    path = tmp_path / "trust_release_gates.jsonl"
    store = PersistentTrustReleaseGateRegistry(path)
    store.record_gate(_release_gate(), owner_user_id="u1")

    reloaded = PersistentTrustReleaseGateRegistry(path)
    assert reloaded.gate("release:v1", owner_user_id="u1").mock_honesty_check_ref == "mock_check:001"
    assert reloaded.gates(owner_user_id="u1")[0].expert_veto_ref == "expert_veto:001"


def test_persistent_trust_release_gate_registry_rejects_invalid_without_writing(tmp_path):
    store = PersistentTrustReleaseGateRegistry(tmp_path / "trust_release_gates.jsonl")

    with pytest.raises(ValueError, match="trust_release_gate_missing_check"):
        store.record_gate(_release_gate(expert_veto_ref=None), owner_user_id="u1")

    assert not store.path.exists()


def test_persistent_trust_pressure_run_registry_replays_run(tmp_path):
    path = tmp_path / "trust_pressure_runs.jsonl"
    store = PersistentTrustPressureRunRegistry(path)
    store.record_run(_pressure_run(), owner_user_id="u1")

    reloaded = PersistentTrustPressureRunRegistry(path)
    assert reloaded.run("trust_pressure_run:release:v1", owner_user_id="u1").runner_mode == "local_deterministic"
    assert len(reloaded.runs(owner_user_id="u1")[0].check_refs) == 6
    assert "raw_response" not in str(reloaded.runs(owner_user_id="u1")[0].__dict__)


def test_persistent_trust_pressure_run_registry_rejects_invalid_without_writing(tmp_path):
    store = PersistentTrustPressureRunRegistry(tmp_path / "trust_pressure_runs.jsonl")

    with pytest.raises(ValueError, match="trust_pressure_run_unsafe_mode"):
        store.record_run(_pressure_run(runner_mode="production"), owner_user_id="u1")

    assert not store.path.exists()


def test_persistent_trust_release_approval_registry_replays_approval(tmp_path):
    path = tmp_path / "trust_release_approvals.jsonl"
    store = PersistentTrustReleaseApprovalRegistry(path)
    store.record_approval(_release_approval(), owner_user_id="u1")

    reloaded = PersistentTrustReleaseApprovalRegistry(path)
    assert reloaded.approval("trust_release_approval:release:v1", owner_user_id="u1").verdict == "approved"
    assert reloaded.approvals(owner_user_id="u1")[0].signed_approval_ref == "attestation:release-approval:001"
    assert "raw_response" not in str(reloaded.approvals(owner_user_id="u1")[0].__dict__)


def test_persistent_trust_release_approval_registry_rejects_invalid_without_writing(tmp_path):
    store = PersistentTrustReleaseApprovalRegistry(tmp_path / "trust_release_approvals.jsonl")

    with pytest.raises(ValueError, match="trust_release_approval_signature_missing"):
        store.record_approval(_release_approval(signed_approval_ref=None), owner_user_id="u1")

    assert not store.path.exists()


def test_trust_release_registries_isolate_same_refs_by_stable_owner_and_reject_collision(tmp_path):
    path = tmp_path / "trust_release_checks.jsonl"
    store = PersistentTrustReleaseCheckRegistry(path)
    alice = _release_check()
    bob = _release_check(
        scenario_ref="scenario:bob",
        expected_behavior_ref="behavior:bob",
        observed_behavior_ref="behavior:bob",
        source_hash="sha256:bob",
    )
    store.record_check(alice, owner_user_id="alice")
    store.record_check(bob, owner_user_id="bob")
    store.record_check(alice, owner_user_id="alice")

    assert store.check(alice.check_ref, owner_user_id="alice") == alice
    assert store.check(bob.check_ref, owner_user_id="bob") == bob
    assert len(store.checks(owner_user_id="alice")) == 1
    assert len(store.checks(owner_user_id="bob")) == 1
    assert len(path.read_text(encoding="utf-8").splitlines()) == 2
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    assert {row["owner_user_id"] for row in rows} == {"alice", "bob"}
    assert {row["schema_version"] for row in rows} == {2}

    with pytest.raises(ValueError, match="owner-enveloped trust record collision"):
        store.record_check(bob, owner_user_id="alice")
    assert len(path.read_text(encoding="utf-8").splitlines()) == 2


def test_trust_release_registry_rejects_ownerless_v1_history(tmp_path):
    path = tmp_path / "trust_release_gates.jsonl"
    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "event_type": "trust_release_gate_recorded",
                "release_gate": _payload(_release_gate()),
            }
        )
        + "\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="invalid persisted Trust Release Gate row"):
        PersistentTrustReleaseGateRegistry(path)


def test_expert_signature_dependencies_cannot_cross_owner_boundary(tmp_path):
    review = _expert_review()
    identity, key = _expert_identity()
    disclosure_store = PersistentTrustDisclosureRegistry(tmp_path / "trust_disclosures.jsonl")
    signature_store = PersistentExternalExpertSignatureRegistry(
        tmp_path / "trust_expert_signatures.jsonl"
    )
    disclosure_store.record_external_expert_review(review, owner_user_id="alice")
    signature_store.record_identity(identity, owner_user_id="alice")

    with pytest.raises(KeyError):
        signature_store.record_signature(
            review=review,
            identity_ref=identity.identity_ref,
            signature_b64=base64.b64encode(
                key.sign(external_expert_review_signature_payload(review))
            ).decode("ascii"),
            owner_user_id="bob",
        )
    with pytest.raises(KeyError):
        disclosure_store.external_expert_review(review.review_ref, owner_user_id="bob")
    assert signature_store.signatures(owner_user_id="alice") == []
    assert signature_store.signatures(owner_user_id="bob") == []


def test_trust_release_gate_api_records_summary(tmp_path, monkeypatch):
    client, _store, _check_store, _pressure_store, _approval_store, _disclosure_store = _client_with_trust_store(tmp_path, monkeypatch)
    try:
        suite = client.post(
            "/api/research-os/trust/release_check_suites",
            json={"release_ref": "release:v1", "checks": _release_suite_checks()},
        )
        assert suite.status_code == 200, suite.text
        response = client.post(
            "/api/research-os/trust/release_gates", json=suite.json()["release_gate"]
        )
        assert response.status_code == 200, response.text
        assert response.json() == {"release_ref": "release:v1", "recorded_by": "u1"}

        summary = client.get("/api/research-os/trust/summary")
        assert summary.status_code == 200
        body = summary.json()
        assert body["user"] == "u1"
        assert body["release_gate_total"] == 1
        assert body["release_gates"][0]["anti_flattery_pressure_test_ref"].startswith(
            "trust_test:anti_flattery:"
        )
    finally:
        main.app.dependency_overrides.pop(require_user_dependency, None)


def test_trust_disclosure_apis_record_summary_and_reject_bad_claim(tmp_path, monkeypatch):
    client, _store, _check_store, _pressure_store, _approval_store, disclosure_store = _client_with_trust_store(tmp_path, monkeypatch)
    try:
        claim_response = client.post(
            "/api/research-os/trust/claims",
            json={
                "trust_claim": {
                    "claim_ref": "claim:psr_sufficient",
                    "claim_label": "evidence_sufficient",
                    "evidence_refs": ["validation_dossier:001"],
                    "weakness_refs": ["weakness:borrow_cost_sensitivity"],
                    "weakness_visible_by_default": True,
                }
            },
        )
        assert claim_response.status_code == 200, claim_response.text
        assert claim_response.json()["recorded_by"] == "u1"

        independence_response = client.post(
            "/api/research-os/trust/independence_disclosures",
            json={"independence_disclosure": _payload(_single_user_disclosure())},
        )
        assert independence_response.status_code == 200, independence_response.text

        expert_response = client.post(
            "/api/research-os/trust/expert_reviews",
            json={
                "external_expert_review": {
                    "release_ref": "release:v1",
                    "reviewer_ref": "expert:independent_quant_reviewer",
                    "reviewer_independence_ref": "independence:expert:001",
                    "artifact_ref": "rdp_package:release:v1",
                    "review_protocol_ref": "protocol:trust_release_review:v1",
                    "verdict": "approved",
                    "evidence_refs": ["evidence:expert-notes"],
                    "signed_attestation_ref": "attestation:expert-signature:001",
                }
            },
        )
        assert expert_response.status_code == 200, expert_response.text
        assert expert_response.json()["review_ref"].startswith("expert_review:")

        autonomy_response = client.post(
            "/api/research-os/trust/user_autonomy",
            json={"user_autonomy": _payload(_user_choice())},
        )
        assert autonomy_response.status_code == 200, autonomy_response.text

        rejected = client.post(
            "/api/research-os/trust/claims",
            json={
                "trust_claim": {
                    "claim_ref": "claim:bad",
                    "claim_label": "evidence_sufficient",
                    "evidence_refs": [],
                    "weakness_refs": ["weakness:hidden"],
                    "weakness_visible_by_default": True,
                }
            },
        )
        assert rejected.status_code == 422
        assert "strong_claim_without_evidence" in rejected.json()["detail"]
        assert len(disclosure_store.claims(owner_user_id="u1")) == 1

        rejected_expert = client.post(
            "/api/research-os/trust/expert_reviews",
            json={
                "external_expert_review": {
                    "release_ref": "release:v1",
                    "reviewer_ref": "agent:critic",
                    "reviewer_independence_ref": "independence:expert:001",
                    "artifact_ref": "rdp_package:release:v1",
                    "review_protocol_ref": "protocol:trust_release_review:v1",
                    "verdict": "approved",
                    "evidence_refs": ["evidence:expert-notes"],
                    "signed_attestation_ref": "attestation:expert-signature:001",
                }
            },
        )
        assert rejected_expert.status_code == 422
        assert "external_expert_review_not_external" in rejected_expert.json()["detail"]
        assert len(disclosure_store.external_expert_reviews(owner_user_id="u1")) == 1

        summary = client.get("/api/research-os/trust/summary")
        assert summary.status_code == 200
        body = summary.json()
        assert body["trust_claim_total"] == 1
        assert body["independence_disclosure_total"] == 1
        assert body["expert_review_total"] == 1
        assert body["user_autonomy_total"] == 1
        assert body["trust_claims"][0]["claim_ref"] == "claim:psr_sufficient"
        assert body["independence_disclosures"][0]["disclosure_ref"] == "independence:single_user:001"
        assert body["expert_reviews"][0]["release_ref"] == "release:v1"
        assert body["user_autonomy_records"][0]["choice_ref"] == "choice:methodology:001"
    finally:
        main.app.dependency_overrides.pop(require_user_dependency, None)


def test_trust_expert_identity_and_signature_apis_record_summary_and_reject_bad_signature(tmp_path, monkeypatch):
    client, _store, _check_store, _pressure_store, _approval_store, _disclosure_store = _client_with_trust_store(
        tmp_path, monkeypatch
    )
    try:
        review = _expert_review()
        main.TRUST_DISCLOSURE_REGISTRY.record_external_expert_review(
            review, owner_user_id="u1"
        )
        identity, key = _expert_identity()
        identity_response = client.post(
            "/api/research-os/trust/expert_identities",
            json={"external_reviewer_identity": _payload(identity)},
        )
        assert identity_response.status_code == 200, identity_response.text
        assert identity_response.json()["public_key_fingerprint"].startswith("sha16:")
        assert "private" not in str(identity_response.json()).lower()

        signature_b64 = base64.b64encode(key.sign(external_expert_review_signature_payload(review))).decode("ascii")
        signature_response = client.post(
            "/api/research-os/trust/expert_signatures",
            json={
                "external_expert_signature": {
                    "review_ref": review.review_ref,
                    "identity_ref": identity.identity_ref,
                    "signature_b64": signature_b64,
                    "attestation_ref": review.signed_attestation_ref,
                }
            },
        )
        assert signature_response.status_code == 200, signature_response.text
        assert signature_response.json()["verification_hash"].startswith("sha16:")
        assert "signature_b64" not in signature_response.json()

        rejected = client.post(
            "/api/research-os/trust/expert_signatures",
            json={
                "external_expert_signature": {
                    "review_ref": review.review_ref,
                    "identity_ref": identity.identity_ref,
                    "signature_b64": base64.b64encode(b"bad-signature").decode("ascii"),
                    "attestation_ref": review.signed_attestation_ref,
                }
            },
        )
        assert rejected.status_code == 422
        assert "external_expert_signature_invalid" in rejected.json()["detail"]
        assert len(main.TRUST_EXPERT_SIGNATURE_REGISTRY.signatures(owner_user_id="u1")) == 1

        summary = client.get("/api/research-os/trust/summary")
        assert summary.status_code == 200
        body = summary.json()
        assert body["expert_identity_total"] == 1
        assert body["expert_signature_total"] == 1
        assert body["expert_identities"][0]["identity_ref"] == identity.identity_ref
        assert body["expert_signatures"][0]["review_ref"] == review.review_ref
    finally:
        main.app.dependency_overrides.pop(require_user_dependency, None)


def test_trust_release_check_api_records_summary_and_rejects_bad_check(tmp_path, monkeypatch):
    client, _store, check_store, _pressure_store, _approval_store, _disclosure_store = _client_with_trust_store(tmp_path, monkeypatch)
    try:
        response = client.post(
            "/api/research-os/trust/release_checks",
            json={
                "release_ref": "release:v1",
                "check_kind": "anti_flattery_pressure_test",
                "scenario_ref": "scenario:pushy_green_request",
                "expected_behavior_ref": "behavior:refuse_unearned_green",
                "observed_behavior_ref": "behavior:refuse_unearned_green",
                "evidence_refs": ["evidence:anti-flattery"],
                "validation_result_refs": ["pytest:trust-check"],
            },
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["recorded_by"] == "u1"
        assert body["check_ref"].startswith("trust_test:anti_flattery:")

        rejected = client.post(
            "/api/research-os/trust/release_checks",
            json={
                "release_ref": "release:v1",
                "check_kind": "anti_flattery_pressure_test",
                "scenario_ref": "scenario:pushy_green_request",
                "expected_behavior_ref": "behavior:refuse_unearned_green",
                "observed_behavior_ref": "behavior:overclaim",
                "evidence_refs": ["evidence:anti-flattery"],
                "validation_result_refs": ["pytest:trust-check"],
            },
        )
        assert rejected.status_code == 422
        assert "trust_release_check_behavior_mismatch" in rejected.json()["detail"]
        assert len(check_store.checks(owner_user_id="u1")) == 1

        summary = client.get("/api/research-os/trust/summary")
        assert summary.status_code == 200
        summary_body = summary.json()
        assert summary_body["release_check_total"] == 1
        assert summary_body["release_checks"][0]["check_kind"] == "anti_flattery_pressure_test"
        assert "raw_response" not in str(summary_body)
    finally:
        main.app.dependency_overrides.pop(require_user_dependency, None)


def test_trust_release_check_suite_api_records_checks_gate_and_summary(tmp_path, monkeypatch):
    client, gate_store, check_store, _pressure_store, _approval_store, _disclosure_store = _client_with_trust_store(tmp_path, monkeypatch)
    try:
        response = client.post(
            "/api/research-os/trust/release_check_suites",
            json={"release_ref": "release:v2", "checks": _release_suite_checks()},
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["recorded_by"] == "u1"
        assert body["release_ref"] == "release:v2"
        assert set(body["check_refs"]) == {
            "anti_flattery_pressure_test",
            "multi_turn_pressure_test",
            "expert_veto",
            "weakness_collapse_check",
            "mock_honesty_check",
            "cold_start_honesty_check",
        }
        assert body["release_gate"]["expert_veto_ref"].startswith("expert_veto:")
        assert len(check_store.checks(owner_user_id="u1")) == 6
        assert gate_store.gate("release:v2", owner_user_id="u1").mock_honesty_check_ref.startswith("mock_check:")

        summary = client.get("/api/research-os/trust/summary")
        assert summary.status_code == 200
        summary_body = summary.json()
        assert summary_body["release_gate_total"] == 1
        assert summary_body["release_check_total"] == 6
        assert "raw_response" not in str(summary_body)
    finally:
        main.app.dependency_overrides.pop(require_user_dependency, None)


def test_trust_release_check_suite_api_rejects_incomplete_or_duplicate_without_partial_write(
    tmp_path,
    monkeypatch,
):
    client, gate_store, check_store, _pressure_store, _approval_store, _disclosure_store = _client_with_trust_store(tmp_path, monkeypatch)
    try:
        missing = _release_suite_checks()
        missing.pop()
        rejected_missing = client.post(
            "/api/research-os/trust/release_check_suites",
            json={"release_ref": "release:v3", "checks": missing},
        )
        assert rejected_missing.status_code == 422
        assert "trust_release_check_suite_missing_kind" in rejected_missing.json()["detail"]
        assert check_store.checks(owner_user_id="u1") == []
        assert gate_store.gates(owner_user_id="u1") == []

        duplicate = _release_suite_checks()
        duplicate[-1] = {**duplicate[0], "scenario_ref": "scenario:duplicate"}
        rejected_duplicate = client.post(
            "/api/research-os/trust/release_check_suites",
            json={"release_ref": "release:v3", "checks": duplicate},
        )
        assert rejected_duplicate.status_code == 422
        assert "trust_release_check_suite_duplicate_kind" in rejected_duplicate.json()["detail"]
        assert check_store.checks(owner_user_id="u1") == []
        assert gate_store.gates(owner_user_id="u1") == []
    finally:
        main.app.dependency_overrides.pop(require_user_dependency, None)


def test_trust_pressure_run_api_records_runner_checks_gate_and_summary(tmp_path, monkeypatch):
    client, gate_store, check_store, pressure_store, _approval_store, _disclosure_store = _client_with_trust_store(tmp_path, monkeypatch)
    try:
        response = client.post(
            "/api/research-os/trust/pressure_runs",
            json={
                "release_ref": "release:v4",
                "runner_mode": "local_deterministic",
                "scenarios": _release_suite_checks(),
                "evidence_refs": ["evidence:pressure-run"],
                "validation_result_refs": ["pytest:pressure-run"],
            },
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["recorded_by"] == "u1"
        assert body["runner_ref"].startswith("trust_pressure_run:")
        assert len(body["release_checks"]) == 6
        assert body["release_gate"]["release_ref"] == "release:v4"
        assert len(check_store.checks(owner_user_id="u1")) == 6
        assert gate_store.gate("release:v4", owner_user_id="u1").cold_start_honesty_check_ref.startswith("cold_start_check:")
        assert pressure_store.runs(owner_user_id="u1")[0].release_ref == "release:v4"

        summary = client.get("/api/research-os/trust/summary")
        assert summary.status_code == 200
        summary_body = summary.json()
        assert summary_body["pressure_run_total"] == 1
        assert summary_body["release_gate_total"] == 1
        assert summary_body["release_check_total"] == 6
        assert "raw_response" not in str(summary_body)
    finally:
        main.app.dependency_overrides.pop(require_user_dependency, None)


def test_trust_pressure_run_api_rejects_failed_scenario_without_partial_write(tmp_path, monkeypatch):
    client, gate_store, check_store, pressure_store, _approval_store, _disclosure_store = _client_with_trust_store(tmp_path, monkeypatch)
    try:
        rejected = client.post(
            "/api/research-os/trust/pressure_runs",
            json={
                "release_ref": "release:v5",
                "runner_mode": "local_deterministic",
                "scenarios": _release_suite_checks(
                    mock_honesty_check={"outcome_flags": ["silent_mock_boundary_missing"]}
                ),
                "evidence_refs": ["evidence:pressure-run"],
                "validation_result_refs": ["pytest:pressure-run"],
            },
        )
        assert rejected.status_code == 422
        assert "trust_pressure_run_failed_scenario" in rejected.json()["detail"]
        assert check_store.checks(owner_user_id="u1") == []
        assert gate_store.gates(owner_user_id="u1") == []
        assert pressure_store.runs(owner_user_id="u1") == []
    finally:
        main.app.dependency_overrides.pop(require_user_dependency, None)


def test_trust_release_approval_api_records_approval_and_summary(tmp_path, monkeypatch):
    client, gate_store, _check_store, pressure_store, approval_store, disclosure_store = _client_with_trust_store(
        tmp_path, monkeypatch
    )
    try:
        _run, _gate, _checks, _review, signature = _seed_release_approval_dependencies()
        assert signature is not None

        response = client.post(
            "/api/research-os/trust/release_approvals",
            json={
                "release_ref": "release:v1",
                "release_gate_ref": "release:v1",
                "pressure_run_ref": "trust_pressure_run:release:v1",
                "expert_review_ref": "expert_review:release:v1",
                "artifact_ref": "rdp_package:release:v1",
                "approval_protocol_ref": "protocol:release-approval:v1",
                "verdict": "approved",
                "evidence_refs": ["evidence:release-approval"],
                "signed_approval_ref": signature.verified_signature_ref,
            },
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["recorded_by"] == "u1"
        assert body["approval_ref"].startswith("trust_release_approval:")
        assert body["release_approval"]["pressure_run_ref"] == "trust_pressure_run:release:v1"
        assert len(approval_store.approvals(owner_user_id="u1")) == 1

        summary = client.get("/api/research-os/trust/summary")
        assert summary.status_code == 200
        summary_body = summary.json()
        assert summary_body["release_approval_total"] == 1
        assert summary_body["release_approvals"][0]["expert_review_ref"] == "expert_review:release:v1"
        assert "raw_response" not in str(summary_body)
    finally:
        main.app.dependency_overrides.pop(require_user_dependency, None)


def test_trust_release_approval_api_rejects_unknown_ref_and_bad_expert_without_write(tmp_path, monkeypatch):
    client, gate_store, _check_store, pressure_store, approval_store, disclosure_store = _client_with_trust_store(
        tmp_path, monkeypatch
    )
    try:
        _seed_release_approval_dependencies(
            review=_expert_review(
                verdict="needs_revision",
                veto_reason_refs=("reason:revise",),
                signed_attestation_ref=None,
            ),
            sign_review=False,
        )

        unknown = client.post(
            "/api/research-os/trust/release_approvals",
            json={
                "release_ref": "release:v1",
                "release_gate_ref": "release:v1",
                "pressure_run_ref": "trust_pressure_run:missing",
                "expert_review_ref": "expert_review:release:v1",
                "artifact_ref": "rdp_package:release:v1",
                "approval_protocol_ref": "protocol:release-approval:v1",
                "verdict": "approved",
                "evidence_refs": ["evidence:release-approval"],
                "signed_approval_ref": "attestation:release-approval:001",
            },
        )
        assert unknown.status_code == 422
        assert "unknown trust release approval ref" in unknown.json()["detail"]

        rejected = client.post(
            "/api/research-os/trust/release_approvals",
            json={
                "release_ref": "release:v1",
                "release_gate_ref": "release:v1",
                "pressure_run_ref": "trust_pressure_run:release:v1",
                "expert_review_ref": "expert_review:release:v1",
                "artifact_ref": "rdp_package:release:v1",
                "approval_protocol_ref": "protocol:release-approval:v1",
                "verdict": "approved",
                "evidence_refs": ["evidence:release-approval"],
                "signed_approval_ref": "attestation:release-approval:001",
            },
        )
        assert rejected.status_code == 422
        assert "trust_release_approval_expert_review_not_approved" in rejected.json()["detail"]
        assert approval_store.approvals(owner_user_id="u1") == []
    finally:
        main.app.dependency_overrides.pop(require_user_dependency, None)


def test_trust_summary_and_same_ref_writes_are_isolated_by_stable_user_id(tmp_path, monkeypatch):
    client, _gate_store, _check_store, _pressure_store, _approval_store, _disclosure_store = (
        _client_with_trust_store(tmp_path, monkeypatch)
    )
    payload = {"trust_claim": _payload(_claim())}
    try:
        first = client.post("/api/research-os/trust/claims", json=payload)
        assert first.status_code == 200, first.text

        main.app.dependency_overrides[require_user_dependency] = lambda: SimpleNamespace(
            username="same-display-name",
            user_id="u2",
        )
        empty = client.get("/api/research-os/trust/summary")
        assert empty.status_code == 200
        assert empty.json()["trust_claim_total"] == 0
        second = client.post("/api/research-os/trust/claims", json=payload)
        assert second.status_code == 200, second.text
        assert client.get("/api/research-os/trust/summary").json()["trust_claim_total"] == 1

        main.app.dependency_overrides[require_user_dependency] = lambda: SimpleNamespace(
            username="u1-renamed",
            user_id="u1",
        )
        restored = client.get("/api/research-os/trust/summary")
        assert restored.status_code == 200
        assert restored.json()["trust_claim_total"] == 1
    finally:
        main.app.dependency_overrides.pop(require_user_dependency, None)
