from __future__ import annotations

from types import SimpleNamespace

from fastapi.testclient import TestClient

from app.research_os.asset_rag import PersistentResearchAssetRAGIndex
from app.research_os.compiler import PersistentCompilerIRStore
from app.research_os.desk_topology import PersistentDeskTopologyRegistry
from app.research_os.goal_coverage import (
    PersistentGoalEntrypointCoverageRegistry,
    RiskConsentEntrypointCoverageRegistry,
)
from app.research_os.goal_proof_ledger import GoalProofLedger
from app.research_os.goal_validation_receipts import (
    PersistentGoalValidationReceiptRegistry,
)
from app.research_os.platform_row_sources import PersistentPlatformRowSourceRegistry
from app.research_os.platform_source_adapters_m9_m15 import (
    PlatformSourceAdaptersM9M15Context,
    build_platform_source_adapters_m9_m15,
)
from app.research_os.platform_source_lineage_core import PlatformSourceLineageFinalizer
from app.research_os.platform_source_lineage_policies_m9_m15 import (
    PlatformSourceLineagePoliciesM9M15Context,
    build_platform_source_lineage_policies_m9_m15,
)
from app.research_os.platform_typed_sources import RealPlatformTypedSourceResolver
from app.research_os.ref_resolution import build_real_ref_resolver
from app.research_os.spine import PersistentResearchGraphStore, ResearchGraphStore


M15_MATH_REF = "math_spine_chain:m15_topology_main"


class _MathRegistry:
    def __init__(self, owner: str) -> None:
        self.owner = owner
        self._chains: list[SimpleNamespace] = []

    def add_chain(
        self,
        *,
        chain_ref: str,
        owner: str,
        evidence_refs: tuple[str, ...],
    ) -> SimpleNamespace:
        chain = SimpleNamespace(
            chain_ref=chain_ref,
            recorded_by=owner,
            evidence_refs=evidence_refs,
            revision="v1",
        )
        self._chains.append(chain)
        return chain

    def chains(self, *, owner: str | None = None):
        if owner is None:
            return list(self._chains)
        return [chain for chain in self._chains if chain.recorded_by == owner]

    def verified_chain(self, ref: str, *, owner: str):
        matches = [
            chain
            for chain in self._chains
            if chain.chain_ref == ref and chain.recorded_by == owner
        ]
        if len(matches) != 1:
            raise KeyError(ref)
        return matches[0]

    def verified_chain_record_refs(self, ref: str, *, owner: str):
        self.verified_chain(ref, owner=owner)
        return SimpleNamespace(
            theory_binding_refs=(),
            consistency_check_refs=(),
        )


class _EmptyConsentCoverageStore:
    @staticmethod
    def source_coverage(_coverage_ref: str):
        raise KeyError(_coverage_ref)

    @staticmethod
    def source_coverage_for_owner(_coverage_ref: str, _owner: str):
        raise KeyError(_coverage_ref)

    @staticmethod
    def source_coverages(*, owner=None):
        del owner
        return []


def _registry(main, tmp_path):
    return PersistentDeskTopologyRegistry(
        tmp_path / "desk_topology.jsonl",
        reference_resolvers={
            kind: (
                lambda ref, owner, _kind=kind: main._resolve_desk_static_reference(
                    _kind,
                    ref,
                    owner,
                )
            )
            for kind in (
                "typed_canvas",
                "agent_shell",
                "rag_projection",
                "math_projection",
                "asset_inspector",
                "tool_permission",
                "canonical_command_capability",
            )
        }
        | {
            "qro": main._resolve_desk_qro,
            "handoff_evidence": main._resolve_desk_handoff_evidence,
        },
        command_resolver=main._resolve_desk_handoff_command,
    )


