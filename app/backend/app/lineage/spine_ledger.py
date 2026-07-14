"""Canonical Mathematical Spine repository.

SQLite WAL is the source of truth.  Every accepted immutable record and its
audit-outbox event are committed in one transaction.  A hash-chained JSONL
mirror is then drained idempotently; a mirror failure remains explicit and can
be repaired without losing the canonical record.
"""

from __future__ import annotations

import json
import hashlib
import os
import sqlite3
import threading
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Callable, TypeVar

from ..cross_process_lock import acquire_exclusive_fd
from .ids import canonical_json, content_hash
from .spine import (
    ConsistencyCheck,
    ImplementationSpec,
    MathematicalSpineChainRecord,
    MathematicalArtifact,
    MethodologyChoiceRecord,
    ResponsibilityDisclosureRecord,
    TheoryImplementationBinding,
    TheorySpec,
    canonical_spine_record_identity,
)

OP_ARTIFACT = "math_artifact"
OP_THEORY_SPEC = "theory_spec"
OP_IMPLEMENTATION_SPEC = "implementation_spec"
OP_BINDING = "theory_impl_binding"
OP_CHECK = "consistency_check"
OP_CHOICE = "methodology_choice"
OP_RESPONSIBILITY = "responsibility_disclosure"
OP_CHAIN = "mathematical_spine_chain"

DB_FILENAME = "spine_ledger.sqlite"
MIRROR_FILENAME = "spine_ledger.jsonl"
LOCK_FILENAME = ".spine_ledger_mirror.lock"
AUDIT_HASH_VERSION = "sha256-v1"
GENESIS_HASH = "0" * 64


