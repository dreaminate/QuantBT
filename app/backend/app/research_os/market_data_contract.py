"""GOAL §11 market data and instrument capability contracts.

两件标的本体在本模块**单一源**收口（C-S11：flat 升 Pydantic + 吸收 orphan 富能力 + 删 orphan）：
- `InstrumentSpec`（flat·Pydantic·frozen）= **LIVE 登记记录**（main.py + PersistentMarketDataRegistry）。
  原 17 个 `*_ref` 字段全保留 + additive typed 值字段；身份恒为 `instrument_ref`。
- `TypedInstrumentSpec` + 每资产类 typed 子类（EquitySpec/OptionSpec/…）+ 跨币种结算门
  （FxConversion / assert_currency_settleable / CrossCurrencyError）+ `parse_instrument_spec`。
  `spec_id` 内容寻址复用 `lineage.ids.content_hash`（同一哈希族），刻意排除装饰字段。
AssetClass / typed enums 在 `asset_class.py` 单一定义，本模块只引不重定义。
"""

from __future__ import annotations

import json
import os
import threading
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import Enum
from pathlib import Path
from typing import Annotated, Any, ClassVar, Literal, Union

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    TypeAdapter,
    ValidationError,
    model_validator,
)

from ..cross_process_lock import acquire_exclusive_fd
from ..lineage.ids import content_hash
from .asset_class import (
    AssetClass,
    DayCount,
    ExerciseStyle,
    OptionType,
    Settlement,
    SpecKind,
)
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


class InstrumentSpec(BaseModel):
    """GOAL §11 标的元数据登记记录（flat refs + additive typed 值）——**LIVE 单一源**。

    身份 = `instrument_ref`（PersistentMarketDataRegistry 的 key / use_validation 交叉引用锚点）。
    `asset_class`/`instrument_type`/`currency` 保持 **str**（非 Literal）：持久化历史里带
    'perpetual'/'cn_equity'/'a_share'/'equity_us'/'crypto' 等窄枚举外的值，收紧成 Literal 会在
    load 期 fail-closed → app 起不来（test_instrument_spec_consolidation read-back 锁此 hazard）。

    additive（C-S11 Commit 1·扩展不替换）：在原 17 个 flat `*_ref` 字段之上补 typed **值**字段
    （expiry/strike/contract_multiplier/settlement/roll_rule/coupon_rate/maturity/day_count），
    **仅当提供时** validator fire（strike>0 / multiplier>0 / settlement∈{physical,cash} …），
    **不强制 value-required**。`to_dict()` superset-stable（只 emit 原 17 keys + 有值的新字段）→
    `content_hash(record.to_dict())` 对既有记录零漂移（main.py record_hash 依赖）。
    """

    model_config = ConfigDict(frozen=True, extra="ignore")

    # ---- 原 17 个 flat 字段（name/type/order/default 全保留·零破坏）----
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

    # Exact venue order symbol.  Optional for legacy research-only records, but
    # mandatory at the live execution boundary so an ETH order cannot cite BTC
    # instrument evidence.
    venue_symbol: str | None = None

    # ---- additive typed 值字段（Optional·provided 时才 validate·JSON-native 防序列化炸）----
    expiry: str | None = None
    strike: float | None = Field(default=None, gt=0)
    contract_multiplier: float | None = Field(default=None, gt=0)
    settlement: Settlement | None = None
    roll_rule: str | None = None
    coupon_rate: float | None = Field(default=None, ge=0)
    maturity: str | None = None
    day_count: DayCount | None = None

    @property
    def spec_id(self) -> str:
        """内容寻址指纹（复用 lineage.ids.content_hash）作 **additive·非 PK**：instrument_ref 仍是
        登记身份/交叉引用锚点，绝不被 spec_id 取代。刻意**不入 to_dict()** → 不扰 record_hash。"""

        return "instr_" + content_hash(self.to_dict())[:12]

    def to_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {
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
        # additive 值字段：仅 emit 有值的（exclude None）→ superset-stable·既有记录 hash 零漂移
        for key in (
            "venue_symbol",
            "expiry",
            "strike",
            "contract_multiplier",
            "settlement",
            "roll_rule",
            "coupon_rate",
            "maturity",
            "day_count",
        ):
            value = getattr(self, key)
            if value is not None:
                data[key] = value
        return data


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
    """从 dict 还原 flat InstrumentSpec（持久化 replay + API 入口共用）。

    契约（main.py 422 catch · registry fail-closed 依赖）：
    - 缺/空 instrument_ref/asset_class/instrument_type/currency → **ValueError**（_required_str；
      纯 ValueError 不被下方 `except ValidationError` 吞，直接上抛）。
    - 17 个 flat 字段保 str 强转（与既有口径一致·旧数据含 perpetual/cn_equity 读得回·tolerant）。
    - additive 值字段 present 时由模型校验（strike>0 / settlement∈{…}），非法 → ValidationError
      （ValueError 子类）裹成 ValueError；absent→None→不入 to_dict。
    - 未知键忽略（只读已知键 + 模型 extra="ignore"）。
    """

    try:
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
            venue_symbol=_optional_str(data, "venue_symbol"),
            # additive 值字段：present 才读回（absent→None→不入 to_dict·零漂移）
            expiry=_optional_str(data, "expiry"),
            strike=data.get("strike"),
            contract_multiplier=data.get("contract_multiplier"),
            settlement=data.get("settlement"),
            roll_rule=_optional_str(data, "roll_rule"),
            coupon_rate=data.get("coupon_rate"),
            maturity=_optional_str(data, "maturity"),
            day_count=data.get("day_count"),
        )
    except ValidationError as exc:
        raise ValueError(f"invalid InstrumentSpec: {_summarize_validation_error(exc)}") from exc


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


