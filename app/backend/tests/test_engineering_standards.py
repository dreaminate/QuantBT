from __future__ import annotations

import json
from dataclasses import replace

import pytest

from app.research_os.engineering_standards import (
    DataUpdateStandardRecord,
    EngineeringStandardsRunRecord,
    FatalRuntimeStandardRecord,
    LLMReplayStandardRecord,
    MockHonestyRecord,
    PerformanceBaselineMeasurement,
    PerformanceBaselineRecord,
    PersistentEngineeringStandardsRegistry,
    TheoryImplementationStandardRecord,
    validate_data_update_standard,
    validate_engineering_standards,
    validate_engineering_standards_run_record,
    validate_fatal_runtime_standard,
    validate_llm_replay_standard,
    validate_mock_honesty,
    validate_performance_baseline,
    validate_theory_implementation_standard,
)


def _codes(decision) -> set[str]:
    return {violation.code for violation in decision.violations}


def _clean_run_record(source_run_ref: str = "ide_run:run-001") -> EngineeringStandardsRunRecord:
    return EngineeringStandardsRunRecord(
        source_run_ref=source_run_ref,
        mock_records=(
            MockHonestyRecord(
                record_ref="mock:run-001",
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
                update_ref="data:run-001",
                dataset_version_ref="dataset_version:run-001",
                checksum="sha256:data",
                lineage_ref="lineage:run-001",
                known_at_ref="known_at:run-001",
                effective_at_ref="effective_at:run-001",
                data_test_refs=("test:1", "test:2", "test:3", "test:4", "test:5"),
            ),
        ),
        llm_calls=(
            LLMReplayStandardRecord(
                call_ref="llm:run-001",
                provider_ref="provider:openai",
                model_ref="model:gpt",
                auth_ref="secretref:openai",
                cost_ref="cost:run-001",
                replay_state_ref="replay:run-001",
                llm_gateway_ref="llm_gateway",
                prompt_hash="sha256:prompt",
                tool_schema_hash="sha256:tools",
            ),
        ),
        theory_claims=(
            TheoryImplementationStandardRecord(
                claim_ref="claim:run-001",
                display_label="evidence_sufficient",
                theory_implementation_binding_ref="binding:run-001",
                consistency_check_ref="check:run-001",
            ),
        ),
        fatal_records=(
            FatalRuntimeStandardRecord(
                runtime_ref="runtime:run-001",
                secret_plaintext_surfaces=(),
                verifier_independence_claimed=True,
                verifier_independence_record_ref="independence:run-001",
            ),
        ),
        performance_records=(
            PerformanceBaselineMeasurement(
                baseline_ref="perf:run-001",
                metric_name="standard backtest",
                threshold_seconds=60.0,
                measured=True,
                observed_seconds=1.2,
                evidence_ref="benchmark:run-001",
            ),
        ),
    )


def test_production_profile_cannot_succeed_through_mock_or_template():
    decision = validate_mock_honesty(
        MockHonestyRecord(
            record_ref="mock:bad",
            production_profile=True,
            mock_used=True,
            mock_label_ref=None,
            fallback_reason_ref=None,
            template_response=True,
            production_success_claim=True,
        )
    )
    assert not decision.accepted
    assert _codes(decision) >= {
        "mock_block_missing_label_or_reason",
        "production_profile_mock_fallback",
        "template_or_mock_false_production_success",
    }


def test_data_update_requires_version_checksum_lineage_time_axes_and_five_tests():
    decision = validate_data_update_standard(
        DataUpdateStandardRecord(
            update_ref="data:update",
            dataset_version_ref=None,
            checksum=None,
            lineage_ref=None,
            known_at_ref=None,
            effective_at_ref=None,
            data_test_refs=("test:1",),
        )
    )
    assert not decision.accepted
    assert _codes(decision) >= {
        "data_update_missing_version_checksum_lineage",
        "data_update_too_few_data_tests",
    }


def test_llm_replay_requires_gateway_provider_model_auth_cost_and_hashes():
    decision = validate_llm_replay_standard(
        LLMReplayStandardRecord(
            call_ref="llm:bad",
            provider_ref=None,
            model_ref=None,
            auth_ref=None,
            cost_ref=None,
            replay_state_ref=None,
            llm_gateway_ref=None,
            prompt_hash=None,
            tool_schema_hash=None,
        )
    )
    assert not decision.accepted
    assert "llm_replay_missing_required_ref" in _codes(decision)


def test_proof_backed_implementation_requires_binding_and_consistency_and_no_user_waiver():
    decision = validate_theory_implementation_standard(
        TheoryImplementationStandardRecord(
            claim_ref="claim:proof",
            display_label="proof_backed",
            theory_implementation_binding_ref=None,
            consistency_check_ref=None,
            user_waiver_ref="waiver:001",
        )
    )
    assert not decision.accepted
    assert _codes(decision) >= {
        "strong_theory_claim_missing_binding_or_consistency",
        "user_waiver_displayed_as_strong_evidence",
    }


def test_fatal_runtime_standard_catches_secret_gateway_independence_a_share_and_leakage():
    decision = validate_fatal_runtime_standard(
        FatalRuntimeStandardRecord(
            runtime_ref="runtime:bad",
            secret_plaintext_surfaces=("rag", "logs"),
            role_agent_bypassed_llm_gateway=True,
            verifier_independence_claimed=True,
            verifier_independence_record_ref=None,
            a_share_live_order=True,
            production_mock_fallback=True,
            lookahead_leakage_detected=True,
        )
    )
    assert not decision.accepted
    assert _codes(decision) >= {
        "secret_plaintext_left_secure_backend",
        "role_agent_bypassed_llm_gateway",
        "verifier_independence_record_missing",
        "fatal_engineering_error_detected",
    }


