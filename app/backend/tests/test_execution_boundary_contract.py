from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from dataclasses import replace
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app import main as app_main
from app.auth import require_user_dependency
from app.research_os import (
    DriftTriggeredAction,
    ExecutionMathClaim,
    ExecutionOrderIntentRecord,
    ExecutionOrderMaterializationRecord,
    ExecutionOrderSubmissionRecord,
    ExecutionSubmitRequestRecord,
    ExecutionVenueCapabilityRecord,
    ExecutionVenueConnectivityCheckRecord,
    ExecutionVenueEventRecord,
    ExecutionVenueSafetyAttestationRecord,
    HaltRecoveryPlan,
    PersistentExecutionOrderSubmissionRegistry,
    PersistentExecutionOrderMaterializationRegistry,
    PersistentExecutionSubmitRequestRegistry,
    PersistentExecutionVenueCapabilityRegistry,
    PersistentExecutionVenueConnectivityCheckRegistry,
    PersistentExecutionReconciliationActionRegistry,
    PersistentExecutionReconciliationRegistry,
    PersistentExecutionOrderIntentRegistry,
    PersistentExecutionVenueEventRegistry,
    PersistentExecutionVenueSafetyAttestationRegistry,
    PersistentCompilerIRStore,
    PersistentEntrypointEvidenceRegistry,
    PersistentGoalEntrypointCoverageRegistry,
    PersistentGoalValidationReceiptRegistry,
    PersistentResearchGraphStore,
    PersistentRuntimePromotionRegistry,
    PersistentUserRiskChoiceRegistry,
    PersistentSignalValidationRegistry,
    ResearchGraphStore,
    RuntimePromotionRecord,
    RuntimePromotionRequest,
    RuntimeStatus,
    SignalPerformanceValidationRecord,
    SignalValidationVerdict,
    UserRiskChoiceRecord,
    execution_client_order_ref_hash,
    reconcile_execution_venue_events,
    validate_execution_order_materialization,
    validate_execution_order_intent,
    validate_execution_order_submission,
    validate_execution_reconciliation,
    validate_execution_submit_request,
    validate_execution_venue_capability,
    validate_execution_venue_connectivity_check,
    validate_execution_venue_safety_attestation,
    validate_execution_venue_event,
    validate_drift_triggered_action,
    validate_execution_boundary,
    validate_execution_math_claim,
    validate_halt_recovery,
    validate_runtime_promotion,
    validate_runtime_promotion_record,
    validate_user_risk_choice,
)
from app.research_os.goal_proof_ledger import GoalProofLedger
from app.research_os.ref_resolution import build_real_ref_resolver


def _codes(decision) -> set[str]:
    return {violation.code for violation in decision.violations}


def _patch_compiler_coverage(tmp_path, monkeypatch, *, graph=None):
    graph = graph if graph is not None else app_main.RESEARCH_GRAPH_STORE
    proof_ledger = GoalProofLedger(tmp_path / "goal_proof_ledger")
    compiler_store = PersistentCompilerIRStore(
        tmp_path / "compiler_ir.jsonl",
        proof_ledger=proof_ledger,
        legacy_read_only=True,
    )
    validations = PersistentGoalValidationReceiptRegistry(
        tmp_path / "goal_validation_receipts.jsonl",
        proof_ledger=proof_ledger,
        legacy_read_only=True,
    )
    evidence = PersistentEntrypointEvidenceRegistry(
        tmp_path / "entrypoint_evidence.jsonl",
        research_graph_store=graph,
        compiler_store=compiler_store,
        validation_receipt_registry=validations,
        proof_ledger=proof_ledger,
        legacy_read_only=True,
    )
    coverage_store = PersistentGoalEntrypointCoverageRegistry(
        tmp_path / "goal_entrypoint_coverage.jsonl",
        proof_ledger=proof_ledger,
        legacy_read_only=True,
    )
    coverage_store.set_ref_resolver(
        build_real_ref_resolver(
            research_graph_store=graph,
            lifecycle_registry=None,
            governance_registry=None,
            rag_index=None,
            spine_chain_registry=None,
            compiler_store=compiler_store,
            goal_validation_receipt_registry=validations,
            platform_source_evidence_registry=evidence,
        )
    )
    monkeypatch.setattr(app_main, "RESEARCH_GRAPH_STORE", graph)
    monkeypatch.setattr(app_main, "COMPILER_IR_STORE", compiler_store)
    monkeypatch.setattr(app_main, "GOAL_VALIDATION_RECEIPT_REGISTRY", validations)
    monkeypatch.setattr(app_main, "ENTRYPOINT_EVIDENCE_REGISTRY", evidence)
    monkeypatch.setattr(app_main, "GOAL_ENTRYPOINT_COVERAGE_REGISTRY", coverage_store)
    return compiler_store, coverage_store


def _assert_compiler_coverage(body: dict, *, entrypoint_ref: str) -> None:
    assert body["compiler_ir_ref"].startswith("compiler_ir:")
    assert body["compiler_pass_ref"].startswith("compiler_pass:")
    assert body["entrypoint_coverage_ref"].startswith("goal_entrypoint_coverage:")
    ir = app_main.COMPILER_IR_STORE.ir(body["compiler_ir_ref"])
    compiler_pass = app_main.COMPILER_IR_STORE.compiler_pass(body["compiler_pass_ref"])
    coverage = app_main.GOAL_ENTRYPOINT_COVERAGE_REGISTRY.coverage(body["entrypoint_coverage_ref"])
    assert ir.source_qro_refs == (body["qro_id"],)
    assert ir.graph_command_refs == (body["research_graph_command_id"],)
    assert compiler_pass.input_qro_refs == (body["qro_id"],)
    assert compiler_pass.entry_source == "api"
    assert coverage.entry_source == "api"
    assert coverage.entrypoint_ref == entrypoint_ref
    assert coverage.compiler_ir_refs == (body["compiler_ir_ref"],)
    assert coverage.compiler_pass_refs == (body["compiler_pass_ref"],)
    assert compiler_pass.direct_graph_mutation is False
    assert compiler_pass.bypassed_permission is False
    assert compiler_pass.raw_llm_output_embedded_as_ir is False
    assert coverage.silent_mock_fallback_used is False
    assert coverage.raw_payload_persisted is False
    compiled_text = (
        str(ir)
        + str(compiler_pass)
        + str(coverage.evidence_refs)
        + str(coverage.validation_refs)
        + str(coverage.canonical_command_refs)
    )
    assert "raw_order" not in compiled_text
    assert "raw_event" not in compiled_text


class _AcceptedMarketDataUseRegistry:
    def __init__(self, accepted_ref: str = "market_data_use:accepted") -> None:
        self.accepted_ref = accepted_ref

    def use_validation(self, validation_ref: str, *, owner_user_id: str):
        if validation_ref != self.accepted_ref:
            raise KeyError(f"unknown market data use validation: {validation_ref}")
        return SimpleNamespace(
            validation_ref=validation_ref,
            accepted=True,
            recorded_by=owner_user_id,
        )


def _live_request(**overrides) -> RuntimePromotionRequest:
    data = {
        "request_ref": "promote:crypto:small_live",
        "asset_class": "crypto_perp",
        "source_runtime": RuntimeStatus.PAPER,
        "target_runtime": RuntimeStatus.LIVE,
        "paper_run_ref": "paper_run:001",
        "testnet_run_ref": None,
        "approval_ref": "approval:001",
        "permission_gate_ref": "permission:live:001",
        "order_guard_ref": "order_guard:policy:001",
        "idempotency_key": "idem:001",
        "audit_record_ref": "audit:001",
        "kill_switch_ref": "kill_switch:001",
        "secret_ref": "secretref:binance:trade",
        "responsibility_boundary_ref": "responsibility:live:001",
    }
    data.update(overrides)
    return RuntimePromotionRequest(**data)


def _runtime_promotion(**overrides) -> RuntimePromotionRecord:
    data = {
        "request_ref": "promote:crypto:live:001",
        "asset_class": "crypto_perp",
        "source_runtime": RuntimeStatus.PAPER,
        "target_runtime": RuntimeStatus.LIVE,
        "paper_run_ref": "paper_run:001",
        "testnet_run_ref": None,
        "approval_ref": "approval:001",
        "permission_gate_ref": "permission:live:001",
        "order_guard_ref": "order_guard:policy:001",
        "idempotency_key": "idem:runtime:001",
        "audit_record_ref": "audit:runtime:001",
        "kill_switch_ref": "kill_switch:001",
        "secret_ref": "secretref:binance:trade",
        "responsibility_boundary_ref": "responsibility:live:001",
        "waiver_requests": (),
        "mock_profile": "none",
        "evidence_refs": ("evidence:paper_passed",),
        "recorded_by": "tester",
    }
    data.update(overrides)
    return RuntimePromotionRecord(**data)


def _risk_choice(**overrides) -> UserRiskChoiceRecord:
    data = {
        "choice_ref": "",
        "selected_risk_path": "small_live",
        "cost_disclosure_ref": "cost:001",
        "leverage_disclosure_ref": "leverage:001",
        "margin_disclosure_ref": "margin:001",
        "borrow_disclosure_ref": "borrow:001",
        "funding_disclosure_ref": "funding:001",
        "slippage_disclosure_ref": "slippage:001",
        "impact_disclosure_ref": "impact:001",
        "liquidation_disclosure_ref": "liquidation:001",
        "regulation_disclosure_ref": "regulation:001",
        "failure_mode_refs": ("failure:venue_down", "failure:gap_risk"),
        "recommendation_ref": "recommendation:paper_first",
        "responsibility_boundary_ref": "responsibility:live:001",
        "owner_user_id": "risk-owner",
        "master_id": "risk-master",
        "follower_id": "risk-owner::risk-master",
        "account_binding_ref": "exchange_account_uid_risk",
        "subject_ref": "copy_trade_subject:risk",
        "runtime_request_ref": "copy_trade_runtime_request:risk",
        "asset_class": "crypto_perp",
        "risk_disclosure_profile_ref": "copy_trade_risk_profile:risk",
        "actor_source": "user_manual",
    }
    data.update(overrides)
    return UserRiskChoiceRecord(**data)


def _order_intent(**overrides) -> ExecutionOrderIntentRecord:
    data = {
        "source_portfolio_ref": "portfolio:p_signal",
        "strategy_book_ref": None,
        "signal_ref": "sig::validated",
        "signal_validation_ref": "signal_validation:accepted",
        "market_data_use_validation_ref": "market_data_use:accepted",
        "execution_policy_ref": "execution_policy:testnet_guarded",
        "risk_policy_ref": "risk_policy:small_order",
        "runtime": RuntimeStatus.TESTNET,
        "asset_class": "crypto_perp",
        "instrument_ref": "instrument:BTCUSDT_PERP",
        "side": "buy",
        "order_type": "limit",
        "venue_ref": "venue:binance_testnet",
        "quantity_ref": "sizing:qty_ref",
        "notional_ref": None,
        "price_ref": "price_ref:limit_anchor",
        "time_in_force_ref": "tif:gtc",
        "permission_gate_ref": "permission:testnet",
        "order_guard_ref": "order_guard:policy:001",
        "idempotency_key": "idem:order:001",
        "audit_record_ref": "audit:order_intent:001",
        "kill_switch_ref": "kill_switch:001",
        "secret_ref": "secretref:binance:testnet",
        "responsibility_boundary_ref": "responsibility:testnet_order",
        "failure_mode_refs": ("failure:venue_down",),
        "recorded_by": "tester",
    }
    data.update(overrides)
    return ExecutionOrderIntentRecord(**data)


def _venue_event(**overrides) -> ExecutionVenueEventRecord:
    data = {
        "order_intent_ref": "order_intent:recorded",
        "runtime_promotion_ref": "runtime_promotion:recorded",
        "venue_ref": "venue:binance_testnet",
        "event_kind": "filled",
        "status": "filled",
        "venue_order_ref": "venue_order:abc",
        "client_order_ref": "client_order:idempotent",
        "ack_ref": "ack:abc",
        "fill_ref": "fill:abc:001",
        "reconcile_ref": "reconcile:abc:001",
        "quantity_ref": "qty_ref:fill",
        "price_ref": "price_ref:fill",
        "fee_ref": "fee_ref:commission",
        "raw_event_hash": "sha256:venue_raw_payload",
        "audit_record_ref": "audit:venue_event:001",
        "order_guard_ref": "order_guard:policy:001",
        "idempotency_key": "idem:order:001",
        "evidence_refs": ("evidence:venue_event",),
        "recorded_by": "tester",
    }
    data.update(overrides)
    return ExecutionVenueEventRecord(**data)


def _materialization(**overrides) -> ExecutionOrderMaterializationRecord:
    data = {
        "order_intent_ref": "order_intent:recorded",
        "runtime_promotion_ref": "runtime_promotion:recorded",
        "materializer_ref": "order_materializer:test",
        "materialization_mode": "testnet",
        "materialization_status": "recorded",
        "permission_gate_ref": "permission:testnet",
        "order_guard_ref": "order_guard:policy:001",
        "idempotency_key": "idem:order:001",
        "audit_record_ref": "audit:materialization:001",
        "order_schema_ref": None,
        "order_payload_hash": None,
        "quantity_resolution_ref": None,
        "notional_resolution_ref": None,
        "price_resolution_ref": None,
        "time_in_force_resolution_ref": None,
        "market_snapshot_ref": None,
        "risk_check_ref": None,
        "kill_switch_ref": "kill_switch:001",
        "secret_ref": "secretref:binance:testnet",
        "responsibility_boundary_ref": "responsibility:testnet_order",
        "materialize_enabled": False,
        "evidence_refs": ("evidence:materialization_ready",),
        "recorded_by": "tester",
    }
    data.update(overrides)
    return ExecutionOrderMaterializationRecord(**data)


def _venue_connectivity_check(**overrides) -> ExecutionVenueConnectivityCheckRecord:
    data = {
        "order_intent_ref": "order_intent:recorded",
        "runtime_promotion_ref": "runtime_promotion:recorded",
        "venue_ref": "venue:binance_testnet",
        "guarded_venue_ref": "guarded_venue:binance_testnet",
        "runtime": "testnet",
        "asset_class": "crypto_perp",
        "instrument_ref": "instrument:BTCUSDT_PERP",
        "connectivity_status": "accepted",
        "checker_ref": "venue_connectivity_checker:binance_testnet:refs_only",
        "permission_gate_ref": "permission:testnet",
        "order_guard_ref": "order_guard:policy:001",
        "idempotency_key": "idem:order:001",
        "audit_record_ref": "audit:venue_connectivity_check:001",
        "credential_check_ref": "credential_check:binance_testnet:ok",
        "ip_allowlist_ref": "ip_allowlist:binance_testnet:ok",
        "withdrawal_disabled_ref": "withdrawal_disabled:binance_testnet:ok",
        "hmac_replay_protection_ref": "hmac_replay:binance_testnet:ok",
        "health_check_ref": "health_check:binance_testnet:ok",
        "rate_limit_ref": "rate_limit:binance_testnet:ok",
        "sandbox_proof_ref": "sandbox:binance_testnet:ok",
        "connectivity_check_hash": "sha256:venue_connectivity_refs",
        "kill_switch_ref": "kill_switch:001",
        "secret_ref": "secretref:binance:testnet",
        "responsibility_boundary_ref": "responsibility:testnet_order",
        "evidence_refs": ("evidence:venue_connectivity_check_accepted",),
        "recorded_by": "tester",
    }
    data.update(overrides)
    return ExecutionVenueConnectivityCheckRecord(**data)


def _venue_safety_attestation(**overrides) -> ExecutionVenueSafetyAttestationRecord:
    data = {
        "order_intent_ref": "order_intent:recorded",
        "runtime_promotion_ref": "runtime_promotion:recorded",
        "venue_ref": "venue:binance_testnet",
        "guarded_venue_ref": "guarded_venue:binance_testnet",
        "runtime": "testnet",
        "asset_class": "crypto_perp",
        "instrument_ref": "instrument:BTCUSDT_PERP",
        "attestation_status": "recorded",
        "permission_gate_ref": "permission:testnet",
        "order_guard_ref": "order_guard:policy:001",
        "idempotency_key": "idem:order:001",
        "audit_record_ref": "audit:venue_safety_attestation:001",
        "credential_check_ref": "credential_check:binance_testnet:ok",
        "ip_allowlist_ref": "ip_allowlist:binance_testnet:ok",
        "withdrawal_disabled_ref": "withdrawal_disabled:binance_testnet:ok",
        "hmac_replay_protection_ref": "hmac_replay:binance_testnet:ok",
        "health_check_ref": "health_check:binance_testnet:ok",
        "rate_limit_ref": "rate_limit:binance_testnet:ok",
        "sandbox_proof_ref": "sandbox:binance_testnet:ok",
        "kill_switch_ref": "kill_switch:001",
        "secret_ref": "secretref:binance:testnet",
        "responsibility_boundary_ref": "responsibility:testnet_order",
        "evidence_refs": ("evidence:venue_safety_attestation_recorded",),
        "recorded_by": "tester",
    }
    data.update(overrides)
    return ExecutionVenueSafetyAttestationRecord(**data)


def _accepted_venue_safety_attestation(**overrides) -> ExecutionVenueSafetyAttestationRecord:
    data = {
        "attestation_status": "accepted",
        "venue_connectivity_check_ref": _venue_connectivity_check().venue_connectivity_check_ref,
        "evidence_refs": ("evidence:venue_safety_attestation_accepted",),
    }
    data.update(overrides)
    return _venue_safety_attestation(**data)


def _venue_capability(**overrides) -> ExecutionVenueCapabilityRecord:
    data = {
        "order_intent_ref": "order_intent:recorded",
        "runtime_promotion_ref": "runtime_promotion:recorded",
        "venue_ref": "venue:binance_testnet",
        "guarded_venue_ref": "guarded_venue:binance_testnet",
        "submitter_ref": "guarded_submitter:test",
        "runtime": "testnet",
        "asset_class": "crypto_perp",
        "instrument_ref": "instrument:BTCUSDT_PERP",
        "capability_status": "recorded",
        "permission_gate_ref": "permission:testnet",
        "order_guard_ref": "order_guard:policy:001",
        "idempotency_key": "idem:order:001",
        "audit_record_ref": "audit:venue_capability:001",
        "venue_safety_attestation_ref": None,
        "credential_check_ref": None,
        "ip_allowlist_ref": None,
        "withdrawal_disabled_ref": None,
        "hmac_replay_protection_ref": None,
        "health_check_ref": None,
        "rate_limit_ref": None,
        "sandbox_proof_ref": None,
        "kill_switch_ref": "kill_switch:001",
        "secret_ref": "secretref:binance:testnet",
        "responsibility_boundary_ref": "responsibility:testnet_order",
        "can_submit_orders": False,
        "evidence_refs": ("evidence:venue_capability_recorded",),
        "recorded_by": "tester",
    }
    data.update(overrides)
    return ExecutionVenueCapabilityRecord(**data)


def _ready_venue_capability(**overrides) -> ExecutionVenueCapabilityRecord:
    attestation = _accepted_venue_safety_attestation()
    data = {
        "venue_safety_attestation_ref": attestation.venue_safety_attestation_ref,
        "capability_status": "ready",
        "can_submit_orders": True,
        "credential_check_ref": "credential_check:binance_testnet:ok",
        "ip_allowlist_ref": "ip_allowlist:binance_testnet:ok",
        "withdrawal_disabled_ref": "withdrawal_disabled:binance_testnet:ok",
        "hmac_replay_protection_ref": "hmac_replay:binance_testnet:ok",
        "health_check_ref": "health_check:binance_testnet:ok",
        "rate_limit_ref": "rate_limit:binance_testnet:ok",
        "sandbox_proof_ref": "sandbox:binance_testnet:ok",
        "evidence_refs": ("evidence:venue_capability_ready",),
    }
    data.update(overrides)
    return _venue_capability(**data)


def _submit_request(**overrides) -> ExecutionSubmitRequestRecord:
    data = {
        "order_intent_ref": "order_intent:recorded",
        "runtime_promotion_ref": "runtime_promotion:recorded",
        "order_materialization_ref": "order_materialization:recorded",
        "venue_capability_ref": "venue_capability:recorded",
        "submitter_ref": "guarded_submitter:test",
        "guarded_venue_ref": "guarded_venue:binance_testnet",
        "venue_ref": "venue:binance_testnet",
        "submit_request_mode": "testnet",
        "submit_request_status": "ready",
        "permission_gate_ref": "permission:testnet",
        "order_guard_ref": "order_guard:policy:001",
        "idempotency_key": "idem:order:001",
        "audit_record_ref": "audit:submit_request:001",
        "order_schema_ref": "schema:execution_order:v1",
        "order_payload_hash": "sha256:order_payload_hash",
        "submit_request_schema_ref": "schema:submit_request:v1",
        "submit_request_hash": "sha256:submit_request_hash",
        "client_order_ref_hash": execution_client_order_ref_hash("client_order:idempotent"),
        "kill_switch_ref": "kill_switch:001",
        "secret_ref": "secretref:binance:testnet",
        "responsibility_boundary_ref": "responsibility:testnet_order",
        "evidence_refs": ("evidence:submit_request_ready",),
        "recorded_by": "tester",
    }
    data.update(overrides)
    return ExecutionSubmitRequestRecord(**data)


def _submission(**overrides) -> ExecutionOrderSubmissionRecord:
    data = {
        "order_intent_ref": "order_intent:recorded",
        "runtime_promotion_ref": "runtime_promotion:recorded",
        "submitter_ref": "guarded_submitter:test",
        "guarded_venue_ref": "guarded_venue:binance_testnet",
        "venue_ref": "venue:binance_testnet",
        "submission_mode": "testnet",
        "permission_gate_ref": "permission:testnet",
        "order_guard_ref": "order_guard:policy:001",
        "idempotency_key": "idem:order:001",
        "audit_record_ref": "audit:submission:001",
        "kill_switch_ref": "kill_switch:001",
        "secret_ref": "secretref:binance:testnet",
        "responsibility_boundary_ref": "responsibility:testnet_order",
        "submit_enabled": False,
        "venue_capability_ref": None,
        "submit_request_ref": None,
        "submission_status": "recorded",
        "client_order_ref_hash": execution_client_order_ref_hash("client_order:idempotent"),
        "evidence_refs": ("evidence:submission_ready",),
        "recorded_by": "tester",
    }
    data.update(overrides)
    return ExecutionOrderSubmissionRecord(**data)


def _signal_validation(verdict=SignalValidationVerdict.ACCEPTED) -> SignalPerformanceValidationRecord:
    return SignalPerformanceValidationRecord(
        signal_ref="sig::validated",
        validation_dataset_ref="dataset_version:btc:oos",
        evaluation_window_ref="window:2025q4",
        methodology_ref="methodology:cpcv_walkforward",
        metric_refs=("metric:rank_ic",),
        performance_summary_ref="signal_perf:validated:oos",
        leakage_check_ref="leakage:oof_purge_embargo",
        evidence_refs=("evidence:signal_validation",),
        verdict=verdict,
        recorded_by="tester",
    )


def test_direct_live_without_paper_or_testnet_evidence_is_rejected():
    decision = validate_runtime_promotion(
        _live_request(source_runtime="backtest", paper_run_ref=None, testnet_run_ref=None)
    )
    assert not decision.accepted
    assert "live_ladder_jump" in _codes(decision)


def test_a_share_live_remains_unreachable_even_with_other_refs_present():
    decision = validate_runtime_promotion(
        _live_request(request_ref="promote:cn:live", asset_class="equity_cn")
    )
    assert not decision.accepted
    assert "a_share_live_forbidden" in _codes(decision)


def test_feature_drift_alone_cannot_trigger_trading_action():
    decision = validate_drift_triggered_action(
        DriftTriggeredAction(
            action_ref="action:scale_down",
            action_kind="scale_down",
            feature_drift_ref="feature_drift:psi",
            performance_evidence_ref=None,
            risk_evidence_ref=None,
        )
    )
    assert not decision.accepted
    assert "feature_drift_alone_triggered_trade_action" in _codes(decision)


def test_kill_switch_order_guard_secret_and_audit_cannot_be_waived_or_missing():
    decision = validate_runtime_promotion(
        _live_request(
            order_guard_ref=None,
            kill_switch_ref=None,
            secret_ref=None,
            audit_record_ref=None,
            waiver_requests=("orderguard", "kill_switch", "secret_ref"),
        )
    )
    assert not decision.accepted
    assert _codes(decision) >= {
        "missing_live_execution_invariant",
        "waiver_attempted_execution_invariant",
    }


def test_halt_recovery_cannot_auto_resend_and_requires_reconcile():
    decision = validate_halt_recovery(
        HaltRecoveryPlan(
            plan_ref="halt_plan:001",
            halt_event_ref="halt:001",
            reconcile_ref=None,
            auto_resend_order=True,
        )
    )
    assert not decision.accepted
    assert _codes(decision) >= {"halt_auto_resend_order", "halt_missing_reconcile"}


