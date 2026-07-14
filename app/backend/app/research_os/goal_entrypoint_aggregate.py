"""Durable current-head receipts for the six canonical GOAL entry sources."""

from __future__ import annotations

import json
import os
import threading
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from ..cross_process_lock import acquire_exclusive_fd
from ..lineage.ids import content_hash
from .goal_coverage import (
    GOAL_ENTRYPOINT_COVERAGE_PROOF_CODEC,
    GoalEntrypointCoverageRecord,
    PersistentGoalEntrypointCoverageRegistry,
    REQUIRED_ENTRY_SOURCES,
    REQUIRED_GOAL_SECTIONS,
    strict_current_entrypoint_records,
)
from .goal_proof_head_lock import acquire_goal_proof_head_lock
from .goal_proof_ledger import GoalProofLedger
from .goal_proof_records import (
    ATOMIC_PROOF_BUNDLE_REQUIRED,
    GoalProofRecordProjection,
    GoalProofRecordProjectionError,
    ProofRecordCodec,
    decode_proof_record_head,
)


LOGICAL_TYPE_ENTRYPOINT_AGGREGATE = "goal.entrypoint_aggregate"


def _entry_source(record: Any) -> str:
    value = getattr(record, "entry_source", "")
    return str(getattr(value, "value", value) or "")


@dataclass(frozen=True)
class GoalEntrypointAggregateRecord:
    aggregate_ref: str
    coverage_refs: tuple[str, ...]
    recorded_by: str
    aggregate_version: str = "goal_entrypoint_aggregate.v1"

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "coverage_refs",
            tuple(str(ref or "").strip() for ref in self.coverage_refs),
        )

    @property
    def canonical_aggregate_ref(self) -> str:
        return "goal_entrypoint_aggregate:" + content_hash(
            {
                "coverage_refs": self.coverage_refs,
                "recorded_by": self.recorded_by,
                "aggregate_version": self.aggregate_version,
            }
        )


def goal_entrypoint_aggregate_from_dict(data: dict[str, Any]) -> GoalEntrypointAggregateRecord:
    return GoalEntrypointAggregateRecord(
        aggregate_ref=str(data.get("aggregate_ref") or ""),
        coverage_refs=tuple(data.get("coverage_refs") or ()),
        recorded_by=str(data.get("recorded_by") or ""),
        aggregate_version=str(
            data.get("aggregate_version") or "goal_entrypoint_aggregate.v1"
        ),
    )


GOAL_ENTRYPOINT_AGGREGATE_PROOF_CODEC = ProofRecordCodec[
    GoalEntrypointAggregateRecord
](
    logical_type=LOGICAL_TYPE_ENTRYPOINT_AGGREGATE,
    record_type=GoalEntrypointAggregateRecord,
    decode=goal_entrypoint_aggregate_from_dict,
    logical_ref=lambda record: record.aggregate_ref,
    owner=lambda record: record.recorded_by,
)


