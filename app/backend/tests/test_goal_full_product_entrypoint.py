from __future__ import annotations

import hashlib
import inspect
import json
import os
import subprocess
import sys
import time
from dataclasses import asdict, replace
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app import main
from app.auth import require_user_dependency
from app.lineage.ids import content_hash
from app.research_os.compiler import (
    COMPILER_IR_PROOF_CODEC,
    COMPILER_PASS_PROOF_CODEC,
    CompilerIRRecord,
    CompilerPassRecord,
    PersistentCompilerIRStore,
)
from app.research_os.goal_coverage import (
    GOAL_ENTRYPOINT_COVERAGE_PROOF_CODEC,
    GoalEntrypointCoverageRecord,
    GoalSectionCoverageRecord,
    PersistentGoalEntrypointCoverageRegistry,
    PersistentGoalSectionCoverageRegistry,
    REQUIRED_ENTRY_SOURCES,
    REQUIRED_GOAL_SECTIONS,
    goal_entrypoint_coverage_identity,
)
from app.research_os.goal_entrypoint_aggregate import (
    PersistentGoalEntrypointAggregateRegistry,
)
from app.research_os.goal_entrypoint_lineage_aggregate import (
    CORE_GOAL_SECTIONS,
    PersistentGoalEntrypointLineageAggregateRegistry,
)
from app.research_os.goal_full_product_entrypoint import (
    FULL_PRODUCT_ATTESTATION_VALIDATOR_IDENTIFIER,
    FULL_PRODUCT_ATTESTATION_VERSION,
    FULL_PRODUCT_VALIDATOR_IDENTIFIER,
    GOAL_FULL_PRODUCT_ATTESTATION_PROOF_CODEC,
    LEGACY_FULL_PRODUCT_ATTESTATION_VERSION,
    GoalFullProductClosureSnapshot,
    GoalFullProductCommitError,
    GoalFullProductCommitStage,
    GoalFullProductEntrypointProducer,
    PersistentGoalFullProductEntrypointAttestationRegistry,
    goal_full_product_entrypoint_attestation_from_dict,
)
from app.research_os.goal_proof_head_lock import acquire_goal_proof_head_lock
from app.research_os.goal_proof_ledger import GoalProofLedger
from app.research_os.goal_semantics import (
    GoalSectionSemanticProofRecord,
    GoalSemanticDecision,
    GoalSemanticViolation,
    PersistentGoalSectionSemanticProofRegistry,
    goal_section_semantic_proof_identity,
)
from app.research_os.goal_validation_receipts import (
    GOAL_VALIDATION_RECEIPT_PROOF_CODEC,
    GoalValidationOutcome,
    GoalValidationReceipt,
    PersistentGoalValidationReceiptRegistry,
)
from app.research_os.ref_resolution import build_real_ref_resolver


OWNER = "owner:alice"
BACKEND_ROOT = Path(__file__).resolve().parents[1]


