"""GOAL §10 methodology and validation boundary contracts."""

from __future__ import annotations

import json
import math
import os
import threading
from dataclasses import asdict, dataclass, is_dataclass
from pathlib import Path
from typing import Any

from ..cross_process_lock import acquire_exclusive_fd
from ..lineage.ids import content_hash


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


def _float_tuple(value: Any) -> tuple[float, ...]:
    values = _tuple(value)
    out: list[float] = []
    for item in values:
        number = float(item)
        if not math.isfinite(number):
            raise ValueError("methodology calculator values must be finite")
        out.append(number)
    return tuple(out)


def _mean(values: tuple[float, ...]) -> float:
    return sum(values) / len(values)


def _json_value(value: Any) -> Any:
    if is_dataclass(value):
        return _json_value(asdict(value))
    if isinstance(value, dict):
        return {str(k): _json_value(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_value(v) for v in value]
    return value


STRONG_LABELS = {"proof_backed", "evidence_sufficient", "production_ready"}
RUNTIME_ENVIRONMENTS = {"paper", "testnet", "live", "production"}
PASSING_VERDICTS = {"accepted", "passed", "no_violation"}
SAFE_DRILL_MODES = {"simulation", "paper", "testnet"}


@dataclass(frozen=True)
class MethodologyViolation:
    code: str
    message: str
    field: str = ""
    ref: str = ""


@dataclass(frozen=True)
class MethodologyDecision:
    accepted: bool
    violations: tuple[MethodologyViolation, ...]


@dataclass(frozen=True)
class ValidationMethodologyRecord:
    validation_ref: str
    claim_label: str
    sample_size: int
    pbo_ref: str | None
    dsr_ref: str | None
    bootstrap_ci_ref: str | None
    cpcv_ref: str | None
    walk_forward_ref: str | None
    purge_embargo_ref: str | None
    honest_n_ref: str | None
    multiple_testing_ref: str | None
    cost_model_refs: tuple[str, ...]
    tca_ref: str | None = None
    methodology_choice_ref: str | None = None
    responsibility_boundary_ref: str | None = None
    user_waived_path: bool = False
    target_environment: str = "research"

    def __post_init__(self) -> None:
        object.__setattr__(self, "cost_model_refs", _tuple(self.cost_model_refs))


@dataclass(frozen=True)
class MethodologyChoiceCoverageRecord:
    choice_ref: str
    control_level: str
    tradeoffs_ref: str | None
    recommendation_ref: str | None
    responsibility_boundary_ref: str | None
    allowed_environment: str | None


@dataclass(frozen=True)
class LiveMonitoringAlertRecord:
    alert_ref: str
    dsr_ref: str | None
    performance_primary_alert_ref: str | None
    drift_root_cause_ref: str | None
    used_dsr_as_primary_live_alert: bool


@dataclass(frozen=True)
class ValidationDepthRecord:
    depth_ref: str
    claim_ref: str
    claim_label: str
    target_environment: str
    cpcv_ref: str | None
    walk_forward_ref: str | None
    conformal_ref: str | None
    abstain_policy_ref: str | None
    tca_ref: str | None
    cost_model_refs: tuple[str, ...]
    feature_leakage_probe_refs: tuple[str, ...]
    feature_leakage_verdict: str
    fault_injection_refs: tuple[str, ...]
    fault_injection_verdict: str
    recovery_drill_refs: tuple[str, ...]
    recovery_drill_verdict: str
    evidence_refs: tuple[str, ...]
    validation_result_refs: tuple[str, ...]
    methodology_choice_ref: str | None = None
    responsibility_boundary_ref: str | None = None
    user_waived_path: bool = False
    silent_mock_fallback_used: bool = False

    def __post_init__(self) -> None:
        for field_name in (
            "cost_model_refs",
            "feature_leakage_probe_refs",
            "fault_injection_refs",
            "recovery_drill_refs",
            "evidence_refs",
            "validation_result_refs",
        ):
            object.__setattr__(self, field_name, tuple(str(v) for v in _tuple(getattr(self, field_name))))


@dataclass(frozen=True)
class ValidationEvidenceBinding:
    owner_user_id: str
    recorded_by: str
    source_run_ref: str
    backtest_run_ref: str


@dataclass(frozen=True)
class CPCVCalculatorRecord:
    cpcv_ref: str
    claim_ref: str
    fold_count: int
    embargo_observations: int
    sample_count: int
    mean_metric: float
    min_metric: float
    max_metric: float
    source_hash: str
    evidence_refs: tuple[str, ...]
    validation_result_refs: tuple[str, ...]
    silent_mock_fallback_used: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(self, "evidence_refs", tuple(str(v) for v in _tuple(self.evidence_refs)))
        object.__setattr__(self, "validation_result_refs", tuple(str(v) for v in _tuple(self.validation_result_refs)))


@dataclass(frozen=True)
class ConformalCalculatorRecord:
    conformal_ref: str
    claim_ref: str
    alpha: float
    calibration_count: int
    nonconformity_threshold: float
    coverage_estimate: float
    source_hash: str
    evidence_refs: tuple[str, ...]
    validation_result_refs: tuple[str, ...]
    abstain_policy_ref: str | None = None
    silent_mock_fallback_used: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(self, "evidence_refs", tuple(str(v) for v in _tuple(self.evidence_refs)))
        object.__setattr__(self, "validation_result_refs", tuple(str(v) for v in _tuple(self.validation_result_refs)))


@dataclass(frozen=True)
class TCACalculatorRecord:
    tca_ref: str
    claim_ref: str
    sample_count: int
    gross_mean_bps: float
    total_cost_bps: float
    net_mean_bps: float
    cost_component_refs: tuple[str, ...]
    cost_model_refs: tuple[str, ...]
    source_hash: str
    evidence_refs: tuple[str, ...]
    validation_result_refs: tuple[str, ...]
    silent_mock_fallback_used: bool = False

    def __post_init__(self) -> None:
        for field_name in ("cost_component_refs", "cost_model_refs", "evidence_refs", "validation_result_refs"):
            object.__setattr__(self, field_name, tuple(str(v) for v in _tuple(getattr(self, field_name))))


@dataclass(frozen=True)
class RuntimeDrillRecord:
    runtime_drill_ref: str
    claim_ref: str
    target_environment: str
    drill_mode: str
    venue_ref: str
    fault_scenario: str
    expected_guard_ref: str
    observed_guard_ref: str
    recovery_action_ref: str
    fault_injection_ref: str
    recovery_drill_ref: str
    fault_injection_verdict: str
    recovery_drill_verdict: str
    source_hash: str
    evidence_refs: tuple[str, ...]
    validation_result_refs: tuple[str, ...]
    silent_mock_fallback_used: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(self, "evidence_refs", tuple(str(v) for v in _tuple(self.evidence_refs)))
        object.__setattr__(
            self,
            "validation_result_refs",
            tuple(str(v) for v in _tuple(self.validation_result_refs)),
        )


def _validate_calculator_common(
    *,
    ref: str,
    claim_ref: str,
    sample_count: int,
    source_hash: str,
    evidence_refs: tuple[str, ...],
    validation_result_refs: tuple[str, ...],
    silent_mock_fallback_used: bool,
) -> list[MethodologyViolation]:
    violations: list[MethodologyViolation] = []
    for field_name, value in (
        ("ref", ref),
        ("claim_ref", claim_ref),
        ("source_hash", source_hash),
    ):
        if not _present(value):
            violations.append(
                MethodologyViolation(
                    "methodology_calculator_required_field_missing",
                    "methodology calculator records require refs and source hash",
                    field=field_name,
                    ref=ref,
                )
            )
    if sample_count <= 0:
        violations.append(
            MethodologyViolation(
                "methodology_calculator_empty_sample",
                "methodology calculator records require non-empty samples",
                field="sample_count",
                ref=ref,
            )
        )
    for field_name, refs in (("evidence_refs", evidence_refs), ("validation_result_refs", validation_result_refs)):
        if not refs:
            violations.append(
                MethodologyViolation(
                    "methodology_calculator_required_ref_missing",
                    "methodology calculator records require evidence and validation result refs",
                    field=field_name,
                    ref=ref,
                )
            )
    if silent_mock_fallback_used:
        violations.append(
            MethodologyViolation(
                "methodology_calculator_silent_mock_fallback",
                "methodology calculators cannot rely on silent mock fallback",
                field="silent_mock_fallback_used",
                ref=ref,
            )
        )
    return violations


def validate_cpcv_calculator(record: CPCVCalculatorRecord) -> MethodologyDecision:
    violations = _validate_calculator_common(
        ref=record.cpcv_ref,
        claim_ref=record.claim_ref,
        sample_count=record.sample_count,
        source_hash=record.source_hash,
        evidence_refs=record.evidence_refs,
        validation_result_refs=record.validation_result_refs,
        silent_mock_fallback_used=record.silent_mock_fallback_used,
    )
    if record.fold_count < 2 or record.sample_count < 2:
        violations.append(
            MethodologyViolation(
                "cpcv_requires_multiple_folds",
                "CPCV calculation requires at least two folds",
                field="fold_count",
                ref=record.cpcv_ref,
            )
        )
    if record.embargo_observations < 0:
        violations.append(
            MethodologyViolation(
                "cpcv_invalid_embargo",
                "CPCV embargo observations cannot be negative",
                field="embargo_observations",
                ref=record.cpcv_ref,
            )
        )
    return MethodologyDecision(accepted=not violations, violations=tuple(violations))


def validate_conformal_calculator(record: ConformalCalculatorRecord) -> MethodologyDecision:
    violations = _validate_calculator_common(
        ref=record.conformal_ref,
        claim_ref=record.claim_ref,
        sample_count=record.calibration_count,
        source_hash=record.source_hash,
        evidence_refs=record.evidence_refs,
        validation_result_refs=record.validation_result_refs,
        silent_mock_fallback_used=record.silent_mock_fallback_used,
    )
    if not 0.0 < record.alpha < 1.0:
        violations.append(
            MethodologyViolation(
                "conformal_invalid_alpha",
                "conformal alpha must be between 0 and 1",
                field="alpha",
                ref=record.conformal_ref,
            )
        )
    if record.calibration_count < 5:
        violations.append(
            MethodologyViolation(
                "conformal_short_calibration_sample",
                "conformal calibration requires at least five observations",
                field="calibration_count",
                ref=record.conformal_ref,
            )
        )
    return MethodologyDecision(accepted=not violations, violations=tuple(violations))


def validate_tca_calculator(record: TCACalculatorRecord) -> MethodologyDecision:
    violations = _validate_calculator_common(
        ref=record.tca_ref,
        claim_ref=record.claim_ref,
        sample_count=record.sample_count,
        source_hash=record.source_hash,
        evidence_refs=record.evidence_refs,
        validation_result_refs=record.validation_result_refs,
        silent_mock_fallback_used=record.silent_mock_fallback_used,
    )
    if not record.cost_model_refs:
        violations.append(
            MethodologyViolation(
                "tca_missing_cost_model_refs",
                "TCA calculation requires cost model refs",
                field="cost_model_refs",
                ref=record.tca_ref,
            )
        )
    if record.total_cost_bps < 0:
        violations.append(
            MethodologyViolation(
                "tca_negative_cost",
                "TCA total cost cannot be negative",
                field="total_cost_bps",
                ref=record.tca_ref,
            )
        )
    return MethodologyDecision(accepted=not violations, violations=tuple(violations))


def validate_runtime_drill(record: RuntimeDrillRecord) -> MethodologyDecision:
    violations: list[MethodologyViolation] = []
    for field_name in (
        "runtime_drill_ref",
        "claim_ref",
        "target_environment",
        "drill_mode",
        "venue_ref",
        "fault_scenario",
        "expected_guard_ref",
        "observed_guard_ref",
        "recovery_action_ref",
        "fault_injection_ref",
        "recovery_drill_ref",
        "source_hash",
    ):
        if not _present(getattr(record, field_name)):
            violations.append(
                MethodologyViolation(
                    "runtime_drill_required_field_missing",
                    "runtime drill records require refs, scenario, mode, venue, guard, recovery, and source hash",
                    field=field_name,
                    ref=record.runtime_drill_ref,
                )
            )
    mode = str(record.drill_mode).strip().lower()
    if mode not in SAFE_DRILL_MODES:
        violations.append(
            MethodologyViolation(
                "runtime_drill_unsafe_mode",
                "methodology runtime drills may only record explicit simulation, paper, or testnet drills",
                field="drill_mode",
                ref=record.runtime_drill_ref,
            )
        )
    if str(record.fault_injection_verdict).strip().lower() not in PASSING_VERDICTS:
        violations.append(
            MethodologyViolation(
                "runtime_drill_fault_not_cleared",
                "runtime drill records require passing fault-injection evidence",
                field="fault_injection_verdict",
                ref=record.runtime_drill_ref,
            )
        )
    if str(record.recovery_drill_verdict).strip().lower() not in PASSING_VERDICTS:
        violations.append(
            MethodologyViolation(
                "runtime_drill_recovery_not_cleared",
                "runtime drill records require passing recovery evidence",
                field="recovery_drill_verdict",
                ref=record.runtime_drill_ref,
            )
        )
    if record.expected_guard_ref != record.observed_guard_ref:
        violations.append(
            MethodologyViolation(
                "runtime_drill_guard_mismatch",
                "runtime drills require observed guard evidence to match the expected guard",
                field="observed_guard_ref",
                ref=record.runtime_drill_ref,
            )
        )
    for field_name, refs in (("evidence_refs", record.evidence_refs), ("validation_result_refs", record.validation_result_refs)):
        if not refs:
            violations.append(
                MethodologyViolation(
                    "runtime_drill_required_ref_missing",
                    "runtime drill records require evidence and validation result refs",
                    field=field_name,
                    ref=record.runtime_drill_ref,
                )
            )
    if record.silent_mock_fallback_used:
        violations.append(
            MethodologyViolation(
                "runtime_drill_silent_mock_fallback",
                "runtime drills cannot rely on silent mock fallback",
                field="silent_mock_fallback_used",
                ref=record.runtime_drill_ref,
            )
        )
    return MethodologyDecision(accepted=not violations, violations=tuple(violations))


def calculate_cpcv(
    *,
    claim_ref: str,
    fold_metric_values: Any,
    embargo_observations: int = 0,
    evidence_refs: Any = (),
    validation_result_refs: Any = (),
    cpcv_ref: str | None = None,
    silent_mock_fallback_used: bool = False,
) -> CPCVCalculatorRecord:
    values = _float_tuple(fold_metric_values)
    source_hash = content_hash(
        {
            "claim_ref": claim_ref,
            "fold_metric_values": values,
            "embargo_observations": embargo_observations,
        }
    )
    record = CPCVCalculatorRecord(
        cpcv_ref=cpcv_ref or "cpcv:" + content_hash({"source_hash": source_hash}),
        claim_ref=claim_ref,
        fold_count=len(values),
        embargo_observations=int(embargo_observations),
        sample_count=len(values),
        mean_metric=_mean(values) if values else 0.0,
        min_metric=min(values) if values else 0.0,
        max_metric=max(values) if values else 0.0,
        source_hash=source_hash,
        evidence_refs=tuple(str(v) for v in _tuple(evidence_refs)),
        validation_result_refs=tuple(str(v) for v in _tuple(validation_result_refs)),
        silent_mock_fallback_used=silent_mock_fallback_used,
    )
    decision = validate_cpcv_calculator(record)
    if not decision.accepted:
        raise ValueError(_decision_message(decision))
    return record


def calculate_conformal(
    *,
    claim_ref: str,
    calibration_scores: Any,
    alpha: float,
    evidence_refs: Any = (),
    validation_result_refs: Any = (),
    abstain_policy_ref: str | None = None,
    conformal_ref: str | None = None,
    silent_mock_fallback_used: bool = False,
) -> ConformalCalculatorRecord:
    scores = tuple(sorted(abs(v) for v in _float_tuple(calibration_scores)))
    alpha_value = float(alpha)
    source_hash = content_hash(
        {
            "claim_ref": claim_ref,
            "calibration_scores": scores,
            "alpha": alpha_value,
            "abstain_policy_ref": abstain_policy_ref,
        }
    )
    if scores and 0.0 < alpha_value < 1.0:
        index = min(len(scores) - 1, max(0, math.ceil((len(scores) + 1) * (1.0 - alpha_value)) - 1))
        threshold = scores[index]
    else:
        threshold = 0.0
    record = ConformalCalculatorRecord(
        conformal_ref=conformal_ref or "conformal:" + content_hash({"source_hash": source_hash}),
        claim_ref=claim_ref,
        alpha=alpha_value,
        calibration_count=len(scores),
        nonconformity_threshold=threshold,
        coverage_estimate=1.0 - alpha_value if 0.0 < alpha_value < 1.0 else 0.0,
        source_hash=source_hash,
        evidence_refs=tuple(str(v) for v in _tuple(evidence_refs)),
        validation_result_refs=tuple(str(v) for v in _tuple(validation_result_refs)),
        abstain_policy_ref=abstain_policy_ref,
        silent_mock_fallback_used=silent_mock_fallback_used,
    )
    decision = validate_conformal_calculator(record)
    if not decision.accepted:
        raise ValueError(_decision_message(decision))
    return record


def calculate_tca(
    *,
    claim_ref: str,
    gross_return_bps: Any,
    cost_components_bps: dict[str, Any],
    cost_model_refs: Any,
    evidence_refs: Any = (),
    validation_result_refs: Any = (),
    tca_ref: str | None = None,
    silent_mock_fallback_used: bool = False,
) -> TCACalculatorRecord:
    gross_values = _float_tuple(gross_return_bps)
    components: dict[str, float] = {}
    for raw_key, raw_value in (cost_components_bps or {}).items():
        key = str(raw_key)
        value = float(raw_value)
        if not math.isfinite(value):
            raise ValueError("TCA cost component values must be finite")
        components[key] = value
    total_cost = sum(components.values())
    source_hash = content_hash(
        {
            "claim_ref": claim_ref,
            "gross_return_bps": gross_values,
            "cost_components_bps": components,
            "cost_model_refs": tuple(str(v) for v in _tuple(cost_model_refs)),
        }
    )
    gross_mean = _mean(gross_values) if gross_values else 0.0
    record = TCACalculatorRecord(
        tca_ref=tca_ref or "tca:" + content_hash({"source_hash": source_hash}),
        claim_ref=claim_ref,
        sample_count=len(gross_values),
        gross_mean_bps=gross_mean,
        total_cost_bps=total_cost,
        net_mean_bps=gross_mean - total_cost,
        cost_component_refs=tuple(f"cost_component:{key}" for key in sorted(components)),
        cost_model_refs=tuple(str(v) for v in _tuple(cost_model_refs)),
        source_hash=source_hash,
        evidence_refs=tuple(str(v) for v in _tuple(evidence_refs)),
        validation_result_refs=tuple(str(v) for v in _tuple(validation_result_refs)),
        silent_mock_fallback_used=silent_mock_fallback_used,
    )
    decision = validate_tca_calculator(record)
    if not decision.accepted:
        raise ValueError(_decision_message(decision))
    return record


def record_runtime_drill(
    *,
    claim_ref: str,
    target_environment: str,
    drill_mode: str,
    venue_ref: str,
    fault_scenario: str,
    expected_guard_ref: str,
    observed_guard_ref: str,
    recovery_action_ref: str,
    evidence_refs: Any = (),
    validation_result_refs: Any = (),
    runtime_drill_ref: str | None = None,
    fault_injection_ref: str | None = None,
    recovery_drill_ref: str | None = None,
    fault_injection_verdict: str = "passed",
    recovery_drill_verdict: str = "passed",
    silent_mock_fallback_used: bool = False,
) -> RuntimeDrillRecord:
    source_hash = content_hash(
        {
            "claim_ref": claim_ref,
            "target_environment": target_environment,
            "drill_mode": drill_mode,
            "venue_ref": venue_ref,
            "fault_scenario": fault_scenario,
            "expected_guard_ref": expected_guard_ref,
            "observed_guard_ref": observed_guard_ref,
            "recovery_action_ref": recovery_action_ref,
            "fault_injection_verdict": fault_injection_verdict,
            "recovery_drill_verdict": recovery_drill_verdict,
        }
    )
    record = RuntimeDrillRecord(
        runtime_drill_ref=runtime_drill_ref or "runtime_drill:" + content_hash({"source_hash": source_hash}),
        claim_ref=claim_ref,
        target_environment=target_environment,
        drill_mode=str(drill_mode).strip().lower(),
        venue_ref=venue_ref,
        fault_scenario=fault_scenario,
        expected_guard_ref=expected_guard_ref,
        observed_guard_ref=observed_guard_ref,
        recovery_action_ref=recovery_action_ref,
        fault_injection_ref=fault_injection_ref or "fault_injection:" + content_hash({"source_hash": source_hash}),
        recovery_drill_ref=recovery_drill_ref or "recovery_drill:" + content_hash({"source_hash": source_hash}),
        fault_injection_verdict=fault_injection_verdict,
        recovery_drill_verdict=recovery_drill_verdict,
        source_hash=source_hash,
        evidence_refs=tuple(str(v) for v in _tuple(evidence_refs)),
        validation_result_refs=tuple(str(v) for v in _tuple(validation_result_refs)),
        silent_mock_fallback_used=silent_mock_fallback_used,
    )
    decision = validate_runtime_drill(record)
    if not decision.accepted:
        raise ValueError(_decision_message(decision))
    return record


def validate_validation_methodology(record: ValidationMethodologyRecord) -> MethodologyDecision:
    violations: list[MethodologyViolation] = []
    strong = record.claim_label in STRONG_LABELS
    if strong and record.sample_size < 30:
        violations.append(
            MethodologyViolation(
                "short_sample_strong_conclusion",
                "short samples cannot produce strong evidence labels",
                field="sample_size",
                ref=record.validation_ref,
            )
        )
    if strong and record.user_waived_path:
        violations.append(
            MethodologyViolation(
                "user_waived_path_marked_strong",
                "user-waived methodology cannot be marked proof-backed/evidence-sufficient/production-ready",
                field="user_waived_path",
                ref=record.validation_ref,
            )
        )
    if record.target_environment in {"paper", "testnet", "live", "production"} and not record.cost_model_refs:
        violations.append(
            MethodologyViolation(
                "production_candidate_missing_cost_model",
                "production candidates require asset-specific cost/TCA assumptions",
                field="cost_model_refs",
                ref=record.validation_ref,
            )
        )
    if strong:
        for field_name in (
            "pbo_ref",
            "dsr_ref",
            "bootstrap_ci_ref",
            "purge_embargo_ref",
            "honest_n_ref",
            "multiple_testing_ref",
        ):
            if not _present(getattr(record, field_name)):
                violations.append(
                    MethodologyViolation(
                        "strong_validation_missing_method_ref",
                        "strong validation requires bias, multiple-testing, honest-N, and interval evidence",
                        field=field_name,
                        ref=record.validation_ref,
                    )
                )
        if not (_present(record.cpcv_ref) or _present(record.walk_forward_ref)):
            violations.append(
                MethodologyViolation(
                    "strong_validation_missing_cpcv_or_walk_forward",
                    "strong validation requires CPCV or walk-forward evidence",
                    field="cpcv_ref",
                    ref=record.validation_ref,
                )
            )
    if record.user_waived_path:
        for field_name in ("methodology_choice_ref", "responsibility_boundary_ref"):
            if not _present(getattr(record, field_name)):
                violations.append(
                    MethodologyViolation(
                        "user_waived_methodology_missing_choice_or_responsibility",
                        "user-waived validation requires choice and responsibility records",
                        field=field_name,
                        ref=record.validation_ref,
                    )
                )
    return MethodologyDecision(accepted=not violations, violations=tuple(violations))


def validate_methodology_choice_coverage(
    record: MethodologyChoiceCoverageRecord,
) -> MethodologyDecision:
    violations: list[MethodologyViolation] = []
    if record.control_level in {"loose", "exploratory", "custom", "user_waived"}:
        for field_name in (
            "tradeoffs_ref",
            "recommendation_ref",
            "responsibility_boundary_ref",
            "allowed_environment",
        ):
            if not _present(getattr(record, field_name)):
                violations.append(
                    MethodologyViolation(
                        "methodology_choice_missing_disclosure",
                        "methodology control choices require tradeoffs, recommendation, responsibility, and allowed environment",
                        field=field_name,
                        ref=record.choice_ref,
                    )
                )
    return MethodologyDecision(accepted=not violations, violations=tuple(violations))


def validate_live_monitoring_alert(alert: LiveMonitoringAlertRecord) -> MethodologyDecision:
    violations: list[MethodologyViolation] = []
    if alert.used_dsr_as_primary_live_alert and not _present(alert.performance_primary_alert_ref):
        violations.append(
            MethodologyViolation(
                "dsr_used_as_primary_live_monitor",
                "DSR cannot be the primary alert for single-strategy live monitoring",
                field="used_dsr_as_primary_live_alert",
                ref=alert.alert_ref,
            )
        )
    return MethodologyDecision(accepted=not violations, violations=tuple(violations))


def _require_depth_ref(
    violations: list[MethodologyViolation],
    *,
    record: ValidationDepthRecord,
    field_name: str,
    value: str | None,
) -> None:
    if not _present(value):
        violations.append(
            MethodologyViolation(
                "validation_depth_required_ref_missing",
                f"{field_name} is required for validation depth records",
                field=field_name,
                ref=record.depth_ref,
            )
        )


def _require_depth_refs(
    violations: list[MethodologyViolation],
    *,
    record: ValidationDepthRecord,
    field_name: str,
    value: tuple[Any, ...],
) -> None:
    if not value:
        violations.append(
            MethodologyViolation(
                "validation_depth_required_ref_missing",
                f"{field_name} is required for validation depth records",
                field=field_name,
                ref=record.depth_ref,
            )
        )


def validate_validation_depth(record: ValidationDepthRecord) -> MethodologyDecision:
    violations: list[MethodologyViolation] = []
    strong = record.claim_label in STRONG_LABELS
    runtime_candidate = str(record.target_environment).strip().lower() in RUNTIME_ENVIRONMENTS
    for field_name in ("depth_ref", "claim_ref", "claim_label", "target_environment"):
        _require_depth_ref(violations, record=record, field_name=field_name, value=getattr(record, field_name))
    for field_name in ("evidence_refs", "validation_result_refs"):
        _require_depth_refs(violations, record=record, field_name=field_name, value=getattr(record, field_name))
    if record.silent_mock_fallback_used:
        violations.append(
            MethodologyViolation(
                "validation_depth_silent_mock_fallback",
                "validation depth records cannot rely on silent mock fallback",
                field="silent_mock_fallback_used",
                ref=record.depth_ref,
            )
        )
    if strong and record.user_waived_path:
        violations.append(
            MethodologyViolation(
                "validation_depth_user_waived_marked_strong",
                "user-waived methodology cannot be marked proof-backed/evidence-sufficient/production-ready",
                field="user_waived_path",
                ref=record.depth_ref,
            )
        )
    if record.user_waived_path:
        for field_name in ("methodology_choice_ref", "responsibility_boundary_ref"):
            _require_depth_ref(violations, record=record, field_name=field_name, value=getattr(record, field_name))
    if strong:
        for field_name in (
            "cpcv_ref",
            "walk_forward_ref",
            "conformal_ref",
            "abstain_policy_ref",
        ):
            _require_depth_ref(violations, record=record, field_name=field_name, value=getattr(record, field_name))
        _require_depth_refs(
            violations,
            record=record,
            field_name="feature_leakage_probe_refs",
            value=record.feature_leakage_probe_refs,
        )
        if str(record.feature_leakage_verdict).strip().lower() not in PASSING_VERDICTS:
            violations.append(
                MethodologyViolation(
                    "validation_depth_feature_leakage_not_cleared",
                    "strong validation requires feature-level leakage probes with a passing verdict",
                    field="feature_leakage_verdict",
                    ref=record.depth_ref,
                )
            )
    if runtime_candidate:
        _require_depth_ref(violations, record=record, field_name="tca_ref", value=record.tca_ref)
        _require_depth_refs(violations, record=record, field_name="cost_model_refs", value=record.cost_model_refs)
        _require_depth_refs(
            violations,
            record=record,
            field_name="fault_injection_refs",
            value=record.fault_injection_refs,
        )
        _require_depth_refs(
            violations,
            record=record,
            field_name="recovery_drill_refs",
            value=record.recovery_drill_refs,
        )
        if str(record.fault_injection_verdict).strip().lower() not in PASSING_VERDICTS:
            violations.append(
                MethodologyViolation(
                    "validation_depth_fault_injection_not_cleared",
                    "runtime candidates require passing fault-injection evidence",
                    field="fault_injection_verdict",
                    ref=record.depth_ref,
                )
            )
        if str(record.recovery_drill_verdict).strip().lower() not in PASSING_VERDICTS:
            violations.append(
                MethodologyViolation(
                    "validation_depth_recovery_drill_not_cleared",
                    "runtime candidates require passing recovery drill evidence",
                    field="recovery_drill_verdict",
                    ref=record.depth_ref,
                )
            )
    return MethodologyDecision(accepted=not violations, violations=tuple(violations))


def validate_methodology_contract(
    validations: tuple[ValidationMethodologyRecord, ...] = (),
    *,
    choices: tuple[MethodologyChoiceCoverageRecord, ...] = (),
    live_alerts: tuple[LiveMonitoringAlertRecord, ...] = (),
    validation_depths: tuple[ValidationDepthRecord, ...] = (),
) -> MethodologyDecision:
    violations: list[MethodologyViolation] = []
    for validation in validations:
        violations.extend(validate_validation_methodology(validation).violations)
    for choice in choices:
        violations.extend(validate_methodology_choice_coverage(choice).violations)
    for alert in live_alerts:
        violations.extend(validate_live_monitoring_alert(alert).violations)
    for depth in validation_depths:
        violations.extend(validate_validation_depth(depth).violations)
    return MethodologyDecision(accepted=not violations, violations=tuple(violations))


def _decision_message(decision: MethodologyDecision) -> str:
    return "; ".join(f"{v.code}:{v.field}" for v in decision.violations) or "methodology record rejected"


def validation_methodology_record_from_dict(data: dict[str, Any]) -> ValidationMethodologyRecord:
    return ValidationMethodologyRecord(
        validation_ref=str(data.get("validation_ref") or ""),
        claim_label=str(data.get("claim_label") or ""),
        sample_size=int(data.get("sample_size") or 0),
        pbo_ref=data.get("pbo_ref"),
        dsr_ref=data.get("dsr_ref"),
        bootstrap_ci_ref=data.get("bootstrap_ci_ref"),
        cpcv_ref=data.get("cpcv_ref"),
        walk_forward_ref=data.get("walk_forward_ref"),
        purge_embargo_ref=data.get("purge_embargo_ref"),
        honest_n_ref=data.get("honest_n_ref"),
        multiple_testing_ref=data.get("multiple_testing_ref"),
        cost_model_refs=_tuple(data.get("cost_model_refs")),
        tca_ref=data.get("tca_ref"),
        methodology_choice_ref=data.get("methodology_choice_ref"),
        responsibility_boundary_ref=data.get("responsibility_boundary_ref"),
        user_waived_path=bool(data.get("user_waived_path", False)),
        target_environment=str(data.get("target_environment") or "research"),
    )


def validation_depth_record_from_dict(data: dict[str, Any]) -> ValidationDepthRecord:
    return ValidationDepthRecord(
        depth_ref=str(data.get("depth_ref") or ""),
        claim_ref=str(data.get("claim_ref") or ""),
        claim_label=str(data.get("claim_label") or ""),
        target_environment=str(data.get("target_environment") or ""),
        cpcv_ref=data.get("cpcv_ref"),
        walk_forward_ref=data.get("walk_forward_ref"),
        conformal_ref=data.get("conformal_ref"),
        abstain_policy_ref=data.get("abstain_policy_ref"),
        tca_ref=data.get("tca_ref"),
        cost_model_refs=_tuple(data.get("cost_model_refs")),
        feature_leakage_probe_refs=_tuple(data.get("feature_leakage_probe_refs")),
        feature_leakage_verdict=str(data.get("feature_leakage_verdict") or ""),
        fault_injection_refs=_tuple(data.get("fault_injection_refs")),
        fault_injection_verdict=str(data.get("fault_injection_verdict") or ""),
        recovery_drill_refs=_tuple(data.get("recovery_drill_refs")),
        recovery_drill_verdict=str(data.get("recovery_drill_verdict") or ""),
        evidence_refs=_tuple(data.get("evidence_refs")),
        validation_result_refs=_tuple(data.get("validation_result_refs")),
        methodology_choice_ref=data.get("methodology_choice_ref"),
        responsibility_boundary_ref=data.get("responsibility_boundary_ref"),
        user_waived_path=bool(data.get("user_waived_path", False)),
        silent_mock_fallback_used=bool(data.get("silent_mock_fallback_used", False)),
    )


class _OwnerMethodologyRegistry:
    """Shared append-only owner envelope mechanics for §10 evidence."""

    event_type = ""
    payload_key = ""
    ref_field = ""

    def __init__(self, path: str | Path) -> None:
        self._path = Path(path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._lock_path = self._path.with_name(f".{self._path.name}.lock")
        self._lock = threading.RLock()
        self._records: dict[tuple[str, str], Any] = {}
        self._bindings: dict[tuple[str, str], ValidationEvidenceBinding] = {}
        self._legacy_quarantined_count = 0
        self._load_existing()

    @property
    def path(self) -> Path:
        return self._path

    @property
    def legacy_quarantined_count(self) -> int:
        return self._legacy_quarantined_count

    @staticmethod
    def _required(value: Any, field_name: str) -> str:
        normalized = str(value or "").strip()
        if not normalized:
            raise ValueError(f"{field_name} is required")
        return normalized

    def _parse(self, raw: dict[str, Any]) -> Any:
        raise NotImplementedError

    def _validate(self, record: Any) -> MethodologyDecision:
        raise NotImplementedError

    def _load_existing(self) -> None:
        if not self._path.exists():
            return
        with self._path.open("r", encoding="utf-8") as fh:
            for line_no, line in enumerate(fh, start=1):
                if not line.strip():
                    continue
                try:
                    row = json.loads(line)
                    if row.get("schema_version") != 2:
                        self._legacy_quarantined_count += 1
                        continue
                    self._apply_row(row, persist=False)
                except Exception as exc:  # noqa: BLE001
                    raise ValueError(
                        f"invalid persisted Methodology Validation row at {self._path}:{line_no}"
                    ) from exc

    def _append_event(self, row: dict[str, Any], *, record_ref: str) -> None:
        fd = os.open(self._lock_path, os.O_RDWR | os.O_CREAT, 0o600)
        held = None
        try:
            os.chmod(self._lock_path, 0o600)
            held = acquire_exclusive_fd(fd, timeout_seconds=30.0)
            if self._path.exists():
                with self._path.open("r", encoding="utf-8") as existing_fh:
                    for line_no, line in enumerate(existing_fh, start=1):
                        if not line.strip():
                            continue
                        existing = json.loads(line)
                        payload = existing.get(self.payload_key)
                        if (
                            existing.get("schema_version") == 2
                            and existing.get("owner_user_id") == row.get("owner_user_id")
                            and isinstance(payload, dict)
                            and str(payload.get(self.ref_field) or "") == record_ref
                        ):
                            if existing == row:
                                return
                            raise ValueError(
                                f"Methodology Validation identity collision at {self._path}:{line_no}"
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

    def _apply_row(self, row: dict[str, Any], *, persist: bool) -> Any:
        if row.get("schema_version") != 2:
            raise ValueError("Methodology Validation owner envelope schema_version=2 is required")
        if row.get("event_type") != self.event_type:
            raise ValueError(f"unknown Methodology Validation event_type={row.get('event_type')!r}")
        raw = row.get(self.payload_key)
        if not isinstance(raw, dict):
            raise ValueError(f"Methodology Validation event missing {self.payload_key}")
        owner = self._required(row.get("owner_user_id"), "owner_user_id")
        binding = ValidationEvidenceBinding(
            owner_user_id=owner,
            recorded_by=self._required(row.get("recorded_by"), "recorded_by"),
            source_run_ref=self._required(row.get("source_run_ref"), "source_run_ref"),
            backtest_run_ref=self._required(row.get("backtest_run_ref"), "backtest_run_ref"),
        )
        record = self._parse(raw)
        decision = self._validate(record)
        if not decision.accepted:
            raise ValueError(_decision_message(decision))
        record_ref = self._required(getattr(record, self.ref_field, ""), self.ref_field)
        key = (owner, record_ref)
        with self._lock:
            existing = self._records.get(key)
            existing_binding = self._bindings.get(key)
            if existing is not None:
                if existing != record or existing_binding != binding:
                    raise ValueError("Methodology Validation identity collision with different content")
                return existing
            if persist:
                self._append_event(row, record_ref=record_ref)
            self._records[key] = record
            self._bindings[key] = binding
            return record

    def _record(
        self,
        record: Any,
        *,
        owner_user_id: str,
        recorded_by: str,
        source_run_ref: str,
        backtest_run_ref: str,
    ) -> Any:
        return self._apply_row(
            {
                "schema_version": 2,
                "event_type": self.event_type,
                "owner_user_id": self._required(owner_user_id, "owner_user_id"),
                "recorded_by": self._required(recorded_by, "recorded_by"),
                "source_run_ref": self._required(source_run_ref, "source_run_ref"),
                "backtest_run_ref": self._required(backtest_run_ref, "backtest_run_ref"),
                self.payload_key: _json_value(record),
            },
            persist=True,
        )

    def _get(self, record_ref: str, *, owner_user_id: str) -> Any:
        return self._records[
            (self._required(owner_user_id, "owner_user_id"), str(record_ref))
        ]

    def _binding(self, record_ref: str, *, owner_user_id: str) -> ValidationEvidenceBinding:
        return self._bindings[
            (self._required(owner_user_id, "owner_user_id"), str(record_ref))
        ]

    def _all(self, *, owner_user_id: str) -> list[Any]:
        owner = self._required(owner_user_id, "owner_user_id")
        return [
            record
            for (record_owner, _ref), record in self._records.items()
            if record_owner == owner
        ]


class PersistentValidationMethodologyRegistry(_OwnerMethodologyRegistry):
    event_type = "validation_methodology_recorded"
    payload_key = "validation_methodology"
    ref_field = "validation_ref"

    def _parse(self, raw: dict[str, Any]) -> ValidationMethodologyRecord:
        return validation_methodology_record_from_dict(raw)

    def _validate(self, record: ValidationMethodologyRecord) -> MethodologyDecision:
        return validate_validation_methodology(record)

    def record_methodology(
        self,
        record: ValidationMethodologyRecord,
        *,
        owner_user_id: str,
        recorded_by: str,
        source_run_ref: str,
        backtest_run_ref: str,
    ) -> ValidationMethodologyRecord:
        return self._record(
            record,
            owner_user_id=owner_user_id,
            recorded_by=recorded_by,
            source_run_ref=source_run_ref,
            backtest_run_ref=backtest_run_ref,
        )

    def methodology(self, validation_ref: str, *, owner_user_id: str) -> ValidationMethodologyRecord:
        return self._get(validation_ref, owner_user_id=owner_user_id)

    def methodology_binding(
        self,
        validation_ref: str,
        *,
        owner_user_id: str,
    ) -> ValidationEvidenceBinding:
        return self._binding(validation_ref, owner_user_id=owner_user_id)

    def methodologies(self, *, owner_user_id: str) -> list[ValidationMethodologyRecord]:
        return self._all(owner_user_id=owner_user_id)


class PersistentValidationDepthRegistry(_OwnerMethodologyRegistry):
    """Owner-scoped append-only registry for GOAL §10 validation-depth evidence."""

    event_type = "validation_depth_recorded"
    payload_key = "validation_depth"
    ref_field = "depth_ref"

    def _parse(self, raw: dict[str, Any]) -> ValidationDepthRecord:
        return validation_depth_record_from_dict(raw)

    def _validate(self, record: ValidationDepthRecord) -> MethodologyDecision:
        return validate_validation_depth(record)

    def record_depth(
        self,
        record: ValidationDepthRecord,
        *,
        owner_user_id: str,
        recorded_by: str,
        source_run_ref: str,
        backtest_run_ref: str,
    ) -> ValidationDepthRecord:
        return self._record(
            record,
            owner_user_id=owner_user_id,
            recorded_by=recorded_by,
            source_run_ref=source_run_ref,
            backtest_run_ref=backtest_run_ref,
        )

    def depth(self, depth_ref: str, *, owner_user_id: str) -> ValidationDepthRecord:
        return self._get(depth_ref, owner_user_id=owner_user_id)

    def depth_binding(
        self,
        depth_ref: str,
        *,
        owner_user_id: str,
    ) -> ValidationEvidenceBinding:
        return self._binding(depth_ref, owner_user_id=owner_user_id)

    def depths(self, *, owner_user_id: str) -> list[ValidationDepthRecord]:
        return self._all(owner_user_id=owner_user_id)


def cpcv_calculator_record_from_dict(data: dict[str, Any]) -> CPCVCalculatorRecord:
    return CPCVCalculatorRecord(
        cpcv_ref=str(data.get("cpcv_ref") or ""),
        claim_ref=str(data.get("claim_ref") or ""),
        fold_count=int(data.get("fold_count") or 0),
        embargo_observations=int(data.get("embargo_observations") or 0),
        sample_count=int(data.get("sample_count") or 0),
        mean_metric=float(data.get("mean_metric") or 0.0),
        min_metric=float(data.get("min_metric") or 0.0),
        max_metric=float(data.get("max_metric") or 0.0),
        source_hash=str(data.get("source_hash") or ""),
        evidence_refs=_tuple(data.get("evidence_refs")),
        validation_result_refs=_tuple(data.get("validation_result_refs")),
        silent_mock_fallback_used=bool(data.get("silent_mock_fallback_used", False)),
    )


def conformal_calculator_record_from_dict(data: dict[str, Any]) -> ConformalCalculatorRecord:
    return ConformalCalculatorRecord(
        conformal_ref=str(data.get("conformal_ref") or ""),
        claim_ref=str(data.get("claim_ref") or ""),
        alpha=float(data.get("alpha") or 0.0),
        calibration_count=int(data.get("calibration_count") or 0),
        nonconformity_threshold=float(data.get("nonconformity_threshold") or 0.0),
        coverage_estimate=float(data.get("coverage_estimate") or 0.0),
        source_hash=str(data.get("source_hash") or ""),
        evidence_refs=_tuple(data.get("evidence_refs")),
        validation_result_refs=_tuple(data.get("validation_result_refs")),
        abstain_policy_ref=data.get("abstain_policy_ref"),
        silent_mock_fallback_used=bool(data.get("silent_mock_fallback_used", False)),
    )


def tca_calculator_record_from_dict(data: dict[str, Any]) -> TCACalculatorRecord:
    return TCACalculatorRecord(
        tca_ref=str(data.get("tca_ref") or ""),
        claim_ref=str(data.get("claim_ref") or ""),
        sample_count=int(data.get("sample_count") or 0),
        gross_mean_bps=float(data.get("gross_mean_bps") or 0.0),
        total_cost_bps=float(data.get("total_cost_bps") or 0.0),
        net_mean_bps=float(data.get("net_mean_bps") or 0.0),
        cost_component_refs=_tuple(data.get("cost_component_refs")),
        cost_model_refs=_tuple(data.get("cost_model_refs")),
        source_hash=str(data.get("source_hash") or ""),
        evidence_refs=_tuple(data.get("evidence_refs")),
        validation_result_refs=_tuple(data.get("validation_result_refs")),
        silent_mock_fallback_used=bool(data.get("silent_mock_fallback_used", False)),
    )


def runtime_drill_record_from_dict(data: dict[str, Any]) -> RuntimeDrillRecord:
    return RuntimeDrillRecord(
        runtime_drill_ref=str(data.get("runtime_drill_ref") or ""),
        claim_ref=str(data.get("claim_ref") or ""),
        target_environment=str(data.get("target_environment") or ""),
        drill_mode=str(data.get("drill_mode") or ""),
        venue_ref=str(data.get("venue_ref") or ""),
        fault_scenario=str(data.get("fault_scenario") or ""),
        expected_guard_ref=str(data.get("expected_guard_ref") or ""),
        observed_guard_ref=str(data.get("observed_guard_ref") or ""),
        recovery_action_ref=str(data.get("recovery_action_ref") or ""),
        fault_injection_ref=str(data.get("fault_injection_ref") or ""),
        recovery_drill_ref=str(data.get("recovery_drill_ref") or ""),
        fault_injection_verdict=str(data.get("fault_injection_verdict") or ""),
        recovery_drill_verdict=str(data.get("recovery_drill_verdict") or ""),
        source_hash=str(data.get("source_hash") or ""),
        evidence_refs=_tuple(data.get("evidence_refs")),
        validation_result_refs=_tuple(data.get("validation_result_refs")),
        silent_mock_fallback_used=bool(data.get("silent_mock_fallback_used", False)),
    )


class PersistentMethodologyRuntimeDrillRegistry(_OwnerMethodologyRegistry):
    """Owner-scoped append-only registry for methodology runtime drills."""

    event_type = "methodology_runtime_drill_recorded"
    payload_key = "runtime_drill"
    ref_field = "runtime_drill_ref"

    def __init__(self, path: str | Path) -> None:
        self._by_fault_ref: dict[tuple[str, str], RuntimeDrillRecord] = {}
        self._by_recovery_ref: dict[tuple[str, str], RuntimeDrillRecord] = {}
        super().__init__(path)

    def _parse(self, raw: dict[str, Any]) -> RuntimeDrillRecord:
        return runtime_drill_record_from_dict(raw)

    def _validate(self, record: RuntimeDrillRecord) -> MethodologyDecision:
        return validate_runtime_drill(record)

    def _apply_row(self, row: dict[str, Any], *, persist: bool) -> RuntimeDrillRecord:
        record = super()._apply_row(row, persist=persist)
        owner = self._required(row.get("owner_user_id"), "owner_user_id")
        for mapping, nested_ref in (
            (self._by_fault_ref, record.fault_injection_ref),
            (self._by_recovery_ref, record.recovery_drill_ref),
        ):
            key = (owner, str(nested_ref))
            existing = mapping.get(key)
            if existing is not None and existing != record:
                raise ValueError("Methodology Runtime Drill nested ref collision")
            mapping[key] = record
        return record

    def record_runtime_drill(
        self,
        record: RuntimeDrillRecord,
        *,
        owner_user_id: str,
        recorded_by: str,
        source_run_ref: str,
        backtest_run_ref: str,
    ) -> RuntimeDrillRecord:
        return self._record(
            record,
            owner_user_id=owner_user_id,
            recorded_by=recorded_by,
            source_run_ref=source_run_ref,
            backtest_run_ref=backtest_run_ref,
        )

    def runtime_drill(self, runtime_drill_ref: str, *, owner_user_id: str) -> RuntimeDrillRecord:
        return self._get(runtime_drill_ref, owner_user_id=owner_user_id)

    def runtime_drill_binding(
        self,
        runtime_drill_ref: str,
        *,
        owner_user_id: str,
    ) -> ValidationEvidenceBinding:
        return self._binding(runtime_drill_ref, owner_user_id=owner_user_id)

    def runtime_drills(self, *, owner_user_id: str) -> list[RuntimeDrillRecord]:
        return self._all(owner_user_id=owner_user_id)

    def by_fault_injection_ref(
        self,
        fault_injection_ref: str,
        *,
        owner_user_id: str,
    ) -> RuntimeDrillRecord:
        return self._by_fault_ref[
            (self._required(owner_user_id, "owner_user_id"), str(fault_injection_ref))
        ]

    def by_recovery_drill_ref(
        self,
        recovery_drill_ref: str,
        *,
        owner_user_id: str,
    ) -> RuntimeDrillRecord:
        return self._by_recovery_ref[
            (self._required(owner_user_id, "owner_user_id"), str(recovery_drill_ref))
        ]


class PersistentMethodologyCalculatorRegistry:
    """Owner-scoped append-only registry for methodology calculator outputs."""

    def __init__(self, path: str | Path) -> None:
        self._path = Path(path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._lock_path = self._path.with_name(f".{self._path.name}.lock")
        self._lock = threading.RLock()
        self._cpcv: dict[tuple[str, str], CPCVCalculatorRecord] = {}
        self._conformal: dict[tuple[str, str], ConformalCalculatorRecord] = {}
        self._tca: dict[tuple[str, str], TCACalculatorRecord] = {}
        self._bindings: dict[tuple[str, str, str], ValidationEvidenceBinding] = {}
        self._legacy_quarantined_count = 0
        self._load_existing()

    @property
    def path(self) -> Path:
        return self._path

    @property
    def legacy_quarantined_count(self) -> int:
        return self._legacy_quarantined_count

    @staticmethod
    def _required(value: Any, field_name: str) -> str:
        value = str(value or "").strip()
        if not value:
            raise ValueError(f"{field_name} is required")
        return value

    def _load_existing(self) -> None:
        if not self._path.exists():
            return
        with self._path.open("r", encoding="utf-8") as fh:
            for line_no, line in enumerate(fh, start=1):
                if not line.strip():
                    continue
                try:
                    row = json.loads(line)
                    if row.get("schema_version") != 2:
                        self._legacy_quarantined_count += 1
                        continue
                    self._apply_row(row, persist=False)
                except Exception as exc:  # noqa: BLE001
                    raise ValueError(f"invalid persisted Methodology Calculator row at {self._path}:{line_no}") from exc

    def _append_event(self, row: dict[str, Any], *, kind: str, record_ref: str) -> None:
        fd = os.open(self._lock_path, os.O_RDWR | os.O_CREAT, 0o600)
        held = None
        try:
            os.chmod(self._lock_path, 0o600)
            held = acquire_exclusive_fd(fd, timeout_seconds=30.0)
            if self._path.exists():
                with self._path.open("r", encoding="utf-8") as existing_fh:
                    for line_no, line in enumerate(existing_fh, start=1):
                        if not line.strip():
                            continue
                        existing = json.loads(line)
                        raw = existing.get("calculator_record")
                        ref_field = {"cpcv": "cpcv_ref", "conformal": "conformal_ref", "tca": "tca_ref"}[kind]
                        if (
                            existing.get("schema_version") == 2
                            and existing.get("owner_user_id") == row.get("owner_user_id")
                            and existing.get("calculator_kind") == kind
                            and isinstance(raw, dict)
                            and str(raw.get(ref_field) or "") == record_ref
                        ):
                            if existing == row:
                                return
                            raise ValueError(
                                f"Methodology Calculator identity collision at {self._path}:{line_no}"
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

    def _apply_row(self, row: dict[str, Any], *, persist: bool) -> None:
        if row.get("schema_version") != 2:
            raise ValueError("Methodology Calculator owner envelope schema_version=2 is required")
        if row.get("event_type") != "methodology_calculator_recorded":
            raise ValueError(f"unknown Methodology Calculator event_type={row.get('event_type')!r}")
        kind = str(row.get("calculator_kind") or "")
        raw = row.get("calculator_record")
        if not isinstance(raw, dict):
            raise ValueError("Methodology Calculator event missing calculator_record")
        binding = ValidationEvidenceBinding(
            owner_user_id=self._required(row.get("owner_user_id"), "owner_user_id"),
            recorded_by=self._required(row.get("recorded_by"), "recorded_by"),
            source_run_ref=self._required(row.get("source_run_ref"), "source_run_ref"),
            backtest_run_ref=self._required(row.get("backtest_run_ref"), "backtest_run_ref"),
        )
        if kind == "cpcv":
            record = cpcv_calculator_record_from_dict(raw)
        elif kind == "conformal":
            record = conformal_calculator_record_from_dict(raw)
        elif kind == "tca":
            record = tca_calculator_record_from_dict(raw)
        else:
            raise ValueError(f"unknown methodology calculator kind={kind!r}")
        return self._record(record, kind=kind, binding=binding, persist=persist, row=row)

    @staticmethod
    def _kind_contract(record: Any) -> tuple[str, str, Any, Any]:
        if isinstance(record, CPCVCalculatorRecord):
            return "cpcv", record.cpcv_ref, validate_cpcv_calculator, "_cpcv"
        if isinstance(record, ConformalCalculatorRecord):
            return "conformal", record.conformal_ref, validate_conformal_calculator, "_conformal"
        if isinstance(record, TCACalculatorRecord):
            return "tca", record.tca_ref, validate_tca_calculator, "_tca"
        raise TypeError("unsupported methodology calculator record")

    def _record(
        self,
        record: Any,
        *,
        kind: str,
        binding: ValidationEvidenceBinding,
        persist: bool,
        row: dict[str, Any],
    ) -> Any:
        actual_kind, record_ref, validator, mapping_name = self._kind_contract(record)
        if actual_kind != kind:
            raise ValueError("methodology calculator kind mismatch")
        decision = validator(record)
        if not decision.accepted:
            raise ValueError(_decision_message(decision))
        key = (binding.owner_user_id, record_ref)
        binding_key = (binding.owner_user_id, kind, record_ref)
        mapping = getattr(self, mapping_name)
        with self._lock:
            existing = mapping.get(key)
            existing_binding = self._bindings.get(binding_key)
            if existing is not None:
                if existing != record or existing_binding != binding:
                    raise ValueError("Methodology Calculator identity collision with different content")
                return existing
            if persist:
                self._append_event(row, kind=kind, record_ref=record_ref)
            mapping[key] = record
            self._bindings[binding_key] = binding
            return record

    def _record_public(
        self,
        record: Any,
        *,
        owner_user_id: str,
        recorded_by: str,
        source_run_ref: str,
        backtest_run_ref: str,
    ) -> Any:
        kind, _record_ref, _validator, _mapping = self._kind_contract(record)
        binding = ValidationEvidenceBinding(
            owner_user_id=self._required(owner_user_id, "owner_user_id"),
            recorded_by=self._required(recorded_by, "recorded_by"),
            source_run_ref=self._required(source_run_ref, "source_run_ref"),
            backtest_run_ref=self._required(backtest_run_ref, "backtest_run_ref"),
        )
        row = {
            "schema_version": 2,
            "event_type": "methodology_calculator_recorded",
            "calculator_kind": kind,
            "owner_user_id": binding.owner_user_id,
            "recorded_by": binding.recorded_by,
            "source_run_ref": binding.source_run_ref,
            "backtest_run_ref": binding.backtest_run_ref,
            "calculator_record": _json_value(record),
        }
        return self._record(record, kind=kind, binding=binding, persist=True, row=row)

    def record_cpcv(self, record: CPCVCalculatorRecord, **binding: str) -> CPCVCalculatorRecord:
        return self._record_public(record, **binding)

    def record_conformal(
        self,
        record: ConformalCalculatorRecord,
        **binding: str,
    ) -> ConformalCalculatorRecord:
        return self._record_public(record, **binding)

    def record_tca(self, record: TCACalculatorRecord, **binding: str) -> TCACalculatorRecord:
        return self._record_public(record, **binding)

    def cpcv(self, cpcv_ref: str, *, owner_user_id: str) -> CPCVCalculatorRecord:
        return self._cpcv[(self._required(owner_user_id, "owner_user_id"), cpcv_ref)]

    def conformal(self, conformal_ref: str, *, owner_user_id: str) -> ConformalCalculatorRecord:
        return self._conformal[(self._required(owner_user_id, "owner_user_id"), conformal_ref)]

    def tca(self, tca_ref: str, *, owner_user_id: str) -> TCACalculatorRecord:
        return self._tca[(self._required(owner_user_id, "owner_user_id"), tca_ref)]

    def binding(self, kind: str, record_ref: str, *, owner_user_id: str) -> ValidationEvidenceBinding:
        return self._bindings[(self._required(owner_user_id, "owner_user_id"), kind, record_ref)]

    def cpcv_records(self, *, owner_user_id: str) -> list[CPCVCalculatorRecord]:
        owner = self._required(owner_user_id, "owner_user_id")
        return [record for (record_owner, _ref), record in self._cpcv.items() if record_owner == owner]

    def conformal_records(self, *, owner_user_id: str) -> list[ConformalCalculatorRecord]:
        owner = self._required(owner_user_id, "owner_user_id")
        return [record for (record_owner, _ref), record in self._conformal.items() if record_owner == owner]

    def tca_records(self, *, owner_user_id: str) -> list[TCACalculatorRecord]:
        owner = self._required(owner_user_id, "owner_user_id")
        return [record for (record_owner, _ref), record in self._tca.items() if record_owner == owner]


__all__ = [
    "CPCVCalculatorRecord",
    "ConformalCalculatorRecord",
    "LiveMonitoringAlertRecord",
    "MethodologyChoiceCoverageRecord",
    "MethodologyDecision",
    "MethodologyViolation",
    "PersistentMethodologyCalculatorRegistry",
    "PersistentMethodologyRuntimeDrillRegistry",
    "PersistentValidationMethodologyRegistry",
    "PersistentValidationDepthRegistry",
    "RuntimeDrillRecord",
    "TCACalculatorRecord",
    "ValidationDepthRecord",
    "ValidationEvidenceBinding",
    "ValidationMethodologyRecord",
    "calculate_conformal",
    "calculate_cpcv",
    "calculate_tca",
    "conformal_calculator_record_from_dict",
    "cpcv_calculator_record_from_dict",
    "record_runtime_drill",
    "runtime_drill_record_from_dict",
    "tca_calculator_record_from_dict",
    "validate_conformal_calculator",
    "validate_cpcv_calculator",
    "validation_depth_record_from_dict",
    "validation_methodology_record_from_dict",
    "validate_live_monitoring_alert",
    "validate_methodology_choice_coverage",
    "validate_methodology_contract",
    "validate_runtime_drill",
    "validate_tca_calculator",
    "validate_validation_depth",
    "validate_validation_methodology",
]
