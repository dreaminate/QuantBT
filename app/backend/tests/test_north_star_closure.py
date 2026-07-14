from __future__ import annotations

import hashlib
from dataclasses import replace
from pathlib import Path

import pytest

from app.research_os.asset_lifecycle import (
    AssetCategory,
    GovernedAssetRecord,
    LifecycleState,
    PersistentAssetLifecycleRegistry,
)
from app.research_os.compiler import (
    CompilerIRRecord,
    CompilerPassRecord,
    PersistentCompilerIRStore,
)
from app.research_os.entrypoint_evidence import (
    PersistentEntrypointEvidenceRegistry,
)
from app.research_os.goal_coverage import (
    GoalEntrypointCoverageRecord,
    GoalSectionCoverageRecord,
    PersistentGoalEntrypointCoverageRegistry,
    PersistentGoalSectionCoverageRegistry,
    REQUIRED_ENTRY_SOURCES,
    REQUIRED_GOAL_SECTIONS,
    goal_entrypoint_coverage_identity,
)
from app.research_os.goal_entrypoint_lineage_aggregate import (
    CORE_GOAL_SECTIONS,
    PersistentGoalEntrypointLineageAggregateRegistry,
)
from app.research_os.goal_validation_receipts import (
    GoalValidationOutcome,
    GoalValidationReceipt,
    PersistentGoalValidationReceiptRegistry,
)
from app.research_os.goal_semantics import (
    GoalSectionSemanticProofRecord,
    GoalSemanticDecision,
    PersistentGoalSectionSemanticProofRegistry,
    goal_section_semantic_proof_identity,
)
from app.research_os.north_star_closure import (
    NORTH_STAR_SOURCE_SECTIONS,
    NorthStarClosureSectionAdapter,
    build_current_north_star_proof,
    resolve_current_north_star_snapshot,
)
from app.research_os.rdp import PersistentRDPStore, RDPManifest
from app.research_os.spine import (
    ActorSource,
    DefinitionStatus,
    EntrySource,
    EvidenceStatus,
    PersistentResearchGraphStore,
    QRORecord,
    QROType,
    ResearchGraphCommand,
    RuntimeStatus,
)


OWNER = "owner:alice"


class _EntryResolver:
    def __init__(
        self,
        *,
        graph: PersistentResearchGraphStore,
        compiler: PersistentCompilerIRStore,
        evidence: PersistentEntrypointEvidenceRegistry,
        lifecycle: PersistentAssetLifecycleRegistry,
        rdps: PersistentRDPStore,
        owner: str = "",
    ) -> None:
        self._graph = graph
        self._compiler = compiler
        self._evidence = evidence
        self._lifecycle = lifecycle
        self._rdps = rdps
        self._owner = owner

    def for_owner(self, owner: str) -> "_EntryResolver":
        return _EntryResolver(
            graph=self._graph,
            compiler=self._compiler,
            evidence=self._evidence,
            lifecycle=self._lifecycle,
            rdps=self._rdps,
            owner=owner,
        )

    def has_qro(self, ref: str) -> bool:
        try:
            return self._graph.qro(ref).owner == self._owner
        except (KeyError, LookupError):
            return False

    def has_research_graph_command(self, ref: str) -> bool:
        return any(
            item.command_id == ref and item.actor == self._owner
            for item in self._graph.commands()
        )

    def has_compiler_ir(self, ref: str) -> bool:
        try:
            self._compiler.ir(ref, owner=self._owner)
            return True
        except (KeyError, LookupError):
            return False

    def has_compiler_pass(self, ref: str) -> bool:
        try:
            self._compiler.compiler_pass(ref, owner=self._owner)
            return True
        except (KeyError, LookupError):
            return False

    def has_evidence(self, ref: str) -> bool:
        try:
            record = self._evidence.evidence(ref, owner_user_id=self._owner)
            return self._evidence.validate_current(
                record,
                owner_user_id=self._owner,
            ).accepted
        except (KeyError, LookupError, ValueError):
            return False

    def has_lifecycle_record(self, ref: str) -> bool:
        try:
            self._lifecycle.governed_asset(ref, owner_user_id=self._owner)
            return True
        except (KeyError, LookupError):
            return False

    def has_rdp(self, ref: str) -> bool:
        try:
            self._rdps.manifest(ref, owner_user_id=self._owner)
            return True
        except (KeyError, LookupError):
            return False

    def entrypoint_linkage_violations(self, record) -> tuple:
        violations: list[tuple[str, str, str]] = []
        for evidence_ref in record.evidence_refs:
            decision = self._evidence.validate_entrypoint_ref(
                evidence_ref,
                owner_user_id=self._owner,
                record=record,
            )
            violations.extend(
                (item.field, item.ref, item.message)
                for item in decision.violations
            )
        return tuple(violations)


