"""Typed-source adapters for the first five GOAL section 14 capability rows.

The builder intentionally registers only rows whose complete specific-source
bundle can be resolved from current, owner-scoped stores.  It does not turn a
reference string, RAG metadata, or a platform-row certification into a domain
object.  Rows with an absent upstream object therefore remain unavailable.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from ..lineage.ids import content_hash
from .platform_coverage import PlatformCapabilityRecord
from .platform_typed_sources import (
    PlatformRowLinkValidator,
    PlatformTypedSourceAdapter,
)
from .qro_spine_binding import (
    current_qro_spine_binding_is_observed,
    platform_spine_binding_historical_command_ref,
)
from .research_design_assets import source_object_hash


M1_M2 = "M1-M2"
M3 = "M3"
M4_M5 = "M4-M5"
M6 = "M6"
M7_M8 = "M7-M8"

_SPINE_BINDING_ENTRYPOINT_BY_ROW = {
    M1_M2: "api:research_os.platform.spine_bindings.m1_m2",
    M3: "api:research_os.platform.spine_bindings.m3",
    M4_M5: "api:research_os.platform.spine_bindings.m4_m5",
    M6: "api:research_os.platform.spine_bindings.m6",
    M7_M8: "api:research_os.platform.spine_bindings.m7_m8",
}


def _text(value: Any) -> str:
    return str(getattr(value, "value", value) or "").strip()


def _row(record: PlatformCapabilityRecord) -> str:
    return _text(record.m_row)


def _specific(record: PlatformCapabilityRecord) -> dict[str, str]:
    return {_text(item.key): _text(item.ref) for item in record.specific_refs}


def _required(value: Any, label: str) -> str:
    token = _text(value)
    if not token:
        raise LookupError(f"{label} is required")
    return token


def _owner_of(value: Any) -> str:
    return _text(getattr(value, "owner_user_id", getattr(value, "owner", "")))


def _qro_type(qro: Any) -> str:
    return _text(getattr(qro, "qro_type", ""))


def _violation_call(label: str, fn: Callable[[], Any]) -> tuple[Any | None, list[str]]:
    try:
        return fn(), []
    except Exception as exc:  # noqa: BLE001 - linkage must fail closed for any store error.
        return None, [f"{label} lookup failed:{type(exc).__name__}"]


def _has_getter(value: Any, method_name: str) -> bool:
    return callable(getattr(value, method_name, None))


def _sha256_file(path: Path) -> str:
    if path.is_symlink() or not path.is_file():
        raise LookupError("model artifact is unavailable or symlinked")
    digest = hashlib.sha256()
    try:
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError as exc:
        raise LookupError("model artifact cannot be read") from exc
    return "sha256:" + digest.hexdigest()


@dataclass(frozen=True)
class PlatformSourceAdaptersM1M8Context:
    """Existing stores used by the M1-M8 adapter builder.

    ``lifecycle_loader`` has the same argument order as a platform lifecycle
    loader.  M6 requires it because no model-passport field can honestly prove
    that an arbitrary same-owner lifecycle record belongs to the model.
    """

    research_graph_store: Any = None
    onboarding_registry: Any = None
    market_data_registry: Any = None
    asset_lifecycle_registry: Any = None
    dataset_registry: Any = None
    rag_index: Any = None
    spine_chain_registry: Any = None
    model_governance_registry: Any = None
    training_service: Any = None
    model_registry: Any = None
    lifecycle_loader: Callable[[str, str, PlatformCapabilityRecord], Any] | None = None
    research_design_registry: Any = None
    strategy_goal_store: Any = None
    hypothesis_store: Any = None
    factor_registry: Any = None
    signal_contract_registry: Any = None
    signal_validation_registry: Any = None


@dataclass(frozen=True)
class ResolvedValidationDossierSource:
    """The exact persisted dossier plus the owner-scoped training-job head."""

    validation_dossier_ref: str
    owner_user_id: str
    job: Any
    dossier: dict[str, Any]


def unavailable_platform_source_rows_m1_m8(
    context: PlatformSourceAdaptersM1M8Context,
) -> dict[str, tuple[str, ...]]:
    """Return the exact source families that keep each row unregistered."""

    unavailable: dict[str, tuple[str, ...]] = {}
    design = context.research_design_registry
    m1_missing = tuple(
        reason
        for value, methods, reason in (
            (
                design,
                ("universe_definition", "regime_scenario", "hypothesis_envelope"),
                "UniverseDefinition/RegimeScenario/Hypothesis owner registry is unavailable",
            ),
            (
                context.strategy_goal_store,
                ("get",),
                "StrategyGoalStore current getter is unavailable",
            ),
            (
                context.hypothesis_store,
                ("get",),
                "HypothesisCardStore current getter is unavailable",
            ),
            (
                context.research_graph_store,
                ("qro", "commands", "projection_index"),
                "Research Graph QRO/history getter is unavailable",
            ),
            (
                context.asset_lifecycle_registry,
                ("governed_asset",),
                "asset lifecycle current getter is unavailable",
            ),
            (
                context.rag_index,
                ("document_for_owner",),
                "RAG current owner getter is unavailable",
            ),
            (
                context.spine_chain_registry,
                ("verified_chain",),
                "Mathematical Spine current getter is unavailable",
            ),
        )
        if value is None or any(not _has_getter(value, method) for method in methods)
    )
    if m1_missing:
        unavailable[M1_M2] = m1_missing
    m4_missing = tuple(
        reason
        for value, methods, reason in (
            (
                design,
                ("label_definition", "factor_envelope"),
                "LabelDefinition/Factor owner registry is unavailable",
            ),
            (context.factor_registry, ("get",), "FactorRegistry current getter is unavailable"),
            (
                context.research_graph_store,
                ("qro", "commands", "projection_index"),
                "Research Graph QRO/history getter is unavailable",
            ),
            (
                context.asset_lifecycle_registry,
                ("governed_asset",),
                "asset lifecycle current getter is unavailable",
            ),
            (context.rag_index, ("document_for_owner",), "RAG current owner getter is unavailable"),
            (
                context.spine_chain_registry,
                ("verified_chain",),
                "Mathematical Spine current getter is unavailable",
            ),
        )
        if value is None or any(not _has_getter(value, method) for method in methods)
    )
    if m4_missing:
        unavailable[M4_M5] = m4_missing
    m7_missing = tuple(
        reason
        for value, methods, reason in (
            (
                design,
                ("portfolio_policy", "signal_contract_envelope", "strategy_book"),
                "PortfolioPolicy/SignalContract/StrategyBook owner registry is unavailable",
            ),
            (
                context.signal_contract_registry,
                ("get",),
                "SignalContractRegistry current getter is unavailable",
            ),
            (
                context.signal_validation_registry,
                ("validation",),
                "SignalValidation current owner getter is unavailable",
            ),
            (
                context.research_graph_store,
                ("qro", "commands", "projection_index"),
                "Research Graph QRO/history getter is unavailable",
            ),
            (
                context.asset_lifecycle_registry,
                ("governed_asset",),
                "asset lifecycle current getter is unavailable",
            ),
            (context.rag_index, ("document_for_owner",), "RAG current owner getter is unavailable"),
            (
                context.spine_chain_registry,
                ("verified_chain",),
                "Mathematical Spine current getter is unavailable",
            ),
        )
        if value is None or any(not _has_getter(value, method) for method in methods)
    )
    if m7_missing:
        unavailable[M7_M8] = m7_missing
    m3_missing = tuple(
        name
        for name, value, methods in (
            (
                "research_graph_store",
                context.research_graph_store,
                ("qro", "commands", "projection_index"),
            ),
            (
                "onboarding_registry",
                context.onboarding_registry,
                (
                    "ingestion_skill",
                    "data_source",
                    "data_connector_pit_bitemporal_rule",
                ),
            ),
            (
                "market_data_registry",
                context.market_data_registry,
                ("dataset", "instrument"),
            ),
            (
                "asset_lifecycle_registry",
                context.asset_lifecycle_registry,
                ("ingestion_skill_update",),
            ),
            ("dataset_registry", context.dataset_registry, ("resolve_version_ref",)),
            ("rag_index", context.rag_index, ("document_for_owner",)),
            ("spine_chain_registry", context.spine_chain_registry, ("verified_chain",)),
        )
        if value is None or any(not _has_getter(value, method) for method in methods)
    )
    if m3_missing:
        unavailable[M3] = tuple(f"missing dependency:{name}" for name in m3_missing)
    m6_missing = tuple(
        name
        for name, value, methods in (
            (
                "research_graph_store",
                context.research_graph_store,
                ("qro", "commands", "projection_index"),
            ),
            ("rag_index", context.rag_index, ("document_for_owner",)),
            ("spine_chain_registry", context.spine_chain_registry, ("verified_chain",)),
            (
                "model_governance_registry",
                context.model_governance_registry,
                ("passport",),
            ),
            ("training_service", context.training_service, ("get_job",)),
            ("model_registry", context.model_registry, ("list_versions",)),
            ("lifecycle_loader", context.lifecycle_loader, ("__call__",)),
        )
        if value is None or any(not _has_getter(value, method) for method in methods)
    )
    if m6_missing:
        unavailable[M6] = tuple(f"missing dependency:{name}" for name in m6_missing)
    return unavailable


@dataclass(frozen=True)
class ResolvedStrategyGoalSource:
    strategy_goal_ref: str
    owner_user_id: str
    goal_id: str
    goal: Any


@dataclass(frozen=True)
class ResolvedHypothesisSource:
    hypothesis_card_ref: str
    owner_user_id: str
    envelope: Any
    card: Any


@dataclass(frozen=True)
class ResolvedFactorSource:
    factor_ref: str
    owner_user_id: str
    envelope: Any
    factor: Any


@dataclass(frozen=True)
class ResolvedSignalContractSource:
    signal_contract_ref: str
    owner_user_id: str
    envelope: Any
    contract: Any


@dataclass(frozen=True)
class ResolvedStrategyBookSource:
    strategy_book_ref: str
    owner_user_id: str
    record: Any
    strategy: Any


def _qro_output(qro: Any) -> dict[str, Any]:
    value = getattr(qro, "output_contract", None)
    if not isinstance(value, dict):
        raise LookupError("row QRO output contract is malformed")
    return value


def _binding_graph_violations(
    graph: Any,
    record: PlatformCapabilityRecord,
    owner: str,
) -> tuple[str, ...]:
    row = _row(record)
    if row not in _SPINE_BINDING_ENTRYPOINT_BY_ROW:
        return (f"{row} does not have a platform Spine binding contract",)
    if current_qro_spine_binding_is_observed(
        research_graph_store=graph,
        owner_user_id=owner,
        qro_ref=_text(record.qro_ref),
        chain_ref=_text(record.math_spine_ref),
        entrypoint_ref=_SPINE_BINDING_ENTRYPOINT_BY_ROW[row],
        graph_command_ref=_text(record.research_graph_ref),
    ):
        return ()
    return (f"{row} current platform Spine binding is not observed",)


def _historical_graph_ref_for_binding(
    graph: Any,
    record: PlatformCapabilityRecord,
) -> str:
    """Resolve the immutable business command named by the current binder head."""

    current_ref = _required(record.research_graph_ref, "binding Graph command ref")
    chain_ref = _required(record.math_spine_ref, "binding Mathematical Spine ref")
    matches = tuple(
        item
        for item in tuple(graph.commands() or ())
        if _text(getattr(item, "command_id", "")) == current_ref
    )
    if len(matches) != 1:
        raise LookupError("current binding Graph command is missing or ambiguous")
    command = matches[0]
    payload = getattr(command, "payload", None)
    qro = payload.get("qro") if isinstance(payload, dict) else None
    try:
        current_qro = graph.qro(_text(record.qro_ref))
    except Exception as exc:  # noqa: BLE001 - typed lookup fails closed.
        raise LookupError("current binding QRO is unavailable") from exc
    if qro != current_qro:
        raise LookupError("current binding Graph command QRO mismatch")
    try:
        return platform_spine_binding_historical_command_ref(
            command,
            owner_user_id=_owner_of(current_qro),
            qro_ref=_text(record.qro_ref),
            chain_ref=chain_ref,
            entrypoint_ref=_SPINE_BINDING_ENTRYPOINT_BY_ROW[_row(record)],
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise LookupError("current binding Graph command provenance is invalid") from exc


def _lifecycle_for_row(
    context: PlatformSourceAdaptersM1M8Context,
    record: PlatformCapabilityRecord,
    owner: str,
) -> Any:
    return context.asset_lifecycle_registry.governed_asset(
        _text(record.lifecycle_ref), owner_user_id=owner
    )


def _rag_for_row(
    context: PlatformSourceAdaptersM1M8Context,
    record: PlatformCapabilityRecord,
    owner: str,
) -> Any:
    return context.rag_index.document_for_owner(
        _text(record.rag_ref), owner_user_id=owner, require_current=True
    )


def _chain_for_row(
    context: PlatformSourceAdaptersM1M8Context,
    record: PlatformCapabilityRecord,
    owner: str,
) -> Any:
    return context.spine_chain_registry.verified_chain(
        _text(record.math_spine_ref), owner=owner
    )


def _m1_m2_adapters_and_validator(
    context: PlatformSourceAdaptersM1M8Context,
) -> tuple[dict[str, PlatformTypedSourceAdapter], PlatformRowLinkValidator]:
    design = context.research_design_registry
    goals = context.strategy_goal_store
    cards = context.hypothesis_store
    graph = context.research_graph_store

    def load_goal(ref: str, owner: str, record: PlatformCapabilityRecord) -> ResolvedStrategyGoalSource:
        if _row(record) != M1_M2:
            raise LookupError("StrategyGoal adapter only supports M1-M2")
        if ref.startswith("strategy_goal:"):
            goal_id = ref.removeprefix("strategy_goal:")
        elif ref.startswith("goal:"):
            goal_id = ref.removeprefix("goal:")
        else:
            raise LookupError("StrategyGoal ref is not canonical")
        goal = goals.get(goal_id)
        qro = graph.qro(_text(record.qro_ref))
        output = _qro_output(qro)
        if (
            _owner_of(qro) != owner
            or _text(output.get("strategy_goal_ref")) != ref
            or _text(output.get("strategy_goal_hash")) != source_object_hash(goal)
        ):
            raise LookupError("StrategyGoal QRO owner/content binding mismatch")
        return ResolvedStrategyGoalSource(ref, owner, goal_id, goal)

    def validate_goal(value: ResolvedStrategyGoalSource, owner: str, record: PlatformCapabilityRecord) -> tuple[str, ...]:
        violations: list[str] = []
        if value.owner_user_id != owner:
            violations.append("StrategyGoal owner mismatch")
        if value.strategy_goal_ref != _specific(record).get("strategy_goal_ref"):
            violations.append("StrategyGoal ref mismatch")
        return tuple(violations)

    def load_card(ref: str, owner: str, record: PlatformCapabilityRecord) -> ResolvedHypothesisSource:
        if _row(record) != M1_M2:
            raise LookupError("HypothesisCard adapter only supports M1-M2")
        envelope = design.hypothesis_envelope(ref, owner_user_id=owner)
        card = cards.get(_text(getattr(envelope, "card_id", "")))
        if source_object_hash(card) != _text(getattr(envelope, "source_content_hash", "")):
            raise LookupError("HypothesisCard source content drifted")
        if _text(getattr(envelope, "hypothesis_card_ref", "")) != ref:
            raise LookupError("HypothesisCard envelope identity mismatch")
        return ResolvedHypothesisSource(ref, owner, envelope, card)

    def validate_card(value: ResolvedHypothesisSource, owner: str, record: PlatformCapabilityRecord) -> tuple[str, ...]:
        violations: list[str] = []
        if value.owner_user_id != owner or _owner_of(value.envelope) != owner:
            violations.append("HypothesisCard owner mismatch")
        if value.hypothesis_card_ref != _specific(record).get("hypothesis_card_ref"):
            violations.append("HypothesisCard ref mismatch")
        if _text(getattr(value.envelope.linkage, "qro_ref", "")) != _text(record.qro_ref):
            violations.append("HypothesisCard QRO linkage mismatch")
        return tuple(violations)

    def load_universe(ref: str, owner: str, record: PlatformCapabilityRecord) -> Any:
        if _row(record) != M1_M2:
            raise LookupError("UniverseDefinition adapter only supports M1-M2")
        value = design.universe_definition(ref, owner_user_id=owner)
        if _text(getattr(value, "universe_definition_ref", "")) != ref:
            raise LookupError("UniverseDefinition identity mismatch")
        return value

    def validate_universe(value: Any, owner: str, record: PlatformCapabilityRecord) -> tuple[str, ...]:
        violations: list[str] = []
        if _owner_of(value) != owner:
            violations.append("UniverseDefinition owner mismatch")
        if _text(getattr(value, "universe_definition_ref", "")) != _specific(record).get("universe_definition_ref"):
            violations.append("UniverseDefinition ref mismatch")
        return tuple(violations)

    def load_regime(ref: str, owner: str, record: PlatformCapabilityRecord) -> Any:
        if _row(record) != M1_M2:
            raise LookupError("RegimeScenario adapter only supports M1-M2")
        value = design.regime_scenario(ref, owner_user_id=owner)
        if _text(getattr(value, "regime_scenario_ref", "")) != ref:
            raise LookupError("RegimeScenario identity mismatch")
        return value

    def validate_regime(value: Any, owner: str, record: PlatformCapabilityRecord) -> tuple[str, ...]:
        violations: list[str] = []
        if _owner_of(value) != owner:
            violations.append("RegimeScenario owner mismatch")
        if _text(getattr(value, "regime_scenario_ref", "")) != _specific(record).get("regime_scenario_ref"):
            violations.append("RegimeScenario ref mismatch")
        return tuple(violations)

    def validate_row(record: PlatformCapabilityRecord, owner: str, values: dict[str, Any]) -> tuple[str, ...]:
        goal = values.get("strategy_goal_ref")
        hypothesis = values.get("hypothesis_card_ref")
        universe = values.get("universe_definition_ref")
        regime = values.get("regime_scenario_ref")
        if not isinstance(goal, ResolvedStrategyGoalSource) or not isinstance(hypothesis, ResolvedHypothesisSource):
            return ("M1-M2 requires the exact StrategyGoal and HypothesisCard",)
        if universe is None or regime is None:
            return ("M1-M2 requires the exact UniverseDefinition and RegimeScenario",)
        violations: list[str] = []
        violations.extend(_binding_graph_violations(graph, record, owner))
        envelope = hypothesis.envelope
        historical_graph_ref, errors = _violation_call(
            "M1-M2 binding Graph",
            lambda: _historical_graph_ref_for_binding(graph, record),
        )
        violations.extend(errors)
        exact_pairs = (
            (getattr(hypothesis.card, "strategy_goal_ref", ""), goal.strategy_goal_ref, "card strategy goal"),
            (getattr(envelope, "strategy_goal_ref", ""), goal.strategy_goal_ref, "envelope strategy goal"),
            (getattr(envelope, "universe_definition_ref", ""), getattr(universe, "universe_definition_ref", ""), "universe"),
            (getattr(envelope, "regime_scenario_ref", ""), getattr(regime, "regime_scenario_ref", ""), "regime"),
            (getattr(regime, "universe_definition_ref", ""), getattr(universe, "universe_definition_ref", ""), "regime universe"),
            (getattr(envelope.linkage, "lifecycle_ref", ""), record.lifecycle_ref, "lifecycle"),
        )
        for actual, expected, label in exact_pairs:
            if _text(actual) != _text(expected):
                violations.append(f"M1-M2 {label} mismatch")
        if (
            historical_graph_ref is not None
            and _text(getattr(envelope.linkage, "research_graph_ref", ""))
            != historical_graph_ref
        ):
            violations.append("M1-M2 graph mismatch")
        qro, errors = _violation_call("M1-M2 QRO", lambda: graph.qro(_text(record.qro_ref)))
        violations.extend(errors)
        if qro is not None:
            if _owner_of(qro) != owner or _qro_type(qro) != "QuantIntent":
                violations.append("M1-M2 QRO must be an owner-scoped QuantIntent")
            output = _qro_output(qro)
            for key, expected in _specific(record).items():
                if _text(output.get(key)) != expected:
                    violations.append(f"M1-M2 QRO output {key} mismatch")
        lifecycle, errors = _violation_call("M1-M2 lifecycle", lambda: _lifecycle_for_row(context, record, owner))
        violations.extend(errors)
        if lifecycle is not None:
            if _text(getattr(lifecycle, "asset_type", "")) != "HypothesisCard":
                violations.append("M1-M2 lifecycle asset type mismatch")
            if _text(getattr(lifecycle, "asset_ref", "")) != hypothesis.hypothesis_card_ref:
                violations.append("M1-M2 lifecycle does not bind HypothesisCard")
        chain, errors = _violation_call("M1-M2 Mathematical Spine", lambda: _chain_for_row(context, record, owner))
        violations.extend(errors)
        if chain is not None:
            chain_refs = {
                _text(item)
                for item in (*tuple(getattr(chain, "validation_refs", ()) or ()), *tuple(getattr(chain, "evidence_refs", ()) or ()))
            }
            required = set(_specific(record).values())
            if not required.issubset(chain_refs):
                violations.append("M1-M2 Mathematical Spine does not bind the exact design bundle")
        rag, errors = _violation_call("M1-M2 RAG", lambda: _rag_for_row(context, record, owner))
        violations.extend(errors)
        if rag is not None:
            allowed_assets = {
                hypothesis.hypothesis_card_ref,
                goal.strategy_goal_ref,
                _text(getattr(universe, "universe_definition_ref", "")),
                _text(getattr(regime, "regime_scenario_ref", "")),
            }
            rag_asset_ref = _text(getattr(rag, "asset_ref", ""))
            if rag_asset_ref not in allowed_assets:
                violations.append("M1-M2 RAG does not bind the design bundle")
            permission = getattr(rag, "permission", None)
            if owner not in tuple(getattr(permission, "allowed_users", ()) or ()):
                violations.append("M1-M2 RAG permission does not bind owner")
            if rag_asset_ref not in tuple(
                getattr(permission, "allowed_assets", ()) or ()
            ):
                violations.append("M1-M2 RAG permission does not bind design asset")
        return tuple(violations)

    return (
        {
            "strategy_goal_ref": PlatformTypedSourceAdapter("strategy_goal_store", load_goal, validate_goal),
            "hypothesis_card_ref": PlatformTypedSourceAdapter("hypothesis_owner_envelope", load_card, validate_card),
            "universe_definition_ref": PlatformTypedSourceAdapter("research_design_universe", load_universe, validate_universe),
            "regime_scenario_ref": PlatformTypedSourceAdapter("research_design_regime", load_regime, validate_regime),
        },
        validate_row,
    )


def _m4_m5_adapters_and_validator(
    context: PlatformSourceAdaptersM1M8Context,
) -> tuple[dict[str, PlatformTypedSourceAdapter], PlatformRowLinkValidator]:
    design = context.research_design_registry
    factors = context.factor_registry
    graph = context.research_graph_store

    def load_factor(ref: str, owner: str, record: PlatformCapabilityRecord) -> ResolvedFactorSource:
        if _row(record) != M4_M5:
            raise LookupError("Factor adapter only supports M4-M5")
        envelope = design.factor_envelope(ref, owner_user_id=owner)
        if _text(getattr(envelope, "factor_ref", "")) != ref:
            raise LookupError("Factor envelope identity mismatch")
        factor = factors.get(_text(getattr(envelope, "factor_id", "")), int(getattr(envelope, "version", 0)))
        if source_object_hash(factor) != _text(getattr(envelope, "source_content_hash", "")):
            raise LookupError("Factor source content drifted")
        return ResolvedFactorSource(ref, owner, envelope, factor)

    def validate_factor(value: ResolvedFactorSource, owner: str, record: PlatformCapabilityRecord) -> tuple[str, ...]:
        violations: list[str] = []
        if value.owner_user_id != owner or _owner_of(value.envelope) != owner:
            violations.append("Factor owner mismatch")
        if value.factor_ref != _specific(record).get("factor_ref"):
            violations.append("Factor ref mismatch")
        if _text(value.envelope.linkage.qro_ref) != _text(record.qro_ref):
            violations.append("Factor QRO linkage mismatch")
        return tuple(violations)

    def load_label(ref: str, owner: str, record: PlatformCapabilityRecord) -> Any:
        if _row(record) != M4_M5:
            raise LookupError("LabelDefinition adapter only supports M4-M5")
        return design.label_definition(ref, owner_user_id=owner)

    def validate_label(value: Any, owner: str, record: PlatformCapabilityRecord) -> tuple[str, ...]:
        violations: list[str] = []
        if _owner_of(value) != owner:
            violations.append("LabelDefinition owner mismatch")
        if _text(getattr(value, "label_ref", "")) != _specific(record).get("label_ref"):
            violations.append("LabelDefinition ref mismatch")
        return tuple(violations)

    def validate_row(record: PlatformCapabilityRecord, owner: str, values: dict[str, Any]) -> tuple[str, ...]:
        factor = values.get("factor_ref")
        label = values.get("label_ref")
        if not isinstance(factor, ResolvedFactorSource) or label is None:
            return ("M4-M5 requires the exact Factor and LabelDefinition",)
        violations: list[str] = []
        violations.extend(_binding_graph_violations(graph, record, owner))
        if _text(getattr(factor.envelope, "label_ref", "")) != _text(getattr(label, "label_ref", "")):
            violations.append("M4-M5 Factor/Label binding mismatch")
        historical_graph_ref, errors = _violation_call(
            "M4-M5 binding Graph",
            lambda: _historical_graph_ref_for_binding(graph, record),
        )
        violations.extend(errors)
        if (
            historical_graph_ref is not None
            and _text(factor.envelope.linkage.research_graph_ref)
            != historical_graph_ref
        ):
            violations.append("M4-M5 graph mismatch")
        if _text(factor.envelope.linkage.lifecycle_ref) != _text(record.lifecycle_ref):
            violations.append("M4-M5 lifecycle mismatch")
        qro, errors = _violation_call("M4-M5 QRO", lambda: graph.qro(_text(record.qro_ref)))
        violations.extend(errors)
        if qro is not None:
            if _owner_of(qro) != owner or _qro_type(qro) != "Factor":
                violations.append("M4-M5 QRO must be an owner-scoped Factor")
            output = _qro_output(qro)
            for key, expected in _specific(record).items():
                if _text(output.get(key)) != expected:
                    violations.append(f"M4-M5 QRO output {key} mismatch")
        lifecycle, errors = _violation_call("M4-M5 lifecycle", lambda: _lifecycle_for_row(context, record, owner))
        violations.extend(errors)
        if lifecycle is not None:
            if (
                _text(getattr(lifecycle, "asset_type", "")) != "Factor"
                or _text(getattr(lifecycle, "asset_ref", ""))
                != _text(factor.envelope.linkage.lifecycle_ref)
                or factor.factor_ref
                not in tuple(getattr(lifecycle, "evidence_refs", ()) or ())
            ):
                violations.append("M4-M5 lifecycle does not bind Factor")
        chain, errors = _violation_call("M4-M5 Mathematical Spine", lambda: _chain_for_row(context, record, owner))
        violations.extend(errors)
        if chain is not None:
            if _text(getattr(chain, "factor_ref", "")) != factor.factor_ref:
                violations.append("M4-M5 Mathematical Spine factor mismatch")
            chain_refs = set(tuple(getattr(chain, "validation_refs", ()) or ())) | set(tuple(getattr(chain, "evidence_refs", ()) or ()))
            if _text(getattr(label, "label_ref", "")) not in chain_refs:
                violations.append("M4-M5 Mathematical Spine label mismatch")
        rag, errors = _violation_call("M4-M5 RAG", lambda: _rag_for_row(context, record, owner))
        violations.extend(errors)
        if rag is not None:
            expected_asset = f"factor:{factor.envelope.factor_id}"
            if _text(getattr(rag, "asset_ref", "")) not in {factor.factor_ref, expected_asset}:
                violations.append("M4-M5 RAG does not bind Factor")
            metadata = dict(getattr(rag, "metadata", {}) or {})
            if _text(metadata.get("formula_hash")) != content_hash({"formula": getattr(factor.factor, "formula", "")}):
                violations.append("M4-M5 RAG factor content hash mismatch")
            permission = getattr(rag, "permission", None)
            if owner not in tuple(getattr(permission, "allowed_users", ()) or ()):
                violations.append("M4-M5 RAG permission does not bind owner")
            if _text(getattr(rag, "asset_ref", "")) not in tuple(
                getattr(permission, "allowed_assets", ()) or ()
            ):
                violations.append("M4-M5 RAG permission does not bind Factor")
        return tuple(violations)

    return (
        {
            "factor_ref": PlatformTypedSourceAdapter("factor_owner_envelope", load_factor, validate_factor),
            "label_ref": PlatformTypedSourceAdapter("research_design_label", load_label, validate_label),
        },
        validate_row,
    )


def _m7_m8_adapters_and_validator(
    context: PlatformSourceAdaptersM1M8Context,
) -> tuple[dict[str, PlatformTypedSourceAdapter], PlatformRowLinkValidator]:
    design = context.research_design_registry
    contracts = context.signal_contract_registry
    validations = context.signal_validation_registry
    graph = context.research_graph_store

    def load_signal(ref: str, owner: str, record: PlatformCapabilityRecord) -> ResolvedSignalContractSource:
        if _row(record) != M7_M8:
            raise LookupError("SignalContract adapter only supports M7-M8")
        envelope = design.signal_contract_envelope(ref, owner_user_id=owner)
        if _text(getattr(envelope, "signal_contract_ref", "")) != ref:
            raise LookupError("SignalContract envelope identity mismatch")
        contract = contracts.get(ref.removeprefix("signal_contract:"))
        if source_object_hash(contract) != _text(getattr(envelope, "source_content_hash", "")):
            raise LookupError("SignalContract source content drifted")
        return ResolvedSignalContractSource(ref, owner, envelope, contract)

    def validate_signal(value: ResolvedSignalContractSource, owner: str, record: PlatformCapabilityRecord) -> tuple[str, ...]:
        violations: list[str] = []
        if value.owner_user_id != owner or _owner_of(value.envelope) != owner:
            violations.append("SignalContract owner mismatch")
        if value.signal_contract_ref != _specific(record).get("signal_contract_ref"):
            violations.append("SignalContract ref mismatch")
        return tuple(violations)

    def load_validation(ref: str, owner: str, record: PlatformCapabilityRecord) -> Any:
        if _row(record) != M7_M8:
            raise LookupError("SignalValidation adapter only supports M7-M8")
        return validations.validation(ref, owner_user_id=owner)

    def validate_validation(value: Any, owner: str, record: PlatformCapabilityRecord) -> tuple[str, ...]:
        violations: list[str] = []
        if _owner_of(value) != owner:
            violations.append("SignalValidation owner mismatch")
        if _text(getattr(value, "validation_id", "")) != _specific(record).get("signal_validation_ref"):
            violations.append("SignalValidation ref mismatch")
        if _text(getattr(getattr(value, "verdict", ""), "value", getattr(value, "verdict", ""))) != "accepted":
            violations.append("SignalValidation is not accepted")
        return tuple(violations)

    def load_strategy(ref: str, owner: str, record: PlatformCapabilityRecord) -> ResolvedStrategyBookSource:
        if _row(record) != M7_M8:
            raise LookupError("StrategyBook adapter only supports M7-M8")
        source = design.strategy_book(ref, owner_user_id=owner)
        strategy = dict(getattr(source, "strategy_book", {}) or {})
        if content_hash(strategy) != _text(getattr(source, "source_content_hash", "")):
            raise LookupError("StrategyBook source content drifted")
        if _text(getattr(source, "strategy_book_ref", "")) != ref:
            raise LookupError("StrategyBook identity mismatch")
        return ResolvedStrategyBookSource(ref, owner, source, strategy)

    def validate_strategy(value: ResolvedStrategyBookSource, owner: str, record: PlatformCapabilityRecord) -> tuple[str, ...]:
        violations: list[str] = []
        if value.owner_user_id != owner or _owner_of(value.record) != owner:
            violations.append("StrategyBook owner mismatch")
        if value.strategy_book_ref != _specific(record).get("strategy_book_ref"):
            violations.append("StrategyBook ref mismatch")
        return tuple(violations)

    def load_policy(ref: str, owner: str, record: PlatformCapabilityRecord) -> Any:
        if _row(record) != M7_M8:
            raise LookupError("PortfolioPolicy adapter only supports M7-M8")
        return design.portfolio_policy(ref, owner_user_id=owner)

    def validate_policy(value: Any, owner: str, record: PlatformCapabilityRecord) -> tuple[str, ...]:
        violations: list[str] = []
        if _owner_of(value) != owner:
            violations.append("PortfolioPolicy owner mismatch")
        if _text(getattr(value, "portfolio_policy_ref", "")) != _specific(record).get("portfolio_policy_ref"):
            violations.append("PortfolioPolicy ref mismatch")
        if _text(getattr(value.linkage, "qro_ref", "")) != _text(record.qro_ref):
            violations.append("PortfolioPolicy QRO linkage mismatch")
        return tuple(violations)

    def validate_row(record: PlatformCapabilityRecord, owner: str, values: dict[str, Any]) -> tuple[str, ...]:
        signal = values.get("signal_contract_ref")
        validation = values.get("signal_validation_ref")
        strategy = values.get("strategy_book_ref")
        policy = values.get("portfolio_policy_ref")
        if not isinstance(signal, ResolvedSignalContractSource) or not isinstance(strategy, ResolvedStrategyBookSource):
            return ("M7-M8 requires exact SignalContract and StrategyBook owner envelopes",)
        if validation is None or policy is None:
            return ("M7-M8 requires exact SignalValidation and PortfolioPolicy",)
        violations: list[str] = []
        violations.extend(_binding_graph_violations(graph, record, owner))
        historical_graph_ref, errors = _violation_call(
            "M7-M8 binding Graph",
            lambda: _historical_graph_ref_for_binding(graph, record),
        )
        violations.extend(errors)
        exact_pairs = (
            (getattr(policy, "signal_contract_ref", ""), signal.signal_contract_ref, "policy signal"),
            (getattr(policy, "signal_validation_ref", ""), getattr(validation, "validation_id", ""), "policy validation"),
            (getattr(policy, "strategy_book_ref", ""), strategy.strategy_book_ref, "policy strategy"),
            (
                getattr(policy, "signal_contract_source_hash", ""),
                getattr(signal.envelope, "source_content_hash", ""),
                "policy signal source hash",
            ),
            (
                getattr(policy, "strategy_book_source_hash", ""),
                getattr(strategy.record, "source_content_hash", ""),
                "policy strategy source hash",
            ),
            (
                getattr(validation, "signal_ref", ""),
                signal.signal_contract_ref.removeprefix("signal_contract:"),
                "validation signal",
            ),
            (getattr(policy.linkage, "lifecycle_ref", ""), record.lifecycle_ref, "lifecycle"),
        )
        for actual, expected, label in exact_pairs:
            if _text(actual) != _text(expected):
                violations.append(f"M7-M8 {label} mismatch")
        if (
            historical_graph_ref is not None
            and _text(getattr(policy.linkage, "research_graph_ref", ""))
            != historical_graph_ref
        ):
            violations.append("M7-M8 graph mismatch")
        strategy_signal_refs = {
            _text(item) for item in tuple(strategy.strategy.get("signal_refs", ()) or ())
        }
        if signal.signal_contract_ref.removeprefix("signal_contract:") not in strategy_signal_refs:
            violations.append("M7-M8 StrategyBook does not bind SignalContract")
        strategy_validation_refs = {
            _text(item)
            for item in tuple(strategy.strategy.get("signal_validation_refs", ()) or ())
        }
        if _text(getattr(validation, "validation_id", "")) not in strategy_validation_refs:
            violations.append("M7-M8 StrategyBook does not bind SignalValidation")
        qro, errors = _violation_call("M7-M8 QRO", lambda: graph.qro(_text(record.qro_ref)))
        violations.extend(errors)
        if qro is not None:
            if _owner_of(qro) != owner or _qro_type(qro) != "PortfolioPolicy":
                violations.append("M7-M8 QRO must be an owner-scoped PortfolioPolicy")
            output = _qro_output(qro)
            for key, expected in _specific(record).items():
                if _text(output.get(key)) != expected:
                    violations.append(f"M7-M8 QRO output {key} mismatch")
        lifecycle, errors = _violation_call("M7-M8 lifecycle", lambda: _lifecycle_for_row(context, record, owner))
        violations.extend(errors)
        if lifecycle is not None and (
            _text(getattr(lifecycle, "asset_type", "")) != "PortfolioPolicy"
            or _text(getattr(lifecycle, "asset_ref", "")) != _text(getattr(policy, "portfolio_policy_ref", ""))
        ):
            violations.append("M7-M8 lifecycle does not bind PortfolioPolicy")
        chain, errors = _violation_call("M7-M8 Mathematical Spine", lambda: _chain_for_row(context, record, owner))
        violations.extend(errors)
        if chain is not None:
            for field, expected in (
                ("signal_contract_ref", signal.signal_contract_ref),
                ("strategy_book_ref", strategy.strategy_book_ref),
                ("portfolio_policy_ref", getattr(policy, "portfolio_policy_ref", "")),
            ):
                if _text(getattr(chain, field, "")) != _text(expected):
                    violations.append(f"M7-M8 Mathematical Spine {field} mismatch")
        rag, errors = _violation_call("M7-M8 RAG", lambda: _rag_for_row(context, record, owner))
        violations.extend(errors)
        if rag is not None:
            allowed_assets = {
                signal.signal_contract_ref,
                signal.signal_contract_ref.removeprefix("signal_contract:"),
                strategy.strategy_book_ref,
                _text(getattr(policy, "portfolio_policy_ref", "")),
            }
            rag_asset_ref = _text(getattr(rag, "asset_ref", ""))
            if rag_asset_ref not in allowed_assets:
                violations.append("M7-M8 RAG does not bind signal/strategy/policy bundle")
            permission = getattr(rag, "permission", None)
            if owner not in tuple(getattr(permission, "allowed_users", ()) or ()):
                violations.append("M7-M8 RAG permission does not bind owner")
            if rag_asset_ref not in tuple(
                getattr(permission, "allowed_assets", ()) or ()
            ):
                violations.append("M7-M8 RAG permission does not bind policy asset")
        return tuple(violations)

    return (
        {
            "signal_contract_ref": PlatformTypedSourceAdapter("signal_contract_owner_envelope", load_signal, validate_signal),
            "signal_validation_ref": PlatformTypedSourceAdapter("signal_validation_registry", load_validation, validate_validation),
            "strategy_book_ref": PlatformTypedSourceAdapter("research_design_strategy_book", load_strategy, validate_strategy),
            "portfolio_policy_ref": PlatformTypedSourceAdapter("research_design_portfolio_policy", load_policy, validate_policy),
        },
        validate_row,
    )


def _m3_adapters_and_validator(
    context: PlatformSourceAdaptersM1M8Context,
) -> tuple[dict[str, PlatformTypedSourceAdapter], PlatformRowLinkValidator]:
    graph = context.research_graph_store
    onboarding = context.onboarding_registry
    market_data = context.market_data_registry
    lifecycle = context.asset_lifecycle_registry
    datasets = context.dataset_registry
    rag = context.rag_index
    spine = context.spine_chain_registry

    def load_skill(ref: str, owner: str, record: PlatformCapabilityRecord) -> Any:
        if _row(record) != M3:
            raise LookupError("ingestion skill adapter only supports M3")
        skill = onboarding.ingestion_skill(ref, owner_user_id=owner)
        if _text(getattr(skill, "skill_id", "")) != ref or _owner_of(skill) != owner:
            raise LookupError("IngestionSkill identity/owner mismatch")
        return skill

    def validate_skill(value: Any, owner: str, record: PlatformCapabilityRecord) -> tuple[str, ...]:
        violations: list[str] = []
        if _row(record) != M3:
            violations.append("IngestionSkill is not attached to M3")
        if _owner_of(value) != owner:
            violations.append("IngestionSkill owner mismatch")
        if _text(getattr(value, "lifecycle_state", "")) != "active":
            violations.append("IngestionSkill is not active")
        if _text(getattr(value, "skill_id", "")) != _specific(record).get(
            "ingestion_skill_ref"
        ):
            violations.append("IngestionSkill ref mismatch")
        return tuple(violations)

    def load_instrument(ref: str, owner: str, record: PlatformCapabilityRecord) -> Any:
        if _row(record) != M3:
            raise LookupError("instrument adapter only supports M3")
        instrument = market_data.instrument(ref, owner_user_id=owner)
        if _text(getattr(instrument, "instrument_ref", "")) != ref:
            raise LookupError("InstrumentSpec identity mismatch")
        return instrument

    def validate_instrument(
        value: Any,
        _owner: str,
        record: PlatformCapabilityRecord,
    ) -> tuple[str, ...]:
        violations: list[str] = []
        if _row(record) != M3:
            violations.append("InstrumentSpec is not attached to M3")
        if _text(getattr(value, "instrument_ref", "")) != _specific(record).get(
            "instrument_spec_ref"
        ):
            violations.append("InstrumentSpec ref mismatch")
        return tuple(violations)

    def validate_row(
        record: PlatformCapabilityRecord,
        owner: str,
        values: dict[str, Any],
    ) -> tuple[str, ...]:
        violations: list[str] = []
        violations.extend(_binding_graph_violations(graph, record, owner))
        skill = values.get("ingestion_skill_ref")
        instrument = values.get("instrument_spec_ref")
        if skill is None or instrument is None:
            return ("M3 requires the exact IngestionSkill and InstrumentSpec",)

        qro, errors = _violation_call(
            "M3 QRO",
            lambda: graph.qro(_text(record.qro_ref)),
        )
        violations.extend(errors)
        if qro is None:
            return tuple(violations)
        if _owner_of(qro) != owner or _qro_type(qro) != "Dataset":
            violations.append("M3 QRO must be an owner-scoped Dataset QRO")
        input_contract = getattr(qro, "input_contract", None)
        output_contract = getattr(qro, "output_contract", None)
        if not isinstance(input_contract, dict) or not isinstance(output_contract, dict):
            return (*violations, "M3 Dataset QRO contracts are malformed")
        dataset_ref = _text(output_contract.get("dataset_ref"))
        dataset, errors = _violation_call(
            "M3 DatasetSemantics",
            lambda: market_data.dataset(dataset_ref, owner_user_id=owner),
        )
        violations.extend(errors)
        update, errors = _violation_call(
            "M3 IngestionSkillUpdate",
            lambda: lifecycle.ingestion_skill_update(
                _text(record.lifecycle_ref), owner_user_id=owner
            ),
        )
        violations.extend(errors)
        source, errors = _violation_call(
            "M3 DataSourceAsset",
            lambda: onboarding.data_source(
                _text(getattr(skill, "source_ref", "")), owner_user_id=owner
            ),
        )
        violations.extend(errors)
        pit_rule, errors = _violation_call(
            "M3 PIT rule",
            lambda: onboarding.data_connector_pit_bitemporal_rule(
                _text(getattr(skill, "pit_bitemporal_rules_ref", "")),
                owner_user_id=owner,
            ),
        )
        violations.extend(errors)
        chain, errors = _violation_call(
            "M3 Mathematical Spine",
            lambda: spine.verified_chain(_text(record.math_spine_ref), owner=owner),
        )
        violations.extend(errors)
        rag_document, errors = _violation_call(
            "M3 RAG",
            lambda: rag.document_for_owner(
                _text(record.rag_ref), owner_user_id=owner, require_current=True
            ),
        )
        violations.extend(errors)
        if dataset is None or update is None or source is None or pit_rule is None:
            return tuple(violations)
        resolver = getattr(datasets, "resolve_version_ref", None)
        if not callable(resolver):
            return (*violations, "M3 DatasetVersion exact-ref resolver is unavailable")
        version, errors = _violation_call(
            "M3 DatasetVersion",
            lambda: resolver(_text(getattr(update, "dataset_version_ref", ""))),
        )
        violations.extend(errors)
        expected_input = {
            "dataset_ref": _text(getattr(dataset, "dataset_ref", "")),
            "source_ref": _text(getattr(dataset, "source_ref", "")),
            "version": _text(getattr(dataset, "version", "")),
            "record_hash": content_hash(dataset.to_dict()),
        }
        for key, expected in expected_input.items():
            if _text(input_contract.get(key)) != expected:
                violations.append(f"M3 Dataset QRO input {key} mismatch")
        expected_output = {
            "status": "dataset_semantics_recorded",
            "dataset_ref": _text(getattr(dataset, "dataset_ref", "")),
            "known_at_ref": _text(getattr(dataset, "known_at_ref", "")),
            "effective_at_ref": _text(getattr(dataset, "effective_at_ref", "")),
            "pit_bitemporal_rules_ref": _text(
                getattr(dataset, "pit_bitemporal_rules_ref", "")
            ),
            "quality_status": _text(getattr(dataset, "quality_status", "")),
            "freshness_status": _text(getattr(dataset, "freshness_status", "")),
        }
        for key, expected in expected_output.items():
            if _text(output_contract.get(key)) != expected:
                violations.append(f"M3 Dataset QRO output {key} mismatch")
        if _text(getattr(qro, "implementation_hash", "")) != (
            "market_data_dataset:" + content_hash(dataset.to_dict())
        ):
            violations.append("M3 Dataset QRO implementation hash mismatch")

        exact_pairs = (
            (getattr(skill, "source_ref", ""), getattr(source, "source_ref", ""), "source"),
            (getattr(update, "update_ref", ""), record.lifecycle_ref, "lifecycle identity"),
            (getattr(update, "skill_ref", ""), getattr(skill, "skill_id", ""), "update skill"),
            (getattr(update, "skill_version", ""), getattr(skill, "version", ""), "update version"),
            (getattr(update, "source_ref", ""), getattr(skill, "source_ref", ""), "update source"),
            (getattr(dataset, "source_ref", ""), getattr(skill, "source_ref", ""), "dataset source"),
            (getattr(dataset, "known_at_ref", ""), getattr(update, "known_at_ref", ""), "dataset known_at"),
            (
                getattr(dataset, "effective_at_ref", ""),
                getattr(update, "effective_at_ref", ""),
                "dataset effective_at",
            ),
            (
                getattr(dataset, "pit_bitemporal_rules_ref", ""),
                getattr(skill, "pit_bitemporal_rules_ref", ""),
                "dataset PIT rule",
            ),
            (getattr(pit_rule, "skill_id", ""), getattr(skill, "skill_id", ""), "PIT skill"),
            (getattr(pit_rule, "source_ref", ""), getattr(skill, "source_ref", ""), "PIT source"),
            (
                getattr(instrument, "symbol_mapping_ref", ""),
                getattr(skill, "schema_mapping_ref", ""),
                "instrument schema mapping",
            ),
        )
        for actual, expected, label in exact_pairs:
            if _text(actual) != _text(expected):
                violations.append(f"M3 {label} mismatch")
        if _owner_of(skill) != owner or _text(getattr(update, "recorded_by", "")) != owner:
            violations.append("M3 skill/update owner mismatch")
        if _text(getattr(pit_rule, "recorded_by", "")) != owner:
            violations.append("M3 PIT rule owner mismatch")
        if version is not None:
            metadata = dict(getattr(version, "metadata", {}) or {})
            version_pairs = (
                (getattr(dataset, "version", ""), getattr(version, "version_id", ""), "version"),
                (getattr(dataset, "checksum", ""), getattr(version, "sha256", ""), "checksum"),
                (getattr(version, "dataset_id", ""), getattr(skill, "output_dataset_id", ""), "dataset id"),
                (metadata.get("ingestion_skill_id"), getattr(skill, "skill_id", ""), "skill id metadata"),
                (metadata.get("ingestion_skill_version"), getattr(skill, "version", ""), "skill version metadata"),
                (metadata.get("source_ref"), getattr(skill, "source_ref", ""), "source metadata"),
            )
            for actual, expected, label in version_pairs:
                if _text(actual) != _text(expected):
                    violations.append(f"M3 DatasetVersion {label} mismatch")
            if getattr(version, "row_count", None) != getattr(update, "row_count", None):
                violations.append("M3 DatasetVersion row count mismatch")
        required_lineage = {
            _text(value)
            for value in (
                getattr(update, "update_ref", ""),
                getattr(update, "lineage_ref", ""),
                getattr(pit_rule, "rule_ref", ""),
                getattr(pit_rule, "field_mapping_ref", ""),
                getattr(pit_rule, "schema_probe_ref", ""),
            )
            if _text(value)
        }
        if not required_lineage.issubset(
            {_text(value) for value in tuple(getattr(dataset, "lineage_refs", ()) or ())}
        ):
            violations.append("M3 DatasetSemantics lineage is incomplete")
        if chain is not None and _text(getattr(chain, "data_semantics_ref", "")) != dataset_ref:
            violations.append("M3 Mathematical Spine does not bind DatasetSemantics")
        if rag_document is not None:
            permission = getattr(rag_document, "permission", None)
            if _text(getattr(rag_document, "asset_ref", "")) != dataset_ref:
                violations.append("M3 RAG asset_ref does not bind DatasetSemantics")
            if dataset_ref not in tuple(getattr(permission, "allowed_assets", ()) or ()):
                violations.append("M3 RAG permission does not bind DatasetSemantics")
            if owner not in tuple(getattr(permission, "allowed_users", ()) or ()):
                violations.append("M3 RAG permission does not bind owner")
        return tuple(violations)

    return (
        {
            "ingestion_skill_ref": PlatformTypedSourceAdapter(
                source_kind="onboarding_ingestion_skill",
                load=load_skill,
                validate_linkage=validate_skill,
            ),
            "instrument_spec_ref": PlatformTypedSourceAdapter(
                source_kind="market_data_instrument_spec",
                load=load_instrument,
                validate_linkage=validate_instrument,
            ),
        },
        validate_row,
    )


def _model_version_parts(model_version_ref: str) -> tuple[str, int]:
    prefix = "model_version:"
    token = _text(model_version_ref)
    if not token.startswith(prefix) or ":v" not in token[len(prefix) :]:
        raise LookupError("model_version_ref is not canonical")
    model, version = token[len(prefix) :].rsplit(":v", 1)
    if not model or not version.isdigit() or int(version) <= 0:
        raise LookupError("model_version_ref is not canonical")
    return model, int(version)


def _m6_adapters_and_validator(
    context: PlatformSourceAdaptersM1M8Context,
) -> tuple[dict[str, PlatformTypedSourceAdapter], PlatformRowLinkValidator]:
    graph = context.research_graph_store
    rag = context.rag_index
    spine = context.spine_chain_registry
    governance = context.model_governance_registry
    training = context.training_service
    models = context.model_registry
    lifecycle_loader = context.lifecycle_loader
    assert lifecycle_loader is not None

    def load_passport(ref: str, owner: str, _record: PlatformCapabilityRecord) -> Any:
        passport = governance.passport(ref, owner_user_id=owner)
        if _text(getattr(passport, "passport_id", "")) != ref:
            raise LookupError("ModelPassport identity mismatch")
        if _owner_of(passport) != owner:
            raise LookupError("ModelPassport owner mismatch")
        return passport

    def validate_passport(value: Any, owner: str, record: PlatformCapabilityRecord) -> tuple[str, ...]:
        violations: list[str] = []
        if _owner_of(value) != owner:
            violations.append("ModelPassport owner mismatch")
        if _text(getattr(value, "passport_id", "")) != _specific(record).get(
            "model_passport_ref"
        ):
            violations.append("ModelPassport ref mismatch")
        if _row(record) == M6 and not _text(getattr(value, "validation_dossier_ref", "")):
            violations.append("M6 ModelPassport lacks validation_dossier_ref")
        return tuple(violations)

    def load_dossier(
        ref: str,
        owner: str,
        record: PlatformCapabilityRecord,
    ) -> ResolvedValidationDossierSource:
        if _row(record) != M6:
            raise LookupError("ValidationDossier adapter only supports M6")
        prefix = "validation_dossier:"
        if not ref.startswith(prefix) or not ref[len(prefix) :]:
            raise LookupError("ValidationDossier ref is not canonical")
        job_id = ref[len(prefix) :]
        job = training.get_job(job_id)
        if _text(getattr(job, "job_id", "")) != job_id:
            raise LookupError("training job identity mismatch")
        if _owner_of(job) != owner:
            raise LookupError("training job owner mismatch")
        if _text(getattr(job, "validation_dossier_ref", "")) != ref:
            raise LookupError("training job dossier ref mismatch")
        artifact_dir = _required(getattr(job, "artifact_dir", ""), "training artifact_dir")
        artifact_root = Path(artifact_dir)
        unresolved_path = artifact_root / "validation_dossier.json"
        if artifact_root.is_symlink() or unresolved_path.is_symlink():
            raise LookupError("persisted validation dossier cannot use symlinks")
        path = unresolved_path.resolve()
        if path.parent != artifact_root.resolve() or not path.is_file():
            raise LookupError("persisted validation_dossier.json is unavailable")
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise LookupError("persisted validation dossier is unreadable") from exc
        if not isinstance(payload, dict) or _text(payload.get("validation_dossier_ref")) != ref:
            raise LookupError("persisted validation dossier identity mismatch")
        return ResolvedValidationDossierSource(
            validation_dossier_ref=ref,
            owner_user_id=owner,
            job=job,
            dossier=payload,
        )

    def validate_dossier(
        value: ResolvedValidationDossierSource,
        owner: str,
        record: PlatformCapabilityRecord,
    ) -> tuple[str, ...]:
        violations: list[str] = []
        if _row(record) != M6:
            violations.append("ValidationDossier is not attached to M6")
        if value.owner_user_id != owner or _owner_of(value.job) != owner:
            violations.append("ValidationDossier training owner mismatch")
        if value.validation_dossier_ref != _specific(record).get("validation_dossier_ref"):
            violations.append("ValidationDossier ref mismatch")
        if _text(getattr(value.job, "qro_id", "")) != _text(record.qro_ref):
            violations.append("ValidationDossier training QRO mismatch")
        historical_graph_ref, errors = _violation_call(
            "ValidationDossier binding Graph",
            lambda: _historical_graph_ref_for_binding(graph, record),
        )
        violations.extend(errors)
        if (
            historical_graph_ref is not None
            and _text(getattr(value.job, "research_graph_command_id", ""))
            != historical_graph_ref
        ):
            violations.append("ValidationDossier training graph command mismatch")
        return tuple(violations)

    def validate_row(
        record: PlatformCapabilityRecord,
        owner: str,
        values: dict[str, Any],
    ) -> tuple[str, ...]:
        passport = values.get("model_passport_ref")
        dossier_source = values.get("validation_dossier_ref")
        if passport is None or not isinstance(dossier_source, ResolvedValidationDossierSource):
            return ("M6 requires the exact ModelPassport and ValidationDossier",)
        job = dossier_source.job
        dossier = dossier_source.dossier
        violations: list[str] = []
        violations.extend(_binding_graph_violations(graph, record, owner))
        qro, errors = _violation_call(
            "M6 QRO",
            lambda: graph.qro(_text(record.qro_ref)),
        )
        violations.extend(errors)
        if qro is None:
            return tuple(violations)
        if _owner_of(qro) != owner or _qro_type(qro) != "Model":
            violations.append("M6 QRO must be an owner-scoped Model QRO")
        input_contract = getattr(qro, "input_contract", None)
        output_contract = getattr(qro, "output_contract", None)
        if not isinstance(input_contract, dict) or not isinstance(output_contract, dict):
            return (*violations, "M6 Model QRO contracts are malformed")
        job_id = _text(getattr(job, "job_id", ""))
        model_version_ref = _text(getattr(passport, "model_version_ref", ""))
        model_id, version_number = _model_version_parts(model_version_ref)
        versions, errors = _violation_call(
            "M6 ModelVersion",
            lambda: [
                item
                for item in models.list_versions(model_id, owner_user_id=owner)
                if getattr(item, "version", None) == version_number
            ],
        )
        violations.extend(errors)
        version = versions[0] if isinstance(versions, list) and len(versions) == 1 else None
        if versions is not None and version is None:
            violations.append("M6 owner-scoped ModelVersion is missing or ambiguous")

        expected_input = {
            "entry_source": "api",
            "executed_by": "training_service",
            "job_id": job_id,
            "model": _text(getattr(job, "model", "")),
            "request_hash": content_hash(dict(getattr(job, "request", {}) or {})),
        }
        for key, expected in expected_input.items():
            if _text(input_contract.get(key)) != expected:
                violations.append(f"M6 Model QRO input {key} mismatch")
        expected_output = {
            "status": "succeeded",
            "job_id": job_id,
            "model": _text(getattr(job, "model", "")),
            "model_version": str(getattr(job, "model_version", "")),
            "model_version_ref": model_version_ref,
            "model_passport_ref": _text(getattr(passport, "passport_id", "")),
            "validation_dossier_ref": dossier_source.validation_dossier_ref,
            "run_id": _text(getattr(job, "run_id", "")),
            "metrics_hash": content_hash(dict(getattr(job, "metrics", {}) or {})),
        }
        for key, expected in expected_output.items():
            if _text(output_contract.get(key)) != expected:
                violations.append(f"M6 Model QRO output {key} mismatch")
        expected_implementation_hash = "training_job:" + content_hash(
            {
                "job_id": job_id,
                "model_version_ref": model_version_ref,
                "request_hash": content_hash(dict(getattr(job, "request", {}) or {})),
                "metrics_hash": content_hash(dict(getattr(job, "metrics", {}) or {})),
            }
        )
        if _text(getattr(qro, "implementation_hash", "")) != expected_implementation_hash:
            violations.append("M6 Model QRO implementation hash mismatch")
        passport_pairs = (
            (getattr(passport, "training_plan_ref", ""), f"training_plan:{job_id}", "training plan"),
            (
                getattr(passport, "training_run_ref", ""),
                f"training_run:{_text(getattr(job, 'run_id', ''))}",
                "training run",
            ),
            (
                getattr(passport, "validation_dossier_ref", ""),
                dossier_source.validation_dossier_ref,
                "validation dossier",
            ),
            (getattr(job, "model_passport_ref", ""), getattr(passport, "passport_id", ""), "job passport"),
            (getattr(job, "validation_dossier_ref", ""), dossier_source.validation_dossier_ref, "job dossier"),
        )
        for actual, expected, label in passport_pairs:
            if _text(actual) != _text(expected):
                violations.append(f"M6 {label} mismatch")
        if _text(getattr(job, "status", "")) != "succeeded" or _owner_of(job) != owner:
            violations.append("M6 training job is not a succeeded owner-scoped head")
        if _text(getattr(job, "model", "")) != model_id or getattr(
            job, "model_version", None
        ) != version_number:
            violations.append("M6 training job model/version does not match ModelPassport")

        dossier_pairs: tuple[tuple[Any, Any, str], ...] = (
            (dossier.get("model_version_ref"), model_version_ref, "model version"),
            (dossier.get("training_run_ref"), getattr(passport, "training_run_ref", ""), "training run"),
            (tuple(dossier.get("dataset_refs") or ()), tuple(getattr(passport, "dataset_refs", ()) or ()), "datasets"),
            (tuple(dossier.get("feature_refs") or ()), tuple(getattr(passport, "feature_refs", ()) or ()), "features"),
            (tuple(dossier.get("label_refs") or ()), tuple(getattr(passport, "label_refs", ()) or ()), "labels"),
            (dict(dossier.get("metrics") or {}), dict(getattr(job, "metrics", {}) or {}), "metrics"),
        )
        for actual, expected, label in dossier_pairs:
            if actual != expected:
                violations.append(f"M6 ValidationDossier {label} mismatch")
        artifacts = tuple(getattr(passport, "artifact_manifest", ()) or ())
        matching_artifacts = [
            item
            for item in artifacts
            if _text(getattr(item, "content_hash", "")) == _text(dossier.get("artifact_hash"))
            and _text(getattr(item, "uri", "")) == _text(dossier.get("artifact_path"))
            and _text(getattr(item, "producer_run_ref", ""))
            == _text(getattr(passport, "training_run_ref", ""))
        ]
        if len(matching_artifacts) != 1:
            violations.append("M6 ValidationDossier does not bind one passport artifact")
        else:
            artifact = matching_artifacts[0]
            artifact_path = Path(_text(getattr(artifact, "uri", "")))
            artifact_hash, errors = _violation_call(
                "M6 model artifact",
                lambda: _sha256_file(artifact_path),
            )
            violations.extend(errors)
            if artifact_hash is not None and artifact_hash != _text(
                getattr(artifact, "content_hash", "")
            ):
                violations.append("M6 model artifact content hash drifted")
            if _text(getattr(artifact, "sandbox_inspection_ref", "")) != _text(
                dossier.get("artifact_inspection_ref")
            ):
                violations.append("M6 artifact inspection ref mismatch")
        if version is not None:
            version_pairs = (
                (getattr(version, "model_passport_ref", ""), getattr(passport, "passport_id", ""), "passport"),
                (getattr(version, "validation_dossier_ref", ""), dossier_source.validation_dossier_ref, "dossier"),
                (getattr(version, "source_run_id", ""), getattr(job, "run_id", ""), "source run"),
            )
            for actual, expected, label in version_pairs:
                if not _text(actual) or _text(actual) != _text(expected):
                    violations.append(f"M6 ModelVersion {label} mismatch")
            if not _text(getattr(version, "model_asset_ref", "")):
                violations.append("M6 ModelVersion asset ref is missing")
            if _text(getattr(version, "artifact_path", "")) != _text(
                dossier.get("artifact_path")
            ):
                violations.append("M6 ModelVersion artifact path mismatch")
        chain, errors = _violation_call(
            "M6 Mathematical Spine",
            lambda: spine.verified_chain(_text(record.math_spine_ref), owner=owner),
        )
        violations.extend(errors)
        if chain is not None and _text(getattr(chain, "model_ref", "")) not in {
            model_version_ref,
            _text(getattr(passport, "passport_id", "")),
        }:
            violations.append("M6 Mathematical Spine does not bind the model lineage")
        lifecycle, errors = _violation_call(
            "M6 lifecycle",
            lambda: lifecycle_loader(_text(record.lifecycle_ref), owner, record),
        )
        violations.extend(errors)
        if lifecycle is not None:
            embedded_owner = _owner_of(lifecycle)
            if embedded_owner and embedded_owner != owner:
                violations.append("M6 lifecycle owner mismatch")
            lifecycle_targets = {
                _text(getattr(lifecycle, field, ""))
                for field in (
                    "logical_asset_ref",
                    "asset_ref",
                    "after_asset_ref",
                    "model_version_ref",
                )
                if _text(getattr(lifecycle, field, ""))
            }
            if not lifecycle_targets.intersection(
                {model_version_ref, _text(getattr(passport, "passport_id", ""))}
            ):
                violations.append("M6 lifecycle record does not bind the model lineage")
        rag_document, errors = _violation_call(
            "M6 RAG",
            lambda: rag.document_for_owner(
                _text(record.rag_ref), owner_user_id=owner, require_current=True
            ),
        )
        violations.extend(errors)
        if rag_document is not None:
            rag_asset_ref = _text(getattr(rag_document, "asset_ref", ""))
            if rag_asset_ref not in {
                model_version_ref,
                _text(getattr(passport, "passport_id", "")),
                dossier_source.validation_dossier_ref,
            }:
                violations.append("M6 RAG asset_ref does not bind the model lineage")
            permission = getattr(rag_document, "permission", None)
            if owner not in tuple(getattr(permission, "allowed_users", ()) or ()):
                violations.append("M6 RAG permission does not bind owner")
            if rag_asset_ref not in tuple(getattr(permission, "allowed_assets", ()) or ()):
                violations.append("M6 RAG permission does not bind model asset")
        return tuple(violations)

    return (
        {
            "model_passport_ref": PlatformTypedSourceAdapter(
                source_kind="model_governance_passport",
                load=load_passport,
                validate_linkage=validate_passport,
            ),
            "validation_dossier_ref": PlatformTypedSourceAdapter(
                source_kind="training_validation_dossier",
                load=load_dossier,
                validate_linkage=validate_dossier,
            ),
        },
        validate_row,
    )


def build_platform_source_adapters_m1_m8(
    context: PlatformSourceAdaptersM1M8Context,
) -> tuple[
    dict[str, PlatformTypedSourceAdapter],
    dict[str, PlatformRowLinkValidator],
]:
    """Build only complete, currently resolvable M1-M8 adapter families."""

    unavailable = unavailable_platform_source_rows_m1_m8(context)
    adapters: dict[str, PlatformTypedSourceAdapter] = {}
    validators: dict[str, PlatformRowLinkValidator] = {}
    for row, factory in (
        (M1_M2, _m1_m2_adapters_and_validator),
        (M4_M5, _m4_m5_adapters_and_validator),
        (M7_M8, _m7_m8_adapters_and_validator),
    ):
        if row in unavailable:
            continue
        row_adapters, row_validator = factory(context)
        overlap = set(adapters).intersection(row_adapters)
        if overlap:
            raise ValueError(f"duplicate platform specific adapters: {sorted(overlap)}")
        adapters.update(row_adapters)
        validators[row] = row_validator
    if M3 not in unavailable:
        m3_adapters, m3_validator = _m3_adapters_and_validator(context)
        overlap = set(adapters).intersection(m3_adapters)
        if overlap:
            raise ValueError(f"duplicate platform specific adapters: {sorted(overlap)}")
        adapters.update(m3_adapters)
        validators[M3] = m3_validator
    if M6 not in unavailable:
        m6_adapters, m6_validator = _m6_adapters_and_validator(context)
        overlap = set(adapters).intersection(m6_adapters)
        if overlap:
            raise ValueError(f"duplicate platform specific adapters: {sorted(overlap)}")
        adapters.update(m6_adapters)
        validators[M6] = m6_validator
    return adapters, validators


__all__ = [
    "PlatformSourceAdaptersM1M8Context",
    "ResolvedValidationDossierSource",
    "build_platform_source_adapters_m1_m8",
    "unavailable_platform_source_rows_m1_m8",
]
