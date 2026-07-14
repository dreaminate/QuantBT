from __future__ import annotations

from dataclasses import replace
from inspect import signature
from types import SimpleNamespace
from typing import Any

import pytest

from app.ide.service import StrategyFile
from app.lineage.ids import content_hash
from app.research_os.asset_lifecycle import (
    AssetCategory,
    GovernedAssetRecord,
    LifecycleState,
)
from app.research_os.compiler import (
    CompilerIRRecord,
    CompilerPassRecord,
    PersistentCompilerIRStore,
)
from app.research_os.goal_coverage import (
    GoalEntrypointCoverageRecord,
    PersistentGoalEntrypointCoverageRegistry,
    goal_entrypoint_coverage_identity,
)
from app.research_os.goal_validation_receipts import (
    GoalValidationOutcome,
    GoalValidationReceipt,
)
from app.research_os.platform_business_history_m16_m21 import (
    ENTRYPOINT_REFS,
    M16BusinessHistorySubject,
    M19BusinessHistorySubject,
    M21BusinessHistorySubject,
    PlatformBusinessHistoryM16M21CommitError,
    PlatformBusinessHistoryM16M21Context,
    PlatformBusinessHistoryM16M21Error,
    PlatformBusinessHistoryM16M21Recorder,
    m21_governed_template_snapshot_hash,
    m21_ide_strategy_snapshot_hash,
    prepare_platform_business_history_m16_m21,
    record_platform_business_history_m16_m21,
)
from app.research_os.qro_spine_binding import prepare_current_qro_spine_binding
from app.research_os.spine import (
    ActorSource,
    EntrySource,
    QROType,
    PersistentResearchGraphStore,
    ResearchGraphCommand,
    ResearchGraphStore,
)
from app.research_os.teaching_assets import (
    TeachingAssetBundle,
    TeachingEvidenceRecord,
    TutorialAssetRecord,
    WeaknessDisclosureRecord,
)
from app.sharing.service import (
    SharedStrategy,
    shared_strategy_asset_ref,
    shared_strategy_permission,
    shared_strategy_source,
    shared_strategy_status,
)


OWNER = "owner:platform-business-history:m16-m21"


class _CompilerStore:
    def __init__(self) -> None:
        self.ir_rows: dict[str, CompilerIRRecord] = {}
        self.pass_rows: dict[str, CompilerPassRecord] = {}

    def put_ir(self, record: CompilerIRRecord) -> None:
        existing = self.ir_rows.get(record.ir_ref)
        if existing is not None and existing != record:
            raise ValueError("compiler IR identity collision")
        self.ir_rows[record.ir_ref] = record

    def put_pass(self, record: CompilerPassRecord) -> None:
        existing = self.pass_rows.get(record.pass_ref)
        if existing is not None and existing != record:
            raise ValueError("compiler pass identity collision")
        self.pass_rows[record.pass_ref] = record

    def ir(self, ref: str, *, owner: str | None = None) -> Any:
        record = self.ir_rows[ref]
        if owner is not None and record.owner != owner:
            raise KeyError(ref)
        return record

    def compiler_pass(self, ref: str, *, owner: str | None = None) -> Any:
        record = self.pass_rows[ref]
        if owner is not None and record.actor != owner:
            raise KeyError(ref)
        return record

    def irs(self, *, owner: str | None = None) -> list[Any]:
        return [
            record
            for record in self.ir_rows.values()
            if owner is None or record.owner == owner
        ]

    def passes(self, *, owner: str | None = None) -> list[Any]:
        return [
            record
            for record in self.pass_rows.values()
            if owner is None or record.actor == owner
        ]


class _CoverageRegistry:
    def __init__(self) -> None:
        self.rows: dict[str, GoalEntrypointCoverageRecord] = {}

    def put(self, record: GoalEntrypointCoverageRecord) -> None:
        existing = self.rows.get(record.coverage_ref)
        if existing is not None and existing != record:
            raise ValueError("coverage identity collision")
        self.rows[record.coverage_ref] = record

    def records(self, *, owner: str | None = None) -> list[Any]:
        return [
            record
            for record in self.rows.values()
            if owner is None or record.recorded_by == owner
        ]

    def coverage(self, ref: str, *, owner: str | None = None) -> Any:
        record = self.rows[ref]
        if owner is not None and record.recorded_by != owner:
            raise KeyError(ref)
        return record

    def validate_real_backing(self, record: Any) -> Any:
        return SimpleNamespace(
            accepted=self.rows.get(record.coverage_ref) == record,
            violations=(),
        )


