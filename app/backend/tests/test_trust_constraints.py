"""§13 信任层硬约束门的【对抗式】测试（GOAL §13 信任层 · 恰当依赖 R24）。

验收标准（RULES §2）：不是「测函数跑通」，而是「种一个已知的坏门，信任门必须抓住，否则门是纸做的」。
GOAL §13 + 卡可证伪验收逐条种坏：

  ① waiver 绕过 secret/OrderGuard/kill switch/no-silent-mock → 必拒（命门·MUT 放过→红·安全不变量不可 waiver）。
  ② Agent 顺从 user wishful thinking 输出强结论(稳赢/忽略 N/忽略成本/忽略泄露/越级实盘) → 必拒（反谄媚）。
  ③ 弱点/风险默认隐藏 / user waiver 被隐藏 → 必拒（弱点一等呈现 R25 + 不隐藏 waiver）。
  ④ user 承担风险但缺/不全 ResponsibilityDisclosureRecord → 必拒；伪造 proof_backed/evidence_sufficient/
     production_ready → 必拒（诚实硬约束·强标签真假委派已建证据门）。
  外加：单人模式声明组织独立 → 拒；Agent 替 user 拍板方法学/风险 → 拒；冷启动 N=1 包装成统计证据 → 拒。

正路径不误伤（同样硬）：合法方法学放宽（非安全）、user 自负其责后非红线交付、证据齐的强结论/强标签、
弱点全展示 —— 必须放行，否则门「管太宽」（违 §0.1 / R26）。
"""

from __future__ import annotations

import pytest

from app.lineage.spine import (
    CHECK_PASS,
    LABEL_EVIDENCE_SUFFICIENT,
    LABEL_EXPLORATORY,
    LABEL_PRODUCTION_READY,
    LABEL_PROOF_BACKED,
    ConsistencyCheck,
    MathematicalArtifact,
    MethodologyChoiceRecord,
    TheoryImplementationBinding,
)
from app.lineage.spine import ARTIFACT_FACTOR_FORMULA
from app.lineage.ids import content_hash
from app.lineage.spine_gate import evaluate_promotion
from app.methodology.control_plane import (
    MethodologyTier,
    build_methodology_choice,
    constrain_promotion,
)
import app.trust.trust_constraints as tc
from app.trust import (
    AGENT_DECIDED_FOR_USER,
    FAKE_CONSISTENCY,
    FAKE_ORG_INDEPENDENCE,
    FAKE_STRONG_LABEL,
    INCOMPLETE_RESPONSIBILITY,
    INV_KILL_SWITCH,
    INV_NO_SILENT_MOCK,
    INV_ORDER_GUARD,
    INV_SECRET,
    MISSING_RESPONSIBILITY,
    SAFETY_INVARIANTS,
    WAIVER_HIDDEN,
    WEAKNESS_HIDDEN,
    AgentConclusion,
    DisclosureManifest,
    ResponsibilityDisclosureRecord,
    SafetyWaiverError,
    TrustClaim,
    TrustContext,
    TrustRejected,
    WaiverRequest,
    assert_safety_invariants_intact,
    check_anti_sycophancy,
    check_honesty_constraints,
    check_responsibility,
    check_user_autonomy,
    check_weakness_disclosure,
    collect_waived_targets,
    evaluate_trust,
    evaluate_waiver_safety,
    gate_anti_sycophancy,
    gate_waiver_safety,
    map_target_to_safety_invariant,
    require_trustworthy,
)


# ─────────────────────────── helpers ───────────────────────────
def _complete_responsibility(actor: str = "user") -> ResponsibilityDisclosureRecord:
    return ResponsibilityDisclosureRecord(
        asset_ref="strat-x",
        boundary="系统给放宽档方法 + 诚实标注；样本外漂移与解读风险由 user 自担",
        risk_owner="user",
        user_accepted_risk=True,
        accepted_risks=("放宽稳健性门后的过拟合风险", "样本外失效风险"),
        recommendation="命中后用 standard/strict 复跑确认再谈强结论",
        actor=actor,
    )


