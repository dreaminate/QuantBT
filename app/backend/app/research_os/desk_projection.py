"""GOAL §2 multi-desk projection and handoff contracts."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


def _tuple(value: Any) -> tuple[Any, ...]:
    if value is None:
        return ()
    if isinstance(value, tuple):
        return value
    if isinstance(value, list):
        return tuple(value)
    return (value,)


def _value(value: Any) -> str:
    if isinstance(value, Enum):
        return str(value.value)
    return str(value or "")


def _present(value: str | None) -> bool:
    return bool(str(value or "").strip())


class DeskName(str, Enum):
    DATA = "data"
    FACTOR = "factor"
    MODEL = "model"
    SIGNAL = "signal"
    STRATEGY = "strategy"
    BACKTEST_VALIDATION = "backtest_validation"
    EXECUTION_RISK = "execution_risk"
    RESEARCH = "research"
    SETTINGS = "settings"


DESK_EDITABLE_ASSETS: dict[str, set[str]] = {
    DeskName.DATA.value: {"DataSourceAsset", "Dataset", "IngestionSkill", "Observable"},
    DeskName.FACTOR.value: {"Factor", "MathematicalArtifact"},
    DeskName.MODEL.value: {"Model", "TrainingPlan", "ValidationDossier"},
    DeskName.SIGNAL.value: {"Signal", "SignalContract"},
    DeskName.STRATEGY.value: {"StrategyBook", "PortfolioPolicy", "RiskPolicy"},
    DeskName.BACKTEST_VALIDATION.value: {"Experiment", "BacktestRun", "ValidationDossier"},
    DeskName.EXECUTION_RISK.value: {"ExecutionPolicy", "RiskPolicy", "RuntimePromotion"},
    DeskName.RESEARCH.value: {"ResearchReport", "DocumentArtifact", "MathematicalArtifact"},
    DeskName.SETTINGS.value: {"IntegrationConfig", "SecretRef", "LLMProvider", "ModelRoutingPolicy"},
}


@dataclass(frozen=True)
class DeskProjectionViolation:
    code: str
    message: str
    field: str = ""
    ref: str = ""


@dataclass(frozen=True)
class DeskProjectionDecision:
    accepted: bool
    violations: tuple[DeskProjectionViolation, ...]


@dataclass(frozen=True)
class DeskProjectionRecord:
    projection_ref: str
    desk: DeskName | str
    source_of_truth_refs: tuple[str, ...]
    typed_canvas_ref: str | None
    agent_shell_ref: str | None
    rag_projection_ref: str | None
    math_projection_ref: str | None
    asset_inspector_ref: str | None
    tool_permission_ref: str | None
    editable_asset_types: tuple[str, ...]
    canonical_command_types: tuple[str, ...]
    independent_truth_ref: str | None = None
    consistency_projection_ref: str | None = None
    claims_institutional_method: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(self, "source_of_truth_refs", _tuple(self.source_of_truth_refs))
        object.__setattr__(self, "editable_asset_types", _tuple(self.editable_asset_types))
        object.__setattr__(self, "canonical_command_types", _tuple(self.canonical_command_types))


@dataclass(frozen=True)
class DeskHandoffRecord:
    handoff_id: str
    from_desk: DeskName | str
    to_desk: DeskName | str
    requested_asset: str
    reason: str
    blocking_dependency: str | None
    status: str
    produced_ref: str | None
    evidence_refs: tuple[str, ...]
    created_by: str
    resolved_by: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "evidence_refs", _tuple(self.evidence_refs))


@dataclass(frozen=True)
class CanvasMutationRequest:
    command_ref: str
    source_desk: DeskName | str
    actor_source: str
    target_asset_type: str
    field_path: str
    canonical_command_ref: str | None
    audit_ref: str | None


@dataclass(frozen=True)
class CanvasMutationRecord:
    command_ref: str
    source_desk: DeskName | str
    actor_source: str
    actor: str
    target_asset_type: str
    target_ref: str
    field_path: str
    operation: str
    canonical_command_ref: str | None
    audit_ref: str | None
    value_ref: str | None = None
    value_hash: str | None = None
    evidence_refs: tuple[str, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        object.__setattr__(self, "evidence_refs", _tuple(self.evidence_refs))


def validate_desk_projection(projection: DeskProjectionRecord) -> DeskProjectionDecision:
    violations: list[DeskProjectionViolation] = []
    truth_refs = {_value(ref).lower() for ref in projection.source_of_truth_refs}
    if "research_graph" not in truth_refs and "researchgraph" not in truth_refs:
        violations.append(
            DeskProjectionViolation(
                "desk_projection_missing_research_graph",
                "desk projection must read from the shared Research Graph",
                field="source_of_truth_refs",
                ref=projection.projection_ref,
            )
        )
    if _present(projection.independent_truth_ref):
        violations.append(
            DeskProjectionViolation(
                "desk_projection_independent_truth_state",
                "desk projection cannot maintain an independent truth state",
                field="independent_truth_ref",
                ref=projection.projection_ref,
            )
        )
    for field_name in (
        "typed_canvas_ref",
        "agent_shell_ref",
        "rag_projection_ref",
        "asset_inspector_ref",
        "tool_permission_ref",
    ):
        if not _present(getattr(projection, field_name)):
            violations.append(
                DeskProjectionViolation(
                    "desk_projection_required_ref_missing",
                    "each desk requires Agent Shell, typed canvas, RAG, asset inspector, and tool permissions",
                    field=field_name,
                    ref=projection.projection_ref,
                )
            )
    desk = _value(projection.desk)
    allowed = DESK_EDITABLE_ASSETS.get(desk, set())
    illegal_types = sorted(set(projection.editable_asset_types) - allowed)
    if illegal_types:
        violations.append(
            DeskProjectionViolation(
                "desk_projection_write_scope_violation",
                "desk write permissions must stay within its editable asset types",
                field="editable_asset_types",
                ref=projection.projection_ref,
            )
        )
    if projection.claims_institutional_method:
        if not _present(projection.math_projection_ref):
            violations.append(
                DeskProjectionViolation(
                    "institutional_method_missing_math_projection",
                    "institutional method claims require a Mathematical Spine projection",
                    field="math_projection_ref",
                    ref=projection.projection_ref,
                )
            )
        if not _present(projection.consistency_projection_ref):
            violations.append(
                DeskProjectionViolation(
                    "institutional_method_missing_consistency_projection",
                    "institutional method claims require a consistency projection",
                    field="consistency_projection_ref",
                    ref=projection.projection_ref,
                )
            )
    return DeskProjectionDecision(accepted=not violations, violations=tuple(violations))


def validate_desk_handoff(handoff: DeskHandoffRecord) -> DeskProjectionDecision:
    violations: list[DeskProjectionViolation] = []
    if handoff.status == "completed":
        if not _present(handoff.produced_ref):
            violations.append(
                DeskProjectionViolation(
                    "desk_handoff_completed_without_produced_ref",
                    "completed DeskHandoff requires produced_ref",
                    field="produced_ref",
                    ref=handoff.handoff_id,
                )
            )
        if not handoff.evidence_refs:
            violations.append(
                DeskProjectionViolation(
                    "desk_handoff_completed_without_evidence",
                    "completed DeskHandoff requires evidence refs",
                    field="evidence_refs",
                    ref=handoff.handoff_id,
                )
            )
    return DeskProjectionDecision(accepted=not violations, violations=tuple(violations))


def validate_canvas_mutation(request: CanvasMutationRequest) -> DeskProjectionDecision:
    violations: list[DeskProjectionViolation] = []
    if not _present(request.canonical_command_ref):
        violations.append(
            DeskProjectionViolation(
                "canvas_mutation_missing_canonical_command",
                "manual, API, IDE, and agent mutations must land as canonical commands",
                field="canonical_command_ref",
                ref=request.command_ref,
            )
        )
    if not _present(request.audit_ref):
        violations.append(
            DeskProjectionViolation(
                "canvas_mutation_missing_audit_ref",
                "canvas mutation requires audit lineage",
                field="audit_ref",
                ref=request.command_ref,
            )
        )
    if (
        _value(request.source_desk) == DeskName.STRATEGY.value
        and request.target_asset_type == "Factor"
        and request.field_path.startswith("formula")
    ):
        violations.append(
            DeskProjectionViolation(
                "strategy_desk_cannot_write_factor_formula",
                "strategy desk must request factor edits through DeskHandoff",
                field="field_path",
                ref=request.command_ref,
            )
        )
    return DeskProjectionDecision(accepted=not violations, violations=tuple(violations))


def validate_multi_desk_contract(
    projections: tuple[DeskProjectionRecord, ...],
    *,
    handoffs: tuple[DeskHandoffRecord, ...] = (),
    mutations: tuple[CanvasMutationRequest, ...] = (),
) -> DeskProjectionDecision:
    violations: list[DeskProjectionViolation] = []
    for projection in projections:
        violations.extend(validate_desk_projection(projection).violations)
    for handoff in handoffs:
        violations.extend(validate_desk_handoff(handoff).violations)
    for mutation in mutations:
        violations.extend(validate_canvas_mutation(mutation).violations)
    return DeskProjectionDecision(accepted=not violations, violations=tuple(violations))


__all__ = [
    "CanvasMutationRecord",
    "CanvasMutationRequest",
    "DeskHandoffRecord",
    "DeskName",
    "DeskProjectionDecision",
    "DeskProjectionRecord",
    "DeskProjectionViolation",
    "validate_canvas_mutation",
    "validate_desk_handoff",
    "validate_desk_projection",
    "validate_multi_desk_contract",
]
