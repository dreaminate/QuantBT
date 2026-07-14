"""Research Delivery Package · §17 4 拒绝门【对抗式】测试（卡 D-RDP-1 · 北极星总闸）。

验收标准（RULES §2）：不是「测函数跑通」，而是「种一个已知的坏门，拒绝门必须抓住，
否则门是纸做的」。§17 行 2069-2076 的 4 条「→ 拒」逐条种坏：去掉对应必填字段 → 断言必拒；
补回 → 必绿。任何把门改弱（放过缺字段）的改动都会让对应断言转红。

外加：开放格式 JSON 往返证据（第三方可解析、无私有二进制）、rdp_id 复用单一身份源
ids.content_hash 的证据（内容寻址 + 时间/署名装饰字段不改 id）。
"""

from __future__ import annotations

import json

import pytest

from app.delivery import (
    ASSET_FACTOR,
    GATE_DATASET_LINEAGE,
    GATE_MANIFEST,
    GATE_PROMOTION_TRACEABILITY,
    GATE_UNVERIFIED_RESIDUAL,
    DatasetVersionRef,
    PromotionClaim,
    RDPManifest,
    RDPRejected,
    assemble_rdp,
    gate_promotion_traceability,
    require_valid_rdp,
    validate_rdp,
)
from app.lineage.ids import content_hash
from app.research_os import PersistentRDPStore, RDPManifest as ResearchOSRDPManifest


# ── builders ──────────────────────────────────────────────────────────────────
def _complete_fields(**overrides):
    """一份过门1-3 的完整 RDP 字段集（每个门必填项都填真值）。"""

    base = dict(
        asset_ref="factor:mom_20d@v3",
        asset_kind=ASSET_FACTOR,
        # 门1
        artifact_hash="a1b2c3d4e5f60718",
        reproducibility_command="python -m app.backend.reproduce --rdp rdp_xxx --seed 7",
        # 门2
        dataset_versions=(DatasetVersionRef("csi300_daily", "2025-12-31", "deadbeefcafef00d"),),
        ingestion_skill_refs=("tushare_daily_ohlcv@v2",),
        # 门3：显式声明残余（非空）→ 过
        unverified_residual=("样本外仅 1 个 regime；交易成本用静态假设未做冲击成本压测",),
        # 上下文（非门强制，带上更真实）
        honest_n=14,
        honest_n_strategy_goal_ref="goal:cross_sectional_momentum",
        verifier_verdict_refs=("vd_0011223344556677",),
        approval_refs=("gate_aabbccddeeff0011",),
    )
    base.update(overrides)
    return base


def _complete_rdp(**overrides) -> RDPManifest:
    return RDPManifest(**_complete_fields(**overrides))


def test_delivery_and_research_os_share_one_canonical_rdp_class():
    assert RDPManifest is ResearchOSRDPManifest


# ── 全绿路径：门不是一刀切摆设 ────────────────────────────────────────────────
def test_complete_rdp_passes_all_gates():
    rdp = _complete_rdp()
    v = validate_rdp(rdp)
    assert v.ok, v.reason_text
    assert v.rejections == ()
    # assemble_rdp 同样放行完整包并返回 manifest。
    assert assemble_rdp(**_complete_fields()).rdp_id == rdp.rdp_id


# ── 门1：缺 manifest 身份 / artifact hash / reproducibility command → 必拒 ──────
def test_gate1_missing_artifact_hash_rejected():
    rdp = _complete_rdp(artifact_hash="")
    v = validate_rdp(rdp)
    assert not v.ok
    o = next(o for o in v.outcomes if o.gate_id == GATE_MANIFEST)
    assert not o.passed and "artifact_hash" in o.missing
    # assemble 路径必 raise（种坏门必抓：门若放过，此处不 raise → 测试红）。
    with pytest.raises(RDPRejected):
        assemble_rdp(**_complete_fields(artifact_hash=""))


def test_gate1_missing_reproducibility_command_rejected():
    rdp = _complete_rdp(reproducibility_command="   ")  # 纯空白也算缺
    v = validate_rdp(rdp)
    assert not v.ok
    o = next(o for o in v.outcomes if o.gate_id == GATE_MANIFEST)
    assert "reproducibility_command" in o.missing
    with pytest.raises(RDPRejected):
        require_valid_rdp(rdp)


def test_gate1_missing_asset_ref_rejected():
    """manifest 身份缺失（不知这份交付描述哪个资产）→ 拒。"""
    rdp = _complete_rdp(asset_ref="")
    o = next(o for o in validate_rdp(rdp).outcomes if o.gate_id == GATE_MANIFEST)
    assert not o.passed and "asset_ref" in o.missing


