"""promote 证据组装器【对抗式】测试（卡 wave10/promote-assembler · 北极星「不给假绿灯」对准组装器自己）。

验收口径（RULES §2）：不是「函数跑通」，而是「种一个已知的坏——组装器随手造个空 binding / 占位
checksum / 假执行块 / 静默丢组装输入——必须被抓」。卡可证伪验收 5 条逐条种坏：

  ① 缺 TIB 不编造 → proof-backed 时 binding 留 None + honest_gaps 钉 + evaluate 经 spine 门硬拒
  ② dataset 缺 → 诚实标缺（声明缺 checksum 不造占位 → gate 硬拒；无声明 → 软披露不静默吞）
  ③ mock/template/fallback 执行块（manifest 声明）经 R1/R4/R5 必拒；非法 mode 构造即 fail-closed
  ④ assembly_inputs 真透传不静默丢（一字不丢 + evaluate 的 honest_gaps surface）
  ⑤ 证据齐全正路径 ok=True 不误伤

核心非编造不变量（MUT 有牙）：缺证据 → 组装器留 None/()、绝不造占位蒙混过门。把组装器改弱（缺
checksum 造占位 / 缺 binding 造空壳）→ 对应断言立刻转红。
"""

from __future__ import annotations

import pytest

from app.delivery.rdp import DatasetVersionRef
from app.lineage.ids import content_hash
from app.lineage.spine import (
    ARTIFACT_RISK_MEASURE,
    LABEL_EXPLORATORY,
    PROOF_BACKED,
    ConsistencyCheck,
    MathematicalArtifact,
    MethodologyChoiceRecord,
    TheoryImplementationBinding,
)
from app.lineage.spine_ledger import _binding_payload, _check_payload, _choice_payload
from app.llm.call_record import (
    CallRecordKind,
    LLMCallRecord,
    ReplayState,
    make_call_id,
    seal_record,
)
from app.llm.call_record_store import LLMCallRecordStore
from app.release_gate import (
    GATE_DATASET_VERSION,
    GATE_METHODOLOGY_CHOICE,
    GATE_MOCK_HONESTY,
    GATE_SPINE_CONSISTENCY,
    ExecutionBlock,
    MockHonestyError,
    evaluate_release,
)
from app.release_gate.mock_honesty import (
    GRADE_EXPLORATORY,
    GRADE_NONE,
    GRADE_PRODUCTION,
    MOCK_UNMARKED,
    MODE_FALLBACK,
    MODE_LIVE,
    MODE_MOCK,
    MODE_TEMPLATE,
    PRODUCTION_VIA_NON_LIVE,
    TEMPLATE_FALSE_SUCCESS,
)
from app.release_gate.promote_assembler import (
    DEFAULT_REQUESTED_LABEL,
    AssembledRelease,
    AssemblyError,
    assemble,
    assemble_release_candidate,
    evaluate_run_releasable,
)

GW_SECRET = b"gateway-nonce-32-bytes-test-00000"


# ════════════════════════════════════════════════════════════════════════════
# 建料：真 run.json 形（镜像 ide.promote.promote_ide_run 写的 manifest）+ 全证据齐
# ════════════════════════════════════════════════════════════════════════════
def _run_manifest(**overrides) -> dict:
    """一份已 promote 的 IDE run 的 run.json（最小可识别字段·镜像 promote_ide_run）。"""

    m = {
        "run_id": "ide_alice_momentum_aB3x",
        "strategy_id": "ide_alice",
        "strategy_name": "动量基线",
        "started_at": "2026-01-01",
        "status": "completed",
        "market": "crypto_perp",
        "frequency": "1d",
        "benchmark": "BTC-USDT",
        "metrics": {"sharpe": 1.1, "total_return": 0.2},
        "source": {"kind": "ide_sandbox", "ide_run_id": "agentbt_crypto_perp",
                   "owner_username": "alice"},
    }
    m.update(overrides)
    return m


