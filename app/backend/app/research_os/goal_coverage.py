"""GOAL §0-§17 implementation coverage manifest contracts."""

from __future__ import annotations

import json
import os
import tempfile
import threading
from contextlib import contextmanager
from dataclasses import asdict, dataclass, is_dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Callable

from ..lineage.ids import content_hash
from ..cross_process_lock import acquire_exclusive_fd
from .goal_proof_head_lock import acquire_goal_proof_head_lock
from .goal_proof_ledger import GoalProofLedger
from .goal_proof_records import (
    ATOMIC_PROOF_BUNDLE_REQUIRED,
    GoalProofRecordProjection,
    GoalProofRecordProjectionError,
    ProofRecordCodec,
)
from .ref_resolution import RefResolver, is_placeholder_ref, resolve_typed_ref
from .spine import EntrySource


def _tuple(value: Any) -> tuple[Any, ...]:
    if value is None:
        return ()
    if isinstance(value, tuple):
        return value
    if isinstance(value, list):
        return tuple(value)
    return (value,)


def _str_tuple(value: Any) -> tuple[str, ...]:
    items: list[str] = []
    for item in _tuple(value):
        text = str(item.value if isinstance(item, Enum) else item or "")
        if text.strip():
            items.append(text)
    return tuple(items)


def _present(value: Any) -> bool:
    return bool(str(value or "").strip())