class _CompilerHarness:
    def __init__(self) -> None:
        self.store = _CompilerStore()
        self.coverage = _CoverageRegistry()
        self.calls = 0
        self.fail_after: str | None = None

    def compile(self, qro, command, plan):
        self.calls += 1
        canonical = tuple(
            dict.fromkeys(
                (*plan.canonical_command_refs, f"entrypoint:{plan.entrypoint_ref}")
            )
        )
        provisional_receipt = GoalValidationReceipt(
            validation_ref="",
            owner_user_id=plan.owner_user_id,
            subject_qro_refs=(qro.qro_id,),
            graph_command_refs=(command.command_id,),
            validator_identifiers=(
                "runtime_validator:platform_business_history_typed_bundle_v1",
                *(f"domain_validation_ref:{ref}" for ref in plan.validation_refs),
            ),
            test_identifiers=(
                "runtime_check:business_history_qro_graph_compiler_exact_match",
            ),
            outcome=GoalValidationOutcome.PASSED,
            evidence_refs=plan.evidence_refs,
            evidence_digests=tuple(
                "sha16:"
                + content_hash(
                    {
                        "evidence_ref": ref,
                        "qro_ref": qro.qro_id,
                        "command_ref": command.command_id,
                    }
                )
                for ref in plan.evidence_refs
            ),
            residuals=(),
        )
        receipt = replace(
            provisional_receipt,
            validation_ref=provisional_receipt.canonical_validation_ref,
        )
        trusted_validation_refs = (receipt.validation_ref,)
        ir_ref = "compiler_ir:" + content_hash(
            {
                "qro_ref": qro.qro_id,
                "command_ref": command.command_id,
                "entrypoint_ref": plan.entrypoint_ref,
            }
        )
        pass_ref = "compiler_pass:" + content_hash(
            {"ir_ref": ir_ref, "entrypoint_ref": plan.entrypoint_ref}
        )
        compiler_ir = CompilerIRRecord(
            ir_ref=ir_ref,
            source_qro_refs=(qro.qro_id,),
            graph_command_refs=(command.command_id,),
            canonical_command_refs=canonical,
            node_refs=plan.node_refs,
            edge_refs=(),
            artifact_refs=(),
            theory_binding_refs=plan.theory_binding_refs,
            consistency_check_refs=plan.consistency_check_refs,
            evidence_refs=plan.evidence_refs,
            validation_refs=trusted_validation_refs,
            permission_ref=plan.permission_ref,
            deterministic_run_plan_ref=plan.deterministic_run_plan_ref,
            rollback_ref=plan.rollback_ref,
            environment_lock_ref=plan.environment_lock_ref,
            mathematical_spine_chain_refs=plan.mathematical_spine_chain_refs,
            owner=plan.owner_user_id,
        )
        self.store.put_ir(compiler_ir)
        if self.fail_after == "ir":
            raise OSError("compiler failed after IR append")
        compiler_pass = CompilerPassRecord(
            pass_ref=pass_ref,
            pass_name=plan.pass_name,
            input_ir_refs=(),
            output_ir_ref=ir_ref,
            input_qro_refs=(qro.qro_id,),
            graph_command_refs=(command.command_id,),
            canonical_command_refs=canonical,
            actor=plan.owner_user_id,
            actor_source=ActorSource.USER_MANUAL,
            entry_source=EntrySource.API,
            permission_ref=plan.permission_ref,
            tool_record_refs=plan.tool_record_refs,
            evidence_refs=plan.evidence_refs,
            validation_refs=trusted_validation_refs,
            deterministic_run_plan_ref=plan.deterministic_run_plan_ref,
            rollback_ref=plan.rollback_ref,
        )
        self.store.put_pass(compiler_pass)
        if self.fail_after == "pass":
            raise OSError("compiler failed after pass append")
        coverage_ref = goal_entrypoint_coverage_identity(
            entry_source=EntrySource.API,
            entrypoint_ref=plan.entrypoint_ref,
            goal_sections=plan.goal_sections,
            qro_refs=(qro.qro_id,),
            research_graph_command_refs=(command.command_id,),
            compiler_ir_refs=(ir_ref,),
            compiler_pass_refs=(pass_ref,),
        )
        coverage = GoalEntrypointCoverageRecord(
            coverage_ref=coverage_ref,
            entry_source=EntrySource.API,
            entrypoint_ref=plan.entrypoint_ref,
            goal_sections=plan.goal_sections,
            qro_refs=(qro.qro_id,),
            research_graph_command_refs=(command.command_id,),
            compiler_ir_refs=(ir_ref,),
            compiler_pass_refs=(pass_ref,),
            evidence_refs=plan.evidence_refs,
            validation_refs=trusted_validation_refs,
            permission_refs=(plan.permission_ref,),
            replay_refs=(
                f"replay:research_graph:{command.command_id}",
                f"replay:compiler_ir:{ir_ref}",
                f"replay:compiler_pass:{pass_ref}",
            ),
            canonical_command_refs=canonical,
            lifecycle_refs=plan.lifecycle_refs,
            rdp_refs=plan.rdp_refs,
            recorded_by=plan.owner_user_id,
        )
        self.coverage.put(coverage)
        return {
            "compiler_ir_ref": ir_ref,
            "compiler_pass_ref": pass_ref,
            "entrypoint_coverage_ref": coverage_ref,
        }


def _governed_asset(
    *,
    asset_ref: str,
    asset_type: str,
    category: AssetCategory,
    evidence_refs: tuple[str, ...],
    display_label: str = "",
    mock_label_ref: str | None = None,
    asset_category_ref: str | None = None,
) -> GovernedAssetRecord:
    return GovernedAssetRecord(
        asset_ref=asset_ref,
        asset_type=asset_type,
        category=category,
        lifecycle_state=LifecycleState.LINKED,
        evidence_refs=evidence_refs,
        validation_plan_ref="validation_plan:business-history",
        promotion_history=(),
        display_label=display_label,
        mock_label_ref=mock_label_ref,
        asset_category_ref=asset_category_ref,
    )


def _m16_subject() -> tuple[str, M16BusinessHistorySubject]:
    strategy = SharedStrategy(
        share_id="share-m16-history",
        run_id="run-m16-history",
        author_id=OWNER,
        title="M16 shared strategy",
        asset_class="equity_cn",
        public=True,
        created_at_utc="2026-07-13T00:00:00+00:00",
    )
    anchor = shared_strategy_asset_ref(strategy)
    permission = shared_strategy_permission(strategy)
    source = shared_strategy_source(strategy)
    status = shared_strategy_status(strategy)
    lifecycle = _governed_asset(
        asset_ref=anchor,
        asset_type="SharedStrategy",
        category=AssetCategory.USER_ASSET,
        evidence_refs=(
            permission.permission_ref,
            source.source_ref,
            status.status_ref,
        ),
    )
    return anchor, M16BusinessHistorySubject(
        strategy=strategy,
        permission=permission,
        source=source,
        status=status,
        governed_asset=lifecycle,
    )


def _m19_subject() -> tuple[str, M19BusinessHistorySubject]:
    governed_ref = "governed_asset:teaching:m19-history"
    tutorial = TutorialAssetRecord(
        tutorial_asset_ref="",
        owner_user_id=OWNER,
        governed_asset_ref=governed_ref,
        category="tutorial",
        title="M19 evidence-first tutorial",
    )
    tutorial = replace(tutorial, tutorial_asset_ref=tutorial.canonical_ref)
    weakness = WeaknessDisclosureRecord(
        weakness_disclosure_ref="",
        owner_user_id=OWNER,
        tutorial_asset_ref=tutorial.tutorial_asset_ref,
        weakness_refs=("weakness:m19:small-sample",),
        visible_by_default=True,
    )
    weakness = replace(
        weakness,
        weakness_disclosure_ref=weakness.canonical_ref,
    )
    evidence = TeachingEvidenceRecord(
        teaching_evidence_ref="",
        owner_user_id=OWNER,
        tutorial_asset_ref=tutorial.tutorial_asset_ref,
        weakness_disclosure_ref=weakness.weakness_disclosure_ref,
        evidence_refs=("evidence:m19:tutorial",),
    )
    evidence = replace(evidence, teaching_evidence_ref=evidence.canonical_ref)
    lifecycle = _governed_asset(
        asset_ref=governed_ref,
        asset_type="TeachingAsset",
        category=AssetCategory.TUTORIAL,
        evidence_refs=("evidence:m19:lifecycle",),
    )
    return tutorial.tutorial_asset_ref, M19BusinessHistorySubject(
        bundle=TeachingAssetBundle(
            tutorial=tutorial,
            weakness=weakness,
            evidence=evidence,
        ),
        governed_asset=lifecycle,
    )


def _m21_subject(
    *,
    strategy_id: str = "strategy-m21-history",
    name: str = "m21_template_fork",
) -> tuple[str, M21BusinessHistorySubject]:
    governed_asset_ref = "governed_asset:template:m21-history"
    lifecycle = _governed_asset(
        asset_ref=governed_asset_ref,
        asset_type="StrategyTemplate",
        category=AssetCategory.TEMPLATE,
        evidence_refs=("evidence:m21:template",),
        display_label="TEMPLATE - candidate context only",
        mock_label_ref="mock_label:template:m21-history",
        asset_category_ref="asset_category:equity_cn:m21-history",
    )
    strategy = StrategyFile(
        strategy_id=strategy_id,
        owner_username="owner_username",
        name=name,
        code="def generate_signal(ctx):\n    return 0\n",
        asset_class="equity_cn",
        description="forked from a governed template",
        updated_at_utc="2026-07-13T00:00:00Z",
        market_data_use_validation_refs=[],
    )
    return f"ide_strategy:{strategy.strategy_id}", M21BusinessHistorySubject(
        governed_asset=lifecycle,
        ide_strategy=strategy,
    )


