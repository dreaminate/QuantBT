"""C-S16-ENG-STD-PROMOTE-ENFORCE · §16 工程标准发版 check（插 SA-3 promote 门链）。

这张卡只建 PARALLEL-SAFE 的 check + 注册函数——把（后端库级已建的）§16 工程标准 6 族判定经 SA-3 门链接到
promote 收口，关掉 codemap 点出的洞：`research_os/engineering_standards.py` 的 6 族 validator 今 library-only，
从未在真 release/promote 决定上被调——不诚实 mock 兜底 / 数据更新缺血统 / LLM 调用不可复放 / 强理论标签无
绑定 / 致命运行期错（明文密钥泄露·越权直连）/ 未测性能基线冒充达标的 run 今天能溜过 release。**不**在此串进
`ide/promote.py`（那是后续 CENTER-SERIAL 的一次性改·两步法）；本模块是新建孤立件，中心后续经 `gate_registry`
调 `register_section16_engineering_standards_gate(...)`（gate_registry 注释明标的「未来 §16 工程标准」即此门）。

═══ 复用不重造（RULES §1 单一源）═══
§16 工程标准判定的唯一源是 `research_os.engineering_standards`：本模块**只**做 manifest(dict)→canonical
record 的薄适配 + 聚合。与 §13/§17 的一处差异——`engineering_standards.py` **没有** `*_from_dict` 适配器
（不同于 trust_layer / rdp），故本模块自带 6 个 dict→record 适配器（`_adapt_*`）。这些适配器**判定中立**：
只做字段映射 + 类型 coercion（`str(... or "")` / `bool(..., False)` / `_opt_str`），**绝不**夹带任何工程标准
判定——「过没过」全部委托 canonical：5 族（mock/data/llm/theory/fatal）整体喂 `validate_engineering_standards`，
性能族喂 `classify_performance_baseline`。本模块**绝不**重写任何一条工程标准判定，连违例码都直接搬运
engineering_standards 的原码。

═══ 6 族 → engineering_standards 违例（construction-map C-S16 的可证伪点）═══
  - mock 诚实（mock_honesty）：mock/fallback 缺 label 或 reason ⇒ `mock_block_missing_label_or_reason`；
    生产档靠 mock 兜底成功 ⇒ `production_profile_mock_fallback`；模板/mock 冒充生产成功 ⇒
    `template_or_mock_false_production_success`。
  - 数据更新（data_update_standard）：缺 version/checksum/lineage/known_at/effective_at ⇒
    `data_update_missing_version_checksum_lineage`；每表少于 5 条 data test ⇒ `data_update_too_few_data_tests`。
  - LLM 复放（llm_replay_standard）：缺 provider/model/auth/cost/replay/gateway/prompt_hash/tool_schema_hash
    任一 ⇒ `llm_replay_missing_required_ref`。
  - 理论实现（theory_implementation_standard）：强标签（proof_backed/evidence_sufficient/production_ready）
    缺 TheoryImplementationBinding 或 ConsistencyCheck ⇒ `strong_theory_claim_missing_binding_or_consistency`；
    强标签却把 user waiver 当强证据展示 ⇒ `user_waiver_displayed_as_strong_evidence`。
  - 致命运行期（fatal_runtime_standard）：明文密钥进 Agent/RAG/日志/导出 ⇒ `secret_plaintext_left_secure_backend`；
    role agent 越过 LLM Gateway ⇒ `role_agent_bypassed_llm_gateway`；验证者独立性声明无记录 ⇒
    `verifier_independence_record_missing`；A 股实盘单/生产 mock 兜底/前视泄露 ⇒ `fatal_engineering_error_detected`。
  - 性能基线（performance_baseline）：observed > threshold ⇒ `performance_baseline_exceeded`；缺实测证据 ⇒
    `performance_baseline_missing_evidence`。

═══ 性能基线诚实 3 态（never-green·非本门 fail-open）═══
性能族的「过/不过」**单一源**是 `classify_performance_baseline`（它内部复用 `validate_performance_baseline`）：
  - measured=True 且 observed ≤ threshold 且有证据 ⇒ PASS（无违例）。
  - measured=True 但 observed > threshold / 缺证据 ⇒ FAIL（搬运 canonical 违例码·经 `_collect`）。
  - measured=False ⇒ **KNOWN_RUN_GAP**：未实测的基线**永不视绿**（`performance_baseline_known_run_gap`）。
    这是诚实 3 态的灵魂——不能用伪造的 observed 时间冒充一次没做的测量。gap 在 `_collect` **之外**单独收，
    故它是硬 never-green：连「弱化 `.accepted` 判定」这类 mutation 也翻不动它（与 5 族判定正交）。
    `performance_baseline_known_run_gap` 是网关层把 canonical 的 gap **状态**映成「门不绿」的码——判定
    （measured=False 即 gap）100% 来自 `classify_performance_baseline`，本模块不重造 gap 检测。

═══ 职责分离（gaming-proof）═══
check **只懂「这个 promote run 的 §16 工程标准过没过」**，返回 `GateCheckResult(ok, reason, missing)`——它
**不**决定自己是 advisory 还是 enforce。advisory/enforce 由 SA-2 策略（`governance.enforcement_policy`）经门链
统一盖章：仅当 `s16_engineering_standards_runjson_producers`（§16 工程标准结构进 manifest 的接线测试）转绿，
门才从 advisory 翻 enforce（LOCKED 决策 1）。check 连 mode 字段都没有 → **无法自封 enforce 绕过 producer 绿灯门**。

═══ 诚实限界（RULES §3·设计极限·非残余）═══
`section16_engineering_standards` 缺省/为空 → `ok=True`，语义是**「未声明 §16 工程标准结构 ⇒ 无可证伪工程
违例」**，**不**代表「整本 run 已查清 §16」。「是否真有工程标准证据被如实写进 manifest」由 producer 绿灯门
（`s16_engineering_standards_runjson_producers` 接线测试）负责——producer 未绿时本门只 advisory，绝不在未接线
门上误拒诚实 run。节存在但格式非法（非 dict / 族非 list / 项非 dict / record 解析炸）→ fail-closed 记 ok=False
（codex 在 C-S9 找到的「非 list 族静默 skip 让违例溜走」洞，本模块同款堵死·绝不 fail-open）。

═══ 委托边界（诚实限界·非本门 fail-open）═══
本门**严格只与 `engineering_standards.validate_engineering_standards` / `classify_performance_baseline` 同强**——
它们判过的本门判过，它们放过的本门放过。适配器对「present 即算有」的边界（如 `_present` 用 `str(v or "").strip()`
判空白）遵 engineering_standards 单一源语义，本门遵「reuse·不擅改 engineering_standards」只忠实委托·绝不在网关
层重写判定（= 防 §1 单一源漂移）。

═══ 冷导入安全 ═══
顶层只 import 同包 `promote_gate_chain`（cold-safe·已证）与 `research_os.engineering_standards`（纯
dataclass + stdlib·经 `python -c` 实证冷导入安全·不触 governance 冷循环）。**不**在顶层 import governance
（SA-2 符号由门链在 evaluate 期惰性载入）。**不**碰 `release_gate/__init__.py`（既有冷导入环·SA-3 note）——
消费方从本子模块直接 import。模块**无 import 期副作用**（不 auto-register）。
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Callable

from ..research_os.engineering_standards import (
    DataUpdateStandardRecord,
    EngineeringStandardDecision,
    FatalRuntimeStandardRecord,
    LLMReplayStandardRecord,
    MockHonestyRecord,
    PerformanceBaselineMeasurement,
    TheoryImplementationStandardRecord,
    classify_performance_baseline,
    validate_engineering_standards,
)
from .promote_gate_chain import GateCheckResult, PromoteGateChain, RunManifest

# —— 门身份 + 证据 producer key（中心注册/绿灯账据此钉）。gate_name 与门链其它节门同族短名 ——
SECTION16_ENGINEERING_STANDARDS_GATE_NAME = "s16_engineering_standards"
# 证据 producer：§16 工程标准结构进 promote manifest 的接线测试。转绿前门停 advisory（LOCKED 决策 1）。
SECTION16_ENGINEERING_STANDARDS_PRODUCER_KEY = "s16_engineering_standards_runjson_producers"
# manifest 里承载 §16 工程标准 6 族的 key（producer 填·check 读）。其值是一个 dict（6 族各一个 list）。
SECTION16_ENGINEERING_STANDARDS_MANIFEST_KEY = "section16_engineering_standards"

# 性能族 key 单独拎出（它走 classify_performance_baseline 的 3 态·不进 validate_engineering_standards 聚合）。
_PERFORMANCE_KEY = "performance_records"

_NOTHING_DECLARED = (
    "§16：manifest 未声明 section16_engineering_standards 结构 —— 无可证伪工程标准违例"
    "（诚实限界：非『整本已查清』·查清由 producer 绿灯门负责）"
)
_ALL_SATISFIED = "§16 工程标准全部满足（已声明工程标准结构无违例·性能基线均实测达标）"

# 各族 ref 字段名（fail-closed 时取作展示样本·纯展示·非判定）。
_REF_KEYS = (
    "record_ref", "update_ref", "call_ref", "claim_ref", "runtime_ref", "baseline_ref", "ref",
)


def _ref_of(d: Mapping[str, Any]) -> str:
    for key in _REF_KEYS:
        val = d.get(key)
        if val:
            return str(val)
    return ""


def _opt_str(value: Any) -> str | None:
    """判定中立的 str|None coercion：None 原样保留（canonical `_present` 视作缺省），余者转 str。

    绝不在此判「present 否」——那是 engineering_standards `_present` 的单一源职责（本适配器只搬数据）。
    """

    return None if value is None else str(value)


def _opt_float(value: Any) -> float | None:
    if value is None:
        return None
    return float(value)  # 非数 → 抛 → 调用方 fail-closed 记 unparseable


# ════════════════════════════════════════════════════════════════════════════
# 6 个 dict→record 适配器（判定中立·engineering_standards 无 `*_from_dict`·故本模块自带）。
# **绝不**夹带工程标准判定——只字段映射 + 类型 coercion。判定全留给 canonical validator。
# ════════════════════════════════════════════════════════════════════════════
def _adapt_mock_honesty(d: Mapping[str, Any]) -> MockHonestyRecord:
    return MockHonestyRecord(
        record_ref=str(d.get("record_ref") or ""),
        production_profile=bool(d.get("production_profile", False)),
        mock_used=bool(d.get("mock_used", False)),
        mock_label_ref=_opt_str(d.get("mock_label_ref")),
        fallback_reason_ref=_opt_str(d.get("fallback_reason_ref")),
        template_response=bool(d.get("template_response", False)),
        production_success_claim=bool(d.get("production_success_claim", False)),
    )


def _adapt_data_update(d: Mapping[str, Any]) -> DataUpdateStandardRecord:
    return DataUpdateStandardRecord(
        update_ref=str(d.get("update_ref") or ""),
        dataset_version_ref=_opt_str(d.get("dataset_version_ref")),
        checksum=_opt_str(d.get("checksum")),
        lineage_ref=_opt_str(d.get("lineage_ref")),
        known_at_ref=_opt_str(d.get("known_at_ref")),
        effective_at_ref=_opt_str(d.get("effective_at_ref")),
        # DataUpdateStandardRecord.__post_init__ 用 `_tuple` 归一（None→()·list→tuple·标量→1元组）。
        data_test_refs=d.get("data_test_refs"),  # type: ignore[arg-type]
    )


def _adapt_llm_replay(d: Mapping[str, Any]) -> LLMReplayStandardRecord:
    return LLMReplayStandardRecord(
        call_ref=str(d.get("call_ref") or ""),
        provider_ref=_opt_str(d.get("provider_ref")),
        model_ref=_opt_str(d.get("model_ref")),
        auth_ref=_opt_str(d.get("auth_ref")),
        cost_ref=_opt_str(d.get("cost_ref")),
        replay_state_ref=_opt_str(d.get("replay_state_ref")),
        llm_gateway_ref=_opt_str(d.get("llm_gateway_ref")),
        prompt_hash=_opt_str(d.get("prompt_hash")),
        tool_schema_hash=_opt_str(d.get("tool_schema_hash")),
    )


def _adapt_theory_implementation(d: Mapping[str, Any]) -> TheoryImplementationStandardRecord:
    return TheoryImplementationStandardRecord(
        claim_ref=str(d.get("claim_ref") or ""),
        # display_label 非可选·canonical 用它比 STRONG_LABELS：缺省 → "" (非强标签·不触强标签门)。
        display_label=str(d.get("display_label") or ""),
        theory_implementation_binding_ref=_opt_str(d.get("theory_implementation_binding_ref")),
        consistency_check_ref=_opt_str(d.get("consistency_check_ref")),
        user_waiver_ref=_opt_str(d.get("user_waiver_ref")),
    )


def _adapt_fatal_runtime(d: Mapping[str, Any]) -> FatalRuntimeStandardRecord:
    return FatalRuntimeStandardRecord(
        runtime_ref=str(d.get("runtime_ref") or ""),
        # __post_init__ 用 `_tuple` 归一：None→()（无泄露面·不触门）·list→tuple（非空即违例）。
        secret_plaintext_surfaces=d.get("secret_plaintext_surfaces"),  # type: ignore[arg-type]
        role_agent_bypassed_llm_gateway=bool(d.get("role_agent_bypassed_llm_gateway", False)),
        verifier_independence_claimed=bool(d.get("verifier_independence_claimed", False)),
        verifier_independence_record_ref=_opt_str(d.get("verifier_independence_record_ref")),
        a_share_live_order=bool(d.get("a_share_live_order", False)),
        production_mock_fallback=bool(d.get("production_mock_fallback", False)),
        lookahead_leakage_detected=bool(d.get("lookahead_leakage_detected", False)),
    )


def _adapt_performance_measurement(d: Mapping[str, Any]) -> PerformanceBaselineMeasurement:
    """性能族 → canonical `PerformanceBaselineMeasurement`（带 `measured` 的诚实 3 态量）。

    `threshold_seconds` 必填——缺/非数 → `float(None)` 抛 → 由调用方 fail-closed 记 unparseable（一个无门槛
    的性能记录无从判定·绝不静默放行）。`observed_seconds` 走 `_opt_float`（measured=False 时为 None=gap）。
    """

    return PerformanceBaselineMeasurement(
        baseline_ref=str(d.get("baseline_ref") or ""),
        metric_name=str(d.get("metric_name") or ""),
        threshold_seconds=float(d.get("threshold_seconds")),  # type: ignore[arg-type]
        measured=bool(d.get("measured", False)),
        observed_seconds=_opt_float(d.get("observed_seconds")),
        evidence_ref=_opt_str(d.get("evidence_ref")),
        unavailable_reason=_opt_str(d.get("unavailable_reason")),
        detail=str(d.get("detail") or ""),
    )


# ════════════════════════════════════════════════════════════════════════════
# 5 个 record 族（性能族单列）：(manifest_key, 适配器)。manifest_key 即 validate_engineering_standards 的
# kwarg（mock_records/data_updates/llm_calls/theory_claims/fatal_records 字面同名）。
# ════════════════════════════════════════════════════════════════════════════
_RECORD_FAMILIES: tuple[tuple[str, Callable[[Mapping[str, Any]], Any]], ...] = (
    ("mock_records", _adapt_mock_honesty),
    ("data_updates", _adapt_data_update),
    ("llm_calls", _adapt_llm_replay),
    ("theory_claims", _adapt_theory_implementation),
    ("fatal_records", _adapt_fatal_runtime),
)


def _parse_family(
    section: Mapping[str, Any],
    key: str,
    adapter: Callable[[Mapping[str, Any]], Any],
    violations: list[tuple[str, str]],
) -> list[Any]:
    """把一族 §16 工程标准 dict 解析成 canonical record · fail-closed（不静默 skip 让违例溜走）。

    缺省/None → 未声明（返回空·诚实空）；present 但非 list/tuple（被填成 {id:rec} 映射 / 标量）→ 记
    `section16_engineering_standards_<key>_malformed`（ok=False·不当空通过）；list 内非 dict 项 → 同样
    malformed；单条 adapter 抛 → 记 `section16_engineering_standards_<key>_unparseable`。**只做 dict→record
    适配**，工程标准判定留给 validate_engineering_standards。
    """

    value = section.get(key)
    if value is None:
        return []
    if not isinstance(value, (list, tuple)):
        violations.append((f"section16_engineering_standards_{key}_malformed", ""))
        return []
    records: list[Any] = []
    for item in value:
        if not isinstance(item, Mapping):
            violations.append((f"section16_engineering_standards_{key}_malformed", ""))
            continue
        try:
            records.append(adapter(dict(item)))
        except Exception:  # noqa: BLE001 — 解析炸 → fail-closed（记族违例·不静默放行·不炸整链）
            violations.append((f"section16_engineering_standards_{key}_unparseable", _ref_of(item)))
    return records


def _collect(result: EngineeringStandardDecision, violations: list[tuple[str, str]]) -> None:
    """把一个 canonical 工程标准裁定的违例搬进聚合表（**单一 mutation 锚点**）。

    ★ mutation 三态（见 test 文件头）：把下面 `if not result.accepted:` 弱化成 `if False:`（无视
      engineering_standards canonical 裁定·让坏 run 溜成 ok=True）→ mock/data/llm/theory/fatal +
      perf-exceeded/perf-missing-evidence 全族对抗测试转 RED → 还原 → GREEN。KNOWN_RUN_GAP 在 `_collect`
      **之外**单独收（never-green·与 `.accepted` 正交）→ 该 gap 测试不随此变异翻。
    """

    if not result.accepted:
        for v in result.violations:
            violations.append((v.code, v.ref or ""))


def _evaluate_performance(
    section: Mapping[str, Any], violations: list[tuple[str, str]]
) -> None:
    """性能族 → `classify_performance_baseline` 诚实 3 态。fail-closed 同 `_parse_family`。

    - measured=False ⇒ KNOWN_RUN_GAP ⇒ `performance_baseline_known_run_gap`（never-green·`_collect` 外收）。
    - measured=True ⇒ verdict.decision 经 `_collect` 搬运 canonical 违例（exceeded / missing-evidence）。
    - measured=True 但 observed_seconds 缺 ⇒ classify 抛 ValueError ⇒ 这里 fail-closed 记 unparseable
      （绝不让「声称已测却无实测时间」静默放行）。
    """

    value = section.get(_PERFORMANCE_KEY)
    if value is None:
        return
    if not isinstance(value, (list, tuple)):
        violations.append(("section16_engineering_standards_performance_records_malformed", ""))
        return
    for item in value:
        if not isinstance(item, Mapping):
            violations.append(("section16_engineering_standards_performance_records_malformed", ""))
            continue
        try:
            measurement = _adapt_performance_measurement(dict(item))
            verdict = classify_performance_baseline(measurement)
        except Exception:  # noqa: BLE001 — 解析/分类炸 → fail-closed（记违例·不静默放行）
            violations.append(
                ("section16_engineering_standards_performance_records_unparseable", _ref_of(item))
            )
            continue
        if verdict.is_known_run_gap:
            # 诚实 3 态：未实测基线 = KNOWN_RUN_GAP·硬 never-green（不经 `_collect`·与 `.accepted` 正交）。
            violations.append(("performance_baseline_known_run_gap", measurement.baseline_ref))
        elif verdict.decision is not None:
            _collect(verdict.decision, violations)  # 实测：exceeded / missing-evidence（canonical 码）


# ════════════════════════════════════════════════════════════════════════════
# 公开 check：promote manifest → GateCheckResult（门链插它）
# ════════════════════════════════════════════════════════════════════════════
def section16_engineering_standards_check(manifest: RunManifest) -> GateCheckResult:
    """§16 工程标准发版 check：把 6 族喂 engineering_standards canonical 判定·聚合违例·返回过/不过。

    - 节缺省/为空 → ok=True（无可证伪违例·诚实限界见模块 docstring）。
    - 节存在但非 dict → ok=False（fail-closed·格式非法不静默放行）。
    - 任一族任一工程标准违例（mock 不诚实 / 数据更新缺血统 / LLM 不可复放 / 强理论无绑定 / 致命运行期错 /
      性能超基线 / 未实测基线冒充达标）→ ok=False·missing=去重违例码（全来自 engineering_standards canonical
      validator）·reason=带 ref 样本。

    判定**单一源**：5 族委托 `validate_engineering_standards`、性能族委托 `classify_performance_baseline`
    （不碰 advisory/enforce·不重写任何门判定）。
    """

    # 非 Mapping manifest → manifest.get 抛 → 由门链 _run_one fail-closed（errored·绝不静默放行）。
    # 刻意不在此 catch 成 ok=True（那是 fail-open）。
    section = manifest.get(SECTION16_ENGINEERING_STANDARDS_MANIFEST_KEY)

    if section is None:
        return GateCheckResult(ok=True, reason=_NOTHING_DECLARED)
    if not isinstance(section, Mapping):
        return GateCheckResult(
            ok=False,
            reason="§16 工程标准节存在但格式非法（应为对象/dict）—— fail-closed 视为未过",
            missing=("section16_engineering_standards_malformed",),
        )

    violations: list[tuple[str, str]] = []

    # —— 5 record 族 → adapter → canonical 聚合器 → `_collect` 搬运违例 ——
    buckets: dict[str, list[Any]] = {}
    for key, adapter in _RECORD_FAMILIES:
        buckets[key] = _parse_family(section, key, adapter, violations)

    # 判定**单一源**：5 族整体委托 validate_engineering_standards（绝不重写任何门判定）。
    # 用 `.get(..., [])` 取桶：注释掉 _RECORD_FAMILIES 任一行（mutation）只让该族变空·不 KeyError 崩链。
    try:
        decision = validate_engineering_standards(
            mock_records=tuple(buckets.get("mock_records", [])),
            data_updates=tuple(buckets.get("data_updates", [])),
            llm_calls=tuple(buckets.get("llm_calls", [])),
            theory_claims=tuple(buckets.get("theory_claims", [])),
            fatal_records=tuple(buckets.get("fatal_records", [])),
        )
    except Exception as exc:  # noqa: BLE001 — 判定炸 → fail-closed（记违例·绝不静默 ok=True 放行）
        violations.append(
            ("section16_engineering_standards_evaluation_unparseable", type(exc).__name__)
        )
    else:
        _collect(decision, violations)

    # —— 性能族 → classify_performance_baseline 诚实 3 态（KNOWN_RUN_GAP never-green）——
    _evaluate_performance(section, violations)

    if not violations:
        return GateCheckResult(ok=True, reason=_ALL_SATISFIED)

    codes = tuple(dict.fromkeys(code for code, _ in violations))  # 去重·保首现序
    sample = "; ".join(f"{code}@{ref}" if ref else code for code, ref in violations[:8])
    more = "" if len(violations) <= 8 else f" …(+{len(violations) - 8})"
    reason = f"§16 工程标准违例 {len(violations)} 项: {sample}{more}"
    return GateCheckResult(ok=False, reason=reason, missing=codes)


def register_section16_engineering_standards_gate(
    chain: PromoteGateChain, *, enforce_intent: bool = True
) -> None:
    """把 §16 工程标准发版 check 注册进给定门链（中心后续经 gate_registry 串 promote.py 时调一次）。

    用法（CENTER-SERIAL·经单一注册收口）：
        from app.release_gate.gate_registry import ensure_default_chain  # 加本门后含它
        ensure_default_chain().evaluate(manifest, producer_status=ledger)

    `enforce_intent=True`：§16 门有 GOAL「拒」语义（mock 不诚实 / 数据缺血统 / LLM 不可复放 / 强理论无绑定 /
    致命运行期错 / 未测或超标性能基线 → 拒发版），**有资格** enforce——但仅当
    `s16_engineering_standards_runjson_producers` 转绿才真翻 enforce；未绿则被 SA-2 策略降级 advisory + 记录
    （绝不误拒诚实 run）。check 无 mode 字段·无从自封 enforce。
    """

    chain.register(
        gate_name=SECTION16_ENGINEERING_STANDARDS_GATE_NAME,
        check=section16_engineering_standards_check,
        required_producer=SECTION16_ENGINEERING_STANDARDS_PRODUCER_KEY,
        enforce_intent=enforce_intent,
    )


__all__ = [
    "SECTION16_ENGINEERING_STANDARDS_GATE_NAME",
    "SECTION16_ENGINEERING_STANDARDS_PRODUCER_KEY",
    "SECTION16_ENGINEERING_STANDARDS_MANIFEST_KEY",
    "section16_engineering_standards_check",
    "register_section16_engineering_standards_gate",
]
