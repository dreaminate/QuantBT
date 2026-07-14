"""C-S6-MATHCHAIN-AUTOWRITE · §6 数学链发版 check 插 SA-3 门链 · 对抗测试（RULES §2 种坏门必抓 + §3 诚实）。

可证伪验收（construction-map C-S6-MATHCHAIN-AUTOWRITE·8 子句全经 lineage.spine_gate.evaluate_promotion 单一源）：
  · ① 声 theory-backed 缺 ConsistencyCheck → ok=False（consistency-present 子句）
  · ② 缺 TheoryImplementationBinding → ok=False（binding-exists 子句）
  · ③ ConsistencyCheck=fail → ok=False（consistency-pass 子句）
  · ④ 完整数学链 → ok=True
  · ⑤ 无 theory 声明 honest-absent / 弱标签 honest-bound → ok=True（不误拒）
补充子句（同一委托）：proof_backed 无证明 → proof-honest；binding 缺字段 → binding-complete；
  estimator 未绑 PIT → pit-bound；实现改了没刷 binding → fresh；waiver 标 proof_backed → proof-honest。
门链合成（复用 SA-3/SA-2·非本卡重测）：
  · 注册 + producer 绿 → 整链 ENFORCE 拒残缺数学链（blocks）
  · 注册 + producer 红/缺 → advisory：只记录不阻断（flip_refused·绝不误拒）
  · check 无 mode 字段 → 无法自封 enforce：mode 仅由 producer 绿灯翻（gaming-proof）
gameability：输入翻转 ok 跟着翻（非常量门）；复用 = missing 逐条来自 spine_gate.evaluate_promotion.violations。
fail-closed：section 非 dict / claims 非 list / claim 非 dict / 子对象非 dict / checks 形态非法 /
  proof_status·check_type·result 非法（adapter 炸）/ evaluate 炸 / 非 Mapping manifest → 全 ok=False 或抛
  （违例绝不溜成 ok=True）。

★ producer 仍 RED（无假绿灯）：本卡**不建** producer 接线 `s6_mathchain_runjson_producers`（把真 artifact/
  真 binding/真 ConsistencyCheck 写进 manifest 那层 = 独立卡 C-S6-RUNJSON-PRODUCERS）。下方门链合成测试用
  **测试态本地** ProducerStatusLedger.mark_green(...) 证明 enforce 行为为真——绝非生产假绿灯（生产
  producer_status 默认 None=红·见 test_absent_producer_status_advisory_only）。

★ mutation 三态（已手验）：把 section6_mathchain_gate._collect 里 `if not decision.promotable:` 弱化成
  `if False:`（无视 spine_gate.evaluate_promotion 的 Π 裁定·让残缺数学链溜成 ok=True）→
  test_missing_consistency_check_flagged / test_missing_binding_flagged / test_failed_consistency_check_flagged
  （+ proof-honest / pit-bound / fresh / 门链 green-enforce）转 RED → 还原 → GREEN。
"""

from __future__ import annotations

import copy
import subprocess
import sys
from pathlib import Path

import pytest

# 冷导入预热（既有循环·非本卡引入）：导入 app.governance.* 前先全载 orchestrator 解环——与
# test_promote_gate_chain.py / test_section17_rdp_gate.py 同款顺序（app.governance 包 __init__ 经
# spine_invariants 触达 orchestrator）。
import app.agent.orchestrator  # noqa: F401  (prime: 解 app.governance 既有冷导入循环)

from app.governance.enforcement_policy import (  # noqa: E402
    MODE_ADVISORY,
    MODE_ENFORCE,
    ProducerStatusLedger,
)
from app.lineage.spine import (  # noqa: E402
    ConsistencyCheck,
    MathematicalArtifact,
    TheoryImplementationBinding,
)
from app.lineage.spine_gate import evaluate_promotion  # noqa: E402
from app.release_gate.promote_gate_chain import (  # noqa: E402
    ChainResult,
    GateCheckResult,
    PromoteGateChain,
)
from app.release_gate.section6_mathchain_gate import (  # noqa: E402
    SECTION6_MATHCHAIN_GATE_NAME,
    SECTION6_MATHCHAIN_MANIFEST_KEY,
    SECTION6_MATHCHAIN_PRODUCER_KEY,
    register_section6_mathchain_gate,
    section6_mathchain_check,
)

