"""Independent, owner-scoped evidence for generic GOAL entrypoint compilation.

Compiler IR and passes may cite evidence, but they are not evidence authorities.
This ledger records a content-addressed snapshot of the already-persisted QRO,
Research Graph command, and passed validation receipt *before* compiler/coverage
records are committed.  The final compiler records must then cite the exact
evidence identity; current validation reopens every dependency and checks that
bidirectional binding.

The record intentionally stores hashes and stable refs, not raw QRO payloads or
caller-provided evidence labels.  Validation-receipt contents retain those
labels as audit inputs, while this ledger is the independent backing accepted
by strict coverage.
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
import threading
from dataclasses import asdict, dataclass, fields, is_dataclass, replace
from enum import Enum
from pathlib import Path
from typing import Any, Iterable

from ..cross_process_lock import acquire_exclusive_fd
from .goal_proof_ledger import GoalProofLedger, ProofHead
from .goal_proof_records import (
    ATOMIC_PROOF_BUNDLE_REQUIRED,
    LOGICAL_TYPE_COMPILER_IR,
    LOGICAL_TYPE_COMPILER_PASS,
    LOGICAL_TYPE_ENTRYPOINT_EVIDENCE,
    LOGICAL_TYPE_VALIDATION_RECEIPT,
    GoalProofRecordProjection,
    GoalProofRecordProjectionError,
    ProofRecordCodec,
    decode_proof_record_head,
)
from .compiler import (
    COMPILER_IR_PROOF_CODEC,
    COMPILER_PASS_PROOF_CODEC,
    validate_compiler_ir,
    validate_compiler_pass,
)
from .goal_validation_receipts import (
    GOAL_VALIDATION_RECEIPT_PROOF_CODEC,
    GoalValidationOutcome,
    GoalValidationReceipt,
    validate_goal_validation_receipt_shape,
)
from .ref_resolution import (
    is_exact_current_research_graph_command,
    is_placeholder_ref,
)


ENTRYPOINT_EVIDENCE_VERSION = "entrypoint_evidence.v1"


def _text(value: Any) -> str:
    return str(getattr(value, "value", value) or "").strip()


def _refs(value: Any) -> tuple[str, ...]:
    if value is None:
        return ()
    values = value if isinstance(value, (tuple, list)) else (value,)
    return tuple(text for item in values if (text := _text(item)))


def _jsonable(value: Any) -> Any:
    if is_dataclass(value):
        return _jsonable(asdict(value))
    if isinstance(value, Enum):
        return _jsonable(value.value)
    if isinstance(value, dict):
        return {
            str(key): _jsonable(item)
            for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
        }
    if isinstance(value, (tuple, list)):
        return [_jsonable(item) for item in value]
    if isinstance(value, set):
        return sorted((_jsonable(item) for item in value), key=str)
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def _sha256(value: Any) -> str:
    serialized = json.dumps(
        _jsonable(value),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return "sha256:" + hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def _valid_digest(value: Any) -> bool:
    token = _text(value).lower()
    return (
        token.startswith("sha256:")
        and len(token) == 71
        and all(char in "0123456789abcdef" for char in token[7:])
    )


def _stable_ref(value: Any, *, field: str) -> str:
    raw = str(getattr(value, "value", value) or "")
    text = raw.strip()
    if (
        not text
        or raw != text
        or any(ord(char) < 32 for char in text)
        or is_placeholder_ref(text)
    ):
        raise ValueError(f"{field} must be an exact non-placeholder ref")
    return text


def _stable_refs(value: Any, *, field: str) -> tuple[str, ...]:
    refs = tuple(_stable_ref(item, field=field) for item in tuple(value or ()))
    if len(refs) != len(set(refs)):
        raise ValueError(f"{field} contains duplicate refs")
    return refs


@dataclass(frozen=True)
class EntrypointEvidenceViolation:
    code: str
    message: str
    field: str = ""
    ref: str = ""


@dataclass(frozen=True)
class EntrypointEvidenceDecision:
    accepted: bool
    violations: tuple[EntrypointEvidenceViolation, ...]


@dataclass(frozen=True)
class EntrypointEvidenceRecord:
    evidence_ref: str
    owner_user_id: str
    entry_source: str
    entrypoint_ref: str
    goal_sections: tuple[str, ...]
    qro_ref: str
    research_graph_ref: str
    validation_ref: str
    compiler_ir_ref: str
    compiler_pass_ref: str
    coverage_ref: str
    qro_state_hash: str
    research_graph_state_hash: str
    validation_state_hash: str
    actor_source: str
    pass_name: str
    permission_ref: str
    environment_lock_ref: str
    deterministic_run_plan_ref: str
    rollback_ref: str
    lifecycle_refs: tuple[str, ...] = ()
    rdp_refs: tuple[str, ...] = ()
    theory_binding_refs: tuple[str, ...] = ()
    consistency_check_refs: tuple[str, ...] = ()
    mathematical_spine_chain_refs: tuple[str, ...] = ()
    evidence_version: str = ENTRYPOINT_EVIDENCE_VERSION

    def __post_init__(self) -> None:
        for field_name in (
            "evidence_ref",
            "owner_user_id",
            "entry_source",
            "entrypoint_ref",
            "qro_ref",
            "research_graph_ref",
            "validation_ref",
            "compiler_ir_ref",
            "compiler_pass_ref",
            "coverage_ref",
            "qro_state_hash",
            "research_graph_state_hash",
            "validation_state_hash",
            "actor_source",
            "pass_name",
            "permission_ref",
            "environment_lock_ref",
            "deterministic_run_plan_ref",
            "rollback_ref",
            "evidence_version",
        ):
            object.__setattr__(self, field_name, _text(getattr(self, field_name)))
        for field_name in (
            "goal_sections",
            "lifecycle_refs",
            "rdp_refs",
            "theory_binding_refs",
            "consistency_check_refs",
            "mathematical_spine_chain_refs",
        ):
            object.__setattr__(self, field_name, _refs(getattr(self, field_name)))

    @property
    def canonical_evidence_ref(self) -> str:
        payload = asdict(self)
        payload.pop("evidence_ref", None)
        return "entrypoint_evidence:" + _sha256(payload).removeprefix("sha256:")


def entrypoint_evidence_from_dict(value: dict[str, Any]) -> EntrypointEvidenceRecord:
    expected_fields = {item.name for item in fields(EntrypointEvidenceRecord)}
    if set(value) != expected_fields:
        raise ValueError("entrypoint evidence field set mismatch")
    return EntrypointEvidenceRecord(
        evidence_ref=value.get("evidence_ref", ""),
        owner_user_id=value.get("owner_user_id", ""),
        entry_source=value.get("entry_source", ""),
        entrypoint_ref=value.get("entrypoint_ref", ""),
        goal_sections=tuple(value.get("goal_sections") or ()),
        qro_ref=value.get("qro_ref", ""),
        research_graph_ref=value.get("research_graph_ref", ""),
        validation_ref=value.get("validation_ref", ""),
        compiler_ir_ref=value.get("compiler_ir_ref", ""),
        compiler_pass_ref=value.get("compiler_pass_ref", ""),
        coverage_ref=value.get("coverage_ref", ""),
        qro_state_hash=value.get("qro_state_hash", ""),
        research_graph_state_hash=value.get("research_graph_state_hash", ""),
        validation_state_hash=value.get("validation_state_hash", ""),
        actor_source=value.get("actor_source", ""),
        pass_name=value.get("pass_name", ""),
        permission_ref=value.get("permission_ref", ""),
        environment_lock_ref=value.get("environment_lock_ref", ""),
        deterministic_run_plan_ref=value.get("deterministic_run_plan_ref", ""),
        rollback_ref=value.get("rollback_ref", ""),
        lifecycle_refs=tuple(value.get("lifecycle_refs") or ()),
        rdp_refs=tuple(value.get("rdp_refs") or ()),
        theory_binding_refs=tuple(value.get("theory_binding_refs") or ()),
        consistency_check_refs=tuple(value.get("consistency_check_refs") or ()),
        mathematical_spine_chain_refs=tuple(
            value.get("mathematical_spine_chain_refs") or ()
        ),
        evidence_version=value.get("evidence_version", ""),
    )


ENTRYPOINT_EVIDENCE_PROOF_CODEC = ProofRecordCodec[
    EntrypointEvidenceRecord
](
    logical_type=LOGICAL_TYPE_ENTRYPOINT_EVIDENCE,
    record_type=EntrypointEvidenceRecord,
    decode=entrypoint_evidence_from_dict,
    logical_ref=lambda record: record.evidence_ref,
    owner=lambda record: record.owner_user_id,
)


def validate_entrypoint_evidence_shape(
    record: EntrypointEvidenceRecord,
) -> EntrypointEvidenceDecision:
    violations: list[EntrypointEvidenceViolation] = []

    def add(code: str, message: str, field: str, ref: Any) -> None:
        violations.append(
            EntrypointEvidenceViolation(code, message, field, _text(ref))
        )

    required_refs = (
        "evidence_ref",
        "owner_user_id",
        "entry_source",
        "entrypoint_ref",
        "qro_ref",
        "research_graph_ref",
        "validation_ref",
        "compiler_ir_ref",
        "compiler_pass_ref",
        "coverage_ref",
        "actor_source",
        "pass_name",
        "permission_ref",
        "environment_lock_ref",
        "deterministic_run_plan_ref",
        "rollback_ref",
    )
    for field_name in required_refs:
        value = _text(getattr(record, field_name))
        if not value or is_placeholder_ref(value):
            add(
                "entrypoint_evidence_required_ref_invalid",
                "entrypoint evidence requires exact non-placeholder refs",
                field_name,
                value,
            )
    if not record.goal_sections or len(record.goal_sections) != len(
        set(record.goal_sections)
    ):
        add(
            "entrypoint_evidence_goal_sections_invalid",
            "entrypoint evidence requires unique GOAL sections",
            "goal_sections",
            record.evidence_ref,
        )
    for field_name in (
        "goal_sections",
        "lifecycle_refs",
        "rdp_refs",
        "theory_binding_refs",
        "consistency_check_refs",
        "mathematical_spine_chain_refs",
    ):
        values = tuple(getattr(record, field_name))
        if len(values) != len(set(values)) or any(
            not value or is_placeholder_ref(value) for value in values
        ):
            add(
                "entrypoint_evidence_ref_set_invalid",
                "entrypoint evidence ref sets must be unique and non-placeholder",
                field_name,
                record.evidence_ref,
            )
    for field_name in (
        "qro_state_hash",
        "research_graph_state_hash",
        "validation_state_hash",
    ):
        if not _valid_digest(getattr(record, field_name)):
            add(
                "entrypoint_evidence_state_hash_invalid",
                "entrypoint evidence state hashes must be full sha256 digests",
                field_name,
                getattr(record, field_name),
            )
    if record.evidence_version != ENTRYPOINT_EVIDENCE_VERSION:
        add(
            "entrypoint_evidence_version_unsupported",
            "entrypoint evidence version is unsupported",
            "evidence_version",
            record.evidence_version,
        )
    if record.evidence_ref and record.evidence_ref != record.canonical_evidence_ref:
        add(
            "entrypoint_evidence_identity_mismatch",
            "evidence_ref must content-bind the complete source/compiler context",
            "evidence_ref",
            record.evidence_ref,
        )
    return EntrypointEvidenceDecision(not violations, tuple(violations))


class PersistentEntrypointEvidenceRegistry:
    """Append-only source-evidence ledger with deterministic prefix recovery."""

    def __init__(
        self,
        path: str | Path,
        *,
        research_graph_store: Any,
        compiler_store: Any,
        validation_receipt_registry: Any,
        proof_ledger: GoalProofLedger | None = None,
        legacy_read_only: bool = False,
    ) -> None:
        required = (
            (research_graph_store, "qro"),
            (research_graph_store, "commands"),
            (compiler_store, "ir"),
            (compiler_store, "compiler_pass"),
            (validation_receipt_registry, "receipt"),
            (validation_receipt_registry, "validate_validation_ref"),
        )
        for value, method in required:
            if not callable(getattr(value, method, None)):
                raise TypeError(f"entrypoint evidence dependency lacks {method}")
        self._path = Path(path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._lock_path = self._path.with_name(f".{self._path.name}.lock")
        self._lock = threading.RLock()
        self._graph = research_graph_store
        self._compiler = compiler_store
        self._validations = validation_receipt_registry
        self._proof_projection = (
            GoalProofRecordProjection(proof_ledger)
            if proof_ledger is not None
            else None
        )
        self._legacy_read_only = bool(legacy_read_only)
        self._proof_head_types: dict[tuple[str, str], str] = {}
        self._records: dict[tuple[str, str], EntrypointEvidenceRecord] = {}
        self._load_existing()
        self._overlay_canonical_unlocked()

    @property
    def path(self) -> Path:
        return self._path

    def matches_dependencies(
        self,
        *,
        research_graph_store: Any,
        compiler_store: Any,
        validation_receipt_registry: Any,
    ) -> bool:
        return (
            self._graph is research_graph_store
            and self._compiler is compiler_store
            and self._validations is validation_receipt_registry
        )

    @staticmethod
    def _owner(value: Any) -> str:
        return _stable_ref(value, field="owner_user_id")

    @staticmethod
    def _event(record: EntrypointEvidenceRecord) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "event_type": "entrypoint_evidence_recorded",
            "owner_user_id": record.owner_user_id,
            "evidence": asdict(record),
        }

    def _load_existing(self) -> None:
        if not self._path.exists():
            return
        with self._path.open("r", encoding="utf-8") as handle:
            for line_no, line in enumerate(handle, start=1):
                if not line.strip():
                    continue
                try:
                    self._apply_row(json.loads(line), persist=False)
                except Exception as exc:  # noqa: BLE001
                    raise ValueError(
                        f"invalid persisted entrypoint evidence at {self._path}:{line_no}"
                    ) from exc

    def _refresh_unlocked(self) -> None:
        self._records = {}
        self._load_existing()

    def _overlay_canonical_unlocked(self) -> None:
        if self._proof_projection is None:
            self._proof_head_types = {}
            return
        canonical_by_type, self._proof_head_types = (
            self._proof_projection.decode_many_with_index(
                ENTRYPOINT_EVIDENCE_PROOF_CODEC
            )
        )
        for record in canonical_by_type[LOGICAL_TYPE_ENTRYPOINT_EVIDENCE]:
            key = (self._owner(record.owner_user_id), record.evidence_ref)
            existing = self._records.get(key)
            if existing is not None and existing != record:
                raise ValueError(
                    "canonical entrypoint evidence collides with legacy record "
                    f"for owner/ref {key[0]!r}/{key[1]!r}"
                )
            self._apply_row(self._event(record), persist=False)

    def _require_legacy_write_allowed(self) -> None:
        if self._legacy_read_only:
            raise RuntimeError(
                f"{ATOMIC_PROOF_BUNDLE_REQUIRED}: "
                "entrypoint evidence legacy JSONL is read-only"
            )

    def refresh(self) -> None:
        with self._lock:
            fd = os.open(self._lock_path, os.O_RDWR | os.O_CREAT, 0o600)
            held = None
            try:
                os.chmod(self._lock_path, 0o600)
                held = acquire_exclusive_fd(fd, timeout_seconds=30.0)
                self._refresh_unlocked()
            finally:
                if held is not None:
                    held.release()
                os.close(fd)
            self._overlay_canonical_unlocked()

    def _append_event(self, row: dict[str, Any]) -> None:
        self._require_legacy_write_allowed()
        fd = os.open(self._lock_path, os.O_RDWR | os.O_CREAT, 0o600)
        held = None
        temporary_path: str | None = None
        try:
            os.chmod(self._lock_path, 0o600)
            held = acquire_exclusive_fd(fd, timeout_seconds=30.0)
            incoming = row["evidence"]
            existing_bytes = self._path.read_bytes() if self._path.exists() else b""
            for line_no, line in enumerate(existing_bytes.splitlines(), start=1):
                if not line.strip():
                    continue
                existing = json.loads(line)
                persisted = existing.get("evidence")
                if (
                    existing.get("schema_version") == 1
                    and existing.get("owner_user_id") == row.get("owner_user_id")
                    and isinstance(persisted, dict)
                    and persisted.get("evidence_ref") == incoming.get("evidence_ref")
                ):
                    if existing == row:
                        return
                    raise ValueError(
                        "entrypoint evidence identity collision at "
                        f"{self._path}:{line_no}"
                    )
            serialized = json.dumps(
                row,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8") + b"\n"
            prefix = existing_bytes
            if prefix and not prefix.endswith(b"\n"):
                prefix += b"\n"
            temporary_fd, temporary_path = tempfile.mkstemp(
                prefix=f".{self._path.name}.",
                suffix=".tmp",
                dir=self._path.parent,
            )
            try:
                os.fchmod(temporary_fd, 0o600)
                with os.fdopen(temporary_fd, "wb") as handle:
                    handle.write(prefix)
                    handle.write(serialized)
                    handle.flush()
                    os.fsync(handle.fileno())
                os.replace(temporary_path, self._path)
                temporary_path = None
                directory_fd = os.open(self._path.parent, os.O_RDONLY)
                try:
                    os.fsync(directory_fd)
                finally:
                    os.close(directory_fd)
            except Exception:
                try:
                    os.close(temporary_fd)
                except OSError:
                    pass
                raise
        finally:
            if temporary_path is not None:
                try:
                    os.unlink(temporary_path)
                except FileNotFoundError:
                    pass
            if held is not None:
                held.release()
            os.close(fd)

    def _apply_row(
        self,
        row: dict[str, Any],
        *,
        persist: bool,
    ) -> EntrypointEvidenceRecord:
        if set(row) != {
            "schema_version",
            "event_type",
            "owner_user_id",
            "evidence",
        }:
            raise ValueError("entrypoint evidence event field set mismatch")
        if row.get("schema_version") != 1:
            raise ValueError("entrypoint evidence requires schema_version=1")
        if row.get("event_type") != "entrypoint_evidence_recorded":
            raise ValueError("unknown entrypoint evidence event_type")
        owner = self._owner(row.get("owner_user_id"))
        raw = row.get("evidence")
        if not isinstance(raw, dict):
            raise ValueError("entrypoint evidence event is missing evidence")
        record = entrypoint_evidence_from_dict(raw)
        if record.owner_user_id != owner:
            raise ValueError("entrypoint evidence owner envelope mismatch")
        decision = validate_entrypoint_evidence_shape(record)
        if not decision.accepted:
            raise ValueError(
                ";".join(
                    f"{item.code}:{item.field}:{item.ref}"
                    for item in decision.violations
                )
            )
        key = (owner, record.evidence_ref)
        existing = self._records.get(key)
        if existing is not None:
            if existing != record:
                raise ValueError("entrypoint evidence identity collision for owner")
            return existing
        if persist:
            self._append_event(row)
        self._records[key] = record
        return record

    def _source_qro_command(
        self,
        *,
        owner_user_id: str,
        qro_ref: str,
        research_graph_ref: str,
        entry_source: str,
    ) -> tuple[Any, Any]:
        owner = self._owner(owner_user_id)
        qro_id = _stable_ref(qro_ref, field="qro_ref")
        graph_ref = _stable_ref(
            research_graph_ref,
            field="research_graph_ref",
        )
        source = _stable_ref(entry_source, field="entry_source")
        qro = self._graph.qro(qro_id)
        if _text(getattr(qro, "owner", "")) != owner:
            raise ValueError("entrypoint evidence QRO owner mismatch")
        commands = tuple(
            item
            for item in self._graph.commands()
            if _text(getattr(item, "command_id", "")) == graph_ref
        )
        if len(commands) != 1:
            raise ValueError(
                "entrypoint evidence requires exactly one Research Graph command"
            )
        command = commands[0]
        command_qro = (
            getattr(command, "payload", {}).get("qro")
            if isinstance(getattr(command, "payload", None), dict)
            else None
        )
        if command_qro != qro or _text(getattr(command_qro, "qro_id", "")) != qro_id:
            raise ValueError(
                "entrypoint evidence Research Graph command/QRO mismatch"
            )
        if _text(getattr(command, "source", "")) != source:
            raise ValueError("entrypoint evidence entry source mismatch")
        if not is_exact_current_research_graph_command(
            self._graph,
            command,
            owner_user_id=owner,
            qro_ref=qro_id,
        ):
            raise ValueError(
                "entrypoint evidence Research Graph command is not the exact "
                "current QRO projection head"
            )
        return qro, command

    def _source_snapshot(
        self,
        *,
        owner_user_id: str,
        qro_ref: str,
        research_graph_ref: str,
        validation_ref: str,
        entry_source: str,
    ) -> tuple[Any, Any, Any]:
        owner = self._owner(owner_user_id)
        qro_id = _stable_ref(qro_ref, field="qro_ref")
        graph_ref = _stable_ref(
            research_graph_ref,
            field="research_graph_ref",
        )
        receipt_ref = _stable_ref(validation_ref, field="validation_ref")
        qro, command = self._source_qro_command(
            owner_user_id=owner,
            qro_ref=qro_id,
            research_graph_ref=graph_ref,
            entry_source=entry_source,
        )
        receipt = self._validations.receipt(
            receipt_ref,
            owner_user_id=owner,
        )
        decision = self._validations.validate_validation_ref(
            receipt_ref,
            owner_user_id=owner,
            subject_qro_refs=(qro_id,),
            graph_command_refs=(graph_ref,),
        )
        if not bool(getattr(decision, "accepted", False)):
            raise ValueError(
                "entrypoint evidence validation receipt is not exact/current/passed"
            )
        return qro, command, receipt

    def _candidate_source_snapshot(
        self,
        *,
        owner_user_id: str,
        qro_ref: str,
        research_graph_ref: str,
        entry_source: str,
        validation_receipt_candidate: GoalValidationReceipt,
    ) -> tuple[Any, Any, GoalValidationReceipt]:
        """Validate an unpersisted server receipt for one atomic bundle.

        The candidate is treated as data, not authority: its canonical
        identity, shape, outcome, owner, exact QRO/command subjects, evidence
        digests, and the live Graph command/QRO relation are all rechecked.
        """

        if not isinstance(validation_receipt_candidate, GoalValidationReceipt):
            raise TypeError(
                "entrypoint evidence requires GoalValidationReceipt candidate"
            )
        owner = self._owner(owner_user_id)
        qro_id = _stable_ref(qro_ref, field="qro_ref")
        graph_ref = _stable_ref(
            research_graph_ref,
            field="research_graph_ref",
        )
        qro, command = self._source_qro_command(
            owner_user_id=owner,
            qro_ref=qro_id,
            research_graph_ref=graph_ref,
            entry_source=entry_source,
        )
        receipt = validation_receipt_candidate
        shape = validate_goal_validation_receipt_shape(receipt)
        if not shape.accepted:
            raise ValueError(
                "entrypoint evidence validation receipt candidate shape invalid:"
                + ";".join(
                    f"{item.code}:{item.field}:{item.ref}"
                    for item in shape.violations
                )
            )
        if receipt.validation_ref != receipt.canonical_validation_ref:
            raise ValueError(
                "entrypoint evidence validation receipt candidate identity mismatch"
            )
        if receipt.owner_user_id != owner:
            raise ValueError(
                "entrypoint evidence validation receipt candidate owner mismatch"
            )
        if receipt.subject_qro_refs != (qro_id,):
            raise ValueError(
                "entrypoint evidence validation receipt candidate QRO subject mismatch"
            )
        if receipt.graph_command_refs != (graph_ref,):
            raise ValueError(
                "entrypoint evidence validation receipt candidate Graph subject mismatch"
            )
        if str(receipt.outcome) != GoalValidationOutcome.PASSED.value:
            raise ValueError(
                "entrypoint evidence validation receipt candidate is not passed"
            )
        if receipt.residuals:
            raise ValueError(
                "entrypoint evidence validation receipt candidate has residuals"
            )
        return qro, command, receipt

    def _prepare_record_from_snapshot(
        self,
        *,
        owner_user_id: str,
        entry_source: str,
        entrypoint_ref: str,
        goal_sections: Iterable[str],
        qro_ref: str,
        research_graph_ref: str,
        validation_ref: str,
        compiler_ir_ref: str,
        compiler_pass_ref: str,
        coverage_ref: str,
        actor_source: str,
        pass_name: str,
        permission_ref: str,
        environment_lock_ref: str,
        deterministic_run_plan_ref: str,
        rollback_ref: str,
        qro: Any,
        command: Any,
        receipt: GoalValidationReceipt,
        lifecycle_refs: Iterable[str] = (),
        rdp_refs: Iterable[str] = (),
        theory_binding_refs: Iterable[str] = (),
        consistency_check_refs: Iterable[str] = (),
        mathematical_spine_chain_refs: Iterable[str] = (),
    ) -> EntrypointEvidenceRecord:
        owner = self._owner(owner_user_id)
        source = _stable_ref(entry_source, field="entry_source")
        qro_id = _stable_ref(qro_ref, field="qro_ref")
        graph_ref = _stable_ref(research_graph_ref, field="research_graph_ref")
        receipt_ref = _stable_ref(validation_ref, field="validation_ref")
        if receipt.validation_ref != receipt_ref:
            raise ValueError(
                "entrypoint evidence validation receipt/ref mismatch"
            )
        provisional = EntrypointEvidenceRecord(
            evidence_ref="",
            owner_user_id=owner,
            entry_source=source,
            entrypoint_ref=_stable_ref(entrypoint_ref, field="entrypoint_ref"),
            goal_sections=_stable_refs(tuple(goal_sections), field="goal_sections"),
            qro_ref=qro_id,
            research_graph_ref=graph_ref,
            validation_ref=receipt_ref,
            compiler_ir_ref=_stable_ref(
                compiler_ir_ref,
                field="compiler_ir_ref",
            ),
            compiler_pass_ref=_stable_ref(
                compiler_pass_ref,
                field="compiler_pass_ref",
            ),
            coverage_ref=_stable_ref(coverage_ref, field="coverage_ref"),
            qro_state_hash=_sha256(qro),
            research_graph_state_hash=_sha256(command),
            validation_state_hash=_sha256(receipt),
            actor_source=_stable_ref(actor_source, field="actor_source"),
            pass_name=_stable_ref(pass_name, field="pass_name"),
            permission_ref=_stable_ref(permission_ref, field="permission_ref"),
            environment_lock_ref=_stable_ref(
                environment_lock_ref,
                field="environment_lock_ref",
            ),
            deterministic_run_plan_ref=_stable_ref(
                deterministic_run_plan_ref,
                field="deterministic_run_plan_ref",
            ),
            rollback_ref=_stable_ref(rollback_ref, field="rollback_ref"),
            lifecycle_refs=_stable_refs(
                tuple(lifecycle_refs),
                field="lifecycle_refs",
            ),
            rdp_refs=_stable_refs(tuple(rdp_refs), field="rdp_refs"),
            theory_binding_refs=_stable_refs(
                tuple(theory_binding_refs),
                field="theory_binding_refs",
            ),
            consistency_check_refs=_stable_refs(
                tuple(consistency_check_refs),
                field="consistency_check_refs",
            ),
            mathematical_spine_chain_refs=_stable_refs(
                tuple(mathematical_spine_chain_refs),
                field="mathematical_spine_chain_refs",
            ),
        )
        record = replace(
            provisional,
            evidence_ref=provisional.canonical_evidence_ref,
        )
        decision = validate_entrypoint_evidence_shape(record)
        if not decision.accepted:
            raise ValueError(
                ";".join(
                    f"{item.code}:{item.field}:{item.ref}"
                    for item in decision.violations
                )
            )
        return record

    def prepare_record(
        self,
        *,
        owner_user_id: str,
        entry_source: str,
        entrypoint_ref: str,
        goal_sections: Iterable[str],
        qro_ref: str,
        research_graph_ref: str,
        validation_ref: str,
        compiler_ir_ref: str,
        compiler_pass_ref: str,
        coverage_ref: str,
        actor_source: str,
        pass_name: str,
        permission_ref: str,
        environment_lock_ref: str,
        deterministic_run_plan_ref: str,
        rollback_ref: str,
        lifecycle_refs: Iterable[str] = (),
        rdp_refs: Iterable[str] = (),
        theory_binding_refs: Iterable[str] = (),
        consistency_check_refs: Iterable[str] = (),
        mathematical_spine_chain_refs: Iterable[str] = (),
    ) -> EntrypointEvidenceRecord:
        owner = self._owner(owner_user_id)
        source = _stable_ref(entry_source, field="entry_source")
        qro_id = _stable_ref(qro_ref, field="qro_ref")
        graph_ref = _stable_ref(research_graph_ref, field="research_graph_ref")
        receipt_ref = _stable_ref(validation_ref, field="validation_ref")
        qro, command, receipt = self._source_snapshot(
            owner_user_id=owner,
            qro_ref=qro_id,
            research_graph_ref=graph_ref,
            validation_ref=receipt_ref,
            entry_source=source,
        )
        return self._prepare_record_from_snapshot(
            owner_user_id=owner,
            entry_source=source,
            entrypoint_ref=entrypoint_ref,
            goal_sections=goal_sections,
            qro_ref=qro_id,
            research_graph_ref=graph_ref,
            validation_ref=receipt_ref,
            compiler_ir_ref=compiler_ir_ref,
            compiler_pass_ref=compiler_pass_ref,
            coverage_ref=coverage_ref,
            actor_source=actor_source,
            pass_name=pass_name,
            permission_ref=permission_ref,
            environment_lock_ref=environment_lock_ref,
            deterministic_run_plan_ref=deterministic_run_plan_ref,
            rollback_ref=rollback_ref,
            qro=qro,
            command=command,
            receipt=receipt,
            lifecycle_refs=lifecycle_refs,
            rdp_refs=rdp_refs,
            theory_binding_refs=theory_binding_refs,
            consistency_check_refs=consistency_check_refs,
            mathematical_spine_chain_refs=mathematical_spine_chain_refs,
        )

    def prepare_record_from_receipt_candidate(
        self,
        *,
        validation_receipt_candidate: GoalValidationReceipt,
        owner_user_id: str,
        entry_source: str,
        entrypoint_ref: str,
        goal_sections: Iterable[str],
        qro_ref: str,
        research_graph_ref: str,
        compiler_ir_ref: str,
        compiler_pass_ref: str,
        coverage_ref: str,
        actor_source: str,
        pass_name: str,
        permission_ref: str,
        environment_lock_ref: str,
        deterministic_run_plan_ref: str,
        rollback_ref: str,
        lifecycle_refs: Iterable[str] = (),
        rdp_refs: Iterable[str] = (),
        theory_binding_refs: Iterable[str] = (),
        consistency_check_refs: Iterable[str] = (),
        mathematical_spine_chain_refs: Iterable[str] = (),
    ) -> EntrypointEvidenceRecord:
        """Prepare evidence for a receipt that will share one SQLite commit."""

        owner = self._owner(owner_user_id)
        source = _stable_ref(entry_source, field="entry_source")
        qro_id = _stable_ref(qro_ref, field="qro_ref")
        graph_ref = _stable_ref(research_graph_ref, field="research_graph_ref")
        qro, command, receipt = self._candidate_source_snapshot(
            owner_user_id=owner,
            qro_ref=qro_id,
            research_graph_ref=graph_ref,
            entry_source=source,
            validation_receipt_candidate=validation_receipt_candidate,
        )
        return self._prepare_record_from_snapshot(
            owner_user_id=owner,
            entry_source=source,
            entrypoint_ref=entrypoint_ref,
            goal_sections=goal_sections,
            qro_ref=qro_id,
            research_graph_ref=graph_ref,
            validation_ref=receipt.validation_ref,
            compiler_ir_ref=compiler_ir_ref,
            compiler_pass_ref=compiler_pass_ref,
            coverage_ref=coverage_ref,
            actor_source=actor_source,
            pass_name=pass_name,
            permission_ref=permission_ref,
            environment_lock_ref=environment_lock_ref,
            deterministic_run_plan_ref=deterministic_run_plan_ref,
            rollback_ref=rollback_ref,
            qro=qro,
            command=command,
            receipt=receipt,
            lifecycle_refs=lifecycle_refs,
            rdp_refs=rdp_refs,
            theory_binding_refs=theory_binding_refs,
            consistency_check_refs=consistency_check_refs,
            mathematical_spine_chain_refs=mathematical_spine_chain_refs,
        )

    def _source_violations(
        self,
        record: EntrypointEvidenceRecord,
        *,
        owner_user_id: str,
        receipt_candidate: GoalValidationReceipt | None = None,
    ) -> list[EntrypointEvidenceViolation]:
        violations = list(validate_entrypoint_evidence_shape(record).violations)
        owner = self._owner(owner_user_id)
        if record.owner_user_id != owner:
            violations.append(
                EntrypointEvidenceViolation(
                    "entrypoint_evidence_owner_mismatch",
                    "entrypoint evidence owner envelope mismatch",
                    "owner_user_id",
                    record.owner_user_id,
                )
            )
            return violations
        if violations:
            return violations
        try:
            if receipt_candidate is None:
                qro, command, receipt = self._source_snapshot(
                    owner_user_id=owner,
                    qro_ref=record.qro_ref,
                    research_graph_ref=record.research_graph_ref,
                    validation_ref=record.validation_ref,
                    entry_source=record.entry_source,
                )
            else:
                qro, command, receipt = self._candidate_source_snapshot(
                    owner_user_id=owner,
                    qro_ref=record.qro_ref,
                    research_graph_ref=record.research_graph_ref,
                    entry_source=record.entry_source,
                    validation_receipt_candidate=receipt_candidate,
                )
        except Exception as exc:  # noqa: BLE001 - current evidence fails closed.
            violations.append(
                EntrypointEvidenceViolation(
                    "entrypoint_evidence_source_resolution_failed",
                    f"entrypoint evidence source resolution failed:{type(exc).__name__}",
                    "qro_ref",
                    record.qro_ref,
                )
            )
            return violations
        for field_name, actual, expected in (
            ("qro_state_hash", _sha256(qro), record.qro_state_hash),
            (
                "research_graph_state_hash",
                _sha256(command),
                record.research_graph_state_hash,
            ),
            (
                "validation_state_hash",
                _sha256(receipt),
                record.validation_state_hash,
            ),
        ):
            if actual != expected:
                violations.append(
                    EntrypointEvidenceViolation(
                        "entrypoint_evidence_source_drifted",
                        "persisted entrypoint evidence source content drifted",
                        field_name,
                        record.evidence_ref,
                    )
                )
        return violations

    def _compiler_violations(
        self,
        record: EntrypointEvidenceRecord,
        *,
        ir_candidate: Any | None = None,
        compiler_pass_candidate: Any | None = None,
    ) -> list[EntrypointEvidenceViolation]:
        violations: list[EntrypointEvidenceViolation] = []

        def add(field: str, message: str, ref: Any) -> None:
            violations.append(
                EntrypointEvidenceViolation(
                    "entrypoint_evidence_compiler_linkage_invalid",
                    message,
                    field,
                    _text(ref),
                )
            )

        if ir_candidate is not None or compiler_pass_candidate is not None:
            if ir_candidate is None or compiler_pass_candidate is None:
                add(
                    "compiler_ir_ref",
                    "canonical compiler snapshot is incomplete",
                    record.compiler_ir_ref,
                )
                return violations
            ir = ir_candidate
            compiler_pass = compiler_pass_candidate
        else:
            try:
                ir = self._compiler.ir(
                    record.compiler_ir_ref,
                    owner=record.owner_user_id,
                )
                compiler_pass = self._compiler.compiler_pass(
                    record.compiler_pass_ref,
                    owner=record.owner_user_id,
                )
            except Exception as exc:  # noqa: BLE001 - current evidence fails closed.
                add(
                    "compiler_ir_ref",
                    f"entrypoint compiler bundle lookup failed:{type(exc).__name__}",
                    record.compiler_ir_ref,
                )
                return violations

        for label, decision in (
            ("compiler IR", validate_compiler_ir(ir)),
            ("compiler pass", validate_compiler_pass(compiler_pass)),
        ):
            for item in decision.violations:
                add(
                    str(item.field or "compiler_record"),
                    f"{label} semantic validator rejected {item.code}",
                    item.ref or record.evidence_ref,
                )

        exact_checks = (
            ("source_qro_refs", tuple(getattr(ir, "source_qro_refs", ()) or ()), (record.qro_ref,)),
            ("graph_command_refs", tuple(getattr(ir, "graph_command_refs", ()) or ()), (record.research_graph_ref,)),
            ("ir_evidence_refs", tuple(getattr(ir, "evidence_refs", ()) or ()), (record.evidence_ref,)),
            ("pass_input_qro_refs", tuple(getattr(compiler_pass, "input_qro_refs", ()) or ()), (record.qro_ref,)),
            ("pass_graph_command_refs", tuple(getattr(compiler_pass, "graph_command_refs", ()) or ()), (record.research_graph_ref,)),
            ("pass_evidence_refs", tuple(getattr(compiler_pass, "evidence_refs", ()) or ()), (record.evidence_ref,)),
        )
        for field_name, actual, expected in exact_checks:
            if actual != expected:
                add(field_name, "compiler bundle does not cite the exact entrypoint evidence lineage", actual)
        for field_name, actual, expected in (
            ("ir.owner", _text(getattr(ir, "owner", "")), record.owner_user_id),
            ("pass.actor", _text(getattr(compiler_pass, "actor", "")), record.owner_user_id),
            ("pass.output_ir_ref", _text(getattr(compiler_pass, "output_ir_ref", "")), record.compiler_ir_ref),
            ("pass.entry_source", _text(getattr(compiler_pass, "entry_source", "")), record.entry_source),
            ("pass.actor_source", _text(getattr(compiler_pass, "actor_source", "")), record.actor_source),
            ("pass.pass_name", _text(getattr(compiler_pass, "pass_name", "")), record.pass_name),
            ("ir.permission_ref", _text(getattr(ir, "permission_ref", "")), record.permission_ref),
            ("pass.permission_ref", _text(getattr(compiler_pass, "permission_ref", "")), record.permission_ref),
            ("ir.environment_lock_ref", _text(getattr(ir, "environment_lock_ref", "")), record.environment_lock_ref),
            ("ir.deterministic_run_plan_ref", _text(getattr(ir, "deterministic_run_plan_ref", "")), record.deterministic_run_plan_ref),
            ("pass.deterministic_run_plan_ref", _text(getattr(compiler_pass, "deterministic_run_plan_ref", "")), record.deterministic_run_plan_ref),
            ("ir.rollback_ref", _text(getattr(ir, "rollback_ref", "")), record.rollback_ref),
            ("pass.rollback_ref", _text(getattr(compiler_pass, "rollback_ref", "")), record.rollback_ref),
        ):
            if actual != expected:
                add(field_name, "compiler bundle context differs from entrypoint evidence", actual)
        for field_name, actual, expected in (
            ("ir.theory_binding_refs", tuple(getattr(ir, "theory_binding_refs", ()) or ()), record.theory_binding_refs),
            ("ir.consistency_check_refs", tuple(getattr(ir, "consistency_check_refs", ()) or ()), record.consistency_check_refs),
            ("ir.mathematical_spine_chain_refs", tuple(getattr(ir, "mathematical_spine_chain_refs", ()) or ()), record.mathematical_spine_chain_refs),
        ):
            if actual != expected:
                add(field_name, "compiler typed refs differ from entrypoint evidence", actual)
        if record.validation_ref not in tuple(getattr(ir, "validation_refs", ()) or ()):
            add("ir.validation_refs", "compiler IR omits the bound validation receipt", record.validation_ref)
        if record.validation_ref not in tuple(getattr(compiler_pass, "validation_refs", ()) or ()):
            add("pass.validation_refs", "compiler pass omits the bound validation receipt", record.validation_ref)
        binding_refs = {
            _text(ref)
            for item in (ir, compiler_pass)
            for ref in (
                *tuple(getattr(item, "tool_record_refs", ()) or ()),
                *tuple(getattr(item, "canonical_command_refs", ()) or ()),
                *tuple(getattr(item, "node_refs", ()) or ()),
            )
        }
        if (
            record.entrypoint_ref not in binding_refs
            and f"entrypoint:{record.entrypoint_ref}" not in binding_refs
        ):
            add(
                "entrypoint_ref",
                "compiler bundle does not bind the evidence entrypoint",
                record.entrypoint_ref,
            )
        return violations

    def _atomic_bundle_snapshot(
        self,
        record: EntrypointEvidenceRecord,
    ) -> tuple[
        GoalValidationReceipt,
        EntrypointEvidenceRecord,
        Any,
        Any,
        tuple[ProofHead, ...],
    ]:
        """Decode the bundle and retain the exact heads used by validation."""

        if self._proof_projection is None:
            raise RuntimeError("canonical entrypoint bundle snapshot is unavailable")
        typed_refs = (
            (LOGICAL_TYPE_VALIDATION_RECEIPT, record.validation_ref),
            (LOGICAL_TYPE_ENTRYPOINT_EVIDENCE, record.evidence_ref),
            (LOGICAL_TYPE_COMPILER_IR, record.compiler_ir_ref),
            (LOGICAL_TYPE_COMPILER_PASS, record.compiler_pass_ref),
        )
        heads = self._proof_projection.current_heads_for_refs(
            owner=record.owner_user_id,
            typed_refs=typed_refs,
        )
        if len({head.bundle_id for head in heads}) != 1:
            raise GoalProofRecordProjectionError(
                "receipt, evidence, compiler IR, and compiler pass must share one proof bundle"
            )
        receipt = decode_proof_record_head(
            heads[0],
            codec=GOAL_VALIDATION_RECEIPT_PROOF_CODEC,
        )
        evidence = decode_proof_record_head(
            heads[1],
            codec=ENTRYPOINT_EVIDENCE_PROOF_CODEC,
        )
        ir = decode_proof_record_head(heads[2], codec=COMPILER_IR_PROOF_CODEC)
        compiler_pass = decode_proof_record_head(
            heads[3],
            codec=COMPILER_PASS_PROOF_CODEC,
        )
        if evidence != record:
            raise GoalProofRecordProjectionError(
                "entrypoint evidence differs from its exact current proof head"
            )
        return receipt, evidence, ir, compiler_pass, heads

    def record_evidence(
        self,
        record: EntrypointEvidenceRecord,
    ) -> EntrypointEvidenceRecord:
        self._require_legacy_write_allowed()
        violations = self._source_violations(
            record,
            owner_user_id=record.owner_user_id,
        )
        if violations:
            raise ValueError(
                ";".join(
                    f"{item.code}:{item.field}:{item.ref}" for item in violations
                )
            )
        with self._lock:
            return self._apply_row(self._event(record), persist=True)

    def evidence(
        self,
        evidence_ref: str,
        *,
        owner_user_id: str,
    ) -> EntrypointEvidenceRecord:
        self.refresh()
        owner = self._owner(owner_user_id)
        ref = _text(evidence_ref)
        if self._proof_projection is not None:
            current_type = self._proof_head_types.get((owner, ref))
            if (
                current_type is not None
                and current_type != LOGICAL_TYPE_ENTRYPOINT_EVIDENCE
            ):
                raise GoalProofRecordProjectionError(
                    "canonical GOAL proof logical ref/type collision: "
                    f"{ref!r} is {current_type!r}, expected "
                    f"{LOGICAL_TYPE_ENTRYPOINT_EVIDENCE!r}"
                )
            if current_type == LOGICAL_TYPE_ENTRYPOINT_EVIDENCE:
                return self._records[(owner, ref)]
        return self._records[(owner, ref)]

    def evidences(
        self,
        *,
        owner_user_id: str,
    ) -> tuple[EntrypointEvidenceRecord, ...]:
        self.refresh()
        owner = self._owner(owner_user_id)
        return tuple(
            record
            for (record_owner, _), record in self._records.items()
            if record_owner == owner
        )

    def validate_current(
        self,
        record: EntrypointEvidenceRecord,
        *,
        owner_user_id: str,
    ) -> EntrypointEvidenceDecision:
        violations: list[EntrypointEvidenceViolation] = []
        receipt_candidate: GoalValidationReceipt | None = None
        ir_candidate: Any | None = None
        compiler_pass_candidate: Any | None = None
        initial_heads: tuple[ProofHead, ...] | None = None
        if self._proof_projection is not None:
            try:
                (
                    receipt_candidate,
                    _canonical_evidence,
                    ir_candidate,
                    compiler_pass_candidate,
                    initial_heads,
                ) = self._atomic_bundle_snapshot(record)
            except Exception as exc:  # noqa: BLE001 - strict proof fails closed.
                violations.append(
                    EntrypointEvidenceViolation(
                        (
                            "entrypoint_evidence_atomic_bundle_recombined"
                            if "share one proof bundle" in str(exc)
                            else "entrypoint_evidence_atomic_bundle_incomplete"
                        ),
                        "entrypoint proof bundle snapshot rejected:"
                        f"{type(exc).__name__}",
                        "evidence_ref",
                        record.evidence_ref,
                    )
                )
        violations.extend(
            self._source_violations(
                record,
                owner_user_id=owner_user_id,
                receipt_candidate=receipt_candidate,
            )
        )
        violations.extend(
            self._compiler_violations(
                record,
                ir_candidate=ir_candidate,
                compiler_pass_candidate=compiler_pass_candidate,
            )
        )
        if self._proof_projection is not None and initial_heads is not None:
            try:
                final_heads = self._proof_projection.current_heads_for_refs(
                    owner=record.owner_user_id,
                    typed_refs=(
                        (LOGICAL_TYPE_VALIDATION_RECEIPT, record.validation_ref),
                        (LOGICAL_TYPE_ENTRYPOINT_EVIDENCE, record.evidence_ref),
                        (LOGICAL_TYPE_COMPILER_IR, record.compiler_ir_ref),
                        (LOGICAL_TYPE_COMPILER_PASS, record.compiler_pass_ref),
                    ),
                )
                final_identities = tuple(
                    (
                        head.logical_ref,
                        head.declaration_event_id,
                        head.generation,
                        head.bundle_id,
                        head.payload_hash,
                    )
                    for head in final_heads
                )
                initial_identities = tuple(
                    (
                        head.logical_ref,
                        head.declaration_event_id,
                        head.generation,
                        head.bundle_id,
                        head.payload_hash,
                    )
                    for head in initial_heads
                )
                if final_identities != initial_identities:
                    raise GoalProofRecordProjectionError(
                        "entrypoint proof heads changed during source validation"
                    )
            except Exception as exc:  # noqa: BLE001 - strict proof fails closed.
                violations.append(
                    EntrypointEvidenceViolation(
                        "entrypoint_evidence_atomic_bundle_changed_during_validation",
                        "entrypoint proof bundle final-head check rejected:"
                        f"{type(exc).__name__}",
                        "evidence_ref",
                        record.evidence_ref,
                    )
                )
        return EntrypointEvidenceDecision(not violations, tuple(violations))

    def is_canonical_current(
        self,
        record: EntrypointEvidenceRecord,
        *,
        owner_user_id: str | None = None,
    ) -> bool:
        """Return whether ``record`` is the exact live SQLite proof head."""

        if self._proof_projection is None:
            return False
        if owner_user_id is not None and self._owner(
            owner_user_id
        ) != self._owner(record.owner_user_id):
            return False
        return self._proof_projection.is_exact_current(
            record,
            codec=ENTRYPOINT_EVIDENCE_PROOF_CODEC,
        )

    def validate_entrypoint_ref(
        self,
        evidence_ref: str,
        *,
        owner_user_id: str,
        record: Any,
        artifact_candidate: Any | None = None,
    ) -> EntrypointEvidenceDecision:
        try:
            evidence = self.evidence(
                evidence_ref,
                owner_user_id=owner_user_id,
            )
        except Exception as exc:  # noqa: BLE001 - linkage fails closed.
            return EntrypointEvidenceDecision(
                False,
                (
                    EntrypointEvidenceViolation(
                        "entrypoint_evidence_unknown",
                        f"entrypoint evidence lookup failed:{type(exc).__name__}",
                        "evidence_refs",
                        evidence_ref,
                    ),
                ),
            )
        violations = list(
            self.validate_current(
                evidence,
                owner_user_id=owner_user_id,
            ).violations
        )
        platform_derivative = tuple(
            _refs(getattr(record, "goal_sections", ()))
        ) == ("§14",)
        entrypoint_ref = _text(getattr(record, "entrypoint_ref", ""))
        artifact_derivative = entrypoint_ref.startswith("compiler_artifact:")
        if artifact_derivative:
            artifact_refs = tuple(
                ref
                for ref in _refs(getattr(record, "lifecycle_refs", ()))
                if ref.startswith("compiler_artifact:")
            )
            artifact = None
            if len(artifact_refs) == 1:
                if (
                    artifact_candidate is not None
                    and _text(getattr(artifact_candidate, "artifact_ref", ""))
                    == artifact_refs[0]
                    and _text(getattr(artifact_candidate, "owner", ""))
                    == owner_user_id
                ):
                    artifact = artifact_candidate
                else:
                    try:
                        artifact = self._compiler.artifact(
                            artifact_refs[0],
                            owner=owner_user_id,
                        )
                    except Exception:  # noqa: BLE001 - derivative fails closed.
                        artifact = None
            artifact_exact = artifact is not None and (
                entrypoint_ref
                == f"compiler_artifact:{_text(getattr(artifact, 'artifact_kind', ''))}"
                and tuple(_refs(getattr(artifact, "source_ir_refs", ())))
                == tuple(_refs(getattr(record, "compiler_ir_refs", ())))
                and tuple(_refs(getattr(artifact, "compiler_pass_refs", ())))
                == tuple(_refs(getattr(record, "compiler_pass_refs", ())))
                and tuple(_refs(getattr(artifact, "graph_command_refs", ())))
                == tuple(
                    _refs(getattr(record, "research_graph_command_refs", ()))
                )
                and tuple(_refs(getattr(artifact, "evidence_refs", ())))
                == tuple(_refs(getattr(record, "evidence_refs", ())))
                and tuple(_refs(getattr(artifact, "validation_refs", ())))
                == tuple(_refs(getattr(record, "validation_refs", ())))
                and tuple(_refs(getattr(artifact, "canonical_command_refs", ())))
                == tuple(_refs(getattr(record, "canonical_command_refs", ())))
                and _text(getattr(artifact, "permission_ref", ""))
                in tuple(_refs(getattr(record, "permission_refs", ())))
                and set(_refs(getattr(record, "lifecycle_refs", ())))
                == {
                    artifact_refs[0],
                    *_refs(
                        getattr(artifact, "mathematical_spine_chain_refs", ())
                    ),
                }
            )
            if not artifact_exact:
                violations.append(
                    EntrypointEvidenceViolation(
                        "entrypoint_evidence_artifact_derivative_invalid",
                        "artifact coverage does not resolve one exact compiler artifact",
                        "lifecycle_refs",
                        evidence_ref,
                    )
                )
        expected = (
            ("recorded_by", evidence.owner_user_id, _text(getattr(record, "recorded_by", ""))),
            ("entry_source", evidence.entry_source, _text(getattr(record, "entry_source", ""))),
            ("entrypoint_ref", evidence.entrypoint_ref, _text(getattr(record, "entrypoint_ref", ""))),
            ("qro_refs", (evidence.qro_ref,), tuple(_refs(getattr(record, "qro_refs", ())))),
            ("research_graph_command_refs", (evidence.research_graph_ref,), tuple(_refs(getattr(record, "research_graph_command_refs", ())))),
            ("compiler_ir_refs", (evidence.compiler_ir_ref,), tuple(_refs(getattr(record, "compiler_ir_refs", ())))),
            ("compiler_pass_refs", (evidence.compiler_pass_ref,), tuple(_refs(getattr(record, "compiler_pass_refs", ())))),
            ("evidence_refs", (evidence.evidence_ref,), tuple(_refs(getattr(record, "evidence_refs", ())))),
            ("permission_refs", (evidence.permission_ref,), tuple(_refs(getattr(record, "permission_refs", ())))),
        )
        if artifact_derivative:
            expected = tuple(
                item for item in expected if item[0] != "entrypoint_ref"
            )
        if not platform_derivative and not artifact_derivative:
            expected = (
                *expected,
                ("coverage_ref", evidence.coverage_ref, _text(getattr(record, "coverage_ref", ""))),
                ("goal_sections", evidence.goal_sections, tuple(_refs(getattr(record, "goal_sections", ())))),
                ("lifecycle_refs", evidence.lifecycle_refs, tuple(_refs(getattr(record, "lifecycle_refs", ())))),
                ("rdp_refs", evidence.rdp_refs, tuple(_refs(getattr(record, "rdp_refs", ())))),
            )
        for field_name, evidence_value, record_value in expected:
            if evidence_value != record_value:
                violations.append(
                    EntrypointEvidenceViolation(
                        "entrypoint_evidence_linkage_mismatch",
                        "coverage and independent entrypoint evidence differ",
                        field_name,
                        evidence_ref,
                    )
                )
        if evidence.validation_ref not in tuple(
            _refs(getattr(record, "validation_refs", ()))
        ):
            violations.append(
                EntrypointEvidenceViolation(
                    "entrypoint_evidence_linkage_mismatch",
                    "coverage omits the evidence validation receipt",
                    "validation_refs",
                    evidence_ref,
                )
            )
        return EntrypointEvidenceDecision(not violations, tuple(violations))

    def validate_platform_ref(
        self,
        evidence_ref: str,
        *,
        owner_user_id: str,
        record: Any,
    ) -> EntrypointEvidenceDecision:
        try:
            evidence = self.evidence(
                evidence_ref,
                owner_user_id=owner_user_id,
            )
        except Exception as exc:  # noqa: BLE001 - linkage fails closed.
            return EntrypointEvidenceDecision(
                False,
                (
                    EntrypointEvidenceViolation(
                        "entrypoint_evidence_unknown",
                        f"entrypoint evidence lookup failed:{type(exc).__name__}",
                        "evidence_refs",
                        evidence_ref,
                    ),
                ),
            )
        violations = list(
            self.validate_current(
                evidence,
                owner_user_id=owner_user_id,
            ).violations
        )
        expected = (
            ("qro_ref", evidence.qro_ref, _text(getattr(record, "qro_ref", ""))),
            ("research_graph_ref", evidence.research_graph_ref, _text(getattr(record, "research_graph_ref", ""))),
            ("governance_ref", evidence.validation_ref, _text(getattr(record, "governance_ref", ""))),
        )
        for field_name, evidence_value, record_value in expected:
            if evidence_value != record_value:
                violations.append(
                    EntrypointEvidenceViolation(
                        "entrypoint_evidence_platform_linkage_mismatch",
                        "platform row and independent entrypoint evidence differ",
                        field_name,
                        evidence_ref,
                    )
                )
        lifecycle_ref = _text(getattr(record, "lifecycle_ref", ""))
        if evidence.lifecycle_refs and lifecycle_ref not in evidence.lifecycle_refs:
            violations.append(
                EntrypointEvidenceViolation(
                    "entrypoint_evidence_platform_linkage_mismatch",
                    "platform lifecycle is not bound by entrypoint evidence",
                    "lifecycle_ref",
                    evidence_ref,
                )
            )
        math_spine_ref = _text(getattr(record, "math_spine_ref", ""))
        if (
            evidence.mathematical_spine_chain_refs
            and math_spine_ref not in evidence.mathematical_spine_chain_refs
        ):
            violations.append(
                EntrypointEvidenceViolation(
                    "entrypoint_evidence_platform_linkage_mismatch",
                    "platform Mathematical Spine is not bound by entrypoint evidence",
                    "math_spine_ref",
                    evidence_ref,
                )
            )
        return EntrypointEvidenceDecision(not violations, tuple(violations))

class CompositeEntrypointEvidenceRegistry:
    """Read adapter over generic and row-specific independent evidence ledgers."""

    def __init__(self, registries: Iterable[Any]) -> None:
        self._registries = tuple(registries)
        if not self._registries:
            raise ValueError("composite entrypoint evidence requires a registry")
        for registry in self._registries:
            for method in ("evidence", "validate_current", "validate_platform_ref"):
                if not callable(getattr(registry, method, None)):
                    raise TypeError(
                        "composite entrypoint evidence registry lacks " + method
                    )

    @property
    def registries(self) -> tuple[Any, ...]:
        return self._registries

    def _provider(self, evidence_ref: str, *, owner_user_id: str) -> tuple[Any, Any]:
        matches: list[tuple[Any, Any]] = []
        for registry in self._registries:
            try:
                evidence = registry.evidence(
                    evidence_ref,
                    owner_user_id=owner_user_id,
                )
            except (KeyError, LookupError):
                continue
            matches.append((registry, evidence))
        if len(matches) != 1:
            raise KeyError("entrypoint evidence is missing or ambiguous")
        return matches[0]

    def evidence(self, evidence_ref: str, *, owner_user_id: str) -> Any:
        return self._provider(
            evidence_ref,
            owner_user_id=owner_user_id,
        )[1]

    def validate_current(self, record: Any, *, owner_user_id: str) -> Any:
        registry, persisted = self._provider(
            _text(getattr(record, "evidence_ref", "")),
            owner_user_id=owner_user_id,
        )
        if persisted != record:
            return EntrypointEvidenceDecision(
                False,
                (
                    EntrypointEvidenceViolation(
                        "entrypoint_evidence_projection_mismatch",
                        "evidence projection differs from the persisted record",
                        "evidence_ref",
                        _text(getattr(record, "evidence_ref", "")),
                    ),
                ),
            )
        return registry.validate_current(record, owner_user_id=owner_user_id)

    def validate_entrypoint_ref(
        self,
        evidence_ref: str,
        *,
        owner_user_id: str,
        record: Any,
        artifact_candidate: Any | None = None,
    ) -> Any:
        registry, evidence = self._provider(
            evidence_ref,
            owner_user_id=owner_user_id,
        )
        validator = getattr(registry, "validate_entrypoint_ref", None)
        if callable(validator):
            return validator(
                evidence_ref,
                owner_user_id=owner_user_id,
                record=record,
                artifact_candidate=artifact_candidate,
            )
        violations = list(
            registry.validate_current(
                evidence,
                owner_user_id=owner_user_id,
            ).violations
        )
        for field_name, evidence_value, record_value in (
            ("owner_user_id", _text(getattr(evidence, "owner_user_id", "")), _text(getattr(record, "recorded_by", ""))),
            ("entry_source", _text(getattr(evidence, "entry_source", "")), _text(getattr(record, "entry_source", ""))),
            ("entrypoint_ref", _text(getattr(evidence, "entrypoint_ref", "")), _text(getattr(record, "entrypoint_ref", ""))),
            ("qro_refs", (_text(getattr(evidence, "qro_ref", "")),), _refs(getattr(record, "qro_refs", ()))),
            ("research_graph_command_refs", (_text(getattr(evidence, "research_graph_ref", "")),), _refs(getattr(record, "research_graph_command_refs", ()))),
            ("lifecycle_refs", (_text(getattr(evidence, "lifecycle_ref", "")),), _refs(getattr(record, "lifecycle_refs", ()))),
        ):
            if evidence_value != record_value:
                violations.append(
                    EntrypointEvidenceViolation(
                        "entrypoint_evidence_linkage_mismatch",
                        "coverage and independent evidence differ",
                        field_name,
                        evidence_ref,
                    )
                )
        if tuple(_refs(getattr(record, "evidence_refs", ()))) != (evidence_ref,):
            violations.append(
                EntrypointEvidenceViolation(
                    "entrypoint_evidence_linkage_mismatch",
                    "coverage must cite exactly one independent evidence record",
                    "evidence_refs",
                    evidence_ref,
                )
            )
        governance_ref = _text(getattr(evidence, "governance_ref", ""))
        if governance_ref not in _refs(getattr(record, "validation_refs", ())):
            violations.append(
                EntrypointEvidenceViolation(
                    "entrypoint_evidence_linkage_mismatch",
                    "coverage omits the platform evidence governance receipt",
                    "validation_refs",
                    evidence_ref,
                )
            )
        return EntrypointEvidenceDecision(not violations, tuple(violations))

    def validate_platform_ref(
        self,
        evidence_ref: str,
        *,
        owner_user_id: str,
        record: Any,
    ) -> Any:
        registry, _evidence = self._provider(
            evidence_ref,
            owner_user_id=owner_user_id,
        )
        return registry.validate_platform_ref(
            evidence_ref,
            owner_user_id=owner_user_id,
            record=record,
        )


__all__ = [
    "ENTRYPOINT_EVIDENCE_VERSION",
    "ENTRYPOINT_EVIDENCE_PROOF_CODEC",
    "CompositeEntrypointEvidenceRegistry",
    "EntrypointEvidenceDecision",
    "EntrypointEvidenceRecord",
    "EntrypointEvidenceViolation",
    "PersistentEntrypointEvidenceRegistry",
    "entrypoint_evidence_from_dict",
    "validate_entrypoint_evidence_shape",
]
