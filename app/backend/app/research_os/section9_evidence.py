"""Owner-scoped, pre-run evidence snapshots for GOAL §9 promotion."""

from __future__ import annotations

import hashlib
import json
import os
import threading
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from ..cross_process_lock import acquire_exclusive_fd
from .factor_strategy_boundary import (
    BoundaryDecision,
    BoundaryViolation,
    FactorGeneratorSpec,
    FactorLibraryEntry,
    SignalPerformanceValidationRecord,
    SignalProtocolRecord,
    SignalValidationVerdict,
    StrategyBookContract,
    StrategyLegContract,
    signal_validation_record_from_dict,
    validate_factor_generator,
    validate_factor_library_entry,
    validate_signal_performance_validation,
    validate_signal_protocol,
    validate_strategy_book,
)


@dataclass(frozen=True)
class FactorGenerationRecord:
    generation_ref: str
    produced_factor_ref: str
    generator: FactorGeneratorSpec


@dataclass(frozen=True)
class Section9EvidenceSnapshot:
    source_strategy_ref: str
    factor_library_entries: tuple[FactorLibraryEntry, ...]
    factor_generations: tuple[FactorGenerationRecord, ...]
    signal_protocols: tuple[SignalProtocolRecord, ...]
    signal_validations: tuple[SignalPerformanceValidationRecord, ...]
    strategy_book: StrategyBookContract
    snapshot_ref: str = ""
    snapshot_version: str = "section9_snapshot.v1"

    def __post_init__(self) -> None:
        for field_name in (
            "factor_library_entries",
            "factor_generations",
            "signal_protocols",
            "signal_validations",
        ):
            object.__setattr__(self, field_name, tuple(getattr(self, field_name)))
        if not self.snapshot_ref:
            object.__setattr__(self, "snapshot_ref", self.canonical_snapshot_ref)

    @property
    def canonical_snapshot_ref(self) -> str:
        payload = asdict(self)
        payload.pop("snapshot_ref", None)
        encoded = json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return f"s9snap_{hashlib.sha256(encoded).hexdigest()}"


