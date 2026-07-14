"""方法学控制面 6 档的【对抗式】测试（GOAL §10 方法学与验证 · 系统提供 user 运行时选）。

验收标准（RULES §2）：不是「测函数跑通」，而是「种一个已知的坏门，控制面必须抓住，
否则门是纸做的」。GOAL §10 四条可证伪门逐条种坏：
  ① user 选 loose/exploratory（放宽档）后系统仍显 evidence_sufficient/proof_backed/
     production_ready → 必拒（MUT 放过→红·命门）。
  ② 方法学松紧未记录 tradeoffs/recommendation/responsibility_boundary → 必拒。
  ③ user_waived 档资产进 proof_backed/evidence_sufficient → 必拒（§1 一致）。
  ④ 6 档齐 + 各档元数据齐 → 正常（系统提供 user 选·正路径不误伤）。
外加：复用 spine 不另造（身份单一源）、与 spine_gate 互补（spine 单门挡不住 evidence_sufficient
放权）、裁决口径不越权（假绿灯反噬自身）、build/记录留痕、effective_label 幂等。
"""

from __future__ import annotations

import pytest

import app.methodology.control_plane as cp
from app.lineage import content_hash, evaluate_promotion
from app.lineage.spine import (
    CHECK_PASS,
    LABEL_CUSTOM_METHODOLOGY,
    LABEL_DRAFT,
    LABEL_EVIDENCE_SUFFICIENT,
    LABEL_EXPLORATORY,
    LABEL_PRODUCTION_READY,
    LABEL_PROOF_BACKED,
    LABEL_USER_WAIVED_VALIDATION,
    PROOF_BACKED,
    PROOF_REQUIRING_LABELS,
    STRONG_LABELS,
    ConsistencyCheck,
    MathematicalArtifact,
    MethodologyChoiceRecord,
    TheoryImplementationBinding,
)
from app.methodology.control_plane import (
    ALL_TIER_VALUES,
    RELAXED_TIERS,
    RIGOROUS_TIERS,
    TIER_PROFILES,
    MethodologyTier,
    assert_label_honest_for_export,
    build_methodology_choice,
    constrain_promotion,
    documentation_gaps,
    effective_label,
    production_eligible,
    runtime_environment_ceiling,
    tier_of,
    validate_profiles,
)

STRONG = (LABEL_EVIDENCE_SUFFICIENT, LABEL_PROOF_BACKED, LABEL_PRODUCTION_READY)


def _documented(tier: MethodologyTier) -> MethodologyChoiceRecord:
    """一条完整留痕的档位选择（过门②）。"""

    return build_methodology_choice(tier, asset_ref="factor/x", actor="user")


# ── 门①（命门）：放宽档后系统仍显强标签 → 必拒 ───────────────────────────────────
@pytest.mark.parametrize("tier", sorted(RELAXED_TIERS, key=lambda t: t.value))
@pytest.mark.parametrize("strong", STRONG)
def test_relaxed_tier_cannot_claim_strong_label(tier, strong):
    """种坏：放宽档请求强标签。门必拒、降级到诚实标签、绝不冒充。"""

    d = constrain_promotion(tier, strong, choice=_documented(tier))
    assert d.permitted is False, d.verdict_text
    assert d.capped is True
    assert d.granted_label not in STRONG_LABELS, d.granted_label
    assert any("强标签" in v and tier.value in v for v in d.violations), d.violations


@pytest.mark.parametrize("tier", sorted(RELAXED_TIERS, key=lambda t: t.value))
@pytest.mark.parametrize("strong", STRONG)
def test_effective_label_caps_strong_for_relaxed(tier, strong):
    """下游证据门哪怕拟授强标签，effective_label 也把放宽档压回诚实标签（展示/导出真实状态）。"""

    eff = effective_label(tier, strong)
    assert eff not in STRONG_LABELS
    assert eff == TIER_PROFILES[tier].honest_downgrade_label


def test_loose_and_exploratory_named_in_goal_are_capped():
    """GOAL §10 点名 loose/exploratory：二者强标签请求逐一被拒（命门具名守）。"""

    for tier in (MethodologyTier.LOOSE, MethodologyTier.EXPLORATORY):
        for strong in STRONG:
            d = constrain_promotion(tier, strong, choice=_documented(tier))
            assert d.permitted is False and d.granted_label not in STRONG_LABELS


