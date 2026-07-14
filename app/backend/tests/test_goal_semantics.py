from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app import main
from app.auth import require_user_dependency
from app.research_os.goal_coverage import (
    GoalEntrypointCoverageRecord,
    GoalSectionCoverageRecord,
    PersistentGoalEntrypointCoverageRegistry,
    PersistentGoalSectionCoverageRegistry,
    REQUIRED_ENTRY_SOURCES,
    REQUIRED_GOAL_SECTIONS,
    goal_entrypoint_coverage_identity,
)
from app.research_os.goal_entrypoint_aggregate import (
    GoalEntrypointAggregateRecord,
    PersistentGoalEntrypointAggregateRegistry,
)
from app.research_os.goal_entrypoint_lineage_aggregate import (
    CORE_GOAL_SECTIONS,
    GoalEntrypointLineageAggregateRecord,
    PersistentGoalEntrypointLineageAggregateRegistry,
)
from app.research_os.goal_semantic_adapters import EntrypointLineageSectionAdapter
from app.research_os.goal_semantics import (
    GoalSectionSemanticProofRecord,
    GoalSemanticDecision,
    GoalSemanticViolation,
    PersistentGoalSectionSemanticProofRegistry,
    goal_section_semantic_proof_identity,
    validate_goal_section_semantic_proof,
)
from app.research_os.ref_resolution import build_real_ref_resolver


@dataclass(frozen=True)
class _LifecycleRecord:
    lifecycle_ref: str
    owner_user_id: str
    recorded_by: str


class _LifecycleStore:
    def __init__(self) -> None:
        self._records: dict[tuple[str, str], _LifecycleRecord] = {}

    def add(self, *, ref: str, owner: str) -> None:
        self._records[(owner, ref)] = _LifecycleRecord(
            lifecycle_ref=ref,
            owner_user_id=owner,
            recorded_by=owner,
        )

    def load(self, ref: str, owner: str) -> _LifecycleRecord:
        return self._records[(owner, ref)]


@dataclass(frozen=True)
class _RDPManifest:
    manifest_id: str
    owner_user_id: str


class _RDPStore:
    def __init__(self) -> None:
        self._records: dict[tuple[str, str], _RDPManifest] = {}

    def add(self, *, ref: str, owner: str) -> None:
        self._records[(owner, ref)] = _RDPManifest(
            manifest_id=ref,
            owner_user_id=owner,
        )

    def manifest(self, ref: str, *, owner_user_id: str) -> _RDPManifest:
        return self._records[(owner_user_id, ref)]


class _EntryResolver:
    def __init__(
        self,
        refs: set[str],
        *,
        closure_resolver=None,
        lifecycle_store: _LifecycleStore | None = None,
        rdp_store: _RDPStore | None = None,
        bound_owner: str | None = None,
    ) -> None:
        self._refs = refs
        self._closure_resolver = closure_resolver
        self._lifecycle_store = lifecycle_store
        self._rdp_store = rdp_store
        self._bound_owner = bound_owner

    def for_owner(self, owner: str):
        return _EntryResolver(
            self._refs,
            closure_resolver=self._closure_resolver,
            lifecycle_store=self._lifecycle_store,
            rdp_store=self._rdp_store,
            bound_owner=owner,
        )

    def register_full_product_closure(
        self,
        coverage: GoalEntrypointCoverageRecord,
    ) -> None:
        if self._lifecycle_store is None or self._rdp_store is None:
            raise RuntimeError("typed full-product closure stores are unavailable")
        for ref in coverage.lifecycle_refs:
            self._lifecycle_store.add(ref=ref, owner=coverage.recorded_by)
        for ref in coverage.rdp_refs:
            self._rdp_store.add(ref=ref, owner=coverage.recorded_by)

    def has_qro(self, ref: str) -> bool:
        return ref in self._refs

    def has_research_graph_command(self, ref: str) -> bool:
        return ref in self._refs

    def has_compiler_ir(self, ref: str) -> bool:
        return ref in self._refs

    def has_compiler_pass(self, ref: str) -> bool:
        return ref in self._refs

    def has_evidence(self, ref: str) -> bool:
        return ref in self._refs

    def has_lifecycle_record(self, ref: str) -> bool:
        if self._closure_resolver is None:
            return ref in self._refs
        if self._bound_owner is None:
            return False
        return self._closure_resolver.for_owner(
            self._bound_owner
        ).has_lifecycle_record(ref)

    def has_rdp(self, ref: str) -> bool:
        if self._closure_resolver is None:
            return ref in self._refs
        if self._bound_owner is None:
            return False
        return self._closure_resolver.for_owner(self._bound_owner).has_rdp(ref)

    def entrypoint_linkage_violations(self, record) -> tuple:
        return ()


