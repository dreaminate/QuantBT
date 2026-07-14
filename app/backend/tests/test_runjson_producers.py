"""C-S17-RUNJSON-PRODUCERS · promote 门链 section 组装【producer 接线】对抗测试（RULES §2 种坏门必抓 + §3 诚实）。

这是把 §6/§9/§10/§17 节门从 advisory 翻 enforce 的**证据 producer 接线测试**：证明
`promote_assembler.assemble_promote_sections` 从**真血统/真运行产物**（typed domain 对象）如实组装出
各 section_*_gate 的 producer 契约 dict，让门有真对象可判——合规 run 过、坏 run 拒、honest-absent 不误拒。
转绿 = 中心据本测试在 `ide/promote.py` 的 `producer_status` 上 `mark_green(对应 producer key)`，门即翻 enforce
（SA-2 LOCKED 决策 1·`mode==ENFORCE ⟹ producer_green==True` 不可违）。

可证伪验收（construction-map C-S17-RUNJSON-PRODUCERS）：
  · 合规真实 run（完整 §6 数学链 / 完整 RDP+traceable promotion / clean §9 / 强标签带成本 / 严格档强 verdict）
    → 组装后五节记录就位 → 五 producer 绿 → 五门 ENFORCE 且**仍全过**（rejected=False·ok=True·证明
    enforce 不误拒诚实 run）。
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

import datetime as dt
import hashlib
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
from app.lineage.ids import content_hash  # noqa: E402
from app.lineage.spine import (  # noqa: E402
    ConsistencyCheck,
    MathematicalArtifact,
    TheoryImplementationBinding,
)
from app.research_os.factor_strategy_boundary import (  # noqa: E402
    FactorAssetKind,
    FactorGeneratorSpec,
    FactorLibraryEntry,
    StrategyBookContract,
)
from app.research_os.methodology_validation import ValidationMethodologyRecord  # noqa: E402
from app.research_os.rdp_reproduction import (  # noqa: E402
    PersistentRDPReproductionReceiptStore,
    RDPReproductionSourceEvidence,
    RDPReproductionVerificationSnapshot,
    ResolvedRDPReproductionSource,
    rdp_manifest_hash,
)
from app.research_os.spine import Section6RecordError  # noqa: E402
from app.research_os.trust_layer import TrustClaimRecord  # noqa: E402
from app.research_os.engineering_standards import MockHonestyRecord  # noqa: E402
from app.release_gate.promote_assembler import (  # noqa: E402
    AssembledSections,
    AssemblyError,
    Section6PromotionClaim,
    Section9StrategyBook,
    Section10TierClaim,
    assemble_promote_sections,
)
from app.release_gate.promote_gate_chain import ChainResult, PromoteGateChain  # noqa: E402
from app.release_gate.section6_mathchain_gate import (  # noqa: E402
    SECTION6_MATHCHAIN_GATE_NAME,
    SECTION6_MATHCHAIN_MANIFEST_KEY,
    SECTION6_MATHCHAIN_PRODUCER_KEY,
    register_section6_mathchain_gate,
)
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
from app.release_gate.section13_trust_gate import (  # noqa: E402
    SECTION13_TRUST_GATE_NAME,
    SECTION13_TRUST_MANIFEST_KEY,
    SECTION13_TRUST_PRODUCER_KEY,
    register_section13_trust_gate,
)
from app.release_gate.section16_engineering_standards_gate import (  # noqa: E402
    SECTION16_ENGINEERING_STANDARDS_GATE_NAME,
    SECTION16_ENGINEERING_STANDARDS_MANIFEST_KEY,
    SECTION16_ENGINEERING_STANDARDS_PRODUCER_KEY,
    register_section16_engineering_standards_gate,
)
from app.release_gate.section17_rdp_gate import (  # noqa: E402
    RDP_REPRODUCTION_RECEIPT_MANIFEST_KEY,
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
    base = dict(binding_id=_binding().binding_id, check_type="numerical", result="pass")
    base.update(overrides)
    return ConsistencyCheck(**base)


def _compliant_mathchain_claim() -> Section6PromotionClaim:
    return Section6PromotionClaim(
        requested_label="evidence_sufficient",
        asset_ref="factor::alpha_x",
        artifact=_artifact(),
        binding=_binding(),
        consistency_checks=(_check(),),
    )


def _bad_mathchain_claim_missing_check() -> Section6PromotionClaim:
    return Section6PromotionClaim(
        requested_label="evidence_sufficient",
        asset_ref="factor::broken_math",
        artifact=_artifact(),
        binding=_binding(),
        consistency_checks=(),
    )


def _compliant_rdp() -> RDPManifest:
    """完整诚实 RDP（过 §17 全部 5 门）：结构齐全并由当前重现收据绑定。"""

    return RDPManifest(
        research_question="Does alpha_x retain evidence after the declared validation run?",
        graph_refs=("research_graph:alpha_x:v1",),
        data_refs=("dataset:ds_csi300",),
        dataset_version_refs=("dataset_version:ds_csi300:v1",),
        market_data_use_validation_refs=("market_data_use:alpha_x:v1",),
        mathematical_refs=("math_artifact:alpha_x:v1",),
        theory_binding_refs=("theory_binding:alpha_x:v1",),
        consistency_check_refs=("consistency_check:alpha_x:v1",),
        asset_refs=("factor::alpha_x",),
        code_refs=("code:quantbt.repro:alpha_x:v1",),
        environment_lock_ref="environment_lock:alpha_x:v1",
        test_refs=("pytest:test_runjson_producers:alpha_x",),
        run_refs=("run:alpha_x:v1",),
        honest_n_refs=("honest_n:alpha_x:v1",),
        cost_and_execution_assumptions=("cost_model:alpha_x:research",),
        attribution_refs=("attribution:alpha_x:v1",),
        known_limits=("execution cost has not been validated live",),
        verifier_verdict_ref="verifier_verdict:alpha_x:v1",
        compiler_artifact_refs=("compiler_artifact:alpha_x:v1",),
        mathematical_spine_chain_refs=("math_spine_chain:alpha_x:v1",),
        goal_entrypoint_coverage_refs=("goal_entrypoint_coverage:alpha_x:v1",),
        source_file_refs=("source_file:quantbt.repro:alpha_x:v1",),
        asset_ref="factor::alpha_x",
        asset_kind="factor",
        artifact_hash="sha256:abc123",
        reproducibility_command="python -m quantbt.repro --run alpha_x",
        dataset_versions=(
            DatasetVersionRef(dataset_id="ds_csi300", version="v1", manifest_sha256="h::1"),
        ),
        ingestion_skill_refs=("skill::tushare_daily",),
        unverified_residual=("执行成本未在 live 验证",),
        seed=7,
    )


def _compliant_reproduction_envelope(
    tmp_path: Path,
    rdp: RDPManifest,
) -> tuple[dict[str, object], PersistentRDPReproductionReceiptStore]:
    """Mint a real persisted receipt through the trusted-loader authority."""

    owner = "owner:runjson-producers"
    source_result_content_hash = content_hash(
        {"run_id": "ide_promote_runjson", "result": "alpha_x"}
    )
    runner_ref = "trusted_runner:runjson_producers:v1"

    def source_resolver(
        loader_owner: str,
        loader_manifest: RDPManifest,
        loader_source_hash: str,
    ) -> ResolvedRDPReproductionSource:
        assert loader_owner == owner
        strategy_code = "pass\n"
        return ResolvedRDPReproductionSource(
            evidence=RDPReproductionSourceEvidence(
                package_id=loader_manifest.package_id,
                source_run_ref=loader_manifest.run_refs[0],
                source_run_id=loader_manifest.run_refs[0].split(":", 1)[-1],
                source_file_ref=loader_manifest.source_file_refs[0],
                manifest_hash=rdp_manifest_hash(loader_manifest),
                source_artifact_hash=loader_manifest.artifact_hash,
                source_integrity_hash="sha16:" + "1" * 16,
                source_bundle_index_sha256="sha256:" + "2" * 64,
                source_run_manifest_sha256="sha256:" + "3" * 64,
                source_strategy_sha256="sha256:"
                + hashlib.sha256(strategy_code.encode()).hexdigest(),
                source_result_sha256="sha256:" + "4" * 64,
                expected_replay_result_sha256="sha256:" + "5" * 64,
                source_portfolio_sha256="sha256:" + "6" * 64,
                source_result_content_hash=loader_source_hash,
                expected_replay_artifact_hash="sha256:" + "7" * 64,
            ),
            strategy_code=strategy_code,
        )

    def verification_loader(
        loader_owner: str,
        loader_manifest: RDPManifest,
        spec,
        resolved_source,
    ) -> RDPReproductionVerificationSnapshot:
        assert loader_owner == owner
        assert resolved_source.evidence.source_evidence_hash == spec.source_evidence_hash
        verified_at = dt.datetime.now(dt.UTC)
        return RDPReproductionVerificationSnapshot(
            package_id=spec.package_id,
            manifest_hash=spec.manifest_hash,
            spec_hash=spec.spec_hash,
            expected_artifact_hash=spec.artifact_hash,
            observed_artifact_hash=spec.artifact_hash,
            expected_source_result_content_hash=spec.source_result_content_hash,
            observed_source_result_content_hash=spec.source_result_content_hash,
            expected_source_integrity_hash=spec.source_integrity_hash,
            observed_source_integrity_hash=spec.source_integrity_hash,
            expected_source_strategy_sha256=spec.source_strategy_sha256,
            observed_source_strategy_sha256=spec.source_strategy_sha256,
            expected_replay_result_sha256=spec.expected_replay_result_sha256,
            observed_replay_result_sha256=spec.expected_replay_result_sha256,
            expected_replay_artifact_hash=spec.expected_replay_artifact_hash,
            observed_replay_artifact_hash=spec.expected_replay_artifact_hash,
            environment_lock_ref=spec.environment_lock_ref,
            outcome="passed",
            passed=True,
            runner_ref=runner_ref,
            evidence_refs=("reproduction_evidence:runjson_producers:alpha_x:v1",),
            verified_at_utc=verified_at.isoformat(),
            valid_until_utc=(verified_at + dt.timedelta(minutes=5)).isoformat(),
        )

    receipts = PersistentRDPReproductionReceiptStore(
        tmp_path / "rdp_reproduction_receipts.jsonl",
        verification_loader,
        source_resolver=source_resolver,
        allowed_runner_refs=(runner_ref,),
    )
    receipt = receipts.record_current(
        owner_user_id=owner,
        manifest=rdp,
        source_result_content_hash=source_result_content_hash,
    )
    assert receipts.current_passed(
        owner_user_id=owner,
        manifest=rdp,
        source_result_content_hash=source_result_content_hash,
    ) == receipt
    return (
        {
            "source": {
                "owner_user_id": owner,
                "result_content_hash": source_result_content_hash,
            },
            RDP_REPRODUCTION_RECEIPT_MANIFEST_KEY: receipt.to_open_dict(),
        },
        receipts,
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


def _compliant_trust_claim() -> TrustClaimRecord:
    """clean §13 信任 claim（弱标签 + 风险默认可见）→ 无 trust_layer 违例。"""

    return TrustClaimRecord(
        claim_ref="trust::ok",
        claim_label="unverified_result",
        evidence_refs=(),
        weakness_refs=("risk::drawdown",),
        weakness_visible_by_default=True,
    )


def _bad_trust_claim() -> TrustClaimRecord:
    """坏 §13：wishful 压力下强标签、缺证据、弱点默认隐藏。"""

    return TrustClaimRecord(
        claim_ref="trust::bad",
        claim_label="evidence_sufficient",
        evidence_refs=(),
        weakness_refs=("risk::hidden",),
        weakness_visible_by_default=False,
        pressure_context="user wishful thinking wants a strong conclusion",
    )


def _compliant_mock_record() -> MockHonestyRecord:
    """clean §16 mock honesty record：生产成功未靠 mock/template 兜底。"""

    return MockHonestyRecord(
        record_ref="mock::ok",
        production_profile=True,
        mock_used=False,
        mock_label_ref=None,
        fallback_reason_ref=None,
        template_response=False,
        production_success_claim=True,
    )


def _bad_mock_record() -> MockHonestyRecord:
    """坏 §16：生产档用 mock，且声称生产成功。"""

    return MockHonestyRecord(
        record_ref="mock::bad",
        production_profile=True,
        mock_used=True,
        mock_label_ref=None,
        fallback_reason_ref=None,
        template_response=False,
        production_success_claim=True,
    )


def _compliant_kwargs() -> dict:
    """七节全合规的组装入参（真血统·过七门）。"""

    rdp = _compliant_rdp()
    return dict(
        mathchain_claims=[_compliant_mathchain_claim()],
        rdp=rdp,
        promotion=_compliant_promotion(rdp),
        factor_library_entries=[_compliant_factor_entry()],
        factor_generators=[_compliant_generator()],
        validation_methodologies=[_compliant_methodology()],
        tier_claims=[_compliant_tier_claim()],
        trust_claims=[_compliant_trust_claim()],
        mock_records=[_compliant_mock_record()],
        # This integration fixture stands in for canonical resolver receipts;
        # typed payload presence alone no longer turns producers green.
        verified_producer_keys=tuple(_GATE_PRODUCER.values()),
    )


# ════════════════════════════════════════════════════════════════════════════
# 门链建装（五门同链·各 producer key·测试态绿灯·绝非生产假绿灯）
# ════════════════════════════════════════════════════════════════════════════
_GATE_PRODUCER = {
    SECTION6_MATHCHAIN_GATE_NAME: SECTION6_MATHCHAIN_PRODUCER_KEY,
    SECTION9_BOUNDARY_GATE_NAME: SECTION9_BOUNDARY_PRODUCER_KEY,
    SECTION10_COST_GATE_NAME: SECTION10_COST_PRODUCER_KEY,
    SECTION10_CONTROLPLANE_GATE_NAME: SECTION10_CONTROLPLANE_PRODUCER_KEY,
    SECTION13_TRUST_GATE_NAME: SECTION13_TRUST_PRODUCER_KEY,
    SECTION16_ENGINEERING_STANDARDS_GATE_NAME: SECTION16_ENGINEERING_STANDARDS_PRODUCER_KEY,
    SECTION17_RDP_GATE_NAME: SECTION17_RDP_PRODUCER_KEY,
}


def _chain_all(
    reproduction_receipt_store: PersistentRDPReproductionReceiptStore | None = None,
) -> PromoteGateChain:
    """独立门链（不碰进程级 default_chain）·注册 §6/§9/§10/§13/§16/§17 七门。"""

    chain = PromoteGateChain()
    register_section6_mathchain_gate(chain)
    register_section9_boundary_gate(chain)
    register_section10_cost_gate(chain)
    register_section10_controlplane_gate(chain)
    register_section13_trust_gate(chain)
    register_section16_engineering_standards_gate(chain)
    register_section17_rdp_gate(
        chain,
        reproduction_receipt_store=reproduction_receipt_store,
    )
    return chain


def _all_green() -> ProducerStatusLedger:
    """七 producer key 全绿（仅本卡测试态·证明 enforce 行为为真·生产默认 None=红·绝非假绿灯）。"""

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
# ① 组装真发生：五节记录就位（★ 变异目标——组装被注释 → 这些必红）
# ════════════════════════════════════════════════════════════════════════════
def test_section6_emitted_from_real_mathchain_claim():
    """★ 组装 §6：真数学链 claim → manifest 带 section6_mathchain（含真 ConsistencyCheck）。"""

    asm = assemble_promote_sections(
        _base_manifest(),
        mathchain_claims=[_compliant_mathchain_claim()],
    )
    assert SECTION6_MATHCHAIN_MANIFEST_KEY in asm.emitted
    section = asm.sections[SECTION6_MATHCHAIN_MANIFEST_KEY]
    claim = section["promotion_claims"][0]
    assert claim["asset_ref"] == "factor::alpha_x"
    assert claim["binding"]["theory_ref"] == "theory::alpha_x"
    assert claim["consistency_checks"][0]["result"] == "pass"


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


def test_section13_emitted_from_real_trust_records():
    """★ 组装 §13：真 TrustClaimRecord → manifest 带 section13_trust（弱点默认可见）。"""

    asm = assemble_promote_sections(_base_manifest(), trust_claims=[_compliant_trust_claim()])
    assert SECTION13_TRUST_MANIFEST_KEY in asm.emitted
    claim = asm.sections[SECTION13_TRUST_MANIFEST_KEY]["trust_claims"][0]
    assert claim["claim_ref"] == "trust::ok"
    assert claim["weakness_visible_by_default"] is True


def test_section16_emitted_from_real_engineering_records():
    """★ 组装 §16：真 MockHonestyRecord → manifest 带 section16_engineering_standards。"""

    asm = assemble_promote_sections(_base_manifest(), mock_records=[_compliant_mock_record()])
    assert SECTION16_ENGINEERING_STANDARDS_MANIFEST_KEY in asm.emitted
    rec = asm.sections[SECTION16_ENGINEERING_STANDARDS_MANIFEST_KEY]["mock_records"][0]
    assert rec["record_ref"] == "mock::ok"
    assert rec["production_success_claim"] is True


def test_assemble_returns_assembled_sections_with_provenance():
    """组装返回 AssembledSections（含 emitted/absent/honest_gaps 诚实账）·apply_to 不改原 manifest。"""

    base = _base_manifest()
    asm = assemble_promote_sections(base, **_compliant_kwargs())
    assert isinstance(asm, AssembledSections)
    assert set(asm.emitted) == {
        SECTION6_MATHCHAIN_MANIFEST_KEY, SECTION17_RDP_MANIFEST_KEY, SECTION9_BOUNDARY_MANIFEST_KEY,
        SECTION10_COST_MANIFEST_KEY, SECTION10_CONTROLPLANE_MANIFEST_KEY,
        SECTION13_TRUST_MANIFEST_KEY, SECTION16_ENGINEERING_STANDARDS_MANIFEST_KEY,
    }
    assert asm.absent == ()
    merged = asm.apply_to(base)
    assert SECTION17_RDP_MANIFEST_KEY in merged
    assert SECTION17_RDP_MANIFEST_KEY not in base, "apply_to 绝不就地改原 manifest"
    produced = asm.producer_status()
    for producer_key in _GATE_PRODUCER.values():
        assert produced.is_green(producer_key) is True


# ════════════════════════════════════════════════════════════════════════════
# ② 合规真实 run：七门 producer 绿 → ENFORCE 且仍全过（证明 enforce 不误拒诚实 run）
# ════════════════════════════════════════════════════════════════════════════
def test_compliant_run_passes_all_seven_enforce_gates(tmp_path: Path):
    """★ 合规 run 组装七节 → 七 producer 绿 → 七门 ENFORCE 且 rejected=False（每门 ok=True·不误拒）。"""

    kwargs = _compliant_kwargs()
    reproduction_envelope, reproduction_store = _compliant_reproduction_envelope(
        tmp_path,
        kwargs["rdp"],
    )
    base = {
        **_base_manifest(),
        **reproduction_envelope,
    }
    asm = assemble_promote_sections(base, **kwargs)
    manifest = asm.apply_to(base)
    result = _chain_all(reproduction_store).evaluate(
        manifest,
        producer_status=asm.producer_status(),
    )

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
def test_bad_mathchain_missing_consistency_check_enforce_rejects():
    """★ 坏 §6：强标签缺 ConsistencyCheck → producer 绿 → ENFORCE 拒（'consistency-present'）。"""

    manifest = _assemble_manifest(mathchain_claims=[_bad_mathchain_claim_missing_check()])
    result = _chain_all().evaluate(manifest, producer_status=_all_green())
    assert result.rejected is True
    v = _verdict(result, SECTION6_MATHCHAIN_GATE_NAME)
    assert v.advisory_or_enforce == MODE_ENFORCE and v.blocks is True and v.ok is False
    assert any("consistency-present" in m for m in v.missing)


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


def test_bad_trust_claim_enforce_rejects():
    """★ 坏 §13：wishful 强标签 + 缺证据 + 隐藏弱点 → producer 绿 → ENFORCE 拒。"""

    manifest = _assemble_manifest(trust_claims=[_bad_trust_claim()])
    result = _chain_all().evaluate(manifest, producer_status=_all_green())
    assert result.rejected is True
    v = _verdict(result, SECTION13_TRUST_GATE_NAME)
    assert v.advisory_or_enforce == MODE_ENFORCE and v.blocks is True and v.ok is False
    assert "strong_claim_without_evidence" in v.missing
    assert "wishful_pressure_strong_conclusion" in v.missing
    assert "weakness_hidden_by_default" in v.missing


def test_bad_engineering_mock_enforce_rejects():
    """★ 坏 §16：生产档 mock 兜底且声称成功 → producer 绿 → ENFORCE 拒。"""

    manifest = _assemble_manifest(mock_records=[_bad_mock_record()])
    result = _chain_all().evaluate(manifest, producer_status=_all_green())
    assert result.rejected is True
    v = _verdict(result, SECTION16_ENGINEERING_STANDARDS_GATE_NAME)
    assert v.advisory_or_enforce == MODE_ENFORCE and v.blocks is True and v.ok is False
    assert "mock_block_missing_label_or_reason" in v.missing
    assert "production_profile_mock_fallback" in v.missing
    assert "template_or_mock_false_production_success" in v.missing


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
    """★ honest-absent：无任何真证据 → 七节全不发 key（绝不发空壳/占位 section 让门误判合规）。"""

    asm = assemble_promote_sections(_base_manifest())
    assert asm.emitted == ()
    assert set(asm.absent) == {
        SECTION6_MATHCHAIN_MANIFEST_KEY, SECTION17_RDP_MANIFEST_KEY, SECTION9_BOUNDARY_MANIFEST_KEY,
        SECTION10_COST_MANIFEST_KEY, SECTION10_CONTROLPLANE_MANIFEST_KEY,
        SECTION13_TRUST_MANIFEST_KEY, SECTION16_ENGINEERING_STANDARDS_MANIFEST_KEY,
    }
    assert asm.sections == {}
    # honest_gaps 软披露每个留空节（诚实账·不静默吞）。
    assert all("undeclared" in g for g in asm.honest_gaps)
    assert len(asm.honest_gaps) == 7
    assert asm.producer_status().as_mapping() == {}


def test_honest_absent_run_not_false_rejected_even_when_green():
    """★ honest-absent + producer 全绿 → 七门 ENFORCE 但因「未声明」honest-bound ok=True（绝不误拒）。

    证明：把门翻 enforce 不会误伤「只是没那类资产」的诚实 run（无 §6/§9/§10/§17 资产 ≠ 违例）。
    """

    manifest = _assemble_manifest()  # 无证据 → 无 section key
    result = _chain_all().evaluate(manifest, producer_status=_all_green())
    assert result.rejected is False
    for gate_name in _GATE_PRODUCER:
        v = _verdict(result, gate_name)
        assert v.advisory_or_enforce == MODE_ENFORCE
        assert v.ok is True, f"{gate_name} 误拒了未声明的诚实 run"


def test_partial_evidence_only_emits_present_sections():
    """honest-absent 颗粒度：只给 §9 证据 → 只发 section9_boundary·其余节诚实留空（非全有或全无）。"""

    asm = assemble_promote_sections(
        _base_manifest(),
        factor_library_entries=[_compliant_factor_entry()],
        verified_producer_keys=(SECTION9_BOUNDARY_PRODUCER_KEY,),
    )
    assert asm.emitted == (SECTION9_BOUNDARY_MANIFEST_KEY,)
    assert SECTION17_RDP_MANIFEST_KEY in asm.absent
    assert SECTION10_COST_MANIFEST_KEY in asm.absent
    assert asm.producer_status().is_green(SECTION9_BOUNDARY_PRODUCER_KEY) is True
    assert asm.producer_status().is_green(SECTION13_TRUST_PRODUCER_KEY) is False


def test_typed_section_payload_without_resolver_receipt_stays_producer_red():
    asm = assemble_promote_sections(
        _base_manifest(),
        factor_library_entries=[_compliant_factor_entry()],
    )
    assert asm.emitted == (SECTION9_BOUNDARY_MANIFEST_KEY,)
    assert asm.producer_status().is_green(SECTION9_BOUNDARY_PRODUCER_KEY) is False


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

    with pytest.raises(Section6RecordError):
        assemble_promote_sections(_base_manifest(), mathchain_claims=["not-a-claim"])  # type: ignore[list-item]
    with pytest.raises(AssemblyError):
        assemble_promote_sections(_base_manifest(), factor_library_entries=["not-a-record"])
    with pytest.raises(AssemblyError):
        assemble_promote_sections(_base_manifest(), rdp="not-an-rdp")  # type: ignore[arg-type]
    with pytest.raises(AssemblyError):
        assemble_promote_sections(_base_manifest(), trust_claims=["not-a-record"])
    with pytest.raises(AssemblyError):
        assemble_promote_sections(_base_manifest(), mock_records=["not-a-record"])


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
        "assert m.assemble_promote_sections and m.AssembledSections and m.Section6PromotionClaim and m.TrustClaimRecord"
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
