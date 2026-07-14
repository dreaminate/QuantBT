"""Durable, owner-scoped current closure proof for GOAL section 14.

The M1-M21 platform registry remains the canonical producer.  A closure
receipt is created only from a freshly resolved, strictly real-backed complete
manifest.  The receipt stores every canonical row payload plus one exact
``row -> source coverage revision -> cited RDP revision`` binding.  Its top
level RDP tuple is only the derived union of those bindings; unrelated owner
packages never enter currentness.

``PersistentPlatformCoverageRegistry`` does not expose an atomic refresh/read
operation.  Therefore this module deliberately requires a narrow
``resolve_current_manifest(owner)`` callback plus narrow coverage and
package-by-id readers.  Integrators must implement those callbacks as
read-only resolvers.  Every composed writer shares the entrypoint coverage
proof-head lock.  The closure registry takes that lock first, resolves all
three views twice, then takes platform, RDP, and closure journal locks in that
deterministic order.  It compares the stable candidate with the latest
platform event and only its linked RDP events, keeps every lock through commit,
and performs one final same-generation assertion before returning.  Any stale,
foreign, missing, or recombined backing fails closed.
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
import threading
from contextlib import contextmanager
from dataclasses import asdict, dataclass, is_dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Iterator

from ..cross_process_lock import acquire_exclusive_fd
from .goal_semantics import (
    GoalSectionSemanticProofRecord,
    GoalSemanticDecision,
    GoalSemanticViolation,
)
from .goal_coverage import (
    GoalEntrypointCoverageRecord,
    validate_goal_entrypoint_coverage,
)
from .goal_proof_head_lock import acquire_goal_proof_head_lock
from .platform_coverage import (
    REQUIRED_PLATFORM_ROWS,
    PersistentPlatformCoverageRegistry,
    PlatformCapabilityRecord,
    PlatformCoverageDecision,
    platform_capability_record_from_dict,
    platform_capability_record_to_dict,
    validate_platform_coverage,
)
from .platform_row_producers import ResolvedPlatformRow
from .ref_resolution import is_placeholder_ref
from .rdp import (
    parse_quarantined_rdp_manifest_event_v1,
    parse_rdp_manifest_event_v2,
)


PLATFORM_CLOSURE_SCHEMA_VERSION = 5
PLATFORM_CLOSURE_RECEIPT_VERSION = "platform_closure_receipt.v4"
_LEGACY_PLATFORM_CLOSURE_SCHEMA_VERSION = 4
_LEGACY_PLATFORM_CLOSURE_RECEIPT_VERSION = "platform_closure_receipt.v3"
PLATFORM_CLOSURE_ENTRYPOINT_REF = "api:goal.platform_closure.current"
PLATFORM_CLOSURE_GOAL_SECTIONS = ("§14",)

_PLATFORM_RECORD_FIELDS = frozenset(
    {
        "m_row",
        "qro_ref",
        "research_graph_ref",
        "lifecycle_ref",
        "governance_ref",
        "rag_ref",
        "math_spine_ref",
        "evidence_refs",
        "specific_refs",
    }
)


def _text(value: Any) -> str:
    return str(value or "").strip()


def _canonical_or_legacy_coverage(view: Any, ref: str, *, owner: str) -> Any:
    """Read a canonical head when configured; legacy is fixture compatibility."""

    canonical = getattr(view, "canonical_coverage", None)
    if (
        getattr(view, "canonical_projection_available", None) is not False
        and callable(canonical)
    ):
        return canonical(ref, owner=owner)
    return getattr(view, "coverage")(ref, owner=owner)


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _jsonable(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, Enum):
        return _jsonable(value.value)
    if is_dataclass(value):
        return _jsonable(asdict(value))
    if isinstance(value, dict):
        return {str(key): _jsonable(child) for key, child in value.items()}
    if isinstance(value, (tuple, list)):
        return [_jsonable(child) for child in value]
    raise TypeError(f"platform closure value is not JSON-safe: {type(value).__name__}")


def _sha256(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _content_hash(value: Any) -> str:
    return "sha256:" + _sha256(value)


def _valid_content_hash(value: Any) -> bool:
    token = _text(value).lower()
    return (
        token.startswith("sha256:")
        and len(token) == 71
        and all(char in "0123456789abcdef" for char in token[7:])
    )


def _valid_production_ref(value: Any) -> bool:
    token = _text(value).lower()
    prefix = "platform_row_production:"
    digest = token.removeprefix(prefix)
    return (
        token.startswith(prefix)
        and len(digest) == 64
        and all(char in "0123456789abcdef" for char in digest)
    )


def _row_value(record: PlatformCapabilityRecord) -> str:
    value = getattr(record.m_row, "value", record.m_row)
    return _text(value)


def _owner(value: Any) -> str:
    owner = _text(value)
    if not owner or owner != value or any(ord(char) < 32 for char in owner):
        raise ValueError("owner_user_id must be a stable non-empty exact string")
    if is_placeholder_ref(owner):
        raise ValueError("owner_user_id cannot contain placeholder material")
    return owner


def _exact_record(value: Any) -> PlatformCapabilityRecord:
    if not isinstance(value, dict) or set(value) != _PLATFORM_RECORD_FIELDS:
        raise ValueError("platform closure row record has an inexact field set")
    raw_specific = value.get("specific_refs")
    if not isinstance(raw_specific, list) or any(
        not isinstance(item, dict) or set(item) != {"key", "ref"}
        for item in raw_specific
    ):
        raise ValueError("platform closure specific_refs have an inexact field set")
    if not isinstance(value.get("evidence_refs"), list):
        raise ValueError("platform closure evidence_refs must be a list")
    return platform_capability_record_from_dict(value)


def _record_payload(record: PlatformCapabilityRecord) -> dict[str, Any]:
    return platform_capability_record_to_dict(record)


def _reject_placeholder_record(record: PlatformCapabilityRecord) -> None:
    payload = _record_payload(record)

    def visit(value: Any, path: str) -> None:
        if isinstance(value, dict):
            for key, child in value.items():
                if key == "m_row":
                    continue
                visit(child, f"{path}.{key}")
        elif isinstance(value, list):
            for index, child in enumerate(value):
                visit(child, f"{path}[{index}]")
        elif isinstance(value, str) and is_placeholder_ref(value):
            raise ValueError(f"{path} contains placeholder material")

    visit(payload, "platform_record")


@dataclass(frozen=True)
class PlatformClosureViolation:
    code: str
    message: str
    field: str = ""
    ref: str = ""


@dataclass(frozen=True)
class PlatformClosureDecision:
    accepted: bool
    violations: tuple[PlatformClosureViolation, ...]


class PlatformClosureError(ValueError):
    """A complete current owner-scoped platform manifest could not be proved."""


class PlatformClosureCommitUncertain(PlatformClosureError):
    """The closure file was replaced but durable rollback could not be proved."""


@dataclass(frozen=True)
class PlatformClosureRowState:
    m_row: str
    record: PlatformCapabilityRecord
    record_hash: str
    production_ref: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "m_row", _text(self.m_row))
        object.__setattr__(self, "record_hash", _text(self.record_hash))
        object.__setattr__(self, "production_ref", _text(self.production_ref))


@dataclass(frozen=True)
class PlatformClosureRDPState:
    package_id: str
    manifest_hash: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "package_id", _text(self.package_id))
        object.__setattr__(self, "manifest_hash", _text(self.manifest_hash))


@dataclass(frozen=True)
class PlatformClosureSourceBinding:
    """One row's exact source coverage revision and cited RDP revisions."""

    m_row: str
    source_coverage_ref: str
    source_coverage_hash: str
    rdps: tuple[PlatformClosureRDPState, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "m_row", _text(self.m_row))
        object.__setattr__(
            self,
            "source_coverage_ref",
            _text(self.source_coverage_ref),
        )
        object.__setattr__(
            self,
            "source_coverage_hash",
            _text(self.source_coverage_hash),
        )
        object.__setattr__(self, "rdps", tuple(self.rdps))


@dataclass(frozen=True)
class PlatformClosureSnapshot:
    owner_user_id: str
    required_rows: tuple[str, ...]
    rows: tuple[PlatformClosureRowState, ...]
    source_bindings: tuple[PlatformClosureSourceBinding, ...]
    rdps: tuple[PlatformClosureRDPState, ...]
    strict_manifest_accepted: bool
    strict_manifest_verdict_hash: str
    source_manifest_event_hash: str
    manifest_hash: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "owner_user_id", _text(self.owner_user_id))
        object.__setattr__(self, "required_rows", tuple(_text(row) for row in self.required_rows))
        object.__setattr__(self, "rows", tuple(self.rows))
        object.__setattr__(self, "source_bindings", tuple(self.source_bindings))
        object.__setattr__(self, "rdps", tuple(self.rdps))
        object.__setattr__(
            self,
            "strict_manifest_verdict_hash",
            _text(self.strict_manifest_verdict_hash),
        )
        object.__setattr__(
            self,
            "source_manifest_event_hash",
            _text(self.source_manifest_event_hash),
        )
        object.__setattr__(self, "manifest_hash", _text(self.manifest_hash))


@dataclass(frozen=True)
class PlatformClosureReceipt:
    receipt_ref: str
    owner_user_id: str
    owner_revision: int
    previous_receipt_ref: str
    snapshot: PlatformClosureSnapshot
    receipt_version: str = PLATFORM_CLOSURE_RECEIPT_VERSION

    def __post_init__(self) -> None:
        for field_name in (
            "receipt_ref",
            "owner_user_id",
            "previous_receipt_ref",
            "receipt_version",
        ):
            object.__setattr__(self, field_name, _text(getattr(self, field_name)))

    @property
    def canonical_receipt_ref(self) -> str:
        return platform_closure_receipt_identity(
            owner_user_id=self.owner_user_id,
            owner_revision=self.owner_revision,
            previous_receipt_ref=self.previous_receipt_ref,
            snapshot=self.snapshot,
            receipt_version=self.receipt_version,
        )


@dataclass(frozen=True)
class PlatformClosureSemanticMaterial:
    subject_ref: str
    producer_refs: tuple[str, ...]
    store_refs: tuple[str, ...]
    consumer_refs: tuple[str, ...]
    gate_verdict_refs: tuple[str, ...]
    test_refs: tuple[str, ...]


PlatformManifestResolver = Callable[[str], tuple[ResolvedPlatformRow, ...]]
PlatformLockedManifestResolver = Callable[
    [str, tuple[PlatformCapabilityRecord, ...]],
    tuple[ResolvedPlatformRow, ...],
]
PlatformCoverageResolver = Callable[[str, str], GoalEntrypointCoverageRecord]
PlatformRDPResolver = Callable[[str, str], PlatformClosureRDPState]


@dataclass(frozen=True)
class _PlatformClosureCandidate:
    resolved_rows: tuple[ResolvedPlatformRow, ...]
    registered_records: tuple[PlatformCapabilityRecord, ...]
    source_bindings: tuple[PlatformClosureSourceBinding, ...]
    strict_decision: PlatformCoverageDecision

    @property
    def rdps(self) -> tuple[PlatformClosureRDPState, ...]:
        return _derived_rdp_union(self.source_bindings)


