"""GOAL §11 market data and instrument capability contracts."""

from __future__ import annotations

import json
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any

from .spine import RuntimeStatus


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


class ValidationUseContext(str, Enum):
    RESEARCH = "research"
    BACKTEST = "backtest"
    CONFIRMATORY_VALIDATION = "confirmatory_validation"
    PAPER = "paper"
    TESTNET = "testnet"
    LIVE = "live"


@dataclass(frozen=True)
class MarketDataViolation:
    code: str
    message: str
    field: str = ""
    ref: str = ""


@dataclass(frozen=True)
class MarketDataDecision:
    accepted: bool
    violations: tuple[MarketDataViolation, ...]


@dataclass(frozen=True)
class DatasetSemanticsRecord:
    dataset_ref: str
    source_ref: str
    version: str
    known_at_ref: str | None
    effective_at_ref: str | None
    pit_bitemporal_rules_ref: str | None
    quality_status: str
    lineage_refs: tuple[str, ...]
    freshness_status: str
    checksum: str | None
    sampling_rule_ref: str | None = None
    adjustment_formula_ref: str | None = None
    asof_join_rule_ref: str | None = None
    missingness_model_ref: str | None = None
    survivorship_rule_ref: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "lineage_refs", _tuple(self.lineage_refs))

    def to_dict(self) -> dict[str, Any]:
        return {
            "dataset_ref": self.dataset_ref,
            "source_ref": self.source_ref,
            "version": self.version,
            "known_at_ref": self.known_at_ref,
            "effective_at_ref": self.effective_at_ref,
            "pit_bitemporal_rules_ref": self.pit_bitemporal_rules_ref,
            "quality_status": self.quality_status,
            "lineage_refs": list(self.lineage_refs),
            "freshness_status": self.freshness_status,
            "checksum": self.checksum,
            "sampling_rule_ref": self.sampling_rule_ref,
            "adjustment_formula_ref": self.adjustment_formula_ref,
            "asof_join_rule_ref": self.asof_join_rule_ref,
            "missingness_model_ref": self.missingness_model_ref,
            "survivorship_rule_ref": self.survivorship_rule_ref,
        }


@dataclass(frozen=True)
class InstrumentSpec:
    instrument_ref: str
    asset_class: str
    instrument_type: str
    currency: str
    exchange_calendar_ref: str | None
    contract_spec_ref: str | None = None
    option_chain_ref: str | None = None
    futures_roll_rule_ref: str | None = None
    continuous_contract_rule_ref: str | None = None
    corporate_actions_ref: str | None = None
    symbol_mapping_ref: str | None = None
    expiry_ref: str | None = None
    strike_ref: str | None = None
    contract_multiplier_ref: str | None = None
    settlement_ref: str | None = None
    exercise_style_ref: str | None = None
    margin_ref: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "instrument_ref": self.instrument_ref,
            "asset_class": self.asset_class,
            "instrument_type": self.instrument_type,
            "currency": self.currency,
            "exchange_calendar_ref": self.exchange_calendar_ref,
            "contract_spec_ref": self.contract_spec_ref,
            "option_chain_ref": self.option_chain_ref,
            "futures_roll_rule_ref": self.futures_roll_rule_ref,
            "continuous_contract_rule_ref": self.continuous_contract_rule_ref,
            "corporate_actions_ref": self.corporate_actions_ref,
            "symbol_mapping_ref": self.symbol_mapping_ref,
            "expiry_ref": self.expiry_ref,
            "strike_ref": self.strike_ref,
            "contract_multiplier_ref": self.contract_multiplier_ref,
            "settlement_ref": self.settlement_ref,
            "exercise_style_ref": self.exercise_style_ref,
            "margin_ref": self.margin_ref,
        }


