"""GOAL §16 engineering standards and fatal-error contracts."""

from __future__ import annotations

import hashlib
import json
import os
import threading
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from ..cross_process_lock import acquire_exclusive_fd


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


PERF_PASS = "pass"
PERF_FAIL = "fail"
PERF_KNOWN_RUN_GAP = "known_run_gap"


@dataclass(frozen=True)
class PerformanceBaselineMeasurement:
    """A benchmark observation for one GOAL §16 performance baseline.

    Two honest states only:
    - measured=True  -> a real timing was taken; ``observed_seconds`` and
      ``evidence_ref`` describe it.
    - measured=False -> the production baseline could not be measured in this
      environment (missing real data / live corpus / browser). ``unavailable_reason``
      states why. This is a KNOWN_RUN_GAP and is **never** a pass.

    A fabricated observed time is never allowed to stand in for an unavailable
    measurement: classify treats measured=False as a gap regardless of any other
    field, so honesty cannot be gamed into green.
    """

    baseline_ref: str
    metric_name: str
    threshold_seconds: float
    measured: bool
    observed_seconds: float | None = None
    evidence_ref: str | None = None
    unavailable_reason: str | None = None
    detail: str = ""


@dataclass(frozen=True)
class PerformanceBaselineVerdict:
    measurement: PerformanceBaselineMeasurement
    status: str
    decision: EngineeringStandardDecision | None

    @property
    def is_pass(self) -> bool:
        return self.status == PERF_PASS

    @property
    def is_known_run_gap(self) -> bool:
        return self.status == PERF_KNOWN_RUN_GAP


@dataclass(frozen=True)
class EngineeringStandardsRunRecord:
    """Content-addressed §16 evidence package for one exact source run.

    Authorization is deliberately not embedded in the portable record.  The
    persistent registry adds a server-derived owner envelope and keys reads by
    ``(owner_user_id, source_run_ref)``.
    """

    source_run_ref: str
    mock_records: tuple[MockHonestyRecord, ...]
    data_updates: tuple[DataUpdateStandardRecord, ...]
    llm_calls: tuple[LLMReplayStandardRecord, ...]
    theory_claims: tuple[TheoryImplementationStandardRecord, ...]
    fatal_records: tuple[FatalRuntimeStandardRecord, ...]
    performance_records: tuple[PerformanceBaselineMeasurement, ...]
    record_ref: str = ""
    record_version: str = "engineering_standards_run.v1"

    def __post_init__(self) -> None:
        for field_name in (
            "mock_records",
            "data_updates",
            "llm_calls",
            "theory_claims",
            "fatal_records",
            "performance_records",
        ):
            object.__setattr__(self, field_name, tuple(getattr(self, field_name)))
        if not self.record_ref:
            object.__setattr__(self, "record_ref", self.canonical_record_ref)

    @property
    def canonical_record_ref(self) -> str:
        payload = asdict(self)
        payload.pop("record_ref", None)
        encoded = json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return f"engstd_{hashlib.sha256(encoded).hexdigest()}"


def classify_performance_baseline(
    measurement: PerformanceBaselineMeasurement,
) -> PerformanceBaselineVerdict:
    """Honest 3-state verdict for a benchmark observation.

    - not measured -> KNOWN_RUN_GAP (never a pass; no fabricated observed time).
    - measured     -> reuse ``validate_performance_baseline`` for the threshold +
      evidence rules. PASS iff the validator accepts, else FAIL.

    This reuses ``validate_performance_baseline`` and does NOT reimplement the
    over-threshold / missing-evidence logic. It is the single source of pass/fail
    truth for the benchmark harness, so weakening it (e.g. letting an
    over-threshold measurement pass, or treating a gap as green) is caught by the
    harness mutation guard.
    """
    if not measurement.measured:
        return PerformanceBaselineVerdict(measurement, PERF_KNOWN_RUN_GAP, None)
    if measurement.observed_seconds is None:
        raise ValueError(
            "measured performance baseline requires observed_seconds; "
            "use measured=False to record a KNOWN_RUN_GAP"
        )
    decision = validate_performance_baseline(
        PerformanceBaselineRecord(
            baseline_ref=measurement.baseline_ref,
            metric_name=measurement.metric_name,
            observed_seconds=measurement.observed_seconds,
            threshold_seconds=measurement.threshold_seconds,
            evidence_ref=measurement.evidence_ref,
        )
    )
    status = PERF_PASS if decision.accepted else PERF_FAIL
    return PerformanceBaselineVerdict(measurement, status, decision)


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


_RUN_FAMILY_REF_FIELDS = (
    ("mock_records", "record_ref"),
    ("data_updates", "update_ref"),
    ("llm_calls", "call_ref"),
    ("theory_claims", "claim_ref"),
    ("fatal_records", "runtime_ref"),
    ("performance_records", "baseline_ref"),
)


