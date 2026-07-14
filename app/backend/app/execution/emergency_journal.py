"""Durable, content-bound journal for non-idempotent emergency close actions.

The SQLite database is the source of truth.  Every state transition appends a
sealed snapshot event in the same transaction, and a JSONL mirror is repaired
from those committed events after a crash.  API credentials and raw venue
payloads are deliberately excluded.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import math
import os
import secrets
import sqlite3
import stat
import threading
from contextlib import contextmanager, nullcontext
from dataclasses import asdict, dataclass, replace
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Literal

from ..cross_process_lock import acquire_exclusive_fd
from ..lineage.ids import canonical_json


EmergencyActionStatus = Literal[
    "prepared",
    "submitting",
    "acknowledged",
    "pending",
    "terminal_partial",
    "filled_residual",
    "manual_unknown_flat",
    "reconciled",
    "failed",
]


class EmergencyActionError(RuntimeError):
    """Emergency action evidence is missing, inconsistent, or tampered."""


def _sha256(payload: str | bytes) -> str:
    raw = payload if isinstance(payload, bytes) else payload.encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="microseconds")


def _required(value: object, *, field: str) -> str:
    cleaned = str(value or "").strip()
    if not cleaned:
        raise ValueError(f"emergency action {field} is required")
    return cleaned


def _positive_epoch(value: object) -> int:
    if type(value) is not int or value <= 0:
        raise ValueError("emergency action account_epoch must be a positive exact integer")
    return value


def _quantity_text(value: object) -> str:
    if isinstance(value, bool):
        raise ValueError("emergency action quantity must be a positive finite number")
    try:
        number = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ValueError("emergency action quantity must be a positive finite number") from exc
    if not number.is_finite() or number <= 0:
        raise ValueError("emergency action quantity must be a positive finite number")
    normalized = format(number.normalize(), "f")
    return normalized.rstrip("0").rstrip(".") if "." in normalized else normalized


def _full_sha256_ref(value: object, *, field: str) -> str:
    cleaned = _required(value, field=field)
    if not cleaned.startswith("sha256:") or len(cleaned) != 71:
        raise ValueError(f"emergency action {field} must be a full sha256 digest")
    digest = cleaned.removeprefix("sha256:")
    if any(ch not in "0123456789abcdef" for ch in digest):
        raise ValueError(f"emergency action {field} must be lowercase hexadecimal")
    return cleaned


def emergency_close_request_params(
    *,
    symbol: str,
    side: Literal["buy", "sell"],
    quantity: object,
    client_order_id: str,
) -> dict[str, Any]:
    """Build the exact unsigned Binance emergency-close request payload."""

    normalized_symbol = _required(symbol, field="symbol").upper()
    normalized_side = str(side or "").strip().lower()
    if normalized_side not in {"buy", "sell"}:
        raise ValueError("emergency action side must be buy or sell")
    client_id = _required(client_order_id, field="client_order_id")
    allowed = frozenset(".ABCDEFGHIJKLMNOPQRSTUVWXYZ:/abcdefghijklmnopqrstuvwxyz0123456789_-")
    if len(client_id) > 36 or any(char not in allowed for char in client_id):
        raise ValueError("emergency action client_order_id is not Binance-compatible")
    return {
        "symbol": normalized_symbol,
        "side": "BUY" if normalized_side == "buy" else "SELL",
        "type": "MARKET",
        "quantity": float(_quantity_text(quantity)),
        "reduceOnly": "true",
        "positionSide": "BOTH",
        "newClientOrderId": client_id,
        "newOrderRespType": "RESULT",
    }


def emergency_close_request_hash(params: dict[str, Any]) -> str:
    """Return the full digest of the exact unsigned emergency request."""

    if not isinstance(params, dict):
        raise TypeError("emergency action request params must be an object")
    return "sha256:" + _sha256(canonical_json(params))


@contextmanager
def _portable_file_lock(path: Path):
    """Cross-process one-byte lock with POSIX and Windows implementations."""

    path.parent.mkdir(parents=True, exist_ok=True)
    if os.path.lexists(path) and stat.S_ISLNK(path.lstat().st_mode):
        raise EmergencyActionError("emergency action mirror lock must not be a symlink")
    flags = os.O_RDWR | os.O_CREAT
    flags |= getattr(os, "O_NOFOLLOW", 0)
    flags |= getattr(os, "O_BINARY", 0)
    fd = os.open(path, flags, 0o600)
    info = os.fstat(fd)
    if not stat.S_ISREG(info.st_mode):
        os.close(fd)
        raise EmergencyActionError("emergency action mirror lock must be a regular file")
    held = None
    try:
        held = acquire_exclusive_fd(fd, timeout_seconds=None)
        yield
    finally:
        try:
            if held is not None:
                held.release()
        finally:
            os.close(fd)


@dataclass(frozen=True)
class EmergencyCloseAction:
    action_ref: str
    owner_user_id: str
    halt_ref: str
    owner_epoch: int
    account_ref: str
    account_epoch: int
    credential_binding_ref: str
    symbol: str
    attempt_no: int
    side: Literal["buy", "sell"]
    quantity_text: str
    client_order_id: str
    action_identity_hash: str
    request_hash: str
    status: EmergencyActionStatus
    venue_order_id: str = ""
    terminal_status: str = ""
    cumulative_filled_qty_text: str = "0"
    ack_response_hash: str = ""
    observation_ref: str = ""
    observation_raw_hash: str = ""
    verified_flat: bool = False
    last_event_ref: str = ""
    created_at_utc: str = ""
    updated_at_utc: str = ""

    @property
    def quantity(self) -> float:
        return float(self.quantity_text)

    def request_params(self) -> dict[str, Any]:
        params = emergency_close_request_params(
            symbol=self.symbol,
            side=self.side,
            quantity=self.quantity_text,
            client_order_id=self.client_order_id,
        )
        if emergency_close_request_hash(params) != self.request_hash:
            raise EmergencyActionError(
                "prepared emergency request no longer matches its sealed request_hash"
            )
        return params

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class EmergencyUnknownSubmissionResolution:
    resolution_ref: str
    action_ref: str
    owner_user_id: str
    original_halt_ref: str
    original_owner_epoch: int
    resolving_halt_ref: str
    resolving_owner_epoch: int
    account_ref: str
    account_epoch: int
    operator_user_id: str
    decision: str
    operator_auth_audit_ref: str
    lookup_code: int
    lookup_evidence_ref: str
    lookup_evidence_hash: str
    lookup_observed_at_utc: str
    flat_verification: dict[str, Any]
    flat_verification_ref: str
    flat_verification_hash: str
    flat_observed_at_utc: str
    historical_submission_outcome: str
    historical_fill_state: str
    automatic_retry_permitted: bool
    expected_action_event_ref: str
    created_at_utc: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class EmergencyActionJournal:
    """SQLite-WAL source of truth plus repairable append-only JSONL mirror."""

    SCHEMA_VERSION = 4
    KEY_VERSION = "emergency-action-hmac-v1"
    MIRROR_SCHEMA_VERSION = "emergency-action-mirror-v1"
    _STATUSES = frozenset(
        {
            "prepared",
            "submitting",
            "acknowledged",
            "pending",
            "terminal_partial",
            "filled_residual",
            "manual_unknown_flat",
            "reconciled",
            "failed",
        }
    )
    _ACTION_FIELDS = (
        "action_ref",
        "owner_user_id",
        "halt_ref",
        "owner_epoch",
        "account_ref",
        "account_epoch",
        "credential_binding_ref",
        "symbol",
        "attempt_no",
        "side",
        "quantity_text",
        "client_order_id",
        "action_identity_hash",
        "request_hash",
        "status",
        "venue_order_id",
        "terminal_status",
        "cumulative_filled_qty_text",
        "ack_response_hash",
        "observation_ref",
        "observation_raw_hash",
        "verified_flat",
        "last_event_ref",
        "created_at_utc",
        "updated_at_utc",
    )
    _ACTION_DB_FIELDS = _ACTION_FIELDS + (
        "integrity_key_version",
        "integrity_seal",
    )
    _RESOLUTION_FIELDS = (
        "resolution_ref",
        "action_ref",
        "owner_user_id",
        "original_halt_ref",
        "original_owner_epoch",
        "resolving_halt_ref",
        "resolving_owner_epoch",
        "account_ref",
        "account_epoch",
        "operator_user_id",
        "decision",
        "operator_auth_audit_ref",
        "lookup_code",
        "lookup_evidence_ref",
        "lookup_evidence_hash",
        "lookup_observed_at_utc",
        "flat_verification",
        "flat_verification_ref",
        "flat_verification_hash",
        "flat_observed_at_utc",
        "historical_submission_outcome",
        "historical_fill_state",
        "automatic_retry_permitted",
        "expected_action_event_ref",
        "created_at_utc",
    )
    _EXPECTED_SCHEMA_OBJECTS = frozenset(
        {
            "emergency_close_actions",
            "idx_emergency_actions_halt",
            "idx_emergency_one_active_symbol_action",
            "idx_emergency_one_active_account_epoch_symbol",
            "emergency_close_action_events",
            "idx_emergency_action_events_action",
            "emergency_unknown_submission_resolutions",
            "idx_emergency_unknown_resolution_action",
        }
    )
    _PRE_RESOLUTION_SCHEMA_OBJECTS = frozenset(
        {
            "emergency_close_actions",
            "idx_emergency_actions_halt",
            "idx_emergency_one_active_symbol_action",
            "idx_emergency_one_active_account_epoch_symbol",
            "emergency_close_action_events",
            "idx_emergency_action_events_action",
        }
    )
    UNKNOWN_RESOLUTION_DECISION = "preserve_unknown_and_forbid_retry"
    UNKNOWN_SUBMISSION_OUTCOME = "unknown"
    UNKNOWN_FILL_STATE = "unknown"

    def __init__(
        self,
        db_path: str | Path,
        *,
        mirror_path: str | Path | None = None,
        integrity_key: bytes | None = None,
        integrity_key_path: str | Path | None = None,
    ) -> None:
        self._path = Path(db_path)
        self._mirror_path = (
            Path(mirror_path)
            if mirror_path is not None
            else self._path.with_name(self._path.stem + ".jsonl")
        )
        self._prepare_storage()
        self._lock = threading.RLock()
        self._account_halt_barrier: object | None = None
        self._init_schema()
        if integrity_key is not None and integrity_key_path is not None:
            raise ValueError("emergency action integrity key and path are mutually exclusive")
        if integrity_key is not None:
            if len(integrity_key) < 32:
                raise ValueError("emergency action integrity key must contain at least 32 bytes")
            self._key = bytes(integrity_key)
            self._key_path: Path | None = None
        else:
            key_path = (
                Path(integrity_key_path)
                if integrity_key_path is not None
                else self._path.with_name("." + self._path.name + ".hmac.key")
            )
            if not key_path.exists() and self._database_has_evidence():
                raise EmergencyActionError(
                    "emergency action integrity key is missing for persisted evidence"
                )
            self._key = self._load_or_create_key(key_path)
            self._key_path = key_path
        self.validate_replay()
        self._migrate_schema_after_replay()
        self.validate_replay()
        self.sync_mirror()

    @property
    def path(self) -> Path:
        return self._path

    @property
    def mirror_path(self) -> Path:
        return self._mirror_path

    @property
    def account_fence_bound(self) -> bool:
        return self._account_halt_barrier is not None

    def bind_account_halt_barrier(self, barrier: object) -> None:
        if not hasattr(barrier, "emergency_action_fence"):
            raise TypeError("account HALT barrier lacks emergency action fencing")
        self._account_halt_barrier = barrier

    def _prepare_storage(self) -> None:
        for directory in {self._path.parent, self._mirror_path.parent}:
            if os.path.lexists(directory) and directory.is_symlink():
                raise EmergencyActionError(
                    f"emergency action storage directory must not be a symlink: {directory}"
                )
            directory.mkdir(parents=True, exist_ok=True)
        if os.path.lexists(self._path):
            self._assert_database_file()
            return
        flags = os.O_RDWR | os.O_CREAT | os.O_EXCL
        flags |= getattr(os, "O_NOFOLLOW", 0)
        fd = os.open(self._path, flags, 0o600)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)
        self._assert_database_file()

    def _assert_database_file(self) -> None:
        try:
            info = self._path.lstat()
        except FileNotFoundError as exc:
            raise EmergencyActionError("emergency action database disappeared") from exc
        if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode):
            raise EmergencyActionError(
                "emergency action database must be a regular non-symlink file"
            )
        if hasattr(os, "getuid") and info.st_uid != os.getuid():
            raise EmergencyActionError(
                "emergency action database is owned by a different runtime user"
            )
        try:
            self._path.chmod(0o600)
        except OSError:
            pass

    def _conn(self) -> sqlite3.Connection:
        self._assert_database_file()
        conn = sqlite3.connect(str(self._path), timeout=5.0, isolation_level=None)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA busy_timeout=5000")
        conn.execute("PRAGMA synchronous=FULL")
        return conn

    @staticmethod
    def _normalize_ddl(sql: str) -> str:
        return "".join(str(sql or "").lower().replace('"', "").split())

    @classmethod
    def _action_table_ddl(
        cls,
        table_name: str,
        *,
        if_not_exists: bool,
        include_filled_residual: bool = True,
        include_manual_unknown_flat: bool = True,
    ) -> str:
        if table_name not in {
            "emergency_close_actions",
            "emergency_close_actions__v2_new",
        }:
            raise ValueError("unsupported emergency action schema table name")
        existence = "IF NOT EXISTS " if if_not_exists else ""
        filled_residual = ",'filled_residual'" if include_filled_residual else ""
        manual_unknown = ",'manual_unknown_flat'" if include_manual_unknown_flat else ""
        return f"""
                CREATE TABLE {existence}{table_name} (
                    action_ref TEXT PRIMARY KEY,
                    owner_user_id TEXT NOT NULL,
                    halt_ref TEXT NOT NULL,
                    owner_epoch INTEGER NOT NULL CHECK(owner_epoch > 0),
                    account_ref TEXT NOT NULL,
                    account_epoch INTEGER NOT NULL CHECK(account_epoch > 0),
                    credential_binding_ref TEXT NOT NULL,
                    symbol TEXT NOT NULL,
                    attempt_no INTEGER NOT NULL CHECK(attempt_no > 0),
                    side TEXT NOT NULL CHECK(side IN ('buy','sell')),
                    quantity_text TEXT NOT NULL,
                    client_order_id TEXT NOT NULL UNIQUE,
                    action_identity_hash TEXT NOT NULL,
                    request_hash TEXT NOT NULL,
                    status TEXT NOT NULL CHECK(status IN (
                        'prepared','submitting','acknowledged','pending','terminal_partial'{filled_residual}{manual_unknown},
                        'reconciled','failed'
                    )),
                    venue_order_id TEXT NOT NULL DEFAULT '',
                    terminal_status TEXT NOT NULL DEFAULT '',
                    cumulative_filled_qty_text TEXT NOT NULL DEFAULT '0',
                    ack_response_hash TEXT NOT NULL DEFAULT '',
                    observation_ref TEXT NOT NULL DEFAULT '',
                    observation_raw_hash TEXT NOT NULL DEFAULT '',
                    verified_flat INTEGER NOT NULL DEFAULT 0 CHECK(verified_flat IN (0,1)),
                    last_event_ref TEXT NOT NULL DEFAULT '',
                    created_at_utc TEXT NOT NULL,
                    updated_at_utc TEXT NOT NULL,
                    integrity_key_version TEXT NOT NULL,
                    integrity_seal TEXT NOT NULL,
                    UNIQUE(owner_user_id, halt_ref, owner_epoch, account_ref,
                           account_epoch, symbol, attempt_no)
                )
        """

    @staticmethod
    def _event_table_ddl(*, if_not_exists: bool) -> str:
        existence = "IF NOT EXISTS " if if_not_exists else ""
        return f"""
                CREATE TABLE {existence}emergency_close_action_events (
                    seq INTEGER PRIMARY KEY AUTOINCREMENT,
                    event_ref TEXT NOT NULL UNIQUE,
                    action_ref TEXT NOT NULL,
                    event_kind TEXT NOT NULL,
                    previous_event_ref TEXT NOT NULL,
                    snapshot_json TEXT NOT NULL,
                    created_at_utc TEXT NOT NULL,
                    integrity_key_version TEXT NOT NULL,
                    integrity_seal TEXT NOT NULL,
                    FOREIGN KEY(action_ref) REFERENCES emergency_close_actions(action_ref)
                        DEFERRABLE INITIALLY DEFERRED
                )
        """

    @staticmethod
    def _resolution_table_ddl(*, if_not_exists: bool) -> str:
        existence = "IF NOT EXISTS " if if_not_exists else ""
        return f"""
                CREATE TABLE {existence}emergency_unknown_submission_resolutions (
                    resolution_ref TEXT PRIMARY KEY,
                    action_ref TEXT NOT NULL UNIQUE,
                    owner_user_id TEXT NOT NULL,
                    original_halt_ref TEXT NOT NULL,
                    original_owner_epoch INTEGER NOT NULL CHECK(original_owner_epoch > 0),
                    resolving_halt_ref TEXT NOT NULL,
                    resolving_owner_epoch INTEGER NOT NULL CHECK(resolving_owner_epoch > 0),
                    account_ref TEXT NOT NULL,
                    account_epoch INTEGER NOT NULL CHECK(account_epoch > 0),
                    operator_user_id TEXT NOT NULL,
                    decision TEXT NOT NULL CHECK(decision='preserve_unknown_and_forbid_retry'),
                    operator_auth_audit_ref TEXT NOT NULL,
                    lookup_code INTEGER NOT NULL CHECK(lookup_code=-2013),
                    lookup_evidence_ref TEXT NOT NULL,
                    lookup_evidence_hash TEXT NOT NULL,
                    lookup_observed_at_utc TEXT NOT NULL,
                    flat_verification_json TEXT NOT NULL,
                    flat_verification_ref TEXT NOT NULL,
                    flat_verification_hash TEXT NOT NULL,
                    flat_observed_at_utc TEXT NOT NULL,
                    historical_submission_outcome TEXT NOT NULL CHECK(historical_submission_outcome='unknown'),
                    historical_fill_state TEXT NOT NULL CHECK(historical_fill_state='unknown'),
                    automatic_retry_permitted INTEGER NOT NULL CHECK(automatic_retry_permitted=0),
                    expected_action_event_ref TEXT NOT NULL,
                    created_at_utc TEXT NOT NULL,
                    integrity_key_version TEXT NOT NULL,
                    integrity_seal TEXT NOT NULL,
                    FOREIGN KEY(action_ref) REFERENCES emergency_close_actions(action_ref)
                        DEFERRABLE INITIALLY DEFERRED
                )
        """

    @staticmethod
    def _index_ddls(
        *,
        if_not_exists: bool,
        include_resolution: bool = True,
        include_manual_unknown_flat: bool = True,
    ) -> dict[str, str]:
        existence = "IF NOT EXISTS " if if_not_exists else ""
        manual_unknown = ",'manual_unknown_flat'" if include_manual_unknown_flat else ""
        ddls = {
            "idx_emergency_actions_halt": (
                f"CREATE INDEX {existence}idx_emergency_actions_halt "
                "ON emergency_close_actions(owner_user_id, halt_ref, owner_epoch, "
                "account_ref, account_epoch)"
            ),
            "idx_emergency_one_active_symbol_action": (
                f"CREATE UNIQUE INDEX {existence}idx_emergency_one_active_symbol_action "
                "ON emergency_close_actions("
                "owner_user_id,halt_ref,owner_epoch,account_ref,account_epoch,symbol) "
                "WHERE status IN ('prepared','submitting','acknowledged','pending'"
                f"{manual_unknown})"
            ),
            "idx_emergency_one_active_account_epoch_symbol": (
                f"CREATE UNIQUE INDEX {existence}idx_emergency_one_active_account_epoch_symbol "
                "ON emergency_close_actions("
                "owner_user_id,account_ref,account_epoch,symbol) "
                "WHERE status IN ('prepared','submitting','acknowledged','pending'"
                f"{manual_unknown})"
            ),
            "idx_emergency_action_events_action": (
                f"CREATE INDEX {existence}idx_emergency_action_events_action "
                "ON emergency_close_action_events(action_ref, seq)"
            ),
        }
        if include_resolution:
            ddls["idx_emergency_unknown_resolution_action"] = (
                f"CREATE UNIQUE INDEX {existence}idx_emergency_unknown_resolution_action "
                "ON emergency_unknown_submission_resolutions(action_ref)"
            )
        return ddls

    def _init_schema(self) -> None:
        conn = self._conn()
        try:
            tables = {
                str(row[0])
                for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
                ).fetchall()
            }
            if tables:
                if tables not in (
                    {
                        "emergency_close_actions",
                        "emergency_close_action_events",
                    },
                    {
                        "emergency_close_actions",
                        "emergency_close_action_events",
                        "emergency_unknown_submission_resolutions",
                    },
                ):
                    raise EmergencyActionError(
                        "emergency action database contains an unsupported table layout"
                    )
                return
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("BEGIN IMMEDIATE")
            conn.execute(
                self._action_table_ddl(
                    "emergency_close_actions",
                    if_not_exists=False,
                )
            )
            index_ddls = self._index_ddls(if_not_exists=False)
            for name in (
                "idx_emergency_actions_halt",
                "idx_emergency_one_active_symbol_action",
                "idx_emergency_one_active_account_epoch_symbol",
            ):
                conn.execute(index_ddls[name])
            conn.execute(self._event_table_ddl(if_not_exists=False))
            conn.execute(index_ddls["idx_emergency_action_events_action"])
            conn.execute(self._resolution_table_ddl(if_not_exists=False))
            conn.execute(index_ddls["idx_emergency_unknown_resolution_action"])
            conn.execute(f"PRAGMA user_version={self.SCHEMA_VERSION}")
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def _database_has_evidence(self) -> bool:
        with self._conn() as conn:
            return (
                conn.execute("SELECT 1 FROM emergency_close_actions LIMIT 1").fetchone()
                is not None
                or conn.execute(
                    "SELECT 1 FROM emergency_close_action_events LIMIT 1"
                ).fetchone()
                is not None
            )

    def _require_supported_schema(self, conn: sqlite3.Connection) -> str:
        rows = conn.execute(
            "SELECT type,name,sql FROM sqlite_master "
            "WHERE name NOT LIKE 'sqlite_%' ORDER BY type,name"
        ).fetchall()
        objects = {str(row["name"]): row for row in rows}
        object_names = set(objects)
        if object_names not in (
            set(self._PRE_RESOLUTION_SCHEMA_OBJECTS),
            set(self._EXPECTED_SCHEMA_OBJECTS),
        ):
            raise EmergencyActionError(
                "emergency action database contains unsupported schema objects"
            )
        has_resolution = (
            "emergency_unknown_submission_resolutions" in objects
        )
        if any(
            str(objects[name]["type"]) != "table"
            for name in (
                "emergency_close_actions",
                "emergency_close_action_events",
                *(
                    ("emergency_unknown_submission_resolutions",)
                    if has_resolution
                    else ()
                ),
            )
        ) or any(
            str(objects[name]["type"]) != "index"
            for name in object_names
            if name.startswith("idx_")
        ):
            raise EmergencyActionError(
                "emergency action database schema object types are invalid"
            )

        actual_action = self._normalize_ddl(objects["emergency_close_actions"]["sql"])
        latest_action = self._normalize_ddl(
            self._action_table_ddl(
                "emergency_close_actions",
                if_not_exists=False,
                include_filled_residual=True,
                include_manual_unknown_flat=True,
            )
        )
        v2_action = self._normalize_ddl(
            self._action_table_ddl(
                "emergency_close_actions",
                if_not_exists=False,
                include_filled_residual=True,
                include_manual_unknown_flat=False,
            )
        )
        legacy_action = self._normalize_ddl(
            self._action_table_ddl(
                "emergency_close_actions",
                if_not_exists=False,
                include_filled_residual=False,
                include_manual_unknown_flat=False,
            )
        )
        if actual_action == latest_action:
            layout = "latest"
        elif actual_action == v2_action:
            layout = "v2"
        elif actual_action == legacy_action:
            layout = "legacy"
        else:
            raise EmergencyActionError(
                "emergency action table constraints differ from supported schemas"
            )

        expected_event = self._normalize_ddl(
            self._event_table_ddl(if_not_exists=False)
        )
        if self._normalize_ddl(objects["emergency_close_action_events"]["sql"]) != expected_event:
            raise EmergencyActionError(
                "emergency action event table differs from the supported schema"
            )
        if has_resolution:
            expected_resolution = self._normalize_ddl(
                self._resolution_table_ddl(if_not_exists=False)
            )
            if self._normalize_ddl(
                objects["emergency_unknown_submission_resolutions"]["sql"]
            ) != expected_resolution:
                raise EmergencyActionError(
                    "emergency unknown-submission resolution table differs from the supported schema"
                )
        latest_indexes = self._index_ddls(
            if_not_exists=False,
            include_resolution=has_resolution,
            include_manual_unknown_flat=True,
        )
        pre_manual_indexes = self._index_ddls(
            if_not_exists=False,
            include_resolution=has_resolution,
            include_manual_unknown_flat=False,
        )

        def indexes_match(expected: dict[str, str]) -> bool:
            return all(
                self._normalize_ddl(objects[name]["sql"])
                == self._normalize_ddl(expected_sql)
                for name, expected_sql in expected.items()
            )

        if indexes_match(latest_indexes):
            index_layout = "latest"
        elif indexes_match(pre_manual_indexes):
            index_layout = "pre_manual_unknown"
        else:
            raise EmergencyActionError(
                "emergency action indexes differ from the supported schemas"
            )

        columns = tuple(
            str(row["name"])
            for row in conn.execute(
                "PRAGMA table_info(emergency_close_actions)"
            ).fetchall()
        )
        if columns != self._ACTION_DB_FIELDS:
            raise EmergencyActionError(
                "emergency action table columns differ from the supported schema"
            )
        version = int(conn.execute("PRAGMA user_version").fetchone()[0])
        if version not in {0, 2, 3, self.SCHEMA_VERSION}:
            raise EmergencyActionError(
                f"unsupported emergency action schema version: {version}"
            )
        if version == 0 and (
            layout != "legacy"
            or has_resolution
            or index_layout != "pre_manual_unknown"
        ):
            raise EmergencyActionError(
                "emergency action legacy schema version conflicts with its layout"
            )
        if version == 2 and (
            layout != "v2"
            or has_resolution
            or index_layout != "pre_manual_unknown"
        ):
            raise EmergencyActionError(
                "emergency action schema version 2 conflicts with its layout"
            )
        if version == 3 and (
            layout != "latest"
            or not has_resolution
            or index_layout != "pre_manual_unknown"
        ):
            raise EmergencyActionError(
                "emergency action schema version 3 conflicts with its index constraints"
            )
        if version == self.SCHEMA_VERSION and (
            layout != "latest"
            or not has_resolution
            or index_layout != "latest"
        ):
            raise EmergencyActionError(
                "emergency action schema version conflicts with its table constraints"
            )
        return "v3" if version == 3 else layout

    @staticmethod
    def _require_database_integrity(conn: sqlite3.Connection) -> None:
        foreign_key_errors = conn.execute("PRAGMA foreign_key_check").fetchall()
        if foreign_key_errors:
            raise EmergencyActionError(
                "emergency action database foreign-key check failed"
            )
        rows = conn.execute("PRAGMA integrity_check").fetchall()
        if len(rows) != 1 or str(rows[0][0]).lower() != "ok":
            raise EmergencyActionError(
                "emergency action database integrity check failed"
            )

    def _migrate_schema_after_replay(self) -> None:
        """Atomically widen the sealed action status CHECK after replay validation."""

        with self._lock:
            conn = self._conn()
            transaction_started = False
            try:
                mode = str(conn.execute("PRAGMA journal_mode=WAL").fetchone()[0]).lower()
                if mode != "wal":
                    raise EmergencyActionError(
                        "emergency action database could not enable WAL mode"
                    )
                conn.execute("PRAGMA foreign_keys=OFF")
                if int(conn.execute("PRAGMA foreign_keys").fetchone()[0]) != 0:
                    raise EmergencyActionError(
                        "emergency action schema migration could not disable foreign keys"
                    )
                conn.execute("BEGIN IMMEDIATE")
                transaction_started = True
                layout = self._require_supported_schema(conn)
                self._require_database_integrity(conn)
                self._validate_replay_conn(conn)

                if layout in {"legacy", "v2"}:
                    conn.execute(
                        self._action_table_ddl(
                            "emergency_close_actions__v2_new",
                            if_not_exists=False,
                            include_filled_residual=True,
                            include_manual_unknown_flat=True,
                        )
                    )
                    columns = ",".join(self._ACTION_DB_FIELDS)
                    conn.execute(
                        "INSERT INTO emergency_close_actions__v2_new ("
                        + columns
                        + ") SELECT "
                        + columns
                        + " FROM emergency_close_actions"
                    )
                    old_count = int(
                        conn.execute(
                            "SELECT COUNT(*) FROM emergency_close_actions"
                        ).fetchone()[0]
                    )
                    new_count = int(
                        conn.execute(
                            "SELECT COUNT(*) FROM emergency_close_actions__v2_new"
                        ).fetchone()[0]
                    )
                    if old_count != new_count:
                        raise EmergencyActionError(
                            "emergency action schema migration row count changed"
                        )
                    old_minus_new = conn.execute(
                        "SELECT "
                        + columns
                        + " FROM emergency_close_actions EXCEPT SELECT "
                        + columns
                        + " FROM emergency_close_actions__v2_new LIMIT 1"
                    ).fetchone()
                    new_minus_old = conn.execute(
                        "SELECT "
                        + columns
                        + " FROM emergency_close_actions__v2_new EXCEPT SELECT "
                        + columns
                        + " FROM emergency_close_actions LIMIT 1"
                    ).fetchone()
                    if old_minus_new is not None or new_minus_old is not None:
                        raise EmergencyActionError(
                            "emergency action schema migration changed sealed row values"
                        )
                    conn.execute("DROP TABLE emergency_close_actions")
                    conn.execute(
                        "ALTER TABLE emergency_close_actions__v2_new "
                        "RENAME TO emergency_close_actions"
                    )
                    index_ddls = self._index_ddls(if_not_exists=False)
                    for name in (
                        "idx_emergency_actions_halt",
                        "idx_emergency_one_active_symbol_action",
                        "idx_emergency_one_active_account_epoch_symbol",
                    ):
                        conn.execute(index_ddls[name])
                    conn.execute(self._resolution_table_ddl(if_not_exists=False))
                    conn.execute(
                        index_ddls["idx_emergency_unknown_resolution_action"]
                    )
                elif layout == "v3":
                    index_ddls = self._index_ddls(if_not_exists=False)
                    for name in (
                        "idx_emergency_one_active_symbol_action",
                        "idx_emergency_one_active_account_epoch_symbol",
                    ):
                        conn.execute(f"DROP INDEX {name}")
                        conn.execute(index_ddls[name])

                conn.execute(f"PRAGMA user_version={self.SCHEMA_VERSION}")
                if self._require_supported_schema(conn) != "latest":
                    raise EmergencyActionError(
                        "emergency action schema migration did not reach the latest layout"
                    )
                self._require_database_integrity(conn)
                self._validate_replay_conn(conn)
                conn.commit()
                transaction_started = False
            except Exception:
                if transaction_started:
                    conn.rollback()
                raise
            finally:
                try:
                    conn.execute("PRAGMA foreign_keys=ON")
                    if int(conn.execute("PRAGMA foreign_keys").fetchone()[0]) != 1:
                        raise EmergencyActionError(
                            "emergency action database could not restore foreign keys"
                        )
                finally:
                    conn.close()

    @staticmethod
    def _load_or_create_key(path: Path) -> bytes:
        path.parent.mkdir(parents=True, exist_ok=True)
        if os.path.lexists(path):
            info = path.lstat()
            if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode):
                raise EmergencyActionError(
                    "emergency action integrity key must be a regular non-symlink file"
                )
            if hasattr(os, "getuid") and info.st_uid != os.getuid():
                raise EmergencyActionError(
                    "emergency action integrity key is owned by a different runtime user"
                )
        try:
            key = path.read_bytes()
        except FileNotFoundError:
            candidate = secrets.token_bytes(32)
            try:
                flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
                flags |= getattr(os, "O_NOFOLLOW", 0)
                fd = os.open(path, flags, 0o600)
            except FileExistsError:
                key = path.read_bytes()
            else:
                try:
                    os.write(fd, candidate)
                    os.fsync(fd)
                finally:
                    os.close(fd)
                key = candidate
        if len(key) < 32:
            raise EmergencyActionError(f"invalid emergency action integrity key at {path}")
        info = path.lstat()
        if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode):
            raise EmergencyActionError(
                "emergency action integrity key must be a regular non-symlink file"
            )
        try:
            path.chmod(0o600)
        except OSError:
            pass
        return key

    def _owner_key(self, owner_user_id: str) -> bytes:
        return hmac.new(
            self._key,
            ("quantbt:emergency-action:" + owner_user_id).encode("utf-8"),
            hashlib.sha256,
        ).digest()

    def _seal(self, owner_user_id: str, payload: dict[str, Any]) -> str:
        return hmac.new(
            self._owner_key(owner_user_id),
            canonical_json(payload).encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()

    @classmethod
    def _snapshot_from_mapping(cls, values: dict[str, Any] | sqlite3.Row) -> dict[str, Any]:
        snapshot = {field: values[field] for field in cls._ACTION_FIELDS}
        for field in ("owner_epoch", "account_epoch", "attempt_no"):
            snapshot[field] = int(snapshot[field])
        snapshot["verified_flat"] = bool(snapshot["verified_flat"])
        return snapshot

    @classmethod
    def _action_from_snapshot(cls, snapshot: dict[str, Any]) -> EmergencyCloseAction:
        try:
            return EmergencyCloseAction(**{field: snapshot[field] for field in cls._ACTION_FIELDS})
        except (KeyError, TypeError, ValueError) as exc:
            raise EmergencyActionError("emergency action snapshot is malformed") from exc

    @staticmethod
    def _timezone_aware(value: object, *, field: str) -> str:
        text = _required(value, field=field)
        try:
            parsed = datetime.fromisoformat(text)
        except ValueError as exc:
            raise EmergencyActionError(
                f"emergency unknown-submission {field} is malformed"
            ) from exc
        if parsed.tzinfo is None:
            raise EmergencyActionError(
                f"emergency unknown-submission {field} is not timezone-aware"
            )
        return text

    @staticmethod
    def _flat_verification(value: object) -> dict[str, Any]:
        if not isinstance(value, dict) or value.get("ok") is not True:
            raise EmergencyActionError(
                "emergency unknown-submission resolution requires successful fresh flat verification"
            )
        for field in (
            "normal_open_order_refs",
            "algo_open_order_refs",
            "open_positions",
        ):
            if value.get(field) != []:
                raise EmergencyActionError(
                    "emergency unknown-submission resolution requires zero current venue exposure"
                )
        try:
            return json.loads(
                json.dumps(
                    value,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                    allow_nan=False,
                )
            )
        except (TypeError, ValueError) as exc:
            raise EmergencyActionError(
                "emergency unknown-submission flat verification is not canonical JSON"
            ) from exc

    @classmethod
    def _resolution_identity(
        cls,
        resolution: EmergencyUnknownSubmissionResolution,
    ) -> dict[str, Any]:
        payload = resolution.to_dict()
        payload.pop("resolution_ref", None)
        return payload

    @classmethod
    def _resolution_from_row(
        cls,
        row: sqlite3.Row,
    ) -> EmergencyUnknownSubmissionResolution:
        try:
            flat_verification = json.loads(str(row["flat_verification_json"]))
            return EmergencyUnknownSubmissionResolution(
                resolution_ref=str(row["resolution_ref"]),
                action_ref=str(row["action_ref"]),
                owner_user_id=str(row["owner_user_id"]),
                original_halt_ref=str(row["original_halt_ref"]),
                original_owner_epoch=int(row["original_owner_epoch"]),
                resolving_halt_ref=str(row["resolving_halt_ref"]),
                resolving_owner_epoch=int(row["resolving_owner_epoch"]),
                account_ref=str(row["account_ref"]),
                account_epoch=int(row["account_epoch"]),
                operator_user_id=str(row["operator_user_id"]),
                decision=str(row["decision"]),
                operator_auth_audit_ref=str(row["operator_auth_audit_ref"]),
                lookup_code=int(row["lookup_code"]),
                lookup_evidence_ref=str(row["lookup_evidence_ref"]),
                lookup_evidence_hash=str(row["lookup_evidence_hash"]),
                lookup_observed_at_utc=str(row["lookup_observed_at_utc"]),
                flat_verification=flat_verification,
                flat_verification_ref=str(row["flat_verification_ref"]),
                flat_verification_hash=str(row["flat_verification_hash"]),
                flat_observed_at_utc=str(row["flat_observed_at_utc"]),
                historical_submission_outcome=str(
                    row["historical_submission_outcome"]
                ),
                historical_fill_state=str(row["historical_fill_state"]),
                automatic_retry_permitted=bool(
                    row["automatic_retry_permitted"]
                ),
                expected_action_event_ref=str(row["expected_action_event_ref"]),
                created_at_utc=str(row["created_at_utc"]),
            )
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise EmergencyActionError(
                "emergency unknown-submission resolution row is malformed"
            ) from exc

    def _validated_resolution_row(
        self,
        conn: sqlite3.Connection,
        row: sqlite3.Row,
        *,
        action: EmergencyCloseAction | None = None,
    ) -> EmergencyUnknownSubmissionResolution:
        resolution = self._resolution_from_row(row)
        owner = _required(resolution.owner_user_id, field="resolution owner_user_id")
        if resolution.operator_user_id != owner:
            raise EmergencyActionError(
                "emergency unknown-submission operator must equal the action owner"
            )
        if resolution.decision != self.UNKNOWN_RESOLUTION_DECISION:
            raise EmergencyActionError(
                "emergency unknown-submission resolution decision is unsupported"
            )
        if (
            resolution.historical_submission_outcome
            != self.UNKNOWN_SUBMISSION_OUTCOME
            or resolution.historical_fill_state != self.UNKNOWN_FILL_STATE
            or resolution.automatic_retry_permitted is not False
        ):
            raise EmergencyActionError(
                "emergency unknown-submission resolution overstates historical certainty or retry authority"
            )
        _positive_epoch(resolution.original_owner_epoch)
        _positive_epoch(resolution.resolving_owner_epoch)
        _positive_epoch(resolution.account_epoch)
        _required(resolution.original_halt_ref, field="original_halt_ref")
        _required(resolution.resolving_halt_ref, field="resolving_halt_ref")
        _required(resolution.account_ref, field="account_ref")
        _required(resolution.operator_auth_audit_ref, field="operator_auth_audit_ref")
        expected_head = _required(
            resolution.expected_action_event_ref,
            field="expected_action_event_ref",
        )
        lookup_at = self._timezone_aware(
            resolution.lookup_observed_at_utc,
            field="lookup_observed_at_utc",
        )
        flat_at = self._timezone_aware(
            resolution.flat_observed_at_utc,
            field="flat_observed_at_utc",
        )
        created_at = self._timezone_aware(
            resolution.created_at_utc,
            field="created_at_utc",
        )
        lookup_time = datetime.fromisoformat(lookup_at)
        flat_time = datetime.fromisoformat(flat_at)
        created_time = datetime.fromisoformat(created_at)
        if not lookup_time <= flat_time <= created_time:
            raise EmergencyActionError(
                "emergency unknown-submission persisted evidence chronology is invalid"
            )
        if (
            (flat_time - lookup_time).total_seconds() > 120
            or (created_time - lookup_time).total_seconds() > 300
        ):
            raise EmergencyActionError(
                "emergency unknown-submission persisted evidence is outside its causal window"
            )
        if type(resolution.lookup_code) is not int or resolution.lookup_code != -2013:
            raise EmergencyActionError(
                "emergency unknown-submission resolution requires exact lookup code -2013"
            )
        flat = self._flat_verification(resolution.flat_verification)
        action_row = action
        if action_row is None:
            raw_action = conn.execute(
                "SELECT * FROM emergency_close_actions WHERE action_ref=?",
                (resolution.action_ref,),
            ).fetchone()
            if raw_action is None:
                raise EmergencyActionError(
                    "emergency unknown-submission resolution action is missing"
                )
            action_row = self._validated_action_row(conn, raw_action)
        if (
            action_row.owner_user_id != owner
            or action_row.halt_ref != resolution.original_halt_ref
            or action_row.owner_epoch != resolution.original_owner_epoch
            or action_row.account_ref != resolution.account_ref
            or action_row.account_epoch != resolution.account_epoch
        ):
            raise EmergencyActionError(
                "emergency unknown-submission resolution scope differs from its action"
            )
        lookup_payload = {
            "action_ref": action_row.action_ref,
            "client_order_id": action_row.client_order_id,
            "lookup_code": -2013,
            "lookup_observed_at_utc": lookup_at,
        }
        lookup_digest = _sha256(canonical_json(lookup_payload))
        if (
            resolution.lookup_evidence_ref
            != "emergency_lookup_sha256_" + lookup_digest
            or resolution.lookup_evidence_hash != "sha256:" + lookup_digest
        ):
            raise EmergencyActionError(
                "emergency unknown-submission lookup evidence identity is invalid"
            )
        flat_payload = {
            "action_ref": action_row.action_ref,
            "account_ref": action_row.account_ref,
            "account_epoch": action_row.account_epoch,
            "flat_verification": flat,
            "flat_observed_at_utc": flat_at,
        }
        flat_digest = _sha256(canonical_json(flat_payload))
        if (
            resolution.flat_verification_ref
            != "emergency_unknown_flat_sha256_" + flat_digest
            or resolution.flat_verification_hash != "sha256:" + flat_digest
        ):
            raise EmergencyActionError(
                "emergency unknown-submission flat evidence identity is invalid"
            )
        resolution_digest = _sha256(
            canonical_json(self._resolution_identity(resolution))
        )
        if resolution.resolution_ref != (
            "emergency_unknown_resolution_sha256_" + resolution_digest
        ):
            raise EmergencyActionError(
                "emergency unknown-submission resolution identity is invalid"
            )
        if str(row["integrity_key_version"]) != self.KEY_VERSION:
            raise EmergencyActionError(
                "emergency unknown-submission resolution key version is unsupported"
            )
        seal_payload = {
            "resolution": resolution.to_dict(),
            "integrity_key_version": self.KEY_VERSION,
        }
        if not hmac.compare_digest(
            str(row["integrity_seal"]),
            self._seal(owner, seal_payload),
        ):
            raise EmergencyActionError(
                "emergency unknown-submission resolution seal is invalid"
            )
        if action_row.status != "manual_unknown_flat":
            raise EmergencyActionError(
                "emergency unknown-submission resolution lacks its terminal action state"
            )
        if (
            action_row.terminal_status != "submission_unknown_manual_only"
            or action_row.observation_ref != resolution.resolution_ref
            or action_row.observation_raw_hash != resolution.flat_verification_hash
            or action_row.verified_flat is not True
        ):
            raise EmergencyActionError(
                "emergency unknown-submission terminal action differs from its resolution"
            )
        terminal_event = conn.execute(
            "SELECT * FROM emergency_close_action_events WHERE event_ref=?",
            (action_row.last_event_ref,),
        ).fetchone()
        if (
            terminal_event is None
            or str(terminal_event["event_kind"])
            != "manual_unknown_submission_resolved"
            or str(terminal_event["previous_event_ref"] or "") != expected_head
        ):
            raise EmergencyActionError(
                "emergency unknown-submission resolution action event linkage is invalid"
            )
        return resolution

    def _event_payload(
        self,
        *,
        event_kind: str,
        previous_event_ref: str,
        snapshot: dict[str, Any],
        created_at_utc: str,
    ) -> dict[str, Any]:
        return {
            "event_kind": event_kind,
            "previous_event_ref": previous_event_ref,
            "snapshot": snapshot,
            "created_at_utc": created_at_utc,
            "integrity_key_version": self.KEY_VERSION,
        }

    def _append_transition(
        self,
        conn: sqlite3.Connection,
        *,
        current: dict[str, Any],
        event_kind: str,
    ) -> EmergencyCloseAction:
        previous_event_ref = str(current.get("last_event_ref") or "")
        now = _now()
        current["updated_at_utc"] = now
        if not current.get("created_at_utc"):
            current["created_at_utc"] = now
        # The head ref is excluded from its own identity, avoiding a recursive
        # hash while still binding the current row to that immutable event.
        identity_snapshot = self._snapshot_from_mapping({**current, "last_event_ref": ""})
        event_payload = self._event_payload(
            event_kind=event_kind,
            previous_event_ref=previous_event_ref,
            snapshot=identity_snapshot,
            created_at_utc=now,
        )
        event_ref = "emergency_event_sha256_" + _sha256(canonical_json(event_payload))
        current["last_event_ref"] = event_ref
        snapshot = self._snapshot_from_mapping(current)
        action_payload = {
            "snapshot": snapshot,
            "integrity_key_version": self.KEY_VERSION,
        }
        action_seal = self._seal(str(current["owner_user_id"]), action_payload)
        event_seal = self._seal(str(current["owner_user_id"]), event_payload)

        columns = ",".join(self._ACTION_FIELDS)
        placeholders = ",".join("?" for _ in self._ACTION_FIELDS)
        updates = ",".join(f"{field}=excluded.{field}" for field in self._ACTION_FIELDS[1:])
        conn.execute(
            f"INSERT INTO emergency_close_actions ({columns},integrity_key_version,integrity_seal) "
            f"VALUES ({placeholders},?,?) ON CONFLICT(action_ref) DO UPDATE SET {updates},"
            "integrity_key_version=excluded.integrity_key_version,integrity_seal=excluded.integrity_seal",
            (
                *(
                    int(snapshot[field])
                    if field == "verified_flat"
                    else snapshot[field]
                    for field in self._ACTION_FIELDS
                ),
                self.KEY_VERSION,
                action_seal,
            ),
        )
        conn.execute(
            """
            INSERT INTO emergency_close_action_events (
                event_ref,action_ref,event_kind,previous_event_ref,snapshot_json,
                created_at_utc,integrity_key_version,integrity_seal
            ) VALUES (?,?,?,?,?,?,?,?)
            """,
            (
                event_ref,
                current["action_ref"],
                event_kind,
                previous_event_ref,
                canonical_json({**snapshot, "last_event_ref": ""}),
                now,
                self.KEY_VERSION,
                event_seal,
            ),
        )
        return self._action_from_snapshot(snapshot)

    @staticmethod
    def _request_identity(
        *,
        owner_user_id: str,
        halt_ref: str,
        owner_epoch: int,
        account_ref: str,
        account_epoch: int,
        credential_binding_ref: str,
        symbol: str,
        attempt_no: int,
        side: str,
        quantity_text: str,
    ) -> dict[str, Any]:
        return {
            "owner_user_id": owner_user_id,
            "halt_ref": halt_ref,
            "owner_epoch": owner_epoch,
            "account_ref": account_ref,
            "account_epoch": account_epoch,
            "credential_binding_ref": credential_binding_ref,
            "symbol": symbol,
            "attempt_no": attempt_no,
            "side": side,
            "quantity_text": quantity_text,
        }

    def prepare(
        self,
        *,
        owner_user_id: str,
        halt_ref: str,
        owner_epoch: int,
        account_ref: str,
        account_epoch: int,
        credential_binding_ref: str,
        symbol: str,
        side: Literal["buy", "sell"],
        quantity: object,
    ) -> EmergencyCloseAction:
        barrier = self._account_halt_barrier
        fence = (
            barrier.emergency_action_fence(  # type: ignore[attr-defined]
                owner_user_id=owner_user_id,
                owner_epoch=owner_epoch,
                halt_ref=halt_ref,
                account_binding_ref=account_ref,
                account_epoch=account_epoch,
            )
            if barrier is not None
            else nullcontext()
        )
        with fence:
            return self._prepare_under_fence(
                owner_user_id=owner_user_id,
                halt_ref=halt_ref,
                owner_epoch=owner_epoch,
                account_ref=account_ref,
                account_epoch=account_epoch,
                credential_binding_ref=credential_binding_ref,
                symbol=symbol,
                side=side,
                quantity=quantity,
            )

    def _prepare_under_fence(
        self,
        *,
        owner_user_id: str,
        halt_ref: str,
        owner_epoch: int,
        account_ref: str,
        account_epoch: int,
        credential_binding_ref: str,
        symbol: str,
        side: Literal["buy", "sell"],
        quantity: object,
    ) -> EmergencyCloseAction:
        owner = _required(owner_user_id, field="owner_user_id")
        halt = _required(halt_ref, field="halt_ref")
        resolved_owner_epoch = _positive_epoch(owner_epoch)
        account = _required(account_ref, field="account_ref")
        epoch = _positive_epoch(account_epoch)
        credential = _required(credential_binding_ref, field="credential_binding_ref")
        normalized_symbol = _required(symbol, field="symbol").upper()
        normalized_side = str(side or "").strip().lower()
        if normalized_side not in {"buy", "sell"}:
            raise ValueError("emergency action side must be buy or sell")
        qty = _quantity_text(quantity)
        action: EmergencyCloseAction
        # Fail before the SQLite mutation when an existing audit mirror is
        # malformed or diverges from the authoritative committed history.
        self.sync_mirror()
        with self._lock:
            conn = self._conn()
            try:
                conn.execute("BEGIN IMMEDIATE")
                self._validate_replay_conn(conn)
                superseded_active = conn.execute(
                    """
                    SELECT * FROM emergency_close_actions
                    WHERE owner_user_id=? AND account_ref=? AND account_epoch=? AND symbol=?
                      AND status IN (
                          'prepared','submitting','acknowledged','pending',
                          'manual_unknown_flat'
                      )
                      AND NOT (halt_ref=? AND owner_epoch=?)
                    ORDER BY attempt_no DESC LIMIT 1
                    """,
                    (
                        owner,
                        account,
                        epoch,
                        normalized_symbol,
                        halt,
                        resolved_owner_epoch,
                    ),
                ).fetchone()
                if superseded_active is not None:
                    prior = self._validated_action_row(conn, superseded_active)
                    raise EmergencyActionError(
                        "a prior HALT scope has an unresolved emergency action "
                        f"{prior.action_ref}"
                    )
                existing = conn.execute(
                    """
                    SELECT * FROM emergency_close_actions
                    WHERE owner_user_id=? AND halt_ref=? AND owner_epoch=?
                      AND account_ref=? AND account_epoch=? AND symbol=?
                    ORDER BY attempt_no DESC LIMIT 1
                    """,
                    (
                        owner,
                        halt,
                        resolved_owner_epoch,
                        account,
                        epoch,
                        normalized_symbol,
                    ),
                ).fetchone()
                attempt_no = 1
                if existing is not None:
                    latest = self._validated_action_row(conn, existing)
                    if latest.status not in {"failed", "terminal_partial", "filled_residual"}:
                        if (
                            latest.credential_binding_ref != credential
                            or latest.side != normalized_side
                            or latest.quantity_text != qty
                        ):
                            raise EmergencyActionError(
                                "emergency action scope was already prepared with different semantics"
                            )
                        conn.commit()
                        action = latest
                    else:
                        attempt_no = latest.attempt_no + 1
                        action = None  # type: ignore[assignment]
                else:
                    action = None  # type: ignore[assignment]
                if action is not None:
                    pass
                else:
                    identity = self._request_identity(
                        owner_user_id=owner,
                        halt_ref=halt,
                        owner_epoch=resolved_owner_epoch,
                        account_ref=account,
                        account_epoch=epoch,
                        credential_binding_ref=credential,
                        symbol=normalized_symbol,
                        attempt_no=attempt_no,
                        side=normalized_side,
                        quantity_text=qty,
                    )
                    digest = _sha256(canonical_json(identity))
                    action_ref = "emergency_action_sha256_" + digest
                    client_order_id = "qbt-kill-" + digest[:24]
                    request_params = emergency_close_request_params(
                        symbol=normalized_symbol,
                        side=normalized_side,  # type: ignore[arg-type]
                        quantity=qty,
                        client_order_id=client_order_id,
                    )
                    action_identity_hash = "sha256:" + digest
                    request_hash = emergency_close_request_hash(request_params)
                    current: dict[str, Any] = {
                        "action_ref": action_ref,
                        "owner_user_id": owner,
                        "halt_ref": halt,
                        "owner_epoch": resolved_owner_epoch,
                        "account_ref": account,
                        "account_epoch": epoch,
                        "credential_binding_ref": credential,
                        "symbol": normalized_symbol,
                        "attempt_no": attempt_no,
                        "side": normalized_side,
                        "quantity_text": qty,
                        "client_order_id": client_order_id,
                        "action_identity_hash": action_identity_hash,
                        "request_hash": request_hash,
                        "status": "prepared",
                        "venue_order_id": "",
                        "terminal_status": "",
                        "cumulative_filled_qty_text": "0",
                        "ack_response_hash": "",
                        "observation_ref": "",
                        "observation_raw_hash": "",
                        "verified_flat": False,
                        "last_event_ref": "",
                        "created_at_utc": "",
                        "updated_at_utc": "",
                    }
                    action = self._append_transition(
                        conn,
                        current=current,
                        event_kind="prepared",
                    )
                    conn.commit()
            except Exception:
                conn.rollback()
                raise
            finally:
                conn.close()
        self.sync_mirror()
        return action

    def _transition(
        self,
        action_ref: str,
        *,
        allowed: frozenset[str],
        status: EmergencyActionStatus,
        event_kind: str,
        updates: dict[str, Any] | None = None,
        allow_idempotent: bool = True,
    ) -> EmergencyCloseAction:
        ref = _required(action_ref, field="action_ref")
        # A known-bad mirror must not turn a successful source-of-truth commit
        # into a post-commit exception visible as a failed operation.
        self.sync_mirror()
        with self._lock:
            conn = self._conn()
            try:
                conn.execute("BEGIN IMMEDIATE")
                self._validate_replay_conn(conn)
                row = conn.execute(
                    "SELECT * FROM emergency_close_actions WHERE action_ref=?",
                    (ref,),
                ).fetchone()
                if row is None:
                    raise EmergencyActionError("emergency action is missing")
                current_action = self._validated_action_row(conn, row)
                if allow_idempotent and current_action.status == status and all(
                    getattr(current_action, key) == value for key, value in (updates or {}).items()
                ):
                    conn.commit()
                    return current_action
                if current_action.status not in allowed:
                    raise EmergencyActionError(
                        f"emergency action cannot transition from {current_action.status} to {status}"
                    )
                incoming_venue_order_id = str((updates or {}).get("venue_order_id") or "").strip()
                if (
                    incoming_venue_order_id
                    and current_action.venue_order_id
                    and incoming_venue_order_id != current_action.venue_order_id
                ):
                    raise EmergencyActionError(
                        "emergency action venue_order_id cannot change after first binding"
                    )
                current = current_action.to_dict()
                current["status"] = status
                current.update(updates or {})
                action = self._append_transition(conn, current=current, event_kind=event_kind)
                conn.commit()
            except Exception:
                conn.rollback()
                raise
            finally:
                conn.close()
        self.sync_mirror()
        return action

    def mark_submitting(self, action_ref: str) -> EmergencyCloseAction:
        return self._transition(
            action_ref,
            allowed=frozenset({"prepared"}),
            status="submitting",
            event_kind="request_boundary_crossed",
            allow_idempotent=False,
        )

    def mark_acknowledged(
        self,
        action_ref: str,
        *,
        venue_order_id: str,
        response_hash: str,
        cumulative_filled_qty: object,
        terminal_status: str,
    ) -> EmergencyCloseAction:
        order_id = _required(venue_order_id, field="venue_order_id")
        raw_hash = _full_sha256_ref(response_hash, field="ack_response_hash")
        filled = _quantity_text(cumulative_filled_qty)
        venue_status = _required(terminal_status, field="terminal_status").lower()
        return self._transition(
            action_ref,
            allowed=frozenset({"submitting"}),
            status="acknowledged",
            event_kind="venue_acknowledged",
            updates={
                "venue_order_id": order_id,
                "ack_response_hash": raw_hash,
                "cumulative_filled_qty_text": filled,
                "terminal_status": venue_status,
            },
        )

    def mark_pending(
        self,
        action_ref: str,
        *,
        venue_order_id: str,
        observation_ref: str,
        response_hash: str,
        cumulative_filled_qty: object,
        terminal_status: str,
    ) -> EmergencyCloseAction:
        raw_hash = _full_sha256_ref(response_hash, field="observation_raw_hash")
        return self._transition(
            action_ref,
            allowed=frozenset({"submitting", "acknowledged", "pending"}),
            status="pending",
            event_kind="venue_observed_pending",
            updates={
                "venue_order_id": _required(venue_order_id, field="venue_order_id"),
                "observation_ref": _required(observation_ref, field="observation_ref"),
                "observation_raw_hash": raw_hash,
                "cumulative_filled_qty_text": (
                    "0" if Decimal(str(cumulative_filled_qty)) == 0 else _quantity_text(cumulative_filled_qty)
                ),
                "terminal_status": _required(terminal_status, field="terminal_status").lower(),
            },
        )

    def mark_reconciled(
        self,
        action_ref: str,
        *,
        venue_order_id: str,
        observation_ref: str,
        response_hash: str,
        cumulative_filled_qty: object,
        terminal_status: str,
        verified_flat: bool,
    ) -> EmergencyCloseAction:
        if verified_flat is not True:
            raise ValueError("emergency action reconciliation requires fresh flat verification")
        current = self.action(action_ref)
        filled = _quantity_text(cumulative_filled_qty)
        if filled != current.quantity_text or str(terminal_status).strip().lower() != "filled":
            raise EmergencyActionError(
                "emergency action can reconcile only an exact fully-filled close"
            )
        return self._transition(
            action_ref,
            allowed=frozenset({"submitting", "acknowledged", "pending"}),
            status="reconciled",
            event_kind="reconciled_flat",
            updates={
                "venue_order_id": _required(venue_order_id, field="venue_order_id"),
                "observation_ref": _required(observation_ref, field="observation_ref"),
                "observation_raw_hash": _full_sha256_ref(
                    response_hash,
                    field="observation_raw_hash",
                ),
                "cumulative_filled_qty_text": filled,
                "terminal_status": "filled",
                "verified_flat": True,
            },
        )

    def mark_failed(
        self,
        action_ref: str,
        *,
        venue_order_id: str,
        observation_ref: str,
        response_hash: str,
        cumulative_filled_qty: object,
        terminal_status: str,
    ) -> EmergencyCloseAction:
        raw_filled = Decimal(str(cumulative_filled_qty))
        if not raw_filled.is_finite() or raw_filled != 0:
            raise EmergencyActionError(
                "terminal emergency action failure with any fill remains unresolved"
            )
        terminal = _required(terminal_status, field="terminal_status").lower()
        if terminal not in {"rejected", "canceled", "expired"}:
            raise EmergencyActionError("emergency action failure status is not terminal")
        return self._transition(
            action_ref,
            allowed=frozenset({"submitting", "acknowledged", "pending"}),
            status="failed",
            event_kind="venue_terminal_failure",
            updates={
                "venue_order_id": _required(venue_order_id, field="venue_order_id"),
                "observation_ref": _required(observation_ref, field="observation_ref"),
                "observation_raw_hash": _full_sha256_ref(
                    response_hash,
                    field="observation_raw_hash",
                ),
                "cumulative_filled_qty_text": "0",
                "terminal_status": terminal,
                "verified_flat": False,
            },
        )

    def mark_pre_submit_superseded(self, action_ref: str) -> EmergencyCloseAction:
        """Close a prepared-only action after a stronger HALT scope replaces it."""

        return self._transition(
            action_ref,
            allowed=frozenset({"prepared"}),
            status="failed",
            event_kind="pre_submit_scope_superseded",
            updates={
                "terminal_status": "not_submitted",
                "cumulative_filled_qty_text": "0",
                "verified_flat": False,
            },
        )

    def mark_partial_terminal(
        self,
        action_ref: str,
        *,
        venue_order_id: str,
        observation_ref: str,
        response_hash: str,
        cumulative_filled_qty: object,
        terminal_status: str,
    ) -> EmergencyCloseAction:
        current = self.action(action_ref)
        filled = _quantity_text(cumulative_filled_qty)
        if Decimal(filled) >= Decimal(current.quantity_text):
            raise EmergencyActionError(
                "partial-terminal emergency action must be below requested quantity"
            )
        terminal = _required(terminal_status, field="terminal_status").lower()
        if terminal not in {"canceled", "expired"}:
            raise EmergencyActionError(
                "partial-terminal emergency action has a non-terminal status"
            )
        return self._transition(
            action_ref,
            allowed=frozenset({"submitting", "acknowledged", "pending"}),
            status="terminal_partial",
            event_kind="venue_terminal_partial",
            updates={
                "venue_order_id": _required(venue_order_id, field="venue_order_id"),
                "observation_ref": _required(observation_ref, field="observation_ref"),
                "observation_raw_hash": _full_sha256_ref(
                    response_hash,
                    field="observation_raw_hash",
                ),
                "cumulative_filled_qty_text": filled,
                "terminal_status": terminal,
                "verified_flat": False,
            },
        )

    def mark_filled_residual(
        self,
        action_ref: str,
        *,
        venue_order_id: str,
        observation_ref: str,
        response_hash: str,
        cumulative_filled_qty: object,
    ) -> EmergencyCloseAction:
        current = self.action(action_ref)
        filled = _quantity_text(cumulative_filled_qty)
        if filled != current.quantity_text:
            raise EmergencyActionError(
                "filled-residual emergency action does not cover its requested quantity"
            )
        return self._transition(
            action_ref,
            allowed=frozenset({"submitting", "acknowledged", "pending"}),
            status="filled_residual",
            event_kind="venue_filled_residual_exposure",
            updates={
                "venue_order_id": _required(venue_order_id, field="venue_order_id"),
                "observation_ref": _required(observation_ref, field="observation_ref"),
                "observation_raw_hash": _full_sha256_ref(
                    response_hash,
                    field="observation_raw_hash",
                ),
                "cumulative_filled_qty_text": filled,
                "terminal_status": "filled",
                "verified_flat": False,
            },
        )

    def resolve_unknown_submission(
        self,
        action_ref: str,
        *,
        owner_user_id: str,
        resolving_halt_ref: str,
        resolving_owner_epoch: int,
        account_ref: str,
        account_epoch: int,
        operator_user_id: str,
        operator_auth_audit_ref: str,
        lookup_code: int,
        lookup_observed_at_utc: str,
        flat_verification: dict[str, Any],
        flat_observed_at_utc: str,
        expected_action_event_ref: str,
    ) -> tuple[EmergencyCloseAction, EmergencyUnknownSubmissionResolution]:
        barrier = self._account_halt_barrier
        fence = (
            barrier.emergency_action_fence(  # type: ignore[attr-defined]
                owner_user_id=owner_user_id,
                owner_epoch=resolving_owner_epoch,
                halt_ref=resolving_halt_ref,
                account_binding_ref=account_ref,
                account_epoch=account_epoch,
            )
            if barrier is not None
            else nullcontext()
        )
        with fence:
            return self._resolve_unknown_submission_under_fence(
                action_ref,
                owner_user_id=owner_user_id,
                resolving_halt_ref=resolving_halt_ref,
                resolving_owner_epoch=resolving_owner_epoch,
                account_ref=account_ref,
                account_epoch=account_epoch,
                operator_user_id=operator_user_id,
                operator_auth_audit_ref=operator_auth_audit_ref,
                lookup_code=lookup_code,
                lookup_observed_at_utc=lookup_observed_at_utc,
                flat_verification=flat_verification,
                flat_observed_at_utc=flat_observed_at_utc,
                expected_action_event_ref=expected_action_event_ref,
            )

    def _resolve_unknown_submission_under_fence(
        self,
        action_ref: str,
        *,
        owner_user_id: str,
        resolving_halt_ref: str,
        resolving_owner_epoch: int,
        account_ref: str,
        account_epoch: int,
        operator_user_id: str,
        operator_auth_audit_ref: str,
        lookup_code: int,
        lookup_observed_at_utc: str,
        flat_verification: dict[str, Any],
        flat_observed_at_utc: str,
        expected_action_event_ref: str,
    ) -> tuple[EmergencyCloseAction, EmergencyUnknownSubmissionResolution]:
        """Atomically preserve an exact ``-2013`` outcome as unknown/no-retry."""

        ref = _required(action_ref, field="action_ref")
        owner = _required(owner_user_id, field="owner_user_id")
        operator = _required(operator_user_id, field="operator_user_id")
        if operator != owner:
            raise EmergencyActionError(
                "emergency unknown-submission operator must equal the action owner"
            )
        resolving_halt = _required(
            resolving_halt_ref,
            field="resolving_halt_ref",
        )
        resolving_epoch = _positive_epoch(resolving_owner_epoch)
        expected_account = _required(account_ref, field="account_ref")
        expected_account_epoch = _positive_epoch(account_epoch)
        auth_audit_ref = _required(
            operator_auth_audit_ref,
            field="operator_auth_audit_ref",
        )
        if type(lookup_code) is not int or lookup_code != -2013:
            raise EmergencyActionError(
                "emergency unknown-submission resolution requires exact lookup code -2013"
            )
        lookup_at = self._timezone_aware(
            lookup_observed_at_utc,
            field="lookup_observed_at_utc",
        )
        flat_at = self._timezone_aware(
            flat_observed_at_utc,
            field="flat_observed_at_utc",
        )
        lookup_time = datetime.fromisoformat(lookup_at)
        flat_time = datetime.fromisoformat(flat_at)
        flat = self._flat_verification(flat_verification)
        expected_head = _required(
            expected_action_event_ref,
            field="expected_action_event_ref",
        )
        self.sync_mirror()
        with self._lock:
            conn = self._conn()
            try:
                conn.execute("BEGIN IMMEDIATE")
                self._validate_replay_conn(conn)
                row = conn.execute(
                    "SELECT * FROM emergency_close_actions WHERE action_ref=?",
                    (ref,),
                ).fetchone()
                if row is None:
                    raise EmergencyActionError("emergency action is missing")
                current_action = self._validated_action_row(conn, row)
                if current_action.owner_user_id != owner:
                    raise EmergencyActionError(
                        "emergency action belongs to a different owner"
                    )
                if (
                    current_action.account_ref != expected_account
                    or current_action.account_epoch != expected_account_epoch
                ):
                    raise EmergencyActionError(
                        "emergency action belongs to a different account epoch"
                    )
                existing_row = conn.execute(
                    "SELECT * FROM emergency_unknown_submission_resolutions "
                    "WHERE action_ref=?",
                    (ref,),
                ).fetchone()
                if existing_row is not None:
                    resolution = self._validated_resolution_row(
                        conn,
                        existing_row,
                        action=current_action,
                    )
                    if (
                        resolution.resolving_halt_ref != resolving_halt
                        or resolution.resolving_owner_epoch != resolving_epoch
                        or resolution.operator_user_id != operator
                        or resolution.operator_auth_audit_ref != auth_audit_ref
                        or resolution.lookup_code != lookup_code
                        or resolution.lookup_observed_at_utc != lookup_at
                        or resolution.flat_verification != flat
                        or resolution.flat_observed_at_utc != flat_at
                        or resolution.expected_action_event_ref != expected_head
                    ):
                        raise EmergencyActionError(
                            "emergency unknown-submission exact retry differs from persisted resolution"
                        )
                    conn.commit()
                    return current_action, resolution
                now_time = datetime.now(UTC)
                if flat_time < lookup_time:
                    raise EmergencyActionError(
                        "emergency unknown-submission flat proof predates exact lookup"
                    )
                if (flat_time - lookup_time).total_seconds() > 120:
                    raise EmergencyActionError(
                        "emergency unknown-submission lookup and flat proof are not one fresh observation window"
                    )
                for field, observed in (
                    ("lookup_observed_at_utc", lookup_time),
                    ("flat_observed_at_utc", flat_time),
                ):
                    age_seconds = (now_time - observed).total_seconds()
                    if age_seconds > 300 or age_seconds < -30:
                        raise EmergencyActionError(
                            f"emergency unknown-submission {field} is stale or future-dated"
                        )
                if current_action.status not in {
                    "submitting",
                    "acknowledged",
                    "pending",
                }:
                    raise EmergencyActionError(
                        "only a submitted unresolved emergency action can be manually preserved as unknown"
                    )
                if current_action.last_event_ref != expected_head:
                    raise EmergencyActionError(
                        "emergency action head changed before unknown-submission resolution"
                    )
                lookup_payload = {
                    "action_ref": current_action.action_ref,
                    "client_order_id": current_action.client_order_id,
                    "lookup_code": -2013,
                    "lookup_observed_at_utc": lookup_at,
                }
                lookup_digest = _sha256(canonical_json(lookup_payload))
                flat_payload = {
                    "action_ref": current_action.action_ref,
                    "account_ref": current_action.account_ref,
                    "account_epoch": current_action.account_epoch,
                    "flat_verification": flat,
                    "flat_observed_at_utc": flat_at,
                }
                flat_digest = _sha256(canonical_json(flat_payload))
                created_at = _now()
                unresolved = EmergencyUnknownSubmissionResolution(
                    resolution_ref="",
                    action_ref=current_action.action_ref,
                    owner_user_id=owner,
                    original_halt_ref=current_action.halt_ref,
                    original_owner_epoch=current_action.owner_epoch,
                    resolving_halt_ref=resolving_halt,
                    resolving_owner_epoch=resolving_epoch,
                    account_ref=current_action.account_ref,
                    account_epoch=current_action.account_epoch,
                    operator_user_id=operator,
                    decision=self.UNKNOWN_RESOLUTION_DECISION,
                    operator_auth_audit_ref=auth_audit_ref,
                    lookup_code=-2013,
                    lookup_evidence_ref="emergency_lookup_sha256_" + lookup_digest,
                    lookup_evidence_hash="sha256:" + lookup_digest,
                    lookup_observed_at_utc=lookup_at,
                    flat_verification=flat,
                    flat_verification_ref=(
                        "emergency_unknown_flat_sha256_" + flat_digest
                    ),
                    flat_verification_hash="sha256:" + flat_digest,
                    flat_observed_at_utc=flat_at,
                    historical_submission_outcome=self.UNKNOWN_SUBMISSION_OUTCOME,
                    historical_fill_state=self.UNKNOWN_FILL_STATE,
                    automatic_retry_permitted=False,
                    expected_action_event_ref=expected_head,
                    created_at_utc=created_at,
                )
                resolution_digest = _sha256(
                    canonical_json(self._resolution_identity(unresolved))
                )
                resolution = replace(
                    unresolved,
                    resolution_ref=(
                        "emergency_unknown_resolution_sha256_" + resolution_digest
                    ),
                )
                current = current_action.to_dict()
                current.update(
                    {
                        "status": "manual_unknown_flat",
                        "terminal_status": "submission_unknown_manual_only",
                        "observation_ref": resolution.resolution_ref,
                        "observation_raw_hash": resolution.flat_verification_hash,
                        "verified_flat": True,
                    }
                )
                terminal_action = self._append_transition(
                    conn,
                    current=current,
                    event_kind="manual_unknown_submission_resolved",
                )
                resolution_payload = resolution.to_dict()
                seal = self._seal(
                    owner,
                    {
                        "resolution": resolution_payload,
                        "integrity_key_version": self.KEY_VERSION,
                    },
                )
                conn.execute(
                    """
                    INSERT INTO emergency_unknown_submission_resolutions (
                        resolution_ref,action_ref,owner_user_id,original_halt_ref,
                        original_owner_epoch,resolving_halt_ref,resolving_owner_epoch,
                        account_ref,account_epoch,operator_user_id,decision,
                        operator_auth_audit_ref,lookup_code,lookup_evidence_ref,
                        lookup_evidence_hash,lookup_observed_at_utc,
                        flat_verification_json,flat_verification_ref,
                        flat_verification_hash,flat_observed_at_utc,
                        historical_submission_outcome,historical_fill_state,
                        automatic_retry_permitted,expected_action_event_ref,
                        created_at_utc,integrity_key_version,integrity_seal
                    ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                    """,
                    (
                        resolution.resolution_ref,
                        resolution.action_ref,
                        resolution.owner_user_id,
                        resolution.original_halt_ref,
                        resolution.original_owner_epoch,
                        resolution.resolving_halt_ref,
                        resolution.resolving_owner_epoch,
                        resolution.account_ref,
                        resolution.account_epoch,
                        resolution.operator_user_id,
                        resolution.decision,
                        resolution.operator_auth_audit_ref,
                        resolution.lookup_code,
                        resolution.lookup_evidence_ref,
                        resolution.lookup_evidence_hash,
                        resolution.lookup_observed_at_utc,
                        canonical_json(resolution.flat_verification),
                        resolution.flat_verification_ref,
                        resolution.flat_verification_hash,
                        resolution.flat_observed_at_utc,
                        resolution.historical_submission_outcome,
                        resolution.historical_fill_state,
                        0,
                        resolution.expected_action_event_ref,
                        resolution.created_at_utc,
                        self.KEY_VERSION,
                        seal,
                    ),
                )
                persisted = conn.execute(
                    "SELECT * FROM emergency_unknown_submission_resolutions "
                    "WHERE resolution_ref=?",
                    (resolution.resolution_ref,),
                ).fetchone()
                if persisted is None:
                    raise EmergencyActionError(
                        "emergency unknown-submission resolution did not persist"
                    )
                self._validated_resolution_row(
                    conn,
                    persisted,
                    action=terminal_action,
                )
                self._validate_replay_conn(conn)
                conn.commit()
            except Exception:
                conn.rollback()
                raise
            finally:
                conn.close()
        self.sync_mirror()
        return terminal_action, resolution

    def unknown_submission_resolution(
        self,
        action_ref: str,
        *,
        owner_user_id: str,
    ) -> EmergencyUnknownSubmissionResolution:
        ref = _required(action_ref, field="action_ref")
        owner = _required(owner_user_id, field="owner_user_id")
        with self._conn() as conn:
            self._validate_replay_conn(conn)
            row = conn.execute(
                "SELECT * FROM emergency_unknown_submission_resolutions "
                "WHERE action_ref=? AND owner_user_id=?",
                (ref, owner),
            ).fetchone()
            if row is None:
                raise EmergencyActionError(
                    "emergency unknown-submission resolution is missing"
                )
            return self._validated_resolution_row(conn, row)

    def _validated_action_row(
        self,
        conn: sqlite3.Connection,
        row: sqlite3.Row,
    ) -> EmergencyCloseAction:
        snapshot = self._snapshot_from_mapping(row)
        action = self._action_from_snapshot(snapshot)
        if action.status not in self._STATUSES:
            raise EmergencyActionError("emergency action has an unsupported status")
        try:
            _positive_epoch(action.owner_epoch)
            _positive_epoch(action.account_epoch)
            _positive_epoch(action.attempt_no)
            quantity = _quantity_text(action.quantity_text)
            identity = self._request_identity(
                owner_user_id=_required(action.owner_user_id, field="owner_user_id"),
                halt_ref=_required(action.halt_ref, field="halt_ref"),
                owner_epoch=action.owner_epoch,
                account_ref=_required(action.account_ref, field="account_ref"),
                account_epoch=action.account_epoch,
                credential_binding_ref=_required(
                    action.credential_binding_ref,
                    field="credential_binding_ref",
                ),
                symbol=_required(action.symbol, field="symbol").upper(),
                attempt_no=action.attempt_no,
                side=action.side,
                quantity_text=quantity,
            )
            digest = _sha256(canonical_json(identity))
            expected_client_id = "qbt-kill-" + digest[:24]
            request_params = emergency_close_request_params(
                symbol=action.symbol,
                side=action.side,
                quantity=quantity,
                client_order_id=expected_client_id,
            )
        except ValueError as exc:
            raise EmergencyActionError("emergency action identity fields are invalid") from exc
        if (
            action.action_ref != "emergency_action_sha256_" + digest
            or action.action_identity_hash != "sha256:" + digest
            or action.client_order_id != expected_client_id
            or action.request_hash != "sha256:" + _sha256(canonical_json(request_params))
        ):
            raise EmergencyActionError("emergency action identity/request hash is invalid")
        for field, value in (
            ("created_at_utc", action.created_at_utc),
            ("updated_at_utc", action.updated_at_utc),
        ):
            try:
                parsed = datetime.fromisoformat(value)
            except ValueError as exc:
                raise EmergencyActionError(f"emergency action {field} is malformed") from exc
            if parsed.tzinfo is None:
                raise EmergencyActionError(f"emergency action {field} is not timezone-aware")
        if str(row["integrity_key_version"]) != self.KEY_VERSION:
            raise EmergencyActionError("emergency action integrity key version is unsupported")
        expected_seal = self._seal(
            action.owner_user_id,
            {"snapshot": snapshot, "integrity_key_version": self.KEY_VERSION},
        )
        if not hmac.compare_digest(str(row["integrity_seal"]), expected_seal):
            raise EmergencyActionError("emergency action current row failed integrity validation")
        event = conn.execute(
            "SELECT * FROM emergency_close_action_events WHERE event_ref=?",
            (action.last_event_ref,),
        ).fetchone()
        if event is None:
            raise EmergencyActionError("emergency action head event is missing")
        try:
            stored_snapshot = json.loads(str(event["snapshot_json"]))
        except json.JSONDecodeError as exc:
            raise EmergencyActionError(
                "emergency action head event snapshot JSON is malformed"
            ) from exc
        if stored_snapshot != {**snapshot, "last_event_ref": ""}:
            raise EmergencyActionError("emergency action current row differs from its head event")
        if str(event["action_ref"] or "") != action.action_ref:
            raise EmergencyActionError("emergency action head event belongs to another action")
        event_payload = self._event_payload(
            event_kind=_required(event["event_kind"], field="event_kind"),
            previous_event_ref=str(event["previous_event_ref"] or ""),
            snapshot=stored_snapshot,
            created_at_utc=_required(
                event["created_at_utc"], field="event created_at_utc"
            ),
        )
        expected_event_ref = "emergency_event_sha256_" + _sha256(
            canonical_json(event_payload)
        )
        if not hmac.compare_digest(str(event["event_ref"]), expected_event_ref):
            raise EmergencyActionError("emergency action head event identity is invalid")
        if str(event["integrity_key_version"]) != self.KEY_VERSION:
            raise EmergencyActionError(
                "emergency action head event key version is unsupported"
            )
        if not hmac.compare_digest(
            str(event["integrity_seal"]),
            self._seal(action.owner_user_id, event_payload),
        ):
            raise EmergencyActionError("emergency action head event seal is invalid")
        return action

    def action(self, action_ref: str) -> EmergencyCloseAction:
        ref = _required(action_ref, field="action_ref")
        with self._conn() as conn:
            self._validate_replay_conn(conn)
            row = conn.execute(
                "SELECT * FROM emergency_close_actions WHERE action_ref=?",
                (ref,),
            ).fetchone()
            if row is None:
                raise EmergencyActionError("emergency action is missing")
            return self._validated_action_row(conn, row)

    def validate_reconciled(
        self,
        action_ref: str,
        *,
        owner_user_id: str,
        halt_ref: str,
        owner_epoch: int,
        account_ref: str,
        account_epoch: int,
        response_hash: str | None = None,
    ) -> EmergencyCloseAction:
        action = self.action(action_ref)
        expected = (
            _required(owner_user_id, field="owner_user_id"),
            _required(halt_ref, field="halt_ref"),
            _positive_epoch(owner_epoch),
            _required(account_ref, field="account_ref"),
            _positive_epoch(account_epoch),
        )
        actual = (
            action.owner_user_id,
            action.halt_ref,
            action.owner_epoch,
            action.account_ref,
            action.account_epoch,
        )
        if actual != expected:
            raise EmergencyActionError("emergency action belongs to a different HALT scope")
        if action.status != "reconciled" or not action.verified_flat:
            raise EmergencyActionError("emergency action has not reconciled to fresh flat state")
        if response_hash is not None and action.observation_raw_hash != response_hash:
            raise EmergencyActionError("emergency action response hash does not match flat proof")
        return action

    def actions_for_scope(
        self,
        *,
        owner_user_id: str,
        halt_ref: str,
        owner_epoch: int,
        account_ref: str,
        account_epoch: int,
    ) -> tuple[EmergencyCloseAction, ...]:
        scope = (
            _required(owner_user_id, field="owner_user_id"),
            _required(halt_ref, field="halt_ref"),
            _positive_epoch(owner_epoch),
            _required(account_ref, field="account_ref"),
            _positive_epoch(account_epoch),
        )
        with self._conn() as conn:
            self._validate_replay_conn(conn)
            rows = conn.execute(
                """
                SELECT * FROM emergency_close_actions
                WHERE owner_user_id=? AND halt_ref=? AND owner_epoch=?
                  AND account_ref=? AND account_epoch=?
                ORDER BY symbol,attempt_no
                """,
                scope,
            ).fetchall()
            return tuple(self._validated_action_row(conn, row) for row in rows)

    def actions_for_account_epoch(
        self,
        *,
        owner_user_id: str,
        account_ref: str,
        account_epoch: int,
    ) -> tuple[EmergencyCloseAction, ...]:
        scope = (
            _required(owner_user_id, field="owner_user_id"),
            _required(account_ref, field="account_ref"),
            _positive_epoch(account_epoch),
        )
        with self._conn() as conn:
            self._validate_replay_conn(conn)
            rows = conn.execute(
                """
                SELECT * FROM emergency_close_actions
                WHERE owner_user_id=? AND account_ref=? AND account_epoch=?
                ORDER BY symbol,owner_epoch,halt_ref,attempt_no
                """,
                scope,
            ).fetchall()
            return tuple(self._validated_action_row(conn, row) for row in rows)

    @staticmethod
    def _action_evidence(action: EmergencyCloseAction) -> dict[str, Any]:
        return {
            "action_ref": action.action_ref,
            "halt_ref": action.halt_ref,
            "owner_epoch": action.owner_epoch,
            "account_epoch": action.account_epoch,
            "terminal_event_ref": action.last_event_ref,
            "attempt_no": action.attempt_no,
            "client_order_id": action.client_order_id,
            "action_identity_hash": action.action_identity_hash,
            "request_hash": action.request_hash,
            "status": action.status,
            "venue_order_id": action.venue_order_id,
            "terminal_status": action.terminal_status,
            "cumulative_filled_qty_text": action.cumulative_filled_qty_text,
            "ack_response_hash": action.ack_response_hash,
            "observation_ref": action.observation_ref,
            "observation_raw_hash": action.observation_raw_hash,
            "verified_flat": action.verified_flat,
        }

    def build_flat_proof_binding(
        self,
        *,
        owner_user_id: str,
        halt_ref: str,
        owner_epoch: int,
        account_ref: str,
        account_epoch: int,
        flat_verification: dict[str, Any],
    ) -> dict[str, Any]:
        if not isinstance(flat_verification, dict) or flat_verification.get("ok") is not True:
            raise EmergencyActionError("emergency flat verification is missing or unsuccessful")
        for field in ("normal_open_order_refs", "algo_open_order_refs", "open_positions"):
            if flat_verification.get(field) != []:
                raise EmergencyActionError(
                    "emergency flat verification still contains venue exposure"
                )
        owner = _required(owner_user_id, field="owner_user_id")
        halt = _required(halt_ref, field="halt_ref")
        resolved_owner_epoch = _positive_epoch(owner_epoch)
        account = _required(account_ref, field="account_ref")
        resolved_account_epoch = _positive_epoch(account_epoch)
        actions = self.actions_for_account_epoch(
            owner_user_id=owner,
            account_ref=account,
            account_epoch=resolved_account_epoch,
        )
        evidence: list[dict[str, Any]] = []
        for action in actions:
            if action.status not in {
                "reconciled",
                "failed",
                "terminal_partial",
                "filled_residual",
                "manual_unknown_flat",
            }:
                raise EmergencyActionError(
                    f"emergency action {action.action_ref} remains {action.status}"
                )
            if action.status == "reconciled" and not action.verified_flat:
                raise EmergencyActionError("reconciled emergency action lacks flat evidence")
            if action.status == "failed" and action.cumulative_filled_qty_text != "0":
                raise EmergencyActionError("failed emergency action has unresolved fills")
            if action.status == "terminal_partial" and not (
                Decimal("0")
                < Decimal(action.cumulative_filled_qty_text)
                < Decimal(action.quantity_text)
            ):
                raise EmergencyActionError("partial-terminal emergency action has invalid fill")
            if action.status == "filled_residual" and (
                action.terminal_status != "filled"
                or action.cumulative_filled_qty_text != action.quantity_text
            ):
                raise EmergencyActionError("filled-residual emergency action has invalid fill")
            if action.status == "manual_unknown_flat":
                if not action.verified_flat:
                    raise EmergencyActionError(
                        "manual unknown-submission action lacks its flat observation"
                    )
                self.unknown_submission_resolution(
                    action.action_ref,
                    owner_user_id=owner,
                )
            evidence.append(self._action_evidence(action))
        verified_at = _now()
        verification_payload = {
            "account_ref": account,
            "account_epoch": resolved_account_epoch,
            "flat_verification": flat_verification,
            "verified_at_utc": verified_at,
        }
        verification_ref = "emergency_flat_sha256_" + _sha256(
            canonical_json(verification_payload)
        )
        payload = {
            "owner_user_id": owner,
            "owner_epoch": resolved_owner_epoch,
            "halt_ref": halt,
            "account_ref": account,
            "account_epoch": resolved_account_epoch,
            "verification_ref": verification_ref,
            "verified_at_utc": verified_at,
            "actions": evidence,
        }
        return {
            "binding_ref": "emergency_binding_sha256_" + _sha256(canonical_json(payload)),
            **payload,
        }

    def validate_flat_proof_binding(
        self,
        binding: dict[str, Any],
        *,
        owner_user_id: str,
        halt_ref: str,
        owner_epoch: int,
        account_ref: str,
        account_epoch: int,
        flat_verification: dict[str, Any],
    ) -> dict[str, Any]:
        if not isinstance(binding, dict):
            raise EmergencyActionError("emergency action flat-proof binding must be an object")
        expected_scope = {
            "owner_user_id": _required(owner_user_id, field="owner_user_id"),
            "owner_epoch": _positive_epoch(owner_epoch),
            "halt_ref": _required(halt_ref, field="halt_ref"),
            "account_ref": _required(account_ref, field="account_ref"),
            "account_epoch": _positive_epoch(account_epoch),
        }
        if any(binding.get(field) != value for field, value in expected_scope.items()):
            raise EmergencyActionError("emergency action binding belongs to a different HALT scope")
        actions = self.actions_for_account_epoch(
            owner_user_id=expected_scope["owner_user_id"],
            account_ref=expected_scope["account_ref"],
            account_epoch=expected_scope["account_epoch"],
        )
        expected_actions = [self._action_evidence(action) for action in actions]
        if binding.get("actions") != expected_actions:
            raise EmergencyActionError("emergency action binding differs from journal evidence")
        for action in actions:
            if action.status not in {
                "reconciled",
                "failed",
                "terminal_partial",
                "filled_residual",
                "manual_unknown_flat",
            }:
                raise EmergencyActionError("emergency action binding contains unresolved actions")
            if action.status == "manual_unknown_flat":
                self.unknown_submission_resolution(
                    action.action_ref,
                    owner_user_id=expected_scope["owner_user_id"],
                )
        verified_at = _required(binding.get("verified_at_utc"), field="verified_at_utc")
        try:
            parsed = datetime.fromisoformat(verified_at)
        except ValueError as exc:
            raise EmergencyActionError("emergency action binding timestamp is malformed") from exc
        if parsed.tzinfo is None:
            raise EmergencyActionError("emergency action binding timestamp is not timezone-aware")
        verification_ref = _required(binding.get("verification_ref"), field="verification_ref")
        if not verification_ref.startswith("emergency_flat_sha256_") or len(verification_ref) != 86:
            raise EmergencyActionError("emergency flat verification ref is malformed")
        expected_verification_ref = "emergency_flat_sha256_" + _sha256(
            canonical_json(
                {
                    "account_ref": expected_scope["account_ref"],
                    "account_epoch": expected_scope["account_epoch"],
                    "flat_verification": flat_verification,
                    "verified_at_utc": verified_at,
                }
            )
        )
        if not hmac.compare_digest(verification_ref, expected_verification_ref):
            raise EmergencyActionError("emergency flat verification identity is invalid")
        payload = {
            **expected_scope,
            "verification_ref": verification_ref,
            "verified_at_utc": verified_at,
            "actions": expected_actions,
        }
        expected_ref = "emergency_binding_sha256_" + _sha256(canonical_json(payload))
        if not hmac.compare_digest(str(binding.get("binding_ref") or ""), expected_ref):
            raise EmergencyActionError("emergency action binding identity is invalid")
        return dict(binding)

    def _validate_replay_conn(self, conn: sqlite3.Connection) -> None:
        rows = conn.execute(
            "SELECT * FROM emergency_close_action_events ORDER BY seq"
        ).fetchall()
        previous_by_action: dict[str, str] = {}
        for row in rows:
            try:
                snapshot = json.loads(str(row["snapshot_json"]))
            except json.JSONDecodeError as exc:
                raise EmergencyActionError("emergency action event snapshot JSON is malformed") from exc
            if not isinstance(snapshot, dict):
                raise EmergencyActionError("emergency action event snapshot must be an object")
            action_ref = _required(row["action_ref"], field="event action_ref")
            previous = str(row["previous_event_ref"] or "")
            if previous != previous_by_action.get(action_ref, ""):
                raise EmergencyActionError("emergency action event chain is discontinuous")
            owner = _required(snapshot.get("owner_user_id"), field="event owner_user_id")
            payload = self._event_payload(
                event_kind=_required(row["event_kind"], field="event_kind"),
                previous_event_ref=previous,
                snapshot=snapshot,
                created_at_utc=_required(row["created_at_utc"], field="event created_at_utc"),
            )
            expected_ref = "emergency_event_sha256_" + _sha256(canonical_json(payload))
            if not hmac.compare_digest(str(row["event_ref"]), expected_ref):
                raise EmergencyActionError("emergency action event identity is invalid")
            if str(row["integrity_key_version"]) != self.KEY_VERSION:
                raise EmergencyActionError("emergency action event key version is unsupported")
            if not hmac.compare_digest(
                str(row["integrity_seal"]),
                self._seal(owner, payload),
            ):
                raise EmergencyActionError("emergency action event seal is invalid")
            previous_by_action[action_ref] = expected_ref
        action_rows = conn.execute(
            "SELECT * FROM emergency_close_actions ORDER BY action_ref"
        ).fetchall()
        if len(action_rows) != len(previous_by_action):
            raise EmergencyActionError("emergency action rows/events cardinality differs")
        actions_by_ref: dict[str, EmergencyCloseAction] = {}
        for row in action_rows:
            action = self._validated_action_row(conn, row)
            if previous_by_action.get(action.action_ref) != action.last_event_ref:
                raise EmergencyActionError("emergency action head does not match event replay")
            actions_by_ref[action.action_ref] = action
        has_resolution_table = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' "
            "AND name='emergency_unknown_submission_resolutions'"
        ).fetchone() is not None
        resolution_rows = (
            conn.execute(
                "SELECT * FROM emergency_unknown_submission_resolutions "
                "ORDER BY resolution_ref"
            ).fetchall()
            if has_resolution_table
            else []
        )
        resolved_actions: set[str] = set()
        for row in resolution_rows:
            action_ref = str(row["action_ref"] or "")
            action = actions_by_ref.get(action_ref)
            if action is None:
                raise EmergencyActionError(
                    "emergency unknown-submission resolution lacks its action"
                )
            self._validated_resolution_row(conn, row, action=action)
            if action_ref in resolved_actions:
                raise EmergencyActionError(
                    "emergency unknown-submission action has duplicate resolutions"
                )
            resolved_actions.add(action_ref)
        manual_actions = {
            action_ref
            for action_ref, action in actions_by_ref.items()
            if action.status == "manual_unknown_flat"
        }
        if manual_actions != resolved_actions:
            raise EmergencyActionError(
                "manual unknown-submission action/resolution cardinality differs"
            )

    def validate_replay(self) -> None:
        with self._conn() as conn:
            self._validate_replay_conn(conn)

    def _mirror_record(self, row: sqlite3.Row) -> dict[str, Any]:
        return {
            "schema_version": self.MIRROR_SCHEMA_VERSION,
            "event_type": "emergency_close_action_transition",
            "event_ref": str(row["event_ref"]),
            "action_ref": str(row["action_ref"]),
            "event_kind": str(row["event_kind"]),
            "previous_event_ref": str(row["previous_event_ref"]),
            "snapshot": json.loads(str(row["snapshot_json"])),
            "created_at_utc": str(row["created_at_utc"]),
            "integrity_key_version": str(row["integrity_key_version"]),
            "integrity_seal": str(row["integrity_seal"]),
        }

    def sync_mirror(self) -> int:
        """Append any committed SQLite events missing from the audit mirror."""

        with self._lock:
            lock_path = self._mirror_path.with_name(self._mirror_path.name + ".lock")
            with _portable_file_lock(lock_path):
                return self._sync_mirror_locked()

    def _sync_mirror_locked(self) -> int:
        existing: list[tuple[str, str]] = []
        if self._mirror_path.exists():
            info = self._mirror_path.lstat()
            if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode):
                raise EmergencyActionError(
                    "emergency action mirror must be a regular non-symlink file"
                )
            raw_bytes = self._mirror_path.read_bytes()
            if raw_bytes and not raw_bytes.endswith(b"\n"):
                # A process can die during the final append.  SQLite remains
                # authoritative, so discard only the unterminated tail and
                # rebuild that event below.  Malformed newline-terminated rows
                # still fail closed as evidence corruption.
                last_newline = raw_bytes.rfind(b"\n")
                durable_prefix = raw_bytes[: last_newline + 1] if last_newline >= 0 else b""
                with self._mirror_path.open("r+b") as mirror:
                    mirror.truncate(len(durable_prefix))
                    mirror.flush()
                    os.fsync(mirror.fileno())
            for line_no, line in enumerate(
                self._mirror_path.read_text(encoding="utf-8").splitlines(),
                start=1,
            ):
                if not line.strip():
                    raise EmergencyActionError(
                        f"emergency action mirror line {line_no} is empty"
                    )
                try:
                    record = json.loads(line)
                except json.JSONDecodeError as exc:
                    raise EmergencyActionError(
                        f"emergency action mirror line {line_no} is malformed"
                    ) from exc
                if not isinstance(record, dict):
                    raise EmergencyActionError(
                        f"emergency action mirror line {line_no} is not an object"
                    )
                event_ref = _required(record.get("event_ref"), field="mirror event_ref")
                encoded = canonical_json(record)
                existing.append((event_ref, encoded))
        with self._conn() as conn:
            conn.execute("BEGIN")
            try:
                # SQLite is authoritative, but only a fully replay-valid
                # snapshot may repair/extend the audit mirror.  Otherwise a
                # forged committed suffix could be copied into JSONL before a
                # later state transition notices and rejects the tamper.
                self._validate_replay_conn(conn)
                rows = conn.execute(
                    "SELECT * FROM emergency_close_action_events ORDER BY seq"
                ).fetchall()
            finally:
                conn.rollback()
        db_records = [self._mirror_record(row) for row in rows]
        if len(existing) > len(db_records):
            raise EmergencyActionError(
                "emergency action mirror contains more events than SQLite"
            )
        for index, (event_ref, encoded) in enumerate(existing):
            expected = db_records[index]
            if event_ref != str(expected["event_ref"]):
                raise EmergencyActionError(
                    "emergency action mirror is not an exact ordered SQLite prefix"
                )
            if encoded != canonical_json(expected):
                raise EmergencyActionError(
                    "emergency action mirror event differs from SQLite source of truth"
                )
        pending = db_records[len(existing) :]
        if not pending:
            return 0
        flags = os.O_WRONLY | os.O_CREAT | os.O_APPEND
        flags |= getattr(os, "O_NOFOLLOW", 0)
        fd = os.open(self._mirror_path, flags, 0o600)
        try:
            for record in pending:
                raw = (canonical_json(record) + "\n").encode("utf-8")
                offset = 0
                while offset < len(raw):
                    offset += os.write(fd, raw[offset:])
            os.fsync(fd)
        finally:
            os.close(fd)
        try:
            self._mirror_path.chmod(0o600)
        except OSError:
            pass
        return len(pending)


__all__ = [
    "EmergencyActionError",
    "EmergencyActionJournal",
    "EmergencyActionStatus",
    "EmergencyCloseAction",
    "EmergencyUnknownSubmissionResolution",
    "emergency_close_request_hash",
    "emergency_close_request_params",
]
