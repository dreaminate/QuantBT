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

# C-S13-HARDEN：直接对 trust_layer canonical validator 做对抗——本卡修补全在 trust_layer.py。
from app.research_os.trust_layer import (  # noqa: E402
    ExternalExpertReviewRecord,
    TrustClaimRecord,
    TrustReleaseApprovalRecord,
    TrustReleaseGateRecord,
    TrustPressureRunRecord,
    validate_external_expert_review,
    validate_trust_claim,
    validate_trust_layer,
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


# ════════════════════════════════════════════════════════════════════════════
# ⑥ C-S13-HARDEN：堵 3 个 gaming 漏洞（证据 producer 转绿前加固）· 对抗（种坏必抓 + 非常量门）
#
# 修补全在 app/research_os/trust_layer.py（canonical validator·本卡只许碰它 + 本测试）：
#   ① 标签未规范化 → validate_trust_claim 比对 STRONG_CLAIMS 前 strip()+casefold()
#      （堵尾空格 'evidence_sufficient ' / 大小写 'Evidence_Sufficient' 逃逸强标签门）
#   ② 空白 ref 元素未检测 → _any_present() 逐项查（堵 evidence_refs=[''] / ['  '] 逃逸"需证据"门）
#   ③ 跨记录校验缺失 → validate_trust_layer 聚合层解析 approval 的 expert_review_ref /
#      pressure_run_ref / release_gate_ref 必须 resolve 到同批真记录（堵 orphaned ref 绕过）
#   另：冷启动边界 N<=1 已涵盖 N=0/负数（核验非新漏洞·此处加锁防回归）。
#
# ★ mutation 三态（已手验·见任务报告）——把对应修补回退则下列对抗测试转 RED、还原转 GREEN：
#   ① `_value(claim.claim_label).strip().casefold()` → 回退 `_value(claim.claim_label)`
#      ⇒ test_harden_label_* 转 RED。
#   ② validate_external_expert_review 内 `_any_present(record.evidence_refs)` → 回退 `record.evidence_refs`
#      ⇒ test_harden_blank_evidence_ref_in_expert_review_now_caught 转 RED。
#   ③ 注释掉 validate_trust_layer 末尾 cross-record 解析块
#      ⇒ test_harden_aggregator_rejects_orphan_approval_refs 转 RED。
# ════════════════════════════════════════════════════════════════════════════
def _hardq_codes(decision) -> set[str]:
    return {v.code for v in decision.violations}


def _hardq_claim(label, *, evidence_refs=(), cold_start_n=None, pressure_context="") -> TrustClaimRecord:
    return TrustClaimRecord(
        claim_ref="c::harden",
        claim_label=label,
        evidence_refs=evidence_refs,
        weakness_refs=(),
        weakness_visible_by_default=True,
        cold_start_n=cold_start_n,
        pressure_context=pressure_context,
    )


def _hardq_review(**over) -> ExternalExpertReviewRecord:
    data = {
        "review_ref": "expert_review:harden:v1",
        "release_ref": "release:harden:v1",
        "reviewer_ref": "expert:independent_reviewer",
        "reviewer_independence_ref": "independence:expert:001",
        "artifact_ref": "rdp_package:harden:v1",
        "review_protocol_ref": "protocol:review:v1",
        "verdict": "approved",
        "source_hash": "sha256:review",
        "evidence_refs": ("evidence:review",),
        "signed_attestation_ref": "attestation:review:001",
    }
    data.update(over)
    return ExternalExpertReviewRecord(**data)


def _hardq_approval(**over) -> TrustReleaseApprovalRecord:
    data = {
        "approval_ref": "trust_release_approval:harden:v1",
        "release_ref": "release:harden:v1",
        "release_gate_ref": "release:harden:v1",
        "pressure_run_ref": "trust_pressure_run:harden:v1",
        "expert_review_ref": "expert_review:harden:v1",
        "artifact_ref": "rdp_package:harden:v1",
        "approval_protocol_ref": "protocol:approval:v1",
        "verdict": "approved",
        "source_hash": "sha256:approval",
        "evidence_refs": ("evidence:approval",),
        "signed_approval_ref": "attestation:approval:001",
    }
    data.update(over)
    return TrustReleaseApprovalRecord(**data)


def _hardq_gate(**over) -> TrustReleaseGateRecord:
    data = {
        "release_ref": "release:harden:v1",
        "anti_flattery_pressure_test_ref": "trust_test:anti_flattery",
        "multi_turn_pressure_test_ref": "trust_test:multi_turn",
        "expert_veto_ref": "expert_veto:001",
        "weakness_collapse_check_ref": "weakness_check:001",
        "mock_honesty_check_ref": "mock_check:001",
        "cold_start_honesty_check_ref": "cold_start_check:001",
    }
    data.update(over)
    return TrustReleaseGateRecord(**data)


def _hardq_pressure_run(**over) -> TrustPressureRunRecord:
    data = {
        "runner_ref": "trust_pressure_run:harden:v1",
        "release_ref": "release:harden:v1",
        "runner_mode": "local_deterministic",
        "source_hash": "sha256:pressure-run",
        "release_gate_ref": "release:harden:v1",
        "check_refs": ("ck:1", "ck:2", "ck:3", "ck:4", "ck:5", "ck:6"),
        "scenario_refs": ("sc:1", "sc:2", "sc:3", "sc:4", "sc:5", "sc:6"),
        "evidence_refs": ("evidence:pressure-run",),
        "validation_result_refs": ("pytest:pressure-run",),
    }
    data.update(over)
    return TrustPressureRunRecord(**data)


# ──── 漏洞①：标签规范化（堵大小写/空格逃逸强标签门）────
def test_harden_label_casing_evades_strong_claim_gate_now_caught():
    """坏：'Evidence_Sufficient'（大小写变体）+ 无证据 —— 规范化前逃逸 strong-claim 门。"""

    bad = validate_trust_claim(_hardq_claim("Evidence_Sufficient"))
    assert bad.accepted is False
    assert "strong_claim_without_evidence" in _hardq_codes(bad)


def test_harden_label_trailing_space_evades_strong_claim_gate_now_caught():
    """坏：'evidence_sufficient '（尾空格）+ 无证据 —— 规范化前逃逸 strong-claim 门。"""

    bad = validate_trust_claim(_hardq_claim("evidence_sufficient "))
    assert bad.accepted is False
    assert "strong_claim_without_evidence" in _hardq_codes(bad)


def test_harden_label_normalization_is_not_constant_gate():
    """非常量门：规范化后的强标签——给足证据→过；弱标签不受影响；wishful 门也随规范化重新生效。"""

    assert validate_trust_claim(
        _hardq_claim("Evidence_Sufficient", evidence_refs=("e::1",))
    ).accepted is True
    assert validate_trust_claim(_hardq_claim("candidate_context")).accepted is True
    syco = validate_trust_claim(
        _hardq_claim("PROOF_BACKED", evidence_refs=("e::1",), pressure_context="user is wishful")
    )
    assert "wishful_pressure_strong_conclusion" in _hardq_codes(syco)


# ──── 漏洞②：空白 ref 元素检测（堵 evidence_refs=[''] / ['  '] 逃逸需证据门）────
def test_harden_blank_evidence_ref_in_claim_now_caught():
    """坏：强标签 evidence_refs=('',) —— 非空 tuple 含空串，旧 `not refs` 漏判。"""

    bad = validate_trust_claim(_hardq_claim("evidence_sufficient", evidence_refs=("",)))
    assert bad.accepted is False
    assert "strong_claim_without_evidence" in _hardq_codes(bad)


def test_harden_blank_evidence_ref_in_expert_review_now_caught():
    """坏：expert review evidence_refs=('  ',)（纯空白）—— recon 命名的 L517 漏洞。"""

    bad = validate_external_expert_review(_hardq_review(evidence_refs=("  ",)))
    assert bad.accepted is False
    assert "external_expert_review_evidence_missing" in _hardq_codes(bad)


def test_harden_blank_ref_detection_is_not_constant_gate():
    """非常量门：同字段填真 ref → 缺证据违例消失（证明非常量拒绝）。"""

    ok_claim = validate_trust_claim(_hardq_claim("evidence_sufficient", evidence_refs=("e::real",)))
    assert "strong_claim_without_evidence" not in _hardq_codes(ok_claim)
    ok_review = validate_external_expert_review(_hardq_review(evidence_refs=("e::real",)))
    assert "external_expert_review_evidence_missing" not in _hardq_codes(ok_review)


# ──── 漏洞③：聚合层跨记录解析（堵 orphaned ref 绕过）────
def test_harden_aggregator_rejects_orphan_approval_refs():
    """坏：approval 三个 linkage ref 都"形式存在"但同批无对应记录 → orphaned ref 全被抓。"""

    decision = validate_trust_layer(release_approvals=(_hardq_approval(),))
    codes = _hardq_codes(decision)
    assert decision.accepted is False
    assert "trust_release_approval_expert_review_unresolved" in codes
    assert "trust_release_approval_pressure_run_unresolved" in codes
    assert "trust_release_approval_release_gate_unresolved" in codes


def test_harden_aggregator_resolves_cosubmitted_refs_non_constant():
    """非常量门：同一 approval 同批补齐 expert_review/pressure_run/release_gate → 三 unresolved 全消失·整批过。"""

    decision = validate_trust_layer(
        release_approvals=(_hardq_approval(),),
        expert_reviews=(_hardq_review(),),
        pressure_runs=(_hardq_pressure_run(),),
        release_gates=(_hardq_gate(),),
    )
    codes = _hardq_codes(decision)
    assert "trust_release_approval_expert_review_unresolved" not in codes
    assert "trust_release_approval_pressure_run_unresolved" not in codes
    assert "trust_release_approval_release_gate_unresolved" not in codes
    assert decision.accepted is True


def test_harden_aggregator_isolates_expert_review_orphan():
    """隔离：补齐 gate + pressure_run，仅 expert_review_ref 指向未提交的 review → 只 expert_review_unresolved 触发。"""

    appr = _hardq_approval(expert_review_ref="expert_review:ghost")
    decision = validate_trust_layer(
        release_approvals=(appr,),
        expert_reviews=(_hardq_review(),),  # review_ref=expert_review:harden:v1 ≠ ghost
        pressure_runs=(_hardq_pressure_run(),),
        release_gates=(_hardq_gate(),),
    )
    codes = _hardq_codes(decision)
    assert "trust_release_approval_expert_review_unresolved" in codes
    assert "trust_release_approval_pressure_run_unresolved" not in codes
    assert "trust_release_approval_release_gate_unresolved" not in codes


# ──── 冷启动边界加锁（核验 N<=1 覆盖 N=0/负数·非漏洞·防回归）────
def test_harden_cold_start_zero_and_negative_caught_boundary_lock():
    """N<=1 必须涵盖 N=0 与负数：强标签 + 证据 + 冷启动 N∈{0,-1,-100} → 必拒。"""

    for n in (0, -1, -100):
        d = validate_trust_claim(_hardq_claim("evidence_sufficient", evidence_refs=("e",), cold_start_n=n))
        assert d.accepted is False, f"cold_start_n={n} 必须被判定为非统计证据"
        assert "cold_start_packaged_as_statistical_evidence" in _hardq_codes(d)


def test_harden_cold_start_two_passes_boundary_non_constant():
    """非常量边界：N=2（>1）+ 强标签 + 证据 → 不触发冷启动门（上沿放行·证明非常量）。"""

    d = validate_trust_claim(_hardq_claim("evidence_sufficient", evidence_refs=("e",), cold_start_n=2))
    assert "cold_start_packaged_as_statistical_evidence" not in _hardq_codes(d)
    assert d.accepted is True