@dataclass(frozen=True)
class MarketCapabilityMatrixRecord:
    matrix_ref: str
    asset_class: str
    instrument_type: str
    research: bool
    backtest: bool
    paper: bool
    testnet: bool
    live: bool
    long: bool
    short: bool
    leverage: bool
    options: bool
    margin: bool
    borrow: bool
    data_availability: str | None
    cost_model_availability: str | None
    execution_availability: str | None
    permission_requirement: str | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "matrix_ref": self.matrix_ref,
            "asset_class": self.asset_class,
            "instrument_type": self.instrument_type,
            "research": self.research,
            "backtest": self.backtest,
            "paper": self.paper,
            "testnet": self.testnet,
            "live": self.live,
            "long": self.long,
            "short": self.short,
            "leverage": self.leverage,
            "options": self.options,
            "margin": self.margin,
            "borrow": self.borrow,
            "data_availability": self.data_availability,
            "cost_model_availability": self.cost_model_availability,
            "execution_availability": self.execution_availability,
            "permission_requirement": self.permission_requirement,
        }


@dataclass(frozen=True)
class CrossCurrencyCapitalRecord:
    base_currency: str | None
    fx_conversion_ref: str | None
    collateral_ref: str | None = None
    margin_ref: str | None = None
    leverage_ref: str | None = None
    net_exposure_ref: str | None = None
    gross_exposure_ref: str | None = None
    capital_allocation_ref: str | None = None
    financing_cost_ref: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "base_currency": self.base_currency,
            "fx_conversion_ref": self.fx_conversion_ref,
            "collateral_ref": self.collateral_ref,
            "margin_ref": self.margin_ref,
            "leverage_ref": self.leverage_ref,
            "net_exposure_ref": self.net_exposure_ref,
            "gross_exposure_ref": self.gross_exposure_ref,
            "capital_allocation_ref": self.capital_allocation_ref,
            "financing_cost_ref": self.financing_cost_ref,
        }


@dataclass(frozen=True)
class DataTransformationClaim:
    transform_ref: str
    claims_theory_correct: bool
    formula_ref: str | None
    unit_binding_ref: str | None
    timing_binding_ref: str | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "transform_ref": self.transform_ref,
            "claims_theory_correct": self.claims_theory_correct,
            "formula_ref": self.formula_ref,
            "unit_binding_ref": self.unit_binding_ref,
            "timing_binding_ref": self.timing_binding_ref,
        }


@dataclass(frozen=True)
class MarketDataUseRequest:
    request_ref: str
    use_context: ValidationUseContext | RuntimeStatus | str
    datasets: tuple[DatasetSemanticsRecord, ...]
    instruments: tuple[InstrumentSpec, ...]
    capability_matrix: MarketCapabilityMatrixRecord
    capital_record: CrossCurrencyCapitalRecord | None = None
    transformation_claims: tuple[DataTransformationClaim, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "datasets", _tuple(self.datasets))
        object.__setattr__(self, "instruments", _tuple(self.instruments))
        object.__setattr__(self, "transformation_claims", _tuple(self.transformation_claims))


@dataclass(frozen=True)
class MarketDataUseValidationRecord:
    validation_ref: str
    request_ref: str
    use_context: str
    dataset_refs: tuple[str, ...]
    instrument_refs: tuple[str, ...]
    capability_matrix_ref: str
    capital_record_ref: str | None
    transformation_refs: tuple[str, ...]
    accepted: bool
    violation_codes: tuple[str, ...]
    evidence_refs: tuple[str, ...]
    recorded_by: str
    created_at_utc: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "dataset_refs", tuple(str(ref) for ref in _tuple(self.dataset_refs)))
        object.__setattr__(self, "instrument_refs", tuple(str(ref) for ref in _tuple(self.instrument_refs)))
        object.__setattr__(self, "transformation_refs", tuple(str(ref) for ref in _tuple(self.transformation_refs)))
        object.__setattr__(self, "violation_codes", tuple(str(code) for code in _tuple(self.violation_codes)))
        object.__setattr__(self, "evidence_refs", tuple(str(ref) for ref in _tuple(self.evidence_refs)))

    def to_dict(self) -> dict[str, Any]:
        return {
            "validation_ref": self.validation_ref,
            "request_ref": self.request_ref,
            "use_context": self.use_context,
            "dataset_refs": list(self.dataset_refs),
            "instrument_refs": list(self.instrument_refs),
            "capability_matrix_ref": self.capability_matrix_ref,
            "capital_record_ref": self.capital_record_ref,
            "transformation_refs": list(self.transformation_refs),
            "accepted": self.accepted,
            "violation_codes": list(self.violation_codes),
            "evidence_refs": list(self.evidence_refs),
            "recorded_by": self.recorded_by,
            "created_at_utc": self.created_at_utc,
        }


