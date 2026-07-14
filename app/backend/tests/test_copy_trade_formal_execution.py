from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from threading import Event
from types import SimpleNamespace

import pytest

from app.approval.schema import ApprovalGate
from app.copy_trade import (
    CopyTradeError,
    CopyTradeService,
    Follower,
    SignalRelayer,
    copy_trade_quota_reservation_ref,
    copy_trade_signal_id,
)
from app.copy_trade.formal_execution import (
    CopyTradeFormalError,
    CopyTradeFormalExecutionCoordinator,
    build_user_risk_choice,
    copy_trade_risk_disclosure_profile,
    runtime_approval_binding_for_follower,
    runtime_requirements_for_follower,
    validate_live_runtime_promotion,
)
from app.copy_trade.gate_binding import relay_nonce
from app.copy_trade.risk_state import CopyTradeRiskError, PersistentFollowerRiskStateStore
from app.execution.base import (
    ExecutionReport,
    Order,
    OrderAck,
    OrderExecutionObservation,
    canonical_raw_event_hash,
)
from app.execution.emergency import AccountExecutionObservation
from app.risk import RiskLimits
from app.research_os import (
    PersistentExecutionOrderIntentRegistry,
    PersistentExecutionOrderMaterializationRegistry,
    PersistentExecutionOrderSubmissionRegistry,
    PersistentExecutionReconciliationRegistry,
    PersistentExecutionSubmitRequestRegistry,
    PersistentExecutionVenueCapabilityRegistry,
    PersistentExecutionVenueConnectivityCheckRegistry,
    PersistentExecutionVenueEventRegistry,
    PersistentExecutionVenueSafetyAttestationRegistry,
    PersistentRuntimePromotionRegistry,
    RuntimePromotionRecord,
)
from app.research_os.execution_boundary import (
    PersistentConsentBackedUserRiskChoiceRegistry,
)
from app.security import InMemoryKeystore, KeystoreRecord, SecureKeystore
from app.security.gate.broker import KeyBroker
from app.security.gate.account_halt import PersistentAccountHaltBarrier
from app.security.gate.nonce import NonceLedger
from app.security.mainnet_guards import MainnetGuardConfig, MainnetGuardsService


class _ApprovalStore:
    def __init__(self, gate: ApprovalGate) -> None:
        self.gate = gate

    def get(self, gate_id: str) -> ApprovalGate:
        if gate_id != self.gate.gate_id:
            raise KeyError(gate_id)
        return self.gate


class _Graph:
    def qro(self, qro_id: str):
        if qro_id != "strategy-qro":
            raise KeyError(qro_id)
        return SimpleNamespace(
            qro_id=qro_id,
            qro_type="StrategyBook",
            owner="master-user",
            allowed_environment="live",
            evidence_status="sufficient",
            governance_status="approved",
            runtime_status="live",
            mock_profile="none",
            evidence_refs=("sig::copy-trade",),
            output_contract={},
        )


class _SignalValidations:
    def validation(self, ref: str, *, owner_user_id: str):
        if ref != "signal-validation" or owner_user_id != "master-user":
            raise KeyError(ref)
        return SimpleNamespace(validation_id=ref, signal_ref="sig::copy-trade", verdict="accepted")


class _MarketData:
    def __init__(self, *, available_owner: str = "master-user") -> None:
        self.available_owner = available_owner
        self.owner_lookups: list[tuple[str, str]] = []

    def use_validation(self, ref: str, *, owner_user_id: str):
        self.owner_lookups.append(("use_validation", owner_user_id))
        if ref != "market-validation" or owner_user_id != self.available_owner:
            raise KeyError(ref)
        return SimpleNamespace(
            validation_ref=ref,
            accepted=True,
            use_context="live",
            instrument_refs=("instrument:BTCUSDT_PERP",),
            recorded_by=self.available_owner,
        )

    def instrument(self, ref: str, *, owner_user_id: str):
        self.owner_lookups.append(("instrument", owner_user_id))
        if ref != "instrument:BTCUSDT_PERP" or owner_user_id != self.available_owner:
            raise KeyError(ref)
        return SimpleNamespace(instrument_ref=ref, asset_class="crypto_perp", venue_symbol="BTCUSDT")


class _FakeVenue:
    def __init__(self, account_ref: str, *, error: Exception | None = None) -> None:
        self.name = f"leased_binance:{account_ref}:mainnet:usdm_futures"
        self.error = error
        self.calls = []

    def get_mark_price(self, symbol: str) -> float:
        return 10_000.0

    def place_order(self, order, *, lease=None):
        self.calls.append((order, lease))
        assert lease is not None
        if self.error is not None:
            raise self.error
        return OrderAck(
            order_id="venue-order-1",
            client_order_id=order.client_order_id,
            status="new",
        )


def _raw_payload(ref: str) -> dict[str, str]:
    return {"fixture_event_ref": ref}


def _raw_hash(ref: str) -> str:
    return canonical_raw_event_hash(_raw_payload(ref))


def _observation(account_ref: str) -> AccountExecutionObservation:
    return AccountExecutionObservation(
        account_ref=account_ref,
        observed_at_utc=datetime.now(UTC).isoformat(),
        source_ref="account-snapshot-1",
        equity=10_000.0,
        positions=(),
        mark_price=10_000.0,
        bid_price=9_999.0,
        ask_price=10_001.0,
        maker_fee_bps=2.0,
        taker_fee_bps=4.0,
        funding_rate_bps=1.0,
        credential_check_ref="credential-check-1",
        ip_allowlist_ref="ip-allowlist-1",
        withdrawal_disabled_ref="withdrawal-disabled-1",
        hmac_replay_protection_ref="nonce-ledger-1",
        health_check_ref="account-health-1",
        rate_limit_ref="rate-limit-1",
        account_identity_source="fapi_v2_balance.accountAlias",
        position_mode="one_way",
        can_trade=True,
        multi_assets_margin=False,
    )


def _state(tmp_path: Path, *, venue_error: Exception | None = None):
    service = CopyTradeService(tmp_path / "copy.db")
    activation_guards = MainnetGuardsService(tmp_path / "copy.db")
    master = service.register_master("master-user", "master", asset_class="crypto_perp")
    provisional = Follower(
        follower_id=f"follower-user::{master.master_id}",
        user_id="follower-user",
        master_id=master.master_id,
        invest_amount=1_000.0,
        per_order_max_usdt=500.0,
        daily_loss_limit_pct=0.05,
        max_positions=5,
        max_leverage=2.0,
        binance_keystore_name="follower-key",
        binance_network="mainnet",
        account_binding_ref="exchange-account-1",
        credential_binding_ref="exchange-credential-1",
    )
    profile = copy_trade_risk_disclosure_profile()
    choice = build_user_risk_choice(
        provisional,
        owner_user_id="follower-user",
        selected_risk_path="small_live",
        risk_disclosure_profile_ref=profile["profile_ref"],
    )
    preliminary_requirements = runtime_requirements_for_follower(
        provisional,
        risk_choice=choice,
    )
    challenge = service.risk_consents.issue_challenge(
        owner_user_id="follower-user",
        follower_id=provisional.follower_id,
        master_id=master.master_id,
        account_binding_ref=provisional.account_binding_ref,
        credential_binding_ref=provisional.credential_binding_ref,
        subject_ref=preliminary_requirements.subject_ref,
        runtime_request_ref=preliminary_requirements.request_ref,
        risk_profile_ref=profile["profile_ref"],
        source_ip_hash=service.risk_consents.source_ip_hash("127.0.0.1"),
        payload={
            "risk_profile": profile,
            "required_acknowledgement_refs": profile["required_acknowledgement_refs"],
            "normalized_risk_limits": {
                "invest_amount": 1_000.0,
                "per_order_max_usdt": 500.0,
                "daily_loss_limit_pct": 0.05,
                "max_positions": 5,
                "max_leverage": 2.0,
            },
            "binance_keystore_name": "follower-key",
            "proposed_user_risk_choice": choice.to_dict(),
        },
    )
    consent_event = service.risk_consents.consume_challenge(
        challenge_ref=challenge.challenge_ref,
        owner_user_id="follower-user",
        user_risk_choice_ref=choice.choice_ref,
        user_risk_choice=choice.to_dict(),
        acknowledged_item_refs=profile["required_acknowledgement_refs"],
        source_ip_hash=service.risk_consents.source_ip_hash("127.0.0.1"),
        password_verified=True,
        totp_verified=False,
    )
    choices = PersistentConsentBackedUserRiskChoiceRegistry(
        service.risk_consents,
        legacy_path=tmp_path / "user_risk_choices.jsonl",
    )
    provisional = replace(
        provisional,
        user_risk_choice_ref=choice.choice_ref,
        user_risk_consent_event_ref=consent_event.consent_event_ref,
    )
    requirements = runtime_requirements_for_follower(provisional, risk_choice=choice)
    approval_binding = runtime_approval_binding_for_follower(
        provisional,
        risk_choice=choice,
    )
    approval = ApprovalGate(
        gate_id="approval-live-1",
        model_id=approval_binding["approval_target_ref"],
        version=1,
        from_stage="testnet",
        to_stage="live",
        channel="confirmatory",
        action_kind="live_order",
        created_by="creator",
        approver="approver",
        evidence={"copy_trade_runtime_approval": approval_binding},
        decision="approved",
    )
    promotions = PersistentRuntimePromotionRegistry(tmp_path / "runtime_promotions.jsonl")
    promotion = promotions.record_promotion(
        RuntimePromotionRecord(
            **requirements.to_dict(),
            asset_class="crypto_perp",
            source_runtime="testnet",
            target_runtime="live",
            testnet_run_ref="testnet-run-1",
            approval_ref=approval.gate_id,
            evidence_refs=(
                "testnet-run-1",
                "testnet-evidence-1",
                choice.choice_ref,
                consent_event.consent_event_ref,
            ),
            recorded_by="approver",
        )
    )
    follower = service.subscribe(
        "follower-user",
        master.master_id,
        invest_amount=1_000.0,
        binance_keystore_name="follower-key",
        binance_network="mainnet",
        per_order_max_usdt=500.0,
        daily_loss_limit_pct=0.05,
        max_positions=5,
        max_leverage=2.0,
        account_binding_ref="exchange-account-1",
        credential_binding_ref="exchange-credential-1",
        runtime_promotion_ref=promotion.runtime_promotion_ref,
        user_risk_choice_ref=choice.choice_ref,
        user_risk_consent_event_ref=consent_event.consent_event_ref,
        initial_status="activating",
    )
    activation_ref = "activation-formal-state-1"
    service.prepare_mainnet_activation(
        activation_ref=activation_ref,
        user_id=follower.user_id,
        master_id=follower.master_id,
        account_binding_ref=follower.account_binding_ref,
        credential_binding_ref=follower.credential_binding_ref,
        runtime_promotion_ref=follower.runtime_promotion_ref,
        user_risk_choice_ref=follower.user_risk_choice_ref,
        user_risk_consent_event_ref=follower.user_risk_consent_event_ref,
        runtime_request_ref=requirements.request_ref,
        risk_profile_ref=profile["profile_ref"],
    )
    follower = service.activate_subscription(
        follower.user_id,
        follower.master_id,
        activation_ref=activation_ref,
        account_binding_ref=follower.account_binding_ref,
        binance_keystore_name=follower.binance_keystore_name,
        credential_binding_ref=follower.credential_binding_ref,
        runtime_promotion_ref=follower.runtime_promotion_ref,
        user_risk_choice_ref=follower.user_risk_choice_ref,
        user_risk_consent_event_ref=follower.user_risk_consent_event_ref,
        runtime_request_ref=requirements.request_ref,
        risk_profile_ref=profile["profile_ref"],
    )
    activation_audit_ref = activation_guards.log_operation(
        follower.user_id,
        "copy_trade_subscription",
        operation_ref=activation_ref,
        result="ok",
    )
    service.mark_mainnet_activation_audited(
        activation_ref,
        activation_audit_ref=activation_audit_ref,
    )
    signal = service.publish_signal(
        master.master_id,
        "master-user",
        symbol="BTCUSDT",
        side="buy",
        quantity=0.01,
        price=10_000.0,
        order_type="limit",
        leverage=2.0,
        strategy_book_qro_id="strategy-qro",
        signal_validation_ref="signal-validation",
        market_data_use_validation_ref="market-validation",
        instrument_ref="instrument:BTCUSDT_PERP",
    )
    registries = SimpleNamespace(
        intents=PersistentExecutionOrderIntentRegistry(tmp_path / "intents.jsonl"),
        materializations=PersistentExecutionOrderMaterializationRegistry(tmp_path / "materializations.jsonl"),
        connectivity=PersistentExecutionVenueConnectivityCheckRegistry(tmp_path / "connectivity.jsonl"),
        safety=PersistentExecutionVenueSafetyAttestationRegistry(tmp_path / "safety.jsonl"),
        capabilities=PersistentExecutionVenueCapabilityRegistry(tmp_path / "capabilities.jsonl"),
        requests=PersistentExecutionSubmitRequestRegistry(tmp_path / "requests.jsonl"),
        submissions=PersistentExecutionOrderSubmissionRegistry(tmp_path / "submissions.jsonl"),
        events=PersistentExecutionVenueEventRegistry(tmp_path / "events.jsonl"),
        reconciliations=PersistentExecutionReconciliationRegistry(tmp_path / "reconciliations.jsonl"),
    )
    risk = PersistentFollowerRiskStateStore(
        tmp_path / "risk.sqlite3",
        reconciliation_store=registries.reconciliations,
        venue_event_store=registries.events,
    )
    market_data = _MarketData()
    coordinator = CopyTradeFormalExecutionCoordinator(
        runtime_promotions=promotions,
        user_risk_choices=choices,
        order_intents=registries.intents,
        materializations=registries.materializations,
        connectivity_checks=registries.connectivity,
        safety_attestations=registries.safety,
        capabilities=registries.capabilities,
        submit_requests=registries.requests,
        submissions=registries.submissions,
        venue_events=registries.events,
        reconciliations=registries.reconciliations,
        signal_validations=_SignalValidations(),
        market_data_registry=market_data,
        research_graph=_Graph(),
        approval_store=_ApprovalStore(approval),
        risk_store=risk,
        observation_provider=lambda _follower, _symbol: _observation("exchange-account-1"),
        active_account_provider=lambda: ("exchange-account-1",),
        consent_authority_provider=lambda item, _choice: (
            service.mainnet_capability_account_status(
                item.user_id,
                item.account_binding_ref,
                item.binance_keystore_name,
                item.credential_binding_ref,
                require_audited_activation=True,
            )
            == "active"
        ),
        master_provider=service.get_master,
        testnet_evidence_provider=lambda ref, _follower: ref == "testnet-run-1",
    )
    backend = InMemoryKeystore()
    backend.store(KeystoreRecord(name="follower-key", api_key="same-account", api_secret="secret"))
    keystore = SecureKeystore(backend)
    halt_barrier = PersistentAccountHaltBarrier(tmp_path / "account-halt.sqlite3")
    halt_barrier.activate(follower.account_binding_ref, follower.user_id)
    broker = KeyBroker(
        keystore,
        hmac_key=b"x" * 32,
        account_halt_barrier=halt_barrier,
    )
    nonce = NonceLedger(tmp_path / "nonce")
    guards = MainnetGuardsService(tmp_path / "mainnet-guards.sqlite3")
    guards.upsert_config(
        MainnetGuardConfig(
            user_id=follower.user_id,
            daily_operation_limit=100,
            daily_notional_limit_usdt=1_000_000,
            require_password_per_order=False,
        )
    )
    venue = _FakeVenue(follower.account_binding_ref, error=venue_error)
    relayer = SignalRelayer(
        service,
        keystore,
        lambda _follower, _keystore: venue,
        enforce_gate=True,
        broker=broker,
        nonce_ledger=nonce,
        formal_coordinator=coordinator,
        mainnet_guards=guards,
        mainnet_readiness_provider=lambda: True,
    )
    return SimpleNamespace(
        service=service,
        master=master,
        follower=follower,
        signal=signal,
        venue=venue,
        relayer=relayer,
        coordinator=coordinator,
        registries=registries,
        risk=risk,
        broker=broker,
        keystore=keystore,
        guards=guards,
        halt_barrier=halt_barrier,
        market_data=market_data,
    )


