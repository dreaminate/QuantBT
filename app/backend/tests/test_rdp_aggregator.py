"""RDP 聚合器【对抗式】测试（卡 D-RDP-2 · 北极星 §17 · 全程真血统·零编造）。

验收标准（RULES §2）：不是「函数跑通」，而是「种已知坏门 / 篡改真源 → 聚合器+D-RDP-1 门必抓」。
本卡 4 条可证伪验收逐条种坏：
  ① 聚合 RDP 缺 DatasetVersion/IngestionSkill 真引用 → D-RDP-1 门拒（MUT：聚合器若伪造默认源放行→红）。
  ② 用了 LLM 但缺 LLMCallRecord → 标 missing 不美化（MUT：若塞假 ref「补全」→红）。
  ③ 缺未验证残余 → 门拒（诚实闸）。
  ④ 真血统装配：DatasetVersion/LLMCallRecord/honest-N/verdict 从真源填·篡改源→聚合反映（MUT：
     若静默填默认/编造→断言转红）。
外加安全红线（北极星·撞即停）：实盘明文 key 绝不进 RDP——只 call_id ref / auth_ref(SecretRef)，
明文进自由文本即 `SecretLeakError`。

全程用**真源类**构造（DatasetVersion / LLMCallRecord / Ledger / VerdictRecord / ApprovalGate），
非 mock：篡改真对象的身份字段 → 派生 ref / honest_n 随之变，证明非编造。
"""

from __future__ import annotations

import json

import pytest

from app.approval.schema import ApprovalGate
from app.data_quality import DatasetVersion
from app.delivery import (
    ASSET_FACTOR,
    GATE_DATASET_LINEAGE,
    GATE_MANIFEST,
    GATE_UNVERIFIED_RESIDUAL,
    RDPRejected,
)
from app.delivery.aggregator import (
    GAP_APPROVAL_MISSING,
    GAP_HONEST_N_UNAVAILABLE,
    GAP_HONEST_N_ZERO,
    GAP_INGESTION_SKILL_UNDERIVED,
    GAP_LLM_RECORD_MISSING,
    GAP_VERDICT_MISSING,
    RDPAssembly,
    aggregate_rdp,
    require_aggregated_rdp,
)
from app.lineage import Ledger
from app.lineage.ledger import LedgerEntry
from app.llm.call_record import LLMCallRecord, ReplayState, SecretLeakError, make_call_id
from app.verification.schema import Independence, VerdictRecord, compute_verdict_id

ASSET_REF = "factor:mom_20d@v3"
GOAL = "goal:cross_sectional_momentum"


# ── 真源构造器（非 mock·真实 dataclass / 真账本）────────────────────────────────
def _real_dataset_version(
    *, dataset_id="csi300_daily", version_id="2025-12-31",
    sha256="deadbeefcafef00d", skill="tushare_daily_ohlcv@v2",
) -> DatasetVersion:
    return DatasetVersion(
        dataset_id=dataset_id, version_id=version_id, source_name="tushare",
        fetched_at_utc="2026-01-01T00:00:00Z", row_count=730,
        coverage_start_utc="2023-01-01", coverage_end_utc="2025-12-31",
        sha256=sha256, ingestion_skill_version=(skill or None), source_ref="tushare:daily",
    )


def _real_llm_record(
    *, provider="anthropic", model="claude-opus-4",
    replay=ReplayState.REPLAYED.value, auth_ref="secretref://anthropic/llm_anthropic",
) -> LLMCallRecord:
    cid = make_call_id(
        prompt_digest="pdg_abc", provider=provider, model=model,
        role="researcher", session_id="sess1", seq=1,
    )
    return LLMCallRecord(
        provider=provider, model=model, auth_ref=auth_ref, replay_state=replay, call_id=cid,
    )


def _real_verdict(*, target_ref=ASSET_REF) -> VerdictRecord:
    ind = Independence(
        model_differs=True, seed_differs=True, slice_differs=False, axes=2, established=True,
    )
    vid = compute_verdict_id(
        target_ref=target_ref, generator_model="gpt-x", checker_model="claude-y",
        verdict="consistent", consistency_check=[], independence=ind, replay_ref=None,
    )
    return VerdictRecord(
        verdict_id=vid, target_ref=target_ref, generator_model="gpt-x", checker_model="claude-y",
        verdict="consistent", consistency_check=[], independence=ind,
    )