def test_execution_math_claim_requires_consistency_check():
    decision = validate_execution_math_claim(
        ExecutionMathClaim(
            claim_ref="claim:cost_model",
            claim_kind="cost_model",
            claims_math_basis=True,
            consistency_check_ref=None,
        )
    )
    assert not decision.accepted
    assert "execution_math_missing_consistency_check" in _codes(decision)


def test_execution_order_intent_requires_typed_refs_and_execution_invariants():
    decision = validate_execution_order_intent(
        _order_intent(
            runtime=RuntimeStatus.LIVE,
            asset_class="equity_cn",
            quantity_ref=None,
            notional_ref=None,
            order_guard_ref=None,
            secret_ref=None,
        ),
        known_signal_validation_refs={"signal_validation:accepted"},
    )
    assert not decision.accepted
    assert _codes(decision) >= {
        "a_share_live_order_intent_forbidden",
        "order_intent_missing_sizing_ref",
        "order_intent_missing_execution_invariant",
    }


def test_execution_order_intent_requires_market_data_use_validation_for_execution_runtimes():
    decision = validate_execution_order_intent(
        _order_intent(market_data_use_validation_ref=None),
        known_signal_validation_refs={"signal_validation:accepted"},
    )

    assert not decision.accepted
    assert "order_intent_missing_market_data_use_validation_ref" in _codes(decision)

    unknown = validate_execution_order_intent(
        _order_intent(market_data_use_validation_ref="market_data_use:missing"),
        known_signal_validation_refs={"signal_validation:accepted"},
        known_market_data_use_validation_refs={"market_data_use:accepted"},
    )

    assert not unknown.accepted
    assert "order_intent_unknown_market_data_use_validation_ref" in _codes(unknown)


def test_execution_order_intent_registry_persists_and_replays(tmp_path):
    path = tmp_path / "execution_order_intents.jsonl"
    registry = PersistentExecutionOrderIntentRegistry(path)
    record = registry.record_intent(
        _order_intent(),
        known_signal_validation_refs={"signal_validation:accepted"},
    )

    reloaded = PersistentExecutionOrderIntentRegistry(path)

    assert reloaded.intent(record.order_intent_ref).instrument_ref == "instrument:BTCUSDT_PERP"
    assert reloaded.intents()[0].order_intent_ref == record.order_intent_ref


def test_execution_order_intent_identity_is_owner_scoped(tmp_path):
    registry = PersistentExecutionOrderIntentRegistry(tmp_path / "execution_order_intents.jsonl")
    alice = _order_intent(recorded_by="alice", order_intent_ref="")
    bob = _order_intent(recorded_by="bob", order_intent_ref="")

    assert alice.order_intent_ref != bob.order_intent_ref
    recorded_alice = registry.record_intent(
        alice,
        known_signal_validation_refs={"signal_validation:accepted"},
    )
    recorded_bob = registry.record_intent(
        bob,
        known_signal_validation_refs={"signal_validation:accepted"},
    )

    assert {record.recorded_by for record in registry.intents()} == {"alice", "bob"}
    assert recorded_alice.order_intent_ref != recorded_bob.order_intent_ref


def test_execution_order_intent_api_ignores_foreign_caller_supplied_identity(
    tmp_path,
    monkeypatch,
):
    signal_validations = PersistentSignalValidationRegistry(tmp_path / "signal_validations.jsonl")
    validation = signal_validations.record_validation(
        replace(_signal_validation(), recorded_by="alice", validation_id=""),
        owner_user_id="alice",
        known_signal_refs={"sig::validated"},
    )
    order_intents = PersistentExecutionOrderIntentRegistry(tmp_path / "execution_order_intents.jsonl")
    monkeypatch.setattr(app_main, "SIGNAL_VALIDATIONS", signal_validations)
    monkeypatch.setattr(app_main, "EXECUTION_ORDER_INTENTS", order_intents)
    monkeypatch.setattr(app_main, "MARKET_DATA_REGISTRY", _AcceptedMarketDataUseRegistry())
    monkeypatch.setattr(app_main, "RESEARCH_GRAPH_STORE", ResearchGraphStore())
    _patch_compiler_coverage(tmp_path, monkeypatch)
    current_owner = {"value": "alice"}
    app_main.app.dependency_overrides[require_user_dependency] = lambda: SimpleNamespace(
        user_id=current_owner["value"],
        username=current_owner["value"],
    )
    try:
        client = TestClient(app_main.app)
        payload = _order_intent(signal_validation_ref=validation.validation_id).to_dict()
        alice = client.post("/api/research-os/execution/order_intents", json=payload)
        assert alice.status_code == 200, alice.text

        current_owner["value"] = "bob"
        forged = {**payload, "order_intent_ref": alice.json()["order_intent_ref"]}
        bob = client.post("/api/research-os/execution/order_intents", json=forged)

        assert bob.status_code == 422, bob.text
        assert "unknown signal validation" in bob.text
        assert {record.recorded_by for record in order_intents.intents()} == {"alice"}
    finally:
        app_main.app.dependency_overrides.pop(require_user_dependency, None)


def test_execution_order_intent_api_records_without_placing_order(tmp_path, monkeypatch):
    signal_validations = PersistentSignalValidationRegistry(tmp_path / "signal_validations.jsonl")
    validation = signal_validations.record_validation(
        _signal_validation(),
        owner_user_id="tester",
        known_signal_refs={"sig::validated"},
    )
    order_intents = PersistentExecutionOrderIntentRegistry(tmp_path / "execution_order_intents.jsonl")
    monkeypatch.setattr(app_main, "SIGNAL_VALIDATIONS", signal_validations)
    monkeypatch.setattr(app_main, "EXECUTION_ORDER_INTENTS", order_intents)
    monkeypatch.setattr(app_main, "MARKET_DATA_REGISTRY", _AcceptedMarketDataUseRegistry())
    graph = ResearchGraphStore()
    monkeypatch.setattr(app_main, "RESEARCH_GRAPH_STORE", graph)
    _patch_compiler_coverage(tmp_path, monkeypatch)
    app_main.app.dependency_overrides[require_user_dependency] = lambda: SimpleNamespace(
        user_id="tester",
        username="tester",
    )
    try:
        client = TestClient(app_main.app)
        payload = _order_intent(signal_validation_ref=validation.validation_id).to_dict()
        response = client.post("/api/research-os/execution/order_intents", json=payload)
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["place_order_called"] is False
        assert body["order_intent_ref"].startswith("order_intent_")
        assert body["qro_id"].startswith("qro_")
        assert body["research_graph_command_id"].startswith("rgcmd_")
        _assert_compiler_coverage(body, entrypoint_ref="api:research_os.execution.order_intents")
        qro = graph.qro(body["qro_id"])
        assert qro.qro_type.value == "ExecutionPolicy"
        assert qro.output_contract["place_order_called"] is False
        assert qro.input_contract["market_data_use_validation_ref"] == "market_data_use:accepted"
        assert qro.output_contract["market_data_use_validation_ref"] == "market_data_use:accepted"
        assert qro.output_contract["execution_boundary_ref"] == qro.output_contract["execution_policy_ref"]
        assert "quantity" not in qro.output_contract
        assert "raw_order" not in qro.output_contract

        summary = client.get("/api/research-os/execution/order_intents/summary")
        assert summary.status_code == 200
        assert summary.json()["order_intent_total"] == 1
        row = summary.json()["order_intents"][0]
        assert row["signal_validation_ref"] == validation.validation_id
        assert row["market_data_use_validation_ref"] == "market_data_use:accepted"
        assert "quantity" not in row
        assert "raw_order" not in row
    finally:
        app_main.app.dependency_overrides.pop(require_user_dependency, None)


def test_execution_order_intent_api_rejects_raw_quantity_without_write(tmp_path, monkeypatch):
    signal_validations = PersistentSignalValidationRegistry(tmp_path / "signal_validations.jsonl")
    validation = signal_validations.record_validation(
        _signal_validation(),
        owner_user_id="tester",
        known_signal_refs={"sig::validated"},
    )
    order_intent_path = tmp_path / "execution_order_intents.jsonl"
    monkeypatch.setattr(app_main, "SIGNAL_VALIDATIONS", signal_validations)
    monkeypatch.setattr(app_main, "EXECUTION_ORDER_INTENTS", PersistentExecutionOrderIntentRegistry(order_intent_path))
    app_main.app.dependency_overrides[require_user_dependency] = lambda: SimpleNamespace(
        user_id="tester",
        username="tester",
    )
    try:
        client = TestClient(app_main.app)
        payload = _order_intent(signal_validation_ref=validation.validation_id).to_dict()
        payload["quantity"] = 0.25
        response = client.post("/api/research-os/execution/order_intents", json=payload)
        assert response.status_code == 422
        assert "raw order" in response.text
        assert not order_intent_path.exists()
    finally:
        app_main.app.dependency_overrides.pop(require_user_dependency, None)


def test_execution_order_intent_api_rejects_unknown_market_data_use_ref_without_write(tmp_path, monkeypatch):
    signal_validations = PersistentSignalValidationRegistry(tmp_path / "signal_validations.jsonl")
    validation = signal_validations.record_validation(
        _signal_validation(),
        owner_user_id="tester",
        known_signal_refs={"sig::validated"},
    )
    order_intent_path = tmp_path / "execution_order_intents.jsonl"
    graph = ResearchGraphStore()
    monkeypatch.setattr(app_main, "SIGNAL_VALIDATIONS", signal_validations)
    monkeypatch.setattr(app_main, "EXECUTION_ORDER_INTENTS", PersistentExecutionOrderIntentRegistry(order_intent_path))
    monkeypatch.setattr(app_main, "MARKET_DATA_REGISTRY", _AcceptedMarketDataUseRegistry())
    monkeypatch.setattr(app_main, "RESEARCH_GRAPH_STORE", graph)
    app_main.app.dependency_overrides[require_user_dependency] = lambda: SimpleNamespace(
        user_id="tester",
        username="tester",
    )
    try:
        client = TestClient(app_main.app)
        payload = _order_intent(
            signal_validation_ref=validation.validation_id,
            market_data_use_validation_ref="market_data_use:missing",
        ).to_dict()
        response = client.post("/api/research-os/execution/order_intents", json=payload)
        assert response.status_code == 422
        assert "unknown market data use validation" in response.text
        assert not order_intent_path.exists()
        assert graph.commands() == []
    finally:
        app_main.app.dependency_overrides.pop(require_user_dependency, None)


def test_runtime_promotion_registry_persists_and_replays(tmp_path):
    path = tmp_path / "runtime_promotions.jsonl"
    registry = PersistentRuntimePromotionRegistry(path)
    record = registry.record_promotion(_runtime_promotion())

    reloaded = PersistentRuntimePromotionRegistry(path)

    assert reloaded.promotion(record.runtime_promotion_ref).request_ref == "promote:crypto:live:001"
    assert reloaded.promotions()[0].runtime_promotion_ref == record.runtime_promotion_ref


def test_runtime_promotion_api_records_qro_without_venue_or_order(tmp_path, monkeypatch):
    promotion_path = tmp_path / "runtime_promotions.jsonl"
    runtime_promotions = PersistentRuntimePromotionRegistry(promotion_path)
    graph = ResearchGraphStore()
    monkeypatch.setattr(app_main, "RUNTIME_PROMOTIONS", runtime_promotions)
    monkeypatch.setattr(app_main, "RESEARCH_GRAPH_STORE", graph)
    _patch_compiler_coverage(tmp_path, monkeypatch)
    app_main.app.dependency_overrides[require_user_dependency] = lambda: SimpleNamespace(
        user_id="tester",
        username="tester",
    )
    try:
        client = TestClient(app_main.app)
        response = client.post("/api/research-os/execution/runtime_promotions", json=_runtime_promotion().to_dict())
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["runtime_promotion_ref"].startswith("runtime_promotion_")
        assert body["qro_id"].startswith("qro_")
        assert body["research_graph_command_id"].startswith("rgcmd_")
        _assert_compiler_coverage(body, entrypoint_ref="api:research_os.execution.runtime_promotions")
        assert body["place_order_called"] is False
        assert body["venue_call_called"] is False
        qro = graph.qro(body["qro_id"])
        assert qro.qro_type.value == "ExecutionPolicy"
        assert qro.output_contract["runtime_transition_recorded"] is True
        assert qro.output_contract["place_order_called"] is False
        assert qro.output_contract["venue_call_called"] is False
        assert "api_key" not in qro.output_contract
        assert "raw_order" not in qro.output_contract

        summary = client.get("/api/research-os/execution/runtime_promotions/summary")
        assert summary.status_code == 200
        row = summary.json()["runtime_promotions"][0]
        assert row["request_ref"] == "promote:crypto:live:001"
        assert "api_key" not in row
        assert "raw_order" not in row
    finally:
        app_main.app.dependency_overrides.pop(require_user_dependency, None)


def test_runtime_promotion_api_rejects_ladder_jump_without_write(tmp_path, monkeypatch):
    promotion_path = tmp_path / "runtime_promotions.jsonl"
    graph = ResearchGraphStore()
    monkeypatch.setattr(app_main, "RUNTIME_PROMOTIONS", PersistentRuntimePromotionRegistry(promotion_path))
    monkeypatch.setattr(app_main, "RESEARCH_GRAPH_STORE", graph)
    app_main.app.dependency_overrides[require_user_dependency] = lambda: SimpleNamespace(
        user_id="tester",
        username="tester",
    )
    try:
        client = TestClient(app_main.app)
        payload = _runtime_promotion(source_runtime="backtest", paper_run_ref=None, testnet_run_ref=None).to_dict()
        response = client.post("/api/research-os/execution/runtime_promotions", json=payload)
        assert response.status_code == 422
        assert "live_ladder_jump" in response.text
        assert not promotion_path.exists()
        assert graph.commands() == []
    finally:
        app_main.app.dependency_overrides.pop(require_user_dependency, None)


def _runtime_promotion_for_submission(**overrides) -> RuntimePromotionRecord:
    data = {
        "request_ref": "promote:crypto:testnet:001",
        "asset_class": "crypto_perp",
        "source_runtime": RuntimeStatus.PAPER,
        "target_runtime": RuntimeStatus.TESTNET,
        "paper_run_ref": "paper_run:001",
        "testnet_run_ref": "testnet_run:001",
        "approval_ref": "approval:testnet:001",
        "permission_gate_ref": "permission:testnet",
        "order_guard_ref": "order_guard:policy:001",
        "idempotency_key": "idem:runtime:testnet",
        "audit_record_ref": "audit:runtime:testnet",
        "kill_switch_ref": "kill_switch:001",
        "secret_ref": "secretref:binance:testnet",
        "responsibility_boundary_ref": "responsibility:testnet_order",
        "waiver_requests": (),
        "mock_profile": "none",
        "evidence_refs": ("evidence:testnet_ready",),
        "recorded_by": "tester",
    }
    data.update(overrides)
    return RuntimePromotionRecord(**data)


def _submission_test_state(tmp_path, monkeypatch):
    order_intents = PersistentExecutionOrderIntentRegistry(tmp_path / "execution_order_intents.jsonl")
    order_intent = order_intents.record_intent(
        _order_intent(),
        known_signal_validation_refs={"signal_validation:accepted"},
    )
    runtime_promotions = PersistentRuntimePromotionRegistry(tmp_path / "runtime_promotions.jsonl")
    runtime_promotion = runtime_promotions.record_promotion(_runtime_promotion_for_submission())
    materializations = PersistentExecutionOrderMaterializationRegistry(tmp_path / "execution_order_materializations.jsonl")
    connectivity_checks = PersistentExecutionVenueConnectivityCheckRegistry(
        tmp_path / "execution_venue_connectivity_checks.jsonl"
    )
    safety_attestations = PersistentExecutionVenueSafetyAttestationRegistry(
        tmp_path / "execution_venue_safety_attestations.jsonl"
    )
    capabilities = PersistentExecutionVenueCapabilityRegistry(tmp_path / "execution_venue_capabilities.jsonl")
    submit_requests = PersistentExecutionSubmitRequestRegistry(tmp_path / "execution_submit_requests.jsonl")
    submissions = PersistentExecutionOrderSubmissionRegistry(tmp_path / "execution_order_submissions.jsonl")
    graph = ResearchGraphStore()
    monkeypatch.setattr(app_main, "EXECUTION_ORDER_INTENTS", order_intents)
    monkeypatch.setattr(app_main, "RUNTIME_PROMOTIONS", runtime_promotions)
    monkeypatch.setattr(app_main, "EXECUTION_ORDER_MATERIALIZATIONS", materializations)
    monkeypatch.setattr(app_main, "EXECUTION_VENUE_CONNECTIVITY_CHECKS", connectivity_checks)
    monkeypatch.setattr(app_main, "EXECUTION_VENUE_SAFETY_ATTESTATIONS", safety_attestations)
    monkeypatch.setattr(app_main, "EXECUTION_VENUE_CAPABILITIES", capabilities)
    monkeypatch.setattr(app_main, "EXECUTION_SUBMIT_REQUESTS", submit_requests)
    monkeypatch.setattr(app_main, "EXECUTION_ORDER_SUBMISSIONS", submissions)
    monkeypatch.setattr(app_main, "RESEARCH_GRAPH_STORE", graph)
    _patch_compiler_coverage(tmp_path, monkeypatch)
    return order_intent, runtime_promotion, materializations, safety_attestations, capabilities, submissions, graph


def test_execution_order_materialization_requires_matching_guard_refs():
    decision = validate_execution_order_materialization(
        _materialization(),
        known_order_intent_refs={"order_intent:recorded"},
        known_runtime_promotion_refs={"runtime_promotion:recorded"},
        order_intent=_order_intent(order_intent_ref="order_intent:recorded"),
        runtime_promotion=_runtime_promotion_for_submission(runtime_promotion_ref="runtime_promotion:recorded"),
    )
    assert decision.accepted

    rejected = validate_execution_order_materialization(
        _materialization(secret_ref="secretref:other"),
        known_order_intent_refs={"order_intent:recorded"},
        known_runtime_promotion_refs={"runtime_promotion:recorded"},
        order_intent=_order_intent(order_intent_ref="order_intent:recorded"),
        runtime_promotion=_runtime_promotion_for_submission(runtime_promotion_ref="runtime_promotion:recorded"),
    )
    assert not rejected.accepted
    assert "order_materialization_intent_ref_mismatch" in _codes(rejected)


def test_execution_order_materialization_registry_persists_and_replays(tmp_path):
    path = tmp_path / "execution_order_materializations.jsonl"
    registry = PersistentExecutionOrderMaterializationRegistry(path)
    record = registry.record_materialization(
        _materialization(),
        known_order_intent_refs={"order_intent:recorded"},
        known_runtime_promotion_refs={"runtime_promotion:recorded"},
    )

    reloaded = PersistentExecutionOrderMaterializationRegistry(path)

    assert reloaded.materialization(record.materialization_ref).materializer_ref == "order_materializer:test"
    assert reloaded.materializations()[0].materialization_ref == record.materialization_ref


def test_execution_order_materialization_api_records_qro_without_default_materializer_call(tmp_path, monkeypatch):
    order_intent, runtime_promotion, _materializations, _safety_attestations, _capabilities, _submissions, graph = _submission_test_state(tmp_path, monkeypatch)
    app_main.app.dependency_overrides[require_user_dependency] = lambda: SimpleNamespace(
        user_id="tester",
        username="tester",
    )
    try:
        client = TestClient(app_main.app)
        payload = _materialization(
            order_intent_ref=order_intent.order_intent_ref,
            runtime_promotion_ref=runtime_promotion.runtime_promotion_ref,
        ).to_dict()
        response = client.post("/api/research-os/execution/order_materializations", json=payload)
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["materialization_ref"].startswith("order_materialization_")
        assert body["record_only"] is True
        assert body["materializer_called"] is False
        assert body["api_place_order_called"] is False
        assert body["api_venue_call_called"] is False
        _assert_compiler_coverage(body, entrypoint_ref="api:research_os.execution.order_materializations")
        qro = graph.qro(body["qro_id"])
        assert qro.qro_type.value == "ExecutionPolicy"
        assert qro.output_contract["status"] == "execution_order_materialization_recorded"
        assert qro.output_contract["record_only"] is True
        assert qro.output_contract["materializer_called"] is False
        assert qro.output_contract["api_place_order_called"] is False
        assert qro.output_contract["api_venue_call_called"] is False
        assert "raw_order" not in qro.output_contract
        assert "quantity" not in qro.output_contract
        assert "price" not in qro.output_contract

        summary = client.get("/api/research-os/execution/order_materializations/summary")
        assert summary.status_code == 200
        row = summary.json()["order_materializations"][0]
        assert row["order_intent_ref"] == order_intent.order_intent_ref
        assert row["runtime_promotion_ref"] == runtime_promotion.runtime_promotion_ref
        assert "raw_order" not in row
        assert "quantity" not in row
        assert "price" not in row
    finally:
        app_main.app.dependency_overrides.pop(require_user_dependency, None)


def test_execution_order_materialization_api_rejects_unknown_order_intent_without_write(tmp_path, monkeypatch):
    _order_intent, runtime_promotion, _materializations, _safety_attestations, _capabilities, _submissions, graph = _submission_test_state(tmp_path, monkeypatch)
    materialization_path = tmp_path / "execution_order_materializations_reject.jsonl"
    monkeypatch.setattr(
        app_main,
        "EXECUTION_ORDER_MATERIALIZATIONS",
        PersistentExecutionOrderMaterializationRegistry(materialization_path),
    )
    app_main.app.dependency_overrides[require_user_dependency] = lambda: SimpleNamespace(
        user_id="tester",
        username="tester",
    )
    try:
        client = TestClient(app_main.app)
        response = client.post(
            "/api/research-os/execution/order_materializations",
            json=_materialization(
                order_intent_ref="order_intent:missing",
                runtime_promotion_ref=runtime_promotion.runtime_promotion_ref,
            ).to_dict(),
        )
        assert response.status_code == 404
        assert response.json()["detail"] == "execution record not found"
        assert not materialization_path.exists()
        assert graph.commands() == []
    finally:
        app_main.app.dependency_overrides.pop(require_user_dependency, None)


def test_execution_order_materialization_api_calls_injected_materializer(tmp_path, monkeypatch):
    order_intent, runtime_promotion, _materializations, _safety_attestations, _capabilities, _submissions, graph = _submission_test_state(tmp_path, monkeypatch)

    class _FakeOrderMaterializer:
        materializer_ref = "order_materializer:fake"

        def __init__(self) -> None:
            self.calls = []

        def materialize_order(self, *, materialization, order_intent, runtime_promotion, actor):
            self.calls.append(
                {
                    "materialization_ref": materialization.materialization_ref,
                    "order_intent_ref": order_intent.order_intent_ref,
                    "runtime_promotion_ref": runtime_promotion.runtime_promotion_ref,
                    "actor": actor,
                }
            )
            return {
                "materializer_ref": self.materializer_ref,
                "order_schema_ref": "schema:execution_order:v1",
                "order_payload_hash": "sha256:order_payload_hash",
                "quantity_resolution_ref": "qty_resolution:001",
                "price_resolution_ref": "price_resolution:001",
                "market_snapshot_ref": "market_snapshot:001",
                "risk_check_ref": "risk_check:001",
                "evidence_refs": ["evidence:fake_materializer_called"],
            }

    fake = _FakeOrderMaterializer()
    monkeypatch.setattr(app_main, "EXECUTION_ORDER_MATERIALIZER", fake)
    app_main.app.dependency_overrides[require_user_dependency] = lambda: SimpleNamespace(
        user_id="tester",
        username="tester",
    )
    try:
        client = TestClient(app_main.app)
        payload = _materialization(
            order_intent_ref=order_intent.order_intent_ref,
            runtime_promotion_ref=runtime_promotion.runtime_promotion_ref,
            materialize_enabled=True,
        ).to_dict()
        response = client.post("/api/research-os/execution/order_materializations", json=payload)
        assert response.status_code == 200, response.text
        body = response.json()
        assert len(fake.calls) == 1
        assert fake.calls[0]["order_intent_ref"] == order_intent.order_intent_ref
        assert body["materialization_status"] == "materialized"
        assert body["materializer_ref"] == "order_materializer:fake"
        assert body["materializer_called"] is True
        assert body["record_only"] is False
        assert body["api_place_order_called"] is False
        assert body["api_venue_call_called"] is False
        assert body["order_payload_hash"] == "sha256:order_payload_hash"
        _assert_compiler_coverage(body, entrypoint_ref="api:research_os.execution.order_materializations")
        qro = graph.qro(body["qro_id"])
        assert qro.output_contract["materializer_called"] is True
        assert qro.output_contract["record_only"] is False
        assert qro.output_contract["api_place_order_called"] is False
        assert qro.output_contract["api_venue_call_called"] is False
        assert qro.output_contract["order_payload_hash"] == "sha256:order_payload_hash"
        assert "raw_order" not in qro.output_contract
        assert "quantity" not in qro.output_contract
        assert "price" not in qro.output_contract
    finally:
        app_main.app.dependency_overrides.pop(require_user_dependency, None)


