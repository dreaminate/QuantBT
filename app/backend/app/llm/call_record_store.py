"""Process-safe, owner-scoped durable sink for sealed ``LLMCallRecord`` rows."""

from __future__ import annotations

import hashlib
import hmac
import json
import math
import os
import secrets
import stat
import threading
from collections import defaultdict
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

from ..cross_process_lock import acquire_exclusive_fd
from ..lineage.ids import canonical_json
from .call_record import (
    CURRENT_LLM_RECORD_SCHEMA_VERSION,
    LEGACY_LLM_RECORD_SCHEMA_VERSION,
    CallRecordKind,
    CallStatus,
    IndependenceRecord,
    LLMCallRecord,
    LLMRecordError,
    assert_legacy_record_loadable,
    assert_record_admissible,
    make_call_id,
    verify_record_seal,
)


# Persist only controlled identifiers, enums, hashes, booleans, timestamps and
# numeric counters. URL/free-text compatibility fields remain in the in-memory
# dataclass but are deliberately absent from durable evidence.
_PERSISTED_FIELDS_V2 = (
    "provider", "model", "auth_ref", "replay_state", "schema_version",
    "owner_user_id", "workflow_id", "invocation_id", "record_kind", "attempt_no",
    "role", "task_difficulty", "risk_level", "tier_requested", "tier_resolved",
    "degraded", "independence", "provider_health", "quota_state", "fallback_used",
    "call_id", "session_id", "prompt_digest", "response_digest", "fixture_key",
    "started_at", "finished_at", "latency_ms", "usage", "status", "error_kind",
    "failure_stage", "repro_level", "seal",
)
_PERSISTED_FIELDS_V3 = _PERSISTED_FIELDS_V2 + (
    "routing_policy_ref", "routing_policy_state", "prompt_hash",
    "tool_schema_hash", "response_ref", "cost",
)
_IDENTIFIER_PUNCTUATION = frozenset("._:@/+=-")
_PROVIDER_PUNCTUATION = frozenset("._-")
_MODEL_PUNCTUATION = frozenset("._:/+-")
_SECRET_REF_PUNCTUATION = frozenset("._-+")
_CHECKPOINT_VERSION = 1


