"""Immutable, tenant-owned trading credential version registry.

Secrets remain in ``SecureKeystore``.  This registry stores only ownership,
alias/version metadata, and an opaque broker HMAC binding; it never stores API
keys or secrets.
"""

from __future__ import annotations

import os
import sqlite3
import stat
import threading
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from ..lineage.ids import content_hash


@dataclass(frozen=True)
class TradingCredentialVersion:
    credential_ref: str
    owner_user_id: str
    alias: str
    version: int
    status: str
    credential_binding_ref: str
    created_at_utc: str


class PersistentTradingCredentialRegistry:
    """Append-only credential versions with one current active alias target."""

    def __init__(self, path: str | Path) -> None:
        self._path = Path(path)
        if self._path.parent.exists() and self._path.parent.is_symlink():
            raise ValueError("trading credential directory must not be a symlink")
        self._path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        parent_info = self._path.parent.stat()
        if not stat.S_ISDIR(parent_info.st_mode) or parent_info.st_uid != os.getuid():
            raise ValueError("trading credential directory is not privately owned")
        self._path.parent.chmod(0o700)
        if self._path.exists() and self._path.is_symlink():
            raise ValueError("trading credential database must not be a symlink")
        if not self._path.exists():
            fd = os.open(self._path, os.O_RDWR | os.O_CREAT | os.O_EXCL, 0o600)
            os.close(fd)
        file_info = self._path.stat()
        if not stat.S_ISREG(file_info.st_mode) or file_info.st_uid != os.getuid():
            raise ValueError("trading credential database is not privately owned")
        self._path.chmod(0o600)
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(self._path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS trading_credential_versions (
                credential_ref TEXT PRIMARY KEY,
                owner_user_id TEXT NOT NULL,
                alias TEXT NOT NULL,
                version INTEGER NOT NULL CHECK(version > 0),
                status TEXT NOT NULL CHECK(status IN ('pending','active','retired','failed')),
                credential_binding_ref TEXT NOT NULL DEFAULT '',
                created_at_utc TEXT NOT NULL,
                UNIQUE(owner_user_id, alias, version)
            );
            CREATE INDEX IF NOT EXISTS idx_trading_credential_owner_alias
                ON trading_credential_versions(owner_user_id, alias, version DESC);
            """
        )
        self._conn.commit()

    @property
    def path(self) -> Path:
        return self._path

    @staticmethod
    def _row(row: sqlite3.Row) -> TradingCredentialVersion:
        return TradingCredentialVersion(
            credential_ref=str(row["credential_ref"]),
            owner_user_id=str(row["owner_user_id"]),
            alias=str(row["alias"]),
            version=int(row["version"]),
            status=str(row["status"]),
            credential_binding_ref=str(row["credential_binding_ref"] or ""),
            created_at_utc=str(row["created_at_utc"]),
        )

    def begin_version(self, owner_user_id: str, alias: str) -> TradingCredentialVersion:
        owner = str(owner_user_id or "").strip()
        normalized_alias = str(alias or "").strip()
        if not owner or not normalized_alias:
            raise ValueError("credential owner and alias are required")
        with self._lock:
            self._conn.execute("BEGIN IMMEDIATE")
            try:
                row = self._conn.execute(
                    """
                    SELECT COALESCE(MAX(version), 0) AS version
                    FROM trading_credential_versions
                    WHERE owner_user_id=? AND alias=?
                    """,
                    (owner, normalized_alias),
                ).fetchone()
                version = int(row["version"] or 0) + 1
                credential_ref = "trading_credential_" + content_hash(
                    {
                        "owner_user_id": owner,
                        "alias": normalized_alias,
                        "version": version,
                    }
                )
                created_at = datetime.now(UTC).isoformat()
                self._conn.execute(
                    """
                    INSERT INTO trading_credential_versions(
                        credential_ref, owner_user_id, alias, version, status,
                        credential_binding_ref, created_at_utc
                    ) VALUES(?,?,?,?,?,?,?)
                    """,
                    (credential_ref, owner, normalized_alias, version, "pending", "", created_at),
                )
                self._conn.commit()
            except Exception:
                self._conn.rollback()
                raise
        return self.credential(credential_ref)

    def activate(self, credential_ref: str, credential_binding_ref: str) -> TradingCredentialVersion:
        binding = str(credential_binding_ref or "").strip()
        if not binding:
            raise ValueError("credential binding ref is required")
        with self._lock:
            self._conn.execute("BEGIN IMMEDIATE")
            try:
                row = self._conn.execute(
                    "SELECT * FROM trading_credential_versions WHERE credential_ref=?",
                    (str(credential_ref),),
                ).fetchone()
                if row is None or row["status"] != "pending":
                    raise ValueError("credential version is not pending")
                self._conn.execute(
                    """
                    UPDATE trading_credential_versions
                    SET status='retired'
                    WHERE owner_user_id=? AND alias=? AND status='active'
                    """,
                    (row["owner_user_id"], row["alias"]),
                )
                self._conn.execute(
                    """
                    UPDATE trading_credential_versions
                    SET status='active', credential_binding_ref=?
                    WHERE credential_ref=? AND status='pending'
                    """,
                    (binding, str(credential_ref)),
                )
                self._conn.commit()
            except Exception:
                self._conn.rollback()
                raise
        return self.credential(str(credential_ref))

    def fail_pending(self, credential_ref: str) -> None:
        with self._lock:
            self._conn.execute(
                """
                UPDATE trading_credential_versions SET status='failed'
                WHERE credential_ref=? AND status='pending'
                """,
                (str(credential_ref),),
            )
            self._conn.commit()

    def credential(self, credential_ref: str) -> TradingCredentialVersion:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM trading_credential_versions WHERE credential_ref=?",
                (str(credential_ref),),
            ).fetchone()
        if row is None:
            raise KeyError(str(credential_ref))
        return self._row(row)

    def current(self, owner_user_id: str, alias: str) -> TradingCredentialVersion:
        with self._lock:
            row = self._conn.execute(
                """
                SELECT * FROM trading_credential_versions
                WHERE owner_user_id=? AND alias=? AND status='active'
                ORDER BY version DESC LIMIT 1
                """,
                (str(owner_user_id), str(alias)),
            ).fetchone()
        if row is None:
            raise KeyError(f"unknown trading credential alias: {alias}")
        return self._row(row)

    def aliases(self, owner_user_id: str) -> tuple[str, ...]:
        with self._lock:
            rows = self._conn.execute(
                """
                SELECT DISTINCT alias FROM trading_credential_versions
                WHERE owner_user_id=? AND status='active' ORDER BY alias
                """,
                (str(owner_user_id),),
            ).fetchall()
        return tuple(str(row["alias"]) for row in rows)

    def refs_for_alias(self, owner_user_id: str, alias: str) -> tuple[str, ...]:
        with self._lock:
            rows = self._conn.execute(
                """
                SELECT credential_ref FROM trading_credential_versions
                WHERE owner_user_id=? AND alias=? AND status IN ('active','retired')
                ORDER BY version
                """,
                (str(owner_user_id), str(alias)),
            ).fetchall()
        return tuple(str(row["credential_ref"]) for row in rows)

    def versions(self, *, status: str | None = None) -> tuple[TradingCredentialVersion, ...]:
        if status is not None and status not in {"pending", "active", "retired", "failed"}:
            raise ValueError("unsupported credential status")
        with self._lock:
            if status is None:
                rows = self._conn.execute(
                    "SELECT * FROM trading_credential_versions ORDER BY owner_user_id,alias,version"
                ).fetchall()
            else:
                rows = self._conn.execute(
                    "SELECT * FROM trading_credential_versions WHERE status=? "
                    "ORDER BY owner_user_id,alias,version",
                    (status,),
                ).fetchall()
        return tuple(self._row(row) for row in rows)

    def is_owned(self, owner_user_id: str, credential_ref: str) -> bool:
        try:
            record = self.credential(credential_ref)
        except KeyError:
            return False
        return record.owner_user_id == str(owner_user_id) and record.status in {
            "pending",
            "active",
            "retired",
        }

    def binding_ref(self, owner_user_id: str, credential_ref: str) -> str | None:
        try:
            record = self.credential(credential_ref)
        except KeyError:
            return None
        if record.owner_user_id != str(owner_user_id) or record.status != "active":
            return None
        return record.credential_binding_ref or None


__all__ = ["PersistentTradingCredentialRegistry", "TradingCredentialVersion"]
