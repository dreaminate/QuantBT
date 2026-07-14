"""Strict read-only resolution for Mathematical Spine external references.

The canonical Spine ledger delegates stage, evidence, and validation references
to a small ``(role, ref, owner) -> bool`` callback.  This module implements that
callback without treating a prefix or a row's mere presence as evidence.

Every typed source must provide all four proofs below:

* an exact canonical reference carried by the returned typed record;
* an owner-aware read whose returned owner equals the authenticated owner;
* a current-head check (append-only immutable records count as their own head);
* two identical read snapshots, so a concurrent head change fails closed.

Legacy Factor, SignalContract, and HypothesisCard stores are deliberately never
read directly.  They are accepted only through the current owner envelope in
``PersistentResearchDesignAssetRegistry`` and an exact source-content hash
reread.  The resolver performs no writes, repairs, migrations, or materializing
lookups.
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, is_dataclass, replace
from enum import Enum
from pathlib import Path, PurePosixPath
from types import MappingProxyType
from typing import Any, Callable, Iterable, Mapping

from ..experiments.store import ModelVersion
from ..factor_factory.registry import Factor
from ..factor_factory.signal_contract import SignalContract
from ..hypothesis.card import HypothesisCard
from .backtest_evidence import BacktestAttributionRecord, BacktestMonitorRecord
from .factor_strategy_boundary import SignalPerformanceValidationRecord
from .market_data_contract import (
    DatasetSemanticsRecord,
    InstrumentSpec,
    MarketDataUseValidationRecord,
)
from .methodology_validation import ValidationDepthRecord, ValidationMethodologyRecord
from .model_governance import ModelGovernancePassport, ModelMonitoringProfile
from .research_design_assets import (
    FactorOwnerEnvelope,
    HypothesisOwnerEnvelope,
    LabelDefinitionRecord,
    PortfolioPolicyRecord,
    RegimeScenarioRecord,
    SignalContractOwnerEnvelope,
    StrategyBookRecord,
    UniverseDefinitionRecord,
    source_object_hash,
)
from .spine import QRORecord


STAGE_REF_ROLES = frozenset(
    {
        "data_semantics_ref",
        "factor_ref",
        "model_ref",
        "forecast_ref",
        "signal_contract_ref",
        "strategy_book_ref",
        "portfolio_policy_ref",
        "risk_policy_ref",
        "execution_policy_ref",
        "backtest_run_ref",
        "attribution_ref",
        "monitor_ref",
    }
)
COLLECTION_REF_ROLES = frozenset(
    {
        "evidence_refs",
        "validation_refs",
        "test_refs",
        "simulation_refs",
        "numerical_check_refs",
        "consistency_input_refs",
    }
)
VERIFIER_REF_ROLE = "verifier_ref"
SUPPORTED_ROLES = STAGE_REF_ROLES | COLLECTION_REF_ROLES | {VERIFIER_REF_ROLE}

_GENERAL_EVIDENCE_ROLES = frozenset(
    {"evidence_refs", "validation_refs", "consistency_input_refs"}
)
_EXECUTED_EVIDENCE_ROLES = frozenset(
    {"test_refs", "simulation_refs", "numerical_check_refs"}
)
_PATH_ROLES = _GENERAL_EVIDENCE_ROLES | _EXECUTED_EVIDENCE_ROLES

_PLACEHOLDER_COMPONENT = re.compile(
    r"(?:^|[:/_.-])(?:synthetic|fixture|test[-_]?only|goal[-_]?closure|"
    r"goalclosure|placeholder|fake|dummy)(?=$|[:/_.-])",
    re.IGNORECASE,
)
_QRO_REF = re.compile(r"(?:qro:)?qro_[0-9a-f]{16}")
_MODEL_VERSION_REF = re.compile(
    r"model_version:(?P<model>[A-Za-z0-9_.-]+):v(?P<version>[1-9][0-9]*)"
)
_FACTOR_REF = re.compile(r"factor:[A-Za-z0-9_.-]+:v[1-9][0-9]*")
_SIGNAL_REF = re.compile(
    r"(?:sig::|signal_contract:(?:sig::)?)[A-Za-z0-9_.-]+"
)
_CANONICAL_PREFIXED_TAIL = re.compile(r"[A-Za-z0-9_.:@+-]+")
_REPO_PATH = re.compile(r"[A-Za-z0-9_.@+-]+(?:/[A-Za-z0-9_.@+-]+)*")
_PYTEST_NODE = re.compile(
    r"[A-Za-z_][A-Za-z0-9_]*(?:\[[A-Za-z0-9_.+-]+\])?"
    r"(?:::[A-Za-z_][A-Za-z0-9_]*(?:\[[A-Za-z0-9_.+-]+\])?)*"
)
_SYMBOL_OR_LINE = re.compile(r"(?:[1-9][0-9]*|[A-Za-z_][A-Za-z0-9_.]*)")

_REPO_SUFFIXES = frozenset(
    {
        ".c",
        ".cc",
        ".cfg",
        ".conf",
        ".cpp",
        ".css",
        ".csv",
        ".go",
        ".h",
        ".hpp",
        ".html",
        ".ini",
        ".java",
        ".js",
        ".json",
        ".jsx",
        ".md",
        ".mjs",
        ".py",
        ".pyi",
        ".rs",
        ".sh",
        ".sql",
        ".toml",
        ".ts",
        ".tsx",
        ".txt",
        ".yaml",
        ".yml",
    }
)


def _exact_text(value: Any) -> str:
    token = str(getattr(value, "value", value) or "")
    if (
        not token
        or token != token.strip()
        or len(token) > 2048
        or any(ord(character) < 32 for character in token)
    ):
        raise ValueError("external reference text is not canonical")
    return token


def _canonical_prefixed_ref(ref: str, prefix: str) -> bool:
    if not ref.startswith(prefix):
        return False
    tail = ref[len(prefix) :]
    return bool(tail and _CANONICAL_PREFIXED_TAIL.fullmatch(tail))


def _enum_json(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    if is_dataclass(value):
        return _enum_json(asdict(value))
    model_dump = getattr(value, "model_dump", None)
    if callable(model_dump):
        return _enum_json(model_dump(mode="json"))
    to_dict = getattr(value, "to_dict", None)
    if callable(to_dict):
        return _enum_json(to_dict())
    if isinstance(value, Mapping):
        return {str(key): _enum_json(child) for key, child in value.items()}
    if isinstance(value, (tuple, list)):
        return [_enum_json(child) for child in value]
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    raise TypeError(f"unsupported external-ref snapshot type: {type(value).__name__}")


def _snapshot(value: Any) -> str:
    return json.dumps(
        _enum_json(value),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


@dataclass(frozen=True)
class OwnerScopedRefSource:
    """One typed, current, owner-scoped external-reference adapter.

    ``accepts_ref`` only routes a canonical reference to a source.  Acceptance
    still requires the loaded record to return that exact reference, the exact
    owner, and ``is_current=True``.  ``load_current`` must be read-only.
    """

    ref_type: str
    roles: frozenset[str]
    accepts_ref: Callable[[str], bool]
    load_current: Callable[[str, str], Any]
    canonical_refs: Callable[[Any], Iterable[str]]
    owner_user_id: Callable[[Any], str]
    is_current: Callable[[Any, str, str], bool]

    def __post_init__(self) -> None:
        ref_type = _exact_text(self.ref_type)
        roles = frozenset(_exact_text(role) for role in self.roles)
        unknown = roles - SUPPORTED_ROLES
        if not roles or unknown:
            raise ValueError(
                f"external-ref source roles must be supported; unknown={sorted(unknown)}"
            )
        if any(not callable(value) for value in (
            self.accepts_ref,
            self.load_current,
            self.canonical_refs,
            self.owner_user_id,
            self.is_current,
        )):
            raise TypeError("external-ref source callbacks must be callable")
        object.__setattr__(self, "ref_type", ref_type)
        object.__setattr__(self, "roles", roles)


@dataclass(frozen=True)
class _OwnedResolvedValue:
    owner_user_id: str
    canonical_refs: tuple[str, ...]
    value: Any
    current: bool = True


def _owned_source(
    *,
    ref_type: str,
    roles: frozenset[str],
    accepts_ref: Callable[[str], bool],
    load_current: Callable[[str, str], _OwnedResolvedValue],
) -> OwnerScopedRefSource:
    return OwnerScopedRefSource(
        ref_type=ref_type,
        roles=roles,
        accepts_ref=accepts_ref,
        load_current=load_current,
        canonical_refs=lambda value: value.canonical_refs,
        owner_user_id=lambda value: value.owner_user_id,
        is_current=lambda value, _ref, _owner: bool(value.current),
    )


def _typed(value: Any, expected_type: type[Any], label: str) -> Any:
    if not isinstance(value, expected_type):
        raise TypeError(f"{label} getter returned {type(value).__name__}")
    return value


def _qro_source(store: Any) -> OwnerScopedRefSource:
    def load(ref: str, owner: str) -> _OwnedResolvedValue:
        qro_id = ref.removeprefix("qro:")
        value = _typed(store.qro(qro_id), QRORecord, "Research Graph QRO")
        canonical = replace(value, qro_id="").qro_id
        if value.qro_id != canonical:
            raise ValueError("Research Graph QRO identity is not canonical")
        return _OwnedResolvedValue(
            owner_user_id=_exact_text(value.owner),
            canonical_refs=(value.qro_id, f"qro:{value.qro_id}"),
            value=value,
        )

    return _owned_source(
        ref_type="research_graph_qro",
        roles=STAGE_REF_ROLES | COLLECTION_REF_ROLES,
        accepts_ref=lambda ref: bool(_QRO_REF.fullmatch(ref)),
        load_current=load,
    )


def _dataset_semantics_source(registry: Any) -> OwnerScopedRefSource:
    def load(ref: str, owner: str) -> _OwnedResolvedValue:
        value = _typed(
            registry.dataset(ref, owner_user_id=owner),
            DatasetSemanticsRecord,
            "DatasetSemantics",
        )
        return _OwnedResolvedValue(owner, (_exact_text(value.dataset_ref),), value)

    return _owned_source(
        ref_type="dataset_semantics",
        roles=frozenset({"data_semantics_ref"}) | _GENERAL_EVIDENCE_ROLES,
        accepts_ref=lambda ref: _canonical_prefixed_ref(ref, "dataset:"),
        load_current=load,
    )


def _factor_source(design: Any, factors: Any) -> OwnerScopedRefSource:
    def load(ref: str, owner: str) -> _OwnedResolvedValue:
        envelope = _typed(
            design.factor_envelope(ref, owner_user_id=owner),
            FactorOwnerEnvelope,
            "Factor owner envelope",
        )
        factor = _typed(
            factors.get(envelope.factor_id, envelope.version),
            Factor,
            "Factor",
        )
        expected_ref = f"factor:{factor.factor_id}:v{factor.version}"
        if (
            envelope.factor_ref != ref
            or expected_ref != ref
            or source_object_hash(factor) != envelope.source_content_hash
        ):
            raise ValueError("Factor owner envelope is stale or recombined")
        return _OwnedResolvedValue(envelope.owner_user_id, (envelope.factor_ref,), (envelope, factor))

    return _owned_source(
        ref_type="factor",
        roles=frozenset({"factor_ref"}) | _GENERAL_EVIDENCE_ROLES,
        accepts_ref=lambda ref: bool(_FACTOR_REF.fullmatch(ref)),
        load_current=load,
    )


def _model_version_source(models: Any) -> OwnerScopedRefSource:
    def load(ref: str, owner: str) -> _OwnedResolvedValue:
        match = _MODEL_VERSION_REF.fullmatch(ref)
        if match is None:
            raise ValueError("model version ref is not canonical")
        model_id = match.group("model")
        version = int(match.group("version"))
        matches = [
            value
            for value in models.list_versions(model_id, owner_user_id=owner)
            if isinstance(value, ModelVersion) and value.version == version
        ]
        if len(matches) != 1:
            raise LookupError("model version is missing or ambiguous")
        value = matches[0]
        canonical = f"model_version:{value.model_id}:v{value.version}"
        return _OwnedResolvedValue(value.owner_user_id, (canonical,), value)

    return _owned_source(
        ref_type="model_version",
        roles=frozenset({"model_ref"}) | _GENERAL_EVIDENCE_ROLES,
        accepts_ref=lambda ref: bool(_MODEL_VERSION_REF.fullmatch(ref)),
        load_current=load,
    )


def _hypothesis_source(design: Any, cards: Any) -> OwnerScopedRefSource:
    def load(ref: str, owner: str) -> _OwnedResolvedValue:
        envelope = _typed(
            design.hypothesis_envelope(ref, owner_user_id=owner),
            HypothesisOwnerEnvelope,
            "Hypothesis owner envelope",
        )
        card = _typed(cards.get(envelope.card_id), HypothesisCard, "HypothesisCard")
        if (
            envelope.hypothesis_card_ref != ref
            or f"hypothesis_card:{card.card_id}" != ref
            or source_object_hash(card) != envelope.source_content_hash
        ):
            raise ValueError("HypothesisCard owner envelope is stale or recombined")
        return _OwnedResolvedValue(
            envelope.owner_user_id,
            (envelope.hypothesis_card_ref,),
            (envelope, card),
        )

    return _owned_source(
        ref_type="hypothesis_card",
        roles=_GENERAL_EVIDENCE_ROLES,
        accepts_ref=lambda ref: _canonical_prefixed_ref(ref, "hypothesis_card:"),
        load_current=load,
    )


def _signal_contract_source(design: Any, signals: Any) -> OwnerScopedRefSource:
    def load(ref: str, owner: str) -> _OwnedResolvedValue:
        envelope = _typed(
            design.signal_contract_envelope(ref, owner_user_id=owner),
            SignalContractOwnerEnvelope,
            "SignalContract owner envelope",
        )
        contract = _typed(
            signals.get(envelope.signal_id), SignalContract, "SignalContract"
        )
        if (
            envelope.signal_contract_ref != ref
            or contract.signal_id != envelope.signal_id
            or source_object_hash(contract) != envelope.source_content_hash
        ):
            raise ValueError("SignalContract owner envelope is stale or recombined")
        return _OwnedResolvedValue(
            envelope.owner_user_id,
            (envelope.signal_contract_ref,),
            (envelope, contract),
        )

    return _owned_source(
        ref_type="signal_contract",
        roles=frozenset({"signal_contract_ref"}) | _GENERAL_EVIDENCE_ROLES,
        accepts_ref=lambda ref: bool(_SIGNAL_REF.fullmatch(ref)),
        load_current=load,
    )


def _design_record_source(
    *,
    ref_type: str,
    roles: frozenset[str],
    prefix: str,
    getter: Callable[[str, str], Any],
    expected_type: type[Any],
    ref_field: str,
) -> OwnerScopedRefSource:
    def load(ref: str, owner: str) -> _OwnedResolvedValue:
        value = _typed(getter(ref, owner), expected_type, ref_type)
        canonical = _exact_text(getattr(value, ref_field, ""))
        return _OwnedResolvedValue(
            _exact_text(getattr(value, "owner_user_id", "")),
            (canonical,),
            value,
        )

    return _owned_source(
        ref_type=ref_type,
        roles=roles,
        accepts_ref=lambda ref: _canonical_prefixed_ref(ref, prefix),
        load_current=load,
    )


def _research_design_sources(registry: Any) -> tuple[OwnerScopedRefSource, ...]:
    evidence = _GENERAL_EVIDENCE_ROLES
    return (
        _design_record_source(
            ref_type="strategy_book",
            roles=frozenset({"strategy_book_ref"}) | evidence,
            prefix="strategy_book:",
            getter=lambda ref, owner: registry.strategy_book(ref, owner_user_id=owner),
            expected_type=StrategyBookRecord,
            ref_field="strategy_book_ref",
        ),
        _design_record_source(
            ref_type="portfolio_policy",
            roles=frozenset({"portfolio_policy_ref"}) | evidence,
            prefix="portfolio_policy:",
            getter=lambda ref, owner: registry.portfolio_policy(ref, owner_user_id=owner),
            expected_type=PortfolioPolicyRecord,
            ref_field="portfolio_policy_ref",
        ),
        _design_record_source(
            ref_type="universe_definition",
            roles=evidence,
            prefix="universe:",
            getter=lambda ref, owner: registry.universe_definition(ref, owner_user_id=owner),
            expected_type=UniverseDefinitionRecord,
            ref_field="universe_definition_ref",
        ),
        _design_record_source(
            ref_type="regime_scenario",
            roles=evidence,
            prefix="regime:",
            getter=lambda ref, owner: registry.regime_scenario(ref, owner_user_id=owner),
            expected_type=RegimeScenarioRecord,
            ref_field="regime_scenario_ref",
        ),
        _design_record_source(
            ref_type="label_definition",
            roles=evidence,
            prefix="label:",
            getter=lambda ref, owner: registry.label_definition(ref, owner_user_id=owner),
            expected_type=LabelDefinitionRecord,
            ref_field="label_ref",
        ),
    )


def _backtest_evidence_sources(registry: Any) -> tuple[OwnerScopedRefSource, ...]:
    def load_attribution(ref: str, owner: str) -> _OwnedResolvedValue:
        value = _typed(
            registry.attribution(ref, owner_user_id=owner),
            BacktestAttributionRecord,
            "BacktestAttribution",
        )
        decision = registry.validate_current_attribution(ref, owner_user_id=owner)
        return _OwnedResolvedValue(
            value.owner_user_id,
            (value.attribution_ref,),
            value,
            current=bool(getattr(decision, "accepted", False)),
        )

    def load_monitor(ref: str, owner: str) -> _OwnedResolvedValue:
        value = _typed(
            registry.monitor(ref, owner_user_id=owner),
            BacktestMonitorRecord,
            "BacktestMonitor",
        )
        decision = registry.validate_current_monitor(ref, owner_user_id=owner)
        return _OwnedResolvedValue(
            value.owner_user_id,
            (value.monitor_ref,),
            value,
            current=bool(getattr(decision, "accepted", False)),
        )

    return (
        _owned_source(
            ref_type="backtest_attribution",
            roles=frozenset({"attribution_ref"}) | _GENERAL_EVIDENCE_ROLES,
            accepts_ref=lambda ref: _canonical_prefixed_ref(ref, "attribution:"),
            load_current=load_attribution,
        ),
        _owned_source(
            ref_type="backtest_monitor",
            roles=frozenset({"monitor_ref"}) | _GENERAL_EVIDENCE_ROLES,
            accepts_ref=lambda ref: _canonical_prefixed_ref(ref, "monitor:"),
            load_current=load_monitor,
        ),
    )


def _methodology_sources(
    methodology_registry: Any | None,
    depth_registry: Any | None,
) -> tuple[OwnerScopedRefSource, ...]:
    sources: list[OwnerScopedRefSource] = []
    roles = _GENERAL_EVIDENCE_ROLES | _EXECUTED_EVIDENCE_ROLES
    if methodology_registry is not None:
        def load_methodology(ref: str, owner: str) -> _OwnedResolvedValue:
            value = _typed(
                methodology_registry.methodology(ref, owner_user_id=owner),
                ValidationMethodologyRecord,
                "ValidationMethodology",
            )
            return _OwnedResolvedValue(owner, (_exact_text(value.validation_ref),), value)

        sources.append(
            _owned_source(
                ref_type="validation_methodology",
                roles=roles,
                accepts_ref=lambda ref: _canonical_prefixed_ref(
                    ref, "validation_methodology:"
                ),
                load_current=load_methodology,
            )
        )
    if depth_registry is not None:
        def load_depth(ref: str, owner: str) -> _OwnedResolvedValue:
            value = _typed(
                depth_registry.depth(ref, owner_user_id=owner),
                ValidationDepthRecord,
                "ValidationDepth",
            )
            return _OwnedResolvedValue(owner, (_exact_text(value.depth_ref),), value)

        sources.append(
            _owned_source(
                ref_type="validation_depth",
                roles=roles,
                accepts_ref=lambda ref: _canonical_prefixed_ref(
                    ref, "validation_depth:"
                ),
                load_current=load_depth,
            )
        )
    return tuple(sources)


def _signal_validation_source(registry: Any) -> OwnerScopedRefSource:
    def load(ref: str, owner: str) -> _OwnedResolvedValue:
        value = _typed(
            registry.validation(ref, owner_user_id=owner),
            SignalPerformanceValidationRecord,
            "SignalPerformanceValidation",
        )
        if value.validation_id != value.canonical_validation_id:
            raise ValueError("signal validation identity is not canonical")
        return _OwnedResolvedValue(value.recorded_by, (value.validation_id,), value)

    return _owned_source(
        ref_type="signal_validation",
        roles=_GENERAL_EVIDENCE_ROLES | _EXECUTED_EVIDENCE_ROLES,
        accepts_ref=lambda ref: _canonical_prefixed_ref(ref, "signal_validation_"),
        load_current=load,
    )


def _market_validation_sources(registry: Any) -> tuple[OwnerScopedRefSource, ...]:
    def load_use_validation(ref: str, owner: str) -> _OwnedResolvedValue:
        value = _typed(
            registry.use_validation(ref, owner_user_id=owner),
            MarketDataUseValidationRecord,
            "MarketDataUseValidation",
        )
        return _OwnedResolvedValue(value.recorded_by, (value.validation_ref,), value)

    def load_instrument(ref: str, owner: str) -> _OwnedResolvedValue:
        value = _typed(
            registry.instrument(ref, owner_user_id=owner),
            InstrumentSpec,
            "InstrumentSpec",
        )
        return _OwnedResolvedValue(owner, (_exact_text(value.instrument_ref),), value)

    return (
        _owned_source(
            ref_type="market_data_use_validation",
            roles=_GENERAL_EVIDENCE_ROLES | _EXECUTED_EVIDENCE_ROLES,
            accepts_ref=lambda ref: _canonical_prefixed_ref(ref, "market_data_use:"),
            load_current=load_use_validation,
        ),
        _owned_source(
            ref_type="instrument_spec",
            roles=_GENERAL_EVIDENCE_ROLES,
            accepts_ref=lambda ref: _canonical_prefixed_ref(ref, "instrument:"),
            load_current=load_instrument,
        ),
    )


def _model_governance_sources(registry: Any) -> tuple[OwnerScopedRefSource, ...]:
    def load_passport(ref: str, owner: str) -> _OwnedResolvedValue:
        value = _typed(
            registry.passport(ref, owner_user_id=owner),
            ModelGovernancePassport,
            "ModelGovernancePassport",
        )
        return _OwnedResolvedValue(value.owner_user_id, (value.passport_id,), value)

    def load_profile(ref: str, owner: str) -> _OwnedResolvedValue:
        value = _typed(
            registry.monitoring_profile(ref, owner_user_id=owner),
            ModelMonitoringProfile,
            "ModelMonitoringProfile",
        )
        return _OwnedResolvedValue(
            value.owner_user_id,
            (value.monitoring_profile_id,),
            value,
        )

    return (
        _owned_source(
            ref_type="model_passport",
            roles=_GENERAL_EVIDENCE_ROLES,
            accepts_ref=lambda ref: _canonical_prefixed_ref(ref, "model_passport_"),
            load_current=load_passport,
        ),
        _owned_source(
            ref_type="model_monitoring_profile",
            roles=frozenset({"monitor_ref"}) | _GENERAL_EVIDENCE_ROLES,
            accepts_ref=lambda ref: _canonical_prefixed_ref(
                ref, "model_monitoring_profile_"
            ),
            load_current=load_profile,
        ),
    )


class StrictSpineExternalRefResolver:
    """Fail-closed adapter for ``SpineLedger.validate_chain_backing``.

    Dependencies are store objects only; construction and calls do not mutate
    them.  Missing dependencies simply remove their ref types from the active
    support map, so those refs resolve ``False`` instead of falling back to a
    lexical prefix check.
    """

    def __init__(
        self,
        *,
        project_root: str | Path,
        verifier_refs: Iterable[str] = (),
        research_graph_store: Any | None = None,
        market_data_registry: Any | None = None,
        research_design_registry: Any | None = None,
        factor_registry: Any | None = None,
        model_registry: Any | None = None,
        signal_contract_registry: Any | None = None,
        hypothesis_store: Any | None = None,
        backtest_evidence_registry: Any | None = None,
        validation_methodology_registry: Any | None = None,
        validation_depth_registry: Any | None = None,
        signal_validation_registry: Any | None = None,
        model_governance_registry: Any | None = None,
        extra_sources: Iterable[OwnerScopedRefSource] = (),
    ) -> None:
        root = Path(project_root)
        if not root.is_absolute():
            raise ValueError("project_root must be absolute")
        self._project_root = root.resolve(strict=True)
        if not self._project_root.is_dir():
            raise ValueError("project_root must be a directory")
        self._verifier_refs = frozenset(_exact_text(ref) for ref in verifier_refs)

        sources: list[OwnerScopedRefSource] = []
        if research_graph_store is not None:
            sources.append(_qro_source(research_graph_store))
        if market_data_registry is not None:
            sources.append(_dataset_semantics_source(market_data_registry))
            sources.extend(_market_validation_sources(market_data_registry))
        if research_design_registry is not None:
            sources.extend(_research_design_sources(research_design_registry))
        if research_design_registry is not None and factor_registry is not None:
            sources.append(_factor_source(research_design_registry, factor_registry))
        if research_design_registry is not None and signal_contract_registry is not None:
            sources.append(
                _signal_contract_source(
                    research_design_registry, signal_contract_registry
                )
            )
        if research_design_registry is not None and hypothesis_store is not None:
            sources.append(
                _hypothesis_source(research_design_registry, hypothesis_store)
            )
        if model_registry is not None:
            sources.append(_model_version_source(model_registry))
        if backtest_evidence_registry is not None:
            sources.extend(_backtest_evidence_sources(backtest_evidence_registry))
        sources.extend(
            _methodology_sources(
                validation_methodology_registry,
                validation_depth_registry,
            )
        )
        if signal_validation_registry is not None:
            sources.append(_signal_validation_source(signal_validation_registry))
        if model_governance_registry is not None:
            sources.extend(_model_governance_sources(model_governance_registry))
        for source in extra_sources:
            if not isinstance(source, OwnerScopedRefSource):
                raise TypeError("extra_sources must contain OwnerScopedRefSource values")
            sources.append(source)

        names = [source.ref_type for source in sources]
        if len(names) != len(set(names)):
            raise ValueError("external-ref source ref_type names must be unique")
        self._sources = tuple(sources)
        support: dict[str, tuple[str, ...]] = {}
        for role in sorted(SUPPORTED_ROLES):
            active = sorted(
                source.ref_type for source in self._sources if role in source.roles
            )
            if role in _PATH_ROLES:
                active.append("repository_path")
            if role == VERIFIER_REF_ROLE and self._verifier_refs:
                active.append("registered_verifier")
            support[role] = tuple(active)
        self._supported_ref_types_by_role = MappingProxyType(support)

    @property
    def supported_ref_types_by_role(self) -> Mapping[str, tuple[str, ...]]:
        """Exact active role-to-ref-type map for audit and composition tests."""

        return self._supported_ref_types_by_role

    @staticmethod
    def _source_resolves(
        source: OwnerScopedRefSource,
        *,
        ref: str,
        owner: str,
    ) -> bool:
        try:
            first = source.load_current(ref, owner)
            first_refs = tuple(_exact_text(value) for value in source.canonical_refs(first))
            first_owner = _exact_text(source.owner_user_id(first))
            if (
                first_owner != owner
                or len(first_refs) != len(set(first_refs))
                or ref not in first_refs
                or not source.is_current(first, ref, owner)
            ):
                return False
            first_snapshot = _snapshot(first)

            second = source.load_current(ref, owner)
            second_refs = tuple(_exact_text(value) for value in source.canonical_refs(second))
            second_owner = _exact_text(source.owner_user_id(second))
            if (
                second_owner != owner
                or second_refs != first_refs
                or ref not in second_refs
                or not source.is_current(second, ref, owner)
            ):
                return False
            return _snapshot(second) == first_snapshot
        except Exception:  # noqa: BLE001 - any store corruption/race must fail closed.
            return False

    def _canonical_repo_path(self, ref: str) -> Path | None:
        raw_path = ref
        selector = ""
        selector_kind = ""
        if "::" in ref:
            raw_path, selector = ref.split("::", 1)
            selector_kind = "pytest"
            if not selector or not _PYTEST_NODE.fullmatch(selector):
                return None
        elif ":" in ref:
            raw_path, selector = ref.rsplit(":", 1)
            selector_kind = "symbol"
            if not selector or not _SYMBOL_OR_LINE.fullmatch(selector):
                return None
        if not raw_path or not _REPO_PATH.fullmatch(raw_path):
            return None
        pure = PurePosixPath(raw_path)
        if (
            pure.is_absolute()
            or pure.as_posix() != raw_path
            or any(part in {"", ".", ".."} or part.startswith(".") for part in pure.parts)
            or Path(raw_path).suffix.lower() not in _REPO_SUFFIXES
        ):
            return None
        if selector_kind == "pytest" and Path(raw_path).suffix.lower() != ".py":
            return None
        unresolved = self._project_root.joinpath(*pure.parts)
        if unresolved.is_symlink():
            return None
        try:
            resolved = unresolved.resolve(strict=True)
            resolved.relative_to(self._project_root)
        except (OSError, RuntimeError, ValueError):
            return None
        return resolved if resolved.is_file() else None

    def __call__(self, role: str, ref: str, owner: str) -> bool:
        try:
            role_text = _exact_text(role)
            ref_text = _exact_text(ref)
            owner_text = _exact_text(owner)
        except (TypeError, ValueError):
            return False
        if role_text not in SUPPORTED_ROLES or _PLACEHOLDER_COMPONENT.search(ref_text):
            return False
        if role_text == VERIFIER_REF_ROLE:
            return ref_text in self._verifier_refs

        candidates: list[OwnerScopedRefSource] = []
        for source in self._sources:
            if role_text not in source.roles:
                continue
            try:
                if source.accepts_ref(ref_text):
                    candidates.append(source)
            except Exception:  # noqa: BLE001 - routing callback failures fail closed.
                return False
        repo_path = self._canonical_repo_path(ref_text) if role_text in _PATH_ROLES else None
        candidate_count = len(candidates) + int(repo_path is not None)
        if candidate_count != 1:
            return False
        if repo_path is not None:
            return True
        return self._source_resolves(candidates[0], ref=ref_text, owner=owner_text)


__all__ = [
    "COLLECTION_REF_ROLES",
    "OwnerScopedRefSource",
    "STAGE_REF_ROLES",
    "SUPPORTED_ROLES",
    "StrictSpineExternalRefResolver",
    "VERIFIER_REF_ROLE",
]