def _promotable_evidence_sufficient_decision():
    """造一条【真】过 spine 一致性门的 evidence_sufficient 裁定（reuse evaluate_promotion·非自判）。"""

    code_src = "def factor(x): return x.zscore()"
    code_hash = content_hash(code_src)
    artifact = MathematicalArtifact(
        artifact_type=ARTIFACT_FACTOR_FORMULA,
        statement="z = (x - mean) / std",
        definition="横截面 zscore 标准化",
        derivation="(x-μ)/σ 的样本估计",
    )
    binding = TheoryImplementationBinding(
        theory_ref=artifact.artifact_id,
        code_ref="factor_factory/zscore.py::factor",
        code_content_hash=code_hash,
        config_ref="cfg_v1_demo",
        data_contract_ref="dc_demo",
        test_refs=("tests/test_zscore.py::test_basic",),
    )
    check = ConsistencyCheck(
        binding_id=binding.binding_id,
        check_type="numerical",
        result=CHECK_PASS,
        expected_property="zscore 均值≈0 方差≈1",
        observed_property="均值 1e-9 方差 1.0",
    )
    decision = evaluate_promotion(
        artifact,
        binding,
        [check],
        requested_label=LABEL_EVIDENCE_SUFFICIENT,
        current_code_hash=code_hash,
    )
    assert decision.promotable and decision.granted_label == LABEL_EVIDENCE_SUFFICIENT
    return decision


# ═══════════════════════ A. waiver-safety 命门 ═══════════════════════
@pytest.mark.parametrize(
    "target,expected",
    [
        ("把实盘 secret 注入 LLM 做调试", INV_SECRET),
        ("明文落库 api_key", INV_SECRET),
        ("user 私钥直接给模型", INV_SECRET),
        ("跳过 OrderGuard 直接 place_order", INV_ORDER_GUARD),
        ("放开提币 withdraw 限制", INV_ORDER_GUARD),
        ("绕过策略门下单", INV_ORDER_GUARD),
        ("关掉 kill switch 熔断", INV_KILL_SWITCH),
        ("禁用回撤熔断 max_drawdown_halt", INV_KILL_SWITCH),
        ("紧急平仓功能先关掉", INV_KILL_SWITCH),
        ("生产结果走 silent mock fallback", INV_NO_SILENT_MOCK),
        ("让 template 冒充生产成功", INV_NO_SILENT_MOCK),
        ("no-silent-mock 检查先跳过", INV_NO_SILENT_MOCK),
    ],
)
def test_map_target_to_safety_invariant_catches_each(target, expected):
    assert map_target_to_safety_invariant(target) == expected


@pytest.mark.parametrize("benign", ["减少 CPCV 折数", "放宽多重检验门", "缩短样本要求", "跳过通缩区间深扫", ""])
def test_map_benign_methodology_target_is_not_safety(benign):
    # 正路径不误伤：合法方法学放宽不得被误判成安全不变量。
    assert map_target_to_safety_invariant(benign) is None


def test_each_safety_invariant_has_a_catching_alias():
    """MUT 守门：四个安全不变量每个都至少被一条别名抓到（删别名表任一族 → 这里转红）。"""

    hits = {
        map_target_to_safety_invariant(s)
        for s in (
            "secret 进 llm",
            "orderguard 绕过",
            "kill switch 关闭",
            "silent mock fallback",
        )
    }
    assert hits == SAFETY_INVARIANTS


@pytest.mark.parametrize(
    "target",
    [
        "把实盘 secret 注入 LLM",
        "跳过 OrderGuard 直接下单",
        "关掉 kill switch",
        "生产结果走 silent mock fallback",
    ],
)
def test_waiver_bypassing_safety_invariant_refused(target):
    """命门①：waiver 绕过任一安全不变量 → 拒（结构化 + 硬 raise 双路径）。"""

    d = evaluate_waiver_safety([target])
    assert d.bypass_attempted is True
    assert d.ok is False
    assert len(d.refused_safety_targets) == 1
    assert d.refused_safety_targets[0][0] == target
    assert target not in d.permitted_targets
    with pytest.raises(SafetyWaiverError):
        assert_safety_invariants_intact([target])


