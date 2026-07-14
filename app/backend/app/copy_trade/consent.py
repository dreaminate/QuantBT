"""Persistent, single-use user consent authority for live copy trading."""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
import sqlite3
import stat
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

from ..lineage.ids import canonical_json

if TYPE_CHECKING:
    from ..research_os.execution_boundary import UserRiskChoiceRecord
    from ..research_os.goal_coverage import (
        GoalCoverageDecision,
        GoalEntrypointCoverageRecord,
    )


RISK_CONSENT_ENTRYPOINT_REF = "api:copy_trade.risk_consents.confirm"


class RiskConsentError(PermissionError):
    """A risk-consent record is missing, stale, tampered, or not authorized."""


def _now() -> datetime:
    return datetime.now(UTC)


def _utc(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(str(value))
    except (TypeError, ValueError) as exc:
        raise RiskConsentError("risk consent timestamp is malformed") from exc
    if parsed.tzinfo is None:
        raise RiskConsentError("risk consent timestamp must be timezone-aware")
    return parsed.astimezone(UTC)


def _sha256(value: str | bytes) -> str:
    raw = value if isinstance(value, bytes) else value.encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _json_object(value: str, *, label: str) -> dict[str, Any]:
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError as exc:
        raise RiskConsentError(f"persisted {label} JSON is malformed") from exc
    if not isinstance(parsed, dict):
        raise RiskConsentError(f"persisted {label} payload must be an object")
    return parsed


@dataclass(frozen=True)
class RiskConsentChallenge:
    challenge_ref: str
    owner_user_id: str
    follower_id: str
    master_id: str
    account_binding_ref: str
    credential_binding_ref: str
    subject_ref: str
    runtime_request_ref: str
    risk_profile_ref: str
    source_ip_hash: str
    payload: dict[str, Any]
    status: Literal["issued", "consumed", "expired", "superseded"]
    issued_at_utc: str
    expires_at_utc: str
    consumed_event_ref: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class UserRiskConsentEvent:
    consent_event_ref: str
    challenge_ref: str
    user_risk_choice_ref: str
    owner_user_id: str
    follower_id: str
    master_id: str
    account_binding_ref: str
    credential_binding_ref: str
    subject_ref: str
    runtime_request_ref: str
    risk_profile_ref: str
    auth_factor: Literal["password", "totp", "password+totp"]
    source_ip_hash: str
    payload: dict[str, Any]
    acknowledged_at_utc: str
    activation_deadline_utc: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class UserRiskConsentDecision:
    decision_ref: str
    challenge_ref: str
    consent_event_ref: str
    second_factor_evidence_ref: str
    user_risk_choice: UserRiskChoiceRecord
    source_coverage: GoalEntrypointCoverageRecord


class PersistentUserRiskConsentStore:
    """SQLite source of truth with content identity and an external HMAC key."""

    KEY_VERSION = "user-risk-consent-hmac-v1"

    def __init__(
        self,
        db_path: str | Path,
        *,
        integrity_key: bytes | None = None,
        integrity_key_path: str | Path | None = None,
    ) -> None:
        self._db_path = Path(db_path)
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()
        if integrity_key is not None:
            if len(integrity_key) < 32:
                raise ValueError("risk consent integrity key must contain at least 32 bytes")
            self._integrity_key = bytes(integrity_key)
            self._integrity_key_path: Path | None = None
        else:
            key_path = (
                Path(integrity_key_path)
                if integrity_key_path is not None
                else self._db_path.with_name(f".{self._db_path.name}.risk-consent-hmac.key")
            )
            self._integrity_key_path = key_path
            self._integrity_key: bytes | None = None
            if key_path.exists() or self._has_records():
                self._integrity_key = self._load_or_create_key(key_path)

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self._db_path), isolation_level=None, timeout=30.0)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_schema(self) -> None:
        conn = self._conn()
        try:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS ct_user_risk_consent_challenges (
                    challenge_ref TEXT PRIMARY KEY,
                    owner_user_id TEXT NOT NULL,
                    follower_id TEXT NOT NULL,
                    master_id TEXT NOT NULL,
                    account_binding_ref TEXT NOT NULL,
                    credential_binding_ref TEXT NOT NULL,
                    subject_ref TEXT NOT NULL,
                    runtime_request_ref TEXT NOT NULL,
                    risk_profile_ref TEXT NOT NULL,
                    source_ip_hash TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    payload_hash TEXT NOT NULL,
                    challenge_nonce TEXT NOT NULL,
                    integrity_key_version TEXT NOT NULL,
                    integrity_seal TEXT NOT NULL,
                    status TEXT NOT NULL
                        CHECK(status IN ('issued','consumed','expired','superseded')),
                    issued_at_utc TEXT NOT NULL,
                    expires_at_utc TEXT NOT NULL,
                    consumed_event_ref TEXT UNIQUE
                );
                CREATE UNIQUE INDEX IF NOT EXISTS idx_ct_one_issued_consent_challenge
                    ON ct_user_risk_consent_challenges(owner_user_id, follower_id)
                    WHERE status='issued';

                CREATE TABLE IF NOT EXISTS ct_user_risk_consent_events (
                    seq INTEGER PRIMARY KEY AUTOINCREMENT,
                    consent_event_ref TEXT NOT NULL UNIQUE,
                    challenge_ref TEXT NOT NULL UNIQUE,
                    user_risk_choice_ref TEXT NOT NULL,
                    owner_user_id TEXT NOT NULL,
                    follower_id TEXT NOT NULL,
                    master_id TEXT NOT NULL,
                    account_binding_ref TEXT NOT NULL,
                    credential_binding_ref TEXT NOT NULL,
                    subject_ref TEXT NOT NULL,
                    runtime_request_ref TEXT NOT NULL,
                    risk_profile_ref TEXT NOT NULL,
                    auth_factor TEXT NOT NULL
                        CHECK(auth_factor IN ('password','totp','password+totp')),
                    source_ip_hash TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    payload_hash TEXT NOT NULL,
                    integrity_key_version TEXT NOT NULL,
                    integrity_seal TEXT NOT NULL,
                    acknowledged_at_utc TEXT NOT NULL,
                    activation_deadline_utc TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS ct_user_risk_consent_decisions (
                    seq INTEGER PRIMARY KEY AUTOINCREMENT,
                    decision_ref TEXT NOT NULL UNIQUE,
                    challenge_ref TEXT NOT NULL UNIQUE,
                    consent_event_ref TEXT NOT NULL UNIQUE,
                    user_risk_choice_ref TEXT NOT NULL,
                    source_coverage_ref TEXT NOT NULL UNIQUE,
                    owner_user_id TEXT NOT NULL,
                    follower_id TEXT NOT NULL,
                    master_id TEXT NOT NULL,
                    runtime_request_ref TEXT NOT NULL,
                    decision_json TEXT NOT NULL,
                    decision_hash TEXT NOT NULL,
                    integrity_key_version TEXT NOT NULL,
                    integrity_seal TEXT NOT NULL,
                    committed_at_utc TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_ct_risk_consent_decision_owner
                    ON ct_user_risk_consent_decisions(
                        owner_user_id,follower_id,runtime_request_ref,seq
                    );
                """
            )
            self._migrate_reconfirmable_decisions(conn)
        finally:
            conn.close()

    @staticmethod
    def _migrate_reconfirmable_decisions(conn: sqlite3.Connection) -> None:
        """Remove the early one-decision-per-choice constraint without data loss."""

        needs_migration = False
        for index in conn.execute(
            "PRAGMA index_list('ct_user_risk_consent_decisions')"
        ).fetchall():
            if not bool(index["unique"]):
                continue
            index_name = str(index["name"]).replace("'", "''")
            columns = tuple(
                str(row["name"])
                for row in conn.execute(
                    f"PRAGMA index_info('{index_name}')"
                ).fetchall()
            )
            if columns == ("user_risk_choice_ref",):
                needs_migration = True
                break
        if not needs_migration:
            return
        conn.executescript(
            """
            BEGIN IMMEDIATE;
            ALTER TABLE ct_user_risk_consent_decisions
                RENAME TO ct_user_risk_consent_decisions_one_per_choice;
            CREATE TABLE ct_user_risk_consent_decisions (
                seq INTEGER PRIMARY KEY AUTOINCREMENT,
                decision_ref TEXT NOT NULL UNIQUE,
                challenge_ref TEXT NOT NULL UNIQUE,
                consent_event_ref TEXT NOT NULL UNIQUE,
                user_risk_choice_ref TEXT NOT NULL,
                source_coverage_ref TEXT NOT NULL UNIQUE,
                owner_user_id TEXT NOT NULL,
                follower_id TEXT NOT NULL,
                master_id TEXT NOT NULL,
                runtime_request_ref TEXT NOT NULL,
                decision_json TEXT NOT NULL,
                decision_hash TEXT NOT NULL,
                integrity_key_version TEXT NOT NULL,
                integrity_seal TEXT NOT NULL,
                committed_at_utc TEXT NOT NULL
            );
            INSERT INTO ct_user_risk_consent_decisions (
                seq,decision_ref,challenge_ref,consent_event_ref,user_risk_choice_ref,
                source_coverage_ref,owner_user_id,follower_id,master_id,
                runtime_request_ref,decision_json,decision_hash,integrity_key_version,
                integrity_seal,committed_at_utc
            )
            SELECT
                seq,decision_ref,challenge_ref,consent_event_ref,user_risk_choice_ref,
                source_coverage_ref,owner_user_id,follower_id,master_id,
                runtime_request_ref,decision_json,decision_hash,integrity_key_version,
                integrity_seal,committed_at_utc
            FROM ct_user_risk_consent_decisions_one_per_choice;
            DROP TABLE ct_user_risk_consent_decisions_one_per_choice;
            CREATE INDEX idx_ct_risk_consent_decision_owner
                ON ct_user_risk_consent_decisions(
                    owner_user_id,follower_id,runtime_request_ref,seq
                );
            COMMIT;
            """
        )

    @property
    def db_path(self) -> Path:
        return self._db_path

    def _has_records(self) -> bool:
        conn = self._conn()
        try:
            return any(
                conn.execute(f"SELECT 1 FROM {table} LIMIT 1").fetchone() is not None
                for table in (
                    "ct_user_risk_consent_challenges",
                    "ct_user_risk_consent_events",
                    "ct_user_risk_consent_decisions",
                )
            )
        finally:
            conn.close()

    def _load_or_create_key(self, path: Path) -> bytes:
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            info = path.lstat()
        except FileNotFoundError:
            if self._has_records():
                raise RuntimeError(
                    "persisted risk consent evidence exists but its integrity key is missing"
                )
            raw = secrets.token_bytes(32)
            flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
            try:
                fd = os.open(str(path), flags, 0o600)
            except FileExistsError:
                return self._load_or_create_key(path)
            try:
                os.write(fd, raw)
                os.fsync(fd)
            finally:
                os.close(fd)
            if os.name != "nt":
                directory_fd = os.open(str(path.parent), os.O_RDONLY)
                try:
                    os.fsync(directory_fd)
                finally:
                    os.close(directory_fd)
            return raw
        if not stat.S_ISREG(info.st_mode) or stat.S_ISLNK(info.st_mode):
            raise RuntimeError("risk consent integrity key path is not a regular file")
        if os.name != "nt" and stat.S_IMODE(info.st_mode) & 0o077:
            raise RuntimeError("risk consent integrity key permissions are too broad")
        raw = path.read_bytes()
        if len(raw) < 32:
            raise RuntimeError("risk consent integrity key is invalid")
        return raw

    def _owner_key(self, owner_user_id: str) -> bytes:
        if self._integrity_key is None:
            if self._integrity_key_path is None:
                raise RuntimeError("risk consent integrity key is unavailable")
            self._integrity_key = self._load_or_create_key(self._integrity_key_path)
        return hmac.new(
            self._integrity_key,
            b"QuantBT/user-risk-consent/v1/" + owner_user_id.encode("utf-8"),
            hashlib.sha256,
        ).digest()

    def _seal(self, owner_user_id: str, payload: dict[str, Any]) -> str:
        return hmac.new(
            self._owner_key(owner_user_id),
            canonical_json(payload).encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()

    @staticmethod
    def source_ip_hash(source_ip: str) -> str:
        return "risk-consent-source-v1-" + _sha256(str(source_ip or ""))

    @staticmethod
    def _required(value: str, label: str) -> str:
        normalized = str(value or "").strip()
        if not normalized:
            raise RiskConsentError(f"risk consent requires {label}")
        return normalized

    def _challenge_identity(
        self,
        *,
        owner_user_id: str,
        follower_id: str,
        master_id: str,
        account_binding_ref: str,
        credential_binding_ref: str,
        subject_ref: str,
        runtime_request_ref: str,
        risk_profile_ref: str,
        source_ip_hash: str,
        payload: dict[str, Any],
        challenge_nonce: str,
        issued_at_utc: str,
        expires_at_utc: str,
    ) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "record_type": "copy_trade_risk_consent_challenge",
            "owner_user_id": owner_user_id,
            "follower_id": follower_id,
            "master_id": master_id,
            "account_binding_ref": account_binding_ref,
            "credential_binding_ref": credential_binding_ref,
            "subject_ref": subject_ref,
            "runtime_request_ref": runtime_request_ref,
            "risk_profile_ref": risk_profile_ref,
            "source_ip_hash": source_ip_hash,
            "payload": payload,
            "challenge_nonce": challenge_nonce,
            "issued_at_utc": issued_at_utc,
            "expires_at_utc": expires_at_utc,
        }

    def issue_challenge(
        self,
        *,
        owner_user_id: str,
        follower_id: str,
        master_id: str,
        account_binding_ref: str,
        credential_binding_ref: str,
        subject_ref: str,
        runtime_request_ref: str,
        risk_profile_ref: str,
        source_ip_hash: str,
        payload: dict[str, Any],
        ttl_seconds: int = 600,
    ) -> RiskConsentChallenge:
        if type(ttl_seconds) is not int or not 60 <= ttl_seconds <= 900:
            raise ValueError("risk consent challenge ttl_seconds must be in [60, 900]")
        values = {
            name: self._required(value, name)
            for name, value in {
                "owner_user_id": owner_user_id,
                "follower_id": follower_id,
                "master_id": master_id,
                "account_binding_ref": account_binding_ref,
                "credential_binding_ref": credential_binding_ref,
                "subject_ref": subject_ref,
                "runtime_request_ref": runtime_request_ref,
                "risk_profile_ref": risk_profile_ref,
                "source_ip_hash": source_ip_hash,
            }.items()
        }
        if not isinstance(payload, dict) or not payload:
            raise RiskConsentError("risk consent challenge payload is required")
        issued = _now()
        issued_at = issued.isoformat()
        expires_at = (issued + timedelta(seconds=ttl_seconds)).isoformat()
        nonce = secrets.token_hex(32)
        identity = self._challenge_identity(
            **values,
            payload=payload,
            challenge_nonce=nonce,
            issued_at_utc=issued_at,
            expires_at_utc=expires_at,
        )
        challenge_ref = "copy_trade_risk_consent_challenge_v1_" + _sha256(
            canonical_json(identity)
        )
        payload_json = canonical_json(payload)
        payload_hash = _sha256(payload_json)
        seal_payload = {
            "challenge_ref": challenge_ref,
            "payload_hash": payload_hash,
            "identity": identity,
            "integrity_key_version": self.KEY_VERSION,
        }
        seal = self._seal(values["owner_user_id"], seal_payload)
        conn = self._conn()
        try:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute(
                "UPDATE ct_user_risk_consent_challenges SET status='superseded' "
                "WHERE owner_user_id=? AND follower_id=? AND status='issued'",
                (values["owner_user_id"], values["follower_id"]),
            )
            conn.execute(
                """
                INSERT INTO ct_user_risk_consent_challenges (
                    challenge_ref,owner_user_id,follower_id,master_id,account_binding_ref,
                    credential_binding_ref,subject_ref,runtime_request_ref,risk_profile_ref,
                    source_ip_hash,payload_json,payload_hash,challenge_nonce,
                    integrity_key_version,integrity_seal,status,issued_at_utc,expires_at_utc,
                    consumed_event_ref
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,'issued',?,?,NULL)
                """,
                (
                    challenge_ref,
                    values["owner_user_id"],
                    values["follower_id"],
                    values["master_id"],
                    values["account_binding_ref"],
                    values["credential_binding_ref"],
                    values["subject_ref"],
                    values["runtime_request_ref"],
                    values["risk_profile_ref"],
                    values["source_ip_hash"],
                    payload_json,
                    payload_hash,
                    nonce,
                    self.KEY_VERSION,
                    seal,
                    issued_at,
                    expires_at,
                ),
            )
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()
        return self.challenge_for_owner(challenge_ref, values["owner_user_id"])

    def _challenge_from_row(self, row: sqlite3.Row) -> RiskConsentChallenge:
        payload = _json_object(str(row["payload_json"]), label="risk consent challenge")
        payload_json = canonical_json(payload)
        if not hmac.compare_digest(str(row["payload_hash"]), _sha256(payload_json)):
            raise RiskConsentError("risk consent challenge payload hash mismatch")
        identity = self._challenge_identity(
            owner_user_id=str(row["owner_user_id"]),
            follower_id=str(row["follower_id"]),
            master_id=str(row["master_id"]),
            account_binding_ref=str(row["account_binding_ref"]),
            credential_binding_ref=str(row["credential_binding_ref"]),
            subject_ref=str(row["subject_ref"]),
            runtime_request_ref=str(row["runtime_request_ref"]),
            risk_profile_ref=str(row["risk_profile_ref"]),
            source_ip_hash=str(row["source_ip_hash"]),
            payload=payload,
            challenge_nonce=str(row["challenge_nonce"]),
            issued_at_utc=str(row["issued_at_utc"]),
            expires_at_utc=str(row["expires_at_utc"]),
        )
        expected_ref = "copy_trade_risk_consent_challenge_v1_" + _sha256(
            canonical_json(identity)
        )
        if not hmac.compare_digest(str(row["challenge_ref"]), expected_ref):
            raise RiskConsentError("risk consent challenge content identity mismatch")
        if str(row["integrity_key_version"]) != self.KEY_VERSION:
            raise RiskConsentError("risk consent challenge integrity key version is unsupported")
        seal_payload = {
            "challenge_ref": expected_ref,
            "payload_hash": str(row["payload_hash"]),
            "identity": identity,
            "integrity_key_version": self.KEY_VERSION,
        }
        expected_seal = self._seal(str(row["owner_user_id"]), seal_payload)
        if not hmac.compare_digest(str(row["integrity_seal"]), expected_seal):
            raise RiskConsentError("risk consent challenge integrity seal mismatch")
        issued_at = _utc(str(row["issued_at_utc"]))
        expires_at = _utc(str(row["expires_at_utc"]))
        if expires_at <= issued_at:
            raise RiskConsentError("risk consent challenge expiry is invalid")
        status = str(row["status"])
        if status not in {"issued", "consumed", "expired", "superseded"}:
            raise RiskConsentError("risk consent challenge status is invalid")
        return RiskConsentChallenge(
            challenge_ref=expected_ref,
            owner_user_id=str(row["owner_user_id"]),
            follower_id=str(row["follower_id"]),
            master_id=str(row["master_id"]),
            account_binding_ref=str(row["account_binding_ref"]),
            credential_binding_ref=str(row["credential_binding_ref"]),
            subject_ref=str(row["subject_ref"]),
            runtime_request_ref=str(row["runtime_request_ref"]),
            risk_profile_ref=str(row["risk_profile_ref"]),
            source_ip_hash=str(row["source_ip_hash"]),
            payload=payload,
            status=status,  # type: ignore[arg-type]
            issued_at_utc=str(row["issued_at_utc"]),
            expires_at_utc=str(row["expires_at_utc"]),
            consumed_event_ref=str(row["consumed_event_ref"] or ""),
        )

    def challenge_for_owner(self, challenge_ref: str, owner_user_id: str) -> RiskConsentChallenge:
        conn = self._conn()
        try:
            row = conn.execute(
                "SELECT * FROM ct_user_risk_consent_challenges WHERE challenge_ref=?",
                (str(challenge_ref or ""),),
            ).fetchone()
        finally:
            conn.close()
        if row is None:
            raise RiskConsentError("risk consent challenge is unknown")
        challenge = self._challenge_from_row(row)
        if challenge.owner_user_id != str(owner_user_id or ""):
            raise RiskConsentError("risk consent challenge belongs to a different owner")
        return challenge

    def _event_identity(
        self,
        *,
        challenge_ref: str,
        user_risk_choice_ref: str,
        owner_user_id: str,
        follower_id: str,
        master_id: str,
        account_binding_ref: str,
        credential_binding_ref: str,
        subject_ref: str,
        runtime_request_ref: str,
        risk_profile_ref: str,
        auth_factor: str,
        source_ip_hash: str,
        payload: dict[str, Any],
        acknowledged_at_utc: str,
        activation_deadline_utc: str,
    ) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "record_type": "copy_trade_user_risk_consent_event",
            "challenge_ref": challenge_ref,
            "user_risk_choice_ref": user_risk_choice_ref,
            "owner_user_id": owner_user_id,
            "follower_id": follower_id,
            "master_id": master_id,
            "account_binding_ref": account_binding_ref,
            "credential_binding_ref": credential_binding_ref,
            "subject_ref": subject_ref,
            "runtime_request_ref": runtime_request_ref,
            "risk_profile_ref": risk_profile_ref,
            "auth_factor": auth_factor,
            "source_ip_hash": source_ip_hash,
            "payload": payload,
            "acknowledged_at_utc": acknowledged_at_utc,
            "activation_deadline_utc": activation_deadline_utc,
        }

    def _event_from_row(self, row: sqlite3.Row) -> UserRiskConsentEvent:
        payload = _json_object(str(row["payload_json"]), label="risk consent event")
        payload_json = canonical_json(payload)
        if not hmac.compare_digest(str(row["payload_hash"]), _sha256(payload_json)):
            raise RiskConsentError("risk consent event payload hash mismatch")
        identity = self._event_identity(
            challenge_ref=str(row["challenge_ref"]),
            user_risk_choice_ref=str(row["user_risk_choice_ref"]),
            owner_user_id=str(row["owner_user_id"]),
            follower_id=str(row["follower_id"]),
            master_id=str(row["master_id"]),
            account_binding_ref=str(row["account_binding_ref"]),
            credential_binding_ref=str(row["credential_binding_ref"]),
            subject_ref=str(row["subject_ref"]),
            runtime_request_ref=str(row["runtime_request_ref"]),
            risk_profile_ref=str(row["risk_profile_ref"]),
            auth_factor=str(row["auth_factor"]),
            source_ip_hash=str(row["source_ip_hash"]),
            payload=payload,
            acknowledged_at_utc=str(row["acknowledged_at_utc"]),
            activation_deadline_utc=str(row["activation_deadline_utc"]),
        )
        expected_ref = "copy_trade_user_risk_consent_event_v1_" + _sha256(
            canonical_json(identity)
        )
        if not hmac.compare_digest(str(row["consent_event_ref"]), expected_ref):
            raise RiskConsentError("risk consent event content identity mismatch")
        if str(row["integrity_key_version"]) != self.KEY_VERSION:
            raise RiskConsentError("risk consent event integrity key version is unsupported")
        seal_payload = {
            "consent_event_ref": expected_ref,
            "payload_hash": str(row["payload_hash"]),
            "identity": identity,
            "integrity_key_version": self.KEY_VERSION,
        }
        expected_seal = self._seal(str(row["owner_user_id"]), seal_payload)
        if not hmac.compare_digest(str(row["integrity_seal"]), expected_seal):
            raise RiskConsentError("risk consent event integrity seal mismatch")
        acknowledged = _utc(str(row["acknowledged_at_utc"]))
        deadline = _utc(str(row["activation_deadline_utc"]))
        if deadline <= acknowledged:
            raise RiskConsentError("risk consent event activation deadline is invalid")
        auth_factor = str(row["auth_factor"])
        if auth_factor not in {"password", "totp", "password+totp"}:
            raise RiskConsentError("risk consent event auth factor is invalid")
        return UserRiskConsentEvent(
            consent_event_ref=expected_ref,
            challenge_ref=str(row["challenge_ref"]),
            user_risk_choice_ref=str(row["user_risk_choice_ref"]),
            owner_user_id=str(row["owner_user_id"]),
            follower_id=str(row["follower_id"]),
            master_id=str(row["master_id"]),
            account_binding_ref=str(row["account_binding_ref"]),
            credential_binding_ref=str(row["credential_binding_ref"]),
            subject_ref=str(row["subject_ref"]),
            runtime_request_ref=str(row["runtime_request_ref"]),
            risk_profile_ref=str(row["risk_profile_ref"]),
            auth_factor=auth_factor,  # type: ignore[arg-type]
            source_ip_hash=str(row["source_ip_hash"]),
            payload=payload,
            acknowledged_at_utc=str(row["acknowledged_at_utc"]),
            activation_deadline_utc=str(row["activation_deadline_utc"]),
        )

    def _event_by_ref(
        self,
        conn: sqlite3.Connection,
        consent_event_ref: str,
    ) -> UserRiskConsentEvent:
        row = conn.execute(
            "SELECT * FROM ct_user_risk_consent_events WHERE consent_event_ref=?",
            (str(consent_event_ref or ""),),
        ).fetchone()
        if row is None:
            raise RiskConsentError("risk consent event is unknown")
        return self._event_from_row(row)

    def _decision_document(
        self,
        event: UserRiskConsentEvent,
        choice: UserRiskChoiceRecord,
    ) -> dict[str, Any]:
        from ..research_os.execution_boundary import validate_user_risk_choice
        from ..research_os.goal_coverage import (
            GoalEntrypointCoverageRecord,
            goal_entrypoint_coverage_identity,
            validate_goal_entrypoint_coverage,
        )

        choice_decision = validate_user_risk_choice(choice)
        if not choice_decision.accepted:
            codes = ",".join(item.code for item in choice_decision.violations)
            raise RiskConsentError(f"risk consent decision has an invalid choice: {codes}")
        exact_bindings = {
            "user_risk_choice_ref": choice.choice_ref,
            "owner_user_id": choice.owner_user_id,
            "follower_id": choice.follower_id,
            "master_id": choice.master_id,
            "account_binding_ref": choice.account_binding_ref,
            "subject_ref": choice.subject_ref,
            "runtime_request_ref": choice.runtime_request_ref,
            "risk_profile_ref": choice.risk_disclosure_profile_ref,
        }
        for field_name, expected in exact_bindings.items():
            if str(getattr(event, field_name) or "") != str(expected or ""):
                raise RiskConsentError(
                    f"risk consent decision {field_name} does not match its choice"
                )
        if event.payload.get("user_risk_choice") != choice.to_dict():
            raise RiskConsentError("risk consent event does not contain the exact choice")
        challenge_payload = event.payload.get("challenge_payload")
        if not isinstance(challenge_payload, dict):
            raise RiskConsentError("risk consent event is missing its challenge payload")
        if challenge_payload.get("proposed_user_risk_choice") != choice.to_dict():
            raise RiskConsentError("risk consent challenge did not present the exact choice")

        second_factor_payload = {
            "schema_version": 1,
            "record_type": "copy_trade_server_verified_second_factor",
            "owner_user_id": event.owner_user_id,
            "challenge_ref": event.challenge_ref,
            "consent_event_ref": event.consent_event_ref,
            "account_binding_ref": event.account_binding_ref,
            "credential_binding_ref": event.credential_binding_ref,
            "auth_factor": event.auth_factor,
            "acknowledged_at_utc": event.acknowledged_at_utc,
        }
        second_factor_ref = "copy_trade_second_factor_evidence_v1_" + _sha256(
            canonical_json(second_factor_payload)
        )
        lineage_seed = _sha256(
            canonical_json(
                {
                    "event": event.to_dict(),
                    "choice": choice.to_dict(),
                    "second_factor_evidence_ref": second_factor_ref,
                    "entrypoint_ref": RISK_CONSENT_ENTRYPOINT_REF,
                }
            )
        )
        qro_ref = f"copy_trade_risk_consent_qro_v1_{lineage_seed}"
        graph_ref = f"copy_trade_risk_consent_graph_command_v1_{lineage_seed}"
        compiler_ir_ref = f"copy_trade_risk_consent_compiler_ir_v1_{lineage_seed}"
        compiler_pass_ref = f"copy_trade_risk_consent_compiler_pass_v1_{lineage_seed}"
        validation_ref = f"goal_validation_receipt:risk_consent:{lineage_seed}"
        replay_ref = f"copy_trade_risk_consent_replay_guard_v1_{lineage_seed}"
        source_coverage = GoalEntrypointCoverageRecord(
            coverage_ref="",
            entry_source="api",
            entrypoint_ref=RISK_CONSENT_ENTRYPOINT_REF,
            goal_sections=("§12",),
            qro_refs=(qro_ref,),
            research_graph_command_refs=(graph_ref,),
            compiler_ir_refs=(compiler_ir_ref,),
            compiler_pass_refs=(compiler_pass_ref,),
            evidence_refs=(
                choice.choice_ref,
                event.consent_event_ref,
                event.challenge_ref,
                event.runtime_request_ref,
                event.account_binding_ref,
                event.credential_binding_ref,
                event.risk_profile_ref,
                second_factor_ref,
            ),
            validation_refs=(validation_ref,),
            permission_refs=(
                second_factor_ref,
                event.account_binding_ref,
                event.credential_binding_ref,
            ),
            replay_refs=(event.challenge_ref, event.consent_event_ref, replay_ref),
            canonical_command_refs=(choice.choice_ref,),
            recorded_by=event.owner_user_id,
            claims_full_product_entrypoint=False,
            silent_mock_fallback_used=False,
            raw_payload_persisted=False,
        )
        source_coverage = GoalEntrypointCoverageRecord(
            **{
                **asdict(source_coverage),
                "coverage_ref": goal_entrypoint_coverage_identity(
                    entry_source=source_coverage.entry_source,
                    entrypoint_ref=source_coverage.entrypoint_ref,
                    goal_sections=source_coverage.goal_sections,
                    qro_refs=source_coverage.qro_refs,
                    research_graph_command_refs=source_coverage.research_graph_command_refs,
                    compiler_ir_refs=source_coverage.compiler_ir_refs,
                    compiler_pass_refs=source_coverage.compiler_pass_refs,
                ),
            }
        )
        coverage_decision = validate_goal_entrypoint_coverage(source_coverage)
        if not coverage_decision.accepted:
            codes = ",".join(item.code for item in coverage_decision.violations)
            raise RiskConsentError(f"risk consent source coverage is invalid: {codes}")
        unsigned = {
            "schema_version": 1,
            "record_type": "copy_trade_user_risk_consent_decision",
            "challenge_ref": event.challenge_ref,
            "consent_event_ref": event.consent_event_ref,
            "second_factor_evidence_ref": second_factor_ref,
            "user_risk_choice": choice.to_dict(),
            "source_coverage": asdict(source_coverage),
            "source_lineage": {
                "qro": {"ref": qro_ref, "choice_ref": choice.choice_ref},
                "research_graph_command": {
                    "ref": graph_ref,
                    "qro_ref": qro_ref,
                    "consent_event_ref": event.consent_event_ref,
                },
                "compiler_ir": {
                    "ref": compiler_ir_ref,
                    "research_graph_command_ref": graph_ref,
                    "runtime_request_ref": event.runtime_request_ref,
                },
                "compiler_pass": {
                    "ref": compiler_pass_ref,
                    "compiler_ir_ref": compiler_ir_ref,
                    "validation_ref": validation_ref,
                },
                "second_factor": {
                    **second_factor_payload,
                    "ref": second_factor_ref,
                },
            },
            "committed_at_utc": event.acknowledged_at_utc,
        }
        return {
            **unsigned,
            "decision_ref": "copy_trade_risk_consent_decision_v1_"
            + _sha256(canonical_json(unsigned)),
        }

    def _decision_from_row(
        self,
        conn: sqlite3.Connection,
        row: sqlite3.Row,
    ) -> UserRiskConsentDecision:
        from ..research_os.execution_boundary import user_risk_choice_from_dict
        from ..research_os.goal_coverage import goal_entrypoint_coverage_record_from_dict

        document = _json_object(str(row["decision_json"]), label="risk consent decision")
        document_json = canonical_json(document)
        if not hmac.compare_digest(str(row["decision_hash"]), _sha256(document_json)):
            raise RiskConsentError("risk consent decision payload hash mismatch")
        raw_choice = document.get("user_risk_choice")
        if not isinstance(raw_choice, dict):
            raise RiskConsentError("risk consent decision is missing its exact choice")
        choice = user_risk_choice_from_dict(raw_choice)
        event = self._event_by_ref(conn, str(row["consent_event_ref"]))
        expected = self._decision_document(event, choice)
        if canonical_json(document) != canonical_json(expected):
            raise RiskConsentError("risk consent decision content identity mismatch")
        redundant = {
            "decision_ref": expected["decision_ref"],
            "challenge_ref": event.challenge_ref,
            "consent_event_ref": event.consent_event_ref,
            "user_risk_choice_ref": choice.choice_ref,
            "source_coverage_ref": expected["source_coverage"]["coverage_ref"],
            "owner_user_id": event.owner_user_id,
            "follower_id": event.follower_id,
            "master_id": event.master_id,
            "runtime_request_ref": event.runtime_request_ref,
            "committed_at_utc": event.acknowledged_at_utc,
        }
        for field_name, expected_value in redundant.items():
            if str(row[field_name]) != str(expected_value):
                raise RiskConsentError(
                    f"risk consent decision {field_name} envelope mismatch"
                )
        if str(row["integrity_key_version"]) != self.KEY_VERSION:
            raise RiskConsentError("risk consent decision integrity key version is unsupported")
        seal_payload = {
            "decision_ref": expected["decision_ref"],
            "decision_hash": str(row["decision_hash"]),
            "decision": expected,
            "integrity_key_version": self.KEY_VERSION,
        }
        expected_seal = self._seal(event.owner_user_id, seal_payload)
        if not hmac.compare_digest(str(row["integrity_seal"]), expected_seal):
            raise RiskConsentError("risk consent decision integrity seal mismatch")
        challenge_row = conn.execute(
            "SELECT * FROM ct_user_risk_consent_challenges WHERE challenge_ref=?",
            (event.challenge_ref,),
        ).fetchone()
        if challenge_row is None:
            raise RiskConsentError("risk consent decision challenge is absent")
        challenge = self._challenge_from_row(challenge_row)
        if (
            challenge.status != "consumed"
            or challenge.consumed_event_ref != event.consent_event_ref
        ):
            raise RiskConsentError("risk consent decision is not atomically committed")
        source_coverage = goal_entrypoint_coverage_record_from_dict(
            expected["source_coverage"]
        )
        return UserRiskConsentDecision(
            decision_ref=str(expected["decision_ref"]),
            challenge_ref=event.challenge_ref,
            consent_event_ref=event.consent_event_ref,
            second_factor_evidence_ref=str(expected["second_factor_evidence_ref"]),
            user_risk_choice=choice,
            source_coverage=source_coverage,
        )

    def _insert_decision(
        self,
        conn: sqlite3.Connection,
        event: UserRiskConsentEvent,
        choice: UserRiskChoiceRecord,
    ) -> UserRiskConsentDecision:
        from ..research_os.goal_coverage import goal_entrypoint_coverage_record_from_dict

        document = self._decision_document(event, choice)
        document_json = canonical_json(document)
        document_hash = _sha256(document_json)
        seal_payload = {
            "decision_ref": document["decision_ref"],
            "decision_hash": document_hash,
            "decision": document,
            "integrity_key_version": self.KEY_VERSION,
        }
        seal = self._seal(event.owner_user_id, seal_payload)
        coverage = goal_entrypoint_coverage_record_from_dict(document["source_coverage"])
        conn.execute(
            """
            INSERT INTO ct_user_risk_consent_decisions (
                decision_ref,challenge_ref,consent_event_ref,user_risk_choice_ref,
                source_coverage_ref,owner_user_id,follower_id,master_id,
                runtime_request_ref,decision_json,decision_hash,integrity_key_version,
                integrity_seal,committed_at_utc
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                document["decision_ref"],
                event.challenge_ref,
                event.consent_event_ref,
                choice.choice_ref,
                coverage.coverage_ref,
                event.owner_user_id,
                event.follower_id,
                event.master_id,
                event.runtime_request_ref,
                document_json,
                document_hash,
                self.KEY_VERSION,
                seal,
                event.acknowledged_at_utc,
            ),
        )
        return UserRiskConsentDecision(
            decision_ref=str(document["decision_ref"]),
            challenge_ref=event.challenge_ref,
            consent_event_ref=event.consent_event_ref,
            second_factor_evidence_ref=str(document["second_factor_evidence_ref"]),
            user_risk_choice=choice,
            source_coverage=coverage,
        )

    def _decision_by_event(
        self,
        conn: sqlite3.Connection,
        consent_event_ref: str,
    ) -> UserRiskConsentDecision:
        row = conn.execute(
            "SELECT * FROM ct_user_risk_consent_decisions WHERE consent_event_ref=?",
            (str(consent_event_ref or ""),),
        ).fetchone()
        if row is None:
            raise RiskConsentError("consumed challenge is missing its atomic decision")
        return self._decision_from_row(conn, row)

    @staticmethod
    def _auth_factor(password_verified: bool, totp_verified: bool) -> str:
        if password_verified and totp_verified:
            return "password+totp"
        if password_verified:
            return "password"
        if totp_verified:
            return "totp"
        raise RiskConsentError("risk consent requires a server-verified authentication factor")

    def consume_challenge(
        self,
        *,
        challenge_ref: str,
        owner_user_id: str,
        user_risk_choice_ref: str,
        user_risk_choice: dict[str, Any],
        acknowledged_item_refs: list[str] | tuple[str, ...],
        source_ip_hash: str,
        password_verified: bool,
        totp_verified: bool,
        activation_ttl_seconds: int = 86_400,
    ) -> UserRiskConsentEvent:
        from ..research_os.execution_boundary import (
            user_risk_choice_from_dict,
            validate_user_risk_choice,
        )

        if type(activation_ttl_seconds) is not int or not 600 <= activation_ttl_seconds <= 86_400:
            raise ValueError("risk consent activation ttl must be in [600, 86400]")
        owner = self._required(owner_user_id, "owner_user_id")
        choice_ref = self._required(user_risk_choice_ref, "user_risk_choice_ref")
        if not isinstance(user_risk_choice, dict) or not user_risk_choice:
            raise RiskConsentError("risk consent requires the exact user risk choice payload")
        choice = user_risk_choice_from_dict(user_risk_choice)
        if choice.to_dict() != user_risk_choice or choice.choice_ref != choice_ref:
            raise RiskConsentError("risk consent choice payload is not canonical")
        choice_decision = validate_user_risk_choice(choice)
        if not choice_decision.accepted:
            codes = ",".join(item.code for item in choice_decision.violations)
            raise RiskConsentError(f"risk consent choice is invalid: {codes}")
        refs = tuple(str(item or "").strip() for item in acknowledged_item_refs)
        if any(not item for item in refs) or len(refs) != len(set(refs)):
            raise RiskConsentError("risk consent acknowledgement refs must be unique and nonempty")
        auth_factor = self._auth_factor(password_verified, totp_verified)
        conn = self._conn()
        try:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                "SELECT * FROM ct_user_risk_consent_challenges WHERE challenge_ref=?",
                (str(challenge_ref or ""),),
            ).fetchone()
            if row is None:
                raise RiskConsentError("risk consent challenge is unknown")
            challenge = self._challenge_from_row(row)
            if challenge.owner_user_id != owner:
                raise RiskConsentError("risk consent challenge belongs to a different owner")
            if challenge.source_ip_hash != str(source_ip_hash or ""):
                raise RiskConsentError("risk consent source changed after disclosure presentation")
            required_refs = challenge.payload.get("required_acknowledgement_refs")
            if not isinstance(required_refs, list) or tuple(required_refs) != refs:
                raise RiskConsentError("risk consent acknowledgement refs do not match the presented profile")
            if challenge.payload.get("proposed_user_risk_choice") != user_risk_choice:
                raise RiskConsentError("risk consent choice differs from the presented choice")
            choice_pairs = {
                "choice_ref": choice_ref,
                "owner_user_id": challenge.owner_user_id,
                "follower_id": challenge.follower_id,
                "master_id": challenge.master_id,
                "account_binding_ref": challenge.account_binding_ref,
                "subject_ref": challenge.subject_ref,
                "runtime_request_ref": challenge.runtime_request_ref,
                "risk_disclosure_profile_ref": challenge.risk_profile_ref,
            }
            for field_name, expected in choice_pairs.items():
                if str(user_risk_choice.get(field_name) or "") != expected:
                    raise RiskConsentError(
                        f"risk consent user choice {field_name} does not match its challenge"
                    )
            event_payload = {
                "challenge_payload": challenge.payload,
                "challenge_payload_hash": _sha256(canonical_json(challenge.payload)),
                "acknowledged_item_refs": list(refs),
                "user_risk_choice": user_risk_choice,
            }
            if challenge.status == "consumed":
                if not challenge.consumed_event_ref:
                    raise RiskConsentError("consumed challenge is missing its consent event")
                existing = self._event_by_ref(conn, challenge.consumed_event_ref)
                if (
                    existing.user_risk_choice_ref != choice_ref
                    or existing.auth_factor != auth_factor
                    or existing.source_ip_hash != source_ip_hash
                    or existing.payload != event_payload
                ):
                    raise RiskConsentError("consumed challenge cannot be changed or replayed")
                decision = self._decision_by_event(conn, existing.consent_event_ref)
                if decision.user_risk_choice != choice:
                    raise RiskConsentError("consumed challenge decision cannot be changed")
                conn.commit()
                return existing
            if challenge.status != "issued":
                raise RiskConsentError(f"risk consent challenge is {challenge.status}")
            if _now() > _utc(challenge.expires_at_utc):
                conn.execute(
                    "UPDATE ct_user_risk_consent_challenges SET status='expired' "
                    "WHERE challenge_ref=? AND status='issued'",
                    (challenge.challenge_ref,),
                )
                raise RiskConsentError("risk consent challenge has expired")
            acknowledged = _now()
            acknowledged_at = acknowledged.isoformat()
            deadline = (acknowledged + timedelta(seconds=activation_ttl_seconds)).isoformat()
            identity = self._event_identity(
                challenge_ref=challenge.challenge_ref,
                user_risk_choice_ref=choice_ref,
                owner_user_id=challenge.owner_user_id,
                follower_id=challenge.follower_id,
                master_id=challenge.master_id,
                account_binding_ref=challenge.account_binding_ref,
                credential_binding_ref=challenge.credential_binding_ref,
                subject_ref=challenge.subject_ref,
                runtime_request_ref=challenge.runtime_request_ref,
                risk_profile_ref=challenge.risk_profile_ref,
                auth_factor=auth_factor,
                source_ip_hash=source_ip_hash,
                payload=event_payload,
                acknowledged_at_utc=acknowledged_at,
                activation_deadline_utc=deadline,
            )
            event_ref = "copy_trade_user_risk_consent_event_v1_" + _sha256(
                canonical_json(identity)
            )
            payload_json = canonical_json(event_payload)
            payload_hash = _sha256(payload_json)
            seal_payload = {
                "consent_event_ref": event_ref,
                "payload_hash": payload_hash,
                "identity": identity,
                "integrity_key_version": self.KEY_VERSION,
            }
            seal = self._seal(owner, seal_payload)
            conn.execute(
                """
                INSERT INTO ct_user_risk_consent_events (
                    consent_event_ref,challenge_ref,user_risk_choice_ref,owner_user_id,
                    follower_id,master_id,account_binding_ref,credential_binding_ref,
                    subject_ref,runtime_request_ref,risk_profile_ref,auth_factor,
                    source_ip_hash,payload_json,payload_hash,integrity_key_version,
                    integrity_seal,acknowledged_at_utc,activation_deadline_utc
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    event_ref,
                    challenge.challenge_ref,
                    choice_ref,
                    owner,
                    challenge.follower_id,
                    challenge.master_id,
                    challenge.account_binding_ref,
                    challenge.credential_binding_ref,
                    challenge.subject_ref,
                    challenge.runtime_request_ref,
                    challenge.risk_profile_ref,
                    auth_factor,
                    source_ip_hash,
                    payload_json,
                    payload_hash,
                    self.KEY_VERSION,
                    seal,
                    acknowledged_at,
                    deadline,
                ),
            )
            inserted_event = self._event_by_ref(conn, event_ref)
            self._insert_decision(conn, inserted_event, choice)
            updated = conn.execute(
                "UPDATE ct_user_risk_consent_challenges "
                "SET status='consumed',consumed_event_ref=? "
                "WHERE challenge_ref=? AND status='issued' AND consumed_event_ref IS NULL",
                (event_ref, challenge.challenge_ref),
            )
            if updated.rowcount != 1:
                raise RiskConsentError("risk consent challenge consume CAS failed")
            conn.commit()
            return self._event_by_ref(conn, event_ref)
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def event_for_owner(self, consent_event_ref: str, owner_user_id: str) -> UserRiskConsentEvent:
        conn = self._conn()
        try:
            event = self._event_by_ref(conn, consent_event_ref)
        finally:
            conn.close()
        if event.owner_user_id != str(owner_user_id or ""):
            raise RiskConsentError("risk consent event belongs to a different owner")
        return event

    def decision_for_event(
        self,
        consent_event_ref: str,
        owner_user_id: str,
    ) -> UserRiskConsentDecision:
        owner = self._required(owner_user_id, "owner_user_id")
        conn = self._conn()
        try:
            row = conn.execute(
                "SELECT * FROM ct_user_risk_consent_decisions "
                "WHERE consent_event_ref=? AND owner_user_id=?",
                (str(consent_event_ref or ""), owner),
            ).fetchone()
            if row is None:
                raise RiskConsentError("risk consent decision is unavailable")
            return self._decision_from_row(conn, row)
        finally:
            conn.close()

    def decisions(self, *, owner: str | None = None) -> list[UserRiskConsentDecision]:
        conn = self._conn()
        try:
            if owner is None:
                rows = conn.execute(
                    "SELECT * FROM ct_user_risk_consent_decisions ORDER BY seq"
                ).fetchall()
            else:
                normalized = self._required(owner, "owner_user_id")
                rows = conn.execute(
                    "SELECT * FROM ct_user_risk_consent_decisions "
                    "WHERE owner_user_id=? ORDER BY seq",
                    (normalized,),
                ).fetchall()
            return [self._decision_from_row(conn, row) for row in rows]
        finally:
            conn.close()

    def choices(self, *, owner: str | None = None) -> list[UserRiskChoiceRecord]:
        return [item.user_risk_choice for item in self.decisions(owner=owner)]

    def legacy_choice_is_committed(self, choice: UserRiskChoiceRecord) -> bool:
        """Accept a pre-migration JSONL choice only with its exact consumed event.

        Legacy events remain usable by already-active subscriptions, but they do
        not acquire a source-lineage receipt after the fact and therefore cannot
        satisfy a new section-12 proof.
        """

        from ..research_os.execution_boundary import validate_user_risk_choice

        decision = validate_user_risk_choice(choice)
        if not decision.accepted:
            return False
        conn = self._conn()
        try:
            rows = conn.execute(
                "SELECT * FROM ct_user_risk_consent_events "
                "WHERE user_risk_choice_ref=? AND owner_user_id=? ORDER BY seq",
                (choice.choice_ref, choice.owner_user_id),
            ).fetchall()
            for row in rows:
                event = self._event_from_row(row)
                if event.payload.get("user_risk_choice") != choice.to_dict():
                    continue
                challenge_row = conn.execute(
                    "SELECT * FROM ct_user_risk_consent_challenges WHERE challenge_ref=?",
                    (event.challenge_ref,),
                ).fetchone()
                if challenge_row is None:
                    continue
                challenge = self._challenge_from_row(challenge_row)
                if (
                    challenge.status == "consumed"
                    and challenge.consumed_event_ref == event.consent_event_ref
                ):
                    return True
            return False
        finally:
            conn.close()

    def source_coverage_for_owner(
        self,
        coverage_ref: str,
        owner_user_id: str,
    ) -> GoalEntrypointCoverageRecord:
        owner = self._required(owner_user_id, "owner_user_id")
        conn = self._conn()
        try:
            row = conn.execute(
                "SELECT * FROM ct_user_risk_consent_decisions "
                "WHERE source_coverage_ref=? AND owner_user_id=?",
                (str(coverage_ref or ""), owner),
            ).fetchone()
            if row is None:
                raise KeyError(str(coverage_ref or ""))
            return self._decision_from_row(conn, row).source_coverage
        finally:
            conn.close()

    def source_coverage(
        self,
        coverage_ref: str,
    ) -> GoalEntrypointCoverageRecord:
        conn = self._conn()
        try:
            rows = conn.execute(
                "SELECT * FROM ct_user_risk_consent_decisions WHERE source_coverage_ref=?",
                (str(coverage_ref or ""),),
            ).fetchall()
            if not rows:
                raise KeyError(str(coverage_ref or ""))
            if len(rows) != 1:
                raise RiskConsentError("risk consent source coverage is owner-ambiguous")
            return self._decision_from_row(conn, rows[0]).source_coverage
        finally:
            conn.close()

    def source_coverages(
        self,
        *,
        owner: str | None = None,
    ) -> list[GoalEntrypointCoverageRecord]:
        return [item.source_coverage for item in self.decisions(owner=owner)]

    def validate_source_coverage(
        self,
        record: GoalEntrypointCoverageRecord,
    ) -> GoalCoverageDecision:
        from ..research_os.goal_coverage import (
            GoalCoverageDecision,
            GoalCoverageViolation,
            validate_goal_entrypoint_coverage,
        )

        violations = list(validate_goal_entrypoint_coverage(record).violations)
        try:
            conn = self._conn()
            try:
                row = conn.execute(
                    "SELECT * FROM ct_user_risk_consent_decisions "
                    "WHERE source_coverage_ref=? AND owner_user_id=?",
                    (record.coverage_ref, record.recorded_by),
                ).fetchone()
                if row is None:
                    raise RiskConsentError(
                        "risk consent source coverage is not backed by a committed decision"
                    )
                decision = self._decision_from_row(conn, row)
                if decision.source_coverage != record:
                    raise RiskConsentError("risk consent source coverage payload mismatch")
                latest = conn.execute(
                    "SELECT source_coverage_ref FROM ct_user_risk_consent_decisions "
                    "WHERE owner_user_id=? AND follower_id=? AND runtime_request_ref=? "
                    "ORDER BY seq DESC LIMIT 1",
                    (
                        decision.user_risk_choice.owner_user_id,
                        decision.user_risk_choice.follower_id,
                        decision.user_risk_choice.runtime_request_ref,
                    ),
                ).fetchone()
                if latest is None or str(latest["source_coverage_ref"]) != record.coverage_ref:
                    raise RiskConsentError(
                        "risk consent source coverage was superseded by a newer decision"
                    )
            finally:
                conn.close()
        except (KeyError, RiskConsentError, sqlite3.Error, ValueError) as exc:
            violations.append(
                GoalCoverageViolation(
                    "risk_consent_source_coverage_not_current",
                    str(exc),
                    field="coverage_ref",
                    ref=record.coverage_ref,
                )
            )
        return GoalCoverageDecision(accepted=not violations, violations=tuple(violations))

    def validate_event(
        self,
        *,
        consent_event_ref: str,
        owner_user_id: str,
        follower_id: str,
        master_id: str,
        account_binding_ref: str,
        credential_binding_ref: str,
        runtime_request_ref: str,
        user_risk_choice_ref: str,
        risk_profile_ref: str,
        require_unexpired: bool = True,
    ) -> UserRiskConsentEvent:
        conn = self._conn()
        try:
            return self.validate_event_for_activation(
                conn,
                consent_event_ref=consent_event_ref,
                owner_user_id=owner_user_id,
                follower_id=follower_id,
                master_id=master_id,
                account_binding_ref=account_binding_ref,
                credential_binding_ref=credential_binding_ref,
                runtime_request_ref=runtime_request_ref,
                user_risk_choice_ref=user_risk_choice_ref,
                risk_profile_ref=risk_profile_ref,
                require_unexpired=require_unexpired,
            )
        finally:
            conn.close()

    def validate_event_for_activation(
        self,
        conn: sqlite3.Connection,
        *,
        consent_event_ref: str,
        owner_user_id: str,
        follower_id: str,
        master_id: str,
        account_binding_ref: str,
        credential_binding_ref: str,
        runtime_request_ref: str,
        user_risk_choice_ref: str,
        risk_profile_ref: str,
        require_unexpired: bool = True,
    ) -> UserRiskConsentEvent:
        event = self._event_by_ref(conn, consent_event_ref)
        expected = {
            "owner_user_id": owner_user_id,
            "follower_id": follower_id,
            "master_id": master_id,
            "account_binding_ref": account_binding_ref,
            "credential_binding_ref": credential_binding_ref,
            "runtime_request_ref": runtime_request_ref,
            "user_risk_choice_ref": user_risk_choice_ref,
            "risk_profile_ref": risk_profile_ref,
        }
        for field_name, expected_value in expected.items():
            if str(getattr(event, field_name) or "") != str(expected_value or ""):
                raise RiskConsentError(
                    f"risk consent event {field_name} does not match activation"
                )
        if require_unexpired and _now() > _utc(event.activation_deadline_utc):
            raise RiskConsentError("risk consent event activation deadline has expired")
        return event


__all__ = [
    "PersistentUserRiskConsentStore",
    "RISK_CONSENT_ENTRYPOINT_REF",
    "RiskConsentChallenge",
    "RiskConsentError",
    "UserRiskConsentDecision",
    "UserRiskConsentEvent",
]
