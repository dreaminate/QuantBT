from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from types import SimpleNamespace

import pytest

from app.research_os.desk_projection import (
    DESK_EDITABLE_ASSETS,
    DeskName,
    DeskProjectionRecord,
)
from app.research_os.desk_topology import (
    CANONICAL_DESKS,
    DESK_TOPOLOGY_ENTRYPOINTS,
    DeskTopologySectionAdapter,
    PersistentDeskTopologyRegistry,
    ResolvedDeskReference,
    ResolvedHandoffCommand,
)
from app.research_os.goal_coverage import GoalCoverageDecision
from app.research_os.goal_semantics import (
    GoalSectionSemanticProofRecord,
    goal_section_semantic_proof_identity,
)


class ResolverFixture:
    def __init__(self) -> None:
        self.refs: dict[tuple[str, str, str], ResolvedDeskReference] = {}
        self.commands: dict[tuple[str, str], ResolvedHandoffCommand] = {}

    def add_ref(
        self,
        kind: str,
        ref: str,
        owner: str,
        *,
        desk: str = "",
        revision: str = "revision:v1",
        editable: tuple[str, ...] = (),
        commands: tuple[str, ...] = (),
    ) -> None:
        self.refs[(kind, owner, ref)] = ResolvedDeskReference(
            ref=ref,
            owner_user_id=owner,
            kind=kind,
            desk=desk,
            revision_hash=revision,
            editable_asset_types=editable,
            canonical_command_types=commands,
            current_ref=ref,
        )

    def resolver(self, kind: str):
        def resolve(ref: str, owner: str) -> ResolvedDeskReference:
            return self.refs[(kind, owner, ref)]

        return resolve

    def command_resolver(self, ref: str, owner: str) -> ResolvedHandoffCommand:
        return self.commands[(owner, ref)]

    def registry(self, path):
        kinds = {
            "typed_canvas",
            "agent_shell",
            "rag_projection",
            "math_projection",
            "asset_inspector",
            "tool_permission",
            "canonical_command_capability",
            "qro",
            "handoff_evidence",
        }
        return PersistentDeskTopologyRegistry(
            path,
            reference_resolvers={kind: self.resolver(kind) for kind in kinds},
            command_resolver=self.command_resolver,
        )


def _projections(
    resolvers: ResolverFixture,
    owner: str,
    *,
    suffix: str = "v1",
) -> tuple[tuple[DeskProjectionRecord, ...], dict[str, tuple[str, ...]]]:
    projections: list[DeskProjectionRecord] = []
    capabilities: dict[str, tuple[str, ...]] = {}
    for desk in CANONICAL_DESKS:
        refs = {
            "typed_canvas": f"typed_canvas:{desk}:{suffix}",
            "agent_shell": f"agent_shell:{desk}:{suffix}",
            "rag_projection": f"rag_projection:{desk}:{suffix}",
            "math_projection": f"math_projection:{desk}:{suffix}",
            "asset_inspector": f"asset_inspector:{desk}:{suffix}",
            "tool_permission": f"tool_permission:{desk}:{suffix}",
        }
        allowed = tuple(sorted(DESK_EDITABLE_ASSETS[desk]))
        for kind, ref in refs.items():
            resolvers.add_ref(
                kind,
                ref,
                owner,
                desk=desk,
                editable=allowed if kind == "tool_permission" else (),
            )
        capability_ref = f"command_capability:{desk}:{suffix}"
        resolvers.add_ref(
            "canonical_command_capability",
            capability_ref,
            owner,
            desk=desk,
            commands=("open_handoff", "resolve_handoff"),
        )
        capabilities[desk] = (capability_ref,)
        projections.append(
            DeskProjectionRecord(
                projection_ref=f"caller_projection:{desk}:{suffix}",
                desk=DeskName(desk),
                source_of_truth_refs=("research_graph",),
                typed_canvas_ref=refs["typed_canvas"],
                agent_shell_ref=refs["agent_shell"],
                rag_projection_ref=refs["rag_projection"],
                math_projection_ref=refs["math_projection"],
                asset_inspector_ref=refs["asset_inspector"],
                tool_permission_ref=refs["tool_permission"],
                editable_asset_types=allowed,
                canonical_command_types=("open_handoff", "resolve_handoff"),
            )
        )
    return tuple(projections), capabilities


