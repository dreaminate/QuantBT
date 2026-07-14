from __future__ import annotations

import json
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app import main
from app.auth import require_user_dependency
from app.research_os.goal_coverage import (
    GOAL_ENTRYPOINT_COVERAGE_PROOF_CODEC,
    REQUIRED_ENTRY_SOURCES,
    REQUIRED_GOAL_SECTIONS,
    GoalEntrypointCoverageRecord,
    GoalSectionCoverageRecord,
    PersistentGoalEntrypointCoverageRegistry,
    PersistentGoalSectionCoverageRegistry,
    RiskConsentEntrypointCoverageRegistry,
    goal_entrypoint_coverage_identity,
    strict_current_entrypoint_coverage,
    strict_current_entrypoint_lookup,
    strict_current_entrypoint_records,
    validate_goal_entrypoint_coverage,
    validate_goal_entrypoint_coverage_manifest,
    validate_goal_entrypoint_real_backing,
    validate_goal_entrypoint_real_manifest,
    validate_goal_coverage_manifest,
    validate_goal_coverage_real_manifest,
    validate_goal_section_real_backing,
    validate_goal_section_coverage,
)
from app.research_os.ref_resolution import build_real_ref_resolver
from app.research_os.goal_proof_ledger import GoalProofLedger, ProofBundle
from app.research_os.goal_proof_records import typed_proof_record_member


def _codes(decision) -> set[str]:
    return {violation.code for violation in decision.violations}


def _record(section: str, **overrides) -> GoalSectionCoverageRecord:
    data = {
        "section": section,
        "contract_refs": (f"contract:{section}",),
        "test_refs": (f"test:{section}",),
        "task_refs": (f"task:{section}",),
        "evidence_refs": (f"evidence:{section}",),
        "recorded_by": "u1",
    }
    data.update(overrides)
    return GoalSectionCoverageRecord(**data)


def _contract_manifest() -> tuple[GoalSectionCoverageRecord, ...]:
    return tuple(_record(section) for section in REQUIRED_GOAL_SECTIONS)


def _entrypoint_record(source: str = "api", **overrides) -> GoalEntrypointCoverageRecord:
    data = {
        "entry_source": source,
        "entrypoint_ref": f"route:{source}:strategy_goal.create",
        "goal_sections": ("§0", "§1", "§8"),
        "qro_refs": (f"qro:{source}:quant_intent",),
        "research_graph_command_refs": (f"rgcmd:{source}:upsert_qro",),
        "compiler_ir_refs": (f"compiler_ir:{source}:quant_intent",),
        "compiler_pass_refs": (f"compiler_pass:{source}:compile_qro",),
        "evidence_refs": (f"evidence:{source}:unit",),
        "validation_refs": (f"pytest:test_goal_coverage:{source}",),
        "permission_refs": (f"permission:{source}:write_qro",),
        "replay_refs": (f"replay:{source}:jsonl",),
        "canonical_command_refs": (f"command:{source}:upsert_qro",),
        "recorded_by": "u1",
    }
    data.update(overrides)
    if data.get("claims_full_product_entrypoint"):
        data.setdefault("lifecycle_refs", (f"lifecycle:{source}:current",))
        data.setdefault("rdp_refs", (f"rdp:{source}:current",))
    if "coverage_ref" not in overrides:
        data["coverage_ref"] = goal_entrypoint_coverage_identity(
            entry_source=data["entry_source"],
            entrypoint_ref=data["entrypoint_ref"],
            goal_sections=tuple(data["goal_sections"]),
            qro_refs=tuple(data["qro_refs"]),
            research_graph_command_refs=tuple(data["research_graph_command_refs"]),
            compiler_ir_refs=tuple(data["compiler_ir_refs"]),
            compiler_pass_refs=tuple(data["compiler_pass_refs"]),
        )
    return GoalEntrypointCoverageRecord(**data)


def _payload(record) -> dict:
    return record.__dict__.copy()


def _client_with_goal_coverage_store(tmp_path, monkeypatch):
    entrypoint_store = PersistentGoalEntrypointCoverageRegistry(tmp_path / "goal_entrypoint_coverage.jsonl")
    section_store = PersistentGoalSectionCoverageRegistry(
        tmp_path / "goal_section_coverage.jsonl",
        entrypoint_store,
    )
    monkeypatch.setattr(main, "GOAL_ENTRYPOINT_COVERAGE_REGISTRY", entrypoint_store)
    monkeypatch.setattr(main, "GOAL_SECTION_COVERAGE_REGISTRY", section_store)
    main.app.dependency_overrides[require_user_dependency] = lambda: SimpleNamespace(
        username="u1",
        user_id="u1",
    )
    return TestClient(main.app), entrypoint_store, section_store


