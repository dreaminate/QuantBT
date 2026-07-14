"""GOAL §1/§7/§8 governed compiler IR contracts.

This module records the first durable compiler audit layer behind QRO and
Research Graph writes. It does not compile executable strategies by itself.
"""

from __future__ import annotations

import json
import os
import tempfile
import threading
from dataclasses import asdict, dataclass, is_dataclass
from enum import Enum
from pathlib import Path
from typing import Any

from ..lineage.ids import content_hash
from ..cross_process_lock import acquire_exclusive_fd
from .goal_proof_ledger import GoalProofLedger
from .goal_proof_records import (
    ATOMIC_PROOF_BUNDLE_REQUIRED,
    LOGICAL_TYPE_COMPILER_ARTIFACT,
    LOGICAL_TYPE_COMPILER_IR,
    LOGICAL_TYPE_COMPILER_PASS,
    GoalProofRecordProjection,
    GoalProofRecordProjectionError,
    ProofRecordCodec,
)
from .spine import ActorSource, EntrySource, RuntimeStatus


def _tuple(value: Any) -> tuple[Any, ...]:
    if value is None:
        return ()
    if isinstance(value, tuple):
        return value
    if isinstance(value, list):
        return tuple(value)
    return (value,)


def _present(value: str | None) -> bool:
    return bool(str(value or "").strip())


def _enum_text(value: Any) -> str:
    return str(value.value if isinstance(value, Enum) else value)


