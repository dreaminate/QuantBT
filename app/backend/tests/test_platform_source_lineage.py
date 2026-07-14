from __future__ import annotations

import json
from dataclasses import dataclass, fields, replace
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from app.research_os.asset_rag import PersistentResearchAssetRAGIndex
from app.research_os.compiler import (
    CompilerIRRecord,
    CompilerPassRecord,
    PersistentCompilerIRStore,
)
from app.research_os.goal_coverage import PersistentGoalEntrypointCoverageRegistry
from app.research_os.goal_validation_receipts import (
    GoalValidationOutcome,
    GoalValidationReceipt,
    PersistentGoalValidationReceiptRegistry,
)
from app.research_os.platform_coverage import PlatformSpecificRef
from app.research_os.platform_row_sources import (
    PersistentPlatformRowSourceRegistry,
    PlatformRowSourceError,
)
from app.research_os.platform_source_lineage import (
    PlatformSourceLineageCommitError,
    PlatformSourceLineageError,
    PlatformSourceLineageProducer,
    PlatformSourceLineageSelection,
    derive_platform_source_lineage_evidence,
)
from app.research_os.platform_typed_sources import (
    PlatformTypedSourceAdapter,
    RealPlatformTypedSourceResolver,
)
from app.research_os.ref_resolution import build_real_ref_resolver
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


OWNER = "owner-platform-lineage"
OTHER_OWNER = "owner-platform-lineage-other"
ROW = "M15"
ENTRYPOINT = "api:research_os.desk_topology.current"
LIFECYCLE_REF = "desk_topology_receipt:current:v1"
MATH_REF = "math_spine_chain:desk_topology:v1"
EVIDENCE_REF = "evidence:platform_source_lineage:desk_topology"


class _LegacyTestCompilerStore(PersistentCompilerIRStore):
    """Expose legacy rows as canonical only inside this no-ledger test fixture."""

    def canonical_records(self, *, owner: str) -> SimpleNamespace:
        return SimpleNamespace(
            owner=owner,
            irs=tuple(self.irs(owner=owner)),
            passes=tuple(self.passes(owner=owner)),
            artifacts=(),
        )

    def canonical_ir(self, ir_ref: str, *, owner: str) -> CompilerIRRecord:
        return self.ir(ir_ref, owner=owner)

    def canonical_compiler_pass(
        self,
        pass_ref: str,
        *,
        owner: str,
    ) -> CompilerPassRecord:
        return self.compiler_pass(pass_ref, owner=owner)


@dataclass(frozen=True)
class _LifecycleRecord:
    lifecycle_ref: str
    owner_user_id: str
    recorded_by: str
    qro_ref: str
    revision: str = "v1"


class _LifecycleRegistry:
    def __init__(self, record: _LifecycleRecord) -> None:
        self.records = {(record.owner_user_id, record.lifecycle_ref): record}

    def load_for_coverage(self, ref: str, owner: str):
        return self.records[(owner, ref)]

    def load(self, ref: str, owner: str, record: Any):
        value = self.records[(owner, ref)]
        if value.qro_ref != record.qro_ref:
            raise LookupError("lifecycle/QRO mismatch")
        return value


@dataclass(frozen=True)
class _MathChain:
    chain_ref: str
    owner_user_id: str
    qro_ref: str
    revision: str = "v1"


class _MathRegistry:
    def __init__(self, chain: _MathChain) -> None:
        self.chains = {(chain.owner_user_id, chain.chain_ref): chain}

    def verified_chain(self, ref: str, *, owner: str):
        return self.chains[(owner, ref)]


@dataclass
class _System:
    root: Path
    graph: PersistentResearchGraphStore
    compiler: PersistentCompilerIRStore
    validations: PersistentGoalValidationReceiptRegistry
    entrypoints: PersistentGoalEntrypointCoverageRegistry
    rag: PersistentResearchAssetRAGIndex
    lifecycle: _LifecycleRegistry
    math: _MathRegistry
    resolver: RealPlatformTypedSourceResolver
    producer: PlatformSourceLineageProducer
    selection: PlatformSourceLineageSelection

    @property
    def source_path(self) -> Path:
        return self.root / "platform_row_sources.jsonl"

    @property
    def coverage_path(self) -> Path:
        return self.root / "goal_entrypoint_coverage.jsonl"

    @property
    def rag_path(self) -> Path:
        return self.root / "research_asset_rag.jsonl"

    @property
    def evidence_path(self) -> Path:
        return self.root / "platform_source_lineage_evidence.jsonl"

    def source_registry(self) -> PersistentPlatformRowSourceRegistry:
        return PersistentPlatformRowSourceRegistry(
            self.source_path,
            entrypoint_registry=self.entrypoints,
            rag_index=self.rag,
            source_resolver=self.resolver,
        )