def test_server_derived_topology_and_handoff_open_are_owner_scoped(
    tmp_path,
    monkeypatch,
) -> None:
    import app.main as main

    monkeypatch.setattr(main, "RESEARCH_GRAPH_STORE", ResearchGraphStore())
    monkeypatch.setattr(
        main,
        "GOAL_VALIDATION_RECEIPT_REGISTRY",
        PersistentGoalValidationReceiptRegistry(tmp_path / "goal_validation.jsonl"),
    )
    monkeypatch.setattr(main, "DESK_TOPOLOGY_REGISTRY", _registry(main, tmp_path))
    main.app.dependency_overrides[main.require_user_dependency] = lambda: SimpleNamespace(
        username="u1",
        user_id="u1",
    )
    client = TestClient(main.app)
    try:
        topology = client.post("/api/research-os/desks/topology/current")
        assert topology.status_code == 200, topology.text
        assert len(topology.json()["desks"]) == 9
        assert set(topology.json()["desks"]) == set(main.CANONICAL_DESKS)

        opened = client.post(
            "/api/research-os/desks/handoffs/open",
            json={
                "handoff_id": "handoff:data-factor:1",
                "from_desk": "data",
                "to_desk": "factor",
                "requested_asset": "Factor",
                "reason": "dataset is ready for factor research",
                "blocking_dependency": "dataset:bars:v1",
            },
        )
        assert opened.status_code == 200, opened.text
        command = main._resolve_desk_handoff_command(
            opened.json()["open_command_ref"],
            "u1",
        )
        assert command.command_type == "open_handoff"
        assert command.current
        assert command.from_desk == "data"
        assert command.to_desk == "factor"

        forged = client.post(
            "/api/research-os/desks/handoffs/resolve",
            json={
                "open_command_ref": opened.json()["open_command_ref"],
                "produced_qro_ref": opened.json()["qro_id"],
                "evidence_refs": ["goal_validation_receipt:not-recorded"],
            },
        )
        assert forged.status_code == 422
        assert main.DESK_TOPOLOGY_REGISTRY.handoffs(owner_user_id="u1") == []

        main.app.dependency_overrides[main.require_user_dependency] = lambda: SimpleNamespace(
            username="u2",
            user_id="u2",
        )
        foreign = client.get("/api/research-os/desks/topology/summary")
        assert foreign.status_code == 200
        assert foreign.json()["topology"] is None
        assert foreign.json()["handoffs"] == []
    finally:
        main.app.dependency_overrides.pop(main.require_user_dependency, None)


