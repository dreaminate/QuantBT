"""Read-only typed-store resolver for certified GOAL section 14 row sources."""

from __future__ import annotations

from dataclasses import asdict, dataclass, is_dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Callable

from .platform_coverage import SPECIFIC_REQUIRED_REFS, PlatformCapabilityRecord
from .platform_row_producers import PlatformRowSourceState, platform_row_source_state


def _text(value: Any) -> str:
    return str(value or "").strip()


def _jsonable(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, Path):
        return value.as_posix()
    if is_dataclass(value):
        return _jsonable(asdict(value))
    if isinstance(value, dict):
        return {str(key): _jsonable(child) for key, child in value.items()}
    if isinstance(value, (tuple, list)):
        return [_jsonable(child) for child in value]
    if isinstance(value, (set, frozenset)):
        return sorted(_jsonable(child) for child in value)
    to_dict = getattr(value, "to_dict", None)
    if callable(to_dict):
        return _jsonable(to_dict())
    model_dump = getattr(value, "model_dump", None)
    if callable(model_dump):
        return _jsonable(model_dump(mode="json"))
    if hasattr(value, "__dict__"):
        return _jsonable(vars(value))
    isoformat = getattr(value, "isoformat", None)
    if callable(isoformat):
        return isoformat()
    return value


TypedSourceLoader = Callable[[str, str, PlatformCapabilityRecord], Any]
TypedSourceLinkValidator = Callable[
    [Any, str, PlatformCapabilityRecord],
    tuple[str, ...],
]
PlatformRowLinkValidator = Callable[
    [PlatformCapabilityRecord, str, dict[str, Any]],
    tuple[str, ...],
]


@dataclass(frozen=True)
class PlatformCompilerSnapshot:
    """One owner-scoped compiler view used by platform proof consumers.

    ``canonical`` is true only when the records came from the GOAL proof-ledger
    projection.  The false branch is an explicit compatibility surface for
    test doubles and legacy stores that have no configured proof projection.
    """

    owner: str
    irs: tuple[Any, ...]
    passes: tuple[Any, ...]
    canonical: bool

    @staticmethod
    def _one(records: tuple[Any, ...], ref: str, *, field: str) -> Any:
        matches = tuple(
            record
            for record in records
            if _text(getattr(record, field, "")) == ref
        )
        if len(matches) != 1:
            raise LookupError(f"compiler {field} is missing or ambiguous")
        return matches[0]

    def ir(self, ir_ref: str) -> Any:
        return self._one(self.irs, _text(ir_ref), field="ir_ref")

    def compiler_pass(self, pass_ref: str) -> Any:
        return self._one(self.passes, _text(pass_ref), field="pass_ref")


_MISSING_PROJECTION = object()


def _compiler_projection_marker(compiler_store: Any) -> Any:
    """Return an observable proof-ledger marker without assuming one store type."""

    marker = getattr(compiler_store, "_proof_projection", _MISSING_PROJECTION)
    if marker is not _MISSING_PROJECTION and marker is not None:
        return marker
    for field in (
        "proof_ledger",
        "_proof_ledger",
        "goal_proof_ledger",
        "_goal_proof_ledger",
    ):
        candidate = getattr(compiler_store, field, _MISSING_PROJECTION)
        if candidate is not _MISSING_PROJECTION and candidate is not None:
            return candidate
    return marker


def platform_compiler_snapshot_required_methods(
    compiler_store: Any,
) -> tuple[str, ...]:
    """Describe the only acceptable read API for the observed store mode."""

    marker = _compiler_projection_marker(compiler_store)
    canonical_records = getattr(compiler_store, "canonical_records", None)
    if marker is not None and marker is not _MISSING_PROJECTION:
        return ("canonical_records",)
    if marker is _MISSING_PROJECTION and callable(canonical_records):
        return ("canonical_records",)
    return ("irs", "passes")