def _qro(*, owner: str = OWNER, suffix: str = "primary") -> QRORecord:
    return QRORecord(
        qro_type=QROType.VALIDATION_DOSSIER,
        owner=owner,
        actor=ActorSource.USER_MANUAL,
        input_contract={
            "entry_source": EntrySource.API.value,
            "entrypoint_ref": ENTRYPOINT,
            "selection": suffix,
        },
        output_contract={"topology_status": "current", "selection": suffix},
        market="global",
        universe="research_desks",
        horizon="current",
        frequency="event",
        lineage=("desk_topology", suffix),
        implementation_hash=f"desk_topology:{suffix}:real",
        assumptions=("nine desk topology was persisted before certification",),
        known_limits=("this QRO records topology state, not trading performance",),
        failure_modes=("a stale graph command can no longer match current QRO state",),
        validation_plan=("run the durable platform source lineage gate",),
        definition_status=DefinitionStatus.IMPLEMENTED,
        evidence_status=EvidenceStatus.SUFFICIENT,
        runtime_status=RuntimeStatus.OFFLINE,
        evidence_refs=(EVIDENCE_REF,),
        mathematical_refs=(MATH_REF,),
        permission=f"permission:{owner}:desk_topology",
        allowed_environment=RuntimeStatus.OFFLINE,
    )


def _record_graph_qro(
    graph: PersistentResearchGraphStore,
    qro: QRORecord,
    *,
    timestamp: str | None = None,
) -> ResearchGraphCommand:
    timestamp_arg = {} if timestamp is None else {"timestamp": timestamp}
    command = ResearchGraphCommand(
        source=EntrySource.API,
        command_type="upsert_qro",
        actor_source=ActorSource.USER_MANUAL,
        actor=qro.owner,
        payload={"qro": qro},
        evidence_refs=(EVIDENCE_REF,),
        tool_record_refs=(f"endpoint:{ENTRYPOINT}",),
        **timestamp_arg,
    )
    graph.apply(command)
    return command


def _record_receipt(
    registry: PersistentGoalValidationReceiptRegistry,
    *,
    qro_ref: str,
    graph_ref: str,
    outcome: GoalValidationOutcome,
) -> GoalValidationReceipt:
    provisional = GoalValidationReceipt(
        validation_ref="",
        owner_user_id=OWNER,
        subject_qro_refs=(qro_ref,),
        graph_command_refs=(graph_ref,),
        validator_identifiers=(
            "runtime_validator:platform_source_lineage_qro_graph_v1",
        ),
        test_identifiers=("pytest:test_platform_source_lineage",),
        outcome=outcome,
        evidence_refs=(EVIDENCE_REF,),
        evidence_digests=("sha256:" + "a" * 64,),
    )
    return registry.record_receipt(
        replace(
            provisional,
            validation_ref=provisional.canonical_validation_ref,
        )
    )


def _record_compiler_lineage(
    compiler: PersistentCompilerIRStore,
    *,
    qro_ref: str,
    graph_ref: str,
    receipt_ref: str,
    suffix: str = "primary",
    math_spine_ref: str = MATH_REF,
    evidence_ref: str = EVIDENCE_REF,
) -> tuple[CompilerIRRecord, CompilerPassRecord]:
    ir_ref = f"compiler_ir:platform_source_lineage:{suffix}"
    pass_ref = f"compiler_pass:platform_source_lineage:{suffix}"
    canonical = (
        f"research_graph_command:{graph_ref}",
        f"entrypoint:{ENTRYPOINT}",
    )
    ir = CompilerIRRecord(
        ir_ref=ir_ref,
        source_qro_refs=(qro_ref,),
        graph_command_refs=(graph_ref,),
        canonical_command_refs=canonical,
        node_refs=(f"qro:{qro_ref}", f"entrypoint:{ENTRYPOINT}"),
        edge_refs=(),
        artifact_refs=(),
        theory_binding_refs=(),
        consistency_check_refs=(),
        evidence_refs=(evidence_ref,),
        validation_refs=(receipt_ref,),
        permission_ref=f"permission:{OWNER}:platform_source_lineage",
        deterministic_run_plan_ref=f"runplan:platform_source_lineage:{suffix}",
        rollback_ref=f"rollback:platform_source_lineage:{suffix}",
        environment_lock_ref="env:platform_source_lineage:v1",
        mathematical_spine_chain_refs=(math_spine_ref,),
        owner=OWNER,
        target_runtime=RuntimeStatus.OFFLINE,
        mock_profile="none",
    )
    compiler_pass = CompilerPassRecord(
        pass_ref=pass_ref,
        pass_name="platform_source_lineage_from_current_qro",
        input_ir_refs=(),
        output_ir_ref=ir_ref,
        input_qro_refs=(qro_ref,),
        graph_command_refs=(graph_ref,),
        canonical_command_refs=canonical,
        actor=OWNER,
        actor_source=ActorSource.USER_MANUAL,
        entry_source=EntrySource.API,
        permission_ref=ir.permission_ref,
        tool_record_refs=(
            f"endpoint:{ENTRYPOINT}",
            f"entrypoint:{ENTRYPOINT}",
        ),
        evidence_refs=ir.evidence_refs,
        validation_refs=ir.validation_refs,
        deterministic_run_plan_ref=ir.deterministic_run_plan_ref,
        rollback_ref=ir.rollback_ref,
    )
    compiler.record_ir(ir)
    compiler.record_pass(compiler_pass)
    return ir, compiler_pass