def _subject(row: str):
    return {
        "M16": _m16_subject,
        "M19": _m19_subject,
        "M21": _m21_subject,
    }[row]()


def _system(row: str):
    anchor, subject = _subject(row)
    graph = ResearchGraphStore()
    harness = _CompilerHarness()
    context = PlatformBusinessHistoryM16M21Context(
        research_graph_store=graph,
        compiler_store=harness.store,
        entrypoint_registry=harness.coverage,
        apply_graph=graph.apply,
        compile_history=harness.compile,
    )
    return SimpleNamespace(
        row=row,
        anchor=anchor,
        subject=subject,
        graph=graph,
        harness=harness,
        context=context,
    )


def test_public_operations_do_not_accept_caller_supplied_lineage_refs() -> None:
    assert tuple(signature(prepare_platform_business_history_m16_m21).parameters) == (
        "owner_user_id",
        "row",
        "anchor_ref",
        "subject",
    )
    assert tuple(signature(record_platform_business_history_m16_m21).parameters) == (
        "context",
        "owner_user_id",
        "row",
        "anchor_ref",
        "subject",
    )


@pytest.mark.parametrize("row", ("M16", "M19", "M21"))
def test_plan_is_deterministic_mathless_non_section_14_and_policy_compatible(
    row: str,
) -> None:
    anchor, subject = _subject(row)

    first = prepare_platform_business_history_m16_m21(
        owner_user_id=OWNER,
        row=row,
        anchor_ref=anchor,
        subject=subject,
    )
    second = prepare_platform_business_history_m16_m21(
        owner_user_id=OWNER,
        row=row,
        anchor_ref=anchor,
        subject=subject,
    )

    assert first == second
    assert first.entrypoint_ref == ENTRYPOINT_REFS[row]
    assert first.qro.mathematical_refs == ()
    assert first.compile_plan.mathematical_spine_chain_refs == ()
    assert first.compile_plan.goal_sections
    assert "§14" not in first.compile_plan.goal_sections
    assert first.command.payload == {"qro": first.qro}
    assert first.command.tool_record_refs == (ENTRYPOINT_REFS[row],)
    assert first.qro.input_contract["entry_source"] == "api"
    if row == "M16":
        assert first.qro.qro_type == QROType.STRATEGY_BOOK
        assert set(first.qro.input_contract) == {
            "entry_source",
            "shared_asset_ref",
            "permission_ref",
            "source_ref",
        }
        assert "status_ref" in first.qro.output_contract
    elif row == "M19":
        assert first.qro.qro_type == QROType.DOCUMENT_ARTIFACT
        assert {
            "tutorial_asset_ref",
            "weakness_disclosure_ref",
            "teaching_evidence_ref",
            "governed_asset_ref",
        }.issubset(first.qro.input_contract)
    else:
        assert first.qro.qro_type == QROType.STRATEGY_BOOK
        assert first.qro.input_contract["governed_asset_ref"] == (
            subject.governed_asset.asset_ref
        )
        assert first.qro.output_contract["ide_strategy_ref"] == anchor
        assert first.compile_plan.lifecycle_refs == (
            subject.governed_asset.asset_ref,
        )
        assert set(first.qro.output_contract) == {
            "ide_strategy_ref",
            "ide_strategy_snapshot_hash",
            "governed_template_snapshot_hash",
            "mock_label_ref",
            "asset_category_ref",
            "status",
        }
        assert first.qro.output_contract["ide_strategy_snapshot_hash"] == (
            m21_ide_strategy_snapshot_hash(subject.ide_strategy)
        )
        assert first.qro.output_contract[
            "governed_template_snapshot_hash"
        ] == m21_governed_template_snapshot_hash(subject.governed_asset)


@pytest.mark.parametrize("mutation", ("anchor", "strategy_id", "template"))
def test_m21_rejects_wrong_fork_anchor_or_recombined_template_before_any_write(
    mutation: str,
) -> None:
    system = _system("M21")
    anchor = system.anchor
    subject = system.subject
    if mutation == "anchor":
        anchor = "ide_strategy:strategy-m21-same-owner-unrelated"
    elif mutation == "strategy_id":
        subject = replace(
            subject,
            ide_strategy=replace(
                subject.ide_strategy,
                strategy_id="strategy-m21-same-owner-unrelated",
            ),
        )
    else:
        subject = replace(
            subject,
            governed_asset=replace(
                subject.governed_asset,
                asset_category_ref="asset_category:crypto_perp:m21-recombined",
            ),
        )

    with pytest.raises(PlatformBusinessHistoryM16M21Error):
        record_platform_business_history_m16_m21(
            context=system.context,
            owner_user_id=OWNER,
            row="M21",
            anchor_ref=anchor,
            subject=subject,
        )

    assert system.graph.commands() == []
    assert system.harness.store.irs(owner=OWNER) == []
    assert system.harness.store.passes(owner=OWNER) == []
    assert system.harness.coverage.records(owner=OWNER) == []
    assert system.harness.calls == 0


@pytest.mark.parametrize("row", ("M16", "M19", "M21"))
def test_records_exact_history_and_reuses_it_idempotently(row: str) -> None:
    system = _system(row)
    recorder = PlatformBusinessHistoryM16M21Recorder(system.context)

    first = recorder.record(
        owner_user_id=OWNER,
        row=row,
        anchor_ref=system.anchor,
        subject=system.subject,
    )
    second = recorder.record(
        owner_user_id=OWNER,
        row=row,
        anchor_ref=system.anchor,
        subject=system.subject,
    )

    assert first.graph_command_created is True
    assert second == replace(first, graph_command_created=False)
    assert len(system.graph.commands()) == 1
    assert system.harness.calls == 1
    assert system.graph.qro(first.qro_ref).mathematical_refs == ()
    coverage = system.harness.coverage.coverage(
        first.entrypoint_coverage_ref,
        owner=OWNER,
    )
    compiler_ir = system.harness.store.ir(first.compiler_ir_ref, owner=OWNER)
    compiler_pass = system.harness.store.compiler_pass(
        first.compiler_pass_ref,
        owner=OWNER,
    )
    assert len(compiler_ir.validation_refs) == 1
    assert compiler_ir.validation_refs[0].startswith("goal_validation_receipt:")
    assert compiler_pass.validation_refs == compiler_ir.validation_refs
    assert coverage.validation_refs == compiler_ir.validation_refs
    assert coverage.entrypoint_ref == ENTRYPOINT_REFS[row]
    assert coverage.goal_sections
    assert "§14" not in coverage.goal_sections


