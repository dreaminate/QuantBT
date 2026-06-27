from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app import main
from app.auth import require_user_dependency
from app.research_os.methodology_validation import (
    LiveMonitoringAlertRecord,
    MethodologyChoiceCoverageRecord,
    PersistentMethodologyCalculatorRegistry,
    PersistentMethodologyRuntimeDrillRegistry,
    PersistentValidationDepthRegistry,
    RuntimeDrillRecord,
    ValidationDepthRecord,
    ValidationMethodologyRecord,
    calculate_conformal,
    calculate_cpcv,
    calculate_tca,
    record_runtime_drill,
    validate_live_monitoring_alert,
    validate_methodology_choice_coverage,
    validate_methodology_contract,
    validate_runtime_drill,
    validate_validation_depth,
    validate_validation_methodology,
)


def _codes(decision) -> set[str]:
    return {violation.code for violation in decision.violations}


def _validation(**overrides) -> ValidationMethodologyRecord:
    data = {
        "validation_ref": "validation:001",
        "claim_label": "evidence_sufficient",
        "sample_size": 240,
        "pbo_ref": "pbo:001",
        "dsr_ref": "dsr:001",
        "bootstrap_ci_ref": "bootstrap:001",
        "cpcv_ref": "cpcv:001",
        "walk_forward_ref": None,
        "purge_embargo_ref": "purge_embargo:001",
        "honest_n_ref": "honest_n:001",
        "multiple_testing_ref": "multiple_testing:001",
        "cost_model_refs": ("cost:equity", "cost:borrow"),
        "tca_ref": "tca:001",
        "target_environment": "paper",
    }
    data.update(overrides)
    return ValidationMethodologyRecord(**data)


def _depth(**overrides) -> ValidationDepthRecord:
    data = {
        "depth_ref": "validation_depth:001",
        "claim_ref": "validation:001",
        "claim_label": "evidence_sufficient",
        "target_environment": "paper",
        "cpcv_ref": "cpcv:001",
        "walk_forward_ref": "walk_forward:001",
        "conformal_ref": "conformal:001",
        "abstain_policy_ref": "abstain:001",
        "tca_ref": "tca:001",
        "cost_model_refs": ("cost:equity", "cost:borrow"),
        "feature_leakage_probe_refs": ("leakage:features:001",),
        "feature_leakage_verdict": "no_violation",
        "fault_injection_refs": ("fault:provider-timeout",),
        "fault_injection_verdict": "passed",
        "recovery_drill_refs": ("recovery:reconcile-before-resend",),
        "recovery_drill_verdict": "passed",
        "evidence_refs": ("evidence:validation-depth",),
        "validation_result_refs": ("pytest:test_methodology_validation_depth",),
    }
    data.update(overrides)
    return ValidationDepthRecord(**data)


def _runtime_drill(**overrides) -> RuntimeDrillRecord:
    data = {
        "runtime_drill_ref": "runtime_drill:001",
        "claim_ref": "validation:001",
        "target_environment": "paper",
        "drill_mode": "simulation",
        "venue_ref": "venue:paper:local",
        "fault_scenario": "venue_timeout",
        "expected_guard_ref": "order_guard:timeout_guard",
        "observed_guard_ref": "order_guard:timeout_guard",
        "recovery_action_ref": "recovery:reconcile_before_resend",
        "fault_injection_ref": "fault_injection:venue_timeout:001",
        "recovery_drill_ref": "recovery_drill:reconcile:001",
        "fault_injection_verdict": "passed",
        "recovery_drill_verdict": "passed",
        "source_hash": "sha256:runtime-drill",
        "evidence_refs": ("evidence:runtime-drill",),
        "validation_result_refs": ("pytest:runtime-drill",),
    }
    data.update(overrides)
    return RuntimeDrillRecord(**data)


def _payload(record) -> dict:
    return record.__dict__.copy()


def _client_with_depth_store(tmp_path, monkeypatch):
    store = PersistentValidationDepthRegistry(tmp_path / "methodology_validation_depth.jsonl")
    calculator_store = PersistentMethodologyCalculatorRegistry(tmp_path / "methodology_calculators.jsonl")
    runtime_drill_store = PersistentMethodologyRuntimeDrillRegistry(tmp_path / "methodology_runtime_drills.jsonl")
    monkeypatch.setattr(main, "VALIDATION_DEPTH_REGISTRY", store)
    monkeypatch.setattr(main, "METHODOLOGY_CALCULATOR_REGISTRY", calculator_store)
    monkeypatch.setattr(main, "METHODOLOGY_RUNTIME_DRILL_REGISTRY", runtime_drill_store)
    main.app.dependency_overrides[require_user_dependency] = lambda: SimpleNamespace(
        username="u1",
        user_id="u1",
    )
    return TestClient(main.app), store, calculator_store, runtime_drill_store


