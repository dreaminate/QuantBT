"""NC-S6-MATHCHAIN-PRODUCER · §6 数学链 producer builder 接线测试（RULES §2 种坏门必抓 + §3 诚实）。

证明 `research_os.spine.build_section6_mathchain_record` 这个 producer builder 有牙：从真 theory-backed
run 的 canonical lineage.spine typed 对象（MathematicalArtifact / TheoryImplementationBinding /
ConsistencyCheck）忠实序列化成 §6 门 producer 契约 record → 标 producer `s6_mathchain_runjson_producers`
绿 → §6 门从 advisory 翻 ENFORCE → **合规 run 仍过（不误拒）· 坏 run 真拒（有牙）· honest-absent 过**。

接线四点（卡要求）：
  · ① 合规 theory-backed run → build record → manifest[section6_mathchain] → producer 绿 → 门 ENFORCE 仍 ok=True
  · ② 坏 run（强标签缺 ConsistencyCheck）→ build record → producer 绿 → 门 ENFORCE 拒 ok=False（consistency-present）
  · ③ honest-absent（无 theory 声明）→ build record=None → 中心不发 section → 门 ok=True（未声明≠违例·不误拒）
  · ④ producer 红时坏 run → 门 advisory：只记录不阻断（flip_refused·绝不误拒诚实 run）
补强（gaming-proof + 复用证明）：
  · faithful 往返：built record 经门的裁定 == 直算 spine_gate.evaluate_promotion（复用不重造·非另判）
  · no whitewash：坏 claim 缺 ConsistencyCheck → 序列化就缺（builder 绝不 fabricate 假 pass 洗白）
  · fail-closed：claim 携错 flavor / 错类型对象 → Section6RecordError（不静默吞坏输入·不产骗门 dict）
  · 输入翻转 ok 跟着翻（非常量·真读 evaluate_promotion）；proof_backed 合规过（证 builder 携 proof_status）

★ producer 真绿是后续 NC-REAL-RESEARCH-PROMOTE 的事（真 run 真写真记录那层）：本卡只建 builder 机制 +
  证有牙。门链合成测试用**测试态本地** ProducerStatusLedger.mark_green(...) 证明 enforce 行为为真——绝非
  生产假绿灯（生产 producer_status 默认 None=红·见 test_red_producer_bad_run_advisory_only_not_blocking）。

★ mutation 三态（已手验·见 spine.py `_section6_claim_to_dict` mutation 锚点）：
  - 漏报：把 builder 的 `consistency_checks` 序列化弱化成「不发 consistency_checks key」→ 合规 run 真 check
    消失 → 门 consistency-present 误拒合规 → test_compliant_run_builds_record_gate_enforces_ok 转 RED。
  - 洗白：把空 checks 补一条假 pass（whitewash）→ 坏 run 被洗白过门 →
    test_bad_run_missing_consistency_check_enforces_reject 转 RED。
  两者还原 → GREEN。证明 builder 忠实搬运 ConsistencyCheck·漏报/洗白都被对抗测试抓。
"""

from __future__ import annotations

import pytest

# 冷导入预热（既有循环·非本卡引入）：导入 app.governance.* 前先全载 orchestrator 解环——与
# test_section6_mathchain_gate.py / test_promote_gate_chain.py 同款顺序。
import app.agent.orchestrator  # noqa: F401  (prime: 解 app.governance 既有冷导入循环)

