"""GOAL §9 factor/model/signal/strategy boundary contracts.

This module is a boundary validator, not a new factor engine. Existing
factor_factory code still owns expression compilation, mining, signal
registration, and lifecycle mechanics. The validator binds those pieces to the
§9 hard gates: generator/gatekeeper separation, model-body category separation,
retired factor adoption, short-intent execution checks, and math-to-run_config
binding.
"""

from __future__ import annotations

import json
import os
import threading
from dataclasses import asdict, dataclass, field, is_dataclass
from datetime import UTC, datetime
from enum import Enum
from pathlib import Path, PurePosixPath
from typing import Any

from ..lineage.ids import content_hash as qbt_content_hash
from ..cross_process_lock import acquire_exclusive_fd
from .market_data_contract import MarketDataUseValidationRecord, validate_market_data_use_validation_record


GATE_METRIC_KEYWORDS: tuple[str, ...] = (
    "ic",
    "ir",
    "dsr",
    "sharpe",
    "pbo",
    "cscv",
    "tstat",
    "pnl",
    "return",
    "alpha",
    "ret",
    "sortino",
    "calmar",
)

MODEL_BODY_EXTS: tuple[str, ...] = (".pt", ".pth", ".onnx", ".pkl", ".pickle", ".joblib", ".h5", ".ckpt")


def _value(value: Any) -> str:
    if isinstance(value, Enum):
        return str(value.value)
    return str(value or "")


def _tuple(value: Any) -> tuple[Any, ...]:
    if value is None:
        return ()
    if isinstance(value, tuple):
        return value
    if isinstance(value, list):
        return tuple(value)
    return (value,)


def _str_tuple(value: Any) -> tuple[str, ...]:
    return tuple(str(item) for item in _tuple(value))


def _present(value: str | None) -> bool:
    return bool(str(value or "").strip())


def _stable(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    if is_dataclass(value):
        return _stable(asdict(value))
    if isinstance(value, dict):
        return {str(k): _stable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_stable(v) for v in value]
    return value


def _normalized_key(value: str) -> str:
    return "".join(ch for ch in str(value or "").lower() if ch.isalnum())


def is_gate_metric_key(key: str) -> bool:
    normalized = _normalized_key(key)
    return any(metric.replace("_", "").replace("-", "") in normalized for metric in GATE_METRIC_KEYWORDS)


def looks_like_model_body(ref: str) -> bool:
    suffix = PurePosixPath(str(ref or "").strip().lower()).suffix
    return suffix in MODEL_BODY_EXTS


class FactorAssetKind(str, Enum):
    EXPRESSION = "expression"
    SIGNAL_CONTRACT = "signal_contract"
    MODEL_BODY = "model_body"


class StrategySide(str, Enum):
    LONG = "long"
    SHORT = "short"


class SignalValidationVerdict(str, Enum):
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    CHALLENGED = "challenged"


@dataclass(frozen=True)
class BoundaryViolation:
    code: str
    message: str
    field: str = ""
    ref: str = ""


@dataclass(frozen=True)
class BoundaryDecision:
    accepted: bool
    violations: tuple[BoundaryViolation, ...]


@dataclass(frozen=True)
class FactorGeneratorSpec:
    generator_ref: str
    structure_inputs: tuple[str, ...]
    fitness_inputs: tuple[str, ...]
    gatekeeper_ref: str | None

    def __post_init__(self) -> None:
        object.__setattr__(self, "structure_inputs", _tuple(self.structure_inputs))
        object.__setattr__(self, "fitness_inputs", _tuple(self.fitness_inputs))


@dataclass(frozen=True)
class FactorLibraryEntry:
    factor_ref: str
    kind: FactorAssetKind | str
    ref: str
    lifecycle_state: str = "NEW"
    adopted_by_default: bool = False
    mathematical_refs: tuple[str, ...] = ()
    theory_binding_ref: str | None = None
    run_config_binding_ref: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "mathematical_refs", _tuple(self.mathematical_refs))


