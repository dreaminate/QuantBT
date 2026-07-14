from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest

from app.research_os.compiler import (
    COMPILER_ARTIFACT_PROOF_CODEC,
    COMPILER_IR_PROOF_CODEC,
    COMPILER_PASS_PROOF_CODEC,
    CompilerArtifactRecord,
    CompilerIRRecord,
    CompilerPassRecord,
    PersistentCompilerIRStore,
)
from app.research_os.entrypoint_evidence import (
    ENTRYPOINT_EVIDENCE_PROOF_CODEC,
    EntrypointEvidenceRecord,
    PersistentEntrypointEvidenceRegistry,
)
from app.research_os.goal_proof_ledger import (
    GoalProofLedger,
    InvalidationTarget,
    ProofBundle,
    ProofMember,
)
from app.research_os.goal_proof_records import (
    LOGICAL_TYPE_VALIDATION_RECEIPT,
    GoalProofRecordProjection,
    GoalProofRecordProjectionError,
    normalize_proof_record,
    proof_record_member,
    typed_proof_record_member,
)
from app.research_os.goal_validation_receipts import (
    GOAL_VALIDATION_RECEIPT_PROOF_CODEC,
    GoalValidationOutcome,
    GoalValidationReceipt,
    PersistentGoalValidationReceiptRegistry,
)
from app.research_os.spine import (
    ActorSource,
    EntrySource,
    QRORecord,
    QROType,
    ResearchGraphCommand,
    ResearchGraphStore,
    RuntimeStatus,
)


OWNER = "owner:goal-proof-projection"
ENTRYPOINT_REF = "api:goal-proof-projection:v1"


def _graph_source() -> tuple[ResearchGraphStore, QRORecord, ResearchGraphCommand]:
    graph = ResearchGraphStore()
    qro = QRORecord(
        qro_type=QROType.QUANT_INTENT,
        owner=OWNER,
        actor=ActorSource.USER_MANUAL,
        input_contract={"request_ref": "request:goal-proof-projection:v1"},
        output_contract={"result_ref": "result:goal-proof-projection:v1"},
        market="crypto",
        universe="BTCUSDT",
        horizon="1d",
        frequency="1m",
        lineage=("request:goal-proof-projection:v1",),
        implementation_hash="implementation:goal-proof-projection:v1",
        assumptions=("The projection fixture is offline and deterministic.",),
        known_limits=("The projection fixture does not execute an order.",),
        failure_modes=("The canonical proof bundle can be invalidated.",),
        validation_plan=("Reopen every typed record from SQLite.",),
        evidence_refs=("source_evidence:goal-proof-projection:v1",),
        permission="research.goal_proof_projection:user_manual",
        runtime_status=RuntimeStatus.OFFLINE,
        allowed_environment=RuntimeStatus.OFFLINE,
    )
    command = ResearchGraphCommand(
        source=EntrySource.API,
        command_type="upsert_qro",
        actor_source=ActorSource.USER_MANUAL,
        actor=OWNER,
        payload={"qro": qro},
        evidence_refs=qro.evidence_refs,
        tool_record_refs=(ENTRYPOINT_REF,),
        timestamp="2026-07-14T00:00:00+00:00",
    )
    assert graph.apply(command) == command.command_id
    return graph, qro, command


def _receipt(
    qro: QRORecord,
    command: ResearchGraphCommand,
    **overrides: object,
) -> GoalValidationReceipt:
    values: dict[str, object] = {
        "validation_ref": "",
        "owner_user_id": OWNER,
        "subject_qro_refs": (qro.qro_id,),
        "graph_command_refs": (command.command_id,),
        "validator_identifiers": ("validator:goal-proof-bundle:v1",),
        "test_identifiers": ("runtime_check:goal-proof-bundle:v1",),
        "outcome": GoalValidationOutcome.PASSED,
        "evidence_refs": ("validation_report:goal-proof-bundle:v1",),
        "evidence_digests": ("sha256:" + "a" * 64,),
        "residuals": (),
    }
    values.update(overrides)
    provisional = GoalValidationReceipt(**values)  # type: ignore[arg-type]
    return replace(
        provisional,
        validation_ref=provisional.canonical_validation_ref,
    )