def _stable_market_owner(value: Any) -> str:
    owner = str(value or "").strip()
    if not owner:
        raise ValueError("owner_user_id is required")
    return owner


def _market_record_key(owner_user_id: Any, record_ref: Any, *, field_name: str) -> tuple[str, str]:
    owner = _stable_market_owner(owner_user_id)
    ref = str(record_ref or "").strip()
    if not ref:
        raise ValueError(f"{field_name} is required")
    return owner, ref


@contextmanager
def _market_file_lock(lock_path: Path | None):
    if lock_path is None:
        yield
        return
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    lock_fd = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o600)
    held = None
    try:
        held = acquire_exclusive_fd(lock_fd, timeout_seconds=10.0)
        yield
    finally:
        if held is not None:
            held.release()
        os.close(lock_fd)


class PersistentMarketDataRegistry:
    """Owner-enveloped append-only GOAL §11 metadata registry.

    Dataset semantics, instrument specs, capability matrices, and use
    validations share one owner namespace because a use validation is valid only
    when every dependency resolves for the same stable user id. Schema-v1 rows
    have no stable owner evidence and are quarantined rather than inferred.
    """

    def __init__(self, path: str | Path | None = None) -> None:
        self._path = Path(path) if path is not None else None
        self._lock_path = (
            self._path.with_suffix(self._path.suffix + ".lock")
            if self._path is not None
            else None
        )
        self._lock = threading.RLock()
        self._datasets: dict[tuple[str, str], DatasetSemanticsRecord] = {}
        self._instruments: dict[tuple[str, str], InstrumentSpec] = {}
        self._capability_matrices: dict[tuple[str, str], MarketCapabilityMatrixRecord] = {}
        self._use_validations: dict[tuple[str, str], MarketDataUseValidationRecord] = {}
        self._event_rows: dict[tuple[str, str, str], str] = {}
        self._legacy_quarantined_count = 0
        if self._path is not None:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            self._load_existing()

    @property
    def path(self) -> Path | None:
        return self._path

    @property
    def legacy_quarantined_count(self) -> int:
        self._refresh_for_read()
        return self._legacy_quarantined_count

    @staticmethod
    def _encoded_row(row: dict[str, Any]) -> str:
        return json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":"))

    def _clear_replay_state(self) -> None:
        self._datasets.clear()
        self._instruments.clear()
        self._capability_matrices.clear()
        self._use_validations.clear()
        self._event_rows.clear()
        self._legacy_quarantined_count = 0

    def _load_existing(self) -> None:
        with self._lock, _market_file_lock(self._lock_path):
            self._reload_from_disk_locked()

    def _refresh_for_read(self) -> None:
        if self._path is None:
            return
        with self._lock, _market_file_lock(self._lock_path):
            self._reload_from_disk_locked()

    def _reload_from_disk_locked(self) -> None:
        self._clear_replay_state()
        if self._path is None or not self._path.exists():
            return
        with self._path.open("r", encoding="utf-8") as fh:
            for line_no, line in enumerate(fh, start=1):
                if not line.strip():
                    continue
                try:
                    row = json.loads(line)
                    if row.get("schema_version") == 1:
                        self._legacy_quarantined_count += 1
                        continue
                    self._replay_row(row)
                except Exception as exc:  # noqa: BLE001 - corrupt v2 history must block use.
                    self._clear_replay_state()
                    raise ValueError(f"invalid persisted market data row at {self._path}:{line_no}") from exc

    def _decode_validated_row(
        self,
        row: dict[str, Any],
    ) -> tuple[str, str, str, Any]:
        if row.get("schema_version") != 2:
            raise ValueError("unsupported or ownerless market data schema_version")
        owner = _stable_market_owner(row.get("owner_user_id"))
        event_type = str(row.get("event_type") or "")
        use_context = str(row.get("use_context") or ValidationUseContext.RESEARCH.value)

        if event_type == "dataset_semantics_recorded":
            payload = row.get("dataset")
            if not isinstance(payload, dict):
                raise ValueError("market data event missing dataset")
            record = dataset_semantics_record_from_dict(payload)
            decision = validate_dataset_semantics(record, use_context=use_context)
            ref = record.dataset_ref
        elif event_type == "instrument_spec_recorded":
            payload = row.get("instrument")
            if not isinstance(payload, dict):
                raise ValueError("market data event missing instrument")
            record = instrument_spec_from_dict(payload)
            decision = validate_instrument_spec(record)
            ref = record.instrument_ref
        elif event_type == "market_capability_matrix_recorded":
            payload = row.get("capability_matrix")
            if not isinstance(payload, dict):
                raise ValueError("market data event missing capability_matrix")
            record = market_capability_matrix_record_from_dict(payload)
            decision = validate_market_capability_matrix(record, use_context=use_context)
            ref = record.matrix_ref
        elif event_type == "market_data_use_validation_recorded":
            payload = row.get("use_validation")
            if not isinstance(payload, dict):
                raise ValueError("market data event missing use_validation")
            record = market_data_use_validation_record_from_dict(payload)
            decision = validate_market_data_use_validation_record(record)
            ref = record.validation_ref
            if record.recorded_by != owner:
                raise ValueError("MarketDataUseValidation recorded_by must match owner_user_id")
            missing_dataset_refs = [
                item for item in record.dataset_refs if (owner, item) not in self._datasets
            ]
            if missing_dataset_refs:
                raise ValueError(f"unknown same-owner dataset refs: {','.join(missing_dataset_refs)}")
            missing_instrument_refs = [
                item for item in record.instrument_refs if (owner, item) not in self._instruments
            ]
            if missing_instrument_refs:
                raise ValueError(f"unknown same-owner instrument refs: {','.join(missing_instrument_refs)}")
            if (owner, record.capability_matrix_ref) not in self._capability_matrices:
                raise ValueError(
                    f"unknown same-owner capability matrix ref: {record.capability_matrix_ref}"
                )
        else:
            raise ValueError(f"unknown market data event_type={event_type!r}")

        if not decision.accepted:
            raise ValueError(_decision_message(decision))
        ref = str(ref or "").strip()
        if not ref:
            raise ValueError("owner-enveloped market data record ref is required")
        return owner, event_type, ref, record

    def _insert_decoded(self, owner: str, event_type: str, ref: str, record: Any) -> None:
        key = (owner, ref)
        if event_type == "dataset_semantics_recorded":
            self._datasets[key] = record
        elif event_type == "instrument_spec_recorded":
            self._instruments[key] = record
        elif event_type == "market_capability_matrix_recorded":
            self._capability_matrices[key] = record
        else:
            self._use_validations[key] = record

    def _replay_row(self, row: dict[str, Any]) -> Any:
        owner, event_type, ref, record = self._decode_validated_row(row)
        event_key = (owner, event_type, ref)
        encoded = self._encoded_row(row)
        existing = self._event_rows.get(event_key)
        if existing is not None:
            if existing == encoded:
                return record
            raise ValueError(
                f"owner-enveloped market data record collision owner={owner!r} ref={ref!r}"
            )
        self._insert_decoded(owner, event_type, ref, record)
        self._event_rows[event_key] = encoded
        return record

    def _write_row(self, row: dict[str, Any]) -> Any:
        with self._lock, _market_file_lock(self._lock_path):
            if self._path is not None:
                self._reload_from_disk_locked()
            owner, event_type, ref, record = self._decode_validated_row(row)
            event_key = (owner, event_type, ref)
            encoded = self._encoded_row(row)
            existing = self._event_rows.get(event_key)
            if existing is not None:
                if existing == encoded:
                    return record
                raise ValueError(
                    f"owner-enveloped market data record collision owner={owner!r} ref={ref!r}"
                )
            if self._path is not None:
                with self._path.open("a", encoding="utf-8") as fh:
                    fh.write(encoded + "\n")
                    fh.flush()
                    os.fsync(fh.fileno())
            self._insert_decoded(owner, event_type, ref, record)
            self._event_rows[event_key] = encoded
            return record

    def record_dataset(
        self,
        record: DatasetSemanticsRecord,
        *,
        owner_user_id: str,
        use_context: ValidationUseContext | RuntimeStatus | str = ValidationUseContext.RESEARCH,
    ) -> DatasetSemanticsRecord:
        owner = _stable_market_owner(owner_user_id)
        return self._write_row(
            {
                "schema_version": 2,
                "event_type": "dataset_semantics_recorded",
                "owner_user_id": owner,
                "use_context": _value(use_context),
                "dataset": record.to_dict(),
            }
        )

    def record_instrument(
        self,
        record: InstrumentSpec,
        *,
        owner_user_id: str,
    ) -> InstrumentSpec:
        owner = _stable_market_owner(owner_user_id)
        return self._write_row(
            {
                "schema_version": 2,
                "event_type": "instrument_spec_recorded",
                "owner_user_id": owner,
                "instrument": record.to_dict(),
            }
        )

    def record_capability_matrix(
        self,
        record: MarketCapabilityMatrixRecord,
        *,
        owner_user_id: str,
        use_context: ValidationUseContext | RuntimeStatus | str = ValidationUseContext.RESEARCH,
    ) -> MarketCapabilityMatrixRecord:
        owner = _stable_market_owner(owner_user_id)
        return self._write_row(
            {
                "schema_version": 2,
                "event_type": "market_capability_matrix_recorded",
                "owner_user_id": owner,
                "use_context": _value(use_context),
                "capability_matrix": record.to_dict(),
            }
        )

    def record_use_validation(
        self,
        record: MarketDataUseValidationRecord,
        *,
        owner_user_id: str,
    ) -> MarketDataUseValidationRecord:
        owner = _stable_market_owner(owner_user_id)
        return self._write_row(
            {
                "schema_version": 2,
                "event_type": "market_data_use_validation_recorded",
                "owner_user_id": owner,
                "use_validation": record.to_dict(),
            }
        )

    def dataset(self, dataset_ref: str, *, owner_user_id: str) -> DatasetSemanticsRecord:
        self._refresh_for_read()
        key = _market_record_key(owner_user_id, dataset_ref, field_name="dataset_ref")
        if key not in self._datasets:
            raise KeyError(f"unknown dataset semantics record: {dataset_ref}")
        return self._datasets[key]

    def instrument(self, instrument_ref: str, *, owner_user_id: str) -> InstrumentSpec:
        self._refresh_for_read()
        key = _market_record_key(owner_user_id, instrument_ref, field_name="instrument_ref")
        if key not in self._instruments:
            raise KeyError(f"unknown instrument spec: {instrument_ref}")
        return self._instruments[key]

    def capability_matrix(
        self,
        matrix_ref: str,
        *,
        owner_user_id: str,
    ) -> MarketCapabilityMatrixRecord:
        self._refresh_for_read()
        key = _market_record_key(owner_user_id, matrix_ref, field_name="matrix_ref")
        if key not in self._capability_matrices:
            raise KeyError(f"unknown market capability matrix: {matrix_ref}")
        return self._capability_matrices[key]

    def use_validation(
        self,
        validation_ref: str,
        *,
        owner_user_id: str,
    ) -> MarketDataUseValidationRecord:
        self._refresh_for_read()
        key = _market_record_key(owner_user_id, validation_ref, field_name="validation_ref")
        if key not in self._use_validations:
            raise KeyError(f"unknown market data use validation: {validation_ref}")
        return self._use_validations[key]

    def datasets(self, *, owner_user_id: str) -> list[DatasetSemanticsRecord]:
        self._refresh_for_read()
        owner = _stable_market_owner(owner_user_id)
        return sorted(
            (record for (record_owner, _), record in self._datasets.items() if record_owner == owner),
            key=lambda record: record.dataset_ref,
        )

    def instruments(self, *, owner_user_id: str) -> list[InstrumentSpec]:
        self._refresh_for_read()
        owner = _stable_market_owner(owner_user_id)
        return sorted(
            (record for (record_owner, _), record in self._instruments.items() if record_owner == owner),
            key=lambda record: record.instrument_ref,
        )

    def capability_matrices(self, *, owner_user_id: str) -> list[MarketCapabilityMatrixRecord]:
        self._refresh_for_read()
        owner = _stable_market_owner(owner_user_id)
        return sorted(
            (
                record
                for (record_owner, _), record in self._capability_matrices.items()
                if record_owner == owner
            ),
            key=lambda record: record.matrix_ref,
        )

    def use_validations(self, *, owner_user_id: str) -> list[MarketDataUseValidationRecord]:
        self._refresh_for_read()
        owner = _stable_market_owner(owner_user_id)
        return sorted(
            (
                record
                for (record_owner, _), record in self._use_validations.items()
                if record_owner == owner
            ),
            key=lambda record: record.validation_ref,
        )


