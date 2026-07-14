"""Server-derived current producers for the GOAL §14 M1-M21 manifest.

The public manifest API must never accept authoritative capability refs from a
caller.  A registered row producer reads typed owner-scoped stores and returns
one content-bound snapshot.  This registry resolves every row twice before a
manifest write; missing, unstable, placeholder, or recombined sources fail
closed.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from typing import Any, Callable

from .platform_coverage import (
    REQUIRED_PLATFORM_ROWS,
    PersistentPlatformCoverageRegistry,
    PlatformCapabilityRecord,
    platform_capability_record_to_dict,
    validate_platform_capability,
)
from .ref_resolution import is_placeholder_ref


def _text(value: Any) -> str:
    return str(value or "").strip()


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _content_hash(value: Any) -> str:
    return "sha256:" + hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _valid_hash(value: Any) -> bool:
    token = _text(value).lower()
    return (
        token.startswith("sha256:")
        and len(token) == 71
        and all(char in "0123456789abcdef" for char in token[7:])
    )


def _row_value(record: PlatformCapabilityRecord) -> str:
    value = getattr(record.m_row, "value", record.m_row)
    return _text(value)


def _record_refs(record: PlatformCapabilityRecord) -> tuple[str, ...]:
    return tuple(
        dict.fromkeys(
            _text(ref)
            for ref in (
                record.qro_ref,
                record.research_graph_ref,
                record.lifecycle_ref,
                record.governance_ref,
                record.rag_ref,
                record.math_spine_ref,
                *record.evidence_refs,
                *(item.ref for item in record.specific_refs),
            )
            if _text(ref)
        )
    )


@dataclass(frozen=True)
class PlatformRowSourceState:
    source_kind: str
    source_ref: str
    state_hash: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "source_kind", _text(self.source_kind))
        object.__setattr__(self, "source_ref", _text(self.source_ref))
        object.__setattr__(self, "state_hash", _text(self.state_hash))


def platform_row_source_state(
    *,
    source_kind: str,
    source_ref: str,
    state_payload: Any,
) -> PlatformRowSourceState:
    kind = _text(source_kind)
    ref = _text(source_ref)
    if not kind or not ref or is_placeholder_ref(kind) or is_placeholder_ref(ref):
        raise ValueError("platform row source kind/ref is invalid")
    return PlatformRowSourceState(kind, ref, _content_hash(state_payload))


@dataclass(frozen=True)
class ResolvedPlatformRow:
    production_ref: str
    owner_user_id: str
    m_row: str
    producer_ref: str
    record: PlatformCapabilityRecord
    source_states: tuple[PlatformRowSourceState, ...]

    def __post_init__(self) -> None:
        for field_name in ("production_ref", "owner_user_id", "m_row", "producer_ref"):
            object.__setattr__(self, field_name, _text(getattr(self, field_name)))
        object.__setattr__(
            self,
            "source_states",
            tuple(sorted(self.source_states, key=lambda item: (item.source_kind, item.source_ref))),
        )

    @property
    def canonical_production_ref(self) -> str:
        return "platform_row_production:" + _content_hash(
            {
                "owner_user_id": self.owner_user_id,
                "m_row": self.m_row,
                "producer_ref": self.producer_ref,
                "record": platform_capability_record_to_dict(self.record),
                "source_states": [asdict(item) for item in self.source_states],
            }
        ).removeprefix("sha256:")


class PlatformRowProductionError(ValueError):
    """A server-derived row could not be resolved from current typed sources."""


PlatformRowProducer = Callable[[str], ResolvedPlatformRow]


def resolved_platform_row(
    *,
    owner_user_id: str,
    m_row: str,
    producer_ref: str,
    record: PlatformCapabilityRecord,
    source_states: tuple[PlatformRowSourceState, ...],
) -> ResolvedPlatformRow:
    blank = ResolvedPlatformRow(
        production_ref="",
        owner_user_id=owner_user_id,
        m_row=m_row,
        producer_ref=producer_ref,
        record=record,
        source_states=source_states,
    )
    return ResolvedPlatformRow(
        production_ref=blank.canonical_production_ref,
        owner_user_id=blank.owner_user_id,
        m_row=blank.m_row,
        producer_ref=blank.producer_ref,
        record=blank.record,
        source_states=blank.source_states,
    )


def validate_resolved_platform_row(
    value: ResolvedPlatformRow,
    *,
    owner_user_id: str,
    m_row: str,
) -> tuple[str, ...]:
    violations: list[str] = []
    owner = _text(owner_user_id)
    row = _text(m_row)
    if not owner or value.owner_user_id != owner or is_placeholder_ref(owner):
        violations.append("platform_row_owner_mismatch")
    if row not in REQUIRED_PLATFORM_ROWS or value.m_row != row or _row_value(value.record) != row:
        violations.append("platform_row_identity_mismatch")
    if not value.producer_ref or is_placeholder_ref(value.producer_ref):
        violations.append("platform_row_producer_ref_invalid")
    shape = validate_platform_capability(value.record)
    if not shape.accepted:
        violations.extend(f"platform_row_shape:{item.code}:{item.field}" for item in shape.violations)
    if not value.source_states:
        violations.append("platform_row_source_states_missing")
    source_keys = tuple((item.source_kind, item.source_ref) for item in value.source_states)
    if len(source_keys) != len(set(source_keys)):
        violations.append("platform_row_source_states_duplicate")
    source_refs = {item.source_ref for item in value.source_states}
    for item in value.source_states:
        if (
            not item.source_kind
            or not item.source_ref
            or is_placeholder_ref(item.source_kind)
            or is_placeholder_ref(item.source_ref)
            or not _valid_hash(item.state_hash)
        ):
            violations.append("platform_row_source_state_invalid")
    missing_bindings = sorted(set(_record_refs(value.record)) - source_refs)
    if missing_bindings:
        violations.append("platform_row_record_refs_not_content_bound:" + ",".join(missing_bindings))
    if value.production_ref != value.canonical_production_ref:
        violations.append("platform_row_production_identity_mismatch")
    return tuple(violations)


class PlatformRowProducerRegistry:
    """Mutable registration table; resolution itself is read-only and fail-closed."""

    def __init__(self, producers: dict[str, PlatformRowProducer] | None = None) -> None:
        self._producers: dict[str, PlatformRowProducer] = {}
        for row, producer in (producers or {}).items():
            self.register(row, producer)

    @property
    def registered_rows(self) -> tuple[str, ...]:
        return tuple(row for row in REQUIRED_PLATFORM_ROWS if row in self._producers)

    def register(self, m_row: str, producer: PlatformRowProducer) -> None:
        row = _text(m_row)
        if row not in REQUIRED_PLATFORM_ROWS:
            raise ValueError("platform row producer row is unknown")
        if row in self._producers:
            raise ValueError(f"platform row producer already registered for {row}")
        if not callable(producer):
            raise TypeError("platform row producer must be callable")
        self._producers[row] = producer

    def resolve_row(self, m_row: str, *, owner_user_id: str) -> ResolvedPlatformRow:
        row = _text(m_row)
        owner = _text(owner_user_id)
        if row not in REQUIRED_PLATFORM_ROWS or not owner:
            raise PlatformRowProductionError("platform row/owner is invalid")
        try:
            producer = self._producers[row]
        except KeyError:
            raise PlatformRowProductionError(
                f"server-derived platform row producer is unavailable for {row}"
            ) from None
        first = producer(owner)
        second = producer(owner)
        if not isinstance(first, ResolvedPlatformRow) or not isinstance(second, ResolvedPlatformRow):
            raise TypeError("platform row producer must return ResolvedPlatformRow")
        if first != second:
            raise PlatformRowProductionError(
                f"server-derived platform row backing changed during resolution for {row}"
            )
        violations = validate_resolved_platform_row(first, owner_user_id=owner, m_row=row)
        if violations:
            raise PlatformRowProductionError(";".join(violations))
        return first

    def resolve_current_manifest(
        self,
        owner_user_id: str,
    ) -> tuple[PlatformCapabilityRecord, ...]:
        return tuple(
            item.record for item in self.resolve_current_rows(owner_user_id)
        )

    def resolve_current_rows(
        self,
        owner_user_id: str,
    ) -> tuple[ResolvedPlatformRow, ...]:
        """Resolve the complete current producer state without discarding hashes.

        ``resolve_current_manifest`` remains the public record projection used by
        the platform journal.  Closure proofs must use this method instead so a
        change to an upstream typed source invalidates the closure even when the
        row's outward refs have not changed.
        """

        owner = _text(owner_user_id)
        missing = tuple(row for row in REQUIRED_PLATFORM_ROWS if row not in self._producers)
        if missing:
            raise PlatformRowProductionError(
                "server-derived platform manifest is missing row producers: "
                + ",".join(missing)
            )
        first = tuple(
            self.resolve_row(row, owner_user_id=owner) for row in REQUIRED_PLATFORM_ROWS
        )
        second = tuple(
            self.resolve_row(row, owner_user_id=owner) for row in REQUIRED_PLATFORM_ROWS
        )
        if first != second:
            raise PlatformRowProductionError(
                "server-derived platform manifest changed during preflight"
            )
        qro_graph_pairs = tuple(
            (_text(item.record.qro_ref), _text(item.record.research_graph_ref))
            for item in first
        )
        if len(qro_graph_pairs) != len(set(qro_graph_pairs)):
            raise PlatformRowProductionError(
                "server-derived platform rows must have distinct QRO/Graph lineages"
            )
        return first

    def record_current_manifest(
        self,
        platform_registry: PersistentPlatformCoverageRegistry,
        *,
        owner_user_id: str,
    ) -> tuple[PlatformCapabilityRecord, ...]:
        records = self.resolve_current_manifest(owner_user_id)
        decision = platform_registry.validate_manifest(
            records,
            owner_user_id=owner_user_id,
        )
        if not decision.accepted:
            raise PlatformRowProductionError(
                ";".join(
                    f"{item.code}:{item.field}:{item.ref}"
                    for item in decision.violations
                )
            )
        return platform_registry.record_manifest(records, owner_user_id=owner_user_id)


class ProducerBoundPlatformRefResolver:
    """Require exact current producer output before resolving a platform ref."""

    def __init__(
        self,
        base_resolver: Any,
        producer_registry: PlatformRowProducerRegistry,
        *,
        owner: str | None = None,
    ) -> None:
        self._base = base_resolver
        self._producers = producer_registry
        self._owner = _text(owner) or None

    def for_owner(self, owner: str) -> "ProducerBoundPlatformRefResolver":
        base = self._base.for_owner(owner) if hasattr(self._base, "for_owner") else self._base
        return ProducerBoundPlatformRefResolver(base, self._producers, owner=owner)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._base, name)

    def _current(self, record: PlatformCapabilityRecord) -> ResolvedPlatformRow | None:
        if self._owner is None:
            return None
        row = _row_value(record)
        try:
            current = self._producers.resolve_row(row, owner_user_id=self._owner)
        except (KeyError, TypeError, ValueError):
            return None
        return current if current.record == record else None

    def has_platform_common_ref(
        self,
        field: str,
        ref: str,
        record: PlatformCapabilityRecord,
    ) -> bool:
        del field
        current = self._current(record)
        return current is not None and _text(ref) in {
            item.source_ref for item in current.source_states
        }

    def has_platform_evidence(
        self,
        record: PlatformCapabilityRecord,
        ref: str,
    ) -> bool:
        current = self._current(record)
        return current is not None and _text(ref) in {
            item.source_ref for item in current.source_states
        }

    def has_platform_specific_ref(
        self,
        key: str,
        ref: str,
        record: PlatformCapabilityRecord,
    ) -> bool:
        del key
        current = self._current(record)
        return current is not None and _text(ref) in {
            item.source_ref for item in current.source_states
        }

    def platform_linkage_violations(
        self,
        record: PlatformCapabilityRecord,
    ) -> tuple[tuple[str, str, str], ...]:
        current = self._current(record)
        if current is None:
            return (("m_row", _row_value(record), "record is not the current server-derived row"),)
        base_linkage = getattr(self._base, "platform_linkage_violations", None)
        if not callable(base_linkage):
            return (("qro_ref", _text(record.qro_ref), "base row linkage resolver is unavailable"),)
        try:
            return tuple(base_linkage(record) or ())
        except Exception:
            return (("qro_ref", _text(record.qro_ref), "base row linkage resolution failed"),)


__all__ = [
    "PlatformRowProducer",
    "PlatformRowProducerRegistry",
    "PlatformRowProductionError",
    "PlatformRowSourceState",
    "ProducerBoundPlatformRefResolver",
    "ResolvedPlatformRow",
    "platform_row_source_state",
    "resolved_platform_row",
    "validate_resolved_platform_row",
]
