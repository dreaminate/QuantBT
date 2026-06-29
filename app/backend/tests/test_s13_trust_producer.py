"""NC-S13-TRUST-PRODUCER · §13 信任结构 producer（trust_layer.build_section13_trust_record）· 对抗测试。

本卡（PARALLEL-SAFE）只建孤立 producer（`trust_layer.build_section13_trust_record`）+ 本测试，**不**碰
`promote_assembler`（中心 CENTER-SERIAL 串接）。producer = 真信任 typed 记录 → `section13_trust` manifest
section dict；信任判定全在 `section13_trust_gate.section13_trust_check → validate_trust_layer`（producer 零判定·
只 faithful 序列化）。

可证伪验收（wiring·producer→门链）：
  ① 合规 trust run → build → manifest[含 section13_trust] → producer 绿 → 门 ENFORCE 仍 ok=True（不误伤诚实 run）
  ② 坏 run（谄媚强结论 / mock 诚实违例）→ producer 绿 → 门 ENFORCE 拒（blocks·ok=False·精确码来自 canonical）
  ③ honest-absent（无信任结构）→ build 返回 {} → 不发 section → 门 ok=True（未声明≠违例·诚实限界）
  ④ producer 红 + 坏 run → advisory：记录不阻断（flip_refused·绝不误拒）
faithful（零洗白·零误拒）：build→门 的违例码集 == 同记录直喂 validate_trust_layer 的违例码集（往返等价·
  跨族同时验 → 误路由/丢字段/改值都会令本测试 RED）。
命门未削弱（GOAL §13）：silent_mock_fallback_used=True / user waiver 藏弱点 → asdict 全量 faithful 序列化 →
  门据真值拒（producer 绝不能洗白 no-silent-mock / 隐藏 user waiver）。
契约绑定（防漂·单一源在 gate）：producer family key 集 == section13_trust_gate._FAMILIES 的 manifest_key 集；
  producer 入参名 == validate_trust_layer 的 kwarg（= _FAMILIES 第二列）。
fail-closed：族喂错类型对象 → TypeError（不静默吞·不产骗门占位）。

★ mutation 三态（已手验·见任务报告）：把 trust_layer._serialize_trust_family 里
  `serialized = _json_value(rec)` 改成
  `serialized = {k: v for k, v in _json_value(rec).items() if k != "silent_mock_fallback_used"}`
  （producer 洗白 no-silent-mock 命门字段）→
  test_bad_mock_dishonesty_producer_green_enforce_rejects /
  test_mlock_silent_mock_faithfully_serialized_not_whitewashed 转 RED → 还原 → GREEN。
"""

from __future__ import annotations

import inspect

import pytest

# 冷导入预热（既有循环·非本卡引入）：导入 app.governance.* 前先全载 orchestrator 解环——与
# test_section13_trust_gate.py / test_promote_gate_chain.py 同款顺序。
import app.agent.orchestrator  # noqa: F401  (prime: 解 app.governance 既有冷导入循环)

from app.governance.enforcement_policy import (  # noqa: E402
    MODE_ADVISORY,
    MODE_ENFORCE,
    ProducerStatusLedger,
)
from app.release_gate.promote_gate_chain import (  # noqa: E402
    ChainResult,
    PromoteGateChain,
)
from app.release_gate.section13_trust_gate import (  # noqa: E402
    SECTION13_TRUST_GATE_NAME,
    SECTION13_TRUST_MANIFEST_KEY,
    SECTION13_TRUST_PRODUCER_KEY,
    _FAMILIES,
    register_section13_trust_gate,
    section13_trust_check,
)
from app.research_os.trust_layer import (  # noqa: E402
    ExternalExpertReviewRecord,
    TrustClaimLabel,
    TrustClaimRecord,
    TrustPressureRunRecord,
    TrustReleaseApprovalRecord,
    TrustReleaseCheckRecord,
    TrustReleaseGateRecord,
    _SECTION13_TRUST_FAMILY_TYPES,
    build_section13_trust_record,
    validate_trust_layer,
)


