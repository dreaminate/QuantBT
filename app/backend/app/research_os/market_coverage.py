"""Durable owner-scoped current coverage proof for GOAL section 11.

The existing market-data registry is the canonical store for datasets,
instruments, capability matrices, and use validations.  This module adds the
records that were previously request-only (capital and transformations), exact
per-instrument semantic bindings, and a current receipt that is valid only
while every dependency re-resolves to the same owner and state.

No record is synthesized from a reference token.  Callers must persist every
capital, transformation, and instrument-semantics revision before asking for a
current coverage receipt.
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
import threading
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterator

from ..cross_process_lock import acquire_exclusive_fd
from ..lineage.ids import content_hash
from .goal_coverage import strict_current_entrypoint_coverage
from .goal_semantics import (
    GoalSectionSemanticProofRecord,
    GoalSemanticDecision,
    GoalSemanticViolation,
)
from .market_data_contract import (
    CrossCurrencyCapitalRecord,
    DataTransformationClaim,
    DatasetSemanticsRecord,
    InstrumentSpec,
    MarketCapabilityMatrixRecord,
    MarketDataUseValidationRecord,
    PersistentMarketDataRegistry,
    validate_data_transformation_claim,
    validate_dataset_semantics,
    validate_instrument_spec,
    validate_market_capability_matrix,
    validate_market_data_use_validation_record,
)
from .ref_resolution import is_placeholder_ref


MARKET_COVERAGE_SCHEMA_VERSION = 2
MARKET_COVERAGE_RECEIPT_VERSION = "market_coverage_receipt.v1"
MARKET_COVERAGE_ENTRYPOINT_REF = "api:goal.market_coverage.current"

REQUIRED_MARKET_FAMILIES = frozenset({"option", "future", "bond", "fx", "commodity"})
REQUIRED_MARKET_USE_CONTEXTS = frozenset(
    {"research", "backtest", "confirmatory_validation", "paper", "testnet"}
)
MARKET_FAMILY_REQUIRED_FIELDS: dict[str, frozenset[str]] = {
    "option": frozenset(
        {
            "greeks_ref",
            "implied_volatility_surface_ref",
            "term_structure_ref",
            "exercise_style_ref",
            "expiry_ref",
            "strike_ref",
            "contract_multiplier_ref",
            "settlement_ref",
            "assignment_ref",
            "margin_ref",
            "volatility_strategy_payoff_ref",
        }
    ),
    "future": frozenset(
        {
            "roll_rule_ref",
            "margin_ref",
            "settlement_ref",
            "contract_multiplier_ref",
            "delivery_ref",
            "continuous_contract_construction_ref",
        }
    ),
    "bond": frozenset(
        {
            "duration_ref",
            "convexity_ref",
            "yield_curve_ref",
            "accrued_interest_ref",
            "coupon_ref",
            "maturity_ref",
            "day_count_ref",
        }
    ),
    "fx": frozenset(
        {
            "base_currency_ref",
            "quote_currency_ref",
            "rollover_ref",
            "funding_ref",
            "holiday_calendar_ref",
            "conversion_rate_ref",
        }
    ),
    "commodity": frozenset(
        {
            "storage_ref",
            "delivery_ref",
            "contract_spec_ref",
            "seasonality_ref",
            "calendar_spread_ref",
        }
    ),
}

_CURRENT_STATUSES = frozenset({"current", "fresh"})
_ACCEPTED_QUALITY_STATUSES = frozenset({"accepted", "current", "pass", "passed", "valid"})
_CAPITAL_FIELDS = (
    "base_currency",
    "fx_conversion_ref",
    "collateral_ref",
    "margin_ref",
    "leverage_ref",
    "net_exposure_ref",
    "gross_exposure_ref",
    "capital_allocation_ref",
    "financing_cost_ref",
)
_DATASET_SEMANTIC_FIELDS = (
    "sampling_rule_ref",
    "adjustment_formula_ref",
    "asof_join_rule_ref",
    "missingness_model_ref",
    "survivorship_rule_ref",
)


def _text(value: Any) -> str:
    return str(value or "").strip()


def _refs(value: Any) -> tuple[str, ...]:
    if value is None:
        return ()
    values = value if isinstance(value, (tuple, list)) else (value,)
    return tuple(item for raw in values if (item := _text(raw)))


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _sha256(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _enum_text(value: Any) -> str:
    return _text(getattr(value, "value", value))


def _state_hash(value: Any) -> str:
    if hasattr(value, "to_dict"):
        value = value.to_dict()
    elif hasattr(value, "model_dump"):
        value = value.model_dump(mode="json")
    else:
        value = asdict(value)
    return "sha256:" + _sha256(value)


def _real_ref(value: Any, *, field: str) -> str:
    ref = _text(value)
    if not ref:
        raise ValueError(f"{field} is required")
    if is_placeholder_ref(ref):
        raise ValueError(f"{field} cannot be synthetic, fixture, placeholder, or goal-closure material")
    return ref


def _owner(value: Any) -> str:
    owner = _text(value)
    if not owner or owner != value or any(ord(char) < 32 for char in owner):
        raise ValueError("owner_user_id must be a stable non-empty exact string")
    return owner


def _exact_unique(values: tuple[str, ...], *, field: str) -> tuple[str, ...]:
    normalized = _refs(values)
    if not normalized or len(normalized) != len(set(normalized)):
        raise ValueError(f"{field} must be a non-empty exact unique ref set")
    for ref in normalized:
        _real_ref(ref, field=field)
    return normalized


@dataclass(frozen=True)
class MarketCoverageViolation:
    code: str
    message: str
    field: str = ""
    ref: str = ""


@dataclass(frozen=True)
class MarketCoverageDecision:
    accepted: bool
    violations: tuple[MarketCoverageViolation, ...]


class MarketCoverageError(ValueError):
    """Current market coverage could not be proved from durable records."""


class MarketCoverageCommitUncertain(MarketCoverageError):
    """The row is visible after replace, but directory durability was not confirmed."""


@dataclass(frozen=True)
class MarketCapitalStateRecord:
    capital_ref: str
    revision: str
    known_at: str
    effective_at: str
    freshness_status: str
    capital: CrossCurrencyCapitalRecord

    def __post_init__(self) -> None:
        for name in ("capital_ref", "revision", "known_at", "effective_at", "freshness_status"):
            object.__setattr__(self, name, _text(getattr(self, name)))
        object.__setattr__(self, "freshness_status", self.freshness_status.lower())


@dataclass(frozen=True)
class MarketTransformationStateRecord:
    transform_ref: str
    revision: str
    known_at: str
    effective_at: str
    freshness_status: str
    claim: DataTransformationClaim

    def __post_init__(self) -> None:
        for name in ("transform_ref", "revision", "known_at", "effective_at", "freshness_status"):
            object.__setattr__(self, name, _text(getattr(self, name)))
        object.__setattr__(self, "freshness_status", self.freshness_status.lower())


@dataclass(frozen=True)
class MarketInstrumentSemanticsRecord:
    semantics_ref: str
    revision: str
    known_at: str
    effective_at: str
    freshness_status: str
    instrument_ref: str
    market_family: str
    semantic_fields: tuple[tuple[str, str], ...]

    def __post_init__(self) -> None:
        for name in (
            "semantics_ref",
            "revision",
            "known_at",
            "effective_at",
            "freshness_status",
            "instrument_ref",
            "market_family",
        ):
            object.__setattr__(self, name, _text(getattr(self, name)))
        object.__setattr__(self, "freshness_status", self.freshness_status.lower())
        object.__setattr__(self, "market_family", self.market_family.lower())
        normalized = tuple(sorted((_text(name), _text(ref)) for name, ref in self.semantic_fields))
        object.__setattr__(self, "semantic_fields", normalized)

    @property
    def field_map(self) -> dict[str, str]:
        return dict(self.semantic_fields)


@dataclass(frozen=True)
class MarketCoverageComponentState:
    component_kind: str
    component_ref: str
    revision: str
    state_hash: str

    def __post_init__(self) -> None:
        for name in ("component_kind", "component_ref", "revision", "state_hash"):
            object.__setattr__(self, name, _text(getattr(self, name)))


@dataclass(frozen=True)
class MarketCoverageSnapshot:
    owner_user_id: str
    market_families: tuple[str, ...]
    use_contexts: tuple[str, ...]
    components: tuple[MarketCoverageComponentState, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "owner_user_id", _text(self.owner_user_id))
        object.__setattr__(self, "market_families", tuple(sorted(_refs(self.market_families))))
        object.__setattr__(self, "use_contexts", tuple(sorted(_refs(self.use_contexts))))
        object.__setattr__(
            self,
            "components",
            tuple(sorted(self.components, key=lambda item: (item.component_kind, item.component_ref))),
        )


@dataclass(frozen=True)
class MarketCoverageReceipt:
    receipt_ref: str
    owner_user_id: str
    use_validation_refs: tuple[str, ...]
    capital_record_ref: str
    transformation_refs: tuple[str, ...]
    instrument_semantics_refs: tuple[str, ...]
    snapshot: MarketCoverageSnapshot
    receipt_version: str = MARKET_COVERAGE_RECEIPT_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(self, "receipt_ref", _text(self.receipt_ref))
        object.__setattr__(self, "owner_user_id", _text(self.owner_user_id))
        object.__setattr__(self, "capital_record_ref", _text(self.capital_record_ref))
        object.__setattr__(self, "receipt_version", _text(self.receipt_version))
        for name in ("use_validation_refs", "transformation_refs", "instrument_semantics_refs"):
            object.__setattr__(self, name, tuple(sorted(_refs(getattr(self, name)))))

    @property
    def canonical_receipt_ref(self) -> str:
        return market_coverage_receipt_identity(
            owner_user_id=self.owner_user_id,
            use_validation_refs=self.use_validation_refs,
            capital_record_ref=self.capital_record_ref,
            transformation_refs=self.transformation_refs,
            instrument_semantics_refs=self.instrument_semantics_refs,
            snapshot=self.snapshot,
            receipt_version=self.receipt_version,
        )


@dataclass(frozen=True)
class MarketCoverageSemanticMaterial:
    subject_ref: str
    producer_refs: tuple[str, ...]
    store_refs: tuple[str, ...]
    consumer_refs: tuple[str, ...]
    gate_verdict_refs: tuple[str, ...]
    test_refs: tuple[str, ...]


@dataclass(frozen=True)
class _MarketRegistrySnapshot:
    datasets: dict[str, DatasetSemanticsRecord]
    instruments: dict[str, InstrumentSpec]
    capability_matrices: dict[str, MarketCapabilityMatrixRecord]
    use_validations: dict[str, MarketDataUseValidationRecord]


def market_coverage_receipt_identity(
    *,
    owner_user_id: str,
    use_validation_refs: tuple[str, ...],
    capital_record_ref: str,
    transformation_refs: tuple[str, ...],
    instrument_semantics_refs: tuple[str, ...],
    snapshot: MarketCoverageSnapshot,
    receipt_version: str = MARKET_COVERAGE_RECEIPT_VERSION,
) -> str:
    return "market_coverage_receipt:" + content_hash(
        {
            "owner_user_id": _text(owner_user_id),
            "use_validation_refs": tuple(sorted(_refs(use_validation_refs))),
            "capital_record_ref": _text(capital_record_ref),
            "transformation_refs": tuple(sorted(_refs(transformation_refs))),
            "instrument_semantics_refs": tuple(sorted(_refs(instrument_semantics_refs))),
            "snapshot": asdict(snapshot),
            "receipt_version": _text(receipt_version),
        }
    )


def _capital_from_dict(value: Any) -> CrossCurrencyCapitalRecord:
    if not isinstance(value, dict) or set(value) != set(_CAPITAL_FIELDS):
        raise ValueError("market capital payload has an inexact field set")
    return CrossCurrencyCapitalRecord(**value)


def market_capital_state_record_from_dict(value: Any) -> MarketCapitalStateRecord:
    expected = {"capital_ref", "revision", "known_at", "effective_at", "freshness_status", "capital"}
    if not isinstance(value, dict) or set(value) != expected:
        raise ValueError("market capital state has an inexact field set")
    return MarketCapitalStateRecord(
        capital_ref=value["capital_ref"],
        revision=value["revision"],
        known_at=value["known_at"],
        effective_at=value["effective_at"],
        freshness_status=value["freshness_status"],
        capital=_capital_from_dict(value["capital"]),
    )


def market_transformation_state_record_from_dict(value: Any) -> MarketTransformationStateRecord:
    expected = {"transform_ref", "revision", "known_at", "effective_at", "freshness_status", "claim"}
    if not isinstance(value, dict) or set(value) != expected or not isinstance(value["claim"], dict):
        raise ValueError("market transformation state has an inexact field set")
    claim_data = value["claim"]
    if set(claim_data) != {
        "transform_ref",
        "claims_theory_correct",
        "formula_ref",
        "unit_binding_ref",
        "timing_binding_ref",
    }:
        raise ValueError("market transformation claim has an inexact field set")
    return MarketTransformationStateRecord(
        transform_ref=value["transform_ref"],
        revision=value["revision"],
        known_at=value["known_at"],
        effective_at=value["effective_at"],
        freshness_status=value["freshness_status"],
        claim=DataTransformationClaim(**claim_data),
    )


def market_instrument_semantics_record_from_dict(value: Any) -> MarketInstrumentSemanticsRecord:
    expected = {
        "semantics_ref",
        "revision",
        "known_at",
        "effective_at",
        "freshness_status",
        "instrument_ref",
        "market_family",
        "semantic_fields",
    }
    if not isinstance(value, dict) or set(value) != expected:
        raise ValueError("market instrument semantics has an inexact field set")
    fields = value["semantic_fields"]
    if not isinstance(fields, (list, tuple)):
        raise ValueError("semantic_fields must be an exact pair sequence")
    return MarketInstrumentSemanticsRecord(
        semantics_ref=value["semantics_ref"],
        revision=value["revision"],
        known_at=value["known_at"],
        effective_at=value["effective_at"],
        freshness_status=value["freshness_status"],
        instrument_ref=value["instrument_ref"],
        market_family=value["market_family"],
        semantic_fields=tuple((item[0], item[1]) for item in fields),
    )


def _component_from_dict(value: Any) -> MarketCoverageComponentState:
    if not isinstance(value, dict) or set(value) != {
        "component_kind",
        "component_ref",
        "revision",
        "state_hash",
    }:
        raise ValueError("market coverage component has an inexact field set")
    return MarketCoverageComponentState(**value)


def market_coverage_snapshot_from_dict(value: Any) -> MarketCoverageSnapshot:
    if not isinstance(value, dict) or set(value) != {
        "owner_user_id",
        "market_families",
        "use_contexts",
        "components",
    }:
        raise ValueError("market coverage snapshot has an inexact field set")
    return MarketCoverageSnapshot(
        owner_user_id=value["owner_user_id"],
        market_families=tuple(value["market_families"]),
        use_contexts=tuple(value["use_contexts"]),
        components=tuple(_component_from_dict(item) for item in value["components"]),
    )


def market_coverage_receipt_from_dict(value: Any) -> MarketCoverageReceipt:
    expected = {
        "receipt_ref",
        "owner_user_id",
        "use_validation_refs",
        "capital_record_ref",
        "transformation_refs",
        "instrument_semantics_refs",
        "snapshot",
        "receipt_version",
    }
    if not isinstance(value, dict) or set(value) != expected:
        raise ValueError("market coverage receipt has an inexact field set")
    return MarketCoverageReceipt(
        receipt_ref=value["receipt_ref"],
        owner_user_id=value["owner_user_id"],
        use_validation_refs=tuple(value["use_validation_refs"]),
        capital_record_ref=value["capital_record_ref"],
        transformation_refs=tuple(value["transformation_refs"]),
        instrument_semantics_refs=tuple(value["instrument_semantics_refs"]),
        snapshot=market_coverage_snapshot_from_dict(value["snapshot"]),
        receipt_version=value["receipt_version"],
    )


def validate_market_capital_state(record: MarketCapitalStateRecord) -> MarketCoverageDecision:
    violations: list[MarketCoverageViolation] = []
    for name in ("capital_ref", "revision", "known_at", "effective_at"):
        value = _text(getattr(record, name))
        if not value or (name == "capital_ref" and is_placeholder_ref(value)):
            violations.append(
                MarketCoverageViolation(
                    "market_capital_required_field_missing",
                    "capital state requires real identity, revision, known_at, and effective_at",
                    field=name,
                    ref=record.capital_ref,
                )
            )
    if record.freshness_status not in _CURRENT_STATUSES:
        violations.append(
            MarketCoverageViolation(
                "market_capital_not_current",
                "capital state freshness must be current or fresh",
                field="freshness_status",
                ref=record.capital_ref,
            )
        )
    for name in _CAPITAL_FIELDS:
        if not _text(getattr(record.capital, name)):
            violations.append(
                MarketCoverageViolation(
                    "market_capital_semantics_incomplete",
                    "cross-market capital requires currency, FX, collateral, margin, leverage, exposure, allocation, and financing refs",
                    field=name,
                    ref=record.capital_ref,
                )
            )
        elif name != "base_currency" and is_placeholder_ref(_text(getattr(record.capital, name))):
            violations.append(
                MarketCoverageViolation(
                    "market_capital_placeholder_ref",
                    "capital semantic refs must be durable real records",
                    field=name,
                    ref=_text(getattr(record.capital, name)),
                )
            )
    return MarketCoverageDecision(not violations, tuple(violations))


def validate_market_transformation_state(
    record: MarketTransformationStateRecord,
) -> MarketCoverageDecision:
    violations: list[MarketCoverageViolation] = []
    if record.transform_ref != _text(record.claim.transform_ref):
        violations.append(
            MarketCoverageViolation(
                "market_transformation_identity_mismatch",
                "durable transform identity must equal claim.transform_ref",
                field="transform_ref",
                ref=record.transform_ref,
            )
        )
    for name in ("transform_ref", "revision", "known_at", "effective_at"):
        if not _text(getattr(record, name)):
            violations.append(
                MarketCoverageViolation(
                    "market_transformation_required_field_missing",
                    "transformation state requires identity, revision, known_at, and effective_at",
                    field=name,
                    ref=record.transform_ref,
                )
            )
    if is_placeholder_ref(record.transform_ref):
        violations.append(
            MarketCoverageViolation(
                "market_transformation_placeholder_ref",
                "transformation identity must be a durable real ref",
                field="transform_ref",
                ref=record.transform_ref,
            )
        )
    if record.freshness_status not in _CURRENT_STATUSES:
        violations.append(
            MarketCoverageViolation(
                "market_transformation_not_current",
                "transformation freshness must be current or fresh",
                field="freshness_status",
                ref=record.transform_ref,
            )
        )
    decision = validate_data_transformation_claim(record.claim)
    if not record.claim.claims_theory_correct or not decision.accepted:
        violations.append(
            MarketCoverageViolation(
                "market_transformation_binding_incomplete",
                "section 11 transformations require theory-correct formula, unit, and timing bindings",
                field="claim",
                ref=record.transform_ref,
            )
        )
    for name in ("formula_ref", "unit_binding_ref", "timing_binding_ref"):
        value = _text(getattr(record.claim, name))
        if not value or is_placeholder_ref(value):
            violations.append(
                MarketCoverageViolation(
                    "market_transformation_binding_not_real",
                    "formula, unit, and timing bindings must be durable real refs",
                    field=name,
                    ref=value or record.transform_ref,
                )
            )
    return MarketCoverageDecision(not violations, tuple(violations))


def validate_market_instrument_semantics(
    record: MarketInstrumentSemanticsRecord,
) -> MarketCoverageDecision:
    violations: list[MarketCoverageViolation] = []
    for name in ("semantics_ref", "revision", "known_at", "effective_at", "instrument_ref"):
        value = _text(getattr(record, name))
        if not value or (name.endswith("_ref") and is_placeholder_ref(value)):
            violations.append(
                MarketCoverageViolation(
                    "market_instrument_semantics_required_field_missing",
                    "instrument semantics require real identity, revision, timing, and instrument refs",
                    field=name,
                    ref=record.semantics_ref,
                )
            )
    if record.freshness_status not in _CURRENT_STATUSES:
        violations.append(
            MarketCoverageViolation(
                "market_instrument_semantics_not_current",
                "instrument semantics freshness must be current or fresh",
                field="freshness_status",
                ref=record.semantics_ref,
            )
        )
    required = MARKET_FAMILY_REQUIRED_FIELDS.get(record.market_family)
    if required is None:
        violations.append(
            MarketCoverageViolation(
                "market_instrument_family_unknown",
                "instrument semantic family must be option, future, bond, fx, or commodity",
                field="market_family",
                ref=record.market_family,
            )
        )
        required = frozenset()
    field_map = record.field_map
    if len(record.semantic_fields) != len(field_map) or frozenset(field_map) != required:
        violations.append(
            MarketCoverageViolation(
                "market_instrument_semantics_inexact",
                "instrument semantic fields must exactly match the GOAL section 11 family contract",
                field="semantic_fields",
                ref=record.semantics_ref,
            )
        )
    for name, ref in record.semantic_fields:
        if not name or not ref or is_placeholder_ref(ref):
            violations.append(
                MarketCoverageViolation(
                    "market_instrument_semantics_ref_not_real",
                    "every instrument semantic field must resolve to a durable real ref",
                    field=name,
                    ref=ref,
                )
            )
    return MarketCoverageDecision(not violations, tuple(violations))


def validate_market_coverage_receipt_shape(record: MarketCoverageReceipt) -> MarketCoverageDecision:
    violations: list[MarketCoverageViolation] = []
    if record.receipt_version != MARKET_COVERAGE_RECEIPT_VERSION:
        violations.append(
            MarketCoverageViolation(
                "market_coverage_receipt_version_unsupported",
                "market coverage receipt version is unsupported",
                field="receipt_version",
                ref=record.receipt_ref,
            )
        )
    for name in (
        "receipt_ref",
        "owner_user_id",
        "capital_record_ref",
        "use_validation_refs",
        "transformation_refs",
        "instrument_semantics_refs",
    ):
        if not getattr(record, name):
            violations.append(
                MarketCoverageViolation(
                    "market_coverage_receipt_required_field_missing",
                    "coverage receipt requires owner and exact durable dependency refs",
                    field=name,
                    ref=record.receipt_ref,
                )
            )
    for name in (
        "use_validation_refs",
        "transformation_refs",
        "instrument_semantics_refs",
    ):
        values = tuple(getattr(record, name))
        if len(values) != len(set(values)):
            violations.append(
                MarketCoverageViolation(
                    "market_coverage_receipt_duplicate_ref",
                    "coverage receipt dependency refs must be unique",
                    field=name,
                    ref=record.receipt_ref,
                )
            )
        for ref in values:
            if is_placeholder_ref(ref):
                violations.append(
                    MarketCoverageViolation(
                        "market_coverage_receipt_placeholder_ref",
                        "coverage receipt cannot bind synthetic, fixture, placeholder, or goal-closure refs",
                        field=name,
                        ref=ref,
                    )
                )
    if is_placeholder_ref(record.capital_record_ref):
        violations.append(
            MarketCoverageViolation(
                "market_coverage_receipt_placeholder_ref",
                "coverage receipt cannot bind a placeholder capital ref",
                field="capital_record_ref",
                ref=record.capital_record_ref,
            )
        )
    if record.snapshot.owner_user_id != record.owner_user_id:
        violations.append(
            MarketCoverageViolation(
                "market_coverage_receipt_owner_mismatch",
                "receipt and snapshot owner must match exactly",
                field="owner_user_id",
                ref=record.owner_user_id,
            )
        )
    if frozenset(record.snapshot.market_families) != REQUIRED_MARKET_FAMILIES:
        violations.append(
            MarketCoverageViolation(
                "market_coverage_family_set_incomplete",
                "current section 11 proof requires exact option, future, bond, FX, and commodity families",
                field="market_families",
                ref=record.receipt_ref,
            )
        )
    if frozenset(record.snapshot.use_contexts) != REQUIRED_MARKET_USE_CONTEXTS:
        violations.append(
            MarketCoverageViolation(
                "market_coverage_use_context_set_incomplete",
                "current section 11 proof requires research, backtest, confirmatory validation, paper, and testnet contexts",
                field="use_contexts",
                ref=record.receipt_ref,
            )
        )
    component_keys = {(item.component_kind, item.component_ref) for item in record.snapshot.components}
    if not record.snapshot.components or len(component_keys) != len(record.snapshot.components):
        violations.append(
            MarketCoverageViolation(
                "market_coverage_component_set_inexact",
                "coverage snapshot components must be non-empty and uniquely keyed",
                field="components",
                ref=record.receipt_ref,
            )
        )
    if record.receipt_ref and record.receipt_ref != record.canonical_receipt_ref:
        violations.append(
            MarketCoverageViolation(
                "market_coverage_receipt_identity_mismatch",
                "receipt_ref must content-bind owner, exact refs, and current component state",
                field="receipt_ref",
                ref=record.receipt_ref,
            )
        )
    return MarketCoverageDecision(not violations, tuple(violations))


def _family_matches_instrument(family: str, instrument: InstrumentSpec) -> bool:
    return family in _families_for_instrument(instrument)


def _families_for_instrument(instrument: InstrumentSpec) -> frozenset[str]:
    asset_class = _text(instrument.asset_class).lower()
    instrument_type = _text(instrument.instrument_type).lower()
    families: set[str] = set()
    if instrument_type == "option" or "option" in asset_class:
        families.add("option")
    if instrument_type in {"future", "futures", "perpetual"}:
        families.add("future")
    if instrument_type in {"bond", "rate"} or asset_class in {"bond", "rate"}:
        families.add("bond")
    if instrument_type in {"fx", "forex"} or asset_class == "fx":
        families.add("fx")
    if asset_class == "commodity":
        families.add("commodity")
    return frozenset(families)


def _strict_dataset(dataset: DatasetSemanticsRecord) -> None:
    decision = validate_dataset_semantics(dataset, use_context="confirmatory_validation")
    if not decision.accepted:
        raise MarketCoverageError(
            "dataset semantics rejected: " + ",".join(item.code for item in decision.violations)
        )
    if _text(dataset.quality_status).lower() not in _ACCEPTED_QUALITY_STATUSES:
        raise MarketCoverageError("dataset quality_status is not accepted/current")
    if _text(dataset.freshness_status).lower() not in _CURRENT_STATUSES:
        raise MarketCoverageError("dataset freshness_status is not current/fresh")
    for name in _DATASET_SEMANTIC_FIELDS:
        _real_ref(getattr(dataset, name), field=f"dataset.{name}")
    for name in (
        "source_ref",
        "known_at_ref",
        "effective_at_ref",
        "pit_bitemporal_rules_ref",
        "checksum",
    ):
        _real_ref(getattr(dataset, name), field=f"dataset.{name}")
    for ref in dataset.lineage_refs:
        _real_ref(ref, field="dataset.lineage_refs")


def _strict_instrument(instrument: InstrumentSpec) -> None:
    decision = validate_instrument_spec(instrument)
    if not decision.accepted:
        raise MarketCoverageError(
            "instrument spec rejected: " + ",".join(item.code for item in decision.violations)
        )
    for name in ("instrument_ref", "exchange_calendar_ref", "contract_spec_ref", "symbol_mapping_ref"):
        _real_ref(getattr(instrument, name), field=f"instrument.{name}")


class PersistentMarketCoverageRegistry:
    """Schema-v2 hash-chained owner ledger for current section 11 receipts."""

    def __init__(self, path: str | Path, market_data_registry: PersistentMarketDataRegistry) -> None:
        if not isinstance(market_data_registry, PersistentMarketDataRegistry):
            raise TypeError("market_data_registry must be PersistentMarketDataRegistry")
        self._path = Path(path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._lock_path = self._path.with_name(f".{self._path.name}.lock")
        self._thread_lock = threading.RLock()
        self._market_data_registry = market_data_registry
        self._capital_versions: dict[tuple[str, str, str], MarketCapitalStateRecord] = {}
        self._capital_heads: dict[tuple[str, str], MarketCapitalStateRecord] = {}
        self._transformation_versions: dict[
            tuple[str, str, str], MarketTransformationStateRecord
        ] = {}
        self._transformation_heads: dict[
            tuple[str, str], MarketTransformationStateRecord
        ] = {}
        self._semantics_versions: dict[
            tuple[str, str, str], MarketInstrumentSemanticsRecord
        ] = {}
        self._semantics_heads: dict[tuple[str, str], MarketInstrumentSemanticsRecord] = {}
        self._receipts: dict[tuple[str, str], MarketCoverageReceipt] = {}
        self._last_record_hash: str | None = None
        self._legacy_quarantined_count = 0
        self._corrupt_quarantined_count = 0
        self._poisoned = False
        self._load_existing()

    @property
    def path(self) -> Path:
        return self._path

    @property
    def legacy_quarantined_count(self) -> int:
        self._refresh()
        return self._legacy_quarantined_count

    @property
    def corrupt_quarantined_count(self) -> int:
        self._refresh()
        return self._corrupt_quarantined_count

    @property
    def poisoned(self) -> bool:
        self._refresh()
        return self._poisoned

    @contextmanager
    def _exclusive_lock(self) -> Iterator[None]:
        fd = os.open(self._lock_path, os.O_RDWR | os.O_CREAT, 0o600)
        held = None
        try:
            os.fchmod(fd, 0o600)
            held = acquire_exclusive_fd(fd, timeout_seconds=10.0)
            yield
        finally:
            if held is not None:
                held.release()
            os.close(fd)

    def _reset(self) -> None:
        self._capital_versions.clear()
        self._capital_heads.clear()
        self._transformation_versions.clear()
        self._transformation_heads.clear()
        self._semantics_versions.clear()
        self._semantics_heads.clear()
        self._receipts.clear()
        self._last_record_hash = None
        self._legacy_quarantined_count = 0
        self._corrupt_quarantined_count = 0
        self._poisoned = False

    def _load_existing(self) -> None:
        with self._thread_lock, self._exclusive_lock():
            self._load_existing_unlocked()

    def _refresh(self) -> None:
        with self._thread_lock, self._exclusive_lock():
            self._load_existing_unlocked()

    @contextmanager
    def _market_registry_snapshot(self, owner: str) -> Iterator[_MarketRegistrySnapshot]:
        """Hold the market registry's writer lock through receipt append."""

        registry = self._market_data_registry
        with registry._lock:  # type: ignore[attr-defined] - same concrete registry is required.
            lock_path = registry._lock_path  # type: ignore[attr-defined]
            fd: int | None = None
            held = None
            try:
                if lock_path is not None:
                    lock_path.parent.mkdir(parents=True, exist_ok=True)
                    fd = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o600)
                    os.fchmod(fd, 0o600)
                    held = acquire_exclusive_fd(fd, timeout_seconds=10.0)
                    registry._reload_from_disk_locked()  # type: ignore[attr-defined]
                yield _MarketRegistrySnapshot(
                    datasets={
                        ref: record
                        for (record_owner, ref), record in registry._datasets.items()  # type: ignore[attr-defined]
                        if record_owner == owner
                    },
                    instruments={
                        ref: record
                        for (record_owner, ref), record in registry._instruments.items()  # type: ignore[attr-defined]
                        if record_owner == owner
                    },
                    capability_matrices={
                        ref: record
                        for (record_owner, ref), record in registry._capability_matrices.items()  # type: ignore[attr-defined]
                        if record_owner == owner
                    },
                    use_validations={
                        ref: record
                        for (record_owner, ref), record in registry._use_validations.items()  # type: ignore[attr-defined]
                        if record_owner == owner
                    },
                )
            finally:
                if held is not None:
                    held.release()
                if fd is not None:
                    os.close(fd)

    def _load_existing_unlocked(self) -> None:
        self._reset()
        if not self._path.exists():
            return
        chain_broken = False
        for line in self._path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                self._corrupt_quarantined_count += 1
                self._poisoned = True
                chain_broken = True
                continue
            if not isinstance(row, dict) or row.get("schema_version") != MARKET_COVERAGE_SCHEMA_VERSION:
                self._legacy_quarantined_count += 1
                continue
            if chain_broken:
                self._corrupt_quarantined_count += 1
                self._poisoned = True
                continue
            try:
                self._apply_row(row)
            except Exception:
                self._corrupt_quarantined_count += 1
                self._poisoned = True
                chain_broken = True

    def _decode_payload(self, event_type: str, payload: Any) -> Any:
        if event_type == "market_capital_state_recorded":
            return market_capital_state_record_from_dict(payload)
        if event_type == "market_transformation_state_recorded":
            return market_transformation_state_record_from_dict(payload)
        if event_type == "market_instrument_semantics_recorded":
            return market_instrument_semantics_record_from_dict(payload)
        if event_type == "market_coverage_receipt_recorded":
            return market_coverage_receipt_from_dict(payload)
        raise ValueError("unknown market coverage event_type")

    @staticmethod
    def _record_decision(record: Any) -> MarketCoverageDecision:
        if isinstance(record, MarketCapitalStateRecord):
            return validate_market_capital_state(record)
        if isinstance(record, MarketTransformationStateRecord):
            return validate_market_transformation_state(record)
        if isinstance(record, MarketInstrumentSemanticsRecord):
            return validate_market_instrument_semantics(record)
        if isinstance(record, MarketCoverageReceipt):
            return validate_market_coverage_receipt_shape(record)
        raise TypeError("unsupported market coverage record")

    def _apply_row(self, row: dict[str, Any]) -> Any:
        expected = {
            "schema_version",
            "event_type",
            "owner_user_id",
            "payload",
            "previous_record_hash",
            "record_hash",
        }
        if set(row) != expected:
            raise ValueError("market coverage row has an inexact schema-v2 envelope")
        owner = _owner(row["owner_user_id"])
        if row["previous_record_hash"] != self._last_record_hash:
            raise ValueError("market coverage previous_record_hash mismatch")
        body = {key: value for key, value in row.items() if key != "record_hash"}
        expected_hash = "sha256:" + _sha256(body)
        if row["record_hash"] != expected_hash:
            raise ValueError("market coverage record_hash mismatch")
        record = self._decode_payload(_text(row["event_type"]), row["payload"])
        decision = self._record_decision(record)
        if not decision.accepted:
            raise ValueError(
                "invalid market coverage record: "
                + ",".join(item.code for item in decision.violations)
            )
        if isinstance(record, MarketCoverageReceipt):
            if record.owner_user_id != owner:
                raise ValueError("market coverage receipt owner envelope mismatch")
            key = (owner, record.receipt_ref)
            existing = self._receipts.get(key)
            if existing is not None and existing != record:
                raise ValueError("market coverage receipt identity collision")
            self._receipts[key] = record
        elif isinstance(record, MarketCapitalStateRecord):
            key = (owner, record.capital_ref, record.revision)
            existing = self._capital_versions.get(key)
            if existing is not None and existing != record:
                raise ValueError("market capital revision collision")
            self._capital_versions[key] = record
            self._capital_heads[(owner, record.capital_ref)] = record
        elif isinstance(record, MarketTransformationStateRecord):
            key = (owner, record.transform_ref, record.revision)
            existing = self._transformation_versions.get(key)
            if existing is not None and existing != record:
                raise ValueError("market transformation revision collision")
            self._transformation_versions[key] = record
            self._transformation_heads[(owner, record.transform_ref)] = record
        else:
            key = (owner, record.semantics_ref, record.revision)
            existing = self._semantics_versions.get(key)
            if existing is not None and existing != record:
                raise ValueError("market instrument semantics revision collision")
            self._semantics_versions[key] = record
            self._semantics_heads[(owner, record.semantics_ref)] = record
        self._last_record_hash = expected_hash
        return record

    def _atomic_append(self, row: dict[str, Any]) -> None:
        existing = self._path.read_bytes() if self._path.exists() else b""
        prefix = existing if not existing or existing.endswith(b"\n") else existing + b"\n"
        encoded = (_canonical_json(row) + "\n").encode("utf-8")
        fd, temporary = tempfile.mkstemp(prefix=f".{self._path.name}.", dir=self._path.parent)
        replaced = False
        try:
            os.fchmod(fd, 0o600)
            with os.fdopen(fd, "wb", closefd=True) as handle:
                handle.write(prefix)
                handle.write(encoded)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, self._path)
            replaced = True
            directory_fd = os.open(self._path.parent, os.O_RDONLY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
        except BaseException as exc:
            try:
                os.close(fd)
            except OSError:
                pass
            try:
                os.unlink(temporary)
            except OSError:
                pass
            if replaced:
                raise MarketCoverageCommitUncertain(
                    "market coverage commit is visible, but directory fsync failed; "
                    "crash durability is unverified and retry is idempotent"
                ) from exc
            raise

    def _record(self, *, owner_user_id: str, event_type: str, record: Any) -> Any:
        owner = _owner(owner_user_id)
        decision = self._record_decision(record)
        if not decision.accepted:
            raise MarketCoverageError(
                "market coverage record rejected: "
                + ",".join(item.code for item in decision.violations)
            )
        with self._thread_lock, self._exclusive_lock():
            self._load_existing_unlocked()
            return self._record_unlocked(owner=owner, event_type=event_type, record=record)

    def _record_unlocked(self, *, owner: str, event_type: str, record: Any) -> Any:
        """Append while both the thread and cross-process locks are already held."""

        if self._poisoned:
            raise MarketCoverageError("market coverage ledger is corrupt and quarantined")
        decision = self._record_decision(record)
        if not decision.accepted:
            raise MarketCoverageError(
                "market coverage record rejected before append: "
                + ",".join(item.code for item in decision.violations)
            )
        existing = self._existing_record(owner, record)
        if existing is not None:
            if existing == record:
                return existing
            raise MarketCoverageError("market coverage record identity collision")
        body = {
            "schema_version": MARKET_COVERAGE_SCHEMA_VERSION,
            "event_type": event_type,
            "owner_user_id": owner,
            "payload": asdict(record),
            "previous_record_hash": self._last_record_hash,
        }
        row = {**body, "record_hash": "sha256:" + _sha256(body)}
        self._atomic_append(row)
        return self._apply_row(row)

    def _existing_record(self, owner: str, record: Any) -> Any | None:
        if isinstance(record, MarketCapitalStateRecord):
            return self._capital_versions.get((owner, record.capital_ref, record.revision))
        if isinstance(record, MarketTransformationStateRecord):
            return self._transformation_versions.get((owner, record.transform_ref, record.revision))
        if isinstance(record, MarketInstrumentSemanticsRecord):
            return self._semantics_versions.get((owner, record.semantics_ref, record.revision))
        return self._receipts.get((owner, record.receipt_ref))

    def record_capital(
        self, record: MarketCapitalStateRecord, *, owner_user_id: str
    ) -> MarketCapitalStateRecord:
        return self._record(
            owner_user_id=owner_user_id,
            event_type="market_capital_state_recorded",
            record=record,
        )

    def record_transformation(
        self, record: MarketTransformationStateRecord, *, owner_user_id: str
    ) -> MarketTransformationStateRecord:
        return self._record(
            owner_user_id=owner_user_id,
            event_type="market_transformation_state_recorded",
            record=record,
        )

    def record_instrument_semantics(
        self, record: MarketInstrumentSemanticsRecord, *, owner_user_id: str
    ) -> MarketInstrumentSemanticsRecord:
        return self._record(
            owner_user_id=owner_user_id,
            event_type="market_instrument_semantics_recorded",
            record=record,
        )

    def _head(self, mapping: dict[tuple[str, str], Any], owner: str, ref: str, label: str) -> Any:
        try:
            return mapping[(owner, _real_ref(ref, field=label))]
        except KeyError as exc:
            raise MarketCoverageError(f"{label} is not durably recorded for owner") from exc

    @staticmethod
    def _component(kind: str, ref: str, revision: str, record: Any) -> MarketCoverageComponentState:
        return MarketCoverageComponentState(
            component_kind=kind,
            component_ref=ref,
            revision=revision,
            state_hash=_state_hash(record),
        )

    def _resolve_snapshot(
        self,
        *,
        owner: str,
        market_registry: _MarketRegistrySnapshot,
        use_validation_refs: tuple[str, ...],
        capital_record_ref: str,
        transformation_refs: tuple[str, ...],
        instrument_semantics_refs: tuple[str, ...],
    ) -> MarketCoverageSnapshot:
        if self._poisoned:
            raise MarketCoverageError("market coverage ledger is corrupt and cannot prove current state")
        use_refs = _exact_unique(use_validation_refs, field="use_validation_refs")
        transform_refs = _exact_unique(transformation_refs, field="transformation_refs")
        semantics_refs = _exact_unique(instrument_semantics_refs, field="instrument_semantics_refs")
        capital_ref = _real_ref(capital_record_ref, field="capital_record_ref")

        capital = self._head(self._capital_heads, owner, capital_ref, "capital_record_ref")
        transformations = tuple(
            self._head(self._transformation_heads, owner, ref, "transformation_ref")
            for ref in transform_refs
        )
        semantics = tuple(
            self._head(self._semantics_heads, owner, ref, "instrument_semantics_ref")
            for ref in semantics_refs
        )
        for record in (capital, *transformations, *semantics):
            decision = self._record_decision(record)
            if not decision.accepted:
                raise MarketCoverageError(
                    "market coverage dependency is not current: "
                    + ",".join(item.code for item in decision.violations)
                )

        components: dict[tuple[str, str], MarketCoverageComponentState] = {}

        def add(kind: str, ref: str, revision: str, record: Any) -> None:
            key = (kind, ref)
            component = self._component(kind, ref, revision, record)
            if key in components and components[key] != component:
                raise MarketCoverageError(f"conflicting current component: {kind}:{ref}")
            components[key] = component

        add("capital", capital.capital_ref, capital.revision, capital)
        for record in transformations:
            add("transformation", record.transform_ref, record.revision, record)
        for record in semantics:
            add("instrument_semantics", record.semantics_ref, record.revision, record)

        validation_records: list[MarketDataUseValidationRecord] = []
        instruments: dict[str, InstrumentSpec] = {}
        matrices: dict[str, MarketCapabilityMatrixRecord] = {}
        datasets: dict[str, DatasetSemanticsRecord] = {}
        use_contexts: set[str] = set()
        datasets_by_context: dict[str, set[str]] = {}
        instruments_by_context: dict[str, set[str]] = {}
        for validation_ref in use_refs:
            try:
                validation = market_registry.use_validations[validation_ref]
            except KeyError as exc:
                raise MarketCoverageError(
                    f"use validation is not durably recorded for owner: {validation_ref}"
                ) from exc
            validation_decision = validate_market_data_use_validation_record(validation)
            if not validation_decision.accepted or validation.recorded_by != owner:
                raise MarketCoverageError("market use validation is not accepted for owner")
            if validation.capital_record_ref != capital_ref:
                raise MarketCoverageError("use validation capital ref does not match durable current capital")
            if set(validation.transformation_refs) != set(transform_refs) or len(
                validation.transformation_refs
            ) != len(transform_refs):
                raise MarketCoverageError(
                    "use validation transformation refs do not exactly match durable current transformations"
                )
            use_context = _enum_text(validation.use_context)
            use_contexts.add(use_context)
            datasets_by_context.setdefault(use_context, set()).update(validation.dataset_refs)
            instruments_by_context.setdefault(use_context, set()).update(validation.instrument_refs)
            add("use_validation", validation.validation_ref, validation.created_at_utc, validation)
            validation_records.append(validation)
            try:
                matrix = market_registry.capability_matrices[validation.capability_matrix_ref]
            except KeyError as exc:
                raise MarketCoverageError("capability matrix is not durably recorded for owner") from exc
            matrix_decision = validate_market_capability_matrix(matrix, use_context=use_context)
            if not matrix_decision.accepted:
                raise MarketCoverageError(
                    "capability matrix rejects current environment: "
                    + ",".join(item.code for item in matrix_decision.violations)
                )
            for field_name in (
                "data_availability",
                "cost_model_availability",
                "execution_availability",
                "permission_requirement",
            ):
                try:
                    _real_ref(
                        getattr(matrix, field_name),
                        field=f"capability_matrix.{field_name}",
                    )
                except ValueError as exc:
                    raise MarketCoverageError(
                        "capability matrix requires exact real availability and environment permission refs"
                    ) from exc
            matrices[matrix.matrix_ref] = matrix
            add(
                "capability_matrix",
                matrix.matrix_ref,
                content_hash(matrix.to_dict()),
                matrix,
            )

            for dataset_ref in validation.dataset_refs:
                try:
                    dataset = market_registry.datasets[dataset_ref]
                except KeyError as exc:
                    raise MarketCoverageError("dataset is not durably recorded for owner") from exc
                _strict_dataset(dataset)
                datasets[dataset.dataset_ref] = dataset
                add("dataset", dataset.dataset_ref, dataset.version, dataset)

            for instrument_ref in validation.instrument_refs:
                try:
                    instrument = market_registry.instruments[instrument_ref]
                except KeyError as exc:
                    raise MarketCoverageError("instrument is not durably recorded for owner") from exc
                _strict_instrument(instrument)
                if (
                    _text(instrument.asset_class) != _text(matrix.asset_class)
                    or _text(instrument.instrument_type) != _text(matrix.instrument_type)
                ):
                    raise MarketCoverageError(
                        "capability matrix asset_class/instrument_type does not exactly match instrument"
                    )
                instruments[instrument.instrument_ref] = instrument
                add("instrument", instrument.instrument_ref, instrument.spec_id, instrument)

        if not validation_records or not datasets or not instruments or not matrices:
            raise MarketCoverageError("coverage requires persisted validation, dataset, instrument, and matrix records")
        if set(use_refs) != set(market_registry.use_validations):
            raise MarketCoverageError(
                "coverage validations must exactly bind the owner's current market registry universe"
            )
        if set(datasets) != set(market_registry.datasets):
            raise MarketCoverageError(
                "coverage datasets must exactly bind the owner's current market registry universe"
            )
        if set(instruments) != set(market_registry.instruments):
            raise MarketCoverageError(
                "coverage instruments must exactly bind the owner's current market registry universe"
            )
        if set(matrices) != set(market_registry.capability_matrices):
            raise MarketCoverageError(
                "coverage capability matrices must exactly bind the owner's current market registry universe"
            )
        complete_dataset_refs = set(datasets)
        complete_instrument_refs = set(instruments)
        for use_context in REQUIRED_MARKET_USE_CONTEXTS:
            if datasets_by_context.get(use_context, set()) != complete_dataset_refs:
                raise MarketCoverageError(
                    "every required environment must preserve the same complete dataset lineage"
                )
            if instruments_by_context.get(use_context, set()) != complete_instrument_refs:
                raise MarketCoverageError(
                    "every required environment must preserve the same complete instrument refs"
                )

        semantics_by_instrument: dict[str, dict[str, MarketInstrumentSemanticsRecord]] = {}
        for record in semantics:
            family_records = semantics_by_instrument.setdefault(record.instrument_ref, {})
            if record.market_family in family_records:
                raise MarketCoverageError(
                    "each instrument requires exactly one current record per applicable semantic family"
                )
            family_records[record.market_family] = record
        expected_semantic_instruments = {
            instrument_ref
            for instrument_ref, instrument in instruments.items()
            if _families_for_instrument(instrument)
        }
        if set(semantics_by_instrument) != expected_semantic_instruments:
            raise MarketCoverageError(
                "instrument semantics refs must exactly cover every current instrument with special-family semantics and no others"
            )
        for instrument_ref, instrument in instruments.items():
            applicable_families = _families_for_instrument(instrument)
            actual_families = set(semantics_by_instrument.get(instrument_ref, {}))
            if actual_families != set(applicable_families):
                raise MarketCoverageError(
                    "instrument semantics must exactly cover every applicable special market family"
                )
        market_families = {record.market_family for record in semantics}
        if market_families != set(REQUIRED_MARKET_FAMILIES):
            raise MarketCoverageError(
                "coverage requires exact option, future, bond, FX, and commodity semantic families"
            )

        return MarketCoverageSnapshot(
            owner_user_id=owner,
            market_families=tuple(market_families),
            use_contexts=tuple(use_contexts),
            components=tuple(components.values()),
        )

    def record_current(
        self,
        *,
        owner_user_id: str,
        use_validation_refs: tuple[str, ...],
        capital_record_ref: str,
        transformation_refs: tuple[str, ...],
        instrument_semantics_refs: tuple[str, ...],
    ) -> MarketCoverageReceipt:
        """Resolve durable exact records and append one current receipt atomically."""

        owner = _owner(owner_user_id)
        with self._thread_lock, self._exclusive_lock():
            self._load_existing_unlocked()
            with self._market_registry_snapshot(owner) as market_registry:
                snapshot = self._resolve_snapshot(
                    owner=owner,
                    market_registry=market_registry,
                    use_validation_refs=use_validation_refs,
                    capital_record_ref=capital_record_ref,
                    transformation_refs=transformation_refs,
                    instrument_semantics_refs=instrument_semantics_refs,
                )
                blank = MarketCoverageReceipt(
                    receipt_ref="",
                    owner_user_id=owner,
                    use_validation_refs=use_validation_refs,
                    capital_record_ref=capital_record_ref,
                    transformation_refs=transformation_refs,
                    instrument_semantics_refs=instrument_semantics_refs,
                    snapshot=snapshot,
                )
                receipt = MarketCoverageReceipt(
                    receipt_ref=blank.canonical_receipt_ref,
                    owner_user_id=blank.owner_user_id,
                    use_validation_refs=blank.use_validation_refs,
                    capital_record_ref=blank.capital_record_ref,
                    transformation_refs=blank.transformation_refs,
                    instrument_semantics_refs=blank.instrument_semantics_refs,
                    snapshot=blank.snapshot,
                )
                return self._record_unlocked(
                    owner=owner,
                    event_type="market_coverage_receipt_recorded",
                    record=receipt,
                )

    def receipt(self, receipt_ref: str, *, owner_user_id: str) -> MarketCoverageReceipt:
        owner = _owner(owner_user_id)
        with self._thread_lock, self._exclusive_lock():
            self._load_existing_unlocked()
            if self._poisoned:
                raise MarketCoverageError("market coverage ledger is corrupt and quarantined")
            try:
                return self._receipts[(owner, _real_ref(receipt_ref, field="receipt_ref"))]
            except KeyError as exc:
                raise KeyError("market coverage receipt is not recorded for owner") from exc

    def receipts(self, *, owner_user_id: str) -> tuple[MarketCoverageReceipt, ...]:
        owner = _owner(owner_user_id)
        with self._thread_lock, self._exclusive_lock():
            self._load_existing_unlocked()
            if self._poisoned:
                return ()
            return tuple(
                record for (record_owner, _), record in self._receipts.items() if record_owner == owner
            )

    def validate_current(
        self, receipt_ref: str, *, owner_user_id: str
    ) -> MarketCoverageDecision:
        try:
            receipt = self.receipt(receipt_ref, owner_user_id=owner_user_id)
        except (KeyError, MarketCoverageError, ValueError) as exc:
            return MarketCoverageDecision(
                False,
                (
                    MarketCoverageViolation(
                        "market_coverage_receipt_unavailable",
                        f"current coverage receipt cannot be resolved: {type(exc).__name__}",
                        field="receipt_ref",
                        ref=_text(receipt_ref),
                    ),
                ),
            )
        try:
            with self._thread_lock, self._exclusive_lock():
                self._load_existing_unlocked()
                with self._market_registry_snapshot(receipt.owner_user_id) as market_registry:
                    current = self._resolve_snapshot(
                        owner=receipt.owner_user_id,
                        market_registry=market_registry,
                        use_validation_refs=receipt.use_validation_refs,
                        capital_record_ref=receipt.capital_record_ref,
                        transformation_refs=receipt.transformation_refs,
                        instrument_semantics_refs=receipt.instrument_semantics_refs,
                    )
        except Exception as exc:  # missing, cross-owner, revoked, or corrupt dependencies are red.
            return MarketCoverageDecision(
                False,
                (
                    MarketCoverageViolation(
                        "market_coverage_current_resolution_failed",
                        f"current coverage dependencies cannot be resolved: {type(exc).__name__}",
                        field="receipt_ref",
                        ref=receipt.receipt_ref,
                    ),
                ),
            )
        violations = list(validate_market_coverage_receipt_shape(receipt).violations)
        if current != receipt.snapshot:
            violations.append(
                MarketCoverageViolation(
                    "market_coverage_current_state_drifted",
                    "capital, transformation, semantics, dataset, instrument, matrix, or validation state changed",
                    field="snapshot",
                    ref=receipt.receipt_ref,
                )
            )
        return MarketCoverageDecision(not violations, tuple(violations))


def market_coverage_semantic_material(
    receipt: MarketCoverageReceipt,
    *,
    entrypoint_ref: str = MARKET_COVERAGE_ENTRYPOINT_REF,
) -> MarketCoverageSemanticMaterial:
    if entrypoint_ref != MARKET_COVERAGE_ENTRYPOINT_REF:
        raise ValueError("section 11 semantic material requires the canonical market coverage API")
    producers = tuple(
        sorted(
            "market_coverage_producer:"
            f"{item.component_kind}:{item.component_ref}:{item.revision}"
            for item in receipt.snapshot.components
        )
    )
    stores = tuple(
        sorted(
            {
                receipt.receipt_ref,
                *(
                    "market_coverage_state:"
                    f"{item.component_kind}:{item.component_ref}:{item.revision}:{item.state_hash}"
                    for item in receipt.snapshot.components
                ),
            }
        )
    )
    consumers = tuple(
        sorted(f"market_data_use_current:{ref}" for ref in receipt.use_validation_refs)
    )
    tests = tuple(
        sorted(
            "market_coverage_current_check:"
            f"{receipt.receipt_ref}:{item.component_kind}:{item.component_ref}:{item.state_hash}"
            for item in receipt.snapshot.components
        )
    )
    return MarketCoverageSemanticMaterial(
        subject_ref=f"goal_section:§11:market_coverage_receipt:{receipt.receipt_ref}",
        producer_refs=producers,
        store_refs=stores,
        consumer_refs=consumers,
        gate_verdict_refs=(receipt.receipt_ref,),
        test_refs=tests,
    )


class MarketCoverageSectionAdapter:
    """Prove section 11 from one canonical API lineage and current receipt."""

    def __init__(self, entrypoint_registry: Any, coverage_registry: PersistentMarketCoverageRegistry) -> None:
        self._entrypoint_registry = entrypoint_registry
        self._coverage_registry = coverage_registry

    def validate(
        self,
        record: GoalSectionSemanticProofRecord,
        *,
        owner: str,
    ) -> GoalSemanticDecision:
        violations: list[GoalSemanticViolation] = []

        def reject(field: str, ref: str, message: str) -> None:
            violations.append(
                GoalSemanticViolation(
                    "goal_semantic_market_coverage_invalid",
                    message,
                    field=field,
                    ref=ref,
                )
            )

        owner = _text(owner)
        if record.section != "§11":
            reject("section", record.section, "market coverage adapter only supports section 11")
            return GoalSemanticDecision(False, tuple(violations))
        if record.recorded_by != owner:
            reject("recorded_by", record.recorded_by, "section 11 semantic proof owner mismatch")
        if not record.claims_section_complete or record.unverified_residuals:
            reject(
                "claims_section_complete",
                record.proof_ref,
                "section 11 completion requires a complete claim with no residuals",
            )
        if len(record.entrypoint_coverage_refs) != 1:
            reject(
                "entrypoint_coverage_refs",
                ",".join(record.entrypoint_coverage_refs),
                "section 11 requires exactly one canonical current market coverage API lineage",
            )
            return GoalSemanticDecision(False, tuple(violations))
        coverage_ref = record.entrypoint_coverage_refs[0]
        try:
            coverage = strict_current_entrypoint_coverage(
                self._entrypoint_registry,
                coverage_ref,
                owner=owner,
            )
        except KeyError:
            reject("entrypoint_coverage_refs", coverage_ref, "market coverage API lineage is absent for owner")
            return GoalSemanticDecision(False, tuple(violations))
        try:
            backing = self._entrypoint_registry.validate_real_backing(coverage)
        except Exception as exc:  # strict current backing is mandatory.
            reject(
                "entrypoint_coverage_refs",
                coverage_ref,
                f"market coverage API backing validation raised {type(exc).__name__}",
            )
            return GoalSemanticDecision(False, tuple(violations))
        if not bool(getattr(backing, "accepted", False)):
            reject("entrypoint_coverage_refs", coverage_ref, "market coverage API lineage is not current")
        if _text(getattr(coverage, "recorded_by", "")) != owner:
            reject(
                "entrypoint_coverage_refs",
                coverage_ref,
                "market coverage API lineage owner does not match",
            )
        source = _enum_text(getattr(coverage, "entry_source", ""))
        if source != "api" or _text(getattr(coverage, "entrypoint_ref", "")) != MARKET_COVERAGE_ENTRYPOINT_REF:
            reject(
                "entrypoint_coverage_refs",
                coverage_ref,
                "section 11 requires api:goal.market_coverage.current",
            )
        if "§11" not in set(getattr(coverage, "goal_sections", ())):
            reject("entrypoint_coverage_refs", coverage_ref, "coverage lineage does not cite section 11")
        receipt_refs = tuple(
            ref
            for ref in getattr(coverage, "validation_refs", ())
            if _text(ref).startswith("market_coverage_receipt:")
        )
        if len(receipt_refs) != 1:
            reject(
                "gate_verdict_refs",
                ",".join(receipt_refs),
                "canonical market coverage lineage must bind exactly one durable receipt",
            )
            return GoalSemanticDecision(False, tuple(violations))
        receipt_ref = receipt_refs[0]
        try:
            receipt = self._coverage_registry.receipt(receipt_ref, owner_user_id=owner)
        except (KeyError, MarketCoverageError):
            reject("gate_verdict_refs", receipt_ref, "market coverage receipt is absent for owner")
            return GoalSemanticDecision(False, tuple(violations))
        current = self._coverage_registry.validate_current(receipt_ref, owner_user_id=owner)
        if not current.accepted:
            reject(
                "gate_verdict_refs",
                receipt_ref,
                "market coverage receipt is no longer current: "
                + ",".join(item.code for item in current.violations),
            )
        expected = market_coverage_semantic_material(receipt)
        if record.subject_ref != expected.subject_ref:
            reject("subject_ref", record.subject_ref, "section 11 subject must content-bind current receipt")
        for field_name in (
            "producer_refs",
            "store_refs",
            "consumer_refs",
            "gate_verdict_refs",
            "test_refs",
        ):
            actual = tuple(getattr(record, field_name))
            wanted = tuple(getattr(expected, field_name))
            if len(actual) != len(set(actual)) or set(actual) != set(wanted):
                reject(
                    field_name,
                    ",".join(sorted(actual)),
                    f"{field_name} must exactly match the current section 11 receipt",
                )
        return GoalSemanticDecision(not violations, tuple(violations))


__all__ = [
    "MARKET_COVERAGE_ENTRYPOINT_REF",
    "MARKET_COVERAGE_RECEIPT_VERSION",
    "MARKET_COVERAGE_SCHEMA_VERSION",
    "MARKET_FAMILY_REQUIRED_FIELDS",
    "REQUIRED_MARKET_FAMILIES",
    "REQUIRED_MARKET_USE_CONTEXTS",
    "MarketCapitalStateRecord",
    "MarketCoverageComponentState",
    "MarketCoverageCommitUncertain",
    "MarketCoverageDecision",
    "MarketCoverageError",
    "MarketCoverageReceipt",
    "MarketCoverageSectionAdapter",
    "MarketCoverageSemanticMaterial",
    "MarketCoverageSnapshot",
    "MarketCoverageViolation",
    "MarketInstrumentSemanticsRecord",
    "MarketTransformationStateRecord",
    "PersistentMarketCoverageRegistry",
    "market_capital_state_record_from_dict",
    "market_coverage_receipt_from_dict",
    "market_coverage_receipt_identity",
    "market_coverage_semantic_material",
    "market_coverage_snapshot_from_dict",
    "market_instrument_semantics_record_from_dict",
    "market_transformation_state_record_from_dict",
    "validate_market_capital_state",
    "validate_market_coverage_receipt_shape",
    "validate_market_instrument_semantics",
    "validate_market_transformation_state",
]