def _record_accepted_connectivity_check(connectivity_checks, order_intent, runtime_promotion, **overrides):
    return connectivity_checks.record_check(
        _venue_connectivity_check(
            order_intent_ref=order_intent.order_intent_ref,
            runtime_promotion_ref=runtime_promotion.runtime_promotion_ref,
            **overrides,
        ),
        known_order_intent_refs={order_intent.order_intent_ref},
        known_runtime_promotion_refs={runtime_promotion.runtime_promotion_ref},
        order_intent=order_intent,
        runtime_promotion=runtime_promotion,
    )


def _record_accepted_safety_attestation(safety_attestations, order_intent, runtime_promotion, **overrides):
    connectivity_check = _record_accepted_connectivity_check(
        app_main.EXECUTION_VENUE_CONNECTIVITY_CHECKS,
        order_intent,
        runtime_promotion,
    )
    return safety_attestations.record_attestation(
        _accepted_venue_safety_attestation(
            order_intent_ref=order_intent.order_intent_ref,
            runtime_promotion_ref=runtime_promotion.runtime_promotion_ref,
            venue_connectivity_check_ref=connectivity_check.venue_connectivity_check_ref,
            **overrides,
        ),
        known_order_intent_refs={order_intent.order_intent_ref},
        known_runtime_promotion_refs={runtime_promotion.runtime_promotion_ref},
        known_venue_connectivity_check_refs={connectivity_check.venue_connectivity_check_ref},
        order_intent=order_intent,
        runtime_promotion=runtime_promotion,
        venue_connectivity_check=connectivity_check,
    )


def test_execution_venue_connectivity_check_requires_accepted_refs():
    order_intent = _order_intent(order_intent_ref="order_intent:recorded")
    runtime_promotion = _runtime_promotion_for_submission(runtime_promotion_ref="runtime_promotion:recorded")
    accepted = validate_execution_venue_connectivity_check(
        _venue_connectivity_check(),
        known_order_intent_refs={"order_intent:recorded"},
        known_runtime_promotion_refs={"runtime_promotion:recorded"},
        order_intent=order_intent,
        runtime_promotion=runtime_promotion,
    )
    assert accepted.accepted

    missing_hash = validate_execution_venue_connectivity_check(
        _venue_connectivity_check(connectivity_check_hash=None),
        order_intent=order_intent,
        runtime_promotion=runtime_promotion,
    )
    assert not missing_hash.accepted
    assert "venue_connectivity_check_missing_hash" in _codes(missing_hash)

    secret_mismatch = validate_execution_venue_connectivity_check(
        _venue_connectivity_check(secret_ref="secretref:other"),
        order_intent=order_intent,
        runtime_promotion=runtime_promotion,
    )
    assert not secret_mismatch.accepted
    assert "venue_connectivity_check_intent_ref_mismatch" in _codes(secret_mismatch)

    a_share_live = validate_execution_venue_connectivity_check(
        _venue_connectivity_check(runtime="live", asset_class="equity_cn", secret_ref="secretref:cn:live")
    )
    assert not a_share_live.accepted
    assert "a_share_live_venue_connectivity_check_forbidden" in _codes(a_share_live)


def test_execution_venue_connectivity_check_registry_persists_and_replays(tmp_path):
    path = tmp_path / "execution_venue_connectivity_checks.jsonl"
    registry = PersistentExecutionVenueConnectivityCheckRegistry(path)
    record = registry.record_check(
        _venue_connectivity_check(),
        known_order_intent_refs={"order_intent:recorded"},
        known_runtime_promotion_refs={"runtime_promotion:recorded"},
    )

    reloaded = PersistentExecutionVenueConnectivityCheckRegistry(path)

    assert reloaded.check(record.venue_connectivity_check_ref).connectivity_status == "accepted"
    assert reloaded.checks()[0].venue_connectivity_check_ref == record.venue_connectivity_check_ref


def test_execution_venue_connectivity_check_api_records_qro_without_venue_call(tmp_path, monkeypatch):
    order_intent, runtime_promotion, _materializations, _safety_attestations, _capabilities, _submissions, graph = _submission_test_state(tmp_path, monkeypatch)
    app_main.app.dependency_overrides[require_user_dependency] = lambda: SimpleNamespace(
        user_id="tester",
        username="tester",
    )
    try:
        client = TestClient(app_main.app)
        payload = _venue_connectivity_check(
            order_intent_ref=order_intent.order_intent_ref,
            runtime_promotion_ref=runtime_promotion.runtime_promotion_ref,
        ).to_dict()
        response = client.post("/api/research-os/execution/venue_connectivity_checks", json=payload)
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["venue_connectivity_check_ref"].startswith("venue_connectivity_check_")
        assert body["connectivity_status"] == "accepted"
        assert body["record_only"] is True
        assert body["api_place_order_called"] is False
        assert body["api_venue_call_called"] is False
        _assert_compiler_coverage(body, entrypoint_ref="api:research_os.execution.venue_connectivity_checks")
        qro = graph.qro(body["qro_id"])
        assert qro.qro_type.value == "ExecutionPolicy"
        assert qro.output_contract["status"] == "execution_venue_connectivity_check_recorded"
        assert qro.output_contract["connectivity_status"] == "accepted"
        assert qro.output_contract["record_only"] is True
        assert qro.output_contract["api_place_order_called"] is False
        assert qro.output_contract["api_venue_call_called"] is False
        assert qro.output_contract["connectivity_check_hash"] == "sha256:venue_connectivity_refs"
        assert "raw_order" not in qro.output_contract
        assert "quantity" not in qro.output_contract
        assert "price" not in qro.output_contract

        summary = client.get("/api/research-os/execution/venue_connectivity_checks/summary")
        assert summary.status_code == 200
        row = summary.json()["venue_connectivity_checks"][0]
        assert row["order_intent_ref"] == order_intent.order_intent_ref
        assert row["runtime_promotion_ref"] == runtime_promotion.runtime_promotion_ref
        assert row["connectivity_status"] == "accepted"
        assert "raw_order" not in row
        assert "quantity" not in row
        assert "price" not in row
    finally:
        app_main.app.dependency_overrides.pop(require_user_dependency, None)


def test_execution_venue_connectivity_check_api_rejects_raw_payload_without_write(tmp_path, monkeypatch):
    order_intent, runtime_promotion, _materializations, _safety_attestations, _capabilities, _submissions, graph = _submission_test_state(tmp_path, monkeypatch)
    check_path = tmp_path / "execution_venue_connectivity_checks_reject_raw.jsonl"
    monkeypatch.setattr(app_main, "EXECUTION_VENUE_CONNECTIVITY_CHECKS", PersistentExecutionVenueConnectivityCheckRegistry(check_path))
    app_main.app.dependency_overrides[require_user_dependency] = lambda: SimpleNamespace(
        user_id="tester",
        username="tester",
    )
    try:
        client = TestClient(app_main.app)
        payload = _venue_connectivity_check(
            order_intent_ref=order_intent.order_intent_ref,
            runtime_promotion_ref=runtime_promotion.runtime_promotion_ref,
        ).to_dict()
        payload["raw_order"] = {"quantity": 1, "price": 100}
        response = client.post("/api/research-os/execution/venue_connectivity_checks", json=payload)
        assert response.status_code == 422
        assert "raw order" in response.text
        assert not check_path.exists()
        assert graph.commands() == []
    finally:
        app_main.app.dependency_overrides.pop(require_user_dependency, None)


def test_execution_venue_connectivity_check_run_disabled_without_write(tmp_path, monkeypatch):
    order_intent, runtime_promotion, _materializations, _safety_attestations, _capabilities, _submissions, graph = _submission_test_state(tmp_path, monkeypatch)
    check_path = tmp_path / "execution_venue_connectivity_checks_disabled.jsonl"
    monkeypatch.setattr(app_main, "EXECUTION_VENUE_CONNECTIVITY_CHECKS", PersistentExecutionVenueConnectivityCheckRegistry(check_path))
    app_main.app.dependency_overrides[require_user_dependency] = lambda: SimpleNamespace(
        user_id="tester",
        username="tester",
    )
    try:
        client = TestClient(app_main.app)
        response = client.post(
            "/api/research-os/execution/venue_connectivity_checks/run",
            json={
                "order_intent_ref": order_intent.order_intent_ref,
                "runtime_promotion_ref": runtime_promotion.runtime_promotion_ref,
            },
        )
        assert response.status_code == 422
        assert "execution venue connectivity checker disabled" in response.text
        assert not check_path.exists()
        assert graph.commands() == []
    finally:
        app_main.app.dependency_overrides.pop(require_user_dependency, None)