def _compiler_records(
    qro: QRORecord,
    command: ResearchGraphCommand,
    receipt: GoalValidationReceipt,
    evidence: EntrypointEvidenceRecord,
) -> tuple[CompilerIRRecord, CompilerPassRecord, CompilerArtifactRecord]:
    ir = CompilerIRRecord(
        ir_ref="compiler_ir:goal-proof-projection:v1",
        source_qro_refs=(qro.qro_id,),
        graph_command_refs=(command.command_id,),
        canonical_command_refs=(ENTRYPOINT_REF,),
        node_refs=(f"qro:{qro.qro_id}",),
        edge_refs=(),
        artifact_refs=(),
        theory_binding_refs=("theory_binding:goal-proof-projection:v1",),
        consistency_check_refs=("consistency_check:goal-proof-projection:v1",),
        evidence_refs=(evidence.evidence_ref,),
        validation_refs=(receipt.validation_ref,),
        permission_ref=qro.permission,
        deterministic_run_plan_ref="runplan:goal-proof-projection:v1",
        rollback_ref="rollback:goal-proof-projection:v1",
        environment_lock_ref="environment_lock:goal-proof-projection:v1",
        mathematical_spine_chain_refs=(
            "mathematical_spine_chain:goal-proof-projection:v1",
        ),
        owner=OWNER,
        target_runtime=RuntimeStatus.OFFLINE,
    )
    compiler_pass = CompilerPassRecord(
        pass_ref="compiler_pass:goal-proof-projection:v1",
        pass_name="goal_proof_projection_qro_to_ir",
        input_ir_refs=(),
        output_ir_ref=ir.ir_ref,
        input_qro_refs=(qro.qro_id,),
        graph_command_refs=(command.command_id,),
        canonical_command_refs=(ENTRYPOINT_REF,),
        actor=OWNER,
        actor_source=ActorSource.USER_MANUAL,
        entry_source=EntrySource.API,
        permission_ref=qro.permission,
        tool_record_refs=(ENTRYPOINT_REF,),
        evidence_refs=(evidence.evidence_ref,),
        validation_refs=(receipt.validation_ref,),
        deterministic_run_plan_ref=ir.deterministic_run_plan_ref,
        rollback_ref=ir.rollback_ref,
    )
    artifact = CompilerArtifactRecord(
        artifact_ref="compiler_artifact:goal-proof-projection:v1",
        artifact_kind="deterministic_run_plan_manifest",
        source_ir_refs=(ir.ir_ref,),
        compiler_pass_refs=(compiler_pass.pass_ref,),
        graph_command_refs=(command.command_id,),
        canonical_command_refs=(ENTRYPOINT_REF,),
        deterministic_run_plan_ref=ir.deterministic_run_plan_ref,
        environment_lock_ref=ir.environment_lock_ref,
        permission_ref=ir.permission_ref,
        output_contract_ref="output_contract:goal-proof-projection:v1",
        manifest_hash="sha256:" + "b" * 64,
        evidence_refs=(evidence.evidence_ref,),
        validation_refs=(receipt.validation_ref,),
        mathematical_spine_chain_refs=ir.mathematical_spine_chain_refs,
        owner=OWNER,
        target_runtime=RuntimeStatus.OFFLINE,
    )
    return ir, compiler_pass, artifact


def _prepare_evidence(
    root: Path,
    graph: ResearchGraphStore,
    qro: QRORecord,
    command: ResearchGraphCommand,
    receipt: GoalValidationReceipt,
) -> EntrypointEvidenceRecord:
    compiler = PersistentCompilerIRStore(root / "preparer_compiler.jsonl")
    validations = PersistentGoalValidationReceiptRegistry(
        root / "preparer_receipts.jsonl"
    )
    evidence = PersistentEntrypointEvidenceRegistry(
        root / "preparer_evidence.jsonl",
        research_graph_store=graph,
        compiler_store=compiler,
        validation_receipt_registry=validations,
    )
    return evidence.prepare_record_from_receipt_candidate(
        validation_receipt_candidate=receipt,
        owner_user_id=OWNER,
        entry_source=EntrySource.API.value,
        entrypoint_ref=ENTRYPOINT_REF,
        goal_sections=("§0", "§1", "§8"),
        qro_ref=qro.qro_id,
        research_graph_ref=command.command_id,
        compiler_ir_ref="compiler_ir:goal-proof-projection:v1",
        compiler_pass_ref="compiler_pass:goal-proof-projection:v1",
        coverage_ref="goal_entrypoint_coverage:goal-proof-projection:v1",
        actor_source=ActorSource.USER_MANUAL.value,
        pass_name="goal_proof_projection_qro_to_ir",
        permission_ref=qro.permission,
        environment_lock_ref="environment_lock:goal-proof-projection:v1",
        deterministic_run_plan_ref="runplan:goal-proof-projection:v1",
        rollback_ref="rollback:goal-proof-projection:v1",
        theory_binding_refs=("theory_binding:goal-proof-projection:v1",),
        consistency_check_refs=("consistency_check:goal-proof-projection:v1",),
        mathematical_spine_chain_refs=(
            "mathematical_spine_chain:goal-proof-projection:v1",
        ),
    )