@dataclass(frozen=True)
class SignalProtocolRecord:
    signal_ref: str
    source_model_ref: str | None
    oof: bool
    purge: bool
    embargo: bool
    train_test_lock_ref: str | None
    honest_n_ref: str | None
    forecast_time_ref: str | None = None
    prediction_horizon_ref: str | None = None
    unit_ref: str | None = None
    direction_semantics_ref: str | None = None
    confidence_ref: str | None = None
    expires_at_ref: str | None = None
    source_layer: str = "signal"


@dataclass(frozen=True)
class SignalPerformanceValidationRecord:
    signal_ref: str
    validation_dataset_ref: str
    evaluation_window_ref: str
    methodology_ref: str
    metric_refs: tuple[str, ...]
    performance_summary_ref: str
    leakage_check_ref: str
    evidence_refs: tuple[str, ...]
    verdict: SignalValidationVerdict | str = SignalValidationVerdict.CHALLENGED
    regime_check_ref: str | None = None
    capacity_check_ref: str | None = None
    known_limits_refs: tuple[str, ...] = ()
    recorded_by: str = "system"
    created_at_utc: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    validation_id: str = ""

    def __post_init__(self) -> None:
        for name in ("metric_refs", "evidence_refs", "known_limits_refs"):
            object.__setattr__(self, name, _str_tuple(getattr(self, name)))
        verdict = _value(self.verdict) or SignalValidationVerdict.CHALLENGED.value
        object.__setattr__(self, "verdict", verdict)
        if not self.validation_id:
            object.__setattr__(self, "validation_id", self.canonical_validation_id)

    @property
    def canonical_validation_id(self) -> str:
        return "signal_validation_" + qbt_content_hash(
            {
                "signal_ref": self.signal_ref,
                "validation_dataset_ref": self.validation_dataset_ref,
                "evaluation_window_ref": self.evaluation_window_ref,
                "methodology_ref": self.methodology_ref,
                "metric_refs": self.metric_refs,
                "performance_summary_ref": self.performance_summary_ref,
                "leakage_check_ref": self.leakage_check_ref,
                "evidence_refs": self.evidence_refs,
                "verdict": _value(self.verdict),
                "regime_check_ref": self.regime_check_ref,
                "capacity_check_ref": self.capacity_check_ref,
                "known_limits_refs": self.known_limits_refs,
                "recorded_by": self.recorded_by,
                "created_at_utc": self.created_at_utc,
            }
        )

    def to_dict(self) -> dict[str, Any]:
        return _stable(self)


@dataclass(frozen=True)
class StrategyLegContract:
    intent_ref: str
    side: StrategySide | str
    instrument_ref: str
    expected_pnl_ref: str | None = None
    venue_ref: str | None = None
    borrow_check_ref: str | None = None
    margin_check_ref: str | None = None
    regulation_check_ref: str | None = None
    permission_check_ref: str | None = None


@dataclass(frozen=True)
class StrategyBookContract:
    strategy_book_ref: str
    factor_refs: tuple[str, ...]
    signal_refs: tuple[str, ...]
    legs: tuple[StrategyLegContract, ...]
    default_factor_refs: tuple[str, ...] = ()
    mathematical_refs: tuple[str, ...] = ()
    theory_binding_refs: tuple[str, ...] = ()
    run_config_binding_refs: tuple[str, ...] = ()
    signal_validation_refs: tuple[str, ...] = ()
    market_data_use_validation_refs: tuple[str, ...] = ()
    portfolio_of_strategies_refs: tuple[str, ...] = ()
    correlation_budget_ref: str | None = None
    capacity_budget_ref: str | None = None
    drawdown_budget_ref: str | None = None
    capital_allocation_ref: str | None = None

    def __post_init__(self) -> None:
        for name in (
            "factor_refs",
            "signal_refs",
            "legs",
            "default_factor_refs",
            "mathematical_refs",
            "theory_binding_refs",
            "run_config_binding_refs",
            "signal_validation_refs",
            "market_data_use_validation_refs",
            "portfolio_of_strategies_refs",
        ):
            object.__setattr__(self, name, _tuple(getattr(self, name)))


