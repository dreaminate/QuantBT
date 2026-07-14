from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta
import json
import os
import stat
from types import SimpleNamespace

import pytest

from app.copy_trade.consent import PersistentUserRiskConsentStore
from app.copy_trade.formal_execution import (
    build_user_risk_choice,
    copy_trade_risk_disclosure_profile,
    runtime_requirements_for_follower,
)
from app.research_os.execution_boundary import (
    ExecutionOrderIntentRecord,
    ExecutionOrderMaterializationRecord,
    ExecutionOrderSubmissionRecord,
    ExecutionSubmitRequestRecord,
    ExecutionVenueCapabilityRecord,
    ExecutionVenueConnectivityCheckRecord,
    ExecutionVenueEventRecord,
    ExecutionVenueSafetyAttestationRecord,
    PersistentExecutionOrderIntentRegistry,
    PersistentExecutionOrderMaterializationRegistry,
    PersistentExecutionOrderSubmissionRegistry,
    PersistentExecutionReconciliationActionRegistry,
    PersistentExecutionReconciliationRegistry,
    PersistentExecutionSubmitRequestRegistry,
    PersistentExecutionVenueCapabilityRegistry,
    PersistentExecutionVenueConnectivityCheckRegistry,
    PersistentExecutionVenueEventRegistry,
    PersistentExecutionVenueSafetyAttestationRegistry,
    PersistentConsentBackedUserRiskChoiceRegistry,
    PersistentRuntimePromotionRegistry,
    PersistentUserRiskChoiceRegistry,
    RuntimePromotionRecord,
    execution_client_order_ref_hash,
    reconcile_execution_venue_events,
)
from app.research_os.execution_closure import (
    EXECUTION_CLOSURE_ENTRYPOINT_REF,
    ExecutionClosureCommitUncertain,
    ExecutionClosureError,
    ExecutionClosureSectionAdapter,
    PersistentExecutionClosureRegistry,
    execution_section_semantic_material,
)
from app.research_os.goal_semantics import GoalSectionSemanticProofRecord


def _registries(tmp_path):
    return SimpleNamespace(
        order_intents=PersistentExecutionOrderIntentRegistry(tmp_path / "intents.jsonl"),
        runtime_promotions=PersistentRuntimePromotionRegistry(tmp_path / "promotions.jsonl"),
        materializations=PersistentExecutionOrderMaterializationRegistry(
            tmp_path / "materializations.jsonl"
        ),
        connectivity_checks=PersistentExecutionVenueConnectivityCheckRegistry(
            tmp_path / "connectivity.jsonl"
        ),
        safety_attestations=PersistentExecutionVenueSafetyAttestationRegistry(
            tmp_path / "safety.jsonl"
        ),
        capabilities=PersistentExecutionVenueCapabilityRegistry(tmp_path / "capabilities.jsonl"),
        submit_requests=PersistentExecutionSubmitRequestRegistry(tmp_path / "requests.jsonl"),
        submissions=PersistentExecutionOrderSubmissionRegistry(tmp_path / "submissions.jsonl"),
        venue_events=PersistentExecutionVenueEventRegistry(tmp_path / "events.jsonl"),
        reconciliations=PersistentExecutionReconciliationRegistry(tmp_path / "reconciliations.jsonl"),
        reconciliation_actions=PersistentExecutionReconciliationActionRegistry(
            tmp_path / "actions.jsonl"
        ),
        user_risk_choices=PersistentUserRiskChoiceRegistry(tmp_path / "risk_choices.jsonl"),
    )


def _closure(tmp_path, registries, **kwargs):
    return PersistentExecutionClosureRegistry(
        tmp_path / "execution_closures.jsonl",
        order_intents=registries.order_intents,
        runtime_promotions=registries.runtime_promotions,
        materializations=registries.materializations,
        connectivity_checks=registries.connectivity_checks,
        safety_attestations=registries.safety_attestations,
        capabilities=registries.capabilities,
        submit_requests=registries.submit_requests,
        submissions=registries.submissions,
        venue_events=registries.venue_events,
        reconciliations=registries.reconciliations,
        reconciliation_actions=registries.reconciliation_actions,
        user_risk_choices=registries.user_risk_choices,
        **kwargs,
    )