# ── 门②：放宽未留 tradeoffs/recommendation/responsibility_boundary → 必拒 ──────────
def test_relaxation_without_record_rejected():
    """种坏：放宽却没给任何 MethodologyChoiceRecord。门必拒。"""

    d = constrain_promotion(MethodologyTier.LOOSE, LABEL_DRAFT, choice=None)
    assert d.permitted is False
    assert any("未记录" in v for v in d.violations)


@pytest.mark.parametrize(
    "kill",
    [
        {"responsibility_boundary": ""},
        {"recommendation": ""},
        {"tradeoffs_shown": ()},
    ],
)
def test_relaxation_with_incomplete_record_rejected(kill):
    """种坏：放宽档记录缺三要素之一（responsibility/recommendation/tradeoffs）。门必拒。"""

    base = dict(
        chosen_path=MethodologyTier.LOOSE.value,
        asset_ref="factor/x",
        recommendation="升 standard 复跑",
        tradeoffs_shown=("代价：稳健性证据变薄",),
        responsibility_boundary="用户自担",
        skipped_steps=("loose",),
    )
    base.update(kill)
    bad = MethodologyChoiceRecord(**base)
    d = constrain_promotion(MethodologyTier.LOOSE, LABEL_DRAFT, choice=bad)
    assert d.permitted is False
    assert any("未记录" in v for v in d.violations), d.violations


def test_documentation_gaps_flags_each_missing_field():
    full = _documented(MethodologyTier.CUSTOM)
    assert documentation_gaps(full) == ()
    assert documentation_gaps(None) == ("MethodologyChoiceRecord(缺失)",)
    miss = MethodologyChoiceRecord(chosen_path="loose", skipped_steps=("loose",))
    gaps = documentation_gaps(miss)
    assert set(gaps) == {"tradeoffs", "recommendation", "responsibility_boundary"}


def test_documented_relaxation_still_capped_on_strong_but_passes_doc_gate():
    """留痕齐全的放宽档：门②过，但门①仍把强标签拦下（两门独立、都得守）。"""

    d = constrain_promotion(MethodologyTier.LOOSE, LABEL_PROOF_BACKED, choice=_documented(MethodologyTier.LOOSE))
    assert d.permitted is False
    assert not any("未记录" in v for v in d.violations)       # 门②过
    assert any("强标签" in v for v in d.violations)            # 门①拦


# ── 门③：user_waived 档资产进 proof_backed/evidence_sufficient → 必拒 ──────────────
@pytest.mark.parametrize("strong", [LABEL_PROOF_BACKED, LABEL_EVIDENCE_SUFFICIENT])
def test_user_waived_cannot_enter_proof_or_evidence(strong):
    d = constrain_promotion(MethodologyTier.USER_WAIVED, strong, choice=_documented(MethodologyTier.USER_WAIVED))
    assert d.permitted is False
    assert d.granted_label == LABEL_USER_WAIVED_VALIDATION  # 诚实降级、不冒充


@pytest.mark.parametrize("tier", sorted(RELAXED_TIERS, key=lambda t: t.value))
@pytest.mark.parametrize("strong", STRONG)
def test_export_guard_blocks_strong_label_on_relaxed_asset(tier, strong):
    """导出守门：放宽档资产携带强标签 → raise（绝不导出为强证据）。"""

    with pytest.raises(ValueError, match="导出守门"):
        assert_label_honest_for_export(tier, strong)


# ── 门④：6 档齐 + 元数据齐 → 正常（正路径不误伤）──────────────────────────────────
def test_six_tiers_match_goal_names():
    assert set(ALL_TIER_VALUES) == {
        "strict",
        "standard",
        "loose",
        "exploratory",
        "custom",
        "user_waived",
    }
    assert len(MethodologyTier) == 6


def test_validate_profiles_passes():
    """6 档元数据齐 + 档位↔标签上限结构一致 → 不 raise（门不是误伤摆设）。"""

    validate_profiles()  # 不抛即过