def _add_completed_ring(
    registry: PersistentDeskTopologyRegistry,
    resolvers: ResolverFixture,
    owner: str,
    topology_ref: str,
    *,
    count: int = 9,
) -> None:
    for index, from_desk in enumerate(CANONICAL_DESKS[:count]):
        to_desk = CANONICAL_DESKS[(index + 1) % len(CANONICAL_DESKS)]
        handoff_id = f"handoff:{index}"
        open_ref = f"command:open:{index}"
        resolution_ref = f"command:resolve:{index}"
        qro_ref = f"qro:{to_desk}:{index}"
        evidence_ref = f"evidence:handoff:{index}"
        resolvers.add_ref("qro", qro_ref, owner, desk=to_desk)
        resolvers.add_ref("handoff_evidence", evidence_ref, owner)
        resolvers.commands[(owner, open_ref)] = ResolvedHandoffCommand(
            command_ref=open_ref,
            owner_user_id=owner,
            command_type="open_handoff",
            target_desk=from_desk,
            handoff_id=handoff_id,
            from_desk=from_desk,
            to_desk=to_desk,
            capability_ref=f"command_capability:{from_desk}:v1",
            revision_hash="open:v1",
        )
        resolvers.commands[(owner, resolution_ref)] = ResolvedHandoffCommand(
            command_ref=resolution_ref,
            owner_user_id=owner,
            command_type="resolve_handoff",
            target_desk=to_desk,
            handoff_id=handoff_id,
            from_desk=from_desk,
            to_desk=to_desk,
            capability_ref=f"command_capability:{to_desk}:v1",
            revision_hash="resolve:v1",
            produced_qro_ref=qro_ref,
            evidence_refs=(evidence_ref,),
        )
        registry.record_completed_handoff(
            owner_user_id=owner,
            topology_ref=topology_ref,
            open_command_ref=open_ref,
            resolution_command_ref=resolution_ref,
        )


def _complete_store(tmp_path, owner: str = "owner-a"):
    resolvers = ResolverFixture()
    registry = resolvers.registry(tmp_path / "desk_topology.jsonl")
    projections, capabilities = _projections(resolvers, owner)
    topology = registry.record_topology(
        owner_user_id=owner,
        projections=projections,
        capability_refs_by_desk=capabilities,
    )
    _add_completed_ring(registry, resolvers, owner, topology.topology_ref)
    receipt = registry.record_current_receipt(owner_user_id=owner)
    return resolvers, registry, topology, receipt, projections, capabilities


class _SemanticEntrypoints:
    def __init__(self, coverage, owner: str = "owner-a") -> None:
        self.coverage_record = coverage
        self.owner = owner
        self.current = True

    def coverage(self, coverage_ref: str, *, owner: str):
        if owner != self.owner or coverage_ref != self.coverage_record.coverage_ref:
            raise KeyError(coverage_ref)
        return self.coverage_record

    def validate_real_backing(self, record):
        return GoalCoverageDecision(
            self.current and record is self.coverage_record,
            (),
        )