def test_methodology_skipped_steps_smuggling_safety_refused():
    """命门：借方法学放权之名把安全不变量塞进 skipped_steps 偷渡 → 仍被抓（复用 MCR·叠加安全边界）。"""

    mcr = MethodologyChoiceRecord(
        chosen_path="custom",
        skipped_steps=("放宽部分稳健性门", "顺手关掉 kill switch 熔断"),
        responsibility_boundary="user 自担",
        actor="user",
    )
    targets = collect_waived_targets(methodology_choice=mcr)
    d = evaluate_waiver_safety(targets)
    assert d.bypass_attempted is True
    assert any(inv == INV_KILL_SWITCH for _, inv in d.refused_safety_targets)
    # 非安全的那条仍可放宽（不误伤研究自由）。
    assert "放宽部分稳健性门" in d.permitted_targets


def test_evaluate_trust_raises_on_safety_waiver_hard_stop():
    """命门在聚合入口走【硬 raise】（撞即停）——绝不降级成 soft ok=False。"""

    ctx = TrustContext(
        asset_ref="a",
        waiver=WaiverRequest(waived_targets=("关掉 kill switch 让策略一直跑",), actor="user"),
    )
    with pytest.raises(SafetyWaiverError):
        evaluate_trust(ctx)
    with pytest.raises(SafetyWaiverError):
        require_trustworthy(ctx)


def test_gate_waiver_safety_wrapper_shape():
    bad = gate_waiver_safety(["把 secret 喂给 LLM"])
    assert bad.passed is False
    assert tc.SAFETY_WAIVER_BYPASS in bad.violation_codes
    good = gate_waiver_safety(["放宽多重检验门"])
    assert good.passed is True


def test_methodology_relaxation_not_safety_is_permitted():
    """正路径不误伤：纯方法学放宽（无安全不变量）→ 放行、全部进 permitted、不 raise。"""

    targets = ["放宽稳健性门", "减少 CPCV 折数", "缩短样本要求"]
    d = evaluate_waiver_safety(targets)
    assert d.bypass_attempted is False
    assert set(d.permitted_targets) == set(targets)
    assert_safety_invariants_intact(targets)  # 不抛


# ═══════════════════════ B. 反谄媚 ═══════════════════════
def test_sure_win_strong_conclusion_refused():
    """可证伪验收②：声称稳赢的强结论 → 拒、降级、给缺口+证据+下一步（即便 user 施压）。"""

    c = AgentConclusion(
        text="这个策略稳赢，直接梭哈",
        strength=tc.STRENGTH_STRONG,
        claims_sure_win=True,
        cost_modeled=False,
        leakage_checked=False,
        sample_n=None,
        user_pressure="你就告诉我能不能稳赚，别跟我扯风险",
    )
    d = check_anti_sycophancy(c)
    assert d.ok is False
    assert d.refused_strong_conclusion is True
    assert d.sure_win_refused is True
    assert d.permit_sure_win is False
    assert d.permitted_strength != tc.STRENGTH_STRONG
    assert d.gaps and d.evidence_requirements and d.next_steps  # 给缺口/证据/下一步


def test_strong_conclusion_ignoring_cost_refused():
    c = AgentConclusion(
        strength=tc.STRENGTH_STRONG,
        cost_modeled=False,
        leakage_checked=True,
        multiple_testing_controlled=True,
        sample_n=500,
    )
    d = check_anti_sycophancy(c)
    assert d.refused_strong_conclusion is True
    assert any("成本" in g for g in d.gaps)


def test_strong_conclusion_ignoring_leakage_refused():
    c = AgentConclusion(
        strength=tc.STRENGTH_STRONG,
        cost_modeled=True,
        leakage_checked=False,
        multiple_testing_controlled=True,
        sample_n=500,
    )
    d = check_anti_sycophancy(c)
    assert d.refused_strong_conclusion is True
    assert any("泄露" in g for g in d.gaps)


def test_strong_conclusion_n_unknown_refused():
    c = AgentConclusion(
        strength=tc.STRENGTH_STRONG,
        cost_modeled=True,
        leakage_checked=True,
        sample_n=None,
    )
    d = check_anti_sycophancy(c)
    assert d.refused_strong_conclusion is True
    assert any("N 未追踪" in g or "N 未知" in g for g in d.gaps)