from app.governance.enforcement_policy import (  # noqa: E402
    MODE_ADVISORY,
    MODE_ENFORCE,
    ProducerStatusLedger,
)
from app.lineage.spine import (  # noqa: E402
    PROOF_BACKED,
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
from app.research_os.spine import (  # noqa: E402
    Section6PromotionClaim,
    Section6RecordError,
    build_section6_mathchain_record,
)

# ════════════════════════════════════════════════════════════════════════════
# typed 对象工厂（canonical lineage.spine flavor·= evaluate_promotion 直接裁定那套）
# ════════════════════════════════════════════════════════════════════════════
def _artifact(**overrides) -> MathematicalArtifact:
    base = dict(
        artifact_type="factor_formula",
        statement="IC(x) 定义",
        definition="x = a / b",
        derivation="由 ... 推得",
    )
    base.update(overrides)
    return MathematicalArtifact(**base)


def _binding(**overrides) -> TheoryImplementationBinding:
    base = dict(
        theory_ref="theory::alpha_x",
        code_ref="factors/alpha_x.py",
        code_content_hash="hash::v1",
        config_ref="cfg::alpha_x",
        data_contract_ref="dc::alpha_x",
        test_refs=("test::alpha_x",),
    )
    base.update(overrides)
    return TheoryImplementationBinding(**base)


def _check(**overrides) -> ConsistencyCheck:
    base = dict(binding_id="b1", check_type="numerical", result="pass")
    base.update(overrides)
    return ConsistencyCheck(**base)


def _compliant_claim() -> Section6PromotionClaim:
    """完整诚实 evidence_sufficient 升级 claim（过 evaluate_promotion 全部相关子句·非 PIT/非 proof-requiring）。"""

    return Section6PromotionClaim(
        requested_label="evidence_sufficient",
        asset_ref="factor::alpha_x",
        artifact=_artifact(),
        binding=_binding(),
        consistency_checks=(_check(),),
    )


def _bad_claim_missing_check() -> Section6PromotionClaim:
    """坏 run：声称 evidence_sufficient（强标签）+ 完整 binding，却**缺 ConsistencyCheck**（监控/执行称数学
    依据缺 CC → 拒·§8 consistency-present）。其余与合规 claim 同——隔离出「缺 check」这一条。"""

    return Section6PromotionClaim(
        requested_label="evidence_sufficient",
        asset_ref="factor::broken",
        artifact=_artifact(),
        binding=_binding(),
        consistency_checks=(),  # ← 缺 ConsistencyCheck（坏点）
    )


# ════════════════════════════════════════════════════════════════════════════
# manifest / 门链 helper
# ════════════════════════════════════════════════════════════════════════════
def _manifest(record) -> dict:
    """真 promote manifest 形：record=None 时**不发** section key（honest-absent·中心 `_take` 同款）。"""

    m = {"run_id": "ide_promote_s6_producer_test", "status": "completed"}
    if record is not None:
        m[SECTION6_MATHCHAIN_MANIFEST_KEY] = record
    return m


def _green_ledger() -> ProducerStatusLedger:
    led = ProducerStatusLedger()
    led.mark_green(SECTION6_MATHCHAIN_PRODUCER_KEY)  # 仅本卡测试态·绝非生产假绿灯
    return led


def _s6_verdict(result: ChainResult):
    matches = [v for v in result.verdicts if v.gate_name == SECTION6_MATHCHAIN_GATE_NAME]
    assert len(matches) == 1, "门链中应恰有一道 §6 数学链门裁定"
    return matches[0]


def _has_clause(cr: GateCheckResult, token: str) -> bool:
    return any(token in m for m in cr.missing)


# ════════════════════════════════════════════════════════════════════════════
# ① 合规 theory-backed run → build → producer 绿 → 门 ENFORCE 仍 ok=True（不误拒诚实 run）
# ════════════════════════════════════════════════════════════════════════════
def test_compliant_run_builds_record_gate_enforces_ok():
    """★ 接线①（mutation 目标）：合规 run → build record → producer 绿 → §6 门 ENFORCE 仍 ok=True。"""

    record = build_section6_mathchain_record([_compliant_claim()])
    assert record is not None
    assert "promotion_claims" in record and len(record["promotion_claims"]) == 1

    # check 层直读：合规数学链 → ok=True·无 missing
    cr = section6_mathchain_check(_manifest(record))
    assert isinstance(cr, GateCheckResult)
    assert cr.ok is True and cr.missing == ()

    # 门链层：producer 绿 → ENFORCE·合规 run 不被误拒（enforce 不误伤诚实 run）
    chain = PromoteGateChain()
    register_section6_mathchain_gate(chain)
    result = chain.evaluate(_manifest(record), producer_status=_green_ledger())
    assert result.rejected is False, "producer 绿 + 合规数学链 → 整链必须放行（不误拒）"
    v = _s6_verdict(result)
    assert v.advisory_or_enforce == MODE_ENFORCE
    assert v.ok is True and v.blocks is False


# ════════════════════════════════════════════════════════════════════════════
# ② 坏 run（强标签缺 ConsistencyCheck）→ build → producer 绿 → 门 ENFORCE 拒 ok=False（有牙）
# ════════════════════════════════════════════════════════════════════════════
def test_bad_run_missing_consistency_check_enforces_reject():
    """★ 接线②（mutation 目标）：坏 run（强标签缺 ConsistencyCheck）→ build → producer 绿 → 门拒 ok=False。"""

    record = build_section6_mathchain_record([_bad_claim_missing_check()])
    assert record is not None

    # check 层：缺 check → ok=False·命中 consistency-present
    cr = section6_mathchain_check(_manifest(record))
    assert cr.ok is False
    assert _has_clause(cr, "consistency-present")

    # 门链层：producer 绿 → ENFORCE 真拒（blocks·整链 rejected）
    chain = PromoteGateChain()
    register_section6_mathchain_gate(chain)
    result = chain.evaluate(_manifest(record), producer_status=_green_ledger())
    assert result.rejected is True, "producer 绿 + 残缺数学链 → 整链必须拒晋级（有牙）"
    v = _s6_verdict(result)
    assert v.advisory_or_enforce == MODE_ENFORCE
    assert v.ok is False and v.blocks is True
    assert v.producer_key == SECTION6_MATHCHAIN_PRODUCER_KEY
    assert any("consistency-present" in m for m in v.missing)


# ════════════════════════════════════════════════════════════════════════════
# ③ honest-absent（无 theory 声明）→ record=None → section 不发 → 门 ok=True（不误拒）
# ════════════════════════════════════════════════════════════════════════════
def test_honest_absent_no_claims_builds_none_gate_ok():
    """★ 接线③：无 theory 声明 → build record=None → 中心不发 section → 门 ok=True（honest-bound·不误拒）。"""

    record = build_section6_mathchain_record([])
    assert record is None, "honest-absent：无 claim → None（中心 `_take` 不发该 section key）"

    # 中心不发 section → manifest 无 §6 key → 门 honest-bound ok=True
    cr = section6_mathchain_check(_manifest(record))
    assert cr.ok is True and cr.missing == ()

    # 门链层：即便 producer 绿（ENFORCE），无声明也不被误拒（未声明≠违例）
    chain = PromoteGateChain()
    register_section6_mathchain_gate(chain)
    result = chain.evaluate(_manifest(record), producer_status=_green_ledger())
    assert result.rejected is False
    v = _s6_verdict(result)
    assert v.advisory_or_enforce == MODE_ENFORCE and v.ok is True and v.blocks is False


# ════════════════════════════════════════════════════════════════════════════
# ④ producer 红时坏 run → advisory：只记录不阻断（flip_refused·绝不误拒诚实 run）
# ════════════════════════════════════════════════════════════════════════════
def test_red_producer_bad_run_advisory_only_not_blocking():
    """★ 接线④：producer 红（出厂默认）+ 坏 run → §6 门 advisory：记录但**不**阻断（flip_refused）。"""

    record = build_section6_mathchain_record([_bad_claim_missing_check()])
    chain = PromoteGateChain()
    register_section6_mathchain_gate(chain)

    # producer 红（空 ledger·= 生产默认未接线态）
    result = chain.evaluate(_manifest(record), producer_status=ProducerStatusLedger())
    assert result.rejected is False, "producer 未绿 → §6 门只 advisory·绝不阻断"
    v = _s6_verdict(result)
    assert v.advisory_or_enforce == MODE_ADVISORY
    assert v.flip_refused is True, "拒翻必须被记录（非静默）"
    assert v.ok is False and v.blocks is False, "门诚实记下未过·但 advisory 不阻断"
    assert v in result.advisories

    # producer_status=None（生产默认）同款 advisory（无假绿灯）
    result_none = chain.evaluate(_manifest(record), producer_status=None)
    v_none = _s6_verdict(result_none)
    assert v_none.advisory_or_enforce == MODE_ADVISORY
    assert v_none.producer_green is False and v_none.blocks is False


# ════════════════════════════════════════════════════════════════════════════
# 复用证明：built record 经门裁定 == 直算 spine_gate.evaluate_promotion（faithful 往返·不另判）
# ════════════════════════════════════════════════════════════════════════════
def test_builder_roundtrip_matches_direct_evaluate_promotion():
    """复用不重造：built record 经门的 missing 逐条 == 直算 evaluate_promotion(同 typed 对象).violations。

    证明 builder 序列化无损往返（typed → dict → 门 `_adapt_*` 复原 → evaluate_promotion），且判定 100%
    来自单一源 spine_gate（builder 零判定·门零重写）。
    """

    art, bnd = _artifact(), _binding()
    # 坏 claim（缺 check）：门 missing 必逐条等于直算 violations
    bad = Section6PromotionClaim(
        requested_label="evidence_sufficient", asset_ref="factor::broken",
        artifact=art, binding=bnd, consistency_checks=(),
    )
    cr = section6_mathchain_check(_manifest(build_section6_mathchain_record([bad])))
    direct = evaluate_promotion(art, bnd, [], requested_label="evidence_sufficient")
    assert cr.ok is False and direct.promotable is False
    assert set(cr.missing) == set(direct.violations), \
        "门 missing 必逐条来自 canonical evaluate_promotion.violations（复用不重造·builder 零判定）"

    # 合规 claim：门 ok=True 当且仅当直算 promotable=True
    good_chk = _check()
    good = Section6PromotionClaim(
        requested_label="evidence_sufficient", asset_ref="factor::alpha_x",
        artifact=art, binding=bnd, consistency_checks=(good_chk,),
    )
    cr_good = section6_mathchain_check(_manifest(build_section6_mathchain_record([good])))
    direct_good = evaluate_promotion(art, bnd, [good_chk], requested_label="evidence_sufficient")
    assert cr_good.ok is True and direct_good.promotable is True


# ════════════════════════════════════════════════════════════════════════════
# no whitewash：坏 claim 缺 ConsistencyCheck → 序列化就缺（builder 绝不 fabricate 假 pass）
# ════════════════════════════════════════════════════════════════════════════
def test_builder_no_whitewash_missing_check_stays_absent():
    """记录层 no-whitewash：缺 ConsistencyCheck 的 claim → 序列化 dict **不含** consistency_checks key。

    若 builder 偷偷补一条假 pass check（洗白），这里就会冒出 consistency_checks → 门被骗过 = 假绿灯。
    钉死「缺即真缺」：builder 只忠实搬运·绝不为蒙混过门 fabricate 证据（守 GOAL §0 no-silent-mock）。
    """

    record = build_section6_mathchain_record([_bad_claim_missing_check()])
    claim_dict = record["promotion_claims"][0]
    assert "consistency_checks" not in claim_dict, \
        "缺 ConsistencyCheck 的 claim 绝不能被 builder 补出 consistency_checks（无 whitewash）"
    # 而合规 claim 必带真 check（对照：builder 在场即忠实序列化）
    good_dict = build_section6_mathchain_record([_compliant_claim()])["promotion_claims"][0]
    assert good_dict.get("consistency_checks") and len(good_dict["consistency_checks"]) == 1


# ════════════════════════════════════════════════════════════════════════════
# fail-closed：claim 携错 flavor / 错类型对象 → Section6RecordError（不静默吞坏输入）
# ════════════════════════════════════════════════════════════════════════════
def test_builder_failcloses_wrong_flavor_artifact():
    """fail-closed：claim.artifact 非 lineage.spine canonical 类型（plain dict）→ raise·不产骗门 dict。"""

    bad = Section6PromotionClaim(requested_label="evidence_sufficient", artifact={"fake": 1})  # type: ignore[arg-type]
    with pytest.raises(Section6RecordError):
        build_section6_mathchain_record([bad])


def test_builder_failcloses_wrong_typed_check():
    """fail-closed：consistency_checks 内含非 ConsistencyCheck 对象 → raise（不静默吞·不冒充真 check）。"""

    bad = Section6PromotionClaim(
        requested_label="evidence_sufficient", artifact=_artifact(), binding=_binding(),
        consistency_checks=({"binding_id": "b", "check_type": "numerical", "result": "pass"},),  # type: ignore[arg-type]
    )
    with pytest.raises(Section6RecordError):
        build_section6_mathchain_record([bad])


def test_builder_failcloses_non_claim_item():
    """fail-closed：claims 列表内含非 Section6PromotionClaim → raise（不静默吞坏输入）。"""

    with pytest.raises(Section6RecordError):
        build_section6_mathchain_record(["not-a-claim"])  # type: ignore[list-item]


def test_builder_failcloses_nonstr_requested_label_no_whitewash():
    """fail-closed（codex 复审 High·种坏必抓）：非 str requested_label → 构造即 raise·绝不被 str() 洗成弱标签放行。

    `['production_ready']` 这类非 str 强标签若被 builder `str()` 洗成 "['production_ready']"，门的 isinstance
    守卫不触发 → 当未知弱标签 promotable=True 放行（强晋级义务被类型洗白绕过 = 假绿灯）。在源头拒死。
    """

    for bad_label in (["production_ready"], 123, True, ("evidence_sufficient",)):
        with pytest.raises(Section6RecordError):
            Section6PromotionClaim(
                requested_label=bad_label,  # type: ignore[arg-type]
                artifact=_artifact(), binding=_binding(), consistency_checks=(_check(),),
            )


def test_builder_failcloses_none_claims_not_silent_absent():
    """fail-closed（codex 复审 Medium·种坏必抓）：claims=None → raise·绝不静默当 honest-absent 躲过判定。

    上游抽取失败返回 None 时，`list(claims or ())` 会把 None 洗成「无 claim」→ 返回 None → 门放行
    （fail-open：失败的抽取悄悄躲过门）。None ≠ 显式空声明 []，强制区分。空序列仍正常 honest-absent。
    """

    with pytest.raises(Section6RecordError):
        build_section6_mathchain_record(None)  # type: ignore[arg-type]
    # 对照：显式空序列仍是合法 honest-absent（返回 None·不 raise）
    assert build_section6_mathchain_record(()) is None
    assert build_section6_mathchain_record([]) is None


# ════════════════════════════════════════════════════════════════════════════
# 非常量门 + proof_status 携带证明（验证 lineage-flavor 选择）
# ════════════════════════════════════════════════════════════════════════════
def test_input_flip_flips_gate_ok_not_constant():
    """非常量：同一 claim 补回 ConsistencyCheck，门 ok 由 False 翻 True（builder 真传差异·门真读 evaluate）。"""

    bad = section6_mathchain_check(_manifest(build_section6_mathchain_record([_bad_claim_missing_check()])))
    good = section6_mathchain_check(_manifest(build_section6_mathchain_record([_compliant_claim()])))
    assert bad.ok is False and good.ok is True, "输入翻转 ok 必须跟着翻（非常量门·builder 忠实传差异）"


def test_proof_backed_compliant_carries_proof_status_passes():
    """proof_backed 合规过：proof_status=proof_backed + 完整链 → ok=True。

    证 builder 携 proof_status（lineage.spine flavor 有此字段·research_os flavor 无）——选 lineage canonical
    类型是对的：proof-requiring 标签的 proof-honest 子句要读 proof_status，序列化必须如实带上它。
    """

    claim = Section6PromotionClaim(
        requested_label="proof_backed", asset_ref="factor::proven",
        artifact=_artifact(proof_status=PROOF_BACKED),
        binding=_binding(),
        consistency_checks=(_check(),),
    )
    cr = section6_mathchain_check(_manifest(build_section6_mathchain_record([claim])))
    assert cr.ok is True, "proof_backed + proof_status=proof_backed + 完整链 → 过（builder 携 proof_status）"

    # 反证：同 claim 但 proof_status 缺省（unproven）→ proof-honest 拒（证 proof_status 真被门读）
    claim_unproven = Section6PromotionClaim(
        requested_label="proof_backed", asset_ref="factor::unproven",
        artifact=_artifact(),  # proof_status 默认 unproven
        binding=_binding(),
        consistency_checks=(_check(),),
    )
    cr2 = section6_mathchain_check(_manifest(build_section6_mathchain_record([claim_unproven])))
    assert cr2.ok is False and _has_clause(cr2, "proof-honest")


# ════════════════════════════════════════════════════════════════════════════
# 多 claim 聚合 + 强标签缺 binding（binding-exists 另一条牙）
# ════════════════════════════════════════════════════════════════════════════
def test_multiple_claims_one_bad_aggregates_reject():
    """聚合：一好一坏多 claim → 整体 ok=False·坏 claim asset_ref 进 reason（不漏不误·builder 忠实多条序列化）。"""

    good = _compliant_claim()
    bad = _bad_claim_missing_check()
    record = build_section6_mathchain_record([good, bad])
    assert len(record["promotion_claims"]) == 2
    cr = section6_mathchain_check(_manifest(record))
    assert cr.ok is False
    assert "factor::broken" in cr.reason


def test_strong_label_missing_binding_rejects():
    """坏 run 另一条牙：强标签缺 TheoryImplementationBinding → 门 ok=False·binding-exists（公式无 impl/test binding）。"""

    claim = Section6PromotionClaim(
        requested_label="evidence_sufficient", asset_ref="factor::nobinding",
        artifact=_artifact(), binding=None, consistency_checks=(_check(),),
    )
    record = build_section6_mathchain_record([claim])
    assert "binding" not in record["promotion_claims"][0], "缺 binding → 序列化就缺（无 whitewash）"
    cr = section6_mathchain_check(_manifest(record))
    assert cr.ok is False and _has_clause(cr, "binding-exists")