def _record_flow(
    registries,
    *,
    owner: str = "owner-a",
    suffix: str = "a",
    runtime: str = "testnet",
    runtime_request_ref: str | None = None,
    subject_ref: str | None = None,
    responsibility_boundary_ref: str | None = None,
):
    permission = f"permission:{runtime}:{suffix}"
    guard = f"order_guard:{suffix}"
    idem = f"idempotency:{suffix}"
    audit = f"audit:{suffix}"
    kill = f"kill_switch:{suffix}"
    secret = f"secretref:binance:{suffix}"
    responsibility = responsibility_boundary_ref or f"responsibility:{suffix}"
    venue_profile = "binance_mainnet" if runtime == "live" else "binance_sandbox"
    venue = f"venue:{venue_profile}:{suffix}"
    guarded_venue = f"guarded_venue:{venue_profile}:{suffix}"
    instrument = f"instrument:BTCUSDT_PERP:{suffix}"

    intent = registries.order_intents.record_intent(
        ExecutionOrderIntentRecord(
            source_portfolio_ref=f"portfolio:{suffix}",
            strategy_book_ref=None,
            execution_policy_ref=f"execution_policy:{suffix}",
            risk_policy_ref=f"risk_policy:{suffix}",
            runtime=runtime,
            asset_class="crypto_perp",
            instrument_ref=instrument,
            side="buy",
            order_type="limit",
            venue_ref=venue,
            market_data_use_validation_ref=f"market_data_use:{suffix}",
            quantity_ref=f"quantity_resolution:{suffix}",
            price_ref=f"price_resolution:{suffix}",
            permission_gate_ref=permission,
            order_guard_ref=guard,
            idempotency_key=idem,
            audit_record_ref=audit,
            kill_switch_ref=kill,
            secret_ref=secret,
            responsibility_boundary_ref=responsibility,
            failure_mode_refs=(f"failure_mode:venue_timeout:{suffix}",),
            recorded_by=owner,
        ),
        known_market_data_use_validation_refs={f"market_data_use:{suffix}"},
    )
    promotion = registries.runtime_promotions.record_promotion(
        RuntimePromotionRecord(
            request_ref=runtime_request_ref or f"runtime_request:{suffix}",
            subject_ref=subject_ref or f"strategy_subject:{suffix}",
            asset_class="crypto_perp",
            source_runtime="testnet" if runtime == "live" else "paper",
            target_runtime=runtime,
            paper_run_ref=f"paper_run:{suffix}",
            testnet_run_ref=f"testnet_run:{suffix}",
            approval_ref=f"approval:{suffix}",
            permission_gate_ref=permission,
            order_guard_ref=guard,
            idempotency_key=idem,
            audit_record_ref=audit,
            kill_switch_ref=kill,
            secret_ref=secret,
            responsibility_boundary_ref=responsibility,
            evidence_refs=(f"evidence:runtime_promotion:{suffix}",),
            recorded_by=owner,
        )
    )
    materialization = registries.materializations.record_materialization(
        ExecutionOrderMaterializationRecord(
            order_intent_ref=intent.order_intent_ref,
            runtime_promotion_ref=promotion.runtime_promotion_ref,
            materializer_ref=f"order_materializer:{suffix}",
            materialization_mode=runtime,
            materialization_status="materialized",
            permission_gate_ref=permission,
            order_guard_ref=guard,
            idempotency_key=idem,
            audit_record_ref=audit,
            order_schema_ref=f"schema:execution_order:{suffix}",
            order_payload_hash=f"sha256:order_payload:{suffix}",
            quantity_resolution_ref=f"quantity_resolution:{suffix}",
            price_resolution_ref=f"price_resolution:{suffix}",
            market_snapshot_ref=f"market_snapshot:{suffix}",
            risk_check_ref=f"risk_check:{suffix}",
            kill_switch_ref=kill,
            secret_ref=secret,
            responsibility_boundary_ref=responsibility,
            materialize_enabled=True,
            evidence_refs=(f"evidence:materialization:{suffix}",),
            recorded_by=owner,
        ),
        known_order_intent_refs={intent.order_intent_ref},
        known_runtime_promotion_refs={promotion.runtime_promotion_ref},
        order_intent=intent,
        runtime_promotion=promotion,
    )
    connectivity = registries.connectivity_checks.record_check(
        ExecutionVenueConnectivityCheckRecord(
            order_intent_ref=intent.order_intent_ref,
            runtime_promotion_ref=promotion.runtime_promotion_ref,
            venue_ref=venue,
            guarded_venue_ref=guarded_venue,
            runtime=runtime,
            asset_class="crypto_perp",
            instrument_ref=instrument,
            connectivity_status="accepted",
            checker_ref=f"connectivity_checker:{suffix}",
            permission_gate_ref=permission,
            order_guard_ref=guard,
            idempotency_key=idem,
            audit_record_ref=audit,
            credential_check_ref=f"credential_check:{suffix}",
            ip_allowlist_ref=f"ip_allowlist:{suffix}",
            withdrawal_disabled_ref=f"withdrawal_disabled:{suffix}",
            hmac_replay_protection_ref=f"hmac_replay:{suffix}",
            health_check_ref=f"health_check:{suffix}",
            rate_limit_ref=f"rate_limit:{suffix}",
            sandbox_proof_ref=f"sandbox_proof:{suffix}",
            connectivity_check_hash=f"sha256:connectivity:{suffix}",
            kill_switch_ref=kill,
            secret_ref=secret,
            responsibility_boundary_ref=responsibility,
            evidence_refs=(f"evidence:connectivity:{suffix}",),
            recorded_by=owner,
        ),
        known_order_intent_refs={intent.order_intent_ref},
        known_runtime_promotion_refs={promotion.runtime_promotion_ref},
        order_intent=intent,
        runtime_promotion=promotion,
    )
    safety = registries.safety_attestations.record_attestation(
        ExecutionVenueSafetyAttestationRecord(
            order_intent_ref=intent.order_intent_ref,
            runtime_promotion_ref=promotion.runtime_promotion_ref,
            venue_ref=venue,
            guarded_venue_ref=guarded_venue,
            runtime=runtime,
            asset_class="crypto_perp",
            instrument_ref=instrument,
            attestation_status="accepted",
            permission_gate_ref=permission,
            order_guard_ref=guard,
            idempotency_key=idem,
            audit_record_ref=audit,
            credential_check_ref=f"credential_check:{suffix}",
            ip_allowlist_ref=f"ip_allowlist:{suffix}",
            withdrawal_disabled_ref=f"withdrawal_disabled:{suffix}",
            hmac_replay_protection_ref=f"hmac_replay:{suffix}",
            health_check_ref=f"health_check:{suffix}",
            rate_limit_ref=f"rate_limit:{suffix}",
            venue_connectivity_check_ref=connectivity.venue_connectivity_check_ref,
            sandbox_proof_ref=f"sandbox_proof:{suffix}",
            kill_switch_ref=kill,
            secret_ref=secret,
            responsibility_boundary_ref=responsibility,
            evidence_refs=(f"evidence:safety:{suffix}",),
            recorded_by=owner,
        ),
        known_order_intent_refs={intent.order_intent_ref},
        known_runtime_promotion_refs={promotion.runtime_promotion_ref},
        known_venue_connectivity_check_refs={connectivity.venue_connectivity_check_ref},
        order_intent=intent,
        runtime_promotion=promotion,
        venue_connectivity_check=connectivity,
    )
    capability = registries.capabilities.record_capability(
        ExecutionVenueCapabilityRecord(
            order_intent_ref=intent.order_intent_ref,
            runtime_promotion_ref=promotion.runtime_promotion_ref,
            venue_ref=venue,
            guarded_venue_ref=guarded_venue,
            submitter_ref=f"guarded_submitter:{suffix}",
            runtime=runtime,
            asset_class="crypto_perp",
            instrument_ref=instrument,
            capability_status="ready",
            permission_gate_ref=permission,
            order_guard_ref=guard,
            idempotency_key=idem,
            audit_record_ref=audit,
            venue_safety_attestation_ref=safety.venue_safety_attestation_ref,
            credential_check_ref=f"credential_check:{suffix}",
            ip_allowlist_ref=f"ip_allowlist:{suffix}",
            withdrawal_disabled_ref=f"withdrawal_disabled:{suffix}",
            hmac_replay_protection_ref=f"hmac_replay:{suffix}",
            health_check_ref=f"health_check:{suffix}",
            rate_limit_ref=f"rate_limit:{suffix}",
            sandbox_proof_ref=f"sandbox_proof:{suffix}",
            kill_switch_ref=kill,
            secret_ref=secret,
            responsibility_boundary_ref=responsibility,
            can_submit_orders=True,
            evidence_refs=(f"evidence:capability:{suffix}",),
            recorded_by=owner,
        ),
        known_order_intent_refs={intent.order_intent_ref},
        known_runtime_promotion_refs={promotion.runtime_promotion_ref},
        known_venue_safety_attestation_refs={safety.venue_safety_attestation_ref},
        order_intent=intent,
        runtime_promotion=promotion,
        venue_safety_attestation=safety,
    )
    client_ref = f"client_order:{suffix}"
    client_ref_hash = execution_client_order_ref_hash(client_ref)
    submit_request = registries.submit_requests.record_request(
        ExecutionSubmitRequestRecord(
            order_intent_ref=intent.order_intent_ref,
            runtime_promotion_ref=promotion.runtime_promotion_ref,
            order_materialization_ref=materialization.materialization_ref,
            venue_capability_ref=capability.venue_capability_ref,
            submitter_ref=capability.submitter_ref,
            guarded_venue_ref=guarded_venue,
            venue_ref=venue,
            submit_request_mode=runtime,
            submit_request_status="ready",
            permission_gate_ref=permission,
            order_guard_ref=guard,
            idempotency_key=idem,
            audit_record_ref=audit,
            order_schema_ref=materialization.order_schema_ref,
            order_payload_hash=materialization.order_payload_hash,
            submit_request_schema_ref=f"schema:submit_request:{suffix}",
            submit_request_hash=f"sha256:submit_request:{suffix}",
            client_order_ref_hash=client_ref_hash,
            kill_switch_ref=kill,
            secret_ref=secret,
            responsibility_boundary_ref=responsibility,
            evidence_refs=(f"evidence:submit_request:{suffix}",),
            recorded_by=owner,
        ),
        known_order_intent_refs={intent.order_intent_ref},
        known_runtime_promotion_refs={promotion.runtime_promotion_ref},
        known_order_materialization_refs={materialization.materialization_ref},
        known_venue_capability_refs={capability.venue_capability_ref},
        order_intent=intent,
        runtime_promotion=promotion,
        order_materialization=materialization,
        venue_capability=capability,
    )
    submission = registries.submissions.record_submission(
        ExecutionOrderSubmissionRecord(
            order_intent_ref=intent.order_intent_ref,
            runtime_promotion_ref=promotion.runtime_promotion_ref,
            submitter_ref=capability.submitter_ref,
            guarded_venue_ref=guarded_venue,
            venue_ref=venue,
            submission_mode=runtime,
            permission_gate_ref=permission,
            order_guard_ref=guard,
            idempotency_key=idem,
            audit_record_ref=audit,
            kill_switch_ref=kill,
            secret_ref=secret,
            responsibility_boundary_ref=responsibility,
            submit_enabled=True,
            order_materialization_ref=materialization.materialization_ref,
            venue_capability_ref=capability.venue_capability_ref,
            submit_request_ref=submit_request.submit_request_ref,
            submission_status="accepted",
            venue_order_ref=f"venue_order:{suffix}",
            ack_ref=f"ack:{suffix}",
            client_order_ref_hash=client_ref_hash,
            evidence_refs=(f"evidence:submission:{suffix}",),
            recorded_by=owner,
        ),
        known_order_intent_refs={intent.order_intent_ref},
        known_runtime_promotion_refs={promotion.runtime_promotion_ref},
        known_order_materialization_refs={materialization.materialization_ref},
        known_venue_capability_refs={capability.venue_capability_ref},
        known_submit_request_refs={submit_request.submit_request_ref},
        order_intent=intent,
        runtime_promotion=promotion,
        order_materialization=materialization,
        venue_capability=capability,
        submit_request=submit_request,
    )

    def event(kind: str, status: str):
        record = ExecutionVenueEventRecord(
            order_intent_ref=intent.order_intent_ref,
            runtime_promotion_ref=promotion.runtime_promotion_ref,
            submission_ref=submission.submission_ref,
            venue_ref=venue,
            event_kind=kind,
            status=status,
            venue_order_ref=submission.venue_order_ref,
            client_order_ref=client_ref,
            ack_ref=submission.ack_ref,
            fill_ref=f"fill:{suffix}",
            reconcile_ref=f"venue_reconcile:{suffix}",
            quantity_ref=f"filled_quantity:{suffix}",
            price_ref=f"fill_price:{suffix}",
            fee_ref=f"fee:{suffix}",
            raw_event_hash=f"sha256:raw_event:{kind}:{suffix}",
            audit_record_ref=audit,
            order_guard_ref=guard,
            idempotency_key=idem,
            evidence_refs=(f"evidence:event:{kind}:{suffix}",),
            recorded_by=owner,
        )
        return registries.venue_events.record_event(
            record,
            known_order_intent_refs={intent.order_intent_ref},
            known_runtime_promotion_refs={promotion.runtime_promotion_ref},
            known_submission_refs={submission.submission_ref},
            submission=submission,
        )

    filled = event("filled", "filled")
    reconciled_event = event("reconciled", "reconciled")
    reconciliation = reconcile_execution_venue_events(
        order_intent_ref=intent.order_intent_ref,
        runtime_promotion_ref=promotion.runtime_promotion_ref,
        submission_ref=submission.submission_ref,
        venue_order_ref=submission.venue_order_ref,
        audit_record_ref=audit,
        events=(filled, reconciled_event),
        evidence_refs=(f"evidence:reconciliation:{suffix}",),
        recorded_by=owner,
    )
    reconciliation = registries.reconciliations.record_reconciliation(
        reconciliation,
        known_order_intent_refs={intent.order_intent_ref},
        known_runtime_promotion_refs={promotion.runtime_promotion_ref},
        known_venue_event_refs={filled.venue_event_ref, reconciled_event.venue_event_ref},
        known_submission_refs={submission.submission_ref},
        submission=submission,
        venue_events=(filled, reconciled_event),
    )
    return SimpleNamespace(
        intent=intent,
        promotion=promotion,
        materialization=materialization,
        connectivity=connectivity,
        safety=safety,
        capability=capability,
        submit_request=submit_request,
        submission=submission,
        events=(filled, reconciled_event),
        reconciliation=reconciliation,
    )