class PersistentGoalEntrypointAggregateRegistry:
    """Append-only owner receipt over the latest strict full-product lineage per source."""

    def __init__(
        self,
        path: str | Path,
        entrypoint_registry: PersistentGoalEntrypointCoverageRegistry,
        *,
        proof_ledger: GoalProofLedger | None = None,
        legacy_read_only: bool = False,
    ) -> None:
        self._path = Path(path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._lock_path = self._path.with_suffix(self._path.suffix + ".lock")
        self._entrypoint_registry = entrypoint_registry
        self._process_lock = threading.RLock()
        self._proof_projection = (
            GoalProofRecordProjection(proof_ledger)
            if proof_ledger is not None
            else None
        )
        self._legacy_read_only = bool(legacy_read_only)
        self._proof_head_types: dict[tuple[str, str], str] = {}
        self._records: dict[tuple[str, str], GoalEntrypointAggregateRecord] = {}
        self._legacy_quarantined_count = 0
        self._disk_signature: tuple[int, int, int, int, int] | None = None
        self._load_existing()
        self._overlay_canonical_unlocked()
        self._disk_signature = self._disk_signature_unlocked()

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
            raise ValueError("GOAL entrypoint aggregate owner is required")
        return owner

    def _current_coverages(self, *, owner: str) -> tuple[Any, ...]:
        if self._proof_projection is not None:
            snapshot = self._proof_projection.ledger.current(owner=owner)
            aggregate_heads = tuple(
                head
                for head in snapshot.heads
                if head.logical_type == LOGICAL_TYPE_ENTRYPOINT_AGGREGATE
            )
            if not aggregate_heads:
                raise ValueError(
                    "GOAL current entrypoint aggregate has no canonical terminal bundle"
                )
            terminal_head = max(
                aggregate_heads,
                key=lambda head: (head.declared_seq, head.logical_ref),
            )
            terminal = decode_proof_record_head(
                terminal_head,
                codec=GOAL_ENTRYPOINT_AGGREGATE_PROOF_CODEC,
            )
            if (
                len(terminal.coverage_refs) != len(REQUIRED_ENTRY_SOURCES)
                or len(set(terminal.coverage_refs))
                != len(REQUIRED_ENTRY_SOURCES)
                or set(terminal_head.depends_on) != set(terminal.coverage_refs)
            ):
                raise ValueError(
                    "GOAL current entrypoint aggregate terminal dependencies are invalid"
                )
            heads_by_ref = {head.logical_ref: head for head in snapshot.heads}
            bundle_coverage_refs = {
                head.logical_ref
                for head in snapshot.heads
                if head.bundle_id == terminal_head.bundle_id
                and head.logical_type
                == GOAL_ENTRYPOINT_COVERAGE_PROOF_CODEC.logical_type
            }
            if bundle_coverage_refs != set(terminal.coverage_refs):
                raise ValueError(
                    "GOAL current entrypoint aggregate does not bind exactly one "
                    "atomic coverage bundle"
                )
            coverages: list[GoalEntrypointCoverageRecord] = []
            for expected_source, coverage_ref in zip(
                REQUIRED_ENTRY_SOURCES,
                terminal.coverage_refs,
                strict=True,
            ):
                try:
                    coverage_head = heads_by_ref[coverage_ref]
                except KeyError:
                    raise ValueError(
                        "GOAL current entrypoint aggregate coverage head is missing: "
                        f"{coverage_ref}"
                    ) from None
                if (
                    coverage_head.logical_type
                    != GOAL_ENTRYPOINT_COVERAGE_PROOF_CODEC.logical_type
                    or coverage_head.bundle_id != terminal_head.bundle_id
                ):
                    raise ValueError(
                        "GOAL current entrypoint aggregate crosses proof bundles"
                    )
                coverage = decode_proof_record_head(
                    coverage_head,
                    codec=GOAL_ENTRYPOINT_COVERAGE_PROOF_CODEC,
                )
                if _entry_source(coverage) != expected_source:
                    raise ValueError(
                        "GOAL current entrypoint aggregate source order is invalid"
                    )
                if (
                    not bool(coverage.claims_full_product_entrypoint)
                    or set(coverage.goal_sections) != set(REQUIRED_GOAL_SECTIONS)
                ):
                    raise ValueError(
                        "GOAL current entrypoint aggregate coverage is not terminal"
                    )
                decision = self._entrypoint_registry.validate_real_backing(coverage)
                if not decision.accepted:
                    raise ValueError(
                        "GOAL current entrypoint aggregate coverage lacks strict backing"
                    )
                coverages.append(coverage)
            if (
                self._proof_projection.ledger.current(owner=owner).head_digest
                != snapshot.head_digest
            ):
                raise ValueError(
                    "GOAL proof heads changed while reading the current entrypoint aggregate"
                )
            return tuple(coverages)

        latest: dict[str, Any] = {}
        for coverage in strict_current_entrypoint_records(
            self._entrypoint_registry,
            owner=owner,
        ):
            source = _entry_source(coverage)
            if source not in REQUIRED_ENTRY_SOURCES:
                continue
            if not bool(coverage.claims_full_product_entrypoint):
                continue
            if set(coverage.goal_sections) != set(REQUIRED_GOAL_SECTIONS):
                continue
            decision = self._entrypoint_registry.validate_real_backing(coverage)
            if not decision.accepted:
                continue
            latest[source] = coverage
        missing = [source for source in REQUIRED_ENTRY_SOURCES if source not in latest]
        if missing:
            raise ValueError(
                "GOAL current entrypoint aggregate is missing strict full-product sources: "
                + ",".join(missing)
            )
        return tuple(latest[source] for source in REQUIRED_ENTRY_SOURCES)

    def prepare_from_coverages(
        self,
        coverages: tuple[GoalEntrypointCoverageRecord, ...],
        *,
        owner_user_id: str,
    ) -> GoalEntrypointAggregateRecord:
        """Build the terminal record from six in-memory candidates, without writes."""

        owner = self._owner(owner_user_id)
        by_source: dict[str, GoalEntrypointCoverageRecord] = {}
        prepare_coverage = getattr(
            self._entrypoint_registry,
            "prepare_record_candidate",
            None,
        )
        if not callable(prepare_coverage):
            raise TypeError(
                "GOAL entrypoint registry lacks pure candidate preparation"
            )
        for coverage in tuple(coverages):
            if not isinstance(coverage, GoalEntrypointCoverageRecord):
                raise TypeError(
                    "GOAL entrypoint aggregate candidates must be coverage records"
                )
            prepared = prepare_coverage(coverage)
            source = _entry_source(prepared)
            if source not in REQUIRED_ENTRY_SOURCES:
                raise ValueError(
                    f"GOAL entrypoint aggregate source is not canonical: {source}"
                )
            if source in by_source:
                raise ValueError(
                    f"GOAL entrypoint aggregate duplicates source {source}"
                )
            if prepared.recorded_by != owner:
                raise ValueError("GOAL entrypoint aggregate coverage owner mismatch")
            if not bool(prepared.claims_full_product_entrypoint):
                raise ValueError(
                    "GOAL entrypoint aggregate requires terminal coverage candidates"
                )
            if (
                len(prepared.goal_sections) != len(REQUIRED_GOAL_SECTIONS)
                or set(prepared.goal_sections) != set(REQUIRED_GOAL_SECTIONS)
            ):
                raise ValueError(
                    "GOAL entrypoint aggregate coverage section set mismatch"
                )
            by_source[source] = prepared
        missing = [source for source in REQUIRED_ENTRY_SOURCES if source not in by_source]
        if missing or len(by_source) != len(REQUIRED_ENTRY_SOURCES):
            raise ValueError(
                "GOAL entrypoint aggregate requires exactly six canonical sources: "
                + ",".join(missing)
            )
        provisional = GoalEntrypointAggregateRecord(
            aggregate_ref="",
            coverage_refs=tuple(
                by_source[source].coverage_ref for source in REQUIRED_ENTRY_SOURCES
            ),
            recorded_by=owner,
        )
        record = GoalEntrypointAggregateRecord(
            **{
                **asdict(provisional),
                "aggregate_ref": provisional.canonical_aggregate_ref,
            }
        )
        violations = self._shape_violations(record, owner_user_id=owner)
        if violations:
            raise ValueError(";".join(violations))
        return record

    def build_current(self, *, owner_user_id: str) -> GoalEntrypointAggregateRecord:
        owner = self._owner(owner_user_id)
        coverages = self._current_coverages(owner=owner)
        return self.prepare_from_coverages(
            tuple(coverages),
            owner_user_id=owner,
        )

    def validate_current(
        self,
        record: GoalEntrypointAggregateRecord,
        *,
        owner_user_id: str,
    ) -> tuple[str, ...]:
        violations = list(self._shape_violations(record, owner_user_id=owner_user_id))
        owner = self._owner(owner_user_id)
        try:
            current = self.build_current(owner_user_id=owner)
        except ValueError:
            violations.append("goal_entrypoint_aggregate_current_heads_unavailable")
        else:
            if record.coverage_refs != current.coverage_refs:
                violations.append("goal_entrypoint_aggregate_not_current")
        if self._proof_projection is not None and not self.is_canonical_current(
            record,
            owner_user_id=owner,
        ):
            violations.append("goal_entrypoint_aggregate_not_canonical_current")
        return tuple(violations)

    def _shape_violations(
        self,
        record: GoalEntrypointAggregateRecord,
        *,
        owner_user_id: str,
    ) -> tuple[str, ...]:
        violations: list[str] = []
        owner = self._owner(owner_user_id)
        if record.recorded_by != owner:
            violations.append("goal_entrypoint_aggregate_owner_mismatch")
        if record.aggregate_version != "goal_entrypoint_aggregate.v1":
            violations.append("goal_entrypoint_aggregate_version_unsupported")
        if record.aggregate_ref != record.canonical_aggregate_ref:
            violations.append("goal_entrypoint_aggregate_identity_mismatch")
        if len(record.coverage_refs) != len(REQUIRED_ENTRY_SOURCES):
            violations.append("goal_entrypoint_aggregate_cardinality_mismatch")
        if len(set(record.coverage_refs)) != len(record.coverage_refs):
            violations.append("goal_entrypoint_aggregate_duplicate_coverage")
        return tuple(violations)

    def _apply_row(
        self,
        row: dict[str, Any],
        *,
        persist: bool,
    ) -> GoalEntrypointAggregateRecord:
        if row.get("schema_version") != 2:
            raise ValueError("GOAL entrypoint aggregates require schema_version=2")
        if row.get("event_type") != "goal_entrypoint_aggregate_recorded":
            raise ValueError("unknown GOAL entrypoint aggregate event_type")
        owner = self._owner(row.get("owner_user_id"))
        raw = row.get("aggregate")
        if not isinstance(raw, dict):
            raise ValueError("GOAL entrypoint aggregate event is missing aggregate")
        record = goal_entrypoint_aggregate_from_dict(raw)
        violations = (
            self.validate_current(record, owner_user_id=owner)
            if persist
            else self._shape_violations(record, owner_user_id=owner)
        )
        if violations:
            raise ValueError(";".join(violations))
        key = (owner, record.aggregate_ref)
        existing = self._records.get(key)
        if existing is not None:
            if existing != record:
                raise ValueError("GOAL entrypoint aggregate identity collision")
            return existing
        if persist:
            self._append(row)
        self._records[key] = record
        return record

    def _append(self, row: dict[str, Any]) -> None:
        self._require_legacy_write_allowed()
        fd = os.open(self._lock_path, os.O_RDWR | os.O_CREAT, 0o600)
        held = None
        try:
            os.chmod(self._lock_path, 0o600)
            held = acquire_exclusive_fd(fd, timeout_seconds=30.0)
            incoming = row["aggregate"]
            if self._path.exists():
                for line_no, line in enumerate(
                    self._path.read_text(encoding="utf-8").splitlines(),
                    start=1,
                ):
                    if not line.strip():
                        continue
                    existing = json.loads(line)
                    existing_record = existing.get("aggregate")
                    if (
                        existing.get("schema_version") == 2
                        and existing.get("owner_user_id") == row.get("owner_user_id")
                        and isinstance(existing_record, dict)
                        and existing_record.get("aggregate_ref")
                        == incoming.get("aggregate_ref")
                    ):
                        if existing == row:
                            return
                        raise ValueError(
                            f"GOAL entrypoint aggregate identity collision at {self._path}:{line_no}"
                        )
            with self._path.open("a", encoding="utf-8") as fh:
                fh.write(
                    json.dumps(
                        row,
                        ensure_ascii=False,
                        sort_keys=True,
                        separators=(",", ":"),
                    )
                    + "\n"
                )
                fh.flush()
                os.fsync(fh.fileno())
        finally:
            if held is not None:
                held.release()
            os.close(fd)

    def _load_existing(self) -> None:
        if not self._path.exists():
            return
        for line_no, line in enumerate(
            self._path.read_text(encoding="utf-8").splitlines(),
            start=1,
        ):
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
                    f"invalid persisted GOAL entrypoint aggregate at {self._path}:{line_no}"
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
                GOAL_ENTRYPOINT_AGGREGATE_PROOF_CODEC
            )
        )
        for record in canonical_by_type[LOGICAL_TYPE_ENTRYPOINT_AGGREGATE]:
            owner = self._owner(record.recorded_by)
            key = (owner, record.aggregate_ref)
            existing = self._records.get(key)
            if existing is not None and existing != record:
                raise ValueError(
                    "canonical GOAL entrypoint aggregate collides with legacy "
                    f"record for owner/ref {owner!r}/{record.aggregate_ref!r}"
                )
            self._apply_row(
                {
                    "schema_version": 2,
                    "event_type": "goal_entrypoint_aggregate_recorded",
                    "owner_user_id": owner,
                    "aggregate": asdict(record),
                },
                persist=False,
            )

    def _require_legacy_write_allowed(self) -> None:
        if self._legacy_read_only:
            raise RuntimeError(
                f"{ATOMIC_PROOF_BUNDLE_REQUIRED}: "
                "GOAL entrypoint aggregate legacy JSONL is read-only"
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
    def _aggregate_file_lock(self):
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
        """Reload terminal aggregate rows under their cross-process file lock."""

        with self._process_lock:
            with self._aggregate_file_lock():
                self._refresh_from_disk_unlocked()
            self._overlay_canonical_unlocked()

    @contextmanager
    def _current_read_boundary(self):
        """Replay and read one linearized durable aggregate projection."""

        with acquire_goal_proof_head_lock(self._entrypoint_registry.path):
            with self._process_lock:
                with self._aggregate_file_lock():
                    if self._proof_projection is None:
                        self._refresh_if_changed_unlocked()
                    else:
                        self._refresh_from_disk_unlocked()
                        self._overlay_canonical_unlocked()
                    yield

    def record_current(self, *, owner_user_id: str) -> GoalEntrypointAggregateRecord:
        self._require_legacy_write_allowed()
        owner = self._owner(owner_user_id)
        with acquire_goal_proof_head_lock(self._entrypoint_registry.path):
            refresh_entrypoints = getattr(self._entrypoint_registry, "refresh", None)
            if callable(refresh_entrypoints):
                refresh_entrypoints()
            with self._process_lock:
                self._refresh_from_disk_unlocked()
                record = self.build_current(owner_user_id=owner)
                return self._apply_row(
                    {
                        "schema_version": 2,
                        "event_type": "goal_entrypoint_aggregate_recorded",
                        "owner_user_id": owner,
                        "aggregate": asdict(record),
                    },
                    persist=True,
                )

    def aggregate(
        self,
        aggregate_ref: str,
        *,
        owner_user_id: str,
    ) -> GoalEntrypointAggregateRecord:
        with self._current_read_boundary():
            return self._aggregate_unlocked(
                aggregate_ref,
                owner_user_id=owner_user_id,
            )

    def _aggregate_unlocked(
        self,
        aggregate_ref: str,
        *,
        owner_user_id: str,
    ) -> GoalEntrypointAggregateRecord:
        owner = self._owner(owner_user_id)
        ref = str(aggregate_ref or "")
        if self._proof_projection is not None:
            current_type = self._proof_head_types.get((owner, ref))
            if (
                current_type is not None
                and current_type != LOGICAL_TYPE_ENTRYPOINT_AGGREGATE
            ):
                raise GoalProofRecordProjectionError(
                    "canonical GOAL proof logical ref/type collision: "
                    f"{ref!r} is {current_type!r}, expected "
                    f"{LOGICAL_TYPE_ENTRYPOINT_AGGREGATE!r}"
                )
        return self._records[(owner, ref)]

    def records(self, *, owner_user_id: str) -> list[GoalEntrypointAggregateRecord]:
        with self._current_read_boundary():
            return self._records_unlocked(owner_user_id=owner_user_id)

    def _records_unlocked(
        self,
        *,
        owner_user_id: str,
    ) -> list[GoalEntrypointAggregateRecord]:
        owner = self._owner(owner_user_id)
        return [
            record
            for (record_owner, _), record in self._records.items()
            if record_owner == owner
        ]

    def is_canonical_current(
        self,
        record: GoalEntrypointAggregateRecord,
        *,
        owner_user_id: str | None = None,
    ) -> bool:
        """Return whether ``record`` is the exact live SQLite proof head."""

        if self._proof_projection is None:
            return False
        if owner_user_id is not None and self._owner(
            owner_user_id
        ) != self._owner(record.recorded_by):
            return False
        return self._proof_projection.is_exact_current(
            record,
            codec=GOAL_ENTRYPOINT_AGGREGATE_PROOF_CODEC,
        )


__all__ = [
    "GOAL_ENTRYPOINT_AGGREGATE_PROOF_CODEC",
    "GoalEntrypointAggregateRecord",
    "LOGICAL_TYPE_ENTRYPOINT_AGGREGATE",
    "PersistentGoalEntrypointAggregateRegistry",
    "goal_entrypoint_aggregate_from_dict",
]
