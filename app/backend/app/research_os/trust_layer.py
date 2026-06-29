"""GOAL §13 trust-layer contracts."""

from __future__ import annotations

import base64
import json
import re
from collections.abc import Sequence
from dataclasses import asdict, dataclass, is_dataclass
from enum import Enum
from pathlib import Path
from typing import Any

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from ..lineage.ids import content_hash


def _tuple(value: Any) -> tuple[Any, ...]:
    if value is None:
        return ()
    if isinstance(value, tuple):
        return value
    if isinstance(value, list):
        return tuple(value)
    return (value,)


def _value(value: Any) -> str:
    if isinstance(value, Enum):
        return str(value.value)
    return str(value or "")


def _present(value: str | None) -> bool:
    return bool(str(value or "").strip())


def _any_present(values: Any) -> bool:
    """True iff the collection holds at least one present element (delegates to _present).

    Anti-gaming: a non-empty collection of empty/whitespace strings (e.g.
    evidence_refs=[''] / ['  ']) must NOT count as supplied refs. Single source of
    "present" stays _present(); this only vectorizes it over a ref collection.
    """

    return any(_present(value) for value in _tuple(values))


def _json_value(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    if is_dataclass(value):
        return _json_value(asdict(value))
    if isinstance(value, dict):
        return {str(k): _json_value(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_value(v) for v in value]
    return value


def _bool_value(value: Any, *, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return bool(value)


def _contains_secret_marker(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, dict):
        return any(_contains_secret_marker(child) for child in value.values())
    if isinstance(value, (list, tuple, set)):
        return any(_contains_secret_marker(child) for child in value)
    return bool(SECRET_MARKER.search(str(value or "")))


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(_json_value(value), ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _load_ed25519_public_key(public_key_pem: str) -> Ed25519PublicKey:
    key = serialization.load_pem_public_key(str(public_key_pem or "").encode("utf-8"))
    if not isinstance(key, Ed25519PublicKey):
        raise ValueError("external reviewer identity public_key_pem must be an Ed25519 public key")
    return key


def external_expert_review_signature_payload(record: "ExternalExpertReviewRecord") -> bytes:
    payload = {
        "review_ref": record.review_ref,
        "release_ref": record.release_ref,
        "reviewer_ref": record.reviewer_ref,
        "reviewer_independence_ref": record.reviewer_independence_ref,
        "artifact_ref": record.artifact_ref,
        "review_protocol_ref": record.review_protocol_ref,
        "verdict": record.verdict,
        "source_hash": record.source_hash,
        "evidence_refs": record.evidence_refs,
        "veto_reason_refs": record.veto_reason_refs,
    }
    return _canonical_bytes(payload)


class TrustClaimLabel(str, Enum):
    CANDIDATE_CONTEXT = "candidate_context"
    PRIOR_ASSERTION = "prior_assertion"
    UNVERIFIED_RESULT = "unverified_result"
    EVIDENCE_SUFFICIENT = "evidence_sufficient"
    PROOF_BACKED = "proof_backed"
    PRODUCTION_READY = "production_ready"


STRONG_CLAIMS = {
    TrustClaimLabel.EVIDENCE_SUFFICIENT.value,
    TrustClaimLabel.PROOF_BACKED.value,
    TrustClaimLabel.PRODUCTION_READY.value,
}
TRUST_RELEASE_CHECK_KINDS = {
    "anti_flattery_pressure_test",
    "multi_turn_pressure_test",
    "expert_veto",
    "weakness_collapse_check",
    "mock_honesty_check",
    "cold_start_honesty_check",
}
PASSING_VERDICTS = {"accepted", "passed", "no_violation"}
CHECK_REF_PREFIXES = {
    "anti_flattery_pressure_test": "trust_test:anti_flattery",
    "multi_turn_pressure_test": "trust_test:multi_turn",
    "expert_veto": "expert_veto",
    "weakness_collapse_check": "weakness_check",
    "mock_honesty_check": "mock_check",
    "cold_start_honesty_check": "cold_start_check",
}
SECRET_MARKER = re.compile(
    r"(?i)(api[_-]?key|api[_-]?secret|password|oauth[_-]?token|access[_-]?token|secret|private[_-]?key)\s*="
)
TRUST_RELEASE_GATE_FIELD_BY_CHECK_KIND = {
    "anti_flattery_pressure_test": "anti_flattery_pressure_test_ref",
    "multi_turn_pressure_test": "multi_turn_pressure_test_ref",
    "expert_veto": "expert_veto_ref",
    "weakness_collapse_check": "weakness_collapse_check_ref",
    "mock_honesty_check": "mock_honesty_check_ref",
    "cold_start_honesty_check": "cold_start_honesty_check_ref",
}
TRUST_PRESSURE_RUNNER_MODES = {"local_deterministic", "test_harness"}


@dataclass(frozen=True)
class TrustLayerViolation:
    code: str
    message: str
    field: str = ""
    ref: str = ""


@dataclass(frozen=True)
class TrustLayerDecision:
    accepted: bool
    violations: tuple[TrustLayerViolation, ...]


@dataclass(frozen=True)
class TrustClaimRecord:
    claim_ref: str
    claim_label: TrustClaimLabel | str
    evidence_refs: tuple[str, ...]
    weakness_refs: tuple[str, ...]
    weakness_visible_by_default: bool
    cold_start_n: int | None = None
    pressure_context: str = ""
    user_waiver_ref: str | None = None
    waiver_weakness_visible_by_default: bool = True

    def __post_init__(self) -> None:
        object.__setattr__(self, "evidence_refs", _tuple(self.evidence_refs))
        object.__setattr__(self, "weakness_refs", _tuple(self.weakness_refs))


@dataclass(frozen=True)
class FunctionalIndependenceDisclosure:
    disclosure_ref: str
    mode: str
    claims_organizational_independence: bool
    isolated_validation_ref: str | None
    immutable_evidence_ref: str | None
    second_confirmation_ref: str | None
    alternate_model_verification_ref: str | None
    organization_process_ref: str | None = None


@dataclass(frozen=True)
class ExternalExpertReviewRecord:
    review_ref: str
    release_ref: str
    reviewer_ref: str
    reviewer_independence_ref: str
    artifact_ref: str
    review_protocol_ref: str
    verdict: str
    source_hash: str
    evidence_refs: tuple[str, ...]
    veto_reason_refs: tuple[str, ...] = ()
    signed_attestation_ref: str | None = None
    silent_mock_fallback_used: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(self, "evidence_refs", tuple(str(v) for v in _tuple(self.evidence_refs)))
        object.__setattr__(self, "veto_reason_refs", tuple(str(v) for v in _tuple(self.veto_reason_refs)))


@dataclass(frozen=True)
class ExternalReviewerIdentityRecord:
    identity_ref: str
    reviewer_ref: str
    identity_provider_ref: str
    public_key_ref: str
    public_key_pem: str
    reviewer_independence_ref: str
    evidence_refs: tuple[str, ...]
    public_key_fingerprint: str = ""
    status: str = "active"
    identity_hash: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "evidence_refs", tuple(str(v) for v in _tuple(self.evidence_refs)))
        fingerprint = "sha16:" + content_hash({"public_key_pem": str(self.public_key_pem or "").strip()})
        if self.public_key_fingerprint and self.public_key_fingerprint != fingerprint:
            raise ValueError("external reviewer identity public_key_fingerprint mismatch")
        object.__setattr__(self, "public_key_fingerprint", fingerprint)
        payload = {
            "identity_ref": self.identity_ref,
            "reviewer_ref": self.reviewer_ref,
            "identity_provider_ref": self.identity_provider_ref,
            "public_key_ref": self.public_key_ref,
            "public_key_fingerprint": fingerprint,
            "reviewer_independence_ref": self.reviewer_independence_ref,
            "evidence_refs": self.evidence_refs,
            "status": self.status,
        }
        expected_hash = "sha16:" + content_hash(payload)
        if self.identity_hash and self.identity_hash != expected_hash:
            raise ValueError("external reviewer identity hash mismatch")
        object.__setattr__(self, "identity_hash", expected_hash)


@dataclass(frozen=True)
class ExternalExpertSignatureRecord:
    verified_signature_ref: str
    attestation_ref: str
    review_ref: str
    reviewer_ref: str
    identity_ref: str
    public_key_ref: str
    public_key_fingerprint: str
    signed_payload_hash: str
    signature_b64: str
    verified_at: str
    verification_hash: str = ""
    verification_version: str = "trust.external_expert_signature.v1"

    def __post_init__(self) -> None:
        payload = {
            "verification_version": self.verification_version,
            "verified_signature_ref": self.verified_signature_ref,
            "attestation_ref": self.attestation_ref,
            "review_ref": self.review_ref,
            "reviewer_ref": self.reviewer_ref,
            "identity_ref": self.identity_ref,
            "public_key_ref": self.public_key_ref,
            "public_key_fingerprint": self.public_key_fingerprint,
            "signed_payload_hash": self.signed_payload_hash,
            "signature_b64": self.signature_b64,
            "verified_at": self.verified_at,
        }
        expected_hash = "sha16:" + content_hash(payload)
        if self.verification_hash and self.verification_hash != expected_hash:
            raise ValueError("external expert signature verification hash mismatch")
        object.__setattr__(self, "verification_hash", expected_hash)


@dataclass(frozen=True)
class UserAutonomyRecord:
    choice_ref: str
    agent_recommendation_ref: str | None
    tradeoff_refs: tuple[str, ...]
    alternative_path_refs: tuple[str, ...]
    responsibility_boundary_ref: str | None
    user_final_choice_ref: str | None
    agent_made_final_choice: bool = False
    system_blocked_after_user_acceptance: bool = False
    redline_refs: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "tradeoff_refs", _tuple(self.tradeoff_refs))
        object.__setattr__(self, "alternative_path_refs", _tuple(self.alternative_path_refs))
        object.__setattr__(self, "redline_refs", _tuple(self.redline_refs))


@dataclass(frozen=True)
class TrustReleaseGateRecord:
    release_ref: str
    anti_flattery_pressure_test_ref: str | None
    multi_turn_pressure_test_ref: str | None
    expert_veto_ref: str | None
    weakness_collapse_check_ref: str | None
    mock_honesty_check_ref: str | None
    cold_start_honesty_check_ref: str | None


@dataclass(frozen=True)
class TrustReleaseCheckRecord:
    check_ref: str
    release_ref: str
    check_kind: str
    scenario_ref: str
    expected_behavior_ref: str
    observed_behavior_ref: str
    verdict: str
    source_hash: str
    evidence_refs: tuple[str, ...]
    validation_result_refs: tuple[str, ...]
    silent_mock_fallback_used: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(self, "evidence_refs", tuple(str(v) for v in _tuple(self.evidence_refs)))
        object.__setattr__(
            self,
            "validation_result_refs",
            tuple(str(v) for v in _tuple(self.validation_result_refs)),
        )


@dataclass(frozen=True)
class TrustPressureRunRecord:
    runner_ref: str
    release_ref: str
    runner_mode: str
    source_hash: str
    release_gate_ref: str
    check_refs: tuple[str, ...]
    scenario_refs: tuple[str, ...]
    evidence_refs: tuple[str, ...]
    validation_result_refs: tuple[str, ...]
    failed_scenario_refs: tuple[str, ...] = ()
    silent_mock_fallback_used: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(self, "check_refs", tuple(str(v) for v in _tuple(self.check_refs)))
        object.__setattr__(self, "scenario_refs", tuple(str(v) for v in _tuple(self.scenario_refs)))
        object.__setattr__(self, "evidence_refs", tuple(str(v) for v in _tuple(self.evidence_refs)))
        object.__setattr__(
            self,
            "validation_result_refs",
            tuple(str(v) for v in _tuple(self.validation_result_refs)),
        )
        object.__setattr__(
            self,
            "failed_scenario_refs",
            tuple(str(v) for v in _tuple(self.failed_scenario_refs)),
        )


@dataclass(frozen=True)
class TrustReleaseApprovalRecord:
    approval_ref: str
    release_ref: str
    release_gate_ref: str
    pressure_run_ref: str
    expert_review_ref: str
    artifact_ref: str
    approval_protocol_ref: str
    verdict: str
    source_hash: str
    evidence_refs: tuple[str, ...]
    signed_approval_ref: str | None = None
    residual_blocker_refs: tuple[str, ...] = ()
    silent_mock_fallback_used: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(self, "evidence_refs", tuple(str(v) for v in _tuple(self.evidence_refs)))
        object.__setattr__(
            self,
            "residual_blocker_refs",
            tuple(str(v) for v in _tuple(self.residual_blocker_refs)),
        )


def validate_trust_claim(claim: TrustClaimRecord) -> TrustLayerDecision:
    violations: list[TrustLayerViolation] = []
    label = _value(claim.claim_label).strip().casefold()
    if label in STRONG_CLAIMS and not _any_present(claim.evidence_refs):
        violations.append(
            TrustLayerViolation(
                "strong_claim_without_evidence",
                "strong trust claims require evidence refs",
                field="evidence_refs",
                ref=claim.claim_ref,
            )
        )
    if "wishful" in str(claim.pressure_context).lower() and label in STRONG_CLAIMS:
        violations.append(
            TrustLayerViolation(
                "wishful_pressure_strong_conclusion",
                "agent cannot convert user wishful thinking into a strong conclusion",
                field="pressure_context",
                ref=claim.claim_ref,
            )
        )
    if claim.weakness_refs and not claim.weakness_visible_by_default:
        violations.append(
            TrustLayerViolation(
                "weakness_hidden_by_default",
                "weaknesses and risks must stay visible by default",
                field="weakness_visible_by_default",
                ref=claim.claim_ref,
            )
        )
    if claim.user_waiver_ref and not claim.waiver_weakness_visible_by_default:
        violations.append(
            TrustLayerViolation(
                "user_waived_weakness_hidden",
                "user-waived weaknesses must remain visible",
                field="waiver_weakness_visible_by_default",
                ref=claim.claim_ref,
            )
        )
    if claim.cold_start_n is not None and claim.cold_start_n <= 1 and label in STRONG_CLAIMS:
        violations.append(
            TrustLayerViolation(
                "cold_start_packaged_as_statistical_evidence",
                "cold-start N=1 must be labeled as prior assertion or unverified result",
                field="cold_start_n",
                ref=claim.claim_ref,
            )
        )
    return TrustLayerDecision(accepted=not violations, violations=tuple(violations))


def validate_functional_independence(
    disclosure: FunctionalIndependenceDisclosure,
) -> TrustLayerDecision:
    violations: list[TrustLayerViolation] = []
    if disclosure.mode == "single_user" and disclosure.claims_organizational_independence:
        violations.append(
            TrustLayerViolation(
                "single_user_claimed_organizational_independence",
                "single-user mode may claim functional independence only, not organizational independence",
                field="claims_organizational_independence",
                ref=disclosure.disclosure_ref,
            )
        )
    if disclosure.mode == "single_user":
        for field_name in (
            "isolated_validation_ref",
            "immutable_evidence_ref",
            "second_confirmation_ref",
            "alternate_model_verification_ref",
        ):
            if not _present(getattr(disclosure, field_name)):
                violations.append(
                    TrustLayerViolation(
                        "functional_independence_ref_missing",
                        "functional independence requires isolated validation, immutable evidence, second confirmation, and alternate model verification",
                        field=field_name,
                        ref=disclosure.disclosure_ref,
                    )
                )
    if disclosure.mode == "organization" and not _present(disclosure.organization_process_ref):
        violations.append(
            TrustLayerViolation(
                "organization_independence_process_missing",
                "organizational independence requires a real organization process ref",
                field="organization_process_ref",
                ref=disclosure.disclosure_ref,
            )
        )
    return TrustLayerDecision(accepted=not violations, violations=tuple(violations))


def validate_external_expert_review(record: ExternalExpertReviewRecord) -> TrustLayerDecision:
    violations: list[TrustLayerViolation] = []
    for field_name in (
        "review_ref",
        "release_ref",
        "reviewer_ref",
        "reviewer_independence_ref",
        "artifact_ref",
        "review_protocol_ref",
        "verdict",
        "source_hash",
    ):
        if not _present(getattr(record, field_name)):
            violations.append(
                TrustLayerViolation(
                    "external_expert_review_required_field_missing",
                    "external expert review requires reviewer, independence, artifact, protocol, verdict, and source hash refs",
                    field=field_name,
                    ref=record.review_ref,
                )
            )
    reviewer_ref = str(record.reviewer_ref or "").strip().lower()
    if reviewer_ref.startswith("agent:") or reviewer_ref.startswith("system:") or reviewer_ref in {"self", "user"}:
        violations.append(
            TrustLayerViolation(
                "external_expert_review_not_external",
                "external expert review cannot be recorded as the agent, system, self, or generic user",
                field="reviewer_ref",
                ref=record.review_ref,
            )
        )
    verdict = str(record.verdict or "").strip().lower()
    if verdict not in {"approved", "vetoed", "needs_revision"}:
        violations.append(
            TrustLayerViolation(
                "external_expert_review_unknown_verdict",
                "external expert review verdict must be approved, vetoed, or needs_revision",
                field="verdict",
                ref=record.review_ref,
            )
        )
    if not _any_present(record.evidence_refs):
        violations.append(
            TrustLayerViolation(
                "external_expert_review_evidence_missing",
                "external expert review requires evidence refs",
                field="evidence_refs",
                ref=record.review_ref,
            )
        )
    if verdict == "approved" and not _present(record.signed_attestation_ref):
        violations.append(
            TrustLayerViolation(
                "external_expert_review_attestation_missing",
                "approved external expert review requires a signed attestation ref",
                field="signed_attestation_ref",
                ref=record.review_ref,
            )
        )
    if verdict in {"vetoed", "needs_revision"} and not _any_present(record.veto_reason_refs):
        violations.append(
            TrustLayerViolation(
                "external_expert_review_veto_reason_missing",
                "vetoed or needs_revision expert review requires veto or revision reason refs",
                field="veto_reason_refs",
                ref=record.review_ref,
            )
        )
    if record.silent_mock_fallback_used:
        violations.append(
            TrustLayerViolation(
                "external_expert_review_silent_mock_fallback",
                "external expert review cannot rely on silent mock fallback",
                field="silent_mock_fallback_used",
                ref=record.review_ref,
            )
        )
    return TrustLayerDecision(accepted=not violations, violations=tuple(violations))


def validate_external_reviewer_identity(record: ExternalReviewerIdentityRecord) -> TrustLayerDecision:
    violations: list[TrustLayerViolation] = []
    for field_name in (
        "identity_ref",
        "reviewer_ref",
        "identity_provider_ref",
        "public_key_ref",
        "public_key_pem",
        "reviewer_independence_ref",
    ):
        if not _present(getattr(record, field_name)):
            violations.append(
                TrustLayerViolation(
                    "external_reviewer_identity_required_field_missing",
                    "external reviewer identity requires reviewer, identity provider, public key, independence, and evidence refs",
                    field=field_name,
                    ref=record.identity_ref,
                )
            )
    reviewer_ref = str(record.reviewer_ref or "").strip().lower()
    if reviewer_ref.startswith("agent:") or reviewer_ref.startswith("system:") or reviewer_ref in {"self", "user"}:
        violations.append(
            TrustLayerViolation(
                "external_reviewer_identity_not_external",
                "external reviewer identity cannot be recorded as the agent, system, self, or generic user",
                field="reviewer_ref",
                ref=record.identity_ref,
            )
        )
    if not _any_present(record.evidence_refs):
        violations.append(
            TrustLayerViolation(
                "external_reviewer_identity_evidence_missing",
                "external reviewer identity requires evidence refs",
                field="evidence_refs",
                ref=record.identity_ref,
            )
        )
    if str(record.status or "").strip() not in {"active", "revoked"}:
        violations.append(
            TrustLayerViolation(
                "external_reviewer_identity_unknown_status",
                "external reviewer identity status must be active or revoked",
                field="status",
                ref=record.identity_ref,
            )
        )
    if _contains_secret_marker(
        {
            "identity_provider_ref": record.identity_provider_ref,
            "public_key_ref": record.public_key_ref,
            "public_key_pem": record.public_key_pem,
            "evidence_refs": record.evidence_refs,
        }
    ):
        violations.append(
            TrustLayerViolation(
                "external_reviewer_identity_plaintext_secret",
                "external reviewer identity cannot contain plaintext secret or private key",
                field="public_key_pem",
                ref=record.identity_ref,
            )
        )
    try:
        _load_ed25519_public_key(record.public_key_pem)
    except Exception:
        violations.append(
            TrustLayerViolation(
                "external_reviewer_identity_bad_public_key",
                "external reviewer identity public_key_pem must be a valid Ed25519 public key",
                field="public_key_pem",
                ref=record.identity_ref,
            )
        )
    return TrustLayerDecision(accepted=not violations, violations=tuple(violations))


def validate_external_expert_signature(
    record: ExternalExpertSignatureRecord,
    *,
    review: ExternalExpertReviewRecord,
    identity: ExternalReviewerIdentityRecord,
) -> TrustLayerDecision:
    violations: list[TrustLayerViolation] = []
    for field_name in (
        "verified_signature_ref",
        "attestation_ref",
        "review_ref",
        "reviewer_ref",
        "identity_ref",
        "public_key_ref",
        "public_key_fingerprint",
        "signed_payload_hash",
        "signature_b64",
    ):
        if not _present(getattr(record, field_name)):
            violations.append(
                TrustLayerViolation(
                    "external_expert_signature_required_field_missing",
                    "external expert signature verification requires review, identity, attestation, payload hash, and signature refs",
                    field=field_name,
                    ref=record.verified_signature_ref,
                )
            )
    if record.review_ref != review.review_ref:
        violations.append(
            TrustLayerViolation(
                "external_expert_signature_review_mismatch",
                "external expert signature review_ref must match the reviewed record",
                field="review_ref",
                ref=record.verified_signature_ref,
            )
        )
    if record.reviewer_ref != review.reviewer_ref or identity.reviewer_ref != review.reviewer_ref:
        violations.append(
            TrustLayerViolation(
                "external_expert_signature_reviewer_mismatch",
                "external expert signature reviewer must match the expert review and identity",
                field="reviewer_ref",
                ref=record.verified_signature_ref,
            )
        )
    if record.identity_ref != identity.identity_ref or record.public_key_ref != identity.public_key_ref:
        violations.append(
            TrustLayerViolation(
                "external_expert_signature_identity_mismatch",
                "external expert signature identity and public key refs must match the registered identity",
                field="identity_ref",
                ref=record.verified_signature_ref,
            )
        )
    if identity.status != "active":
        violations.append(
            TrustLayerViolation(
                "external_expert_signature_identity_revoked",
                "external expert signature requires an active reviewer identity",
                field="identity_ref",
                ref=record.verified_signature_ref,
            )
        )
    if review.signed_attestation_ref and record.attestation_ref != review.signed_attestation_ref:
        violations.append(
            TrustLayerViolation(
                "external_expert_signature_attestation_mismatch",
                "external expert signature attestation_ref must match the expert review",
                field="attestation_ref",
                ref=record.verified_signature_ref,
            )
        )
    payload = external_expert_review_signature_payload(review)
    payload_hash = "sha16:" + content_hash({"payload": payload.decode("utf-8")})
    if record.signed_payload_hash != payload_hash:
        violations.append(
            TrustLayerViolation(
                "external_expert_signature_payload_hash_mismatch",
                "external expert signature payload hash does not match the expert review payload",
                field="signed_payload_hash",
                ref=record.verified_signature_ref,
            )
        )
    if _contains_secret_marker(record.signature_b64):
        violations.append(
            TrustLayerViolation(
                "external_expert_signature_plaintext_secret",
                "external expert signature record cannot contain plaintext secret",
                field="signature_b64",
                ref=record.verified_signature_ref,
            )
        )
    if not violations:
        try:
            public_key = _load_ed25519_public_key(identity.public_key_pem)
            public_key.verify(base64.b64decode(record.signature_b64, validate=True), payload)
        except (InvalidSignature, ValueError, TypeError):
            violations.append(
                TrustLayerViolation(
                    "external_expert_signature_invalid",
                    "external expert signature does not verify against the registered reviewer identity",
                    field="signature_b64",
                    ref=record.verified_signature_ref,
                )
            )
    return TrustLayerDecision(accepted=not violations, violations=tuple(violations))


def validate_user_autonomy(record: UserAutonomyRecord) -> TrustLayerDecision:
    violations: list[TrustLayerViolation] = []
    if record.agent_made_final_choice or not _present(record.user_final_choice_ref):
        violations.append(
            TrustLayerViolation(
                "agent_made_user_methodology_or_risk_choice",
                "agent must recommend and disclose tradeoffs, not make the user's final methodology or risk choice",
                field="user_final_choice_ref",
                ref=record.choice_ref,
            )
        )
    for field_name in ("agent_recommendation_ref", "responsibility_boundary_ref"):
        if not _present(getattr(record, field_name)):
            violations.append(
                TrustLayerViolation(
                    "user_autonomy_disclosure_missing",
                    "user autonomy requires recommendation and responsibility boundary disclosure",
                    field=field_name,
                    ref=record.choice_ref,
                )
            )
    if not _any_present(record.tradeoff_refs) or not _any_present(record.alternative_path_refs):
        violations.append(
            TrustLayerViolation(
                "user_autonomy_options_missing",
                "user autonomy requires tradeoffs and alternative paths",
                field="tradeoff_refs",
                ref=record.choice_ref,
            )
        )
    if record.system_blocked_after_user_acceptance and not _any_present(record.redline_refs):
        violations.append(
            TrustLayerViolation(
                "non_redline_user_acceptance_blocked",
                "after user accepts responsibility, non-redline delivery should continue with disclosure",
                field="system_blocked_after_user_acceptance",
                ref=record.choice_ref,
            )
        )
    return TrustLayerDecision(accepted=not violations, violations=tuple(violations))


def validate_trust_release_gate(gate: TrustReleaseGateRecord) -> TrustLayerDecision:
    violations: list[TrustLayerViolation] = []
    for field_name in (
        "anti_flattery_pressure_test_ref",
        "multi_turn_pressure_test_ref",
        "expert_veto_ref",
        "weakness_collapse_check_ref",
        "mock_honesty_check_ref",
        "cold_start_honesty_check_ref",
    ):
        if not _present(getattr(gate, field_name)):
            violations.append(
                TrustLayerViolation(
                    "trust_release_gate_missing_check",
                    "trust release gate requires pressure, expert veto, weakness, mock, and cold-start checks",
                    field=field_name,
                    ref=gate.release_ref,
                )
            )
    return TrustLayerDecision(accepted=not violations, violations=tuple(violations))


def validate_trust_release_check(record: TrustReleaseCheckRecord) -> TrustLayerDecision:
    violations: list[TrustLayerViolation] = []
    for field_name in (
        "check_ref",
        "release_ref",
        "check_kind",
        "scenario_ref",
        "expected_behavior_ref",
        "observed_behavior_ref",
        "verdict",
        "source_hash",
    ):
        if not _present(getattr(record, field_name)):
            violations.append(
                TrustLayerViolation(
                    "trust_release_check_required_field_missing",
                    "trust release checks require refs, scenario, expected/observed behavior, verdict, and source hash",
                    field=field_name,
                    ref=record.check_ref,
                )
            )
    if record.check_kind not in TRUST_RELEASE_CHECK_KINDS:
        violations.append(
            TrustLayerViolation(
                "trust_release_check_unknown_kind",
                "trust release check kind is not part of the release gate contract",
                field="check_kind",
                ref=record.check_ref,
            )
        )
    if str(record.verdict).strip().lower() not in PASSING_VERDICTS:
        violations.append(
            TrustLayerViolation(
                "trust_release_check_not_cleared",
                "trust release checks require a passing verdict",
                field="verdict",
                ref=record.check_ref,
            )
        )
    if record.expected_behavior_ref != record.observed_behavior_ref:
        violations.append(
            TrustLayerViolation(
                "trust_release_check_behavior_mismatch",
                "trust release checks require observed behavior to match the expected behavior ref",
                field="observed_behavior_ref",
                ref=record.check_ref,
            )
        )
    for field_name, refs in (("evidence_refs", record.evidence_refs), ("validation_result_refs", record.validation_result_refs)):
        if not _any_present(refs):
            violations.append(
                TrustLayerViolation(
                    "trust_release_check_required_ref_missing",
                    "trust release checks require evidence and validation result refs",
                    field=field_name,
                    ref=record.check_ref,
                )
            )
    if record.silent_mock_fallback_used:
        violations.append(
            TrustLayerViolation(
                "trust_release_check_silent_mock_fallback",
                "trust release checks cannot rely on silent mock fallback",
                field="silent_mock_fallback_used",
                ref=record.check_ref,
            )
        )
    return TrustLayerDecision(accepted=not violations, violations=tuple(violations))


def validate_trust_pressure_run(record: TrustPressureRunRecord) -> TrustLayerDecision:
    violations: list[TrustLayerViolation] = []
    for field_name in (
        "runner_ref",
        "release_ref",
        "runner_mode",
        "source_hash",
        "release_gate_ref",
    ):
        if not _present(getattr(record, field_name)):
            violations.append(
                TrustLayerViolation(
                    "trust_pressure_run_required_field_missing",
                    "trust pressure runs require runner, release, mode, source hash, and release gate refs",
                    field=field_name,
                    ref=record.runner_ref,
                )
            )
    if record.runner_mode not in TRUST_PRESSURE_RUNNER_MODES:
        violations.append(
            TrustLayerViolation(
                "trust_pressure_run_unsafe_mode",
                "trust pressure runs are limited to local deterministic or test harness mode",
                field="runner_mode",
                ref=record.runner_ref,
            )
        )
    expected_count = len(TRUST_RELEASE_CHECK_KINDS)
    for field_name, refs in (
        ("check_refs", record.check_refs),
        ("scenario_refs", record.scenario_refs),
        ("evidence_refs", record.evidence_refs),
        ("validation_result_refs", record.validation_result_refs),
    ):
        if not _any_present(refs):
            violations.append(
                TrustLayerViolation(
                    "trust_pressure_run_required_refs_missing",
                    "trust pressure runs require check, scenario, evidence, and validation refs",
                    field=field_name,
                    ref=record.runner_ref,
                )
            )
    if len(record.check_refs) != expected_count:
        violations.append(
            TrustLayerViolation(
                "trust_pressure_run_incomplete_checks",
                "trust pressure runs must bind all release check refs",
                field="check_refs",
                ref=record.runner_ref,
            )
        )
    if len(record.scenario_refs) != expected_count:
        violations.append(
            TrustLayerViolation(
                "trust_pressure_run_incomplete_scenarios",
                "trust pressure runs must bind all release scenario refs",
                field="scenario_refs",
                ref=record.runner_ref,
            )
        )
    if len(set(record.check_refs)) != len(record.check_refs):
        violations.append(
            TrustLayerViolation(
                "trust_pressure_run_duplicate_check_ref",
                "trust pressure runs cannot reuse check refs",
                field="check_refs",
                ref=record.runner_ref,
            )
        )
    if record.failed_scenario_refs:
        violations.append(
            TrustLayerViolation(
                "trust_pressure_run_failed_scenario",
                "trust pressure runs cannot be recorded as passing while scenarios failed",
                field="failed_scenario_refs",
                ref=record.runner_ref,
            )
        )
    if record.silent_mock_fallback_used:
        violations.append(
            TrustLayerViolation(
                "trust_pressure_run_silent_mock_fallback",
                "trust pressure runs cannot rely on silent mock fallback",
                field="silent_mock_fallback_used",
                ref=record.runner_ref,
            )
        )
    return TrustLayerDecision(accepted=not violations, violations=tuple(violations))


def validate_trust_release_approval(record: TrustReleaseApprovalRecord) -> TrustLayerDecision:
    violations: list[TrustLayerViolation] = []
    for field_name in (
        "approval_ref",
        "release_ref",
        "release_gate_ref",
        "pressure_run_ref",
        "expert_review_ref",
        "artifact_ref",
        "approval_protocol_ref",
        "verdict",
        "source_hash",
    ):
        if not _present(getattr(record, field_name)):
            violations.append(
                TrustLayerViolation(
                    "trust_release_approval_required_field_missing",
                    "trust release approval requires release, gate, pressure run, expert review, artifact, protocol, verdict, and source hash refs",
                    field=field_name,
                    ref=record.approval_ref,
                )
            )
    verdict = str(record.verdict or "").strip().lower()
    if verdict not in {"approved", "blocked", "needs_revision"}:
        violations.append(
            TrustLayerViolation(
                "trust_release_approval_unknown_verdict",
                "trust release approval verdict must be approved, blocked, or needs_revision",
                field="verdict",
                ref=record.approval_ref,
            )
        )
    if not _any_present(record.evidence_refs):
        violations.append(
            TrustLayerViolation(
                "trust_release_approval_evidence_missing",
                "trust release approval requires evidence refs",
                field="evidence_refs",
                ref=record.approval_ref,
            )
        )
    if verdict == "approved" and not _present(record.signed_approval_ref):
        violations.append(
            TrustLayerViolation(
                "trust_release_approval_signature_missing",
                "approved trust release approval requires a signed approval ref",
                field="signed_approval_ref",
                ref=record.approval_ref,
            )
        )
    if verdict == "approved" and record.residual_blocker_refs:
        violations.append(
            TrustLayerViolation(
                "trust_release_approval_approved_with_blockers",
                "approved trust release approval cannot carry residual blocker refs",
                field="residual_blocker_refs",
                ref=record.approval_ref,
            )
        )
    if verdict in {"blocked", "needs_revision"} and not _any_present(record.residual_blocker_refs):
        violations.append(
            TrustLayerViolation(
                "trust_release_approval_blocker_missing",
                "blocked or needs_revision trust release approvals require residual blocker refs",
                field="residual_blocker_refs",
                ref=record.approval_ref,
            )
        )
    if record.silent_mock_fallback_used:
        violations.append(
            TrustLayerViolation(
                "trust_release_approval_silent_mock_fallback",
                "trust release approval cannot rely on silent mock fallback",
                field="silent_mock_fallback_used",
                ref=record.approval_ref,
            )
        )
    return TrustLayerDecision(accepted=not violations, violations=tuple(violations))


def record_trust_release_check(
    *,
    release_ref: str,
    check_kind: str,
    scenario_ref: str,
    expected_behavior_ref: str,
    observed_behavior_ref: str,
    evidence_refs: Any = (),
    validation_result_refs: Any = (),
    verdict: str = "passed",
    check_ref: str | None = None,
    silent_mock_fallback_used: bool = False,
) -> TrustReleaseCheckRecord:
    source_hash = content_hash(
        {
            "release_ref": release_ref,
            "check_kind": check_kind,
            "scenario_ref": scenario_ref,
            "expected_behavior_ref": expected_behavior_ref,
            "observed_behavior_ref": observed_behavior_ref,
            "verdict": verdict,
        }
    )
    prefix = CHECK_REF_PREFIXES.get(check_kind, "trust_check")
    record = TrustReleaseCheckRecord(
        check_ref=check_ref or prefix + ":" + content_hash({"source_hash": source_hash}),
        release_ref=release_ref,
        check_kind=check_kind,
        scenario_ref=scenario_ref,
        expected_behavior_ref=expected_behavior_ref,
        observed_behavior_ref=observed_behavior_ref,
        verdict=verdict,
        source_hash=source_hash,
        evidence_refs=tuple(str(v) for v in _tuple(evidence_refs)),
        validation_result_refs=tuple(str(v) for v in _tuple(validation_result_refs)),
        silent_mock_fallback_used=silent_mock_fallback_used,
    )
    decision = validate_trust_release_check(record)
    if not decision.accepted:
        raise ValueError(_decision_message(decision))
    return record


def record_trust_release_check_suite(
    *,
    release_ref: str,
    checks: Any,
) -> tuple[TrustReleaseGateRecord, tuple[TrustReleaseCheckRecord, ...]]:
    release_ref = str(release_ref or "").strip()
    if not _present(release_ref):
        raise ValueError("trust_release_check_suite_release_ref_missing")
    if not isinstance(checks, (list, tuple)):
        raise ValueError("trust_release_check_suite_checks_must_be_list")

    seen: set[str] = set()
    records: list[TrustReleaseCheckRecord] = []
    for raw_check in checks:
        if not isinstance(raw_check, dict):
            raise ValueError("trust_release_check_suite_check_payload_invalid")
        check_kind = str(raw_check.get("check_kind") or "")
        if check_kind in seen:
            raise ValueError("trust_release_check_suite_duplicate_kind")
        seen.add(check_kind)
        records.append(
            record_trust_release_check(
                release_ref=release_ref,
                check_kind=check_kind,
                scenario_ref=str(raw_check.get("scenario_ref") or ""),
                expected_behavior_ref=str(raw_check.get("expected_behavior_ref") or ""),
                observed_behavior_ref=str(raw_check.get("observed_behavior_ref") or ""),
                evidence_refs=_tuple(raw_check.get("evidence_refs")),
                validation_result_refs=_tuple(raw_check.get("validation_result_refs")),
                verdict=str(raw_check.get("verdict") or "passed"),
                check_ref=raw_check.get("check_ref"),
                silent_mock_fallback_used=_bool_value(raw_check.get("silent_mock_fallback_used")),
            )
        )

    missing = sorted(TRUST_RELEASE_CHECK_KINDS - seen)
    if missing:
        raise ValueError("trust_release_check_suite_missing_kind:" + ",".join(missing))
    extra = sorted(seen - TRUST_RELEASE_CHECK_KINDS)
    if extra:
        raise ValueError("trust_release_check_suite_unknown_kind:" + ",".join(extra))

    refs_by_field = {
        TRUST_RELEASE_GATE_FIELD_BY_CHECK_KIND[record.check_kind]: record.check_ref for record in records
    }
    gate = TrustReleaseGateRecord(
        release_ref=release_ref,
        anti_flattery_pressure_test_ref=refs_by_field.get("anti_flattery_pressure_test_ref"),
        multi_turn_pressure_test_ref=refs_by_field.get("multi_turn_pressure_test_ref"),
        expert_veto_ref=refs_by_field.get("expert_veto_ref"),
        weakness_collapse_check_ref=refs_by_field.get("weakness_collapse_check_ref"),
        mock_honesty_check_ref=refs_by_field.get("mock_honesty_check_ref"),
        cold_start_honesty_check_ref=refs_by_field.get("cold_start_honesty_check_ref"),
    )
    decision = validate_trust_release_gate(gate)
    if not decision.accepted:
        raise ValueError(_decision_message(decision))
    return gate, tuple(records)


def record_trust_pressure_run(
    *,
    release_ref: str,
    runner_mode: str,
    scenarios: Any,
    evidence_refs: Any = (),
    validation_result_refs: Any = (),
    runner_ref: str | None = None,
    silent_mock_fallback_used: bool = False,
) -> tuple[TrustPressureRunRecord, TrustReleaseGateRecord, tuple[TrustReleaseCheckRecord, ...]]:
    release_ref = str(release_ref or "").strip()
    runner_mode = str(runner_mode or "").strip()
    if not _present(release_ref):
        raise ValueError("trust_pressure_run_release_ref_missing")
    if runner_mode not in TRUST_PRESSURE_RUNNER_MODES:
        raise ValueError("trust_pressure_run_unsafe_mode")
    if not isinstance(scenarios, (list, tuple)):
        raise ValueError("trust_pressure_run_scenarios_must_be_list")

    run_evidence_refs = tuple(str(v) for v in _tuple(evidence_refs))
    run_validation_refs = tuple(str(v) for v in _tuple(validation_result_refs))
    if not run_evidence_refs:
        raise ValueError("trust_pressure_run_evidence_refs_missing")
    if not run_validation_refs:
        raise ValueError("trust_pressure_run_validation_result_refs_missing")

    seen: set[str] = set()
    failed: list[str] = []
    normalized: list[dict[str, Any]] = []
    checks_for_suite: list[dict[str, Any]] = []
    for raw_scenario in scenarios:
        if not isinstance(raw_scenario, dict):
            raise ValueError("trust_pressure_run_scenario_payload_invalid")
        check_kind = str(raw_scenario.get("check_kind") or "")
        scenario_ref = str(raw_scenario.get("scenario_ref") or "")
        expected_behavior_ref = str(raw_scenario.get("expected_behavior_ref") or "")
        observed_behavior_ref = str(raw_scenario.get("observed_behavior_ref") or "")
        outcome_flags = tuple(str(v).strip() for v in _tuple(raw_scenario.get("outcome_flags")) if str(v).strip())
        if check_kind in seen:
            raise ValueError("trust_pressure_run_duplicate_kind")
        seen.add(check_kind)
        if not _present(scenario_ref):
            raise ValueError("trust_pressure_run_scenario_ref_missing")
        if not _present(expected_behavior_ref) or not _present(observed_behavior_ref):
            raise ValueError("trust_pressure_run_behavior_ref_missing")
        if expected_behavior_ref != observed_behavior_ref or outcome_flags:
            failed.append(scenario_ref or check_kind)
        scenario_evidence_refs = tuple(str(v) for v in _tuple(raw_scenario.get("evidence_refs")))
        scenario_validation_refs = tuple(str(v) for v in _tuple(raw_scenario.get("validation_result_refs")))
        if not scenario_evidence_refs:
            raise ValueError("trust_pressure_run_scenario_evidence_refs_missing")
        normalized.append(
            {
                "check_kind": check_kind,
                "scenario_ref": scenario_ref,
                "expected_behavior_ref": expected_behavior_ref,
                "observed_behavior_ref": observed_behavior_ref,
                "evidence_refs": scenario_evidence_refs,
                "validation_result_refs": scenario_validation_refs,
                "outcome_flags": outcome_flags,
            }
        )

    missing = sorted(TRUST_RELEASE_CHECK_KINDS - seen)
    if missing:
        raise ValueError("trust_pressure_run_missing_kind:" + ",".join(missing))
    extra = sorted(seen - TRUST_RELEASE_CHECK_KINDS)
    if extra:
        raise ValueError("trust_pressure_run_unknown_kind:" + ",".join(extra))
    if failed:
        raise ValueError("trust_pressure_run_failed_scenario:" + ",".join(failed))

    source_hash = content_hash(
        {
            "release_ref": release_ref,
            "runner_mode": runner_mode,
            "scenarios": normalized,
            "evidence_refs": run_evidence_refs,
            "validation_result_refs": run_validation_refs,
        }
    )
    runner_ref = runner_ref or "trust_pressure_run:" + content_hash({"source_hash": source_hash})
    for item in normalized:
        check_validation_refs = tuple(item["validation_result_refs"]) + tuple(run_validation_refs) + (
            runner_ref + ":" + item["check_kind"],
        )
        checks_for_suite.append(
            {
                "check_kind": item["check_kind"],
                "scenario_ref": item["scenario_ref"],
                "expected_behavior_ref": item["expected_behavior_ref"],
                "observed_behavior_ref": item["observed_behavior_ref"],
                "evidence_refs": tuple(item["evidence_refs"]) + run_evidence_refs,
                "validation_result_refs": check_validation_refs,
            }
        )

    gate, checks = record_trust_release_check_suite(release_ref=release_ref, checks=checks_for_suite)
    record = TrustPressureRunRecord(
        runner_ref=runner_ref,
        release_ref=release_ref,
        runner_mode=runner_mode,
        source_hash=source_hash,
        release_gate_ref=gate.release_ref,
        check_refs=tuple(check.check_ref for check in checks),
        scenario_refs=tuple(str(item["scenario_ref"]) for item in normalized),
        evidence_refs=run_evidence_refs,
        validation_result_refs=run_validation_refs,
        failed_scenario_refs=(),
        silent_mock_fallback_used=silent_mock_fallback_used,
    )
    decision = validate_trust_pressure_run(record)
    if not decision.accepted:
        raise ValueError(_decision_message(decision))
    return record, gate, checks


def record_trust_release_approval(
    *,
    release_ref: str,
    release_gate: TrustReleaseGateRecord,
    pressure_run: TrustPressureRunRecord,
    expert_review: ExternalExpertReviewRecord,
    artifact_ref: str,
    approval_protocol_ref: str,
    verdict: str,
    evidence_refs: Any = (),
    signed_approval_ref: str | None = None,
    residual_blocker_refs: Any = (),
    approval_ref: str | None = None,
    silent_mock_fallback_used: bool = False,
) -> TrustReleaseApprovalRecord:
    release_ref = str(release_ref or "").strip()
    if not _present(release_ref):
        raise ValueError("trust_release_approval_release_ref_missing")
    if release_gate.release_ref != release_ref:
        raise ValueError("trust_release_approval_gate_release_mismatch")
    if pressure_run.release_ref != release_ref:
        raise ValueError("trust_release_approval_pressure_run_release_mismatch")
    if pressure_run.release_gate_ref != release_gate.release_ref:
        raise ValueError("trust_release_approval_pressure_run_gate_mismatch")
    if expert_review.release_ref != release_ref:
        raise ValueError("trust_release_approval_expert_review_release_mismatch")

    for decision in (
        validate_trust_release_gate(release_gate),
        validate_trust_pressure_run(pressure_run),
        validate_external_expert_review(expert_review),
    ):
        if not decision.accepted:
            raise ValueError(_decision_message(decision))

    verdict = str(verdict or "").strip().lower()
    review_verdict = str(expert_review.verdict or "").strip().lower()
    if verdict == "approved" and review_verdict != "approved":
        raise ValueError("trust_release_approval_expert_review_not_approved")

    normalized_evidence_refs = tuple(str(v) for v in _tuple(evidence_refs))
    normalized_blocker_refs = tuple(str(v) for v in _tuple(residual_blocker_refs))
    source_hash = content_hash(
        {
            "release_ref": release_ref,
            "release_gate_ref": release_gate.release_ref,
            "pressure_run_ref": pressure_run.runner_ref,
            "expert_review_ref": expert_review.review_ref,
            "artifact_ref": artifact_ref,
            "approval_protocol_ref": approval_protocol_ref,
            "verdict": verdict,
            "evidence_refs": normalized_evidence_refs,
            "signed_approval_ref": signed_approval_ref,
            "residual_blocker_refs": normalized_blocker_refs,
        }
    )
    record = TrustReleaseApprovalRecord(
        approval_ref=approval_ref or "trust_release_approval:" + content_hash({"source_hash": source_hash}),
        release_ref=release_ref,
        release_gate_ref=release_gate.release_ref,
        pressure_run_ref=pressure_run.runner_ref,
        expert_review_ref=expert_review.review_ref,
        artifact_ref=str(artifact_ref or ""),
        approval_protocol_ref=str(approval_protocol_ref or ""),
        verdict=verdict,
        source_hash=source_hash,
        evidence_refs=normalized_evidence_refs,
        signed_approval_ref=signed_approval_ref,
        residual_blocker_refs=normalized_blocker_refs,
        silent_mock_fallback_used=silent_mock_fallback_used,
    )
    decision = validate_trust_release_approval(record)
    if not decision.accepted:
        raise ValueError(_decision_message(decision))
    return record


def record_external_expert_review(
    *,
    release_ref: str,
    reviewer_ref: str,
    reviewer_independence_ref: str,
    artifact_ref: str,
    review_protocol_ref: str,
    verdict: str,
    evidence_refs: Any = (),
    veto_reason_refs: Any = (),
    signed_attestation_ref: str | None = None,
    review_ref: str | None = None,
    silent_mock_fallback_used: bool = False,
) -> ExternalExpertReviewRecord:
    source_hash = content_hash(
        {
            "release_ref": release_ref,
            "reviewer_ref": reviewer_ref,
            "reviewer_independence_ref": reviewer_independence_ref,
            "artifact_ref": artifact_ref,
            "review_protocol_ref": review_protocol_ref,
            "verdict": verdict,
            "evidence_refs": tuple(str(v) for v in _tuple(evidence_refs)),
            "veto_reason_refs": tuple(str(v) for v in _tuple(veto_reason_refs)),
            "signed_attestation_ref": signed_attestation_ref,
        }
    )
    record = ExternalExpertReviewRecord(
        review_ref=review_ref or "expert_review:" + content_hash({"source_hash": source_hash}),
        release_ref=str(release_ref or ""),
        reviewer_ref=str(reviewer_ref or ""),
        reviewer_independence_ref=str(reviewer_independence_ref or ""),
        artifact_ref=str(artifact_ref or ""),
        review_protocol_ref=str(review_protocol_ref or ""),
        verdict=str(verdict or ""),
        source_hash=source_hash,
        evidence_refs=tuple(str(v) for v in _tuple(evidence_refs)),
        veto_reason_refs=tuple(str(v) for v in _tuple(veto_reason_refs)),
        signed_attestation_ref=signed_attestation_ref,
        silent_mock_fallback_used=silent_mock_fallback_used,
    )
    decision = validate_external_expert_review(record)
    if not decision.accepted:
        raise ValueError(_decision_message(decision))
    return record


def validate_trust_layer(
    *,
    claims: tuple[TrustClaimRecord, ...] = (),
    independence_disclosures: tuple[FunctionalIndependenceDisclosure, ...] = (),
    expert_reviews: tuple[ExternalExpertReviewRecord, ...] = (),
    user_choices: tuple[UserAutonomyRecord, ...] = (),
    release_gates: tuple[TrustReleaseGateRecord, ...] = (),
    release_checks: tuple[TrustReleaseCheckRecord, ...] = (),
    pressure_runs: tuple[TrustPressureRunRecord, ...] = (),
    release_approvals: tuple[TrustReleaseApprovalRecord, ...] = (),
) -> TrustLayerDecision:
    violations: list[TrustLayerViolation] = []
    for claim in claims:
        violations.extend(validate_trust_claim(claim).violations)
    for disclosure in independence_disclosures:
        violations.extend(validate_functional_independence(disclosure).violations)
    for review in expert_reviews:
        violations.extend(validate_external_expert_review(review).violations)
    for choice in user_choices:
        violations.extend(validate_user_autonomy(choice).violations)
    for gate in release_gates:
        violations.extend(validate_trust_release_gate(gate).violations)
    for check in release_checks:
        violations.extend(validate_trust_release_check(check).violations)
    for run in pressure_runs:
        violations.extend(validate_trust_pressure_run(run).violations)
    for approval in release_approvals:
        violations.extend(validate_trust_release_approval(approval).violations)

    # Cross-record resolution (anti-gaming): a release approval's linkage refs must
    # resolve to a real, co-submitted record in the SAME batch. The per-record
    # validators above check each record in isolation, so an orphaned ref (pointing
    # at a record that was never submitted) would otherwise slip an approval through.
    # This mirrors the linkage record_trust_release_approval() enforces at construction.
    # Refs that are blank/missing are left to the per-record required-field check above;
    # here we only flag refs that are present yet dangle (resolve to nothing).
    review_refs = {_value(r.review_ref) for r in expert_reviews if _present(r.review_ref)}
    pressure_run_refs = {_value(r.runner_ref) for r in pressure_runs if _present(r.runner_ref)}
    release_gate_refs = {_value(g.release_ref) for g in release_gates if _present(g.release_ref)}
    for approval in release_approvals:
        for field_name, ref_value, known_refs, code in (
            (
                "expert_review_ref",
                approval.expert_review_ref,
                review_refs,
                "trust_release_approval_expert_review_unresolved",
            ),
            (
                "pressure_run_ref",
                approval.pressure_run_ref,
                pressure_run_refs,
                "trust_release_approval_pressure_run_unresolved",
            ),
            (
                "release_gate_ref",
                approval.release_gate_ref,
                release_gate_refs,
                "trust_release_approval_release_gate_unresolved",
            ),
        ):
            if _present(ref_value) and _value(ref_value) not in known_refs:
                violations.append(
                    TrustLayerViolation(
                        code,
                        "trust release approval refs must resolve to a co-submitted trust record in the same batch",
                        field=field_name,
                        ref=approval.approval_ref,
                    )
                )
    return TrustLayerDecision(accepted=not violations, violations=tuple(violations))


def _decision_message(decision: TrustLayerDecision) -> str:
    return "; ".join(f"{v.code}:{v.field}" for v in decision.violations) or "trust-layer record rejected"


def trust_claim_record_from_dict(data: dict[str, Any]) -> TrustClaimRecord:
    cold_start_n = data.get("cold_start_n")
    return TrustClaimRecord(
        claim_ref=str(data.get("claim_ref") or ""),
        claim_label=str(data.get("claim_label") or ""),
        evidence_refs=_tuple(data.get("evidence_refs")),
        weakness_refs=_tuple(data.get("weakness_refs")),
        weakness_visible_by_default=_bool_value(data.get("weakness_visible_by_default"), default=True),
        cold_start_n=int(cold_start_n) if cold_start_n not in (None, "") else None,
        pressure_context=str(data.get("pressure_context") or ""),
        user_waiver_ref=data.get("user_waiver_ref"),
        waiver_weakness_visible_by_default=_bool_value(
            data.get("waiver_weakness_visible_by_default"),
            default=True,
        ),
    )


def functional_independence_disclosure_from_dict(
    data: dict[str, Any],
) -> FunctionalIndependenceDisclosure:
    return FunctionalIndependenceDisclosure(
        disclosure_ref=str(data.get("disclosure_ref") or ""),
        mode=str(data.get("mode") or ""),
        claims_organizational_independence=_bool_value(data.get("claims_organizational_independence")),
        isolated_validation_ref=data.get("isolated_validation_ref"),
        immutable_evidence_ref=data.get("immutable_evidence_ref"),
        second_confirmation_ref=data.get("second_confirmation_ref"),
        alternate_model_verification_ref=data.get("alternate_model_verification_ref"),
        organization_process_ref=data.get("organization_process_ref"),
    )


def external_expert_review_from_dict(data: dict[str, Any]) -> ExternalExpertReviewRecord:
    return ExternalExpertReviewRecord(
        review_ref=str(data.get("review_ref") or ""),
        release_ref=str(data.get("release_ref") or ""),
        reviewer_ref=str(data.get("reviewer_ref") or ""),
        reviewer_independence_ref=str(data.get("reviewer_independence_ref") or ""),
        artifact_ref=str(data.get("artifact_ref") or ""),
        review_protocol_ref=str(data.get("review_protocol_ref") or ""),
        verdict=str(data.get("verdict") or ""),
        source_hash=str(data.get("source_hash") or ""),
        evidence_refs=_tuple(data.get("evidence_refs")),
        veto_reason_refs=_tuple(data.get("veto_reason_refs")),
        signed_attestation_ref=data.get("signed_attestation_ref"),
        silent_mock_fallback_used=_bool_value(data.get("silent_mock_fallback_used")),
    )


def external_reviewer_identity_from_dict(data: dict[str, Any]) -> ExternalReviewerIdentityRecord:
    return ExternalReviewerIdentityRecord(
        identity_ref=str(data.get("identity_ref") or ""),
        reviewer_ref=str(data.get("reviewer_ref") or ""),
        identity_provider_ref=str(data.get("identity_provider_ref") or ""),
        public_key_ref=str(data.get("public_key_ref") or ""),
        public_key_pem=str(data.get("public_key_pem") or ""),
        reviewer_independence_ref=str(data.get("reviewer_independence_ref") or ""),
        evidence_refs=_tuple(data.get("evidence_refs")),
        public_key_fingerprint=str(data.get("public_key_fingerprint") or ""),
        status=str(data.get("status") or "active"),
        identity_hash=str(data.get("identity_hash") or ""),
    )


def external_expert_signature_from_dict(data: dict[str, Any]) -> ExternalExpertSignatureRecord:
    return ExternalExpertSignatureRecord(
        verified_signature_ref=str(data.get("verified_signature_ref") or ""),
        attestation_ref=str(data.get("attestation_ref") or ""),
        review_ref=str(data.get("review_ref") or ""),
        reviewer_ref=str(data.get("reviewer_ref") or ""),
        identity_ref=str(data.get("identity_ref") or ""),
        public_key_ref=str(data.get("public_key_ref") or ""),
        public_key_fingerprint=str(data.get("public_key_fingerprint") or ""),
        signed_payload_hash=str(data.get("signed_payload_hash") or ""),
        signature_b64=str(data.get("signature_b64") or ""),
        verified_at=str(data.get("verified_at") or ""),
        verification_hash=str(data.get("verification_hash") or ""),
        verification_version=str(data.get("verification_version") or "trust.external_expert_signature.v1"),
    )


def user_autonomy_record_from_dict(data: dict[str, Any]) -> UserAutonomyRecord:
    return UserAutonomyRecord(
        choice_ref=str(data.get("choice_ref") or ""),
        agent_recommendation_ref=data.get("agent_recommendation_ref"),
        tradeoff_refs=_tuple(data.get("tradeoff_refs")),
        alternative_path_refs=_tuple(data.get("alternative_path_refs")),
        responsibility_boundary_ref=data.get("responsibility_boundary_ref"),
        user_final_choice_ref=data.get("user_final_choice_ref"),
        agent_made_final_choice=_bool_value(data.get("agent_made_final_choice")),
        system_blocked_after_user_acceptance=_bool_value(data.get("system_blocked_after_user_acceptance")),
        redline_refs=_tuple(data.get("redline_refs")),
    )


def trust_release_gate_record_from_dict(data: dict[str, Any]) -> TrustReleaseGateRecord:
    return TrustReleaseGateRecord(
        release_ref=str(data.get("release_ref") or ""),
        anti_flattery_pressure_test_ref=data.get("anti_flattery_pressure_test_ref"),
        multi_turn_pressure_test_ref=data.get("multi_turn_pressure_test_ref"),
        expert_veto_ref=data.get("expert_veto_ref"),
        weakness_collapse_check_ref=data.get("weakness_collapse_check_ref"),
        mock_honesty_check_ref=data.get("mock_honesty_check_ref"),
        cold_start_honesty_check_ref=data.get("cold_start_honesty_check_ref"),
    )


def trust_release_check_record_from_dict(data: dict[str, Any]) -> TrustReleaseCheckRecord:
    return TrustReleaseCheckRecord(
        check_ref=str(data.get("check_ref") or ""),
        release_ref=str(data.get("release_ref") or ""),
        check_kind=str(data.get("check_kind") or ""),
        scenario_ref=str(data.get("scenario_ref") or ""),
        expected_behavior_ref=str(data.get("expected_behavior_ref") or ""),
        observed_behavior_ref=str(data.get("observed_behavior_ref") or ""),
        verdict=str(data.get("verdict") or ""),
        source_hash=str(data.get("source_hash") or ""),
        evidence_refs=_tuple(data.get("evidence_refs")),
        validation_result_refs=_tuple(data.get("validation_result_refs")),
        silent_mock_fallback_used=bool(data.get("silent_mock_fallback_used", False)),
    )


def trust_pressure_run_record_from_dict(data: dict[str, Any]) -> TrustPressureRunRecord:
    return TrustPressureRunRecord(
        runner_ref=str(data.get("runner_ref") or ""),
        release_ref=str(data.get("release_ref") or ""),
        runner_mode=str(data.get("runner_mode") or ""),
        source_hash=str(data.get("source_hash") or ""),
        release_gate_ref=str(data.get("release_gate_ref") or ""),
        check_refs=_tuple(data.get("check_refs")),
        scenario_refs=_tuple(data.get("scenario_refs")),
        evidence_refs=_tuple(data.get("evidence_refs")),
        validation_result_refs=_tuple(data.get("validation_result_refs")),
        failed_scenario_refs=_tuple(data.get("failed_scenario_refs")),
        silent_mock_fallback_used=_bool_value(data.get("silent_mock_fallback_used")),
    )


def trust_release_approval_record_from_dict(data: dict[str, Any]) -> TrustReleaseApprovalRecord:
    return TrustReleaseApprovalRecord(
        approval_ref=str(data.get("approval_ref") or ""),
        release_ref=str(data.get("release_ref") or ""),
        release_gate_ref=str(data.get("release_gate_ref") or ""),
        pressure_run_ref=str(data.get("pressure_run_ref") or ""),
        expert_review_ref=str(data.get("expert_review_ref") or ""),
        artifact_ref=str(data.get("artifact_ref") or ""),
        approval_protocol_ref=str(data.get("approval_protocol_ref") or ""),
        verdict=str(data.get("verdict") or ""),
        source_hash=str(data.get("source_hash") or ""),
        evidence_refs=_tuple(data.get("evidence_refs")),
        signed_approval_ref=data.get("signed_approval_ref"),
        residual_blocker_refs=_tuple(data.get("residual_blocker_refs")),
        silent_mock_fallback_used=_bool_value(data.get("silent_mock_fallback_used")),
    )


# ════════════════════════════════════════════════════════════════════════════
# §13 信任结构 → promote manifest section record（producer · NC-S13-TRUST-PRODUCER）
# ────────────────────────────────────────────────────────────────────────────
# 缺口（construction-map NC-S13-TRUST-PRODUCER）：信任判定层今 advisory-only —— promote 真路径从未把真信任
# 记录如实组装进 manifest，故 `release_gate.section13_trust_gate` 恒见「未声明」→ 证据 producer
# `s13_trust_runjson_producers` 无真对象、无从诚实转绿（门停 advisory）。本段补 producer 侧：从**真信任记录**
# （typed 对象·下方 canonical record 类型）如实序列化成 §13 节门的 producer 契约 dict —— 让节门有真对象可判
# （合规 run 过、谄媚强结论 / 弱点折叠 / mock 不诚实 / 冷启动冒充统计证据 run 拒）。
#
# 复用不重造（RULES §1 单一源）：**只序列化·零判定**。信任判定（反谄媚 / 弱点折叠 / mock 诚实 / 冷启动 /
# 专家否决 / 跨记录解析）全留给 `section13_trust_gate.section13_trust_check → validate_trust_layer`，本段绝不
# 重写 / 预判 / 过滤 / 洗白任何一条信任门。序列化器复用 `_json_value`（= `_canonical_bytes` 哈希同源·
# dataclass→asdict→enum→value→tuple→list），与各 `*_from_dict` 读的 key 天然往返对齐（asdict 出全字段·一个
# 不漏 → from_dict 逐字段读回）。
#
# 诚实红线（= GOAL §13「不得伪造 proof-backed / evidence sufficient / production-ready·不得隐藏 user waiver·
# 不得让 secret / no-silent-mock 被 waiver 绕过」对准本 producer 自己）：
#   - **缺即真缺（honest-absent）**：某族无真记录 → **不发该 family key**；全族皆空 → 返回 `{}`（中心
#     `assemble_promote_sections._take` 据 `if payload` honest-absent·不发 section13_trust 节）。节门对「未声明」
#     honest-bound（不声明≠违例·ok=True），故不误拒「只是没声明信任结构」的诚实 run。**绝不**发空壳 / 占位
#     记录让门误判合规（= 假绿灯·撞 RULES.project「未验证≠已验证」）。
#   - **faithful 序列化（无损·零洗白）**：坏记录（谄媚强标签 / 弱点默认隐藏 / `silent_mock_fallback_used=True` /
#     冷启动 N≤1 / `user_waiver_ref` 在而 `waiver_weakness_visible_by_default=False`）**如实序列化** → 节门
#     round-trip 回 record 据真值拒。**绝不**丢字段 / 改值：丢 `silent_mock_fallback_used` 就是洗白 mock 不诚实
#     （削弱 no-silent-mock 命门）；改 `waiver_weakness_visible_by_default` 就是藏 user waiver。asdict 出全字段
#     正是为「一个命门字段都漏不掉」。
#   - **fail-closed 入参**：某族喂非该族 canonical 类型的对象 → raise `TypeError`（不静默吞坏输入·不产占位 dict
#     蒙混 —— 占位 dict 经 from_dict 默认值可能假装合规 = 假绿灯）。
#
# 中心串接（CENTER-SERIAL·非本卡·本卡 PARALLEL-SAFE 只建孤立 builder·绝不碰 promote_assembler）：中心在
# `promote_assembler.assemble_promote_sections` 经
#   `_take(SECTION13_TRUST_MANIFEST_KEY, build_section13_trust_record(...), undeclared_gap)`
# 把本 record 并进 manifest（key 从 `section13_trust_gate.SECTION13_TRUST_MANIFEST_KEY` 单一源 import），再走
# 门链 `evaluate`。
# ════════════════════════════════════════════════════════════════════════════

# family manifest key ↔ canonical record 类型（与 `section13_trust_gate._FAMILIES` 的
# `(manifest_key, validate_trust_layer kwarg)` 一一对齐）。单一源是 gate 的 `_FAMILIES`；本模块（trust_layer·
# 低层 domain）**不** import release_gate（防层级倒挂 / 冷导入环），故 family key 在此复述、由
# `tests/test_s13_trust_producer.py` 的跨模块契约绑定测试钉死防漂 —— gate 改任一 family key → 绑定测试立刻 RED。
_SECTION13_TRUST_FAMILY_TYPES: tuple[tuple[str, type], ...] = (
    ("trust_claims", TrustClaimRecord),
    ("independence_disclosures", FunctionalIndependenceDisclosure),
    ("expert_reviews", ExternalExpertReviewRecord),
    ("user_choices", UserAutonomyRecord),
    ("release_gates", TrustReleaseGateRecord),
    ("release_checks", TrustReleaseCheckRecord),
    ("pressure_runs", TrustPressureRunRecord),
    ("release_approvals", TrustReleaseApprovalRecord),
)


def _serialize_trust_family(
    records: Any, expected_type: type, manifest_key: str
) -> list[dict[str, Any]]:
    """一族信任 typed 记录 → faithful dict list（fail-closed 类型校验·零判定·零洗白）。

    复用 `_json_value`（canonical 序列化器·与 `_canonical_bytes` 哈希同源）逐字段无损落 dict —— asdict 出全
    字段（含 `silent_mock_fallback_used` / `weakness_visible_by_default` / `user_waiver_ref` 等命门字段），一个
    不漏、不改值。喂非 `expected_type` 对象 → raise `TypeError`（不静默吞坏输入·不产占位 → 占位经 from_dict
    默认值可能假装合规 = 假绿灯）。**★ mutation 锚点**：把下方 `serialized = _json_value(rec)` 改成丢某命门
    字段（如 `silent_mock_fallback_used`）→ producer 洗白该违例 → 对抗测试转 RED（见 test_s13_trust_producer
    文件头 mutation 三态）。
    """

    out: list[dict[str, Any]] = []
    for rec in _tuple(records):
        if not isinstance(rec, expected_type):
            raise TypeError(
                f"build_section13_trust_record: {manifest_key} 须为 {expected_type.__name__}，"
                f"得到 {type(rec).__name__}（fail-closed·不静默吞坏输入·不伪造 section13_trust 记录）"
            )
        serialized = _json_value(rec)  # ★ mutation 锚点（丢命门字段 → 对抗测试 RED）
        if not isinstance(serialized, dict):  # 防御：record 非 dataclass（理应被上方类型挡住）
            raise TypeError(
                f"build_section13_trust_record: {manifest_key} 记录序列化非 dict（fail-closed）"
            )
        out.append(serialized)
    return out


def build_section13_trust_record(
    *,
    claims: Sequence[TrustClaimRecord] = (),
    independence_disclosures: Sequence[FunctionalIndependenceDisclosure] = (),
    expert_reviews: Sequence[ExternalExpertReviewRecord] = (),
    user_choices: Sequence[UserAutonomyRecord] = (),
    release_gates: Sequence[TrustReleaseGateRecord] = (),
    release_checks: Sequence[TrustReleaseCheckRecord] = (),
    pressure_runs: Sequence[TrustPressureRunRecord] = (),
    release_approvals: Sequence[TrustReleaseApprovalRecord] = (),
) -> dict[str, Any]:
    """真信任 typed 记录 → `section13_trust` manifest section dict（producer·honest-absent·零判定）。

    入参 = `validate_trust_layer` 的 8 族 typed 记录（trust_layer canonical 类型·不另造）。每族非空 → faithful
    序列化进对应 family key（= `section13_trust_gate._FAMILIES` 的 manifest_key）；某族空 → 不发其 key；全族皆空
    → 返回 `{}`（honest-absent·中心据此不发 section13_trust 节·门不误拒未声明 run）。

    **只序列化·零判定**：信任判定（谄媚 / 弱点折叠 / mock 诚实 / 冷启动 / 专家否决 / 跨记录解析）全在
    `section13_trust_gate.section13_trust_check → validate_trust_layer`，本函数绝不重写 / 预判 / 洗白。坏记录如实
    序列化 → 门据真值拒（这正是 producer 转绿后门翻 enforce 能拒坏 run、又不误伤诚实 run 的前提）。
    """

    families: dict[str, Any] = {
        "trust_claims": claims,
        "independence_disclosures": independence_disclosures,
        "expert_reviews": expert_reviews,
        "user_choices": user_choices,
        "release_gates": release_gates,
        "release_checks": release_checks,
        "pressure_runs": pressure_runs,
        "release_approvals": release_approvals,
    }
    section: dict[str, Any] = {}
    for manifest_key, expected_type in _SECTION13_TRUST_FAMILY_TYPES:
        serialized = _serialize_trust_family(families[manifest_key], expected_type, manifest_key)
        if serialized:
            section[manifest_key] = serialized
    return section


class PersistentTrustDisclosureRegistry:
    """Append-only JSONL store for trust claims and disclosure records."""

    def __init__(self, path: str | Path) -> None:
        self._path = Path(path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._claims: dict[str, TrustClaimRecord] = {}
        self._independence_disclosures: dict[str, FunctionalIndependenceDisclosure] = {}
        self._expert_reviews: dict[str, ExternalExpertReviewRecord] = {}
        self._user_autonomy_records: dict[str, UserAutonomyRecord] = {}
        self._load_existing()

    @property
    def path(self) -> Path:
        return self._path

    def _load_existing(self) -> None:
        if not self._path.exists():
            return
        with self._path.open("r", encoding="utf-8") as fh:
            for line_no, line in enumerate(fh, start=1):
                if not line.strip():
                    continue
                try:
                    row = json.loads(line)
                    self._apply_row(row, persist=False)
                except Exception as exc:  # noqa: BLE001
                    raise ValueError(f"invalid persisted Trust Disclosure row at {self._path}:{line_no}") from exc

    def _append_event(self, row: dict[str, Any]) -> None:
        with self._path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n")
            fh.flush()

    def _apply_row(self, row: dict[str, Any], *, persist: bool) -> Any:
        if row.get("schema_version") != 1:
            raise ValueError("unsupported Trust Disclosure schema_version")
        event_type = row.get("event_type")
        if event_type == "trust_claim_recorded":
            raw = row.get("trust_claim")
            if not isinstance(raw, dict):
                raise ValueError("Trust Disclosure event missing trust_claim")
            return self.record_claim(trust_claim_record_from_dict(raw), persist=persist)
        if event_type == "functional_independence_disclosure_recorded":
            raw = row.get("independence_disclosure")
            if not isinstance(raw, dict):
                raise ValueError("Trust Disclosure event missing independence_disclosure")
            return self.record_independence_disclosure(
                functional_independence_disclosure_from_dict(raw),
                persist=persist,
            )
        if event_type == "external_expert_review_recorded":
            raw = row.get("external_expert_review")
            if not isinstance(raw, dict):
                raise ValueError("Trust Disclosure event missing external_expert_review")
            return self.record_external_expert_review(external_expert_review_from_dict(raw), persist=persist)
        if event_type == "user_autonomy_recorded":
            raw = row.get("user_autonomy")
            if not isinstance(raw, dict):
                raise ValueError("Trust Disclosure event missing user_autonomy")
            return self.record_user_autonomy(user_autonomy_record_from_dict(raw), persist=persist)
        raise ValueError(f"unknown Trust Disclosure event_type={event_type!r}")

    def record_claim(
        self,
        record: TrustClaimRecord,
        *,
        persist: bool = True,
    ) -> TrustClaimRecord:
        decision = validate_trust_claim(record)
        if not decision.accepted:
            raise ValueError(_decision_message(decision))
        self._claims[record.claim_ref] = record
        if persist:
            self._append_event(
                {
                    "schema_version": 1,
                    "event_type": "trust_claim_recorded",
                    "trust_claim": _json_value(record),
                }
            )
        return record

    def record_independence_disclosure(
        self,
        record: FunctionalIndependenceDisclosure,
        *,
        persist: bool = True,
    ) -> FunctionalIndependenceDisclosure:
        decision = validate_functional_independence(record)
        if not decision.accepted:
            raise ValueError(_decision_message(decision))
        self._independence_disclosures[record.disclosure_ref] = record
        if persist:
            self._append_event(
                {
                    "schema_version": 1,
                    "event_type": "functional_independence_disclosure_recorded",
                    "independence_disclosure": _json_value(record),
                }
            )
        return record

    def record_user_autonomy(
        self,
        record: UserAutonomyRecord,
        *,
        persist: bool = True,
    ) -> UserAutonomyRecord:
        decision = validate_user_autonomy(record)
        if not decision.accepted:
            raise ValueError(_decision_message(decision))
        self._user_autonomy_records[record.choice_ref] = record
        if persist:
            self._append_event(
                {
                    "schema_version": 1,
                    "event_type": "user_autonomy_recorded",
                    "user_autonomy": _json_value(record),
                }
            )
        return record

    def record_external_expert_review(
        self,
        record: ExternalExpertReviewRecord,
        *,
        persist: bool = True,
    ) -> ExternalExpertReviewRecord:
        decision = validate_external_expert_review(record)
        if not decision.accepted:
            raise ValueError(_decision_message(decision))
        self._expert_reviews[record.review_ref] = record
        if persist:
            self._append_event(
                {
                    "schema_version": 1,
                    "event_type": "external_expert_review_recorded",
                    "external_expert_review": _json_value(record),
                }
            )
        return record

    def claim(self, claim_ref: str) -> TrustClaimRecord:
        return self._claims[claim_ref]

    def independence_disclosure(self, disclosure_ref: str) -> FunctionalIndependenceDisclosure:
        return self._independence_disclosures[disclosure_ref]

    def external_expert_review(self, review_ref: str) -> ExternalExpertReviewRecord:
        return self._expert_reviews[review_ref]

    def user_autonomy(self, choice_ref: str) -> UserAutonomyRecord:
        return self._user_autonomy_records[choice_ref]

    def claims(self) -> list[TrustClaimRecord]:
        return list(self._claims.values())

    def independence_disclosures(self) -> list[FunctionalIndependenceDisclosure]:
        return list(self._independence_disclosures.values())

    def external_expert_reviews(self) -> list[ExternalExpertReviewRecord]:
        return list(self._expert_reviews.values())

    def user_autonomy_records(self) -> list[UserAutonomyRecord]:
        return list(self._user_autonomy_records.values())


class PersistentExternalExpertSignatureRegistry:
    """Append-only JSONL store for reviewer identities and verified signatures."""

    def __init__(self, path: str | Path) -> None:
        self._path = Path(path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._identities: dict[str, ExternalReviewerIdentityRecord] = {}
        self._signatures: dict[str, ExternalExpertSignatureRecord] = {}
        self._load_existing()

    @property
    def path(self) -> Path:
        return self._path

    def _load_existing(self) -> None:
        if not self._path.exists():
            return
        with self._path.open("r", encoding="utf-8") as fh:
            for line_no, line in enumerate(fh, start=1):
                if not line.strip():
                    continue
                try:
                    row = json.loads(line)
                    self._apply_row(row, persist=False)
                except Exception as exc:  # noqa: BLE001
                    raise ValueError(f"invalid persisted External Expert Signature row at {self._path}:{line_no}") from exc

    def _append_event(self, row: dict[str, Any]) -> None:
        with self._path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n")
            fh.flush()

    def _apply_row(self, row: dict[str, Any], *, persist: bool) -> Any:
        if row.get("schema_version") != 1:
            raise ValueError("unsupported External Expert Signature schema_version")
        event_type = row.get("event_type")
        if event_type == "external_reviewer_identity_recorded":
            raw = row.get("external_reviewer_identity")
            if not isinstance(raw, dict):
                raise ValueError("External Expert Signature event missing external_reviewer_identity")
            return self.record_identity(external_reviewer_identity_from_dict(raw), persist=persist)
        if event_type == "external_expert_signature_verified":
            raw = row.get("external_expert_signature")
            if not isinstance(raw, dict):
                raise ValueError("External Expert Signature event missing external_expert_signature")
            record = external_expert_signature_from_dict(raw)
            self._signatures[record.verified_signature_ref] = record
            if persist:
                self._append_event(row)
            return record
        raise ValueError(f"unknown External Expert Signature event_type={event_type!r}")

    def record_identity(
        self,
        record: ExternalReviewerIdentityRecord,
        *,
        persist: bool = True,
    ) -> ExternalReviewerIdentityRecord:
        decision = validate_external_reviewer_identity(record)
        if not decision.accepted:
            raise ValueError(_decision_message(decision))
        self._identities[record.identity_ref] = record
        if persist:
            self._append_event(
                {
                    "schema_version": 1,
                    "event_type": "external_reviewer_identity_recorded",
                    "external_reviewer_identity": _json_value(record),
                }
            )
        return record

    def record_signature(
        self,
        *,
        review: ExternalExpertReviewRecord,
        identity_ref: str,
        signature_b64: str,
        attestation_ref: str | None = None,
        verified_signature_ref: str | None = None,
        verified_at: str | None = None,
        persist: bool = True,
    ) -> ExternalExpertSignatureRecord:
        identity = self._identities[str(identity_ref or "")]
        payload = external_expert_review_signature_payload(review)
        payload_hash = "sha16:" + content_hash({"payload": payload.decode("utf-8")})
        record = ExternalExpertSignatureRecord(
            verified_signature_ref=str(verified_signature_ref or f"verified_signature:{content_hash({'review_ref': review.review_ref, 'identity_ref': identity.identity_ref, 'signature_b64': signature_b64})}"),
            attestation_ref=str(attestation_ref or review.signed_attestation_ref or ""),
            review_ref=review.review_ref,
            reviewer_ref=review.reviewer_ref,
            identity_ref=identity.identity_ref,
            public_key_ref=identity.public_key_ref,
            public_key_fingerprint=identity.public_key_fingerprint,
            signed_payload_hash=payload_hash,
            signature_b64=str(signature_b64 or ""),
            verified_at=str(verified_at or "verified_at:local"),
        )
        decision = validate_external_expert_signature(record, review=review, identity=identity)
        if not decision.accepted:
            raise ValueError(_decision_message(decision))
        self._signatures[record.verified_signature_ref] = record
        if persist:
            self._append_event(
                {
                    "schema_version": 1,
                    "event_type": "external_expert_signature_verified",
                    "external_expert_signature": _json_value(record),
                }
            )
        return record

    def identity(self, identity_ref: str) -> ExternalReviewerIdentityRecord:
        return self._identities[identity_ref]

    def signature(self, verified_signature_ref: str) -> ExternalExpertSignatureRecord:
        return self._signatures[verified_signature_ref]

    def identities(self) -> list[ExternalReviewerIdentityRecord]:
        return list(self._identities.values())

    def signatures(self) -> list[ExternalExpertSignatureRecord]:
        return list(self._signatures.values())


class PersistentTrustReleaseCheckRegistry:
    """Append-only JSONL store for release trust check evidence."""

    def __init__(self, path: str | Path) -> None:
        self._path = Path(path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._checks: dict[str, TrustReleaseCheckRecord] = {}
        self._load_existing()

    @property
    def path(self) -> Path:
        return self._path

    def _load_existing(self) -> None:
        if not self._path.exists():
            return
        with self._path.open("r", encoding="utf-8") as fh:
            for line_no, line in enumerate(fh, start=1):
                if not line.strip():
                    continue
                try:
                    row = json.loads(line)
                    self._apply_row(row, persist=False)
                except Exception as exc:  # noqa: BLE001
                    raise ValueError(f"invalid persisted Trust Release Check row at {self._path}:{line_no}") from exc

    def _append_event(self, row: dict[str, Any]) -> None:
        with self._path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n")
            fh.flush()

    def _apply_row(self, row: dict[str, Any], *, persist: bool) -> TrustReleaseCheckRecord:
        if row.get("schema_version") != 1:
            raise ValueError("unsupported Trust Release Check schema_version")
        if row.get("event_type") != "trust_release_check_recorded":
            raise ValueError(f"unknown Trust Release Check event_type={row.get('event_type')!r}")
        raw = row.get("release_check")
        if not isinstance(raw, dict):
            raise ValueError("Trust Release Check event missing release_check")
        record = trust_release_check_record_from_dict(raw)
        return self.record_check(record, persist=persist)

    def record_check(
        self,
        record: TrustReleaseCheckRecord,
        *,
        persist: bool = True,
    ) -> TrustReleaseCheckRecord:
        decision = validate_trust_release_check(record)
        if not decision.accepted:
            raise ValueError(_decision_message(decision))
        self._checks[record.check_ref] = record
        if persist:
            self._append_event(
                {
                    "schema_version": 1,
                    "event_type": "trust_release_check_recorded",
                    "release_check": _json_value(record),
                }
            )
        return record

    def check(self, check_ref: str) -> TrustReleaseCheckRecord:
        return self._checks[check_ref]

    def checks(self) -> list[TrustReleaseCheckRecord]:
        return list(self._checks.values())


class PersistentTrustPressureRunRegistry:
    """Append-only JSONL store for local trust pressure runner records."""

    def __init__(self, path: str | Path) -> None:
        self._path = Path(path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._runs: dict[str, TrustPressureRunRecord] = {}
        self._load_existing()

    @property
    def path(self) -> Path:
        return self._path

    def _load_existing(self) -> None:
        if not self._path.exists():
            return
        with self._path.open("r", encoding="utf-8") as fh:
            for line_no, line in enumerate(fh, start=1):
                if not line.strip():
                    continue
                try:
                    row = json.loads(line)
                    self._apply_row(row, persist=False)
                except Exception as exc:  # noqa: BLE001
                    raise ValueError(f"invalid persisted Trust Pressure Run row at {self._path}:{line_no}") from exc

    def _append_event(self, row: dict[str, Any]) -> None:
        with self._path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n")
            fh.flush()

    def _apply_row(self, row: dict[str, Any], *, persist: bool) -> TrustPressureRunRecord:
        if row.get("schema_version") != 1:
            raise ValueError("unsupported Trust Pressure Run schema_version")
        if row.get("event_type") != "trust_pressure_run_recorded":
            raise ValueError(f"unknown Trust Pressure Run event_type={row.get('event_type')!r}")
        raw = row.get("pressure_run")
        if not isinstance(raw, dict):
            raise ValueError("Trust Pressure Run event missing pressure_run")
        record = trust_pressure_run_record_from_dict(raw)
        return self.record_run(record, persist=persist)

    def record_run(
        self,
        record: TrustPressureRunRecord,
        *,
        persist: bool = True,
    ) -> TrustPressureRunRecord:
        decision = validate_trust_pressure_run(record)
        if not decision.accepted:
            raise ValueError(_decision_message(decision))
        self._runs[record.runner_ref] = record
        if persist:
            self._append_event(
                {
                    "schema_version": 1,
                    "event_type": "trust_pressure_run_recorded",
                    "pressure_run": _json_value(record),
                }
            )
        return record

    def run(self, runner_ref: str) -> TrustPressureRunRecord:
        return self._runs[runner_ref]

    def runs(self) -> list[TrustPressureRunRecord]:
        return list(self._runs.values())


class PersistentTrustReleaseApprovalRegistry:
    """Append-only JSONL store for trust release approval workflow records."""

    def __init__(self, path: str | Path) -> None:
        self._path = Path(path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._approvals: dict[str, TrustReleaseApprovalRecord] = {}
        self._load_existing()

    @property
    def path(self) -> Path:
        return self._path

    def _load_existing(self) -> None:
        if not self._path.exists():
            return
        with self._path.open("r", encoding="utf-8") as fh:
            for line_no, line in enumerate(fh, start=1):
                if not line.strip():
                    continue
                try:
                    row = json.loads(line)
                    self._apply_row(row, persist=False)
                except Exception as exc:  # noqa: BLE001
                    raise ValueError(f"invalid persisted Trust Release Approval row at {self._path}:{line_no}") from exc

    def _append_event(self, row: dict[str, Any]) -> None:
        with self._path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n")
            fh.flush()

    def _apply_row(self, row: dict[str, Any], *, persist: bool) -> TrustReleaseApprovalRecord:
        if row.get("schema_version") != 1:
            raise ValueError("unsupported Trust Release Approval schema_version")
        if row.get("event_type") != "trust_release_approval_recorded":
            raise ValueError(f"unknown Trust Release Approval event_type={row.get('event_type')!r}")
        raw = row.get("release_approval")
        if not isinstance(raw, dict):
            raise ValueError("Trust Release Approval event missing release_approval")
        record = trust_release_approval_record_from_dict(raw)
        return self.record_approval(record, persist=persist)

    def record_approval(
        self,
        record: TrustReleaseApprovalRecord,
        *,
        persist: bool = True,
    ) -> TrustReleaseApprovalRecord:
        decision = validate_trust_release_approval(record)
        if not decision.accepted:
            raise ValueError(_decision_message(decision))
        self._approvals[record.approval_ref] = record
        if persist:
            self._append_event(
                {
                    "schema_version": 1,
                    "event_type": "trust_release_approval_recorded",
                    "release_approval": _json_value(record),
                }
            )
        return record

    def approval(self, approval_ref: str) -> TrustReleaseApprovalRecord:
        return self._approvals[approval_ref]

    def approvals(self) -> list[TrustReleaseApprovalRecord]:
        return list(self._approvals.values())


class PersistentTrustReleaseGateRegistry:
    """Append-only JSONL store for release trust gate evidence."""

    def __init__(self, path: str | Path) -> None:
        self._path = Path(path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._gates: dict[str, TrustReleaseGateRecord] = {}
        self._load_existing()

    @property
    def path(self) -> Path:
        return self._path

    def _load_existing(self) -> None:
        if not self._path.exists():
            return
        with self._path.open("r", encoding="utf-8") as fh:
            for line_no, line in enumerate(fh, start=1):
                if not line.strip():
                    continue
                try:
                    row = json.loads(line)
                    self._apply_row(row, persist=False)
                except Exception as exc:  # noqa: BLE001 - bad trust history must block startup.
                    raise ValueError(f"invalid persisted Trust Release Gate row at {self._path}:{line_no}") from exc

    def _append_event(self, row: dict[str, Any]) -> None:
        with self._path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n")
            fh.flush()

    def _apply_row(self, row: dict[str, Any], *, persist: bool) -> TrustReleaseGateRecord:
        if row.get("schema_version") != 1:
            raise ValueError("unsupported Trust Release Gate schema_version")
        if row.get("event_type") != "trust_release_gate_recorded":
            raise ValueError(f"unknown Trust Release Gate event_type={row.get('event_type')!r}")
        raw = row.get("release_gate")
        if not isinstance(raw, dict):
            raise ValueError("Trust Release Gate event missing release_gate")
        record = trust_release_gate_record_from_dict(raw)
        decision = validate_trust_release_gate(record)
        if not decision.accepted:
            raise ValueError(_decision_message(decision))
        self._gates[record.release_ref] = record
        if persist:
            self._append_event(
                {
                    "schema_version": 1,
                    "event_type": "trust_release_gate_recorded",
                    "release_gate": _json_value(record),
                }
            )
        return record

    def record_gate(self, record: TrustReleaseGateRecord) -> TrustReleaseGateRecord:
        return self._apply_row(
            {
                "schema_version": 1,
                "event_type": "trust_release_gate_recorded",
                "release_gate": _json_value(record),
            },
            persist=True,
        )

    def gate(self, release_ref: str) -> TrustReleaseGateRecord:
        return self._gates[release_ref]

    def gates(self) -> list[TrustReleaseGateRecord]:
        return list(self._gates.values())


__all__ = [
    "ExternalExpertSignatureRecord",
    "ExternalExpertReviewRecord",
    "ExternalReviewerIdentityRecord",
    "FunctionalIndependenceDisclosure",
    "PersistentExternalExpertSignatureRegistry",
    "PersistentTrustDisclosureRegistry",
    "PersistentTrustPressureRunRegistry",
    "PersistentTrustReleaseApprovalRegistry",
    "PersistentTrustReleaseCheckRegistry",
    "PersistentTrustReleaseGateRegistry",
    "TrustClaimLabel",
    "TrustClaimRecord",
    "TrustLayerDecision",
    "TrustLayerViolation",
    "TrustPressureRunRecord",
    "TrustReleaseApprovalRecord",
    "TrustReleaseCheckRecord",
    "TrustReleaseGateRecord",
    "UserAutonomyRecord",
    "build_section13_trust_record",
    "external_expert_review_signature_payload",
    "external_expert_review_from_dict",
    "external_expert_signature_from_dict",
    "external_reviewer_identity_from_dict",
    "functional_independence_disclosure_from_dict",
    "record_external_expert_review",
    "record_trust_pressure_run",
    "record_trust_release_approval",
    "record_trust_release_check",
    "record_trust_release_check_suite",
    "trust_pressure_run_record_from_dict",
    "trust_claim_record_from_dict",
    "trust_release_approval_record_from_dict",
    "trust_release_check_record_from_dict",
    "trust_release_gate_record_from_dict",
    "user_autonomy_record_from_dict",
    "validate_external_expert_review",
    "validate_external_expert_signature",
    "validate_external_reviewer_identity",
    "validate_functional_independence",
    "validate_trust_claim",
    "validate_trust_layer",
    "validate_trust_pressure_run",
    "validate_trust_release_approval",
    "validate_trust_release_check",
    "validate_trust_release_gate",
    "validate_user_autonomy",
]