def _full_product_entry_resolver(
    refs: set[str],
    coverages: tuple[GoalEntrypointCoverageRecord, ...],
) -> _EntryResolver:
    lifecycle = _LifecycleStore()
    rdp = _RDPStore()
    closure = build_real_ref_resolver(
        research_graph_store=SimpleNamespace(),
        lifecycle_registry=None,
        governance_registry=None,
        rag_index=None,
        spine_chain_registry=None,
        rdp_store=rdp,
        lifecycle_loaders=(lifecycle.load,),
    )
    resolver = _EntryResolver(
        refs,
        closure_resolver=closure,
        lifecycle_store=lifecycle,
        rdp_store=rdp,
    )
    for coverage in coverages:
        resolver.register_full_product_closure(coverage)
    return resolver


def _entrypoint(
    owner: str,
    section: str = "§6",
    *,
    source: str = "api",
    full_product: bool = False,
    variant: str = "semantic-proof",
    goal_sections: tuple[str, ...] | None = None,
) -> GoalEntrypointCoverageRecord:
    sections = (
        tuple(goal_sections)
        if goal_sections is not None
        else (REQUIRED_GOAL_SECTIONS if full_product else (section,))
    )
    data = {
        "entry_source": source,
        "entrypoint_ref": f"route:{source}:{variant}",
        "goal_sections": sections,
        "qro_refs": (f"qro:{source}:{variant}",),
        "research_graph_command_refs": (f"rgcmd:{source}:{variant}",),
        "compiler_ir_refs": (f"compiler_ir:{source}:{variant}",),
        "compiler_pass_refs": (f"compiler_pass:{source}:{variant}",),
        "evidence_refs": (f"evidence:{source}:{variant}",),
        "validation_refs": (f"validation:{source}:{variant}",),
        "permission_refs": (f"permission:{source}:{variant}",),
        "replay_refs": (
            f"replay:research_graph:rgcmd:{source}:{variant}",
            f"replay:compiler_ir:compiler_ir:{source}:{variant}",
            f"replay:compiler_pass:compiler_pass:{source}:{variant}",
        ),
        "canonical_command_refs": (f"command:{source}:{variant}",),
        "lifecycle_refs": (
            (f"asset_lifecycle:{source}:{variant}",) if full_product else ()
        ),
        "rdp_refs": (
            (f"rdp_manifest:{source}:{variant}",) if full_product else ()
        ),
        "recorded_by": owner,
        "claims_full_product_entrypoint": full_product,
    }
    data["coverage_ref"] = goal_entrypoint_coverage_identity(
        entry_source=data["entry_source"],
        entrypoint_ref=data["entrypoint_ref"],
        goal_sections=data["goal_sections"],
        qro_refs=data["qro_refs"],
        research_graph_command_refs=data["research_graph_command_refs"],
        compiler_ir_refs=data["compiler_ir_refs"],
        compiler_pass_refs=data["compiler_pass_refs"],
    )
    return GoalEntrypointCoverageRecord(**data)


def _entrypoint_store(tmp_path, *owners: str) -> tuple[PersistentGoalEntrypointCoverageRegistry, str]:
    first = _entrypoint(owners[0])
    refs = {
        *first.qro_refs,
        *first.research_graph_command_refs,
        *first.compiler_ir_refs,
        *first.compiler_pass_refs,
        *first.evidence_refs,
    }
    store = PersistentGoalEntrypointCoverageRegistry(
        tmp_path / "entrypoints.jsonl",
        resolver=_EntryResolver(refs),
    )
    for owner in owners:
        store.record_coverage(_entrypoint(owner))
    return store, first.coverage_ref