# ════════════════════════════════════════════════════════════════════════════════════════════
# §11 typed 合约本体（吸收自原 instruments/spec.py·orphan 已删·此处单一源）
#
# 与上方 flat `InstrumentSpec`（LIVE 登记记录）正交并存：flat 承载 `*_ref` 元数据 + additive 值，
# typed 这层按 spec_kind 派发每资产类的 typed 合约字段（构造期可证伪门）+ 跨币种结算门。
# 基类刻意命名 `TypedInstrumentSpec`（≠ flat `InstrumentSpec`），避免单模块内 InstrumentSpec 撞名。
# `spec_id` 内容寻址复用 `lineage.ids.content_hash`（同一哈希族），排除装饰字段（改名不算新标的）。
# ════════════════════════════════════════════════════════════════════════════════════════════
class InstrumentSpecError(ValueError):
    """typed 合约不完整 / 资产类不匹配 / 解析失败（构造期拒，绝不静默放过半成品 spec）。"""


class CrossCurrencyError(InstrumentSpecError):
    """跨币种结算缺 base currency / FX conversion / 桥接不匹配（§11 跨市场资本账可证伪门）。"""


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


# ── 跨币种结算（§11 跨市场资本账：base currency + FX conversion）──
class FxConversion(BaseModel):
    """一条币种换算声明（base ↔ quote）——`assert_currency_settleable` 的桥接凭据。

    诚实：本对象只**声明**换算来源/口径（rate_source 必填），是否真取到汇率、用哪个时点，
    由数据层落实；本模块绝不自己取汇率。`conversion_rate` 是可选钉值（缺则按 rate_source 实时取）。
    """

    base_currency: str = Field(..., min_length=1, description="记账本币（账户/组合 base）")
    quote_currency: str = Field(..., min_length=1, description="标的计价币（instrument quote）")
    rate_source: str = Field(..., min_length=1, description="汇率来源/口径（如 ecb_daily / binance_spot）——必填，缺则无据")
    conversion_rate: float | None = Field(None, gt=0, description="钉死的换算率（可选；缺则按 rate_source 实时取）")
    as_of: datetime | None = Field(None, description="该换算率的 as-of 时点（PIT）")

    def assert_bridges(self, quote: str, base: str) -> None:
        """校验本换算确实桥接 quote↔base（无序对匹配；汇率可逆，方向不挑）。不匹配即拒。"""

        declared = {self.base_currency.strip().upper(), self.quote_currency.strip().upper()}
        wanted = {(quote or "").strip().upper(), (base or "").strip().upper()}
        if declared != wanted:
            raise CrossCurrencyError(
                f"FX conversion 桥接不匹配：声明 {sorted(declared)}，需要 {sorted(wanted)}"
            )


