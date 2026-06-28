"""GOAL §14 M1-M21 platform coverage contracts."""

from __future__ import annotations

import json
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Protocol


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


def _str_tuple(value: Any) -> tuple[str, ...]:
    return tuple(str(item) for item in _tuple(value) if str(item or "").strip())


class PlatformRow(str, Enum):
    M1_M2 = "M1-M2"
    M3 = "M3"
    M4_M5 = "M4-M5"
    M6 = "M6"
    M7_M8 = "M7-M8"
    M9 = "M9"
    M10 = "M10"
    M11 = "M11"
    M12 = "M12"
    M13 = "M13"
    M14 = "M14"
    M15 = "M15"
    M16 = "M16"
    M17 = "M17"
    M18 = "M18"
    M19 = "M19"
    M20 = "M20"
    M21 = "M21"


REQUIRED_PLATFORM_ROWS = tuple(row.value for row in PlatformRow)

SPECIFIC_REQUIRED_REFS: dict[str, tuple[str, ...]] = {
    PlatformRow.M3.value: ("ingestion_skill_ref", "instrument_spec_ref"),
    PlatformRow.M6.value: ("model_passport_ref", "validation_dossier_ref"),
    PlatformRow.M7_M8.value: ("signal_contract_ref", "strategy_book_ref"),
    PlatformRow.M9.value: ("execution_boundary_ref", "market_capability_matrix_ref"),
    PlatformRow.M14.value: (
        "llm_gateway_ref",
        "model_routing_policy_ref",
        "credential_pool_ref",
        "theory_implementation_binding_ref",
    ),
    PlatformRow.M15.value: ("typed_canvas_projection_ref",),
    PlatformRow.M18.value: ("canonical_code_command_ref", "consistency_check_ref"),
    PlatformRow.M20.value: ("secret_ref", "llm_gateway_ref", "kill_switch_ref"),
    PlatformRow.M21.value: ("mock_label_ref", "asset_category_ref"),
}

SPECIFIC_REF_PREFIXES: dict[str, tuple[str, ...]] = {
    "ingestion_skill_ref": ("ingestion_skill:",),
    "instrument_spec_ref": ("instrument_spec:",),
    "model_passport_ref": ("model_passport:",),
    "validation_dossier_ref": ("validation_dossier:",),
    "signal_contract_ref": ("signal_contract:",),
    "strategy_book_ref": ("strategy_book:",),
    "execution_boundary_ref": ("execution_boundary:",),
    "market_capability_matrix_ref": ("market_capability_matrix:",),
    "llm_gateway_ref": ("llm_gateway:",),
    "model_routing_policy_ref": ("model_routing_policy:",),
    "credential_pool_ref": ("credential_pool:",),
    "theory_implementation_binding_ref": ("theory_binding:", "theory_implementation_binding:"),
    "typed_canvas_projection_ref": ("typed_canvas_projection:",),
    "canonical_code_command_ref": ("canonical_code_command:",),
    "consistency_check_ref": ("consistency_check:",),
    "secret_ref": ("secret:",),
    "kill_switch_ref": ("kill_switch:",),
    "mock_label_ref": ("mock_label:",),
    "asset_category_ref": ("asset_category:",),
}


@dataclass(frozen=True)
class PlatformCoverageViolation:
    code: str
    message: str
    field: str = ""
    ref: str = ""


@dataclass(frozen=True)
class PlatformCoverageDecision:
    accepted: bool
    violations: tuple[PlatformCoverageViolation, ...]


@dataclass(frozen=True)
class PlatformSpecificRef:
    key: str
    ref: str


@dataclass(frozen=True)
class PlatformCapabilityRecord:
    m_row: PlatformRow | str
    qro_ref: str | None
    research_graph_ref: str | None
    lifecycle_ref: str | None
    governance_ref: str | None
    rag_ref: str | None
    math_spine_ref: str | None
    evidence_refs: tuple[str, ...]
    specific_refs: tuple[PlatformSpecificRef, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "evidence_refs", _tuple(self.evidence_refs))
        object.__setattr__(self, "specific_refs", _tuple(self.specific_refs))


def _row_value(row: PlatformRow | str) -> str:
    if isinstance(row, PlatformRow):
        return row.value
    return str(row)


