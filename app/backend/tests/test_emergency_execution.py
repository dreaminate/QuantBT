from __future__ import annotations

from datetime import UTC, datetime

import pytest

from app.execution import Balance, OrderExecutionObservation, Position
from app.execution.binance_client import BinanceAPIError
from app.execution.emergency import (
    ActiveEmergencyVenueRegistry,
    BrokeredEmergencyBinanceVenue,
    EmergencyHaltContext,
)
from app.execution.emergency_journal import (
    EmergencyActionError,
    EmergencyActionJournal,
    emergency_close_request_hash,
)
from app.risk import KillSwitch
from app.security import InMemoryKeystore, KeystoreRecord, SecureKeystore
from app.security.gate.account_halt import PersistentAccountHaltBarrier
from app.security.gate.broker import KeyBroker


class _FakeLeasedVenue:
    def __init__(self) -> None:
        self.positions = [Position(symbol="BTCUSDT", quantity=0.2)]
        self.normal_orders = [{"orderId": "o1", "symbol": "BTCUSDT", "_qb_order_kind": "normal"}]
        self.algo_orders = [{"algoId": "a1", "symbol": "ETHUSDT", "_qb_order_kind": "algo"}]
        self.seen_keys: list[str] = []
        self.seen_lease_ids: list[int] = []

    def _observe(self, lease) -> None:
        self.seen_keys.append(lease.record.api_key)
        self.seen_lease_ids.append(id(lease))

    def emergency_cancel_all(self, *, lease):
        self._observe(lease)
        self.normal_orders = []
        self.algo_orders = []
        return {
            "ok": True,
            "verified_noop": False,
            "actions": [{"order_id": "o1"}],
            "error": None,
        }

    def list_open_positions(self, *, lease):
        self._observe(lease)
        return list(self.positions)

    def close_open_position(self, position, *, lease):
        self._observe(lease)
        self.positions = []
        return {"closed": position.symbol, "quantity": position.quantity}

    def list_open_orders(self, *, lease):
        self._observe(lease)
        return [*self.normal_orders, *self.algo_orders]

    def verify_emergency_flat(self, *, close_positions, lease):
        self._observe(lease)
        normal = [str(item["orderId"]) for item in self.normal_orders]
        algo = [str(item["algoId"]) for item in self.algo_orders]
        positions = [
            {"symbol": position.symbol, "quantity": position.quantity}
            for position in self.positions
        ]
        return {
            "ok": not normal and not algo and (not close_positions or not positions),
            "normal_open_order_refs": normal,
            "algo_open_order_refs": algo,
            "open_positions": positions,
        }

    def margin_equity(self, *, lease):
        self._observe(lease)
        return 1000.0

    def get_balance(self, *, lease):
        self._observe(lease)
        return {"USDT": Balance(asset="USDT", free=1000.0)}

    def execution_account_snapshot(self, symbol, *, lease):
        self._observe(lease)
        return {
            "account_uid": "venue-account-123",
            "account_identity_source": "fapi_v2_balance.accountAlias",
            "position_mode": "one_way",
            "can_trade": True,
            "multi_assets_margin": False,
            "equity": 1_050.0,
            "positions": [],
            "mark_price": 100.0,
            "bid_price": 99.0,
            "ask_price": 101.0,
            "maker_commission_rate": 0.0002,
            "taker_commission_rate": 0.0004,
            "funding_rate": 0.0001,
            "permission_state": {"enableFutures": True, "enableWithdrawals": False},
            "ip_restricted": True,
            "permission_warnings": (),
        }


def _handle(
    account_ref: str = "follower-1",
    *,
    owner_user_id: str = "owner-1",
    keystore_name: str = "acct",
    api_key: str = "K",
):
    keystore = SecureKeystore(InMemoryKeystore())
    keystore.store(KeystoreRecord(name=keystore_name, api_key=api_key, api_secret="S"))
    broker = KeyBroker(keystore, hmac_key=b"x" * 32)
    fake = _FakeLeasedVenue()
    handle = BrokeredEmergencyBinanceVenue(
        owner_user_id=owner_user_id,
        account_ref=account_ref,
        keystore_name=keystore_name,
        credential_binding_ref=broker.credential_binding_ref(keystore_name),
        broker=broker,
        network="testnet",
        product="usdm_futures",
        venue_factory=lambda: fake,  # type: ignore[arg-type]
    )
    return handle, fake, broker