# ════════════════════════════════════════════════════════════════════════════
# 真信任 typed 记录构造器（producer 入参 = trust_layer canonical 类型·不另造）
# ════════════════════════════════════════════════════════════════════════════
def _clean_claim() -> TrustClaimRecord:
    """clean：强标签 + 证据齐 + 弱点可见 + 无 wishful + 无冷启动 → 无违例（typed 版 _clean_manifest）。"""

    return TrustClaimRecord(
        claim_ref="c::ok",
        claim_label=TrustClaimLabel.EVIDENCE_SUFFICIENT,
        evidence_refs=("e::ok",),
        weakness_refs=("w::disclosed",),
        weakness_visible_by_default=True,
        pressure_context="",
    )


def _sycophantic_claim() -> TrustClaimRecord:
    """坏：用户 wishful 施压 + agent 转强标签结论 → 隔离 wishful_pressure_strong_conclusion。"""

    return TrustClaimRecord(
        claim_ref="c::syco",
        claim_label=TrustClaimLabel.EVIDENCE_SUFFICIENT,
        evidence_refs=("e::1",),
        weakness_refs=(),
        weakness_visible_by_default=True,
        pressure_context="user is very wishful and wants a strong yes",
    )


def _mock_dishonest_check() -> TrustReleaseCheckRecord:
    """坏：发版 check 靠静默 mock 兜底（no-silent-mock 命门）→ 隔离 trust_release_check_silent_mock_fallback。"""

    return TrustReleaseCheckRecord(
        check_ref="chk::mock",
        release_ref="rel::1",
        check_kind="mock_honesty_check",
        scenario_ref="sc::1",
        expected_behavior_ref="beh::1",
        observed_behavior_ref="beh::1",
        verdict="passed",
        source_hash="h::1",
        evidence_refs=("e::1",),
        validation_result_refs=("v::1",),
        silent_mock_fallback_used=True,
    )


def _waiver_hidden_claim() -> TrustClaimRecord:
    """坏：user waiver 藏弱点（user_waiver_ref 在 + waiver_weakness_visible_by_default=False）。

    GOAL §13「不得隐藏 user waiver」命门 → 隔离 user_waived_weakness_hidden（label 非强·弱点本身可见）。
    """

    return TrustClaimRecord(
        claim_ref="c::waiver",
        claim_label=TrustClaimLabel.UNVERIFIED_RESULT,
        evidence_refs=(),
        weakness_refs=("w::tail",),
        weakness_visible_by_default=True,
        user_waiver_ref="waiver::001",
        waiver_weakness_visible_by_default=False,
    )


# —— 多族合规批（co-submitted·复用 test_section13_trust_gate 证清的字段值·跨记录解析全 resolve）——
def _clean_review() -> ExternalExpertReviewRecord:
    return ExternalExpertReviewRecord(
        review_ref="expert_review:s13p:v1",
        release_ref="release:s13p:v1",
        reviewer_ref="expert:independent_reviewer",
        reviewer_independence_ref="independence:expert:001",
        artifact_ref="rdp_package:s13p:v1",
        review_protocol_ref="protocol:review:v1",
        verdict="approved",
        source_hash="sha256:review",
        evidence_refs=("evidence:review",),
        signed_attestation_ref="attestation:review:001",
    )


def _clean_pressure_run() -> TrustPressureRunRecord:
    return TrustPressureRunRecord(
        runner_ref="trust_pressure_run:s13p:v1",
        release_ref="release:s13p:v1",
        runner_mode="local_deterministic",
        source_hash="sha256:pressure-run",
        release_gate_ref="release:s13p:v1",
        check_refs=("ck:1", "ck:2", "ck:3", "ck:4", "ck:5", "ck:6"),
        scenario_refs=("sc:1", "sc:2", "sc:3", "sc:4", "sc:5", "sc:6"),
        evidence_refs=("evidence:pressure-run",),
        validation_result_refs=("pytest:pressure-run",),
    )