def test_proof_head_lock_excludes_a_separate_process(tmp_path) -> None:
    ledger_path = tmp_path / "entrypoint-coverages.jsonl"
    ready_path = tmp_path / "child-ready"
    acquired_path = tmp_path / "child-acquired"
    child_code = """
import sys
from pathlib import Path
from app.research_os.goal_proof_head_lock import acquire_goal_proof_head_lock

ledger_path = Path(sys.argv[1])
ready_path = Path(sys.argv[2])
acquired_path = Path(sys.argv[3])
ready_path.write_text("ready", encoding="utf-8")
with acquire_goal_proof_head_lock(ledger_path, timeout_seconds=20.0):
    acquired_path.write_text("acquired", encoding="utf-8")
"""

    child = None
    with acquire_goal_proof_head_lock(ledger_path):
        child = subprocess.Popen(
            [
                sys.executable,
                "-c",
                child_code,
                str(ledger_path),
                str(ready_path),
                str(acquired_path),
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            cwd=BACKEND_ROOT,
        )
        # Importing the backend package can take several seconds on a loaded CI
        # worker.  The child must still signal readiness before it blocks on the
        # held proof-head lock; give startup its own deterministic budget.
        deadline = time.monotonic() + 15.0
        while not ready_path.exists() and time.monotonic() < deadline:
            time.sleep(0.01)
        assert ready_path.exists()
        time.sleep(0.1)
        assert not acquired_path.exists()

    assert child is not None
    stdout, stderr = child.communicate(timeout=5.0)
    assert child.returncode == 0, (stdout, stderr)
    assert acquired_path.read_text(encoding="utf-8") == "acquired"


def _digest(value: str) -> str:
    return "sha256:" + hashlib.sha256(value.encode("utf-8")).hexdigest()


class _GraphStore:
    def __init__(self) -> None:
        self.qros: dict[str, object] = {}
        self._commands: list[object] = []
        self._projections: dict[str, object] = {}

    def qro(self, ref: str):
        return self.qros[ref]

    def commands(self):
        return list(self._commands)

    def projection_index(self, *, owner: str | None = None):
        records = tuple(self._projections.values())
        if owner is None:
            return list(records)
        return [record for record in records if record.owner == owner]


class _FixtureGoalProofLedger(GoalProofLedger):
    """Cache immutable current snapshots until the SQLite file changes."""

    def __init__(self, root: str | Path) -> None:
        self._fixture_current_cache: dict[tuple[str | None, tuple[int, ...]], object] = {}
        super().__init__(root)

    def _fixture_db_signature(self) -> tuple[int, ...]:
        stat = os.stat(self.db_path)
        return (
            stat.st_dev,
            stat.st_ino,
            stat.st_size,
            stat.st_mtime_ns,
            stat.st_ctime_ns,
        )

    def current(self, *, owner: str | None = None):
        signature = self._fixture_db_signature()
        key = (owner, signature)
        cached = self._fixture_current_cache.get(key)
        if cached is not None:
            return cached
        snapshot = super().current(owner=owner)
        self._fixture_current_cache[key] = snapshot
        return snapshot

    def commit(self, bundle):
        self._fixture_current_cache.clear()
        try:
            return super().commit(bundle)
        finally:
            self._fixture_current_cache.clear()

    def sync(self) -> int:
        return super().sync()


class _OwnedDocumentStore:
    def __init__(self) -> None:
        self._owners: dict[str, str] = {}

    def add(self, ref: str, *, owner: str) -> None:
        self._owners[ref] = owner

    def span(self, ref: str):
        try:
            owner = self._owners[ref]
        except KeyError:
            raise KeyError(ref) from None
        return SimpleNamespace(
            span_ref=ref,
            owner=owner,
            verified=True,
            span_support_verification_ref=f"span_support:{ref}",
        )


class _OwnedLifecycleRegistry:
    def __init__(self) -> None:
        self._owners: dict[str, str] = {}

    def add(self, ref: str, *, owner: str) -> None:
        self._owners[ref] = owner

    def governed_asset(self, ref: str, *, owner_user_id: str):
        if self._owners.get(ref) != owner_user_id:
            raise KeyError(ref)
        return SimpleNamespace(asset_ref=ref, owner_user_id=owner_user_id)


class _OwnedRDPStore:
    def __init__(self) -> None:
        self._owners: dict[str, str] = {}

    def add(self, ref: str, *, owner: str) -> None:
        self._owners[ref] = owner

    def manifest(self, ref: str, *, owner_user_id: str):
        if self._owners.get(ref) != owner_user_id:
            raise KeyError(ref)
        return SimpleNamespace(package_id=ref, owner_user_id=owner_user_id)


class _CanonicalClosureResolver:
    def __init__(self, snapshot: GoalFullProductClosureSnapshot) -> None:
        self.snapshot = snapshot
        self.calls: list[tuple[str, tuple[str, ...]]] = []

    def __call__(self, owner_user_id: str, semantic_proofs: tuple[object, ...]):
        self.calls.append(
            (
                owner_user_id,
                tuple(str(proof.proof_ref) for proof in semantic_proofs),
            )
        )
        return self.snapshot


class _ExactSemanticAdapter:
    """Rejects every proof except explicitly content-bound real test records."""

    def __init__(self) -> None:
        self.allowed: dict[str, GoalSectionSemanticProofRecord] = {}

    def allow(self, record: GoalSectionSemanticProofRecord) -> None:
        self.allowed[record.proof_ref] = record

    def validate(
        self,
        record: GoalSectionSemanticProofRecord,
        *,
        owner: str,
    ) -> GoalSemanticDecision:
        violations: list[GoalSemanticViolation] = []
        expected = self.allowed.get(record.proof_ref)
        if expected != record:
            violations.append(
                GoalSemanticViolation(
                    "test_semantic_record_not_exact",
                    "adapter requires an explicitly content-bound semantic record",
                    field="proof_ref",
                    ref=record.proof_ref,
                )
            )
        if record.recorded_by != owner:
            violations.append(
                GoalSemanticViolation(
                    "test_semantic_owner_mismatch",
                    "adapter owner must match the proof owner",
                    field="recorded_by",
                    ref=record.proof_ref,
                )
            )
        return GoalSemanticDecision(not violations, tuple(violations))


def _base_lineage(
    *,
    owner: str,
    source: str,
    graph_store: _GraphStore,
    compiler_store: PersistentCompilerIRStore,
    receipt_registry: PersistentGoalValidationReceiptRegistry,
    entrypoint_registry: PersistentGoalEntrypointCoverageRegistry | None = None,
    document_store: _OwnedDocumentStore,
    lifecycle_registry: _OwnedLifecycleRegistry,
    rdp_store: _OwnedRDPStore,
    include_closure: bool,
    variant: str = "core",
) -> GoalEntrypointCoverageRecord:
    entrypoint_ref = f"route:{source}:{variant}"
    qro = SimpleNamespace(
        qro_id=f"qro:{source}:{variant}",
        owner=owner,
        input_contract={"entry_source": source},
        version=1,
    )
    command = SimpleNamespace(
        command_id=f"rgcmd:{source}:{variant}",
        command_type="upsert_qro",
        source=source,
        actor=owner,
        actor_source="user_manual",
        timestamp=f"2026-01-01T00:00:{len(graph_store._commands):02d}Z",
        payload={"qro": qro},
    )
    graph_store.qros[qro.qro_id] = qro
    graph_store._commands.append(command)
    graph_store._projections[qro.qro_id] = SimpleNamespace(
        qro_id=qro.qro_id,
        command_id=command.command_id,
        owner=owner,
        source=source,
        actor_source=command.actor_source,
        actor=owner,
        command_timestamp=command.timestamp,
        qro_version=qro.version,
    )
    evidence_ref = f"evidence:{source}:{variant}"
    lifecycle_ref = f"lifecycle:{source}:{variant}"
    rdp_ref = f"rdp:{source}:{variant}"
    document_store.add(evidence_ref, owner=owner)
    if include_closure:
        lifecycle_registry.add(lifecycle_ref, owner=owner)
        rdp_store.add(rdp_ref, owner=owner)
    provisional_receipt = GoalValidationReceipt(
        validation_ref="",
        owner_user_id=owner,
        subject_qro_refs=(qro.qro_id,),
        graph_command_refs=(command.command_id,),
        validator_identifiers=(
            f"runtime_validator:{source}_{variant}_lineage_v1",
        ),
        test_identifiers=(
            f"pytest:goal_full_product:{source}:{variant}_lineage",
        ),
        outcome=GoalValidationOutcome.PASSED,
        evidence_refs=(evidence_ref,),
        evidence_digests=(_digest(evidence_ref),),
    )
    receipt = replace(
        provisional_receipt,
        validation_ref=provisional_receipt.canonical_validation_ref,
    )
    canonical_refs = (
        f"research_graph_command:{command.command_id}",
        f"entrypoint:{entrypoint_ref}",
    )
    ir = CompilerIRRecord(
        ir_ref=f"compiler_ir:{source}:{variant}",
        source_qro_refs=(qro.qro_id,),
        graph_command_refs=(command.command_id,),
        canonical_command_refs=canonical_refs,
        node_refs=(qro.qro_id, f"entrypoint:{entrypoint_ref}"),
        edge_refs=(),
        artifact_refs=(),
        theory_binding_refs=(),
        consistency_check_refs=(),
        evidence_refs=(evidence_ref,),
        validation_refs=(receipt.validation_ref,),
        permission_ref=f"permission:{source}:{variant}",
        deterministic_run_plan_ref=f"run_plan:{source}:{variant}",
        rollback_ref=f"rollback:{source}:{variant}",
        environment_lock_ref="environment_lock:test-goal-full-product-v1",
        owner=owner,
    )
    compiler_pass = CompilerPassRecord(
        pass_ref=f"compiler_pass:{source}:{variant}",
        pass_name=f"test_{variant}_lineage",
        input_ir_refs=(),
        output_ir_ref=ir.ir_ref,
        input_qro_refs=(qro.qro_id,),
        graph_command_refs=(command.command_id,),
        canonical_command_refs=canonical_refs,
        actor=owner,
        actor_source="user_manual",
        entry_source=source,
        permission_ref=ir.permission_ref,
        tool_record_refs=(entrypoint_ref,),
        evidence_refs=ir.evidence_refs,
        validation_refs=ir.validation_refs,
        deterministic_run_plan_ref=ir.deterministic_run_plan_ref,
        rollback_ref=ir.rollback_ref,
    )
    coverage_ref = goal_entrypoint_coverage_identity(
        entry_source=source,
        entrypoint_ref=entrypoint_ref,
        goal_sections=CORE_GOAL_SECTIONS,
        qro_refs=(qro.qro_id,),
        research_graph_command_refs=(command.command_id,),
        compiler_ir_refs=(ir.ir_ref,),
        compiler_pass_refs=(compiler_pass.pass_ref,),
    )
    coverage = GoalEntrypointCoverageRecord(
        coverage_ref=coverage_ref,
        entry_source=source,
        entrypoint_ref=entrypoint_ref,
        goal_sections=CORE_GOAL_SECTIONS,
        qro_refs=(qro.qro_id,),
        research_graph_command_refs=(command.command_id,),
        compiler_ir_refs=(ir.ir_ref,),
        compiler_pass_refs=(compiler_pass.pass_ref,),
        evidence_refs=ir.evidence_refs,
        validation_refs=ir.validation_refs,
        permission_refs=(ir.permission_ref,),
        replay_refs=(
            f"replay:research_graph:{command.command_id}",
            f"replay:compiler_ir:{ir.ir_ref}",
            f"replay:compiler_pass:{compiler_pass.pass_ref}",
        ),
        canonical_command_refs=canonical_refs,
        lifecycle_refs=(lifecycle_ref,) if include_closure else (),
        rdp_refs=(rdp_ref,) if include_closure else (),
        recorded_by=owner,
    )
    if entrypoint_registry is None:
        receipt_registry.record_receipt(receipt)
        compiler_store.record_ir(ir)
        compiler_store.record_pass(compiler_pass)
        return coverage
    main._commit_canonical_goal_proof_bundle(
        owner=owner,
        subject=f"test_goal_full_product_base:{source}:{variant}",
        records=(
            (receipt, GOAL_VALIDATION_RECEIPT_PROOF_CODEC),
            (ir, COMPILER_IR_PROOF_CODEC),
            (compiler_pass, COMPILER_PASS_PROOF_CODEC),
            (coverage, GOAL_ENTRYPOINT_COVERAGE_PROOF_CODEC),
        ),
        registries=(receipt_registry, compiler_store, entrypoint_registry),
        metadata={
            "producer": "test_goal_full_product_base",
            "entry_source": source,
            "variant": variant,
        },
    )
    return entrypoint_registry.canonical_coverage(
        coverage.coverage_ref,
        owner=owner,
    )


def _commit_section_lineages(
    *,
    owner: str,
    entrypoints: PersistentGoalEntrypointCoverageRegistry,
    records: tuple[GoalEntrypointCoverageRecord, ...],
) -> tuple[GoalEntrypointCoverageRecord, ...]:
    main._commit_canonical_goal_proof_bundle(
        owner=owner,
        subject="test_goal_full_product_sections",
        records=tuple(
            (record, GOAL_ENTRYPOINT_COVERAGE_PROOF_CODEC)
            for record in records
        ),
        registries=(entrypoints,),
        metadata={
            "producer": "test_goal_full_product_sections",
            "coverage_refs": tuple(record.coverage_ref for record in records),
        },
    )
    return tuple(
        entrypoints.canonical_coverage(record.coverage_ref, owner=owner)
        for record in records
    )


def _section_lineage(
    base: GoalEntrypointCoverageRecord,
    section: str,
) -> GoalEntrypointCoverageRecord:
    coverage_ref = goal_entrypoint_coverage_identity(
        entry_source=base.entry_source,
        entrypoint_ref=base.entrypoint_ref,
        goal_sections=(section,),
        qro_refs=base.qro_refs,
        research_graph_command_refs=base.research_graph_command_refs,
        compiler_ir_refs=base.compiler_ir_refs,
        compiler_pass_refs=base.compiler_pass_refs,
    )
    return replace(
        base,
        coverage_ref=coverage_ref,
        goal_sections=(section,),
    )


def _semantic_proof(
    *,
    owner: str,
    section: str,
    coverage_ref: str,
    variant: str = "current",
) -> GoalSectionSemanticProofRecord:
    data = {
        "section": section,
        "subject_ref": f"goal_section_subject:{section}:{variant}",
        "producer_refs": (f"producer:{section}:{variant}",),
        "store_refs": (f"store:{section}:{variant}",),
        "consumer_refs": (f"consumer:{section}:{variant}",),
        "gate_verdict_refs": (f"gate_verdict:{section}:{variant}",),
        "test_refs": (f"pytest:goal_full_product:{section}:{variant}",),
        "entrypoint_coverage_refs": (coverage_ref,),
        "recorded_by": owner,
        "claims_section_complete": True,
        "unverified_residuals": (),
    }
    data["proof_ref"] = goal_section_semantic_proof_identity(**data)
    return GoalSectionSemanticProofRecord(**data)


def _section_coverage(
    *,
    owner: str,
    section: str,
    coverage_ref: str,
    proof_ref: str,
    variant: str = "current",
) -> GoalSectionCoverageRecord:
    return GoalSectionCoverageRecord(
        section=section,
        contract_refs=(f"contract:{section}:{variant}",),
        test_refs=(f"pytest:goal_full_product_section:{section}:{variant}",),
        task_refs=(f"task:goal_full_product:{section}:{variant}",),
        evidence_refs=(f"evidence:goal_full_product:{section}:{variant}",),
        recorded_by=owner,
        full_entrypoint_wired=True,
        entrypoint_wiring_refs=(coverage_ref,),
        semantic_proof_refs=(proof_ref,),
    )


def _environment(
    tmp_path,
    owner: str = OWNER,
    *,
    include_closure: bool = False,
):
    graph_store = _GraphStore()
    proof_ledger = _FixtureGoalProofLedger(tmp_path / "goal_proof_ledger")
    compiler_store = PersistentCompilerIRStore(
        tmp_path / "compiler.jsonl",
        proof_ledger=proof_ledger,
    )
    receipts = PersistentGoalValidationReceiptRegistry(
        tmp_path / "receipts.jsonl",
        proof_ledger=proof_ledger,
    )
    documents = _OwnedDocumentStore()
    lifecycle = _OwnedLifecycleRegistry()
    rdps = _OwnedRDPStore()
    resolver = build_real_ref_resolver(
        research_graph_store=graph_store,
        lifecycle_registry=lifecycle,
        governance_registry=None,
        rag_index=None,
        spine_chain_registry=None,
        compiler_store=compiler_store,
        document_store=documents,
        rdp_store=rdps,
        goal_validation_receipt_registry=receipts,
    )
    entrypoints = PersistentGoalEntrypointCoverageRegistry(
        tmp_path / "entrypoints.jsonl",
        resolver=resolver,
        proof_ledger=proof_ledger,
    )
    bases = tuple(
        _base_lineage(
            owner=owner,
            source=source,
            graph_store=graph_store,
            compiler_store=compiler_store,
            receipt_registry=receipts,
            entrypoint_registry=entrypoints,
            document_store=documents,
            lifecycle_registry=lifecycle,
            rdp_store=rdps,
            include_closure=include_closure,
        )
        for source in REQUIRED_ENTRY_SOURCES
    )
    closure = GoalFullProductClosureSnapshot(
        lifecycle_refs=("lifecycle:promotion:current",),
        rdp_refs=("rdp:promotion:current",),
        promotion_receipt_ref="promotion_receipt:current",
    )
    for lifecycle_ref in closure.lifecycle_refs:
        lifecycle.add(lifecycle_ref, owner=owner)
    for rdp_ref in closure.rdp_refs:
        rdps.add(rdp_ref, owner=owner)
    closure_resolver = _CanonicalClosureResolver(closure)
    api_base = bases[REQUIRED_ENTRY_SOURCES.index("api")]
    support: dict[str, GoalEntrypointCoverageRecord] = {}
    deferred_section_records: list[GoalEntrypointCoverageRecord] = []
    for section in REQUIRED_GOAL_SECTIONS:
        if section in CORE_GOAL_SECTIONS:
            support[section] = api_base
        else:
            deferred_section_records.append(_section_lineage(api_base, section))
    committed_section_records = _commit_section_lineages(
        owner=owner,
        entrypoints=entrypoints,
        records=tuple(deferred_section_records),
    )
    support.update(
        {
            record.goal_sections[0]: record
            for record in committed_section_records
        }
    )

    lineage_aggregates = PersistentGoalEntrypointLineageAggregateRegistry(
        tmp_path / "lineage_aggregates.jsonl",
        entrypoints,
    )
    lineage_aggregate = lineage_aggregates.record_current(
        owner_user_id=owner
    )

    adapters = {
        section: _ExactSemanticAdapter()
        for section in REQUIRED_GOAL_SECTIONS
    }
    proofs = {
        section: _semantic_proof(
            owner=owner,
            section=section,
            coverage_ref=support[section].coverage_ref,
        )
        for section in REQUIRED_GOAL_SECTIONS
    }
    for section, proof in proofs.items():
        adapters[section].allow(proof)
    semantic = PersistentGoalSectionSemanticProofRegistry(
        tmp_path / "semantic.jsonl",
        entrypoints,
        adapters=adapters,
    )
    for section in REQUIRED_GOAL_SECTIONS:
        semantic.record_proof(proofs[section])

    sections = PersistentGoalSectionCoverageRegistry(
        tmp_path / "sections.jsonl",
        entrypoints,
        semantic,
    )
    for section in REQUIRED_GOAL_SECTIONS:
        sections.record_coverage(
            _section_coverage(
                owner=owner,
                section=section,
                coverage_ref=support[section].coverage_ref,
                proof_ref=proofs[section].proof_ref,
            )
        )

    attestations = PersistentGoalFullProductEntrypointAttestationRegistry(
        tmp_path / "attestations.jsonl",
        entrypoint_registry=entrypoints,
        lineage_aggregate_registry=lineage_aggregates,
        semantic_proof_registry=semantic,
        section_coverage_registry=sections,
        compiler_store=compiler_store,
        validation_receipt_registry=receipts,
        closure_resolver=closure_resolver,
        proof_ledger=proof_ledger,
    )
    terminal_resolver = build_real_ref_resolver(
        research_graph_store=graph_store,
        lifecycle_registry=lifecycle,
        governance_registry=None,
        rag_index=None,
        spine_chain_registry=None,
        compiler_store=compiler_store,
        document_store=documents,
        rdp_store=rdps,
        goal_validation_receipt_registry=receipts,
        goal_full_product_attestation_registry=attestations,
    )
    entrypoints.set_ref_resolver(terminal_resolver)
    terminal_aggregates = PersistentGoalEntrypointAggregateRegistry(
        tmp_path / "terminal_aggregates.jsonl",
        entrypoints,
        proof_ledger=proof_ledger,
    )
    producer = GoalFullProductEntrypointProducer(
        attestation_registry=attestations,
        entrypoint_registry=entrypoints,
        compiler_store=compiler_store,
        validation_receipt_registry=receipts,
        terminal_aggregate_registry=terminal_aggregates,
        proof_ledger=proof_ledger,
    )
    return SimpleNamespace(
        owner=owner,
        proof_ledger=proof_ledger,
        graph_store=graph_store,
        compiler_store=compiler_store,
        receipts=receipts,
        documents=documents,
        lifecycle=lifecycle,
        rdps=rdps,
        terminal_resolver=terminal_resolver,
        entrypoints=entrypoints,
        bases=bases,
        support=support,
        lineage_aggregates=lineage_aggregates,
        lineage_aggregate=lineage_aggregate,
        adapters=adapters,
        proofs=proofs,
        semantic=semantic,
        sections=sections,
        attestations=attestations,
        terminal_aggregates=terminal_aggregates,
        producer=producer,
        closure=closure,
        closure_resolver=closure_resolver,
    )


def _reopen_protocol(env):
    """Reopen every durable protocol ledger as an independent process would."""

    proof_ledger = _FixtureGoalProofLedger(env.proof_ledger.db_path.parent)
    compiler_store = PersistentCompilerIRStore(
        env.compiler_store.path,
        proof_ledger=proof_ledger,
    )
    receipts = PersistentGoalValidationReceiptRegistry(
        env.receipts.path,
        proof_ledger=proof_ledger,
    )
    resolver = build_real_ref_resolver(
        research_graph_store=env.graph_store,
        lifecycle_registry=env.lifecycle,
        governance_registry=None,
        rag_index=None,
        spine_chain_registry=None,
        compiler_store=compiler_store,
        document_store=env.documents,
        rdp_store=env.rdps,
        goal_validation_receipt_registry=receipts,
    )
    entrypoints = PersistentGoalEntrypointCoverageRegistry(
        env.entrypoints.path,
        resolver=resolver,
        proof_ledger=proof_ledger,
    )
    lineage_aggregates = PersistentGoalEntrypointLineageAggregateRegistry(
        env.lineage_aggregates.path,
        entrypoints,
    )
    semantic = PersistentGoalSectionSemanticProofRegistry(
        env.semantic.path,
        entrypoints,
        adapters=env.adapters,
    )
    sections = PersistentGoalSectionCoverageRegistry(
        env.sections.path,
        entrypoints,
        semantic,
    )
    attestations = PersistentGoalFullProductEntrypointAttestationRegistry(
        env.attestations.path,
        entrypoint_registry=entrypoints,
        lineage_aggregate_registry=lineage_aggregates,
        semantic_proof_registry=semantic,
        section_coverage_registry=sections,
        compiler_store=compiler_store,
        validation_receipt_registry=receipts,
        closure_resolver=env.closure_resolver,
        proof_ledger=proof_ledger,
    )
    terminal_resolver = build_real_ref_resolver(
        research_graph_store=env.graph_store,
        lifecycle_registry=env.lifecycle,
        governance_registry=None,
        rag_index=None,
        spine_chain_registry=None,
        compiler_store=compiler_store,
        document_store=env.documents,
        rdp_store=env.rdps,
        goal_validation_receipt_registry=receipts,
        goal_full_product_attestation_registry=attestations,
    )
    entrypoints.set_ref_resolver(terminal_resolver)
    terminal_aggregates = PersistentGoalEntrypointAggregateRegistry(
        env.terminal_aggregates.path,
        entrypoints,
        proof_ledger=proof_ledger,
    )
    producer = GoalFullProductEntrypointProducer(
        attestation_registry=attestations,
        entrypoint_registry=entrypoints,
        compiler_store=compiler_store,
        validation_receipt_registry=receipts,
        terminal_aggregate_registry=terminal_aggregates,
        proof_ledger=proof_ledger,
    )
    return SimpleNamespace(
        **{
            **vars(env),
            "proof_ledger": proof_ledger,
            "compiler_store": compiler_store,
            "receipts": receipts,
            "terminal_resolver": terminal_resolver,
            "entrypoints": entrypoints,
            "lineage_aggregates": lineage_aggregates,
            "semantic": semantic,
            "sections": sections,
            "attestations": attestations,
            "terminal_aggregates": terminal_aggregates,
            "producer": producer,
        }
    )


def _protocol_counts(env) -> dict[str, int]:
    compiler = env.compiler_store.canonical_records(owner=env.owner)
    coverages = env.entrypoints.canonical_records(owner=env.owner)
    attestations = tuple(
        record
        for record in env.attestations.records(owner_user_id=env.owner)
        if env.attestations.is_canonical_current(
            record,
            owner_user_id=env.owner,
        )
    )
    receipts = tuple(
        record
        for record in env.receipts.receipts(owner_user_id=env.owner)
        if env.receipts.is_canonical_current(
            record,
            owner_user_id=env.owner,
        )
    )
    terminal_aggregates = tuple(
        record
        for record in env.terminal_aggregates.records(owner_user_id=env.owner)
        if env.terminal_aggregates.is_canonical_current(
            record,
            owner_user_id=env.owner,
        )
    )
    return {
        "attestations": len(attestations),
        "receipts": len(receipts),
        "irs": len(compiler.irs),
        "passes": len(compiler.passes),
        "coverages": len(coverages),
        "terminal_aggregates": len(terminal_aggregates),
    }


def _commit_candidate_bundle(env, candidate) -> None:
    main._commit_canonical_goal_proof_bundle(
        owner=env.owner,
        subject=(
            "test_goal_full_product_candidate:"
            f"{candidate.attestation.entry_source}"
        ),
        records=(
            (
                candidate.attestation,
                GOAL_FULL_PRODUCT_ATTESTATION_PROOF_CODEC,
            ),
            (
                candidate.validation_receipt,
                GOAL_VALIDATION_RECEIPT_PROOF_CODEC,
            ),
            (candidate.compiler_ir, COMPILER_IR_PROOF_CODEC),
            (candidate.compiler_pass, COMPILER_PASS_PROOF_CODEC),
            (candidate.coverage, GOAL_ENTRYPOINT_COVERAGE_PROOF_CODEC),
        ),
        registries=(
            env.attestations,
            env.receipts,
            env.compiler_store,
            env.entrypoints,
        ),
        metadata={
            "producer": "test_goal_full_product_candidate",
            "entry_source": candidate.attestation.entry_source,
        },
    )
    for store in (
        env.attestations,
        env.receipts,
        env.compiler_store,
        env.entrypoints,
    ):
        store.refresh()


def _canonical_attestation(record, **changes):
    provisional = replace(record, attestation_ref="", **changes)
    return replace(
        provisional,
        attestation_ref=provisional.canonical_attestation_ref,
    )


def _compatibility_attestation_registry(
    env,
) -> PersistentGoalFullProductEntrypointAttestationRegistry:
    """Open the explicit legacy-JSONL attestation compatibility surface."""

    return PersistentGoalFullProductEntrypointAttestationRegistry(
        env.attestations.path,
        entrypoint_registry=env.entrypoints,
        lineage_aggregate_registry=env.lineage_aggregates,
        semantic_proof_registry=env.semantic,
        section_coverage_registry=env.sections,
        compiler_store=env.compiler_store,
        validation_receipt_registry=env.receipts,
        closure_resolver=env.closure_resolver,
    )


def test_preflight_derives_all_proofs_without_caller_refs_and_is_deterministic(
    tmp_path,
) -> None:
    env = _environment(tmp_path)
    parameters = tuple(
        inspect.signature(env.attestations.prepare_current_source).parameters
    )
    assert parameters == ("owner_user_id", "entry_source")
    constructor_parameter = inspect.signature(
        PersistentGoalFullProductEntrypointAttestationRegistry.__init__
    ).parameters["closure_resolver"]
    assert constructor_parameter.default is inspect.Parameter.empty

    first = env.attestations.prepare_current_all(owner_user_id=env.owner)
    second = env.attestations.prepare_current_all(owner_user_id=env.owner)
    assert first == second
    assert tuple(item.attestation.entry_source for item in first) == (
        REQUIRED_ENTRY_SOURCES
    )
    assert env.closure_resolver.calls[-1] == (
        env.owner,
        tuple(
            env.proofs[section].proof_ref for section in REQUIRED_GOAL_SECTIONS
        ),
    )
    for candidate, base in zip(first, env.bases, strict=True):
        attestation = candidate.attestation
        assert base.lifecycle_refs == ()
        assert base.rdp_refs == ()
        assert attestation.base_coverage_ref == base.coverage_ref
        assert attestation.lineage_aggregate_ref == (
            env.lineage_aggregate.aggregate_ref
        )
        assert attestation.lineage_coverage_refs == (
            env.lineage_aggregate.coverage_refs
        )
        assert attestation.semantic_proof_refs == tuple(
            env.proofs[section].proof_ref for section in REQUIRED_GOAL_SECTIONS
        )
        assert len(attestation.section_snapshot_refs) == len(
            REQUIRED_GOAL_SECTIONS
        )
        assert candidate.coverage.claims_full_product_entrypoint is True
        assert candidate.coverage.goal_sections == REQUIRED_GOAL_SECTIONS
        assert attestation.lifecycle_refs == env.closure.lifecycle_refs
        assert attestation.rdp_refs == env.closure.rdp_refs
        assert (
            attestation.promotion_receipt_ref
            == env.closure.promotion_receipt_ref
        )
        assert candidate.coverage.lifecycle_refs == attestation.lifecycle_refs
        assert candidate.coverage.rdp_refs == attestation.rdp_refs
        assert candidate.coverage.evidence_refs == (attestation.attestation_ref,)


def test_preflight_ignores_base_closure_and_uses_server_resolved_snapshot(
    tmp_path,
) -> None:
    env = _environment(tmp_path, include_closure=True)
    assert all(base.lifecycle_refs for base in env.bases)
    assert all(base.rdp_refs for base in env.bases)

    candidates = env.attestations.prepare_current_all(owner_user_id=env.owner)

    for candidate, base in zip(candidates, env.bases, strict=True):
        assert candidate.coverage.lifecycle_refs == env.closure.lifecycle_refs
        assert candidate.coverage.rdp_refs == env.closure.rdp_refs
        assert candidate.coverage.lifecycle_refs != base.lifecycle_refs
        assert candidate.coverage.rdp_refs != base.rdp_refs


def test_preflight_succeeds_when_immutable_bases_have_no_closure_refs(tmp_path) -> None:
    env = _environment(tmp_path, include_closure=False)

    candidates = env.attestations.prepare_current_all(owner_user_id=env.owner)

    assert len(candidates) == len(REQUIRED_ENTRY_SOURCES)
    assert all(not base.lifecycle_refs and not base.rdp_refs for base in env.bases)
    assert all(
        candidate.coverage.lifecycle_refs == env.closure.lifecycle_refs
        and candidate.coverage.rdp_refs == env.closure.rdp_refs
        for candidate in candidates
    )


@pytest.mark.parametrize(
    "closure",
    (
        GoalFullProductClosureSnapshot(
            lifecycle_refs=(),
            rdp_refs=("rdp:promotion:current",),
            promotion_receipt_ref="promotion_receipt:current",
        ),
        GoalFullProductClosureSnapshot(
            lifecycle_refs=("lifecycle:duplicate", "lifecycle:duplicate"),
            rdp_refs=("rdp:promotion:current",),
            promotion_receipt_ref="promotion_receipt:current",
        ),
        GoalFullProductClosureSnapshot(
            lifecycle_refs=("lifecycle:promotion:current",),
            rdp_refs=[],  # type: ignore[arg-type]
            promotion_receipt_ref="promotion_receipt:current",
        ),
        GoalFullProductClosureSnapshot(
            lifecycle_refs=("lifecycle:promotion:current",),
            rdp_refs=("rdp:duplicate", "rdp:duplicate"),
            promotion_receipt_ref="promotion_receipt:current",
        ),
        GoalFullProductClosureSnapshot(
            lifecycle_refs=("lifecycle:promotion:current",),
            rdp_refs=("rdp:promotion:current",),
            promotion_receipt_ref="",
        ),
        GoalFullProductClosureSnapshot(
            lifecycle_refs=("shared:closure",),
            rdp_refs=("rdp:promotion:current",),
            promotion_receipt_ref="shared:closure",
        ),
    ),
)
def test_malformed_server_closure_is_rejected_before_any_attestation_write(
    tmp_path,
    closure,
) -> None:
    env = _environment(tmp_path)
    before = (
        env.attestations.path.read_bytes()
        if env.attestations.path.exists()
        else None
    )
    env.closure_resolver.snapshot = closure

    with pytest.raises((TypeError, ValueError), match="full-product closure"):
        env.attestations.prepare_current_all(owner_user_id=env.owner)

    after = (
        env.attestations.path.read_bytes()
        if env.attestations.path.exists()
        else None
    )
    assert after == before
    assert env.attestations.records(owner_user_id=env.owner) == []


def test_closure_resolver_is_not_called_before_strict_semantic_proofs(tmp_path) -> None:
    env = _environment(tmp_path)
    env.closure_resolver.calls.clear()
    env.adapters["§2"].allowed.clear()

    with pytest.raises(ValueError, match="semantic proof §2 is not strict"):
        env.attestations.build_current_snapshot(owner_user_id=env.owner)

    assert env.closure_resolver.calls == []


def test_closure_mutation_changes_every_derived_identity(tmp_path) -> None:
    env = _environment(tmp_path)
    first = env.attestations.prepare_current_source(
        owner_user_id=env.owner,
        entry_source="api",
    )
    changed = GoalFullProductClosureSnapshot(
        lifecycle_refs=("lifecycle:promotion:new",),
        rdp_refs=("rdp:promotion:new",),
        promotion_receipt_ref="promotion_receipt:new",
    )
    env.lifecycle.add(changed.lifecycle_refs[0], owner=env.owner)
    env.rdps.add(changed.rdp_refs[0], owner=env.owner)
    env.closure_resolver.snapshot = changed

    second = env.attestations.prepare_current_source(
        owner_user_id=env.owner,
        entry_source="api",
    )

    assert first.attestation.attestation_version == FULL_PRODUCT_ATTESTATION_VERSION
    assert second.attestation.lifecycle_refs == changed.lifecycle_refs
    assert second.attestation.rdp_refs == changed.rdp_refs
    assert second.attestation.promotion_receipt_ref == changed.promotion_receipt_ref
    assert first.attestation.attestation_ref != second.attestation.attestation_ref
    assert first.attestation.derived_entrypoint_ref != (
        second.attestation.derived_entrypoint_ref
    )
    assert first.compiler_ir.ir_ref != second.compiler_ir.ir_ref
    assert first.compiler_pass.pass_ref != second.compiler_pass.pass_ref
    assert first.coverage.coverage_ref != second.coverage.coverage_ref
    assert not env.attestations.validate_current(
        first.attestation,
        owner_user_id=env.owner,
    ).accepted


def test_v1_rows_are_quarantined_while_v2_reloads_and_validates_current(
    tmp_path,
) -> None:
    env = _environment(tmp_path)
    compatibility_attestations = _compatibility_attestation_registry(env)
    candidate = env.attestations.prepare_current_source(
        owner_user_id=env.owner,
        entry_source="api",
    )
    persisted = compatibility_attestations.record_attestation(
        candidate.attestation
    )
    v2_line = compatibility_attestations.path.read_text(encoding="utf-8")

    legacy_raw = asdict(persisted)
    for field_name in (
        "lifecycle_refs",
        "rdp_refs",
        "promotion_receipt_ref",
    ):
        legacy_raw.pop(field_name)
    legacy_raw["attestation_version"] = LEGACY_FULL_PRODUCT_ATTESTATION_VERSION
    legacy_identity_payload = {
        key: value
        for key, value in legacy_raw.items()
        if key != "attestation_ref"
    }
    legacy_raw["attestation_ref"] = (
        "goal_full_product_entrypoint_attestation:"
        + content_hash(legacy_identity_payload)
    )
    missing_version_raw = dict(legacy_raw)
    missing_version_raw.pop("attestation_version")
    assert goal_full_product_entrypoint_attestation_from_dict(
        missing_version_raw
    ).attestation_version == LEGACY_FULL_PRODUCT_ATTESTATION_VERSION
    rows = (
        {
            "schema_version": 2,
            "event_type": "goal_full_product_attestation_recorded",
            "owner_user_id": env.owner,
            "attestation": legacy_raw,
        },
        {
            "schema_version": 2,
            "event_type": "goal_full_product_attestation_recorded",
            "owner_user_id": env.owner,
            "attestation": missing_version_raw,
        },
    )
    compatibility_attestations.path.write_text(
        "".join(json.dumps(row, sort_keys=True) + "\n" for row in rows)
        + v2_line,
        encoding="utf-8",
    )

    reopened = _compatibility_attestation_registry(env)

    assert reopened.legacy_quarantined_count == 2
    assert reopened.records(owner_user_id=env.owner) == [persisted]
    assert reopened.validate_current(
        persisted,
        owner_user_id=env.owner,
    ).accepted


@pytest.mark.parametrize(
    "mutation",
    (
        {"attestation_version": "goal_full_product_entrypoint_attestation.v999"},
        {"base_coverage_ref": ""},
    ),
)
def test_unknown_or_corrupt_attestation_history_still_fails_closed(
    tmp_path,
    mutation,
) -> None:
    env = _environment(tmp_path / "env")
    candidate = env.attestations.prepare_current_source(
        owner_user_id=env.owner,
        entry_source="api",
    )
    raw = asdict(candidate.attestation)
    for field_name in (
        "lifecycle_refs",
        "rdp_refs",
        "promotion_receipt_ref",
    ):
        raw.pop(field_name)
    raw["attestation_version"] = LEGACY_FULL_PRODUCT_ATTESTATION_VERSION
    raw.update(mutation)
    bad_path = tmp_path / "bad-attestations.jsonl"
    bad_path.write_text(
        json.dumps(
            {
                "schema_version": 2,
                "event_type": "goal_full_product_attestation_recorded",
                "owner_user_id": env.owner,
                "attestation": raw,
            },
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="invalid persisted"):
        PersistentGoalFullProductEntrypointAttestationRegistry(
            bad_path,
            entrypoint_registry=env.entrypoints,
            lineage_aggregate_registry=env.lineage_aggregates,
            semantic_proof_registry=env.semantic,
            section_coverage_registry=env.sections,
            compiler_store=env.compiler_store,
            validation_receipt_registry=env.receipts,
            closure_resolver=env.closure_resolver,
        )


def test_legacy_terminal_history_without_closure_loads_but_is_not_strict(
    tmp_path,
) -> None:
    env = _environment(tmp_path / "env", include_closure=False)
    base = env.bases[0]
    legacy = replace(
        base,
        goal_sections=REQUIRED_GOAL_SECTIONS,
        claims_full_product_entrypoint=True,
    )
    legacy = replace(
        legacy,
        coverage_ref=goal_entrypoint_coverage_identity(
            entry_source=legacy.entry_source,
            entrypoint_ref=legacy.entrypoint_ref,
            goal_sections=legacy.goal_sections,
            qro_refs=legacy.qro_refs,
            research_graph_command_refs=legacy.research_graph_command_refs,
            compiler_ir_refs=legacy.compiler_ir_refs,
            compiler_pass_refs=legacy.compiler_pass_refs,
        ),
    )
    path = tmp_path / "legacy_terminal_entrypoints.jsonl"
    path.write_text(
        json.dumps(
            {
                "schema_version": 2,
                "event_type": "goal_entrypoint_coverage_recorded",
                "owner_user_id": env.owner,
                "entrypoint_coverage": asdict(legacy),
            },
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )

    reloaded = PersistentGoalEntrypointCoverageRegistry(
        path,
        resolver=env.terminal_resolver,
    )
    assert reloaded.coverage(legacy.coverage_ref, owner=env.owner) == legacy
    decision = reloaded.validate_real_backing(legacy)
    assert not decision.accepted
    assert {
        violation.field
        for violation in decision.violations
        if violation.code == "goal_entrypoint_full_product_closure_ref_missing"
    } == {"lifecycle_refs", "rdp_refs"}


def test_full_product_preflight_refuses_legacy_only_compiler_records(
    tmp_path,
) -> None:
    owner = OWNER
    graph_store = _GraphStore()
    legacy_compiler = PersistentCompilerIRStore(tmp_path / "compiler.jsonl")
    receipts = PersistentGoalValidationReceiptRegistry(tmp_path / "receipts.jsonl")
    base = _base_lineage(
        owner=owner,
        source="api",
        graph_store=graph_store,
        compiler_store=legacy_compiler,
        receipt_registry=receipts,
        document_store=_OwnedDocumentStore(),
        lifecycle_registry=_OwnedLifecycleRegistry(),
        rdp_store=_OwnedRDPStore(),
        include_closure=False,
    )
    canonical_compiler = PersistentCompilerIRStore(
        legacy_compiler.path,
        proof_ledger=GoalProofLedger(tmp_path / "empty_proof_ledger"),
    )
    entrypoints = PersistentGoalEntrypointCoverageRegistry(
        tmp_path / "entrypoints.jsonl"
    )
    attestations = PersistentGoalFullProductEntrypointAttestationRegistry(
        tmp_path / "attestations.jsonl",
        entrypoint_registry=entrypoints,
        lineage_aggregate_registry=SimpleNamespace(),
        semantic_proof_registry=SimpleNamespace(),
        section_coverage_registry=SimpleNamespace(),
        compiler_store=canonical_compiler,
        validation_receipt_registry=receipts,
        closure_resolver=lambda _owner, _proofs: GoalFullProductClosureSnapshot(
            lifecycle_refs=("lifecycle:test",),
            rdp_refs=("rdp:test",),
            promotion_receipt_ref="promotion_receipt:test",
        ),
    )

    assert canonical_compiler.irs(owner=owner)
    assert canonical_compiler.canonical_records(owner=owner).irs == ()
    assert attestations._compiler_records_snapshot(owner=owner) == ((), ())
    with pytest.raises(KeyError, match=base.compiler_ir_refs[0]):
        attestations._current_compiler_ir(
            base.compiler_ir_refs[0],
            owner=owner,
        )


def test_real_resolver_end_to_end_and_retry_are_idempotent(tmp_path) -> None:
    env = _environment(tmp_path)
    result = env.producer.record_current_all(owner_user_id=env.owner)

    assert tuple(item.entry_source for item in result.sources) == (
        REQUIRED_ENTRY_SOURCES
    )
    assert env.terminal_aggregates.aggregate(
        result.final_aggregate_ref,
        owner_user_id=env.owner,
    ).coverage_refs == tuple(item.coverage_ref for item in result.sources)
    for item in result.sources:
        coverage = env.entrypoints.coverage(
            item.coverage_ref,
            owner=env.owner,
        )
        decision = env.attestations.validate_full_product_coverage(
            coverage,
            owner_user_id=env.owner,
        )
        assert decision.accepted, decision.violations
        assert env.terminal_resolver.for_owner(env.owner).has_evidence(
            coverage.evidence_refs[0]
        )
        receipt = env.receipts.receipt(
            item.validation_ref,
            owner_user_id=env.owner,
        )
        assert FULL_PRODUCT_VALIDATOR_IDENTIFIER in receipt.validator_identifiers
        assert (
            FULL_PRODUCT_ATTESTATION_VALIDATOR_IDENTIFIER
            in receipt.validator_identifiers
        )


def test_current_terminal_aggregate_uses_one_latest_atomic_bundle(tmp_path) -> None:
    env = _environment(tmp_path)
    first = env.producer.record_current_all(owner_user_id=env.owner)
    section = "§2"
    newer = _semantic_proof(
        owner=env.owner,
        section=section,
        coverage_ref=env.support[section].coverage_ref,
        variant="second-terminal-generation",
    )
    env.adapters[section].allow(newer)
    external_semantic = PersistentGoalSectionSemanticProofRegistry(
        env.semantic.path,
        env.entrypoints,
        adapters=env.adapters,
    )
    external_semantic.record_proof(newer)
    external_sections = PersistentGoalSectionCoverageRegistry(
        env.sections.path,
        env.entrypoints,
        external_semantic,
    )
    external_sections.record_coverage(
        _section_coverage(
            owner=env.owner,
            section=section,
            coverage_ref=env.support[section].coverage_ref,
            proof_ref=newer.proof_ref,
            variant="second-terminal-generation",
        )
    )

    second = env.producer.record_current_all(owner_user_id=env.owner)

    assert second.final_aggregate_ref != first.final_aggregate_ref
    current = env.terminal_aggregates.build_current(owner_user_id=env.owner)
    assert current.aggregate_ref == second.final_aggregate_ref
    assert current.coverage_refs == tuple(
        item.coverage_ref for item in second.sources
    )
    assert set(current.coverage_refs).isdisjoint(
        item.coverage_ref for item in first.sources
    )


def test_terminal_strict_gate_requires_both_lifecycle_and_rdp_refs(tmp_path) -> None:
    env = _environment(tmp_path)
    result = env.producer.record_current_all(owner_user_id=env.owner)
    coverage = env.entrypoints.coverage(
        result.sources[0].coverage_ref,
        owner=env.owner,
    )

    for field_name in ("lifecycle_refs", "rdp_refs"):
        decision = env.entrypoints.validate_real_backing(
            replace(coverage, **{field_name: ()})
        )
        assert not decision.accepted
        assert any(
            violation.code == "goal_entrypoint_full_product_closure_ref_missing"
            and violation.field == field_name
            for violation in decision.violations
        )

    before = env.proof_ledger.current(owner=env.owner)
    assert env.producer.record_current_all(owner_user_id=env.owner) == result
    assert env.proof_ledger.current(owner=env.owner) == before


def test_forged_marker_owner_source_and_recombined_attestation_are_rejected(
    tmp_path,
) -> None:
    env = _environment(tmp_path)
    candidates = env.attestations.prepare_current_all(owner_user_id=env.owner)
    result = env.producer.record_current_all(owner_user_id=env.owner)
    by_source = {
        candidate.attestation.entry_source: candidate
        for candidate in candidates
    }
    api = by_source["api"]
    chat = by_source["chat"]
    api_coverage = env.entrypoints.coverage(
        next(item.coverage_ref for item in result.sources if item.entry_source == "api"),
        owner=env.owner,
    )

    forged_provisional = GoalValidationReceipt(
        validation_ref="",
        owner_user_id=env.owner,
        subject_qro_refs=api_coverage.qro_refs,
        graph_command_refs=api_coverage.research_graph_command_refs,
        validator_identifiers=(FULL_PRODUCT_VALIDATOR_IDENTIFIER,),
        test_identifiers=("runtime_check:forged_marker_only_v1",),
        outcome=GoalValidationOutcome.PASSED,
        evidence_refs=("evidence:forged_marker_only",),
        evidence_digests=(_digest("forged-marker-only"),),
    )
    forged_receipt = env.receipts.record_receipt(
        replace(
            forged_provisional,
            validation_ref=forged_provisional.canonical_validation_ref,
        )
    )
    forged_marker_coverage = replace(
        api_coverage,
        validation_refs=(forged_receipt.validation_ref,),
    )
    assert not env.attestations.validate_full_product_coverage(
        forged_marker_coverage,
        owner_user_id=env.owner,
    ).accepted

    wrong_source = replace(
        api_coverage,
        entry_source="chat",
        coverage_ref=goal_entrypoint_coverage_identity(
            entry_source="chat",
            entrypoint_ref=api_coverage.entrypoint_ref,
            goal_sections=api_coverage.goal_sections,
            qro_refs=api_coverage.qro_refs,
            research_graph_command_refs=api_coverage.research_graph_command_refs,
            compiler_ir_refs=api_coverage.compiler_ir_refs,
            compiler_pass_refs=api_coverage.compiler_pass_refs,
        ),
    )
    assert not env.attestations.validate_full_product_coverage(
        wrong_source,
        owner_user_id=env.owner,
    ).accepted
    assert not env.attestations.validate_full_product_coverage(
        replace(api_coverage, recorded_by="owner:bob"),
        owner_user_id=env.owner,
    ).accepted

    recombined = _canonical_attestation(
        api.attestation,
        base_coverage_ref=chat.attestation.base_coverage_ref,
        base_coverage_digest=chat.attestation.base_coverage_digest,
    )
    decision = env.attestations.validate_current(
        recombined,
        owner_user_id=env.owner,
    )
    assert not decision.accepted
    assert "goal_full_product_attestation_not_current" in {
        item.code for item in decision.violations
    }


def test_stale_semantic_and_section_heads_invalidate_old_attestation(tmp_path) -> None:
    env = _environment(tmp_path)
    old = env.attestations.prepare_current_source(
        owner_user_id=env.owner,
        entry_source="api",
    ).attestation
    section = "§2"
    newer_proof = _semantic_proof(
        owner=env.owner,
        section=section,
        coverage_ref=env.support[section].coverage_ref,
        variant="newer",
    )
    env.adapters[section].allow(newer_proof)
    env.semantic.record_proof(newer_proof)
    env.sections.record_coverage(
        _section_coverage(
            owner=env.owner,
            section=section,
            coverage_ref=env.support[section].coverage_ref,
            proof_ref=newer_proof.proof_ref,
            variant="newer",
        )
    )

    decision = env.attestations.validate_current(
        old,
        owner_user_id=env.owner,
    )
    assert not decision.accepted
    assert "goal_full_product_attestation_not_current" in {
        item.code for item in decision.violations
    }


def test_peer_api_base_and_lineage_head_invalidate_stale_instance_views(
    tmp_path,
) -> None:
    env = _environment(tmp_path)
    old_candidate = env.attestations.prepare_current_source(
        owner_user_id=env.owner,
        entry_source="api",
    )
    _commit_candidate_bundle(env, old_candidate)
    assert env.attestations.validate_current(
        old_candidate.attestation,
        owner_user_id=env.owner,
    ).accepted
    assert env.attestations.validate_full_product_coverage(
        old_candidate.coverage,
        owner_user_id=env.owner,
    ).accepted

    peer = _reopen_protocol(env)
    newer_api_base = _base_lineage(
        owner=env.owner,
        source="api",
        graph_store=env.graph_store,
        compiler_store=peer.compiler_store,
        receipt_registry=peer.receipts,
        entrypoint_registry=peer.entrypoints,
        document_store=env.documents,
        lifecycle_registry=env.lifecycle,
        rdp_store=env.rdps,
        include_closure=False,
        variant="external_newer",
    )
    newer_aggregate = peer.lineage_aggregates.record_current(
        owner_user_id=env.owner
    )
    assert newer_aggregate.aggregate_ref != env.lineage_aggregate.aggregate_ref

    stale_attestation_decision = env.attestations.validate_current(
        old_candidate.attestation,
        owner_user_id=env.owner,
    )
    assert not stale_attestation_decision.accepted
    assert "goal_full_product_attestation_not_current" in {
        item.code for item in stale_attestation_decision.violations
    }

    stale_coverage_decision = env.attestations.validate_full_product_coverage(
        old_candidate.coverage,
        owner_user_id=env.owner,
    )
    assert not stale_coverage_decision.accepted
    assert "goal_full_product_coverage_recombined_or_stale" in {
        item.code for item in stale_coverage_decision.violations
    }

    persisted = env.attestations.attestation(
        old_candidate.attestation.attestation_ref,
        owner_user_id=env.owner,
    )
    assert persisted == old_candidate.attestation
    current_rows = env.attestations.current_records_with_decisions(
        owner_user_id=env.owner
    )
    assert current_rows == ((persisted, stale_attestation_decision),)


def test_atomic_commit_failure_leaves_no_prefix_and_retry_finishes_once(
    tmp_path,
    monkeypatch,
) -> None:
    env = _environment(tmp_path)
    before = _protocol_counts(env)
    original = env.proof_ledger.commit
    failed = False

    def _fail_once(bundle):
        nonlocal failed
        if not failed:
            failed = True
            raise OSError("simulated atomic proof bundle failure")
        return original(bundle)

    monkeypatch.setattr(env.proof_ledger, "commit", _fail_once)
    with pytest.raises(GoalFullProductCommitError) as captured:
        env.producer.record_current_all(owner_user_id=env.owner)
    error = captured.value
    assert error.entry_source == ""
    assert error.stage is GoalFullProductCommitStage.FINAL_AGGREGATE
    assert error.completed_stages == ()
    assert error.compensation_attempted is False
    assert error.compensation_verified is False
    assert error.state_unchanged is True
    assert error.compensated is False
    assert error.compensation_error is None
    assert env.terminal_aggregates.records(owner_user_id=env.owner) == []
    reopened = _reopen_protocol(env)
    assert _protocol_counts(reopened) == before

    result = reopened.producer.record_current_all(owner_user_id=env.owner)
    assert len(result.sources) == len(REQUIRED_ENTRY_SOURCES)
    assert len(
        reopened.terminal_aggregates.records(owner_user_id=env.owner)
    ) == 1


def test_final_aggregate_is_blocked_if_proof_heads_move_during_commit(
    tmp_path,
    monkeypatch,
) -> None:
    env = _environment(tmp_path)
    before = _protocol_counts(env)
    original = env.producer._atomic_bundle
    moved = False
    base = env.bases[0]
    provisional_movement = GoalValidationReceipt(
        validation_ref="",
        owner_user_id=env.owner,
        subject_qro_refs=base.qro_refs,
        graph_command_refs=base.research_graph_command_refs,
        validator_identifiers=("runtime_validator:concurrent_move_v1",),
        test_identifiers=("pytest:goal_full_product:concurrent_move",),
        outcome=GoalValidationOutcome.PASSED,
        evidence_refs=base.evidence_refs,
        evidence_digests=tuple(_digest(ref) for ref in base.evidence_refs),
    )
    movement = replace(
        provisional_movement,
        validation_ref=provisional_movement.canonical_validation_ref,
    )

    def _move_before_digest_check(**kwargs):
        nonlocal moved
        bundle = original(**kwargs)
        if not moved:
            moved = True
            main._commit_canonical_goal_proof_bundle(
                owner=env.owner,
                subject="test_goal_full_product_concurrent_move",
                records=((movement, GOAL_VALIDATION_RECEIPT_PROOF_CODEC),),
                registries=(env.receipts,),
                metadata={"producer": "test_concurrent_move"},
            )
        return bundle

    monkeypatch.setattr(
        env.producer,
        "_atomic_bundle",
        _move_before_digest_check,
    )
    with pytest.raises(GoalFullProductCommitError) as captured:
        env.producer.record_current_all(owner_user_id=env.owner)
    assert captured.value.stage is GoalFullProductCommitStage.PREFLIGHT
    assert captured.value.compensation_attempted is False
    assert captured.value.compensation_verified is False
    assert env.terminal_aggregates.records(owner_user_id=env.owner) == []
    reopened = _reopen_protocol(env)
    partial = _protocol_counts(reopened)
    assert partial["attestations"] == before["attestations"]
    assert partial["receipts"] == before["receipts"] + 1
    assert partial["terminal_aggregates"] == 0
    result = reopened.producer.record_current_all(owner_user_id=env.owner)
    assert len(result.sources) == len(REQUIRED_ENTRY_SOURCES)
    assert len(
        reopened.terminal_aggregates.records(owner_user_id=env.owner)
    ) == 1


def test_atomic_commit_ack_loss_preserves_complete_bundle_for_retry(
    tmp_path,
    monkeypatch,
) -> None:
    env = _environment(tmp_path)
    before = _protocol_counts(env)
    original = env.proof_ledger.commit
    lost = False

    def _persist_then_lose_ack(bundle):
        nonlocal lost
        result = original(bundle)
        if not lost:
            lost = True
            raise OSError("simulated atomic bundle acknowledgement loss")
        return result

    monkeypatch.setattr(env.proof_ledger, "commit", _persist_then_lose_ack)

    with pytest.raises(GoalFullProductCommitError) as captured:
        env.producer.record_current_all(owner_user_id=env.owner)

    assert captured.value.stage is GoalFullProductCommitStage.FINAL_AGGREGATE
    assert captured.value.compensation_attempted is False
    assert captured.value.compensation_verified is False
    assert captured.value.state_unchanged is False
    reopened = _reopen_protocol(env)
    partial = _protocol_counts(reopened)
    assert partial["attestations"] == before["attestations"] + len(
        REQUIRED_ENTRY_SOURCES
    )
    assert partial["terminal_aggregates"] == 1
    result = reopened.producer.record_current_all(owner_user_id=env.owner)
    assert len(result.sources) == len(REQUIRED_ENTRY_SOURCES)
    assert len(
        reopened.terminal_aggregates.records(owner_user_id=env.owner)
    ) == 1


def test_terminal_aggregate_ack_loss_recovers_exact_persisted_result(
    tmp_path,
    monkeypatch,
) -> None:
    env = _environment(tmp_path)
    legacy_append_called = False

    def _legacy_append_forbidden(_row):
        nonlocal legacy_append_called
        legacy_append_called = True
        raise AssertionError("atomic path must not append a legacy aggregate")

    monkeypatch.setattr(
        env.terminal_aggregates,
        "_append",
        _legacy_append_forbidden,
    )

    result = env.producer.record_current_all(owner_user_id=env.owner)
    assert legacy_append_called is False
    reopened = _reopen_protocol(env)
    persisted = reopened.terminal_aggregates.aggregate(
        result.final_aggregate_ref,
        owner_user_id=env.owner,
    )
    assert persisted.coverage_refs == tuple(
        item.coverage_ref for item in result.sources
    )
    assert len(
        reopened.terminal_aggregates.records(owner_user_id=env.owner)
    ) == 1
    for coverage_ref in persisted.coverage_refs:
        assert (
            reopened.entrypoints.coverage(coverage_ref, owner=env.owner).coverage_ref
            == coverage_ref
        )


def test_reopened_atomic_bundle_retry_is_idempotent(tmp_path) -> None:
    env = _environment(tmp_path)
    first = env.producer.record_current_all(owner_user_id=env.owner)
    before = env.proof_ledger.current(owner=env.owner)

    reopened = _reopen_protocol(env)
    result = reopened.producer.record_current_all(owner_user_id=env.owner)
    assert result == first
    assert reopened.proof_ledger.current(owner=env.owner) == before
    assert len(
        reopened.terminal_aggregates.records(owner_user_id=env.owner)
    ) == 1
    assert len(reopened.attestations.records(owner_user_id=env.owner)) == len(
        REQUIRED_ENTRY_SOURCES
    )


def test_atomic_candidate_identity_mismatch_fails_closed_without_new_writes(
    tmp_path,
    monkeypatch,
) -> None:
    env = _environment(tmp_path)
    candidates = env.attestations.prepare_current_all(owner_user_id=env.owner)
    tampered = replace(
        candidates[0],
        attestation=replace(
            candidates[0].attestation,
            derived_ir_ref="compiler_ir:tampered",
        ),
    )
    before = _protocol_counts(env)

    monkeypatch.setattr(
        env.attestations,
        "_prepare_current_all_unlocked",
        lambda *, owner_user_id: (tampered, *candidates[1:]),
    )
    with pytest.raises(GoalFullProductCommitError) as captured:
        env.producer.record_current_all(owner_user_id=env.owner)

    error = captured.value
    assert error.stage is GoalFullProductCommitStage.PREFLIGHT
    assert "attestation" in str(error.cause)
    assert error.compensation_attempted is False
    assert error.compensation_verified is False
    assert error.state_unchanged is True
    assert _protocol_counts(env) == before


def test_independent_legacy_attestation_append_is_preserved_by_atomic_commit(
    tmp_path,
) -> None:
    env = _environment(tmp_path)
    external = _compatibility_attestation_registry(env)
    candidate = env.attestations.prepare_current_source(
        owner_user_id=env.owner,
        entry_source="api",
    )
    persisted = external.record_attestation(candidate.attestation)
    legacy_bytes = env.attestations.path.read_bytes()

    result = env.producer.record_current_all(owner_user_id=env.owner)
    assert len(result.sources) == len(REQUIRED_ENTRY_SOURCES)
    assert env.attestations.path.read_bytes() == legacy_bytes

    reopened = _reopen_protocol(env)
    assert reopened.attestations.attestation(
        persisted.attestation_ref,
        owner_user_id=env.owner,
    ) == persisted
    assert reopened.attestations.is_canonical_current(
        persisted,
        owner_user_id=env.owner,
    )


def test_external_semantic_head_is_refreshed_before_terminal_commit(tmp_path) -> None:
    env = _environment(tmp_path)
    section = "§2"
    newer = _semantic_proof(
        owner=env.owner,
        section=section,
        coverage_ref=env.support[section].coverage_ref,
        variant="external-process-newer",
    )
    env.adapters[section].allow(newer)
    external_semantic = PersistentGoalSectionSemanticProofRegistry(
        env.semantic.path,
        env.entrypoints,
        adapters=env.adapters,
    )
    external_semantic.record_proof(newer)
    external_sections = PersistentGoalSectionCoverageRegistry(
        env.sections.path,
        env.entrypoints,
        external_semantic,
    )
    external_sections.record_coverage(
        _section_coverage(
            owner=env.owner,
            section=section,
            coverage_ref=env.support[section].coverage_ref,
            proof_ref=newer.proof_ref,
            variant="external-process-newer",
        )
    )

    result = env.producer.record_current_all(owner_user_id=env.owner)
    reopened = _reopen_protocol(env)
    for item in result.sources:
        attestation = reopened.attestations.attestation(
            item.attestation_ref,
            owner_user_id=env.owner,
        )
        assert newer.proof_ref in attestation.semantic_proof_refs
        assert reopened.attestations.validate_current(
            attestation,
            owner_user_id=env.owner,
        ).accepted


def test_direct_attestation_write_refreshes_dependency_heads(tmp_path) -> None:
    env = _environment(tmp_path)
    stale_candidate = env.attestations.prepare_current_all(
        owner_user_id=env.owner
    )[0]
    section = "§2"
    newer = _semantic_proof(
        owner=env.owner,
        section=section,
        coverage_ref=env.support[section].coverage_ref,
        variant="external-before-direct-attestation",
    )
    env.adapters[section].allow(newer)
    external_semantic = PersistentGoalSectionSemanticProofRegistry(
        env.semantic.path,
        env.entrypoints,
        adapters=env.adapters,
    )
    external_semantic.record_proof(newer)
    external_sections = PersistentGoalSectionCoverageRegistry(
        env.sections.path,
        env.entrypoints,
        external_semantic,
    )
    external_sections.record_coverage(
        _section_coverage(
            owner=env.owner,
            section=section,
            coverage_ref=env.support[section].coverage_ref,
            proof_ref=newer.proof_ref,
            variant="external-before-direct-attestation",
        )
    )

    with pytest.raises(
        ValueError,
        match=(
            "goal_full_product_attestation_not_current|"
            "goal_full_product_attestation_current_snapshot_unavailable"
        ),
    ):
        env.attestations.record_attestation(stale_candidate.attestation)

    reopened = _reopen_protocol(env)
    assert reopened.attestations.records(owner_user_id=env.owner) == []


def test_terminal_full_rows_cannot_become_semantic_or_section_upstream(
    tmp_path,
) -> None:
    env = _environment(tmp_path)
    result = env.producer.record_current_all(owner_user_id=env.owner)
    api_terminal = env.entrypoints.coverage(
        next(item.coverage_ref for item in result.sources if item.entry_source == "api"),
        owner=env.owner,
    )
    section = "§2"
    cyclic_proof = _semantic_proof(
        owner=env.owner,
        section=section,
        coverage_ref=api_terminal.coverage_ref,
        variant="terminal-upstream",
    )
    env.adapters[section].allow(cyclic_proof)
    semantic_before = env.semantic.path.read_bytes()
    section_before = env.sections.path.read_bytes()
    with pytest.raises(
        ValueError,
        match="goal_semantic_terminal_entrypoint_forbidden",
    ):
        env.semantic.record_proof(cyclic_proof)
    assert env.semantic.path.read_bytes() == semantic_before
    assert cyclic_proof not in env.semantic.records(owner=env.owner, section=section)

    with pytest.raises(
        ValueError,
        match="goal_section_semantic_proof_unknown",
    ):
        env.sections.record_coverage(
            _section_coverage(
                owner=env.owner,
                section=section,
                coverage_ref=api_terminal.coverage_ref,
                proof_ref=cyclic_proof.proof_ref,
                variant="terminal-upstream",
            )
        )
    assert env.sections.path.read_bytes() == section_before

    snapshot = env.attestations.build_current_snapshot(owner_user_id=env.owner)
    assert snapshot.owner_user_id == env.owner


def test_main_full_product_endpoint_derives_all_refs_and_is_idempotent(
    tmp_path,
    monkeypatch,
) -> None:
    env = _environment(tmp_path)
    monkeypatch.setattr(
        main,
        "GOAL_FULL_PRODUCT_ENTRYPOINT_PRODUCER",
        env.producer,
    )
    monkeypatch.setattr(
        main,
        "GOAL_FULL_PRODUCT_ATTESTATION_REGISTRY",
        env.attestations,
    )
    main.app.dependency_overrides[require_user_dependency] = lambda: SimpleNamespace(
        username="alice",
        user_id=env.owner,
    )
    client = TestClient(main.app)
    try:
        first = client.post(
            "/api/research-os/goal/full_product_entrypoints/current",
            json={
                "coverage_ref": "caller:forged",
                "claims_full_product_entrypoint": False,
            },
        )
        assert first.status_code == 200, first.text
        body = first.json()
        assert body["full_product_entrypoint_total"] == len(REQUIRED_ENTRY_SOURCES)
        assert tuple(item["entry_source"] for item in body["sources"]) == (
            REQUIRED_ENTRY_SOURCES
        )
        assert all(
            item["coverage_ref"] != "caller:forged" for item in body["sources"]
        )

        second = client.post(
            "/api/research-os/goal/full_product_entrypoints/current"
        )
        assert second.status_code == 200, second.text
        assert second.json() == body

        summary = client.get(
            "/api/research-os/goal/full_product_entrypoints"
        )
        assert summary.status_code == 200, summary.text
        assert summary.json()["attestation_total"] == len(REQUIRED_ENTRY_SOURCES)
        assert summary.json()["current_attestation_total"] == len(
            REQUIRED_ENTRY_SOURCES
        )
    finally:
        main.app.dependency_overrides.pop(require_user_dependency, None)


def test_main_full_product_endpoint_exposes_forward_only_failure_state(monkeypatch) -> None:
    class _FailingProducer:
        def record_current_all(self, *, owner_user_id: str):
            raise GoalFullProductCommitError(
                entry_source="api",
                stage=GoalFullProductCommitStage.COVERAGE,
                completed_stages=("attestation", "validation_receipt"),
                cause=OSError("durable coverage append unavailable"),
                compensation_attempted=False,
                compensation_verified=False,
                state_unchanged=False,
            )

    monkeypatch.setattr(main, "GOAL_FULL_PRODUCT_ENTRYPOINT_PRODUCER", _FailingProducer())
    main.app.dependency_overrides[require_user_dependency] = lambda: SimpleNamespace(
        username="alice",
        user_id=OWNER,
    )
    try:
        response = TestClient(main.app).post(
            "/api/research-os/goal/full_product_entrypoints/current"
        )
    finally:
        main.app.dependency_overrides.pop(require_user_dependency, None)

    assert response.status_code == 409, response.text
    detail = response.json()["detail"]
    assert detail["compensated"] is False
    assert detail["compensation_attempted"] is False
    assert detail["compensation_verified"] is False
    assert detail["state_unchanged"] is False
    assert detail["compensation_error"] == ""