# ── typed 合约基类（共享身份 / PIT / 血统 / 跨币种门）──
class TypedInstrumentSpec(BaseModel):
    """可交易标的的 typed 合约基类——共享身份、PIT、血统、跨币种结算门。

    身份 `spec_id` 内容寻址自结构性字段（spec_kind/symbol/asset_class/market/quote_currency +
    各子类 typed 字段），排除装饰字段（name/description/时间戳）。`spec_ref` 即下游
    `instrument_spec_ref`（strategy_book.ShortExecutionRequirement / Forecast）回填用的字符串。
    """

    model_config = ConfigDict(arbitrary_types_allowed=True)

    # 子类用 Literal 覆盖此处的 ALLOWED_ASSET_CLASSES（空集=不限）。
    ALLOWED_ASSET_CLASSES: ClassVar[frozenset[str]] = frozenset()

    spec_kind: SpecKind = Field(..., description="结构判别式（discriminator）：决定有哪些 typed 字段")
    symbol: str = Field(..., min_length=1, description="标的代码（如 510300.SH / BTC-USDT / ES）")
    asset_class: AssetClass = Field(..., description="§0 资产类 token")
    quote_currency: str = Field(..., min_length=1, description="标的计价/结算币（如 CNY/USD/USDT）")
    market: str = Field("", description="市场/场所 region key（如 CN/US/BINANCE/CME）——matrix 寻址 + 诚实标注")
    exchange: str | None = Field(None, description="交易所")
    calendar_ref: str | None = Field(None, description="交易日历引用（exchange calendar）")
    # PIT / 血统（§11）——本 spec 版本何时可知/生效 + 回指数据层血统。
    known_at: datetime | None = Field(None, description="known_at：本 spec 版本何时可知（PIT；公司行动/合约变更）")
    effective_at: datetime | None = Field(None, description="effective_at：本 spec 何时起生效")
    source_lineage_ref: str | None = Field(None, description="回指数据层 dataset/lineage（source lineage）")
    theory_binding_ref: str | None = Field(None, description="§9 spine 前向槽：TheoryImplementationBinding 引用（无新公式则空）")
    name: str = Field("", description="可读名（装饰，不入身份）")
    description: str = Field("", description="说明（装饰，不入身份）")
    spec_id: str = Field("", description="内容寻址身份；留空则按结构字段自动计算")
    created_at_utc: str = Field(default_factory=_now_iso)

    @model_validator(mode="after")
    def _finalize(self) -> "TypedInstrumentSpec":
        allowed = type(self).ALLOWED_ASSET_CLASSES
        if allowed and self.asset_class not in allowed:
            raise InstrumentSpecError(
                f"{type(self).__name__} 的 asset_class 必须 ∈ {sorted(allowed)}，得到 {self.asset_class!r}"
            )
        if not self.spec_id:
            structural = self.model_dump(
                mode="json",
                exclude={"name", "description", "spec_id", "created_at_utc"},
            )
            self.spec_id = "instr_" + content_hash(structural)[:12]
        return self

    @property
    def spec_ref(self) -> str:
        """下游 `instrument_spec_ref` 回填用字符串（= spec_id；非空即可被 strategy_book 引用门接受）。"""

        return self.spec_id

    # ----- 跨币种结算门（§11 跨市场资本账可证伪验收：缺 base currency / FX conversion → 拒）-----
    def needs_fx(self, base_currency: str | None) -> bool:
        """本标的相对账户 base currency 是否需要换汇（计价币 ≠ base 即需要）。"""

        if not base_currency or not str(base_currency).strip():
            return True  # 连 base 都没有 → 必然需要先有 base 才能谈
        return self.quote_currency.strip().upper() != base_currency.strip().upper()

    def assert_currency_settleable(
        self, *, base_currency: str | None, conversion: FxConversion | None = None
    ) -> None:
        """跨币种结算可证伪门（§11）。违一条即 CrossCurrencyError，绝不静默放过脏账。

          · 缺 base currency（账户本币未声明）→ 拒（无法记账）。
          · 计价币 ≠ base 且缺 FX conversion → 拒（缺 currency conversion）。
          · 提供了 conversion 但桥接不上（币对不匹配）→ 拒（伪换算）。
          · 计价币 == base（同币种）→ 放（无需换汇）。
        """

        if not base_currency or not str(base_currency).strip():
            raise CrossCurrencyError(
                f"标的 {self.symbol!r}（计价 {self.quote_currency}）跨币种结算缺 base currency："
                "账户本币未声明，无法记账（§11 跨市场资本账）"
            )
        qc = self.quote_currency.strip().upper()
        bc = base_currency.strip().upper()
        if qc == bc:
            return
        if conversion is None:
            raise CrossCurrencyError(
                f"跨币种 {qc}->{bc} 缺 FX conversion（标的 {self.symbol!r}）：缺 currency conversion，拒（§11）"
            )
        conversion.assert_bridges(quote=qc, base=bc)


