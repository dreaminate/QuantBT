"""GOAL §13 trust-layer contracts."""

from __future__ import annotations

import base64
import json
import os
import re
import threading
from dataclasses import asdict, dataclass, is_dataclass
from enum import Enum
from pathlib import Path
from typing import Any

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from ..lineage.ids import content_hash
from ..cross_process_lock import acquire_exclusive_fd


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


def _req_str(data: dict[str, Any], key: str, default: str = "") -> str:
    # Trust deserializer scalar-ref hygiene (同 §17 _rdp_str·放权-calibrated 不假绿灯):
    # the old `str(data.get(key) or default)` str-coerced a dict/list into a fabricated
    # non-empty ref (e.g. str({...})="{'x': 1}") that then passed the downstream _present
    # non-empty check — whitewashing honesty/independence gates. Absent → default; a real
    # string passes; a mapping/list/number is rejected (ValueError → HTTP 422 at the
    # endpoint's except (ValueError, TypeError)). This is reject-non-str hygiene only — it
    # does NOT force the ref to resolve to a real registered record (that stays the user's).
    value = data.get(key)
    if value is None:
        return default
    if not isinstance(value, str):
        raise ValueError(
            f"trust field {key!r} must be a string, not {type(value).__name__} "
            "(a mapping/list would fabricate a non-empty ref)"
        )
    return value or default


def _opt_str(data: dict[str, Any], key: str) -> str | None:
    # Optional Trust scalar ref: absent stays None (the "not supplied" sentinel the
    # validators distinguish); a real string passes; a mapping/list/number is rejected.
    value = data.get(key)
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError(
            f"trust field {key!r} must be a string, not {type(value).__name__} "
            "(a mapping/list would fabricate a non-empty ref)"
        )
    return value


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


def _stable_owner_user_id(value: Any) -> str:
    owner = str(value or "").strip()
    if not owner:
        raise ValueError("owner_user_id is required")
    return owner


def _owner_record_key(owner_user_id: Any, record_ref: Any) -> tuple[str, str]:
    owner = _stable_owner_user_id(owner_user_id)
    ref = str(record_ref or "").strip()
    if not ref:
        raise ValueError("owner-enveloped trust record ref is required")
    return owner, ref


def _append_owner_enveloped_event(
    path: Path,
    lock_path: Path,
    row: dict[str, Any],
    *,
    record_field: str,
    ref_field: str,
) -> bool:
    """Append one schema-v2 event with cross-process retry/collision safety."""

    if row.get("schema_version") != 2:
        raise ValueError("owner-enveloped trust event requires schema_version=2")
    owner = _stable_owner_user_id(row.get("owner_user_id"))
    raw = row.get(record_field)
    if not isinstance(raw, dict):
        raise ValueError(f"owner-enveloped trust event missing {record_field}")
    record_ref = str(raw.get(ref_field) or "").strip()
    if not record_ref:
        raise ValueError(f"owner-enveloped trust event missing {ref_field}")
    encoded = json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    lock_fd = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o600)
    held = None
    try:
        held = acquire_exclusive_fd(lock_fd, timeout_seconds=10.0)
        if path.exists():
            with path.open("r", encoding="utf-8") as fh:
                for line_no, line in enumerate(fh, start=1):
                    if not line.strip():
                        continue
                    try:
                        existing = json.loads(line)
                    except Exception as exc:  # noqa: BLE001
                        raise ValueError(f"invalid persisted trust row at {path}:{line_no}") from exc
                    existing_raw = existing.get(record_field)
                    if (
                        existing.get("event_type") == row.get("event_type")
                        and existing.get("owner_user_id") == owner
                        and isinstance(existing_raw, dict)
                        and str(existing_raw.get(ref_field) or "").strip() == record_ref
                    ):
                        existing_encoded = json.dumps(
                            existing,
                            ensure_ascii=False,
                            sort_keys=True,
                            separators=(",", ":"),
                        )
                        if existing_encoded == encoded:
                            return False
                        raise ValueError(
                            f"owner-enveloped trust record collision owner={owner!r} ref={record_ref!r}"
                        )
        with path.open("a", encoding="utf-8") as fh:
            fh.write(encoded + "\n")
            fh.flush()
            os.fsync(fh.fileno())
        return True
    finally:
        if held is not None:
            held.release()
        os.close(lock_fd)


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
    if expert_review.artifact_ref != str(artifact_ref or ""):
        raise ValueError("trust_release_approval_expert_review_artifact_mismatch")

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
        claim_ref=_req_str(data, "claim_ref"),
        claim_label=_req_str(data, "claim_label"),
        evidence_refs=_tuple(data.get("evidence_refs")),
        weakness_refs=_tuple(data.get("weakness_refs")),
        weakness_visible_by_default=_bool_value(data.get("weakness_visible_by_default"), default=True),
        cold_start_n=int(cold_start_n) if cold_start_n not in (None, "") else None,
        pressure_context=_req_str(data, "pressure_context"),
        user_waiver_ref=_opt_str(data, "user_waiver_ref"),
        waiver_weakness_visible_by_default=_bool_value(
            data.get("waiver_weakness_visible_by_default"),
            default=True,
        ),
    )