def _bundle(
    receipt: GoalValidationReceipt,
    evidence: EntrypointEvidenceRecord,
    ir: CompilerIRRecord,
    compiler_pass: CompilerPassRecord,
    artifact: CompilerArtifactRecord,
) -> ProofBundle:
    return ProofBundle(
        owner=OWNER,
        subject="entrypoint_bundle:goal-proof-projection:v1",
        members=(
            typed_proof_record_member(
                receipt,
                codec=GOAL_VALIDATION_RECEIPT_PROOF_CODEC,
            ),
            typed_proof_record_member(
                evidence,
                codec=ENTRYPOINT_EVIDENCE_PROOF_CODEC,
                depends_on=(receipt.validation_ref,),
            ),
            typed_proof_record_member(
                ir,
                codec=COMPILER_IR_PROOF_CODEC,
                depends_on=(receipt.validation_ref, evidence.evidence_ref),
            ),
            typed_proof_record_member(
                compiler_pass,
                codec=COMPILER_PASS_PROOF_CODEC,
                depends_on=(
                    receipt.validation_ref,
                    evidence.evidence_ref,
                    ir.ir_ref,
                ),
            ),
            typed_proof_record_member(
                artifact,
                codec=COMPILER_ARTIFACT_PROOF_CODEC,
                depends_on=(
                    receipt.validation_ref,
                    evidence.evidence_ref,
                    ir.ir_ref,
                    compiler_pass.pass_ref,
                ),
            ),
        ),
        metadata={"entrypoint_ref": ENTRYPOINT_REF},
    )


def _canonical_registries(
    root: Path,
    *,
    ledger: GoalProofLedger,
    graph: ResearchGraphStore,
) -> tuple[
    PersistentCompilerIRStore,
    PersistentGoalValidationReceiptRegistry,
    PersistentEntrypointEvidenceRegistry,
    dict[Path, bytes],
]:
    compiler_path = root / "compiler.jsonl"
    receipt_path = root / "receipts.jsonl"
    evidence_path = root / "evidence.jsonl"
    for path in (compiler_path, receipt_path, evidence_path):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"")
    before = {
        path: path.read_bytes()
        for path in (compiler_path, receipt_path, evidence_path)
    }
    compiler = PersistentCompilerIRStore(
        compiler_path,
        proof_ledger=ledger,
        legacy_read_only=True,
    )
    validations = PersistentGoalValidationReceiptRegistry(
        receipt_path,
        proof_ledger=ledger,
        legacy_read_only=True,
    )
    evidence = PersistentEntrypointEvidenceRegistry(
        evidence_path,
        research_graph_store=graph,
        compiler_store=compiler,
        validation_receipt_registry=validations,
        proof_ledger=ledger,
        legacy_read_only=True,
    )
    return compiler, validations, evidence, before


