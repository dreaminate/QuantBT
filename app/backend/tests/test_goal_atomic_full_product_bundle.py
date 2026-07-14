from __future__ import annotations

import json
from dataclasses import asdict, replace
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.research_os.compiler import (
    CompilerIRRecord,
    CompilerPassRecord,
    PersistentCompilerIRStore,
)
from app.research_os.goal_coverage import (
    GoalEntrypointCoverageRecord,
    PersistentGoalEntrypointCoverageRegistry,
    REQUIRED_ENTRY_SOURCES,
    REQUIRED_GOAL_SECTIONS,
    goal_entrypoint_coverage_identity,
)
from app.research_os.goal_entrypoint_aggregate import (
    GoalEntrypointAggregateRecord,
    PersistentGoalEntrypointAggregateRegistry,
)
from app.research_os.goal_full_product_entrypoint import (
    FULL_PRODUCT_ATTESTATION_VALIDATOR_IDENTIFIER,
    FULL_PRODUCT_COMPILER_VERSION,
    FULL_PRODUCT_VALIDATOR_IDENTIFIER,
    GoalFullProductCandidate,
    GoalFullProductClosureSnapshot,
    GoalFullProductCommitError,
    GoalFullProductEntrypointAttestation,
    GoalFullProductEntrypointProducer,
    PersistentGoalFullProductEntrypointAttestationRegistry,
    _sha256,
)
from app.research_os.goal_proof_ledger import (
    GoalProofLedger,
    InvalidationTarget,
    ProofBundle,
)
from app.research_os.goal_proof_records import (
    GoalProofRecordProjectionError,
    proof_record_member,
)
from app.research_os.goal_validation_receipts import (
    GoalValidationOutcome,
    GoalValidationReceipt,
    PersistentGoalValidationReceiptRegistry,
)


OWNER = "owner:atomic-full-product"


class _PermissiveStrictResolver:
    """Test resolver proving existence while product code checks exact linkage."""

    def for_owner(self, owner: str) -> "_PermissiveStrictResolver":
        assert owner
        return self

    def has_qro(self, ref: str) -> bool:
        return bool(ref)

    def has_research_graph_command(self, ref: str) -> bool:
        return bool(ref)

    def has_compiler_ir(self, ref: str) -> bool:
        return bool(ref)

    def has_compiler_pass(self, ref: str) -> bool:
        return bool(ref)

    def has_evidence(self, ref: str) -> bool:
        return bool(ref)

    def has_lifecycle_record(self, ref: str) -> bool:
        return bool(ref)

    def has_rdp(self, ref: str) -> bool:
        return bool(ref)

    def entrypoint_linkage_violations(
        self,
        record: GoalEntrypointCoverageRecord,
    ) -> tuple[tuple[str, str, str], ...]:
        assert record.recorded_by
        return ()


