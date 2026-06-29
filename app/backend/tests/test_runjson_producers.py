"""C-S17-RUNJSON-PRODUCERS · promote 门链 section 组装【producer 接线】对抗测试（RULES §2 种坏门必抓 + §3 诚实）。

这是把 §9/§10/§17 节门从 advisory 翻 enforce 的**证据 producer 接线测试**：证明
`promote_assembler.assemble_promote_sections` 从**真血统/真运行产物**（typed domain 对象）如实组装出
各 section_*_gate 的 producer 契约 dict，让门有真对象可判——合规 run 过、坏 run 拒、honest-absent 不误拒。
转绿 = 中心据本测试在 `ide/promote.py` 的 `producer_status` 上 `mark_green(对应 producer key)`，门即翻 enforce
（SA-2 LOCKED 决策 1·`mode==ENFORCE ⟹ producer_green==True` 不可违）。

可证伪验收（construction-map C-S17-RUNJSON-PRODUCERS）：
  · 合规真实 run（完整 RDP+traceable promotion / clean §9 / 强标签带成本 / 严格档强 verdict）→ 组装后四节
    记录就位 → 四 producer 绿 → 四门 ENFORCE 且**仍全过**（rejected=False·ok=True·证明 enforce 不误拒诚实 run）。
  · 坏 run（缺 artifact_hash / 强标签缺成本 / 放宽档强标签 / 缺 DatasetVersion / self-promote 无 RDP）→
    producer 绿后对应门 ENFORCE **必拒**（blocks·ok=False·缺项精确·落 run.json verdict）。
  · producer 红时同坏 run → 只 advisory 记录不阻（flip_refused·绝不误拒）。
  · honest-absent：无该类资产 → **不发** section key → 门 honest-bound ok=True（非违例·不误拒）。

★ 不假绿灯（核心非编造不变量·MUT 有牙）：组装器**只序列化真对象·零判定**——坏对象（artifact_hash=''
  的 RDP / model_body 因子 / 强标签缺成本 record）**如实序列化** → 门据真值拒，绝不在组装层洗白/补占位
  （见 `test_assembler_does_not_launder_bad_rdp` / `test_honest_absent_emits_no_section`）。

★ 变异三态（手验·见任务报告）：把 `promote_assembler.assemble_promote_sections` 改成恒返回空（`sections={}`·
  manifest 不填 section 记录）→ 下列**必变红**：四条 `test_*_emitted` + 五条坏 run `*_enforce_rejects` +
  `test_compliant_run_passes_all_four_enforce_gates`（无 section → 门「未声明」ok=True → 坏 run 不再被拒 / 合规
  run section 缺失）→ 还原 → GREEN。证明组装真发生、测试有牙（非常量门）。
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

# 冷导入预热（既有循环·非本卡引入）：导入 app.governance.* / promote_assembler（触 release_gate/__init__
# 既有冷导入环）前先全载 orchestrator 解环——与 test_section17_rdp_gate.py 等同款顺序。
import app.agent.orchestrator  # noqa: F401  (prime: 解 app.governance 既有冷导入循环)

from app.delivery.rdp import (  # noqa: E402
    DatasetVersionRef,
    PromotionClaim,
    RDPManifest,
)
from app.governance.enforcement_policy import (  # noqa: E402
    MODE_ADVISORY,
    MODE_ENFORCE,
    ProducerStatusLedger,
)
from app.methodology.control_plane import MethodologyTier  # noqa: E402
from app.research_os.factor_strategy_boundary import (  # noqa: E402
    FactorAssetKind,
    FactorGeneratorSpec,
    FactorLibraryEntry,
    StrategyBookContract,
)
from app.research_os.methodology_validation import ValidationMethodologyRecord  # noqa: E402
from app.release_gate.promote_assembler import (  # noqa: E402
    AssembledSections,
    AssemblyError,
    Section9StrategyBook,
    Section10TierClaim,
    assemble_promote_sections,
)
from app.release_gate.promote_gate_chain import ChainResult, PromoteGateChain  # noqa: E402
from app.release_gate.section9_boundary_gate import (  # noqa: E402
    SECTION9_BOUNDARY_GATE_NAME,
    SECTION9_BOUNDARY_MANIFEST_KEY,
    SECTION9_BOUNDARY_PRODUCER_KEY,
    register_section9_boundary_gate,
)
from app.release_gate.section10_methodology_gate import (  # noqa: E402
    SECTION10_CONTROLPLANE_GATE_NAME,
    SECTION10_CONTROLPLANE_MANIFEST_KEY,
    SECTION10_CONTROLPLANE_PRODUCER_KEY,
    SECTION10_COST_GATE_NAME,
    SECTION10_COST_MANIFEST_KEY,
    SECTION10_COST_PRODUCER_KEY,
    register_section10_controlplane_gate,
    register_section10_cost_gate,
)
from app.release_gate.section17_rdp_gate import (  # noqa: E402
    SECTION17_RDP_GATE_NAME,
    SECTION17_RDP_MANIFEST_KEY,
    SECTION17_RDP_PRODUCER_KEY,
    register_section17_rdp_gate,
)


# ════════════════════════════════════════════════════════════════════════════
# 真血统建料（typed domain 对象·镜像各 section_gate 的 canonical 合规/坏样本）
# ════════════════════════════════════════════════════════════════════════════
def _base_manifest() -> dict:
    """一份已 promote 的 IDE run 的 run.json 最小骨架（镜像 ide.promote.promote_ide_run 写的 manifest）。"""

    return {"run_id": "ide_promote_runjson", "strategy_id": "ide_runjson", "status": "completed"}


def _compliant_rdp() -> RDPManifest:
    """完整诚实 RDP（过 §17 全部 4 门）：身份齐 + artifact hash + repro command + 可解析 DatasetVersion
    + IngestionSkill ref + 已列未验证残余。"""

    return RDPManifest(
        asset_ref="factor::alpha_x",
        asset_kind="factor",
        artifact_hash="sha256:abc123",
        reproducibility_command="python -m quantbt.repro --run alpha_x",
        dataset_versions=(
            DatasetVersionRef(dataset_id="ds_csi300", version="v1", manifest_sha256="h::1"),
        ),
        ingestion_skill_refs=("skill::tushare_daily",),
        unverified_residual=("执行成本未在 live 验证",),
    )


def _compliant_promotion(rdp: RDPManifest) -> PromotionClaim:
    """traceable 晋级断言：rdp_ref 解析到本 RDP（内容寻址 rdp_id）+ 资产对得上。"""

    return PromotionClaim(asset_ref=rdp.asset_ref, asset_kind="factor", rdp_ref=rdp.rdp_id)


def _compliant_factor_entry() -> FactorLibraryEntry:
    """clean 因子库条目（expression·非 model_body·无 §9 违例）。"""

    return FactorLibraryEntry(factor_ref="f::ok", kind=FactorAssetKind.EXPRESSION, ref="ts_zscore(close,20)")


def _compliant_generator() -> FactorGeneratorSpec:
    """clean 因子生成器（fitness 无守门指标 + 有独立 gatekeeper）。"""

    return FactorGeneratorSpec(
        generator_ref="gen::ok",
        structure_inputs=("close",),
        fitness_inputs=("complexity",),
        gatekeeper_ref="gk::holdout_sharpe",
    )


def _compliant_methodology() -> ValidationMethodologyRecord:
    """强标签 record 带成本证据（cost_model_refs 非空）→ 过 §10 成本门。"""

    return ValidationMethodologyRecord(
        validation_ref="v::strong_ok",
        claim_label="evidence_sufficient",
        sample_size=30,
        pbo_ref=None,
        dsr_ref=None,
        bootstrap_ci_ref=None,
        cpcv_ref=None,
        walk_forward_ref=None,
        purge_embargo_ref=None,
        honest_n_ref=None,
        multiple_testing_ref=None,
        cost_model_refs=("cm::a_share",),
        target_environment="research",
    )


def _compliant_tier_claim() -> Section10TierClaim:
    """严格档显强标签（rigorous 档不被控制面封顶·交下游证据门）→ 过 §10 控制面门。"""

    return Section10TierClaim(claimed_label="evidence_sufficient", tier=MethodologyTier.STRICT)


def _bad_methodology_no_cost() -> ValidationMethodologyRecord:
    """坏 run：声 evidence_sufficient（research）却缺 cost_model_refs/tca_ref（强标签缺成本）。"""

    return ValidationMethodologyRecord(
        validation_ref="v::strong_no_cost",
        claim_label="evidence_sufficient",
        sample_size=30,
        pbo_ref=None,
        dsr_ref=None,
        bootstrap_ci_ref=None,
        cpcv_ref=None,
        walk_forward_ref=None,
        purge_embargo_ref=None,
        honest_n_ref=None,
        multiple_testing_ref=None,
        cost_model_refs=(),  # ← 缺成本
        target_environment="research",
    )


def _bad_model_body_entry() -> FactorLibraryEntry:
    """坏 run：把 .pt 模型体当因子库条目（kind=model_body）。"""

    return FactorLibraryEntry(factor_ref="f::sneaky_model", kind=FactorAssetKind.MODEL_BODY, ref="models/alpha.pt")


def _compliant_kwargs() -> dict:
    """四节全合规的组装入参（真血统·过四门）。"""

    rdp = _compliant_rdp()
    return dict(
        rdp=rdp,
        promotion=_compliant_promotion(rdp),
        factor_library_entries=[_compliant_factor_entry()],
        factor_generators=[_compliant_generator()],
        validation_methodologies=[_compliant_methodology()],
        tier_claims=[_compliant_tier_claim()],
    )


# ════════════════════════════════════════════════════════════════════════════
# 门链建装（四门同链·各 producer key·测试态绿灯·绝非生产假绿灯）
# ════════════════════════════════════════════════════════════════════════════
_GATE_PRODUCER = {
    SECTION9_BOUNDARY_GATE_NAME: SECTION9_BOUNDARY_PRODUCER_KEY,
    SECTION10_COST_GATE_NAME: SECTION10_COST_PRODUCER_KEY,
    SECTION10_CONTROLPLANE_GATE_NAME: SECTION10_CONTROLPLANE_PRODUCER_KEY,
    SECTION17_RDP_GATE_NAME: SECTION17_RDP_PRODUCER_KEY,
}


def _chain_all() -> PromoteGateChain:
    """独立门链（不碰进程级 default_chain）·注册 §9/§10成本/§10控制面/§17 四门。"""

    chain = PromoteGateChain()
    register_section9_boundary_gate(chain)
    register_section10_cost_gate(chain)
    register_section10_controlplane_gate(chain)
    register_section17_rdp_gate(chain)
    return chain


def _all_green() -> ProducerStatusLedger:
    """四 producer key 全绿（仅本卡测试态·证明 enforce 行为为真·生产默认 None=红·绝非假绿灯）。"""

    led = ProducerStatusLedger()
    for key in _GATE_PRODUCER.values():
        led.mark_green(key)
    return led


def _verdict(result: ChainResult, gate_name: str):
    matches = [v for v in result.verdicts if v.gate_name == gate_name]
    assert len(matches) == 1, f"门链中应恰有一道 {gate_name} 裁定"
    return matches[0]


def _assemble_manifest(**kwargs) -> dict:
    """真血统 → 组装四节 → merge 进 base manifest（中心串 promote.py 的真路径形态）。"""

    base = _base_manifest()
    return assemble_promote_sections(base, **kwargs).apply_to(base)


# ════════════════════════════════════════════════════════════════════════════
# ① 组装真发生：四节记录就位（★ 变异目标——组装被注释 → 这些必红）
# ════════════════════════════════════════════════════════════════════════════
def test_section17_emitted_from_real_rdp():
    """★ 组装 §17：真 RDP/promotion → manifest 带 section17_rdp（含 rdp 子对象·真 artifact_hash）。"""

    rdp = _compliant_rdp()
    asm = assemble_promote_sections(_base_manifest(), rdp=rdp, promotion=_compliant_promotion(rdp))
    assert SECTION17_RDP_MANIFEST_KEY in asm.emitted
    section = asm.sections[SECTION17_RDP_MANIFEST_KEY]
    assert section["rdp"]["artifact_hash"] == "sha256:abc123"  # 真字段如实组装·非占位
    assert section["promotion"]["rdp_ref"] == rdp.rdp_id  # traceable


def test_section9_emitted_from_real_boundary_records():
    """★ 组装 §9：真因子库/生成器 → manifest 带 section9_boundary（族 dict 就位）。"""

    asm = assemble_promote_sections(
        _base_manifest(),
        factor_library_entries=[_compliant_factor_entry()],
        factor_generators=[_compliant_generator()],
    )
    assert SECTION9_BOUNDARY_MANIFEST_KEY in asm.emitted
    section = asm.sections[SECTION9_BOUNDARY_MANIFEST_KEY]
    assert section["factor_library_entries"][0]["factor_ref"] == "f::ok"
    assert section["factor_library_entries"][0]["kind"] == "expression"  # enum→value JSON-safe


def test_section10_cost_emitted_from_real_methodology():
    """★ 组装 §10 成本：真方法学 record → manifest 带 section10_cost（含真 claim_label + cost_model_refs）。"""

    asm = assemble_promote_sections(_base_manifest(), validation_methodologies=[_compliant_methodology()])
    assert SECTION10_COST_MANIFEST_KEY in asm.emitted
    rec = asm.sections[SECTION10_COST_MANIFEST_KEY]["validation_methodologies"][0]
    assert rec["claim_label"] == "evidence_sufficient"
    assert rec["cost_model_refs"] == ["cm::a_share"]  # tuple→list JSON-safe


def test_section10_controlplane_emitted_from_real_tier_claim():
    """★ 组装 §10 控制面：真档位声明 → manifest 带 section10_control_plane（含 tier + claimed_label）。"""

    asm = assemble_promote_sections(_base_manifest(), tier_claims=[_compliant_tier_claim()])
    assert SECTION10_CONTROLPLANE_MANIFEST_KEY in asm.emitted
    claim = asm.sections[SECTION10_CONTROLPLANE_MANIFEST_KEY]["tier_claims"][0]
    assert claim == {"tier": "strict", "claimed_label": "evidence_sufficient"}


def test_assemble_returns_assembled_sections_with_provenance():
    """组装返回 AssembledSections（含 emitted/absent/honest_gaps 诚实账）·apply_to 不改原 manifest。"""

    base = _base_manifest()
    asm = assemble_promote_sections(base, **_compliant_kwargs())
    assert isinstance(asm, AssembledSections)
    assert set(asm.emitted) == {
        SECTION17_RDP_MANIFEST_KEY, SECTION9_BOUNDARY_MANIFEST_KEY,
        SECTION10_COST_MANIFEST_KEY, SECTION10_CONTROLPLANE_MANIFEST_KEY,
    }
    assert asm.absent == ()
    merged = asm.apply_to(base)
    assert SECTION17_RDP_MANIFEST_KEY in merged
    assert SECTION17_RDP_MANIFEST_KEY not in base, "apply_to 绝不就地改原 manifest"


# ════════════════════════════════════════════════════════════════════════════
# ② 合规真实 run：四门 producer 绿 → ENFORCE 且仍全过（证明 enforce 不误拒诚实 run）
# ════════════════════════════════════════════════════════════════════════════
def test_compliant_run_passes_all_four_enforce_gates():
    """★ 合规 run 组装四节 → 四 producer 绿 → 四门 ENFORCE 且 rejected=False（每门 ok=True·不误拒）。"""

    manifest = _assemble_manifest(**_compliant_kwargs())
    result = _chain_all().evaluate(manifest, producer_status=_all_green())

    assert isinstance(result, ChainResult)
    assert result.rejected is False, f"合规 run 被误拒：{result.reason_text}"
    for gate_name in _GATE_PRODUCER:
        v = _verdict(result, gate_name)
        assert v.advisory_or_enforce == MODE_ENFORCE, f"{gate_name} 应 enforce（producer 绿）"
        assert v.ok is True, f"{gate_name} 合规却未过：{v.reason}"
        assert v.blocks is False
        assert v.producer_green is True


# ════════════════════════════════════════════════════════════════════════════
# ③ 坏 run：producer 绿 → 对应门 ENFORCE 必拒（blocks·ok=False·缺项精确·落 run.json verdict）
# ════════════════════════════════════════════════════════════════════════════
def test_bad_rdp_missing_artifact_hash_enforce_rejects():
    """★ 坏 §17：缺 artifact_hash 的 RDP 组装 → producer 绿 → ENFORCE 拒（'artifact_hash'）。"""

    bad_rdp = RDPManifest(
        asset_ref="factor::a", asset_kind="factor", artifact_hash="",  # ← 缺
        reproducibility_command="cmd",
        dataset_versions=(DatasetVersionRef("ds", "v1", "h"),),
        ingestion_skill_refs=("skill::x",), unverified_residual=("r",),
    )
    manifest = _assemble_manifest(rdp=bad_rdp)
    result = _chain_all().evaluate(manifest, producer_status=_all_green())
    assert result.rejected is True
    v = _verdict(result, SECTION17_RDP_GATE_NAME)
    assert v.advisory_or_enforce == MODE_ENFORCE and v.blocks is True and v.ok is False
    assert "artifact_hash" in v.missing
    # 落 run.json verdict（promote.py 写 result.to_dict() 进 manifest['promote_gate_chain']）。
    assert v.to_dict()["blocks"] is True


def test_bad_rdp_missing_dataset_version_enforce_rejects():
    """★ 坏 §17：缺可解析 DatasetVersion 的 RDP → producer 绿 → ENFORCE 拒（'dataset_versions'）。"""

    bad_rdp = RDPManifest(
        asset_ref="factor::a", asset_kind="factor", artifact_hash="sha256:x",
        reproducibility_command="cmd",
        dataset_versions=(),  # ← 缺
        ingestion_skill_refs=("skill::x",), unverified_residual=("r",),
    )
    manifest = _assemble_manifest(rdp=bad_rdp)
    result = _chain_all().evaluate(manifest, producer_status=_all_green())
    assert result.rejected is True
    v = _verdict(result, SECTION17_RDP_GATE_NAME)
    assert v.blocks is True and "dataset_versions" in v.missing


def test_self_promote_without_rdp_enforce_rejects():
    """★ 坏 §17：晋级断言在场却无 RDP（self-promote without RDP）→ producer 绿 → ENFORCE 拒（'rdp'）。"""

    manifest = _assemble_manifest(
        promotion=PromotionClaim(asset_ref="f::a", asset_kind="factor", rdp_ref="rdp_x")
    )
    result = _chain_all().evaluate(manifest, producer_status=_all_green())
    assert result.rejected is True
    v = _verdict(result, SECTION17_RDP_GATE_NAME)
    assert v.blocks is True and "rdp" in v.missing


def test_bad_model_body_factor_enforce_rejects():
    """★ 坏 §9：模型体入因子库 → producer 绿 → ENFORCE 拒（'model_body_in_factor_library'）。"""

    manifest = _assemble_manifest(factor_library_entries=[_bad_model_body_entry()])
    result = _chain_all().evaluate(manifest, producer_status=_all_green())
    assert result.rejected is True
    v = _verdict(result, SECTION9_BOUNDARY_GATE_NAME)
    assert v.advisory_or_enforce == MODE_ENFORCE and v.blocks is True and v.ok is False
    assert "model_body_in_factor_library" in v.missing


def test_bad_retired_factor_default_adoption_enforce_rejects():
    """★ 坏 §9（StrategyBook bundle）：退役因子被新策略默认采用 → producer 绿 → ENFORCE 拒。"""

    retired = FactorLibraryEntry(
        factor_ref="f::retired", kind=FactorAssetKind.EXPRESSION, ref="ts_mean(close,5)",
        lifecycle_state="RETIRED",
    )
    book = StrategyBookContract(
        strategy_book_ref="book::new_strat",
        factor_refs=("f::retired",), signal_refs=(), legs=(),
        default_factor_refs=("f::retired",),
    )
    bundle = Section9StrategyBook(book=book, factor_library={"f::retired": retired})
    manifest = _assemble_manifest(strategy_books=[bundle])
    result = _chain_all().evaluate(manifest, producer_status=_all_green())
    assert result.rejected is True
    v = _verdict(result, SECTION9_BOUNDARY_GATE_NAME)
    assert v.blocks is True and "retired_factor_default_adoption" in v.missing


def test_bad_strong_claim_missing_cost_enforce_rejects():
    """★ 坏 §10 成本：强标签缺成本 → producer 绿 → ENFORCE 拒（'s10_strong_claim_missing_cost_tca'）。"""

    manifest = _assemble_manifest(validation_methodologies=[_bad_methodology_no_cost()])
    result = _chain_all().evaluate(manifest, producer_status=_all_green())
    assert result.rejected is True
    v = _verdict(result, SECTION10_COST_GATE_NAME)
    assert v.advisory_or_enforce == MODE_ENFORCE and v.blocks is True and v.ok is False
    assert "s10_strong_claim_missing_cost_tca" in v.missing


def test_bad_relaxed_tier_strong_verdict_enforce_rejects():
    """★ 坏 §10 控制面：放宽档（loose）显强标签 → producer 绿 → ENFORCE 拒（封顶码）。"""

    manifest = _assemble_manifest(
        tier_claims=[Section10TierClaim(claimed_label="evidence_sufficient", tier=MethodologyTier.LOOSE)]
    )
    result = _chain_all().evaluate(manifest, producer_status=_all_green())
    assert result.rejected is True
    v = _verdict(result, SECTION10_CONTROLPLANE_GATE_NAME)
    assert v.advisory_or_enforce == MODE_ENFORCE and v.blocks is True and v.ok is False
    assert "s10_relaxed_tier_strong_verdict_capped" in v.missing


# ════════════════════════════════════════════════════════════════════════════
# ④ producer 红：同坏 run 只 advisory 记录不阻（flip_refused·绝不误拒·向后兼容）
# ════════════════════════════════════════════════════════════════════════════
def test_bad_run_red_producer_advisory_only_not_blocking():
    """★ producer 红（生产默认）→ 坏 run 四门全 advisory：记录但**不**阻断（flip_refused·绝不误拒）。"""

    bad_rdp = RDPManifest(
        asset_ref="factor::a", asset_kind="factor", artifact_hash="",
        reproducibility_command="cmd",
        dataset_versions=(DatasetVersionRef("ds", "v1", "h"),),
        ingestion_skill_refs=("skill::x",), unverified_residual=("r",),
    )
    manifest = _assemble_manifest(rdp=bad_rdp, validation_methodologies=[_bad_methodology_no_cost()])
    result = _chain_all().evaluate(manifest, producer_status=ProducerStatusLedger())  # 全红

    assert result.rejected is False, "producer 红 → 坏 run 只 advisory·绝不阻断"
    s17 = _verdict(result, SECTION17_RDP_GATE_NAME)
    assert s17.advisory_or_enforce == MODE_ADVISORY
    assert s17.flip_refused is True
    assert s17.ok is False and s17.blocks is False  # 门诚实记下未过·但 advisory 不阻断
    assert s17 in result.advisories


def test_absent_producer_status_advisory_only_no_false_green():
    """★ 无假绿灯：producer_status=None（生产默认）→ 坏 run 四门 advisory·producer_green=False·不阻断。"""

    manifest = _assemble_manifest(validation_methodologies=[_bad_methodology_no_cost()])
    result = _chain_all().evaluate(manifest, producer_status=None)
    assert result.rejected is False
    v = _verdict(result, SECTION10_COST_GATE_NAME)
    assert v.advisory_or_enforce == MODE_ADVISORY
    assert v.producer_green is False, "确认 producer 仍 RED（出厂红·无假绿灯）"


# ════════════════════════════════════════════════════════════════════════════
# ⑤ honest-absent：无该类资产 → 不发 section key → 门 ok=True（非违例·绝不误拒诚实 run）
# ════════════════════════════════════════════════════════════════════════════
def test_honest_absent_emits_no_section():
    """★ honest-absent：无任何真证据 → 四节全不发 key（绝不发空壳/占位 section 让门误判合规）。"""

    asm = assemble_promote_sections(_base_manifest())
    assert asm.emitted == ()
    assert set(asm.absent) == {
        SECTION17_RDP_MANIFEST_KEY, SECTION9_BOUNDARY_MANIFEST_KEY,
        SECTION10_COST_MANIFEST_KEY, SECTION10_CONTROLPLANE_MANIFEST_KEY,
    }
    assert asm.sections == {}
    # honest_gaps 软披露每个留空节（诚实账·不静默吞）。
    assert all("undeclared" in g for g in asm.honest_gaps)
    assert len(asm.honest_gaps) == 4


def test_honest_absent_run_not_false_rejected_even_when_green():
    """★ honest-absent + producer 全绿 → 四门 ENFORCE 但因「未声明」honest-bound ok=True（绝不误拒）。

    证明：把门翻 enforce 不会误伤「只是没那类资产」的诚实 run（无 §9/§10/§17 资产 ≠ 违例）。
    """

    manifest = _assemble_manifest()  # 无证据 → 无 section key
    result = _chain_all().evaluate(manifest, producer_status=_all_green())
    assert result.rejected is False
    for gate_name in _GATE_PRODUCER:
        v = _verdict(result, gate_name)
        assert v.advisory_or_enforce == MODE_ENFORCE
        assert v.ok is True, f"{gate_name} 误拒了未声明的诚实 run"


def test_partial_evidence_only_emits_present_sections():
    """honest-absent 颗粒度：只给 §9 证据 → 只发 section9_boundary·其余三节诚实留空（非全有或全无）。"""

    asm = assemble_promote_sections(_base_manifest(), factor_library_entries=[_compliant_factor_entry()])
    assert asm.emitted == (SECTION9_BOUNDARY_MANIFEST_KEY,)
    assert SECTION17_RDP_MANIFEST_KEY in asm.absent
    assert SECTION10_COST_MANIFEST_KEY in asm.absent


# ════════════════════════════════════════════════════════════════════════════
# ⑥ 不假绿灯：组装器只序列化真值·不洗白坏对象（核心非编造不变量）
# ════════════════════════════════════════════════════════════════════════════
def test_assembler_does_not_launder_bad_rdp():
    """★ 非编造：artifact_hash='' 的坏 RDP → 组装如实序列化空 artifact_hash（绝不补占位洗白）。

    把组装器改弱（缺 artifact_hash 时补个假值）→ 本断言转红——证明组装不洗白·门据真值拒。
    """

    bad_rdp = RDPManifest(
        asset_ref="factor::a", asset_kind="factor", artifact_hash="",
        reproducibility_command="cmd",
        dataset_versions=(DatasetVersionRef("ds", "v1", "h"),),
        ingestion_skill_refs=("skill::x",), unverified_residual=("r",),
    )
    asm = assemble_promote_sections(_base_manifest(), rdp=bad_rdp)
    assert asm.sections[SECTION17_RDP_MANIFEST_KEY]["rdp"]["artifact_hash"] == ""  # 如实空·不占位


def test_input_flip_flips_rejection_not_constant_gate():
    """反作弊（非常量门）：同结构 §10 成本 record，缺成本→拒 / 补成本→过（组装真序列化字段·门真读值）。"""

    led = _all_green()
    bad = _chain_all().evaluate(
        _assemble_manifest(validation_methodologies=[_bad_methodology_no_cost()]), producer_status=led
    )
    good = _chain_all().evaluate(
        _assemble_manifest(validation_methodologies=[_compliant_methodology()]), producer_status=led
    )
    assert bad.rejected is True and good.rejected is False, "输入翻转 → rejected 必须跟着翻"


def test_assembler_failcloses_on_bad_typed_input():
    """fail-closed：喂错类型对象（非 typed record）→ raise AssemblyError（不静默吞坏输入·不产占位 section）。"""

    with pytest.raises(AssemblyError):
        assemble_promote_sections(_base_manifest(), factor_library_entries=["not-a-record"])
    with pytest.raises(AssemblyError):
        assemble_promote_sections(_base_manifest(), rdp="not-an-rdp")  # type: ignore[arg-type]


def test_malformed_section_in_manifest_failcloses_through_enforce():
    """fail-closed 端到端：manifest 携 malformed §17 节（被填成 list）→ 经 enforce 门 → 拒（不静默 skip）。

    组装器只产 well-formed dict·此处直构 malformed 节，证明 enforce 路径对 malformed 同样 fail-closed。
    """

    manifest = {**_base_manifest(), SECTION17_RDP_MANIFEST_KEY: ["not", "a", "dict"]}
    result = _chain_all().evaluate(manifest, producer_status=_all_green())
    assert result.rejected is True
    v = _verdict(result, SECTION17_RDP_GATE_NAME)
    assert v.ok is False and v.blocks is True
    assert "section17_rdp_malformed" in v.missing


# ════════════════════════════════════════════════════════════════════════════
# ⑦ 冷导入安全（promote_assembler 经 release_gate/__init__ 既有冷导入环·须经 orchestrator 预热）
# ════════════════════════════════════════════════════════════════════════════
def test_promote_assembler_importable_after_orchestrator_prime():
    """全新解释器 import promote_assembler（先载 orchestrator 解 release_gate/__init__ 冷环）→ 成功。

    promote_assembler 顶层 import release_gate/__init__（既有冷导入环·非本卡引入）+ section_*_gate（cold-safe）。
    """

    backend_root = Path(__file__).resolve().parents[1]  # app/backend
    code = (
        "import app.agent.orchestrator; "
        "import app.release_gate.promote_assembler as m; "
        "assert m.assemble_promote_sections and m.AssembledSections and m.Section10TierClaim"
    )
    proc = subprocess.run(
        [sys.executable, "-c", code],
        cwd=str(backend_root),
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert proc.returncode == 0, (
        f"promote_assembler 应可 import:\nSTDOUT={proc.stdout}\nSTDERR={proc.stderr}"
    )