class LLMCallRecordStore:
    """Append-only JSONL store with strict integrity and tenant isolation."""

    def __init__(
        self,
        path: Path | str,
        *,
        seal_secret: bytes | None = None,
        seal_key_path: Path | str | None = None,
    ) -> None:
        self._path = Path(path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._lock_path = self._path.with_name(self._path.name + ".lock")
        self._checkpoint_path = self._path.with_name("." + self._path.name + ".head.json")
        self._claim_dir = self._path.with_name("." + self._path.name + ".invocations")
        self._quarantined_rows = 0
        self._poisoned = False
        if seal_secret is not None and seal_key_path is not None:
            raise ValueError("LLM record seal_secret and seal_key_path are mutually exclusive")
        if seal_secret is not None and len(seal_secret) < 32:
            raise ValueError("LLM record seal secret must contain at least 32 bytes")
        self._seal_secret: bytes | None = bytes(seal_secret) if seal_secret is not None else None
        self._seal_key_path = (
            None
            if seal_secret is not None
            else (
                Path(seal_key_path)
                if seal_key_path is not None
                else self._path.with_name("." + self._path.name + ".seal.key")
            )
        )
        self._prepare_record_file()
        # Key discovery/creation and startup replay share the OS lock. Concurrent
        # first starters therefore cannot observe a partially written key.
        with self._locked_file():
            if self._seal_secret is None:
                assert self._seal_key_path is not None
                if not os.path.lexists(self._seal_key_path):
                    if os.path.lexists(self._checkpoint_path):
                        raise LLMRecordError(
                            "LLM record seal key is missing for checkpointed audit evidence"
                        )
                    if self._path.stat().st_size and not self._journal_is_legacy_only():
                        raise LLMRecordError(
                            "LLM record seal key is missing for persisted schema-v2/v3 audit evidence"
                        )
                self._seal_secret = self._load_or_create_key(self._seal_key_path)
            self._prepare_claim_directory()
            self._prepare_checkpoint()
            self._read_all_locked()

    @property
    def path(self) -> Path:
        return self._path

    @property
    def seal_secret(self) -> bytes:
        """Stable gateway injection seam; callers must not serialize or log it."""

        assert self._seal_secret is not None
        return bytes(self._seal_secret)

    @property
    def quarantined_legacy_rows(self) -> int:
        return self._quarantined_rows

    @property
    def checkpoint_path(self) -> Path:
        return self._checkpoint_path

    def append(self, record: LLMCallRecord) -> LLMCallRecord:
        if not isinstance(record, LLMCallRecord):
            raise TypeError(f"record must be LLMCallRecord, got {type(record).__name__}")
        self._validate_record(record)
        payload = self._to_persisted_payload(record)
        with self._locked_file():
            rows = self._read_all_locked()
            identity = self._identity(record)
            for existing in rows:
                if existing.call_id == record.call_id or self._identity(existing) == identity:
                    if (
                        existing.to_dict() == record.to_dict()
                        or self._equivalent_replay_retry(existing, record)
                    ):
                        return existing
                    raise LLMRecordError("LLMCallRecord identity collision differs from persisted evidence")
            candidate_rows = [*rows, record]
            self._validate_sequences(candidate_rows)
            raw = (canonical_json(payload) + "\n").encode("utf-8")
            self._transactional_append_locked(raw)
        return record

    def read_all(self, *, owner_user_id: str) -> list[LLMCallRecord]:
        owner = self._required_owner(owner_user_id)
        with self._locked_file():
            rows = self._read_all_locked()
        return [record for record in rows if record.owner_user_id == owner]

    def llm_records_for(self, asset_ref: str, *, owner_user_id: str) -> tuple[LLMCallRecord, ...]:
        ref = str(asset_ref or "").strip()
        if not ref:
            return ()
        return tuple(
            record for record in self.read_all(owner_user_id=owner_user_id)
            if record.workflow_id == ref
            or record.session_id == ref
            or record.call_id == ref
            or record.invocation_id == ref
        )

    def latest_by_call_id(self, *, owner_user_id: str) -> dict[str, LLMCallRecord]:
        return {record.call_id: record for record in self.read_all(owner_user_id=owner_user_id)}

    def resolve_terminal_record(
        self,
        call_id: str,
        owner_user_id: str,
    ) -> LLMCallRecord:
        """Resolve one exact owner-scoped terminal record for binding validation."""

        owner = self._required_owner(owner_user_id)
        ref = str(call_id or "").strip()
        if not ref:
            raise LLMRecordError("terminal LLM call_id is required")
        matches = [
            record
            for record in self.read_all(owner_user_id=owner)
            if record.call_id == ref
            and record.record_kind == CallRecordKind.TERMINAL.value
        ]
        if len(matches) != 1:
            raise KeyError("terminal LLM call is not recorded exactly once for owner")
        return matches[0]

    def invocation_records(
        self,
        *,
        owner_user_id: str,
        workflow_id: str,
        invocation_id: str,
    ) -> tuple[LLMCallRecord, ...]:
        owner = self._required_owner(owner_user_id)
        workflow = str(workflow_id or "").strip()
        invocation = str(invocation_id or "").strip()
        if not workflow or not invocation:
            raise LLMRecordError("workflow_id and invocation_id are required for invocation lookup")
        return tuple(
            record for record in self.read_all(owner_user_id=owner)
            if record.workflow_id == workflow and record.invocation_id == invocation
        )

    def claim_invocation(
        self,
        *,
        owner_user_id: str,
        workflow_id: str,
        invocation_id: str,
        prompt_digest: str,
    ) -> None:
        """Durably reserve one invocation before any provider access.

        Claim files contain only hashes and remain as fail-closed tombstones. A
        crash after reservation can therefore block a retry, but can never cause
        the provider to run twice under one idempotency envelope.
        """

        owner = self._required_owner(owner_user_id)
        workflow = str(workflow_id or "").strip()
        invocation = str(invocation_id or "").strip()
        digest = str(prompt_digest or "").strip()
        if not all(self._safe_identifier(value) for value in (owner, workflow, invocation)):
            raise LLMRecordError("LLM invocation scope contains non-identifier text")
        if len(digest) != 16 or any(ch not in "0123456789abcdef" for ch in digest):
            raise LLMRecordError("LLM invocation prompt_digest must be a sha256/16 digest")
        scope_payload = {
            "owner_user_id": owner,
            "workflow_id": workflow,
            "invocation_id": invocation,
        }
        scope_hash = hashlib.sha256(canonical_json(scope_payload).encode("utf-8")).hexdigest()
        body = {
            "claim_version": 1,
            "scope_sha256": scope_hash,
            "prompt_digest": digest,
        }
        assert self._seal_secret is not None
        integrity = hmac.new(
            self._seal_secret,
            b"llm-invocation-claim\x00" + canonical_json(body).encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
        payload = (canonical_json({**body, "integrity": integrity}) + "\n").encode("utf-8")
        claim_path = self._claim_dir / f"{scope_hash}.json"
        with self._locked_file():
            existing_rows = [
                record for record in self._read_all_locked()
                if record.owner_user_id == owner
                and record.workflow_id == workflow
                and record.invocation_id == invocation
            ]
            if existing_rows or os.path.lexists(claim_path):
                raise LLMRecordError(
                    "LLM invocation_id already has durable audit evidence or a durable claim"
                )
            flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
            fd = os.open(claim_path, flags, 0o600)
            try:
                os.fchmod(fd, 0o600)
                self._write_all(fd, payload)
                os.fsync(fd)
            except BaseException:
                os.close(fd)
                try:
                    os.unlink(claim_path)
                    self._fsync_directory(self._claim_dir)
                except BaseException:
                    pass
                raise
            else:
                os.close(fd)
            self._fsync_directory(self._claim_dir)

    @staticmethod
    def _write_all(fd: int, payload: bytes) -> None:
        offset = 0
        while offset < len(payload):
            written = os.write(fd, payload[offset:])
            if written <= 0:
                raise OSError("short write while persisting LLM audit evidence")
            offset += written

    def _journal_is_legacy_only(self) -> bool:
        """Return true only when every non-empty row predates schema v2."""

        raw = self._path.read_bytes()
        if not raw or not raw.endswith(b"\n"):
            return False
        saw_row = False
        for raw_line in raw.splitlines():
            if not raw_line.strip():
                return False
            try:
                payload = json.loads(raw_line.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError):
                return False
            if not isinstance(payload, dict) or payload.get("schema_version") not in (None, 1):
                return False
            saw_row = True
        return saw_row

    def _checkpoint_body(self, journal: bytes) -> dict[str, Any]:
        return {
            "checkpoint_version": _CHECKPOINT_VERSION,
            "journal": self._path.name,
            "size": len(journal),
            "sha256": hashlib.sha256(journal).hexdigest(),
        }

    def _checkpoint_bytes(self, journal: bytes) -> bytes:
        assert self._seal_secret is not None
        body = self._checkpoint_body(journal)
        domain = b"llm-call-record-head\x00" + self._path.name.encode("utf-8") + b"\x00"
        integrity = hmac.new(
            self._seal_secret,
            domain + canonical_json(body).encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
        return (canonical_json({**body, "integrity": integrity}) + "\n").encode("utf-8")

    def _read_checkpoint(self) -> tuple[dict[str, Any], bytes]:
        if not os.path.lexists(self._checkpoint_path):
            raise LLMRecordError("LLM record journal checkpoint is missing")
        self._assert_regular_owned(self._checkpoint_path, label="LLM record journal checkpoint")
        raw = self._checkpoint_path.read_bytes()
        try:
            text = raw.decode("utf-8")
            row = json.loads(text)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise LLMRecordError("LLM record journal checkpoint is malformed") from exc
        if not isinstance(row, dict) or text != canonical_json(row) + "\n":
            raise LLMRecordError("LLM record journal checkpoint is not canonical JSON")
        try:
            integrity = str(row.pop("integrity"))
        except KeyError as exc:
            raise LLMRecordError("LLM record journal checkpoint lacks integrity") from exc
        assert self._seal_secret is not None
        domain = b"llm-call-record-head\x00" + self._path.name.encode("utf-8") + b"\x00"
        expected = hmac.new(
            self._seal_secret,
            domain + canonical_json(row).encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
        if not hmac.compare_digest(expected, integrity):
            raise LLMRecordError("LLM record journal checkpoint HMAC verification failed")
        if (
            row.get("checkpoint_version") != _CHECKPOINT_VERSION
            or row.get("journal") != self._path.name
        ):
            raise LLMRecordError("LLM record journal checkpoint identity is invalid")
        return row, raw

    def _verified_journal_bytes(self) -> bytes:
        if self._poisoned:
            raise LLMRecordError(
                "LLM record store is fail-closed after an incomplete durability rollback"
            )
        self._assert_regular_owned(self._path, label="LLM record journal")
        checkpoint, _ = self._read_checkpoint()
        payload = self._path.read_bytes()
        if checkpoint.get("size") != len(payload):
            raise LLMRecordError("LLM record journal size diverged from checkpoint")
        digest = hashlib.sha256(payload).hexdigest()
        if not hmac.compare_digest(str(checkpoint.get("sha256") or ""), digest):
            raise LLMRecordError("LLM record journal digest diverged from checkpoint")
        return payload

    def _prepare_checkpoint(self) -> None:
        if os.path.lexists(self._checkpoint_path):
            self._verified_journal_bytes()
            return
        raw = self._path.read_bytes()
        if raw and not self._journal_is_legacy_only():
            raise LLMRecordError(
                "schema-v2/v3 LLM audit evidence is missing its durable checkpoint"
            )
        self._atomic_replace_bytes(self._checkpoint_path, self._checkpoint_bytes(raw))

    def _atomic_replace_bytes(self, path: Path, payload: bytes) -> None:
        temp = path.with_name(f".{path.name}.{os.getpid()}.{secrets.token_hex(8)}.tmp")
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
        fd = os.open(temp, flags, 0o600)
        try:
            os.fchmod(fd, 0o600)
            self._write_all(fd, payload)
            os.fsync(fd)
        except BaseException:
            os.close(fd)
            try:
                os.unlink(temp)
            except FileNotFoundError:
                pass
            raise
        else:
            os.close(fd)
        try:
            os.replace(temp, path)
            self._fsync_parent(path)
        except BaseException:
            try:
                os.unlink(temp)
            except FileNotFoundError:
                pass
            raise

    def _restore_transaction(
        self,
        *,
        prior_journal: bytes,
        prior_checkpoint: bytes,
    ) -> list[str]:
        errors: list[str] = []
        try:
            if self._path.read_bytes() != prior_journal:
                fd = os.open(
                    self._path,
                    os.O_WRONLY | getattr(os, "O_NOFOLLOW", 0),
                )
                try:
                    os.ftruncate(fd, 0)
                    self._write_all(fd, prior_journal)
                    os.fsync(fd)
                finally:
                    os.close(fd)
        except BaseException as exc:  # noqa: BLE001 - retain every durability failure.
            errors.append(f"journal restore: {type(exc).__name__}: {exc}")
        try:
            if (
                not os.path.lexists(self._checkpoint_path)
                or self._checkpoint_path.read_bytes() != prior_checkpoint
            ):
                self._atomic_replace_bytes(self._checkpoint_path, prior_checkpoint)
        except BaseException as exc:  # noqa: BLE001
            errors.append(f"checkpoint restore: {type(exc).__name__}: {exc}")
        try:
            if (
                self._path.read_bytes() != prior_journal
                or self._checkpoint_path.read_bytes() != prior_checkpoint
            ):
                errors.append("restored bytes do not match pre-append state")
        except BaseException as exc:  # noqa: BLE001
            errors.append(f"rollback verification: {type(exc).__name__}: {exc}")
        return errors

    def _transactional_append_locked(self, payload: bytes) -> None:
        prior_journal = self._verified_journal_bytes()
        _, prior_checkpoint = self._read_checkpoint()
        fd = -1
        try:
            fd = os.open(
                self._path,
                os.O_WRONLY | os.O_APPEND | getattr(os, "O_NOFOLLOW", 0),
            )
            file_stat = os.fstat(fd)
            if not stat.S_ISREG(file_stat.st_mode):
                raise LLMRecordError("LLM record journal must remain a regular file")
            if hasattr(os, "getuid") and file_stat.st_uid != os.getuid():
                raise LLMRecordError("LLM record journal owner changed during append")
            self._write_all(fd, payload)
            os.fsync(fd)
            os.close(fd)
            fd = -1
            updated = prior_journal + payload
            self._atomic_replace_bytes(self._checkpoint_path, self._checkpoint_bytes(updated))
            if self._verified_journal_bytes() != updated:
                raise LLMRecordError("LLM record append postcondition failed")
        except BaseException as exc:
            if fd >= 0:
                os.close(fd)
            rollback_errors = self._restore_transaction(
                prior_journal=prior_journal,
                prior_checkpoint=prior_checkpoint,
            )
            if rollback_errors:
                self._poisoned = True
                raise LLMRecordError(
                    "LLM record append failed and rollback durability is unverified; "
                    + "; ".join(rollback_errors)
                ) from exc
            raise

    def _prepare_record_file(self) -> None:
        if os.path.lexists(self._path):
            self._assert_regular_owned(self._path, label="LLM record journal")
            return
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
        try:
            fd = os.open(self._path, flags, 0o600)
        except FileExistsError:
            self._assert_regular_owned(self._path, label="LLM record journal")
            return
        try:
            os.fsync(fd)
        finally:
            os.close(fd)
        self._fsync_parent(self._path)
        self._assert_regular_owned(self._path, label="LLM record journal")

    @staticmethod
    def _fsync_parent(path: Path) -> None:
        LLMCallRecordStore._fsync_directory(path.parent)

    @staticmethod
    def _fsync_directory(path: Path) -> None:
        flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
        fd = os.open(path, flags)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)

    def _prepare_claim_directory(self) -> None:
        try:
            info = self._claim_dir.lstat()
        except FileNotFoundError:
            try:
                self._claim_dir.mkdir(mode=0o700)
            except FileExistsError:
                info = self._claim_dir.lstat()
            else:
                self._fsync_parent(self._claim_dir)
                info = self._claim_dir.lstat()
        if stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode):
            raise LLMRecordError("LLM invocation claim path must be a regular directory")
        if hasattr(os, "getuid") and info.st_uid != os.getuid():
            raise LLMRecordError("LLM invocation claim directory is owned by a different runtime user")
        self._claim_dir.chmod(0o700)

    @staticmethod
    def _assert_regular_owned(path: Path, *, label: str) -> None:
        info = path.lstat()
        if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode):
            raise LLMRecordError(f"{label} must be a regular non-symlink file")
        if hasattr(os, "getuid") and info.st_uid != os.getuid():
            raise LLMRecordError(f"{label} is owned by a different runtime user")
        path.chmod(0o600)

    @classmethod
    def _load_or_create_key(cls, path: Path) -> bytes:
        path.parent.mkdir(parents=True, exist_ok=True)
        if os.path.lexists(path):
            cls._assert_regular_owned(path, label="LLM record seal key")
            key = path.read_bytes()
        else:
            candidate = os.urandom(32)
            flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
            try:
                fd = os.open(path, flags, 0o600)
            except FileExistsError:
                cls._assert_regular_owned(path, label="LLM record seal key")
                key = path.read_bytes()
            else:
                try:
                    os.fchmod(fd, 0o600)
                    cls._write_all(fd, candidate)
                    os.fsync(fd)
                except BaseException:
                    os.close(fd)
                    try:
                        os.unlink(path)
                    except FileNotFoundError:
                        pass
                    raise
                else:
                    os.close(fd)
                cls._fsync_parent(path)
                key = candidate
        if len(key) < 32:
            raise LLMRecordError("LLM record seal key is invalid")
        cls._assert_regular_owned(path, label="LLM record seal key")
        return key

    @contextmanager
    def _locked_file(self):
        with self._lock:
            flags = os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0)
            fd = os.open(self._lock_path, flags, 0o600)
            held = None
            try:
                info = os.fstat(fd)
                if not stat.S_ISREG(info.st_mode):
                    raise LLMRecordError("LLM record lock must be a regular file")
                if hasattr(os, "getuid") and info.st_uid != os.getuid():
                    raise LLMRecordError("LLM record lock is owned by a different runtime user")
                os.fchmod(fd, 0o600)
                held = acquire_exclusive_fd(fd, timeout_seconds=10.0)
                self._assert_regular_owned(self._path, label="LLM record journal")
                yield
            finally:
                if held is not None:
                    held.release()
                os.close(fd)

    def _read_all_locked(self) -> list[LLMCallRecord]:
        raw = self._verified_journal_bytes()
        if raw and not raw.endswith(b"\n"):
            raise LLMRecordError("LLM record journal has a torn or unterminated tail")
        rows: list[LLMCallRecord] = []
        seen_call_ids: set[str] = set()
        seen_identities: set[tuple[str, str, str, str, int]] = set()
        quarantined = 0
        for line_no, raw_line in enumerate(raw.splitlines(), start=1):
            if not raw_line.strip():
                raise LLMRecordError(f"LLM record journal line {line_no} is empty")
            try:
                text = raw_line.decode("utf-8")
                payload = json.loads(text)
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise LLMRecordError(f"LLM record journal line {line_no} is malformed") from exc
            if not isinstance(payload, dict) or text != canonical_json(payload):
                raise LLMRecordError(f"LLM record journal line {line_no} is not canonical JSON")
            schema_version = payload.get("schema_version")
            if schema_version in (None, 1):
                quarantined += 1
                continue
            if schema_version not in {
                LEGACY_LLM_RECORD_SCHEMA_VERSION,
                CURRENT_LLM_RECORD_SCHEMA_VERSION,
            }:
                raise LLMRecordError(
                    f"LLM record journal line {line_no} has unsupported schema_version"
                )
            record = self._from_dict(payload)
            self._validate_record(record, allow_legacy=True)
            identity = self._identity(record)
            if record.call_id in seen_call_ids or identity in seen_identities:
                raise LLMRecordError("LLM record journal contains a duplicate identity")
            seen_call_ids.add(record.call_id)
            seen_identities.add(identity)
            rows.append(record)
        self._validate_sequences(rows)
        self._quarantined_rows = quarantined
        return rows

    def _validate_record(self, record: LLMCallRecord, *, allow_legacy: bool = False) -> None:
        if record.schema_version == LEGACY_LLM_RECORD_SCHEMA_VERSION:
            if not allow_legacy:
                raise LLMRecordError(
                    "schema-v2 LLMCallRecord is read-only legacy history and cannot be appended"
                )
            assert_legacy_record_loadable(record)
        else:
            assert_record_admissible(record)
        if not record.call_id or not record.started_at or not record.finished_at:
            raise LLMRecordError("persisted LLMCallRecord requires call_id and timestamps")
        expected = make_call_id(
            prompt_digest="", provider="", model="", role="", session_id="", seq=record.attempt_no,
            owner_user_id=record.owner_user_id,
            workflow_id=record.workflow_id,
            invocation_id=record.invocation_id,
            record_kind=record.record_kind,
            attempt_no=record.attempt_no,
            schema_version=record.schema_version,
        )
        if record.call_id != expected:
            raise LLMRecordError("LLMCallRecord call_id does not match its identity envelope")
        assert self._seal_secret is not None
        if not verify_record_seal(record, self._seal_secret):
            raise LLMRecordError("LLMCallRecord seal verification failed")
        self._to_persisted_payload(record)

    @classmethod
    def _to_persisted_payload(cls, record: LLMCallRecord) -> dict[str, Any]:
        if record.degrade_reason or record.fallback_chain or record.base_url_redacted:
            raise LLMRecordError("free-text, fallback strings, and URLs are not persistable audit fields")
        if record.independence.reason:
            raise LLMRecordError("free-text independence reason is not persistable")
        if record.provider and not cls._safe_provider(record.provider):
            raise LLMRecordError("LLMCallRecord provider is not a controlled provider identifier")
        if record.model and not cls._safe_model(record.model):
            raise LLMRecordError("LLMCallRecord model is not a controlled model identifier")
        if record.auth_ref and not cls._safe_secret_ref(record.auth_ref):
            raise LLMRecordError("LLMCallRecord auth_ref must be a controlled SecretRef")
        for name in (
            "provider", "model", "auth_ref", "owner_user_id", "workflow_id", "invocation_id",
            "role", "task_difficulty", "risk_level", "tier_requested", "tier_resolved",
            "routing_policy_ref", "routing_policy_state", "provider_health", "quota_state",
            "call_id", "session_id", "prompt_digest", "prompt_hash", "tool_schema_hash",
            "response_digest", "response_ref", "fixture_key", "status", "error_kind",
            "failure_stage", "repro_level",
        ):
            value = getattr(record, name)
            if value is not None and value != "" and not cls._safe_identifier(str(value)):
                raise LLMRecordError(f"LLMCallRecord {name} contains non-identifier text")
        digest_names = ["call_id", "prompt_digest"]
        if record.schema_version == CURRENT_LLM_RECORD_SCHEMA_VERSION:
            digest_names.extend(("prompt_hash", "tool_schema_hash"))
        for digest_name in digest_names:
            digest = str(getattr(record, digest_name) or "")
            if len(digest) != 16 or any(ch not in "0123456789abcdef" for ch in digest):
                raise LLMRecordError(f"LLMCallRecord {digest_name} must be a sha256/16 digest")
        if record.response_digest:
            if len(record.response_digest) != 16 or any(
                ch not in "0123456789abcdef" for ch in record.response_digest
            ):
                raise LLMRecordError("LLMCallRecord response_digest must be a sha256/16 digest")
        if len(record.seal) != 32 or any(ch not in "0123456789abcdef" for ch in record.seal):
            raise LLMRecordError("LLMCallRecord seal must be a sha256 HMAC/32 tag")
        if record.independence.builder_call_id and not cls._safe_identifier(
            record.independence.builder_call_id
        ):
            raise LLMRecordError("LLMCallRecord builder_call_id is not a controlled identifier")
        for timestamp_name in ("started_at", "finished_at"):
            timestamp = str(getattr(record, timestamp_name) or "")
            try:
                parsed = datetime.fromisoformat(timestamp)
            except ValueError as exc:
                raise LLMRecordError(
                    f"LLMCallRecord {timestamp_name} must be an ISO-8601 timestamp"
                ) from exc
            if parsed.tzinfo is None:
                raise LLMRecordError(f"LLMCallRecord {timestamp_name} must include a timezone")
        started_at = datetime.fromisoformat(record.started_at)
        finished_at = datetime.fromisoformat(record.finished_at)
        if finished_at < started_at:
            raise LLMRecordError("LLMCallRecord finished_at cannot precede started_at")
        if record.latency_ms is not None:
            if type(record.latency_ms) not in (int, float) or not math.isfinite(record.latency_ms):
                raise LLMRecordError("LLMCallRecord latency_ms must be finite numeric metadata")
            if record.latency_ms < 0:
                raise LLMRecordError("LLMCallRecord latency_ms must be non-negative")
        if not isinstance(record.usage, dict):
            raise LLMRecordError("LLMCallRecord usage must be numeric counters")
        for key, value in record.usage.items():
            if not cls._safe_identifier(str(key)):
                raise LLMRecordError("LLMCallRecord usage key is not a controlled identifier")
            if type(value) is int and value >= 0:
                continue
            if type(value) is float and math.isfinite(value) and value >= 0:
                continue
            raise LLMRecordError("LLMCallRecord usage values must be finite numeric counters")
        data = record.to_dict()
        data["independence"] = {
            "required": record.independence.required,
            "satisfied": record.independence.satisfied,
            "distinct_provider": record.independence.distinct_provider,
            "distinct_model": record.independence.distinct_model,
            "builder_call_id": record.independence.builder_call_id,
        }
        fields = (
            _PERSISTED_FIELDS_V3
            if record.schema_version == CURRENT_LLM_RECORD_SCHEMA_VERSION
            else _PERSISTED_FIELDS_V2
        )
        return {name: data[name] for name in fields}

    @staticmethod
    def _safe_identifier(value: str) -> bool:
        return bool(value) and len(value) <= 256 and value.isascii() and all(
            ch.isalnum() or ch in _IDENTIFIER_PUNCTUATION for ch in value
        )

    @staticmethod
    def _safe_provider(value: str) -> bool:
        return type(value) is str and bool(value) and len(value) <= 128 and value.isascii() and all(
            ch.isalnum() or ch in _PROVIDER_PUNCTUATION for ch in value
        )

    @staticmethod
    def _safe_model(value: str) -> bool:
        return (
            type(value) is str
            and bool(value)
            and len(value) <= 256
            and value.isascii()
            and "://" not in value
            and all(ch.isalnum() or ch in _MODEL_PUNCTUATION for ch in value)
        )

    @staticmethod
    def _safe_secret_ref(value: str) -> bool:
        prefix = "secretref://"
        if type(value) is not str or not value.startswith(prefix) or len(value) > 256:
            return False
        remainder = value[len(prefix):]
        parts = remainder.split("/")
        if len(parts) != 2 or not all(parts):
            return False
        return all(
            part.isascii()
            and all(ch.isalnum() or ch in _SECRET_REF_PUNCTUATION for ch in part)
            for part in parts
        )

    @staticmethod
    def _identity(record: LLMCallRecord) -> tuple[str, str, str, str, int]:
        return (
            record.owner_user_id,
            record.workflow_id,
            record.invocation_id,
            record.record_kind,
            record.attempt_no,
        )

    @staticmethod
    def _equivalent_replay_retry(existing: LLMCallRecord, candidate: LLMCallRecord) -> bool:
        """Treat temporal-only drift as an exact retry for standalone replay outcomes.

        The invocation envelope remains the idempotency key. Evidence-bearing
        fields (fixture/prompt/response/provider/auth/status) must still match;
        otherwise append rejects the collision.
        """

        if not (
            existing.record_kind == candidate.record_kind == CallRecordKind.TERMINAL.value
            and (
                existing.replay_state == candidate.replay_state == "replayed"
                or existing.failure_stage == candidate.failure_stage == "replay"
            )
        ):
            return False
        left = existing.to_dict()
        right = candidate.to_dict()
        for payload in (left, right):
            for field in ("started_at", "finished_at", "latency_ms", "seal"):
                payload.pop(field, None)
        return left == right

    @staticmethod
    def _validate_sequences(rows: list[LLMCallRecord]) -> None:
        groups: dict[tuple[str, str, str], list[LLMCallRecord]] = defaultdict(list)
        for record in rows:
            groups[(record.owner_user_id, record.workflow_id, record.invocation_id)].append(record)
        for group in groups.values():
            attempts = [r for r in group if r.record_kind == CallRecordKind.ATTEMPT.value]
            terminals = [r for r in group if r.record_kind == CallRecordKind.TERMINAL.value]
            numbers = [r.attempt_no for r in attempts]
            if numbers != list(range(1, len(numbers) + 1)):
                raise LLMRecordError("LLM invocation attempts must be ordered and contiguous from one")
            successful_attempts = [r for r in attempts if r.status == CallStatus.OK.value]
            if successful_attempts:
                if len(successful_attempts) != 1 or attempts[-1] is not successful_attempts[0]:
                    raise LLMRecordError(
                        "LLM invocation may contain only one successful final attempt"
                    )
            if len(terminals) > 1:
                raise LLMRecordError("LLM invocation may contain only one terminal record")
            if terminals and group[-1].record_kind != CallRecordKind.TERMINAL.value:
                raise LLMRecordError("LLM invocation cannot append attempts after its terminal record")
            if not terminals:
                continue
            terminal = terminals[0]
            if attempts:
                max_attempt = attempts[-1].attempt_no
                allowed = {max_attempt}
                if terminal.status == CallStatus.REFUSED.value:
                    allowed.add(max_attempt + 1)
                if terminal.attempt_no not in allowed:
                    raise LLMRecordError("LLM terminal attempt_no does not match invocation attempts")
            elif terminal.attempt_no != 1:
                raise LLMRecordError("pre-attempt LLM terminal record must use attempt_no one")
            if terminal.status == CallStatus.OK.value:
                standalone_replay = (
                    not attempts
                    and terminal.replay_state == "replayed"
                    and bool(terminal.fixture_key)
                )
                if standalone_replay:
                    continue
                match = next(
                    (
                        row for row in attempts
                        if row.attempt_no == terminal.attempt_no
                        and row.status == CallStatus.OK.value
                        and row.response_digest == terminal.response_digest
                    ),
                    None,
                )
                if match is None:
                    raise LLMRecordError("terminal success requires a matching successful attempt")
            elif successful_attempts:
                raise LLMRecordError(
                    "failed/refused terminal cannot follow a successful provider attempt"
                )
            elif terminal.status == CallStatus.ERROR.value and attempts:
                if terminal.attempt_no != attempts[-1].attempt_no:
                    raise LLMRecordError(
                        "terminal error must match the last failed provider attempt"
                    )
            elif terminal.status == CallStatus.REFUSED.value and attempts:
                if terminal.attempt_no != attempts[-1].attempt_no + 1:
                    raise LLMRecordError(
                        "post-attempt terminal refusal must occupy the next attempt number"
                    )

    @staticmethod
    def _required_owner(owner_user_id: str) -> str:
        owner = str(owner_user_id or "").strip()
        if not owner:
            raise LLMRecordError("owner_user_id is required for LLM record reads")
        return owner

    @staticmethod
    def _from_dict(data: dict[str, Any]) -> LLMCallRecord:
        schema_version = data.get("schema_version")
        if schema_version == LEGACY_LLM_RECORD_SCHEMA_VERSION:
            persisted_fields = _PERSISTED_FIELDS_V2
        elif schema_version == CURRENT_LLM_RECORD_SCHEMA_VERSION:
            persisted_fields = _PERSISTED_FIELDS_V3
        else:
            raise LLMRecordError("LLM record schema_version is unsupported")
        unknown = set(data) - set(persisted_fields)
        missing = set(persisted_fields) - set(data)
        if unknown or missing:
            raise LLMRecordError(
                f"LLM record persisted field mismatch: unknown={sorted(unknown)}, missing={sorted(missing)}"
            )
        payload = dict(data)
        independence = payload.get("independence")
        if not isinstance(independence, dict):
            raise LLMRecordError("LLM record independence payload is malformed")
        allowed_independence = {
            "required", "satisfied", "distinct_provider", "distinct_model", "builder_call_id"
        }
        if set(independence) != allowed_independence:
            raise LLMRecordError("LLM record independence fields are malformed")
        payload["independence"] = IndependenceRecord(**independence, reason="")
        try:
            return LLMCallRecord(**payload)
        except (TypeError, ValueError) as exc:
            raise LLMRecordError("LLM record payload is malformed") from exc


def collect_llm_records(
    stores: Iterable[Any],
    asset_ref: str,
    *,
    owner_user_id: str,
) -> tuple[LLMCallRecord, ...]:
    """Resolve only records within the caller's explicit owner namespace."""

    out: list[LLMCallRecord] = []
    for store in stores:
        if store is None or not hasattr(store, "llm_records_for"):
            continue
        rows = store.llm_records_for(asset_ref, owner_user_id=owner_user_id)
        out.extend(row for row in rows if isinstance(row, LLMCallRecord))
    return tuple(out)


__all__ = ["LLMCallRecordStore", "collect_llm_records"]