def _json_value(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    if is_dataclass(value):
        return _json_value(asdict(value))
    if isinstance(value, dict):
        return {str(k): _json_value(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_value(v) for v in value]
    return value


class GoalSection(str, Enum):
    SECTION_0 = "§0"
    SECTION_1 = "§1"
    SECTION_2 = "§2"
    SECTION_3 = "§3"
    SECTION_4 = "§4"
    SECTION_5 = "§5"
    SECTION_6 = "§6"
    SECTION_7 = "§7"
    SECTION_8 = "§8"
    SECTION_9 = "§9"
    SECTION_10 = "§10"
    SECTION_11 = "§11"
    SECTION_12 = "§12"
    SECTION_13 = "§13"
    SECTION_14 = "§14"
    SECTION_15 = "§15"
    SECTION_16 = "§16"
    SECTION_17 = "§17"


REQUIRED_GOAL_SECTIONS = tuple(section.value for section in GoalSection)
REQUIRED_ENTRY_SOURCES = tuple(source.value for source in EntrySource)
LOGICAL_TYPE_ENTRYPOINT_COVERAGE = "goal.entrypoint_coverage"
RESERVED_RISK_CONSENT_ENTRYPOINT_REF = "api:copy_trade.risk_consents.confirm"


def _canonical_entrypoint_projection_configured(registry: Any) -> bool:
    """Return whether a registry advertises an exact proof-head projection."""

    marker = getattr(registry, "canonical_projection_available", False)
    if callable(marker):
        marker = marker()
    return bool(marker) or getattr(registry, "_proof_projection", None) is not None


def strict_current_entrypoint_coverage(
    registry: Any,
    coverage_ref: str,
    *,
    owner: str,
) -> "GoalEntrypointCoverageRecord":
    """Read one durable current coverage without merging legacy history.

    Registries without a proof ledger retain the explicit compatibility read.
    A ledger-backed registry must expose ``canonical_coverage``; absence of
    that API fails closed.  A separately atomic producer may expose the narrow
    ``authoritative_transactional_coverage`` hook for refs which deliberately
    do not enter the shared proof-ledger record snapshot.
    """

    if not _canonical_entrypoint_projection_configured(registry):
        reader = getattr(registry, "coverage", None)
        if not callable(reader):
            raise TypeError("GOAL entrypoint registry lacks compatibility reads")
        return reader(coverage_ref, owner=owner)

    canonical_reader = getattr(registry, "canonical_coverage", None)
    if not callable(canonical_reader):
        raise TypeError("GOAL entrypoint registry lacks canonical proof reads")
    try:
        return canonical_reader(coverage_ref, owner=owner)
    except KeyError:
        transactional_reader = getattr(
            registry,
            "authoritative_transactional_coverage",
            None,
        )
        if not callable(transactional_reader):
            raise
        return transactional_reader(coverage_ref, owner=owner)


def strict_current_entrypoint_records(
    registry: Any,
    *,
    owner: str,
) -> tuple["GoalEntrypointCoverageRecord", ...]:
    """Read one owner's durable coverage heads from one exact snapshot.

    Transactional consent history is intentionally not added to this record
    view because it is not a member of the shared proof ledger.
    """

    if not _canonical_entrypoint_projection_configured(registry):
        reader = getattr(registry, "records", None)
        if not callable(reader):
            raise TypeError("GOAL entrypoint registry lacks compatibility reads")
        return tuple(reader(owner=owner))

    canonical_reader = getattr(registry, "canonical_records", None)
    if not callable(canonical_reader):
        raise TypeError("GOAL entrypoint registry lacks canonical proof reads")
    return tuple(canonical_reader(owner=owner))


def strict_current_entrypoint_lookup(
    registry: Any,
    *,
    owner: str,
) -> Callable[[str], "GoalEntrypointCoverageRecord"]:
    """Capture one owner snapshot and return an exact-ref lookup closure."""

    canonical = _canonical_entrypoint_projection_configured(registry)
    compatibility_reader = getattr(registry, "coverage", None)
    if not canonical and not callable(getattr(registry, "records", None)):
        if not callable(compatibility_reader):
            raise TypeError("GOAL entrypoint registry lacks compatibility reads")

        def _compatibility_lookup(
            coverage_ref: str,
        ) -> GoalEntrypointCoverageRecord:
            return compatibility_reader(coverage_ref, owner=owner)

        return _compatibility_lookup
    records = strict_current_entrypoint_records(registry, owner=owner)
    by_ref: dict[str, GoalEntrypointCoverageRecord] = {}
    for record in records:
        existing = by_ref.get(record.coverage_ref)
        if existing is not None and existing != record:
            raise ValueError(
                "GOAL entrypoint coverage identity collision in current snapshot"
            )
        by_ref[record.coverage_ref] = record
    transactional_reader = (
        getattr(registry, "authoritative_transactional_coverage", None)
        if canonical
        else None
    )

    def _lookup(coverage_ref: str) -> GoalEntrypointCoverageRecord:
        try:
            return by_ref[coverage_ref]
        except KeyError:
            if not callable(transactional_reader):
                raise
            return transactional_reader(coverage_ref, owner=owner)

    return _lookup


@dataclass(frozen=True)
class GoalCoverageViolation:
    code: str
    message: str
    field: str = ""
    ref: str = ""


@dataclass(frozen=True)
class GoalCoverageDecision:
    accepted: bool
    violations: tuple[GoalCoverageViolation, ...]


@dataclass(frozen=True)
class GoalSectionCoverageRecord:
    section: GoalSection | str
    contract_refs: tuple[str, ...]
    test_refs: tuple[str, ...]
    task_refs: tuple[str, ...]
    evidence_refs: tuple[str, ...]
    recorded_by: str = ""
    full_entrypoint_wired: bool = False
    entrypoint_wiring_refs: tuple[str, ...] = ()
    semantic_proof_refs: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "contract_refs", _tuple(self.contract_refs))
        object.__setattr__(self, "test_refs", _tuple(self.test_refs))
        object.__setattr__(self, "task_refs", _tuple(self.task_refs))
        object.__setattr__(self, "evidence_refs", _tuple(self.evidence_refs))
        object.__setattr__(self, "entrypoint_wiring_refs", _tuple(self.entrypoint_wiring_refs))
        object.__setattr__(self, "semantic_proof_refs", _tuple(self.semantic_proof_refs))


@dataclass(frozen=True)
class GoalEntrypointCoverageRecord:
    coverage_ref: str
    entry_source: EntrySource | str
    entrypoint_ref: str
    goal_sections: tuple[GoalSection | str, ...]
    qro_refs: tuple[str, ...]
    research_graph_command_refs: tuple[str, ...]
    compiler_ir_refs: tuple[str, ...]
    compiler_pass_refs: tuple[str, ...]
    evidence_refs: tuple[str, ...]
    validation_refs: tuple[str, ...]
    permission_refs: tuple[str, ...]
    replay_refs: tuple[str, ...]
    canonical_command_refs: tuple[str, ...] = ()
    lifecycle_refs: tuple[str, ...] = ()
    rdp_refs: tuple[str, ...] = ()
    recorded_by: str = ""
    claims_full_product_entrypoint: bool = False
    silent_mock_fallback_used: bool = False
    raw_payload_persisted: bool = False

    def __post_init__(self) -> None:
        for field_name in (
            "goal_sections",
            "qro_refs",
            "research_graph_command_refs",
            "compiler_ir_refs",
            "compiler_pass_refs",
            "evidence_refs",
            "validation_refs",
            "permission_refs",
            "replay_refs",
            "canonical_command_refs",
            "lifecycle_refs",
            "rdp_refs",
        ):
            object.__setattr__(self, field_name, _str_tuple(getattr(self, field_name)))


def _section_value(section: GoalSection | str) -> str:
    if isinstance(section, GoalSection):
        return section.value
    return str(section)


def _entry_source_value(entry_source: EntrySource | str) -> str:
    if isinstance(entry_source, EntrySource):
        return entry_source.value
    return str(entry_source)


def goal_entrypoint_coverage_identity(
    *,
    entry_source: EntrySource | str,
    entrypoint_ref: str,
    goal_sections: tuple[GoalSection | str, ...],
    qro_refs: tuple[str, ...],
    research_graph_command_refs: tuple[str, ...],
    compiler_ir_refs: tuple[str, ...],
    compiler_pass_refs: tuple[str, ...],
) -> str:
    """Content identity binding an entrypoint label to one compiler lineage.

    Legacy rows remain readable, but rows whose id was calculated without the
    entrypoint/source/section binding cannot count as strict completion proof.
    """

    return "goal_entrypoint_coverage:" + content_hash(
        {
            "entry_source": _entry_source_value(entry_source),
            "entrypoint_ref": str(entrypoint_ref or ""),
            "goal_sections": tuple(_section_value(section) for section in goal_sections),
            "qro_refs": tuple(qro_refs),
            "research_graph_command_refs": tuple(research_graph_command_refs),
            "compiler_ir_refs": tuple(compiler_ir_refs),
            "compiler_pass_refs": tuple(compiler_pass_refs),
        }
    )


def validate_goal_section_coverage(record: GoalSectionCoverageRecord) -> GoalCoverageDecision:
    violations: list[GoalCoverageViolation] = []
    section = _section_value(record.section)
    for field_name in ("contract_refs", "test_refs", "task_refs", "evidence_refs"):
        if not getattr(record, field_name):
            violations.append(
                GoalCoverageViolation(
                    "goal_section_missing_contract_evidence",
                    "each GOAL section requires contract, test, task, and evidence refs",
                    field=field_name,
                    ref=section,
                )
            )
    if record.full_entrypoint_wired and not record.entrypoint_wiring_refs:
        violations.append(
            GoalCoverageViolation(
                "goal_section_claimed_wired_without_refs",
                "full entrypoint wiring claims require wiring refs",
                field="entrypoint_wiring_refs",
                ref=section,
            )
        )
    return GoalCoverageDecision(accepted=not violations, violations=tuple(violations))


def _real_ref_violation(field: str, section: str, ref: str, reason: str) -> GoalCoverageViolation:
    return GoalCoverageViolation(
        "goal_section_ref_not_backed",
        reason,
        field=field,
        ref=f"{section}:{ref}",
    )


def validate_goal_section_real_backing(record: GoalSectionCoverageRecord) -> GoalCoverageDecision:
    """Strict GOAL section coverage gate: reject self-certifying refs.

    Presence-only coverage remains useful for loading old audit history, but it
    must not be counted as full implementation closure. This gate rejects
    placeholder / synthetic / goal-closure refs across contract, test, task,
    evidence, and entrypoint wiring fields. Entrypoint wiring refs are also
    resolved by `PersistentGoalSectionCoverageRegistry` when new records are
    written; this function owns the cross-field anti-self-certification rule.
    """

    violations: list[GoalCoverageViolation] = list(validate_goal_section_coverage(record).violations)
    section = _section_value(record.section)
    for field_name in (
        "contract_refs",
        "test_refs",
        "task_refs",
        "evidence_refs",
        "entrypoint_wiring_refs",
        "semantic_proof_refs",
    ):
        for ref in _str_tuple(getattr(record, field_name)):
            if is_placeholder_ref(ref):
                violations.append(
                    _real_ref_violation(
                        field_name,
                        section,
                        ref,
                        "GOAL section coverage refs cannot be synthetic/placeholder/goal-closure tokens",
                    )
                )
    return GoalCoverageDecision(accepted=not violations, violations=tuple(violations))


def validate_goal_entrypoint_coverage(record: GoalEntrypointCoverageRecord) -> GoalCoverageDecision:
    violations: list[GoalCoverageViolation] = []
    ref = record.coverage_ref
    entry_source = _entry_source_value(record.entry_source)
    if not _present(record.coverage_ref):
        violations.append(
            GoalCoverageViolation(
                "goal_entrypoint_required_ref_missing",
                "entrypoint coverage requires coverage_ref",
                field="coverage_ref",
                ref=ref,
            )
        )
    if entry_source not in REQUIRED_ENTRY_SOURCES:
        violations.append(
            GoalCoverageViolation(
                "goal_entrypoint_unknown_source",
                "entrypoint coverage source must be a known EntrySource",
                field="entry_source",
                ref=ref,
            )
        )
    if not _present(record.entrypoint_ref):
        violations.append(
            GoalCoverageViolation(
                "goal_entrypoint_required_ref_missing",
                "entrypoint coverage requires entrypoint_ref",
                field="entrypoint_ref",
                ref=ref,
            )
        )
    if not _present(record.recorded_by):
        violations.append(
            GoalCoverageViolation(
                "goal_entrypoint_required_ref_missing",
                "entrypoint coverage requires a stable owner in recorded_by",
                field="recorded_by",
                ref=ref,
            )
        )
    for section in record.goal_sections:
        if section not in REQUIRED_GOAL_SECTIONS:
            violations.append(
                GoalCoverageViolation(
                    "goal_entrypoint_unknown_section",
                    "entrypoint coverage section must be one of §0 through §17",
                    field="goal_sections",
                    ref=section,
                )
            )
    for field_name in (
        "goal_sections",
        "qro_refs",
        "research_graph_command_refs",
        "compiler_ir_refs",
        "compiler_pass_refs",
        "evidence_refs",
        "validation_refs",
        "permission_refs",
        "replay_refs",
    ):
        if not getattr(record, field_name):
            violations.append(
                GoalCoverageViolation(
                    "goal_entrypoint_required_ref_missing",
                    "entrypoint coverage requires QRO, graph, compiler, evidence, permission, replay, and validation refs",
                    field=field_name,
                    ref=ref,
                )
            )
    if record.claims_full_product_entrypoint and set(record.goal_sections) != set(REQUIRED_GOAL_SECTIONS):
        violations.append(
            GoalCoverageViolation(
                "goal_entrypoint_full_product_claim_missing_sections",
                "full-product entrypoint claims must cite every GOAL section from §0 to §17",
                field="goal_sections",
                ref=ref,
            )
        )
    if record.silent_mock_fallback_used:
        violations.append(
            GoalCoverageViolation(
                "goal_entrypoint_silent_mock_fallback",
                "entrypoint coverage cannot rely on silent mock fallback",
                field="silent_mock_fallback_used",
                ref=ref,
            )
        )
    if record.raw_payload_persisted:
        violations.append(
            GoalCoverageViolation(
                "goal_entrypoint_raw_payload_persisted",
                "entrypoint coverage must cite refs/hashes, not persisted raw user or tool payloads",
                field="raw_payload_persisted",
                ref=ref,
            )
        )
    return GoalCoverageDecision(accepted=not violations, violations=tuple(violations))


def _entrypoint_real_ref_violation(field: str, coverage_ref: str, ref: str, reason: str) -> GoalCoverageViolation:
    return GoalCoverageViolation(
        "goal_entrypoint_ref_not_backed",
        reason,
        field=field,
        ref=f"{coverage_ref}:{ref}",
    )


def validate_goal_entrypoint_real_backing(
    record: GoalEntrypointCoverageRecord,
    *,
    resolver: RefResolver | None,
) -> GoalCoverageDecision:
    """Strict entrypoint coverage gate for new writes.

    Presence-only coverage is still accepted when replaying old JSONL history.
    New strict writes must prove that QRO, Research Graph, Compiler IR/pass,
    and evidence refs resolve through independent real stores. Compiler
    containment is lineage, not evidence backing. Terminal full-product claims
    additionally require owner-scoped lifecycle and RDP closure refs. Historic
    schema-v2 rows remain readable, but missing closure refs cannot pass this
    current strict gate.
    """

    violations: list[GoalCoverageViolation] = list(validate_goal_entrypoint_coverage(record).violations)
    owner_resolver_factory = getattr(resolver, "for_owner", None)
    if callable(owner_resolver_factory) and _present(record.recorded_by):
        resolver = owner_resolver_factory(record.recorded_by)
    expected_identity = goal_entrypoint_coverage_identity(
        entry_source=record.entry_source,
        entrypoint_ref=record.entrypoint_ref,
        goal_sections=record.goal_sections,
        qro_refs=record.qro_refs,
        research_graph_command_refs=record.research_graph_command_refs,
        compiler_ir_refs=record.compiler_ir_refs,
        compiler_pass_refs=record.compiler_pass_refs,
    )
    if record.coverage_ref != expected_identity:
        violations.append(
            GoalCoverageViolation(
                "goal_entrypoint_identity_mismatch",
                "coverage_ref must content-bind entry_source, entrypoint_ref, sections, QRO, Graph, IR, and pass refs",
                field="coverage_ref",
                ref=record.coverage_ref,
            )
        )
    if record.claims_full_product_entrypoint:
        for field_name in ("lifecycle_refs", "rdp_refs"):
            if not _str_tuple(getattr(record, field_name)):
                violations.append(
                    GoalCoverageViolation(
                        "goal_entrypoint_full_product_closure_ref_missing",
                        "full-product entrypoint claims require current lifecycle and RDP refs",
                        field=field_name,
                        ref=record.coverage_ref,
                    )
                )
    for field_name, ref_type in (
        ("qro_refs", "qro"),
        ("research_graph_command_refs", "research_graph"),
        ("compiler_ir_refs", "compiler_ir"),
        ("compiler_pass_refs", "compiler_pass"),
        ("evidence_refs", "evidence"),
        ("lifecycle_refs", "lifecycle"),
        ("rdp_refs", "rdp"),
    ):
        for ref in _str_tuple(getattr(record, field_name)):
            if not resolve_typed_ref(resolver, ref_type, ref):
                violations.append(
                    _entrypoint_real_ref_violation(
                        field_name,
                        record.coverage_ref,
                        ref,
                        "GOAL entrypoint coverage refs must resolve to owner-scoped persisted records in the matching typed store",
                    )
                )
    for field_name in (
        "validation_refs",
        "permission_refs",
        "replay_refs",
        "canonical_command_refs",
    ):
        for ref in _str_tuple(getattr(record, field_name)):
            if is_placeholder_ref(ref):
                violations.append(
                    _entrypoint_real_ref_violation(
                        field_name,
                        record.coverage_ref,
                        ref,
                        "GOAL entrypoint coverage refs cannot be synthetic/placeholder/goal-closure tokens",
                    )
                )
    linkage_validator = getattr(resolver, "entrypoint_linkage_violations", None)
    if not callable(linkage_validator):
        violations.append(
            GoalCoverageViolation(
                "goal_entrypoint_linkage_unverified",
                "strict coverage requires a resolver that validates source and cross-record compiler lineage",
                field="entrypoint_ref",
                ref=record.coverage_ref,
            )
        )
    else:
        try:
            linkage_violations = tuple(linkage_validator(record))
        except Exception:  # noqa: BLE001 - strict validation fails closed.
            linkage_violations = (
                ("entrypoint_ref", record.entrypoint_ref, "entrypoint linkage resolver raised"),
            )
        for field_name, ref, reason in linkage_violations:
            violations.append(
                GoalCoverageViolation(
                    "goal_entrypoint_linkage_invalid",
                    str(reason),
                    field=str(field_name),
                    ref=f"{record.coverage_ref}:{ref}",
                )
            )
    return GoalCoverageDecision(accepted=not violations, violations=tuple(violations))


def validate_goal_coverage_manifest(
    records: tuple[GoalSectionCoverageRecord, ...],
    *,
    claims_full_product_implementation: bool = False,
) -> GoalCoverageDecision:
    violations: list[GoalCoverageViolation] = []
    seen = {_section_value(record.section) for record in records}
    for section in REQUIRED_GOAL_SECTIONS:
        if section not in seen:
            violations.append(
                GoalCoverageViolation(
                    "goal_section_missing",
                    "GOAL coverage manifest must include every section from §0 to §17",
                    field="section",
                    ref=section,
                )
            )
    for record in records:
        section_decision = validate_goal_section_coverage(record)
        violations.extend(section_decision.violations)
        if claims_full_product_implementation and not record.full_entrypoint_wired:
            violations.append(
                GoalCoverageViolation(
                    "goal_section_not_full_entrypoint_wired",
                    "contract coverage cannot be reported as full product implementation without entrypoint wiring refs",
                    field="full_entrypoint_wired",
                    ref=_section_value(record.section),
                )
            )
    return GoalCoverageDecision(accepted=not violations, violations=tuple(violations))


def validate_goal_coverage_real_manifest(
    records: tuple[GoalSectionCoverageRecord, ...],
    *,
    claims_full_product_implementation: bool = False,
    semantic_validation_available: bool = False,
) -> GoalCoverageDecision:
    """Strict full-product section coverage manifest.

    This keeps old audit rows readable but prevents `goal_closure:*` /
    placeholder refs from counting as real closure in summaries or new writes.
    """

    violations: list[GoalCoverageViolation] = []
    seen = {_section_value(record.section) for record in records}
    for section in REQUIRED_GOAL_SECTIONS:
        if section not in seen:
            violations.append(
                GoalCoverageViolation(
                    "goal_section_missing",
                    "GOAL coverage manifest must include every section from §0 to §17",
                    field="section",
                    ref=section,
                )
            )
    for record in records:
        violations.extend(validate_goal_section_real_backing(record).violations)
        if claims_full_product_implementation and not record.full_entrypoint_wired:
            violations.append(
                GoalCoverageViolation(
                    "goal_section_not_full_entrypoint_wired",
                    "contract coverage cannot be reported as full product implementation without entrypoint wiring refs",
                    field="full_entrypoint_wired",
                    ref=_section_value(record.section),
                )
            )
    if claims_full_product_implementation and not semantic_validation_available:
        violations.append(
            GoalCoverageViolation(
                "goal_section_semantic_validation_unavailable",
                "full product implementation requires section-specific producer/store/consumer/gate validators; lexical refs are insufficient",
                field="section_semantic_validators",
                ref="§0-§17",
            )
        )
    return GoalCoverageDecision(accepted=not violations, violations=tuple(violations))


def validate_goal_entrypoint_coverage_manifest(
    records: tuple[GoalEntrypointCoverageRecord, ...],
    *,
    claims_all_entrypoints_wired: bool = False,
) -> GoalCoverageDecision:
    violations: list[GoalCoverageViolation] = []
    seen_sources: set[str] = set()
    for record in records:
        source = _entry_source_value(record.entry_source)
        if source in REQUIRED_ENTRY_SOURCES:
            seen_sources.add(source)
        violations.extend(validate_goal_entrypoint_coverage(record).violations)
    if claims_all_entrypoints_wired:
        for source in REQUIRED_ENTRY_SOURCES:
            if source not in seen_sources:
                violations.append(
                    GoalCoverageViolation(
                        "goal_entrypoint_source_missing",
                        "all-entrypoints-wired claims require coverage for every EntrySource",
                        field="entry_source",
                        ref=source,
                    )
                )
    return GoalCoverageDecision(accepted=not violations, violations=tuple(violations))


def validate_goal_entrypoint_real_manifest(
    records: tuple[GoalEntrypointCoverageRecord, ...],
    *,
    resolver: RefResolver | None,
    claims_all_entrypoints_wired: bool = False,
) -> GoalCoverageDecision:
    """Validate a manifest using only entrypoint rows with real-store-backed refs.

    Historic JSONL rows remain readable, but an unresolved row cannot satisfy an
    EntrySource requirement merely because it is present in the file.  Every
    unresolved row is surfaced as a violation and only accepted rows contribute
    to ``seen_sources``.
    """

    violations: list[GoalCoverageViolation] = []
    backed_sources: set[str] = set()
    fully_wired_sources: set[str] = set()
    for record in records:
        record_decision = validate_goal_entrypoint_real_backing(record, resolver=resolver)
        violations.extend(record_decision.violations)
        source = _entry_source_value(record.entry_source)
        if record_decision.accepted and source in REQUIRED_ENTRY_SOURCES:
            backed_sources.add(source)
            if (
                record.claims_full_product_entrypoint
                and set(record.goal_sections) == set(REQUIRED_GOAL_SECTIONS)
            ):
                fully_wired_sources.add(source)
    if claims_all_entrypoints_wired:
        for source in REQUIRED_ENTRY_SOURCES:
            if source in backed_sources and source not in fully_wired_sources:
                violations.append(
                    GoalCoverageViolation(
                        "goal_entrypoint_source_only_partial",
                        "real-backed source rows do not prove the full §0-§17 entrypoint contract",
                        field="claims_full_product_entrypoint",
                        ref=source,
                    )
                )
            if source not in fully_wired_sources:
                violations.append(
                    GoalCoverageViolation(
                        "goal_entrypoint_source_missing",
                        "all-entrypoints-wired claims require a real-backed full §0-§17 row for every EntrySource",
                        field="entry_source",
                        ref=source,
                    )
                )
    return GoalCoverageDecision(accepted=not violations, violations=tuple(violations))


def _decision_message(decision: GoalCoverageDecision) -> str:
    return "; ".join(f"{v.code}:{v.field}" for v in decision.violations) or "goal coverage record rejected"


def goal_entrypoint_coverage_record_from_dict(data: dict[str, Any]) -> GoalEntrypointCoverageRecord:
    return GoalEntrypointCoverageRecord(
        coverage_ref=str(data.get("coverage_ref") or ""),
        entry_source=str(data.get("entry_source") or ""),
        entrypoint_ref=str(data.get("entrypoint_ref") or ""),
        goal_sections=_str_tuple(data.get("goal_sections")),
        qro_refs=_str_tuple(data.get("qro_refs")),
        research_graph_command_refs=_str_tuple(data.get("research_graph_command_refs")),
        compiler_ir_refs=_str_tuple(data.get("compiler_ir_refs")),
        compiler_pass_refs=_str_tuple(data.get("compiler_pass_refs")),
        evidence_refs=_str_tuple(data.get("evidence_refs")),
        validation_refs=_str_tuple(data.get("validation_refs")),
        permission_refs=_str_tuple(data.get("permission_refs")),
        replay_refs=_str_tuple(data.get("replay_refs")),
        canonical_command_refs=_str_tuple(data.get("canonical_command_refs")),
        lifecycle_refs=_str_tuple(data.get("lifecycle_refs")),
        rdp_refs=_str_tuple(data.get("rdp_refs")),
        recorded_by=str(data.get("recorded_by") or ""),
        claims_full_product_entrypoint=bool(data.get("claims_full_product_entrypoint", False)),
        silent_mock_fallback_used=bool(data.get("silent_mock_fallback_used", False)),
        raw_payload_persisted=bool(data.get("raw_payload_persisted", False)),
    )


GOAL_ENTRYPOINT_COVERAGE_PROOF_CODEC = ProofRecordCodec[
    GoalEntrypointCoverageRecord
](
    logical_type=LOGICAL_TYPE_ENTRYPOINT_COVERAGE,
    record_type=GoalEntrypointCoverageRecord,
    decode=goal_entrypoint_coverage_record_from_dict,
    logical_ref=lambda record: record.coverage_ref,
    owner=lambda record: record.recorded_by,
)


def goal_section_coverage_record_from_dict(data: dict[str, Any]) -> GoalSectionCoverageRecord:
    return GoalSectionCoverageRecord(
        section=str(data.get("section") or ""),
        contract_refs=_str_tuple(data.get("contract_refs")),
        test_refs=_str_tuple(data.get("test_refs")),
        task_refs=_str_tuple(data.get("task_refs")),
        evidence_refs=_str_tuple(data.get("evidence_refs")),
        recorded_by=str(data.get("recorded_by") or ""),
        full_entrypoint_wired=bool(data.get("full_entrypoint_wired", False)),
        entrypoint_wiring_refs=_str_tuple(data.get("entrypoint_wiring_refs")),
        semantic_proof_refs=_str_tuple(data.get("semantic_proof_refs")),
    )


def _atomic_rewrite_entrypoint_coverage_rows(
    path: Path,
    rows: tuple[dict[str, Any], ...],
) -> None:
    """Durably replace one entrypoint coverage JSONL log under its lock."""

    fd, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.",
        suffix=".rollback",
        dir=str(path.parent),
    )
    temporary_path = Path(temporary_name)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "wb") as fh:
            fd = -1
            for row in rows:
                payload = (
                    json.dumps(
                        row,
                        ensure_ascii=False,
                        sort_keys=True,
                        separators=(",", ":"),
                    )
                    + "\n"
                ).encode("utf-8")
                written = fh.write(payload)
                if written != len(payload):
                    raise OSError("GOAL coverage rollback wrote a partial event")
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(temporary_path, path)
        directory_flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
        directory_fd = os.open(path.parent, directory_flags)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        if fd >= 0:
            os.close(fd)
        try:
            temporary_path.unlink()
        except FileNotFoundError:
            pass