def _clean_gate() -> TrustReleaseGateRecord:
    return TrustReleaseGateRecord(
        release_ref="release:s13p:v1",
        anti_flattery_pressure_test_ref="trust_test:anti_flattery",
        multi_turn_pressure_test_ref="trust_test:multi_turn",
        expert_veto_ref="expert_veto:001",
        weakness_collapse_check_ref="weakness_check:001",
        mock_honesty_check_ref="mock_check:001",
        cold_start_honesty_check_ref="cold_start_check:001",
    )


def _clean_approval() -> TrustReleaseApprovalRecord:
    return TrustReleaseApprovalRecord(
        approval_ref="trust_release_approval:s13p:v1",
        release_ref="release:s13p:v1",
        release_gate_ref="release:s13p:v1",
        pressure_run_ref="trust_pressure_run:s13p:v1",
        expert_review_ref="expert_review:s13p:v1",
        artifact_ref="rdp_package:s13p:v1",
        approval_protocol_ref="protocol:approval:v1",
        verdict="approved",
        source_hash="sha256:approval",
        evidence_refs=("evidence:approval",),
        signed_approval_ref="attestation:approval:001",
    )


# —— 门链脚手架（复用 SA-3/SA-2·镜像 test_section13_trust_gate）——
def _manifest(record: dict | None) -> dict:
    m = {"run_id": "ide_promote_test", "status": "completed"}
    if record:  # honest-absent：build 返回 {} → 不发 section（镜像中心 _take 的 `if payload`）
        m[SECTION13_TRUST_MANIFEST_KEY] = record
    return m


def _green_ledger() -> ProducerStatusLedger:
    led = ProducerStatusLedger()
    led.mark_green(SECTION13_TRUST_PRODUCER_KEY)
    return led


def _s13_verdict(result: ChainResult):
    matches = [v for v in result.verdicts if v.gate_name == SECTION13_TRUST_GATE_NAME]
    assert len(matches) == 1, "门链中应恰有一道 §13 信任门裁定"
    return matches[0]


def _codes(decision) -> set[str]:
    return {v.code for v in decision.violations}


# ════════════════════════════════════════════════════════════════════════════
# ① 合规 run → producer 绿 → 门 ENFORCE 仍 ok=True（不误伤诚实 run）
# ════════════════════════════════════════════════════════════════════════════
def test_compliant_claim_producer_green_enforce_passes():
    """★ 合规 trust 单 claim → build → manifest → producer 绿 → 整链 ENFORCE 不拒（门 ok=True）。"""

    record = build_section13_trust_record(claims=(_clean_claim(),))
    assert SECTION13_TRUST_MANIFEST_KEY not in record  # record 是 section 体·不含顶层 key
    assert record["trust_claims"], "合规 claim 必序列化进 trust_claims 族"

    chain = PromoteGateChain()
    register_section13_trust_gate(chain)
    result = chain.evaluate(_manifest(record), producer_status=_green_ledger())

    assert result.rejected is False, "合规 run + producer 绿 → enforce 不得误拒"
    v = _s13_verdict(result)
    assert v.advisory_or_enforce == MODE_ENFORCE
    assert v.ok is True and v.blocks is False


def test_compliant_multifamily_producer_green_enforce_passes():
    """★ 合规多族批（claim + 专家评审 + 施压跑 + 发版门 + 审批·跨记录全 resolve）→ enforce 不拒。

    证 producer 跨 8 族 faithful 序列化不误伤诚实 run（含 approval 的 cross-record linkage 解析）。
    """

    record = build_section13_trust_record(
        claims=(_clean_claim(),),
        expert_reviews=(_clean_review(),),
        pressure_runs=(_clean_pressure_run(),),
        release_gates=(_clean_gate(),),
        release_approvals=(_clean_approval(),),
    )
    # 每族都发了 key（非空族 → 出现）
    for fam in ("trust_claims", "expert_reviews", "pressure_runs", "release_gates", "release_approvals"):
        assert fam in record, f"{fam} 应被序列化进 section"

    chain = PromoteGateChain()
    register_section13_trust_gate(chain)
    result = chain.evaluate(_manifest(record), producer_status=_green_ledger())
    assert result.rejected is False, "合规多族 run + producer 绿 → enforce 不得误拒"
    v = _s13_verdict(result)
    assert v.advisory_or_enforce == MODE_ENFORCE and v.ok is True