@pytest.mark.parametrize("row", ("M16", "M19", "M21"))
def test_history_head_is_accepted_by_the_shared_spine_binding_preflight(
    row: str,
) -> None:
    system = _system(row)
    result = record_platform_business_history_m16_m21(
        context=system.context,
        owner_user_id=OWNER,
        row=row,
        anchor_ref=system.anchor,
        subject=system.subject,
    )
    chain = SimpleNamespace(
        chain_ref=f"math_spine_chain:{row.lower()}:history",
        recorded_by=OWNER,
    )

    binding = prepare_current_qro_spine_binding(
        research_graph_store=system.graph,
        qro_ref=result.qro_ref,
        owner_user_id=OWNER,
        verified_chain=chain,
    )

    assert binding.already_bound is False
    assert binding.current_qro.mathematical_refs == ()
    assert binding.bound_qro.qro_id == binding.current_qro.qro_id
    assert binding.bound_qro.mathematical_refs == (chain.chain_ref,)


@pytest.mark.parametrize("row", ("M16", "M19", "M21"))
def test_rejects_recombined_subject_before_any_write(row: str) -> None:
    system = _system(row)
    if row == "M16":
        subject = replace(
            system.subject,
            permission=replace(
                system.subject.permission,
                owner_user_id="owner:foreign",
            ),
        )
    elif row == "M19":
        subject = replace(
            system.subject,
            bundle=replace(
                system.subject.bundle,
                weakness=replace(
                    system.subject.bundle.weakness,
                    visible_by_default=False,
                ),
            ),
        )
    else:
        subject = replace(
            system.subject,
            ide_strategy=replace(
                system.subject.ide_strategy,
                asset_class="crypto_perp",
            ),
        )

    with pytest.raises(PlatformBusinessHistoryM16M21Error):
        record_platform_business_history_m16_m21(
            context=system.context,
            owner_user_id=OWNER,
            row=row,
            anchor_ref=system.anchor,
            subject=subject,
        )
    assert system.graph.commands() == []
    assert system.harness.calls == 0


def test_graph_append_then_ack_loss_preserves_exact_attempt_and_retry_reuses_it() -> None:
    system = _system("M16")
    failed = True

    def apply_then_raise(command):
        nonlocal failed
        ref = system.graph.apply(command)
        if failed:
            failed = False
            raise OSError("Graph durability acknowledgement unavailable")
        return ref

    context = replace(system.context, apply_graph=apply_then_raise)
    with pytest.raises(PlatformBusinessHistoryM16M21CommitError) as captured:
        record_platform_business_history_m16_m21(
            context=context,
            owner_user_id=OWNER,
            row="M16",
            anchor_ref=system.anchor,
            subject=system.subject,
        )

    error = captured.value
    assert error.phase == "research_graph"
    assert error.graph_history_current is True
    assert error.graph_command_created is True
    assert error.compiler_history_current is False
    assert len(system.graph.commands()) == 1
    assert system.harness.calls == 0
    preserved_command = system.graph.commands()[0]

    result = record_platform_business_history_m16_m21(
        context=system.context,
        owner_user_id=OWNER,
        row="M16",
        anchor_ref=system.anchor,
        subject=system.subject,
    )
    assert result.graph_command_created is False
    assert system.graph.commands() == [preserved_command]


def test_partial_compiler_state_is_reported_and_retry_reuses_graph() -> None:
    system = _system("M19")
    system.harness.fail_after = "ir"

    with pytest.raises(PlatformBusinessHistoryM16M21CommitError) as captured:
        record_platform_business_history_m16_m21(
            context=system.context,
            owner_user_id=OWNER,
            row="M19",
            anchor_ref=system.anchor,
            subject=system.subject,
        )

    error = captured.value
    assert error.phase == "compiler_coverage"
    assert error.graph_history_current is True
    assert error.graph_command_created is True
    assert error.compiler_history_current is False
    assert error.compiler_ir_ref.startswith("compiler_ir:")
    assert error.compiler_pass_ref == ""
    assert error.entrypoint_coverage_ref == ""

    system.harness.fail_after = None
    result = record_platform_business_history_m16_m21(
        context=system.context,
        owner_user_id=OWNER,
        row="M19",
        anchor_ref=system.anchor,
        subject=system.subject,
    )
    assert result.graph_command_created is False
    assert len(system.graph.commands()) == 1


def test_rejects_recombined_partial_compiler_ir_before_retry_writes() -> None:
    system = _system("M19")
    system.harness.fail_after = "ir"
    with pytest.raises(PlatformBusinessHistoryM16M21CommitError):
        record_platform_business_history_m16_m21(
            context=system.context,
            owner_user_id=OWNER,
            row="M19",
            anchor_ref=system.anchor,
            subject=system.subject,
        )
    ir_ref, compiler_ir = next(iter(system.harness.store.ir_rows.items()))
    system.harness.store.ir_rows[ir_ref] = replace(
        compiler_ir,
        evidence_refs=(*compiler_ir.evidence_refs, "evidence:foreign:recombined"),
    )
    system.harness.fail_after = None
    calls = system.harness.calls

    with pytest.raises(
        PlatformBusinessHistoryM16M21Error,
        match="compiler IR is stale, recombined",
    ):
        record_platform_business_history_m16_m21(
            context=system.context,
            owner_user_id=OWNER,
            row="M19",
            anchor_ref=system.anchor,
            subject=system.subject,
        )

    assert system.harness.calls == calls
    assert system.harness.store.pass_rows == {}
    assert system.harness.coverage.rows == {}


def test_compiler_ack_loss_reports_complete_persisted_history_and_retry_skips_compile() -> None:
    system = _system("M21")

    def compile_then_raise(qro, command, plan):
        system.harness.compile(qro, command, plan)
        raise OSError("compiler durability acknowledgement unavailable")

    context = replace(system.context, compile_history=compile_then_raise)
    with pytest.raises(PlatformBusinessHistoryM16M21CommitError) as captured:
        record_platform_business_history_m16_m21(
            context=context,
            owner_user_id=OWNER,
            row="M21",
            anchor_ref=system.anchor,
            subject=system.subject,
        )

    error = captured.value
    assert error.phase == "compiler_coverage"
    assert error.graph_history_current is True
    assert error.compiler_history_current is True
    assert error.compiler_ir_ref.startswith("compiler_ir:")
    assert error.compiler_pass_ref.startswith("compiler_pass:")
    assert error.entrypoint_coverage_ref.startswith("goal_entrypoint_coverage:")
    calls = system.harness.calls

    result = record_platform_business_history_m16_m21(
        context=system.context,
        owner_user_id=OWNER,
        row="M21",
        anchor_ref=system.anchor,
        subject=system.subject,
    )
    assert result.graph_command_created is False
    assert system.harness.calls == calls