def test_one_sqlite_bundle_projects_exact_records_without_legacy_writes_and_refreshes(
    tmp_path: Path,
) -> None:
    graph, qro, command = _graph_source()
    receipt = _receipt(qro, command)
    evidence_record = _prepare_evidence(tmp_path, graph, qro, command, receipt)
    ir, compiler_pass, artifact = _compiler_records(
        qro,
        command,
        receipt,
        evidence_record,
    )
    ledger = GoalProofLedger(tmp_path / "proof_ledger")
    compiler, validations, evidence, legacy_before = _canonical_registries(
        tmp_path / "canonical_readers",
        ledger=ledger,
        graph=graph,
    )

    committed = ledger.commit(
        _bundle(receipt, evidence_record, ir, compiler_pass, artifact)
    )

    assert validations.receipt(
        receipt.validation_ref,
        owner_user_id=OWNER,
    ) == receipt
    assert compiler.ir(ir.ir_ref, owner=OWNER) == ir
    assert compiler.compiler_pass(compiler_pass.pass_ref, owner=OWNER) == compiler_pass
    assert compiler.artifact(artifact.artifact_ref, owner=OWNER) == artifact
    assert evidence.evidence(
        evidence_record.evidence_ref,
        owner_user_id=OWNER,
    ) == evidence_record
    assert evidence.validate_current(
        evidence_record,
        owner_user_id=OWNER,
    ).accepted
    assert validations.is_canonical_current(receipt)
    assert compiler.is_canonical_current(ir)
    assert compiler.is_canonical_current(compiler_pass)
    assert compiler.is_canonical_current(artifact)
    assert evidence.is_canonical_current(evidence_record)
    for head in committed.heads:
        expected = {
            receipt.validation_ref: receipt,
            evidence_record.evidence_ref: evidence_record,
            ir.ir_ref: ir,
            compiler_pass.pass_ref: compiler_pass,
            artifact.artifact_ref: artifact,
        }[head.logical_ref]
        assert head.payload["record"] == normalize_proof_record(expected)
    assert {
        path: path.read_bytes() for path in legacy_before
    } == legacy_before

    invalidated = ledger.invalidate(
        owner=OWNER,
        operation_id="invalidate:goal-proof-projection:g1",
        targets=(InvalidationTarget.from_head(committed.heads[0]),),
        reason="exercise exact projection invalidation",
        subject="entrypoint_bundle:goal-proof-projection:v1",
    )
    assert len(invalidated.affected_refs) == 5
    assert validations.receipts(owner_user_id=OWNER) == []
    assert compiler.irs(owner=OWNER) == []
    assert compiler.passes(owner=OWNER) == []
    assert compiler.artifacts(owner=OWNER) == []
    assert evidence.evidences(owner_user_id=OWNER) == ()
    assert not validations.is_canonical_current(receipt)

    redeclared = ledger.commit(
        _bundle(receipt, evidence_record, ir, compiler_pass, artifact)
    )
    assert {head.generation for head in redeclared.heads} == {2}
    assert validations.receipt(
        receipt.validation_ref,
        owner_user_id=OWNER,
    ) == receipt
    assert compiler.ir(ir.ir_ref, owner=OWNER) == ir
    assert evidence.evidence(
        evidence_record.evidence_ref,
        owner_user_id=OWNER,
    ) == evidence_record
    assert {
        path: path.read_bytes() for path in legacy_before
    } == legacy_before