class _AcceptCurrentSection:
    def validate(self, _record, *, owner: str) -> GoalSemanticDecision:
        assert owner == OWNER
        return GoalSemanticDecision(True, ())


class _CoverageWorld:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.graph = PersistentResearchGraphStore(root / "research_graph.jsonl")
        self.compiler = PersistentCompilerIRStore(root / "compiler.jsonl")
        self.receipts = PersistentGoalValidationReceiptRegistry(
            root / "validation_receipts.jsonl"
        )
        self.lifecycle = PersistentAssetLifecycleRegistry(
            root / "asset_lifecycle.jsonl"
        )
        self.rdps = PersistentRDPStore(root / "rdp_manifests.jsonl")
        self.evidence = PersistentEntrypointEvidenceRegistry(
            root / "entrypoint_evidence.jsonl",
            research_graph_store=self.graph,
            compiler_store=self.compiler,
            validation_receipt_registry=self.receipts,
        )

    def resolver(self, *, reopen: bool = False) -> _EntryResolver:
        if not reopen:
            return _EntryResolver(
                graph=self.graph,
                compiler=self.compiler,
                evidence=self.evidence,
                lifecycle=self.lifecycle,
                rdps=self.rdps,
            )
        graph = PersistentResearchGraphStore(self.graph.path)
        compiler = PersistentCompilerIRStore(self.compiler.path)
        receipts = PersistentGoalValidationReceiptRegistry(self.receipts.path)
        return _EntryResolver(
            graph=graph,
            compiler=compiler,
            evidence=PersistentEntrypointEvidenceRegistry(
                self.evidence.path,
                research_graph_store=graph,
                compiler_store=compiler,
                validation_receipt_registry=receipts,
            ),
            lifecycle=PersistentAssetLifecycleRegistry(self.lifecycle.path),
            rdps=PersistentRDPStore(self.rdps.path),
        )

    def materialize(
        self,
        source: str,
        *,
        revision: str = "v1",
        goal_sections: tuple[str, ...] = CORE_GOAL_SECTIONS,
    ) -> GoalEntrypointCoverageRecord:
        suffix = "north-star" if revision == "v1" else f"north-star-{revision}"
        entrypoint_ref = f"route:{source}:{suffix}"
        raw_evidence_ref = f"source_evidence:{source}:{suffix}"
        permission_ref = f"permission:{source}:{suffix}"
        lifecycle_ref = f"governed_asset:strategybook:{source}:{suffix}"
        chain_ref = f"math_spine_chain:{source}:{suffix}"
        qro = QRORecord(
            qro_type=QROType.STRATEGY_BOOK,
            owner=OWNER,
            actor=ActorSource.USER_MANUAL,
            input_contract={"entry_source": source, "revision": revision},
            output_contract={"asset_ref": lifecycle_ref},
            market="global",
            universe="north_star_fixture",
            horizon="current",
            frequency="event",
            lineage=("north_star", source, revision),
            implementation_hash=f"north_star:{source}:{revision}",
            assumptions=("the fixture is owner scoped",),
            known_limits=("the fixture proves closure wiring only",),
            failure_modes=("recombined evidence must be rejected",),
            validation_plan=("reopen every persisted dependency",),
            definition_status=DefinitionStatus.IMPLEMENTED,
            evidence_status=EvidenceStatus.SUFFICIENT,
            runtime_status=RuntimeStatus.OFFLINE,
            evidence_refs=(raw_evidence_ref,),
            permission=permission_ref,
            allowed_environment=RuntimeStatus.OFFLINE,
        )
        command = ResearchGraphCommand(
            source=EntrySource(source),
            command_type="upsert_qro",
            actor_source=ActorSource.USER_MANUAL,
            actor=OWNER,
            payload={"qro": qro},
            evidence_refs=(raw_evidence_ref,),
            tool_record_refs=(f"entrypoint:{entrypoint_ref}",),
        )
        self.graph.apply(command)
        provisional_receipt = GoalValidationReceipt(
            validation_ref="",
            owner_user_id=OWNER,
            subject_qro_refs=(qro.qro_id,),
            graph_command_refs=(command.command_id,),
            validator_identifiers=(
                "runtime_validator:goal_full_product_entrypoint_v1",
            ),
            test_identifiers=("pytest:test_north_star_closure",),
            outcome=GoalValidationOutcome.PASSED,
            evidence_refs=(raw_evidence_ref,),
            evidence_digests=(
                "sha256:"
                + hashlib.sha256(raw_evidence_ref.encode("utf-8")).hexdigest(),
            ),
        )
        receipt = self.receipts.record_receipt(
            replace(
                provisional_receipt,
                validation_ref=provisional_receipt.canonical_validation_ref,
            )
        )
        ir_ref = f"compiler_ir:{source}:{suffix}"
        pass_ref = f"compiler_pass:{source}:{suffix}"
        pass_name = f"compile_north_star_{source}_{revision}"
        coverage_ref = goal_entrypoint_coverage_identity(
            entry_source=source,
            entrypoint_ref=entrypoint_ref,
            goal_sections=goal_sections,
            qro_refs=(qro.qro_id,),
            research_graph_command_refs=(command.command_id,),
            compiler_ir_refs=(ir_ref,),
            compiler_pass_refs=(pass_ref,),
        )
        asset = self.lifecycle.record_governed_asset(
            GovernedAssetRecord(
                asset_ref=lifecycle_ref,
                asset_type="StrategyBook",
                category=AssetCategory.USER_ASSET,
                lifecycle_state=LifecycleState.SPECIFIED,
                evidence_refs=(raw_evidence_ref,),
                validation_plan_ref=f"validation_plan:{source}:{suffix}",
                promotion_history=(),
            ),
            owner_user_id=OWNER,
        )
        rdp = self.rdps.record_manifest(
            RDPManifest(
                research_question=f"Does {source} preserve the north-star lineage?",
                graph_refs=(command.command_id,),
                data_refs=(f"dataset:{source}:{suffix}",),
                dataset_version_refs=(f"dataset_version:{source}:{suffix}",),
                market_data_use_validation_refs=(f"market_data_use:{source}:{suffix}",),
                ingestion_skill_refs=(f"ingestion_skill:{source}:{suffix}",),
                mathematical_refs=(f"math_artifact:{source}:{suffix}",),
                theory_binding_refs=(f"theory_binding:{source}:{suffix}",),
                consistency_check_refs=(f"consistency_check:{source}:{suffix}",),
                asset_refs=(asset.asset_ref,),
                code_refs=(f"code:{source}:{suffix}",),
                environment_lock_ref=f"environment_lock:{source}:{suffix}",
                reproducibility_command=f"quantbt reproduce {source} {revision}",
                artifact_hash="sha256:"
                + hashlib.sha256(coverage_ref.encode("utf-8")).hexdigest(),
                test_refs=("pytest:test_north_star_closure",),
                run_refs=(f"run:{source}:{suffix}",),
                honest_n_refs=(f"honest_n:{source}:{suffix}",),
                cost_and_execution_assumptions=(f"cost_assumption:{source}:{suffix}",),
                attribution_refs=(f"attribution:{source}:{suffix}",),
                known_limits=("this is a local closure fixture",),
                unverified_residuals=("external production acceptance is absent",),
                verifier_verdict_ref=f"verifier_verdict:{source}:{suffix}",
                compiler_artifact_refs=(ir_ref, pass_ref),
                mathematical_spine_chain_refs=(chain_ref,),
                goal_entrypoint_coverage_refs=(coverage_ref,),
                source_file_refs=(f"source_file:{source}:{suffix}",),
                target_runtime=RuntimeStatus.OFFLINE,
            ),
            owner_user_id=OWNER,
            recorded_by=OWNER,
        )
        run_plan_ref = f"run_plan:{source}:{suffix}"
        rollback_ref = f"rollback:{source}:{suffix}"
        environment_lock_ref = f"environment_lock:{source}:{suffix}"
        evidence = self.evidence.prepare_record(
            owner_user_id=OWNER,
            entry_source=source,
            entrypoint_ref=entrypoint_ref,
            goal_sections=goal_sections,
            qro_ref=qro.qro_id,
            research_graph_ref=command.command_id,
            validation_ref=receipt.validation_ref,
            compiler_ir_ref=ir_ref,
            compiler_pass_ref=pass_ref,
            coverage_ref=coverage_ref,
            actor_source=ActorSource.USER_MANUAL.value,
            pass_name=pass_name,
            permission_ref=permission_ref,
            environment_lock_ref=environment_lock_ref,
            deterministic_run_plan_ref=run_plan_ref,
            rollback_ref=rollback_ref,
            lifecycle_refs=(asset.asset_ref,),
            rdp_refs=(rdp.package_id,),
        )
        evidence = self.evidence.record_evidence(evidence)
        canonical_refs = (
            f"research_graph_command:{command.command_id}",
            f"entrypoint:{entrypoint_ref}",
        )
        ir = self.compiler.record_ir(
            CompilerIRRecord(
                ir_ref=ir_ref,
                source_qro_refs=(qro.qro_id,),
                graph_command_refs=(command.command_id,),
                canonical_command_refs=canonical_refs,
                node_refs=(qro.qro_id, f"entrypoint:{entrypoint_ref}"),
                edge_refs=(),
                artifact_refs=(asset.asset_ref,),
                theory_binding_refs=(),
                consistency_check_refs=(),
                evidence_refs=(evidence.evidence_ref,),
                validation_refs=(receipt.validation_ref,),
                permission_ref=permission_ref,
                deterministic_run_plan_ref=run_plan_ref,
                rollback_ref=rollback_ref,
                environment_lock_ref=environment_lock_ref,
                owner=OWNER,
                target_runtime=RuntimeStatus.OFFLINE,
                mock_profile="none",
            )
        )
        compiler_pass = self.compiler.record_pass(
            CompilerPassRecord(
                pass_ref=pass_ref,
                pass_name=pass_name,
                input_ir_refs=(),
                output_ir_ref=ir.ir_ref,
                input_qro_refs=(qro.qro_id,),
                graph_command_refs=(command.command_id,),
                canonical_command_refs=canonical_refs,
                actor=OWNER,
                actor_source=ActorSource.USER_MANUAL,
                entry_source=EntrySource(source),
                permission_ref=permission_ref,
                tool_record_refs=(entrypoint_ref, f"entrypoint:{entrypoint_ref}"),
                evidence_refs=(evidence.evidence_ref,),
                validation_refs=(receipt.validation_ref,),
                deterministic_run_plan_ref=run_plan_ref,
                rollback_ref=rollback_ref,
            )
        )
        return GoalEntrypointCoverageRecord(
            coverage_ref=coverage_ref,
            entry_source=source,
            entrypoint_ref=entrypoint_ref,
            goal_sections=goal_sections,
            qro_refs=(qro.qro_id,),
            research_graph_command_refs=(command.command_id,),
            compiler_ir_refs=(ir.ir_ref,),
            compiler_pass_refs=(compiler_pass.pass_ref,),
            evidence_refs=(evidence.evidence_ref,),
            validation_refs=(receipt.validation_ref,),
            permission_refs=(permission_ref,),
            replay_refs=(
                f"replay:research_graph:{command.command_id}",
                f"replay:compiler_ir:{ir.ir_ref}",
                f"replay:compiler_pass:{compiler_pass.pass_ref}",
            ),
            canonical_command_refs=canonical_refs,
            lifecycle_refs=(asset.asset_ref,),
            rdp_refs=(rdp.package_id,),
            recorded_by=OWNER,
            claims_full_product_entrypoint=False,
        )


