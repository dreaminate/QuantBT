"""Durable current-head receipts for non-terminal GOAL entrypoint lineage.

This aggregate deliberately excludes full-product rows.  Section semantic
proofs can therefore depend on it without making the terminal §0-§17 proof
depend on itself.
"""

from __future__ import annotations

import json
import os
import threading
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from ..cross_process_lock import acquire_exclusive_fd
from ..lineage.ids import content_hash
from .goal_coverage import (
    GoalEntrypointCoverageRecord,
    PersistentGoalEntrypointCoverageRegistry,
    REQUIRED_ENTRY_SOURCES,
    REQUIRED_GOAL_SECTIONS,
)
from .goal_proof_head_lock import acquire_goal_proof_head_lock


CORE_GOAL_SECTIONS = ("§0", "§1", "§7", "§8")
LINEAGE_AGGREGATE_VERSION = "goal_entrypoint_lineage_aggregate.v1"


def _entry_source(record: Any) -> str:
    value = getattr(record, "entry_source", "")
    return str(getattr(value, "value", value) or "")


def _has_ordered_non_terminal_core_sections(
    goal_sections: tuple[str, ...],
) -> bool:
    """Accept expanded core lineage without admitting terminal coverage rows."""

    sections = tuple(goal_sections)
    if len(sections) != len(set(sections)):
        return False
    if set(sections) == set(REQUIRED_GOAL_SECTIONS):
        return False
    return tuple(
        section for section in sections if section in CORE_GOAL_SECTIONS
    ) == CORE_GOAL_SECTIONS


@dataclass(frozen=True)
class GoalEntrypointLineageAggregateRecord:
    """Owner-bound current heads for the six non-terminal core lineages."""

    aggregate_ref: str
    coverage_refs: tuple[str, ...]
    recorded_by: str
    aggregate_version: str = LINEAGE_AGGREGATE_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "coverage_refs",
            tuple(str(ref or "").strip() for ref in self.coverage_refs),
        )
        object.__setattr__(self, "recorded_by", str(self.recorded_by or "").strip())
        object.__setattr__(
            self,
            "aggregate_version",
            str(self.aggregate_version or "").strip(),
        )

    @property
    def canonical_aggregate_ref(self) -> str:
        return "goal_entrypoint_lineage_aggregate:" + content_hash(
            {
                "coverage_refs": self.coverage_refs,
                "recorded_by": self.recorded_by,
                "aggregate_version": self.aggregate_version,
            }
        )


@dataclass(frozen=True)
class GoalEntrypointLineageCurrentSnapshot:
    """One owner-scoped coverage snapshot and its derived aggregate."""

    aggregate: GoalEntrypointLineageAggregateRecord
    coverages: tuple[GoalEntrypointCoverageRecord, ...]


def goal_entrypoint_lineage_aggregate_from_dict(
    data: dict[str, Any],
) -> GoalEntrypointLineageAggregateRecord:
    return GoalEntrypointLineageAggregateRecord(
        aggregate_ref=str(data.get("aggregate_ref") or ""),
        coverage_refs=tuple(data.get("coverage_refs") or ()),
        recorded_by=str(data.get("recorded_by") or ""),
        aggregate_version=str(
            data.get("aggregate_version") or LINEAGE_AGGREGATE_VERSION
        ),
    )


