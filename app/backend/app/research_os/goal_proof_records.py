"""Typed projections for records stored in :mod:`goal_proof_ledger`.

The proof ledger deliberately stores product-agnostic JSON objects.  This
module adds the small, strict envelope needed by record registries to project
those objects back into their existing dataclasses without treating legacy
JSONL rows as canonical proof heads.
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass, is_dataclass
from enum import Enum
from typing import Any, Callable, Generic, Mapping, TypeVar

from .goal_proof_ledger import GoalProofLedger, ProofHead, ProofMember


PROOF_RECORD_SCHEMA_VERSION = "goal_proof_record.v1"

LOGICAL_TYPE_COMPILER_IR = "goal.compiler_ir"
LOGICAL_TYPE_COMPILER_PASS = "goal.compiler_pass"
LOGICAL_TYPE_COMPILER_ARTIFACT = "goal.compiler_artifact"
LOGICAL_TYPE_VALIDATION_RECEIPT = "goal.validation_receipt"
LOGICAL_TYPE_ENTRYPOINT_EVIDENCE = "goal.entrypoint_evidence"
LOGICAL_TYPE_ENTRYPOINT_COVERAGE = "goal.entrypoint_coverage"

ATOMIC_PROOF_BUNDLE_REQUIRED = "atomic proof bundle required"


class GoalProofRecordProjectionError(ValueError):
    """A canonical proof head cannot be decoded as its declared record type."""


def _required(value: Any, *, field_name: str) -> str:
    normalized = str(value or "").strip()
    if not normalized:
        raise GoalProofRecordProjectionError(
            f"canonical GOAL proof record {field_name} is required"
        )
    return normalized


def _exact_required(value: Any, *, field_name: str) -> str:
    raw = str(value or "")
    normalized = _required(raw, field_name=field_name)
    if raw != normalized:
        raise GoalProofRecordProjectionError(
            f"canonical GOAL proof record {field_name} must be exact"
        )
    return normalized


def normalize_proof_record(value: Any) -> Any:
    """Return a detached JSON value with dataclasses and Enums normalized.

    Unlike a permissive ``default=str`` serializer, this function fails on
    unknown Python objects and non-finite numbers so canonical ledger payloads
    cannot silently decode to a different application record.
    """

    if isinstance(value, Enum):
        return normalize_proof_record(value.value)
    if is_dataclass(value):
        return normalize_proof_record(asdict(value))
    if isinstance(value, Mapping):
        normalized: dict[str, Any] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise GoalProofRecordProjectionError(
                    "canonical GOAL proof record object keys must be strings"
                )
            normalized[key] = normalize_proof_record(item)
        return normalized
    if isinstance(value, (tuple, list)):
        return [normalize_proof_record(item) for item in value]
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise GoalProofRecordProjectionError(
                "canonical GOAL proof record numbers must be finite"
            )
        return value
    raise GoalProofRecordProjectionError(
        "canonical GOAL proof record contains a non-JSON value: "
        f"{type(value).__name__}"
    )


def proof_record_envelope(
    *,
    logical_type: str,
    logical_ref: str,
    owner: str,
    record: Any,
) -> dict[str, Any]:
    """Build the exact payload stored by one typed proof member."""

    normalized_record = normalize_proof_record(record)
    if not isinstance(normalized_record, dict):
        raise GoalProofRecordProjectionError(
            "canonical GOAL proof record body must be an object"
        )
    return {
        "schema_version": PROOF_RECORD_SCHEMA_VERSION,
        "logical_type": _required(logical_type, field_name="logical_type"),
        "logical_ref": _required(logical_ref, field_name="logical_ref"),
        "owner": _required(owner, field_name="owner"),
        "record": normalized_record,
    }


def proof_record_member(
    *,
    logical_type: str,
    logical_ref: str,
    owner: str,
    record: Any,
    depends_on: tuple[str, ...] = (),
) -> ProofMember:
    """Create a product-typed :class:`ProofMember` with a stable envelope."""

    normalized_type = _required(logical_type, field_name="logical_type")
    normalized_ref = _required(logical_ref, field_name="logical_ref")
    normalized_owner = _required(owner, field_name="owner")
    return ProofMember(
        logical_type=normalized_type,
        logical_ref=normalized_ref,
        payload=proof_record_envelope(
            logical_type=normalized_type,
            logical_ref=normalized_ref,
            owner=normalized_owner,
            record=record,
        ),
        depends_on=depends_on,
    )


RecordT = TypeVar("RecordT")


@dataclass(frozen=True)
class ProofRecordCodec(Generic[RecordT]):
    """Typed decoder hooks for one application record family."""

    logical_type: str
    record_type: type[RecordT]
    decode: Callable[[dict[str, Any]], RecordT]
    logical_ref: Callable[[RecordT], str]
    owner: Callable[[RecordT], str]

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "logical_type",
            _required(self.logical_type, field_name="codec logical_type"),
        )


def typed_proof_record_member(
    record: RecordT,
    *,
    codec: ProofRecordCodec[RecordT],
    depends_on: tuple[str, ...] = (),
) -> ProofMember:
    """Create a member after checking its typed owner and logical identity."""

    if not isinstance(record, codec.record_type):
        raise TypeError(
            "canonical GOAL proof record type mismatch: expected "
            f"{codec.record_type.__name__}"
        )
    logical_ref = _exact_required(
        codec.logical_ref(record),
        field_name="record ref",
    )
    owner = _exact_required(codec.owner(record), field_name="record owner")
    return proof_record_member(
        logical_type=codec.logical_type,
        logical_ref=logical_ref,
        owner=owner,
        record=record,
        depends_on=depends_on,
    )


def decode_proof_record_head(
    head: ProofHead,
    *,
    codec: ProofRecordCodec[RecordT],
) -> RecordT:
    """Strictly decode one exact current head through ``codec``."""

    if not isinstance(head, ProofHead):
        raise TypeError("canonical GOAL proof record decoding requires ProofHead")
    if head.logical_type != codec.logical_type:
        raise GoalProofRecordProjectionError(
            "canonical GOAL proof logical ref/type collision: "
            f"{head.logical_ref!r} is {head.logical_type!r}, expected "
            f"{codec.logical_type!r}"
        )
    payload = head.payload
    if not isinstance(payload, Mapping):
        raise GoalProofRecordProjectionError(
            "canonical GOAL proof record payload must be an object"
        )
    expected_fields = {
        "schema_version",
        "logical_type",
        "logical_ref",
        "owner",
        "record",
    }
    if set(payload) != expected_fields:
        raise GoalProofRecordProjectionError(
            "canonical GOAL proof record envelope field set mismatch"
        )
    if payload.get("schema_version") != PROOF_RECORD_SCHEMA_VERSION:
        raise GoalProofRecordProjectionError(
            "canonical GOAL proof record schema_version is unsupported"
        )
    for field_name, actual, expected in (
        ("logical_type", payload.get("logical_type"), head.logical_type),
        ("logical_ref", payload.get("logical_ref"), head.logical_ref),
        ("owner", payload.get("owner"), head.owner),
    ):
        if actual != expected:
            raise GoalProofRecordProjectionError(
                "canonical GOAL proof record envelope/head collision in "
                f"{field_name}"
            )
    raw_record = payload.get("record")
    if not isinstance(raw_record, Mapping):
        raise GoalProofRecordProjectionError(
            "canonical GOAL proof record body must be an object"
        )
    detached = normalize_proof_record(raw_record)
    if not isinstance(detached, dict):
        raise GoalProofRecordProjectionError(
            "canonical GOAL proof record body must normalize to an object"
        )
    try:
        record = codec.decode(detached)
    except Exception as exc:
        raise GoalProofRecordProjectionError(
            "canonical GOAL proof record typed decoder rejected its body"
        ) from exc
    if not isinstance(record, codec.record_type):
        raise GoalProofRecordProjectionError(
            "canonical GOAL proof record typed decoder returned the wrong type"
        )
    if normalize_proof_record(record) != detached:
        raise GoalProofRecordProjectionError(
            "canonical GOAL proof record body does not exactly round-trip"
        )
    if _exact_required(codec.owner(record), field_name="decoded owner") != head.owner:
        raise GoalProofRecordProjectionError(
            "canonical GOAL proof decoded record owner collision"
        )
    if _exact_required(codec.logical_ref(record), field_name="decoded ref") != head.logical_ref:
        raise GoalProofRecordProjectionError(
            "canonical GOAL proof decoded record ref collision"
        )
    return record


class GoalProofRecordProjection:
    """Live typed view over exact current heads in a ``GoalProofLedger``."""

    def __init__(self, ledger: GoalProofLedger) -> None:
        if not isinstance(ledger, GoalProofLedger):
            raise TypeError("canonical GOAL proof projection requires GoalProofLedger")
        self._ledger = ledger

    @property
    def ledger(self) -> GoalProofLedger:
        return self._ledger

    def current_head(
        self,
        *,
        owner: str,
        logical_type: str,
        logical_ref: str,
    ) -> ProofHead:
        normalized_owner = _required(owner, field_name="owner")
        normalized_type = _required(logical_type, field_name="logical_type")
        normalized_ref = _required(logical_ref, field_name="logical_ref")
        matches = tuple(
            head
            for head in self._ledger.current(owner=normalized_owner).heads
            if head.logical_ref == normalized_ref
        )
        if not matches:
            raise KeyError(normalized_ref)
        if len(matches) != 1:
            raise GoalProofRecordProjectionError(
                "canonical GOAL proof current ref is ambiguous"
            )
        head = matches[0]
        if head.logical_type != normalized_type:
            raise GoalProofRecordProjectionError(
                "canonical GOAL proof logical ref/type collision: "
                f"{normalized_ref!r} is {head.logical_type!r}, expected "
                f"{normalized_type!r}"
            )
        return head

    def current_heads(
        self,
        *,
        logical_type: str,
        owner: str | None = None,
    ) -> tuple[ProofHead, ...]:
        normalized_type = _required(logical_type, field_name="logical_type")
        normalized_owner = (
            _required(owner, field_name="owner") if owner is not None else None
        )
        return tuple(
            head
            for head in self._ledger.current(owner=normalized_owner).heads
            if head.logical_type == normalized_type
        )

    def decode_current(
        self,
        *,
        owner: str,
        logical_ref: str,
        codec: ProofRecordCodec[RecordT],
    ) -> RecordT:
        return decode_proof_record_head(
            self.current_head(
                owner=owner,
                logical_type=codec.logical_type,
                logical_ref=logical_ref,
            ),
            codec=codec,
        )

    def decode_all(
        self,
        *,
        codec: ProofRecordCodec[RecordT],
        owner: str | None = None,
    ) -> tuple[RecordT, ...]:
        return tuple(
            decode_proof_record_head(head, codec=codec)
            for head in self.current_heads(
                logical_type=codec.logical_type,
                owner=owner,
            )
        )

    def decode_many(
        self,
        *codecs: ProofRecordCodec[Any],
        owner: str | None = None,
    ) -> dict[str, tuple[Any, ...]]:
        """Decode several logical types from one exact ledger snapshot."""

        decoded, _head_types = self.decode_many_with_index(
            *codecs,
            owner=owner,
        )
        return decoded

    def decode_many_with_index(
        self,
        *codecs: ProofRecordCodec[Any],
        owner: str | None = None,
    ) -> tuple[
        dict[str, tuple[Any, ...]],
        dict[tuple[str, str], str],
    ]:
        """Decode types and return the same snapshot's owner/ref type index."""

        if not codecs:
            return {}, {}
        codec_by_type = {codec.logical_type: codec for codec in codecs}
        if len(codec_by_type) != len(codecs):
            raise ValueError("canonical GOAL proof codecs must have unique types")
        normalized_owner = (
            _required(owner, field_name="owner") if owner is not None else None
        )
        decoded: dict[str, list[Any]] = {
            logical_type: [] for logical_type in codec_by_type
        }
        snapshot = self._ledger.current(owner=normalized_owner)
        head_types = {
            (head.owner, head.logical_ref): head.logical_type
            for head in snapshot.heads
        }
        for head in snapshot.heads:
            codec = codec_by_type.get(head.logical_type)
            if codec is None:
                continue
            decoded[head.logical_type].append(
                decode_proof_record_head(head, codec=codec)
            )
        return (
            {
                logical_type: tuple(records)
                for logical_type, records in decoded.items()
            },
            head_types,
        )

    def is_exact_current(
        self,
        record: RecordT,
        *,
        codec: ProofRecordCodec[RecordT],
    ) -> bool:
        if not isinstance(record, codec.record_type):
            return False
        owner = _required(codec.owner(record), field_name="record owner")
        logical_ref = _required(codec.logical_ref(record), field_name="record ref")
        try:
            current = self.decode_current(
                owner=owner,
                logical_ref=logical_ref,
                codec=codec,
            )
        except KeyError:
            return False
        return (
            current == record
            and normalize_proof_record(current) == normalize_proof_record(record)
        )

    def exact_current_head(
        self,
        record: RecordT,
        *,
        codec: ProofRecordCodec[RecordT],
    ) -> ProofHead | None:
        """Return the immutable head only when ``record`` is its exact payload."""

        if not isinstance(record, codec.record_type):
            return None
        owner = _required(codec.owner(record), field_name="record owner")
        logical_ref = _required(codec.logical_ref(record), field_name="record ref")
        try:
            head = self.current_head(
                owner=owner,
                logical_type=codec.logical_type,
                logical_ref=logical_ref,
            )
        except KeyError:
            return None
        current = decode_proof_record_head(head, codec=codec)
        if (
            current != record
            or normalize_proof_record(current) != normalize_proof_record(record)
        ):
            return None
        return head

    def current_bundle_id(
        self,
        *,
        owner: str,
        logical_type: str,
        logical_ref: str,
    ) -> str:
        """Return the exact current declaration bundle for one typed ref."""

        return self.current_head(
            owner=owner,
            logical_type=logical_type,
            logical_ref=logical_ref,
        ).bundle_id

    def current_heads_for_refs(
        self,
        *,
        owner: str,
        typed_refs: tuple[tuple[str, str], ...],
    ) -> tuple[ProofHead, ...]:
        """Resolve several typed refs from one immutable ledger snapshot."""

        normalized_owner = _required(owner, field_name="owner")
        normalized = tuple(
            (
                _required(logical_type, field_name="logical_type"),
                _required(logical_ref, field_name="logical_ref"),
            )
            for logical_type, logical_ref in typed_refs
        )
        refs = tuple(logical_ref for _logical_type, logical_ref in normalized)
        if len(refs) != len(set(refs)):
            raise GoalProofRecordProjectionError(
                "canonical GOAL proof snapshot refs must be unique"
            )
        snapshot = self._ledger.current(owner=normalized_owner)
        by_ref = {head.logical_ref: head for head in snapshot.heads}
        resolved: list[ProofHead] = []
        for logical_type, logical_ref in normalized:
            try:
                head = by_ref[logical_ref]
            except KeyError:
                raise KeyError(logical_ref) from None
            if head.logical_type != logical_type:
                raise GoalProofRecordProjectionError(
                    "canonical GOAL proof logical ref/type collision: "
                    f"{logical_ref!r} is {head.logical_type!r}, expected "
                    f"{logical_type!r}"
                )
            resolved.append(head)
        return tuple(resolved)


__all__ = [
    "ATOMIC_PROOF_BUNDLE_REQUIRED",
    "GoalProofRecordProjection",
    "GoalProofRecordProjectionError",
    "LOGICAL_TYPE_COMPILER_ARTIFACT",
    "LOGICAL_TYPE_COMPILER_IR",
    "LOGICAL_TYPE_COMPILER_PASS",
    "LOGICAL_TYPE_ENTRYPOINT_EVIDENCE",
    "LOGICAL_TYPE_ENTRYPOINT_COVERAGE",
    "LOGICAL_TYPE_VALIDATION_RECEIPT",
    "PROOF_RECORD_SCHEMA_VERSION",
    "ProofRecordCodec",
    "decode_proof_record_head",
    "normalize_proof_record",
    "proof_record_envelope",
    "proof_record_member",
    "typed_proof_record_member",
]