def _source_proof(section: str, coverage_ref: str, *, revision: str = "v1") -> GoalSectionSemanticProofRecord:
    token = section.removeprefix("§")
    values = {
        "section": section,
        "subject_ref": f"section_subject:{token}:{revision}",
        "producer_refs": (f"section_producer:{token}:{revision}",),
        "store_refs": (f"section_store:{token}:{revision}",),
        "consumer_refs": (f"section_consumer:{token}:{revision}",),
        "gate_verdict_refs": (f"section_gate:{token}:{revision}",),
        "test_refs": (f"pytest:section_{token}:{revision}",),
        "entrypoint_coverage_refs": (coverage_ref,),
        "recorded_by": OWNER,
        "claims_section_complete": True,
        "unverified_residuals": (),
    }
    return GoalSectionSemanticProofRecord(
        proof_ref=goal_section_semantic_proof_identity(**values),
        **values,
    )


def _replace_proof(
    proof: GoalSectionSemanticProofRecord,
    **updates: object,
) -> GoalSectionSemanticProofRecord:
    changed = replace(proof, **updates, proof_ref="")
    return replace(
        changed,
        proof_ref=goal_section_semantic_proof_identity(
            section=changed.section,
            subject_ref=changed.subject_ref,
            producer_refs=changed.producer_refs,
            store_refs=changed.store_refs,
            consumer_refs=changed.consumer_refs,
            gate_verdict_refs=changed.gate_verdict_refs,
            test_refs=changed.test_refs,
            entrypoint_coverage_refs=changed.entrypoint_coverage_refs,
            recorded_by=changed.recorded_by,
            claims_section_complete=changed.claims_section_complete,
            unverified_residuals=changed.unverified_residuals,
        ),
    )


