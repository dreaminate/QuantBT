from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app import main
from app.auth import require_user_dependency
from app.research_os.platform_coverage import (
    PersistentPlatformCoverageRegistry,
    REQUIRED_PLATFORM_ROWS,
    PlatformCapabilityRecord,
    PlatformRow,
    PlatformSpecificRef,
    platform_capability_record_to_dict,
    validate_platform_capability,
    validate_platform_capability_real_backing,
    validate_platform_coverage,
    validate_platform_coverage_real_manifest,
)


def _codes(decision) -> set[str]:
    return {violation.code for violation in decision.violations}


def _record(row: PlatformRow | str, **overrides) -> PlatformCapabilityRecord:
    data = {
        "m_row": row,
        "qro_ref": f"qro:{row}",
        "research_graph_ref": "research_graph",
        "lifecycle_ref": f"lifecycle:{row}",
        "governance_ref": f"governance:{row}",
        "rag_ref": f"rag:{row}",
        "math_spine_ref": f"math:{row}",
        "evidence_refs": (f"evidence:{row}",),
        "specific_refs": (),
    }
    data.update(overrides)
    return PlatformCapabilityRecord(**data)


def _specific(*keys: str) -> tuple[PlatformSpecificRef, ...]:
    return tuple(PlatformSpecificRef(key=key, ref=f"{key}:001") for key in keys)


_SPECIFIC_PREFIX_BY_KEY = {
    "ingestion_skill_ref": "ingestion_skill",
    "instrument_spec_ref": "instrument_spec",
    "model_passport_ref": "model_passport",
    "validation_dossier_ref": "validation_dossier",
    "signal_contract_ref": "signal_contract",
    "strategy_book_ref": "strategy_book",
    "execution_boundary_ref": "execution_boundary",
    "market_capability_matrix_ref": "market_capability_matrix",
    "llm_gateway_ref": "llm_gateway",
    "model_routing_policy_ref": "model_routing_policy",
    "credential_pool_ref": "credential_pool",
    "theory_implementation_binding_ref": "theory_binding",
    "typed_canvas_projection_ref": "typed_canvas_projection",
    "canonical_code_command_ref": "canonical_code_command",
    "consistency_check_ref": "consistency_check",
    "secret_ref": "secret",
    "kill_switch_ref": "kill_switch",
    "mock_label_ref": "mock_label",
    "asset_category_ref": "asset_category",
}


def _row_slug(row: PlatformRow | str) -> str:
    return str(row.value if hasattr(row, "value") else row).replace("-", "_")


def _real_specific(row: PlatformRow | str, *keys: str) -> tuple[PlatformSpecificRef, ...]:
    row_slug = _row_slug(row)
    return tuple(
        PlatformSpecificRef(
            key=key,
            ref=f"{_SPECIFIC_PREFIX_BY_KEY[key]}:platform_{row_slug}_{key}_real",
        )
        for key in keys
    )


def _real_record(row: PlatformRow | str, **overrides) -> PlatformCapabilityRecord:
    row_slug = _row_slug(row)
    data = {
        "m_row": row,
        "qro_ref": f"qro_platform_{row_slug}_real",
        "research_graph_ref": f"rgcmd_platform_{row_slug}_real",
        "lifecycle_ref": f"lifecycle_event:platform_{row_slug}_real",
        "governance_ref": f"governance_decision:platform_{row_slug}_real",
        "rag_ref": f"rag_asset:platform_{row_slug}_real",
        "math_spine_ref": f"math_spine_chain:platform_{row_slug}_real",
        "evidence_refs": (f"evidence:platform_{row_slug}_real",),
        "specific_refs": (),
    }
    data.update(overrides)
    return PlatformCapabilityRecord(**data)