def _prepare_without_venue(state):
    order = Order(
        venue=f"leased_binance:{state.follower.account_binding_ref}:mainnet:usdm_futures",
        symbol=state.signal.symbol,
        side=state.signal.side,
        quantity=state.signal.quantity,
        order_type=state.signal.order_type,
        price=state.signal.price,
        leverage=state.signal.leverage,
        client_order_id=relay_nonce(state.signal.signal_id, state.follower.follower_id),
    )
    return state.coordinator.prepare(
        follower=state.follower,
        signal=state.signal,
        order=order,
        actor="copy_trade_signal_relayer",
    )


def _restart_risk_store(state, tmp_path: Path) -> PersistentFollowerRiskStateStore:
    return PersistentFollowerRiskStateStore(
        tmp_path / "risk.sqlite3",
        reconciliation_store=state.registries.reconciliations,
        venue_event_store=state.registries.events,
    )


def _reload_projection_state(state, tmp_path: Path):
    promotions = PersistentRuntimePromotionRegistry(tmp_path / "runtime_promotions.jsonl")
    choices = PersistentConsentBackedUserRiskChoiceRegistry(
        state.service.risk_consents,
        legacy_path=tmp_path / "user_risk_choices.jsonl",
    )
    registries = SimpleNamespace(
        intents=PersistentExecutionOrderIntentRegistry(tmp_path / "intents.jsonl"),
        materializations=PersistentExecutionOrderMaterializationRegistry(tmp_path / "materializations.jsonl"),
        connectivity=PersistentExecutionVenueConnectivityCheckRegistry(tmp_path / "connectivity.jsonl"),
        safety=PersistentExecutionVenueSafetyAttestationRegistry(tmp_path / "safety.jsonl"),
        capabilities=PersistentExecutionVenueCapabilityRegistry(tmp_path / "capabilities.jsonl"),
        requests=PersistentExecutionSubmitRequestRegistry(tmp_path / "requests.jsonl"),
        submissions=PersistentExecutionOrderSubmissionRegistry(tmp_path / "submissions.jsonl"),
        events=PersistentExecutionVenueEventRegistry(tmp_path / "events.jsonl"),
        reconciliations=PersistentExecutionReconciliationRegistry(tmp_path / "reconciliations.jsonl"),
    )
    risk = PersistentFollowerRiskStateStore(
        tmp_path / "risk.sqlite3",
        reconciliation_store=registries.reconciliations,
        venue_event_store=registries.events,
    )
    coordinator = CopyTradeFormalExecutionCoordinator(
        runtime_promotions=promotions,
        user_risk_choices=choices,
        order_intents=registries.intents,
        materializations=registries.materializations,
        connectivity_checks=registries.connectivity,
        safety_attestations=registries.safety,
        capabilities=registries.capabilities,
        submit_requests=registries.requests,
        submissions=registries.submissions,
        venue_events=registries.events,
        reconciliations=registries.reconciliations,
        signal_validations=_SignalValidations(),
        market_data_registry=_MarketData(),
        research_graph=_Graph(),
        approval_store=state.coordinator._approval_store,
        risk_store=risk,
        observation_provider=lambda _follower, _symbol: _observation("exchange-account-1"),
        active_account_provider=lambda: ("exchange-account-1",),
        consent_authority_provider=lambda item, _choice: (
            state.service.mainnet_capability_account_status(
                item.user_id,
                item.account_binding_ref,
                item.binance_keystore_name,
                item.credential_binding_ref,
                require_audited_activation=True,
            )
            == "active"
        ),
        master_provider=state.service.get_master,
        testnet_evidence_provider=lambda ref, _follower: ref == "testnet-run-1",
    )
    return SimpleNamespace(coordinator=coordinator, registries=registries, risk=risk)


def _replay_all_formal_attempts(restarted) -> list[dict[str, str]]:
    return [
        restarted.coordinator.ensure_formal_projection(attempt)
        for attempt in restarted.risk.formal_projection_attempts()
    ]


def test_live_relay_persists_one_content_bound_formal_chain(tmp_path: Path) -> None:
    state = _state(tmp_path)
    result = state.relayer.relay(state.signal)[0]
    assert result["status"] == "placed"
    assert len(state.venue.calls) == 1
    assert len(state.registries.intents.intents()) == 1
    assert len(state.registries.materializations.materializations()) == 1
    assert len(state.registries.connectivity.checks()) == 1
    assert len(state.registries.safety.attestations()) == 1
    assert len(state.registries.capabilities.capabilities()) == 1
    assert len(state.registries.requests.requests()) == 1
    usage = state.guards.get_today_usage(state.follower.user_id)
    assert usage["operations_today"] == 1
    assert usage["notional_today_usdt"] == pytest.approx(100.0)
    submission = state.registries.submissions.submissions()[0]
    event = state.registries.events.events()[0]
    reconciliation = state.registries.reconciliations.reconciliations()[0]
    assert event.submission_ref == submission.submission_ref
    assert reconciliation.submission_ref == submission.submission_ref
    assert reconciliation.status == "open"


def test_copy_trade_market_data_resolution_uses_master_user_id(tmp_path: Path) -> None:
    state = _state(tmp_path)

    prepared = _prepare_without_venue(state)

    assert prepared.intent.instrument_ref == "instrument:BTCUSDT_PERP"
    assert state.market_data.owner_lookups == [
        ("use_validation", state.master.user_id),
        ("instrument", state.master.user_id),
    ]


def test_copy_trade_foreign_owner_market_data_ref_fails_before_venue(tmp_path: Path) -> None:
    state = _state(tmp_path)
    state.coordinator._market_data = _MarketData(available_owner="foreign-master-user")

    result = state.relayer.relay(state.signal)[0]

    assert result["status"] == "rejected"
    assert "market data validation cannot be resolved for the master owner" in result["reason"]
    assert state.venue.calls == []


def test_runtime_approval_cannot_be_replayed_for_different_risk_limits(tmp_path: Path) -> None:
    state = _state(tmp_path)
    changed_follower = replace(
        state.follower,
        per_order_max_usdt=state.follower.per_order_max_usdt + 1.0,
    )
    profile = copy_trade_risk_disclosure_profile()
    changed_choice = build_user_risk_choice(
        changed_follower,
        owner_user_id=changed_follower.user_id,
        selected_risk_path="small_live",
        risk_disclosure_profile_ref=profile["profile_ref"],
    )
    changed_requirements = runtime_requirements_for_follower(
        changed_follower,
        risk_choice=changed_choice,
    )
    changed_promotion = RuntimePromotionRecord(
        **changed_requirements.to_dict(),
        asset_class="crypto_perp",
        source_runtime="testnet",
        target_runtime="live",
        testnet_run_ref="testnet-run-2",
        approval_ref="approval-live-1",
        evidence_refs=("testnet-run-2", changed_choice.choice_ref),
    )

    with pytest.raises(CopyTradeFormalError, match="approval_request_mismatch"):
        validate_live_runtime_promotion(
            changed_promotion,
            changed_follower,
            risk_choice=changed_choice,
            approval_store=state.coordinator._approval_store,
        )


