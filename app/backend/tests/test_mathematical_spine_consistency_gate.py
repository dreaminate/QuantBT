"""Mathematical Spine · 理论实现一致性硬门的【对抗式】测试（GOAL §6/§8 · 决策 D-MATH-SPINE）。

验收标准（RULES §2）：不是「测函数跑通」，而是「种一个已知的坏门，一致性门必须抓住，
否则门是纸做的」。升级健全谓词 Π 的 8 条必需子句，每条种一个会让「未证明/不一致/过期」
产物被伪装成强标签的坏，断言被拒；外加全绿路径放行（证明门不是一刀切摆设）、拒绝口径
不越权（假绿灯反噬自身）、账本无改小 API（honest 不可伪造）。

谓词与每条门为何必要：dev/research/findings/dreaminate/spine-consistency-gate/00-*.md
"""

from __future__ import annotations

import json

import pytest

from app.lineage import content_hash, evaluate_promotion
from app.lineage.spine import (
    CHECK_FAIL,
    CHECK_PASS,
    CHECK_PENDING,
    LABEL_CHALLENGED,
    LABEL_DRAFT,
    LABEL_EVIDENCE_SUFFICIENT,
    LABEL_EXPLORATORY,
    LABEL_PRODUCTION_READY,
    LABEL_PROOF_BACKED,
    LABEL_USER_WAIVED_THEORY,
    PROOF_BACKED,
    PROOF_SKETCH,
    ConsistencyCheck,
    MathematicalArtifact,
    MethodologyChoiceRecord,
    TheoryImplementationBinding,
)
from app.lineage.spine_gate import BANNED_POSITIVE_TERMS
from app.lineage.spine_ledger import SpineLedger

CODE_SRC_A = "def momentum(p, k):\n    return (p[-1] - p[-1 - k]) / p[-1 - k]\n"
CODE_SRC_B = "def momentum(p, k):\n    return p[-1] / p[-1 - k] - 1.0  # 改了实现\n"
PIT_CONTRACT = {"known_at": "2026-06-01", "effective_at": "2026-06-02"}


# ── builders ────────────────────────────────────────────────────────────────
def _artifact(*, proof=PROOF_BACKED, atype="factor_formula", statement="mom=(p_t-p_{t-k})/p_{t-k}",
              derivation="价格序列差分推导"):
    return MathematicalArtifact(
        artifact_type=atype,
        statement=statement,
        definition="过去 k 日收益率",
        derivation=derivation,
        assumptions=("价格已前复权",),
        applicability="日频, k>=5",
        failure_conditions=("除权未复权",),
        proof_status=proof,
    )


def _binding(art, *, code_source=CODE_SRC_A, data_contract_ref="contract/hs300_daily",
             config_ref="cfg_v1_abc", test_refs=("tests/test_mom.py::ok",), waiver_ref=""):
    return TheoryImplementationBinding.bind_source(
        theory_ref=art.artifact_id,
        code_ref="factors/momentum.py:momentum",
        code_source=code_source,
        config_ref=config_ref,
        data_contract_ref=data_contract_ref,
        test_refs=test_refs,
        waiver_ref=waiver_ref,
    )


def _pass(b):
    return ConsistencyCheck(binding_id=b.binding_id, check_type="numerical", result=CHECK_PASS,
                            expected_property="fixture==0.05", observed_property="0.05")


def _full_green(**ov):
    """8 子句全过的完整套件（factor_formula，非 PIT 类型）。"""
    art = _artifact(**{k: v for k, v in ov.items() if k in ("proof", "atype", "derivation", "statement")})
    b = _binding(art, **{k: v for k, v in ov.items() if k in ("code_source", "data_contract_ref",
                                                              "config_ref", "test_refs", "waiver_ref")})
    return art, b, [_pass(b)]


# ── 全绿路径：门不是一刀切，证据齐了真放行 ────────────────────────────────────
def test_full_green_promotes_to_proof_backed():
    art, b, checks = _full_green()
    d = evaluate_promotion(art, b, checks, requested_label=LABEL_PROOF_BACKED,
                           current_code_hash=content_hash(CODE_SRC_A))
    assert d.promotable is True, d.verdict_text
    assert d.granted_label == LABEL_PROOF_BACKED
    assert d.violations == ()
    assert d.allow_existence is True
    assert "claim-grounded(§8 TheoryClaim⇒Artifact)" in d.matched_rules
    assert "proof-honest" in " ".join(d.matched_rules)


