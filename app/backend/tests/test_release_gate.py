"""发版门禁 · §16 工程标准 release gate【对抗式】测试（卡 D-RELEASE-GATE · 北极星总闸）。

验收标准（RULES §2）：不是「测函数跑通」，而是「种一个已知的坏门，release gate 必须抓住，
否则门是纸做的」。卡可证伪验收 5 条逐条种坏：

  ① silent mock fallback / template false success → 拒（MUT：补回标识/原因/降级即必绿）
  ② proof-backed 缺 TheoryImplementationBinding → 拒；theory promotion 缺 ConsistencyCheck → 拒
  ③ user-waived 缺 MethodologyChoiceRecord → 拒
  ④ LLM 未经 Gateway / LLMCallRecord 缺字段 → 拒
  ⑤ 全标准齐 → 放行（正路径不误伤）

外加：收编已建门的对抗（Verifier blocked / Approval 非 approved / RDP 未过 §17 → 拒）+ 安全红线
（明文 secret 进账 → 撞即停 raise）+ 单一源复用证据（不另造一致性/必填判定）。

把任一门改弱（放过缺标准）→ 对应断言立刻转红。
"""

from __future__ import annotations

import pytest

from app.lineage.ids import content_hash
from app.lineage.spine import (
    ARTIFACT_RISK_MEASURE,
    PROOF_BACKED,
    ConsistencyCheck,
    MathematicalArtifact,
    MethodologyChoiceRecord,
    TheoryImplementationBinding,
)
from app.llm.call_record import (
    LLMCallRecord,
    ReplayState,
    SecretLeakError,
    seal_record,
)
from app.release_gate import (
    GATE_APPROVAL,
    GATE_DATASET_VERSION,
    GATE_LLM_GATEWAY,
    GATE_METHODOLOGY_CHOICE,
    GATE_MOCK_HONESTY,
    GATE_RDP,
    GATE_SPINE_CONSISTENCY,
    GATE_VERIFIER,
    ExecutionBlock,
    MockHonestyError,
    ReleaseCandidate,
    ReleaseRejected,
    evaluate_release,
    require_releasable,
)
from app.release_gate.mock_honesty import (
    FALLBACK_NO_REASON,
    GRADE_EXPLORATORY,
    GRADE_NONE,
    GRADE_PRODUCTION,
    LIVE_NO_SOURCE,
    MOCK_UNMARKED,
    MODE_FALLBACK,
    MODE_LIVE,
    MODE_MOCK,
    MODE_TEMPLATE,
    PRODUCTION_VIA_NON_LIVE,
    TEMPLATE_FALSE_SUCCESS,
)

GW_SECRET = b"gateway-nonce-32-bytes-test-00000"


# ════════════════════════════════════════════════════════════════════════════
# 建料：合法治理工件（happy-path 全标准齐 · 各对抗从此 mutate）
# ════════════════════════════════════════════════════════════════════════════
def _good_spine() -> tuple[MathematicalArtifact, TheoryImplementationBinding, ConsistencyCheck, str]:
    code_src = "def var(returns, alpha): return -quantile(returns, alpha)"
    ch = content_hash(code_src)
    art = MathematicalArtifact(
        artifact_type=ARTIFACT_RISK_MEASURE,
        statement="VaR_alpha(X)",
        definition="alpha-quantile of loss",
        derivation="by definition of the alpha quantile of the loss distribution",
        proof_status=PROOF_BACKED,
    )
    tib = TheoryImplementationBinding(
        theory_ref=art.artifact_id,
        code_ref="app/risk/var.py",
        code_content_hash=ch,
        config_ref="cfg:var:1",
        data_contract_ref="dc:returns:1",
        test_refs=("tests/test_var.py::test_var",),
    )
    cc = ConsistencyCheck(
        binding_id=tib.binding_id,
        check_type="numerical",
        result="pass",
        expected_property="empirical VaR matches closed-form on gaussian",
        observed_property="match within 1e-6",
    )
    return art, tib, cc, ch