def test_brokered_emergency_handle_uses_unique_account_name_and_revokes_every_lease():
    handle, fake, broker = _handle()
    result = KillSwitch([handle]).trigger()
    assert result[handle.name]["ok"] is True
    assert fake.positions == []
    assert fake.seen_keys == ["K", "K", "K", "K"]
    assert broker._leases == {}
    assert handle.name == "leased_binance:follower-1:testnet:usdm_futures"


def test_active_registry_drives_killswitch_and_source_bound_equity_without_network():
    handle, _fake, broker = _handle()
    registry = ActiveEmergencyVenueRegistry()
    kill_switch = KillSwitch(venue_provider=registry.venues)
    assert kill_switch.active_venue_names == ()
    registry.register(handle)
    assert kill_switch.active_venue_names == (handle.name,)
    assert registry.venues_for_user("owner-1") == (handle,)
    assert registry.venues_for_user("owner-2") == ()
    assert registry.venue_for_user("owner-1", handle.account_ref) is handle
    with pytest.raises(KeyError):
        registry.venue_for_user("owner-2", handle.account_ref)
    assert registry.unregister_for_user("owner-2", handle.account_ref) is False
    equity, source_ref, observed_at = registry.equity_observation()
    assert equity == 1000.0
    assert source_ref.startswith("active_emergency_equity:")
    assert observed_at
    assert broker._leases == {}
    assert registry.unregister(handle.account_ref) is True
    assert kill_switch.active_venue_names == ()


def test_emergency_registry_rejects_account_identity_collision():
    first, _fake, _broker = _handle("same")
    second, _fake2, _broker2 = _handle("same", owner_user_id="owner-2")
    registry = ActiveEmergencyVenueRegistry()
    registry.register(first)
    try:
        registry.register(second)
    except ValueError as exc:
        assert "account_ref collision" in str(exc)
    else:  # pragma: no cover - mutation guard
        raise AssertionError("account identity collision must fail closed")


def test_emergency_registry_rejects_same_account_credential_replacement():
    first, _fake, _broker = _handle("same-account")
    second, _fake2, _broker2 = _handle(
        "same-account",
        keystore_name="other-version",
        api_key="K2",
    )
    registry = ActiveEmergencyVenueRegistry()
    registry.register(first)
    with pytest.raises(ValueError, match="account_ref collision"):
        registry.register(second)


def test_execution_observation_requires_safe_permissions_and_uses_margin_equity():
    handle, fake, broker = _handle()
    observation = handle.execution_observation(
        "BTCUSDT",
        ip_allowlist_ref="ip-ref",
        hmac_replay_protection_ref="nonce-ref",
        rate_limit_ref="rate-ref",
    )
    assert observation.equity == 1_050.0
    assert observation.account_ref.startswith("exchange_account_uid_")
    assert observation.mark_price == 100.0
    assert observation.permission_warnings == ()
    assert fake.seen_keys == ["K"]
    assert broker._leases == {}


def test_execution_observation_rejects_permission_warning():
    handle, fake, _broker = _handle()
    original = fake.execution_account_snapshot

    def warned(symbol, *, lease):
        payload = original(symbol, lease=lease)
        return {**payload, "permission_warnings": ("ipRestrict=False",)}

    fake.execution_account_snapshot = warned
    with pytest.raises(PermissionError, match="unresolved warnings"):
        handle.execution_observation(
            "BTCUSDT",
            ip_allowlist_ref="ip-ref",
            hmac_replay_protection_ref="nonce-ref",
            rate_limit_ref="rate-ref",
        )