def _real_approval(*, gate_id="gate_aabbccddeeff0011") -> ApprovalGate:
    return ApprovalGate(
        gate_id=gate_id, model_id="mom_20d", version=3, from_stage="staging",
        to_stage="production", channel="confirmatory", action_kind="promote_production",
        created_by="dreaminate", approver="reviewer",
    )


def _real_ledger(root, n: int) -> Ledger:
    """真 Ledger + n 条 distinct config 试验 → honest_n(GOAL) == n（真查询）。"""

    led = Ledger(root)
    for i in range(n):
        led.record_or_hit(
            LedgerEntry.create(
                factor=f"rank(close*{i})", params={"win": 5}, universe="csi300",
                dataset_version="ds_a", freq="1d", label="ret1",
                strategy_goal_ref=GOAL, kind="backtest", stage="confirmatory",
            )
        )
    return led


def _complete_kwargs(**over):
    """一份过 D-RDP-1 门1-3 的完整聚合输入（全真源；默认不带 Ledger → honest_n 留 None）。"""

    base = dict(
        asset_ref=ASSET_REF,
        asset_kind=ASSET_FACTOR,
        dataset_versions=(_real_dataset_version(),),
        llm_call_records=(_real_llm_record(),),
        verdicts=(_real_verdict(),),
        approvals=(_real_approval(),),
        artifact_hash="a1b2c3d4e5f60718",
        reproducibility_command="python -m app.backend.reproduce --rdp x --seed 7",
        unverified_residual=("样本外仅 1 个 regime；成本用静态假设未压测冲击成本",),
    )
    base.update(over)
    return base


# ════════════ 全绿路径：真血统齐备 → 过全部门 + 开放 JSON ════════════
def test_full_real_assembly_passes_all_gates_open_json(tmp_path):
    led = _real_ledger(tmp_path / "led", 3)
    a = aggregate_rdp(**_complete_kwargs(ledger=led, honest_n_strategy_goal_ref=GOAL))
    assert isinstance(a, RDPAssembly)
    assert a.ok, a.validation.reason_text
    assert a.validation.rejections == ()
    # 真血统齐备 → 零诚实缺口。
    assert a.honest_gaps == (), a.honest_gaps
    # honest_n 来自真账（3 条 distinct config）。
    assert a.rdp.honest_n == 3
    # 开放格式：第三方 json.loads 可解析、无私有二进制。
    parsed = json.loads(a.rdp.to_json())
    assert parsed["asset_ref"] == ASSET_REF
    assert parsed["dataset_versions"][0]["dataset_id"] == "csi300_daily"


# ════════════ 验收①：缺 DatasetVersion / IngestionSkill → D-RDP-1 门拒 ════════════
def test_missing_dataset_version_gate2_rejects():
    """聚合漏真 DatasetVersion → 门2 必抓。MUT：若聚合器伪造默认 dataset 放行 → `a.ok` 转 True → 红。"""
    a = aggregate_rdp(**_complete_kwargs(dataset_versions=()))
    assert not a.ok
    o = next(o for o in a.validation.outcomes if o.gate_id == GATE_DATASET_LINEAGE)
    assert not o.passed and "dataset_versions" in o.missing
    # 强制入口必 raise（门若被改弱放行 → 不 raise → 红）。
    with pytest.raises(RDPRejected):
        require_aggregated_rdp(**_complete_kwargs(dataset_versions=()))


def test_missing_ingestion_skill_gate2_rejects():
    """DatasetVersion 无 ingestion_skill_version 且未显式提供 → 门2 拒 ingestion_skill_refs。"""
    dv = _real_dataset_version(skill="")  # 真 dataset 但无采集 skill 身份
    a = aggregate_rdp(**_complete_kwargs(dataset_versions=(dv,)))
    assert GAP_INGESTION_SKILL_UNDERIVED in a.honest_gaps
    o = next(o for o in a.validation.outcomes if o.gate_id == GATE_DATASET_LINEAGE)
    assert not o.passed and "ingestion_skill_refs" in o.missing