def test_rejects_recombined_complete_coverage_even_when_registry_accepts_it() -> None:
    system = _system("M21")
    result = record_platform_business_history_m16_m21(
        context=system.context,
        owner_user_id=OWNER,
        row="M21",
        anchor_ref=system.anchor,
        subject=system.subject,
    )
    coverage = system.harness.coverage.rows[result.entrypoint_coverage_ref]
    system.harness.coverage.rows[result.entrypoint_coverage_ref] = replace(
        coverage,
        evidence_refs=(*coverage.evidence_refs, "evidence:foreign:recombined"),
    )
    calls = system.harness.calls

    with pytest.raises(
        PlatformBusinessHistoryM16M21Error,
        match="stale, different, or recombined",
    ):
        record_platform_business_history_m16_m21(
            context=system.context,
            owner_user_id=OWNER,
            row="M21",
            anchor_ref=system.anchor,
            subject=system.subject,
        )

    assert system.harness.calls == calls


def test_rejects_compiler_state_that_predates_the_graph_head() -> None:
    system = _system("M16")
    plan = prepare_platform_business_history_m16_m21(
        owner_user_id=OWNER,
        row="M16",
        anchor_ref=system.anchor,
        subject=system.subject,
    )
    system.harness.fail_after = "ir"
    with pytest.raises(OSError):
        system.harness.compile(plan.qro, plan.command, plan.compile_plan)
    system.harness.fail_after = None

    with pytest.raises(
        PlatformBusinessHistoryM16M21Error,
        match="before its business history Graph head",
    ):
        record_platform_business_history_m16_m21(
            context=system.context,
            owner_user_id=OWNER,
            row="M16",
            anchor_ref=system.anchor,
            subject=system.subject,
        )
    assert system.graph.commands() == []


def test_rejects_stale_different_qro_for_the_same_business_anchor() -> None:
    system = _system("M16")
    first = record_platform_business_history_m16_m21(
        context=system.context,
        owner_user_id=OWNER,
        row="M16",
        anchor_ref=system.anchor,
        subject=system.subject,
    )
    changed_strategy = replace(system.subject.strategy, public=False)
    changed_permission = shared_strategy_permission(changed_strategy)
    changed_source = shared_strategy_source(changed_strategy)
    changed_status = shared_strategy_status(changed_strategy)
    changed_subject = M16BusinessHistorySubject(
        strategy=changed_strategy,
        permission=changed_permission,
        source=changed_source,
        status=changed_status,
        governed_asset=replace(
            system.subject.governed_asset,
            evidence_refs=(
                changed_permission.permission_ref,
                changed_source.source_ref,
                changed_status.status_ref,
            ),
        ),
    )
    changed_plan = prepare_platform_business_history_m16_m21(
        owner_user_id=OWNER,
        row="M16",
        anchor_ref=system.anchor,
        subject=changed_subject,
    )
    assert changed_plan.qro.qro_id != first.qro_ref

    with pytest.raises(
        PlatformBusinessHistoryM16M21Error,
        match="stale, different, or recombined",
    ):
        record_platform_business_history_m16_m21(
            context=system.context,
            owner_user_id=OWNER,
            row="M16",
            anchor_ref=system.anchor,
            subject=changed_subject,
        )

    assert len(system.graph.commands()) == 1
    assert system.harness.calls == 1


def test_rejects_forged_m19_typed_record_identity_before_any_write() -> None:
    system = _system("M19")
    forged = replace(
        system.subject,
        bundle=replace(
            system.subject.bundle,
            tutorial=replace(
                system.subject.bundle.tutorial,
                title="changed without recomputing the canonical record ref",
            ),
        ),
    )

    with pytest.raises(
        PlatformBusinessHistoryM16M21Error,
        match="stale or recombined",
    ):
        record_platform_business_history_m16_m21(
            context=system.context,
            owner_user_id=OWNER,
            row="M19",
            anchor_ref=system.anchor,
            subject=forged,
        )

    assert system.graph.commands() == []
    assert system.harness.calls == 0


@pytest.mark.parametrize("mutation", ("duplicate", "recombined", "current_math"))
def test_rejects_duplicate_recombined_or_current_math_graph_state(
    mutation: str,
) -> None:
    system = _system("M21")
    plan = prepare_platform_business_history_m16_m21(
        owner_user_id=OWNER,
        row="M21",
        anchor_ref=system.anchor,
        subject=system.subject,
    )
    if mutation == "duplicate":
        system.graph.apply(plan.command)
        # Corrupt the append-only ledger directly: the public Graph API
        # idempotently deduplicates an identical command id.
        system.graph._commands.append(plan.command)
    elif mutation == "recombined":
        recombined_qro = replace(
            plan.qro,
            evidence_refs=("evidence:m21:recombined",),
        )
        system.graph.apply(
            replace(plan.command, payload={"qro": recombined_qro}, command_id="")
        )
    else:
        bound_qro = replace(
            plan.qro,
            mathematical_refs=("math_spine_chain:m21:already-bound",),
        )
        system.graph.apply(
            ResearchGraphCommand(
                source=EntrySource.API,
                command_type="upsert_qro",
                actor_source=ActorSource.USER_MANUAL,
                actor=OWNER,
                payload={"qro": bound_qro},
                evidence_refs=("math_spine_chain:m21:already-bound",),
                tool_record_refs=(
                    "api:research_os.platform.business_attestations.m21",
                ),
            )
        )

    with pytest.raises(PlatformBusinessHistoryM16M21Error):
        record_platform_business_history_m16_m21(
            context=system.context,
            owner_user_id=OWNER,
            row="M21",
            anchor_ref=system.anchor,
            subject=system.subject,
        )
    assert system.harness.calls == 0