def _sealed_record(call_id: str = "call:1") -> LLMCallRecord:
    prompt_hash = "1111111111111111"
    response_digest = "0123456789abcdef"
    rec = LLMCallRecord(
        provider="anthropic",
        model="claude-x",
        auth_ref="secretref://anthropic/llm_anthropic",
        replay_state=ReplayState.REPLAYED.value,
        owner_user_id="owner-test",
        workflow_id="release-gate-test",
        invocation_id="release-gate-test",
        routing_policy_ref="routing:release:fixture-origin",
        routing_policy_state="replay_origin",
        call_id=call_id,
        prompt_digest=prompt_hash,
        prompt_hash=prompt_hash,
        tool_schema_hash="2222222222222222",
        response_digest=response_digest,
        response_ref=f"llm_response:{response_digest}",
        latency_ms=0.0,
        usage={"input_tokens": 12, "output_tokens": 5, "cost_usd": 0.0007},
        cost={
            "status": "reported", "currency": "USD", "amount": 0.0007,
            "source": "provider_usage_cost_usd", "reason": "",
        },
    )
    rec.seal = seal_record(rec, GW_SECRET)
    return rec


def _good_candidate(**overrides) -> ReleaseCandidate:
    """全 §16 标准齐的 proof_backed 发版候选（criterion ⑤ 基线·各对抗从此减字段）。"""

    art, tib, cc, ch = _good_spine()
    base = dict(
        asset_ref="factor:momentum:v3",
        asset_kind="factor",
        requested_label="proof_backed",
        execution_blocks=(
            ExecutionBlock(block_id="ingest", mode=MODE_LIVE, result_grade=GRADE_PRODUCTION,
                           live_source_ref="tushare://hs300/daily"),
            ExecutionBlock(block_id="probe", mode=MODE_MOCK, result_grade=GRADE_EXPLORATORY,
                           mock_marked=True),
        ),
        dataset_versions=(
            _DV("ds:hs300", "20240101T000000__abcd1234", "abcd1234deadbeef"),
        ),
        artifact=art,
        binding=tib,
        consistency_checks=(cc,),
        current_code_hash=ch,
        llm_used=True,
        llm_call_records=(_sealed_record(),),
        gateway_secret=GW_SECRET,
    )
    base.update(overrides)
    return ReleaseCandidate(**base)


class _DV:
    """duck-typed DatasetVersion stub（dataset_id/version_id/sha256）——免拉 polars 重依赖建真 DatasetVersion。"""

    def __init__(self, dataset_id: str, version_id: str, sha256: str) -> None:
        self.dataset_id = dataset_id
        self.version_id = version_id
        self.sha256 = sha256


# ════════════════════════════════════════════════════════════════════════════
# criterion ⑤：全标准齐 → 放行（正路径不误伤）—— 基线必绿，否则后续对抗无意义
# ════════════════════════════════════════════════════════════════════════════
def test_full_standards_release_not_misfired():
    v = evaluate_release(_good_candidate())
    assert v.ok, f"全标准齐却被误拒：{v.reason_text}"
    assert v.rejections == ()
    # require_releasable 在过门时原样返回（不抛）。
    cand = _good_candidate()
    assert require_releasable(cand) is cand


# ════════════════════════════════════════════════════════════════════════════
# ① Mock 诚实：silent mock fallback / template false success（5 条规则逐条种坏 + MUT）
# ════════════════════════════════════════════════════════════════════════════
def _has(v, gate_id, code_suffix):
    rej = [o for o in v.rejections if o.gate_id == gate_id]
    assert rej, f"门 {gate_id} 应拒却放行：{v.reason_text}"
    flat = ",".join(",".join(o.missing) for o in rej)
    assert code_suffix in flat, f"门 {gate_id} 拒了但未点出 {code_suffix}：{flat}"