def _coverage_for_section(
    coverages: tuple[GoalEntrypointCoverageRecord, ...],
    section: str,
) -> GoalEntrypointCoverageRecord:
    return next(
        coverage for coverage in coverages if section in coverage.goal_sections
    )


def _stores(tmp_path, *, section_count: int = 17):
    world = _CoverageWorld(tmp_path)
    base_coverages = tuple(
        world.materialize(source) for source in REQUIRED_ENTRY_SOURCES
    )
    support = {
        section: (
            base_coverages[0]
            if section in CORE_GOAL_SECTIONS
            else world.materialize(
                "api",
                revision=f"section-{section.removeprefix('§')}",
                goal_sections=(section,),
            )
        )
        for section in NORTH_STAR_SOURCE_SECTIONS
    }
    coverages = tuple(dict.fromkeys((*base_coverages, *support.values())))
    entrypoints = PersistentGoalEntrypointCoverageRegistry(
        tmp_path / "entrypoints.jsonl",
        resolver=world.resolver(),
    )
    for coverage in coverages:
        entrypoints.record_coverage(coverage)
    aggregates = PersistentGoalEntrypointLineageAggregateRegistry(
        tmp_path / "aggregates.jsonl",
        entrypoints,
    )
    aggregates.record_current(owner_user_id=OWNER)
    semantic = PersistentGoalSectionSemanticProofRegistry(
        tmp_path / "semantic.jsonl",
        entrypoints,
    )
    for section in NORTH_STAR_SOURCE_SECTIONS:
        semantic.register_adapter(section, _AcceptCurrentSection())
    for section in NORTH_STAR_SOURCE_SECTIONS[:section_count]:
        semantic.record_proof(_source_proof(section, support[section].coverage_ref))
    semantic.register_adapter(
        "§0",
        NorthStarClosureSectionAdapter(semantic, aggregates),
    )
    return entrypoints, aggregates, semantic, coverages, world