# ════════════════════════════════════════════════════════════════════════════
# manifest 构造器（faithful §6 producer 契约·中心后续据此填）
# ════════════════════════════════════════════════════════════════════════════
# 一条**完整且诚实**的升级 claim（过 evidence_sufficient 全部相关子句·非 PIT/非 proof-requiring）：
#   artifact(statement/definition) + 完整 binding(code+config+data_contract+content_hash+test_refs)
#   + 决定性通过 ConsistencyCheck。各对抗用例从此基线**删/篡一项**隔离出对应子句。
_BASE_BINDING = TheoryImplementationBinding(
    theory_ref="theory::alpha_x",
    code_ref="factors/alpha_x.py",
    code_content_hash="hash::v1",
    config_ref="cfg::alpha_x",
    data_contract_ref="dc::alpha_x",
    test_refs=("test::alpha_x",),
)

_BASE_CLAIM = {
    "requested_label": "evidence_sufficient",
    "asset_ref": "factor::alpha_x",
    "artifact": {
        "artifact_type": "factor_formula",
        "statement": "IC(x) 定义",
        "definition": "x = a / b",
        "derivation": "由 ... 推得",
    },
    "binding": {
        "theory_ref": "theory::alpha_x",
        "code_ref": "factors/alpha_x.py",
        "code_content_hash": "hash::v1",
        "config_ref": "cfg::alpha_x",
        "data_contract_ref": "dc::alpha_x",
        "test_refs": ["test::alpha_x"],
    },
    "consistency_checks": [
        {
            "binding_id": _BASE_BINDING.binding_id,
            "check_type": "numerical",
            "result": "pass",
        }
    ],
}


def _manifest(section) -> dict:
    m = {"run_id": "ide_promote_test", "status": "completed"}
    if section is not None:
        m[SECTION6_MATHCHAIN_MANIFEST_KEY] = section
    return m


def _section(claims) -> dict:
    return {"promotion_claims": claims}


def _claim(**overrides) -> dict:
    c = copy.deepcopy(_BASE_CLAIM)
    c.update(overrides)
    return c


def _drop(field: str) -> dict:
    """完整 claim 删一个顶层 key（隔离出对应子句）。"""

    c = copy.deepcopy(_BASE_CLAIM)
    c.pop(field, None)
    return c


def _green_ledger() -> ProducerStatusLedger:
    led = ProducerStatusLedger()
    led.mark_green(SECTION6_MATHCHAIN_PRODUCER_KEY)  # 仅此卡测试态·绝非生产假绿灯
    return led


def _s6_verdict(result: ChainResult):
    matches = [v for v in result.verdicts if v.gate_name == SECTION6_MATHCHAIN_GATE_NAME]
    assert len(matches) == 1, "门链中应恰有一道 §6 数学链门裁定"
    return matches[0]


def _has_clause(cr: GateCheckResult, token: str) -> bool:
    return any(token in m for m in cr.missing)


# ════════════════════════════════════════════════════════════════════════════
# ① check 层：5 可证伪点（mutation 目标）+ 补充子句
# ════════════════════════════════════════════════════════════════════════════
def test_missing_consistency_check_flagged():
    """★ 可证伪①（mutation 目标）：声 theory-backed 缺 ConsistencyCheck → ok=False·consistency-present。"""

    cr = section6_mathchain_check(_manifest(_section([_drop("consistency_checks")])))
    assert isinstance(cr, GateCheckResult)
    assert cr.ok is False
    assert _has_clause(cr, "consistency-present")


def test_missing_binding_flagged():
    """★ 可证伪②（mutation 目标）：缺 TheoryImplementationBinding → ok=False·binding-exists。"""

    cr = section6_mathchain_check(_manifest(_section([_drop("binding")])))
    assert cr.ok is False
    assert _has_clause(cr, "binding-exists")


def test_failed_consistency_check_flagged():
    """★ 可证伪③（mutation 目标）：ConsistencyCheck=fail（实现↔定义不一致）→ ok=False·consistency-pass。"""

    bad = _claim(consistency_checks=[
        {"binding_id": _BASE_BINDING.binding_id, "check_type": "numerical", "result": "fail",
         "failure_reason": "相对误差 0.3 超容差"}
    ])
    cr = section6_mathchain_check(_manifest(_section([bad])))
    assert cr.ok is False
    assert _has_clause(cr, "consistency-pass")