# ════════════════════════════════════════════════════════════════════════════
# ② 坏 run → producer 绿 → 门 ENFORCE 拒（blocks）
# ════════════════════════════════════════════════════════════════════════════
def test_bad_sycophantic_producer_green_enforce_rejects():
    """★ 谄媚强结论 run → producer 绿 → 整链 ENFORCE 拒（blocks·ok=False·wishful_pressure_strong_conclusion）。"""

    record = build_section13_trust_record(claims=(_sycophantic_claim(),))
    chain = PromoteGateChain()
    register_section13_trust_gate(chain)
    result = chain.evaluate(_manifest(record), producer_status=_green_ledger())

    assert result.rejected is True, "producer 绿 + §13 谄媚违例 → 整链必须拒晋级"
    v = _s13_verdict(result)
    assert v.advisory_or_enforce == MODE_ENFORCE
    assert v.blocks is True and v.ok is False
    assert v.producer_key == SECTION13_TRUST_PRODUCER_KEY
    assert "wishful_pressure_strong_conclusion" in v.missing


def test_bad_mock_dishonesty_producer_green_enforce_rejects():
    """★（mutation 目标）mock 静默兜底 run → producer 绿 → ENFORCE 拒·trust_release_check_silent_mock_fallback。

    producer 若洗白 silent_mock_fallback_used（mutation）→ 门见不到 mock 旗 → 误判 ok=True → 本测试 RED。
    """

    record = build_section13_trust_record(release_checks=(_mock_dishonest_check(),))
    chain = PromoteGateChain()
    register_section13_trust_gate(chain)
    result = chain.evaluate(_manifest(record), producer_status=_green_ledger())

    assert result.rejected is True, "producer 绿 + mock 不诚实 → 整链必须拒晋级"
    v = _s13_verdict(result)
    assert v.advisory_or_enforce == MODE_ENFORCE
    assert v.blocks is True and v.ok is False
    assert "trust_release_check_silent_mock_fallback" in v.missing


# ════════════════════════════════════════════════════════════════════════════
# ③ honest-absent → build {} → 门 ok=True（未声明≠违例·诚实限界 RULES §3）
# ════════════════════════════════════════════════════════════════════════════
def test_honest_absent_build_returns_empty_dict():
    """诚实限界：无任何信任记录 → build 返回 {}（中心据 `if payload` 不发 section13_trust 节）。"""

    assert build_section13_trust_record() == {}
    # 中心 _take 语义：{} 为 falsy → 不并进 manifest（honest-absent）。
    m = _manifest(build_section13_trust_record())
    assert SECTION13_TRUST_MANIFEST_KEY not in m


def test_honest_absent_no_section_gate_ok():
    """honest-absent run（manifest 无 section13_trust）→ producer 绿也不误拒（门 ok=True·诚实限界）。"""

    chain = PromoteGateChain()
    register_section13_trust_gate(chain)
    result = chain.evaluate(_manifest(build_section13_trust_record()), producer_status=_green_ledger())
    assert result.rejected is False
    v = _s13_verdict(result)
    assert v.ok is True


def test_empty_families_emit_no_keys():
    """空族不发 key（honest-absent 粒度）：只给空 tuple → {}；混入一族真记录 → 只发该族 key。"""

    assert build_section13_trust_record(claims=(), release_checks=()) == {}
    only_claim = build_section13_trust_record(claims=(_clean_claim(),), release_checks=())
    assert set(only_claim) == {"trust_claims"}, "空 release_checks 不得发 release_checks key"