def test_north_star_proof_is_derived_from_all_nonzero_heads_and_persists(tmp_path) -> None:
    entrypoints, aggregates, semantic, coverages, world = _stores(tmp_path)
    proof = build_current_north_star_proof(semantic, aggregates, owner=OWNER)
    entrypoint_before = entrypoints.path.read_bytes()
    aggregate_before = aggregates.path.read_bytes()

    assert proof.section == "§0"
    assert proof.claims_section_complete is True
    assert proof.unverified_residuals == ()
    assert len(resolve_current_north_star_snapshot(semantic, aggregates, owner=OWNER).section_proof_refs) == 17
    assert semantic.record_proof(proof) == proof
    assert semantic.validate_real_backing(proof, owner=OWNER).accepted is True
    semantic_after = semantic.path.read_bytes()
    assert semantic.record_proof(proof) == proof
    assert semantic.path.read_bytes() == semantic_after
    assert entrypoints.path.read_bytes() == entrypoint_before
    assert aggregates.path.read_bytes() == aggregate_before

    replayed_entrypoints = PersistentGoalEntrypointCoverageRegistry(
        entrypoints.path,
        resolver=world.resolver(reopen=True),
    )
    replayed_aggregates = PersistentGoalEntrypointLineageAggregateRegistry(
        aggregates.path,
        replayed_entrypoints,
    )
    replayed = PersistentGoalSectionSemanticProofRegistry(
        semantic.path,
        replayed_entrypoints,
        adapters={section: _AcceptCurrentSection() for section in NORTH_STAR_SOURCE_SECTIONS},
    )
    replayed.register_adapter(
        "§0",
        NorthStarClosureSectionAdapter(replayed, replayed_aggregates),
    )
    restored = replayed.proof(proof.proof_ref, owner=OWNER)
    assert replayed.validate_real_backing(restored, owner=OWNER).accepted is True