def _json_value(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    if is_dataclass(value):
        return _json_value(asdict(value))
    if isinstance(value, dict):
        return {str(k): _json_value(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_value(v) for v in value]
    return value


@dataclass(frozen=True)
class CompilerViolation:
    code: str
    message: str
    field: str = ""
    ref: str = ""


@dataclass(frozen=True)
class CompilerDecision:
    accepted: bool
    violations: tuple[CompilerViolation, ...]


@dataclass(frozen=True)
class CompilerIRRecord:
    ir_ref: str
    source_qro_refs: tuple[str, ...]
    graph_command_refs: tuple[str, ...]
    canonical_command_refs: tuple[str, ...]
    node_refs: tuple[str, ...]
    edge_refs: tuple[str, ...]
    artifact_refs: tuple[str, ...]
    theory_binding_refs: tuple[str, ...]
    consistency_check_refs: tuple[str, ...]
    evidence_refs: tuple[str, ...]
    validation_refs: tuple[str, ...]
    permission_ref: str
    deterministic_run_plan_ref: str
    rollback_ref: str
    environment_lock_ref: str
    mathematical_spine_chain_refs: tuple[str, ...] = ()
    owner: str = ""
    target_runtime: RuntimeStatus | str = RuntimeStatus.OFFLINE
    compiler_version: str = "governed-compiler-ir.v1"
    mock_profile: str = "none"

    def __post_init__(self) -> None:
        for field_name in (
            "source_qro_refs",
            "graph_command_refs",
            "canonical_command_refs",
            "node_refs",
            "edge_refs",
            "artifact_refs",
            "theory_binding_refs",
            "consistency_check_refs",
            "evidence_refs",
            "validation_refs",
            "mathematical_spine_chain_refs",
        ):
            object.__setattr__(self, field_name, tuple(str(v) for v in _tuple(getattr(self, field_name))))


@dataclass(frozen=True)
class CompilerPassRecord:
    pass_ref: str
    pass_name: str
    input_ir_refs: tuple[str, ...]
    output_ir_ref: str
    input_qro_refs: tuple[str, ...]
    graph_command_refs: tuple[str, ...]
    canonical_command_refs: tuple[str, ...]
    actor: str
    actor_source: ActorSource | str
    entry_source: EntrySource | str
    permission_ref: str
    tool_record_refs: tuple[str, ...]
    evidence_refs: tuple[str, ...]
    validation_refs: tuple[str, ...]
    deterministic_run_plan_ref: str
    rollback_ref: str
    status: str = "compiled"
    direct_graph_mutation: bool = False
    bypassed_permission: bool = False
    raw_llm_output_embedded_as_ir: bool = False

    def __post_init__(self) -> None:
        for field_name in (
            "input_ir_refs",
            "input_qro_refs",
            "graph_command_refs",
            "canonical_command_refs",
            "tool_record_refs",
            "evidence_refs",
            "validation_refs",
        ):
            object.__setattr__(self, field_name, tuple(str(v) for v in _tuple(getattr(self, field_name))))


@dataclass(frozen=True)
class CompilerArtifactRecord:
    artifact_ref: str
    artifact_kind: str
    source_ir_refs: tuple[str, ...]
    compiler_pass_refs: tuple[str, ...]
    graph_command_refs: tuple[str, ...]
    canonical_command_refs: tuple[str, ...]
    deterministic_run_plan_ref: str
    environment_lock_ref: str
    permission_ref: str
    output_contract_ref: str
    manifest_hash: str
    evidence_refs: tuple[str, ...]
    validation_refs: tuple[str, ...]
    mathematical_spine_chain_refs: tuple[str, ...] = ()
    owner: str = ""
    target_runtime: RuntimeStatus | str = RuntimeStatus.OFFLINE
    compiler_version: str = "governed-compiler-ir.v1"
    mock_profile: str = "none"
    executable: bool = False
    contains_source_code: bool = False
    raw_llm_output_embedded: bool = False
    plaintext_secret_embedded: bool = False
    silent_mock_fallback: bool = False

    def __post_init__(self) -> None:
        for field_name in (
            "source_ir_refs",
            "compiler_pass_refs",
            "graph_command_refs",
            "canonical_command_refs",
            "evidence_refs",
            "validation_refs",
            "mathematical_spine_chain_refs",
        ):
            object.__setattr__(self, field_name, tuple(str(v) for v in _tuple(getattr(self, field_name))))
        if not _present(self.artifact_ref):
            object.__setattr__(
                self,
                "artifact_ref",
                "compiler_artifact:" + content_hash(
                    {
                        "artifact_kind": self.artifact_kind,
                        "source_ir_refs": self.source_ir_refs,
                        "compiler_pass_refs": self.compiler_pass_refs,
                        "manifest_hash": self.manifest_hash,
                    }
                ),
            )


@dataclass(frozen=True)
class CanonicalCompilerRecords:
    """One owner-scoped compiler view from one proof-ledger snapshot."""

    owner: str
    irs: tuple[CompilerIRRecord, ...]
    passes: tuple[CompilerPassRecord, ...]
    artifacts: tuple[CompilerArtifactRecord, ...]


COMPILER_IR_PROOF_CODEC = ProofRecordCodec[
    CompilerIRRecord
](
    logical_type=LOGICAL_TYPE_COMPILER_IR,
    record_type=CompilerIRRecord,
    decode=lambda value: CompilerIRRecord(**value),
    logical_ref=lambda record: record.ir_ref,
    owner=lambda record: record.owner,
)

COMPILER_PASS_PROOF_CODEC = ProofRecordCodec[
    CompilerPassRecord
](
    logical_type=LOGICAL_TYPE_COMPILER_PASS,
    record_type=CompilerPassRecord,
    decode=lambda value: CompilerPassRecord(**value),
    logical_ref=lambda record: record.pass_ref,
    owner=lambda record: record.actor,
)

COMPILER_ARTIFACT_PROOF_CODEC = ProofRecordCodec[
    CompilerArtifactRecord
](
    logical_type=LOGICAL_TYPE_COMPILER_ARTIFACT,
    record_type=CompilerArtifactRecord,
    decode=lambda value: CompilerArtifactRecord(**value),
    logical_ref=lambda record: record.artifact_ref,
    owner=lambda record: record.owner,
)


def _require_list(
    violations: list[CompilerViolation],
    *,
    field_name: str,
    value: tuple[Any, ...],
    ref: str,
) -> None:
    if not value:
        violations.append(
            CompilerViolation(
                "compiler_required_ref_missing",
                f"{field_name} is required",
                field=field_name,
                ref=ref,
            )
        )


def _require_text(
    violations: list[CompilerViolation],
    *,
    field_name: str,
    value: str | None,
    ref: str,
) -> None:
    if not _present(value):
        violations.append(
            CompilerViolation(
                "compiler_required_ref_missing",
                f"{field_name} is required",
                field=field_name,
                ref=ref,
            )
        )


def validate_compiler_ir(ir: CompilerIRRecord) -> CompilerDecision:
    violations: list[CompilerViolation] = []
    _require_text(violations, field_name="ir_ref", value=ir.ir_ref, ref=ir.ir_ref)
    _require_text(violations, field_name="owner", value=ir.owner, ref=ir.ir_ref)
    for field_name in (
        "source_qro_refs",
        "graph_command_refs",
        "canonical_command_refs",
        "node_refs",
        "evidence_refs",
        "validation_refs",
    ):
        _require_list(violations, field_name=field_name, value=getattr(ir, field_name), ref=ir.ir_ref)
    for field_name in ("permission_ref", "deterministic_run_plan_ref", "rollback_ref", "environment_lock_ref"):
        _require_text(violations, field_name=field_name, value=getattr(ir, field_name), ref=ir.ir_ref)
    if ir.theory_binding_refs and not ir.consistency_check_refs:
        violations.append(
            CompilerViolation(
                "compiler_ir_missing_consistency_for_theory",
                "compiler IR with theory bindings requires consistency check refs",
                field="consistency_check_refs",
                ref=ir.ir_ref,
            )
        )
    if _enum_text(ir.target_runtime) == RuntimeStatus.LIVE.value and ir.mock_profile != "none":
        violations.append(
            CompilerViolation(
                "compiler_ir_live_mock_profile",
                "live compiler IR cannot carry a mock profile",
                field="mock_profile",
                ref=ir.ir_ref,
            )
        )
    return CompilerDecision(accepted=not violations, violations=tuple(violations))


def validate_compiler_pass(record: CompilerPassRecord) -> CompilerDecision:
    violations: list[CompilerViolation] = []
    for field_name in ("pass_ref", "pass_name", "output_ir_ref", "actor", "permission_ref"):
        _require_text(violations, field_name=field_name, value=getattr(record, field_name), ref=record.pass_ref)
    for field_name in (
        "input_qro_refs",
        "graph_command_refs",
        "canonical_command_refs",
        "tool_record_refs",
        "evidence_refs",
        "validation_refs",
    ):
        _require_list(violations, field_name=field_name, value=getattr(record, field_name), ref=record.pass_ref)
    for field_name in ("deterministic_run_plan_ref", "rollback_ref"):
        _require_text(violations, field_name=field_name, value=getattr(record, field_name), ref=record.pass_ref)
    if record.direct_graph_mutation:
        violations.append(
            CompilerViolation(
                "compiler_pass_direct_graph_mutation",
                "compiler passes must write through canonical commands, not direct graph mutation",
                field="direct_graph_mutation",
                ref=record.pass_ref,
            )
        )
    if record.bypassed_permission:
        violations.append(
            CompilerViolation(
                "compiler_pass_bypassed_permission",
                "compiler passes must preserve permission records",
                field="bypassed_permission",
                ref=record.pass_ref,
            )
        )
    if record.raw_llm_output_embedded_as_ir:
        violations.append(
            CompilerViolation(
                "compiler_pass_raw_llm_output_as_ir",
                "raw LLM output cannot become compiler IR without schema-constrained command materialization",
                field="raw_llm_output_embedded_as_ir",
                ref=record.pass_ref,
            )
        )
    return CompilerDecision(accepted=not violations, violations=tuple(violations))


def validate_compiler_artifact(record: CompilerArtifactRecord) -> CompilerDecision:
    violations: list[CompilerViolation] = []
    for field_name in (
        "artifact_ref",
        "artifact_kind",
        "deterministic_run_plan_ref",
        "environment_lock_ref",
        "permission_ref",
        "output_contract_ref",
        "manifest_hash",
        "owner",
    ):
        _require_text(violations, field_name=field_name, value=getattr(record, field_name), ref=record.artifact_ref)
    for field_name in (
        "source_ir_refs",
        "compiler_pass_refs",
        "graph_command_refs",
        "canonical_command_refs",
        "evidence_refs",
        "validation_refs",
        "mathematical_spine_chain_refs",
    ):
        _require_list(violations, field_name=field_name, value=getattr(record, field_name), ref=record.artifact_ref)
    if str(record.artifact_kind).strip().lower() in {"strategy_source", "python_source", "executable_strategy"}:
        violations.append(
            CompilerViolation(
                "compiler_artifact_source_generation_not_implemented",
                "current governed compiler artifacts are manifests only, not generated strategy source",
                field="artifact_kind",
                ref=record.artifact_ref,
            )
        )
    if record.executable:
        violations.append(
            CompilerViolation(
                "compiler_artifact_executable_not_supported",
                "current governed compiler artifact layer cannot claim executable output",
                field="executable",
                ref=record.artifact_ref,
            )
        )
    if record.contains_source_code:
        violations.append(
            CompilerViolation(
                "compiler_artifact_contains_source_code",
                "compiler artifact manifests must reference code or run plans without embedding source code",
                field="contains_source_code",
                ref=record.artifact_ref,
            )
        )
    if record.raw_llm_output_embedded:
        violations.append(
            CompilerViolation(
                "compiler_artifact_raw_llm_output",
                "raw LLM output cannot be embedded in compiler artifacts",
                field="raw_llm_output_embedded",
                ref=record.artifact_ref,
            )
        )
    if record.plaintext_secret_embedded:
        violations.append(
            CompilerViolation(
                "compiler_artifact_plaintext_secret",
                "compiler artifacts cannot embed plaintext secrets",
                field="plaintext_secret_embedded",
                ref=record.artifact_ref,
            )
        )
    if record.silent_mock_fallback:
        violations.append(
            CompilerViolation(
                "compiler_artifact_silent_mock_fallback",
                "compiler artifacts cannot rely on silent mock fallback",
                field="silent_mock_fallback",
                ref=record.artifact_ref,
            )
        )
    if _enum_text(record.target_runtime) == RuntimeStatus.LIVE.value and record.mock_profile != "none":
        violations.append(
            CompilerViolation(
                "compiler_artifact_live_mock_profile",
                "live compiler artifacts cannot carry a mock profile",
                field="mock_profile",
                ref=record.artifact_ref,
            )
        )
    return CompilerDecision(accepted=not violations, violations=tuple(violations))


def _decision_message(decision: CompilerDecision) -> str:
    return "; ".join(f"{v.code}:{v.field}" for v in decision.violations) or "compiler record rejected"


_EVENT_RECORD_TYPES: dict[str, tuple[str, type[Any]]] = {
    "compiler_ir_recorded": ("ir", CompilerIRRecord),
    "compiler_pass_recorded": ("compiler_pass", CompilerPassRecord),
    "compiler_artifact_recorded": ("artifact", CompilerArtifactRecord),
}


def _event_row(
    event_type: str,
    field_name: str,
    record: Any,
    *,
    owner: str,
) -> dict[str, Any]:
    return {
        "schema_version": 2,
        "event_type": event_type,
        "owner_user_id": owner,
        field_name: _json_value(record),
    }


def _atomic_rewrite_compiler_rows(
    path: Path,
    rows: tuple[dict[str, Any], ...],
) -> None:
    """Durably replace one compiler JSONL log while its lock is held."""

    fd, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.",
        suffix=".rollback",
        dir=str(path.parent),
    )
    temporary_path = Path(temporary_name)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "wb") as fh:
            fd = -1
            for row in rows:
                payload = (
                    json.dumps(
                        row,
                        ensure_ascii=False,
                        sort_keys=True,
                        separators=(",", ":"),
                    )
                    + "\n"
                ).encode("utf-8")
                written = fh.write(payload)
                if written != len(payload):
                    raise OSError("Governed Compiler rollback wrote a partial event")
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(temporary_path, path)
        directory_flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
        directory_fd = os.open(path.parent, directory_flags)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        if fd >= 0:
            os.close(fd)
        try:
            temporary_path.unlink()
        except FileNotFoundError:
            pass