def validate_platform_capability(record: PlatformCapabilityRecord) -> PlatformCoverageDecision:
    violations: list[PlatformCoverageViolation] = []
    row = _row_value(record.m_row)
    for field_name in (
        "qro_ref",
        "research_graph_ref",
        "lifecycle_ref",
        "governance_ref",
        "rag_ref",
        "math_spine_ref",
    ):
        if not _present(getattr(record, field_name)):
            violations.append(
                PlatformCoverageViolation(
                    "platform_capability_missing_common_ref",
                    "M1-M21 capabilities must connect to QRO, Research Graph, lifecycle, governance, RAG, and Mathematical Spine",
                    field=field_name,
                    ref=row,
                )
            )
    if not record.evidence_refs:
        violations.append(
            PlatformCoverageViolation(
                "platform_capability_missing_evidence",
                "platform capability coverage requires evidence refs",
                field="evidence_refs",
                ref=row,
            )
        )
    refs = {item.key: item.ref for item in record.specific_refs}
    for key in SPECIFIC_REQUIRED_REFS.get(row, ()):
        if not _present(refs.get(key)):
            violations.append(
                PlatformCoverageViolation(
                    "platform_capability_missing_specific_ref",
                    "platform row is missing GOAL-specific coverage ref",
                    field=key,
                    ref=row,
                )
            )
    return PlatformCoverageDecision(accepted=not violations, violations=tuple(violations))


def validate_platform_coverage(records: tuple[PlatformCapabilityRecord, ...]) -> PlatformCoverageDecision:
    violations: list[PlatformCoverageViolation] = []
    seen = {_row_value(record.m_row) for record in records}
    for row in REQUIRED_PLATFORM_ROWS:
        if row not in seen:
            violations.append(
                PlatformCoverageViolation(
                    "platform_capability_row_missing",
                    "M1-M21 coverage manifest is missing a GOAL platform row",
                    field="m_row",
                    ref=row,
                )
            )
    for record in records:
        violations.extend(validate_platform_capability(record).violations)
    return PlatformCoverageDecision(accepted=not violations, violations=tuple(violations))


def platform_capability_record_from_dict(data: dict[str, Any]) -> PlatformCapabilityRecord:
    raw_specific_refs = data.get("specific_refs") or ()
    specific_refs: list[PlatformSpecificRef] = []
    for item in _tuple(raw_specific_refs):
        if isinstance(item, PlatformSpecificRef):
            specific_refs.append(item)
        elif isinstance(item, dict):
            specific_refs.append(PlatformSpecificRef(key=str(item.get("key") or ""), ref=str(item.get("ref") or "")))
    return PlatformCapabilityRecord(
        m_row=str(data.get("m_row") or ""),
        qro_ref=str(data.get("qro_ref") or ""),
        research_graph_ref=str(data.get("research_graph_ref") or ""),
        lifecycle_ref=str(data.get("lifecycle_ref") or ""),
        governance_ref=str(data.get("governance_ref") or ""),
        rag_ref=str(data.get("rag_ref") or ""),
        math_spine_ref=str(data.get("math_spine_ref") or ""),
        evidence_refs=_str_tuple(data.get("evidence_refs")),
        specific_refs=tuple(specific_refs),
    )


def platform_capability_record_to_dict(record: PlatformCapabilityRecord) -> dict[str, Any]:
    return {
        "m_row": _row_value(record.m_row),
        "qro_ref": record.qro_ref,
        "research_graph_ref": record.research_graph_ref,
        "lifecycle_ref": record.lifecycle_ref,
        "governance_ref": record.governance_ref,
        "rag_ref": record.rag_ref,
        "math_spine_ref": record.math_spine_ref,
        "evidence_refs": list(record.evidence_refs),
        "specific_refs": [{"key": item.key, "ref": item.ref} for item in record.specific_refs],
    }


# Tokens that mark a ref as a synthetic / placeholder / self-certifying-closure
# string rather than a real persisted store id. Banned even when the ref happens
# to resolve, because the closure materializer that was removed seeded some
# dependency stores (e.g. mathematical_spine_chains.jsonl) with goal_closure:*
# placeholder records — a pure resolution check alone could be fooled by them.
_PLACEHOLDER_TOKENS: tuple[str, ...] = (
    "synthetic",
    "fixture",
    "test_only",
    "test-only",
    "goal_closure",
    "goal-closure",
    "goalclosure",
    "placeholder",
)

# Each common platform ref must resolve to a real object in a specific backend
# store. This maps the record field to the resolver method that owns that store.
_COMMON_REF_RESOLVER_METHODS: dict[str, str] = {
    "qro_ref": "has_qro",
    "research_graph_ref": "has_research_graph_command",
    "lifecycle_ref": "has_lifecycle_record",
    "governance_ref": "has_governance_record",
    "rag_ref": "has_rag_asset",
    "math_spine_ref": "has_math_spine_chain",
}