# ════════════════════════════════════════════════════════════════════════════
# ④ producer 红 + 坏 run → advisory：记录不阻断（flip_refused·绝不误拒）
# ════════════════════════════════════════════════════════════════════════════
def test_bad_run_producer_red_advisory_only_not_blocking():
    """★ 坏 run（谄媚）+ producer 红/缺 → advisory：门记下未过但**不**阻断（flip_refused·诚实不误拒）。"""

    record = build_section13_trust_record(claims=(_sycophantic_claim(),))
    chain = PromoteGateChain()
    register_section13_trust_gate(chain)
    result = chain.evaluate(_manifest(record), producer_status=ProducerStatusLedger())  # 空账=producer 红

    assert result.rejected is False, "producer 未绿 → §13 门只 advisory·绝不阻断"
    v = _s13_verdict(result)
    assert v.advisory_or_enforce == MODE_ADVISORY
    assert v.flip_refused is True, "拒翻必须被记录（非静默）"
    assert v.ok is False and v.blocks is False, "门诚实记下未过·但 advisory 不阻断"
    assert v in result.advisories


# ════════════════════════════════════════════════════════════════════════════
# faithful 往返等价（零洗白·零误拒·跨族同时验·误路由/丢字段/改值即 RED）
# ════════════════════════════════════════════════════════════════════════════
def test_faithful_roundtrip_codes_equal_direct_validation():
    """faithful 证明：build→门 的违例码集 == 同记录直喂 validate_trust_layer 的违例码集（多族同验）。

    误路由（族放错 key）/ 丢字段 / 改值 任一 → 两侧码集不等 → RED。
    """

    syco, mock, waiver = _sycophantic_claim(), _mock_dishonest_check(), _waiver_hidden_claim()
    record = build_section13_trust_record(claims=(syco, waiver), release_checks=(mock,))
    gate_missing = set(section13_trust_check({SECTION13_TRUST_MANIFEST_KEY: record}).missing)

    direct = validate_trust_layer(claims=(syco, waiver), release_checks=(mock,))
    direct_codes = _codes(direct)

    assert gate_missing == direct_codes, (
        f"producer 序列化须 faithful（往返等价）：门={gate_missing} vs 直算={direct_codes}"
    )
    # 三条违例都在（谄媚 / mock 不诚实 / user waiver 藏弱点）——证序列化无洗白。
    assert {
        "wishful_pressure_strong_conclusion",
        "trust_release_check_silent_mock_fallback",
        "user_waived_weakness_hidden",
    } <= gate_missing


def test_faithful_clean_roundtrip_no_violation():
    """faithful 反向：合规多族批 build→门 无违例（== 直算 accepted）——证序列化不凭空造误拒。"""

    families = dict(
        claims=(_clean_claim(),),
        expert_reviews=(_clean_review(),),
        pressure_runs=(_clean_pressure_run(),),
        release_gates=(_clean_gate(),),
        release_approvals=(_clean_approval(),),
    )
    record = build_section13_trust_record(**families)
    cr = section13_trust_check({SECTION13_TRUST_MANIFEST_KEY: record})
    direct = validate_trust_layer(**families)
    assert cr.ok is True and cr.missing == ()
    assert direct.accepted is True


def test_claim_label_enum_serialized_to_value_not_repr():
    """faithful 细节（强标签门成败所系）：enum claim_label 序列化为 .value（'evidence_sufficient'），

    非 str(enum)（'TrustClaimLabel.EVIDENCE_SUFFICIENT'）——后者会逃出 STRONG_CLAIMS 静默放过谄媚/缺证据。
    """

    record = build_section13_trust_record(claims=(_clean_claim(),))
    label = record["trust_claims"][0]["claim_label"]
    assert label == "evidence_sufficient", f"enum 须序列化为 value·得到 {label!r}"
    assert "TrustClaimLabel" not in label