def validate_dataset_semantics(
    dataset: DatasetSemanticsRecord,
    *,
    use_context: ValidationUseContext | RuntimeStatus | str,
) -> MarketDataDecision:
    violations: list[MarketDataViolation] = []
    context = _value(use_context)
    if context == ValidationUseContext.CONFIRMATORY_VALIDATION.value:
        for field_name in ("known_at_ref", "effective_at_ref", "pit_bitemporal_rules_ref"):
            if not _present(getattr(dataset, field_name)):
                violations.append(
                    MarketDataViolation(
                        "dataset_missing_pit_semantics",
                        "confirmatory validation requires known_at, effective_at, and PIT/bitemporal rules",
                        field=field_name,
                        ref=dataset.dataset_ref,
                    )
                )
    for field_name in ("source_ref", "version", "quality_status", "freshness_status", "checksum"):
        if not _present(getattr(dataset, field_name)):
            violations.append(
                MarketDataViolation(
                    f"missing_{field_name}",
                    f"{field_name} is required before dataset use",
                    field=field_name,
                    ref=dataset.dataset_ref,
                )
            )
    if not dataset.lineage_refs:
        violations.append(
            MarketDataViolation(
                "missing_lineage_refs",
                "dataset lineage is required before research use",
                field="lineage_refs",
                ref=dataset.dataset_ref,
            )
        )
    return MarketDataDecision(accepted=not violations, violations=tuple(violations))


def validate_instrument_spec(instrument: InstrumentSpec) -> MarketDataDecision:
    violations: list[MarketDataViolation] = []
    if not _present(instrument.exchange_calendar_ref):
        violations.append(
            MarketDataViolation(
                "missing_exchange_calendar",
                "InstrumentSpec requires exchange calendar",
                field="exchange_calendar_ref",
                ref=instrument.instrument_ref,
            )
        )
    if instrument.instrument_type.lower() == "option":
        for field_name in ("expiry_ref", "strike_ref", "contract_multiplier_ref", "settlement_ref"):
            if not _present(getattr(instrument, field_name)):
                violations.append(
                    MarketDataViolation(
                        "option_semantics_incomplete",
                        "option strategies require expiry, strike, multiplier, and settlement",
                        field=field_name,
                        ref=instrument.instrument_ref,
                    )
                )
    if instrument.instrument_type.lower() in {"future", "futures", "perpetual"}:
        if not _present(instrument.margin_ref):
            violations.append(
                MarketDataViolation(
                    "futures_margin_missing",
                    "futures/perpetual instruments require margin semantics",
                    field="margin_ref",
                    ref=instrument.instrument_ref,
                )
            )
    return MarketDataDecision(accepted=not violations, violations=tuple(violations))


def validate_market_data_use(request: MarketDataUseRequest) -> MarketDataDecision:
    violations: list[MarketDataViolation] = []
    context = _value(request.use_context)

    for dataset in request.datasets:
        violations.extend(validate_dataset_semantics(dataset, use_context=context).violations)
    for instrument in request.instruments:
        violations.extend(validate_instrument_spec(instrument).violations)
    violations.extend(_validate_capability_matrix(request.capability_matrix, context).violations)
    violations.extend(_validate_cross_currency(request).violations)
    for claim in request.transformation_claims:
        violations.extend(validate_data_transformation_claim(claim).violations)

    return MarketDataDecision(accepted=not violations, violations=tuple(violations))


def validate_market_capability_matrix(
    matrix: MarketCapabilityMatrixRecord,
    *,
    use_context: ValidationUseContext | RuntimeStatus | str = ValidationUseContext.RESEARCH,
) -> MarketDataDecision:
    return _validate_capability_matrix(matrix, _value(use_context))