def validate_factor_generator(spec: FactorGeneratorSpec) -> BoundaryDecision:
    violations: list[BoundaryViolation] = []
    for key in spec.fitness_inputs:
        if is_gate_metric_key(str(key)):
            violations.append(
                BoundaryViolation(
                    "gate_metric_in_generator_fitness",
                    f"gate metric {key!r} cannot enter generator fitness",
                    field="fitness_inputs",
                    ref=spec.generator_ref,
                )
            )
    if not _present(spec.gatekeeper_ref):
        violations.append(
            BoundaryViolation(
                "missing_gatekeeper_ref",
                "factor generator must name a separate gatekeeper",
                field="gatekeeper_ref",
                ref=spec.generator_ref,
            )
        )
    return BoundaryDecision(accepted=not violations, violations=tuple(violations))


def validate_factor_library_entry(entry: FactorLibraryEntry) -> BoundaryDecision:
    violations: list[BoundaryViolation] = []
    kind = _value(entry.kind)
    if kind == FactorAssetKind.MODEL_BODY.value:
        violations.append(
            BoundaryViolation(
                "model_body_in_factor_library",
                "ML/DL model bodies belong in Model Registry, not Factor Library",
                field="kind",
                ref=entry.factor_ref,
            )
        )
    if kind != FactorAssetKind.SIGNAL_CONTRACT.value and looks_like_model_body(entry.ref):
        violations.append(
            BoundaryViolation(
                "model_body_ref_in_factor_library",
                "model body refs must be registered through a signal contract before factor-library use",
                field="ref",
                ref=entry.factor_ref,
            )
        )
    if entry.mathematical_refs and (not _present(entry.theory_binding_ref) or not _present(entry.run_config_binding_ref)):
        violations.append(
            BoundaryViolation(
                "factor_math_without_run_binding",
                "factor math refs require theory and run_config bindings",
                field="mathematical_refs",
                ref=entry.factor_ref,
            )
        )
    return BoundaryDecision(accepted=not violations, violations=tuple(violations))


def validate_signal_protocol(record: SignalProtocolRecord) -> BoundaryDecision:
    violations: list[BoundaryViolation] = []
    if _present(record.source_model_ref) and looks_like_model_body(str(record.source_model_ref)):
        missing: list[str] = []
        if not record.oof:
            missing.append("OOF")
        if not record.purge:
            missing.append("purge")
        if not record.embargo:
            missing.append("embargo")
        if not _present(record.train_test_lock_ref):
            missing.append("train_test_lock_ref")
        if not _present(record.honest_n_ref):
            missing.append("honest_n_ref")
        for field_name in (
            "forecast_time_ref",
            "prediction_horizon_ref",
            "unit_ref",
            "direction_semantics_ref",
            "confidence_ref",
            "expires_at_ref",
        ):
            if not _present(getattr(record, field_name)):
                missing.append(field_name)
        if missing:
            violations.append(
                BoundaryViolation(
                    "signal_protocol_incomplete",
                    "ML/DL signal usage requires leakage controls and typed forecast/signal semantics",
                    field="signal_protocol",
                    ref=record.signal_ref,
                )
            )
    return BoundaryDecision(accepted=not violations, violations=tuple(violations))


def signal_validation_record_from_dict(data: dict[str, Any]) -> SignalPerformanceValidationRecord:
    return SignalPerformanceValidationRecord(
        signal_ref=str(data.get("signal_ref") or ""),
        validation_dataset_ref=str(data.get("validation_dataset_ref") or ""),
        evaluation_window_ref=str(data.get("evaluation_window_ref") or ""),
        methodology_ref=str(data.get("methodology_ref") or ""),
        metric_refs=_str_tuple(data.get("metric_refs")),
        performance_summary_ref=str(data.get("performance_summary_ref") or ""),
        leakage_check_ref=str(data.get("leakage_check_ref") or ""),
        evidence_refs=_str_tuple(data.get("evidence_refs")),
        verdict=str(data.get("verdict") or SignalValidationVerdict.CHALLENGED.value),
        regime_check_ref=data.get("regime_check_ref"),
        capacity_check_ref=data.get("capacity_check_ref"),
        known_limits_refs=_str_tuple(data.get("known_limits_refs")),
        recorded_by=str(data.get("recorded_by") or "system"),
        created_at_utc=str(data.get("created_at_utc") or datetime.now(UTC).isoformat()),
        validation_id=str(data.get("validation_id") or ""),
    )