def test_short_sample_cannot_output_strong_conclusion():
    decision = validate_validation_methodology(_validation(sample_size=12))
    assert not decision.accepted
    assert "short_sample_strong_conclusion" in _codes(decision)


def test_strong_validation_requires_bias_interval_honest_n_and_cpcv_or_walk_forward():
    decision = validate_validation_methodology(
        _validation(
            pbo_ref=None,
            bootstrap_ci_ref=None,
            cpcv_ref=None,
            walk_forward_ref=None,
            honest_n_ref=None,
            multiple_testing_ref=None,
        )
    )
    assert not decision.accepted
    assert _codes(decision) >= {
        "strong_validation_missing_method_ref",
        "strong_validation_missing_cpcv_or_walk_forward",
    }


def test_production_candidate_requires_cost_model():
    decision = validate_validation_methodology(_validation(cost_model_refs=()))
    assert not decision.accepted
    assert "production_candidate_missing_cost_model" in _codes(decision)


def test_user_waived_validation_cannot_be_marked_strong_and_requires_records():
    decision = validate_validation_methodology(
        _validation(
            user_waived_path=True,
            methodology_choice_ref=None,
            responsibility_boundary_ref=None,
        )
    )
    assert not decision.accepted
    assert _codes(decision) >= {
        "user_waived_path_marked_strong",
        "user_waived_methodology_missing_choice_or_responsibility",
    }


def test_methodology_choice_requires_tradeoffs_recommendation_and_responsibility():
    decision = validate_methodology_choice_coverage(
        MethodologyChoiceCoverageRecord(
            choice_ref="choice:loose",
            control_level="loose",
            tradeoffs_ref=None,
            recommendation_ref=None,
            responsibility_boundary_ref=None,
            allowed_environment=None,
        )
    )
    assert not decision.accepted
    assert "methodology_choice_missing_disclosure" in _codes(decision)


def test_dsr_cannot_be_primary_live_monitoring_alert():
    decision = validate_live_monitoring_alert(
        LiveMonitoringAlertRecord(
            alert_ref="alert:live",
            dsr_ref="dsr:001",
            performance_primary_alert_ref=None,
            drift_root_cause_ref="drift:psi",
            used_dsr_as_primary_live_alert=True,
        )
    )
    assert not decision.accepted
    assert "dsr_used_as_primary_live_monitor" in _codes(decision)


def test_validation_depth_requires_dual_track_conformal_abstain_and_runtime_drills():
    decision = validate_validation_depth(
        _depth(
            walk_forward_ref=None,
            conformal_ref=None,
            abstain_policy_ref=None,
            tca_ref=None,
            cost_model_refs=(),
            feature_leakage_probe_refs=(),
            feature_leakage_verdict="failed",
            fault_injection_refs=(),
            fault_injection_verdict="failed",
            recovery_drill_refs=(),
            recovery_drill_verdict="failed",
        )
    )
    assert not decision.accepted
    assert _codes(decision) >= {
        "validation_depth_required_ref_missing",
        "validation_depth_feature_leakage_not_cleared",
        "validation_depth_fault_injection_not_cleared",
        "validation_depth_recovery_drill_not_cleared",
    }
    assert {violation.field for violation in decision.violations} >= {
        "walk_forward_ref",
        "conformal_ref",
        "abstain_policy_ref",
        "tca_ref",
        "cost_model_refs",
        "feature_leakage_probe_refs",
        "fault_injection_refs",
        "recovery_drill_refs",
    }


def test_validation_depth_rejects_user_waived_strong_label_and_silent_mock():
    decision = validate_validation_depth(
        _depth(
            user_waived_path=True,
            methodology_choice_ref=None,
            responsibility_boundary_ref=None,
            silent_mock_fallback_used=True,
        )
    )
    assert not decision.accepted
    assert _codes(decision) >= {
        "validation_depth_user_waived_marked_strong",
        "validation_depth_silent_mock_fallback",
        "validation_depth_required_ref_missing",
    }