# ── 每资产类 typed 子类（§11 语义 → typed 字段）──
class EquitySpec(TypedInstrumentSpec):
    """股票/指数/ETF/基金（cash equity-like）。"""

    ALLOWED_ASSET_CLASSES: ClassVar[frozenset[str]] = frozenset(
        {"equity", "equity_cn", "index", "etf", "fund"}
    )
    spec_kind: Literal["equity"] = "equity"
    lot_size: int = Field(1, gt=0, description="最小交易单位（A股=100）")
    is_etf: bool = Field(False, description="是否 ETF")
    underlying_index_ref: str | None = Field(None, description="跟踪指数引用（ETF/指数衍生）")
    board: str | None = Field(None, description="板块（主板/科创板/创业板…）")


class BondSpec(TypedInstrumentSpec):
    """债券/利率（§11：duration/convexity/yield curve/accrued interest/coupon/maturity/day count）。

    duration/convexity 是**声明值**（风险度量字段），非本模块推导的新公式。
    """

    ALLOWED_ASSET_CLASSES: ClassVar[frozenset[str]] = frozenset({"bond", "rate"})
    spec_kind: Literal["bond"] = "bond"
    coupon_rate: float = Field(..., ge=0, description="票息率（年化比率；零息=0）")
    maturity: datetime = Field(..., description="到期日（maturity）")
    day_count: DayCount = Field(..., description="计息基准（day count）")
    face_value: float = Field(100.0, gt=0, description="面值")
    coupon_frequency: int = Field(2, ge=0, description="年付息次数（0=零息）")
    duration: float | None = Field(None, ge=0, description="久期（声明值；modified/Macaulay）")
    convexity: float | None = Field(None, description="凸性（声明值）")
    accrued_interest: float | None = Field(None, ge=0, description="应计利息（声明值）")
    yield_curve_ref: str | None = Field(None, description="收益率曲线引用")