@pytest.mark.parametrize("tier", sorted(RIGOROUS_TIERS, key=lambda t: t.value))
@pytest.mark.parametrize("strong", STRONG)
def test_rigorous_tier_permitted_but_not_granted(tier, strong):
    """正路径不误伤：strict/standard 请求强标签 → 档位层许可、非授予（下游证据门仍裁）。"""

    d = constrain_promotion(tier, strong)
    assert d.permitted is True
    assert d.capped is False
    assert d.granted_label == strong
    assert any("非授予" in n or "下游证据门" in n for n in d.notes), d.notes


@pytest.mark.parametrize("tier", list(MethodologyTier))
def test_honest_label_always_permitted(tier):
    """任何档请求诚实标签（draft/exploratory）→ 放行、不误伤。"""

    for honest in (LABEL_DRAFT, LABEL_EXPLORATORY):
        d = constrain_promotion(tier, honest, choice=_documented(tier))
        assert d.permitted is True
        assert d.granted_label == honest


def test_production_eligibility_split():
    for t in RIGOROUS_TIERS:
        assert production_eligible(t) is True
    for t in RELAXED_TIERS:
        assert production_eligible(t) is False
        # 放宽档运行环境上限非空，且绝不复用 rigorous 档的「受控生产」串（限制运行环境）
        env = runtime_environment_ceiling(t)
        assert env.strip()
        assert "受控生产" not in env, env


# ── 复用单一源：绝不另造 MethodologyChoiceRecord（RULES §1 / 卡红线）───────────────
def test_reuses_lineage_record_not_another():
    """控制面用的 MethodologyChoiceRecord 必须就是 lineage.spine 那一个类（复用不另造）。"""

    import app.lineage.spine as spine

    assert cp.MethodologyChoiceRecord is spine.MethodologyChoiceRecord


def test_build_choice_is_documented_and_lossless():
    for tier in MethodologyTier:
        rec = build_methodology_choice(tier, asset_ref="a", run_ref="r", actor="user")
        assert documentation_gaps(rec) == ()                 # 自带留痕（过门②）
        assert rec.chosen_path == tier.value                 # 无损保留档名
        assert set(rec.available_options) == set(ALL_TIER_VALUES)
        assert tier_of(rec) is tier                           # 可反推回原档
        # 放宽档 → is_waiver True（喂进 spine_gate 也会就 proof_backed 触发 proof-honest）
        assert rec.is_waiver is (tier in RELAXED_TIERS)


def test_choice_id_is_content_addressed_deterministic():
    a = build_methodology_choice(MethodologyTier.LOOSE, asset_ref="x", actor="user")
    b = build_methodology_choice(MethodologyTier.LOOSE, asset_ref="x", actor="user")
    assert a.choice_id == b.choice_id and a.choice_id  # 同输入同 id、非空