class _PersistentHistoryCoverageResolver:
    """Strict read resolver over one isolated persistent history bundle."""

    def __init__(
        self,
        graph,
        compiler,
        *,
        owner: str,
        lifecycle_refs: tuple[str, ...],
    ) -> None:
        self.graph = graph
        self.compiler = compiler
        self.owner = owner
        self.lifecycle_refs = frozenset(lifecycle_refs)

    def for_owner(self, owner: str):
        if owner != self.owner:
            raise KeyError(owner)
        return self

    def has_qro(self, ref: str) -> bool:
        try:
            return self.graph.qro(ref).owner == self.owner
        except (KeyError, LookupError):
            return False

    def has_research_graph_command(self, ref: str) -> bool:
        return (
            sum(
                command.command_id == ref and command.actor == self.owner
                for command in self.graph.commands()
            )
            == 1
        )

    def has_compiler_ir(self, ref: str) -> bool:
        try:
            return self.compiler.ir(ref, owner=self.owner).owner == self.owner
        except (KeyError, LookupError):
            return False

    def has_compiler_pass(self, ref: str) -> bool:
        try:
            return (
                self.compiler.compiler_pass(ref, owner=self.owner).actor
                == self.owner
            )
        except (KeyError, LookupError):
            return False

    def has_evidence(self, ref: str) -> bool:
        records = (
            *self.compiler.irs(owner=self.owner),
            *self.compiler.passes(owner=self.owner),
        )
        return any(ref in tuple(record.evidence_refs) for record in records)

    def has_lifecycle_record(self, ref: str) -> bool:
        return ref in self.lifecycle_refs

    def has_rdp(self, _ref: str) -> bool:
        return False

    def entrypoint_linkage_violations(self, record):
        if any(
            len(refs) != 1
            for refs in (
                record.qro_refs,
                record.research_graph_command_refs,
                record.compiler_ir_refs,
                record.compiler_pass_refs,
            )
        ):
            return (
                (
                    "entrypoint_ref",
                    record.entrypoint_ref,
                    "history coverage must select one QRO/Graph/IR/pass",
                ),
            )
        qro_ref = record.qro_refs[0]
        command_ref = record.research_graph_command_refs[0]
        ir_ref = record.compiler_ir_refs[0]
        pass_ref = record.compiler_pass_refs[0]
        try:
            qro = self.graph.qro(qro_ref)
            command = next(
                item
                for item in self.graph.commands()
                if item.command_id == command_ref
            )
            compiler_ir = self.compiler.ir(ir_ref, owner=self.owner)
            compiler_pass = self.compiler.compiler_pass(
                pass_ref,
                owner=self.owner,
            )
        except (KeyError, LookupError, StopIteration):
            return (
                (
                    "entrypoint_ref",
                    record.entrypoint_ref,
                    "history coverage does not resolve through persistent stores",
                ),
            )
        embedded = (
            command.payload.get("qro")
            if isinstance(command.payload, dict)
            else None
        )
        canonical = tuple(compiler_ir.canonical_command_refs)
        if (
            embedded != qro
            or qro.owner != self.owner
            or command.actor != self.owner
            or command.source != EntrySource.API
            or tuple(compiler_ir.source_qro_refs) != (qro_ref,)
            or tuple(compiler_ir.graph_command_refs) != (command_ref,)
            or tuple(compiler_pass.input_qro_refs) != (qro_ref,)
            or tuple(compiler_pass.graph_command_refs) != (command_ref,)
            or compiler_pass.output_ir_ref != ir_ref
            or tuple(compiler_pass.canonical_command_refs) != canonical
            or tuple(record.canonical_command_refs) != canonical
            or f"research_graph_command:{command_ref}" not in canonical
            or f"entrypoint:{record.entrypoint_ref}" not in canonical
        ):
            return (
                (
                    "entrypoint_ref",
                    record.entrypoint_ref,
                    "history coverage recombines persistent lineage",
                ),
            )
        return ()


class _FailOncePersistentHistoryCoverage(
    PersistentGoalEntrypointCoverageRegistry
):
    fail_before_append_once = False
    fail_after_append_once = False

    def record_coverage(self, record):
        if self.fail_before_append_once:
            self.fail_before_append_once = False
            raise OSError("injected coverage append failure")
        persisted = super().record_coverage(record)
        if self.fail_after_append_once:
            self.fail_after_append_once = False
            raise OSError("injected coverage durability acknowledgement failure")
        return persisted


class _PersistentHistoryCompilerAdapter:
    def __init__(self, *, compiler, coverage, failure: str) -> None:
        self.compiler = compiler
        self.coverage = coverage
        self.failure = failure
        self.calls = 0

    def compile(self, qro, command, plan):
        self.calls += 1
        built = _CompilerHarness()
        result = built.compile(qro, command, plan)
        compiler_ir = built.store.irs(owner=plan.owner_user_id)[0]
        compiler_pass = built.store.passes(owner=plan.owner_user_id)[0]
        coverage = built.coverage.records(owner=plan.owner_user_id)[0]

        self.compiler.record_ir(compiler_ir)
        if self.failure == "after_ir":
            self.failure = ""
            raise OSError("injected compiler failure after IR append")
        self.compiler.record_pass(compiler_pass)
        if self.failure == "after_pass":
            self.failure = ""
            raise OSError("injected compiler failure after pass append")
        if self.failure == "coverage_failure":
            self.failure = ""
            self.coverage.fail_before_append_once = True
        elif self.failure == "coverage_ack":
            self.failure = ""
            self.coverage.fail_after_append_once = True
        self.coverage.record_coverage(coverage)
        return result


def _persistent_history_runtime(tmp_path, *, row: str, failure: str):
    anchor, subject = _subject(row)
    plan = prepare_platform_business_history_m16_m21(
        owner_user_id=OWNER,
        row=row,
        anchor_ref=anchor,
        subject=subject,
    )
    graph_path = tmp_path / f"{row.lower()}-research-graph.jsonl"
    compiler_path = tmp_path / f"{row.lower()}-compiler.jsonl"
    coverage_path = tmp_path / f"{row.lower()}-coverage.jsonl"
    graph = PersistentResearchGraphStore(graph_path)
    compiler = PersistentCompilerIRStore(compiler_path)
    backing = _PersistentHistoryCoverageResolver(
        graph,
        compiler,
        owner=OWNER,
        lifecycle_refs=plan.compile_plan.lifecycle_refs,
    )
    coverage = _FailOncePersistentHistoryCoverage(
        coverage_path,
        resolver=backing,
    )
    adapter = _PersistentHistoryCompilerAdapter(
        compiler=compiler,
        coverage=coverage,
        failure=failure,
    )

    def fresh_compiler():
        return PersistentCompilerIRStore(compiler_path)

    def fresh_coverage():
        fresh_graph = PersistentResearchGraphStore(graph_path)
        fresh_compiler_store = PersistentCompilerIRStore(compiler_path)
        fresh_backing = _PersistentHistoryCoverageResolver(
            fresh_graph,
            fresh_compiler_store,
            owner=OWNER,
            lifecycle_refs=plan.compile_plan.lifecycle_refs,
        )
        return PersistentGoalEntrypointCoverageRegistry(
            coverage_path,
            resolver=fresh_backing,
        )

    context = PlatformBusinessHistoryM16M21Context(
        research_graph_store=graph,
        compiler_store=compiler,
        entrypoint_registry=coverage,
        apply_graph=graph.apply,
        compile_history=adapter.compile,
        compiler_view_factory=fresh_compiler,
        entrypoint_view_factory=fresh_coverage,
    )
    return SimpleNamespace(
        row=row,
        anchor=anchor,
        subject=subject,
        plan=plan,
        graph=graph,
        compiler=compiler,
        coverage=coverage,
        adapter=adapter,
        context=context,
        paths={
            "graph": graph_path,
            "compiler": compiler_path,
            "coverage": coverage_path,
        },
    )


def _fresh_persistent_history_state(runtime):
    graph = PersistentResearchGraphStore(runtime.paths["graph"])
    compiler = PersistentCompilerIRStore(runtime.paths["compiler"])
    backing = _PersistentHistoryCoverageResolver(
        graph,
        compiler,
        owner=OWNER,
        lifecycle_refs=runtime.plan.compile_plan.lifecycle_refs,
    )
    coverage = PersistentGoalEntrypointCoverageRegistry(
        runtime.paths["coverage"],
        resolver=backing,
    )
    return SimpleNamespace(
        graph=graph,
        compiler=compiler,
        coverage=coverage,
    )


