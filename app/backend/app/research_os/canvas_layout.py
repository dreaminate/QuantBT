"""Persistent GraphCanvas layout records for QRO-backed nodes.

Canvas mutations update QRO contracts; this store holds the inspectable layout
payload that a QRO can reference through ``output_contract.canvas_layout_ref``.
Projection code must only replay a layout when the current QRO version binds
that ref.
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from typing import Any

from ..lineage.ids import content_hash

_MAX_CANVAS_COORDINATE = 1_000_000.0


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _as_tuple(value: Any) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, (list, tuple, set)):
        return tuple(str(v) for v in value if str(v).strip())
    return (str(value),) if str(value).strip() else ()


def _require_token(value: str, field_name: str, *, ref: bool = False) -> str:
    token = str(value or "").strip()
    if not token:
        raise ValueError(f"{field_name} is required")
    if any(ch.isspace() for ch in token):
        raise ValueError(f"{field_name} must be a compact token")
    if ref and ":" not in token:
        raise ValueError(f"{field_name} must be a reference token")
    return token


def _coordinate(value: float | int, field_name: str) -> float:
    coord = float(value)
    if not math.isfinite(coord):
        raise ValueError(f"{field_name} must be finite")
    if abs(coord) > _MAX_CANVAS_COORDINATE:
        raise ValueError(f"{field_name} is outside canvas bounds")
    return round(coord, 3)


def _layout_hash(*, qro_id: str, node_id: str, x: float, y: float, w: float) -> str:
    return "hash_canvas_layout_" + content_hash(
        {
            "node_id": node_id,
            "qro_id": qro_id,
            "w": w,
            "x": x,
            "y": y,
        }
    )[:16]


@dataclass(frozen=True)
class CanvasLayoutRecord:
    layout_ref: str
    layout_hash: str
    qro_id: str
    qro_type: str
    node_id: str
    x: float
    y: float
    w: float
    source_desk: str
    actor_source: str
    actor: str
    mutation_command_ref: str
    canonical_command_ref: str
    audit_ref: str
    evidence_refs: tuple[str, ...] = ()
    timestamp: str = ""

    def to_event_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["evidence_refs"] = list(self.evidence_refs)
        return data


def make_canvas_layout_record(
    *,
    qro_id: str,
    qro_type: str,
    node_id: str,
    x: float,
    y: float,
    w: float,
    source_desk: str,
    actor_source: str,
    actor: str,
    mutation_command_ref: str,
    canonical_command_ref: str,
    audit_ref: str,
    evidence_refs: tuple[str, ...] = (),
    timestamp: str | None = None,
) -> CanvasLayoutRecord:
    clean_qro_id = _require_token(qro_id, "qro_id")
    clean_node_id = _require_token(node_id, "node_id", ref=True)
    clean_x = _coordinate(x, "x")
    clean_y = _coordinate(y, "y")
    clean_w = _coordinate(w, "w")
    layout_hash = _layout_hash(qro_id=clean_qro_id, node_id=clean_node_id, x=clean_x, y=clean_y, w=clean_w)
    return CanvasLayoutRecord(
        layout_ref=f"canvas_layout:{clean_qro_id}:{layout_hash}",
        layout_hash=layout_hash,
        qro_id=clean_qro_id,
        qro_type=_require_token(qro_type, "qro_type"),
        node_id=clean_node_id,
        x=clean_x,
        y=clean_y,
        w=clean_w,
        source_desk=_require_token(source_desk, "source_desk"),
        actor_source=_require_token(actor_source, "actor_source"),
        actor=_require_token(actor, "actor"),
        mutation_command_ref=_require_token(mutation_command_ref, "mutation_command_ref", ref=True),
        canonical_command_ref=_require_token(canonical_command_ref, "canonical_command_ref", ref=True),
        audit_ref=_require_token(audit_ref, "audit_ref", ref=True),
        evidence_refs=_as_tuple(evidence_refs),
        timestamp=timestamp or _now(),
    )


def validate_canvas_layout_record(record: CanvasLayoutRecord) -> None:
    expected_node_id = f"canvas_node:qro:{_require_token(record.qro_id, 'qro_id')}"
    if record.node_id != expected_node_id:
        raise ValueError("canvas layout node_id must target the QRO node")
    x = _coordinate(record.x, "x")
    y = _coordinate(record.y, "y")
    w = _coordinate(record.w, "w")
    expected_hash = _layout_hash(qro_id=record.qro_id, node_id=record.node_id, x=x, y=y, w=w)
    if record.layout_hash != expected_hash:
        raise ValueError("canvas layout hash mismatch")
    if record.layout_ref != f"canvas_layout:{record.qro_id}:{expected_hash}":
        raise ValueError("canvas layout ref mismatch")
    _require_token(record.qro_type, "qro_type")
    _require_token(record.source_desk, "source_desk")
    _require_token(record.actor_source, "actor_source")
    _require_token(record.actor, "actor")
    _require_token(record.mutation_command_ref, "mutation_command_ref", ref=True)
    _require_token(record.canonical_command_ref, "canonical_command_ref", ref=True)
    _require_token(record.audit_ref, "audit_ref", ref=True)
    _require_token(record.timestamp, "timestamp")


__all__ = [
    "CanvasLayoutRecord",
    "make_canvas_layout_record",
    "validate_canvas_layout_record",
]