def test_live_relay_requires_standing_auto_copy_authorization_before_key_or_venue(tmp_path: Path) -> None:
    state = _state(tmp_path)
    state.guards.upsert_config(
        MainnetGuardConfig(
            user_id=state.follower.user_id,
            daily_operation_limit=100,
            daily_notional_limit_usdt=1_000_000,
            require_password_per_order=True,
        )
    )
    fetched: list[str] = []
    original = state.keystore.fetch
    state.keystore.fetch = lambda name: (fetched.append(name), original(name))[1]

    result = state.relayer.relay(state.signal)[0]

    assert result["status"] == "rejected"
    assert "standing_auto_copy_authorization_required" in result["reason"]
    assert state.venue.calls == []
    assert fetched == []


def test_live_relay_daily_quota_rejects_before_key_or_venue(tmp_path: Path) -> None:
    state = _state(tmp_path)
    state.guards.upsert_config(
        MainnetGuardConfig(
            user_id=state.follower.user_id,
            daily_operation_limit=100,
            daily_notional_limit_usdt=50,
            require_password_per_order=False,
        )
    )
    fetched: list[str] = []
    original = state.keystore.fetch
    state.keystore.fetch = lambda name: (fetched.append(name), original(name))[1]

    result = state.relayer.relay(state.signal)[0]

    assert result["status"] == "rejected"
    assert "mainnet_daily_quota_rejected" in result["reason"]
    assert state.venue.calls == []
    assert fetched == []


def test_old_process_pre_submit_reject_releases_stranded_quota(monkeypatch, tmp_path: Path) -> None:
    from app import main as app_main

    state = _state(tmp_path)
    prepared = _prepare_without_venue(state)
    quota_ref = copy_trade_quota_reservation_ref(
        state.signal.signal_id,
        state.follower.follower_id,
        prepared.reservation.client_order_id,
    )
    state.guards.reserve_operation(
        state.follower.user_id,
        "copy_trade_live_order",
        reservation_ref=quota_ref,
        notional_usdt=prepared.reservation.notional_usdt,
    )
    state.risk.mark_definitive_reject(
        prepared.reservation,
        reason_ref="pre_submit_crash_reject",
    )
    restarted = _restart_risk_store(state, tmp_path)
    monkeypatch.setattr(app_main, "FOLLOWER_RISK_STATE", restarted)
    monkeypatch.setattr(app_main, "MAINNET_GUARDS", state.guards)

    recovery = app_main._recover_copy_trade_quota_reservations()

    assert recovery == {"pending": 1, "settled": 0, "released": 1, "skipped": 0, "failures": 0}
    assert state.guards.reserved_operations(operation="copy_trade_live_order") == ()
    assert state.guards.get_today_usage(state.follower.user_id)["operations_today"] == 0


def test_old_process_order_request_marker_settles_stranded_quota_as_unknown(
    monkeypatch,
    tmp_path: Path,
) -> None:
    from app import main as app_main

    state = _state(tmp_path)
    prepared = _prepare_without_venue(state)
    quota_ref = copy_trade_quota_reservation_ref(
        state.signal.signal_id,
        state.follower.follower_id,
        prepared.reservation.client_order_id,
    )
    state.guards.reserve_operation(
        state.follower.user_id,
        "copy_trade_live_order",
        reservation_ref=quota_ref,
        notional_usdt=prepared.reservation.notional_usdt,
    )
    state.coordinator.mark_order_request_started(prepared)
    restarted = _restart_risk_store(state, tmp_path)
    monkeypatch.setattr(app_main, "FOLLOWER_RISK_STATE", restarted)
    monkeypatch.setattr(app_main, "MAINNET_GUARDS", state.guards)

    recovery = app_main._recover_copy_trade_quota_reservations()

    assert recovery == {"pending": 1, "settled": 1, "released": 0, "skipped": 0, "failures": 0}
    usage = state.guards.get_today_usage(state.follower.user_id)
    assert usage["operations_today"] == 1
    assert usage["notional_today_usdt"] == pytest.approx(prepared.reservation.notional_usdt)
    audit = state.guards.list_audit_log(state.follower.user_id)
    assert audit[0]["result"] == "outcome_unknown"
    assert audit[0]["error"] == "recovered_after_process_boundary"


def test_quota_recovery_missing_risk_evidence_stays_reserved(monkeypatch, tmp_path: Path) -> None:
    from app import main as app_main

    state = _state(tmp_path)
    state.guards.reserve_operation(
        state.follower.user_id,
        "copy_trade_live_order",
        reservation_ref="mainnet_quota_unbound_mutation",
        notional_usdt=25.0,
    )
    restarted = _restart_risk_store(state, tmp_path)
    monkeypatch.setattr(app_main, "FOLLOWER_RISK_STATE", restarted)
    monkeypatch.setattr(app_main, "MAINNET_GUARDS", state.guards)

    recovery = app_main._recover_copy_trade_quota_reservations()

    assert recovery["failures"] == 1
    assert recovery["settled"] == recovery["released"] == 0
    assert [item.reservation_ref for item in state.guards.reserved_operations()] == [
        "mainnet_quota_unbound_mutation"
    ]


def test_quota_recovery_never_steals_current_process_reservation(monkeypatch, tmp_path: Path) -> None:
    from app import main as app_main

    state = _state(tmp_path)
    prepared = _prepare_without_venue(state)
    quota_ref = copy_trade_quota_reservation_ref(
        state.signal.signal_id,
        state.follower.follower_id,
        prepared.reservation.client_order_id,
    )
    state.guards.reserve_operation(
        state.follower.user_id,
        "copy_trade_live_order",
        reservation_ref=quota_ref,
        notional_usdt=prepared.reservation.notional_usdt,
    )
    monkeypatch.setattr(app_main, "FOLLOWER_RISK_STATE", state.risk)
    monkeypatch.setattr(app_main, "MAINNET_GUARDS", state.guards)

    recovery = app_main._recover_copy_trade_quota_reservations()

    assert recovery == {"pending": 1, "settled": 0, "released": 0, "skipped": 1, "failures": 0}
    assert [item.reservation_ref for item in state.guards.reserved_operations()] == [quota_ref]


def test_live_relay_without_formal_coordinator_never_calls_venue(tmp_path: Path) -> None:
    state = _state(tmp_path)
    state.relayer._formal = None
    result = state.relayer.relay(state.signal)[0]
    assert result == {
        "follower_id": state.follower.follower_id,
        "status": "rejected",
        "reason": "formal_execution_unavailable",
    }
    assert state.venue.calls == []


def test_pre_submit_append_failure_leaves_no_memory_phantom_or_venue_call(tmp_path: Path, monkeypatch) -> None:
    state = _state(tmp_path)

    def fail_append(_record):
        raise OSError("disk full")

    monkeypatch.setattr(state.registries.materializations, "_append", fail_append)
    result = state.relayer.relay(state.signal)[0]
    assert result["status"] == "failed"
    assert state.venue.calls == []
    assert state.registries.materializations.materializations() == []
    replayed = PersistentFollowerRiskStateStore(tmp_path / "risk.sqlite3")
    risk_state = replayed.state(state.follower.follower_id, state.follower.account_binding_ref)
    assert risk_state.reserved_turnover == 0
    assert risk_state.open_reservation_refs == ()


def test_venue_exception_is_outcome_unknown_without_fabricated_event(tmp_path: Path) -> None:
    state = _state(tmp_path, venue_error=TimeoutError("no ack"))
    result = state.relayer.relay(state.signal)[0]
    assert result["status"] == "outcome_unknown"
    assert len(state.venue.calls) == 1
    assert state.registries.events.events() == []
    reconciliation = state.registries.reconciliations.reconciliations()[0]
    assert reconciliation.status == "missing_events"
    replayed = PersistentFollowerRiskStateStore(tmp_path / "risk.sqlite3")
    risk_state = replayed.state(state.follower.follower_id, state.follower.account_binding_ref)
    assert risk_state.reserved_turnover == pytest.approx(100.0)
    assert risk_state.open_reservation_refs


def test_started_attempt_without_submission_repairs_to_outcome_unknown(tmp_path: Path) -> None:
    state = _state(tmp_path)
    prepared = _prepare_without_venue(state)
    state.coordinator.mark_order_request_started(prepared)
    binding = state.risk.submission_binding_for_reservation(prepared.reservation.reservation_ref)
    assert binding["state"] == "order_request_started"

    repaired = state.coordinator.ensure_started_attempt_projection(
        prepared.reservation,
        binding,
    )
    rebound = state.risk.submission_binding_for_reservation(prepared.reservation.reservation_ref)

    assert repaired["formal_status"] == "outcome_unknown"
    assert rebound["state"] == "submission_unknown"
    assert rebound["submission_ref"] == repaired["submission_ref"]
    assert state.registries.submissions.submission(repaired["submission_ref"]).submission_status == (
        "outcome_unknown"
    )
    assert state.risk.state(
        state.follower.follower_id,
        state.follower.account_binding_ref,
    ).open_reservation_refs


def test_ack_risk_commit_with_missing_jsonl_projection_is_repairable(
    tmp_path: Path,
    monkeypatch,
) -> None:
    state = _state(tmp_path)
    prepared = _prepare_without_venue(state)
    state.coordinator.mark_order_request_started(prepared)
    original_append = state.registries.submissions._append
    monkeypatch.setattr(
        state.registries.submissions,
        "_append",
        lambda _record: (_ for _ in ()).throw(OSError("simulated process death before JSONL append")),
    )
    ack = OrderAck(
        order_id="venue-order-1",
        client_order_id=prepared.reservation.client_order_id,
        status="new",
    )
    with pytest.raises(OSError, match="simulated process death"):
        state.coordinator.record_success(
            prepared,
            ack=ack,
            actor="copy_trade_signal_relayer",
        )
    binding = state.risk.submission_binding_for_reservation(prepared.reservation.reservation_ref)
    assert binding["state"] == "submission_accepted"
    assert state.registries.submissions.submissions() == []

    monkeypatch.setattr(state.registries.submissions, "_append", original_append)
    repaired = state.coordinator.ensure_started_attempt_projection(
        prepared.reservation,
        binding,
    )

    assert repaired["formal_status"] == "accepted"
    assert repaired["submission_ref"] == binding["submission_ref"]
    assert state.registries.submissions.submission(binding["submission_ref"]).submission_status == (
        "accepted"
    )
    assert len(state.registries.events.events()) == 1
    assert len(state.registries.reconciliations.reconciliations()) == 1