def validate_signal_performance_validation(
    record: SignalPerformanceValidationRecord,
    *,
    known_signal_refs: set[str] | None = None,
) -> BoundaryDecision:
    violations: list[BoundaryViolation] = []
    if record.validation_id != record.canonical_validation_id:
        violations.append(
            BoundaryViolation(
                "signal_validation_identity_mismatch",
                "validation_id must content-bind the complete signal validation record",
                field="validation_id",
                ref=record.validation_id,
            )
        )
    if not _present(record.signal_ref):
        violations.append(
            BoundaryViolation(
                "missing_signal_ref",
                "signal validation must name a signal contract ref",
                field="signal_ref",
            )
        )
    elif not str(record.signal_ref).startswith("sig::"):
        violations.append(
            BoundaryViolation(
                "signal_validation_requires_signal_contract_ref",
                "signal validation must point at a SignalContract ref, not a model body or loose label",
                field="signal_ref",
                ref=record.signal_ref,
            )
        )
    elif known_signal_refs is not None and record.signal_ref not in known_signal_refs:
        violations.append(
            BoundaryViolation(
                "unknown_signal_contract_ref",
                "signal validation must point at an existing SignalContract",
                field="signal_ref",
                ref=record.signal_ref,
            )
        )
    for field_name in (
        "validation_dataset_ref",
        "evaluation_window_ref",
        "methodology_ref",
        "performance_summary_ref",
        "leakage_check_ref",
    ):
        if not _present(getattr(record, field_name)):
            violations.append(
                BoundaryViolation(
                    "signal_validation_missing_required_ref",
                    f"signal validation missing {field_name}",
                    field=field_name,
                    ref=record.signal_ref,
                )
            )
    if not record.metric_refs:
        violations.append(
            BoundaryViolation(
                "signal_validation_missing_metric_refs",
                "signal validation requires metric refs",
                field="metric_refs",
                ref=record.signal_ref,
            )
        )
    if not record.evidence_refs:
        violations.append(
            BoundaryViolation(
                "signal_validation_missing_evidence_refs",
                "signal validation requires evidence refs",
                field="evidence_refs",
                ref=record.signal_ref,
            )
        )
    if _value(record.verdict) not in {item.value for item in SignalValidationVerdict}:
        violations.append(
            BoundaryViolation(
                "signal_validation_bad_verdict",
                "signal validation verdict must be accepted, rejected, or challenged",
                field="verdict",
                ref=record.signal_ref,
            )
        )
    return BoundaryDecision(accepted=not violations, violations=tuple(violations))