class PersistentCompilerIRStore:
    """Append-only JSONL store for governed compiler IR/pass audit records."""

    def __init__(
        self,
        path: str | Path,
        *,
        proof_ledger: GoalProofLedger | None = None,
        legacy_read_only: bool = False,
    ) -> None:
        self._path = Path(path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._lock_path = self._path.with_suffix(self._path.suffix + ".lock")
        self._process_lock = threading.RLock()
        self._proof_projection = (
            GoalProofRecordProjection(proof_ledger)
            if proof_ledger is not None
            else None
        )
        self._legacy_read_only = bool(legacy_read_only)
        self._proof_head_types: dict[tuple[str, str], str] = {}
        self._irs: dict[tuple[str, str], CompilerIRRecord] = {}
        self._passes: dict[tuple[str, str], CompilerPassRecord] = {}
        self._artifacts: dict[tuple[str, str], CompilerArtifactRecord] = {}
        self._legacy_quarantined = {"irs": 0, "passes": 0, "artifacts": 0}
        self._load_existing()
        self._overlay_canonical_unlocked()

    @property
    def path(self) -> Path:
        return self._path

    def _load_existing(self) -> None:
        if not self._path.exists():
            return
        with self._path.open("r", encoding="utf-8") as fh:
            for line_no, line in enumerate(fh, start=1):
                if not line.strip():
                    continue
                try:
                    row = json.loads(line)
                    self._apply_row(row, persist=False)
                except Exception as exc:  # noqa: BLE001 - bad compiler history must block startup.
                    raise ValueError(f"invalid persisted Governed Compiler row at {self._path}:{line_no}") from exc

    def _refresh_from_disk_unlocked(self) -> None:
        self._irs = {}
        self._passes = {}
        self._artifacts = {}
        self._legacy_quarantined = {"irs": 0, "passes": 0, "artifacts": 0}
        self._load_existing()

    def _overlay_canonical_unlocked(self) -> None:
        if self._proof_projection is None:
            self._proof_head_types = {}
            return
        canonical_by_type, self._proof_head_types = (
            self._proof_projection.decode_many_with_index(
                COMPILER_IR_PROOF_CODEC,
                COMPILER_PASS_PROOF_CODEC,
                COMPILER_ARTIFACT_PROOF_CODEC,
            )
        )
        for codec, bucket_name, recorder, owner_getter in (
            (
                COMPILER_IR_PROOF_CODEC,
                "_irs",
                self._record_ir,
                lambda record: record.owner,
            ),
            (
                COMPILER_PASS_PROOF_CODEC,
                "_passes",
                self._record_pass,
                lambda record: record.actor,
            ),
            (
                COMPILER_ARTIFACT_PROOF_CODEC,
                "_artifacts",
                self._record_artifact,
                lambda record: record.owner,
            ),
        ):
            records = canonical_by_type[codec.logical_type]
            bucket = getattr(self, bucket_name)
            for record in records:
                owner = self._owner(owner_getter(record))
                logical_ref = codec.logical_ref(record)
                existing = bucket.get((owner, logical_ref))
                if existing is not None and existing != record:
                    raise ValueError(
                        "canonical Governed Compiler record collides with legacy "
                        f"record for owner/ref {owner!r}/{logical_ref!r}"
                    )
                recorder(record, owner=owner, persist=False)

    def _require_legacy_write_allowed(self) -> None:
        if self._legacy_read_only:
            raise RuntimeError(
                f"{ATOMIC_PROOF_BUNDLE_REQUIRED}: "
                "Governed Compiler legacy JSONL is read-only"
            )

    def _refresh_for_canonical_read(self) -> None:
        if self._proof_projection is not None:
            self.refresh()

    def refresh(self) -> None:
        """Reload the current durable compiler projection under its file lock."""

        with self._process_lock:
            fd = os.open(self._lock_path, os.O_RDWR | os.O_CREAT, 0o600)
            held = None
            try:
                os.chmod(self._lock_path, 0o600)
                held = acquire_exclusive_fd(fd, timeout_seconds=30.0)
                self._refresh_from_disk_unlocked()
            finally:
                if held is not None:
                    held.release()
                os.close(fd)
            self._overlay_canonical_unlocked()

    @staticmethod
    def _owner(owner: str) -> str:
        normalized = str(owner or "").strip()
        if not normalized:
            raise ValueError("Governed Compiler owner is required")
        return normalized

    def _append_event(self, row: dict[str, Any]) -> None:
        self._require_legacy_write_allowed()
        fd = os.open(self._lock_path, os.O_RDWR | os.O_CREAT, 0o600)
        held = None
        try:
            os.chmod(self._lock_path, 0o600)
            held = acquire_exclusive_fd(fd, timeout_seconds=30.0)
            event_type = str(row.get("event_type") or "")
            field_name, _record_type = _EVENT_RECORD_TYPES[event_type]
            ref_field = {
                "ir": "ir_ref",
                "compiler_pass": "pass_ref",
                "artifact": "artifact_ref",
            }[field_name]
            incoming_ref = str(row[field_name][ref_field])
            if self._path.exists():
                with self._path.open("r", encoding="utf-8") as existing_fh:
                    for line_no, line in enumerate(existing_fh, start=1):
                        if not line.strip():
                            continue
                        existing = json.loads(line)
                        if (
                            existing.get("schema_version") == 2
                            and existing.get("event_type") == event_type
                            and existing.get("owner_user_id")
                            == row.get("owner_user_id")
                            and isinstance(existing.get(field_name), dict)
                            and str(existing[field_name].get(ref_field) or "")
                            == incoming_ref
                        ):
                            if existing == row:
                                return
                            raise ValueError(
                                "Governed Compiler persisted identity collision at "
                                f"{self._path}:{line_no}"
                            )
            with self._path.open("a", encoding="utf-8") as fh:
                fh.write(
                    json.dumps(
                        row,
                        ensure_ascii=False,
                        sort_keys=True,
                        separators=(",", ":"),
                    )
                    + "\n"
                )
                fh.flush()
                os.fsync(fh.fileno())
        finally:
            if held is not None:
                held.release()
            os.close(fd)

    def _apply_row(self, row: dict[str, Any], *, persist: bool) -> None:
        schema_version = row.get("schema_version")
        if schema_version == 1:
            event_type = str(row.get("event_type") or "")
            bucket = {
                "compiler_ir_recorded": "irs",
                "compiler_pass_recorded": "passes",
                "compiler_artifact_recorded": "artifacts",
            }.get(event_type)
            if bucket is None:
                raise ValueError(f"unknown Governed Compiler event_type={event_type!r}")
            field_name, record_type = _EVENT_RECORD_TYPES[event_type]
            raw = row.get(field_name)
            if not isinstance(raw, dict):
                raise ValueError(f"Governed Compiler event missing {field_name}")
            record_type(**raw)
            self._legacy_quarantined[bucket] += 1
            return
        if schema_version != 2:
            raise ValueError("unsupported Governed Compiler schema_version")
        event_type = str(row.get("event_type") or "")
        spec = _EVENT_RECORD_TYPES.get(event_type)
        if spec is None:
            raise ValueError(f"unknown Governed Compiler event_type={event_type!r}")
        field_name, record_type = spec
        raw = row.get(field_name)
        if not isinstance(raw, dict):
            raise ValueError(f"Governed Compiler event missing {field_name}")
        record = record_type(**raw)
        owner = self._owner(str(row.get("owner_user_id") or ""))
        if isinstance(record, CompilerIRRecord):
            if record.owner != owner:
                raise ValueError("compiler IR owner envelope mismatch")
            self._record_ir(record, owner=owner, persist=persist)
        elif isinstance(record, CompilerPassRecord):
            if record.actor != owner:
                raise ValueError("compiler pass owner envelope mismatch")
            self._record_pass(record, owner=owner, persist=persist)
        elif isinstance(record, CompilerArtifactRecord):
            if record.owner != owner:
                raise ValueError("compiler artifact owner envelope mismatch")
            self._record_artifact(record, owner=owner, persist=persist)
        else:
            raise ValueError(f"unsupported Governed Compiler record type {type(record).__name__}")

    def record_ir(self, ir: CompilerIRRecord) -> CompilerIRRecord:
        self._require_legacy_write_allowed()
        with self._process_lock:
            return self._record_ir(ir, owner=self._owner(ir.owner), persist=True)

    def _record_ir(
        self,
        ir: CompilerIRRecord,
        *,
        owner: str,
        persist: bool,
    ) -> CompilerIRRecord:
        decision = validate_compiler_ir(ir)
        if not decision.accepted:
            raise ValueError(_decision_message(decision))
        owner = self._owner(owner)
        if ir.owner != owner:
            raise ValueError("compiler IR owner mismatch")
        key = (owner, ir.ir_ref)
        existing = self._irs.get(key)
        if existing is not None:
            if existing != ir:
                raise ValueError("compiler IR identity collision for owner")
            return existing
        if persist:
            self._append_event(
                _event_row("compiler_ir_recorded", "ir", ir, owner=owner)
            )
        self._irs[key] = ir
        return ir

    def record_pass(self, record: CompilerPassRecord) -> CompilerPassRecord:
        self._require_legacy_write_allowed()
        with self._process_lock:
            return self._record_pass(
                record,
                owner=self._owner(record.actor),
                persist=True,
            )

    def _record_pass(
        self,
        record: CompilerPassRecord,
        *,
        owner: str,
        persist: bool,
    ) -> CompilerPassRecord:
        decision = validate_compiler_pass(record)
        if not decision.accepted:
            raise ValueError(_decision_message(decision))
        owner = self._owner(owner)
        if record.actor != owner:
            raise ValueError("compiler pass owner mismatch")
        output_key = (owner, record.output_ir_ref)
        if output_key not in self._irs:
            raise ValueError(f"compiler pass output_ir_ref {record.output_ir_ref!r} is not recorded")
        for ir_ref in record.input_ir_refs:
            if (owner, ir_ref) not in self._irs:
                raise ValueError(f"compiler pass input_ir_ref {ir_ref!r} is not recorded")
        key = (owner, record.pass_ref)
        existing = self._passes.get(key)
        if existing is not None:
            if existing != record:
                raise ValueError("compiler pass identity collision for owner")
            return existing
        if persist:
            self._append_event(
                _event_row(
                    "compiler_pass_recorded",
                    "compiler_pass",
                    record,
                    owner=owner,
                )
            )
        self._passes[key] = record
        return record

    def record_artifact(self, record: CompilerArtifactRecord) -> CompilerArtifactRecord:
        self._require_legacy_write_allowed()
        with self._process_lock:
            return self._record_artifact(
                record,
                owner=self._owner(record.owner),
                persist=True,
            )

    def _record_artifact(
        self,
        record: CompilerArtifactRecord,
        *,
        owner: str,
        persist: bool,
    ) -> CompilerArtifactRecord:
        decision = validate_compiler_artifact(record)
        if not decision.accepted:
            raise ValueError(_decision_message(decision))
        owner = self._owner(owner)
        if record.owner != owner:
            raise ValueError("compiler artifact owner mismatch")
        for ir_ref in record.source_ir_refs:
            if (owner, ir_ref) not in self._irs:
                raise ValueError(f"compiler artifact source_ir_ref {ir_ref!r} is not recorded")
        for pass_ref in record.compiler_pass_refs:
            compiler_pass = self._passes.get((owner, pass_ref))
            if compiler_pass is None:
                raise ValueError(f"compiler artifact compiler_pass_ref {pass_ref!r} is not recorded")
            if compiler_pass.output_ir_ref not in record.source_ir_refs:
                raise ValueError(
                    f"compiler artifact pass {pass_ref!r} output_ir_ref "
                    f"{compiler_pass.output_ir_ref!r} is not in source_ir_refs"
                )
        key = (owner, record.artifact_ref)
        existing = self._artifacts.get(key)
        if existing is not None:
            if existing != record:
                raise ValueError("compiler artifact identity collision for owner")
            return existing
        if persist:
            self._append_event(
                _event_row(
                    "compiler_artifact_recorded",
                    "artifact",
                    record,
                    owner=owner,
                )
            )
        self._artifacts[key] = record
        return record

    def _unambiguous(
        self,
        records: dict[tuple[str, str], Any],
        record_ref: str,
        *,
        logical_type: str,
    ) -> Any:
        if self._proof_projection is not None:
            current_types = {
                current_type
                for (_owner, ref), current_type in self._proof_head_types.items()
                if ref == record_ref
            }
            wrong_types = current_types - {logical_type}
            if wrong_types:
                raise GoalProofRecordProjectionError(
                    "canonical GOAL proof logical ref/type collision: "
                    f"{record_ref!r} has current type(s) "
                    f"{','.join(sorted(wrong_types))!r}, expected {logical_type!r}"
                )
        matches = [
            record for (_owner, ref), record in records.items() if ref == record_ref
        ]
        if not matches:
            raise KeyError(record_ref)
        if len(matches) != 1:
            raise ValueError(f"Governed Compiler ref {record_ref!r} is owner-ambiguous")
        return matches[0]

    def ir(self, ir_ref: str, *, owner: str | None = None) -> CompilerIRRecord:
        self._refresh_for_canonical_read()
        if owner is not None and self._proof_projection is not None:
            normalized_owner = self._owner(owner)
            current_type = self._proof_head_types.get(
                (normalized_owner, ir_ref)
            )
            if current_type is not None and current_type != LOGICAL_TYPE_COMPILER_IR:
                raise GoalProofRecordProjectionError(
                    "canonical GOAL proof logical ref/type collision: "
                    f"{ir_ref!r} is {current_type!r}, expected "
                    f"{LOGICAL_TYPE_COMPILER_IR!r}"
                )
            if current_type == LOGICAL_TYPE_COMPILER_IR:
                return self._irs[(normalized_owner, ir_ref)]
        if owner is None:
            return self._unambiguous(
                self._irs,
                ir_ref,
                logical_type=LOGICAL_TYPE_COMPILER_IR,
            )
        return self._irs[(self._owner(owner), ir_ref)]

    def compiler_pass(
        self,
        pass_ref: str,
        *,
        owner: str | None = None,
    ) -> CompilerPassRecord:
        self._refresh_for_canonical_read()
        if owner is not None and self._proof_projection is not None:
            normalized_owner = self._owner(owner)
            current_type = self._proof_head_types.get(
                (normalized_owner, pass_ref)
            )
            if current_type is not None and current_type != LOGICAL_TYPE_COMPILER_PASS:
                raise GoalProofRecordProjectionError(
                    "canonical GOAL proof logical ref/type collision: "
                    f"{pass_ref!r} is {current_type!r}, expected "
                    f"{LOGICAL_TYPE_COMPILER_PASS!r}"
                )
            if current_type == LOGICAL_TYPE_COMPILER_PASS:
                return self._passes[(normalized_owner, pass_ref)]
        if owner is None:
            return self._unambiguous(
                self._passes,
                pass_ref,
                logical_type=LOGICAL_TYPE_COMPILER_PASS,
            )
        return self._passes[(self._owner(owner), pass_ref)]

    def artifact(
        self,
        artifact_ref: str,
        *,
        owner: str | None = None,
    ) -> CompilerArtifactRecord:
        self._refresh_for_canonical_read()
        if owner is not None and self._proof_projection is not None:
            normalized_owner = self._owner(owner)
            current_type = self._proof_head_types.get(
                (normalized_owner, artifact_ref)
            )
            if (
                current_type is not None
                and current_type != LOGICAL_TYPE_COMPILER_ARTIFACT
            ):
                raise GoalProofRecordProjectionError(
                    "canonical GOAL proof logical ref/type collision: "
                    f"{artifact_ref!r} is {current_type!r}, expected "
                    f"{LOGICAL_TYPE_COMPILER_ARTIFACT!r}"
                )
            if current_type == LOGICAL_TYPE_COMPILER_ARTIFACT:
                return self._artifacts[(normalized_owner, artifact_ref)]
        if owner is None:
            return self._unambiguous(
                self._artifacts,
                artifact_ref,
                logical_type=LOGICAL_TYPE_COMPILER_ARTIFACT,
            )
        return self._artifacts[(self._owner(owner), artifact_ref)]

    def _canonical_records_with_index(
        self,
        *,
        owner: str,
    ) -> tuple[CanonicalCompilerRecords, dict[tuple[str, str], str]]:
        normalized_owner = self._owner(owner)
        if self._proof_projection is None:
            return (
                CanonicalCompilerRecords(
                    owner=normalized_owner,
                    irs=(),
                    passes=(),
                    artifacts=(),
                ),
                {},
            )
        decoded, head_types = self._proof_projection.decode_many_with_index(
            COMPILER_IR_PROOF_CODEC,
            COMPILER_PASS_PROOF_CODEC,
            COMPILER_ARTIFACT_PROOF_CODEC,
            owner=normalized_owner,
        )
        irs = tuple(decoded[LOGICAL_TYPE_COMPILER_IR])
        passes = tuple(decoded[LOGICAL_TYPE_COMPILER_PASS])
        artifacts = tuple(decoded[LOGICAL_TYPE_COMPILER_ARTIFACT])

        ir_refs = {record.ir_ref for record in irs}
        pass_by_ref = {record.pass_ref: record for record in passes}
        for record in passes:
            decision = validate_compiler_pass(record)
            if not decision.accepted:
                raise GoalProofRecordProjectionError(
                    "canonical compiler pass is invalid: "
                    + _decision_message(decision)
                )
            missing_ir_refs = {
                record.output_ir_ref,
                *record.input_ir_refs,
            } - ir_refs
            if missing_ir_refs:
                raise GoalProofRecordProjectionError(
                    "canonical compiler pass references non-canonical IR: "
                    + ",".join(sorted(missing_ir_refs))
                )
        for record in irs:
            decision = validate_compiler_ir(record)
            if not decision.accepted:
                raise GoalProofRecordProjectionError(
                    "canonical compiler IR is invalid: "
                    + _decision_message(decision)
                )
        for record in artifacts:
            decision = validate_compiler_artifact(record)
            if not decision.accepted:
                raise GoalProofRecordProjectionError(
                    "canonical compiler artifact is invalid: "
                    + _decision_message(decision)
                )
            missing_ir_refs = set(record.source_ir_refs) - ir_refs
            if missing_ir_refs:
                raise GoalProofRecordProjectionError(
                    "canonical compiler artifact references non-canonical IR: "
                    + ",".join(sorted(missing_ir_refs))
                )
            missing_pass_refs = set(record.compiler_pass_refs) - set(pass_by_ref)
            if missing_pass_refs:
                raise GoalProofRecordProjectionError(
                    "canonical compiler artifact references non-canonical pass: "
                    + ",".join(sorted(missing_pass_refs))
                )
            for pass_ref in record.compiler_pass_refs:
                if pass_by_ref[pass_ref].output_ir_ref not in record.source_ir_refs:
                    raise GoalProofRecordProjectionError(
                        "canonical compiler artifact pass output is not a source IR: "
                        + pass_ref
                    )
        return (
            CanonicalCompilerRecords(
                owner=normalized_owner,
                irs=irs,
                passes=passes,
                artifacts=artifacts,
            ),
            head_types,
        )

    def canonical_records(self, *, owner: str) -> CanonicalCompilerRecords:
        """Return only exact current proof heads from one owner snapshot.

        Legacy JSONL rows never enter this view.  All three compiler record
        families are decoded from the same immutable proof-ledger snapshot so
        callers such as summaries cannot mix generations across separate
        reads.
        """

        records, _head_types = self._canonical_records_with_index(owner=owner)
        return records

    def canonical_ir(self, ir_ref: str, *, owner: str) -> CompilerIRRecord:
        records, head_types = self._canonical_records_with_index(owner=owner)
        current_type = head_types.get((records.owner, ir_ref))
        if current_type is not None and current_type != LOGICAL_TYPE_COMPILER_IR:
            raise GoalProofRecordProjectionError(
                "canonical GOAL proof logical ref/type collision: "
                f"{ir_ref!r} is {current_type!r}, expected "
                f"{LOGICAL_TYPE_COMPILER_IR!r}"
            )
        for record in records.irs:
            if record.ir_ref == ir_ref:
                return record
        raise KeyError(ir_ref)

    def canonical_compiler_pass(
        self,
        pass_ref: str,
        *,
        owner: str,
    ) -> CompilerPassRecord:
        records, head_types = self._canonical_records_with_index(owner=owner)
        current_type = head_types.get((records.owner, pass_ref))
        if (
            current_type is not None
            and current_type != LOGICAL_TYPE_COMPILER_PASS
        ):
            raise GoalProofRecordProjectionError(
                "canonical GOAL proof logical ref/type collision: "
                f"{pass_ref!r} is {current_type!r}, expected "
                f"{LOGICAL_TYPE_COMPILER_PASS!r}"
            )
        for record in records.passes:
            if record.pass_ref == pass_ref:
                return record
        raise KeyError(pass_ref)

    def canonical_artifact(
        self,
        artifact_ref: str,
        *,
        owner: str,
    ) -> CompilerArtifactRecord:
        records, head_types = self._canonical_records_with_index(owner=owner)
        current_type = head_types.get((records.owner, artifact_ref))
        if (
            current_type is not None
            and current_type != LOGICAL_TYPE_COMPILER_ARTIFACT
        ):
            raise GoalProofRecordProjectionError(
                "canonical GOAL proof logical ref/type collision: "
                f"{artifact_ref!r} is {current_type!r}, expected "
                f"{LOGICAL_TYPE_COMPILER_ARTIFACT!r}"
            )
        for record in records.artifacts:
            if record.artifact_ref == artifact_ref:
                return record
        raise KeyError(artifact_ref)

    def irs(self, *, owner: str | None = None) -> list[CompilerIRRecord]:
        self._refresh_for_canonical_read()
        if owner is None:
            return list(self._irs.values())
        normalized = self._owner(owner)
        return [record for (record_owner, _), record in self._irs.items() if record_owner == normalized]

    def passes(self, *, owner: str | None = None) -> list[CompilerPassRecord]:
        self._refresh_for_canonical_read()
        if owner is None:
            return list(self._passes.values())
        normalized = self._owner(owner)
        return [record for (record_owner, _), record in self._passes.items() if record_owner == normalized]

    def artifacts(self, *, owner: str | None = None) -> list[CompilerArtifactRecord]:
        self._refresh_for_canonical_read()
        if owner is None:
            return list(self._artifacts.values())
        normalized = self._owner(owner)
        return [record for (record_owner, _), record in self._artifacts.items() if record_owner == normalized]

    def rollback_exact_bundle(
        self,
        *,
        ir: CompilerIRRecord,
        compiler_pass: CompilerPassRecord | None = None,
        owner: str | None = None,
    ) -> bool:
        """Remove one exact IR/pass bundle when no later compiler record depends on it.

        ``compiler_pass`` is optional so a failure between IR and pass persistence
        can compensate the IR-only prefix. The full dataclass payload and owner
        envelope are part of the identity check.
        """

        self._require_legacy_write_allowed()
        normalized_owner = self._owner(owner or ir.owner)
        if ir.owner != normalized_owner:
            raise ValueError("compiler rollback IR owner mismatch")
        if compiler_pass is not None:
            if compiler_pass.actor != normalized_owner:
                raise ValueError("compiler rollback pass owner mismatch")
            if compiler_pass.output_ir_ref != ir.ir_ref:
                raise ValueError("compiler rollback pass output does not match IR")

        with self._process_lock:
            fd = os.open(self._lock_path, os.O_RDWR | os.O_CREAT, 0o600)
            held = None
            try:
                os.chmod(self._lock_path, 0o600)
                held = acquire_exclusive_fd(fd, timeout_seconds=30.0)
                self._refresh_from_disk_unlocked()

                ir_key = (normalized_owner, ir.ir_ref)
                persisted_ir = self._irs.get(ir_key)
                pass_key = (
                    (normalized_owner, compiler_pass.pass_ref)
                    if compiler_pass is not None
                    else None
                )
                persisted_pass = (
                    self._passes.get(pass_key) if pass_key is not None else None
                )
                if persisted_ir is None and persisted_pass is None:
                    return False
                if persisted_ir != ir:
                    raise ValueError("compiler rollback IR identity mismatch")
                if compiler_pass is not None and persisted_pass != compiler_pass:
                    raise ValueError("compiler rollback pass identity mismatch")

                dependent_passes = tuple(
                    record.pass_ref
                    for (record_owner, _), record in self._passes.items()
                    if record_owner == normalized_owner
                    and (
                        compiler_pass is None
                        or record.pass_ref != compiler_pass.pass_ref
                    )
                    and (
                        ir.ir_ref in record.input_ir_refs
                        or record.output_ir_ref == ir.ir_ref
                    )
                )
                if dependent_passes:
                    raise ValueError(
                        "compiler rollback refused because dependent passes reference "
                        f"the IR: {','.join(dependent_passes)}"
                    )

                dependent_artifacts = tuple(
                    record.artifact_ref
                    for (record_owner, _), record in self._artifacts.items()
                    if record_owner == normalized_owner
                    and (
                        ir.ir_ref in record.source_ir_refs
                        or (
                            compiler_pass is not None
                            and compiler_pass.pass_ref in record.compiler_pass_refs
                        )
                    )
                )
                if dependent_artifacts:
                    raise ValueError(
                        "compiler rollback refused because artifacts reference the "
                        f"bundle: {','.join(dependent_artifacts)}"
                    )

                rows: list[dict[str, Any]] = []
                if self._path.exists():
                    with self._path.open("r", encoding="utf-8") as fh:
                        rows = [json.loads(line) for line in fh if line.strip()]
                expected_rows = [
                    _event_row(
                        "compiler_ir_recorded",
                        "ir",
                        ir,
                        owner=normalized_owner,
                    )
                ]
                if compiler_pass is not None:
                    expected_rows.append(
                        _event_row(
                            "compiler_pass_recorded",
                            "compiler_pass",
                            compiler_pass,
                            owner=normalized_owner,
                        )
                    )
                for expected in expected_rows:
                    if sum(row == expected for row in rows) != 1:
                        raise ValueError(
                            "compiler rollback exact persisted event is not unique"
                        )
                retained = tuple(
                    row for row in rows if not any(row == expected for expected in expected_rows)
                )
                _atomic_rewrite_compiler_rows(self._path, retained)
                self._refresh_from_disk_unlocked()
                return True
            finally:
                if held is not None:
                    held.release()
                os.close(fd)

    def legacy_quarantined_counts(self) -> dict[str, int]:
        return dict(self._legacy_quarantined)

    def is_canonical_current(
        self,
        record: CompilerIRRecord | CompilerPassRecord | CompilerArtifactRecord,
        *,
        owner: str | None = None,
    ) -> bool:
        """Return whether ``record`` is the exact live SQLite proof head."""

        if self._proof_projection is None:
            return False
        if isinstance(record, CompilerIRRecord):
            codec = COMPILER_IR_PROOF_CODEC
            record_owner = record.owner
        elif isinstance(record, CompilerPassRecord):
            codec = COMPILER_PASS_PROOF_CODEC
            record_owner = record.actor
        elif isinstance(record, CompilerArtifactRecord):
            codec = COMPILER_ARTIFACT_PROOF_CODEC
            record_owner = record.owner
        else:  # pragma: no cover - the annotation is narrower than runtime calls.
            raise TypeError("unsupported Governed Compiler canonical record type")
        if owner is not None and self._owner(owner) != self._owner(record_owner):
            return False
        return self._proof_projection.is_exact_current(record, codec=codec)


__all__ = [
    "CanonicalCompilerRecords",
    "COMPILER_ARTIFACT_PROOF_CODEC",
    "COMPILER_IR_PROOF_CODEC",
    "COMPILER_PASS_PROOF_CODEC",
    "CompilerArtifactRecord",
    "CompilerDecision",
    "CompilerIRRecord",
    "CompilerPassRecord",
    "CompilerViolation",
    "PersistentCompilerIRStore",
    "validate_compiler_artifact",
    "validate_compiler_ir",
    "validate_compiler_pass",
]