def test_complete_math_chain_passes():
    """★ 可证伪④：完整诚实数学链 → ok=True·无 missing。"""

    cr = section6_mathchain_check(_manifest(_section([dict(_BASE_CLAIM)])))
    assert cr.ok is True
    assert cr.missing == ()


def test_binding_missing_required_ref_flagged():
    """补充：binding 缺 config_ref → ok=False·binding-complete（§8 TIB ⇒ code+config+data_contract）。"""

    claim = _claim()
    claim["binding"] = {k: v for k, v in _BASE_CLAIM["binding"].items() if k != "config_ref"}
    cr = section6_mathchain_check(_manifest(_section([claim])))
    assert cr.ok is False
    assert _has_clause(cr, "binding-complete")


def test_proof_backed_without_proof_flagged():
    """补充：请求 proof_backed 但 proof_status≠proof_backed → ok=False·proof-honest。"""

    claim = _claim(requested_label="proof_backed")
    claim["artifact"] = {**_BASE_CLAIM["artifact"], "proof_status": "unproven"}
    cr = section6_mathchain_check(_manifest(_section([claim])))
    assert cr.ok is False
    assert _has_clause(cr, "proof-honest")


def test_proof_backed_with_waiver_flagged():
    """补充：proof_backed + 用户 waiver（跳过严格证明）→ ok=False·proof-honest（降级·不冒充）。"""

    claim = _claim(requested_label="proof_backed")
    claim["artifact"] = {**_BASE_CLAIM["artifact"], "proof_status": "proof_backed"}
    claim["binding"] = {**_BASE_CLAIM["binding"], "waiver_ref": "waiver::user_skip"}
    cr = section6_mathchain_check(_manifest(_section([claim])))
    assert cr.ok is False
    assert _has_clause(cr, "proof-honest")


def test_estimator_without_pit_flagged():
    """补充：estimator 未绑 PIT(known_at∧effective_at) → ok=False·pit-bound（防 look-ahead）。"""

    claim = _claim()
    claim["artifact"] = {"artifact_type": "estimator", "statement": "rolling beta", "definition": "..."}
    # 无 data_contract → pit 缺
    cr = section6_mathchain_check(_manifest(_section([claim])))
    assert cr.ok is False
    assert _has_clause(cr, "pit-bound")


def test_estimator_with_pit_passes():
    """补充：estimator + data_contract(known_at∧effective_at) → ok=True（PIT 绑定齐·过）。"""

    claim = _claim(data_contract={"known_at": "2020-01-01", "effective_at": "2020-01-02"})
    claim["artifact"] = {"artifact_type": "estimator", "statement": "rolling beta", "definition": "..."}
    cr = section6_mathchain_check(_manifest(_section([claim])))
    assert cr.ok is True


def test_stale_binding_flagged():
    """补充：实现改了没刷 binding（current_code_hash ≠ binding.code_content_hash）→ ok=False·fresh。"""

    claim = _claim(current_code_hash="hash::v2_changed")  # binding 冻结的是 hash::v1
    cr = section6_mathchain_check(_manifest(_section([claim])))
    assert cr.ok is False
    assert _has_clause(cr, "fresh")


# ════════════════════════════════════════════════════════════════════════════
# ② 诚实限界（RULES §3·honest-absent / honest-bound·不误拒）
# ════════════════════════════════════════════════════════════════════════════
def test_absent_section_is_ok_documented_limit():
    """⑤ 诚实限界：manifest 未声明 §6 结构 → ok=True（无可证伪违例·非『整本已查清』）。"""

    cr = section6_mathchain_check(_manifest(None))
    assert cr.ok is True
    assert cr.missing == ()
    assert "无可证伪" in cr.reason


def test_absent_claims_nothing_declared_ok():
    """诚实限界：section 在但无 promotion_claims → ok=True（未声明·非违例）。"""

    cr = section6_mathchain_check(_manifest({}))
    assert cr.ok is True
    assert cr.missing == ()