def test_complete_methodology_contract_accepts_strong_validated_candidate():
    decision = validate_methodology_contract(
        (_validation(),),
        choices=(
            MethodologyChoiceCoverageRecord(
                choice_ref="choice:standard",
                control_level="standard",
                tradeoffs_ref=None,
                recommendation_ref=None,
                responsibility_boundary_ref=None,
                allowed_environment=None,
            ),
        ),
        live_alerts=(
            LiveMonitoringAlertRecord(
                alert_ref="alert:live",
                dsr_ref="dsr:001",
                performance_primary_alert_ref="perf:drawdown",
                drift_root_cause_ref="drift:feature",
                used_dsr_as_primary_live_alert=False,
            ),
        ),
        validation_depths=(_depth(),),
    )
    assert decision.accepted
    assert decision.violations == ()


def test_persistent_validation_depth_registry_replays_record(tmp_path):
    path = tmp_path / "methodology_validation_depth.jsonl"
    store = PersistentValidationDepthRegistry(path)
    store.record_depth(_depth())

    reloaded = PersistentValidationDepthRegistry(path)
    assert reloaded.depth("validation_depth:001").walk_forward_ref == "walk_forward:001"
    assert reloaded.depths()[0].fault_injection_refs == ("fault:provider-timeout",)


def test_methodology_calculators_return_refs_hashes_and_summaries_without_raw_series():
    cpcv = calculate_cpcv(
        claim_ref="claim:strategy",
        fold_metric_values=(0.11, 0.07, 0.15),
        embargo_observations=2,
        evidence_refs=("evidence:cpcv",),
        validation_result_refs=("pytest:cpcv",),
    )
    conformal = calculate_conformal(
        claim_ref="claim:strategy",
        calibration_scores=(0.05, 0.08, 0.03, 0.09, 0.04),
        alpha=0.2,
        abstain_policy_ref="abstain:drawdown",
        evidence_refs=("evidence:conformal",),
        validation_result_refs=("pytest:conformal",),
    )
    tca = calculate_tca(
        claim_ref="claim:strategy",
        gross_return_bps=(10.0, 14.0, 8.0),
        cost_components_bps={"spread": 1.5, "fee": 0.5, "slippage": 2.0},
        cost_model_refs=("cost:crypto",),
        evidence_refs=("evidence:tca",),
        validation_result_refs=("pytest:tca",),
    )

    assert cpcv.cpcv_ref.startswith("cpcv:")
    assert cpcv.mean_metric == pytest.approx(0.11)
    assert conformal.conformal_ref.startswith("conformal:")
    assert conformal.nonconformity_threshold == pytest.approx(0.09)
    assert conformal.coverage_estimate == pytest.approx(0.8)
    assert tca.tca_ref.startswith("tca:")
    assert tca.total_cost_bps == pytest.approx(4.0)
    assert tca.net_mean_bps == pytest.approx((10.0 + 14.0 + 8.0) / 3 - 4.0)
    serialized = str(cpcv.__dict__) + str(conformal.__dict__) + str(tca.__dict__)
    assert "fold_metric_values" not in serialized
    assert "calibration_scores" not in serialized
    assert "gross_return_bps" not in serialized


def test_methodology_calculator_registry_replays_all_calculator_records(tmp_path):
    path = tmp_path / "methodology_calculators.jsonl"
    store = PersistentMethodologyCalculatorRegistry(path)
    cpcv = store.record_cpcv(
        calculate_cpcv(
            claim_ref="claim:strategy",
            fold_metric_values=(1.0, 2.0),
            evidence_refs=("evidence:cpcv",),
            validation_result_refs=("pytest:cpcv",),
        )
    )
    conformal = store.record_conformal(
        calculate_conformal(
            claim_ref="claim:strategy",
            calibration_scores=(0.1, 0.2, 0.3, 0.4, 0.5),
            alpha=0.2,
            evidence_refs=("evidence:conformal",),
            validation_result_refs=("pytest:conformal",),
        )
    )
    tca = store.record_tca(
        calculate_tca(
            claim_ref="claim:strategy",
            gross_return_bps=(5.0, 7.0),
            cost_components_bps={"fee": 1.0},
            cost_model_refs=("cost:basic",),
            evidence_refs=("evidence:tca",),
            validation_result_refs=("pytest:tca",),
        )
    )

    reloaded = PersistentMethodologyCalculatorRegistry(path)
    assert reloaded.cpcv(cpcv.cpcv_ref).sample_count == 2
    assert reloaded.conformal(conformal.conformal_ref).calibration_count == 5
    assert reloaded.tca(tca.tca_ref).net_mean_bps == pytest.approx(5.0)