def _source_resolver(
    *,
    graph: PersistentResearchGraphStore,
    compiler: PersistentCompilerIRStore,
    validations: PersistentGoalValidationReceiptRegistry,
    rag: PersistentResearchAssetRAGIndex,
    lifecycle: _LifecycleRegistry,
    math: _MathRegistry,
) -> RealPlatformTypedSourceResolver:
    def load_projection(ref: str, owner: str, record: Any):
        matches = [
            item
            for item in graph.projection_index(owner=owner)
            if item.projection_ref == ref
        ]
        if len(matches) != 1:
            raise LookupError("projection missing or ambiguous")
        projection = matches[0]
        if (
            projection.qro_id != record.qro_ref
            or projection.command_id != record.research_graph_ref
        ):
            raise LookupError("projection/QRO/Graph recombination")
        return projection

    def validate_projection(value: Any, owner: str, record: Any) -> tuple[str, ...]:
        if (
            value.owner != owner
            or value.qro_id != record.qro_ref
            or value.command_id != record.research_graph_ref
        ):
            return ("projection owner/QRO/Graph mismatch",)
        return ()

    def validate_row(
        record: Any,
        owner: str,
        values: dict[str, Any],
    ) -> tuple[str, ...]:
        projection = values.get("typed_canvas_projection_ref")
        if projection is None:
            return ("M15 projection is absent",)
        try:
            lifecycle_record = lifecycle.load(record.lifecycle_ref, owner, record)
            chain = math.verified_chain(record.math_spine_ref, owner=owner)
        except Exception as exc:
            return (f"M15 lifecycle/math lookup failed:{type(exc).__name__}",)
        violations = []
        if lifecycle_record.qro_ref != record.qro_ref:
            violations.append("M15 lifecycle/QRO mismatch")
        if chain.qro_ref != record.qro_ref:
            violations.append("M15 math/QRO mismatch")
        if projection.qro_id != record.qro_ref:
            violations.append("M15 projection/QRO mismatch")
        return tuple(violations)

    return RealPlatformTypedSourceResolver(
        research_graph_store=graph,
        lifecycle_loaders=(lifecycle.load,),
        goal_validation_receipt_registry=validations,
        rag_index=rag,
        spine_chain_registry=math,
        compiler_store=compiler,
        specific_adapters={
            (ROW, "typed_canvas_projection_ref"): PlatformTypedSourceAdapter(
                source_kind="research_graph_current_projection",
                load=load_projection,
                validate_linkage=validate_projection,
            )
        },
        row_validators={ROW: validate_row},
    )


def _wire_system(
    root: Path,
    *,
    graph: PersistentResearchGraphStore,
    compiler: PersistentCompilerIRStore,
    validations: PersistentGoalValidationReceiptRegistry,
    rag: PersistentResearchAssetRAGIndex,
    lifecycle: _LifecycleRegistry,
    math: _MathRegistry,
    selection: PlatformSourceLineageSelection,
    record_rag_document=None,
) -> _System:
    resolver = _source_resolver(
        graph=graph,
        compiler=compiler,
        validations=validations,
        rag=rag,
        lifecycle=lifecycle,
        math=math,
    )
    strict_ref_resolver = build_real_ref_resolver(
        research_graph_store=graph,
        lifecycle_registry=lifecycle,
        governance_registry=None,
        rag_index=rag,
        spine_chain_registry=math,
        compiler_store=compiler,
        goal_validation_receipt_registry=validations,
        lifecycle_loaders=(lifecycle.load_for_coverage,),
    )
    entrypoints = PersistentGoalEntrypointCoverageRegistry(
        root / "goal_entrypoint_coverage.jsonl",
        resolver=strict_ref_resolver,
    )
    producer = PlatformSourceLineageProducer(
        research_graph_store=graph,
        compiler_store=compiler,
        goal_validation_receipt_registry=validations,
        entrypoint_registry=entrypoints,
        rag_index=rag,
        source_resolver=resolver,
        record_coverage=entrypoints.record_coverage,
        record_rag_document=record_rag_document or rag.add_for_owner,
    )
    return _System(
        root=root,
        graph=graph,
        compiler=compiler,
        validations=validations,
        entrypoints=entrypoints,
        rag=rag,
        lifecycle=lifecycle,
        math=math,
        resolver=resolver,
        producer=producer,
        selection=selection,
    )