def _entrypoint_aggregate_proof(
    owner: str,
    section: str,
    coverages: tuple[GoalEntrypointCoverageRecord, ...],
    aggregate: GoalEntrypointAggregateRecord | GoalEntrypointLineageAggregateRecord,
) -> GoalSectionSemanticProofRecord:
    data = {
        "section": section,
        "subject_ref": (
            f"goal_section:{section}:entrypoint_aggregate:{aggregate.aggregate_ref}"
        ),
        "producer_refs": tuple(
            ref
            for coverage in coverages
            for ref in coverage.research_graph_command_refs
        ),
        "store_refs": tuple(
            [aggregate.aggregate_ref]
            + [coverage.coverage_ref for coverage in coverages]
            + [ref for coverage in coverages for ref in coverage.qro_refs]
            + [ref for coverage in coverages for ref in coverage.compiler_ir_refs]
            + [ref for coverage in coverages for ref in coverage.compiler_pass_refs]
        ),
        "consumer_refs": tuple(coverage.entrypoint_ref for coverage in coverages),
        "gate_verdict_refs": (aggregate.aggregate_ref,),
        "test_refs": tuple(
            ref for coverage in coverages for ref in coverage.validation_refs
        ),
        "entrypoint_coverage_refs": tuple(
            coverage.coverage_ref for coverage in coverages
        ),
        "recorded_by": owner,
        "claims_section_complete": True,
        "unverified_residuals": (),
    }
    data["proof_ref"] = goal_section_semantic_proof_identity(**data)
    return GoalSectionSemanticProofRecord(**data)


def _proof(owner: str, coverage_ref: str, **overrides) -> GoalSectionSemanticProofRecord:
    data = {
        "section": "§6",
        "subject_ref": "math_spine_chain:semantic-proof",
        "producer_refs": ("producer:math-spine:semantic-proof",),
        "store_refs": ("math_spine_chain:semantic-proof",),
        "consumer_refs": ("consumer:promote:semantic-proof",),
        "gate_verdict_refs": ("gate_verdict:section6:semantic-proof",),
        "test_refs": ("pytest:test_goal_semantics:section6",),
        "entrypoint_coverage_refs": (coverage_ref,),
        "recorded_by": owner,
        "claims_section_complete": True,
        "unverified_residuals": (),
    }
    data.update(overrides)
    data["proof_ref"] = goal_section_semantic_proof_identity(**data)
    return GoalSectionSemanticProofRecord(**data)


class _KnownSemanticAdapter:
    def __init__(self, known_refs: set[str]) -> None:
        self._known_refs = known_refs

    def validate(self, record, *, owner: str) -> GoalSemanticDecision:
        violations = []
        for field_name in (
            "producer_refs",
            "store_refs",
            "consumer_refs",
            "gate_verdict_refs",
            "test_refs",
        ):
            for ref in getattr(record, field_name):
                if ref not in self._known_refs:
                    violations.append(
                        GoalSemanticViolation(
                            "goal_semantic_ref_not_backed",
                            "adapter did not resolve the claimed semantic ref",
                            field=field_name,
                            ref=ref,
                        )
                    )
        return GoalSemanticDecision(not violations, tuple(violations))


def _adapter_for(record: GoalSectionSemanticProofRecord) -> _KnownSemanticAdapter:
    return _KnownSemanticAdapter(
        {
            *record.producer_refs,
            *record.store_refs,
            *record.consumer_refs,
            *record.gate_verdict_refs,
            *record.test_refs,
        }
    )


def test_semantic_proof_content_identity_and_placeholder_gate():
    record = _proof("alice", "entrypoint:real")
    assert validate_goal_section_semantic_proof(record).accepted

    poisoned = _proof(
        "alice",
        "entrypoint:real",
        store_refs=("goal_closure:math_spine",),
    )
    decision = validate_goal_section_semantic_proof(poisoned)
    assert not decision.accepted
    assert {item.code for item in decision.violations} == {
        "goal_semantic_placeholder_ref"
    }

    mismatched = replace(record, subject_ref="math_spine_chain:different")
    assert "goal_semantic_identity_mismatch" in {
        item.code for item in validate_goal_section_semantic_proof(mismatched).violations
    }


def test_semantic_proof_missing_adapter_rejects_without_partial_write(tmp_path):
    entrypoints, coverage_ref = _entrypoint_store(tmp_path, "alice")
    store = PersistentGoalSectionSemanticProofRegistry(
        tmp_path / "semantic.jsonl",
        entrypoints,
    )
    record = _proof("alice", coverage_ref)

    with pytest.raises(ValueError, match="goal_semantic_adapter_unavailable"):
        store.record_proof(record)

    assert store.records() == []
    assert not store.path.exists()