class _OwnerLifecycleStore:
    def __init__(self, owners: dict[str, str]) -> None:
        self._owners = dict(owners)

    def governed_asset(self, ref: str, *, owner_user_id: str):
        if self._owners.get(ref) != owner_user_id:
            raise KeyError(ref)
        return SimpleNamespace(asset_ref=ref, owner_user_id=owner_user_id)


class _OwnerRDPStore:
    def __init__(self, owners: dict[str, str]) -> None:
        self._owners = dict(owners)

    def manifest(self, ref: str, *, owner_user_id: str):
        if self._owners.get(ref) != owner_user_id:
            raise KeyError(ref)
        return SimpleNamespace(package_id=ref, owner_user_id=owner_user_id)


class _GoalResolver:
    def __init__(
        self,
        *,
        backed: set[tuple[str, str]],
        lifecycle_owners: dict[str, str] | None = None,
        rdp_owners: dict[str, str] | None = None,
    ) -> None:
        self._backed = backed
        self._closure_resolvers = {
            owner: build_real_ref_resolver(
                research_graph_store=None,
                lifecycle_registry=_OwnerLifecycleStore(lifecycle_owners or {}),
                governance_registry=None,
                rag_index=None,
                spine_chain_registry=None,
                rdp_store=_OwnerRDPStore(rdp_owners or {}),
                owner=owner,
            )
            for owner in set((lifecycle_owners or {}).values())
            | set((rdp_owners or {}).values())
        }
        self._active_owner: str | None = None

    def for_owner(self, owner: str):
        clone = _GoalResolver(backed=self._backed)
        clone._closure_resolvers = self._closure_resolvers
        clone._active_owner = owner
        return clone

    def _has(self, kind: str, ref: str) -> bool:
        return (kind, ref) in self._backed

    def has_qro(self, ref: str) -> bool:
        return self._has("qro", ref)

    def has_research_graph_command(self, ref: str) -> bool:
        return self._has("research_graph", ref)

    def has_lifecycle_record(self, ref: str) -> bool:
        resolver = self._closure_resolvers.get(str(self._active_owner or ""))
        return resolver is not None and resolver.has_lifecycle_record(ref)

    def has_governance_record(self, ref: str) -> bool:
        return self._has("governance", ref)

    def has_rag_asset(self, ref: str) -> bool:
        return self._has("rag", ref)

    def has_math_spine_chain(self, ref: str) -> bool:
        return self._has("math_spine", ref)

    def has_compiler_ir(self, ref: str) -> bool:
        return self._has("compiler_ir", ref)

    def has_compiler_pass(self, ref: str) -> bool:
        return self._has("compiler_pass", ref)

    def has_evidence(self, ref: str) -> bool:
        return self._has("evidence", ref)

    def has_rdp(self, ref: str) -> bool:
        resolver = self._closure_resolvers.get(str(self._active_owner or ""))
        return resolver is not None and resolver.has_rdp(ref)

    def entrypoint_linkage_violations(self, record) -> tuple:
        return ()


def _resolver_for(record: GoalEntrypointCoverageRecord) -> _GoalResolver:
    backed: set[tuple[str, str]] = set()
    for kind, refs in (
        ("qro", record.qro_refs),
        ("research_graph", record.research_graph_command_refs),
        ("compiler_ir", record.compiler_ir_refs),
        ("compiler_pass", record.compiler_pass_refs),
        ("evidence", record.evidence_refs),
        ("lifecycle", record.lifecycle_refs),
        ("rdp", record.rdp_refs),
    ):
        for ref in refs:
            backed.add((kind, ref))
    return _GoalResolver(
        backed=backed,
        lifecycle_owners={ref: record.recorded_by for ref in record.lifecycle_refs},
        rdp_owners={ref: record.recorded_by for ref in record.rdp_refs},
    )


def _resolver_for_records(records: tuple[GoalEntrypointCoverageRecord, ...]) -> _GoalResolver:
    backed: set[tuple[str, str]] = set()
    lifecycle_owners: dict[str, str] = {}
    rdp_owners: dict[str, str] = {}
    for record in records:
        backed.update(_resolver_for(record)._backed)
        lifecycle_owners.update(
            {ref: record.recorded_by for ref in record.lifecycle_refs}
        )
        rdp_owners.update({ref: record.recorded_by for ref in record.rdp_refs})
    return _GoalResolver(
        backed=backed,
        lifecycle_owners=lifecycle_owners,
        rdp_owners=rdp_owners,
    )


