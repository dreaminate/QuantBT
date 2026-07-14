"""Persistent, account-bound risk reservations for copy-trade execution.

The ledger is append-only SQLite.  A live reservation is evaluated and written
inside one ``BEGIN IMMEDIATE`` transaction so concurrent relays cannot both see
the same unused turnover budget.  Unknown submission outcomes remain reserved
until an explicit reconciliation proves that no venue effect occurred.
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
import tempfile
import uuid
import fcntl
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterator

from ..cross_process_lock import acquire_exclusive_fd
from ..execution.base import (
    ExecutionReport,
    Order,
    OrderExecutionObservation,
    canonical_raw_event_hash,
)
from ..execution.emergency import AccountExecutionObservation
from ..lineage.ids import canonical_json, content_hash
from ..research_os.execution_boundary import (
    ExecutionReconciliationRecord,
    ExecutionVenueEventRecord,
    reconcile_execution_venue_events,
    validate_execution_reconciliation,
    validate_execution_venue_event,
)
from ..risk import RiskLimits


class CopyTradeRiskError(PermissionError):
    pass


_KEY_CREATION_LOCK_TIMEOUT_SECONDS = 10.0


@dataclass(frozen=True)
class FollowerRiskState:
    follower_id: str
    account_binding_ref: str
    day: str
    starting_equity: float
    current_equity: float
    order_count: int
    reserved_turnover: float
    filled_turnover: float
    realized_pnl: float
    realized_pnl_complete: bool
    normalized_cost_usdt: float | None
    cost_complete: bool
    open_reservation_refs: tuple[str, ...]
    snapshot_ref: str


@dataclass(frozen=True)
class FollowerFillEconomics:
    """Owner-filterable, HMAC-backed projection of one venue fill.

    This is deliberately a per-fill record.  It does not claim that periodic
    funding, borrow, or other holding costs have been attributed to the order.
    """

    event_ref: str
    reservation_ref: str
    submission_ref: str
    venue_event_ref: str
    reconciliation_ref: str
    source_event_ref: str
    raw_event_hash: str
    signal_ref: str
    follower_ref: str
    account_binding_ref: str
    symbol: str
    side: str
    venue_order_ref: str
    client_order_ref: str
    fill_status: str
    filled_qty: float
    cumulative_filled_qty: float
    fill_price: float
    fill_price_source: str
    filled_notional_usdt: float
    commission: float
    commission_asset: str
    normalized_cost_usdt: float | None
    cost_conversion_ref: str | None
    cost_complete: bool
    realized_pnl_delta: float
    realized_pnl_complete: bool
    fill_economics_complete: bool
    occurred_at_utc: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class PreTradeReservation:
    reservation_ref: str
    risk_check_ref: str
    follower_id: str
    account_binding_ref: str
    signal_id: str
    symbol: str
    side: str
    client_order_id: str
    snapshot_ref: str
    trusted_mark_price: float
    order_quantity: float
    notional_usdt: float
    expected_cost_usdt: float
    daily_turnover_before: float
    drawdown_now: float
    projected_position_count: int
    projected_symbol_concentration: float
    created_at_utc: str
    attempt_instance_id: str = ""


@dataclass(frozen=True)
class FormalSubmissionRiskBinding:
    submission_ref: str
    reservation_ref: str
    binding_event_id: str
    outcome_state: str
    follower_id: str
    account_binding_ref: str
    signal_id: str
    risk_check_ref: str
    snapshot_ref: str
    client_order_id: str
    venue_order_ref: str
    ack_ref: str
    reason_ref: str
    order_request_context: dict[str, str]
    projection_completed_event_id: str = ""
    initial_reconciliation_ref: str = ""


def _now() -> datetime:
    return datetime.now(UTC)


def _parse_timestamp(value: str) -> datetime:
    parsed = datetime.fromisoformat(str(value))
    if parsed.tzinfo is None:
        raise ValueError("timestamp must include an explicit UTC offset")
    return parsed


class PersistentFollowerRiskStateStore:
    def __init__(
        self,
        path: str | Path,
        *,
        reconciliation_store: Any = None,
        venue_event_store: Any = None,
        submission_store: Any = None,
        allow_unsealed_test_transitions: bool = False,
    ) -> None:
        self._path = Path(path)
        self._reconciliation_store = reconciliation_store
        self._venue_event_store = venue_event_store
        self._submission_store = submission_store
        self._allow_unsealed_test_transitions = bool(allow_unsealed_test_transitions)
        self.__lifecycle_finalize_token = object()
        self._instance_id = "risk_process_" + uuid.uuid4().hex
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._secure_database_files()
        key_path = self._path.with_name(self._path.name + ".hmac.key")
        if not key_path.exists() and self._database_has_events(self._path):
            raise ValueError("copy-trade risk integrity key is missing for a nonempty ledger")
        self._integrity_key = self._load_or_create_integrity_key(key_path)
        self._init_schema()
        self._secure_database_files()
        self._validate_replay()

    @property
    def instance_id(self) -> str:
        """Opaque process identity sealed into newly created reservations."""

        return self._instance_id

    def bind_formal_proof_stores(
        self,
        *,
        reconciliation_store: Any,
        venue_event_store: Any,
        submission_store: Any = None,
    ) -> None:
        """Bind persisted formal registries before terminal risk release."""

        if not hasattr(reconciliation_store, "reconciliation") or not hasattr(
            venue_event_store, "event"
        ):
            raise TypeError("formal proof stores must resolve reconciliation and venue event refs")
        if submission_store is not None and not hasattr(submission_store, "submission"):
            raise TypeError("formal submission store must resolve submission refs")
        self._reconciliation_store = reconciliation_store
        self._venue_event_store = venue_event_store
        self._submission_store = submission_store

    @staticmethod
    def _database_has_events(path: Path) -> bool:
        if not path.exists():
            return False
        try:
            with sqlite3.connect(str(path)) as conn:
                row = conn.execute(
                    "SELECT 1 FROM sqlite_master WHERE type='table' AND name='ct_risk_events'"
                ).fetchone()
                if row is None:
                    return False
                return conn.execute("SELECT 1 FROM ct_risk_events LIMIT 1").fetchone() is not None
        except sqlite3.DatabaseError as exc:
            raise ValueError(f"invalid copy-trade risk database at {path}") from exc

    @staticmethod
    def _read_integrity_key(path: Path) -> bytes:
        flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
        try:
            fd = os.open(path, flags)
        except FileNotFoundError:
            raise
        except OSError as exc:
            raise ValueError(
                f"copy-trade risk integrity key must be a regular non-symlink file: {path}"
            ) from exc
        try:
            info = os.fstat(fd)
            if not stat.S_ISREG(info.st_mode):
                raise ValueError(
                    f"copy-trade risk integrity key must be a regular file: {path}"
                )
            if hasattr(os, "getuid") and info.st_uid != os.getuid():
                raise ValueError(
                    f"copy-trade risk integrity key must be owned by the current user: {path}"
                )
            if info.st_nlink != 1:
                raise ValueError(
                    f"copy-trade risk integrity key must not have additional hard links: {path}"
                )
            if stat.S_IMODE(info.st_mode) != 0o600:
                raise ValueError(f"copy-trade risk integrity key mode must be 0600: {path}")
            chunks: list[bytes] = []
            while True:
                chunk = os.read(fd, 4096)
                if not chunk:
                    break
                chunks.append(chunk)
            key = b"".join(chunks)
        finally:
            os.close(fd)
        if len(key) < 32:
            raise ValueError(f"invalid copy-trade risk integrity key at {path}")
        return key

    @staticmethod
    def _load_or_create_integrity_key(path: Path) -> bytes:
        path.parent.mkdir(parents=True, exist_ok=True)
        lock_path = path.with_name(f".{path.name}.create.lock")
        flags = os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0)
        try:
            lock_fd = os.open(lock_path, flags, 0o600)
        except OSError as exc:
            raise ValueError(
                f"copy-trade risk integrity key creation lock is unavailable: {lock_path}"
            ) from exc
        held = None
        try:
            lock_info = os.fstat(lock_fd)
            if not stat.S_ISREG(lock_info.st_mode):
                raise ValueError(
                    f"copy-trade risk integrity key creation lock must be regular: {lock_path}"
                )
            if hasattr(os, "getuid") and lock_info.st_uid != os.getuid():
                raise ValueError(
                    f"copy-trade risk integrity key creation lock must be owned by the current user: {lock_path}"
                )
            if lock_info.st_nlink != 1:
                raise ValueError(
                    f"copy-trade risk integrity key creation lock must not have additional hard links: {lock_path}"
                )
            os.fchmod(lock_fd, 0o600)
            held = acquire_exclusive_fd(
                lock_fd,
                timeout_seconds=_KEY_CREATION_LOCK_TIMEOUT_SECONDS,
            )
            return PersistentFollowerRiskStateStore._load_or_create_integrity_key_unlocked(
                path
            )
        finally:
            try:
                if held is not None:
                    held.release()
            finally:
                os.close(lock_fd)

    @staticmethod
    def _load_or_create_integrity_key_unlocked(path: Path) -> bytes:
        try:
            return PersistentFollowerRiskStateStore._read_integrity_key(path)
        except FileNotFoundError:
            pass

        candidate = secrets.token_bytes(32)
        temp_fd, temp_name = tempfile.mkstemp(
            prefix=f".{path.name}.",
            suffix=".tmp",
            dir=path.parent,
        )
        try:
            try:
                os.fchmod(temp_fd, 0o600)
                remaining = memoryview(candidate)
                while remaining:
                    written = os.write(temp_fd, remaining)
                    if written <= 0:
                        raise OSError("copy-trade risk integrity key write made no progress")
                    remaining = remaining[written:]
                os.fsync(temp_fd)
            finally:
                os.close(temp_fd)
                temp_fd = -1
            if os.path.lexists(path):
                # A non-cooperating creator won outside this lock.  Never
                # overwrite it; the strict reader below decides whether it is
                # an admissible private key.
                pass
            else:
                os.replace(temp_name, path)
                directory_fd = os.open(path.parent, os.O_RDONLY)
                try:
                    os.fsync(directory_fd)
                finally:
                    os.close(directory_fd)
        finally:
            if temp_fd >= 0:
                os.close(temp_fd)
            try:
                os.unlink(temp_name)
            except FileNotFoundError:
                pass
        return PersistentFollowerRiskStateStore._read_integrity_key(path)

    def _secure_database_files(self) -> None:
        """Keep the local risk ledger and SQLite sidecars private to the owner."""

        for path in (
            self._path,
            self._path.with_name(self._path.name + "-wal"),
            self._path.with_name(self._path.name + "-shm"),
            self._path.with_name(self._path.name + "-journal"),
        ):
            if not os.path.lexists(path):
                continue
            try:
                info = path.lstat()
                if not stat.S_ISREG(info.st_mode):
                    raise ValueError(
                        f"copy-trade risk database path must be a regular file: {path}"
                    )
                if hasattr(os, "getuid") and info.st_uid != os.getuid():
                    raise ValueError(
                        f"copy-trade risk database path must be owned by the current user: {path}"
                    )
                if info.st_nlink != 1:
                    raise ValueError(
                        f"copy-trade risk database path must not have additional hard links: {path}"
                    )
                path.chmod(0o600, follow_symlinks=False)
            except OSError as exc:
                raise ValueError(
                    f"copy-trade risk database permissions could not be secured: {path}"
                ) from exc
            if stat.S_IMODE(path.stat().st_mode) != 0o600:
                raise ValueError(
                    f"copy-trade risk database mode must be 0600: {path}"
                )

    def _seal(self, payload: dict[str, Any]) -> str:
        return hmac.new(
            self._integrity_key,
            canonical_json(payload).encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()

    def _conn(self) -> sqlite3.Connection:
        self._secure_database_files()
        conn = sqlite3.connect(str(self._path), timeout=5.0, isolation_level=None)
        self._secure_database_files()
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA busy_timeout=5000")
        return conn

    @contextmanager
    def formal_projection_guard(self, reservation_ref: str) -> Iterator[None]:
        """Serialize risk validation through the matching formal append.

        Formal events live outside SQLite, so a SQLite transaction alone cannot
        prevent two reconcilers from validating the same prior cumulative fill.
        This process-wide filesystem lock also covers sibling worker processes.
        """

        if not str(reservation_ref or "").strip():
            raise CopyTradeRiskError("formal projection guard requires reservation_ref")
        lock_path = self._path.with_name(self._path.name + ".formal_projection.lock")
        fd = os.open(lock_path, os.O_RDWR | os.O_CREAT, 0o600)
        try:
            os.chmod(lock_path, 0o600)
            fcntl.flock(fd, fcntl.LOCK_EX)
            yield
        finally:
            fcntl.flock(fd, fcntl.LOCK_UN)
            os.close(fd)

    def _init_schema(self) -> None:
        with self._conn() as conn:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS ct_risk_events (
                    seq INTEGER PRIMARY KEY AUTOINCREMENT,
                    event_id TEXT NOT NULL UNIQUE,
                    follower_id TEXT NOT NULL,
                    account_binding_ref TEXT NOT NULL,
                    signal_id TEXT,
                    reservation_ref TEXT,
                    event_kind TEXT NOT NULL,
                    day TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    prev_seal TEXT NOT NULL DEFAULT '',
                    integrity_seal TEXT NOT NULL DEFAULT '',
                    created_at_utc TEXT NOT NULL
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_ct_risk_follower_day ON ct_risk_events(follower_id, day, seq)"
            )
            conn.execute(
                "CREATE UNIQUE INDEX IF NOT EXISTS idx_ct_risk_one_reservation "
                "ON ct_risk_events(follower_id, signal_id, event_kind) "
                "WHERE event_kind='pretrade_reserved'"
            )
            columns = {str(row[1]) for row in conn.execute("PRAGMA table_info(ct_risk_events)").fetchall()}
            if "prev_seal" not in columns:
                conn.execute("ALTER TABLE ct_risk_events ADD COLUMN prev_seal TEXT NOT NULL DEFAULT ''")
            if "integrity_seal" not in columns:
                conn.execute("ALTER TABLE ct_risk_events ADD COLUMN integrity_seal TEXT NOT NULL DEFAULT ''")
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS ct_risk_integrity_head (
                    singleton INTEGER PRIMARY KEY CHECK(singleton=1),
                    last_seq INTEGER NOT NULL,
                    last_seal TEXT NOT NULL,
                    head_seal TEXT NOT NULL
                )
                """
            )
            if conn.execute("SELECT 1 FROM ct_risk_integrity_head WHERE singleton=1").fetchone() is None:
                head = {"last_seq": 0, "last_seal": ""}
                conn.execute(
                    "INSERT INTO ct_risk_integrity_head(singleton,last_seq,last_seal,head_seal) VALUES(1,?,?,?)",
                    (0, "", self._seal({"kind": "risk_integrity_head", **head})),
                )

    def _validated_rows_snapshot(self) -> list[sqlite3.Row]:
        conn = self._conn()
        try:
            conn.execute("BEGIN")
            rows = conn.execute("SELECT * FROM ct_risk_events ORDER BY seq").fetchall()
            head = conn.execute(
                "SELECT last_seq,last_seal,head_seal FROM ct_risk_integrity_head WHERE singleton=1"
            ).fetchone()
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()
        previous_seq = 0
        previous_seal = ""
        for row in rows:
            try:
                payload = json.loads(row["payload_json"])
            except Exception as exc:  # noqa: BLE001
                raise ValueError(f"invalid copy-trade risk event seq={row['seq']}") from exc
            if not isinstance(payload, dict):
                raise ValueError(f"invalid copy-trade risk event payload seq={row['seq']}")
            for field in ("event_id", "follower_id", "account_binding_ref", "event_kind", "day", "created_at_utc"):
                if not str(row[field] or "").strip():
                    raise ValueError(f"copy-trade risk event seq={row['seq']} lacks {field}")
            signed = {
                "seq": row["seq"],
                "event_id": row["event_id"],
                "follower_id": row["follower_id"],
                "account_binding_ref": row["account_binding_ref"],
                "signal_id": row["signal_id"],
                "reservation_ref": row["reservation_ref"],
                "event_kind": row["event_kind"],
                "day": row["day"],
                "payload": payload,
                "prev_seal": row["prev_seal"],
                "created_at_utc": row["created_at_utc"],
            }
            if int(row["seq"]) != previous_seq + 1 or str(row["prev_seal"] or "") != previous_seal:
                raise ValueError(f"copy-trade risk event chain discontinuity seq={row['seq']}")
            if not hmac.compare_digest(self._seal(signed), str(row["integrity_seal"] or "")):
                raise ValueError(f"copy-trade risk event integrity failure seq={row['seq']}")
            previous_seq = int(row["seq"])
            previous_seal = str(row["integrity_seal"])
        if head is None:
            raise ValueError("copy-trade risk ledger integrity head is missing")
        expected_head_seal = self._seal(
            {"kind": "risk_integrity_head", "last_seq": previous_seq, "last_seal": previous_seal}
        )
        if (
            int(head["last_seq"]) != previous_seq
            or str(head["last_seal"]) != previous_seal
            or not hmac.compare_digest(str(head["head_seal"] or ""), expected_head_seal)
        ):
            raise ValueError("copy-trade risk ledger integrity head mismatch")
        return rows

    def _validate_replay(self) -> None:
        self._validated_rows_snapshot()

    @staticmethod
    def _rows(conn: sqlite3.Connection, follower_id: str) -> list[sqlite3.Row]:
        return conn.execute(
            "SELECT * FROM ct_risk_events WHERE follower_id=? ORDER BY seq",
            (follower_id,),
        ).fetchall()

    @staticmethod
    def _account_rows(conn: sqlite3.Connection, account_binding_ref: str) -> list[sqlite3.Row]:
        return conn.execute(
            "SELECT * FROM ct_risk_events WHERE account_binding_ref=? ORDER BY seq",
            (account_binding_ref,),
        ).fetchall()

    @staticmethod
    def _payload(row: sqlite3.Row) -> dict[str, Any]:
        payload = json.loads(row["payload_json"])
        if not isinstance(payload, dict):
            raise ValueError(f"invalid risk payload seq={row['seq']}")
        return payload

    def _assert_exact_persisted_reservation(
        self,
        reservation: PreTradeReservation,
    ) -> None:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT * FROM ct_risk_events WHERE reservation_ref=? "
                "AND event_kind='pretrade_reserved'",
                (reservation.reservation_ref,),
            ).fetchone()
        if row is None:
            raise CopyTradeRiskError("risk transition references an unknown reservation")
        payload = self._payload(row).get("reservation")
        if not isinstance(payload, dict):
            raise CopyTradeRiskError("persisted reservation payload is malformed")
        try:
            persisted = PreTradeReservation(**payload)
        except (TypeError, ValueError) as exc:
            raise CopyTradeRiskError("persisted reservation cannot be reconstructed") from exc
        if persisted != reservation:
            raise CopyTradeRiskError("risk transition reservation content mismatch")

    @classmethod
    def _active_reservations(cls, rows: list[sqlite3.Row]) -> dict[str, dict[str, Any]]:
        reservations = {
            str(row["reservation_ref"]): cls._payload(row)
            for row in rows
            if row["event_kind"] == "pretrade_reserved"
        }
        terminal: set[str] = set()
        cumulative_fills: dict[str, float] = {}
        for row in rows:
            reservation_ref = str(row["reservation_ref"] or "")
            if not reservation_ref:
                continue
            if row["event_kind"] in {
                "definitive_reject",
                "venue_reject",
                "reconciled_no_effect",
                "reconciled_partial_terminal",
            }:
                terminal.add(reservation_ref)
            elif row["event_kind"] == "fill" and cls._payload(row).get("terminal_fill") is True:
                terminal.add(reservation_ref)
            if row["event_kind"] == "fill":
                cumulative_fills[reservation_ref] = max(
                    cumulative_fills.get(reservation_ref, 0.0),
                    float(cls._payload(row).get("cumulative_filled_qty", 0) or 0),
                )
        active: dict[str, dict[str, Any]] = {}
        for ref, payload in reservations.items():
            if ref in terminal:
                continue
            adjusted = dict(payload)
            reservation_payload = payload.get("reservation")
            requested = (
                float(reservation_payload.get("order_quantity", 0) or 0)
                if isinstance(reservation_payload, dict)
                else 0.0
            )
            cumulative = cumulative_fills.get(ref, 0.0)
            if requested > 0 and cumulative > 0:
                remaining_fraction = max(0.0, min(1.0, (requested - cumulative) / requested))
                adjusted["notional_usdt"] = float(payload.get("notional_usdt", 0) or 0) * remaining_fraction
            active[ref] = adjusted
        return active

    @classmethod
    def _derive_state(
        cls,
        rows: list[sqlite3.Row],
        *,
        follower_id: str,
        account_binding_ref: str,
        day: str,
    ) -> FollowerRiskState:
        if any(row["account_binding_ref"] != account_binding_ref for row in rows):
            raise CopyTradeRiskError("follower risk history account binding changed")
        daily_rows = [row for row in rows if row["day"] == day]
        snapshots = [cls._payload(row) for row in daily_rows if row["event_kind"] == "account_snapshot"]
        baselines = [cls._payload(row) for row in daily_rows if row["event_kind"] == "daily_baseline"]
        reservations = {
            str(row["reservation_ref"]): cls._payload(row)
            for row in rows
            if row["event_kind"] == "pretrade_reserved"
        }
        reservation_days = {
            str(row["reservation_ref"]): str(row["day"])
            for row in rows
            if row["event_kind"] == "pretrade_reserved"
        }
        ineffective: set[str] = set()
        fills: dict[str, dict[str, Any]] = {}
        for row in rows:
            reservation_ref = str(row["reservation_ref"] or "")
            if not reservation_ref:
                continue
            if row["event_kind"] in {
                "definitive_reject",
                "venue_reject",
                "reconciled_no_effect",
            }:
                ineffective.add(reservation_ref)
            if row["event_kind"] == "fill" and row["day"] == day:
                fills[str(row["event_id"])] = cls._payload(row)

        active = cls._active_reservations(rows)
        daily_effective = {
            ref: payload
            for ref, payload in reservations.items()
            if reservation_days.get(ref) == day and ref not in ineffective
        }
        filled_turnover = sum(float(payload.get("filled_notional_usdt", 0) or 0) for payload in fills.values())
        realized_pnl = sum(float(payload.get("realized_pnl_delta", 0) or 0) for payload in fills.values())
        realized_pnl_complete = all(
            payload.get("realized_pnl_complete") is True for payload in fills.values()
        )
        known_costs = [payload for payload in fills.values() if payload.get("cost_complete") is True]
        incomplete_cost = any(payload.get("cost_complete") is not True for payload in fills.values())
        normalized_cost = sum(float(payload.get("normalized_cost_usdt", 0) or 0) for payload in known_costs)
        latest_snapshot = snapshots[-1] if snapshots else {}
        starting_equity = float((baselines[-1] if baselines else {}).get("starting_equity", 0) or 0)
        return FollowerRiskState(
            follower_id=follower_id,
            account_binding_ref=account_binding_ref,
            day=day,
            starting_equity=starting_equity,
            current_equity=float(latest_snapshot.get("equity", 0) or 0),
            order_count=len(daily_effective),
            reserved_turnover=sum(float(payload.get("notional_usdt", 0) or 0) for payload in active.values()),
            filled_turnover=filled_turnover,
            realized_pnl=realized_pnl,
            realized_pnl_complete=realized_pnl_complete,
            normalized_cost_usdt=None if incomplete_cost else normalized_cost,
            cost_complete=not incomplete_cost,
            open_reservation_refs=tuple(sorted(active)),
            snapshot_ref=str(latest_snapshot.get("snapshot_ref") or ""),
        )

    def _insert_event(
        self,
        conn: sqlite3.Connection,
        *,
        event_id: str,
        follower_id: str,
        account_binding_ref: str,
        signal_id: str | None,
        reservation_ref: str | None,
        event_kind: str,
        day: str,
        payload: dict[str, Any],
        created_at_utc: str,
    ) -> None:
        head = conn.execute(
            "SELECT last_seq,last_seal FROM ct_risk_integrity_head WHERE singleton=1"
        ).fetchone()
        if head is None:
            raise ValueError("copy-trade risk ledger integrity head is missing")
        seq = int(head["last_seq"]) + 1
        prev_seal = str(head["last_seal"] or "")
        signed = {
            "seq": seq,
            "event_id": event_id,
            "follower_id": follower_id,
            "account_binding_ref": account_binding_ref,
            "signal_id": signal_id,
            "reservation_ref": reservation_ref,
            "event_kind": event_kind,
            "day": day,
            "payload": payload,
            "prev_seal": prev_seal,
            "created_at_utc": created_at_utc,
        }
        integrity_seal = self._seal(signed)
        conn.execute(
            """
                INSERT INTO ct_risk_events(
                    seq, event_id, follower_id, account_binding_ref, signal_id,
                    reservation_ref, event_kind, day, payload_json, prev_seal, integrity_seal, created_at_utc
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                seq,
                event_id,
                follower_id,
                account_binding_ref,
                signal_id,
                reservation_ref,
                event_kind,
                day,
                json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
                prev_seal,
                integrity_seal,
                created_at_utc,
            ),
        )
        head_payload = {"kind": "risk_integrity_head", "last_seq": seq, "last_seal": integrity_seal}
        conn.execute(
            "UPDATE ct_risk_integrity_head SET last_seq=?,last_seal=?,head_seal=? WHERE singleton=1",
            (seq, integrity_seal, self._seal(head_payload)),
        )

    def reserve(
        self,
        *,
        follower: Any,
        signal_id: str,
        order: Order,
        observation: AccountExecutionObservation,
        limits: RiskLimits,
        max_snapshot_age_s: float = 60.0,
    ) -> PreTradeReservation:
        follower_id = str(getattr(follower, "follower_id", "") or "")
        account_binding_ref = str(getattr(follower, "account_binding_ref", "") or "")
        if not follower_id or not account_binding_ref:
            raise CopyTradeRiskError("live risk reservation requires follower and account binding refs")
        if observation.account_ref != account_binding_ref:
            raise CopyTradeRiskError("account observation does not match follower account binding")
        if observation.account_identity_source != "fapi_v2_balance.accountAlias":
            raise CopyTradeRiskError("account observation lacks documented venue account identity")
        if observation.position_mode != "one_way":
            raise CopyTradeRiskError("account observation is not in one-way position mode")
        if observation.can_trade is not True:
            raise CopyTradeRiskError("account observation does not prove trading is enabled")
        if observation.multi_assets_margin is not False:
            raise CopyTradeRiskError("account observation uses unsupported multi-assets margin mode")
        if order.order_type not in {"market", "limit"}:
            raise CopyTradeRiskError(
                "live copy-trade allows only market/limit until algo reconciliation is available"
            )
        if observation.permission_warnings:
            raise CopyTradeRiskError("account permission state contains unresolved warnings")
        for field_name in (
            "source_ref",
            "credential_check_ref",
            "ip_allowlist_ref",
            "withdrawal_disabled_ref",
            "hmac_replay_protection_ref",
            "health_check_ref",
            "rate_limit_ref",
        ):
            if not str(getattr(observation, field_name, "") or "").strip():
                raise CopyTradeRiskError(f"account observation lacks {field_name}")
        observed_at = _parse_timestamp(observation.observed_at_utc)
        age_s = (_now() - observed_at.astimezone(UTC)).total_seconds()
        if age_s < -5 or age_s > max_snapshot_age_s:
            raise CopyTradeRiskError("account observation is future-dated or stale")
        numeric_values = (
            observation.equity,
            observation.mark_price,
            observation.bid_price,
            observation.ask_price,
            observation.maker_fee_bps,
            observation.taker_fee_bps,
            observation.funding_rate_bps,
            order.quantity,
        )
        optional_order_values = tuple(
            value
            for value in (order.price, order.stop_price, order.take_profit_price)
            if value is not None
        )
        if not all(
            math.isfinite(float(value))
            for value in (*numeric_values, *optional_order_values)
        ):
            raise CopyTradeRiskError("live risk state contains non-finite values")
        if order.leverage is None or not math.isfinite(float(order.leverage)):
            raise CopyTradeRiskError("order leverage is missing or non-finite")
        if observation.equity <= 0 or observation.mark_price <= 0 or order.quantity <= 0:
            raise CopyTradeRiskError("live risk state requires positive equity, mark, and quantity")
        if observation.ask_price < observation.bid_price or observation.bid_price <= 0:
            raise CopyTradeRiskError("live order book is malformed")

        mark = float(observation.mark_price)
        if order.price is not None:
            if float(order.price) <= 0:
                raise CopyTradeRiskError("live limit price must be positive")
            deviation = abs(float(order.price) - mark) / mark
            if deviation > float(limits.fat_finger_pct):
                raise CopyTradeRiskError("limit price exceeds the fat-finger deviation limit")
        notional = abs(float(order.quantity) * mark)
        if notional <= 0 or notional > float(limits.per_order_max_usdt):
            raise CopyTradeRiskError("per-order notional exceeds the follower risk limit")
        max_positions = max(int(getattr(follower, "max_positions", 0) or 0), 0)
        if max_positions <= 0:
            raise CopyTradeRiskError("max_positions must be positive for live copy-trade")
        if any(position.margin_mode != "isolated" for position in observation.positions):
            raise CopyTradeRiskError("live copy-trade requires isolated margin on every open position")
        max_leverage = float(getattr(follower, "max_leverage", 0) or 0)
        if max_leverage <= 0 or order.leverage is None or float(order.leverage) > max_leverage:
            raise CopyTradeRiskError("order leverage is missing or exceeds follower max_leverage")
        for position in observation.positions:
            if position.leverage > max_leverage:
                raise CopyTradeRiskError("existing position leverage exceeds follower max_leverage")
            if position.liquidation_price > 0:
                distance = abs(position.mark_price - position.liquidation_price) / position.mark_price
                if distance <= float(limits.liquidation_distance_alert_pct):
                    raise CopyTradeRiskError("existing position is too close to liquidation")

        allocation_equity = min(float(observation.equity), float(getattr(follower, "invest_amount", 0) or 0))
        if allocation_equity <= 0:
            raise CopyTradeRiskError("follower allocation equity is unavailable")
        spread_bps = (observation.ask_price - observation.bid_price) / mark * 10_000
        expected_cost_bps = observation.taker_fee_bps + max(spread_bps / 2, 0) + abs(observation.funding_rate_bps)
        if not math.isfinite(expected_cost_bps) or expected_cost_bps < 0:
            raise CopyTradeRiskError("execution cost state is incomplete")
        expected_cost = notional * expected_cost_bps * 1e-4
        now = _now()
        day = now.date().isoformat()
        created_at = now.isoformat()
        reservation_ref = "copy_risk_reservation_" + content_hash(
            {"follower_id": follower_id, "signal_id": signal_id, "account_binding_ref": account_binding_ref}
        )

        with self._conn() as conn:
            conn.execute("BEGIN IMMEDIATE")
            try:
                duplicate = conn.execute(
                    "SELECT payload_json FROM ct_risk_events WHERE follower_id=? AND signal_id=? AND event_kind='pretrade_reserved'",
                    (follower_id, signal_id),
                ).fetchone()
                if duplicate is not None:
                    conn.rollback()
                    raise CopyTradeRiskError("duplicate signal/follower risk reservation")

                account_rows = self._account_rows(conn, account_binding_ref)
                account_followers = {str(row["follower_id"]) for row in account_rows}
                if account_followers - {follower_id}:
                    raise CopyTradeRiskError("exchange account risk history belongs to a different follower")
                rows = self._rows(conn, follower_id)
                snapshot_event_id = "risk_snapshot_" + content_hash(
                    {
                        "follower_id": follower_id,
                        "signal_id": signal_id,
                        "snapshot_ref": observation.source_ref,
                    }
                )
                self._insert_event(
                    conn,
                    event_id=snapshot_event_id,
                    follower_id=follower_id,
                    account_binding_ref=account_binding_ref,
                    signal_id=signal_id,
                    reservation_ref=None,
                    event_kind="account_snapshot",
                    day=day,
                    payload={
                        "snapshot_ref": observation.source_ref,
                        "equity": observation.equity,
                        "observed_at_utc": observation.observed_at_utc,
                        "position_count": len(observation.positions),
                    },
                    created_at_utc=created_at,
                )
                if not any(row["event_kind"] == "daily_baseline" and row["day"] == day for row in rows):
                    self._insert_event(
                        conn,
                        event_id="risk_baseline_" + content_hash(
                            {"follower_id": follower_id, "account_binding_ref": account_binding_ref, "day": day}
                        ),
                        follower_id=follower_id,
                        account_binding_ref=account_binding_ref,
                        signal_id=None,
                        reservation_ref=None,
                        event_kind="daily_baseline",
                        day=day,
                        payload={"starting_equity": observation.equity, "snapshot_ref": observation.source_ref},
                        created_at_utc=created_at,
                    )
                rows = self._rows(conn, follower_id)
                state = self._derive_state(
                    rows,
                    follower_id=follower_id,
                    account_binding_ref=account_binding_ref,
                    day=day,
                )
                starting_equity = state.starting_equity or observation.equity
                allocation_baseline = min(
                    float(starting_equity),
                    float(getattr(follower, "invest_amount", 0) or 0),
                )
                if allocation_baseline <= 0:
                    raise CopyTradeRiskError("follower allocation baseline is unavailable")
                drawdown = (observation.equity - starting_equity) / allocation_baseline
                if drawdown < -float(limits.daily_loss_limit_pct):
                    raise CopyTradeRiskError("follower allocation drawdown exceeds daily loss limit")
                if state.order_count >= int(limits.daily_order_count_max):
                    raise CopyTradeRiskError("daily order count limit reached")
                pending = self._active_reservations(rows)
                observed_symbols = {position.symbol.upper() for position in observation.positions}
                pending_symbols = {
                    str(payload.get("symbol") or "").upper()
                    for payload in pending.values()
                    if str(payload.get("symbol") or "").strip()
                }
                symbol = order.symbol.upper()
                projected_position_count = len(observed_symbols | pending_symbols | {symbol})
                if projected_position_count > max_positions:
                    raise CopyTradeRiskError("projected position count exceeds max_positions")
                current_symbol_notional = sum(
                    abs(position.quantity * position.mark_price)
                    for position in observation.positions
                    if position.symbol.upper() == symbol
                )
                pending_symbol_notional = sum(
                    float(payload.get("notional_usdt", 0) or 0)
                    for payload in pending.values()
                    if str(payload.get("symbol") or "").upper() == symbol
                )
                projected_concentration = (
                    current_symbol_notional + pending_symbol_notional + notional
                ) / allocation_equity
                if projected_concentration > float(limits.single_symbol_position_pct_max):
                    raise CopyTradeRiskError("projected symbol concentration exceeds the follower limit")
                turnover_cap = float(limits.per_order_max_usdt) * max_positions
                if state.reserved_turnover + state.filled_turnover + notional > turnover_cap:
                    raise CopyTradeRiskError("daily turnover cap would be exceeded")
                risk_check_ref = "copy_risk_check_" + content_hash(
                    {
                        "reservation_ref": reservation_ref,
                        "snapshot_ref": observation.source_ref,
                        "notional_usdt": notional,
                        "daily_turnover_before": state.reserved_turnover,
                        "drawdown_now": drawdown,
                        "projected_position_count": projected_position_count,
                        "projected_symbol_concentration": projected_concentration,
                        "expected_cost_usdt": expected_cost,
                    }
                )
                reservation = PreTradeReservation(
                    reservation_ref=reservation_ref,
                    risk_check_ref=risk_check_ref,
                    follower_id=follower_id,
                    account_binding_ref=account_binding_ref,
                    signal_id=signal_id,
                    symbol=symbol,
                    side=str(order.side),
                    client_order_id=str(order.client_order_id or ""),
                    snapshot_ref=observation.source_ref,
                    trusted_mark_price=mark,
                    order_quantity=float(order.quantity),
                    notional_usdt=notional,
                    expected_cost_usdt=expected_cost,
                    daily_turnover_before=state.reserved_turnover,
                    drawdown_now=drawdown,
                    projected_position_count=projected_position_count,
                    projected_symbol_concentration=projected_concentration,
                    created_at_utc=created_at,
                    attempt_instance_id=self._instance_id,
                )
                self._insert_event(
                    conn,
                    event_id=reservation_ref,
                    follower_id=follower_id,
                    account_binding_ref=account_binding_ref,
                    signal_id=signal_id,
                    reservation_ref=reservation_ref,
                    event_kind="pretrade_reserved",
                    day=day,
                    payload={
                        "reservation": asdict(reservation),
                        "notional_usdt": notional,
                        "symbol": symbol,
                        "side": str(order.side),
                    },
                    created_at_utc=created_at,
                )
                conn.commit()
                return reservation
            except Exception:
                conn.rollback()
                raise

    def _record_transition(
        self,
        reservation: PreTradeReservation,
        *,
        event_kind: str,
        payload: dict[str, Any],
        event_suffix: str,
        occurred_at_utc: str | None = None,
    ) -> str:
        ingested_at = _now()
        try:
            occurred_at = _parse_timestamp(occurred_at_utc) if occurred_at_utc is not None else ingested_at
        except ValueError as exc:
            raise CopyTradeRiskError("risk transition occurrence time is invalid") from exc
        if (occurred_at.astimezone(UTC) - ingested_at).total_seconds() > 5:
            raise CopyTradeRiskError("risk transition occurrence time is future-dated")
        now = ingested_at.isoformat()
        day = occurred_at.astimezone(UTC).date().isoformat()
        event_id = f"{reservation.reservation_ref}:{event_suffix}"
        with self._conn() as conn:
            conn.execute("BEGIN IMMEDIATE")
            try:
                reservation_row = conn.execute(
                    "SELECT * FROM ct_risk_events WHERE reservation_ref=? AND event_kind='pretrade_reserved'",
                    (reservation.reservation_ref,),
                ).fetchone()
                if reservation_row is None:
                    raise CopyTradeRiskError("risk transition references an unknown reservation")
                if (
                    reservation_row["follower_id"] != reservation.follower_id
                    or reservation_row["account_binding_ref"] != reservation.account_binding_ref
                    or reservation_row["signal_id"] != reservation.signal_id
                ):
                    raise CopyTradeRiskError("risk transition reservation identity mismatch")
                persisted_payload = self._payload(reservation_row).get("reservation")
                if not isinstance(persisted_payload, dict):
                    raise CopyTradeRiskError("persisted reservation payload is malformed")
                if PreTradeReservation(**persisted_payload) != reservation:
                    raise CopyTradeRiskError("risk transition reservation content mismatch")
                existing_event = conn.execute(
                    "SELECT * FROM ct_risk_events WHERE event_id=?",
                    (event_id,),
                ).fetchone()
                if existing_event is not None:
                    if existing_event["event_kind"] == event_kind and self._payload(existing_event) == payload:
                        conn.rollback()
                        return event_id
                    raise CopyTradeRiskError("risk transition event identity collision")
                prior_rows = conn.execute(
                    "SELECT event_id,event_kind,payload_json FROM ct_risk_events "
                    "WHERE reservation_ref=? ORDER BY seq",
                    (reservation.reservation_ref,),
                ).fetchall()
                prior_kinds = {str(row["event_kind"]) for row in prior_rows}
                if event_kind == "formal_lifecycle_claim":
                    finalized_claims = {
                        str(json.loads(row["payload_json"]).get("projection_claim_event_id") or "")
                        for row in prior_rows
                        if str(row["event_kind"])
                        in {"fill", "reconciled_no_effect", "reconciled_partial_terminal"}
                    }
                    pending_claims = {
                        str(row["event_id"])
                        for row in prior_rows
                        if str(row["event_kind"]) == "formal_lifecycle_claim"
                        and str(row["event_id"]) not in finalized_claims
                        and str(row["event_id"]) != event_id
                    }
                    if pending_claims:
                        raise CopyTradeRiskError(
                            "reservation has an unfinished lifecycle projection claim"
                        )
                if event_kind == "definitive_reject" and prior_kinds & {
                    "order_request_started",
                    "submission_accepted",
                    "submission_unknown",
                    "fill",
                    "reconciled_no_effect",
                    "reconciled_partial_terminal",
                }:
                    raise CopyTradeRiskError("submitted or unknown reservation cannot become a definitive reject")
                if event_kind == "venue_reject":
                    if "order_request_started" not in prior_kinds:
                        raise CopyTradeRiskError("venue rejection requires a started order request")
                    if prior_kinds & {
                        "definitive_reject",
                        "venue_reject",
                        "submission_accepted",
                        "submission_unknown",
                        "fill",
                        "reconciled_no_effect",
                        "reconciled_partial_terminal",
                    }:
                        raise CopyTradeRiskError("venue rejection conflicts with the reservation state")
                if event_kind == "submission_accepted" and prior_kinds & {
                    "definitive_reject",
                    "venue_reject",
                    "reconciled_no_effect",
                    "reconciled_partial_terminal",
                }:
                    raise CopyTradeRiskError("reservation cannot enter submitted state from its current state")
                if event_kind == "submission_accepted" and "order_request_started" not in prior_kinds:
                    raise CopyTradeRiskError("accepted submission requires the durable order-request boundary")
                if (
                    event_kind == "submission_accepted"
                    and "submission_unknown" in prior_kinds
                    and not str(payload.get("reconciliation_ref") or "").startswith("execution_reconcile_v2_")
                ):
                    raise CopyTradeRiskError("unknown reservation requires formal reconciliation before acceptance")
                if event_kind == "submission_unknown" and prior_kinds & {
                    "definitive_reject",
                    "submission_accepted",
                    "fill",
                    "reconciled_no_effect",
                    "reconciled_partial_terminal",
                }:
                    raise CopyTradeRiskError("reservation cannot enter unknown state from its current state")
                if event_kind == "submission_unknown" and "order_request_started" not in prior_kinds:
                    raise CopyTradeRiskError("unknown submission requires the durable order-request boundary")
                if event_kind == "order_request_started":
                    if prior_kinds & {
                        "definitive_reject",
                        "submission_accepted",
                        "submission_unknown",
                        "fill",
                        "reconciled_no_effect",
                        "reconciled_partial_terminal",
                    }:
                        raise CopyTradeRiskError("order request cannot start from the current reservation state")
                    required_attempt_refs = (
                        "runtime_promotion_ref",
                        "order_intent_ref",
                        "order_materialization_ref",
                        "venue_capability_ref",
                        "submit_request_ref",
                        "client_order_id",
                    )
                    if not all(str(payload.get(field) or "").strip() for field in required_attempt_refs):
                        raise CopyTradeRiskError("order request start lacks formal attempt refs")
                    if payload.get("client_order_id") != reservation.client_order_id:
                        raise CopyTradeRiskError("order request start client identity mismatch")
                if event_kind == "fill" and "submission_accepted" not in prior_kinds:
                    raise CopyTradeRiskError("fill requires a prior accepted submission")
                if event_kind == "fill" and prior_kinds & {"definitive_reject", "reconciled_no_effect"}:
                    raise CopyTradeRiskError("terminal no-effect reservation cannot record a fill")
                if event_kind == "fill" and "reconciled_partial_terminal" in prior_kinds:
                    raise CopyTradeRiskError("terminal partial reservation cannot record another fill")
                if event_kind == "fill":
                    reservation_payload = self._payload(reservation_row).get("reservation")
                    if not isinstance(reservation_payload, dict):
                        raise CopyTradeRiskError("persisted reservation payload is malformed")
                    order_quantity = float(reservation_payload.get("order_quantity", 0) or 0)
                    filled_qty = float(payload.get("filled_qty", 0) or 0)
                    cumulative_filled_qty = float(payload.get("cumulative_filled_qty", 0) or 0)
                    prior_fills = [
                        json.loads(row["payload_json"])
                        for row in prior_rows
                        if row["event_kind"] == "fill"
                    ]
                    if any(item.get("terminal_fill") is True for item in prior_fills):
                        raise CopyTradeRiskError("terminally filled reservation cannot accept another fill")
                    prior_cumulative = max(
                        (float(item.get("cumulative_filled_qty", 0) or 0) for item in prior_fills),
                        default=0.0,
                    )
                    tolerance = max(order_quantity, 1.0) * 1e-9
                    if cumulative_filled_qty <= prior_cumulative + tolerance:
                        raise CopyTradeRiskError("fill cumulative quantity is stale or non-increasing")
                    if abs((cumulative_filled_qty - prior_cumulative) - filled_qty) > tolerance:
                        raise CopyTradeRiskError("fill incremental quantity conflicts with cumulative quantity")
                    if cumulative_filled_qty > order_quantity + tolerance:
                        raise CopyTradeRiskError("fill cumulative quantity exceeds the reserved order quantity")
                    if payload.get("terminal_fill") is True and abs(cumulative_filled_qty - order_quantity) > tolerance:
                        raise CopyTradeRiskError("terminal fill does not cover the reserved order quantity")
                if event_kind == "reconciled_no_effect" and not prior_kinds & {
                    "submission_accepted",
                    "submission_unknown",
                }:
                    raise CopyTradeRiskError("no-effect release requires a prior submitted or outcome-unknown state")
                if event_kind == "reconciled_no_effect" and "fill" in prior_kinds:
                    raise CopyTradeRiskError("filled reservation cannot reconcile to no effect")
                if event_kind in {"reconciled_no_effect", "reconciled_partial_terminal"} and prior_kinds & {
                    "definitive_reject",
                    "venue_reject",
                    "reconciled_no_effect",
                    "reconciled_partial_terminal",
                }:
                    raise CopyTradeRiskError("terminal reservation cannot record a conflicting reconciliation")
                if event_kind == "reconciled_partial_terminal":
                    if "submission_accepted" not in prior_kinds or "fill" not in prior_kinds:
                        raise CopyTradeRiskError(
                            "partial terminal release requires an accepted submission and prior fill"
                        )
                    prior_fills = [
                        json.loads(row["payload_json"])
                        for row in prior_rows
                        if row["event_kind"] == "fill"
                    ]
                    last_cumulative = max(
                        (float(item.get("cumulative_filled_qty", 0) or 0) for item in prior_fills),
                        default=0.0,
                    )
                    observed_cumulative = float(payload.get("cumulative_filled_qty", 0) or 0)
                    order_quantity = float(payload.get("requested_qty", 0) or 0)
                    tolerance = max(order_quantity, 1.0) * 1e-9
                    if (
                        observed_cumulative <= tolerance
                        or observed_cumulative >= order_quantity - tolerance
                        or abs(observed_cumulative - last_cumulative) > tolerance
                    ):
                        raise CopyTradeRiskError(
                            "partial terminal executed quantity does not match the recorded fills"
                        )
                if event_kind == "formal_projection_completed":
                    binding_event_id = str(payload.get("binding_event_id") or "")
                    binding_row = conn.execute(
                        "SELECT event_kind,payload_json FROM ct_risk_events "
                        "WHERE reservation_ref=? AND event_id=?",
                        (reservation.reservation_ref, binding_event_id),
                    ).fetchone()
                    if binding_row is None:
                        raise CopyTradeRiskError(
                            "formal projection completion references an unknown binding event"
                        )
                    if str(binding_row["event_kind"]) not in {
                        "submission_accepted",
                        "submission_unknown",
                        "venue_reject",
                        "definitive_reject",
                    }:
                        raise CopyTradeRiskError(
                            "formal projection completion references a non-binding event"
                        )
                    binding_payload = json.loads(binding_row["payload_json"])
                    if binding_payload.get("submission_ref") != payload.get("submission_ref"):
                        raise CopyTradeRiskError(
                            "formal projection completion submission identity mismatch"
                        )
                self._insert_event(
                    conn,
                    event_id=event_id,
                    follower_id=reservation.follower_id,
                    account_binding_ref=reservation.account_binding_ref,
                    signal_id=reservation.signal_id,
                    reservation_ref=reservation.reservation_ref,
                    event_kind=event_kind,
                    day=day,
                    payload=payload,
                    created_at_utc=now,
                )
                conn.commit()
            except sqlite3.IntegrityError:
                conn.rollback()
                existing = conn.execute(
                    "SELECT * FROM ct_risk_events WHERE event_id=?",
                    (event_id,),
                ).fetchone()
                if existing is None or existing["event_kind"] != event_kind or self._payload(existing) != payload:
                    raise CopyTradeRiskError("risk transition event identity collision")
            except Exception:
                conn.rollback()
                raise
        return event_id

    def mark_submitted(
        self,
        reservation: PreTradeReservation,
        *,
        submission_ref: str,
        venue_order_ref: str,
        ack_ref: str,
        ack_accepted_at_utc: str | None = None,
        reconciliation_ref: str | None = None,
        ack_status: str = "new",
        actor: str = "system",
        projection_kind: str = "ack",
    ) -> None:
        if not all(str(value or "").strip() for value in (submission_ref, venue_order_ref, ack_ref)):
            raise CopyTradeRiskError("accepted submission transition requires submission, venue-order, and ack refs")
        projection = {
            "submission_ref": submission_ref,
            "venue_order_ref": venue_order_ref,
            "ack_ref": ack_ref,
            "ack_status": str(ack_status or "").lower(),
            "actor": str(actor or "system"),
            "projection_kind": projection_kind,
            "formal_submission_status": (
                "outcome_unknown" if projection_kind == "fill_recovered" else "accepted"
            ),
            "reconciliation_ref": reconciliation_ref,
        }
        if str(ack_accepted_at_utc or "").strip():
            projection["ack_accepted_at_utc"] = str(ack_accepted_at_utc)
        projection["projection_digest"] = content_hash(projection)
        return self._record_transition(
            reservation,
            event_kind="submission_accepted",
            event_suffix="submitted",
            payload=projection,
        )

    def mark_submission_unknown(
        self,
        reservation: PreTradeReservation,
        *,
        reason_ref: str,
        submission_ref: str | None = None,
        venue_order_ref: str | None = None,
        ack_ref: str | None = None,
        actor: str = "system",
    ) -> None:
        if not str(reason_ref or "").strip():
            raise CopyTradeRiskError("unknown submission transition requires reason_ref")
        projection = {
            "reason_ref": reason_ref,
            "submission_ref": submission_ref,
            "venue_order_ref": venue_order_ref,
            "ack_ref": ack_ref,
            "actor": str(actor or "system"),
            "projection_kind": "outcome_unknown",
            "formal_submission_status": "outcome_unknown",
        }
        projection["projection_digest"] = content_hash(projection)
        self._record_transition(
            reservation,
            event_kind="submission_unknown",
            event_suffix="unknown",
            payload=projection,
        )

    def mark_order_request_started(
        self,
        reservation: PreTradeReservation,
        *,
        runtime_promotion_ref: str,
        order_intent_ref: str,
        order_materialization_ref: str,
        venue_capability_ref: str,
        submit_request_ref: str,
    ) -> None:
        """Durably cross the exact order-POST boundary before network I/O."""

        self._record_transition(
            reservation,
            event_kind="order_request_started",
            event_suffix="order_request_started",
            payload={
                "runtime_promotion_ref": runtime_promotion_ref,
                "order_intent_ref": order_intent_ref,
                "order_materialization_ref": order_materialization_ref,
                "venue_capability_ref": venue_capability_ref,
                "submit_request_ref": submit_request_ref,
                "client_order_id": reservation.client_order_id,
            },
        )

    def mark_definitive_reject(
        self,
        reservation: PreTradeReservation,
        *,
        reason_ref: str,
        submission_ref: str | None = None,
        ack_ref: str | None = None,
        actor: str = "system",
    ) -> None:
        if not str(reason_ref or "").strip():
            raise CopyTradeRiskError("definitive reject transition requires reason_ref")
        projection = {
            "reason_ref": reason_ref,
            "submission_ref": submission_ref,
            "venue_order_ref": None,
            "ack_ref": ack_ref,
            "ack_status": "rejected",
            "actor": str(actor or "system"),
            "projection_kind": "definitive_reject" if submission_ref else "pre_submit_reject",
            "formal_submission_status": "rejected" if submission_ref else "",
        }
        projection["projection_digest"] = content_hash(projection)
        self._record_transition(
            reservation,
            event_kind="definitive_reject",
            event_suffix="rejected",
            payload=projection,
        )

    def mark_venue_reject(
        self,
        reservation: PreTradeReservation,
        *,
        reason_ref: str,
        submission_ref: str,
        venue_order_ref: str | None,
        ack_ref: str,
        ack_accepted_at_utc: str | None = None,
        actor: str,
    ) -> None:
        if not str(reason_ref or "").strip():
            raise CopyTradeRiskError("venue reject transition requires reason_ref")
        projection = {
            "reason_ref": reason_ref,
            "submission_ref": submission_ref,
            "venue_order_ref": venue_order_ref,
            "ack_ref": ack_ref,
            "ack_status": "rejected",
            "actor": str(actor or "system"),
            "projection_kind": "venue_reject",
            "formal_submission_status": "rejected",
        }
        if str(ack_accepted_at_utc or "").strip():
            projection["ack_accepted_at_utc"] = str(ack_accepted_at_utc)
        projection["projection_digest"] = content_hash(projection)
        self._record_transition(
            reservation,
            event_kind="venue_reject",
            event_suffix="venue_rejected",
            payload=projection,
        )

    def mark_formal_projection_completed(
        self,
        reservation: PreTradeReservation,
        *,
        binding_event_id: str,
        submission_ref: str,
        venue_event_ref: str | None,
        reconciliation_ref: str,
    ) -> None:
        if not all(
            str(value or "").strip()
            for value in (binding_event_id, submission_ref, reconciliation_ref)
        ):
            raise CopyTradeRiskError("formal projection completion lacks required refs")
        self._record_transition(
            reservation,
            event_kind="formal_projection_completed",
            event_suffix="formal_projection_completed:" + content_hash(binding_event_id),
            payload={
                "binding_event_id": binding_event_id,
                "submission_ref": submission_ref,
                "venue_event_ref": venue_event_ref,
                "reconciliation_ref": reconciliation_ref,
            },
        )

    @staticmethod
    def _resolve_realized_pnl(
        report: ExecutionReport,
        *,
        realized_pnl_delta: float | None,
        realized_pnl_complete: bool | None,
    ) -> tuple[float, bool]:
        if realized_pnl_delta is None:
            resolved_delta = float(report.realized_pnl_delta)
            resolved_complete = (
                report.realized_pnl_complete
                if realized_pnl_complete is None
                else realized_pnl_complete
            )
        else:
            resolved_delta = float(realized_pnl_delta)
            resolved_complete = True if realized_pnl_complete is None else realized_pnl_complete
        if type(resolved_complete) is not bool:
            raise CopyTradeRiskError("realized PnL completeness must be an exact boolean")
        if not math.isfinite(resolved_delta):
            raise CopyTradeRiskError("fill realized PnL must be finite")
        if not resolved_complete and resolved_delta != 0:
            raise CopyTradeRiskError("incomplete realized PnL cannot carry a nonzero value")
        if report.realized_pnl_complete and (
            not resolved_complete
            or not math.isclose(
                resolved_delta,
                float(report.realized_pnl_delta),
                rel_tol=1e-12,
                abs_tol=1e-12,
            )
        ):
            raise CopyTradeRiskError("fill realized PnL differs from its venue report")
        return resolved_delta, resolved_complete

    @staticmethod
    def _fill_transition_payload(
        *,
        report: ExecutionReport,
        submission_ref: str,
        venue_event_ref: str,
        normalized_cost_usdt: float | None,
        cost_conversion_ref: str | None,
        realized_pnl_delta: float,
        realized_pnl_complete: bool,
        reconciliation_ref: str | None,
        projection_claim_event_id: str | None,
        actor: str,
    ) -> dict[str, Any]:
        cost_complete = normalized_cost_usdt is not None and bool(cost_conversion_ref)
        return {
            "submission_ref": submission_ref,
            "venue_event_ref": venue_event_ref,
            "source_event_ref": report.source_event_ref,
            "raw_event_hash": report.raw_event_hash,
            "client_order_id": report.client_order_id,
            "venue_order_ref": report.order_id,
            "filled_qty": float(report.filled_qty),
            "cumulative_filled_qty": float(report.cumulative_filled_qty),
            "fill_price": float(report.fill_price),
            "filled_notional_usdt": abs(float(report.filled_qty) * float(report.fill_price)),
            "commission": float(report.commission),
            "commission_asset": str(report.commission_asset or ""),
            "normalized_cost_usdt": normalized_cost_usdt,
            "cost_conversion_ref": cost_conversion_ref,
            "cost_complete": cost_complete,
            "terminal_fill": str(report.status).lower() == "filled",
            "occurred_at_utc": report.timestamp_utc,
            "realized_pnl_delta": float(realized_pnl_delta),
            "realized_pnl_complete": realized_pnl_complete,
            "reconciliation_ref": str(reconciliation_ref or ""),
            "projection_claim_event_id": str(projection_claim_event_id or ""),
            "actor": str(actor or ""),
        }

    def record_fill(
        self,
        reservation: PreTradeReservation,
        *,
        report: ExecutionReport,
        submission_ref: str,
        venue_event_ref: str,
        normalized_cost_usdt: float | None,
        cost_conversion_ref: str | None,
        realized_pnl_delta: float | None = None,
        realized_pnl_complete: bool | None = None,
        reconciliation_ref: str | None = None,
        projection_claim_event_id: str | None = None,
        actor: str = "binance_execution_reconciler",
        _finalize_token: object | None = None,
    ) -> str:
        realized_pnl_delta, realized_pnl_complete = self._resolve_realized_pnl(
            report,
            realized_pnl_delta=realized_pnl_delta,
            realized_pnl_complete=realized_pnl_complete,
        )
        if projection_claim_event_id and _finalize_token is not self.__lifecycle_finalize_token:
            claim = self.lifecycle_projection_claim(projection_claim_event_id)
            payload = claim["payload"]
            expected = {
                "projection_kind": "fill",
                "submission_ref": submission_ref,
                "actor": actor,
                "report": asdict(report),
                "venue_event_ref": venue_event_ref,
                "reconciliation_ref": str(reconciliation_ref or ""),
                "normalized_cost_usdt": normalized_cost_usdt,
                "cost_conversion_ref": cost_conversion_ref,
                "realized_pnl_delta": float(realized_pnl_delta),
                "realized_pnl_complete": realized_pnl_complete,
            }
            actual = {
                "projection_kind": payload.get("projection_kind"),
                "submission_ref": payload.get("submission_ref"),
                "actor": payload.get("actor"),
                "report": payload.get("report"),
                "venue_event_ref": (payload.get("venue_event") or {}).get("venue_event_ref"),
                "reconciliation_ref": (payload.get("reconciliation") or {}).get(
                    "reconciliation_ref"
                ),
                "normalized_cost_usdt": payload.get("normalized_cost_usdt"),
                "cost_conversion_ref": payload.get("cost_conversion_ref"),
                "realized_pnl_delta": float(payload.get("realized_pnl_delta", 0) or 0),
                "realized_pnl_complete": payload.get("realized_pnl_complete") is True,
            }
            if actual != expected:
                raise CopyTradeRiskError("fill finalization call differs from its sealed claim")
            return self.finalize_lifecycle_projection_claim(
                reservation,
                claim_event_id=projection_claim_event_id,
            )
        if not projection_claim_event_id and not self._allow_unsealed_test_transitions:
            raise CopyTradeRiskError("fill transition requires a sealed lifecycle projection claim")
        self.validate_fill(
            reservation,
            report=report,
            submission_ref=submission_ref,
            venue_event_ref=venue_event_ref,
            normalized_cost_usdt=normalized_cost_usdt,
            cost_conversion_ref=cost_conversion_ref,
            realized_pnl_delta=realized_pnl_delta,
            realized_pnl_complete=realized_pnl_complete,
            reconciliation_ref=reconciliation_ref,
            projection_claim_event_id=projection_claim_event_id,
            actor=actor,
        )
        payload = self._fill_transition_payload(
            report=report,
            submission_ref=submission_ref,
            venue_event_ref=venue_event_ref,
            normalized_cost_usdt=normalized_cost_usdt,
            cost_conversion_ref=cost_conversion_ref,
            realized_pnl_delta=realized_pnl_delta,
            realized_pnl_complete=realized_pnl_complete,
            reconciliation_ref=reconciliation_ref,
            projection_claim_event_id=projection_claim_event_id,
            actor=actor,
        )
        return self._record_transition(
            reservation,
            event_kind="fill",
            event_suffix="fill:" + report.source_event_ref,
            payload=payload,
            occurred_at_utc=report.timestamp_utc,
        )

    def validate_fill(
        self,
        reservation: PreTradeReservation,
        *,
        report: ExecutionReport,
        submission_ref: str,
        venue_event_ref: str,
        normalized_cost_usdt: float | None,
        cost_conversion_ref: str | None,
        realized_pnl_delta: float | None = None,
        realized_pnl_complete: bool | None = None,
        reconciliation_ref: str | None = None,
        projection_claim_event_id: str | None = None,
        actor: str = "binance_execution_reconciler",
    ) -> None:
        """Validate a fill completely before any formal or risk append."""

        realized_pnl_delta, realized_pnl_complete = self._resolve_realized_pnl(
            report,
            realized_pnl_delta=realized_pnl_delta,
            realized_pnl_complete=realized_pnl_complete,
        )
        self._assert_exact_persisted_reservation(reservation)
        numeric = (
            report.filled_qty,
            report.cumulative_filled_qty,
            report.fill_price,
            report.commission,
            realized_pnl_delta,
        )
        if not all(math.isfinite(float(value)) for value in numeric):
            raise CopyTradeRiskError("fill contains non-finite numeric state")
        if report.filled_qty <= 0 or report.fill_price <= 0 or report.commission < 0:
            raise CopyTradeRiskError("fill quantity/price must be positive and commission nonnegative")
        if report.status not in {"partially_filled", "filled"}:
            raise CopyTradeRiskError("fill event must have partially_filled or filled status")
        if report.cumulative_filled_qty < report.filled_qty:
            raise CopyTradeRiskError("fill cumulative quantity cannot be below the incremental quantity")
        if report.symbol.upper() != reservation.symbol or str(report.side) != reservation.side:
            raise CopyTradeRiskError("fill instrument or side does not match the reservation")
        if str(report.client_order_id or "") != reservation.client_order_id:
            raise CopyTradeRiskError("fill client-order identity does not match the reservation")
        if not str(report.source_event_ref or "").strip():
            raise CopyTradeRiskError("fill requires a source event identity")
        try:
            expected_raw_hash = canonical_raw_event_hash(report.raw)
        except ValueError as exc:
            raise CopyTradeRiskError("fill requires a nonempty raw venue payload") from exc
        if report.raw_event_hash != expected_raw_hash:
            raise CopyTradeRiskError("fill raw-event digest does not match the raw venue payload")
        if not str(report.commission_asset or "").strip():
            raise CopyTradeRiskError("fill commission asset is required")
        if normalized_cost_usdt is not None and (
            not math.isfinite(float(normalized_cost_usdt)) or float(normalized_cost_usdt) < 0
        ):
            raise CopyTradeRiskError("normalized fill cost must be finite and nonnegative")
        if (normalized_cost_usdt is None) != (not bool(cost_conversion_ref)):
            raise CopyTradeRiskError("normalized fill cost and conversion ref must be provided together")
        with self._conn() as conn:
            prior_rows = conn.execute(
                "SELECT event_kind,payload_json FROM ct_risk_events "
                "WHERE reservation_ref=? ORDER BY seq",
                (reservation.reservation_ref,),
            ).fetchall()
        submitted = next(
            (
                row
                for row in reversed(prior_rows)
                if str(row["event_kind"]) in {"submission_accepted", "submission_unknown"}
            ),
            None,
        )
        if submitted is None:
            raise CopyTradeRiskError("fill has no submitted or outcome-unknown binding")
        submitted_payload = json.loads(submitted["payload_json"])
        if submitted_payload.get("submission_ref") != submission_ref:
            raise CopyTradeRiskError("fill submission binding mismatch")
        bound_venue_order = str(submitted_payload.get("venue_order_ref") or "")
        if bound_venue_order and bound_venue_order != report.order_id:
            raise CopyTradeRiskError("fill submission or venue-order binding mismatch")
        if not str(venue_event_ref or "").strip():
            raise CopyTradeRiskError("fill requires venue_event_ref")
        prior_fills = [
            json.loads(row["payload_json"])
            for row in prior_rows
            if str(row["event_kind"]) == "fill"
        ]
        expected_payload = self._fill_transition_payload(
            report=report,
            submission_ref=submission_ref,
            venue_event_ref=venue_event_ref,
            normalized_cost_usdt=normalized_cost_usdt,
            cost_conversion_ref=cost_conversion_ref,
            realized_pnl_delta=realized_pnl_delta,
            realized_pnl_complete=realized_pnl_complete,
            reconciliation_ref=reconciliation_ref,
            projection_claim_event_id=projection_claim_event_id,
            actor=actor,
        )
        same_source = [
            item
            for item in prior_fills
            if str(item.get("source_event_ref") or "") == report.source_event_ref
        ]
        if same_source:
            if len(same_source) != 1 or same_source[0] != expected_payload:
                raise CopyTradeRiskError("fill source event identity collision")
            return
        prior_kinds = {str(row["event_kind"]) for row in prior_rows}
        if prior_kinds & {"definitive_reject", "venue_reject", "reconciled_no_effect"}:
            raise CopyTradeRiskError("terminal no-effect reservation cannot record a fill")
        if "reconciled_partial_terminal" in prior_kinds:
            raise CopyTradeRiskError("terminal partial reservation cannot record another fill")
        if any(item.get("terminal_fill") is True for item in prior_fills):
            raise CopyTradeRiskError("terminally filled reservation cannot accept another fill")
        prior_cumulative = max(
            (float(item.get("cumulative_filled_qty", 0) or 0) for item in prior_fills),
            default=0.0,
        )
        tolerance = max(reservation.order_quantity, 1.0) * 1e-9
        if report.cumulative_filled_qty <= prior_cumulative + tolerance:
            raise CopyTradeRiskError("fill cumulative quantity is stale or non-increasing")
        if abs((report.cumulative_filled_qty - prior_cumulative) - report.filled_qty) > tolerance:
            raise CopyTradeRiskError("fill incremental quantity conflicts with cumulative quantity")
        if report.cumulative_filled_qty > reservation.order_quantity + tolerance:
            raise CopyTradeRiskError("fill cumulative quantity exceeds the reserved order quantity")
        if report.status == "filled" and abs(
            report.cumulative_filled_qty - reservation.order_quantity
        ) > tolerance:
            raise CopyTradeRiskError("terminal fill does not cover the reserved order quantity")

    def _assert_no_other_pending_lifecycle_claim(
        self,
        reservation: PreTradeReservation,
        *,
        candidate_event_id: str,
    ) -> None:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT event_id,event_kind,payload_json FROM ct_risk_events "
                "WHERE reservation_ref=? ORDER BY seq",
                (reservation.reservation_ref,),
            ).fetchall()
        finalized = {
            str(json.loads(row["payload_json"]).get("projection_claim_event_id") or "")
            for row in rows
            if str(row["event_kind"]) in {"fill", "reconciled_no_effect", "reconciled_partial_terminal"}
        }
        pending = {
            str(row["event_id"])
            for row in rows
            if str(row["event_kind"]) == "formal_lifecycle_claim"
            and str(row["event_id"]) not in finalized
            and str(row["event_id"]) != candidate_event_id
        }
        if pending:
            raise CopyTradeRiskError("reservation has an unfinished lifecycle projection claim")

    @staticmethod
    def _same_lifecycle_claim_semantics(left: dict[str, Any], right: dict[str, Any]) -> bool:
        a = json.loads(json.dumps(left, sort_keys=True))
        b = json.loads(json.dumps(right, sort_keys=True))
        for payload in (a, b):
            for field_name in ("venue_event", "reconciliation"):
                nested = payload.get(field_name)
                if isinstance(nested, dict):
                    nested.pop("created_at_utc", None)
        return a == b

    def _claim_formal_context(
        self,
        reservation: PreTradeReservation,
        *,
        submission_ref: str,
        candidate_event: ExecutionVenueEventRecord,
    ) -> tuple[dict[str, str], Any, tuple[ExecutionVenueEventRecord, ...]]:
        context = self.order_request_context(reservation.reservation_ref)
        if context is None:
            raise CopyTradeRiskError("lifecycle projection claim lacks order-request context")
        if self._submission_store is None or self._venue_event_store is None:
            raise CopyTradeRiskError("lifecycle projection claim lacks strict formal parent stores")
        for store in (self._submission_store, self._venue_event_store):
            refresh = getattr(store, "refresh", None)
            if callable(refresh):
                refresh()
        try:
            submission = self._submission_store.submission(submission_ref)
        except (KeyError, TypeError, ValueError) as exc:
            raise CopyTradeRiskError("lifecycle projection submission parent does not resolve") from exc
        if submission.submission_ref != submission_ref:
            raise CopyTradeRiskError("lifecycle projection submission parent identity mismatch")
        events_reader = getattr(self._venue_event_store, "events", None)
        if not callable(events_reader):
            raise CopyTradeRiskError("lifecycle projection venue-event store cannot enumerate history")
        existing = [
            item
            for item in events_reader()
            if item.submission_ref == submission_ref
            and item.venue_event_ref != candidate_event.venue_event_ref
        ]
        events = tuple(
            sorted(
                (*existing, candidate_event),
                key=lambda item: (item.created_at_utc, item.venue_event_ref),
            )
        )
        return context, submission, events

    def _assert_fill_claim_formal_semantics(
        self,
        reservation: PreTradeReservation,
        *,
        report: ExecutionReport,
        submission_ref: str,
        venue_event: ExecutionVenueEventRecord,
        reconciliation: ExecutionReconciliationRecord,
        normalized_cost_usdt: float | None,
        cost_conversion_ref: str | None,
        actor: str,
    ) -> None:
        context, submission, events = self._claim_formal_context(
            reservation,
            submission_ref=submission_ref,
            candidate_event=venue_event,
        )
        fill_ref = str(report.source_event_ref)
        expected_event = ExecutionVenueEventRecord(
            order_intent_ref=context["order_intent_ref"],
            runtime_promotion_ref=context["runtime_promotion_ref"],
            submission_ref=submission_ref,
            venue_ref=submission.venue_ref,
            event_kind=str(report.status),
            status=str(report.status),
            audit_record_ref="copy_fill_audit_" + content_hash(fill_ref),
            order_guard_ref=submission.order_guard_ref,
            idempotency_key=submission.idempotency_key,
            venue_order_ref=str(report.order_id),
            client_order_ref=str(report.client_order_id),
            fill_ref=fill_ref,
            quantity_ref="fill_quantity_"
            + content_hash(
                {
                    "filled_qty": report.filled_qty,
                    "cumulative_filled_qty": report.cumulative_filled_qty,
                }
            ),
            price_ref="fill_price_" + content_hash({"fill_price": report.fill_price}),
            fee_ref="execution_fee_"
            + content_hash(
                {
                    "fill_ref": fill_ref,
                    "commission": report.commission,
                    "commission_asset": report.commission_asset,
                    "normalized_cost_usdt": normalized_cost_usdt,
                    "cost_conversion_ref": cost_conversion_ref,
                }
            ),
            raw_event_hash=report.raw_event_hash,
            evidence_refs=tuple(
                ref
                for ref in (fill_ref, report.raw_event_hash, cost_conversion_ref)
                if str(ref or "").strip()
            ),
            recorded_by=actor,
            created_at_utc=report.timestamp_utc,
        )
        if venue_event.to_dict() != expected_event.to_dict():
            raise CopyTradeRiskError("fill projection venue event is not report-exact")
        expected_reconciliation = reconcile_execution_venue_events(
            order_intent_ref=context["order_intent_ref"],
            runtime_promotion_ref=context["runtime_promotion_ref"],
            submission_ref=submission_ref,
            venue_order_ref=str(report.order_id),
            audit_record_ref="copy_fill_reconcile_audit_"
            + content_hash(
                {
                    "submission_ref": submission_ref,
                    "event_refs": [item.venue_event_ref for item in events],
                }
            ),
            events=events,
            evidence_refs=tuple(item.venue_event_ref for item in events),
            recorded_by=actor,
        )
        if not self._same_lifecycle_claim_semantics(
            {"reconciliation": reconciliation.to_dict()},
            {"reconciliation": expected_reconciliation.to_dict()},
        ):
            raise CopyTradeRiskError("fill projection reconciliation is not history-exact")
        event_decision = validate_execution_venue_event(
            venue_event,
            known_order_intent_refs={context["order_intent_ref"]},
            known_runtime_promotion_refs={context["runtime_promotion_ref"]},
            known_submission_refs={submission_ref},
            submission=submission,
        )
        reconciliation_decision = validate_execution_reconciliation(
            reconciliation,
            known_order_intent_refs={context["order_intent_ref"]},
            known_runtime_promotion_refs={context["runtime_promotion_ref"]},
            known_venue_event_refs={item.venue_event_ref for item in events},
            known_submission_refs={submission_ref},
            submission=submission,
            venue_events=events,
        )
        if not event_decision.accepted or not reconciliation_decision.accepted:
            raise CopyTradeRiskError("fill projection claim fails strict formal-parent validation")

    def _assert_terminal_claim_formal_semantics(
        self,
        reservation: PreTradeReservation,
        *,
        observation: OrderExecutionObservation,
        submission_ref: str,
        venue_event: ExecutionVenueEventRecord,
        reconciliation: ExecutionReconciliationRecord,
        actor: str,
    ) -> None:
        context, submission, events = self._claim_formal_context(
            reservation,
            submission_ref=submission_ref,
            candidate_event=venue_event,
        )
        expected_event = ExecutionVenueEventRecord(
            order_intent_ref=context["order_intent_ref"],
            runtime_promotion_ref=context["runtime_promotion_ref"],
            submission_ref=submission_ref,
            venue_ref=submission.venue_ref,
            event_kind=observation.status,
            status=observation.status,
            audit_record_ref="copy_terminal_audit_" + content_hash(observation.source_event_ref),
            order_guard_ref=submission.order_guard_ref,
            idempotency_key=submission.idempotency_key,
            venue_order_ref=observation.order_id,
            client_order_ref=observation.client_order_id,
            ack_ref=(observation.source_event_ref if observation.status == "rejected" else None),
            quantity_ref="terminal_quantity_"
            + content_hash(
                {
                    "requested_qty": observation.requested_qty,
                    "cumulative_filled_qty": observation.cumulative_filled_qty,
                }
            ),
            raw_event_hash=observation.raw_event_hash,
            evidence_refs=(observation.source_event_ref, observation.raw_event_hash),
            recorded_by=actor,
            created_at_utc=observation.observed_at_utc,
        )
        if venue_event.to_dict() != expected_event.to_dict():
            raise CopyTradeRiskError("terminal projection venue event is not observation-exact")
        expected_reconciliation = reconcile_execution_venue_events(
            order_intent_ref=context["order_intent_ref"],
            runtime_promotion_ref=context["runtime_promotion_ref"],
            submission_ref=submission_ref,
            venue_order_ref=observation.order_id,
            audit_record_ref="copy_terminal_reconcile_audit_"
            + content_hash(
                {
                    "submission_ref": submission_ref,
                    "event_refs": [item.venue_event_ref for item in events],
                }
            ),
            events=events,
            evidence_refs=tuple(item.venue_event_ref for item in events),
            recorded_by=actor,
        )
        if not self._same_lifecycle_claim_semantics(
            {"reconciliation": reconciliation.to_dict()},
            {"reconciliation": expected_reconciliation.to_dict()},
        ):
            raise CopyTradeRiskError("terminal projection reconciliation is not history-exact")
        event_decision = validate_execution_venue_event(
            venue_event,
            known_order_intent_refs={context["order_intent_ref"]},
            known_runtime_promotion_refs={context["runtime_promotion_ref"]},
            known_submission_refs={submission_ref},
            submission=submission,
        )
        reconciliation_decision = validate_execution_reconciliation(
            reconciliation,
            known_order_intent_refs={context["order_intent_ref"]},
            known_runtime_promotion_refs={context["runtime_promotion_ref"]},
            known_venue_event_refs={item.venue_event_ref for item in events},
            known_submission_refs={submission_ref},
            submission=submission,
            venue_events=events,
        )
        if not event_decision.accepted or not reconciliation_decision.accepted:
            raise CopyTradeRiskError("terminal projection claim fails strict formal-parent validation")

    def claim_fill_projection(
        self,
        reservation: PreTradeReservation,
        *,
        report: ExecutionReport,
        submission_ref: str,
        venue_event: ExecutionVenueEventRecord,
        reconciliation: ExecutionReconciliationRecord,
        normalized_cost_usdt: float | None,
        cost_conversion_ref: str | None,
        realized_pnl_delta: float | None = None,
        realized_pnl_complete: bool | None = None,
        actor: str,
    ) -> str:
        realized_pnl_delta, realized_pnl_complete = self._resolve_realized_pnl(
            report,
            realized_pnl_delta=realized_pnl_delta,
            realized_pnl_complete=realized_pnl_complete,
        )
        claim_event_id = (
            f"{reservation.reservation_ref}:lifecycle_claim:fill:{report.source_event_ref}"
        )
        self.validate_fill(
            reservation,
            report=report,
            submission_ref=submission_ref,
            venue_event_ref=venue_event.venue_event_ref,
            normalized_cost_usdt=normalized_cost_usdt,
            cost_conversion_ref=cost_conversion_ref,
            realized_pnl_delta=realized_pnl_delta,
            realized_pnl_complete=realized_pnl_complete,
            reconciliation_ref=reconciliation.reconciliation_ref,
            projection_claim_event_id=claim_event_id,
            actor=actor,
        )
        self._assert_fill_claim_formal_semantics(
            reservation,
            report=report,
            submission_ref=submission_ref,
            venue_event=venue_event,
            reconciliation=reconciliation,
            normalized_cost_usdt=normalized_cost_usdt,
            cost_conversion_ref=cost_conversion_ref,
            actor=actor,
        )
        if not validate_execution_venue_event(venue_event).accepted:
            raise CopyTradeRiskError("fill projection claim has invalid canonical venue event")
        if not validate_execution_reconciliation(reconciliation).accepted:
            raise CopyTradeRiskError("fill projection claim has invalid canonical reconciliation")
        if venue_event.venue_event_ref not in set(reconciliation.event_refs):
            raise CopyTradeRiskError("fill projection reconciliation omits the candidate event")
        self._assert_no_other_pending_lifecycle_claim(
            reservation,
            candidate_event_id=claim_event_id,
        )
        payload = {
            "projection_kind": "fill",
            "submission_ref": submission_ref,
            "source_event_ref": report.source_event_ref,
            "actor": actor,
            "report": asdict(report),
            "venue_event": venue_event.to_dict(),
            "reconciliation": reconciliation.to_dict(),
            "normalized_cost_usdt": normalized_cost_usdt,
            "cost_conversion_ref": cost_conversion_ref,
            "realized_pnl_delta": float(realized_pnl_delta),
            "realized_pnl_complete": realized_pnl_complete,
        }
        try:
            existing_claim = self.lifecycle_projection_claim(claim_event_id)
        except CopyTradeRiskError:
            existing_claim = None
        if existing_claim is not None:
            if not self._same_lifecycle_claim_semantics(existing_claim["payload"], payload):
                raise CopyTradeRiskError("fill projection claim identity collision")
            return claim_event_id
        actual = self._record_transition(
            reservation,
            event_kind="formal_lifecycle_claim",
            event_suffix="lifecycle_claim:fill:" + report.source_event_ref,
            payload=payload,
            occurred_at_utc=report.timestamp_utc,
        )
        if actual != claim_event_id:
            raise CopyTradeRiskError("fill projection claim identity mismatch")
        return actual

    def _validate_terminal_observation(
        self,
        reservation: PreTradeReservation,
        observation: OrderExecutionObservation,
    ) -> None:
        self._assert_exact_persisted_reservation(reservation)
        if observation.symbol.upper() != reservation.symbol or observation.side != reservation.side:
            raise CopyTradeRiskError("terminal order instrument or side does not match the reservation")
        if observation.client_order_id != reservation.client_order_id:
            raise CopyTradeRiskError("terminal order client identity does not match the reservation")
        tolerance = max(reservation.order_quantity, 1.0) * 1e-9
        if abs(observation.requested_qty - reservation.order_quantity) > tolerance:
            raise CopyTradeRiskError("terminal order requested quantity does not match the reservation")
        if not str(observation.order_id or "").strip():
            raise CopyTradeRiskError("terminal order lacks venue order identity")
        if not str(observation.source_event_ref or "").strip():
            raise CopyTradeRiskError("terminal order lacks source observation identity")
        try:
            expected_raw_hash = canonical_raw_event_hash(observation.raw)
        except ValueError as exc:
            raise CopyTradeRiskError(
                "terminal order requires a nonempty raw venue payload"
            ) from exc
        if observation.raw_event_hash != expected_raw_hash:
            raise CopyTradeRiskError(
                "terminal order raw digest does not match the raw venue payload"
            )
        try:
            _parse_timestamp(observation.observed_at_utc)
        except ValueError as exc:
            raise CopyTradeRiskError("terminal order observation time is invalid") from exc

    def validate_terminal_observation(
        self,
        reservation: PreTradeReservation,
        observation: OrderExecutionObservation,
        *,
        submission_ref: str,
        venue_event_ref: str,
    ) -> None:
        """Public pre-append validation for terminal venue observations."""

        self._validate_terminal_observation(reservation, observation)
        if not all(
            math.isfinite(float(value))
            for value in (
                observation.requested_qty,
                observation.cumulative_filled_qty,
            )
        ):
            raise CopyTradeRiskError("terminal order observation contains non-finite quantity")
        with self._conn() as conn:
            prior_rows = conn.execute(
                "SELECT event_kind,payload_json FROM ct_risk_events "
                "WHERE reservation_ref=? ORDER BY seq",
                (reservation.reservation_ref,),
            ).fetchall()
        submitted = next(
            (
                row
                for row in reversed(prior_rows)
                if str(row["event_kind"]) in {"submission_accepted", "submission_unknown"}
            ),
            None,
        )
        if submitted is None:
            raise CopyTradeRiskError("terminal observation lacks a submitted reservation state")
        submitted_payload = json.loads(submitted["payload_json"])
        if submitted_payload.get("submission_ref") != submission_ref:
            raise CopyTradeRiskError("terminal observation submission binding mismatch")
        if not str(venue_event_ref or "").strip():
            raise CopyTradeRiskError("terminal observation requires venue_event_ref")
        bound_order = str(submitted_payload.get("venue_order_ref") or "")
        if bound_order and bound_order != observation.order_id:
            raise CopyTradeRiskError("terminal observation venue-order binding mismatch")
        terminal_payloads = [
            json.loads(row["payload_json"])
            for row in prior_rows
            if str(row["event_kind"]) in {"reconciled_no_effect", "reconciled_partial_terminal"}
        ]
        same_source = [
            payload
            for payload in terminal_payloads
            if str(payload.get("source_event_ref") or "") == observation.source_event_ref
        ]
        if same_source:
            if len(same_source) != 1:
                raise CopyTradeRiskError("terminal source event identity collision")
            existing = same_source[0]
            expected_fields = {
                "venue_event_ref": venue_event_ref,
                "status": observation.status,
                "venue_order_ref": observation.order_id,
                "source_event_ref": observation.source_event_ref,
                "raw_event_hash": observation.raw_event_hash,
                "requested_qty": observation.requested_qty,
                "cumulative_filled_qty": observation.cumulative_filled_qty,
            }
            if any(existing.get(field) != value for field, value in expected_fields.items()):
                raise CopyTradeRiskError("terminal source event identity collision")
            return
        if terminal_payloads:
            raise CopyTradeRiskError("terminal reservation cannot record a conflicting observation")
        prior_fills = [
            json.loads(row["payload_json"])
            for row in prior_rows
            if str(row["event_kind"]) == "fill"
        ]
        tolerance = max(reservation.order_quantity, 1.0) * 1e-9
        observed_cumulative = float(observation.cumulative_filled_qty)
        if observed_cumulative < -tolerance or observed_cumulative > reservation.order_quantity + tolerance:
            raise CopyTradeRiskError("terminal observation cumulative quantity is outside the reservation")
        if observed_cumulative <= tolerance:
            if prior_fills:
                raise CopyTradeRiskError("no-effect terminal observation conflicts with recorded fills")
            return
        if observation.status not in {"canceled", "expired"}:
            raise CopyTradeRiskError("partially filled terminal observation must be canceled or expired")
        if str(submitted["event_kind"]) != "submission_accepted" or not prior_fills:
            raise CopyTradeRiskError("partial terminal observation lacks accepted fill history")
        if any(item.get("terminal_fill") is True for item in prior_fills):
            raise CopyTradeRiskError("terminally filled reservation cannot accept a terminal close observation")
        last_cumulative = max(
            float(item.get("cumulative_filled_qty", 0) or 0)
            for item in prior_fills
        )
        if (
            observed_cumulative >= reservation.order_quantity - tolerance
            or abs(observed_cumulative - last_cumulative) > tolerance
        ):
            raise CopyTradeRiskError(
                "partial terminal executed quantity does not match the recorded fills"
            )

    def claim_terminal_projection(
        self,
        reservation: PreTradeReservation,
        *,
        observation: OrderExecutionObservation,
        submission_ref: str,
        venue_event: ExecutionVenueEventRecord,
        reconciliation: ExecutionReconciliationRecord,
        actor: str,
    ) -> str:
        claim_event_id = (
            f"{reservation.reservation_ref}:lifecycle_claim:terminal:"
            f"{observation.source_event_ref}"
        )
        self.validate_terminal_observation(
            reservation,
            observation,
            submission_ref=submission_ref,
            venue_event_ref=venue_event.venue_event_ref,
        )
        self._assert_terminal_claim_formal_semantics(
            reservation,
            observation=observation,
            submission_ref=submission_ref,
            venue_event=venue_event,
            reconciliation=reconciliation,
            actor=actor,
        )
        if not validate_execution_venue_event(venue_event).accepted:
            raise CopyTradeRiskError("terminal projection claim has invalid canonical venue event")
        if not validate_execution_reconciliation(reconciliation).accepted:
            raise CopyTradeRiskError("terminal projection claim has invalid canonical reconciliation")
        if venue_event.venue_event_ref not in set(reconciliation.event_refs):
            raise CopyTradeRiskError("terminal projection reconciliation omits the candidate event")
        tolerance = max(reservation.order_quantity, 1.0) * 1e-9
        expected_status = (
            "closed_no_fill"
            if observation.cumulative_filled_qty <= tolerance
            else "closed_partial_fill"
        )
        if reconciliation.status != expected_status or reconciliation.action_required:
            raise CopyTradeRiskError("terminal projection claim reconciliation is not safely closed")
        self._assert_no_other_pending_lifecycle_claim(
            reservation,
            candidate_event_id=claim_event_id,
        )
        payload = {
            "projection_kind": "terminal",
            "submission_ref": submission_ref,
            "source_event_ref": observation.source_event_ref,
            "actor": actor,
            "observation": asdict(observation),
            "venue_event": venue_event.to_dict(),
            "reconciliation": reconciliation.to_dict(),
            "expected_status": expected_status,
        }
        try:
            existing_claim = self.lifecycle_projection_claim(claim_event_id)
        except CopyTradeRiskError:
            existing_claim = None
        if existing_claim is not None:
            if not self._same_lifecycle_claim_semantics(existing_claim["payload"], payload):
                raise CopyTradeRiskError("terminal projection claim identity collision")
            return claim_event_id
        actual = self._record_transition(
            reservation,
            event_kind="formal_lifecycle_claim",
            event_suffix="lifecycle_claim:terminal:" + observation.source_event_ref,
            payload=payload,
            occurred_at_utc=observation.observed_at_utc,
        )
        if actual != claim_event_id:
            raise CopyTradeRiskError("terminal projection claim identity mismatch")
        return actual

    def lifecycle_projection_claim(self, claim_event_id: str) -> dict[str, Any]:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT * FROM ct_risk_events WHERE event_id=? "
                "AND event_kind='formal_lifecycle_claim'",
                (str(claim_event_id),),
            ).fetchone()
        if row is None:
            raise CopyTradeRiskError("unknown lifecycle projection claim")
        return {
            "claim_event_id": str(row["event_id"]),
            "reservation_ref": str(row["reservation_ref"]),
            "payload": self._payload(row),
        }

    def _resolve_terminal_proof(
        self,
        reservation: PreTradeReservation,
        *,
        reconciliation_ref: str,
        venue_event_ref: str,
        observation: OrderExecutionObservation,
        expected_reconciliation_status: str,
    ) -> tuple[ExecutionReconciliationRecord, ExecutionVenueEventRecord, dict[str, str]]:
        self._validate_terminal_observation(reservation, observation)
        if self._reconciliation_store is None or self._venue_event_store is None:
            raise CopyTradeRiskError("terminal release requires bound persisted formal proof stores")
        try:
            reconciliation = self._reconciliation_store.reconciliation(reconciliation_ref)
            venue_event = self._venue_event_store.event(venue_event_ref)
        except (KeyError, TypeError, ValueError) as exc:
            raise CopyTradeRiskError("terminal release formal proof does not resolve") from exc
        if not isinstance(reconciliation, ExecutionReconciliationRecord):
            raise CopyTradeRiskError("resolved terminal reconciliation has the wrong type")
        if not isinstance(venue_event, ExecutionVenueEventRecord):
            raise CopyTradeRiskError("resolved terminal venue event has the wrong type")
        reconciliation_decision = validate_execution_reconciliation(reconciliation)
        if not reconciliation_decision.accepted:
            raise CopyTradeRiskError("resolved terminal reconciliation is not canonical v2 evidence")
        event_decision = validate_execution_venue_event(venue_event)
        if not event_decision.accepted:
            raise CopyTradeRiskError("resolved terminal venue event is not canonical v2 evidence")
        binding = self.submission_binding_for_reservation(reservation.reservation_ref)
        if binding is None or not binding.get("submission_ref"):
            raise CopyTradeRiskError("terminal release lacks a formal submission binding")
        if reconciliation.reconciliation_ref != reconciliation_ref:
            raise CopyTradeRiskError("terminal reconciliation identity mismatch")
        if reconciliation.status != expected_reconciliation_status or reconciliation.action_required:
            raise CopyTradeRiskError("terminal reconciliation does not prove a closed order")
        if reconciliation.submission_ref != binding["submission_ref"]:
            raise CopyTradeRiskError("terminal reconciliation submission mismatch")
        if reconciliation.venue_order_ref != observation.order_id:
            raise CopyTradeRiskError("terminal reconciliation venue-order mismatch")
        if venue_event.venue_event_ref not in set(reconciliation.event_refs):
            raise CopyTradeRiskError("terminal reconciliation does not include the terminal venue event")
        if venue_event.submission_ref != binding["submission_ref"]:
            raise CopyTradeRiskError("terminal venue event submission mismatch")
        if venue_event.venue_order_ref != observation.order_id:
            raise CopyTradeRiskError("terminal venue event order mismatch")
        if venue_event.client_order_ref != observation.client_order_id:
            raise CopyTradeRiskError("terminal venue event client identity mismatch")
        if venue_event.event_kind != observation.status or venue_event.status != observation.status:
            raise CopyTradeRiskError("terminal venue event status mismatch")
        if venue_event.raw_event_hash != observation.raw_event_hash:
            raise CopyTradeRiskError("terminal venue event raw digest mismatch")
        evidence = set(venue_event.evidence_refs)
        if observation.source_event_ref not in evidence or observation.raw_event_hash not in evidence:
            raise CopyTradeRiskError("terminal venue event lacks source-bound evidence refs")
        if binding["venue_order_ref"] and binding["venue_order_ref"] != observation.order_id:
            raise CopyTradeRiskError("terminal order venue identity does not match the submission")
        return reconciliation, venue_event, binding

    def reconcile_no_effect(
        self,
        reservation: PreTradeReservation,
        *,
        reconciliation_ref: str,
        venue_event_ref: str,
        observation: OrderExecutionObservation | None = None,
        projection_claim_event_id: str | None = None,
        actor: str = "binance_execution_reconciler",
        _finalize_token: object | None = None,
    ) -> str:
        if projection_claim_event_id and _finalize_token is not self.__lifecycle_finalize_token:
            if observation is None:
                raise CopyTradeRiskError(
                    "no-effect reconciliation requires a source-bound terminal observation"
                )
            claim = self.lifecycle_projection_claim(projection_claim_event_id)
            payload = claim["payload"]
            if (
                payload.get("projection_kind") != "terminal"
                or payload.get("expected_status") != "closed_no_fill"
                or payload.get("observation") != asdict(observation)
                or (payload.get("venue_event") or {}).get("venue_event_ref") != venue_event_ref
                or (payload.get("reconciliation") or {}).get("reconciliation_ref")
                != reconciliation_ref
                or payload.get("actor") != actor
            ):
                raise CopyTradeRiskError("terminal finalization call differs from its sealed claim")
            return self.finalize_lifecycle_projection_claim(
                reservation,
                claim_event_id=projection_claim_event_id,
            )
        if not projection_claim_event_id and not self._allow_unsealed_test_transitions:
            raise CopyTradeRiskError(
                "terminal transition requires a sealed lifecycle projection claim"
            )
        if observation is None:
            raise CopyTradeRiskError("no-effect reconciliation requires a source-bound terminal observation")
        if observation.status not in {"canceled", "expired", "rejected"}:
            raise CopyTradeRiskError("no-effect reconciliation requires a terminal no-fill status")
        tolerance = max(reservation.order_quantity, 1.0) * 1e-9
        if observation.cumulative_filled_qty > tolerance:
            raise CopyTradeRiskError("no-effect reconciliation cannot release an order with fills")
        self._resolve_terminal_proof(
            reservation,
            reconciliation_ref=reconciliation_ref,
            venue_event_ref=venue_event_ref,
            observation=observation,
            expected_reconciliation_status="closed_no_fill",
        )
        return self._record_transition(
            reservation,
            event_kind="reconciled_no_effect",
            event_suffix="reconciled_no_effect:" + observation.source_event_ref,
            payload={
                "reconciliation_ref": reconciliation_ref,
                "venue_event_ref": venue_event_ref,
                "status": observation.status,
                "venue_order_ref": observation.order_id,
                "source_event_ref": observation.source_event_ref,
                "raw_event_hash": observation.raw_event_hash,
                "requested_qty": observation.requested_qty,
                "cumulative_filled_qty": observation.cumulative_filled_qty,
                "projection_claim_event_id": str(projection_claim_event_id or ""),
                "actor": str(actor or ""),
            },
            occurred_at_utc=observation.observed_at_utc,
        )

    def reconcile_partial_terminal(
        self,
        reservation: PreTradeReservation,
        *,
        reconciliation_ref: str,
        venue_event_ref: str,
        observation: OrderExecutionObservation,
        projection_claim_event_id: str | None = None,
        actor: str = "binance_execution_reconciler",
        _finalize_token: object | None = None,
    ) -> str:
        if projection_claim_event_id and _finalize_token is not self.__lifecycle_finalize_token:
            claim = self.lifecycle_projection_claim(projection_claim_event_id)
            payload = claim["payload"]
            if (
                payload.get("projection_kind") != "terminal"
                or payload.get("expected_status") != "closed_partial_fill"
                or payload.get("observation") != asdict(observation)
                or (payload.get("venue_event") or {}).get("venue_event_ref") != venue_event_ref
                or (payload.get("reconciliation") or {}).get("reconciliation_ref")
                != reconciliation_ref
                or payload.get("actor") != actor
            ):
                raise CopyTradeRiskError("terminal finalization call differs from its sealed claim")
            return self.finalize_lifecycle_projection_claim(
                reservation,
                claim_event_id=projection_claim_event_id,
            )
        if not projection_claim_event_id and not self._allow_unsealed_test_transitions:
            raise CopyTradeRiskError(
                "terminal transition requires a sealed lifecycle projection claim"
            )
        if observation.status not in {"canceled", "expired"}:
            raise CopyTradeRiskError("partial terminal requires canceled or expired status")
        _, _, binding = self._resolve_terminal_proof(
            reservation,
            reconciliation_ref=reconciliation_ref,
            venue_event_ref=venue_event_ref,
            observation=observation,
            expected_reconciliation_status="closed_partial_fill",
        )
        if binding is None or binding["state"] != "submission_accepted":
            raise CopyTradeRiskError("partial terminal lacks an accepted submission binding")
        if binding["venue_order_ref"] != observation.order_id:
            raise CopyTradeRiskError("partial terminal venue identity does not match the submission")
        return self._record_transition(
            reservation,
            event_kind="reconciled_partial_terminal",
            event_suffix="reconciled_partial_terminal:" + observation.source_event_ref,
            payload={
                "reconciliation_ref": reconciliation_ref,
                "venue_event_ref": venue_event_ref,
                "status": observation.status,
                "venue_order_ref": observation.order_id,
                "source_event_ref": observation.source_event_ref,
                "raw_event_hash": observation.raw_event_hash,
                "requested_qty": observation.requested_qty,
                "cumulative_filled_qty": observation.cumulative_filled_qty,
                "projection_claim_event_id": str(projection_claim_event_id or ""),
                "actor": str(actor or ""),
            },
            occurred_at_utc=observation.observed_at_utc,
        )

    def finalize_lifecycle_projection_claim(
        self,
        reservation: PreTradeReservation,
        *,
        claim_event_id: str,
    ) -> str:
        claim = self.lifecycle_projection_claim(claim_event_id)
        if claim["reservation_ref"] != reservation.reservation_ref:
            raise CopyTradeRiskError("lifecycle projection claim reservation mismatch")
        payload = claim["payload"]
        event_payload = payload.get("venue_event")
        reconciliation_payload = payload.get("reconciliation")
        if not isinstance(event_payload, dict) or not isinstance(reconciliation_payload, dict):
            raise CopyTradeRiskError("lifecycle projection claim lacks formal record payloads")
        if self._venue_event_store is None or self._reconciliation_store is None:
            raise CopyTradeRiskError("lifecycle projection finalization lacks formal proof stores")
        event_ref = str(event_payload.get("venue_event_ref") or "")
        reconciliation_ref = str(reconciliation_payload.get("reconciliation_ref") or "")
        try:
            persisted_event = self._venue_event_store.event(event_ref)
            persisted_reconciliation = self._reconciliation_store.reconciliation(reconciliation_ref)
        except (KeyError, TypeError, ValueError) as exc:
            raise CopyTradeRiskError("lifecycle projection formal proof does not resolve") from exc
        if persisted_event.to_dict() != event_payload:
            raise CopyTradeRiskError("lifecycle projection venue event differs from its sealed claim")
        if persisted_reconciliation.to_dict() != reconciliation_payload:
            raise CopyTradeRiskError("lifecycle projection reconciliation differs from its sealed claim")
        if not validate_execution_venue_event(persisted_event).accepted:
            raise CopyTradeRiskError("lifecycle projection venue event is not canonical")
        if not validate_execution_reconciliation(persisted_reconciliation).accepted:
            raise CopyTradeRiskError("lifecycle projection reconciliation is not canonical")
        if event_ref not in set(persisted_reconciliation.event_refs):
            raise CopyTradeRiskError("lifecycle projection reconciliation omits its venue event")

        projection_kind = str(payload.get("projection_kind") or "")
        actor = str(payload.get("actor") or "binance_execution_reconciler")
        if projection_kind == "fill":
            report_payload = payload.get("report")
            if not isinstance(report_payload, dict):
                raise CopyTradeRiskError("fill projection claim lacks execution report")
            report = ExecutionReport(**report_payload)
            binding = self.submission_binding_for_reservation(reservation.reservation_ref)
            submission_ref = str(payload.get("submission_ref") or "")
            if binding is None or binding["state"] != "submission_accepted":
                self.mark_submitted(
                    reservation,
                    submission_ref=submission_ref,
                    venue_order_ref=report.order_id,
                    ack_ref=report.source_event_ref,
                    ack_accepted_at_utc=report.timestamp_utc,
                    reconciliation_ref=reconciliation_ref,
                    ack_status=report.status,
                    actor=actor,
                    projection_kind="fill_recovered",
                )
            elif (
                binding["submission_ref"] != submission_ref
                or binding["venue_order_ref"] != report.order_id
            ):
                raise CopyTradeRiskError("fill projection claim conflicts with submission binding")
            return self.record_fill(
                reservation,
                report=report,
                submission_ref=submission_ref,
                venue_event_ref=event_ref,
                normalized_cost_usdt=payload.get("normalized_cost_usdt"),
                cost_conversion_ref=payload.get("cost_conversion_ref"),
                realized_pnl_delta=float(payload.get("realized_pnl_delta", 0) or 0),
                realized_pnl_complete=payload.get("realized_pnl_complete") is True,
                reconciliation_ref=reconciliation_ref,
                projection_claim_event_id=claim_event_id,
                actor=actor,
                _finalize_token=self.__lifecycle_finalize_token,
            )
        if projection_kind == "terminal":
            observation_payload = payload.get("observation")
            if not isinstance(observation_payload, dict):
                raise CopyTradeRiskError("terminal projection claim lacks order observation")
            observation = OrderExecutionObservation(**observation_payload)
            if payload.get("expected_status") == "closed_no_fill":
                return self.reconcile_no_effect(
                    reservation,
                    reconciliation_ref=reconciliation_ref,
                    venue_event_ref=event_ref,
                    observation=observation,
                    projection_claim_event_id=claim_event_id,
                    actor=actor,
                    _finalize_token=self.__lifecycle_finalize_token,
                )
            if payload.get("expected_status") == "closed_partial_fill":
                return self.reconcile_partial_terminal(
                    reservation,
                    reconciliation_ref=reconciliation_ref,
                    venue_event_ref=event_ref,
                    observation=observation,
                    projection_claim_event_id=claim_event_id,
                    actor=actor,
                    _finalize_token=self.__lifecycle_finalize_token,
                )
        raise CopyTradeRiskError("lifecycle projection claim has unsupported projection kind")

    def abort_pre_submit(
        self,
        *,
        follower_id: str,
        account_binding_ref: str,
        signal_id: str,
        reason_ref: str,
    ) -> bool:
        """Release a reservation only when no venue-submission state exists."""

        with self._conn() as conn:
            row = conn.execute(
                "SELECT payload_json FROM ct_risk_events "
                "WHERE follower_id=? AND account_binding_ref=? AND signal_id=? "
                "AND event_kind='pretrade_reserved'",
                (follower_id, account_binding_ref, signal_id),
            ).fetchone()
            transition_kinds = {
                str(item["event_kind"])
                for item in conn.execute(
                    "SELECT event_kind FROM ct_risk_events WHERE follower_id=? "
                    "AND account_binding_ref=? AND signal_id=?",
                    (follower_id, account_binding_ref, signal_id),
                ).fetchall()
            }
        if row is None:
            return False
        if transition_kinds & {"definitive_reject", "venue_reject", "reconciled_no_effect"}:
            return False
        if transition_kinds & {
            "order_request_started",
            "submission_accepted",
            "submission_unknown",
            "fill",
        }:
            return False
        payload = json.loads(row["payload_json"])
        reservation_payload = payload.get("reservation")
        if not isinstance(reservation_payload, dict):
            raise CopyTradeRiskError("persisted reservation payload is malformed")
        reservation = PreTradeReservation(**reservation_payload)
        self.mark_definitive_reject(reservation, reason_ref=reason_ref)
        return True

    def state(self, follower_id: str, account_binding_ref: str, *, day: str | None = None) -> FollowerRiskState:
        target_day = day or _now().date().isoformat()
        with self._conn() as conn:
            rows = self._rows(conn, follower_id)
        return self._derive_state(
            rows,
            follower_id=follower_id,
            account_binding_ref=account_binding_ref,
            day=target_day,
        )

    def has_open_reservations(self, follower_id: str, account_binding_ref: str) -> bool:
        """Return whether venue-effect uncertainty still requires account controls."""

        with self._conn() as conn:
            rows = self._rows(conn, follower_id)
        if any(str(row["account_binding_ref"]) != account_binding_ref for row in rows):
            raise CopyTradeRiskError("follower risk history account binding changed")
        return bool(self._active_reservations(rows))

    def reservation_for_submission(self, submission_ref: str) -> PreTradeReservation:
        """Resolve an accepted formal submission to its exact risk reservation."""

        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM ct_risk_events WHERE event_kind IN ('submission_accepted','submission_unknown') "
                "ORDER BY seq",
            ).fetchall()
            matches = [row for row in rows if self._payload(row).get("submission_ref") == submission_ref]
            reservation_refs = {
                str(row["reservation_ref"] or "") for row in matches if str(row["reservation_ref"] or "")
            }
            if len(reservation_refs) != 1:
                raise CopyTradeRiskError("formal submission does not resolve to exactly one risk reservation")
            reservation_row = conn.execute(
                "SELECT * FROM ct_risk_events WHERE reservation_ref=? AND event_kind='pretrade_reserved'",
                (next(iter(reservation_refs)),),
            ).fetchone()
        if reservation_row is None:
            raise CopyTradeRiskError("formal submission risk reservation is missing")
        reservation_payload = self._payload(reservation_row).get("reservation")
        if not isinstance(reservation_payload, dict):
            raise CopyTradeRiskError("persisted reservation payload is malformed")
        return PreTradeReservation(**reservation_payload)

    def reservation_by_risk_check_ref(self, risk_check_ref: str) -> PreTradeReservation:
        """Resolve one exact risk gate from an HMAC-validated ledger snapshot."""

        ref = str(risk_check_ref or "").strip()
        if not ref.startswith("copy_risk_check_"):
            raise CopyTradeRiskError("canonical copy-trade risk check ref is required")
        rows = self._validated_rows_snapshot()
        matches: list[PreTradeReservation] = []
        for row in rows:
            if str(row["event_kind"] or "") != "pretrade_reserved":
                continue
            payload = self._payload(row).get("reservation")
            if not isinstance(payload, dict):
                raise CopyTradeRiskError("persisted reservation payload is malformed")
            reservation = PreTradeReservation(**payload)
            if reservation.risk_check_ref == ref:
                matches.append(reservation)
        identities = {item.reservation_ref for item in matches}
        if len(matches) != 1 or len(identities) != 1:
            raise CopyTradeRiskError("risk check ref is missing or ambiguous")
        return matches[0]

    def verified_formal_submission_bindings(self) -> tuple[FormalSubmissionRiskBinding, ...]:
        """Resolve every formal submission through one HMAC-validated ledger snapshot."""

        rows = self._validated_rows_snapshot()
        reservation_rows: dict[str, sqlite3.Row] = {}
        request_rows: dict[str, list[sqlite3.Row]] = {}
        completion_rows: dict[str, list[sqlite3.Row]] = {}
        outcomes_by_submission: dict[str, list[sqlite3.Row]] = {}
        outcome_kinds = {
            "submission_accepted",
            "submission_unknown",
            "venue_reject",
            "definitive_reject",
        }
        for row in rows:
            kind = str(row["event_kind"])
            reservation_ref = str(row["reservation_ref"] or "")
            if kind == "pretrade_reserved":
                if not reservation_ref or reservation_ref in reservation_rows:
                    raise CopyTradeRiskError("risk ledger has duplicate reservation authority")
                reservation_rows[reservation_ref] = row
            elif kind == "order_request_started" and reservation_ref:
                request_rows.setdefault(reservation_ref, []).append(row)
            elif kind == "formal_projection_completed":
                binding_event_id = str(self._payload(row).get("binding_event_id") or "")
                if not binding_event_id:
                    raise CopyTradeRiskError("formal projection completion lacks binding event identity")
                completion_rows.setdefault(binding_event_id, []).append(row)
            elif kind in outcome_kinds:
                submission_ref = str(self._payload(row).get("submission_ref") or "").strip()
                if submission_ref:
                    outcomes_by_submission.setdefault(submission_ref, []).append(row)

        bindings: list[tuple[int, FormalSubmissionRiskBinding]] = []
        for submission_ref, outcome_rows in outcomes_by_submission.items():
            reservation_refs = {
                str(row["reservation_ref"] or "").strip() for row in outcome_rows
            }
            if "" in reservation_refs or len(reservation_refs) != 1:
                raise CopyTradeRiskError(
                    "formal submission maps to multiple or missing risk reservations"
                )
            reservation_ref = next(iter(reservation_refs))
            reservation_row = reservation_rows.get(reservation_ref)
            if reservation_row is None:
                raise CopyTradeRiskError("formal submission risk reservation is missing")
            raw_reservation = self._payload(reservation_row).get("reservation")
            if not isinstance(raw_reservation, dict):
                raise CopyTradeRiskError("persisted reservation payload is malformed")
            try:
                reservation = PreTradeReservation(**raw_reservation)
            except (TypeError, ValueError) as exc:
                raise CopyTradeRiskError("persisted reservation payload is malformed") from exc
            if (
                reservation.reservation_ref != reservation_ref
                or reservation.follower_id != str(reservation_row["follower_id"])
                or reservation.account_binding_ref != str(reservation_row["account_binding_ref"])
                or reservation.signal_id != str(reservation_row["signal_id"] or "")
            ):
                raise CopyTradeRiskError("formal submission reservation columns differ from payload")

            latest = max(outcome_rows, key=lambda row: int(row["seq"]))
            requests = request_rows.get(reservation_ref, [])
            if not requests and str(latest["event_kind"]) != "definitive_reject":
                raise CopyTradeRiskError("formal submission lacks its order-request boundary")
            if requests:
                request_payloads = [self._payload(row) for row in requests]
                if any(payload != request_payloads[0] for payload in request_payloads[1:]):
                    raise CopyTradeRiskError(
                        "formal submission has conflicting order-request contexts"
                    )
                order_context = {
                    str(key): str(value or "") for key, value in request_payloads[-1].items()
                }
                if order_context.get("client_order_id") != reservation.client_order_id:
                    raise CopyTradeRiskError("formal submission client order identity changed")
            else:
                order_context = {}
            for row in outcome_rows:
                if (
                    str(row["follower_id"]) != reservation.follower_id
                    or str(row["account_binding_ref"]) != reservation.account_binding_ref
                    or str(row["signal_id"] or "") != reservation.signal_id
                ):
                    raise CopyTradeRiskError("formal submission outcome changed risk ownership")
            payload = self._payload(latest)
            binding_event_id = str(latest["event_id"])
            completions = completion_rows.get(binding_event_id, [])
            completion_event_id = ""
            initial_reconciliation_ref = ""
            if completions:
                completion_payloads = [self._payload(row) for row in completions]
                if any(item != completion_payloads[0] for item in completion_payloads[1:]):
                    raise CopyTradeRiskError("formal projection completion is ambiguous")
                completion = completion_payloads[-1]
                if str(completion.get("submission_ref") or "") != submission_ref:
                    raise CopyTradeRiskError("formal projection completion changed submission")
                initial_reconciliation_ref = str(
                    completion.get("reconciliation_ref") or ""
                ).strip()
                if not initial_reconciliation_ref:
                    raise CopyTradeRiskError("formal projection completion lacks reconciliation")
                completion_event_id = str(completions[-1]["event_id"])
            bindings.append(
                (
                    int(latest["seq"]),
                    FormalSubmissionRiskBinding(
                        submission_ref=submission_ref,
                        reservation_ref=reservation_ref,
                        binding_event_id=binding_event_id,
                        outcome_state=str(latest["event_kind"]),
                        follower_id=reservation.follower_id,
                        account_binding_ref=reservation.account_binding_ref,
                        signal_id=reservation.signal_id,
                        risk_check_ref=reservation.risk_check_ref,
                        snapshot_ref=reservation.snapshot_ref,
                        client_order_id=reservation.client_order_id,
                        venue_order_ref=str(payload.get("venue_order_ref") or ""),
                        ack_ref=str(payload.get("ack_ref") or ""),
                        reason_ref=str(payload.get("reason_ref") or ""),
                        order_request_context=order_context,
                        projection_completed_event_id=completion_event_id,
                        initial_reconciliation_ref=initial_reconciliation_ref,
                    ),
                )
            )
        return tuple(binding for _seq, binding in sorted(bindings, key=lambda item: item[0]))

    def verified_formal_submission_binding(
        self,
        submission_ref: str,
    ) -> FormalSubmissionRiskBinding | None:
        target = str(submission_ref or "").strip()
        if not target:
            return None
        matches = [
            binding
            for binding in self.verified_formal_submission_bindings()
            if binding.submission_ref == target
        ]
        if len(matches) > 1:
            raise CopyTradeRiskError("formal submission owner binding is ambiguous")
        return matches[0] if matches else None

    def submission_binding_for_reservation(self, reservation_ref: str) -> dict[str, str] | None:
        """Return the accepted venue/submission identity for reconciliation polling."""

        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM ct_risk_events WHERE reservation_ref=? "
                "AND event_kind IN ('submission_accepted','submission_unknown','venue_reject','definitive_reject') "
                "ORDER BY seq",
                (reservation_ref,),
            ).fetchall()
            rows = [row for row in rows if str(self._payload(row).get("submission_ref") or "").strip()]
        if not rows:
            with self._conn() as conn:
                started = conn.execute(
                    "SELECT * FROM ct_risk_events WHERE reservation_ref=? "
                    "AND event_kind='order_request_started' ORDER BY seq DESC LIMIT 1",
                    (reservation_ref,),
                ).fetchone()
            if started is None:
                return None
            return {
                "submission_ref": "",
                "venue_order_ref": "",
                "ack_ref": "",
                "reason_ref": "",
                "state": "order_request_started",
            }
        payload = self._payload(rows[-1])
        if not str(payload.get("submission_ref") or "").strip():
            raise CopyTradeRiskError("risk submission binding lacks formal submission identity")
        return {
            "submission_ref": str(payload["submission_ref"]),
            "venue_order_ref": str(payload.get("venue_order_ref") or ""),
            "ack_ref": str(payload.get("ack_ref") or ""),
            "reason_ref": str(payload.get("reason_ref") or ""),
            "state": str(rows[-1]["event_kind"]),
            "binding_event_id": str(rows[-1]["event_id"]),
        }

    def order_request_context(self, reservation_ref: str) -> dict[str, str] | None:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT * FROM ct_risk_events WHERE reservation_ref=? "
                "AND event_kind='order_request_started' ORDER BY seq DESC LIMIT 1",
                (reservation_ref,),
            ).fetchone()
        if row is None:
            return None
        payload = self._payload(row)
        return {str(key): str(value or "") for key, value in payload.items()}

    def formal_projection_attempts(
        self,
        *,
        follower_id: str | None = None,
        account_binding_ref: str | None = None,
    ) -> tuple[dict[str, Any], ...]:
        """Return the latest sealed formal-projection outbox item per attempt.

        Completed entries are intentionally returned too. Replaying `_ensure`
        detects and repairs JSONL loss after a later restart.
        """

        with self._conn() as conn:
            rows = conn.execute("SELECT * FROM ct_risk_events ORDER BY seq").fetchall()
        reservation_rows = {
            str(row["reservation_ref"]): row
            for row in rows
            if row["event_kind"] == "pretrade_reserved"
        }
        outcome_candidates: dict[str, sqlite3.Row] = {}
        relevant = {
            "order_request_started",
            "submission_accepted",
            "submission_unknown",
            "venue_reject",
            "definitive_reject",
        }
        for row in rows:
            ref = str(row["reservation_ref"] or "")
            if not ref or row["event_kind"] not in relevant:
                continue
            if follower_id is not None and row["follower_id"] != follower_id:
                continue
            if account_binding_ref is not None and row["account_binding_ref"] != account_binding_ref:
                continue
            payload = self._payload(row)
            if row["event_kind"] == "definitive_reject" and not str(
                payload.get("submission_ref") or ""
            ).strip():
                continue
            if row["event_kind"] == "submission_accepted" and payload.get(
                "projection_kind"
            ) == "fill_recovered":
                continue
            outcome_candidates[ref] = row
        completed_by_binding = {
            str(self._payload(row).get("binding_event_id") or ""): self._payload(row)
            for row in rows
            if row["event_kind"] == "formal_projection_completed"
        }
        finalized_by_claim = {
            str(self._payload(row).get("projection_claim_event_id") or ""): self._payload(row)
            for row in rows
            if row["event_kind"] in {"fill", "reconciled_no_effect", "reconciled_partial_terminal"}
            and str(self._payload(row).get("projection_claim_event_id") or "")
        }
        lifecycle_rows = [
            row
            for row in rows
            if row["event_kind"] == "formal_lifecycle_claim"
            and (follower_id is None or row["follower_id"] == follower_id)
            and (account_binding_ref is None or row["account_binding_ref"] == account_binding_ref)
        ]
        candidate_rows = sorted(
            (*outcome_candidates.values(), *lifecycle_rows),
            key=lambda row: int(row["seq"]),
        )
        attempts: list[dict[str, Any]] = []
        for row in candidate_rows:
            ref = str(row["reservation_ref"] or "")
            reservation_row = reservation_rows.get(ref)
            if reservation_row is None:
                raise CopyTradeRiskError("formal projection outbox lacks its reservation")
            reservation_payload = self._payload(reservation_row).get("reservation")
            if not isinstance(reservation_payload, dict):
                raise CopyTradeRiskError("persisted reservation payload is malformed")
            binding_event_id = str(row["event_id"])
            attempts.append(
                {
                    "reservation": PreTradeReservation(**reservation_payload),
                    "state": str(row["event_kind"]),
                    "binding_event_id": binding_event_id,
                    "payload": self._payload(row),
                    "completed": (
                        finalized_by_claim.get(binding_event_id)
                        if str(row["event_kind"]) == "formal_lifecycle_claim"
                        else completed_by_binding.get(binding_event_id)
                    ),
                }
            )
        return tuple(attempts)

    def recover_pre_submit_orphans(self, *, min_age_s: float = 60.0) -> int:
        """Release only prior-process reservations that never crossed order POST."""

        if min_age_s < 0:
            raise ValueError("min_age_s must be nonnegative")
        recovered = 0
        for reservation in self.unresolved_reservations():
            if not reservation.attempt_instance_id:
                continue
            if reservation.attempt_instance_id == self._instance_id:
                continue
            try:
                age_s = (_now() - _parse_timestamp(reservation.created_at_utc).astimezone(UTC)).total_seconds()
            except ValueError:
                continue
            if age_s < min_age_s:
                continue
            with self._conn() as conn:
                kinds = {
                    str(row["event_kind"])
                    for row in conn.execute(
                        "SELECT event_kind FROM ct_risk_events WHERE reservation_ref=?",
                        (reservation.reservation_ref,),
                    ).fetchall()
                }
            if kinds & {
                "order_request_started",
                "submission_accepted",
                "submission_unknown",
                "fill",
                "reconciled_no_effect",
                "reconciled_partial_terminal",
                "definitive_reject",
                "venue_reject",
            }:
                continue
            self.mark_definitive_reject(
                reservation,
                reason_ref="pre_submit_process_orphan_" + content_hash(
                    {
                        "reservation_ref": reservation.reservation_ref,
                        "attempt_instance_id": reservation.attempt_instance_id,
                    }
                ),
            )
            recovered += 1
        return recovered

    def unresolved_reservations(
        self,
        *,
        follower_id: str | None = None,
        account_binding_ref: str | None = None,
    ) -> tuple[PreTradeReservation, ...]:
        """List every reservation that still needs venue reconciliation."""

        with self._conn() as conn:
            rows = conn.execute("SELECT * FROM ct_risk_events ORDER BY seq").fetchall()
        active_refs = set(self._active_reservations(rows))
        reservations: list[PreTradeReservation] = []
        for row in rows:
            if row["event_kind"] != "pretrade_reserved" or row["reservation_ref"] not in active_refs:
                continue
            if follower_id is not None and row["follower_id"] != follower_id:
                continue
            if account_binding_ref is not None and row["account_binding_ref"] != account_binding_ref:
                continue
            payload = self._payload(row).get("reservation")
            if not isinstance(payload, dict):
                raise CopyTradeRiskError("persisted reservation payload is malformed")
            reservations.append(PreTradeReservation(**payload))
        return tuple(reservations)

    def reservation_lifecycles(self) -> tuple[dict[str, Any], ...]:
        """Return each typed reservation with its complete sealed event-kind set."""

        with self._conn() as conn:
            rows = conn.execute("SELECT * FROM ct_risk_events ORDER BY seq").fetchall()
        grouped: dict[str, list[sqlite3.Row]] = {}
        for row in rows:
            ref = str(row["reservation_ref"] or "").strip()
            if ref:
                grouped.setdefault(ref, []).append(row)
        lifecycles: list[dict[str, Any]] = []
        for reservation_ref, group in grouped.items():
            reserved_rows = [row for row in group if row["event_kind"] == "pretrade_reserved"]
            if len(reserved_rows) != 1:
                raise CopyTradeRiskError(
                    "risk reservation lifecycle does not contain exactly one pretrade reservation"
                )
            payload = self._payload(reserved_rows[0]).get("reservation")
            if not isinstance(payload, dict):
                raise CopyTradeRiskError("persisted reservation payload is malformed")
            reservation = PreTradeReservation(**payload)
            if reservation.reservation_ref != reservation_ref:
                raise CopyTradeRiskError("persisted reservation lifecycle identity mismatch")
            lifecycles.append(
                {
                    "reservation": reservation,
                    "event_kinds": tuple(str(row["event_kind"]) for row in group),
                    "last_seq": max(int(row["seq"]) for row in group),
                }
            )
        return tuple(sorted(lifecycles, key=lambda item: int(item["last_seq"])))

    def fill_economics_for_followers(
        self,
        follower_ids: Iterator[str],
        *,
        signal_id: str | None = None,
        follower_id: str | None = None,
        limit: int = 200,
    ) -> tuple[FollowerFillEconomics, ...]:
        """Read owner-authorized fill economics from one validated HMAC snapshot."""

        if type(limit) is not int or not 1 <= limit <= 200:
            raise ValueError("fill economics limit must be an exact integer in [1, 200]")
        allowed = {str(value or "").strip() for value in follower_ids}
        allowed.discard("")
        requested_follower = str(follower_id or "").strip()
        requested_signal = str(signal_id or "").strip()
        if requested_follower and requested_follower not in allowed:
            return ()
        if not allowed:
            return ()

        rows = self._validated_rows_snapshot()
        reservations: dict[str, PreTradeReservation] = {}
        for row in rows:
            if str(row["event_kind"]) != "pretrade_reserved":
                continue
            payload = self._payload(row).get("reservation")
            if not isinstance(payload, dict):
                raise CopyTradeRiskError("persisted reservation payload is malformed")
            try:
                reservation = PreTradeReservation(**payload)
            except (TypeError, ValueError) as exc:
                raise CopyTradeRiskError("persisted reservation cannot be reconstructed") from exc
            ref = str(row["reservation_ref"] or "")
            if (
                not ref
                or ref in reservations
                or reservation.reservation_ref != ref
                or reservation.follower_id != str(row["follower_id"])
                or reservation.account_binding_ref != str(row["account_binding_ref"])
                or reservation.signal_id != str(row["signal_id"] or "")
            ):
                raise CopyTradeRiskError("persisted reservation authority is ambiguous")
            reservations[ref] = reservation

        def finite_number(value: Any, *, field_name: str) -> float:
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise CopyTradeRiskError(f"fill economics has invalid {field_name}")
            parsed = float(value)
            if not math.isfinite(parsed):
                raise CopyTradeRiskError(f"fill economics has non-finite {field_name}")
            return parsed

        records: list[FollowerFillEconomics] = []
        for row in reversed(rows):
            if str(row["event_kind"]) != "fill":
                continue
            row_follower = str(row["follower_id"])
            if row_follower not in allowed:
                continue
            if requested_follower and row_follower != requested_follower:
                continue
            row_signal = str(row["signal_id"] or "")
            if requested_signal and row_signal != requested_signal:
                continue
            reservation_ref = str(row["reservation_ref"] or "")
            reservation = reservations.get(reservation_ref)
            if reservation is None:
                raise CopyTradeRiskError("fill economics lacks its reservation authority")
            if (
                reservation.follower_id != row_follower
                or reservation.account_binding_ref != str(row["account_binding_ref"])
                or reservation.signal_id != row_signal
            ):
                raise CopyTradeRiskError("fill economics changed reservation ownership")
            payload = self._payload(row)
            filled_qty = finite_number(payload.get("filled_qty"), field_name="filled_qty")
            cumulative = finite_number(
                payload.get("cumulative_filled_qty"), field_name="cumulative_filled_qty"
            )
            notional = finite_number(
                payload.get("filled_notional_usdt"), field_name="filled_notional_usdt"
            )
            commission = finite_number(payload.get("commission"), field_name="commission")
            if filled_qty <= 0 or cumulative < filled_qty or notional <= 0 or commission < 0:
                raise CopyTradeRiskError("fill economics contains invalid quantities or costs")
            if payload.get("fill_price") is None:
                fill_price = notional / filled_qty
                fill_price_source = "derived_from_sealed_notional"
            else:
                fill_price = finite_number(payload.get("fill_price"), field_name="fill_price")
                fill_price_source = "venue_fill"
            if fill_price <= 0 or not math.isclose(
                abs(filled_qty * fill_price),
                notional,
                rel_tol=1e-9,
                abs_tol=max(notional, 1.0) * 1e-12,
            ):
                raise CopyTradeRiskError("fill price does not reproduce sealed fill notional")
            cost_complete = payload.get("cost_complete") is True
            normalized_raw = payload.get("normalized_cost_usdt")
            normalized_cost = (
                None
                if normalized_raw is None
                else finite_number(normalized_raw, field_name="normalized_cost_usdt")
            )
            conversion_ref = str(payload.get("cost_conversion_ref") or "").strip() or None
            if cost_complete != (normalized_cost is not None and conversion_ref is not None):
                raise CopyTradeRiskError("fill cost completeness conflicts with conversion evidence")
            if normalized_cost is not None and normalized_cost < 0:
                raise CopyTradeRiskError("fill normalized cost cannot be negative")
            realized_pnl = finite_number(
                payload.get("realized_pnl_delta", 0), field_name="realized_pnl_delta"
            )
            realized_complete = payload.get("realized_pnl_complete") is True
            occurred_at = str(payload.get("occurred_at_utc") or "")
            _parse_timestamp(occurred_at)
            source_ref = str(payload.get("source_event_ref") or "").strip()
            raw_hash = str(payload.get("raw_event_hash") or "").strip()
            submission_ref = str(payload.get("submission_ref") or "").strip()
            venue_event_ref = str(payload.get("venue_event_ref") or "").strip()
            reconciliation_ref = str(payload.get("reconciliation_ref") or "").strip()
            venue_order_ref = str(payload.get("venue_order_ref") or "").strip()
            client_order_ref = str(payload.get("client_order_id") or "").strip()
            commission_asset = str(payload.get("commission_asset") or "").strip()
            if not all(
                (
                    source_ref,
                    raw_hash,
                    submission_ref,
                    venue_event_ref,
                    reconciliation_ref,
                    venue_order_ref,
                    client_order_ref,
                    commission_asset,
                )
            ) or not raw_hash.startswith("sha256:"):
                raise CopyTradeRiskError("fill economics lacks exact lifecycle evidence")
            if client_order_ref != reservation.client_order_id:
                raise CopyTradeRiskError("fill economics client order differs from reservation")
            if self._venue_event_store is None or self._reconciliation_store is None:
                raise CopyTradeRiskError("fill economics lacks formal proof stores")
            for proof_store in (self._venue_event_store, self._reconciliation_store):
                refresh = getattr(proof_store, "refresh", None)
                if callable(refresh):
                    refresh()
            try:
                formal_event = self._venue_event_store.event(venue_event_ref)
                formal_reconciliation = self._reconciliation_store.reconciliation(
                    reconciliation_ref
                )
            except (KeyError, TypeError, ValueError) as exc:
                raise CopyTradeRiskError("fill economics formal proof does not resolve") from exc
            fill_status = (
                "filled" if payload.get("terminal_fill") is True else "partially_filled"
            )
            if (
                formal_event.submission_ref != submission_ref
                or formal_event.venue_event_ref != venue_event_ref
                or formal_event.event_kind != fill_status
                or formal_event.status != fill_status
                or formal_event.fill_ref != source_ref
                or formal_event.raw_event_hash != raw_hash
                or formal_event.venue_order_ref != venue_order_ref
                or formal_event.client_order_ref != client_order_ref
                or not formal_event.quantity_ref
                or not formal_event.price_ref
                or not formal_event.fee_ref
            ):
                raise CopyTradeRiskError("fill economics differs from its formal venue event")
            if (
                formal_reconciliation.reconciliation_ref != reconciliation_ref
                or formal_reconciliation.submission_ref != submission_ref
                or formal_reconciliation.venue_order_ref != venue_order_ref
                or venue_event_ref not in set(formal_reconciliation.event_refs)
                or not validate_execution_venue_event(formal_event).accepted
                or not validate_execution_reconciliation(formal_reconciliation).accepted
            ):
                raise CopyTradeRiskError("fill economics formal reconciliation is invalid")
            records.append(
                FollowerFillEconomics(
                    event_ref=str(row["event_id"]),
                    reservation_ref=reservation_ref,
                    submission_ref=submission_ref,
                    venue_event_ref=venue_event_ref,
                    reconciliation_ref=reconciliation_ref,
                    source_event_ref=source_ref,
                    raw_event_hash=raw_hash,
                    signal_ref=row_signal,
                    follower_ref=row_follower,
                    account_binding_ref=reservation.account_binding_ref,
                    symbol=reservation.symbol,
                    side=reservation.side,
                    venue_order_ref=venue_order_ref,
                    client_order_ref=client_order_ref,
                    fill_status=fill_status,
                    filled_qty=filled_qty,
                    cumulative_filled_qty=cumulative,
                    fill_price=fill_price,
                    fill_price_source=fill_price_source,
                    filled_notional_usdt=notional,
                    commission=commission,
                    commission_asset=commission_asset,
                    normalized_cost_usdt=normalized_cost,
                    cost_conversion_ref=conversion_ref,
                    cost_complete=cost_complete,
                    realized_pnl_delta=realized_pnl,
                    realized_pnl_complete=realized_complete,
                    fill_economics_complete=cost_complete and realized_complete,
                    occurred_at_utc=occurred_at,
                )
            )
            if len(records) >= limit:
                break
        return tuple(records)

    def events(self, follower_id: str | None = None) -> list[dict[str, Any]]:
        with self._conn() as conn:
            if follower_id is None:
                rows = conn.execute("SELECT * FROM ct_risk_events ORDER BY seq").fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM ct_risk_events WHERE follower_id=? ORDER BY seq", (follower_id,)
                ).fetchall()
        return [{**dict(row), "payload": self._payload(row)} for row in rows]


__all__ = [
    "CopyTradeRiskError",
    "FollowerFillEconomics",
    "FollowerRiskState",
    "FormalSubmissionRiskBinding",
    "PersistentFollowerRiskStateStore",
    "PreTradeReservation",
]