def _candidate(source: str) -> GoalFullProductCandidate:
    qro_ref = f"qro:atomic:{source}"
    graph_ref = f"research_graph_command:atomic:{source}"
    entrypoint_ref = f"goal_full_product_entrypoint:atomic:{source}"
    ir_ref = f"compiler_ir:goal_full_product_entrypoint:atomic:{source}"
    pass_ref = f"compiler_pass:goal_full_product_entrypoint:atomic:{source}"
    coverage_ref = goal_entrypoint_coverage_identity(
        entry_source=source,
        entrypoint_ref=entrypoint_ref,
        goal_sections=REQUIRED_GOAL_SECTIONS,
        qro_refs=(qro_ref,),
        research_graph_command_refs=(graph_ref,),
        compiler_ir_refs=(ir_ref,),
        compiler_pass_refs=(pass_ref,),
    )
    provisional_attestation = GoalFullProductEntrypointAttestation(
        attestation_ref="",
        owner_user_id=OWNER,
        entry_source=source,
        base_coverage_ref=f"goal_entrypoint_coverage:base:{source}",
        base_coverage_digest="sha256:" + source.encode().hex().ljust(64, "0")[:64],
        lineage_aggregate_ref="goal_entrypoint_lineage_aggregate:atomic",
        lineage_coverage_refs=tuple(
            f"goal_entrypoint_coverage:base:{item}"
            for item in REQUIRED_ENTRY_SOURCES
        ),
        semantic_proof_refs=tuple(
            f"goal_semantic_proof:atomic:{section}"
            for section in REQUIRED_GOAL_SECTIONS
        ),
        section_snapshot_refs=tuple(
            f"goal_section_snapshot:atomic:{section}"
            for section in REQUIRED_GOAL_SECTIONS
        ),
        qro_refs=(qro_ref,),
        research_graph_command_refs=(graph_ref,),
        permission_ref=f"permission:atomic:{source}",
        lifecycle_refs=(f"lifecycle:atomic:{source}",),
        rdp_refs=(f"rdp:atomic:{source}",),
        promotion_receipt_ref=f"promotion_receipt:atomic:{source}",
        derived_entrypoint_ref=entrypoint_ref,
        derived_ir_ref=ir_ref,
        derived_pass_ref=pass_ref,
        derived_coverage_ref=coverage_ref,
    )
    attestation = replace(
        provisional_attestation,
        attestation_ref=provisional_attestation.canonical_attestation_ref,
    )
    provisional_receipt = GoalValidationReceipt(
        validation_ref="",
        owner_user_id=OWNER,
        subject_qro_refs=(qro_ref,),
        graph_command_refs=(graph_ref,),
        validator_identifiers=(
            FULL_PRODUCT_VALIDATOR_IDENTIFIER,
            FULL_PRODUCT_ATTESTATION_VALIDATOR_IDENTIFIER,
        ),
        test_identifiers=("runtime_check:atomic_full_product_bundle",),
        outcome=GoalValidationOutcome.PASSED,
        evidence_refs=(attestation.attestation_ref,),
        evidence_digests=(_sha256(attestation),),
        residuals=(),
    )
    receipt = replace(
        provisional_receipt,
        validation_ref=provisional_receipt.canonical_validation_ref,
    )
    canonical_refs = (
        f"entrypoint:{entrypoint_ref}",
        attestation.attestation_ref,
    )
    compiler_ir = CompilerIRRecord(
        ir_ref=ir_ref,
        source_qro_refs=(qro_ref,),
        graph_command_refs=(graph_ref,),
        canonical_command_refs=canonical_refs,
        node_refs=(qro_ref, f"entrypoint:{entrypoint_ref}"),
        edge_refs=(),
        artifact_refs=(),
        theory_binding_refs=(),
        consistency_check_refs=(),
        evidence_refs=(attestation.attestation_ref,),
        validation_refs=(receipt.validation_ref,),
        permission_ref=attestation.permission_ref,
        deterministic_run_plan_ref=f"deterministic_run_plan:atomic:{source}",
        rollback_ref=f"rollback:atomic:{source}",
        environment_lock_ref="environment_lock:atomic_full_product_v1",
        owner=OWNER,
        target_runtime="offline",
        compiler_version=FULL_PRODUCT_COMPILER_VERSION,
        mock_profile="none",
    )
    compiler_pass = CompilerPassRecord(
        pass_ref=pass_ref,
        pass_name="goal_full_product_entrypoint_attestation",
        input_ir_refs=(),
        output_ir_ref=ir_ref,
        input_qro_refs=(qro_ref,),
        graph_command_refs=(graph_ref,),
        canonical_command_refs=canonical_refs,
        actor=OWNER,
        actor_source="agent",
        entry_source=source,
        permission_ref=attestation.permission_ref,
        tool_record_refs=(entrypoint_ref, attestation.attestation_ref),
        evidence_refs=(attestation.attestation_ref,),
        validation_refs=(receipt.validation_ref,),
        deterministic_run_plan_ref=compiler_ir.deterministic_run_plan_ref,
        rollback_ref=compiler_ir.rollback_ref,
    )
    coverage = GoalEntrypointCoverageRecord(
        coverage_ref=coverage_ref,
        entry_source=source,
        entrypoint_ref=entrypoint_ref,
        goal_sections=REQUIRED_GOAL_SECTIONS,
        qro_refs=(qro_ref,),
        research_graph_command_refs=(graph_ref,),
        compiler_ir_refs=(ir_ref,),
        compiler_pass_refs=(pass_ref,),
        evidence_refs=(attestation.attestation_ref,),
        validation_refs=(receipt.validation_ref,),
        permission_refs=(attestation.permission_ref,),
        replay_refs=(
            f"replay:research_graph:{graph_ref}",
            f"replay:compiler_ir:{ir_ref}",
            f"replay:compiler_pass:{pass_ref}",
        ),
        canonical_command_refs=canonical_refs,
        lifecycle_refs=attestation.lifecycle_refs,
        rdp_refs=attestation.rdp_refs,
        recorded_by=OWNER,
        claims_full_product_entrypoint=True,
    )
    return GoalFullProductCandidate(
        attestation=attestation,
        validation_receipt=receipt,
        compiler_ir=compiler_ir,
        compiler_pass=compiler_pass,
        coverage=coverage,
    )


