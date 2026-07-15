"""Canonical GOAL proof ledger.

SQLite WAL is the source of truth.  Declaration, dependency, invalidation,
current-head, and audit-outbox rows are committed in one ``BEGIN IMMEDIATE``
transaction.  The JSONL file is an append-only, hash-chained mirror which can
only be extended from committed SQLite events.

The module is deliberately product-agnostic.  Integrators provide typed
logical refs, JSON payloads, and logical dependency refs; this ledger resolves
those dependencies to exact immutable declaration events itself.
"""

from __future__ import annotations

import copy
import hashlib
import json
import math
import os
import sqlite3
import stat
import threading
from collections import OrderedDict
from contextlib import contextmanager
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, Callable, Iterable, Literal, Mapping, Sequence

from ..cross_process_lock import acquire_exclusive_fd
from ..lineage.ids import canonical_json

# current() 快照缓存的 LRU 上限:按 (owner, subject) 对计,足够覆盖单请求内的重复读,
# 又不让长驻进程无界增长。淘汰纯为控内存,命中正确性仍由 token 校验独立门控。
_SNAPSHOT_CACHE_MAXSIZE = 256


DB_FILENAME = "goal_proof_ledger.sqlite"
MIRROR_FILENAME = "goal_proof_ledger.jsonl"
MIRROR_LOCK_FILENAME = ".goal_proof_ledger_mirror.lock"
SCHEMA_VERSION = 2
MIRROR_SCHEMA_VERSION = "goal-proof-ledger-mirror-v1"
HASH_VERSION = "sha256-v1"
GENESIS_HASH = "0" * 64

EventKind = Literal["declaration", "invalidation"]
CommitStatus = Literal["committed", "idempotent"]


def _expected_meta() -> dict[str, str]:
    return {
        "schema_version": str(SCHEMA_VERSION),
        "hash_version": HASH_VERSION,
        "mirror_schema_version": MIRROR_SCHEMA_VERSION,
    }


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256(value: Any) -> str:
    return _sha256_bytes(canonical_json(value).encode("utf-8"))


def _required(value: object, *, field_name: str) -> str:
    normalized = str(value or "").strip()
    if not normalized:
        raise ValueError(f"GOAL proof {field_name} is required")
    return normalized


def _assert_json_value(value: Any, *, field_name: str) -> None:
    if value is None or isinstance(value, (str, bool, int)):
        return
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError(f"GOAL proof {field_name} must contain finite JSON numbers")
        return
    if isinstance(value, list) or isinstance(value, tuple):
        for item in value:
            _assert_json_value(item, field_name=field_name)
        return
    if isinstance(value, dict):
        for key, item in value.items():
            if not isinstance(key, str):
                raise ValueError(f"GOAL proof {field_name} keys must be strings")
            _assert_json_value(item, field_name=field_name)
        return
    raise ValueError(f"GOAL proof {field_name} must be JSON serializable")