def _validate_capability_matrix(
    matrix: MarketCapabilityMatrixRecord,
    context: str,
) -> MarketDataDecision:
    violations: list[MarketDataViolation] = []
    context_to_flag = {
        ValidationUseContext.RESEARCH.value: matrix.research,
        ValidationUseContext.BACKTEST.value: matrix.backtest,
        ValidationUseContext.CONFIRMATORY_VALIDATION.value: matrix.backtest,
        ValidationUseContext.PAPER.value: matrix.paper,
        ValidationUseContext.TESTNET.value: matrix.testnet,
        ValidationUseContext.LIVE.value: matrix.live,
        RuntimeStatus.LIVE.value: matrix.live,
        RuntimeStatus.PAPER.value: matrix.paper,
        RuntimeStatus.TESTNET.value: matrix.testnet,
    }
    if context in {ValidationUseContext.LIVE.value, RuntimeStatus.LIVE.value}:
        if str(matrix.asset_class).lower() in {"a_share", "equity_cn", "stocks_cn", "cn_equity"}:
            violations.append(
                MarketDataViolation(
                    "a_share_live_forbidden",
                    "A-share instruments are research/backtest/paper only in current scope",
                    field="asset_class",
                    ref=matrix.matrix_ref,
                )
            )
        if not matrix.live or not _present(matrix.permission_requirement):
            violations.append(
                MarketDataViolation(
                    "live_capability_missing",
                    "live use requires MarketCapabilityMatrix.live and permission_requirement",
                    field="live",
                    ref=matrix.matrix_ref,
                )
            )
    elif context in context_to_flag and not context_to_flag[context]:
        violations.append(
            MarketDataViolation(
                "market_capability_unavailable",
                f"MarketCapabilityMatrix does not allow {context}",
                field=context,
                ref=matrix.matrix_ref,
            )
        )
    for field_name in ("data_availability", "cost_model_availability", "execution_availability"):
        if not _present(getattr(matrix, field_name)):
            violations.append(
                MarketDataViolation(
                    f"missing_{field_name}",
                    f"{field_name} is required in MarketCapabilityMatrix",
                    field=field_name,
                    ref=matrix.matrix_ref,
                )
            )
    return MarketDataDecision(accepted=not violations, violations=tuple(violations))


def _validate_cross_currency(request: MarketDataUseRequest) -> MarketDataDecision:
    currencies = {str(instr.currency).upper() for instr in request.instruments if _present(instr.currency)}
    violations: list[MarketDataViolation] = []
    if len(currencies) <= 1:
        return MarketDataDecision(accepted=True, violations=())
    cap = request.capital_record
    if cap is None or not _present(cap.base_currency) or not _present(cap.fx_conversion_ref):
        violations.append(
            MarketDataViolation(
                "cross_currency_capital_missing",
                "cross-currency strategies require base_currency and FX conversion",
                field="capital_record",
                ref=request.request_ref,
            )
        )
    return MarketDataDecision(accepted=not violations, violations=tuple(violations))


def validate_data_transformation_claim(claim: DataTransformationClaim) -> MarketDataDecision:
    violations: list[MarketDataViolation] = []
    if claim.claims_theory_correct:
        for field_name in ("formula_ref", "unit_binding_ref", "timing_binding_ref"):
            if not _present(getattr(claim, field_name)):
                violations.append(
                    MarketDataViolation(
                        "transformation_theory_binding_missing",
                        "theory-correct data transformations require formula, unit, and timing bindings",
                        field=field_name,
                        ref=claim.transform_ref,
                    )
                )
    return MarketDataDecision(accepted=not violations, violations=tuple(violations))


def validate_market_data_use_validation_record(record: MarketDataUseValidationRecord) -> MarketDataDecision:
    violations: list[MarketDataViolation] = []
    for field_name in ("validation_ref", "request_ref", "use_context", "capability_matrix_ref", "recorded_by", "created_at_utc"):
        if not _present(getattr(record, field_name)):
            violations.append(
                MarketDataViolation(
                    f"missing_{field_name}",
                    f"{field_name} is required in MarketDataUseValidationRecord",
                    field=field_name,
                    ref=record.validation_ref,
                )
            )
    if not record.dataset_refs:
        violations.append(
            MarketDataViolation(
                "market_data_use_missing_dataset_refs",
                "market data use validation requires dataset refs",
                field="dataset_refs",
                ref=record.validation_ref,
            )
        )
    if not record.instrument_refs:
        violations.append(
            MarketDataViolation(
                "market_data_use_missing_instrument_refs",
                "market data use validation requires instrument refs",
                field="instrument_refs",
                ref=record.validation_ref,
            )
        )
    if not record.accepted:
        violations.append(
            MarketDataViolation(
                "market_data_use_not_accepted",
                "only accepted market data use validations may be recorded",
                field="accepted",
                ref=record.validation_ref,
            )
        )
    if record.violation_codes:
        violations.append(
            MarketDataViolation(
                "market_data_use_has_violations",
                "accepted market data use validation cannot retain violation codes",
                field="violation_codes",
                ref=record.validation_ref,
            )
        )
    if not record.evidence_refs:
        violations.append(
            MarketDataViolation(
                "market_data_use_missing_evidence_refs",
                "market data use validation requires evidence refs",
                field="evidence_refs",
                ref=record.validation_ref,
            )
        )
    return MarketDataDecision(accepted=not violations, violations=tuple(violations))