def _environment(
    root: Path,
    *,
    fault_injector=None,
) -> SimpleNamespace:
    ledger = GoalProofLedger(root / "proof_ledger", fault_injector=fault_injector)
    paths = {
        name: root / f"{name}.jsonl"
        for name in (
            "compiler",
            "receipts",
            "entrypoints",
            "attestations",
            "terminal_aggregates",
        )
    }
    for path in paths.values():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"")
    legacy_bytes = {path: path.read_bytes() for path in paths.values()}
    compiler = PersistentCompilerIRStore(
        paths["compiler"],
        proof_ledger=ledger,
        legacy_read_only=True,
    )
    receipts = PersistentGoalValidationReceiptRegistry(
        paths["receipts"],
        proof_ledger=ledger,
        legacy_read_only=True,
    )
    entrypoints = PersistentGoalEntrypointCoverageRegistry(
        paths["entrypoints"],
        resolver=_PermissiveStrictResolver(),
        proof_ledger=ledger,
        legacy_read_only=True,
    )
    inert = SimpleNamespace()
    attestations = PersistentGoalFullProductEntrypointAttestationRegistry(
        paths["attestations"],
        entrypoint_registry=entrypoints,
        lineage_aggregate_registry=inert,
        semantic_proof_registry=inert,
        section_coverage_registry=inert,
        compiler_store=compiler,
        validation_receipt_registry=receipts,
        closure_resolver=lambda _owner, _proofs: GoalFullProductClosureSnapshot(
            lifecycle_refs=("lifecycle:unused",),
            rdp_refs=("rdp:unused",),
            promotion_receipt_ref="promotion_receipt:unused",
        ),
        proof_ledger=ledger,
        legacy_read_only=True,
    )
    terminal = PersistentGoalEntrypointAggregateRegistry(
        paths["terminal_aggregates"],
        entrypoints,
        proof_ledger=ledger,
        legacy_read_only=True,
    )
    candidates = tuple(_candidate(source) for source in REQUIRED_ENTRY_SOURCES)
    attestations._prepare_current_all_unlocked = (  # type: ignore[method-assign]
        lambda *, owner_user_id: candidates
        if owner_user_id == OWNER
        else (_ for _ in ()).throw(ValueError("owner mismatch"))
    )
    producer = GoalFullProductEntrypointProducer(
        attestation_registry=attestations,
        entrypoint_registry=entrypoints,
        compiler_store=compiler,
        validation_receipt_registry=receipts,
        terminal_aggregate_registry=terminal,
        proof_ledger=ledger,
    )
    return SimpleNamespace(
        ledger=ledger,
        paths=paths,
        legacy_bytes=legacy_bytes,
        compiler=compiler,
        receipts=receipts,
        entrypoints=entrypoints,
        attestations=attestations,
        terminal=terminal,
        candidates=candidates,
        producer=producer,
    )


def _assert_legacy_bytes_unchanged(env: SimpleNamespace) -> None:
    assert {path: path.read_bytes() for path in env.legacy_bytes} == env.legacy_bytes