def test_execution_venue_connectivity_check_run_calls_injected_checker(tmp_path, monkeypatch):
    order_intent, runtime_promotion, _materializations, _safety_attestations, _capabilities, _submissions, graph = _submission_test_state(tmp_path, monkeypatch)

    class _FakeConnectivityChecker:
        checker_ref = "venue_connectivity_checker:fake"

        def __init__(self) -> None:
            self.calls = []

        def check_connectivity(self, *, order_intent, runtime_promotion, actor):
            self.calls.append(
                {
                    "order_intent_ref": order_intent.order_intent_ref,
                    "runtime_promotion_ref": runtime_promotion.runtime_promotion_ref,
                    "actor": actor,
                }
            )
            return {
                "checker_ref": self.checker_ref,
                "guarded_venue_ref": "guarded_venue:binance_testnet",
                "audit_record_ref": "audit:venue_connectivity_check:fake",
                "credential_check_ref": "credential_check:binance_testnet:ok",
                "ip_allowlist_ref": "ip_allowlist:binance_testnet:ok",
                "withdrawal_disabled_ref": "withdrawal_disabled:binance_testnet:ok",
                "hmac_replay_protection_ref": "hmac_replay:binance_testnet:ok",
                "health_check_ref": "health_check:binance_testnet:ok",
                "rate_limit_ref": "rate_limit:binance_testnet:ok",
                "sandbox_proof_ref": "sandbox:binance_testnet:ok",
                "connectivity_check_hash": "sha256:fake_connectivity_check",
                "evidence_refs": ["evidence:fake_connectivity_checker_called"],
            }

    fake = _FakeConnectivityChecker()
    monkeypatch.setattr(app_main, "EXECUTION_VENUE_CONNECTIVITY_CHECKER", fake)
    app_main.app.dependency_overrides[require_user_dependency] = lambda: SimpleNamespace(
        user_id="tester",
        username="tester",
    )
    try:
        client = TestClient(app_main.app)
        response = client.post(
            "/api/research-os/execution/venue_connectivity_checks/run",
            json={
                "order_intent_ref": order_intent.order_intent_ref,
                "runtime_promotion_ref": runtime_promotion.runtime_promotion_ref,
            },
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert len(fake.calls) == 1
        assert fake.calls[0]["order_intent_ref"] == order_intent.order_intent_ref
        assert body["venue_connectivity_check_ref"].startswith("venue_connectivity_check_")
        assert body["checker_ref"] == "venue_connectivity_checker:fake"
        assert body["connectivity_status"] == "accepted"
        assert body["connectivity_check_hash"] == "sha256:fake_connectivity_check"
        assert body["checker_called"] is True
        assert body["api_place_order_called"] is False
        assert body["api_venue_call_called"] is False
        _assert_compiler_coverage(body, entrypoint_ref="api:research_os.execution.venue_connectivity_checks")
        qro = graph.qro(body["qro_id"])
        assert qro.qro_type.value == "ExecutionPolicy"
        assert qro.output_contract["status"] == "execution_venue_connectivity_check_recorded"
        assert qro.output_contract["checker_ref"] == "venue_connectivity_checker:fake"
        assert qro.output_contract["connectivity_check_hash"] == "sha256:fake_connectivity_check"
        assert qro.output_contract["api_place_order_called"] is False
        assert qro.output_contract["api_venue_call_called"] is False
        assert "raw_order" not in qro.output_contract
        assert "quantity" not in qro.output_contract
        assert "price" not in qro.output_contract
    finally:
        app_main.app.dependency_overrides.pop(require_user_dependency, None)


def test_execution_venue_connectivity_check_run_rejects_unsafe_checker_result_without_write(tmp_path, monkeypatch):
    order_intent, runtime_promotion, _materializations, _safety_attestations, _capabilities, _submissions, graph = _submission_test_state(tmp_path, monkeypatch)
    check_path = tmp_path / "execution_venue_connectivity_checks_unsafe_checker.jsonl"
    monkeypatch.setattr(app_main, "EXECUTION_VENUE_CONNECTIVITY_CHECKS", PersistentExecutionVenueConnectivityCheckRegistry(check_path))

    class _UnsafeConnectivityChecker:
        checker_ref = "venue_connectivity_checker:unsafe"

        def check_connectivity(self, *, order_intent, runtime_promotion, actor):
            return {
                "checker_ref": self.checker_ref,
                "guarded_venue_ref": "guarded_venue:binance_testnet",
                "raw_payload": {"status": "ok"},
            }

    monkeypatch.setattr(app_main, "EXECUTION_VENUE_CONNECTIVITY_CHECKER", _UnsafeConnectivityChecker())
    app_main.app.dependency_overrides[require_user_dependency] = lambda: SimpleNamespace(
        user_id="tester",
        username="tester",
    )
    try:
        client = TestClient(app_main.app)
        response = client.post(
            "/api/research-os/execution/venue_connectivity_checks/run",
            json={
                "order_intent_ref": order_intent.order_intent_ref,
                "runtime_promotion_ref": runtime_promotion.runtime_promotion_ref,
            },
        )
        assert response.status_code == 422
        assert "raw order" in response.text
        assert not check_path.exists()
        assert graph.commands() == []
    finally:
        app_main.app.dependency_overrides.pop(require_user_dependency, None)


def test_execution_venue_connectivity_check_run_rejects_direct_venue_call_report_without_write(tmp_path, monkeypatch):
    order_intent, runtime_promotion, _materializations, _safety_attestations, _capabilities, _submissions, graph = _submission_test_state(tmp_path, monkeypatch)
    check_path = tmp_path / "execution_venue_connectivity_checks_direct_venue.jsonl"
    monkeypatch.setattr(app_main, "EXECUTION_VENUE_CONNECTIVITY_CHECKS", PersistentExecutionVenueConnectivityCheckRegistry(check_path))

    class _DirectVenueConnectivityChecker:
        checker_ref = "venue_connectivity_checker:direct"

        def check_connectivity(self, *, order_intent, runtime_promotion, actor):
            return {
                "checker_ref": self.checker_ref,
                "guarded_venue_ref": "guarded_venue:binance_testnet",
                "api_venue_call_called": True,
                "audit_record_ref": "audit:venue_connectivity_check:direct",
                "credential_check_ref": "credential_check:binance_testnet:ok",
                "ip_allowlist_ref": "ip_allowlist:binance_testnet:ok",
                "withdrawal_disabled_ref": "withdrawal_disabled:binance_testnet:ok",
                "hmac_replay_protection_ref": "hmac_replay:binance_testnet:ok",
                "health_check_ref": "health_check:binance_testnet:ok",
                "rate_limit_ref": "rate_limit:binance_testnet:ok",
                "sandbox_proof_ref": "sandbox:binance_testnet:ok",
                "connectivity_check_hash": "sha256:direct_connectivity_check",
            }

    monkeypatch.setattr(app_main, "EXECUTION_VENUE_CONNECTIVITY_CHECKER", _DirectVenueConnectivityChecker())
    app_main.app.dependency_overrides[require_user_dependency] = lambda: SimpleNamespace(
        user_id="tester",
        username="tester",
    )
    try:
        client = TestClient(app_main.app)
        response = client.post(
            "/api/research-os/execution/venue_connectivity_checks/run",
            json={
                "order_intent_ref": order_intent.order_intent_ref,
                "runtime_promotion_ref": runtime_promotion.runtime_promotion_ref,
            },
        )
        assert response.status_code == 422
        assert "cannot call a venue API" in response.text
        assert not check_path.exists()
        assert graph.commands() == []
    finally:
        app_main.app.dependency_overrides.pop(require_user_dependency, None)


def test_execution_venue_safety_attestation_requires_matching_guard_refs():
    connectivity_check = _venue_connectivity_check()
    accepted = validate_execution_venue_safety_attestation(
        _accepted_venue_safety_attestation(
            venue_connectivity_check_ref=connectivity_check.venue_connectivity_check_ref,
        ),
        known_order_intent_refs={"order_intent:recorded"},
        known_runtime_promotion_refs={"runtime_promotion:recorded"},
        known_venue_connectivity_check_refs={connectivity_check.venue_connectivity_check_ref},
        order_intent=_order_intent(order_intent_ref="order_intent:recorded"),
        runtime_promotion=_runtime_promotion_for_submission(runtime_promotion_ref="runtime_promotion:recorded"),
        venue_connectivity_check=connectivity_check,
    )
    assert accepted.accepted

    rejected = validate_execution_venue_safety_attestation(
        _accepted_venue_safety_attestation(
            venue_connectivity_check_ref=connectivity_check.venue_connectivity_check_ref,
            secret_ref="secretref:other",
        ),
        known_order_intent_refs={"order_intent:recorded"},
        known_runtime_promotion_refs={"runtime_promotion:recorded"},
        known_venue_connectivity_check_refs={connectivity_check.venue_connectivity_check_ref},
        order_intent=_order_intent(order_intent_ref="order_intent:recorded"),
        runtime_promotion=_runtime_promotion_for_submission(runtime_promotion_ref="runtime_promotion:recorded"),
        venue_connectivity_check=connectivity_check,
    )
    assert not rejected.accepted
    assert "venue_safety_attestation_intent_ref_mismatch" in _codes(rejected)

    missing_connectivity_ref = validate_execution_venue_safety_attestation(
        _accepted_venue_safety_attestation(venue_connectivity_check_ref=None)
    )
    assert not missing_connectivity_ref.accepted
    assert "venue_safety_attestation_missing_connectivity_check_ref" in _codes(missing_connectivity_ref)

    failed_connectivity_check = _venue_connectivity_check(connectivity_status="failed")
    not_accepted_connectivity = validate_execution_venue_safety_attestation(
        _accepted_venue_safety_attestation(
            venue_connectivity_check_ref=failed_connectivity_check.venue_connectivity_check_ref,
        ),
        known_venue_connectivity_check_refs={failed_connectivity_check.venue_connectivity_check_ref},
        venue_connectivity_check=failed_connectivity_check,
    )
    assert not not_accepted_connectivity.accepted
    assert "venue_safety_attestation_connectivity_check_not_accepted" in _codes(not_accepted_connectivity)

    a_share_live = validate_execution_venue_safety_attestation(
        _accepted_venue_safety_attestation(runtime="live", asset_class="equity_cn", secret_ref="secretref:cn:live")
    )
    assert not a_share_live.accepted
    assert "a_share_live_venue_safety_attestation_forbidden" in _codes(a_share_live)


def test_execution_venue_safety_attestation_registry_persists_and_replays(tmp_path):
    path = tmp_path / "execution_venue_safety_attestations.jsonl"
    registry = PersistentExecutionVenueSafetyAttestationRegistry(path)
    connectivity_check = _venue_connectivity_check()
    record = registry.record_attestation(
        _accepted_venue_safety_attestation(
            venue_connectivity_check_ref=connectivity_check.venue_connectivity_check_ref,
        ),
        known_order_intent_refs={"order_intent:recorded"},
        known_runtime_promotion_refs={"runtime_promotion:recorded"},
        known_venue_connectivity_check_refs={connectivity_check.venue_connectivity_check_ref},
        venue_connectivity_check=connectivity_check,
    )

    reloaded = PersistentExecutionVenueSafetyAttestationRegistry(path)

    assert reloaded.attestation(record.venue_safety_attestation_ref).attestation_status == "accepted"
    assert reloaded.attestations()[0].venue_safety_attestation_ref == record.venue_safety_attestation_ref


def test_execution_venue_safety_attestation_api_records_qro_without_venue_call(tmp_path, monkeypatch):
    order_intent, runtime_promotion, _materializations, _safety_attestations, _capabilities, _submissions, graph = _submission_test_state(tmp_path, monkeypatch)
    connectivity_check = _record_accepted_connectivity_check(
        app_main.EXECUTION_VENUE_CONNECTIVITY_CHECKS,
        order_intent,
        runtime_promotion,
    )
    app_main.app.dependency_overrides[require_user_dependency] = lambda: SimpleNamespace(
        user_id="tester",
        username="tester",
    )
    try:
        client = TestClient(app_main.app)
        payload = _accepted_venue_safety_attestation(
            order_intent_ref=order_intent.order_intent_ref,
            runtime_promotion_ref=runtime_promotion.runtime_promotion_ref,
            venue_connectivity_check_ref=connectivity_check.venue_connectivity_check_ref,
        ).to_dict()
        response = client.post("/api/research-os/execution/venue_safety_attestations", json=payload)
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["venue_safety_attestation_ref"].startswith("venue_safety_attestation_")
        assert body["attestation_status"] == "accepted"
        assert body["venue_connectivity_check_ref"] == connectivity_check.venue_connectivity_check_ref
        assert body["record_only"] is True
        assert body["api_place_order_called"] is False
        assert body["api_venue_call_called"] is False
        _assert_compiler_coverage(body, entrypoint_ref="api:research_os.execution.venue_safety_attestations")
        qro = graph.qro(body["qro_id"])
        assert qro.qro_type.value == "ExecutionPolicy"
        assert qro.output_contract["status"] == "execution_venue_safety_attestation_recorded"
        assert qro.output_contract["attestation_status"] == "accepted"
        assert qro.output_contract["venue_connectivity_check_ref"] == connectivity_check.venue_connectivity_check_ref
        assert qro.output_contract["record_only"] is True
        assert qro.output_contract["api_place_order_called"] is False
        assert qro.output_contract["api_venue_call_called"] is False
        assert "raw_order" not in qro.output_contract
        assert "quantity" not in qro.output_contract
        assert "price" not in qro.output_contract

        summary = client.get("/api/research-os/execution/venue_safety_attestations/summary")
        assert summary.status_code == 200
        row = summary.json()["venue_safety_attestations"][0]
        assert row["order_intent_ref"] == order_intent.order_intent_ref
        assert row["runtime_promotion_ref"] == runtime_promotion.runtime_promotion_ref
        assert row["attestation_status"] == "accepted"
        assert row["venue_connectivity_check_ref"] == connectivity_check.venue_connectivity_check_ref
        assert "raw_order" not in row
        assert "quantity" not in row
        assert "price" not in row
    finally:
        app_main.app.dependency_overrides.pop(require_user_dependency, None)


def test_execution_venue_safety_attestation_api_rejects_raw_payload_without_write(tmp_path, monkeypatch):
    order_intent, runtime_promotion, _materializations, _safety_attestations, _capabilities, _submissions, graph = _submission_test_state(tmp_path, monkeypatch)
    attestation_path = tmp_path / "execution_venue_safety_attestations_reject_raw.jsonl"
    monkeypatch.setattr(
        app_main,
        "EXECUTION_VENUE_SAFETY_ATTESTATIONS",
        PersistentExecutionVenueSafetyAttestationRegistry(attestation_path),
    )
    app_main.app.dependency_overrides[require_user_dependency] = lambda: SimpleNamespace(
        user_id="tester",
        username="tester",
    )
    try:
        client = TestClient(app_main.app)
        payload = _accepted_venue_safety_attestation(
            order_intent_ref=order_intent.order_intent_ref,
            runtime_promotion_ref=runtime_promotion.runtime_promotion_ref,
        ).to_dict()
        payload["raw_order"] = {"quantity": 1, "price": 100}
        response = client.post("/api/research-os/execution/venue_safety_attestations", json=payload)
        assert response.status_code == 422
        assert "raw order" in response.text
        assert not attestation_path.exists()
        assert graph.commands() == []
    finally:
        app_main.app.dependency_overrides.pop(require_user_dependency, None)


def test_execution_venue_safety_attestation_api_rejects_unknown_connectivity_check_without_write(tmp_path, monkeypatch):
    order_intent, runtime_promotion, _materializations, _safety_attestations, _capabilities, _submissions, graph = _submission_test_state(tmp_path, monkeypatch)
    attestation_path = tmp_path / "execution_venue_safety_attestations_reject_unknown_check.jsonl"
    monkeypatch.setattr(
        app_main,
        "EXECUTION_VENUE_SAFETY_ATTESTATIONS",
        PersistentExecutionVenueSafetyAttestationRegistry(attestation_path),
    )
    app_main.app.dependency_overrides[require_user_dependency] = lambda: SimpleNamespace(
        user_id="tester",
        username="tester",
    )
    try:
        client = TestClient(app_main.app)
        payload = _accepted_venue_safety_attestation(
            order_intent_ref=order_intent.order_intent_ref,
            runtime_promotion_ref=runtime_promotion.runtime_promotion_ref,
            venue_connectivity_check_ref="venue_connectivity_check_unknown",
        ).to_dict()
        response = client.post("/api/research-os/execution/venue_safety_attestations", json=payload)
        assert response.status_code == 404
        assert response.json()["detail"] == "execution record not found"
        assert not attestation_path.exists()
        assert graph.commands() == []
    finally:
        app_main.app.dependency_overrides.pop(require_user_dependency, None)


def test_execution_venue_capability_requires_ready_safety_refs():
    attestation = _accepted_venue_safety_attestation()
    accepted = validate_execution_venue_capability(
        _ready_venue_capability(venue_safety_attestation_ref=attestation.venue_safety_attestation_ref),
        known_order_intent_refs={"order_intent:recorded"},
        known_runtime_promotion_refs={"runtime_promotion:recorded"},
        known_venue_safety_attestation_refs={attestation.venue_safety_attestation_ref},
        order_intent=_order_intent(order_intent_ref="order_intent:recorded"),
        runtime_promotion=_runtime_promotion_for_submission(runtime_promotion_ref="runtime_promotion:recorded"),
        venue_safety_attestation=attestation,
    )
    assert accepted.accepted

    missing_attestation_ref = validate_execution_venue_capability(_ready_venue_capability(venue_safety_attestation_ref=None))
    assert not missing_attestation_ref.accepted
    assert "venue_capability_missing_safety_attestation_ref" in _codes(missing_attestation_ref)

    missing_ready_ref = validate_execution_venue_capability(
        _ready_venue_capability(credential_check_ref=None),
        known_order_intent_refs={"order_intent:recorded"},
        known_runtime_promotion_refs={"runtime_promotion:recorded"},
        order_intent=_order_intent(order_intent_ref="order_intent:recorded"),
        runtime_promotion=_runtime_promotion_for_submission(runtime_promotion_ref="runtime_promotion:recorded"),
    )
    assert not missing_ready_ref.accepted
    assert "venue_capability_missing_ready_ref" in _codes(missing_ready_ref)

    not_ready = validate_execution_venue_capability(_venue_capability(can_submit_orders=True))
    assert not not_ready.accepted
    assert "venue_capability_submit_without_ready" in _codes(not_ready)

    a_share_live = validate_execution_venue_capability(
        _ready_venue_capability(runtime="live", asset_class="equity_cn", secret_ref="secretref:cn:live")
    )
    assert not a_share_live.accepted
    assert "a_share_live_venue_capability_forbidden" in _codes(a_share_live)


def test_execution_venue_capability_registry_persists_and_replays(tmp_path):
    path = tmp_path / "execution_venue_capabilities.jsonl"
    registry = PersistentExecutionVenueCapabilityRegistry(path)
    attestation = _accepted_venue_safety_attestation()
    record = registry.record_capability(
        _ready_venue_capability(venue_safety_attestation_ref=attestation.venue_safety_attestation_ref),
        known_order_intent_refs={"order_intent:recorded"},
        known_runtime_promotion_refs={"runtime_promotion:recorded"},
        known_venue_safety_attestation_refs={attestation.venue_safety_attestation_ref},
        venue_safety_attestation=attestation,
    )

    reloaded = PersistentExecutionVenueCapabilityRegistry(path)

    assert reloaded.capability(record.venue_capability_ref).guarded_venue_ref == "guarded_venue:binance_testnet"
    assert reloaded.capabilities()[0].venue_capability_ref == record.venue_capability_ref


def test_execution_venue_capability_api_records_qro_without_venue_call(tmp_path, monkeypatch):
    order_intent, runtime_promotion, _materializations, safety_attestations, _capabilities, _submissions, graph = _submission_test_state(tmp_path, monkeypatch)
    attestation = _record_accepted_safety_attestation(safety_attestations, order_intent, runtime_promotion)
    app_main.app.dependency_overrides[require_user_dependency] = lambda: SimpleNamespace(
        user_id="tester",
        username="tester",
    )
    try:
        client = TestClient(app_main.app)
        payload = _ready_venue_capability(
            order_intent_ref=order_intent.order_intent_ref,
            runtime_promotion_ref=runtime_promotion.runtime_promotion_ref,
            venue_safety_attestation_ref=attestation.venue_safety_attestation_ref,
        ).to_dict()
        response = client.post("/api/research-os/execution/venue_capabilities", json=payload)
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["venue_capability_ref"].startswith("venue_capability_")
        assert body["capability_status"] == "ready"
        assert body["can_submit_orders"] is True
        assert body["venue_safety_attestation_ref"] == attestation.venue_safety_attestation_ref
        assert body["record_only"] is True
        assert body["api_place_order_called"] is False
        assert body["api_venue_call_called"] is False
        _assert_compiler_coverage(body, entrypoint_ref="api:research_os.execution.venue_capabilities")
        qro = graph.qro(body["qro_id"])
        assert qro.qro_type.value == "ExecutionPolicy"
        assert qro.output_contract["status"] == "execution_venue_capability_recorded"
        assert qro.output_contract["can_submit_orders"] is True
        assert qro.output_contract["venue_safety_attestation_ref"] == attestation.venue_safety_attestation_ref
        assert qro.output_contract["record_only"] is True
        assert qro.output_contract["api_place_order_called"] is False
        assert qro.output_contract["api_venue_call_called"] is False
        assert "raw_order" not in qro.output_contract
        assert "quantity" not in qro.output_contract
        assert "price" not in qro.output_contract

        summary = client.get("/api/research-os/execution/venue_capabilities/summary")
        assert summary.status_code == 200
        row = summary.json()["venue_capabilities"][0]
        assert row["order_intent_ref"] == order_intent.order_intent_ref
        assert row["runtime_promotion_ref"] == runtime_promotion.runtime_promotion_ref
        assert row["guarded_venue_ref"] == "guarded_venue:binance_testnet"
        assert row["venue_safety_attestation_ref"] == attestation.venue_safety_attestation_ref
        assert "raw_order" not in row
        assert "quantity" not in row
        assert "price" not in row
    finally:
        app_main.app.dependency_overrides.pop(require_user_dependency, None)


def test_execution_venue_capability_api_rejects_raw_payload_without_write(tmp_path, monkeypatch):
    order_intent, runtime_promotion, _materializations, safety_attestations, _capabilities, _submissions, graph = _submission_test_state(tmp_path, monkeypatch)
    attestation = _record_accepted_safety_attestation(safety_attestations, order_intent, runtime_promotion)
    capability_path = tmp_path / "execution_venue_capabilities_reject_raw.jsonl"
    monkeypatch.setattr(app_main, "EXECUTION_VENUE_CAPABILITIES", PersistentExecutionVenueCapabilityRegistry(capability_path))
    app_main.app.dependency_overrides[require_user_dependency] = lambda: SimpleNamespace(
        user_id="tester",
        username="tester",
    )
    try:
        client = TestClient(app_main.app)
        payload = _ready_venue_capability(
            order_intent_ref=order_intent.order_intent_ref,
            runtime_promotion_ref=runtime_promotion.runtime_promotion_ref,
            venue_safety_attestation_ref=attestation.venue_safety_attestation_ref,
        ).to_dict()
        payload["raw_order"] = {"quantity": 1, "price": 100}
        response = client.post("/api/research-os/execution/venue_capabilities", json=payload)
        assert response.status_code == 422
        assert "raw order" in response.text
        assert not capability_path.exists()
        assert graph.commands() == []
    finally:
        app_main.app.dependency_overrides.pop(require_user_dependency, None)


def test_execution_venue_capability_api_rejects_ready_without_safety_attestation(tmp_path, monkeypatch):
    order_intent, runtime_promotion, _materializations, _safety_attestations, _capabilities, _submissions, graph = _submission_test_state(tmp_path, monkeypatch)
    capability_path = tmp_path / "execution_venue_capabilities_reject_missing_attestation.jsonl"
    monkeypatch.setattr(app_main, "EXECUTION_VENUE_CAPABILITIES", PersistentExecutionVenueCapabilityRegistry(capability_path))
    app_main.app.dependency_overrides[require_user_dependency] = lambda: SimpleNamespace(
        user_id="tester",
        username="tester",
    )
    try:
        client = TestClient(app_main.app)
        payload = _ready_venue_capability(
            order_intent_ref=order_intent.order_intent_ref,
            runtime_promotion_ref=runtime_promotion.runtime_promotion_ref,
            venue_safety_attestation_ref=None,
        ).to_dict()
        response = client.post("/api/research-os/execution/venue_capabilities", json=payload)
        assert response.status_code == 422
        assert "venue_capability_missing_safety_attestation_ref" in response.text
        assert not capability_path.exists()
        assert graph.commands() == []
    finally:
        app_main.app.dependency_overrides.pop(require_user_dependency, None)


def test_execution_submit_request_requires_ready_materialization_and_capability():
    materialization = _materialization(
        materialize_enabled=True,
        materialization_status="materialized",
        order_schema_ref="schema:execution_order:v1",
        order_payload_hash="sha256:order_payload_hash",
        quantity_resolution_ref="qty_resolution:001",
        price_resolution_ref="price_resolution:001",
        market_snapshot_ref="market_snapshot:001",
        risk_check_ref="risk_check:001",
    )
    capability = _ready_venue_capability()
    request = _submit_request(
        order_materialization_ref=materialization.materialization_ref,
        venue_capability_ref=capability.venue_capability_ref,
    )
    accepted = validate_execution_submit_request(
        request,
        order_intent=_order_intent(order_intent_ref="order_intent:recorded"),
        runtime_promotion=_runtime_promotion_for_submission(runtime_promotion_ref="runtime_promotion:recorded"),
        order_materialization=materialization,
        venue_capability=capability,
    )
    assert accepted.accepted

    rejected_missing_hash = validate_execution_submit_request(
        _submit_request(
            order_materialization_ref=materialization.materialization_ref,
            venue_capability_ref=capability.venue_capability_ref,
            submit_request_hash=None,
        ),
        order_intent=_order_intent(order_intent_ref="order_intent:recorded"),
        runtime_promotion=_runtime_promotion_for_submission(runtime_promotion_ref="runtime_promotion:recorded"),
        order_materialization=materialization,
        venue_capability=capability,
    )
    assert not rejected_missing_hash.accepted
    assert "submit_request_missing_ready_ref" in _codes(rejected_missing_hash)

    rejected_payload_mismatch = validate_execution_submit_request(
        _submit_request(
            order_materialization_ref=materialization.materialization_ref,
            venue_capability_ref=capability.venue_capability_ref,
            order_payload_hash="sha256:other",
        ),
        order_intent=_order_intent(order_intent_ref="order_intent:recorded"),
        runtime_promotion=_runtime_promotion_for_submission(runtime_promotion_ref="runtime_promotion:recorded"),
        order_materialization=materialization,
        venue_capability=capability,
    )
    assert not rejected_payload_mismatch.accepted
    assert "submit_request_materialization_ref_mismatch" in _codes(rejected_payload_mismatch)


def test_execution_submit_request_registry_persists_and_replays(tmp_path):
    path = tmp_path / "execution_submit_requests.jsonl"
    registry = PersistentExecutionSubmitRequestRegistry(path)
    record = registry.record_request(_submit_request(submit_request_status="recorded", submit_request_mode="record_only"))

    reloaded = PersistentExecutionSubmitRequestRegistry(path)

    assert reloaded.request(record.submit_request_ref).guarded_venue_ref == "guarded_venue:binance_testnet"
    assert reloaded.requests()[0].submit_request_ref == record.submit_request_ref


def test_execution_submit_request_api_records_qro_without_venue_call(tmp_path, monkeypatch):
    order_intent, runtime_promotion, materializations, safety_attestations, capabilities, _submissions, graph = _submission_test_state(tmp_path, monkeypatch)
    materialization = _record_ready_materialization(materializations, order_intent, runtime_promotion)
    capability = _record_ready_capability(capabilities, safety_attestations, order_intent, runtime_promotion)
    app_main.app.dependency_overrides[require_user_dependency] = lambda: SimpleNamespace(
        user_id="tester",
        username="tester",
    )
    try:
        client = TestClient(app_main.app)
        payload = _submit_request(
            order_intent_ref=order_intent.order_intent_ref,
            runtime_promotion_ref=runtime_promotion.runtime_promotion_ref,
            order_materialization_ref=materialization.materialization_ref,
            venue_capability_ref=capability.venue_capability_ref,
            submitter_ref=capability.submitter_ref,
            guarded_venue_ref=capability.guarded_venue_ref,
            venue_ref=capability.venue_ref,
            permission_gate_ref=capability.permission_gate_ref,
            order_guard_ref=capability.order_guard_ref,
            idempotency_key=capability.idempotency_key,
            order_schema_ref=materialization.order_schema_ref,
            order_payload_hash=materialization.order_payload_hash,
            kill_switch_ref=capability.kill_switch_ref,
            secret_ref=capability.secret_ref,
            responsibility_boundary_ref=capability.responsibility_boundary_ref,
        ).to_dict()
        response = client.post("/api/research-os/execution/submit_requests", json=payload)
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["submit_request_ref"].startswith("submit_request_")
        assert body["order_materialization_ref"] == materialization.materialization_ref
        assert body["venue_capability_ref"] == capability.venue_capability_ref
        assert body["record_only"] is True
        assert body["api_place_order_called"] is False
        assert body["api_venue_call_called"] is False
        _assert_compiler_coverage(body, entrypoint_ref="api:research_os.execution.submit_requests")
        qro = graph.qro(body["qro_id"])
        assert qro.qro_type.value == "ExecutionPolicy"
        assert qro.output_contract["status"] == "execution_submit_request_recorded"
        assert qro.output_contract["record_only"] is True
        assert qro.output_contract["api_place_order_called"] is False
        assert qro.output_contract["api_venue_call_called"] is False
        assert "raw_order" not in qro.output_contract
        assert "quantity" not in qro.output_contract
        assert "price" not in qro.output_contract

        summary = client.get("/api/research-os/execution/submit_requests/summary")
        assert summary.status_code == 200
        row = summary.json()["submit_requests"][0]
        assert row["submit_request_ref"] == body["submit_request_ref"]
        assert row["order_payload_hash"] == materialization.order_payload_hash
        assert "raw_order" not in row
        assert "quantity" not in row
        assert "price" not in row
    finally:
        app_main.app.dependency_overrides.pop(require_user_dependency, None)


def test_execution_submit_request_api_rejects_raw_payload_without_write(tmp_path, monkeypatch):
    order_intent, runtime_promotion, materializations, safety_attestations, capabilities, _submissions, graph = _submission_test_state(tmp_path, monkeypatch)
    materialization = _record_ready_materialization(materializations, order_intent, runtime_promotion)
    capability = _record_ready_capability(capabilities, safety_attestations, order_intent, runtime_promotion)
    request_path = tmp_path / "execution_submit_requests_reject_raw.jsonl"
    monkeypatch.setattr(app_main, "EXECUTION_SUBMIT_REQUESTS", PersistentExecutionSubmitRequestRegistry(request_path))
    app_main.app.dependency_overrides[require_user_dependency] = lambda: SimpleNamespace(
        user_id="tester",
        username="tester",
    )
    try:
        client = TestClient(app_main.app)
        payload = _submit_request(
            order_intent_ref=order_intent.order_intent_ref,
            runtime_promotion_ref=runtime_promotion.runtime_promotion_ref,
            order_materialization_ref=materialization.materialization_ref,
            venue_capability_ref=capability.venue_capability_ref,
            submitter_ref=capability.submitter_ref,
            guarded_venue_ref=capability.guarded_venue_ref,
            venue_ref=capability.venue_ref,
            permission_gate_ref=capability.permission_gate_ref,
            order_guard_ref=capability.order_guard_ref,
            idempotency_key=capability.idempotency_key,
            order_schema_ref=materialization.order_schema_ref,
            order_payload_hash=materialization.order_payload_hash,
            kill_switch_ref=capability.kill_switch_ref,
            secret_ref=capability.secret_ref,
            responsibility_boundary_ref=capability.responsibility_boundary_ref,
        ).to_dict()
        payload["raw_payload"] = {"quantity": 1, "price": 100}
        response = client.post("/api/research-os/execution/submit_requests", json=payload)
        assert response.status_code == 422
        assert "raw_payload" in response.text
        assert not request_path.exists()
        assert graph.commands() == []
    finally:
        app_main.app.dependency_overrides.pop(require_user_dependency, None)


def test_execution_submit_request_run_disabled_without_write(tmp_path, monkeypatch):
    order_intent, runtime_promotion, materializations, safety_attestations, capabilities, _submissions, graph = _submission_test_state(tmp_path, monkeypatch)
    materialization = _record_ready_materialization(materializations, order_intent, runtime_promotion)
    capability = _record_ready_capability(capabilities, safety_attestations, order_intent, runtime_promotion)
    request_path = tmp_path / "execution_submit_requests_disabled_builder.jsonl"
    monkeypatch.setattr(app_main, "EXECUTION_SUBMIT_REQUESTS", PersistentExecutionSubmitRequestRegistry(request_path))
    app_main.app.dependency_overrides[require_user_dependency] = lambda: SimpleNamespace(
        user_id="tester",
        username="tester",
    )
    try:
        client = TestClient(app_main.app)
        response = client.post(
            "/api/research-os/execution/submit_requests/run",
            json={
                "order_materialization_ref": materialization.materialization_ref,
                "venue_capability_ref": capability.venue_capability_ref,
            },
        )
        assert response.status_code == 422
        assert "execution submit request builder disabled" in response.text
        assert not request_path.exists()
        assert graph.commands() == []
    finally:
        app_main.app.dependency_overrides.pop(require_user_dependency, None)


def test_execution_submit_request_run_calls_injected_builder(tmp_path, monkeypatch):
    order_intent, runtime_promotion, materializations, safety_attestations, capabilities, _submissions, graph = _submission_test_state(tmp_path, monkeypatch)
    materialization = _record_ready_materialization(materializations, order_intent, runtime_promotion)
    capability = _record_ready_capability(capabilities, safety_attestations, order_intent, runtime_promotion)

    class _FakeSubmitRequestBuilder:
        builder_ref = "submit_request_builder:fake"

        def __init__(self) -> None:
            self.calls = []

        def build_submit_request(self, *, order_intent, runtime_promotion, order_materialization, venue_capability, actor):
            self.calls.append(
                {
                    "order_intent_ref": order_intent.order_intent_ref,
                    "runtime_promotion_ref": runtime_promotion.runtime_promotion_ref,
                    "order_materialization_ref": order_materialization.materialization_ref,
                    "venue_capability_ref": venue_capability.venue_capability_ref,
                    "actor": actor,
                }
            )
            return {
                "builder_ref": self.builder_ref,
                "audit_record_ref": "audit:submit_request_builder:fake",
                "submit_request_schema_ref": "schema:submit_request:v1",
                "submit_request_hash": "sha256:fake_submit_request",
                "client_order_ref_hash": "sha256:fake_client_order_ref",
                "evidence_refs": ["evidence:fake_submit_request_builder_called"],
            }

    fake = _FakeSubmitRequestBuilder()
    monkeypatch.setattr(app_main, "EXECUTION_SUBMIT_REQUEST_BUILDER", fake)
    app_main.app.dependency_overrides[require_user_dependency] = lambda: SimpleNamespace(
        user_id="tester",
        username="tester",
    )
    try:
        client = TestClient(app_main.app)
        response = client.post(
            "/api/research-os/execution/submit_requests/run",
            json={
                "order_materialization_ref": materialization.materialization_ref,
                "venue_capability_ref": capability.venue_capability_ref,
            },
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert len(fake.calls) == 1
        assert fake.calls[0]["order_materialization_ref"] == materialization.materialization_ref
        assert body["submit_request_ref"].startswith("submit_request_")
        assert body["order_materialization_ref"] == materialization.materialization_ref
        assert body["venue_capability_ref"] == capability.venue_capability_ref
        assert body["builder_ref"] == "submit_request_builder:fake"
        assert body["builder_called"] is True
        assert body["submit_request_status"] == "ready"
        assert body["order_payload_hash"] == materialization.order_payload_hash
        assert body["submit_request_hash"] == "sha256:fake_submit_request"
        assert body["api_place_order_called"] is False
        assert body["api_venue_call_called"] is False
        _assert_compiler_coverage(body, entrypoint_ref="api:research_os.execution.submit_requests")
        qro = graph.qro(body["qro_id"])
        assert qro.qro_type.value == "ExecutionPolicy"
        assert qro.output_contract["status"] == "execution_submit_request_recorded"
        assert qro.output_contract["submit_request_hash"] == "sha256:fake_submit_request"
        assert qro.output_contract["api_place_order_called"] is False
        assert qro.output_contract["api_venue_call_called"] is False
        assert "raw_order" not in qro.output_contract
        assert "quantity" not in qro.output_contract
        assert "price" not in qro.output_contract
    finally:
        app_main.app.dependency_overrides.pop(require_user_dependency, None)


def test_execution_submit_request_run_rejects_unsafe_builder_result_without_write(tmp_path, monkeypatch):
    order_intent, runtime_promotion, materializations, safety_attestations, capabilities, _submissions, graph = _submission_test_state(tmp_path, monkeypatch)
    materialization = _record_ready_materialization(materializations, order_intent, runtime_promotion)
    capability = _record_ready_capability(capabilities, safety_attestations, order_intent, runtime_promotion)
    request_path = tmp_path / "execution_submit_requests_unsafe_builder.jsonl"
    monkeypatch.setattr(app_main, "EXECUTION_SUBMIT_REQUESTS", PersistentExecutionSubmitRequestRegistry(request_path))

    class _UnsafeSubmitRequestBuilder:
        builder_ref = "submit_request_builder:unsafe"

        def build_submit_request(self, *, order_intent, runtime_promotion, order_materialization, venue_capability, actor):
            return {
                "builder_ref": self.builder_ref,
                "raw_payload": {"quantity": 1, "price": 100},
            }

    monkeypatch.setattr(app_main, "EXECUTION_SUBMIT_REQUEST_BUILDER", _UnsafeSubmitRequestBuilder())
    app_main.app.dependency_overrides[require_user_dependency] = lambda: SimpleNamespace(
        user_id="tester",
        username="tester",
    )
    try:
        client = TestClient(app_main.app)
        response = client.post(
            "/api/research-os/execution/submit_requests/run",
            json={
                "order_materialization_ref": materialization.materialization_ref,
                "venue_capability_ref": capability.venue_capability_ref,
            },
        )
        assert response.status_code == 422
        assert "raw order" in response.text
        assert not request_path.exists()
        assert graph.commands() == []
    finally:
        app_main.app.dependency_overrides.pop(require_user_dependency, None)


def test_execution_submit_request_run_rejects_direct_venue_call_report_without_write(tmp_path, monkeypatch):
    order_intent, runtime_promotion, materializations, safety_attestations, capabilities, _submissions, graph = _submission_test_state(tmp_path, monkeypatch)
    materialization = _record_ready_materialization(materializations, order_intent, runtime_promotion)
    capability = _record_ready_capability(capabilities, safety_attestations, order_intent, runtime_promotion)
    request_path = tmp_path / "execution_submit_requests_direct_venue_builder.jsonl"
    monkeypatch.setattr(app_main, "EXECUTION_SUBMIT_REQUESTS", PersistentExecutionSubmitRequestRegistry(request_path))

    class _DirectVenueSubmitRequestBuilder:
        builder_ref = "submit_request_builder:direct"

        def build_submit_request(self, *, order_intent, runtime_promotion, order_materialization, venue_capability, actor):
            return {
                "builder_ref": self.builder_ref,
                "api_venue_call_called": True,
                "audit_record_ref": "audit:submit_request_builder:direct",
                "submit_request_schema_ref": "schema:submit_request:v1",
                "submit_request_hash": "sha256:direct_submit_request",
                "client_order_ref_hash": "sha256:direct_client_order_ref",
            }

    monkeypatch.setattr(app_main, "EXECUTION_SUBMIT_REQUEST_BUILDER", _DirectVenueSubmitRequestBuilder())
    app_main.app.dependency_overrides[require_user_dependency] = lambda: SimpleNamespace(
        user_id="tester",
        username="tester",
    )
    try:
        client = TestClient(app_main.app)
        response = client.post(
            "/api/research-os/execution/submit_requests/run",
            json={
                "order_materialization_ref": materialization.materialization_ref,
                "venue_capability_ref": capability.venue_capability_ref,
            },
        )
        assert response.status_code == 422
        assert "cannot call a venue API" in response.text
        assert not request_path.exists()
        assert graph.commands() == []
    finally:
        app_main.app.dependency_overrides.pop(require_user_dependency, None)


def test_execution_order_submission_requires_matching_guard_refs():
    decision = validate_execution_order_submission(
        _submission(),
        order_intent=_order_intent(),
        runtime_promotion=_runtime_promotion_for_submission(),
    )
    assert decision.accepted

    rejected = validate_execution_order_submission(
        _submission(secret_ref="secretref:other"),
        order_intent=_order_intent(),
        runtime_promotion=_runtime_promotion_for_submission(),
    )
    assert not rejected.accepted
    assert "order_submission_intent_ref_mismatch" in _codes(rejected)


def test_execution_order_submission_requires_ready_matching_venue_capability():
    materialization = _materialization(
        materialize_enabled=True,
        materialization_status="materialized",
        order_schema_ref="schema:execution_order:v1",
        order_payload_hash="sha256:order_payload_hash",
        quantity_resolution_ref="qty_resolution:001",
        price_resolution_ref="price_resolution:001",
        market_snapshot_ref="market_snapshot:001",
        risk_check_ref="risk_check:001",
    )
    capability = _ready_venue_capability()
    submit_request = _submit_request(
        order_materialization_ref=materialization.materialization_ref,
        venue_capability_ref=capability.venue_capability_ref,
    )
    submission = _submission(
        submit_enabled=True,
        order_materialization_ref=materialization.materialization_ref,
        venue_capability_ref=capability.venue_capability_ref,
        submit_request_ref=submit_request.submit_request_ref,
    )

    accepted = validate_execution_order_submission(
        submission,
        order_intent=_order_intent(order_intent_ref="order_intent:recorded"),
        runtime_promotion=_runtime_promotion_for_submission(runtime_promotion_ref="runtime_promotion:recorded"),
        order_materialization=materialization,
        venue_capability=capability,
        submit_request=submit_request,
    )
    assert accepted.accepted

    non_ready_capability = _venue_capability()
    non_ready_submit_request = _submit_request(
        order_materialization_ref=materialization.materialization_ref,
        venue_capability_ref=non_ready_capability.venue_capability_ref,
    )
    rejected_not_ready = validate_execution_order_submission(
        _submission(
            submit_enabled=True,
            order_materialization_ref=materialization.materialization_ref,
            venue_capability_ref=non_ready_capability.venue_capability_ref,
            submit_request_ref=non_ready_submit_request.submit_request_ref,
        ),
        order_intent=_order_intent(order_intent_ref="order_intent:recorded"),
        runtime_promotion=_runtime_promotion_for_submission(runtime_promotion_ref="runtime_promotion:recorded"),
        order_materialization=materialization,
        venue_capability=non_ready_capability,
        submit_request=non_ready_submit_request,
    )
    assert not rejected_not_ready.accepted
    assert "order_submission_venue_capability_not_ready" in _codes(rejected_not_ready)

    mismatch_submit_request = _submit_request(
        order_materialization_ref=materialization.materialization_ref,
        venue_capability_ref=capability.venue_capability_ref,
        submitter_ref="guarded_submitter:other",
    )
    rejected_mismatch = validate_execution_order_submission(
        _submission(
            submitter_ref="guarded_submitter:other",
            submit_enabled=True,
            order_materialization_ref=materialization.materialization_ref,
            venue_capability_ref=capability.venue_capability_ref,
            submit_request_ref=mismatch_submit_request.submit_request_ref,
        ),
        order_intent=_order_intent(order_intent_ref="order_intent:recorded"),
        runtime_promotion=_runtime_promotion_for_submission(runtime_promotion_ref="runtime_promotion:recorded"),
        order_materialization=materialization,
        venue_capability=capability,
        submit_request=mismatch_submit_request,
    )
    assert not rejected_mismatch.accepted
    assert "order_submission_venue_capability_ref_mismatch" in _codes(rejected_mismatch)


def test_execution_order_submission_registry_persists_and_replays(tmp_path):
    path = tmp_path / "execution_order_submissions.jsonl"
    registry = PersistentExecutionOrderSubmissionRegistry(path)
    record = registry.record_submission(
        _submission(),
        known_order_intent_refs={"order_intent:recorded"},
        known_runtime_promotion_refs={"runtime_promotion:recorded"},
    )

    reloaded = PersistentExecutionOrderSubmissionRegistry(path)

    assert reloaded.submission(record.submission_ref).guarded_venue_ref == "guarded_venue:binance_testnet"
    assert reloaded.submissions()[0].submission_ref == record.submission_ref


def test_execution_order_submission_api_records_qro_without_default_submitter_call(tmp_path, monkeypatch):
    order_intent, runtime_promotion, _materializations, _safety_attestations, _capabilities, _submissions, graph = _submission_test_state(tmp_path, monkeypatch)
    app_main.app.dependency_overrides[require_user_dependency] = lambda: SimpleNamespace(
        user_id="tester",
        username="tester",
    )
    try:
        client = TestClient(app_main.app)
        payload = _submission(
            order_intent_ref=order_intent.order_intent_ref,
            runtime_promotion_ref=runtime_promotion.runtime_promotion_ref,
        ).to_dict()
        response = client.post("/api/research-os/execution/order_submissions", json=payload)
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["submission_ref"].startswith("order_submission_")
        assert body["record_only"] is True
        assert body["submitter_called"] is False
        assert body["api_place_order_called"] is False
        assert body["api_venue_call_called"] is False
        _assert_compiler_coverage(body, entrypoint_ref="api:research_os.execution.order_submissions")
        qro = graph.qro(body["qro_id"])
        assert qro.qro_type.value == "ExecutionPolicy"
        assert qro.output_contract["status"] == "execution_order_submission_recorded"
        assert qro.output_contract["record_only"] is True
        assert qro.output_contract["submitter_called"] is False
        assert qro.output_contract["api_place_order_called"] is False
        assert qro.output_contract["api_venue_call_called"] is False
        assert "raw_order" not in qro.output_contract
        assert "quantity" not in qro.output_contract
        assert "price" not in qro.output_contract

        summary = client.get("/api/research-os/execution/order_submissions/summary")
        assert summary.status_code == 200
        row = summary.json()["order_submissions"][0]
        assert row["order_intent_ref"] == order_intent.order_intent_ref
        assert row["runtime_promotion_ref"] == runtime_promotion.runtime_promotion_ref
        assert "raw_order" not in row
        assert "quantity" not in row
        assert "price" not in row
    finally:
        app_main.app.dependency_overrides.pop(require_user_dependency, None)


def test_execution_order_submission_api_rejects_unknown_order_intent_without_write(tmp_path, monkeypatch):
    _order_intent, runtime_promotion, _materializations, _safety_attestations, _capabilities, _submissions, graph = _submission_test_state(tmp_path, monkeypatch)
    submission_path = tmp_path / "execution_order_submissions_reject.jsonl"
    monkeypatch.setattr(app_main, "EXECUTION_ORDER_SUBMISSIONS", PersistentExecutionOrderSubmissionRegistry(submission_path))
    app_main.app.dependency_overrides[require_user_dependency] = lambda: SimpleNamespace(
        user_id="tester",
        username="tester",
    )
    try:
        client = TestClient(app_main.app)
        response = client.post(
            "/api/research-os/execution/order_submissions",
            json=_submission(
                order_intent_ref="order_intent:missing",
                runtime_promotion_ref=runtime_promotion.runtime_promotion_ref,
            ).to_dict(),
        )
        assert response.status_code == 404
        assert response.json()["detail"] == "execution record not found"
        assert not submission_path.exists()
        assert graph.commands() == []
    finally:
        app_main.app.dependency_overrides.pop(require_user_dependency, None)


def test_execution_order_submission_api_rejects_submit_without_materialization(tmp_path, monkeypatch):
    order_intent, runtime_promotion, _materializations, _safety_attestations, _capabilities, _submissions, graph = _submission_test_state(tmp_path, monkeypatch)

    class _FakeGuardedSubmitter:
        def __init__(self) -> None:
            self.calls = []

        def submit_guarded_order(self, **kwargs):
            self.calls.append(kwargs)
            return {}

    fake = _FakeGuardedSubmitter()
    monkeypatch.setattr(app_main, "EXECUTION_ORDER_SUBMITTER", fake)
    submission_path = tmp_path / "execution_order_submissions_reject_materialization.jsonl"
    monkeypatch.setattr(app_main, "EXECUTION_ORDER_SUBMISSIONS", PersistentExecutionOrderSubmissionRegistry(submission_path))
    app_main.app.dependency_overrides[require_user_dependency] = lambda: SimpleNamespace(
        user_id="tester",
        username="tester",
    )
    try:
        client = TestClient(app_main.app)
        response = client.post(
            "/api/research-os/execution/order_submissions",
            json=_submission(
                order_intent_ref=order_intent.order_intent_ref,
                runtime_promotion_ref=runtime_promotion.runtime_promotion_ref,
                submit_enabled=True,
            ).to_dict(),
        )
        assert response.status_code == 422
        assert "order_submission_missing_materialization_ref" in response.text
        assert fake.calls == []
        assert not submission_path.exists()
        assert graph.commands() == []
    finally:
        app_main.app.dependency_overrides.pop(require_user_dependency, None)


def _record_ready_materialization(materializations, order_intent, runtime_promotion):
    return materializations.record_materialization(
        _materialization(
            order_intent_ref=order_intent.order_intent_ref,
            runtime_promotion_ref=runtime_promotion.runtime_promotion_ref,
            materialize_enabled=True,
            materialization_status="materialized",
            order_schema_ref="schema:execution_order:v1",
            order_payload_hash="sha256:order_payload_hash",
            quantity_resolution_ref="qty_resolution:001",
            price_resolution_ref="price_resolution:001",
            market_snapshot_ref="market_snapshot:001",
            risk_check_ref="risk_check:001",
        ),
        known_order_intent_refs={order_intent.order_intent_ref},
        known_runtime_promotion_refs={runtime_promotion.runtime_promotion_ref},
        order_intent=order_intent,
        runtime_promotion=runtime_promotion,
    )


def _record_ready_capability(capabilities, safety_attestations, order_intent, runtime_promotion, **overrides):
    attestation = _record_accepted_safety_attestation(safety_attestations, order_intent, runtime_promotion)
    return capabilities.record_capability(
        _ready_venue_capability(
            order_intent_ref=order_intent.order_intent_ref,
            runtime_promotion_ref=runtime_promotion.runtime_promotion_ref,
            venue_safety_attestation_ref=attestation.venue_safety_attestation_ref,
            **overrides,
        ),
        known_order_intent_refs={order_intent.order_intent_ref},
        known_runtime_promotion_refs={runtime_promotion.runtime_promotion_ref},
        known_venue_safety_attestation_refs={attestation.venue_safety_attestation_ref},
        order_intent=order_intent,
        runtime_promotion=runtime_promotion,
        venue_safety_attestation=attestation,
    )


def _record_ready_submit_request(submit_requests, order_intent, runtime_promotion, materialization, capability, **overrides):
    data = {
        "order_intent_ref": order_intent.order_intent_ref,
        "runtime_promotion_ref": runtime_promotion.runtime_promotion_ref,
        "order_materialization_ref": materialization.materialization_ref,
        "venue_capability_ref": capability.venue_capability_ref,
        "submitter_ref": capability.submitter_ref,
        "guarded_venue_ref": capability.guarded_venue_ref,
        "venue_ref": capability.venue_ref,
        "permission_gate_ref": capability.permission_gate_ref,
        "order_guard_ref": capability.order_guard_ref,
        "idempotency_key": capability.idempotency_key,
        "order_schema_ref": materialization.order_schema_ref,
        "order_payload_hash": materialization.order_payload_hash,
        "kill_switch_ref": capability.kill_switch_ref,
        "secret_ref": capability.secret_ref,
        "responsibility_boundary_ref": capability.responsibility_boundary_ref,
    }
    data.update(overrides)
    return submit_requests.record_request(
        _submit_request(**data),
        known_order_intent_refs={order_intent.order_intent_ref},
        known_runtime_promotion_refs={runtime_promotion.runtime_promotion_ref},
        known_order_materialization_refs={materialization.materialization_ref},
        known_venue_capability_refs={capability.venue_capability_ref},
        order_intent=order_intent,
        runtime_promotion=runtime_promotion,
        order_materialization=materialization,
        venue_capability=capability,
    )


def _record_submitted_submission(
    submissions,
    order_intent,
    runtime_promotion,
    materialization,
    capability,
    submit_request,
    **overrides,
):
    data = {
        "order_intent_ref": order_intent.order_intent_ref,
        "runtime_promotion_ref": runtime_promotion.runtime_promotion_ref,
        "submitter_ref": capability.submitter_ref,
        "guarded_venue_ref": capability.guarded_venue_ref,
        "venue_ref": capability.venue_ref,
        "submission_mode": submit_request.submit_request_mode,
        "permission_gate_ref": capability.permission_gate_ref,
        "order_guard_ref": capability.order_guard_ref,
        "idempotency_key": capability.idempotency_key,
        "audit_record_ref": "audit:order_submission:recorded",
        "kill_switch_ref": capability.kill_switch_ref,
        "secret_ref": capability.secret_ref,
        "responsibility_boundary_ref": capability.responsibility_boundary_ref,
        "submit_enabled": True,
        "order_materialization_ref": materialization.materialization_ref,
        "venue_capability_ref": capability.venue_capability_ref,
        "submit_request_ref": submit_request.submit_request_ref,
        "submission_status": "accepted",
        "venue_order_ref": "venue_order:recorded_ack",
        "ack_ref": "ack:recorded_submission",
        "client_order_ref_hash": submit_request.client_order_ref_hash,
        "evidence_refs": ("evidence:recorded_submission",),
    }
    data.update(overrides)
    return submissions.record_submission(
        _submission(**data),
        known_order_intent_refs={order_intent.order_intent_ref},
        known_runtime_promotion_refs={runtime_promotion.runtime_promotion_ref},
        known_order_materialization_refs={materialization.materialization_ref},
        known_venue_capability_refs={capability.venue_capability_ref},
        known_submit_request_refs={submit_request.submit_request_ref},
        order_intent=order_intent,
        runtime_promotion=runtime_promotion,
        order_materialization=materialization,
        venue_capability=capability,
        submit_request=submit_request,
    )


def test_execution_order_submission_api_rejects_submit_without_venue_capability(tmp_path, monkeypatch):
    order_intent, runtime_promotion, materializations, _safety_attestations, _capabilities, _submissions, graph = _submission_test_state(
        tmp_path,
        monkeypatch,
    )
    materialization = _record_ready_materialization(materializations, order_intent, runtime_promotion)

    class _FakeGuardedSubmitter:
        def __init__(self) -> None:
            self.calls = []

        def submit_guarded_order(self, **kwargs):
            self.calls.append(kwargs)
            return {}

    fake = _FakeGuardedSubmitter()
    monkeypatch.setattr(app_main, "EXECUTION_ORDER_SUBMITTER", fake)
    submission_path = tmp_path / "execution_order_submissions_reject_capability.jsonl"
    monkeypatch.setattr(app_main, "EXECUTION_ORDER_SUBMISSIONS", PersistentExecutionOrderSubmissionRegistry(submission_path))
    app_main.app.dependency_overrides[require_user_dependency] = lambda: SimpleNamespace(
        user_id="tester",
        username="tester",
    )
    try:
        client = TestClient(app_main.app)
        response = client.post(
            "/api/research-os/execution/order_submissions",
            json=_submission(
                order_intent_ref=order_intent.order_intent_ref,
                runtime_promotion_ref=runtime_promotion.runtime_promotion_ref,
                order_materialization_ref=materialization.materialization_ref,
                submit_enabled=True,
            ).to_dict(),
        )
        assert response.status_code == 422
        assert "order_submission_missing_venue_capability_ref" in response.text
        assert fake.calls == []
        assert not submission_path.exists()
        assert graph.commands() == []
    finally:
        app_main.app.dependency_overrides.pop(require_user_dependency, None)


def test_execution_order_submission_api_rejects_submit_without_submit_request(tmp_path, monkeypatch):
    order_intent, runtime_promotion, materializations, safety_attestations, capabilities, _submissions, graph = _submission_test_state(
        tmp_path,
        monkeypatch,
    )
    materialization = _record_ready_materialization(materializations, order_intent, runtime_promotion)
    capability = _record_ready_capability(capabilities, safety_attestations, order_intent, runtime_promotion)

    class _FakeGuardedSubmitter:
        def __init__(self) -> None:
            self.calls = []

        def submit_guarded_order(self, **kwargs):
            self.calls.append(kwargs)
            return {}

    fake = _FakeGuardedSubmitter()
    monkeypatch.setattr(app_main, "EXECUTION_ORDER_SUBMITTER", fake)
    submission_path = tmp_path / "execution_order_submissions_reject_submit_request.jsonl"
    monkeypatch.setattr(app_main, "EXECUTION_ORDER_SUBMISSIONS", PersistentExecutionOrderSubmissionRegistry(submission_path))
    app_main.app.dependency_overrides[require_user_dependency] = lambda: SimpleNamespace(
        user_id="tester",
        username="tester",
    )
    try:
        client = TestClient(app_main.app)
        response = client.post(
            "/api/research-os/execution/order_submissions",
            json=_submission(
                order_intent_ref=order_intent.order_intent_ref,
                runtime_promotion_ref=runtime_promotion.runtime_promotion_ref,
                order_materialization_ref=materialization.materialization_ref,
                venue_capability_ref=capability.venue_capability_ref,
                submit_enabled=True,
            ).to_dict(),
        )
        assert response.status_code == 422
        assert "order_submission_missing_submit_request_ref" in response.text
        assert fake.calls == []
        assert not submission_path.exists()
        assert graph.commands() == []
    finally:
        app_main.app.dependency_overrides.pop(require_user_dependency, None)


def test_execution_order_submission_api_rejects_raw_submitter_result_without_write(tmp_path, monkeypatch):
    order_intent, runtime_promotion, materializations, safety_attestations, capabilities, _submissions, graph = _submission_test_state(tmp_path, monkeypatch)
    materialization = _record_ready_materialization(materializations, order_intent, runtime_promotion)
    capability = _record_ready_capability(capabilities, safety_attestations, order_intent, runtime_promotion)
    submit_request = _record_ready_submit_request(
        app_main.EXECUTION_SUBMIT_REQUESTS,
        order_intent,
        runtime_promotion,
        materialization,
        capability,
    )

    class _RawResultSubmitter:
        def __init__(self) -> None:
            self.calls = []

        def submit_guarded_order(self, **kwargs):
            self.calls.append(kwargs)
            return {"raw_order": {"quantity": 1, "price": 100}}

    fake = _RawResultSubmitter()
    monkeypatch.setattr(app_main, "EXECUTION_ORDER_SUBMITTER", fake)
    submission_path = tmp_path / "execution_order_submissions_reject_raw_submitter.jsonl"
    monkeypatch.setattr(app_main, "EXECUTION_ORDER_SUBMISSIONS", PersistentExecutionOrderSubmissionRegistry(submission_path))
    app_main.app.dependency_overrides[require_user_dependency] = lambda: SimpleNamespace(
        user_id="tester",
        username="tester",
    )
    try:
        client = TestClient(app_main.app)
        response = client.post(
            "/api/research-os/execution/order_submissions",
            json=_submission(
                order_intent_ref=order_intent.order_intent_ref,
                runtime_promotion_ref=runtime_promotion.runtime_promotion_ref,
                order_materialization_ref=materialization.materialization_ref,
                venue_capability_ref=capability.venue_capability_ref,
                submit_request_ref=submit_request.submit_request_ref,
                submit_enabled=True,
            ).to_dict(),
        )
        assert response.status_code == 422
        assert "raw order" in response.text
        assert len(fake.calls) == 1
        assert not submission_path.exists()
        assert graph.commands() == []
    finally:
        app_main.app.dependency_overrides.pop(require_user_dependency, None)


def test_execution_order_submission_api_calls_injected_guarded_submitter(tmp_path, monkeypatch):
    order_intent, runtime_promotion, materializations, safety_attestations, capabilities, _submissions, graph = _submission_test_state(tmp_path, monkeypatch)
    materialization = _record_ready_materialization(materializations, order_intent, runtime_promotion)
    capability = _record_ready_capability(
        capabilities,
        safety_attestations,
        order_intent,
        runtime_promotion,
        submitter_ref="guarded_submitter:fake",
    )
    submit_request = _record_ready_submit_request(
        app_main.EXECUTION_SUBMIT_REQUESTS,
        order_intent,
        runtime_promotion,
        materialization,
        capability,
        submitter_ref="guarded_submitter:fake",
    )

    class _FakeGuardedSubmitter:
        submitter_ref = "guarded_submitter:fake"

        def __init__(self) -> None:
            self.calls = []

        def submit_guarded_order(
            self,
            *,
            submission,
            order_intent,
            runtime_promotion,
            order_materialization,
            venue_capability,
            submit_request,
            actor,
        ):
            self.calls.append(
                {
                    "submission_ref": submission.submission_ref,
                    "order_intent_ref": order_intent.order_intent_ref,
                    "runtime_promotion_ref": runtime_promotion.runtime_promotion_ref,
                    "order_materialization_ref": order_materialization.materialization_ref,
                    "venue_capability_ref": venue_capability.venue_capability_ref,
                    "submit_request_ref": submit_request.submit_request_ref,
                    "actor": actor,
                }
            )
            return {
                "submitter_ref": self.submitter_ref,
                "submission_status": "submitted",
                "venue_order_ref": "venue_order:fake_ack",
                "ack_ref": "ack:fake_guarded_submitter",
                "evidence_refs": ["evidence:fake_guarded_submitter_called"],
                "api_venue_call_called": False,
            }

    fake = _FakeGuardedSubmitter()
    monkeypatch.setattr(app_main, "EXECUTION_ORDER_SUBMITTER", fake)
    app_main.app.dependency_overrides[require_user_dependency] = lambda: SimpleNamespace(
        user_id="tester",
        username="tester",
    )
    try:
        client = TestClient(app_main.app)
        payload = _submission(
            order_intent_ref=order_intent.order_intent_ref,
            runtime_promotion_ref=runtime_promotion.runtime_promotion_ref,
            submitter_ref="guarded_submitter:fake",
            order_materialization_ref=materialization.materialization_ref,
            venue_capability_ref=capability.venue_capability_ref,
            submit_request_ref=submit_request.submit_request_ref,
            submit_enabled=True,
        ).to_dict()
        response = client.post("/api/research-os/execution/order_submissions", json=payload)
        assert response.status_code == 200, response.text
        body = response.json()
        assert len(fake.calls) == 1
        assert fake.calls[0]["order_intent_ref"] == order_intent.order_intent_ref
        assert fake.calls[0]["order_materialization_ref"] == materialization.materialization_ref
        assert fake.calls[0]["venue_capability_ref"] == capability.venue_capability_ref
        assert fake.calls[0]["submit_request_ref"] == submit_request.submit_request_ref
        assert body["order_materialization_ref"] == materialization.materialization_ref
        assert body["venue_capability_ref"] == capability.venue_capability_ref
        assert body["submit_request_ref"] == submit_request.submit_request_ref
        assert body["submission_status"] == "submitted"
        assert body["submitter_ref"] == "guarded_submitter:fake"
        assert body["submitter_called"] is True
        assert body["record_only"] is False
        assert body["api_place_order_called"] is False
        assert body["api_venue_call_called"] is False
        assert body["venue_order_ref"] == "venue_order:fake_ack"
        assert body["ack_ref"] == "ack:fake_guarded_submitter"
        _assert_compiler_coverage(body, entrypoint_ref="api:research_os.execution.order_submissions")
        qro = graph.qro(body["qro_id"])
        assert qro.output_contract["submitter_called"] is True
        assert qro.output_contract["order_materialization_ref"] == materialization.materialization_ref
        assert qro.output_contract["venue_capability_ref"] == capability.venue_capability_ref
        assert qro.output_contract["submit_request_ref"] == submit_request.submit_request_ref
        assert qro.output_contract["record_only"] is False
        assert qro.output_contract["api_place_order_called"] is False
        assert qro.output_contract["api_venue_call_called"] is False
        assert qro.output_contract["venue_order_ref"] == "venue_order:fake_ack"
        assert "raw_order" not in qro.output_contract
        assert "quantity" not in qro.output_contract
        assert "price" not in qro.output_contract
    finally:
        app_main.app.dependency_overrides.pop(require_user_dependency, None)


def test_execution_order_submission_run_disabled_without_write(tmp_path, monkeypatch):
    order_intent, runtime_promotion, materializations, safety_attestations, capabilities, _submissions, graph = _submission_test_state(tmp_path, monkeypatch)
    materialization = _record_ready_materialization(materializations, order_intent, runtime_promotion)
    capability = _record_ready_capability(capabilities, safety_attestations, order_intent, runtime_promotion)
    submit_request = _record_ready_submit_request(
        app_main.EXECUTION_SUBMIT_REQUESTS,
        order_intent,
        runtime_promotion,
        materialization,
        capability,
    )
    submission_path = tmp_path / "execution_order_submissions_run_disabled.jsonl"
    monkeypatch.setattr(app_main, "EXECUTION_ORDER_SUBMISSIONS", PersistentExecutionOrderSubmissionRegistry(submission_path))
    app_main.app.dependency_overrides[require_user_dependency] = lambda: SimpleNamespace(
        user_id="tester",
        username="tester",
    )
    try:
        client = TestClient(app_main.app)
        response = client.post(
            "/api/research-os/execution/order_submissions/run",
            json={"submit_request_ref": submit_request.submit_request_ref},
        )
        assert response.status_code == 422
        assert "guarded order submitter disabled" in response.text
        assert not submission_path.exists()
        assert graph.commands() == []
    finally:
        app_main.app.dependency_overrides.pop(require_user_dependency, None)


def test_execution_order_submission_run_calls_injected_guarded_submitter(tmp_path, monkeypatch):
    order_intent, runtime_promotion, materializations, safety_attestations, capabilities, _submissions, graph = _submission_test_state(tmp_path, monkeypatch)
    materialization = _record_ready_materialization(materializations, order_intent, runtime_promotion)
    capability = _record_ready_capability(
        capabilities,
        safety_attestations,
        order_intent,
        runtime_promotion,
        submitter_ref="guarded_submitter:runner_fake",
    )
    submit_request = _record_ready_submit_request(
        app_main.EXECUTION_SUBMIT_REQUESTS,
        order_intent,
        runtime_promotion,
        materialization,
        capability,
        submitter_ref="guarded_submitter:runner_fake",
    )

    class _FakeGuardedSubmitter:
        submitter_ref = "guarded_submitter:runner_fake"

        def __init__(self) -> None:
            self.calls = []

        def submit_guarded_order(self, **kwargs):
            self.calls.append(kwargs)
            return {
                "submitter_ref": self.submitter_ref,
                "submission_status": "submitted",
                "venue_order_ref": "venue_order:runner_fake_ack",
                "ack_ref": "ack:runner_fake_guarded_submitter",
                "evidence_refs": ["evidence:runner_fake_guarded_submitter_called"],
                "api_venue_call_called": False,
            }

    fake = _FakeGuardedSubmitter()
    monkeypatch.setattr(app_main, "EXECUTION_ORDER_SUBMITTER", fake)
    app_main.app.dependency_overrides[require_user_dependency] = lambda: SimpleNamespace(
        user_id="tester",
        username="tester",
    )
    try:
        client = TestClient(app_main.app)
        response = client.post(
            "/api/research-os/execution/order_submissions/run",
            json={"submit_request_ref": submit_request.submit_request_ref},
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert len(fake.calls) == 1
        assert fake.calls[0]["submit_request"].submit_request_ref == submit_request.submit_request_ref
        assert fake.calls[0]["submission"].submit_request_ref == submit_request.submit_request_ref
        assert body["submission_ref"].startswith("order_submission_")
        assert body["submit_request_ref"] == submit_request.submit_request_ref
        assert body["order_materialization_ref"] == materialization.materialization_ref
        assert body["venue_capability_ref"] == capability.venue_capability_ref
        assert body["submission_status"] == "submitted"
        assert body["submitter_ref"] == "guarded_submitter:runner_fake"
        assert body["submitter_called"] is True
        assert body["api_place_order_called"] is False
        assert body["api_venue_call_called"] is False
        assert body["venue_order_ref"] == "venue_order:runner_fake_ack"
        assert body["ack_ref"] == "ack:runner_fake_guarded_submitter"
        _assert_compiler_coverage(body, entrypoint_ref="api:research_os.execution.order_submissions")
        qro = graph.qro(body["qro_id"])
        assert qro.output_contract["submitter_called"] is True
        assert qro.output_contract["submit_request_ref"] == submit_request.submit_request_ref
        assert qro.output_contract["api_place_order_called"] is False
        assert qro.output_contract["api_venue_call_called"] is False
        assert "raw_order" not in qro.output_contract
        assert "quantity" not in qro.output_contract
        assert "price" not in qro.output_contract
    finally:
        app_main.app.dependency_overrides.pop(require_user_dependency, None)


def test_execution_order_submission_run_rejects_unsafe_submitter_result_without_write(tmp_path, monkeypatch):
    order_intent, runtime_promotion, materializations, safety_attestations, capabilities, _submissions, graph = _submission_test_state(tmp_path, monkeypatch)
    materialization = _record_ready_materialization(materializations, order_intent, runtime_promotion)
    capability = _record_ready_capability(capabilities, safety_attestations, order_intent, runtime_promotion)
    submit_request = _record_ready_submit_request(
        app_main.EXECUTION_SUBMIT_REQUESTS,
        order_intent,
        runtime_promotion,
        materialization,
        capability,
    )
    submission_path = tmp_path / "execution_order_submissions_run_unsafe_submitter.jsonl"
    monkeypatch.setattr(app_main, "EXECUTION_ORDER_SUBMISSIONS", PersistentExecutionOrderSubmissionRegistry(submission_path))

    class _UnsafeGuardedSubmitter:
        def submit_guarded_order(self, **kwargs):
            return {"raw_payload": {"quantity": 1, "price": 100}}

    monkeypatch.setattr(app_main, "EXECUTION_ORDER_SUBMITTER", _UnsafeGuardedSubmitter())
    app_main.app.dependency_overrides[require_user_dependency] = lambda: SimpleNamespace(
        user_id="tester",
        username="tester",
    )
    try:
        client = TestClient(app_main.app)
        response = client.post(
            "/api/research-os/execution/order_submissions/run",
            json={"submit_request_ref": submit_request.submit_request_ref},
        )
        assert response.status_code == 422
        assert "raw order" in response.text
        assert not submission_path.exists()
        assert graph.commands() == []
    finally:
        app_main.app.dependency_overrides.pop(require_user_dependency, None)


def test_execution_order_submission_run_rejects_direct_venue_call_report_without_write(tmp_path, monkeypatch):
    order_intent, runtime_promotion, materializations, safety_attestations, capabilities, _submissions, graph = _submission_test_state(tmp_path, monkeypatch)
    materialization = _record_ready_materialization(materializations, order_intent, runtime_promotion)
    capability = _record_ready_capability(capabilities, safety_attestations, order_intent, runtime_promotion)
    submit_request = _record_ready_submit_request(
        app_main.EXECUTION_SUBMIT_REQUESTS,
        order_intent,
        runtime_promotion,
        materialization,
        capability,
    )
    submission_path = tmp_path / "execution_order_submissions_run_direct_venue.jsonl"
    monkeypatch.setattr(app_main, "EXECUTION_ORDER_SUBMISSIONS", PersistentExecutionOrderSubmissionRegistry(submission_path))

    class _DirectVenueGuardedSubmitter:
        def submit_guarded_order(self, **kwargs):
            return {
                "submission_status": "submitted",
                "venue_order_ref": "venue_order:direct",
                "ack_ref": "ack:direct",
                "api_venue_call_called": True,
            }

    monkeypatch.setattr(app_main, "EXECUTION_ORDER_SUBMITTER", _DirectVenueGuardedSubmitter())
    app_main.app.dependency_overrides[require_user_dependency] = lambda: SimpleNamespace(
        user_id="tester",
        username="tester",
    )
    try:
        client = TestClient(app_main.app)
        response = client.post(
            "/api/research-os/execution/order_submissions/run",
            json={"submit_request_ref": submit_request.submit_request_ref},
        )
        assert response.status_code == 422
        assert "cannot call a venue API" in response.text
        assert not submission_path.exists()
        assert graph.commands() == []
    finally:
        app_main.app.dependency_overrides.pop(require_user_dependency, None)


def _submitted_ingester_state(tmp_path, monkeypatch):
    order_intent, runtime_promotion, materializations, safety_attestations, capabilities, submissions, graph = _submission_test_state(
        tmp_path,
        monkeypatch,
    )
    materialization = _record_ready_materialization(materializations, order_intent, runtime_promotion)
    capability = _record_ready_capability(capabilities, safety_attestations, order_intent, runtime_promotion)
    submit_request = _record_ready_submit_request(
        app_main.EXECUTION_SUBMIT_REQUESTS,
        order_intent,
        runtime_promotion,
        materialization,
        capability,
    )
    submission = _record_submitted_submission(
        submissions,
        order_intent,
        runtime_promotion,
        materialization,
        capability,
        submit_request,
    )
    return submission, graph


def test_execution_venue_event_run_disabled_without_write(tmp_path, monkeypatch):
    submission, graph = _submitted_ingester_state(tmp_path, monkeypatch)
    event_path = tmp_path / "execution_venue_events_run_disabled.jsonl"
    monkeypatch.setattr(app_main, "EXECUTION_VENUE_EVENTS", PersistentExecutionVenueEventRegistry(event_path))
    app_main.app.dependency_overrides[require_user_dependency] = lambda: SimpleNamespace(
        user_id="tester",
        username="tester",
    )
    try:
        client = TestClient(app_main.app)
        response = client.post(
            "/api/research-os/execution/venue_events/run",
            json={"submission_ref": submission.submission_ref},
        )
        assert response.status_code == 422
        assert "execution venue event ingester disabled" in response.text
        assert not event_path.exists()
        assert graph.commands() == []
    finally:
        app_main.app.dependency_overrides.pop(require_user_dependency, None)


def test_execution_venue_event_run_calls_injected_ingester(tmp_path, monkeypatch):
    submission, graph = _submitted_ingester_state(tmp_path, monkeypatch)

    class _FakeVenueEventIngester:
        ingester_ref = "venue_event_ingester:fake"

        def __init__(self) -> None:
            self.calls = []

        def ingest_event(self, *, submission, order_intent, runtime_promotion, actor):
            self.calls.append(
                {
                    "submission_ref": submission.submission_ref,
                    "order_intent_ref": order_intent.order_intent_ref,
                    "runtime_promotion_ref": runtime_promotion.runtime_promotion_ref,
                    "actor": actor,
                }
            )
            return {
                "ingester_ref": self.ingester_ref,
                "event_kind": "accepted",
                "status": "accepted",
                "venue_order_ref": submission.venue_order_ref,
                "client_order_ref": "client_order:idempotent",
                "ack_ref": submission.ack_ref,
                "raw_event_hash": "sha256:fake_venue_event",
                "evidence_refs": ["evidence:fake_venue_event_ingester_called"],
            }

    fake = _FakeVenueEventIngester()
    monkeypatch.setattr(app_main, "EXECUTION_VENUE_EVENT_INGESTER", fake)
    app_main.app.dependency_overrides[require_user_dependency] = lambda: SimpleNamespace(
        user_id="tester",
        username="tester",
    )
    try:
        client = TestClient(app_main.app)
        response = client.post(
            "/api/research-os/execution/venue_events/run",
            json={"submission_ref": submission.submission_ref},
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert len(fake.calls) == 1
        assert fake.calls[0]["submission_ref"] == submission.submission_ref
        assert body["venue_event_ref"].startswith("venue_event_")
        assert body["submission_ref"] == submission.submission_ref
        assert body["event_kind"] == "accepted"
        assert body["status"] == "accepted"
        assert body["ingester_ref"] == "venue_event_ingester:fake"
        assert body["ingester_called"] is True
        assert body["api_place_order_called"] is False
        assert body["api_venue_call_called"] is False
        _assert_compiler_coverage(body, entrypoint_ref="api:research_os.execution.venue_events")
        qro = graph.qro(body["qro_id"])
        assert qro.qro_type.value == "ExecutionPolicy"
        assert qro.output_contract["status"] == "venue_event_recorded"
        assert qro.output_contract["api_place_order_called"] is False
        assert qro.output_contract["api_venue_call_called"] is False
        assert "raw_order" not in qro.output_contract
        assert "quantity" not in qro.output_contract
        assert "price" not in qro.output_contract
    finally:
        app_main.app.dependency_overrides.pop(require_user_dependency, None)


def test_execution_venue_event_run_rejects_unsafe_ingester_result_without_write(tmp_path, monkeypatch):
    submission, graph = _submitted_ingester_state(tmp_path, monkeypatch)
    event_path = tmp_path / "execution_venue_events_run_unsafe.jsonl"
    monkeypatch.setattr(app_main, "EXECUTION_VENUE_EVENTS", PersistentExecutionVenueEventRegistry(event_path))

    class _UnsafeVenueEventIngester:
        def ingest_event(self, *, submission, order_intent, runtime_promotion, actor):
            return {"raw_payload": {"venue_order_id": "abc"}}

    monkeypatch.setattr(app_main, "EXECUTION_VENUE_EVENT_INGESTER", _UnsafeVenueEventIngester())
    app_main.app.dependency_overrides[require_user_dependency] = lambda: SimpleNamespace(
        user_id="tester",
        username="tester",
    )
    try:
        client = TestClient(app_main.app)
        response = client.post(
            "/api/research-os/execution/venue_events/run",
            json={"submission_ref": submission.submission_ref},
        )
        assert response.status_code == 422
        assert "raw order" in response.text
        assert not event_path.exists()
        assert graph.commands() == []
    finally:
        app_main.app.dependency_overrides.pop(require_user_dependency, None)


def test_execution_venue_event_run_rejects_direct_venue_call_report_without_write(tmp_path, monkeypatch):
    submission, graph = _submitted_ingester_state(tmp_path, monkeypatch)
    event_path = tmp_path / "execution_venue_events_run_direct_venue.jsonl"
    monkeypatch.setattr(app_main, "EXECUTION_VENUE_EVENTS", PersistentExecutionVenueEventRegistry(event_path))

    class _DirectVenueEventIngester:
        def ingest_event(self, *, submission, order_intent, runtime_promotion, actor):
            return {
                "event_kind": "accepted",
                "status": "accepted",
                "venue_order_ref": submission.venue_order_ref,
                "ack_ref": "ack:direct_venue_event",
                "api_venue_call_called": True,
            }

    monkeypatch.setattr(app_main, "EXECUTION_VENUE_EVENT_INGESTER", _DirectVenueEventIngester())
    app_main.app.dependency_overrides[require_user_dependency] = lambda: SimpleNamespace(
        user_id="tester",
        username="tester",
    )
    try:
        client = TestClient(app_main.app)
        response = client.post(
            "/api/research-os/execution/venue_events/run",
            json={"submission_ref": submission.submission_ref},
        )
        assert response.status_code == 422
        assert "cannot call a venue API" in response.text
        assert not event_path.exists()
        assert graph.commands() == []
    finally:
        app_main.app.dependency_overrides.pop(require_user_dependency, None)


def test_execution_venue_event_run_rejects_incomplete_fill_without_write(tmp_path, monkeypatch):
    submission, graph = _submitted_ingester_state(tmp_path, monkeypatch)
    event_path = tmp_path / "execution_venue_events_run_bad_fill.jsonl"
    monkeypatch.setattr(app_main, "EXECUTION_VENUE_EVENTS", PersistentExecutionVenueEventRegistry(event_path))

    class _IncompleteFillIngester:
        def ingest_event(self, *, submission, order_intent, runtime_promotion, actor):
            return {
                "event_kind": "filled",
                "status": "filled",
                "venue_order_ref": submission.venue_order_ref,
                "client_order_ref": "client_order:idempotent",
                "fill_ref": "fill:missing_refs",
                "raw_event_hash": "sha256:incomplete_fill",
                "evidence_refs": ["evidence:incomplete_fill"],
            }

    monkeypatch.setattr(app_main, "EXECUTION_VENUE_EVENT_INGESTER", _IncompleteFillIngester())
    app_main.app.dependency_overrides[require_user_dependency] = lambda: SimpleNamespace(
        user_id="tester",
        username="tester",
    )
    try:
        client = TestClient(app_main.app)
        response = client.post(
            "/api/research-os/execution/venue_events/run",
            json={"submission_ref": submission.submission_ref},
        )
        assert response.status_code == 422
        assert "venue_event_missing_fill_ref" in response.text
        assert not event_path.exists()
        assert graph.commands() == []
    finally:
        app_main.app.dependency_overrides.pop(require_user_dependency, None)


def test_execution_venue_event_registry_persists_and_replays(tmp_path):
    path = tmp_path / "execution_venue_events.jsonl"
    registry = PersistentExecutionVenueEventRegistry(path)
    submission = _submission(
        submit_enabled=True,
        submission_status="accepted",
        venue_order_ref="venue_order:abc",
        ack_ref="ack:abc",
        client_order_ref_hash=execution_client_order_ref_hash("client_order:idempotent"),
    )
    record = registry.record_event(
        _venue_event(submission_ref=submission.submission_ref),
        known_order_intent_refs={"order_intent:recorded"},
        known_runtime_promotion_refs={"runtime_promotion:recorded"},
        known_submission_refs={submission.submission_ref},
        submission=submission,
    )

    reloaded = PersistentExecutionVenueEventRegistry(path)

    assert reloaded.event(record.venue_event_ref).event_kind == "filled"
    assert reloaded.events()[0].venue_event_ref == record.venue_event_ref


def test_v2_formal_identities_reject_forged_or_stale_refs():
    promotion = _runtime_promotion()
    assert not validate_runtime_promotion_record(
        replace(promotion, runtime_promotion_ref="runtime_promotion_v2_forged")
    ).accepted
    assert not validate_runtime_promotion_record(
        replace(promotion, idempotency_key="idem:mutated", runtime_promotion_ref=promotion.runtime_promotion_ref)
    ).accepted

    submission = _submission()
    mutated_submission = replace(
        submission,
        audit_record_ref="audit:mutated",
        submission_ref=submission.submission_ref,
    )
    assert "order_submission_content_identity_mismatch" in _codes(
        validate_execution_order_submission(mutated_submission)
    )


def test_v2_registry_is_idempotent_across_concurrent_writers(tmp_path):
    path = tmp_path / "runtime_promotions.jsonl"
    record = _runtime_promotion()
    first = PersistentRuntimePromotionRegistry(path)
    second = PersistentRuntimePromotionRegistry(path)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda registry: registry.record_promotion(record), (first, second)))
    assert [item.runtime_promotion_ref for item in results] == [record.runtime_promotion_ref] * 2
    assert len(path.read_text(encoding="utf-8").splitlines()) == 1

    with pytest.raises(ValueError, match="identity collision"):
        first.record_promotion(
            replace(record, idempotency_key="idem:conflict", runtime_promotion_ref=record.runtime_promotion_ref)
        )


def test_strict_event_rejects_impossible_parent_state():
    submission = _submission(
        submit_enabled=True,
        submission_status="rejected",
        ack_ref="ack:rejected",
        client_order_ref_hash=execution_client_order_ref_hash("client_order:idempotent"),
    )
    event = _venue_event(
        submission_ref=submission.submission_ref,
        event_kind="accepted",
        status="accepted",
        ack_ref=submission.ack_ref,
    )
    decision = validate_execution_venue_event(
        event,
        known_submission_refs={submission.submission_ref},
        submission=submission,
    )
    assert "venue_event_submission_state_mismatch" in _codes(decision)


def test_strict_reconciliation_rejects_asserted_status_not_derived_from_events():
    submission = _submission(
        submit_enabled=True,
        submission_status="accepted",
        venue_order_ref="venue_order:abc",
        ack_ref="ack:abc",
        client_order_ref_hash=execution_client_order_ref_hash("client_order:idempotent"),
    )
    event = _venue_event(submission_ref=submission.submission_ref)
    canonical = reconcile_execution_venue_events(
        order_intent_ref=event.order_intent_ref,
        runtime_promotion_ref=event.runtime_promotion_ref,
        submission_ref=submission.submission_ref,
        venue_order_ref=event.venue_order_ref,
        audit_record_ref="audit:canonical",
        events=(event,),
    )
    forged = replace(
        canonical,
        status="reconciled",
        discrepancy_refs=(),
        action_required=False,
        reconciliation_ref="",
    )
    decision = validate_execution_reconciliation(
        forged,
        known_venue_event_refs={event.venue_event_ref},
        known_submission_refs={submission.submission_ref},
        submission=submission,
        venue_events=(event,),
    )
    assert "execution_reconcile_not_canonical" in _codes(decision)


def test_legacy_v1_event_replays_read_only_but_cannot_parent_a_strict_chain(tmp_path):
    path = tmp_path / "legacy_events.jsonl"
    legacy = replace(
        _venue_event(),
        submission_ref=None,
        venue_event_ref="venue_event_legacy_v1",
    )
    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "event_type": "execution_venue_event_recorded",
                "venue_event": legacy.to_dict(),
            },
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    registry = PersistentExecutionVenueEventRegistry(path)
    assert registry.event("venue_event_legacy_v1").submission_ref is None

    legacy_submission = _submission(
        submission_ref="order_submission_legacy_v1",
        submit_enabled=True,
        submission_status="accepted",
        venue_order_ref="venue_order:abc",
        ack_ref="ack:abc",
        client_order_ref_hash=execution_client_order_ref_hash("client_order:idempotent"),
    )
    with pytest.raises(ValueError, match="legacy_submission_parent"):
        registry.record_event(
            _venue_event(submission_ref=legacy_submission.submission_ref),
            known_order_intent_refs={legacy_submission.order_intent_ref},
            known_runtime_promotion_refs={legacy_submission.runtime_promotion_ref},
            known_submission_refs={legacy_submission.submission_ref},
            submission=legacy_submission,
        )


def test_legacy_rows_cannot_forge_reserved_v2_identity_namespaces(tmp_path):
    """Persisted schema provenance, not a caller-chosen ref prefix, defines v2 trust."""

    promotion = _runtime_promotion()
    submission = _submission()
    event = _venue_event()
    reconciliation = reconcile_execution_venue_events(
        order_intent_ref=event.order_intent_ref,
        runtime_promotion_ref=event.runtime_promotion_ref,
        submission_ref=event.submission_ref,
        venue_order_ref=event.venue_order_ref,
        audit_record_ref="audit:legacy-v2-forgery",
        events=(event,),
    )
    cases = (
        (
            "runtime_promotions.jsonl",
            "runtime_promotion_recorded",
            "runtime_promotion",
            promotion,
            PersistentRuntimePromotionRegistry,
            "runtime_promotion_v2_",
        ),
        (
            "submissions.jsonl",
            "execution_order_submission_recorded",
            "order_submission",
            submission,
            PersistentExecutionOrderSubmissionRegistry,
            "order_submission_v2_",
        ),
        (
            "events.jsonl",
            "execution_venue_event_recorded",
            "venue_event",
            event,
            PersistentExecutionVenueEventRegistry,
            "venue_event_v2_",
        ),
        (
            "reconciliations.jsonl",
            "execution_reconciliation_recorded",
            "reconciliation",
            reconciliation,
            PersistentExecutionReconciliationRegistry,
            "execution_reconcile_v2_",
        ),
    )

    for filename, event_type, payload_key, record, registry_type, prefix in cases:
        ref = next(
            str(value)
            for name, value in record.to_dict().items()
            if name.endswith("_ref") and str(value).startswith(prefix)
        )
        assert ref.startswith(prefix)
        path = tmp_path / filename
        path.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "event_type": event_type,
                    payload_key: record.to_dict(),
                },
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
        with pytest.raises(ValueError, match="invalid persisted") as exc_info:
            registry_type(path)
        assert "cannot claim reserved v2 identity" in str(exc_info.value.__cause__)


