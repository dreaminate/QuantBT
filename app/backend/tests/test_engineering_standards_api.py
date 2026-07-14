from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

import app.main as main
from app.auth import require_user_dependency
from app.research_os.engineering_standards import (
    DataUpdateStandardRecord,
    EngineeringStandardsRunRecord,
    FatalRuntimeStandardRecord,
    LLMReplayStandardRecord,
    MockHonestyRecord,
    PerformanceBaselineMeasurement,
    PersistentEngineeringStandardsRegistry,
    TheoryImplementationStandardRecord,
    engineering_standards_run_record_to_dict,
)


def _record() -> EngineeringStandardsRunRecord:
    return EngineeringStandardsRunRecord(
        source_run_ref="ide_run:api-001",
        mock_records=(
            MockHonestyRecord(
                record_ref="mock:api-001",
                production_profile=True,
                mock_used=False,
                mock_label_ref=None,
                fallback_reason_ref=None,
                template_response=False,
                production_success_claim=True,
            ),
        ),
        data_updates=(
            DataUpdateStandardRecord(
                update_ref="data:api-001",
                dataset_version_ref="dataset_version:api-001",
                checksum="sha256:data",
                lineage_ref="lineage:api-001",
                known_at_ref="known_at:api-001",
                effective_at_ref="effective_at:api-001",
                data_test_refs=tuple(f"test:{i}" for i in range(5)),
            ),
        ),
        llm_calls=(
            LLMReplayStandardRecord(
                call_ref="llm:api-001",
                provider_ref="provider:openai",
                model_ref="model:gpt",
                auth_ref="secretref:openai",
                cost_ref="cost:api-001",
                replay_state_ref="replay:api-001",
                llm_gateway_ref="llm_gateway",
                prompt_hash="sha256:prompt",
                tool_schema_hash="sha256:tools",
            ),
        ),
        theory_claims=(
            TheoryImplementationStandardRecord(
                claim_ref="claim:api-001",
                display_label="exploratory",
                theory_implementation_binding_ref="binding:api-001",
                consistency_check_ref="check:api-001",
            ),
        ),
        fatal_records=(
            FatalRuntimeStandardRecord(
                runtime_ref="runtime:api-001",
                secret_plaintext_surfaces=(),
            ),
        ),
        performance_records=(
            PerformanceBaselineMeasurement(
                baseline_ref="perf:api-001",
                metric_name="standard backtest",
                threshold_seconds=60.0,
                measured=True,
                observed_seconds=1.0,
                evidence_ref="benchmark:api-001",
            ),
        ),
    )


def test_engineering_standard_api_uses_authenticated_owner_and_isolates_summary(
    tmp_path,
    monkeypatch,
):
    registry = PersistentEngineeringStandardsRegistry(tmp_path / "engineering.jsonl")
    monkeypatch.setattr(main, "ENGINEERING_STANDARDS_REGISTRY", registry)
    main.app.dependency_overrides[require_user_dependency] = lambda: SimpleNamespace(
        username="alice",
        user_id="alice-id",
    )
    try:
        client = TestClient(main.app)
        payload = engineering_standards_run_record_to_dict(_record())
        payload["owner_user_id"] = "victim-id"
        response = client.post(
            "/api/research-os/engineering-standards/run_records",
            json=payload,
        )
        assert response.status_code == 200, response.text
        assert registry.run_record(
            "ide_run:api-001",
            owner_user_id="alice-id",
        ).record_ref == response.json()["record"]["record_ref"]
        with pytest.raises(KeyError):
            registry.run_record("ide_run:api-001", owner_user_id="victim-id")

        main.app.dependency_overrides[require_user_dependency] = lambda: SimpleNamespace(
            username="bob",
            user_id="bob-id",
        )
        summary = client.get("/api/research-os/engineering-standards/run_records")
        assert summary.status_code == 200
        assert summary.json()["total"] == 0
    finally:
        main.app.dependency_overrides.pop(require_user_dependency, None)


def test_engineering_standard_api_rejects_partial_family_without_write(
    tmp_path,
    monkeypatch,
):
    registry = PersistentEngineeringStandardsRegistry(tmp_path / "engineering.jsonl")
    monkeypatch.setattr(main, "ENGINEERING_STANDARDS_REGISTRY", registry)
    main.app.dependency_overrides[require_user_dependency] = lambda: SimpleNamespace(
        username="alice",
        user_id="alice-id",
    )
    try:
        payload = engineering_standards_run_record_to_dict(_record())
        payload["llm_calls"] = []
        response = TestClient(main.app).post(
            "/api/research-os/engineering-standards/run_records",
            json=payload,
        )
        assert response.status_code == 422
        assert registry.records(owner_user_id="alice-id") == []
        assert not registry.path.exists()
    finally:
        main.app.dependency_overrides.pop(require_user_dependency, None)
