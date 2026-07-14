"""Owner-scoped semantic proof ledger for GOAL §0-§17.

The section coverage manifest is an index, not proof.  This module stores the
content-bound producer -> store -> consumer -> gate -> test evidence that a
section adapter has resolved against canonical backends.  Missing adapters and
unresolved entrypoint lineage fail closed.
"""

from __future__ import annotations

import json
import os
import threading
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Callable, Protocol

from ..cross_process_lock import acquire_exclusive_fd
from ..lineage.ids import content_hash
from .goal_coverage import (
    GoalEntrypointCoverageRecord,
    PersistentGoalEntrypointCoverageRegistry,
    REQUIRED_GOAL_SECTIONS,
    strict_current_entrypoint_lookup,
)
from .goal_proof_head_lock import acquire_goal_proof_head_lock
from .ref_resolution import is_placeholder_ref


def _tuple(value: Any) -> tuple[str, ...]:
    if value is None:
        return ()
    values = value if isinstance(value, (tuple, list)) else (value,)
    return tuple(str(item or "").strip() for item in values if str(item or "").strip())


@dataclass(frozen=True)
class GoalSemanticViolation:
    code: str
    message: str
    field: str = ""
    ref: str = ""


@dataclass(frozen=True)
class GoalSemanticDecision:
    accepted: bool
    violations: tuple[GoalSemanticViolation, ...]


@dataclass(frozen=True)
class GoalSectionSemanticProofRecord:
    proof_ref: str
    section: str
    subject_ref: str
    producer_refs: tuple[str, ...]
    store_refs: tuple[str, ...]
    consumer_refs: tuple[str, ...]
    gate_verdict_refs: tuple[str, ...]
    test_refs: tuple[str, ...]
    entrypoint_coverage_refs: tuple[str, ...]
    recorded_by: str
    claims_section_complete: bool = False
    unverified_residuals: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        for field_name in (
            "producer_refs",
            "store_refs",
            "consumer_refs",
            "gate_verdict_refs",
            "test_refs",
            "entrypoint_coverage_refs",
            "unverified_residuals",
        ):
            object.__setattr__(self, field_name, _tuple(getattr(self, field_name)))


def goal_section_semantic_proof_identity(
    *,
    section: str,
    subject_ref: str,
    producer_refs: tuple[str, ...],
    store_refs: tuple[str, ...],
    consumer_refs: tuple[str, ...],
    gate_verdict_refs: tuple[str, ...],
    test_refs: tuple[str, ...],
    entrypoint_coverage_refs: tuple[str, ...],
    recorded_by: str,
    claims_section_complete: bool,
    unverified_residuals: tuple[str, ...],
) -> str:
    return "goal_section_semantic_proof:" + content_hash(
        {
            "section": str(section or ""),
            "subject_ref": str(subject_ref or ""),
            "producer_refs": tuple(producer_refs),
            "store_refs": tuple(store_refs),
            "consumer_refs": tuple(consumer_refs),
            "gate_verdict_refs": tuple(gate_verdict_refs),
            "test_refs": tuple(test_refs),
            "entrypoint_coverage_refs": tuple(entrypoint_coverage_refs),
            "recorded_by": str(recorded_by or ""),
            "claims_section_complete": bool(claims_section_complete),
            "unverified_residuals": tuple(unverified_residuals),
        }
    )


def goal_section_semantic_proof_from_dict(data: dict[str, Any]) -> GoalSectionSemanticProofRecord:
    return GoalSectionSemanticProofRecord(
        proof_ref=str(data.get("proof_ref") or ""),
        section=str(data.get("section") or ""),
        subject_ref=str(data.get("subject_ref") or ""),
        producer_refs=_tuple(data.get("producer_refs")),
        store_refs=_tuple(data.get("store_refs")),
        consumer_refs=_tuple(data.get("consumer_refs")),
        gate_verdict_refs=_tuple(data.get("gate_verdict_refs")),
        test_refs=_tuple(data.get("test_refs")),
        entrypoint_coverage_refs=_tuple(data.get("entrypoint_coverage_refs")),
        recorded_by=str(data.get("recorded_by") or ""),
        claims_section_complete=bool(data.get("claims_section_complete", False)),
        unverified_residuals=_tuple(data.get("unverified_residuals")),
    )