def validate_engineering_standards_run_record(
    record: EngineeringStandardsRunRecord,
) -> EngineeringStandardDecision:
    """Validate a complete six-family package before it can become a receipt."""

    violations: list[EngineeringStandardViolation] = []

    def reject(code: str, message: str, *, field: str = "", ref: str = "") -> None:
        violations.append(
            EngineeringStandardViolation(code, message, field=field, ref=ref)
        )

    if not _present(record.source_run_ref):
        reject(
            "engineering_standard_source_run_required",
            "engineering standards packages require an exact source_run_ref",
            field="source_run_ref",
        )
    if record.record_version != "engineering_standards_run.v1":
        reject(
            "engineering_standard_record_version_unsupported",
            "unsupported engineering standards record version",
            field="record_version",
            ref=record.record_ref,
        )
    if record.record_ref != record.canonical_record_ref:
        reject(
            "engineering_standard_record_ref_mismatch",
            "record_ref must equal the content-addressed engineering standards identity",
            field="record_ref",
            ref=record.record_ref,
        )

    for family_name, ref_field in _RUN_FAMILY_REF_FIELDS:
        family = tuple(getattr(record, family_name))
        if not family:
            reject(
                "engineering_standard_family_missing",
                "a producer receipt requires all six canonical §16 families",
                field=family_name,
                ref=record.record_ref,
            )
            continue
        refs = [str(getattr(item, ref_field, "") or "").strip() for item in family]
        if any(not ref for ref in refs) or len(refs) != len(set(refs)):
            reject(
                "engineering_standard_family_ref_invalid",
                "family record refs must be non-empty and unique",
                field=family_name,
                ref=record.record_ref,
            )

    canonical = validate_engineering_standards(
        mock_records=record.mock_records,
        data_updates=record.data_updates,
        llm_calls=record.llm_calls,
        theory_claims=record.theory_claims,
        fatal_records=record.fatal_records,
    )
    violations.extend(canonical.violations)
    for measurement in record.performance_records:
        try:
            verdict = classify_performance_baseline(measurement)
        except (TypeError, ValueError) as exc:
            reject(
                "performance_baseline_unparseable",
                f"performance baseline could not be classified: {type(exc).__name__}",
                field="performance_records",
                ref=measurement.baseline_ref,
            )
            continue
        if verdict.is_known_run_gap:
            reject(
                "performance_baseline_known_run_gap",
                "unmeasured performance baselines cannot mint a §16 producer receipt",
                field="performance_records",
                ref=measurement.baseline_ref,
            )
        elif verdict.decision is not None:
            violations.extend(verdict.decision.violations)
    return EngineeringStandardDecision(not violations, tuple(violations))


def engineering_standards_run_record_to_dict(
    record: EngineeringStandardsRunRecord,
) -> dict[str, Any]:
    return asdict(record)


def _family_rows(raw: dict[str, Any], field_name: str) -> tuple[dict[str, Any], ...]:
    value = raw.get(field_name)
    if not isinstance(value, (list, tuple)):
        raise TypeError(f"{field_name} must be a list")
    rows = tuple(value)
    if any(not isinstance(item, dict) for item in rows):
        raise TypeError(f"{field_name} items must be objects")
    return rows


def engineering_standards_run_record_from_dict(
    raw: dict[str, Any],
) -> EngineeringStandardsRunRecord:
    if not isinstance(raw, dict):
        raise TypeError("engineering standards run record must be an object")
    return EngineeringStandardsRunRecord(
        source_run_ref=str(raw.get("source_run_ref") or ""),
        mock_records=tuple(
            MockHonestyRecord(**item) for item in _family_rows(raw, "mock_records")
        ),
        data_updates=tuple(
            DataUpdateStandardRecord(**item)
            for item in _family_rows(raw, "data_updates")
        ),
        llm_calls=tuple(
            LLMReplayStandardRecord(**item)
            for item in _family_rows(raw, "llm_calls")
        ),
        theory_claims=tuple(
            TheoryImplementationStandardRecord(**item)
            for item in _family_rows(raw, "theory_claims")
        ),
        fatal_records=tuple(
            FatalRuntimeStandardRecord(**item)
            for item in _family_rows(raw, "fatal_records")
        ),
        performance_records=tuple(
            PerformanceBaselineMeasurement(**item)
            for item in _family_rows(raw, "performance_records")
        ),
        record_ref=str(raw.get("record_ref") or ""),
        record_version=str(
            raw.get("record_version") or "engineering_standards_run.v1"
        ),
    )