def test_semantic_proof_rejects_terminal_entrypoint_without_partial_write(
    tmp_path,
):
    owner = "alice"
    terminal = _entrypoint(
        owner,
        source="api",
        full_product=True,
        variant="terminal-semantic-upstream",
    )
    refs = {
        *terminal.qro_refs,
        *terminal.research_graph_command_refs,
        *terminal.compiler_ir_refs,
        *terminal.compiler_pass_refs,
        *terminal.evidence_refs,
    }
    entrypoints = PersistentGoalEntrypointCoverageRegistry(
        tmp_path / "terminal-entrypoints.jsonl",
        resolver=_full_product_entry_resolver(refs, (terminal,)),
    )
    entrypoints.record_coverage(terminal)
    proof = _proof(owner, terminal.coverage_ref)
    semantic = PersistentGoalSectionSemanticProofRegistry(
        tmp_path / "terminal-semantic.jsonl",
        entrypoints,
        adapters={"§6": _adapter_for(proof)},
    )

    before_records = semantic.records(owner=owner, section="§6")
    with pytest.raises(
        ValueError,
        match="goal_semantic_terminal_entrypoint_forbidden",
    ):
        semantic.record_proof(proof)

    assert before_records == []
    assert semantic.records(owner=owner, section="§6") == []
    assert not semantic.path.exists()


def test_semantic_proof_allows_real_cross_section_support_but_requires_primary_lineage(
    tmp_path,
):
    owner = "alice"
    primary = _entrypoint(owner, section="§6", variant="primary-section6")
    supporting = _entrypoint(owner, section="§14", variant="support-platform")
    refs = {
        *primary.qro_refs,
        *primary.research_graph_command_refs,
        *primary.compiler_ir_refs,
        *primary.compiler_pass_refs,
        *primary.evidence_refs,
        *supporting.qro_refs,
        *supporting.research_graph_command_refs,
        *supporting.compiler_ir_refs,
        *supporting.compiler_pass_refs,
        *supporting.evidence_refs,
    }
    entrypoints = PersistentGoalEntrypointCoverageRegistry(
        tmp_path / "entrypoints-cross-section.jsonl",
        resolver=_EntryResolver(refs),
    )
    entrypoints.record_coverage(primary)
    entrypoints.record_coverage(supporting)

    aggregate = _proof(
        owner,
        primary.coverage_ref,
        entrypoint_coverage_refs=(primary.coverage_ref, supporting.coverage_ref),
    )
    registry = PersistentGoalSectionSemanticProofRegistry(
        tmp_path / "semantic-cross-section.jsonl",
        entrypoints,
        adapters={"§6": _adapter_for(aggregate)},
    )
    assert registry.validate_real_backing(aggregate, owner=owner).accepted

    supporting_only = _proof(
        owner,
        supporting.coverage_ref,
        entrypoint_coverage_refs=(supporting.coverage_ref,),
    )
    decision = registry.validate_real_backing(supporting_only, owner=owner)
    assert not decision.accepted
    assert "goal_semantic_primary_entrypoint_missing" in {
        item.code for item in decision.violations
    }


def test_semantic_proof_adapter_persists_replays_and_rejects_mutation_atomically(tmp_path):
    entrypoints, coverage_ref = _entrypoint_store(tmp_path, "alice")
    record = _proof("alice", coverage_ref)
    adapter = _adapter_for(record)
    path = tmp_path / "semantic.jsonl"
    store = PersistentGoalSectionSemanticProofRegistry(
        path,
        entrypoints,
        adapters={"§6": adapter},
    )

    assert store.record_proof(record) == record
    before = path.read_bytes()
    poisoned = _proof(
        "alice",
        coverage_ref,
        store_refs=("math_spine_chain:missing",),
    )
    with pytest.raises(ValueError, match="goal_semantic_ref_not_backed"):
        store.record_proof(poisoned)
    assert path.read_bytes() == before
    assert store.records(owner="alice", section="§6") == [record]

    reloaded = PersistentGoalSectionSemanticProofRegistry(
        path,
        entrypoints,
        adapters={"§6": adapter},
    )
    assert reloaded.proof(record.proof_ref, owner="alice") == record
    assert reloaded.validate_real_backing(record, owner="alice").accepted