def functional_independence_disclosure_from_dict(
    data: dict[str, Any],
) -> FunctionalIndependenceDisclosure:
    return FunctionalIndependenceDisclosure(
        disclosure_ref=_req_str(data, "disclosure_ref"),
        mode=_req_str(data, "mode"),
        claims_organizational_independence=_bool_value(data.get("claims_organizational_independence")),
        isolated_validation_ref=_opt_str(data, "isolated_validation_ref"),
        immutable_evidence_ref=_opt_str(data, "immutable_evidence_ref"),
        second_confirmation_ref=_opt_str(data, "second_confirmation_ref"),
        alternate_model_verification_ref=_opt_str(data, "alternate_model_verification_ref"),
        organization_process_ref=_opt_str(data, "organization_process_ref"),
    )


def external_expert_review_from_dict(data: dict[str, Any]) -> ExternalExpertReviewRecord:
    return ExternalExpertReviewRecord(
        review_ref=_req_str(data, "review_ref"),
        release_ref=_req_str(data, "release_ref"),
        reviewer_ref=_req_str(data, "reviewer_ref"),
        reviewer_independence_ref=_req_str(data, "reviewer_independence_ref"),
        artifact_ref=_req_str(data, "artifact_ref"),
        review_protocol_ref=_req_str(data, "review_protocol_ref"),
        verdict=_req_str(data, "verdict"),
        source_hash=_req_str(data, "source_hash"),
        evidence_refs=_tuple(data.get("evidence_refs")),
        veto_reason_refs=_tuple(data.get("veto_reason_refs")),
        signed_attestation_ref=_opt_str(data, "signed_attestation_ref"),
        silent_mock_fallback_used=_bool_value(data.get("silent_mock_fallback_used")),
    )


