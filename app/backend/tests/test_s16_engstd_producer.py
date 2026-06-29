"""NC-S16-ENGSTD-PRODUCER · §16 工程标准 manifest record builder 对抗测试（RULES §2 种坏门必抓 + §3 诚实）。

被测对象 = `research_os.engineering_standards.build_section16_engineering_standards_record`（孤立 producer·
把 6 族 typed 工程证据忠实序列化成 §16 门 check 读的 `section16_engineering_standards` manifest payload）。
**不**测 `section16_engineering_standards_gate` 自身判定（那是 C-S16-GATE 卡的 test_section16_engineering_standards_gate.py，
本卡只读复用其 check + MANIFEST_KEY），本卡测 **producer→门 wiring**：producer 产的 manifest 喂真门 check + 真门链。

可证伪验收（producer 真把工程证据如实落进 manifest·门据真值判）：
  · 合规 6 族 run → build → manifest[含 section16] → producer 绿 → 门 ENFORCE 仍 ok=True（不误伤诚实 run）
  · 坏 run（生产档 mock 兜底 / 未实测性能基线 / 数据更新缺 version / mock 缺 label / LLM 缺 provider /
    强理论缺 binding / 致命明文密钥 / 性能超基线）→ build → producer 绿 → 门 ENFORCE 拒（blocks·缺项精确）
  · honest-absent（无任何工程证据）→ build 返回 {} → 中心 _take 不发 section → 门 ok=True（未声明≠违例·非整本已查清）
  · producer 红/缺 + 坏 run → advisory：只记录不阻断（flip_refused·绝不误拒诚实 run）
faithful：producer→门 裁定逐码 == 直接喂 canonical validator（不增不减不改·复用单一源·非另造判定）。
不洗白：record 的 None/未实测原样序列化（绝不补占位 / 造 observed 时间）→ 门 surface 真违例 / KNOWN_RUN_GAP。
fail-closed：喂错族类型（mock 塞 data 槽 / 性能族塞非 3 态 PerformanceBaselineRecord）→ raise（不静默吞坏输入）。

★ producer 仍 RED（无假绿灯）：本卡**不建** producer 接线 `s16_engineering_standards_runjson_producers`（中心把
  本 builder 串进 `promote_assembler.assemble_promote_sections` 那步 = CENTER-SERIAL·独立）。下方门链合成测试用
  **测试态本地** ProducerStatusLedger.mark_green(...) 证明 enforce 行为为真——绝非生产假绿灯（生产 producer_status
  默认 None=红·见 test_absent_producer_status_advisory_only）。

★ producer mutation 三态（已手验：GREEN 25 → 洗白 RED 12/GREEN 13 → 还原 GREEN 25）：把
  engineering_standards._engineering_record_to_manifest_dict 的 `return _to_json_safe(asdict(record))` 改成 None-洗白
  `return _to_json_safe({k: (v if v is not None else "__filled__") for k, v in asdict(record).items()})`（= 假绿灯）。
  洗白双向作恶 → 12 个依赖「忠实保留 None/缺省」的测试转 RED：
    ① 抹真违例：test_bad_mock_missing_label_rejected_under_green / test_bad_data_missing_version_rejected_under_green /
      test_bad_llm_missing_provider_rejected_under_green / test_bad_strong_theory_missing_binding_rejected_under_green
    ② 造假违例（误拒合规）：test_compliant_builder_output_passes_gate_check /
      test_compliant_run_builds_and_passes_under_green_enforce（合规 theory 的 None user_waiver_ref 被洗成「有
      waiver」→ 强标签 user_waiver_displayed_as_strong_evidence 误触）
    ③ 性能未实测被洗炸：test_bad_unmeasured_perf_baseline_rejected_under_green（observed_seconds=None→非数串→
      float() 炸成 unparseable·gap 码变）/ test_no_whitewash_unmeasured_perf_preserved
    ④ 忠实/反作弊探针：test_no_whitewash_none_ref_preserved / test_serialization_faithful_to_canonical_validator /
      test_input_flip_flips_gate_verdict_not_constant / test_bad_run_under_red_producer_advisory_only_not_blocking（断言 v.ok is False）
  与 None 正交 → 13 个仍 GREEN：bool/数值/tuple 判定（test_bad_production_mock_fallback_rejected_under_green /
    test_bad_perf_exceeded_rejected_under_green / test_bad_fatal_secret_plaintext_rejected_under_green）+ honest-absent
    无 record 可洗（test_honest_absent_*×3 / test_absent_producer_status_advisory_only /
    test_none_or_falsy_family_is_honest_absent_not_silently_judged）+ 结构/类型/冷导入
    （test_builder_emits_only_nonempty_families / test_builder_field_names_match_gate_adapter_contract_and_json_safe /
    test_failclosed_wrong_record_type_in_family / test_failclosed_perf_record_must_be_three_state_measurement /
    test_builder_module_cold_importable）→ 还原 → 全 25 GREEN。
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

# 冷导入预热（既有循环·非本卡引入）：导入 app.governance.* 前先全载 orchestrator 解环——与
# test_section16_engineering_standards_gate.py 同款顺序（app.governance 包 __init__ 经 spine_invariants 触达 orchestrator）。
import app.agent.orchestrator  # noqa: F401  (prime: 解 app.governance 既有冷导入循环)

from app.governance.enforcement_policy import (  # noqa: E402
    MODE_ADVISORY,
    MODE_ENFORCE,
    ProducerStatusLedger,
)
from app.release_gate.promote_gate_chain import (  # noqa: E402
    ChainResult,
    GateCheckResult,
    PromoteGateChain,
)
from app.release_gate.section16_engineering_standards_gate import (  # noqa: E402
    SECTION16_ENGINEERING_STANDARDS_GATE_NAME,
    SECTION16_ENGINEERING_STANDARDS_MANIFEST_KEY as KEY,
    SECTION16_ENGINEERING_STANDARDS_PRODUCER_KEY,
    register_section16_engineering_standards_gate,
    section16_engineering_standards_check,
)
from app.research_os import engineering_standards as es  # noqa: E402


# ════════════════════════════════════════════════════════════════════════════
# 各族 clean typed record（喂 builder·值对齐 gate test 的 _clean_* dict → 证 builder 产同款合规 payload）
# ════════════════════════════════════════════════════════════════════════════
def _clean_mock() -> es.MockHonestyRecord:
    return es.MockHonestyRecord(
        record_ref="mock::1", production_profile=True, mock_used=False, mock_label_ref=None,
        fallback_reason_ref=None, template_response=False, production_success_claim=True,
    )


def _clean_data() -> es.DataUpdateStandardRecord:
    return es.DataUpdateStandardRecord(
        update_ref="du::1", dataset_version_ref="dv::1", checksum="sha256::1", lineage_ref="lin::1",
        known_at_ref="k::1", effective_at_ref="e::1", data_test_refs=("t1", "t2", "t3", "t4", "t5"),
    )


def _clean_llm() -> es.LLMReplayStandardRecord:
    return es.LLMReplayStandardRecord(
        call_ref="llm::1", provider_ref="anthropic", model_ref="m::1", auth_ref="au::1", cost_ref="c::1",
        replay_state_ref="r::1", llm_gateway_ref="g::1", prompt_hash="ph::1", tool_schema_hash="th::1",
    )


def _clean_theory() -> es.TheoryImplementationStandardRecord:
    return es.TheoryImplementationStandardRecord(
        claim_ref="th::1", display_label="evidence_sufficient",
        theory_implementation_binding_ref="tib::1", consistency_check_ref="cc::1",
    )


def _clean_fatal() -> es.FatalRuntimeStandardRecord:
    return es.FatalRuntimeStandardRecord(runtime_ref="rt::1", secret_plaintext_surfaces=())


def _clean_perf() -> es.PerformanceBaselineMeasurement:
    return es.PerformanceBaselineMeasurement(
        baseline_ref="bl::1", metric_name="factor_calc", threshold_seconds=2.0,
        measured=True, observed_seconds=1.0, evidence_ref="ev::1",
    )


def _all_clean_kwargs() -> dict:
    return dict(
        mock_records=[_clean_mock()], data_updates=[_clean_data()], llm_calls=[_clean_llm()],
        theory_claims=[_clean_theory()], fatal_records=[_clean_fatal()], performance_records=[_clean_perf()],
    )


# ════════════════════════════════════════════════════════════════════════════
# 中心 wiring 镜像：build payload → 仅非空时发 section key（mirror promote_assembler._take 的 honest-absent）
# ════════════════════════════════════════════════════════════════════════════
def _manifest_from_builder(**builder_kwargs) -> dict:
    """build §16 payload → 套进 manifest（payload 非空才发 KEY·镜像中心 _take：空 payload→honest-absent）。"""

    section = es.build_section16_engineering_standards_record(**builder_kwargs)
    m: dict = {"run_id": "ide_promote_test", "status": "completed"}
    if section:  # _take: 空 payload 不发 key（未声明≠违例）
        m[KEY] = section
    return m


def _green_ledger() -> ProducerStatusLedger:
    led = ProducerStatusLedger()
    led.mark_green(SECTION16_ENGINEERING_STANDARDS_PRODUCER_KEY)  # 仅此卡测试态·绝非生产假绿灯
    return led


def _s16_verdict(result: ChainResult):
    matches = [v for v in result.verdicts if v.gate_name == SECTION16_ENGINEERING_STANDARDS_GATE_NAME]
    assert len(matches) == 1, "门链中应恰有一道 §16 工程标准门裁定"
    return matches[0]


def _assert_rejected_under_green(*, code: str, **builder_kwargs):
    """坏 run → build → producer 绿 → 整链 ENFORCE 拒（blocks·缺项含 code）。返回 §16 verdict。"""

    m = _manifest_from_builder(**builder_kwargs)
    assert KEY in m, "坏 run 应有工程证据被 build 进 manifest（非 honest-absent）"
    chain = PromoteGateChain()
    register_section16_engineering_standards_gate(chain)
    result = chain.evaluate(m, producer_status=_green_ledger())
    assert result.rejected is True, f"producer 绿 + §16 违例({code}) → 整链必须拒晋级"
    v = _s16_verdict(result)
    assert v.advisory_or_enforce == MODE_ENFORCE
    assert v.blocks is True and v.ok is False
    assert code in v.missing, f"缺项应精确含 {code}（来自 canonical validator）·实得 {v.missing}"
    return v


# ════════════════════════════════════════════════════════════════════════════
# ① 合规 run：build → 真进 manifest → producer 绿 → 门 ENFORCE 仍 ok=True（不误伤诚实 run）
# ════════════════════════════════════════════════════════════════════════════
def test_compliant_builder_output_passes_gate_check():
    """合规 6 族 → build → 门 check 直判 ok=True·无 missing（producer 产合规 payload）。"""

    cr = section16_engineering_standards_check(_manifest_from_builder(**_all_clean_kwargs()))
    assert isinstance(cr, GateCheckResult)
    assert cr.ok is True and cr.missing == ()


def test_compliant_run_builds_and_passes_under_green_enforce():
    """★ wiring ①：合规 run → build → manifest[含 section16] → producer 绿 → 整链 ENFORCE 不拒·门 ok=True。"""

    m = _manifest_from_builder(**_all_clean_kwargs())
    assert KEY in m, "合规 run 的 6 族工程证据须真被 build 进 manifest"
    chain = PromoteGateChain()
    register_section16_engineering_standards_gate(chain)
    result = chain.evaluate(m, producer_status=_green_ledger())
    assert result.rejected is False, "合规工程证据在 enforce 下不得被拒"
    v = _s16_verdict(result)
    assert v.advisory_or_enforce == MODE_ENFORCE and v.ok is True
    assert v.producer_key == SECTION16_ENGINEERING_STANDARDS_PRODUCER_KEY


# ════════════════════════════════════════════════════════════════════════════
# ② 坏 run：build → producer 绿 → 门 ENFORCE 拒（6 族坏门必抓·mutation 三态 RED/GREEN 目标）
# ════════════════════════════════════════════════════════════════════════════
def test_bad_production_mock_fallback_rejected_under_green():
    """★ wiring ②：生产档靠 mock 兜底（label/reason 给齐隔离缺 label）→ producer 绿 → 拒·production_profile_mock_fallback。

    [mutation 三态] None-洗白正交（production_profile/mock_used 是 bool）→ 仍 GREEN。
    """

    bad = es.MockHonestyRecord(
        record_ref="m::prod", production_profile=True, mock_used=True, mock_label_ref="MOCK",
        fallback_reason_ref="net down", template_response=False, production_success_claim=False,
    )
    _assert_rejected_under_green(mock_records=[bad], code="production_profile_mock_fallback")


def test_bad_unmeasured_perf_baseline_rejected_under_green():
    """★ wiring ②（never-green）：未实测性能基线（measured=False）→ producer 绿 → 拒·performance_baseline_known_run_gap。

    producer 忠实序列化 measured=False（绝不造 observed 时间洗成达标）→ 门经 classify_performance_baseline 判 gap。
    [mutation 三态] gap 由 measured 旗（bool）定·与 None-洗白正交 → 仍 GREEN。
    """

    bad = es.PerformanceBaselineMeasurement(
        baseline_ref="bl::gap", metric_name="hs300_read", threshold_seconds=3.0,
        measured=False, observed_seconds=None, unavailable_reason="production dataset absent in this env",
    )
    _assert_rejected_under_green(performance_records=[bad], code="performance_baseline_known_run_gap")


def test_bad_data_missing_version_rejected_under_green():
    """★ wiring ②：数据更新缺 dataset_version（其余血统 + 5 test 给齐隔离）→ producer 绿 → 拒·data_update_missing_version_checksum_lineage。

    [mutation 三态] 依赖 None ref（dataset_version_ref=None）→ 洗白则 RED。
    """

    bad = es.DataUpdateStandardRecord(
        update_ref="du::bad", dataset_version_ref=None, checksum="sha256::1", lineage_ref="lin::1",
        known_at_ref="k::1", effective_at_ref="e::1", data_test_refs=("t1", "t2", "t3", "t4", "t5"),
    )
    _assert_rejected_under_green(data_updates=[bad], code="data_update_missing_version_checksum_lineage")


def test_bad_mock_missing_label_rejected_under_green():
    """坏门：mock_used 却缺 label/reason → 拒·mock_block_missing_label_or_reason。[mutation 三态] None ref → 洗白则 RED。"""

    bad = es.MockHonestyRecord(
        record_ref="m::nolabel", production_profile=False, mock_used=True, mock_label_ref=None,
        fallback_reason_ref=None, template_response=False, production_success_claim=False,
    )
    _assert_rejected_under_green(mock_records=[bad], code="mock_block_missing_label_or_reason")


def test_bad_llm_missing_provider_rejected_under_green():
    """坏门：LLM 调用缺 provider_ref → 拒·llm_replay_missing_required_ref。[mutation 三态] None ref → 洗白则 RED。"""

    bad = es.LLMReplayStandardRecord(
        call_ref="llm::bad", provider_ref=None, model_ref="m::1", auth_ref="au::1", cost_ref="c::1",
        replay_state_ref="r::1", llm_gateway_ref="g::1", prompt_hash="ph::1", tool_schema_hash="th::1",
    )
    _assert_rejected_under_green(llm_calls=[bad], code="llm_replay_missing_required_ref")


def test_bad_strong_theory_missing_binding_rejected_under_green():
    """坏门：强理论标签缺 binding/consistency → 拒·strong_theory_claim_missing_binding_or_consistency。

    [mutation 三态] 依赖 None ref（binding/consistency=None）→ 洗白则 RED。
    """

    bad = es.TheoryImplementationStandardRecord(
        claim_ref="t::bad", display_label="proof_backed",
        theory_implementation_binding_ref=None, consistency_check_ref=None,
    )
    _assert_rejected_under_green(
        theory_claims=[bad], code="strong_theory_claim_missing_binding_or_consistency"
    )


def test_bad_fatal_secret_plaintext_rejected_under_green():
    """坏门：致命明文密钥泄露面非空 → 拒·secret_plaintext_left_secure_backend。[mutation 三态] tuple 非 None → 仍 GREEN。"""

    bad = es.FatalRuntimeStandardRecord(
        runtime_ref="rt::leak", secret_plaintext_surfaces=("agent_prompt", "export_zip"),
    )
    _assert_rejected_under_green(fatal_records=[bad], code="secret_plaintext_left_secure_backend")


def test_bad_perf_exceeded_rejected_under_green():
    """坏门：性能 observed > threshold → 拒·performance_baseline_exceeded。[mutation 三态] 数值判定 → 仍 GREEN。"""

    bad = es.PerformanceBaselineMeasurement(
        baseline_ref="bl::slow", metric_name="backtest", threshold_seconds=1.0,
        measured=True, observed_seconds=5.0, evidence_ref="ev::1",
    )
    _assert_rejected_under_green(performance_records=[bad], code="performance_baseline_exceeded")


# ════════════════════════════════════════════════════════════════════════════
# ③ honest-absent：无工程证据 → build {} → 中心不发 section → 门 ok=True（未声明≠违例·非整本已查清）
# ════════════════════════════════════════════════════════════════════════════
def test_honest_absent_builder_returns_empty():
    """无 record → build 返回 {}（不发任何族 key·绝不发空壳让门误判合规）。"""

    assert es.build_section16_engineering_standards_record() == {}


def test_honest_absent_manifest_omits_section_and_passes_check():
    """★ wiring ③：build {} → 中心不发 section key → 门 check ok=True·reason 标『无可证伪』（诚实限界）。"""

    m = _manifest_from_builder()  # 无 record
    assert KEY not in m, "honest-absent：空 payload 不得发 section key"
    cr = section16_engineering_standards_check(m)
    assert cr.ok is True and cr.missing == ()
    assert "无可证伪" in cr.reason


def test_honest_absent_passes_under_green_enforce():
    """★ wiring ③：honest-absent run 即使 producer 绿 + enforce 也不被拒（未声明≠违例·绝不误拒诚实 run）。"""

    m = _manifest_from_builder()
    chain = PromoteGateChain()
    register_section16_engineering_standards_gate(chain)
    result = chain.evaluate(m, producer_status=_green_ledger())
    assert result.rejected is False
    v = _s16_verdict(result)
    assert v.ok is True and v.blocks is False


# ════════════════════════════════════════════════════════════════════════════
# ④ producer 红/缺 + 坏 run → advisory：记录不阻断（flip_refused·绝不误拒）
# ════════════════════════════════════════════════════════════════════════════
def _bad_mock_manifest() -> dict:
    bad = es.MockHonestyRecord(
        record_ref="m::bad", production_profile=False, mock_used=True, mock_label_ref=None,
        fallback_reason_ref=None, template_response=False, production_success_claim=False,
    )
    return _manifest_from_builder(mock_records=[bad])


def test_bad_run_under_red_producer_advisory_only_not_blocking():
    """★ wiring ④：坏 run + producer 红（空 ledger）→ advisory：记录但不阻断（flip_refused·门诚实记未过·不阻）。"""

    chain = PromoteGateChain()
    register_section16_engineering_standards_gate(chain)
    result = chain.evaluate(_bad_mock_manifest(), producer_status=ProducerStatusLedger())
    assert result.rejected is False, "producer 未绿 → §16 门只 advisory·绝不阻断"
    v = _s16_verdict(result)
    assert v.advisory_or_enforce == MODE_ADVISORY
    assert v.flip_refused is True, "拒翻必须被记录（非静默）"
    assert v.ok is False and v.blocks is False
    assert v in result.advisories


def test_absent_producer_status_advisory_only():
    """★ 无假绿灯：producer_status=None（生产默认）→ §16 门 advisory·producer_green=False·不阻断。"""

    chain = PromoteGateChain()
    register_section16_engineering_standards_gate(chain)
    result = chain.evaluate(_bad_mock_manifest(), producer_status=None)
    assert result.rejected is False
    v = _s16_verdict(result)
    assert v.advisory_or_enforce == MODE_ADVISORY
    assert v.producer_green is False, "确认 producer 仍 RED（出厂红·无假绿灯）"
    assert v.blocks is False


# ════════════════════════════════════════════════════════════════════════════
# ⑤ faithful（复用单一源·非另造）+ 不洗白 + fail-closed + 反作弊
# ════════════════════════════════════════════════════════════════════════════
def test_serialization_faithful_to_canonical_validator():
    """复用证明：producer→门 裁定逐码 == 直接喂 canonical validator（不增不减不改·非另造判定）。

    [mutation 三态] 洗白 mock 的 None label → producer→门 漏报 → 与 canonical 直判不一致 → RED。
    """

    bad = es.MockHonestyRecord(
        record_ref="m::x", production_profile=False, mock_used=True, mock_label_ref=None,
        fallback_reason_ref=None, template_response=False, production_success_claim=False,
    )
    direct_codes = {v.code for v in es.validate_mock_honesty(bad).violations}
    assert direct_codes, "前置：canonical 须确有违例（隔离测试有效性）"
    cr = section16_engineering_standards_check(_manifest_from_builder(mock_records=[bad]))
    assert set(cr.missing) == direct_codes, (
        f"producer→门 裁定须与 canonical validator 逐码一致·门得 {cr.missing}·canonical {direct_codes}"
    )


def test_no_whitewash_none_ref_preserved():
    """不洗白：mock 缺 label（None）→ 序列化 payload 的字段仍是 None（绝不被补成占位）。"""

    payload = es.build_section16_engineering_standards_record(
        mock_records=[es.MockHonestyRecord(
            record_ref="m::nl", production_profile=False, mock_used=True, mock_label_ref=None,
            fallback_reason_ref=None, template_response=False, production_success_claim=False,
        )]
    )
    d = payload["mock_records"][0]
    assert d["mock_label_ref"] is None and d["fallback_reason_ref"] is None, "None 字段绝不被洗成占位"


def test_no_whitewash_unmeasured_perf_preserved():
    """不洗白：未实测性能基线 → measured=False·observed_seconds=None 原样保留（绝不造 observed 时间）。"""

    payload = es.build_section16_engineering_standards_record(
        performance_records=[es.PerformanceBaselineMeasurement(
            baseline_ref="bl::g", metric_name="x", threshold_seconds=3.0, measured=False,
            observed_seconds=None, unavailable_reason="no prod data",
        )]
    )
    d = payload["performance_records"][0]
    assert d["measured"] is False and d["observed_seconds"] is None, "未实测绝不被造成 observed 达标时间"


def test_builder_emits_only_nonempty_families():
    """honest-absent 逐族：只给 mock → payload 只含 mock_records key（其余 5 族不发·非空壳）。"""

    payload = es.build_section16_engineering_standards_record(mock_records=[_clean_mock()])
    assert set(payload.keys()) == {"mock_records"}


def test_builder_field_names_match_gate_adapter_contract_and_json_safe():
    """faithful 契约：序列化 dict 的字段名即门 _adapt_* 读的 key（round-trip 不丢键）·tuple→list JSON-safe。"""

    payload = es.build_section16_engineering_standards_record(**_all_clean_kwargs())
    assert set(payload["mock_records"][0]) == {
        "record_ref", "production_profile", "mock_used", "mock_label_ref",
        "fallback_reason_ref", "template_response", "production_success_claim",
    }
    assert set(payload["data_updates"][0]) == {
        "update_ref", "dataset_version_ref", "checksum", "lineage_ref",
        "known_at_ref", "effective_at_ref", "data_test_refs",
    }
    assert set(payload["llm_calls"][0]) == {
        "call_ref", "provider_ref", "model_ref", "auth_ref", "cost_ref",
        "replay_state_ref", "llm_gateway_ref", "prompt_hash", "tool_schema_hash",
    }
    assert set(payload["theory_claims"][0]) == {
        "claim_ref", "display_label", "theory_implementation_binding_ref",
        "consistency_check_ref", "user_waiver_ref",
    }
    assert set(payload["fatal_records"][0]) == {
        "runtime_ref", "secret_plaintext_surfaces", "role_agent_bypassed_llm_gateway",
        "verifier_independence_claimed", "verifier_independence_record_ref",
        "a_share_live_order", "production_mock_fallback", "lookahead_leakage_detected",
    }
    assert set(payload["performance_records"][0]) == {
        "baseline_ref", "metric_name", "threshold_seconds", "measured",
        "observed_seconds", "evidence_ref", "unavailable_reason", "detail",
    }
    # tuple 字段 → JSON-safe list（manifest 是 run.json）
    assert isinstance(payload["data_updates"][0]["data_test_refs"], list)
    assert isinstance(payload["fatal_records"][0]["secret_plaintext_surfaces"], list)


def test_failclosed_wrong_record_type_in_family():
    """fail-closed：把 MockHonestyRecord 塞进 data_updates 槽 → raise TypeError（不静默吞·不产错位记录）。"""

    with pytest.raises(TypeError):
        es.build_section16_engineering_standards_record(data_updates=[_clean_mock()])


def test_failclosed_perf_record_must_be_three_state_measurement():
    """fail-closed：性能族塞 PerformanceBaselineRecord（非 3 态 Measurement）→ raise TypeError。

    强制 3 态量是「不洗白未实测」的根：只有带 measured 旗的量能诚实表达 gap，故 builder 拒收 2 字段的旧 record。
    """

    rec = es.PerformanceBaselineRecord(
        baseline_ref="bl::r", metric_name="x", observed_seconds=1.0, threshold_seconds=2.0, evidence_ref="ev::1",
    )
    with pytest.raises(TypeError):
        es.build_section16_engineering_standards_record(performance_records=[rec])


def test_none_or_falsy_family_is_honest_absent_not_silently_judged():
    """边界（codex 复核裁决）：None/空 list 的族 → honest-absent {}（同 shipped _typed_list(seq or ()) 约）。

    与 fail-closed 不矛盾：**非空错类型**才 raise（test_failclosed_*）；falsy 容器（None/[]/()）= 未声明该族·
    gate honest-bound（未声明≠违例）·完整性由 producer 绿灯门负责。不把 None 当违例硬拒（否则中心用 .get()
    取「无该类证据」时反致误拒诚实 run）。
    """

    assert es.build_section16_engineering_standards_record(mock_records=None, performance_records=None) == {}
    assert es.build_section16_engineering_standards_record(mock_records=[], data_updates=()) == {}


def test_input_flip_flips_gate_verdict_not_constant():
    """反作弊：同一 mock 补回 label+reason → 门由拒翻过（producer 真把字段变化传给门·非常量门）。"""

    bad = es.MockHonestyRecord(
        record_ref="m::f", production_profile=False, mock_used=True, mock_label_ref=None,
        fallback_reason_ref=None, template_response=False, production_success_claim=False,
    )
    good = es.MockHonestyRecord(
        record_ref="m::f", production_profile=False, mock_used=True, mock_label_ref="MOCK",
        fallback_reason_ref="net down", template_response=False, production_success_claim=False,
    )
    cr_bad = section16_engineering_standards_check(_manifest_from_builder(mock_records=[bad]))
    cr_good = section16_engineering_standards_check(_manifest_from_builder(mock_records=[good]))
    assert cr_bad.ok is False and cr_good.ok is True, "输入翻转 ok 必须跟着翻（producer 忠实·门真读 validator）"


# ════════════════════════════════════════════════════════════════════════════
# ⑥ 冷导入安全（SA-3 纪律·builder 在 research_os 纯 dataclass + stdlib 层·不触 governance 冷循环）
# ════════════════════════════════════════════════════════════════════════════
def test_builder_module_cold_importable():
    """冷导入：全新解释器 import engineering_standards + 调 builder（honest-absent）不撞既有冷导入循环。"""

    backend_root = Path(__file__).resolve().parents[1]  # app/backend
    code = (
        "import app.research_os.engineering_standards as m; "
        "assert m.build_section16_engineering_standards_record() == {}"
    )
    proc = subprocess.run(
        [sys.executable, "-c", code],
        cwd=str(backend_root),
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert proc.returncode == 0, (
        f"§16 producer builder 应冷导入成功:\nSTDOUT={proc.stdout}\nSTDERR={proc.stderr}"
    )