@pytest.mark.parametrize(
    ("ack_status", "failure_seam"),
    (
        ("new", "submission"),
        ("new", "event"),
        ("new", "reconciliation"),
        ("new", "completion"),
        ("rejected", "submission"),
        ("rejected", "event"),
        ("rejected", "reconciliation"),
        ("rejected", "completion"),
    ),
)
def test_ack_projection_outbox_repairs_every_crash_seam_after_restart(
    tmp_path: Path,
    monkeypatch,
    ack_status: str,
    failure_seam: str,
) -> None:
    state = _state(tmp_path)
    prepared = _prepare_without_venue(state)
    state.coordinator.mark_order_request_started(prepared)

    def fail(*_args, **_kwargs):
        raise OSError(f"crash at {failure_seam}")

    if failure_seam == "submission":
        monkeypatch.setattr(state.registries.submissions, "_append", fail)
    elif failure_seam == "event":
        monkeypatch.setattr(state.registries.events, "_append", fail)
    elif failure_seam == "reconciliation":
        monkeypatch.setattr(state.registries.reconciliations, "_append", fail)
    else:
        monkeypatch.setattr(state.risk, "mark_formal_projection_completed", fail)

    with pytest.raises(OSError, match=f"crash at {failure_seam}"):
        state.coordinator.record_success(
            prepared,
            ack=OrderAck(
                order_id="venue-order-1" if ack_status != "rejected" else "reject-order-1",
                client_order_id=prepared.reservation.client_order_id,
                status=ack_status,
            ),
            actor="copy_trade_signal_relayer",
        )

    # A venue rejection is terminal for exposure, but its sealed outbox row is
    # still discoverable and repairable after restart.
    if ack_status == "rejected":
        assert state.risk.unresolved_reservations() == ()

    restarted = _reload_projection_state(state, tmp_path)
    attempts = restarted.risk.formal_projection_attempts(
        follower_id=state.follower.follower_id,
        account_binding_ref=state.follower.account_binding_ref,
    )
    assert len(attempts) == 1
    repaired = restarted.coordinator.ensure_formal_projection(attempts[0])

    assert repaired["formal_status"] == ("rejected" if ack_status == "rejected" else "accepted")
    assert len(restarted.registries.submissions.submissions()) == 1
    assert len(restarted.registries.events.events()) == 1
    assert len(restarted.registries.reconciliations.reconciliations()) == 1
    assert restarted.registries.events.events()[0].event_kind == (
        "rejected" if ack_status == "rejected" else "accepted"
    )
    replayed_attempt = restarted.risk.formal_projection_attempts()[0]
    assert replayed_attempt["completed"]["submission_ref"] == repaired["submission_ref"]


def test_local_preflight_failure_is_definitive_before_order_request(tmp_path: Path) -> None:
    state = _state(tmp_path)
    boundary_calls: list[str] = []

    def preflight_failure(order, *, lease=None, before_order_request=None):
        state.venue.calls.append((order, lease))
        assert before_order_request is not None
        boundary_calls.append("preflight")
        raise ConnectionError("position-mode check failed before order POST")

    state.venue.place_order = preflight_failure
    result = state.relayer.relay(state.signal)[0]

    assert result["status"] == "rejected"
    assert boundary_calls == ["preflight"]
    execution = state.service.list_executions(signal_id=state.signal.signal_id)[0]
    assert execution.status == "rejected"
    risk_state = state.risk.state(state.follower.follower_id, state.follower.account_binding_ref)
    assert risk_state.open_reservation_refs == ()
    assert risk_state.reserved_turnover == 0


def test_order_request_marker_failure_is_definitive_and_never_calls_venue(
    tmp_path: Path,
    monkeypatch,
) -> None:
    state = _state(tmp_path)
    venue_calls: list[str] = []

    def marker_failure(_prepared):
        raise OSError("risk ledger fsync failed")

    def venue_boundary(order, *, lease=None, before_order_request=None):
        assert before_order_request is not None
        before_order_request(order)
        venue_calls.append("order_post")
        return OrderAck(
            order_id="must-not-exist",
            client_order_id=order.client_order_id,
            status="new",
        )

    monkeypatch.setattr(state.coordinator, "mark_order_request_started", marker_failure)
    state.venue.place_order = venue_boundary

    result = state.relayer.relay(state.signal)[0]

    assert result["status"] == "rejected"
    assert venue_calls == []
    assert state.risk.order_request_context(
        state.risk.events(state.follower.follower_id)[-1]["reservation_ref"]
    ) is None
    risk_state = state.risk.state(state.follower.follower_id, state.follower.account_binding_ref)
    assert risk_state.open_reservation_refs == ()
    assert risk_state.reserved_turnover == 0


def test_account_binding_aliases_collide_and_service_rejects_second_live_follower(tmp_path: Path) -> None:
    backend = InMemoryKeystore()
    backend.store(KeystoreRecord(name="alias-a", api_key="same", api_secret="secret"))
    backend.store(KeystoreRecord(name="alias-b", api_key="same", api_secret="secret"))
    broker = KeyBroker(SecureKeystore(backend), hmac_key=b"k" * 32)
    account_ref = broker.account_binding_ref("alias-a")
    assert account_ref == broker.account_binding_ref("alias-b")

    service = CopyTradeService(tmp_path / "account-collision.sqlite3")
    first_master = service.register_master("master-a", "A", asset_class="crypto_perp")
    second_master = service.register_master("master-b", "B", asset_class="crypto_perp")
    service.subscribe(
        "follower-a",
        first_master.master_id,
        invest_amount=100,
        binance_keystore_name="alias-a",
        binance_network="mainnet",
        max_leverage=2,
        account_binding_ref=account_ref,
        runtime_promotion_ref="promotion-a",
        user_risk_choice_ref="risk-choice-a",
    )
    assert service.unsubscribe("follower-a", first_master.master_id)

    with pytest.raises(CopyTradeError, match="历史占用"):
        service.subscribe(
            "follower-b",
            second_master.master_id,
            invest_amount=100,
            binance_keystore_name="alias-b",
            binance_network="mainnet",
            max_leverage=2,
            account_binding_ref=account_ref,
            runtime_promotion_ref="promotion-b",
            user_risk_choice_ref="risk-choice-b",
        )


def test_credential_binding_detects_secret_only_swap() -> None:
    backend = InMemoryKeystore()
    backend.store(KeystoreRecord(name="original", api_key="same-key", api_secret="secret-a"))
    backend.store(KeystoreRecord(name="swapped", api_key="same-key", api_secret="secret-b"))
    broker = KeyBroker(SecureKeystore(backend), hmac_key=b"k" * 32)

    original = broker.credential_binding_ref("original")
    swapped = broker.credential_binding_ref("swapped")
    assert original.startswith("exchange_credential_v2_")
    assert swapped.startswith("exchange_credential_v2_")
    assert original != swapped


def test_stopped_mainnet_follower_cannot_rebind_a_different_account(tmp_path: Path) -> None:
    service = CopyTradeService(tmp_path / "immutable-account.sqlite3")
    master = service.register_master("master-a", "A", asset_class="crypto_perp")
    service.subscribe(
        "follower-a",
        master.master_id,
        invest_amount=100,
        binance_keystore_name="key-a",
        binance_network="mainnet",
        max_leverage=2,
        account_binding_ref="account-a",
        runtime_promotion_ref="promotion-a",
        user_risk_choice_ref="risk-choice-a",
    )
    assert service.unsubscribe("follower-a", master.master_id)

    with pytest.raises(CopyTradeError, match="immutable"):
        service.subscribe(
            "follower-a",
            master.master_id,
            invest_amount=100,
            binance_keystore_name="key-b",
            binance_network="mainnet",
            max_leverage=2,
            account_binding_ref="account-b",
            runtime_promotion_ref="promotion-b",
            user_risk_choice_ref="risk-choice-b",
        )


def test_account_binding_is_stable_across_broker_restart(tmp_path: Path) -> None:
    backend = InMemoryKeystore()
    backend.store(KeystoreRecord(name="account", api_key="same", api_secret="secret"))
    keystore = SecureKeystore(backend)
    key_path = tmp_path / "security" / "broker.key"

    first = KeyBroker(keystore, hmac_key_path=key_path).account_binding_ref("account")
    second = KeyBroker(keystore, hmac_key_path=key_path).account_binding_ref("account")

    assert first == second
    assert key_path.stat().st_mode & 0o777 == 0o600


def test_broker_rejects_existing_broad_hmac_key_permissions(tmp_path: Path) -> None:
    backend = InMemoryKeystore()
    backend.store(KeystoreRecord(name="account", api_key="key", api_secret="secret"))
    key_path = tmp_path / "security" / "broker.key"
    key_path.parent.mkdir(mode=0o700)
    key_path.write_bytes(b"k" * 32)
    key_path.chmod(0o644)

    with pytest.raises(ValueError, match="mode 0600"):
        KeyBroker(SecureKeystore(backend), hmac_key_path=key_path)


def test_venue_uid_identity_survives_key_rotation_and_distinguishes_accounts(tmp_path: Path) -> None:
    backend = InMemoryKeystore()
    backend.store(KeystoreRecord(name="old-key", api_key="old", api_secret="secret"))
    backend.store(KeystoreRecord(name="new-key", api_key="new", api_secret="secret"))
    broker = KeyBroker(SecureKeystore(backend), hmac_key_path=tmp_path / "broker.key")

    assert broker.credential_binding_ref("old-key") != broker.credential_binding_ref("new-key")
    first = broker.account_identity_ref(
        venue="binance",
        network="mainnet",
        product="usdm_futures",
        venue_account_uid="account-123",
    )
    rotated = broker.account_identity_ref(
        venue="binance",
        network="mainnet",
        product="usdm_futures",
        venue_account_uid="account-123",
    )
    other = broker.account_identity_ref(
        venue="binance",
        network="mainnet",
        product="usdm_futures",
        venue_account_uid="account-456",
    )
    assert first == rotated
    assert first.startswith("exchange_account_uid_")
    assert first != other

    with pytest.raises(PermissionError, match="venue-issued account UID"):
        broker.account_identity_ref(
            venue="binance",
            network="mainnet",
            product="usdm_futures",
            venue_account_uid="",
        )


def test_ack_filled_is_not_treated_as_fill_evidence(tmp_path: Path) -> None:
    state = _state(tmp_path)
    state.venue.error = None

    def filled_ack(order, *, lease=None):
        state.venue.calls.append((order, lease))
        return OrderAck(order_id="venue-order-1", client_order_id=order.client_order_id, status="filled")

    state.venue.place_order = filled_ack
    result = state.relayer.relay(state.signal)[0]
    assert result["status"] == "needs_reconcile"
    event = state.registries.events.events()[0]
    assert event.event_kind == "accepted"
    assert event.fill_ref is None
    risk_state = state.risk.state(state.follower.follower_id, state.follower.account_binding_ref)
    assert risk_state.open_reservation_refs


@pytest.mark.parametrize("ack_status", ["canceled", "expired"])
def test_terminal_ack_without_fill_evidence_stays_outcome_unknown(
    tmp_path: Path,
    ack_status: str,
) -> None:
    state = _state(tmp_path)

    def terminal_ack(order, *, lease=None):
        state.venue.calls.append((order, lease))
        return OrderAck(
            order_id="venue-order-1",
            client_order_id=order.client_order_id,
            status=ack_status,
        )

    state.venue.place_order = terminal_ack
    result = state.relayer.relay(state.signal)[0]

    assert result["status"] == "outcome_unknown"
    assert state.registries.events.events() == []
    risk_state = state.risk.state(state.follower.follower_id, state.follower.account_binding_ref)
    assert risk_state.open_reservation_refs


