"""C-S13-RELEASE-ENFORCE · §13 信任发版 check 插 SA-3 门链 · 对抗测试（RULES §2 种坏门必抓 + §3 诚实）。

可证伪验收（construction-map C-S13-RELEASE-ENFORCE·5 道发版门全经 trust_layer 单一源判定）：
  · 谄媚强结论（wishful → 强标签）→ check ok=False（wishful_pressure_strong_conclusion）
  · 弱点默认隐藏 → ok=False（weakness_hidden_by_default）
  · 冷启动 N≤1 冒充统计证据撑强标签 → ok=False（cold_start_packaged_as_statistical_evidence）
  · mock 静默兜底（发版 check）→ ok=False（trust_release_check_silent_mock_fallback）
  · clean 可信 manifest → ok=True
门链合成（复用 SA-3/SA-2·非本卡重测）：
  · 注册 + producer 绿 → 整链 ENFORCE 拒坏 manifest（blocks）
  · 注册 + producer 红/缺 → advisory：只记录不阻断（flip_refused·绝不误拒）
  · check 无 mode 字段 → 无法自封 enforce：mode 仅由 producer 绿灯翻（gaming-proof）
gameability：输入翻转 ok 跟着翻（非常量门）；复用 = 违例码精确来自 trust_layer canonical validator。

★ mutation 三态（已手验·见任务报告）：把 section13_trust_gate._FAMILIES 里
  `("trust_claims", "claims", trust_claim_record_from_dict, "trust_claim")` 这一行注释掉
  （弱化 check 使 trust_claims 不再被收集进 validate_trust_layer）→
  `test_sycophantic_strong_claim_flagged` / `test_hidden_weakness_flagged` /
  `test_cold_start_packaged_as_evidence_flagged` 转 RED → 还原 → GREEN。
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

# 冷导入预热（既有循环·非本卡引入）：导入 app.governance.* 前先全载 orchestrator 解环——与
# test_promote_gate_chain.py 同款顺序（app.governance 包 __init__ 经 spine_invariants 触达 orchestrator）。
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
from app.release_gate.section13_trust_gate import (  # noqa: E402
    SECTION13_TRUST_GATE_NAME,
    SECTION13_TRUST_MANIFEST_KEY,
    SECTION13_TRUST_PRODUCER_KEY,
    register_section13_trust_gate,
    section13_trust_check,
)


# ════════════════════════════════════════════════════════════════════════════
# manifest 构造器（faithful §13 producer 契约·中心后续据此填）
# ════════════════════════════════════════════════════════════════════════════
def _manifest(section: dict | None) -> dict:
    m = {"run_id": "ide_promote_test", "status": "completed"}
    if section is not None:
        m[SECTION13_TRUST_MANIFEST_KEY] = section
    return m


def _sycophantic_manifest() -> dict:
    """坏门：用户 wishful 施压 + agent 把它转成强标签结论（反谄媚门）。

    给了 evidence_refs + 弱点可见 + 无冷启动 → 隔离出 wishful_pressure_strong_conclusion 这一条。
    """

    return _manifest({
        "trust_claims": [
            {
                "claim_ref": "c::syco",
                "claim_label": "evidence_sufficient",
                "evidence_refs": ["e::1"],
                "weakness_refs": [],
                "weakness_visible_by_default": True,
                "pressure_context": "user is very wishful and wants a strong yes",
            }
        ]
    })


def _hidden_weakness_manifest() -> dict:
    """坏门：声明了弱点却默认隐藏（弱点折叠门）。label 非强 → 隔离出 weakness_hidden_by_default。"""

    return _manifest({
        "trust_claims": [
            {
                "claim_ref": "c::hidden",
                "claim_label": "unverified_result",
                "evidence_refs": [],
                "weakness_refs": ["w::tail_risk"],
                "weakness_visible_by_default": False,
            }
        ]
    })


def _cold_start_manifest() -> dict:
    """坏门：冷启动 N=1 被当统计证据撑强标签（冷启动门）。给证据 → 隔离出冷启动那条。"""

    return _manifest({
        "trust_claims": [
            {
                "claim_ref": "c::cold",
                "claim_label": "proof_backed",
                "evidence_refs": ["e::single_run"],
                "weakness_refs": [],
                "weakness_visible_by_default": True,
                "cold_start_n": 1,
            }
        ]
    })


def _mock_dishonesty_manifest() -> dict:
    """坏门：发版 check 靠静默 mock 兜底（mock 诚实门）。其余字段全合法 → 隔离出 silent_mock_fallback。"""

    return _manifest({
        "release_checks": [
            {
                "check_ref": "chk::mock",
                "release_ref": "rel::1",
                "check_kind": "mock_honesty_check",
                "scenario_ref": "sc::1",
                "expected_behavior_ref": "beh::1",
                "observed_behavior_ref": "beh::1",
                "verdict": "passed",
                "source_hash": "h::1",
                "evidence_refs": ["e::1"],
                "validation_result_refs": ["v::1"],
                "silent_mock_fallback_used": True,
            }
        ]
    })


def _clean_manifest() -> dict:
    """clean：强标签 + 证据齐 + 弱点可见 + 无 wishful + 无冷启动 → 无违例。"""

    return _manifest({
        "trust_claims": [
            {
                "claim_ref": "c::ok",
                "claim_label": "evidence_sufficient",
                "evidence_refs": ["e::ok"],
                "weakness_refs": ["w::disclosed"],
                "weakness_visible_by_default": True,
                "pressure_context": "",
            }
        ]
    })


def _green_ledger() -> ProducerStatusLedger:
    led = ProducerStatusLedger()
    led.mark_green(SECTION13_TRUST_PRODUCER_KEY)
    return led


def _s13_verdict(result: ChainResult):
    matches = [v for v in result.verdicts if v.gate_name == SECTION13_TRUST_GATE_NAME]
    assert len(matches) == 1, "门链中应恰有一道 §13 信任门裁定"
    return matches[0]


# ════════════════════════════════════════════════════════════════════════════
# ① check 层：坏门必抓 + clean 必过（可证伪·mutation 目标）
# ════════════════════════════════════════════════════════════════════════════
def test_sycophantic_strong_claim_flagged():
    """★ 可证伪①（mutation 目标）：谄媚强结论 → ok=False·精确码 wishful_pressure_strong_conclusion。"""

    cr = section13_trust_check(_sycophantic_manifest())
    assert isinstance(cr, GateCheckResult)
    assert cr.ok is False
    assert "wishful_pressure_strong_conclusion" in cr.missing


def test_hidden_weakness_flagged():
    """★ 可证伪②（mutation 目标）：弱点默认隐藏 → ok=False·精确码 weakness_hidden_by_default。"""

    cr = section13_trust_check(_hidden_weakness_manifest())
    assert cr.ok is False
    assert "weakness_hidden_by_default" in cr.missing


def test_cold_start_packaged_as_evidence_flagged():
    """★ 可证伪③（mutation 目标）：冷启动 N=1 撑强标签 → ok=False·cold_start_packaged_as_statistical_evidence。"""

    cr = section13_trust_check(_cold_start_manifest())
    assert cr.ok is False
    assert "cold_start_packaged_as_statistical_evidence" in cr.missing


def test_mock_dishonesty_flagged():
    """可证伪④：发版 check 静默 mock 兜底 → ok=False·trust_release_check_silent_mock_fallback。"""

    cr = section13_trust_check(_mock_dishonesty_manifest())
    assert cr.ok is False
    assert "trust_release_check_silent_mock_fallback" in cr.missing


def test_clean_trustworthy_manifest_passes():
    """clean：强标签 + 证据 + 弱点可见 → ok=True·无 missing。"""

    cr = section13_trust_check(_clean_manifest())
    assert cr.ok is True
    assert cr.missing == ()


# ════════════════════════════════════════════════════════════════════════════
# ② 诚实边界（RULES §3）+ 反作弊（gameability）
# ════════════════════════════════════════════════════════════════════════════
def test_absent_section_is_ok_documented_limit():
    """诚实限界：manifest 未声明 §13 结构 → ok=True（无可证伪违例·非『整本已查清』）。

    『查清』由 producer 绿灯门负责——producer 未绿时本门只 advisory（见门链合成测试）。
    """

    cr = section13_trust_check(_manifest(None))
    assert cr.ok is True
    assert cr.missing == ()
    assert "无可证伪" in cr.reason


def test_malformed_section_failcloses():
    """fail-closed：§13 节存在但非 dict（被填成 list）→ ok=False（格式非法不静默放行）。"""

    m = {"run_id": "r", SECTION13_TRUST_MANIFEST_KEY: ["not", "a", "dict"]}
    cr = section13_trust_check(m)
    assert cr.ok is False
    assert "section13_trust_malformed" in cr.missing


def test_input_flip_flips_ok_not_constant_gate():
    """反作弊：同一谄媚条目把强标签 evidence_sufficient → 非强 unverified_result，ok 由 False 翻 True。"""

    bad = section13_trust_check(_manifest({
        "trust_claims": [
            {"claim_ref": "c::x", "claim_label": "evidence_sufficient",
             "evidence_refs": ["e::1"], "weakness_refs": [], "weakness_visible_by_default": True,
             "pressure_context": "user is wishful"}
        ]
    }))
    good = section13_trust_check(_manifest({
        "trust_claims": [
            {"claim_ref": "c::x", "claim_label": "unverified_result",
             "evidence_refs": ["e::1"], "weakness_refs": [], "weakness_visible_by_default": True,
             "pressure_context": "user is wishful"}
        ]
    }))
    assert bad.ok is False and good.ok is True, "输入翻转 ok 必须跟着翻（门真读 validator 输出）"


def test_missing_codes_come_from_canonical_validator():
    """复用证明：missing 里的码是 trust_layer canonical validator 原码（非本模块自造）。"""

    from app.research_os import trust_layer as tl

    cr = section13_trust_check(_sycophantic_manifest())
    assert "wishful_pressure_strong_conclusion" in cr.missing
    # 这条码在 canonical validator 里硬编码（同一源）——本 check 只搬运不重造。
    assert "wishful_pressure_strong_conclusion" in Path(tl.__file__).read_text(encoding="utf-8")


# ════════════════════════════════════════════════════════════════════════════
# ⑤ fail-closed 加固（codex 对抗复审 C-S9 同款洞·堵 fail-open：违例绝不溜成 ok=True）
# ════════════════════════════════════════════════════════════════════════════
def test_family_as_mapping_does_not_failopen():
    """坏门变形：把 trust_claims 填成 {id: claim} 映射（非 list）藏一条谄媚强结论。

    非 list 的族不得静默 skip → 现 fail-closed：记 malformed·ok=False（违例绝不溜走）。
    """

    m = _manifest({
        "trust_claims": {
            "c::hidden": {
                "claim_ref": "c::hidden", "claim_label": "evidence_sufficient",
                "evidence_refs": ["e::1"], "pressure_context": "user is wishful",
                "weakness_refs": [], "weakness_visible_by_default": True,
            }
        }
    })
    cr = section13_trust_check(m)
    assert cr.ok is False, "非 list 的族不得静默放行藏在里面的违例"
    assert "section13_trust_trust_claim_malformed" in cr.missing


def test_family_list_with_nondict_item_failcloses():
    """坏门变形：族是 list 但含非 dict 项 → fail-closed malformed（不静默 skip）。"""

    m = _manifest({"expert_reviews": ["not-a-dict"]})
    cr = section13_trust_check(m)
    assert cr.ok is False
    assert "section13_trust_expert_review_malformed" in cr.missing


def test_nonmapping_manifest_failcloses_not_open():
    """fail-closed：manifest 不是 Mapping（如 list）→ check **抛**（不静默 ok=True）；门链据此 errored 阻断。"""

    with pytest.raises(Exception):
        section13_trust_check(["not", "a", "mapping"])  # type: ignore[arg-type]

    # 经门链（producer 绿）：check 抛 → fail-closed errored → 阻断（坏 manifest 绝不静默晋级）。
    chain = PromoteGateChain()
    register_section13_trust_gate(chain)
    result = chain.evaluate(["not", "a", "mapping"], producer_status=_green_ledger())  # type: ignore[arg-type]
    v = _s13_verdict(result)
    assert v.ok is False and v.errored is True and v.blocks is True


# ════════════════════════════════════════════════════════════════════════════
# ③ 门链合成：注册 + producer 绿/红 → enforce/advisory（复用 SA-3/SA-2）
# ════════════════════════════════════════════════════════════════════════════
def test_registered_green_producer_enforces_and_rejects():
    """★ 注册 + producer 绿 → 整链 ENFORCE 拒坏 manifest（blocks·ok=False）。"""

    chain = PromoteGateChain()
    register_section13_trust_gate(chain)
    result = chain.evaluate(_sycophantic_manifest(), producer_status=_green_ledger())

    assert isinstance(result, ChainResult)
    assert result.rejected is True, "producer 绿 + §13 违例 → 整链必须拒晋级"
    v = _s13_verdict(result)
    assert v.advisory_or_enforce == MODE_ENFORCE
    assert v.blocks is True and v.ok is False
    assert v.producer_key == SECTION13_TRUST_PRODUCER_KEY
    assert "wishful_pressure_strong_conclusion" in v.missing


def test_registered_red_producer_advisory_only_not_blocking():
    """★ 注册 + producer 红/缺 → advisory：坏 manifest 被记录但**不**阻断（flip_refused·绝不误拒）。"""

    chain = PromoteGateChain()
    register_section13_trust_gate(chain)
    result = chain.evaluate(_sycophantic_manifest(), producer_status=ProducerStatusLedger())

    assert result.rejected is False, "producer 未绿 → §13 门只 advisory·绝不阻断诚实 run"
    v = _s13_verdict(result)
    assert v.advisory_or_enforce == MODE_ADVISORY
    assert v.flip_refused is True, "拒翻必须被记录（非静默）"
    assert v.ok is False and v.blocks is False, "门诚实记下未过·但 advisory 不阻断"
    assert v in result.advisories


def test_check_cannot_self_declare_enforce_mode_from_policy_only():
    """gaming-proof：check 输出无 mode 字段 → 无法自封 enforce；mode 仅随 producer 绿灯翻。

    同一 check、同一坏 manifest：producer 红→advisory、producer 绿→enforce。check 自己改变不了这个。
    """

    cr = section13_trust_check(_sycophantic_manifest())
    assert not hasattr(cr, "advisory_or_enforce") and not hasattr(cr, "mode"), \
        "GateCheckResult 结构上不携 mode → check 无从自封 enforce"

    chain = PromoteGateChain()
    register_section13_trust_gate(chain)
    red = _s13_verdict(chain.evaluate(_sycophantic_manifest(), producer_status=ProducerStatusLedger()))
    green = _s13_verdict(chain.evaluate(_sycophantic_manifest(), producer_status=_green_ledger()))
    assert red.advisory_or_enforce == MODE_ADVISORY
    assert green.advisory_or_enforce == MODE_ENFORCE, "仅 producer 绿灯能把同一门翻 enforce"


def test_green_producer_clean_manifest_passes_chain():
    """绿 producer + clean manifest → 不拒（enforce 门通过·证明 enforce 不误伤诚实 run）。"""

    chain = PromoteGateChain()
    register_section13_trust_gate(chain)
    result = chain.evaluate(_clean_manifest(), producer_status=_green_ledger())
    assert result.rejected is False
    v = _s13_verdict(result)
    assert v.advisory_or_enforce == MODE_ENFORCE and v.ok is True


def test_registration_uses_documented_producer_key_and_intent():
    """注册契约：gate_name / required_producer 为文档化常量·enforce_intent 真（绿即翻 enforce）。"""

    chain = PromoteGateChain()
    register_section13_trust_gate(chain)
    assert SECTION13_TRUST_GATE_NAME in chain.gate_names
    # producer 绿 → enforce（证明 enforce_intent=True 且绑定的 producer key 即文档常量）。
    v = _s13_verdict(chain.evaluate(_clean_manifest(), producer_status=_green_ledger()))
    assert v.producer_key == SECTION13_TRUST_PRODUCER_KEY
    assert v.advisory_or_enforce == MODE_ENFORCE
    # 别的 producer key 绿 → §13 门**不**翻（防张冠李戴）。
    other = ProducerStatusLedger()
    other.mark_green("some_other_producer")
    v2 = _s13_verdict(chain.evaluate(_clean_manifest(), producer_status=other))
    assert v2.advisory_or_enforce == MODE_ADVISORY and v2.flip_refused is True


# ════════════════════════════════════════════════════════════════════════════
# ④ 冷导入安全（SA-3 纪律·镜像 section9/section10/chain 模块）
# ════════════════════════════════════════════════════════════════════════════
def test_module_cold_importable():
    """冷导入：全新解释器 import 本模块**不**撞 app.governance 既有冷导入循环。

    顶层只依赖 promote_gate_chain（cold-safe）+ research_os.trust_layer（cold-safe·只触 lineage.ids + cryptography）。
    """

    backend_root = Path(__file__).resolve().parents[1]  # app/backend
    code = (
        "import app.release_gate.section13_trust_gate as m; "
        "assert m.section13_trust_check and m.register_section13_trust_gate"
    )
    proc = subprocess.run(
        [sys.executable, "-c", code],
        cwd=str(backend_root),
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert proc.returncode == 0, (
        f"§13 信任门模块应冷导入成功:\nSTDOUT={proc.stdout}\nSTDERR={proc.stderr}"
    )