class PersistentSignalValidationRegistry:
    """Owner-scoped append-only signal validation registry.

    This stores refs and verdicts only. It does not store raw prediction
    series, returns, or metric payloads.
    """

    def __init__(self, path: str | Path | None = None) -> None:
        self._path = Path(path) if path is not None else None
        self._lock = threading.RLock()
        self._lock_path = (
            self._path.with_name(f".{self._path.name}.lock")
            if self._path is not None
            else None
        )
        self._records: dict[tuple[str, str], SignalPerformanceValidationRecord] = {}
        self._legacy_quarantined_count = 0
        if self._path is not None:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            self._load_existing()

    def _load_existing(self) -> None:
        assert self._path is not None
        if not self._path.exists():
            return
        for line_no, line in enumerate(self._path.read_text(encoding="utf-8").splitlines(), start=1):
            if not line.strip():
                continue
            try:
                row = json.loads(line)
                if row.get("schema_version") != 2:
                    self._legacy_quarantined_count += 1
                    continue
                if row.get("event_type") != "signal_performance_validation_recorded":
                    raise ValueError("unsupported signal validation event_type")
                payload = row.get("signal_validation")
                if not isinstance(payload, dict):
                    raise ValueError("missing signal_validation")
                record = signal_validation_record_from_dict(payload)
                owner = self._owner(row.get("owner_user_id"))
                decision = validate_signal_performance_validation(record)
                if not decision.accepted:
                    codes = ",".join(v.code for v in decision.violations)
                    raise ValueError(f"invalid signal validation record: {codes}")
                if record.recorded_by != owner:
                    raise ValueError("signal validation owner envelope mismatch")
                key = (owner, record.validation_id)
                existing = self._records.get(key)
                if existing is not None and existing != record:
                    raise ValueError("signal validation identity collision in persisted history")
                self._records[key] = record
            except Exception as exc:  # noqa: BLE001 - corrupt governance history must be visible.
                raise ValueError(f"invalid persisted signal validation row at {self._path}:{line_no}") from exc

    @property
    def legacy_quarantined_count(self) -> int:
        return self._legacy_quarantined_count

    def refresh(self) -> None:
        if self._path is None:
            return
        with self._lock:
            self._records = {}
            self._legacy_quarantined_count = 0
            self._load_existing()

    @staticmethod
    def _owner(value: Any) -> str:
        owner = str(value or "").strip()
        if not owner:
            raise ValueError("signal validation owner_user_id is required")
        return owner

    def _append(self, row: dict[str, Any], *, validation_id: str) -> None:
        if self._path is None:
            return
        assert self._lock_path is not None
        fd = os.open(self._lock_path, os.O_RDWR | os.O_CREAT, 0o600)
        held = None
        try:
            os.chmod(self._lock_path, 0o600)
            held = acquire_exclusive_fd(fd, timeout_seconds=30.0)
            if self._path.exists():
                for line_no, line in enumerate(
                    self._path.read_text(encoding="utf-8").splitlines(),
                    start=1,
                ):
                    if not line.strip():
                        continue
                    existing = json.loads(line)
                    payload = existing.get("signal_validation")
                    if (
                        existing.get("schema_version") == 2
                        and existing.get("owner_user_id") == row.get("owner_user_id")
                        and isinstance(payload, dict)
                        and str(payload.get("validation_id") or "") == validation_id
                    ):
                        if existing == row:
                            return
                        raise ValueError(
                            f"signal validation identity collision at {self._path}:{line_no}"
                        )
            with self._path.open("a", encoding="utf-8") as fh:
                fh.write(
                    json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
                    + "\n"
                )
                fh.flush()
                os.fsync(fh.fileno())
        finally:
            if held is not None:
                held.release()
            os.close(fd)

    def record_validation(
        self,
        record: SignalPerformanceValidationRecord,
        *,
        owner_user_id: str,
        known_signal_refs: set[str] | None = None,
    ) -> SignalPerformanceValidationRecord:
        owner = self._owner(owner_user_id)
        if record.recorded_by != owner:
            raise ValueError("signal validation recorded_by must match authenticated owner")
        decision = validate_signal_performance_validation(record, known_signal_refs=known_signal_refs)
        if not decision.accepted:
            codes = ",".join(v.code for v in decision.violations)
            raise ValueError(codes)
        key = (owner, record.validation_id)
        row = {
            "schema_version": 2,
            "event_type": "signal_performance_validation_recorded",
            "owner_user_id": owner,
            "signal_validation": record.to_dict(),
        }
        with self._lock:
            existing = self._records.get(key)
            if existing is not None:
                if existing != record:
                    raise ValueError("signal validation identity collision with different content")
                return existing
            self._append(row, validation_id=record.validation_id)
            self._records[key] = record
            return record

    def validation(
        self,
        validation_id: str,
        *,
        owner_user_id: str,
    ) -> SignalPerformanceValidationRecord:
        key = (self._owner(owner_user_id), validation_id)
        if key not in self._records:
            raise KeyError(f"unknown signal validation: {validation_id}")
        return self._records[key]

    def validations(self, *, owner_user_id: str) -> list[SignalPerformanceValidationRecord]:
        owner = self._owner(owner_user_id)
        return sorted(
            (
                record
                for (record_owner, _ref), record in self._records.items()
                if record_owner == owner
            ),
            key=lambda item: (item.signal_ref, item.created_at_utc),
        )

    def validations_for_signal(
        self,
        signal_ref: str,
        *,
        owner_user_id: str,
    ) -> list[SignalPerformanceValidationRecord]:
        return [
            record
            for record in self.validations(owner_user_id=owner_user_id)
            if record.signal_ref == signal_ref
        ]

    def accepted_for_signal(
        self,
        signal_ref: str,
        *,
        owner_user_id: str,
    ) -> list[SignalPerformanceValidationRecord]:
        return [
            record
            for record in self.validations_for_signal(
                signal_ref,
                owner_user_id=owner_user_id,
            )
            if _value(record.verdict) == SignalValidationVerdict.ACCEPTED.value
        ]