class PlatformCoverageRefResolver(Protocol):
    """Resolves a platform-coverage ref to a real object in a real backend store.

    Implementations MUST return True only when the ref is the id of an object
    that is actually persisted in the corresponding store. Nonexistent or
    placeholder ids MUST return False (fail-closed).
    """

    def has_qro(self, ref: str) -> bool: ...

    def has_research_graph_command(self, ref: str) -> bool: ...

    def has_lifecycle_record(self, ref: str) -> bool: ...

    def has_governance_record(self, ref: str) -> bool: ...

    def has_rag_asset(self, ref: str) -> bool: ...

    def has_math_spine_chain(self, ref: str) -> bool: ...


class RealPlatformCoverageRefResolver:
    """Resolve platform-coverage refs against the real QRO / research graph /
    lifecycle / governance / RAG / Mathematical Spine stores.

    This reuses the existing store getters (no new store APIs). A ref counts as
    backed only when the matching getter returns a real persisted object; a
    missing id raises ``KeyError``/``LookupError`` inside the store and is
    reported here as not backed (fail-closed). The resolver does NOT mint,
    materialize, or self-certify anything — it only reads existing stores.
    """

    def __init__(
        self,
        *,
        research_graph_store: Any,
        lifecycle_registry: Any,
        governance_registry: Any,
        rag_index: Any,
        spine_chain_registry: Any,
    ) -> None:
        self._research_graph_store = research_graph_store
        self._lifecycle_registry = lifecycle_registry
        self._governance_registry = governance_registry
        self._rag_index = rag_index
        self._spine_chain_registry = spine_chain_registry

    def has_qro(self, ref: str) -> bool:
        ref = str(ref or "")
        if not ref:
            return False
        try:
            self._research_graph_store.qro(ref)
            return True
        except (KeyError, LookupError):
            return False

    def has_research_graph_command(self, ref: str) -> bool:
        ref = str(ref or "")
        if not ref:
            return False
        return any(
            getattr(command, "command_id", None) == ref
            for command in self._research_graph_store.commands()
        )

    def has_lifecycle_record(self, ref: str) -> bool:
        ref = str(ref or "")
        if not ref:
            return False
        try:
            self._lifecycle_registry.ingestion_skill_update(ref)
            return True
        except (KeyError, LookupError):
            return False

    def has_governance_record(self, ref: str) -> bool:
        ref = str(ref or "")
        if not ref:
            return False
        for getter_name in (
            "passport",
            "monitoring_profile",
            "recertification_record",
            "artifact_inspection",
            "serving_invocation",
        ):
            getter = getattr(self._governance_registry, getter_name, None)
            if getter is None:
                continue
            try:
                getter(ref)
                return True
            except (KeyError, LookupError):
                continue
        return False

    def has_rag_asset(self, ref: str) -> bool:
        ref = str(ref or "")
        if not ref:
            return False
        return any(
            getattr(vector, "document_id", None) == ref
            for vector in self._rag_index.dense_vectors()
        )

    def has_math_spine_chain(self, ref: str) -> bool:
        ref = str(ref or "")
        if not ref:
            return False
        try:
            self._spine_chain_registry.chain(ref)
            return True
        except (KeyError, LookupError):
            return False


def build_real_platform_coverage_resolver(
    *,
    research_graph_store: Any,
    lifecycle_registry: Any,
    governance_registry: Any,
    rag_index: Any,
    spine_chain_registry: Any,
) -> RealPlatformCoverageRefResolver:
    """Build the production resolver from the real backend store singletons.

    Intended to be wired once at startup, e.g. in ``app.main``::

        set_default_platform_coverage_resolver(
            build_real_platform_coverage_resolver(
                research_graph_store=RESEARCH_GRAPH_STORE,
                lifecycle_registry=ASSET_LIFECYCLE_REGISTRY,
                governance_registry=MODEL_GOVERNANCE_REGISTRY,
                rag_index=RESEARCH_ASSET_RAG_INDEX,
                spine_chain_registry=MATHEMATICAL_SPINE_CHAIN_REGISTRY,
            )
        )
    """

    return RealPlatformCoverageRefResolver(
        research_graph_store=research_graph_store,
        lifecycle_registry=lifecycle_registry,
        governance_registry=governance_registry,
        rag_index=rag_index,
        spine_chain_registry=spine_chain_registry,
    )


# Dependency-injection seam. Defaults to None == fail-closed: with no resolver
# configured, no common ref can be proven backed, so manifests are rejected
# rather than rubber-stamped. Production wires the real resolver via the setter
# (one line in app.main); tests inject scenario resolvers explicitly.
_DEFAULT_RESOLVER: PlatformCoverageRefResolver | None = None