def _receipt_kwargs(flow):
    return {
        "order_intent_ref": flow.intent.order_intent_ref,
        "runtime_promotion_ref": flow.promotion.runtime_promotion_ref,
        "order_materialization_ref": flow.materialization.materialization_ref,
        "venue_connectivity_check_ref": flow.connectivity.venue_connectivity_check_ref,
        "venue_safety_attestation_ref": flow.safety.venue_safety_attestation_ref,
        "venue_capability_ref": flow.capability.venue_capability_ref,
        "submit_request_ref": flow.submit_request.submit_request_ref,
        "submission_ref": flow.submission.submission_ref,
        "venue_event_refs": tuple(event.venue_event_ref for event in flow.events),
        "reconciliation_ref": flow.reconciliation.reconciliation_ref,
    }


def test_execution_closure_records_replays_and_validates_current_chain(tmp_path):
    registries = _registries(tmp_path)
    flow = _record_flow(registries)
    registry = _closure(tmp_path, registries)

    receipt = registry.record_current(owner_user_id="owner-a", **_receipt_kwargs(flow))

    assert receipt.receipt_ref.startswith("execution_closure_receipt:")
    assert receipt.snapshot.runtime == "testnet"
    assert receipt.snapshot.reconciliation_status == "reconciled"
    assert registry.validate_current(receipt.receipt_ref, owner_user_id="owner-a").accepted
    reopened = _closure(tmp_path, registries)
    assert reopened.receipt(receipt.receipt_ref, owner_user_id="owner-a") == receipt
    assert reopened.validate_current(receipt.receipt_ref, owner_user_id="owner-a").accepted