def validate_goal_section_semantic_proof(
    record: GoalSectionSemanticProofRecord,
) -> GoalSemanticDecision:
    violations: list[GoalSemanticViolation] = []
    if record.section not in REQUIRED_GOAL_SECTIONS:
        violations.append(
            GoalSemanticViolation(
                "goal_semantic_unknown_section",
                "semantic proof section must be one of §0 through §17",
                field="section",
                ref=record.section,
            )
        )
    for field_name in (
        "proof_ref",
        "subject_ref",
        "recorded_by",
        "producer_refs",
        "store_refs",
        "consumer_refs",
        "gate_verdict_refs",
        "test_refs",
        "entrypoint_coverage_refs",
    ):
        if not getattr(record, field_name):
            violations.append(
                GoalSemanticViolation(
                    "goal_semantic_required_field_missing",
                    "semantic proof requires producer, store, consumer, gate, test, entrypoint, subject, and owner fields",
                    field=field_name,
                    ref=record.proof_ref,
                )
            )
    for field_name in (
        "subject_ref",
        "producer_refs",
        "store_refs",
        "consumer_refs",
        "gate_verdict_refs",
        "test_refs",
        "entrypoint_coverage_refs",
        "unverified_residuals",
    ):
        values = _tuple(getattr(record, field_name))
        for ref in values:
            if is_placeholder_ref(ref):
                violations.append(
                    GoalSemanticViolation(
                        "goal_semantic_placeholder_ref",
                        "semantic proof cannot contain synthetic, fixture, placeholder, or goal-closure refs",
                        field=field_name,
                        ref=ref,
                    )
                )
    expected_ref = goal_section_semantic_proof_identity(
        section=record.section,
        subject_ref=record.subject_ref,
        producer_refs=record.producer_refs,
        store_refs=record.store_refs,
        consumer_refs=record.consumer_refs,
        gate_verdict_refs=record.gate_verdict_refs,
        test_refs=record.test_refs,
        entrypoint_coverage_refs=record.entrypoint_coverage_refs,
        recorded_by=record.recorded_by,
        claims_section_complete=record.claims_section_complete,
        unverified_residuals=record.unverified_residuals,
    )
    if record.proof_ref and record.proof_ref != expected_ref:
        violations.append(
            GoalSemanticViolation(
                "goal_semantic_identity_mismatch",
                "proof_ref must content-bind the complete semantic proof",
                field="proof_ref",
                ref=record.proof_ref,
            )
        )
    if record.claims_section_complete and record.unverified_residuals:
        violations.append(
            GoalSemanticViolation(
                "goal_semantic_complete_with_residuals",
                "a complete section claim cannot retain unverified residuals",
                field="unverified_residuals",
                ref=record.proof_ref,
            )
        )
    return GoalSemanticDecision(not violations, tuple(violations))


class GoalSectionSemanticAdapter(Protocol):
    """Read-only section adapter; it must resolve every claimed semantic ref."""

    def validate(
        self,
        record: GoalSectionSemanticProofRecord,
        *,
        owner: str,
    ) -> GoalSemanticDecision: ...


SemanticAdapter = GoalSectionSemanticAdapter | Callable[..., GoalSemanticDecision]


class GoalSemanticCommitUncertain(ValueError):
    """A semantic proof append completed before backing drift was detected."""


