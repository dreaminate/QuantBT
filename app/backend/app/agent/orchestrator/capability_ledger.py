"""Owner/workflow-scoped durable records for GOAL section 7 runtime capabilities.

This ledger records only successful runtime actions.  It deliberately stores
content references and digests instead of prompts, model output, diffs, test
logs, tool arguments, or tool results.  The journal is append-only, HMAC
chained, checkpointed, fsynced, and reloaded under one cross-process lock before
every read or write.

The records are evidence of actions that already happened.  They are not a
section-closure receipt and do not turn an unavailable capability into a green
claim.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import stat
import tempfile
import threading
import uuid
from collections.abc import Iterable, Iterator, Mapping
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.cross_process_lock import acquire_exclusive_fd
from app.dag.engine import DAGTask
from app.dag.kernel import KernelRunResult
from app.lineage.ids import canonical_json
from app.llm.call_record import (
    IndependenceRecord,
    IndependenceVerdict,
    LLMCallRecord,
    ReviewSubjectBinding,
    ReviewSubjectBindingError,
    evaluate_independence,
    validate_review_subject_binding,
)

from .plan import AgentCodeChange, AgentPlan


AGENT_CAPABILITY_SCHEMA_VERSION = 1
AGENT_CAPABILITY_RECORD_VERSION = "agent_capability_record.v1"

CAPABILITY_PLAN = "plan"
CAPABILITY_REVIEW = "review"
CAPABILITY_REACT = "react"
CAPABILITY_REPLAY = "replay"
CAPABILITY_REPAIR = "repair"
CAPABILITY_CODE_CHANGE = "agent_code_change"
CAPABILITY_DAG_CHECKPOINT = "dag_checkpoint"
CAPABILITY_DAG_REPLAY = "dag_replay"
CAPABILITY_DAG_FORK = "dag_fork"
CAPABILITY_DAG_ROLLBACK = "dag_rollback"

_CAPABILITY_OPERATION = "_capability_operation"

CAPABILITY_KINDS = frozenset(
    {
        CAPABILITY_PLAN,
        CAPABILITY_REVIEW,
        CAPABILITY_REACT,
        CAPABILITY_REPLAY,
        CAPABILITY_REPAIR,
        CAPABILITY_CODE_CHANGE,
        CAPABILITY_DAG_CHECKPOINT,
        CAPABILITY_DAG_REPLAY,
        CAPABILITY_DAG_FORK,
        CAPABILITY_DAG_ROLLBACK,
    }
)
_RECORD_KINDS = CAPABILITY_KINDS | {_CAPABILITY_OPERATION}

_DAG_KIND_BY_MODE = {
    "run": CAPABILITY_DAG_CHECKPOINT,
    "replay": CAPABILITY_DAG_REPLAY,
    "fork": CAPABILITY_DAG_FORK,
    "rollback": CAPABILITY_DAG_ROLLBACK,
}
_DAG_SOURCE_PREFIX_BY_MODE = {
    "run": "dag_run",
    "replay": "replay",
    "fork": "fork",
    "rollback": "rollback",
}

_ROW_SCHEMA_VERSION = 1
_HEAD_SCHEMA_VERSION = 1
_GENESIS = "0" * 64
_KEY_BYTES = 32
_ROW_KEYS = frozenset(
    {
        "schema_version",
        "event_type",
        "owner_user_id",
        "workflow_id",
        "capability_kind",
        "revision",
        "previous_record_ref",
        "record",
        "previous_row_hash",
        "row_hash",
        "row_hmac",
    }
)
_HEAD_KEYS = frozenset(
    {
        "schema_version",
        "row_count",
        "last_row_hash",
        "last_row_hmac",
        "ledger_size",
        "checkpoint_hmac",
    }
)
_RECORD_KEYS = frozenset(
    {
        "record_ref",
        "owner_user_id",
        "workflow_id",
        "capability_kind",
        "revision",
        "previous_record_ref",
        "source_ref",
        "payload_hash",
        "payload",
        "created_at",
        "record_version",
    }
)
_OPERATION_PAYLOAD_KEYS = frozenset(
    {
        "operation_ref",
        "target_kind",
        "state",
        "request_ref",
        "prepared_record_ref",
        "capability_refs",
        "failure_ref",
    }
)
_OPERATION_STATES = frozenset({"prepared", "committed", "aborted"})
_REVIEW_PAYLOAD_KEYS = frozenset(
    {
        "source_event_ref",
        "builder_call_ref",
        "builder_provider",
        "builder_model",
        "builder_context_ref",
        "builder_response_ref",
        "builder_artifact_ref",
        "builder_output_ref",
        "verifier_call_ref",
        "verifier_provider",
        "verifier_model",
        "verifier_context_ref",
        "review_binding_schema_version",
        "review_criteria_ref",
        "review_subject_ref",
        "verifier_input_ref",
        "verifier_prompt_binding_ref",
        "declared_builder_call_ref",
        "independence_required",
        "independence_claimed_satisfied",
        "distinct_provider",
        "distinct_model",
        "independent",
        "verdict_reason_ref",
    }
)

# These names represent plaintext surfaces that this ledger must never persist.
# Digest/ref variants (for example prompt_digest and diff_ref) remain allowed.
_FORBIDDEN_PAYLOAD_KEYS = frozenset(
    {
        "api_key",
        "arguments",
        "chain_of_thought",
        "content",
        "description",
        "diff",
        "error",
        "failure_reason",
        "goal",
        "hidden_reasoning",
        "instruction",
        "messages",
        "output",
        "prompt",
        "prompt_plaintext",
        "raw_prompt",
        "reasoning_raw",
        "result",
        "response",
        "risk",
        "rollback_point",
        "secret",
        "secret_plaintext",
        "test_result",
        "token_plaintext",
        "tool_arguments",
        "tool_args",
        "tool_result",
    }
)


class AgentCapabilityError(ValueError):
    """A capability record is invalid, unavailable, or not current."""


class AgentCapabilityIntegrityError(AgentCapabilityError):
    """The durable journal, checkpoint, or revision chain is invalid."""


class AgentCapabilityCommitUncertain(AgentCapabilityIntegrityError):
    """An append failed and durable restoration could not be verified."""


@dataclass(frozen=True)
class AgentCapabilityViolation:
    code: str
    message: str
    field: str = ""
    ref: str = ""


@dataclass(frozen=True)
class AgentCapabilityDecision:
    accepted: bool
    violations: tuple[AgentCapabilityViolation, ...]


@dataclass(frozen=True)
class _AgentCapabilityDraft:
    capability_kind: str
    source_ref: str
    payload: Mapping[str, Any]


@dataclass(frozen=True)
class AgentCapabilityRecord:
    record_ref: str
    owner_user_id: str
    workflow_id: str
    capability_kind: str
    revision: int
    previous_record_ref: str
    source_ref: str
    payload_hash: str
    payload: dict[str, Any]
    created_at: str
    record_version: str = AGENT_CAPABILITY_RECORD_VERSION

    @property
    def canonical_record_ref(self) -> str:
        return _record_identity(
            owner_user_id=self.owner_user_id,
            workflow_id=self.workflow_id,
            capability_kind=self.capability_kind,
            revision=self.revision,
            previous_record_ref=self.previous_record_ref,
            source_ref=self.source_ref,
            payload_hash=self.payload_hash,
            payload=self.payload,
            created_at=self.created_at,
            record_version=self.record_version,
        )


def _sha256(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def _digest_ref(prefix: str, value: Any) -> str:
    return f"{prefix}:sha256:{_sha256(value)}"


def _required_text(value: Any, field_name: str) -> str:
    text = str(value or "").strip()
    if not text or "\x00" in text or "\n" in text or "\r" in text:
        raise AgentCapabilityError(f"{field_name} must be a stable non-empty single-line value")
    return text


def _required_ref(value: Any, field_name: str) -> str:
    ref = _required_text(value, field_name)
    if any(char.isspace() for char in ref):
        raise AgentCapabilityError(f"{field_name} must be an opaque reference, not plaintext")
    return ref


def validate_review_capability_evidence(
    *,
    owner_user_id: str,
    workflow_id: str,
    builder: Any,
    verifier: Any,
    payload: Mapping[str, Any],
) -> IndependenceVerdict:
    """Cross-bind a persisted Review claim to its exact terminal LLM calls.

    Both the producer and the closure resolver use this gate.  A Review head is
    therefore not self-authenticating: provider/model/context, the declared
    builder edge, independence flags, and verdict must all be derivable from two
    distinct successful terminal records in the same owner/workflow scope.
    """

    if not isinstance(builder, LLMCallRecord) or not isinstance(verifier, LLMCallRecord):
        raise AgentCapabilityError("review capability requires typed LLMCallRecord inputs")
    if not isinstance(verifier.independence, IndependenceRecord):
        raise AgentCapabilityError("review verifier requires typed independence metadata")
    if not isinstance(payload, Mapping) or set(payload) != _REVIEW_PAYLOAD_KEYS:
        raise AgentCapabilityError("review capability payload has an invalid schema")

    owner = _required_text(owner_user_id, "owner_user_id")
    workflow = _required_text(workflow_id, "workflow_id")
    for label, record in (("builder", builder), ("verifier", verifier)):
        if record.owner_user_id != owner or record.workflow_id != workflow:
            raise AgentCapabilityError(
                f"{label} review record must match the capability owner/workflow"
            )
        if record.record_kind != "terminal" or record.status != "ok":
            raise AgentCapabilityError(
                f"{label} review record must be a successful terminal LLM call"
            )
        _required_ref(record.call_id, f"{label}_call_ref")
        _required_ref(record.prompt_digest, f"{label}_context_ref")
        _required_text(record.provider, f"{label}_provider")
        _required_text(record.model, f"{label}_model")

    if builder.call_id == verifier.call_id:
        raise AgentCapabilityError("review builder and verifier must be distinct terminal calls")
    if verifier.independence.required is not True:
        raise AgentCapabilityError("review capability requires an independence challenge")
    if verifier.independence.builder_call_id != builder.call_id:
        raise AgentCapabilityError(
            "verifier independence metadata must reference the exact builder call"
        )

    subject_binding = ReviewSubjectBinding(
        builder_call_ref=str(payload.get("builder_call_ref") or ""),
        builder_response_ref=str(payload.get("builder_response_ref") or ""),
        builder_artifact_ref=str(payload.get("builder_artifact_ref") or ""),
        builder_output_ref=str(payload.get("builder_output_ref") or ""),
        review_criteria_ref=str(payload.get("review_criteria_ref") or ""),
        review_subject_ref=str(payload.get("review_subject_ref") or ""),
        verifier_input_ref=str(payload.get("verifier_input_ref") or ""),
        verifier_context_ref=str(payload.get("verifier_context_ref") or ""),
        verifier_prompt_binding_ref=str(
            payload.get("verifier_prompt_binding_ref") or ""
        ),
        schema_version=payload.get("review_binding_schema_version"),
    )
    try:
        validate_review_subject_binding(
            builder=builder,
            verifier=verifier,
            binding=subject_binding,
        )
    except ReviewSubjectBindingError as exc:
        raise AgentCapabilityError(
            "review subject binding contradicts terminal evidence"
        ) from exc

    distinct_provider = builder.provider != verifier.provider
    distinct_model = builder.model != verifier.model
    if (
        verifier.independence.distinct_provider is not distinct_provider
        or verifier.independence.distinct_model is not distinct_model
    ):
        raise AgentCapabilityError(
            "verifier independence metadata contradicts the exact call records"
        )
    evaluated = evaluate_independence(builder, verifier)
    if verifier.independence.satisfied is not evaluated.independent:
        raise AgentCapabilityError(
            "verifier independence metadata contradicts the canonical evaluation"
        )

    expected = {
        "source_event_ref": _required_ref(payload.get("source_event_ref"), "source_event_ref"),
        "builder_call_ref": builder.call_id,
        "builder_provider": builder.provider,
        "builder_model": builder.model,
        "builder_context_ref": builder.prompt_digest,
        "builder_response_ref": subject_binding.builder_response_ref,
        "builder_artifact_ref": subject_binding.builder_artifact_ref,
        "builder_output_ref": subject_binding.builder_output_ref,
        "verifier_call_ref": verifier.call_id,
        "verifier_provider": verifier.provider,
        "verifier_model": verifier.model,
        "verifier_context_ref": verifier.prompt_digest,
        "review_binding_schema_version": subject_binding.schema_version,
        "review_criteria_ref": subject_binding.review_criteria_ref,
        "review_subject_ref": subject_binding.review_subject_ref,
        "verifier_input_ref": subject_binding.verifier_input_ref,
        "verifier_prompt_binding_ref": subject_binding.verifier_prompt_binding_ref,
        "declared_builder_call_ref": verifier.independence.builder_call_id,
        "independence_required": True,
        "independence_claimed_satisfied": verifier.independence.satisfied,
        "distinct_provider": distinct_provider,
        "distinct_model": distinct_model,
        "independent": evaluated.independent,
        "verdict_reason_ref": _digest_ref("review_reason", evaluated.reason),
    }
    mismatched = sorted(
        key for key, expected_value in expected.items() if payload.get(key) != expected_value
    )
    if mismatched:
        raise AgentCapabilityError(
            "review capability payload contradicts terminal evidence: "
            + ",".join(mismatched)
        )
    return evaluated


def _checkpoint_ref(value: Any) -> str:
    return f"checkpoint:{_required_ref(value, 'checkpoint_ref')}"


def _json_payload(value: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise AgentCapabilityError("capability payload must be a mapping")
    try:
        # Reject NaN/Infinity before using the repository canonical encoder.
        json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False)
        return json.loads(canonical_json(dict(value)))
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        raise AgentCapabilityError("capability payload must be finite canonical JSON") from exc


def _walk_keys(value: Any) -> Iterator[str]:
    if isinstance(value, Mapping):
        for key, child in value.items():
            yield str(key)
            yield from _walk_keys(child)
    elif isinstance(value, (tuple, list)):
        for child in value:
            yield from _walk_keys(child)


def _assert_private_payload(payload: Mapping[str, Any], secret_values: Iterable[str]) -> None:
    forbidden = sorted(set(_walk_keys(payload)).intersection(_FORBIDDEN_PAYLOAD_KEYS))
    if forbidden:
        raise AgentCapabilityError(
            "capability payload contains forbidden plaintext fields: " + ",".join(forbidden)
        )
    serialized = canonical_json(payload)
    for secret in secret_values:
        token = str(secret or "")
        if token and len(token) >= 8 and token in serialized:
            raise AgentCapabilityError(
                f"known plaintext secret (len={len(token)}) entered capability evidence"
            )


def _record_identity(
    *,
    owner_user_id: str,
    workflow_id: str,
    capability_kind: str,
    revision: int,
    previous_record_ref: str,
    source_ref: str,
    payload_hash: str,
    payload: Mapping[str, Any],
    created_at: str,
    record_version: str,
) -> str:
    return "agent_capability:" + _sha256(
        {
            "owner_user_id": owner_user_id,
            "workflow_id": workflow_id,
            "capability_kind": capability_kind,
            "revision": revision,
            "previous_record_ref": previous_record_ref,
            "source_ref": source_ref,
            "payload_hash": payload_hash,
            "payload": dict(payload),
            "created_at": created_at,
            "record_version": record_version,
        }
    )


def _record_from_dict(raw: Any) -> AgentCapabilityRecord:
    if not isinstance(raw, dict) or set(raw) != _RECORD_KEYS:
        raise AgentCapabilityIntegrityError("capability record has unknown or missing fields")
    payload = _json_payload(raw["payload"])
    return AgentCapabilityRecord(
        record_ref=raw["record_ref"],
        owner_user_id=raw["owner_user_id"],
        workflow_id=raw["workflow_id"],
        capability_kind=raw["capability_kind"],
        revision=raw["revision"],
        previous_record_ref=raw["previous_record_ref"],
        source_ref=raw["source_ref"],
        payload_hash=raw["payload_hash"],
        payload=payload,
        created_at=raw["created_at"],
        record_version=raw["record_version"],
    )


def _validate_record_shape(record: AgentCapabilityRecord) -> None:
    _required_text(record.owner_user_id, "owner_user_id")
    _required_text(record.workflow_id, "workflow_id")
    _required_ref(record.source_ref, "source_ref")
    if record.capability_kind not in _RECORD_KINDS:
        raise AgentCapabilityIntegrityError("unsupported capability kind")
    if type(record.revision) is not int or record.revision <= 0:
        raise AgentCapabilityIntegrityError("capability revision must be a positive exact integer")
    if record.record_version != AGENT_CAPABILITY_RECORD_VERSION:
        raise AgentCapabilityIntegrityError("unsupported capability record version")
    if (record.revision == 1) != (not record.previous_record_ref):
        raise AgentCapabilityIntegrityError("capability previous-record chain is invalid")
    if record.revision > 1 and not record.previous_record_ref.startswith("agent_capability:"):
        raise AgentCapabilityIntegrityError("later capability revisions require a prior record ref")
    if record.payload_hash != _sha256(record.payload):
        raise AgentCapabilityIntegrityError("capability payload hash mismatch")
    if record.record_ref != record.canonical_record_ref:
        raise AgentCapabilityIntegrityError("capability record identity mismatch")
    if record.capability_kind == _CAPABILITY_OPERATION:
        _validate_operation_payload(record.payload)


def _validate_operation_payload(payload: Mapping[str, Any]) -> None:
    if set(payload) != _OPERATION_PAYLOAD_KEYS:
        raise AgentCapabilityIntegrityError(
            "capability operation has unknown or missing fields"
        )
    operation_ref = _required_ref(payload.get("operation_ref"), "operation_ref")
    target_kind = _required_text(payload.get("target_kind"), "target_kind")
    state = _required_text(payload.get("state"), "state")
    request_ref = _required_ref(payload.get("request_ref"), "request_ref")
    prepared_ref = str(payload.get("prepared_record_ref") or "")
    failure_ref = str(payload.get("failure_ref") or "")
    raw_capability_refs = payload.get("capability_refs")
    if (
        not operation_ref.startswith("agent_capability_operation:")
        or target_kind not in CAPABILITY_KINDS
        or state not in _OPERATION_STATES
        or not request_ref
        or not isinstance(raw_capability_refs, list)
    ):
        raise AgentCapabilityIntegrityError("capability operation shape is invalid")
    capability_refs = tuple(
        _required_ref(ref, "capability_ref") for ref in raw_capability_refs
    )
    if len(capability_refs) != len(set(capability_refs)):
        raise AgentCapabilityIntegrityError(
            "capability operation contains duplicate capability refs"
        )
    if state == "prepared":
        if prepared_ref or capability_refs or failure_ref:
            raise AgentCapabilityIntegrityError(
                "prepared capability operation cannot claim an outcome"
            )
        return
    _required_ref(prepared_ref, "prepared_record_ref")
    if not prepared_ref.startswith("agent_capability:"):
        raise AgentCapabilityIntegrityError(
            "terminal capability operation must bind its prepared record"
        )
    if state == "committed":
        if not capability_refs or failure_ref:
            raise AgentCapabilityIntegrityError(
                "committed capability operation requires capability refs only"
            )
        if any(not ref.startswith("agent_capability:") for ref in capability_refs):
            raise AgentCapabilityIntegrityError(
                "committed capability operation contains an invalid capability ref"
            )
        return
    if capability_refs or not failure_ref:
        raise AgentCapabilityIntegrityError(
            "aborted capability operation requires one failure ref and no capabilities"
        )
    _required_ref(failure_ref, "failure_ref")


def capability_path_for_event_ledger(path: str | Path) -> Path:
    source = Path(path)
    if source.name == "agent_workflow_events.jsonl":
        return source.with_name("agent_capabilities.jsonl")
    suffix = source.suffix or ".jsonl"
    return source.with_name(f"{source.stem}.capabilities{suffix}")


class PersistentAgentCapabilityLedger:
    """HMAC-chained append-only capability journal with exact per-kind heads."""

    def __init__(self, path: str | Path, *, secret_values: Iterable[str] = ()) -> None:
        self._path = Path(path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._lock_path = self._path.with_suffix(self._path.suffix + ".lock")
        self._key_path = self._path.with_suffix(self._path.suffix + ".hmac.key")
        self._head_path = self._path.with_suffix(self._path.suffix + ".head")
        self._secret_values = tuple(str(value) for value in secret_values if str(value or ""))
        self._lock = threading.RLock()
        self._records: dict[tuple[str, str], AgentCapabilityRecord] = {}
        self._heads: dict[tuple[str, str, str], AgentCapabilityRecord] = {}
        with self._process_lock():
            self._prepare_journal()
            if not os.path.lexists(self._key_path) and self._path.stat().st_size:
                raise AgentCapabilityIntegrityError(
                    "capability HMAC key is missing for a nonempty journal"
                )
            self._key = self._load_or_create_key()
            if not os.path.lexists(self._head_path):
                if self._path.stat().st_size:
                    raise AgentCapabilityIntegrityError(
                        "capability checkpoint is missing for a nonempty journal"
                    )
                self._write_checkpoint([], ledger_size=0)
            self._reload_unlocked()

    @property
    def path(self) -> Path:
        return self._path

    @property
    def head_path(self) -> Path:
        return self._head_path

    @property
    def key_path(self) -> Path:
        return self._key_path

    @contextmanager
    def _process_lock(self) -> Iterator[None]:
        flags = os.O_CREAT | os.O_RDWR | getattr(os, "O_NOFOLLOW", 0)
        fd = os.open(self._lock_path, flags, 0o600)
        held = None
        try:
            info = os.fstat(fd)
            if not stat.S_ISREG(info.st_mode):
                raise AgentCapabilityIntegrityError("capability lock must be a regular file")
            if hasattr(os, "getuid") and info.st_uid != os.getuid():
                raise AgentCapabilityIntegrityError("capability lock has a different owner")
            os.fchmod(fd, 0o600)
            held = acquire_exclusive_fd(fd, timeout_seconds=10.0)
            yield
        finally:
            if held is not None:
                held.release()
            os.close(fd)

    @staticmethod
    def _fsync_parent(path: Path) -> None:
        fd = os.open(path.parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
        try:
            os.fsync(fd)
        finally:
            os.close(fd)

    @staticmethod
    def _assert_private_regular(path: Path, *, label: str) -> os.stat_result:
        try:
            info = path.lstat()
        except FileNotFoundError as exc:
            raise AgentCapabilityIntegrityError(f"missing {label}: {path}") from exc
        if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode):
            raise AgentCapabilityIntegrityError(f"{label} must be a regular non-symlink file")
        if hasattr(os, "getuid") and info.st_uid != os.getuid():
            raise AgentCapabilityIntegrityError(f"{label} has a different owner")
        if stat.S_IMODE(info.st_mode) != 0o600:
            raise AgentCapabilityIntegrityError(f"{label} must have mode 0600")
        return info

    @classmethod
    def _read_private_bytes(cls, path: Path, *, label: str) -> bytes:
        before = cls._assert_private_regular(path, label=label)
        fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
        try:
            opened = os.fstat(fd)
            if (
                not stat.S_ISREG(opened.st_mode)
                or (opened.st_dev, opened.st_ino) != (before.st_dev, before.st_ino)
                or stat.S_IMODE(opened.st_mode) != 0o600
            ):
                raise AgentCapabilityIntegrityError(f"{label} changed during secure open")
            chunks: list[bytes] = []
            while True:
                chunk = os.read(fd, 65536)
                if not chunk:
                    break
                chunks.append(chunk)
            return b"".join(chunks)
        finally:
            os.close(fd)

    @classmethod
    def _create_private_file(cls, path: Path, payload: bytes, *, label: str) -> None:
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
        fd = os.open(path, flags, 0o600)
        try:
            os.fchmod(fd, 0o600)
            view = memoryview(payload)
            while view:
                written = os.write(fd, view)
                if written <= 0:
                    raise OSError(f"short write creating {label}")
                view = view[written:]
            os.fsync(fd)
        finally:
            os.close(fd)
        cls._fsync_parent(path)
        cls._assert_private_regular(path, label=label)

    def _prepare_journal(self) -> None:
        if not os.path.lexists(self._path):
            self._create_private_file(self._path, b"", label="capability journal")
            return
        info = self._path.lstat()
        if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode):
            raise AgentCapabilityIntegrityError(
                "capability journal must be a regular non-symlink file"
            )
        if hasattr(os, "getuid") and info.st_uid != os.getuid():
            raise AgentCapabilityIntegrityError("capability journal has a different owner")
        os.chmod(self._path, 0o600)

    def _load_or_create_key(self) -> bytes:
        if not os.path.lexists(self._key_path):
            self._create_private_file(
                self._key_path, os.urandom(_KEY_BYTES), label="capability HMAC key"
            )
        key = self._read_private_bytes(self._key_path, label="capability HMAC key")
        if len(key) != _KEY_BYTES:
            raise AgentCapabilityIntegrityError("capability HMAC key must contain 32 bytes")
        return key

    def _hmac(self, domain: bytes, value: Mapping[str, Any]) -> str:
        message = (
            b"quantbt:agent-capability:v1\x00"
            + domain
            + b"\x00"
            + canonical_json(dict(value)).encode("utf-8")
        )
        return hmac.new(self._key, message, hashlib.sha256).hexdigest()

    def _atomic_private_write(self, path: Path, payload: bytes, *, label: str) -> None:
        if os.path.lexists(path):
            self._assert_private_regular(path, label=label)
        fd, raw_tmp = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
        tmp = Path(raw_tmp)
        try:
            os.fchmod(fd, 0o600)
            view = memoryview(payload)
            while view:
                written = os.write(fd, view)
                if written <= 0:
                    raise OSError(f"short atomic write for {label}")
                view = view[written:]
            os.fsync(fd)
            os.close(fd)
            fd = -1
            os.replace(tmp, path)
            self._assert_private_regular(path, label=label)
            self._fsync_parent(path)
        finally:
            if fd >= 0:
                os.close(fd)
            try:
                tmp.unlink()
            except FileNotFoundError:
                pass

    def _checkpoint_payload(
        self, rows: list[dict[str, Any]], *, ledger_size: int
    ) -> dict[str, Any]:
        return {
            "schema_version": _HEAD_SCHEMA_VERSION,
            "row_count": len(rows),
            "last_row_hash": rows[-1]["row_hash"] if rows else _GENESIS,
            "last_row_hmac": rows[-1]["row_hmac"] if rows else _GENESIS,
            "ledger_size": ledger_size,
        }

    def _write_checkpoint(self, rows: list[dict[str, Any]], *, ledger_size: int) -> None:
        body = self._checkpoint_payload(rows, ledger_size=ledger_size)
        head = {**body, "checkpoint_hmac": self._hmac(b"checkpoint", body)}
        self._atomic_private_write(
            self._head_path,
            (canonical_json(head) + "\n").encode("utf-8"),
            label="capability checkpoint",
        )

    def _read_checkpoint(self) -> dict[str, Any]:
        raw = self._read_private_bytes(self._head_path, label="capability checkpoint")
        if not raw.endswith(b"\n") or raw.count(b"\n") != 1:
            raise AgentCapabilityIntegrityError(
                "capability checkpoint must be one canonical JSON line"
            )
        try:
            text = raw[:-1].decode("utf-8")
            head = json.loads(text)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise AgentCapabilityIntegrityError("capability checkpoint is malformed") from exc
        if not isinstance(head, dict) or set(head) != _HEAD_KEYS:
            raise AgentCapabilityIntegrityError(
                "capability checkpoint has unknown or missing fields"
            )
        if text != canonical_json(head):
            raise AgentCapabilityIntegrityError("capability checkpoint is non-canonical")
        body = {key: value for key, value in head.items() if key != "checkpoint_hmac"}
        if body.get("schema_version") != _HEAD_SCHEMA_VERSION:
            raise AgentCapabilityIntegrityError("unsupported capability checkpoint schema")
        if (
            type(body.get("row_count")) is not int
            or body["row_count"] < 0
            or type(body.get("ledger_size")) is not int
            or body["ledger_size"] < 0
            or not isinstance(body.get("last_row_hash"), str)
            or len(body["last_row_hash"]) != 64
            or not isinstance(body.get("last_row_hmac"), str)
            or len(body["last_row_hmac"]) != 64
        ):
            raise AgentCapabilityIntegrityError("capability checkpoint values are invalid")
        expected = self._hmac(b"checkpoint", body)
        if not hmac.compare_digest(str(head.get("checkpoint_hmac") or ""), expected):
            raise AgentCapabilityIntegrityError("capability checkpoint HMAC mismatch")
        return body

    def _read_rows_unlocked(self) -> list[dict[str, Any]]:
        persisted_key = self._read_private_bytes(self._key_path, label="capability HMAC key")
        if len(persisted_key) != _KEY_BYTES or not hmac.compare_digest(persisted_key, self._key):
            raise AgentCapabilityIntegrityError(
                "capability HMAC key changed after ledger initialization"
            )
        raw = self._read_private_bytes(self._path, label="capability journal")
        if raw and not raw.endswith(b"\n"):
            raise AgentCapabilityIntegrityError("capability journal has a torn tail")
        rows: list[dict[str, Any]] = []
        previous_row_hash = _GENESIS
        expected_revisions: dict[tuple[str, str, str], int] = {}
        previous_records: dict[tuple[str, str, str], str] = {}
        seen_refs: set[str] = set()
        for line_no, raw_line in enumerate(raw.splitlines(), start=1):
            try:
                text = raw_line.decode("utf-8")
                row = json.loads(text)
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise AgentCapabilityIntegrityError(
                    f"invalid capability journal row at line {line_no}"
                ) from exc
            if not isinstance(row, dict) or set(row) != _ROW_KEYS:
                raise AgentCapabilityIntegrityError(
                    f"unknown capability journal fields at line {line_no}"
                )
            if text != canonical_json(row):
                raise AgentCapabilityIntegrityError(
                    f"non-canonical capability journal row at line {line_no}"
                )
            if row.get("schema_version") != _ROW_SCHEMA_VERSION:
                raise AgentCapabilityIntegrityError("unsupported capability journal schema")
            base = {key: value for key, value in row.items() if key not in {"row_hash", "row_hmac"}}
            expected_hash = _sha256(base)
            if (
                row.get("previous_row_hash") != previous_row_hash
                or row.get("row_hash") != expected_hash
            ):
                raise AgentCapabilityIntegrityError("capability row hash chain mismatch")
            hmac_body = {**base, "row_hash": row["row_hash"]}
            expected_hmac = self._hmac(b"row", hmac_body)
            if not hmac.compare_digest(str(row.get("row_hmac") or ""), expected_hmac):
                raise AgentCapabilityIntegrityError("capability row HMAC mismatch")
            record = _record_from_dict(row["record"])
            _validate_record_shape(record)
            _assert_private_payload(record.payload, self._secret_values)
            scope = (record.owner_user_id, record.workflow_id, record.capability_kind)
            expected_revision = expected_revisions.get(scope, 1)
            expected_previous = previous_records.get(scope, "")
            if (
                row.get("event_type") != "agent_capability_recorded"
                or row.get("owner_user_id") != record.owner_user_id
                or row.get("workflow_id") != record.workflow_id
                or row.get("capability_kind") != record.capability_kind
                or row.get("revision") != record.revision
                or row.get("previous_record_ref") != record.previous_record_ref
                or record.revision != expected_revision
                or record.previous_record_ref != expected_previous
            ):
                raise AgentCapabilityIntegrityError(
                    "capability envelope or revision chain mismatch"
                )
            if record.record_ref in seen_refs:
                raise AgentCapabilityIntegrityError("duplicate capability record identity")
            seen_refs.add(record.record_ref)
            expected_revisions[scope] = expected_revision + 1
            previous_records[scope] = record.record_ref
            rows.append(row)
            previous_row_hash = row["row_hash"]
        checkpoint = self._read_checkpoint()
        if (
            checkpoint["row_count"] != len(rows)
            or checkpoint["ledger_size"] != len(raw)
            or checkpoint["last_row_hash"] != (rows[-1]["row_hash"] if rows else _GENESIS)
            or checkpoint["last_row_hmac"] != (rows[-1]["row_hmac"] if rows else _GENESIS)
        ):
            raise AgentCapabilityIntegrityError(
                "capability checkpoint does not match the complete journal"
            )
        return rows

    def _reload_unlocked(self) -> list[dict[str, Any]]:
        rows = self._read_rows_unlocked()
        records: dict[tuple[str, str], AgentCapabilityRecord] = {}
        heads: dict[tuple[str, str, str], AgentCapabilityRecord] = {}
        for row in rows:
            record = _record_from_dict(row["record"])
            records[(record.owner_user_id, record.record_ref)] = record
            heads[(record.owner_user_id, record.workflow_id, record.capability_kind)] = record
        self._records = records
        self._heads = heads
        return rows

    def _build_records_unlocked(
        self,
        *,
        owner_user_id: str,
        workflow_id: str,
        drafts: tuple[_AgentCapabilityDraft, ...],
    ) -> tuple[AgentCapabilityRecord, ...]:
        owner = _required_text(owner_user_id, "owner_user_id")
        workflow = _required_text(workflow_id, "workflow_id")
        heads = dict(self._heads)
        records: list[AgentCapabilityRecord] = []
        for draft in drafts:
            kind = _required_text(draft.capability_kind, "capability_kind")
            if kind not in _RECORD_KINDS:
                raise AgentCapabilityError(f"unsupported capability kind: {kind}")
            source_ref = _required_ref(draft.source_ref, "source_ref")
            payload = _json_payload(draft.payload)
            _assert_private_payload(payload, self._secret_values)
            previous = heads.get((owner, workflow, kind))
            revision = 1 if previous is None else previous.revision + 1
            previous_ref = "" if previous is None else previous.record_ref
            created_at = datetime.now(UTC).isoformat()
            provisional = AgentCapabilityRecord(
                record_ref="",
                owner_user_id=owner,
                workflow_id=workflow,
                capability_kind=kind,
                revision=revision,
                previous_record_ref=previous_ref,
                source_ref=source_ref,
                payload_hash=_sha256(payload),
                payload=payload,
                created_at=created_at,
            )
            record = AgentCapabilityRecord(
                **{**asdict(provisional), "record_ref": provisional.canonical_record_ref}
            )
            _validate_record_shape(record)
            records.append(record)
            heads[(owner, workflow, kind)] = record
        return tuple(records)

    def _rows_for_records(
        self,
        records: tuple[AgentCapabilityRecord, ...],
        *,
        previous_row_hash: str,
    ) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        prior = previous_row_hash
        for record in records:
            base = {
                "schema_version": _ROW_SCHEMA_VERSION,
                "event_type": "agent_capability_recorded",
                "owner_user_id": record.owner_user_id,
                "workflow_id": record.workflow_id,
                "capability_kind": record.capability_kind,
                "revision": record.revision,
                "previous_record_ref": record.previous_record_ref,
                "record": asdict(record),
                "previous_row_hash": prior,
            }
            row_hash = _sha256(base)
            hmac_body = {**base, "row_hash": row_hash}
            row = {**hmac_body, "row_hmac": self._hmac(b"row", hmac_body)}
            rows.append(row)
            prior = row_hash
        return rows

    def _append_rows_unlocked(
        self, existing_rows: list[dict[str, Any]], new_rows: list[dict[str, Any]]
    ) -> None:
        payload = "".join(canonical_json(row) + "\n" for row in new_rows).encode("utf-8")
        original_size = self._path.stat().st_size
        old_checkpoint = self._read_private_bytes(
            self._head_path, label="capability checkpoint"
        )
        checkpoint_started = False
        try:
            flags = os.O_WRONLY | os.O_APPEND | getattr(os, "O_NOFOLLOW", 0)
            fd = os.open(self._path, flags)
            try:
                view = memoryview(payload)
                while view:
                    written = os.write(fd, view)
                    if written <= 0:
                        raise OSError("short capability journal append")
                    view = view[written:]
                os.fsync(fd)
            finally:
                os.close(fd)
            checkpoint_started = True
            self._write_checkpoint(
                [*existing_rows, *new_rows], ledger_size=original_size + len(payload)
            )
        except Exception as exc:
            recovery_errors: list[BaseException] = []
            try:
                with self._path.open("r+b") as rollback:
                    rollback.truncate(original_size)
                    rollback.flush()
                    os.fsync(rollback.fileno())
            except Exception as rollback_exc:  # noqa: BLE001 - commit status becomes uncertain.
                recovery_errors.append(rollback_exc)
            if checkpoint_started:
                try:
                    self._atomic_private_write(
                        self._head_path,
                        old_checkpoint,
                        label="capability checkpoint",
                    )
                except Exception as checkpoint_exc:  # noqa: BLE001
                    recovery_errors.append(checkpoint_exc)
            if recovery_errors:
                raise AgentCapabilityCommitUncertain(
                    "capability append failed and durable restoration is unverified"
                ) from exc
            raise

    def _record_actions_unlocked(
        self,
        *,
        owner_user_id: str,
        workflow_id: str,
        drafts: tuple[_AgentCapabilityDraft, ...],
    ) -> tuple[AgentCapabilityRecord, ...]:
        existing_rows = self._reload_unlocked()
        records = self._build_records_unlocked(
            owner_user_id=owner_user_id,
            workflow_id=workflow_id,
            drafts=drafts,
        )
        prior_hash = existing_rows[-1]["row_hash"] if existing_rows else _GENESIS
        new_rows = self._rows_for_records(records, previous_row_hash=prior_hash)
        self._append_rows_unlocked(existing_rows, new_rows)
        try:
            self._reload_unlocked()
        except Exception as exc:
            raise AgentCapabilityCommitUncertain(
                "capability append committed but durable verification failed"
            ) from exc
        for record in records:
            persisted = self._records.get((record.owner_user_id, record.record_ref))
            if persisted != record:
                raise AgentCapabilityCommitUncertain(
                    "capability append returned without the exact record on durable reload"
                )
        return records

    def _record_actions(
        self,
        *,
        owner_user_id: str,
        workflow_id: str,
        drafts: Iterable[_AgentCapabilityDraft],
    ) -> tuple[AgentCapabilityRecord, ...]:
        action_drafts = tuple(drafts)
        if not action_drafts:
            raise AgentCapabilityError("at least one capability action is required")
        with self._lock, self._process_lock():
            return self._record_actions_unlocked(
                owner_user_id=owner_user_id,
                workflow_id=workflow_id,
                drafts=action_drafts,
            )

    def _record_action(
        self,
        *,
        owner_user_id: str,
        workflow_id: str,
        capability_kind: str,
        source_ref: str,
        payload: Mapping[str, Any],
    ) -> AgentCapabilityRecord:
        return self._record_actions(
            owner_user_id=owner_user_id,
            workflow_id=workflow_id,
            drafts=(_AgentCapabilityDraft(capability_kind, source_ref, payload),),
        )[0]

    def _latest_operation_unlocked(
        self,
        *,
        owner_user_id: str,
        workflow_id: str,
        operation_ref: str,
    ) -> AgentCapabilityRecord | None:
        latest = None
        for record in self._records.values():
            if (
                record.owner_user_id == owner_user_id
                and record.workflow_id == workflow_id
                and record.capability_kind == _CAPABILITY_OPERATION
                and record.payload.get("operation_ref") == operation_ref
            ):
                latest = record
        return latest

    def prepare_operation(
        self,
        *,
        owner_user_id: str,
        workflow_id: str,
        target_kind: str,
        request_ref: str,
    ) -> AgentCapabilityRecord:
        """Durably prepare an action before any cross-store source mutation.

        Prepared rows are coordination evidence, not successful capabilities,
        and are intentionally hidden from ``records()``.  A missing terminal
        transition remains restart-visible through ``unresolved_operations``.
        """

        owner = _required_text(owner_user_id, "owner_user_id")
        workflow = _required_text(workflow_id, "workflow_id")
        target = _required_text(target_kind, "target_kind")
        if target not in CAPABILITY_KINDS:
            raise AgentCapabilityError("operation target must be a capability kind")
        request = _required_ref(request_ref, "request_ref")
        operation_ref = _digest_ref(
            "agent_capability_operation",
            {
                "owner_user_id": owner,
                "workflow_id": workflow,
                "target_kind": target,
                "request_ref": request,
                "nonce": uuid.uuid4().hex,
            },
        )
        return self._record_action(
            owner_user_id=owner,
            workflow_id=workflow,
            capability_kind=_CAPABILITY_OPERATION,
            source_ref=request,
            payload={
                "operation_ref": operation_ref,
                "target_kind": target,
                "state": "prepared",
                "request_ref": request,
                "prepared_record_ref": "",
                "capability_refs": [],
                "failure_ref": "",
            },
        )

    def _transition_operation(
        self,
        *,
        owner_user_id: str,
        workflow_id: str,
        prepared_record_ref: str,
        state: str,
        capability_refs: Iterable[str] = (),
        failure_ref: str = "",
    ) -> AgentCapabilityRecord:
        owner = _required_text(owner_user_id, "owner_user_id")
        workflow = _required_text(workflow_id, "workflow_id")
        prepared_ref = _required_ref(prepared_record_ref, "prepared_record_ref")
        terminal_state = _required_text(state, "state")
        refs = tuple(
            dict.fromkeys(_required_ref(ref, "capability_ref") for ref in capability_refs)
        )
        failure = str(failure_ref or "")
        with self._lock, self._process_lock():
            self._reload_unlocked()
            prepared = self._records.get((owner, prepared_ref))
            if (
                prepared is None
                or prepared.workflow_id != workflow
                or prepared.capability_kind != _CAPABILITY_OPERATION
                or prepared.payload.get("state") != "prepared"
            ):
                raise AgentCapabilityError(
                    "prepared capability operation is unavailable for owner/workflow"
                )
            operation_ref = str(prepared.payload["operation_ref"])
            latest = self._latest_operation_unlocked(
                owner_user_id=owner,
                workflow_id=workflow,
                operation_ref=operation_ref,
            )
            if latest is None:
                raise AgentCapabilityIntegrityError(
                    "prepared capability operation disappeared"
                )
            latest_state = str(latest.payload.get("state") or "")
            if latest_state != "prepared":
                if latest_state == terminal_state:
                    expected_refs = tuple(latest.payload.get("capability_refs") or ())
                    if expected_refs == refs and str(latest.payload.get("failure_ref") or "") == failure:
                        return latest
                raise AgentCapabilityError("capability operation is already terminal")
            target_kind = str(prepared.payload["target_kind"])
            if terminal_state == "committed":
                if not refs or failure:
                    raise AgentCapabilityError(
                        "committed capability operation requires capability refs only"
                    )
                resolved = []
                for ref in refs:
                    record = self._records.get((owner, ref))
                    if (
                        record is None
                        or record.workflow_id != workflow
                        or record.capability_kind == _CAPABILITY_OPERATION
                    ):
                        raise AgentCapabilityError(
                            "operation capability ref is unavailable for owner/workflow"
                        )
                    resolved.append(record)
                if target_kind not in {record.capability_kind for record in resolved}:
                    raise AgentCapabilityError(
                        "operation capabilities do not include the prepared target kind"
                    )
            elif terminal_state == "aborted":
                if refs:
                    raise AgentCapabilityError(
                        "aborted capability operation cannot claim capabilities"
                    )
                failure = _required_ref(failure, "failure_ref")
            else:
                raise AgentCapabilityError("operation terminal state must be committed or aborted")
            return self._record_actions_unlocked(
                owner_user_id=owner,
                workflow_id=workflow,
                drafts=(
                    _AgentCapabilityDraft(
                        _CAPABILITY_OPERATION,
                        operation_ref,
                        {
                            "operation_ref": operation_ref,
                            "target_kind": target_kind,
                            "state": terminal_state,
                            "request_ref": str(prepared.payload["request_ref"]),
                            "prepared_record_ref": prepared.record_ref,
                            "capability_refs": list(refs),
                            "failure_ref": failure,
                        },
                    ),
                ),
            )[0]

    def commit_operation(
        self,
        *,
        owner_user_id: str,
        workflow_id: str,
        prepared_record_ref: str,
        capability_refs: Iterable[str],
    ) -> AgentCapabilityRecord:
        return self._transition_operation(
            owner_user_id=owner_user_id,
            workflow_id=workflow_id,
            prepared_record_ref=prepared_record_ref,
            state="committed",
            capability_refs=capability_refs,
        )

    def abort_operation(
        self,
        *,
        owner_user_id: str,
        workflow_id: str,
        prepared_record_ref: str,
        failure_ref: str,
    ) -> AgentCapabilityRecord:
        return self._transition_operation(
            owner_user_id=owner_user_id,
            workflow_id=workflow_id,
            prepared_record_ref=prepared_record_ref,
            state="aborted",
            failure_ref=failure_ref,
        )

    def unresolved_operations(
        self,
        *,
        owner_user_id: str,
        workflow_id: str,
    ) -> tuple[AgentCapabilityRecord, ...]:
        owner = _required_text(owner_user_id, "owner_user_id")
        workflow = _required_text(workflow_id, "workflow_id")
        with self._lock, self._process_lock():
            self._reload_unlocked()
            latest_by_operation: dict[str, AgentCapabilityRecord] = {}
            for record in self._records.values():
                if (
                    record.owner_user_id == owner
                    and record.workflow_id == workflow
                    and record.capability_kind == _CAPABILITY_OPERATION
                ):
                    latest_by_operation[str(record.payload["operation_ref"])] = record
            return tuple(
                record
                for record in latest_by_operation.values()
                if record.payload.get("state") == "prepared"
            )

    def record_plan(
        self,
        *,
        owner_user_id: str,
        workflow_id: str,
        plan: Any,
        source_event_refs: Iterable[str],
    ) -> AgentCapabilityRecord:
        if not isinstance(plan, AgentPlan):
            raise AgentCapabilityError("plan capability requires a typed AgentPlan")
        events = tuple(_required_ref(ref, "source_event_ref") for ref in source_event_refs)
        if not events:
            raise AgentCapabilityError("plan capability requires durable source events")
        plan_dict = plan.to_dict()
        payload = {
            "source_event_refs": list(events),
            "plan_digest": _digest_ref("plan", plan_dict),
            "status": str(plan.status),
            "todos": [
                {
                    "todo_id": str(todo.todo_id),
                    "role": str(todo.role),
                    "deps": list(todo.deps),
                    "description_ref": _digest_ref("todo_description", todo.description),
                }
                for todo in plan.todos
            ],
            "dependencies": [
                {"todo_id": str(todo_id), "depends_on": list(dependencies)}
                for todo_id, dependencies in sorted(plan.dependencies.items())
            ],
            "risk_refs": [_digest_ref("plan_risk", risk) for risk in plan.risk_list],
            "acceptance_gates": [
                {
                    "gate_id": str(gate.gate_id),
                    "description_ref": _digest_ref("gate_description", gate.description),
                    "falsifiable_check_ref": _digest_ref(
                        "gate_check", gate.falsifiable_check
                    ),
                }
                for gate in plan.acceptance_gates
            ],
            "handoff_refs": [
                _digest_ref("plan_handoff", handoff)
                for handoff in plan.cross_desk_handoff_plan
            ],
            "rollback_point_refs": [
                _digest_ref("plan_rollback", point) for point in plan.rollback_points
            ],
        }
        return self._record_action(
            owner_user_id=owner_user_id,
            workflow_id=workflow_id,
            capability_kind=CAPABILITY_PLAN,
            source_ref=events[0],
            payload=payload,
        )

    def record_review(
        self,
        *,
        owner_user_id: str,
        workflow_id: str,
        builder: Any,
        verifier: Any,
        subject_binding: Any,
        verdict: Any,
        source_event_ref: str,
    ) -> AgentCapabilityRecord:
        if not isinstance(builder, LLMCallRecord) or not isinstance(verifier, LLMCallRecord):
            raise AgentCapabilityError("review capability requires typed LLMCallRecord inputs")
        if not isinstance(verdict, IndependenceVerdict):
            raise AgentCapabilityError("review capability requires a typed independence verdict")
        if not isinstance(subject_binding, ReviewSubjectBinding):
            raise AgentCapabilityError("review capability requires a typed subject binding")
        owner = _required_text(owner_user_id, "owner_user_id")
        workflow = _required_text(workflow_id, "workflow_id")
        for label, record in (("builder", builder), ("verifier", verifier)):
            if record.owner_user_id != owner or record.workflow_id != workflow:
                raise AgentCapabilityError(
                    f"{label} review record must match the capability owner/workflow"
                )
            if record.status != "ok":
                raise AgentCapabilityError(
                    f"{label} review record must be a successful LLM call"
                )
            _required_ref(record.call_id, f"{label}_call_ref")
            _required_ref(record.prompt_digest, f"{label}_context_ref")
        if verifier.independence.required is not True:
            raise AgentCapabilityError("review capability requires an independence challenge")
        if verifier.independence.builder_call_id != builder.call_id:
            raise AgentCapabilityError(
                "verifier independence metadata must reference the exact builder call"
            )
        distinct_provider = builder.provider != verifier.provider
        distinct_model = builder.model != verifier.model
        if (
            verifier.independence.distinct_provider is not distinct_provider
            or verifier.independence.distinct_model is not distinct_model
        ):
            raise AgentCapabilityError(
                "verifier independence metadata contradicts the exact call records"
            )
        evaluated = evaluate_independence(builder, verifier)
        if verdict != evaluated or verifier.independence.satisfied is not evaluated.independent:
            raise AgentCapabilityError(
                "review verdict contradicts the canonical independence evaluation"
            )
        event_ref = _required_ref(source_event_ref, "source_event_ref")
        payload = {
            "source_event_ref": event_ref,
            "builder_call_ref": _required_ref(builder.call_id, "builder_call_ref"),
            "builder_provider": str(builder.provider),
            "builder_model": str(builder.model),
            "builder_context_ref": _required_ref(
                builder.prompt_digest, "builder_context_ref"
            ),
            "builder_response_ref": _required_ref(
                subject_binding.builder_response_ref, "builder_response_ref"
            ),
            "builder_artifact_ref": _required_ref(
                subject_binding.builder_artifact_ref, "builder_artifact_ref"
            ),
            "builder_output_ref": _required_ref(
                subject_binding.builder_output_ref, "builder_output_ref"
            ),
            "verifier_call_ref": _required_ref(verifier.call_id, "verifier_call_ref"),
            "verifier_provider": str(verifier.provider),
            "verifier_model": str(verifier.model),
            "verifier_context_ref": _required_ref(
                verifier.prompt_digest, "verifier_context_ref"
            ),
            "review_binding_schema_version": subject_binding.schema_version,
            "review_criteria_ref": _required_ref(
                subject_binding.review_criteria_ref, "review_criteria_ref"
            ),
            "review_subject_ref": _required_ref(
                subject_binding.review_subject_ref, "review_subject_ref"
            ),
            "verifier_input_ref": _required_ref(
                subject_binding.verifier_input_ref, "verifier_input_ref"
            ),
            "verifier_prompt_binding_ref": _required_ref(
                subject_binding.verifier_prompt_binding_ref,
                "verifier_prompt_binding_ref",
            ),
            "declared_builder_call_ref": str(
                verifier.independence.builder_call_id or ""
            ),
            "independence_required": bool(verifier.independence.required),
            "independence_claimed_satisfied": bool(verifier.independence.satisfied),
            "distinct_provider": distinct_provider,
            "distinct_model": distinct_model,
            "independent": bool(verdict.independent),
            "verdict_reason_ref": _digest_ref("review_reason", verdict.reason),
        }
        validate_review_capability_evidence(
            owner_user_id=owner,
            workflow_id=workflow,
            builder=builder,
            verifier=verifier,
            payload=payload,
        )
        return self._record_action(
            owner_user_id=owner,
            workflow_id=workflow,
            capability_kind=CAPABILITY_REVIEW,
            source_ref=event_ref,
            payload=payload,
        )

    def record_dag_operation(
        self,
        *,
        owner_user_id: str,
        workflow_id: str,
        mode: str,
        tasks: Iterable[Any],
        result: Any,
        details: Mapping[str, Any] | None = None,
    ) -> AgentCapabilityRecord:
        normalized_mode = _required_text(mode, "mode")
        kind = _DAG_KIND_BY_MODE.get(normalized_mode)
        if kind is None:
            raise AgentCapabilityError(f"unsupported DAG capability mode: {normalized_mode}")
        if not isinstance(result, KernelRunResult):
            raise AgentCapabilityError("DAG capability requires a typed KernelRunResult")
        task_values = tuple(tasks)
        if not task_values or any(not isinstance(task, DAGTask) for task in task_values):
            raise AgentCapabilityError("DAG capability requires typed DAGTask inputs")
        if result.succeeded is not True:
            raise AgentCapabilityError("failed DAG actions cannot mint capability records")
        task_rows = [
            {
                "task_id": str(task.id),
                "op": str(task.op),
                "kind": str(task.kind),
                "deps": list(task.deps),
                "params_ref": _digest_ref("dag_params", task.params),
                "effect_key_ref": (
                    _digest_ref("effect_key", task.effect_idempotency_key)
                    if task.effect_idempotency_key
                    else ""
                ),
            }
            for task in task_values
        ]
        node_rows = [
            {
                "task_id": str(node.task_id),
                "checkpoint_ref": _checkpoint_ref(node.node_id),
                "kind": str(node.kind),
                "status": str(node.status),
                "reused": bool(node.reused),
                "halted": bool(node.halted),
                "requires_reconcile": bool(node.requires_reconcile),
                "result_ref": _digest_ref("dag_result", node.result),
                "error_ref": _digest_ref("dag_error", node.error) if node.error else "",
            }
            for node in result.nodes
        ]
        detail_payload = _json_payload(details or {})
        if normalized_mode in {"run", "replay"}:
            if detail_payload:
                raise AgentCapabilityError(
                    f"{normalized_mode} DAG capability does not accept caller details"
                )
        elif normalized_mode == "fork":
            if set(detail_payload) != {"from_task_id", "overrides_ref"}:
                raise AgentCapabilityError(
                    "fork DAG capability requires only from_task_id and overrides_ref"
                )
            detail_payload = {
                "from_task_id": _required_ref(
                    detail_payload["from_task_id"], "from_task_id"
                ),
                "overrides_ref": _required_ref(
                    detail_payload["overrides_ref"], "overrides_ref"
                ),
            }
        elif normalized_mode == "rollback":
            if set(detail_payload) != {"to_task_id"}:
                raise AgentCapabilityError(
                    "rollback DAG capability requires only to_task_id"
                )
            detail_payload = {
                "to_task_id": _required_ref(detail_payload["to_task_id"], "to_task_id")
            }
        payload = {
            "mode": normalized_mode,
            "succeeded": True,
            "graph_ref": _digest_ref("dag_graph", task_rows),
            "tasks": task_rows,
            "nodes": node_rows,
            "node_id_by_task": [
                {
                    "task_id": str(task_id),
                    "checkpoint_ref": _checkpoint_ref(node_id),
                }
                for task_id, node_id in sorted(result.node_id_by_task.items())
            ],
            "events_ref": _digest_ref("dag_events", result.events),
            "details": detail_payload,
        }
        return self._record_action(
            owner_user_id=owner_user_id,
            workflow_id=workflow_id,
            capability_kind=kind,
            source_ref=_digest_ref(
                _DAG_SOURCE_PREFIX_BY_MODE[normalized_mode], payload
            ),
            payload=payload,
        )

    def record_orchestration_mode(
        self,
        *,
        owner_user_id: str,
        workflow_id: str,
        mode: str,
        source_event_ref: str,
        dag_record_ref: str,
        result: Any,
    ) -> AgentCapabilityRecord:
        normalized_mode = _required_text(mode, "mode")
        if normalized_mode not in {CAPABILITY_REACT, CAPABILITY_REPLAY}:
            raise AgentCapabilityError("orchestration capability mode must be react or replay")
        if not isinstance(getattr(result, "kernel_result", None), KernelRunResult):
            raise AgentCapabilityError(
                "orchestration capability requires a typed kernel result"
            )
        if result.succeeded is not True:
            raise AgentCapabilityError("failed orchestration cannot mint a capability record")
        owner = _required_text(owner_user_id, "owner_user_id")
        workflow = _required_text(workflow_id, "workflow_id")
        event_ref = _required_ref(source_event_ref, "source_event_ref")
        dag_ref = _required_ref(dag_record_ref, "dag_record_ref")
        if result.kernel_result.capability_record_ref != dag_ref:
            raise AgentCapabilityError(
                "orchestration result must reference the exact durable DAG capability"
            )
        try:
            dag_record = self.record(dag_ref, owner_user_id=owner)
        except KeyError as exc:
            raise AgentCapabilityError(
                "orchestration DAG capability is unavailable for owner"
            ) from exc
        expected_dag_kind = (
            CAPABILITY_DAG_CHECKPOINT
            if normalized_mode == CAPABILITY_REACT
            else CAPABILITY_DAG_REPLAY
        )
        if (
            dag_record.workflow_id != workflow
            or dag_record.capability_kind != expected_dag_kind
        ):
            raise AgentCapabilityError(
                "orchestration DAG capability has the wrong workflow or mode"
            )
        payload = {
            "source_event_ref": event_ref,
            "dag_record_ref": dag_ref,
            "succeeded": True,
            "node_checkpoint_refs": [
                {
                    "task_id": str(node.task_id),
                    "checkpoint_ref": _checkpoint_ref(node.node_id),
                }
                for node in result.kernel_result.nodes
            ],
        }
        return self._record_action(
            owner_user_id=owner,
            workflow_id=workflow,
            capability_kind=normalized_mode,
            source_ref=event_ref,
            payload=payload,
        )

    def record_repair(
        self,
        *,
        owner_user_id: str,
        workflow_id: str,
        failure_ref: str,
        code_change: Any,
        permission_ref: str,
        source_event_refs: Iterable[str],
    ) -> tuple[AgentCapabilityRecord, AgentCapabilityRecord]:
        if not isinstance(code_change, AgentCodeChange):
            raise AgentCapabilityError(
                "repair capability requires a typed AgentCodeChange"
            )
        events = tuple(_required_ref(ref, "source_event_ref") for ref in source_event_refs)
        if len(events) != 2:
            raise AgentCapabilityError(
                "repair capability requires failure and repair source events"
            )
        permission = _required_ref(permission_ref, "permission_ref")
        change_material = {
            "path_ref": _digest_ref("code_path", code_change.path),
            "diff_ref": _digest_ref("code_diff", code_change.diff),
            "test_result_ref": _digest_ref("code_test", code_change.test_result),
            "rollback_point_ref": _digest_ref(
                "code_rollback", code_change.rollback_point
            ),
            "permission_ref": permission,
            "theory_implementation_binding_ref": str(
                code_change.theory_implementation_binding or ""
            ),
            "claims_theory_backed": bool(code_change.claims_theory_backed),
        }
        code_change_ref = _digest_ref("agent_code_change", change_material)
        code_payload = {
            "code_change_ref": code_change_ref,
            **change_material,
            "source_event_ref": events[1],
        }
        repair_payload = {
            "source_event_refs": list(events),
            "failure_ref": _required_ref(failure_ref, "failure_ref"),
            "code_change_ref": code_change_ref,
            "permission_ref": permission,
        }
        records = self._record_actions(
            owner_user_id=owner_user_id,
            workflow_id=workflow_id,
            drafts=(
                _AgentCapabilityDraft(
                    CAPABILITY_CODE_CHANGE, code_change_ref, code_payload
                ),
                _AgentCapabilityDraft(CAPABILITY_REPAIR, events[1], repair_payload),
            ),
        )
        return records[0], records[1]

    def record(
        self, record_ref: str, *, owner_user_id: str
    ) -> AgentCapabilityRecord:
        owner = _required_text(owner_user_id, "owner_user_id")
        ref = _required_ref(record_ref, "record_ref")
        with self._lock, self._process_lock():
            self._reload_unlocked()
            try:
                return self._records[(owner, ref)]
            except KeyError:
                raise KeyError("capability record is not available for owner") from None

    def records(
        self,
        *,
        owner_user_id: str,
        workflow_id: str | None = None,
        capability_kind: str | None = None,
    ) -> tuple[AgentCapabilityRecord, ...]:
        owner = _required_text(owner_user_id, "owner_user_id")
        workflow = str(workflow_id or "").strip()
        kind = str(capability_kind or "").strip()
        with self._lock, self._process_lock():
            self._reload_unlocked()
            return tuple(
                record
                for (record_owner, _), record in self._records.items()
                if record_owner == owner
                and record.capability_kind != _CAPABILITY_OPERATION
                and (not workflow or record.workflow_id == workflow)
                and (not kind or record.capability_kind == kind)
            )

    def current_head(
        self,
        *,
        owner_user_id: str,
        workflow_id: str,
        capability_kind: str,
    ) -> AgentCapabilityRecord:
        owner = _required_text(owner_user_id, "owner_user_id")
        workflow = _required_text(workflow_id, "workflow_id")
        kind = _required_text(capability_kind, "capability_kind")
        if kind not in CAPABILITY_KINDS:
            raise AgentCapabilityError("unsupported public capability kind")
        with self._lock, self._process_lock():
            self._reload_unlocked()
            try:
                return self._heads[(owner, workflow, kind)]
            except KeyError:
                raise KeyError("capability head is not available for owner/workflow") from None

    def validate_current(
        self, record_ref: str, *, owner_user_id: str
    ) -> AgentCapabilityDecision:
        try:
            record = self.record(record_ref, owner_user_id=owner_user_id)
            head = self.current_head(
                owner_user_id=owner_user_id,
                workflow_id=record.workflow_id,
                capability_kind=record.capability_kind,
            )
        except (AgentCapabilityError, AgentCapabilityIntegrityError, KeyError) as exc:
            return AgentCapabilityDecision(
                False,
                (
                    AgentCapabilityViolation(
                        "agent_capability_resolution_failed",
                        f"capability record could not be resolved: {type(exc).__name__}",
                        ref=str(record_ref or ""),
                    ),
                ),
            )
        if head.record_ref != record.record_ref:
            return AgentCapabilityDecision(
                False,
                (
                    AgentCapabilityViolation(
                        "agent_capability_not_current_head",
                        "capability record is no longer the current kind head",
                        field="record_ref",
                        ref=record.record_ref,
                    ),
                ),
            )
        return AgentCapabilityDecision(True, ())


__all__ = [
    "AGENT_CAPABILITY_RECORD_VERSION",
    "AGENT_CAPABILITY_SCHEMA_VERSION",
    "CAPABILITY_CODE_CHANGE",
    "CAPABILITY_DAG_CHECKPOINT",
    "CAPABILITY_DAG_FORK",
    "CAPABILITY_DAG_REPLAY",
    "CAPABILITY_DAG_ROLLBACK",
    "CAPABILITY_KINDS",
    "CAPABILITY_PLAN",
    "CAPABILITY_REACT",
    "CAPABILITY_REPAIR",
    "CAPABILITY_REPLAY",
    "CAPABILITY_REVIEW",
    "AgentCapabilityCommitUncertain",
    "AgentCapabilityDecision",
    "AgentCapabilityError",
    "AgentCapabilityIntegrityError",
    "AgentCapabilityRecord",
    "AgentCapabilityViolation",
    "PersistentAgentCapabilityLedger",
    "capability_path_for_event_ledger",
    "validate_review_capability_evidence",
]