def test_semantic_proof_registry_isolates_owners_and_entrypoint_refs(tmp_path):
    entrypoints, coverage_ref = _entrypoint_store(tmp_path, "alice", "bob")
    alice = _proof("alice", coverage_ref)
    bob = _proof("bob", coverage_ref)
    adapter = _adapter_for(alice)
    store = PersistentGoalSectionSemanticProofRegistry(
        tmp_path / "semantic.jsonl",
        entrypoints,
        adapters={"§6": adapter},
    )

    store.record_proof(alice)
    store.record_proof(bob)

    assert store.proof(alice.proof_ref, owner="alice").recorded_by == "alice"
    assert store.proof(bob.proof_ref, owner="bob").recorded_by == "bob"
    assert len(store.records(owner="alice")) == 1
    assert len(store.records(owner="bob")) == 1
    wrong_owner = store.validate_real_backing(alice, owner="bob")
    assert "goal_semantic_owner_mismatch" in {
        item.code for item in wrong_owner.violations
    }


def test_public_reads_reload_cross_instance_coverage_semantic_and_aggregate_heads(
    tmp_path,
):
    owner = "alice"
    coverage = _entrypoint(owner, variant="current-read")
    coverage_refs = {
        *coverage.qro_refs,
        *coverage.research_graph_command_refs,
        *coverage.compiler_ir_refs,
        *coverage.compiler_pass_refs,
        *coverage.evidence_refs,
    }
    entrypoint_path = tmp_path / "current-read-entrypoints.jsonl"
    entrypoint_reader = PersistentGoalEntrypointCoverageRegistry(
        entrypoint_path,
        resolver=_EntryResolver(coverage_refs),
    )
    entrypoint_writer = PersistentGoalEntrypointCoverageRegistry(
        entrypoint_path,
        resolver=_EntryResolver(coverage_refs),
    )
    entrypoint_writer.record_coverage(coverage)

    assert entrypoint_reader.coverage(coverage.coverage_ref, owner=owner) == coverage
    assert entrypoint_reader.records(owner=owner) == [coverage]

    proof = _proof(owner, coverage.coverage_ref)
    semantic_path = tmp_path / "current-read-semantic.jsonl"
    semantic_reader = PersistentGoalSectionSemanticProofRegistry(
        semantic_path,
        entrypoint_reader,
        adapters={"§6": _adapter_for(proof)},
    )
    semantic_writer = PersistentGoalSectionSemanticProofRegistry(
        semantic_path,
        entrypoint_writer,
        adapters={"§6": _adapter_for(proof)},
    )
    semantic_writer.record_proof(proof)

    assert semantic_reader.proof(proof.proof_ref, owner=owner) == proof
    assert semantic_reader.records(owner=owner, section="§6") == [proof]

    terminal_coverages = tuple(
        _entrypoint(
            owner,
            source=source,
            full_product=True,
            variant="current-read-terminal",
        )
        for source in REQUIRED_ENTRY_SOURCES
    )
    terminal_refs = {
        ref
        for item in terminal_coverages
        for ref in (
            *item.qro_refs,
            *item.research_graph_command_refs,
            *item.compiler_ir_refs,
            *item.compiler_pass_refs,
            *item.evidence_refs,
        )
    }
    terminal_entrypoints = PersistentGoalEntrypointCoverageRegistry(
        tmp_path / "current-read-terminal-entrypoints.jsonl",
        resolver=_full_product_entry_resolver(terminal_refs, terminal_coverages),
    )
    for item in terminal_coverages:
        terminal_entrypoints.record_coverage(item)
    aggregate_path = tmp_path / "current-read-aggregates.jsonl"
    aggregate_reader = PersistentGoalEntrypointAggregateRegistry(
        aggregate_path,
        terminal_entrypoints,
    )
    aggregate_writer = PersistentGoalEntrypointAggregateRegistry(
        aggregate_path,
        terminal_entrypoints,
    )
    aggregate = aggregate_writer.record_current(owner_user_id=owner)

    assert aggregate_reader.aggregate(
        aggregate.aggregate_ref,
        owner_user_id=owner,
    ) == aggregate
    assert aggregate_reader.records(owner_user_id=owner) == [aggregate]