def platform_compiler_snapshot(
    compiler_store: Any,
    *,
    owner: str,
) -> PlatformCompilerSnapshot:
    """Read exactly one compiler snapshot without mixing legacy JSONL heads."""

    normalized_owner = _text(owner)
    if not normalized_owner:
        raise ValueError("platform compiler snapshot owner is required")
    marker = _compiler_projection_marker(compiler_store)
    canonical_records = getattr(compiler_store, "canonical_records", None)
    use_legacy_compatibility = marker is None
    if not use_legacy_compatibility and callable(canonical_records):
        records = canonical_records(owner=normalized_owner)
        if any(
            not hasattr(records, field)
            for field in ("owner", "irs", "passes")
        ):
            raise TypeError("canonical compiler snapshot is malformed")
        record_owner = _text(getattr(records, "owner"))
        if record_owner != normalized_owner:
            raise LookupError("canonical compiler snapshot owner mismatch")
        irs = tuple(getattr(records, "irs", ()) or ())
        passes = tuple(getattr(records, "passes", ()) or ())
        canonical = True
    else:
        if marker is not None and marker is not _MISSING_PROJECTION:
            raise TypeError(
                "ledger-backed compiler store lacks canonical_records"
            )
        irs_reader = getattr(compiler_store, "irs", None)
        passes_reader = getattr(compiler_store, "passes", None)
        if not callable(irs_reader) or not callable(passes_reader):
            raise TypeError("compiler store lacks snapshot read methods")
        irs = tuple(irs_reader(owner=normalized_owner) or ())
        passes = tuple(passes_reader(owner=normalized_owner) or ())
        canonical = False

    if any(_text(getattr(item, "owner", "")) != normalized_owner for item in irs):
        raise LookupError("compiler snapshot contains an IR for another owner")
    if any(_text(getattr(item, "actor", "")) != normalized_owner for item in passes):
        raise LookupError("compiler snapshot contains a pass for another owner")
    ir_refs = tuple(_text(getattr(item, "ir_ref", "")) for item in irs)
    pass_refs = tuple(_text(getattr(item, "pass_ref", "")) for item in passes)
    if (
        any(not ref for ref in (*ir_refs, *pass_refs))
        or (
            canonical
            and (
                len(ir_refs) != len(set(ir_refs))
                or len(pass_refs) != len(set(pass_refs))
            )
        )
    ):
        raise LookupError("compiler snapshot contains missing or duplicate refs")
    return PlatformCompilerSnapshot(
        owner=normalized_owner,
        irs=irs,
        passes=passes,
        canonical=canonical,
    )


@dataclass(frozen=True)
class PlatformTypedSourceAdapter:
    source_kind: str
    load: TypedSourceLoader
    validate_linkage: TypedSourceLinkValidator