def test_mock_silent_unmarked_rejected():
    """R1：mock 块未挂标识 → 拒（silent mock）。"""
    blk = ExecutionBlock(block_id="b", mode=MODE_MOCK, result_grade=GRADE_EXPLORATORY, mock_marked=False)
    v = evaluate_release(_good_candidate(execution_blocks=(blk,)))
    _has(v, GATE_MOCK_HONESTY, MOCK_UNMARKED)
    # MUT：挂上标识即必绿（门不是纸做的——补回标识就过）。
    fixed = ExecutionBlock(block_id="b", mode=MODE_MOCK, result_grade=GRADE_EXPLORATORY, mock_marked=True)
    assert evaluate_release(_good_candidate(execution_blocks=(fixed,))).ok


def test_fallback_silent_no_reason_rejected():
    """R2：fallback 块未显原因 → 拒（silent fallback）。"""
    blk = ExecutionBlock(block_id="b", mode=MODE_FALLBACK, result_grade=GRADE_EXPLORATORY, fallback_reason="")
    v = evaluate_release(_good_candidate(execution_blocks=(blk,)))
    _has(v, GATE_MOCK_HONESTY, FALLBACK_NO_REASON)
    fixed = ExecutionBlock(block_id="b", mode=MODE_FALLBACK, result_grade=GRADE_EXPLORATORY,
                           fallback_reason="primary provider 429, degraded to cached snapshot")
    assert evaluate_release(_good_candidate(execution_blocks=(fixed,))).ok


def test_live_block_no_source_rejected():
    """R3：live 块未声明 live source → 拒。"""
    blk = ExecutionBlock(block_id="b", mode=MODE_LIVE, result_grade=GRADE_PRODUCTION, live_source_ref="")
    v = evaluate_release(_good_candidate(execution_blocks=(blk,)))
    _has(v, GATE_MOCK_HONESTY, LIVE_NO_SOURCE)
    fixed = ExecutionBlock(block_id="b", mode=MODE_LIVE, result_grade=GRADE_PRODUCTION,
                           live_source_ref="binance://btcusdt/1m")
    assert evaluate_release(_good_candidate(execution_blocks=(fixed,))).ok


def test_template_false_production_success_rejected():
    """R4：template response 标 production success → 拒（no template false success）。"""
    blk = ExecutionBlock(block_id="b", mode=MODE_TEMPLATE, result_grade=GRADE_PRODUCTION)
    v = evaluate_release(_good_candidate(execution_blocks=(blk,)))
    _has(v, GATE_MOCK_HONESTY, TEMPLATE_FALSE_SUCCESS)
    # MUT：把 template 降到非生产等级即必绿（template 不进生产路径就诚实）。
    fixed = ExecutionBlock(block_id="b", mode=MODE_TEMPLATE, result_grade=GRADE_NONE)
    assert evaluate_release(_good_candidate(execution_blocks=(fixed,))).ok


def test_production_via_mock_fallback_rejected():
    """R5（致命）：生产结果走 mock/fallback → 拒（§16 致命：生产结果走 mock fallback）。"""
    blk = ExecutionBlock(block_id="b", mode=MODE_FALLBACK, result_grade=GRADE_PRODUCTION,
                         fallback_reason="provider down")  # 有原因但仍喂生产 → 致命
    v = evaluate_release(_good_candidate(execution_blocks=(blk,)))
    _has(v, GATE_MOCK_HONESTY, PRODUCTION_VIA_NON_LIVE)


def test_mock_mode_typo_fails_closed():
    """fail-closed：非法 mode（typo）构造即 raise——杜绝 typo 绕过分类静默放行。"""
    with pytest.raises(MockHonestyError):
        ExecutionBlock(block_id="b", mode="mok", result_grade=GRADE_PRODUCTION)
    with pytest.raises(MockHonestyError):
        ExecutionBlock(block_id="b", mode=MODE_MOCK, result_grade="prod")


@pytest.mark.parametrize(
    "blocks",
    (
        (),
        (
            ExecutionBlock(
                block_id="ide_sandbox",
                mode=MODE_MOCK,
                result_grade=GRADE_EXPLORATORY,
                mock_marked=True,
            ),
        ),
    ),
    ids=("missing_execution", "mock_exploratory_only"),
)
def test_production_ready_requires_live_production_execution(blocks):
    verdict = evaluate_release(
        _good_candidate(
            requested_label="production_ready",
            execution_blocks=blocks,
        )
    )

    mock_gate = [
        outcome
        for outcome in verdict.rejections
        if outcome.gate_id == GATE_MOCK_HONESTY
    ]
    assert len(mock_gate) == 1
    assert mock_gate[0].missing == (
        "production_ready:live_production_execution_block",
    )