def test_estimator_full_green_with_pit():
    art = _artifact(atype="estimator", statement="OLS β̂=(XᵀX)⁻¹Xᵀy")
    b = _binding(art)
    d = evaluate_promotion(art, b, [_pass(b)], requested_label=LABEL_EVIDENCE_SUFFICIENT,
                           current_code_hash=content_hash(CODE_SRC_A), data_contract=PIT_CONTRACT)
    assert d.promotable is True, d.verdict_text
    assert "pit-bound(§6 estimator 绑 PIT)" in d.matched_rules


# ── ¬(1) 公式无 implementation/test binding → 不得 promoted ────────────────────
def test_missing_test_binding_blocks_promotion():
    art = _artifact()
    b = _binding(art, test_refs=())  # 无 test_ref
    d = evaluate_promotion(art, b, [_pass(b)], requested_label=LABEL_EVIDENCE_SUFFICIENT,
                           current_code_hash=content_hash(CODE_SRC_A))
    assert d.promotable is False
    assert any("binding-exists" in v for v in d.violations)
    assert d.granted_label == LABEL_DRAFT


def test_no_binding_at_all_blocks():
    art = _artifact()
    d = evaluate_promotion(art, None, [], requested_label=LABEL_EVIDENCE_SUFFICIENT)
    assert d.promotable is False
    assert any("binding-exists" in v for v in d.violations)


# ── ¬(2) TIB ⇒ code_ref + config_ref + data_contract_ref ─────────────────────
def test_incomplete_binding_missing_data_contract():
    art = _artifact()
    b = _binding(art, data_contract_ref="")
    d = evaluate_promotion(art, b, [_pass(b)], requested_label=LABEL_EVIDENCE_SUFFICIENT,
                           current_code_hash=content_hash(CODE_SRC_A))
    assert d.promotable is False
    assert any("binding-complete" in v and "data_contract_ref" in v for v in d.violations)


def test_incomplete_binding_missing_config():
    art = _artifact()
    b = _binding(art, config_ref="")
    d = evaluate_promotion(art, b, [_pass(b)], requested_label=LABEL_EVIDENCE_SUFFICIENT,
                           current_code_hash=content_hash(CODE_SRC_A))
    assert d.promotable is False
    assert any("config_ref" in v for v in d.violations)


# ── ¬(3) 声称按理论实现但无决定性 ConsistencyCheck → 拒 ───────────────────────
def test_no_consistency_check_blocks():
    art = _artifact()
    b = _binding(art)
    d = evaluate_promotion(art, b, [], requested_label=LABEL_EVIDENCE_SUFFICIENT,
                           current_code_hash=content_hash(CODE_SRC_A))
    assert d.promotable is False
    assert any("consistency-present" in v for v in d.violations)


def test_only_pending_check_is_not_decisive():
    art = _artifact()
    b = _binding(art)
    pending = ConsistencyCheck(binding_id=b.binding_id, check_type="numerical", result=CHECK_PENDING)
    d = evaluate_promotion(art, b, [pending], requested_label=LABEL_EVIDENCE_SUFFICIENT,
                           current_code_hash=content_hash(CODE_SRC_A))
    assert d.promotable is False
    assert any("consistency-present" in v for v in d.violations)


# ── ¬(4) 代码实现与数学定义不一致 → 拒（命门）─────────────────────────────────
def test_consistency_fail_rejects():
    art = _artifact()
    b = _binding(art)
    failed = ConsistencyCheck(binding_id=b.binding_id, check_type="numerical", result=CHECK_FAIL,
                              expected_property="fixture==0.05", observed_property="0.09",
                              failure_reason="数值偏差超容差")
    d = evaluate_promotion(art, b, [failed], requested_label=LABEL_PROOF_BACKED,
                           current_code_hash=content_hash(CODE_SRC_A))
    assert d.promotable is False
    assert any("consistency-pass" in v and "不一致" in v for v in d.violations)
    assert d.granted_label == LABEL_CHALLENGED


# ── ¬(5) 实现改动后未刷新 binding → 拒（staleness，真 content_hash）────────────
def test_stale_binding_rejected_on_code_change():
    art = _artifact()
    b = _binding(art, code_source=CODE_SRC_A)  # binding 冻结 A 的指纹
    # 实现被改成 B，运行时取 content_hash(B) ≠ binding.code_content_hash
    d = evaluate_promotion(art, b, [_pass(b)], requested_label=LABEL_PROOF_BACKED,
                           current_code_hash=content_hash(CODE_SRC_B))
    assert d.promotable is False
    assert any("fresh" in v and "未刷新" in v for v in d.violations)