def test_section_manifest_binds_real_semantic_proof_and_rejects_unknown_ref_atomically(tmp_path):
    entrypoints, coverage_ref = _entrypoint_store(tmp_path, "alice")
    proof = _proof("alice", coverage_ref)
    semantic_store = PersistentGoalSectionSemanticProofRegistry(
        tmp_path / "semantic.jsonl",
        entrypoints,
        adapters={"§6": _adapter_for(proof)},
    )
    semantic_store.record_proof(proof)
    section_path = tmp_path / "sections.jsonl"
    section_store = PersistentGoalSectionCoverageRegistry(
        section_path,
        entrypoints,
        semantic_store,
    )
    section_record = GoalSectionCoverageRecord(
        section="§6",
        contract_refs=("contract:goal:section6",),
        test_refs=("pytest:test_goal_semantics:section6",),
        task_refs=("task:section6:math-spine",),
        evidence_refs=("evidence:semantic-proof",),
        recorded_by="alice",
        full_entrypoint_wired=True,
        entrypoint_wiring_refs=(coverage_ref,),
        semantic_proof_refs=(proof.proof_ref,),
    )

    assert section_store.record_coverage(section_record) == section_record
    before = section_path.read_bytes()
    poisoned = replace(
        section_record,
        section="§7",
        semantic_proof_refs=("goal_section_semantic_proof:missing",),
    )
    with pytest.raises(ValueError, match="goal_section_semantic_proof_unknown"):
        section_store.record_coverage(poisoned)
    assert section_path.read_bytes() == before
    assert section_store.records(owner="alice") == [section_record]

    updated = replace(
        section_record,
        evidence_refs=("evidence:semantic-proof:v2",),
    )
    assert section_store.record_coverage(updated) == updated
    assert section_store.coverage("§6", owner="alice") == updated
    reloaded_sections = PersistentGoalSectionCoverageRegistry(
        section_path,
        entrypoints,
        semantic_store,
    )
    assert reloaded_sections.coverage("§6", owner="alice") == updated


def test_entrypoint_lineage_adapter_requires_all_six_real_backed_sources(tmp_path):
    owner = "alice"
    coverages = tuple(
        _entrypoint(
            owner,
            section="§1",
            source=source,
            goal_sections=CORE_GOAL_SECTIONS,
        )
        for source in REQUIRED_ENTRY_SOURCES
    )
    refs = {
        ref
        for coverage in coverages
        for ref in (
            *coverage.qro_refs,
            *coverage.research_graph_command_refs,
            *coverage.compiler_ir_refs,
            *coverage.compiler_pass_refs,
            *coverage.evidence_refs,
        )
    }
    resolver = _EntryResolver(refs)
    entrypoints = PersistentGoalEntrypointCoverageRegistry(
        tmp_path / "aggregate_entrypoints.jsonl",
        resolver=resolver,
    )
    for coverage in coverages:
        entrypoints.record_coverage(coverage)
    aggregates = PersistentGoalEntrypointLineageAggregateRegistry(
        tmp_path / "entrypoint_aggregates.jsonl",
        entrypoints,
    )
    aggregate = aggregates.record_current(owner_user_id=owner)
    semantic_path = tmp_path / "aggregate_semantic.jsonl"
    semantic_store = PersistentGoalSectionSemanticProofRegistry(
        semantic_path,
        entrypoints,
        adapters={
            "§1": EntrypointLineageSectionAdapter(
                entrypoints,
                aggregates,
                section="§1",
            )
        },
    )
    complete = _entrypoint_aggregate_proof(owner, "§1", coverages, aggregate)

    assert semantic_store.record_proof(complete) == complete
    before = semantic_path.read_bytes()
    missing_scheduler = tuple(
        coverage
        for coverage in coverages
        if coverage.entry_source != "scheduler"
    )
    partial = _entrypoint_aggregate_proof(
        owner,
        "§1",
        missing_scheduler,
        aggregate,
    )
    with pytest.raises(ValueError, match="goal_semantic_entrypoint_aggregate_invalid"):
        semantic_store.record_proof(partial)
    assert semantic_path.read_bytes() == before
    assert semantic_store.records(owner=owner, section="§1") == [complete]

    newer_api = _entrypoint(
        owner,
        section="§1",
        source="api",
        variant="semantic-proof-v2",
        goal_sections=CORE_GOAL_SECTIONS,
    )
    resolver._refs.update(
        {
            *newer_api.qro_refs,
            *newer_api.research_graph_command_refs,
            *newer_api.compiler_ir_refs,
            *newer_api.compiler_pass_refs,
            *newer_api.evidence_refs,
        }
    )
    entrypoints.record_coverage(newer_api)
    assert (
        "goal_entrypoint_lineage_aggregate_not_current"
        in aggregates.validate_current(
            aggregate,
            owner_user_id=owner,
        )
    )
    assert not semantic_store.validate_real_backing(
        complete,
        owner=owner,
    ).accepted