def test_production_ready_accepts_live_production_with_marked_exploratory_probe():
    verdict = evaluate_release(
        _good_candidate(requested_label="production_ready")
    )

    mock_gate = [
        outcome
        for outcome in verdict.outcomes
        if outcome.gate_id == GATE_MOCK_HONESTY
    ][0]
    assert mock_gate.passed is True


def test_unknown_release_label_fails_closed_at_candidate_construction():
    with pytest.raises(ValueError, match="requested_label must be one of"):
        _good_candidate(requested_label="production-readi")


# ════════════════════════════════════════════════════════════════════════════
# ② proof-backed 缺 TIB → 拒；theory promotion 缺 ConsistencyCheck → 拒（委派 spine 单一源）
# ════════════════════════════════════════════════════════════════════════════
def test_proof_backed_missing_tib_rejected():
    art, _tib, cc, ch = _good_spine()
    v = evaluate_release(_good_candidate(binding=None, consistency_checks=(cc,)))
    rej = [o for o in v.rejections if o.gate_id == GATE_SPINE_CONSISTENCY]
    assert rej, f"proof_backed 缺 TIB 应拒：{v.reason_text}"
    assert any("binding-exists" in m for m in rej[0].missing), rej[0].missing


def test_theory_promotion_missing_consistency_check_rejected():
    v = evaluate_release(_good_candidate(consistency_checks=()))  # 有 TIB 但无 ConsistencyCheck
    rej = [o for o in v.rejections if o.gate_id == GATE_SPINE_CONSISTENCY]
    assert rej, f"theory 晋级缺 ConsistencyCheck 应拒：{v.reason_text}"
    assert any("consistency-present" in m for m in rej[0].missing), rej[0].missing


def test_weak_label_no_spine_obligation_not_misfired():
    """弱标签（draft）无 TIB/CC 义务 → spine 门不触发、不误伤。"""
    v = evaluate_release(
        ReleaseCandidate(asset_ref="factor:x", requested_label="draft")
    )
    spine = [o for o in v.outcomes if o.gate_id == GATE_SPINE_CONSISTENCY][0]
    assert spine.passed


# ════════════════════════════════════════════════════════════════════════════
# ③ user-waived 缺 MethodologyChoiceRecord → 拒
# ════════════════════════════════════════════════════════════════════════════
def test_user_waived_missing_mcr_rejected():
    v = evaluate_release(
        ReleaseCandidate(asset_ref="factor:x", requested_label="user_waived_theory",
                         methodology_choice=None)
    )
    rej = [o for o in v.rejections if o.gate_id == GATE_METHODOLOGY_CHOICE]
    assert rej and "methodology_choice" in rej[0].missing, v.reason_text


def test_user_waived_with_valid_mcr_passes():
    mcr = MethodologyChoiceRecord(
        chosen_path="user_waived_theory",
        asset_ref="factor:x",
        actor="dreaminate",
        skipped_steps=("formal_proof",),
        responsibility_boundary="user accepts theory not formally proven; exploratory only",
    )
    v = evaluate_release(
        ReleaseCandidate(asset_ref="factor:x", requested_label="user_waived_theory",
                         methodology_choice=mcr)
    )
    mc = [o for o in v.outcomes if o.gate_id == GATE_METHODOLOGY_CHOICE][0]
    assert mc.passed, mc.reason


def test_user_waived_methodology_cannot_claim_evidence_sufficient():
    mcr = MethodologyChoiceRecord(
        chosen_path="user_waived_theory",
        asset_ref="strategy:good",
        actor="dreaminate",
        skipped_steps=("formal_proof",),
        responsibility_boundary="user accepts exploratory-only status",
    )
    verdict = evaluate_release(
        _good_candidate(
            requested_label="evidence_sufficient",
            methodology_choice=mcr,
        )
    )
    spine_rejections = [
        outcome
        for outcome in verdict.rejections
        if outcome.gate_id == GATE_SPINE_CONSISTENCY
    ]
    assert spine_rejections
    assert "strong-label-honest" in spine_rejections[0].reason