def test_real_m15_route_uses_current_head_bound_math_and_reserved_lineage(
    tmp_path,
    monkeypatch,
) -> None:
    import app.main as main

    owner = "u1"
    graph = PersistentResearchGraphStore(tmp_path / "research_graph.jsonl")
    proof_ledger = GoalProofLedger(tmp_path / "goal_proof_ledger")
    compiler = PersistentCompilerIRStore(
        tmp_path / "compiler.jsonl",
        proof_ledger=proof_ledger,
        legacy_read_only=True,
    )
    validations = PersistentGoalValidationReceiptRegistry(
        tmp_path / "goal_validation.jsonl",
        proof_ledger=proof_ledger,
        legacy_read_only=True,
    )
    rag = PersistentResearchAssetRAGIndex(tmp_path / "research_asset_rag.jsonl")
    math = _MathRegistry(owner)
    monkeypatch.setattr(main, "RESEARCH_GRAPH_STORE", graph)
    monkeypatch.setattr(main, "COMPILER_IR_STORE", compiler)
    monkeypatch.setattr(main, "GOAL_VALIDATION_RECEIPT_REGISTRY", validations)
    monkeypatch.setattr(main, "RESEARCH_ASSET_RAG_INDEX", rag)
    monkeypatch.setattr(main, "MATHEMATICAL_SPINE_CHAIN_REGISTRY", math)

    topology = _registry(main, tmp_path)
    monkeypatch.setattr(main, "DESK_TOPOLOGY_REGISTRY", topology)
    strict_refs = build_real_ref_resolver(
        research_graph_store=graph,
        lifecycle_registry=None,
        governance_registry=None,
        rag_index=rag,
        spine_chain_registry=math,
        compiler_store=compiler,
        goal_validation_receipt_registry=validations,
        lifecycle_loaders=(
            lambda ref, selected_owner: topology.receipt(
                ref,
                owner_user_id=selected_owner,
            ),
        ),
    )
    delegate = PersistentGoalEntrypointCoverageRegistry(
        tmp_path / "goal_entrypoint_coverage.jsonl",
        resolver=strict_refs,
        proof_ledger=proof_ledger,
        legacy_read_only=True,
    )
    entrypoints = RiskConsentEntrypointCoverageRegistry(
        delegate,
        _EmptyConsentCoverageStore(),
        entrypoint_ref=main.RISK_CONSENT_ENTRYPOINT_REF,
    )
    monkeypatch.setattr(main, "GOAL_ENTRYPOINT_COVERAGE_REGISTRY", entrypoints)

    adapters, validators_by_row = build_platform_source_adapters_m9_m15(
        PlatformSourceAdaptersM9M15Context(
            research_graph_store=graph,
            desk_topology_registry=topology,
        )
    )
    source_resolver = RealPlatformTypedSourceResolver(
        research_graph_store=graph,
        lifecycle_loaders=(
            lambda ref, selected_owner, _record: topology.receipt(
                ref,
                owner_user_id=selected_owner,
            ),
        ),
        goal_validation_receipt_registry=validations,
        rag_index=rag,
        spine_chain_registry=math,
        compiler_store=compiler,
        specific_adapters=adapters,
        row_validators=validators_by_row,
    )
    row_sources = PersistentPlatformRowSourceRegistry(
        tmp_path / "platform_row_sources.jsonl",
        entrypoint_registry=entrypoints,
        rag_index=rag,
        source_resolver=source_resolver,
    )
    policy = build_platform_source_lineage_policies_m9_m15(
        PlatformSourceLineagePoliciesM9M15Context(
            research_graph_store=graph,
            compiler_store=compiler,
            spine_chain_registry=math,
            desk_topology_registry=topology,
        )
    )
    lineage = PlatformSourceLineageFinalizer(
        policy_resolver=policy,
        entrypoint_registry=delegate,
        rag_index=rag,
        row_source_registry=row_sources,
        source_resolver=source_resolver,
        record_coverage=lambda record: main._record_canonical_goal_entrypoint_coverage(
            record,
            registry=entrypoints,
        ),
        record_rag_document=rag.add_for_owner,
        record_certification=row_sources.record_current,
    )
    monkeypatch.setattr(main, "PLATFORM_SOURCE_LINEAGE_FINALIZER", lineage)
    monkeypatch.setattr(main, "PLATFORM_ROW_SOURCE_REGISTRY", row_sources)
    main.app.dependency_overrides[main.require_user_dependency] = lambda: SimpleNamespace(
        username=owner,
        user_id=owner,
    )
    client = TestClient(main.app)
    try:
        topology_response = client.post("/api/research-os/desks/topology/current")
        assert topology_response.status_code == 200, topology_response.text

        desks = sorted(main.CANONICAL_DESKS)
        for index, from_desk in enumerate(desks):
            to_desk = desks[(index + 1) % len(desks)]
            handoff_id = f"handoff:m15:{index}"
            opened = client.post(
                "/api/research-os/desks/handoffs/open",
                json={
                    "handoff_id": handoff_id,
                    "from_desk": from_desk,
                    "to_desk": to_desk,
                    "requested_asset": "ValidationDossier",
                    "reason": "prove every desk participates in the current topology",
                    "blocking_dependency": "",
                },
            )
            assert opened.status_code == 200, opened.text
            open_refs = opened.json()
            produced_qro = main.QRORecord(
                qro_type=main.QROType.VALIDATION_DOSSIER,
                owner=owner,
                actor=main.ActorSource.USER_MANUAL,
                input_contract={"entry_source": "api", "desk": to_desk},
                output_contract={"status": "produced", "desk": to_desk},
                market="cross_market",
                universe="multi_desk_research_os",
                horizon="event",
                frequency="event_driven",
                lineage=(handoff_id, f"desk:{to_desk}"),
                implementation_hash=f"desk_handoff_product:{handoff_id}",
                assumptions=("The target desk produced this bounded handoff asset.",),
                known_limits=("This proves routing, not research correctness.",),
                failure_modes=("A stale QRO or receipt invalidates the handoff.",),
                validation_plan=("Resolve the current QRO and validation receipt.",),
                definition_status=main.DefinitionStatus.IMPLEMENTED,
                evidence_status=main.EvidenceStatus.SUFFICIENT,
                runtime_status=main.RuntimeStatus.OFFLINE,
                evidence_refs=(f"evidence:{handoff_id}:produced",),
                permission=f"research_os.desk:{to_desk}:produce",
                allowed_environment=main.RuntimeStatus.OFFLINE,
            )
            produced_command = main.ResearchGraphCommand(
                source=main.EntrySource.API,
                command_type="upsert_qro",
                actor_source=main.ActorSource.USER_MANUAL,
                actor=owner,
                payload={"qro": produced_qro},
                evidence_refs=produced_qro.evidence_refs,
                tool_record_refs=("test:desk_handoff_product",),
            )
            produced_command_ref = graph.apply(produced_command)
            main._compile_entrypoint_qro(
                qro_id=produced_qro.qro_id,
                graph_command_id=produced_command_ref,
                actor=owner,
                actor_source="user_manual",
                entry_source="api",
                entrypoint_ref="api:goal.desk_handoff.current",
                pass_name="api_desk_handoff_to_validation_ir",
                validation_refs=("runtime_validator:desk_handoff_current_v1",),
                evidence_refs=(f"evidence:{handoff_id}",),
                environment_lock_ref="env:desk_handoff:v1",
                permission_ref=f"research_os.desk_handoff:{from_desk}:{to_desk}",
                deterministic_run_plan_ref=f"runplan:{handoff_id}",
                rollback_ref=f"rollback:{handoff_id}:append_new_head",
                tool_record_refs=("api:research-os.desks.handoffs",),
                goal_sections=("§2",),
            )
            matching_receipts = [
                item
                for item in validations.receipts(owner_user_id=owner)
                if item.subject_qro_refs == (produced_qro.qro_id,)
                and item.graph_command_refs == (produced_command_ref,)
            ]
            assert len(matching_receipts) == 1
            resolved = client.post(
                "/api/research-os/desks/handoffs/resolve",
                json={
                    "open_command_ref": open_refs["open_command_ref"],
                    "produced_qro_ref": produced_qro.qro_id,
                    "evidence_refs": [matching_receipts[0].validation_ref],
                },
            )
            assert resolved.status_code == 200, resolved.text

        bound_qro_refs = tuple(
            sorted(
                handoff.produced_qro_ref
                for handoff in topology.handoffs(owner_user_id=owner)
            )
        )
        math.add_chain(
            chain_ref="math_spine_chain:unbound-latest-owner-chain",
            owner=owner,
            evidence_refs=("qro:not-current-topology",),
        )
        caller_selected = client.post(
            "/api/research-os/desks/topology/receipts/current",
            json={"math_spine_ref": M15_MATH_REF},
        )
        assert caller_selected.status_code == 422, caller_selected.text
        assert caller_selected.json()["detail"] == (
            "desk topology receipt payload must be empty"
        )

        no_bound_chain = client.post(
            "/api/research-os/desks/topology/receipts/current"
        )
        assert no_bound_chain.status_code == 422, no_bound_chain.text
        assert "requires exactly one" in no_bound_chain.json()["detail"]

        math.add_chain(
            chain_ref="math_spine_chain:foreign-topology-binding",
            owner="u2",
            evidence_refs=bound_qro_refs,
        )
        math.add_chain(
            chain_ref=M15_MATH_REF,
            owner=owner,
            evidence_refs=bound_qro_refs,
        )
        first_receipt = client.post(
            "/api/research-os/desks/topology/receipts/current",
        )
        assert first_receipt.status_code == 200, first_receipt.text
        first_refs = first_receipt.json()
        first_qro = graph.qro(first_refs["qro_id"])
        assert first_qro.mathematical_refs == (M15_MATH_REF,)
        assert compiler.ir(
            first_refs["compiler_ir_ref"],
            owner=owner,
        ).mathematical_spine_chain_refs == (M15_MATH_REF,)

        first_lineage = client.post(
            "/api/research-os/platform/source_lineage/M15/current",
            json={"anchor_ref": first_refs["receipt_ref"]},
        )
        assert first_lineage.status_code == 200, first_lineage.text
        assert first_lineage.json()["row_source_certified"] is True
        assert first_lineage.json()["current"] is True
        assert first_lineage.json()["row_revision"] == 1

        second_receipt = client.post(
            "/api/research-os/desks/topology/receipts/current",
            json={},
        )
        assert second_receipt.status_code == 200, second_receipt.text
        second_refs = second_receipt.json()
        assert second_refs["qro_id"] == first_refs["qro_id"]
        assert (
            second_refs["research_graph_command_id"]
            != first_refs["research_graph_command_id"]
        )

        second_lineage = client.post(
            "/api/research-os/platform/source_lineage/M15/current",
            json={"anchor_ref": second_refs["receipt_ref"]},
        )
        assert second_lineage.status_code == 200, second_lineage.text
        assert (
            second_lineage.json()["record"]["research_graph_ref"]
            == second_refs["research_graph_command_id"]
        )
        assert second_lineage.json()["row_revision"] == 2

        commands_before_ambiguity = len(graph.commands())
        math.add_chain(
            chain_ref="math_spine_chain:m15_topology_main_duplicate",
            owner=owner,
            evidence_refs=bound_qro_refs,
        )
        ambiguous = client.post(
            "/api/research-os/desks/topology/receipts/current"
        )
        assert ambiguous.status_code == 422, ambiguous.text
        assert "requires exactly one" in ambiguous.json()["detail"]
        assert len(graph.commands()) == commands_before_ambiguity

        forged = client.post(
            "/api/research-os/platform/source_lineage/M15/current",
            json={
                "anchor_ref": second_refs["receipt_ref"],
                "math_spine_ref": "math_spine_chain:caller-forged",
            },
        )
        assert forged.status_code == 422, forged.text
    finally:
        main.app.dependency_overrides.pop(main.require_user_dependency, None)
