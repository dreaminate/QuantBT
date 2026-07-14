"""Policy-driven three-ledger finalizer for GOAL section 14 row sources.

The public write contract is deliberately small: an authenticated owner, a
canonical M row, and one business anchor.  Coverage, RAG, governance,
Mathematical Spine, evidence, and row-specific refs are never accepted from
the caller.  An injected server policy resolves those refs from typed stores
and is responsible for the row's domain semantics.

The finalizer selects one strictly backed *business* entrypoint coverage row,
derives a new section-14 coverage row and reserved RAG document, then records
the row-source certification.  The three ledgers are append-only and cannot be
updated transactionally, so failures expose the exact observed persistence
state and retries are content-idempotent.

This module does not register policies, routes, or business producers.  It
also never treats its own metadata envelope as domain evidence.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, is_dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Protocol

from .asset_rag import (
    AssetRAGDocument,
    PersistentResearchAssetRAGIndex,
    RAGPermission,
)
from .goal_coverage import (
    GoalEntrypointCoverageRecord,
    PersistentGoalEntrypointCoverageRegistry,
    goal_entrypoint_coverage_identity,
)
from .goal_proof_head_lock import acquire_goal_proof_head_lock
from .platform_coverage import (
    REQUIRED_PLATFORM_ROWS,
    SPECIFIC_REQUIRED_REFS,
    PlatformCapabilityRecord,
    PlatformSpecificRef,
    validate_platform_capability,
)
from .platform_row_producers import PlatformRowSourceState
from .platform_row_sources import PlatformRowSourceCertification
from .platform_typed_sources import (
    RealPlatformTypedSourceResolver,
    platform_compiler_snapshot,
)
from .ref_resolution import is_placeholder_ref
from .spine import EntrySource


PLATFORM_SOURCE_LINEAGE_CORE_VERSION = "platform_source_lineage.v1"
_PLATFORM_METADATA_KEY = "platform_capability"
_ROW_POLICY_METADATA_KEY = "row_policy"
_UPSTREAM_RAG_METADATA_KEY = "upstream_business_rag"
_RESERVED_SOURCE_PREFIX = "platform_source_lineage:"
_RESERVED_SOURCE_KIND = "server_derived_platform_source_lineage"
_ROW_TOP_LEVEL_METADATA_ALLOWLIST: dict[str, tuple[str, ...]] = {
    "M4-M5": ("formula_hash",),
}


def _text(value: Any) -> str:
    return str(getattr(value, "value", value) or "").strip()


def _canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _jsonable(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, Path):
        return value.as_posix()
    if is_dataclass(value):
        return _jsonable(asdict(value))
    if isinstance(value, dict):
        return {str(key): _jsonable(child) for key, child in value.items()}
    if isinstance(value, (tuple, list)):
        return [_jsonable(child) for child in value]
    raise TypeError(f"platform source-lineage metadata is not JSON-safe: {type(value).__name__}")


def _sha256(value: Any) -> str:
    return hashlib.sha256(_canonical_json(_jsonable(value)).encode("utf-8")).hexdigest()


def _stable_exact(value: Any, *, field: str) -> str:
    raw = str(getattr(value, "value", value) or "")
    normalized = raw.strip()
    if (
        not normalized
        or raw != normalized
        or any(ord(char) < 32 for char in normalized)
        or is_placeholder_ref(normalized)
    ):
        raise PlatformSourceLineageCoreError(f"{field} is not a stable real ref")
    return normalized


def _unique_refs(value: Any, *, field: str, required: bool = True) -> tuple[str, ...]:
    refs = tuple(_stable_exact(item, field=field) for item in tuple(value or ()))
    if required and not refs:
        raise PlatformSourceLineageCoreError(f"{field} is required")
    if len(refs) != len(set(refs)):
        raise PlatformSourceLineageCoreError(f"{field} contains duplicate refs")
    return refs


def _enum_text(value: Any) -> str:
    return _text(getattr(value, "value", value))


def _entrypoint_read_methods(view: Any) -> tuple[str, ...]:
    """Prefer canonical proof heads, retaining fixture compatibility."""

    if (
        getattr(view, "canonical_projection_available", None) is not False
        and callable(getattr(view, "canonical_records", None))
        and callable(getattr(view, "canonical_coverage", None))
    ):
        return ("canonical_records", "canonical_coverage", "validate_real_backing")
    return ("records", "coverage", "validate_real_backing")


def _entrypoint_records(view: Any, *, owner: str) -> tuple[Any, ...]:
    methods = _entrypoint_read_methods(view)
    return tuple(getattr(view, methods[0])(owner=owner) or ())


def _entrypoint_coverage(view: Any, ref: str, *, owner: str) -> Any:
    methods = _entrypoint_read_methods(view)
    return getattr(view, methods[1])(ref, owner=owner)


def _document_semantics(document: AssetRAGDocument) -> dict[str, Any]:
    return {
        "document_id": document.document_id,
        "source_id": document.source_id,
        "version": document.version,
        "title": document.title,
        "body": document.body,
        "projection": document.projection_value,
        "asset_ref": document.asset_ref,
        "permission": document.permission.snapshot(),
        "applicability": document.applicability,
        "source_kind": document.source_kind,
        "metadata": document.metadata,
        "evidence_label": document.evidence_label,
        "methodology_path": document.methodology_path,
    }


def _strings(value: Any) -> set[str]:
    found: set[str] = set()
    if isinstance(value, str):
        token = value.strip()
        if token:
            found.add(token)
    elif isinstance(value, dict):
        for key, child in value.items():
            found.update(_strings(key))
            found.update(_strings(child))
    elif isinstance(value, (tuple, list, set, frozenset)):
        for child in value:
            found.update(_strings(child))
    elif value is not None and is_dataclass(value):
        found.update(_strings(asdict(value)))
    return found


class PlatformSourceLineageCoreError(ValueError):
    """The server-resolved anchor does not form one current typed lineage."""


class PlatformSourceLineageCoreCommitError(PlatformSourceLineageCoreError):
    """The non-atomic write phase failed; flags report observed durable state."""

    def __init__(
        self,
        message: str,
        *,
        coverage_persisted: bool,
        rag_persisted: bool,
        row_source_persisted: bool,
    ) -> None:
        super().__init__(message)
        self.coverage_persisted = bool(coverage_persisted)
        self.rag_persisted = bool(rag_persisted)
        self.row_source_persisted = bool(row_source_persisted)


@dataclass(frozen=True)
class UpstreamBusinessRAGBinding:
    """A pre-existing business retrieval used before final platform proof exists."""

    usage_ref: str
    document_refs: tuple[str, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "document_refs", tuple(self.document_refs))


@dataclass(frozen=True)
class PlatformSourceLineagePolicyResolution:
    """Internal server policy result; this is never a public request payload.

    The policy may select proof objects only after resolving ``anchor_ref`` from
    its typed business stores.  Graph, compiler, governance, evidence, and
    coverage refs are intentionally absent and are derived by this core from
    the exact business entrypoint coverage.
    """

    m_row: str
    anchor_ref: str
    qro_ref: str
    business_entry_source: str
    business_entrypoint_ref: str
    lifecycle_ref: str
    math_spine_ref: str
    specific_refs: tuple[PlatformSpecificRef, ...]
    primary_rag_asset_ref: str
    row_policy_metadata: tuple[tuple[str, Any], ...] = ()
    upstream_business_rag: UpstreamBusinessRAGBinding | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "specific_refs", tuple(self.specific_refs))
        object.__setattr__(
            self,
            "row_policy_metadata",
            tuple((str(key), value) for key, value in self.row_policy_metadata),
        )


class PlatformSourceLineagePolicyResolver(Protocol):
    """Server-owned row policy used by :class:`PlatformSourceLineageFinalizer`."""

    def resolve(
        self,
        *,
        owner_user_id: str,
        m_row: str,
        anchor_ref: str,
    ) -> PlatformSourceLineagePolicyResolution: ...

    def semantic_violations(
        self,
        resolution: PlatformSourceLineagePolicyResolution,
        *,
        owner_user_id: str,
        business_coverage: GoalEntrypointCoverageRecord,
        capability_record: PlatformCapabilityRecord,
        rag_document: AssetRAGDocument,
    ) -> tuple[str, ...]: ...


@dataclass(frozen=True)
class PlatformSourceLineageFinalizationResult:
    business_coverage_ref: str
    coverage: GoalEntrypointCoverageRecord
    rag_document: AssetRAGDocument
    certification: PlatformRowSourceCertification
    preexisting_source_states: tuple[PlatformRowSourceState, ...]


@dataclass(frozen=True)
class _UpstreamRAGSnapshot:
    usage: Any
    documents: tuple[AssetRAGDocument, ...]


CoverageWriter = Callable[[GoalEntrypointCoverageRecord], GoalEntrypointCoverageRecord]
RAGWriter = Callable[..., AssetRAGDocument]
CertificationWriter = Callable[..., PlatformRowSourceCertification]
RegistryViewFactory = Callable[[], Any]


class PlatformSourceLineageFinalizer:
    """Derive and persist one policy-resolved section-14 source lineage.

    ``record_current`` is the only mutation entrypoint.  Its arguments are not
    proof refs: the policy must derive every proof object from ``anchor_ref``.
    """

    def __init__(
        self,
        *,
        policy_resolver: PlatformSourceLineagePolicyResolver,
        entrypoint_registry: Any,
        rag_index: Any,
        row_source_registry: Any,
        source_resolver: RealPlatformTypedSourceResolver,
        record_coverage: CoverageWriter | None = None,
        record_rag_document: RAGWriter | None = None,
        record_certification: CertificationWriter | None = None,
        entrypoint_view_factory: RegistryViewFactory | None = None,
        rag_view_factory: RegistryViewFactory | None = None,
    ) -> None:
        if not callable(getattr(policy_resolver, "resolve", None)):
            raise TypeError("policy_resolver.resolve is required")
        if not callable(getattr(policy_resolver, "semantic_violations", None)):
            raise TypeError("policy_resolver.semantic_violations is required")
        if not isinstance(source_resolver, RealPlatformTypedSourceResolver):
            raise TypeError("source_resolver must be RealPlatformTypedSourceResolver")
        for value, method, label in (
            (
                entrypoint_registry,
                _entrypoint_read_methods(entrypoint_registry)[0],
                "entrypoint_registry records",
            ),
            (
                entrypoint_registry,
                _entrypoint_read_methods(entrypoint_registry)[1],
                "entrypoint_registry coverage",
            ),
            (
                entrypoint_registry,
                "validate_real_backing",
                "entrypoint_registry.validate_real_backing",
            ),
            (rag_index, "add_for_owner", "rag_index.add_for_owner"),
            (rag_index, "document_for_owner", "rag_index.document_for_owner"),
            (
                rag_index,
                "current_document_for_owner",
                "rag_index.current_document_for_owner",
            ),
            (
                rag_index,
                "strict_usage_for_owner",
                "rag_index.strict_usage_for_owner",
            ),
            (
                rag_index,
                "validate_current_usage",
                "rag_index.validate_current_usage",
            ),
            (
                row_source_registry,
                "record_current",
                "row_source_registry.record_current",
            ),
            (
                row_source_registry,
                "resolve_current_row",
                "row_source_registry.resolve_current_row",
            ),
            (
                row_source_registry,
                "current_certifications",
                "row_source_registry.current_certifications",
            ),
        ):
            if not callable(getattr(value, method, None)):
                raise TypeError(f"{label} is required")
        self._policy = policy_resolver
        self._entrypoints = entrypoint_registry
        self._proof_head_ledger_path = Path(entrypoint_registry.path).expanduser().absolute()
        self._rag = rag_index
        self._rows = row_source_registry
        self._resolver = source_resolver
        self._record_coverage = record_coverage or entrypoint_registry.record_coverage
        self._record_rag = record_rag_document or rag_index.add_for_owner
        self._record_certification = (
            record_certification or row_source_registry.record_current
        )
        if entrypoint_view_factory is not None and not callable(
            entrypoint_view_factory
        ):
            raise TypeError("entrypoint_view_factory must be callable")
        if rag_view_factory is not None and not callable(rag_view_factory):
            raise TypeError("rag_view_factory must be callable")
        self._entrypoint_view_factory = entrypoint_view_factory
        self._rag_view_factory = rag_view_factory

    @staticmethod
    def _require_methods(
        value: Any,
        methods: tuple[str, ...],
        *,
        label: str,
    ) -> Any:
        missing = tuple(
            method
            for method in methods
            if not callable(getattr(value, method, None))
        )
        if missing:
            raise PlatformSourceLineageCoreError(
                f"fresh {label} view is missing methods:{','.join(missing)}"
            )
        return value

    def _entrypoint_view(self) -> Any:
        """Open a disk-current coverage view; never trust a cached registry."""

        try:
            if self._entrypoint_view_factory is not None:
                view = self._entrypoint_view_factory()
            elif isinstance(
                self._entrypoints,
                PersistentGoalEntrypointCoverageRegistry,
            ):
                proof_projection = getattr(
                    self._entrypoints,
                    "_proof_projection",
                    None,
                )
                view = PersistentGoalEntrypointCoverageRegistry(
                    self._entrypoints.path,
                    resolver=self._entrypoints._resolver,
                    proof_ledger=getattr(proof_projection, "ledger", None),
                    legacy_read_only=bool(
                        getattr(self._entrypoints, "_legacy_read_only", False)
                    ),
                )
            else:
                refresh = getattr(self._entrypoints, "refresh", None)
                if not callable(refresh):
                    raise PlatformSourceLineageCoreError(
                        "entrypoint registry requires a fresh-view factory"
                    )
                refresh()
                view = self._entrypoints
        except PlatformSourceLineageCoreError:
            raise
        except Exception as exc:
            raise PlatformSourceLineageCoreError(
                f"fresh entrypoint registry view failed:{type(exc).__name__}"
            ) from exc
        return self._require_methods(
            view,
            _entrypoint_read_methods(view),
            label="entrypoint registry",
        )

    def _refresh_primary_entrypoints(self) -> None:
        """Synchronize the registry embedded in the row-source writer."""

        try:
            refresh = getattr(self._entrypoints, "refresh", None)
            if callable(refresh):
                refresh()
                return
            if isinstance(
                self._entrypoints,
                PersistentGoalEntrypointCoverageRegistry,
            ):
                self._entrypoints._load_existing()
                return
        except Exception as exc:
            raise PlatformSourceLineageCoreError(
                f"entrypoint registry refresh failed:{type(exc).__name__}"
            ) from exc

    def _rag_view(self) -> Any:
        """Return a disk-current RAG view and refresh the resolver's instance."""

        try:
            primary_refresh = getattr(self._rag, "refresh", None)
            if callable(primary_refresh):
                primary_refresh()
            if self._rag_view_factory is not None:
                view = self._rag_view_factory()
            elif isinstance(self._rag, PersistentResearchAssetRAGIndex):
                view = self._rag
            else:
                if not callable(primary_refresh):
                    raise PlatformSourceLineageCoreError(
                        "RAG index requires a fresh-view factory"
                    )
                view = self._rag
        except PlatformSourceLineageCoreError:
            raise
        except Exception as exc:
            raise PlatformSourceLineageCoreError(
                f"fresh RAG index view failed:{type(exc).__name__}"
            ) from exc
        return self._require_methods(
            view,
            (
                "document_for_owner",
                "current_document_for_owner",
                "strict_usage_for_owner",
                "validate_current_usage",
            ),
            label="RAG index",
        )

    @staticmethod
    def _owner(value: Any) -> str:
        raw = str(value or "")
        owner = _stable_exact(raw, field="owner_user_id")
        if owner != raw:
            raise PlatformSourceLineageCoreError(
                "owner_user_id must be an exact stable string"
            )
        return owner

    @staticmethod
    def _row(value: Any) -> str:
        raw = str(getattr(value, "value", value) or "")
        row = raw.strip()
        if raw != row or row not in REQUIRED_PLATFORM_ROWS:
            raise PlatformSourceLineageCoreError(
                "m_row is not a canonical platform row"
            )
        return row

    def _validate_resolution(
        self,
        resolution: Any,
        *,
        owner: str,
        row: str,
        anchor_ref: str,
    ) -> PlatformSourceLineagePolicyResolution:
        if not isinstance(resolution, PlatformSourceLineagePolicyResolution):
            raise PlatformSourceLineageCoreError(
                "policy resolver returned an invalid resolution"
            )
        if (
            _stable_exact(resolution.m_row, field="policy.m_row") != row
            or _text(resolution.m_row) != row
        ):
            raise PlatformSourceLineageCoreError("policy resolution row mismatch")
        resolved_anchor = _stable_exact(
            resolution.anchor_ref,
            field="policy.anchor_ref",
        )
        if resolved_anchor != anchor_ref:
            raise PlatformSourceLineageCoreError("policy resolution anchor mismatch")
        qro_ref = _stable_exact(resolution.qro_ref, field="policy.qro_ref")
        entrypoint_ref = _stable_exact(
            resolution.business_entrypoint_ref,
            field="policy.business_entrypoint_ref",
        )
        entry_source = _enum_text(resolution.business_entry_source)
        if entry_source not in {item.value for item in EntrySource}:
            raise PlatformSourceLineageCoreError(
                "policy business entry source is unknown"
            )
        lifecycle_ref = _stable_exact(
            resolution.lifecycle_ref,
            field="policy.lifecycle_ref",
        )
        math_spine_ref = _stable_exact(
            resolution.math_spine_ref,
            field="policy.math_spine_ref",
        )
        primary_rag_asset_ref = _stable_exact(
            resolution.primary_rag_asset_ref,
            field="policy.primary_rag_asset_ref",
        )
        specifics = tuple(resolution.specific_refs)
        if any(not isinstance(item, PlatformSpecificRef) for item in specifics):
            raise PlatformSourceLineageCoreError(
                "policy specific refs must be PlatformSpecificRef records"
            )
        keys = tuple(
            _stable_exact(item.key, field="policy.specific_refs.key")
            for item in specifics
        )
        expected_keys = tuple(SPECIFIC_REQUIRED_REFS[row])
        if keys != expected_keys:
            raise PlatformSourceLineageCoreError(
                "policy specific refs must exactly follow the canonical row schema"
            )
        specific_values = _unique_refs(
            (item.ref for item in specifics),
            field="policy.specific_refs.ref",
        )
        metadata_keys = tuple(
            _stable_exact(key, field="policy.row_policy_metadata.key")
            for key, _value in resolution.row_policy_metadata
        )
        if len(metadata_keys) != len(set(metadata_keys)):
            raise PlatformSourceLineageCoreError(
                "policy row metadata contains duplicate keys"
            )
        if set(metadata_keys).intersection(
            {
                _PLATFORM_METADATA_KEY,
                _ROW_POLICY_METADATA_KEY,
                _UPSTREAM_RAG_METADATA_KEY,
            }
        ):
            raise PlatformSourceLineageCoreError(
                "policy row metadata uses a reserved provenance key"
            )
        metadata_values = tuple(
            _jsonable(value) for _key, value in resolution.row_policy_metadata
        )
        binding = resolution.upstream_business_rag
        normalized_binding = None
        if binding is not None:
            normalized_binding = UpstreamBusinessRAGBinding(
                usage_ref=_stable_exact(
                    binding.usage_ref,
                    field="upstream_rag.usage_ref",
                ),
                document_refs=_unique_refs(
                    binding.document_refs,
                    field="upstream_rag.document_refs",
                ),
            )
        return PlatformSourceLineagePolicyResolution(
            m_row=row,
            anchor_ref=resolved_anchor,
            qro_ref=qro_ref,
            business_entry_source=entry_source,
            business_entrypoint_ref=entrypoint_ref,
            lifecycle_ref=lifecycle_ref,
            math_spine_ref=math_spine_ref,
            specific_refs=tuple(
                PlatformSpecificRef(key=key, ref=ref)
                for key, ref in zip(keys, specific_values, strict=True)
            ),
            primary_rag_asset_ref=primary_rag_asset_ref,
            row_policy_metadata=tuple(
                (key, value)
                for key, value in zip(
                    metadata_keys,
                    metadata_values,
                    strict=True,
                )
            ),
            upstream_business_rag=normalized_binding,
        )

    def _resolve_policy_twice(
        self,
        *,
        owner: str,
        row: str,
        anchor_ref: str,
    ) -> PlatformSourceLineagePolicyResolution:
        try:
            first = self._validate_resolution(
                self._policy.resolve(
                    owner_user_id=owner,
                    m_row=row,
                    anchor_ref=anchor_ref,
                ),
                owner=owner,
                row=row,
                anchor_ref=anchor_ref,
            )
            second = self._validate_resolution(
                self._policy.resolve(
                    owner_user_id=owner,
                    m_row=row,
                    anchor_ref=anchor_ref,
                ),
                owner=owner,
                row=row,
                anchor_ref=anchor_ref,
            )
        except PlatformSourceLineageCoreError:
            raise
        except Exception as exc:
            raise PlatformSourceLineageCoreError(
                f"platform row policy resolution failed:{type(exc).__name__}"
            ) from exc
        if first != second:
            raise PlatformSourceLineageCoreError(
                "platform row policy changed during resolution"
            )
        return first

    def _strict_backing(self, coverage: GoalEntrypointCoverageRecord) -> None:
        try:
            first = self._entrypoint_view().validate_real_backing(coverage)
            second = self._entrypoint_view().validate_real_backing(coverage)
        except Exception as exc:
            raise PlatformSourceLineageCoreError(
                f"entrypoint coverage strict validation failed:{type(exc).__name__}"
            ) from exc
        if first != second:
            raise PlatformSourceLineageCoreError(
                "entrypoint coverage decision changed during validation"
            )
        if not bool(getattr(first, "accepted", False)):
            codes = ",".join(
                sorted(
                    {
                        _text(getattr(item, "code", "entrypoint_rejected"))
                        for item in tuple(getattr(first, "violations", ()) or ())
                    }
                )
            )
            raise PlatformSourceLineageCoreError(
                "entrypoint coverage is not strictly backed"
                + (f":{codes}" if codes else "")
            )

    def _business_coverage(
        self,
        *,
        owner: str,
        resolution: PlatformSourceLineagePolicyResolution,
    ) -> GoalEntrypointCoverageRecord:
        try:
            records = _entrypoint_records(self._entrypoint_view(), owner=owner)
        except Exception as exc:
            raise PlatformSourceLineageCoreError(
                f"business coverage listing failed:{type(exc).__name__}"
            ) from exc
        policy_metadata = dict(resolution.row_policy_metadata)
        graph_ref = _stable_exact(
            policy_metadata.get("graph_command_ref"),
            field="policy.row_policy_metadata.graph_command_ref",
        )
        optional_lineage_keys = ("compiler_ir_ref", "compiler_pass_ref")
        present_optional = tuple(
            key for key in optional_lineage_keys if key in policy_metadata
        )
        if present_optional and present_optional != optional_lineage_keys:
            raise PlatformSourceLineageCoreError(
                "policy row metadata must bind both compiler IR and pass or neither"
            )
        compiler_ir_ref = (
            _stable_exact(
                policy_metadata["compiler_ir_ref"],
                field="policy.row_policy_metadata.compiler_ir_ref",
            )
            if present_optional
            else None
        )
        compiler_pass_ref = (
            _stable_exact(
                policy_metadata["compiler_pass_ref"],
                field="policy.row_policy_metadata.compiler_pass_ref",
            )
            if present_optional
            else None
        )
        business_coverage_ref = (
            _stable_exact(
                policy_metadata["business_coverage_ref"],
                field="policy.row_policy_metadata.business_coverage_ref",
            )
            if "business_coverage_ref" in policy_metadata
            else None
        )
        candidates = tuple(
            record
            for record in records
            if _text(getattr(record, "recorded_by", "")) == owner
            and _text(getattr(record, "entrypoint_ref", ""))
            == resolution.business_entrypoint_ref
            and _enum_text(getattr(record, "entry_source", ""))
            == resolution.business_entry_source
            and tuple(getattr(record, "qro_refs", ()) or ())
            == (resolution.qro_ref,)
            and tuple(
                getattr(record, "research_graph_command_refs", ()) or ()
            )
            == (graph_ref,)
            and (
                compiler_ir_ref is None
                or tuple(getattr(record, "compiler_ir_refs", ()) or ())
                == (compiler_ir_ref,)
            )
            and (
                compiler_pass_ref is None
                or tuple(getattr(record, "compiler_pass_refs", ()) or ())
                == (compiler_pass_ref,)
            )
            and (
                business_coverage_ref is None
                or _text(getattr(record, "coverage_ref", ""))
                == business_coverage_ref
            )
            and "§14" not in tuple(
                _enum_text(item)
                for item in tuple(getattr(record, "goal_sections", ()) or ())
            )
        )
        if len(candidates) != 1:
            raise PlatformSourceLineageCoreError(
                "policy anchor must select exactly one non-§14 business coverage "
                "for its canonical entrypoint"
            )
        coverage = candidates[0]
        self._strict_backing(coverage)
        qro_refs = _unique_refs(coverage.qro_refs, field="business_coverage.qro_refs")
        graph_refs = _unique_refs(
            coverage.research_graph_command_refs,
            field="business_coverage.research_graph_command_refs",
        )
        ir_refs = _unique_refs(
            coverage.compiler_ir_refs,
            field="business_coverage.compiler_ir_refs",
        )
        pass_refs = _unique_refs(
            coverage.compiler_pass_refs,
            field="business_coverage.compiler_pass_refs",
        )
        if not all(len(refs) == 1 for refs in (qro_refs, graph_refs, ir_refs, pass_refs)):
            raise PlatformSourceLineageCoreError(
                "business coverage must bind exactly one QRO, graph, IR, and pass"
            )
        try:
            compiler = platform_compiler_snapshot(
                getattr(self._resolver, "_compiler"),
                owner=owner,
            )
            compiler_ir = compiler.ir(ir_refs[0])
            compiler_pass = compiler.compiler_pass(pass_refs[0])
        except Exception as exc:
            raise PlatformSourceLineageCoreError(
                "business coverage compiler lineage lookup failed:"
                f"{type(exc).__name__}"
            ) from exc
        if (
            tuple(getattr(compiler_ir, "source_qro_refs", ()) or ()) != qro_refs
            or tuple(getattr(compiler_ir, "graph_command_refs", ()) or ())
            != graph_refs
            or _text(getattr(compiler_ir, "owner", "")) != owner
            or tuple(getattr(compiler_pass, "input_qro_refs", ()) or ())
            != qro_refs
            or tuple(getattr(compiler_pass, "graph_command_refs", ()) or ())
            != graph_refs
            or _text(getattr(compiler_pass, "output_ir_ref", ""))
            != ir_refs[0]
            or _text(getattr(compiler_pass, "actor", "")) != owner
        ):
            raise PlatformSourceLineageCoreError(
                "business coverage compiler lineage is stale or recombined"
            )
        validation_refs = _unique_refs(
            coverage.validation_refs,
            field="business_coverage.validation_refs",
        )
        governance_refs = tuple(
            ref
            for ref in validation_refs
            if ref.startswith("goal_validation_receipt:")
        )
        if len(governance_refs) != 1:
            raise PlatformSourceLineageCoreError(
                "business coverage must bind exactly one durable GOAL validation receipt"
            )
        _unique_refs(
            coverage.evidence_refs,
            field="business_coverage.evidence_refs",
        )
        _unique_refs(
            coverage.permission_refs,
            field="business_coverage.permission_refs",
        )
        _unique_refs(
            coverage.replay_refs,
            field="business_coverage.replay_refs",
        )
        _unique_refs(
            coverage.canonical_command_refs,
            field="business_coverage.canonical_command_refs",
        )
        return coverage

    def _business_coverage_twice(
        self,
        *,
        owner: str,
        resolution: PlatformSourceLineagePolicyResolution,
    ) -> GoalEntrypointCoverageRecord:
        first = self._business_coverage(owner=owner, resolution=resolution)
        second = self._business_coverage(owner=owner, resolution=resolution)
        if first != second:
            raise PlatformSourceLineageCoreError(
                "business coverage changed during resolution"
            )
        return first

    @staticmethod
    def _derived_coverage(
        *,
        owner: str,
        resolution: PlatformSourceLineagePolicyResolution,
        business: GoalEntrypointCoverageRecord,
    ) -> GoalEntrypointCoverageRecord:
        qro_refs = tuple(business.qro_refs)
        graph_refs = tuple(business.research_graph_command_refs)
        ir_refs = tuple(business.compiler_ir_refs)
        pass_refs = tuple(business.compiler_pass_refs)
        rdp_refs = _unique_refs(
            business.rdp_refs,
            field="business_coverage.rdp_refs",
            required=False,
        )
        if resolution.m_row == "M18":
            selected_package = _stable_exact(
                resolution.lifecycle_ref,
                field="M18 policy lifecycle_ref",
            )
            policy_metadata = dict(resolution.row_policy_metadata)
            metadata_package = _stable_exact(
                policy_metadata.get("rdp_package_ref"),
                field="M18 policy rdp_package_ref",
            )
            if metadata_package != selected_package:
                raise PlatformSourceLineageCoreError(
                    "M18 policy RDP package is stale or recombined"
                )
            rdp_refs = (selected_package,)
        coverage_ref = goal_entrypoint_coverage_identity(
            entry_source=business.entry_source,
            entrypoint_ref=business.entrypoint_ref,
            goal_sections=("§14",),
            qro_refs=qro_refs,
            research_graph_command_refs=graph_refs,
            compiler_ir_refs=ir_refs,
            compiler_pass_refs=pass_refs,
        )
        return GoalEntrypointCoverageRecord(
            coverage_ref=coverage_ref,
            entry_source=business.entry_source,
            entrypoint_ref=business.entrypoint_ref,
            goal_sections=("§14",),
            qro_refs=qro_refs,
            research_graph_command_refs=graph_refs,
            compiler_ir_refs=ir_refs,
            compiler_pass_refs=pass_refs,
            evidence_refs=tuple(business.evidence_refs),
            validation_refs=tuple(business.validation_refs),
            permission_refs=tuple(business.permission_refs),
            replay_refs=(
                *(f"replay:research_graph:{ref}" for ref in graph_refs),
                *(f"replay:compiler_ir:{ref}" for ref in ir_refs),
                *(f"replay:compiler_pass:{ref}" for ref in pass_refs),
            ),
            canonical_command_refs=tuple(business.canonical_command_refs),
            lifecycle_refs=(resolution.lifecycle_ref,),
            rdp_refs=rdp_refs,
            recorded_by=owner,
            claims_full_product_entrypoint=False,
            silent_mock_fallback_used=False,
            raw_payload_persisted=False,
        )

    def _upstream_rag_snapshot(
        self,
        *,
        owner: str,
        row: str,
        binding: UpstreamBusinessRAGBinding | None,
    ) -> _UpstreamRAGSnapshot | None:
        if binding is None:
            return None
        try:
            rag = self._rag_view()
            usage = rag.strict_usage_for_owner(
                binding.usage_ref,
                owner_user_id=owner,
            )
            decision = rag.validate_current_usage(
                binding.usage_ref,
                owner_user_id=owner,
            )
        except Exception as exc:
            raise PlatformSourceLineageCoreError(
                f"upstream business RAG usage lookup failed:{type(exc).__name__}"
            ) from exc
        if not bool(getattr(decision, "accepted", False)):
            raise PlatformSourceLineageCoreError(
                "upstream business RAG usage is not current"
            )
        returned = tuple(
            _text(getattr(item, "document_id", ""))
            for item in tuple(getattr(usage, "returned_documents", ()) or ())
        )
        if returned != tuple(binding.document_refs):
            raise PlatformSourceLineageCoreError(
                "upstream business RAG usage/document binding is inexact"
            )
        documents: list[AssetRAGDocument] = []
        for ref in binding.document_refs:
            try:
                document = rag.document_for_owner(
                    ref,
                    owner_user_id=owner,
                    require_current=True,
                )
            except Exception as exc:
                raise PlatformSourceLineageCoreError(
                    f"upstream business RAG document lookup failed:{type(exc).__name__}"
                ) from exc
            if (
                document.source_id.startswith(_RESERVED_SOURCE_PREFIX)
                or document.source_kind == _RESERVED_SOURCE_KIND
            ):
                raise PlatformSourceLineageCoreError(
                    "upstream business RAG cannot be a reserved platform lineage document"
                )
            documents.append(document)
        return _UpstreamRAGSnapshot(usage=usage, documents=tuple(documents))

    def _upstream_rag_twice(
        self,
        *,
        owner: str,
        row: str,
        binding: UpstreamBusinessRAGBinding | None,
    ) -> _UpstreamRAGSnapshot | None:
        first = self._upstream_rag_snapshot(
            owner=owner,
            row=row,
            binding=binding,
        )
        second = self._upstream_rag_snapshot(
            owner=owner,
            row=row,
            binding=binding,
        )
        if first != second:
            raise PlatformSourceLineageCoreError(
                "upstream business RAG changed during resolution"
            )
        return first

    @staticmethod
    def _rag_document(
        *,
        owner: str,
        row: str,
        resolution: PlatformSourceLineagePolicyResolution,
        coverage: GoalEntrypointCoverageRecord,
    ) -> AssetRAGDocument:
        validation_refs = tuple(coverage.validation_refs)
        governance_refs = tuple(
            ref
            for ref in validation_refs
            if ref.startswith("goal_validation_receipt:")
        )
        capability = {
            "schema_version": 1,
            "m_row": row,
            "source_coverage_ref": coverage.coverage_ref,
            "qro_ref": coverage.qro_refs[0],
            "research_graph_ref": coverage.research_graph_command_refs[0],
            "lifecycle_ref": resolution.lifecycle_ref,
            "governance_ref": governance_refs[0],
            "math_spine_ref": resolution.math_spine_ref,
            "evidence_refs": list(coverage.evidence_refs),
            "specific_refs": {
                item.key: item.ref for item in resolution.specific_refs
            },
        }
        metadata: dict[str, Any] = {_PLATFORM_METADATA_KEY: capability}
        row_policy_metadata: dict[str, Any] = {}
        if resolution.row_policy_metadata:
            row_policy_metadata = _jsonable(
                dict(resolution.row_policy_metadata)
            )
            metadata[_ROW_POLICY_METADATA_KEY] = row_policy_metadata
        for key in _ROW_TOP_LEVEL_METADATA_ALLOWLIST.get(row, ()):
            if key not in row_policy_metadata:
                raise PlatformSourceLineageCoreError(
                    f"row policy metadata requires safe top-level projection:{key}"
                )
            value = row_policy_metadata[key]
            if key == "formula_hash" and (
                not isinstance(value, str)
                or len(value) != 16
                or any(char not in "0123456789abcdef" for char in value)
            ):
                raise PlatformSourceLineageCoreError(
                    "row policy formula_hash must be a lowercase 16-hex content hash"
                )
            metadata[key] = value
        binding = resolution.upstream_business_rag
        if binding is not None:
            metadata[_UPSTREAM_RAG_METADATA_KEY] = {
                "usage_ref": binding.usage_ref,
                "document_refs": list(binding.document_refs),
                "role": "upstream_business_context",
            }
        content_digest = "sha256:" + _sha256(metadata)
        allowed_assets = tuple(
            dict.fromkeys(
                (
                    resolution.primary_rag_asset_ref,
                    resolution.qro_ref,
                    resolution.lifecycle_ref,
                    resolution.math_spine_ref,
                    *(item.ref for item in resolution.specific_refs),
                )
            )
        )
        document = AssetRAGDocument(
            source_id=f"{_RESERVED_SOURCE_PREFIX}{row}",
            version=(
                f"{PLATFORM_SOURCE_LINEAGE_CORE_VERSION}."
                f"{content_digest.removeprefix('sha256:')}"
            ),
            title=f"GOAL section 14 {row} platform source lineage",
            body=f"Server-derived platform source metadata digest {content_digest}.",
            projection="research",
            asset_ref=resolution.primary_rag_asset_ref,
            permission=RAGPermission(
                allowed_users=(owner,),
                allowed_assets=allowed_assets,
                permission_tags=("platform_source_lineage",),
            ),
            applicability=f"GOAL section 14 {row} candidate context only",
            source_kind=_RESERVED_SOURCE_KIND,
            metadata=metadata,
            evidence_label="candidate_context",
        )
        if document.document_id in _strings(metadata):
            raise PlatformSourceLineageCoreError(
                "reserved RAG metadata cannot depend on its own document identity"
            )
        return document

    @staticmethod
    def _capability(
        *,
        row: str,
        resolution: PlatformSourceLineagePolicyResolution,
        coverage: GoalEntrypointCoverageRecord,
        rag_document: AssetRAGDocument,
    ) -> PlatformCapabilityRecord:
        governance_ref = next(
            ref
            for ref in coverage.validation_refs
            if ref.startswith("goal_validation_receipt:")
        )
        record = PlatformCapabilityRecord(
            m_row=row,
            qro_ref=coverage.qro_refs[0],
            research_graph_ref=coverage.research_graph_command_refs[0],
            lifecycle_ref=resolution.lifecycle_ref,
            governance_ref=governance_ref,
            rag_ref=rag_document.document_id,
            math_spine_ref=resolution.math_spine_ref,
            evidence_refs=tuple(coverage.evidence_refs),
            specific_refs=tuple(resolution.specific_refs),
        )
        decision = validate_platform_capability(record)
        if not decision.accepted:
            raise PlatformSourceLineageCoreError(
                ";".join(
                    f"{item.code}:{item.field}"
                    for item in decision.violations
                )
            )
        return record

    def _preexisting_states(
        self,
        *,
        owner: str,
        record: PlatformCapabilityRecord,
    ) -> tuple[PlatformRowSourceState, ...]:
        fields_and_refs = (
            ("qro_ref", _text(record.qro_ref)),
            ("research_graph_ref", _text(record.research_graph_ref)),
            ("lifecycle_ref", _text(record.lifecycle_ref)),
            ("governance_ref", _text(record.governance_ref)),
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
                raise PlatformSourceLineageCoreError(
                    f"preexisting typed source {field} failed:{type(exc).__name__}"
                ) from exc
            if not isinstance(state, PlatformRowSourceState) or state.source_ref != ref:
                raise PlatformSourceLineageCoreError(
                    f"preexisting typed source {field} returned an invalid state"
                )
            states.append(state)
        return tuple(states)

    def _preexisting_states_twice(
        self,
        *,
        owner: str,
        record: PlatformCapabilityRecord,
    ) -> tuple[PlatformRowSourceState, ...]:
        first = self._preexisting_states(owner=owner, record=record)
        second = self._preexisting_states(owner=owner, record=record)
        if first != second:
            raise PlatformSourceLineageCoreError(
                "preexisting typed sources changed during resolution"
            )
        return first

    def _policy_semantics_twice(
        self,
        *,
        owner: str,
        resolution: PlatformSourceLineagePolicyResolution,
        business: GoalEntrypointCoverageRecord,
        capability: PlatformCapabilityRecord,
        rag_document: AssetRAGDocument,
    ) -> None:
        def run() -> tuple[str, ...]:
            try:
                return tuple(
                    _text(item)
                    for item in tuple(
                        self._policy.semantic_violations(
                            resolution,
                            owner_user_id=owner,
                            business_coverage=business,
                            capability_record=capability,
                            rag_document=rag_document,
                        )
                        or ()
                    )
                    if _text(item)
                )
            except Exception as exc:
                raise PlatformSourceLineageCoreError(
                    f"platform row semantic resolver failed:{type(exc).__name__}"
                ) from exc

        first = run()
        second = run()
        if first != second:
            raise PlatformSourceLineageCoreError(
                "platform row semantic decision changed during resolution"
            )
        if first:
            raise PlatformSourceLineageCoreError(";".join(first))

    def _linkage_twice(
        self,
        *,
        owner: str,
        record: PlatformCapabilityRecord,
        coverage: GoalEntrypointCoverageRecord,
        rag_document: AssetRAGDocument,
    ) -> None:
        def run() -> tuple[str, ...]:
            try:
                return tuple(
                    _text(item)
                    for item in tuple(
                        self._resolver.linkage_violations(
                            record,
                            owner_user_id=owner,
                            source_coverage=coverage,
                            rag_document=rag_document,
                        )
                        or ()
                    )
                    if _text(item)
                )
            except Exception as exc:
                raise PlatformSourceLineageCoreError(
                    f"platform typed linkage resolver failed:{type(exc).__name__}"
                ) from exc

        first = run()
        second = run()
        if first != second:
            raise PlatformSourceLineageCoreError(
                "platform typed linkage decision changed during resolution"
            )
        if first:
            raise PlatformSourceLineageCoreError(";".join(first))

    def _lineage_still_current(
        self,
        *,
        owner: str,
        row: str,
        anchor_ref: str,
        resolution: PlatformSourceLineagePolicyResolution,
        business: GoalEntrypointCoverageRecord,
        coverage: GoalEntrypointCoverageRecord,
        capability: PlatformCapabilityRecord,
        rag_document: AssetRAGDocument,
        upstream: _UpstreamRAGSnapshot | None,
    ) -> tuple[PlatformRowSourceState, ...]:
        current_resolution = self._resolve_policy_twice(
            owner=owner,
            row=row,
            anchor_ref=anchor_ref,
        )
        if current_resolution != resolution:
            raise PlatformSourceLineageCoreError(
                "platform row policy changed during finalization"
            )
        current_business = self._business_coverage_twice(
            owner=owner,
            resolution=resolution,
        )
        if current_business != business:
            raise PlatformSourceLineageCoreError(
                "business coverage changed during finalization"
            )
        self._strict_backing(coverage)
        current_upstream = self._upstream_rag_twice(
            owner=owner,
            row=row,
            binding=resolution.upstream_business_rag,
        )
        if current_upstream != upstream:
            raise PlatformSourceLineageCoreError(
                "upstream business RAG changed during finalization"
            )
        states = self._preexisting_states_twice(owner=owner, record=capability)
        self._policy_semantics_twice(
            owner=owner,
            resolution=resolution,
            business=business,
            capability=capability,
            rag_document=rag_document,
        )
        return states

    def _coverage_persisted(
        self,
        coverage: GoalEntrypointCoverageRecord,
        *,
        owner: str,
    ) -> bool:
        try:
            stored = _entrypoint_coverage(
                self._entrypoint_view(),
                coverage.coverage_ref,
                owner=owner,
            )
            return stored == coverage
        except Exception:
            return False

    def _rag_persisted(
        self,
        document: AssetRAGDocument,
        *,
        owner: str,
    ) -> bool:
        try:
            stored = self._rag_view().document_for_owner(
                document.document_id,
                owner_user_id=owner,
                require_current=True,
            )
            return _document_semantics(stored) == _document_semantics(document)
        except Exception:
            return False

    def _row_source_persisted(
        self,
        *,
        owner: str,
        row: str,
        coverage: GoalEntrypointCoverageRecord,
        document: AssetRAGDocument,
        capability: PlatformCapabilityRecord,
    ) -> bool:
        try:
            current = tuple(
                self._rows.current_certifications(owner_user_id=owner)
            )
        except Exception:
            return False
        matches = tuple(item for item in current if item.m_row == row)
        return (
            len(matches) == 1
            and matches[0].source_coverage_ref == coverage.coverage_ref
            and matches[0].rag_ref == document.document_id
            and matches[0].resolved_row.record == capability
        )

    def _persist_rag(
        self,
        document: AssetRAGDocument,
        *,
        owner: str,
    ) -> AssetRAGDocument:
        if self._rag_persisted(document, owner=owner):
            return self._rag_view().document_for_owner(
                document.document_id,
                owner_user_id=owner,
                require_current=True,
            )
        try:
            current = self._rag_view().current_document_for_owner(
                owner_user_id=owner,
                source_id=document.source_id,
                asset_ref=document.asset_ref,
                projection=document.projection,
            )
        except KeyError:
            current = None
        supersedes = None if current is None else current.document_id
        stored = self._record_rag(
            document,
            owner_user_id=owner,
            supersedes_document_id=supersedes,
        )
        if (
            not isinstance(stored, AssetRAGDocument)
            or _document_semantics(stored) != _document_semantics(document)
        ):
            raise PlatformSourceLineageCoreError(
                "RAG writer did not return the exact derived document"
            )
        return stored

    def record_current(
        self,
        *,
        owner_user_id: str,
        m_row: str,
        anchor_ref: str,
    ) -> PlatformSourceLineageFinalizationResult:
        with acquire_goal_proof_head_lock(self._proof_head_ledger_path):
            return self._record_current_under_proof_head(
                owner_user_id=owner_user_id,
                m_row=m_row,
                anchor_ref=anchor_ref,
            )

    def _record_current_under_proof_head(
        self,
        *,
        owner_user_id: str,
        m_row: str,
        anchor_ref: str,
    ) -> PlatformSourceLineageFinalizationResult:
        """Finalize one current row from a server-resolved business anchor."""

        owner = self._owner(owner_user_id)
        row = self._row(m_row)
        anchor = _stable_exact(anchor_ref, field="anchor_ref")
        resolution = self._resolve_policy_twice(
            owner=owner,
            row=row,
            anchor_ref=anchor,
        )
        business = self._business_coverage_twice(
            owner=owner,
            resolution=resolution,
        )
        coverage = self._derived_coverage(
            owner=owner,
            resolution=resolution,
            business=business,
        )
        self._strict_backing(coverage)
        upstream = self._upstream_rag_twice(
            owner=owner,
            row=row,
            binding=resolution.upstream_business_rag,
        )
        rag_document = self._rag_document(
            owner=owner,
            row=row,
            resolution=resolution,
            coverage=coverage,
        )
        if (
            resolution.upstream_business_rag is not None
            and rag_document.document_id
            in resolution.upstream_business_rag.document_refs
        ):
            raise PlatformSourceLineageCoreError(
                "reserved RAG cannot be an input to its upstream business usage"
            )
        capability = self._capability(
            row=row,
            resolution=resolution,
            coverage=coverage,
            rag_document=rag_document,
        )
        preexisting_states = self._lineage_still_current(
            owner=owner,
            row=row,
            anchor_ref=anchor,
            resolution=resolution,
            business=business,
            coverage=coverage,
            capability=capability,
            rag_document=rag_document,
            upstream=upstream,
        )

        try:
            stored_coverage = self._record_coverage(coverage)
            self._refresh_primary_entrypoints()
            if stored_coverage != coverage or not self._coverage_persisted(
                coverage,
                owner=owner,
            ):
                raise PlatformSourceLineageCoreError(
                    "coverage writer did not persist the exact derived record"
                )
            self._lineage_still_current(
                owner=owner,
                row=row,
                anchor_ref=anchor,
                resolution=resolution,
                business=business,
                coverage=coverage,
                capability=capability,
                rag_document=rag_document,
                upstream=upstream,
            )

            rag_document = self._persist_rag(rag_document, owner=owner)
            if not self._rag_persisted(rag_document, owner=owner):
                raise PlatformSourceLineageCoreError(
                    "RAG writer did not persist the exact current document"
                )
            preexisting_states = self._lineage_still_current(
                owner=owner,
                row=row,
                anchor_ref=anchor,
                resolution=resolution,
                business=business,
                coverage=coverage,
                capability=capability,
                rag_document=rag_document,
                upstream=upstream,
            )
            self._resolver.resolve_state(
                "rag_ref",
                rag_document.document_id,
                owner_user_id=owner,
                record=capability,
            )
            self._linkage_twice(
                owner=owner,
                record=capability,
                coverage=coverage,
                rag_document=rag_document,
            )

            certification = self._record_certification(
                owner_user_id=owner,
                m_row=row,
                source_coverage_ref=coverage.coverage_ref,
                rag_ref=rag_document.document_id,
            )
            if not isinstance(certification, PlatformRowSourceCertification):
                raise PlatformSourceLineageCoreError(
                    "row-source writer returned an invalid certification"
                )
            if (
                certification.source_coverage_ref != coverage.coverage_ref
                or certification.rag_ref != rag_document.document_id
                or certification.resolved_row.record != capability
                or not self._row_source_persisted(
                    owner=owner,
                    row=row,
                    coverage=coverage,
                    document=rag_document,
                    capability=capability,
                )
            ):
                raise PlatformSourceLineageCoreError(
                    "row-source writer did not persist the exact derived certification"
                )
            first_current = self._rows.resolve_current_row(
                row,
                owner_user_id=owner,
            )
            second_current = self._rows.resolve_current_row(
                row,
                owner_user_id=owner,
            )
            if (
                first_current != second_current
                or first_current != certification.resolved_row
            ):
                raise PlatformSourceLineageCoreError(
                    "row-source certification changed during final resolution"
                )
            self._lineage_still_current(
                owner=owner,
                row=row,
                anchor_ref=anchor,
                resolution=resolution,
                business=business,
                coverage=coverage,
                capability=capability,
                rag_document=rag_document,
                upstream=upstream,
            )
            return PlatformSourceLineageFinalizationResult(
                business_coverage_ref=business.coverage_ref,
                coverage=coverage,
                rag_document=rag_document,
                certification=certification,
                preexisting_source_states=preexisting_states,
            )
        except Exception as exc:
            coverage_persisted = self._coverage_persisted(coverage, owner=owner)
            rag_persisted = self._rag_persisted(rag_document, owner=owner)
            row_source_persisted = self._row_source_persisted(
                owner=owner,
                row=row,
                coverage=coverage,
                document=rag_document,
                capability=capability,
            )
            raise PlatformSourceLineageCoreCommitError(
                f"platform source-lineage finalization failed:{type(exc).__name__}:{exc}",
                coverage_persisted=coverage_persisted,
                rag_persisted=rag_persisted,
                row_source_persisted=row_source_persisted,
            ) from exc


__all__ = [
    "PLATFORM_SOURCE_LINEAGE_CORE_VERSION",
    "PlatformSourceLineageCoreCommitError",
    "PlatformSourceLineageCoreError",
    "PlatformSourceLineageFinalizationResult",
    "PlatformSourceLineageFinalizer",
    "PlatformSourceLineagePolicyResolution",
    "PlatformSourceLineagePolicyResolver",
    "UpstreamBusinessRAGBinding",
]