def test_execution_venue_event_api_records_qro_without_calling_venue(tmp_path, monkeypatch):
    submission, graph = _submitted_ingester_state(tmp_path, monkeypatch)
    venue_events = PersistentExecutionVenueEventRegistry(tmp_path / "execution_venue_events.jsonl")
    monkeypatch.setattr(app_main, "EXECUTION_VENUE_EVENTS", venue_events)
    app_main.app.dependency_overrides[require_user_dependency] = lambda: SimpleNamespace(
        user_id="tester",
        username="tester",
    )
    try:
        client = TestClient(app_main.app)
        payload = _venue_event(
            order_intent_ref=submission.order_intent_ref,
            runtime_promotion_ref=submission.runtime_promotion_ref,
            submission_ref=submission.submission_ref,
            venue_ref=submission.venue_ref,
            venue_order_ref=submission.venue_order_ref,
            ack_ref=submission.ack_ref,
            order_guard_ref=submission.order_guard_ref,
            idempotency_key=submission.idempotency_key,
        ).to_dict()
        response = client.post("/api/research-os/execution/venue_events", json=payload)
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["venue_event_ref"].startswith("venue_event_")
        assert body["qro_id"].startswith("qro_")
        assert body["research_graph_command_id"].startswith("rgcmd_")
        _assert_compiler_coverage(body, entrypoint_ref="api:research_os.execution.venue_events")
        assert body["record_only"] is True
        assert body["api_place_order_called"] is False
        assert body["api_venue_call_called"] is False
        qro = graph.qro(body["qro_id"])
        assert qro.qro_type.value == "ExecutionPolicy"
        assert qro.output_contract["record_only"] is True
        assert qro.output_contract["api_place_order_called"] is False
        assert qro.output_contract["api_venue_call_called"] is False
        assert "raw_order" not in qro.output_contract
        assert "filled_qty" not in qro.output_contract

        summary = client.get("/api/research-os/execution/venue_events/summary")
        assert summary.status_code == 200
        row = summary.json()["venue_events"][0]
        assert row["order_intent_ref"] == submission.order_intent_ref
        assert row["runtime_promotion_ref"] == submission.runtime_promotion_ref
        assert row["submission_ref"] == submission.submission_ref
        assert "raw_order" not in row
        assert "filled_qty" not in row
    finally:
        app_main.app.dependency_overrides.pop(require_user_dependency, None)


