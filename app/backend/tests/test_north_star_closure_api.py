from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from types import SimpleNamespace

from fastapi.testclient import TestClient

from app import main
from app.auth import require_user_dependency
from app.research_os.goal_coverage import (
    GoalCoverageDecision,
    GoalCoverageViolation,
    GoalEntrypointCoverageRecord,
    PersistentGoalEntrypointCoverageRegistry,
    REQUIRED_ENTRY_SOURCES,
    REQUIRED_GOAL_SECTIONS,
    goal_entrypoint_coverage_identity,
)
from app.research_os.goal_entrypoint_lineage_aggregate import (
    CORE_GOAL_SECTIONS,
    PersistentGoalEntrypointLineageAggregateRegistry,
)
from app.research_os.goal_semantics import (
    GoalSectionSemanticProofRecord,
    GoalSemanticCommitUncertain,
    GoalSemanticDecision,
    PersistentGoalSectionSemanticProofRegistry,
    goal_section_semantic_proof_identity,
)
from app.research_os.north_star_closure import (
    NORTH_STAR_CLOSURE_ENTRYPOINT_REF,
    NORTH_STAR_SOURCE_SECTIONS,
    NorthStarClosureSectionAdapter,
    build_current_north_star_proof,
)


OWNER = "owner:north-star-api"


class _EntryResolver:
    def __init__(self, refs: set[str]) -> None:
        self.refs = refs

    def has_qro(self, ref: str) -> bool:
        return ref in self.refs

    def has_research_graph_command(self, ref: str) -> bool:
        return ref in self.refs

    def has_compiler_ir(self, ref: str) -> bool:
        return ref in self.refs

    def has_compiler_pass(self, ref: str) -> bool:
        return ref in self.refs

    def has_evidence(self, ref: str) -> bool:
        return ref in self.refs

    def has_lifecycle_record(self, ref: str) -> bool:
        return ref in self.refs

    def has_rdp(self, ref: str) -> bool:
        return ref in self.refs

    def entrypoint_linkage_violations(self, _record) -> tuple:
        return ()


class _AcceptCurrentSection:
    def validate(self, _record, *, owner: str) -> GoalSemanticDecision:
        assert owner == OWNER
        return GoalSemanticDecision(True, ())


def _coverage(
    source: str,
    *,
    token: str = "core",
    goal_sections: tuple[str, ...] = CORE_GOAL_SECTIONS,
) -> GoalEntrypointCoverageRecord:
    entrypoint_ref = f"route:{source}:north-star-api:{token}"
    qro_refs = (f"qro:{source}:north-star-api:{token}",)
    graph_refs = (f"rgcmd:{source}:north-star-api:{token}",)
    ir_refs = (f"compiler_ir:{source}:north-star-api:{token}",)
    pass_refs = (f"compiler_pass:{source}:north-star-api:{token}",)
    return GoalEntrypointCoverageRecord(
        coverage_ref=goal_entrypoint_coverage_identity(
            entry_source=source,
            entrypoint_ref=entrypoint_ref,
            goal_sections=goal_sections,
            qro_refs=qro_refs,
            research_graph_command_refs=graph_refs,
            compiler_ir_refs=ir_refs,
            compiler_pass_refs=pass_refs,
        ),
        entry_source=source,
        entrypoint_ref=entrypoint_ref,
        goal_sections=goal_sections,
        qro_refs=qro_refs,
        research_graph_command_refs=graph_refs,
        compiler_ir_refs=ir_refs,
        compiler_pass_refs=pass_refs,
        evidence_refs=(f"evidence:{source}:north-star-api",),
        validation_refs=(f"validation:{source}:north-star-api",),
        permission_refs=(f"permission:{source}:north-star-api",),
        replay_refs=(
            f"replay:research_graph:{graph_refs[0]}",
            f"replay:compiler_ir:{ir_refs[0]}",
            f"replay:compiler_pass:{pass_refs[0]}",
        ),
        canonical_command_refs=(f"command:{source}:north-star-api",),
        recorded_by=OWNER,
        claims_full_product_entrypoint=False,
    )