def test_goal_section_coverage_requires_contract_test_task_and_evidence_refs():
    decision = validate_goal_section_coverage(
        _record("§6", contract_refs=(), test_refs=(), task_refs=(), evidence_refs=())
    )
    assert not decision.accepted
    assert "goal_section_missing_contract_evidence" in _codes(decision)


def test_goal_coverage_manifest_requires_sections_zero_through_seventeen():
    manifest = tuple(record for record in _contract_manifest() if record.section != "§13")
    decision = validate_goal_coverage_manifest(manifest)
    assert not decision.accepted
    assert "goal_section_missing" in _codes(decision)


def test_contract_coverage_cannot_be_reported_as_full_product_implementation():
    decision = validate_goal_coverage_manifest(
        _contract_manifest(),
        claims_full_product_implementation=True,
    )
    assert not decision.accepted
    assert "goal_section_not_full_entrypoint_wired" in _codes(decision)


def test_full_product_claim_requires_entrypoint_wiring_refs_for_every_section():
    manifest = tuple(
        _record(
            section,
            full_entrypoint_wired=True,
            entrypoint_wiring_refs=(f"entrypoint:{section}",),
        )
        for section in REQUIRED_GOAL_SECTIONS
    )
    decision = validate_goal_coverage_manifest(
        manifest,
        claims_full_product_implementation=True,
    )
    assert decision.accepted
    assert decision.violations == ()


def test_goal_section_real_backing_rejects_goal_closure_self_cert_refs():
    decision = validate_goal_section_real_backing(
        _record(
            "§6",
            evidence_refs=("evidence:goal_closure:section6",),
            task_refs=("task:goal-closure:section6",),
        )
    )
    assert not decision.accepted
    assert "goal_section_ref_not_backed" in _codes(decision)


def test_goal_real_manifest_does_not_count_goal_closure_refs_as_full_product():
    manifest = tuple(
        _record(
            section,
            full_entrypoint_wired=True,
            entrypoint_wiring_refs=(f"entrypoint:{section}",),
            evidence_refs=(f"evidence:goal_closure:{section}",),
        )
        for section in REQUIRED_GOAL_SECTIONS
    )
    decision = validate_goal_coverage_real_manifest(
        manifest,
        claims_full_product_implementation=True,
    )
    assert not decision.accepted
    assert "goal_section_ref_not_backed" in _codes(decision)


def test_contract_coverage_manifest_accepts_all_sections_without_overclaiming_full_wiring():
    decision = validate_goal_coverage_manifest(_contract_manifest())
    assert decision.accepted
    assert decision.violations == ()


def test_entrypoint_coverage_requires_qro_graph_compiler_evidence_permission_and_replay_refs():
    decision = validate_goal_entrypoint_coverage(
        _entrypoint_record(
            qro_refs=(),
            research_graph_command_refs=(),
            compiler_ir_refs=(),
            compiler_pass_refs=(),
            evidence_refs=(),
            validation_refs=(),
            permission_refs=(),
            replay_refs=(),
        )
    )
    assert not decision.accepted
    assert "goal_entrypoint_required_ref_missing" in _codes(decision)
    assert {violation.field for violation in decision.violations} >= {
        "qro_refs",
        "research_graph_command_refs",
        "compiler_ir_refs",
        "compiler_pass_refs",
        "evidence_refs",
        "validation_refs",
        "permission_refs",
        "replay_refs",
    }


def test_entrypoint_coverage_rejects_unknown_source_raw_payload_and_silent_mock():
    decision = validate_goal_entrypoint_coverage(
        _entrypoint_record(
            source="unknown",
            entry_source="unknown",
            goal_sections=("§99",),
            silent_mock_fallback_used=True,
            raw_payload_persisted=True,
        )
    )
    assert not decision.accepted
    assert _codes(decision) >= {
        "goal_entrypoint_unknown_source",
        "goal_entrypoint_unknown_section",
        "goal_entrypoint_silent_mock_fallback",
        "goal_entrypoint_raw_payload_persisted",
    }


def test_full_product_entrypoint_claim_requires_every_goal_section():
    decision = validate_goal_entrypoint_coverage(
        _entrypoint_record(claims_full_product_entrypoint=True)
    )
    assert not decision.accepted
    assert "goal_entrypoint_full_product_claim_missing_sections" in _codes(decision)