def _good_spine():
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
    response_digest = "0123456789abcdef"
    rec = LLMCallRecord(
        provider="anthropic",
        model="claude-x",
        auth_ref="secretref://anthropic/llm_anthropic",
        replay_state=ReplayState.REPLAYED.value,
        owner_user_id="owner-alice",
        workflow_id="ide_alice_momentum_aB3x",
        invocation_id="release-gate-test",
        routing_policy_ref="routing:promote:fixture-origin",
        routing_policy_state="replay_origin",
        call_id=call_id,
        prompt_digest="1111111111111111",
        prompt_hash="1111111111111111",
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


def _append_store_invocation(
    store: LLMCallRecordStore,
    *,
    owner_user_id: str,
    workflow_id: str,
    invocation_id: str,
) -> tuple[LLMCallRecord, LLMCallRecord]:
    common = dict(
        provider="anthropic",
        model="claude-x",
        auth_ref="secretref://anthropic/llm_anthropic",
        replay_state=ReplayState.LIVE.value,
        owner_user_id=owner_user_id,
        workflow_id=workflow_id,
        invocation_id=invocation_id,
        attempt_no=1,
        routing_policy_ref="routing:promote:test",
        routing_policy_state="configured_ref",
        prompt_digest="0123456789abcdef",
        prompt_hash="0123456789abcdef",
        tool_schema_hash="1111111111111111",
        response_digest="fedcba9876543210",
        response_ref="llm_response:fedcba9876543210",
        started_at="2026-07-12T00:00:00+00:00",
        finished_at="2026-07-12T00:00:01+00:00",
        latency_ms=1000.0,
        cost={
            "status": "unavailable", "currency": "USD", "amount": None,
            "source": "none", "reason": "provider_cost_not_reported",
        },
    )
    rows: list[LLMCallRecord] = []
    for kind in (CallRecordKind.ATTEMPT.value, CallRecordKind.TERMINAL.value):
        row = LLMCallRecord(
            **common,
            record_kind=kind,
            call_id=make_call_id(
                prompt_digest="",
                provider="",
                model="",
                role="",
                session_id="",
                seq=1,
                owner_user_id=owner_user_id,
                workflow_id=workflow_id,
                invocation_id=invocation_id,
                record_kind=kind,
                attempt_no=1,
            ),
        )
        row.seal = seal_record(row, store.seal_secret)
        store.append(row)
        rows.append(row)
    return rows[0], rows[1]


def _good_evidence() -> dict:
    """中心接真 promote 端点时【显式注入】的全证据（criterion ⑤ 基线·各对抗从此减字段）。"""

    art, tib, cc, ch = _good_spine()
    return dict(
        requested_label="proof_backed",
        execution_blocks=(
            ExecutionBlock(block_id="ingest", mode=MODE_LIVE, result_grade=GRADE_PRODUCTION,
                           live_source_ref="binance://btcusdt/1d"),
            ExecutionBlock(block_id="probe", mode=MODE_MOCK, result_grade=GRADE_EXPLORATORY,
                           mock_marked=True),
        ),
        dataset_versions=(
            DatasetVersionRef(dataset_id="ds:btc", version="20240101__abcd",
                              manifest_sha256="abcd1234deadbeef"),
        ),
        artifact=art,
        binding=tib,
        consistency_checks=(cc,),
        current_code_hash=ch,
        llm_used=True,
        llm_call_records=(_sealed_record(),),
        gateway_secret=GW_SECRET,
    )


# ════════════════════════════════════════════════════════════════════════════
# 身份映射：asset_ref = run_id（缺则 strategy_id）；两皆缺 → fail-closed
# ════════════════════════════════════════════════════════════════════════════
def test_asset_ref_from_run_id():
    asm = assemble(_run_manifest())
    assert asm.candidate.asset_ref == "ide_alice_momentum_aB3x"
    assert "asset_ref" in asm.mapped_fields


def test_asset_ref_falls_back_to_strategy_id():
    m = _run_manifest()
    m.pop("run_id")
    assert assemble(m).candidate.asset_ref == "ide_alice"


def test_missing_identity_fails_closed():
    m = _run_manifest()
    m.pop("run_id")
    m.pop("strategy_id")
    with pytest.raises(AssemblyError):
        assemble(m)


def test_non_mapping_manifest_rejected():
    with pytest.raises(AssemblyError):
        assemble(["not", "a", "mapping"])  # type: ignore[arg-type]


def test_default_label_is_weak_exploratory():
    """run.json 无升级标签 → 默认弱标签 exploratory（不编造晋级野心·不触发强证据门）。"""
    asm = assemble(_run_manifest())
    assert asm.candidate.requested_label == DEFAULT_REQUESTED_LABEL == LABEL_EXPLORATORY
    assert not asm.candidate.is_strong_label
    assert not asm.candidate.is_user_waived  # exploratory ∉ USER_WAIVED_LABELS → MCR 门不触发


@pytest.mark.parametrize(
    "bad_label",
    [[], {}, True, 1],
    ids=["list", "dict", "bool", "int"],
)
def test_explicit_requested_label_wrong_type_fails_closed(bad_label):
    """显式畸形标签不得经 _clean 静默降级为 exploratory。"""
    with pytest.raises(AssemblyError, match="requested_label parameter"):
        assemble(_run_manifest(), requested_label=bad_label)


@pytest.mark.parametrize(
    "bad_label",
    [[], {}, True, 1],
    ids=["list", "dict", "bool", "int"],
)
def test_manifest_requested_label_wrong_type_fails_closed(bad_label):
    """manifest 畸形标签不得被当成未声明而静默放过。"""
    with pytest.raises(AssemblyError, match="run_manifest.requested_label"):
        assemble(_run_manifest(requested_label=bad_label))


def test_blank_explicit_label_preserves_manifest_fallback():
    """空白显式标签沿用既有优先级：回退到 manifest 中的合法标签。"""
    asm = assemble(_run_manifest(requested_label="proof_backed"), requested_label="  ")
    assert asm.candidate.requested_label == "proof_backed"


# ════════════════════════════════════════════════════════════════════════════
# 对抗①：缺 TIB 不编造 → proof_backed 时 binding 留 None + 经 spine 门硬拒
# ════════════════════════════════════════════════════════════════════════════
def test_proof_backed_missing_binding_not_fabricated():
    manifest = _run_manifest()
    asm = assemble(manifest, requested_label="proof_backed")
    # 核心非编造不变量：缺 binding → 留 None（绝不造空壳蒙混）
    assert asm.candidate.binding is None
    assert "binding" in asm.absent_fields
    assert any("strong_label_without_binding" in g for g in asm.honest_gaps), asm.honest_gaps
    # 判定委派 evaluate_release：proof_backed 缺 TIB → spine 门硬拒（binding-exists）
    v = evaluate_run_releasable(manifest, requested_label="proof_backed")
    assert not v.ok
    rej = [o for o in v.rejections if o.gate_id == GATE_SPINE_CONSISTENCY]
    assert rej and any("binding-exists" in m for m in rej[0].missing), v.reason_text


def test_proof_backed_theory_promotion_missing_consistency_check_rejected():
    """有 TIB 但无 ConsistencyCheck（缺一致性证据·不编造一条 pass）→ spine 门硬拒。"""
    _art, tib, _cc, ch = _good_spine()
    manifest = _run_manifest()
    asm = assemble(manifest, requested_label="proof_backed", binding=tib, current_code_hash=ch)
    assert asm.candidate.consistency_checks == ()  # 不编造
    v = evaluate_release(asm.candidate)
    rej = [o for o in v.rejections if o.gate_id == GATE_SPINE_CONSISTENCY]
    assert rej and any("consistency-present" in m for m in rej[0].missing), v.reason_text


def test_weak_label_no_spine_obligation_not_misfired():
    """弱默认标签（exploratory）无 TIB/CC 义务 → spine 门不触发、不误伤。"""
    v = evaluate_run_releasable(_run_manifest())
    spine = [o for o in v.outcomes if o.gate_id == GATE_SPINE_CONSISTENCY][0]
    assert spine.passed, spine.reason


# ════════════════════════════════════════════════════════════════════════════
# 对抗②：dataset 缺 → 诚实标缺（声明缺 checksum 不造占位 → 硬拒；无声明 → 软披露）
# ════════════════════════════════════════════════════════════════════════════
def test_dataset_declared_without_checksum_not_fabricated():
    """manifest 声明 dataset 但缺 checksum → 映射成空 checksum（绝不造占位）→ gate 硬拒。"""
    manifest = _run_manifest(dataset_versions=[{"dataset_id": "ds:hs300", "version": "v1"}])
    asm = assemble(manifest)
    dv = asm.candidate.dataset_versions
    assert len(dv) == 1
    assert dv[0].manifest_sha256 == ""  # ← 核心非编造不变量：缺 checksum 留空，不造占位
    v = evaluate_run_releasable(manifest)
    assert not v.ok
    rej = [o for o in v.rejections if o.gate_id == GATE_DATASET_VERSION]
    assert rej and any("checksum" in m for m in rej[0].missing), v.reason_text


def test_dataset_version_id_sha256_shape_mapped():
    """duck-type DatasetVersion 字段名（version_id / sha256）也诚实映射。"""
    manifest = _run_manifest(
        dataset_versions=[{"dataset_id": "ds:x", "version_id": "v2", "sha256": "deadbeefcafe0000"}]
    )
    dv = assemble(manifest).candidate.dataset_versions
    assert dv[0].version == "v2" and dv[0].manifest_sha256 == "deadbeefcafe0000"
    assert evaluate_run_releasable(manifest).ok  # 身份齐 → dataset 门过


def test_dataset_absent_surfaced_as_honest_gap_not_silent():
    """run.json 无 dataset 身份 → 留空 + 软披露（gate 平凡过·但绝不静默吞缺口）。"""
    asm = assemble(_run_manifest())
    assert asm.candidate.dataset_versions == ()
    assert "dataset_versions" in asm.absent_fields
    assert any("dataset:identity_unrecorded" in g for g in asm.honest_gaps), asm.honest_gaps


# ════════════════════════════════════════════════════════════════════════════
# 对抗③：mock/template/fallback 执行块（manifest 声明）经 R1/R4/R5 必拒 + fail-closed
# ════════════════════════════════════════════════════════════════════════════
def test_declared_silent_mock_block_rejected_R1():
    manifest = _run_manifest(execution_blocks=[
        {"block_id": "ingest", "mode": MODE_MOCK, "result_grade": GRADE_EXPLORATORY,
         "mock_marked": False},  # R1 silent mock
    ])
    asm = assemble(manifest)
    assert len(asm.candidate.execution_blocks) == 1  # 真映射·不丢
    v = evaluate_run_releasable(manifest)
    rej = [o for o in v.rejections if o.gate_id == GATE_MOCK_HONESTY]
    assert rej and any(MOCK_UNMARKED in m for m in rej[0].missing), v.reason_text


def test_declared_template_production_block_rejected_R4():
    manifest = _run_manifest(execution_blocks=[
        {"block_id": "synth", "mode": MODE_TEMPLATE, "result_grade": GRADE_PRODUCTION},  # R4
    ])
    v = evaluate_run_releasable(manifest)
    rej = [o for o in v.rejections if o.gate_id == GATE_MOCK_HONESTY]
    assert rej and any(TEMPLATE_FALSE_SUCCESS in m for m in rej[0].missing), v.reason_text


def test_declared_production_via_fallback_rejected_R5():
    manifest = _run_manifest(execution_blocks=[
        {"block_id": "ingest", "mode": MODE_FALLBACK, "result_grade": GRADE_PRODUCTION,
         "fallback_reason": "provider down"},  # 有原因但喂生产 → R5 致命
    ])
    v = evaluate_run_releasable(manifest)
    rej = [o for o in v.rejections if o.gate_id == GATE_MOCK_HONESTY]
    assert rej and any(PRODUCTION_VIA_NON_LIVE in m for m in rej[0].missing), v.reason_text


def test_declared_block_invalid_mode_fails_closed():
    """非法 mode（typo）→ ExecutionBlock 构造即 raise（绝不静默吞一个分类不明的块）。"""
    with pytest.raises(MockHonestyError):
        assemble(_run_manifest(execution_blocks=[{"block_id": "b", "mode": "mok"}]))


def test_declared_block_missing_mode_fails_closed():
    """声明块缺 mode → 无法诚实分类 → AssemblyError（不默认成 live 放行）。"""
    with pytest.raises(AssemblyError):
        assemble(_run_manifest(execution_blocks=[{"block_id": "b", "result_grade": GRADE_PRODUCTION}]))


@pytest.mark.parametrize(
    "bad_container",
    [None, "mock", {"mode": MODE_MOCK}, 7, True],
    ids=["none", "string", "mapping", "int", "bool"],
)
def test_declared_execution_blocks_container_fails_closed(bad_container):
    """声明了 execution_blocks 就必须是块序列，畸形容器不能退化成“未声明”。"""
    with pytest.raises(AssemblyError, match="run_manifest.execution_blocks"):
        assemble(_run_manifest(execution_blocks=bad_container))


@pytest.mark.parametrize(
    "bad_block",
    [None, "drop-me", 7, True],
    ids=["none", "string", "int", "bool"],
)
def test_declared_non_mapping_block_fails_closed_instead_of_dropped(bad_block):
    """序列中的任一非 Mapping 条目都必须拒绝，不能过滤后让剩余块继续过门。"""
    manifest = _run_manifest(execution_blocks=[
        {"block_id": "live", "mode": MODE_LIVE, "live_source_ref": "feed://live"},
        bad_block,
    ])
    with pytest.raises(AssemblyError, match=r"execution_blocks\[1\] 须为 Mapping"):
        assemble(manifest)


@pytest.mark.parametrize(
    "bad_marker",
    ["false", 0, 1, None],
    ids=["string-false", "zero", "one", "none"],
)
def test_declared_mock_marked_requires_actual_bool(bad_marker):
    """truthiness 不能代替布尔声明；尤其字符串 'false' 不得被 bool(...) 改写成 True。"""
    manifest = _run_manifest(execution_blocks=[
        {"block_id": "mock", "mode": MODE_MOCK, "mock_marked": bad_marker},
    ])
    with pytest.raises(AssemblyError, match=r"execution_blocks\[0\]\.mock_marked 须为 bool"):
        assemble(manifest)


def test_execution_absent_surfaced_as_honest_gap():
    """run.json 无执行诚实标识 → 留空 + 软披露（不假装'已核 live'）。"""
    asm = assemble(_run_manifest())
    assert asm.candidate.execution_blocks == ()
    assert "execution_blocks" in asm.absent_fields
    assert any("execution:honesty_undeclared" in g for g in asm.honest_gaps), asm.honest_gaps


# ════════════════════════════════════════════════════════════════════════════
# 对抗④：assembly_inputs 真透传不静默丢
# ════════════════════════════════════════════════════════════════════════════
def test_assembly_inputs_passthrough_not_dropped():
    ai = {"factor_set": "fs_momentum_v3", "model_id": "m_xgb_7", "cost_preset": "binance_perp"}
    manifest = _run_manifest(assembly_inputs=ai)
    asm = assemble(manifest)
    assert asm.assembly_inputs == ai  # 一字不丢
    # evaluate_run_releasable 的 honest_gaps surface（不静默吞·钉 §16 致命「未注入却声称已采用」）
    v = evaluate_run_releasable(manifest)
    assert any("assembly:intent_recorded_injection_unverified" in g for g in v.honest_gaps)
    assert any("factor_set" in g for g in v.honest_gaps), v.honest_gaps


def test_no_assembly_inputs_no_false_claim():
    asm = assemble(_run_manifest())
    assert asm.assembly_inputs == {}
    assert not any("assembly:intent_recorded" in g for g in asm.honest_gaps)


# ════════════════════════════════════════════════════════════════════════════
# 对抗⑤：证据齐全正路径 ok=True 不误伤
# ════════════════════════════════════════════════════════════════════════════
def test_full_evidence_run_releasable_not_misfired():
    manifest = _run_manifest()
    v = evaluate_run_releasable(manifest, **_good_evidence())
    assert v.ok, f"全证据齐却被误拒：{v.reason_text}"
    assert v.rejections == ()


def test_assemble_release_candidate_thin_returns_candidate():
    """薄包 assemble_release_candidate 返回 ReleaseCandidate（卡契约类型）且与 assemble().candidate 一致。"""
    manifest = _run_manifest()
    cand = assemble_release_candidate(manifest, **_good_evidence())
    assert evaluate_release(cand).ok
    asm = assemble(manifest, **_good_evidence())
    assert isinstance(asm, AssembledRelease)
    assert cand == asm.candidate


def test_bare_weak_run_releasable_with_soft_gaps():
    """裸 exploratory run（无 strong 证据义务）→ §16 层 ok=True，但缺口全软披露（不静默放绿）。"""
    v = evaluate_run_releasable(_run_manifest())
    assert v.ok, v.reason_text
    assert any("dataset:identity_unrecorded" in g for g in v.honest_gaps)
    assert any("execution:honesty_undeclared" in g for g in v.honest_gaps)


def test_llm_ledger_probe_reads_only_explicit_owner_real_rows(tmp_path):
    store = LLMCallRecordStore(tmp_path / "llm_call_records.jsonl")
    expected = _append_store_invocation(
        store,
        owner_user_id="owner-alice",
        workflow_id="ide_alice_momentum_aB3x",
        invocation_id="invocation-alice",
    )

    asm = assemble(
        _run_manifest(),
        ledger=store,
        owner_user_id="owner-alice",
        llm_used=True,
        gateway_secret=store.seal_secret,
    )

    assert asm.candidate.llm_call_records == expected
    assert evaluate_release(asm.candidate).ok


def test_llm_ledger_probe_wrong_owner_isolated(tmp_path):
    store = LLMCallRecordStore(tmp_path / "llm_call_records.jsonl")
    _append_store_invocation(
        store,
        owner_user_id="owner-alice",
        workflow_id="ide_alice_momentum_aB3x",
        invocation_id="invocation-alice",
    )

    asm = assemble(
        _run_manifest(),
        ledger=store,
        owner_user_id="owner-bob",
    )

    assert asm.candidate.llm_call_records == ()
    assert "llm_call_records" in asm.absent_fields


def test_llm_ledger_probe_requires_owner_and_does_not_swallow_errors(tmp_path):
    store = LLMCallRecordStore(tmp_path / "llm_call_records.jsonl")
    manifest_with_owner_metadata = _run_manifest()
    manifest_with_owner_metadata["source"]["owner_user_id"] = "owner-alice"
    with pytest.raises(AssemblyError, match="owner_user_id is required"):
        assemble(manifest_with_owner_metadata, ledger=store)

    class BrokenOwnerScopedStore:
        def llm_records_for(self, asset_ref, *, owner_user_id):
            raise RuntimeError("owner-scoped read failed")

    with pytest.raises(RuntimeError, match="owner-scoped read failed"):
        assemble(
            _run_manifest(),
            ledger=BrokenOwnerScopedStore(),
            owner_user_id="owner-alice",
        )


# ════════════════════════════════════════════════════════════════════════════
# user-waived 缺 MCR → 拒（不编造 MCR）；ledger 若在 → 填（duck-typed 探针）
# ════════════════════════════════════════════════════════════════════════════
def test_user_waived_label_missing_mcr_not_fabricated():
    manifest = _run_manifest()
    asm = assemble(manifest, requested_label="user_waived_theory")
    assert asm.candidate.methodology_choice is None  # 不编造 MCR
    v = evaluate_release(asm.candidate)
    rej = [o for o in v.rejections if o.gate_id == GATE_METHODOLOGY_CHOICE]
    assert rej and "methodology_choice" in rej[0].missing, v.reason_text


class _FakeSpineLedger:
    """SpineLedger 形 duck（latest_binding/checks_for/choices_for 返回 spine_ledger payload）。"""

    def __init__(self, binding=None, checks=(), choices=()):
        self._binding = binding
        self._checks = list(checks)
        self._choices = list(choices)

    def latest_binding(self, theory_ref):
        if self._binding and self._binding.get("theory_ref") == theory_ref:
            return self._binding
        return None

    def checks_for(self, binding_id):
        return [c for c in self._checks if c.get("binding_id") == binding_id]

    def choices_for(self, asset_ref):
        return [c for c in self._choices if c.get("asset_ref") == asset_ref]


def test_ledger_spine_evidence_filled_when_present():
    """ledger 里 TIB + ConsistencyCheck 在场（按 theory_ref）→ 组装器如实重建填入（id 一致）。"""
    _art, tib, cc, _ch = _good_spine()
    ledger = _FakeSpineLedger(binding=_binding_payload(tib), checks=[_check_payload(cc)])
    asm = assemble(_run_manifest(), ledger=ledger, theory_ref=tib.theory_ref)
    assert asm.candidate.binding is not None
    assert asm.candidate.binding.binding_id == tib.binding_id  # 内容寻址 id 重算一致
    assert len(asm.candidate.consistency_checks) == 1
    assert asm.candidate.consistency_checks[0].check_id == cc.check_id


def test_ledger_mcr_filled_by_asset_ref():
    """ledger 里 MCR 按 asset_ref(=run_id) 在场 → 填入；满足 user-waived 路径门。"""
    manifest = _run_manifest()
    run_id = manifest["run_id"]
    mcr = MethodologyChoiceRecord(
        chosen_path="user_waived_theory", asset_ref=run_id, actor="dreaminate",
        skipped_steps=("formal_proof",),
        responsibility_boundary="user accepts theory not formally proven; exploratory only",
    )
    ledger = _FakeSpineLedger(choices=[_choice_payload(mcr)])
    asm = assemble(manifest, ledger=ledger, requested_label="user_waived_theory")
    assert asm.candidate.methodology_choice is not None
    assert asm.candidate.methodology_choice.choice_id == mcr.choice_id
    mc = [o for o in evaluate_release(asm.candidate).outcomes
          if o.gate_id == GATE_METHODOLOGY_CHOICE][0]
    assert mc.passed, mc.reason


def test_ledger_absent_evidence_stays_empty():
    """ledger 无匹配（无 theory_ref 提示 / 无 choices）→ 留空（探针不编造）。"""
    ledger = _FakeSpineLedger()
    asm = assemble(_run_manifest(), ledger=ledger)
    assert asm.candidate.binding is None
    assert asm.candidate.methodology_choice is None
    assert asm.candidate.consistency_checks == ()


def test_explicit_evidence_overrides_ledger():
    """显式注入证据 > ledger 探针（中心喂的真证据优先）。"""
    _art, tib, cc, ch = _good_spine()
    other = TheoryImplementationBinding(theory_ref="other:theory", code_ref="x.py",
                                        code_content_hash=ch)
    ledger = _FakeSpineLedger(binding=_binding_payload(other), checks=[])
    asm = assemble(_run_manifest(), ledger=ledger, theory_ref="other:theory",
                   binding=tib, consistency_checks=(cc,))
    assert asm.candidate.binding.binding_id == tib.binding_id  # 显式赢


# ════════════════════════════════════════════════════════════════════════════
# helper 委派完整性：evaluate_run_releasable 不改门裁定，只 merge 软披露（扩展不替换）
# ════════════════════════════════════════════════════════════════════════════
def test_helper_delegates_verdict_unchanged():
    """evaluate_run_releasable 的 ok/outcomes 与直接 evaluate_release(候选) 完全一致（判定全委派）。"""
    manifest = _run_manifest()
    asm = assemble(manifest, **_good_evidence())
    direct = evaluate_release(asm.candidate)
    via = evaluate_run_releasable(manifest, **_good_evidence())
    assert via.ok == direct.ok
    assert via.outcomes == direct.outcomes
    # honest_gaps 是叠加（扩展不替换）：direct 的全在，且 ≥ direct
    assert set(direct.honest_gaps) <= set(via.honest_gaps)