def test_runtime_drill_producer_returns_refs_hashes_and_replays_without_raw_logs(tmp_path):
    record = record_runtime_drill(
        claim_ref="validation:001",
        target_environment="paper",
        drill_mode="simulation",
        venue_ref="venue:paper:local",
        fault_scenario="venue_timeout",
        expected_guard_ref="order_guard:timeout_guard",
        observed_guard_ref="order_guard:timeout_guard",
        recovery_action_ref="recovery:reconcile_before_resend",
        evidence_refs=("evidence:runtime-drill",),
        validation_result_refs=("pytest:runtime-drill",),
    )
    assert record.runtime_drill_ref.startswith("runtime_drill:")
    assert record.fault_injection_ref.startswith("fault_injection:")
    assert record.recovery_drill_ref.startswith("recovery_drill:")
    assert record.source_hash
    assert validate_runtime_drill(record).accepted

    path = tmp_path / "methodology_runtime_drills.jsonl"
    store = PersistentMethodologyRuntimeDrillRegistry(path)
    store.record_runtime_drill(record)

    reloaded = PersistentMethodologyRuntimeDrillRegistry(path)
    assert reloaded.runtime_drill(record.runtime_drill_ref).fault_scenario == "venue_timeout"
    serialized = str(reloaded.runtime_drill(record.runtime_drill_ref).__dict__)
    assert "raw_log" not in serialized
    assert "traceback" not in serialized


def test_runtime_drill_rejects_unsafe_modes_guard_mismatch_and_silent_mock(tmp_path):
    assert "runtime_drill_guard_mismatch" in _codes(
        validate_runtime_drill(_runtime_drill(observed_guard_ref="order_guard:wrong_guard"))
    )
    assert "runtime_drill_unsafe_mode" in _codes(validate_runtime_drill(_runtime_drill(drill_mode="live")))

    store = PersistentMethodologyRuntimeDrillRegistry(tmp_path / "methodology_runtime_drills.jsonl")
    with pytest.raises(ValueError, match="runtime_drill_silent_mock_fallback"):
        store.record_runtime_drill(_runtime_drill(silent_mock_fallback_used=True))

    assert not store.path.exists()


def test_persistent_validation_depth_registry_rejects_invalid_without_writing(tmp_path):
    store = PersistentValidationDepthRegistry(tmp_path / "methodology_validation_depth.jsonl")

    with pytest.raises(ValueError, match="validation_depth_required_ref_missing"):
        store.record_depth(_depth(evidence_refs=(), validation_result_refs=()))

    assert not store.path.exists()


def test_methodology_validation_depth_api_records_summary(tmp_path, monkeypatch):
    client, _store, _calculator_store, _runtime_drill_store = _client_with_depth_store(tmp_path, monkeypatch)
    try:
        response = client.post(
            "/api/research-os/methodology/validation_depth_records",
            json=_payload(_depth()),
        )
        assert response.status_code == 200, response.text
        assert response.json() == {
            "depth_ref": "validation_depth:001",
            "claim_ref": "validation:001",
            "target_environment": "paper",
            "recorded_by": "u1",
        }

        summary = client.get("/api/research-os/methodology/summary")
        assert summary.status_code == 200
        body = summary.json()
        assert body["user"] == "u1"
        assert body["validation_depth_total"] == 1
        assert body["validation_depths"][0]["cpcv_ref"] == "cpcv:001"
        assert body["validation_depths"][0]["walk_forward_ref"] == "walk_forward:001"
        assert body["validation_depths"][0]["feature_leakage_verdict"] == "no_violation"
    finally:
        main.app.dependency_overrides.pop(require_user_dependency, None)


def test_methodology_validation_depth_api_rejects_silent_mock_without_persisting(tmp_path, monkeypatch):
    client, store, _calculator_store, _runtime_drill_store = _client_with_depth_store(tmp_path, monkeypatch)
    try:
        response = client.post(
            "/api/research-os/methodology/validation_depth_records",
            json=_payload(_depth(silent_mock_fallback_used=True)),
        )
        assert response.status_code == 422
        assert "validation_depth_silent_mock_fallback" in response.json()["detail"]
        assert not store.path.exists()
    finally:
        main.app.dependency_overrides.pop(require_user_dependency, None)