def validate_strategy_book(
    book: StrategyBookContract,
    *,
    factor_library: dict[str, FactorLibraryEntry] | None = None,
    signal_protocols: dict[str, SignalProtocolRecord] | None = None,
    signal_validations: dict[str, SignalPerformanceValidationRecord] | None = None,
    require_signal_validation: bool = False,
    market_data_use_validations: dict[str, MarketDataUseValidationRecord] | None = None,
    require_market_data_use_validation: bool = False,
) -> BoundaryDecision:
    factor_library = factor_library or {}
    signal_protocols = signal_protocols or {}
    signal_validations = signal_validations or {}
    market_data_use_validations = market_data_use_validations or {}
    violations: list[BoundaryViolation] = []

    for entry in factor_library.values():
        violations.extend(validate_factor_library_entry(entry).violations)

    default_factor_refs = set(book.default_factor_refs)
    for factor_ref in book.factor_refs:
        entry = factor_library.get(factor_ref)
        if entry is None:
            violations.append(
                BoundaryViolation(
                    "missing_factor_contract",
                    "strategy factor ref must resolve to a factor contract",
                    field="factor_refs",
                    ref=factor_ref,
                )
            )
            continue
        if str(entry.lifecycle_state).upper() == "RETIRED" and (factor_ref in default_factor_refs or entry.adopted_by_default):
            violations.append(
                BoundaryViolation(
                    "retired_factor_default_adoption",
                    "retired factor cannot be adopted by a new strategy by default",
                    field="default_factor_refs",
                    ref=factor_ref,
                )
            )

    for signal_ref in book.signal_refs:
        record = signal_protocols.get(signal_ref)
        if record is None:
            violations.append(
                BoundaryViolation(
                    "missing_signal_contract",
                    "strategy signal ref must resolve to a signal contract",
                    field="signal_refs",
                    ref=signal_ref,
                )
            )
            continue
        violations.extend(validate_signal_protocol(record).violations)

    accepted_validation_signal_refs: set[str] = set()
    for validation_ref in book.signal_validation_refs:
        record = signal_validations.get(str(validation_ref))
        if record is None:
            violations.append(
                BoundaryViolation(
                    "missing_signal_validation_record",
                    "strategy signal_validation_ref must resolve to a validation record",
                    field="signal_validation_refs",
                    ref=str(validation_ref),
                )
            )
            continue
        validation_decision = validate_signal_performance_validation(record)
        violations.extend(validation_decision.violations)
        if _value(record.verdict) != SignalValidationVerdict.ACCEPTED.value:
            violations.append(
                BoundaryViolation(
                    "signal_validation_not_accepted",
                    "strategy can only consume accepted signal validation records",
                    field="signal_validation_refs",
                    ref=record.validation_id,
                )
            )
            continue
        accepted_validation_signal_refs.add(record.signal_ref)

    if require_signal_validation:
        for signal_ref in book.signal_refs:
            if str(signal_ref) not in accepted_validation_signal_refs:
                violations.append(
                    BoundaryViolation(
                        "missing_signal_performance_validation",
                        "strategy signal refs require accepted signal performance validation before portfolio use",
                        field="signal_refs",
                        ref=str(signal_ref),
                    )
                )

    accepted_market_data_instruments: set[str] = set()
    for validation_ref in book.market_data_use_validation_refs:
        record = market_data_use_validations.get(str(validation_ref))
        if record is None:
            violations.append(
                BoundaryViolation(
                    "missing_market_data_use_validation_record",
                    "strategy market_data_use_validation_ref must resolve to a MarketDataUseValidationRecord",
                    field="market_data_use_validation_refs",
                    ref=str(validation_ref),
                )
            )
            continue
        validation_decision = validate_market_data_use_validation_record(record)
        for violation in validation_decision.violations:
            violations.append(
                BoundaryViolation(
                    violation.code,
                    violation.message,
                    field=violation.field,
                    ref=violation.ref,
                )
            )
        if not validation_decision.accepted:
            continue
        accepted_market_data_instruments.update(str(ref) for ref in record.instrument_refs)

    if require_market_data_use_validation:
        for leg in book.legs:
            if str(leg.instrument_ref) not in accepted_market_data_instruments:
                violations.append(
                    BoundaryViolation(
                        "missing_market_data_use_validation",
                        "strategy leg instruments require accepted MarketDataUse validation before strategy use",
                        field="market_data_use_validation_refs",
                        ref=str(leg.instrument_ref),
                    )
                )

    for leg in book.legs:
        if _value(leg.side) == StrategySide.SHORT.value:
            missing = [
                field_name
                for field_name in (
                    "venue_ref",
                    "borrow_check_ref",
                    "margin_check_ref",
                    "regulation_check_ref",
                    "permission_check_ref",
                )
                if not _present(getattr(leg, field_name))
            ]
            if missing:
                violations.append(
                    BoundaryViolation(
                        "short_intent_missing_execution_checks",
                        "short intent needs venue, borrow, margin, regulation, and permission checks before runtime use",
                        field="legs",
                        ref=leg.intent_ref,
                    )
                )

    if book.mathematical_refs and (not book.theory_binding_refs or not book.run_config_binding_refs):
        violations.append(
            BoundaryViolation(
                "strategy_math_without_run_config_binding",
                "StrategyBook math refs require theory bindings and run_config bindings",
                field="mathematical_refs",
                ref=book.strategy_book_ref,
            )
        )

    if book.portfolio_of_strategies_refs:
        for field_name in (
            "correlation_budget_ref",
            "capacity_budget_ref",
            "drawdown_budget_ref",
            "capital_allocation_ref",
        ):
            if not _present(getattr(book, field_name)):
                violations.append(
                    BoundaryViolation(
                        "portfolio_of_strategies_missing_budget",
                        "portfolio-of-strategies requires correlation, capacity, drawdown, and capital budgets",
                        field=field_name,
                        ref=book.strategy_book_ref,
                    )
                )

    return BoundaryDecision(accepted=not violations, violations=tuple(violations))


__all__ = [
    "BoundaryDecision",
    "BoundaryViolation",
    "FactorAssetKind",
    "FactorGeneratorSpec",
    "FactorLibraryEntry",
    "PersistentSignalValidationRegistry",
    "SignalPerformanceValidationRecord",
    "SignalProtocolRecord",
    "SignalValidationVerdict",
    "StrategyBookContract",
    "StrategyLegContract",
    "StrategySide",
    "is_gate_metric_key",
    "looks_like_model_body",
    "signal_validation_record_from_dict",
    "validate_factor_generator",
    "validate_factor_library_entry",
    "validate_signal_performance_validation",
    "validate_signal_protocol",
    "validate_strategy_book",
]