def test_full_product_bundle_commits_all_31_heads_and_redeclares_generation(
    tmp_path: Path,
) -> None:
    env = _environment(tmp_path)

    first = env.producer.record_current_all(owner_user_id=OWNER)

    snapshot = env.ledger.current(owner=OWNER)
    assert len(snapshot.heads) == len(REQUIRED_ENTRY_SOURCES) * 5 + 1 == 31
    assert len(first.sources) == len(REQUIRED_ENTRY_SOURCES)
    assert env.terminal.aggregate(
        first.final_aggregate_ref,
        owner_user_id=OWNER,
    ).coverage_refs == tuple(item.coverage.coverage_ref for item in env.candidates)
    assert not env.terminal.validate_current(
        env.terminal.aggregate(first.final_aggregate_ref, owner_user_id=OWNER),
        owner_user_id=OWNER,
    )
    aggregate_head = next(
        head for head in snapshot.heads if head.logical_ref == first.final_aggregate_ref
    )
    assert set(aggregate_head.depends_on) == {
        item.coverage.coverage_ref for item in env.candidates
    }
    for candidate in env.candidates:
        assert env.attestations.is_canonical_current(candidate.attestation)
        assert env.receipts.is_canonical_current(candidate.validation_receipt)
        assert env.compiler.is_canonical_current(candidate.compiler_ir)
        assert env.compiler.is_canonical_current(candidate.compiler_pass)
        assert env.entrypoints.is_canonical_current(candidate.coverage)
    _assert_legacy_bytes_unchanged(env)

    invalidated = env.ledger.invalidate(
        owner=OWNER,
        operation_id="invalidate:atomic-full-product:g1",
        targets=(InvalidationTarget.from_head(snapshot.heads[0]),),
        reason="exercise exact full-product bundle invalidation",
        subject=aggregate_head.subject,
    )
    assert len(invalidated.affected_refs) == 31
    assert env.ledger.current(owner=OWNER).heads == ()
    assert env.attestations.records(owner_user_id=OWNER) == []
    assert env.receipts.receipts(owner_user_id=OWNER) == []
    assert env.compiler.irs(owner=OWNER) == []
    assert env.entrypoints.records(owner=OWNER) == []
    assert env.terminal.records(owner_user_id=OWNER) == []

    second = env.producer.record_current_all(owner_user_id=OWNER)
    assert second == first
    assert {head.generation for head in env.ledger.current(owner=OWNER).heads} == {2}
    _assert_legacy_bytes_unchanged(env)


def test_injected_precommit_failure_leaves_zero_heads_and_legacy_bytes(
    tmp_path: Path,
) -> None:
    def fail(cutpoint: str) -> None:
        if cutpoint == "before_sqlite_commit":
            raise RuntimeError("injected atomic full-product precommit failure")

    env = _environment(tmp_path, fault_injector=fail)

    with pytest.raises(
        GoalFullProductCommitError,
        match="injected atomic full-product precommit failure",
    ) as caught:
        env.producer.record_current_all(owner_user_id=OWNER)

    assert caught.value.completed_stages == ()
    assert caught.value.state_unchanged is True
    assert env.ledger.current(owner=OWNER).heads == ()
    _assert_legacy_bytes_unchanged(env)


def test_atomic_preflight_rejects_cross_owner_recombination_and_type_collision(
    tmp_path: Path,
) -> None:
    env = _environment(tmp_path)
    first, second = env.candidates[:2]
    foreign_attestation = replace(
        first.attestation,
        attestation_ref="",
        owner_user_id="owner:foreign",
    )
    foreign_attestation = replace(
        foreign_attestation,
        attestation_ref=foreign_attestation.canonical_attestation_ref,
    )
    with pytest.raises(ValueError, match="owner"):
        env.producer._validate_atomic_candidate(
            replace(first, attestation=foreign_attestation),
            owner=OWNER,
        )
    with pytest.raises(ValueError, match="recombined"):
        env.producer._validate_atomic_candidate(
            replace(first, coverage=second.coverage),
            owner=OWNER,
        )

    collided_ref = first.coverage.coverage_ref
    env.ledger.commit(
        ProofBundle(
            owner=OWNER,
            subject="goal_full_product_bundle:type-collision",
            members=(
                proof_record_member(
                    logical_type="goal.unrelated_type",
                    logical_ref=collided_ref,
                    owner=OWNER,
                    record={"value": "unrelated"},
                ),
            ),
        )
    )
    with pytest.raises(GoalProofRecordProjectionError, match="ref/type collision"):
        env.entrypoints.coverage(collided_ref, owner=OWNER)
    with pytest.raises(
        GoalFullProductCommitError,
        match="overlaps current logical refs",
    ):
        env.producer.record_current_all(owner_user_id=OWNER)
    _assert_legacy_bytes_unchanged(env)

    for mutation in (
        lambda: env.attestations.record_attestation(first.attestation),
        lambda: env.receipts.record_receipt(first.validation_receipt),
        lambda: env.compiler.record_ir(first.compiler_ir),
        lambda: env.compiler.record_pass(first.compiler_pass),
        lambda: env.entrypoints.record_coverage(first.coverage),
        lambda: env.terminal.record_current(owner_user_id=OWNER),
    ):
        with pytest.raises(RuntimeError, match="atomic proof bundle required"):
            mutation()
    _assert_legacy_bytes_unchanged(env)