def test_explicit_ingestion_skill_used_when_dataset_lacks():
    """dataset 缺 skill 时，显式 ingestion_skill_refs 补位 → 门2 过（真值·非编造）。"""
    dv = _real_dataset_version(skill="")
    a = aggregate_rdp(
        **_complete_kwargs(dataset_versions=(dv,), ingestion_skill_refs=("manual_intake@v1",))
    )
    assert "manual_intake@v1" in a.rdp.ingestion_skill_refs
    o = next(o for o in a.validation.outcomes if o.gate_id == GATE_DATASET_LINEAGE)
    assert o.passed


def test_hollow_dataset_version_rejected():
    """空壳 DatasetVersion（dataset_id/version 空）不算有效血统 → 门2 拒（反映真源残缺）。"""
    dv = _real_dataset_version(dataset_id="", version_id="")
    a = aggregate_rdp(**_complete_kwargs(dataset_versions=(dv,)))
    o = next(o for o in a.validation.outcomes if o.gate_id == GATE_DATASET_LINEAGE)
    assert not o.passed and "dataset_versions" in o.missing


# ════════════ 验收②：用了 LLM 但缺 LLMCallRecord → 标 missing 不美化 ════════════
def test_llm_used_no_record_marks_missing_not_beautify():
    """声明用 LLM 却无调用账：refs 留空（不塞假 ref）+ honest_gaps 标 missing。

    MUT：若聚合器伪造一条假 LLMCallRecord ref「补全」→ `llm_call_record_refs` 非空 → 断言转红。
    """
    a = aggregate_rdp(**_complete_kwargs(llm_call_records=(), llm_used=True))
    # 不美化：绝不塞假 ref。
    assert a.rdp.llm_call_record_refs == ()
    # 标 missing：诚实缺口被披露。
    assert GAP_LLM_RECORD_MISSING in a.honest_gaps
    # LLM 非 §17 门硬拒（D-SCOPE-CONSERVATIVE 不管太宽）：dataset/残余齐备仍过门，但缺口诚实在册。
    assert a.ok


def test_llm_used_inferred_from_provider_without_record():
    """未显式 llm_used，但给了 llm_provider 却无 record → 推断「用了」→ 标 missing。"""
    a = aggregate_rdp(**_complete_kwargs(llm_call_records=(), llm_provider="anthropic"))
    assert a.rdp.llm_call_record_refs == ()
    assert GAP_LLM_RECORD_MISSING in a.honest_gaps


def test_no_llm_declared_no_false_gap():
    """没声明用 LLM、也没给 record/provider → 不该误报 LLM 缺口（不无中生有）。"""
    a = aggregate_rdp(**_complete_kwargs(llm_call_records=(), llm_used=False))
    assert GAP_LLM_RECORD_MISSING not in a.honest_gaps


# ════════════ 验收③：缺未验证残余 → 门3 拒（诚实闸）════════════
def test_missing_unverified_residual_gate3_rejects():
    a = aggregate_rdp(**_complete_kwargs(unverified_residual=None))
    assert not a.ok
    o = next(o for o in a.validation.outcomes if o.gate_id == GATE_UNVERIFIED_RESIDUAL)
    assert not o.passed and "unverified_residual" in o.missing
    with pytest.raises(RDPRejected):
        require_aggregated_rdp(**_complete_kwargs(unverified_residual=None))


def test_zero_residual_without_attestation_rejected():
    """显式声明零残余但无署名审查 → 门3 拒（claim 完美须可归因·聚合器透传哨兵语义）。"""
    a = aggregate_rdp(**_complete_kwargs(unverified_residual=(), residual_attestation=""))
    o = next(o for o in a.validation.outcomes if o.gate_id == GATE_UNVERIFIED_RESIDUAL)
    assert not o.passed and "residual_attestation" in o.missing


# ════════════ 验收④：真血统装配·篡改源→聚合反映（非编造/不静默默认）════════════
def test_honest_n_from_real_ledger_not_fabricated(tmp_path):
    """honest_n 走真 Ledger 查询：篡改源（更多试验）→ 反映；无 Ledger → None（不补 0 美化）。

    MUT：若聚合器硬填 honest_n=0/默认 → `==3`/`==7` 断言转红；无 Ledger 填 0 → `is None` 转红。
    """
    led3 = _real_ledger(tmp_path / "l3", 3)
    a3 = aggregate_rdp(**_complete_kwargs(ledger=led3, honest_n_strategy_goal_ref=GOAL))
    assert a3.rdp.honest_n == 3

    led7 = _real_ledger(tmp_path / "l7", 7)
    a7 = aggregate_rdp(**_complete_kwargs(ledger=led7, honest_n_strategy_goal_ref=GOAL))
    assert a7.rdp.honest_n == 7  # 源变（更多 distinct config）→ 聚合反映

    # 无 Ledger → honest_n 留 None（绝不补 0 假装「跑过 0 次」），并标缺口。
    a0 = aggregate_rdp(**_complete_kwargs(ledger=None))
    assert a0.rdp.honest_n is None
    assert GAP_HONEST_N_UNAVAILABLE in a0.honest_gaps