class FutureSpec(TypedInstrumentSpec):
    """期货（§11：roll rule/margin/settlement/contract multiplier/delivery/continuous contract）。"""

    ALLOWED_ASSET_CLASSES: ClassVar[frozenset[str]] = frozenset({"futures", "commodity", "rate"})
    spec_kind: Literal["future"] = "future"
    expiry: datetime = Field(..., description="合约到期日")
    contract_multiplier: float = Field(..., gt=0, description="合约乘数")
    settlement: Settlement = Field(..., description="交割方式（physical/cash）")
    roll_rule: str = Field(..., min_length=1, description="移仓规则（如 n_days_before_expiry:5 / volume_oi_switch）")
    delivery: str | None = Field(None, description="交割说明")
    margin_requirement: float | None = Field(None, ge=0, description="保证金要求（比率或名义）")
    continuous_contract_rule: str | None = Field(None, description="连续合约构造（panama/ratio/none）")
    underlying_ref: str | None = Field(None, description="标的物引用")


class OptionSpec(TypedInstrumentSpec):
    """期权（§11：expiry/strike/contract multiplier/settlement/exercise style/assignment/margin）。

    可证伪门（§11）：**expiry/strike/contract_multiplier/settlement 四者缺一即构造期拒**
    （required field + Field(gt=0)；MUT 把任一改为可选即被 test_instrument_spec 抓红）。
    Greeks / IV surface / term structure 是**定价/风险引擎**产物（运行期），不在合约 spec 里——
    本模块绝不算它们（诚实边界），只钉合约条款。
    """

    ALLOWED_ASSET_CLASSES: ClassVar[frozenset[str]] = frozenset({"options", "crypto_option"})
    spec_kind: Literal["option"] = "option"
    expiry: datetime = Field(..., description="到期日（必填·缺即拒）")
    strike: float = Field(..., gt=0, description="行权价（必填·>0·缺即拒）")
    contract_multiplier: float = Field(..., gt=0, description="合约乘数（必填·>0·缺即拒）")
    settlement: Settlement = Field(..., description="交割方式 physical/cash（必填·缺即拒）")
    exercise_style: ExerciseStyle = Field(..., description="行权方式（european/american/bermudan）")
    option_type: OptionType = Field(..., description="call/put")
    underlying_ref: str = Field(..., min_length=1, description="标的物引用（必填）")
    margin_requirement: float | None = Field(None, ge=0, description="保证金要求（卖方）")