class PersistentGoalEntrypointCoverageRegistry:
    """Append-only JSONL registry for QRO -> Graph -> Compiler -> Evidence entrypoint coverage."""

    def __init__(
        self,
        path: str | Path,
        *,
        resolver: RefResolver | None = None,
        proof_ledger: GoalProofLedger | None = None,
        legacy_read_only: bool = False,
    ) -> None:
        self._path = Path(path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._lock_path = self._path.with_suffix(self._path.suffix + ".lock")
        self._process_lock = threading.RLock()
        self._resolver = resolver
        self._proof_projection = (
            GoalProofRecordProjection(proof_ledger)
            if proof_ledger is not None
            else None
        )
        self._legacy_read_only = bool(legacy_read_only)
        self._proof_head_types: dict[tuple[str, str], str] = {}
        self._records: dict[tuple[str, str], GoalEntrypointCoverageRecord] = {}
        self._legacy_quarantined_count = 0
        self._disk_signature: tuple[int, int, int, int, int] | None = None
        self._load_existing()
        self._overlay_canonical_unlocked()
        self._disk_signature = self._disk_signature_unlocked()

    @property
    def path(self) -> Path:
        return self._path

    @property
    def canonical_projection_available(self) -> bool:
        """Return whether exact SQLite proof-head reads are configured."""

        return self._proof_projection is not None

    def set_ref_resolver(self, resolver: RefResolver | None) -> None:
        self._resolver = resolver

    def attach_platform_source_evidence_registry(self, registry: Any) -> None:
        """Wire the producer-owned evidence ledger into the strict resolver."""

        setter = getattr(
            self._resolver,
            "set_platform_source_evidence_registry",
            None,
        )
        if not callable(setter):
            raise TypeError(
                "entrypoint resolver cannot attach platform source evidence"
            )
        setter(registry)

    def validate_real_backing(self, record: GoalEntrypointCoverageRecord) -> GoalCoverageDecision:
        """Return the current strict decision without mutating or persisting state."""

        return validate_goal_entrypoint_real_backing(record, resolver=self._resolver)

    def prepare_record_candidate(
        self,
        record: GoalEntrypointCoverageRecord,
    ) -> GoalEntrypointCoverageRecord:
        """Validate one write-free candidate before it enters an atomic bundle."""

        owner = self._owner(record.recorded_by)
        if record.recorded_by != owner:
            raise ValueError("GOAL entrypoint coverage owner must be exact")
        decision = validate_goal_entrypoint_coverage(record)
        if not decision.accepted:
            raise ValueError(_decision_message(decision))
        expected_ref = goal_entrypoint_coverage_identity(
            entry_source=record.entry_source,
            entrypoint_ref=record.entrypoint_ref,
            goal_sections=record.goal_sections,
            qro_refs=record.qro_refs,
            research_graph_command_refs=record.research_graph_command_refs,
            compiler_ir_refs=record.compiler_ir_refs,
            compiler_pass_refs=record.compiler_pass_refs,
        )
        if record.coverage_ref != expected_ref:
            raise ValueError("goal_entrypoint_identity_mismatch:coverage_ref")
        return record

    def validate_real_manifest(
        self,
        *,
        claims_all_entrypoints_wired: bool = False,
        owner: str | None = None,
    ) -> GoalCoverageDecision:
        """Strictly validate all loaded rows against the currently wired resolver."""

        records = (
            self.canonical_records(owner=self._owner(owner))
            if self.canonical_projection_available and owner is not None
            else tuple(self.records(owner=owner))
        )
        return validate_goal_entrypoint_real_manifest(
            tuple(records),
            resolver=self._resolver,
            claims_all_entrypoints_wired=claims_all_entrypoints_wired,
        )

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
                except Exception as exc:  # noqa: BLE001 - bad coverage history must block startup.
                    raise ValueError(f"invalid persisted GOAL entrypoint coverage row at {self._path}:{line_no}") from exc

    def _refresh_from_disk_unlocked(self) -> None:
        self._records = {}
        self._legacy_quarantined_count = 0
        self._load_existing()
        self._disk_signature = self._disk_signature_unlocked()

    def _overlay_canonical_unlocked(self) -> None:
        if self._proof_projection is None:
            self._proof_head_types = {}
            return
        canonical_by_type, self._proof_head_types = (
            self._proof_projection.decode_many_with_index(
                GOAL_ENTRYPOINT_COVERAGE_PROOF_CODEC
            )
        )
        for record in canonical_by_type[LOGICAL_TYPE_ENTRYPOINT_COVERAGE]:
            owner = self._owner(record.recorded_by)
            key = (owner, record.coverage_ref)
            existing = self._records.get(key)
            if existing is not None and existing != record:
                raise ValueError(
                    "canonical GOAL entrypoint coverage collides with legacy "
                    f"record for owner/ref {owner!r}/{record.coverage_ref!r}"
                )
            self._apply_row(
                {
                    "schema_version": 2,
                    "event_type": "goal_entrypoint_coverage_recorded",
                    "owner_user_id": owner,
                    "entrypoint_coverage": _json_value(record),
                },
                persist=False,
            )

    def _require_legacy_write_allowed(self) -> None:
        if self._legacy_read_only:
            raise RuntimeError(
                f"{ATOMIC_PROOF_BUNDLE_REQUIRED}: "
                "GOAL entrypoint coverage legacy JSONL is read-only"
            )

    def _disk_signature_unlocked(self) -> tuple[int, int, int, int, int] | None:
        try:
            stat = self._path.stat()
        except FileNotFoundError:
            return None
        return (
            stat.st_dev,
            stat.st_ino,
            stat.st_size,
            stat.st_mtime_ns,
            stat.st_ctime_ns,
        )

    def _refresh_if_changed_unlocked(self) -> None:
        if self._disk_signature_unlocked() != self._disk_signature:
            self._refresh_from_disk_unlocked()

    @contextmanager
    def _coverage_file_lock(self):
        fd = os.open(self._lock_path, os.O_RDWR | os.O_CREAT, 0o600)
        held = None
        try:
            os.chmod(self._lock_path, 0o600)
            held = acquire_exclusive_fd(fd, timeout_seconds=30.0)
            yield
        finally:
            if held is not None:
                held.release()
            os.close(fd)

    def refresh(self) -> None:
        """Reload the current durable coverage projection under its file lock."""

        with self._process_lock:
            with self._coverage_file_lock():
                self._refresh_from_disk_unlocked()
            self._overlay_canonical_unlocked()

    @contextmanager
    def _current_read_boundary(self):
        """Replay and read one linearized durable entrypoint projection."""

        with acquire_goal_proof_head_lock(self._path):
            with self._process_lock:
                with self._coverage_file_lock():
                    if self._proof_projection is None:
                        self._refresh_if_changed_unlocked()
                    else:
                        self._refresh_from_disk_unlocked()
                        self._overlay_canonical_unlocked()
                    yield

    @staticmethod
    def _owner(owner: str) -> str:
        normalized = str(owner or "").strip()
        if not normalized:
            raise ValueError("GOAL entrypoint coverage owner is required")
        return normalized

    def _append_event(self, row: dict[str, Any]) -> None:
        self._require_legacy_write_allowed()
        fd = os.open(self._lock_path, os.O_RDWR | os.O_CREAT, 0o600)
        held = None
        try:
            os.chmod(self._lock_path, 0o600)
            held = acquire_exclusive_fd(fd, timeout_seconds=30.0)
            incoming = row["entrypoint_coverage"]
            incoming_ref = str(incoming["coverage_ref"])
            if self._path.exists():
                with self._path.open("r", encoding="utf-8") as existing_fh:
                    for line_no, line in enumerate(existing_fh, start=1):
                        if not line.strip():
                            continue
                        existing = json.loads(line)
                        existing_record = existing.get("entrypoint_coverage")
                        if (
                            existing.get("schema_version") == 2
                            and existing.get("owner_user_id") == row.get("owner_user_id")
                            and isinstance(existing_record, dict)
                            and str(existing_record.get("coverage_ref") or "")
                            == incoming_ref
                        ):
                            if existing == row:
                                return
                            raise ValueError(
                                "GOAL entrypoint coverage identity collision at "
                                f"{self._path}:{line_no}"
                            )
            with self._path.open("a", encoding="utf-8") as fh:
                fh.write(
                    json.dumps(
                        row,
                        ensure_ascii=False,
                        sort_keys=True,
                        separators=(",", ":"),
                    )
                    + "\n"
                )
                fh.flush()
                os.fsync(fh.fileno())
        finally:
            if held is not None:
                held.release()
            os.close(fd)

    def _apply_row(self, row: dict[str, Any], *, persist: bool) -> GoalEntrypointCoverageRecord:
        schema_version = row.get("schema_version")
        if schema_version == 1:
            if row.get("event_type") != "goal_entrypoint_coverage_recorded":
                raise ValueError(
                    f"unknown GOAL entrypoint coverage event_type={row.get('event_type')!r}"
                )
            raw = row.get("entrypoint_coverage")
            if not isinstance(raw, dict):
                raise ValueError("GOAL entrypoint coverage event missing entrypoint_coverage")
            legacy_record = goal_entrypoint_coverage_record_from_dict(raw)
            legacy_decision = validate_goal_entrypoint_coverage(legacy_record)
            legacy_non_owner_violations = tuple(
                violation
                for violation in legacy_decision.violations
                if violation.field != "recorded_by"
            )
            if legacy_non_owner_violations:
                raise ValueError(
                    _decision_message(
                        GoalCoverageDecision(False, legacy_non_owner_violations)
                    )
                )
            self._legacy_quarantined_count += 1
            return legacy_record
        if schema_version != 2:
            raise ValueError("unsupported GOAL entrypoint coverage schema_version")
        if row.get("event_type") != "goal_entrypoint_coverage_recorded":
            raise ValueError(f"unknown GOAL entrypoint coverage event_type={row.get('event_type')!r}")
        raw = row.get("entrypoint_coverage")
        if not isinstance(raw, dict):
            raise ValueError("GOAL entrypoint coverage event missing entrypoint_coverage")
        record = goal_entrypoint_coverage_record_from_dict(raw)
        owner = self._owner(str(row.get("owner_user_id") or ""))
        if record.recorded_by != owner:
            raise ValueError("GOAL entrypoint coverage owner envelope mismatch")
        decision = (
            validate_goal_entrypoint_real_backing(record, resolver=self._resolver)
            if persist and self._resolver is not None
            else validate_goal_entrypoint_coverage(record)
        )
        if not decision.accepted:
            raise ValueError(_decision_message(decision))
        key = (owner, record.coverage_ref)
        existing = self._records.get(key)
        if existing is not None:
            if existing != record:
                raise ValueError("GOAL entrypoint coverage identity collision for owner")
            return existing
        if persist:
            self._append_event(
                {
                    "schema_version": 2,
                    "event_type": "goal_entrypoint_coverage_recorded",
                    "owner_user_id": owner,
                    "entrypoint_coverage": _json_value(record),
                }
            )
        self._records[key] = record
        return record

    def record_coverage(self, record: GoalEntrypointCoverageRecord) -> GoalEntrypointCoverageRecord:
        self._require_legacy_write_allowed()
        with acquire_goal_proof_head_lock(self._path):
            with self._process_lock:
                self._refresh_from_disk_unlocked()
                owner = self._owner(record.recorded_by)
                return self._apply_row(
                    {
                        "schema_version": 2,
                        "event_type": "goal_entrypoint_coverage_recorded",
                        "owner_user_id": owner,
                        "entrypoint_coverage": _json_value(record),
                    },
                    persist=True,
                )

    def coverage(
        self,
        coverage_ref: str,
        *,
        owner: str | None = None,
    ) -> GoalEntrypointCoverageRecord:
        with self._current_read_boundary():
            return self._coverage_unlocked(coverage_ref, owner=owner)

    def _coverage_unlocked(
        self,
        coverage_ref: str,
        *,
        owner: str | None = None,
    ) -> GoalEntrypointCoverageRecord:
        if owner is not None:
            normalized_owner = self._owner(owner)
            if self._proof_projection is not None:
                current_type = self._proof_head_types.get(
                    (normalized_owner, coverage_ref)
                )
                if (
                    current_type is not None
                    and current_type != LOGICAL_TYPE_ENTRYPOINT_COVERAGE
                ):
                    raise GoalProofRecordProjectionError(
                        "canonical GOAL proof logical ref/type collision: "
                        f"{coverage_ref!r} is {current_type!r}, expected "
                        f"{LOGICAL_TYPE_ENTRYPOINT_COVERAGE!r}"
                    )
            return self._records[(normalized_owner, coverage_ref)]
        matches = [
            record
            for (_record_owner, ref), record in self._records.items()
            if ref == coverage_ref
        ]
        if not matches:
            raise KeyError(coverage_ref)
        if len(matches) != 1:
            raise ValueError(f"GOAL entrypoint coverage ref {coverage_ref!r} is owner-ambiguous")
        return matches[0]

    def _canonical_records_with_index(
        self,
        *,
        owner: str,
    ) -> tuple[
        tuple[GoalEntrypointCoverageRecord, ...],
        dict[tuple[str, str], str],
    ]:
        """Decode one owner's coverage rows and type index from one snapshot."""

        normalized_owner = self._owner(owner)
        if self._proof_projection is None:
            return (), {}
        decoded, head_types = self._proof_projection.decode_many_with_index(
            GOAL_ENTRYPOINT_COVERAGE_PROOF_CODEC,
            owner=normalized_owner,
        )
        records = tuple(decoded[LOGICAL_TYPE_ENTRYPOINT_COVERAGE])
        for record in records:
            decision = validate_goal_entrypoint_coverage(record)
            if not decision.accepted:
                raise GoalProofRecordProjectionError(
                    "canonical GOAL entrypoint coverage is invalid: "
                    + _decision_message(decision)
                )
        return records, head_types

    def canonical_records(
        self,
        *,
        owner: str,
    ) -> tuple[GoalEntrypointCoverageRecord, ...]:
        """Return only exact current coverage proof heads for one owner.

        Legacy JSONL rows never enter this view.  The returned tuple is decoded
        from one immutable :class:`GoalProofLedger` snapshot.
        """

        records, _head_types = self._canonical_records_with_index(owner=owner)
        return records

    def canonical_coverage(
        self,
        coverage_ref: str,
        *,
        owner: str,
    ) -> GoalEntrypointCoverageRecord:
        """Resolve one exact current coverage head from one owner snapshot."""

        records, head_types = self._canonical_records_with_index(owner=owner)
        normalized_owner = self._owner(owner)
        current_type = head_types.get((normalized_owner, coverage_ref))
        if (
            current_type is not None
            and current_type != LOGICAL_TYPE_ENTRYPOINT_COVERAGE
        ):
            raise GoalProofRecordProjectionError(
                "canonical GOAL proof logical ref/type collision: "
                f"{coverage_ref!r} is {current_type!r}, expected "
                f"{LOGICAL_TYPE_ENTRYPOINT_COVERAGE!r}"
            )
        for record in records:
            if record.coverage_ref == coverage_ref:
                return record
        raise KeyError(coverage_ref)

    def records(self, *, owner: str | None = None) -> list[GoalEntrypointCoverageRecord]:
        with self._current_read_boundary():
            return self._records_unlocked(owner=owner)

    def _records_unlocked(
        self,
        *,
        owner: str | None = None,
    ) -> list[GoalEntrypointCoverageRecord]:
        if owner is None:
            return list(self._records.values())
        normalized = self._owner(owner)
        return [
            record
            for (record_owner, _), record in self._records.items()
            if record_owner == normalized
        ]

    def records_for_entry_source(
        self,
        entry_source: EntrySource | str,
        *,
        owner: str | None = None,
    ) -> list[GoalEntrypointCoverageRecord]:
        source = _entry_source_value(entry_source)
        return [
            record
            for record in self.records(owner=owner)
            if _entry_source_value(record.entry_source) == source
        ]

    def rollback_exact_coverage(self, record: GoalEntrypointCoverageRecord) -> bool:
        """Remove one exact owner-scoped coverage event and refresh projection."""

        self._require_legacy_write_allowed()
        owner = self._owner(record.recorded_by)
        with acquire_goal_proof_head_lock(self._path):
            with self._process_lock:
                fd = os.open(self._lock_path, os.O_RDWR | os.O_CREAT, 0o600)
                held = None
                try:
                    os.chmod(self._lock_path, 0o600)
                    held = acquire_exclusive_fd(fd, timeout_seconds=30.0)
                    self._refresh_from_disk_unlocked()
                    key = (owner, record.coverage_ref)
                    persisted = self._records.get(key)
                    if persisted is None:
                        return False
                    if persisted != record:
                        raise ValueError(
                            "GOAL entrypoint coverage rollback identity mismatch"
                        )

                    expected = {
                        "schema_version": 2,
                        "event_type": "goal_entrypoint_coverage_recorded",
                        "owner_user_id": owner,
                        "entrypoint_coverage": _json_value(record),
                    }
                    rows: list[dict[str, Any]] = []
                    if self._path.exists():
                        with self._path.open("r", encoding="utf-8") as fh:
                            rows = [json.loads(line) for line in fh if line.strip()]
                    if sum(row == expected for row in rows) != 1:
                        raise ValueError(
                            "GOAL entrypoint coverage rollback exact persisted event is "
                            "not unique"
                        )
                    retained = tuple(row for row in rows if row != expected)
                    _atomic_rewrite_entrypoint_coverage_rows(self._path, retained)
                    self._refresh_from_disk_unlocked()
                    return True
                finally:
                    if held is not None:
                        held.release()
                    os.close(fd)

    @property
    def legacy_quarantined_count(self) -> int:
        return self._legacy_quarantined_count

    def is_canonical_current(
        self,
        record: GoalEntrypointCoverageRecord,
        *,
        owner: str | None = None,
    ) -> bool:
        """Return whether ``record`` is the exact live SQLite proof head."""

        if self._proof_projection is None:
            return False
        if owner is not None and self._owner(owner) != self._owner(
            record.recorded_by
        ):
            return False
        return self._proof_projection.is_exact_current(
            record,
            codec=GOAL_ENTRYPOINT_COVERAGE_PROOF_CODEC,
        )


class RiskConsentEntrypointCoverageRegistry:
    """Merge normal coverage with transactional consent-source coverage.

    The consent store is duck-typed to keep Research OS independent from the
    copy-trade package. Reserved-entrypoint rows cannot be appended to the
    JSONL delegate; they must originate in the consent SQLite transaction.
    """

    def __init__(
        self,
        delegate: PersistentGoalEntrypointCoverageRegistry,
        store: Any,
        *,
        entrypoint_ref: str,
    ) -> None:
        self._delegate = delegate
        self._store = store
        self._entrypoint_ref = str(entrypoint_ref or "").strip()
        if self._entrypoint_ref != RESERVED_RISK_CONSENT_ENTRYPOINT_REF:
            raise ValueError(
                "risk consent coverage entrypoint_ref must be the reserved "
                f"{RESERVED_RISK_CONSENT_ENTRYPOINT_REF} source"
            )

    @property
    def path(self) -> Path:
        return self._delegate.path

    @property
    def legacy_quarantined_count(self) -> int:
        return int(self._delegate.legacy_quarantined_count)

    @property
    def canonical_projection_available(self) -> bool:
        return bool(self._delegate.canonical_projection_available)

    def set_ref_resolver(self, resolver: Any) -> None:
        self._delegate.set_ref_resolver(resolver)

    def attach_platform_source_evidence_registry(self, registry: Any) -> None:
        self._delegate.attach_platform_source_evidence_registry(registry)

    def refresh(self) -> None:
        self._delegate.refresh()

    def record_coverage(
        self,
        record: GoalEntrypointCoverageRecord,
    ) -> GoalEntrypointCoverageRecord:
        if record.entrypoint_ref == self._entrypoint_ref:
            raise ValueError(
                "risk consent source coverage can only be committed by its SQLite transaction"
            )
        return self._delegate.record_coverage(record)

    def rollback_exact_coverage(
        self,
        record: GoalEntrypointCoverageRecord,
    ) -> bool:
        if record.entrypoint_ref == self._entrypoint_ref:
            raise ValueError(
                "risk consent source coverage can only be rolled back by its "
                "SQLite transaction"
            )
        return self._delegate.rollback_exact_coverage(record)

    def coverage(
        self,
        coverage_ref: str,
        *,
        owner: str | None = None,
    ) -> GoalEntrypointCoverageRecord:
        try:
            if owner is None:
                return self._store.source_coverage(coverage_ref)
            return self._store.source_coverage_for_owner(coverage_ref, owner)
        except KeyError:
            return self._delegate.coverage(coverage_ref, owner=owner)

    def canonical_coverage(
        self,
        coverage_ref: str,
        *,
        owner: str,
    ) -> GoalEntrypointCoverageRecord:
        """Resolve only the shared proof-ledger head, never consent history."""

        return self._delegate.canonical_coverage(coverage_ref, owner=owner)

    def authoritative_transactional_coverage(
        self,
        coverage_ref: str,
        *,
        owner: str,
    ) -> GoalEntrypointCoverageRecord:
        """Resolve one exact consent-owned coverage outside the proof ledger."""

        record = self._store.source_coverage_for_owner(coverage_ref, owner)
        if (
            record.coverage_ref != coverage_ref
            or record.entrypoint_ref != self._entrypoint_ref
            or _entry_source_value(record.entry_source) != EntrySource.API.value
            or record.recorded_by != owner
            or tuple(_section_value(section) for section in record.goal_sections)
            != (GoalSection.SECTION_12.value,)
            or bool(record.claims_full_product_entrypoint)
        ):
            raise ValueError(
                "transactional GOAL coverage does not match the reserved consent source"
            )
        return record

    def records(self, *, owner: str | None = None) -> list[GoalEntrypointCoverageRecord]:
        combined: dict[tuple[str, str], GoalEntrypointCoverageRecord] = {}
        for record in [
            *self._delegate.records(owner=owner),
            *self._store.source_coverages(owner=owner),
        ]:
            key = (record.recorded_by, record.coverage_ref)
            existing = combined.get(key)
            if existing is not None and existing != record:
                raise ValueError("GOAL coverage identity collision across stores")
            combined[key] = record
        return list(combined.values())

    def canonical_records(
        self,
        *,
        owner: str,
    ) -> tuple[GoalEntrypointCoverageRecord, ...]:
        """Return only exact shared proof-ledger heads for one owner."""

        return self._delegate.canonical_records(owner=owner)

    def records_for_entry_source(
        self,
        entry_source: EntrySource | str,
        *,
        owner: str | None = None,
    ) -> list[GoalEntrypointCoverageRecord]:
        source = _entry_source_value(entry_source)
        return [
            record
            for record in self.records(owner=owner)
            if _entry_source_value(record.entry_source) == source
        ]

    def validate_real_backing(
        self,
        record: GoalEntrypointCoverageRecord,
    ) -> GoalCoverageDecision:
        if record.entrypoint_ref == self._entrypoint_ref:
            return self._store.validate_source_coverage(record)
        return self._delegate.validate_real_backing(record)

    def prepare_record_candidate(
        self,
        record: GoalEntrypointCoverageRecord,
    ) -> GoalEntrypointCoverageRecord:
        if record.entrypoint_ref == self._entrypoint_ref:
            raise ValueError(
                "risk consent source coverage can only be prepared by its "
                "SQLite transaction"
            )
        return self._delegate.prepare_record_candidate(record)

    def is_canonical_current(
        self,
        record: GoalEntrypointCoverageRecord,
        *,
        owner: str | None = None,
    ) -> bool:
        if record.entrypoint_ref == self._entrypoint_ref:
            return False
        return self._delegate.is_canonical_current(record, owner=owner)

    def validate_real_manifest(
        self,
        *,
        claims_all_entrypoints_wired: bool = False,
        owner: str | None = None,
    ) -> GoalCoverageDecision:
        violations: list[GoalCoverageViolation] = []
        fully_wired_sources: set[str] = set()
        records = (
            self.canonical_records(owner=owner)
            if self.canonical_projection_available and owner is not None
            else tuple(self.records(owner=owner))
        )
        for record in records:
            decision = self.validate_real_backing(record)
            violations.extend(decision.violations)
            source = _entry_source_value(record.entry_source)
            if (
                decision.accepted
                and record.claims_full_product_entrypoint
                and set(record.goal_sections) == set(REQUIRED_GOAL_SECTIONS)
            ):
                fully_wired_sources.add(source)
        if claims_all_entrypoints_wired:
            for source in REQUIRED_ENTRY_SOURCES:
                if source not in fully_wired_sources:
                    violations.append(
                        GoalCoverageViolation(
                            "goal_entrypoint_source_missing",
                            "all-entrypoints-wired claims require a real-backed full §0-§17 row for every EntrySource",
                            field="entry_source",
                            ref=source,
                        )
                    )
        return GoalCoverageDecision(accepted=not violations, violations=tuple(violations))


class PersistentGoalSectionCoverageRegistry:
    """Append-only JSONL registry for §0-§17 section implementation coverage."""

    def __init__(
        self,
        path: str | Path,
        entrypoint_coverage_registry: PersistentGoalEntrypointCoverageRegistry,
        semantic_proof_registry: Any = None,
    ) -> None:
        self._path = Path(path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._lock_path = self._path.with_suffix(self._path.suffix + ".lock")
        self._entrypoint_coverage_registry = entrypoint_coverage_registry
        self._semantic_proof_registry = semantic_proof_registry
        self._process_lock = threading.RLock()
        self._records: dict[tuple[str, str], GoalSectionCoverageRecord] = {}
        self._legacy_quarantined_count = 0
        self._load_existing()

    @property
    def path(self) -> Path:
        return self._path

    @staticmethod
    def _owner(owner: str) -> str:
        normalized = str(owner or "").strip()
        if not normalized:
            raise ValueError("GOAL section coverage owner is required")
        return normalized

    def _real_entrypoint_ref_violations(
        self,
        record: GoalSectionCoverageRecord,
        *,
        owner: str,
    ) -> tuple[GoalCoverageViolation, ...]:
        violations: list[GoalCoverageViolation] = []
        section = _section_value(record.section)
        coverage_for_ref = strict_current_entrypoint_lookup(
            self._entrypoint_coverage_registry,
            owner=owner,
        )
        for coverage_ref in record.entrypoint_wiring_refs:
            try:
                entrypoint_record = coverage_for_ref(coverage_ref)
            except KeyError:
                violations.append(
                    GoalCoverageViolation(
                        "goal_section_unknown_entrypoint_wiring_ref",
                        "section wiring ref is not present in the entrypoint coverage registry",
                        field="entrypoint_wiring_refs",
                        ref=section,
                    )
                )
                continue
            entrypoint_decision = self._entrypoint_coverage_registry.validate_real_backing(entrypoint_record)
            if not entrypoint_decision.accepted:
                codes = ",".join(sorted({violation.code for violation in entrypoint_decision.violations}))
                violations.append(
                    GoalCoverageViolation(
                        "goal_section_entrypoint_ref_not_real_backed",
                        f"section wiring ref {coverage_ref!r} failed strict entrypoint validation: {codes}",
                        field="entrypoint_wiring_refs",
                        ref=section,
                    )
                )
            if section not in set(entrypoint_record.goal_sections):
                violations.append(
                    GoalCoverageViolation(
                        "goal_section_entrypoint_ref_section_mismatch",
                        f"section wiring ref {coverage_ref!r} does not cite {section}",
                        field="entrypoint_wiring_refs",
                        ref=section,
                    )
                )
        return tuple(violations)

    def _real_semantic_proof_violations(
        self,
        record: GoalSectionCoverageRecord,
        *,
        owner: str,
    ) -> tuple[GoalCoverageViolation, ...]:
        if not record.full_entrypoint_wired:
            return ()
        section = _section_value(record.section)
        violations: list[GoalCoverageViolation] = []
        if not record.semantic_proof_refs:
            return (
                GoalCoverageViolation(
                    "goal_section_semantic_proof_missing",
                    "full section wiring requires owner-scoped semantic proof refs",
                    field="semantic_proof_refs",
                    ref=section,
                ),
            )
        if self._semantic_proof_registry is None:
            return (
                GoalCoverageViolation(
                    "goal_section_semantic_validation_unavailable",
                    "section semantic proof registry is unavailable",
                    field="semantic_proof_refs",
                    ref=section,
                ),
            )
        for proof_ref in record.semantic_proof_refs:
            try:
                proof = self._semantic_proof_registry.proof(
                    proof_ref,
                    owner=owner,
                )
            except KeyError:
                violations.append(
                    GoalCoverageViolation(
                        "goal_section_semantic_proof_unknown",
                        "section semantic proof ref is not persisted for this owner",
                        field="semantic_proof_refs",
                        ref=section,
                    )
                )
                continue
            proof_decision = self._semantic_proof_registry.validate_real_backing(
                proof,
                owner=owner,
            )
            if not proof_decision.accepted:
                violations.append(
                    GoalCoverageViolation(
                        "goal_section_semantic_proof_not_real_backed",
                        "section semantic proof failed its registered real-store adapter",
                        field="semantic_proof_refs",
                        ref=section,
                    )
                )
            if str(getattr(proof, "section", "") or "") != section:
                violations.append(
                    GoalCoverageViolation(
                        "goal_section_semantic_proof_section_mismatch",
                        "semantic proof does not belong to this GOAL section",
                        field="semantic_proof_refs",
                        ref=section,
                    )
                )
            if not bool(getattr(proof, "claims_section_complete", False)):
                violations.append(
                    GoalCoverageViolation(
                        "goal_section_semantic_proof_partial",
                        "semantic proof does not claim the section producer/store/consumer/gate chain complete",
                        field="semantic_proof_refs",
                        ref=section,
                    )
                )
            if tuple(getattr(proof, "unverified_residuals", ()) or ()):
                violations.append(
                    GoalCoverageViolation(
                        "goal_section_semantic_proof_has_residuals",
                        "semantic proof still carries unverified residuals",
                        field="semantic_proof_refs",
                        ref=section,
                    )
                )
        return tuple(violations)

    def validate_real_backing(
        self,
        record: GoalSectionCoverageRecord,
        *,
        owner: str | None = None,
    ) -> GoalCoverageDecision:
        normalized_owner = self._owner(owner or record.recorded_by)
        violations = list(validate_goal_section_real_backing(record).violations)
        if record.recorded_by != normalized_owner:
            violations.append(
                GoalCoverageViolation(
                    "goal_section_owner_mismatch",
                    "section coverage owner envelope must match recorded_by",
                    field="recorded_by",
                    ref=_section_value(record.section),
                )
            )
        violations.extend(
            self._real_entrypoint_ref_violations(record, owner=normalized_owner)
        )
        violations.extend(
            self._real_semantic_proof_violations(record, owner=normalized_owner)
        )
        return GoalCoverageDecision(accepted=not violations, violations=tuple(violations))

    def validate_real_manifest(
        self,
        *,
        claims_full_product_implementation: bool = False,
        owner: str,
    ) -> GoalCoverageDecision:
        normalized_owner = self._owner(owner)
        records = tuple(self.records(owner=normalized_owner))
        base = validate_goal_coverage_real_manifest(
            records,
            claims_full_product_implementation=claims_full_product_implementation,
            semantic_validation_available=self._semantic_proof_registry is not None,
        )
        violations = list(base.violations)
        for record in records:
            violations.extend(
                self._real_entrypoint_ref_violations(
                    record,
                    owner=normalized_owner,
                )
            )
            violations.extend(
                self._real_semantic_proof_violations(
                    record,
                    owner=normalized_owner,
                )
            )
        return GoalCoverageDecision(accepted=not violations, violations=tuple(violations))

    def _load_existing(self) -> None:
        if not self._path.exists():
            return
        with self._path.open("r", encoding="utf-8") as fh:
            for line_no, line in enumerate(fh, start=1):
                if not line.strip():
                    continue
                try:
                    row = json.loads(line)
                    if row.get("schema_version") == 1:
                        # Ownerless schema-v1 rows remain readable on disk but
                        # cannot count toward any tenant's strict §0-§17 proof.
                        self._legacy_quarantined_count += 1
                        continue
                    self._apply_row(row, persist=False)
                except Exception as exc:  # noqa: BLE001 - bad coverage history must block startup.
                    raise ValueError(f"invalid persisted GOAL section coverage row at {self._path}:{line_no}") from exc

    def _refresh_from_disk_unlocked(self) -> None:
        self._records = {}
        self._legacy_quarantined_count = 0
        self._load_existing()

    def refresh(self) -> None:
        """Reload section heads under their cross-process file lock."""

        with self._process_lock:
            fd = os.open(self._lock_path, os.O_RDWR | os.O_CREAT, 0o600)
            held = None
            try:
                os.chmod(self._lock_path, 0o600)
                held = acquire_exclusive_fd(fd, timeout_seconds=30.0)
                self._refresh_from_disk_unlocked()
            finally:
                if held is not None:
                    held.release()
                os.close(fd)

    def _append_event(self, row: dict[str, Any]) -> None:
        fd = os.open(self._lock_path, os.O_RDWR | os.O_CREAT, 0o600)
        held = None
        try:
            os.chmod(self._lock_path, 0o600)
            held = acquire_exclusive_fd(fd, timeout_seconds=30.0)
            incoming = row["section_coverage"]
            incoming_section = _section_value(incoming["section"])
            latest_matching_row: dict[str, Any] | None = None
            if self._path.exists():
                with self._path.open("r", encoding="utf-8") as existing_fh:
                    for line_no, line in enumerate(existing_fh, start=1):
                        if not line.strip():
                            continue
                        existing = json.loads(line)
                        existing_record = existing.get("section_coverage")
                        if (
                            existing.get("schema_version") == 2
                            and existing.get("owner_user_id") == row.get("owner_user_id")
                            and isinstance(existing_record, dict)
                            and _section_value(existing_record.get("section") or "")
                            == incoming_section
                        ):
                            latest_matching_row = existing
            if latest_matching_row == row:
                return
            with self._path.open("a", encoding="utf-8") as fh:
                fh.write(
                    json.dumps(
                        row,
                        ensure_ascii=False,
                        sort_keys=True,
                        separators=(",", ":"),
                    )
                    + "\n"
                )
                fh.flush()
                os.fsync(fh.fileno())
        finally:
            if held is not None:
                held.release()
            os.close(fd)

    def _validate_entrypoint_refs(
        self,
        record: GoalSectionCoverageRecord,
        *,
        owner: str,
    ) -> None:
        section = _section_value(record.section)
        coverage_for_ref = strict_current_entrypoint_lookup(
            self._entrypoint_coverage_registry,
            owner=owner,
        )
        for coverage_ref in record.entrypoint_wiring_refs:
            try:
                entrypoint_record = coverage_for_ref(coverage_ref)
            except KeyError as exc:
                raise ValueError(f"goal_section_unknown_entrypoint_wiring_ref:entrypoint_wiring_refs:{coverage_ref}") from exc
            decision = validate_goal_entrypoint_coverage(entrypoint_record)
            if not decision.accepted:
                raise ValueError(
                    "goal_section_invalid_entrypoint_wiring_ref:entrypoint_wiring_refs:"
                    + ",".join(f"{violation.code}:{violation.field}" for violation in decision.violations)
                )
            if section not in set(entrypoint_record.goal_sections):
                raise ValueError(
                    f"goal_section_entrypoint_ref_section_mismatch:entrypoint_wiring_refs:{coverage_ref}"
                )

    def _validate_semantic_proof_refs(
        self,
        record: GoalSectionCoverageRecord,
        *,
        owner: str,
    ) -> None:
        decision = GoalCoverageDecision(
            accepted=True,
            violations=self._real_semantic_proof_violations(record, owner=owner),
        )
        if decision.violations:
            raise ValueError(_decision_message(GoalCoverageDecision(False, decision.violations)))

    def _apply_row(self, row: dict[str, Any], *, persist: bool) -> GoalSectionCoverageRecord:
        if row.get("schema_version") != 2:
            raise ValueError("unsupported GOAL section coverage schema_version")
        if row.get("event_type") != "goal_section_coverage_recorded":
            raise ValueError(f"unknown GOAL section coverage event_type={row.get('event_type')!r}")
        raw = row.get("section_coverage")
        if not isinstance(raw, dict):
            raise ValueError("GOAL section coverage event missing section_coverage")
        record = goal_section_coverage_record_from_dict(raw)
        owner = self._owner(str(row.get("owner_user_id") or ""))
        if record.recorded_by != owner:
            raise ValueError("GOAL section coverage owner envelope mismatch")
        decision = validate_goal_section_coverage(record)
        if not decision.accepted:
            raise ValueError(_decision_message(decision))
        self._validate_entrypoint_refs(record, owner=owner)
        if persist:
            self._validate_semantic_proof_refs(record, owner=owner)
        key = (owner, _section_value(record.section))
        existing = self._records.get(key)
        if existing is not None:
            if existing == record:
                return existing
        if persist:
            self._append_event(
                {
                    "schema_version": 2,
                    "event_type": "goal_section_coverage_recorded",
                    "owner_user_id": owner,
                    "section_coverage": _json_value(record),
                }
            )
        self._records[key] = record
        return record

    def record_coverage(self, record: GoalSectionCoverageRecord) -> GoalSectionCoverageRecord:
        owner = self._owner(record.recorded_by)
        with acquire_goal_proof_head_lock(self._entrypoint_coverage_registry.path):
            refresh_entrypoints = getattr(
                self._entrypoint_coverage_registry,
                "refresh",
                None,
            )
            if callable(refresh_entrypoints):
                refresh_entrypoints()
            refresh_semantic = getattr(self._semantic_proof_registry, "refresh", None)
            if callable(refresh_semantic):
                refresh_semantic()
            with self._process_lock:
                self._refresh_from_disk_unlocked()
                decision = self.validate_real_backing(record, owner=owner)
                if not decision.accepted:
                    raise ValueError(_decision_message(decision))
                return self._apply_row(
                    {
                        "schema_version": 2,
                        "event_type": "goal_section_coverage_recorded",
                        "owner_user_id": owner,
                        "section_coverage": _json_value(record),
                    },
                    persist=True,
                )

    def coverage(
        self,
        section: GoalSection | str,
        *,
        owner: str | None = None,
    ) -> GoalSectionCoverageRecord:
        section_value = _section_value(section)
        if owner is not None:
            return self._records[(self._owner(owner), section_value)]
        matches = [
            record
            for (_record_owner, record_section), record in self._records.items()
            if record_section == section_value
        ]
        if not matches:
            raise KeyError(section_value)
        if len(matches) != 1:
            raise ValueError(f"GOAL section {section_value!r} is owner-ambiguous")
        return matches[0]

    def records(self, *, owner: str | None = None) -> list[GoalSectionCoverageRecord]:
        if owner is None:
            return list(self._records.values())
        normalized = self._owner(owner)
        return [
            record
            for (record_owner, _), record in self._records.items()
            if record_owner == normalized
        ]

    @property
    def legacy_quarantined_count(self) -> int:
        return self._legacy_quarantined_count


__all__ = [
    "GOAL_ENTRYPOINT_COVERAGE_PROOF_CODEC",
    "GoalCoverageDecision",
    "GoalCoverageViolation",
    "GoalEntrypointCoverageRecord",
    "GoalSection",
    "GoalSectionCoverageRecord",
    "LOGICAL_TYPE_ENTRYPOINT_COVERAGE",
    "PersistentGoalEntrypointCoverageRegistry",
    "PersistentGoalSectionCoverageRegistry",
    "RiskConsentEntrypointCoverageRegistry",
    "REQUIRED_ENTRY_SOURCES",
    "REQUIRED_GOAL_SECTIONS",
    "goal_entrypoint_coverage_record_from_dict",
    "goal_entrypoint_coverage_identity",
    "goal_section_coverage_record_from_dict",
    "validate_goal_entrypoint_coverage",
    "validate_goal_entrypoint_coverage_manifest",
    "validate_goal_entrypoint_real_backing",
    "validate_goal_entrypoint_real_manifest",
    "validate_goal_coverage_manifest",
    "validate_goal_coverage_real_manifest",
    "validate_goal_section_real_backing",
    "validate_goal_section_coverage",
]