@dataclass(frozen=True)
class _PlatformClosureChainHead:
    receipt_ref: str
    owner_revision: int
    legacy: bool


def _row_to_dict(row: PlatformClosureRowState) -> dict[str, Any]:
    return {
        "m_row": row.m_row,
        "record": _record_payload(row.record),
        "record_hash": row.record_hash,
        "production_ref": row.production_ref,
    }


def _row_from_dict(value: Any) -> PlatformClosureRowState:
    if not isinstance(value, dict) or set(value) != {
        "m_row",
        "record",
        "record_hash",
        "production_ref",
    }:
        raise ValueError("platform closure row state has an inexact field set")
    return PlatformClosureRowState(
        m_row=value["m_row"],
        record=_exact_record(value["record"]),
        record_hash=value["record_hash"],
        production_ref=value["production_ref"],
    )


def _rdp_to_dict(rdp: PlatformClosureRDPState) -> dict[str, str]:
    return {
        "package_id": rdp.package_id,
        "manifest_hash": rdp.manifest_hash,
    }


def _rdp_from_dict(value: Any) -> PlatformClosureRDPState:
    if not isinstance(value, dict) or set(value) != {"package_id", "manifest_hash"}:
        raise ValueError("platform closure RDP state has an inexact field set")
    return PlatformClosureRDPState(
        package_id=value["package_id"],
        manifest_hash=value["manifest_hash"],
    )


def _binding_to_dict(binding: PlatformClosureSourceBinding) -> dict[str, Any]:
    return {
        "m_row": binding.m_row,
        "source_coverage_ref": binding.source_coverage_ref,
        "source_coverage_hash": binding.source_coverage_hash,
        "rdps": [_rdp_to_dict(rdp) for rdp in binding.rdps],
    }


def _binding_from_dict(value: Any) -> PlatformClosureSourceBinding:
    if not isinstance(value, dict) or set(value) != {
        "m_row",
        "source_coverage_ref",
        "source_coverage_hash",
        "rdps",
    }:
        raise ValueError("platform closure source binding has an inexact field set")
    if not isinstance(value["rdps"], list):
        raise ValueError("platform closure source binding RDPs must be a list")
    return PlatformClosureSourceBinding(
        m_row=value["m_row"],
        source_coverage_ref=value["source_coverage_ref"],
        source_coverage_hash=value["source_coverage_hash"],
        rdps=tuple(_rdp_from_dict(rdp) for rdp in value["rdps"]),
    )


def _derived_rdp_union(
    bindings: tuple[PlatformClosureSourceBinding, ...],
) -> tuple[PlatformClosureRDPState, ...]:
    by_package: dict[str, PlatformClosureRDPState] = {}
    for binding in bindings:
        for state in binding.rdps:
            existing = by_package.get(state.package_id)
            if existing is not None and existing != state:
                raise ValueError(
                    "platform closure source bindings disagree on one RDP revision"
                )
            by_package[state.package_id] = state
    return tuple(sorted(by_package.values(), key=lambda item: item.package_id))


def platform_closure_rdp_state(
    *,
    package_id: str,
    manifest_payload: dict[str, Any],
) -> PlatformClosureRDPState:
    package = _text(package_id)
    if not package or is_placeholder_ref(package):
        raise ValueError("platform closure RDP package_id is invalid")
    if not isinstance(manifest_payload, dict) or _text(manifest_payload.get("package_id")) != package:
        raise ValueError("platform closure RDP payload does not bind package_id")
    return PlatformClosureRDPState(
        package_id=package,
        manifest_hash=_content_hash(manifest_payload),
    )


def _snapshot_to_dict(snapshot: PlatformClosureSnapshot) -> dict[str, Any]:
    return {
        "owner_user_id": snapshot.owner_user_id,
        "required_rows": list(snapshot.required_rows),
        "rows": [_row_to_dict(row) for row in snapshot.rows],
        "source_bindings": [
            _binding_to_dict(binding) for binding in snapshot.source_bindings
        ],
        "rdps": [_rdp_to_dict(rdp) for rdp in snapshot.rdps],
        "strict_manifest_accepted": snapshot.strict_manifest_accepted,
        "strict_manifest_verdict_hash": snapshot.strict_manifest_verdict_hash,
        "source_manifest_event_hash": snapshot.source_manifest_event_hash,
        "manifest_hash": snapshot.manifest_hash,
    }


def platform_closure_snapshot_from_dict(value: Any) -> PlatformClosureSnapshot:
    expected = {
        "owner_user_id",
        "required_rows",
        "rows",
        "source_bindings",
        "rdps",
        "strict_manifest_accepted",
        "strict_manifest_verdict_hash",
        "source_manifest_event_hash",
        "manifest_hash",
    }
    if not isinstance(value, dict) or set(value) != expected:
        raise ValueError("platform closure snapshot has an inexact field set")
    if (
        not isinstance(value["required_rows"], list)
        or not isinstance(value["rows"], list)
        or not isinstance(value["source_bindings"], list)
        or not isinstance(value["rdps"], list)
    ):
        raise ValueError("platform closure snapshot row fields must be lists")
    return PlatformClosureSnapshot(
        owner_user_id=value["owner_user_id"],
        required_rows=tuple(value["required_rows"]),
        rows=tuple(_row_from_dict(row) for row in value["rows"]),
        source_bindings=tuple(
            _binding_from_dict(binding) for binding in value["source_bindings"]
        ),
        rdps=tuple(_rdp_from_dict(rdp) for rdp in value["rdps"]),
        strict_manifest_accepted=value["strict_manifest_accepted"],
        strict_manifest_verdict_hash=value["strict_manifest_verdict_hash"],
        source_manifest_event_hash=value["source_manifest_event_hash"],
        manifest_hash=value["manifest_hash"],
    )


def _receipt_to_dict(receipt: PlatformClosureReceipt) -> dict[str, Any]:
    return {
        "receipt_ref": receipt.receipt_ref,
        "owner_user_id": receipt.owner_user_id,
        "owner_revision": receipt.owner_revision,
        "previous_receipt_ref": receipt.previous_receipt_ref,
        "snapshot": _snapshot_to_dict(receipt.snapshot),
        "receipt_version": receipt.receipt_version,
    }


def platform_closure_receipt_from_dict(value: Any) -> PlatformClosureReceipt:
    expected = {
        "receipt_ref",
        "owner_user_id",
        "owner_revision",
        "previous_receipt_ref",
        "snapshot",
        "receipt_version",
    }
    if not isinstance(value, dict) or set(value) != expected:
        raise ValueError("platform closure receipt has an inexact field set")
    return PlatformClosureReceipt(
        receipt_ref=value["receipt_ref"],
        owner_user_id=value["owner_user_id"],
        owner_revision=value["owner_revision"],
        previous_receipt_ref=value["previous_receipt_ref"],
        snapshot=platform_closure_snapshot_from_dict(value["snapshot"]),
        receipt_version=value["receipt_version"],
    )


def platform_closure_receipt_identity(
    *,
    owner_user_id: str,
    owner_revision: int,
    previous_receipt_ref: str,
    snapshot: PlatformClosureSnapshot,
    receipt_version: str = PLATFORM_CLOSURE_RECEIPT_VERSION,
) -> str:
    return "platform_closure_receipt:" + _sha256(
        {
            "owner_user_id": _text(owner_user_id),
            "owner_revision": owner_revision,
            "previous_receipt_ref": _text(previous_receipt_ref),
            "snapshot": _snapshot_to_dict(snapshot),
            "receipt_version": _text(receipt_version),
        }
    )


def _verdict_hash(decision: PlatformCoverageDecision) -> str:
    return _content_hash(
        {
            "accepted": decision.accepted,
            "violations": [asdict(violation) for violation in decision.violations],
        }
    )


def _snapshot_manifest_hash(
    *,
    owner_user_id: str,
    rows: tuple[PlatformClosureRowState, ...],
    source_bindings: tuple[PlatformClosureSourceBinding, ...],
    rdps: tuple[PlatformClosureRDPState, ...],
    strict_manifest_accepted: bool,
    strict_manifest_verdict_hash: str,
    source_manifest_event_hash: str,
) -> str:
    return _content_hash(
        {
            "owner_user_id": owner_user_id,
            "required_rows": list(REQUIRED_PLATFORM_ROWS),
            "rows": [_row_to_dict(row) for row in rows],
            "source_bindings": [
                _binding_to_dict(binding) for binding in source_bindings
            ],
            "rdps": [_rdp_to_dict(rdp) for rdp in rdps],
            "strict_manifest_accepted": strict_manifest_accepted,
            "strict_manifest_verdict_hash": strict_manifest_verdict_hash,
            "source_manifest_event_hash": source_manifest_event_hash,
        }
    )


def _build_snapshot(
    *,
    owner_user_id: str,
    resolved_rows: tuple[ResolvedPlatformRow, ...],
    source_bindings: tuple[PlatformClosureSourceBinding, ...],
    decision: PlatformCoverageDecision,
    source_manifest_event_hash: str,
) -> PlatformClosureSnapshot:
    owner = _owner(owner_user_id)
    if not decision.accepted or decision.violations:
        codes = ",".join(item.code for item in decision.violations)
        raise PlatformClosureError(f"strict platform manifest rejected: {codes}")
    by_row = {item.m_row: item for item in resolved_rows}
    if len(by_row) != len(resolved_rows) or set(by_row) != set(REQUIRED_PLATFORM_ROWS):
        raise PlatformClosureError("strict platform manifest does not exactly cover required rows")
    canonical = tuple(by_row[row] for row in REQUIRED_PLATFORM_ROWS)
    rows: list[PlatformClosureRowState] = []
    for expected_row, resolved in zip(REQUIRED_PLATFORM_ROWS, canonical, strict=True):
        if resolved.owner_user_id != owner or resolved.m_row != expected_row:
            raise PlatformClosureError("platform producer owner or row identity mismatch")
        if resolved.production_ref != resolved.canonical_production_ref:
            raise PlatformClosureError("platform producer state identity mismatch")
        record = resolved.record
        _reject_placeholder_record(record)
        payload = _record_payload(record)
        rows.append(
            PlatformClosureRowState(
                m_row=expected_row,
                record=record,
                record_hash=_content_hash(payload),
                production_ref=resolved.production_ref,
            )
        )
    row_tuple = tuple(rows)
    if tuple(binding.m_row for binding in source_bindings) != tuple(
        REQUIRED_PLATFORM_ROWS
    ):
        raise PlatformClosureError(
            "platform closure source bindings are not in exact canonical row order"
        )
    try:
        rdp_tuple = _derived_rdp_union(source_bindings)
    except ValueError as exc:
        raise PlatformClosureError(str(exc)) from exc
    if not rdp_tuple:
        raise PlatformClosureError(
            "platform closure requires at least one coverage-linked RDP manifest"
        )
    if (
        any(
            not rdp.package_id
            or is_placeholder_ref(rdp.package_id)
            or not _valid_content_hash(rdp.manifest_hash)
            for rdp in rdp_tuple
        )
        or len({rdp.package_id for rdp in rdp_tuple}) != len(rdp_tuple)
    ):
        raise PlatformClosureError("platform closure RDP snapshot is invalid")
    verdict_hash = _verdict_hash(decision)
    source_event_hash = _text(source_manifest_event_hash)
    if not _valid_content_hash(source_event_hash):
        raise PlatformClosureError("source platform manifest event hash is invalid")
    return PlatformClosureSnapshot(
        owner_user_id=owner,
        required_rows=tuple(REQUIRED_PLATFORM_ROWS),
        rows=row_tuple,
        source_bindings=source_bindings,
        rdps=rdp_tuple,
        strict_manifest_accepted=True,
        strict_manifest_verdict_hash=verdict_hash,
        source_manifest_event_hash=source_event_hash,
        manifest_hash=_snapshot_manifest_hash(
            owner_user_id=owner,
            rows=row_tuple,
            source_bindings=source_bindings,
            rdps=rdp_tuple,
            strict_manifest_accepted=True,
            strict_manifest_verdict_hash=verdict_hash,
            source_manifest_event_hash=source_event_hash,
        ),
    )


