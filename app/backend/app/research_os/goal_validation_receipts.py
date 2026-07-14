"""Durable owner-bound receipts for GOAL entrypoint validation refs.

Entrypoint/compiler ``validation_refs`` are indexes into this ledger; their
string presence is not validation evidence.  A receipt content-binds the
validated QRO and Research Graph command sets to the validator/test run and
its evidence digests.  Failed, errored, or residual-bearing runs remain
auditable but cannot satisfy strict entrypoint coverage.
"""

from __future__ import annotations

import json
import os
import tempfile
import threading
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from enum import Enum
from pathlib import Path
from typing import Any

from ..cross_process_lock import acquire_exclusive_fd
from ..lineage.ids import content_hash
from .goal_proof_ledger import GoalProofLedger
from .goal_proof_records import (
    ATOMIC_PROOF_BUNDLE_REQUIRED,
    LOGICAL_TYPE_VALIDATION_RECEIPT,
    GoalProofRecordProjection,
    GoalProofRecordProjectionError,
    ProofRecordCodec,
    decode_proof_record_head,
)
from .ref_resolution import is_placeholder_ref


def _refs(value: Any) -> tuple[str, ...]:
    if value is None:
        return ()
    values = value if isinstance(value, (tuple, list)) else (value,)
    return tuple(
        text
        for item in values
        if (text := str(item or "").strip())
    )


class GoalValidationOutcome(str, Enum):
    PASSED = "passed"
    FAILED = "failed"
    ERROR = "error"
    SKIPPED = "skipped"


@dataclass(frozen=True)
class GoalValidationViolation:
    code: str
    message: str
    field: str = ""
    ref: str = ""


@dataclass(frozen=True)
class GoalValidationDecision:
    accepted: bool
    violations: tuple[GoalValidationViolation, ...]


@dataclass(frozen=True)
class GoalValidationReceipt:
    validation_ref: str
    owner_user_id: str
    subject_qro_refs: tuple[str, ...]
    graph_command_refs: tuple[str, ...]
    validator_identifiers: tuple[str, ...]
    test_identifiers: tuple[str, ...]
    outcome: GoalValidationOutcome | str
    evidence_refs: tuple[str, ...]
    evidence_digests: tuple[str, ...]
    residuals: tuple[str, ...] = ()
    receipt_version: str = "goal_validation_receipt.v1"

    def __post_init__(self) -> None:
        object.__setattr__(self, "validation_ref", str(self.validation_ref or "").strip())
        object.__setattr__(self, "owner_user_id", str(self.owner_user_id or "").strip())
        for field_name in (
            "subject_qro_refs",
            "graph_command_refs",
            "validator_identifiers",
            "test_identifiers",
            "evidence_refs",
            "evidence_digests",
            "residuals",
        ):
            object.__setattr__(self, field_name, _refs(getattr(self, field_name)))
        outcome = (
            self.outcome.value
            if isinstance(self.outcome, GoalValidationOutcome)
            else self.outcome
        )
        object.__setattr__(self, "outcome", str(outcome or "").strip().lower())
        object.__setattr__(
            self,
            "receipt_version",
            str(self.receipt_version or "").strip(),
        )

    @property
    def canonical_validation_ref(self) -> str:
        return goal_validation_receipt_identity(
            owner_user_id=self.owner_user_id,
            subject_qro_refs=self.subject_qro_refs,
            graph_command_refs=self.graph_command_refs,
            validator_identifiers=self.validator_identifiers,
            test_identifiers=self.test_identifiers,
            outcome=str(self.outcome),
            evidence_refs=self.evidence_refs,
            evidence_digests=self.evidence_digests,
            residuals=self.residuals,
            receipt_version=self.receipt_version,
        )


