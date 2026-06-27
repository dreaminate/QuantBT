"""GOAL §16 engineering standards and fatal-error contracts."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


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


STRONG_LABELS = {"proof_backed", "evidence_sufficient", "production_ready"}


@dataclass(frozen=True)
class EngineeringStandardViolation:
    code: str
    message: str
    field: str = ""
    ref: str = ""


@dataclass(frozen=True)
class EngineeringStandardDecision:
    accepted: bool
    violations: tuple[EngineeringStandardViolation, ...]


@dataclass(frozen=True)
class MockHonestyRecord:
    record_ref: str
    production_profile: bool
    mock_used: bool
    mock_label_ref: str | None
    fallback_reason_ref: str | None
    template_response: bool
    production_success_claim: bool


@dataclass(frozen=True)
class DataUpdateStandardRecord:
    update_ref: str
    dataset_version_ref: str | None
    checksum: str | None
    lineage_ref: str | None
    known_at_ref: str | None
    effective_at_ref: str | None
    data_test_refs: tuple[str, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "data_test_refs", _tuple(self.data_test_refs))


@dataclass(frozen=True)
class LLMReplayStandardRecord:
    call_ref: str
    provider_ref: str | None
    model_ref: str | None
    auth_ref: str | None
    cost_ref: str | None
    replay_state_ref: str | None
    llm_gateway_ref: str | None
    prompt_hash: str | None
    tool_schema_hash: str | None


@dataclass(frozen=True)
class TheoryImplementationStandardRecord:
    claim_ref: str
    display_label: str
    theory_implementation_binding_ref: str | None
    consistency_check_ref: str | None
    user_waiver_ref: str | None = None


@dataclass(frozen=True)
class FatalRuntimeStandardRecord:
    runtime_ref: str
    secret_plaintext_surfaces: tuple[str, ...]
    role_agent_bypassed_llm_gateway: bool = False
    verifier_independence_claimed: bool = False
    verifier_independence_record_ref: str | None = None
    a_share_live_order: bool = False
    production_mock_fallback: bool = False
    lookahead_leakage_detected: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(self, "secret_plaintext_surfaces", _tuple(self.secret_plaintext_surfaces))


@dataclass(frozen=True)
class PerformanceBaselineRecord:
    baseline_ref: str
    metric_name: str
    observed_seconds: float
    threshold_seconds: float
    evidence_ref: str | None


def validate_mock_honesty(record: MockHonestyRecord) -> EngineeringStandardDecision:
    violations: list[EngineeringStandardViolation] = []
    if record.mock_used and (not _present(record.mock_label_ref) or not _present(record.fallback_reason_ref)):
        violations.append(
            EngineeringStandardViolation(
                "mock_block_missing_label_or_reason",
                "mock/fallback blocks require label and fallback reason",
                field="mock_label_ref",
                ref=record.record_ref,
            )
        )
    if record.production_profile and record.mock_used:
        violations.append(
            EngineeringStandardViolation(
                "production_profile_mock_fallback",
                "production profile cannot silently succeed through mock fallback",
                field="mock_used",
                ref=record.record_ref,
            )
        )
    if record.production_success_claim and (record.mock_used or record.template_response):
        violations.append(
            EngineeringStandardViolation(
                "template_or_mock_false_production_success",
                "template/mock response cannot generate production success",
                field="production_success_claim",
                ref=record.record_ref,
            )
        )
    return EngineeringStandardDecision(accepted=not violations, violations=tuple(violations))


def validate_data_update_standard(record: DataUpdateStandardRecord) -> EngineeringStandardDecision:
    violations: list[EngineeringStandardViolation] = []
    for field_name in ("dataset_version_ref", "checksum", "lineage_ref", "known_at_ref", "effective_at_ref"):
        if not _present(getattr(record, field_name)):
            violations.append(
                EngineeringStandardViolation(
                    "data_update_missing_version_checksum_lineage",
                    "data updates require dataset_version, checksum, lineage, known_at, and effective_at",
                    field=field_name,
                    ref=record.update_ref,
                )
            )
    if len(record.data_test_refs) < 5:
        violations.append(
            EngineeringStandardViolation(
                "data_update_too_few_data_tests",
                "each table requires at least five data tests",
                field="data_test_refs",
                ref=record.update_ref,
            )
        )
    return EngineeringStandardDecision(accepted=not violations, violations=tuple(violations))


def validate_llm_replay_standard(record: LLMReplayStandardRecord) -> EngineeringStandardDecision:
    violations: list[EngineeringStandardViolation] = []
    for field_name in (
        "provider_ref",
        "model_ref",
        "auth_ref",
        "cost_ref",
        "replay_state_ref",
        "llm_gateway_ref",
        "prompt_hash",
        "tool_schema_hash",
    ):
        if not _present(getattr(record, field_name)):
            violations.append(
                EngineeringStandardViolation(
                    "llm_replay_missing_required_ref",
                    "LLM calls require provider/model/auth/cost/replay/gateway/hash records",
                    field=field_name,
                    ref=record.call_ref,
                )
            )
    return EngineeringStandardDecision(accepted=not violations, violations=tuple(violations))


def validate_theory_implementation_standard(
    record: TheoryImplementationStandardRecord,
) -> EngineeringStandardDecision:
    violations: list[EngineeringStandardViolation] = []
    if record.display_label in STRONG_LABELS:
        for field_name in ("theory_implementation_binding_ref", "consistency_check_ref"):
            if not _present(getattr(record, field_name)):
                violations.append(
                    EngineeringStandardViolation(
                        "strong_theory_claim_missing_binding_or_consistency",
                        "proof-backed implementation requires TheoryImplementationBinding and ConsistencyCheck",
                        field=field_name,
                        ref=record.claim_ref,
                    )
                )
        if _present(record.user_waiver_ref):
            violations.append(
                EngineeringStandardViolation(
                    "user_waiver_displayed_as_strong_evidence",
                    "user waiver cannot be displayed as strong system evidence",
                    field="user_waiver_ref",
                    ref=record.claim_ref,
                )
            )
    return EngineeringStandardDecision(accepted=not violations, violations=tuple(violations))


def validate_fatal_runtime_standard(record: FatalRuntimeStandardRecord) -> EngineeringStandardDecision:
    violations: list[EngineeringStandardViolation] = []
    if record.secret_plaintext_surfaces:
        violations.append(
            EngineeringStandardViolation(
                "secret_plaintext_left_secure_backend",
                "plaintext secrets must not enter Agent, RAG, logs, or export packages",
                field="secret_plaintext_surfaces",
                ref=record.runtime_ref,
            )
        )
    if record.role_agent_bypassed_llm_gateway:
        violations.append(
            EngineeringStandardViolation(
                "role_agent_bypassed_llm_gateway",
                "role agents must use LLM Gateway",
                field="role_agent_bypassed_llm_gateway",
                ref=record.runtime_ref,
            )
        )
    if record.verifier_independence_claimed and not _present(record.verifier_independence_record_ref):
        violations.append(
            EngineeringStandardViolation(
                "verifier_independence_record_missing",
                "verifier independence claims require provider/model/context record",
                field="verifier_independence_record_ref",
                ref=record.runtime_ref,
            )
        )
    fatal_flags = {
        "a_share_live_order": record.a_share_live_order,
        "production_mock_fallback": record.production_mock_fallback,
        "lookahead_leakage_detected": record.lookahead_leakage_detected,
    }
    for field_name, active in fatal_flags.items():
        if active:
            violations.append(
                EngineeringStandardViolation(
                    "fatal_engineering_error_detected",
                    "fatal engineering error detected",
                    field=field_name,
                    ref=record.runtime_ref,
                )
            )
    return EngineeringStandardDecision(accepted=not violations, violations=tuple(violations))


def validate_performance_baseline(record: PerformanceBaselineRecord) -> EngineeringStandardDecision:
    violations: list[EngineeringStandardViolation] = []
    if record.observed_seconds > record.threshold_seconds:
        violations.append(
            EngineeringStandardViolation(
                "performance_baseline_exceeded",
                "performance baseline exceeded",
                field="observed_seconds",
                ref=record.baseline_ref,
            )
        )
    if not _present(record.evidence_ref):
        violations.append(
            EngineeringStandardViolation(
                "performance_baseline_missing_evidence",
                "performance baseline requires measured evidence",
                field="evidence_ref",
                ref=record.baseline_ref,
            )
        )
    return EngineeringStandardDecision(accepted=not violations, violations=tuple(violations))


def validate_engineering_standards(
    *,
    mock_records: tuple[MockHonestyRecord, ...] = (),
    data_updates: tuple[DataUpdateStandardRecord, ...] = (),
    llm_calls: tuple[LLMReplayStandardRecord, ...] = (),
    theory_claims: tuple[TheoryImplementationStandardRecord, ...] = (),
    fatal_records: tuple[FatalRuntimeStandardRecord, ...] = (),
    performance_records: tuple[PerformanceBaselineRecord, ...] = (),
) -> EngineeringStandardDecision:
    violations: list[EngineeringStandardViolation] = []
    for record in mock_records:
        violations.extend(validate_mock_honesty(record).violations)
    for record in data_updates:
        violations.extend(validate_data_update_standard(record).violations)
    for record in llm_calls:
        violations.extend(validate_llm_replay_standard(record).violations)
    for record in theory_claims:
        violations.extend(validate_theory_implementation_standard(record).violations)
    for record in fatal_records:
        violations.extend(validate_fatal_runtime_standard(record).violations)
    for record in performance_records:
        violations.extend(validate_performance_baseline(record).violations)
    return EngineeringStandardDecision(accepted=not violations, violations=tuple(violations))


__all__ = [
    "DataUpdateStandardRecord",
    "EngineeringStandardDecision",
    "EngineeringStandardViolation",
    "FatalRuntimeStandardRecord",
    "LLMReplayStandardRecord",
    "MockHonestyRecord",
    "PerformanceBaselineRecord",
    "TheoryImplementationStandardRecord",
    "validate_data_update_standard",
    "validate_engineering_standards",
    "validate_fatal_runtime_standard",
    "validate_llm_replay_standard",
    "validate_mock_honesty",
    "validate_performance_baseline",
    "validate_theory_implementation_standard",
]