class _CrashAfterAcceptVenue(_FakeLeasedVenue):
    def __init__(self) -> None:
        super().__init__()
        self.posts = 0
        self.orders: dict[str, OrderExecutionObservation] = {}
        self.raise_after_accept = True
        self.position_to_mutate: Position | None = None
        self.seen_request_params: dict | None = None

    def close_open_position(self, position, *, client_order_id, lease):
        self._observe(lease)
        self.posts += 1
        self.positions = []
        observation = OrderExecutionObservation(
            order_id="991",
            client_order_id=client_order_id,
            symbol=position.symbol,
            side="sell" if position.quantity > 0 else "buy",
            status="filled",
            requested_qty=abs(float(position.quantity)),
            cumulative_filled_qty=abs(float(position.quantity)),
            observed_at_utc=datetime.now(UTC).isoformat(),
            source_event_ref="venue-observation-991",
            raw_event_hash="sha256:" + "9" * 64,
            raw={
                "orderId": 991,
                "clientOrderId": client_order_id,
                "origQty": str(abs(float(position.quantity))),
                "type": "MARKET",
                "reduceOnly": True,
                "closePosition": False,
                "positionSide": "BOTH",
            },
        )
        self.orders[client_order_id] = observation
        if self.raise_after_accept:
            self.raise_after_accept = False
            raise RuntimeError("transport lost after venue acceptance")
        return {
            "order_id": "991",
            "client_order_id": client_order_id,
            "status": "filled",
            "filled_quantity": abs(float(position.quantity)),
            "response_hash": "sha256:" + "8" * 64,
            "verified_flat": True,
        }

    def close_prepared_emergency_request(self, *, request_params, request_hash, lease):
        assert emergency_close_request_hash(request_params) == request_hash
        self.seen_request_params = dict(request_params)
        if self.position_to_mutate is not None:
            self.position_to_mutate.symbol = "ETHUSDT"
            self.position_to_mutate.quantity = 9.0
        quantity = float(request_params["quantity"])
        signed_quantity = quantity if request_params["side"] == "SELL" else -quantity
        return self.close_open_position(
            Position(symbol=request_params["symbol"], quantity=signed_quantity),
            client_order_id=request_params["newClientOrderId"],
            lease=lease,
        )

    def order_execution_observation(
        self,
        symbol,
        *,
        order_id=None,
        client_order_id=None,
        expected_emergency_close=False,
        lease,
    ):
        self._observe(lease)
        try:
            observation = self.orders[str(client_order_id)]
        except KeyError as exc:
            raise BinanceAPIError(status_code=400, code=-2013, message="Order does not exist") from exc
        assert observation.symbol == symbol
        if expected_emergency_close:
            assert observation.raw["reduceOnly"] is True
        return observation


def _durable_handle(tmp_path, fake):
    keystore = SecureKeystore(InMemoryKeystore())
    keystore.store(KeystoreRecord(name="acct", api_key="K", api_secret="S"))
    broker = KeyBroker(keystore, hmac_key=b"x" * 32)
    journal = EmergencyActionJournal(
        tmp_path / "emergency.sqlite3",
        mirror_path=tmp_path / "emergency.jsonl",
        integrity_key_path=tmp_path / "emergency.key",
    )
    halt_barrier = PersistentAccountHaltBarrier(tmp_path / "account-halt.sqlite3")
    snapshot = halt_barrier.snapshot("follower-1")
    if snapshot is None:
        halt_barrier.activate("follower-1", "owner-1")
        snapshot = halt_barrier.begin_account_halt(
            "follower-1",
            "owner-1",
            halt_ref="halt-crash",
            action_name="copy_trade_unsubscribe",
            close_positions=True,
        )
    journal.bind_account_halt_barrier(halt_barrier)
    handle = BrokeredEmergencyBinanceVenue(
        owner_user_id="owner-1",
        account_ref="follower-1",
        keystore_name="acct",
        credential_binding_ref=broker.credential_binding_ref("acct"),
        broker=broker,
        network="mainnet",
        product="usdm_futures",
        action_journal=journal,
        venue_factory=lambda: fake,
    )
    context = EmergencyHaltContext(
        owner_user_id="owner-1",
        owner_epoch=halt_barrier.owner_epoch("owner-1"),
        halt_ref=str(snapshot.halt_ref or ""),
        account_ref="follower-1",
        account_epoch=snapshot.epoch,
    )
    return handle, journal, context