def test_execution_venue_event_api_rejects_invalid_fill_without_write(tmp_path, monkeypatch):
    submission, graph = _submitted_ingester_state(tmp_path, monkeypatch)
    venue_event_path = tmp_path / "execution_venue_events.jsonl"
    monkeypatch.setattr(app_main, "EXECUTION_VENUE_EVENTS", PersistentExecutionVenueEventRegistry(venue_event_path))
    app_main.app.dependency_overrides[require_user_dependency] = lambda: SimpleNamespace(
        user_id="tester",
        username="tester",
    )
    try:
        client = TestClient(app_main.app)
        payload = _venue_event(
            order_intent_ref=submission.order_intent_ref,
            runtime_promotion_ref=submission.runtime_promotion_ref,
            submission_ref=submission.submission_ref,
            venue_ref=submission.venue_ref,
            venue_order_ref=submission.venue_order_ref,
            ack_ref=submission.ack_ref,
            order_guard_ref=submission.order_guard_ref,
            idempotency_key=submission.idempotency_key,
            price_ref=None,
        ).to_dict()
        response = client.post("/api/research-os/execution/venue_events", json=payload)
        assert response.status_code == 422
        assert "venue_event_missing_fill_ref" in response.text
        assert not venue_event_path.exists()
        assert graph.commands() == []
    finally:
        app_main.app.dependency_overrides.pop(require_user_dependency, None)


