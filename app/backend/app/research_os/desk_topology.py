"""Durable, owner-scoped proof for the GOAL §2 nine-desk topology.

The ledger stores projections and completed handoffs, but never treats their
presence as proof.  A current receipt is derived only after the injected,
typed read-only resolvers re-confirm every reference and its revision token.
"""

from __future__ import annotations

import json
import os
import tempfile
import threading
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Callable, Mapping

from ..cross_process_lock import acquire_exclusive_fd
from ..lineage.ids import content_hash
from .desk_projection import DESK_EDITABLE_ASSETS, DeskName, DeskProjectionRecord
from .goal_coverage import (
    PersistentGoalEntrypointCoverageRegistry,
    strict_current_entrypoint_coverage,
)
from .goal_semantics import (
    GoalSectionSemanticProofRecord,
    GoalSemanticDecision,
    GoalSemanticViolation,
)


DESK_TOPOLOGY_VERSION = "desk_topology.v1"
DESK_HANDOFF_VERSION = "desk_topology_handoff.v1"
DESK_RECEIPT_VERSION = "desk_topology_receipt.v1"
CANONICAL_DESKS = tuple(item.value for item in DeskName)
DESK_TOPOLOGY_ENTRYPOINTS = {
    "api": "api:goal.desk_topology.current",
    "agent_shell": "agent_shell:goal.desk_topology.current",
}

PROJECTION_REF_FIELDS: dict[str, str] = {
    "typed_canvas": "typed_canvas_ref",
    "agent_shell": "agent_shell_ref",
    "rag_projection": "rag_projection_ref",
    "math_projection": "math_projection_ref",
    "asset_inspector": "asset_inspector_ref",
    "tool_permission": "tool_permission_ref",
}


def _token(value: Any) -> str:
    return str(value or "").strip()


def _tokens(value: Any) -> tuple[str, ...]:
    if value is None:
        return ()
    values = value if isinstance(value, (tuple, list, set, frozenset)) else (value,)
    return tuple(_token(item) for item in values if _token(item))


def _desk(value: DeskName | str) -> str:
    return value.value if isinstance(value, DeskName) else _token(value)


def _hash(prefix: str, payload: Mapping[str, Any]) -> str:
    return prefix + content_hash(dict(payload))


@dataclass(frozen=True)
class ResolvedDeskReference:
    """Exact current state returned by one typed reference resolver."""

    ref: str
    owner_user_id: str
    kind: str
    desk: str
    revision_hash: str
    current: bool = True
    editable_asset_types: tuple[str, ...] = ()
    canonical_command_types: tuple[str, ...] = ()
    current_ref: str = ""

    def __post_init__(self) -> None:
        for name in ("ref", "owner_user_id", "kind", "desk", "revision_hash", "current_ref"):
            object.__setattr__(self, name, _token(getattr(self, name)))
        object.__setattr__(self, "editable_asset_types", _tokens(self.editable_asset_types))
        object.__setattr__(self, "canonical_command_types", _tokens(self.canonical_command_types))


@dataclass(frozen=True)
class ResolvedHandoffCommand:
    """Current command projection used to derive, not assert, a handoff."""

    command_ref: str
    owner_user_id: str
    command_type: str
    target_desk: str
    handoff_id: str
    from_desk: str
    to_desk: str
    capability_ref: str
    revision_hash: str
    current: bool = True
    produced_qro_ref: str = ""
    evidence_refs: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        for name in (
            "command_ref",
            "owner_user_id",
            "command_type",
            "target_desk",
            "handoff_id",
            "from_desk",
            "to_desk",
            "capability_ref",
            "revision_hash",
            "produced_qro_ref",
        ):
            object.__setattr__(self, name, _token(getattr(self, name)))
        object.__setattr__(self, "evidence_refs", _tokens(self.evidence_refs))


ReferenceResolver = Callable[[str, str], ResolvedDeskReference]
CommandResolver = Callable[[str, str], ResolvedHandoffCommand]


@dataclass(frozen=True)
class DeskRefBinding:
    kind: str
    ref: str
    revision_hash: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "kind", _token(self.kind))
        object.__setattr__(self, "ref", _token(self.ref))
        object.__setattr__(self, "revision_hash", _token(self.revision_hash))


@dataclass(frozen=True)
class DeskProjectionSnapshot:
    projection_ref: str
    desk: str
    source_of_truth_refs: tuple[str, ...]
    typed_canvas_ref: str
    agent_shell_ref: str
    rag_projection_ref: str
    math_projection_ref: str
    asset_inspector_ref: str
    tool_permission_ref: str
    editable_asset_types: tuple[str, ...]
    canonical_command_types: tuple[str, ...]
    canonical_command_capability_refs: tuple[str, ...]
    ref_bindings: tuple[DeskRefBinding, ...]
    independent_truth_ref: str = ""
    consistency_projection_ref: str = ""
    claims_institutional_method: bool = False

    def __post_init__(self) -> None:
        for name in (
            "projection_ref",
            "desk",
            "typed_canvas_ref",
            "agent_shell_ref",
            "rag_projection_ref",
            "math_projection_ref",
            "asset_inspector_ref",
            "tool_permission_ref",
            "independent_truth_ref",
            "consistency_projection_ref",
        ):
            object.__setattr__(self, name, _token(getattr(self, name)))
        for name in (
            "source_of_truth_refs",
            "editable_asset_types",
            "canonical_command_types",
            "canonical_command_capability_refs",
        ):
            object.__setattr__(self, name, _tokens(getattr(self, name)))
        object.__setattr__(
            self,
            "ref_bindings",
            tuple(
                item if isinstance(item, DeskRefBinding) else DeskRefBinding(**item)
                for item in self.ref_bindings
            ),
        )

    @property
    def canonical_projection_ref(self) -> str:
        return _hash(
            "desk_projection:",
            {
                key: value
                for key, value in asdict(self).items()
                if key != "projection_ref"
            },
        )


@dataclass(frozen=True)
class DeskTopologyRecord:
    topology_ref: str
    owner_user_id: str
    revision: int
    previous_topology_ref: str
    projections: tuple[DeskProjectionSnapshot, ...]
    topology_version: str = DESK_TOPOLOGY_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(self, "topology_ref", _token(self.topology_ref))
        object.__setattr__(self, "owner_user_id", _token(self.owner_user_id))
        object.__setattr__(self, "previous_topology_ref", _token(self.previous_topology_ref))
        object.__setattr__(
            self,
            "projections",
            tuple(
                item if isinstance(item, DeskProjectionSnapshot) else _projection_from_dict(item)
                for item in self.projections
            ),
        )

    @property
    def canonical_topology_ref(self) -> str:
        return _hash(
            "desk_topology:",
            {
                "owner_user_id": self.owner_user_id,
                "revision": self.revision,
                "previous_topology_ref": self.previous_topology_ref,
                "projection_refs": tuple(item.projection_ref for item in self.projections),
                "topology_version": self.topology_version,
            },
        )