# ── 门2：缺 DatasetVersion 或 IngestionSkill 引用 → 必拒 ──────────────────────
def test_gate2_missing_dataset_versions_rejected():
    rdp = _complete_rdp(dataset_versions=())
    o = next(o for o in validate_rdp(rdp).outcomes if o.gate_id == GATE_DATASET_LINEAGE)
    assert not o.passed and "dataset_versions" in o.missing
    with pytest.raises(RDPRejected):
        assemble_rdp(**_complete_fields(dataset_versions=()))


def test_gate2_hollow_dataset_version_rejected():
    """空壳 DatasetVersion 引用（dataset_id/version 空）不算有效血统 → 拒。"""
    rdp = _complete_rdp(dataset_versions=(DatasetVersionRef("", ""),))
    o = next(o for o in validate_rdp(rdp).outcomes if o.gate_id == GATE_DATASET_LINEAGE)
    assert not o.passed and "dataset_versions" in o.missing


def test_gate2_missing_ingestion_skill_rejected():
    rdp = _complete_rdp(ingestion_skill_refs=())
    o = next(o for o in validate_rdp(rdp).outcomes if o.gate_id == GATE_DATASET_LINEAGE)
    assert not o.passed and "ingestion_skill_refs" in o.missing


# ── 门3：缺「未验证残余」声明 → 必拒（诚实闸）────────────────────────────────
def test_gate3_residual_none_rejected():
    """未声明残余（None 哨兵）→ 拒：未声明残余的交付不完整。"""
    rdp = _complete_rdp(unverified_residual=None)
    o = next(o for o in validate_rdp(rdp).outcomes if o.gate_id == GATE_UNVERIFIED_RESIDUAL)
    assert not o.passed and "unverified_residual" in o.missing
    with pytest.raises(RDPRejected):
        assemble_rdp(**_complete_fields(unverified_residual=None))


def test_gate3_empty_residual_without_attestation_rejected():
    """显式声明零残余但无署名审查 → 拒（claim 完美须可归因，不可空口）。"""
    rdp = _complete_rdp(unverified_residual=(), residual_attestation="")
    o = next(o for o in validate_rdp(rdp).outcomes if o.gate_id == GATE_UNVERIFIED_RESIDUAL)
    assert not o.passed and "residual_attestation" in o.missing


def test_gate3_empty_residual_with_attestation_passes():
    """零残余 + 署名审查记录 → 过（显式、可归因的「已审无残余」）。"""
    rdp = _complete_rdp(
        unverified_residual=(),
        residual_attestation="dreaminate 2026-06-26 复核：本因子全部声明已对账，无已知未验证残余",
    )
    o = next(o for o in validate_rdp(rdp).outcomes if o.gate_id == GATE_UNVERIFIED_RESIDUAL)
    assert o.passed


# ── 门4：晋级资产追不到一份关于本资产的有效 RDP → 必拒 ────────────────────────
def test_gate4_promotion_missing_rdp_ref_rejected():
    rdp = _complete_rdp()
    claim = PromotionClaim(asset_ref=rdp.asset_ref, asset_kind=ASSET_FACTOR, rdp_ref="")
    o = gate_promotion_traceability(claim, rdp)
    assert not o.passed and "rdp_ref" in o.missing
    # validate_rdp 带 promotion 时也并入门4。
    with pytest.raises(RDPRejected):
        require_valid_rdp(rdp, promotion=claim)


def test_gate4_promotion_no_rdp_rejected():
    """晋级断言压根没有 RDP 可追溯 → 拒。"""
    claim = PromotionClaim(asset_ref="factor:x@v1", asset_kind=ASSET_FACTOR, rdp_ref="rdp_whatever")
    o = gate_promotion_traceability(claim, None)
    assert not o.passed and "rdp" in o.missing


def test_gate4_promotion_ref_mismatch_rejected():
    """rdp_ref 解析不到提供的 RDP（伪造/错挂 ref）→ 拒。"""
    rdp = _complete_rdp()
    claim = PromotionClaim(asset_ref=rdp.asset_ref, asset_kind=ASSET_FACTOR, rdp_ref="rdp_0000000000000000")
    o = gate_promotion_traceability(claim, rdp)
    assert not o.passed and "rdp_ref" in o.missing