def test_cold_start_n1_not_packaged_as_statistical_refused():
    """GOAL §13 + R27：冷启动 N=1 包装成统计证据 → 拒（标先验断言·非统计证据）。"""

    c = AgentConclusion(
        strength=tc.STRENGTH_STRONG,
        cost_modeled=True,
        leakage_checked=True,
        multiple_testing_controlled=True,
        sample_n=1,
    )
    d = check_anti_sycophancy(c)
    assert d.refused_strong_conclusion is True
    assert any("N=1" in g and "冷启动" in g for g in d.gaps)


def test_strong_conclusion_uncontrolled_multiple_testing_refused():
    c = AgentConclusion(
        strength=tc.STRENGTH_STRONG,
        cost_modeled=True,
        leakage_checked=True,
        multiple_testing_controlled=False,
        sample_n=500,
    )
    d = check_anti_sycophancy(c)
    assert d.refused_strong_conclusion is True
    assert any("多重检验" in g for g in d.gaps)


def test_live_escalation_without_staged_validation_refused():
    c = AgentConclusion(
        strength=tc.STRENGTH_TENTATIVE,
        proposes_live_escalation=True,
        staged_validation_done=False,
    )
    d = check_anti_sycophancy(c)
    assert any("越级实盘" in g for g in d.gaps)
    assert d.ok is False  # 越级实盘缺阶梯 = 不放行（须安全门 + 阶梯）


def test_sure_win_refused_even_when_not_strong():
    """稳赢断言在任何强度都被剥离（exploratory 也不背书稳赢）。"""

    c = AgentConclusion(strength=tc.STRENGTH_EXPLORATORY, claims_sure_win=True)
    d = check_anti_sycophancy(c)
    assert d.sure_win_refused is True
    assert d.ok is False


def test_honest_strong_conclusion_with_full_evidence_permitted():
    """正路径不误伤：证据姿态齐的强结论（无稳赢/越级·成本+泄露+多重检验+N 足）→ 放行。"""

    c = AgentConclusion(
        strength=tc.STRENGTH_STRONG,
        claims_sure_win=False,
        proposes_live_escalation=False,
        cost_modeled=True,
        leakage_checked=True,
        multiple_testing_controlled=True,
        sample_n=750,
    )
    d = check_anti_sycophancy(c)
    assert d.ok is True
    assert d.refused_strong_conclusion is False
    assert d.permitted_strength == tc.STRENGTH_STRONG
    assert d.gaps == ()


def test_gate_anti_sycophancy_wrapper_flags():
    bad = gate_anti_sycophancy(AgentConclusion(strength=tc.STRENGTH_STRONG, claims_sure_win=True))
    assert bad.passed is False
    assert tc.SYCOPHANTIC_STRONG_CONCLUSION in bad.violation_codes
    good = gate_anti_sycophancy(
        AgentConclusion(
            strength=tc.STRENGTH_STRONG,
            cost_modeled=True,
            leakage_checked=True,
            multiple_testing_controlled=True,
            sample_n=500,
        )
    )
    assert good.passed is True


def test_invalid_conclusion_strength_raises():
    with pytest.raises(ValueError):
        AgentConclusion(strength="definitely")


# ═══════════════════════ C. 弱点一等呈现 ═══════════════════════
def test_hidden_weakness_refused():
    """可证伪验收③：已知弱点未展示（默认隐藏）→ 拒（R25 弱点一等呈现·绝不淡化）。"""

    m = DisclosureManifest(
        known_weaknesses=("过拟合风险高", "样本期只有 1 年"),
        shown=("过拟合风险高",),  # 「样本期只有 1 年」被悄悄藏了
    )
    d = check_weakness_disclosure(m)
    assert d.passed is False
    assert WEAKNESS_HIDDEN in d.violation_codes
    assert any("样本期只有 1 年" in v.reason for v in d.violations)


def test_explicitly_hidden_item_refused():
    m = DisclosureManifest(
        known_weaknesses=("最大回撤 60%",),
        shown=("最大回撤 60%",),
        hidden=("最大回撤 60%",),  # 即便也在 shown，被标 hidden 即拒
    )
    d = check_weakness_disclosure(m)
    assert d.passed is False
    assert WEAKNESS_HIDDEN in d.violation_codes


