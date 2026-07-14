"""SA-3 promote 门链**接进真 promote 路径**（gate_registry + ide/promote）· 对抗测试。

中心串行第三波：`promote_gate_chain` seam + 各节门 check 已落地（test_promote_gate_chain /
test_section9_boundary_gate / test_section10_methodology_gate 守 seam/check 本身）。本卡把它们经
**单一注册收口** `release_gate.gate_registry` 接进 `ide.promote.promote_ide_run`——每个 promoted run
的 run.json 现携带 `promote_gate_chain` 裁决。

advisory-first 不变量（本测试守门·守 LOCKED 决策 1 + RULES.project「未验证≠已验证」）：
  ① 经 promote_ide_run 跑出一个 §9 / §10 违例 + **producer 全红** → 裁决落 run.json 作 **advisory**
     （记录·flip_refused·**绝不阻断**）·promote 仍成功落盘；
  ② **同一违例** + 对应 producer 在 ledger 标绿 → 同门翻 ENFORCE → **阻断**（promote 抛 PromoteError·
     被拒晋级不留 run.json·绝不冒充成功 run）；
  ③ 向后兼容：clean manifest（无 §9/§10/§13 结构）→ 全门 advisory ok=True·promote 与既有完全一致；
  ④ 无任何 producer 假绿灯：默认 producer_status=None → 全门 advisory + producer_green=False。

★ mutation 三态（已手验·见任务报告）：把 ide/promote.py 的 SA-3 门链块（evaluate+attach+reject）整段
  注释掉（弱化接线·裁决不再 evaluate/attach）→ `test_s9_violation_recorded_advisory_while_producer_red`
  与 `test_s9_violation_blocks_when_producer_green` 转 RED → 还原 → GREEN。

诚实说明：本卡**不建 producer**（把真实 §9/§10 资产写进 manifest 那层 = 独立卡·LOCKED 决策 1）。测试
用一个薄 wrapper 在 evaluate 边界把 §9/§10 结构注入 manifest，**模拟未来 producer 填值**——被评估的门、
门链、SA-2 策略全是真组件（advisory/enforce 行为 100% 真）。生产路径无 producer → manifest 无 §9/§10
结构 → 三门 nothing-declared 全过（advisory）。
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import subprocess
import sys
from dataclasses import replace
from pathlib import Path

import pytest

# 冷导入预热（既有循环·非本卡引入）：导入 app.governance.* 前先全载 orchestrator 解环——与
# test_promote_gate_chain.py 同款顺序（app.governance 包 __init__ 经 spine_invariants 触达 orchestrator）。
import app.agent.orchestrator  # noqa: F401  (prime: 解 app.governance 既有冷导入循环)
from conftest import build_verified_spine_chain

from app.governance.enforcement_policy import ProducerStatusLedger  # noqa: E402
from app.delivery import DatasetVersionRef  # noqa: E402
from app.ide.promote import PromoteError, promote_ide_run  # noqa: E402
from app.ide.promotion_evidence import (  # noqa: E402
    CanonicalPromotionEvidenceResolver,
    PromotionEvidenceError,
)
from app.research_os import (  # noqa: E402
    ActorSource,
    DataUpdateStandardRecord,
    DefinitionStatus,
    EngineeringStandardsRunRecord,
    EntrySource,
    EvidenceStatus,
    FactorAssetKind,
    FactorGenerationRecord,
    FactorGeneratorSpec,
    FactorLibraryEntry,
    FatalRuntimeStandardRecord,
    GovernanceStatus,
    LLMReplayStandardRecord,
    MathematicalSpineChainRecord,
    MockHonestyRecord,
    PerformanceBaselineMeasurement,
    PersistentEngineeringStandardsRegistry,
    PersistentSection9EvidenceRegistry,
    PersistentSignalValidationRegistry,
    PersistentMethodologyCalculatorRegistry,
    PersistentMethodologyRuntimeDrillRegistry,
    PersistentValidationDepthRegistry,
    PersistentValidationMethodologyRegistry,
    PersistentTrustDisclosureRegistry,
    PersistentTrustPressureRunRegistry,
    PersistentTrustReleaseApprovalRegistry,
    PersistentTrustReleaseCheckRegistry,
    PersistentTrustReleaseGateRegistry,
    PersistentRDPStore,
    PersistentResearchGraphStore,
    QRORecord,
    QROType,
    RDPManifest,
    ResearchGraphCommand,
    RuntimeStatus,
    Section9EvidenceSnapshot,
    SignalPerformanceValidationRecord,
    SignalProtocolRecord,
    SignalValidationVerdict,
    StrategyBookContract,
    StrategyLegContract,
    TheoryImplementationStandardRecord,
    ValidationDepthRecord,
    ValidationMethodologyRecord,
    calculate_conformal,
    calculate_cpcv,
    calculate_tca,
    record_runtime_drill,
    record_external_expert_review,
    record_trust_pressure_run,
    record_trust_release_approval,
)
from app.release_gate.gate_registry import (  # noqa: E402
    ensure_default_chain,
    register_all_gates,
)
from app.release_gate.promote_gate_chain import (  # noqa: E402
    PromoteGateChain,
    reset_default_chain,
)
from app.release_gate.section6_mathchain_gate import (  # noqa: E402
    SECTION6_MATHCHAIN_GATE_NAME,
    SECTION6_MATHCHAIN_MANIFEST_KEY,
)
from app.release_gate.section9_boundary_gate import (  # noqa: E402
    SECTION9_BOUNDARY_GATE_NAME,
    SECTION9_BOUNDARY_MANIFEST_KEY,
    SECTION9_BOUNDARY_PRODUCER_KEY,
)
from app.release_gate.section10_methodology_gate import (  # noqa: E402
    SECTION10_CONTROLPLANE_GATE_NAME,
    SECTION10_CONTROLPLANE_MANIFEST_KEY,
    SECTION10_CONTROLPLANE_PRODUCER_KEY,
    SECTION10_COST_GATE_NAME,
    SECTION10_COST_MANIFEST_KEY,
)
from app.release_gate.section13_trust_gate import (  # noqa: E402
    SECTION13_TRUST_GATE_NAME,
    SECTION13_TRUST_MANIFEST_KEY,
)
from app.release_gate.section16_engineering_standards_gate import (  # noqa: E402
    SECTION16_ENGINEERING_STANDARDS_GATE_NAME,
    SECTION16_ENGINEERING_STANDARDS_MANIFEST_KEY,
)
from app.release_gate.section17_rdp_gate import (  # noqa: E402
    SECTION17_RDP_GATE_NAME,
    SECTION17_RDP_MANIFEST_KEY,
)
from app.research_os.rdp_reproduction import (  # noqa: E402
    PersistentRDPReproductionReceiptStore,
    RDPReproductionSourceEvidence,
    RDPReproductionVerificationSnapshot,
    ResolvedRDPReproductionSource,
    rdp_manifest_hash,
)

# —— 经 canonical 测试证明的违例 fixture（与 test_section9/10 同源·此处只搬运不重造）——
_S9_VIOLATION = {
    "factor_library_entries": [
        {"factor_ref": "f::sneaky_model", "kind": "model_body", "ref": "models/alpha.pt"}
    ]
}
_S9_CODE = "model_body_in_factor_library"

_S10CP_VIOLATION = {"tier_claims": [{"tier": "loose", "claimed_label": "evidence_sufficient"}]}
_S10CP_CODE = "s10_relaxed_tier_strong_verdict_capped"

_ALL_GATE_NAMES = {
    SECTION6_MATHCHAIN_GATE_NAME,  # §6 数学链发版门经 gate_registry 落地接进 promote 路径（C-S6-MATHCHAIN·advisory-first）
    SECTION9_BOUNDARY_GATE_NAME,
    SECTION10_COST_GATE_NAME,
    SECTION10_CONTROLPLANE_GATE_NAME,
    SECTION13_TRUST_GATE_NAME,  # §13 信任发版门经 gate_registry 落地接进 promote 路径（C-S13-RELEASE-ENFORCE）
    SECTION16_ENGINEERING_STANDARDS_GATE_NAME,  # §16 工程标准发版门经 gate_registry 落地接进 promote 路径（C-S16-ENGSTD-WIRE·advisory-first）
    SECTION17_RDP_GATE_NAME,  # §17 RDP 发版门经 gate_registry 落地接进 promote 路径（C-S17-RDP-PROMOTE-ENFORCE）
}
_REPRODUCTION_RUNNER = "backend_runner:rdp_reproduction:v1"


@pytest.fixture(autouse=True)
def _reset_chain():
    """每个用例前后清空进程级默认门链（隔离·让 ensure_default_chain 每次从空重填·防跨用例污染）。"""

    reset_default_chain()
    yield
    reset_default_chain()


def _curve(n: int) -> list[dict]:
    """最小可 promote 的 equity_curve（镜像 test_promote_release_advisory._curve）。"""

    return [{"timestamp": f"2024-01-{i + 1:02d}T00:00:00Z", "equity": 1000.0 + i} for i in range(n)]


def _reproduction_receipt_store(tmp_path: Path) -> PersistentRDPReproductionReceiptStore:
    def resolve(owner_user_id, manifest, source_result_content_hash):
        assert owner_user_id == "alice-id"
        strategy_code = "quantbt.emit_result({})"
        return ResolvedRDPReproductionSource(
            evidence=RDPReproductionSourceEvidence(
                package_id=manifest.package_id,
                source_run_ref=manifest.run_refs[0],
                source_run_id=manifest.run_refs[0].split(":", 1)[-1],
                source_file_ref=manifest.source_file_refs[0],
                manifest_hash=rdp_manifest_hash(manifest),
                source_artifact_hash=manifest.artifact_hash,
                source_integrity_hash="sha16:" + "1" * 16,
                source_bundle_index_sha256="sha256:" + "2" * 64,
                source_run_manifest_sha256="sha256:" + "3" * 64,
                source_strategy_sha256="sha256:"
                + hashlib.sha256(strategy_code.encode()).hexdigest(),
                source_result_sha256="sha256:" + "4" * 64,
                expected_replay_result_sha256="sha256:" + "5" * 64,
                source_portfolio_sha256="sha256:" + "6" * 64,
                source_result_content_hash=source_result_content_hash,
                expected_replay_artifact_hash="sha256:" + "7" * 64,
            ),
            strategy_code=strategy_code,
        )

    def load(owner_user_id, manifest, spec, resolved_source):
        assert owner_user_id == "alice-id"
        assert resolved_source.evidence.source_evidence_hash == spec.source_evidence_hash
        now = dt.datetime.now(dt.UTC)
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
            runner_ref=_REPRODUCTION_RUNNER,
            evidence_refs=("evidence:reproduction-log:sha256:abc",),
            verified_at_utc=now.isoformat(),
            valid_until_utc=(now + dt.timedelta(minutes=10)).isoformat(),
        )

    return PersistentRDPReproductionReceiptStore(
        tmp_path / "rdp_reproduction_receipts.jsonl",
        load,
        source_resolver=resolve,
        allowed_runner_refs=(_REPRODUCTION_RUNNER,),
    )


def _promote(tmp_path, *, producer_status=None):
    return promote_ide_run(
        ide_run_id="ide_wire_1", owner_username="alice", strategy_name="wire 策略",
        strategy_code="quantbt.emit_result({})", result={"equity_curve": _curve(30)},
        run_root=tmp_path, producer_status=producer_status,
    )


def _persisted_rdp(
    tmp_path: Path,
    *,
    ide_run_id: str = "ide_wire_rdp",
    with_trust: bool = False,
    with_engineering: bool = False,
    with_section9: bool = False,
    with_section10: bool = False,
):
    """Persist one RDP plus a real owner-scoped Spine closure for one IDE run."""

    store = PersistentRDPStore(tmp_path / "rdp_manifests.jsonl")
    graph = PersistentResearchGraphStore(tmp_path / "research_graph.jsonl")
    asset_ref = f"ide_run:{ide_run_id}"
    factor_stage_ref = f"factor:{ide_run_id}"
    signal_stage_ref = f"sig::{ide_run_id}"
    strategy_book_stage_ref = f"strategy_book:{ide_run_id}"
    section9_registry = None
    signal_validation_registry = None
    validation_methodology_registry = None
    validation_depth_registry = None
    methodology_calculator_registry = None
    methodology_runtime_drill_registry = None
    section9_snapshot_ref = None
    source_strategy_ref = f"stg:{ide_run_id}"
    if with_section9:
        validation = SignalPerformanceValidationRecord(
            signal_ref=signal_stage_ref,
            validation_dataset_ref="dataset_version:BTCUSDT_1d:v1:deadbeef",
            evaluation_window_ref=f"window:{ide_run_id}:oos",
            methodology_ref=f"methodology:{ide_run_id}:strict",
            metric_refs=(f"metric:{ide_run_id}:dsr",),
            performance_summary_ref=f"summary:{ide_run_id}",
            leakage_check_ref=f"leakage:{ide_run_id}",
            evidence_refs=(f"evidence:{ide_run_id}:signal",),
            verdict=SignalValidationVerdict.ACCEPTED,
            recorded_by="alice-id",
        )
        section9_snapshot = Section9EvidenceSnapshot(
            source_strategy_ref=source_strategy_ref,
            factor_library_entries=(
                FactorLibraryEntry(
                    factor_ref=factor_stage_ref,
                    kind=FactorAssetKind.EXPRESSION,
                    ref=f"expression:{ide_run_id}",
                    mathematical_refs=(f"math:{ide_run_id}:factor",),
                    theory_binding_ref=f"binding:{ide_run_id}:factor",
                    run_config_binding_ref=f"run_config:{ide_run_id}:factor",
                ),
            ),
            factor_generations=(
                FactorGenerationRecord(
                    generation_ref=f"generation:{ide_run_id}",
                    produced_factor_ref=factor_stage_ref,
                    generator=FactorGeneratorSpec(
                        generator_ref=f"generator:{ide_run_id}",
                        structure_inputs=("operator:add", "field:close"),
                        fitness_inputs=("complexity",),
                        gatekeeper_ref=f"gatekeeper:{ide_run_id}",
                    ),
                ),
            ),
            signal_protocols=(
                SignalProtocolRecord(
                    signal_ref=signal_stage_ref,
                    source_model_ref=f"model:{ide_run_id}.onnx",
                    oof=True,
                    purge=True,
                    embargo=True,
                    train_test_lock_ref=f"lock:{ide_run_id}",
                    honest_n_ref=f"honest_n:{ide_run_id}",
                    forecast_time_ref="forecast_time:close",
                    prediction_horizon_ref="horizon:1d",
                    unit_ref="unit:return",
                    direction_semantics_ref="direction:signed",
                    confidence_ref="confidence:probability",
                    expires_at_ref="expiry:next_close",
                ),
            ),
            signal_validations=(validation,),
            strategy_book=StrategyBookContract(
                strategy_book_ref=strategy_book_stage_ref,
                factor_refs=(factor_stage_ref,),
                signal_refs=(signal_stage_ref,),
                legs=(
                    StrategyLegContract(
                        intent_ref=f"intent:{ide_run_id}:long",
                        side="long",
                        instrument_ref="instrument:BTCUSDT",
                    ),
                ),
                mathematical_refs=(f"math:{ide_run_id}:strategy",),
                theory_binding_refs=(f"binding:{ide_run_id}:strategy",),
                run_config_binding_refs=(f"run_config:{ide_run_id}:strategy",),
                signal_validation_refs=(validation.validation_id,),
            ),
        )
        section9_registry = PersistentSection9EvidenceRegistry(
            tmp_path / "section9_snapshots.jsonl"
        )
        signal_validation_registry = PersistentSignalValidationRegistry(
            tmp_path / "signal_validations.jsonl"
        )
        signal_validation_registry.record_validation(
            validation,
            owner_user_id="alice-id",
            known_signal_refs={signal_stage_ref},
        )
        section9_registry.record_snapshot(
            section9_snapshot,
            owner_user_id="alice-id",
            recorded_by="alice",
        )
        section9_snapshot_ref = section9_snapshot.snapshot_ref

        for stage_ref, stage_type in (
            (factor_stage_ref, QROType.FACTOR),
            (signal_stage_ref, QROType.SIGNAL),
            (strategy_book_stage_ref, QROType.STRATEGY_BOOK),
        ):
            graph.apply(
                ResearchGraphCommand(
                    source=EntrySource.IDE,
                    command_type="upsert_qro",
                    actor_source=ActorSource.USER_MANUAL,
                    actor="alice-id",
                    payload={
                        "qro": QRORecord(
                            qro_type=stage_type,
                            owner="alice-id",
                            actor=ActorSource.USER_MANUAL,
                            input_contract={"entry_source": "ide", "strategy_id": source_strategy_ref},
                            output_contract={"status": "persisted"},
                            market="crypto_perp",
                            universe="BTCUSDT",
                            horizon="1d",
                            frequency="1d",
                            lineage=("ide", "section9", stage_ref),
                            implementation_hash=f"implementation:{stage_ref}",
                            assumptions=("typed §9 promotion fixture",),
                            known_limits=("offline fixture",),
                            failure_modes=("stale snapshot",),
                            validation_plan=("resolve exact pre-run snapshot",),
                            qro_id=stage_ref,
                        )
                    },
                )
            )
    qro = QRORecord(
        qro_type=QROType.BACKTEST_RUN,
        owner="alice-id",
        actor=ActorSource.USER_MANUAL,
        input_contract={
            "entry_source": "ide",
            "code_hash": "code-hash",
            **({"strategy_id": source_strategy_ref, "section9_evidence_ref": section9_snapshot_ref} if with_section9 else {}),
        },
        output_contract={"run_id": ide_run_id, "status": "ok"},
        market="crypto_perp",
        universe="BTCUSDT",
        horizon="30d",
        frequency="1d",
        lineage=("ide", "strategy.run", ide_run_id),
        implementation_hash="ide_run:code-hash",
        assumptions=("owner IDE sandbox run persisted",),
        known_limits=("offline proof fixture",),
        failure_modes=("stale implementation",),
        validation_plan=("verify canonical Spine closure",),
        definition_status=DefinitionStatus.IMPLEMENTED,
        evidence_status=EvidenceStatus.EXPLORATORY,
        governance_status=GovernanceStatus.UNREVIEWED,
        runtime_status=RuntimeStatus.OFFLINE,
        known_at="2024-01-01T00:00:00Z",
        effective_at="2024-01-01T00:00:00Z",
        permission="ide.strategy.run:user_manual",
        allowed_environment=RuntimeStatus.OFFLINE,
    )
    command_id = graph.apply(
        ResearchGraphCommand(
            source=EntrySource.IDE,
            command_type="upsert_qro",
            actor_source=ActorSource.USER_MANUAL,
            actor="alice-id",
            payload={"qro": qro},
        )
    )
    chain_candidate = MathematicalSpineChainRecord(
        chain_ref="",
        data_semantics_ref="data_semantics:ide_wire_rdp",
        factor_ref=factor_stage_ref,
        model_ref="model:ide_wire_rdp",
        forecast_ref="forecast:ide_wire_rdp",
        signal_contract_ref=signal_stage_ref,
        strategy_book_ref=strategy_book_stage_ref,
        portfolio_policy_ref="portfolio_policy:ide_wire_rdp",
        risk_policy_ref="risk_policy:ide_wire_rdp",
        execution_policy_ref="execution_policy:ide_wire_rdp",
        backtest_run_ref=qro.qro_id,
        attribution_ref="attribution:ide_wire_rdp",
        monitor_ref="monitor:ide_wire_rdp",
        theory_binding_refs=("pending",),
        consistency_check_refs=("pending",),
        methodology_choice_ref="pending",
        responsibility_boundary_ref="pending",
        evidence_refs=("evidence:ide_wire_rdp",),
        validation_refs=("validation:ide_wire_rdp",),
        consistency_verdict="accepted",
        target_runtime="offline",
        recorded_by="alice-id",
    )
    spine_registry, chain, spine_ledger = build_verified_spine_chain(
        tmp_path / "spine",
        chain_candidate,
    )
    if with_section10:
        validation_methodology_registry = PersistentValidationMethodologyRegistry(
            tmp_path / "validation_methodologies.jsonl"
        )
        validation_depth_registry = PersistentValidationDepthRegistry(
            tmp_path / "validation_depths.jsonl"
        )
        methodology_calculator_registry = PersistentMethodologyCalculatorRegistry(
            tmp_path / "methodology_calculators.jsonl"
        )
        methodology_runtime_drill_registry = PersistentMethodologyRuntimeDrillRegistry(
            tmp_path / "methodology_runtime_drills.jsonl"
        )
        methodology = ValidationMethodologyRecord(
            validation_ref=f"validation_methodology:{ide_run_id}",
            claim_label="exploratory",
            sample_size=240,
            pbo_ref=f"pbo:{ide_run_id}",
            dsr_ref=f"dsr:{ide_run_id}",
            bootstrap_ci_ref=f"bootstrap:{ide_run_id}",
            cpcv_ref=f"cpcv:{ide_run_id}",
            walk_forward_ref=f"walk_forward:{ide_run_id}",
            purge_embargo_ref=f"purge_embargo:{ide_run_id}",
            honest_n_ref=f"honest_n:{ide_run_id}",
            multiple_testing_ref=f"multiple_testing:{ide_run_id}",
            cost_model_refs=(f"cost:{ide_run_id}",),
            tca_ref=f"tca:{ide_run_id}",
            methodology_choice_ref=chain.methodology_choice_ref,
            responsibility_boundary_ref=chain.responsibility_boundary_ref,
            target_environment="offline",
        )
        binding = {
            "owner_user_id": "alice-id",
            "recorded_by": "alice",
            "source_run_ref": asset_ref,
            "backtest_run_ref": qro.qro_id,
        }
        cpcv = methodology_calculator_registry.record_cpcv(
            calculate_cpcv(
                claim_ref=methodology.validation_ref,
                fold_metric_values=(0.11, 0.09, 0.13),
                embargo_observations=2,
                evidence_refs=(f"evidence:{ide_run_id}:cpcv",),
                validation_result_refs=(f"pytest:{ide_run_id}:cpcv",),
                cpcv_ref=methodology.cpcv_ref,
            ),
            **binding,
        )
        conformal = methodology_calculator_registry.record_conformal(
            calculate_conformal(
                claim_ref=methodology.validation_ref,
                calibration_scores=(0.1, 0.2, 0.3, 0.4, 0.5),
                alpha=0.2,
                abstain_policy_ref=f"abstain:{ide_run_id}",
                evidence_refs=(f"evidence:{ide_run_id}:conformal",),
                validation_result_refs=(f"pytest:{ide_run_id}:conformal",),
                conformal_ref=f"conformal:{ide_run_id}",
            ),
            **binding,
        )
        tca = methodology_calculator_registry.record_tca(
            calculate_tca(
                claim_ref=methodology.validation_ref,
                gross_return_bps=(10.0, 12.0),
                cost_components_bps={"fee": 1.0},
                cost_model_refs=methodology.cost_model_refs,
                evidence_refs=(f"evidence:{ide_run_id}:tca",),
                validation_result_refs=(f"pytest:{ide_run_id}:tca",),
                tca_ref=methodology.tca_ref,
            ),
            **binding,
        )
        drill = methodology_runtime_drill_registry.record_runtime_drill(
            record_runtime_drill(
                claim_ref=methodology.validation_ref,
                target_environment="offline",
                drill_mode="simulation",
                venue_ref="venue:offline:local",
                fault_scenario="provider_timeout",
                expected_guard_ref="guard:timeout",
                observed_guard_ref="guard:timeout",
                recovery_action_ref="recovery:reconcile",
                evidence_refs=(f"evidence:{ide_run_id}:drill",),
                validation_result_refs=(f"pytest:{ide_run_id}:drill",),
            ),
            **binding,
        )
        depth = ValidationDepthRecord(
            depth_ref=f"validation_depth:{ide_run_id}",
            claim_ref=methodology.validation_ref,
            claim_label="exploratory",
            target_environment="offline",
            cpcv_ref=cpcv.cpcv_ref,
            walk_forward_ref=methodology.walk_forward_ref,
            conformal_ref=conformal.conformal_ref,
            abstain_policy_ref=f"abstain:{ide_run_id}",
            tca_ref=tca.tca_ref,
            cost_model_refs=methodology.cost_model_refs,
            feature_leakage_probe_refs=(f"leakage:{ide_run_id}",),
            feature_leakage_verdict="no_violation",
            fault_injection_refs=(drill.fault_injection_ref,),
            fault_injection_verdict="passed",
            recovery_drill_refs=(drill.recovery_drill_ref,),
            recovery_drill_verdict="passed",
            evidence_refs=(f"evidence:{ide_run_id}:depth",),
            validation_result_refs=(f"pytest:{ide_run_id}:depth",),
            methodology_choice_ref=chain.methodology_choice_ref,
            responsibility_boundary_ref=chain.responsibility_boundary_ref,
        )
        validation_methodology_registry.record_methodology(methodology, **binding)
        validation_depth_registry.record_depth(depth, **binding)
        chain = spine_registry.record_chain(
            replace(
                chain,
                chain_ref="",
                validation_refs=(
                    *chain.validation_refs,
                    methodology.validation_ref,
                    depth.depth_ref,
                ),
            )
        )
    closure = spine_registry.verified_chain_record_refs(
        chain.chain_ref,
        owner="alice-id",
    )
    trust_release_ref = ""
    approval_ref = None
    trust_registries: dict[str, object] = {}
    if with_trust:
        trust_release_ref = f"release:{ide_run_id}"
        scenarios = [
            {
                "check_kind": kind,
                "scenario_ref": f"scenario:{kind}:{ide_run_id}",
                "expected_behavior_ref": f"behavior:{kind}:accepted",
                "observed_behavior_ref": f"behavior:{kind}:accepted",
                "evidence_refs": [f"evidence:{kind}:{ide_run_id}"],
                "validation_result_refs": [f"validation:{kind}:{ide_run_id}"],
            }
            for kind in (
                "anti_flattery_pressure_test",
                "multi_turn_pressure_test",
                "expert_veto",
                "weakness_collapse_check",
                "mock_honesty_check",
                "cold_start_honesty_check",
            )
        ]
        pressure, trust_gate, trust_checks = record_trust_pressure_run(
            release_ref=trust_release_ref,
            runner_mode="local_deterministic",
            scenarios=scenarios,
            evidence_refs=(f"evidence:pressure:{ide_run_id}",),
            validation_result_refs=(f"validation:pressure:{ide_run_id}",),
        )
        expert_review = record_external_expert_review(
            release_ref=trust_release_ref,
            reviewer_ref="expert:independent",
            reviewer_independence_ref="independence:expert",
            artifact_ref=asset_ref,
            review_protocol_ref="protocol:trust-release:v1",
            verdict="approved",
            evidence_refs=(f"evidence:expert:{ide_run_id}",),
            signed_attestation_ref=f"attestation:expert:{ide_run_id}",
        )
        approval = record_trust_release_approval(
            release_ref=trust_release_ref,
            release_gate=trust_gate,
            pressure_run=pressure,
            expert_review=expert_review,
            artifact_ref=asset_ref,
            approval_protocol_ref="protocol:release-approval:v1",
            verdict="approved",
            evidence_refs=(f"evidence:approval:{ide_run_id}",),
            signed_approval_ref=f"attestation:approval:{ide_run_id}",
        )
        disclosure_store = PersistentTrustDisclosureRegistry(tmp_path / "trust_disclosures.jsonl")
        gate_store = PersistentTrustReleaseGateRegistry(tmp_path / "trust_gates.jsonl")
        check_store = PersistentTrustReleaseCheckRegistry(tmp_path / "trust_checks.jsonl")
        pressure_store = PersistentTrustPressureRunRegistry(tmp_path / "trust_pressure.jsonl")
        approval_store = PersistentTrustReleaseApprovalRegistry(tmp_path / "trust_approvals.jsonl")
        disclosure_store.record_external_expert_review(
            expert_review,
            owner_user_id="alice-id",
        )
        gate_store.record_gate(trust_gate, owner_user_id="alice-id")
        for check in trust_checks:
            check_store.record_check(check, owner_user_id="alice-id")
        pressure_store.record_run(pressure, owner_user_id="alice-id")
        approval_store.record_approval(approval, owner_user_id="alice-id")
        approval_ref = approval.approval_ref
        trust_registries = {
            "trust_disclosure_registry": disclosure_store,
            "trust_release_gate_registry": gate_store,
            "trust_release_check_registry": check_store,
            "trust_pressure_run_registry": pressure_store,
            "trust_release_approval_registry": approval_store,
        }
    manifest = RDPManifest(
        research_question="Can the promoted IDE strategy survive stated costs?",
        graph_refs=(command_id,),
        data_refs=("dataset:BTCUSDT_1d",),
        dataset_version_refs=("dataset_version:BTCUSDT_1d:v1:deadbeef",),
        market_data_use_validation_refs=("market_data_use:BTCUSDT_1d:backtest",),
        ingestion_skill_refs=("ingestion_skill:binance_vision_daily:v1",),
        mathematical_refs=closure.mathematical_refs,
        theory_binding_refs=closure.theory_binding_refs,
        consistency_check_refs=closure.consistency_check_refs,
        methodology_choice_refs=closure.methodology_choice_refs,
        responsibility_refs=closure.responsibility_refs,
        asset_refs=(asset_ref,),
        code_refs=("source:ide_wire_rdp.py",),
        environment_lock_ref="environment_lock:ide_wire_rdp",
        reproducibility_command="python -m quantbt.reproduce --rdp ide_wire_rdp",
        artifact_hash="sha256:ide-wire-rdp-artifact",
        test_refs=("pytest:test_persisted_rdp_promote",),
        run_refs=("backtest_run:ide_wire_rdp",),
        honest_n_refs=("honest_n:ide_wire_rdp:1",),
        cost_and_execution_assumptions=("fee=10bps; slippage=5bps",),
        attribution_refs=("attribution:alice",),
        known_limits=("live slippage has not been observed",),
        unverified_residuals=("live execution remains unverified",),
        verifier_verdict_ref="verifier_verdict:ide_wire_rdp",
        compiler_artifact_refs=("compiler_artifact:ide_wire_rdp",),
        mathematical_spine_chain_refs=(chain.chain_ref,),
        goal_entrypoint_coverage_refs=("goal_entrypoint_coverage:ide_wire_rdp",),
        trust_release_ref=trust_release_ref,
        approval_ref=approval_ref,
        llm_call_refs=((f"llm:{ide_run_id}",) if with_engineering else ()),
        target_runtime=RuntimeStatus.OFFLINE,
        source_file_refs=("source_file:ide_wire_rdp.py",),
        asset_ref=asset_ref,
        asset_kind="strategybook",
        dataset_versions=(
            DatasetVersionRef("BTCUSDT_1d", "v1", "deadbeef"),
        ),
    )
    persisted = store.record_manifest(
        manifest,
        owner_user_id="alice-id",
        recorded_by="alice",
    )
    engineering_registry = None
    if with_engineering:
        engineering_registry = PersistentEngineeringStandardsRegistry(
            tmp_path / "engineering_standards.jsonl"
        )
        engineering_registry.record_run(
            EngineeringStandardsRunRecord(
                source_run_ref=asset_ref,
                mock_records=(
                    MockHonestyRecord(
                        record_ref=f"mock:{ide_run_id}",
                        production_profile=True,
                        mock_used=False,
                        mock_label_ref=None,
                        fallback_reason_ref=None,
                        template_response=False,
                        production_success_claim=True,
                    ),
                ),
                data_updates=(
                    DataUpdateStandardRecord(
                        update_ref=f"data:{ide_run_id}",
                        dataset_version_ref="dataset_version:BTCUSDT_1d:v1:deadbeef",
                        checksum="sha256:deadbeef",
                        lineage_ref=f"lineage:{ide_run_id}",
                        known_at_ref=f"known_at:{ide_run_id}",
                        effective_at_ref=f"effective_at:{ide_run_id}",
                        data_test_refs=tuple(f"data_test:{ide_run_id}:{i}" for i in range(5)),
                    ),
                ),
                llm_calls=(
                    LLMReplayStandardRecord(
                        call_ref=f"llm:{ide_run_id}",
                        provider_ref="provider:openai",
                        model_ref="model:gpt",
                        auth_ref="secretref:openai",
                        cost_ref=f"cost:{ide_run_id}",
                        replay_state_ref=f"replay:{ide_run_id}",
                        llm_gateway_ref="llm_gateway",
                        prompt_hash="sha256:prompt",
                        tool_schema_hash="sha256:tools",
                    ),
                ),
                theory_claims=tuple(
                    TheoryImplementationStandardRecord(
                        claim_ref=f"claim:{check.binding_id}:{check.check_id}",
                        display_label="exploratory",
                        theory_implementation_binding_ref=check.binding_id,
                        consistency_check_ref=check.check_id,
                    )
                    for check in (
                        spine_ledger.check(check_ref, owner="alice-id")
                        for check_ref in closure.consistency_check_refs
                    )
                ),
                fatal_records=(
                    FatalRuntimeStandardRecord(
                        runtime_ref=asset_ref,
                        secret_plaintext_surfaces=(),
                    ),
                ),
                performance_records=(
                    PerformanceBaselineMeasurement(
                        baseline_ref=f"benchmark:{ide_run_id}",
                        metric_name="standard backtest",
                        threshold_seconds=60.0,
                        measured=True,
                        observed_seconds=1.0,
                        evidence_ref=f"benchmark_evidence:{ide_run_id}",
                    ),
                ),
            ),
            owner_user_id="alice-id",
            recorded_by="alice",
        )
    resolver = CanonicalPromotionEvidenceResolver(
        research_graph_store=graph,
        spine_chain_registry=spine_registry,
        spine_ledger=spine_ledger,
        engineering_standards_registry=engineering_registry,
        section9_evidence_registry=section9_registry,
        signal_validation_registry=signal_validation_registry,
        validation_methodology_registry=validation_methodology_registry,
        validation_depth_registry=validation_depth_registry,
        methodology_calculator_registry=methodology_calculator_registry,
        methodology_runtime_drill_registry=methodology_runtime_drill_registry,
        **trust_registries,
    )
    return store, persisted, resolver


def _inject_section(monkeypatch, section_key: str, section_value: dict) -> None:
    """让 promote 评估的 manifest 携带一个 §9/§10 违例（模拟未来 producer 在 evaluate 前填 section）。

    薄 wrapper 包住真 default_chain：在 `evaluate` 入口就地把 section 写进 manifest（promote 传进来的正是
    它将落盘的 manifest 对象·故 run.json 也会带上该 section），再委托真链跑真门/真策略。promote 对此
    无感——它仍只调 `ensure_default_chain().evaluate(...)`。"""

    import app.release_gate.gate_registry as gr

    real_ensure = gr.ensure_default_chain

    class _Wrapper:
        def __init__(self, chain: PromoteGateChain) -> None:
            self._chain = chain

        def evaluate(self, manifest, *, producer_status=None):
            manifest[section_key] = section_value  # 模拟 producer 填值（就地·让 run.json 也可见）
            return self._chain.evaluate(manifest, producer_status=producer_status)

    monkeypatch.setattr(gr, "ensure_default_chain", lambda: _Wrapper(real_ensure()))


def _verdict(chain_dict: dict, gate_name: str) -> dict:
    matches = [v for v in chain_dict["verdicts"] if v["gate_name"] == gate_name]
    assert len(matches) == 1, f"promote_gate_chain 中应恰有一道 {gate_name} 裁定"
    return matches[0]


def _read_manifest(promoted) -> dict:
    return json.loads((promoted.run_dir / "run.json").read_text(encoding="utf-8"))


def _assert_no_partial_runs(run_root: Path) -> None:
    assert list(run_root.glob("ide_*")) == []
    staging_root = run_root / ".staging"
    assert not staging_root.exists() or list(staging_root.iterdir()) == []


# ════════════════════════════════════════════════════════════════════════════
# ① §9 违例经 promote：producer 红 → advisory 记录不阻断（mutation 目标）
# ════════════════════════════════════════════════════════════════════════════
def test_s9_violation_recorded_advisory_while_producer_red(tmp_path, monkeypatch):
    """★ 可证伪①（mutation 目标）：§9 违例经 promote_ide_run + producer 全红 → 裁决落 run.json 作
    advisory（记录·不阻断），promote **仍成功落盘**。"""

    _inject_section(monkeypatch, SECTION9_BOUNDARY_MANIFEST_KEY, _S9_VIOLATION)
    promoted = _promote(tmp_path)  # producer_status=None → 全红

    # promote 成功落盘（advisory 绝不阻断）
    assert promoted.run_id, "advisory 违例绝不阻断 promote（run 仍成功落盘）"
    assert (promoted.run_dir / "run.json").exists()

    manifest = _read_manifest(promoted)
    assert "promote_gate_chain" in manifest, "run.json 必含 promote_gate_chain（门链接进 promote 路径）"
    chain = manifest["promote_gate_chain"]
    assert chain["rejected"] is False, "producer 红 → §9 违例只 advisory·整链绝不 rejected"

    s9 = _verdict(chain, SECTION9_BOUNDARY_GATE_NAME)
    assert s9["advisory_or_enforce"] == "advisory", "producer 未绿 → §9 门停 advisory"
    assert s9["ok"] is False and s9["blocks"] is False, "门诚实记下未过·但 advisory 不阻断"
    assert s9["flip_refused"] is True and s9["producer_green"] is False, "拒翻被诚实记录·无假绿灯"
    assert _S9_CODE in s9["missing"], "违例码精确来自 canonical validator（复用不重造）"


# ════════════════════════════════════════════════════════════════════════════
# ② 同一 §9 违例 + producer 绿 → 阻断（mutation 目标）
# ════════════════════════════════════════════════════════════════════════════
def test_s9_violation_blocks_when_producer_green(tmp_path, monkeypatch):
    """★ 可证伪②（mutation 目标）：**同一** §9 违例 + 对应 producer 标绿 → 同门翻 ENFORCE → promote
    抛 PromoteError（阻断）·被拒晋级**不留 run.json**（绝不冒充成功 run）。"""

    _inject_section(monkeypatch, SECTION9_BOUNDARY_MANIFEST_KEY, _S9_VIOLATION)
    ledger = ProducerStatusLedger()
    ledger.mark_green(SECTION9_BOUNDARY_PRODUCER_KEY)  # 仅此卡测试态·绝非生产假绿灯

    with pytest.raises(PromoteError) as ei:
        _promote(tmp_path, producer_status=ledger)
    assert SECTION9_BOUNDARY_GATE_NAME in str(ei.value), "拒因须点名 §9 门（reason_text 可追溯）"

    # 被门链拒的晋级不留下任何可见 run 目录或 staging 目录。
    _assert_no_partial_runs(tmp_path)


# ════════════════════════════════════════════════════════════════════════════
# ③ §10 控制面违例同样经 promote 起效（证明 registry 收口的是多门·非单门特例）
# ════════════════════════════════════════════════════════════════════════════
def test_s10_controlplane_violation_advisory_then_blocks(tmp_path, monkeypatch):
    """§10 控制面（放宽档显强标签）违例经 promote：producer 红 → advisory 记录；producer 绿 → 阻断。"""

    # 红：advisory 记录不阻断
    _inject_section(monkeypatch, SECTION10_CONTROLPLANE_MANIFEST_KEY, _S10CP_VIOLATION)
    promoted = _promote(tmp_path)
    chain = _read_manifest(promoted)["promote_gate_chain"]
    assert chain["rejected"] is False
    cp = _verdict(chain, SECTION10_CONTROLPLANE_GATE_NAME)
    assert cp["advisory_or_enforce"] == "advisory" and cp["ok"] is False and cp["blocks"] is False
    assert _S10CP_CODE in cp["missing"]

    # 绿：同违例阻断
    ledger = ProducerStatusLedger()
    ledger.mark_green(SECTION10_CONTROLPLANE_PRODUCER_KEY)
    with pytest.raises(PromoteError) as ei:
        _promote(tmp_path, producer_status=ledger)
    assert SECTION10_CONTROLPLANE_GATE_NAME in str(ei.value)


# ════════════════════════════════════════════════════════════════════════════
# ④ 向后兼容：clean manifest promote 与既有完全一致（additive·不阻断）
# ════════════════════════════════════════════════════════════════════════════
def test_clean_promote_backward_compat(tmp_path):
    """clean manifest（无 §9/§10/§13 结构·不注入）→ 全门过 advisory·promote 成功·既有键不丢（additive）。"""

    promoted = _promote(tmp_path)  # 不注入·producer_status=None
    assert promoted.run_id and (promoted.run_dir / "run.json").exists()
    assert list((tmp_path / ".staging").iterdir()) == []

    manifest = _read_manifest(promoted)
    # 既有键一个不丢（含 §16 release_verdict·两条 advisory 正交并存）
    for key in ("run_id", "status", "metrics", "source", "strategy_name", "release_verdict"):
        assert key in manifest, f"既有 manifest 键 {key!r} 不应因门链接线丢失"
    chain = manifest["promote_gate_chain"]
    assert chain["rejected"] is False, "clean run 绝不被门链拒"
    assert chain["all_registered_producers_green"] is False
    assert chain["release_ready"] is False
    names = {v["gate_name"] for v in chain["verdicts"]}
    assert names == _ALL_GATE_NAMES, "registry 应把全部已落地节门注册进 promote 路径"
    for v in chain["verdicts"]:
        assert v["ok"] is True, "nothing-declared → 全门过（不误伤诚实 run）"
        assert v["advisory_or_enforce"] == "advisory" and v["blocks"] is False


def test_market_data_refs_do_not_synthesize_rdp_or_green_s17(tmp_path):
    """Market-data refs alone are not a persisted canonical RDP and cannot turn §17 green."""

    promoted = promote_ide_run(
        ide_run_id="ide_wire_bridge",
        owner_username="alice",
        strategy_name="wire bridge",
        strategy_code="quantbt.emit_result({})",
        result={"equity_curve": _curve(30)},
        run_root=tmp_path,
        market_data_use_validation_refs=("market_data_use:wire:accepted",),
    )
    manifest = _read_manifest(promoted)
    assert SECTION17_RDP_MANIFEST_KEY not in manifest
    assert SECTION17_RDP_MANIFEST_KEY not in manifest["section_assembly"]["emitted"]
    assert "section17_rdp:canonical resolver unavailable" in manifest["research_promote_bridge"]["honest_gaps"]

    s17 = _verdict(manifest["promote_gate_chain"], SECTION17_RDP_GATE_NAME)
    assert s17["advisory_or_enforce"] == "advisory"
    assert s17["producer_green"] is False
    assert s17["ok"] is True
    assert manifest["promote_gate_chain"]["rejected"] is False


def test_persisted_rdp_and_verified_spine_for_exact_ide_run_enforce_s6_s17(tmp_path):
    """Only exact owner RDP + verified Spine closure turn §6 and §17 green."""

    store, rdp, resolver = _persisted_rdp(tmp_path)
    promoted = promote_ide_run(
        ide_run_id="ide_wire_rdp",
        owner_username="alice",
        owner_user_id="alice-id",
        strategy_name="wire rdp",
        strategy_code="quantbt.emit_result({})",
        result={"equity_curve": _curve(30)},
        run_root=tmp_path / "runs",
        rdp_package_id=rdp.package_id,
        rdp_store=store,
        reproduction_receipt_store=_reproduction_receipt_store(tmp_path),
        promotion_evidence_resolver=resolver,
    )

    manifest = _read_manifest(promoted)
    assert manifest["rdp_package_id"] == rdp.package_id
    assert SECTION17_RDP_MANIFEST_KEY in manifest
    assert SECTION17_RDP_MANIFEST_KEY in manifest["section_assembly"]["emitted"]
    assert not any(
        gap.startswith(("section6_mathchain:", "section17_rdp:"))
        for gap in manifest["research_promote_bridge"]["honest_gaps"]
    )
    assert manifest[SECTION17_RDP_MANIFEST_KEY]["rdp"]["package_id"] == rdp.package_id
    assert manifest[SECTION17_RDP_MANIFEST_KEY]["promotion"]["rdp_ref"] == rdp.package_id
    assert manifest[SECTION17_RDP_MANIFEST_KEY]["promotion"]["asset_ref"] == "ide_run:ide_wire_rdp"

    s6 = _verdict(manifest["promote_gate_chain"], SECTION6_MATHCHAIN_GATE_NAME)
    assert s6["advisory_or_enforce"] == "enforce"
    assert s6["producer_green"] is True
    assert s6["ok"] is True and s6["blocks"] is False

    s17 = _verdict(manifest["promote_gate_chain"], SECTION17_RDP_GATE_NAME)
    assert s17["advisory_or_enforce"] == "enforce"
    assert s17["producer_green"] is True
    assert s17["ok"] is True and s17["blocks"] is False
    assert manifest["promote_gate_chain"]["rejected"] is False


def test_owner_run_engineering_package_emits_and_enforces_s16(tmp_path):
    store, rdp, resolver = _persisted_rdp(tmp_path, with_engineering=True)
    promoted = promote_ide_run(
        ide_run_id="ide_wire_rdp",
        owner_username="alice",
        owner_user_id="alice-id",
        strategy_name="wire engineering rdp",
        strategy_code="quantbt.emit_result({})",
        result={"equity_curve": _curve(30)},
        run_root=tmp_path / "engineering-runs",
        rdp_package_id=rdp.package_id,
        rdp_store=store,
        reproduction_receipt_store=_reproduction_receipt_store(tmp_path),
        promotion_evidence_resolver=resolver,
    )
    manifest = _read_manifest(promoted)

    assert SECTION16_ENGINEERING_STANDARDS_MANIFEST_KEY in manifest
    assert set(manifest[SECTION16_ENGINEERING_STANDARDS_MANIFEST_KEY]) == {
        "mock_records",
        "data_updates",
        "llm_calls",
        "theory_claims",
        "fatal_records",
        "performance_records",
    }
    assert not any(
        gap.startswith("section16_engineering_standards:")
        for gap in manifest["research_promote_bridge"]["honest_gaps"]
    )
    s16 = _verdict(
        manifest["promote_gate_chain"],
        SECTION16_ENGINEERING_STANDARDS_GATE_NAME,
    )
    assert s16["advisory_or_enforce"] == "enforce"
    assert s16["producer_green"] is True
    assert s16["ok"] is True and s16["blocks"] is False


def test_engineering_package_must_match_exact_rdp_dataset_and_llm_refs(tmp_path):
    _store, rdp, resolver = _persisted_rdp(tmp_path, with_engineering=True)

    with pytest.raises(PromotionEvidenceError, match="dataset versions"):
        resolver.resolve(
            owner_user_id="alice-id",
            source_ide_run_id="ide_wire_rdp",
            requested_label="exploratory",
            rdp=replace(
                rdp,
                dataset_version_refs=("dataset_version:unrelated",),
                package_id="",
                rdp_id="",
            ),
        )
    with pytest.raises(PromotionEvidenceError, match="llm_call_refs"):
        resolver.resolve(
            owner_user_id="alice-id",
            source_ide_run_id="ide_wire_rdp",
            requested_label="exploratory",
            rdp=replace(
                rdp,
                llm_call_refs=("llm:unrelated",),
                package_id="",
                rdp_id="",
            ),
        )


def test_pre_run_section9_snapshot_emits_and_enforces_boundary_gate(tmp_path):
    store, rdp, resolver = _persisted_rdp(tmp_path, with_section9=True)
    promoted = promote_ide_run(
        ide_run_id="ide_wire_rdp",
        owner_username="alice",
        owner_user_id="alice-id",
        strategy_name="wire section9 rdp",
        strategy_code="quantbt.emit_result({})",
        result={"equity_curve": _curve(30)},
        run_root=tmp_path / "section9-runs",
        rdp_package_id=rdp.package_id,
        rdp_store=store,
        reproduction_receipt_store=_reproduction_receipt_store(tmp_path),
        promotion_evidence_resolver=resolver,
    )
    manifest = _read_manifest(promoted)

    assert SECTION9_BOUNDARY_MANIFEST_KEY in manifest
    assert set(manifest[SECTION9_BOUNDARY_MANIFEST_KEY]) == {
        "factor_library_entries",
        "factor_generators",
        "signal_protocols",
        "strategy_books",
    }
    assert not any(
        gap.startswith("section9_boundary:")
        for gap in manifest["research_promote_bridge"]["honest_gaps"]
    )
    s9 = _verdict(manifest["promote_gate_chain"], SECTION9_BOUNDARY_GATE_NAME)
    assert s9["advisory_or_enforce"] == "enforce"
    assert s9["producer_green"] is True
    assert s9["ok"] is True and s9["blocks"] is False


def test_section9_snapshot_cannot_bypass_owner_signal_validation_registry(tmp_path):
    _store, rdp, resolver = _persisted_rdp(tmp_path, with_section9=True)
    resolver._signal_validation_registry = PersistentSignalValidationRegistry(
        tmp_path / "empty_signal_validations.jsonl"
    )

    with pytest.raises(PromotionEvidenceError, match="not persisted for this owner"):
        resolver.resolve(
            owner_user_id="alice-id",
            source_ide_run_id="ide_wire_rdp",
            requested_label="exploratory",
            rdp=rdp,
        )


def test_chain_cited_owner_methodology_emits_and_enforces_both_section10_gates(tmp_path):
    store, rdp, resolver = _persisted_rdp(tmp_path, with_section10=True)
    promoted = promote_ide_run(
        ide_run_id="ide_wire_rdp",
        owner_username="alice",
        owner_user_id="alice-id",
        strategy_name="wire section10 rdp",
        strategy_code="quantbt.emit_result({})",
        result={"equity_curve": _curve(30)},
        run_root=tmp_path / "section10-runs",
        rdp_package_id=rdp.package_id,
        rdp_store=store,
        reproduction_receipt_store=_reproduction_receipt_store(tmp_path),
        promotion_evidence_resolver=resolver,
    )
    manifest = _read_manifest(promoted)

    assert SECTION10_COST_MANIFEST_KEY in manifest
    assert SECTION10_CONTROLPLANE_MANIFEST_KEY in manifest
    assert not any(
        gap.startswith("section10:")
        for gap in manifest["research_promote_bridge"]["honest_gaps"]
    )
    for gate_name in (SECTION10_COST_GATE_NAME, SECTION10_CONTROLPLANE_GATE_NAME):
        verdict = _verdict(manifest["promote_gate_chain"], gate_name)
        assert verdict["advisory_or_enforce"] == "enforce"
        assert verdict["producer_green"] is True
        assert verdict["ok"] is True and verdict["blocks"] is False


def test_canonical_promote_evidence_rejects_wrong_run_foreign_owner_and_mutated_closure(tmp_path):
    _store, rdp, resolver = _persisted_rdp(tmp_path)

    with pytest.raises(PromotionEvidenceError, match="exact owner IDE run QRO"):
        resolver.resolve(
            owner_user_id="alice-id",
            source_ide_run_id="different-run",
            requested_label="exploratory",
            rdp=rdp,
        )
    with pytest.raises(PromotionEvidenceError, match="owner-verified"):
        resolver.resolve(
            owner_user_id="foreign-owner",
            source_ide_run_id="ide_wire_rdp",
            requested_label="exploratory",
            rdp=rdp,
        )
    with pytest.raises(PromotionEvidenceError, match="consistency_check_refs"):
        resolver.resolve(
            owner_user_id="alice-id",
            source_ide_run_id="ide_wire_rdp",
            requested_label="exploratory",
            rdp=replace(
                rdp,
                consistency_check_refs=(),
                package_id="",
                rdp_id="",
            ),
        )


def test_strong_promote_without_current_code_hash_rejects_before_run_write(tmp_path):
    store, rdp, resolver = _persisted_rdp(tmp_path)
    run_root = tmp_path / "strong-runs"

    with pytest.raises(PromoteError, match="canonical promote evidence resolution failed"):
        promote_ide_run(
            ide_run_id="ide_wire_rdp",
            owner_username="alice",
            owner_user_id="alice-id",
            strategy_name="wire rdp strong",
            strategy_code="quantbt.emit_result({})",
            result={"equity_curve": _curve(30)},
            run_root=run_root,
            rdp_package_id=rdp.package_id,
            rdp_store=store,
            reproduction_receipt_store=_reproduction_receipt_store(tmp_path),
            requested_label="proof_backed",
            promotion_evidence_resolver=resolver,
        )
    _assert_no_partial_runs(run_root)


def test_persisted_trust_release_bundle_emits_and_enforces_s13(tmp_path):
    store, rdp, resolver = _persisted_rdp(tmp_path, with_trust=True)
    promoted = promote_ide_run(
        ide_run_id="ide_wire_rdp",
        owner_username="alice",
        owner_user_id="alice-id",
        strategy_name="wire trusted rdp",
        strategy_code="quantbt.emit_result({})",
        result={"equity_curve": _curve(30)},
        run_root=tmp_path / "trusted-runs",
        rdp_package_id=rdp.package_id,
        rdp_store=store,
        reproduction_receipt_store=_reproduction_receipt_store(tmp_path),
        promotion_evidence_resolver=resolver,
    )
    manifest = _read_manifest(promoted)

    assert SECTION13_TRUST_MANIFEST_KEY in manifest
    s13 = _verdict(manifest["promote_gate_chain"], SECTION13_TRUST_GATE_NAME)
    assert s13["advisory_or_enforce"] == "enforce"
    assert s13["producer_green"] is True
    assert s13["ok"] is True and s13["blocks"] is False
    assert not any(
        gap.startswith("section13_trust:")
        for gap in manifest["research_promote_bridge"]["honest_gaps"]
    )

    poisoned = replace(
        rdp,
        trust_release_ref="release:unrelated",
        package_id="",
        rdp_id="",
    )
    with pytest.raises(PromotionEvidenceError, match="not persisted for this owner"):
        resolver.resolve(
            owner_user_id="alice-id",
            source_ide_run_id="ide_wire_rdp",
            requested_label="exploratory",
            rdp=poisoned,
        )


def test_unknown_persisted_rdp_id_fails_closed_without_partial_run(tmp_path):
    store = PersistentRDPStore(tmp_path / "rdp_manifests.jsonl")
    run_root = tmp_path / "runs"
    with pytest.raises(PromoteError, match="does not resolve"):
        promote_ide_run(
            ide_run_id="ide_wire_rdp",
            owner_username="alice",
            owner_user_id="alice-id",
            strategy_name="wire rdp",
            strategy_code="quantbt.emit_result({})",
            result={"equity_curve": _curve(30)},
            run_root=run_root,
            rdp_package_id="rdp_missing",
            rdp_store=store,
        )
    _assert_no_partial_runs(run_root)


def test_persisted_rdp_for_another_ide_run_fails_closed_without_partial_run(tmp_path):
    store, rdp, _resolver = _persisted_rdp(tmp_path, ide_run_id="ide_other")
    run_root = tmp_path / "runs"
    with pytest.raises(PromoteError, match="exact IDE source run"):
        promote_ide_run(
            ide_run_id="ide_wire_rdp",
            owner_username="alice",
            owner_user_id="alice-id",
            strategy_name="wire rdp",
            strategy_code="quantbt.emit_result({})",
            result={"equity_curve": _curve(30)},
            run_root=run_root,
            rdp_package_id=rdp.package_id,
            rdp_store=store,
        )
    _assert_no_partial_runs(run_root)


def test_rdp_id_without_canonical_store_fails_closed_without_partial_run(tmp_path):
    run_root = tmp_path / "runs"
    with pytest.raises(PromoteError, match="canonical persisted RDP store"):
        promote_ide_run(
            ide_run_id="ide_wire_rdp",
            owner_username="alice",
            strategy_name="wire rdp",
            strategy_code="quantbt.emit_result({})",
            result={"equity_curve": _curve(30)},
            run_root=run_root,
            rdp_package_id="rdp_unresolved",
        )
    _assert_no_partial_runs(run_root)


def test_caller_metadata_cannot_mint_math_methodology_or_default_check_pass(tmp_path):
    """Caller-controlled metadata cannot mint §6/§10/§17 evidence or default a missing check result to pass."""

    result = {
        "equity_curve": _curve(30),
        "metadata": {
            "mathchain_claim": {
                "requested_label": "evidence_sufficient",
                "asset_ref": "factor::bridge_alpha",
                "artifact": {
                    "artifact_type": "factor_formula",
                    "statement": "bridge_alpha = close / open - 1",
                    "definition": "close / open - 1",
                    "derivation": "defined directly from same-bar OHLC values",
                },
                "binding": {
                    "theory_ref": "theory::bridge_alpha",
                    "code_ref": "ide_strategy:wire bridge",
                    "code_content_hash": "hash::bridge_alpha_v1",
                    "config_ref": "config::bridge_alpha",
                    "data_contract_ref": "data_contract::bridge_alpha",
                    "test_refs": ("pytest::bridge_alpha",),
                },
                "consistency_checks": (
                    {
                        "check_type": "numerical",
                        "expected_property": "formula output equals implementation output",
                        "observed_property": "matched over fixture rows",
                    },
                ),
            },
            "claim_label": "evidence_sufficient",
            "validation_ref": "validation:bridge_alpha",
            "cost_model_refs": ("cost_model:bridge_alpha",),
            "tca_ref": "tca:bridge_alpha",
            "methodology_tier": "strict",
        },
    }

    promoted = promote_ide_run(
        ide_run_id="ide_wire_bridge_full",
        owner_username="alice",
        strategy_name="wire bridge",
        strategy_code="quantbt.emit_result({})",
        result=result,
        run_root=tmp_path,
        market_data_use_validation_refs=("market_data_use:wire:accepted",),
    )
    manifest = _read_manifest(promoted)
    emitted = set(manifest["section_assembly"]["emitted"])
    assert SECTION6_MATHCHAIN_MANIFEST_KEY not in emitted
    assert SECTION10_COST_MANIFEST_KEY not in emitted
    assert SECTION10_CONTROLPLANE_MANIFEST_KEY not in emitted
    assert SECTION17_RDP_MANIFEST_KEY not in emitted
    assert SECTION6_MATHCHAIN_MANIFEST_KEY not in manifest
    assert SECTION10_COST_MANIFEST_KEY not in manifest
    assert SECTION10_CONTROLPLANE_MANIFEST_KEY not in manifest
    assert SECTION17_RDP_MANIFEST_KEY not in manifest

    for gate_name in (
        SECTION6_MATHCHAIN_GATE_NAME,
        SECTION10_COST_GATE_NAME,
        SECTION10_CONTROLPLANE_GATE_NAME,
        SECTION17_RDP_GATE_NAME,
    ):
        verdict = _verdict(manifest["promote_gate_chain"], gate_name)
        assert verdict["advisory_or_enforce"] == "advisory"
        assert verdict["producer_green"] is False
        assert verdict["ok"] is True
    assert manifest["promote_gate_chain"]["rejected"] is False


@pytest.mark.parametrize(
    ("target", "message"),
    (
        ("evaluate_run_releasable", "release 自检失败"),
        ("assemble_promote_sections", "promote 证据组装失败"),
    ),
)
def test_release_or_section_evaluation_error_fails_closed_without_partial_run(
    tmp_path, monkeypatch, target, message
):
    """A required release/section evaluator exception cannot be downgraded to an available run."""

    import app.release_gate.promote_assembler as assembler

    def _boom(*args, **kwargs):
        raise RuntimeError("poisoned evaluator")

    monkeypatch.setattr(assembler, target, _boom)
    with pytest.raises(PromoteError, match=message):
        _promote(tmp_path)
    _assert_no_partial_runs(tmp_path)


def test_gate_chain_error_fails_closed_without_partial_run(tmp_path, monkeypatch):
    """A gate-chain exception is not an advisory result and leaves no published run."""

    import app.release_gate.gate_registry as gate_registry

    class _BrokenChain:
        def evaluate(self, *args, **kwargs):
            raise RuntimeError("poisoned gate chain")

    monkeypatch.setattr(gate_registry, "ensure_default_chain", lambda: _BrokenChain())
    with pytest.raises(PromoteError, match="promote 门链执行失败"):
        _promote(tmp_path)
    _assert_no_partial_runs(tmp_path)


def test_file_write_error_audits_construction_and_never_publishes_run(tmp_path, monkeypatch):
    """A mid-write failure leaves one hidden audit artifact and no public run."""

    import app.ide.promote as promote_module

    write_new = promote_module._write_new_bytes_at

    def _partial_then_fail(directory_fd, name, payload):
        write_new(directory_fd, name, payload)
        if name == "portfolio.csv":
            raise RuntimeError("disk write failed")

    monkeypatch.setattr(promote_module, "_write_new_bytes_at", _partial_then_fail)
    with pytest.raises(RuntimeError, match="disk write failed"):
        _promote(tmp_path)
    assert list(tmp_path.glob("ide_*")) == []
    audited = list((tmp_path / ".staging").glob("*.construction_failed.*"))
    assert len(audited) == 1
    assert (audited[0] / "portfolio.csv").is_file()
    assert not (audited[0] / "run.json").exists()


def test_file_write_baseexception_audits_construction_and_preserves_type(
    tmp_path,
    monkeypatch,
):
    """A construction process boundary is audited and re-raised unchanged."""

    import app.ide.promote as promote_module

    write_new = promote_module._write_new_bytes_at

    class InjectedConstructionCrash(BaseException):
        pass

    def _partial_then_crash(directory_fd, name, payload):
        write_new(directory_fd, name, payload)
        if name == "portfolio.csv":
            raise InjectedConstructionCrash("construction boundary")

    monkeypatch.setattr(promote_module, "_write_new_bytes_at", _partial_then_crash)
    with pytest.raises(InjectedConstructionCrash, match="construction boundary"):
        _promote(tmp_path)
    assert list(tmp_path.glob("ide_*")) == []
    audited = list((tmp_path / ".staging").glob("*.construction_failed.*"))
    assert len(audited) == 1
    assert (audited[0] / "portfolio.csv").is_file()


def test_promote_gate_chain_is_json_safe(tmp_path, monkeypatch):
    """promote_gate_chain 必 JSON-safe（已落盘 run.json·能再 dumps 一遍·无对象残留）。"""

    _inject_section(monkeypatch, SECTION9_BOUNDARY_MANIFEST_KEY, _S9_VIOLATION)
    manifest = _read_manifest(_promote(tmp_path))
    json.dumps(manifest["promote_gate_chain"])  # 不抛即 JSON-safe


# ════════════════════════════════════════════════════════════════════════════
# ⑤ 无假绿灯：默认 producer_status=None → 全门 advisory + producer_green=False
# ════════════════════════════════════════════════════════════════════════════
def test_all_gates_advisory_no_producer_green_by_default(tmp_path):
    """★ 守 advisory-first：默认 producer_status=None → 三门全 advisory·**无任一 producer 假绿灯**。"""

    chain = _read_manifest(_promote(tmp_path))["promote_gate_chain"]
    assert chain["rejected"] is False
    for v in chain["verdicts"]:
        assert v["advisory_or_enforce"] == "advisory", "无 producer 标绿 → 全 advisory（advisory-first）"
        assert v["producer_green"] is False, "确认无任何 producer 假绿灯（出厂全红）"
        assert v["flip_refused"] is True, "enforce_intent 门 producer 红 → 拒翻被诚实记录（非静默）"


# ════════════════════════════════════════════════════════════════════════════
# ⑥ 单一注册收口：registry 注册恰已落地全部节门 + ensure_default_chain 幂等（reset 安全）
# ════════════════════════════════════════════════════════════════════════════
def test_registry_registers_exactly_the_landed_gates():
    """registry 把全部已落地节门（§9 边界/§10 成本/§10 控制面/§13 信任）注册进任意空链·无遗漏无多余。"""

    chain = PromoteGateChain()
    register_all_gates(chain)
    assert set(chain.gate_names) == _ALL_GATE_NAMES


def test_ensure_default_chain_idempotent_and_reset_safe():
    """ensure_default_chain 幂等：连调两次不撞 register 防重抛·返回同一进程级单例·reset 后重填。"""

    reset_default_chain()
    c1 = ensure_default_chain()
    assert set(c1.gate_names) == _ALL_GATE_NAMES
    c2 = ensure_default_chain()  # 第二次：链非空 → 跳过注册（不抛重复）
    assert c1 is c2 and set(c2.gate_names) == _ALL_GATE_NAMES
    reset_default_chain()
    c3 = ensure_default_chain()  # reset 后 → 重新填满
    assert set(c3.gate_names) == _ALL_GATE_NAMES


# ════════════════════════════════════════════════════════════════════════════
# ⑦ 冷导入安全（SA-3 纪律·镜像 section9/section10/chain 模块）
# ════════════════════════════════════════════════════════════════════════════
def test_gate_registry_cold_importable():
    """冷导入：全新解释器 import gate_registry **不**撞 app.governance 既有冷导入循环（顶层不触 governance·
    register 内 governance 惰性载入只在调用期触发·模块无 import 期 auto-register 副作用）。"""

    backend_root = Path(__file__).resolve().parents[1]  # app/backend
    code = (
        "import app.release_gate.gate_registry as m; "
        "assert m.ensure_default_chain and m.register_all_gates"
    )
    proc = subprocess.run(
        [sys.executable, "-c", code],
        cwd=str(backend_root),
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert proc.returncode == 0, (
        f"gate_registry 应冷导入成功（不依赖导入顺序）:\nSTDOUT={proc.stdout}\nSTDERR={proc.stderr}"
    )