def test_execution_venue_event_api_rejects_raw_event_payload_without_write(tmp_path, monkeypatch):
    order_intents = PersistentExecutionOrderIntentRegistry(tmp_path / "execution_order_intents.jsonl")
    order_intent = order_intents.record_intent(
        _order_intent(),
        known_signal_validation_refs={"signal_validation:accepted"},
    )
    runtime_promotions = PersistentRuntimePromotionRegistry(tmp_path / "runtime_promotions.jsonl")
    runtime_promotion = runtime_promotions.record_promotion(_runtime_promotion())
    venue_event_path = tmp_path / "execution_venue_events.jsonl"
    monkeypatch.setattr(app_main, "EXECUTION_ORDER_INTENTS", order_intents)
    monkeypatch.setattr(app_main, "RUNTIME_PROMOTIONS", runtime_promotions)
    monkeypatch.setattr(app_main, "EXECUTION_VENUE_EVENTS", PersistentExecutionVenueEventRegistry(venue_event_path))
    app_main.app.dependency_overrides[require_user_dependency] = lambda: SimpleNamespace(
        user_id="tester",
        username="tester",
    )
    try:
        client = TestClient(app_main.app)
        payload = _venue_event(
            order_intent_ref=order_intent.order_intent_ref,
            runtime_promotion_ref=runtime_promotion.runtime_promotion_ref,
        ).to_dict()
        payload["raw_event"] = {"filled_qty": 1, "fill_price": 100}
        response = client.post("/api/research-os/execution/venue_events", json=payload)
        assert response.status_code == 422
        assert "raw order" in response.text
        assert not venue_event_path.exists()
    finally:
        app_main.app.dependency_overrides.pop(require_user_dependency, None)


def _reconciliation_test_state(tmp_path, monkeypatch):
    submission, graph = _submitted_ingester_state(tmp_path, monkeypatch)
    order_intent = app_main.EXECUTION_ORDER_INTENTS.intent(submission.order_intent_ref)
    runtime_promotion = app_main.RUNTIME_PROMOTIONS.promotion(submission.runtime_promotion_ref)
    venue_events = PersistentExecutionVenueEventRegistry(tmp_path / "execution_venue_events.jsonl")
    reconciliations = PersistentExecutionReconciliationRegistry(tmp_path / "execution_reconciliations.jsonl")
    reconciliation_actions = PersistentExecutionReconciliationActionRegistry(tmp_path / "execution_reconciliation_actions.jsonl")
    monkeypatch.setattr(app_main, "EXECUTION_VENUE_EVENTS", venue_events)
    monkeypatch.setattr(app_main, "EXECUTION_RECONCILIATIONS", reconciliations)
    monkeypatch.setattr(app_main, "EXECUTION_RECONCILIATION_ACTIONS", reconciliation_actions)
    monkeypatch.setattr(app_main, "RESEARCH_GRAPH_STORE", graph)
    _patch_compiler_coverage(tmp_path, monkeypatch)
    return order_intent, runtime_promotion, venue_events, graph


def _record_reconciliation_event(venue_events, order_intent, runtime_promotion, **overrides):
    submission = app_main.EXECUTION_ORDER_SUBMISSIONS.submissions()[0]
    record = _venue_event(
        order_intent_ref=order_intent.order_intent_ref,
        runtime_promotion_ref=runtime_promotion.runtime_promotion_ref,
        submission_ref=submission.submission_ref,
        venue_ref=submission.venue_ref,
        venue_order_ref=submission.venue_order_ref,
        client_order_ref="client_order:idempotent",
        ack_ref=submission.ack_ref,
        order_guard_ref=submission.order_guard_ref,
        idempotency_key=submission.idempotency_key,
        **overrides,
    )
    return venue_events.record_event(
        record,
        known_order_intent_refs={order_intent.order_intent_ref},
        known_runtime_promotion_refs={runtime_promotion.runtime_promotion_ref},
        known_submission_refs={submission.submission_ref},
        submission=submission,
    )


