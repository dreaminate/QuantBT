from __future__ import annotations

import hashlib
import inspect
import json
import threading
from dataclasses import asdict, dataclass, is_dataclass, replace
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from conftest import build_verified_spine_chain

from app.ide.service import StrategyFile
from app.lineage.ids import content_hash
from app.research_os.asset_lifecycle import (
    AssetCategory,
    GovernedAssetRecord,
    LifecycleState,
    PersistentAssetLifecycleRegistry,
)
from app.research_os.asset_rag import (
    AssetRAGDocument,
    PersistentResearchAssetRAGIndex,
    RAGPermission,
    RAGProjection,
    RAGQueryContext,
)
from app.research_os.compiler import (
    COMPILER_IR_PROOF_CODEC,
    COMPILER_PASS_PROOF_CODEC,
    CompilerIRRecord,
    CompilerPassRecord,
    PersistentCompilerIRStore,
)
from app.research_os.entrypoint_evidence import (
    ENTRYPOINT_EVIDENCE_PROOF_CODEC,
    PersistentEntrypointEvidenceRegistry,
)
from app.research_os.goal_coverage import (
    GOAL_ENTRYPOINT_COVERAGE_PROOF_CODEC,
    GoalEntrypointCoverageRecord,
    PersistentGoalEntrypointCoverageRegistry,
    goal_entrypoint_coverage_identity,
)
from app.research_os.goal_proof_head_lock import acquire_goal_proof_head_lock
from app.research_os.goal_proof_ledger import GoalProofLedger, ProofBundle
from app.research_os.goal_proof_records import typed_proof_record_member
from app.research_os.goal_validation_receipts import (
    GOAL_VALIDATION_RECEIPT_PROOF_CODEC,
    GoalValidationOutcome,
    GoalValidationReceipt,
    PersistentGoalValidationReceiptRegistry,
)
from app.research_os.platform_coverage import PlatformSpecificRef
from app.research_os.platform_row_sources import PersistentPlatformRowSourceRegistry
from app.research_os.platform_source_adapters_m16_m21 import (
    PlatformSourceAdaptersM16M21Context,
    build_platform_source_adapters_m16_m21,
)
from app.research_os.platform_source_lineage_core import (
    PlatformSourceLineageCoreCommitError,
    PlatformSourceLineageCoreError,
    PlatformSourceLineageFinalizer,
    PlatformSourceLineagePolicyResolution,
    UpstreamBusinessRAGBinding,
)
from app.research_os.platform_typed_sources import RealPlatformTypedSourceResolver
from app.research_os.ref_resolution import build_real_ref_resolver
from app.research_os.spine import (
    ActorSource,
    ConsistencyStatus,
    DefinitionStatus,
    EntrySource,
    EvidenceStatus,
    MathematicalSpineChainRecord,
    PersistentResearchGraphStore,
    QRORecord,
    QROType,
    ResearchGraphCommand,
    RuntimeStatus,
)


OWNER = "owner:platform-source-lineage-core"
OTHER_OWNER = "owner:platform-source-lineage-core:other"
ROW = "M21"
ENTRYPOINT = "api:strategies.templates.fork_to_ide"
ASSET_REF = "governed_asset:strategy_template:platform_core"
IDE_STRATEGY_ID = "strategy-platform-source-lineage-core-legacy"
IDE_STRATEGY_REF = f"ide_strategy:{IDE_STRATEGY_ID}"
IDE_OWNER_USERNAME = "platform_source_lineage_core_owner"
MOCK_LABEL_REF = "mock_label:strategy_template:platform_core"
ASSET_CATEGORY_REF = "asset_category:strategy_template:platform_core"
EVIDENCE_REF = "evidence:platform_source_lineage_core:m21"
PERMISSION_REF = "permission:platform_source_lineage_core:m21"
COMPILER_IR_REF = "compiler_ir:platform_source_lineage_core:m21"
COMPILER_PASS_REF = "compiler_pass:platform_source_lineage_core:m21"
COMPILER_PASS_NAME = "derive_platform_source_lineage_from_business_entrypoint"
RUN_PLAN_REF = "runplan:platform_source_lineage_core:m21"
ROLLBACK_REF = "rollback:platform_source_lineage_core:m21"
ENVIRONMENT_LOCK_REF = "env:platform_source_lineage_core:v1"


def _digest(value: str) -> str:
    return "sha256:" + hashlib.sha256(value.encode("utf-8")).hexdigest()


def _strings(value: Any) -> set[str]:
    found: set[str] = set()
    if isinstance(value, str):
        if value.strip():
            found.add(value.strip())
    elif isinstance(value, dict):
        for key, child in value.items():
            found.update(_strings(key))
            found.update(_strings(child))
    elif isinstance(value, (tuple, list, set, frozenset)):
        for child in value:
            found.update(_strings(child))
    elif value is not None and is_dataclass(value):
        found.update(_strings(asdict(value)))
    return found