def _build_system(
    root: Path,
    *,
    outcome: GoalValidationOutcome = GoalValidationOutcome.PASSED,
    record_rag_document=None,
    compiler_math_spine_ref: str = MATH_REF,
    compiler_evidence_ref: str | None = None,
) -> _System:
    graph = PersistentResearchGraphStore(root / "research_graph.jsonl")
    qro = _qro()
    command = _record_graph_qro(graph, qro)
    projection = graph.projection_index(owner=OWNER)[0]
    compiler = _LegacyTestCompilerStore(root / "compiler.jsonl")
    validations = PersistentGoalValidationReceiptRegistry(
        root / "goal_validation_receipts.jsonl"
    )
    receipt = _record_receipt(
        validations,
        qro_ref=qro.qro_id,
        graph_ref=command.command_id,
        outcome=outcome,
    )
    lifecycle = _LifecycleRegistry(
        _LifecycleRecord(
            lifecycle_ref=LIFECYCLE_REF,
            owner_user_id=OWNER,
            recorded_by=OWNER,
            qro_ref=qro.qro_id,
        )
    )
    math = _MathRegistry(
        _MathChain(
            chain_ref=MATH_REF,
            owner_user_id=OWNER,
            qro_ref=qro.qro_id,
        )
    )
    rag = PersistentResearchAssetRAGIndex(root / "research_asset_rag.jsonl")
    selection = PlatformSourceLineageSelection(
        m_row=ROW,
        qro_ref=qro.qro_id,
        lifecycle_ref=LIFECYCLE_REF,
        math_spine_ref=MATH_REF,
        specific_refs=(
            PlatformSpecificRef(
                key="typed_canvas_projection_ref",
                ref=projection.projection_ref,
            ),
        ),
    )
    derived_evidence_ref = EVIDENCE_REF
    if outcome is GoalValidationOutcome.PASSED:
        precompiler_resolver = _source_resolver(
            graph=graph,
            compiler=compiler,
            validations=validations,
            rag=rag,
            lifecycle=lifecycle,
            math=math,
        )
        derived_evidence_ref = derive_platform_source_lineage_evidence(
            source_resolver=precompiler_resolver,
            owner_user_id=OWNER,
            m_row=ROW,
            entry_source=EntrySource.API.value,
            entrypoint_ref=ENTRYPOINT,
            qro_ref=qro.qro_id,
            research_graph_ref=command.command_id,
            lifecycle_ref=LIFECYCLE_REF,
            governance_ref=receipt.validation_ref,
            math_spine_ref=MATH_REF,
            specific_refs=selection.specific_refs,
        ).evidence_ref
    _record_compiler_lineage(
        compiler,
        qro_ref=qro.qro_id,
        graph_ref=command.command_id,
        receipt_ref=receipt.validation_ref,
        math_spine_ref=compiler_math_spine_ref,
        evidence_ref=compiler_evidence_ref or derived_evidence_ref,
    )
    return _wire_system(
        root,
        graph=graph,
        compiler=compiler,
        validations=validations,
        rag=rag,
        lifecycle=lifecycle,
        math=math,
        selection=selection,
        record_rag_document=record_rag_document,
    )


def _reload(system: _System) -> _System:
    return _wire_system(
        system.root,
        graph=PersistentResearchGraphStore(system.root / "research_graph.jsonl"),
        compiler=_LegacyTestCompilerStore(system.root / "compiler.jsonl"),
        validations=PersistentGoalValidationReceiptRegistry(
            system.root / "goal_validation_receipts.jsonl"
        ),
        rag=PersistentResearchAssetRAGIndex(system.rag_path),
        lifecycle=system.lifecycle,
        math=system.math,
        selection=system.selection,
    )