class PersistentGoalSectionSemanticProofRegistry:
    """Append-only owner-scoped semantic proof ledger.

    A proof is accepted only when the owner-scoped entrypoint records resolve
    and a registered section adapter validates the real producer/store/
    consumer/gate chain.  Registering no adapter is deliberately a hard red.
    """

    def __init__(
        self,
        path: str | Path,
        entrypoint_registry: PersistentGoalEntrypointCoverageRegistry,
        *,
        adapters: dict[str, SemanticAdapter] | None = None,
    ) -> None:
        self._path = Path(path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._lock_path = self._path.with_suffix(self._path.suffix + ".lock")
        self._entrypoint_registry = entrypoint_registry
        self._process_lock = threading.RLock()
        self._adapters = dict(adapters or {})
        self._records: dict[tuple[str, str], GoalSectionSemanticProofRecord] = {}
        self._legacy_quarantined_count = 0
        self._disk_signature: tuple[int, int, int, int, int] | None = None
        self._load_existing()
        self._disk_signature = self._disk_signature_unlocked()

    @property
    def path(self) -> Path:
        return self._path

    @staticmethod
    def _owner(owner: str) -> str:
        normalized = str(owner or "").strip()
        if not normalized:
            raise ValueError("GOAL semantic proof owner is required")
        return normalized

    def register_adapter(self, section: str, adapter: SemanticAdapter) -> None:
        section = str(section or "")
        if section not in REQUIRED_GOAL_SECTIONS:
            raise ValueError("GOAL semantic adapter section must be §0 through §17")
        if section in self._adapters:
            raise ValueError(f"GOAL semantic adapter already registered for {section}")
        self._adapters[section] = adapter

    @property
    def registered_sections(self) -> tuple[str, ...]:
        return tuple(section for section in REQUIRED_GOAL_SECTIONS if section in self._adapters)

    def _entrypoint_violations(
        self,
        record: GoalSectionSemanticProofRecord,
        *,
        owner: str,
    ) -> tuple[GoalSemanticViolation, ...]:
        violations: list[GoalSemanticViolation] = []
        section_bound_count = 0
        coverage_for_ref = strict_current_entrypoint_lookup(
            self._entrypoint_registry,
            owner=owner,
        )
        for coverage_ref in record.entrypoint_coverage_refs:
            try:
                coverage: GoalEntrypointCoverageRecord = coverage_for_ref(coverage_ref)
            except KeyError:
                violations.append(
                    GoalSemanticViolation(
                        "goal_semantic_entrypoint_unknown",
                        "semantic proof entrypoint ref is not persisted for this owner",
                        field="entrypoint_coverage_refs",
                        ref=coverage_ref,
                    )
                )
                continue
            if bool(coverage.claims_full_product_entrypoint) or set(
                coverage.goal_sections
            ) == set(REQUIRED_GOAL_SECTIONS):
                violations.append(
                    GoalSemanticViolation(
                        "goal_semantic_terminal_entrypoint_forbidden",
                        "semantic section proofs must depend on non-terminal entrypoint lineage; terminal full-product coverage is a downstream attestation",
                        field="entrypoint_coverage_refs",
                        ref=coverage_ref,
                    )
                )
            decision = self._entrypoint_registry.validate_real_backing(coverage)
            if not decision.accepted:
                violations.append(
                    GoalSemanticViolation(
                        "goal_semantic_entrypoint_not_real_backed",
                        "semantic proof requires strict real-backed entrypoint lineage",
                        field="entrypoint_coverage_refs",
                        ref=coverage_ref,
                    )
                )
            if record.section in set(coverage.goal_sections):
                section_bound_count += 1
        if section_bound_count == 0:
            violations.append(
                GoalSemanticViolation(
                    "goal_semantic_primary_entrypoint_missing",
                    "semantic proof requires at least one real entrypoint lineage owned by the claimed section; cross-section supporting lineages remain adapter-scoped",
                    field="entrypoint_coverage_refs",
                    ref=record.section,
                )
            )
        return tuple(violations)

    def validate_real_backing(
        self,
        record: GoalSectionSemanticProofRecord,
        *,
        owner: str | None = None,
    ) -> GoalSemanticDecision:
        normalized_owner = self._owner(owner or record.recorded_by)
        violations = list(validate_goal_section_semantic_proof(record).violations)
        if record.recorded_by != normalized_owner:
            violations.append(
                GoalSemanticViolation(
                    "goal_semantic_owner_mismatch",
                    "semantic proof owner envelope must match recorded_by",
                    field="recorded_by",
                    ref=record.proof_ref,
                )
            )
        violations.extend(self._entrypoint_violations(record, owner=normalized_owner))
        adapter = self._adapters.get(record.section)
        if adapter is None:
            violations.append(
                GoalSemanticViolation(
                    "goal_semantic_adapter_unavailable",
                    "section-specific producer/store/consumer/gate adapter is unavailable",
                    field="section",
                    ref=record.section,
                )
            )
        else:
            try:
                validator = getattr(adapter, "validate", adapter)
                adapter_decision = validator(record, owner=normalized_owner)
                if not isinstance(adapter_decision, GoalSemanticDecision):
                    raise TypeError("semantic adapter must return GoalSemanticDecision")
                violations.extend(adapter_decision.violations)
            except Exception as exc:  # noqa: BLE001 - semantic proof fails closed.
                violations.append(
                    GoalSemanticViolation(
                        "goal_semantic_adapter_failed",
                        f"section semantic adapter raised {type(exc).__name__}",
                        field="section",
                        ref=record.section,
                    )
                )
        return GoalSemanticDecision(not violations, tuple(violations))

    def _load_existing(self) -> None:
        if not self._path.exists():
            return
        with self._path.open("r", encoding="utf-8") as fh:
            for line_no, line in enumerate(fh, start=1):
                if not line.strip():
                    continue
                try:
                    row = json.loads(line)
                    if row.get("schema_version") == 1:
                        self._legacy_quarantined_count += 1
                        continue
                    self._apply_row(row, persist=False)
                except Exception as exc:  # noqa: BLE001 - corrupt proof history blocks startup.
                    raise ValueError(
                        f"invalid persisted GOAL semantic proof row at {self._path}:{line_no}"
                    ) from exc

    def _refresh_from_disk_unlocked(self) -> None:
        self._records = {}
        self._legacy_quarantined_count = 0
        self._load_existing()
        self._disk_signature = self._disk_signature_unlocked()

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
    def _semantic_file_lock(self):
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
        """Reload semantic proof heads under their cross-process file lock."""

        with self._process_lock:
            with self._semantic_file_lock():
                self._refresh_from_disk_unlocked()

    @contextmanager
    def _current_read_boundary(self):
        """Replay and read one linearized durable semantic projection."""

        with acquire_goal_proof_head_lock(self._entrypoint_registry.path):
            with self._process_lock:
                with self._semantic_file_lock():
                    self._refresh_if_changed_unlocked()
                    yield

    def _append_event(
        self,
        row: dict[str, Any],
        *,
        precommit_assertion: Callable[[], None],
    ) -> None:
        # ``record_proof`` already holds the shared proof-head lock and the
        # process-local RLock.  Run backing validation before taking the
        # non-reentrant semantic file lock because section adapters may read
        # ``records()`` to resolve the current semantic heads.  The shared
        # proof-head lock remains the cross-registry linearization boundary.
        precommit_assertion()
        fd = os.open(self._lock_path, os.O_RDWR | os.O_CREAT, 0o600)
        held = None
        try:
            os.chmod(self._lock_path, 0o600)
            held = acquire_exclusive_fd(fd, timeout_seconds=30.0)
            incoming = row["semantic_proof"]
            incoming_ref = str(incoming["proof_ref"])
            if self._path.exists():
                with self._path.open("r", encoding="utf-8") as existing_fh:
                    for line_no, line in enumerate(existing_fh, start=1):
                        if not line.strip():
                            continue
                        existing = json.loads(line)
                        existing_record = existing.get("semantic_proof")
                        if (
                            existing.get("schema_version") == 2
                            and existing.get("owner_user_id") == row.get("owner_user_id")
                            and isinstance(existing_record, dict)
                            and str(existing_record.get("proof_ref") or "") == incoming_ref
                        ):
                            if existing == row:
                                return
                            raise ValueError(
                                f"GOAL semantic proof identity collision at {self._path}:{line_no}"
                            )
            with self._path.open("a", encoding="utf-8") as fh:
                fh.write(
                    json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
                    + "\n"
                )
                fh.flush()
                os.fsync(fh.fileno())
        finally:
            if held is not None:
                held.release()
            os.close(fd)

    def _apply_row(
        self,
        row: dict[str, Any],
        *,
        persist: bool,
    ) -> GoalSectionSemanticProofRecord:
        if row.get("schema_version") != 2:
            raise ValueError("unsupported GOAL semantic proof schema_version")
        if row.get("event_type") != "goal_section_semantic_proof_recorded":
            raise ValueError("unknown GOAL semantic proof event_type")
        raw = row.get("semantic_proof")
        if not isinstance(raw, dict):
            raise ValueError("GOAL semantic proof event missing semantic_proof")
        record = goal_section_semantic_proof_from_dict(raw)
        owner = self._owner(str(row.get("owner_user_id") or ""))
        if record.recorded_by != owner:
            raise ValueError("GOAL semantic proof owner envelope mismatch")
        decision = (
            self.validate_real_backing(record, owner=owner)
            if persist
            else validate_goal_section_semantic_proof(record)
        )
        if not decision.accepted:
            raise ValueError(
                "; ".join(f"{item.code}:{item.field}:{item.ref}" for item in decision.violations)
            )
        key = (owner, record.proof_ref)
        existing = self._records.get(key)
        if existing is not None:
            if existing != record:
                raise ValueError("GOAL semantic proof identity collision for owner")
            return existing
        if persist:
            def assert_precommit() -> None:
                final_decision = self.validate_real_backing(record, owner=owner)
                if final_decision != decision or not final_decision.accepted:
                    raise ValueError(
                        "GOAL semantic proof backing changed at the append boundary"
                    )

            self._append_event(
                row,
                precommit_assertion=assert_precommit,
            )
            post_append = self.validate_real_backing(record, owner=owner)
            if post_append != decision or not post_append.accepted:
                raise GoalSemanticCommitUncertain(
                    "GOAL semantic proof was appended but backing changed at the "
                    "post-append return boundary; non-atomic stale append is persisted"
                )
        self._records[key] = record
        return record

    def record_proof(
        self,
        record: GoalSectionSemanticProofRecord,
    ) -> GoalSectionSemanticProofRecord:
        owner = self._owner(record.recorded_by)
        with acquire_goal_proof_head_lock(self._entrypoint_registry.path):
            refresh_entrypoints = getattr(self._entrypoint_registry, "refresh", None)
            if callable(refresh_entrypoints):
                refresh_entrypoints()
            with self._process_lock:
                self._refresh_from_disk_unlocked()
                return self._apply_row(
                    {
                        "schema_version": 2,
                        "event_type": "goal_section_semantic_proof_recorded",
                        "owner_user_id": owner,
                        "semantic_proof": asdict(record),
                    },
                    persist=True,
                )

    def proof(
        self,
        proof_ref: str,
        *,
        owner: str,
    ) -> GoalSectionSemanticProofRecord:
        with self._current_read_boundary():
            return self._proof_unlocked(proof_ref, owner=owner)

    def _proof_unlocked(
        self,
        proof_ref: str,
        *,
        owner: str,
    ) -> GoalSectionSemanticProofRecord:
        return self._records[(self._owner(owner), str(proof_ref or ""))]

    def records(
        self,
        *,
        owner: str | None = None,
        section: str | None = None,
    ) -> list[GoalSectionSemanticProofRecord]:
        with self._current_read_boundary():
            return self._records_unlocked(owner=owner, section=section)

    def _records_unlocked(
        self,
        *,
        owner: str | None = None,
        section: str | None = None,
    ) -> list[GoalSectionSemanticProofRecord]:
        records = list(self._records.values())
        if owner is not None:
            normalized = self._owner(owner)
            records = [record for record in records if record.recorded_by == normalized]
        if section is not None:
            records = [record for record in records if record.section == str(section)]
        return records

    @property
    def legacy_quarantined_count(self) -> int:
        return self._legacy_quarantined_count


__all__ = [
    "GoalSemanticCommitUncertain",
    "GoalSectionSemanticAdapter",
    "GoalSectionSemanticProofRecord",
    "GoalSemanticDecision",
    "GoalSemanticViolation",
    "PersistentGoalSectionSemanticProofRegistry",
    "goal_section_semantic_proof_from_dict",
    "goal_section_semantic_proof_identity",
    "validate_goal_section_semantic_proof",
]
