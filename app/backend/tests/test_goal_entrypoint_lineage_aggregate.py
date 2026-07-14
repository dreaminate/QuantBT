from __future__ import annotations

import json
from dataclasses import asdict, replace

import pytest

from app.research_os.goal_coverage import (
    GOAL_ENTRYPOINT_COVERAGE_PROOF_CODEC,
    GoalEntrypointCoverageRecord,
    PersistentGoalEntrypointCoverageRegistry,
    REQUIRED_ENTRY_SOURCES,
    REQUIRED_GOAL_SECTIONS,
    goal_entrypoint_coverage_identity,
)
from app.research_os.goal_proof_ledger import GoalProofLedger, ProofBundle
from app.research_os.goal_proof_records import typed_proof_record_member
from app.research_os.goal_entrypoint_lineage_aggregate import (
    CORE_GOAL_SECTIONS,
    PersistentGoalEntrypointLineageAggregateRegistry,
)
from app.research_os.ref_resolution import build_real_ref_resolver


class _OwnerLifecycleStore:
    def __init__(self) -> None:
        self._owners: dict[str, str] = {}

    def add(self, ref: str, *, owner: str) -> None:
        self._owners[ref] = owner

    def governed_asset(self, ref: str, *, owner_user_id: str):
        if self._owners.get(ref) != owner_user_id:
            raise KeyError(ref)
        return type("LifecycleRecord", (), {"owner_user_id": owner_user_id})()


class _OwnerRDPStore:
    def __init__(self) -> None:
        self._owners: dict[str, str] = {}

    def add(self, ref: str, *, owner: str) -> None:
        self._owners[ref] = owner

    def manifest(self, ref: str, *, owner_user_id: str):
        if self._owners.get(ref) != owner_user_id:
            raise KeyError(ref)
        return type("RDPManifest", (), {"owner_user_id": owner_user_id})()


class _ContentBoundResolver:
    """Strict test resolver: every accepted ref and linkage is pre-registered."""

    def __init__(self, owner: str) -> None:
        self._records: dict[str, GoalEntrypointCoverageRecord] = {}
        self._refs: set[str] = set()
        self._lifecycle = _OwnerLifecycleStore()
        self._rdps = _OwnerRDPStore()
        self._closure_resolver = build_real_ref_resolver(
            research_graph_store=None,
            lifecycle_registry=self._lifecycle,
            governance_registry=None,
            rag_index=None,
            spine_chain_registry=None,
            rdp_store=self._rdps,
            owner=owner,
        )

    def register(self, record: GoalEntrypointCoverageRecord) -> None:
        self._records[record.coverage_ref] = record
        self._refs.update(record.qro_refs)
        self._refs.update(record.research_graph_command_refs)
        self._refs.update(record.compiler_ir_refs)
        self._refs.update(record.compiler_pass_refs)
        self._refs.update(record.evidence_refs)
        for ref in record.lifecycle_refs:
            self._lifecycle.add(ref, owner=record.recorded_by)
        for ref in record.rdp_refs:
            self._rdps.add(ref, owner=record.recorded_by)

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
        return self._closure_resolver.has_lifecycle_record(ref)

    def has_rdp(self, ref: str) -> bool:
        return self._closure_resolver.has_rdp(ref)

    def entrypoint_linkage_violations(
        self,
        record: GoalEntrypointCoverageRecord,
    ) -> tuple[tuple[str, str, str], ...]:
        expected = self._records.get(record.coverage_ref)
        if expected is None:
            return (("coverage_ref", record.coverage_ref, "unregistered lineage"),)
        if expected != record:
            return (("coverage_ref", record.coverage_ref, "recombined lineage"),)
        return ()