def _required_str(data: dict[str, Any], field_name: str) -> str:
    value = data.get(field_name)
    if not _present(value):
        raise ValueError(f"{field_name} is required")
    return str(value)


def _optional_str(data: dict[str, Any], field_name: str) -> str | None:
    value = data.get(field_name)
    if value is None:
        return None
    return str(value)


def _required_bool(data: dict[str, Any], field_name: str) -> bool:
    value = data.get(field_name)
    if not isinstance(value, bool):
        raise ValueError(f"{field_name} must be boolean")
    return value


def _decision_message(decision: MarketDataDecision) -> str:
    return ",".join(violation.code for violation in decision.violations) or "market data record rejected"


def dataset_semantics_record_from_dict(data: dict[str, Any]) -> DatasetSemanticsRecord:
    return DatasetSemanticsRecord(
        dataset_ref=_required_str(data, "dataset_ref"),
        source_ref=_required_str(data, "source_ref"),
        version=_required_str(data, "version"),
        known_at_ref=_optional_str(data, "known_at_ref"),
        effective_at_ref=_optional_str(data, "effective_at_ref"),
        pit_bitemporal_rules_ref=_optional_str(data, "pit_bitemporal_rules_ref"),
        quality_status=_required_str(data, "quality_status"),
        lineage_refs=tuple(str(ref) for ref in _tuple(data.get("lineage_refs")) if _present(ref)),
        freshness_status=_required_str(data, "freshness_status"),
        checksum=_optional_str(data, "checksum"),
        sampling_rule_ref=_optional_str(data, "sampling_rule_ref"),
        adjustment_formula_ref=_optional_str(data, "adjustment_formula_ref"),
        asof_join_rule_ref=_optional_str(data, "asof_join_rule_ref"),
        missingness_model_ref=_optional_str(data, "missingness_model_ref"),
        survivorship_rule_ref=_optional_str(data, "survivorship_rule_ref"),
    )


def instrument_spec_from_dict(data: dict[str, Any]) -> InstrumentSpec:
    return InstrumentSpec(
        instrument_ref=_required_str(data, "instrument_ref"),
        asset_class=_required_str(data, "asset_class"),
        instrument_type=_required_str(data, "instrument_type"),
        currency=_required_str(data, "currency"),
        exchange_calendar_ref=_optional_str(data, "exchange_calendar_ref"),
        contract_spec_ref=_optional_str(data, "contract_spec_ref"),
        option_chain_ref=_optional_str(data, "option_chain_ref"),
        futures_roll_rule_ref=_optional_str(data, "futures_roll_rule_ref"),
        continuous_contract_rule_ref=_optional_str(data, "continuous_contract_rule_ref"),
        corporate_actions_ref=_optional_str(data, "corporate_actions_ref"),
        symbol_mapping_ref=_optional_str(data, "symbol_mapping_ref"),
        expiry_ref=_optional_str(data, "expiry_ref"),
        strike_ref=_optional_str(data, "strike_ref"),
        contract_multiplier_ref=_optional_str(data, "contract_multiplier_ref"),
        settlement_ref=_optional_str(data, "settlement_ref"),
        exercise_style_ref=_optional_str(data, "exercise_style_ref"),
        margin_ref=_optional_str(data, "margin_ref"),
    )