def _complete_manifest() -> tuple[PlatformCapabilityRecord, ...]:
    records = []
    for row in REQUIRED_PLATFORM_ROWS:
        keys = {
            PlatformRow.M3.value: ("ingestion_skill_ref", "instrument_spec_ref"),
            PlatformRow.M6.value: ("model_passport_ref", "validation_dossier_ref"),
            PlatformRow.M7_M8.value: ("signal_contract_ref", "strategy_book_ref"),
            PlatformRow.M9.value: ("execution_boundary_ref", "market_capability_matrix_ref"),
            PlatformRow.M14.value: (
                "llm_gateway_ref",
                "model_routing_policy_ref",
                "credential_pool_ref",
                "theory_implementation_binding_ref",
            ),
            PlatformRow.M15.value: ("typed_canvas_projection_ref",),
            PlatformRow.M18.value: ("canonical_code_command_ref", "consistency_check_ref"),
            PlatformRow.M20.value: ("secret_ref", "llm_gateway_ref", "kill_switch_ref"),
            PlatformRow.M21.value: ("mock_label_ref", "asset_category_ref"),
        }.get(row, ())
        records.append(_record(row, specific_refs=_specific(*keys)))
    return tuple(records)


def _real_manifest() -> tuple[PlatformCapabilityRecord, ...]:
    records = []
    for row in REQUIRED_PLATFORM_ROWS:
        keys = {
            PlatformRow.M3.value: ("ingestion_skill_ref", "instrument_spec_ref"),
            PlatformRow.M6.value: ("model_passport_ref", "validation_dossier_ref"),
            PlatformRow.M7_M8.value: ("signal_contract_ref", "strategy_book_ref"),
            PlatformRow.M9.value: ("execution_boundary_ref", "market_capability_matrix_ref"),
            PlatformRow.M14.value: (
                "llm_gateway_ref",
                "model_routing_policy_ref",
                "credential_pool_ref",
                "theory_implementation_binding_ref",
            ),
            PlatformRow.M15.value: ("typed_canvas_projection_ref",),
            PlatformRow.M18.value: ("canonical_code_command_ref", "consistency_check_ref"),
            PlatformRow.M20.value: ("secret_ref", "llm_gateway_ref", "kill_switch_ref"),
            PlatformRow.M21.value: ("mock_label_ref", "asset_category_ref"),
        }.get(row, ())
        records.append(_real_record(row, specific_refs=_real_specific(row, *keys)))
    return tuple(records)


def _payload(records: tuple[PlatformCapabilityRecord, ...]) -> dict:
    return {"records": [platform_capability_record_to_dict(record) for record in records]}


def _client_with_platform_registry(tmp_path, monkeypatch):
    store = PersistentPlatformCoverageRegistry(tmp_path / "platform_coverage_manifest.jsonl")
    monkeypatch.setattr(main, "PLATFORM_COVERAGE_REGISTRY", store)
    main.app.dependency_overrides[require_user_dependency] = lambda: SimpleNamespace(
        username="u1",
        user_id="u1",
    )
    return TestClient(main.app), store


def test_platform_capability_requires_common_qro_graph_lifecycle_governance_rag_and_math_refs():
    decision = validate_platform_capability(
        _record(
            PlatformRow.M10,
            qro_ref=None,
            research_graph_ref=None,
            lifecycle_ref=None,
            evidence_refs=(),
        )
    )
    assert not decision.accepted
    assert _codes(decision) >= {
        "platform_capability_missing_common_ref",
        "platform_capability_missing_evidence",
    }


def test_platform_coverage_manifest_requires_every_m_row():
    records = tuple(record for record in _complete_manifest() if record.m_row != PlatformRow.M14.value)
    decision = validate_platform_coverage(records)
    assert not decision.accepted
    assert "platform_capability_row_missing" in _codes(decision)


def test_m14_agent_platform_requires_gateway_routing_credential_pool_and_math_binding():
    decision = validate_platform_capability(_record(PlatformRow.M14))
    assert not decision.accepted
    assert "platform_capability_missing_specific_ref" in _codes(decision)