class RealPlatformTypedSourceResolver:
    """Resolve common refs plus explicit row-specific adapters.

    A specific key is unavailable unless it has both an exact getter and a
    linkage validator.  A row is unavailable unless it has a row-level
    validator.  This prevents a mere same-owner object from being recombined
    into an unrelated platform row.
    """

    def __init__(
        self,
        *,
        research_graph_store: Any,
        lifecycle_loaders: tuple[TypedSourceLoader, ...],
        goal_validation_receipt_registry: Any,
        rag_index: Any,
        spine_chain_registry: Any,
        compiler_store: Any,
        document_store: Any = None,
        specific_adapters: dict[
            str | tuple[str, str], PlatformTypedSourceAdapter
        ]
        | None = None,
        row_validators: dict[str, PlatformRowLinkValidator] | None = None,
    ) -> None:
        self._graph = research_graph_store
        self._lifecycle_loaders = tuple(lifecycle_loaders)
        self._validations = goal_validation_receipt_registry
        self._rag = rag_index
        self._spine = spine_chain_registry
        self._compiler = compiler_store
        self._documents = document_store
        self._specific: dict[str, PlatformTypedSourceAdapter] = {}
        self._row_specific: dict[
            tuple[str, str], PlatformTypedSourceAdapter
        ] = {}
        for raw_key, adapter in dict(specific_adapters or {}).items():
            if isinstance(raw_key, tuple):
                if len(raw_key) != 2:
                    raise ValueError(
                        "platform row-specific adapter key must be (m_row, field)"
                    )
                row, field = (_text(raw_key[0]), _text(raw_key[1]))
                if row not in SPECIFIC_REQUIRED_REFS:
                    raise ValueError(
                        f"platform row-specific adapter has unknown row {row!r}"
                    )
                if field not in SPECIFIC_REQUIRED_REFS[row]:
                    raise ValueError(
                        f"platform row-specific adapter field {field!r} is not required by {row}"
                    )
                self._row_specific[(row, field)] = adapter
                continue
            field = _text(raw_key)
            if not field:
                raise ValueError("platform specific adapter field is required")
            self._specific[field] = adapter
        self._row_validators = dict(row_validators or {})

    @property
    def registered_specific_keys(self) -> tuple[str, ...]:
        return tuple(
            sorted(
                (
                    *self._specific,
                    *(f"{row}:{field}" for row, field in self._row_specific),
                )
            )
        )

    @property
    def registered_rows(self) -> tuple[str, ...]:
        return tuple(sorted(self._row_validators))

    def producer_statuses(self) -> dict[str, dict[str, Any]]:
        """Expose exact adapter availability without attempting certification."""

        return {
            row: {
                "available": row in self._row_validators
                and all(self._has_specific_adapter(row, key) for key in required),
                "row_validator_available": row in self._row_validators,
                "required_specific_keys": list(required),
                "missing_specific_keys": [
                    key
                    for key in required
                    if not self._has_specific_adapter(row, key)
                ],
            }
            for row, required in SPECIFIC_REQUIRED_REFS.items()
        }

    def _has_specific_adapter(self, row: str, field: str) -> bool:
        return (row, field) in self._row_specific or field in self._specific

    def _specific_adapter(
        self,
        field: str,
        record: PlatformCapabilityRecord,
    ) -> PlatformTypedSourceAdapter:
        row = _text(getattr(record.m_row, "value", record.m_row))
        adapter = self._row_specific.get((row, field))
        if adapter is not None:
            return adapter
        try:
            return self._specific[field]
        except KeyError:
            raise LookupError(
                f"platform specific typed getter is unavailable for {row}.{field}"
            ) from None

    @staticmethod
    def _owned(value: Any, owner: str) -> bool:
        return _text(
            getattr(value, "owner_user_id", getattr(value, "owner", ""))
        ) == owner

    def _qro(self, ref: str, owner: str) -> Any:
        qro = self._graph.qro(ref)
        if _text(getattr(qro, "owner", "")) != owner:
            raise LookupError("QRO owner mismatch")
        return qro

    def _delegated_command_matches_owner(
        self,
        command: Any,
        qro: Any,
        owner: str,
        record: PlatformCapabilityRecord,
    ) -> bool:
        """Accept the one persisted delegated-review shape used by M12.

        The model owner remains the QRO/compiler/coverage owner while the
        independent reviewer is the Graph command actor.  The compiler path
        already validates the live reviewer grant and records that result in
        the durable GOAL validation receipt; revalidation requires that exact
        receipt and never treats arbitrary delegated fields as authority.
        """

        row = _text(getattr(record.m_row, "value", record.m_row))
        inputs = getattr(qro, "input_contract", None)
        outputs = getattr(qro, "output_contract", None)
        actor = _text(getattr(command, "actor", ""))
        if (
            row != "M12"
            or not isinstance(inputs, dict)
            or not isinstance(outputs, dict)
            or _text(getattr(qro, "owner", "")) != owner
            or not actor
            or _text(inputs.get("delegated_actor")) != actor
            or _text(outputs.get("approved_by")) != actor
            or not _text(inputs.get("delegated_actor_authority_ref"))
            or not _text(inputs.get("delegated_actor_authority_hash"))
            or _text(inputs.get("gate_id")) != _text(outputs.get("gate_id"))
            or _text(getattr(qro, "approval", "")) != _text(inputs.get("gate_id"))
        ):
            return False
        try:
            receipt = self._validations.receipt(
                _text(record.governance_ref),
                owner_user_id=owner,
            )
            decision = self._validations.validate_validation_ref(
                _text(record.governance_ref),
                owner_user_id=owner,
                subject_qro_refs=(_text(record.qro_ref),),
                graph_command_refs=(_text(record.research_graph_ref),),
            )
        except (KeyError, LookupError, TypeError, ValueError):
            return False
        return bool(getattr(decision, "accepted", False)) and (
            "runtime_validator:current_qro_graph_delegated_authority_v1"
            in tuple(getattr(receipt, "validator_identifiers", ()) or ())
        )

    def _command(self, ref: str, owner: str, record: PlatformCapabilityRecord) -> Any:
        command = next(
            item
            for item in self._graph.commands()
            if _text(getattr(item, "command_id", "")) == ref
        )
        payload = getattr(command, "payload", None)
        qro = payload.get("qro") if isinstance(payload, dict) else None
        if (
            _text(getattr(qro, "qro_id", "")) != _text(record.qro_ref)
            or _text(getattr(qro, "owner", "")) != owner
            or (
                _text(getattr(command, "actor", "")) != owner
                and not self._delegated_command_matches_owner(
                    command,
                    qro,
                    owner,
                    record,
                )
            )
        ):
            raise LookupError("Research Graph command/QRO linkage mismatch")
        return command

    def _lifecycle(
        self,
        ref: str,
        owner: str,
        record: PlatformCapabilityRecord,
    ) -> Any:
        for loader in self._lifecycle_loaders:
            try:
                value = loader(ref, owner, record)
            except (KeyError, LookupError, TypeError, ValueError):
                continue
            if value is not None:
                return value
        raise LookupError("lifecycle ref has no exact typed getter")

    def _governance(self, ref: str, owner: str, record: PlatformCapabilityRecord) -> Any:
        receipt = self._validations.receipt(ref, owner_user_id=owner)
        decision = self._validations.validate_validation_ref(
            ref,
            owner_user_id=owner,
            subject_qro_refs=(_text(record.qro_ref),),
            graph_command_refs=(_text(record.research_graph_ref),),
        )
        if not bool(getattr(decision, "accepted", False)):
            raise LookupError("GOAL validation receipt is not current for row QRO/Graph")
        return receipt

    def _rag_document(self, ref: str, owner: str) -> Any:
        document = self._rag.document_for_owner(
            ref,
            owner_user_id=owner,
            require_current=True,
        )
        permission = getattr(document, "permission", None)
        if owner not in tuple(getattr(permission, "allowed_users", ()) or ()):
            raise LookupError("RAG owner permission mismatch")
        return document

    def _math_chain(self, ref: str, owner: str) -> Any:
        return self._spine.verified_chain(ref, owner=owner)

    def _evidence(
        self,
        ref: str,
        owner: str,
        record: PlatformCapabilityRecord,
    ) -> Any:
        matches: list[dict[str, Any]] = []
        compiler = platform_compiler_snapshot(self._compiler, owner=owner)
        for ir in compiler.irs:
            if (
                _text(record.qro_ref) in tuple(getattr(ir, "source_qro_refs", ()) or ())
                and ref in tuple(getattr(ir, "evidence_refs", ()) or ())
            ):
                matches.append({"kind": "compiler_ir", "record": _jsonable(ir)})
        for compiler_pass in compiler.passes:
            if (
                _text(record.qro_ref)
                in tuple(getattr(compiler_pass, "input_qro_refs", ()) or ())
                and ref in tuple(getattr(compiler_pass, "evidence_refs", ()) or ())
            ):
                matches.append(
                    {"kind": "compiler_pass", "record": _jsonable(compiler_pass)}
                )
        if self._documents is not None:
            try:
                span = self._documents.span(ref)
            except (KeyError, LookupError):
                span = None
            if span is not None and _text(getattr(span, "owner", "")) == owner:
                matches.append({"kind": "document_span", "record": _jsonable(span)})
        if not matches:
            raise LookupError("evidence ref is absent from current QRO compiler lineage")
        return matches

    def _specific_value(
        self,
        field: str,
        ref: str,
        owner: str,
        record: PlatformCapabilityRecord,
    ) -> tuple[PlatformTypedSourceAdapter, Any]:
        adapter = self._specific_adapter(field, record)
        value = adapter.load(ref, owner, record)
        violations = tuple(adapter.validate_linkage(value, owner, record) or ())
        if violations:
            raise LookupError(";".join(_text(item) for item in violations))
        return adapter, value

    def resolve_state(
        self,
        field: str,
        ref: str,
        *,
        owner_user_id: str,
        record: PlatformCapabilityRecord,
    ) -> PlatformRowSourceState:
        field_name = _text(field)
        source_ref = _text(ref)
        owner = _text(owner_user_id)
        if not field_name or not source_ref or not owner:
            raise ValueError("platform typed source field/ref/owner is required")
        if field_name == "qro_ref":
            kind, value = "research_graph_qro", self._qro(source_ref, owner)
        elif field_name == "research_graph_ref":
            kind, value = "research_graph_command", self._command(
                source_ref,
                owner,
                record,
            )
        elif field_name == "lifecycle_ref":
            kind, value = "lifecycle_record", self._lifecycle(
                source_ref,
                owner,
                record,
            )
        elif field_name == "governance_ref":
            kind, value = "goal_validation_receipt", self._governance(
                source_ref,
                owner,
                record,
            )
        elif field_name == "rag_ref":
            kind, value = "research_asset_rag", self._rag_document(source_ref, owner)
        elif field_name == "math_spine_ref":
            kind, value = "mathematical_spine_chain", self._math_chain(
                source_ref,
                owner,
            )
        elif field_name == "evidence_ref":
            kind, value = "compiler_or_document_evidence", self._evidence(
                source_ref,
                owner,
                record,
            )
        else:
            adapter, value = self._specific_value(
                field_name,
                source_ref,
                owner,
                record,
            )
            kind = _text(adapter.source_kind)
        return platform_row_source_state(
            source_kind=kind,
            source_ref=source_ref,
            state_payload=_jsonable(value),
        )

    def linkage_violations(
        self,
        record: PlatformCapabilityRecord,
        *,
        owner_user_id: str,
        source_coverage: Any,
        rag_document: Any,
    ) -> tuple[str, ...]:
        owner = _text(owner_user_id)
        row = _text(getattr(record.m_row, "value", record.m_row))
        violations: list[str] = []
        try:
            qro = self._qro(_text(record.qro_ref), owner)
            command = self._command(
                _text(record.research_graph_ref),
                owner,
                record,
            )
        except (KeyError, LookupError, StopIteration, TypeError, ValueError) as exc:
            return (f"platform row QRO/Graph linkage failed:{type(exc).__name__}",)
        command_qro = (
            command.payload.get("qro")
            if isinstance(getattr(command, "payload", None), dict)
            else None
        )
        if command_qro != qro:
            violations.append("Research Graph command does not carry the exact current QRO")
        if tuple(getattr(source_coverage, "qro_refs", ()) or ()) != (
            _text(record.qro_ref),
        ):
            violations.append("source coverage QRO ref mismatch")
        if tuple(
            getattr(source_coverage, "research_graph_command_refs", ()) or ()
        ) != (_text(record.research_graph_ref),):
            violations.append("source coverage graph command ref mismatch")
        if _text(getattr(rag_document, "document_id", "")) != _text(record.rag_ref):
            violations.append("RAG document identity mismatch")
        specific_values: dict[str, Any] = {}
        for item in record.specific_refs:
            try:
                _adapter, value = self._specific_value(
                    item.key,
                    item.ref,
                    owner,
                    record,
                )
                specific_values[item.key] = value
            except (KeyError, LookupError, TypeError, ValueError) as exc:
                violations.append(
                    f"specific source {item.key} linkage failed:{type(exc).__name__}"
                )
        validator = self._row_validators.get(row)
        if validator is None:
            violations.append(f"platform row linkage validator is unavailable for {row}")
        else:
            try:
                violations.extend(
                    _text(item)
                    for item in tuple(validator(record, owner, specific_values) or ())
                    if _text(item)
                )
            except Exception as exc:
                violations.append(
                    f"platform row linkage validator failed:{type(exc).__name__}"
                )
        return tuple(violations)