def test_execution_closure_rejects_cross_flow_and_owner_laundering_without_write(tmp_path):
    registries = _registries(tmp_path)
    left = _record_flow(registries, suffix="left")
    right = _record_flow(registries, suffix="right")
    placeholder = _record_flow(registries, suffix="placeholder")
    registry = _closure(tmp_path, registries)
    path = registry.path

    mixed = {**_receipt_kwargs(left), "order_materialization_ref": right.materialization.materialization_ref}
    with pytest.raises(ExecutionClosureError):
        registry.record_current(owner_user_id="owner-a", **mixed)
    with pytest.raises(ExecutionClosureError, match="owner"):
        registry.record_current(owner_user_id="owner-b", **_receipt_kwargs(left))
    with pytest.raises(ValueError, match="placeholder"):
        registry.record_current(owner_user_id="owner-a", **_receipt_kwargs(placeholder))

    assert not path.exists()


def test_execution_closure_becomes_non_current_after_newer_promotion_for_subject(tmp_path):
    registries = _registries(tmp_path)
    flow = _record_flow(registries)
    registry = _closure(tmp_path, registries)
    receipt = registry.record_current(owner_user_id="owner-a", **_receipt_kwargs(flow))
    registries.runtime_promotions.record_promotion(
        replace(
            flow.promotion,
            request_ref="runtime_request:newer",
            testnet_run_ref="testnet_run:newer",
            evidence_refs=("evidence:runtime_promotion:newer",),
            created_at_utc=(
                datetime.fromisoformat(flow.promotion.created_at_utc) + timedelta(seconds=1)
            ).isoformat(),
            runtime_promotion_ref="",
        )
    )

    current = registry.validate_current(receipt.receipt_ref, owner_user_id="owner-a")

    assert not current.accepted
    assert current.violations[0].code == "execution_closure_current_resolution_failed"