def _json_object(value: Mapping[str, Any] | dict[str, Any], *, field_name: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise TypeError(f"GOAL proof {field_name} must be an object")
    normalized = dict(value)
    _assert_json_value(normalized, field_name=field_name)
    # Round-trip to detach caller-owned mutable values and normalize tuples.
    return json.loads(canonical_json(normalized))


def _strict_json_object(raw: str, *, field_name: str) -> dict[str, Any]:
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise GoalProofLedgerIntegrityError(
            f"GOAL proof {field_name} contains malformed JSON"
        ) from exc
    if not isinstance(value, dict):
        raise GoalProofLedgerIntegrityError(
            f"GOAL proof {field_name} must contain a JSON object"
        )
    _assert_json_value(value, field_name=field_name)
    if canonical_json(value) != raw:
        raise GoalProofLedgerIntegrityError(
            f"GOAL proof {field_name} is not canonical JSON"
        )
    return value


class GoalProofLedgerError(RuntimeError):
    """Base error for canonical GOAL proof-ledger failures."""


class GoalProofLedgerIntegrityError(GoalProofLedgerError):
    """SQLite, current-head, or JSONL state is inconsistent."""


class GoalProofConflictError(GoalProofLedgerError):
    """A logical identity, payload, owner, or dependency conflicts with history."""


class GoalProofDependencyError(GoalProofConflictError):
    """A dependency is absent or prevents an exact invalidation."""


class GoalProofMirrorPendingError(GoalProofLedgerError):
    """SQLite committed, but its append-only mirror is explicitly pending."""

    def __init__(self, operation: str, result: object, cause: BaseException) -> None:
        self.operation = operation
        self.result = result
        self.cause = cause
        super().__init__(
            f"GOAL proof {operation} committed in SQLite but audit mirror is pending: {cause}"
        )


@dataclass(frozen=True)
class ProofMember:
    logical_type: str
    logical_ref: str
    payload: Mapping[str, Any]
    depends_on: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        logical_type = _required(self.logical_type, field_name="logical_type")
        logical_ref = _required(self.logical_ref, field_name="logical_ref")
        payload = _json_object(self.payload, field_name="member payload")
        raw_dependencies = tuple(self.depends_on or ())
        dependencies = tuple(
            _required(item, field_name="dependency logical_ref")
            for item in raw_dependencies
        )
        if len(dependencies) != len(set(dependencies)):
            raise ValueError("GOAL proof member dependencies must be unique")
        if logical_ref in dependencies:
            raise ValueError("GOAL proof member cannot depend on itself")
        object.__setattr__(self, "logical_type", logical_type)
        object.__setattr__(self, "logical_ref", logical_ref)
        object.__setattr__(self, "payload", payload)
        object.__setattr__(self, "depends_on", tuple(sorted(dependencies)))

    def to_dict(self) -> dict[str, Any]:
        return {
            "logical_type": self.logical_type,
            "logical_ref": self.logical_ref,
            "payload": dict(self.payload),
            "depends_on": list(self.depends_on),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ProofMember":
        if not isinstance(value, Mapping):
            raise TypeError("GOAL proof member input must be an object")
        allowed = {"logical_type", "logical_ref", "payload", "depends_on"}
        unknown = set(value) - allowed
        if unknown:
            raise ValueError(
                "GOAL proof member input contains unknown fields: "
                + ", ".join(sorted(unknown))
            )
        return cls(
            logical_type=str(value.get("logical_type") or ""),
            logical_ref=str(value.get("logical_ref") or ""),
            payload=value.get("payload", {}),  # type: ignore[arg-type]
            depends_on=tuple(value.get("depends_on", ()) or ()),  # type: ignore[arg-type]
        )


@dataclass(frozen=True)
class ProofBundle:
    owner: str
    subject: str
    members: tuple[ProofMember, ...]
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        owner = _required(self.owner, field_name="owner")
        subject = _required(self.subject, field_name="subject")
        members = tuple(self.members or ())
        if not members:
            raise ValueError("GOAL proof bundle requires at least one member")
        if any(not isinstance(member, ProofMember) for member in members):
            raise TypeError("GOAL proof bundle members must be ProofMember values")
        logical_refs = [member.logical_ref for member in members]
        if len(logical_refs) != len(set(logical_refs)):
            raise ValueError("GOAL proof bundle logical_refs must be unique")
        metadata = _json_object(self.metadata, field_name="bundle metadata")
        object.__setattr__(self, "owner", owner)
        object.__setattr__(self, "subject", subject)
        object.__setattr__(
            self,
            "members",
            tuple(sorted(members, key=lambda member: member.logical_ref)),
        )
        object.__setattr__(self, "metadata", metadata)

    def to_dict(self) -> dict[str, Any]:
        return {
            "owner": self.owner,
            "subject": self.subject,
            "members": [member.to_dict() for member in self.members],
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ProofBundle":
        if not isinstance(value, Mapping):
            raise TypeError("GOAL proof bundle input must be an object")
        allowed = {"owner", "subject", "members", "metadata"}
        unknown = set(value) - allowed
        if unknown:
            raise ValueError(
                "GOAL proof bundle input contains unknown fields: "
                + ", ".join(sorted(unknown))
            )
        members = value.get("members")
        if not isinstance(members, list):
            raise TypeError("GOAL proof bundle input members must be an array")
        return cls(
            owner=str(value.get("owner") or ""),
            subject=str(value.get("subject") or ""),
            members=tuple(ProofMember.from_dict(item) for item in members),
            metadata=value.get("metadata", {}),  # type: ignore[arg-type]
        )


@dataclass(frozen=True)
class ProofHead:
    owner: str
    subject: str
    logical_type: str
    logical_ref: str
    generation: int
    declaration_event_id: str
    bundle_id: str
    payload_hash: str
    payload: Mapping[str, Any]
    depends_on: tuple[str, ...]
    dependency_event_ids: tuple[str, ...]
    declared_seq: int


@dataclass(frozen=True)
class ProofSnapshot:
    owner: str | None
    subject: str | None
    at_seq: int
    head_digest: str
    heads: tuple[ProofHead, ...]
    mirror_synced: bool


@dataclass(frozen=True)
class CommitResult:
    status: CommitStatus
    bundle_id: str
    owner: str
    subject: str
    heads: tuple[ProofHead, ...]
    event_seqs: tuple[int, ...]
    mirror_pending: bool = False


@dataclass(frozen=True)
class InvalidationTarget:
    logical_ref: str
    declaration_event_id: str
    generation: int

    def __post_init__(self) -> None:
        logical_ref = _required(self.logical_ref, field_name="invalidation logical_ref")
        event_id = _required(
            self.declaration_event_id,
            field_name="expected declaration_event_id",
        )
        if type(self.generation) is not int or self.generation <= 0:
            raise ValueError(
                "GOAL proof expected generation must be a positive exact integer"
            )
        object.__setattr__(self, "logical_ref", logical_ref)
        object.__setattr__(self, "declaration_event_id", event_id)

    def to_dict(self) -> dict[str, Any]:
        return {
            "logical_ref": self.logical_ref,
            "declaration_event_id": self.declaration_event_id,
            "generation": self.generation,
        }

    @classmethod
    def from_head(cls, head: ProofHead) -> "InvalidationTarget":
        if not isinstance(head, ProofHead):
            raise TypeError("GOAL proof invalidation target requires ProofHead")
        return cls(
            logical_ref=head.logical_ref,
            declaration_event_id=head.declaration_event_id,
            generation=head.generation,
        )


@dataclass(frozen=True)
class InvalidationResult:
    status: CommitStatus
    invalidation_bundle_id: str
    operation_id: str
    owner: str
    subject: str
    requested_targets: tuple[InvalidationTarget, ...]
    requested_refs: tuple[str, ...]
    affected_refs: tuple[str, ...]
    target_declaration_event_ids: tuple[str, ...]
    invalidation_event_ids: tuple[str, ...]
    event_seqs: tuple[int, ...]
    mirror_pending: bool = False


@dataclass(frozen=True)
class MirrorSyncResult:
    appended: int
    repaired_partial_tail: bool
    mirror_event_count: int
    sqlite_event_count: int


@dataclass(frozen=True)
class LedgerVerification:
    ok: bool
    issues: tuple[str, ...]
    sqlite_event_count: int
    mirror_event_count: int
    current_head_count: int
    current_digest: str


class GoalProofLedger:
    """Owner-scoped immutable proof events with an exact current projection."""

    def __init__(
        self,
        root: str | Path,
        *,
        mirror_path: str | Path | None = None,
        fault_injector: Callable[[str], None] | None = None,
    ) -> None:
        self._root = Path(root)
        self._root.mkdir(parents=True, exist_ok=True)
        self._db_path = self._root / DB_FILENAME
        self._mirror_path = (
            Path(mirror_path) if mirror_path is not None else self._root / MIRROR_FILENAME
        )
        self._lock_path = self._root / MIRROR_LOCK_FILENAME
        self._fault_injector = fault_injector
        self._lock = threading.RLock()
        # LRU 有界(原为无界 dict:每个 (owner,subject) 一条永不淘汰)。
        # 正确性不受影响:命中仍由 token 校验(cached[0]==state_token + fully_mirrored)
        # 门控,淘汰只导致重算、绝不 stale;WAL 文件状态绑定(见 _current_state_token)
        # 不碰。move_to_end 标最近用,超上限 popitem(last=False) 逐最旧。
        self._current_snapshot_cache: "OrderedDict[tuple[str | None, str | None], tuple[tuple[Any, ...], ProofSnapshot]]" = OrderedDict()
        self._current_snapshot_cache_maxsize = _SNAPSHOT_CACHE_MAXSIZE
        self._prepare_paths()
        self._initialize_database()
        self.sync()
        verification = self.verify()
        if not verification.ok:
            raise GoalProofLedgerIntegrityError("; ".join(verification.issues))

    @property
    def db_path(self) -> Path:
        return self._db_path

    @property
    def mirror_path(self) -> Path:
        return self._mirror_path

    def _fault(self, cutpoint: str) -> None:
        if self._fault_injector is not None:
            self._fault_injector(cutpoint)

    @contextmanager
    def _mirror_lock(self):
        flags = os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0)
        fd = os.open(self._lock_path, flags, 0o600)
        held = None
        try:
            info = os.fstat(fd)
            if not stat.S_ISREG(info.st_mode):
                raise GoalProofLedgerIntegrityError(
                    "GOAL proof mirror lock must be a regular file"
                )
            held = acquire_exclusive_fd(fd, timeout_seconds=30.0)
            yield
        finally:
            if held is not None:
                held.release()
            os.close(fd)

    def _prepare_paths(self) -> None:
        for directory in {self._root, self._db_path.parent, self._mirror_path.parent}:
            if os.path.lexists(directory) and directory.is_symlink():
                raise GoalProofLedgerIntegrityError(
                    f"GOAL proof storage directory must not be a symlink: {directory}"
                )
            directory.mkdir(parents=True, exist_ok=True)
        for path, label in (
            (self._db_path, "database"),
            (self._mirror_path, "mirror"),
        ):
            if not os.path.lexists(path):
                continue
            info = path.lstat()
            if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode):
                raise GoalProofLedgerIntegrityError(
                    f"GOAL proof {label} must be a regular non-symlink file"
                )

    def _connect(self) -> sqlite3.Connection:
        self._prepare_paths()
        connection = sqlite3.connect(
            str(self._db_path),
            isolation_level=None,
            timeout=30.0,
        )
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA busy_timeout=30000")
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA synchronous=FULL")
        if int(connection.execute("PRAGMA foreign_keys").fetchone()[0]) != 1:
            connection.close()
            raise GoalProofLedgerIntegrityError(
                "GOAL proof SQLite connection could not enable foreign_keys"
            )
        if int(connection.execute("PRAGMA synchronous").fetchone()[0]) != 2:
            connection.close()
            raise GoalProofLedgerIntegrityError(
                "GOAL proof SQLite connection could not enable synchronous FULL"
            )
        return connection

    def _initialize_database(self) -> None:
        # Fresh-root initialization is itself a cross-process write.  Use the
        # same global lock order as sync/verify/current so WAL setup, schema
        # creation, and meta validation cannot race in separate processes.
        with self._mirror_lock():
            with self._lock:
                connection = self._connect()
                try:
                    mode = str(
                        connection.execute("PRAGMA journal_mode=WAL").fetchone()[0]
                    ).lower()
                    if mode != "wal":
                        raise GoalProofLedgerIntegrityError(
                            f"GOAL proof SQLite requires WAL mode, got {mode!r}"
                        )
                    self._create_schema(connection)
                    connection.execute("COMMIT")
                except Exception:
                    if connection.in_transaction:
                        connection.execute("ROLLBACK")
                    raise
                finally:
                    connection.close()

    @staticmethod
    def _create_schema(connection: sqlite3.Connection) -> None:
        connection.executescript(
            """
            BEGIN IMMEDIATE;
            CREATE TABLE IF NOT EXISTS goal_proof_meta (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS goal_proof_events (
                seq INTEGER PRIMARY KEY AUTOINCREMENT,
                event_id TEXT NOT NULL UNIQUE,
                event_kind TEXT NOT NULL CHECK(event_kind IN (
                    'declaration','invalidation'
                )),
                owner TEXT NOT NULL,
                subject TEXT NOT NULL,
                bundle_id TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                payload_hash TEXT NOT NULL,
                mirrored INTEGER NOT NULL DEFAULT 0 CHECK(mirrored IN (0,1))
            );
            CREATE TABLE IF NOT EXISTS goal_proof_bundles (
                bundle_id TEXT PRIMARY KEY,
                request_fingerprint TEXT NOT NULL,
                owner TEXT NOT NULL,
                subject TEXT NOT NULL,
                metadata_json TEXT NOT NULL,
                metadata_hash TEXT NOT NULL,
                members_json TEXT NOT NULL,
                generations_json TEXT NOT NULL,
                first_event_seq INTEGER NOT NULL,
                last_event_seq INTEGER NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_goal_proof_bundle_retry
                ON goal_proof_bundles(owner, request_fingerprint, last_event_seq);
            CREATE TABLE IF NOT EXISTS goal_proof_declarations (
                declaration_event_id TEXT PRIMARY KEY,
                bundle_id TEXT NOT NULL,
                owner TEXT NOT NULL,
                subject TEXT NOT NULL,
                logical_type TEXT NOT NULL,
                logical_ref TEXT NOT NULL,
                generation INTEGER NOT NULL CHECK(generation > 0),
                member_payload_json TEXT NOT NULL,
                member_payload_hash TEXT NOT NULL,
                depends_on_json TEXT NOT NULL,
                dependency_event_ids_json TEXT NOT NULL,
                declared_seq INTEGER NOT NULL UNIQUE,
                invalidated_by_event_id TEXT,
                UNIQUE(owner, logical_ref, generation),
                FOREIGN KEY(declaration_event_id)
                    REFERENCES goal_proof_events(event_id),
                FOREIGN KEY(bundle_id) REFERENCES goal_proof_bundles(bundle_id),
                FOREIGN KEY(invalidated_by_event_id)
                    REFERENCES goal_proof_events(event_id)
            );
            CREATE INDEX IF NOT EXISTS idx_goal_proof_declaration_history
                ON goal_proof_declarations(owner, logical_ref, generation);
            CREATE TABLE IF NOT EXISTS goal_proof_dependency_edges (
                owner TEXT NOT NULL,
                declaration_event_id TEXT NOT NULL,
                dependency_logical_ref TEXT NOT NULL,
                dependency_event_id TEXT NOT NULL,
                PRIMARY KEY(declaration_event_id, dependency_logical_ref),
                FOREIGN KEY(declaration_event_id)
                    REFERENCES goal_proof_declarations(declaration_event_id),
                FOREIGN KEY(dependency_event_id)
                    REFERENCES goal_proof_declarations(declaration_event_id)
            );
            CREATE INDEX IF NOT EXISTS idx_goal_proof_dependency_inbound
                ON goal_proof_dependency_edges(owner, dependency_event_id);
            CREATE TABLE IF NOT EXISTS goal_proof_current_heads (
                owner TEXT NOT NULL,
                logical_ref TEXT NOT NULL,
                declaration_event_id TEXT NOT NULL UNIQUE,
                subject TEXT NOT NULL,
                logical_type TEXT NOT NULL,
                generation INTEGER NOT NULL CHECK(generation > 0),
                bundle_id TEXT NOT NULL,
                payload_hash TEXT NOT NULL,
                declared_seq INTEGER NOT NULL,
                PRIMARY KEY(owner, logical_ref),
                FOREIGN KEY(declaration_event_id)
                    REFERENCES goal_proof_declarations(declaration_event_id),
                FOREIGN KEY(bundle_id) REFERENCES goal_proof_bundles(bundle_id)
            );
            CREATE TABLE IF NOT EXISTS goal_proof_invalidation_bundles (
                invalidation_bundle_id TEXT PRIMARY KEY,
                request_fingerprint TEXT NOT NULL,
                owner TEXT NOT NULL,
                operation_id TEXT NOT NULL,
                subject TEXT NOT NULL,
                request_subject TEXT,
                requested_targets_json TEXT NOT NULL,
                requested_refs_json TEXT NOT NULL,
                affected_refs_json TEXT NOT NULL,
                reason TEXT NOT NULL,
                metadata_json TEXT NOT NULL,
                metadata_hash TEXT NOT NULL,
                first_event_seq INTEGER NOT NULL,
                last_event_seq INTEGER NOT NULL,
                UNIQUE(owner, operation_id)
            );
            CREATE INDEX IF NOT EXISTS idx_goal_proof_invalidation_retry
                ON goal_proof_invalidation_bundles(
                    owner, request_fingerprint, last_event_seq
                );
            CREATE TABLE IF NOT EXISTS goal_proof_invalidations (
                invalidation_event_id TEXT PRIMARY KEY,
                invalidation_bundle_id TEXT NOT NULL,
                target_declaration_event_id TEXT NOT NULL UNIQUE,
                owner TEXT NOT NULL,
                subject TEXT NOT NULL,
                logical_ref TEXT NOT NULL,
                generation INTEGER NOT NULL CHECK(generation > 0),
                reason TEXT NOT NULL,
                metadata_json TEXT NOT NULL,
                invalidated_seq INTEGER NOT NULL UNIQUE,
                FOREIGN KEY(invalidation_event_id)
                    REFERENCES goal_proof_events(event_id),
                FOREIGN KEY(invalidation_bundle_id)
                    REFERENCES goal_proof_invalidation_bundles(invalidation_bundle_id),
                FOREIGN KEY(target_declaration_event_id)
                    REFERENCES goal_proof_declarations(declaration_event_id)
            );
            """
        )
        for key, value in _expected_meta().items():
            row = connection.execute(
                "SELECT value FROM goal_proof_meta WHERE key=?", (key,)
            ).fetchone()
            if row is None:
                connection.execute(
                    "INSERT INTO goal_proof_meta(key,value) VALUES (?,?)",
                    (key, value),
                )
            elif str(row["value"]) != value:
                raise GoalProofLedgerIntegrityError(
                    f"unsupported GOAL proof {key}={row['value']!r}"
                )

    @staticmethod
    def _bundle_request(bundle: ProofBundle) -> dict[str, Any]:
        return bundle.to_dict()

    @classmethod
    def _bundle_request_fingerprint(cls, bundle: ProofBundle) -> str:
        return _sha256({"kind": "goal_proof_bundle_request", **cls._bundle_request(bundle)})

    @staticmethod
    def _bundle_id(
        *, request_fingerprint: str, generations: Mapping[str, int]
    ) -> str:
        return "goal_proof_bundle_sha256_" + _sha256(
            {
                "kind": "goal_proof_bundle",
                "request_fingerprint": request_fingerprint,
                "generations": dict(sorted(generations.items())),
            }
        )

    @staticmethod
    def _declaration_event_identity(payload: Mapping[str, Any]) -> dict[str, Any]:
        return {
            key: payload[key]
            for key in (
                "event_kind",
                "owner",
                "subject",
                "bundle_id",
                "logical_type",
                "logical_ref",
                "generation",
                "member_payload_hash",
                "depends_on",
            )
        }

    @classmethod
    def _declaration_event_id(cls, payload: Mapping[str, Any]) -> str:
        return "goal_proof_declaration_sha256_" + _sha256(
            cls._declaration_event_identity(payload)
        )

    @staticmethod
    def _invalidation_event_id(payload: Mapping[str, Any]) -> str:
        return "goal_proof_invalidation_sha256_" + _sha256(payload)

    @staticmethod
    def _insert_event(
        connection: sqlite3.Connection,
        *,
        event_id: str,
        event_kind: EventKind,
        owner: str,
        subject: str,
        bundle_id: str,
        payload: Mapping[str, Any],
    ) -> int:
        payload_json = canonical_json(payload)
        payload_hash = _sha256(payload)
        cursor = connection.execute(
            "INSERT INTO goal_proof_events("
            "event_id,event_kind,owner,subject,bundle_id,payload_json,payload_hash"
            ") VALUES (?,?,?,?,?,?,?)",
            (
                event_id,
                event_kind,
                owner,
                subject,
                bundle_id,
                payload_json,
                payload_hash,
            ),
        )
        return int(cursor.lastrowid)

    @staticmethod
    def _head_from_row(row: sqlite3.Row) -> ProofHead:
        return ProofHead(
            owner=str(row["owner"]),
            subject=str(row["subject"]),
            logical_type=str(row["logical_type"]),
            logical_ref=str(row["logical_ref"]),
            generation=int(row["generation"]),
            declaration_event_id=str(row["declaration_event_id"]),
            bundle_id=str(row["bundle_id"]),
            payload_hash=str(row["member_payload_hash"]),
            payload=_strict_json_object(
                str(row["member_payload_json"]), field_name="member payload"
            ),
            depends_on=tuple(json.loads(str(row["depends_on_json"]))),
            dependency_event_ids=tuple(
                json.loads(str(row["dependency_event_ids_json"]))
            ),
            declared_seq=int(row["declared_seq"]),
        )

    @staticmethod
    def _current_head_rows(
        connection: sqlite3.Connection,
        *,
        owner: str | None = None,
        subject: str | None = None,
        logical_refs: Sequence[str] | None = None,
    ) -> list[sqlite3.Row]:
        sql = (
            "SELECT d.*,"
            "h.owner AS head_owner,"
            "h.logical_ref AS head_logical_ref,"
            "h.declaration_event_id AS head_declaration_event_id,"
            "h.subject AS head_subject,"
            "h.logical_type AS head_logical_type,"
            "h.generation AS head_generation,"
            "h.bundle_id AS head_bundle_id,"
            "h.payload_hash AS head_payload_hash,"
            "h.declared_seq AS head_declared_seq "
            "FROM goal_proof_current_heads h "
            "JOIN goal_proof_declarations d "
            "ON d.declaration_event_id=h.declaration_event_id WHERE 1=1"
        )
        params: list[Any] = []
        if owner is not None:
            sql += " AND h.owner=?"
            params.append(owner)
        if subject is not None:
            sql += " AND h.subject=?"
            params.append(subject)
        if logical_refs is not None:
            if not logical_refs:
                return []
            sql += " AND h.logical_ref IN (" + ",".join("?" for _ in logical_refs) + ")"
            params.extend(logical_refs)
        sql += " ORDER BY h.owner,h.logical_ref"
        return connection.execute(sql, tuple(params)).fetchall()

    @classmethod
    def _result_for_bundle(
        cls,
        connection: sqlite3.Connection,
        *,
        bundle_id: str,
        status: CommitStatus,
    ) -> CommitResult:
        bundle_row = connection.execute(
            "SELECT * FROM goal_proof_bundles WHERE bundle_id=?", (bundle_id,)
        ).fetchone()
        if bundle_row is None:
            raise GoalProofLedgerIntegrityError("GOAL proof bundle disappeared")
        rows = connection.execute(
            "SELECT * FROM goal_proof_declarations WHERE bundle_id=? "
            "ORDER BY logical_ref",
            (bundle_id,),
        ).fetchall()
        return CommitResult(
            status=status,
            bundle_id=bundle_id,
            owner=str(bundle_row["owner"]),
            subject=str(bundle_row["subject"]),
            heads=tuple(cls._head_from_row(row) for row in rows),
            event_seqs=tuple(int(row["declared_seq"]) for row in rows),
        )

    def _commit_bundle_tx(
        self, connection: sqlite3.Connection, bundle: ProofBundle
    ) -> CommitResult:
        request_fingerprint = self._bundle_request_fingerprint(bundle)
        member_refs = tuple(member.logical_ref for member in bundle.members)
        current_rows = self._current_head_rows(
            connection, owner=bundle.owner, logical_refs=member_refs
        )
        if current_rows:
            current_by_ref = {str(row["logical_ref"]): row for row in current_rows}
            if set(current_by_ref) != set(member_refs):
                raise GoalProofConflictError(
                    "GOAL proof bundle overlaps current logical refs; exact partial retry is forbidden"
                )
            bundle_ids = {str(row["bundle_id"]) for row in current_rows}
            if len(bundle_ids) == 1:
                existing_bundle_id = next(iter(bundle_ids))
                existing = connection.execute(
                    "SELECT request_fingerprint FROM goal_proof_bundles WHERE bundle_id=?",
                    (existing_bundle_id,),
                ).fetchone()
                if (
                    existing is not None
                    and str(existing["request_fingerprint"]) == request_fingerprint
                ):
                    return self._result_for_bundle(
                        connection,
                        bundle_id=existing_bundle_id,
                        status="idempotent",
                    )
            raise GoalProofConflictError(
                "GOAL proof logical ref is current with a different payload, bundle, or event; "
                "invalidate it before re-declaration"
            )

        generations: dict[str, int] = {}
        for member in bundle.members:
            history = connection.execute(
                "SELECT logical_type,subject,generation FROM goal_proof_declarations "
                "WHERE owner=? AND logical_ref=? ORDER BY generation",
                (bundle.owner, member.logical_ref),
            ).fetchall()
            if history:
                if any(
                    str(row["logical_type"]) != member.logical_type
                    or str(row["subject"]) != bundle.subject
                    for row in history
                ):
                    raise GoalProofConflictError(
                        "GOAL proof logical identity cannot change owner, subject, or logical_type"
                    )
                generations[member.logical_ref] = int(history[-1]["generation"]) + 1
            else:
                generations[member.logical_ref] = 1

        bundle_id = self._bundle_id(
            request_fingerprint=request_fingerprint, generations=generations
        )
        metadata_json = canonical_json(bundle.metadata)
        members_json = canonical_json(
            [member.to_dict() for member in bundle.members]
        )
        generations_json = canonical_json(dict(sorted(generations.items())))

        identity_payloads: dict[str, dict[str, Any]] = {}
        declaration_event_ids: dict[str, str] = {}
        for member in bundle.members:
            member_payload_hash = _sha256(member.payload)
            identity_payload = {
                "event_kind": "declaration",
                "owner": bundle.owner,
                "subject": bundle.subject,
                "bundle_id": bundle_id,
                "logical_type": member.logical_type,
                "logical_ref": member.logical_ref,
                "generation": generations[member.logical_ref],
                "member_payload_hash": member_payload_hash,
                "depends_on": list(member.depends_on),
            }
            identity_payloads[member.logical_ref] = identity_payload
            declaration_event_ids[member.logical_ref] = self._declaration_event_id(
                identity_payload
            )

        dependency_events: dict[str, dict[str, str]] = {}
        bundle_ref_set = set(member_refs)
        for member in bundle.members:
            resolved: dict[str, str] = {}
            for dependency_ref in member.depends_on:
                if dependency_ref in bundle_ref_set:
                    resolved[dependency_ref] = declaration_event_ids[dependency_ref]
                    continue
                row = connection.execute(
                    "SELECT declaration_event_id FROM goal_proof_current_heads "
                    "WHERE owner=? AND logical_ref=?",
                    (bundle.owner, dependency_ref),
                ).fetchone()
                if row is None:
                    raise GoalProofDependencyError(
                        f"GOAL proof dependency {dependency_ref!r} is not current for owner"
                    )
                resolved[dependency_ref] = str(row["declaration_event_id"])
            dependency_events[member.logical_ref] = dict(sorted(resolved.items()))

        connection.execute(
            "INSERT INTO goal_proof_bundles("
            "bundle_id,request_fingerprint,owner,subject,metadata_json,metadata_hash,"
            "members_json,generations_json,first_event_seq,last_event_seq"
            ") VALUES (?,?,?,?,?,?,?,?,0,0)",
            (
                bundle_id,
                request_fingerprint,
                bundle.owner,
                bundle.subject,
                metadata_json,
                _sha256(bundle.metadata),
                members_json,
                generations_json,
            ),
        )

        declaration_rows: list[tuple[ProofMember, str, dict[str, Any], int]] = []
        for member in bundle.members:
            dependency_map = dependency_events[member.logical_ref]
            event_payload = {
                **identity_payloads[member.logical_ref],
                "member_payload": dict(member.payload),
                "dependency_event_ids": dependency_map,
                "bundle_metadata_hash": _sha256(bundle.metadata),
            }
            event_id = declaration_event_ids[member.logical_ref]
            seq = self._insert_event(
                connection,
                event_id=event_id,
                event_kind="declaration",
                owner=bundle.owner,
                subject=bundle.subject,
                bundle_id=bundle_id,
                payload=event_payload,
            )
            connection.execute(
                "INSERT INTO goal_proof_declarations("
                "declaration_event_id,bundle_id,owner,subject,logical_type,logical_ref,"
                "generation,member_payload_json,member_payload_hash,depends_on_json,"
                "dependency_event_ids_json,declared_seq"
                ") VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    event_id,
                    bundle_id,
                    bundle.owner,
                    bundle.subject,
                    member.logical_type,
                    member.logical_ref,
                    generations[member.logical_ref],
                    canonical_json(member.payload),
                    _sha256(member.payload),
                    canonical_json(list(member.depends_on)),
                    canonical_json(list(dependency_map.values())),
                    seq,
                ),
            )
            declaration_rows.append((member, event_id, event_payload, seq))

        for member, event_id, _event_payload, seq in declaration_rows:
            dependency_map = dependency_events[member.logical_ref]
            for dependency_ref, dependency_event_id in dependency_map.items():
                connection.execute(
                    "INSERT INTO goal_proof_dependency_edges("
                    "owner,declaration_event_id,dependency_logical_ref,dependency_event_id"
                    ") VALUES (?,?,?,?)",
                    (
                        bundle.owner,
                        event_id,
                        dependency_ref,
                        dependency_event_id,
                    ),
                )
            connection.execute(
                "INSERT INTO goal_proof_current_heads("
                "owner,logical_ref,declaration_event_id,subject,logical_type,generation,"
                "bundle_id,payload_hash,declared_seq"
                ") VALUES (?,?,?,?,?,?,?,?,?)",
                (
                    bundle.owner,
                    member.logical_ref,
                    event_id,
                    bundle.subject,
                    member.logical_type,
                    generations[member.logical_ref],
                    bundle_id,
                    _sha256(member.payload),
                    seq,
                ),
            )

        event_seqs = [seq for _member, _event_id, _payload, seq in declaration_rows]
        connection.execute(
            "UPDATE goal_proof_bundles SET first_event_seq=?,last_event_seq=? "
            "WHERE bundle_id=?",
            (min(event_seqs), max(event_seqs), bundle_id),
        )
        return self._result_for_bundle(
            connection, bundle_id=bundle_id, status="committed"
        )

    def commit(self, bundle: ProofBundle) -> CommitResult:
        if not isinstance(bundle, ProofBundle):
            raise TypeError("GOAL proof commit requires ProofBundle")
        self.sync()
        self._fault("after_preflight_sync")
        with self._lock:
            connection = self._connect()
            try:
                connection.execute("BEGIN IMMEDIATE")
                integrity_issues, _heads, _event_count = self._verify_sqlite(connection)
                if integrity_issues:
                    raise GoalProofLedgerIntegrityError("; ".join(integrity_issues))
                result = self._commit_bundle_tx(connection, bundle)
                self._fault("before_sqlite_commit")
                connection.execute("COMMIT")
            except Exception:
                if connection.in_transaction:
                    connection.execute("ROLLBACK")
                raise
            finally:
                connection.close()
        try:
            if result.status == "committed":
                self._fault("after_sqlite_commit")
            self.sync()
        except Exception as exc:
            pending = replace(result, mirror_pending=True)
            raise GoalProofMirrorPendingError("commit", pending, exc) from exc
        return result

    @staticmethod
    def _invalidation_request_fingerprint(
        *,
        owner: str,
        operation_id: str,
        requested_targets: Sequence[InvalidationTarget],
        reason: str,
        metadata: Mapping[str, Any],
        subject: str | None,
    ) -> str:
        return _sha256(
            {
                "kind": "goal_proof_invalidation_request",
                "owner": owner,
                "operation_id": operation_id,
                "requested_targets": [
                    target.to_dict() for target in requested_targets
                ],
                "reason": reason,
                "metadata": dict(metadata),
                "subject": subject,
            }
        )

    @staticmethod
    def _invalidation_bundle_id(
        *, request_fingerprint: str, target_event_ids: Sequence[str]
    ) -> str:
        return "goal_proof_invalidation_bundle_sha256_" + _sha256(
            {
                "kind": "goal_proof_invalidation_bundle",
                "request_fingerprint": request_fingerprint,
                "target_declaration_event_ids": list(target_event_ids),
            }
        )

    @classmethod
    def _invalidation_result(
        cls,
        connection: sqlite3.Connection,
        *,
        invalidation_bundle_id: str,
        status: CommitStatus,
    ) -> InvalidationResult:
        bundle = connection.execute(
            "SELECT * FROM goal_proof_invalidation_bundles "
            "WHERE invalidation_bundle_id=?",
            (invalidation_bundle_id,),
        ).fetchone()
        if bundle is None:
            raise GoalProofLedgerIntegrityError("GOAL proof invalidation bundle disappeared")
        rows = connection.execute(
            "SELECT * FROM goal_proof_invalidations "
            "WHERE invalidation_bundle_id=? ORDER BY logical_ref",
            (invalidation_bundle_id,),
        ).fetchall()
        return InvalidationResult(
            status=status,
            invalidation_bundle_id=invalidation_bundle_id,
            operation_id=str(bundle["operation_id"]),
            owner=str(bundle["owner"]),
            subject=str(bundle["subject"]),
            requested_targets=tuple(
                InvalidationTarget(**value)
                for value in json.loads(str(bundle["requested_targets_json"]))
            ),
            requested_refs=tuple(json.loads(str(bundle["requested_refs_json"]))),
            affected_refs=tuple(json.loads(str(bundle["affected_refs_json"]))),
            target_declaration_event_ids=tuple(
                str(row["target_declaration_event_id"]) for row in rows
            ),
            invalidation_event_ids=tuple(
                str(row["invalidation_event_id"]) for row in rows
            ),
            event_seqs=tuple(int(row["invalidated_seq"]) for row in rows),
        )

    def _invalidate_tx(
        self,
        connection: sqlite3.Connection,
        *,
        owner: str,
        operation_id: str,
        requested_targets: tuple[InvalidationTarget, ...],
        reason: str,
        metadata: Mapping[str, Any],
        subject: str | None,
    ) -> InvalidationResult:
        requested_refs = tuple(target.logical_ref for target in requested_targets)
        request_fingerprint = self._invalidation_request_fingerprint(
            owner=owner,
            operation_id=operation_id,
            requested_targets=requested_targets,
            reason=reason,
            metadata=metadata,
            subject=subject,
        )
        prior = connection.execute(
            "SELECT invalidation_bundle_id,request_fingerprint "
            "FROM goal_proof_invalidation_bundles "
            "WHERE owner=? AND operation_id=?",
            (owner, operation_id),
        ).fetchone()
        if prior is not None:
            if str(prior["request_fingerprint"]) != request_fingerprint:
                raise GoalProofConflictError(
                    "GOAL proof invalidation operation identity was reused "
                    "with a different request"
                )
            return self._invalidation_result(
                connection,
                invalidation_bundle_id=str(prior["invalidation_bundle_id"]),
                status="idempotent",
            )

        requested_rows = self._current_head_rows(
            connection, owner=owner, logical_refs=requested_refs
        )
        requested_current = {str(row["logical_ref"]): row for row in requested_rows}
        if set(requested_current) != set(requested_refs):
            missing = sorted(set(requested_refs) - set(requested_current))
            raise GoalProofConflictError(
                "GOAL proof invalidation targets are not all current: "
                + ", ".join(missing)
            )
        stale_targets = [
            target.logical_ref
            for target in requested_targets
            if (
                str(requested_current[target.logical_ref]["declaration_event_id"])
                != target.declaration_event_id
                or int(requested_current[target.logical_ref]["generation"])
                != target.generation
            )
        ]
        if stale_targets:
            raise GoalProofConflictError(
                "GOAL proof invalidation expected targets are stale: "
                + ", ".join(stale_targets)
            )

        all_rows = self._current_head_rows(connection, owner=owner)
        by_ref = {str(row["logical_ref"]): row for row in all_rows}
        adjacency: dict[str, set[str]] = {logical_ref: set() for logical_ref in by_ref}
        event_to_ref = {
            str(row["declaration_event_id"]): logical_ref
            for logical_ref, row in by_ref.items()
        }
        if event_to_ref:
            placeholders = ",".join("?" for _ in event_to_ref)
            edges = connection.execute(
                "SELECT declaration_event_id,dependency_event_id "
                "FROM goal_proof_dependency_edges WHERE owner=? "
                f"AND declaration_event_id IN ({placeholders})",
                (owner, *event_to_ref.keys()),
            ).fetchall()
            for edge in edges:
                source = event_to_ref.get(str(edge["declaration_event_id"]))
                target = event_to_ref.get(str(edge["dependency_event_id"]))
                if source is not None and target is not None:
                    adjacency[source].add(target)

        # Invalidation is bundle-generation exact, not caller-selected and not
        # merely graph-SCC exact.  A committed bundle is the atomic proof unit;
        # leaving any acyclic sibling current would create a projection that
        # never existed in the source transaction.
        requested_bundle_ids = {
            str(row["bundle_id"]) for row in requested_current.values()
        }
        affected = {
            logical_ref
            for logical_ref, row in by_ref.items()
            if str(row["bundle_id"]) in requested_bundle_ids
        }
        for bundle_id in requested_bundle_ids:
            persisted_refs = {
                str(row["logical_ref"])
                for row in connection.execute(
                    "SELECT logical_ref FROM goal_proof_declarations WHERE bundle_id=?",
                    (bundle_id,),
                ).fetchall()
            }
            current_bundle_refs = {
                logical_ref
                for logical_ref, row in by_ref.items()
                if str(row["bundle_id"]) == bundle_id
            }
            if persisted_refs != current_bundle_refs:
                raise GoalProofLedgerIntegrityError(
                    "GOAL proof bundle has a partial current projection"
                )

        inbound = sorted(
            source
            for source, dependencies in adjacency.items()
            if source not in affected and dependencies.intersection(affected)
        )
        if inbound:
            raise GoalProofDependencyError(
                "GOAL proof invalidation refused because current external dependents exist: "
                + ", ".join(inbound)
            )

        affected_refs = tuple(sorted(affected))
        affected_rows = [by_ref[logical_ref] for logical_ref in affected_refs]
        subjects = {str(row["subject"]) for row in affected_rows}
        if len(subjects) != 1:
            raise GoalProofConflictError(
                "GOAL proof invalidation bundle cannot span subjects"
            )
        resolved_subject = next(iter(subjects))
        if subject is not None and subject != resolved_subject:
            raise GoalProofConflictError(
                "GOAL proof invalidation subject does not match current declaration"
            )
        target_event_ids = tuple(
            str(row["declaration_event_id"]) for row in affected_rows
        )
        invalidation_bundle_id = self._invalidation_bundle_id(
            request_fingerprint=request_fingerprint,
            target_event_ids=target_event_ids,
        )
        metadata_json = canonical_json(metadata)
        connection.execute(
            "INSERT INTO goal_proof_invalidation_bundles("
            "invalidation_bundle_id,request_fingerprint,owner,operation_id,subject,"
            "request_subject,requested_targets_json,requested_refs_json,"
            "affected_refs_json,reason,metadata_json,metadata_hash,first_event_seq,last_event_seq"
            ") VALUES (?,?,?,?,?,?,?,?,?,?,?,?,0,0)",
            (
                invalidation_bundle_id,
                request_fingerprint,
                owner,
                operation_id,
                resolved_subject,
                subject,
                canonical_json(
                    [target.to_dict() for target in requested_targets]
                ),
                canonical_json(list(requested_refs)),
                canonical_json(list(affected_refs)),
                reason,
                metadata_json,
                _sha256(metadata),
            ),
        )
        event_seqs: list[int] = []
        for row in affected_rows:
            payload = {
                "event_kind": "invalidation",
                "owner": owner,
                "subject": resolved_subject,
                "invalidation_bundle_id": invalidation_bundle_id,
                "operation_id": operation_id,
                "requested_targets": [
                    target.to_dict() for target in requested_targets
                ],
                "requested_refs": list(requested_refs),
                "affected_refs": list(affected_refs),
                "target_declaration_event_id": str(row["declaration_event_id"]),
                "logical_ref": str(row["logical_ref"]),
                "generation": int(row["generation"]),
                "reason": reason,
                "metadata": dict(metadata),
            }
            event_id = self._invalidation_event_id(payload)
            seq = self._insert_event(
                connection,
                event_id=event_id,
                event_kind="invalidation",
                owner=owner,
                subject=resolved_subject,
                bundle_id=invalidation_bundle_id,
                payload=payload,
            )
            connection.execute(
                "INSERT INTO goal_proof_invalidations("
                "invalidation_event_id,invalidation_bundle_id,target_declaration_event_id,"
                "owner,subject,logical_ref,generation,reason,metadata_json,invalidated_seq"
                ") VALUES (?,?,?,?,?,?,?,?,?,?)",
                (
                    event_id,
                    invalidation_bundle_id,
                    row["declaration_event_id"],
                    owner,
                    resolved_subject,
                    row["logical_ref"],
                    row["generation"],
                    reason,
                    metadata_json,
                    seq,
                ),
            )
            updated = connection.execute(
                "UPDATE goal_proof_declarations SET invalidated_by_event_id=? "
                "WHERE declaration_event_id=? AND invalidated_by_event_id IS NULL",
                (event_id, row["declaration_event_id"]),
            )
            if updated.rowcount != 1:
                raise GoalProofConflictError(
                    "GOAL proof declaration was already invalidated"
                )
            deleted = connection.execute(
                "DELETE FROM goal_proof_current_heads "
                "WHERE declaration_event_id=?",
                (row["declaration_event_id"],),
            )
            if deleted.rowcount != 1:
                raise GoalProofLedgerIntegrityError(
                    "GOAL proof current head disappeared during invalidation"
                )
            event_seqs.append(seq)
        connection.execute(
            "UPDATE goal_proof_invalidation_bundles "
            "SET first_event_seq=?,last_event_seq=? WHERE invalidation_bundle_id=?",
            (min(event_seqs), max(event_seqs), invalidation_bundle_id),
        )
        return self._invalidation_result(
            connection,
            invalidation_bundle_id=invalidation_bundle_id,
            status="committed",
        )

    def invalidate(
        self,
        *,
        owner: str,
        operation_id: str,
        targets: Iterable[InvalidationTarget],
        reason: str,
        metadata: Mapping[str, Any] | None = None,
        subject: str | None = None,
    ) -> InvalidationResult:
        normalized_owner = _required(owner, field_name="owner")
        normalized_operation_id = _required(
            operation_id, field_name="invalidation operation_id"
        )
        raw_targets = tuple(targets)
        if not raw_targets:
            raise ValueError("GOAL proof invalidation requires at least one target")
        if any(not isinstance(target, InvalidationTarget) for target in raw_targets):
            raise TypeError(
                "GOAL proof invalidation targets must be InvalidationTarget values"
            )
        requested_targets = tuple(
            sorted(raw_targets, key=lambda target: target.logical_ref)
        )
        requested_refs = tuple(target.logical_ref for target in requested_targets)
        requested_event_ids = tuple(
            target.declaration_event_id for target in requested_targets
        )
        if len(requested_refs) != len(set(requested_refs)):
            raise ValueError(
                "GOAL proof invalidation target logical_refs must be unique"
            )
        if len(requested_event_ids) != len(set(requested_event_ids)):
            raise ValueError(
                "GOAL proof invalidation target declaration_event_ids must be unique"
            )
        normalized_reason = _required(reason, field_name="invalidation reason")
        normalized_metadata = _json_object(
            metadata or {}, field_name="invalidation metadata"
        )
        normalized_subject = (
            _required(subject, field_name="subject") if subject is not None else None
        )
        self.sync()
        self._fault("after_preflight_sync")
        with self._lock:
            connection = self._connect()
            try:
                connection.execute("BEGIN IMMEDIATE")
                integrity_issues, _heads, _event_count = self._verify_sqlite(connection)
                if integrity_issues:
                    raise GoalProofLedgerIntegrityError("; ".join(integrity_issues))
                result = self._invalidate_tx(
                    connection,
                    owner=normalized_owner,
                    operation_id=normalized_operation_id,
                    requested_targets=requested_targets,
                    reason=normalized_reason,
                    metadata=normalized_metadata,
                    subject=normalized_subject,
                )
                self._fault("before_sqlite_commit")
                connection.execute("COMMIT")
            except Exception:
                if connection.in_transaction:
                    connection.execute("ROLLBACK")
                raise
            finally:
                connection.close()
        try:
            if result.status == "committed":
                self._fault("after_sqlite_commit")
            self.sync()
        except Exception as exc:
            pending = replace(result, mirror_pending=True)
            raise GoalProofMirrorPendingError("invalidation", pending, exc) from exc
        return result

    @classmethod
    def _mirror_row(cls, event: sqlite3.Row, *, prev_hash: str) -> dict[str, Any]:
        payload = _strict_json_object(
            str(event["payload_json"]), field_name="event payload"
        )
        seq = int(event["seq"])
        kind = str(event["event_kind"])
        if payload.get("event_kind") != kind:
            raise GoalProofLedgerIntegrityError(
                f"GOAL proof event kind mismatch at seq={seq}"
            )
        if _sha256(payload) != str(event["payload_hash"]):
            raise GoalProofLedgerIntegrityError(
                f"GOAL proof event payload hash mismatch at seq={seq}"
            )
        try:
            if kind == "declaration":
                expected_event_id = cls._declaration_event_id(payload)
                expected_bundle_id = str(payload["bundle_id"])
            elif kind == "invalidation":
                expected_event_id = cls._invalidation_event_id(payload)
                expected_bundle_id = str(payload["invalidation_bundle_id"])
            else:
                raise GoalProofLedgerIntegrityError(
                    f"GOAL proof event kind is unsupported at seq={seq}"
                )
        except (KeyError, TypeError, ValueError) as exc:
            raise GoalProofLedgerIntegrityError(
                f"GOAL proof event identity is invalid at seq={seq}"
            ) from exc
        if expected_event_id != str(event["event_id"]):
            raise GoalProofLedgerIntegrityError(
                f"GOAL proof event identity mismatch at seq={seq}"
            )
        if (
            str(payload.get("owner", "")) != str(event["owner"])
            or str(payload.get("subject", "")) != str(event["subject"])
            or expected_bundle_id != str(event["bundle_id"])
        ):
            raise GoalProofLedgerIntegrityError(
                f"GOAL proof event owner, subject, or bundle mismatch at seq={seq}"
            )
        row = {
            "schema_version": MIRROR_SCHEMA_VERSION,
            "seq": seq,
            "prev_hash": prev_hash,
            "event_id": str(event["event_id"]),
            "event_kind": str(event["event_kind"]),
            "owner": str(event["owner"]),
            "subject": str(event["subject"]),
            "bundle_id": str(event["bundle_id"]),
            "payload_hash": str(event["payload_hash"]),
            "payload": payload,
        }
        row["row_hash"] = _sha256(row)
        return row

    @staticmethod
    def _mirror_line(row: Mapping[str, Any]) -> bytes:
        return (canonical_json(row) + "\n").encode("utf-8")

    @staticmethod
    def _fsync_directory(directory: Path) -> None:
        flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
        try:
            fd = os.open(directory, flags)
        except OSError:
            return
        try:
            os.fsync(fd)
        finally:
            os.close(fd)

    def _scan_mirror_for_sync(
        self,
        *,
        events: Sequence[sqlite3.Row],
    ) -> tuple[list[dict[str, Any]], bool]:
        if not self._mirror_path.exists():
            return [], False
        info = self._mirror_path.lstat()
        if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode):
            raise GoalProofLedgerIntegrityError(
                "GOAL proof mirror must be a regular non-symlink file"
            )
        raw = self._mirror_path.read_bytes()
        complete_raw = raw
        partial_tail = b""
        if raw and not raw.endswith(b"\n"):
            last_newline = raw.rfind(b"\n")
            split_at = last_newline + 1 if last_newline >= 0 else 0
            complete_raw = raw[:split_at]
            partial_tail = raw[split_at:]

        rows: list[dict[str, Any]] = []
        for line_no, raw_line in enumerate(complete_raw.splitlines(), start=1):
            if not raw_line.strip():
                raise GoalProofLedgerIntegrityError(
                    f"GOAL proof mirror line {line_no} is empty"
                )
            try:
                row = json.loads(raw_line.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise GoalProofLedgerIntegrityError(
                    f"GOAL proof mirror line {line_no} is malformed"
                ) from exc
            if not isinstance(row, dict) or canonical_json(row).encode("utf-8") != raw_line:
                raise GoalProofLedgerIntegrityError(
                    f"GOAL proof mirror line {line_no} is not canonical"
                )
            rows.append(row)

        expected_rows: list[dict[str, Any]] = []
        prev_hash = GENESIS_HASH
        for event in events:
            expected = self._mirror_row(event, prev_hash=prev_hash)
            expected_rows.append(expected)
            prev_hash = str(expected["row_hash"])
        if len(rows) > len(expected_rows):
            raise GoalProofLedgerIntegrityError(
                "GOAL proof mirror is ahead of SQLite source of truth"
            )
        for index, row in enumerate(rows):
            if canonical_json(row) != canonical_json(expected_rows[index]):
                raise GoalProofLedgerIntegrityError(
                    f"GOAL proof mirror diverges from SQLite at seq={index + 1}"
                )

        repaired = False
        if partial_tail:
            index = len(rows)
            if index >= len(expected_rows):
                raise GoalProofLedgerIntegrityError(
                    "GOAL proof mirror has an uncommitted partial event"
                )
            if bool(events[index]["mirrored"]):
                raise GoalProofLedgerIntegrityError(
                    "GOAL proof mirror was truncated after a mirrored event"
                )
            expected_line = self._mirror_line(expected_rows[index])
            if not expected_line.startswith(partial_tail):
                raise GoalProofLedgerIntegrityError(
                    "GOAL proof mirror partial tail differs from the next SQLite event"
                )
            with self._mirror_path.open("r+b") as handle:
                handle.truncate(len(complete_raw))
                handle.flush()
                os.fsync(handle.fileno())
            repaired = True

        for event in events[len(rows) :]:
            if bool(event["mirrored"]):
                raise GoalProofLedgerIntegrityError(
                    "GOAL proof mirror was truncated after a mirrored event"
                )
        return rows, repaired

    def sync(self) -> MirrorSyncResult:
        """Deterministically extend/repair the JSONL mirror from SQLite outbox rows."""

        with self._mirror_lock():
            with self._lock:
                connection = self._connect()
                try:
                    connection.execute("BEGIN IMMEDIATE")
                    events = connection.execute(
                        "SELECT * FROM goal_proof_events ORDER BY seq"
                    ).fetchall()
                    rows, repaired = self._scan_mirror_for_sync(events=events)
                    expected_rows: list[dict[str, Any]] = []
                    prev_hash = GENESIS_HASH
                    for event in events:
                        row = self._mirror_row(event, prev_hash=prev_hash)
                        expected_rows.append(row)
                        prev_hash = str(row["row_hash"])

                    pending_rows = expected_rows[len(rows) :]
                    if pending_rows:
                        mirror_flags = (
                            os.O_WRONLY
                            | os.O_CREAT
                            | os.O_APPEND
                            | getattr(os, "O_NOFOLLOW", 0)
                        )
                        mirror_fd = os.open(self._mirror_path, mirror_flags, 0o600)
                        try:
                            for row_index, row in enumerate(pending_rows):
                                raw = self._mirror_line(row)
                                midpoint = max(1, len(raw) // 2)
                                written = os.write(mirror_fd, raw[:midpoint])
                                if written != midpoint:
                                    raise OSError("short GOAL proof mirror prefix write")
                                if row_index == 0:
                                    self._fault("mirror_after_partial_write")
                                offset = midpoint
                                while offset < len(raw):
                                    count = os.write(mirror_fd, raw[offset:])
                                    if count <= 0:
                                        raise OSError("short GOAL proof mirror write")
                                    offset += count
                            os.fsync(mirror_fd)
                        finally:
                            os.close(mirror_fd)
                        self._fsync_directory(self._mirror_path.parent)
                    self._fault("mirror_after_fsync_before_mark")
                    if events:
                        connection.execute(
                            "UPDATE goal_proof_events SET mirrored=1 WHERE mirrored=0"
                        )
                    self._fault("before_mirror_mark_commit")
                    connection.execute("COMMIT")
                    return MirrorSyncResult(
                        appended=len(pending_rows),
                        repaired_partial_tail=repaired,
                        mirror_event_count=len(expected_rows),
                        sqlite_event_count=len(events),
                    )
                except Exception:
                    if connection.in_transaction:
                        connection.execute("ROLLBACK")
                    raise
                finally:
                    connection.close()

    def _verify_sqlite(
        self, connection: sqlite3.Connection
    ) -> tuple[list[str], list[ProofHead], int]:
        issues: list[str] = []
        try:
            if str(connection.execute("PRAGMA journal_mode").fetchone()[0]).lower() != "wal":
                issues.append("SQLite journal_mode is not WAL")
            if int(connection.execute("PRAGMA synchronous").fetchone()[0]) != 2:
                issues.append("SQLite synchronous is not FULL")
            if int(connection.execute("PRAGMA foreign_keys").fetchone()[0]) != 1:
                issues.append("SQLite foreign_keys is not ON")
            if connection.execute("PRAGMA foreign_key_check").fetchall():
                issues.append("SQLite foreign_key_check failed")
            integrity = connection.execute("PRAGMA integrity_check").fetchall()
            if len(integrity) != 1 or str(integrity[0][0]).lower() != "ok":
                issues.append("SQLite integrity_check failed")
            meta_rows = connection.execute(
                "SELECT key,value FROM goal_proof_meta ORDER BY key"
            ).fetchall()
            expected_meta = _expected_meta()
            observed_meta = {
                str(row["key"]): str(row["value"]) for row in meta_rows
            }
            if len(meta_rows) != len(expected_meta):
                issues.append(
                    "GOAL proof meta cardinality mismatch: "
                    f"expected {len(expected_meta)}, got {len(meta_rows)}"
                )
            for key, expected_value in expected_meta.items():
                if key not in observed_meta:
                    issues.append(f"GOAL proof meta key {key} is missing")
                elif observed_meta[key] != expected_value:
                    issues.append(
                        f"GOAL proof meta {key} mismatch: "
                        f"expected {expected_value!r}, got {observed_meta[key]!r}"
                    )
            unexpected_meta = sorted(set(observed_meta) - set(expected_meta))
            if unexpected_meta:
                issues.append(
                    "GOAL proof meta has unexpected keys: "
                    + ", ".join(unexpected_meta)
                )
        except sqlite3.DatabaseError as exc:
            return [f"SQLite integrity query failed: {exc}"], [], 0

        events = connection.execute(
            "SELECT * FROM goal_proof_events ORDER BY seq"
        ).fetchall()
        expected_seq = 1
        event_by_id: dict[str, sqlite3.Row] = {}
        for event in events:
            seq = int(event["seq"])
            if seq != expected_seq:
                issues.append(f"event sequence is discontinuous at seq={seq}")
                expected_seq = seq
            expected_seq += 1
            try:
                payload = _strict_json_object(
                    str(event["payload_json"]), field_name="event payload"
                )
            except GoalProofLedgerIntegrityError as exc:
                issues.append(str(exc))
                continue
            if _sha256(payload) != str(event["payload_hash"]):
                issues.append(f"event payload hash mismatch at seq={seq}")
            kind = str(event["event_kind"])
            expected_event_id = ""
            try:
                if kind == "declaration":
                    expected_event_id = self._declaration_event_id(payload)
                elif kind == "invalidation":
                    expected_event_id = self._invalidation_event_id(payload)
                else:
                    issues.append(f"unsupported event kind at seq={seq}")
            except (KeyError, TypeError, ValueError) as exc:
                issues.append(f"event identity fields invalid at seq={seq}: {exc}")
            if expected_event_id and expected_event_id != str(event["event_id"]):
                issues.append(f"event identity mismatch at seq={seq}")
            for column, key in (
                ("owner", "owner"),
                ("subject", "subject"),
            ):
                if key in payload and str(event[column]) != str(payload[key]):
                    issues.append(f"event {column} mismatch at seq={seq}")
            if kind == "declaration" and str(event["bundle_id"]) != str(
                payload.get("bundle_id", "")
            ):
                issues.append(f"declaration bundle mismatch at seq={seq}")
            if kind == "invalidation" and str(event["bundle_id"]) != str(
                payload.get("invalidation_bundle_id", "")
            ):
                issues.append(f"invalidation bundle mismatch at seq={seq}")
            event_by_id[str(event["event_id"])] = event

        declarations = connection.execute(
            "SELECT * FROM goal_proof_declarations ORDER BY declared_seq"
        ).fetchall()
        declaration_by_id = {
            str(row["declaration_event_id"]): row for row in declarations
        }
        history: dict[tuple[str, str], list[sqlite3.Row]] = {}
        for row in declarations:
            event_id = str(row["declaration_event_id"])
            event = event_by_id.get(event_id)
            if event is None or str(event["event_kind"]) != "declaration":
                issues.append(f"declaration {event_id} lacks its declaration event")
                continue
            payload = _strict_json_object(
                str(event["payload_json"]), field_name="declaration event payload"
            )
            expected_columns = {
                "bundle_id": payload.get("bundle_id"),
                "owner": payload.get("owner"),
                "subject": payload.get("subject"),
                "logical_type": payload.get("logical_type"),
                "logical_ref": payload.get("logical_ref"),
                "generation": payload.get("generation"),
                "member_payload_hash": payload.get("member_payload_hash"),
            }
            for column, expected in expected_columns.items():
                observed: Any = row[column]
                if column == "generation":
                    observed = int(observed)
                if observed != expected:
                    issues.append(f"declaration {event_id} {column} mismatch")
            member_payload = _strict_json_object(
                str(row["member_payload_json"]), field_name="member payload"
            )
            if member_payload != payload.get("member_payload"):
                issues.append(f"declaration {event_id} payload differs from event")
            if _sha256(member_payload) != str(row["member_payload_hash"]):
                issues.append(f"declaration {event_id} payload hash mismatch")
            depends_on = json.loads(str(row["depends_on_json"]))
            dependency_event_ids = json.loads(str(row["dependency_event_ids_json"]))
            event_dependency_map = payload.get("dependency_event_ids", {})
            if not isinstance(event_dependency_map, dict):
                issues.append(f"declaration {event_id} dependency map is invalid")
                event_dependency_map = {}
            if depends_on != payload.get("depends_on"):
                issues.append(f"declaration {event_id} dependencies differ from event")
            if dependency_event_ids != list(event_dependency_map.values()):
                issues.append(f"declaration {event_id} dependency events differ from event")
            edge_rows = connection.execute(
                "SELECT owner,dependency_logical_ref,dependency_event_id "
                "FROM goal_proof_dependency_edges WHERE declaration_event_id=? "
                "ORDER BY dependency_logical_ref",
                (event_id,),
            ).fetchall()
            edge_map = {
                str(edge["dependency_logical_ref"]): str(edge["dependency_event_id"])
                for edge in edge_rows
            }
            if edge_map != event_dependency_map:
                issues.append(f"declaration {event_id} server dependency edges differ")
            for edge in edge_rows:
                edge_owner = str(edge["owner"])
                dependency_ref = str(edge["dependency_logical_ref"])
                dependency_event_id = str(edge["dependency_event_id"])
                if edge_owner != str(row["owner"]):
                    issues.append(
                        f"declaration {event_id} dependency owner mismatch"
                    )
                target = declaration_by_id.get(dependency_event_id)
                if target is None:
                    issues.append(f"declaration {event_id} dependency event is absent")
                else:
                    if str(target["owner"]) != edge_owner:
                        issues.append(
                            f"declaration {event_id} dependency owner mismatch"
                        )
                    if str(target["logical_ref"]) != dependency_ref:
                        issues.append(
                            f"declaration {event_id} dependency logical_ref mismatch"
                        )
            history.setdefault(
                (str(row["owner"]), str(row["logical_ref"])), []
            ).append(row)

        for (owner, logical_ref), rows in history.items():
            generations = [int(row["generation"]) for row in rows]
            if generations != list(range(1, len(rows) + 1)):
                issues.append(f"generation sequence invalid for {owner}/{logical_ref}")
            types = {str(row["logical_type"]) for row in rows}
            subjects = {str(row["subject"]) for row in rows}
            if len(types) != 1 or len(subjects) != 1:
                issues.append(f"logical identity drift for {owner}/{logical_ref}")

        bundles = connection.execute(
            "SELECT * FROM goal_proof_bundles ORDER BY first_event_seq"
        ).fetchall()
        for bundle in bundles:
            bundle_id = str(bundle["bundle_id"])
            try:
                members = json.loads(str(bundle["members_json"]))
                generations = json.loads(str(bundle["generations_json"]))
                metadata = _strict_json_object(
                    str(bundle["metadata_json"]), field_name="bundle metadata"
                )
                reconstructed = ProofBundle(
                    owner=str(bundle["owner"]),
                    subject=str(bundle["subject"]),
                    members=tuple(ProofMember.from_dict(item) for item in members),
                    metadata=metadata,
                )
                request_fingerprint = self._bundle_request_fingerprint(reconstructed)
                expected_bundle_id = self._bundle_id(
                    request_fingerprint=request_fingerprint,
                    generations={str(k): int(v) for k, v in generations.items()},
                )
                if request_fingerprint != str(bundle["request_fingerprint"]):
                    issues.append(f"bundle {bundle_id} request fingerprint mismatch")
                if expected_bundle_id != bundle_id:
                    issues.append(f"bundle {bundle_id} identity mismatch")
                if _sha256(metadata) != str(bundle["metadata_hash"]):
                    issues.append(f"bundle {bundle_id} metadata hash mismatch")
                bundle_declarations = [
                    row for row in declarations if str(row["bundle_id"]) == bundle_id
                ]
                if {str(row["logical_ref"]) for row in bundle_declarations} != set(
                    generations
                ):
                    issues.append(f"bundle {bundle_id} member coverage mismatch")
                seqs = [int(row["declared_seq"]) for row in bundle_declarations]
                if not seqs or min(seqs) != int(bundle["first_event_seq"]) or max(
                    seqs
                ) != int(bundle["last_event_seq"]):
                    issues.append(f"bundle {bundle_id} event range mismatch")
            except Exception as exc:
                issues.append(f"bundle {bundle_id} is invalid: {exc}")

        invalidations = connection.execute(
            "SELECT * FROM goal_proof_invalidations ORDER BY invalidated_seq"
        ).fetchall()
        invalidation_by_target: dict[str, sqlite3.Row] = {}
        for row in invalidations:
            event_id = str(row["invalidation_event_id"])
            event = event_by_id.get(event_id)
            target_id = str(row["target_declaration_event_id"])
            target = declaration_by_id.get(target_id)
            if event is None or str(event["event_kind"]) != "invalidation":
                issues.append(f"invalidation {event_id} lacks its event")
                continue
            if target is None:
                issues.append(f"invalidation {event_id} lacks target declaration")
                continue
            payload = _strict_json_object(
                str(event["payload_json"]), field_name="invalidation event payload"
            )
            expected = {
                "invalidation_bundle_id": row["invalidation_bundle_id"],
                "target_declaration_event_id": target_id,
                "owner": row["owner"],
                "subject": row["subject"],
                "logical_ref": row["logical_ref"],
                "generation": int(row["generation"]),
                "reason": row["reason"],
            }
            for key, value in expected.items():
                if payload.get(key) != value:
                    issues.append(f"invalidation {event_id} {key} mismatch")
            if str(target["invalidated_by_event_id"] or "") != event_id:
                issues.append(f"invalidation {event_id} is not target's exact revocation")
            if int(row["invalidated_seq"]) <= int(target["declared_seq"]):
                issues.append(f"invalidation {event_id} precedes its declaration")
            invalidation_by_target[target_id] = row

        invalidation_bundles = connection.execute(
            "SELECT * FROM goal_proof_invalidation_bundles ORDER BY first_event_seq"
        ).fetchall()
        for invalidation_bundle in invalidation_bundles:
            invalidation_bundle_id = str(
                invalidation_bundle["invalidation_bundle_id"]
            )
            try:
                operation_id = _required(
                    invalidation_bundle["operation_id"],
                    field_name="invalidation operation_id",
                )
                requested_targets_raw = json.loads(
                    str(invalidation_bundle["requested_targets_json"])
                )
                if not isinstance(requested_targets_raw, list):
                    raise ValueError("requested targets must be an array")
                requested_targets = tuple(
                    InvalidationTarget(**value) for value in requested_targets_raw
                )
                requested_refs = tuple(
                    json.loads(str(invalidation_bundle["requested_refs_json"]))
                )
                affected_refs = tuple(
                    json.loads(str(invalidation_bundle["affected_refs_json"]))
                )
                if (
                    canonical_json(
                        [target.to_dict() for target in requested_targets]
                    )
                    != str(invalidation_bundle["requested_targets_json"])
                    or tuple(
                        sorted(requested_targets, key=lambda target: target.logical_ref)
                    )
                    != requested_targets
                    or len(
                        {target.declaration_event_id for target in requested_targets}
                    )
                    != len(requested_targets)
                    or tuple(target.logical_ref for target in requested_targets)
                    != requested_refs
                    or canonical_json(list(requested_refs))
                    != str(invalidation_bundle["requested_refs_json"])
                    or canonical_json(list(affected_refs))
                    != str(invalidation_bundle["affected_refs_json"])
                    or tuple(sorted(set(requested_refs))) != requested_refs
                    or tuple(sorted(set(affected_refs))) != affected_refs
                    or not requested_refs
                    or not set(requested_refs).issubset(affected_refs)
                ):
                    issues.append(
                        f"invalidation bundle {invalidation_bundle_id} ref sets are invalid"
                    )
                metadata = _strict_json_object(
                    str(invalidation_bundle["metadata_json"]),
                    field_name="invalidation metadata",
                )
                if _sha256(metadata) != str(invalidation_bundle["metadata_hash"]):
                    issues.append(
                        f"invalidation bundle {invalidation_bundle_id} metadata hash mismatch"
                    )
                request_subject_raw = invalidation_bundle["request_subject"]
                request_subject = (
                    str(request_subject_raw)
                    if request_subject_raw is not None
                    else None
                )
                expected_fingerprint = self._invalidation_request_fingerprint(
                    owner=str(invalidation_bundle["owner"]),
                    operation_id=operation_id,
                    requested_targets=requested_targets,
                    reason=str(invalidation_bundle["reason"]),
                    metadata=metadata,
                    subject=request_subject,
                )
                if expected_fingerprint != str(
                    invalidation_bundle["request_fingerprint"]
                ):
                    issues.append(
                        f"invalidation bundle {invalidation_bundle_id} request fingerprint mismatch"
                    )
                if request_subject is not None and request_subject != str(
                    invalidation_bundle["subject"]
                ):
                    issues.append(
                        f"invalidation bundle {invalidation_bundle_id} request subject mismatch"
                    )
                bundle_rows = sorted(
                    (
                        row
                        for row in invalidations
                        if str(row["invalidation_bundle_id"])
                        == invalidation_bundle_id
                    ),
                    key=lambda row: str(row["logical_ref"]),
                )
                if tuple(str(row["logical_ref"]) for row in bundle_rows) != affected_refs:
                    issues.append(
                        f"invalidation bundle {invalidation_bundle_id} affected coverage mismatch"
                    )
                target_event_ids = tuple(
                    str(row["target_declaration_event_id"]) for row in bundle_rows
                )
                requested_target_event_ids = {
                    target.declaration_event_id for target in requested_targets
                }
                for requested_target in requested_targets:
                    declaration = declaration_by_id.get(
                        requested_target.declaration_event_id
                    )
                    if declaration is None:
                        issues.append(
                            f"invalidation bundle {invalidation_bundle_id} requested target is absent"
                        )
                    elif (
                        str(declaration["owner"])
                        != str(invalidation_bundle["owner"])
                        or str(declaration["logical_ref"])
                        != requested_target.logical_ref
                        or int(declaration["generation"])
                        != requested_target.generation
                    ):
                        issues.append(
                            f"invalidation bundle {invalidation_bundle_id} requested target identity mismatch"
                        )
                if not requested_target_event_ids.issubset(set(target_event_ids)):
                    issues.append(
                        f"invalidation bundle {invalidation_bundle_id} requested targets are outside affected coverage"
                    )
                expected_bundle_id = self._invalidation_bundle_id(
                    request_fingerprint=expected_fingerprint,
                    target_event_ids=target_event_ids,
                )
                if expected_bundle_id != invalidation_bundle_id:
                    issues.append(
                        f"invalidation bundle {invalidation_bundle_id} identity mismatch"
                    )
                seqs = [int(row["invalidated_seq"]) for row in bundle_rows]
                if (
                    not seqs
                    or min(seqs) != int(invalidation_bundle["first_event_seq"])
                    or max(seqs) != int(invalidation_bundle["last_event_seq"])
                ):
                    issues.append(
                        f"invalidation bundle {invalidation_bundle_id} event range mismatch"
                    )
                target_ids = set(target_event_ids)
                target_bundle_ids = {
                    str(declaration_by_id[target_id]["bundle_id"])
                    for target_id in target_ids
                    if target_id in declaration_by_id
                }
                exact_target_ids = {
                    str(row["declaration_event_id"])
                    for row in declarations
                    if str(row["bundle_id"]) in target_bundle_ids
                }
                if target_ids != exact_target_ids:
                    issues.append(
                        f"invalidation bundle {invalidation_bundle_id} is not exact declaration-bundle coverage"
                    )
                first_seq = min(seqs) if seqs else 0
                current_before = {
                    str(row["declaration_event_id"])
                    for row in declarations
                    if int(row["declared_seq"]) < first_seq
                    and (
                        str(row["declaration_event_id"])
                        not in invalidation_by_target
                        or int(
                            invalidation_by_target[
                                str(row["declaration_event_id"])
                            ]["invalidated_seq"]
                        )
                        >= first_seq
                    )
                }
                inbound_rows = connection.execute(
                    "SELECT declaration_event_id,dependency_event_id "
                    "FROM goal_proof_dependency_edges"
                ).fetchall()
                if any(
                    str(edge["declaration_event_id"]) in current_before - target_ids
                    and str(edge["dependency_event_id"]) in target_ids
                    for edge in inbound_rows
                ):
                    issues.append(
                        f"invalidation bundle {invalidation_bundle_id} bypassed an external inbound dependency"
                    )
                for row in bundle_rows:
                    event = event_by_id.get(str(row["invalidation_event_id"]))
                    if event is None:
                        continue
                    payload = _strict_json_object(
                        str(event["payload_json"]),
                        field_name="invalidation event payload",
                    )
                    if (
                        payload.get("operation_id") != operation_id
                        or payload.get("requested_targets")
                        != [target.to_dict() for target in requested_targets]
                        or payload.get("requested_refs") != list(requested_refs)
                        or payload.get("affected_refs") != list(affected_refs)
                        or payload.get("metadata") != metadata
                    ):
                        issues.append(
                            f"invalidation bundle {invalidation_bundle_id} event request differs"
                        )
            except Exception as exc:
                issues.append(
                    f"invalidation bundle {invalidation_bundle_id} is invalid: {exc}"
                )

        expected_current = {
            event_id: row
            for event_id, row in declaration_by_id.items()
            if event_id not in invalidation_by_target
        }
        actual_current_rows = self._current_head_rows(connection)
        actual_current = {
            str(row["head_declaration_event_id"]): row
            for row in actual_current_rows
        }
        if set(actual_current) != set(expected_current):
            issues.append("current-head projection differs from declaration/invalidation replay")
        for event_id, row in actual_current.items():
            expected = expected_current.get(event_id)
            if expected is None:
                continue
            for head_column, declaration_column, issue_field in (
                ("head_owner", "owner", "owner"),
                ("head_logical_ref", "logical_ref", "logical_ref"),
                (
                    "head_declaration_event_id",
                    "declaration_event_id",
                    "declaration_event_id",
                ),
                ("head_subject", "subject", "subject"),
                ("head_logical_type", "logical_type", "logical_type"),
                ("head_generation", "generation", "generation"),
                ("head_bundle_id", "bundle_id", "bundle_id"),
                ("head_declared_seq", "declared_seq", "declared_seq"),
            ):
                if row[head_column] != expected[declaration_column]:
                    issues.append(
                        f"current head {event_id} {issue_field} mismatch"
                    )
            if row["head_payload_hash"] != expected["member_payload_hash"]:
                issues.append(f"current head {event_id} payload_hash mismatch")

        actual_current_ids = set(actual_current)
        invalidated_ids = set(invalidation_by_target)
        for bundle in bundles:
            bundle_id = str(bundle["bundle_id"])
            declaration_ids = {
                str(row["declaration_event_id"])
                for row in declarations
                if str(row["bundle_id"]) == bundle_id
            }
            if not declaration_ids:
                continue
            current_count = len(declaration_ids.intersection(actual_current_ids))
            invalidated_count = len(declaration_ids.intersection(invalidated_ids))
            if current_count not in (0, len(declaration_ids)) or invalidated_count not in (
                0,
                len(declaration_ids),
            ):
                issues.append(f"bundle {bundle_id} partial current status")

        current_event_ids = set(actual_current)
        for event_id, row in actual_current.items():
            edge_rows = connection.execute(
                "SELECT dependency_event_id FROM goal_proof_dependency_edges "
                "WHERE declaration_event_id=?",
                (event_id,),
            ).fetchall()
            for edge in edge_rows:
                if str(edge["dependency_event_id"]) not in current_event_ids:
                    issues.append(
                        f"current declaration {row['logical_ref']} depends on a non-current event"
                    )

        heads: list[ProofHead] = []
        for row in actual_current_rows:
            try:
                heads.append(self._head_from_row(row))
            except Exception as exc:
                issues.append(f"current head could not be decoded: {exc}")
        return issues, heads, len(events)

    @staticmethod
    def _snapshot_digest(heads: Sequence[ProofHead]) -> str:
        return _sha256(
            [
                {
                    "owner": head.owner,
                    "subject": head.subject,
                    "logical_type": head.logical_type,
                    "logical_ref": head.logical_ref,
                    "generation": head.generation,
                    "declaration_event_id": head.declaration_event_id,
                    "payload_hash": head.payload_hash,
                }
                for head in sorted(heads, key=lambda item: (item.owner, item.logical_ref))
            ]
        )

    def _verify_mirror(
        self, events: Sequence[sqlite3.Row]
    ) -> tuple[list[str], int]:
        issues: list[str] = []
        if not self._mirror_path.exists():
            if events:
                issues.append("JSONL mirror is absent while SQLite events exist")
            return issues, 0
        raw = self._mirror_path.read_bytes()
        if raw and not raw.endswith(b"\n"):
            issues.append("JSONL mirror ends with a partial event")
            return issues, len(raw.splitlines())
        rows: list[dict[str, Any]] = []
        for line_no, raw_line in enumerate(raw.splitlines(), start=1):
            try:
                row = json.loads(raw_line.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError):
                issues.append(f"JSONL mirror line {line_no} is malformed")
                continue
            if not isinstance(row, dict) or canonical_json(row).encode("utf-8") != raw_line:
                issues.append(f"JSONL mirror line {line_no} is not canonical")
                continue
            rows.append(row)
        if len(rows) != len(events):
            issues.append("SQLite event count differs from JSONL mirror")
        prev_hash = GENESIS_HASH
        for index, event in enumerate(events):
            expected = self._mirror_row(event, prev_hash=prev_hash)
            prev_hash = str(expected["row_hash"])
            if index >= len(rows):
                continue
            if canonical_json(rows[index]) != canonical_json(expected):
                issues.append(f"JSONL mirror diverges at seq={index + 1}")
            if not bool(event["mirrored"]):
                issues.append(f"SQLite outbox is pending at seq={index + 1}")
        return issues, len(rows)

    def verify(self) -> LedgerVerification:
        # Mirror lock first is the global lock order used by ``sync``.  It
        # prevents the file from advancing while the SQLite WAL read snapshot
        # is being compared with its exact outbox prefix.
        with self._mirror_lock():
            with self._lock:
                connection = self._connect()
                try:
                    connection.execute("BEGIN")
                    sqlite_issues, heads, event_count = self._verify_sqlite(connection)
                    events = connection.execute(
                        "SELECT * FROM goal_proof_events ORDER BY seq"
                    ).fetchall()
                    mirror_issues, mirror_count = self._verify_mirror(events)
                    issues = tuple(sqlite_issues + mirror_issues)
                    result = LedgerVerification(
                        ok=not issues,
                        issues=issues,
                        sqlite_event_count=event_count,
                        mirror_event_count=mirror_count,
                        current_head_count=len(heads),
                        current_digest=self._snapshot_digest(heads),
                    )
                    connection.execute("COMMIT")
                    return result
                except Exception:
                    if connection.in_transaction:
                        connection.execute("ROLLBACK")
                    raise
                finally:
                    connection.close()

    @staticmethod
    def _file_state(path: Path) -> tuple[int, int, int, int, int] | None:
        try:
            info = path.lstat()
        except FileNotFoundError:
            return None
        return (
            int(info.st_dev),
            int(info.st_ino),
            int(info.st_size),
            int(info.st_mtime_ns),
            int(info.st_ctime_ns),
        )

    def _wal_file_state(self) -> tuple[int, int, int, int, int] | None:
        state = self._file_state(Path(str(self._db_path) + "-wal"))
        # On macOS, opening a WAL-mode database for a read transaction can
        # transiently create a new empty -wal file and remove it again when
        # the connection closes. An empty WAL contains no committed state, so
        # binding its inode/ctime would make every unchanged read miss the
        # verified snapshot cache. Non-empty WAL files remain fully bound.
        if state is not None and state[2] == 0:
            return None
        return state

    def _current_file_state_unlocked(self) -> tuple[Any, ...]:
        return (
            self._file_state(self._db_path),
            self._wal_file_state(),
            self._file_state(self._mirror_path),
        )

    def _current_logical_state_token(
        self,
        connection: sqlite3.Connection,
    ) -> tuple[Any, ...]:
        event_state = tuple(
            connection.execute(
                "SELECT COUNT(*),COALESCE(MAX(seq),0),"
                "COALESCE(SUM(mirrored),0) FROM goal_proof_events"
            ).fetchone()
        )
        head_state = tuple(
            connection.execute(
                "SELECT COUNT(*),COALESCE(MAX(declared_seq),0) "
                "FROM goal_proof_current_heads"
            ).fetchone()
        )
        meta_state = tuple(
            tuple(row)
            for row in connection.execute(
                "SELECT key,value FROM goal_proof_meta ORDER BY key"
            ).fetchall()
        )
        return event_state, head_state, meta_state

    def _current_state_token_unlocked(self) -> tuple[Any, ...] | None:
        """Return a cheap invalidation token for a fully verified snapshot.

        A complete ``current()`` read verifies every SQLite relation and every
        JSONL hash-chain row. Strict backing can ask for the same unchanged
        owner snapshot hundreds of times in one request, so repeating that
        replay is both redundant and quadratic at the call graph level. The
        token binds the logical event/head/meta counters to OS change metadata
        for SQLite, its WAL, and the mirror. Any legitimate writer, direct SQL
        mutation, mirror rewrite/truncation, or outbox-state change therefore
        misses the cache and re-enters the full fail-closed path.

        Callers hold the mirror lock and the instance lock. The SQLite queries
        use one read transaction so a concurrent writer cannot produce a
        recombined token.
        """

        files_before = self._current_file_state_unlocked()
        connection = self._connect()
        try:
            connection.execute("BEGIN")
            logical_state = self._current_logical_state_token(connection)
            files_after = self._current_file_state_unlocked()
            connection.execute("COMMIT")
        except Exception:
            if connection.in_transaction:
                connection.execute("ROLLBACK")
            raise
        finally:
            connection.close()
        if files_before != files_after:
            return None
        return (*logical_state, *files_after)

    @staticmethod
    def _token_is_fully_mirrored(token: tuple[Any, ...]) -> bool:
        event_count, _max_seq, mirrored_count = token[0]
        return int(event_count) == int(mirrored_count)

    def current(
        self,
        *,
        owner: str | None = None,
        subject: str | None = None,
    ) -> ProofSnapshot:
        normalized_owner = (
            _required(owner, field_name="owner") if owner is not None else None
        )
        normalized_subject = (
            _required(subject, field_name="subject") if subject is not None else None
        )
        cache_key = (normalized_owner, normalized_subject)
        cache_enabled = self._fault_injector is None
        if cache_enabled:
            with self._mirror_lock():
                with self._lock:
                    state_token = self._current_state_token_unlocked()
                    cached = self._current_snapshot_cache.get(cache_key)
                    if (
                        state_token is not None
                        and cached is not None
                        and self._token_is_fully_mirrored(state_token)
                        and cached[0] == state_token
                    ):
                        # LRU:真命中(token 匹配)才标最近用。stale 项(token 不匹配)
                        # 落到重算路径、由写侧覆盖,不在此提权。
                        self._current_snapshot_cache.move_to_end(cache_key)
                        # Proof payloads are JSON dictionaries. Return a
                        # defensive copy so a caller cannot mutate the cached
                        # authoritative snapshot seen by later readers.
                        return copy.deepcopy(cached[1])
        # Repair any already-committed outbox rows before establishing the
        # snapshot.  A commit racing after ``BEGIN`` cannot leak into this WAL
        # snapshot, and its mirror sync is held behind the same mirror lock.
        self.sync()
        with self._mirror_lock():
            with self._lock:
                connection = self._connect()
                files_before = self._current_file_state_unlocked()
                verified_state_token: tuple[Any, ...] | None = None
                try:
                    connection.execute("BEGIN")
                    at_seq = int(
                        connection.execute(
                            "SELECT COALESCE(MAX(seq),0) FROM goal_proof_events"
                        ).fetchone()[0]
                    )
                    self._fault("current_after_snapshot_start")
                    sqlite_issues, all_heads, event_count = self._verify_sqlite(connection)
                    events = connection.execute(
                        "SELECT * FROM goal_proof_events ORDER BY seq"
                    ).fetchall()
                    mirror_issues, mirror_count = self._verify_mirror(events)
                    if event_count != at_seq:
                        sqlite_issues.append(
                            "GOAL proof current snapshot event head changed within one transaction"
                        )
                    if any(not bool(event["mirrored"]) for event in events):
                        mirror_issues.append(
                            "GOAL proof current snapshot contains an unmirrored event"
                        )
                    issues = sqlite_issues + mirror_issues
                    if issues:
                        raise GoalProofLedgerIntegrityError("; ".join(issues))
                    heads = tuple(
                        head
                        for head in all_heads
                        if (normalized_owner is None or head.owner == normalized_owner)
                        and (
                            normalized_subject is None
                            or head.subject == normalized_subject
                        )
                    )
                    snapshot = ProofSnapshot(
                        owner=normalized_owner,
                        subject=normalized_subject,
                        at_seq=at_seq,
                        head_digest=self._snapshot_digest(heads),
                        heads=heads,
                        mirror_synced=(
                            not mirror_issues
                            and mirror_count == event_count
                            and all(bool(event["mirrored"]) for event in events)
                        ),
                    )
                    logical_state = self._current_logical_state_token(connection)
                    files_after = self._current_file_state_unlocked()
                    if files_before == files_after:
                        verified_state_token = (*logical_state, *files_after)
                    connection.execute("COMMIT")
                except Exception:
                    if connection.in_transaction:
                        connection.execute("ROLLBACK")
                    raise
                finally:
                    connection.close()
                if cache_enabled and verified_state_token is not None:
                    _event_count, max_seq, _mirrored_count = verified_state_token[0]
                    if (
                        self._token_is_fully_mirrored(verified_state_token)
                        and int(max_seq) == snapshot.at_seq
                    ):
                        self._current_snapshot_cache[cache_key] = (
                            verified_state_token,
                            copy.deepcopy(snapshot),
                        )
                        self._current_snapshot_cache.move_to_end(cache_key)
                        # LRU 淘汰:超上限逐最旧(FIFO of least-recently-used)。
                        # 淘汰项下次读走重算路径,token 校验保证绝不 stale。
                        while (
                            len(self._current_snapshot_cache)
                            > self._current_snapshot_cache_maxsize
                        ):
                            self._current_snapshot_cache.popitem(last=False)
                return snapshot

    def journal_mode(self) -> str:
        connection = self._connect()
        try:
            return str(connection.execute("PRAGMA journal_mode").fetchone()[0]).lower()
        finally:
            connection.close()

    def close(self) -> None:
        """No-op compatibility hook; this repository opens scoped connections."""


__all__ = [
    "CommitResult",
    "DB_FILENAME",
    "GENESIS_HASH",
    "GoalProofConflictError",
    "GoalProofDependencyError",
    "GoalProofLedger",
    "GoalProofLedgerError",
    "GoalProofLedgerIntegrityError",
    "GoalProofMirrorPendingError",
    "HASH_VERSION",
    "InvalidationResult",
    "InvalidationTarget",
    "LedgerVerification",
    "MIRROR_FILENAME",
    "MIRROR_SCHEMA_VERSION",
    "MirrorSyncResult",
    "ProofBundle",
    "ProofHead",
    "ProofMember",
    "ProofSnapshot",
    "SCHEMA_VERSION",
]