def _full_content_hash(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


class SpineAuditIntegrityError(RuntimeError):
    """The audit mirror is malformed, divergent, or unexpectedly truncated."""


class SpineMirrorPendingError(RuntimeError):
    """The canonical SQLite write committed but its audit mirror is pending."""


@dataclass(frozen=True)
class SpineChainBackingViolation:
    code: str
    field: str
    ref: str
    message: str


@dataclass(frozen=True)
class SpineChainBackingDecision:
    accepted: bool
    violations: tuple[SpineChainBackingViolation, ...]


@dataclass(frozen=True)
class SpineChainRecordRefs:
    """Canonical record closure reachable from one verified chain."""

    mathematical_refs: tuple[str, ...]
    implementation_refs: tuple[str, ...]
    theory_binding_refs: tuple[str, ...]
    consistency_check_refs: tuple[str, ...]
    methodology_choice_refs: tuple[str, ...]
    responsibility_refs: tuple[str, ...]


@dataclass(frozen=True)
class CanonicalSpinePackage:
    """One transactionally persisted Mathematical Spine evidence package."""

    artifacts: tuple[MathematicalArtifact, ...]
    theory_specs: tuple[TheorySpec, ...]
    implementation_specs: tuple[ImplementationSpec, ...]
    bindings: tuple[TheoryImplementationBinding, ...]
    checks: tuple[ConsistencyCheck, ...]
    choices: tuple[MethodologyChoiceRecord, ...]
    responsibilities: tuple[ResponsibilityDisclosureRecord, ...]

    def __post_init__(self) -> None:
        for name in (
            "artifacts",
            "theory_specs",
            "implementation_specs",
            "bindings",
            "checks",
            "choices",
            "responsibilities",
        ):
            object.__setattr__(self, name, tuple(getattr(self, name)))


@dataclass(frozen=True)
class SpinePackageRecordRefs:
    artifact_refs: tuple[str, ...]
    theory_spec_refs: tuple[str, ...]
    implementation_spec_refs: tuple[str, ...]
    binding_refs: tuple[str, ...]
    check_refs: tuple[str, ...]
    choice_refs: tuple[str, ...]
    responsibility_refs: tuple[str, ...]


def _artifact_payload(value: MathematicalArtifact) -> dict[str, Any]:
    return asdict(value)


def _theory_spec_payload(value: TheorySpec) -> dict[str, Any]:
    return asdict(value)


def _implementation_spec_payload(value: ImplementationSpec) -> dict[str, Any]:
    return asdict(value)


def _binding_payload(value: TheoryImplementationBinding) -> dict[str, Any]:
    return asdict(value)


def _check_payload(value: ConsistencyCheck) -> dict[str, Any]:
    return asdict(value)


def _choice_payload(value: MethodologyChoiceRecord) -> dict[str, Any]:
    return asdict(value)


def _responsibility_payload(value: ResponsibilityDisclosureRecord) -> dict[str, Any]:
    return asdict(value)


_RECORD_SPECS: dict[str, tuple[type[Any], str]] = {
    OP_ARTIFACT: (MathematicalArtifact, "artifact_id"),
    OP_THEORY_SPEC: (TheorySpec, "theory_spec_id"),
    OP_IMPLEMENTATION_SPEC: (ImplementationSpec, "implementation_spec_id"),
    OP_BINDING: (TheoryImplementationBinding, "binding_id"),
    OP_CHECK: (ConsistencyCheck, "check_id"),
    OP_CHOICE: (MethodologyChoiceRecord, "choice_id"),
    OP_RESPONSIBILITY: (ResponsibilityDisclosureRecord, "disclosure_id"),
    OP_CHAIN: (MathematicalSpineChainRecord, "chain_ref"),
}

T = TypeVar("T")


class SpineLedger:
    """One canonical, owner-scoped, append-only Mathematical Spine ledger."""

    def __init__(self, root: Path | str) -> None:
        self._root = Path(root)
        self._root.mkdir(parents=True, exist_ok=True)
        self._db_path = self._root / DB_FILENAME
        self._mirror_path = self._root / MIRROR_FILENAME
        self._lock_path = self._root / LOCK_FILENAME
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(
            str(self._db_path),
            isolation_level=None,
            timeout=30.0,
            check_same_thread=False,
        )
        self._conn.row_factory = sqlite3.Row
        mode = str(self._conn.execute("PRAGMA journal_mode=WAL").fetchone()[0]).lower()
        if mode != "wal":
            raise RuntimeError(f"Mathematical Spine requires SQLite WAL, got {mode!r}")
        self._conn.execute("PRAGMA synchronous=FULL")
        self._conn.execute("PRAGMA foreign_keys=ON")
        self._init_schema()
        self.sync_audit_mirror()

    @property
    def db_path(self) -> Path:
        return self._db_path

    @property
    def mirror_path(self) -> Path:
        return self._mirror_path

    def _init_schema(self) -> None:
        self._conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS spine_records (
                record_type TEXT NOT NULL,
                record_id TEXT NOT NULL,
                owner TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                payload_hash TEXT NOT NULL,
                created_seq INTEGER NOT NULL,
                PRIMARY KEY (record_type, record_id, owner)
            );
            CREATE INDEX IF NOT EXISTS idx_spine_record_id
                ON spine_records(record_id, owner);
            CREATE INDEX IF NOT EXISTS idx_spine_record_type_seq
                ON spine_records(record_type, created_seq);
            CREATE TABLE IF NOT EXISTS spine_audit_events (
                seq INTEGER PRIMARY KEY AUTOINCREMENT,
                event_id TEXT NOT NULL UNIQUE,
                record_type TEXT NOT NULL,
                record_id TEXT NOT NULL,
                owner TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                payload_hash TEXT NOT NULL,
                mirrored INTEGER NOT NULL DEFAULT 0 CHECK (mirrored IN (0, 1)),
                UNIQUE (record_type, record_id, owner),
                FOREIGN KEY (record_type, record_id, owner)
                    REFERENCES spine_records(record_type, record_id, owner)
            );
            CREATE TABLE IF NOT EXISTS spine_meta (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );
            """
        )
        row = self._conn.execute(
            "SELECT value FROM spine_meta WHERE key='audit_hash_version'"
        ).fetchone()
        if row is None:
            event_count = int(
                self._conn.execute("SELECT COUNT(*) FROM spine_audit_events").fetchone()[0]
            )
            if event_count:
                raise SpineAuditIntegrityError(
                    "legacy truncated Mathematical Spine audit hashes require explicit migration"
                )
            self._conn.execute(
                "INSERT INTO spine_meta(key, value) VALUES ('audit_hash_version', ?)",
                (AUDIT_HASH_VERSION,),
            )
        elif str(row["value"]) != AUDIT_HASH_VERSION:
            raise SpineAuditIntegrityError(
                f"unsupported Mathematical Spine audit_hash_version={row['value']!r}"
            )

    @staticmethod
    def _owner(owner: str) -> str:
        normalized = str(owner or "").strip()
        if not normalized:
            raise ValueError("Mathematical Spine owner is required")
        return normalized

    @staticmethod
    def _payload(record: Any) -> dict[str, Any]:
        return asdict(record)

    @staticmethod
    def _record_id(record_type: str, record: Any) -> str:
        expected_type, id_field = _RECORD_SPECS[record_type]
        if not isinstance(record, expected_type):
            raise TypeError(
                f"{record_type} requires {expected_type.__name__}, got {type(record).__name__}"
            )
        record_id = str(getattr(record, id_field) or "")
        expected_id = canonical_spine_record_identity(record)
        if not record_id or record_id != expected_id:
            raise ValueError(
                f"{record_type} identity mismatch: supplied={record_id!r} expected={expected_id!r}"
            )
        return record_id

    def _exists(self, record_types: tuple[str, ...], record_id: str, owner: str) -> bool:
        placeholders = ",".join("?" for _ in record_types)
        row = self._conn.execute(
            f"SELECT 1 FROM spine_records WHERE owner=? AND record_id=? "
            f"AND record_type IN ({placeholders}) LIMIT 1",
            (owner, record_id, *record_types),
        ).fetchone()
        return row is not None

    def _validate_parentage(self, record_type: str, record: Any, owner: str) -> None:
        if record_type == OP_THEORY_SPEC and not self._exists(
            (OP_ARTIFACT,), record.artifact_ref, owner
        ):
            raise ValueError("TheorySpec artifact_ref is not recorded for owner")
        if record_type == OP_IMPLEMENTATION_SPEC and not self._exists(
            (OP_ARTIFACT, OP_THEORY_SPEC), record.theory_ref, owner
        ):
            raise ValueError("ImplementationSpec theory_ref is not recorded for owner")
        if record_type == OP_BINDING:
            if not self._exists((OP_ARTIFACT, OP_THEORY_SPEC), record.theory_ref, owner):
                raise ValueError("TheoryImplementationBinding theory_ref is not recorded for owner")
            if str(record.implementation_ref).startswith("implspec_") and not self._exists(
                (OP_IMPLEMENTATION_SPEC,), record.implementation_ref, owner
            ):
                raise ValueError("TheoryImplementationBinding implementation_ref is not recorded for owner")
        if record_type == OP_CHECK and not self._exists(
            (OP_BINDING,), record.binding_id, owner
        ):
            raise ValueError("ConsistencyCheck binding_id is not recorded for owner")
        if record_type == OP_RESPONSIBILITY:
            if record.methodology_choice_ref and not self._exists(
                (OP_CHOICE,), record.methodology_choice_ref, owner
            ):
                raise ValueError("ResponsibilityDisclosure methodology_choice_ref is not recorded for owner")
        if record_type == OP_CHAIN:
            if str(record.recorded_by or "") != owner:
                raise ValueError("Mathematical Spine chain recorded_by must equal owner")
            for binding_ref in record.theory_binding_refs:
                if not self._exists((OP_BINDING,), binding_ref, owner):
                    raise ValueError("Mathematical Spine chain binding is not recorded for owner")
            for check_ref in record.consistency_check_refs:
                if not self._exists((OP_CHECK,), check_ref, owner):
                    raise ValueError("Mathematical Spine chain check is not recorded for owner")
            if not self._exists((OP_CHOICE,), record.methodology_choice_ref, owner):
                raise ValueError("Mathematical Spine chain choice is not recorded for owner")
            if not self._exists(
                (OP_RESPONSIBILITY,), record.responsibility_boundary_ref, owner
            ):
                raise ValueError(
                    "Mathematical Spine chain responsibility is not recorded for owner"
                )

    def _record(self, record_type: str, record: T, *, owner: str) -> T:
        owner = self._owner(owner)
        record_id = self._record_id(record_type, record)
        payload = self._payload(record)
        payload_json = canonical_json(payload)
        payload_hash = _full_content_hash(payload)
        event_id = _full_content_hash(
            {
                "record_type": record_type,
                "record_id": record_id,
                "owner": owner,
                "payload_hash": payload_hash,
            }
        )
        with self._lock:
            self._conn.execute("BEGIN IMMEDIATE")
            try:
                existing = self._conn.execute(
                    "SELECT payload_hash, payload_json FROM spine_records "
                    "WHERE record_type=? AND record_id=? AND owner=?",
                    (record_type, record_id, owner),
                ).fetchone()
                if existing is not None:
                    if (
                        existing["payload_hash"] != payload_hash
                        or existing["payload_json"] != payload_json
                    ):
                        raise ValueError(f"{record_type} persisted identity collision")
                    self._conn.execute("COMMIT")
                else:
                    self._validate_parentage(record_type, record, owner)
                    self._conn.execute(
                        "INSERT INTO spine_records"
                        "(record_type, record_id, owner, payload_json, payload_hash, created_seq) "
                        "VALUES (?, ?, ?, ?, ?, ?)",
                        (record_type, record_id, owner, payload_json, payload_hash, 0),
                    )
                    cursor = self._conn.execute(
                        "INSERT INTO spine_audit_events"
                        "(event_id, record_type, record_id, owner, payload_json, payload_hash) "
                        "VALUES (?, ?, ?, ?, ?, ?)",
                        (event_id, record_type, record_id, owner, payload_json, payload_hash),
                    )
                    seq = int(cursor.lastrowid)
                    self._conn.execute(
                        "UPDATE spine_records SET created_seq=? "
                        "WHERE record_type=? AND record_id=? AND owner=?",
                        (seq, record_type, record_id, owner),
                    )
                    self._conn.execute("COMMIT")
            except Exception:
                if self._conn.in_transaction:
                    self._conn.execute("ROLLBACK")
                raise
        try:
            self.sync_audit_mirror()
        except Exception as exc:
            raise SpineMirrorPendingError(
                f"canonical Mathematical Spine record committed but audit mirror is pending: {record_id}"
            ) from exc
        return record

    @staticmethod
    def _mirror_hash(row: dict[str, Any]) -> str:
        return _full_content_hash(
            {
                "seq": row["seq"],
                "prev_hash": row["prev_hash"],
                "event_id": row["event_id"],
                "record_type": row["record_type"],
                "record_id": row["record_id"],
                "owner": row["owner"],
                "payload_hash": row["payload_hash"],
                "payload": row["payload"],
            }
        )

    def _scan_mirror(self) -> list[dict[str, Any]]:
        if not self._mirror_path.exists():
            return []
        rows: list[dict[str, Any]] = []
        prev = GENESIS_HASH
        for line_no, line in enumerate(
            self._mirror_path.read_text(encoding="utf-8").splitlines(), start=1
        ):
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError as exc:
                raise SpineAuditIntegrityError(
                    f"invalid Mathematical Spine audit JSON at line {line_no}"
                ) from exc
            expected_seq = len(rows) + 1
            if row.get("seq") != expected_seq or row.get("prev_hash") != prev:
                raise SpineAuditIntegrityError(
                    f"Mathematical Spine audit chain discontinuity at line {line_no}"
                )
            if row.get("payload_hash") != _full_content_hash(row.get("payload")):
                raise SpineAuditIntegrityError(
                    f"Mathematical Spine audit payload hash mismatch at line {line_no}"
                )
            if row.get("row_hash") != self._mirror_hash(row):
                raise SpineAuditIntegrityError(
                    f"Mathematical Spine audit row hash mismatch at line {line_no}"
                )
            prev = row["row_hash"]
            rows.append(row)
        return rows

    def sync_audit_mirror(self) -> int:
        """Drain committed audit events to the JSONL mirror, idempotently."""

        fd = os.open(self._lock_path, os.O_RDWR | os.O_CREAT, 0o600)
        held = None
        try:
            os.chmod(self._lock_path, 0o600)
            held = acquire_exclusive_fd(fd, timeout_seconds=30.0)
            with self._lock:
                rows = self._scan_mirror()
                events = self._conn.execute(
                    "SELECT seq, event_id, record_type, record_id, owner, "
                    "payload_json, payload_hash, mirrored "
                    "FROM spine_audit_events ORDER BY seq"
                ).fetchall()
                if len(rows) > len(events):
                    raise SpineAuditIntegrityError(
                        "Mathematical Spine audit mirror has events absent from SQLite"
                    )
                for index, row in enumerate(rows):
                    event = events[index]
                    if (
                        row["seq"] != event["seq"]
                        or row["event_id"] != event["event_id"]
                        or row["payload_hash"] != event["payload_hash"]
                    ):
                        raise SpineAuditIntegrityError(
                            "Mathematical Spine audit mirror diverges from SQLite"
                        )
                    if not event["mirrored"]:
                        self._conn.execute(
                            "UPDATE spine_audit_events SET mirrored=1 WHERE seq=?",
                            (event["seq"],),
                        )
                prev = rows[-1]["row_hash"] if rows else GENESIS_HASH
                appended = 0
                for event in events[len(rows) :]:
                    if event["mirrored"]:
                        raise SpineAuditIntegrityError(
                            "Mathematical Spine audit mirror was truncated after a mirrored event"
                        )
                    payload = json.loads(event["payload_json"])
                    mirror_row = {
                        "seq": event["seq"],
                        "prev_hash": prev,
                        "event_id": event["event_id"],
                        "record_type": event["record_type"],
                        "record_id": event["record_id"],
                        "owner": event["owner"],
                        "payload_hash": event["payload_hash"],
                        "payload": payload,
                    }
                    mirror_row["row_hash"] = self._mirror_hash(mirror_row)
                    with self._mirror_path.open("a", encoding="utf-8") as fh:
                        fh.write(
                            json.dumps(
                                mirror_row,
                                ensure_ascii=False,
                                sort_keys=True,
                                separators=(",", ":"),
                            )
                            + "\n"
                        )
                        fh.flush()
                        os.fsync(fh.fileno())
                    self._conn.execute(
                        "UPDATE spine_audit_events SET mirrored=1 WHERE seq=?",
                        (event["seq"],),
                    )
                    prev = mirror_row["row_hash"]
                    appended += 1
                return appended
        finally:
            if held is not None:
                held.release()
            os.close(fd)

    def _rows(self, record_type: str, *, owner: str | None = None) -> list[dict[str, Any]]:
        sql = "SELECT payload_json FROM spine_records WHERE record_type=?"
        params: tuple[Any, ...] = (record_type,)
        if owner is not None:
            sql += " AND owner=?"
            params += (self._owner(owner),)
        sql += " ORDER BY created_seq"
        with self._lock:
            return [
                json.loads(row["payload_json"])
                for row in self._conn.execute(sql, params).fetchall()
            ]

    def _row(
        self,
        record_types: tuple[str, ...],
        record_id: str,
        *,
        owner: str | None = None,
    ) -> dict[str, Any]:
        placeholders = ",".join("?" for _ in record_types)
        sql = (
            "SELECT payload_json FROM spine_records WHERE record_id=? "
            f"AND record_type IN ({placeholders})"
        )
        params: tuple[Any, ...] = (str(record_id), *record_types)
        if owner is not None:
            sql += " AND owner=?"
            params += (self._owner(owner),)
        sql += " ORDER BY created_seq DESC"
        with self._lock:
            rows = self._conn.execute(sql, params).fetchall()
        if not rows:
            raise KeyError(record_id)
        if owner is None and len(rows) > 1:
            raise ValueError(f"Mathematical Spine ref {record_id!r} is owner-ambiguous")
        return json.loads(rows[0]["payload_json"])

    def record_artifact(self, value: MathematicalArtifact, *, owner: str = "system") -> str:
        return self._record(OP_ARTIFACT, value, owner=owner).artifact_id

    def record_theory_spec(self, value: TheorySpec, *, owner: str = "system") -> str:
        return self._record(OP_THEORY_SPEC, value, owner=owner).theory_spec_id

    def record_implementation_spec(
        self, value: ImplementationSpec, *, owner: str = "system"
    ) -> str:
        return self._record(OP_IMPLEMENTATION_SPEC, value, owner=owner).implementation_spec_id

    def record_binding(
        self, value: TheoryImplementationBinding, *, owner: str = "system"
    ) -> str:
        return self._record(OP_BINDING, value, owner=owner).binding_id

    def record_check(self, value: ConsistencyCheck, *, owner: str = "system") -> str:
        return self._record(OP_CHECK, value, owner=owner).check_id

    def record_choice(self, value: MethodologyChoiceRecord, *, owner: str = "system") -> str:
        return self._record(OP_CHOICE, value, owner=owner).choice_id

    def record_responsibility(
        self, value: ResponsibilityDisclosureRecord, *, owner: str = "system"
    ) -> str:
        return self._record(OP_RESPONSIBILITY, value, owner=owner).disclosure_id

    def record_chain(
        self,
        value: MathematicalSpineChainRecord,
        *,
        owner: str,
    ) -> MathematicalSpineChainRecord:
        return self._record(OP_CHAIN, value, owner=owner)

    def record_package(
        self,
        package: CanonicalSpinePackage,
        *,
        owner: str,
    ) -> SpinePackageRecordRefs:
        """Persist a complete package and its outbox events in one transaction."""

        if not isinstance(package, CanonicalSpinePackage):
            raise TypeError("record_package requires CanonicalSpinePackage")
        owner = self._owner(owner)
        required_groups = {
            "artifacts": package.artifacts,
            "theory_specs": package.theory_specs,
            "implementation_specs": package.implementation_specs,
            "bindings": package.bindings,
            "checks": package.checks,
            "choices": package.choices,
            "responsibilities": package.responsibilities,
        }
        missing = [name for name, values in required_groups.items() if not values]
        if missing:
            raise ValueError(
                "canonical Mathematical Spine package is incomplete: "
                + ", ".join(missing)
            )
        record_type_by_group = {
            "artifacts": OP_ARTIFACT,
            "theory_specs": OP_THEORY_SPEC,
            "implementation_specs": OP_IMPLEMENTATION_SPEC,
            "bindings": OP_BINDING,
            "checks": OP_CHECK,
            "choices": OP_CHOICE,
            "responsibilities": OP_RESPONSIBILITY,
        }
        for group_name, records in required_groups.items():
            record_type = record_type_by_group[group_name]
            record_ids = [self._record_id(record_type, record) for record in records]
            if len(record_ids) != len(set(record_ids)):
                raise ValueError(
                    f"canonical Mathematical Spine package contains duplicate {group_name}"
                )
        package_artifact_ids = {
            artifact.artifact_id for artifact in package.artifacts
        }
        theory_artifact_ids = {
            theory.artifact_ref for theory in package.theory_specs
        }
        if package_artifact_ids != theory_artifact_ids:
            raise ValueError(
                "canonical Mathematical Spine package theories must exactly cover "
                "package artifacts"
            )
        package_theory_ids = {
            theory.theory_spec_id for theory in package.theory_specs
        }
        implementation_theory_ids = {
            implementation.theory_ref
            for implementation in package.implementation_specs
        }
        if package_theory_ids != implementation_theory_ids:
            raise ValueError(
                "canonical Mathematical Spine package implementations must exactly "
                "cover package theories"
            )
        package_implementation_ids = {
            implementation.implementation_spec_id
            for implementation in package.implementation_specs
        }
        binding_implementation_ids = {
            binding.implementation_ref for binding in package.bindings
        }
        if package_implementation_ids != binding_implementation_ids:
            raise ValueError(
                "canonical Mathematical Spine package bindings must exactly cover "
                "package implementations"
            )
        binding_theory_ids = {binding.theory_ref for binding in package.bindings}
        if binding_theory_ids != package_theory_ids:
            raise ValueError(
                "canonical Mathematical Spine package bindings must exactly cover "
                "package theories"
            )
        package_binding_ids = {binding.binding_id for binding in package.bindings}
        checked_binding_ids = {check.binding_id for check in package.checks}
        if package_binding_ids != checked_binding_ids:
            raise ValueError(
                "canonical Mathematical Spine package checks must exactly cover package bindings"
            )
        package_choice_ids = {choice.choice_id for choice in package.choices}
        if any(
            responsibility.methodology_choice_ref not in package_choice_ids
            for responsibility in package.responsibilities
        ):
            raise ValueError(
                "canonical Mathematical Spine package responsibility must bind a package choice"
            )
        responsibility_choice_ids = {
            responsibility.methodology_choice_ref
            for responsibility in package.responsibilities
        }
        if responsibility_choice_ids != package_choice_ids:
            raise ValueError(
                "canonical Mathematical Spine package responsibilities must exactly "
                "cover package choices"
            )

        ordered: tuple[tuple[str, Any], ...] = tuple(
            (record_type, record)
            for record_type, records in (
                (OP_ARTIFACT, package.artifacts),
                (OP_THEORY_SPEC, package.theory_specs),
                (OP_IMPLEMENTATION_SPEC, package.implementation_specs),
                (OP_BINDING, package.bindings),
                (OP_CHECK, package.checks),
                (OP_CHOICE, package.choices),
                (OP_RESPONSIBILITY, package.responsibilities),
            )
            for record in records
        )

        with self._lock:
            self._conn.execute("BEGIN IMMEDIATE")
            try:
                for record_type, record in ordered:
                    record_id = self._record_id(record_type, record)
                    payload = self._payload(record)
                    payload_json = canonical_json(payload)
                    payload_hash = _full_content_hash(payload)
                    existing = self._conn.execute(
                        "SELECT payload_hash, payload_json FROM spine_records "
                        "WHERE record_type=? AND record_id=? AND owner=?",
                        (record_type, record_id, owner),
                    ).fetchone()
                    if existing is not None:
                        if (
                            existing["payload_hash"] != payload_hash
                            or existing["payload_json"] != payload_json
                        ):
                            raise ValueError(
                                f"{record_type} persisted identity collision"
                            )
                        continue
                    self._validate_parentage(record_type, record, owner)
                    event_id = _full_content_hash(
                        {
                            "record_type": record_type,
                            "record_id": record_id,
                            "owner": owner,
                            "payload_hash": payload_hash,
                        }
                    )
                    self._conn.execute(
                        "INSERT INTO spine_records"
                        "(record_type, record_id, owner, payload_json, payload_hash, created_seq) "
                        "VALUES (?, ?, ?, ?, ?, ?)",
                        (record_type, record_id, owner, payload_json, payload_hash, 0),
                    )
                    cursor = self._conn.execute(
                        "INSERT INTO spine_audit_events"
                        "(event_id, record_type, record_id, owner, payload_json, payload_hash) "
                        "VALUES (?, ?, ?, ?, ?, ?)",
                        (
                            event_id,
                            record_type,
                            record_id,
                            owner,
                            payload_json,
                            payload_hash,
                        ),
                    )
                    self._conn.execute(
                        "UPDATE spine_records SET created_seq=? "
                        "WHERE record_type=? AND record_id=? AND owner=?",
                        (int(cursor.lastrowid), record_type, record_id, owner),
                    )
                self._conn.execute("COMMIT")
            except Exception:
                if self._conn.in_transaction:
                    self._conn.execute("ROLLBACK")
                raise
        try:
            self.sync_audit_mirror()
        except Exception as exc:
            raise SpineMirrorPendingError(
                "canonical Mathematical Spine package committed but audit mirror is pending"
            ) from exc

        return SpinePackageRecordRefs(
            artifact_refs=tuple(item.artifact_id for item in package.artifacts),
            theory_spec_refs=tuple(item.theory_spec_id for item in package.theory_specs),
            implementation_spec_refs=tuple(
                item.implementation_spec_id for item in package.implementation_specs
            ),
            binding_refs=tuple(item.binding_id for item in package.bindings),
            check_refs=tuple(item.check_id for item in package.checks),
            choice_refs=tuple(item.choice_id for item in package.choices),
            responsibility_refs=tuple(
                item.disclosure_id for item in package.responsibilities
            ),
        )

    def artifact(self, ref: str, *, owner: str | None = None) -> MathematicalArtifact:
        return MathematicalArtifact(**self._row((OP_ARTIFACT,), ref, owner=owner))

    def theory_spec(self, ref: str, *, owner: str | None = None) -> TheorySpec:
        return TheorySpec(**self._row((OP_THEORY_SPEC,), ref, owner=owner))

    def implementation_spec(
        self, ref: str, *, owner: str | None = None
    ) -> ImplementationSpec:
        return ImplementationSpec(**self._row((OP_IMPLEMENTATION_SPEC,), ref, owner=owner))

    def binding(self, ref: str, *, owner: str | None = None) -> TheoryImplementationBinding:
        return TheoryImplementationBinding(**self._row((OP_BINDING,), ref, owner=owner))

    def check(self, ref: str, *, owner: str | None = None) -> ConsistencyCheck:
        return ConsistencyCheck(**self._row((OP_CHECK,), ref, owner=owner))

    def choice(self, ref: str, *, owner: str | None = None) -> MethodologyChoiceRecord:
        return MethodologyChoiceRecord(**self._row((OP_CHOICE,), ref, owner=owner))

    def responsibility(
        self, ref: str, *, owner: str | None = None
    ) -> ResponsibilityDisclosureRecord:
        return ResponsibilityDisclosureRecord(
            **self._row((OP_RESPONSIBILITY,), ref, owner=owner)
        )

    def chain(
        self,
        ref: str,
        *,
        owner: str | None = None,
    ) -> MathematicalSpineChainRecord:
        return MathematicalSpineChainRecord(
            **self._row((OP_CHAIN,), ref, owner=owner)
        )

    def chains(
        self,
        *,
        owner: str | None = None,
    ) -> list[MathematicalSpineChainRecord]:
        return [
            MathematicalSpineChainRecord(**row)
            for row in self._rows(OP_CHAIN, owner=owner)
        ]

    def theory(self, ref: str, *, owner: str | None = None) -> MathematicalArtifact | TheorySpec:
        try:
            return self.artifact(ref, owner=owner)
        except KeyError:
            return self.theory_spec(ref, owner=owner)

    def list_bindings(
        self, theory_ref: str | None = None, *, owner: str | None = None
    ) -> list[dict[str, Any]]:
        rows = self._rows(OP_BINDING, owner=owner)
        return rows if theory_ref is None else [row for row in rows if row["theory_ref"] == theory_ref]

    def latest_binding(
        self, theory_ref: str, *, owner: str | None = None
    ) -> dict[str, Any] | None:
        rows = self.list_bindings(theory_ref, owner=owner)
        return rows[-1] if rows else None

    def checks_for(
        self, binding_id: str, *, owner: str | None = None
    ) -> list[dict[str, Any]]:
        return [
            row
            for row in self._rows(OP_CHECK, owner=owner)
            if row["binding_id"] == binding_id
        ]

    def choices_for(self, asset_ref: str, *, owner: str | None = None) -> list[dict[str, Any]]:
        return [
            row
            for row in self._rows(OP_CHOICE, owner=owner)
            if row["asset_ref"] == asset_ref
        ]

    def chain_record_refs(self, record: Any, *, owner: str) -> SpineChainRecordRefs:
        """Return the exact owner-scoped canonical records cited by ``record``.

        This method deliberately performs typed lookups instead of trusting ref
        prefixes.  Callers that need a verified chain must first run
        ``validate_chain_backing`` (the chain registry does this before exposing
        this closure).
        """

        owner = self._owner(owner)
        mathematical: set[str] = set()
        implementations: set[str] = set()
        bindings: set[str] = set()
        checks: set[str] = set()

        for ref in tuple(getattr(record, "theory_binding_refs", ()) or ()):
            binding = self.binding(str(ref), owner=owner)
            bindings.add(binding.binding_id)
            theory = self.theory(binding.theory_ref, owner=owner)
            if isinstance(theory, TheorySpec):
                mathematical.add(theory.theory_spec_id)
                artifact = self.artifact(theory.artifact_ref, owner=owner)
                mathematical.add(artifact.artifact_id)
            else:
                mathematical.add(theory.artifact_id)
            implementation = self.implementation_spec(
                binding.implementation_ref,
                owner=owner,
            )
            implementations.add(implementation.implementation_spec_id)

        for ref in tuple(getattr(record, "consistency_check_refs", ()) or ()):
            check = self.check(str(ref), owner=owner)
            if check.binding_id not in bindings:
                raise ValueError(
                    "Mathematical Spine chain check targets an uncited binding"
                )
            checks.add(check.check_id)

        choice = self.choice(
            str(getattr(record, "methodology_choice_ref", "") or ""),
            owner=owner,
        )
        responsibility = self.responsibility(
            str(getattr(record, "responsibility_boundary_ref", "") or ""),
            owner=owner,
        )
        if responsibility.methodology_choice_ref != choice.choice_id:
            raise ValueError(
                "Mathematical Spine responsibility does not bind the cited methodology choice"
            )

        return SpineChainRecordRefs(
            mathematical_refs=tuple(sorted(mathematical)),
            implementation_refs=tuple(sorted(implementations)),
            theory_binding_refs=tuple(sorted(bindings)),
            consistency_check_refs=tuple(sorted(checks)),
            methodology_choice_refs=(choice.choice_id,),
            responsibility_refs=(responsibility.disclosure_id,),
        )

    def is_stale(
        self,
        theory_ref: str,
        current_code_source: Any,
        *,
        owner: str | None = None,
    ) -> bool | None:
        binding = self.latest_binding(theory_ref, owner=owner)
        if binding is None:
            return None
        return content_hash(current_code_source) != binding.get("code_content_hash")

    def validate_chain_backing(
        self,
        record: Any,
        *,
        owner: str,
        external_ref_resolver: Callable[[str, str, str], bool] | None,
        current_hash_resolver: Callable[[str, str, str], str | None] | None,
    ) -> SpineChainBackingDecision:
        """Resolve and revalidate a full chain against canonical current state."""

        owner = self._owner(owner)
        violations: list[SpineChainBackingViolation] = []

        def reject(code: str, field: str, ref: Any, message: str) -> None:
            violations.append(
                SpineChainBackingViolation(code, field, str(ref or ""), message)
            )

        stage_fields = (
            "data_semantics_ref",
            "factor_ref",
            "model_ref",
            "forecast_ref",
            "signal_contract_ref",
            "strategy_book_ref",
            "portfolio_policy_ref",
            "risk_policy_ref",
            "execution_policy_ref",
            "backtest_run_ref",
            "attribution_ref",
            "monitor_ref",
        )
        if str(getattr(record, "recorded_by", "") or "") != owner:
            reject(
                "mathematical_spine_owner_mismatch",
                "recorded_by",
                getattr(record, "chain_ref", ""),
                "chain owner must equal the authenticated owner",
            )
        if bool(getattr(record, "silent_mock_fallback_used", False)):
            reject(
                "mathematical_spine_silent_mock",
                "silent_mock_fallback_used",
                getattr(record, "chain_ref", ""),
                "verified Mathematical Spine chains cannot use silent mock fallback",
            )
        if external_ref_resolver is None:
            reject(
                "mathematical_spine_external_resolver_unavailable",
                "external_refs",
                "",
                "external reference resolver is required",
            )
        else:
            for field_name in stage_fields:
                ref = str(getattr(record, field_name, "") or "")
                if not ref or not external_ref_resolver(field_name, ref, owner):
                    reject(
                        "mathematical_spine_external_ref_unresolved",
                        field_name,
                        ref,
                        "full-chain stage ref is not persisted for this owner",
                    )
            for field_name in ("evidence_refs", "validation_refs"):
                for ref in tuple(getattr(record, field_name, ()) or ()):
                    if not external_ref_resolver(field_name, str(ref), owner):
                        reject(
                            "mathematical_spine_external_ref_unresolved",
                            field_name,
                            ref,
                            "evidence or validation ref is not persisted for this owner",
                        )

        bindings: dict[str, TheoryImplementationBinding] = {}
        artifacts: dict[str, MathematicalArtifact] = {}
        used_by: set[str] = set()
        for binding_ref in tuple(getattr(record, "theory_binding_refs", ()) or ()):
            try:
                binding = self.binding(str(binding_ref), owner=owner)
            except KeyError:
                reject(
                    "mathematical_spine_binding_unresolved",
                    "theory_binding_refs",
                    binding_ref,
                    "TheoryImplementationBinding is not recorded for this owner",
                )
                continue
            bindings[binding.binding_id] = binding
            try:
                theory = self.theory(binding.theory_ref, owner=owner)
            except KeyError:
                reject(
                    "mathematical_spine_theory_unresolved",
                    "theory_ref",
                    binding.theory_ref,
                    "binding theory_ref does not resolve",
                )
                continue
            if isinstance(theory, TheorySpec):
                try:
                    artifact = self.artifact(theory.artifact_ref, owner=owner)
                except KeyError:
                    reject(
                        "mathematical_spine_artifact_unresolved",
                        "artifact_ref",
                        theory.artifact_ref,
                        "TheorySpec artifact_ref does not resolve",
                    )
                    continue
            else:
                artifact = theory
            artifacts[artifact.artifact_id] = artifact
            used_by.update(str(ref) for ref in binding.used_by)
            used_by.update(str(ref) for ref in artifact.used_by)

            if not binding.implementation_ref:
                reject(
                    "mathematical_spine_implementation_unresolved",
                    "implementation_ref",
                    binding.binding_id,
                    "binding requires a canonical ImplementationSpec ref",
                )
                continue
            try:
                implementation = self.implementation_spec(
                    binding.implementation_ref, owner=owner
                )
            except KeyError:
                reject(
                    "mathematical_spine_implementation_unresolved",
                    "implementation_ref",
                    binding.implementation_ref,
                    "ImplementationSpec is not recorded for this owner",
                )
                continue
            for field_name in ("theory_ref", "code_ref", "config_ref", "data_contract_ref"):
                expected = str(getattr(implementation, field_name) or "")
                observed = str(getattr(binding, field_name) or "")
                if expected != observed:
                    reject(
                        "mathematical_spine_binding_implementation_mismatch",
                        field_name,
                        binding.binding_id,
                        "binding and ImplementationSpec refs differ",
                    )
            for kind, ref_field, hash_field in (
                ("code", "code_ref", "code_content_hash"),
                ("config", "config_ref", "config_content_hash"),
                ("data_contract", "data_contract_ref", "data_contract_content_hash"),
            ):
                bound_hash = str(getattr(binding, hash_field) or "")
                spec_hash = str(getattr(implementation, hash_field) or "")
                if not bound_hash or bound_hash != spec_hash:
                    reject(
                        "mathematical_spine_content_hash_mismatch",
                        hash_field,
                        binding.binding_id,
                        "binding hash is missing or differs from ImplementationSpec",
                    )
                    continue
                current_hash = (
                    current_hash_resolver(kind, str(getattr(binding, ref_field)), owner)
                    if current_hash_resolver is not None
                    else None
                )
                if not current_hash or current_hash != bound_hash:
                    reject(
                        "mathematical_spine_current_hash_mismatch",
                        hash_field,
                        str(getattr(binding, ref_field)),
                        "current code/config/data content hash is unavailable or stale",
                    )
            if external_ref_resolver is not None:
                for field_name in ("test_refs", "simulation_refs", "numerical_check_refs"):
                    refs = tuple(getattr(binding, field_name, ()) or ())
                    if not refs:
                        reject(
                            "mathematical_spine_validation_ref_missing",
                            field_name,
                            binding.binding_id,
                            "binding requires test/simulation/numerical refs",
                        )
                    for ref in refs:
                        if not external_ref_resolver(field_name, str(ref), owner):
                            reject(
                                "mathematical_spine_external_ref_unresolved",
                                field_name,
                                ref,
                                "binding validation ref is not persisted for this owner",
                            )

        checks_by_binding: dict[str, list[ConsistencyCheck]] = {
            binding_ref: [] for binding_ref in bindings
        }
        for check_ref in tuple(getattr(record, "consistency_check_refs", ()) or ()):
            try:
                check = self.check(str(check_ref), owner=owner)
            except KeyError:
                reject(
                    "mathematical_spine_check_unresolved",
                    "consistency_check_refs",
                    check_ref,
                    "ConsistencyCheck is not recorded for this owner",
                )
                continue
            if check.binding_id not in bindings:
                reject(
                    "mathematical_spine_check_binding_mismatch",
                    "binding_id",
                    check.check_id,
                    "ConsistencyCheck targets an uncited binding",
                )
                continue
            checks_by_binding[check.binding_id].append(check)
            if check.result != "pass":
                reject(
                    "mathematical_spine_check_not_passed",
                    "result",
                    check.check_id,
                    "verified chain requires every cited check to pass",
                )
            if not check.input_refs or not check.verifier_ref:
                reject(
                    "mathematical_spine_check_evidence_incomplete",
                    "input_refs",
                    check.check_id,
                    "ConsistencyCheck requires input refs and verifier ref",
                )
            if external_ref_resolver is not None:
                for ref in check.input_refs:
                    if not external_ref_resolver("consistency_input_refs", str(ref), owner):
                        reject(
                            "mathematical_spine_external_ref_unresolved",
                            "consistency_input_refs",
                            ref,
                            "ConsistencyCheck input ref is not persisted for this owner",
                        )
                if not external_ref_resolver(
                    "verifier_ref", str(check.verifier_ref), owner
                ):
                    reject(
                        "mathematical_spine_external_ref_unresolved",
                        "verifier_ref",
                        check.verifier_ref,
                        "ConsistencyCheck verifier ref is not persisted for this owner",
                    )
        for binding_ref, checks in checks_by_binding.items():
            if not checks:
                reject(
                    "mathematical_spine_binding_missing_check",
                    "consistency_check_refs",
                    binding_ref,
                    "every cited binding requires a cited ConsistencyCheck",
                )
                continue
            executed_check_types = {
                check.check_type for check in checks if check.result == "pass"
            }
            if not executed_check_types.intersection(
                {"numerical", "simulation", "replay"}
            ):
                reject(
                    "mathematical_spine_executed_check_missing",
                    "consistency_check_refs",
                    binding_ref,
                    "verified full chain requires a passing numerical, simulation, or replay check; property-only checks are insufficient",
                )

        for field_name in stage_fields:
            stage_ref = str(getattr(record, field_name, "") or "")
            if stage_ref and stage_ref not in used_by:
                reject(
                    "mathematical_spine_stage_not_bound",
                    field_name,
                    stage_ref,
                    "full-chain stage is not covered by artifact/binding used_by",
                )
        required_artifact_types = {
            "data_semantics_ref": {"data_timing"},
            "factor_ref": {"factor_formula"},
            "model_ref": {"loss_function", "estimator"},
            "forecast_ref": {"estimator", "statistical_test"},
            "signal_contract_ref": {"signal_transform"},
            "strategy_book_ref": {"payoff_definition"},
            "portfolio_policy_ref": {"portfolio_objective", "risk_measure"},
            "risk_policy_ref": {"risk_measure"},
            "execution_policy_ref": {"execution_cost"},
            "backtest_run_ref": {"estimator", "statistical_test"},
            "attribution_ref": {"attribution_decomposition"},
            "monitor_ref": {"monitor_trigger"},
        }
        for field_name, allowed_types in required_artifact_types.items():
            stage_ref = str(getattr(record, field_name, "") or "")
            if not any(
                artifact.artifact_type in allowed_types
                and stage_ref in artifact.used_by
                for artifact in artifacts.values()
            ):
                reject(
                    "mathematical_spine_stage_artifact_missing",
                    field_name,
                    stage_ref,
                    "full-chain stage lacks a canonical artifact of the required mathematical type",
                )
        if not any(
            artifact.artifact_type == "execution_cost"
            and str(getattr(record, "execution_policy_ref", "")) in artifact.used_by
            for artifact in artifacts.values()
        ):
            reject(
                "mathematical_spine_execution_cost_missing",
                "execution_policy_ref",
                getattr(record, "execution_policy_ref", ""),
                "execution stage requires a bound execution_cost artifact",
            )
        if not any(
            artifact.artifact_type == "monitor_trigger"
            and str(getattr(record, "monitor_ref", "")) in artifact.used_by
            for artifact in artifacts.values()
        ):
            reject(
                "mathematical_spine_monitor_trigger_missing",
                "monitor_ref",
                getattr(record, "monitor_ref", ""),
                "monitor stage requires a bound monitor_trigger artifact",
            )

        choice_ref = str(getattr(record, "methodology_choice_ref", "") or "")
        responsibility_ref = str(
            getattr(record, "responsibility_boundary_ref", "") or ""
        )
        try:
            choice = self.choice(choice_ref, owner=owner)
        except KeyError:
            reject(
                "mathematical_spine_choice_unresolved",
                "methodology_choice_ref",
                choice_ref,
                "MethodologyChoiceRecord is not recorded for this owner",
            )
            choice = None
        try:
            responsibility = self.responsibility(responsibility_ref, owner=owner)
        except KeyError:
            reject(
                "mathematical_spine_responsibility_unresolved",
                "responsibility_boundary_ref",
                responsibility_ref,
                "ResponsibilityDisclosureRecord is not recorded for this owner",
            )
            responsibility = None
        if choice is not None and responsibility is not None:
            if str(choice.actor or "") != owner:
                reject(
                    "mathematical_spine_choice_owner_mismatch",
                    "actor",
                    choice.choice_id,
                    "methodology choice actor must equal the authenticated owner",
                )
            if (
                str(responsibility.actor or "") != owner
                or str(responsibility.risk_owner or "") != owner
            ):
                reject(
                    "mathematical_spine_responsibility_owner_mismatch",
                    "actor",
                    responsibility.disclosure_id,
                    "responsibility actor and risk owner must equal the authenticated owner",
                )
            if responsibility.methodology_choice_ref != choice.choice_id:
                reject(
                    "mathematical_spine_responsibility_choice_mismatch",
                    "methodology_choice_ref",
                    responsibility.disclosure_id,
                    "responsibility disclosure does not bind the cited methodology choice",
                )
            if choice.is_waiver:
                reject(
                    "mathematical_spine_waiver_not_verified",
                    "methodology_choice_ref",
                    choice.choice_id,
                    "user-waived methodology cannot produce a verified full chain",
                )
        return SpineChainBackingDecision(
            accepted=not violations,
            violations=tuple(violations),
        )

    def verify_chain(self) -> tuple[bool, list[str]]:
        issues: list[str] = []
        try:
            rows = self._scan_mirror()
        except SpineAuditIntegrityError as exc:
            return False, [str(exc)]
        with self._lock:
            events = self._conn.execute(
                "SELECT seq, event_id, record_type, record_id, owner, payload_json, "
                "payload_hash, mirrored FROM spine_audit_events ORDER BY seq"
            ).fetchall()
            records = self._conn.execute(
                "SELECT record_type, record_id, owner, payload_json, payload_hash "
                "FROM spine_records"
            ).fetchall()
        if len(rows) != len(events):
            issues.append("SQLite audit event count differs from JSONL mirror")
        for index, event in enumerate(events):
            if not event["mirrored"]:
                issues.append(f"audit mirror pending for seq={event['seq']}")
            if index >= len(rows):
                continue
            row = rows[index]
            if (
                row["seq"] != event["seq"]
                or row["event_id"] != event["event_id"]
                or row["payload_hash"] != event["payload_hash"]
                or canonical_json(row["payload"]) != event["payload_json"]
            ):
                issues.append(f"SQLite audit event differs from mirror at seq={event['seq']}")
        event_keys = {
            (row["record_type"], row["record_id"], row["owner"], row["payload_hash"])
            for row in events
        }
        record_keys = {
            (row["record_type"], row["record_id"], row["owner"], row["payload_hash"])
            for row in records
        }
        if event_keys != record_keys:
            issues.append("SQLite canonical records differ from audit events")
        return not issues, issues

    def journal_mode(self) -> str:
        return str(self._conn.execute("PRAGMA journal_mode").fetchone()[0]).lower()

    def close(self) -> None:
        with self._lock:
            self._conn.close()


__all__ = [
    "DB_FILENAME",
    "AUDIT_HASH_VERSION",
    "CanonicalSpinePackage",
    "MIRROR_FILENAME",
    "OP_ARTIFACT",
    "OP_BINDING",
    "OP_CHECK",
    "OP_CHAIN",
    "OP_CHOICE",
    "OP_IMPLEMENTATION_SPEC",
    "OP_RESPONSIBILITY",
    "OP_THEORY_SPEC",
    "SpineAuditIntegrityError",
    "SpineChainBackingDecision",
    "SpineChainBackingViolation",
    "SpineChainRecordRefs",
    "SpineLedger",
    "SpineMirrorPendingError",
    "SpinePackageRecordRefs",
    "_artifact_payload",
    "_binding_payload",
    "_check_payload",
    "_choice_payload",
    "_implementation_spec_payload",
    "_responsibility_payload",
    "_theory_spec_payload",
]