def _reject(
    violations: list[PlatformClosureViolation],
    code: str,
    message: str,
    *,
    field: str = "",
    ref: str = "",
) -> None:
    violations.append(PlatformClosureViolation(code, message, field=field, ref=ref))


def validate_platform_closure_snapshot(
    snapshot: PlatformClosureSnapshot,
    *,
    owner_user_id: str,
) -> PlatformClosureDecision:
    violations: list[PlatformClosureViolation] = []
    try:
        owner = _owner(owner_user_id)
        snapshot_owner = _owner(snapshot.owner_user_id)
    except ValueError as exc:
        _reject(violations, "platform_closure_owner_invalid", str(exc), field="owner_user_id")
        return PlatformClosureDecision(False, tuple(violations))
    if snapshot_owner != owner:
        _reject(
            violations,
            "platform_closure_owner_mismatch",
            "platform closure snapshot owner does not match its envelope",
            field="owner_user_id",
            ref=snapshot.owner_user_id,
        )
    if snapshot.required_rows != tuple(REQUIRED_PLATFORM_ROWS):
        _reject(
            violations,
            "platform_closure_required_rows_mismatch",
            "platform closure must bind the exact canonical REQUIRED_PLATFORM_ROWS",
            field="required_rows",
        )
    row_names = tuple(row.m_row for row in snapshot.rows)
    if row_names != tuple(REQUIRED_PLATFORM_ROWS) or len(row_names) != len(set(row_names)):
        _reject(
            violations,
            "platform_closure_rows_inexact",
            "platform closure rows must be unique and in canonical complete order",
            field="rows",
        )
    records: list[PlatformCapabilityRecord] = []
    for row in snapshot.rows:
        records.append(row.record)
        if row.m_row != _row_value(row.record):
            _reject(
                violations,
                "platform_closure_row_identity_mismatch",
                "closure row label does not match its platform record",
                field="m_row",
                ref=row.m_row,
            )
        expected_hash = _content_hash(_record_payload(row.record))
        if row.record_hash != expected_hash:
            _reject(
                violations,
                "platform_closure_row_hash_mismatch",
                "platform row hash does not bind its exact payload",
                field="record_hash",
                ref=row.m_row,
            )
        if not _valid_production_ref(row.production_ref):
            _reject(
                violations,
                "platform_closure_production_ref_invalid",
                "closure row must bind a canonical current producer state",
                field="production_ref",
                ref=row.m_row,
            )
        try:
            _reject_placeholder_record(row.record)
        except ValueError as exc:
            _reject(
                violations,
                "platform_closure_placeholder_ref",
                str(exc),
                field="record",
                ref=row.m_row,
            )
    binding_rows = tuple(binding.m_row for binding in snapshot.source_bindings)
    if binding_rows != tuple(REQUIRED_PLATFORM_ROWS) or len(binding_rows) != len(
        set(binding_rows)
    ):
        _reject(
            violations,
            "platform_closure_source_bindings_inexact",
            "platform closure requires one source binding in canonical order per row",
            field="source_bindings",
        )
    coverage_refs = tuple(
        binding.source_coverage_ref for binding in snapshot.source_bindings
    )
    if len(coverage_refs) != len(set(coverage_refs)):
        _reject(
            violations,
            "platform_closure_source_coverage_recombined",
            "platform closure source coverage revisions must be unique per row",
            field="source_bindings",
        )
    rows_by_name = {row.m_row: row for row in snapshot.rows}
    for binding in snapshot.source_bindings:
        if (
            not binding.source_coverage_ref.startswith("goal_entrypoint_coverage:")
            or is_placeholder_ref(binding.source_coverage_ref)
            or not _valid_content_hash(binding.source_coverage_hash)
        ):
            _reject(
                violations,
                "platform_closure_source_coverage_invalid",
                "source binding must identify one exact content-hashed coverage revision",
                field="source_bindings",
                ref=binding.m_row,
            )
        binding_rdp_ids = tuple(rdp.package_id for rdp in binding.rdps)
        if binding_rdp_ids != tuple(sorted(binding_rdp_ids)) or len(
            binding_rdp_ids
        ) != len(set(binding_rdp_ids)):
            _reject(
                violations,
                "platform_closure_binding_rdp_set_invalid",
                "source binding RDPs must be unique and canonically ordered",
                field="source_bindings",
                ref=binding.m_row,
            )
        for rdp in binding.rdps:
            if (
                not rdp.package_id
                or is_placeholder_ref(rdp.package_id)
                or not _valid_content_hash(rdp.manifest_hash)
            ):
                _reject(
                    violations,
                    "platform_closure_binding_rdp_invalid",
                    "source binding RDP identity/hash is invalid",
                    field="source_bindings",
                    ref=binding.m_row,
                )
        if binding.m_row == "M18":
            row = rows_by_name.get("M18")
            expected_package = _text(
                getattr(getattr(row, "record", None), "lifecycle_ref", "")
            )
            if binding_rdp_ids != (expected_package,):
                _reject(
                    violations,
                    "platform_closure_m18_rdp_mismatch",
                    "M18 must bind exactly its selected RDP package revision",
                    field="source_bindings",
                    ref=binding.source_coverage_ref,
                )
    if not snapshot.rdps:
        _reject(
            violations,
            "platform_closure_rdp_missing",
            "platform closure must bind at least one coverage-linked RDP manifest",
            field="rdps",
        )
    rdp_ids = tuple(rdp.package_id for rdp in snapshot.rdps)
    if rdp_ids != tuple(sorted(rdp_ids)) or len(rdp_ids) != len(set(rdp_ids)):
        _reject(
            violations,
            "platform_closure_rdp_set_invalid",
            "platform closure RDPs must be unique and canonically ordered",
            field="rdps",
        )
    for rdp in snapshot.rdps:
        if (
            not rdp.package_id
            or is_placeholder_ref(rdp.package_id)
            or not _valid_content_hash(rdp.manifest_hash)
        ):
            _reject(
                violations,
                "platform_closure_rdp_invalid",
                "platform closure RDP identity/hash is invalid",
                field="rdps",
                ref=rdp.package_id,
            )
    try:
        derived_rdps = _derived_rdp_union(snapshot.source_bindings)
    except ValueError as exc:
        derived_rdps = ()
        _reject(
            violations,
            "platform_closure_binding_rdp_hash_conflict",
            str(exc),
            field="source_bindings",
        )
    if snapshot.rdps != derived_rdps:
        _reject(
            violations,
            "platform_closure_rdp_union_mismatch",
            "snapshot RDPs must be the exact derived union of row source bindings",
            field="rdps",
        )
    presence = validate_platform_coverage(tuple(records))
    if not presence.accepted:
        for violation in presence.violations:
            _reject(
                violations,
                "platform_closure_manifest_shape_invalid",
                violation.message,
                field=violation.field,
                ref=violation.ref,
            )
    canonical_verdict_hash = _content_hash({"accepted": True, "violations": []})
    if snapshot.strict_manifest_accepted is not True:
        _reject(
            violations,
            "platform_closure_strict_verdict_not_accepted",
            "closure cannot persist a non-accepted strict manifest verdict",
            field="strict_manifest_accepted",
        )
    if snapshot.strict_manifest_verdict_hash != canonical_verdict_hash:
        _reject(
            violations,
            "platform_closure_verdict_hash_mismatch",
            "strict manifest verdict hash must bind accepted=true and zero violations",
            field="strict_manifest_verdict_hash",
        )
    if not _valid_content_hash(snapshot.source_manifest_event_hash):
        _reject(
            violations,
            "platform_closure_source_event_hash_invalid",
            "closure must bind the disk-current platform manifest event",
            field="source_manifest_event_hash",
        )
    expected_manifest_hash = _snapshot_manifest_hash(
        owner_user_id=snapshot.owner_user_id,
        rows=snapshot.rows,
        source_bindings=snapshot.source_bindings,
        rdps=snapshot.rdps,
        strict_manifest_accepted=snapshot.strict_manifest_accepted,
        strict_manifest_verdict_hash=snapshot.strict_manifest_verdict_hash,
        source_manifest_event_hash=snapshot.source_manifest_event_hash,
    )
    if snapshot.manifest_hash != expected_manifest_hash:
        _reject(
            violations,
            "platform_closure_manifest_hash_mismatch",
            "manifest_hash must bind owner, exact rows, row hashes, and strict verdict",
            field="manifest_hash",
            ref=snapshot.manifest_hash,
        )
    return PlatformClosureDecision(not violations, tuple(violations))


def validate_platform_closure_receipt_shape(
    receipt: PlatformClosureReceipt,
) -> PlatformClosureDecision:
    violations: list[PlatformClosureViolation] = []
    if receipt.receipt_version != PLATFORM_CLOSURE_RECEIPT_VERSION:
        _reject(
            violations,
            "platform_closure_receipt_version_unsupported",
            "platform closure receipt version is unsupported",
            field="receipt_version",
        )
    if type(receipt.owner_revision) is not int or receipt.owner_revision <= 0:
        _reject(
            violations,
            "platform_closure_owner_revision_invalid",
            "owner_revision must be a positive integer",
            field="owner_revision",
        )
    if (receipt.owner_revision == 1) != (not receipt.previous_receipt_ref):
        _reject(
            violations,
            "platform_closure_previous_receipt_invalid",
            "only owner revision one may omit previous_receipt_ref",
            field="previous_receipt_ref",
        )
    if receipt.owner_revision > 1 and not receipt.previous_receipt_ref.startswith(
        "platform_closure_receipt:"
    ):
        _reject(
            violations,
            "platform_closure_previous_receipt_invalid",
            "later owner revisions must bind the prior closure receipt",
            field="previous_receipt_ref",
            ref=receipt.previous_receipt_ref,
        )
    snapshot_decision = validate_platform_closure_snapshot(
        receipt.snapshot,
        owner_user_id=receipt.owner_user_id,
    )
    violations.extend(snapshot_decision.violations)
    if receipt.receipt_ref != receipt.canonical_receipt_ref:
        _reject(
            violations,
            "platform_closure_receipt_identity_mismatch",
            "receipt_ref must content-bind the owner, revision, and complete manifest snapshot",
            field="receipt_ref",
            ref=receipt.receipt_ref,
        )
    return PlatformClosureDecision(not violations, tuple(violations))