def test_invalidated_sqlite_heads_cannot_be_revalidated_from_identical_legacy_rows(
    tmp_path: Path,
) -> None:
    graph, qro, command = _graph_source()
    receipt = _receipt(qro, command)
    evidence_record = _prepare_evidence(tmp_path, graph, qro, command, receipt)
    ir, compiler_pass, artifact = _compiler_records(
        qro,
        command,
        receipt,
        evidence_record,
    )
    legacy_root = tmp_path / "legacy_and_canonical"
    compiler_path = legacy_root / "compiler.jsonl"
    receipt_path = legacy_root / "receipts.jsonl"
    evidence_path = legacy_root / "evidence.jsonl"
    legacy_compiler = PersistentCompilerIRStore(compiler_path)
    legacy_receipts = PersistentGoalValidationReceiptRegistry(receipt_path)
    legacy_evidence = PersistentEntrypointEvidenceRegistry(
        evidence_path,
        research_graph_store=graph,
        compiler_store=legacy_compiler,
        validation_receipt_registry=legacy_receipts,
    )
    legacy_receipts.record_receipt(receipt)
    legacy_evidence.record_evidence(evidence_record)
    legacy_compiler.record_ir(ir)
    legacy_compiler.record_pass(compiler_pass)
    legacy_compiler.record_artifact(artifact)

    ledger = GoalProofLedger(tmp_path / "proof_ledger_with_legacy_shadow")
    committed = ledger.commit(
        _bundle(receipt, evidence_record, ir, compiler_pass, artifact)
    )
    compiler = PersistentCompilerIRStore(
        compiler_path,
        proof_ledger=ledger,
        legacy_read_only=True,
    )
    validations = PersistentGoalValidationReceiptRegistry(
        receipt_path,
        proof_ledger=ledger,
        legacy_read_only=True,
    )
    evidence = PersistentEntrypointEvidenceRegistry(
        evidence_path,
        research_graph_store=graph,
        compiler_store=compiler,
        validation_receipt_registry=validations,
        proof_ledger=ledger,
        legacy_read_only=True,
    )
    assert validations.validate_validation_ref(
        receipt.validation_ref,
        owner_user_id=OWNER,
        subject_qro_refs=receipt.subject_qro_refs,
        graph_command_refs=receipt.graph_command_refs,
    ).accepted
    assert evidence.validate_current(
        evidence_record,
        owner_user_id=OWNER,
    ).accepted

    ledger.invalidate(
        owner=OWNER,
        operation_id="invalidate:legacy-shadow:g1",
        targets=(InvalidationTarget.from_head(committed.heads[0]),),
        reason="prove compatibility rows cannot revive invalidated proof",
        subject="entrypoint_bundle:goal-proof-projection:v1",
    )

    # Compatibility lookups remain available, but strict proof decisions are red.
    assert validations.receipt(
        receipt.validation_ref,
        owner_user_id=OWNER,
    ) == receipt
    assert evidence.evidence(
        evidence_record.evidence_ref,
        owner_user_id=OWNER,
    ) == evidence_record
    validation_decision = validations.validate_validation_ref(
        receipt.validation_ref,
        owner_user_id=OWNER,
        subject_qro_refs=receipt.subject_qro_refs,
        graph_command_refs=receipt.graph_command_refs,
    )
    evidence_decision = evidence.validate_current(
        evidence_record,
        owner_user_id=OWNER,
    )
    assert not validation_decision.accepted
    assert {
        item.code for item in validation_decision.violations
    } == {"goal_validation_receipt_not_canonical_current"}
    assert not evidence_decision.accepted
    assert "entrypoint_evidence_atomic_bundle_incomplete" in {
        item.code for item in evidence_decision.violations
    }


def test_entrypoint_evidence_rejects_canonical_members_split_across_bundles(
    tmp_path: Path,
) -> None:
    graph, qro, command = _graph_source()
    receipt = _receipt(qro, command)
    evidence_record = _prepare_evidence(tmp_path, graph, qro, command, receipt)
    ir, compiler_pass, artifact = _compiler_records(
        qro,
        command,
        receipt,
        evidence_record,
    )
    full_bundle = _bundle(
        receipt,
        evidence_record,
        ir,
        compiler_pass,
        artifact,
    )
    by_ref = {member.logical_ref: member for member in full_bundle.members}
    ledger = GoalProofLedger(tmp_path / "split_bundle_ledger")
    for index, logical_ref in enumerate(
        (
            receipt.validation_ref,
            evidence_record.evidence_ref,
            ir.ir_ref,
            compiler_pass.pass_ref,
            artifact.artifact_ref,
        ),
        start=1,
    ):
        ledger.commit(
            ProofBundle(
                owner=OWNER,
                subject="entrypoint_bundle:goal-proof-projection:v1",
                members=(by_ref[logical_ref],),
                metadata={"split_index": index},
            )
        )
    compiler, validations, evidence, _legacy_before = _canonical_registries(
        tmp_path / "split_bundle_readers",
        ledger=ledger,
        graph=graph,
    )

    assert validations.is_canonical_current(receipt)
    assert compiler.is_canonical_current(ir)
    assert compiler.is_canonical_current(compiler_pass)
    assert evidence.is_canonical_current(evidence_record)
    decision = evidence.validate_current(
        evidence_record,
        owner_user_id=OWNER,
    )
    assert not decision.accepted
    assert "entrypoint_evidence_atomic_bundle_recombined" in {
        item.code for item in decision.violations
    }