def test_methodology_runtime_drill_api_records_summary_and_rejects_unsafe_mode(tmp_path, monkeypatch):
    client, _store, _calculator_store, runtime_drill_store = _client_with_depth_store(tmp_path, monkeypatch)
    try:
        response = client.post(
            "/api/research-os/methodology/runtime_drills",
            json={
                "claim_ref": "validation:001",
                "target_environment": "paper",
                "drill_mode": "simulation",
                "venue_ref": "venue:paper:local",
                "fault_scenario": "venue_timeout",
                "expected_guard_ref": "order_guard:timeout_guard",
                "observed_guard_ref": "order_guard:timeout_guard",
                "recovery_action_ref": "recovery:reconcile_before_resend",
                "evidence_refs": ["evidence:runtime-drill"],
                "validation_result_refs": ["pytest:runtime-drill"],
            },
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["recorded_by"] == "u1"
        assert body["fault_injection_ref"].startswith("fault_injection:")
        assert body["recovery_drill_ref"].startswith("recovery_drill:")
        assert body["drill_mode"] == "simulation"

        rejected = client.post(
            "/api/research-os/methodology/runtime_drills",
            json={
                "claim_ref": "validation:001",
                "target_environment": "live",
                "drill_mode": "live",
                "venue_ref": "venue:live:forbidden",
                "fault_scenario": "venue_timeout",
                "expected_guard_ref": "order_guard:timeout_guard",
                "observed_guard_ref": "order_guard:timeout_guard",
                "recovery_action_ref": "recovery:reconcile_before_resend",
                "evidence_refs": ["evidence:runtime-drill"],
                "validation_result_refs": ["pytest:runtime-drill"],
            },
        )
        assert rejected.status_code == 422
        assert "runtime_drill_unsafe_mode" in rejected.json()["detail"]
        assert len(runtime_drill_store.runtime_drills()) == 1

        summary = client.get("/api/research-os/methodology/summary")
        assert summary.status_code == 200
        summary_body = summary.json()
        assert summary_body["runtime_drill_total"] == 1
        assert summary_body["runtime_drills"][0]["fault_scenario"] == "venue_timeout"
        assert "raw_log" not in str(summary_body)
    finally:
        main.app.dependency_overrides.pop(require_user_dependency, None)


def test_methodology_calculator_api_records_summary_and_rejects_mock(tmp_path, monkeypatch):
    client, _store, calculator_store, _runtime_drill_store = _client_with_depth_store(tmp_path, monkeypatch)
    try:
        cpcv = client.post(
            "/api/research-os/methodology/cpcv",
            json={
                "claim_ref": "claim:strategy",
                "fold_metric_values": [0.11, 0.07, 0.15],
                "embargo_observations": 2,
                "evidence_refs": ["evidence:cpcv"],
                "validation_result_refs": ["pytest:cpcv"],
            },
        )
        assert cpcv.status_code == 200, cpcv.text
        assert cpcv.json()["recorded_by"] == "u1"
        assert cpcv.json()["mean_metric"] == pytest.approx(0.11)

        conformal = client.post(
            "/api/research-os/methodology/conformal",
            json={
                "claim_ref": "claim:strategy",
                "calibration_scores": [0.05, 0.08, 0.03, 0.09, 0.04],
                "alpha": 0.2,
                "abstain_policy_ref": "abstain:drawdown",
                "evidence_refs": ["evidence:conformal"],
                "validation_result_refs": ["pytest:conformal"],
            },
        )
        assert conformal.status_code == 200, conformal.text
        assert conformal.json()["coverage_estimate"] == pytest.approx(0.8)

        tca = client.post(
            "/api/research-os/methodology/tca",
            json={
                "claim_ref": "claim:strategy",
                "gross_return_bps": [10.0, 14.0, 8.0],
                "cost_components_bps": {"spread": 1.5, "fee": 0.5, "slippage": 2.0},
                "cost_model_refs": ["cost:crypto"],
                "evidence_refs": ["evidence:tca"],
                "validation_result_refs": ["pytest:tca"],
            },
        )
        assert tca.status_code == 200, tca.text
        assert tca.json()["net_mean_bps"] == pytest.approx((10.0 + 14.0 + 8.0) / 3 - 4.0)

        rejected = client.post(
            "/api/research-os/methodology/cpcv",
            json={
                "claim_ref": "claim:strategy",
                "fold_metric_values": [0.11, 0.07, 0.15],
                "evidence_refs": ["evidence:cpcv"],
                "validation_result_refs": ["pytest:cpcv"],
                "silent_mock_fallback_used": True,
            },
        )
        assert rejected.status_code == 422
        assert "methodology_calculator_silent_mock_fallback" in rejected.json()["detail"]
        assert len(calculator_store.cpcv_records()) == 1

        summary = client.get("/api/research-os/methodology/summary")
        assert summary.status_code == 200
        body = summary.json()
        assert body["calculator_totals"] == {"cpcv": 1, "conformal": 1, "tca": 1}
        assert body["cpcv_calculations"][0]["source_hash"]
        assert "fold_metric_values" not in str(body)
        assert "calibration_scores" not in str(body)
        assert "gross_return_bps" not in str(body)
    finally:
        main.app.dependency_overrides.pop(require_user_dependency, None)