class PersistentEngineeringStandardsRegistry:
    """Append-only, owner-enveloped registry for complete §16 run packages."""

    def __init__(self, path: str | Path) -> None:
        self._path = Path(path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._lock_path = self._path.with_name(f".{self._path.name}.lock")
        self._lock = threading.RLock()
        self._by_source: dict[tuple[str, str], EngineeringStandardsRunRecord] = {}
        self._by_ref: dict[tuple[str, str], EngineeringStandardsRunRecord] = {}
        self._quarantined_legacy_rows = 0
        self._load_existing()

    @property
    def path(self) -> Path:
        return self._path

    @property
    def quarantined_legacy_rows(self) -> int:
        return self._quarantined_legacy_rows

    @staticmethod
    def _owner(value: Any) -> str:
        owner = str(value or "").strip()
        if not owner:
            raise ValueError("engineering standards owner_user_id is required")
        return owner

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
                        self._quarantined_legacy_rows += 1
                        continue
                    self._apply_row(row, persist=False)
                except Exception as exc:  # noqa: BLE001 - malformed current history blocks startup.
                    raise ValueError(
                        f"invalid persisted engineering standards row at {self._path}:{line_no}"
                    ) from exc

    def _append_event(self, row: dict[str, Any]) -> None:
        fd = os.open(self._lock_path, os.O_RDWR | os.O_CREAT, 0o600)
        held = None
        try:
            os.chmod(self._lock_path, 0o600)
            held = acquire_exclusive_fd(fd, timeout_seconds=30.0)
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

    def _apply_row(
        self,
        row: dict[str, Any],
        *,
        persist: bool,
    ) -> EngineeringStandardsRunRecord:
        if row.get("schema_version") != 2:
            raise ValueError("engineering standards owner envelope schema_version=2 is required")
        if row.get("event_type") != "engineering_standards_run_recorded":
            raise ValueError("unknown engineering standards event_type")
        owner = self._owner(row.get("owner_user_id"))
        recorded_by = str(row.get("recorded_by") or "").strip()
        if not recorded_by:
            raise ValueError("engineering standards recorded_by is required")
        raw = row.get("record")
        if not isinstance(raw, dict):
            raise ValueError("engineering standards event missing record")
        return self._record(
            engineering_standards_run_record_from_dict(raw),
            owner_user_id=owner,
            recorded_by=recorded_by,
            persist=persist,
        )

    def record_run(
        self,
        record: EngineeringStandardsRunRecord,
        *,
        owner_user_id: str,
        recorded_by: str,
    ) -> EngineeringStandardsRunRecord:
        return self._record(
            record,
            owner_user_id=owner_user_id,
            recorded_by=recorded_by,
            persist=True,
        )

    def _record(
        self,
        record: EngineeringStandardsRunRecord,
        *,
        owner_user_id: str,
        recorded_by: str,
        persist: bool,
    ) -> EngineeringStandardsRunRecord:
        if not isinstance(record, EngineeringStandardsRunRecord):
            raise TypeError("record must be EngineeringStandardsRunRecord")
        owner = self._owner(owner_user_id)
        actor = str(recorded_by or "").strip()
        if not actor:
            raise ValueError("engineering standards recorded_by is required")
        decision = validate_engineering_standards_run_record(record)
        if not decision.accepted:
            raise ValueError(
                "; ".join(violation.code for violation in decision.violations)
            )
        source_key = (owner, record.source_run_ref)
        ref_key = (owner, record.record_ref)
        with self._lock:
            source_existing = self._by_source.get(source_key)
            ref_existing = self._by_ref.get(ref_key)
            for existing in (source_existing, ref_existing):
                if existing is not None:
                    if existing != record:
                        raise ValueError(
                            "engineering standards identity collision with different content"
                        )
                    return existing
            if persist:
                self._append_event(
                    {
                        "schema_version": 2,
                        "event_type": "engineering_standards_run_recorded",
                        "owner_user_id": owner,
                        "recorded_by": actor,
                        "record": engineering_standards_run_record_to_dict(record),
                    }
                )
            self._by_source[source_key] = record
            self._by_ref[ref_key] = record
            return record

    def run_record(
        self,
        source_run_ref: str,
        *,
        owner_user_id: str,
    ) -> EngineeringStandardsRunRecord:
        return self._by_source[(self._owner(owner_user_id), str(source_run_ref))]

    def record(
        self,
        record_ref: str,
        *,
        owner_user_id: str,
    ) -> EngineeringStandardsRunRecord:
        return self._by_ref[(self._owner(owner_user_id), str(record_ref))]

    def records(self, *, owner_user_id: str) -> list[EngineeringStandardsRunRecord]:
        owner = self._owner(owner_user_id)
        return [
            record
            for (record_owner, _source_ref), record in self._by_source.items()
            if record_owner == owner
        ]


__all__ = [
    "DataUpdateStandardRecord",
    "EngineeringStandardDecision",
    "EngineeringStandardsRunRecord",
    "EngineeringStandardViolation",
    "FatalRuntimeStandardRecord",
    "LLMReplayStandardRecord",
    "MockHonestyRecord",
    "PERF_FAIL",
    "PERF_KNOWN_RUN_GAP",
    "PERF_PASS",
    "PerformanceBaselineMeasurement",
    "PerformanceBaselineRecord",
    "PerformanceBaselineVerdict",
    "PersistentEngineeringStandardsRegistry",
    "TheoryImplementationStandardRecord",
    "classify_performance_baseline",
    "engineering_standards_run_record_from_dict",
    "engineering_standards_run_record_to_dict",
    "validate_data_update_standard",
    "validate_engineering_standards",
    "validate_engineering_standards_run_record",
    "validate_fatal_runtime_standard",
    "validate_llm_replay_standard",
    "validate_mock_honesty",
    "validate_performance_baseline",
    "validate_theory_implementation_standard",
]