def test_user_waived_mcr_wrong_asset_rejected():
    """张冠李戴：MCR 绑别的资产 → 拒。"""
    mcr = MethodologyChoiceRecord(
        chosen_path="user_waived_theory", asset_ref="factor:OTHER", actor="u",
        skipped_steps=("formal_proof",), responsibility_boundary="...",
    )
    v = evaluate_release(
        ReleaseCandidate(asset_ref="factor:x", requested_label="user_waived_theory",
                         methodology_choice=mcr)
    )
    rej = [o for o in v.rejections if o.gate_id == GATE_METHODOLOGY_CHOICE]
    assert rej and "methodology_choice.asset_ref" in rej[0].missing


def test_user_waived_mcr_missing_responsibility_boundary_rejected():
    """waiver 缺责任边界 → 拒（§16 致命：user waiver 不得展示成系统强证据）。"""
    mcr = MethodologyChoiceRecord(
        chosen_path="user_waived_theory", asset_ref="factor:x", actor="u",
        skipped_steps=("formal_proof",), responsibility_boundary="",
    )
    v = evaluate_release(
        ReleaseCandidate(asset_ref="factor:x", requested_label="user_waived_theory",
                         methodology_choice=mcr)
    )
    rej = [o for o in v.rejections if o.gate_id == GATE_METHODOLOGY_CHOICE]
    assert rej and "methodology_choice.responsibility_boundary" in rej[0].missing


# ════════════════════════════════════════════════════════════════════════════
# ④ LLM 未经 Gateway / LLMCallRecord 缺字段 → 拒
# ════════════════════════════════════════════════════════════════════════════
def test_llm_declared_used_but_no_record_rejected():
    v = evaluate_release(_good_candidate(llm_used=True, llm_call_records=(), gateway_secret=None))
    rej = [o for o in v.rejections if o.gate_id == GATE_LLM_GATEWAY]
    assert rej and "llm_call_records" in rej[0].missing, v.reason_text


def test_llm_record_missing_required_field_rejected():
    """LLMCallRecord 缺必填字段（auth_ref 空）→ 拒（复用单一源 assert_record_admissible）。"""
    bad = LLMCallRecord(provider="anthropic", model="claude-x", auth_ref="",
                        replay_state=ReplayState.LIVE.value, call_id="bad",
                        owner_user_id="owner-test", workflow_id="release-gate-test",
                        invocation_id="bad-auth", response_digest="0123456789abcdef")
    bad.seal = seal_record(bad, GW_SECRET)  # 封印有效但字段缺 → 仍拒
    v = evaluate_release(_good_candidate(llm_call_records=(bad,)))
    rej = [o for o in v.rejections if o.gate_id == GATE_LLM_GATEWAY]
    assert rej and any("admissible" in m for m in rej[0].missing), v.reason_text


def test_llm_bypassed_gateway_forged_seal_rejected():
    """未经 Gateway：账封印验不过 gateway_secret（自造账）→ 拒。"""
    forged = LLMCallRecord(provider="anthropic", model="claude-x",
                           auth_ref="secretref://anthropic/x",
                           replay_state=ReplayState.LIVE.value, call_id="forged",
                           owner_user_id="owner-test", workflow_id="release-gate-test",
                           invocation_id="forged", response_digest="0123456789abcdef")
    # 不盖封印（或盖错）——绕过 Gateway 自造账。
    v = evaluate_release(_good_candidate(llm_call_records=(forged,), gateway_secret=GW_SECRET))
    rej = [o for o in v.rejections if o.gate_id == GATE_LLM_GATEWAY]
    assert rej and any("seal" in m for m in rej[0].missing), v.reason_text