def validate_section9_evidence_snapshot(
    snapshot: Section9EvidenceSnapshot,
) -> BoundaryDecision:
    violations: list[BoundaryViolation] = []

    def reject(code: str, message: str, *, field: str = "", ref: str = "") -> None:
        violations.append(BoundaryViolation(code, message, field=field, ref=ref))

    if not str(snapshot.source_strategy_ref or "").strip():
        reject(
            "section9_source_strategy_required",
            "§9 snapshot requires the exact persisted IDE strategy ref",
            field="source_strategy_ref",
        )
    if snapshot.snapshot_version != "section9_snapshot.v1":
        reject(
            "section9_snapshot_version_unsupported",
            "unsupported §9 snapshot version",
            field="snapshot_version",
            ref=snapshot.snapshot_ref,
        )
    if snapshot.snapshot_ref != snapshot.canonical_snapshot_ref:
        reject(
            "section9_snapshot_identity_mismatch",
            "snapshot_ref must content-bind the complete §9 pre-run snapshot",
            field="snapshot_ref",
            ref=snapshot.snapshot_ref,
        )
    for field_name in (
        "factor_library_entries",
        "factor_generations",
        "signal_protocols",
        "signal_validations",
    ):
        if not tuple(getattr(snapshot, field_name)):
            reject(
                "section9_snapshot_family_missing",
                "§9 producer receipt requires every canonical boundary family",
                field=field_name,
                ref=snapshot.snapshot_ref,
            )

    factor_by_ref = {
        str(record.factor_ref): record for record in snapshot.factor_library_entries
    }
    if len(factor_by_ref) != len(snapshot.factor_library_entries):
        reject(
            "section9_factor_ref_duplicate",
            "factor refs must be unique inside a snapshot",
            field="factor_library_entries",
            ref=snapshot.snapshot_ref,
        )
    for record in snapshot.factor_library_entries:
        violations.extend(validate_factor_library_entry(record).violations)

    produced_refs: list[str] = []
    generation_refs: set[str] = set()
    for generation in snapshot.factor_generations:
        if not str(generation.generation_ref or "").strip():
            reject(
                "section9_generation_ref_required",
                "factor generation records require a stable ref",
                field="factor_generations",
                ref=snapshot.snapshot_ref,
            )
        if generation.generation_ref in generation_refs:
            reject(
                "section9_generation_ref_duplicate",
                "factor generation refs must be unique",
                field="factor_generations",
                ref=generation.generation_ref,
            )
        generation_refs.add(generation.generation_ref)
        produced_refs.append(str(generation.produced_factor_ref))
        violations.extend(validate_factor_generator(generation.generator).violations)
    if set(produced_refs) != set(factor_by_ref) or len(produced_refs) != len(set(produced_refs)):
        reject(
            "section9_generation_factor_closure_mismatch",
            "factor generation records must exactly and uniquely cover snapshot factors",
            field="factor_generations",
            ref=snapshot.snapshot_ref,
        )

    signal_by_ref = {
        str(record.signal_ref): record for record in snapshot.signal_protocols
    }
    if len(signal_by_ref) != len(snapshot.signal_protocols):
        reject(
            "section9_signal_ref_duplicate",
            "signal refs must be unique inside a snapshot",
            field="signal_protocols",
            ref=snapshot.snapshot_ref,
        )
    for record in snapshot.signal_protocols:
        violations.extend(validate_signal_protocol(record).violations)

    validation_by_ref = {
        str(record.validation_id): record for record in snapshot.signal_validations
    }
    if len(validation_by_ref) != len(snapshot.signal_validations):
        reject(
            "section9_signal_validation_ref_duplicate",
            "signal validation refs must be unique inside a snapshot",
            field="signal_validations",
            ref=snapshot.snapshot_ref,
        )
    for record in snapshot.signal_validations:
        violations.extend(
            validate_signal_performance_validation(
                record,
                known_signal_refs=set(signal_by_ref),
            ).violations
        )
        if str(record.verdict) != SignalValidationVerdict.ACCEPTED.value:
            reject(
                "signal_validation_not_accepted",
                "§9 snapshots can only bind accepted signal validations",
                field="signal_validations",
                ref=record.validation_id,
            )

    book = snapshot.strategy_book
    if not str(book.strategy_book_ref or "").strip() or not book.legs:
        reject(
            "section9_strategy_book_incomplete",
            "§9 snapshot requires a named StrategyBook with at least one leg",
            field="strategy_book",
            ref=book.strategy_book_ref,
        )
    if set(map(str, book.factor_refs)) != set(factor_by_ref):
        reject(
            "section9_strategy_factor_closure_mismatch",
            "StrategyBook factor refs must exactly equal the snapshot factor family",
            field="strategy_book.factor_refs",
            ref=book.strategy_book_ref,
        )
    if set(map(str, book.signal_refs)) != set(signal_by_ref):
        reject(
            "section9_strategy_signal_closure_mismatch",
            "StrategyBook signal refs must exactly equal the snapshot signal family",
            field="strategy_book.signal_refs",
            ref=book.strategy_book_ref,
        )
    if set(map(str, book.signal_validation_refs)) != set(validation_by_ref):
        reject(
            "section9_strategy_validation_closure_mismatch",
            "StrategyBook validation refs must exactly equal the snapshot validation family",
            field="strategy_book.signal_validation_refs",
            ref=book.strategy_book_ref,
        )
    violations.extend(
        validate_strategy_book(
            book,
            factor_library=factor_by_ref,
            signal_protocols=signal_by_ref,
            signal_validations=validation_by_ref,
            require_signal_validation=True,
        ).violations
    )
    return BoundaryDecision(not violations, tuple(violations))


def section9_evidence_snapshot_to_dict(snapshot: Section9EvidenceSnapshot) -> dict[str, Any]:
    return asdict(snapshot)


def section9_evidence_snapshot_from_dict(raw: dict[str, Any]) -> Section9EvidenceSnapshot:
    if not isinstance(raw, dict):
        raise TypeError("§9 snapshot must be an object")

    def rows(field_name: str) -> tuple[dict[str, Any], ...]:
        value = raw.get(field_name)
        if not isinstance(value, (list, tuple)) or any(
            not isinstance(item, dict) for item in value
        ):
            raise TypeError(f"{field_name} must be a list of objects")
        return tuple(value)

    factor_rows = rows("factor_library_entries")
    generation_rows = rows("factor_generations")
    signal_rows = rows("signal_protocols")
    validation_rows = rows("signal_validations")
    book_raw = raw.get("strategy_book")
    if not isinstance(book_raw, dict):
        raise TypeError("strategy_book must be an object")
    return Section9EvidenceSnapshot(
        source_strategy_ref=str(raw.get("source_strategy_ref") or ""),
        factor_library_entries=tuple(FactorLibraryEntry(**item) for item in factor_rows),
        factor_generations=tuple(
            FactorGenerationRecord(
                generation_ref=str(item.get("generation_ref") or ""),
                produced_factor_ref=str(item.get("produced_factor_ref") or ""),
                generator=FactorGeneratorSpec(**dict(item.get("generator") or {})),
            )
            for item in generation_rows
        ),
        signal_protocols=tuple(SignalProtocolRecord(**item) for item in signal_rows),
        signal_validations=tuple(
            signal_validation_record_from_dict(item) for item in validation_rows
        ),
        strategy_book=StrategyBookContract(
            strategy_book_ref=str(book_raw.get("strategy_book_ref") or ""),
            factor_refs=tuple(book_raw.get("factor_refs") or ()),
            signal_refs=tuple(book_raw.get("signal_refs") or ()),
            legs=tuple(
                StrategyLegContract(**leg) for leg in tuple(book_raw.get("legs") or ())
            ),
            default_factor_refs=tuple(book_raw.get("default_factor_refs") or ()),
            mathematical_refs=tuple(book_raw.get("mathematical_refs") or ()),
            theory_binding_refs=tuple(book_raw.get("theory_binding_refs") or ()),
            run_config_binding_refs=tuple(book_raw.get("run_config_binding_refs") or ()),
            signal_validation_refs=tuple(book_raw.get("signal_validation_refs") or ()),
            market_data_use_validation_refs=tuple(
                book_raw.get("market_data_use_validation_refs") or ()
            ),
            portfolio_of_strategies_refs=tuple(
                book_raw.get("portfolio_of_strategies_refs") or ()
            ),
            correlation_budget_ref=book_raw.get("correlation_budget_ref"),
            capacity_budget_ref=book_raw.get("capacity_budget_ref"),
            drawdown_budget_ref=book_raw.get("drawdown_budget_ref"),
            capital_allocation_ref=book_raw.get("capital_allocation_ref"),
        ),
        snapshot_ref=str(raw.get("snapshot_ref") or ""),
        snapshot_version=str(raw.get("snapshot_version") or "section9_snapshot.v1"),
    )