class FxSpec(TypedInstrumentSpec):
    """外汇（§11：base/quote/rollover/funding/holiday calendar/conversion rate）。

    quote_currency（基类）= quote_ccy（_sync_quote_ccy 强制一致），保证跨币种门口径不裂。
    """

    ALLOWED_ASSET_CLASSES: ClassVar[frozenset[str]] = frozenset({"fx"})
    spec_kind: Literal["fx"] = "fx"
    base_ccy: str = Field(..., min_length=3, max_length=3, description="基准货币（如 EUR）")
    quote_ccy: str = Field(..., min_length=3, max_length=3, description="计价货币（如 USD）")
    rollover: bool = Field(True, description="是否隔夜滚动（rollover/swap 适用）")
    funding_basis: str | None = Field(None, description="融资/掉期基准（funding）")
    holiday_calendar_ref: str | None = Field(None, description="假期日历引用")
    pip_size: float = Field(0.0001, gt=0, description="最小报价变动（pip）")

    @model_validator(mode="before")
    @classmethod
    def _sync_quote_ccy(cls, data: Any) -> Any:
        # FX 计价币 == quote_ccy。用 mode="before" 在字段校验前对齐，避免与基类 _finalize
        # （算 spec_id）的 after-validator 次序耦合（顺序无关，spec_id 必含正确 quote_currency）。
        if isinstance(data, dict):
            qq = str(data.get("quote_ccy", "")).strip().upper()
            if qq:
                existing = str(data.get("quote_currency", "")).strip().upper()
                if existing and existing != qq:
                    raise InstrumentSpecError(
                        f"FxSpec quote_currency({existing}) 必须 == quote_ccy({qq})"
                    )
                data = {**data, "quote_currency": qq}
        return data


class CommoditySpec(TypedInstrumentSpec):
    """商品（§11：storage/delivery/contract spec/seasonality/calendar spread）。

    商品多为期货载体：要 roll/连续合约用 FutureSpec(asset_class=commodity)；要 storage/季节性
    等商品专属字段用本类。两者按需选，文档化（不强制单选，避免误伤）。
    """

    ALLOWED_ASSET_CLASSES: ClassVar[frozenset[str]] = frozenset({"commodity"})
    spec_kind: Literal["commodity"] = "commodity"
    contract_multiplier: float = Field(..., gt=0, description="合约乘数")
    settlement: Settlement = Field("physical", description="交割方式")
    expiry: datetime | None = Field(None, description="到期日（现货商品可空）")
    storage_cost_bps: float | None = Field(None, ge=0, description="仓储成本 bps（storage）")
    delivery: str | None = Field(None, description="交割说明")
    seasonality: str | None = Field(None, description="季节性模式描述/引用")
    calendar_spread_ref: str | None = Field(None, description="跨期价差引用（calendar spread）")
    grade: str | None = Field(None, description="品级/质量（contract spec）")
    underlying_ref: str | None = Field(None, description="标的物引用")