def test_hidden_user_waiver_refused():
    """可证伪验收③：user waiver 被隐藏 → 拒（不得隐藏 user waiver / user-waived 弱点不默认隐藏）。"""

    m = DisclosureManifest(
        waivers=("user_waived_validation:mcr_abc",),
        shown_waivers=(),  # waiver 没展示
    )
    d = check_weakness_disclosure(m)
    assert d.passed is False
    assert WAIVER_HIDDEN in d.violation_codes


def test_all_weaknesses_and_waivers_shown_permitted():
    """正路径不误伤：弱点全展示 + waiver 全展示 + 无标隐藏 → 放行。"""

    m = DisclosureManifest(
        known_weaknesses=("过拟合风险", "样本短"),
        shown=("过拟合风险", "样本短"),
        hidden=(),
        waivers=("user_waived: loose",),
        shown_waivers=("user_waived: loose",),
    )
    d = check_weakness_disclosure(m)
    assert d.passed is True


# ═══════════════════════ D. 诚实硬约束（强标签真假委派已建证据门）═══════════════════════
def test_fake_proof_backed_without_decision_refused():
    """可证伪验收④：声称 proof_backed 但无任何证据门裁定背书 → 拒（伪造强标签）。"""

    d = check_honesty_constraints(TrustClaim(asset_ref="a", claimed_label=LABEL_PROOF_BACKED))
    assert d.passed is False
    assert FAKE_STRONG_LABEL in d.violation_codes


def test_fake_strong_label_when_spine_not_promotable_refused():
    """声称 production_ready 但 spine 一致性门未放行（只授诚实弱标签）→ 拒。"""

    sd = evaluate_promotion(
        None, None, [], requested_label=LABEL_PRODUCTION_READY  # 啥证据都没给 → 不可升级
    )
    assert sd.promotable is False
    d = check_honesty_constraints(
        TrustClaim(asset_ref="a", claimed_label=LABEL_PRODUCTION_READY, spine_decision=sd)
    )
    assert d.passed is False
    assert FAKE_STRONG_LABEL in d.violation_codes


def test_fake_evidence_sufficient_via_relaxed_tier_cap_refused():
    """放宽档(loose)把 evidence_sufficient cap 成 exploratory，却仍声称 evidence_sufficient → 拒。"""

    sd = _promotable_evidence_sufficient_decision()  # spine 这关过
    choice = build_methodology_choice(MethodologyTier.LOOSE)
    md = constrain_promotion(MethodologyTier.LOOSE, LABEL_EVIDENCE_SUFFICIENT, choice=choice)
    assert md.permitted is False and md.capped is True  # 方法学控制面把它压低了
    d = check_honesty_constraints(
        TrustClaim(
            asset_ref="a",
            claimed_label=LABEL_EVIDENCE_SUFFICIENT,
            spine_decision=sd,
            methodology_decision=md,
        )
    )
    assert d.passed is False
    assert FAKE_STRONG_LABEL in d.violation_codes


def test_real_evidence_sufficient_double_backed_permitted():
    """正路径不误伤：spine 一致性门 + standard 档双背书的 evidence_sufficient → 放行（reuse 端到端）。"""

    sd = _promotable_evidence_sufficient_decision()
    md = constrain_promotion(MethodologyTier.STANDARD, LABEL_EVIDENCE_SUFFICIENT)
    assert md.permitted is True and md.capped is False
    d = check_honesty_constraints(
        TrustClaim(
            asset_ref="a",
            claimed_label=LABEL_EVIDENCE_SUFFICIENT,
            spine_decision=sd,
            methodology_decision=md,
        )
    )
    assert d.passed is True


def test_weak_label_has_no_strong_evidence_obligation():
    """诚实弱标签（exploratory）无强证据义务 → 放行（如实陈述·不冒充）。"""

    d = check_honesty_constraints(TrustClaim(asset_ref="a", claimed_label=LABEL_EXPLORATORY))
    assert d.passed is True


def test_fake_theory_impl_consistency_refused():
    d = check_honesty_constraints(
        TrustClaim(
            asset_ref="a",
            claims_theory_impl_consistent=True,
            consistency_failed=True,
        )
    )
    assert d.passed is False
    assert FAKE_CONSISTENCY in d.violation_codes