def test_llm_not_used_not_misfired():
    v = evaluate_release(
        ReleaseCandidate(asset_ref="factor:x", requested_label="draft", llm_used=False)
    )
    llm = [o for o in v.outcomes if o.gate_id == GATE_LLM_GATEWAY][0]
    assert llm.passed


def test_llm_cost_unlogged_is_soft_gap_not_hard_reject():
    """§16 列 cost·但单一源准入门不含——cost 未记作软披露不硬拒（不与单一源矛盾·不误伤封印真账）。"""
    rec = LLMCallRecord(provider="anthropic", model="claude-x",
                        auth_ref="secretref://anthropic/x",
                        replay_state=ReplayState.REPLAYED.value, call_id="nocost", usage={},
                        owner_user_id="owner-test", workflow_id="release-gate-test",
                        invocation_id="nocost",
                        routing_policy_ref="routing:release:fixture-origin",
                        routing_policy_state="replay_origin",
                        prompt_digest="1111111111111111",
                        prompt_hash="1111111111111111",
                        tool_schema_hash="2222222222222222",
                        response_digest="0123456789abcdef",
                        response_ref="llm_response:0123456789abcdef",
                        latency_ms=0.0,
                        cost={
                            "status": "unavailable", "currency": "USD", "amount": None,
                            "source": "none", "reason": "provider_cost_not_reported",
                        })
    rec.seal = seal_record(rec, GW_SECRET)
    v = evaluate_release(_good_candidate(llm_call_records=(rec,)))
    assert v.ok, f"cost 未记不该硬拒：{v.reason_text}"
    assert any("cost_unlogged" in g for g in v.honest_gaps), v.honest_gaps


def test_legacy_v2_record_is_rejected_by_formal_release_gate():
    legacy = _sealed_record()
    legacy.schema_version = 2
    legacy.routing_policy_ref = ""
    legacy.routing_policy_state = ""
    legacy.prompt_hash = ""
    legacy.tool_schema_hash = ""
    legacy.response_ref = ""
    legacy.cost = {}
    legacy.seal = seal_record(legacy, GW_SECRET)

    verdict = evaluate_release(_good_candidate(llm_call_records=(legacy,)))
    rejection = [item for item in verdict.rejections if item.gate_id == GATE_LLM_GATEWAY]
    assert rejection and any("admissible" in item for item in rejection[0].missing)


# ════════════════════════════════════════════════════════════════════════════
# ③ dataset_version + checksum（§16 ③）
# ════════════════════════════════════════════════════════════════════════════
def test_dataset_missing_version_rejected():
    v = evaluate_release(_good_candidate(dataset_versions=(_DV("ds:x", "", "abcd1234"),)))
    rej = [o for o in v.rejections if o.gate_id == GATE_DATASET_VERSION]
    assert rej and any("dataset_version" in m for m in rej[0].missing), v.reason_text


def test_dataset_missing_checksum_rejected():
    v = evaluate_release(_good_candidate(dataset_versions=(_DV("ds:x", "v1", ""),)))
    rej = [o for o in v.rejections if o.gate_id == GATE_DATASET_VERSION]
    assert rej and any("checksum" in m for m in rej[0].missing), v.reason_text


def test_dataset_version_ref_shape_accepted():
    """duck-type 兼容 delivery.DatasetVersionRef（version/manifest_sha256 字段名）。"""
    from app.delivery.rdp import DatasetVersionRef

    ref = DatasetVersionRef(dataset_id="ds:x", version="v1", manifest_sha256="deadbeef")
    v = evaluate_release(_good_candidate(dataset_versions=(ref,)))
    dsv = [o for o in v.outcomes if o.gate_id == GATE_DATASET_VERSION][0]
    assert dsv.passed, dsv.reason