def test_empty_claims_list_ok():
    """诚实限界：promotion_claims=[] → ok=True（空声明·非违例）。"""

    cr = section6_mathchain_check(_manifest(_section([])))
    assert cr.ok is True
    assert cr.missing == ()


def test_weak_label_claim_honest_bound_ok():
    """⑤ honest-bound：claim 请求弱标签（draft）→ evaluate_promotion 恒 promotable → ok=True（不误拒）。"""

    cr = section6_mathchain_check(_manifest(_section([
        {"requested_label": "draft", "artifact": {"artifact_type": "factor_formula"}}
    ])))
    assert cr.ok is True
    assert cr.missing == ()


def test_empty_claim_defaults_draft_ok():
    """honest-bound：空 claim {}（无 requested_label → 默认 draft）→ ok=True（无越权标注·不误拒）。"""

    cr = section6_mathchain_check(_manifest(_section([{}])))
    assert cr.ok is True
    assert cr.missing == ()


# ════════════════════════════════════════════════════════════════════════════
# ③ 反作弊（gameability）+ 复用证明（不重造）
# ════════════════════════════════════════════════════════════════════════════
def test_input_flip_flips_ok_not_constant_gate():
    """反作弊：同一 claim 补回 ConsistencyCheck，ok 由 False 翻 True（门真读 evaluate_promotion·非常量门）。"""

    bad = section6_mathchain_check(_manifest(_section([_drop("consistency_checks")])))
    good = section6_mathchain_check(_manifest(_section([dict(_BASE_CLAIM)])))
    assert bad.ok is False and good.ok is True, "输入翻转 ok 必须跟着翻"


def test_missing_delegated_to_canonical_evaluate_promotion():
    """复用证明：本 check 的 missing 逐条 == canonical `spine_gate.evaluate_promotion` 的 violations。

    独立重建同字段 canonical record·直算 evaluate_promotion·证明 missing 100% 来自单一源（不重造判定）。
    """

    d = _drop("consistency_checks")  # evidence_sufficient·缺 checks
    artifact = MathematicalArtifact(
        artifact_type="factor_formula", statement="IC(x) 定义", definition="x = a / b",
        derivation="由 ... 推得",
    )
    binding = TheoryImplementationBinding(
        theory_ref="theory::alpha_x", code_ref="factors/alpha_x.py", code_content_hash="hash::v1",
        config_ref="cfg::alpha_x", data_contract_ref="dc::alpha_x", test_refs=("test::alpha_x",),
    )
    decision = evaluate_promotion(artifact, binding, [], requested_label="evidence_sufficient")
    cr = section6_mathchain_check(_manifest(_section([d])))
    assert cr.ok is False and decision.promotable is False
    assert set(cr.missing) == set(decision.violations), \
        "missing 必逐条来自 canonical evaluate_promotion.violations（复用不重造）"


def test_multiple_claims_one_bad_rejects_and_aggregates():
    """聚合：多 claim 一好一坏 → 整体 ok=False·坏 claim 的 asset_ref 进 reason（不漏不误）。"""

    good = dict(_BASE_CLAIM)
    bad = _claim(asset_ref="factor::broken")
    bad.pop("binding", None)
    cr = section6_mathchain_check(_manifest(_section([good, bad])))
    assert cr.ok is False
    assert "factor::broken" in cr.reason


# ════════════════════════════════════════════════════════════════════════════
# ④ fail-closed 加固（codex C-S9 同款洞·堵 fail-open：违例绝不溜成 ok=True）
# ════════════════════════════════════════════════════════════════════════════
def test_section_not_mapping_failcloses():
    """fail-closed：§6 节非 dict（被填成 list）→ ok=False（'section6_mathchain_malformed'）。"""

    cr = section6_mathchain_check(_manifest(["not", "a", "dict"]))
    assert cr.ok is False
    assert "section6_mathchain_malformed" in cr.missing


def test_claims_not_list_failcloses():
    """fail-closed：promotion_claims 非 list → ok=False（'section6_mathchain_promotion_claims_malformed'）。"""

    cr = section6_mathchain_check(_manifest({"promotion_claims": "nope"}))
    assert cr.ok is False
    assert "section6_mathchain_promotion_claims_malformed" in cr.missing