def test_single_person_mode_claims_org_independence_refused():
    """GOAL §13：单人模式声明组织独立 → 拒（只可展示 functional independence）。"""

    d = check_honesty_constraints(
        TrustClaim(
            asset_ref="a",
            claims_organizational_independence=True,
            single_person_mode=True,
            has_real_org_process=False,
        )
    )
    assert d.passed is False
    assert FAKE_ORG_INDEPENDENCE in d.violation_codes


def test_org_independence_with_real_process_permitted():
    """正路径：真实组织流程存在时声明组织独立 → 放行。"""

    d = check_honesty_constraints(
        TrustClaim(
            asset_ref="a",
            claims_organizational_independence=True,
            single_person_mode=False,
            has_real_org_process=True,
        )
    )
    assert d.passed is True


# ═══════════════════════ E. 用户自主 + 责任披露 ═══════════════════════
def test_agent_decides_methodology_for_user_refused():
    """GOAL §13：Agent 替 user 拍板方法学放权（actor=agent）→ 拒。"""

    mcr = MethodologyChoiceRecord(
        chosen_path="loose",
        skipped_steps=("放宽部分稳健性门（loose）",),  # 非安全·不触命门
        responsibility_boundary="...",
        actor="agent",
    )
    d = check_user_autonomy(methodology_choice=mcr)
    assert d.passed is False
    assert AGENT_DECIDED_FOR_USER in d.violation_codes


def test_agent_assumes_risk_for_user_refused():
    rdr = _complete_responsibility(actor="agent")
    d = check_user_autonomy(responsibility=rdr)
    assert d.passed is False
    assert AGENT_DECIDED_FOR_USER in d.violation_codes


def test_user_chosen_relaxation_permitted():
    """正路径：user 自己选的放宽（build 默认 actor=user）→ 自主门放行。"""

    mcr = build_methodology_choice(MethodologyTier.LOOSE)  # actor=user
    d = check_user_autonomy(methodology_choice=mcr, responsibility=_complete_responsibility("user"))
    assert d.passed is True


def test_risk_assumed_missing_responsibility_refused():
    """可证伪验收④：user 承担风险但缺 ResponsibilityDisclosureRecord → 拒。"""

    d = check_responsibility(risk_assumed=True, responsibility=None)
    assert d.passed is False
    assert MISSING_RESPONSIBILITY in d.violation_codes


def test_incomplete_responsibility_refused():
    """承担风险但责任披露不完整（空壳）→ 拒。"""

    rdr = ResponsibilityDisclosureRecord(
        asset_ref="a", user_accepted_risk=True, accepted_risks=()  # 缺 boundary/risk_owner/具体项
    )
    assert rdr.is_complete is False
    d = check_responsibility(risk_assumed=True, responsibility=rdr)
    assert d.passed is False
    assert INCOMPLETE_RESPONSIBILITY in d.violation_codes


def test_responsibility_complete_nonsafety_not_overblocked():
    """GOAL §13：user 自负其责（完整记录）后系统不阻断非红线交付 → 放行（不过度拦）。"""

    d = check_responsibility(risk_assumed=True, responsibility=_complete_responsibility("user"))
    assert d.passed is True


# ═══════════════════════ F. 记录身份 + reuse 不另造 ═══════════════════════
def test_responsibility_record_content_addressed_and_stable():
    a = _complete_responsibility("user")
    b = _complete_responsibility("user")
    assert a.disclosure_id == b.disclosure_id  # 同输入逐字节同 id
    assert a.disclosure_id.startswith("rdr_")
    c = ResponsibilityDisclosureRecord(
        asset_ref="strat-x",
        boundary="改了边界",
        risk_owner="user",
        user_accepted_risk=True,
        accepted_risks=("x",),
        actor="user",
    )
    assert c.disclosure_id != a.disclosure_id  # 改内容即变 id


def test_reuses_spine_methodology_choice_record_not_recreated():
    """复用单一源：trust 不另造 MethodologyChoiceRecord；ResponsibilityDisclosureRecord 是新增独立类。"""

    from app.lineage.spine import MethodologyChoiceRecord as SpineMCR

    # trust 引用的 MCR 必须是 spine 那一份（同一类对象·非平行复制）。
    assert tc.MethodologyChoiceRecord is SpineMCR
    assert ResponsibilityDisclosureRecord is not SpineMCR