def external_reviewer_identity_from_dict(data: dict[str, Any]) -> ExternalReviewerIdentityRecord:
    return ExternalReviewerIdentityRecord(
        identity_ref=_req_str(data, "identity_ref"),
        reviewer_ref=_req_str(data, "reviewer_ref"),
        identity_provider_ref=_req_str(data, "identity_provider_ref"),
        public_key_ref=_req_str(data, "public_key_ref"),
        public_key_pem=_req_str(data, "public_key_pem"),
        reviewer_independence_ref=_req_str(data, "reviewer_independence_ref"),
        evidence_refs=_tuple(data.get("evidence_refs")),
        public_key_fingerprint=_req_str(data, "public_key_fingerprint"),
        status=_req_str(data, "status", "active"),
        identity_hash=_req_str(data, "identity_hash"),
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
        choice_ref=_req_str(data, "choice_ref"),
        agent_recommendation_ref=_opt_str(data, "agent_recommendation_ref"),
        tradeoff_refs=_tuple(data.get("tradeoff_refs")),
        alternative_path_refs=_tuple(data.get("alternative_path_refs")),
        responsibility_boundary_ref=_opt_str(data, "responsibility_boundary_ref"),
        user_final_choice_ref=_opt_str(data, "user_final_choice_ref"),
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


class PersistentTrustDisclosureRegistry:
    """Owner-enveloped append-only store for trust disclosures and reviews."""

    def __init__(self, path: str | Path) -> None:
        self._path = Path(path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._lock_path = self._path.with_suffix(self._path.suffix + ".lock")
        self._lock = threading.RLock()
        self._claims: dict[tuple[str, str], TrustClaimRecord] = {}
        self._independence_disclosures: dict[tuple[str, str], FunctionalIndependenceDisclosure] = {}
        self._expert_reviews: dict[tuple[str, str], ExternalExpertReviewRecord] = {}
        self._user_autonomy_records: dict[tuple[str, str], UserAutonomyRecord] = {}
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

    def _apply_row(self, row: dict[str, Any], *, persist: bool) -> Any:
        if row.get("schema_version") != 2:
            raise ValueError("unsupported or ownerless Trust Disclosure schema_version")
        owner = _stable_owner_user_id(row.get("owner_user_id"))
        event_type = row.get("event_type")
        if event_type == "trust_claim_recorded":
            raw = row.get("trust_claim")
            if not isinstance(raw, dict):
                raise ValueError("Trust Disclosure event missing trust_claim")
            return self.record_claim(trust_claim_record_from_dict(raw), owner_user_id=owner, persist=persist)
        if event_type == "functional_independence_disclosure_recorded":
            raw = row.get("independence_disclosure")
            if not isinstance(raw, dict):
                raise ValueError("Trust Disclosure event missing independence_disclosure")
            return self.record_independence_disclosure(
                functional_independence_disclosure_from_dict(raw),
                owner_user_id=owner,
                persist=persist,
            )
        if event_type == "external_expert_review_recorded":
            raw = row.get("external_expert_review")
            if not isinstance(raw, dict):
                raise ValueError("Trust Disclosure event missing external_expert_review")
            return self.record_external_expert_review(
                external_expert_review_from_dict(raw),
                owner_user_id=owner,
                persist=persist,
            )
        if event_type == "user_autonomy_recorded":
            raw = row.get("user_autonomy")
            if not isinstance(raw, dict):
                raise ValueError("Trust Disclosure event missing user_autonomy")
            return self.record_user_autonomy(
                user_autonomy_record_from_dict(raw),
                owner_user_id=owner,
                persist=persist,
            )
        raise ValueError(f"unknown Trust Disclosure event_type={event_type!r}")

    def record_claim(
        self,
        record: TrustClaimRecord,
        *,
        owner_user_id: str,
        persist: bool = True,
    ) -> TrustClaimRecord:
        decision = validate_trust_claim(record)
        if not decision.accepted:
            raise ValueError(_decision_message(decision))
        key = _owner_record_key(owner_user_id, record.claim_ref)
        row = {
            "schema_version": 2,
            "owner_user_id": key[0],
            "event_type": "trust_claim_recorded",
            "trust_claim": _json_value(record),
        }
        with self._lock:
            existing = self._claims.get(key)
            if existing is not None and existing != record:
                raise ValueError(f"owner-enveloped trust record collision owner={key[0]!r} ref={key[1]!r}")
            if persist:
                _append_owner_enveloped_event(
                    self._path, self._lock_path, row, record_field="trust_claim", ref_field="claim_ref"
                )
            self._claims[key] = record
            return record

    def record_independence_disclosure(
        self,
        record: FunctionalIndependenceDisclosure,
        *,
        owner_user_id: str,
        persist: bool = True,
    ) -> FunctionalIndependenceDisclosure:
        decision = validate_functional_independence(record)
        if not decision.accepted:
            raise ValueError(_decision_message(decision))
        key = _owner_record_key(owner_user_id, record.disclosure_ref)
        row = {
            "schema_version": 2,
            "owner_user_id": key[0],
            "event_type": "functional_independence_disclosure_recorded",
            "independence_disclosure": _json_value(record),
        }
        with self._lock:
            existing = self._independence_disclosures.get(key)
            if existing is not None and existing != record:
                raise ValueError(f"owner-enveloped trust record collision owner={key[0]!r} ref={key[1]!r}")
            if persist:
                _append_owner_enveloped_event(
                    self._path,
                    self._lock_path,
                    row,
                    record_field="independence_disclosure",
                    ref_field="disclosure_ref",
                )
            self._independence_disclosures[key] = record
            return record

    def record_user_autonomy(
        self,
        record: UserAutonomyRecord,
        *,
        owner_user_id: str,
        persist: bool = True,
    ) -> UserAutonomyRecord:
        decision = validate_user_autonomy(record)
        if not decision.accepted:
            raise ValueError(_decision_message(decision))
        key = _owner_record_key(owner_user_id, record.choice_ref)
        row = {
            "schema_version": 2,
            "owner_user_id": key[0],
            "event_type": "user_autonomy_recorded",
            "user_autonomy": _json_value(record),
        }
        with self._lock:
            existing = self._user_autonomy_records.get(key)
            if existing is not None and existing != record:
                raise ValueError(f"owner-enveloped trust record collision owner={key[0]!r} ref={key[1]!r}")
            if persist:
                _append_owner_enveloped_event(
                    self._path, self._lock_path, row, record_field="user_autonomy", ref_field="choice_ref"
                )
            self._user_autonomy_records[key] = record
            return record

    def record_external_expert_review(
        self,
        record: ExternalExpertReviewRecord,
        *,
        owner_user_id: str,
        persist: bool = True,
    ) -> ExternalExpertReviewRecord:
        decision = validate_external_expert_review(record)
        if not decision.accepted:
            raise ValueError(_decision_message(decision))
        key = _owner_record_key(owner_user_id, record.review_ref)
        row = {
            "schema_version": 2,
            "owner_user_id": key[0],
            "event_type": "external_expert_review_recorded",
            "external_expert_review": _json_value(record),
        }
        with self._lock:
            existing = self._expert_reviews.get(key)
            if existing is not None and existing != record:
                raise ValueError(f"owner-enveloped trust record collision owner={key[0]!r} ref={key[1]!r}")
            if persist:
                _append_owner_enveloped_event(
                    self._path,
                    self._lock_path,
                    row,
                    record_field="external_expert_review",
                    ref_field="review_ref",
                )
            self._expert_reviews[key] = record
            return record

    def claim(self, claim_ref: str, *, owner_user_id: str) -> TrustClaimRecord:
        return self._claims[_owner_record_key(owner_user_id, claim_ref)]

    def independence_disclosure(
        self, disclosure_ref: str, *, owner_user_id: str
    ) -> FunctionalIndependenceDisclosure:
        return self._independence_disclosures[_owner_record_key(owner_user_id, disclosure_ref)]

    def external_expert_review(
        self, review_ref: str, *, owner_user_id: str
    ) -> ExternalExpertReviewRecord:
        return self._expert_reviews[_owner_record_key(owner_user_id, review_ref)]

    def user_autonomy(self, choice_ref: str, *, owner_user_id: str) -> UserAutonomyRecord:
        return self._user_autonomy_records[_owner_record_key(owner_user_id, choice_ref)]

    def claims(self, *, owner_user_id: str) -> list[TrustClaimRecord]:
        owner = _stable_owner_user_id(owner_user_id)
        return [record for (record_owner, _), record in self._claims.items() if record_owner == owner]

    def independence_disclosures(
        self, *, owner_user_id: str
    ) -> list[FunctionalIndependenceDisclosure]:
        owner = _stable_owner_user_id(owner_user_id)
        return [record for (record_owner, _), record in self._independence_disclosures.items() if record_owner == owner]

    def external_expert_reviews(self, *, owner_user_id: str) -> list[ExternalExpertReviewRecord]:
        owner = _stable_owner_user_id(owner_user_id)
        return [record for (record_owner, _), record in self._expert_reviews.items() if record_owner == owner]

    def user_autonomy_records(self, *, owner_user_id: str) -> list[UserAutonomyRecord]:
        owner = _stable_owner_user_id(owner_user_id)
        return [record for (record_owner, _), record in self._user_autonomy_records.items() if record_owner == owner]


class PersistentExternalExpertSignatureRegistry:
    """Owner-enveloped store for reviewer identities and verified signatures."""

    def __init__(self, path: str | Path) -> None:
        self._path = Path(path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._lock_path = self._path.with_suffix(self._path.suffix + ".lock")
        self._lock = threading.RLock()
        self._identities: dict[tuple[str, str], ExternalReviewerIdentityRecord] = {}
        self._signatures: dict[tuple[str, str], ExternalExpertSignatureRecord] = {}
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

    def _apply_row(self, row: dict[str, Any], *, persist: bool) -> Any:
        if row.get("schema_version") != 2:
            raise ValueError("unsupported or ownerless External Expert Signature schema_version")
        owner = _stable_owner_user_id(row.get("owner_user_id"))
        event_type = row.get("event_type")
        if event_type == "external_reviewer_identity_recorded":
            raw = row.get("external_reviewer_identity")
            if not isinstance(raw, dict):
                raise ValueError("External Expert Signature event missing external_reviewer_identity")
            return self.record_identity(
                external_reviewer_identity_from_dict(raw),
                owner_user_id=owner,
                persist=persist,
            )
        if event_type == "external_expert_signature_verified":
            raw = row.get("external_expert_signature")
            if not isinstance(raw, dict):
                raise ValueError("External Expert Signature event missing external_expert_signature")
            record = external_expert_signature_from_dict(raw)
            key = _owner_record_key(owner, record.verified_signature_ref)
            with self._lock:
                existing = self._signatures.get(key)
                if existing is not None and existing != record:
                    raise ValueError(
                        f"owner-enveloped trust record collision owner={key[0]!r} ref={key[1]!r}"
                    )
                if persist:
                    _append_owner_enveloped_event(
                        self._path,
                        self._lock_path,
                        row,
                        record_field="external_expert_signature",
                        ref_field="verified_signature_ref",
                    )
                self._signatures[key] = record
                return record
        raise ValueError(f"unknown External Expert Signature event_type={event_type!r}")

    def record_identity(
        self,
        record: ExternalReviewerIdentityRecord,
        *,
        owner_user_id: str,
        persist: bool = True,
    ) -> ExternalReviewerIdentityRecord:
        decision = validate_external_reviewer_identity(record)
        if not decision.accepted:
            raise ValueError(_decision_message(decision))
        key = _owner_record_key(owner_user_id, record.identity_ref)
        row = {
            "schema_version": 2,
            "owner_user_id": key[0],
            "event_type": "external_reviewer_identity_recorded",
            "external_reviewer_identity": _json_value(record),
        }
        with self._lock:
            existing = self._identities.get(key)
            if existing is not None and existing != record:
                raise ValueError(f"owner-enveloped trust record collision owner={key[0]!r} ref={key[1]!r}")
            if persist:
                _append_owner_enveloped_event(
                    self._path,
                    self._lock_path,
                    row,
                    record_field="external_reviewer_identity",
                    ref_field="identity_ref",
                )
            self._identities[key] = record
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
        owner_user_id: str,
        persist: bool = True,
    ) -> ExternalExpertSignatureRecord:
        owner = _stable_owner_user_id(owner_user_id)
        identity = self._identities[_owner_record_key(owner, identity_ref)]
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
        key = _owner_record_key(owner, record.verified_signature_ref)
        row = {
            "schema_version": 2,
            "owner_user_id": owner,
            "event_type": "external_expert_signature_verified",
            "external_expert_signature": _json_value(record),
        }
        with self._lock:
            existing = self._signatures.get(key)
            if existing is not None and existing != record:
                raise ValueError(f"owner-enveloped trust record collision owner={key[0]!r} ref={key[1]!r}")
            if persist:
                _append_owner_enveloped_event(
                    self._path,
                    self._lock_path,
                    row,
                    record_field="external_expert_signature",
                    ref_field="verified_signature_ref",
                )
            self._signatures[key] = record
            return record

    def identity(self, identity_ref: str, *, owner_user_id: str) -> ExternalReviewerIdentityRecord:
        return self._identities[_owner_record_key(owner_user_id, identity_ref)]

    def signature(
        self, verified_signature_ref: str, *, owner_user_id: str
    ) -> ExternalExpertSignatureRecord:
        return self._signatures[_owner_record_key(owner_user_id, verified_signature_ref)]

    def identities(self, *, owner_user_id: str) -> list[ExternalReviewerIdentityRecord]:
        owner = _stable_owner_user_id(owner_user_id)
        return [record for (record_owner, _), record in self._identities.items() if record_owner == owner]

    def signatures(self, *, owner_user_id: str) -> list[ExternalExpertSignatureRecord]:
        owner = _stable_owner_user_id(owner_user_id)
        return [record for (record_owner, _), record in self._signatures.items() if record_owner == owner]


class PersistentTrustReleaseCheckRegistry:
    """Owner-enveloped append-only store for release trust check evidence."""

    def __init__(self, path: str | Path) -> None:
        self._path = Path(path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._lock_path = self._path.with_suffix(self._path.suffix + ".lock")
        self._lock = threading.RLock()
        self._checks: dict[tuple[str, str], TrustReleaseCheckRecord] = {}
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

    def _apply_row(self, row: dict[str, Any], *, persist: bool) -> TrustReleaseCheckRecord:
        if row.get("schema_version") != 2:
            raise ValueError("unsupported or ownerless Trust Release Check schema_version")
        owner = _stable_owner_user_id(row.get("owner_user_id"))
        if row.get("event_type") != "trust_release_check_recorded":
            raise ValueError(f"unknown Trust Release Check event_type={row.get('event_type')!r}")
        raw = row.get("release_check")
        if not isinstance(raw, dict):
            raise ValueError("Trust Release Check event missing release_check")
        record = trust_release_check_record_from_dict(raw)
        return self.record_check(record, owner_user_id=owner, persist=persist)

    def record_check(
        self,
        record: TrustReleaseCheckRecord,
        *,
        owner_user_id: str,
        persist: bool = True,
    ) -> TrustReleaseCheckRecord:
        decision = validate_trust_release_check(record)
        if not decision.accepted:
            raise ValueError(_decision_message(decision))
        key = _owner_record_key(owner_user_id, record.check_ref)
        row = {
            "schema_version": 2,
            "owner_user_id": key[0],
            "event_type": "trust_release_check_recorded",
            "release_check": _json_value(record),
        }
        with self._lock:
            existing = self._checks.get(key)
            if existing is not None and existing != record:
                raise ValueError(f"owner-enveloped trust record collision owner={key[0]!r} ref={key[1]!r}")
            if persist:
                _append_owner_enveloped_event(
                    self._path, self._lock_path, row, record_field="release_check", ref_field="check_ref"
                )
            self._checks[key] = record
            return record

    def check(self, check_ref: str, *, owner_user_id: str) -> TrustReleaseCheckRecord:
        return self._checks[_owner_record_key(owner_user_id, check_ref)]

    def checks(self, *, owner_user_id: str) -> list[TrustReleaseCheckRecord]:
        owner = _stable_owner_user_id(owner_user_id)
        return [record for (record_owner, _), record in self._checks.items() if record_owner == owner]


class PersistentTrustPressureRunRegistry:
    """Owner-enveloped append-only store for local trust pressure runs."""

    def __init__(self, path: str | Path) -> None:
        self._path = Path(path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._lock_path = self._path.with_suffix(self._path.suffix + ".lock")
        self._lock = threading.RLock()
        self._runs: dict[tuple[str, str], TrustPressureRunRecord] = {}
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

    def _apply_row(self, row: dict[str, Any], *, persist: bool) -> TrustPressureRunRecord:
        if row.get("schema_version") != 2:
            raise ValueError("unsupported or ownerless Trust Pressure Run schema_version")
        owner = _stable_owner_user_id(row.get("owner_user_id"))
        if row.get("event_type") != "trust_pressure_run_recorded":
            raise ValueError(f"unknown Trust Pressure Run event_type={row.get('event_type')!r}")
        raw = row.get("pressure_run")
        if not isinstance(raw, dict):
            raise ValueError("Trust Pressure Run event missing pressure_run")
        record = trust_pressure_run_record_from_dict(raw)
        return self.record_run(record, owner_user_id=owner, persist=persist)

    def record_run(
        self,
        record: TrustPressureRunRecord,
        *,
        owner_user_id: str,
        persist: bool = True,
    ) -> TrustPressureRunRecord:
        decision = validate_trust_pressure_run(record)
        if not decision.accepted:
            raise ValueError(_decision_message(decision))
        key = _owner_record_key(owner_user_id, record.runner_ref)
        row = {
            "schema_version": 2,
            "owner_user_id": key[0],
            "event_type": "trust_pressure_run_recorded",
            "pressure_run": _json_value(record),
        }
        with self._lock:
            existing = self._runs.get(key)
            if existing is not None and existing != record:
                raise ValueError(f"owner-enveloped trust record collision owner={key[0]!r} ref={key[1]!r}")
            if persist:
                _append_owner_enveloped_event(
                    self._path, self._lock_path, row, record_field="pressure_run", ref_field="runner_ref"
                )
            self._runs[key] = record
            return record

    def run(self, runner_ref: str, *, owner_user_id: str) -> TrustPressureRunRecord:
        return self._runs[_owner_record_key(owner_user_id, runner_ref)]

    def runs(self, *, owner_user_id: str) -> list[TrustPressureRunRecord]:
        owner = _stable_owner_user_id(owner_user_id)
        return [record for (record_owner, _), record in self._runs.items() if record_owner == owner]


class PersistentTrustReleaseApprovalRegistry:
    """Owner-enveloped append-only store for trust release approvals."""

    def __init__(self, path: str | Path) -> None:
        self._path = Path(path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._lock_path = self._path.with_suffix(self._path.suffix + ".lock")
        self._lock = threading.RLock()
        self._approvals: dict[tuple[str, str], TrustReleaseApprovalRecord] = {}
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

    def _apply_row(self, row: dict[str, Any], *, persist: bool) -> TrustReleaseApprovalRecord:
        if row.get("schema_version") != 2:
            raise ValueError("unsupported or ownerless Trust Release Approval schema_version")
        owner = _stable_owner_user_id(row.get("owner_user_id"))
        if row.get("event_type") != "trust_release_approval_recorded":
            raise ValueError(f"unknown Trust Release Approval event_type={row.get('event_type')!r}")
        raw = row.get("release_approval")
        if not isinstance(raw, dict):
            raise ValueError("Trust Release Approval event missing release_approval")
        record = trust_release_approval_record_from_dict(raw)
        return self.record_approval(record, owner_user_id=owner, persist=persist)

    def record_approval(
        self,
        record: TrustReleaseApprovalRecord,
        *,
        owner_user_id: str,
        persist: bool = True,
    ) -> TrustReleaseApprovalRecord:
        decision = validate_trust_release_approval(record)
        if not decision.accepted:
            raise ValueError(_decision_message(decision))
        key = _owner_record_key(owner_user_id, record.approval_ref)
        row = {
            "schema_version": 2,
            "owner_user_id": key[0],
            "event_type": "trust_release_approval_recorded",
            "release_approval": _json_value(record),
        }
        with self._lock:
            existing = self._approvals.get(key)
            if existing is not None and existing != record:
                raise ValueError(f"owner-enveloped trust record collision owner={key[0]!r} ref={key[1]!r}")
            if persist:
                _append_owner_enveloped_event(
                    self._path,
                    self._lock_path,
                    row,
                    record_field="release_approval",
                    ref_field="approval_ref",
                )
            self._approvals[key] = record
            return record

    def approval(self, approval_ref: str, *, owner_user_id: str) -> TrustReleaseApprovalRecord:
        return self._approvals[_owner_record_key(owner_user_id, approval_ref)]

    def approvals(self, *, owner_user_id: str) -> list[TrustReleaseApprovalRecord]:
        owner = _stable_owner_user_id(owner_user_id)
        return [record for (record_owner, _), record in self._approvals.items() if record_owner == owner]


class PersistentTrustReleaseGateRegistry:
    """Owner-enveloped append-only store for release trust gate evidence."""

    def __init__(self, path: str | Path) -> None:
        self._path = Path(path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._lock_path = self._path.with_suffix(self._path.suffix + ".lock")
        self._lock = threading.RLock()
        self._gates: dict[tuple[str, str], TrustReleaseGateRecord] = {}
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

    def _apply_row(self, row: dict[str, Any], *, persist: bool) -> TrustReleaseGateRecord:
        if row.get("schema_version") != 2:
            raise ValueError("unsupported or ownerless Trust Release Gate schema_version")
        owner = _stable_owner_user_id(row.get("owner_user_id"))
        if row.get("event_type") != "trust_release_gate_recorded":
            raise ValueError(f"unknown Trust Release Gate event_type={row.get('event_type')!r}")
        raw = row.get("release_gate")
        if not isinstance(raw, dict):
            raise ValueError("Trust Release Gate event missing release_gate")
        record = trust_release_gate_record_from_dict(raw)
        decision = validate_trust_release_gate(record)
        if not decision.accepted:
            raise ValueError(_decision_message(decision))
        key = _owner_record_key(owner, record.release_ref)
        with self._lock:
            existing = self._gates.get(key)
            if existing is not None and existing != record:
                raise ValueError(f"owner-enveloped trust record collision owner={key[0]!r} ref={key[1]!r}")
            if persist:
                _append_owner_enveloped_event(
                    self._path,
                    self._lock_path,
                    row,
                    record_field="release_gate",
                    ref_field="release_ref",
                )
            self._gates[key] = record
            return record

    def record_gate(
        self, record: TrustReleaseGateRecord, *, owner_user_id: str
    ) -> TrustReleaseGateRecord:
        owner = _stable_owner_user_id(owner_user_id)
        return self._apply_row(
            {
                "schema_version": 2,
                "owner_user_id": owner,
                "event_type": "trust_release_gate_recorded",
                "release_gate": _json_value(record),
            },
            persist=True,
        )

    def gate(self, release_ref: str, *, owner_user_id: str) -> TrustReleaseGateRecord:
        return self._gates[_owner_record_key(owner_user_id, release_ref)]

    def gates(self, *, owner_user_id: str) -> list[TrustReleaseGateRecord]:
        owner = _stable_owner_user_id(owner_user_id)
        return [record for (record_owner, _), record in self._gates.items() if record_owner == owner]


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