def test_source_identified_execution_report_records_formal_fill_and_closes_risk(tmp_path: Path) -> None:
    state = _state(tmp_path)
    placed = state.relayer.relay(state.signal)[0]
    assert placed["status"] == "placed"
    client_order_id = state.venue.calls[0][0].client_order_id

    result = state.coordinator.record_execution_report(
        ExecutionReport(
            order_id="venue-order-1",
            client_order_id=client_order_id,
            symbol="BTCUSDT",
            side="buy",
            filled_qty=0.01,
            cumulative_filled_qty=0.01,
            fill_price=10_000.0,
            commission=0.04,
            commission_asset="USDT",
            status="filled",
            timestamp_utc=datetime.now(UTC).isoformat(),
            source_event_ref="binance_execution_trade_1",
            raw=_raw_payload("raw-event-1"),
            raw_event_hash=_raw_hash("raw-event-1"),
        ),
        actor="binance_execution_reconciler",
        normalized_cost_usdt=0.04,
        cost_conversion_ref="cost_conversion_usdt_identity",
    )

    assert result["formal_status"] == "filled"
    assert state.registries.events.event(result["venue_event_ref"]).event_kind == "filled"
    risk_state = state.risk.state(state.follower.follower_id, state.follower.account_binding_ref)
    assert risk_state.open_reservation_refs == ()
    assert risk_state.filled_turnover == pytest.approx(100.0)


def test_execution_report_rejects_mismatched_expected_submission_before_projection(
    tmp_path: Path,
) -> None:
    state = _state(tmp_path)
    placed = state.relayer.relay(state.signal)[0]
    client_order_id = state.venue.calls[0][0].client_order_id
    report = ExecutionReport(
        order_id="venue-order-1",
        client_order_id=client_order_id,
        symbol="BTCUSDT",
        side="buy",
        filled_qty=0.01,
        cumulative_filled_qty=0.01,
        fill_price=10_000.0,
        commission=0.04,
        commission_asset="USDT",
        status="filled",
        timestamp_utc=datetime.now(UTC).isoformat(),
        source_event_ref="binance_execution_expected_submission_guard",
        raw=_raw_payload("expected-submission-guard"),
        raw_event_hash=_raw_hash("expected-submission-guard"),
    )
    before_events = tuple(state.registries.events.events())

    with pytest.raises(
        CopyTradeFormalError,
        match="exactly one risk-bound submission",
    ):
        state.coordinator.record_execution_report(
            report,
            actor="binance_execution_reconciler",
            expected_submission_ref="order_submission_v2_foreign",
            normalized_cost_usdt=0.04,
            cost_conversion_ref="cost_conversion_usdt_identity",
        )

    assert tuple(state.registries.events.events()) == before_events
    result = state.coordinator.record_execution_report(
        report,
        actor="binance_execution_reconciler",
        expected_submission_ref=placed["submission_ref"],
        normalized_cost_usdt=0.04,
        cost_conversion_ref="cost_conversion_usdt_identity",
    )
    assert result["formal_status"] == "filled"


def test_terminal_order_observation_closes_zero_fill_reservation(tmp_path: Path) -> None:
    state = _state(tmp_path)
    placed = state.relayer.relay(state.signal)[0]
    assert placed["status"] == "placed"
    client_order_id = state.venue.calls[0][0].client_order_id
    observation = OrderExecutionObservation(
        order_id="venue-order-1",
        client_order_id=client_order_id,
        symbol="BTCUSDT",
        side="buy",
        status="canceled",
        requested_qty=0.01,
        cumulative_filled_qty=0,
        observed_at_utc=datetime.now(UTC).isoformat(),
        source_event_ref="binance_order_terminal_zero_1",
        raw=_raw_payload("terminal-zero-1"),
        raw_event_hash=_raw_hash("terminal-zero-1"),
    )

    result = state.coordinator.record_order_observation(
        observation,
        actor="binance_execution_reconciler",
    )
    repeated = state.coordinator.record_order_observation(
        observation,
        actor="binance_execution_reconciler",
    )

    assert result == repeated
    assert result["formal_status"] == "closed_no_fill"
    assert state.registries.reconciliations.reconciliation(
        result["reconciliation_ref"]
    ).status == "closed_no_fill"
    risk_state = state.risk.state(state.follower.follower_id, state.follower.account_binding_ref)
    assert risk_state.open_reservation_refs == ()
    assert risk_state.filled_turnover == 0


def test_terminal_order_observation_closes_partial_fill_remainder(tmp_path: Path) -> None:
    state = _state(tmp_path)
    assert state.relayer.relay(state.signal)[0]["status"] == "placed"
    client_order_id = state.venue.calls[0][0].client_order_id
    state.coordinator.record_execution_report(
        ExecutionReport(
            order_id="venue-order-1",
            client_order_id=client_order_id,
            symbol="BTCUSDT",
            side="buy",
            filled_qty=0.004,
            cumulative_filled_qty=0.004,
            fill_price=10_000.0,
            commission=0.01,
            commission_asset="USDT",
            status="partially_filled",
            timestamp_utc=datetime.now(UTC).isoformat(),
            source_event_ref="binance_execution_partial_1",
            raw=_raw_payload("partial-1"),
            raw_event_hash=_raw_hash("partial-1"),
        ),
        actor="binance_execution_reconciler",
        normalized_cost_usdt=0.01,
        cost_conversion_ref="cost_conversion_usdt_identity",
    )
    observation = OrderExecutionObservation(
        order_id="venue-order-1",
        client_order_id=client_order_id,
        symbol="BTCUSDT",
        side="buy",
        status="canceled",
        requested_qty=0.01,
        cumulative_filled_qty=0.004,
        observed_at_utc=datetime.now(UTC).isoformat(),
        source_event_ref="binance_order_terminal_partial_1",
        raw=_raw_payload("terminal-partial-1"),
        raw_event_hash=_raw_hash("terminal-partial-1"),
    )

    result = state.coordinator.record_order_observation(
        observation,
        actor="binance_execution_reconciler",
    )

    assert result["formal_status"] == "closed_partial_fill"
    risk_state = state.risk.state(state.follower.follower_id, state.follower.account_binding_ref)
    assert risk_state.open_reservation_refs == ()
    assert risk_state.filled_turnover == pytest.approx(40.0)


def test_stale_fill_is_rejected_before_any_formal_append(tmp_path: Path) -> None:
    state = _state(tmp_path)
    assert state.relayer.relay(state.signal)[0]["status"] == "placed"
    client_order_id = state.venue.calls[0][0].client_order_id
    first = ExecutionReport(
        order_id="venue-order-1",
        client_order_id=client_order_id,
        symbol="BTCUSDT",
        side="buy",
        filled_qty=0.004,
        cumulative_filled_qty=0.004,
        fill_price=10_000.0,
        commission=0.01,
        commission_asset="USDT",
        status="partially_filled",
        timestamp_utc=datetime.now(UTC).isoformat(),
        source_event_ref="binance_execution_monotonic_1",
        raw=_raw_payload("monotonic-1"),
        raw_event_hash=_raw_hash("monotonic-1"),
    )
    state.coordinator.record_execution_report(
        first,
        actor="binance_execution_reconciler",
        normalized_cost_usdt=0.01,
        cost_conversion_ref="cost_conversion_usdt_identity",
    )
    counts_before = (
        len(state.registries.events.events()),
        len(state.registries.reconciliations.reconciliations()),
    )
    stale = replace(
        first,
        filled_qty=0.001,
        cumulative_filled_qty=0.004,
        source_event_ref="binance_execution_monotonic_stale",
        raw=_raw_payload("monotonic-stale"),
        raw_event_hash=_raw_hash("monotonic-stale"),
    )
    with pytest.raises(CopyTradeRiskError, match="stale or non-increasing"):
        state.coordinator.record_execution_report(
            stale,
            actor="binance_execution_reconciler",
            normalized_cost_usdt=0.01,
            cost_conversion_ref="cost_conversion_usdt_identity",
        )
    assert (
        len(state.registries.events.events()),
        len(state.registries.reconciliations.reconciliations()),
    ) == counts_before


def test_mismatched_terminal_is_rejected_before_any_formal_append(tmp_path: Path) -> None:
    state = _state(tmp_path)
    assert state.relayer.relay(state.signal)[0]["status"] == "placed"
    client_order_id = state.venue.calls[0][0].client_order_id
    partial = ExecutionReport(
        order_id="venue-order-1",
        client_order_id=client_order_id,
        symbol="BTCUSDT",
        side="buy",
        filled_qty=0.004,
        cumulative_filled_qty=0.004,
        fill_price=10_000.0,
        commission=0.01,
        commission_asset="USDT",
        status="partially_filled",
        timestamp_utc=datetime.now(UTC).isoformat(),
        source_event_ref="binance_execution_terminal_guard_partial",
        raw=_raw_payload("terminal-guard-partial"),
        raw_event_hash=_raw_hash("terminal-guard-partial"),
    )
    state.coordinator.record_execution_report(
        partial,
        actor="binance_execution_reconciler",
        normalized_cost_usdt=0.01,
        cost_conversion_ref="cost_conversion_usdt_identity",
    )
    counts_before = (
        len(state.registries.events.events()),
        len(state.registries.reconciliations.reconciliations()),
    )
    observation = OrderExecutionObservation(
        order_id="venue-order-1",
        client_order_id=client_order_id,
        symbol="BTCUSDT",
        side="buy",
        status="canceled",
        requested_qty=0.01,
        cumulative_filled_qty=0.003,
        observed_at_utc=datetime.now(UTC).isoformat(),
        source_event_ref="binance_terminal_guard_stale",
        raw=_raw_payload("terminal-guard-stale"),
        raw_event_hash=_raw_hash("terminal-guard-stale"),
    )
    with pytest.raises(CopyTradeRiskError, match="does not match the recorded fills"):
        state.coordinator.record_order_observation(
            observation,
            actor="binance_execution_reconciler",
        )
    assert (
        len(state.registries.events.events()),
        len(state.registries.reconciliations.reconciliations()),
    ) == counts_before


def test_concurrent_same_cumulative_fills_append_only_one_formal_event(tmp_path: Path) -> None:
    state = _state(tmp_path)
    assert state.relayer.relay(state.signal)[0]["status"] == "placed"
    client_order_id = state.venue.calls[0][0].client_order_id

    def project(index: int):
        report = ExecutionReport(
            order_id="venue-order-1",
            client_order_id=client_order_id,
            symbol="BTCUSDT",
            side="buy",
            filled_qty=0.004,
            cumulative_filled_qty=0.004,
            fill_price=10_000.0,
            commission=0.01,
            commission_asset="USDT",
            status="partially_filled",
            timestamp_utc=datetime.now(UTC).isoformat(),
            source_event_ref=f"binance_execution_race_{index}",
            raw=_raw_payload(f"race-{index}"),
            raw_event_hash=_raw_hash(f"race-{index}"),
        )
        try:
            return state.coordinator.record_execution_report(
                report,
                actor="binance_execution_reconciler",
                normalized_cost_usdt=0.01,
                cost_conversion_ref="cost_conversion_usdt_identity",
            )
        except CopyTradeRiskError as exc:
            return exc

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(project, (1, 2), timeout=10))
    assert sum(isinstance(item, dict) for item in outcomes) == 1
    assert sum(isinstance(item, CopyTradeRiskError) for item in outcomes) == 1
    assert len(state.registries.events.events()) == 2
    assert len(state.registries.reconciliations.reconciliations()) == 2