def test_current_entrypoint_aggregate_api_uses_authenticated_owner(
    tmp_path,
    monkeypatch,
):
    owner = "alice-id"
    coverages = tuple(
        _entrypoint(owner, source=source, full_product=True)
        for source in REQUIRED_ENTRY_SOURCES
    )
    refs = {
        ref
        for coverage in coverages
        for ref in (
            *coverage.qro_refs,
            *coverage.research_graph_command_refs,
            *coverage.compiler_ir_refs,
            *coverage.compiler_pass_refs,
            *coverage.evidence_refs,
        )
    }
    resolver = _full_product_entry_resolver(refs, coverages)
    entrypoints = PersistentGoalEntrypointCoverageRegistry(
        tmp_path / "api_entrypoints.jsonl",
        resolver=resolver,
    )
    for coverage in coverages:
        entrypoints.record_coverage(coverage)
    aggregates = PersistentGoalEntrypointAggregateRegistry(
        tmp_path / "api_aggregates.jsonl",
        entrypoints,
    )
    monkeypatch.setattr(main, "GOAL_ENTRYPOINT_AGGREGATE_REGISTRY", aggregates)
    main.app.dependency_overrides[require_user_dependency] = lambda: SimpleNamespace(
        username="alice-display",
        user_id=owner,
    )
    try:
        client = TestClient(main.app)
        recorded = client.post(
            "/api/research-os/goal/entrypoint_aggregates/current"
        )
        assert recorded.status_code == 200, recorded.text
        assert recorded.json()["recorded_by"] == owner
        assert len(recorded.json()["coverage_refs"]) == len(REQUIRED_ENTRY_SOURCES)

        summary = client.get("/api/research-os/goal/entrypoint_aggregates")
        assert summary.status_code == 200
        assert summary.json()["total"] == 1
        assert summary.json()["aggregates"][0]["current"] is True
    finally:
        main.app.dependency_overrides.pop(require_user_dependency, None)


def test_semantic_proof_api_rejects_direct_proof_write(tmp_path, monkeypatch):
    entrypoints, coverage_ref = _entrypoint_store(tmp_path, "alice")
    proof = _proof("alice", coverage_ref)
    semantic_store = PersistentGoalSectionSemanticProofRegistry(
        tmp_path / "api_semantic.jsonl",
        entrypoints,
        adapters={"§6": _adapter_for(proof)},
    )
    monkeypatch.setattr(
        main,
        "GOAL_SECTION_SEMANTIC_PROOF_REGISTRY",
        semantic_store,
    )
    main.app.dependency_overrides[require_user_dependency] = lambda: SimpleNamespace(
        username="same-display-name",
        user_id="alice",
    )
    try:
        payload = asdict(proof)
        payload["recorded_by"] = "spoofed-client"
        response = TestClient(main.app).post(
            "/api/research-os/goal/section_semantic_proofs",
            json=payload,
        )
        assert response.status_code == 422, response.text
        assert "direct GOAL section semantic proof writes are disabled" in response.text
        assert semantic_store.records(owner="alice") == []

        summary = TestClient(main.app).get(
            "/api/research-os/goal/section_semantic_proofs/summary"
        )
        assert summary.status_code == 200
        body = summary.json()
        assert body["proof_total"] == 0
        assert body["strictly_backed_proof_total"] == 0
        assert body["sections_with_complete_semantic_proof"] == []
        assert body["proofs"] == []
    finally:
        main.app.dependency_overrides.pop(require_user_dependency, None)