def test_m21_examples_require_mock_label_and_asset_category_refs():
    decision = validate_platform_capability(_record(PlatformRow.M21, specific_refs=_specific("mock_label_ref")))
    assert not decision.accepted
    assert "platform_capability_missing_specific_ref" in _codes(decision)


def test_complete_platform_coverage_manifest_accepts_all_rows():
    decision = validate_platform_coverage(_complete_manifest())
    assert decision.accepted
    assert decision.violations == ()


def test_real_platform_manifest_requires_registry_shaped_refs():
    decision = validate_platform_coverage_real_manifest(_complete_manifest())
    assert not decision.accepted
    assert "platform_capability_ref_not_backed" in _codes(decision)


def test_real_platform_manifest_accepts_and_replays_all_rows(tmp_path):
    store = PersistentPlatformCoverageRegistry(tmp_path / "platform_coverage_manifest.jsonl")

    recorded = store.record_manifest(_real_manifest())
    assert len(recorded) == len(REQUIRED_PLATFORM_ROWS)
    assert validate_platform_coverage_real_manifest(tuple(store.records())).accepted

    reloaded = PersistentPlatformCoverageRegistry(tmp_path / "platform_coverage_manifest.jsonl")
    assert [record.m_row for record in reloaded.records()] == list(REQUIRED_PLATFORM_ROWS)
    assert validate_platform_coverage_real_manifest(tuple(reloaded.records())).accepted


def test_real_platform_manifest_rejects_synthetic_placeholder_manifest_without_writing(tmp_path):
    store = PersistentPlatformCoverageRegistry(tmp_path / "platform_coverage_manifest.jsonl")

    with pytest.raises(ValueError, match="platform_capability_ref_not_backed"):
        store.record_manifest(_complete_manifest())

    assert store.records() == []
    assert not (tmp_path / "platform_coverage_manifest.jsonl").exists()


def test_real_m14_requires_gateway_routing_credentials_and_theory_binding():
    decision = validate_platform_capability_real_backing(
        _real_record(
            PlatformRow.M14,
            specific_refs=_real_specific(
                PlatformRow.M14,
                "model_routing_policy_ref",
                "credential_pool_ref",
                "theory_implementation_binding_ref",
            ),
        )
    )
    assert not decision.accepted
    assert "platform_capability_missing_specific_ref" in _codes(decision)


def test_real_m21_requires_mock_label_and_asset_category_refs():
    decision = validate_platform_capability_real_backing(
        _real_record(PlatformRow.M21, specific_refs=_real_specific(PlatformRow.M21, "mock_label_ref"))
    )
    assert not decision.accepted
    assert "platform_capability_missing_specific_ref" in _codes(decision)


def test_platform_coverage_api_records_summary_and_rejects_synthetic_manifest(tmp_path, monkeypatch):
    client, store = _client_with_platform_registry(tmp_path, monkeypatch)
    try:
        synthetic_response = client.post("/api/research-os/platform/coverage_manifest", json=_payload(_complete_manifest()))
        assert synthetic_response.status_code == 422
        assert store.records() == []

        response = client.post("/api/research-os/platform/coverage_manifest", json=_payload(_real_manifest()))
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["recorded_by"] == "u1"
        assert body["platform_row_total"] == len(REQUIRED_PLATFORM_ROWS)
        assert body["full_platform_coverage"] is True

        summary = client.get("/api/research-os/platform/coverage_summary")
        assert summary.status_code == 200
        data = summary.json()
        assert data["platform_row_total"] == len(REQUIRED_PLATFORM_ROWS)
        assert data["platform_rows_present"] == list(REQUIRED_PLATFORM_ROWS)
        assert data["missing_platform_rows"] == []
        assert data["full_platform_coverage"] is True
    finally:
        main.app.dependency_overrides.pop(require_user_dependency, None)