def test_claim_not_mapping_failcloses():
    """fail-closed：claim 项非 dict → ok=False（'section6_mathchain_claim_malformed'）。"""

    cr = section6_mathchain_check(_manifest(_section(["not-a-dict"])))
    assert cr.ok is False
    assert "section6_mathchain_claim_malformed" in cr.missing


def test_artifact_not_mapping_failcloses():
    """fail-closed：artifact 子对象非 dict → ok=False（'section6_mathchain_artifact_malformed'）。"""

    cr = section6_mathchain_check(_manifest(_section([{"artifact": "x"}])))
    assert cr.ok is False
    assert "section6_mathchain_artifact_malformed" in cr.missing


def test_binding_not_mapping_failcloses():
    """fail-closed：binding 子对象非 dict → ok=False（'section6_mathchain_binding_malformed'）。"""

    cr = section6_mathchain_check(_manifest(_section([{"binding": "x"}])))
    assert cr.ok is False
    assert "section6_mathchain_binding_malformed" in cr.missing


def test_consistency_checks_not_list_failcloses():
    """fail-closed：consistency_checks 非 list/dict（标量）→ ok=False（'..._consistency_checks_malformed'）。"""

    cr = section6_mathchain_check(_manifest(_section([{"consistency_checks": 5}])))
    assert cr.ok is False
    assert "section6_mathchain_consistency_checks_malformed" in cr.missing


def test_consistency_checks_item_not_dict_failcloses():
    """fail-closed：consistency_checks 内含非 dict 项 → ok=False（不静默 skip 让违例溜走）。"""

    cr = section6_mathchain_check(_manifest(_section([{"consistency_checks": ["not-a-dict"]}])))
    assert cr.ok is False
    assert "section6_mathchain_consistency_checks_malformed" in cr.missing


def test_bad_proof_status_unparseable_failcloses():
    """fail-closed：proof_status 非法 → MathematicalArtifact 构造 raise → ok=False（'..._claim_unparseable'）。"""

    cr = section6_mathchain_check(_manifest(_section([
        {"artifact": {"artifact_type": "factor_formula", "proof_status": "garbage"}}
    ])))
    assert cr.ok is False
    assert "section6_mathchain_claim_unparseable" in cr.missing


def test_bad_check_type_unparseable_failcloses():
    """fail-closed：check_type 非法 → ConsistencyCheck 构造 raise → ok=False（'..._claim_unparseable'）。"""

    cr = section6_mathchain_check(_manifest(_section([
        {"consistency_checks": [{"binding_id": "b", "check_type": "BAD", "result": "pass"}]}
    ])))
    assert cr.ok is False
    assert "section6_mathchain_claim_unparseable" in cr.missing


def test_bad_check_result_unparseable_failcloses():
    """fail-closed：result 非法 → ConsistencyCheck 构造 raise → ok=False（'..._claim_unparseable'）。"""

    cr = section6_mathchain_check(_manifest(_section([
        {"consistency_checks": [{"binding_id": "b", "check_type": "numerical", "result": "BAD"}]}
    ])))
    assert cr.ok is False
    assert "section6_mathchain_claim_unparseable" in cr.missing


# —— codex 复审堵的 2 类 malformed-input fail-open（种坏必抓·防回归）——
def test_nonstring_requested_label_failcloses():
    """fail-closed（codex①）：非 str requested_label（list/int）→ ok=False·绝不 str() 成未知弱标签放行。

    `['production_ready']` / `123` 若被 `str(...)` 改写成非匹配字符串，会被当弱标签 promotable=True 放行
    （强晋级悄悄降级）→ fail-open。本门改 fail-closed：记 requested_label_malformed。
    """

    for bad_label in (["production_ready"], 123, True):
        cr = section6_mathchain_check(_manifest(_section([
            {"requested_label": bad_label, "artifact": {}, "binding": {}}
        ])))
        assert cr.ok is False, f"非 str requested_label={bad_label!r} 必 fail-closed"
        assert "section6_mathchain_requested_label_malformed" in cr.missing