# ════════════════════════════════════════════════════════════════════════════
# 命门未削弱（GOAL §13·producer 绝不能洗白）
# ════════════════════════════════════════════════════════════════════════════
def test_mlock_silent_mock_faithfully_serialized_not_whitewashed():
    """★（mutation 目标）no-silent-mock 命门：silent_mock_fallback_used=True 必 faithful 落 dict（True）。

    producer 若丢/改该字段 → 序列化层洗白 mock 不诚实 → 本断言 RED（命门被 producer 削弱即抓）。
    """

    record = build_section13_trust_record(release_checks=(_mock_dishonest_check(),))
    serialized = record["release_checks"][0]
    assert "silent_mock_fallback_used" in serialized, "命门字段绝不能被 producer 丢掉（丢=洗白）"
    assert serialized["silent_mock_fallback_used"] is True, "命门字段值绝不能被 producer 改（改=洗白）"


def test_mlock_user_waiver_hidden_faithfully_serialized():
    """命门：user waiver 藏弱点字段 faithful 落 dict → 门据真值判 user_waived_weakness_hidden（不被 producer 隐藏）。"""

    record = build_section13_trust_record(claims=(_waiver_hidden_claim(),))
    serialized = record["trust_claims"][0]
    assert serialized["user_waiver_ref"] == "waiver::001"
    assert serialized["waiver_weakness_visible_by_default"] is False
    cr = section13_trust_check({SECTION13_TRUST_MANIFEST_KEY: record})
    assert cr.ok is False and "user_waived_weakness_hidden" in cr.missing


# ════════════════════════════════════════════════════════════════════════════
# 契约绑定（防漂·单一源在 section13_trust_gate）+ fail-closed
# ════════════════════════════════════════════════════════════════════════════
def test_contract_family_keys_match_gate_single_source():
    """防漂：producer family key 集 == section13_trust_gate._FAMILIES 的 manifest_key 集。

    gate 改任一 family key（重命名 / 增删族）→ 本断言立刻 RED → 强制 producer 同步（单一源不漂）。
    """

    producer_keys = {k for k, _ in _SECTION13_TRUST_FAMILY_TYPES}
    gate_keys = {fam[0] for fam in _FAMILIES}
    assert producer_keys == gate_keys, f"producer↔gate family key 漂移：{producer_keys ^ gate_keys}"


def test_contract_builder_params_match_validate_trust_layer_kwargs():
    """防漂：producer 入参名 == validate_trust_layer 的 kwarg（= _FAMILIES 第二列）——族路由不串。"""

    params = {p for p in inspect.signature(build_section13_trust_record).parameters}
    gate_kwargs = {fam[1] for fam in _FAMILIES}
    assert params == gate_kwargs, f"producer 入参↔validate kwarg 漂移：{params ^ gate_kwargs}"


def test_failclosed_wrong_type_in_family_raises():
    """fail-closed：某族喂非该族 canonical 类型对象 → TypeError（不静默吞·不产骗门占位 dict）。"""

    with pytest.raises(TypeError):
        build_section13_trust_record(claims=(_mock_dishonest_check(),))  # check 塞进 claims 族
    with pytest.raises(TypeError):
        build_section13_trust_record(release_checks=({"check_ref": "raw-dict"},))  # 裸 dict 非 typed 记录


def test_failclosed_does_not_whitewash_bad_record_into_clean():
    """fail-closed 闭环：坏 record 经 producer 后门仍拒（producer 不预判/不过滤违例·零洗白）。

    谄媚 claim 直接 build → 门 ENFORCE（绿 producer）拒——证 producer 没把坏 record 洗成合规。
    """

    record = build_section13_trust_record(claims=(_sycophantic_claim(),))
    cr = section13_trust_check({SECTION13_TRUST_MANIFEST_KEY: record})
    assert cr.ok is False, "producer 绝不能把坏 record 序列化成『门看着合规』"