def _semantic_material(
    registry: PersistentDeskTopologyRegistry,
    topology,
    receipt,
    *,
    source: str = "api",
    owner: str = "owner-a",
):
    coverage = SimpleNamespace(
        coverage_ref=f"goal_entrypoint_coverage:desk-topology:{source}",
        entry_source=source,
        entrypoint_ref=DESK_TOPOLOGY_ENTRYPOINTS[source],
        goal_sections=("§2",),
        validation_refs=(receipt.receipt_ref, "goal_validation_receipt:entry"),
    )
    handoffs_by_ref = {
        item.handoff_ref: item
        for item in registry.handoffs(owner_user_id=owner)
    }
    handoffs = tuple(handoffs_by_ref[ref] for ref in receipt.handoff_refs)
    data = {
        "section": "§2",
        "subject_ref": (
            f"goal_section:§2:desk_topology_receipt:{receipt.receipt_ref}"
        ),
        "producer_refs": tuple(
            sorted(
                {
                    *(
                        ref
                        for projection in topology.projections
                        for ref in projection.canonical_command_capability_refs
                    ),
                    *(item.open_command_ref for item in handoffs),
                    *(item.resolution_command_ref for item in handoffs),
                    *(item.produced_qro_ref for item in handoffs),
                    *(ref for item in handoffs for ref in item.evidence_refs),
                }
            )
        ),
        "store_refs": tuple(
            sorted(
                {
                    receipt.receipt_ref,
                    topology.topology_ref,
                    *(item.projection_ref for item in topology.projections),
                    *(item.handoff_ref for item in handoffs),
                }
            )
        ),
        "consumer_refs": tuple(
            sorted(
                {
                    coverage.entrypoint_ref,
                    *(item.typed_canvas_ref for item in topology.projections),
                    *(item.agent_shell_ref for item in topology.projections),
                    *(item.rag_projection_ref for item in topology.projections),
                    *(item.math_projection_ref for item in topology.projections),
                    *(item.asset_inspector_ref for item in topology.projections),
                }
            )
        ),
        "gate_verdict_refs": (receipt.receipt_ref,),
        "test_refs": tuple(
            sorted(
                {
                    receipt.receipt_ref,
                    "desk_topology_current_check:"
                    f"{receipt.receipt_ref}:{topology.topology_ref}",
                    *(
                        f"desk_projection_current_check:{receipt.receipt_ref}:"
                        f"{item.projection_ref}"
                        for item in topology.projections
                    ),
                    *(
                        f"desk_handoff_current_check:{receipt.receipt_ref}:"
                        f"{item.handoff_ref}"
                        for item in handoffs
                    ),
                }
            )
        ),
        "entrypoint_coverage_refs": (coverage.coverage_ref,),
        "recorded_by": owner,
        "claims_section_complete": True,
        "unverified_residuals": (),
    }
    data["proof_ref"] = goal_section_semantic_proof_identity(**data)
    return (
        _SemanticEntrypoints(coverage, owner),
        GoalSectionSemanticProofRecord(**data),
    )


def test_exact_nine_desk_topology_and_derived_receipt_survive_reload(tmp_path):
    resolvers, registry, topology, receipt, _projections_v1, _capabilities = (
        _complete_store(tmp_path)
    )

    assert topology.revision == 1
    assert tuple(item.desk for item in topology.projections) == tuple(
        sorted(CANONICAL_DESKS)
    )
    assert len(receipt.handoff_refs) == 9
    assert registry.validate_current_receipt(
        receipt, owner_user_id="owner-a"
    ).accepted

    reloaded = resolvers.registry(tmp_path / "desk_topology.jsonl")
    persisted = reloaded.receipt(receipt.receipt_ref, owner_user_id="owner-a")
    assert persisted == receipt
    assert reloaded.validate_current_receipt(
        persisted, owner_user_id="owner-a"
    ).accepted


def test_owner_scope_rejects_cross_owner_receipt_lookup_and_validation(tmp_path):
    _resolvers, registry, _topology, receipt, _projections_v1, _capabilities = (
        _complete_store(tmp_path)
    )

    with pytest.raises(KeyError):
        registry.receipt(receipt.receipt_ref, owner_user_id="owner-b")
    decision = registry.validate_current_receipt(receipt, owner_user_id="owner-b")
    assert not decision.accepted
    assert {item.code for item in decision.violations} >= {
        "desk_topology_receipt_owner_mismatch",
        "desk_topology_current_proof_unavailable",
    }