def _nonempty_rows(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def test_platform_source_lineage_derives_strict_coverage_rag_and_source_certification(
    tmp_path,
):
    system = _build_system(tmp_path)

    result = system.producer.record_current(
        owner_user_id=OWNER,
        selection=system.selection,
    )

    assert {field.name for field in fields(PlatformSourceLineageSelection)} == {
        "m_row",
        "qro_ref",
        "lifecycle_ref",
        "math_spine_ref",
        "specific_refs",
    }
    assert result.coverage.goal_sections == ("§14",)
    assert result.coverage.qro_refs == (system.selection.qro_ref,)
    assert len(result.coverage.research_graph_command_refs) == 1
    assert len(result.coverage.compiler_ir_refs) == 1
    assert len(result.coverage.compiler_pass_refs) == 1
    assert len(
        [
            ref
            for ref in result.coverage.validation_refs
            if ref.startswith("goal_validation_receipt:")
        ]
    ) == 1
    assert result.coverage.coverage_ref.startswith("goal_entrypoint_coverage:")
    assert result.evidence_record.evidence_ref == (
        result.evidence_record.canonical_evidence_ref
    )
    assert result.coverage.evidence_refs == (
        result.evidence_record.evidence_ref,
    )
    assert EVIDENCE_REF not in result.coverage.evidence_refs
    assert system.producer.evidence_registry.evidence(
        result.evidence_record.evidence_ref,
        owner_user_id=OWNER,
    ) == result.evidence_record
    assert system.compiler.ir(
        result.coverage.compiler_ir_refs[0],
        owner=OWNER,
    ).evidence_refs == result.coverage.evidence_refs
    assert result.capability_record.governance_ref in result.coverage.validation_refs
    assert result.capability_record.rag_ref == result.rag_document.document_id
    capability_metadata = result.rag_document.metadata["platform_capability"]
    assert set(capability_metadata) == {
        "schema_version",
        "m_row",
        "source_coverage_ref",
        "qro_ref",
        "research_graph_ref",
        "lifecycle_ref",
        "governance_ref",
        "math_spine_ref",
        "evidence_refs",
        "specific_refs",
    }
    assert capability_metadata["source_coverage_ref"] == result.coverage.coverage_ref
    assert capability_metadata["specific_refs"] == {
        "typed_canvas_projection_ref": system.selection.specific_refs[0].ref
    }

    sources = system.source_registry()
    certification = sources.record_current(
        owner_user_id=OWNER,
        m_row=ROW,
        source_coverage_ref=result.coverage.coverage_ref,
        rag_ref=result.rag_document.document_id,
    )
    assert sources.resolve_current_row(
        ROW,
        owner_user_id=OWNER,
    ) == certification.resolved_row
    assert certification.resolved_row.record == result.capability_record


def test_platform_source_lineage_restarts_idempotently_and_revalidates_drift(tmp_path):
    system = _build_system(tmp_path)
    first = system.producer.record_current(
        owner_user_id=OWNER,
        selection=system.selection,
    )
    sources = system.source_registry()
    certification = sources.record_current(
        owner_user_id=OWNER,
        m_row=ROW,
        source_coverage_ref=first.coverage.coverage_ref,
        rag_ref=first.rag_document.document_id,
    )

    reloaded = _reload(system)
    second = reloaded.producer.record_current(
        owner_user_id=OWNER,
        selection=reloaded.selection,
    )
    assert second == first
    assert len(_nonempty_rows(reloaded.evidence_path)) == 1
    assert len(_nonempty_rows(reloaded.coverage_path)) == 1
    assert len(_nonempty_rows(reloaded.rag_path)) == 1

    reloaded_sources = reloaded.source_registry()
    assert reloaded_sources.certification(
        certification.certification_ref,
        owner_user_id=OWNER,
    ) == certification
    assert reloaded_sources.resolve_current_row(
        ROW,
        owner_user_id=OWNER,
    ) == certification.resolved_row

    key = (OWNER, LIFECYCLE_REF)
    old = reloaded.lifecycle.records[key]
    reloaded.lifecycle.records[key] = replace(old, revision="v2")
    evidence_decision = reloaded.producer.evidence_registry.validate_current(
        first.evidence_record,
        owner_user_id=OWNER,
    )
    assert not evidence_decision.accepted
    assert "platform_source_evidence_drifted" in {
        item.code for item in evidence_decision.violations
    }
    with pytest.raises(PlatformRowSourceError, match="not strictly backed"):
        reloaded_sources.resolve_current_row(ROW, owner_user_id=OWNER)


def test_platform_source_lineage_rejects_corrupt_gate_without_writes(tmp_path):
    system = _build_system(tmp_path, outcome=GoalValidationOutcome.FAILED)

    with pytest.raises(PlatformSourceLineageError, match="GOAL validation receipt"):
        system.producer.record_current(
            owner_user_id=OWNER,
            selection=system.selection,
        )

    assert not system.coverage_path.exists()
    assert not system.rag_path.exists()


def test_platform_source_lineage_rejects_compiler_only_evidence_without_writes(
    tmp_path,
):
    system = _build_system(
        tmp_path,
        compiler_evidence_ref=EVIDENCE_REF,
    )

    with pytest.raises(
        PlatformSourceLineageError,
        match="independently derived content-bound evidence ref",
    ):
        system.producer.record_current(
            owner_user_id=OWNER,
            selection=system.selection,
        )

    assert not system.evidence_path.exists()
    assert not system.coverage_path.exists()
    assert not system.rag_path.exists()


def test_platform_source_evidence_rejects_owner_tamper_and_missing_compiler_citation(
    tmp_path,
):
    system = _build_system(tmp_path)
    result = system.producer.record_current(
        owner_user_id=OWNER,
        selection=system.selection,
    )
    evidence = result.evidence_record

    with pytest.raises(KeyError):
        system.producer.evidence_registry.evidence(
            evidence.evidence_ref,
            owner_user_id=OTHER_OWNER,
        )
    tampered = replace(
        evidence,
        lifecycle_ref="desk_topology_receipt:tampered:v1",
    )
    tampered_decision = system.producer.evidence_registry.validate_current(
        tampered,
        owner_user_id=OWNER,
    )
    assert not tampered_decision.accepted
    assert "platform_source_evidence_identity_mismatch" in {
        item.code for item in tampered_decision.violations
    }
    with pytest.raises(ValueError, match="identity_mismatch"):
        system.producer.evidence_registry.record_evidence(tampered)

    empty_compiler = _LegacyTestCompilerStore(tmp_path / "empty_compiler.jsonl")
    resolver_without_citation = build_real_ref_resolver(
        research_graph_store=system.graph,
        lifecycle_registry=system.lifecycle,
        governance_registry=None,
        rag_index=system.rag,
        spine_chain_registry=system.math,
        compiler_store=empty_compiler,
        goal_validation_receipt_registry=system.validations,
        platform_source_evidence_registry=system.producer.evidence_registry,
        lifecycle_loaders=(system.lifecycle.load_for_coverage,),
        owner=OWNER,
    )
    assert resolver_without_citation.has_evidence(evidence.evidence_ref)
    assert not resolver_without_citation.has_platform_evidence(
        result.capability_record,
        evidence.evidence_ref,
    )


def test_platform_source_lineage_rejects_same_owner_recombination_without_writes(
    tmp_path,
):
    system = _build_system(tmp_path)
    other_qro = _qro(suffix="unrelated")
    _record_graph_qro(system.graph, other_qro)
    other_projection = next(
        item
        for item in system.graph.projection_index(owner=OWNER)
        if item.qro_id == other_qro.qro_id
    )
    recombined = replace(
        system.selection,
        specific_refs=(
            PlatformSpecificRef(
                key="typed_canvas_projection_ref",
                ref=other_projection.projection_ref,
            ),
        ),
    )

    with pytest.raises(PlatformSourceLineageError, match="current Research Graph projection"):
        system.producer.record_current(
            owner_user_id=OWNER,
            selection=recombined,
        )

    assert not system.coverage_path.exists()
    assert not system.rag_path.exists()


def test_platform_source_lineage_rejects_row_linkage_corruption_without_writes(
    tmp_path,
):
    system = _build_system(tmp_path)
    key = (OWNER, MATH_REF)
    system.math.chains[key] = replace(
        system.math.chains[key],
        qro_ref="qro:unrelated-math-lineage",
    )

    with pytest.raises(PlatformSourceLineageError, match="math/QRO mismatch"):
        system.producer.record_current(
            owner_user_id=OWNER,
            selection=system.selection,
        )

    assert not system.coverage_path.exists()
    assert not system.rag_path.exists()


def test_platform_source_lineage_uses_current_head_and_ignores_historical_lineage(
    tmp_path,
):
    system = _build_system(tmp_path)
    old_graph_ref = system.graph.commands()[0].command_id
    current_command = _record_graph_qro(
        system.graph,
        system.graph.qro(system.selection.qro_ref),
        timestamp="2099-01-01T00:00:00+00:00",
    )
    current_projection = next(
        item
        for item in system.graph.projection_index(owner=OWNER)
        if item.qro_id == system.selection.qro_ref
    )
    current_receipt = _record_receipt(
        system.validations,
        qro_ref=system.selection.qro_ref,
        graph_ref=current_command.command_id,
        outcome=GoalValidationOutcome.PASSED,
    )
    current_selection = replace(
        system.selection,
        specific_refs=(
            PlatformSpecificRef(
                key="typed_canvas_projection_ref",
                ref=current_projection.projection_ref,
            ),
        ),
    )
    current_evidence_ref = derive_platform_source_lineage_evidence(
        source_resolver=system.resolver,
        owner_user_id=OWNER,
        m_row=ROW,
        entry_source=EntrySource.API.value,
        entrypoint_ref=ENTRYPOINT,
        qro_ref=system.selection.qro_ref,
        research_graph_ref=current_command.command_id,
        lifecycle_ref=LIFECYCLE_REF,
        governance_ref=current_receipt.validation_ref,
        math_spine_ref=MATH_REF,
        specific_refs=current_selection.specific_refs,
    ).evidence_ref
    current_ir, current_pass = _record_compiler_lineage(
        system.compiler,
        qro_ref=system.selection.qro_ref,
        graph_ref=current_command.command_id,
        receipt_ref=current_receipt.validation_ref,
        suffix="current_head",
        evidence_ref=current_evidence_ref,
    )

    result = system.producer.record_current(
        owner_user_id=OWNER,
        selection=current_selection,
    )

    assert old_graph_ref != current_command.command_id
    assert result.coverage.research_graph_command_refs == (
        current_command.command_id,
    )
    assert result.coverage.compiler_ir_refs == (current_ir.ir_ref,)
    assert result.coverage.compiler_pass_refs == (current_pass.pass_ref,)
    assert len(_nonempty_rows(system.coverage_path)) == 1
    assert len(_nonempty_rows(system.rag_path)) == 1


def test_platform_source_lineage_rejects_stale_projection_without_writes(tmp_path):
    system = _build_system(tmp_path)
    stale_selection = system.selection
    _record_graph_qro(
        system.graph,
        system.graph.qro(system.selection.qro_ref),
        timestamp="2099-01-01T00:00:00+00:00",
    )

    with pytest.raises(
        PlatformSourceLineageError,
        match="unique current Research Graph projection",
    ):
        system.producer.record_current(
            owner_user_id=OWNER,
            selection=stale_selection,
        )

    assert not system.coverage_path.exists()
    assert not system.rag_path.exists()


def test_platform_source_lineage_rejects_unbound_same_owner_math_without_writes(
    tmp_path,
):
    system = _build_system(tmp_path)
    unrelated_math_ref = "math_spine_chain:desk_topology:unrelated"
    system.math.chains[(OWNER, unrelated_math_ref)] = _MathChain(
        chain_ref=unrelated_math_ref,
        owner_user_id=OWNER,
        qro_ref=system.selection.qro_ref,
    )
    recombined = replace(
        system.selection,
        math_spine_ref=unrelated_math_ref,
    )

    with pytest.raises(
        PlatformSourceLineageError,
        match="selected QRO must bind exactly",
    ):
        system.producer.record_current(
            owner_user_id=OWNER,
            selection=recombined,
        )

    assert not system.coverage_path.exists()
    assert not system.rag_path.exists()


def test_platform_source_lineage_rejects_compiler_ir_math_recombination_without_writes(
    tmp_path,
):
    system = _build_system(
        tmp_path,
        compiler_math_spine_ref="math_spine_chain:desk_topology:unrelated",
    )

    with pytest.raises(
        PlatformSourceLineageError,
        match="selected compiler IR must bind exactly",
    ):
        system.producer.record_current(
            owner_user_id=OWNER,
            selection=system.selection,
        )

    assert not system.coverage_path.exists()
    assert not system.rag_path.exists()


def test_platform_source_lineage_rejects_ambiguous_compiler_lineage_without_writes(
    tmp_path,
):
    system = _build_system(tmp_path)
    receipt_ref = system.validations.receipts(owner_user_id=OWNER)[0].validation_ref
    graph_ref = system.graph.commands()[0].command_id
    _record_compiler_lineage(
        system.compiler,
        qro_ref=system.selection.qro_ref,
        graph_ref=graph_ref,
        receipt_ref=receipt_ref,
        suffix="second_current",
    )

    with pytest.raises(PlatformSourceLineageError, match="exactly one current"):
        system.producer.record_current(
            owner_user_id=OWNER,
            selection=system.selection,
        )

    assert not system.coverage_path.exists()
    assert not system.rag_path.exists()


def test_platform_source_lineage_rejects_unproven_row_rag_contract_before_writes(
    tmp_path,
):
    system = _build_system(tmp_path)
    unsupported = replace(
        system.selection,
        m_row="M3",
        specific_refs=(
            PlatformSpecificRef(
                key="ingestion_skill_ref",
                ref="ingestion_skill:unsupported-row-proof",
            ),
            PlatformSpecificRef(
                key="instrument_spec_ref",
                ref="instrument_spec:unsupported-row-proof",
            ),
        ),
    )

    with pytest.raises(PlatformSourceLineageError, match="only proven for M15"):
        system.producer.record_current(
            owner_user_id=OWNER,
            selection=unsupported,
        )

    assert not system.coverage_path.exists()
    assert not system.rag_path.exists()


def test_platform_source_lineage_enforces_owner_isolation(tmp_path):
    system = _build_system(tmp_path)

    with pytest.raises(PlatformSourceLineageError, match="owner mismatch"):
        system.producer.record_current(
            owner_user_id=OTHER_OWNER,
            selection=system.selection,
        )
    assert system.entrypoints.records(owner=OTHER_OWNER) == []
    assert system.rag.owned_documents(owner_user_id=OTHER_OWNER) == []

    accepted = system.producer.record_current(
        owner_user_id=OWNER,
        selection=system.selection,
    )
    assert accepted.coverage.recorded_by == OWNER


def test_platform_source_lineage_reports_non_atomic_callback_failure_and_retries(
    tmp_path,
):
    def fail_rag(*_args, **_kwargs):
        raise OSError("simulated RAG ledger failure")

    system = _build_system(tmp_path, record_rag_document=fail_rag)
    with pytest.raises(PlatformSourceLineageCommitError) as raised:
        system.producer.record_current(
            owner_user_id=OWNER,
            selection=system.selection,
        )
    assert raised.value.coverage_persisted is True
    assert raised.value.rag_persisted is False
    assert raised.value.evidence_persisted is True
    assert len(_nonempty_rows(system.evidence_path)) == 1
    assert len(_nonempty_rows(system.coverage_path)) == 1
    assert not system.rag_path.exists()

    retry = _wire_system(
        tmp_path,
        graph=system.graph,
        compiler=system.compiler,
        validations=system.validations,
        rag=system.rag,
        lifecycle=system.lifecycle,
        math=system.math,
        selection=system.selection,
    )
    result = retry.producer.record_current(
        owner_user_id=OWNER,
        selection=system.selection,
    )
    assert result.coverage.coverage_ref
    assert len(_nonempty_rows(system.coverage_path)) == 1
    assert len(_nonempty_rows(system.rag_path)) == 1


def test_platform_source_lineage_detects_compiler_change_during_commit(tmp_path):
    system = _build_system(tmp_path)
    receipt_ref = system.validations.receipts(owner_user_id=OWNER)[0].validation_ref
    graph_ref = system.graph.commands()[0].command_id

    def record_rag_then_change_lineage(document, **kwargs):
        stored = system.rag.add_for_owner(document, **kwargs)
        _record_compiler_lineage(
            system.compiler,
            qro_ref=system.selection.qro_ref,
            graph_ref=graph_ref,
            receipt_ref=receipt_ref,
            suffix="concurrent_change",
        )
        return stored

    concurrent = _wire_system(
        tmp_path,
        graph=system.graph,
        compiler=system.compiler,
        validations=system.validations,
        rag=system.rag,
        lifecycle=system.lifecycle,
        math=system.math,
        selection=system.selection,
        record_rag_document=record_rag_then_change_lineage,
    )

    with pytest.raises(PlatformSourceLineageCommitError) as raised:
        concurrent.producer.record_current(
            owner_user_id=OWNER,
            selection=system.selection,
        )
    assert raised.value.coverage_persisted is True
    assert raised.value.rag_persisted is True
    assert "exactly one current" in str(raised.value)


def test_platform_source_lineage_detects_projection_change_during_commit(tmp_path):
    system = _build_system(tmp_path)

    def record_rag_then_change_projection(document, **kwargs):
        stored = system.rag.add_for_owner(document, **kwargs)
        _record_graph_qro(
            system.graph,
            system.graph.qro(system.selection.qro_ref),
            timestamp="2099-01-01T00:00:00+00:00",
        )
        return stored

    concurrent = _wire_system(
        tmp_path,
        graph=system.graph,
        compiler=system.compiler,
        validations=system.validations,
        rag=system.rag,
        lifecycle=system.lifecycle,
        math=system.math,
        selection=system.selection,
        record_rag_document=record_rag_then_change_projection,
    )

    with pytest.raises(PlatformSourceLineageCommitError) as raised:
        concurrent.producer.record_current(
            owner_user_id=OWNER,
            selection=system.selection,
        )
    assert raised.value.coverage_persisted is True
    assert raised.value.rag_persisted is True
    assert "current Research Graph projection" in str(raised.value)