def test_concurrent_terminal_observations_append_only_one_formal_event(tmp_path: Path) -> None:
    state = _state(tmp_path)
    assert state.relayer.relay(state.signal)[0]["status"] == "placed"
    client_order_id = state.venue.calls[0][0].client_order_id

    def project(index: int):
        label = f"terminal-race-{index}"
        observation = OrderExecutionObservation(
            order_id="venue-order-1",
            client_order_id=client_order_id,
            symbol="BTCUSDT",
            side="buy",
            status="canceled",
            requested_qty=0.01,
            cumulative_filled_qty=0,
            observed_at_utc=datetime.now(UTC).isoformat(),
            source_event_ref=f"binance_{label}",
            raw=_raw_payload(label),
            raw_event_hash=_raw_hash(label),
        )
        try:
            return state.coordinator.record_order_observation(
                observation,
                actor="binance_execution_reconciler",
            )
        except CopyTradeRiskError as exc:
            return exc

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(project, (1, 2), timeout=10))
    assert sum(isinstance(item, dict) for item in outcomes) == 1
    assert sum(isinstance(item, CopyTradeRiskError) for item in outcomes) == 1
    assert len(state.registries.events.events()) == 2
    assert len(state.registries.reconciliations.reconciliations()) == 2


def test_stale_coordinator_refreshes_prior_fill_before_terminal_reconciliation(tmp_path: Path) -> None:
    state = _state(tmp_path)
    assert state.relayer.relay(state.signal)[0]["status"] == "placed"
    stale = _reload_projection_state(state, tmp_path)
    client_order_id = state.venue.calls[0][0].client_order_id
    state.coordinator.record_execution_report(
        ExecutionReport(
            order_id="venue-order-1",
            client_order_id=client_order_id,
            symbol="BTCUSDT",
            side="buy",
            filled_qty=0.004,
            cumulative_filled_qty=0.004,
            fill_price=10_000.0,
            commission=0.01,
            commission_asset="USDT",
            status="partially_filled",
            timestamp_utc=datetime.now(UTC).isoformat(),
            source_event_ref="binance_cross_instance_partial",
            raw=_raw_payload("cross-instance-partial"),
            raw_event_hash=_raw_hash("cross-instance-partial"),
        ),
        actor="binance_execution_reconciler",
        normalized_cost_usdt=0.01,
        cost_conversion_ref="cost_conversion_usdt_identity",
    )
    result = stale.coordinator.record_order_observation(
        OrderExecutionObservation(
            order_id="venue-order-1",
            client_order_id=client_order_id,
            symbol="BTCUSDT",
            side="buy",
            status="canceled",
            requested_qty=0.01,
            cumulative_filled_qty=0.004,
            observed_at_utc=datetime.now(UTC).isoformat(),
            source_event_ref="binance_cross_instance_terminal",
            raw=_raw_payload("cross-instance-terminal"),
            raw_event_hash=_raw_hash("cross-instance-terminal"),
        ),
        actor="binance_execution_reconciler",
    )
    assert result["formal_status"] == "closed_partial_fill"
    stale.registries.events.refresh()
    assert [item.event_kind for item in stale.registries.events.events()] == [
        "accepted",
        "partially_filled",
        "canceled",
    ]


def test_exact_terminal_replay_with_different_actor_rejects_before_append(tmp_path: Path) -> None:
    state = _state(tmp_path)
    assert state.relayer.relay(state.signal)[0]["status"] == "placed"
    client_order_id = state.venue.calls[0][0].client_order_id
    observation = OrderExecutionObservation(
        order_id="venue-order-1",
        client_order_id=client_order_id,
        symbol="BTCUSDT",
        side="buy",
        status="canceled",
        requested_qty=0.01,
        cumulative_filled_qty=0,
        observed_at_utc=datetime.now(UTC).isoformat(),
        source_event_ref="binance_actor_bound_terminal",
        raw=_raw_payload("actor-bound-terminal"),
        raw_event_hash=_raw_hash("actor-bound-terminal"),
    )
    state.coordinator.record_order_observation(observation, actor="actor-a")
    counts_before = (
        len(state.registries.events.events()),
        len(state.registries.reconciliations.reconciliations()),
    )
    with pytest.raises(CopyTradeRiskError, match="identity collision"):
        state.coordinator.record_order_observation(observation, actor="actor-b")
    assert (
        len(state.registries.events.events()),
        len(state.registries.reconciliations.reconciliations()),
    ) == counts_before


def test_stale_coordinator_refreshes_all_fills_before_advancing_reconciliation(tmp_path: Path) -> None:
    state = _state(tmp_path)
    assert state.relayer.relay(state.signal)[0]["status"] == "placed"
    stale = _reload_projection_state(state, tmp_path)
    client_order_id = state.venue.calls[0][0].client_order_id

    def report(label: str, filled: float, cumulative: float, status: str) -> ExecutionReport:
        return ExecutionReport(
            order_id="venue-order-1",
            client_order_id=client_order_id,
            symbol="BTCUSDT",
            side="buy",
            filled_qty=filled,
            cumulative_filled_qty=cumulative,
            fill_price=10_000.0,
            commission=0.01,
            commission_asset="USDT",
            status=status,
            timestamp_utc=datetime.now(UTC).isoformat(),
            source_event_ref=f"binance_{label}",
            raw=_raw_payload(label),
            raw_event_hash=_raw_hash(label),
        )

    first = state.coordinator.record_execution_report(
        report("cross_instance_fill_one", 0.004, 0.004, "partially_filled"),
        actor="binance_execution_reconciler",
        normalized_cost_usdt=0.01,
        cost_conversion_ref="cost_conversion_usdt_identity",
    )
    second = stale.coordinator.record_execution_report(
        report("cross_instance_fill_two", 0.006, 0.01, "filled"),
        actor="binance_execution_reconciler",
        normalized_cost_usdt=0.01,
        cost_conversion_ref="cost_conversion_usdt_identity",
    )
    reconciliation = stale.registries.reconciliations.reconciliation(second["reconciliation_ref"])
    assert first["venue_event_ref"] in reconciliation.event_refs
    assert second["venue_event_ref"] in reconciliation.event_refs
    stale.registries.events.refresh()
    assert len(stale.registries.events.events()) == 3


def test_stale_coordinator_created_before_attempt_refreshes_every_formal_parent(
    tmp_path: Path,
) -> None:
    state = _state(tmp_path)
    stale = _reload_projection_state(state, tmp_path)
    assert stale.registries.intents.intents() == []
    assert stale.registries.materializations.materializations() == []
    assert stale.registries.capabilities.capabilities() == []
    assert stale.registries.requests.requests() == []

    assert state.relayer.relay(state.signal)[0]["status"] == "placed"
    results = _replay_all_formal_attempts(stale)

    assert results[0]["formal_status"] == "accepted"
    assert len(stale.registries.intents.intents()) == 1
    assert len(stale.registries.materializations.materializations()) == 1
    assert len(stale.registries.capabilities.capabilities()) == 1
    assert len(stale.registries.requests.requests()) == 1
    assert len(stale.registries.submissions.submissions()) == 1


def test_registry_refresh_never_exposes_an_empty_partial_snapshot(
    tmp_path: Path,
    monkeypatch,
) -> None:
    state = _state(tmp_path)
    assert state.relayer.relay(state.signal)[0]["status"] == "placed"
    registry = state.registries.intents
    assert len(registry.intents()) == 1
    entered = Event()
    release = Event()
    original_load = PersistentExecutionOrderIntentRegistry._load_existing

    def blocked_load(instance):
        entered.set()
        assert release.wait(timeout=10)
        return original_load(instance)

    monkeypatch.setattr(PersistentExecutionOrderIntentRegistry, "_load_existing", blocked_load)
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(registry.refresh)
        assert entered.wait(timeout=10)
        assert len(registry.intents()) == 1
        release.set()
        future.result(timeout=10)
    assert len(registry.intents()) == 1


def test_fill_claim_rejects_valid_but_unrelated_ack_and_open_reconciliation(
    tmp_path: Path,
) -> None:
    state = _state(tmp_path)
    assert state.relayer.relay(state.signal)[0]["status"] == "placed"
    reservation = state.risk.reservation_for_submission(
        state.registries.submissions.submissions()[0].submission_ref
    )
    report = ExecutionReport(
        order_id="venue-order-1",
        client_order_id=reservation.client_order_id,
        symbol="BTCUSDT",
        side="buy",
        filled_qty=0.01,
        cumulative_filled_qty=0.01,
        fill_price=10_000.0,
        commission=0.04,
        commission_asset="USDT",
        status="filled",
        timestamp_utc=datetime.now(UTC).isoformat(),
        source_event_ref="binance_misbinding_fill",
        raw=_raw_payload("misbinding-fill"),
        raw_event_hash=_raw_hash("misbinding-fill"),
    )

    with pytest.raises(CopyTradeRiskError, match="report-exact"):
        state.risk.claim_fill_projection(
            reservation,
            report=report,
            submission_ref=state.registries.submissions.submissions()[0].submission_ref,
            venue_event=state.registries.events.events()[0],
            reconciliation=state.registries.reconciliations.reconciliations()[0],
            normalized_cost_usdt=0.04,
            cost_conversion_ref="cost_conversion_usdt_identity",
            actor="binance_execution_reconciler",
        )
    assert [item["state"] for item in state.risk.formal_projection_attempts()] == [
        "submission_accepted"
    ]


def test_pending_lifecycle_claim_check_is_atomic_inside_sqlite_transaction(
    tmp_path: Path,
) -> None:
    state = _state(tmp_path)
    assert state.relayer.relay(state.signal)[0]["status"] == "placed"
    reservation = state.risk.reservation_for_submission(
        state.registries.submissions.submissions()[0].submission_ref
    )

    def claim(label: str):
        try:
            return state.risk._record_transition(
                reservation,
                event_kind="formal_lifecycle_claim",
                event_suffix=f"lifecycle_claim:fill:{label}",
                payload={"projection_kind": "fill", "source_event_ref": label},
            )
        except CopyTradeRiskError as exc:
            return exc

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(claim, ("atomic-a", "atomic-b"), timeout=10))

    assert sum(isinstance(item, str) for item in outcomes) == 1
    assert sum(isinstance(item, CopyTradeRiskError) for item in outcomes) == 1
    assert any("unfinished lifecycle" in str(item) for item in outcomes if isinstance(item, Exception))