def test_missing_extra_and_relabeled_desks_are_refused(tmp_path):
    resolvers = ResolverFixture()
    registry = resolvers.registry(tmp_path / "desk_topology.jsonl")
    projections, capabilities = _projections(resolvers, "owner-a")

    with pytest.raises(ValueError, match="exactly nine"):
        registry.record_topology(
            owner_user_id="owner-a",
            projections=projections[:-1],
            capability_refs_by_desk=capabilities,
        )
    with pytest.raises(ValueError, match="exactly nine"):
        registry.record_topology(
            owner_user_id="owner-a",
            projections=projections + (projections[0],),
            capability_refs_by_desk=capabilities,
        )
    relabeled = (replace(projections[0], desk=DeskName.FACTOR),) + projections[1:]
    with pytest.raises(ValueError, match="nine canonical desks"):
        registry.record_topology(
            owner_user_id="owner-a",
            projections=relabeled,
            capability_refs_by_desk=capabilities,
        )


def test_incomplete_and_mixed_handoff_commands_are_refused(tmp_path):
    resolvers = ResolverFixture()
    registry = resolvers.registry(tmp_path / "desk_topology.jsonl")
    projections, capabilities = _projections(resolvers, "owner-a")
    topology = registry.record_topology(
        owner_user_id="owner-a",
        projections=projections,
        capability_refs_by_desk=capabilities,
    )
    resolvers.commands[("owner-a", "open")] = ResolvedHandoffCommand(
        command_ref="open",
        owner_user_id="owner-a",
        command_type="open_handoff",
        target_desk="data",
        handoff_id="handoff:one",
        from_desk="data",
        to_desk="factor",
        capability_ref="command_capability:data:v1",
        revision_hash="open:v1",
    )
    resolvers.commands[("owner-a", "resolve")] = ResolvedHandoffCommand(
        command_ref="resolve",
        owner_user_id="owner-a",
        command_type="resolve_handoff",
        target_desk="factor",
        handoff_id="handoff:other",
        from_desk="data",
        to_desk="factor",
        capability_ref="command_capability:factor:v1",
        revision_hash="resolve:v1",
    )

    with pytest.raises(ValueError, match="incomplete, mixed"):
        registry.record_completed_handoff(
            owner_user_id="owner-a",
            topology_ref=topology.topology_ref,
            open_command_ref="open",
            resolution_command_ref="resolve",
        )
    resolvers.commands[("owner-a", "resolve")] = replace(
        resolvers.commands[("owner-a", "resolve")],
        handoff_id="handoff:one",
    )
    with pytest.raises(ValueError, match="incomplete, mixed"):
        registry.record_completed_handoff(
            owner_user_id="owner-a",
            topology_ref=topology.topology_ref,
            open_command_ref="open",
            resolution_command_ref="resolve",
        )


def test_receipt_refuses_topology_when_a_desk_has_no_completed_handoff(tmp_path):
    resolvers = ResolverFixture()
    registry = resolvers.registry(tmp_path / "desk_topology.jsonl")
    projections, capabilities = _projections(resolvers, "owner-a")
    topology = registry.record_topology(
        owner_user_id="owner-a",
        projections=projections,
        capability_refs_by_desk=capabilities,
    )
    _add_completed_ring(
        registry,
        resolvers,
        "owner-a",
        topology.topology_ref,
        count=7,
    )

    with pytest.raises(ValueError, match="every canonical desk"):
        registry.build_current_receipt(owner_user_id="owner-a")


def test_generic_resolver_cannot_substitute_for_typed_resolvers(tmp_path):
    with pytest.raises(ValueError, match="requires typed resolvers"):
        PersistentDeskTopologyRegistry(
            tmp_path / "desk_topology.jsonl",
            reference_resolvers={"generic": lambda ref, owner: True},
            command_resolver=lambda ref, owner: True,
        )