def test_missing_section_refuses_to_build_or_write_zero_proof(tmp_path) -> None:
    _entrypoints, aggregates, semantic, _coverages, _world = _stores(
        tmp_path,
        section_count=16,
    )
    before = semantic.path.read_bytes()

    with pytest.raises(ValueError, match="north_star_section_proof_missing:§17"):
        build_current_north_star_proof(semantic, aggregates, owner=OWNER)

    assert semantic.path.read_bytes() == before
    assert semantic.records(owner=OWNER, section="§0") == []


@pytest.mark.parametrize(
    "field_name",
    (
        "subject_ref",
        "producer_refs",
        "store_refs",
        "consumer_refs",
        "gate_verdict_refs",
        "test_refs",
        "entrypoint_coverage_refs",
    ),
)
def test_recombined_field_is_rejected_without_partial_append(
    tmp_path,
    field_name: str,
) -> None:
    _entrypoints, aggregates, semantic, _coverages, _world = _stores(tmp_path)
    proof = build_current_north_star_proof(semantic, aggregates, owner=OWNER)
    if field_name == "subject_ref":
        updates = {field_name: "north_star_snapshot:foreign"}
    elif field_name == "entrypoint_coverage_refs":
        updates = {
            field_name: (
                *proof.entrypoint_coverage_refs,
                proof.entrypoint_coverage_refs[0],
            )
        }
    else:
        updates = {
            field_name: (*getattr(proof, field_name), f"{field_name}:foreign")
        }
    poisoned = _replace_proof(proof, **updates)
    before = semantic.path.read_bytes()

    with pytest.raises(ValueError, match="goal_semantic_north_star_invalid"):
        semantic.record_proof(poisoned)

    assert semantic.path.read_bytes() == before
    assert semantic.records(owner=OWNER, section="§0") == []