@pytest.mark.parametrize("projection_kind", ["fill", "terminal"])
@pytest.mark.parametrize("failure_seam", ["event", "reconciliation", "risk_finalization"])
def test_lifecycle_projection_claim_repairs_every_post_claim_crash_seam(
    tmp_path: Path,
    monkeypatch,
    projection_kind: str,
    failure_seam: str,
) -> None:
    state = _state(tmp_path)
    assert state.relayer.relay(state.signal)[0]["status"] == "placed"
    client_order_id = state.venue.calls[0][0].client_order_id

    def fail(*_args, **_kwargs):
        raise OSError(f"crash at lifecycle {failure_seam}")

    if failure_seam == "event":
        monkeypatch.setattr(state.registries.events, "_append", fail)
    elif failure_seam == "reconciliation":
        monkeypatch.setattr(state.registries.reconciliations, "_append", fail)
    else:
        monkeypatch.setattr(state.risk, "finalize_lifecycle_projection_claim", fail)

    with pytest.raises(OSError, match=f"crash at lifecycle {failure_seam}"):
        if projection_kind == "fill":
            state.coordinator.record_execution_report(
                ExecutionReport(
                    order_id="venue-order-1",
                    client_order_id=client_order_id,
                    symbol="BTCUSDT",
                    side="buy",
                    filled_qty=0.01,
                    cumulative_filled_qty=0.01,
                    fill_price=10_000.0,
                    commission=0.04,
                    commission_asset="USDT",
                    status="filled",
                    timestamp_utc=datetime.now(UTC).isoformat(),
                    source_event_ref="binance_lifecycle_crash_fill",
                    raw=_raw_payload("lifecycle-crash-fill"),
                    raw_event_hash=_raw_hash("lifecycle-crash-fill"),
                ),
                actor="binance_execution_reconciler",
                normalized_cost_usdt=0.04,
                cost_conversion_ref="cost_conversion_usdt_identity",
            )
        else:
            state.coordinator.record_order_observation(
                OrderExecutionObservation(
                    order_id="venue-order-1",
                    client_order_id=client_order_id,
                    symbol="BTCUSDT",
                    side="buy",
                    status="canceled",
                    requested_qty=0.01,
                    cumulative_filled_qty=0,
                    observed_at_utc=datetime.now(UTC).isoformat(),
                    source_event_ref="binance_lifecycle_crash_terminal",
                    raw=_raw_payload("lifecycle-crash-terminal"),
                    raw_event_hash=_raw_hash("lifecycle-crash-terminal"),
                ),
                actor="binance_execution_reconciler",
            )

    attempts = state.risk.formal_projection_attempts()
    assert [item["state"] for item in attempts] == [
        "submission_accepted",
        "formal_lifecycle_claim",
    ]
    restarted = _reload_projection_state(state, tmp_path)
    _replay_all_formal_attempts(restarted)
    restarted.registries.events.refresh()
    restarted.registries.reconciliations.refresh()
    expected_kind = "filled" if projection_kind == "fill" else "canceled"
    assert [item.event_kind for item in restarted.registries.events.events()] == [
        "accepted",
        expected_kind,
    ]
    assert len(restarted.registries.reconciliations.reconciliations()) == 2
    assert restarted.risk.state(
        state.follower.follower_id,
        state.follower.account_binding_ref,
    ).open_reservation_refs == ()
    replayed_claim = [
        item
        for item in restarted.risk.formal_projection_attempts()
        if item["state"] == "formal_lifecycle_claim"
    ][0]
    assert replayed_claim["completed"]["projection_claim_event_id"] == replayed_claim[
        "binding_event_id"
    ]


def test_direct_fill_transition_cannot_complete_claim_before_formal_proof(
    tmp_path: Path,
    monkeypatch,
) -> None:
    state = _state(tmp_path)
    assert state.relayer.relay(state.signal)[0]["status"] == "placed"
    client_order_id = state.venue.calls[0][0].client_order_id
    report = ExecutionReport(
        order_id="venue-order-1",
        client_order_id=client_order_id,
        symbol="BTCUSDT",
        side="buy",
        filled_qty=0.01,
        cumulative_filled_qty=0.01,
        fill_price=10_000.0,
        commission=0.04,
        commission_asset="USDT",
        status="filled",
        timestamp_utc=datetime.now(UTC).isoformat(),
        source_event_ref="binance_direct_completion_bypass",
        raw=_raw_payload("direct-completion-bypass"),
        raw_event_hash=_raw_hash("direct-completion-bypass"),
    )

    def fail_event_append(*_args, **_kwargs):
        raise OSError("crash before lifecycle event append")

    monkeypatch.setattr(state.registries.events, "_append", fail_event_append)
    with pytest.raises(OSError, match="before lifecycle event append"):
        state.coordinator.record_execution_report(
            report,
            actor="binance_execution_reconciler",
            normalized_cost_usdt=0.04,
            cost_conversion_ref="cost_conversion_usdt_identity",
        )
    claim = [
        item
        for item in state.risk.formal_projection_attempts()
        if item["state"] == "formal_lifecycle_claim"
    ][0]
    payload = claim["payload"]
    reservation = claim["reservation"]

    with pytest.raises(CopyTradeRiskError, match="formal proof does not resolve"):
        state.risk.record_fill(
            reservation,
            report=report,
            submission_ref=payload["submission_ref"],
            venue_event_ref=payload["venue_event"]["venue_event_ref"],
            normalized_cost_usdt=payload["normalized_cost_usdt"],
            cost_conversion_ref=payload["cost_conversion_ref"],
            realized_pnl_delta=payload["realized_pnl_delta"],
            realized_pnl_complete=payload["realized_pnl_complete"],
            reconciliation_ref=payload["reconciliation"]["reconciliation_ref"],
            projection_claim_event_id=claim["binding_event_id"],
            actor=payload["actor"],
        )
    replayed = [
        item
        for item in state.risk.formal_projection_attempts()
        if item["state"] == "formal_lifecycle_claim"
    ][0]
    assert replayed["completed"] is None
    assert state.risk.state(
        state.follower.follower_id,
        state.follower.account_binding_ref,
    ).open_reservation_refs == (reservation.reservation_ref,)


@pytest.mark.parametrize("projection_kind", ["fill", "terminal"])
def test_completed_lifecycle_outbox_repairs_deleted_formal_jsonls(
    tmp_path: Path,
    projection_kind: str,
) -> None:
    state = _state(tmp_path)
    assert state.relayer.relay(state.signal)[0]["status"] == "placed"
    client_order_id = state.venue.calls[0][0].client_order_id
    if projection_kind == "fill":
        state.coordinator.record_execution_report(
            ExecutionReport(
                order_id="venue-order-1",
                client_order_id=client_order_id,
                symbol="BTCUSDT",
                side="buy",
                filled_qty=0.01,
                cumulative_filled_qty=0.01,
                fill_price=10_000.0,
                commission=0.04,
                commission_asset="USDT",
                status="filled",
                timestamp_utc=datetime.now(UTC).isoformat(),
                source_event_ref="binance_deleted_fill",
                raw=_raw_payload("deleted-fill"),
                raw_event_hash=_raw_hash("deleted-fill"),
            ),
            actor="binance_execution_reconciler",
            normalized_cost_usdt=0.04,
            cost_conversion_ref="cost_conversion_usdt_identity",
        )
    else:
        state.coordinator.record_order_observation(
            OrderExecutionObservation(
                order_id="venue-order-1",
                client_order_id=client_order_id,
                symbol="BTCUSDT",
                side="buy",
                status="canceled",
                requested_qty=0.01,
                cumulative_filled_qty=0,
                observed_at_utc=datetime.now(UTC).isoformat(),
                source_event_ref="binance_deleted_terminal",
                raw=_raw_payload("deleted-terminal"),
                raw_event_hash=_raw_hash("deleted-terminal"),
            ),
            actor="binance_execution_reconciler",
        )

    (tmp_path / "events.jsonl").unlink()
    (tmp_path / "reconciliations.jsonl").unlink()
    restarted = _reload_projection_state(state, tmp_path)
    _replay_all_formal_attempts(restarted)
    expected_kind = "filled" if projection_kind == "fill" else "canceled"
    assert [item.event_kind for item in restarted.registries.events.events()] == [
        "accepted",
        expected_kind,
    ]
    assert len(restarted.registries.reconciliations.reconciliations()) == 2


def test_partial_fill_terminal_full_sweep_and_deleted_jsonl_repair_are_idempotent(
    tmp_path: Path,
) -> None:
    state = _state(tmp_path)
    assert state.relayer.relay(state.signal)[0]["status"] == "placed"
    client_order_id = state.venue.calls[0][0].client_order_id
    state.coordinator.record_execution_report(
        ExecutionReport(
            order_id="venue-order-1",
            client_order_id=client_order_id,
            symbol="BTCUSDT",
            side="buy",
            filled_qty=0.004,
            cumulative_filled_qty=0.004,
            fill_price=10_000.0,
            commission=0.01,
            commission_asset="USDT",
            status="partially_filled",
            timestamp_utc=datetime.now(UTC).isoformat(),
            source_event_ref="binance_partial_before_terminal",
            raw=_raw_payload("partial-before-terminal"),
            raw_event_hash=_raw_hash("partial-before-terminal"),
        ),
        actor="binance_execution_reconciler",
        normalized_cost_usdt=0.01,
        cost_conversion_ref="cost_conversion_usdt_identity",
    )
    state.coordinator.record_order_observation(
        OrderExecutionObservation(
            order_id="venue-order-1",
            client_order_id=client_order_id,
            symbol="BTCUSDT",
            side="buy",
            status="canceled",
            requested_qty=0.01,
            cumulative_filled_qty=0.004,
            observed_at_utc=datetime.now(UTC).isoformat(),
            source_event_ref="binance_partial_terminal_cancel",
            raw=_raw_payload("partial-terminal-cancel"),
            raw_event_hash=_raw_hash("partial-terminal-cancel"),
        ),
        actor="binance_execution_reconciler",
    )

    _replay_all_formal_attempts(state)
    (tmp_path / "events.jsonl").unlink()
    (tmp_path / "reconciliations.jsonl").unlink()
    restarted = _reload_projection_state(state, tmp_path)
    _replay_all_formal_attempts(restarted)

    assert [item.event_kind for item in restarted.registries.events.events()] == [
        "accepted",
        "partially_filled",
        "canceled",
    ]
    assert len(restarted.registries.reconciliations.reconciliations()) == 3
    risk_state = restarted.risk.state(
        state.follower.follower_id,
        state.follower.account_binding_ref,
    )
    assert risk_state.open_reservation_refs == ()
    assert risk_state.filled_turnover == pytest.approx(40.0)


def test_lifecycle_full_sweep_finalizes_each_claim_once(
    tmp_path: Path,
    monkeypatch,
) -> None:
    state = _state(tmp_path)
    assert state.relayer.relay(state.signal)[0]["status"] == "placed"
    client_order_id = state.venue.calls[0][0].client_order_id
    for index, cumulative in enumerate((0.0025, 0.005, 0.0075, 0.01), start=1):
        state.coordinator.record_execution_report(
            ExecutionReport(
                order_id="venue-order-1",
                client_order_id=client_order_id,
                symbol="BTCUSDT",
                side="buy",
                filled_qty=0.0025,
                cumulative_filled_qty=cumulative,
                fill_price=10_000.0,
                commission=0.01,
                commission_asset="USDT",
                status="filled" if index == 4 else "partially_filled",
                timestamp_utc=datetime.now(UTC).isoformat(),
                source_event_ref=f"binance_linear_fill_{index}",
                raw=_raw_payload(f"linear-fill-{index}"),
                raw_event_hash=_raw_hash(f"linear-fill-{index}"),
            ),
            actor="binance_execution_reconciler",
            normalized_cost_usdt=0.01,
            cost_conversion_ref="cost_conversion_usdt_identity",
        )

    calls: list[str] = []
    original = state.risk.finalize_lifecycle_projection_claim

    def counted(reservation, *, claim_event_id: str):
        calls.append(claim_event_id)
        return original(reservation, claim_event_id=claim_event_id)

    monkeypatch.setattr(state.risk, "finalize_lifecycle_projection_claim", counted)
    _replay_all_formal_attempts(state)
    assert len(calls) == 4
    assert len(set(calls)) == 4