def _events(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _commit_proof_records(
    ledger: GoalProofLedger,
    *,
    subject: str,
    records: tuple[tuple[Any, Any], ...],
) -> None:
    ledger.commit(
        ProofBundle(
            owner=OWNER,
            subject=subject,
            members=tuple(
                typed_proof_record_member(record, codec=codec)
                for record, codec in records
            ),
            metadata={"producer": "test_platform_source_lineage_core"},
        )
    )
    ledger.sync()


def _chain_candidate() -> MathematicalSpineChainRecord:
    return MathematicalSpineChainRecord(
        chain_ref="math_spine_chain:pending",
        data_semantics_ref="dataset_semantics:template_examples:v1",
        factor_ref="factor:template_examples:none",
        model_ref="model:template_examples:none",
        forecast_ref="forecast:template_examples:none",
        signal_contract_ref="signal_contract:template_examples:none",
        strategy_book_ref=ASSET_REF,
        portfolio_policy_ref="portfolio_policy:template_examples:none",
        risk_policy_ref="risk_policy:template_examples:none",
        execution_policy_ref="execution_policy:template_examples:offline",
        backtest_run_ref="backtest_run:template_examples:none",
        attribution_ref="attribution:template_examples:none",
        monitor_ref="monitor:template_examples:labels",
        theory_binding_refs=("theory_binding:pending",),
        consistency_check_refs=("consistency_check:pending",),
        methodology_choice_ref="methodology_choice:pending",
        responsibility_boundary_ref="responsibility:pending",
        evidence_refs=(EVIDENCE_REF,),
        validation_refs=("pytest:platform_source_lineage_core",),
        consistency_verdict=ConsistencyStatus.ACCEPTED,
        target_runtime=RuntimeStatus.OFFLINE,
        recorded_by=OWNER,
    )


def _qro(*, chain_ref: str) -> QRORecord:
    return QRORecord(
        qro_type=QROType.STRATEGY_BOOK,
        owner=OWNER,
        actor=ActorSource.USER_MANUAL,
        input_contract={
            "entry_source": EntrySource.API.value,
            "asset_ref": ASSET_REF,
        },
        output_contract={
            "ide_strategy_ref": IDE_STRATEGY_REF,
            "mock_label_ref": MOCK_LABEL_REF,
            "asset_category_ref": ASSET_CATEGORY_REF,
            "status": "template_fork_recorded",
        },
        market="global",
        universe="strategy_templates",
        horizon="current",
        frequency="event",
        lineage=("platform", "template", "m21"),
        implementation_hash="platform_source_lineage_core:m21:v1",
        assumptions=("the template is visibly labeled and owner scoped",),
        known_limits=("the template is candidate context, not production",),
        failure_modes=("a recombined mock/category label is rejected",),
        validation_plan=("resolve the three-ledger source certification twice",),
        definition_status=DefinitionStatus.IMPLEMENTED,
        evidence_status=EvidenceStatus.SUFFICIENT,
        runtime_status=RuntimeStatus.OFFLINE,
        evidence_refs=(EVIDENCE_REF,),
        mathematical_refs=(chain_ref,),
        permission=PERMISSION_REF,
        allowed_environment=RuntimeStatus.OFFLINE,
    )


def _ide_strategy() -> StrategyFile:
    return StrategyFile(
        strategy_id=IDE_STRATEGY_ID,
        owner_username=IDE_OWNER_USERNAME,
        name="platform_source_lineage_core_legacy",
        code="def generate_signal(ctx):\n    return 0\n",
        asset_class="equity_cn",
        description="forked from the governed M21 template",
        updated_at_utc="2026-07-13T00:00:00Z",
        market_data_use_validation_refs=[],
    )


def _record_graph(
    graph: PersistentResearchGraphStore,
    qro: QRORecord,
) -> ResearchGraphCommand:
    command = ResearchGraphCommand(
        source=EntrySource.API,
        command_type="upsert_qro",
        actor_source=ActorSource.USER_MANUAL,
        actor=OWNER,
        payload={"qro": qro},
        evidence_refs=(EVIDENCE_REF,),
        tool_record_refs=(f"endpoint:{ENTRYPOINT}",),
    )
    graph.apply(command)
    return command


def _record_receipt(
    receipts: PersistentGoalValidationReceiptRegistry,
    *,
    qro_ref: str,
    graph_ref: str,
    persist: bool = True,
) -> GoalValidationReceipt:
    provisional = GoalValidationReceipt(
        validation_ref="",
        owner_user_id=OWNER,
        subject_qro_refs=(qro_ref,),
        graph_command_refs=(graph_ref,),
        validator_identifiers=(
            "runtime_validator:platform_source_lineage_core_m21_v1",
        ),
        test_identifiers=("pytest:test_platform_source_lineage_core",),
        outcome=GoalValidationOutcome.PASSED,
        evidence_refs=(EVIDENCE_REF,),
        evidence_digests=(_digest(EVIDENCE_REF),),
    )
    candidate = replace(
        provisional,
        validation_ref=provisional.canonical_validation_ref,
    )
    return receipts.record_receipt(candidate) if persist else candidate


def _record_compiler(
    compiler: PersistentCompilerIRStore,
    *,
    qro_ref: str,
    graph_ref: str,
    receipt_ref: str,
    chain_ref: str,
    evidence_ref: str,
    persist: bool = True,
) -> tuple[CompilerIRRecord, CompilerPassRecord]:
    canonical = (
        f"research_graph_command:{graph_ref}",
        f"entrypoint:{ENTRYPOINT}",
    )
    ir = CompilerIRRecord(
        ir_ref=COMPILER_IR_REF,
        source_qro_refs=(qro_ref,),
        graph_command_refs=(graph_ref,),
        canonical_command_refs=canonical,
        node_refs=(f"qro:{qro_ref}", f"entrypoint:{ENTRYPOINT}"),
        edge_refs=(),
        artifact_refs=(ASSET_REF,),
        theory_binding_refs=(),
        consistency_check_refs=(),
        evidence_refs=(evidence_ref,),
        validation_refs=(receipt_ref,),
        permission_ref=PERMISSION_REF,
        deterministic_run_plan_ref=RUN_PLAN_REF,
        rollback_ref=ROLLBACK_REF,
        environment_lock_ref=ENVIRONMENT_LOCK_REF,
        mathematical_spine_chain_refs=(chain_ref,),
        owner=OWNER,
        target_runtime=RuntimeStatus.OFFLINE,
        mock_profile="none",
    )
    compiler_pass = CompilerPassRecord(
        pass_ref=COMPILER_PASS_REF,
        pass_name=COMPILER_PASS_NAME,
        input_ir_refs=(),
        output_ir_ref=ir.ir_ref,
        input_qro_refs=(qro_ref,),
        graph_command_refs=(graph_ref,),
        canonical_command_refs=canonical,
        actor=OWNER,
        actor_source=ActorSource.USER_MANUAL,
        entry_source=EntrySource.API,
        permission_ref=PERMISSION_REF,
        tool_record_refs=(ENTRYPOINT, f"entrypoint:{ENTRYPOINT}"),
        evidence_refs=(evidence_ref,),
        validation_refs=(receipt_ref,),
        deterministic_run_plan_ref=ir.deterministic_run_plan_ref,
        rollback_ref=ir.rollback_ref,
    )
    if persist:
        ir = compiler.record_ir(ir)
        compiler_pass = compiler.record_pass(compiler_pass)
    return ir, compiler_pass


def _coverage(
    *,
    qro_ref: str,
    graph_ref: str,
    ir: CompilerIRRecord,
    compiler_pass: CompilerPassRecord,
    lifecycle_ref: str,
    evidence_ref: str,
    section: str = "§1",
) -> GoalEntrypointCoverageRecord:
    coverage_ref = goal_entrypoint_coverage_identity(
        entry_source=EntrySource.API,
        entrypoint_ref=ENTRYPOINT,
        goal_sections=(section,),
        qro_refs=(qro_ref,),
        research_graph_command_refs=(graph_ref,),
        compiler_ir_refs=(ir.ir_ref,),
        compiler_pass_refs=(compiler_pass.pass_ref,),
    )
    return GoalEntrypointCoverageRecord(
        coverage_ref=coverage_ref,
        entry_source=EntrySource.API,
        entrypoint_ref=ENTRYPOINT,
        goal_sections=(section,),
        qro_refs=(qro_ref,),
        research_graph_command_refs=(graph_ref,),
        compiler_ir_refs=(ir.ir_ref,),
        compiler_pass_refs=(compiler_pass.pass_ref,),
        evidence_refs=(evidence_ref,),
        validation_refs=ir.validation_refs,
        permission_refs=(PERMISSION_REF,),
        replay_refs=(
            f"replay:research_graph:{graph_ref}",
            f"replay:compiler_ir:{ir.ir_ref}",
            f"replay:compiler_pass:{compiler_pass.pass_ref}",
        ),
        canonical_command_refs=ir.canonical_command_refs,
        lifecycle_refs=(lifecycle_ref,),
        recorded_by=OWNER,
        claims_full_product_entrypoint=False,
        silent_mock_fallback_used=False,
        raw_payload_persisted=False,
    )


class _CoverageLifecycleLoader:
    """Owner-envelope a real persistent asset for strict coverage resolution."""

    def __init__(self, lifecycle: PersistentAssetLifecycleRegistry) -> None:
        self._lifecycle = lifecycle

    def __call__(self, ref: str, owner: str) -> Any:
        asset = self._lifecycle.governed_asset(ref, owner_user_id=owner)
        return SimpleNamespace(
            lifecycle_ref=asset.asset_ref,
            owner_user_id=owner,
            recorded_by=owner,
            governed_asset=asset,
        )


class _M21AnchorPolicy:
    def __init__(
        self,
        *,
        graph: PersistentResearchGraphStore,
        lifecycle: PersistentAssetLifecycleRegistry,
        spine: Any,
        upstream: UpstreamBusinessRAGBinding,
        drift: bool = False,
        recombined_asset_ref: str = "",
    ) -> None:
        self._graph = graph
        self._lifecycle = lifecycle
        self._spine = spine
        self._upstream = upstream
        self._drift = drift
        self._recombined_asset_ref = recombined_asset_ref
        self._reads = 0

    def resolve(
        self,
        *,
        owner_user_id: str,
        m_row: str,
        anchor_ref: str,
    ) -> PlatformSourceLineagePolicyResolution:
        if m_row != ROW:
            raise LookupError("M21 policy row mismatch")
        asset = self._lifecycle.governed_asset(
            anchor_ref,
            owner_user_id=owner_user_id,
        )
        projections = [
            item
            for item in self._graph.projection_index(owner=owner_user_id)
            if anchor_ref
            in _strings(
                (
                    self._graph.qro(item.qro_id).input_contract,
                    self._graph.qro(item.qro_id).output_contract,
                )
            )
        ]
        if len(projections) != 1:
            raise LookupError("anchor must select exactly one current QRO")
        qro = self._graph.qro(projections[0].qro_id)
        chains = [
            item
            for item in self._spine.chains(owner=owner_user_id)
            if anchor_ref in _strings(item)
        ]
        if len(chains) != 1:
            raise LookupError("anchor must select exactly one Mathematical Spine")
        selected_asset = asset
        if self._recombined_asset_ref:
            selected_asset = self._lifecycle.governed_asset(
                self._recombined_asset_ref,
                owner_user_id=owner_user_id,
            )
        self._reads += 1
        metadata = (
            ("graph_command_ref", projections[0].command_id),
            ("asset_category", asset.category),
            ("policy_revision", "v2" if self._drift and self._reads > 1 else "v1"),
        )
        return PlatformSourceLineagePolicyResolution(
            m_row=ROW,
            anchor_ref=asset.asset_ref,
            qro_ref=qro.qro_id,
            business_entry_source=str(qro.input_contract["entry_source"]),
            business_entrypoint_ref=ENTRYPOINT,
            lifecycle_ref=asset.asset_ref,
            math_spine_ref=chains[0].chain_ref,
            specific_refs=(
                PlatformSpecificRef(
                    "mock_label_ref",
                    str(selected_asset.mock_label_ref),
                ),
                PlatformSpecificRef(
                    "asset_category_ref",
                    str(selected_asset.asset_category_ref),
                ),
            ),
            primary_rag_asset_ref=asset.asset_ref,
            row_policy_metadata=metadata,
            upstream_business_rag=self._upstream,
        )

    def semantic_violations(
        self,
        resolution: PlatformSourceLineagePolicyResolution,
        *,
        owner_user_id: str,
        business_coverage: GoalEntrypointCoverageRecord,
        capability_record: Any,
        rag_document: AssetRAGDocument,
    ) -> tuple[str, ...]:
        violations: list[str] = []
        try:
            asset = self._lifecycle.governed_asset(
                resolution.anchor_ref,
                owner_user_id=owner_user_id,
            )
            qro = self._graph.qro(resolution.qro_ref)
            chain = self._spine.verified_chain(
                resolution.math_spine_ref,
                owner=owner_user_id,
            )
        except Exception as exc:  # noqa: BLE001 - policy fails closed.
            return (f"M21 anchor semantics lookup failed:{type(exc).__name__}",)
        expected_specifics = {
            "mock_label_ref": str(asset.mock_label_ref),
            "asset_category_ref": str(asset.asset_category_ref),
        }
        actual_specifics = {
            item.key: item.ref for item in capability_record.specific_refs
        }
        declared = _strings((qro.input_contract, qro.output_contract))
        if qro.owner != owner_user_id:
            violations.append("M21 QRO owner mismatch")
        if not {asset.asset_ref, *expected_specifics.values()}.issubset(declared):
            violations.append("M21 QRO contracts do not bind the anchor and labels")
        if actual_specifics != expected_specifics:
            violations.append("M21 specific refs recombine another governed asset")
        if capability_record.lifecycle_ref != asset.asset_ref:
            violations.append("M21 lifecycle ref does not equal the anchor asset")
        if tuple(business_coverage.lifecycle_refs) != (asset.asset_ref,):
            violations.append("M21 business coverage lifecycle does not equal the anchor")
        if business_coverage.entrypoint_ref != ENTRYPOINT:
            violations.append("M21 business entrypoint mismatch")
        if asset.asset_ref not in _strings(chain):
            violations.append("M21 Mathematical Spine does not bind the anchor asset")
        if rag_document.asset_ref != asset.asset_ref:
            violations.append("M21 RAG document does not bind the anchor asset")
        if asset.asset_ref not in rag_document.permission.allowed_assets:
            violations.append("M21 RAG permission does not bind the anchor asset")
        return tuple(violations)


@dataclass
class _System:
    root: Path
    proof_ledger: GoalProofLedger
    graph: PersistentResearchGraphStore
    lifecycle: PersistentAssetLifecycleRegistry
    spine: Any
    compiler: PersistentCompilerIRStore
    receipts: PersistentGoalValidationReceiptRegistry
    entrypoints: PersistentGoalEntrypointCoverageRegistry
    rag: PersistentResearchAssetRAGIndex
    typed: RealPlatformTypedSourceResolver
    rows: PersistentPlatformRowSourceRegistry
    policy: _M21AnchorPolicy
    business: GoalEntrypointCoverageRecord
    ide_strategy: StrategyFile

    @property
    def coverage_path(self) -> Path:
        return self.root / "goal_entrypoint_coverage.jsonl"

    @property
    def rag_path(self) -> Path:
        return self.root / "research_asset_rag.jsonl"

    @property
    def row_path(self) -> Path:
        return self.root / "platform_row_sources.jsonl"

    def finalizer(
        self,
        *,
        policy: _M21AnchorPolicy | None = None,
        record_coverage=None,
        record_rag_document=None,
        record_certification=None,
    ) -> PlatformSourceLineageFinalizer:
        return PlatformSourceLineageFinalizer(
            policy_resolver=policy or self.policy,
            entrypoint_registry=self.entrypoints,
            rag_index=self.rag,
            row_source_registry=self.rows,
            source_resolver=self.typed,
            record_coverage=record_coverage or self.record_coverage,
            record_rag_document=record_rag_document,
            record_certification=record_certification,
        )

    def record_coverage(
        self,
        record: GoalEntrypointCoverageRecord,
    ) -> GoalEntrypointCoverageRecord:
        _commit_proof_records(
            self.proof_ledger,
            subject=f"platform_source_lineage_coverage:{record.coverage_ref}",
            records=((record, GOAL_ENTRYPOINT_COVERAGE_PROOF_CODEC),),
        )
        self.entrypoints.refresh()
        return self.entrypoints.canonical_coverage(
            record.coverage_ref,
            owner=record.recorded_by,
        )


def _strict_entrypoints(
    root: Path,
    *,
    graph: PersistentResearchGraphStore,
    lifecycle: PersistentAssetLifecycleRegistry,
    rag: PersistentResearchAssetRAGIndex,
    spine: Any,
    compiler: PersistentCompilerIRStore,
    receipts: PersistentGoalValidationReceiptRegistry,
    proof_ledger: GoalProofLedger,
) -> PersistentGoalEntrypointCoverageRegistry:
    evidence = PersistentEntrypointEvidenceRegistry(
        root / "entrypoint_evidence.jsonl",
        research_graph_store=graph,
        compiler_store=compiler,
        validation_receipt_registry=receipts,
        proof_ledger=proof_ledger,
        legacy_read_only=True,
    )
    resolver = build_real_ref_resolver(
        research_graph_store=graph,
        lifecycle_registry=object(),
        governance_registry=None,
        rag_index=rag,
        spine_chain_registry=spine,
        compiler_store=compiler,
        goal_validation_receipt_registry=receipts,
        platform_source_evidence_registry=evidence,
        lifecycle_loaders=(_CoverageLifecycleLoader(lifecycle),),
    )
    return PersistentGoalEntrypointCoverageRegistry(
        root / "goal_entrypoint_coverage.jsonl",
        resolver=resolver,
        proof_ledger=proof_ledger,
        legacy_read_only=True,
    )


def _wire_runtime(
    root: Path,
    *,
    graph: PersistentResearchGraphStore,
    lifecycle: PersistentAssetLifecycleRegistry,
    spine: Any,
    compiler: PersistentCompilerIRStore,
    receipts: PersistentGoalValidationReceiptRegistry,
    entrypoints: PersistentGoalEntrypointCoverageRegistry,
    rag: PersistentResearchAssetRAGIndex,
    policy: _M21AnchorPolicy,
    business: GoalEntrypointCoverageRecord,
    ide_strategy: StrategyFile,
    proof_ledger: GoalProofLedger,
) -> _System:
    def load_ide_strategy(ref: str, owner: str) -> StrategyFile:
        if (
            ref != IDE_STRATEGY_REF
            or owner != OWNER
            or ide_strategy.strategy_id != IDE_STRATEGY_ID
            or ide_strategy.owner_username != IDE_OWNER_USERNAME
        ):
            raise LookupError("M21 current owned IDE strategy is unavailable")
        return ide_strategy

    adapters, validators = build_platform_source_adapters_m16_m21(
        PlatformSourceAdaptersM16M21Context(
            research_graph_store=graph,
            asset_lifecycle_registry=lifecycle,
            rag_index=rag,
            spine_chain_registry=spine,
            ide_strategy_loader=load_ide_strategy,
        )
    )
    assert {"mock_label_ref", "asset_category_ref"}.issubset(adapters)
    assert ROW in validators

    def load_asset(ref: str, owner: str, _record: Any) -> GovernedAssetRecord:
        return lifecycle.governed_asset(ref, owner_user_id=owner)

    typed = RealPlatformTypedSourceResolver(
        research_graph_store=graph,
        lifecycle_loaders=(load_asset,),
        goal_validation_receipt_registry=receipts,
        rag_index=rag,
        spine_chain_registry=spine,
        compiler_store=compiler,
        specific_adapters=adapters,
        row_validators=validators,
    )
    rows = PersistentPlatformRowSourceRegistry(
        root / "platform_row_sources.jsonl",
        entrypoint_registry=entrypoints,
        rag_index=rag,
        source_resolver=typed,
    )
    return _System(
        root=root,
        proof_ledger=proof_ledger,
        graph=graph,
        lifecycle=lifecycle,
        spine=spine,
        compiler=compiler,
        receipts=receipts,
        entrypoints=entrypoints,
        rag=rag,
        typed=typed,
        rows=rows,
        policy=policy,
        business=business,
        ide_strategy=ide_strategy,
    )


def _build_system(root: Path) -> _System:
    proof_ledger = GoalProofLedger(root / "goal_proof_ledger")
    ide_strategy = _ide_strategy()
    lifecycle = PersistentAssetLifecycleRegistry(root / "asset_lifecycle.jsonl")
    asset = lifecycle.record_governed_asset(
        GovernedAssetRecord(
            asset_ref=ASSET_REF,
            asset_type="StrategyBook",
            category=AssetCategory.TEMPLATE,
            lifecycle_state=LifecycleState.SPECIFIED,
            evidence_refs=(EVIDENCE_REF,),
            validation_plan_ref="validation_plan:template_labels:v1",
            promotion_history=(),
            display_label="TEMPLATE - candidate context only",
            mock_label_ref=MOCK_LABEL_REF,
            asset_category_ref=ASSET_CATEGORY_REF,
        ),
        owner_user_id=OWNER,
    )
    spine, chain, _ledger = build_verified_spine_chain(
        root / "spine",
        _chain_candidate(),
    )
    graph = PersistentResearchGraphStore(root / "research_graph.jsonl")
    qro = _qro(chain_ref=chain.chain_ref)
    command = _record_graph(graph, qro)
    compiler = PersistentCompilerIRStore(
        root / "compiler.jsonl",
        proof_ledger=proof_ledger,
        legacy_read_only=True,
    )
    receipts = PersistentGoalValidationReceiptRegistry(
        root / "goal_validation_receipts.jsonl",
        proof_ledger=proof_ledger,
        legacy_read_only=True,
    )
    receipt = _record_receipt(
        receipts,
        qro_ref=qro.qro_id,
        graph_ref=command.command_id,
        persist=False,
    )
    coverage_ref = goal_entrypoint_coverage_identity(
        entry_source=EntrySource.API,
        entrypoint_ref=ENTRYPOINT,
        goal_sections=("§1",),
        qro_refs=(qro.qro_id,),
        research_graph_command_refs=(command.command_id,),
        compiler_ir_refs=(COMPILER_IR_REF,),
        compiler_pass_refs=(COMPILER_PASS_REF,),
    )
    evidence_registry = PersistentEntrypointEvidenceRegistry(
        root / "entrypoint_evidence.jsonl",
        research_graph_store=graph,
        compiler_store=compiler,
        validation_receipt_registry=receipts,
        proof_ledger=proof_ledger,
        legacy_read_only=True,
    )
    evidence = evidence_registry.prepare_record_from_receipt_candidate(
        validation_receipt_candidate=receipt,
        owner_user_id=OWNER,
        entry_source=EntrySource.API.value,
        entrypoint_ref=ENTRYPOINT,
        goal_sections=("§1",),
        qro_ref=qro.qro_id,
        research_graph_ref=command.command_id,
        compiler_ir_ref=COMPILER_IR_REF,
        compiler_pass_ref=COMPILER_PASS_REF,
        coverage_ref=coverage_ref,
        actor_source=ActorSource.USER_MANUAL.value,
        pass_name=COMPILER_PASS_NAME,
        permission_ref=PERMISSION_REF,
        environment_lock_ref=ENVIRONMENT_LOCK_REF,
        deterministic_run_plan_ref=RUN_PLAN_REF,
        rollback_ref=ROLLBACK_REF,
        lifecycle_refs=(asset.asset_ref,),
        mathematical_spine_chain_refs=(chain.chain_ref,),
    )
    ir, compiler_pass = _record_compiler(
        compiler,
        qro_ref=qro.qro_id,
        graph_ref=command.command_id,
        receipt_ref=receipt.validation_ref,
        chain_ref=chain.chain_ref,
        evidence_ref=evidence.evidence_ref,
        persist=False,
    )
    rag = PersistentResearchAssetRAGIndex(root / "research_asset_rag.jsonl")
    upstream_document = rag.add_for_owner(
        AssetRAGDocument(
            source_id="business_template_context",
            version="v1",
            title="Strategy template business context",
            body="The visible strategy template remains candidate business context.",
            projection=RAGProjection.RESEARCH,
            asset_ref=asset.asset_ref,
            permission=RAGPermission(
                allowed_users=(OWNER,),
                allowed_desks=("research",),
                allowed_assets=(asset.asset_ref,),
                permission_tags=("research.read",),
            ),
            applicability="template selection before platform certification",
            source_kind="GovernedTemplateContext",
            metadata={"governed_asset_ref": asset.asset_ref},
            evidence_label="candidate_context",
        ),
        owner_user_id=OWNER,
    )
    context = RAGQueryContext(
        user_id=OWNER,
        desk="research",
        visible_asset_refs=(asset.asset_ref,),
        permission_tags=("research.read",),
        actor="agent",
    )
    hits = rag.retrieve_for_owner(
        "strategy template business context",
        owner_user_id=OWNER,
        context=context,
    )
    assert [item.document_id for item in hits] == [upstream_document.document_id]
    usage = rag.record_usage_for_owner(
        owner_user_id=OWNER,
        agent_id="agent:platform_source_lineage_policy",
        workflow_ref="workflow:platform_source_lineage_core:m21",
        tool_call_ref="tool_call:platform_source_lineage_core:resolve_anchor",
        query="strategy template business context",
        context=context,
        hits=hits,
        purpose="resolve the business anchor before platform certification",
    )
    upstream = UpstreamBusinessRAGBinding(
        usage_ref=usage.usage_id,
        document_refs=(upstream_document.document_id,),
    )
    entrypoints = _strict_entrypoints(
        root,
        graph=graph,
        lifecycle=lifecycle,
        rag=rag,
        spine=spine,
        compiler=compiler,
        receipts=receipts,
        proof_ledger=proof_ledger,
    )
    business = _coverage(
        qro_ref=qro.qro_id,
        graph_ref=command.command_id,
        ir=ir,
        compiler_pass=compiler_pass,
        lifecycle_ref=asset.asset_ref,
        evidence_ref=evidence.evidence_ref,
    )
    _commit_proof_records(
        proof_ledger,
        subject="platform_source_lineage_initial_business_bundle",
        records=(
            (receipt, GOAL_VALIDATION_RECEIPT_PROOF_CODEC),
            (evidence, ENTRYPOINT_EVIDENCE_PROOF_CODEC),
            (ir, COMPILER_IR_PROOF_CODEC),
            (compiler_pass, COMPILER_PASS_PROOF_CODEC),
            (business, GOAL_ENTRYPOINT_COVERAGE_PROOF_CODEC),
        ),
    )
    for registry in (receipts, evidence_registry, compiler, entrypoints):
        registry.refresh()
    business = entrypoints.canonical_coverage(
        business.coverage_ref,
        owner=OWNER,
    )
    policy = _M21AnchorPolicy(
        graph=graph,
        lifecycle=lifecycle,
        spine=spine,
        upstream=upstream,
    )
    return _wire_runtime(
        root,
        graph=graph,
        lifecycle=lifecycle,
        spine=spine,
        compiler=compiler,
        receipts=receipts,
        entrypoints=entrypoints,
        rag=rag,
        policy=policy,
        business=business,
        ide_strategy=ide_strategy,
        proof_ledger=proof_ledger,
    )


def _alternate_business_coverage(
    system: _System,
    *,
    section: str,
) -> GoalEntrypointCoverageRecord:
    """Prepare another coverage head over the same canonical compiler bundle."""

    qro_ref = system.business.qro_refs[0]
    graph_ref = system.business.research_graph_command_refs[0]
    ir = system.compiler.canonical_ir(
        system.business.compiler_ir_refs[0],
        owner=OWNER,
    )
    compiler_pass = system.compiler.canonical_compiler_pass(
        system.business.compiler_pass_refs[0],
        owner=OWNER,
    )
    return _coverage(
        qro_ref=qro_ref,
        graph_ref=graph_ref,
        ir=ir,
        compiler_pass=compiler_pass,
        lifecycle_ref=ASSET_REF,
        evidence_ref=system.business.evidence_refs[0],
        section=section,
    )


def _reload(system: _System) -> _System:
    proof_ledger = GoalProofLedger(system.root / "goal_proof_ledger")
    graph = PersistentResearchGraphStore(system.graph.path)
    lifecycle = PersistentAssetLifecycleRegistry(system.lifecycle.path)
    compiler = PersistentCompilerIRStore(
        system.compiler.path,
        proof_ledger=proof_ledger,
        legacy_read_only=True,
    )
    receipts = PersistentGoalValidationReceiptRegistry(
        system.receipts.path,
        proof_ledger=proof_ledger,
        legacy_read_only=True,
    )
    rag = PersistentResearchAssetRAGIndex(system.rag_path)
    entrypoints = _strict_entrypoints(
        system.root,
        graph=graph,
        lifecycle=lifecycle,
        rag=rag,
        spine=system.spine,
        compiler=compiler,
        receipts=receipts,
        proof_ledger=proof_ledger,
    )
    policy = _M21AnchorPolicy(
        graph=graph,
        lifecycle=lifecycle,
        spine=system.spine,
        upstream=system.policy._upstream,
    )
    return _wire_runtime(
        system.root,
        graph=graph,
        lifecycle=lifecycle,
        spine=system.spine,
        compiler=compiler,
        receipts=receipts,
        entrypoints=entrypoints,
        rag=rag,
        policy=policy,
        business=system.business,
        ide_strategy=system.ide_strategy,
        proof_ledger=proof_ledger,
    )


def test_anchor_only_finalizer_commits_three_ledgers_and_retries_idempotently(
    tmp_path: Path,
) -> None:
    system = _build_system(tmp_path)

    qro = system.graph.qro(system.business.qro_refs[0])
    assert qro.input_contract == {
        "entry_source": EntrySource.API.value,
        "asset_ref": ASSET_REF,
    }
    assert qro.output_contract == {
        "ide_strategy_ref": IDE_STRATEGY_REF,
        "mock_label_ref": MOCK_LABEL_REF,
        "asset_category_ref": ASSET_CATEGORY_REF,
        "status": "template_fork_recorded",
    }

    parameters = tuple(
        inspect.signature(PlatformSourceLineageFinalizer.record_current).parameters
    )
    assert parameters == ("self", "owner_user_id", "m_row", "anchor_ref")
    with pytest.raises(
        PlatformSourceLineageCoreError,
        match="canonical platform row",
    ):
        system.finalizer().record_current(
            owner_user_id=OWNER,
            m_row=f" {ROW}",
            anchor_ref=ASSET_REF,
        )

    first = system.finalizer().record_current(
        owner_user_id=OWNER,
        m_row=ROW,
        anchor_ref=ASSET_REF,
    )

    assert first.business_coverage_ref == system.business.coverage_ref
    assert first.coverage.goal_sections == ("§14",)
    assert first.coverage.lifecycle_refs == (ASSET_REF,)
    assert first.rag_document.source_id == "platform_source_lineage:M21"
    assert first.rag_document.source_kind == "server_derived_platform_source_lineage"
    assert first.rag_document.metadata["row_policy"]["asset_category"] == "template"
    assert first.certification.resolved_row.record.m_row == ROW
    assert first.certification.resolved_row.record.rag_ref == first.rag_document.document_id
    upstream = first.rag_document.metadata["upstream_business_rag"]
    assert upstream["document_refs"] == list(system.policy._upstream.document_refs)
    assert first.rag_document.document_id not in _strings(first.rag_document.metadata)
    assert len(system.entrypoints.records(owner=OWNER)) == 2
    assert len(system.rag.owned_documents(owner_user_id=OWNER)) == 2
    assert len(system.rows.current_certifications(owner_user_id=OWNER)) == 1

    reloaded = _reload(system)
    second = reloaded.finalizer().record_current(
        owner_user_id=OWNER,
        m_row=ROW,
        anchor_ref=ASSET_REF,
    )

    assert second.coverage == first.coverage
    assert second.rag_document.document_id == first.rag_document.document_id
    assert second.certification.certification_ref == first.certification.certification_ref
    assert len(reloaded.entrypoints.records(owner=OWNER)) == 2
    assert len(reloaded.rag.owned_documents(owner_user_id=OWNER)) == 2
    assert len(reloaded.rows.current_certifications(owner_user_id=OWNER)) == 1
    assert len(reloaded.entrypoints.canonical_records(owner=OWNER)) == 2
    assert reloaded.proof_ledger.verify().ok
    assert len(_events(reloaded.row_path)) == 1


@pytest.mark.parametrize("boundary", ("coverage", "rag", "certification"))
def test_finalizer_holds_shared_proof_head_across_every_write_boundary(
    tmp_path: Path,
    boundary: str,
) -> None:
    system = _build_system(tmp_path)
    entered = threading.Event()
    release = threading.Event()
    contender_acquired = threading.Event()
    failures: list[BaseException] = []

    def paused(callback):
        def wrapped(*args, **kwargs):
            entered.set()
            assert release.wait(5.0)
            return callback(*args, **kwargs)

        return wrapped

    callbacks = {
        "coverage": {
            "record_coverage": paused(system.record_coverage),
        },
        "rag": {
            "record_rag_document": paused(system.rag.add_for_owner),
        },
        "certification": {
            "record_certification": paused(system.rows.record_current),
        },
    }
    finalizer = system.finalizer(**callbacks[boundary])

    def finalize() -> None:
        try:
            finalizer.record_current(
                owner_user_id=OWNER,
                m_row=ROW,
                anchor_ref=ASSET_REF,
            )
        except BaseException as exc:  # noqa: BLE001 - thread evidence is asserted below.
            failures.append(exc)

    def contend() -> None:
        try:
            with acquire_goal_proof_head_lock(system.entrypoints.path):
                contender_acquired.set()
        except BaseException as exc:  # noqa: BLE001 - thread evidence is asserted below.
            failures.append(exc)

    finalizer_thread = threading.Thread(target=finalize, daemon=True)
    finalizer_thread.start()
    assert entered.wait(5.0)
    contender_thread = threading.Thread(target=contend, daemon=True)
    contender_thread.start()
    assert not contender_acquired.wait(0.2)

    release.set()
    finalizer_thread.join(5.0)
    contender_thread.join(5.0)
    assert not finalizer_thread.is_alive()
    assert not contender_thread.is_alive()
    assert failures == []
    assert contender_acquired.is_set()


def test_m18_derived_coverage_propagates_only_exact_policy_selected_rdp() -> None:
    business = GoalEntrypointCoverageRecord(
        coverage_ref="goal_entrypoint_coverage:business:m18",
        entry_source="api",
        entrypoint_ref="api:platform.m18",
        goal_sections=("§17",),
        qro_refs=("qro:m18",),
        research_graph_command_refs=("rgcmd:m18",),
        compiler_ir_refs=("compiler_ir:m18",),
        compiler_pass_refs=("compiler_pass:m18",),
        evidence_refs=("evidence:m18",),
        validation_refs=("goal_validation_receipt:m18",),
        permission_refs=("permission:m18",),
        replay_refs=("replay:m18",),
        canonical_command_refs=("rgcmd:m18",),
        lifecycle_refs=("rdp_business",),
        recorded_by=OWNER,
    )
    selected_package = "rdp_selected_m18"
    resolution = PlatformSourceLineagePolicyResolution(
        m_row="M18",
        anchor_ref="consistency_check:m18",
        qro_ref="qro:m18",
        business_entry_source="api",
        business_entrypoint_ref="api:platform.m18",
        lifecycle_ref=selected_package,
        math_spine_ref="math_spine:m18",
        specific_refs=(),
        primary_rag_asset_ref=selected_package,
        row_policy_metadata=(("rdp_package_ref", selected_package),),
    )

    coverage = PlatformSourceLineageFinalizer._derived_coverage(
        owner=OWNER,
        resolution=resolution,
        business=business,
    )
    assert coverage.rdp_refs == (selected_package,)
    assert coverage.lifecycle_refs == (selected_package,)

    non_m18 = PlatformSourceLineageFinalizer._derived_coverage(
        owner=OWNER,
        resolution=replace(
            resolution,
            m_row="M21",
            lifecycle_ref="governed_asset:m21",
            row_policy_metadata=(("rdp_package_ref", "rdp_must_not_leak"),),
        ),
        business=business,
    )
    assert non_m18.rdp_refs == ()
    explicit_non_m18 = PlatformSourceLineageFinalizer._derived_coverage(
        owner=OWNER,
        resolution=replace(
            resolution,
            m_row="M21",
            lifecycle_ref="governed_asset:m21",
            row_policy_metadata=(),
        ),
        business=replace(business, rdp_refs=("rdp_explicit_business",)),
    )
    assert explicit_non_m18.rdp_refs == ("rdp_explicit_business",)

    with pytest.raises(
        PlatformSourceLineageCoreError,
        match="stale or recombined",
    ):
        PlatformSourceLineageFinalizer._derived_coverage(
            owner=OWNER,
            resolution=replace(
                resolution,
                row_policy_metadata=(("rdp_package_ref", "rdp_other"),),
            ),
            business=business,
        )


def test_row_metadata_only_projects_explicit_m4_formula_hash_allowlist(
    tmp_path: Path,
) -> None:
    system = _build_system(tmp_path)
    formula_hash = content_hash({"formula": "returns_5d"})
    resolution = PlatformSourceLineagePolicyResolution(
        m_row="M4-M5",
        anchor_ref="factor:returns_5d",
        qro_ref=system.business.qro_refs[0],
        business_entry_source=EntrySource.API.value,
        business_entrypoint_ref=ENTRYPOINT,
        lifecycle_ref=ASSET_REF,
        math_spine_ref=system.policy.resolve(
            owner_user_id=OWNER,
            m_row=ROW,
            anchor_ref=ASSET_REF,
        ).math_spine_ref,
        specific_refs=(
            PlatformSpecificRef("factor_ref", "factor:returns_5d"),
            PlatformSpecificRef("label_ref", "label:forward_returns_1d"),
        ),
        primary_rag_asset_ref="factor:returns_5d",
        row_policy_metadata=(
            ("formula_hash", formula_hash),
            ("diagnostic_note", "server-owned factor policy"),
        ),
    )

    document = PlatformSourceLineageFinalizer._rag_document(
        owner=OWNER,
        row="M4-M5",
        resolution=resolution,
        coverage=system.business,
    )

    assert document.metadata["formula_hash"] == formula_hash
    assert "diagnostic_note" not in {
        key for key in document.metadata if key != "row_policy"
    }
    assert document.metadata["row_policy"] == {
        "formula_hash": formula_hash,
        "diagnostic_note": "server-owned factor policy",
    }
    assert set(document.metadata).issuperset(
        {"platform_capability", "row_policy", "formula_hash"}
    )

    with pytest.raises(
        PlatformSourceLineageCoreError,
        match="lowercase 16-hex",
    ):
        PlatformSourceLineageFinalizer._rag_document(
            owner=OWNER,
            row="M4-M5",
            resolution=replace(
                resolution,
                row_policy_metadata=(("formula_hash", "not-a-content-hash"),),
            ),
            coverage=system.business,
        )


def test_exact_non_section14_business_coverage_rejects_ambiguity_before_writes(
    tmp_path: Path,
) -> None:
    system = _build_system(tmp_path)
    second = _alternate_business_coverage(system, section="§2")
    system.record_coverage(second)

    with pytest.raises(
        PlatformSourceLineageCoreError,
        match="exactly one non-§14 business coverage",
    ):
        system.finalizer().record_current(
            owner_user_id=OWNER,
            m_row=ROW,
            anchor_ref=ASSET_REF,
        )

    assert len(system.entrypoints.records(owner=OWNER)) == 2
    assert len(system.rag.owned_documents(owner_user_id=OWNER)) == 1
    assert system.rows.current_certifications(owner_user_id=OWNER) == ()


def test_fresh_disk_view_rejects_business_coverage_appended_by_second_instance(
    tmp_path: Path,
) -> None:
    system = _build_system(tmp_path)
    external = _strict_entrypoints(
        system.root,
        graph=system.graph,
        lifecycle=system.lifecycle,
        rag=system.rag,
        spine=system.spine,
        compiler=system.compiler,
        receipts=system.receipts,
        proof_ledger=system.proof_ledger,
    )
    second = _alternate_business_coverage(system, section="§2")
    system.record_coverage(second)
    current_records = system.entrypoints.records(owner=OWNER)
    current_by_ref = {record.coverage_ref: record for record in current_records}
    assert current_by_ref == {
        system.business.coverage_ref: system.business,
        second.coverage_ref: second,
    }

    with pytest.raises(
        PlatformSourceLineageCoreError,
        match="exactly one non-§14 business coverage",
    ):
        system.finalizer().record_current(
            owner_user_id=OWNER,
            m_row=ROW,
            anchor_ref=ASSET_REF,
        )

    fresh = _strict_entrypoints(
        system.root,
        graph=system.graph,
        lifecycle=system.lifecycle,
        rag=system.rag,
        spine=system.spine,
        compiler=system.compiler,
        receipts=system.receipts,
        proof_ledger=system.proof_ledger,
    )
    assert {
        record.coverage_ref: record for record in fresh.records(owner=OWNER)
    } == current_by_ref
    assert len(system.rag.owned_documents(owner_user_id=OWNER)) == 1
    assert system.rows.current_certifications(owner_user_id=OWNER) == ()


def test_policy_double_resolution_owner_isolation_and_recombination_fail_closed(
    tmp_path: Path,
) -> None:
    system = _build_system(tmp_path)
    drift = _M21AnchorPolicy(
        graph=system.graph,
        lifecycle=system.lifecycle,
        spine=system.spine,
        upstream=system.policy._upstream,
        drift=True,
    )
    with pytest.raises(
        PlatformSourceLineageCoreError,
        match="policy changed during resolution",
    ):
        system.finalizer(policy=drift).record_current(
            owner_user_id=OWNER,
            m_row=ROW,
            anchor_ref=ASSET_REF,
        )

    with pytest.raises(PlatformSourceLineageCoreError, match="policy resolution failed"):
        system.finalizer().record_current(
            owner_user_id=OTHER_OWNER,
            m_row=ROW,
            anchor_ref=ASSET_REF,
        )

    other = system.lifecycle.record_governed_asset(
        GovernedAssetRecord(
            asset_ref="governed_asset:strategy_template:other",
            asset_type="StrategyBook",
            category=AssetCategory.TEMPLATE,
            lifecycle_state=LifecycleState.SPECIFIED,
            evidence_refs=(EVIDENCE_REF,),
            validation_plan_ref="validation_plan:template_labels:other",
            promotion_history=(),
            display_label="OTHER TEMPLATE - candidate context only",
            mock_label_ref="mock_label:strategy_template:other",
            asset_category_ref="asset_category:strategy_template:other",
        ),
        owner_user_id=OWNER,
    )
    recombined = _M21AnchorPolicy(
        graph=system.graph,
        lifecycle=system.lifecycle,
        spine=system.spine,
        upstream=system.policy._upstream,
        recombined_asset_ref=other.asset_ref,
    )
    with pytest.raises(
        PlatformSourceLineageCoreError,
        match="specific refs recombine",
    ):
        system.finalizer(policy=recombined).record_current(
            owner_user_id=OWNER,
            m_row=ROW,
            anchor_ref=ASSET_REF,
        )

    assert len(system.entrypoints.records(owner=OWNER)) == 1
    assert len(system.rag.owned_documents(owner_user_id=OWNER)) == 1
    assert system.rows.current_certifications(owner_user_id=OWNER) == ()


@pytest.mark.parametrize(
    ("boundary", "expected"),
    (
        ("coverage", (False, False, False)),
        ("rag", (True, False, False)),
        ("certification", (True, True, False)),
        ("certification_after_persist", (True, True, True)),
    ),
)
def test_partial_commit_flags_and_retry_are_exactly_idempotent(
    tmp_path: Path,
    boundary: str,
    expected: tuple[bool, bool, bool],
) -> None:
    system = _build_system(tmp_path)

    def fail_coverage(_record: GoalEntrypointCoverageRecord):
        raise OSError("simulated coverage ledger failure")

    def fail_rag(_document: AssetRAGDocument, **_kwargs):
        raise OSError("simulated RAG ledger failure")

    def fail_certification(**_kwargs):
        raise OSError("simulated row-source ledger failure")

    def persist_then_fail_certification(**kwargs):
        system.rows.record_current(**kwargs)
        raise OSError("simulated acknowledgement loss after row-source persistence")

    callbacks: dict[str, dict[str, Any]] = {
        "coverage": {"record_coverage": fail_coverage},
        "rag": {"record_rag_document": fail_rag},
        "certification": {"record_certification": fail_certification},
        "certification_after_persist": {
            "record_certification": persist_then_fail_certification
        },
    }
    with pytest.raises(PlatformSourceLineageCoreCommitError) as raised:
        system.finalizer(**callbacks[boundary]).record_current(
            owner_user_id=OWNER,
            m_row=ROW,
            anchor_ref=ASSET_REF,
        )

    observed = (
        raised.value.coverage_persisted,
        raised.value.rag_persisted,
        raised.value.row_source_persisted,
    )
    assert observed == expected

    retry = _reload(system)
    result = retry.finalizer().record_current(
        owner_user_id=OWNER,
        m_row=ROW,
        anchor_ref=ASSET_REF,
    )
    assert result.coverage.coverage_ref
    assert result.rag_document.document_id
    assert result.certification.certification_ref
    assert len(retry.entrypoints.records(owner=OWNER)) == 2
    assert len(retry.rag.owned_documents(owner_user_id=OWNER)) == 2
    assert len(retry.rows.current_certifications(owner_user_id=OWNER)) == 1
    assert len(retry.entrypoints.canonical_records(owner=OWNER)) == 2
    assert retry.proof_ledger.verify().ok
    assert len(_events(retry.row_path)) == 1


@pytest.mark.parametrize(
    ("boundary", "expected"),
    (
        ("coverage", (True, False, False)),
        ("rag", (True, True, False)),
        ("certification", (True, True, True)),
    ),
)
def test_cross_instance_ack_loss_reports_fresh_durable_commit_flags(
    tmp_path: Path,
    boundary: str,
    expected: tuple[bool, bool, bool],
) -> None:
    system = _build_system(tmp_path)
    external_entrypoints = _strict_entrypoints(
        system.root,
        graph=system.graph,
        lifecycle=system.lifecycle,
        rag=system.rag,
        spine=system.spine,
        compiler=system.compiler,
        receipts=system.receipts,
        proof_ledger=system.proof_ledger,
    )
    external_rag = PersistentResearchAssetRAGIndex(system.rag_path)

    def external_coverage_then_fail(record: GoalEntrypointCoverageRecord):
        system.record_coverage(record)
        raise OSError("simulated cross-instance coverage acknowledgement loss")

    def external_rag_then_fail(document: AssetRAGDocument, **kwargs):
        external_rag.add_for_owner(document, **kwargs)
        raise OSError("simulated cross-instance RAG acknowledgement loss")

    def external_certification_then_fail(**kwargs):
        fresh_entrypoints = _strict_entrypoints(
            system.root,
            graph=system.graph,
            lifecycle=system.lifecycle,
            rag=system.rag,
            spine=system.spine,
            compiler=system.compiler,
            receipts=system.receipts,
            proof_ledger=system.proof_ledger,
        )
        fresh_rag = PersistentResearchAssetRAGIndex(system.rag_path)
        external_rows = PersistentPlatformRowSourceRegistry(
            system.row_path,
            entrypoint_registry=fresh_entrypoints,
            rag_index=fresh_rag,
            source_resolver=system.typed,
        )
        external_rows.record_current(**kwargs)
        raise OSError("simulated cross-instance row acknowledgement loss")

    callbacks = {
        "coverage": {"record_coverage": external_coverage_then_fail},
        "rag": {"record_rag_document": external_rag_then_fail},
        "certification": {
            "record_certification": external_certification_then_fail
        },
    }
    with pytest.raises(PlatformSourceLineageCoreCommitError) as raised:
        system.finalizer(**callbacks[boundary]).record_current(
            owner_user_id=OWNER,
            m_row=ROW,
            anchor_ref=ASSET_REF,
        )

    observed = (
        raised.value.coverage_persisted,
        raised.value.rag_persisted,
        raised.value.row_source_persisted,
    )
    assert observed == expected

    retry = _reload(system)
    result = retry.finalizer().record_current(
        owner_user_id=OWNER,
        m_row=ROW,
        anchor_ref=ASSET_REF,
    )
    assert result.coverage.coverage_ref
    assert result.rag_document.document_id
    assert result.certification.certification_ref
    assert len(retry.entrypoints.records(owner=OWNER)) == 2
    assert len(retry.rag.owned_documents(owner_user_id=OWNER)) == 2
    assert len(retry.rows.current_certifications(owner_user_id=OWNER)) == 1