def test_entrypoint_real_backing_rejects_unresolved_qro_graph_compiler_and_evidence_refs():
    record = _entrypoint_record("api")
    resolver = _GoalResolver(backed=set())
    decision = validate_goal_entrypoint_real_backing(record, resolver=resolver)
    assert not decision.accepted
    assert "goal_entrypoint_ref_not_backed" in _codes(decision)
    assert {
        violation.field
        for violation in decision.violations
        if violation.code == "goal_entrypoint_ref_not_backed"
    } >= {"qro_refs", "research_graph_command_refs", "compiler_ir_refs", "compiler_pass_refs", "evidence_refs"}


def test_entrypoint_registry_with_resolver_accepts_only_real_backed_refs(tmp_path):
    record = _entrypoint_record("api")
    store = PersistentGoalEntrypointCoverageRegistry(
        tmp_path / "goal_entrypoint_coverage.jsonl",
        resolver=_resolver_for(record),
    )
    assert store.record_coverage(record).coverage_ref == record.coverage_ref

    before = store.path.read_text(encoding="utf-8")
    missing = _entrypoint_record("chat")
    with pytest.raises(ValueError, match="goal_entrypoint_ref_not_backed"):
        store.record_coverage(missing)
    assert store.path.read_text(encoding="utf-8") == before


def test_all_entrypoint_claim_requires_each_required_entry_source():
    decision = validate_goal_entrypoint_coverage_manifest(
        (_entrypoint_record("api"),),
        claims_all_entrypoints_wired=True,
    )
    assert not decision.accepted
    assert "goal_entrypoint_source_missing" in _codes(decision)


def test_all_entrypoint_manifest_accepts_chat_canvas_api_ide_scheduler_agent_shell():
    decision = validate_goal_entrypoint_coverage_manifest(
        tuple(_entrypoint_record(source) for source in REQUIRED_ENTRY_SOURCES),
        claims_all_entrypoints_wired=True,
    )
    assert decision.accepted
    assert decision.violations == ()


def test_real_entrypoint_manifest_does_not_count_resolved_partial_rows_as_fully_wired():
    records = tuple(_entrypoint_record(source) for source in REQUIRED_ENTRY_SOURCES)
    resolver = _resolver_for_records(records)

    decision = validate_goal_entrypoint_real_manifest(
        records,
        resolver=resolver,
        claims_all_entrypoints_wired=True,
    )

    assert not decision.accepted
    assert "goal_entrypoint_source_only_partial" in _codes(decision)
    missing_sources = {
        violation.ref
        for violation in decision.violations
        if violation.code == "goal_entrypoint_source_missing"
    }
    assert missing_sources == set(REQUIRED_ENTRY_SOURCES)


def test_real_entrypoint_manifest_accepts_all_sources_only_when_every_row_resolves():
    records = tuple(
        _entrypoint_record(
            source,
            goal_sections=tuple(REQUIRED_GOAL_SECTIONS),
            claims_full_product_entrypoint=True,
        )
        for source in REQUIRED_ENTRY_SOURCES
    )
    decision = validate_goal_entrypoint_real_manifest(
        records,
        resolver=_resolver_for_records(records),
        claims_all_entrypoints_wired=True,
    )

    assert decision.accepted
    assert decision.violations == ()


def test_entrypoint_coverage_registry_replays_and_invalid_does_not_write(tmp_path):
    path = tmp_path / "goal_entrypoint_coverage.jsonl"
    store = PersistentGoalEntrypointCoverageRegistry(path)
    record = store.record_coverage(_entrypoint_record("api"))
    assert store.coverage(record.coverage_ref).coverage_ref == record.coverage_ref
    assert PersistentGoalEntrypointCoverageRegistry(path).coverage(record.coverage_ref).entry_source == "api"
    before = path.read_text(encoding="utf-8")

    with pytest.raises(ValueError):
        store.record_coverage(_entrypoint_record("chat", qro_refs=()))

    assert path.read_text(encoding="utf-8") == before
    assert [item.coverage_ref for item in store.records()] == [record.coverage_ref]