def test_execution_closure_uses_append_order_against_backdated_promotion(tmp_path):
    registries = _registries(tmp_path)
    flow = _record_flow(registries)
    registry = _closure(tmp_path, registries)
    receipt = registry.record_current(owner_user_id="owner-a", **_receipt_kwargs(flow))
    registries.runtime_promotions.record_promotion(
        replace(
            flow.promotion,
            request_ref="runtime_request:backdated-later-append",
            testnet_run_ref="testnet_run:backdated-later-append",
            evidence_refs=("evidence:runtime_promotion:backdated-later-append",),
            created_at_utc=(
                datetime.fromisoformat(flow.promotion.created_at_utc) - timedelta(days=1)
            ).isoformat(),
            runtime_promotion_ref="",
        )
    )

    current = registry.validate_current(receipt.receipt_ref, owner_user_id="owner-a")

    assert not current.accepted
    assert current.violations[0].code == "execution_closure_current_resolution_failed"


def test_execution_closure_becomes_non_current_after_later_submission_event(tmp_path):
    registries = _registries(tmp_path)
    flow = _record_flow(registries)
    registry = _closure(tmp_path, registries)
    receipt = registry.record_current(owner_user_id="owner-a", **_receipt_kwargs(flow))
    later = replace(
        flow.events[-1],
        raw_event_hash="sha256:raw_event:later-reconciled",
        evidence_refs=("evidence:event:later-reconciled",),
        created_at_utc=(
            datetime.fromisoformat(flow.events[-1].created_at_utc) + timedelta(seconds=1)
        ).isoformat(),
        venue_event_ref="",
    )
    registries.venue_events.record_event(
        later,
        known_order_intent_refs={flow.intent.order_intent_ref},
        known_runtime_promotion_refs={flow.promotion.runtime_promotion_ref},
        known_submission_refs={flow.submission.submission_ref},
        submission=flow.submission,
    )

    current = registry.validate_current(receipt.receipt_ref, owner_user_id="owner-a")

    assert not current.accepted
    assert current.violations[0].code == "execution_closure_current_resolution_failed"


