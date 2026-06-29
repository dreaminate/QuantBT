"""GOAL §16 engineering standards and fatal-error contracts."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import asdict, dataclass
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


# ════════════════════════════════════════════════════════════════════════════
# NC-S16-ENGSTD-PRODUCER · §16 工程标准 manifest record builder（孤立·扩展不替换·只忠实序列化·零判定）
# ────────────────────────────────────────────────────────────────────────────
# 缺口（construction-map NC-S16-ENGSTD-PRODUCER）：§16 门 `section16_engineering_standards_gate.check` 已建，
# 但 promote 真路径从未把真工程证据如实写进 manifest 的 `section16_engineering_standards` 结构，故门恒见
# 「未声明」、producer（`s16_engineering_standards_runjson_producers`）无真对象可证、无从诚实转绿。本段补这块：
# 从 6 族 typed 工程证据（本模块既有 record 类型·复用不另造）**忠实序列化**成门 check 读的 manifest record。
#
# 与门侧 `_adapt_*` 的关系（faithful round-trip 的根）：各族 record 的字段名 **即** 门 `_adapt_*` 读的 key
# （同模块同口径），故 `asdict(record)` 产出的 dict 字段与门期望逐一对应——producer 序列化 → 门 adapter 还原
# → canonical validator 裁定，三段忠实往返。本 builder **绝不**重写任何工程标准判定，连违例码都不碰。
#
# 诚实红线（= GOAL §16「no silent mock / no template false success / 未追踪数据不得发版」对准 producer 自己）：
#   - **零判定·只序列化**：逐字段照搬 typed record 进 dict，过没过全留门 check →
#     `validate_engineering_standards` / `classify_performance_baseline`（单一源）。
#   - **不洗白·缺诚实空**：record 的 None/空字段原样序列化 → 门据真值 surface 违例 / KNOWN_RUN_GAP。绝不补
#     label / 造 observed 时间 / 填假 checksum（洗白=假绿灯·撞 RULES.project「未验证≠已验证」）。
#   - **honest-absent**：某族无 record → 不发该族 key；6 族全空 → 返回 `{}`（中心 `_take` 据此标缺·门
#     honest-bound：未声明≠违例·非「整本已查清」·查清由 producer 绿灯门负责）。
#   - **性能族强制用 3 态诚实量 `PerformanceBaselineMeasurement`**（带 `measured` 旗）而非
#     `PerformanceBaselineRecord`：只有 3 态量能表达「未实测」(measured=False)，从根上杜绝把没做的测量洗成达标。
#   - **fail-closed 入参**：喂错族类型对象 → raise TypeError（不静默吞坏输入·不产错位 manifest 记录）。
# ════════════════════════════════════════════════════════════════════════════

# 6 族 → (族内 manifest key, 期望 record 类型)。族内 key 即门 check 的 `_RECORD_FAMILIES` + `_PERFORMANCE_KEY`
# 契约（producer↔gate round-trip·由 wiring 测试钉防漂）。性能族强制 `PerformanceBaselineMeasurement`（3 态）。
_SECTION16_RECORD_FAMILIES: tuple[tuple[str, type], ...] = (
    ("mock_records", MockHonestyRecord),
    ("data_updates", DataUpdateStandardRecord),
    ("llm_calls", LLMReplayStandardRecord),
    ("theory_claims", TheoryImplementationStandardRecord),
    ("fatal_records", FatalRuntimeStandardRecord),
    ("performance_records", PerformanceBaselineMeasurement),
)


def _to_json_safe(value: Any) -> Any:
    """JSON 结构归一（tuple→list·dict→dict·标量原样·递归）—— manifest 是 run.json·须 JSON-safe。

    **无损·绝不改任何字段值**：坏值 / None 原样保留，让门据真值判（不洗白）。
    """

    if isinstance(value, dict):
        return {str(k): _to_json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_to_json_safe(v) for v in value]
    return value


def _engineering_record_to_manifest_dict(record: Any) -> dict[str, Any]:
    """单条 §16 工程证据 typed record → manifest dict（faithful·逐字段照搬·零判定零洗白）。

    `dataclasses.asdict` 全字段展开（不漏字段·结构上无从挑字段藏），再 `_to_json_safe` 归一 tuple→list。
    None/空字段原样保留 → 门 check 据真值 surface 违例 / KNOWN_RUN_GAP。本函数无任何「补默认 / 填占位 /
    造时间」分支 → producer 不洗白的硬保证。

    ★ producer mutation 三态锚点（已手验·见 test 文件头）：把本函数改成 None-洗白
      `{k: (v if v is not None else "__filled__") for k, v in asdict(record).items()}` → 12 个依赖「忠实保留
      None/缺省」的对抗测试转 RED（洗白双向作恶：既抹掉真违例——mock 缺 label / data 缺 version / llm 缺
      provider / 强理论缺 binding；又凭空造假违例——把合规记录的 None user_waiver_ref 洗成「有 waiver」误拒
      合规 run；还把性能 observed_seconds=None 洗成非数串使 float() 炸成 unparseable）；与 None 正交的
      bool/数值/tuple 判定（生产档 mock 兜底 / 致命密钥 tuple / perf 超标数值）+ honest-absent（无 record 可洗）
      + 结构/类型/冷导入测试 共 12 个仍 GREEN → 还原 → 全 24 GREEN。
    """

    return _to_json_safe(asdict(record))


def _serialize_section16_family(
    records: Sequence[Any], expected: type, family: str
) -> list[dict[str, Any]]:
    """一族 typed record → list[dict]·fail-closed 校验每项类型（不静默吞坏输入·不产错位记录）。

    喂错族类型（把 MockHonestyRecord 塞进 data_updates·或把 `PerformanceBaselineRecord` 塞进
    performance_records 而非 3 态 `PerformanceBaselineMeasurement`）→ raise TypeError（fail-closed）。
    """

    out: list[dict[str, Any]] = []
    for rec in records or ():
        if not isinstance(rec, expected):
            raise TypeError(
                f"section16 producer: {family} 须为 {expected.__name__}，"
                f"得到 {type(rec).__name__}（fail-closed·不静默吞坏输入·不产错位 manifest 记录）"
            )
        out.append(_engineering_record_to_manifest_dict(rec))
    return out


def build_section16_engineering_standards_record(
    *,
    mock_records: Sequence[MockHonestyRecord] = (),
    data_updates: Sequence[DataUpdateStandardRecord] = (),
    llm_calls: Sequence[LLMReplayStandardRecord] = (),
    theory_claims: Sequence[TheoryImplementationStandardRecord] = (),
    fatal_records: Sequence[FatalRuntimeStandardRecord] = (),
    performance_records: Sequence[PerformanceBaselineMeasurement] = (),
) -> dict[str, list[dict[str, Any]]]:
    """6 族 typed 工程证据 → §16 门 check 读的 `section16_engineering_standards` manifest record（payload）。

    [契约] 返回值 = manifest 里 `section16_engineering_standards` key 的 **payload**（6 族 dict），**不含**外层
    key——key 名是 `section16_engineering_standards_gate.SECTION16_ENGINEERING_STANDARDS_MANIFEST_KEY` 单一源，
    由中心 `promote_assembler.assemble_promote_sections` 经 `_take` 套上。本 builder 在更低层（research_os），
    刻意**不**引该常量（防 gate→engineering_standards 反向循环导入）。族内 key 即门 check 的
    `_RECORD_FAMILIES` + `_PERFORMANCE_KEY` 契约（producer↔gate round-trip·由 wiring 测试钉防漂）。

    [行为] 每族：有 record → 序列化进 payload；无 record → 不发该族 key；6 族全空 → 返回 `{}`（honest-absent）。
    判定全委托门 check → canonical（本 builder 零判定·见上方段头诚实红线）。
    """

    bound: dict[str, Sequence[Any]] = {
        "mock_records": mock_records,
        "data_updates": data_updates,
        "llm_calls": llm_calls,
        "theory_claims": theory_claims,
        "fatal_records": fatal_records,
        "performance_records": performance_records,
    }
    section: dict[str, list[dict[str, Any]]] = {}
    for family, expected in _SECTION16_RECORD_FAMILIES:
        serialized = _serialize_section16_family(bound[family], expected, family)
        if serialized:  # honest-absent：空族不发 key（中心 _take 据 payload 真伪标缺·绝不发空壳让门误判）
            section[family] = serialized
    return section


__all__ = [
    "DataUpdateStandardRecord",
    "EngineeringStandardDecision",
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
    "TheoryImplementationStandardRecord",
    "build_section16_engineering_standards_record",
    "classify_performance_baseline",
    "validate_data_update_standard",
    "validate_engineering_standards",
    "validate_fatal_runtime_standard",
    "validate_llm_replay_standard",
    "validate_mock_honesty",
    "validate_performance_baseline",
    "validate_theory_implementation_standard",
]