def test_entrypoint_coverage_registry_isolates_same_ref_by_owner(tmp_path):
    path = tmp_path / "goal_entrypoint_coverage.jsonl"
    store = PersistentGoalEntrypointCoverageRegistry(path)
    alice = _entrypoint_record("api", recorded_by="alice")
    bob = _entrypoint_record("api", recorded_by="bob")

    store.record_coverage(alice)
    store.record_coverage(bob)
    store.record_coverage(alice)

    assert store.coverage(alice.coverage_ref, owner="alice").recorded_by == "alice"
    assert store.coverage(bob.coverage_ref, owner="bob").recorded_by == "bob"
    with pytest.raises(ValueError, match="owner-ambiguous"):
        store.coverage(alice.coverage_ref)
    assert len(path.read_text(encoding="utf-8").splitlines()) == 2
    reloaded = PersistentGoalEntrypointCoverageRegistry(path)
    assert len(reloaded.records(owner="alice")) == 1
    assert len(reloaded.records(owner="bob")) == 1


def test_canonical_coverage_view_excludes_strict_backed_schema2_history(
    tmp_path,
    monkeypatch,
):
    path = tmp_path / "goal_entrypoint_coverage.jsonl"
    legacy = _entrypoint_record("api")
    canonical = _entrypoint_record("chat")
    path.write_text(
        json.dumps(
            {
                "schema_version": 2,
                "event_type": "goal_entrypoint_coverage_recorded",
                "owner_user_id": legacy.recorded_by,
                "entrypoint_coverage": _payload(legacy),
            },
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    ledger = GoalProofLedger(tmp_path / "goal_proof_ledger")
    ledger.commit(
        ProofBundle(
            owner=canonical.recorded_by,
            subject="goal_coverage:canonical-view",
            members=(
                typed_proof_record_member(
                    canonical,
                    codec=GOAL_ENTRYPOINT_COVERAGE_PROOF_CODEC,
                ),
            ),
        )
    )
    store = PersistentGoalEntrypointCoverageRegistry(
        path,
        resolver=_resolver_for_records((legacy, canonical)),
        proof_ledger=ledger,
    )

    assert set(store.records(owner="u1")) == {legacy, canonical}
    original_current = ledger.current
    calls = 0

    def _one_snapshot(*args, **kwargs):
        nonlocal calls
        calls += 1
        return original_current(*args, **kwargs)

    monkeypatch.setattr(ledger, "current", _one_snapshot)
    assert store.canonical_records(owner="u1") == (canonical,)
    assert calls == 1
    calls = 0
    assert strict_current_entrypoint_records(store, owner="u1") == (canonical,)
    assert calls == 1
    calls = 0
    assert store.canonical_coverage(
        canonical.coverage_ref,
        owner="u1",
    ) == canonical
    assert calls == 1
    calls = 0
    assert strict_current_entrypoint_coverage(
        store,
        canonical.coverage_ref,
        owner="u1",
    ) == canonical
    assert calls == 1
    calls = 0
    lookup = strict_current_entrypoint_lookup(store, owner="u1")
    assert calls == 1
    assert lookup(canonical.coverage_ref) == canonical
    with pytest.raises(KeyError, match=legacy.coverage_ref):
        lookup(legacy.coverage_ref)
    assert calls == 1


def test_strict_current_entrypoint_reads_fail_closed_without_canonical_api():
    legacy = _entrypoint_record("api")
    registry = SimpleNamespace(
        canonical_projection_available=True,
        coverage=lambda *_args, **_kwargs: legacy,
        records=lambda **_kwargs: [legacy],
    )

    with pytest.raises(TypeError, match="lacks canonical proof reads"):
        strict_current_entrypoint_coverage(
            registry,
            legacy.coverage_ref,
            owner=legacy.recorded_by,
        )
    with pytest.raises(TypeError, match="lacks canonical proof reads"):
        strict_current_entrypoint_records(
            registry,
            owner=legacy.recorded_by,
        )


def test_strict_current_entrypoint_read_preserves_exact_transactional_consent(
    tmp_path,
):
    consent = _entrypoint_record(
        "api",
        entrypoint_ref="api:copy_trade.risk_consents.confirm",
        goal_sections=("§12",),
    )

    class _ConsentStore:
        @staticmethod
        def source_coverage_for_owner(coverage_ref, owner):
            if coverage_ref != consent.coverage_ref or owner != consent.recorded_by:
                raise KeyError(coverage_ref)
            return consent

    delegate = PersistentGoalEntrypointCoverageRegistry(
        tmp_path / "goal_entrypoint_coverage.jsonl",
        proof_ledger=GoalProofLedger(tmp_path / "goal_proof_ledger"),
        legacy_read_only=True,
    )
    registry = RiskConsentEntrypointCoverageRegistry(
        delegate,
        _ConsentStore(),
        entrypoint_ref="api:copy_trade.risk_consents.confirm",
    )

    assert strict_current_entrypoint_coverage(
        registry,
        consent.coverage_ref,
        owner=consent.recorded_by,
    ) == consent
    assert strict_current_entrypoint_lookup(
        registry,
        owner=consent.recorded_by,
    )(consent.coverage_ref) == consent
    assert strict_current_entrypoint_records(
        registry,
        owner=consent.recorded_by,
    ) == ()


def test_transactional_consent_registry_rejects_configurable_entrypoint(tmp_path):
    delegate = PersistentGoalEntrypointCoverageRegistry(
        tmp_path / "goal_entrypoint_coverage.jsonl",
        proof_ledger=GoalProofLedger(tmp_path / "goal_proof_ledger"),
        legacy_read_only=True,
    )

    with pytest.raises(
        ValueError,
        match="must be the reserved api:copy_trade.risk_consents.confirm source",
    ):
        RiskConsentEntrypointCoverageRegistry(
            delegate,
            object(),
            entrypoint_ref="api:not_copy_trade.anything",
        )


def test_transactional_consent_read_rejects_store_ref_substitution(tmp_path):
    requested = _entrypoint_record(
        "api",
        entrypoint_ref="api:copy_trade.risk_consents.confirm",
        goal_sections=("§12",),
    )
    substituted = _entrypoint_record(
        "api",
        entrypoint_ref="api:copy_trade.risk_consents.confirm",
        goal_sections=("§12", "§17"),
    )
    assert substituted.coverage_ref != requested.coverage_ref

    class _SubstitutingConsentStore:
        @staticmethod
        def source_coverage_for_owner(_coverage_ref, owner):
            assert owner == requested.recorded_by
            return substituted

    delegate = PersistentGoalEntrypointCoverageRegistry(
        tmp_path / "goal_entrypoint_coverage.jsonl",
        proof_ledger=GoalProofLedger(tmp_path / "goal_proof_ledger"),
        legacy_read_only=True,
    )
    registry = RiskConsentEntrypointCoverageRegistry(
        delegate,
        _SubstitutingConsentStore(),
        entrypoint_ref="api:copy_trade.risk_consents.confirm",
    )

    with pytest.raises(
        ValueError,
        match="transactional GOAL coverage does not match the reserved consent source",
    ):
        strict_current_entrypoint_coverage(
            registry,
            requested.coverage_ref,
            owner=requested.recorded_by,
        )
    lookup = strict_current_entrypoint_lookup(
        registry,
        owner=requested.recorded_by,
    )
    with pytest.raises(
        ValueError,
        match="transactional GOAL coverage does not match the reserved consent source",
    ):
        lookup(requested.coverage_ref)


def test_entrypoint_coverage_api_rejects_direct_proof_write(tmp_path, monkeypatch):
    client, store, _section_store = _client_with_goal_coverage_store(tmp_path, monkeypatch)
    payload = _payload(_entrypoint_record("api", recorded_by="spoofed-client"))

    response = client.post("/api/research-os/goal/entrypoint_coverage_records", json=payload)
    assert response.status_code == 422, response.text
    assert response.json()["detail"] == (
        "direct GOAL entrypoint coverage proof writes are disabled; "
        "use a governed producer entrypoint"
    )
    assert store.records() == []

    summary = client.get("/api/research-os/goal/entrypoint_coverage/summary")
    assert summary.status_code == 200
    data = summary.json()
    assert data["coverage_total"] == 0
    assert data["strictly_backed_coverage_total"] == 0
    assert data["invalid_coverage_total"] == 0
    assert data["recorded_entry_sources_present"] == []
    assert data["entry_sources_present"] == []
    assert data["entry_sources_with_valid_lineage"] == []
    assert data["all_entry_sources_have_valid_lineage"] is False
    assert "chat" in data["missing_entry_sources"]
    assert data["all_entrypoints_wired"] is False
    assert data["coverage_records"] == []


def test_entrypoint_coverage_api_rejects_invalid_without_writing(tmp_path, monkeypatch):
    client, store, _section_store = _client_with_goal_coverage_store(tmp_path, monkeypatch)
    payload = _payload(_entrypoint_record("chat", compiler_ir_refs=()))

    response = client.post("/api/research-os/goal/entrypoint_coverage_records", json=payload)
    assert response.status_code == 422
    assert "direct GOAL entrypoint coverage proof writes are disabled" in response.text
    assert store.records() == []


def test_section_coverage_registry_rejects_unknown_or_mismatched_entrypoint_refs(tmp_path):
    entrypoint_store = PersistentGoalEntrypointCoverageRegistry(tmp_path / "entrypoints.jsonl")
    section_store = PersistentGoalSectionCoverageRegistry(tmp_path / "sections.jsonl", entrypoint_store)

    with pytest.raises(ValueError, match="goal_section_unknown_entrypoint_wiring_ref"):
        section_store.record_coverage(
            _record("§0", full_entrypoint_wired=True, entrypoint_wiring_refs=("missing:coverage",))
        )
    assert section_store.records() == []


def test_section_registry_quarantines_legacy_rows_whose_entrypoint_rows_are_quarantined(tmp_path):
    entrypoint_path = tmp_path / "entrypoints.jsonl"
    section_path = tmp_path / "sections.jsonl"
    legacy_entrypoint = _entrypoint_record("api", goal_sections=("§0",))
    legacy_section = _record(
        "§0",
        full_entrypoint_wired=True,
        entrypoint_wiring_refs=(legacy_entrypoint.coverage_ref,),
    )
    entrypoint_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "event_type": "goal_entrypoint_coverage_recorded",
                "entrypoint_coverage": _payload(legacy_entrypoint),
            }
        )
        + "\n",
        encoding="utf-8",
    )
    section_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "event_type": "goal_section_coverage_recorded",
                "section_coverage": _payload(legacy_section),
            }
        )
        + "\n",
        encoding="utf-8",
    )

    entrypoint_store = PersistentGoalEntrypointCoverageRegistry(entrypoint_path)
    section_store = PersistentGoalSectionCoverageRegistry(section_path, entrypoint_store)

    assert entrypoint_store.legacy_quarantined_count == 1
    assert entrypoint_store.records() == []
    assert section_store.legacy_quarantined_count == 1
    assert section_store.records() == []
    assert "goal_section_coverage_recorded" in section_path.read_text(encoding="utf-8")

    candidate = _entrypoint_record("api", goal_sections=("§1",))
    entrypoint_store.set_ref_resolver(_resolver_for(candidate))
    coverage = entrypoint_store.record_coverage(candidate)
    with pytest.raises(ValueError, match="goal_section_entrypoint_ref_section_mismatch"):
        section_store.record_coverage(
            _record("§0", full_entrypoint_wired=True, entrypoint_wiring_refs=(coverage.coverage_ref,))
        )
    assert section_store.records() == []