def scope_platform_source_adapters(
    adapters: dict[str | tuple[str, str], PlatformTypedSourceAdapter],
    row_validators: dict[str, PlatformRowLinkValidator],
) -> dict[tuple[str, str], PlatformTypedSourceAdapter]:
    """Project one adapter-builder result onto exact ``(row, field)`` keys.

    Several M rows intentionally reuse a field name (for example M6/M12 model
    passports and M14/M20 LLM gateway refs).  Production composition must not
    let whichever builder runs last silently replace the other row's getter.
    """

    scoped: dict[tuple[str, str], PlatformTypedSourceAdapter] = {}
    for raw_row in row_validators:
        row = _text(raw_row)
        if row not in SPECIFIC_REQUIRED_REFS:
            raise ValueError(f"unknown platform adapter row {row!r}")
        for field in SPECIFIC_REQUIRED_REFS[row]:
            adapter = adapters.get((row, field)) or adapters.get(field)
            if adapter is None:
                raise ValueError(f"platform adapter builder omitted {row}.{field}")
            scoped[(row, field)] = adapter
    return scoped


def compose_platform_source_adapter_groups(
    *groups: tuple[
        dict[str | tuple[str, str], PlatformTypedSourceAdapter],
        dict[str, PlatformRowLinkValidator],
    ],
) -> tuple[
    dict[tuple[str, str], PlatformTypedSourceAdapter],
    dict[str, PlatformRowLinkValidator],
]:
    """Merge disjoint adapter families without global-field collisions."""

    scoped: dict[tuple[str, str], PlatformTypedSourceAdapter] = {}
    validators: dict[str, PlatformRowLinkValidator] = {}
    for adapters, group_validators in groups:
        duplicate_rows = set(validators).intersection(group_validators)
        if duplicate_rows:
            raise ValueError(
                f"duplicate platform row validators: {sorted(duplicate_rows)}"
            )
        group_scoped = scope_platform_source_adapters(adapters, group_validators)
        duplicate_keys = set(scoped).intersection(group_scoped)
        if duplicate_keys:
            raise ValueError(
                f"duplicate platform row adapters: {sorted(duplicate_keys)}"
            )
        scoped.update(group_scoped)
        validators.update(group_validators)
    return scoped, validators


__all__ = [
    "PlatformCompilerSnapshot",
    "PlatformRowLinkValidator",
    "PlatformTypedSourceAdapter",
    "RealPlatformTypedSourceResolver",
    "TypedSourceLinkValidator",
    "TypedSourceLoader",
    "compose_platform_source_adapter_groups",
    "platform_compiler_snapshot",
    "platform_compiler_snapshot_required_methods",
    "scope_platform_source_adapters",
]