def test_legacy_records_remain_readable_but_never_become_canonical_and_writes_refuse(
    tmp_path: Path,
) -> None:
    graph, qro, command = _graph_source()
    receipt = _receipt(qro, command)
    legacy_validations = PersistentGoalValidationReceiptRegistry(
        tmp_path / "legacy" / "receipts.jsonl"
    )
    legacy_validations.record_receipt(receipt)
    legacy_compiler = PersistentCompilerIRStore(
        tmp_path / "legacy" / "compiler.jsonl"
    )
    preparer = PersistentEntrypointEvidenceRegistry(
        tmp_path / "legacy" / "evidence.jsonl",
        research_graph_store=graph,
        compiler_store=legacy_compiler,
        validation_receipt_registry=legacy_validations,
    )
    evidence_record = preparer.prepare_record(
        owner_user_id=OWNER,
        entry_source=EntrySource.API.value,
        entrypoint_ref=ENTRYPOINT_REF,
        goal_sections=("§0", "§1", "§8"),
        qro_ref=qro.qro_id,
        research_graph_ref=command.command_id,
        validation_ref=receipt.validation_ref,
        compiler_ir_ref="compiler_ir:goal-proof-projection:v1",
        compiler_pass_ref="compiler_pass:goal-proof-projection:v1",
        coverage_ref="goal_entrypoint_coverage:goal-proof-projection:v1",
        actor_source=ActorSource.USER_MANUAL.value,
        pass_name="goal_proof_projection_qro_to_ir",
        permission_ref=qro.permission,
        environment_lock_ref="environment_lock:goal-proof-projection:v1",
        deterministic_run_plan_ref="runplan:goal-proof-projection:v1",
        rollback_ref="rollback:goal-proof-projection:v1",
        theory_binding_refs=("theory_binding:goal-proof-projection:v1",),
        consistency_check_refs=("consistency_check:goal-proof-projection:v1",),
        mathematical_spine_chain_refs=(
            "mathematical_spine_chain:goal-proof-projection:v1",
        ),
    )
    ir, compiler_pass, artifact = _compiler_records(
        qro,
        command,
        receipt,
        evidence_record,
    )
    legacy_compiler.record_ir(ir)
    legacy_compiler.record_pass(compiler_pass)
    legacy_compiler.record_artifact(artifact)
    preparer.record_evidence(evidence_record)
    paths = (
        legacy_compiler.path,
        legacy_validations.path,
        preparer.path,
    )
    before = {path: path.read_bytes() for path in paths}

    ledger = GoalProofLedger(tmp_path / "empty_proof_ledger")
    compiler = PersistentCompilerIRStore(
        legacy_compiler.path,
        proof_ledger=ledger,
        legacy_read_only=True,
    )
    validations = PersistentGoalValidationReceiptRegistry(
        legacy_validations.path,
        proof_ledger=ledger,
        legacy_read_only=True,
    )
    evidence = PersistentEntrypointEvidenceRegistry(
        preparer.path,
        research_graph_store=graph,
        compiler_store=compiler,
        validation_receipt_registry=validations,
        proof_ledger=ledger,
        legacy_read_only=True,
    )

    assert compiler.ir(ir.ir_ref, owner=OWNER) == ir
    assert validations.receipt(receipt.validation_ref, owner_user_id=OWNER) == receipt
    assert evidence.evidence(
        evidence_record.evidence_ref,
        owner_user_id=OWNER,
    ) == evidence_record
    assert not compiler.is_canonical_current(ir)
    assert not validations.is_canonical_current(receipt)
    assert not evidence.is_canonical_current(evidence_record)
    for mutation in (
        lambda: compiler.record_ir(ir),
        lambda: compiler.record_pass(compiler_pass),
        lambda: compiler.record_artifact(artifact),
        lambda: validations.record_receipt(receipt),
        lambda: evidence.record_evidence(evidence_record),
    ):
        with pytest.raises(RuntimeError, match="atomic proof bundle required"):
            mutation()
    assert {path: path.read_bytes() for path in paths} == before