def test_whitespace_strong_label_not_downgraded():
    """fail-closed（codex①）：'production_ready '（带空白的强标签）strip 后按真强标签判·不被当未知弱标签绕过。

    残缺 claim（空 artifact/binding）+ 带空白强标签 → ok=False（强标签义务被执行·命中强标签子句），
    而非 ok=True（若不 strip 会当未知弱标签放行 = fail-open）。
    """

    cr = section6_mathchain_check(_manifest(_section([
        {"requested_label": "production_ready ", "asset_ref": "x", "artifact": {}, "binding": {}}
    ])))
    assert cr.ok is False
    assert _has_clause(cr, "claim-grounded") or _has_clause(cr, "binding-exists"), \
        "带空白强标签必须按强标签判（执行强标签子句）·非降级放行"


def test_malformed_test_refs_no_phantom_binding_exists():
    """fail-closed（codex②）：malformed/空白 test_refs 不得 fabricate 成幽灵 ref 满足 binding-exists。

    test_refs={...}（dict）/ ''（空串）/ ['']（空白项）→ `_as_tuple` 滤成空 → binding-exists 拒（与 §17
    hollow-values 同纪律）。否则一个无真 test binding 的产物会冒充「有 binding」溜过强标签门 = fail-open。
    """

    for bad_refs in ({"not": "a-list"}, "", [""], ["  "], 0):
        claim = _claim()
        claim["binding"] = {**_BASE_CLAIM["binding"], "test_refs": bad_refs}
        cr = section6_mathchain_check(_manifest(_section([claim])))
        assert cr.ok is False, f"malformed test_refs={bad_refs!r} 不得满足 binding-exists"
        assert _has_clause(cr, "binding-exists"), \
            f"malformed test_refs={bad_refs!r} → binding-exists 必须拒（不 fabricate 幽灵 ref）"


def test_nonmapping_manifest_failcloses_not_open():
    """fail-closed：manifest 不是 Mapping（如 list）→ check **抛**（不静默 ok=True）；门链据此 errored 阻断。"""

    with pytest.raises(Exception):
        section6_mathchain_check(["not", "a", "mapping"])  # type: ignore[arg-type]

    # 经门链（producer 绿）：check 抛 → fail-closed errored → 阻断（坏 manifest 绝不静默晋级）。
    chain = PromoteGateChain()
    register_section6_mathchain_gate(chain)
    result = chain.evaluate(["not", "a", "mapping"], producer_status=_green_ledger())  # type: ignore[arg-type]
    v = _s6_verdict(result)
    assert v.ok is False and v.errored is True and v.blocks is True


# ════════════════════════════════════════════════════════════════════════════
# ⑤ 门链合成：注册 + producer 绿/红 → enforce/advisory（复用 SA-3/SA-2）
# ════════════════════════════════════════════════════════════════════════════
def test_registered_green_producer_enforces_and_rejects():
    """★ 注册 + producer 绿 → 整链 ENFORCE 拒残缺数学链（blocks·ok=False·缺项精确）。"""

    chain = PromoteGateChain()
    register_section6_mathchain_gate(chain)
    result = chain.evaluate(
        _manifest(_section([_drop("consistency_checks")])), producer_status=_green_ledger()
    )

    assert isinstance(result, ChainResult)
    assert result.rejected is True, "producer 绿 + 残缺数学链 → 整链必须拒晋级"
    v = _s6_verdict(result)
    assert v.advisory_or_enforce == MODE_ENFORCE
    assert v.blocks is True and v.ok is False
    assert v.producer_key == SECTION6_MATHCHAIN_PRODUCER_KEY
    assert any("consistency-present" in m for m in v.missing)


def test_registered_red_producer_advisory_only_not_blocking():
    """★ 注册 + producer 红/缺 → advisory：残缺数学链被记录但**不**阻断（flip_refused·绝不误拒）。"""

    chain = PromoteGateChain()
    register_section6_mathchain_gate(chain)
    result = chain.evaluate(
        _manifest(_section([_drop("consistency_checks")])), producer_status=ProducerStatusLedger()
    )

    assert result.rejected is False, "producer 未绿 → §6 门只 advisory·绝不阻断"
    v = _s6_verdict(result)
    assert v.advisory_or_enforce == MODE_ADVISORY
    assert v.flip_refused is True, "拒翻必须被记录（非静默）"
    assert v.ok is False and v.blocks is False, "门诚实记下未过·但 advisory 不阻断"
    assert v in result.advisories