def test_accepted_then_crashed_close_reconciles_before_position_discovery_without_second_post(
    tmp_path,
):
    fake = _CrashAfterAcceptVenue()
    first, journal, context = _durable_handle(tmp_path, fake)
    first_result = KillSwitch([first]).trigger(
        halt_contexts={first.account_ref: context},
    )
    assert first_result[first.name]["ok"] is False
    assert fake.posts == 1
    actions = journal.actions_for_scope(
        owner_user_id=context.owner_user_id,
        halt_ref=context.halt_ref,
        owner_epoch=context.owner_epoch,
        account_ref=context.account_ref,
        account_epoch=context.account_epoch,
    )
    assert len(actions) == 1 and actions[0].status == "submitting"
    assert fake.positions == []

    reopened, reopened_journal, reopened_context = _durable_handle(tmp_path, fake)
    recovered = KillSwitch([reopened]).trigger(
        halt_contexts={reopened.account_ref: reopened_context},
    )
    assert recovered[reopened.name]["ok"] is True
    assert recovered[reopened.name]["emergency_reconciliation"]["actions"]
    assert recovered[reopened.name]["position_discovery"]["verified_noop"] is True
    assert fake.posts == 1
    final_action = reopened_journal.action(actions[0].action_ref)
    assert final_action.status == "reconciled"
    assert final_action.observation_raw_hash == "sha256:" + "9" * 64


def test_submitting_action_missing_from_exact_lookup_never_auto_resubmits(tmp_path):
    fake = _CrashAfterAcceptVenue()
    fake.raise_after_accept = False
    handle, journal, context = _durable_handle(tmp_path, fake)
    action = journal.prepare(
        owner_user_id=context.owner_user_id,
        halt_ref=context.halt_ref,
        owner_epoch=context.owner_epoch,
        account_ref=context.account_ref,
        account_epoch=context.account_epoch,
        credential_binding_ref=handle.credential_binding_ref,
        symbol="BTCUSDT",
        side="sell",
        quantity=0.2,
    )
    journal.mark_submitting(action.action_ref)
    with pytest.raises(EmergencyActionError, match="automatic resubmit denied"):
        handle.close_open_position_for_halt(fake.positions[0], context)
    assert fake.posts == 0
    assert journal.action(action.action_ref).status == "submitting"


def test_operator_resolves_exact_minus_2013_as_unknown_flat_without_retry(tmp_path):
    fake = _CrashAfterAcceptVenue()
    fake.positions = []
    fake.normal_orders = []
    fake.algo_orders = []
    handle, journal, context = _durable_handle(tmp_path, fake)
    action = journal.prepare(
        owner_user_id=context.owner_user_id,
        halt_ref=context.halt_ref,
        owner_epoch=context.owner_epoch,
        account_ref=context.account_ref,
        account_epoch=context.account_epoch,
        credential_binding_ref=handle.credential_binding_ref,
        symbol="BTCUSDT",
        side="sell",
        quantity=0.2,
    )
    action = journal.mark_submitting(action.action_ref)

    result = handle.resolve_unknown_submission_for_halt(
        action.action_ref,
        context,
        operator_auth_audit_ref="mainnet_audit_v1_authorized",
    )

    assert result["resolved_via"] == "manual_unknown_flat"
    assert result["action"]["status"] == "manual_unknown_flat"
    assert result["resolution"]["historical_submission_outcome"] == "unknown"
    assert result["resolution"]["historical_fill_state"] == "unknown"
    assert result["resolution"]["automatic_retry_permitted"] is False
    assert fake.posts == 0
    assert len(fake.seen_lease_ids) == 2
    assert len(set(fake.seen_lease_ids)) == 1, "lookup and flat proof must share one lease"
    assert journal.action(action.action_ref).status == "manual_unknown_flat"

    with pytest.raises(EmergencyActionError, match="non-retryable"):
        handle.close_open_position_for_halt(
            Position(symbol="BTCUSDT", quantity=0.2),
            context,
        )
    assert fake.posts == 0


def test_unknown_submission_resolution_rejects_current_exposure_without_mutation(
    tmp_path,
):
    fake = _CrashAfterAcceptVenue()
    fake.normal_orders = []
    fake.algo_orders = []
    handle, journal, context = _durable_handle(tmp_path, fake)
    action = journal.prepare(
        owner_user_id=context.owner_user_id,
        halt_ref=context.halt_ref,
        owner_epoch=context.owner_epoch,
        account_ref=context.account_ref,
        account_epoch=context.account_epoch,
        credential_binding_ref=handle.credential_binding_ref,
        symbol="BTCUSDT",
        side="sell",
        quantity=0.2,
    )
    action = journal.mark_submitting(action.action_ref)

    with pytest.raises(EmergencyActionError, match="zero current venue exposure"):
        handle.resolve_unknown_submission_for_halt(
            action.action_ref,
            context,
            operator_auth_audit_ref="mainnet_audit_v1_authorized",
        )

    assert journal.action(action.action_ref).status == "submitting"
    assert fake.posts == 0


