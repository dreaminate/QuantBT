"""C-S10-COST-GATE + C-S10-CONTROLPLANE-ENFORCE · §10 两道 check 插 SA-3 门链 · 对抗测试。

RULES §2（种坏门必抓 + 变形 + 幂等 + 措辞核对）+ §3（诚实限界 vs 残余）。

可证伪验收（codemap C-S10-COST-GATE / C-S10-CONTROLPLANE-ENFORCE）：
  COST：声 evidence_sufficient 但缺 cost_model_refs/tca_ref → ok=False；补成本 → ok=True。
  CONTROL-PLANE：放宽档（loose/exploratory/custom/user_waived）显 evidence_sufficient → 封顶 ok=False；
                 严格档（strict/standard）显 evidence_sufficient → ok=True。
门链合成（复用 SA-3/SA-2·非本卡重测）：producer 绿 → 整链 ENFORCE 拒坏 manifest（blocks）；producer
  红/缺 → advisory（flip_refused·只记录不阻断·绝不误拒诚实 run）；check 无 mode 字段 → 无法自封 enforce。
fail-closed（堵 codex 在 C-S9 找到的「非 list 族静默 skip」洞）：节非 dict / 族非 list / 项非 dict /
  record 解析炸 / tier 非法 → ok=False（不静默放行）。gameability：输入翻转 ok 跟着翻（非常量门）。

★ mutation 三态（已手验·见任务报告）：
  · COST：把 `section10_methodology_gate._collect_cost_family` 里「强标签缺成本」那条 append 注释掉
    （弱化消费策略）→ `test_cost_strong_claim_no_cost_rejected` 转 RED → 还原 → GREEN。
  · CONTROL-PLANE：把 `_collect_control_plane` 的 `capped = effective_label(...)!=claimed` 改成
    `capped = False`（弱化封顶判定）→ `test_cp_loose_evidence_sufficient_capped` 转 RED → 还原 → GREEN。
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

# 冷导入预热（既有循环·非本卡引入）：导入 app.governance.* 前先全载 orchestrator 解环
# （app.governance 包 __init__ 经 spine_invariants 触达 orchestrator）——与 test_promote_gate_chain 同款。
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
from app.release_gate.section10_methodology_gate import (  # noqa: E402
    SECTION10_CONTROLPLANE_GATE_NAME,
    SECTION10_CONTROLPLANE_MANIFEST_KEY,
    SECTION10_CONTROLPLANE_PRODUCER_KEY,
    SECTION10_COST_GATE_NAME,
    SECTION10_COST_MANIFEST_KEY,
    SECTION10_COST_PRODUCER_KEY,
    register_section10_controlplane_gate,
    register_section10_cost_gate,
    section10_controlplane_check,
    section10_cost_check,
)


# ════════════════════════════════════════════════════════════════════════════
# manifest 构造器（faithful §10 producer 契约·中心后续据此填）
# ════════════════════════════════════════════════════════════════════════════
def _cost_manifest(section: dict | None) -> dict:
    m = {"run_id": "ide_promote_s10", "status": "completed"}
    if section is not None:
        m[SECTION10_COST_MANIFEST_KEY] = section
    return m


def _cp_manifest(section: dict | None) -> dict:
    m = {"run_id": "ide_promote_s10", "status": "completed"}
    if section is not None:
        m[SECTION10_CONTROLPLANE_MANIFEST_KEY] = section
    return m


def _strong_no_cost() -> dict:
    """坏门：声 evidence_sufficient（research 环境）却缺 cost_model_refs/tca_ref。"""

    return _cost_manifest({
        "validation_methodologies": [
            {"validation_ref": "v::strong", "claim_label": "evidence_sufficient",
             "sample_size": 30, "target_environment": "research"}
        ]
    })


def _strong_with_tca() -> dict:
    return _cost_manifest({
        "validation_methodologies": [
            {"validation_ref": "v::strong", "claim_label": "evidence_sufficient",
             "sample_size": 30, "target_environment": "research", "tca_ref": "tca::abc"}
        ]
    })


def _strong_with_cost_model() -> dict:
    return _cost_manifest({
        "validation_methodologies": [
            {"validation_ref": "v::strong", "claim_label": "evidence_sufficient",
             "sample_size": 30, "target_environment": "research", "cost_model_refs": ["cm::a_share"]}
        ]
    })


def _loose_evidence_sufficient() -> dict:
    """坏门：放宽档 loose 把 verdict 显成 evidence_sufficient。"""

    return _cp_manifest({"tier_claims": [{"tier": "loose", "claimed_label": "evidence_sufficient"}]})


def _strict_evidence_sufficient() -> dict:
    return _cp_manifest({"tier_claims": [{"tier": "strict", "claimed_label": "evidence_sufficient"}]})


def _cost_green_ledger() -> ProducerStatusLedger:
    led = ProducerStatusLedger()
    led.mark_green(SECTION10_COST_PRODUCER_KEY)
    return led


def _cp_green_ledger() -> ProducerStatusLedger:
    led = ProducerStatusLedger()
    led.mark_green(SECTION10_CONTROLPLANE_PRODUCER_KEY)
    return led


def _verdict(result: ChainResult, gate_name: str):
    matches = [v for v in result.verdicts if v.gate_name == gate_name]
    assert len(matches) == 1, f"门链中应恰有一道 {gate_name} 裁定"
    return matches[0]


# ════════════════════════════════════════════════════════════════════════════
# ① COST check：falsifiable（缺成本→拒·补成本→过）+ 诚实 + canonical 复用
# ════════════════════════════════════════════════════════════════════════════
def test_cost_strong_claim_no_cost_rejected():
    """★ 可证伪①（mutation 目标）：evidence_sufficient（research）缺成本 → ok=False·消费码精确。"""

    cr = section10_cost_check(_strong_no_cost())
    assert isinstance(cr, GateCheckResult)
    assert cr.ok is False
    assert "s10_strong_claim_missing_cost_tca" in cr.missing


def test_cost_strong_claim_with_tca_passes():
    """★ 可证伪①补面：同一强标签补 tca_ref → ok=True（输入翻转 ok 跟着翻·非常量门）。"""

    cr = section10_cost_check(_strong_with_tca())
    assert cr.ok is True
    assert cr.missing == ()


def test_cost_strong_claim_with_cost_model_passes():
    """补 cost_model_refs（而非 tca_ref）同样满足成本证据 → ok=True。"""

    assert section10_cost_check(_strong_with_cost_model()).ok is True


def test_cost_input_flip_flips_ok_not_constant_gate():
    """反作弊：同一强标签 record，缺成本→ok=False / 补成本→ok=True（证明门真读字段·非 no-op）。"""

    bad = section10_cost_check(_strong_no_cost())
    good = section10_cost_check(_strong_with_tca())
    assert bad.ok is False and good.ok is True


def test_cost_weak_label_no_cost_research_passes():
    """诚实边界：非强标签（draft）research 缺成本 → ok=True（无强结论须背书·不误拒探索 run）。"""

    m = _cost_manifest({
        "validation_methodologies": [
            {"validation_ref": "v::draft", "claim_label": "draft",
             "sample_size": 5, "target_environment": "research"}
        ]
    })
    assert section10_cost_check(m).ok is True


def test_cost_runtime_env_missing_cost_uses_canonical_validator():
    """复用单一源：runtime 环境（paper）缺成本 → canonical `production_candidate_missing_cost_model`。

    这条触发条件（runtime 环境而非强标签）来自 `validate_validation_methodology`·本门未重写·只搬运。
    """

    m = _cost_manifest({
        "validation_methodologies": [
            {"validation_ref": "v::paper", "claim_label": "draft",
             "sample_size": 5, "target_environment": "paper"}  # runtime env·非强标签
        ]
    })
    cr = section10_cost_check(m)
    assert cr.ok is False
    assert "production_candidate_missing_cost_model" in cr.missing


def test_cost_canonical_code_comes_from_methodology_validation():
    """复用证明：missing 里的 canonical 码硬编码在 methodology_validation（同一源·非本模块自造）。"""

    from app.research_os import methodology_validation as mv

    m = _cost_manifest({
        "validation_methodologies": [
            {"validation_ref": "v::paper", "claim_label": "draft",
             "sample_size": 5, "target_environment": "live"}
        ]
    })
    cr = section10_cost_check(m)
    assert "production_candidate_missing_cost_model" in cr.missing
    assert "production_candidate_missing_cost_model" in Path(mv.__file__).read_text(encoding="utf-8")


def test_cost_depth_record_strong_no_cost_rejected():
    """消费策略亦作用于 ValidationDepthRecord（复用既有 from_dict）：强标签 depth 缺成本 → ok=False。"""

    m = _cost_manifest({
        "validation_depths": [
            {"depth_ref": "d::strong", "claim_ref": "c::1", "claim_label": "evidence_sufficient",
             "target_environment": "research", "evidence_refs": ["e::1"], "validation_result_refs": ["r::1"]}
        ]
    })
    cr = section10_cost_check(m)
    assert cr.ok is False
    assert "s10_strong_claim_missing_cost_tca" in cr.missing


# ════════════════════════════════════════════════════════════════════════════
# ② COST fail-closed（堵 fail-open·违例绝不溜成 ok=True）
# ════════════════════════════════════════════════════════════════════════════
def test_cost_absent_section_is_ok_documented_limit():
    """诚实限界：未声明 section10_cost → ok=True（无可证伪违例·非『整本已查清』）。"""

    cr = section10_cost_check(_cost_manifest(None))
    assert cr.ok is True
    assert cr.missing == ()
    assert "无可证伪" in cr.reason


def test_cost_malformed_section_failcloses():
    """fail-closed：成本节存在但非 dict（被填成 list）→ ok=False。"""

    m = {"run_id": "r", SECTION10_COST_MANIFEST_KEY: ["not", "a", "dict"]}
    cr = section10_cost_check(m)
    assert cr.ok is False
    assert "section10_cost_malformed" in cr.missing


def test_cost_family_as_mapping_does_not_failopen():
    """★ codex 洞同款：把 validation_methodologies 填成 {id: rec} 映射藏一个强标签缺成本 record。

    旧式静默 skip 非 list → ok=True（违例溜走）。现 fail-closed：记 malformed·ok=False。
    """

    m = _cost_manifest({
        "validation_methodologies": {
            "v::hidden": {"validation_ref": "v::hidden", "claim_label": "evidence_sufficient",
                          "sample_size": 30, "target_environment": "research"}
        }
    })
    cr = section10_cost_check(m)
    assert cr.ok is False
    assert "section10_cost_validation_methodology_malformed" in cr.missing


def test_cost_family_list_with_nondict_item_failcloses():
    """坏门变形：族是 list 但含非 dict 项 → fail-closed malformed（不静默 skip）。"""

    cr = section10_cost_check(_cost_manifest({"validation_methodologies": ["not-a-dict"]}))
    assert cr.ok is False
    assert "section10_cost_validation_methodology_malformed" in cr.missing


def test_cost_unparseable_record_failcloses():
    """坏门变形：record 字段非法（sample_size 非数值）→ adapter 抛 → fail-closed unparseable（不放行）。"""

    cr = section10_cost_check(_cost_manifest({"validation_methodologies": [{"sample_size": "abc"}]}))
    assert cr.ok is False
    assert "section10_cost_validation_methodology_unparseable" in cr.missing


def test_cost_blank_cost_ref_does_not_failopen():
    """★ codex 洞：cost_model_refs=[""] 空白占位 ref 不算成本证据 → 强标签仍 ok=False（防伪造有成本）。"""

    m = _cost_manifest({
        "validation_methodologies": [
            {"validation_ref": "v::blank", "claim_label": "evidence_sufficient",
             "sample_size": 30, "target_environment": "research", "cost_model_refs": [""]}
        ]
    })
    cr = section10_cost_check(m)
    assert cr.ok is False
    assert "s10_strong_claim_missing_cost_tca" in cr.missing


def test_cost_whitespace_label_does_not_failopen():
    """★ codex 洞：claim_label='evidence_sufficient '（加空白）仍按强标签判 → 缺成本 ok=False（防去空白躲门）。"""

    m = _cost_manifest({
        "validation_methodologies": [
            {"validation_ref": "v::ws", "claim_label": "evidence_sufficient ",
             "sample_size": 30, "target_environment": "research"}
        ]
    })
    cr = section10_cost_check(m)
    assert cr.ok is False
    assert "s10_strong_claim_missing_cost_tca" in cr.missing


def test_cost_nonmapping_manifest_failcloses_not_open():
    """fail-closed：manifest 非 Mapping（如 list）→ check **抛**（不静默 ok=True）；门链据此 errored 阻断。"""

    with pytest.raises(Exception):
        section10_cost_check(["not", "a", "mapping"])  # type: ignore[arg-type]

    chain = PromoteGateChain()
    register_section10_cost_gate(chain)
    result = chain.evaluate(["not", "a", "mapping"], producer_status=_cost_green_ledger())  # type: ignore[arg-type]
    v = _verdict(result, SECTION10_COST_GATE_NAME)
    assert v.ok is False and v.errored is True and v.blocks is True


# ════════════════════════════════════════════════════════════════════════════
# ③ CONTROL-PLANE check：falsifiable（放宽档显强→封顶·严格档→过）+ 诚实 + tier 复用
# ════════════════════════════════════════════════════════════════════════════
def test_cp_loose_evidence_sufficient_capped():
    """★ 可证伪②（mutation 目标）：loose 档显 evidence_sufficient → ok=False·封顶码精确。"""

    cr = section10_controlplane_check(_loose_evidence_sufficient())
    assert isinstance(cr, GateCheckResult)
    assert cr.ok is False
    assert "s10_relaxed_tier_strong_verdict_capped" in cr.missing
    # 措辞核对（RULES §2）：reason 须暴露降级目标 exploratory（loose 的诚实上限）。
    assert "exploratory" in cr.reason


def test_cp_strict_evidence_sufficient_passes():
    """★ 可证伪②补面：strict 档显 evidence_sufficient → ok=True（严格档不被封顶·交下游证据门）。"""

    cr = section10_controlplane_check(_strict_evidence_sufficient())
    assert cr.ok is True
    assert cr.missing == ()


def test_cp_standard_evidence_sufficient_passes():
    """standard（rigorous 组）显 evidence_sufficient → ok=True（同 strict·不封顶）。"""

    assert section10_controlplane_check(
        _cp_manifest({"tier_claims": [{"tier": "standard", "claimed_label": "evidence_sufficient"}]})
    ).ok is True


def test_cp_input_flip_flips_ok_not_constant_gate():
    """反作弊：同 loose 档，label evidence_sufficient→exploratory，ok False→True（非常量门）。"""

    bad = section10_controlplane_check(_loose_evidence_sufficient())
    good = section10_controlplane_check(
        _cp_manifest({"tier_claims": [{"tier": "loose", "claimed_label": "exploratory"}]})
    )
    assert bad.ok is False and good.ok is True


@pytest.mark.parametrize("tier", ["loose", "exploratory", "custom", "user_waived"])
def test_cp_all_relaxed_tiers_capped(tier):
    """全部四个放宽档显 evidence_sufficient → 一律封顶 ok=False（复用 control_plane.RELAXED_TIERS）。"""

    cr = section10_controlplane_check(
        _cp_manifest({"tier_claims": [{"tier": tier, "claimed_label": "evidence_sufficient"}]})
    )
    assert cr.ok is False
    assert "s10_relaxed_tier_strong_verdict_capped" in cr.missing


def test_cp_loose_honest_label_passes_no_false_reject():
    """诚实边界：loose 档显 exploratory（诚实上限内）→ ok=True（绝不误拒诚实放宽 run）。"""

    assert section10_controlplane_check(
        _cp_manifest({"tier_claims": [{"tier": "loose", "claimed_label": "exploratory"}]})
    ).ok is True


def test_cp_methodology_choice_path_reuses_tier_of():
    """复用 tier_of：用 methodology_choice.chosen_path 而非 tier 字段定档 → loose 仍被封顶。"""

    cr = section10_controlplane_check(
        _cp_manifest({"tier_claims": [
            {"methodology_choice": {"chosen_path": "loose"}, "claimed_label": "proof_backed"}
        ]})
    )
    assert cr.ok is False
    assert "s10_relaxed_tier_strong_verdict_capped" in cr.missing


def test_cp_capped_uses_control_plane_effective_label():
    """复用证明：封顶判定 = control_plane.effective_label（同一源·loose+强标签→降级·非强→原样）。"""

    from app.methodology.control_plane import MethodologyTier, effective_label

    assert effective_label(MethodologyTier.LOOSE, "evidence_sufficient") != "evidence_sufficient"
    assert effective_label(MethodologyTier.LOOSE, "exploratory") == "exploratory"
    assert effective_label(MethodologyTier.STRICT, "evidence_sufficient") == "evidence_sufficient"


# ════════════════════════════════════════════════════════════════════════════
# ④ CONTROL-PLANE fail-closed（堵 dodge：省略/伪造档位躲封顶）
# ════════════════════════════════════════════════════════════════════════════
def test_cp_absent_section_is_ok_documented_limit():
    """诚实限界：未声明 section10_control_plane → ok=True（无可证伪违例）。"""

    cr = section10_controlplane_check(_cp_manifest(None))
    assert cr.ok is True
    assert "无可证伪" in cr.reason


def test_cp_garbage_tier_failcloses():
    """fail-closed：tier 是非法档名 → ok=False（格式非法·不静默放行）。"""

    cr = section10_controlplane_check(
        _cp_manifest({"tier_claims": [{"tier": "bogus_tier", "claimed_label": "evidence_sufficient"}]})
    )
    assert cr.ok is False
    assert "s10_control_plane_tier_malformed" in cr.missing


def test_cp_strong_claim_without_tier_failcloses_dodge():
    """★ dodge 堵口：声 evidence_sufficient 却**漏档位** → ok=False（不许省档位躲封顶）。"""

    cr = section10_controlplane_check(
        _cp_manifest({"tier_claims": [{"claimed_label": "evidence_sufficient"}]})
    )
    assert cr.ok is False
    assert "s10_control_plane_tier_unresolved" in cr.missing


def test_cp_weak_claim_without_tier_passes_no_false_reject():
    """诚实边界：非强标签 + 漏档位 → ok=True（无强 verdict 可封·不误拒）。"""

    assert section10_controlplane_check(
        _cp_manifest({"tier_claims": [{"claimed_label": "draft"}]})
    ).ok is True


def test_cp_malformed_section_failcloses():
    """fail-closed：控制面节非 dict（list）→ ok=False。"""

    m = {"run_id": "r", SECTION10_CONTROLPLANE_MANIFEST_KEY: ["x"]}
    cr = section10_controlplane_check(m)
    assert cr.ok is False
    assert "section10_control_plane_malformed" in cr.missing


def test_cp_claims_nonlist_failcloses():
    """fail-closed：tier_claims 非 list（被填成映射）→ ok=False。"""

    cr = section10_controlplane_check(_cp_manifest({"tier_claims": {"a": 1}}))
    assert cr.ok is False
    assert "section10_control_plane_malformed" in cr.missing


def test_cp_claims_item_nondict_failcloses():
    """fail-closed：tier_claims 含非 dict 项 → ok=False（不静默 skip）。"""

    cr = section10_controlplane_check(_cp_manifest({"tier_claims": ["not-a-dict"]}))
    assert cr.ok is False
    assert "s10_control_plane_malformed" in cr.missing


def test_cp_whitespace_label_does_not_failopen():
    """★ codex 洞：claimed_label='evidence_sufficient '（加空白）仍被 loose 档封顶 → ok=False（防去空白躲封顶）。"""

    cr = section10_controlplane_check(
        _cp_manifest({"tier_claims": [{"tier": "loose", "claimed_label": "evidence_sufficient "}]})
    )
    assert cr.ok is False
    assert "s10_relaxed_tier_strong_verdict_capped" in cr.missing


def test_cp_nonmapping_manifest_failcloses_not_open():
    """fail-closed：manifest 非 Mapping → check 抛；门链 errored 阻断。"""

    with pytest.raises(Exception):
        section10_controlplane_check(("not", "mapping"))  # type: ignore[arg-type]

    chain = PromoteGateChain()
    register_section10_controlplane_gate(chain)
    result = chain.evaluate(("not", "mapping"), producer_status=_cp_green_ledger())  # type: ignore[arg-type]
    v = _verdict(result, SECTION10_CONTROLPLANE_GATE_NAME)
    assert v.ok is False and v.errored is True and v.blocks is True


# ════════════════════════════════════════════════════════════════════════════
# ⑤ 门链合成：注册 + producer 绿/红 → enforce/advisory（复用 SA-3/SA-2·非本卡重测）
# ════════════════════════════════════════════════════════════════════════════
def test_cost_green_producer_enforces_and_rejects():
    """★ COST：producer 绿 + 缺成本强结论 → 整链 ENFORCE 拒晋级（blocks·ok=False）。"""

    chain = PromoteGateChain()
    register_section10_cost_gate(chain)
    result = chain.evaluate(_strong_no_cost(), producer_status=_cost_green_ledger())
    assert result.rejected is True
    v = _verdict(result, SECTION10_COST_GATE_NAME)
    assert v.advisory_or_enforce == MODE_ENFORCE
    assert v.blocks is True and v.ok is False
    assert v.producer_key == SECTION10_COST_PRODUCER_KEY
    assert "s10_strong_claim_missing_cost_tca" in v.missing


def test_cost_red_producer_advisory_only_not_blocking():
    """★ COST：producer 红/缺 → advisory（坏 manifest 被记录但不阻断·flip_refused·绝不误拒）。"""

    chain = PromoteGateChain()
    register_section10_cost_gate(chain)
    result = chain.evaluate(_strong_no_cost(), producer_status=ProducerStatusLedger())
    assert result.rejected is False
    v = _verdict(result, SECTION10_COST_GATE_NAME)
    assert v.advisory_or_enforce == MODE_ADVISORY
    assert v.flip_refused is True
    assert v.ok is False and v.blocks is False
    assert v in result.advisories


def test_cost_green_producer_clean_manifest_passes():
    """COST：绿 producer + 补成本 clean → 不拒（enforce 不误伤诚实 run）。"""

    chain = PromoteGateChain()
    register_section10_cost_gate(chain)
    result = chain.evaluate(_strong_with_tca(), producer_status=_cost_green_ledger())
    assert result.rejected is False
    v = _verdict(result, SECTION10_COST_GATE_NAME)
    assert v.advisory_or_enforce == MODE_ENFORCE and v.ok is True


def test_cp_green_producer_enforces_and_rejects():
    """★ CONTROL-PLANE：producer 绿 + loose 显强标签 → 整链 ENFORCE 拒晋级（blocks）。"""

    chain = PromoteGateChain()
    register_section10_controlplane_gate(chain)
    result = chain.evaluate(_loose_evidence_sufficient(), producer_status=_cp_green_ledger())
    assert result.rejected is True
    v = _verdict(result, SECTION10_CONTROLPLANE_GATE_NAME)
    assert v.advisory_or_enforce == MODE_ENFORCE
    assert v.blocks is True and v.ok is False
    assert "s10_relaxed_tier_strong_verdict_capped" in v.missing


def test_cp_red_producer_advisory_only_not_blocking():
    """★ CONTROL-PLANE：producer 红/缺 → advisory（记录不阻断·flip_refused）。"""

    chain = PromoteGateChain()
    register_section10_controlplane_gate(chain)
    result = chain.evaluate(_loose_evidence_sufficient(), producer_status=ProducerStatusLedger())
    assert result.rejected is False
    v = _verdict(result, SECTION10_CONTROLPLANE_GATE_NAME)
    assert v.advisory_or_enforce == MODE_ADVISORY
    assert v.flip_refused is True
    assert v.ok is False and v.blocks is False


def test_cp_green_producer_strict_passes():
    """CONTROL-PLANE：绿 producer + strict 显强标签 → 不拒（严格档不被封顶·enforce 不误伤）。"""

    chain = PromoteGateChain()
    register_section10_controlplane_gate(chain)
    result = chain.evaluate(_strict_evidence_sufficient(), producer_status=_cp_green_ledger())
    assert result.rejected is False
    v = _verdict(result, SECTION10_CONTROLPLANE_GATE_NAME)
    assert v.advisory_or_enforce == MODE_ENFORCE and v.ok is True


def test_checks_carry_no_mode_field_gaming_proof():
    """gaming-proof：两道 check 输出皆无 mode 字段 → 无法自封 enforce；mode 仅随 producer 绿灯翻。"""

    for cr in (section10_cost_check(_strong_no_cost()),
               section10_controlplane_check(_loose_evidence_sufficient())):
        assert not hasattr(cr, "advisory_or_enforce") and not hasattr(cr, "mode")


def test_both_gates_coexist_in_one_chain_with_documented_keys():
    """注册契约：两门同链共存（无重名）·各自 producer key 为文档常量·绿即翻 enforce·不张冠李戴。"""

    chain = PromoteGateChain()
    register_section10_cost_gate(chain)
    register_section10_controlplane_gate(chain)
    assert SECTION10_COST_GATE_NAME in chain.gate_names
    assert SECTION10_CONTROLPLANE_GATE_NAME in chain.gate_names

    # 只把 cost producer 标绿 → cost 门 enforce·controlplane 门仍 advisory（精确绑定·不串）。
    led = ProducerStatusLedger()
    led.mark_green(SECTION10_COST_PRODUCER_KEY)
    result = chain.evaluate(_cost_manifest(None), producer_status=led)
    cost_v = _verdict(result, SECTION10_COST_GATE_NAME)
    cp_v = _verdict(result, SECTION10_CONTROLPLANE_GATE_NAME)
    assert cost_v.advisory_or_enforce == MODE_ENFORCE
    assert cost_v.producer_key == SECTION10_COST_PRODUCER_KEY
    assert cp_v.advisory_or_enforce == MODE_ADVISORY and cp_v.flip_refused is True


# ════════════════════════════════════════════════════════════════════════════
# ⑥ 冷导入安全（SA-3 纪律·镜像 section9 / chain 模块）
# ════════════════════════════════════════════════════════════════════════════
def test_module_cold_importable():
    """冷导入：全新解释器 import 本模块**不**撞 app.governance 既有冷导入循环。

    顶层只依赖 promote_gate_chain（cold-safe）+ methodology_validation + control_plane + spine
    （皆只触 lineage.ids·cold-safe）。
    """

    backend_root = Path(__file__).resolve().parents[1]  # app/backend
    code = (
        "import app.release_gate.section10_methodology_gate as m; "
        "assert m.section10_cost_check and m.section10_controlplane_check; "
        "assert m.register_section10_cost_gate and m.register_section10_controlplane_gate"
    )
    proc = subprocess.run(
        [sys.executable, "-c", code],
        cwd=str(backend_root),
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert proc.returncode == 0, (
        f"§10 方法学门模块应冷导入成功:\nSTDOUT={proc.stdout}\nSTDERR={proc.stderr}"
    )