def goal_validation_receipt_identity(
    *,
    owner_user_id: str,
    subject_qro_refs: tuple[str, ...],
    graph_command_refs: tuple[str, ...],
    validator_identifiers: tuple[str, ...],
    test_identifiers: tuple[str, ...],
    outcome: GoalValidationOutcome | str,
    evidence_refs: tuple[str, ...],
    evidence_digests: tuple[str, ...],
    residuals: tuple[str, ...] = (),
    receipt_version: str = "goal_validation_receipt.v1",
) -> str:
    outcome_value = outcome.value if isinstance(outcome, GoalValidationOutcome) else outcome
    return "goal_validation_receipt:" + content_hash(
        {
            "owner_user_id": str(owner_user_id or "").strip(),
            "subject_qro_refs": _refs(subject_qro_refs),
            "graph_command_refs": _refs(graph_command_refs),
            "validator_identifiers": _refs(validator_identifiers),
            "test_identifiers": _refs(test_identifiers),
            "outcome": str(outcome_value or "").strip().lower(),
            "evidence_refs": _refs(evidence_refs),
            "evidence_digests": _refs(evidence_digests),
            "residuals": _refs(residuals),
            "receipt_version": str(receipt_version or "").strip(),
        }
    )


def goal_validation_receipt_from_dict(data: dict[str, Any]) -> GoalValidationReceipt:
    return GoalValidationReceipt(
        validation_ref=str(data.get("validation_ref") or ""),
        owner_user_id=str(data.get("owner_user_id") or ""),
        subject_qro_refs=_refs(data.get("subject_qro_refs")),
        graph_command_refs=_refs(data.get("graph_command_refs")),
        validator_identifiers=_refs(data.get("validator_identifiers")),
        test_identifiers=_refs(data.get("test_identifiers")),
        outcome=str(data.get("outcome") or ""),
        evidence_refs=_refs(data.get("evidence_refs")),
        evidence_digests=_refs(data.get("evidence_digests")),
        residuals=_refs(data.get("residuals")),
        receipt_version=str(
            data.get("receipt_version") or "goal_validation_receipt.v1"
        ),
    )


GOAL_VALIDATION_RECEIPT_PROOF_CODEC = ProofRecordCodec[
    GoalValidationReceipt
](
    logical_type=LOGICAL_TYPE_VALIDATION_RECEIPT,
    record_type=GoalValidationReceipt,
    decode=goal_validation_receipt_from_dict,
    logical_ref=lambda record: record.validation_ref,
    owner=lambda record: record.owner_user_id,
)


def _valid_digest(value: str) -> bool:
    token = str(value or "").strip().lower()
    if ":" in token:
        algorithm, token = token.split(":", 1)
        expected_length = {"sha16": 16, "sha256": 64}.get(algorithm)
        if expected_length is None or len(token) != expected_length:
            return False
    elif len(token) not in {16, 64}:
        return False
    return all(char in "0123456789abcdef" for char in token)