def _source_proof(
    section: str,
    coverage_ref: str,
) -> GoalSectionSemanticProofRecord:
    token = section.removeprefix("§")
    values = {
        "section": section,
        "subject_ref": f"section_subject:{token}:north-star-api",
        "producer_refs": (f"section_producer:{token}:north-star-api",),
        "store_refs": (f"section_store:{token}:north-star-api",),
        "consumer_refs": (f"section_consumer:{token}:north-star-api",),
        "gate_verdict_refs": (f"section_gate:{token}:north-star-api",),
        "test_refs": (f"pytest:section-{token}:north-star-api",),
        "entrypoint_coverage_refs": (coverage_ref,),
        "recorded_by": OWNER,
        "claims_section_complete": True,
        "unverified_residuals": (),
    }
    return GoalSectionSemanticProofRecord(
        proof_ref=goal_section_semantic_proof_identity(**values),
        **values,
    )


def _resolver_refs(
    coverages: tuple[GoalEntrypointCoverageRecord, ...],
) -> set[str]:
    return {
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


@dataclass
class _Stores:
    entrypoints: PersistentGoalEntrypointCoverageRegistry
    aggregates: PersistentGoalEntrypointLineageAggregateRegistry
    semantic: PersistentGoalSectionSemanticProofRegistry
    coverages: tuple[GoalEntrypointCoverageRecord, ...]


def _stores(tmp_path, *, section_count: int = 17) -> _Stores:
    base_coverages = tuple(_coverage(source) for source in REQUIRED_ENTRY_SOURCES)
    support = {
        section: (
            base_coverages[0]
            if section in CORE_GOAL_SECTIONS
            else _coverage(
                "api",
                token=f"section-{section.removeprefix('§')}",
                goal_sections=(section,),
            )
        )
        for section in NORTH_STAR_SOURCE_SECTIONS
    }
    coverages = tuple(
        dict.fromkeys((*base_coverages, *support.values()))
    )
    entrypoints = PersistentGoalEntrypointCoverageRegistry(
        tmp_path / "entrypoints.jsonl",
        resolver=_EntryResolver(_resolver_refs(coverages)),
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
    return _Stores(entrypoints, aggregates, semantic, coverages)


def _install(monkeypatch, stores: _Stores, *, user_id: str = OWNER) -> TestClient:
    monkeypatch.setattr(
        main,
        "GOAL_ENTRYPOINT_COVERAGE_REGISTRY",
        stores.entrypoints,
    )
    monkeypatch.setattr(
        main,
        "GOAL_ENTRYPOINT_LINEAGE_AGGREGATE_REGISTRY",
        stores.aggregates,
    )
    monkeypatch.setattr(
        main,
        "GOAL_SECTION_SEMANTIC_PROOF_REGISTRY",
        stores.semantic,
    )
    main.app.dependency_overrides[require_user_dependency] = lambda: SimpleNamespace(
        username="north-star-display",
        user_id=user_id,
    )
    return TestClient(main.app)


def _restart(stores: _Stores) -> _Stores:
    entrypoints = PersistentGoalEntrypointCoverageRegistry(
        stores.entrypoints.path,
        resolver=_EntryResolver(_resolver_refs(stores.coverages)),
    )
    aggregates = PersistentGoalEntrypointLineageAggregateRegistry(
        stores.aggregates.path,
        entrypoints,
    )
    semantic = PersistentGoalSectionSemanticProofRegistry(
        stores.semantic.path,
        entrypoints,
        adapters={
            section: _AcceptCurrentSection()
            for section in NORTH_STAR_SOURCE_SECTIONS
        },
    )
    semantic.register_adapter(
        "§0",
        NorthStarClosureSectionAdapter(semantic, aggregates),
    )
    return _Stores(entrypoints, aggregates, semantic, stores.coverages)


def _clear_dependency_override() -> None:
    main.app.dependency_overrides.pop(require_user_dependency, None)


def test_production_registers_zero_after_all_source_adapters_and_routes() -> None:
    assert (
        main.GOAL_SECTION_SEMANTIC_PROOF_REGISTRY.registered_sections
        == REQUIRED_GOAL_SECTIONS
    )
    route_methods = {
        (route.path, method)
        for route in main.app.routes
        for method in getattr(route, "methods", ())
    }
    assert (
        "/api/research-os/goal/north_star_closure/current",
        "POST",
    ) in route_methods
    assert (
        "/api/research-os/goal/north_star_closure",
        "GET",
    ) in route_methods
    assert (
        "/api/research-os/goal/entrypoint_lineage_aggregates/current",
        "POST",
    ) in route_methods


def test_current_api_is_server_derived_idempotent_read_only_and_restart_safe(
    tmp_path,
    monkeypatch,
) -> None:
    stores = _stores(tmp_path)
    client = _install(monkeypatch, stores)
    entrypoint_before = stores.entrypoints.path.read_bytes()
    aggregate_before = stores.aggregates.path.read_bytes()
    semantic_before = stores.semantic.path.read_bytes()
    try:
        lineage = client.post(
            "/api/research-os/goal/entrypoint_lineage_aggregates/current",
            json={"coverage_refs": ["caller:forged"]},
        )
        assert lineage.status_code == 200, lineage.text
        assert lineage.json()["aggregate_ref"] == stores.aggregates.build_current(
            owner_user_id=OWNER
        ).aggregate_ref
        assert stores.aggregates.path.read_bytes() == aggregate_before

        recorded = client.post(
            "/api/research-os/goal/north_star_closure/current",
            json={
                "proof_ref": "client:forged",
                "claims_section_complete": False,
            },
        )
        assert recorded.status_code == 200, recorded.text
        body = recorded.json()
        assert body["entrypoint_ref"] == NORTH_STAR_CLOSURE_ENTRYPOINT_REF
        assert body["recorded_by"] == OWNER
        assert body["section"] == "§0"
        assert body["claims_section_complete"] is True
        assert len(body["section_proof_refs"]) == 17
        assert body["proof_ref"] != "client:forged"
        assert stores.entrypoints.path.read_bytes() == entrypoint_before
        assert stores.aggregates.path.read_bytes() == aggregate_before
        assert stores.semantic.path.read_bytes() != semantic_before

        semantic_after = stores.semantic.path.read_bytes()
        replay = client.post(
            "/api/research-os/goal/north_star_closure/current"
        )
        assert replay.status_code == 200, replay.text
        assert replay.json()["proof_ref"] == body["proof_ref"]
        assert stores.semantic.path.read_bytes() == semantic_after

        summary = client.get("/api/research-os/goal/north_star_closure")
        assert summary.status_code == 200, summary.text
        assert summary.json()["current_available"] is True
        assert summary.json()["current_persisted"] is True
        assert summary.json()["current_proof_ref"] == body["proof_ref"]
        assert summary.json()["proof_total"] == 1
        assert stores.semantic.path.read_bytes() == semantic_after

        restarted = _restart(stores)
        client = _install(monkeypatch, restarted)
        restarted_summary = client.get(
            "/api/research-os/goal/north_star_closure"
        )
        assert restarted_summary.status_code == 200, restarted_summary.text
        assert restarted_summary.json()["current_persisted"] is True
        assert restarted_summary.json()["current_proof_ref"] == body["proof_ref"]
    finally:
        _clear_dependency_override()


def test_current_api_reports_committed_semantic_append_as_409(
    tmp_path,
    monkeypatch,
) -> None:
    stores = _stores(tmp_path)
    client = _install(monkeypatch, stores)
    record_proof = stores.semantic.record_proof

    def append_then_lose_ack(record):
        persisted = record_proof(record)
        raise GoalSemanticCommitUncertain(
            f"injected post-append acknowledgement loss:{persisted.proof_ref}"
        )

    monkeypatch.setattr(stores.semantic, "record_proof", append_then_lose_ack)
    before = stores.semantic.path.read_bytes()
    try:
        response = client.post(
            "/api/research-os/goal/north_star_closure/current"
        )
        assert response.status_code == 409, response.text
        assert response.json()["detail"]["write_committed"] is True
        assert response.json()["detail"]["retry_required"] is True
        assert stores.semantic.path.read_bytes() != before
        [persisted] = stores.semantic.records(owner=OWNER, section="§0")

        monkeypatch.setattr(stores.semantic, "record_proof", record_proof)
        retry = client.post(
            "/api/research-os/goal/north_star_closure/current"
        )
        assert retry.status_code == 200, retry.text
        assert retry.json()["proof_ref"] == persisted.proof_ref
        assert len(stores.semantic.records(owner=OWNER, section="§0")) == 1
    finally:
        _clear_dependency_override()


def test_generic_semantic_api_rejects_even_exact_zero_proof_without_write(
    tmp_path,
    monkeypatch,
) -> None:
    stores = _stores(tmp_path)
    client = _install(monkeypatch, stores)
    exact = build_current_north_star_proof(
        stores.semantic,
        stores.aggregates,
        owner=OWNER,
    )
    payload = asdict(exact)
    payload["recorded_by"] = "client:spoofed"
    before = stores.semantic.path.read_bytes()
    try:
        response = client.post(
            "/api/research-os/goal/section_semantic_proofs",
            json=payload,
        )
        assert response.status_code == 422, response.text
        assert "goal_semantic_north_star_server_derived_required" in response.text
        assert stores.semantic.path.read_bytes() == before
        assert stores.semantic.records(owner=OWNER, section="§0") == []
    finally:
        _clear_dependency_override()


def test_current_api_detects_source_change_before_append(
    tmp_path,
    monkeypatch,
) -> None:
    stores = _stores(tmp_path)
    client = _install(monkeypatch, stores)
    expected = build_current_north_star_proof(
        stores.semantic,
        stores.aggregates,
        owner=OWNER,
    )
    monkeypatch.setattr(
        main,
        "build_current_north_star_proof",
        lambda *_args, **_kwargs: replace(
            expected,
            subject_ref="north_star_snapshot:changed-during-build",
        ),
    )
    before = stores.semantic.path.read_bytes()
    try:
        response = client.post(
            "/api/research-os/goal/north_star_closure/current"
        )
        assert response.status_code == 422, response.text
        assert "north_star_source_heads_changed_during_build" in response.text
        assert stores.semantic.path.read_bytes() == before
        assert stores.semantic.records(owner=OWNER, section="§0") == []
    finally:
        _clear_dependency_override()


def test_current_api_missing_source_and_wrong_owner_fail_without_write(
    tmp_path,
    monkeypatch,
) -> None:
    stores = _stores(tmp_path, section_count=16)
    client = _install(monkeypatch, stores)
    before = stores.semantic.path.read_bytes()
    try:
        missing = client.post(
            "/api/research-os/goal/north_star_closure/current"
        )
        assert missing.status_code == 422, missing.text
        assert "north_star_section_proof_missing:§17" in missing.text
        assert stores.semantic.path.read_bytes() == before

        unavailable = client.get("/api/research-os/goal/north_star_closure")
        assert unavailable.status_code == 200, unavailable.text
        assert unavailable.json()["current_available"] is False
        assert "north_star_section_proof_missing:§17" in unavailable.json()[
            "current_error"
        ]
        assert stores.semantic.path.read_bytes() == before

        client = _install(monkeypatch, stores, user_id="owner:other")
        wrong_owner = client.post(
            "/api/research-os/goal/north_star_closure/current"
        )
        assert wrong_owner.status_code == 422, wrong_owner.text
        assert stores.semantic.path.read_bytes() == before
        isolated = client.get("/api/research-os/goal/north_star_closure")
        assert isolated.status_code == 200, isolated.text
        assert isolated.json()["proof_total"] == 0
        assert isolated.json()["current_available"] is False
    finally:
        _clear_dependency_override()


class _SemanticFailureSectionSummary:
    legacy_quarantined_count = 0

    def records(self, *, owner: str) -> list:
        assert owner == OWNER
        return []

    def validate_real_manifest(
        self,
        *,
        claims_full_product_implementation: bool,
        owner: str,
    ) -> GoalCoverageDecision:
        assert claims_full_product_implementation is True
        assert owner == OWNER
        return GoalCoverageDecision(
            False,
            (
                GoalCoverageViolation(
                    "goal_section_semantic_proof_not_real_backed",
                    "stale north-star proof",
                    field="semantic_proof_refs",
                    ref="§0",
                ),
            ),
        )


def test_section_summary_surfaces_stale_zero_semantic_proof(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        main,
        "GOAL_SECTION_COVERAGE_REGISTRY",
        _SemanticFailureSectionSummary(),
    )
    main.app.dependency_overrides[require_user_dependency] = lambda: SimpleNamespace(
        username="north-star-display",
        user_id=OWNER,
    )
    try:
        response = TestClient(main.app).get(
            "/api/research-os/goal/section_coverage/summary"
        )
        assert response.status_code == 200, response.text
        assert response.json()["not_full_entrypoint_wired_sections"] == ["§0"]
        assert response.json()["full_product_implementation"] is False
    finally:
        _clear_dependency_override()