# ═══════════════════════ G. 聚合入口 + 裁决口径自检 ═══════════════════════
def _good_context() -> TrustContext:
    mcr = build_methodology_choice(MethodologyTier.LOOSE)  # actor=user·非安全 skipped_steps
    return TrustContext(
        asset_ref="strat-x",
        methodology_choice=mcr,
        claim=TrustClaim(asset_ref="strat-x", claimed_label=LABEL_EXPLORATORY),
        conclusion=AgentConclusion(strength=tc.STRENGTH_EXPLORATORY, claims_sure_win=False),
        disclosure=DisclosureManifest(
            known_weaknesses=("loose 档稳健性证据薄",),
            shown=("loose 档稳健性证据薄",),
            waivers=("loose 放宽（user 选）",),
            shown_waivers=("loose 放宽（user 选）",),
        ),
        risk_assumed=True,
        responsibility=_complete_responsibility("user"),
    )


def test_evaluate_trust_good_path_ok():
    v = evaluate_trust(_good_context())
    assert v.ok is True
    assert v.rejections == ()
    assert v.waiver_safety.bypass_attempted is False


def test_require_trustworthy_raises_on_hidden_weakness():
    ctx = _good_context()
    bad = TrustContext(
        asset_ref=ctx.asset_ref,
        methodology_choice=ctx.methodology_choice,
        claim=ctx.claim,
        conclusion=ctx.conclusion,
        disclosure=DisclosureManifest(
            known_weaknesses=("致命弱点：未测样本外",), shown=()  # 藏了
        ),
        risk_assumed=ctx.risk_assumed,
        responsibility=ctx.responsibility,
    )
    with pytest.raises(TrustRejected) as ei:
        require_trustworthy(bad)
    assert WEAKNESS_HIDDEN in ei.value.validation.violation_codes


def test_require_trustworthy_passes_good_context():
    assert require_trustworthy(_good_context()) is not None


def test_evaluate_trust_aggregates_multiple_violations():
    """多门同时坏 → 聚合把每条都 surface（缺陷面完整·非短路）。"""

    ctx = TrustContext(
        asset_ref="a",
        claim=TrustClaim(asset_ref="a", claimed_label=LABEL_PROOF_BACKED),  # 伪造强标签
        conclusion=AgentConclusion(strength=tc.STRENGTH_STRONG, claims_sure_win=True),  # 谄媚
        disclosure=DisclosureManifest(known_weaknesses=("w",), shown=()),  # 藏弱点
        risk_assumed=True,
        responsibility=None,  # 缺责任记录
    )
    v = evaluate_trust(ctx)
    assert v.ok is False
    codes = set(v.violation_codes)
    assert {FAKE_STRONG_LABEL, tc.SYCOPHANTIC_STRONG_CONCLUSION, WEAKNESS_HIDDEN, MISSING_RESPONSIBILITY} <= codes


def test_verdict_texts_carry_no_banned_positive_terms():
    """裁决口径自检（假绿灯反噬自身）：本门 verdict_text 绝不出现越权正向断言。"""

    texts: list[str] = []
    texts.append(evaluate_waiver_safety(["把 secret 给 LLM"]).verdict_text)
    texts.append(evaluate_waiver_safety(["放宽稳健性门"]).verdict_text)
    texts.append(check_anti_sycophancy(AgentConclusion(strength=tc.STRENGTH_STRONG, claims_sure_win=True)).verdict_text)
    texts.append(check_weakness_disclosure(DisclosureManifest(known_weaknesses=("w",), shown=())).verdict_text)
    texts.append(check_honesty_constraints(TrustClaim(claimed_label=LABEL_PROOF_BACKED)).verdict_text)
    texts.append(check_responsibility(risk_assumed=True, responsibility=None).verdict_text)
    for t in texts:
        for term in tc._BANNED_POSITIVE_TERMS:
            assert term not in t, f"verdict 含越权正向断言 {term!r}: {t}"


def test_banned_positive_self_check_fires():
    """自检函数本身有效：planted 越权词必触发 AssertionError。"""

    with pytest.raises(AssertionError):
        tc._assert_no_banned_positive("本门保证结果可信")
    tc._assert_no_banned_positive("本门拒绝越权强结论，给出缺口与下一步")  # 干净文本不触发