def test_unknown_submission_resolution_uses_exact_observation_when_order_exists(
    tmp_path,
):
    fake = _CrashAfterAcceptVenue()
    fake.positions = []
    fake.normal_orders = []
    fake.algo_orders = []
    handle, journal, context = _durable_handle(tmp_path, fake)
    action = journal.prepare(
        owner_user_id=context.owner_user_id,
        halt_ref=context.halt_ref,
        owner_epoch=context.owner_epoch,
        account_ref=context.account_ref,
        account_epoch=context.account_epoch,
        credential_binding_ref=handle.credential_binding_ref,
        symbol="BTCUSDT",
        side="sell",
        quantity=0.2,
    )
    action = journal.mark_submitting(action.action_ref)
    fake.orders[action.client_order_id] = OrderExecutionObservation(
        order_id="known-order",
        client_order_id=action.client_order_id,
        symbol="BTCUSDT",
        side="sell",
        status="filled",
        requested_qty=0.2,
        cumulative_filled_qty=0.2,
        observed_at_utc=datetime.now(UTC).isoformat(),
        source_event_ref="known-order-observation",
        raw_event_hash="sha256:" + "6" * 64,
        raw={
            "orderId": "known-order",
            "origQty": "0.2",
            "type": "MARKET",
            "reduceOnly": True,
            "closePosition": False,
            "positionSide": "BOTH",
        },
    )

    result = handle.resolve_unknown_submission_for_halt(
        action.action_ref,
        context,
        operator_auth_audit_ref="mainnet_audit_v1_authorized",
    )

    assert result["resolved_via"] == "exact_venue_observation"
    assert result["resolution"] is None
    assert result["action"]["status"] == "reconciled"
    with pytest.raises(EmergencyActionError, match="resolution is missing"):
        journal.unknown_submission_resolution(
            action.action_ref,
            owner_user_id=context.owner_user_id,
        )


def test_journaled_mainnet_handle_rejects_unscoped_close(tmp_path):
    fake = _CrashAfterAcceptVenue()
    handle, _journal, _context = _durable_handle(tmp_path, fake)
    with pytest.raises(PermissionError, match="durable HALT context"):
        handle.close_open_position(fake.positions[0])
    assert fake.posts == 0


def test_mainnet_handle_cannot_be_constructed_without_action_journal():
    keystore = SecureKeystore(InMemoryKeystore())
    keystore.store(KeystoreRecord(name="acct", api_key="K", api_secret="S"))
    broker = KeyBroker(keystore, hmac_key=b"x" * 32)
    with pytest.raises(ValueError, match="durable action journal"):
        BrokeredEmergencyBinanceVenue(
            owner_user_id="owner-1",
            account_ref="follower-1",
            keystore_name="acct",
            credential_binding_ref=broker.credential_binding_ref("acct"),
            broker=broker,
            network="mainnet",
            product="usdm_futures",
            venue_factory=lambda: _FakeLeasedVenue(),
        )


