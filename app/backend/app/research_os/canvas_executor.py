"""Canonical Canvas asset mutation executor.

The read model in ``canvas_projection`` is not the source of truth. This module
turns a governed Canvas edit into two Research Graph commands:

1. record the Canvas mutation audit;
2. upsert a new QRO version with only reference/hash fields changed.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from enum import Enum
from typing import Any

from ..lineage.ids import content_hash
from .desk_projection import CanvasMutationRecord, validate_canvas_mutation
from .spine import EntrySource, QRORecord, ResearchGraphCommand, ResearchGraphError, ResearchGraphStore, RuntimeStatus


@dataclass(frozen=True)
class CanvasAssetMutationResult:
    mutation_command_id: str
    qro_command_id: str
    qro_id: str
    qro_version: int
    projection_ref: str
    updated_field_path: str


def _enum_text(value: Any) -> str:
    return str(value.value if isinstance(value, Enum) else value)


def _qro_type(qro: QRORecord) -> str:
    return _enum_text(qro.qro_type)


def _runtime(qro: QRORecord) -> str:
    return _enum_text(qro.runtime_status)


def _require_value_ref(record: CanvasMutationRecord) -> str:
    value_ref = str(record.value_ref or "").strip()
    if not value_ref:
        raise ResearchGraphError("canvas asset mutation requires value_ref for *_ref fields")
    if any(ch.isspace() for ch in value_ref) or ":" not in value_ref:
        raise ResearchGraphError("canvas asset mutation value_ref must be a reference token, not raw text")
    return value_ref


def _require_value_hash(record: CanvasMutationRecord) -> str:
    value_hash = str(record.value_hash or "").strip()
    if not value_hash:
        raise ResearchGraphError("canvas asset mutation requires value_hash for *_hash fields")
    if any(ch.isspace() for ch in value_hash):
        raise ResearchGraphError("canvas asset mutation value_hash must be a compact hash token")
    return value_hash


def _with_contract_field(qro: QRORecord, record: CanvasMutationRecord) -> QRORecord:
    field_path = str(record.field_path or "")
    if "." not in field_path:
        raise ResearchGraphError("canvas asset mutation field_path must target input_contract.* or output_contract.*")
    root, field_name = field_path.split(".", 1)
    if root not in {"input_contract", "output_contract"}:
        raise ResearchGraphError("canvas asset mutation can only update QRO input_contract or output_contract")
    if "." in field_name or not field_name:
        raise ResearchGraphError("canvas asset mutation only supports one-level contract fields")
    if not (field_name.endswith("_ref") or field_name.endswith("_hash")):
        raise ResearchGraphError("canvas asset mutation contract field must end with _ref or _hash")

    input_contract = dict(qro.input_contract)
    output_contract = dict(qro.output_contract)
    target = input_contract if root == "input_contract" else output_contract
    if field_name.endswith("_ref"):
        target[field_name] = _require_value_ref(record)
        if record.value_hash:
            target[field_name[: -len("_ref")] + "_hash"] = _require_value_hash(record)
    else:
        target[field_name] = _require_value_hash(record)
    return replace(qro, input_contract=input_contract, output_contract=output_contract)


def _with_appended_ref(qro: QRORecord, record: CanvasMutationRecord) -> QRORecord:
    value_ref = _require_value_ref(record)
    if record.field_path == "evidence_refs":
        refs = tuple(dict.fromkeys((*qro.evidence_refs, value_ref)))
        return replace(qro, evidence_refs=refs)
    if record.field_path == "mathematical_refs":
        refs = tuple(dict.fromkeys((*qro.mathematical_refs, value_ref)))
        return replace(qro, mathematical_refs=refs)
    raise ResearchGraphError("append_ref only supports evidence_refs or mathematical_refs")


def _updated_qro(qro: QRORecord, record: CanvasMutationRecord) -> QRORecord:
    operation = str(record.operation or "")
    if operation in {"set_ref", "set_hash"}:
        changed = _with_contract_field(qro, record)
    elif operation == "append_ref":
        changed = _with_appended_ref(qro, record)
    else:
        raise ResearchGraphError("canvas asset mutation operation must be set_ref, set_hash, or append_ref")

    audit_refs = tuple(
        dict.fromkeys(
            (
                *changed.evidence_refs,
                *(str(ref) for ref in record.evidence_refs if str(ref).strip()),
                str(record.audit_ref or ""),
                str(record.canonical_command_ref or ""),
            )
        )
    )
    audit_refs = tuple(ref for ref in audit_refs if ref)
    return replace(
        changed,
        version=qro.version + 1,
        implementation_hash="canvas_asset_mutation:"
        + content_hash(
            {
                "qro_id": qro.qro_id,
                "previous_version": qro.version,
                "command_ref": record.command_ref,
                "field_path": record.field_path,
                "operation": record.operation,
                "value_ref": record.value_ref,
                "value_hash": record.value_hash,
            }
        ),
        lineage=tuple(dict.fromkeys((*qro.lineage, "canvas_asset_mutation", record.command_ref))),
        evidence_refs=audit_refs,
        qro_id=qro.qro_id,
    )


def execute_canvas_asset_mutation(
    store: ResearchGraphStore,
    record: CanvasMutationRecord,
    *,
    owner_user_id: str,
    tool_record_refs: tuple[str, ...] = (),
) -> CanvasAssetMutationResult:
    decision = validate_canvas_mutation(record)
    if not decision.accepted:
        codes = ",".join(violation.code for violation in decision.violations)
        raise ResearchGraphError(f"canvas asset mutation rejected: {codes}")
    try:
        current = store.qro(record.target_ref)
    except KeyError as exc:
        raise ResearchGraphError(f"canvas asset mutation target QRO not found: {record.target_ref}") from exc
    owner = str(owner_user_id or "").strip()
    if not owner or str(record.actor or "") != owner or str(current.owner or "") != owner:
        raise ResearchGraphError("canvas asset mutation target belongs to a different owner")
    if _qro_type(current) != str(record.target_asset_type):
        raise ResearchGraphError(
            f"canvas asset mutation target_asset_type mismatch: expected {_qro_type(current)}, got {record.target_asset_type}"
        )
    if _runtime(current) == RuntimeStatus.LIVE.value:
        raise ResearchGraphError("canvas asset mutation cannot edit live QRO; fork a draft/offline asset first")

    updated = _updated_qro(current, record)
    mutation_command = ResearchGraphCommand(
        source=EntrySource.CANVAS,
        command_type="record_canvas_mutation",
        actor_source=record.actor_source,
        actor=record.actor,
        payload={"mutation": record},
        evidence_refs=record.evidence_refs,
        tool_record_refs=tool_record_refs,
    )
    mutation_command_id = store.apply(mutation_command)
    qro_command = ResearchGraphCommand(
        source=EntrySource.CANVAS,
        command_type="upsert_qro",
        actor_source=record.actor_source,
        actor=record.actor,
        payload={"qro": updated},
        evidence_refs=updated.evidence_refs,
        tool_record_refs=(mutation_command_id, *tool_record_refs),
    )
    qro_command_id = store.apply(qro_command)
    projection = [record for record in store.projection_index() if record.qro_id == updated.qro_id][-1]
    return CanvasAssetMutationResult(
        mutation_command_id=mutation_command_id,
        qro_command_id=qro_command_id,
        qro_id=updated.qro_id,
        qro_version=updated.version,
        projection_ref=projection.projection_ref,
        updated_field_path=record.field_path,
    )


__all__ = [
    "CanvasAssetMutationResult",
    "execute_canvas_asset_mutation",
]
