from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app import main
from app.auth import require_user_dependency
from app.research_os.goal_coverage import (
    REQUIRED_ENTRY_SOURCES,
    REQUIRED_GOAL_SECTIONS,
    GoalEntrypointCoverageRecord,
    GoalSectionCoverageRecord,
    PersistentGoalEntrypointCoverageRegistry,
    PersistentGoalSectionCoverageRegistry,
    validate_goal_entrypoint_coverage,
    validate_goal_entrypoint_coverage_manifest,
    validate_goal_coverage_manifest,
    validate_goal_section_coverage,
)


def _codes(decision) -> set[str]:
    return {violation.code for violation in decision.violations}


def _record(section: str, **overrides) -> GoalSectionCoverageRecord:
    data = {
        "section": section,
        "contract_refs": (f"contract:{section}",),
        "test_refs": (f"test:{section}",),
        "task_refs": (f"task:{section}",),
        "evidence_refs": (f"evidence:{section}",),
    }
    data.update(overrides)
    return GoalSectionCoverageRecord(**data)


def _contract_manifest() -> tuple[GoalSectionCoverageRecord, ...]:
    return tuple(_record(section) for section in REQUIRED_GOAL_SECTIONS)


def _entrypoint_record(source: str = "api", **overrides) -> GoalEntrypointCoverageRecord:
    data = {
        "coverage_ref": f"entrypoint_coverage:{source}:strategy_goal:v1",
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
    }
    data.update(overrides)
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


def test_entrypoint_coverage_api_records_summary_and_overrides_actor(tmp_path, monkeypatch):
    client, store, _section_store = _client_with_goal_coverage_store(tmp_path, monkeypatch)
    payload = _payload(_entrypoint_record("api", recorded_by="spoofed-client"))

    response = client.post("/api/research-os/goal/entrypoint_coverage_records", json=payload)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["coverage_ref"] == payload["coverage_ref"]
    assert body["entry_source"] == "api"
    assert body["recorded_by"] == "u1"
    assert store.coverage(payload["coverage_ref"]).recorded_by == "u1"

    summary = client.get("/api/research-os/goal/entrypoint_coverage/summary")
    assert summary.status_code == 200
    data = summary.json()
    assert data["coverage_total"] == 1
    assert data["entry_sources_present"] == ["api"]
    assert "chat" in data["missing_entry_sources"]
    assert data["all_entrypoints_wired"] is False


def test_entrypoint_coverage_api_rejects_invalid_without_writing(tmp_path, monkeypatch):
    client, store, _section_store = _client_with_goal_coverage_store(tmp_path, monkeypatch)
    payload = _payload(_entrypoint_record("chat", compiler_ir_refs=()))

    response = client.post("/api/research-os/goal/entrypoint_coverage_records", json=payload)
    assert response.status_code == 422
    assert store.records() == []


def test_section_coverage_registry_rejects_unknown_or_mismatched_entrypoint_refs(tmp_path):
    entrypoint_store = PersistentGoalEntrypointCoverageRegistry(tmp_path / "entrypoints.jsonl")
    section_store = PersistentGoalSectionCoverageRegistry(tmp_path / "sections.jsonl", entrypoint_store)

    with pytest.raises(ValueError, match="goal_section_unknown_entrypoint_wiring_ref"):
        section_store.record_coverage(
            _record("§0", full_entrypoint_wired=True, entrypoint_wiring_refs=("missing:coverage",))
        )
    assert section_store.records() == []

    coverage = entrypoint_store.record_coverage(_entrypoint_record("api", goal_sections=("§1",)))
    with pytest.raises(ValueError, match="goal_section_entrypoint_ref_section_mismatch"):
        section_store.record_coverage(
            _record("§0", full_entrypoint_wired=True, entrypoint_wiring_refs=(coverage.coverage_ref,))
        )
    assert section_store.records() == []


def test_section_coverage_api_records_summary_and_keeps_full_claim_false_until_complete(tmp_path, monkeypatch):
    client, entrypoint_store, section_store = _client_with_goal_coverage_store(tmp_path, monkeypatch)
    coverage = entrypoint_store.record_coverage(
        _entrypoint_record(
            "api",
            goal_sections=tuple(REQUIRED_GOAL_SECTIONS),
            claims_full_product_entrypoint=True,
        )
    )

    payload = _payload(
        _record("§0", full_entrypoint_wired=True, entrypoint_wiring_refs=(coverage.coverage_ref,))
    )
    response = client.post("/api/research-os/goal/section_coverage_records", json=payload)
    assert response.status_code == 200, response.text
    assert response.json()["section"] == "§0"
    assert section_store.coverage("§0").entrypoint_wiring_refs == (coverage.coverage_ref,)

    summary = client.get("/api/research-os/goal/section_coverage/summary")
    assert summary.status_code == 200
    data = summary.json()
    assert data["section_total"] == 1
    assert data["full_product_implementation"] is False
    assert "§1" in data["missing_sections"]


def test_section_coverage_api_accepts_full_product_only_with_all_sections_wired(tmp_path, monkeypatch):
    client, entrypoint_store, _section_store = _client_with_goal_coverage_store(tmp_path, monkeypatch)
    coverage = entrypoint_store.record_coverage(
        _entrypoint_record(
            "api",
            goal_sections=tuple(REQUIRED_GOAL_SECTIONS),
            claims_full_product_entrypoint=True,
        )
    )
    for section in REQUIRED_GOAL_SECTIONS:
        payload = _payload(
            _record(section, full_entrypoint_wired=True, entrypoint_wiring_refs=(coverage.coverage_ref,))
        )
        response = client.post("/api/research-os/goal/section_coverage_records", json=payload)
        assert response.status_code == 200, response.text

    summary = client.get("/api/research-os/goal/section_coverage/summary")
    assert summary.status_code == 200
    data = summary.json()
    assert data["section_total"] == len(REQUIRED_GOAL_SECTIONS)
    assert data["missing_sections"] == []
    assert data["not_full_entrypoint_wired_sections"] == []
    assert data["full_product_implementation"] is True


def test_section_coverage_api_rejects_unknown_entrypoint_ref_without_partial_write(tmp_path, monkeypatch):
    client, _entrypoint_store, section_store = _client_with_goal_coverage_store(tmp_path, monkeypatch)
    payload = _payload(
        _record("§0", full_entrypoint_wired=True, entrypoint_wiring_refs=("missing:coverage",))
    )

    response = client.post("/api/research-os/goal/section_coverage_records", json=payload)
    assert response.status_code == 422
    assert "goal_section_unknown_entrypoint_wiring_ref" in response.text
    assert section_store.records() == []