def test_individual_action_is_reconciled_when_global_halt_supersedes_scope(tmp_path):
    fake = _CrashAfterAcceptVenue()
    first, first_journal, individual = _durable_handle(tmp_path, fake)
    failed = KillSwitch([first]).trigger(
        halt_contexts={first.account_ref: individual},
    )
    assert failed[first.name]["ok"] is False
    assert fake.posts == 1 and fake.positions == []
    old_action = first_journal.actions_for_account_epoch(
        owner_user_id=individual.owner_user_id,
        account_ref=individual.account_ref,
        account_epoch=individual.account_epoch,
    )[0]
    assert old_action.status == "submitting"

    reopened, journal, _ = _durable_handle(tmp_path, fake)
    global_barrier = PersistentAccountHaltBarrier(tmp_path / "account-halt.sqlite3")
    batch = global_barrier.begin_halt_many(
        individual.owner_user_id,
        [individual.account_ref],
        halt_ref="global-halt",
        action_name="emergency_close_all",
        close_positions=True,
    )
    global_operation = global_barrier.owner_halt_operation(individual.owner_user_id)
    global_context = EmergencyHaltContext(
        owner_user_id=individual.owner_user_id,
        owner_epoch=global_operation.epoch,
        halt_ref=global_operation.halt_ref,
        account_ref=individual.account_ref,
        account_epoch=batch[individual.account_ref].epoch,
    )
    recovered = KillSwitch([reopened]).trigger(
        halt_contexts={reopened.account_ref: global_context},
    )
    assert recovered[reopened.name]["ok"] is True
    assert fake.posts == 1
    inherited = journal.action(old_action.action_ref)
    assert inherited.status == "reconciled"
    flat = recovered[reopened.name]["flat_verification"]["proof"]
    binding = journal.build_flat_proof_binding(
        owner_user_id=global_context.owner_user_id,
        halt_ref=global_context.halt_ref,
        owner_epoch=global_context.owner_epoch,
        account_ref=global_context.account_ref,
        account_epoch=global_context.account_epoch,
        flat_verification=flat,
    )
    assert binding["actions"][0]["action_ref"] == old_action.action_ref
    assert binding["actions"][0]["halt_ref"] == individual.halt_ref


def test_filled_action_with_fresh_residual_uses_new_attempt_client_id(tmp_path):
    fake = _CrashAfterAcceptVenue()
    fake.raise_after_accept = False
    handle, journal, context = _durable_handle(tmp_path, fake)
    first = journal.prepare(
        owner_user_id=context.owner_user_id,
        halt_ref=context.halt_ref,
        owner_epoch=context.owner_epoch,
        account_ref=context.account_ref,
        account_epoch=context.account_epoch,
        credential_binding_ref=handle.credential_binding_ref,
        symbol="BTCUSDT",
        side="sell",
        quantity=0.2,
    )
    journal.mark_submitting(first.action_ref)
    fake.orders[first.client_order_id] = OrderExecutionObservation(
        order_id="first-order",
        client_order_id=first.client_order_id,
        symbol="BTCUSDT",
        side="sell",
        status="filled",
        requested_qty=0.2,
        cumulative_filled_qty=0.2,
        observed_at_utc=datetime.now(UTC).isoformat(),
        source_event_ref="first-observation",
        raw_event_hash="sha256:" + "7" * 64,
        raw={
            "orderId": "first-order",
            "origQty": "0.2",
            "type": "MARKET",
            "reduceOnly": True,
            "closePosition": False,
            "positionSide": "BOTH",
        },
    )
    fake.positions = [Position(symbol="BTCUSDT", quantity=0.05)]
    result = KillSwitch([handle]).trigger(
        halt_contexts={handle.account_ref: context},
    )
    assert result[handle.name]["ok"] is True
    actions = journal.actions_for_account_epoch(
        owner_user_id=context.owner_user_id,
        account_ref=context.account_ref,
        account_epoch=context.account_epoch,
    )
    assert [action.status for action in actions] == ["filled_residual", "reconciled"]
    assert actions[1].attempt_no == 2
    assert actions[1].client_order_id != actions[0].client_order_id
    assert fake.posts == 1


def test_journaled_submit_uses_sealed_action_when_original_position_mutates(tmp_path):
    fake = _CrashAfterAcceptVenue()
    fake.raise_after_accept = False
    original = fake.positions[0]
    fake.position_to_mutate = original
    handle, journal, context = _durable_handle(tmp_path, fake)

    result = KillSwitch([handle]).trigger(
        halt_contexts={handle.account_ref: context},
    )

    assert result[handle.name]["ok"] is True
    assert fake.seen_request_params is not None
    assert fake.seen_request_params["symbol"] == "BTCUSDT"
    assert fake.seen_request_params["side"] == "SELL"
    assert fake.seen_request_params["quantity"] == 0.2
    action = journal.actions_for_account_epoch(
        owner_user_id=context.owner_user_id,
        account_ref=context.account_ref,
        account_epoch=context.account_epoch,
    )[0]
    assert emergency_close_request_hash(fake.seen_request_params) == action.request_hash