def test_section_coverage_rejects_legacy_entrypoint_row_that_fails_strict_resolution(tmp_path):
    entrypoint_store = PersistentGoalEntrypointCoverageRegistry(tmp_path / "entrypoints.jsonl")
    legacy = entrypoint_store.record_coverage(_entrypoint_record("api", goal_sections=("§0",)))
    entrypoint_store.set_ref_resolver(_GoalResolver(backed=set()))
    section_store = PersistentGoalSectionCoverageRegistry(tmp_path / "sections.jsonl", entrypoint_store)

    with pytest.raises(ValueError, match="goal_section_entrypoint_ref_not_real_backed"):
        section_store.record_coverage(
            _record("§0", full_entrypoint_wired=True, entrypoint_wiring_refs=(legacy.coverage_ref,))
        )
    assert section_store.records() == []


def test_section_coverage_registry_isolates_same_section_by_owner(tmp_path):
    entrypoint_store = PersistentGoalEntrypointCoverageRegistry(
        tmp_path / "entrypoints.jsonl"
    )
    alice_entry = _entrypoint_record(
        "api",
        recorded_by="alice",
        goal_sections=("§0",),
    )
    bob_entry = _entrypoint_record(
        "api",
        recorded_by="bob",
        goal_sections=("§0",),
    )
    entrypoint_store.set_ref_resolver(_resolver_for(alice_entry))
    entrypoint_store.record_coverage(alice_entry)
    entrypoint_store.record_coverage(bob_entry)
    section_path = tmp_path / "sections.jsonl"
    section_store = PersistentGoalSectionCoverageRegistry(
        section_path,
        entrypoint_store,
    )

    for owner in ("alice", "bob"):
        section_store.record_coverage(
            _record(
                "§0",
                recorded_by=owner,
                full_entrypoint_wired=False,
                entrypoint_wiring_refs=(alice_entry.coverage_ref,),
            )
        )

    assert section_store.coverage("§0", owner="alice").recorded_by == "alice"
    assert section_store.coverage("§0", owner="bob").recorded_by == "bob"
    with pytest.raises(ValueError, match="owner-ambiguous"):
        section_store.coverage("§0")
    assert len(section_path.read_text(encoding="utf-8").splitlines()) == 2
    reloaded = PersistentGoalSectionCoverageRegistry(section_path, entrypoint_store)
    assert len(reloaded.records(owner="alice")) == 1
    assert len(reloaded.records(owner="bob")) == 1