def market_capability_matrix_record_from_dict(data: dict[str, Any]) -> MarketCapabilityMatrixRecord:
    return MarketCapabilityMatrixRecord(
        matrix_ref=_required_str(data, "matrix_ref"),
        asset_class=_required_str(data, "asset_class"),
        instrument_type=_required_str(data, "instrument_type"),
        research=_required_bool(data, "research"),
        backtest=_required_bool(data, "backtest"),
        paper=_required_bool(data, "paper"),
        testnet=_required_bool(data, "testnet"),
        live=_required_bool(data, "live"),
        long=_required_bool(data, "long"),
        short=_required_bool(data, "short"),
        leverage=_required_bool(data, "leverage"),
        options=_required_bool(data, "options"),
        margin=_required_bool(data, "margin"),
        borrow=_required_bool(data, "borrow"),
        data_availability=_optional_str(data, "data_availability"),
        cost_model_availability=_optional_str(data, "cost_model_availability"),
        execution_availability=_optional_str(data, "execution_availability"),
        permission_requirement=_optional_str(data, "permission_requirement"),
    )


def cross_currency_capital_record_from_dict(data: dict[str, Any] | None) -> CrossCurrencyCapitalRecord | None:
    if data is None:
        return None
    if not isinstance(data, dict):
        raise ValueError("capital_record must be an object")
    return CrossCurrencyCapitalRecord(
        base_currency=_optional_str(data, "base_currency"),
        fx_conversion_ref=_optional_str(data, "fx_conversion_ref"),
        collateral_ref=_optional_str(data, "collateral_ref"),
        margin_ref=_optional_str(data, "margin_ref"),
        leverage_ref=_optional_str(data, "leverage_ref"),
        net_exposure_ref=_optional_str(data, "net_exposure_ref"),
        gross_exposure_ref=_optional_str(data, "gross_exposure_ref"),
        capital_allocation_ref=_optional_str(data, "capital_allocation_ref"),
        financing_cost_ref=_optional_str(data, "financing_cost_ref"),
    )


def data_transformation_claim_from_dict(data: dict[str, Any]) -> DataTransformationClaim:
    return DataTransformationClaim(
        transform_ref=_required_str(data, "transform_ref"),
        claims_theory_correct=_required_bool(data, "claims_theory_correct"),
        formula_ref=_optional_str(data, "formula_ref"),
        unit_binding_ref=_optional_str(data, "unit_binding_ref"),
        timing_binding_ref=_optional_str(data, "timing_binding_ref"),
    )


def market_data_use_validation_record_from_dict(data: dict[str, Any]) -> MarketDataUseValidationRecord:
    return MarketDataUseValidationRecord(
        validation_ref=_required_str(data, "validation_ref"),
        request_ref=_required_str(data, "request_ref"),
        use_context=_required_str(data, "use_context"),
        dataset_refs=tuple(str(ref) for ref in _tuple(data.get("dataset_refs")) if _present(ref)),
        instrument_refs=tuple(str(ref) for ref in _tuple(data.get("instrument_refs")) if _present(ref)),
        capability_matrix_ref=_required_str(data, "capability_matrix_ref"),
        capital_record_ref=_optional_str(data, "capital_record_ref"),
        transformation_refs=tuple(str(ref) for ref in _tuple(data.get("transformation_refs")) if _present(ref)),
        accepted=_required_bool(data, "accepted"),
        violation_codes=tuple(str(code) for code in _tuple(data.get("violation_codes")) if _present(code)),
        evidence_refs=tuple(str(ref) for ref in _tuple(data.get("evidence_refs")) if _present(ref)),
        recorded_by=_required_str(data, "recorded_by"),
        created_at_utc=_required_str(data, "created_at_utc"),
    )