def validate_goal_validation_receipt_shape(
    record: GoalValidationReceipt,
) -> GoalValidationDecision:
    """Validate durable shape/identity without treating the outcome as green."""

    violations: list[GoalValidationViolation] = []
    for field_name in (
        "validation_ref",
        "owner_user_id",
        "subject_qro_refs",
        "graph_command_refs",
        "validator_identifiers",
        "test_identifiers",
        "evidence_refs",
        "evidence_digests",
    ):
        if not getattr(record, field_name):
            violations.append(
                GoalValidationViolation(
                    "goal_validation_receipt_required_field_missing",
                    "validation receipts require owner, subjects, validators, tests, and evidence",
                    field=field_name,
                    ref=record.validation_ref,
                )
            )
    if record.receipt_version != "goal_validation_receipt.v1":
        violations.append(
            GoalValidationViolation(
                "goal_validation_receipt_version_unsupported",
                "validation receipt version is unsupported",
                field="receipt_version",
                ref=record.validation_ref,
            )
        )
    if str(record.outcome) not in {item.value for item in GoalValidationOutcome}:
        violations.append(
            GoalValidationViolation(
                "goal_validation_receipt_outcome_unknown",
                "validation receipt outcome must be passed, failed, error, or skipped",
                field="outcome",
                ref=record.validation_ref,
            )
        )
    for field_name in (
        "subject_qro_refs",
        "graph_command_refs",
        "validator_identifiers",
        "test_identifiers",
        "evidence_refs",
        "evidence_digests",
    ):
        values = getattr(record, field_name)
        if len(values) != len(set(values)):
            violations.append(
                GoalValidationViolation(
                    "goal_validation_receipt_duplicate_value",
                    "validation receipt bound values must be unique",
                    field=field_name,
                    ref=record.validation_ref,
                )
            )
    for field_name in (
        "subject_qro_refs",
        "graph_command_refs",
        "validator_identifiers",
        "test_identifiers",
        "evidence_refs",
    ):
        for ref in getattr(record, field_name):
            if is_placeholder_ref(ref):
                violations.append(
                    GoalValidationViolation(
                        "goal_validation_receipt_placeholder_ref",
                        "validation receipts cannot bind synthetic, fixture, "
                        "placeholder, or goal-closure refs",
                        field=field_name,
                        ref=ref,
                    )
                )
    if len(record.evidence_refs) != len(record.evidence_digests):
        violations.append(
            GoalValidationViolation(
                "goal_validation_receipt_evidence_cardinality_mismatch",
                "each validation evidence ref requires exactly one content digest",
                field="evidence_digests",
                ref=record.validation_ref,
            )
        )
    for digest in record.evidence_digests:
        if not _valid_digest(digest):
            violations.append(
                GoalValidationViolation(
                    "goal_validation_receipt_digest_invalid",
                    "evidence digests must be full sha256 or project sha16 hex digests",
                    field="evidence_digests",
                    ref=digest,
                )
            )
    if record.validation_ref and record.validation_ref != record.canonical_validation_ref:
        violations.append(
            GoalValidationViolation(
                "goal_validation_receipt_identity_mismatch",
                "validation_ref must content-bind owner, subjects, validators, "
                "outcome, evidence, and residuals",
                field="validation_ref",
                ref=record.validation_ref,
            )
        )
    return GoalValidationDecision(not violations, tuple(violations))


def _same_exact_ref_set(actual: tuple[str, ...], expected: tuple[str, ...]) -> bool:
    return (
        bool(expected)
        and len(actual) == len(set(actual))
        and len(expected) == len(set(expected))
        and frozenset(actual) == frozenset(expected)
    )


def _atomic_rewrite_receipt_rows(
    path: Path,
    rows: tuple[dict[str, Any], ...],
) -> None:
    """Replace the receipt ledger with one fsynced canonical JSONL snapshot."""

    temp_path: str | None = None
    temp_fd, temp_path = tempfile.mkstemp(
        prefix=f".{path.name}.",
        suffix=".tmp",
        dir=path.parent,
    )
    try:
        os.fchmod(temp_fd, 0o600)
        with os.fdopen(temp_fd, "wb") as fh:
            for row in rows:
                fh.write(
                    json.dumps(
                        row,
                        ensure_ascii=False,
                        sort_keys=True,
                        separators=(",", ":"),
                    ).encode("utf-8")
                    + b"\n"
                )
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(temp_path, path)
        temp_path = None
        directory_fd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    except Exception:
        try:
            os.close(temp_fd)
        except OSError:
            pass
        raise
    finally:
        if temp_path is not None:
            try:
                os.unlink(temp_path)
            except FileNotFoundError:
                pass