def test_gate4_promotion_asset_mismatch_rejected():
    """RDP 描述的资产 ≠ 被晋级资产（张冠李戴：拿别的资产的 RDP 给本资产背书）→ 拒。"""
    rdp = _complete_rdp(asset_ref="factor:mom_20d@v3")
    claim = PromotionClaim(
        asset_ref="factor:reversal_5d@v1", asset_kind=ASSET_FACTOR, rdp_ref=rdp.rdp_id
    )
    o = gate_promotion_traceability(claim, rdp)
    assert not o.passed and "asset_ref" in o.missing


def test_gate4_promotion_against_invalid_rdp_rejected():
    """追溯到的 RDP 本身残缺（缺残余声明）→ 追到一份破 RDP 不算可追溯 → 拒。"""
    broken = _complete_rdp(unverified_residual=None)
    claim = PromotionClaim(asset_ref=broken.asset_ref, asset_kind=ASSET_FACTOR, rdp_ref=broken.rdp_id)
    o = gate_promotion_traceability(claim, broken)
    assert not o.passed


def test_gate4_promotion_traceable_passes():
    """ref 解析 + 资产匹配 + RDP 有效 → 晋级可追溯，放行。"""
    rdp = _complete_rdp()
    claim = PromotionClaim(asset_ref=rdp.asset_ref, asset_kind=ASSET_FACTOR, rdp_ref=rdp.rdp_id)
    o = gate_promotion_traceability(claim, rdp)
    assert o.passed
    assert validate_rdp(rdp, promotion=claim).ok


# ── 开放格式：JSON 可第三方解析、往返不丢、无私有二进制 ──────────────────────
def test_rdp_open_format_json_roundtrip():
    rdp = _complete_rdp()
    text = rdp.to_json()
    # 纯 JSON：任何 json.loads 都能解析（不依赖本模块）。
    parsed = json.loads(text)
    assert isinstance(parsed, dict)
    assert parsed["asset_ref"] == "factor:mom_20d@v3"
    # 嵌套 DatasetVersionRef 投影成普通 dict（开放、无自定义类型标记）。
    assert parsed["dataset_versions"][0]["dataset_id"] == "csi300_daily"
    # 往返重建：内容等价（rdp_id 稳定）。
    rebuilt = RDPManifest.from_json(text)
    assert rebuilt.rdp_id == rdp.rdp_id
    assert rebuilt.to_dict() == rdp.to_dict()


def test_rdp_from_dict_recomputes_id_not_trusting_input():
    """from_dict 不信任外部 rdp_id，按内容重算（防伪造 id 蒙混追溯）。"""
    d = _complete_rdp().to_dict()
    d["rdp_id"] = "rdp_forged0000000"  # 伪造 id
    rebuilt = RDPManifest.from_dict(d)
    assert rebuilt.rdp_id != "rdp_forged0000000"
    assert rebuilt.rdp_id == "rdp_" + content_hash(rebuilt._identity_payload())


def test_rdp_direct_constructor_rejects_forged_identity():
    with pytest.raises(ValueError, match="canonical content identity"):
        RDPManifest(**_complete_fields(), package_id="rdp_forged0000000")


def test_rdp_store_rejects_post_construction_content_mutation(tmp_path):
    manifest = _complete_rdp()
    object.__setattr__(manifest, "artifact_hash", "tampered-after-construction")

    with pytest.raises(ValueError, match="content_identity_mismatch"):
        PersistentRDPStore(tmp_path / "rdp.jsonl").record_manifest(
            manifest,
            owner_user_id="u1",
            recorded_by="u1",
        )


# ── 身份复用：rdp_id 走单一身份源 ids.content_hash，不另造哈希族 ──────────────
def test_rdp_id_reuses_content_hash_single_source():
    rdp = _complete_rdp()
    assert rdp.rdp_id.startswith("rdp_")
    assert rdp.rdp_id == "rdp_" + content_hash(rdp._identity_payload())
    # 16 位 hex（= 全库 HASH_LEN 不变量）。
    assert len(rdp.rdp_id) == len("rdp_") + 16


def test_rdp_id_content_addressed_changes_with_content():
    a = _complete_rdp(artifact_hash="aaaa000000000000")
    b = _complete_rdp(artifact_hash="bbbb000000000000")
    assert a.rdp_id != b.rdp_id  # 内容变 → id 变


def test_rdp_id_stable_across_decorative_fields():
    """时间/署名是装饰字段：改它们不该改变内容寻址身份。"""
    a = _complete_rdp(created_at_utc="2026-06-26T00:00:00Z", created_by="alice")
    b = _complete_rdp(created_at_utc="2026-06-27T12:00:00Z", created_by="bob")
    assert a.rdp_id == b.rdp_id


def test_asset_kind_must_be_legal():
    with pytest.raises(ValueError):
        _complete_rdp(asset_kind="garbage")