class PersistentGoalEntrypointLineageAggregateRegistry:
    """Append-only current-head registry over strict non-full core lineages."""

    def __init__(
        self,
        path: str | Path,
        entrypoint_registry: PersistentGoalEntrypointCoverageRegistry,
    ) -> None:
        self._path = Path(path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._lock_path = self._path.with_suffix(self._path.suffix + ".lock")
        self._entrypoint_registry = entrypoint_registry
        self._process_lock = threading.RLock()
        self._records: dict[
            tuple[str, str], GoalEntrypointLineageAggregateRecord
        ] = {}
        self._legacy_quarantined_count = 0
        self._load_existing()

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
            raise ValueError("GOAL entrypoint lineage aggregate owner is required")
        return owner

    def _entrypoint_records_snapshot(
        self,
        *,
        owner: str,
    ) -> tuple[GoalEntrypointCoverageRecord, ...]:
        if bool(
            getattr(
                self._entrypoint_registry,
                "canonical_projection_available",
                False,
            )
        ):
            canonical_records = getattr(
                self._entrypoint_registry,
                "canonical_records",
                None,
            )
            if not callable(canonical_records):
                raise TypeError(
                    "GOAL entrypoint registry lacks canonical proof reads"
                )
            return tuple(canonical_records(owner=owner))
        return tuple(self._entrypoint_registry.records(owner=owner))

    def _current_coverages_from_records(
        self,
        *,
        owner: str,
        records: tuple[GoalEntrypointCoverageRecord, ...],
    ) -> tuple[GoalEntrypointCoverageRecord, ...]:
        if any(record.recorded_by != owner for record in records):
            raise ValueError(
                "GOAL entrypoint lineage snapshot cannot span owners"
            )
        latest: dict[str, GoalEntrypointCoverageRecord] = {}
        for coverage in records:
            source = _entry_source(coverage)
            if source not in REQUIRED_ENTRY_SOURCES:
                continue
            if bool(coverage.claims_full_product_entrypoint):
                continue
            if not _has_ordered_non_terminal_core_sections(
                tuple(coverage.goal_sections)
            ):
                continue
            decision = self._entrypoint_registry.validate_real_backing(coverage)
            if not decision.accepted:
                continue
            latest[source] = coverage
        missing = [source for source in REQUIRED_ENTRY_SOURCES if source not in latest]
        if missing:
            raise ValueError(
                "GOAL current entrypoint lineage aggregate is missing strict "
                "non-full core sources: " + ",".join(missing)
            )
        return tuple(latest[source] for source in REQUIRED_ENTRY_SOURCES)

    def current_coverages(
        self,
        *,
        owner_user_id: str,
    ) -> tuple[GoalEntrypointCoverageRecord, ...]:
        """Return latest strict non-full core coverage for every entry source."""

        owner = self._owner(owner_user_id)
        return self._current_coverages_from_records(
            owner=owner,
            records=self._entrypoint_records_snapshot(owner=owner),
        )

    def _current_snapshot_from_records(
        self,
        *,
        owner: str,
        records: tuple[GoalEntrypointCoverageRecord, ...],
    ) -> GoalEntrypointLineageCurrentSnapshot:
        coverages = self._current_coverages_from_records(
            owner=owner,
            records=records,
        )
        provisional = GoalEntrypointLineageAggregateRecord(
            aggregate_ref="",
            coverage_refs=tuple(
                coverage.coverage_ref for coverage in coverages
            ),
            recorded_by=owner,
        )
        aggregate = GoalEntrypointLineageAggregateRecord(
            **{
                **asdict(provisional),
                "aggregate_ref": provisional.canonical_aggregate_ref,
            }
        )
        return GoalEntrypointLineageCurrentSnapshot(
            aggregate=aggregate,
            coverages=coverages,
        )

    def current_snapshot(
        self,
        *,
        owner_user_id: str,
    ) -> GoalEntrypointLineageCurrentSnapshot:
        """Build an aggregate from one owner-scoped registry snapshot."""

        owner = self._owner(owner_user_id)
        return self._current_snapshot_from_records(
            owner=owner,
            records=self._entrypoint_records_snapshot(owner=owner),
        )

    def build_current(
        self,
        *,
        owner_user_id: str,
    ) -> GoalEntrypointLineageAggregateRecord:
        return self.current_snapshot(
            owner_user_id=owner_user_id
        ).aggregate

    def _shape_violations(
        self,
        record: GoalEntrypointLineageAggregateRecord,
        *,
        owner_user_id: str,
    ) -> tuple[str, ...]:
        owner = self._owner(owner_user_id)
        violations: list[str] = []
        if record.recorded_by != owner:
            violations.append("goal_entrypoint_lineage_aggregate_owner_mismatch")
        if record.aggregate_version != LINEAGE_AGGREGATE_VERSION:
            violations.append("goal_entrypoint_lineage_aggregate_version_unsupported")
        if record.aggregate_ref != record.canonical_aggregate_ref:
            violations.append("goal_entrypoint_lineage_aggregate_identity_mismatch")
        if len(record.coverage_refs) != len(REQUIRED_ENTRY_SOURCES):
            violations.append("goal_entrypoint_lineage_aggregate_cardinality_mismatch")
        if len(set(record.coverage_refs)) != len(record.coverage_refs):
            violations.append("goal_entrypoint_lineage_aggregate_duplicate_coverage")
        return tuple(violations)

    def validate_current(
        self,
        record: GoalEntrypointLineageAggregateRecord,
        *,
        owner_user_id: str,
    ) -> tuple[str, ...]:
        owner = self._owner(owner_user_id)
        try:
            current_snapshot = self.current_snapshot(owner_user_id=owner)
        except ValueError:
            return (
                *self._shape_violations(record, owner_user_id=owner),
                "goal_entrypoint_lineage_aggregate_current_heads_unavailable",
            )
        return self._validate_against_current_snapshot(
            record,
            owner=owner,
            current_snapshot=current_snapshot,
        )

    def _validate_against_current_snapshot(
        self,
        record: GoalEntrypointLineageAggregateRecord,
        *,
        owner: str,
        current_snapshot: GoalEntrypointLineageCurrentSnapshot,
    ) -> tuple[str, ...]:
        owner = self._owner(owner)
        violations = list(
            self._shape_violations(record, owner_user_id=owner)
        )
        try:
            current = current_snapshot.aggregate
            if current.recorded_by != owner:
                raise ValueError(
                    "GOAL entrypoint lineage current snapshot owner mismatch"
                )
        except ValueError:
            violations.append(
                "goal_entrypoint_lineage_aggregate_current_heads_unavailable"
            )
        else:
            if record.coverage_refs != current.coverage_refs:
                violations.append("goal_entrypoint_lineage_aggregate_not_current")
        return tuple(violations)

    def _apply_row(
        self,
        row: dict[str, Any],
        *,
        persist: bool,
    ) -> GoalEntrypointLineageAggregateRecord:
        if row.get("schema_version") != 2:
            raise ValueError(
                "GOAL entrypoint lineage aggregates require schema_version=2"
            )
        if row.get("event_type") != "goal_entrypoint_lineage_aggregate_recorded":
            raise ValueError("unknown GOAL entrypoint lineage aggregate event_type")
        owner = self._owner(row.get("owner_user_id"))
        raw = row.get("aggregate")
        if not isinstance(raw, dict):
            raise ValueError(
                "GOAL entrypoint lineage aggregate event is missing aggregate"
            )
        record = goal_entrypoint_lineage_aggregate_from_dict(raw)
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
                raise ValueError(
                    "GOAL entrypoint lineage aggregate identity collision"
                )
            return existing
        if persist:
            self._append(row)
        self._records[key] = record
        return record

    def _append(self, row: dict[str, Any]) -> None:
        fd = os.open(self._lock_path, os.O_RDWR | os.O_CREAT, 0o600)
        held = None
        try:
            os.chmod(self._lock_path, 0o600)
            held = acquire_exclusive_fd(fd, timeout_seconds=30.0)
            incoming = row["aggregate"]
            if self._path.exists():
                with self._path.open("r", encoding="utf-8") as existing_fh:
                    for line_no, line in enumerate(existing_fh, start=1):
                        if not line.strip():
                            continue
                        existing = json.loads(line)
                        existing_record = existing.get("aggregate")
                        if (
                            existing.get("schema_version") == 2
                            and existing.get("owner_user_id")
                            == row.get("owner_user_id")
                            and isinstance(existing_record, dict)
                            and existing_record.get("aggregate_ref")
                            == incoming.get("aggregate_ref")
                        ):
                            if existing == row:
                                return
                            raise ValueError(
                                "GOAL entrypoint lineage aggregate identity "
                                f"collision at {self._path}:{line_no}"
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
                        "invalid persisted GOAL entrypoint lineage aggregate at "
                        f"{self._path}:{line_no}"
                    ) from exc

    def _refresh_from_disk_unlocked(self) -> None:
        self._records = {}
        self._legacy_quarantined_count = 0
        self._load_existing()

    def refresh(self) -> None:
        """Reload lineage aggregate rows under their cross-process file lock."""

        with self._process_lock:
            fd = os.open(self._lock_path, os.O_RDWR | os.O_CREAT, 0o600)
            held = None
            try:
                os.chmod(self._lock_path, 0o600)
                held = acquire_exclusive_fd(fd, timeout_seconds=30.0)
                self._refresh_from_disk_unlocked()
            finally:
                if held is not None:
                    held.release()
                os.close(fd)

    def record_current(
        self,
        *,
        owner_user_id: str,
    ) -> GoalEntrypointLineageAggregateRecord:
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
                        "event_type": "goal_entrypoint_lineage_aggregate_recorded",
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
    ) -> GoalEntrypointLineageAggregateRecord:
        return self._records[
            (self._owner(owner_user_id), str(aggregate_ref or ""))
        ]

    def records(
        self,
        *,
        owner_user_id: str,
    ) -> list[GoalEntrypointLineageAggregateRecord]:
        owner = self._owner(owner_user_id)
        return [
            record
            for (record_owner, _), record in self._records.items()
            if record_owner == owner
        ]


__all__ = [
    "CORE_GOAL_SECTIONS",
    "GoalEntrypointLineageAggregateRecord",
    "GoalEntrypointLineageCurrentSnapshot",
    "LINEAGE_AGGREGATE_VERSION",
    "PersistentGoalEntrypointLineageAggregateRegistry",
    "goal_entrypoint_lineage_aggregate_from_dict",
]