def test_stale_topology_revision_invalidates_old_receipt(tmp_path):
    resolvers, registry, topology_v1, receipt, _projections_v1, _capabilities_v1 = (
        _complete_store(tmp_path)
    )
    projections_v2, capabilities_v2 = _projections(
        resolvers, "owner-a", suffix="v2"
    )
    topology_v2 = registry.record_topology(
        owner_user_id="owner-a",
        projections=projections_v2,
        capability_refs_by_desk=capabilities_v2,
    )

    assert topology_v2.revision == topology_v1.revision + 1
    assert topology_v2.previous_topology_ref == topology_v1.topology_ref
    decision = registry.validate_current_receipt(receipt, owner_user_id="owner-a")
    assert not decision.accepted
    assert "desk_topology_current_proof_unavailable" in {
        item.code for item in decision.violations
    }


@pytest.mark.parametrize(
    "drift_kind", ["qro", "tool_permission", "command", "handoff_evidence"]
)
def test_current_backing_drift_invalidates_receipt(tmp_path, drift_kind):
    resolvers, registry, topology, receipt, _projections_v1, _capabilities = (
        _complete_store(tmp_path)
    )
    if drift_kind == "qro":
        key = ("qro", "owner-a", "qro:factor:0")
        resolvers.refs[key] = replace(
            resolvers.refs[key], revision_hash="revision:v2"
        )
    elif drift_kind == "tool_permission":
        projection = next(item for item in topology.projections if item.desk == "data")
        key = ("tool_permission", "owner-a", projection.tool_permission_ref)
        resolvers.refs[key] = replace(
            resolvers.refs[key], editable_asset_types=("Dataset",)
        )
    elif drift_kind == "command":
        key = ("owner-a", "command:resolve:0")
        resolvers.commands[key] = replace(
            resolvers.commands[key], revision_hash="resolve:v2"
        )
    else:
        key = ("handoff_evidence", "owner-a", "evidence:handoff:0")
        resolvers.refs[key] = replace(
            resolvers.refs[key], revision_hash="revision:v2"
        )

    decision = registry.validate_current_receipt(receipt, owner_user_id="owner-a")
    assert not decision.accepted
    assert "desk_topology_current_proof_unavailable" in {
        item.code for item in decision.violations
    }