def test_malformed_projection_and_legacy_canonical_collision_fail_closed(
    tmp_path: Path,
) -> None:
    graph, qro, command = _graph_source()
    receipt = _receipt(qro, command)
    malformed_ledger = GoalProofLedger(tmp_path / "malformed_ledger")
    malformed_ledger.commit(
        ProofBundle(
            owner=OWNER,
            subject="entrypoint_bundle:malformed:v1",
            members=(
                ProofMember(
                    logical_type=LOGICAL_TYPE_VALIDATION_RECEIPT,
                    logical_ref=receipt.validation_ref,
                    payload={
                        "schema_version": "goal_proof_record.v1",
                        "logical_type": LOGICAL_TYPE_VALIDATION_RECEIPT,
                        "logical_ref": receipt.validation_ref,
                        "owner": OWNER,
                        "record": {"validation_ref": receipt.validation_ref},
                    },
                ),
            ),
        )
    )
    with pytest.raises(
        GoalProofRecordProjectionError,
        match="round-trip|decoder rejected",
    ):
        PersistentGoalValidationReceiptRegistry(
            tmp_path / "malformed_receipts.jsonl",
            proof_ledger=malformed_ledger,
        )

    evidence_record = _prepare_evidence(tmp_path, graph, qro, command, receipt)
    legacy_ir, compiler_pass, artifact = _compiler_records(
        qro,
        command,
        receipt,
        evidence_record,
    )
    legacy_path = tmp_path / "collision" / "compiler.jsonl"
    legacy = PersistentCompilerIRStore(legacy_path)
    legacy.record_ir(legacy_ir)
    canonical_ir = replace(
        legacy_ir,
        artifact_refs=("artifact:canonical-payload-differs:v1",),
    )
    collision_ledger = GoalProofLedger(tmp_path / "collision_ledger")
    collision_ledger.commit(
        ProofBundle(
            owner=OWNER,
            subject="entrypoint_bundle:collision:v1",
            members=(
                typed_proof_record_member(
                    canonical_ir,
                    codec=COMPILER_IR_PROOF_CODEC,
                ),
            ),
        )
    )
    before = legacy_path.read_bytes()
    with pytest.raises(ValueError, match="collides with legacy"):
        PersistentCompilerIRStore(
            legacy_path,
            proof_ledger=collision_ledger,
            legacy_read_only=True,
        )
    assert legacy_path.read_bytes() == before

    type_collision_ledger = GoalProofLedger(tmp_path / "type_collision_ledger")
    type_collision_ledger.commit(
        ProofBundle(
            owner=OWNER,
            subject="entrypoint_bundle:type-collision:v1",
            members=(
                proof_record_member(
                    logical_type="goal.some_other_type",
                    logical_ref=receipt.validation_ref,
                    owner=OWNER,
                    record={"value": "unrelated"},
                ),
            ),
        )
    )
    projection = GoalProofRecordProjection(type_collision_ledger)
    with pytest.raises(GoalProofRecordProjectionError, match="ref/type collision"):
        projection.current_head(
            owner=OWNER,
            logical_type=LOGICAL_TYPE_VALIDATION_RECEIPT,
            logical_ref=receipt.validation_ref,
        )
    receipt_projection = PersistentGoalValidationReceiptRegistry(
        tmp_path / "type_collision_receipts.jsonl",
        proof_ledger=type_collision_ledger,
    )
    with pytest.raises(GoalProofRecordProjectionError, match="ref/type collision"):
        receipt_projection.receipt(
            receipt.validation_ref,
            owner_user_id=OWNER,
        )

    ownerless_collision_path = tmp_path / "ownerless_type_collision.jsonl"
    ownerless_legacy = PersistentCompilerIRStore(ownerless_collision_path)
    ownerless_legacy.record_ir(legacy_ir)
    ownerless_type_ledger = GoalProofLedger(tmp_path / "ownerless_type_ledger")
    ownerless_type_ledger.commit(
        ProofBundle(
            owner=OWNER,
            subject="entrypoint_bundle:ownerless-type-collision:v1",
            members=(
                proof_record_member(
                    logical_type="goal.some_other_type",
                    logical_ref=legacy_ir.ir_ref,
                    owner=OWNER,
                    record={"value": "unrelated"},
                ),
            ),
        )
    )
    ownerless_projection = PersistentCompilerIRStore(
        ownerless_collision_path,
        proof_ledger=ownerless_type_ledger,
        legacy_read_only=True,
    )
    with pytest.raises(GoalProofRecordProjectionError, match="ref/type collision"):
        ownerless_projection.ir(legacy_ir.ir_ref)