@dataclass(frozen=True)
class CompletedDeskHandoffRecord:
    handoff_ref: str
    owner_user_id: str
    topology_ref: str
    handoff_id: str
    from_desk: str
    to_desk: str
    open_command_ref: str
    resolution_command_ref: str
    open_command_revision_hash: str
    resolution_command_revision_hash: str
    produced_qro_ref: str
    produced_qro_revision_hash: str
    evidence_refs: tuple[str, ...]
    evidence_bindings: tuple[DeskRefBinding, ...]
    handoff_version: str = DESK_HANDOFF_VERSION

    def __post_init__(self) -> None:
        for name in (
            "handoff_ref",
            "owner_user_id",
            "topology_ref",
            "handoff_id",
            "from_desk",
            "to_desk",
            "open_command_ref",
            "resolution_command_ref",
            "open_command_revision_hash",
            "resolution_command_revision_hash",
            "produced_qro_ref",
            "produced_qro_revision_hash",
        ):
            object.__setattr__(self, name, _token(getattr(self, name)))
        object.__setattr__(self, "evidence_refs", _tokens(self.evidence_refs))
        object.__setattr__(
            self,
            "evidence_bindings",
            tuple(
                item if isinstance(item, DeskRefBinding) else DeskRefBinding(**item)
                for item in self.evidence_bindings
            ),
        )

    @property
    def canonical_handoff_ref(self) -> str:
        return _hash(
            "desk_handoff_receipt:",
            {
                key: value
                for key, value in asdict(self).items()
                if key != "handoff_ref"
            },
        )


@dataclass(frozen=True)
class DeskTopologyReceipt:
    receipt_ref: str
    owner_user_id: str
    topology_ref: str
    handoff_refs: tuple[str, ...]
    receipt_version: str = DESK_RECEIPT_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(self, "receipt_ref", _token(self.receipt_ref))
        object.__setattr__(self, "owner_user_id", _token(self.owner_user_id))
        object.__setattr__(self, "topology_ref", _token(self.topology_ref))
        object.__setattr__(self, "handoff_refs", _tokens(self.handoff_refs))

    @property
    def canonical_receipt_ref(self) -> str:
        return _hash(
            "desk_topology_receipt:",
            {
                "owner_user_id": self.owner_user_id,
                "topology_ref": self.topology_ref,
                "handoff_refs": self.handoff_refs,
                "receipt_version": self.receipt_version,
            },
        )


@dataclass(frozen=True)
class DeskTopologyViolation:
    code: str
    message: str
    field: str = ""
    ref: str = ""


@dataclass(frozen=True)
class DeskTopologyDecision:
    accepted: bool
    violations: tuple[DeskTopologyViolation, ...]


def _projection_from_dict(data: Mapping[str, Any]) -> DeskProjectionSnapshot:
    return DeskProjectionSnapshot(
        projection_ref=data.get("projection_ref", ""),
        desk=data.get("desk", ""),
        source_of_truth_refs=tuple(data.get("source_of_truth_refs") or ()),
        typed_canvas_ref=data.get("typed_canvas_ref", ""),
        agent_shell_ref=data.get("agent_shell_ref", ""),
        rag_projection_ref=data.get("rag_projection_ref", ""),
        math_projection_ref=data.get("math_projection_ref", ""),
        asset_inspector_ref=data.get("asset_inspector_ref", ""),
        tool_permission_ref=data.get("tool_permission_ref", ""),
        editable_asset_types=tuple(data.get("editable_asset_types") or ()),
        canonical_command_types=tuple(data.get("canonical_command_types") or ()),
        canonical_command_capability_refs=tuple(
            data.get("canonical_command_capability_refs") or ()
        ),
        ref_bindings=tuple(data.get("ref_bindings") or ()),
        independent_truth_ref=data.get("independent_truth_ref", ""),
        consistency_projection_ref=data.get("consistency_projection_ref", ""),
        claims_institutional_method=bool(data.get("claims_institutional_method", False)),
    )


def _topology_from_dict(data: Mapping[str, Any]) -> DeskTopologyRecord:
    return DeskTopologyRecord(
        topology_ref=data.get("topology_ref", ""),
        owner_user_id=data.get("owner_user_id", ""),
        revision=int(data.get("revision") or 0),
        previous_topology_ref=data.get("previous_topology_ref", ""),
        projections=tuple(data.get("projections") or ()),
        topology_version=data.get("topology_version", DESK_TOPOLOGY_VERSION),
    )


def _handoff_from_dict(data: Mapping[str, Any]) -> CompletedDeskHandoffRecord:
    return CompletedDeskHandoffRecord(
        handoff_ref=data.get("handoff_ref", ""),
        owner_user_id=data.get("owner_user_id", ""),
        topology_ref=data.get("topology_ref", ""),
        handoff_id=data.get("handoff_id", ""),
        from_desk=data.get("from_desk", ""),
        to_desk=data.get("to_desk", ""),
        open_command_ref=data.get("open_command_ref", ""),
        resolution_command_ref=data.get("resolution_command_ref", ""),
        open_command_revision_hash=data.get("open_command_revision_hash", ""),
        resolution_command_revision_hash=data.get("resolution_command_revision_hash", ""),
        produced_qro_ref=data.get("produced_qro_ref", ""),
        produced_qro_revision_hash=data.get("produced_qro_revision_hash", ""),
        evidence_refs=tuple(data.get("evidence_refs") or ()),
        evidence_bindings=tuple(data.get("evidence_bindings") or ()),
        handoff_version=data.get("handoff_version", DESK_HANDOFF_VERSION),
    )


def _receipt_from_dict(data: Mapping[str, Any]) -> DeskTopologyReceipt:
    return DeskTopologyReceipt(
        receipt_ref=data.get("receipt_ref", ""),
        owner_user_id=data.get("owner_user_id", ""),
        topology_ref=data.get("topology_ref", ""),
        handoff_refs=tuple(data.get("handoff_refs") or ()),
        receipt_version=data.get("receipt_version", DESK_RECEIPT_VERSION),
    )