class PersistentGoalValidationReceiptRegistry:
    """Schema-v2 owner ledger with append writes and exact compensation."""

    def __init__(
        self,
        path: str | Path,
        *,
        proof_ledger: GoalProofLedger | None = None,
        legacy_read_only: bool = False,
    ) -> None:
        self._path = Path(path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._lock_path = self._path.with_name(f".{self._path.name}.lock")
        self._lock = threading.RLock()
        self._proof_projection = (
            GoalProofRecordProjection(proof_ledger)
            if proof_ledger is not None
            else None
        )
        self._legacy_read_only = bool(legacy_read_only)
        self._proof_head_types: dict[tuple[str, str], str] = {}
        self._records: dict[tuple[str, str], GoalValidationReceipt] = {}
        self._legacy_quarantined_count = 0
        self._disk_signature: tuple[int, int, int, int, int] | None = None
        self._load_existing()
        self._disk_signature = self._disk_signature_unlocked()
        self._overlay_canonical_unlocked()

    @property
    def path(self) -> Path:
        return self._path

    @property
    def legacy_quarantined_count(self) -> int:
        return self._legacy_quarantined_count

    @staticmethod
    def _owner(value: Any) -> str:
        owner = str(value or "").strip()
        if not owner:
            raise ValueError("GOAL validation receipt owner_user_id is required")
        return owner

    @staticmethod
    def _event(record: GoalValidationReceipt) -> dict[str, Any]:
        return {
            "schema_version": 2,
            "event_type": "goal_validation_receipt_recorded",
            "owner_user_id": record.owner_user_id,
            "validation_receipt": asdict(record),
        }

    def _load_existing(self) -> None:
        if not self._path.exists():
            return
        with self._path.open("r", encoding="utf-8") as fh:
            for line_no, line in enumerate(fh, start=1):
                if not line.strip():
                    continue
                try:
                    row = json.loads(line)
                    if row.get("schema_version") != 2:
                        self._legacy_quarantined_count += 1
                        continue
                    self._apply_row(row, persist=False)
                except Exception as exc:  # noqa: BLE001
                    raise ValueError(
                        f"invalid persisted GOAL validation receipt at {self._path}:{line_no}"
                    ) from exc

    def _refresh_from_disk_unlocked(self) -> None:
        self._records = {}
        self._legacy_quarantined_count = 0
        self._load_existing()
        self._disk_signature = self._disk_signature_unlocked()

    def _overlay_canonical_unlocked(self) -> None:
        if self._proof_projection is None:
            self._proof_head_types = {}
            return
        canonical_by_type, self._proof_head_types = (
            self._proof_projection.decode_many_with_index(
                GOAL_VALIDATION_RECEIPT_PROOF_CODEC
            )
        )
        for record in canonical_by_type[LOGICAL_TYPE_VALIDATION_RECEIPT]:
            key = (self._owner(record.owner_user_id), record.validation_ref)
            existing = self._records.get(key)
            if existing is not None and existing != record:
                raise ValueError(
                    "canonical GOAL validation receipt collides with legacy "
                    f"record for owner/ref {key[0]!r}/{key[1]!r}"
                )
            self._apply_row(self._event(record), persist=False)

    def _require_legacy_write_allowed(self) -> None:
        if self._legacy_read_only:
            raise RuntimeError(
                f"{ATOMIC_PROOF_BUNDLE_REQUIRED}: "
                "GOAL validation receipt legacy JSONL is read-only"
            )

    def _disk_signature_unlocked(self) -> tuple[int, int, int, int, int] | None:
        try:
            stat = self._path.stat()
        except FileNotFoundError:
            return None
        return (
            stat.st_dev,
            stat.st_ino,
            stat.st_size,
            stat.st_mtime_ns,
            stat.st_ctime_ns,
        )

    def _refresh_if_changed_unlocked(self) -> None:
        if self._disk_signature_unlocked() != self._disk_signature:
            self._refresh_from_disk_unlocked()

    @contextmanager
    def _receipt_file_lock(self):
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

    def refresh(self) -> None:
        """Reload the current durable receipt projection under its file lock."""

        with self._lock:
            with self._receipt_file_lock():
                self._refresh_from_disk_unlocked()
            self._overlay_canonical_unlocked()

    @contextmanager
    def _current_read_boundary(self):
        """Replay and read one linearized durable receipt projection."""

        with self._lock:
            with self._receipt_file_lock():
                if self._proof_projection is not None:
                    # Canonical heads can change while the compatibility JSONL
                    # remains byte-identical, so rebuild the legacy base before
                    # every live SQLite overlay.
                    self._refresh_from_disk_unlocked()
                else:
                    self._refresh_if_changed_unlocked()
            self._overlay_canonical_unlocked()
            yield

    def _append_event(self, row: dict[str, Any]) -> None:
        """Atomically append a logical row while holding a cross-process lock."""

        self._require_legacy_write_allowed()
        fd = os.open(self._lock_path, os.O_RDWR | os.O_CREAT, 0o600)
        held = None
        temp_path: str | None = None
        try:
            os.chmod(self._lock_path, 0o600)
            held = acquire_exclusive_fd(fd, timeout_seconds=30.0)
            incoming = row["validation_receipt"]
            existing_bytes = self._path.read_bytes() if self._path.exists() else b""
            for line_no, line in enumerate(existing_bytes.splitlines(), start=1):
                if not line.strip():
                    continue
                existing = json.loads(line)
                persisted = existing.get("validation_receipt")
                if (
                    existing.get("schema_version") == 2
                    and existing.get("owner_user_id") == row.get("owner_user_id")
                    and isinstance(persisted, dict)
                    and persisted.get("validation_ref") == incoming.get("validation_ref")
                ):
                    if existing.get("event_type") == row.get("event_type"):
                        try:
                            persisted_record = goal_validation_receipt_from_dict(
                                persisted
                            )
                            incoming_record = goal_validation_receipt_from_dict(incoming)
                        except (TypeError, ValueError):
                            pass
                        else:
                            if persisted_record == incoming_record:
                                return
                    raise ValueError(
                        "GOAL validation receipt identity collision at "
                        f"{self._path}:{line_no}"
                    )

            serialized = json.dumps(
                row,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8") + b"\n"
            prefix = existing_bytes
            if prefix and not prefix.endswith(b"\n"):
                prefix += b"\n"
            temp_fd, temp_path = tempfile.mkstemp(
                prefix=f".{self._path.name}.",
                suffix=".tmp",
                dir=self._path.parent,
            )
            try:
                os.fchmod(temp_fd, 0o600)
                with os.fdopen(temp_fd, "wb") as fh:
                    fh.write(prefix)
                    fh.write(serialized)
                    fh.flush()
                    os.fsync(fh.fileno())
                os.replace(temp_path, self._path)
                temp_path = None
                directory_fd = os.open(self._path.parent, os.O_RDONLY)
                try:
                    os.fsync(directory_fd)
                finally:
                    os.close(directory_fd)
            except Exception:
                try:
                    os.close(temp_fd)
                except OSError:
                    pass
                raise
        finally:
            if temp_path is not None:
                try:
                    os.unlink(temp_path)
                except FileNotFoundError:
                    pass
            if held is not None:
                held.release()
            os.close(fd)

    def _apply_row(
        self,
        row: dict[str, Any],
        *,
        persist: bool,
    ) -> GoalValidationReceipt:
        if row.get("schema_version") != 2:
            raise ValueError("GOAL validation receipts require schema_version=2")
        if row.get("event_type") != "goal_validation_receipt_recorded":
            raise ValueError("unknown GOAL validation receipt event_type")
        owner = self._owner(row.get("owner_user_id"))
        raw = row.get("validation_receipt")
        if not isinstance(raw, dict):
            raise ValueError("GOAL validation receipt event is missing validation_receipt")
        record = goal_validation_receipt_from_dict(raw)
        if record.owner_user_id != owner:
            raise ValueError("GOAL validation receipt owner envelope mismatch")
        decision = validate_goal_validation_receipt_shape(record)
        if not decision.accepted:
            raise ValueError(
                "; ".join(
                    f"{item.code}:{item.field}:{item.ref}"
                    for item in decision.violations
                )
            )
        key = (owner, record.validation_ref)
        with self._lock:
            existing = self._records.get(key)
            if existing is not None:
                if existing != record:
                    raise ValueError("GOAL validation receipt identity collision for owner")
                return existing
            if persist:
                self._append_event(row)
            self._records[key] = record
            return record

    def record_receipt(self, record: GoalValidationReceipt) -> GoalValidationReceipt:
        self._require_legacy_write_allowed()
        self._owner(record.owner_user_id)
        return self._apply_row(self._event(record), persist=True)

    def receipt(
        self,
        validation_ref: str,
        *,
        owner_user_id: str,
    ) -> GoalValidationReceipt:
        with self._current_read_boundary():
            return self._receipt_unlocked(
                validation_ref,
                owner_user_id=owner_user_id,
            )

    def _receipt_unlocked(
        self,
        validation_ref: str,
        *,
        owner_user_id: str,
    ) -> GoalValidationReceipt:
        owner = self._owner(owner_user_id)
        ref = str(validation_ref or "").strip()
        if self._proof_projection is not None:
            current_type = self._proof_head_types.get((owner, ref))
            if (
                current_type is not None
                and current_type != LOGICAL_TYPE_VALIDATION_RECEIPT
            ):
                raise GoalProofRecordProjectionError(
                    "canonical GOAL proof logical ref/type collision: "
                    f"{ref!r} is {current_type!r}, expected "
                    f"{LOGICAL_TYPE_VALIDATION_RECEIPT!r}"
                )
            if current_type == LOGICAL_TYPE_VALIDATION_RECEIPT:
                return self._records[(owner, ref)]
        return self._records[(owner, ref)]

    def receipts(self, *, owner_user_id: str) -> list[GoalValidationReceipt]:
        with self._current_read_boundary():
            return self._receipts_unlocked(owner_user_id=owner_user_id)

    def _receipts_unlocked(
        self,
        *,
        owner_user_id: str,
    ) -> list[GoalValidationReceipt]:
        owner = self._owner(owner_user_id)
        return [
            record
            for (record_owner, _validation_ref), record in self._records.items()
            if record_owner == owner
        ]

    def rollback_exact_receipt(
        self,
        record: GoalValidationReceipt,
        *,
        dependent_refs: tuple[str, ...],
    ) -> bool:
        """Remove one exact receipt after callers prove no live dependents remain.

        Receipt consumers live in other durable stores (notably compiler IR/pass,
        entrypoint coverage, and full-product aggregate records), so this registry
        cannot discover inbound references itself. ``dependent_refs`` is required
        to make that boundary explicit. Callers must inspect the current durable
        consumer stores and invoke this as the final compensation step; any
        reported dependency is a hard refusal.
        """

        self._require_legacy_write_allowed()
        owner = self._owner(record.owner_user_id)
        dependencies = tuple(str(ref or "").strip() for ref in dependent_refs)
        if any(not ref for ref in dependencies):
            raise ValueError(
                "GOAL validation receipt rollback dependent_refs must be non-empty refs"
            )
        if dependencies:
            raise ValueError(
                "GOAL validation receipt rollback refused because live records "
                "reference the receipt: "
                + ",".join(dependencies)
            )

        with self._lock:
            fd = os.open(self._lock_path, os.O_RDWR | os.O_CREAT, 0o600)
            held = None
            try:
                os.chmod(self._lock_path, 0o600)
                held = acquire_exclusive_fd(fd, timeout_seconds=30.0)
                self._refresh_from_disk_unlocked()

                key = (owner, record.validation_ref)
                persisted = self._records.get(key)
                if persisted is None:
                    foreign_matches = tuple(
                        candidate
                        for (_candidate_owner, candidate_ref), candidate in (
                            self._records.items()
                        )
                        if candidate_ref == record.validation_ref
                    )
                    if foreign_matches:
                        raise ValueError(
                            "GOAL validation receipt rollback owner identity mismatch"
                        )
                    return False
                if persisted != record:
                    raise ValueError(
                        "GOAL validation receipt rollback identity mismatch"
                    )

                expected = json.loads(
                    json.dumps(
                        self._event(record),
                        ensure_ascii=False,
                        sort_keys=True,
                        separators=(",", ":"),
                    )
                )
                rows: list[dict[str, Any]] = []
                if self._path.exists():
                    with self._path.open("r", encoding="utf-8") as fh:
                        rows = [json.loads(line) for line in fh if line.strip()]
                if sum(row == expected for row in rows) != 1:
                    raise ValueError(
                        "GOAL validation receipt rollback exact persisted event is "
                        "not unique"
                    )
                retained = tuple(row for row in rows if row != expected)
                _atomic_rewrite_receipt_rows(self._path, retained)
                self._refresh_from_disk_unlocked()
                return True
            finally:
                if held is not None:
                    held.release()
                os.close(fd)

    def validate_validation_ref(
        self,
        validation_ref: str,
        *,
        owner_user_id: str,
        subject_qro_refs: tuple[str, ...],
        graph_command_refs: tuple[str, ...],
    ) -> GoalValidationDecision:
        """Resolve and validate one ref against the exact current subject sets."""

        owner = self._owner(owner_user_id)
        ref = str(validation_ref or "").strip()
        violations: list[GoalValidationViolation] = []
        if self._proof_projection is not None:
            try:
                head = self._proof_projection.current_heads_for_refs(
                    owner=owner,
                    typed_refs=((LOGICAL_TYPE_VALIDATION_RECEIPT, ref),),
                )[0]
                record = decode_proof_record_head(
                    head,
                    codec=GOAL_VALIDATION_RECEIPT_PROOF_CODEC,
                )
            except (KeyError, GoalProofRecordProjectionError):
                return GoalValidationDecision(
                    False,
                    (
                        GoalValidationViolation(
                            "goal_validation_receipt_not_canonical_current",
                            "validation ref is not a current canonical proof head",
                            field="validation_ref",
                            ref=ref,
                        ),
                    ),
                )
        else:
            try:
                record = self.receipt(ref, owner_user_id=owner)
            except KeyError:
                return GoalValidationDecision(
                    False,
                    (
                        GoalValidationViolation(
                            "goal_validation_receipt_unknown",
                            "validation ref is not persisted for this owner",
                            field="validation_ref",
                            ref=ref,
                        ),
                    ),
                )

        if record.owner_user_id != owner:
            return GoalValidationDecision(
                False,
                (
                    GoalValidationViolation(
                        "goal_validation_receipt_owner_mismatch",
                        "validation ref is not canonical for this owner",
                        field="validation_ref",
                        ref=ref,
                    ),
                ),
            )
        violations.extend(validate_goal_validation_receipt_shape(record).violations)
        expected_qros = _refs(subject_qro_refs)
        expected_commands = _refs(graph_command_refs)
        if not _same_exact_ref_set(record.subject_qro_refs, expected_qros):
            violations.append(
                GoalValidationViolation(
                    "goal_validation_receipt_qro_set_mismatch",
                    "validation receipt must bind the exact entrypoint QRO set",
                    field="subject_qro_refs",
                    ref=ref,
                )
            )
        if not _same_exact_ref_set(record.graph_command_refs, expected_commands):
            violations.append(
                GoalValidationViolation(
                    "goal_validation_receipt_graph_set_mismatch",
                    "validation receipt must bind the exact entrypoint Research Graph command set",
                    field="graph_command_refs",
                    ref=ref,
                )
            )
        if str(record.outcome) != GoalValidationOutcome.PASSED.value:
            violations.append(
                GoalValidationViolation(
                    "goal_validation_receipt_not_passed",
                    "only a passed validation outcome can satisfy strict coverage",
                    field="outcome",
                    ref=ref,
                )
            )
        if record.residuals:
            violations.append(
                GoalValidationViolation(
                    "goal_validation_receipt_has_residuals",
                    "validation receipts with unresolved residuals cannot satisfy strict coverage",
                    field="residuals",
                    ref=ref,
                )
            )
        return GoalValidationDecision(not violations, tuple(violations))

    def is_canonical_current(
        self,
        record: GoalValidationReceipt,
        *,
        owner_user_id: str | None = None,
    ) -> bool:
        """Return whether ``record`` is the exact live SQLite proof head."""

        if self._proof_projection is None:
            return False
        if owner_user_id is not None and self._owner(
            owner_user_id
        ) != self._owner(record.owner_user_id):
            return False
        return self._proof_projection.is_exact_current(
            record,
            codec=GOAL_VALIDATION_RECEIPT_PROOF_CODEC,
        )


__all__ = [
    "GOAL_VALIDATION_RECEIPT_PROOF_CODEC",
    "GoalValidationDecision",
    "GoalValidationOutcome",
    "GoalValidationReceipt",
    "GoalValidationViolation",
    "PersistentGoalValidationReceiptRegistry",
    "goal_validation_receipt_from_dict",
    "goal_validation_receipt_identity",
    "validate_goal_validation_receipt_shape",
]