def test_new_section_head_invalidates_old_zero_proof(tmp_path) -> None:
    _entrypoints, aggregates, semantic, coverages, _world = _stores(tmp_path)
    old = build_current_north_star_proof(semantic, aggregates, owner=OWNER)
    semantic.record_proof(old)
    semantic.record_proof(
        _source_proof(
            "§17",
            _coverage_for_section(coverages, "§17").coverage_ref,
            revision="v2",
        )
    )

    assert semantic.validate_real_backing(old, owner=OWNER).accepted is False
    current = build_current_north_star_proof(semantic, aggregates, owner=OWNER)
    assert current.proof_ref != old.proof_ref
    assert semantic.record_proof(current) == current


def test_historical_zero_ref_cannot_feed_back_through_new_section_head(tmp_path) -> None:
    _entrypoints, aggregates, semantic, coverages, _world = _stores(tmp_path)
    zero = build_current_north_star_proof(semantic, aggregates, owner=OWNER)
    semantic.record_proof(zero)
    section_one = _source_proof(
        "§1",
        _coverage_for_section(coverages, "§1").coverage_ref,
        revision="v2",
    )
    semantic.record_proof(
        _replace_proof(
            section_one,
            store_refs=(*section_one.store_refs, zero.proof_ref),
        )
    )
    before = semantic.path.read_bytes()

    with pytest.raises(ValueError, match="north_star_historical_zero_ref_cycle"):
        build_current_north_star_proof(semantic, aggregates, owner=OWNER)
    assert semantic.path.read_bytes() == before
    assert semantic.validate_real_backing(zero, owner=OWNER).accepted is False


def test_historical_zero_snapshot_cannot_feed_back_as_section_subject(tmp_path) -> None:
    _entrypoints, aggregates, semantic, coverages, _world = _stores(tmp_path)
    zero = build_current_north_star_proof(semantic, aggregates, owner=OWNER)
    semantic.record_proof(zero)
    section_one = _source_proof(
        "§1",
        _coverage_for_section(coverages, "§1").coverage_ref,
        revision="v2",
    )
    semantic.record_proof(
        _replace_proof(section_one, subject_ref=zero.subject_ref)
    )
    before = semantic.path.read_bytes()

    with pytest.raises(ValueError, match="north_star_historical_zero_ref_cycle"):
        build_current_north_star_proof(semantic, aggregates, owner=OWNER)

    assert semantic.path.read_bytes() == before
    assert semantic.validate_real_backing(zero, owner=OWNER).accepted is False


def test_direct_zero_self_subject_is_rejected_without_write(tmp_path) -> None:
    _entrypoints, aggregates, semantic, _coverages, _world = _stores(tmp_path)
    proof = build_current_north_star_proof(semantic, aggregates, owner=OWNER)
    poisoned = replace(proof, subject_ref=proof.proof_ref)
    before = semantic.path.read_bytes()

    with pytest.raises(ValueError):
        semantic.record_proof(poisoned)

    assert semantic.path.read_bytes() == before
    assert semantic.records(owner=OWNER, section="§0") == []


def test_unpersisted_current_aggregate_blocks_reclosure_without_semantic_write(
    tmp_path,
) -> None:
    entrypoints, aggregates, semantic, coverages, world = _stores(tmp_path)
    old = build_current_north_star_proof(semantic, aggregates, owner=OWNER)
    semantic.record_proof(old)
    newer_api = world.materialize("api", revision="v2")
    entrypoints.set_ref_resolver(world.resolver())
    entrypoints.record_coverage(newer_api)
    before = semantic.path.read_bytes()

    assert semantic.validate_real_backing(old, owner=OWNER).accepted is False
    with pytest.raises(
        ValueError,
        match="north_star_entrypoint_aggregate_not_persisted",
    ):
        build_current_north_star_proof(semantic, aggregates, owner=OWNER)
    assert semantic.path.read_bytes() == before

    aggregate = aggregates.record_current(owner_user_id=OWNER)
    assert newer_api.coverage_ref in aggregate.coverage_refs
    current = build_current_north_star_proof(semantic, aggregates, owner=OWNER)
    assert current.proof_ref != old.proof_ref
    assert semantic.record_proof(current) == current