class PersistentDeskTopologyRegistry:
    """Append-only schema-v2 ledger with live, typed current validation."""

    def __init__(
        self,
        path: str | Path,
        *,
        reference_resolvers: Mapping[str, ReferenceResolver],
        command_resolver: CommandResolver,
    ) -> None:
        required = set(PROJECTION_REF_FIELDS) | {
            "canonical_command_capability",
            "qro",
            "handoff_evidence",
        }
        missing = required - set(reference_resolvers)
        if missing:
            raise ValueError(
                "desk topology requires typed resolvers; missing " + ",".join(sorted(missing))
            )
        self._path = Path(path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._lock_path = self._path.with_name(f".{self._path.name}.lock")
        self._reference_resolvers = dict(reference_resolvers)
        self._command_resolver = command_resolver
        self._lock = threading.RLock()
        self._topologies: dict[tuple[str, str], DeskTopologyRecord] = {}
        self._handoffs: dict[tuple[str, str], CompletedDeskHandoffRecord] = {}
        self._receipts: dict[tuple[str, str], DeskTopologyReceipt] = {}
        self._legacy_quarantined_count = 0
        self._load_existing()

    @property
    def path(self) -> Path:
        return self._path

    @property
    def legacy_quarantined_count(self) -> int:
        return self._legacy_quarantined_count

    @staticmethod
    def _owner(value: Any) -> str:
        owner = _token(value)
        if not owner:
            raise ValueError("desk topology owner_user_id is required")
        return owner

    def _resolve_ref(
        self,
        kind: str,
        ref: str,
        owner: str,
        *,
        desk: str = "",
    ) -> ResolvedDeskReference:
        try:
            state = self._reference_resolvers[kind](ref, owner)
        except Exception as exc:  # noqa: BLE001 - typed evidence fails closed.
            raise ValueError(f"desk topology {kind} ref is not resolvable: {ref}") from exc
        if not isinstance(state, ResolvedDeskReference):
            raise ValueError(f"desk topology {kind} resolver returned an untyped result")
        if (
            state.ref != ref
            or state.owner_user_id != owner
            or state.kind != kind
            or not state.current
            or not state.revision_hash
            or state.current_ref != ref
        ):
            raise ValueError(f"desk topology {kind} ref is not exact/current: {ref}")
        if desk and state.desk != desk:
            raise ValueError(f"desk topology {kind} ref desk mismatch: {ref}")
        return state

    def _capture_projection(
        self,
        owner: str,
        projection: DeskProjectionRecord,
        capability_refs: tuple[str, ...],
    ) -> DeskProjectionSnapshot:
        desk = _desk(projection.desk)
        if desk not in CANONICAL_DESKS:
            raise ValueError(f"unknown desk projection: {desk}")
        if tuple(projection.source_of_truth_refs) != ("research_graph",):
            raise ValueError("desk projection must have Research Graph as its sole truth source")
        if _token(projection.independent_truth_ref):
            raise ValueError("desk projection cannot carry an independent truth source")
        allowed = tuple(sorted(DESK_EDITABLE_ASSETS[desk]))
        editable = _tokens(projection.editable_asset_types)
        if editable != allowed:
            raise ValueError(f"desk editable asset types must equal the canonical allowlist: {desk}")
        command_types = _tokens(projection.canonical_command_types)
        if not command_types or len(command_types) != len(set(command_types)):
            raise ValueError(f"desk canonical command types must be nonempty and unique: {desk}")
        capability_refs = _tokens(capability_refs)
        if not capability_refs or len(capability_refs) != len(set(capability_refs)):
            raise ValueError(f"desk command capability refs must be nonempty and unique: {desk}")

        bindings: list[DeskRefBinding] = []
        for kind, field_name in PROJECTION_REF_FIELDS.items():
            ref = _token(getattr(projection, field_name))
            if not ref:
                raise ValueError(f"desk projection required ref missing: {desk}:{field_name}")
            state = self._resolve_ref(kind, ref, owner, desk=desk)
            bindings.append(DeskRefBinding(kind, ref, state.revision_hash))

        permission = self._resolve_ref(
            "tool_permission", _token(projection.tool_permission_ref), owner, desk=desk
        )
        if permission.editable_asset_types != allowed:
            raise ValueError(f"desk tool permission allowlist mismatch: {desk}")

        resolved_command_types: list[str] = []
        for ref in capability_refs:
            state = self._resolve_ref(
                "canonical_command_capability", ref, owner, desk=desk
            )
            bindings.append(
                DeskRefBinding("canonical_command_capability", ref, state.revision_hash)
            )
            resolved_command_types.extend(state.canonical_command_types)
        if tuple(resolved_command_types) != command_types:
            raise ValueError(f"desk command capability types mismatch: {desk}")

        consistency_ref = _token(projection.consistency_projection_ref)
        if projection.claims_institutional_method and not consistency_ref:
            raise ValueError(f"institutional desk projection lacks consistency ref: {desk}")
        if consistency_ref:
            if "consistency_projection" not in self._reference_resolvers:
                raise ValueError("desk topology consistency projection resolver is unavailable")
            state = self._resolve_ref(
                "consistency_projection", consistency_ref, owner, desk=desk
            )
            bindings.append(
                DeskRefBinding("consistency_projection", consistency_ref, state.revision_hash)
            )

        snapshot = DeskProjectionSnapshot(
            projection_ref="",
            desk=desk,
            source_of_truth_refs=("research_graph",),
            typed_canvas_ref=_token(projection.typed_canvas_ref),
            agent_shell_ref=_token(projection.agent_shell_ref),
            rag_projection_ref=_token(projection.rag_projection_ref),
            math_projection_ref=_token(projection.math_projection_ref),
            asset_inspector_ref=_token(projection.asset_inspector_ref),
            tool_permission_ref=_token(projection.tool_permission_ref),
            editable_asset_types=editable,
            canonical_command_types=command_types,
            canonical_command_capability_refs=capability_refs,
            ref_bindings=tuple(bindings),
            independent_truth_ref="",
            consistency_projection_ref=consistency_ref,
            claims_institutional_method=projection.claims_institutional_method,
        )
        return DeskProjectionSnapshot(
            **{**asdict(snapshot), "projection_ref": snapshot.canonical_projection_ref}
        )

    def _projection_violations(
        self,
        owner: str,
        projection: DeskProjectionSnapshot,
    ) -> list[DeskTopologyViolation]:
        violations: list[DeskTopologyViolation] = []

        def add(code: str, message: str, field: str = "", ref: str = "") -> None:
            violations.append(DeskTopologyViolation(code, message, field, ref))

        desk = projection.desk
        if projection.projection_ref != projection.canonical_projection_ref:
            add("desk_projection_identity_mismatch", "projection identity is not canonical", "projection_ref")
        if desk not in CANONICAL_DESKS:
            add("desk_projection_unknown_desk", "projection desk is not canonical", "desk", desk)
            return violations
        if projection.source_of_truth_refs != ("research_graph",) or projection.independent_truth_ref:
            add("desk_projection_independent_truth", "Research Graph must be the sole truth source")
        allowed = tuple(sorted(DESK_EDITABLE_ASSETS[desk]))
        if projection.editable_asset_types != allowed:
            add("desk_projection_editable_allowlist_mismatch", "editable allowlist drifted", "editable_asset_types")
        expected_bindings = {
            (item.kind, item.ref): item.revision_hash for item in projection.ref_bindings
        }
        if len(expected_bindings) != len(projection.ref_bindings):
            add("desk_projection_duplicate_binding", "projection bindings must be unique", "ref_bindings")
        for kind, field_name in PROJECTION_REF_FIELDS.items():
            ref = _token(getattr(projection, field_name))
            try:
                state = self._resolve_ref(kind, ref, owner, desk=desk)
            except ValueError:
                add("desk_projection_ref_not_current", "typed projection ref is not current", field_name, ref)
                continue
            if expected_bindings.get((kind, ref)) != state.revision_hash:
                add("desk_projection_ref_revision_drift", "typed projection ref revision drifted", field_name, ref)
            if kind == "tool_permission" and state.editable_asset_types != allowed:
                add("desk_projection_permission_policy_drift", "tool permission allowlist drifted", field_name, ref)
        resolved_types: list[str] = []
        for ref in projection.canonical_command_capability_refs:
            try:
                state = self._resolve_ref("canonical_command_capability", ref, owner, desk=desk)
            except ValueError:
                add("desk_projection_command_capability_not_current", "command capability is not current", "canonical_command_capability_refs", ref)
                continue
            if expected_bindings.get(("canonical_command_capability", ref)) != state.revision_hash:
                add("desk_projection_command_capability_drift", "command capability revision drifted", "canonical_command_capability_refs", ref)
            resolved_types.extend(state.canonical_command_types)
        if tuple(resolved_types) != projection.canonical_command_types:
            add("desk_projection_command_types_drift", "command capability types drifted", "canonical_command_types")
        if projection.claims_institutional_method and not projection.consistency_projection_ref:
            add("desk_projection_consistency_missing", "institutional claim lacks consistency projection")
        if projection.consistency_projection_ref:
            ref = projection.consistency_projection_ref
            try:
                state = self._resolve_ref("consistency_projection", ref, owner, desk=desk)
            except (KeyError, ValueError):
                add("desk_projection_consistency_not_current", "consistency projection is not current", "consistency_projection_ref", ref)
            else:
                if expected_bindings.get(("consistency_projection", ref)) != state.revision_hash:
                    add("desk_projection_consistency_drift", "consistency projection revision drifted", "consistency_projection_ref", ref)
        return violations

    def validate_topology_current(
        self,
        record: DeskTopologyRecord,
        *,
        owner_user_id: str,
    ) -> DeskTopologyDecision:
        owner = self._owner(owner_user_id)
        violations: list[DeskTopologyViolation] = []
        if record.owner_user_id != owner:
            violations.append(DeskTopologyViolation("desk_topology_owner_mismatch", "topology owner mismatch"))
        if record.topology_version != DESK_TOPOLOGY_VERSION:
            violations.append(DeskTopologyViolation("desk_topology_version_unsupported", "topology version unsupported"))
        if record.topology_ref != record.canonical_topology_ref:
            violations.append(DeskTopologyViolation("desk_topology_identity_mismatch", "topology identity mismatch"))
        desks = tuple(item.desk for item in record.projections)
        if len(desks) != len(CANONICAL_DESKS) or frozenset(desks) != frozenset(CANONICAL_DESKS):
            violations.append(DeskTopologyViolation("desk_topology_nine_desk_mismatch", "topology must contain exactly the nine canonical desks"))
        if tuple(sorted(desks)) != desks:
            violations.append(DeskTopologyViolation("desk_topology_projection_order_mismatch", "topology projections must be canonical sorted order"))
        for projection in record.projections:
            violations.extend(self._projection_violations(owner, projection))
        try:
            current = self.current_topology(owner_user_id=owner)
        except KeyError:
            current = None
        if current is not None and current.topology_ref != record.topology_ref:
            violations.append(DeskTopologyViolation("desk_topology_not_current", "topology revision is stale", ref=record.topology_ref))
        return DeskTopologyDecision(not violations, tuple(violations))

    def record_topology(
        self,
        *,
        owner_user_id: str,
        projections: tuple[DeskProjectionRecord, ...],
        capability_refs_by_desk: Mapping[str, tuple[str, ...]],
    ) -> DeskTopologyRecord:
        owner = self._owner(owner_user_id)
        with self._lock:
            self.refresh()
            if len(projections) != len(CANONICAL_DESKS):
                raise ValueError("desk topology requires exactly nine projection records")
            desks = tuple(_desk(item.desk) for item in projections)
            if len(set(desks)) != len(CANONICAL_DESKS) or set(desks) != set(CANONICAL_DESKS):
                raise ValueError("desk topology projection desks must equal the nine canonical desks")
            if set(capability_refs_by_desk) != set(CANONICAL_DESKS):
                raise ValueError("desk topology capability map must equal the nine canonical desks")
            snapshots = tuple(
                sorted(
                    (
                        self._capture_projection(
                            owner,
                            item,
                            tuple(capability_refs_by_desk[_desk(item.desk)]),
                        )
                        for item in projections
                    ),
                    key=lambda item: item.desk,
                )
            )
            try:
                current = self.current_topology(owner_user_id=owner)
            except KeyError:
                current = None
            if current is not None and current.projections == snapshots:
                return current
            draft = DeskTopologyRecord(
                topology_ref="",
                owner_user_id=owner,
                revision=(current.revision + 1 if current else 1),
                previous_topology_ref=(current.topology_ref if current else ""),
                projections=snapshots,
            )
            record = DeskTopologyRecord(
                **{**asdict(draft), "topology_ref": draft.canonical_topology_ref}
            )
            self._apply_event(
                {
                    "schema_version": 2,
                    "event_type": "desk_topology_recorded",
                    "owner_user_id": owner,
                    "topology": asdict(record),
                },
                persist=True,
            )
            return record

    def record_completed_handoff(
        self,
        *,
        owner_user_id: str,
        topology_ref: str,
        open_command_ref: str,
        resolution_command_ref: str,
    ) -> CompletedDeskHandoffRecord:
        owner = self._owner(owner_user_id)
        topology = self.topology(topology_ref, owner_user_id=owner)
        if not self.validate_topology_current(topology, owner_user_id=owner).accepted:
            raise ValueError("completed handoff requires the current valid topology")
        opened = self._command_resolver(open_command_ref, owner)
        resolved = self._command_resolver(resolution_command_ref, owner)
        if not isinstance(opened, ResolvedHandoffCommand) or not isinstance(resolved, ResolvedHandoffCommand):
            raise ValueError("handoff command resolver returned an untyped result")
        if (
            opened.owner_user_id != owner
            or resolved.owner_user_id != owner
            or opened.command_ref != open_command_ref
            or resolved.command_ref != resolution_command_ref
            or opened.command_type != "open_handoff"
            or resolved.command_type != "resolve_handoff"
            or not opened.current
            or not resolved.current
            or not opened.revision_hash
            or not resolved.revision_hash
            or opened.handoff_id != resolved.handoff_id
            or opened.from_desk != resolved.from_desk
            or opened.to_desk != resolved.to_desk
            or opened.from_desk == opened.to_desk
            or opened.from_desk not in CANONICAL_DESKS
            or opened.to_desk not in CANONICAL_DESKS
            or opened.target_desk != opened.from_desk
            or resolved.target_desk != resolved.to_desk
            or not resolved.produced_qro_ref
            or not resolved.evidence_refs
        ):
            raise ValueError("handoff commands are incomplete, mixed, stale, or incorrectly linked")
        projections = {item.desk: item for item in topology.projections}
        if opened.capability_ref not in projections[opened.from_desk].canonical_command_capability_refs:
            raise ValueError("open handoff command capability is not registered for its desk")
        if resolved.capability_ref not in projections[resolved.to_desk].canonical_command_capability_refs:
            raise ValueError("resolution handoff command capability is not registered for its desk")

        qro = self._resolve_ref("qro", resolved.produced_qro_ref, owner, desk=resolved.to_desk)
        evidence_bindings = tuple(
            DeskRefBinding(
                "handoff_evidence",
                ref,
                self._resolve_ref("handoff_evidence", ref, owner).revision_hash,
            )
            for ref in resolved.evidence_refs
        )
        draft = CompletedDeskHandoffRecord(
            handoff_ref="",
            owner_user_id=owner,
            topology_ref=topology.topology_ref,
            handoff_id=opened.handoff_id,
            from_desk=opened.from_desk,
            to_desk=opened.to_desk,
            open_command_ref=opened.command_ref,
            resolution_command_ref=resolved.command_ref,
            open_command_revision_hash=opened.revision_hash,
            resolution_command_revision_hash=resolved.revision_hash,
            produced_qro_ref=qro.ref,
            produced_qro_revision_hash=qro.revision_hash,
            evidence_refs=resolved.evidence_refs,
            evidence_bindings=evidence_bindings,
        )
        record = CompletedDeskHandoffRecord(
            **{**asdict(draft), "handoff_ref": draft.canonical_handoff_ref}
        )
        with self._lock:
            self._apply_event(
                {
                    "schema_version": 2,
                    "event_type": "desk_handoff_completed",
                    "owner_user_id": owner,
                    "handoff": asdict(record),
                },
                persist=True,
            )
        return record

    def _handoff_violations(
        self,
        owner: str,
        record: CompletedDeskHandoffRecord,
        topology: DeskTopologyRecord,
    ) -> list[DeskTopologyViolation]:
        violations: list[DeskTopologyViolation] = []

        def add(code: str, message: str, field: str = "", ref: str = "") -> None:
            violations.append(DeskTopologyViolation(code, message, field, ref))

        if record.owner_user_id != owner or record.topology_ref != topology.topology_ref:
            add("desk_handoff_owner_or_topology_mismatch", "handoff owner/topology mismatch")
        if record.handoff_version != DESK_HANDOFF_VERSION or record.handoff_ref != record.canonical_handoff_ref:
            add("desk_handoff_identity_mismatch", "handoff identity/version mismatch")
        try:
            opened = self._command_resolver(record.open_command_ref, owner)
            resolved = self._command_resolver(record.resolution_command_ref, owner)
        except Exception:  # noqa: BLE001
            add("desk_handoff_command_not_current", "handoff command lookup failed")
            return violations
        if not isinstance(opened, ResolvedHandoffCommand) or not isinstance(resolved, ResolvedHandoffCommand):
            add("desk_handoff_command_untyped", "handoff command resolver returned untyped state")
            return violations
        expected = (
            owner,
            record.handoff_id,
            record.from_desk,
            record.to_desk,
        )
        if (
            (opened.owner_user_id, opened.handoff_id, opened.from_desk, opened.to_desk) != expected
            or (resolved.owner_user_id, resolved.handoff_id, resolved.from_desk, resolved.to_desk) != expected
            or opened.command_type != "open_handoff"
            or resolved.command_type != "resolve_handoff"
            or opened.target_desk != record.from_desk
            or resolved.target_desk != record.to_desk
            or not opened.current
            or not resolved.current
            or opened.revision_hash != record.open_command_revision_hash
            or resolved.revision_hash != record.resolution_command_revision_hash
            or resolved.produced_qro_ref != record.produced_qro_ref
            or resolved.evidence_refs != record.evidence_refs
        ):
            add("desk_handoff_command_linkage_drift", "handoff command linkage drifted")
        projections = {item.desk: item for item in topology.projections}
        from_projection = projections.get(record.from_desk)
        to_projection = projections.get(record.to_desk)
        if (
            from_projection is None
            or to_projection is None
            or opened.capability_ref
            not in from_projection.canonical_command_capability_refs
            or resolved.capability_ref
            not in to_projection.canonical_command_capability_refs
        ):
            add("desk_handoff_command_capability_drift", "handoff command capability is not current")
        try:
            qro = self._resolve_ref("qro", record.produced_qro_ref, owner, desk=record.to_desk)
        except ValueError:
            add("desk_handoff_qro_not_current", "produced QRO is not current", "produced_qro_ref", record.produced_qro_ref)
        else:
            if qro.revision_hash != record.produced_qro_revision_hash:
                add("desk_handoff_qro_revision_drift", "produced QRO revision drifted", "produced_qro_ref", record.produced_qro_ref)
        bindings = {(item.kind, item.ref): item.revision_hash for item in record.evidence_bindings}
        if len(bindings) != len(record.evidence_refs):
            add("desk_handoff_evidence_binding_mismatch", "handoff evidence bindings are not exact")
        for ref in record.evidence_refs:
            try:
                state = self._resolve_ref("handoff_evidence", ref, owner)
            except ValueError:
                add("desk_handoff_evidence_not_current", "handoff evidence is not current", "evidence_refs", ref)
            else:
                if bindings.get(("handoff_evidence", ref)) != state.revision_hash:
                    add("desk_handoff_evidence_revision_drift", "handoff evidence revision drifted", "evidence_refs", ref)
        return violations

    def build_current_receipt(self, *, owner_user_id: str) -> DeskTopologyReceipt:
        owner = self._owner(owner_user_id)
        topology = self.current_topology(owner_user_id=owner)
        decision = self.validate_topology_current(topology, owner_user_id=owner)
        if not decision.accepted:
            raise ValueError("current desk topology is not strictly valid")
        handoffs = tuple(
            sorted(
                (
                    item
                    for item in self.handoffs(owner_user_id=owner)
                    if item.topology_ref == topology.topology_ref
                ),
                key=lambda item: item.handoff_ref,
            )
        )
        participating: set[str] = set()
        for handoff in handoffs:
            violations = self._handoff_violations(owner, handoff, topology)
            if violations:
                raise ValueError("current desk handoff is not strictly valid")
            participating.update((handoff.from_desk, handoff.to_desk))
        if participating != set(CANONICAL_DESKS):
            raise ValueError("every canonical desk must participate in a completed handoff")
        draft = DeskTopologyReceipt(
            receipt_ref="",
            owner_user_id=owner,
            topology_ref=topology.topology_ref,
            handoff_refs=tuple(item.handoff_ref for item in handoffs),
        )
        return DeskTopologyReceipt(
            **{**asdict(draft), "receipt_ref": draft.canonical_receipt_ref}
        )

    def validate_current_receipt(
        self,
        record: DeskTopologyReceipt,
        *,
        owner_user_id: str,
    ) -> DeskTopologyDecision:
        owner = self._owner(owner_user_id)
        violations: list[DeskTopologyViolation] = []
        if record.owner_user_id != owner:
            violations.append(DeskTopologyViolation("desk_topology_receipt_owner_mismatch", "receipt owner mismatch"))
        if record.receipt_version != DESK_RECEIPT_VERSION or record.receipt_ref != record.canonical_receipt_ref:
            violations.append(DeskTopologyViolation("desk_topology_receipt_identity_mismatch", "receipt identity/version mismatch"))
        try:
            current = self.build_current_receipt(owner_user_id=owner)
        except (KeyError, ValueError):
            violations.append(DeskTopologyViolation("desk_topology_current_proof_unavailable", "current topology/handoff proof is unavailable"))
        else:
            if current != record:
                violations.append(DeskTopologyViolation("desk_topology_receipt_not_current", "receipt does not match current derived proof"))
        return DeskTopologyDecision(not violations, tuple(violations))

    def record_current_receipt(self, *, owner_user_id: str) -> DeskTopologyReceipt:
        owner = self._owner(owner_user_id)
        record = self.build_current_receipt(owner_user_id=owner)
        with self._lock:
            self._apply_event(
                {
                    "schema_version": 2,
                    "event_type": "desk_topology_receipt_recorded",
                    "owner_user_id": owner,
                    "receipt": asdict(record),
                },
                persist=True,
            )
        return record

    def topology(self, topology_ref: str, *, owner_user_id: str) -> DeskTopologyRecord:
        return self._topologies[(self._owner(owner_user_id), _token(topology_ref))]

    def current_topology(self, *, owner_user_id: str) -> DeskTopologyRecord:
        owner = self._owner(owner_user_id)
        records = [item for (row_owner, _), item in self._topologies.items() if row_owner == owner]
        if not records:
            raise KeyError(owner)
        return max(records, key=lambda item: item.revision)

    def handoffs(self, *, owner_user_id: str) -> list[CompletedDeskHandoffRecord]:
        owner = self._owner(owner_user_id)
        return [item for (row_owner, _), item in self._handoffs.items() if row_owner == owner]

    def receipt(self, receipt_ref: str, *, owner_user_id: str) -> DeskTopologyReceipt:
        return self._receipts[(self._owner(owner_user_id), _token(receipt_ref))]

    def receipts(self, *, owner_user_id: str) -> list[DeskTopologyReceipt]:
        owner = self._owner(owner_user_id)
        return [
            item
            for (row_owner, _), item in self._receipts.items()
            if row_owner == owner
        ]

    def refresh(self) -> None:
        with self._lock:
            self._topologies.clear()
            self._handoffs.clear()
            self._receipts.clear()
            self._legacy_quarantined_count = 0
            self._load_existing()

    def _load_existing(self) -> None:
        if not self._path.exists():
            return
        with self._path.open("r", encoding="utf-8") as fh:
            for line_no, line in enumerate(fh, start=1):
                if not line.strip():
                    continue
                try:
                    row = json.loads(line)
                    if row.get("schema_version") != 2:
                        self._legacy_quarantined_count += 1
                        continue
                    self._apply_event(row, persist=False)
                except Exception as exc:  # noqa: BLE001
                    raise ValueError(
                        f"invalid persisted desk topology event at {self._path}:{line_no}"
                    ) from exc

    def _apply_event(self, row: dict[str, Any], *, persist: bool) -> Any:
        if row.get("schema_version") != 2:
            raise ValueError("desk topology events require schema_version=2")
        owner = self._owner(row.get("owner_user_id"))
        event_type = row.get("event_type")
        if event_type == "desk_topology_recorded":
            raw = row.get("topology")
            record = _topology_from_dict(raw) if isinstance(raw, dict) else None
            if record is None or record.owner_user_id != owner or record.topology_ref != record.canonical_topology_ref:
                raise ValueError("invalid desk topology owner envelope or identity")
            key = (owner, record.topology_ref)
            existing_revision = next(
                (
                    item
                    for (row_owner, _), item in self._topologies.items()
                    if row_owner == owner and item.revision == record.revision
                ),
                None,
            )
            if existing_revision is not None and existing_revision != record:
                raise ValueError("desk topology revision collision")
            store = self._topologies
        elif event_type == "desk_handoff_completed":
            raw = row.get("handoff")
            record = _handoff_from_dict(raw) if isinstance(raw, dict) else None
            if record is None or record.owner_user_id != owner or record.handoff_ref != record.canonical_handoff_ref:
                raise ValueError("invalid desk handoff owner envelope or identity")
            key = (owner, record.handoff_ref)
            same_handoff = next(
                (
                    item
                    for (row_owner, _), item in self._handoffs.items()
                    if row_owner == owner
                    and item.topology_ref == record.topology_ref
                    and item.handoff_id == record.handoff_id
                ),
                None,
            )
            if same_handoff is not None and same_handoff != record:
                raise ValueError("desk handoff identity collision")
            store = self._handoffs
        elif event_type == "desk_topology_receipt_recorded":
            raw = row.get("receipt")
            record = _receipt_from_dict(raw) if isinstance(raw, dict) else None
            if record is None or record.owner_user_id != owner or record.receipt_ref != record.canonical_receipt_ref:
                raise ValueError("invalid desk topology receipt owner envelope or identity")
            key = (owner, record.receipt_ref)
            store = self._receipts
        else:
            raise ValueError("unknown desk topology event_type")
        existing = store.get(key)
        if existing is not None:
            if existing != record:
                raise ValueError("desk topology event identity collision")
            return existing
        if persist:
            self._append_event(row)
        store[key] = record
        return record

    def _append_event(self, row: dict[str, Any]) -> None:
        fd = os.open(self._lock_path, os.O_RDWR | os.O_CREAT, 0o600)
        held = None
        temp_path: str | None = None
        try:
            os.chmod(self._lock_path, 0o600)
            held = acquire_exclusive_fd(fd, timeout_seconds=30.0)
            existing_bytes = self._path.read_bytes() if self._path.exists() else b""
            serialized = json.dumps(
                row, ensure_ascii=False, sort_keys=True, separators=(",", ":")
            ).encode("utf-8") + b"\n"
            for line_no, line in enumerate(existing_bytes.splitlines(), start=1):
                if not line.strip():
                    continue
                existing = json.loads(line)
                if existing == row:
                    return
                if (
                    existing.get("schema_version") == 2
                    and existing.get("owner_user_id") == row.get("owner_user_id")
                    and existing.get("event_type") == row.get("event_type")
                ):
                    event_type = row["event_type"]
                    collision = False
                    if event_type == "desk_topology_recorded":
                        old = existing.get("topology") or {}
                        new = row.get("topology") or {}
                        collision = (
                            old.get("topology_ref") == new.get("topology_ref")
                            or old.get("revision") == new.get("revision")
                        )
                    elif event_type == "desk_handoff_completed":
                        old = existing.get("handoff") or {}
                        new = row.get("handoff") or {}
                        collision = (
                            old.get("handoff_ref") == new.get("handoff_ref")
                            or (
                                old.get("topology_ref") == new.get("topology_ref")
                                and old.get("handoff_id") == new.get("handoff_id")
                            )
                        )
                    elif event_type == "desk_topology_receipt_recorded":
                        old = existing.get("receipt") or {}
                        new = row.get("receipt") or {}
                        collision = old.get("receipt_ref") == new.get("receipt_ref")
                    if collision:
                        raise ValueError(
                            "desk topology disk identity/revision collision at "
                            f"{self._path}:{line_no}"
                        )
            prefix = existing_bytes
            if prefix and not prefix.endswith(b"\n"):
                prefix += b"\n"
            temp_fd, temp_path = tempfile.mkstemp(
                prefix=f".{self._path.name}.", suffix=".tmp", dir=self._path.parent
            )
            try:
                os.fchmod(temp_fd, 0o600)
                with os.fdopen(temp_fd, "wb") as fh:
                    fh.write(prefix)
                    fh.write(serialized)
                    fh.flush()
                    os.fsync(fh.fileno())
                os.replace(temp_path, self._path)
                temp_path = None
                directory_fd = os.open(self._path.parent, os.O_RDONLY)
                try:
                    os.fsync(directory_fd)
                finally:
                    os.close(directory_fd)
            except Exception:
                try:
                    os.close(temp_fd)
                except OSError:
                    pass
                raise
        finally:
            if temp_path is not None:
                try:
                    os.unlink(temp_path)
                except FileNotFoundError:
                    pass
            if held is not None:
                held.release()
            os.close(fd)


class DeskTopologySectionAdapter:
    """Prove GOAL §2 from one current nine-desk receipt and entry lineage."""

    def __init__(
        self,
        entrypoint_registry: PersistentGoalEntrypointCoverageRegistry,
        topology_registry: PersistentDeskTopologyRegistry,
    ) -> None:
        self._entrypoint_registry = entrypoint_registry
        self._topology_registry = topology_registry

    @staticmethod
    def _entry_source(record: Any) -> str:
        value = getattr(record, "entry_source", "")
        return _token(getattr(value, "value", value))

    def validate(
        self,
        record: GoalSectionSemanticProofRecord,
        *,
        owner: str,
    ) -> GoalSemanticDecision:
        violations: list[GoalSemanticViolation] = []

        def reject(field: str, ref: str, reason: str) -> None:
            violations.append(
                GoalSemanticViolation(
                    "goal_semantic_desk_topology_invalid",
                    reason,
                    field=field,
                    ref=ref,
                )
            )

        if record.section != "§2":
            reject("section", record.section, "desk topology adapter only supports §2")
            return GoalSemanticDecision(False, tuple(violations))
        if record.recorded_by != owner:
            reject(
                "recorded_by",
                record.recorded_by,
                "desk topology semantic proof owner mismatch",
            )
        if not record.claims_section_complete or record.unverified_residuals:
            reject(
                "claims_section_complete",
                record.proof_ref,
                "§2 completion requires an explicit complete claim with no residuals",
            )
        if len(record.entrypoint_coverage_refs) != 1:
            reject(
                "entrypoint_coverage_refs",
                ",".join(record.entrypoint_coverage_refs),
                "§2 requires exactly one canonical API or Agent Shell lineage",
            )
            return GoalSemanticDecision(False, tuple(violations))

        coverage_ref = record.entrypoint_coverage_refs[0]
        try:
            coverage = strict_current_entrypoint_coverage(
                self._entrypoint_registry,
                coverage_ref,
                owner=owner,
            )
        except (KeyError, LookupError, ValueError):
            reject(
                "entrypoint_coverage_refs",
                coverage_ref,
                "§2 entrypoint lineage is not persisted for owner",
            )
            return GoalSemanticDecision(False, tuple(violations))
        try:
            coverage_decision = self._entrypoint_registry.validate_real_backing(
                coverage
            )
        except Exception:  # noqa: BLE001 - current entrypoint proof fails closed.
            reject(
                "entrypoint_coverage_refs",
                coverage_ref,
                "§2 entrypoint current-backing validation raised",
            )
        else:
            if not bool(getattr(coverage_decision, "accepted", False)):
                reject(
                    "entrypoint_coverage_refs",
                    coverage_ref,
                    "§2 entrypoint lineage failed strict current backing",
                )

        source = self._entry_source(coverage)
        expected_entrypoint = DESK_TOPOLOGY_ENTRYPOINTS.get(source)
        if expected_entrypoint is None or coverage.entrypoint_ref != expected_entrypoint:
            reject(
                "entrypoint_coverage_refs",
                coverage_ref,
                "§2 requires the canonical current-topology API or Agent Shell entrypoint",
            )
        if "§2" not in set(coverage.goal_sections):
            reject(
                "entrypoint_coverage_refs",
                coverage_ref,
                "§2 entrypoint lineage does not cite §2",
            )

        receipt_refs = tuple(
            _token(ref)
            for ref in coverage.validation_refs
            if _token(ref).startswith("desk_topology_receipt:")
        )
        if len(receipt_refs) != 1 or len(set(receipt_refs)) != 1:
            reject(
                "gate_verdict_refs",
                ",".join(receipt_refs),
                "§2 entrypoint lineage must bind exactly one topology receipt",
            )
            return GoalSemanticDecision(False, tuple(violations))
        receipt_ref = receipt_refs[0]
        try:
            receipt = self._topology_registry.receipt(
                receipt_ref,
                owner_user_id=owner,
            )
        except (KeyError, LookupError, ValueError):
            reject(
                "gate_verdict_refs",
                receipt_ref,
                "§2 topology receipt is not persisted for owner",
            )
            return GoalSemanticDecision(False, tuple(violations))

        try:
            current_decision = self._topology_registry.validate_current_receipt(
                receipt,
                owner_user_id=owner,
            )
        except Exception:  # noqa: BLE001 - live topology validation fails closed.
            reject(
                "gate_verdict_refs",
                receipt_ref,
                "§2 topology receipt current validation raised",
            )
            return GoalSemanticDecision(False, tuple(violations))
        if not current_decision.accepted:
            codes = ",".join(
                sorted({item.code for item in current_decision.violations})
            )
            reject(
                "gate_verdict_refs",
                receipt_ref,
                "§2 topology receipt is no longer current"
                + (f": {codes}" if codes else ""),
            )

        try:
            topology = self._topology_registry.topology(
                receipt.topology_ref,
                owner_user_id=owner,
            )
            current_topology = self._topology_registry.current_topology(
                owner_user_id=owner
            )
        except (KeyError, LookupError, ValueError):
            reject(
                "store_refs",
                receipt.topology_ref,
                "§2 receipt topology is not persisted for owner",
            )
            return GoalSemanticDecision(False, tuple(violations))
        if current_topology.topology_ref != topology.topology_ref:
            reject(
                "store_refs",
                topology.topology_ref,
                "§2 receipt topology is not the current revision",
            )

        projection_desks = tuple(item.desk for item in topology.projections)
        if (
            len(projection_desks) != len(CANONICAL_DESKS)
            or len(set(projection_desks)) != len(CANONICAL_DESKS)
            or set(projection_desks) != set(CANONICAL_DESKS)
        ):
            reject(
                "store_refs",
                topology.topology_ref,
                "§2 topology does not contain exactly all nine canonical desks",
            )

        owner_handoffs = {
            item.handoff_ref: item
            for item in self._topology_registry.handoffs(owner_user_id=owner)
        }
        if (
            len(receipt.handoff_refs) != len(set(receipt.handoff_refs))
            or any(ref not in owner_handoffs for ref in receipt.handoff_refs)
        ):
            reject(
                "store_refs",
                receipt_ref,
                "§2 receipt handoffs are missing, duplicated, or recombined",
            )
            return GoalSemanticDecision(False, tuple(violations))
        handoffs = tuple(owner_handoffs[ref] for ref in receipt.handoff_refs)
        participating: set[str] = set()
        for handoff in handoffs:
            if (
                handoff.owner_user_id != owner
                or handoff.topology_ref != topology.topology_ref
            ):
                reject(
                    "store_refs",
                    handoff.handoff_ref,
                    "§2 completed handoff owner/topology linkage was recombined",
                )
            participating.update((handoff.from_desk, handoff.to_desk))
        if participating != set(CANONICAL_DESKS):
            reject(
                "store_refs",
                receipt_ref,
                "§2 requires every canonical desk to participate in a completed handoff",
            )

        expected_subject = (
            f"goal_section:§2:desk_topology_receipt:{receipt.receipt_ref}"
        )
        expected_producers = {
            *(
                ref
                for projection in topology.projections
                for ref in projection.canonical_command_capability_refs
            ),
            *(handoff.open_command_ref for handoff in handoffs),
            *(handoff.resolution_command_ref for handoff in handoffs),
            *(handoff.produced_qro_ref for handoff in handoffs),
            *(ref for handoff in handoffs for ref in handoff.evidence_refs),
        }
        expected_stores = {
            receipt.receipt_ref,
            topology.topology_ref,
            *(projection.projection_ref for projection in topology.projections),
            *(handoff.handoff_ref for handoff in handoffs),
        }
        expected_consumers = {
            coverage.entrypoint_ref,
            *(projection.typed_canvas_ref for projection in topology.projections),
            *(projection.agent_shell_ref for projection in topology.projections),
            *(projection.rag_projection_ref for projection in topology.projections),
            *(projection.math_projection_ref for projection in topology.projections),
            *(projection.asset_inspector_ref for projection in topology.projections),
        }
        expected_gates = {receipt.receipt_ref}
        expected_tests = {
            receipt.receipt_ref,
            "desk_topology_current_check:"
            f"{receipt.receipt_ref}:{topology.topology_ref}",
            *(
                f"desk_projection_current_check:{receipt.receipt_ref}:"
                f"{projection.projection_ref}"
                for projection in topology.projections
            ),
            *(
                f"desk_handoff_current_check:{receipt.receipt_ref}:"
                f"{handoff.handoff_ref}"
                for handoff in handoffs
            ),
        }

        if record.subject_ref != expected_subject:
            reject(
                "subject_ref",
                record.subject_ref,
                "§2 subject must bind the exact current topology receipt",
            )
        for field_name, expected in (
            ("producer_refs", expected_producers),
            ("store_refs", expected_stores),
            ("consumer_refs", expected_consumers),
            ("gate_verdict_refs", expected_gates),
            ("test_refs", expected_tests),
        ):
            actual = tuple(getattr(record, field_name))
            if len(actual) != len(set(actual)) or set(actual) != expected:
                reject(
                    field_name,
                    ",".join(sorted(actual)),
                    f"{field_name} must exactly match the current §2 topology receipt",
                )

        return GoalSemanticDecision(not violations, tuple(violations))


__all__ = [
    "CANONICAL_DESKS",
    "CompletedDeskHandoffRecord",
    "DeskProjectionSnapshot",
    "DeskRefBinding",
    "DeskTopologySectionAdapter",
    "DeskTopologyDecision",
    "DeskTopologyRecord",
    "DeskTopologyReceipt",
    "DeskTopologyViolation",
    "PersistentDeskTopologyRegistry",
    "ResolvedDeskReference",
    "ResolvedHandoffCommand",
]