def test_execution_closure_binds_ttl_policy_and_expires_current_evidence(tmp_path, monkeypatch):
    registries = _registries(tmp_path)
    flow = _record_flow(registries)
    registry = _closure(tmp_path, registries, evidence_ttl_seconds=60.0)
    receipt = registry.record_current(owner_user_id="owner-a", **_receipt_kwargs(flow))

    assert _closure(
        tmp_path,
        registries,
        evidence_ttl_seconds=60.0,
    ).validate_current(receipt.receipt_ref, owner_user_id="owner-a").accepted
    assert not _closure(
        tmp_path,
        registries,
        evidence_ttl_seconds=120.0,
    ).validate_current(receipt.receipt_ref, owner_user_id="owner-a").accepted

    real_datetime = datetime

    class FutureDateTime(real_datetime):
        @classmethod
        def now(cls, tz=None):
            return real_datetime.now(tz) + timedelta(hours=1)

    monkeypatch.setattr("app.research_os.execution_closure.datetime", FutureDateTime)
    expired = registry.validate_current(receipt.receipt_ref, owner_user_id="owner-a")

    assert not expired.accepted
    assert expired.violations[0].code == "execution_closure_current_resolution_failed"


@pytest.mark.parametrize("ttl", [0.0, -1.0, float("nan"), float("inf")])
def test_execution_closure_rejects_non_finite_or_non_positive_ttl(tmp_path, ttl):
    registries = _registries(tmp_path)

    with pytest.raises(ValueError, match="finite and positive"):
        _closure(tmp_path, registries, evidence_ttl_seconds=ttl)


def test_execution_closure_detects_optional_ledger_first_create_race(tmp_path, monkeypatch):
    registries = _registries(tmp_path)
    flow = _record_flow(registries)
    registry = _closure(tmp_path, registries)
    original = registry._resolve_snapshot

    def resolve_after_optional_create(**kwargs):
        registries.reconciliation_actions._path.touch()
        return original(**kwargs)

    monkeypatch.setattr(registry, "_resolve_snapshot", resolve_after_optional_create)

    with pytest.raises(ExecutionClosureCommitUncertain, match="backing ledgers changed"):
        registry.record_current(owner_user_id="owner-a", **_receipt_kwargs(flow))

    assert not registry.path.exists()
    assert registry.receipts(owner_user_id="owner-a") == ()


def test_execution_closure_postcommit_drift_restores_exact_preexisting_ledger(
    tmp_path, monkeypatch
):
    registries = _registries(tmp_path)
    first_flow = _record_flow(registries, suffix="first")
    registry = _closure(tmp_path, registries)
    first_receipt = registry.record_current(
        owner_user_id="owner-a",
        **_receipt_kwargs(first_flow),
    )
    original = registry.path.read_bytes().rstrip(b"\n")
    registry.path.write_bytes(original)
    second_flow = _record_flow(registries, suffix="second")
    original_resolve = registry._resolve_snapshot

    def resolve_after_optional_create(**kwargs):
        registries.reconciliation_actions._path.touch()
        return original_resolve(**kwargs)

    monkeypatch.setattr(registry, "_resolve_snapshot", resolve_after_optional_create)

    with pytest.raises(ExecutionClosureCommitUncertain, match="backing ledgers changed"):
        registry.record_current(
            owner_user_id="owner-a",
            **_receipt_kwargs(second_flow),
        )

    assert original and not original.endswith(b"\n")
    assert registry.path.read_bytes() == original
    assert registry.receipts(owner_user_id="owner-a") == (first_receipt,)


