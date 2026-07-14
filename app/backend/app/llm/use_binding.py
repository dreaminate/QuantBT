"""Durable proof of the gateway selection consumed by one terminal LLM call.

The user request never supplies these fields.  ``LLMGateway`` derives them
from its resolved routing decision, materialized SecretRef descriptor, and
server-configured service-principal mappings after the terminal call record is
sealed and persisted.  The store verifies both gateway HMAC provenance and the
current terminal call record before accepting or returning a binding.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
import stat
import threading
from contextlib import contextmanager
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from typing import Any, Callable, Iterator

from ..cross_process_lock import acquire_exclusive_fd
from ..lineage.ids import canonical_json, content_hash
from .call_record import (
    CallRecordKind,
    CallStatus,
    LLMCallRecord,
    LLMRecordError,
    assert_record_admissible,
    verify_record_seal,
)


USE_BINDING_SCHEMA_VERSION = 2
USE_BINDING_RECORD_VERSION = "llm_gateway_use_binding.v1"
_CHECKPOINT_VERSION = 1
_IDENTIFIER_PUNCTUATION = frozenset("._:@/+=-")
_PROVIDER_PUNCTUATION = frozenset("._-")
_SECRET_REF_PUNCTUATION = frozenset("._-+")


class LLMUseBindingError(LLMRecordError):
    """Gateway-use binding evidence is missing, inconsistent, or corrupted."""


@dataclass(frozen=True)
class LLMUseBindingViolation:
    code: str
    message: str
    field: str = ""
    ref: str = ""


@dataclass(frozen=True)
class LLMUseBindingDecision:
    accepted: bool
    violations: tuple[LLMUseBindingViolation, ...]


@dataclass(frozen=True)
class LLMGatewayUseBindingRecord:
    schema_version: int
    binding_ref: str
    owner_user_id: str
    service_principal_ref: str
    provider_ref: str
    auth_ref: str
    credential_pool_ref: str
    routing_policy_ref: str
    terminal_call_id: str
    invocation_id: str
    workflow_id: str
    terminal_record_kind: str
    terminal_status: str
    record_revision: int
    state_hash: str
    gateway_seal: str
    record_version: str = USE_BINDING_RECORD_VERSION

    def state_payload(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "owner_user_id": self.owner_user_id,
            "service_principal_ref": self.service_principal_ref,
            "provider_ref": self.provider_ref,
            "auth_ref": self.auth_ref,
            "credential_pool_ref": self.credential_pool_ref,
            "routing_policy_ref": self.routing_policy_ref,
            "terminal_call_id": self.terminal_call_id,
            "invocation_id": self.invocation_id,
            "workflow_id": self.workflow_id,
            "terminal_record_kind": self.terminal_record_kind,
            "terminal_status": self.terminal_status,
            "record_revision": self.record_revision,
            "record_version": self.record_version,
        }

    def sealable_payload(self) -> dict[str, Any]:
        payload = asdict(self)
        payload.pop("gateway_seal", None)
        return payload


TerminalRecordResolver = Callable[[str, str], LLMCallRecord]


def _state_hash(payload: dict[str, Any]) -> str:
    return "sha256:" + hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()


def _binding_ref(payload: dict[str, Any]) -> str:
    return "llm_gateway_use_binding:" + content_hash(payload)


def seal_llm_gateway_use_binding(
    record: LLMGatewayUseBindingRecord,
    secret: bytes,
) -> str:
    if len(secret) < 32:
        raise ValueError("LLM use-binding seal secret must contain at least 32 bytes")
    return hmac.new(
        secret,
        b"llm-gateway-use-binding\x00"
        + canonical_json(record.sealable_payload()).encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


def verify_llm_gateway_use_binding_seal(
    record: LLMGatewayUseBindingRecord,
    secret: bytes,
) -> bool:
    if not record.gateway_seal:
        return False
    expected = seal_llm_gateway_use_binding(record, secret)
    return hmac.compare_digest(expected, record.gateway_seal)


def make_llm_gateway_use_binding(
    terminal_record: LLMCallRecord,
    *,
    service_principal_ref: str,
    credential_pool_ref: str,
    routing_policy_ref: str,
    seal_secret: bytes,
) -> LLMGatewayUseBindingRecord:
    """Create one gateway-sealed binding from a successful terminal record."""

    assert_record_admissible(terminal_record)
    if terminal_record.record_kind != CallRecordKind.TERMINAL.value:
        raise LLMUseBindingError("LLM use binding requires a terminal call record")
    if terminal_record.status != CallStatus.OK.value:
        raise LLMUseBindingError("LLM use binding requires a successful terminal call")
    if not verify_record_seal(terminal_record, seal_secret):
        raise LLMUseBindingError("terminal LLM call is not sealed by this gateway")
    values = {
        "service_principal_ref": str(service_principal_ref or "").strip(),
        "credential_pool_ref": str(credential_pool_ref or "").strip(),
        "routing_policy_ref": str(routing_policy_ref or "").strip(),
    }
    if not all(values.values()):
        raise LLMUseBindingError(
            "gateway service principal, credential pool, and routing policy refs are required"
        )
    blank = LLMGatewayUseBindingRecord(
        schema_version=USE_BINDING_SCHEMA_VERSION,
        binding_ref="",
        owner_user_id=terminal_record.owner_user_id,
        service_principal_ref=values["service_principal_ref"],
        provider_ref=terminal_record.provider,
        auth_ref=terminal_record.auth_ref,
        credential_pool_ref=values["credential_pool_ref"],
        routing_policy_ref=values["routing_policy_ref"],
        terminal_call_id=terminal_record.call_id,
        invocation_id=terminal_record.invocation_id,
        workflow_id=terminal_record.workflow_id,
        terminal_record_kind=terminal_record.record_kind,
        terminal_status=terminal_record.status,
        record_revision=1,
        state_hash="",
        gateway_seal="",
    )
    state_hash = _state_hash(blank.state_payload())
    with_hash = replace(blank, state_hash=state_hash)
    with_ref = replace(with_hash, binding_ref=_binding_ref(with_hash.state_payload()))
    return replace(
        with_ref,
        gateway_seal=seal_llm_gateway_use_binding(with_ref, seal_secret),
    )


def _safe_identifier(value: str) -> bool:
    return bool(value) and len(value) <= 256 and value.isascii() and all(
        char.isalnum() or char in _IDENTIFIER_PUNCTUATION for char in value
    )


def _safe_provider(value: str) -> bool:
    return bool(value) and len(value) <= 128 and value.isascii() and all(
        char.isalnum() or char in _PROVIDER_PUNCTUATION for char in value
    )


def _safe_secret_ref(value: str) -> bool:
    prefix = "secretref://"
    if not value.startswith(prefix) or len(value) > 256:
        return False
    parts = value[len(prefix):].split("/")
    return len(parts) == 2 and all(
        part
        and part.isascii()
        and all(char.isalnum() or char in _SECRET_REF_PUNCTUATION for char in part)
        for part in parts
    )


def validate_llm_gateway_use_binding_shape(
    record: LLMGatewayUseBindingRecord,
    *,
    seal_secret: bytes,
) -> LLMUseBindingDecision:
    violations: list[LLMUseBindingViolation] = []

    def reject(code: str, message: str, *, field: str = "", ref: str = "") -> None:
        violations.append(LLMUseBindingViolation(code, message, field=field, ref=ref))

    if record.schema_version != USE_BINDING_SCHEMA_VERSION:
        reject(
            "llm_use_binding_schema_unsupported",
            "LLM use binding schema_version must be 2",
            field="schema_version",
            ref=record.binding_ref,
        )
    if record.record_version != USE_BINDING_RECORD_VERSION:
        reject(
            "llm_use_binding_record_version_unsupported",
            "LLM use binding record version is unsupported",
            field="record_version",
            ref=record.binding_ref,
        )
    if type(record.record_revision) is not int or record.record_revision != 1:
        reject(
            "llm_use_binding_revision_invalid",
            "terminal gateway-use bindings are immutable revision-one records",
            field="record_revision",
            ref=record.binding_ref,
        )
    for field_name in (
        "binding_ref",
        "owner_user_id",
        "service_principal_ref",
        "credential_pool_ref",
        "routing_policy_ref",
        "terminal_call_id",
        "invocation_id",
        "workflow_id",
        "terminal_record_kind",
        "terminal_status",
        "state_hash",
        "gateway_seal",
    ):
        value = getattr(record, field_name)
        if not isinstance(value, str) or not value or value != value.strip():
            reject(
                "llm_use_binding_required_field_missing",
                "LLM use binding fields must be stable non-empty exact strings",
                field=field_name,
                ref=record.binding_ref,
            )
    for field_name in (
        "binding_ref",
        "owner_user_id",
        "service_principal_ref",
        "credential_pool_ref",
        "routing_policy_ref",
        "terminal_call_id",
        "invocation_id",
        "workflow_id",
        "terminal_record_kind",
        "terminal_status",
    ):
        value = str(getattr(record, field_name) or "")
        if value and not _safe_identifier(value):
            reject(
                "llm_use_binding_identifier_unsafe",
                "LLM use binding contains non-identifier text",
                field=field_name,
                ref=record.binding_ref,
            )
    if not _safe_provider(record.provider_ref):
        reject(
            "llm_use_binding_provider_invalid",
            "provider_ref must be a controlled provider identifier",
            field="provider_ref",
            ref=record.binding_ref,
        )
    if not _safe_secret_ref(record.auth_ref):
        reject(
            "llm_use_binding_auth_ref_invalid",
            "auth_ref must be a controlled SecretRef and never plaintext",
            field="auth_ref",
            ref=record.binding_ref,
        )
    if record.terminal_record_kind != CallRecordKind.TERMINAL.value:
        reject(
            "llm_use_binding_not_terminal",
            "LLM use binding must reference a terminal call record",
            field="terminal_record_kind",
            ref=record.terminal_call_id,
        )
    if record.terminal_status != CallStatus.OK.value:
        reject(
            "llm_use_binding_terminal_not_successful",
            "failed or refused terminal calls cannot prove provider consumption",
            field="terminal_status",
            ref=record.terminal_call_id,
        )
    expected_hash = _state_hash(record.state_payload())
    if record.state_hash != expected_hash:
        reject(
            "llm_use_binding_state_hash_mismatch",
            "state_hash must bind owner, service, selection, and terminal identity",
            field="state_hash",
            ref=record.binding_ref,
        )
    expected_ref = _binding_ref(record.state_payload())
    if record.binding_ref != expected_ref:
        reject(
            "llm_use_binding_identity_mismatch",
            "binding_ref must content-bind the complete gateway-use selection",
            field="binding_ref",
            ref=record.binding_ref,
        )
    if not verify_llm_gateway_use_binding_seal(record, seal_secret):
        reject(
            "llm_use_binding_gateway_seal_invalid",
            "binding was not sealed by the configured LLM Gateway key",
            field="gateway_seal",
            ref=record.binding_ref,
        )
    return LLMUseBindingDecision(not violations, tuple(violations))


def validate_llm_gateway_use_binding_terminal(
    record: LLMGatewayUseBindingRecord,
    terminal_record: LLMCallRecord,
    *,
    seal_secret: bytes,
) -> LLMUseBindingDecision:
    violations = list(
        validate_llm_gateway_use_binding_shape(
            record,
            seal_secret=seal_secret,
        ).violations
    )

    def reject(field: str, message: str) -> None:
        violations.append(
            LLMUseBindingViolation(
                "llm_use_binding_terminal_mismatch",
                message,
                field=field,
                ref=record.terminal_call_id,
            )
        )

    try:
        assert_record_admissible(terminal_record)
    except LLMRecordError:
        reject("terminal_call_id", "resolved terminal call record is inadmissible")
    if not verify_record_seal(terminal_record, seal_secret):
        reject("terminal_call_id", "resolved terminal call seal is invalid")
    expected = {
        "owner_user_id": terminal_record.owner_user_id,
        "provider_ref": terminal_record.provider,
        "auth_ref": terminal_record.auth_ref,
        "terminal_call_id": terminal_record.call_id,
        "invocation_id": terminal_record.invocation_id,
        "workflow_id": terminal_record.workflow_id,
        "terminal_record_kind": terminal_record.record_kind,
        "terminal_status": terminal_record.status,
    }
    for field_name, value in expected.items():
        if getattr(record, field_name) != value:
            reject(field_name, "binding does not exactly match the persisted terminal call")
    return LLMUseBindingDecision(not violations, tuple(violations))


def llm_gateway_use_binding_from_dict(data: dict[str, Any]) -> LLMGatewayUseBindingRecord:
    expected = {
        "schema_version",
        "binding_ref",
        "owner_user_id",
        "service_principal_ref",
        "provider_ref",
        "auth_ref",
        "credential_pool_ref",
        "routing_policy_ref",
        "terminal_call_id",
        "invocation_id",
        "workflow_id",
        "terminal_record_kind",
        "terminal_status",
        "record_revision",
        "state_hash",
        "gateway_seal",
        "record_version",
    }
    if not isinstance(data, dict) or set(data) != expected:
        raise LLMUseBindingError("LLM use binding persisted field set is malformed")
    try:
        return LLMGatewayUseBindingRecord(**data)
    except (TypeError, ValueError) as exc:
        raise LLMUseBindingError("LLM use binding payload is malformed") from exc


class PersistentLLMUseBindingStore:
    """Append-only, checkpointed, owner-scoped gateway-use binding ledger."""

    def __init__(
        self,
        path: str | Path,
        *,
        seal_secret: bytes,
        terminal_record_resolver: TerminalRecordResolver,
    ) -> None:
        if len(seal_secret) < 32:
            raise ValueError("LLM use-binding seal secret must contain at least 32 bytes")
        if not callable(terminal_record_resolver):
            raise TypeError("terminal_record_resolver must be callable")
        self._path = Path(path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._lock_path = self._path.with_name(f".{self._path.name}.lock")
        self._checkpoint_path = self._path.with_name(f".{self._path.name}.head.json")
        self._seal_secret = bytes(seal_secret)
        self._terminal_record_resolver = terminal_record_resolver
        self._thread_lock = threading.RLock()
        self._quarantined_legacy_rows = 0
        self._poisoned = False
        self._prepare_journal()
        with self._locked_file():
            self._prepare_checkpoint()
            self._read_all_locked(validate_terminal=True)

    @property
    def path(self) -> Path:
        return self._path

    @property
    def checkpoint_path(self) -> Path:
        return self._checkpoint_path

    @property
    def quarantined_legacy_rows(self) -> int:
        with self._locked_file():
            self._read_all_locked(validate_terminal=True)
            return self._quarantined_legacy_rows

    def append(self, record: LLMGatewayUseBindingRecord) -> LLMGatewayUseBindingRecord:
        if not isinstance(record, LLMGatewayUseBindingRecord):
            raise TypeError("record must be LLMGatewayUseBindingRecord")
        self._validate_record(record, validate_terminal=True)
        with self._locked_file():
            rows = self._read_all_locked(validate_terminal=True)
            for existing in rows:
                if (
                    existing.binding_ref == record.binding_ref
                    or self._identity(existing) == self._identity(record)
                ):
                    if existing == record:
                        return existing
                    raise LLMUseBindingError(
                        "LLM use binding identity collision differs from persisted evidence"
                    )
            raw = (canonical_json(asdict(record)) + "\n").encode("utf-8")
            self._transactional_append_locked(raw)
        return record

    def read_all(self, *, owner_user_id: str) -> tuple[LLMGatewayUseBindingRecord, ...]:
        owner = self._owner(owner_user_id)
        with self._locked_file():
            rows = self._read_all_locked(validate_terminal=True)
        return tuple(row for row in rows if row.owner_user_id == owner)

    def binding(
        self,
        binding_ref: str,
        *,
        owner_user_id: str,
    ) -> LLMGatewayUseBindingRecord:
        owner = self._owner(owner_user_id)
        ref = str(binding_ref or "").strip()
        for row in self.read_all(owner_user_id=owner):
            if row.binding_ref == ref:
                return row
        raise KeyError("LLM use binding is not recorded for owner")

    def binding_for_terminal(
        self,
        terminal_call_id: str,
        *,
        owner_user_id: str,
    ) -> LLMGatewayUseBindingRecord:
        owner = self._owner(owner_user_id)
        call_id = str(terminal_call_id or "").strip()
        matches = [
            row for row in self.read_all(owner_user_id=owner)
            if row.terminal_call_id == call_id
        ]
        if len(matches) != 1:
            raise KeyError("terminal LLM call does not have exactly one owner binding")
        return matches[0]

    def validate_current(
        self,
        binding_ref: str,
        *,
        owner_user_id: str,
    ) -> LLMUseBindingDecision:
        try:
            record = self.binding(binding_ref, owner_user_id=owner_user_id)
            terminal = self._terminal_record_resolver(
                record.terminal_call_id,
                record.owner_user_id,
            )
        except (KeyError, LookupError, TypeError, ValueError, LLMRecordError) as exc:
            return LLMUseBindingDecision(
                False,
                (
                    LLMUseBindingViolation(
                        "llm_use_binding_current_resolution_failed",
                        f"current terminal evidence could not be resolved: {type(exc).__name__}",
                        ref=str(binding_ref or ""),
                    ),
                ),
            )
        return validate_llm_gateway_use_binding_terminal(
            record,
            terminal,
            seal_secret=self._seal_secret,
        )

    @staticmethod
    def _owner(value: str) -> str:
        owner = str(value or "").strip()
        if not owner or owner != value or not _safe_identifier(owner):
            raise LLMUseBindingError("owner_user_id must be a stable exact identifier")
        return owner

    @staticmethod
    def _identity(record: LLMGatewayUseBindingRecord) -> tuple[str, str]:
        return (record.owner_user_id, record.terminal_call_id)

    def _validate_record(
        self,
        record: LLMGatewayUseBindingRecord,
        *,
        validate_terminal: bool,
    ) -> None:
        decision = validate_llm_gateway_use_binding_shape(
            record,
            seal_secret=self._seal_secret,
        )
        if not decision.accepted:
            raise LLMUseBindingError(
                "invalid LLM use binding: "
                + ",".join(item.code for item in decision.violations)
            )
        if not validate_terminal:
            return
        terminal = self._terminal_record_resolver(
            record.terminal_call_id,
            record.owner_user_id,
        )
        current = validate_llm_gateway_use_binding_terminal(
            record,
            terminal,
            seal_secret=self._seal_secret,
        )
        if not current.accepted:
            raise LLMUseBindingError(
                "LLM use binding does not match terminal evidence: "
                + ",".join(item.code for item in current.violations)
            )

    @contextmanager
    def _locked_file(self) -> Iterator[None]:
        with self._thread_lock:
            flags = os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0)
            fd = os.open(self._lock_path, flags, 0o600)
            held = None
            try:
                info = os.fstat(fd)
                if not stat.S_ISREG(info.st_mode):
                    raise LLMUseBindingError("LLM use binding lock must be a regular file")
                if hasattr(os, "getuid") and info.st_uid != os.getuid():
                    raise LLMUseBindingError("LLM use binding lock has a different owner")
                os.fchmod(fd, 0o600)
                held = acquire_exclusive_fd(fd, timeout_seconds=10.0)
                self._assert_regular_owned(self._path, label="LLM use binding journal")
                yield
            finally:
                if held is not None:
                    held.release()
                os.close(fd)

    def _read_all_locked(
        self,
        *,
        validate_terminal: bool,
    ) -> list[LLMGatewayUseBindingRecord]:
        raw = self._verified_journal_bytes()
        if raw and not raw.endswith(b"\n"):
            raise LLMUseBindingError("LLM use binding journal has a torn tail")
        rows: list[LLMGatewayUseBindingRecord] = []
        identities: set[tuple[str, str]] = set()
        refs: set[str] = set()
        quarantined = 0
        for line_no, raw_line in enumerate(raw.splitlines(), start=1):
            if not raw_line.strip():
                raise LLMUseBindingError(
                    f"LLM use binding journal line {line_no} is empty"
                )
            try:
                text = raw_line.decode("utf-8")
                payload = json.loads(text)
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise LLMUseBindingError(
                    f"LLM use binding journal line {line_no} is malformed"
                ) from exc
            if not isinstance(payload, dict) or text != canonical_json(payload):
                raise LLMUseBindingError(
                    f"LLM use binding journal line {line_no} is not canonical JSON"
                )
            if payload.get("schema_version") in (None, 1):
                quarantined += 1
                continue
            record = llm_gateway_use_binding_from_dict(payload)
            self._validate_record(record, validate_terminal=validate_terminal)
            identity = self._identity(record)
            if identity in identities or record.binding_ref in refs:
                raise LLMUseBindingError("LLM use binding journal contains a duplicate identity")
            identities.add(identity)
            refs.add(record.binding_ref)
            rows.append(record)
        self._quarantined_legacy_rows = quarantined
        return rows

    def _checkpoint_body(self, journal: bytes) -> dict[str, Any]:
        return {
            "checkpoint_version": _CHECKPOINT_VERSION,
            "journal": self._path.name,
            "size": len(journal),
            "sha256": hashlib.sha256(journal).hexdigest(),
        }

    def _checkpoint_bytes(self, journal: bytes) -> bytes:
        body = self._checkpoint_body(journal)
        integrity = hmac.new(
            self._seal_secret,
            b"llm-use-binding-head\x00"
            + self._path.name.encode("utf-8")
            + b"\x00"
            + canonical_json(body).encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
        return (canonical_json({**body, "integrity": integrity}) + "\n").encode("utf-8")

    def _read_checkpoint(self) -> tuple[dict[str, Any], bytes]:
        if not os.path.lexists(self._checkpoint_path):
            raise LLMUseBindingError("LLM use binding checkpoint is missing")
        self._assert_regular_owned(self._checkpoint_path, label="LLM use binding checkpoint")
        raw = self._checkpoint_path.read_bytes()
        try:
            text = raw.decode("utf-8")
            row = json.loads(text)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise LLMUseBindingError("LLM use binding checkpoint is malformed") from exc
        if not isinstance(row, dict) or text != canonical_json(row) + "\n":
            raise LLMUseBindingError("LLM use binding checkpoint is not canonical JSON")
        if set(row) != {
            "checkpoint_version",
            "journal",
            "size",
            "sha256",
            "integrity",
        }:
            raise LLMUseBindingError("LLM use binding checkpoint fields are malformed")
        body = {key: value for key, value in row.items() if key != "integrity"}
        expected = hmac.new(
            self._seal_secret,
            b"llm-use-binding-head\x00"
            + self._path.name.encode("utf-8")
            + b"\x00"
            + canonical_json(body).encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
        if not hmac.compare_digest(expected, str(row["integrity"])):
            raise LLMUseBindingError("LLM use binding checkpoint HMAC verification failed")
        if (
            body["checkpoint_version"] != _CHECKPOINT_VERSION
            or body["journal"] != self._path.name
        ):
            raise LLMUseBindingError("LLM use binding checkpoint identity is invalid")
        return body, raw

    def _verified_journal_bytes(self) -> bytes:
        if self._poisoned:
            raise LLMUseBindingError(
                "LLM use binding store is fail-closed after an incomplete rollback"
            )
        self._assert_regular_owned(self._path, label="LLM use binding journal")
        checkpoint, _raw = self._read_checkpoint()
        journal = self._path.read_bytes()
        if checkpoint["size"] != len(journal):
            raise LLMUseBindingError("LLM use binding journal size diverged from checkpoint")
        digest = hashlib.sha256(journal).hexdigest()
        if not hmac.compare_digest(str(checkpoint["sha256"]), digest):
            raise LLMUseBindingError("LLM use binding journal digest diverged from checkpoint")
        return journal

    def _prepare_checkpoint(self) -> None:
        if os.path.lexists(self._checkpoint_path):
            self._verified_journal_bytes()
            return
        raw = self._path.read_bytes()
        if raw:
            legacy_only = True
            if not raw.endswith(b"\n"):
                legacy_only = False
            else:
                for line in raw.splitlines():
                    try:
                        payload = json.loads(line.decode("utf-8"))
                    except (UnicodeDecodeError, json.JSONDecodeError):
                        legacy_only = False
                        break
                    if not isinstance(payload, dict) or payload.get("schema_version") not in (None, 1):
                        legacy_only = False
                        break
            if not legacy_only:
                raise LLMUseBindingError(
                    "schema-v2 LLM use binding evidence is missing its checkpoint"
                )
        self._atomic_replace_bytes(self._checkpoint_path, self._checkpoint_bytes(raw))

    def _transactional_append_locked(self, payload: bytes) -> None:
        prior_journal = self._verified_journal_bytes()
        _checkpoint, prior_checkpoint = self._read_checkpoint()
        fd = -1
        try:
            fd = os.open(
                self._path,
                os.O_WRONLY | os.O_APPEND | getattr(os, "O_NOFOLLOW", 0),
            )
            self._write_all(fd, payload)
            os.fsync(fd)
            os.close(fd)
            fd = -1
            updated = prior_journal + payload
            self._atomic_replace_bytes(
                self._checkpoint_path,
                self._checkpoint_bytes(updated),
            )
            if self._verified_journal_bytes() != updated:
                raise LLMUseBindingError("LLM use binding append postcondition failed")
        except BaseException as exc:
            if fd >= 0:
                os.close(fd)
            rollback_errors = self._restore_transaction(
                prior_journal=prior_journal,
                prior_checkpoint=prior_checkpoint,
            )
            if rollback_errors:
                self._poisoned = True
                raise LLMUseBindingError(
                    "LLM use binding append failed and rollback is unverified; "
                    + "; ".join(rollback_errors)
                ) from exc
            raise

    def _restore_transaction(
        self,
        *,
        prior_journal: bytes,
        prior_checkpoint: bytes,
    ) -> list[str]:
        errors: list[str] = []
        try:
            fd = os.open(self._path, os.O_WRONLY | getattr(os, "O_NOFOLLOW", 0))
            try:
                os.ftruncate(fd, 0)
                self._write_all(fd, prior_journal)
                os.fsync(fd)
            finally:
                os.close(fd)
        except BaseException as exc:  # noqa: BLE001
            errors.append(f"journal restore: {type(exc).__name__}: {exc}")
        try:
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

    def _prepare_journal(self) -> None:
        if os.path.lexists(self._path):
            self._assert_regular_owned(self._path, label="LLM use binding journal")
            return
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
        try:
            fd = os.open(self._path, flags, 0o600)
        except FileExistsError:
            self._assert_regular_owned(self._path, label="LLM use binding journal")
            return
        try:
            os.fsync(fd)
        finally:
            os.close(fd)
        self._fsync_parent(self._path)

    def _atomic_replace_bytes(self, path: Path, payload: bytes) -> None:
        temporary = path.with_name(
            f".{path.name}.{os.getpid()}.{secrets.token_hex(8)}.tmp"
        )
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
        fd = os.open(temporary, flags, 0o600)
        try:
            os.fchmod(fd, 0o600)
            self._write_all(fd, payload)
            os.fsync(fd)
        except BaseException:
            os.close(fd)
            try:
                os.unlink(temporary)
            except FileNotFoundError:
                pass
            raise
        else:
            os.close(fd)
        try:
            os.replace(temporary, path)
            self._fsync_parent(path)
        except BaseException:
            try:
                os.unlink(temporary)
            except FileNotFoundError:
                pass
            raise

    @staticmethod
    def _write_all(fd: int, payload: bytes) -> None:
        offset = 0
        while offset < len(payload):
            written = os.write(fd, payload[offset:])
            if written <= 0:
                raise OSError("short write while persisting LLM use binding")
            offset += written

    @staticmethod
    def _fsync_parent(path: Path) -> None:
        flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
        fd = os.open(path.parent, flags)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)

    @staticmethod
    def _assert_regular_owned(path: Path, *, label: str) -> None:
        info = path.lstat()
        if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode):
            raise LLMUseBindingError(f"{label} must be a regular non-symlink file")
        if hasattr(os, "getuid") and info.st_uid != os.getuid():
            raise LLMUseBindingError(f"{label} is owned by a different runtime user")
        path.chmod(0o600)


__all__ = [
    "LLMGatewayUseBindingRecord",
    "LLMUseBindingDecision",
    "LLMUseBindingError",
    "LLMUseBindingViolation",
    "PersistentLLMUseBindingStore",
    "TerminalRecordResolver",
    "USE_BINDING_RECORD_VERSION",
    "USE_BINDING_SCHEMA_VERSION",
    "llm_gateway_use_binding_from_dict",
    "make_llm_gateway_use_binding",
    "seal_llm_gateway_use_binding",
    "validate_llm_gateway_use_binding_shape",
    "validate_llm_gateway_use_binding_terminal",
    "verify_llm_gateway_use_binding_seal",
]