def test_historical_ownerless_compiler_schema_is_quarantined_not_canonical(
    tmp_path: Path,
) -> None:
    graph, qro, command = _graph_source()
    receipt = _receipt(qro, command)
    evidence_record = _prepare_evidence(tmp_path, graph, qro, command, receipt)
    ir, _compiler_pass, _artifact = _compiler_records(
        qro,
        command,
        receipt,
        evidence_record,
    )
    historical = {
        "schema_version": 1,
        "event_type": "compiler_ir_recorded",
        "ir": normalize_proof_record(replace(ir, owner="")),
    }
    path = tmp_path / "historical_compiler.jsonl"
    path.write_text(
        json.dumps(
            historical,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n",
        encoding="utf-8",
    )

    compiler = PersistentCompilerIRStore(path)

    assert compiler.legacy_quarantined_counts() == {
        "irs": 1,
        "passes": 0,
        "artifacts": 0,
    }
    with pytest.raises(KeyError):
        compiler.ir(ir.ir_ref)


def test_pure_evidence_candidate_rejects_receipt_and_graph_recombination(
    tmp_path: Path,
) -> None:
    graph, qro, command = _graph_source()
    receipt = _receipt(qro, command)
    compiler = PersistentCompilerIRStore(tmp_path / "compiler.jsonl")
    validations = PersistentGoalValidationReceiptRegistry(
        tmp_path / "receipts.jsonl"
    )
    registry = PersistentEntrypointEvidenceRegistry(
        tmp_path / "evidence.jsonl",
        research_graph_store=graph,
        compiler_store=compiler,
        validation_receipt_registry=validations,
    )
    valid_kwargs = {
        "owner_user_id": OWNER,
        "entry_source": EntrySource.API.value,
        "entrypoint_ref": ENTRYPOINT_REF,
        "goal_sections": ("§0", "§1", "§8"),
        "qro_ref": qro.qro_id,
        "research_graph_ref": command.command_id,
        "compiler_ir_ref": "compiler_ir:goal-proof-projection:v1",
        "compiler_pass_ref": "compiler_pass:goal-proof-projection:v1",
        "coverage_ref": "goal_entrypoint_coverage:goal-proof-projection:v1",
        "actor_source": ActorSource.USER_MANUAL.value,
        "pass_name": "goal_proof_projection_qro_to_ir",
        "permission_ref": qro.permission,
        "environment_lock_ref": "environment_lock:goal-proof-projection:v1",
        "deterministic_run_plan_ref": "runplan:goal-proof-projection:v1",
        "rollback_ref": "rollback:goal-proof-projection:v1",
    }
    assert registry.prepare_record_from_receipt_candidate(
        validation_receipt_candidate=receipt,
        **valid_kwargs,
    ).validation_ref == receipt.validation_ref
    assert validations.receipts(owner_user_id=OWNER) == []
    assert not validations.path.exists()

    foreign_owner = _receipt(qro, command, owner_user_id="owner:foreign")
    with pytest.raises(ValueError, match="candidate owner mismatch"):
        registry.prepare_record_from_receipt_candidate(
            validation_receipt_candidate=foreign_owner,
            **valid_kwargs,
        )
    wrong_subject = _receipt(
        qro,
        command,
        subject_qro_refs=("qro:recombined",),
    )
    with pytest.raises(ValueError, match="candidate QRO subject mismatch"):
        registry.prepare_record_from_receipt_candidate(
            validation_receipt_candidate=wrong_subject,
            **valid_kwargs,
        )
    failed = _receipt(qro, command, outcome=GoalValidationOutcome.FAILED)
    with pytest.raises(ValueError, match="candidate is not passed"):
        registry.prepare_record_from_receipt_candidate(
            validation_receipt_candidate=failed,
            **valid_kwargs,
        )
    malformed_digest = _receipt(
        qro,
        command,
        evidence_digests=("sha256:not-a-digest",),
    )
    with pytest.raises(ValueError, match="candidate shape invalid"):
        registry.prepare_record_from_receipt_candidate(
            validation_receipt_candidate=malformed_digest,
            **valid_kwargs,
        )

    other_qro = replace(
        qro,
        qro_id="",
        input_contract={"request_ref": "request:other:v1"},
    )
    assert other_qro.qro_id != qro.qro_id
    other_command = ResearchGraphCommand(
        source=EntrySource.API,
        command_type="upsert_qro",
        actor_source=ActorSource.USER_MANUAL,
        actor=OWNER,
        payload={"qro": other_qro},
        evidence_refs=other_qro.evidence_refs,
        tool_record_refs=(ENTRYPOINT_REF,),
        timestamp="2026-07-14T00:00:01+00:00",
    )
    graph.apply(other_command)
    recombined_kwargs = {
        **valid_kwargs,
        "research_graph_ref": other_command.command_id,
    }
    with pytest.raises(ValueError, match="command/QRO mismatch"):
        registry.prepare_record_from_receipt_candidate(
            validation_receipt_candidate=receipt,
            **recombined_kwargs,
        )
