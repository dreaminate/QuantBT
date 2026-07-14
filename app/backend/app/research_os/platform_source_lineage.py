"""Server-derived source lineage for the proven GOAL section 14 M15 row.

The caller may select already-persisted typed objects, but none of those refs
is accepted as evidence by string shape.  This producer derives the Research
Graph command, compiler lineage, evidence, validation receipt, permissions,
replay refs, coverage identity, and RAG identity from owner-scoped stores.  It
resolves every pre-existing platform source twice before invoking either write
callback, then re-resolves the complete persisted row twice.

M15 is the only row whose RAG contract is proven by this producer.  Other rows
have additional row-specific RAG contracts and are rejected before persistence.
The evidence, coverage, and RAG ledgers are separate append-only files, so their
writes cannot provide a cross-ledger transaction.  A failure after the write
phase starts is reported as
:class:`PlatformSourceLineageCommitError` with the observed persistence state;
retries are content-idempotent.
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
import threading
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Callable

from ..cross_process_lock import acquire_exclusive_fd
from .asset_rag import AssetRAGDocument, RAGPermission
from .goal_proof_head_lock import acquire_goal_proof_head_lock
from .goal_coverage import (
    GoalEntrypointCoverageRecord,
    goal_entrypoint_coverage_identity,
)
from .platform_coverage import (
    REQUIRED_PLATFORM_ROWS,
    SPECIFIC_REF_PREFIXES,
    SPECIFIC_REQUIRED_REFS,
    PlatformCapabilityRecord,
    PlatformSpecificRef,
    validate_platform_capability,
)
from .platform_row_producers import PlatformRowSourceState
from .platform_typed_sources import (
    RealPlatformTypedSourceResolver,
    platform_compiler_snapshot,
    platform_compiler_snapshot_required_methods,
)
from .ref_resolution import is_placeholder_ref
from .spine import EntrySource, ResearchGraphProjectionRecord


PLATFORM_SOURCE_LINEAGE_VERSION = "platform_source_lineage.v1"
PLATFORM_SOURCE_LINEAGE_EVIDENCE_VERSION = (
    "platform_source_lineage_evidence.v1"
)
PLATFORM_SOURCE_LINEAGE_PROVEN_ROWS = frozenset({"M15"})
_PLATFORM_METADATA_KEY = "platform_capability"


def _text(value: Any) -> str:
    return str(getattr(value, "value", value) or "").strip()


def _canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )


def _sha256(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _stable_exact(value: Any, *, field: str) -> str:
    raw = str(getattr(value, "value", value) or "")
    normalized = raw.strip()
    if (
        not normalized
        or raw != normalized
        or any(ord(char) < 32 for char in normalized)
        or is_placeholder_ref(normalized)
    ):
        raise PlatformSourceLineageError(f"{field} is not a stable real ref")
    return normalized


def _unique_refs(value: Any, *, field: str, required: bool = True) -> tuple[str, ...]:
    raw = tuple(value or ())
    refs = tuple(_stable_exact(item, field=field) for item in raw)
    if required and not refs:
        raise PlatformSourceLineageError(f"{field} is required")
    if len(refs) != len(set(refs)):
        raise PlatformSourceLineageError(f"{field} contains duplicate refs")
    return refs


def _same_ref_set(left: tuple[str, ...], right: tuple[str, ...]) -> bool:
    return len(left) == len(right) and frozenset(left) == frozenset(right)


def _sorted_union(*groups: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(sorted({ref for group in groups for ref in group}))


def _enum_text(value: Any) -> str:
    return _text(getattr(value, "value", value))


class PlatformSourceLineageError(ValueError):
    """The selected refs do not form one current, real, owner-scoped lineage."""


class PlatformSourceLineageCommitError(PlatformSourceLineageError):
    """A callback or post-write proof failed after the write phase began."""

    def __init__(
        self,
        message: str,
        *,
        evidence_persisted: bool = False,
        coverage_persisted: bool,
        rag_persisted: bool,
    ) -> None:
        super().__init__(message)
        self.evidence_persisted = bool(evidence_persisted)
        self.coverage_persisted = bool(coverage_persisted)
        self.rag_persisted = bool(rag_persisted)


@dataclass(frozen=True)
class PlatformSourceLineageEvidenceViolation:
    code: str
    message: str
    field: str = ""
    ref: str = ""


@dataclass(frozen=True)
class PlatformSourceLineageEvidenceDecision:
    accepted: bool
    violations: tuple[PlatformSourceLineageEvidenceViolation, ...]


@dataclass(frozen=True)
class PlatformSourceLineageEvidenceRecord:
    """Independent current-source evidence cited by compiler and coverage.

    Compiler IR/pass refs are deliberately absent from this record.  The
    evidence identity is derived from owner-scoped QRO, Graph, lifecycle,
    validation, Mathematical Spine, and row-specific source states that exist
    before compiler lineage is accepted.
    """

    evidence_ref: str
    owner_user_id: str
    m_row: str
    entry_source: str
    entrypoint_ref: str
    qro_ref: str
    research_graph_ref: str
    lifecycle_ref: str
    governance_ref: str
    math_spine_ref: str
    specific_refs: tuple[PlatformSpecificRef, ...]
    source_states: tuple[PlatformRowSourceState, ...]
    evidence_version: str = PLATFORM_SOURCE_LINEAGE_EVIDENCE_VERSION

    def __post_init__(self) -> None:
        for field_name in (
            "evidence_ref",
            "owner_user_id",
            "m_row",
            "entry_source",
            "entrypoint_ref",
            "qro_ref",
            "research_graph_ref",
            "lifecycle_ref",
            "governance_ref",
            "math_spine_ref",
            "evidence_version",
        ):
            object.__setattr__(self, field_name, _text(getattr(self, field_name)))
        object.__setattr__(
            self,
            "specific_refs",
            tuple(sorted(tuple(self.specific_refs), key=lambda item: (item.key, item.ref))),
        )
        object.__setattr__(
            self,
            "source_states",
            tuple(
                sorted(
                    tuple(self.source_states),
                    key=lambda item: (item.source_kind, item.source_ref),
                )
            ),
        )

    @property
    def canonical_evidence_ref(self) -> str:
        return "platform_source_evidence:" + _sha256(
            {
                "owner_user_id": self.owner_user_id,
                "m_row": self.m_row,
                "entry_source": self.entry_source,
                "entrypoint_ref": self.entrypoint_ref,
                "qro_ref": self.qro_ref,
                "research_graph_ref": self.research_graph_ref,
                "lifecycle_ref": self.lifecycle_ref,
                "governance_ref": self.governance_ref,
                "math_spine_ref": self.math_spine_ref,
                "specific_refs": [asdict(item) for item in self.specific_refs],
                "source_states": [asdict(item) for item in self.source_states],
                "evidence_version": self.evidence_version,
            }
        )


def _valid_state_hash(value: Any) -> bool:
    token = _text(value).lower()
    return (
        token.startswith("sha256:")
        and len(token) == 71
        and all(char in "0123456789abcdef" for char in token[7:])
    )


def validate_platform_source_lineage_evidence_shape(
    record: PlatformSourceLineageEvidenceRecord,
) -> PlatformSourceLineageEvidenceDecision:
    violations: list[PlatformSourceLineageEvidenceViolation] = []

    def add(code: str, message: str, *, field: str, ref: Any) -> None:
        violations.append(
            PlatformSourceLineageEvidenceViolation(
                code,
                message,
                field=field,
                ref=_text(ref),
            )
        )

    stable_fields = (
        "evidence_ref",
        "owner_user_id",
        "m_row",
        "entry_source",
        "entrypoint_ref",
        "qro_ref",
        "research_graph_ref",
        "lifecycle_ref",
        "governance_ref",
        "math_spine_ref",
        "evidence_version",
    )
    for field_name in stable_fields:
        value = _text(getattr(record, field_name))
        if not value or is_placeholder_ref(value):
            add(
                "platform_source_evidence_ref_invalid",
                "platform source evidence requires stable non-placeholder fields",
                field=field_name,
                ref=value,
            )
    if record.m_row not in PLATFORM_SOURCE_LINEAGE_PROVEN_ROWS:
        add(
            "platform_source_evidence_row_unproven",
            "platform source evidence row is not supported by this producer",
            field="m_row",
            ref=record.m_row,
        )
    if record.entry_source not in {item.value for item in EntrySource}:
        add(
            "platform_source_evidence_entry_source_unknown",
            "platform source evidence has an unknown entry source",
            field="entry_source",
            ref=record.entry_source,
        )
    required_specifics = SPECIFIC_REQUIRED_REFS.get(record.m_row, ())
    specific_map = {item.key: item.ref for item in record.specific_refs}
    if (
        len(specific_map) != len(record.specific_refs)
        or set(specific_map) != set(required_specifics)
        or any(not ref or is_placeholder_ref(ref) for ref in specific_map.values())
    ):
        add(
            "platform_source_evidence_specific_refs_invalid",
            "platform source evidence must bind the exact row-specific refs",
            field="specific_refs",
            ref=record.m_row,
        )
    expected_source_refs = {
        record.qro_ref,
        record.research_graph_ref,
        record.lifecycle_ref,
        record.governance_ref,
        record.math_spine_ref,
        *specific_map.values(),
    }
    actual_source_refs = [item.source_ref for item in record.source_states]
    if (
        not record.source_states
        or len(actual_source_refs) != len(set(actual_source_refs))
        or set(actual_source_refs) != expected_source_refs
    ):
        add(
            "platform_source_evidence_state_set_mismatch",
            "source states must exactly cover the independent typed source refs",
            field="source_states",
            ref=record.evidence_ref,
        )
    for state in record.source_states:
        if (
            not _text(state.source_kind)
            or is_placeholder_ref(state.source_kind)
            or not _text(state.source_ref)
            or is_placeholder_ref(state.source_ref)
            or not _valid_state_hash(state.state_hash)
        ):
            add(
                "platform_source_evidence_state_invalid",
                "platform source evidence state is not content-bound",
                field="source_states",
                ref=state.source_ref,
            )
    if record.evidence_ref != record.canonical_evidence_ref:
        add(
            "platform_source_evidence_identity_mismatch",
            "evidence_ref must content-bind owner, refs, and current source states",
            field="evidence_ref",
            ref=record.evidence_ref,
        )
    return PlatformSourceLineageEvidenceDecision(
        accepted=not violations,
        violations=tuple(violations),
    )


def derive_platform_source_lineage_evidence(
    *,
    source_resolver: RealPlatformTypedSourceResolver,
    owner_user_id: str,
    m_row: str,
    entry_source: str,
    entrypoint_ref: str,
    qro_ref: str,
    research_graph_ref: str,
    lifecycle_ref: str,
    governance_ref: str,
    math_spine_ref: str,
    specific_refs: tuple[PlatformSpecificRef, ...],
) -> PlatformSourceLineageEvidenceRecord:
    """Derive one evidence identity without consulting compiler evidence refs."""

    if not isinstance(source_resolver, RealPlatformTypedSourceResolver):
        raise TypeError("source_resolver must be RealPlatformTypedSourceResolver")
    owner = _stable_exact(owner_user_id, field="owner_user_id")
    row = _stable_exact(m_row, field="m_row")
    source = _stable_exact(entry_source, field="entry_source")
    entrypoint = _stable_exact(entrypoint_ref, field="entrypoint_ref")
    qro = _stable_exact(qro_ref, field="qro_ref")
    graph = _stable_exact(research_graph_ref, field="research_graph_ref")
    lifecycle = _stable_exact(lifecycle_ref, field="lifecycle_ref")
    governance = _stable_exact(governance_ref, field="governance_ref")
    math_spine = _stable_exact(math_spine_ref, field="math_spine_ref")
    specifics = tuple(
        sorted(
            (
                PlatformSpecificRef(
                    key=_stable_exact(item.key, field="specific_refs.key"),
                    ref=_stable_exact(item.ref, field=f"specific_refs.{item.key}"),
                )
                for item in tuple(specific_refs)
            ),
            key=lambda item: (item.key, item.ref),
        )
    )
    provisional_capability = PlatformCapabilityRecord(
        m_row=row,
        qro_ref=qro,
        research_graph_ref=graph,
        lifecycle_ref=lifecycle,
        governance_ref=governance,
        rag_ref="research_asset_rag:platform-source-evidence:" + _sha256(
            (owner, row, qro, graph)
        ),
        math_spine_ref=math_spine,
        evidence_refs=(),
        specific_refs=specifics,
    )
    fields_and_refs = (
        ("qro_ref", qro),
        ("research_graph_ref", graph),
        ("lifecycle_ref", lifecycle),
        ("governance_ref", governance),
        ("math_spine_ref", math_spine),
        *((item.key, item.ref) for item in specifics),
    )
    states: list[PlatformRowSourceState] = []
    for field_name, ref in fields_and_refs:
        try:
            state = source_resolver.resolve_state(
                field_name,
                ref,
                owner_user_id=owner,
                record=provisional_capability,
            )
        except Exception as exc:
            raise PlatformSourceLineageError(
                "independent evidence source resolution failed:"
                f"{field_name}:{type(exc).__name__}"
            ) from exc
        if not isinstance(state, PlatformRowSourceState) or state.source_ref != ref:
            raise PlatformSourceLineageError(
                f"independent evidence source {field_name} returned invalid state"
            )
        states.append(state)
    try:
        linkage = tuple(
            source_resolver.linkage_violations(
                provisional_capability,
                owner_user_id=owner,
                source_coverage=SimpleNamespace(
                    qro_refs=(qro,),
                    research_graph_command_refs=(graph,),
                ),
                rag_document=SimpleNamespace(
                    document_id=provisional_capability.rag_ref,
                ),
            )
            or ()
        )
    except Exception as exc:
        raise PlatformSourceLineageError(
            "independent evidence row linkage failed:"
            f"{type(exc).__name__}"
        ) from exc
    if linkage:
        raise PlatformSourceLineageError(
            ";".join(_text(item) for item in linkage)
        )
    provisional = PlatformSourceLineageEvidenceRecord(
        evidence_ref="",
        owner_user_id=owner,
        m_row=row,
        entry_source=source,
        entrypoint_ref=entrypoint,
        qro_ref=qro,
        research_graph_ref=graph,
        lifecycle_ref=lifecycle,
        governance_ref=governance,
        math_spine_ref=math_spine,
        specific_refs=specifics,
        source_states=tuple(states),
    )
    record = replace(
        provisional,
        evidence_ref=provisional.canonical_evidence_ref,
    )
    decision = validate_platform_source_lineage_evidence_shape(record)
    if not decision.accepted:
        raise PlatformSourceLineageError(
            ";".join(
                f"{item.code}:{item.field}:{item.ref}"
                for item in decision.violations
            )
        )
    return record


def platform_source_lineage_evidence_to_dict(
    record: PlatformSourceLineageEvidenceRecord,
) -> dict[str, Any]:
    return {
        "evidence_ref": record.evidence_ref,
        "owner_user_id": record.owner_user_id,
        "m_row": record.m_row,
        "entry_source": record.entry_source,
        "entrypoint_ref": record.entrypoint_ref,
        "qro_ref": record.qro_ref,
        "research_graph_ref": record.research_graph_ref,
        "lifecycle_ref": record.lifecycle_ref,
        "governance_ref": record.governance_ref,
        "math_spine_ref": record.math_spine_ref,
        "specific_refs": [asdict(item) for item in record.specific_refs],
        "source_states": [asdict(item) for item in record.source_states],
        "evidence_version": record.evidence_version,
    }


def platform_source_lineage_evidence_from_dict(
    value: dict[str, Any],
) -> PlatformSourceLineageEvidenceRecord:
    return PlatformSourceLineageEvidenceRecord(
        evidence_ref=_text(value.get("evidence_ref")),
        owner_user_id=_text(value.get("owner_user_id")),
        m_row=_text(value.get("m_row")),
        entry_source=_text(value.get("entry_source")),
        entrypoint_ref=_text(value.get("entrypoint_ref")),
        qro_ref=_text(value.get("qro_ref")),
        research_graph_ref=_text(value.get("research_graph_ref")),
        lifecycle_ref=_text(value.get("lifecycle_ref")),
        governance_ref=_text(value.get("governance_ref")),
        math_spine_ref=_text(value.get("math_spine_ref")),
        specific_refs=tuple(
            PlatformSpecificRef(
                key=_text(item.get("key")),
                ref=_text(item.get("ref")),
            )
            for item in tuple(value.get("specific_refs") or ())
            if isinstance(item, dict)
        ),
        source_states=tuple(
            PlatformRowSourceState(
                source_kind=_text(item.get("source_kind")),
                source_ref=_text(item.get("source_ref")),
                state_hash=_text(item.get("state_hash")),
            )
            for item in tuple(value.get("source_states") or ())
            if isinstance(item, dict)
        ),
        evidence_version=_text(value.get("evidence_version")),
    )


class PersistentPlatformSourceLineageEvidenceRegistry:
    """Owner-scoped JSONL ledger for independent platform source evidence."""

    def __init__(
        self,
        path: str | Path,
        *,
        source_resolver: RealPlatformTypedSourceResolver,
    ) -> None:
        if not isinstance(source_resolver, RealPlatformTypedSourceResolver):
            raise TypeError("source_resolver must be RealPlatformTypedSourceResolver")
        self._path = Path(path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._lock_path = self._path.with_name(f".{self._path.name}.lock")
        self._lock = threading.RLock()
        self._resolver = source_resolver
        self._records: dict[
            tuple[str, str],
            PlatformSourceLineageEvidenceRecord,
        ] = {}
        self._load_existing()

    @property
    def path(self) -> Path:
        return self._path

    @staticmethod
    def _owner(value: Any) -> str:
        owner = _text(value)
        if not owner:
            raise ValueError("platform source evidence owner_user_id is required")
        return owner

    @staticmethod
    def _event(record: PlatformSourceLineageEvidenceRecord) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "event_type": "platform_source_lineage_evidence_recorded",
            "owner_user_id": record.owner_user_id,
            "evidence": platform_source_lineage_evidence_to_dict(record),
        }

    def _load_existing(self) -> None:
        if not self._path.exists():
            return
        with self._path.open("r", encoding="utf-8") as fh:
            for line_no, line in enumerate(fh, start=1):
                if not line.strip():
                    continue
                try:
                    self._apply_row(json.loads(line), persist=False)
                except Exception as exc:  # noqa: BLE001
                    raise ValueError(
                        "invalid persisted platform source evidence at "
                        f"{self._path}:{line_no}"
                    ) from exc

    def _append_event(self, row: dict[str, Any]) -> None:
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
                    and persisted.get("evidence_ref")
                    == incoming.get("evidence_ref")
                ):
                    if existing == row:
                        return
                    raise ValueError(
                        "platform source evidence identity collision at "
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
                with os.fdopen(temporary_fd, "wb") as fh:
                    fh.write(prefix)
                    fh.write(serialized)
                    fh.flush()
                    os.fsync(fh.fileno())
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
    ) -> PlatformSourceLineageEvidenceRecord:
        if row.get("schema_version") != 1:
            raise ValueError("platform source evidence requires schema_version=1")
        if row.get("event_type") != "platform_source_lineage_evidence_recorded":
            raise ValueError("unknown platform source evidence event_type")
        owner = self._owner(row.get("owner_user_id"))
        raw = row.get("evidence")
        if not isinstance(raw, dict):
            raise ValueError("platform source evidence event is missing evidence")
        record = platform_source_lineage_evidence_from_dict(raw)
        if record.owner_user_id != owner:
            raise ValueError("platform source evidence owner envelope mismatch")
        decision = validate_platform_source_lineage_evidence_shape(record)
        if not decision.accepted:
            raise ValueError(
                ";".join(
                    f"{item.code}:{item.field}:{item.ref}"
                    for item in decision.violations
                )
            )
        key = (owner, record.evidence_ref)
        with self._lock:
            existing = self._records.get(key)
            if existing is not None:
                if existing != record:
                    raise ValueError(
                        "platform source evidence identity collision for owner"
                    )
                return existing
            if persist:
                self._append_event(row)
            self._records[key] = record
            return record

    def validate_current(
        self,
        record: PlatformSourceLineageEvidenceRecord,
        *,
        owner_user_id: str,
    ) -> PlatformSourceLineageEvidenceDecision:
        violations = list(
            validate_platform_source_lineage_evidence_shape(record).violations
        )
        owner = self._owner(owner_user_id)
        if record.owner_user_id != owner:
            violations.append(
                PlatformSourceLineageEvidenceViolation(
                    "platform_source_evidence_owner_mismatch",
                    "platform source evidence owner envelope mismatch",
                    field="owner_user_id",
                    ref=record.owner_user_id,
                )
            )
        if not violations:
            try:
                current = derive_platform_source_lineage_evidence(
                    source_resolver=self._resolver,
                    owner_user_id=owner,
                    m_row=record.m_row,
                    entry_source=record.entry_source,
                    entrypoint_ref=record.entrypoint_ref,
                    qro_ref=record.qro_ref,
                    research_graph_ref=record.research_graph_ref,
                    lifecycle_ref=record.lifecycle_ref,
                    governance_ref=record.governance_ref,
                    math_spine_ref=record.math_spine_ref,
                    specific_refs=record.specific_refs,
                )
            except Exception as exc:  # noqa: BLE001 - current proof fails closed.
                violations.append(
                    PlatformSourceLineageEvidenceViolation(
                        "platform_source_evidence_current_resolution_failed",
                        "current typed source resolution failed:"
                        f"{type(exc).__name__}",
                        field="source_states",
                        ref=record.evidence_ref,
                    )
                )
            else:
                if current != record:
                    violations.append(
                        PlatformSourceLineageEvidenceViolation(
                            "platform_source_evidence_drifted",
                            "persisted evidence no longer matches current typed sources",
                            field="source_states",
                            ref=record.evidence_ref,
                        )
                    )
        return PlatformSourceLineageEvidenceDecision(
            accepted=not violations,
            violations=tuple(violations),
        )

    def record_evidence(
        self,
        record: PlatformSourceLineageEvidenceRecord,
    ) -> PlatformSourceLineageEvidenceRecord:
        decision = self.validate_current(
            record,
            owner_user_id=record.owner_user_id,
        )
        if not decision.accepted:
            raise ValueError(
                ";".join(
                    f"{item.code}:{item.field}:{item.ref}"
                    for item in decision.violations
                )
            )
        return self._apply_row(self._event(record), persist=True)

    def evidence(
        self,
        evidence_ref: str,
        *,
        owner_user_id: str,
    ) -> PlatformSourceLineageEvidenceRecord:
        return self._records[
            (self._owner(owner_user_id), _text(evidence_ref))
        ]

    def evidences(
        self,
        *,
        owner_user_id: str,
    ) -> tuple[PlatformSourceLineageEvidenceRecord, ...]:
        owner = self._owner(owner_user_id)
        return tuple(
            record
            for (record_owner, _), record in self._records.items()
            if record_owner == owner
        )

    def validate_platform_ref(
        self,
        evidence_ref: str,
        *,
        owner_user_id: str,
        record: PlatformCapabilityRecord,
    ) -> PlatformSourceLineageEvidenceDecision:
        try:
            evidence = self.evidence(
                evidence_ref,
                owner_user_id=owner_user_id,
            )
        except Exception as exc:  # noqa: BLE001 - linkage fails closed.
            return PlatformSourceLineageEvidenceDecision(
                False,
                (
                    PlatformSourceLineageEvidenceViolation(
                        "platform_source_evidence_unknown",
                        "independent evidence lookup failed:"
                        f"{type(exc).__name__}",
                        field="evidence_refs",
                        ref=evidence_ref,
                    ),
                ),
            )
        violations = list(
            self.validate_current(
                evidence,
                owner_user_id=owner_user_id,
            ).violations
        )
        row = _text(getattr(record.m_row, "value", record.m_row))
        expected = (
            ("m_row", evidence.m_row, row),
            ("qro_ref", evidence.qro_ref, _text(record.qro_ref)),
            (
                "research_graph_ref",
                evidence.research_graph_ref,
                _text(record.research_graph_ref),
            ),
            (
                "lifecycle_ref",
                evidence.lifecycle_ref,
                _text(record.lifecycle_ref),
            ),
            (
                "governance_ref",
                evidence.governance_ref,
                _text(record.governance_ref),
            ),
            (
                "math_spine_ref",
                evidence.math_spine_ref,
                _text(record.math_spine_ref),
            ),
        )
        for field_name, evidence_value, record_value in expected:
            if evidence_value != record_value:
                violations.append(
                    PlatformSourceLineageEvidenceViolation(
                        "platform_source_evidence_linkage_mismatch",
                        "platform row and independent evidence refs differ",
                        field=field_name,
                        ref=evidence_ref,
                    )
                )
        if tuple(evidence.specific_refs) != tuple(
            sorted(
                tuple(record.specific_refs),
                key=lambda item: (item.key, item.ref),
            )
        ):
            violations.append(
                PlatformSourceLineageEvidenceViolation(
                    "platform_source_evidence_linkage_mismatch",
                    "platform row and independent evidence specific refs differ",
                    field="specific_refs",
                    ref=evidence_ref,
                )
            )
        return PlatformSourceLineageEvidenceDecision(
            accepted=not violations,
            violations=tuple(violations),
        )


@dataclass(frozen=True)
class PlatformSourceLineageSelection:
    """Untrusted M15 hints; hashes and proof refs are intentionally absent."""

    m_row: str
    qro_ref: str
    lifecycle_ref: str
    math_spine_ref: str
    specific_refs: tuple[PlatformSpecificRef, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "specific_refs", tuple(self.specific_refs))


@dataclass(frozen=True)
class PlatformSourceLineageResult:
    """Fully revalidated persisted result for the currently proven M15 path."""

    evidence_record: PlatformSourceLineageEvidenceRecord
    coverage: GoalEntrypointCoverageRecord
    rag_document: AssetRAGDocument
    capability_record: PlatformCapabilityRecord
    source_states: tuple[PlatformRowSourceState, ...]


@dataclass(frozen=True)
class _CompilerLineage:
    qro: Any
    graph_command: Any
    compiler_ir: Any
    compiler_pass: Any
    receipt: Any
    entry_source: str
    entrypoint_ref: str
    qro_ref: str
    graph_ref: str
    ir_ref: str
    pass_ref: str
    evidence_refs: tuple[str, ...]
    validation_refs: tuple[str, ...]
    permission_refs: tuple[str, ...]
    canonical_command_refs: tuple[str, ...]
    governance_ref: str


@dataclass(frozen=True)
class _ProjectionHead:
    projection: ResearchGraphProjectionRecord
    projection_ref: str
    qro_ref: str
    graph_ref: str


CoverageRecorder = Callable[[GoalEntrypointCoverageRecord], GoalEntrypointCoverageRecord]
RAGRecorder = Callable[..., AssetRAGDocument]


class PlatformSourceLineageProducer:
    """Derive and record one M15 source lineage from real stores.

    ``record_coverage`` should normally be
    ``PersistentGoalEntrypointCoverageRegistry.record_coverage`` and
    ``record_rag_document`` should normally be
    ``PersistentResearchAssetRAGIndex.add_for_owner``.
    """

    def __init__(
        self,
        *,
        research_graph_store: Any,
        compiler_store: Any,
        goal_validation_receipt_registry: Any,
        entrypoint_registry: Any,
        rag_index: Any,
        source_resolver: RealPlatformTypedSourceResolver,
        record_coverage: CoverageRecorder,
        record_rag_document: RAGRecorder,
        evidence_registry: PersistentPlatformSourceLineageEvidenceRegistry
        | None = None,
    ) -> None:
        if not isinstance(source_resolver, RealPlatformTypedSourceResolver):
            raise TypeError("source_resolver must be RealPlatformTypedSourceResolver")
        required_methods = (
            (research_graph_store, "qro"),
            (research_graph_store, "commands"),
            (research_graph_store, "projection_index"),
            *(
                (compiler_store, method)
                for method in platform_compiler_snapshot_required_methods(
                    compiler_store
                )
            ),
            (goal_validation_receipt_registry, "receipt"),
            (goal_validation_receipt_registry, "validate_validation_ref"),
            (entrypoint_registry, "coverage"),
            (entrypoint_registry, "validate_real_backing"),
            (entrypoint_registry, "attach_platform_source_evidence_registry"),
            (rag_index, "document_for_owner"),
            (rag_index, "current_document_for_owner"),
        )
        for value, method in required_methods:
            if not callable(getattr(value, method, None)):
                raise TypeError(f"platform source lineage dependency lacks {method}")
        if not callable(record_coverage) or not callable(record_rag_document):
            raise TypeError("platform source lineage record callbacks are required")
        self._graph = research_graph_store
        self._compiler = compiler_store
        self._validations = goal_validation_receipt_registry
        self._entrypoints = entrypoint_registry
        self._proof_head_ledger_path = Path(entrypoint_registry.path).expanduser().absolute()
        self._rag = rag_index
        self._resolver = source_resolver
        if evidence_registry is None:
            evidence_registry = PersistentPlatformSourceLineageEvidenceRegistry(
                Path(entrypoint_registry.path).with_name(
                    "platform_source_lineage_evidence.jsonl"
                ),
                source_resolver=source_resolver,
            )
        if not isinstance(
            evidence_registry,
            PersistentPlatformSourceLineageEvidenceRegistry,
        ):
            raise TypeError(
                "evidence_registry must be "
                "PersistentPlatformSourceLineageEvidenceRegistry"
            )
        self._evidence = evidence_registry
        entrypoint_registry.attach_platform_source_evidence_registry(
            evidence_registry
        )
        self._record_coverage = record_coverage
        self._record_rag_document = record_rag_document

    @property
    def evidence_registry(
        self,
    ) -> PersistentPlatformSourceLineageEvidenceRegistry:
        return self._evidence

    @staticmethod
    def _selection(
        owner_user_id: str,
        selection: PlatformSourceLineageSelection,
    ) -> tuple[str, str, str, str, dict[str, str]]:
        owner = _stable_exact(owner_user_id, field="owner_user_id")
        row = _stable_exact(selection.m_row, field="m_row")
        if row not in REQUIRED_PLATFORM_ROWS:
            raise PlatformSourceLineageError("m_row is not a canonical platform row")
        if row not in PLATFORM_SOURCE_LINEAGE_PROVEN_ROWS:
            raise PlatformSourceLineageError(
                "platform source lineage is only proven for M15; "
                "other row-specific RAG contracts are unsupported"
            )
        qro_ref = _stable_exact(selection.qro_ref, field="qro_ref")
        lifecycle_ref = _stable_exact(
            selection.lifecycle_ref,
            field="lifecycle_ref",
        )
        math_spine_ref = _stable_exact(
            selection.math_spine_ref,
            field="math_spine_ref",
        )
        specifics: dict[str, str] = {}
        for item in selection.specific_refs:
            if not isinstance(item, PlatformSpecificRef):
                raise PlatformSourceLineageError(
                    "specific_refs must contain PlatformSpecificRef values"
                )
            key = _stable_exact(item.key, field="specific_refs.key")
            ref = _stable_exact(item.ref, field=f"specific_refs.{key}")
            if key in specifics:
                raise PlatformSourceLineageError(
                    f"specific_refs contains duplicate key {key}"
                )
            specifics[key] = ref
        required = SPECIFIC_REQUIRED_REFS[row]
        if set(specifics) != set(required):
            raise PlatformSourceLineageError(
                "specific_refs must exactly match the selected platform row"
            )
        for key in required:
            prefixes = SPECIFIC_REF_PREFIXES.get(key, ())
            if prefixes and not specifics[key].startswith(prefixes):
                raise PlatformSourceLineageError(
                    f"specific_refs.{key} has a non-canonical prefix"
                )
        return owner, row, qro_ref, lifecycle_ref, math_spine_ref, specifics

    def _projection_head(
        self,
        *,
        owner: str,
        qro_ref: str,
        projection_ref: str,
    ) -> _ProjectionHead:
        try:
            projections = tuple(self._graph.projection_index(owner=owner))
            qro = self._graph.qro(qro_ref)
            commands = tuple(self._graph.commands())
        except Exception as exc:
            raise PlatformSourceLineageError(
                "current Research Graph projection lookup failed:"
                f"{type(exc).__name__}"
            ) from exc
        if _text(getattr(qro, "owner", "")) != owner:
            raise PlatformSourceLineageError("selected QRO owner mismatch")
        current_for_qro = tuple(
            item
            for item in projections
            if _text(getattr(item, "qro_id", "")) == qro_ref
        )
        matches = tuple(
            item
            for item in current_for_qro
            if _text(getattr(item, "projection_ref", "")) == projection_ref
        )
        if len(current_for_qro) != 1 or len(matches) != 1:
            raise PlatformSourceLineageError(
                "selected typed canvas projection is not the unique current "
                "Research Graph projection"
            )
        projection = matches[0]
        if not isinstance(projection, ResearchGraphProjectionRecord):
            raise PlatformSourceLineageError(
                "selected typed canvas projection has an invalid persisted type"
            )
        graph_ref = _stable_exact(
            projection.command_id,
            field="typed_canvas_projection.command_id",
        )
        graph_commands = tuple(
            item
            for item in commands
            if _text(getattr(item, "command_id", "")) == graph_ref
        )
        if len(graph_commands) != 1:
            raise PlatformSourceLineageError(
                "current projection command is missing or ambiguous"
            )
        command = graph_commands[0]
        payload = getattr(command, "payload", None)
        command_qro = payload.get("qro") if isinstance(payload, dict) else None
        if (
            _text(getattr(qro, "owner", "")) != owner
            or _text(getattr(projection, "owner", "")) != owner
            or _text(getattr(projection, "actor", "")) != owner
            or _text(getattr(command, "actor", "")) != owner
            or _text(getattr(command, "command_type", "")) != "upsert_qro"
            or _text(getattr(projection, "qro_id", "")) != qro_ref
            or command_qro != qro
        ):
            raise PlatformSourceLineageError(
                "current projection owner/QRO/command linkage mismatch"
            )
        expected_projection = ResearchGraphProjectionRecord.from_qro_command(
            command=command,
            qro=qro,
        )
        if projection != expected_projection:
            raise PlatformSourceLineageError(
                "current projection differs from its exact QRO/command head"
            )
        return _ProjectionHead(
            projection=projection,
            projection_ref=projection_ref,
            qro_ref=qro_ref,
            graph_ref=graph_ref,
        )

    def _compiler_lineage(
        self,
        *,
        owner: str,
        qro_ref: str,
        graph_ref: str,
        math_spine_ref: str,
    ) -> _CompilerLineage:
        try:
            qro = self._graph.qro(qro_ref)
            compiler = platform_compiler_snapshot(self._compiler, owner=owner)
            irs = compiler.irs
            passes = compiler.passes
        except Exception as exc:
            raise PlatformSourceLineageError(
                f"platform source lineage store lookup failed:{type(exc).__name__}"
            ) from exc
        if _text(getattr(qro, "owner", "")) != owner:
            raise PlatformSourceLineageError("selected QRO owner mismatch")

        candidates: list[tuple[Any, Any]] = []
        irs_by_ref = {
            _text(getattr(item, "ir_ref", "")): item
            for item in irs
            if _text(getattr(item, "ir_ref", ""))
        }
        for compiler_pass in passes:
            ir = irs_by_ref.get(_text(getattr(compiler_pass, "output_ir_ref", "")))
            if ir is None:
                continue
            if tuple(getattr(ir, "source_qro_refs", ()) or ()) != (qro_ref,):
                continue
            if tuple(getattr(compiler_pass, "input_qro_refs", ()) or ()) != (
                qro_ref,
            ):
                continue
            if tuple(getattr(ir, "graph_command_refs", ()) or ()) != (
                graph_ref,
            ):
                continue
            if tuple(getattr(compiler_pass, "graph_command_refs", ()) or ()) != (
                graph_ref,
            ):
                continue
            candidates.append((ir, compiler_pass))
        if len(candidates) != 1:
            raise PlatformSourceLineageError(
                "selected QRO must have exactly one current compiler IR/pass lineage"
            )
        ir, compiler_pass = candidates[0]
        ir_ref = _stable_exact(getattr(ir, "ir_ref", ""), field="compiler_ir_ref")
        pass_ref = _stable_exact(
            getattr(compiler_pass, "pass_ref", ""),
            field="compiler_pass_ref",
        )
        try:
            if compiler.ir(ir_ref) != ir:
                raise PlatformSourceLineageError("compiler IR snapshot state mismatch")
            if compiler.compiler_pass(pass_ref) != compiler_pass:
                raise PlatformSourceLineageError("compiler pass snapshot state mismatch")
        except PlatformSourceLineageError:
            raise
        except Exception as exc:
            raise PlatformSourceLineageError(
                f"exact compiler lineage reload failed:{type(exc).__name__}"
            ) from exc

        if (
            _text(getattr(ir, "owner", "")) != owner
            or _text(getattr(compiler_pass, "actor", "")) != owner
        ):
            raise PlatformSourceLineageError("compiler lineage owner mismatch")
        qro_math_refs = _unique_refs(
            getattr(qro, "mathematical_refs", ()),
            field="qro.mathematical_refs",
        )
        ir_math_refs = _unique_refs(
            getattr(ir, "mathematical_spine_chain_refs", ()),
            field="compiler_ir.mathematical_spine_chain_refs",
        )
        if qro_math_refs != (math_spine_ref,):
            raise PlatformSourceLineageError(
                "selected QRO must bind exactly the selected Mathematical Spine chain"
            )
        if ir_math_refs != (math_spine_ref,):
            raise PlatformSourceLineageError(
                "selected compiler IR must bind exactly the selected Mathematical Spine chain"
            )
        ir_graph = _unique_refs(
            getattr(ir, "graph_command_refs", ()),
            field="compiler_ir.graph_command_refs",
        )
        pass_graph = _unique_refs(
            getattr(compiler_pass, "graph_command_refs", ()),
            field="compiler_pass.graph_command_refs",
        )
        if ir_graph != (graph_ref,) or pass_graph != (graph_ref,):
            raise PlatformSourceLineageError(
                "compiler IR/pass must bind the selected current Research Graph head"
            )

        commands = tuple(
            item
            for item in self._graph.commands()
            if _text(getattr(item, "command_id", "")) == graph_ref
        )
        if len(commands) != 1:
            raise PlatformSourceLineageError(
                "compiler graph command is missing or ambiguous"
            )
        command = commands[0]
        payload = getattr(command, "payload", None)
        command_qro = payload.get("qro") if isinstance(payload, dict) else None
        if (
            _text(getattr(command, "actor", "")) != owner
            or _text(getattr(command, "command_type", "")) != "upsert_qro"
            or _text(getattr(command_qro, "qro_id", "")) != qro_ref
            or _text(getattr(command_qro, "owner", "")) != owner
            or command_qro != qro
        ):
            raise PlatformSourceLineageError(
                "compiler graph command is stale, recombined, or owner-mismatched"
            )

        entry_source = _stable_exact(
            getattr(compiler_pass, "entry_source", ""),
            field="compiler_pass.entry_source",
        )
        if entry_source not in {item.value for item in EntrySource}:
            raise PlatformSourceLineageError("compiler entry source is unknown")
        if _enum_text(getattr(command, "source", "")) != entry_source:
            raise PlatformSourceLineageError(
                "Research Graph and compiler entry sources differ"
            )
        qro_input = getattr(qro, "input_contract", None)
        declared_source = (
            _text(qro_input.get("entry_source"))
            if isinstance(qro_input, dict)
            else ""
        )
        if declared_source and declared_source != entry_source:
            raise PlatformSourceLineageError("QRO and compiler entry sources differ")

        ir_evidence = _unique_refs(
            getattr(ir, "evidence_refs", ()),
            field="compiler_ir.evidence_refs",
        )
        pass_evidence = _unique_refs(
            getattr(compiler_pass, "evidence_refs", ()),
            field="compiler_pass.evidence_refs",
        )
        ir_validations = _unique_refs(
            getattr(ir, "validation_refs", ()),
            field="compiler_ir.validation_refs",
        )
        pass_validations = _unique_refs(
            getattr(compiler_pass, "validation_refs", ()),
            field="compiler_pass.validation_refs",
        )
        ir_canonical = _unique_refs(
            getattr(ir, "canonical_command_refs", ()),
            field="compiler_ir.canonical_command_refs",
        )
        pass_canonical = _unique_refs(
            getattr(compiler_pass, "canonical_command_refs", ()),
            field="compiler_pass.canonical_command_refs",
        )
        if not _same_ref_set(ir_evidence, pass_evidence):
            raise PlatformSourceLineageError(
                "compiler IR/pass evidence sets are recombined"
            )
        if not _same_ref_set(ir_validations, pass_validations):
            raise PlatformSourceLineageError(
                "compiler IR/pass validation sets are recombined"
            )
        if not _same_ref_set(ir_canonical, pass_canonical):
            raise PlatformSourceLineageError(
                "compiler IR/pass canonical command sets are recombined"
            )
        ir_permission = _stable_exact(
            getattr(ir, "permission_ref", ""),
            field="compiler_ir.permission_ref",
        )
        pass_permission = _stable_exact(
            getattr(compiler_pass, "permission_ref", ""),
            field="compiler_pass.permission_ref",
        )
        if ir_permission != pass_permission:
            raise PlatformSourceLineageError(
                "compiler IR/pass permission refs are recombined"
            )

        binding_refs = _sorted_union(
            ir_canonical,
            pass_canonical,
            _unique_refs(
                getattr(ir, "node_refs", ()),
                field="compiler_ir.node_refs",
            ),
            _unique_refs(
                getattr(compiler_pass, "tool_record_refs", ()),
                field="compiler_pass.tool_record_refs",
            ),
        )
        entrypoint_tokens = tuple(
            sorted(
                {
                    ref.removeprefix("entrypoint:")
                    for ref in binding_refs
                    if ref.startswith("entrypoint:")
                }
            )
        )
        if len(entrypoint_tokens) != 1 or not entrypoint_tokens[0]:
            raise PlatformSourceLineageError(
                "compiler lineage must bind exactly one canonical entrypoint"
            )
        entrypoint_ref = _stable_exact(
            entrypoint_tokens[0],
            field="entrypoint_ref",
        )

        validation_refs = _sorted_union(ir_validations, pass_validations)
        receipt_refs = tuple(
            ref
            for ref in validation_refs
            if ref.startswith("goal_validation_receipt:")
        )
        if len(receipt_refs) != 1:
            raise PlatformSourceLineageError(
                "compiler lineage must bind exactly one GOAL validation receipt"
            )
        governance_ref = receipt_refs[0]
        try:
            receipt = self._validations.receipt(
                governance_ref,
                owner_user_id=owner,
            )
            decision = self._validations.validate_validation_ref(
                governance_ref,
                owner_user_id=owner,
                subject_qro_refs=(qro_ref,),
                graph_command_refs=(graph_ref,),
            )
        except Exception as exc:
            raise PlatformSourceLineageError(
                f"GOAL validation receipt lookup failed:{type(exc).__name__}"
            ) from exc
        if (
            _text(getattr(receipt, "owner_user_id", "")) != owner
            or _text(getattr(receipt, "validation_ref", "")) != governance_ref
            or not bool(getattr(decision, "accepted", False))
        ):
            raise PlatformSourceLineageError(
                "GOAL validation receipt is not an exact passed QRO/Graph gate"
            )

        return _CompilerLineage(
            qro=qro,
            graph_command=command,
            compiler_ir=ir,
            compiler_pass=compiler_pass,
            receipt=receipt,
            entry_source=entry_source,
            entrypoint_ref=entrypoint_ref,
            qro_ref=qro_ref,
            graph_ref=graph_ref,
            ir_ref=ir_ref,
            pass_ref=pass_ref,
            evidence_refs=_sorted_union(ir_evidence, pass_evidence),
            validation_refs=validation_refs,
            permission_refs=(ir_permission,),
            canonical_command_refs=_sorted_union(ir_canonical, pass_canonical),
            governance_ref=governance_ref,
        )

    def _strict_coverage(
        self,
        coverage: GoalEntrypointCoverageRecord,
    ) -> None:
        try:
            first = self._entrypoints.validate_real_backing(coverage)
            second = self._entrypoints.validate_real_backing(coverage)
        except Exception as exc:
            raise PlatformSourceLineageError(
                f"strict entrypoint coverage preflight failed:{type(exc).__name__}"
            ) from exc
        if first != second:
            raise PlatformSourceLineageError(
                "strict entrypoint coverage decision changed during preflight"
            )
        if not bool(getattr(first, "accepted", False)):
            codes = ",".join(
                sorted(
                    {
                        _text(getattr(item, "code", "goal_entrypoint_rejected"))
                        for item in tuple(getattr(first, "violations", ()) or ())
                    }
                )
            )
            raise PlatformSourceLineageError(
                "strict entrypoint coverage rejected"
                + (f":{codes}" if codes else "")
            )

    @staticmethod
    def _primary_asset_ref(
        row: str,
        qro_ref: str,
    ) -> str:
        if row != "M15":
            raise PlatformSourceLineageError(
                "RAG asset derivation is only proven for M15"
            )
        return qro_ref

    @staticmethod
    def _rag_semantics(document: AssetRAGDocument) -> dict[str, Any]:
        permission = document.permission.snapshot()
        return {
            "document_id": document.document_id,
            "source_id": document.source_id,
            "version": document.version,
            "title": document.title,
            "body": document.body,
            "projection": document.projection_value,
            "asset_ref": document.asset_ref,
            "permission": permission,
            "applicability": document.applicability,
            "source_kind": document.source_kind,
            "metadata": document.metadata,
            "evidence_label": document.evidence_label,
            "methodology_path": document.methodology_path,
        }

    def _rag_document(
        self,
        *,
        owner: str,
        row: str,
        qro_ref: str,
        lifecycle_ref: str,
        math_spine_ref: str,
        specifics: dict[str, str],
        coverage: GoalEntrypointCoverageRecord,
        lineage: _CompilerLineage,
    ) -> AssetRAGDocument:
        capability = {
            "schema_version": 1,
            "m_row": row,
            "source_coverage_ref": coverage.coverage_ref,
            "qro_ref": qro_ref,
            "research_graph_ref": lineage.graph_ref,
            "lifecycle_ref": lifecycle_ref,
            "governance_ref": lineage.governance_ref,
            "math_spine_ref": math_spine_ref,
            "evidence_refs": list(lineage.evidence_refs),
            "specific_refs": {key: specifics[key] for key in SPECIFIC_REQUIRED_REFS[row]},
        }
        metadata = {_PLATFORM_METADATA_KEY: capability}
        content_digest = "sha256:" + _sha256(metadata)
        asset_ref = self._primary_asset_ref(
            row,
            qro_ref,
        )
        allowed_assets = tuple(
            dict.fromkeys(
                (
                    asset_ref,
                    qro_ref,
                    lifecycle_ref,
                    math_spine_ref,
                    *(specifics[key] for key in SPECIFIC_REQUIRED_REFS[row]),
                )
            )
        )
        return AssetRAGDocument(
            source_id=f"platform_source_lineage:{row}",
            version=f"{PLATFORM_SOURCE_LINEAGE_VERSION}.{content_digest.removeprefix('sha256:')}",
            title=f"GOAL section 14 {row} platform source lineage",
            body=f"Server-derived platform source metadata digest {content_digest}.",
            projection="research",
            asset_ref=asset_ref,
            permission=RAGPermission(
                allowed_users=(owner,),
                allowed_assets=allowed_assets,
                permission_tags=("platform_source_lineage",),
            ),
            applicability=f"GOAL section 14 {row} candidate context only",
            source_kind="server_derived_platform_source_lineage",
            metadata=metadata,
            evidence_label="candidate_context",
        )

    def _resolve_states(
        self,
        *,
        owner: str,
        record: PlatformCapabilityRecord,
        include_rag: bool,
    ) -> tuple[PlatformRowSourceState, ...]:
        fields_and_refs = (
            ("qro_ref", _text(record.qro_ref)),
            ("research_graph_ref", _text(record.research_graph_ref)),
            ("lifecycle_ref", _text(record.lifecycle_ref)),
            ("governance_ref", _text(record.governance_ref)),
            *(((("rag_ref", _text(record.rag_ref)),)) if include_rag else ()),
            ("math_spine_ref", _text(record.math_spine_ref)),
            *(("evidence_ref", ref) for ref in record.evidence_refs),
            *((item.key, item.ref) for item in record.specific_refs),
        )
        states: list[PlatformRowSourceState] = []
        for field, ref in fields_and_refs:
            try:
                state = self._resolver.resolve_state(
                    field,
                    ref,
                    owner_user_id=owner,
                    record=record,
                )
            except Exception as exc:
                raise PlatformSourceLineageError(
                    f"typed source {field} preflight failed:{type(exc).__name__}"
                ) from exc
            if not isinstance(state, PlatformRowSourceState) or state.source_ref != ref:
                raise PlatformSourceLineageError(
                    f"typed source {field} returned an invalid state"
                )
            states.append(state)
        return tuple(states)

    def _resolve_twice(
        self,
        *,
        owner: str,
        record: PlatformCapabilityRecord,
        include_rag: bool,
    ) -> tuple[PlatformRowSourceState, ...]:
        first = self._resolve_states(
            owner=owner,
            record=record,
            include_rag=include_rag,
        )
        second = self._resolve_states(
            owner=owner,
            record=record,
            include_rag=include_rag,
        )
        if first != second:
            raise PlatformSourceLineageError(
                "typed platform sources changed during double resolution"
            )
        return first

    def _linkage_twice(
        self,
        *,
        owner: str,
        record: PlatformCapabilityRecord,
        coverage: GoalEntrypointCoverageRecord,
        rag_document: AssetRAGDocument,
    ) -> None:
        try:
            first = tuple(
                self._resolver.linkage_violations(
                    record,
                    owner_user_id=owner,
                    source_coverage=coverage,
                    rag_document=rag_document,
                )
                or ()
            )
            second = tuple(
                self._resolver.linkage_violations(
                    record,
                    owner_user_id=owner,
                    source_coverage=coverage,
                    rag_document=rag_document,
                )
                or ()
            )
        except Exception as exc:
            raise PlatformSourceLineageError(
                f"typed platform linkage validation failed:{type(exc).__name__}"
            ) from exc
        if first != second:
            raise PlatformSourceLineageError(
                "typed platform linkage decision changed during validation"
            )
        if first:
            raise PlatformSourceLineageError(";".join(_text(item) for item in first))

    def _coverage_persisted(
        self,
        coverage: GoalEntrypointCoverageRecord,
        *,
        owner: str,
    ) -> bool:
        try:
            return self._entrypoints.coverage(
                coverage.coverage_ref,
                owner=owner,
            ) == coverage
        except Exception:
            return False

    def _evidence_persisted(
        self,
        evidence: PlatformSourceLineageEvidenceRecord,
        *,
        owner: str,
    ) -> bool:
        try:
            return self._evidence.evidence(
                evidence.evidence_ref,
                owner_user_id=owner,
            ) == evidence
        except Exception:
            return False

    def _derive_evidence_twice(
        self,
        *,
        owner: str,
        row: str,
        lifecycle_ref: str,
        math_spine_ref: str,
        specifics: dict[str, str],
        lineage: _CompilerLineage,
    ) -> PlatformSourceLineageEvidenceRecord:
        parameters = {
            "source_resolver": self._resolver,
            "owner_user_id": owner,
            "m_row": row,
            "entry_source": lineage.entry_source,
            "entrypoint_ref": lineage.entrypoint_ref,
            "qro_ref": lineage.qro_ref,
            "research_graph_ref": lineage.graph_ref,
            "lifecycle_ref": lifecycle_ref,
            "governance_ref": lineage.governance_ref,
            "math_spine_ref": math_spine_ref,
            "specific_refs": tuple(
                PlatformSpecificRef(key=key, ref=specifics[key])
                for key in SPECIFIC_REQUIRED_REFS[row]
            ),
        }
        first = derive_platform_source_lineage_evidence(**parameters)
        second = derive_platform_source_lineage_evidence(**parameters)
        if first != second:
            raise PlatformSourceLineageError(
                "independent evidence sources changed during double resolution"
            )
        if lineage.evidence_refs != (first.evidence_ref,):
            raise PlatformSourceLineageError(
                "compiler IR/pass must cite exactly the independently derived "
                "content-bound evidence ref"
            )
        first_decision = self._evidence.validate_current(
            first,
            owner_user_id=owner,
        )
        second_decision = self._evidence.validate_current(
            first,
            owner_user_id=owner,
        )
        if first_decision != second_decision:
            raise PlatformSourceLineageError(
                "independent evidence decision changed during preflight"
            )
        if not first_decision.accepted:
            raise PlatformSourceLineageError(
                ";".join(
                    f"{item.code}:{item.field}:{item.ref}"
                    for item in first_decision.violations
                )
            )
        return first

    def _rag_persisted(
        self,
        document: AssetRAGDocument,
        *,
        owner: str,
    ) -> bool:
        try:
            stored = self._rag.document_for_owner(
                document.document_id,
                owner_user_id=owner,
                require_current=True,
            )
        except Exception:
            return False
        return self._rag_semantics(stored) == self._rag_semantics(document)

    def record_current(
        self,
        *,
        owner_user_id: str,
        selection: PlatformSourceLineageSelection,
    ) -> PlatformSourceLineageResult:
        with acquire_goal_proof_head_lock(self._proof_head_ledger_path):
            return self._record_current_under_proof_head(
                owner_user_id=owner_user_id,
                selection=selection,
            )

    def _record_current_under_proof_head(
        self,
        *,
        owner_user_id: str,
        selection: PlatformSourceLineageSelection,
    ) -> PlatformSourceLineageResult:
        """Record evidence, coverage, and RAG, then return the revalidated row.

        No callback is invoked until all selected pre-existing refs, the unique
        compiler lineage, the GOAL receipt, and the independent evidence inputs
        have passed two read-only resolutions.
        """

        owner, row, qro_ref, lifecycle_ref, math_spine_ref, specifics = (
            self._selection(owner_user_id, selection)
        )
        projection_ref = specifics["typed_canvas_projection_ref"]
        first_head = self._projection_head(
            owner=owner,
            qro_ref=qro_ref,
            projection_ref=projection_ref,
        )
        second_head = self._projection_head(
            owner=owner,
            qro_ref=qro_ref,
            projection_ref=projection_ref,
        )
        if first_head != second_head:
            raise PlatformSourceLineageError(
                "current Research Graph projection changed during preflight"
            )
        head = first_head
        first_lineage = self._compiler_lineage(
            owner=owner,
            qro_ref=qro_ref,
            graph_ref=head.graph_ref,
            math_spine_ref=math_spine_ref,
        )
        second_lineage = self._compiler_lineage(
            owner=owner,
            qro_ref=qro_ref,
            graph_ref=head.graph_ref,
            math_spine_ref=math_spine_ref,
        )
        if first_lineage != second_lineage:
            raise PlatformSourceLineageError(
                "QRO/Graph/compiler/receipt lineage changed during preflight"
            )
        lineage = first_lineage
        evidence = self._derive_evidence_twice(
            owner=owner,
            row=row,
            lifecycle_ref=lifecycle_ref,
            math_spine_ref=math_spine_ref,
            specifics=specifics,
            lineage=lineage,
        )

        coverage_ref = goal_entrypoint_coverage_identity(
            entry_source=lineage.entry_source,
            entrypoint_ref=lineage.entrypoint_ref,
            goal_sections=("§14",),
            qro_refs=(qro_ref,),
            research_graph_command_refs=(lineage.graph_ref,),
            compiler_ir_refs=(lineage.ir_ref,),
            compiler_pass_refs=(lineage.pass_ref,),
        )
        coverage = GoalEntrypointCoverageRecord(
            coverage_ref=coverage_ref,
            entry_source=lineage.entry_source,
            entrypoint_ref=lineage.entrypoint_ref,
            goal_sections=("§14",),
            qro_refs=(qro_ref,),
            research_graph_command_refs=(lineage.graph_ref,),
            compiler_ir_refs=(lineage.ir_ref,),
            compiler_pass_refs=(lineage.pass_ref,),
            evidence_refs=(evidence.evidence_ref,),
            validation_refs=lineage.validation_refs,
            permission_refs=lineage.permission_refs,
            replay_refs=(
                f"replay:research_graph:{lineage.graph_ref}",
                f"replay:compiler_ir:{lineage.ir_ref}",
                f"replay:compiler_pass:{lineage.pass_ref}",
            ),
            canonical_command_refs=lineage.canonical_command_refs,
            lifecycle_refs=(lifecycle_ref,),
            recorded_by=owner,
            claims_full_product_entrypoint=False,
            silent_mock_fallback_used=False,
            raw_payload_persisted=False,
        )
        rag_document = self._rag_document(
            owner=owner,
            row=row,
            qro_ref=qro_ref,
            lifecycle_ref=lifecycle_ref,
            math_spine_ref=math_spine_ref,
            specifics=specifics,
            coverage=coverage,
            lineage=lineage,
        )
        capability = PlatformCapabilityRecord(
            m_row=row,
            qro_ref=qro_ref,
            research_graph_ref=lineage.graph_ref,
            lifecycle_ref=lifecycle_ref,
            governance_ref=lineage.governance_ref,
            rag_ref=rag_document.document_id,
            math_spine_ref=math_spine_ref,
            evidence_refs=(evidence.evidence_ref,),
            specific_refs=tuple(
                PlatformSpecificRef(key=key, ref=specifics[key])
                for key in SPECIFIC_REQUIRED_REFS[row]
            ),
        )
        shape = validate_platform_capability(capability)
        if not shape.accepted:
            raise PlatformSourceLineageError(
                ";".join(
                    f"{item.code}:{item.field}"
                    for item in shape.violations
                )
            )
        self._linkage_twice(
            owner=owner,
            record=capability,
            coverage=coverage,
            rag_document=rag_document,
        )

        try:
            recorded_evidence = self._evidence.record_evidence(evidence)
            if recorded_evidence != evidence or not self._evidence_persisted(
                evidence,
                owner=owner,
            ):
                raise PlatformSourceLineageError(
                    "evidence ledger did not persist the exact derived record"
                )
            self._strict_coverage(coverage)
            self._resolve_twice(
                owner=owner,
                record=capability,
                include_rag=False,
            )
            recorded_coverage = self._record_coverage(coverage)
            if recorded_coverage != coverage or not self._coverage_persisted(
                coverage,
                owner=owner,
            ):
                raise PlatformSourceLineageError(
                    "coverage callback did not persist the exact derived record"
                )

            supersedes_document_id: str | None = None
            try:
                current = self._rag.current_document_for_owner(
                    owner_user_id=owner,
                    source_id=rag_document.source_id,
                    asset_ref=rag_document.asset_ref,
                    projection=rag_document.projection,
                )
            except KeyError:
                current = None
            if current is not None and current.document_id != rag_document.document_id:
                supersedes_document_id = current.document_id
            recorded_rag = self._record_rag_document(
                rag_document,
                owner_user_id=owner,
                supersedes_document_id=supersedes_document_id,
            )
            if (
                not isinstance(recorded_rag, AssetRAGDocument)
                or self._rag_semantics(recorded_rag)
                != self._rag_semantics(rag_document)
                or not self._rag_persisted(rag_document, owner=owner)
            ):
                raise PlatformSourceLineageError(
                    "RAG callback did not persist the exact derived document"
                )
            rag_document = recorded_rag

            post_head_first = self._projection_head(
                owner=owner,
                qro_ref=qro_ref,
                projection_ref=projection_ref,
            )
            post_head_second = self._projection_head(
                owner=owner,
                qro_ref=qro_ref,
                projection_ref=projection_ref,
            )
            if post_head_first != post_head_second or post_head_first != head:
                raise PlatformSourceLineageError(
                    "current Research Graph projection changed during commit"
                )
            post_lineage_first = self._compiler_lineage(
                owner=owner,
                qro_ref=qro_ref,
                graph_ref=head.graph_ref,
                math_spine_ref=math_spine_ref,
            )
            post_lineage_second = self._compiler_lineage(
                owner=owner,
                qro_ref=qro_ref,
                graph_ref=head.graph_ref,
                math_spine_ref=math_spine_ref,
            )
            if (
                post_lineage_first != post_lineage_second
                or post_lineage_first != lineage
            ):
                raise PlatformSourceLineageError(
                    "QRO/Graph/compiler/receipt lineage changed during commit"
                )
            post_evidence_first = self._evidence.validate_current(
                evidence,
                owner_user_id=owner,
            )
            post_evidence_second = self._evidence.validate_current(
                evidence,
                owner_user_id=owner,
            )
            if (
                post_evidence_first != post_evidence_second
                or not post_evidence_first.accepted
            ):
                raise PlatformSourceLineageError(
                    "independent evidence changed during commit"
                )
            self._strict_coverage(coverage)
            source_states = self._resolve_twice(
                owner=owner,
                record=capability,
                include_rag=True,
            )
            self._linkage_twice(
                owner=owner,
                record=capability,
                coverage=coverage,
                rag_document=rag_document,
            )
        except Exception as exc:
            if isinstance(exc, PlatformSourceLineageCommitError):
                raise
            raise PlatformSourceLineageCommitError(
                "platform source lineage write/postflight failed:"
                f"{type(exc).__name__}:{exc}",
                evidence_persisted=self._evidence_persisted(
                    evidence,
                    owner=owner,
                ),
                coverage_persisted=self._coverage_persisted(
                    coverage,
                    owner=owner,
                ),
                rag_persisted=self._rag_persisted(
                    rag_document,
                    owner=owner,
                ),
            ) from exc

        return PlatformSourceLineageResult(
            evidence_record=evidence,
            coverage=coverage,
            rag_document=rag_document,
            capability_record=capability,
            source_states=source_states,
        )


__all__ = [
    "PLATFORM_SOURCE_LINEAGE_PROVEN_ROWS",
    "PLATFORM_SOURCE_LINEAGE_EVIDENCE_VERSION",
    "PLATFORM_SOURCE_LINEAGE_VERSION",
    "PersistentPlatformSourceLineageEvidenceRegistry",
    "PlatformSourceLineageCommitError",
    "PlatformSourceLineageEvidenceDecision",
    "PlatformSourceLineageEvidenceRecord",
    "PlatformSourceLineageEvidenceViolation",
    "PlatformSourceLineageError",
    "PlatformSourceLineageProducer",
    "PlatformSourceLineageResult",
    "PlatformSourceLineageSelection",
    "derive_platform_source_lineage_evidence",
    "platform_source_lineage_evidence_from_dict",
    "platform_source_lineage_evidence_to_dict",
    "validate_platform_source_lineage_evidence_shape",
]