class PersistentSection9EvidenceRegistry:
    """Append-only owner envelope for pre-run §9 snapshots."""

    def __init__(self, path: str | Path) -> None:
        self._path = Path(path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._lock_path = self._path.with_name(f".{self._path.name}.lock")
        self._lock = threading.RLock()
        self._records: dict[tuple[str, str], Section9EvidenceSnapshot] = {}
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
            raise ValueError("§9 snapshot owner_user_id is required")
        return owner

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
                        f"invalid persisted §9 snapshot at {self._path}:{line_no}"
                    ) from exc

    def _append(self, row: dict[str, Any]) -> None:
        fd = os.open(self._lock_path, os.O_RDWR | os.O_CREAT, 0o600)
        held = None
        try:
            os.chmod(self._lock_path, 0o600)
            held = acquire_exclusive_fd(fd, timeout_seconds=30.0)
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

    def _apply_row(self, row: dict[str, Any], *, persist: bool) -> Section9EvidenceSnapshot:
        if row.get("schema_version") != 2:
            raise ValueError("§9 snapshots require schema_version=2 owner envelopes")
        if row.get("event_type") != "section9_evidence_snapshot_recorded":
            raise ValueError("unknown §9 snapshot event_type")
        owner = self._owner(row.get("owner_user_id"))
        if not str(row.get("recorded_by") or "").strip():
            raise ValueError("§9 snapshot recorded_by is required")
        raw = row.get("snapshot")
        if not isinstance(raw, dict):
            raise ValueError("§9 snapshot event missing snapshot")
        snapshot = section9_evidence_snapshot_from_dict(raw)
        decision = validate_section9_evidence_snapshot(snapshot)
        if not decision.accepted:
            raise ValueError("; ".join(item.code for item in decision.violations))
        key = (owner, snapshot.snapshot_ref)
        with self._lock:
            existing = self._records.get(key)
            if existing is not None:
                if existing != snapshot:
                    raise ValueError("§9 snapshot identity collision with different content")
                return existing
            if persist:
                self._append(row)
            self._records[key] = snapshot
            return snapshot

    def record_snapshot(
        self,
        snapshot: Section9EvidenceSnapshot,
        *,
        owner_user_id: str,
        recorded_by: str,
    ) -> Section9EvidenceSnapshot:
        owner = self._owner(owner_user_id)
        actor = str(recorded_by or "").strip()
        if not actor:
            raise ValueError("§9 snapshot recorded_by is required")
        return self._apply_row(
            {
                "schema_version": 2,
                "event_type": "section9_evidence_snapshot_recorded",
                "owner_user_id": owner,
                "recorded_by": actor,
                "snapshot": section9_evidence_snapshot_to_dict(snapshot),
            },
            persist=True,
        )

    def snapshot(
        self,
        snapshot_ref: str,
        *,
        owner_user_id: str,
    ) -> Section9EvidenceSnapshot:
        return self._records[(self._owner(owner_user_id), str(snapshot_ref))]

    def snapshots(self, *, owner_user_id: str) -> list[Section9EvidenceSnapshot]:
        owner = self._owner(owner_user_id)
        return [
            snapshot
            for (record_owner, _snapshot_ref), snapshot in self._records.items()
            if record_owner == owner
        ]


__all__ = [
    "FactorGenerationRecord",
    "PersistentSection9EvidenceRegistry",
    "Section9EvidenceSnapshot",
    "section9_evidence_snapshot_from_dict",
    "section9_evidence_snapshot_to_dict",
    "validate_section9_evidence_snapshot",
]