def test_missing_persisted_aggregate_and_wrong_owner_do_not_write(tmp_path) -> None:
    entrypoints, _aggregates, semantic, _coverages, _world = _stores(tmp_path)
    empty_aggregates = PersistentGoalEntrypointLineageAggregateRegistry(
        tmp_path / "empty-aggregates.jsonl",
        entrypoints,
    )
    before = semantic.path.read_bytes()

    with pytest.raises(
        ValueError,
        match="north_star_entrypoint_aggregate_not_persisted",
    ):
        build_current_north_star_proof(
            semantic,
            empty_aggregates,
            owner=OWNER,
        )
    with pytest.raises(ValueError, match="missing strict non-full core sources"):
        build_current_north_star_proof(
            semantic,
            empty_aggregates,
            owner="owner:bob",
        )

    assert semantic.path.read_bytes() == before


def test_strict_manifest_turns_red_on_zero_head_drift_and_recovers(tmp_path) -> None:
    entrypoints, aggregates, semantic, coverages, world = _stores(tmp_path)
    zero = build_current_north_star_proof(semantic, aggregates, owner=OWNER)
    semantic.record_proof(zero)
    section_path = tmp_path / "section-coverage.jsonl"
    sections = PersistentGoalSectionCoverageRegistry(
        section_path,
        entrypoints,
        semantic,
    )

    def section_record(section: str, proof_ref: str) -> GoalSectionCoverageRecord:
        token = section.removeprefix("§")
        return GoalSectionCoverageRecord(
            section=section,
            contract_refs=(f"contract:goal-section-{token}",),
            test_refs=(f"pytest:north-star-manifest:section-{token}",),
            task_refs=(f"task:north-star-manifest:section-{token}",),
            evidence_refs=(f"evidence:north-star-manifest:section-{token}",),
            recorded_by=OWNER,
            full_entrypoint_wired=True,
            entrypoint_wiring_refs=(
                _coverage_for_section(coverages, section).coverage_ref,
            ),
            semantic_proof_refs=(proof_ref,),
        )

    for section in REQUIRED_GOAL_SECTIONS:
        proof = (
            zero
            if section == "§0"
            else semantic.records(owner=OWNER, section=section)[-1]
        )
        sections.record_coverage(section_record(section, proof.proof_ref))

    assert sections.validate_real_manifest(
        claims_full_product_implementation=True,
        owner=OWNER,
    ).accepted is True

    semantic.record_proof(
        _source_proof(
            "§17",
            _coverage_for_section(coverages, "§17").coverage_ref,
            revision="v2",
        )
    )
    stale = sections.validate_real_manifest(
        claims_full_product_implementation=True,
        owner=OWNER,
    )
    assert stale.accepted is False
    assert any(
        violation.code == "goal_section_semantic_proof_not_real_backed"
        and violation.ref == "§0"
        for violation in stale.violations
    )

    current = build_current_north_star_proof(semantic, aggregates, owner=OWNER)
    semantic.record_proof(current)
    sections.record_coverage(section_record("§0", current.proof_ref))
    assert sections.validate_real_manifest(
        claims_full_product_implementation=True,
        owner=OWNER,
    ).accepted is True

    replayed_entrypoints = PersistentGoalEntrypointCoverageRegistry(
        entrypoints.path,
        resolver=world.resolver(reopen=True),
    )
    replayed_aggregates = PersistentGoalEntrypointLineageAggregateRegistry(
        aggregates.path,
        replayed_entrypoints,
    )
    replayed_semantic = PersistentGoalSectionSemanticProofRegistry(
        semantic.path,
        replayed_entrypoints,
        adapters={
            section: _AcceptCurrentSection()
            for section in NORTH_STAR_SOURCE_SECTIONS
        },
    )
    replayed_semantic.register_adapter(
        "§0",
        NorthStarClosureSectionAdapter(replayed_semantic, replayed_aggregates),
    )
    replayed_sections = PersistentGoalSectionCoverageRegistry(
        section_path,
        replayed_entrypoints,
        replayed_semantic,
    )
    assert replayed_sections.validate_real_manifest(
        claims_full_product_implementation=True,
        owner=OWNER,
    ).accepted is True