def set_default_platform_coverage_resolver(resolver: PlatformCoverageRefResolver | None) -> None:
    global _DEFAULT_RESOLVER
    _DEFAULT_RESOLVER = resolver


def get_default_platform_coverage_resolver() -> PlatformCoverageRefResolver | None:
    return _DEFAULT_RESOLVER


def _ref_is_backed(
    resolver: PlatformCoverageRefResolver | None,
    field_name: str,
    ref: str,
) -> bool:
    """Return True only if ``resolver`` proves ``ref`` resolves to a real object.

    Fail-closed: a missing resolver, an unknown field, or any error during
    resolution all count as not backed.
    """

    if resolver is None:
        return False
    method_name = _COMMON_REF_RESOLVER_METHODS.get(field_name)
    if method_name is None:
        return False
    method = getattr(resolver, method_name, None)
    if method is None:
        return False
    try:
        return bool(method(ref))
    except Exception:  # noqa: BLE001 - a gate must fail closed if resolution errors.
        return False


def _real_ref_violation(field: str, row: str, ref: str, reason: str) -> PlatformCoverageViolation:
    return PlatformCoverageViolation(
        "platform_capability_ref_not_backed",
        reason,
        field=field,
        ref=f"{row}:{ref}",
    )


def validate_platform_capability_real_backing(
    record: PlatformCapabilityRecord,
    *,
    resolver: PlatformCoverageRefResolver | None = None,
) -> PlatformCoverageDecision:
    """Require every common platform ref to resolve to a real backend object.

    Unlike :func:`validate_platform_capability` (presence-only), this gate
    REQUIRES each of the six common refs (QRO, research-graph command,
    lifecycle, governance, RAG, Mathematical Spine) to resolve to a real object
    in its real store via ``resolver``. With no resolver (neither the argument
    nor the module default) the gate is fail-closed: nothing is provably backed,
    so the capability is rejected rather than rubber-stamped. Placeholder /
    goal-closure / synthetic tokens are rejected before resolution, so a
    dependency store seeded with a ``goal_closure:*`` placeholder record cannot
    launder a ref into "backed".

    Specific and evidence refs keep their lexical anti-placeholder guards; deep
    real-store resolution of those heterogeneous ref types is a recorded
    follow-up (see KNOWN_RUN_GAPS in the wave report), not closure faking.
    """

    active_resolver = resolver if resolver is not None else _DEFAULT_RESOLVER
    violations: list[PlatformCoverageViolation] = list(validate_platform_capability(record).violations)
    row = _row_value(record.m_row)
    common_refs = {
        "qro_ref": str(record.qro_ref or ""),
        "research_graph_ref": str(record.research_graph_ref or ""),
        "lifecycle_ref": str(record.lifecycle_ref or ""),
        "governance_ref": str(record.governance_ref or ""),
        "rag_ref": str(record.rag_ref or ""),
        "math_spine_ref": str(record.math_spine_ref or ""),
    }
    for field_name, ref in common_refs.items():
        if not ref:
            # Absence already reported by validate_platform_capability above.
            continue
        lowered = ref.lower()
        if any(token in lowered for token in _PLACEHOLDER_TOKENS):
            violations.append(
                _real_ref_violation(
                    field_name,
                    row,
                    ref,
                    "platform coverage refs cannot be synthetic/placeholder/goal-closure tokens",
                )
            )
            continue
        if ref == f"{field_name.removesuffix('_ref')}:{row}" or ref in {row, "research_graph"}:
            violations.append(
                _real_ref_violation(field_name, row, ref, "platform coverage refs cannot be row placeholders")
            )
            continue
        if not _ref_is_backed(active_resolver, field_name, ref):
            violations.append(
                _real_ref_violation(
                    field_name,
                    row,
                    ref,
                    f"platform coverage {field_name} does not resolve to a real object in its backend store",
                )
            )
    for ref in record.evidence_refs:
        ref = str(ref or "")
        lowered = ref.lower()
        if any(token in lowered for token in _PLACEHOLDER_TOKENS) or ref.endswith(":001"):
            violations.append(
                _real_ref_violation(
                    "evidence_refs",
                    row,
                    ref,
                    "platform evidence refs must point to audit/test evidence, not placeholders",
                )
            )
    for item in record.specific_refs:
        ref = str(item.ref or "")
        lowered = ref.lower()
        if any(token in lowered for token in _PLACEHOLDER_TOKENS) or ref.endswith(":001"):
            violations.append(
                _real_ref_violation(
                    f"specific_refs.{item.key}",
                    row,
                    ref,
                    "platform specific refs must point to real registry/audit refs, not placeholders",
                )
            )
        prefixes = SPECIFIC_REF_PREFIXES.get(item.key)
        if prefixes and not ref.startswith(prefixes):
            violations.append(
                _real_ref_violation(
                    f"specific_refs.{item.key}",
                    row,
                    ref,
                    "platform specific refs must use the registry/audit prefix for their key",
                )
            )
    return PlatformCoverageDecision(accepted=not violations, violations=tuple(violations))