def test_section_coverage_api_rejects_direct_proof_write(tmp_path, monkeypatch):
    client, entrypoint_store, section_store = _client_with_goal_coverage_store(tmp_path, monkeypatch)
    candidate = _entrypoint_record(
        "api",
        goal_sections=tuple(REQUIRED_GOAL_SECTIONS),
        claims_full_product_entrypoint=True,
    )
    entrypoint_store.set_ref_resolver(_resolver_for(candidate))
    coverage = entrypoint_store.record_coverage(candidate)

    payload = _payload(
        _record(
            "§0",
            recorded_by="spoofed-client",
            full_entrypoint_wired=False,
            entrypoint_wiring_refs=(coverage.coverage_ref,),
        )
    )
    response = client.post("/api/research-os/goal/section_coverage_records", json=payload)
    assert response.status_code == 422, response.text
    assert "direct GOAL section coverage proof writes are disabled" in response.text
    assert section_store.records(owner="u1") == []

    summary = client.get("/api/research-os/goal/section_coverage/summary")
    assert summary.status_code == 200
    data = summary.json()
    assert data["section_total"] == 0
    assert data["full_product_implementation"] is False
    assert "§1" in data["missing_sections"]


def test_section_coverage_api_rejects_full_product_lexical_refs_without_semantic_proofs(tmp_path, monkeypatch):
    client, entrypoint_store, _section_store = _client_with_goal_coverage_store(tmp_path, monkeypatch)
    candidate = _entrypoint_record(
        "api",
        goal_sections=tuple(REQUIRED_GOAL_SECTIONS),
        claims_full_product_entrypoint=True,
    )
    entrypoint_store.set_ref_resolver(_resolver_for(candidate))
    coverage = entrypoint_store.record_coverage(candidate)
    for section in REQUIRED_GOAL_SECTIONS:
        payload = _payload(
            _record(section, full_entrypoint_wired=True, entrypoint_wiring_refs=(coverage.coverage_ref,))
        )
        response = client.post("/api/research-os/goal/section_coverage_records", json=payload)
        assert response.status_code == 422, response.text
        assert "direct GOAL section coverage proof writes are disabled" in response.text

    summary = client.get("/api/research-os/goal/section_coverage/summary")
    assert summary.status_code == 200
    data = summary.json()
    assert data["section_total"] == 0
    assert set(data["missing_sections"]) == set(REQUIRED_GOAL_SECTIONS)
    assert data["full_product_implementation"] is False
    assert data["validation_mode"] == "owner_scoped_entrypoint_and_section_semantic_proof"