def test_replay_is_idempotent_and_threads_share_one_topology_event(tmp_path):
    resolvers = ResolverFixture()
    registry = resolvers.registry(tmp_path / "desk_topology.jsonl")
    projections, capabilities = _projections(resolvers, "owner-a")

    def record():
        return registry.record_topology(
            owner_user_id="owner-a",
            projections=projections,
            capability_refs_by_desk=capabilities,
        )

    with ThreadPoolExecutor(max_workers=6) as executor:
        records = list(executor.map(lambda _: record(), range(12)))

    assert len({item.topology_ref for item in records}) == 1
    rows = [
        json.loads(line)
        for line in registry.path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert [row["event_type"] for row in rows] == ["desk_topology_recorded"]


def test_schema_v1_rows_are_quarantined_without_becoming_proof(tmp_path):
    path = tmp_path / "desk_topology.jsonl"
    path.write_text('{"schema_version":1,"topology_ref":"legacy"}\n', encoding="utf-8")
    resolvers = ResolverFixture()
    registry = resolvers.registry(path)

    assert registry.legacy_quarantined_count == 1
    with pytest.raises(KeyError):
        registry.current_topology(owner_user_id="owner-a")


@pytest.mark.parametrize("source", ("api", "agent_shell"))
def test_section_adapter_accepts_exact_current_api_or_agent_lineage(
    tmp_path,
    source,
):
    _resolvers, registry, topology, receipt, _projections_v1, _capabilities = (
        _complete_store(tmp_path)
    )
    entrypoints, proof = _semantic_material(
        registry,
        topology,
        receipt,
        source=source,
    )
    adapter = DeskTopologySectionAdapter(entrypoints, registry)

    decision = adapter.validate(proof, owner="owner-a")

    assert decision.accepted, decision.violations


def test_section_adapter_requires_exactly_one_canonical_entrypoint_lineage(tmp_path):
    _resolvers, registry, topology, receipt, _projections_v1, _capabilities = (
        _complete_store(tmp_path)
    )
    entrypoints, proof = _semantic_material(registry, topology, receipt)
    adapter = DeskTopologySectionAdapter(entrypoints, registry)

    multiple = adapter.validate(
        replace(
            proof,
            entrypoint_coverage_refs=(
                *proof.entrypoint_coverage_refs,
                "goal_entrypoint_coverage:unrelated",
            ),
        ),
        owner="owner-a",
    )
    entrypoints.coverage_record.entrypoint_ref = "api:goal.desk_topology.unrelated"
    relabeled = adapter.validate(proof, owner="owner-a")

    assert not multiple.accepted
    assert any(item.field == "entrypoint_coverage_refs" for item in multiple.violations)
    assert not relabeled.accepted
    assert any("canonical current-topology" in item.message for item in relabeled.violations)


@pytest.mark.parametrize(
    "field_name",
    (
        "producer_refs",
        "store_refs",
        "consumer_refs",
        "gate_verdict_refs",
        "test_refs",
    ),
)
def test_section_adapter_rejects_semantic_field_recombination(
    tmp_path,
    field_name,
):
    _resolvers, registry, topology, receipt, _projections_v1, _capabilities = (
        _complete_store(tmp_path)
    )
    entrypoints, proof = _semantic_material(registry, topology, receipt)
    adapter = DeskTopologySectionAdapter(entrypoints, registry)
    recombined = replace(
        proof,
        **{field_name: (*getattr(proof, field_name), f"unrelated:{field_name}")},
    )

    decision = adapter.validate(recombined, owner="owner-a")

    assert not decision.accepted
    assert any(item.field == field_name for item in decision.violations)


def test_section_adapter_rejects_receipt_drift_after_qro_changes(tmp_path):
    resolvers, registry, topology, receipt, _projections_v1, _capabilities = (
        _complete_store(tmp_path)
    )
    entrypoints, proof = _semantic_material(registry, topology, receipt)
    adapter = DeskTopologySectionAdapter(entrypoints, registry)
    qro_key = ("qro", "owner-a", "qro:factor:0")
    resolvers.refs[qro_key] = replace(
        resolvers.refs[qro_key],
        revision_hash="revision:v2",
    )

    decision = adapter.validate(proof, owner="owner-a")

    assert not decision.accepted
    assert any("no longer current" in item.message for item in decision.violations)


def test_section_adapter_rejects_cross_owner_receipt_reuse(tmp_path):
    _resolvers, registry, topology, receipt, _projections_v1, _capabilities = (
        _complete_store(tmp_path)
    )
    entrypoints, proof = _semantic_material(registry, topology, receipt)
    adapter = DeskTopologySectionAdapter(entrypoints, registry)

    decision = adapter.validate(proof, owner="owner-b")

    assert not decision.accepted
    assert any("not persisted for owner" in item.message for item in decision.violations)


def test_section_adapter_rejects_duplicate_current_material(tmp_path):
    _resolvers, registry, topology, receipt, _projections_v1, _capabilities = (
        _complete_store(tmp_path)
    )
    entrypoints, proof = _semantic_material(registry, topology, receipt)
    adapter = DeskTopologySectionAdapter(entrypoints, registry)
    duplicated = replace(
        proof,
        producer_refs=(*proof.producer_refs, proof.producer_refs[0]),
    )

    decision = adapter.validate(duplicated, owner="owner-a")

    assert not decision.accepted
    assert any(item.field == "producer_refs" for item in decision.violations)
