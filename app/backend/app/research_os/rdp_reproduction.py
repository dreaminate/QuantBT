"""Trusted, content-bound reproduction receipts for formal RDP promotion.

The free-form ``RDPManifest.reproducibility_command`` is documentation only and
is never executed.  A receipt can be minted only from a trusted source resolver
and an injected backend verification loader whose runner identity is explicitly
allowlisted by the composition root.  The repository loader uses only the fixed
argv replay module and preserves its non-hardened-sandbox residual.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import re
import threading
from collections.abc import Callable, Mapping
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path
from typing import Any, Iterator, TypeAlias

from ..cross_process_lock import acquire_exclusive_fd
from ..lineage.ids import canonical_json, content_hash
from .rdp import RDPManifest, validate_rdp_manifest


REPRODUCTION_SPEC_VERSION = "rdp.reproduction_spec.v2"
REPRODUCTION_RECEIPT_VERSION = "rdp.reproduction_receipt.v2"
REPRODUCTION_RECEIPT_PREFIX = "rdp_reproduction_receipt:"
MAX_REPRODUCTION_RECEIPT_VALIDITY_SECONDS = 900

_SHA16 = re.compile(r"(?:sha16:)?[0-9a-f]{16}\Z")
_SHA256 = re.compile(r"sha256:[0-9a-f]{64}\Z")


def _text(value: Any) -> str:
    return str(value or "").strip()


def _strings(value: Any) -> tuple[str, ...]:
    if value is None:
        return ()
    values = value if isinstance(value, (tuple, list)) else (value,)
    return tuple(text for item in values if (text := _text(item)))


def _aware_utc(value: str, field_name: str) -> dt.datetime:
    token = _text(value)
    if not token:
        raise ValueError(f"{field_name} is required")
    try:
        parsed = dt.datetime.fromisoformat(token.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"{field_name} must be an ISO-8601 timestamp") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{field_name} must include a timezone")
    return parsed.astimezone(dt.UTC)


def rdp_manifest_hash(manifest: RDPManifest) -> str:
    """Return the canonical manifest digest used by RDP package records."""

    return "sha16:" + content_hash(manifest.to_open_dict())


def _sha256_bytes(payload: bytes) -> str:
    return "sha256:" + hashlib.sha256(payload).hexdigest()


@dataclass(frozen=True)
class RDPReproductionSourceEvidence:
    """Current immutable source-package evidence resolved by trusted server code."""

    package_id: str
    source_run_ref: str
    source_run_id: str
    source_file_ref: str
    manifest_hash: str
    source_artifact_hash: str
    source_integrity_hash: str
    source_bundle_index_sha256: str
    source_run_manifest_sha256: str
    source_strategy_sha256: str
    source_result_sha256: str
    expected_replay_result_sha256: str
    source_portfolio_sha256: str
    source_result_content_hash: str
    expected_replay_artifact_hash: str
    source_evidence_hash: str = ""

    def __post_init__(self) -> None:
        for field_name in self.__dataclass_fields__:
            object.__setattr__(self, field_name, _text(getattr(self, field_name)))
        for field_name in (
            "package_id",
            "source_run_ref",
            "source_run_id",
            "source_file_ref",
            "source_artifact_hash",
        ):
            if not getattr(self, field_name):
                raise ValueError(f"{field_name} is required")
        for field_name in ("manifest_hash", "source_integrity_hash"):
            if not _SHA16.fullmatch(getattr(self, field_name)):
                raise ValueError(f"{field_name} must be a sha16 digest")
        for field_name in (
            "source_bundle_index_sha256",
            "source_run_manifest_sha256",
            "source_strategy_sha256",
            "source_result_sha256",
            "expected_replay_result_sha256",
            "source_portfolio_sha256",
            "expected_replay_artifact_hash",
        ):
            if not _SHA256.fullmatch(getattr(self, field_name)):
                raise ValueError(f"{field_name} must be a full SHA-256 digest")
        if not re.fullmatch(r"[0-9a-f]{16}", self.source_result_content_hash):
            raise ValueError(
                "source_result_content_hash must be a canonical 16-hex content hash"
            )
        supplied = self.source_evidence_hash
        expected = "sha16:" + content_hash(self._identity_payload())
        if supplied and supplied != expected:
            raise ValueError("RDP reproduction source_evidence_hash mismatch")
        object.__setattr__(self, "source_evidence_hash", expected)

    def _identity_payload(self) -> dict[str, Any]:
        payload = asdict(self)
        payload.pop("source_evidence_hash", None)
        return payload

    def to_open_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ResolvedRDPReproductionSource:
    """Source evidence plus private strategy text for an injected verifier."""

    evidence: RDPReproductionSourceEvidence
    strategy_code: str = field(repr=False)

    def __post_init__(self) -> None:
        if not isinstance(self.evidence, RDPReproductionSourceEvidence):
            raise TypeError("resolved reproduction source evidence is required")
        if not isinstance(self.strategy_code, str) or not self.strategy_code:
            raise ValueError("resolved reproduction strategy_code is required")
        if _sha256_bytes(self.strategy_code.encode("utf-8")) != self.evidence.source_strategy_sha256:
            raise ValueError("resolved reproduction strategy does not match source evidence")


@dataclass(frozen=True)
class RDPReproductionSpec:
    """Structured inputs and expected outputs; contains no executable command."""

    package_id: str
    manifest_hash: str
    artifact_hash: str
    source_result_content_hash: str
    environment_lock_ref: str
    dataset_version_refs: tuple[str, ...]
    code_refs: tuple[str, ...]
    run_refs: tuple[str, ...]
    source_file_refs: tuple[str, ...]
    seed: int | None
    documentation_command_digest: str
    source_run_ref: str
    source_run_id: str
    source_file_ref: str
    source_integrity_hash: str
    source_evidence_hash: str
    source_bundle_index_sha256: str
    source_run_manifest_sha256: str
    source_strategy_sha256: str
    source_result_sha256: str
    expected_replay_result_sha256: str
    source_portfolio_sha256: str
    expected_replay_artifact_hash: str
    spec_hash: str = ""
    spec_version: str = REPRODUCTION_SPEC_VERSION

    def __post_init__(self) -> None:
        for field_name in (
            "package_id",
            "manifest_hash",
            "artifact_hash",
            "source_result_content_hash",
            "environment_lock_ref",
            "documentation_command_digest",
            "source_run_ref",
            "source_run_id",
            "source_file_ref",
            "source_integrity_hash",
            "source_evidence_hash",
            "source_bundle_index_sha256",
            "source_run_manifest_sha256",
            "source_strategy_sha256",
            "source_result_sha256",
            "expected_replay_result_sha256",
            "source_portfolio_sha256",
            "expected_replay_artifact_hash",
            "spec_hash",
            "spec_version",
        ):
            object.__setattr__(self, field_name, _text(getattr(self, field_name)))
        for field_name in (
            "dataset_version_refs",
            "code_refs",
            "run_refs",
            "source_file_refs",
        ):
            object.__setattr__(self, field_name, _strings(getattr(self, field_name)))
        supplied = self.spec_hash
        expected = "sha16:" + content_hash(self._identity_payload())
        if supplied and supplied != expected:
            raise ValueError("RDP reproduction spec_hash mismatch")
        object.__setattr__(self, "spec_hash", expected)

    def _identity_payload(self) -> dict[str, Any]:
        payload = asdict(self)
        payload.pop("spec_hash", None)
        return payload

    def to_open_dict(self) -> dict[str, Any]:
        return asdict(self)


def reproduction_spec(
    manifest: RDPManifest,
    *,
    source_result_content_hash: str,
    source_evidence: RDPReproductionSourceEvidence,
) -> RDPReproductionSpec:
    """Derive the only promotable structured reproduction specification."""

    violations = validate_rdp_manifest(manifest)
    if violations:
        raise ValueError(
            "RDP manifest is not eligible for reproduction verification: "
            + "; ".join(item.code for item in violations)
        )
    source_hash = _text(source_result_content_hash)
    if not _SHA16.fullmatch(source_hash) or source_hash.startswith("sha16:"):
        raise ValueError("source_result_content_hash must be a canonical 16-hex content hash")
    if not isinstance(source_evidence, RDPReproductionSourceEvidence):
        raise ValueError("trusted RDP reproduction source evidence is required")
    expected_manifest_hash = rdp_manifest_hash(manifest)
    evidence_expected = {
        "package_id": manifest.package_id,
        "manifest_hash": expected_manifest_hash,
        "source_artifact_hash": manifest.artifact_hash,
        "source_result_content_hash": source_hash,
    }
    for field_name, expected_value in evidence_expected.items():
        if getattr(source_evidence, field_name) != expected_value:
            raise ValueError(f"RDP reproduction source evidence {field_name} mismatch")
    if source_evidence.source_run_ref not in manifest.run_refs:
        raise ValueError("RDP reproduction source run_ref is not declared")
    if source_evidence.source_file_ref not in manifest.source_file_refs:
        raise ValueError("RDP reproduction source file_ref is not declared")
    return RDPReproductionSpec(
        package_id=manifest.package_id,
        manifest_hash=rdp_manifest_hash(manifest),
        artifact_hash=manifest.artifact_hash,
        source_result_content_hash=source_hash,
        environment_lock_ref=manifest.environment_lock_ref,
        dataset_version_refs=manifest.dataset_version_refs,
        code_refs=manifest.code_refs,
        run_refs=manifest.run_refs,
        source_file_refs=manifest.source_file_refs,
        seed=manifest.seed,
        documentation_command_digest="sha16:"
        + content_hash(
            {
                "documentation_only": manifest.reproducibility_command,
            }
        ),
        source_run_ref=source_evidence.source_run_ref,
        source_run_id=source_evidence.source_run_id,
        source_file_ref=source_evidence.source_file_ref,
        source_integrity_hash=source_evidence.source_integrity_hash,
        source_evidence_hash=source_evidence.source_evidence_hash,
        source_bundle_index_sha256=source_evidence.source_bundle_index_sha256,
        source_run_manifest_sha256=source_evidence.source_run_manifest_sha256,
        source_strategy_sha256=source_evidence.source_strategy_sha256,
        source_result_sha256=source_evidence.source_result_sha256,
        expected_replay_result_sha256=source_evidence.expected_replay_result_sha256,
        source_portfolio_sha256=source_evidence.source_portfolio_sha256,
        expected_replay_artifact_hash=source_evidence.expected_replay_artifact_hash,
    )


@dataclass(frozen=True)
class RDPReproductionVerificationSnapshot:
    """Read-only result returned by an injected trusted backend verifier."""

    package_id: str
    manifest_hash: str
    spec_hash: str
    expected_artifact_hash: str
    observed_artifact_hash: str
    expected_source_result_content_hash: str
    observed_source_result_content_hash: str
    expected_source_integrity_hash: str
    observed_source_integrity_hash: str
    expected_source_strategy_sha256: str
    observed_source_strategy_sha256: str
    expected_replay_result_sha256: str
    observed_replay_result_sha256: str
    expected_replay_artifact_hash: str
    observed_replay_artifact_hash: str
    environment_lock_ref: str
    outcome: str
    passed: bool
    runner_ref: str
    evidence_refs: tuple[str, ...]
    verified_at_utc: str
    valid_until_utc: str
    errors: tuple[str, ...] = ()
    residuals: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        for field_name in (
            "package_id",
            "manifest_hash",
            "spec_hash",
            "expected_artifact_hash",
            "observed_artifact_hash",
            "expected_source_result_content_hash",
            "observed_source_result_content_hash",
            "expected_source_integrity_hash",
            "observed_source_integrity_hash",
            "expected_source_strategy_sha256",
            "observed_source_strategy_sha256",
            "expected_replay_result_sha256",
            "observed_replay_result_sha256",
            "expected_replay_artifact_hash",
            "observed_replay_artifact_hash",
            "environment_lock_ref",
            "outcome",
            "runner_ref",
            "verified_at_utc",
            "valid_until_utc",
        ):
            object.__setattr__(self, field_name, _text(getattr(self, field_name)))
        for field_name in ("evidence_refs", "errors", "residuals"):
            object.__setattr__(self, field_name, _strings(getattr(self, field_name)))


@dataclass(frozen=True)
class RDPReproductionReceipt:
    """Immutable receipt minted only after trusted snapshot validation."""

    receipt_ref: str
    owner_user_id: str
    package_id: str
    manifest_hash: str
    spec_hash: str
    artifact_hash: str
    source_result_content_hash: str
    source_run_ref: str
    source_run_id: str
    source_file_ref: str
    source_integrity_hash: str
    source_evidence_hash: str
    source_bundle_index_sha256: str
    source_run_manifest_sha256: str
    source_strategy_sha256: str
    source_result_sha256: str
    expected_replay_result_sha256: str
    source_portfolio_sha256: str
    expected_replay_artifact_hash: str
    environment_lock_ref: str
    outcome: str
    passed: bool
    runner_ref: str
    evidence_refs: tuple[str, ...]
    verified_at_utc: str
    valid_until_utc: str
    verification_snapshot_hash: str
    receipt_version: str = REPRODUCTION_RECEIPT_VERSION

    def __post_init__(self) -> None:
        for field_name in (
            "receipt_ref",
            "owner_user_id",
            "package_id",
            "manifest_hash",
            "spec_hash",
            "artifact_hash",
            "source_result_content_hash",
            "source_run_ref",
            "source_run_id",
            "source_file_ref",
            "source_integrity_hash",
            "source_evidence_hash",
            "source_bundle_index_sha256",
            "source_run_manifest_sha256",
            "source_strategy_sha256",
            "source_result_sha256",
            "expected_replay_result_sha256",
            "source_portfolio_sha256",
            "expected_replay_artifact_hash",
            "environment_lock_ref",
            "outcome",
            "runner_ref",
            "verified_at_utc",
            "valid_until_utc",
            "verification_snapshot_hash",
            "receipt_version",
        ):
            object.__setattr__(self, field_name, _text(getattr(self, field_name)))
        object.__setattr__(self, "evidence_refs", _strings(self.evidence_refs))
        supplied = self.receipt_ref
        expected = REPRODUCTION_RECEIPT_PREFIX + content_hash(self._identity_payload())
        if supplied and supplied != expected:
            raise ValueError("RDP reproduction receipt_ref mismatch")
        object.__setattr__(self, "receipt_ref", expected)

    def _identity_payload(self) -> dict[str, Any]:
        payload = asdict(self)
        payload.pop("receipt_ref", None)
        return payload

    def to_open_dict(self) -> dict[str, Any]:
        return asdict(self)


def reproduction_verification_snapshot_from_dict(
    raw: Mapping[str, Any],
) -> RDPReproductionVerificationSnapshot:
    return RDPReproductionVerificationSnapshot(
        package_id=raw.get("package_id", ""),
        manifest_hash=raw.get("manifest_hash", ""),
        spec_hash=raw.get("spec_hash", ""),
        expected_artifact_hash=raw.get("expected_artifact_hash", ""),
        observed_artifact_hash=raw.get("observed_artifact_hash", ""),
        expected_source_result_content_hash=raw.get(
            "expected_source_result_content_hash", ""
        ),
        observed_source_result_content_hash=raw.get(
            "observed_source_result_content_hash", ""
        ),
        expected_source_integrity_hash=raw.get(
            "expected_source_integrity_hash", ""
        ),
        observed_source_integrity_hash=raw.get(
            "observed_source_integrity_hash", ""
        ),
        expected_source_strategy_sha256=raw.get(
            "expected_source_strategy_sha256", ""
        ),
        observed_source_strategy_sha256=raw.get(
            "observed_source_strategy_sha256", ""
        ),
        expected_replay_result_sha256=raw.get(
            "expected_replay_result_sha256", ""
        ),
        observed_replay_result_sha256=raw.get(
            "observed_replay_result_sha256", ""
        ),
        expected_replay_artifact_hash=raw.get(
            "expected_replay_artifact_hash", ""
        ),
        observed_replay_artifact_hash=raw.get(
            "observed_replay_artifact_hash", ""
        ),
        environment_lock_ref=raw.get("environment_lock_ref", ""),
        outcome=raw.get("outcome", ""),
        passed=raw.get("passed") is True,
        runner_ref=raw.get("runner_ref", ""),
        evidence_refs=_strings(raw.get("evidence_refs")),
        verified_at_utc=raw.get("verified_at_utc", ""),
        valid_until_utc=raw.get("valid_until_utc", ""),
        errors=_strings(raw.get("errors")),
        residuals=_strings(raw.get("residuals")),
    )


def reproduction_receipt_from_dict(raw: Mapping[str, Any]) -> RDPReproductionReceipt:
    expected_fields = {item.name for item in fields(RDPReproductionReceipt)}
    actual_fields = set(raw)
    if actual_fields != expected_fields:
        missing = sorted(expected_fields - actual_fields)
        unknown = sorted(actual_fields - expected_fields)
        raise ValueError(
            "RDP reproduction receipt requires the exact v2 field set "
            f"(missing={missing}, unknown={unknown})"
        )
    receipt = RDPReproductionReceipt(
        receipt_ref=raw.get("receipt_ref", ""),
        owner_user_id=raw.get("owner_user_id", ""),
        package_id=raw.get("package_id", ""),
        manifest_hash=raw.get("manifest_hash", ""),
        spec_hash=raw.get("spec_hash", ""),
        artifact_hash=raw.get("artifact_hash", ""),
        source_result_content_hash=raw.get("source_result_content_hash", ""),
        source_run_ref=raw.get("source_run_ref", ""),
        source_run_id=raw.get("source_run_id", ""),
        source_file_ref=raw.get("source_file_ref", ""),
        source_integrity_hash=raw.get("source_integrity_hash", ""),
        source_evidence_hash=raw.get("source_evidence_hash", ""),
        source_bundle_index_sha256=raw.get("source_bundle_index_sha256", ""),
        source_run_manifest_sha256=raw.get("source_run_manifest_sha256", ""),
        source_strategy_sha256=raw.get("source_strategy_sha256", ""),
        source_result_sha256=raw.get("source_result_sha256", ""),
        expected_replay_result_sha256=raw.get(
            "expected_replay_result_sha256", ""
        ),
        source_portfolio_sha256=raw.get("source_portfolio_sha256", ""),
        expected_replay_artifact_hash=raw.get(
            "expected_replay_artifact_hash", ""
        ),
        environment_lock_ref=raw.get("environment_lock_ref", ""),
        outcome=raw.get("outcome", ""),
        passed=raw.get("passed") is True,
        runner_ref=raw.get("runner_ref", ""),
        evidence_refs=_strings(raw.get("evidence_refs")),
        verified_at_utc=raw.get("verified_at_utc", ""),
        valid_until_utc=raw.get("valid_until_utc", ""),
        verification_snapshot_hash=raw.get("verification_snapshot_hash", ""),
        receipt_version=raw.get(
            "receipt_version", REPRODUCTION_RECEIPT_VERSION
        ),
    )
    if canonical_json(dict(raw)) != canonical_json(receipt.to_open_dict()):
        raise ValueError(
            "RDP reproduction receipt payload is not the exact canonical v2 representation"
        )
    return receipt


class RDPReproductionReceiptRejected(ValueError):
    """Trusted verification or current receipt validation failed closed."""

    def __init__(self, violations: tuple[str, ...]) -> None:
        self.violations = violations
        super().__init__("; ".join(violations) or "RDP reproduction receipt rejected")


def _snapshot_violations(
    snapshot: RDPReproductionVerificationSnapshot,
    *,
    spec: RDPReproductionSpec,
    allowed_runner_refs: frozenset[str],
    now_utc: dt.datetime,
) -> tuple[str, ...]:
    violations: list[str] = []
    expected = {
        "package_id": spec.package_id,
        "manifest_hash": spec.manifest_hash,
        "spec_hash": spec.spec_hash,
        "expected_artifact_hash": spec.artifact_hash,
        "expected_source_result_content_hash": spec.source_result_content_hash,
        "expected_source_integrity_hash": spec.source_integrity_hash,
        "expected_source_strategy_sha256": spec.source_strategy_sha256,
        "expected_replay_result_sha256": spec.expected_replay_result_sha256,
        "expected_replay_artifact_hash": spec.expected_replay_artifact_hash,
        "environment_lock_ref": spec.environment_lock_ref,
    }
    for field_name, expected_value in expected.items():
        if getattr(snapshot, field_name) != expected_value:
            violations.append(f"reproduction_snapshot_{field_name}_mismatch")
    if snapshot.observed_artifact_hash != spec.artifact_hash:
        violations.append("reproduction_snapshot_artifact_drift")
    if snapshot.observed_source_result_content_hash != spec.source_result_content_hash:
        violations.append("reproduction_snapshot_result_drift")
    if snapshot.observed_source_integrity_hash != spec.source_integrity_hash:
        violations.append("reproduction_snapshot_source_integrity_drift")
    if snapshot.observed_source_strategy_sha256 != spec.source_strategy_sha256:
        violations.append("reproduction_snapshot_strategy_drift")
    if snapshot.observed_replay_result_sha256 != spec.expected_replay_result_sha256:
        violations.append("reproduction_snapshot_replay_result_sha256_drift")
    if snapshot.observed_replay_artifact_hash != spec.expected_replay_artifact_hash:
        violations.append("reproduction_snapshot_replay_artifact_drift")
    if snapshot.outcome != "passed" or snapshot.passed is not True:
        violations.append("reproduction_snapshot_not_passed")
    if snapshot.runner_ref not in allowed_runner_refs:
        violations.append("reproduction_snapshot_runner_not_allowlisted")
    if not snapshot.evidence_refs or len(snapshot.evidence_refs) != len(
        set(snapshot.evidence_refs)
    ):
        violations.append("reproduction_snapshot_evidence_invalid")
    if snapshot.errors:
        violations.append("reproduction_snapshot_has_errors")
    if snapshot.residuals:
        violations.append("reproduction_snapshot_has_residuals")
    try:
        verified_at = _aware_utc(snapshot.verified_at_utc, "verified_at_utc")
        valid_until = _aware_utc(snapshot.valid_until_utc, "valid_until_utc")
    except ValueError:
        violations.append("reproduction_snapshot_time_invalid")
    else:
        if verified_at > now_utc:
            violations.append("reproduction_snapshot_from_future")
        if valid_until <= verified_at or valid_until <= now_utc:
            violations.append("reproduction_snapshot_stale")
        if valid_until - verified_at > dt.timedelta(
            seconds=MAX_REPRODUCTION_RECEIPT_VALIDITY_SECONDS
        ):
            violations.append("reproduction_snapshot_validity_exceeds_policy")
    return tuple(dict.fromkeys(violations))


def reproduction_receipt_violations(
    receipt: RDPReproductionReceipt,
    *,
    manifest: RDPManifest,
    owner_user_id: str,
    source_result_content_hash: str,
    allowed_runner_refs: frozenset[str] | None = None,
    now_utc: dt.datetime | None = None,
) -> tuple[str, ...]:
    """Validate exact content binding and freshness without running any command."""

    now = (now_utc or dt.datetime.now(dt.UTC)).astimezone(dt.UTC)
    violations: list[str] = []
    try:
        source_evidence = RDPReproductionSourceEvidence(
            package_id=receipt.package_id,
            source_run_ref=receipt.source_run_ref,
            source_run_id=receipt.source_run_id,
            source_file_ref=receipt.source_file_ref,
            manifest_hash=receipt.manifest_hash,
            source_artifact_hash=receipt.artifact_hash,
            source_integrity_hash=receipt.source_integrity_hash,
            source_bundle_index_sha256=receipt.source_bundle_index_sha256,
            source_run_manifest_sha256=receipt.source_run_manifest_sha256,
            source_strategy_sha256=receipt.source_strategy_sha256,
            source_result_sha256=receipt.source_result_sha256,
            expected_replay_result_sha256=receipt.expected_replay_result_sha256,
            source_portfolio_sha256=receipt.source_portfolio_sha256,
            source_result_content_hash=receipt.source_result_content_hash,
            expected_replay_artifact_hash=receipt.expected_replay_artifact_hash,
            source_evidence_hash=receipt.source_evidence_hash,
        )
        spec = reproduction_spec(
            manifest,
            source_result_content_hash=source_result_content_hash,
            source_evidence=source_evidence,
        )
    except ValueError:
        return ("reproduction_receipt_manifest_or_spec_invalid",)
    expected = {
        "owner_user_id": _text(owner_user_id),
        "package_id": spec.package_id,
        "manifest_hash": spec.manifest_hash,
        "spec_hash": spec.spec_hash,
        "artifact_hash": spec.artifact_hash,
        "source_result_content_hash": spec.source_result_content_hash,
        "source_run_ref": spec.source_run_ref,
        "source_run_id": spec.source_run_id,
        "source_file_ref": spec.source_file_ref,
        "source_integrity_hash": spec.source_integrity_hash,
        "source_evidence_hash": spec.source_evidence_hash,
        "source_bundle_index_sha256": spec.source_bundle_index_sha256,
        "source_run_manifest_sha256": spec.source_run_manifest_sha256,
        "source_strategy_sha256": spec.source_strategy_sha256,
        "source_result_sha256": spec.source_result_sha256,
        "expected_replay_result_sha256": spec.expected_replay_result_sha256,
        "source_portfolio_sha256": spec.source_portfolio_sha256,
        "expected_replay_artifact_hash": spec.expected_replay_artifact_hash,
        "environment_lock_ref": spec.environment_lock_ref,
        "receipt_version": REPRODUCTION_RECEIPT_VERSION,
    }
    for field_name, expected_value in expected.items():
        if not expected_value or getattr(receipt, field_name) != expected_value:
            violations.append(f"reproduction_receipt_{field_name}_mismatch")
    if receipt.outcome != "passed" or receipt.passed is not True:
        violations.append("reproduction_receipt_not_passed")
    if allowed_runner_refs is not None and receipt.runner_ref not in allowed_runner_refs:
        violations.append("reproduction_receipt_runner_not_allowlisted")
    if not receipt.runner_ref:
        violations.append("reproduction_receipt_runner_missing")
    if not receipt.evidence_refs or len(receipt.evidence_refs) != len(
        set(receipt.evidence_refs)
    ):
        violations.append("reproduction_receipt_evidence_invalid")
    if not _SHA16.fullmatch(receipt.verification_snapshot_hash):
        violations.append("reproduction_receipt_snapshot_hash_invalid")
    try:
        verified_at = _aware_utc(receipt.verified_at_utc, "verified_at_utc")
        valid_until = _aware_utc(receipt.valid_until_utc, "valid_until_utc")
    except ValueError:
        violations.append("reproduction_receipt_time_invalid")
    else:
        if verified_at > now:
            violations.append("reproduction_receipt_from_future")
        if valid_until <= verified_at or valid_until <= now:
            violations.append("reproduction_receipt_stale")
        if valid_until - verified_at > dt.timedelta(
            seconds=MAX_REPRODUCTION_RECEIPT_VALIDITY_SECONDS
        ):
            violations.append("reproduction_receipt_validity_exceeds_policy")
    if receipt.receipt_ref != REPRODUCTION_RECEIPT_PREFIX + content_hash(
        receipt._identity_payload()
    ):
        violations.append("reproduction_receipt_identity_mismatch")
    return tuple(dict.fromkeys(violations))


class IDEReproductionSourceResolver:
    """Resolve one exact, re-attested IDE source package for reproduction."""

    def __init__(
        self,
        *,
        integrity_store: Any,
        package_root: str | Path,
        ide_run_root: str | Path,
    ) -> None:
        if not hasattr(integrity_store, "records") or not hasattr(
            integrity_store, "record_integrity"
        ):
            raise ValueError("canonical RDP source-run integrity store is required")
        self._integrity_store = integrity_store
        self._package_root = Path(package_root)
        self._ide_run_root = Path(ide_run_root)

    @staticmethod
    def _ide_run_binding(manifest: RDPManifest) -> tuple[str, str, str]:
        if len(manifest.asset_refs) != 1 or not manifest.asset_refs[0].startswith(
            "ide_run:"
        ):
            raise ValueError("RDP reproduction requires exactly one ide_run asset_ref")
        run_ref = manifest.asset_refs[0]
        run_id = run_ref.removeprefix("ide_run:")
        if (
            not run_id
            or run_id in {".", ".."}
            or any(ch not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-." for ch in run_id)
        ):
            raise ValueError("RDP reproduction IDE run_id is unsafe")
        if manifest.run_refs != (run_ref,):
            raise ValueError("RDP reproduction run_refs must exactly bind the IDE source run")
        if len(manifest.source_file_refs) != 1:
            raise ValueError("RDP reproduction requires exactly one source_file_ref")
        return run_ref, run_id, manifest.source_file_refs[0]

    def _run_file(self, run_id: str, name: str) -> Path:
        root = self._ide_run_root.resolve()
        run_dir = root / run_id
        if run_dir.is_symlink():
            raise ValueError("RDP reproduction refuses symlink IDE run directory")
        resolved_dir = run_dir.resolve()
        try:
            resolved_dir.relative_to(root)
        except ValueError as exc:
            raise ValueError("RDP reproduction IDE run path escapes run root") from exc
        path = resolved_dir / name
        if path.is_symlink() or not path.exists() or not path.is_file():
            raise ValueError(f"RDP reproduction source artifact is required: {name}")
        return path

    def __call__(
        self,
        owner_user_id: str,
        manifest: RDPManifest,
        source_result_content_hash: str,
    ) -> ResolvedRDPReproductionSource:
        owner = _text(owner_user_id)
        if not owner:
            raise ValueError("RDP reproduction owner is required")
        run_ref, run_id, source_file_ref = self._ide_run_binding(manifest)
        manifest_digest = rdp_manifest_hash(manifest)
        matching = [
            record
            for record in self._integrity_store.records(
                manifest.package_id,
                owner_user_id=owner,
            )
            if record.package_id == manifest.package_id
            and record.run_ref == run_ref
            and record.run_id == run_id
            and record.source_file_ref == source_file_ref
            and record.manifest_hash == manifest_digest
            and record.artifact_hash == manifest.artifact_hash
        ]
        if not matching:
            raise ValueError("current exact RDP source-run integrity record not found")
        evidence_states = {
            (
                record.package_id,
                record.run_ref,
                record.run_id,
                record.source_file_ref,
                record.manifest_hash,
                record.manifest_file_sha256,
                record.refs_index_sha256,
                record.source_bundle_index_sha256,
                record.bundled_source_sha256,
                record.run_manifest_sha256,
                record.run_strategy_sha256,
                record.run_portfolio_sha256,
                record.artifact_hash,
            )
            for record in matching
        }
        if len(evidence_states) != 1:
            raise ValueError("current exact RDP source-run integrity record is ambiguous")
        # Repeated attestations of identical bytes are not an ambiguity.  The
        # newest attestation identity becomes the current source evidence.
        recorded = max(
            matching,
            key=lambda item: (str(item.attested_at), str(item.integrity_hash)),
        )
        current = self._integrity_store.record_integrity(
            manifest,
            owner_user_id=owner,
            package_root=self._package_root,
            run_root=self._ide_run_root,
            run_id=run_id,
            source_file_ref=source_file_ref,
            attested_by=recorded.attested_by,
            attested_at=recorded.attested_at,
        )
        if current != recorded:
            raise ValueError("RDP source-run integrity re-attestation drifted")

        strategy_path = self._run_file(run_id, "strategy.py")
        result_path = self._run_file(run_id, "result.json")
        strategy_code = strategy_path.read_text(encoding="utf-8")
        result_bytes = result_path.read_bytes()
        try:
            result = json.loads(result_bytes.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError("RDP reproduction result.json is invalid") from exc
        if not isinstance(result, dict):
            raise ValueError("RDP reproduction result.json must be an object")
        result_content_hash = content_hash(result)
        if result_content_hash != _text(source_result_content_hash):
            raise ValueError("RDP reproduction source result does not match promotion result")
        # Lazy import avoids the release-gate -> IDE package initialization cycle.
        from .rdp_replay import reproduction_artifact_hash

        evidence = RDPReproductionSourceEvidence(
            package_id=manifest.package_id,
            source_run_ref=run_ref,
            source_run_id=run_id,
            source_file_ref=source_file_ref,
            manifest_hash=current.manifest_hash,
            source_artifact_hash=current.artifact_hash,
            source_integrity_hash=current.integrity_hash,
            source_bundle_index_sha256=current.source_bundle_index_sha256,
            source_run_manifest_sha256=current.run_manifest_sha256,
            source_strategy_sha256=current.run_strategy_sha256,
            source_result_sha256=_sha256_bytes(result_bytes),
            expected_replay_result_sha256=_sha256_bytes(
                canonical_json(result).encode("utf-8")
            ),
            source_portfolio_sha256=current.run_portfolio_sha256,
            source_result_content_hash=result_content_hash,
            expected_replay_artifact_hash=reproduction_artifact_hash(result),
        )
        return ResolvedRDPReproductionSource(
            evidence=evidence,
            strategy_code=strategy_code,
        )


def repository_reproduction_verification_loader(
    owner_user_id: str,
    manifest: RDPManifest,
    spec: RDPReproductionSpec,
    resolved_source: ResolvedRDPReproductionSource,
) -> RDPReproductionVerificationSnapshot:
    """Run the repository replay worker and preserve its non-hardened residual."""

    _ = owner_user_id, manifest
    # Lazy import avoids importing ``app.ide`` while release-gate modules initialize.
    from .rdp_replay import run_replay_subprocess

    observation = run_replay_subprocess(resolved_source.strategy_code)
    errors: list[str] = []
    if observation.observed_strategy_sha256 != spec.source_strategy_sha256:
        errors.append("replay_strategy_drift")
    if (
        observation.observed_source_result_content_hash
        != spec.source_result_content_hash
    ):
        errors.append("replay_result_content_drift")
    if observation.observed_result_sha256 != spec.expected_replay_result_sha256:
        errors.append("replay_result_sha256_drift")
    if observation.observed_artifact_hash != spec.expected_replay_artifact_hash:
        errors.append("replay_artifact_drift")
    now = dt.datetime.now(dt.UTC)
    passed = not errors
    return RDPReproductionVerificationSnapshot(
        package_id=spec.package_id,
        manifest_hash=spec.manifest_hash,
        spec_hash=spec.spec_hash,
        expected_artifact_hash=spec.artifact_hash,
        # This is the re-resolved immutable package artifact, not the replay digest.
        observed_artifact_hash=resolved_source.evidence.source_artifact_hash,
        expected_source_result_content_hash=spec.source_result_content_hash,
        observed_source_result_content_hash=(
            observation.observed_source_result_content_hash
        ),
        expected_source_integrity_hash=spec.source_integrity_hash,
        observed_source_integrity_hash=resolved_source.evidence.source_integrity_hash,
        expected_source_strategy_sha256=spec.source_strategy_sha256,
        observed_source_strategy_sha256=observation.observed_strategy_sha256,
        expected_replay_result_sha256=spec.expected_replay_result_sha256,
        observed_replay_result_sha256=observation.observed_result_sha256,
        expected_replay_artifact_hash=spec.expected_replay_artifact_hash,
        observed_replay_artifact_hash=observation.observed_artifact_hash,
        environment_lock_ref=spec.environment_lock_ref,
        outcome="passed" if passed else "failed",
        passed=passed,
        runner_ref=observation.runner_ref,
        evidence_refs=tuple(
            dict.fromkeys(
                (
                    f"rdp_source_run_integrity:{spec.source_integrity_hash}",
                    f"rdp_source_evidence:{spec.source_evidence_hash}",
                    *observation.evidence_refs,
                )
            )
        ),
        verified_at_utc=now.isoformat(),
        valid_until_utc=(now + dt.timedelta(minutes=5)).isoformat(),
        errors=tuple(errors),
        residuals=observation.residuals,
    )


ReproductionSourceResolver: TypeAlias = Callable[
    [str, RDPManifest, str],
    ResolvedRDPReproductionSource,
]
ReproductionVerificationLoader: TypeAlias = Callable[
    [str, RDPManifest, RDPReproductionSpec, ResolvedRDPReproductionSource],
    RDPReproductionVerificationSnapshot | Mapping[str, Any],
]


def _receipt_event_row(
    receipt: RDPReproductionReceipt,
    *,
    owner_user_id: str,
) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "event_type": "rdp_reproduction_receipt_recorded",
        "owner_user_id": _text(owner_user_id),
        "receipt": receipt.to_open_dict(),
    }


class PersistentRDPReproductionReceiptStore:
    """Owner-scoped append-only receipts issued through a trusted loader only."""

    def __init__(
        self,
        path: str | Path,
        verification_loader: ReproductionVerificationLoader,
        *,
        source_resolver: ReproductionSourceResolver,
        allowed_runner_refs: tuple[str, ...],
    ) -> None:
        if not callable(verification_loader):
            raise ValueError("trusted reproduction verification_loader is required")
        if not callable(source_resolver):
            raise ValueError("trusted reproduction source_resolver is required")
        allowed = frozenset(_strings(allowed_runner_refs))
        if not allowed:
            raise ValueError("at least one allowlisted backend reproduction runner is required")
        self._path = Path(path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._lock_path = self._path.with_name(f".{self._path.name}.lock")
        self._verification_loader = verification_loader
        self._source_resolver = source_resolver
        self._allowed_runner_refs = allowed
        self._lock = threading.RLock()
        with self._lock, self._exclusive_lock():
            self._replay_unlocked()

    @property
    def path(self) -> Path:
        return self._path

    @contextmanager
    def _exclusive_lock(self) -> Iterator[None]:
        fd = os.open(self._lock_path, os.O_RDWR | os.O_CREAT, 0o600)
        held = None
        try:
            os.chmod(self._lock_path, 0o600)
            held = acquire_exclusive_fd(fd, timeout_seconds=30.0)
            yield
        finally:
            if held is not None:
                held.release()
            os.close(fd)

    def _replay_unlocked(self) -> dict[tuple[str, str], list[RDPReproductionReceipt]]:
        records: dict[tuple[str, str], list[RDPReproductionReceipt]] = {}
        if not self._path.exists():
            return records
        with self._path.open("r", encoding="utf-8") as handle:
            for line_no, line in enumerate(handle, start=1):
                if not line.strip():
                    continue
                try:
                    row = json.loads(line)
                    if row.get("schema_version") != 1:
                        raise ValueError("unsupported schema_version")
                    if row.get("event_type") != "rdp_reproduction_receipt_recorded":
                        raise ValueError("unknown event_type")
                    owner = _text(row.get("owner_user_id"))
                    raw = row.get("receipt")
                    if not owner or not isinstance(raw, Mapping):
                        raise ValueError("owner-enveloped receipt is required")
                    receipt = reproduction_receipt_from_dict(raw)
                    if receipt.owner_user_id != owner:
                        raise ValueError("receipt owner does not match event envelope")
                    records.setdefault((owner, receipt.package_id), []).append(receipt)
                except Exception as exc:  # noqa: BLE001 - corrupt authority fails startup.
                    raise ValueError(
                        f"invalid persisted RDP reproduction receipt at {self._path}:{line_no}"
                    ) from exc
        return records

    def _append_unlocked(self, row: dict[str, Any]) -> None:
        encoded = json.dumps(
            row,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ) + "\n"
        with self._path.open("a", encoding="utf-8") as handle:
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())

    def record_current(
        self,
        *,
        owner_user_id: str,
        manifest: RDPManifest,
        source_result_content_hash: str,
        now_utc: dt.datetime | None = None,
    ) -> RDPReproductionReceipt:
        """Run the injected verifier and mint only its exact, current pass."""

        owner = _text(owner_user_id)
        if not owner:
            raise RDPReproductionReceiptRejected(("reproduction_receipt_owner_missing",))
        now = (now_utc or dt.datetime.now(dt.UTC)).astimezone(dt.UTC)
        try:
            resolved_source = self._source_resolver(
                owner,
                manifest,
                source_result_content_hash,
            )
            if not isinstance(resolved_source, ResolvedRDPReproductionSource):
                raise TypeError("source resolver returned malformed value")
            spec = reproduction_spec(
                manifest,
                source_result_content_hash=source_result_content_hash,
                source_evidence=resolved_source.evidence,
            )
        except Exception as exc:  # noqa: BLE001 - source resolution is authoritative.
            raise RDPReproductionReceiptRejected(
                (
                    "reproduction_source_resolution_failed:"
                    f"{type(exc).__name__}:{_text(exc)}",
                )
            ) from exc
        try:
            raw_snapshot = self._verification_loader(
                owner,
                manifest,
                spec,
                resolved_source,
            )
        except Exception as exc:  # noqa: BLE001 - verifier failure is a red gate.
            raise RDPReproductionReceiptRejected(
                (f"reproduction_verification_loader_failed:{type(exc).__name__}",)
            ) from exc
        if isinstance(raw_snapshot, RDPReproductionVerificationSnapshot):
            snapshot = raw_snapshot
        elif isinstance(raw_snapshot, Mapping):
            snapshot = reproduction_verification_snapshot_from_dict(raw_snapshot)
        else:
            raise RDPReproductionReceiptRejected(
                ("reproduction_verification_snapshot_malformed",)
            )
        try:
            post_verify_source = self._source_resolver(
                owner,
                manifest,
                source_result_content_hash,
            )
            if not isinstance(post_verify_source, ResolvedRDPReproductionSource):
                raise TypeError("source resolver returned malformed value")
            post_verify_spec = reproduction_spec(
                manifest,
                source_result_content_hash=source_result_content_hash,
                source_evidence=post_verify_source.evidence,
            )
        except Exception as exc:  # noqa: BLE001 - post-run source must still resolve.
            raise RDPReproductionReceiptRejected(
                (
                    "reproduction_post_verification_source_resolution_failed:"
                    f"{type(exc).__name__}:{_text(exc)}",
                )
            ) from exc
        if post_verify_spec != spec:
            raise RDPReproductionReceiptRejected(
                ("reproduction_source_drifted_during_verification",)
            )
        # A trusted loader may stamp completion a few microseconds after this
        # method began.  Compare against post-verification wall time unless a
        # deterministic validation instant was explicitly supplied.
        if now_utc is None:
            now = dt.datetime.now(dt.UTC)
        violations = _snapshot_violations(
            snapshot,
            spec=spec,
            allowed_runner_refs=self._allowed_runner_refs,
            now_utc=now,
        )
        if violations:
            raise RDPReproductionReceiptRejected(violations)
        snapshot_hash = "sha16:" + content_hash(asdict(snapshot))
        receipt = RDPReproductionReceipt(
            receipt_ref="",
            owner_user_id=owner,
            package_id=spec.package_id,
            manifest_hash=spec.manifest_hash,
            spec_hash=spec.spec_hash,
            artifact_hash=spec.artifact_hash,
            source_result_content_hash=spec.source_result_content_hash,
            source_run_ref=spec.source_run_ref,
            source_run_id=spec.source_run_id,
            source_file_ref=spec.source_file_ref,
            source_integrity_hash=spec.source_integrity_hash,
            source_evidence_hash=spec.source_evidence_hash,
            source_bundle_index_sha256=spec.source_bundle_index_sha256,
            source_run_manifest_sha256=spec.source_run_manifest_sha256,
            source_strategy_sha256=spec.source_strategy_sha256,
            source_result_sha256=spec.source_result_sha256,
            expected_replay_result_sha256=spec.expected_replay_result_sha256,
            source_portfolio_sha256=spec.source_portfolio_sha256,
            expected_replay_artifact_hash=spec.expected_replay_artifact_hash,
            environment_lock_ref=spec.environment_lock_ref,
            outcome=snapshot.outcome,
            passed=snapshot.passed,
            runner_ref=snapshot.runner_ref,
            evidence_refs=snapshot.evidence_refs,
            verified_at_utc=snapshot.verified_at_utc,
            valid_until_utc=snapshot.valid_until_utc,
            verification_snapshot_hash=snapshot_hash,
        )
        receipt_violations = reproduction_receipt_violations(
            receipt,
            manifest=manifest,
            owner_user_id=owner,
            source_result_content_hash=spec.source_result_content_hash,
            allowed_runner_refs=self._allowed_runner_refs,
            now_utc=now,
        )
        if receipt_violations:
            raise RDPReproductionReceiptRejected(receipt_violations)

        row = _receipt_event_row(receipt, owner_user_id=owner)
        with self._lock, self._exclusive_lock():
            records = self._replay_unlocked()
            existing = next(
                (
                    item
                    for item in records.get((owner, receipt.package_id), ())
                    if item.receipt_ref == receipt.receipt_ref
                ),
                None,
            )
            if existing is not None:
                return existing
            self._append_unlocked(row)
        return receipt

    def current_passed(
        self,
        *,
        owner_user_id: str,
        manifest: RDPManifest,
        source_result_content_hash: str,
        now_utc: dt.datetime | None = None,
    ) -> RDPReproductionReceipt:
        """Resolve the newest still-current receipt for the exact content."""

        owner = _text(owner_user_id)
        now = (now_utc or dt.datetime.now(dt.UTC)).astimezone(dt.UTC)
        try:
            resolved_source = self._source_resolver(
                owner,
                manifest,
                source_result_content_hash,
            )
            if not isinstance(resolved_source, ResolvedRDPReproductionSource):
                raise TypeError("source resolver returned malformed value")
            current_spec = reproduction_spec(
                manifest,
                source_result_content_hash=source_result_content_hash,
                source_evidence=resolved_source.evidence,
            )
        except Exception as exc:  # noqa: BLE001 - current source must revalidate.
            raise RDPReproductionReceiptRejected(
                (
                    "reproduction_source_resolution_failed:"
                    f"{type(exc).__name__}:{_text(exc)}",
                )
            ) from exc
        with self._lock, self._exclusive_lock():
            records = self._replay_unlocked().get((owner, manifest.package_id), ())
        current: list[RDPReproductionReceipt] = []
        for receipt in records:
            if (
                receipt.spec_hash == current_spec.spec_hash
                and receipt.source_evidence_hash == current_spec.source_evidence_hash
                and not reproduction_receipt_violations(
                    receipt,
                    manifest=manifest,
                    owner_user_id=owner,
                    source_result_content_hash=source_result_content_hash,
                    allowed_runner_refs=self._allowed_runner_refs,
                    now_utc=now,
                )
            ):
                current.append(receipt)
        if not current:
            raise RDPReproductionReceiptRejected(
                ("current_reproduction_receipt_not_found",)
            )
        return max(
            current,
            key=lambda item: _aware_utc(item.verified_at_utc, "verified_at_utc"),
        )


__all__ = [
    "IDEReproductionSourceResolver",
    "PersistentRDPReproductionReceiptStore",
    "MAX_REPRODUCTION_RECEIPT_VALIDITY_SECONDS",
    "RDPReproductionReceipt",
    "RDPReproductionReceiptRejected",
    "RDPReproductionSourceEvidence",
    "RDPReproductionSpec",
    "RDPReproductionVerificationSnapshot",
    "ResolvedRDPReproductionSource",
    "REPRODUCTION_RECEIPT_PREFIX",
    "REPRODUCTION_RECEIPT_VERSION",
    "REPRODUCTION_SPEC_VERSION",
    "rdp_manifest_hash",
    "reproduction_receipt_from_dict",
    "reproduction_receipt_violations",
    "reproduction_spec",
    "reproduction_verification_snapshot_from_dict",
    "repository_reproduction_verification_loader",
]