def _coverage(
    owner: str,
    source: str,
    variant: str,
    *,
    goal_sections: tuple[str, ...] = CORE_GOAL_SECTIONS,
    full: bool = False,
) -> GoalEntrypointCoverageRecord:
    data = {
        "entry_source": source,
        "entrypoint_ref": f"route:{source}:{variant}",
        "goal_sections": goal_sections,
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
        "canonical_command_refs": (
            f"entrypoint:route:{source}:{variant}",
        ),
        "lifecycle_refs": (
            (f"lifecycle:{source}:{variant}",) if full else ()
        ),
        "rdp_refs": ((f"rdp:{source}:{variant}",) if full else ()),
        "recorded_by": owner,
        "claims_full_product_entrypoint": full,
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


def _registry(tmp_path, owner: str = "owner:alice"):
    resolver = _ContentBoundResolver(owner)
    entrypoints = PersistentGoalEntrypointCoverageRegistry(
        tmp_path / "entrypoints.jsonl",
        resolver=resolver,
    )
    bases = []
    for source in REQUIRED_ENTRY_SOURCES:
        record = _coverage(owner, source, "base")
        resolver.register(record)
        bases.append(entrypoints.record_coverage(record))
    aggregates = PersistentGoalEntrypointLineageAggregateRegistry(
        tmp_path / "lineage_aggregates.jsonl",
        entrypoints,
    )
    return resolver, entrypoints, aggregates, tuple(bases)


def test_latest_strict_non_full_core_heads_ignore_terminal_rows(tmp_path) -> None:
    owner = "owner:alice"
    resolver, entrypoints, aggregates, bases = _registry(tmp_path, owner)
    newer_api = _coverage(owner, "api", "newer-core")
    resolver.register(newer_api)
    entrypoints.record_coverage(newer_api)

    first = aggregates.record_current(owner_user_id=owner)
    assert first.coverage_refs[REQUIRED_ENTRY_SOURCES.index("api")] == (
        newer_api.coverage_ref
    )
    assert first.coverage_refs[0] == bases[0].coverage_ref

    expanded_non_terminal = _coverage(
        owner,
        "api",
        "expanded-non-terminal",
        goal_sections=REQUIRED_GOAL_SECTIONS,
    )
    resolver.register(expanded_non_terminal)
    entrypoints.record_coverage(expanded_non_terminal)
    assert aggregates.build_current(owner_user_id=owner) == first

    terminal = _coverage(
        owner,
        "api",
        "terminal",
        goal_sections=REQUIRED_GOAL_SECTIONS,
        full=True,
    )
    resolver.register(terminal)
    entrypoints.record_coverage(terminal)

    assert aggregates.build_current(owner_user_id=owner) == first
    assert aggregates.validate_current(first, owner_user_id=owner) == ()
    before = aggregates.path.read_bytes()
    assert aggregates.record_current(owner_user_id=owner) == first
    assert aggregates.path.read_bytes() == before


def test_expanded_real_chat_and_agent_shell_lineages_become_current_heads(
    tmp_path,
) -> None:
    owner = "owner:alice"
    resolver, entrypoints, aggregates, bases = _registry(tmp_path, owner)
    expanded: dict[str, GoalEntrypointCoverageRecord] = {}
    for source in ("chat", "agent_shell"):
        record = _coverage(
            owner,
            source,
            "expanded-real",
            goal_sections=("§0", "§1", "§5", "§7", "§8"),
        )
        resolver.register(record)
        expanded[source] = entrypoints.record_coverage(record)

    current = aggregates.build_current(owner_user_id=owner)

    for source, record in expanded.items():
        source_index = REQUIRED_ENTRY_SOURCES.index(source)
        assert current.coverage_refs[source_index] == record.coverage_ref
        assert current.coverage_refs[source_index] != bases[source_index].coverage_ref


def test_expanded_core_filter_rejects_missing_reordered_and_duplicate_core(
    tmp_path,
) -> None:
    owner = "owner:alice"
    resolver, entrypoints, aggregates, bases = _registry(tmp_path, owner)
    chat_index = REQUIRED_ENTRY_SOURCES.index("chat")
    rejected_sections = (
        ("§0", "§1", "§5", "§7"),
        ("§1", "§0", "§5", "§7", "§8"),
        ("§0", "§1", "§5", "§7", "§7", "§8"),
    )
    for index, goal_sections in enumerate(rejected_sections):
        rejected = _coverage(
            owner,
            "chat",
            f"rejected-{index}",
            goal_sections=goal_sections,
        )
        resolver.register(rejected)
        entrypoints.record_coverage(rejected)

    current = aggregates.build_current(owner_user_id=owner)

    assert current.coverage_refs[chat_index] == bases[chat_index].coverage_ref


def test_expanded_full_section_nonterminal_and_terminal_rows_remain_ignored(
    tmp_path,
) -> None:
    owner = "owner:alice"
    resolver, entrypoints, aggregates, bases = _registry(tmp_path, owner)
    chat_index = REQUIRED_ENTRY_SOURCES.index("chat")
    expanded_nonterminal = _coverage(
        owner,
        "chat",
        "expanded-full-nonterminal",
        goal_sections=REQUIRED_GOAL_SECTIONS,
    )
    terminal = _coverage(
        owner,
        "chat",
        "expanded-full-terminal",
        goal_sections=REQUIRED_GOAL_SECTIONS,
        full=True,
    )
    for record in (expanded_nonterminal, terminal):
        resolver.register(record)
        entrypoints.record_coverage(record)

    current = aggregates.build_current(owner_user_id=owner)

    assert current.coverage_refs[chat_index] == bases[chat_index].coverage_ref


def test_lineage_aggregate_rejects_stale_owner_and_recombined_heads(tmp_path) -> None:
    owner = "owner:alice"
    resolver, entrypoints, aggregates, _bases = _registry(tmp_path, owner)
    current = aggregates.record_current(owner_user_id=owner)

    changed = _coverage(owner, "chat", "changed-core")
    resolver.register(changed)
    entrypoints.record_coverage(changed)
    assert "goal_entrypoint_lineage_aggregate_not_current" in (
        aggregates.validate_current(current, owner_user_id=owner)
    )

    wrong_owner = replace(current, recorded_by="owner:bob")
    assert "goal_entrypoint_lineage_aggregate_owner_mismatch" in (
        aggregates.validate_current(wrong_owner, owner_user_id=owner)
    )

    recombined = replace(
        current,
        coverage_refs=(
            current.coverage_refs[1],
            current.coverage_refs[0],
            *current.coverage_refs[2:],
        ),
    )
    assert "goal_entrypoint_lineage_aggregate_identity_mismatch" in (
        aggregates.validate_current(recombined, owner_user_id=owner)
    )


def test_lineage_aggregate_replays_owner_scoped_idempotent_receipt(tmp_path) -> None:
    owner = "owner:alice"
    _resolver, entrypoints, aggregates, _bases = _registry(tmp_path, owner)
    recorded = aggregates.record_current(owner_user_id=owner)

    replayed = PersistentGoalEntrypointLineageAggregateRegistry(
        aggregates.path,
        entrypoints,
    )
    assert replayed.aggregate(
        recorded.aggregate_ref,
        owner_user_id=owner,
    ) == recorded
    before = replayed.path.read_bytes()
    assert replayed.record_current(owner_user_id=owner) == recorded
    assert replayed.path.read_bytes() == before


def test_lineage_aggregate_excludes_strict_schema2_rows_until_canonical(
    tmp_path,
    monkeypatch,
) -> None:
    owner = "owner:alice"
    resolver = _ContentBoundResolver(owner)
    records = tuple(
        _coverage(owner, source, "canonical-boundary")
        for source in REQUIRED_ENTRY_SOURCES
    )
    for record in records:
        resolver.register(record)
    entrypoint_path = tmp_path / "entrypoints.jsonl"
    entrypoint_path.write_text(
        "".join(
            json.dumps(
                {
                    "schema_version": 2,
                    "event_type": "goal_entrypoint_coverage_recorded",
                    "owner_user_id": owner,
                    "entrypoint_coverage": asdict(record),
                },
                sort_keys=True,
            )
            + "\n"
            for record in records
        ),
        encoding="utf-8",
    )
    ledger = GoalProofLedger(tmp_path / "proof_ledger")
    for record in records[:-1]:
        ledger.commit(
            ProofBundle(
                owner=owner,
                subject=f"lineage:{record.entry_source}",
                members=(
                    typed_proof_record_member(
                        record,
                        codec=GOAL_ENTRYPOINT_COVERAGE_PROOF_CODEC,
                    ),
                ),
            )
        )
    entrypoints = PersistentGoalEntrypointCoverageRegistry(
        entrypoint_path,
        resolver=resolver,
        proof_ledger=ledger,
    )
    aggregates = PersistentGoalEntrypointLineageAggregateRegistry(
        tmp_path / "lineage_aggregates.jsonl",
        entrypoints,
    )

    with pytest.raises(ValueError, match=REQUIRED_ENTRY_SOURCES[-1]):
        aggregates.current_coverages(owner_user_id=owner)

    missing = records[-1]
    ledger.commit(
        ProofBundle(
            owner=owner,
            subject=f"lineage:{missing.entry_source}",
            members=(
                typed_proof_record_member(
                    missing,
                    codec=GOAL_ENTRYPOINT_COVERAGE_PROOF_CODEC,
                ),
            ),
        )
    )
    original_current = ledger.current
    calls = 0

    def _one_snapshot(*args, **kwargs):
        nonlocal calls
        calls += 1
        return original_current(*args, **kwargs)

    monkeypatch.setattr(ledger, "current", _one_snapshot)
    assert aggregates.current_coverages(owner_user_id=owner) == records
    assert calls == 1
