"""GOAL §1/§7/§8 governed compiler IR contracts.

This module records the first durable compiler audit layer behind QRO and
Research Graph writes. It does not compile executable strategies by itself.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, is_dataclass
from enum import Enum
from pathlib import Path
from typing import Any

from ..lineage.ids import content_hash
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


def _event_row(event_type: str, field_name: str, record: Any) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "event_type": event_type,
        field_name: _json_value(record),
    }


class PersistentCompilerIRStore:
    """Append-only JSONL store for governed compiler IR/pass audit records."""

    def __init__(self, path: str | Path) -> None:
        self._path = Path(path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._irs: dict[str, CompilerIRRecord] = {}
        self._passes: dict[str, CompilerPassRecord] = {}
        self._artifacts: dict[str, CompilerArtifactRecord] = {}
        self._load_existing()

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

    def _append_event(self, row: dict[str, Any]) -> None:
        with self._path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n")
            fh.flush()

    def _apply_row(self, row: dict[str, Any], *, persist: bool) -> None:
        if row.get("schema_version") != 1:
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
        if isinstance(record, CompilerIRRecord):
            self._record_ir(record, persist=persist)
        elif isinstance(record, CompilerPassRecord):
            self._record_pass(record, persist=persist)
        elif isinstance(record, CompilerArtifactRecord):
            self._record_artifact(record, persist=persist)
        else:
            raise ValueError(f"unsupported Governed Compiler record type {type(record).__name__}")

    def record_ir(self, ir: CompilerIRRecord) -> CompilerIRRecord:
        return self._record_ir(ir, persist=True)

    def _record_ir(self, ir: CompilerIRRecord, *, persist: bool) -> CompilerIRRecord:
        decision = validate_compiler_ir(ir)
        if not decision.accepted:
            raise ValueError(_decision_message(decision))
        self._irs[ir.ir_ref] = ir
        if persist:
            self._append_event(_event_row("compiler_ir_recorded", "ir", ir))
        return ir

    def record_pass(self, record: CompilerPassRecord) -> CompilerPassRecord:
        return self._record_pass(record, persist=True)

    def _record_pass(self, record: CompilerPassRecord, *, persist: bool) -> CompilerPassRecord:
        decision = validate_compiler_pass(record)
        if not decision.accepted:
            raise ValueError(_decision_message(decision))
        if record.output_ir_ref not in self._irs:
            raise ValueError(f"compiler pass output_ir_ref {record.output_ir_ref!r} is not recorded")
        for ir_ref in record.input_ir_refs:
            if ir_ref not in self._irs:
                raise ValueError(f"compiler pass input_ir_ref {ir_ref!r} is not recorded")
        self._passes[record.pass_ref] = record
        if persist:
            self._append_event(_event_row("compiler_pass_recorded", "compiler_pass", record))
        return record

    def record_artifact(self, record: CompilerArtifactRecord) -> CompilerArtifactRecord:
        return self._record_artifact(record, persist=True)

    def _record_artifact(self, record: CompilerArtifactRecord, *, persist: bool) -> CompilerArtifactRecord:
        decision = validate_compiler_artifact(record)
        if not decision.accepted:
            raise ValueError(_decision_message(decision))
        for ir_ref in record.source_ir_refs:
            if ir_ref not in self._irs:
                raise ValueError(f"compiler artifact source_ir_ref {ir_ref!r} is not recorded")
        for pass_ref in record.compiler_pass_refs:
            compiler_pass = self._passes.get(pass_ref)
            if compiler_pass is None:
                raise ValueError(f"compiler artifact compiler_pass_ref {pass_ref!r} is not recorded")
            if compiler_pass.output_ir_ref not in record.source_ir_refs:
                raise ValueError(
                    f"compiler artifact pass {pass_ref!r} output_ir_ref "
                    f"{compiler_pass.output_ir_ref!r} is not in source_ir_refs"
                )
        self._artifacts[record.artifact_ref] = record
        if persist:
            self._append_event(_event_row("compiler_artifact_recorded", "artifact", record))
        return record

    def ir(self, ir_ref: str) -> CompilerIRRecord:
        return self._irs[ir_ref]

    def compiler_pass(self, pass_ref: str) -> CompilerPassRecord:
        return self._passes[pass_ref]

    def artifact(self, artifact_ref: str) -> CompilerArtifactRecord:
        return self._artifacts[artifact_ref]

    def irs(self) -> list[CompilerIRRecord]:
        return list(self._irs.values())

    def passes(self) -> list[CompilerPassRecord]:
        return list(self._passes.values())

    def artifacts(self) -> list[CompilerArtifactRecord]:
        return list(self._artifacts.values())


__all__ = [
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