def test_honest_n_zero_disclosed(tmp_path):
    """真 Ledger 但该主题 0 条 → honest_n=0 是真测值，须披露（晋级前 N=0 是诚实警示）。"""
    led = _real_ledger(tmp_path / "lz", 0)
    a = aggregate_rdp(**_complete_kwargs(ledger=led, honest_n_strategy_goal_ref=GOAL))
    assert a.rdp.honest_n == 0
    assert GAP_HONEST_N_ZERO in a.honest_gaps


def test_dataset_ref_mirrors_real_source_identity():
    """DatasetVersionRef 的 version/sha 来自真 DatasetVersion 身份；篡改源 → ref 变 → rdp_id 变。"""
    dv = _real_dataset_version(version_id="2025-12-31", sha256="deadbeefcafef00d")
    a = aggregate_rdp(**_complete_kwargs(dataset_versions=(dv,)))
    ref = a.rdp.dataset_versions[0]
    assert ref.dataset_id == dv.dataset_id
    assert ref.version == dv.version_id        # 真 version_id（非编造）
    assert ref.manifest_sha256 == dv.sha256    # 真 sha256

    dv2 = _real_dataset_version(version_id="2026-01-15", sha256="0011223344556677")
    a2 = aggregate_rdp(**_complete_kwargs(dataset_versions=(dv2,)))
    assert a2.rdp.dataset_versions[0].version == "2026-01-15"
    assert a.rdp.rdp_id != a2.rdp.rdp_id        # 内容寻址：真源变 → rdp_id 变


def test_llm_verdict_approval_refs_from_real_ids():
    """llm_call_record_refs / verifier_verdict_refs / approval_refs 来自各真对象的真 id。"""
    rec = _real_llm_record(provider="anthropic", replay=ReplayState.RECORDED.value)
    vd = _real_verdict()
    ap = _real_approval(gate_id="gate_1234567890abcdef")
    a = aggregate_rdp(
        **_complete_kwargs(llm_call_records=(rec,), verdicts=(vd,), approvals=(ap,))
    )
    assert rec.call_id in a.rdp.llm_call_record_refs   # 真 call_id（make_call_id 单一源）
    assert a.rdp.llm_provider == "anthropic"
    assert a.rdp.replay_state == ReplayState.RECORDED.value
    assert vd.verdict_id in a.rdp.verifier_verdict_refs  # 真 verdict_id
    assert ap.gate_id in a.rdp.approval_refs             # 真 gate_id


def test_missing_verdict_and_approval_disclosed():
    """无 Verifier 裁决 / 无 Approval → 标 missing（§17 契约携带·不美化）。"""
    a = aggregate_rdp(**_complete_kwargs(verdicts=(), approvals=()))
    assert GAP_VERDICT_MISSING in a.honest_gaps
    assert GAP_APPROVAL_MISSING in a.honest_gaps
    assert a.rdp.verifier_verdict_refs == ()
    assert a.rdp.approval_refs == ()


def test_artifact_hash_derived_from_real_artifact_single_source():
    """缺 artifact_hash 时由真 artifact 经 lineage.ids.content_hash 派生（单一身份源·非另造）。"""
    from app.lineage.ids import content_hash

    artifact = {"factor": "rank(close)", "params": {"win": 20}}
    a = aggregate_rdp(**_complete_kwargs(artifact_hash="", artifact=artifact))
    assert a.rdp.artifact_hash == content_hash(artifact)
    o = next(o for o in a.validation.outcomes if o.gate_id == GATE_MANIFEST)
    assert o.passed  # 派生出真 hash → 门1 过