def test_binding_never_froze_hash_rejected():
    art = _artifact()
    # 直接造一个从未冻结 code_content_hash 的 binding
    b = TheoryImplementationBinding(theory_ref=art.artifact_id, code_ref="x.py:f",
                                    config_ref="cfg", data_contract_ref="c",
                                    test_refs=("t::ok",), code_content_hash="")
    d = evaluate_promotion(art, b, [_pass(b)], requested_label=LABEL_EVIDENCE_SUFFICIENT)
    assert d.promotable is False
    assert any("fresh" in v and "从未冻结" in v for v in d.violations)


def test_freshness_unverified_note_when_current_hash_absent():
    art, b, checks = _full_green()
    d = evaluate_promotion(art, b, checks, requested_label=LABEL_PROOF_BACKED)  # 不传 current_code_hash
    assert d.promotable is True
    assert any("freshness_unverified" in n for n in d.notes)


# ── ¬(6) 理论证明被 user 跳过但标 proof-backed → 拒 ───────────────────────────
def test_proof_backed_with_user_waiver_rejected():
    art, b, checks = _full_green(proof=PROOF_BACKED)
    choice = MethodologyChoiceRecord(chosen_path=LABEL_USER_WAIVED_THEORY, asset_ref=art.artifact_id,
                                     responsibility_boundary="用户自负", allowed_environment="paper",
                                     skipped_steps=("strict_proof",))
    d = evaluate_promotion(art, b, checks, requested_label=LABEL_PROOF_BACKED,
                           current_code_hash=content_hash(CODE_SRC_A), choice=choice)
    assert d.promotable is False
    assert any("proof-honest" in v for v in d.violations)
    assert d.granted_label == LABEL_USER_WAIVED_THEORY  # 诚实降级到放权标签，不冒充


def test_proof_sketch_cannot_claim_proof_backed():
    art, b, checks = _full_green(proof=PROOF_SKETCH)
    d = evaluate_promotion(art, b, checks, requested_label=LABEL_PROOF_BACKED,
                           current_code_hash=content_hash(CODE_SRC_A))
    assert d.promotable is False
    assert any("proof-honest" in v for v in d.violations)


def test_production_ready_also_requires_proof_honest():
    art, b, checks = _full_green(proof=PROOF_SKETCH)
    d = evaluate_promotion(art, b, checks, requested_label=LABEL_PRODUCTION_READY,
                           current_code_hash=content_hash(CODE_SRC_A))
    assert d.promotable is False
    assert any("proof-honest" in v for v in d.violations)


# ── ¬(7) estimator 未绑定 data timing/PIT → 拒（look-ahead 红线）──────────────
def test_estimator_without_pit_rejected():
    art = _artifact(atype="estimator")
    b = _binding(art)
    d = evaluate_promotion(art, b, [_pass(b)], requested_label=LABEL_EVIDENCE_SUFFICIENT,
                           current_code_hash=content_hash(CODE_SRC_A))  # 不传 data_contract
    assert d.promotable is False
    assert any("pit-bound" in v for v in d.violations)


def test_estimator_partial_pit_rejected():
    art = _artifact(atype="estimator")
    b = _binding(art)
    d = evaluate_promotion(art, b, [_pass(b)], requested_label=LABEL_EVIDENCE_SUFFICIENT,
                           current_code_hash=content_hash(CODE_SRC_A),
                           data_contract={"known_at": "2026-06-01"})  # 缺 effective_at
    assert d.promotable is False
    assert any("pit-bound" in v for v in d.violations)


# ── ¬(8) 请求 proof_backed 但缺 MathematicalArtifact → 拒 ─────────────────────
def test_proof_backed_without_artifact_rejected():
    art = _artifact()
    b = _binding(art)
    d = evaluate_promotion(None, b, [_pass(b)], requested_label=LABEL_PROOF_BACKED,
                           current_code_hash=content_hash(CODE_SRC_A))
    assert d.promotable is False
    assert any("claim-grounded" in v for v in d.violations)


def test_proof_backed_empty_statement_rejected():
    art = _artifact(statement="   ", derivation="")
    b = _binding(art)
    d = evaluate_promotion(art, b, [_pass(b)], requested_label=LABEL_PROOF_BACKED,
                           current_code_hash=content_hash(CODE_SRC_A))
    assert d.promotable is False
    assert any("claim-grounded" in v for v in d.violations)