def test_execution_reconciliation_api_closes_filled_reconciled_events_without_calling_venue(tmp_path, monkeypatch):
    order_intent, runtime_promotion, venue_events, graph = _reconciliation_test_state(tmp_path, monkeypatch)
    _record_reconciliation_event(venue_events, order_intent, runtime_promotion)
    _record_reconciliation_event(
        venue_events,
        order_intent,
        runtime_promotion,
        event_kind="reconciled",
        status="reconciled",
    )
    app_main.app.dependency_overrides[require_user_dependency] = lambda: SimpleNamespace(
        user_id="tester",
        username="tester",
    )
    try:
        client = TestClient(app_main.app)
        response = client.post(
            "/api/research-os/execution/reconciliations",
            json={
                "order_intent_ref": order_intent.order_intent_ref,
                "runtime_promotion_ref": runtime_promotion.runtime_promotion_ref,
                "submission_ref": app_main.EXECUTION_ORDER_SUBMISSIONS.submissions()[0].submission_ref,
                "venue_order_ref": app_main.EXECUTION_ORDER_SUBMISSIONS.submissions()[0].venue_order_ref,
                "audit_record_ref": "audit:reconcile:001",
            },
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["status"] == "reconciled"
        assert body["action_required"] is False
        assert body["api_place_order_called"] is False
        assert body["api_venue_call_called"] is False
        _assert_compiler_coverage(body, entrypoint_ref="api:research_os.execution.reconciliations")
        qro = graph.qro(body["qro_id"])
        assert qro.output_contract["reconciliation_status"] == "reconciled"
        assert qro.output_contract["action_required"] is False
        assert qro.output_contract["api_place_order_called"] is False
        assert qro.output_contract["api_venue_call_called"] is False
        assert "raw_order" not in qro.output_contract
        assert "filled_qty" not in qro.output_contract

        summary = client.get("/api/research-os/execution/reconciliations/summary")
        assert summary.status_code == 200
        row = summary.json()["reconciliations"][0]
        assert row["status"] == "reconciled"
        assert row["action_required"] is False
    finally:
        app_main.app.dependency_overrides.pop(require_user_dependency, None)


def test_execution_reconciliation_api_records_missing_reconcile_as_action_required(tmp_path, monkeypatch):
    order_intent, runtime_promotion, venue_events, graph = _reconciliation_test_state(tmp_path, monkeypatch)
    _record_reconciliation_event(venue_events, order_intent, runtime_promotion)
    app_main.app.dependency_overrides[require_user_dependency] = lambda: SimpleNamespace(
        user_id="tester",
        username="tester",
    )
    try:
        client = TestClient(app_main.app)
        response = client.post(
            "/api/research-os/execution/reconciliations",
            json={
                "order_intent_ref": order_intent.order_intent_ref,
                "runtime_promotion_ref": runtime_promotion.runtime_promotion_ref,
                "submission_ref": app_main.EXECUTION_ORDER_SUBMISSIONS.submissions()[0].submission_ref,
                "venue_order_ref": app_main.EXECUTION_ORDER_SUBMISSIONS.submissions()[0].venue_order_ref,
                "audit_record_ref": "audit:reconcile:002",
            },
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["status"] == "needs_reconcile"
        assert body["action_required"] is True
        assert "missing_reconcile_event" in body["discrepancy_refs"]
        _assert_compiler_coverage(body, entrypoint_ref="api:research_os.execution.reconciliations")
        qro = graph.qro(body["qro_id"])
        assert qro.output_contract["reconciliation_status"] == "needs_reconcile"
        assert qro.output_contract["action_required"] is True
    finally:
        app_main.app.dependency_overrides.pop(require_user_dependency, None)


def test_execution_reconciliation_api_rejects_unknown_order_intent_without_write(tmp_path, monkeypatch):
    _order_intent, _runtime_promotion, _venue_events, graph = _reconciliation_test_state(tmp_path, monkeypatch)
    reconcile_path = tmp_path / "execution_reconciliations_reject.jsonl"
    monkeypatch.setattr(app_main, "EXECUTION_RECONCILIATIONS", PersistentExecutionReconciliationRegistry(reconcile_path))
    app_main.app.dependency_overrides[require_user_dependency] = lambda: SimpleNamespace(
        user_id="tester",
        username="tester",
    )
    try:
        client = TestClient(app_main.app)
        response = client.post(
            "/api/research-os/execution/reconciliations",
            json={
                "order_intent_ref": "order_intent:missing",
                "runtime_promotion_ref": _runtime_promotion.runtime_promotion_ref,
                "submission_ref": app_main.EXECUTION_ORDER_SUBMISSIONS.submissions()[0].submission_ref,
                "audit_record_ref": "audit:reconcile:reject",
            },
        )
        assert response.status_code == 422
        assert "unknown execution order intent" in response.text
        assert not reconcile_path.exists()
        assert graph.commands() == []
    finally:
        app_main.app.dependency_overrides.pop(require_user_dependency, None)


def test_execution_reconciliation_batch_worker_is_idempotent(tmp_path, monkeypatch):
    order_intent, runtime_promotion, venue_events, graph = _reconciliation_test_state(tmp_path, monkeypatch)
    _record_reconciliation_event(venue_events, order_intent, runtime_promotion)
    app_main.app.dependency_overrides[require_user_dependency] = lambda: SimpleNamespace(
        user_id="tester",
        username="tester",
    )
    try:
        client = TestClient(app_main.app)
        first = client.post(
            "/api/research-os/execution/reconciliations/run_pending",
            json={"audit_record_ref": "audit:reconcile:batch"},
        )
        assert first.status_code == 200, first.text
        first_body = first.json()
        assert first_body["group_total"] == 1
        assert first_body["created_count"] == 1
        assert first_body["skipped_count"] == 0
        assert first_body["api_place_order_called"] is False
        assert first_body["api_venue_call_called"] is False
        created = first_body["created"][0]
        assert created["status"] == "needs_reconcile"
        assert created["action_required"] is True
        assert created["qro_id"].startswith("qro_")
        assert graph.qro(created["qro_id"]).output_contract["reconciliation_status"] == "needs_reconcile"

        second = client.post(
            "/api/research-os/execution/reconciliations/run_pending",
            json={"audit_record_ref": "audit:reconcile:batch"},
        )
        assert second.status_code == 200
        second_body = second.json()
        assert second_body["created_count"] == 0
        assert second_body["skipped_count"] == 1
    finally:
        app_main.app.dependency_overrides.pop(require_user_dependency, None)


def test_execution_reconciliation_action_api_records_follow_up_without_calling_venue(tmp_path, monkeypatch):
    order_intent, runtime_promotion, venue_events, graph = _reconciliation_test_state(tmp_path, monkeypatch)
    _record_reconciliation_event(venue_events, order_intent, runtime_promotion)
    app_main.app.dependency_overrides[require_user_dependency] = lambda: SimpleNamespace(
        user_id="tester",
        username="tester",
    )
    try:
        client = TestClient(app_main.app)
        reconciliation = client.post(
            "/api/research-os/execution/reconciliations",
            json={
                "order_intent_ref": order_intent.order_intent_ref,
                "runtime_promotion_ref": runtime_promotion.runtime_promotion_ref,
                "submission_ref": app_main.EXECUTION_ORDER_SUBMISSIONS.submissions()[0].submission_ref,
                "venue_order_ref": app_main.EXECUTION_ORDER_SUBMISSIONS.submissions()[0].venue_order_ref,
                "audit_record_ref": "audit:reconcile:action",
            },
        )
        assert reconciliation.status_code == 200, reconciliation.text
        reconciliation_body = reconciliation.json()
        assert reconciliation_body["action_required"] is True

        response = client.post(
            "/api/research-os/execution/reconciliation_actions",
            json={
                "reconciliation_ref": reconciliation_body["reconciliation_ref"],
                "action_kind": "request_missing_reconcile",
                "action_status": "open",
                    "action_owner_ref": "execution-owner:tester",
                "audit_record_ref": "audit:reconcile_action:001",
                "remediation_ref": "remediation:request_missing_reconcile:001",
                "evidence_refs": ["evidence:monitor:missing_reconcile"],
            },
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["action_kind"] == "request_missing_reconcile"
        assert body["action_status"] == "open"
        assert body["api_place_order_called"] is False
        assert body["api_venue_call_called"] is False
        _assert_compiler_coverage(body, entrypoint_ref="api:research_os.execution.reconciliation_actions")
        qro = graph.qro(body["qro_id"])
        assert qro.output_contract["status"] == "execution_reconciliation_action_recorded"
        assert qro.output_contract["action_kind"] == "request_missing_reconcile"
        assert qro.output_contract["action_required"] is True
        assert qro.output_contract["api_place_order_called"] is False
        assert qro.output_contract["api_venue_call_called"] is False
        assert "raw_order" not in qro.output_contract
        assert "fill_price" not in qro.output_contract

        summary = client.get("/api/research-os/execution/reconciliation_actions/summary")
        assert summary.status_code == 200
        assert summary.json()["reconciliation_action_total"] == 1
    finally:
        app_main.app.dependency_overrides.pop(require_user_dependency, None)


def test_execution_reconciliation_action_api_rejects_clean_reconciliation_without_write(tmp_path, monkeypatch):
    order_intent, runtime_promotion, venue_events, graph = _reconciliation_test_state(tmp_path, monkeypatch)
    actions_path = tmp_path / "execution_reconciliation_actions.jsonl"
    _record_reconciliation_event(venue_events, order_intent, runtime_promotion)
    _record_reconciliation_event(
        venue_events,
        order_intent,
        runtime_promotion,
        event_kind="reconciled",
        status="reconciled",
    )
    app_main.app.dependency_overrides[require_user_dependency] = lambda: SimpleNamespace(
        user_id="tester",
        username="tester",
    )
    try:
        client = TestClient(app_main.app)
        reconciliation = client.post(
            "/api/research-os/execution/reconciliations",
            json={
                "order_intent_ref": order_intent.order_intent_ref,
                "runtime_promotion_ref": runtime_promotion.runtime_promotion_ref,
                "submission_ref": app_main.EXECUTION_ORDER_SUBMISSIONS.submissions()[0].submission_ref,
                "venue_order_ref": app_main.EXECUTION_ORDER_SUBMISSIONS.submissions()[0].venue_order_ref,
                "audit_record_ref": "audit:reconcile:clean",
            },
        )
        assert reconciliation.status_code == 200, reconciliation.text
        reconciliation_body = reconciliation.json()
        assert reconciliation_body["action_required"] is False
        command_count = len(graph.commands())

        response = client.post(
            "/api/research-os/execution/reconciliation_actions",
            json={
                "reconciliation_ref": reconciliation_body["reconciliation_ref"],
                "action_kind": "investigate",
                "action_status": "open",
                "audit_record_ref": "audit:reconcile_action:clean",
                "evidence_refs": ["evidence:clean_should_not_act"],
            },
        )
        assert response.status_code == 422
        assert "execution_reconcile_action_not_required" in response.text
        assert not actions_path.exists()
        assert len(graph.commands()) == command_count
    finally:
        app_main.app.dependency_overrides.pop(require_user_dependency, None)


def test_execution_reconciliation_action_batch_worker_is_idempotent(tmp_path, monkeypatch):
    order_intent, runtime_promotion, venue_events, graph = _reconciliation_test_state(tmp_path, monkeypatch)
    _record_reconciliation_event(venue_events, order_intent, runtime_promotion)
    app_main.app.dependency_overrides[require_user_dependency] = lambda: SimpleNamespace(
        user_id="tester",
        username="tester",
    )
    try:
        client = TestClient(app_main.app)
        reconciliation = client.post(
            "/api/research-os/execution/reconciliations/run_pending",
            json={"audit_record_ref": "audit:reconcile:batch_action_source"},
        )
        assert reconciliation.status_code == 200, reconciliation.text
        assert reconciliation.json()["created_count"] == 1

        first = client.post(
            "/api/research-os/execution/reconciliation_actions/run_pending",
            json={
                "audit_record_ref": "audit:reconcile_action:batch",
                "action_owner_ref": "execution-owner:tester",
                "evidence_refs": ["evidence:monitor:batch"],
            },
        )
        assert first.status_code == 200, first.text
        first_body = first.json()
        assert first_body["pending_total"] == 1
        assert first_body["created_count"] == 1
        assert first_body["skipped_count"] == 0
        assert first_body["api_place_order_called"] is False
        assert first_body["api_venue_call_called"] is False
        created = first_body["created"][0]
        assert created["action_kind"] == "request_missing_reconcile"
        assert created["action_status"] == "open"
        qro = graph.qro(created["qro_id"])
        assert qro.output_contract["status"] == "execution_reconciliation_action_recorded"
        assert qro.output_contract["action_kind"] == "request_missing_reconcile"
        assert qro.output_contract["api_place_order_called"] is False
        assert qro.output_contract["api_venue_call_called"] is False

        second = client.post(
            "/api/research-os/execution/reconciliation_actions/run_pending",
            json={"audit_record_ref": "audit:reconcile_action:batch"},
        )
        assert second.status_code == 200
        second_body = second.json()
        assert second_body["created_count"] == 0
        assert second_body["skipped_count"] == 1
    finally:
        app_main.app.dependency_overrides.pop(require_user_dependency, None)


def test_execution_reconciliation_action_batch_repairs_post_append_qro_failure(
    tmp_path,
    monkeypatch,
):
    order_intent, runtime_promotion, venue_events, graph = _reconciliation_test_state(
        tmp_path,
        monkeypatch,
    )
    _record_reconciliation_event(venue_events, order_intent, runtime_promotion)
    app_main.app.dependency_overrides[require_user_dependency] = lambda: SimpleNamespace(
        user_id="tester",
        username="tester",
    )
    try:
        client = TestClient(app_main.app)
        reconciliation = client.post(
            "/api/research-os/execution/reconciliations/run_pending",
            json={"audit_record_ref": "audit:reconcile:qro_repair_source"},
        )
        assert reconciliation.status_code == 200, reconciliation.text
        assert reconciliation.json()["created_count"] == 1

        original = app_main._record_execution_reconciliation_action_qro

        def fail_after_action_append(*_args, **_kwargs):
            raise RuntimeError("injected action QRO failure after durable append")

        monkeypatch.setattr(
            app_main,
            "_record_execution_reconciliation_action_qro",
            fail_after_action_append,
        )
        graph_count = len(graph.commands())
        with pytest.raises(RuntimeError, match="injected action QRO failure"):
            client.post(
                "/api/research-os/execution/reconciliation_actions/run_pending",
                json={"audit_record_ref": "audit:reconcile_action:qro_repair"},
            )
        assert len(app_main.EXECUTION_RECONCILIATION_ACTIONS.actions()) == 1
        assert len(graph.commands()) == graph_count

        monkeypatch.setattr(
            app_main,
            "EXECUTION_RECONCILIATION_ACTIONS",
            PersistentExecutionReconciliationActionRegistry(
                tmp_path / "execution_reconciliation_actions.jsonl"
            ),
        )
        restarted_graph = ResearchGraphStore()
        _patch_compiler_coverage(
            tmp_path,
            monkeypatch,
            graph=restarted_graph,
        )
        monkeypatch.setattr(
            app_main,
            "_record_execution_reconciliation_action_qro",
            original,
        )
        retry = client.post(
            "/api/research-os/execution/reconciliation_actions/run_pending",
            json={"audit_record_ref": "audit:reconcile_action:qro_repair"},
        )

        assert retry.status_code == 200, retry.text
        body = retry.json()
        assert body["created_count"] == 0
        assert body["repaired_count"] == 1
        assert body["skipped_count"] == 0
        assert len(app_main.EXECUTION_RECONCILIATION_ACTIONS.actions()) == 1
        assert len(restarted_graph.commands()) == 1
        assert body["repaired"][0]["qro_id"].startswith("qro_")
        _assert_compiler_coverage(
            body["repaired"][0],
            entrypoint_ref="api:research_os.execution.reconciliation_actions",
        )
    finally:
        app_main.app.dependency_overrides.pop(require_user_dependency, None)


def test_execution_reconciliation_action_batch_repairs_graph_without_compiler_after_restart(
    tmp_path,
    monkeypatch,
):
    order_intent, runtime_promotion, venue_events, _graph = _reconciliation_test_state(
        tmp_path,
        monkeypatch,
    )
    graph_path = tmp_path / "reconciliation_action_graph.jsonl"
    _patch_compiler_coverage(
        tmp_path,
        monkeypatch,
        graph=PersistentResearchGraphStore(graph_path),
    )
    _record_reconciliation_event(venue_events, order_intent, runtime_promotion)
    app_main.app.dependency_overrides[require_user_dependency] = lambda: SimpleNamespace(
        user_id="tester",
        username="tester",
    )
    try:
        client = TestClient(app_main.app)
        reconciliation = client.post(
            "/api/research-os/execution/reconciliations/run_pending",
            json={"audit_record_ref": "audit:reconcile:compiler_repair_source"},
        )
        assert reconciliation.status_code == 200, reconciliation.text

        original_compile = app_main._compile_execution_boundary_qro

        def fail_action_compiler(*args, **kwargs):
            if kwargs.get("entrypoint_ref") == app_main._RECONCILIATION_ACTION_ENTRYPOINT:
                raise RuntimeError("injected action compiler failure after graph append")
            return original_compile(*args, **kwargs)

        monkeypatch.setattr(app_main, "_compile_execution_boundary_qro", fail_action_compiler)
        with pytest.raises(RuntimeError, match="injected action compiler failure"):
            client.post(
                "/api/research-os/execution/reconciliation_actions/run_pending",
                json={"audit_record_ref": "audit:reconcile_action:compiler_repair"},
            )
        assert len(app_main.EXECUTION_RECONCILIATION_ACTIONS.actions()) == 1
        assert len(
            app_main.RESEARCH_GRAPH_STORE.projection_index(
                lineage_token=app_main.EXECUTION_RECONCILIATION_ACTIONS.actions()[0].action_ref
            )
        ) == 1

        monkeypatch.setattr(
            app_main,
            "EXECUTION_RECONCILIATION_ACTIONS",
            PersistentExecutionReconciliationActionRegistry(
                tmp_path / "execution_reconciliation_actions.jsonl"
            ),
        )
        _patch_compiler_coverage(
            tmp_path,
            monkeypatch,
            graph=PersistentResearchGraphStore(graph_path),
        )
        monkeypatch.setattr(app_main, "_compile_execution_boundary_qro", original_compile)
        retry = client.post(
            "/api/research-os/execution/reconciliation_actions/run_pending",
            json={"audit_record_ref": "audit:reconcile_action:compiler_repair"},
        )

        assert retry.status_code == 200, retry.text
        body = retry.json()
        assert body["created_count"] == 0
        assert body["repaired_count"] == 1
        assert body["skipped_count"] == 0
        assert len(app_main.EXECUTION_RECONCILIATION_ACTIONS.actions()) == 1
        assert app_main._execution_reconciliation_action_delivery_refs(
            app_main.EXECUTION_RECONCILIATION_ACTIONS.actions()[0]
        ) == {
            key: body["repaired"][0][key]
            for key in (
                "qro_id",
                "research_graph_command_id",
                "compiler_ir_ref",
                "compiler_pass_ref",
                "entrypoint_coverage_ref",
            )
        }
    finally:
        app_main.app.dependency_overrides.pop(require_user_dependency, None)


def test_formal_execution_http_scope_hides_foreign_testnet_submission_and_events(
    tmp_path,
    monkeypatch,
):
    owned_submission, _graph = _submitted_ingester_state(tmp_path, monkeypatch)
    order_intent = app_main.EXECUTION_ORDER_INTENTS.intent(owned_submission.order_intent_ref)
    runtime_promotion = app_main.RUNTIME_PROMOTIONS.promotion(
        owned_submission.runtime_promotion_ref
    )
    materialization = app_main.EXECUTION_ORDER_MATERIALIZATIONS.materialization(
        owned_submission.order_materialization_ref
    )
    capability = app_main.EXECUTION_VENUE_CAPABILITIES.capability(
        owned_submission.venue_capability_ref
    )
    submit_request = app_main.EXECUTION_SUBMIT_REQUESTS.request(
        owned_submission.submit_request_ref
    )
    foreign_submission = _record_submitted_submission(
        app_main.EXECUTION_ORDER_SUBMISSIONS,
        order_intent,
        runtime_promotion,
        materialization,
        capability,
        submit_request,
        recorded_by="bob",
    )
    venue_events = PersistentExecutionVenueEventRegistry(
        tmp_path / "owner_scoped_execution_venue_events.jsonl"
    )
    monkeypatch.setattr(app_main, "EXECUTION_VENUE_EVENTS", venue_events)
    for submission, owner in (
        (owned_submission, "tester"),
        (foreign_submission, "bob"),
    ):
        event = _venue_event(
            order_intent_ref=submission.order_intent_ref,
            runtime_promotion_ref=submission.runtime_promotion_ref,
            submission_ref=submission.submission_ref,
            venue_ref=submission.venue_ref,
            venue_order_ref=submission.venue_order_ref,
            ack_ref=submission.ack_ref,
            order_guard_ref=submission.order_guard_ref,
            idempotency_key=submission.idempotency_key,
            recorded_by=owner,
        )
        venue_events.record_event(
            event,
            known_order_intent_refs={submission.order_intent_ref},
            known_runtime_promotion_refs={submission.runtime_promotion_ref},
            known_submission_refs={submission.submission_ref},
            submission=submission,
        )

    app_main.app.dependency_overrides[require_user_dependency] = lambda: SimpleNamespace(
        user_id="tester",
        username="bob",
    )
    try:
        client = TestClient(app_main.app)
        submissions = client.get(
            "/api/research-os/execution/order_submissions/summary"
        )
        assert submissions.status_code == 200, submissions.text
        assert submissions.json()["user"] == "tester"
        assert [
            row["submission_ref"] for row in submissions.json()["order_submissions"]
        ] == [owned_submission.submission_ref]

        events = client.get("/api/research-os/execution/venue_events/summary")
        assert events.status_code == 200, events.text
        assert [row["submission_ref"] for row in events.json()["venue_events"]] == [
            owned_submission.submission_ref
        ]

        foreign_payload = _venue_event(
            order_intent_ref=foreign_submission.order_intent_ref,
            runtime_promotion_ref=foreign_submission.runtime_promotion_ref,
            submission_ref=foreign_submission.submission_ref,
            venue_ref=foreign_submission.venue_ref,
            venue_order_ref=foreign_submission.venue_order_ref,
            ack_ref=foreign_submission.ack_ref,
            order_guard_ref=foreign_submission.order_guard_ref,
            idempotency_key=foreign_submission.idempotency_key,
            recorded_by="tester",
            event_kind="accepted",
            status="accepted",
            fill_ref=None,
            quantity_ref=None,
            price_ref=None,
            fee_ref=None,
        ).to_dict()
        denied = client.post(
            "/api/research-os/execution/venue_events",
            json=foreign_payload,
        )
        assert denied.status_code == 404
        assert denied.json()["detail"] == "execution record not found"

        missing_parent_payload = {
            **foreign_payload,
            "order_intent_ref": "order_intent_missing_owner_oracle",
            "runtime_promotion_ref": "runtime_promotion_missing_owner_oracle",
        }
        missing_parent = client.post(
            "/api/research-os/execution/venue_events",
            json=missing_parent_payload,
        )
        assert missing_parent.status_code == denied.status_code
        assert missing_parent.json() == denied.json()
    finally:
        app_main.app.dependency_overrides.pop(require_user_dependency, None)


def test_formal_execution_pre_submission_parent_is_owner_scoped(
    tmp_path,
    monkeypatch,
):
    (
        order_intent,
        runtime_promotion,
        materializations,
        _safety,
        _capabilities,
        _submissions,
        graph,
    ) = _submission_test_state(tmp_path, monkeypatch)
    app_main.app.dependency_overrides[require_user_dependency] = lambda: SimpleNamespace(
        user_id="bob",
        username="tester",
    )
    try:
        response = TestClient(app_main.app).post(
            "/api/research-os/execution/order_materializations",
            json=_materialization(
                order_intent_ref=order_intent.order_intent_ref,
                runtime_promotion_ref=runtime_promotion.runtime_promotion_ref,
                materialize_enabled=False,
                recorded_by="bob",
            ).to_dict(),
        )
        assert response.status_code == 404
        assert response.json()["detail"] == "execution record not found"
        missing = TestClient(app_main.app).post(
            "/api/research-os/execution/order_materializations",
            json=_materialization(
                order_intent_ref="order_intent_missing_owner_probe",
                runtime_promotion_ref=runtime_promotion.runtime_promotion_ref,
                materialize_enabled=False,
                recorded_by="bob",
            ).to_dict(),
        )
        assert missing.status_code == 404
        assert missing.json()["detail"] == response.json()["detail"]
        assert materializations.materializations() == []
        assert graph.commands() == []
    finally:
        app_main.app.dependency_overrides.pop(require_user_dependency, None)


def test_order_submission_runner_hides_foreign_live_and_missing_refs_equally(monkeypatch):
    foreign = SimpleNamespace(
        submit_request_ref="submit-request-foreign-live",
        submit_request_mode="live",
        recorded_by="alice",
    )

    class Requests:
        @staticmethod
        def request(ref: str):
            if ref == foreign.submit_request_ref:
                return foreign
            raise KeyError(ref)

    class Submitter:
        def __init__(self) -> None:
            self.calls = 0

        def submit_guarded_order(self, **_kwargs):
            self.calls += 1
            return {}

    submitter = Submitter()
    monkeypatch.setattr(app_main, "EXECUTION_SUBMIT_REQUESTS", Requests())
    monkeypatch.setattr(app_main, "EXECUTION_ORDER_SUBMITTER", submitter)
    app_main.app.dependency_overrides[require_user_dependency] = lambda: SimpleNamespace(
        user_id="bob",
        username="alice",
    )
    try:
        client = TestClient(app_main.app)
        foreign_response = client.post(
            "/api/research-os/execution/order_submissions/run",
            json={"submit_request_ref": foreign.submit_request_ref},
        )
        missing_response = client.post(
            "/api/research-os/execution/order_submissions/run",
            json={"submit_request_ref": "submit-request-missing"},
        )
        assert foreign_response.status_code == missing_response.status_code == 404
        assert foreign_response.json()["detail"] == missing_response.json()["detail"] == (
            "execution record not found"
        )
        assert submitter.calls == 0
    finally:
        app_main.app.dependency_overrides.pop(require_user_dependency, None)


def test_reconciliation_action_rejects_stale_owned_head(tmp_path, monkeypatch):
    order_intent, runtime_promotion, venue_events, _graph = _reconciliation_test_state(
        tmp_path,
        monkeypatch,
    )
    _record_reconciliation_event(venue_events, order_intent, runtime_promotion)
    submission = app_main.EXECUTION_ORDER_SUBMISSIONS.submissions()[0]
    app_main.app.dependency_overrides[require_user_dependency] = lambda: SimpleNamespace(
        user_id="tester",
        username="tester",
    )
    try:
        client = TestClient(app_main.app)
        first = client.post(
            "/api/research-os/execution/reconciliations",
            json={
                "order_intent_ref": order_intent.order_intent_ref,
                "runtime_promotion_ref": runtime_promotion.runtime_promotion_ref,
                "submission_ref": submission.submission_ref,
                "venue_order_ref": submission.venue_order_ref,
                "audit_record_ref": "audit:reconcile:stale-head-1",
            },
        )
        assert first.status_code == 200, first.text
        stale_ref = first.json()["reconciliation_ref"]

        _record_reconciliation_event(
            venue_events,
            order_intent,
            runtime_promotion,
            event_kind="reconciled",
            status="reconciled",
        )
        second = client.post(
            "/api/research-os/execution/reconciliations",
            json={
                "order_intent_ref": order_intent.order_intent_ref,
                "runtime_promotion_ref": runtime_promotion.runtime_promotion_ref,
                "submission_ref": submission.submission_ref,
                "venue_order_ref": submission.venue_order_ref,
                "audit_record_ref": "audit:reconcile:stale-head-2",
            },
        )
        assert second.status_code == 200, second.text

        denied = client.post(
            "/api/research-os/execution/reconciliation_actions",
            json={
                "reconciliation_ref": stale_ref,
                "action_kind": "request_missing_reconcile",
                "action_status": "open",
                "audit_record_ref": "audit:stale-action",
            },
        )
        assert denied.status_code == 409
        assert denied.json()["detail"] == "formal reconciliation is stale"

        summary = client.get("/api/research-os/execution/reconciliations/summary")
        assert summary.status_code == 200, summary.text
        rows = summary.json()["reconciliations"]
        assert len(rows) == 2
        assert [row["reconciliation_ref"] for row in rows if row["is_current_head"]] == [
            second.json()["reconciliation_ref"]
        ]
    finally:
        app_main.app.dependency_overrides.pop(require_user_dependency, None)


def test_reconciliation_action_append_holds_shared_head_mutation_guard(tmp_path, monkeypatch):
    order_intent, runtime_promotion, venue_events, _graph = _reconciliation_test_state(
        tmp_path,
        monkeypatch,
    )
    _record_reconciliation_event(venue_events, order_intent, runtime_promotion)
    submission = app_main.EXECUTION_ORDER_SUBMISSIONS.submissions()[0]
    app_main.app.dependency_overrides[require_user_dependency] = lambda: SimpleNamespace(
        user_id="tester",
        username="tester",
    )
    try:
        client = TestClient(app_main.app)
        reconciliation = client.post(
            "/api/research-os/execution/reconciliations",
            json={
                "order_intent_ref": order_intent.order_intent_ref,
                "runtime_promotion_ref": runtime_promotion.runtime_promotion_ref,
                "submission_ref": submission.submission_ref,
                "venue_order_ref": submission.venue_order_ref,
                "audit_record_ref": "audit:reconcile:guarded-action",
            },
        )
        assert reconciliation.status_code == 200, reconciliation.text
        assert reconciliation.json()["action_required"] is True

        held = {"value": False, "observed_at_append": False}
        original_guard = app_main.EXECUTION_RECONCILIATIONS.mutation_guard
        original_record_action = app_main.EXECUTION_RECONCILIATION_ACTIONS.record_action

        @contextmanager
        def observed_guard():
            with original_guard():
                held["value"] = True
                try:
                    yield
                finally:
                    held["value"] = False

        def observed_record_action(*args, **kwargs):
            held["observed_at_append"] = held["value"]
            return original_record_action(*args, **kwargs)

        monkeypatch.setattr(
            app_main.EXECUTION_RECONCILIATIONS,
            "mutation_guard",
            observed_guard,
        )
        monkeypatch.setattr(
            app_main.EXECUTION_RECONCILIATION_ACTIONS,
            "record_action",
            observed_record_action,
        )
        response = client.post(
            "/api/research-os/execution/reconciliation_actions",
            json={
                "reconciliation_ref": reconciliation.json()["reconciliation_ref"],
                "action_kind": "request_missing_reconcile",
                "action_status": "open",
                "audit_record_ref": "audit:guarded-action",
            },
        )
        assert response.status_code == 200, response.text
        assert held["observed_at_append"] is True
        assert held["value"] is False
    finally:
        app_main.app.dependency_overrides.pop(require_user_dependency, None)


def test_reconciliation_mutation_guard_is_reentrant_for_same_lock_path(tmp_path):
    registry = PersistentExecutionReconciliationRegistry(
        tmp_path / "execution_reconciliations.jsonl"
    )

    with registry.mutation_guard():
        with registry.mutation_guard():
            pass


def test_reconciliation_duplicate_event_set_cannot_poison_current_head(tmp_path, monkeypatch):
    order_intent, runtime_promotion, venue_events, _graph = _reconciliation_test_state(
        tmp_path,
        monkeypatch,
    )
    _record_reconciliation_event(venue_events, order_intent, runtime_promotion)
    submission = app_main.EXECUTION_ORDER_SUBMISSIONS.submissions()[0]
    app_main.app.dependency_overrides[require_user_dependency] = lambda: SimpleNamespace(
        user_id="tester",
        username="tester",
    )
    try:
        client = TestClient(app_main.app)
        base = {
            "order_intent_ref": order_intent.order_intent_ref,
            "runtime_promotion_ref": runtime_promotion.runtime_promotion_ref,
            "submission_ref": submission.submission_ref,
            "venue_order_ref": submission.venue_order_ref,
        }
        first = client.post(
            "/api/research-os/execution/reconciliations",
            json={**base, "audit_record_ref": "audit:reconcile:canonical-a"},
        )
        duplicate = client.post(
            "/api/research-os/execution/reconciliations",
            json={**base, "audit_record_ref": "audit:reconcile:canonical-b"},
        )

        assert first.status_code == 200, first.text
        assert duplicate.status_code == 422
        assert "event set already has a canonical record" in duplicate.text
        summary = client.get("/api/research-os/execution/reconciliations/summary")
        assert summary.status_code == 200, summary.text
        rows = summary.json()["reconciliations"]
        assert len(rows) == 1
        assert rows[0]["is_current_head"] is True
        assert rows[0]["reconciliation_ref"] == first.json()["reconciliation_ref"]
    finally:
        app_main.app.dependency_overrides.pop(require_user_dependency, None)


def test_live_formal_owner_requires_hmac_client_and_account_authority(
    monkeypatch,
):
    client_order_id = "copy-live-owner-1"
    submission = SimpleNamespace(
        submission_ref="order_submission_v2_live_owner",
        submission_mode="live",
        submission_status="accepted",
        client_order_ref_hash=execution_client_order_ref_hash(client_order_id),
        order_intent_ref="order_intent_live_owner",
        runtime_promotion_ref="runtime_promotion_live_owner",
        order_materialization_ref="materialization_live_owner",
        venue_capability_ref="capability_live_owner",
        submit_request_ref="submit_request_live_owner",
        venue_order_ref="venue-order-live-owner",
        ack_ref="ack-live-owner",
        recorded_by="copy_trade_signal_relayer",
    )
    binding = app_main.FormalSubmissionRiskBinding(
        submission_ref=submission.submission_ref,
        reservation_ref="reservation-live-owner",
        binding_event_id="risk-event-live-owner",
        outcome_state="submission_accepted",
        follower_id="alice::master-live-owner",
        account_binding_ref="exchange-account-live-owner",
        signal_id="signal-live-owner",
        risk_check_ref="risk-check-live-owner",
        snapshot_ref="snapshot-live-owner",
        client_order_id=client_order_id,
        venue_order_ref=submission.venue_order_ref,
        ack_ref=submission.ack_ref,
        reason_ref="",
        order_request_context={
            "client_order_id": client_order_id,
            "order_intent_ref": submission.order_intent_ref,
            "runtime_promotion_ref": submission.runtime_promotion_ref,
            "order_materialization_ref": submission.order_materialization_ref,
            "venue_capability_ref": submission.venue_capability_ref,
            "submit_request_ref": submission.submit_request_ref,
        },
    )
    monkeypatch.setattr(
        app_main,
        "ACCOUNT_HALT_BARRIER",
        SimpleNamespace(
            snapshot=lambda account_ref: SimpleNamespace(
                owner_user_id="alice"
            )
            if account_ref == "exchange-account-live-owner"
            else None
        ),
    )
    monkeypatch.setattr(
        app_main,
        "COPY_TRADE_SERVICE",
        SimpleNamespace(get_follower=lambda _follower_id: None),
    )

    assert app_main._formal_submission_owner(
        submission,
        live_bindings={submission.submission_ref: binding},
    ) == "alice"
    assert app_main._formal_submission_owner(submission, live_bindings={}) is None

    changed_hash = SimpleNamespace(
        **{
            **submission.__dict__,
            "client_order_ref_hash": execution_client_order_ref_hash("foreign-client"),
        }
    )
    with pytest.raises(app_main.HTTPException) as caught:
        app_main._formal_submission_owner(
            changed_hash,
            live_bindings={submission.submission_ref: binding},
        )
    assert caught.value.status_code == 503
    assert caught.value.detail == "formal execution owner authority unavailable"


def test_live_formal_http_event_ingester_is_coordinator_only(monkeypatch):
    client_order_id = "copy-live-http-owner-1"
    submission = SimpleNamespace(
        submission_ref="order_submission_v2_live_http_owner",
        submission_mode="live",
        submission_status="accepted",
        client_order_ref_hash=execution_client_order_ref_hash(client_order_id),
        order_intent_ref="order_intent_live_http_owner",
        runtime_promotion_ref="runtime_promotion_live_http_owner",
        order_materialization_ref="materialization_live_http_owner",
        venue_capability_ref="capability_live_http_owner",
        submit_request_ref="submit_request_live_http_owner",
        venue_order_ref="venue-order-live-http-owner",
        ack_ref="ack-live-http-owner",
        recorded_by="copy_trade_signal_relayer",
    )
    binding = app_main.FormalSubmissionRiskBinding(
        submission_ref=submission.submission_ref,
        reservation_ref="reservation-live-http-owner",
        binding_event_id="risk-event-live-http-owner",
        outcome_state="submission_accepted",
        follower_id="alice::master-live-http-owner",
        account_binding_ref="exchange-account-live-http-owner",
        signal_id="signal-live-http-owner",
        risk_check_ref="risk-check-live-http-owner",
        snapshot_ref="snapshot-live-http-owner",
        client_order_id=client_order_id,
        venue_order_ref=submission.venue_order_ref,
        ack_ref=submission.ack_ref,
        reason_ref="",
        order_request_context={
            "client_order_id": client_order_id,
            "order_intent_ref": submission.order_intent_ref,
            "runtime_promotion_ref": submission.runtime_promotion_ref,
            "order_materialization_ref": submission.order_materialization_ref,
            "venue_capability_ref": submission.venue_capability_ref,
            "submit_request_ref": submission.submit_request_ref,
        },
    )

    class _SubmissionStore:
        def refresh(self):
            return None

        def submission(self, ref):
            if ref != submission.submission_ref:
                raise KeyError(ref)
            return submission

        def submissions(self):
            return [submission]

    class _NeverIngester:
        calls = 0

        def ingest_event(self, **_kwargs):
            self.calls += 1
            raise AssertionError("live HTTP must not reach the generic ingester")

    ingester = _NeverIngester()
    monkeypatch.setattr(app_main, "EXECUTION_ORDER_SUBMISSIONS", _SubmissionStore())
    monkeypatch.setattr(
        app_main,
        "FOLLOWER_RISK_STATE",
        SimpleNamespace(verified_formal_submission_bindings=lambda: (binding,)),
    )
    monkeypatch.setattr(
        app_main,
        "ACCOUNT_HALT_BARRIER",
        SimpleNamespace(
            snapshot=lambda _account_ref: SimpleNamespace(owner_user_id="alice")
        ),
    )
    monkeypatch.setattr(
        app_main,
        "COPY_TRADE_SERVICE",
        SimpleNamespace(get_follower=lambda _follower_id: None),
    )
    monkeypatch.setattr(app_main, "EXECUTION_VENUE_EVENT_INGESTER", ingester)
    app_main.app.dependency_overrides[require_user_dependency] = lambda: SimpleNamespace(
        user_id="alice",
        username="mutable-display-name",
    )
    try:
        response = TestClient(app_main.app).post(
            "/api/research-os/execution/venue_events/run",
            json={"submission_ref": submission.submission_ref},
        )
        assert response.status_code == 409
        assert response.json()["detail"] == (
            "live formal venue event ingestion is coordinator-managed"
        )
        assert ingester.calls == 0
    finally:
        app_main.app.dependency_overrides.pop(require_user_dependency, None)


def test_incomparable_reconciliation_heads_fail_closed() -> None:
    left = SimpleNamespace(
        submission_ref="submission-head-conflict",
        reconciliation_ref="reconciliation-left",
        event_refs=("event-a",),
    )
    right = SimpleNamespace(
        submission_ref="submission-head-conflict",
        reconciliation_ref="reconciliation-right",
        event_refs=("event-b",),
    )
    with pytest.raises(app_main.HTTPException) as caught:
        app_main._current_formal_reconciliation_heads((left, right))
    assert caught.value.status_code == 503
    assert caught.value.detail == "formal reconciliation head is ambiguous"


def test_equal_reconciliation_event_sets_choose_stable_historical_head() -> None:
    common = {
        "submission_ref": "submission-head-equal",
        "event_refs": ("event-a",),
        "order_intent_ref": "intent-a",
        "runtime_promotion_ref": "promotion-a",
        "venue_order_ref": "venue-order-a",
        "status": "needs_reconcile",
        "action_required": True,
        "discrepancy_refs": ("missing_terminal_reconciliation",),
    }
    left = SimpleNamespace(reconciliation_ref="reconciliation-b", **common)
    right = SimpleNamespace(reconciliation_ref="reconciliation-a", **common)

    heads = app_main._current_formal_reconciliation_heads((left, right))

    assert heads["submission-head-equal"].reconciliation_ref == "reconciliation-a"


def test_user_risk_choice_requires_responsibility_boundary_and_disclosures():
    decision = validate_user_risk_choice(
        _risk_choice(cost_disclosure_ref=None, failure_mode_refs=(), responsibility_boundary_ref=None)
    )
    assert not decision.accepted
    assert _codes(decision) >= {
        "risk_choice_missing_responsibility_boundary",
        "risk_choice_missing_failure_modes",
    }


def test_user_risk_choice_registry_is_owner_scoped_durable_and_content_bound(tmp_path):
    path = tmp_path / "user_risk_choices.jsonl"
    registry = PersistentUserRiskChoiceRegistry(path)
    recorded = registry.record_choice(_risk_choice())
    assert recorded.choice_ref.startswith("user_risk_choice_v2_")
    assert registry.record_choice(_risk_choice()).choice_ref == recorded.choice_ref

    reopened = PersistentUserRiskChoiceRegistry(path)
    assert reopened.choice_for_owner(recorded.choice_ref, "risk-owner") == recorded
    with pytest.raises(PermissionError, match="different owner"):
        reopened.choice_for_owner(recorded.choice_ref, "other-owner")

    forged = replace(recorded, choice_ref="user_risk_choice_v2_" + "0" * 64)
    with pytest.raises(ValueError, match="content_identity_mismatch"):
        registry.record_choice(forged)


def test_complete_execution_boundary_contract_accepts_small_live_step():
    decision = validate_execution_boundary(
        _live_request(),
        drift_actions=(
            DriftTriggeredAction(
                action_ref="action:demote",
                action_kind="demote",
                feature_drift_ref="feature_drift:psi",
                performance_evidence_ref="perf:drawdown_alert",
                risk_evidence_ref=None,
            ),
        ),
        halt_recovery_plans=(
            HaltRecoveryPlan(
                plan_ref="halt_plan:001",
                halt_event_ref="halt:001",
                reconcile_ref="reconcile:001",
                auto_resend_order=False,
            ),
        ),
        math_claims=(
            ExecutionMathClaim(
                claim_ref="claim:kill_trigger",
                claim_kind="kill_trigger",
                claims_math_basis=True,
                consistency_check_ref="consistency:kill_trigger",
            ),
        ),
        user_risk_choices=(_risk_choice(),),
    )
    assert decision.accepted
    assert decision.violations == ()