@pytest.mark.parametrize("row", ("M16", "M19", "M21"))
@pytest.mark.parametrize(
    "failure",
    ("after_ir", "after_pass", "coverage_failure", "coverage_ack"),
)
def test_persistent_history_failure_preserves_append_prefix_then_retries_once(
    tmp_path,
    row: str,
    failure: str,
) -> None:
    runtime = _persistent_history_runtime(
        tmp_path,
        row=row,
        failure=failure,
    )
    recorder = PlatformBusinessHistoryM16M21Recorder(runtime.context)

    with pytest.raises(PlatformBusinessHistoryM16M21CommitError) as captured:
        recorder.record(
            owner_user_id=OWNER,
            row=row,
            anchor_ref=runtime.anchor,
            subject=runtime.subject,
        )

    error = captured.value
    assert error.phase == "compiler_coverage"
    assert isinstance(error.__cause__, OSError)
    assert "injected" in str(error.__cause__)
    assert error.graph_command_ref == runtime.plan.command.command_id

    # Every assertion comes from a new replay, not the coordinator's in-memory
    # projection.  A late failure may leave a valid append prefix, but it must
    # never delete or rewrite that durable prefix.
    failed_replay = _fresh_persistent_history_state(runtime)
    expected_counts = {
        "after_ir": (1, 0, 0),
        "after_pass": (1, 1, 0),
        "coverage_failure": (1, 1, 0),
        "coverage_ack": (1, 1, 1),
    }[failure]
    assert len(failed_replay.graph.commands()) == 1
    assert len(failed_replay.compiler.irs(owner=OWNER)) == expected_counts[0]
    assert len(failed_replay.compiler.passes(owner=OWNER)) == expected_counts[1]
    assert len(failed_replay.coverage.records(owner=OWNER)) == expected_counts[2]
    preserved_command = failed_replay.graph.commands()[0]
    preserved_ir_refs = tuple(
        record.ir_ref for record in failed_replay.compiler.irs(owner=OWNER)
    )
    preserved_pass_refs = tuple(
        record.pass_ref for record in failed_replay.compiler.passes(owner=OWNER)
    )
    preserved_coverage_refs = tuple(
        record.coverage_ref
        for record in failed_replay.coverage.records(owner=OWNER)
    )
    failed_bytes = {
        key: (path.read_bytes() if path.exists() else b"")
        for key, path in runtime.paths.items()
    }

    repaired = recorder.record(
        owner_user_id=OWNER,
        row=row,
        anchor_ref=runtime.anchor,
        subject=runtime.subject,
    )
    reused = recorder.record(
        owner_user_id=OWNER,
        row=row,
        anchor_ref=runtime.anchor,
        subject=runtime.subject,
    )

    assert repaired.graph_command_created is False
    assert reused == replace(repaired, graph_command_created=False)
    assert runtime.adapter.calls == (1 if failure == "coverage_ack" else 2)
    success_replay = _fresh_persistent_history_state(runtime)
    assert success_replay.graph.commands() == [preserved_command]
    assert runtime.paths["graph"].read_bytes() == failed_bytes["graph"]
    assert runtime.paths["compiler"].read_bytes().startswith(
        failed_bytes["compiler"]
    )
    assert runtime.paths["coverage"].read_bytes().startswith(
        failed_bytes["coverage"]
    )
    assert [
        record.ir_ref for record in success_replay.compiler.irs(owner=OWNER)
    ] == [repaired.compiler_ir_ref]
    assert [
        record.pass_ref for record in success_replay.compiler.passes(owner=OWNER)
    ] == [repaired.compiler_pass_ref]
    assert [
        record.coverage_ref
        for record in success_replay.coverage.records(owner=OWNER)
    ] == [repaired.entrypoint_coverage_ref]
    assert set(preserved_ir_refs).issubset(
        {record.ir_ref for record in success_replay.compiler.irs(owner=OWNER)}
    )
    assert set(preserved_pass_refs).issubset(
        {record.pass_ref for record in success_replay.compiler.passes(owner=OWNER)}
    )
    assert set(preserved_coverage_refs).issubset(
        {
            record.coverage_ref
            for record in success_replay.coverage.records(owner=OWNER)
        }
    )