@pytest.mark.parametrize(
    "preexisting",
    [False, True],
    ids=["first-create", "preexisting"],
)
def test_execution_closure_directory_fsync_failure_restores_exact_prior_ledger(
    tmp_path, monkeypatch, preexisting
):
    registries = _registries(tmp_path)
    registry = _closure(tmp_path, registries)
    first_receipt = None
    original = b""
    if preexisting:
        first_flow = _record_flow(registries, suffix="first")
        first_receipt = registry.record_current(
            owner_user_id="owner-a",
            **_receipt_kwargs(first_flow),
        )
        original = registry.path.read_bytes().rstrip(b"\n")
        registry.path.write_bytes(original)
        flow = _record_flow(registries, suffix="second")
    else:
        flow = _record_flow(registries)

    real_fsync = os.fsync
    directory_fsync_calls = 0

    def fail_first_directory_fsync(fd):
        nonlocal directory_fsync_calls
        if stat.S_ISDIR(os.fstat(fd).st_mode):
            directory_fsync_calls += 1
            if directory_fsync_calls == 1:
                raise OSError("directory fsync failed")
        return real_fsync(fd)

    monkeypatch.setattr(
        "app.research_os.execution_closure.os.fsync",
        fail_first_directory_fsync,
    )

    with pytest.raises(ExecutionClosureCommitUncertain, match="directory fsync failed"):
        registry.record_current(owner_user_id="owner-a", **_receipt_kwargs(flow))

    assert directory_fsync_calls == 2
    if preexisting:
        assert first_receipt is not None
        assert original and not original.endswith(b"\n")
        assert registry.path.read_bytes() == original
        assert registry.receipts(owner_user_id="owner-a") == (first_receipt,)
    else:
        assert not registry.path.exists()
        assert registry.receipts(owner_user_id="owner-a") == ()


def test_execution_closure_atomic_replace_failure_writes_no_partial_receipt(
    tmp_path, monkeypatch
):
    registries = _registries(tmp_path)
    flow = _record_flow(registries)
    registry = _closure(tmp_path, registries)

    def fail_replace(*_args, **_kwargs):
        raise OSError("replace failed")

    monkeypatch.setattr("app.research_os.execution_closure.os.replace", fail_replace)
    with pytest.raises(OSError, match="replace failed"):
        registry.record_current(owner_user_id="owner-a", **_receipt_kwargs(flow))

    assert not registry.path.exists()
    assert registry.receipts(owner_user_id="owner-a") == ()