# ── 弱标签永远可授：诚实标签不越权，不被强证据义务挡住 ────────────────────────
def test_weak_label_always_grantable_even_with_failures():
    art = _artifact()
    b = _binding(art, test_refs=())  # 缺一堆强证据
    failed = ConsistencyCheck(binding_id=b.binding_id, check_type="numerical", result=CHECK_FAIL)
    d = evaluate_promotion(art, b, [failed], requested_label=LABEL_EXPLORATORY)
    assert d.promotable is True  # exploratory 不声称一致/已证明 → 不挡探索（P2）
    assert d.granted_label == LABEL_EXPLORATORY
    assert d.allow_existence is True


# ── 拒绝口径不越权（假绿灯反噬自身）──────────────────────────────────────────
def test_reject_verdict_has_no_overclaim_terms():
    # 拿多个被拒决定，断言 verdict_text 不含越权正向断言词
    art = _artifact()
    decisions = [
        evaluate_promotion(art, _binding(art, test_refs=()), [], requested_label=LABEL_PROOF_BACKED),
        evaluate_promotion(None, _binding(art), [], requested_label=LABEL_PROOF_BACKED),
    ]
    for d in decisions:
        assert d.promotable is False
        for term in BANNED_POSITIVE_TERMS:
            assert term not in d.verdict_text, f"拒绝口径出现越权词 {term!r}：{d.verdict_text}"
        assert "不冒充" in d.verdict_text


# ── 数据模型校验 ─────────────────────────────────────────────────────────────
def test_invalid_proof_status_raises():
    with pytest.raises(ValueError):
        MathematicalArtifact(artifact_type="factor_formula", proof_status="totally_proven")


def test_invalid_check_type_and_result_raise():
    with pytest.raises(ValueError):
        ConsistencyCheck(binding_id="b", check_type="vibes", result=CHECK_PASS)
    with pytest.raises(ValueError):
        ConsistencyCheck(binding_id="b", check_type="numerical", result="green")


def test_content_addressed_ids_deterministic():
    a1 = _artifact()
    a2 = _artifact()
    assert a1.artifact_id == a2.artifact_id  # 同内容同 id（content-addressed）
    a3 = _artifact(statement="不同陈述")
    assert a3.artifact_id != a1.artifact_id
    assert a1.artifact_id.startswith("math_")


# ── 账本：append-only + 无改小/伪造 API + 篡改可检 ────────────────────────────
def test_spine_ledger_has_no_mutation_api(tmp_path):
    led = SpineLedger(tmp_path)
    for forbidden in ("set_label", "force_promote", "promote", "update", "delete", "remove",
                      "set_status", "set_verdict", "override"):
        assert not hasattr(led, forbidden), f"账本暴露了 {forbidden} → 升级结论可被伪造（门坏）"


def test_spine_ledger_records_and_staleness(tmp_path):
    led = SpineLedger(tmp_path)
    art = _artifact()
    b = _binding(art, code_source=CODE_SRC_A)
    led.record_artifact(art)
    led.record_binding(b)
    led.record_check(_pass(b))
    assert led.latest_binding(art.artifact_id)["code_content_hash"] == content_hash(CODE_SRC_A)
    assert led.checks_for(b.binding_id)[0]["result"] == CHECK_PASS
    # 实现没改 → 不 stale；改成 B → stale
    assert led.is_stale(art.artifact_id, CODE_SRC_A) is False
    assert led.is_stale(art.artifact_id, CODE_SRC_B) is True
    assert led.is_stale("不存在的理论", CODE_SRC_A) is None
    ok, issues = led.verify_chain()
    assert ok, issues


def test_spine_ledger_refresh_appends_new_version(tmp_path):
    led = SpineLedger(tmp_path)
    art = _artifact()
    led.record_binding(_binding(art, code_source=CODE_SRC_A))
    led.record_binding(_binding(art, code_source=CODE_SRC_B))  # 刷新 = append 新版本
    assert len(led.list_bindings(art.artifact_id)) == 2  # 旧版仍在链上（staleness 可重算）
    assert led.latest_binding(art.artifact_id)["code_content_hash"] == content_hash(CODE_SRC_B)


def test_spine_ledger_tamper_detected(tmp_path):
    led = SpineLedger(tmp_path)
    art = _artifact()
    led.record_binding(_binding(art))
    led.record_check(_pass(_binding(art)))
    # 篡改：把 jsonl 中间行的 payload 改掉，破坏哈希链
    path = tmp_path / "spine_ledger.jsonl"
    lines = path.read_text(encoding="utf-8").splitlines()
    rec = json.loads(lines[0])
    rec["payload"]["code_ref"] = "被偷偷改了"
    lines[0] = json.dumps(rec, ensure_ascii=False)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    led2 = SpineLedger(tmp_path)
    ok, issues = led2.verify_chain()
    assert ok is False and issues  # 篡改被检出