def test_m21_two_forks_of_one_template_persist_as_distinct_idempotent_histories(
    tmp_path,
) -> None:
    first_anchor, first_subject = _m21_subject(
        strategy_id="strategy-m21-history-first",
        name="m21_template_fork_first",
    )
    second_anchor, second_subject = _m21_subject(
        strategy_id="strategy-m21-history-second",
        name="m21_template_fork_second",
    )
    assert first_anchor != second_anchor
    assert first_subject.governed_asset == second_subject.governed_asset

    first_plan = prepare_platform_business_history_m16_m21(
        owner_user_id=OWNER,
        row="M21",
        anchor_ref=first_anchor,
        subject=first_subject,
    )
    second_plan = prepare_platform_business_history_m16_m21(
        owner_user_id=OWNER,
        row="M21",
        anchor_ref=second_anchor,
        subject=second_subject,
    )
    assert first_plan.qro.qro_id != second_plan.qro.qro_id
    assert first_plan.command.command_id != second_plan.command.command_id
    assert first_plan.compile_plan.lifecycle_refs == (
        first_subject.governed_asset.asset_ref,
    )
    assert second_plan.compile_plan.lifecycle_refs == (
        first_subject.governed_asset.asset_ref,
    )

    graph_path = tmp_path / "m21-two-forks-research-graph.jsonl"
    compiler_path = tmp_path / "m21-two-forks-compiler.jsonl"
    coverage_path = tmp_path / "m21-two-forks-coverage.jsonl"
    graph = PersistentResearchGraphStore(graph_path)
    compiler = PersistentCompilerIRStore(compiler_path)
    lifecycle_refs = (first_subject.governed_asset.asset_ref,)
    coverage = PersistentGoalEntrypointCoverageRegistry(
        coverage_path,
        resolver=_PersistentHistoryCoverageResolver(
            graph,
            compiler,
            owner=OWNER,
            lifecycle_refs=lifecycle_refs,
        ),
    )
    adapter = _PersistentHistoryCompilerAdapter(
        compiler=compiler,
        coverage=coverage,
        failure="",
    )

    def fresh_compiler():
        return PersistentCompilerIRStore(compiler_path)

    def fresh_coverage():
        fresh_graph = PersistentResearchGraphStore(graph_path)
        fresh_compiler_store = PersistentCompilerIRStore(compiler_path)
        return PersistentGoalEntrypointCoverageRegistry(
            coverage_path,
            resolver=_PersistentHistoryCoverageResolver(
                fresh_graph,
                fresh_compiler_store,
                owner=OWNER,
                lifecycle_refs=lifecycle_refs,
            ),
        )

    recorder = PlatformBusinessHistoryM16M21Recorder(
        PlatformBusinessHistoryM16M21Context(
            research_graph_store=graph,
            compiler_store=compiler,
            entrypoint_registry=coverage,
            apply_graph=graph.apply,
            compile_history=adapter.compile,
            compiler_view_factory=fresh_compiler,
            entrypoint_view_factory=fresh_coverage,
        )
    )
    first = recorder.record(
        owner_user_id=OWNER,
        row="M21",
        anchor_ref=first_anchor,
        subject=first_subject,
    )
    second = recorder.record(
        owner_user_id=OWNER,
        row="M21",
        anchor_ref=second_anchor,
        subject=second_subject,
    )
    persisted_before_retry = {
        path: path.read_bytes()
        for path in (graph_path, compiler_path, coverage_path)
    }

    first_retry = recorder.record(
        owner_user_id=OWNER,
        row="M21",
        anchor_ref=first_anchor,
        subject=first_subject,
    )
    second_retry = recorder.record(
        owner_user_id=OWNER,
        row="M21",
        anchor_ref=second_anchor,
        subject=second_subject,
    )

    assert first_retry == replace(first, graph_command_created=False)
    assert second_retry == replace(second, graph_command_created=False)
    assert adapter.calls == 2
    assert {
        path: path.read_bytes()
        for path in (graph_path, compiler_path, coverage_path)
    } == persisted_before_retry

    replay_graph = PersistentResearchGraphStore(graph_path)
    replay_compiler = PersistentCompilerIRStore(compiler_path)
    replay_coverage = PersistentGoalEntrypointCoverageRegistry(
        coverage_path,
        resolver=_PersistentHistoryCoverageResolver(
            replay_graph,
            replay_compiler,
            owner=OWNER,
            lifecycle_refs=lifecycle_refs,
        ),
    )
    assert {command.command_id for command in replay_graph.commands()} == {
        first.graph_command_ref,
        second.graph_command_ref,
    }
    assert {record.ir_ref for record in replay_compiler.irs(owner=OWNER)} == {
        first.compiler_ir_ref,
        second.compiler_ir_ref,
    }
    assert {
        record.pass_ref for record in replay_compiler.passes(owner=OWNER)
    } == {first.compiler_pass_ref, second.compiler_pass_ref}
    assert {
        record.coverage_ref
        for record in replay_coverage.records(owner=OWNER)
    } == {first.entrypoint_coverage_ref, second.entrypoint_coverage_ref}
    for anchor, result in ((first_anchor, first), (second_anchor, second)):
        qro = replay_graph.qro(result.qro_ref)
        assert qro.input_contract["governed_asset_ref"] == lifecycle_refs[0]
        assert qro.output_contract["ide_strategy_ref"] == anchor


def test_m21_existing_fork_rejects_recombined_strategy_id_without_more_writes() -> None:
    system = _system("M21")
    first = record_platform_business_history_m16_m21(
        context=system.context,
        owner_user_id=OWNER,
        row="M21",
        anchor_ref=system.anchor,
        subject=system.subject,
    )
    changed = replace(
        system.subject,
        ide_strategy=replace(
            system.subject.ide_strategy,
            strategy_id="strategy-m21-same-owner-recombined",
        ),
    )

    with pytest.raises(PlatformBusinessHistoryM16M21Error):
        record_platform_business_history_m16_m21(
            context=system.context,
            owner_user_id=OWNER,
            row="M21",
            anchor_ref=system.anchor,
            subject=changed,
        )

    assert [command.command_id for command in system.graph.commands()] == [
        first.graph_command_ref
    ]
    assert system.harness.calls == 1


@pytest.mark.parametrize(
    "mutation",
    ("name", "code", "description", "validation_refs"),
)
def test_m21_same_strategy_id_rejects_mutated_ide_snapshot_without_more_writes(
    mutation: str,
) -> None:
    system = _system("M21")
    first = record_platform_business_history_m16_m21(
        context=system.context,
        owner_user_id=OWNER,
        row="M21",
        anchor_ref=system.anchor,
        subject=system.subject,
    )
    changes = {
        "name": {"name": "m21_same_id_mutated_name"},
        "code": {"code": "def generate_signal(ctx):\n    return 1\n"},
        "description": {"description": "same id but changed description"},
        "validation_refs": {
            "market_data_use_validation_refs": [
                "market_data_use_validation:m21:same-id-mutated"
            ]
        },
    }[mutation]
    changed = replace(
        system.subject,
        ide_strategy=replace(system.subject.ide_strategy, **changes),
    )

    with pytest.raises(PlatformBusinessHistoryM16M21Error):
        record_platform_business_history_m16_m21(
            context=system.context,
            owner_user_id=OWNER,
            row="M21",
            anchor_ref=system.anchor,
            subject=changed,
        )

    assert [command.command_id for command in system.graph.commands()] == [
        first.graph_command_ref
    ]
    assert len(system.harness.store.irs(owner=OWNER)) == 1
    assert len(system.harness.store.passes(owner=OWNER)) == 1
    assert len(system.harness.coverage.records(owner=OWNER)) == 1
    assert system.harness.calls == 1


def test_persistent_observation_failure_preserves_phase_cause_and_unknown_state(
    tmp_path,
) -> None:
    anchor, subject = _m16_subject()
    graph_path = tmp_path / "observation-failure-graph.jsonl"

    class _FailApplyThenObservation(PersistentResearchGraphStore):
        observation_unavailable = False

        def apply(self, _command):
            self.observation_unavailable = True
            raise OSError("injected graph append failure")

        def commands(self):
            if self.observation_unavailable:
                raise OSError("injected graph observation failure")
            return super().commands()

        def qro(self, ref):
            if self.observation_unavailable:
                raise OSError("injected graph observation failure")
            return super().qro(ref)

        def projection_index(self, *, owner=None):
            if self.observation_unavailable:
                raise OSError("injected graph observation failure")
            return super().projection_index(owner=owner)

    graph = _FailApplyThenObservation(graph_path)
    harness = _CompilerHarness()
    context = PlatformBusinessHistoryM16M21Context(
        research_graph_store=graph,
        compiler_store=harness.store,
        entrypoint_registry=harness.coverage,
        apply_graph=graph.apply,
        compile_history=harness.compile,
    )

    with pytest.raises(PlatformBusinessHistoryM16M21CommitError) as captured:
        record_platform_business_history_m16_m21(
            context=context,
            owner_user_id=OWNER,
            row="M16",
            anchor_ref=anchor,
            subject=subject,
        )

    error = captured.value
    assert error.phase == "research_graph"
    assert isinstance(error.__cause__, OSError)
    assert str(error.__cause__) == "injected graph append failure"
    assert error.graph_history_current is None
    assert error.graph_command_created is None
    assert error.compiler_history_current is None
    assert PersistentResearchGraphStore(graph_path).commands() == []
    assert harness.calls == 0
