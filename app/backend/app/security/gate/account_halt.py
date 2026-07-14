"""Durable account-scoped HALT epochs for live-order lease fencing.

The state transition to ``halting`` is committed before waiting for leases
that were issued under the previous epoch.  New live-order leases therefore
fail closed immediately, while the drain step waits for every pre-HALT lease
to be revoked before emergency cancellation/flattening may begin.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
import json
import math
import os
import sqlite3
import stat
import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal, Mapping

from ...cross_process_lock import (
    CrossProcessLockError,
    CrossProcessLockTimeout,
    HeldExclusiveFileLock,
    acquire_exclusive_fd,
)
from ...lineage.ids import content_hash

AccountHaltState = Literal["running", "halting", "halted"]


class AccountHaltError(RuntimeError):
    """The durable HALT barrier could not prove a safe transition."""


@dataclass(frozen=True)
class AccountHaltSnapshot:
    account_binding_ref: str
    owner_user_id: str
    state: AccountHaltState
    epoch: int
    execution_enabled: bool
    halt_ref: str | None
    halt_started_at_utc: str | None
    halted_at_utc: str | None
    flat_proof_ref: str | None
    updated_at_utc: str
    halt_action_name: str | None = None
    halt_close_positions: bool | None = None


@dataclass(frozen=True)
class AccountHaltBatch:
    snapshots: dict[str, AccountHaltSnapshot]
    drained_refs: tuple[str, ...]
    drain_failures: tuple[str, ...]


@dataclass(frozen=True)
class AccountHaltOperation:
    owner_user_id: str
    state: AccountHaltState
    epoch: int
    halt_ref: str
    action_name: str
    close_positions: bool
    updated_at_utc: str


@dataclass(frozen=True)
class AccountHaltAccountOperation:
    owner_user_id: str
    account_binding_ref: str
    state: AccountHaltState
    epoch: int
    halt_ref: str
    action_name: str
    close_positions: bool
    updated_at_utc: str


@dataclass(frozen=True)
class AccountHaltEvidence:
    """Owner-scoped durable evidence that one exact HALT operation was committed."""

    owner_user_id: str
    halt_ref: str
    owner_state: AccountHaltState
    owner_epoch: int
    account_binding_refs: tuple[str, ...]
    flat_proof_refs: tuple[str, ...]
    updated_at_utc: str


_INDIVIDUAL_HALT_ACTIONS: dict[str, bool] = {
    "copy_trade_unsubscribe": True,
    "copy_trade_startup_quarantine": False,
    "copy_trade_orphan_activation_quarantine": False,
    "copy_trade_activation_compensation": False,
}


class _HeldAccountFence:
    """One process-local lock plus one cross-process advisory file lock."""

    __slots__ = ("_fd", "_local_lock", "_os_lock", "_released")

    def __init__(
        self,
        local_lock: threading.Lock,
        fd: int,
        os_lock: HeldExclusiveFileLock,
    ) -> None:
        self._local_lock = local_lock
        self._fd = fd
        self._os_lock = os_lock
        self._released = False

    def release(self) -> None:
        if self._released:
            return
        self._released = True
        try:
            self._os_lock.release()
        finally:
            try:
                os.close(self._fd)
            finally:
                self._local_lock.release()


class PersistentAccountHaltBarrier:
    """SQLite HALT state plus lease-duration execution fences.

    ``running`` is the only state that permits a live-order lease.  A HALT
    raises the epoch and commits ``halting`` before draining old-epoch leases.
    ``halted`` is a separate, later transition that requires a caller-supplied
    flat/exposure proof reference.
    """

    def __init__(self, path: str | Path, *, drain_timeout_seconds: float = 30.0) -> None:
        self._path = Path(path)
        timeout = float(drain_timeout_seconds)
        if not math.isfinite(timeout) or timeout <= 0:
            raise ValueError("account HALT drain timeout must be positive and finite")
        self._drain_timeout_seconds = timeout
        self._lock_dir = self._path.parent / (self._path.name + ".locks")
        self._lock_map_guard = threading.Lock()
        self._local_locks: dict[str, threading.Lock] = {}
        self._emergency_action_journal: object | None = None
        self._prepare_private_storage()
        self._initialize()

    def bind_emergency_action_journal(self, journal: object) -> None:
        if not hasattr(journal, "validate_flat_proof_binding"):
            raise TypeError("emergency action journal lacks flat-proof validation")
        self._emergency_action_journal = journal

    def _validate_emergency_action_bindings(
        self,
        *,
        owner_user_id: str,
        owner_epoch: int,
        halt_ref: str,
        account_epochs: Mapping[str, int],
        results: Mapping[str, object],
    ) -> None:
        journal = self._emergency_action_journal
        if journal is None:
            return
        validator = getattr(journal, "validate_flat_proof_binding")
        for account_ref, account_epoch in account_epochs.items():
            raw_result = results.get(account_ref)
            if not isinstance(raw_result, dict):
                raise AccountHaltError("account HALT result lacks emergency action evidence")
            binding = raw_result.get("emergency_action_binding")
            flat_verification = {
                key: value
                for key, value in raw_result.items()
                if key != "emergency_action_binding"
            }
            try:
                validator(
                    binding,
                    owner_user_id=owner_user_id,
                    halt_ref=halt_ref,
                    owner_epoch=owner_epoch,
                    account_ref=account_ref,
                    account_epoch=account_epoch,
                    flat_verification=flat_verification,
                )
            except Exception as exc:  # noqa: BLE001 - proof boundary fails closed.
                raise AccountHaltError(
                    "account HALT emergency action binding failed validation"
                ) from exc

    @staticmethod
    def _now() -> str:
        return datetime.now(UTC).isoformat()

    @staticmethod
    def _clean_required(value: str, *, field: str) -> str:
        cleaned = str(value or "").strip()
        if not cleaned:
            raise ValueError(f"account HALT {field} is required")
        return cleaned

    @staticmethod
    def _validate_epoch(value: object, *, field: str = "epoch") -> int:
        if type(value) is not int or value <= 0:
            raise AccountHaltError(f"account HALT {field} must be a positive exact integer")
        return value

    @staticmethod
    def _validate_individual_intent(
        action_name: object,
        close_positions: object,
    ) -> tuple[str, bool]:
        action = str(action_name or "").strip()
        if action not in _INDIVIDUAL_HALT_ACTIONS:
            raise ValueError("individual account HALT action_name is unsupported")
        if type(close_positions) is not bool:
            raise ValueError("individual account HALT close_positions must be an exact boolean")
        if _INDIVIDUAL_HALT_ACTIONS[action] is not close_positions:
            raise ValueError("individual account HALT action/close intent is inconsistent")
        return action, close_positions

    @staticmethod
    def _assert_private_directory(path: Path) -> None:
        info = path.lstat()
        if stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode):
            raise AccountHaltError(f"account HALT directory must be a non-symlink directory: {path}")
        if info.st_uid != os.getuid():
            raise AccountHaltError(f"account HALT directory must be owned by the runtime user: {path}")
        path.chmod(0o700)

    @staticmethod
    def _assert_private_file(path: Path) -> None:
        try:
            info = path.lstat()
        except FileNotFoundError as exc:
            raise AccountHaltError(f"account HALT database disappeared: {path}") from exc
        if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode):
            raise AccountHaltError(f"account HALT database must be a regular non-symlink file: {path}")
        if info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) != 0o600:
            raise AccountHaltError(f"account HALT database must be owner-only mode 0600: {path}")

    def _prepare_private_storage(self) -> None:
        if self._path.parent.exists() and self._path.parent.is_symlink():
            raise AccountHaltError(f"account HALT parent must not be a symlink: {self._path.parent}")
        self._path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        self._assert_private_directory(self._path.parent)
        self._lock_dir.mkdir(mode=0o700, exist_ok=True)
        self._assert_private_directory(self._lock_dir)
        if not self._path.exists():
            flags = os.O_RDWR | os.O_CREAT | os.O_EXCL
            flags |= getattr(os, "O_NOFOLLOW", 0)
            fd = os.open(self._path, flags, 0o600)
            try:
                os.fsync(fd)
            finally:
                os.close(fd)
            parent_fd = os.open(self._path.parent, os.O_RDONLY)
            try:
                os.fsync(parent_fd)
            finally:
                os.close(parent_fd)
        self._assert_private_file(self._path)

    def _conn(self) -> sqlite3.Connection:
        self._assert_private_file(self._path)
        conn = sqlite3.connect(self._path, timeout=5.0, isolation_level=None)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA busy_timeout=5000")
        conn.execute("PRAGMA synchronous=FULL")
        conn.execute("PRAGMA fullfsync=ON")
        return conn

    def _initialize(self) -> None:
        conn = self._conn()
        try:
            conn.execute("PRAGMA journal_mode=DELETE")
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS account_halt_state (
                    account_binding_ref TEXT PRIMARY KEY,
                    owner_user_id TEXT NOT NULL,
                    state TEXT NOT NULL CHECK(state IN ('running','halting','halted')),
                    epoch INTEGER NOT NULL CHECK(epoch > 0),
                    execution_enabled INTEGER NOT NULL DEFAULT 0
                        CHECK(execution_enabled IN (0,1)),
                    halt_ref TEXT,
                    halt_started_at_utc TEXT,
                    halted_at_utc TEXT,
                    flat_proof_ref TEXT,
                    halt_action_name TEXT,
                    halt_close_positions INTEGER
                        CHECK(halt_close_positions IN (0,1)),
                    updated_at_utc TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS account_halt_owners (
                    owner_user_id TEXT PRIMARY KEY,
                    state TEXT NOT NULL CHECK(state IN ('running','halting','halted')),
                    epoch INTEGER NOT NULL CHECK(epoch > 0),
                    halt_ref TEXT,
                    halt_action_name TEXT,
                    halt_close_positions INTEGER
                        CHECK(halt_close_positions IN (0,1)),
                    updated_at_utc TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS account_halt_events (
                    seq INTEGER PRIMARY KEY AUTOINCREMENT,
                    event_ref TEXT NOT NULL UNIQUE,
                    account_binding_ref TEXT NOT NULL,
                    owner_user_id TEXT NOT NULL,
                    from_state TEXT,
                    to_state TEXT NOT NULL,
                    epoch INTEGER NOT NULL,
                    proof_ref TEXT,
                    created_at_utc TEXT NOT NULL,
                    FOREIGN KEY(account_binding_ref)
                        REFERENCES account_halt_state(account_binding_ref)
                );
                CREATE INDEX IF NOT EXISTS idx_account_halt_events_account
                    ON account_halt_events(account_binding_ref, seq);
                CREATE TABLE IF NOT EXISTS account_halt_flat_proofs (
                    flat_proof_ref TEXT PRIMARY KEY,
                    owner_user_id TEXT NOT NULL,
                    owner_epoch INTEGER NOT NULL CHECK(owner_epoch > 0),
                    halt_ref TEXT NOT NULL,
                    close_positions INTEGER NOT NULL CHECK(close_positions IN (0,1)),
                    account_epochs_json TEXT NOT NULL,
                    results_json TEXT NOT NULL,
                    created_at_utc TEXT NOT NULL
                );
                """
            )
            columns = {
                str(row[1])
                for row in conn.execute("PRAGMA table_info(account_halt_state)").fetchall()
            }
            if "execution_enabled" not in columns:
                conn.execute(
                    "ALTER TABLE account_halt_state "
                    "ADD COLUMN execution_enabled INTEGER NOT NULL DEFAULT 0"
                )
            if "halt_action_name" not in columns:
                conn.execute(
                    "ALTER TABLE account_halt_state ADD COLUMN halt_action_name TEXT"
                )
            if "halt_close_positions" not in columns:
                conn.execute(
                    "ALTER TABLE account_halt_state ADD COLUMN halt_close_positions INTEGER"
                )
            owner_columns = {
                str(row[1])
                for row in conn.execute("PRAGMA table_info(account_halt_owners)").fetchall()
            }
            flat_proof_columns = {
                str(row[1])
                for row in conn.execute(
                    "PRAGMA table_info(account_halt_flat_proofs)"
                ).fetchall()
            }
            if "owner_epoch" not in flat_proof_columns:
                conn.execute(
                    "ALTER TABLE account_halt_flat_proofs "
                    "ADD COLUMN owner_epoch INTEGER NOT NULL DEFAULT 0"
                )
            if "halt_action_name" not in owner_columns:
                conn.execute("ALTER TABLE account_halt_owners ADD COLUMN halt_action_name TEXT")
            if "halt_close_positions" not in owner_columns:
                conn.execute(
                    "ALTER TABLE account_halt_owners ADD COLUMN halt_close_positions INTEGER"
                )
            check = conn.execute("PRAGMA quick_check").fetchone()
            if check is None or str(check[0]) != "ok":
                raise AccountHaltError("account HALT database integrity check failed")
        finally:
            conn.close()
        self._path.chmod(0o600)

    @staticmethod
    def _snapshot_from_row(row: sqlite3.Row) -> AccountHaltSnapshot:
        state = str(row["state"])
        if state not in {"running", "halting", "halted"}:
            raise AccountHaltError("account HALT row contains an invalid state")
        epoch = PersistentAccountHaltBarrier._validate_epoch(row["epoch"])
        account_ref = str(row["account_binding_ref"] or "").strip()
        owner = str(row["owner_user_id"] or "").strip()
        updated_at = str(row["updated_at_utc"] or "").strip()
        if not account_ref or not owner or not updated_at:
            raise AccountHaltError("account HALT row is structurally incomplete")
        action_name = str(row["halt_action_name"] or "").strip()
        raw_close_positions = row["halt_close_positions"]
        if not action_name and raw_close_positions is None:
            action_name_value: str | None = None
            close_positions_value: bool | None = None
        elif (
            action_name
            and type(raw_close_positions) is int
            and raw_close_positions in {0, 1}
        ):
            action_name_value = action_name
            close_positions_value = bool(raw_close_positions)
        else:
            raise AccountHaltError("account HALT row contains incomplete operation intent")
        if state == "running" and (
            action_name_value is not None or close_positions_value is not None
        ):
            raise AccountHaltError("running account HALT row retains stale operation intent")
        return AccountHaltSnapshot(
            account_binding_ref=account_ref,
            owner_user_id=owner,
            state=state,  # type: ignore[arg-type]
            epoch=epoch,
            execution_enabled=bool(row["execution_enabled"]),
            halt_ref=str(row["halt_ref"] or "") or None,
            halt_started_at_utc=str(row["halt_started_at_utc"] or "") or None,
            halted_at_utc=str(row["halted_at_utc"] or "") or None,
            flat_proof_ref=str(row["flat_proof_ref"] or "") or None,
            updated_at_utc=updated_at,
            halt_action_name=action_name_value,
            halt_close_positions=close_positions_value,
        )

    @staticmethod
    def _append_event(
        conn: sqlite3.Connection,
        *,
        account_ref: str,
        owner: str,
        from_state: str | None,
        to_state: str,
        epoch: int,
        proof_ref: str | None,
        created_at: str,
    ) -> None:
        payload = {
            "account_binding_ref": account_ref,
            "owner_user_id": owner,
            "from_state": from_state,
            "to_state": to_state,
            "epoch": epoch,
            "proof_ref": proof_ref,
            "created_at_utc": created_at,
        }
        conn.execute(
            """
            INSERT INTO account_halt_events (
                event_ref, account_binding_ref, owner_user_id, from_state,
                to_state, epoch, proof_ref, created_at_utc
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "account_halt_event_" + content_hash(payload),
                account_ref,
                owner,
                from_state,
                to_state,
                epoch,
                proof_ref,
                created_at,
            ),
        )

    def snapshot(self, account_binding_ref: str) -> AccountHaltSnapshot | None:
        account_ref = self._clean_required(account_binding_ref, field="account_binding_ref")
        conn = self._conn()
        try:
            row = conn.execute(
                "SELECT * FROM account_halt_state WHERE account_binding_ref=?",
                (account_ref,),
            ).fetchone()
        finally:
            conn.close()
        return None if row is None else self._snapshot_from_row(row)

    def require_snapshot(self, account_binding_ref: str, owner_user_id: str) -> AccountHaltSnapshot:
        owner = self._clean_required(owner_user_id, field="owner_user_id")
        snapshot = self.snapshot(account_binding_ref)
        if snapshot is None:
            raise PermissionError("account HALT state is missing")
        if snapshot.owner_user_id != owner:
            raise PermissionError("account HALT state belongs to a different owner")
        return snapshot

    def validate_account(self, account_binding_ref: str, owner_user_id: str) -> AccountHaltSnapshot:
        """Validate the owner latch and account row without requiring ``running``."""

        owner = self._clean_required(owner_user_id, field="owner_user_id")
        account_ref = self._clean_required(account_binding_ref, field="account_binding_ref")
        conn = self._conn()
        try:
            owner_state, _owner_epoch = self._require_owner_state(conn, owner)
            row = conn.execute(
                "SELECT * FROM account_halt_state WHERE account_binding_ref=?",
                (account_ref,),
            ).fetchone()
        finally:
            conn.close()
        if row is None:
            raise PermissionError("account HALT state is missing")
        snapshot = self._snapshot_from_row(row)
        if snapshot.owner_user_id != owner:
            raise PermissionError("account HALT state belongs to a different owner")
        if owner_state in {"halting", "halted"} and snapshot.execution_enabled and snapshot.state == "running":
            raise AccountHaltError("HALTed owner contains an enabled running account")
        if owner_state == "halted" and snapshot.execution_enabled and snapshot.state != "halted":
            raise AccountHaltError("halted owner contains an unfinished enabled account")
        return snapshot

    def owner_state(self, owner_user_id: str) -> AccountHaltState:
        """Return the durable owner latch state for audit and orchestration."""

        owner = self._clean_required(owner_user_id, field="owner_user_id")
        conn = self._conn()
        try:
            state, _epoch = self._require_owner_state(conn, owner)
        finally:
            conn.close()
        return state  # type: ignore[return-value]

    def owner_epoch(self, owner_user_id: str) -> int:
        """Return the exact durable owner epoch for account-scoped orchestration."""

        owner = self._clean_required(owner_user_id, field="owner_user_id")
        conn = self._conn()
        try:
            _state, epoch = self._require_owner_state(conn, owner)
            return epoch
        finally:
            conn.close()

    @contextmanager
    def emergency_action_fence(
        self,
        *,
        owner_user_id: str,
        owner_epoch: int,
        halt_ref: str,
        account_binding_ref: str,
        account_epoch: int,
    ):
        """Serialize journal prepare with account HALT finalization."""

        owner = self._clean_required(owner_user_id, field="owner_user_id")
        account_ref = self._clean_required(
            account_binding_ref,
            field="account_binding_ref",
        )
        expected_owner_epoch = self._validate_epoch(
            owner_epoch,
            field="expected owner epoch",
        )
        expected_account_epoch = self._validate_epoch(account_epoch)
        expected_halt_ref = self._clean_required(halt_ref, field="halt_ref")
        held = self._acquire_raw_fence(
            account_ref,
            timeout=self._drain_timeout_seconds,
        )
        try:
            conn = self._conn()
            try:
                _owner_state, current_owner_epoch = self._require_owner_state(conn, owner)
                row = conn.execute(
                    "SELECT * FROM account_halt_state WHERE account_binding_ref=?",
                    (account_ref,),
                ).fetchone()
            finally:
                conn.close()
            if current_owner_epoch != expected_owner_epoch or row is None:
                raise PermissionError("emergency action HALT owner/epoch changed")
            snapshot = self._snapshot_from_row(row)
            if (
                snapshot.owner_user_id != owner
                or snapshot.state != "halting"
                or snapshot.epoch != expected_account_epoch
                or snapshot.halt_ref != expected_halt_ref
            ):
                raise PermissionError("emergency action HALT account scope changed")
            yield
        finally:
            held.release()

    def halting_owner_ids(self) -> tuple[str, ...]:
        """List durable global owner latches that require recovery."""

        conn = self._conn()
        try:
            rows = conn.execute(
                "SELECT owner_user_id FROM account_halt_owners "
                "WHERE state='halting' ORDER BY owner_user_id"
            ).fetchall()
        finally:
            conn.close()
        owners = tuple(str(row["owner_user_id"] or "").strip() for row in rows)
        if any(not owner for owner in owners):
            raise AccountHaltError("account HALT owner recovery row is structurally incomplete")
        return owners

    def owner_halt_operation(self, owner_user_id: str) -> AccountHaltOperation:
        """Resolve the exact persisted intent for one incomplete global HALT."""

        owner = self._clean_required(owner_user_id, field="owner_user_id")
        conn = self._conn()
        try:
            row = conn.execute(
                "SELECT * FROM account_halt_owners WHERE owner_user_id=?",
                (owner,),
            ).fetchone()
        finally:
            conn.close()
        if row is None or str(row["state"] or "") != "halting":
            raise PermissionError("owner does not have an incomplete global HALT")
        halt_ref = str(row["halt_ref"] or "").strip()
        action_name = str(row["halt_action_name"] or "").strip()
        close_positions = row["halt_close_positions"]
        updated_at = str(row["updated_at_utc"] or "").strip()
        if (
            not halt_ref
            or not action_name
            or type(close_positions) is not int
            or close_positions not in {0, 1}
            or not updated_at
        ):
            raise AccountHaltError("incomplete global HALT lacks persisted operation intent")
        return AccountHaltOperation(
            owner_user_id=owner,
            state="halting",
            epoch=self._validate_epoch(row["epoch"], field="owner epoch"),
            halt_ref=halt_ref,
            action_name=action_name,
            close_positions=bool(close_positions),
            updated_at_utc=updated_at,
        )

    def halt_evidence(
        self,
        halt_ref: str,
        *,
        owner_user_id: str,
    ) -> AccountHaltEvidence:
        """Resolve one exact persisted HALT ref without mutating account state.

        The original operation ref may live on the owner latch, account rows, or
        flat-proof rows after finalization.  At least one of those durable rows
        must match the same owner; lexical shape alone never counts.
        """

        owner = self._clean_required(owner_user_id, field="owner_user_id")
        proof = self._clean_required(halt_ref, field="halt_ref")
        conn = self._conn()
        try:
            owner_row = conn.execute(
                "SELECT * FROM account_halt_owners WHERE owner_user_id=?",
                (owner,),
            ).fetchone()
            account_rows = conn.execute(
                "SELECT * FROM account_halt_state "
                "WHERE owner_user_id=? AND halt_ref=? ORDER BY account_binding_ref",
                (owner, proof),
            ).fetchall()
            proof_rows = conn.execute(
                "SELECT flat_proof_ref FROM account_halt_flat_proofs "
                "WHERE owner_user_id=? AND halt_ref=? ORDER BY flat_proof_ref",
                (owner, proof),
            ).fetchall()
        finally:
            conn.close()
        owner_matches = (
            owner_row is not None
            and str(owner_row["halt_ref"] or "").strip() == proof
        )
        if not owner_matches and not account_rows and not proof_rows:
            raise KeyError(f"unknown account HALT ref for owner: {proof}")
        if owner_row is None:
            raise AccountHaltError("account HALT evidence lacks its owner latch")
        state = str(owner_row["state"] or "")
        if state not in {"halting", "halted"}:
            raise AccountHaltError("account HALT evidence owner latch is not active")
        owner_epoch = self._validate_epoch(owner_row["epoch"], field="owner epoch")
        updated_at = str(owner_row["updated_at_utc"] or "").strip()
        if not updated_at:
            raise AccountHaltError("account HALT evidence lacks updated_at_utc")
        return AccountHaltEvidence(
            owner_user_id=owner,
            halt_ref=proof,
            owner_state=state,  # type: ignore[arg-type]
            owner_epoch=owner_epoch,
            account_binding_refs=tuple(
                str(row["account_binding_ref"] or "").strip()
                for row in account_rows
            ),
            flat_proof_refs=tuple(
                str(row["flat_proof_ref"] or "").strip()
                for row in proof_rows
            ),
            updated_at_utc=updated_at,
        )

    def account_halt_operation(
        self,
        account_binding_ref: str,
        owner_user_id: str,
    ) -> AccountHaltAccountOperation:
        """Resolve exact persisted intent for one incomplete individual HALT."""

        snapshot = self.require_snapshot(account_binding_ref, owner_user_id)
        if snapshot.state not in {"halting", "halted"}:
            raise PermissionError("account has no incomplete HALT operation")
        halt_ref = str(snapshot.halt_ref or "").strip()
        action_name = str(snapshot.halt_action_name or "").strip()
        close_positions = snapshot.halt_close_positions
        if (
            not halt_ref
            or action_name not in _INDIVIDUAL_HALT_ACTIONS
            or type(close_positions) is not bool
            or _INDIVIDUAL_HALT_ACTIONS[action_name] is not close_positions
        ):
            raise AccountHaltError("incomplete account HALT lacks persisted operation intent")
        return AccountHaltAccountOperation(
            owner_user_id=snapshot.owner_user_id,
            account_binding_ref=snapshot.account_binding_ref,
            state=snapshot.state,
            epoch=snapshot.epoch,
            halt_ref=halt_ref,
            action_name=action_name,
            close_positions=close_positions,
            updated_at_utc=snapshot.updated_at_utc,
        )

    def halting_accounts(self) -> tuple[AccountHaltSnapshot, ...]:
        """List every individually or globally incomplete account HALT."""

        conn = self._conn()
        try:
            rows = conn.execute(
                "SELECT * FROM account_halt_state "
                "WHERE state='halting' ORDER BY owner_user_id, account_binding_ref"
            ).fetchall()
        finally:
            conn.close()
        return tuple(self._snapshot_from_row(row) for row in rows)

    def record_flat_proof(
        self,
        owner_user_id: str,
        *,
        halt_ref: str,
        close_positions: bool,
        account_epochs: Mapping[str, int],
        results: Mapping[str, object],
    ) -> str:
        """Persist the sanitized backing payload for a HALT flat-proof ref."""

        owner = self._clean_required(owner_user_id, field="owner_user_id")
        halt = self._clean_required(halt_ref, field="halt_ref")
        if type(close_positions) is not bool:
            raise ValueError("account HALT flat proof close_positions must be an exact boolean")
        epochs = {
            self._clean_required(ref, field="account_binding_ref"): self._validate_epoch(epoch)
            for ref, epoch in sorted(account_epochs.items())
        }
        normalized_results = dict(results)
        if set(normalized_results) != set(epochs):
            raise ValueError(
                "account HALT flat proof must contain exactly one result per account epoch"
            )
        for account_ref, raw_result in normalized_results.items():
            if not isinstance(account_ref, str) or account_ref not in epochs:
                raise ValueError("account HALT flat proof contains an unknown account result")
            if not isinstance(raw_result, dict):
                raise ValueError("account HALT flat proof account result must be an object")
            normal_refs = raw_result.get("normal_open_order_refs")
            algo_refs = raw_result.get("algo_open_order_refs")
            open_positions = raw_result.get("open_positions")
            if (
                raw_result.get("ok") is not True
                or not isinstance(normal_refs, list)
                or normal_refs
                or not isinstance(algo_refs, list)
                or algo_refs
                or not isinstance(open_positions, list)
                or open_positions
            ):
                raise ValueError(
                    "account HALT flat proof result does not attest zero venue exposure"
                )
        if epochs and not close_positions:
            raise ValueError(
                "account HALT flat proof cannot finalize accounts when close_positions is false"
            )
        results_json = json.dumps(
            normalized_results,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
        epochs_json = json.dumps(epochs, sort_keys=True, separators=(",", ":"))
        now = self._now()
        conn = self._conn()
        try:
            conn.execute("BEGIN IMMEDIATE")
            _owner_state, owner_epoch = self._require_owner_state(conn, owner)
            self._validate_emergency_action_bindings(
                owner_user_id=owner,
                owner_epoch=owner_epoch,
                halt_ref=halt,
                account_epochs=epochs,
                results=normalized_results,
            )
            payload = {
                "owner_user_id": owner,
                "owner_epoch": owner_epoch,
                "halt_ref": halt,
                "close_positions": close_positions,
                "account_epochs": epochs,
                "results": json.loads(results_json),
                "created_at_utc": now,
            }
            proof_ref = "account_halt_flat_" + content_hash(payload)
            existing = conn.execute(
                "SELECT * FROM account_halt_flat_proofs WHERE flat_proof_ref=?",
                (proof_ref,),
            ).fetchone()
            if existing is None:
                conn.execute(
                    """
                    INSERT INTO account_halt_flat_proofs (
                        flat_proof_ref,owner_user_id,owner_epoch,halt_ref,close_positions,
                        account_epochs_json,results_json,created_at_utc
                    ) VALUES (?,?,?,?,?,?,?,?)
                    """,
                    (
                        proof_ref,
                        owner,
                        owner_epoch,
                        halt,
                        int(close_positions),
                        epochs_json,
                        results_json,
                        now,
                    ),
                )
            elif (
                existing["owner_user_id"] != owner
                or existing["owner_epoch"] != owner_epoch
                or existing["halt_ref"] != halt
                or existing["close_positions"] != int(close_positions)
                or existing["account_epochs_json"] != epochs_json
                or existing["results_json"] != results_json
            ):
                raise AccountHaltError("account HALT flat-proof identity collision")
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()
        return proof_ref

    def _flat_proof_from_row(self, row: sqlite3.Row) -> dict[str, object]:
        """Decode and re-hash one stored proof; any mutation fails closed."""

        proof_ref = self._clean_required(row["flat_proof_ref"], field="flat_proof_ref")
        owner = self._clean_required(row["owner_user_id"], field="flat proof owner_user_id")
        try:
            owner_epoch = self._validate_epoch(
                row["owner_epoch"],
                field="flat proof owner epoch",
            )
        except (TypeError, ValueError) as exc:
            raise AccountHaltError("account HALT flat proof contains an invalid owner epoch") from exc
        halt_ref = self._clean_required(row["halt_ref"], field="flat proof halt_ref")
        raw_close_positions = row["close_positions"]
        if type(raw_close_positions) is not int or raw_close_positions not in {0, 1}:
            raise AccountHaltError("account HALT flat proof contains an invalid close_positions value")
        try:
            raw_epochs = json.loads(str(row["account_epochs_json"]))
            raw_results = json.loads(str(row["results_json"]))
        except (TypeError, ValueError, json.JSONDecodeError) as exc:
            raise AccountHaltError("account HALT flat proof contains invalid JSON") from exc
        if not isinstance(raw_epochs, dict) or not isinstance(raw_results, dict):
            raise AccountHaltError("account HALT flat proof payload must contain object maps")
        try:
            epochs = {
                self._clean_required(ref, field="flat proof account_binding_ref"): self._validate_epoch(
                    epoch,
                    field="flat proof account epoch",
                )
                for ref, epoch in sorted(raw_epochs.items())
            }
        except (TypeError, ValueError) as exc:
            raise AccountHaltError("account HALT flat proof contains an invalid account epoch map") from exc
        if epochs != raw_epochs or set(raw_results) != set(epochs):
            raise AccountHaltError("account HALT flat proof account/result scope is inconsistent")
        for account_ref, raw_result in raw_results.items():
            if not isinstance(account_ref, str) or not isinstance(raw_result, dict):
                raise AccountHaltError("account HALT flat proof contains a malformed account result")
            normal_refs = raw_result.get("normal_open_order_refs")
            algo_refs = raw_result.get("algo_open_order_refs")
            open_positions = raw_result.get("open_positions")
            if (
                raw_result.get("ok") is not True
                or not isinstance(normal_refs, list)
                or normal_refs
                or not isinstance(algo_refs, list)
                or algo_refs
                or not isinstance(open_positions, list)
                or open_positions
            ):
                raise AccountHaltError(
                    "account HALT flat proof result does not attest zero venue exposure"
                )
        close_positions = bool(raw_close_positions)
        if epochs and not close_positions:
            raise AccountHaltError(
                "account HALT flat proof cannot cover accounts when close_positions is false"
            )
        self._validate_emergency_action_bindings(
            owner_user_id=owner,
            owner_epoch=owner_epoch,
            halt_ref=halt_ref,
            account_epochs=epochs,
            results=raw_results,
        )
        canonical_epochs_json = json.dumps(epochs, sort_keys=True, separators=(",", ":"))
        canonical_results_json = json.dumps(
            raw_results,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
        if (
            canonical_epochs_json != str(row["account_epochs_json"])
            or canonical_results_json != str(row["results_json"])
        ):
            raise AccountHaltError("account HALT flat proof JSON is not canonical")
        created_at = self._clean_required(
            row["created_at_utc"],
            field="flat proof created_at_utc",
        )
        try:
            parsed_created_at = datetime.fromisoformat(created_at)
        except ValueError as exc:
            raise AccountHaltError("account HALT flat proof created_at_utc is malformed") from exc
        if parsed_created_at.tzinfo is None:
            raise AccountHaltError("account HALT flat proof created_at_utc must be timezone-aware")
        payload = {
            "owner_user_id": owner,
            "owner_epoch": owner_epoch,
            "halt_ref": halt_ref,
            "close_positions": close_positions,
            "account_epochs": epochs,
            "results": raw_results,
            "created_at_utc": created_at,
        }
        expected_ref = "account_halt_flat_" + content_hash(payload)
        if proof_ref != expected_ref:
            raise AccountHaltError("account HALT flat-proof identity does not match its payload")
        return {
            "flat_proof_ref": proof_ref,
            **payload,
        }

    def _require_flat_proof(
        self,
        conn: sqlite3.Connection,
        flat_proof_ref: str,
        *,
        owner_user_id: str,
        owner_epoch: int | None = None,
        account_epochs: Mapping[str, int],
        halt_ref: str | None = None,
        close_positions: bool | None = None,
    ) -> dict[str, object]:
        row = conn.execute(
            "SELECT * FROM account_halt_flat_proofs WHERE flat_proof_ref=?",
            (flat_proof_ref,),
        ).fetchone()
        if row is None:
            raise PermissionError("account HALT finalization proof is missing")
        proof = self._flat_proof_from_row(row)
        expected_epochs = {
            self._clean_required(ref, field="account_binding_ref"): self._validate_epoch(epoch)
            for ref, epoch in sorted(account_epochs.items())
        }
        if proof["owner_user_id"] != owner_user_id:
            raise PermissionError("account HALT finalization proof belongs to a different owner")
        if owner_epoch is not None and proof["owner_epoch"] != self._validate_epoch(
            owner_epoch,
            field="expected owner epoch",
        ):
            raise PermissionError("account HALT finalization proof has a stale owner epoch")
        if proof["account_epochs"] != expected_epochs:
            raise PermissionError("account HALT finalization proof has a different account/epoch scope")
        if halt_ref is not None and proof["halt_ref"] != halt_ref:
            raise PermissionError("account HALT finalization proof belongs to a different HALT operation")
        if close_positions is not None and proof["close_positions"] is not close_positions:
            raise PermissionError("account HALT finalization proof has a different close-positions intent")
        return proof

    def flat_proof(self, flat_proof_ref: str) -> dict[str, object]:
        proof = self._clean_required(flat_proof_ref, field="flat_proof_ref")
        conn = self._conn()
        try:
            row = conn.execute(
                "SELECT * FROM account_halt_flat_proofs WHERE flat_proof_ref=?",
                (proof,),
            ).fetchone()
        finally:
            conn.close()
        if row is None:
            raise KeyError(f"unknown account HALT flat proof: {proof}")
        return self._flat_proof_from_row(row)

    def _require_owner_state(self, conn: sqlite3.Connection, owner: str) -> tuple[str, int]:
        row = conn.execute(
            "SELECT state, epoch FROM account_halt_owners WHERE owner_user_id=?",
            (owner,),
        ).fetchone()
        if row is None:
            raise PermissionError("account HALT owner latch is missing")
        state = str(row["state"] or "")
        if state not in {"running", "halting", "halted"}:
            raise AccountHaltError("account HALT owner latch contains an invalid state")
        return state, self._validate_epoch(row["epoch"], field="owner epoch")

    def provision(self, account_binding_ref: str, owner_user_id: str) -> tuple[AccountHaltSnapshot, bool]:
        """Create a disabled running account; never resumes a HALTed account."""

        account_ref = self._clean_required(account_binding_ref, field="account_binding_ref")
        owner = self._clean_required(owner_user_id, field="owner_user_id")
        now = self._now()
        conn = self._conn()
        try:
            conn.execute("BEGIN IMMEDIATE")
            owner_row = conn.execute(
                "SELECT state, epoch FROM account_halt_owners WHERE owner_user_id=?",
                (owner,),
            ).fetchone()
            if owner_row is None:
                conn.execute(
                    """
                    INSERT INTO account_halt_owners (
                        owner_user_id, state, epoch, updated_at_utc
                    ) VALUES (?, 'running', 1, ?)
                    """,
                    (owner, now),
                )
            else:
                owner_state = str(owner_row["state"] or "")
                self._validate_epoch(owner_row["epoch"], field="owner epoch")
                if owner_state != "running":
                    raise PermissionError("account owner is HALTed and requires a dedicated audited resume")
            row = conn.execute(
                "SELECT * FROM account_halt_state WHERE account_binding_ref=?",
                (account_ref,),
            ).fetchone()
            created = row is None
            if row is None:
                conn.execute(
                    """
                    INSERT INTO account_halt_state (
                        account_binding_ref, owner_user_id, state, epoch,
                        execution_enabled, updated_at_utc
                    ) VALUES (?, ?, 'running', 1, 0, ?)
                    """,
                    (account_ref, owner, now),
                )
                self._append_event(
                    conn,
                    account_ref=account_ref,
                    owner=owner,
                    from_state=None,
                    to_state="running",
                    epoch=1,
                    proof_ref="account_provisioned_disabled",
                    created_at=now,
                )
            else:
                snapshot = self._snapshot_from_row(row)
                if snapshot.owner_user_id != owner:
                    raise PermissionError("account HALT state belongs to a different owner")
                if snapshot.state != "running":
                    raise PermissionError("HALTed account requires a dedicated audited resume")
            row = conn.execute(
                "SELECT * FROM account_halt_state WHERE account_binding_ref=?",
                (account_ref,),
            ).fetchone()
            if row is None:  # pragma: no cover - transaction invariant
                raise AccountHaltError("account HALT activation row disappeared")
            result = self._snapshot_from_row(row)
            conn.commit()
            return result, created
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def enable(self, account_binding_ref: str, owner_user_id: str) -> AccountHaltSnapshot:
        """Enable live leases only after the external follower is fully staged."""

        account_ref = self._clean_required(account_binding_ref, field="account_binding_ref")
        owner = self._clean_required(owner_user_id, field="owner_user_id")
        now = self._now()
        conn = self._conn()
        try:
            conn.execute("BEGIN IMMEDIATE")
            owner_state, _owner_epoch = self._require_owner_state(conn, owner)
            if owner_state != "running":
                raise PermissionError("account owner is HALTed and cannot enable execution")
            row = conn.execute(
                "SELECT * FROM account_halt_state WHERE account_binding_ref=?",
                (account_ref,),
            ).fetchone()
            if row is None:
                raise PermissionError("account HALT state is missing")
            snapshot = self._snapshot_from_row(row)
            if snapshot.owner_user_id != owner or snapshot.state != "running":
                raise PermissionError("only an owned running account can enable execution")
            if not snapshot.execution_enabled:
                epoch = snapshot.epoch + 1
                conn.execute(
                    """
                    UPDATE account_halt_state
                    SET execution_enabled=1, epoch=?, updated_at_utc=?
                    WHERE account_binding_ref=? AND state='running'
                      AND execution_enabled=0 AND epoch=?
                    """,
                    (epoch, now, account_ref, snapshot.epoch),
                )
                self._append_event(
                    conn,
                    account_ref=account_ref,
                    owner=owner,
                    from_state="running",
                    to_state="running",
                    epoch=epoch,
                    proof_ref="account_execution_enabled",
                    created_at=now,
                )
            row = conn.execute(
                "SELECT * FROM account_halt_state WHERE account_binding_ref=?",
                (account_ref,),
            ).fetchone()
            if row is None:  # pragma: no cover - transaction invariant
                raise AccountHaltError("enabled account HALT row disappeared")
            result = self._snapshot_from_row(row)
            conn.commit()
            return result
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def activate(self, account_binding_ref: str, owner_user_id: str) -> tuple[AccountHaltSnapshot, bool]:
        """Convenience activation for callers without an external staged row."""

        _snapshot, created = self.provision(account_binding_ref, owner_user_id)
        return self.enable(account_binding_ref, owner_user_id), created

    def disable(self, account_binding_ref: str, owner_user_id: str, *, reason_ref: str) -> AccountHaltSnapshot:
        """Invalidate live capabilities during activation compensation."""

        account_ref = self._clean_required(account_binding_ref, field="account_binding_ref")
        owner = self._clean_required(owner_user_id, field="owner_user_id")
        proof = self._clean_required(reason_ref, field="reason_ref")
        conn = self._conn()
        try:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                "SELECT * FROM account_halt_state WHERE account_binding_ref=?",
                (account_ref,),
            ).fetchone()
            if row is None:
                raise PermissionError("account HALT state is missing")
            snapshot = self._snapshot_from_row(row)
            if snapshot.owner_user_id != owner:
                raise PermissionError("account HALT state belongs to a different owner")
            if snapshot.state == "running" and snapshot.execution_enabled:
                now = self._now()
                epoch = snapshot.epoch + 1
                conn.execute(
                    """
                    UPDATE account_halt_state
                    SET execution_enabled=0, epoch=?, updated_at_utc=?
                    WHERE account_binding_ref=? AND state='running'
                      AND execution_enabled=1 AND epoch=?
                    """,
                    (epoch, now, account_ref, snapshot.epoch),
                )
                self._append_event(
                    conn,
                    account_ref=account_ref,
                    owner=owner,
                    from_state="running",
                    to_state="running",
                    epoch=epoch,
                    proof_ref=proof,
                    created_at=now,
                )
            row = conn.execute(
                "SELECT * FROM account_halt_state WHERE account_binding_ref=?",
                (account_ref,),
            ).fetchone()
            if row is None:  # pragma: no cover - transaction invariant
                raise AccountHaltError("disabled account HALT row disappeared")
            result = self._snapshot_from_row(row)
            conn.commit()
            return result
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def running_epoch(self, account_binding_ref: str, owner_user_id: str) -> int:
        owner = self._clean_required(owner_user_id, field="owner_user_id")
        account_ref = self._clean_required(account_binding_ref, field="account_binding_ref")
        conn = self._conn()
        try:
            owner_state, _owner_epoch = self._require_owner_state(conn, owner)
            row = conn.execute(
                "SELECT * FROM account_halt_state WHERE account_binding_ref=?",
                (account_ref,),
            ).fetchone()
        finally:
            conn.close()
        if owner_state != "running":
            raise PermissionError(f"account HALT owner state={owner_state} denies live-order capability")
        if row is None:
            raise PermissionError("account HALT state is missing")
        snapshot = self._snapshot_from_row(row)
        if snapshot.owner_user_id != owner:
            raise PermissionError("account HALT state belongs to a different owner")
        if snapshot.state != "running":
            raise PermissionError(f"account HALT state={snapshot.state} denies live-order capability")
        if not snapshot.execution_enabled:
            raise PermissionError("account HALT execution is not enabled")
        return snapshot.epoch

    def _local_lock(self, account_ref: str) -> threading.Lock:
        with self._lock_map_guard:
            return self._local_locks.setdefault(account_ref, threading.Lock())

    def _lock_path(self, account_ref: str) -> Path:
        digest = content_hash({"account_binding_ref": account_ref})
        return self._lock_dir / f"{digest}.lock"

    def _acquire_raw_fence(self, account_ref: str, *, timeout: float) -> _HeldAccountFence:
        deadline = time.monotonic() + max(timeout, 0.0)
        local_lock = self._local_lock(account_ref)
        if not local_lock.acquire(timeout=max(deadline - time.monotonic(), 0.0)):
            raise TimeoutError(f"account HALT lease drain timed out for {account_ref}")
        fd = -1
        try:
            path = self._lock_path(account_ref)
            flags = os.O_RDWR | os.O_CREAT
            flags |= getattr(os, "O_NOFOLLOW", 0)
            flags |= getattr(os, "O_BINARY", 0)
            fd = os.open(path, flags, 0o600)
            info = os.fstat(fd)
            if not stat.S_ISREG(info.st_mode) or (
                hasattr(os, "getuid") and info.st_uid != os.getuid()
            ):
                raise AccountHaltError("account HALT fence file is not a privately owned regular file")
            if hasattr(os, "fchmod") and stat.S_IMODE(info.st_mode) != 0o600:
                os.fchmod(fd, 0o600)
            try:
                os_lock = acquire_exclusive_fd(
                    fd,
                    timeout_seconds=max(deadline - time.monotonic(), 0.0),
                )
            except CrossProcessLockTimeout as exc:
                raise TimeoutError(
                    f"account HALT lease drain timed out for {account_ref}"
                ) from exc
            except (CrossProcessLockError, OSError) as exc:
                raise AccountHaltError(
                    f"account HALT cross-process fence unavailable for {account_ref}"
                ) from exc
            return _HeldAccountFence(local_lock, fd, os_lock)
        except Exception:
            if fd >= 0:
                os.close(fd)
            local_lock.release()
            raise

    def acquire_execution_fence(
        self,
        account_binding_ref: str,
        owner_user_id: str,
        expected_epoch: int,
    ) -> _HeldAccountFence:
        """Hold the account fence for the complete lifetime of a live lease."""

        account_ref = self._clean_required(account_binding_ref, field="account_binding_ref")
        owner = self._clean_required(owner_user_id, field="owner_user_id")
        expected = self._validate_epoch(expected_epoch, field="capability epoch")
        # Reject a stale/non-running capability before waiting behind an
        # old-epoch lease.  The second read below remains authoritative for
        # the race where HALT commits after this optimistic check.
        if self.running_epoch(account_ref, owner) != expected:
            raise PermissionError("account HALT epoch/state changed before live-order lease")
        held = self._acquire_raw_fence(account_ref, timeout=self._drain_timeout_seconds)
        try:
            conn = self._conn()
            try:
                owner_state, _owner_epoch = self._require_owner_state(conn, owner)
                row = conn.execute(
                    "SELECT * FROM account_halt_state WHERE account_binding_ref=?",
                    (account_ref,),
                ).fetchone()
            finally:
                conn.close()
            if owner_state != "running" or row is None:
                raise PermissionError("account HALT owner/account state denies live-order lease")
            snapshot = self._snapshot_from_row(row)
            if snapshot.owner_user_id != owner:
                raise PermissionError("account HALT state belongs to a different owner")
            if (
                snapshot.state != "running"
                or not snapshot.execution_enabled
                or snapshot.epoch != expected
            ):
                raise PermissionError("account HALT epoch/state changed before live-order lease")
            return held
        except Exception:
            held.release()
            raise

    def _drain_fences(self, account_refs: tuple[str, ...]) -> None:
        deadline = time.monotonic() + self._drain_timeout_seconds
        held: list[_HeldAccountFence] = []
        try:
            for account_ref in account_refs:
                held.append(
                    self._acquire_raw_fence(
                        account_ref,
                        timeout=max(deadline - time.monotonic(), 0.0),
                    )
                )
        finally:
            for fence in reversed(held):
                fence.release()

    def _commit_halt_many(
        self,
        owner_user_id: str,
        account_binding_refs: tuple[str, ...] | list[str],
        *,
        halt_ref: str,
        allow_missing: bool = False,
        action_name: str | None = None,
        close_positions: bool | None = None,
        expected_owner_epoch: int | None = None,
    ) -> dict[str, AccountHaltSnapshot]:
        """Commit every selected/enabled account as non-running."""

        owner = self._clean_required(owner_user_id, field="owner_user_id")
        proof = self._clean_required(halt_ref, field="halt_ref")
        if (action_name is None) != (close_positions is None):
            raise ValueError("global account HALT action_name and close_positions must be provided together")
        persisted_action: str | None = None
        if action_name is not None:
            persisted_action = self._clean_required(action_name, field="action_name")
            if type(close_positions) is not bool:
                raise ValueError("global account HALT close_positions must be an exact boolean")
        expected_epoch = (
            None
            if expected_owner_epoch is None
            else self._validate_epoch(expected_owner_epoch, field="expected owner epoch")
        )
        if expected_epoch is not None and persisted_action is None:
            raise ValueError("global account HALT recovery CAS requires persisted operation intent")
        refs = tuple(sorted({self._clean_required(ref, field="account_binding_ref") for ref in account_binding_refs}))
        now = self._now()
        conn = self._conn()
        try:
            conn.execute("BEGIN IMMEDIATE")
            owner_row = conn.execute(
                "SELECT * FROM account_halt_owners WHERE owner_user_id=?",
                (owner,),
            ).fetchone()
            if expected_epoch is not None:
                if owner_row is None:
                    raise PermissionError("global account HALT recovery owner disappeared")
                if (
                    str(owner_row["state"] or "") != "halting"
                    or owner_row["epoch"] != expected_epoch
                    or str(owner_row["halt_ref"] or "").strip() != proof
                    or str(owner_row["halt_action_name"] or "").strip() != persisted_action
                    or owner_row["halt_close_positions"] != int(close_positions)
                ):
                    raise PermissionError("global account HALT recovery intent changed")
            if owner_row is None:
                if not allow_missing:
                    raise PermissionError("account HALT owner latch is missing")
                owner_state = "halting"
                owner_epoch = 1
                conn.execute(
                    """
                    INSERT INTO account_halt_owners (
                        owner_user_id, state, epoch, halt_ref, halt_action_name,
                        halt_close_positions, updated_at_utc
                    ) VALUES (?, 'halting', ?, ?, ?, ?, ?)
                    """,
                    (
                        owner,
                        owner_epoch,
                        proof,
                        persisted_action,
                        None if close_positions is None else int(close_positions),
                        now,
                    ),
                )
            else:
                owner_state = str(owner_row["state"] or "")
                owner_epoch = self._validate_epoch(owner_row["epoch"], field="owner epoch")
                reopen_halted_operation = False
                if owner_state not in {"running", "halting", "halted"}:
                    raise AccountHaltError("account HALT owner latch contains an invalid state")
                if owner_state == "running":
                    owner_state = "halting"
                    owner_epoch += 1
                    conn.execute(
                        """
                        UPDATE account_halt_owners
                        SET state='halting', epoch=?, halt_ref=?, halt_action_name=?,
                            halt_close_positions=?, updated_at_utc=?
                        WHERE owner_user_id=?
                        """,
                        (
                            owner_epoch,
                            proof,
                            persisted_action,
                            None if close_positions is None else int(close_positions),
                            now,
                            owner,
                        ),
                    )
                elif owner_state == "halting" and persisted_action is not None:
                    existing_ref = str(owner_row["halt_ref"] or "").strip()
                    existing_action = str(owner_row["halt_action_name"] or "").strip()
                    existing_close = owner_row["halt_close_positions"]
                    if (
                        not existing_ref
                        or not existing_action
                        or type(existing_close) is not int
                        or existing_close not in {0, 1}
                    ):
                        raise AccountHaltError(
                            "in-progress global HALT lacks persisted operation intent"
                        )
                    if existing_ref == proof:
                        if (
                            existing_action != persisted_action
                            or existing_close != int(close_positions)
                        ):
                            raise AccountHaltError("persisted global HALT intent changed for the same ref")
                    elif existing_close == 0 and close_positions is True:
                        # An authenticated close request may only strengthen an
                        # in-progress cancel-only operation.  No caller may
                        # downgrade close intent once it is durable.
                        conn.execute(
                            """
                            UPDATE account_halt_owners
                            SET halt_ref=?, halt_action_name=?, halt_close_positions=?,
                                updated_at_utc=?
                            WHERE owner_user_id=? AND state='halting' AND epoch=?
                            """,
                            (
                                proof,
                                persisted_action,
                                int(close_positions),
                                now,
                                owner,
                                owner_epoch,
                            ),
                        )
                    else:
                        # Preserve the already durable operation for equal or
                        # weaker fresh requests, including automated activation
                        # compensation racing a user emergency close.
                        proof = existing_ref
                        persisted_action = existing_action
                        close_positions = bool(existing_close)
                elif owner_state == "halted" and persisted_action is not None:
                    existing_ref = str(owner_row["halt_ref"] or "").strip()
                    if existing_ref == proof:
                        if (
                            str(owner_row["halt_action_name"] or "").strip() != persisted_action
                            or owner_row["halt_close_positions"] != int(close_positions)
                        ):
                            raise AccountHaltError("persisted global HALT intent changed for the same ref")
                    else:
                        reopen_halted_operation = True
                        owner_state = "halting"
                        owner_epoch += 1
                        conn.execute(
                            """
                            UPDATE account_halt_owners
                            SET state='halting', epoch=?, halt_ref=?, halt_action_name=?,
                                halt_close_positions=?, updated_at_utc=?
                            WHERE owner_user_id=? AND state='halted'
                            """,
                            (
                                owner_epoch,
                                proof,
                                persisted_action,
                                int(close_positions),
                                now,
                                owner,
                            ),
                        )
                else:
                    reopen_halted_operation = False
            if owner_row is None:
                reopen_halted_operation = False
            inserted_while_owner_halted = False
            for account_ref in refs:
                row = conn.execute(
                    "SELECT * FROM account_halt_state WHERE account_binding_ref=?",
                    (account_ref,),
                ).fetchone()
                if row is None:
                    if not allow_missing:
                        raise PermissionError(f"account HALT state is missing for {account_ref}")
                    inserted_while_owner_halted = inserted_while_owner_halted or owner_state == "halted"
                    epoch = 1
                    conn.execute(
                        """
                        INSERT INTO account_halt_state (
                            account_binding_ref, owner_user_id, state, epoch,
                            execution_enabled, halt_ref, halt_started_at_utc,
                            halt_action_name, halt_close_positions, updated_at_utc
                        ) VALUES (?, ?, 'halting', ?, 1, ?, ?, ?, ?, ?)
                        """,
                        (
                            account_ref,
                            owner,
                            epoch,
                            proof,
                            now,
                            persisted_action,
                            None if close_positions is None else int(close_positions),
                            now,
                        ),
                    )
                    self._append_event(
                        conn,
                        account_ref=account_ref,
                        owner=owner,
                        from_state=None,
                        to_state="halting",
                        epoch=epoch,
                        proof_ref=proof,
                        created_at=now,
                    )
                    continue
                snapshot = self._snapshot_from_row(row)
                if snapshot.owner_user_id != owner:
                    raise PermissionError("account HALT state belongs to a different owner")
            if inserted_while_owner_halted:
                owner_state = "halting"
                owner_epoch += 1
                conn.execute(
                    """
                    UPDATE account_halt_owners
                    SET state='halting', epoch=?, halt_ref=?, halt_action_name=?,
                        halt_close_positions=?, updated_at_utc=?
                    WHERE owner_user_id=?
                    """,
                    (
                        owner_epoch,
                        proof,
                        persisted_action,
                        None if close_positions is None else int(close_positions),
                        now,
                        owner,
                    ),
                )

            if persisted_action is not None and owner_state == "halting":
                superseded_rows = conn.execute(
                    """
                    SELECT * FROM account_halt_state
                    WHERE owner_user_id=? AND state='halting' AND halt_ref!=?
                    """,
                    (owner, proof),
                ).fetchall()
                for superseded_row in superseded_rows:
                    superseded = self._snapshot_from_row(superseded_row)
                    conn.execute(
                        """
                        UPDATE account_halt_state
                        SET halt_ref=?, halt_started_at_utc=?, flat_proof_ref=NULL,
                            halt_action_name=?, halt_close_positions=?, updated_at_utc=?
                        WHERE account_binding_ref=? AND state='halting' AND epoch=?
                        """,
                        (
                            proof,
                            now,
                            persisted_action,
                            int(bool(close_positions)),
                            now,
                            superseded.account_binding_ref,
                            superseded.epoch,
                        ),
                    )
                    self._append_event(
                        conn,
                        account_ref=superseded.account_binding_ref,
                        owner=owner,
                        from_state="halting",
                        to_state="halting",
                        epoch=superseded.epoch,
                        proof_ref=proof,
                        created_at=now,
                    )
                conn.execute(
                    """
                    UPDATE account_halt_state
                    SET halt_action_name=?, halt_close_positions=?, updated_at_utc=?
                    WHERE owner_user_id=? AND state='halting' AND halt_ref=?
                    """,
                    (
                        persisted_action,
                        int(bool(close_positions)),
                        now,
                        owner,
                        proof,
                    ),
                )

            # The owner latch and every account row are mutated under the same
            # SQLite writer transaction.  A concurrent activation therefore
            # either commits first and is discovered here, or observes the
            # latched owner and is rejected after this commit.
            owned_rows = conn.execute(
                "SELECT * FROM account_halt_state WHERE owner_user_id=? ORDER BY account_binding_ref",
                (owner,),
            ).fetchall()
            explicit_refs = set(refs)
            for row in owned_rows:
                snapshot = self._snapshot_from_row(row)
                if snapshot.state == "running" and (
                    snapshot.execution_enabled or snapshot.account_binding_ref in explicit_refs
                ):
                    epoch = snapshot.epoch + 1
                    conn.execute(
                        """
                        UPDATE account_halt_state
                        SET state='halting', epoch=?, execution_enabled=1,
                            halt_ref=?, halt_started_at_utc=?,
                            halted_at_utc=NULL, flat_proof_ref=NULL,
                            halt_action_name=?, halt_close_positions=?, updated_at_utc=?
                        WHERE account_binding_ref=? AND state='running' AND epoch=?
                        """,
                        (
                            epoch,
                            proof,
                            now,
                            persisted_action,
                            None if close_positions is None else int(close_positions),
                            now,
                            snapshot.account_binding_ref,
                            snapshot.epoch,
                        ),
                    )
                    self._append_event(
                        conn,
                        account_ref=snapshot.account_binding_ref,
                        owner=owner,
                        from_state="running",
                        to_state="halting",
                        epoch=epoch,
                        proof_ref=proof,
                        created_at=now,
                    )
                elif (
                    reopen_halted_operation
                    and snapshot.state == "halted"
                    and snapshot.account_binding_ref in explicit_refs
                ):
                    epoch = snapshot.epoch + 1
                    conn.execute(
                        """
                        UPDATE account_halt_state
                        SET state='halting', epoch=?, execution_enabled=1,
                            halt_ref=?, halt_started_at_utc=?, halted_at_utc=NULL,
                            flat_proof_ref=NULL, halt_action_name=?,
                            halt_close_positions=?, updated_at_utc=?
                        WHERE account_binding_ref=? AND state='halted' AND epoch=?
                        """,
                        (
                            epoch,
                            proof,
                            now,
                            persisted_action,
                            None if close_positions is None else int(close_positions),
                            now,
                            snapshot.account_binding_ref,
                            snapshot.epoch,
                        ),
                    )
                    self._append_event(
                        conn,
                        account_ref=snapshot.account_binding_ref,
                        owner=owner,
                        from_state="halted",
                        to_state="halting",
                        epoch=epoch,
                        proof_ref=proof,
                        created_at=now,
                    )
            rows = conn.execute(
                """
                SELECT * FROM account_halt_state
                WHERE owner_user_id=? AND execution_enabled=1
                ORDER BY account_binding_ref
                """,
                (owner,),
            ).fetchall()
            all_enabled = {
                row["account_binding_ref"]: self._snapshot_from_row(row)
                for row in rows
            }
            result = {
                ref: snapshot
                for ref, snapshot in all_enabled.items()
                if snapshot.state == "halting" or ref in explicit_refs
            }
            if not set(refs).issubset(result):
                raise AccountHaltError("account HALT transaction did not cover every requested account")
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

        return result

    def drain_account_fences(
        self,
        account_binding_refs: tuple[str, ...] | list[str],
    ) -> tuple[tuple[str, ...], tuple[str, ...]]:
        """Drain accounts independently so one hung lease cannot block peers."""

        refs = tuple(sorted({self._clean_required(ref, field="account_binding_ref") for ref in account_binding_refs}))
        if not refs:
            return (), ()

        def drain_one(account_ref: str) -> None:
            held = self._acquire_raw_fence(
                account_ref,
                timeout=self._drain_timeout_seconds,
            )
            held.release()

        drained: list[str] = []
        failed: list[str] = []
        with ThreadPoolExecutor(max_workers=min(len(refs), 16)) as pool:
            futures = {pool.submit(drain_one, ref): ref for ref in refs}
            for future in as_completed(futures):
                ref = futures[future]
                try:
                    future.result()
                except Exception:  # noqa: BLE001 - state remains durably halting.
                    failed.append(ref)
                else:
                    drained.append(ref)
        return tuple(sorted(drained)), tuple(sorted(failed))

    def begin_halt_many_partial(
        self,
        owner_user_id: str,
        account_binding_refs: tuple[str, ...] | list[str],
        *,
        halt_ref: str,
        allow_missing: bool = False,
        action_name: str | None = None,
        close_positions: bool | None = None,
        expected_owner_epoch: int | None = None,
    ) -> AccountHaltBatch:
        snapshots = self._commit_halt_many(
            owner_user_id,
            account_binding_refs,
            halt_ref=halt_ref,
            allow_missing=allow_missing,
            action_name=action_name,
            close_positions=close_positions,
            expected_owner_epoch=expected_owner_epoch,
        )
        drained, failed = self.drain_account_fences(list(snapshots))
        return AccountHaltBatch(
            snapshots=snapshots,
            drained_refs=drained,
            drain_failures=failed,
        )

    def begin_halt_many(
        self,
        owner_user_id: str,
        account_binding_refs: tuple[str, ...] | list[str],
        *,
        halt_ref: str,
        allow_missing: bool = False,
        action_name: str | None = None,
        close_positions: bool | None = None,
        expected_owner_epoch: int | None = None,
    ) -> dict[str, AccountHaltSnapshot]:
        """Strict batch helper used when every old-epoch lease must drain."""

        batch = self.begin_halt_many_partial(
            owner_user_id,
            account_binding_refs,
            halt_ref=halt_ref,
            allow_missing=allow_missing,
            action_name=action_name,
            close_positions=close_positions,
            expected_owner_epoch=expected_owner_epoch,
        )
        if batch.drain_failures:
            raise TimeoutError(
                f"account HALT lease drain failed for {len(batch.drain_failures)} account(s)"
            )
        return batch.snapshots

    def begin_account_halt(
        self,
        account_binding_ref: str,
        owner_user_id: str,
        *,
        halt_ref: str,
        action_name: str,
        close_positions: bool,
        allow_missing: bool = False,
    ) -> AccountHaltSnapshot:
        """Disable and drain one account without latching unrelated accounts."""

        account_ref = self._clean_required(account_binding_ref, field="account_binding_ref")
        owner = self._clean_required(owner_user_id, field="owner_user_id")
        proof = self._clean_required(halt_ref, field="halt_ref")
        action, close = self._validate_individual_intent(action_name, close_positions)
        now = self._now()
        conn = self._conn()
        try:
            conn.execute("BEGIN IMMEDIATE")
            owner_row = conn.execute(
                "SELECT state, epoch FROM account_halt_owners WHERE owner_user_id=?",
                (owner,),
            ).fetchone()
            if owner_row is None:
                if not allow_missing:
                    raise PermissionError("account HALT owner latch is missing")
                owner_state = "running"
                conn.execute(
                    "INSERT INTO account_halt_owners "
                    "(owner_user_id,state,epoch,updated_at_utc) VALUES (?,'running',1,?)",
                    (owner, now),
                )
            else:
                owner_state = str(owner_row["state"] or "")
                self._validate_epoch(owner_row["epoch"], field="owner epoch")
                if owner_state not in {"running", "halting", "halted"}:
                    raise AccountHaltError("account HALT owner latch contains an invalid state")
            row = conn.execute(
                "SELECT * FROM account_halt_state WHERE account_binding_ref=?",
                (account_ref,),
            ).fetchone()
            if row is None:
                if not allow_missing:
                    raise PermissionError("account HALT state is missing")
                if owner_state != "running":
                    raise PermissionError(
                        "missing individual account cannot be staged while the owner is HALTed"
                    )
                epoch = 1
                conn.execute(
                    """
                    INSERT INTO account_halt_state (
                        account_binding_ref, owner_user_id, state, epoch,
                        execution_enabled, halt_ref, halt_started_at_utc,
                        halt_action_name, halt_close_positions, updated_at_utc
                    ) VALUES (?, ?, 'halting', ?, 1, ?, ?, ?, ?, ?)
                    """,
                    (account_ref, owner, epoch, proof, now, action, int(close), now),
                )
                self._append_event(
                    conn,
                    account_ref=account_ref,
                    owner=owner,
                    from_state=None,
                    to_state="halting",
                    epoch=epoch,
                    proof_ref=proof,
                    created_at=now,
                )
            else:
                snapshot = self._snapshot_from_row(row)
                if snapshot.owner_user_id != owner:
                    raise PermissionError("account HALT state belongs to a different owner")
                if owner_state in {"halting", "halted"} and snapshot.state == "running":
                    raise AccountHaltError("HALTed owner contains a running account")
                if snapshot.state in {"halting", "halted"}:
                    if owner_state in {"halting", "halted"}:
                        # A global owner operation is stronger and already
                        # persisted on this row by _commit_halt_many.
                        proof = str(snapshot.halt_ref or proof)
                    elif snapshot.state == "halted":
                        if (
                            snapshot.halt_ref != proof
                            or snapshot.halt_action_name != action
                            or snapshot.halt_close_positions is not close
                        ):
                            raise PermissionError(
                                "halted account requires resume before a different operation"
                            )
                    elif snapshot.halt_ref == proof:
                        if (
                            snapshot.halt_action_name != action
                            or snapshot.halt_close_positions is not close
                        ):
                            raise AccountHaltError(
                                "persisted individual HALT intent changed for the same ref"
                            )
                    elif snapshot.halt_close_positions is True and close is False:
                        # Automated quarantine cannot downgrade an explicit
                        # user liquidation already in progress.
                        proof = str(snapshot.halt_ref or proof)
                    elif snapshot.halt_close_positions is False and close is True:
                        conn.execute(
                            """
                            UPDATE account_halt_state
                            SET halt_ref=?, halt_started_at_utc=?, halt_action_name=?,
                                halt_close_positions=1, flat_proof_ref=NULL, updated_at_utc=?
                            WHERE account_binding_ref=? AND state='halting' AND epoch=?
                            """,
                            (proof, now, action, now, account_ref, snapshot.epoch),
                        )
                        self._append_event(
                            conn,
                            account_ref=account_ref,
                            owner=owner,
                            from_state="halting",
                            to_state="halting",
                            epoch=snapshot.epoch,
                            proof_ref=proof,
                            created_at=now,
                        )
                    elif snapshot.halt_action_name is None:
                        # A current explicit request may replace a legacy
                        # intent-less row; passive recovery never calls begin.
                        conn.execute(
                            """
                            UPDATE account_halt_state
                            SET halt_ref=?, halt_started_at_utc=?, halt_action_name=?,
                                halt_close_positions=?, flat_proof_ref=NULL, updated_at_utc=?
                            WHERE account_binding_ref=? AND state='halting' AND epoch=?
                            """,
                            (
                                proof,
                                now,
                                action,
                                int(close),
                                now,
                                account_ref,
                                snapshot.epoch,
                            ),
                        )
                    else:
                        proof = str(snapshot.halt_ref or proof)
            if row is not None and snapshot.state == "running":
                epoch = snapshot.epoch + 1
                conn.execute(
                    """
                    UPDATE account_halt_state
                    SET state='halting', epoch=?, execution_enabled=1,
                        halt_ref=?, halt_started_at_utc=?, halted_at_utc=NULL,
                        flat_proof_ref=NULL, halt_action_name=?,
                        halt_close_positions=?, updated_at_utc=?
                    WHERE account_binding_ref=? AND state='running' AND epoch=?
                    """,
                    (
                        epoch,
                        proof,
                        now,
                        action,
                        int(close),
                        now,
                        account_ref,
                        snapshot.epoch,
                    ),
                )
                self._append_event(
                    conn,
                    account_ref=account_ref,
                    owner=owner,
                    from_state="running",
                    to_state="halting",
                    epoch=epoch,
                    proof_ref=proof,
                    created_at=now,
                )
            row = conn.execute(
                "SELECT * FROM account_halt_state WHERE account_binding_ref=?",
                (account_ref,),
            ).fetchone()
            if row is None:  # pragma: no cover - transaction invariant
                raise AccountHaltError("account HALT row disappeared during drain transition")
            result = self._snapshot_from_row(row)
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()
        self._drain_fences((account_ref,))
        return result

    def provision_after_owner_resume(
        self,
        account_binding_ref: str,
        owner_user_id: str,
        *,
        authorization_ref: str,
    ) -> AccountHaltSnapshot:
        """Atomically re-attest an empty halted owner and stage one disabled account.

        This is intentionally narrower than an owner-only ``resume``: the
        owner cannot become running without the new disabled account row being
        committed in the same writer transaction.
        """

        account_ref = self._clean_required(account_binding_ref, field="account_binding_ref")
        owner = self._clean_required(owner_user_id, field="owner_user_id")
        proof = self._clean_required(authorization_ref, field="authorization_ref")
        held = self._acquire_raw_fence(account_ref, timeout=self._drain_timeout_seconds)
        conn = self._conn()
        try:
            conn.execute("BEGIN IMMEDIATE")
            owner_state, owner_epoch = self._require_owner_state(conn, owner)
            if owner_state != "halted":
                raise PermissionError("empty-owner re-attestation requires a halted owner latch")
            existing_owned = conn.execute(
                "SELECT 1 FROM account_halt_state WHERE owner_user_id=? LIMIT 1",
                (owner,),
            ).fetchone()
            if existing_owned is not None:
                raise PermissionError(
                    "empty-owner re-attestation is denied when an account-specific resume exists"
                )
            collision = conn.execute(
                "SELECT owner_user_id FROM account_halt_state WHERE account_binding_ref=?",
                (account_ref,),
            ).fetchone()
            if collision is not None:
                raise PermissionError("account HALT state belongs to another owner")
            now = self._now()
            conn.execute(
                """
                UPDATE account_halt_owners
                SET state='running', epoch=?, halt_ref=NULL, halt_action_name=NULL,
                    halt_close_positions=NULL, updated_at_utc=?
                WHERE owner_user_id=? AND state='halted' AND epoch=?
                """,
                (owner_epoch + 1, now, owner, owner_epoch),
            )
            conn.execute(
                """
                INSERT INTO account_halt_state (
                    account_binding_ref, owner_user_id, state, epoch,
                    execution_enabled, updated_at_utc
                ) VALUES (?, ?, 'running', 1, 0, ?)
                """,
                (account_ref, owner, now),
            )
            self._append_event(
                conn,
                account_ref=account_ref,
                owner=owner,
                from_state=None,
                to_state="running",
                epoch=1,
                proof_ref=proof,
                created_at=now,
            )
            row = conn.execute(
                "SELECT * FROM account_halt_state WHERE account_binding_ref=?",
                (account_ref,),
            ).fetchone()
            if row is None:  # pragma: no cover - transaction invariant
                raise AccountHaltError("re-attested account HALT row disappeared")
            result = self._snapshot_from_row(row)
            conn.commit()
            return result
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()
            held.release()

    def finalize_account_halt(
        self,
        account_binding_ref: str,
        owner_user_id: str,
        *,
        expected_epoch: int,
        flat_proof_ref: str,
    ) -> AccountHaltSnapshot:
        """Complete one drained account after a fresh zero-exposure proof."""

        account_ref = self._clean_required(account_binding_ref, field="account_binding_ref")
        owner = self._clean_required(owner_user_id, field="owner_user_id")
        epoch = self._validate_epoch(expected_epoch)
        proof = self._clean_required(flat_proof_ref, field="flat_proof_ref")
        held = self._acquire_raw_fence(
            account_ref,
            timeout=self._drain_timeout_seconds,
        )
        conn = self._conn()
        try:
            conn.execute("BEGIN IMMEDIATE")
            _owner_state, owner_epoch = self._require_owner_state(conn, owner)
            row = conn.execute(
                "SELECT * FROM account_halt_state WHERE account_binding_ref=?",
                (account_ref,),
            ).fetchone()
            if row is None:
                raise PermissionError("account HALT state disappeared before finalization")
            snapshot = self._snapshot_from_row(row)
            if snapshot.owner_user_id != owner or snapshot.epoch != epoch:
                raise PermissionError("account HALT owner/epoch changed before finalization")
            if not snapshot.halt_ref:
                raise AccountHaltError("account HALT state lacks its operation ref")
            if (
                snapshot.halt_action_name not in _INDIVIDUAL_HALT_ACTIONS
                or snapshot.halt_close_positions is not True
                or _INDIVIDUAL_HALT_ACTIONS[snapshot.halt_action_name] is not True
            ):
                raise AccountHaltError(
                    "individual account HALT is not authorized for close finalization"
                )
            self._require_flat_proof(
                conn,
                proof,
                owner_user_id=owner,
                owner_epoch=owner_epoch,
                account_epochs={account_ref: epoch},
                halt_ref=snapshot.halt_ref,
                close_positions=True,
            )
            if snapshot.state == "halting":
                now = self._now()
                conn.execute(
                    """
                    UPDATE account_halt_state
                    SET state='halted', halted_at_utc=?, flat_proof_ref=?, updated_at_utc=?
                    WHERE account_binding_ref=? AND state='halting' AND epoch=?
                    """,
                    (now, proof, now, account_ref, epoch),
                )
                self._append_event(
                    conn,
                    account_ref=account_ref,
                    owner=owner,
                    from_state="halting",
                    to_state="halted",
                    epoch=epoch,
                    proof_ref=proof,
                    created_at=now,
                )
            elif snapshot.state == "halted":
                if snapshot.flat_proof_ref != proof:
                    raise PermissionError("halted account was finalized by a different flat proof")
            else:
                raise PermissionError("only a halting account can complete account HALT")
            row = conn.execute(
                "SELECT * FROM account_halt_state WHERE account_binding_ref=?",
                (account_ref,),
            ).fetchone()
            if row is None:  # pragma: no cover - transaction invariant
                raise AccountHaltError("account HALT row disappeared after finalization")
            result = self._snapshot_from_row(row)
            conn.commit()
            return result
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()
            held.release()

    def finalize_halt_many(
        self,
        owner_user_id: str,
        account_epochs: Mapping[str, int],
        *,
        flat_proof_ref: str,
    ) -> dict[str, AccountHaltSnapshot]:
        owner = self._clean_required(owner_user_id, field="owner_user_id")
        proof = self._clean_required(flat_proof_ref, field="flat_proof_ref")
        expected = {
            self._clean_required(ref, field="account_binding_ref"): self._validate_epoch(epoch)
            for ref, epoch in account_epochs.items()
        }
        if not expected:
            raise ValueError("account HALT finalization requires at least one account proof")
        now = self._now()
        deadline = time.monotonic() + self._drain_timeout_seconds
        held_fences: list[_HeldAccountFence] = []
        try:
            for account_ref in sorted(expected):
                held_fences.append(
                    self._acquire_raw_fence(
                        account_ref,
                        timeout=max(deadline - time.monotonic(), 0.0),
                    )
                )
        except Exception:
            for fence in reversed(held_fences):
                fence.release()
            raise
        conn = self._conn()
        try:
            conn.execute("BEGIN IMMEDIATE")
            owner_row = conn.execute(
                "SELECT * FROM account_halt_owners WHERE owner_user_id=?",
                (owner,),
            ).fetchone()
            if owner_row is None:
                raise PermissionError("account HALT owner latch is missing")
            owner_state = str(owner_row["state"] or "")
            owner_epoch = self._validate_epoch(owner_row["epoch"], field="owner epoch")
            if owner_state not in {"halting", "halted"}:
                raise PermissionError("account HALT owner latch is not finalizable")
            proof_payload = self._require_flat_proof(
                conn,
                proof,
                owner_user_id=owner,
                owner_epoch=owner_epoch,
                account_epochs=expected,
                close_positions=True,
            )
            if owner_state == "halting":
                if proof_payload["halt_ref"] != str(owner_row["halt_ref"] or "").strip():
                    raise PermissionError(
                        "account HALT finalization proof belongs to a stale owner operation"
                    )
            elif str(owner_row["halt_ref"] or "").strip() != proof:
                raise PermissionError("halted owner was finalized by a different flat proof")
            for account_ref in sorted(expected):
                row = conn.execute(
                    "SELECT * FROM account_halt_state WHERE account_binding_ref=?",
                    (account_ref,),
                ).fetchone()
                if row is None:
                    raise PermissionError("account HALT state disappeared before finalization")
                snapshot = self._snapshot_from_row(row)
                if snapshot.owner_user_id != owner:
                    raise PermissionError("account HALT state belongs to a different owner")
                if snapshot.epoch != expected[account_ref]:
                    raise PermissionError("account HALT epoch changed before finalization")
                if snapshot.state == "halted":
                    if snapshot.flat_proof_ref != proof:
                        raise PermissionError(
                            "halted account was finalized by a different flat proof"
                        )
                    continue
                if snapshot.state != "halting":
                    raise PermissionError("only a halting account can become halted")
                if snapshot.halt_ref != proof_payload["halt_ref"]:
                    raise PermissionError(
                        "account HALT state belongs to a different HALT operation"
                    )
                conn.execute(
                    """
                    UPDATE account_halt_state
                    SET state='halted', halted_at_utc=?, flat_proof_ref=?, updated_at_utc=?
                    WHERE account_binding_ref=? AND state='halting' AND epoch=?
                    """,
                    (now, proof, now, account_ref, snapshot.epoch),
                )
                self._append_event(
                    conn,
                    account_ref=account_ref,
                    owner=owner,
                    from_state="halting",
                    to_state="halted",
                    epoch=snapshot.epoch,
                    proof_ref=proof,
                    created_at=now,
                )
            rows = conn.execute(
                f"SELECT * FROM account_halt_state WHERE account_binding_ref IN ({','.join('?' for _ in expected)})",
                tuple(sorted(expected)),
            ).fetchall()
            result = {row["account_binding_ref"]: self._snapshot_from_row(row) for row in rows}
            unfinished = conn.execute(
                """
                SELECT account_binding_ref, state FROM account_halt_state
                WHERE owner_user_id=? AND execution_enabled=1 AND state!='halted'
                """,
                (owner,),
            ).fetchall()
            if unfinished:
                raise PermissionError("not every owned account has a completed HALT proof")
            prior_halted_rows = conn.execute(
                """
                SELECT * FROM account_halt_state
                WHERE owner_user_id=? AND execution_enabled=1 AND state='halted'
                """,
                (owner,),
            ).fetchall()
            for prior_halted_row in prior_halted_rows:
                prior_halted = self._snapshot_from_row(prior_halted_row)
                if prior_halted.account_binding_ref in expected:
                    continue
                if not prior_halted.flat_proof_ref or not prior_halted.halt_ref:
                    raise AccountHaltError(
                        "owner HALT contains a halted account without durable flat proof"
                    )
                self._require_flat_proof(
                    conn,
                    prior_halted.flat_proof_ref,
                    owner_user_id=owner,
                    account_epochs={prior_halted.account_binding_ref: prior_halted.epoch},
                    halt_ref=prior_halted.halt_ref,
                    close_positions=True,
                )
            if owner_state == "halting":
                conn.execute(
                    """
                    UPDATE account_halt_owners
                    SET state='halted', halt_ref=?, updated_at_utc=?
                    WHERE owner_user_id=? AND state='halting' AND epoch=?
                    """,
                    (proof, now, owner, owner_epoch),
                )
            elif owner_state != "halted":
                raise PermissionError("account HALT owner latch is not finalizable")
            conn.commit()
            return result
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()
            for fence in reversed(held_fences):
                fence.release()

    def finalize_owner_halt_if_complete(
        self,
        owner_user_id: str,
        *,
        proof_ref: str,
    ) -> str:
        """Finalize an owner latch when every enabled account is already halted."""

        owner = self._clean_required(owner_user_id, field="owner_user_id")
        proof = self._clean_required(proof_ref, field="proof_ref")
        conn = self._conn()
        try:
            conn.execute("BEGIN IMMEDIATE")
            owner_state, owner_epoch = self._require_owner_state(conn, owner)
            owner_row = conn.execute(
                "SELECT * FROM account_halt_owners WHERE owner_user_id=?",
                (owner,),
            ).fetchone()
            if owner_row is None:  # pragma: no cover - paired with _require_owner_state.
                raise AccountHaltError("account HALT owner latch disappeared")
            unfinished = conn.execute(
                """
                SELECT 1 FROM account_halt_state
                WHERE owner_user_id=? AND execution_enabled=1 AND state!='halted'
                LIMIT 1
                """,
                (owner,),
            ).fetchone()
            if unfinished is not None:
                raise PermissionError("owner HALT still has unfinished enabled accounts")
            if owner_state == "halting":
                operation_ref = str(owner_row["halt_ref"] or "").strip()
                if not operation_ref:
                    raise AccountHaltError("owner HALT latch lacks its operation ref")
                expected_close = owner_row["halt_close_positions"]
                if type(expected_close) is not int or expected_close not in {0, 1}:
                    raise AccountHaltError("owner HALT latch lacks exact operation intent")
                self._require_flat_proof(
                    conn,
                    proof,
                    owner_user_id=owner,
                    owner_epoch=owner_epoch,
                    account_epochs={},
                    halt_ref=operation_ref,
                    close_positions=bool(expected_close),
                )
                halted_rows = conn.execute(
                    """
                    SELECT * FROM account_halt_state
                    WHERE owner_user_id=? AND execution_enabled=1 AND state='halted'
                    """,
                    (owner,),
                ).fetchall()
                for halted_row in halted_rows:
                    halted_snapshot = self._snapshot_from_row(halted_row)
                    if not halted_snapshot.flat_proof_ref or not halted_snapshot.halt_ref:
                        raise AccountHaltError(
                            "owner HALT contains a halted account without durable flat proof"
                        )
                    self._require_flat_proof(
                        conn,
                        halted_snapshot.flat_proof_ref,
                        owner_user_id=owner,
                        account_epochs={
                            halted_snapshot.account_binding_ref: halted_snapshot.epoch
                        },
                        halt_ref=halted_snapshot.halt_ref,
                        close_positions=True,
                    )
                now = self._now()
                conn.execute(
                    """
                    UPDATE account_halt_owners
                    SET state='halted', halt_ref=?, updated_at_utc=?
                    WHERE owner_user_id=? AND state='halting' AND epoch=?
                    """,
                    (proof, now, owner, owner_epoch),
                )
                owner_state = "halted"
            elif owner_state == "halted":
                if str(owner_row["halt_ref"] or "").strip() != proof:
                    raise PermissionError("halted owner was finalized by a different flat proof")
                proof_row = conn.execute(
                    "SELECT * FROM account_halt_flat_proofs WHERE flat_proof_ref=?",
                    (proof,),
                ).fetchone()
                if proof_row is None:
                    raise PermissionError("halted owner finalization proof is missing")
                proof_payload = self._flat_proof_from_row(proof_row)
                if (
                    proof_payload["owner_user_id"] != owner
                    or proof_payload["owner_epoch"] != owner_epoch
                ):
                    raise PermissionError(
                        "halted owner finalization proof has a stale owner epoch"
                    )
            else:
                raise PermissionError("owner HALT latch is not finalizable")
            conn.commit()
            return owner_state
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def resume(
        self,
        account_binding_ref: str,
        owner_user_id: str,
        *,
        authorization_ref: str,
        enable_execution: bool = False,
    ) -> AccountHaltSnapshot:
        """Re-attest one halted account; execution stays disabled by default.

        An owner may be ``running`` when only one account was individually
        stopped, or after another account from a global HALT was re-attested.
        ``halting`` remains an absolute denial.  Callers that stage external
        follower state use the default and invoke :meth:`enable` only after
        that state is durable.
        """

        account_ref = self._clean_required(account_binding_ref, field="account_binding_ref")
        owner = self._clean_required(owner_user_id, field="owner_user_id")
        proof = self._clean_required(authorization_ref, field="authorization_ref")
        if type(enable_execution) is not bool:
            raise ValueError("account HALT enable_execution must be an exact boolean")
        held = self._acquire_raw_fence(account_ref, timeout=self._drain_timeout_seconds)
        conn = self._conn()
        try:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                "SELECT * FROM account_halt_state WHERE account_binding_ref=?",
                (account_ref,),
            ).fetchone()
            if row is None:
                raise PermissionError("account HALT state is missing")
            snapshot = self._snapshot_from_row(row)
            if snapshot.owner_user_id != owner:
                raise PermissionError("dedicated resume requires an owned account")
            owner_state, owner_epoch = self._require_owner_state(conn, owner)
            if owner_state == "halting":
                raise PermissionError("dedicated resume is denied while the owner HALT is in progress")
            if owner_state not in {"running", "halted"}:
                raise AccountHaltError("account HALT owner latch contains an invalid state")
            resumable_halted = snapshot.state == "halted"
            resumable_disabled = (
                owner_state == "halted"
                and snapshot.state == "running"
                and not snapshot.execution_enabled
            )
            if not (resumable_halted or resumable_disabled):
                raise PermissionError(
                    "dedicated resume requires a halted account or a disabled account under a halted owner"
                )
            epoch = snapshot.epoch + 1
            now = self._now()
            conn.execute(
                """
                UPDATE account_halt_state
                SET state='running', epoch=?, execution_enabled=?,
                    halt_ref=NULL, halt_started_at_utc=NULL,
                    halted_at_utc=NULL, flat_proof_ref=NULL,
                    halt_action_name=NULL, halt_close_positions=NULL,
                    updated_at_utc=?
                WHERE account_binding_ref=? AND state=? AND epoch=?
                """,
                (
                    epoch,
                    int(enable_execution),
                    now,
                    account_ref,
                    snapshot.state,
                    snapshot.epoch,
                ),
            )
            self._append_event(
                conn,
                account_ref=account_ref,
                owner=owner,
                from_state=snapshot.state,
                to_state="running",
                epoch=epoch,
                proof_ref=proof,
                created_at=now,
            )
            conn.execute(
                """
                UPDATE account_halt_owners
                SET state='running', epoch=?, halt_ref=NULL, halt_action_name=NULL,
                    halt_close_positions=NULL, updated_at_utc=?
                WHERE owner_user_id=? AND state=? AND epoch=?
                """,
                (owner_epoch + 1, now, owner, owner_state, owner_epoch),
            )
            row = conn.execute(
                "SELECT * FROM account_halt_state WHERE account_binding_ref=?",
                (account_ref,),
            ).fetchone()
            if row is None:  # pragma: no cover - transaction invariant
                raise AccountHaltError("resumed account HALT row disappeared")
            result = self._snapshot_from_row(row)
            conn.commit()
            return result
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()
            held.release()


__all__ = [
    "AccountHaltBatch",
    "AccountHaltEvidence",
    "AccountHaltError",
    "AccountHaltOperation",
    "AccountHaltSnapshot",
    "AccountHaltState",
    "PersistentAccountHaltBarrier",
]