def validate_platform_coverage_real_manifest(
    records: tuple[PlatformCapabilityRecord, ...],
    *,
    resolver: PlatformCoverageRefResolver | None = None,
) -> PlatformCoverageDecision:
    active_resolver = resolver if resolver is not None else _DEFAULT_RESOLVER
    violations: list[PlatformCoverageViolation] = []
    seen = {_row_value(record.m_row) for record in records}
    for row in REQUIRED_PLATFORM_ROWS:
        if row not in seen:
            violations.append(
                PlatformCoverageViolation(
                    "platform_capability_row_missing",
                    "M1-M21 coverage manifest is missing a GOAL platform row",
                    field="m_row",
                    ref=row,
                )
            )
    for record in records:
        violations.extend(
            validate_platform_capability_real_backing(record, resolver=active_resolver).violations
        )
    return PlatformCoverageDecision(accepted=not violations, violations=tuple(violations))


def _decision_message(decision: PlatformCoverageDecision) -> str:
    return "; ".join(f"{violation.code}:{violation.field}:{violation.ref}" for violation in decision.violations)


class PersistentPlatformCoverageRegistry:
    """Append-only registry for real M1-M21 platform coverage manifests."""

    def __init__(self, path: str | Path, *, resolver: PlatformCoverageRefResolver | None = None) -> None:
        self._path = Path(path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._resolver = resolver
        self._records: dict[str, PlatformCapabilityRecord] = {}
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
                except Exception as exc:  # noqa: BLE001 - invalid platform coverage history must block startup.
                    raise ValueError(f"invalid platform coverage row at {self._path}:{line_no}") from exc

    def _append_event(self, row: dict[str, Any]) -> None:
        with self._path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n")
            fh.flush()

    def _apply_row(self, row: dict[str, Any], *, persist: bool) -> tuple[PlatformCapabilityRecord, ...]:
        if row.get("schema_version") != 1:
            raise ValueError("unsupported platform coverage schema_version")
        if row.get("event_type") != "platform_coverage_manifest_recorded":
            raise ValueError(f"unknown platform coverage event_type={row.get('event_type')!r}")
        raw_records = row.get("records")
        if not isinstance(raw_records, list):
            raise ValueError("platform coverage manifest event requires records list")
        if any(not isinstance(item, dict) for item in raw_records):
            raise ValueError("platform coverage manifest records must be objects")
        records = tuple(platform_capability_record_from_dict(item) for item in raw_records)
        decision = validate_platform_coverage_real_manifest(records, resolver=self._resolver)
        if not decision.accepted:
            raise ValueError(_decision_message(decision))
        self._records = {_row_value(record.m_row): record for record in records}
        if persist:
            self._append_event(
                {
                    "schema_version": 1,
                    "event_type": "platform_coverage_manifest_recorded",
                    "records": [platform_capability_record_to_dict(record) for record in records],
                }
            )
        return records

    def record_manifest(self, records: tuple[PlatformCapabilityRecord, ...]) -> tuple[PlatformCapabilityRecord, ...]:
        return self._apply_row(
            {
                "schema_version": 1,
                "event_type": "platform_coverage_manifest_recorded",
                "records": [platform_capability_record_to_dict(record) for record in records],
            },
            persist=True,
        )

    def records(self) -> list[PlatformCapabilityRecord]:
        return list(self._records.values())


__all__ = [
    "PersistentPlatformCoverageRegistry",
    "PlatformCapabilityRecord",
    "PlatformCoverageDecision",
    "PlatformCoverageRefResolver",
    "PlatformCoverageViolation",
    "PlatformRow",
    "PlatformSpecificRef",
    "REQUIRED_PLATFORM_ROWS",
    "RealPlatformCoverageRefResolver",
    "build_real_platform_coverage_resolver",
    "get_default_platform_coverage_resolver",
    "platform_capability_record_from_dict",
    "platform_capability_record_to_dict",
    "set_default_platform_coverage_resolver",
    "validate_platform_capability",
    "validate_platform_capability_real_backing",
    "validate_platform_coverage",
    "validate_platform_coverage_real_manifest",
]