def test_legacy_full_product_rows_remain_readable_but_never_canonical(
    tmp_path: Path,
) -> None:
    candidates = tuple(_candidate(source) for source in REQUIRED_ENTRY_SOURCES)
    coverage_path = tmp_path / "legacy" / "entrypoints.jsonl"
    attestation_path = tmp_path / "legacy" / "attestations.jsonl"
    aggregate_path = tmp_path / "legacy" / "terminal_aggregates.jsonl"
    coverage_path.parent.mkdir(parents=True, exist_ok=True)
    coverage_path.write_text(
        "".join(
            json.dumps(
                {
                    "schema_version": 2,
                    "event_type": "goal_entrypoint_coverage_recorded",
                    "owner_user_id": OWNER,
                    "entrypoint_coverage": asdict(candidate.coverage),
                },
                sort_keys=True,
                separators=(",", ":"),
            )
            + "\n"
            for candidate in candidates
        ),
        encoding="utf-8",
    )
    attestation_path.write_text(
        json.dumps(
            {
                "schema_version": 2,
                "event_type": "goal_full_product_attestation_recorded",
                "owner_user_id": OWNER,
                "attestation": asdict(candidates[0].attestation),
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n",
        encoding="utf-8",
    )
    provisional_aggregate = GoalEntrypointAggregateRecord(
        aggregate_ref="",
        coverage_refs=tuple(
            candidate.coverage.coverage_ref for candidate in candidates
        ),
        recorded_by=OWNER,
    )
    aggregate = replace(
        provisional_aggregate,
        aggregate_ref=provisional_aggregate.canonical_aggregate_ref,
    )
    aggregate_path.write_text(
        json.dumps(
            {
                "schema_version": 2,
                "event_type": "goal_entrypoint_aggregate_recorded",
                "owner_user_id": OWNER,
                "aggregate": asdict(aggregate),
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n",
        encoding="utf-8",
    )
    before = {
        path: path.read_bytes()
        for path in (coverage_path, attestation_path, aggregate_path)
    }

    ledger = GoalProofLedger(tmp_path / "legacy" / "proof_ledger")
    compiler = PersistentCompilerIRStore(
        tmp_path / "legacy" / "compiler.jsonl",
        proof_ledger=ledger,
        legacy_read_only=True,
    )
    receipts = PersistentGoalValidationReceiptRegistry(
        tmp_path / "legacy" / "receipts.jsonl",
        proof_ledger=ledger,
        legacy_read_only=True,
    )
    entrypoints = PersistentGoalEntrypointCoverageRegistry(
        coverage_path,
        resolver=_PermissiveStrictResolver(),
        proof_ledger=ledger,
        legacy_read_only=True,
    )
    inert = SimpleNamespace()
    attestations = PersistentGoalFullProductEntrypointAttestationRegistry(
        attestation_path,
        entrypoint_registry=entrypoints,
        lineage_aggregate_registry=inert,
        semantic_proof_registry=inert,
        section_coverage_registry=inert,
        compiler_store=compiler,
        validation_receipt_registry=receipts,
        closure_resolver=lambda _owner, _proofs: GoalFullProductClosureSnapshot(
            lifecycle_refs=("lifecycle:unused",),
            rdp_refs=("rdp:unused",),
            promotion_receipt_ref="promotion_receipt:unused",
        ),
        proof_ledger=ledger,
        legacy_read_only=True,
    )
    terminal = PersistentGoalEntrypointAggregateRegistry(
        aggregate_path,
        entrypoints,
        proof_ledger=ledger,
        legacy_read_only=True,
    )

    assert entrypoints.coverage(
        candidates[0].coverage.coverage_ref,
        owner=OWNER,
    ) == candidates[0].coverage
    assert attestations.attestation(
        candidates[0].attestation.attestation_ref,
        owner_user_id=OWNER,
    ) == candidates[0].attestation
    assert terminal.aggregate(
        aggregate.aggregate_ref,
        owner_user_id=OWNER,
    ) == aggregate
    assert not entrypoints.is_canonical_current(candidates[0].coverage)
    assert not attestations.is_canonical_current(candidates[0].attestation)
    assert not terminal.is_canonical_current(aggregate)
    assert "goal_entrypoint_aggregate_not_canonical_current" in (
        terminal.validate_current(aggregate, owner_user_id=OWNER)
    )
    for mutation in (
        lambda: entrypoints.record_coverage(candidates[0].coverage),
        lambda: attestations.record_attestation(candidates[0].attestation),
        lambda: terminal.record_current(owner_user_id=OWNER),
    ):
        with pytest.raises(RuntimeError, match="atomic proof bundle required"):
            mutation()
    assert {path: path.read_bytes() for path in before} == before