class CryptoSpotSpec(TypedInstrumentSpec):
    """加密现货。"""

    ALLOWED_ASSET_CLASSES: ClassVar[frozenset[str]] = frozenset({"crypto_spot"})
    spec_kind: Literal["crypto_spot"] = "crypto_spot"
    base_asset: str | None = Field(None, description="基础资产（如 BTC）")
    min_qty: float = Field(0.0, ge=0, description="最小下单量")
    tick_size: float = Field(0.0, ge=0, description="最小价格变动")


class CryptoPerpSpec(TypedInstrumentSpec):
    """加密永续（funding/margin/leverage 语义；唯一可达 live 的资产类之一）。"""

    ALLOWED_ASSET_CLASSES: ClassVar[frozenset[str]] = frozenset({"crypto_perp"})
    spec_kind: Literal["crypto_perp"] = "crypto_perp"
    base_asset: str | None = Field(None, description="基础资产（如 BTC）")
    contract_multiplier: float = Field(1.0, gt=0, description="合约乘数")
    funding_interval_hours: int = Field(8, gt=0, description="资金费率结算间隔（小时）")
    funding_rate_ref: str | None = Field(None, description="资金费率来源引用")
    margin_requirement: float | None = Field(None, ge=0, description="保证金要求")
    max_leverage: float | None = Field(None, gt=0, description="最大杠杆（合约规则）")


class GenericInstrumentSpec(TypedInstrumentSpec):
    """自定义/未知可交易标的（§0「用户自定义」+「可以添加新内容」）。

    诚实：本类**无资产类专属 typed 门**，只承载自定义属性——不假装有期权/期货那样的结构校验。
    扩展点：新资产类应优先建专属子类（带 typed 门），GenericInstrumentSpec 是兜底不是默认。
    """

    ALLOWED_ASSET_CLASSES: ClassVar[frozenset[str]] = frozenset()  # 不限
    spec_kind: Literal["generic"] = "generic"
    attributes: dict[str, Any] = Field(default_factory=dict, description="自定义属性（无专属门）")


# ── 判别式联合 + 解析工厂（显式可证伪门：缺必填字段 → InstrumentSpecError）──
ConcreteInstrumentSpec = Union[
    EquitySpec, BondSpec, FutureSpec, OptionSpec, FxSpec,
    CommoditySpec, CryptoSpotSpec, CryptoPerpSpec, GenericInstrumentSpec,
]
AnyInstrumentSpec = Annotated[ConcreteInstrumentSpec, Field(discriminator="spec_kind")]
_SPEC_ADAPTER: TypeAdapter[TypedInstrumentSpec] = TypeAdapter(AnyInstrumentSpec)


def _summarize_validation_error(exc: ValidationError) -> str:
    parts: list[str] = []
    for err in exc.errors():
        loc = ".".join(str(p) for p in err.get("loc", ()))
        parts.append(f"{loc or '<root>'}: {err.get('msg', '')}")
    return "; ".join(parts) or str(exc)


def parse_instrument_spec(data: dict[str, Any]) -> TypedInstrumentSpec:
    """从 dict 解析 typed 合约（按 spec_kind 判别）。

    这是**显式可证伪门**：任一子类必填字段缺失/非法 → 统一抛 InstrumentSpecError（含缺项 loc）。
    期权缺 expiry/strike/contract_multiplier/settlement 走这里即拒（§11 可证伪验收）。
    """

    if not isinstance(data, dict) or not data.get("spec_kind"):
        raise InstrumentSpecError("parse_instrument_spec 需 dict 且含判别式 spec_kind")
    try:
        return _SPEC_ADAPTER.validate_python(data)
    except ValidationError as exc:
        raise InstrumentSpecError(
            f"InstrumentSpec({data.get('spec_kind')}) 解析失败（缺/非法字段）：{_summarize_validation_error(exc)}"
        ) from exc


__all__ = [
    # ---- flat 登记记录族（LIVE）----
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
    # ---- §11 typed 合约本体（吸收自 orphan·单一源）----
    "AnyInstrumentSpec",
    "AssetClass",
    "BondSpec",
    "CommoditySpec",
    "CrossCurrencyError",
    "CryptoPerpSpec",
    "CryptoSpotSpec",
    "DayCount",
    "EquitySpec",
    "ExerciseStyle",
    "FutureSpec",
    "FxConversion",
    "FxSpec",
    "GenericInstrumentSpec",
    "InstrumentSpecError",
    "OptionSpec",
    "OptionType",
    "Settlement",
    "SpecKind",
    "TypedInstrumentSpec",
    "parse_instrument_spec",
]