# ════════════════════════════════════════════════════════════════════════════
# 安全红线：明文 secret 进 LLMCallRecord → 撞即停（raise SecretLeakError·不回显 secret）
# ════════════════════════════════════════════════════════════════════════════
def test_plaintext_secret_in_record_raises():
    leaky = LLMCallRecord(provider="anthropic", model="claude-x",
                          auth_ref="sk-LIVE-SECRET-abcdef123456",  # 明文 key 进账（红线）
                          replay_state=ReplayState.LIVE.value, call_id="leak",
                          owner_user_id="owner-test", workflow_id="release-gate-test",
                          invocation_id="leak", response_digest="0123456789abcdef")
    leaky.seal = seal_record(leaky, GW_SECRET)
    with pytest.raises(SecretLeakError) as ei:
        evaluate_release(_good_candidate(
            llm_call_records=(leaky,),
            known_secrets=("sk-LIVE-SECRET-abcdef123456",),
        ))
    assert "sk-LIVE-SECRET" not in str(ei.value)  # 绝不回显 secret 本身


# ════════════════════════════════════════════════════════════════════════════
# 收编已建门的对抗（Verifier / Approval / RDP 收编只读·种坏必抓）
# ════════════════════════════════════════════════════════════════════════════
def test_blocked_verifier_verdict_rejected():
    from app.verification.verifier import Verifier

    vr = Verifier().reconcile(
        target_ref="factor:momentum:v3",
        claims={"sharpe": 1.2}, recomputed={"sharpe": -0.8},  # 符号翻转 → blocked
        generator_model="gpt-4", checker_model="claude-3",
    )
    assert vr.verdict == "blocked"
    v = evaluate_release(_good_candidate(verifier_verdict=vr))
    rej = [o for o in v.rejections if o.gate_id == GATE_VERIFIER]
    assert rej, v.reason_text


def test_unapproved_approval_gate_rejected():
    from app.approval.schema import ApprovalGate

    gate = ApprovalGate(
        gate_id="g1", model_id="m", version=1, from_stage="staging", to_stage="production",
        channel="confirmatory", action_kind="promote_production", created_by="u",
        decision="rejected",
    )
    v = evaluate_release(_good_candidate(approval=gate))
    rej = [o for o in v.rejections if o.gate_id == GATE_APPROVAL]
    assert rej and "approval.decision" in rej[0].missing, v.reason_text


def test_invalid_rdp_rejected():
    from app.delivery.rdp import RDPManifest

    # 缺 artifact_hash / reproducibility_command / dataset / 残余 → §17 门拒。
    rdp = RDPManifest(asset_ref="factor:momentum:v3", asset_kind="factor")
    v = evaluate_release(_good_candidate(rdp=rdp))
    rej = [o for o in v.rejections if o.gate_id == GATE_RDP]
    assert rej, v.reason_text


# ════════════════════════════════════════════════════════════════════════════
# require_releasable：未过门 → raise ReleaseRejected（带结构化缺口）
# ════════════════════════════════════════════════════════════════════════════
def test_require_releasable_raises_on_reject():
    blk = ExecutionBlock(block_id="b", mode=MODE_MOCK, result_grade=GRADE_PRODUCTION, mock_marked=False)
    with pytest.raises(ReleaseRejected) as ei:
        require_releasable(_good_candidate(execution_blocks=(blk,)))
    assert ei.value.validation.rejections
    assert any(o.gate_id == GATE_MOCK_HONESTY for o in ei.value.validation.rejections)


def test_multiple_standards_missing_all_surfaced():
    """多标准同缺 → 全部 surface（不短路·缺陷面要完整）。"""
    blk = ExecutionBlock(block_id="b", mode=MODE_MOCK, result_grade=GRADE_PRODUCTION, mock_marked=False)
    v = evaluate_release(ReleaseCandidate(
        asset_ref="factor:x",
        requested_label="proof_backed",   # 触发 spine（缺 TIB）
        execution_blocks=(blk,),          # 触发 mock（silent + 生产）
        dataset_versions=(_DV("ds", "", ""),),  # 触发 dataset（缺 version+checksum）
        llm_used=True,                    # 触发 llm（无 record）
    ))
    rejected_gates = {o.gate_id for o in v.rejections}
    assert {GATE_MOCK_HONESTY, GATE_SPINE_CONSISTENCY, GATE_DATASET_VERSION, GATE_LLM_GATEWAY} <= rejected_gates