def test_absent_producer_status_advisory_only():
    """★ 无假绿灯：producer_status=None（生产默认）→ §6 门 advisory·producer_green=False·不阻断。"""

    chain = PromoteGateChain()
    register_section6_mathchain_gate(chain)
    result = chain.evaluate(_manifest(_section([_drop("consistency_checks")])), producer_status=None)

    assert result.rejected is False
    v = _s6_verdict(result)
    assert v.advisory_or_enforce == MODE_ADVISORY
    assert v.producer_green is False, "确认 producer 仍 RED（出厂红·无假绿灯）"
    assert v.blocks is False


def test_check_cannot_self_declare_enforce():
    """gaming-proof：check 输出无 mode 字段 → 无法自封 enforce；mode 仅随 producer 绿灯翻。"""

    cr = section6_mathchain_check(_manifest(_section([_drop("consistency_checks")])))
    assert not hasattr(cr, "advisory_or_enforce") and not hasattr(cr, "mode"), \
        "GateCheckResult 结构上不携 mode → check 无从自封 enforce"

    chain = PromoteGateChain()
    register_section6_mathchain_gate(chain)
    bad = _manifest(_section([_drop("consistency_checks")]))
    red = _s6_verdict(chain.evaluate(bad, producer_status=ProducerStatusLedger()))
    green = _s6_verdict(chain.evaluate(bad, producer_status=_green_ledger()))
    assert red.advisory_or_enforce == MODE_ADVISORY
    assert green.advisory_or_enforce == MODE_ENFORCE, "仅 producer 绿灯能把同一门翻 enforce"


def test_green_producer_complete_chain_passes_chain():
    """绿 producer + 完整数学链 → 不拒（enforce 门通过·证明 enforce 不误伤诚实 run）。"""

    chain = PromoteGateChain()
    register_section6_mathchain_gate(chain)
    result = chain.evaluate(_manifest(_section([dict(_BASE_CLAIM)])), producer_status=_green_ledger())
    assert result.rejected is False
    v = _s6_verdict(result)
    assert v.advisory_or_enforce == MODE_ENFORCE and v.ok is True


def test_registration_uses_documented_producer_key_and_intent():
    """注册契约：gate_name / required_producer 为文档化常量·enforce_intent 真（绿即翻 enforce·不张冠李戴）。"""

    chain = PromoteGateChain()
    register_section6_mathchain_gate(chain)
    assert SECTION6_MATHCHAIN_GATE_NAME in chain.gate_names
    v = _s6_verdict(chain.evaluate(_manifest(_section([dict(_BASE_CLAIM)])), producer_status=_green_ledger()))
    assert v.producer_key == SECTION6_MATHCHAIN_PRODUCER_KEY
    assert v.advisory_or_enforce == MODE_ENFORCE
    # 别的 producer key 绿 → §6 门**不**翻（防张冠李戴）。
    other = ProducerStatusLedger()
    other.mark_green("some_other_producer")
    v2 = _s6_verdict(chain.evaluate(_manifest(_section([dict(_BASE_CLAIM)])), producer_status=other))
    assert v2.advisory_or_enforce == MODE_ADVISORY and v2.flip_refused is True


# ════════════════════════════════════════════════════════════════════════════
# ⑥ 冷导入安全（SA-3 纪律·镜像 section9/section10/section13/section16/section17 模块）
# ════════════════════════════════════════════════════════════════════════════
def test_module_cold_importable():
    """冷导入：全新解释器 import 本模块**不**撞 app.governance 既有冷导入循环。

    顶层只依赖 promote_gate_chain（cold-safe）+ lineage.spine / lineage.spine_gate（cold-safe·只触 lineage.ids）。
    """

    backend_root = Path(__file__).resolve().parents[1]  # app/backend
    code = (
        "import app.release_gate.section6_mathchain_gate as m; "
        "assert m.section6_mathchain_check and m.register_section6_mathchain_gate"
    )
    proc = subprocess.run(
        [sys.executable, "-c", code],
        cwd=str(backend_root),
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert proc.returncode == 0, (
        f"§6 数学链门模块应冷导入成功:\nSTDOUT={proc.stdout}\nSTDERR={proc.stderr}"
    )