def test_section_coverage_api_rejects_unknown_entrypoint_ref_without_partial_write(tmp_path, monkeypatch):
    client, _entrypoint_store, section_store = _client_with_goal_coverage_store(tmp_path, monkeypatch)
    payload = _payload(
        _record("§0", full_entrypoint_wired=True, entrypoint_wiring_refs=("missing:coverage",))
    )

    response = client.post("/api/research-os/goal/section_coverage_records", json=payload)
    assert response.status_code == 422
    assert "direct GOAL section coverage proof writes are disabled" in response.text
    assert section_store.records() == []


def test_section_coverage_api_rejects_goal_closure_self_cert_ref(tmp_path, monkeypatch):
    client, entrypoint_store, section_store = _client_with_goal_coverage_store(tmp_path, monkeypatch)
    candidate = _entrypoint_record("api", goal_sections=("§0",))
    entrypoint_store.set_ref_resolver(_resolver_for(candidate))
    coverage = entrypoint_store.record_coverage(candidate)
    payload = _payload(
        _record(
            "§0",
            full_entrypoint_wired=True,
            entrypoint_wiring_refs=(coverage.coverage_ref,),
            evidence_refs=("evidence:goal_closure:section0",),
        )
    )

    response = client.post("/api/research-os/goal/section_coverage_records", json=payload)
    assert response.status_code == 422
    assert "direct GOAL section coverage proof writes are disabled" in response.text
    assert section_store.records() == []