class PersistentMarketDataRegistry:
    """Append-only GOAL §11 metadata registry.

    This records dataset semantics, instrument specs, and capability matrices as
    refs and metadata only. It does not store raw market data rows, provider
    payloads, credentials, or connector results.
    """

    def __init__(self, path: str | Path | None = None) -> None:
        self._path = Path(path) if path is not None else None
        self._datasets: dict[str, DatasetSemanticsRecord] = {}
        self._instruments: dict[str, InstrumentSpec] = {}
        self._capability_matrices: dict[str, MarketCapabilityMatrixRecord] = {}
        self._use_validations: dict[str, MarketDataUseValidationRecord] = {}
        if self._path is not None:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            self._load_existing()

    @property
    def path(self) -> Path | None:
        return self._path

    def _load_existing(self) -> None:
        assert self._path is not None
        if not self._path.exists():
            return
        for line_no, line in enumerate(self._path.read_text(encoding="utf-8").splitlines(), start=1):
            if not line.strip():
                continue
            try:
                row = json.loads(line)
                self._apply_row(row, persist=False)
            except Exception as exc:  # noqa: BLE001 - corrupt market-data history must block startup.
                raise ValueError(f"invalid persisted market data row at {self._path}:{line_no}") from exc

    def _append(self, row: dict[str, Any]) -> None:
        if self._path is None:
            return
        with self._path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n")

    def _apply_row(self, row: dict[str, Any], *, persist: bool) -> None:
        if row.get("schema_version") != 1:
            raise ValueError("unsupported market data schema_version")
        event_type = str(row.get("event_type") or "")
        use_context = str(row.get("use_context") or ValidationUseContext.RESEARCH.value)
        if event_type == "dataset_semantics_recorded":
            payload = row.get("dataset")
            if not isinstance(payload, dict):
                raise ValueError("market data event missing dataset")
            self._record_dataset(dataset_semantics_record_from_dict(payload), use_context=use_context, persist=persist)
            return
        if event_type == "instrument_spec_recorded":
            payload = row.get("instrument")
            if not isinstance(payload, dict):
                raise ValueError("market data event missing instrument")
            self._record_instrument(instrument_spec_from_dict(payload), persist=persist)
            return
        if event_type == "market_capability_matrix_recorded":
            payload = row.get("capability_matrix")
            if not isinstance(payload, dict):
                raise ValueError("market data event missing capability_matrix")
            self._record_capability_matrix(
                market_capability_matrix_record_from_dict(payload),
                use_context=use_context,
                persist=persist,
            )
            return
        if event_type == "market_data_use_validation_recorded":
            payload = row.get("use_validation")
            if not isinstance(payload, dict):
                raise ValueError("market data event missing use_validation")
            self._record_use_validation(market_data_use_validation_record_from_dict(payload), persist=persist)
            return
        raise ValueError(f"unknown market data event_type={event_type!r}")

    def record_dataset(
        self,
        record: DatasetSemanticsRecord,
        *,
        use_context: ValidationUseContext | RuntimeStatus | str = ValidationUseContext.RESEARCH,
    ) -> DatasetSemanticsRecord:
        return self._record_dataset(record, use_context=use_context, persist=True)

    def _record_dataset(
        self,
        record: DatasetSemanticsRecord,
        *,
        use_context: ValidationUseContext | RuntimeStatus | str,
        persist: bool,
    ) -> DatasetSemanticsRecord:
        decision = validate_dataset_semantics(record, use_context=use_context)
        if not decision.accepted:
            raise ValueError(_decision_message(decision))
        self._datasets[record.dataset_ref] = record
        if persist:
            self._append(
                {
                    "schema_version": 1,
                    "event_type": "dataset_semantics_recorded",
                    "use_context": _value(use_context),
                    "dataset": record.to_dict(),
                }
            )
        return record

    def record_instrument(self, record: InstrumentSpec) -> InstrumentSpec:
        return self._record_instrument(record, persist=True)

    def _record_instrument(self, record: InstrumentSpec, *, persist: bool) -> InstrumentSpec:
        decision = validate_instrument_spec(record)
        if not decision.accepted:
            raise ValueError(_decision_message(decision))
        self._instruments[record.instrument_ref] = record
        if persist:
            self._append(
                {
                    "schema_version": 1,
                    "event_type": "instrument_spec_recorded",
                    "instrument": record.to_dict(),
                }
            )
        return record

    def record_capability_matrix(
        self,
        record: MarketCapabilityMatrixRecord,
        *,
        use_context: ValidationUseContext | RuntimeStatus | str = ValidationUseContext.RESEARCH,
    ) -> MarketCapabilityMatrixRecord:
        return self._record_capability_matrix(record, use_context=use_context, persist=True)

    def _record_capability_matrix(
        self,
        record: MarketCapabilityMatrixRecord,
        *,
        use_context: ValidationUseContext | RuntimeStatus | str,
        persist: bool,
    ) -> MarketCapabilityMatrixRecord:
        decision = validate_market_capability_matrix(record, use_context=use_context)
        if not decision.accepted:
            raise ValueError(_decision_message(decision))
        self._capability_matrices[record.matrix_ref] = record
        if persist:
            self._append(
                {
                    "schema_version": 1,
                    "event_type": "market_capability_matrix_recorded",
                    "use_context": _value(use_context),
                    "capability_matrix": record.to_dict(),
                }
            )
        return record

    def record_use_validation(self, record: MarketDataUseValidationRecord) -> MarketDataUseValidationRecord:
        return self._record_use_validation(record, persist=True)

    def _record_use_validation(
        self,
        record: MarketDataUseValidationRecord,
        *,
        persist: bool,
    ) -> MarketDataUseValidationRecord:
        decision = validate_market_data_use_validation_record(record)
        if not decision.accepted:
            raise ValueError(_decision_message(decision))
        missing_dataset_refs = [ref for ref in record.dataset_refs if ref not in self._datasets]
        if missing_dataset_refs:
            raise ValueError(f"unknown dataset refs: {','.join(missing_dataset_refs)}")
        missing_instrument_refs = [ref for ref in record.instrument_refs if ref not in self._instruments]
        if missing_instrument_refs:
            raise ValueError(f"unknown instrument refs: {','.join(missing_instrument_refs)}")
        if record.capability_matrix_ref not in self._capability_matrices:
            raise ValueError(f"unknown capability matrix ref: {record.capability_matrix_ref}")
        self._use_validations[record.validation_ref] = record
        if persist:
            self._append(
                {
                    "schema_version": 1,
                    "event_type": "market_data_use_validation_recorded",
                    "use_validation": record.to_dict(),
                }
            )
        return record

    def dataset(self, dataset_ref: str) -> DatasetSemanticsRecord:
        if dataset_ref not in self._datasets:
            raise KeyError(f"unknown dataset semantics record: {dataset_ref}")
        return self._datasets[dataset_ref]

    def instrument(self, instrument_ref: str) -> InstrumentSpec:
        if instrument_ref not in self._instruments:
            raise KeyError(f"unknown instrument spec: {instrument_ref}")
        return self._instruments[instrument_ref]

    def capability_matrix(self, matrix_ref: str) -> MarketCapabilityMatrixRecord:
        if matrix_ref not in self._capability_matrices:
            raise KeyError(f"unknown market capability matrix: {matrix_ref}")
        return self._capability_matrices[matrix_ref]

    def use_validation(self, validation_ref: str) -> MarketDataUseValidationRecord:
        if validation_ref not in self._use_validations:
            raise KeyError(f"unknown market data use validation: {validation_ref}")
        return self._use_validations[validation_ref]

    def datasets(self) -> list[DatasetSemanticsRecord]:
        return sorted(self._datasets.values(), key=lambda record: record.dataset_ref)

    def instruments(self) -> list[InstrumentSpec]:
        return sorted(self._instruments.values(), key=lambda record: record.instrument_ref)

    def capability_matrices(self) -> list[MarketCapabilityMatrixRecord]:
        return sorted(self._capability_matrices.values(), key=lambda record: record.matrix_ref)

    def use_validations(self) -> list[MarketDataUseValidationRecord]:
        return sorted(self._use_validations.values(), key=lambda record: record.validation_ref)


__all__ = [
    "CrossCurrencyCapitalRecord",
    "DataTransformationClaim",
    "DatasetSemanticsRecord",
    "InstrumentSpec",
    "MarketCapabilityMatrixRecord",
    "MarketDataDecision",
    "MarketDataUseRequest",
    "MarketDataUseValidationRecord",
    "MarketDataViolation",
    "PersistentMarketDataRegistry",
    "ValidationUseContext",
    "cross_currency_capital_record_from_dict",
    "data_transformation_claim_from_dict",
    "dataset_semantics_record_from_dict",
    "instrument_spec_from_dict",
    "market_capability_matrix_record_from_dict",
    "market_data_use_validation_record_from_dict",
    "validate_data_transformation_claim",
    "validate_dataset_semantics",
    "validate_instrument_spec",
    "validate_market_capability_matrix",
    "validate_market_data_use_validation_record",
    "validate_market_data_use",
]