def test_performance_baseline_requires_evidence_and_threshold_pass():
    decision = validate_performance_baseline(
        PerformanceBaselineRecord(
            baseline_ref="perf:run_first_screen",
            metric_name="Run first screen",
            observed_seconds=2.5,
            threshold_seconds=2.0,
            evidence_ref=None,
        )
    )
    assert not decision.accepted
    assert _codes(decision) >= {
        "performance_baseline_exceeded",
        "performance_baseline_missing_evidence",
    }


def test_complete_engineering_standards_contract_accepts_clean_records():
    decision = validate_engineering_standards(
        mock_records=(
            MockHonestyRecord(
                record_ref="mock:none",
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
                update_ref="data:update",
                dataset_version_ref="dataset_version:001",
                checksum="sha256:data",
                lineage_ref="lineage:001",
                known_at_ref="known_at:001",
                effective_at_ref="effective_at:001",
                data_test_refs=("test:1", "test:2", "test:3", "test:4", "test:5"),
            ),
        ),
        llm_calls=(
            LLMReplayStandardRecord(
                call_ref="llm:001",
                provider_ref="provider:openai",
                model_ref="model:gpt",
                auth_ref="secretref:openai",
                cost_ref="cost:001",
                replay_state_ref="replay:fixture",
                llm_gateway_ref="llm_gateway",
                prompt_hash="sha256:prompt",
                tool_schema_hash="sha256:tool_schema",
            ),
        ),
        theory_claims=(
            TheoryImplementationStandardRecord(
                claim_ref="claim:implementation",
                display_label="evidence_sufficient",
                theory_implementation_binding_ref="binding:001",
                consistency_check_ref="consistency:001",
            ),
        ),
        fatal_records=(
            FatalRuntimeStandardRecord(
                runtime_ref="runtime:clean",
                secret_plaintext_surfaces=(),
                verifier_independence_claimed=True,
                verifier_independence_record_ref="independence:001",
            ),
        ),
        performance_records=(
            PerformanceBaselineRecord(
                baseline_ref="perf:rag",
                metric_name="RAG first batch",
                observed_seconds=1.2,
                threshold_seconds=3.0,
                evidence_ref="benchmark:001",
            ),
        ),
    )
    assert decision.accepted
    assert decision.violations == ()


def test_complete_run_record_is_content_addressed_and_requires_all_six_families():
    record = _clean_run_record()
    assert record.record_ref.startswith("engstd_")
    assert validate_engineering_standards_run_record(record).accepted

    incomplete = replace(record, llm_calls=(), record_ref="")
    decision = validate_engineering_standards_run_record(incomplete)
    assert not decision.accepted
    assert "engineering_standard_family_missing" in _codes(decision)


def test_unmeasured_or_failed_performance_cannot_mint_run_receipt():
    record = _clean_run_record()
    gap = replace(
        record,
        performance_records=(
            replace(
                record.performance_records[0],
                measured=False,
                observed_seconds=None,
                evidence_ref=None,
                unavailable_reason="production corpus unavailable",
            ),
        ),
        record_ref="",
    )
    decision = validate_engineering_standards_run_record(gap)
    assert not decision.accepted
    assert "performance_baseline_known_run_gap" in _codes(decision)

    failed = replace(
        record,
        performance_records=(
            replace(record.performance_records[0], observed_seconds=61.0),
        ),
        record_ref="",
    )
    decision = validate_engineering_standards_run_record(failed)
    assert not decision.accepted
    assert "performance_baseline_exceeded" in _codes(decision)


def test_persistent_registry_is_owner_scoped_replay_safe_and_atomic(tmp_path):
    path = tmp_path / "engineering_standards.jsonl"
    registry = PersistentEngineeringStandardsRegistry(path)
    record = _clean_run_record()
    persisted = registry.record_run(
        record,
        owner_user_id="owner-a",
        recorded_by="alice",
    )
    before = path.read_bytes()

    assert registry.run_record(
        record.source_run_ref,
        owner_user_id="owner-a",
    ) == persisted
    assert registry.record(record.record_ref, owner_user_id="owner-a") == persisted
    with pytest.raises(KeyError):
        registry.run_record(record.source_run_ref, owner_user_id="owner-b")

    assert registry.record_run(
        record,
        owner_user_id="owner-a",
        recorded_by="alice",
    ) == persisted
    assert path.read_bytes() == before

    collision = replace(
        _clean_run_record(),
        fatal_records=(
            replace(_clean_run_record().fatal_records[0], runtime_ref="runtime:changed"),
        ),
        record_ref="",
    )
    with pytest.raises(ValueError, match="identity collision"):
        registry.record_run(
            collision,
            owner_user_id="owner-a",
            recorded_by="alice",
        )
    assert path.read_bytes() == before

    reloaded = PersistentEngineeringStandardsRegistry(path)
    assert reloaded.run_record(
        record.source_run_ref,
        owner_user_id="owner-a",
    ) == record


def test_registry_rejects_invalid_package_without_partial_write_and_quarantines_legacy(tmp_path):
    path = tmp_path / "engineering_standards.jsonl"
    path.write_text(
        json.dumps({"schema_version": 1, "record": {"source_run_ref": "legacy"}})
        + "\n",
        encoding="utf-8",
    )
    registry = PersistentEngineeringStandardsRegistry(path)
    assert registry.quarantined_legacy_rows == 1
    before = path.read_bytes()

    invalid = replace(_clean_run_record(), data_updates=(), record_ref="")
    with pytest.raises(ValueError, match="engineering_standard_family_missing"):
        registry.record_run(
            invalid,
            owner_user_id="owner-a",
            recorded_by="alice",
        )
    assert path.read_bytes() == before