# ── 与 spine_gate 互证（不替换）：两层都拒 waiver 冒充 evidence_sufficient ───────────
def test_spine_and_controlplane_both_reject_evidence_sufficient_under_waiver():
    """evidence_sufficient 虽不属于旧 proof-only 集合，仍是强标签。

    canonical spine 的 strong-label-honest 门与方法学控制面必须分别拒绝 user waiver
    冒充强证据；两层互证，任一层被绕过都不能形成假绿。
    """

    # 结构事实：它不是 proof-only 标签，但仍受统一强标签诚实门约束。
    assert LABEL_EVIDENCE_SUFFICIENT in STRONG_LABELS
    assert LABEL_EVIDENCE_SUFFICIENT not in PROOF_REQUIRING_LABELS

    code_src = "def f(p, k):\n    return (p[-1] - p[-1 - k]) / p[-1 - k]\n"
    art = MathematicalArtifact(
        artifact_type="factor_formula",
        statement="mom=(p_t-p_{t-k})/p_{t-k}",
        definition="过去 k 日收益率",
        derivation="价格序列差分",
        proof_status=PROOF_BACKED,
    )
    binding = TheoryImplementationBinding.bind_source(
        theory_ref=art.artifact_id,
        code_ref="f.py:f",
        code_source=code_src,
        config_ref="cfg_v1_x",
        data_contract_ref="contract/x",
        test_refs=("t::ok",),
    )
    check = ConsistencyCheck(
        binding_id=binding.binding_id,
        check_type="numerical",
        result=CHECK_PASS,
        expected_property="0.05",
        observed_property="0.05",
    )
    waiver = build_methodology_choice(MethodologyTier.USER_WAIVED, asset_ref=art.artifact_id)

    # canonical spine 先拒，并诚实降级。
    spine_dec = evaluate_promotion(
        art, binding, [check],
        requested_label=LABEL_EVIDENCE_SUFFICIENT,
        current_code_hash=content_hash(code_src),
        choice=waiver,
    )
    assert spine_dec.promotable is False
    assert spine_dec.granted_label not in STRONG_LABELS
    assert any("strong-label-honest" in violation for violation in spine_dec.violations)

    # 控制面独立地执行同一责任边界，不能依赖 spine 已经拒绝。
    assert effective_label(MethodologyTier.USER_WAIVED, spine_dec.granted_label) not in STRONG_LABELS
    cp_dec = constrain_promotion(MethodologyTier.USER_WAIVED, LABEL_EVIDENCE_SUFFICIENT, choice=waiver)
    assert cp_dec.permitted is False


def test_spine_gate_rejects_proof_backed_with_controlplane_waiver():
    """互证：放宽档记录喂进 spine_gate，其 proof-honest 也就 proof_backed 触发（is_waiver 桥通）。"""

    code_src = "def f(p):\n    return p\n"
    art = MathematicalArtifact(
        artifact_type="factor_formula", statement="s", definition="d",
        derivation="x", proof_status=PROOF_BACKED,
    )
    binding = TheoryImplementationBinding.bind_source(
        theory_ref=art.artifact_id, code_ref="f.py:f", code_source=code_src,
        config_ref="cfg_v1_x", data_contract_ref="contract/x", test_refs=("t::ok",),
    )
    check = ConsistencyCheck(binding_id=binding.binding_id, check_type="numerical",
                             result=CHECK_PASS, expected_property="1", observed_property="1")
    waiver = build_methodology_choice(MethodologyTier.LOOSE, asset_ref=art.artifact_id)
    dec = evaluate_promotion(art, binding, [check], requested_label=LABEL_PROOF_BACKED,
                             current_code_hash=content_hash(code_src), choice=waiver)
    assert dec.promotable is False
    assert any("proof-honest" in v for v in dec.violations)


# ── 诚实纪律：裁决口径不越权（假绿灯反噬自身）────────────────────────────────────
def test_no_banned_positive_terms_in_any_verdict():
    """全档 × 全标签扫一遍裁决文，绝不出现越权正向断言（含放行/拒绝两路）。"""

    labels = list(STRONG) + [LABEL_DRAFT, LABEL_EXPLORATORY, LABEL_CUSTOM_METHODOLOGY]
    for tier in MethodologyTier:
        ch = _documented(tier)
        for lab in labels:
            d = constrain_promotion(tier, lab, choice=ch)
            for term in cp._BANNED_VERDICT_TERMS:
                assert term not in d.verdict_text, (tier.value, lab, term, d.verdict_text)
            assert d.disclosure  # 每条裁定都带诚实免责口径


def test_effective_label_idempotent():
    for tier in MethodologyTier:
        for lab in list(STRONG) + [LABEL_DRAFT]:
            once = effective_label(tier, lab)
            assert effective_label(tier, once) == once


def test_tier_of_maps_spine_waiver_labels_back():
    """tier_of 容忍 chosen_path 是 spine 放权标签（如既有测试 chosen_path=user_waived_validation）。"""

    rec = MethodologyChoiceRecord(chosen_path=LABEL_USER_WAIVED_VALIDATION, skipped_steps=("x",))
    assert tier_of(rec) is MethodologyTier.USER_WAIVED
    assert tier_of(MethodologyChoiceRecord(chosen_path="custom_methodology")) is MethodologyTier.CUSTOM
    assert tier_of(MethodologyChoiceRecord(chosen_path="??unknown")) is None