def test_execution_closure_section_adapter_uses_source_lineages_without_platform_cycle(
    tmp_path,
):
    consent_store = PersistentUserRiskConsentStore(
        tmp_path / "community.db",
        integrity_key=b"c" * 32,
    )
    follower = SimpleNamespace(
        follower_id="owner-a::master-a",
        user_id="owner-a",
        master_id="master-a",
        account_binding_ref="exchange-account-a",
        binance_network="mainnet",
        invest_amount=1_000.0,
        per_order_max_usdt=100.0,
        daily_loss_limit_pct=0.05,
        max_positions=3,
        max_leverage=2.0,
    )
    profile = copy_trade_risk_disclosure_profile()
    choice = build_user_risk_choice(
        follower,
        owner_user_id="owner-a",
        selected_risk_path="small_live",
        risk_disclosure_profile_ref=profile["profile_ref"],
    )
    requirements = runtime_requirements_for_follower(follower, risk_choice=choice)
    source_ip_hash = consent_store.source_ip_hash("127.0.0.1")
    challenge = consent_store.issue_challenge(
        owner_user_id="owner-a",
        follower_id=follower.follower_id,
        master_id=follower.master_id,
        account_binding_ref=follower.account_binding_ref,
        credential_binding_ref="exchange-credential-a",
        subject_ref=requirements.subject_ref,
        runtime_request_ref=requirements.request_ref,
        risk_profile_ref=profile["profile_ref"],
        source_ip_hash=source_ip_hash,
        payload={
            "risk_profile": profile,
            "required_acknowledgement_refs": profile["required_acknowledgement_refs"],
            "proposed_user_risk_choice": choice.to_dict(),
        },
    )
    consent_event = consent_store.consume_challenge(
        challenge_ref=challenge.challenge_ref,
        owner_user_id="owner-a",
        user_risk_choice_ref=choice.choice_ref,
        user_risk_choice=choice.to_dict(),
        acknowledged_item_refs=profile["required_acknowledgement_refs"],
        source_ip_hash=source_ip_hash,
        password_verified=True,
        totp_verified=False,
    )
    consent_decision = consent_store.decision_for_event(
        consent_event.consent_event_ref,
        "owner-a",
    )
    registries = _registries(tmp_path)
    registries.user_risk_choices = PersistentConsentBackedUserRiskChoiceRegistry(
        consent_store
    )
    flow = _record_flow(
        registries,
        runtime="live",
        runtime_request_ref=choice.runtime_request_ref,
        subject_ref=choice.subject_ref,
        responsibility_boundary_ref=choice.responsibility_boundary_ref,
    )
    closure_registry = _closure(tmp_path, registries)
    receipt = closure_registry.record_current(
        owner_user_id="owner-a",
        user_risk_choice_ref=choice.choice_ref,
        **_receipt_kwargs(flow),
    )
    assert receipt.snapshot.runtime == "live"
    assert receipt.user_risk_choice_ref == choice.choice_ref
    entrypoint_by_kind = {
        "order_intent": "api:research_os.execution.order_intents",
        "runtime_promotion": "api:research_os.execution.runtime_promotions",
        "order_materialization": "api:research_os.execution.order_materializations",
        "venue_connectivity_check": "api:research_os.execution.venue_connectivity_checks",
        "venue_safety_attestation": "api:research_os.execution.venue_safety_attestations",
        "venue_capability": "api:research_os.execution.venue_capabilities",
        "submit_request": "api:research_os.execution.submit_requests",
        "submission": "api:research_os.execution.order_submissions",
        "venue_event": "api:research_os.execution.venue_events",
        "reconciliation": "api:research_os.execution.reconciliations",
        "user_risk_choice": "api:copy_trade.risk_consents.confirm",
    }
    coverages = tuple(
        consent_decision.source_coverage
        if component.component_kind == "user_risk_choice"
        else SimpleNamespace(
            coverage_ref=f"coverage:execution_source:{index}",
            recorded_by="owner-a",
            entry_source="api",
            entrypoint_ref=entrypoint_by_kind[component.component_kind],
            goal_sections=("§12",),
            validation_refs=(
                f"goal_validation_receipt:execution-source:{index}",
            ),
            evidence_refs=(component.component_ref,),
            canonical_command_refs=(component.component_ref,),
            qro_refs=(f"qro_execution_source_{index}",),
            research_graph_command_refs=(f"rgcmd_execution_source_{index}",),
            compiler_ir_refs=(f"compiler_ir:execution-source:{index}",),
            compiler_pass_refs=(f"compiler_pass:execution-source:{index}",),
            silent_mock_fallback_used=False,
            raw_payload_persisted=False,
        )
        for index, component in enumerate(receipt.snapshot.components, start=1)
    )
    coverage_refs = tuple(coverage.coverage_ref for coverage in coverages)
    validation_refs = tuple(
        ref for coverage in coverages for ref in coverage.validation_refs
    )
    producer_refs = tuple(
        ref
        for coverage in coverages
        for ref in (*coverage.qro_refs, *coverage.research_graph_command_refs)
    )
    store_refs = tuple(
        ref
        for coverage in coverages
        for ref in (*coverage.compiler_ir_refs, *coverage.compiler_pass_refs)
    )
    consumer_refs = tuple(
        sorted({coverage.entrypoint_ref for coverage in coverages})
    )
    material = execution_section_semantic_material(
        receipt,
        execution_coverage_refs=coverage_refs,
        execution_validation_refs=validation_refs,
        execution_producer_refs=producer_refs,
        execution_store_refs=store_refs,
        execution_consumer_refs=consumer_refs,
    )

    class CoverageRegistry:
        def coverage(self, ref, *, owner):
            by_ref = {coverage.coverage_ref: coverage for coverage in coverages}
            if ref not in by_ref or owner != "owner-a":
                raise KeyError(ref)
            return by_ref[ref]

        def validate_real_backing(self, record):
            assert record in coverages
            if record is consent_decision.source_coverage:
                return consent_store.validate_source_coverage(record)
            return SimpleNamespace(accepted=True)

    adapter = ExecutionClosureSectionAdapter(
        CoverageRegistry(),
        closure_registry,
    )
    proof = GoalSectionSemanticProofRecord(
        proof_ref="goal_section_semantic_proof:execution:a",
        section="§12",
        subject_ref=material.subject_ref,
        producer_refs=material.producer_refs,
        store_refs=material.store_refs,
        consumer_refs=material.consumer_refs,
        gate_verdict_refs=material.gate_verdict_refs,
        test_refs=material.test_refs,
        entrypoint_coverage_refs=coverage_refs,
        recorded_by="owner-a",
        claims_section_complete=True,
    )

    assert adapter.validate(proof, owner="owner-a").accepted
    rejected = adapter.validate(
        replace(proof, entrypoint_coverage_refs=coverage_refs[:-1]),
        owner="owner-a",
    )
    assert not rejected.accepted

    coverages[0].goal_sections = ("§12", "§14")
    relabelled = adapter.validate(proof, owner="owner-a")
    assert not relabelled.accepted


def test_execution_closure_hash_chain_tamper_is_quarantined_fail_closed(tmp_path):
    registries = _registries(tmp_path)
    flow = _record_flow(registries)
    registry = _closure(tmp_path, registries)
    receipt = registry.record_current(owner_user_id="owner-a", **_receipt_kwargs(flow))
    row = json.loads(registry.path.read_text(encoding="utf-8"))
    row["execution_closure"]["snapshot"]["runtime"] = "live"
    registry.path.write_text(json.dumps(row, sort_keys=True) + "\n", encoding="utf-8")

    reopened = _closure(tmp_path, registries)

    assert reopened.poisoned
    assert reopened.corrupt_quarantined_count == 1
    assert not reopened.validate_current(receipt.receipt_ref, owner_user_id="owner-a").accepted
    with pytest.raises(ExecutionClosureError, match="corrupt"):
        reopened.receipt(receipt.receipt_ref, owner_user_id="owner-a")