# ════════════ 安全红线：实盘明文 key 绝不进 RDP ════════════
def test_plaintext_live_key_in_freetext_caught_by_safety_gate():
    """明文 key 误进自由文本（reproducibility_command）+ known_secrets → 安全闸 raise（撞即停）。

    MUT：若聚合器不扫描 RDP 开放面 → 不 raise → 红。
    """
    SECRET = "sk-ant-LIVE-0123456789abcdefDEADBEEFcafef00d"
    with pytest.raises(SecretLeakError):
        aggregate_rdp(
            **_complete_kwargs(
                reproducibility_command=f"reproduce --api-key {SECRET}",
                known_secrets=[SECRET],
            )
        )


def test_record_auth_ref_secretref_not_in_rdp_only_call_id():
    """LLMCallRecord 的 auth_ref 是 SecretRef：聚合器只取 call_id ref，auth_ref 根本不进 RDP。"""
    rec = _real_llm_record(auth_ref="secretref://anthropic/llm_anthropic")
    a = aggregate_rdp(**_complete_kwargs(llm_call_records=(rec,)))
    blob = a.rdp.to_json()
    assert "secretref://anthropic/llm_anthropic" not in blob  # auth_ref 不进 RDP
    assert rec.call_id in blob                                # 只 call_id ref 进
    assert a.rdp.llm_provider == "anthropic"


def test_clean_secretref_record_not_falsely_flagged():
    """真 record 只携 SecretRef（非明文）：即便扫描其引用的实盘明文也找不到 → 不误报（证明明文未泄）。"""
    LIVE_PLAINTEXT = "sk-ant-REAL-PLAINTEXT-key-never-leaks-0123456789abcdef"
    rec = _real_llm_record(auth_ref="secretref://anthropic/llm_anthropic")
    a = aggregate_rdp(
        **_complete_kwargs(llm_call_records=(rec,), known_secrets=[LIVE_PLAINTEXT])
    )
    assert a.ok  # 明文不在 record / RDP 任何字段 → 扫描零命中 → 正常装配


# ════════════ passthrough 完整性：context_fields 不能绕过真装配 ════════════
def test_context_fields_rejects_unknown_key():
    with pytest.raises(ValueError):
        aggregate_rdp(**_complete_kwargs(context_fields={"not_a_real_field": "x"}))


def test_context_fields_forbids_clobbering_managed_lineage():
    """禁止借 passthrough 覆盖聚合器管理的真血统字段（防塞假 dataset/honest_n）。"""
    with pytest.raises(ValueError):
        aggregate_rdp(**_complete_kwargs(context_fields={"dataset_versions": ()}))
    with pytest.raises(ValueError):
        aggregate_rdp(**_complete_kwargs(context_fields={"honest_n": 999}))


def test_context_fields_passthrough_populates_section17():
    """未建类（TheorySpec 等）经 context_fields 走 string ref passthrough（不强造 typed 对象）。"""
    a = aggregate_rdp(
        **_complete_kwargs(
            context_fields={
                "research_proposition": "动量在 A 股横截面存在正溢价",
                "theory_spec_refs": ("ts_unbuilt_ref_001",),
                "responsibility_disclosure_refs": ("rdr_unbuilt_ref_001",),
            }
        )
    )
    assert a.rdp.research_proposition.startswith("动量")
    assert a.rdp.theory_spec_refs == ("ts_unbuilt_ref_001",)
    assert a.rdp.responsibility_disclosure_refs == ("rdr_unbuilt_ref_001",)


# ════════════ 装配产物喂 D-RDP-1 门：require 变体语义 ════════════
def test_require_aggregated_rdp_returns_manifest_on_complete(tmp_path):
    led = _real_ledger(tmp_path / "lr", 2)
    rdp = require_aggregated_rdp(**_complete_kwargs(ledger=led, honest_n_strategy_goal_ref=GOAL))
    assert rdp.asset_ref == ASSET_REF
    assert rdp.rdp_id.startswith("rdp_")


def test_assembly_open_json_roundtrip_stable_id(tmp_path):
    """装配的 RDP 开放 JSON 往返：内容等价、rdp_id 稳定（内容寻址·复用单一身份源）。"""
    from app.delivery import RDPManifest

    led = _real_ledger(tmp_path / "lj", 2)
    a = aggregate_rdp(**_complete_kwargs(ledger=led, honest_n_strategy_goal_ref=GOAL))
    rebuilt = RDPManifest.from_json(a.rdp.to_json())
    assert rebuilt.rdp_id == a.rdp.rdp_id
    assert rebuilt.to_dict() == a.rdp.to_dict()
