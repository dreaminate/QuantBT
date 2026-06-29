"""C-S16-ENG-STD-PROMOTE-ENFORCE · §16 工程标准发版 check 插 SA-3 门链 · 对抗测试（RULES §2 种坏门必抓 + §3 诚实）。

可证伪验收（construction-map C-S16·6 族全经 engineering_standards 单一源判定）：
  · mock 缺 label/reason → check ok=False（mock_block_missing_label_or_reason）
  · 生产档靠 mock 兜底 → ok=False（production_profile_mock_fallback）
  · 数据更新缺 version/checksum/lineage → ok=False（data_update_missing_version_checksum_lineage）
  · data_test_refs < 5 → ok=False（data_update_too_few_data_tests）
  · LLM 调用缺 provider_ref → ok=False（llm_replay_missing_required_ref）
  · 强理论标签缺 binding/consistency → ok=False（strong_theory_claim_missing_binding_or_consistency）
  · FatalRecord 明文密钥泄露面非空 → ok=False（secret_plaintext_left_secure_backend）
  · 性能 observed > threshold → ok=False（performance_baseline_exceeded）
  · 性能 measured=False → KNOWN_RUN_GAP·never-green → ok=False（performance_baseline_known_run_gap）
  · 6 族全 clean + 性能实测达标 → ok=True
门链合成（复用 SA-3/SA-2·非本卡重测）：
  · 注册 + producer 绿 → 整链 ENFORCE 拒坏 manifest（blocks）
  · 注册 + producer 红/缺 → advisory：只记录不阻断（flip_refused·绝不误拒）
  · check 无 mode 字段 → 无法自封 enforce：mode 仅由 producer 绿灯翻（gaming-proof）
gameability：输入翻转 ok 跟着翻（非常量门）；复用 = 违例码精确来自 engineering_standards canonical validator。
fail-closed：节非 dict / 族非 list / 项非 dict / 性能记录缺门槛 / 声称已测却无 observed 时间 → 全 ok=False
  （违例绝不溜成 ok=True）。

★ producer 仍 RED（无假绿灯）：本卡**不建** producer 接线 `s16_engineering_standards_runjson_producers`（把真
  工程证据写进 manifest 那层 = 独立卡）。下方门链合成测试用**测试态本地** ProducerStatusLedger.mark_green(...)
  证明 enforce 行为为真——绝非生产假绿灯（生产 producer_status 默认 None=红·见
  test_absent_producer_status_advisory_only）。

★ mutation 三态（已手验·见任务报告）：把 section16_engineering_standards_gate._collect 里
  `if not result.accepted:` 弱化成 `if False:`（无视 engineering_standards canonical 裁定·让坏 run 溜成
  ok=True）→ test_mock_missing_label_flagged / test_production_profile_mock_fallback_flagged /
  test_data_update_missing_lineage_flagged / test_data_update_too_few_tests_flagged /
  test_llm_missing_provider_flagged / test_strong_theory_missing_binding_flagged /
  test_fatal_secret_plaintext_flagged / test_performance_exceeded_flagged 转 RED；
  test_performance_known_run_gap_never_green 仍 GREEN（gap 与 .accepted 正交·硬 never-green）→ 还原 → GREEN。
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

# 冷导入预热（既有循环·非本卡引入）：导入 app.governance.* 前先全载 orchestrator 解环——与
# test_promote_gate_chain.py / test_section13_trust_gate.py 同款顺序（app.governance 包 __init__ 经
# spine_invariants 触达 orchestrator）。
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
    SECTION16_ENGINEERING_STANDARDS_MANIFEST_KEY,
    SECTION16_ENGINEERING_STANDARDS_PRODUCER_KEY,
    register_section16_engineering_standards_gate,
    section16_engineering_standards_check,
)


# ════════════════════════════════════════════════════════════════════════════
# manifest 构造器（faithful §16 producer 契约·中心后续据此填）
# ════════════════════════════════════════════════════════════════════════════
def _manifest(section: dict | None) -> dict:
    m = {"run_id": "ide_promote_test", "status": "completed"}
    if section is not None:
        m[SECTION16_ENGINEERING_STANDARDS_MANIFEST_KEY] = section
    return m


# —— 各族的 clean 基线（过本族判定·从此删/篡一项隔离出对应违例）——
def _clean_mock() -> dict:
    return {"record_ref": "mock::1", "production_profile": True, "mock_used": False,
            "template_response": False, "production_success_claim": True}


def _clean_data_update() -> dict:
    return {"update_ref": "du::1", "dataset_version_ref": "dv::1", "checksum": "sha256::1",
            "lineage_ref": "lin::1", "known_at_ref": "k::1", "effective_at_ref": "e::1",
            "data_test_refs": ["t1", "t2", "t3", "t4", "t5"]}


def _clean_llm() -> dict:
    return {"call_ref": "llm::1", "provider_ref": "anthropic", "model_ref": "m::1", "auth_ref": "au::1",
            "cost_ref": "c::1", "replay_state_ref": "r::1", "llm_gateway_ref": "g::1",
            "prompt_hash": "ph::1", "tool_schema_hash": "th::1"}


def _clean_theory() -> dict:
    return {"claim_ref": "th::1", "display_label": "evidence_sufficient",
            "theory_implementation_binding_ref": "tib::1", "consistency_check_ref": "cc::1"}


def _clean_fatal() -> dict:
    return {"runtime_ref": "rt::1", "secret_plaintext_surfaces": []}


def _clean_perf() -> dict:
    return {"baseline_ref": "bl::1", "metric_name": "factor_calc", "threshold_seconds": 2.0,
            "measured": True, "observed_seconds": 1.0, "evidence_ref": "ev::1"}


def _clean_section() -> dict:
    """6 族全 clean·性能实测达标 → 无违例。"""

    return {
        "mock_records": [_clean_mock()],
        "data_updates": [_clean_data_update()],
        "llm_calls": [_clean_llm()],
        "theory_claims": [_clean_theory()],
        "fatal_records": [_clean_fatal()],
        "performance_records": [_clean_perf()],
    }


def _green_ledger() -> ProducerStatusLedger:
    led = ProducerStatusLedger()
    led.mark_green(SECTION16_ENGINEERING_STANDARDS_PRODUCER_KEY)  # 仅此卡测试态·绝非生产假绿灯
    return led


def _s16_verdict(result: ChainResult):
    matches = [v for v in result.verdicts if v.gate_name == SECTION16_ENGINEERING_STANDARDS_GATE_NAME]
    assert len(matches) == 1, "门链中应恰有一道 §16 工程标准门裁定"
    return matches[0]


# ════════════════════════════════════════════════════════════════════════════
# ① check 层：6 族坏门必抓（可证伪·mutation 目标）—— 每条只破一族隔离出对应码
# ════════════════════════════════════════════════════════════════════════════
def test_mock_missing_label_flagged():
    """★ 可证伪（mutation 目标）：mock_used 却缺 label/reason → ok=False·mock_block_missing_label_or_reason。"""

    cr = section16_engineering_standards_check(_manifest({
        "mock_records": [{"record_ref": "m::bad", "mock_used": True}]
    }))
    assert isinstance(cr, GateCheckResult)
    assert cr.ok is False
    assert "mock_block_missing_label_or_reason" in cr.missing


def test_production_profile_mock_fallback_flagged():
    """★ 可证伪（mutation 目标）：生产档靠 mock 兜底成功 → ok=False·production_profile_mock_fallback。

    给齐 label/reason 隔离掉缺 label 那条 → 单独剩生产档 mock 兜底。
    """

    cr = section16_engineering_standards_check(_manifest({
        "mock_records": [{"record_ref": "m::prod", "production_profile": True, "mock_used": True,
                          "mock_label_ref": "MOCK", "fallback_reason_ref": "net down"}]
    }))
    assert cr.ok is False
    assert "production_profile_mock_fallback" in cr.missing


def test_data_update_missing_lineage_flagged():
    """★ 可证伪（mutation 目标）：数据更新缺 checksum/lineage → ok=False·data_update_missing_version_checksum_lineage。

    保 5 条 data test 隔离掉 too-few-tests → 单独剩缺血统那条。
    """

    bad = dict(_clean_data_update())
    bad.pop("checksum")
    bad.pop("lineage_ref")
    cr = section16_engineering_standards_check(_manifest({"data_updates": [bad]}))
    assert cr.ok is False
    assert "data_update_missing_version_checksum_lineage" in cr.missing


def test_data_update_too_few_tests_flagged():
    """★ 可证伪（mutation 目标）：每表 < 5 条 data test → ok=False·data_update_too_few_data_tests。

    血统字段全齐隔离掉缺血统 → 单独剩 data test 太少那条。
    """

    bad = dict(_clean_data_update())
    bad["data_test_refs"] = ["t1", "t2"]  # 只有 2 条 < 5
    cr = section16_engineering_standards_check(_manifest({"data_updates": [bad]}))
    assert cr.ok is False
    assert "data_update_too_few_data_tests" in cr.missing


def test_llm_missing_provider_flagged():
    """★ 可证伪（mutation 目标）：LLM 调用缺 provider_ref → ok=False·llm_replay_missing_required_ref。"""

    bad = dict(_clean_llm())
    bad.pop("provider_ref")
    cr = section16_engineering_standards_check(_manifest({"llm_calls": [bad]}))
    assert cr.ok is False
    assert "llm_replay_missing_required_ref" in cr.missing


def test_strong_theory_missing_binding_flagged():
    """★ 可证伪（mutation 目标）：强理论标签缺 binding/consistency → ok=False·strong_theory_claim_missing_binding_or_consistency。"""

    cr = section16_engineering_standards_check(_manifest({
        "theory_claims": [{"claim_ref": "t::bad", "display_label": "proof_backed"}]
    }))
    assert cr.ok is False
    assert "strong_theory_claim_missing_binding_or_consistency" in cr.missing


def test_fatal_secret_plaintext_flagged():
    """★ 可证伪（mutation 目标）：FatalRecord 明文密钥泄露面非空 → ok=False·secret_plaintext_left_secure_backend。"""

    cr = section16_engineering_standards_check(_manifest({
        "fatal_records": [{"runtime_ref": "rt::leak", "secret_plaintext_surfaces": ["agent_prompt", "export_zip"]}]
    }))
    assert cr.ok is False
    assert "secret_plaintext_left_secure_backend" in cr.missing


def test_performance_exceeded_flagged():
    """★ 可证伪（mutation 目标）：性能 observed > threshold → ok=False·performance_baseline_exceeded。"""

    cr = section16_engineering_standards_check(_manifest({
        "performance_records": [{"baseline_ref": "bl::slow", "metric_name": "factor_calc",
                                 "threshold_seconds": 1.0, "measured": True,
                                 "observed_seconds": 5.0, "evidence_ref": "ev::1"}]
    }))
    assert cr.ok is False
    assert "performance_baseline_exceeded" in cr.missing


def test_performance_measured_missing_evidence_flagged():
    """可证伪：实测但缺 evidence_ref（无可验证实测证据）→ ok=False·performance_baseline_missing_evidence。

    observed ≤ threshold 隔离掉 exceeded → 单独剩缺证据那条（canonical 第 2 条性能违例码）。
    """

    cr = section16_engineering_standards_check(_manifest({
        "performance_records": [{"baseline_ref": "bl::noev", "metric_name": "factor_calc",
                                 "threshold_seconds": 2.0, "measured": True, "observed_seconds": 1.0}]
    }))
    assert cr.ok is False
    assert "performance_baseline_missing_evidence" in cr.missing


def test_performance_known_run_gap_never_green():
    """★ 可证伪（KNOWN_RUN_GAP·与 .accepted 正交）：性能 measured=False → ok=False·performance_baseline_known_run_gap。

    诚实 3 态灵魂：未实测基线**永不视绿**·不能用任何字段把 gap 洗成 pass。此条不随 `_collect` 的
    `if not result.accepted` mutation 翻（gap 在 `_collect` 之外硬收）。
    """

    cr = section16_engineering_standards_check(_manifest({
        "performance_records": [{"baseline_ref": "bl::gap", "metric_name": "hs300_read",
                                 "threshold_seconds": 3.0, "measured": False, "observed_seconds": None,
                                 "unavailable_reason": "production dataset absent in this env"}]
    }))
    assert cr.ok is False
    assert "performance_baseline_known_run_gap" in cr.missing


def test_fatal_extra_flags_flagged():
    """补充可证伪：A 股实盘/前视泄露等致命标记 → ok=False·fatal_engineering_error_detected（致命门）。"""

    cr = section16_engineering_standards_check(_manifest({
        "fatal_records": [{"runtime_ref": "rt::fatal", "a_share_live_order": True}]
    }))
    assert cr.ok is False
    assert "fatal_engineering_error_detected" in cr.missing


def test_clean_section_passes():
    """6 族全 clean + 性能实测达标 → ok=True·无 missing。"""

    cr = section16_engineering_standards_check(_manifest(_clean_section()))
    assert cr.ok is True
    assert cr.missing == ()


# ════════════════════════════════════════════════════════════════════════════
# ② 诚实边界（RULES §3）+ 反作弊（gameability）+ 复用证明
# ════════════════════════════════════════════════════════════════════════════
def test_absent_section_is_ok_documented_limit():
    """诚实限界：manifest 未声明 §16 结构 → ok=True（无可证伪违例·非『整本已查清』）。

    『查清』由 producer 绿灯门负责——producer 未绿时本门只 advisory（见门链合成测试）。
    """

    cr = section16_engineering_standards_check(_manifest(None))
    assert cr.ok is True
    assert cr.missing == ()
    assert "无可证伪" in cr.reason


def test_empty_section_nothing_declared_ok():
    """诚实限界：section16_engineering_standards={}（6 族均缺）→ ok=True（未声明·非违例）。"""

    cr = section16_engineering_standards_check(_manifest({}))
    assert cr.ok is True
    assert cr.missing == ()


def test_input_flip_flips_ok_not_constant_gate():
    """反作弊：同一 mock 记录补回 label+reason，ok 由 False 翻 True（门真读 validator 输出·非常量门）。"""

    bad = section16_engineering_standards_check(_manifest({
        "mock_records": [{"record_ref": "m::x", "mock_used": True}]
    }))
    good = section16_engineering_standards_check(_manifest({
        "mock_records": [{"record_ref": "m::x", "mock_used": True,
                          "mock_label_ref": "MOCK", "fallback_reason_ref": "net down"}]
    }))
    assert bad.ok is False and good.ok is True, "输入翻转 ok 必须跟着翻（门真读 validator 输出）"


def test_performance_measured_flip_flips_ok():
    """反作弊（性能 3 态）：同一基线 measured=False(gap) → measured=True+实测达标，ok 由 False 翻 True。"""

    gap = section16_engineering_standards_check(_manifest({
        "performance_records": [{"baseline_ref": "bl::p", "metric_name": "x", "threshold_seconds": 2.0,
                                 "measured": False, "observed_seconds": None,
                                 "unavailable_reason": "no prod data"}]
    }))
    ok = section16_engineering_standards_check(_manifest({
        "performance_records": [{"baseline_ref": "bl::p", "metric_name": "x", "threshold_seconds": 2.0,
                                 "measured": True, "observed_seconds": 0.5, "evidence_ref": "ev::1"}]
    }))
    assert gap.ok is False and ok.ok is True, "未实测 gap 必不绿·实测达标才绿"


def test_missing_codes_come_from_canonical_validator():
    """复用证明：missing 里的工程标准码是 engineering_standards canonical validator 原码（非本模块自造）。"""

    from app.research_os import engineering_standards as es

    cr = section16_engineering_standards_check(_manifest({
        "mock_records": [{"record_ref": "m::bad", "mock_used": True}]
    }))
    assert "mock_block_missing_label_or_reason" in cr.missing
    # 这条码在 canonical validator 里硬编码（同一源）——本 check 只搬运不重造。
    assert "mock_block_missing_label_or_reason" in Path(es.__file__).read_text(encoding="utf-8")


# ════════════════════════════════════════════════════════════════════════════
# ③ fail-closed 加固（codex 对抗复审 C-S9 同款洞·堵 fail-open：违例绝不溜成 ok=True）
# ════════════════════════════════════════════════════════════════════════════
def test_malformed_section_failcloses():
    """fail-closed：§16 节存在但非 dict（被填成 list）→ ok=False（格式非法不静默放行）。"""

    m = {"run_id": "r", SECTION16_ENGINEERING_STANDARDS_MANIFEST_KEY: ["not", "a", "dict"]}
    cr = section16_engineering_standards_check(m)
    assert cr.ok is False
    assert "section16_engineering_standards_malformed" in cr.missing


def test_family_as_mapping_does_not_failopen():
    """坏门变形：把 mock_records 填成 {id: rec} 映射（非 list）藏一条缺 label 的 mock。

    非 list 的族不得静默 skip → 现 fail-closed：记 malformed·ok=False（违例绝不溜走）。
    """

    m = _manifest({
        "mock_records": {"m::hidden": {"record_ref": "m::hidden", "mock_used": True}}
    })
    cr = section16_engineering_standards_check(m)
    assert cr.ok is False, "非 list 的族不得静默放行藏在里面的违例"
    assert "section16_engineering_standards_mock_records_malformed" in cr.missing


def test_family_list_with_nondict_item_failcloses():
    """坏门变形：族是 list 但含非 dict 项 → fail-closed malformed（不静默 skip）。"""

    m = _manifest({"llm_calls": ["not-a-dict"]})
    cr = section16_engineering_standards_check(m)
    assert cr.ok is False
    assert "section16_engineering_standards_llm_calls_malformed" in cr.missing


def test_performance_family_as_mapping_failcloses():
    """坏门变形：performance_records 被填成映射（非 list）→ fail-closed malformed·ok=False。"""

    m = _manifest({"performance_records": {"bl::x": {"baseline_ref": "bl::x", "measured": False}}})
    cr = section16_engineering_standards_check(m)
    assert cr.ok is False
    assert "section16_engineering_standards_performance_records_malformed" in cr.missing


def test_performance_list_with_nondict_item_failcloses():
    """坏门变形：performance_records 是 list 但含非 dict 项 → fail-closed malformed（不静默 skip）。"""

    cr = section16_engineering_standards_check(_manifest({"performance_records": ["not-a-dict"]}))
    assert cr.ok is False
    assert "section16_engineering_standards_performance_records_malformed" in cr.missing


def test_performance_missing_threshold_failcloses():
    """fail-closed：性能记录缺 threshold_seconds（无门槛无从判定）→ ok=False·_performance_records_unparseable。"""

    m = _manifest({"performance_records": [{"baseline_ref": "bl::nothr", "measured": True,
                                            "observed_seconds": 1.0, "evidence_ref": "ev::1"}]})
    cr = section16_engineering_standards_check(m)
    assert cr.ok is False
    assert "section16_engineering_standards_performance_records_unparseable" in cr.missing


def test_performance_measured_without_observed_failcloses():
    """fail-closed：声称 measured=True 却无 observed_seconds（冒充已测）→ classify 抛 → ok=False·unparseable。

    诚实灵魂：不能既说「我测了」又拿不出实测时间——这条洞必须 fail-closed，不得溜成 gap 也不得溜成 pass。
    """

    m = _manifest({"performance_records": [{"baseline_ref": "bl::lie", "metric_name": "x",
                                            "threshold_seconds": 2.0, "measured": True,
                                            "observed_seconds": None, "evidence_ref": "ev::1"}]})
    cr = section16_engineering_standards_check(m)
    assert cr.ok is False
    assert "section16_engineering_standards_performance_records_unparseable" in cr.missing


def test_nonmapping_manifest_failcloses_not_open():
    """fail-closed：manifest 不是 Mapping（如 list）→ check **抛**（不静默 ok=True）；门链据此 errored 阻断。"""

    with pytest.raises(Exception):
        section16_engineering_standards_check(["not", "a", "mapping"])  # type: ignore[arg-type]

    # 经门链（producer 绿）：check 抛 → fail-closed errored → 阻断（坏 manifest 绝不静默晋级）。
    chain = PromoteGateChain()
    register_section16_engineering_standards_gate(chain)
    result = chain.evaluate(["not", "a", "mapping"], producer_status=_green_ledger())  # type: ignore[arg-type]
    v = _s16_verdict(result)
    assert v.ok is False and v.errored is True and v.blocks is True


# ════════════════════════════════════════════════════════════════════════════
# ④ 门链合成：注册 + producer 绿/红 → enforce/advisory（复用 SA-3/SA-2）
# ════════════════════════════════════════════════════════════════════════════
def test_registered_green_producer_enforces_and_rejects():
    """★ 注册 + producer 绿 → 整链 ENFORCE 拒坏 manifest（blocks·ok=False·缺项精确）。"""

    chain = PromoteGateChain()
    register_section16_engineering_standards_gate(chain)
    result = chain.evaluate(
        _manifest({"mock_records": [{"record_ref": "m::bad", "mock_used": True}]}),
        producer_status=_green_ledger(),
    )

    assert isinstance(result, ChainResult)
    assert result.rejected is True, "producer 绿 + §16 违例 → 整链必须拒晋级"
    v = _s16_verdict(result)
    assert v.advisory_or_enforce == MODE_ENFORCE
    assert v.blocks is True and v.ok is False
    assert v.producer_key == SECTION16_ENGINEERING_STANDARDS_PRODUCER_KEY
    assert "mock_block_missing_label_or_reason" in v.missing


def test_known_run_gap_blocks_under_green_enforce():
    """★ never-green 终局证明：producer 绿 + 未实测基线（gap）→ 整链 ENFORCE 阻断（gap 不可晋级）。"""

    chain = PromoteGateChain()
    register_section16_engineering_standards_gate(chain)
    result = chain.evaluate(
        _manifest({"performance_records": [{"baseline_ref": "bl::gap", "metric_name": "x",
                                            "threshold_seconds": 2.0, "measured": False,
                                            "observed_seconds": None, "unavailable_reason": "no prod data"}]}),
        producer_status=_green_ledger(),
    )
    assert result.rejected is True, "未实测基线在 enforce 下必须阻断晋级（never-green）"
    v = _s16_verdict(result)
    assert v.blocks is True and "performance_baseline_known_run_gap" in v.missing


def test_registered_red_producer_advisory_only_not_blocking():
    """★ 注册 + producer 红/缺 → advisory：坏 manifest 被记录但**不**阻断（flip_refused·绝不误拒）。"""

    chain = PromoteGateChain()
    register_section16_engineering_standards_gate(chain)
    result = chain.evaluate(
        _manifest({"mock_records": [{"record_ref": "m::bad", "mock_used": True}]}),
        producer_status=ProducerStatusLedger(),
    )

    assert result.rejected is False, "producer 未绿 → §16 门只 advisory·绝不阻断诚实 run"
    v = _s16_verdict(result)
    assert v.advisory_or_enforce == MODE_ADVISORY
    assert v.flip_refused is True, "拒翻必须被记录（非静默）"
    assert v.ok is False and v.blocks is False, "门诚实记下未过·但 advisory 不阻断"
    assert v in result.advisories


def test_absent_producer_status_advisory_only():
    """★ 无假绿灯：producer_status=None（生产默认）→ §16 门 advisory·producer_green=False·不阻断。"""

    chain = PromoteGateChain()
    register_section16_engineering_standards_gate(chain)
    result = chain.evaluate(
        _manifest({"mock_records": [{"record_ref": "m::bad", "mock_used": True}]}),
        producer_status=None,
    )

    assert result.rejected is False
    v = _s16_verdict(result)
    assert v.advisory_or_enforce == MODE_ADVISORY
    assert v.producer_green is False, "确认 producer 仍 RED（出厂红·无假绿灯）"
    assert v.blocks is False


def test_check_cannot_self_declare_enforce_mode_from_policy_only():
    """gaming-proof：check 输出无 mode 字段 → 无法自封 enforce；mode 仅随 producer 绿灯翻。

    同一 check、同一坏 manifest：producer 红→advisory、producer 绿→enforce。check 自己改变不了这个。
    """

    bad = _manifest({"mock_records": [{"record_ref": "m::bad", "mock_used": True}]})
    cr = section16_engineering_standards_check(bad)
    assert not hasattr(cr, "advisory_or_enforce") and not hasattr(cr, "mode"), \
        "GateCheckResult 结构上不携 mode → check 无从自封 enforce"

    chain = PromoteGateChain()
    register_section16_engineering_standards_gate(chain)
    red = _s16_verdict(chain.evaluate(bad, producer_status=ProducerStatusLedger()))
    green = _s16_verdict(chain.evaluate(bad, producer_status=_green_ledger()))
    assert red.advisory_or_enforce == MODE_ADVISORY
    assert green.advisory_or_enforce == MODE_ENFORCE, "仅 producer 绿灯能把同一门翻 enforce"


def test_green_producer_clean_section_passes_chain():
    """绿 producer + clean 工程标准 → 不拒（enforce 门通过·证明 enforce 不误伤诚实 run）。"""

    chain = PromoteGateChain()
    register_section16_engineering_standards_gate(chain)
    result = chain.evaluate(_manifest(_clean_section()), producer_status=_green_ledger())
    assert result.rejected is False
    v = _s16_verdict(result)
    assert v.advisory_or_enforce == MODE_ENFORCE and v.ok is True


def test_registration_uses_documented_producer_key_and_intent():
    """注册契约：gate_name / required_producer 为文档化常量·enforce_intent 真（绿即翻 enforce·不张冠李戴）。"""

    chain = PromoteGateChain()
    register_section16_engineering_standards_gate(chain)
    assert SECTION16_ENGINEERING_STANDARDS_GATE_NAME in chain.gate_names
    # producer 绿 → enforce（证明 enforce_intent=True 且绑定的 producer key 即文档常量）。
    v = _s16_verdict(chain.evaluate(_manifest(_clean_section()), producer_status=_green_ledger()))
    assert v.producer_key == SECTION16_ENGINEERING_STANDARDS_PRODUCER_KEY
    assert v.advisory_or_enforce == MODE_ENFORCE
    # 别的 producer key 绿 → §16 门**不**翻（防张冠李戴）。
    other = ProducerStatusLedger()
    other.mark_green("some_other_producer")
    v2 = _s16_verdict(chain.evaluate(_manifest(_clean_section()), producer_status=other))
    assert v2.advisory_or_enforce == MODE_ADVISORY and v2.flip_refused is True


# ════════════════════════════════════════════════════════════════════════════
# ⑤ 冷导入安全（SA-3 纪律·镜像 section9/section10/section13/section17 模块）
# ════════════════════════════════════════════════════════════════════════════
def test_module_cold_importable():
    """冷导入：全新解释器 import 本模块**不**撞 app.governance 既有冷导入循环。

    顶层只依赖 promote_gate_chain（cold-safe）+ research_os.engineering_standards（cold-safe·纯 dataclass + stdlib）。
    """

    backend_root = Path(__file__).resolve().parents[1]  # app/backend
    code = (
        "import app.release_gate.section16_engineering_standards_gate as m; "
        "assert m.section16_engineering_standards_check and m.register_section16_engineering_standards_gate"
    )
    proc = subprocess.run(
        [sys.executable, "-c", code],
        cwd=str(backend_root),
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert proc.returncode == 0, (
        f"§16 工程标准门模块应冷导入成功:\nSTDOUT={proc.stdout}\nSTDERR={proc.stderr}"
    )