class PersistentPlatformClosureRegistry:
    """Schema-v5 exact-lineage ledger for current platform closures."""

    def __init__(
        self,
        path: str | Path,
        platform_registry: PersistentPlatformCoverageRegistry,
        *,
        resolve_current_manifest: PlatformManifestResolver,
        resolve_current_manifest_unlocked: PlatformLockedManifestResolver,
        resolve_current_coverage: PlatformCoverageResolver,
        entrypoint_ledger_path: str | Path,
        rdp_path: str | Path,
        resolve_linked_rdp: PlatformRDPResolver,
    ) -> None:
        if not callable(resolve_current_manifest):
            raise TypeError("resolve_current_manifest must be callable")
        if not callable(resolve_current_manifest_unlocked):
            raise TypeError("resolve_current_manifest_unlocked must be callable")
        if not callable(resolve_current_coverage):
            raise TypeError("resolve_current_coverage must be callable")
        if not callable(resolve_linked_rdp):
            raise TypeError("resolve_linked_rdp must be callable")
        self._path = Path(path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._lock_path = self._path.with_name(f".{self._path.name}.lock")
        self._platform_registry = platform_registry
        platform_path = getattr(platform_registry, "path", None)
        if platform_path is None:
            raise TypeError("platform_registry must expose its public journal path")
        self._platform_path = Path(platform_path)
        self._platform_lock_path = self._platform_path.with_suffix(
            self._platform_path.suffix + ".lock"
        )
        self._rdp_path = Path(rdp_path)
        self._rdp_lock_path = self._rdp_path.with_name(f".{self._rdp_path.name}.lock")
        self._resolve_current_manifest = resolve_current_manifest
        self._resolve_current_manifest_unlocked = resolve_current_manifest_unlocked
        self._resolve_current_coverage = resolve_current_coverage
        self._resolve_linked_rdp = resolve_linked_rdp
        self._entrypoint_ledger_path = (
            Path(entrypoint_ledger_path).expanduser().absolute()
        )
        platform_proof_head = getattr(
            platform_registry,
            "proof_head_ledger_path",
            None,
        )
        if (
            platform_proof_head is not None
            and Path(platform_proof_head).expanduser().absolute()
            != self._entrypoint_ledger_path
        ):
            raise ValueError(
                "platform registry and closure must share the exact GOAL proof-head ledger"
            )
        self._thread_lock = threading.RLock()
        self._records: dict[tuple[str, str], PlatformClosureReceipt] = {}
        self._heads: dict[str, PlatformClosureReceipt] = {}
        self._chain_heads: dict[str, _PlatformClosureChainHead] = {}
        self._last_ledger_revision = 0
        self._last_record_hash = ""
        self._legacy_quarantined_count = 0
        self._load_existing()

    @property
    def path(self) -> Path:
        return self._path

    @property
    def rdp_path(self) -> Path:
        return self._rdp_path

    @property
    def entrypoint_ledger_path(self) -> Path:
        return self._entrypoint_ledger_path

    @property
    def legacy_quarantined_count(self) -> int:
        with self._thread_lock, self._exclusive_lock():
            self._load_existing_unlocked()
            return self._legacy_quarantined_count

    @contextmanager
    def _exclusive_lock(self) -> Iterator[None]:
        fd = os.open(self._lock_path, os.O_RDWR | os.O_CREAT, 0o600)
        held = None
        try:
            os.fchmod(fd, 0o600)
            held = acquire_exclusive_fd(fd, timeout_seconds=10.0)
            yield
        finally:
            if held is not None:
                held.release()
            os.close(fd)

    @contextmanager
    def _platform_exclusive_lock(self) -> Iterator[None]:
        """Use the platform registry's journal lock for one currentness boundary."""

        fd = os.open(self._platform_lock_path, os.O_RDWR | os.O_CREAT, 0o600)
        held = None
        try:
            os.fchmod(fd, 0o600)
            held = acquire_exclusive_fd(fd, timeout_seconds=10.0)
            yield
        finally:
            if held is not None:
                held.release()
            os.close(fd)

    @contextmanager
    def _rdp_exclusive_lock(self) -> Iterator[None]:
        """Hold the canonical RDP journal lock through one currentness boundary."""

        fd = os.open(self._rdp_lock_path, os.O_RDWR | os.O_CREAT, 0o600)
        held = None
        try:
            os.fchmod(fd, 0o600)
            held = acquire_exclusive_fd(fd, timeout_seconds=10.0)
            yield
        finally:
            if held is not None:
                held.release()
            os.close(fd)

    @contextmanager
    def _currentness_commit_locks(self) -> Iterator[None]:
        """Hold lower-level journals in the one permitted deterministic order.

        Callers must already hold the shared GOAL proof-head lock.  The full
        order is proof-head -> platform journal -> RDP journal -> closure
        process/file lock.  Public callback resolution happens before these
        lower locks.  Only the explicitly lock-safe source-row resolver may run
        inside them; platform and RDP state is parsed through unlocked readers.
        """

        with self._platform_exclusive_lock():
            with self._rdp_exclusive_lock():
                with self._thread_lock:
                    with self._exclusive_lock():
                        yield

    def _reset(self) -> None:
        self._records = {}
        self._heads = {}
        self._chain_heads = {}
        self._last_ledger_revision = 0
        self._last_record_hash = ""
        self._legacy_quarantined_count = 0

    def _load_existing(self) -> None:
        with self._thread_lock, self._exclusive_lock():
            self._load_existing_unlocked()

    def _load_existing_unlocked(self) -> None:
        self._reset()
        if not self._path.exists():
            return
        saw_schema_v5 = False
        for line_no, line in enumerate(self._path.read_text(encoding="utf-8").split("\n"), start=1):
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(
                    f"invalid partial/corrupt platform closure row at {self._path}:{line_no}"
                ) from exc
            if isinstance(row, dict) and row.get("schema_version") in {1, 2, 3}:
                self._legacy_quarantined_count += 1
                continue
            if (
                isinstance(row, dict)
                and row.get("schema_version") == _LEGACY_PLATFORM_CLOSURE_SCHEMA_VERSION
            ):
                if saw_schema_v5:
                    raise ValueError(
                        f"legacy platform closure row follows schema-v5 history at {self._path}:{line_no}"
                    )
                try:
                    self._apply_legacy_v4_row(row)
                except Exception as exc:
                    raise ValueError(
                        f"invalid persisted legacy platform closure row at {self._path}:{line_no}"
                    ) from exc
                self._legacy_quarantined_count += 1
                continue
            if not isinstance(row, dict) or row.get("schema_version") != PLATFORM_CLOSURE_SCHEMA_VERSION:
                raise ValueError(
                    f"unsupported platform closure row at {self._path}:{line_no}"
                )
            saw_schema_v5 = True
            try:
                self._apply_row(row)
            except Exception as exc:
                raise ValueError(
                    f"invalid persisted platform closure row at {self._path}:{line_no}"
                ) from exc

    def _apply_legacy_v4_row(self, row: dict[str, Any]) -> None:
        expected = {
            "schema_version",
            "event_type",
            "owner_user_id",
            "ledger_revision",
            "owner_revision",
            "previous_record_hash",
            "receipt",
            "record_hash",
        }
        if set(row) != expected or row.get("event_type") != "platform_closure_recorded":
            raise ValueError("platform closure row has an inexact schema-v4 envelope")
        owner = _owner(row["owner_user_id"])
        ledger_revision = row["ledger_revision"]
        if type(ledger_revision) is not int or ledger_revision != self._last_ledger_revision + 1:
            raise ValueError("legacy platform closure ledger revision chain is discontinuous")
        if row["previous_record_hash"] != self._last_record_hash:
            raise ValueError("legacy platform closure previous_record_hash mismatch")
        body = {key: value for key, value in row.items() if key != "record_hash"}
        expected_hash = _content_hash(body)
        if row["record_hash"] != expected_hash:
            raise ValueError("legacy platform closure record_hash mismatch")

        receipt = row.get("receipt")
        if not isinstance(receipt, dict) or set(receipt) != {
            "receipt_ref",
            "owner_user_id",
            "owner_revision",
            "previous_receipt_ref",
            "snapshot",
            "receipt_version",
        }:
            raise ValueError("legacy platform closure receipt has an inexact field set")
        if receipt.get("receipt_version") != _LEGACY_PLATFORM_CLOSURE_RECEIPT_VERSION:
            raise ValueError("legacy platform closure receipt version is unsupported")
        snapshot = receipt.get("snapshot")
        legacy_snapshot_fields = {
            "owner_user_id",
            "required_rows",
            "rows",
            "rdps",
            "strict_manifest_accepted",
            "strict_manifest_verdict_hash",
            "source_manifest_event_hash",
            "manifest_hash",
        }
        if not isinstance(snapshot, dict) or set(snapshot) != legacy_snapshot_fields:
            raise ValueError("legacy platform closure snapshot has an inexact field set")
        if (
            snapshot.get("owner_user_id") != owner
            or snapshot.get("required_rows") != list(REQUIRED_PLATFORM_ROWS)
            or not isinstance(snapshot.get("rows"), list)
            or not isinstance(snapshot.get("rdps"), list)
        ):
            raise ValueError("legacy platform closure snapshot owner/rows are invalid")
        rows = tuple(_row_from_dict(value) for value in snapshot["rows"])
        if tuple(item.m_row for item in rows) != tuple(REQUIRED_PLATFORM_ROWS):
            raise ValueError("legacy platform closure rows are not canonical")
        for item in rows:
            if (
                item.m_row != _row_value(item.record)
                or item.record_hash != _content_hash(_record_payload(item.record))
                or not _valid_production_ref(item.production_ref)
            ):
                raise ValueError("legacy platform closure row state is invalid")
            _reject_placeholder_record(item.record)
        rdps = tuple(_rdp_from_dict(value) for value in snapshot["rdps"])
        rdp_ids = tuple(item.package_id for item in rdps)
        if (
            not rdps
            or rdp_ids != tuple(sorted(rdp_ids))
            or len(rdp_ids) != len(set(rdp_ids))
            or any(
                not item.package_id
                or is_placeholder_ref(item.package_id)
                or not _valid_content_hash(item.manifest_hash)
                for item in rdps
            )
        ):
            raise ValueError("legacy platform closure RDP state is invalid")
        if validate_platform_coverage(tuple(item.record for item in rows)).violations:
            raise ValueError("legacy platform closure manifest shape is invalid")
        canonical_verdict_hash = _content_hash({"accepted": True, "violations": []})
        if (
            snapshot.get("strict_manifest_accepted") is not True
            or snapshot.get("strict_manifest_verdict_hash") != canonical_verdict_hash
            or not _valid_content_hash(snapshot.get("source_manifest_event_hash"))
        ):
            raise ValueError("legacy platform closure strict verdict is invalid")
        legacy_manifest_body = {
            key: value for key, value in snapshot.items() if key != "manifest_hash"
        }
        if snapshot.get("manifest_hash") != _content_hash(legacy_manifest_body):
            raise ValueError("legacy platform closure manifest_hash mismatch")

        previous = self._chain_heads.get(owner)
        expected_owner_revision = 1 if previous is None else previous.owner_revision + 1
        expected_previous_ref = "" if previous is None else previous.receipt_ref
        if (
            row.get("owner_revision") != expected_owner_revision
            or receipt.get("owner_user_id") != owner
            or receipt.get("owner_revision") != expected_owner_revision
            or receipt.get("previous_receipt_ref") != expected_previous_ref
        ):
            raise ValueError("legacy platform closure owner chain mismatch")
        expected_receipt_ref = "platform_closure_receipt:" + _sha256(
            {
                "owner_user_id": owner,
                "owner_revision": expected_owner_revision,
                "previous_receipt_ref": expected_previous_ref,
                "snapshot": snapshot,
                "receipt_version": _LEGACY_PLATFORM_CLOSURE_RECEIPT_VERSION,
            }
        )
        if receipt.get("receipt_ref") != expected_receipt_ref:
            raise ValueError("legacy platform closure receipt identity mismatch")
        self._chain_heads[owner] = _PlatformClosureChainHead(
            receipt_ref=expected_receipt_ref,
            owner_revision=expected_owner_revision,
            legacy=True,
        )
        self._last_ledger_revision = ledger_revision
        self._last_record_hash = expected_hash

    def _apply_row(self, row: dict[str, Any]) -> None:
        expected = {
            "schema_version",
            "event_type",
            "owner_user_id",
            "ledger_revision",
            "owner_revision",
            "previous_record_hash",
            "receipt",
            "record_hash",
        }
        if set(row) != expected or row.get("event_type") != "platform_closure_recorded":
            raise ValueError("platform closure row has an inexact schema-v5 envelope")
        owner = _owner(row["owner_user_id"])
        ledger_revision = row["ledger_revision"]
        if type(ledger_revision) is not int or ledger_revision != self._last_ledger_revision + 1:
            raise ValueError("platform closure ledger revision chain is discontinuous")
        if row["previous_record_hash"] != self._last_record_hash:
            raise ValueError("platform closure previous_record_hash mismatch")
        body = {key: value for key, value in row.items() if key != "record_hash"}
        expected_hash = _content_hash(body)
        if row["record_hash"] != expected_hash:
            raise ValueError("platform closure record_hash mismatch")
        previous = self._chain_heads.get(owner)
        expected_owner_revision = 1 if previous is None else previous.owner_revision + 1
        if row["owner_revision"] != expected_owner_revision:
            raise ValueError("platform closure owner revision chain mismatch")
        receipt = platform_closure_receipt_from_dict(row["receipt"])
        if (
            receipt.owner_user_id != owner
            or receipt.owner_revision != expected_owner_revision
            or receipt.previous_receipt_ref != ("" if previous is None else previous.receipt_ref)
        ):
            raise ValueError("platform closure receipt chain does not match its envelope")
        shape = validate_platform_closure_receipt_shape(receipt)
        if not shape.accepted:
            raise ValueError("invalid platform closure receipt shape")
        key = (owner, receipt.receipt_ref)
        existing = self._records.get(key)
        if existing is not None and existing != receipt:
            raise ValueError("platform closure receipt identity collision")
        self._records[key] = receipt
        self._heads[owner] = receipt
        self._chain_heads[owner] = _PlatformClosureChainHead(
            receipt_ref=receipt.receipt_ref,
            owner_revision=receipt.owner_revision,
            legacy=False,
        )
        self._last_ledger_revision = ledger_revision
        self._last_record_hash = expected_hash

    def _journal_manifest_unlocked(
        self,
        owner: str,
    ) -> tuple[tuple[PlatformCapabilityRecord, ...], str]:
        """Read the last owner event while the platform journal lock is held."""

        current: tuple[PlatformCapabilityRecord, ...] | None = None
        current_event_hash = ""
        if not self._platform_path.exists():
            raise PlatformClosureError("platform coverage journal is absent")
        for line_no, line in enumerate(
            self._platform_path.read_text(encoding="utf-8").split("\n"),
            start=1,
        ):
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError as exc:
                raise PlatformClosureError(
                    f"platform coverage journal is partial/corrupt at line {line_no}"
                ) from exc
            if isinstance(row, dict) and row.get("schema_version") == 1:
                continue
            if not isinstance(row, dict) or set(row) != {
                "schema_version",
                "event_type",
                "owner_user_id",
                "records",
            }:
                raise PlatformClosureError(
                    f"platform coverage journal has an unsupported envelope at line {line_no}"
                )
            if (
                row.get("schema_version") != 2
                or row.get("event_type") != "platform_coverage_manifest_recorded"
            ):
                raise PlatformClosureError(
                    f"platform coverage journal has an unsupported event at line {line_no}"
                )
            event_owner = _owner(row.get("owner_user_id"))
            raw_records = row.get("records")
            if not isinstance(raw_records, list):
                raise PlatformClosureError(
                    f"platform coverage journal records are invalid at line {line_no}"
                )
            parsed = tuple(_exact_record(item) for item in raw_records)
            if event_owner == owner:
                current = parsed
                current_event_hash = _content_hash(row)
        if current is None:
            raise PlatformClosureError(
                "platform coverage journal has no schema-v2 manifest for owner"
            )
        return current, current_event_hash

    @staticmethod
    def _manifest_payloads(
        records: tuple[PlatformCapabilityRecord, ...],
    ) -> dict[str, dict[str, Any]]:
        return {_row_value(record): _record_payload(record) for record in records}

    def _journal_rdps_unlocked(
        self,
        owner: str,
        expected_package_ids: tuple[str, ...],
    ) -> tuple[PlatformClosureRDPState, ...]:
        if not self._rdp_path.exists():
            raise PlatformClosureError("RDP manifest journal is absent")
        current: dict[str, PlatformClosureRDPState] = {}
        for line_no, line in enumerate(
            self._rdp_path.read_text(encoding="utf-8").split("\n"),
            start=1,
        ):
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError as exc:
                raise PlatformClosureError(
                    f"RDP manifest journal is partial/corrupt at line {line_no}"
                ) from exc
            try:
                if isinstance(row, dict) and row.get("schema_version") == 1:
                    parse_quarantined_rdp_manifest_event_v1(row)
                    continue
                event_owner, _recorded_by, _waiver, manifest = (
                    parse_rdp_manifest_event_v2(row)
                )
            except Exception as exc:
                raise PlatformClosureError(
                    f"RDP manifest journal event is invalid at line {line_no}"
                ) from exc
            if event_owner != owner:
                continue
            manifest_payload = manifest.to_open_dict()
            state = platform_closure_rdp_state(
                package_id=manifest.package_id,
                manifest_payload=manifest_payload,
            )
            existing = current.get(state.package_id)
            if existing is not None and existing != state:
                raise PlatformClosureError(
                    "RDP package_id collision with different journal content"
                )
            current[state.package_id] = state
        expected = tuple(sorted(expected_package_ids))
        if not expected or len(expected) != len(set(expected)):
            raise PlatformClosureError("coverage-linked RDP package set is invalid")
        missing = tuple(package for package in expected if package not in current)
        if missing:
            raise PlatformClosureError(
                "RDP manifest journal is missing an owner-scoped coverage-linked package"
            )
        return tuple(current[package] for package in expected)

    @staticmethod
    def _coverage_state_for_row(resolved: ResolvedPlatformRow) -> Any:
        matches = tuple(
            state
            for state in resolved.source_states
            if state.source_kind == "goal_entrypoint_coverage"
        )
        if len(matches) != 1:
            raise PlatformClosureError(
                f"platform row {resolved.m_row} must bind exactly one source coverage state"
            )
        return matches[0]

    def _source_binding_for_row(
        self,
        *,
        owner: str,
        resolved: ResolvedPlatformRow,
        rdp_cache: dict[str, PlatformClosureRDPState],
        resolve_linked_rdp: PlatformRDPResolver | None = None,
    ) -> PlatformClosureSourceBinding:
        active_rdp_resolver = resolve_linked_rdp or self._resolve_linked_rdp
        state = self._coverage_state_for_row(resolved)
        try:
            coverage = self._resolve_current_coverage(owner, state.source_ref)
        except (KeyError, LookupError, TypeError, ValueError) as exc:
            raise PlatformClosureError(
                f"platform row {resolved.m_row} source coverage could not be resolved: "
                f"{type(exc).__name__}"
            ) from exc
        if not isinstance(coverage, GoalEntrypointCoverageRecord):
            raise TypeError(
                "resolve_current_coverage must return GoalEntrypointCoverageRecord"
            )
        coverage_hash = _content_hash(_jsonable(coverage))
        shape = validate_goal_entrypoint_coverage(coverage)
        sections = tuple(
            _text(getattr(section, "value", section))
            for section in coverage.goal_sections
        )
        if (
            not shape.accepted
            or coverage.coverage_ref != state.source_ref
            or coverage_hash != state.state_hash
            or coverage.recorded_by != owner
            or "§14" not in sections
            or tuple(coverage.qro_refs) != (_text(resolved.record.qro_ref),)
            or tuple(coverage.research_graph_command_refs)
            != (_text(resolved.record.research_graph_ref),)
            or _text(resolved.record.lifecycle_ref)
            not in tuple(_text(ref) for ref in coverage.lifecycle_refs)
            or not set(_text(ref) for ref in resolved.record.evidence_refs).issubset(
                {_text(ref) for ref in coverage.evidence_refs}
            )
        ):
            raise PlatformClosureError(
                f"platform row {resolved.m_row} source coverage is stale or recombined"
            )
        raw_package_ids = tuple(_text(ref) for ref in coverage.rdp_refs)
        if (
            any(not ref or is_placeholder_ref(ref) for ref in raw_package_ids)
            or len(raw_package_ids) != len(set(raw_package_ids))
        ):
            raise PlatformClosureError(
                f"platform row {resolved.m_row} source coverage RDP refs are invalid"
            )
        package_ids = tuple(sorted(raw_package_ids))
        if resolved.m_row == "M18" and raw_package_ids != (
            _text(resolved.record.lifecycle_ref),
        ):
            raise PlatformClosureError(
                "M18 source coverage does not bind exactly its selected RDP package"
            )
        rdps: list[PlatformClosureRDPState] = []
        for package_id in package_ids:
            linked = rdp_cache.get(package_id)
            if linked is None:
                try:
                    linked = active_rdp_resolver(owner, package_id)
                except (KeyError, LookupError, TypeError, ValueError) as exc:
                    raise PlatformClosureError(
                        f"coverage-linked RDP {package_id!r} could not be resolved for owner: "
                        f"{type(exc).__name__}"
                    ) from exc
                if not isinstance(linked, PlatformClosureRDPState):
                    raise TypeError(
                        "resolve_linked_rdp must return PlatformClosureRDPState"
                    )
                if linked.package_id != package_id:
                    raise PlatformClosureError(
                        "coverage-linked RDP resolver returned a recombined package"
                    )
                rdp_cache[package_id] = linked
            rdps.append(linked)
        return PlatformClosureSourceBinding(
            m_row=resolved.m_row,
            source_coverage_ref=coverage.coverage_ref,
            source_coverage_hash=coverage_hash,
            rdps=tuple(rdps),
        )

    def _resolve_candidate(self, owner: str) -> _PlatformClosureCandidate:
        """Resolve public/callback state without recursively taking journal locks."""

        try:
            resolved_rows = self._resolve_current_manifest(owner)
        except (KeyError, LookupError, TypeError, ValueError) as exc:
            raise PlatformClosureError(
                "current platform producer state could not be resolved: "
                f"{type(exc).__name__}"
            ) from exc
        if not isinstance(resolved_rows, tuple) or any(
            not isinstance(row, ResolvedPlatformRow) for row in resolved_rows
        ):
            raise TypeError(
                "resolve_current_manifest must return tuple[ResolvedPlatformRow, ...]"
            )
        registered = tuple(self._platform_registry.records(owner_user_id=owner))
        if any(not isinstance(record, PlatformCapabilityRecord) for record in registered):
            raise TypeError("platform registry returned an invalid current manifest")
        by_row = {row.m_row: row for row in resolved_rows}
        if len(by_row) != len(resolved_rows) or set(by_row) != set(
            REQUIRED_PLATFORM_ROWS
        ):
            raise PlatformClosureError(
                "current platform producer state does not exactly cover required rows"
            )
        canonical_rows = tuple(by_row[row] for row in REQUIRED_PLATFORM_ROWS)
        rdp_cache: dict[str, PlatformClosureRDPState] = {}
        source_bindings = tuple(
            self._source_binding_for_row(
                owner=owner,
                resolved=resolved,
                rdp_cache=rdp_cache,
            )
            for resolved in canonical_rows
        )
        coverage_refs = tuple(
            binding.source_coverage_ref for binding in source_bindings
        )
        if len(coverage_refs) != len(set(coverage_refs)):
            raise PlatformClosureError(
                "platform source coverage revisions are recombined across rows"
            )
        records = tuple(row.record for row in canonical_rows)
        strict_decision = self._platform_registry.validate_manifest(
            records,
            owner_user_id=owner,
        )
        if not isinstance(strict_decision, PlatformCoverageDecision):
            raise TypeError(
                "platform registry validate_manifest returned an invalid decision"
            )
        return _PlatformClosureCandidate(
            resolved_rows=canonical_rows,
            registered_records=registered,
            source_bindings=source_bindings,
            strict_decision=strict_decision,
        )

    def _resolve_durable_candidate_unlocked(
        self,
        owner: str,
        expected: _PlatformClosureCandidate,
    ) -> _PlatformClosureCandidate:
        """Resolve source rows without re-entering held platform/RDP locks.

        Platform and RDP truth comes only from the direct journal parsers.  The
        narrow callback is required to be safe while those journal locks are
        held; it receives the already-parsed platform records so adapters never
        need to call the public platform registry from this boundary.
        """

        journal_records, _source_event_hash = self._journal_manifest_unlocked(owner)
        try:
            resolved_rows = self._resolve_current_manifest_unlocked(
                owner,
                journal_records,
            )
        except (KeyError, LookupError, TypeError, ValueError) as exc:
            raise PlatformClosureError(
                "current platform producer state could not be resolved: "
                f"{type(exc).__name__}"
            ) from exc
        if not isinstance(resolved_rows, tuple) or any(
            not isinstance(row, ResolvedPlatformRow) for row in resolved_rows
        ):
            raise TypeError(
                "resolve_current_manifest must return tuple[ResolvedPlatformRow, ...]"
            )
        by_row = {row.m_row: row for row in resolved_rows}
        if len(by_row) != len(resolved_rows) or set(by_row) != set(
            REQUIRED_PLATFORM_ROWS
        ):
            raise PlatformClosureError(
                "current platform producer state does not exactly cover required rows"
            )
        canonical_rows = tuple(by_row[row] for row in REQUIRED_PLATFORM_ROWS)
        return _PlatformClosureCandidate(
            resolved_rows=canonical_rows,
            registered_records=journal_records,
            source_bindings=expected.source_bindings,
            strict_decision=expected.strict_decision,
        )

    def _resolve_durable_snapshot_unlocked(
        self,
        owner: str,
        expected: _PlatformClosureCandidate,
    ) -> PlatformClosureSnapshot:
        candidate = self._resolve_durable_candidate_unlocked(owner, expected)
        return self._resolve_verified(owner, candidate)

    def _assert_durable_snapshot_unlocked(
        self,
        *,
        owner: str,
        expected_candidate: _PlatformClosureCandidate,
        expected: PlatformClosureSnapshot,
        boundary: str,
        append_completed: bool,
    ) -> None:
        try:
            fresh = self._resolve_durable_snapshot_unlocked(
                owner,
                expected_candidate,
            )
        except Exception as exc:
            if append_completed:
                raise PlatformClosureCommitUncertain(
                    "platform closure receipt was appended but current backing changed "
                    f"at the {boundary}; non-atomic stale append is persisted"
                ) from exc
            raise PlatformClosureError(
                "platform closure backing changed at the durable precommit boundary"
            ) from exc
        if fresh == expected:
            return
        if append_completed:
            raise PlatformClosureCommitUncertain(
                "platform closure receipt was appended but current backing changed "
                f"at the {boundary}; non-atomic stale append is persisted"
            )
        raise PlatformClosureError(
            "platform closure backing changed at the durable precommit boundary"
        )

    def _resolve_stable_candidate(
        self,
        owner: str,
        *,
        boundary: str,
    ) -> _PlatformClosureCandidate:
        first = self._resolve_candidate(owner)
        second = self._resolve_candidate(owner)
        if first != second:
            raise PlatformClosureError(
                f"platform/RDP backing changed during {boundary} before disk-current verification"
            )
        return second

    def _resolve_verified(
        self,
        owner: str,
        candidate: _PlatformClosureCandidate,
    ) -> PlatformClosureSnapshot:
        """Compare one stable candidate with journals while both locks are held."""

        journal_records, source_event_hash = self._journal_manifest_unlocked(owner)
        records = tuple(row.record for row in candidate.resolved_rows)
        registered = candidate.registered_records
        resolved_by_row = self._manifest_payloads(records)
        registered_by_row = self._manifest_payloads(registered)
        journal_by_row = self._manifest_payloads(journal_records)
        if (
            len(resolved_by_row) != len(records)
            or len(registered_by_row) != len(registered)
            or len(journal_by_row) != len(journal_records)
            or resolved_by_row != registered_by_row
            or resolved_by_row != journal_by_row
        ):
            raise PlatformClosureError(
                "resolved manifest does not equal the disk-current owner-scoped platform manifest"
            )
        journal_rdps = self._journal_rdps_unlocked(
            owner,
            tuple(rdp.package_id for rdp in candidate.rdps),
        )
        if candidate.rdps != journal_rdps:
            raise PlatformClosureError(
                "resolved coverage-linked RDPs do not equal their disk-current owner revisions"
            )
        return _build_snapshot(
            owner_user_id=owner,
            resolved_rows=candidate.resolved_rows,
            source_bindings=candidate.source_bindings,
            decision=candidate.strict_decision,
            source_manifest_event_hash=source_event_hash,
        )

    @staticmethod
    def _decision_error(decision: PlatformClosureDecision) -> PlatformClosureError:
        codes = ",".join(item.code for item in decision.violations)
        return PlatformClosureError(f"platform closure rejected: {codes}")

    def record_current(self, owner_user_id: str) -> PlatformClosureReceipt:
        """Commit one snapshot in the shared proof-head serialization domain."""

        owner = _owner(owner_user_id)
        with acquire_goal_proof_head_lock(self._entrypoint_ledger_path):
            candidate = self._resolve_stable_candidate(
                owner,
                boundary="closure commit-boundary resolution",
            )
            appended = False
            verified: PlatformClosureReceipt | None = None
            with self._currentness_commit_locks():
                self._load_existing_unlocked()
                snapshot = self._resolve_verified(owner, candidate)
                current_head = self._heads.get(owner)
                if current_head is not None and current_head.snapshot == snapshot:
                    verified = self._verified_head_unlocked(
                        owner,
                        candidate,
                        receipt_ref=current_head.receipt_ref,
                    )
                else:
                    chain_head = self._chain_heads.get(owner)
                    owner_revision = (
                        1 if chain_head is None else chain_head.owner_revision + 1
                    )
                    previous_ref = (
                        "" if chain_head is None else chain_head.receipt_ref
                    )
                    blank = PlatformClosureReceipt(
                        receipt_ref="",
                        owner_user_id=owner,
                        owner_revision=owner_revision,
                        previous_receipt_ref=previous_ref,
                        snapshot=snapshot,
                    )
                    receipt = PlatformClosureReceipt(
                        receipt_ref=blank.canonical_receipt_ref,
                        owner_user_id=owner,
                        owner_revision=owner_revision,
                        previous_receipt_ref=previous_ref,
                        snapshot=snapshot,
                    )
                    shape = validate_platform_closure_receipt_shape(receipt)
                    if not shape.accepted:
                        raise self._decision_error(shape)
                    body = {
                        "schema_version": PLATFORM_CLOSURE_SCHEMA_VERSION,
                        "event_type": "platform_closure_recorded",
                        "owner_user_id": owner,
                        "ledger_revision": self._last_ledger_revision + 1,
                        "owner_revision": owner_revision,
                        "previous_record_hash": self._last_record_hash,
                        "receipt": _receipt_to_dict(receipt),
                    }
                    row = {**body, "record_hash": _content_hash(body)}
                    self._commit_row(
                        row,
                        precommit_assertion=lambda: (
                            self._assert_durable_snapshot_unlocked(
                                owner=owner,
                                expected_candidate=candidate,
                                expected=snapshot,
                                boundary="durable precommit boundary",
                                append_completed=False,
                            )
                        ),
                    )
                    appended = True
                    try:
                        self._assert_durable_snapshot_unlocked(
                            owner=owner,
                            expected_candidate=candidate,
                            expected=snapshot,
                            boundary="post-append locked boundary",
                            append_completed=True,
                        )
                        verified = self._verified_head_unlocked(
                            owner,
                            candidate,
                            receipt_ref=receipt.receipt_ref,
                        )
                    except PlatformClosureCommitUncertain:
                        self._reset()
                        raise
                    except Exception as exc:
                        self._reset()
                        raise PlatformClosureCommitUncertain(
                            "platform closure receipt was appended but the in-memory "
                            "head changed before success; non-atomic status is persisted"
                        ) from exc

            # Typed stores cannot safely be called while the platform/RDP locks
            # are held.  Re-resolve them twice immediately after releasing those
            # locks, while the shared proof-head lock still excludes certified
            # row-source writes.  Drift after a durable append is reported as
            # uncertain; it is never returned as a successful current receipt.
            try:
                return_candidate = self._resolve_stable_candidate(
                    owner,
                    boundary="closure public return-boundary resolution",
                )
                if return_candidate != candidate:
                    raise PlatformClosureError(
                        "platform typed source state changed before the public return boundary"
                    )
            except Exception as exc:
                if appended:
                    self._reset()
                    raise PlatformClosureCommitUncertain(
                        "platform closure receipt was appended but typed source state "
                        "changed before return; non-atomic stale status is persisted"
                    ) from exc
                raise PlatformClosureError(
                    "platform closure typed source state changed before return"
                ) from exc
            if verified is None:
                raise RuntimeError("platform closure commit produced no verified receipt")
            return verified

    def _commit_row(
        self,
        row: dict[str, Any],
        *,
        precommit_assertion: Callable[[], None],
    ) -> None:
        """Apply then durably append, rolling memory back on any certain failure."""

        checkpoint = (
            dict(self._records),
            dict(self._heads),
            dict(self._chain_heads),
            self._last_ledger_revision,
            self._last_record_hash,
            self._legacy_quarantined_count,
        )
        try:
            # Validate and stage the exact row before the durable replace.  The
            # registry locks make this provisional state invisible to peers.
            self._apply_row(row)
            self._atomic_append(
                row,
                precommit_assertion=precommit_assertion,
            )
        except PlatformClosureCommitUncertain:
            # Disk state is deliberately not guessed when rollback durability
            # could not be proved; the next public operation reloads from disk.
            self._reset()
            raise
        except Exception:
            (
                self._records,
                self._heads,
                self._chain_heads,
                self._last_ledger_revision,
                self._last_record_hash,
                self._legacy_quarantined_count,
            ) = checkpoint
            raise

    def _atomic_append(
        self,
        row: dict[str, Any],
        *,
        precommit_assertion: Callable[[], None],
    ) -> None:
        original_exists = self._path.exists()
        original = self._path.read_bytes() if original_exists else b""
        original_state = (original_exists, original)
        separator = b"" if not original or original.endswith(b"\n") else b"\n"
        payload = original + separator + (_canonical_json(row) + "\n").encode("utf-8")
        target_state = (True, payload)
        # This is the true durable precommit boundary: the proof head plus
        # platform, RDP, and closure locks are held and no closure bytes have
        # been created or replaced yet.
        precommit_assertion()
        fd, raw_tmp = tempfile.mkstemp(prefix=f".{self._path.name}.", dir=self._path.parent)
        tmp = Path(raw_tmp)
        try:
            os.fchmod(fd, 0o600)
            write_fd = fd
            fd = -1
            with os.fdopen(write_fd, "wb", closefd=True) as handle:
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(tmp, self._path)
            parent_fd = os.open(self._path.parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
            try:
                os.fsync(parent_fd)
            finally:
                os.close(parent_fd)
            if self._disk_state() != target_state:
                raise OSError("platform closure append bytes could not be verified")
        except Exception as exc:
            try:
                current_state = self._disk_state()
            except Exception as recovery_exc:
                raise PlatformClosureCommitUncertain(
                    "platform closure append failed and journal state cannot be read"
                ) from recovery_exc
            if current_state == original_state:
                raise
            if current_state != target_state:
                raise PlatformClosureCommitUncertain(
                    "platform closure append failed with unexpected journal bytes"
                ) from exc
            try:
                self._restore(original_exists=original_exists, original=original)
            except Exception as recovery_exc:
                raise PlatformClosureCommitUncertain(
                    "platform closure append failed and durable rollback is uncertain"
                ) from recovery_exc
            raise
        finally:
            if fd >= 0:
                os.close(fd)
            tmp.unlink(missing_ok=True)

    def _disk_state(self) -> tuple[bool, bytes]:
        exists = self._path.exists()
        return exists, self._path.read_bytes() if exists else b""

    def _restore(self, *, original_exists: bool, original: bytes) -> None:
        if original_exists:
            fd, raw_restore = tempfile.mkstemp(
                prefix=f".{self._path.name}.restore.", dir=self._path.parent
            )
            restore = Path(raw_restore)
            try:
                os.fchmod(fd, 0o600)
                write_fd = fd
                fd = -1
                with os.fdopen(write_fd, "wb", closefd=True) as handle:
                    handle.write(original)
                    handle.flush()
                    os.fsync(handle.fileno())
                os.replace(restore, self._path)
            finally:
                if fd >= 0:
                    os.close(fd)
                restore.unlink(missing_ok=True)
        else:
            self._path.unlink(missing_ok=True)
        parent_fd = os.open(self._path.parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
        try:
            os.fsync(parent_fd)
        finally:
            os.close(parent_fd)
        expected = (original_exists, original if original_exists else b"")
        if self._disk_state() != expected:
            raise OSError("platform closure rollback bytes could not be verified")

    def receipt(self, receipt_ref: str, *, owner_user_id: str) -> PlatformClosureReceipt:
        owner = _owner(owner_user_id)
        ref = _text(receipt_ref)
        with self._thread_lock, self._exclusive_lock():
            self._load_existing_unlocked()
            try:
                return self._records[(owner, ref)]
            except KeyError:
                raise KeyError("platform closure receipt is not recorded for owner") from None

    def _verified_head_unlocked(
        self,
        owner: str,
        candidate: _PlatformClosureCandidate,
        *,
        receipt_ref: str | None = None,
    ) -> PlatformClosureReceipt:
        try:
            receipt = self._heads[owner]
        except KeyError:
            raise KeyError("platform closure has no current receipt for owner") from None
        if receipt_ref is not None and receipt.receipt_ref != _text(receipt_ref):
            raise PlatformClosureError("requested platform closure receipt is not the owner head")
        snapshot = self._resolve_verified(owner, candidate)
        if snapshot != receipt.snapshot:
            raise PlatformClosureError(
                "platform closure receipt does not match disk-current strict backing"
            )
        return receipt

    def current_receipt(self, *, owner_user_id: str) -> PlatformClosureReceipt:
        """Return the owner head only after strict disk-current revalidation."""

        owner = _owner(owner_user_id)
        with acquire_goal_proof_head_lock(self._entrypoint_ledger_path):
            candidate = self._resolve_stable_candidate(
                owner,
                boundary="current receipt lookup",
            )
            with self._currentness_commit_locks():
                self._load_existing_unlocked()
                return self._verified_head_unlocked(owner, candidate)

    def current_rows(
        self,
        *,
        owner_user_id: str,
        m_rows: tuple[str, ...] | None = None,
        receipt_ref: str | None = None,
    ) -> tuple[PlatformClosureRowState, ...]:
        """Return selected rows only from a freshly revalidated owner head.

        This is the supported lookup for section-level aggregate proofs.  It
        rejects duplicate/unknown requests before resolving and never returns
        rows from a merely present or stale receipt.
        """

        owner = _owner(owner_user_id)
        selected = tuple(REQUIRED_PLATFORM_ROWS) if m_rows is None else tuple(m_rows)
        if not selected or len(selected) != len(set(selected)):
            raise ValueError("m_rows must be a non-empty exact unique row set")
        unknown = tuple(row for row in selected if row not in REQUIRED_PLATFORM_ROWS)
        if unknown:
            raise ValueError(f"unknown platform rows requested: {','.join(unknown)}")
        with acquire_goal_proof_head_lock(self._entrypoint_ledger_path):
            candidate = self._resolve_stable_candidate(
                owner,
                boundary="current row lookup",
            )
            with self._currentness_commit_locks():
                self._load_existing_unlocked()
                receipt = self._verified_head_unlocked(
                    owner,
                    candidate,
                    receipt_ref=receipt_ref,
                )
                by_row = {row.m_row: row for row in receipt.snapshot.rows}
                if len(by_row) != len(REQUIRED_PLATFORM_ROWS):
                    raise PlatformClosureError(
                        "current platform closure contains duplicate or missing rows"
                    )
                return tuple(by_row[row] for row in selected)

    def current_row(
        self,
        m_row: str,
        *,
        owner_user_id: str,
        receipt_ref: str | None = None,
    ) -> PlatformClosureRowState:
        """Return one strictly current owner row for a section subproof."""

        return self.current_rows(
            owner_user_id=owner_user_id,
            m_rows=(_text(m_row),),
            receipt_ref=receipt_ref,
        )[0]

    def validate_current(
        self,
        receipt_ref: str,
        *,
        owner_user_id: str,
    ) -> PlatformClosureDecision:
        try:
            owner = _owner(owner_user_id)
            with acquire_goal_proof_head_lock(self._entrypoint_ledger_path):
                candidate = self._resolve_stable_candidate(
                    owner,
                    boundary="current receipt validation",
                )
                with self._currentness_commit_locks():
                    self._load_existing_unlocked()
                    receipt = self._records[(owner, _text(receipt_ref))]
                    current = self._heads[owner]
                    snapshot = self._resolve_verified(owner, candidate)
        except Exception as exc:
            return PlatformClosureDecision(
                False,
                (
                    PlatformClosureViolation(
                        "platform_closure_current_resolution_failed",
                        f"current platform manifest could not be resolved: {type(exc).__name__}",
                        ref=_text(receipt_ref),
                    ),
                ),
            )
        violations: list[PlatformClosureViolation] = []
        if current.receipt_ref != receipt.receipt_ref:
            _reject(
                violations,
                "platform_closure_receipt_not_head",
                "platform closure receipt is no longer the owner head",
                field="receipt_ref",
                ref=receipt.receipt_ref,
            )
        if snapshot != receipt.snapshot:
            _reject(
                violations,
                "platform_closure_current_state_drifted",
                "one or more platform manifest rows or strict backing verdicts changed",
                field="snapshot",
                ref=receipt.receipt_ref,
            )
        return PlatformClosureDecision(not violations, tuple(violations))


def platform_closure_semantic_material(
    receipt: PlatformClosureReceipt,
    *,
    coverage_refs: tuple[str, ...],
    validation_refs: tuple[str, ...],
) -> PlatformClosureSemanticMaterial:
    del coverage_refs
    records = tuple(row.record for row in receipt.snapshot.rows)
    bound_coverage_refs = tuple(
        binding.source_coverage_ref for binding in receipt.snapshot.source_bindings
    )
    receipt_validation_refs = tuple(
        _text(ref)
        for ref in validation_refs
        if _text(ref) and _text(ref) != receipt.receipt_ref
    )
    producers = tuple(
        sorted(
            {
                *(str(record.qro_ref or "") for record in records),
                *(str(record.research_graph_ref or "") for record in records),
            }
        )
    )
    stores = tuple(
        sorted(
            {
                receipt.receipt_ref,
                receipt.snapshot.source_manifest_event_hash,
                *(row.production_ref for row in receipt.snapshot.rows),
                *(binding.source_coverage_ref for binding in receipt.snapshot.source_bindings),
                *(binding.source_coverage_hash for binding in receipt.snapshot.source_bindings),
                *(str(record.lifecycle_ref or "") for record in records),
                *(str(record.governance_ref or "") for record in records),
                *(str(record.rag_ref or "") for record in records),
                *(str(record.math_spine_ref or "") for record in records),
                *(item.ref for record in records for item in record.specific_refs),
                *(rdp.package_id for rdp in receipt.snapshot.rdps),
                *(rdp.manifest_hash for rdp in receipt.snapshot.rdps),
            }
        )
    )
    tests = tuple(
        sorted(
            {
                *receipt_validation_refs,
                *(ref for record in records for ref in record.evidence_refs),
                *(rdp.manifest_hash for rdp in receipt.snapshot.rdps),
                *(binding.source_coverage_hash for binding in receipt.snapshot.source_bindings),
            }
        )
    )
    return PlatformClosureSemanticMaterial(
        subject_ref=f"goal_section:§14:platform_closure:{receipt.receipt_ref}",
        producer_refs=producers,
        store_refs=stores,
        consumer_refs=(
            PLATFORM_CLOSURE_ENTRYPOINT_REF,
            *bound_coverage_refs,
        ),
        gate_verdict_refs=(
            receipt.receipt_ref,
            f"platform_manifest:{receipt.snapshot.manifest_hash}",
            f"platform_manifest_verdict:{receipt.snapshot.strict_manifest_verdict_hash}",
            *tuple(
                f"rdp_manifest:{rdp.package_id}:{rdp.manifest_hash}"
                for rdp in receipt.snapshot.rdps
            ),
            *tuple(
                "platform_source_binding:"
                f"{binding.m_row}:{binding.source_coverage_hash}"
                for binding in receipt.snapshot.source_bindings
            ),
        ),
        test_refs=tests,
    )


class PlatformClosureSectionAdapter:
    """Read-only §14 adapter over current source lineages and one closure receipt."""

    def __init__(
        self,
        entrypoint_registry: Any,
        closure_registry: PersistentPlatformClosureRegistry,
        source_registry: Any = None,
    ) -> None:
        self._entrypoint_registry = entrypoint_registry
        self._closure_registry = closure_registry
        self._source_registry = source_registry
        self._entrypoint_ledger_path = (
            Path(entrypoint_registry.path).expanduser().absolute()
        )

    def validate(
        self,
        record: GoalSectionSemanticProofRecord,
        *,
        owner: str,
    ) -> GoalSemanticDecision:
        with acquire_goal_proof_head_lock(self._entrypoint_ledger_path):
            return self._validate_under_proof_head(record, owner=owner)

    def _validate_under_proof_head(
        self,
        record: GoalSectionSemanticProofRecord,
        *,
        owner: str,
    ) -> GoalSemanticDecision:
        violations: list[GoalSemanticViolation] = []

        def reject(field: str, ref: str, message: str) -> None:
            violations.append(
                GoalSemanticViolation(
                    "goal_semantic_platform_closure_invalid",
                    message,
                    field=field,
                    ref=ref,
                )
            )

        owner = _text(owner)
        if record.section != "§14":
            reject("section", record.section, "platform closure adapter only supports section 14")
            return GoalSemanticDecision(False, tuple(violations))
        if record.recorded_by != owner:
            reject("recorded_by", record.recorded_by, "section 14 semantic proof owner mismatch")
        if not record.claims_section_complete or record.unverified_residuals:
            reject(
                "claims_section_complete",
                record.proof_ref,
                "section 14 completion requires a complete claim with no residuals",
            )
        try:
            receipt_refs = tuple(
                ref
                for ref in record.gate_verdict_refs
                if ref.startswith("platform_closure_receipt:")
            )
        except Exception:
            receipt_refs = ()
        if len(receipt_refs) != 1:
            reject(
                "gate_verdict_refs",
                ",".join(receipt_refs),
                "section 14 requires exactly one durable platform closure receipt",
            )
            return GoalSemanticDecision(False, tuple(violations))
        receipt_ref = receipt_refs[0]
        try:
            receipt = self._closure_registry.receipt(receipt_ref, owner_user_id=owner)
        except Exception:
            reject("gate_verdict_refs", receipt_ref, "platform closure receipt is absent for owner")
            return GoalSemanticDecision(False, tuple(violations))
        current = self._closure_registry.validate_current(receipt_ref, owner_user_id=owner)
        if not current.accepted:
            reject(
                "gate_verdict_refs",
                receipt_ref,
                "platform closure receipt is no longer current: "
                + ",".join(item.code for item in current.violations),
            )
        rows = receipt.snapshot.rows
        bindings = receipt.snapshot.source_bindings
        if self._source_registry is None:
            reject(
                "store_refs",
                receipt_ref,
                "section 14 requires the current typed platform source registry",
            )
            return GoalSemanticDecision(False, tuple(violations))
        bound_coverage_refs = tuple(
            binding.source_coverage_ref for binding in bindings
        )
        if (
            len(bindings) != len(rows)
            or tuple(binding.m_row for binding in bindings)
            != tuple(row.m_row for row in rows)
            or tuple(record.entrypoint_coverage_refs) != bound_coverage_refs
            or len(set(record.entrypoint_coverage_refs)) != len(rows)
        ):
            reject(
                "entrypoint_coverage_refs",
                ",".join(record.entrypoint_coverage_refs),
                "section 14 requires the exact source coverage revision bound per platform row",
            )
            return GoalSemanticDecision(False, tuple(violations))
        validation_refs: list[str] = []
        for row, binding in zip(rows, bindings, strict=True):
            coverage_ref = binding.source_coverage_ref
            try:
                selected_coverage_ref = self._source_registry.source_coverage_ref(
                    row.m_row,
                    owner_user_id=owner,
                )
                current_source_row = self._source_registry.resolve_current_row(
                    row.m_row,
                    owner_user_id=owner,
                )
            except Exception as exc:
                reject(
                    "store_refs",
                    row.m_row,
                    f"platform row current typed source could not be resolved: {type(exc).__name__}",
                )
                continue
            if _text(selected_coverage_ref) != _text(coverage_ref):
                reject(
                    "entrypoint_coverage_refs",
                    coverage_ref,
                    f"platform row {row.m_row} semantic lineage is not its certified source lineage",
                )
            if (
                _text(getattr(current_source_row, "production_ref", ""))
                != _text(row.production_ref)
                or getattr(current_source_row, "record", None) != row.record
            ):
                reject(
                    "store_refs",
                    row.m_row,
                    f"platform row {row.m_row} closure does not bind its current typed production",
                )
            try:
                coverage = _canonical_or_legacy_coverage(
                    self._entrypoint_registry,
                    coverage_ref,
                    owner=owner,
                )
                backing = self._entrypoint_registry.validate_real_backing(coverage)
            except Exception as exc:
                reject(
                    "entrypoint_coverage_refs",
                    coverage_ref,
                    f"platform row source lineage could not be resolved: {type(exc).__name__}",
                )
                continue
            if not bool(getattr(backing, "accepted", False)):
                reject(
                    "entrypoint_coverage_refs",
                    coverage_ref,
                    f"platform row {row.m_row} source lineage is not current",
                )
            sections = tuple(
                _text(getattr(section, "value", section))
                for section in (getattr(coverage, "goal_sections", ()) or ())
            )
            if "§14" not in sections:
                reject(
                    "entrypoint_coverage_refs",
                    coverage_ref,
                    f"platform row {row.m_row} source lineage is not bound to section 14",
                )
            if _text(getattr(coverage, "recorded_by", "")) != owner:
                reject("entrypoint_coverage_refs", coverage_ref, "platform row source owner mismatch")
            if _content_hash(_jsonable(coverage)) != binding.source_coverage_hash:
                reject(
                    "entrypoint_coverage_refs",
                    coverage_ref,
                    f"platform row {row.m_row} source coverage revision hash drifted",
                )
            if tuple(
                sorted(
                    _text(ref)
                    for ref in getattr(coverage, "rdp_refs", ()) or ()
                )
            ) != tuple(rdp.package_id for rdp in binding.rdps):
                reject(
                    "entrypoint_coverage_refs",
                    coverage_ref,
                    f"platform row {row.m_row} source coverage RDP linkage drifted",
                )
            if bool(getattr(coverage, "silent_mock_fallback_used", False)) or bool(
                getattr(coverage, "raw_payload_persisted", False)
            ):
                reject(
                    "entrypoint_coverage_refs",
                    coverage_ref,
                    "platform row source cannot use mock fallback or persist raw payloads",
                )
            source_qros = tuple(_text(ref) for ref in getattr(coverage, "qro_refs", ()) or ())
            source_commands = tuple(
                _text(ref)
                for ref in getattr(coverage, "research_graph_command_refs", ()) or ()
            )
            if source_qros != (_text(row.record.qro_ref),) or source_commands != (
                _text(row.record.research_graph_ref),
            ):
                reject(
                    "entrypoint_coverage_refs",
                    coverage_ref,
                    f"platform row {row.m_row} source lineage does not bind its exact QRO/Graph pair",
                )
            lifecycle_refs = tuple(
                _text(ref) for ref in getattr(coverage, "lifecycle_refs", ()) or ()
            )
            if _text(row.record.lifecycle_ref) not in lifecycle_refs:
                reject(
                    "lifecycle_refs",
                    coverage_ref,
                    f"platform row {row.m_row} source lineage does not bind its lifecycle ref",
                )
            evidence_refs = set(
                _text(ref) for ref in getattr(coverage, "evidence_refs", ()) or ()
            )
            if not set(_text(ref) for ref in row.record.evidence_refs).issubset(evidence_refs):
                reject(
                    "test_refs",
                    coverage_ref,
                    f"platform row {row.m_row} source lineage omits row evidence",
                )
            row_validation_refs = tuple(
                _text(ref) for ref in getattr(coverage, "validation_refs", ()) or ()
            )
            if (
                len(row_validation_refs) != len(set(row_validation_refs))
                or not any(
                    ref.startswith("goal_validation_receipt:")
                    for ref in row_validation_refs
                )
            ):
                reject(
                    "test_refs",
                    coverage_ref,
                    f"platform row {row.m_row} requires a unique durable GOAL validation receipt",
                )
            validation_refs.extend(row_validation_refs)
        expected = platform_closure_semantic_material(
            receipt,
            coverage_refs=record.entrypoint_coverage_refs,
            validation_refs=tuple(dict.fromkeys(validation_refs)),
        )
        if record.subject_ref != expected.subject_ref:
            reject("subject_ref", record.subject_ref, "section 14 subject must content-bind current receipt")
        for field_name in (
            "producer_refs",
            "store_refs",
            "consumer_refs",
            "gate_verdict_refs",
            "test_refs",
        ):
            actual = tuple(getattr(record, field_name))
            wanted = tuple(getattr(expected, field_name))
            if actual != wanted:
                reject(
                    field_name,
                    ",".join(actual),
                    f"{field_name} must exactly equal the current section 14 closure material",
                )
        return GoalSemanticDecision(not violations, tuple(violations))


__all__ = [
    "PLATFORM_CLOSURE_ENTRYPOINT_REF",
    "PLATFORM_CLOSURE_GOAL_SECTIONS",
    "PLATFORM_CLOSURE_RECEIPT_VERSION",
    "PLATFORM_CLOSURE_SCHEMA_VERSION",
    "PersistentPlatformClosureRegistry",
    "PlatformClosureCommitUncertain",
    "PlatformClosureDecision",
    "PlatformClosureError",
    "PlatformClosureReceipt",
    "PlatformClosureRDPState",
    "PlatformClosureRowState",
    "PlatformClosureSourceBinding",
    "PlatformClosureSectionAdapter",
    "PlatformClosureSemanticMaterial",
    "PlatformClosureSnapshot",
    "PlatformClosureViolation",
    "PlatformManifestResolver",
    "PlatformCoverageResolver",
    "PlatformRDPResolver",
    "platform_closure_receipt_from_dict",
    "platform_closure_receipt_identity",
    "platform_closure_rdp_state",
    "platform_closure_semantic_material",
    "platform_closure_snapshot_from_dict",
    "validate_platform_closure_receipt_shape",
    "validate_platform_closure_snapshot",
]