def test_outcome_unknown_can_recover_from_exact_source_execution_report(tmp_path: Path) -> None:
    state = _state(tmp_path, venue_error=TimeoutError("ack timeout"))
    outcome = state.relayer.relay(state.signal)[0]
    assert outcome["status"] == "outcome_unknown"
    client_order_id = state.venue.calls[0][0].client_order_id

    result = state.coordinator.record_execution_report(
        ExecutionReport(
            order_id="late-venue-order",
            client_order_id=client_order_id,
            symbol="BTCUSDT",
            side="buy",
            filled_qty=0.01,
            cumulative_filled_qty=0.01,
            fill_price=10_000.0,
            commission=0.04,
            commission_asset="USDT",
            status="filled",
            timestamp_utc=datetime.now(UTC).isoformat(),
            source_event_ref="binance_execution_late_trade_1",
            raw=_raw_payload("late-raw-event-1"),
            raw_event_hash=_raw_hash("late-raw-event-1"),
        ),
        actor="binance_execution_reconciler",
        normalized_cost_usdt=0.04,
        cost_conversion_ref="cost_conversion_usdt_identity",
    )

    assert result["formal_status"] == "filled"
    risk_state = state.risk.state(state.follower.follower_id, state.follower.account_binding_ref)
    assert risk_state.open_reservation_refs == ()
    assert risk_state.filled_turnover == pytest.approx(100.0)


def test_outcome_unknown_acceptance_binding_supports_multiple_source_fills(tmp_path: Path) -> None:
    state = _state(tmp_path, venue_error=TimeoutError("ack timeout"))
    assert state.relayer.relay(state.signal)[0]["status"] == "outcome_unknown"
    client_order_id = state.venue.calls[0][0].client_order_id

    first = state.coordinator.record_execution_report(
        ExecutionReport(
            order_id="late-venue-order",
            client_order_id=client_order_id,
            symbol="BTCUSDT",
            side="buy",
            filled_qty=0.004,
            cumulative_filled_qty=0.004,
            fill_price=10_000.0,
            commission=0.01,
            commission_asset="USDT",
            status="partially_filled",
            timestamp_utc=datetime.now(UTC).isoformat(),
            source_event_ref="binance_execution_late_trade_partial",
            raw=_raw_payload("late-raw-event-partial"),
            raw_event_hash=_raw_hash("late-raw-event-partial"),
        ),
        actor="binance_execution_reconciler",
        normalized_cost_usdt=0.01,
        cost_conversion_ref="cost_conversion_usdt_identity",
    )
    second = state.coordinator.record_execution_report(
        ExecutionReport(
            order_id="late-venue-order",
            client_order_id=client_order_id,
            symbol="BTCUSDT",
            side="buy",
            filled_qty=0.006,
            cumulative_filled_qty=0.01,
            fill_price=10_000.0,
            commission=0.02,
            commission_asset="USDT",
            status="filled",
            timestamp_utc=datetime.now(UTC).isoformat(),
            source_event_ref="binance_execution_late_trade_final",
            raw=_raw_payload("late-raw-event-final"),
            raw_event_hash=_raw_hash("late-raw-event-final"),
        ),
        actor="binance_execution_reconciler",
        normalized_cost_usdt=0.02,
        cost_conversion_ref="cost_conversion_usdt_identity",
    )

    assert first["formal_status"] == "needs_reconcile"
    assert second["formal_status"] == "filled"
    risk_state = state.risk.state(state.follower.follower_id, state.follower.account_binding_ref)
    assert risk_state.open_reservation_refs == ()
    assert risk_state.filled_turnover == pytest.approx(100.0)


def test_rejected_ack_is_reported_and_persisted_as_rejected(tmp_path: Path) -> None:
    state = _state(tmp_path)

    def rejected_ack(order, *, lease=None):
        state.venue.calls.append((order, lease))
        return OrderAck(order_id="reject-1", client_order_id=order.client_order_id, status="rejected")

    state.venue.place_order = rejected_ack
    result = state.relayer.relay(state.signal)[0]

    assert result["status"] == "rejected"
    assert state.service.list_executions(signal_id=state.signal.signal_id)[0].status == "rejected"
    assert state.registries.events.events()[0].event_kind == "rejected"
    risk_state = state.risk.state(state.follower.follower_id, state.follower.account_binding_ref)
    assert risk_state.reserved_turnover == 0
    assert risk_state.open_reservation_refs == ()


def test_mismatched_ack_identity_remains_outcome_unknown(tmp_path: Path) -> None:
    state = _state(tmp_path)

    def wrong_ack(order, *, lease=None):
        state.venue.calls.append((order, lease))
        return OrderAck(order_id="venue-order-wrong", client_order_id="another-client", status="new")

    state.venue.place_order = wrong_ack
    result = state.relayer.relay(state.signal)[0]

    assert result["status"] == "outcome_unknown"
    assert state.service.list_executions(signal_id=state.signal.signal_id)[0].status == "outcome_unknown"
    assert state.registries.events.events() == []
    assert state.registries.reconciliations.reconciliations()[0].status == "missing_events"
    risk_state = state.risk.state(state.follower.follower_id, state.follower.account_binding_ref)
    assert risk_state.reserved_turnover == pytest.approx(100.0)


def test_signal_payload_mutation_is_rejected_before_venue(tmp_path: Path) -> None:
    state = _state(tmp_path)
    mutated = replace(state.signal, quantity=0.02)

    result = state.relayer.relay(mutated)[0]

    assert result["status"] == "rejected"
    assert result["reason"] == "copy-trade signal content identity mismatch"
    assert state.venue.calls == []


def test_instrument_symbol_mismatch_is_rejected_before_venue(tmp_path: Path) -> None:
    state = _state(tmp_path)
    eth_signal = state.service.publish_signal(
        state.master.master_id,
        "master-user",
        symbol="ETHUSDT",
        side="buy",
        quantity=0.01,
        price=10_000.0,
        order_type="limit",
        leverage=2.0,
        strategy_book_qro_id="strategy-qro",
        signal_validation_ref="signal-validation",
        market_data_use_validation_ref="market-validation",
        instrument_ref="instrument:BTCUSDT_PERP",
    )
    assert eth_signal.signal_id == copy_trade_signal_id(eth_signal)

    result = state.relayer.relay(eth_signal)[0]

    assert result["status"] == "rejected"
    assert result["reason"] == "copy-trade instrument venue symbol does not match the order"
    assert state.venue.calls == []


def test_live_market_order_uses_observed_mark_without_mutating_order_price(tmp_path: Path) -> None:
    state = _state(tmp_path)
    signal = state.service.publish_signal(
        state.master.master_id,
        "master-user",
        symbol="BTCUSDT",
        side="buy",
        quantity=0.01,
        order_type="market",
        leverage=2.0,
        strategy_book_qro_id="strategy-qro",
        signal_validation_ref="signal-validation",
        market_data_use_validation_ref="market-validation",
        instrument_ref="instrument:BTCUSDT_PERP",
    )
    result = state.relayer.relay(signal)[0]
    assert result["status"] == "placed"
    assert state.venue.calls[-1][0].price is None


def test_live_market_order_without_observed_mark_is_rejected_before_venue(tmp_path: Path) -> None:
    state = _state(tmp_path)
    state.coordinator._observe = lambda _follower, _symbol: replace(
        _observation("exchange-account-1"),
        mark_price=0.0,
    )
    signal = state.service.publish_signal(
        state.master.master_id,
        "master-user",
        symbol="BTCUSDT",
        side="buy",
        quantity=0.01,
        order_type="market",
        leverage=2.0,
        strategy_book_qro_id="strategy-qro",
        signal_validation_ref="signal-validation",
        market_data_use_validation_ref="market-validation",
        instrument_ref="instrument:BTCUSDT_PERP",
    )
    result = state.relayer.relay(signal)[0]
    assert result["status"] == "rejected"
    assert "positive equity, mark, and quantity" in result["reason"]
    assert state.venue.calls == []


def test_live_market_order_observed_notional_cap_is_enforced_before_venue(tmp_path: Path) -> None:
    state = _state(tmp_path)
    signal = state.service.publish_signal(
        state.master.master_id,
        "master-user",
        symbol="BTCUSDT",
        side="buy",
        quantity=0.1,
        order_type="market",
        leverage=2.0,
        strategy_book_qro_id="strategy-qro",
        signal_validation_ref="signal-validation",
        market_data_use_validation_ref="market-validation",
        instrument_ref="instrument:BTCUSDT_PERP",
    )
    result = state.relayer.relay(signal)[0]
    assert result["status"] == "rejected"
    assert result["reason"] == "per-order notional exceeds the follower risk limit"
    assert state.venue.calls == []


def test_live_key_is_materialized_only_after_formal_and_gate_checks(tmp_path: Path) -> None:
    state = _state(tmp_path)
    fetched: list[str] = []
    original = state.keystore.fetch
    state.keystore.fetch = lambda name: (fetched.append(name), original(name))[1]

    first = state.relayer.relay(state.signal)[0]
    assert first["status"] == "placed"
    assert fetched == ["follower-key"]

    bad = state.service.publish_signal(
        state.master.master_id,
        "master-user",
        symbol="BTCUSDT",
        side="buy",
        quantity=0.01,
        price=10_000.0,
        order_type="limit",
        leverage=None,
        strategy_book_qro_id="strategy-qro",
        signal_validation_ref="signal-validation",
        market_data_use_validation_ref="market-validation",
        instrument_ref="instrument:BTCUSDT_PERP",
    )
    second = state.relayer.relay(bad)[0]
    assert second["status"] == "rejected"
    assert "leverage" in second["reason"]
    assert fetched == ["follower-key"]


def test_duplicate_live_relay_is_rejected_before_second_venue_call(tmp_path: Path) -> None:
    state = _state(tmp_path)
    first = state.relayer.relay(state.signal)[0]
    second = state.relayer.relay(state.signal)[0]

    assert first["status"] == "placed"
    assert second == {
        "follower_id": state.follower.follower_id,
        "status": "rejected",
        "reason": "duplicate signal/follower risk reservation",
    }
    assert len(state.venue.calls) == 1
    assert len(state.registries.submissions.submissions()) == 1


def test_concurrent_risk_reservations_atomically_share_turnover_budget(tmp_path: Path) -> None:
    store = PersistentFollowerRiskStateStore(tmp_path / "risk.sqlite3")
    follower = SimpleNamespace(
        follower_id="follower-1",
        account_binding_ref="exchange-account-1",
        invest_amount=1_000.0,
        max_positions=1,
        max_leverage=2.0,
    )
    limits = RiskLimits(
        per_order_max_usdt=300.0,
        daily_order_count_max=10,
        daily_loss_limit_pct=0.05,
        single_symbol_position_pct_max=1.0,
    )

    def reserve(signal_id: str):
        try:
            return store.reserve(
                follower=follower,
                signal_id=signal_id,
                order=Order(
                    venue="leased",
                    symbol="BTCUSDT",
                    side="buy",
                    quantity=0.02,
                    price=10_000.0,
                    leverage=2.0,
                ),
                observation=_observation("exchange-account-1"),
                limits=limits,
            )
        except CopyTradeRiskError as exc:
            return exc

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(reserve, ("signal-a", "signal-b"), timeout=10))

    assert sum(not isinstance(outcome, Exception) for outcome in outcomes) == 1
    assert sum(isinstance(outcome, CopyTradeRiskError) for outcome in outcomes) == 1
    assert any("daily turnover cap" in str(outcome) for outcome in outcomes if isinstance(outcome, Exception))
    state = store.state(follower.follower_id, follower.account_binding_ref)
    assert state.reserved_turnover == pytest.approx(200.0)
    assert len(state.open_reservation_refs) == 1
