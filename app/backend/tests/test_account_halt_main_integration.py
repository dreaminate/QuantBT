from __future__ import annotations

import sqlite3
import threading
import time
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app import main
from app.copy_trade import Follower
from app.execution import Position
from app.risk import KillSwitch
from app.security.gate.account_halt import PersistentAccountHaltBarrier
from app.security.gate.broker import KeyBroker


class _CountingKeystore:
    def __init__(self) -> None:
        self.fetched = 0

    def fetch(self, _name: str):
        self.fetched += 1
        return {"api_key": "K", "api_secret": "S"}


class _Venue:
    def __init__(self, account_ref: str, *, on_first_action=None) -> None:
        self.account_ref = account_ref
        self.owner_user_id = "alice"
        self.name = f"venue:{account_ref}"
        self.positions = [Position(symbol="BTCUSDT", quantity=0.1)]
        self.on_first_action = on_first_action
        self.cancel_started = threading.Event()

    def emergency_cancel_all(self):
        self.cancel_started.set()
        if self.on_first_action is not None:
            self.on_first_action()
        return {
            "ok": True,
            "verified_noop": False,
            "actions": [{"cancelled_all": True}],
            "error": None,
        }

    def list_open_positions(self):
        return list(self.positions)

    def close_open_position(self, position):
        self.positions = [item for item in self.positions if item.symbol != position.symbol]
        return {"closed": position.symbol, "quantity": position.quantity}

    def reconcile_emergency_actions_for_halt(self, _context):
        return ()

    def close_open_position_for_halt(self, position, _context):
        return self.close_open_position(position)

    def verify_emergency_flat(self, *, close_positions=True):
        positions = [
            {"symbol": position.symbol, "quantity": position.quantity}
            for position in self.positions
        ]
        return {
            "ok": not close_positions or not positions,
            "normal_open_order_refs": [],
            "algo_open_order_refs": [],
            "open_positions": positions,
        }


class _Registry:
    def __init__(self, venues=()) -> None:
        self._venues = tuple(venues)

    def venues_for_user(self, owner: str):
        return tuple(venue for venue in self._venues if venue.owner_user_id == owner)

    def venue_for_user(self, owner: str, account_ref: str):
        for venue in self._venues:
            if venue.owner_user_id == owner and venue.account_ref == account_ref:
                return venue
        raise KeyError(account_ref)

    def unregister_for_user(self, owner: str, account_ref: str) -> bool:
        before = len(self._venues)
        self._venues = tuple(
            venue
            for venue in self._venues
            if not (venue.owner_user_id == owner and venue.account_ref == account_ref)
        )
        return len(self._venues) != before


class _FollowerStateService:
    def __init__(self, followers: tuple[Follower, ...]) -> None:
        self._followers = {follower.follower_id: follower for follower in followers}

    def list_subscriptions(self, owner: str) -> tuple[Follower, ...]:
        return tuple(
            follower
            for follower in self._followers.values()
            if follower.user_id == owner
        )

    def begin_draining(self, owner: str, master_id: str) -> bool:
        follower_id = f"{owner}::{master_id}"
        follower = self._followers.get(follower_id)
        if follower is None or follower.status not in {"activating", "active", "paused"}:
            return False
        self._followers[follower_id] = replace(follower, status="draining")
        return True

    def list_draining_mainnet_followers(self) -> tuple[Follower, ...]:
        return tuple(
            follower
            for follower in self._followers.values()
            if follower.binance_network == "mainnet" and follower.status == "draining"
        )

    def get_follower(self, follower_id: str) -> Follower | None:
        return self._followers.get(follower_id)

    def finalize_stop(self, owner: str, master_id: str) -> bool:
        follower_id = f"{owner}::{master_id}"
        follower = self._followers.get(follower_id)
        if follower is None or follower.status != "draining":
            return False
        self._followers[follower_id] = replace(follower, status="stopped")
        return True


def _follower(account_ref: str, suffix: str) -> Follower:
    return Follower(
        follower_id=f"alice::master-{suffix}",
        user_id="alice",
        master_id=f"master-{suffix}",
        binance_network="mainnet",
        binance_keystore_name=f"key-{suffix}",
        account_binding_ref=account_ref,
        runtime_promotion_ref=f"promotion-{suffix}",
        status="active",
    )


def _zero_exposure_result() -> dict[str, object]:
    return {
        "ok": True,
        "normal_open_order_refs": [],
        "algo_open_order_refs": [],
        "open_positions": [],
    }


def _record_flat(
    barrier: PersistentAccountHaltBarrier,
    snapshot,
) -> str:
    return barrier.record_flat_proof(
        snapshot.owner_user_id,
        halt_ref=str(snapshot.halt_ref or ""),
        close_positions=True,
        account_epochs={snapshot.account_binding_ref: snapshot.epoch},
        results={snapshot.account_binding_ref: _zero_exposure_result()},
    )


def _install(
    monkeypatch,
    tmp_path: Path,
    *,
    account_refs=("exchange_account_uid_a",),
    unresolved: bool = False,
    on_first_action=None,
):
    barrier = PersistentAccountHaltBarrier(tmp_path / "account-halt.sqlite3")
    followers = tuple(_follower(ref, str(index)) for index, ref in enumerate(account_refs))
    for follower in followers:
        barrier.activate(follower.account_binding_ref, follower.user_id)
    venues = tuple(_Venue(ref, on_first_action=on_first_action) for ref in account_refs)
    monkeypatch.setattr(main, "ACCOUNT_HALT_BARRIER", barrier)
    monkeypatch.setattr(main, "COPY_TRADE_SERVICE", _FollowerStateService(followers))
    monkeypatch.setattr(main, "ACTIVE_EMERGENCY_VENUES", _Registry(venues))
    monkeypatch.setattr(main, "KILL_SWITCH", KillSwitch())
    monkeypatch.setattr(main, "RISK_MONITOR", SimpleNamespace(readiness=lambda: (True, None)))
    monkeypatch.setattr(
        main,
        "FOLLOWER_RISK_STATE",
        SimpleNamespace(has_open_reservations=lambda *_args: unresolved),
    )
    return barrier, followers, venues


def _live_capability(broker: KeyBroker, account_ref: str):
    return broker.issue_capability(
        action="request_live_order",
        gate_ref="gate",
        keystore_name="key",
        account_identity_ref=account_ref,
        owner_user_id="alice",
        requires_halt_fence=True,
    )


def test_all_accounts_are_halting_before_first_venue_action_and_stale_caps_never_fetch(
    monkeypatch,
    tmp_path: Path,
) -> None:
    refs = ("exchange_account_uid_a", "exchange_account_uid_b")
    observed_actions: list[str] = []
    barrier_holder: dict[str, PersistentAccountHaltBarrier] = {}
    broker_holder: dict[str, KeyBroker] = {}
    caps: list[object] = []

    def assert_latched() -> None:
        barrier = barrier_holder["value"]
        assert {barrier.snapshot(ref).state for ref in refs} == {"halting"}  # type: ignore[union-attr]
        for cap in caps:
            with pytest.raises(PermissionError):
                broker_holder["value"].issue(cap)  # type: ignore[arg-type]
        observed_actions.append("venue")

    barrier, _followers, _venues = _install(
        monkeypatch,
        tmp_path,
        account_refs=refs,
        on_first_action=assert_latched,
    )
    barrier_holder["value"] = barrier
    keystore = _CountingKeystore()
    broker = KeyBroker(
        keystore,
        hmac_key=b"h" * 32,
        account_halt_barrier=barrier,
    )
    broker_holder["value"] = broker
    caps.extend(_live_capability(broker, ref) for ref in refs)

    response, audit_result, error = main._execute_durable_user_halt(
        "alice",
        close_positions=True,
        action_name="test-kill",
    )

    assert response["action_ok"] is True
    assert response["halt"]["complete"] is True
    assert response["halt"]["status"] == "halted"
    assert audit_result == "ok"
    assert error is None
    assert observed_actions == ["venue", "venue"]
    assert keystore.fetched == 0
    assert {barrier.snapshot(ref).state for ref in refs} == {"halted"}  # type: ignore[union-attr]
    for ref in refs:
        with pytest.raises(PermissionError, match="HALT"):
            _live_capability(broker, ref)


def test_pre_halt_lease_is_drained_before_cancel_starts(monkeypatch, tmp_path: Path) -> None:
    barrier, _followers, venues = _install(monkeypatch, tmp_path)
    broker = KeyBroker(
        _CountingKeystore(),
        hmac_key=b"h" * 32,
        account_halt_barrier=barrier,
    )
    lease = broker.issue(_live_capability(broker, "exchange_account_uid_a"))
    outcome: dict[str, object] = {}

    def run_halt() -> None:
        try:
            outcome["response"] = main._execute_durable_user_halt(
                "alice",
                close_positions=True,
                action_name="drain-test",
            )[0]
        except BaseException as exc:  # noqa: BLE001
            outcome["error"] = exc

    worker = threading.Thread(target=run_halt)
    worker.start()
    deadline = time.monotonic() + 1
    while time.monotonic() < deadline:
        if barrier.snapshot("exchange_account_uid_a").state == "halting":  # type: ignore[union-attr]
            break
        time.sleep(0.005)
    assert barrier.snapshot("exchange_account_uid_a").state == "halting"  # type: ignore[union-attr]
    assert not venues[0].cancel_started.is_set()

    broker.revoke(lease)
    worker.join(timeout=2)
    assert not worker.is_alive()
    assert "error" not in outcome
    assert venues[0].cancel_started.is_set()
    assert outcome["response"]["halt"]["complete"] is True  # type: ignore[index]


def test_unresolved_formal_state_leaves_account_halting(monkeypatch, tmp_path: Path) -> None:
    barrier, _followers, _venues = _install(monkeypatch, tmp_path, unresolved=True)
    response, audit_result, error = main._execute_durable_user_halt(
        "alice",
        close_positions=True,
        action_name="unresolved-test",
    )
    assert response["action_ok"] is True
    assert response["ok"] is False
    assert response["halt"]["complete"] is False
    assert response["halt"]["status"] == "halting"
    assert audit_result == "halting"
    assert "unresolved" in str(error)
    assert barrier.snapshot("exchange_account_uid_a").state == "halting"  # type: ignore[union-attr]


def test_close_positions_false_can_never_finalize_halt(monkeypatch, tmp_path: Path) -> None:
    barrier, _followers, _venues = _install(monkeypatch, tmp_path)
    response, audit_result, error = main._execute_durable_user_halt(
        "alice",
        close_positions=False,
        action_name="cancel-only-test",
    )
    assert response["action_ok"] is True
    assert response["halt"]["complete"] is False
    assert response["halt"]["status"] == "halting"
    assert audit_result == "halting"
    assert "close_positions=false" in str(error)
    assert barrier.snapshot("exchange_account_uid_a").state == "halting"  # type: ignore[union-attr]


def test_empty_repeat_halt_finalizes_the_owner_latch(monkeypatch, tmp_path: Path) -> None:
    barrier = PersistentAccountHaltBarrier(tmp_path / "account-halt.sqlite3")
    barrier.activate("exchange_account_uid_a", "alice")
    snapshot = barrier.begin_account_halt(
        "exchange_account_uid_a",
        "alice",
        halt_ref="individual-stop",
        action_name="copy_trade_unsubscribe",
        close_positions=True,
    )
    barrier.finalize_account_halt(
        "exchange_account_uid_a",
        "alice",
        expected_epoch=snapshot.epoch,
        flat_proof_ref=_record_flat(barrier, snapshot),
    )
    monkeypatch.setattr(
        main,
        "COPY_TRADE_SERVICE",
        SimpleNamespace(
            list_subscriptions=lambda _owner: (),
            list_draining_mainnet_followers=lambda: (),
        ),
    )
    monkeypatch.setattr(main, "ACTIVE_EMERGENCY_VENUES", _Registry())
    monkeypatch.setattr(main, "KILL_SWITCH", KillSwitch())
    monkeypatch.setattr(main, "RISK_MONITOR", SimpleNamespace(readiness=lambda: (True, None)))
    monkeypatch.setattr(main, "ACCOUNT_HALT_BARRIER", barrier)

    response, _audit_result, error = main._execute_durable_user_halt(
        "alice",
        close_positions=True,
        action_name="repeat-kill",
    )

    assert response["halt"]["complete"] is True
    assert response["halt"]["status"] == "halted"
    assert response["halt"]["owner_state"] == "halted"
    assert error == "kill switch has no active venues"
    assert barrier.owner_state("alice") == "halted"


def test_halt_rehydrates_missing_process_local_emergency_handle(monkeypatch, tmp_path: Path) -> None:
    barrier, followers, venues = _install(monkeypatch, tmp_path)
    monkeypatch.setattr(main, "ACTIVE_EMERGENCY_VENUES", _Registry())
    monkeypatch.setattr(
        main,
        "_emergency_handle_for_follower",
        lambda follower: (
            venues[0]
            if follower.account_binding_ref == followers[0].account_binding_ref
            else None
        ),
    )

    response, audit_result, error = main._execute_durable_user_halt(
        "alice",
        close_positions=True,
        action_name="rehydrate-handle",
    )

    assert venues[0].cancel_started.is_set()
    assert response["halt"]["complete"] is True
    assert audit_result == "ok"
    assert error is None


def test_multi_account_global_flat_proof_allows_next_cycle_follower_cleanup(
    monkeypatch,
    tmp_path: Path,
) -> None:
    barrier, followers, _venues = _install(
        monkeypatch,
        tmp_path,
        account_refs=("exchange_account_uid_a", "exchange_account_uid_b"),
    )

    response, _audit_result, _error = main._execute_durable_user_halt(
        "alice",
        close_positions=True,
        action_name="multi-account-cleanup",
    )
    assert response["halt"]["complete"] is True
    proof_refs = {
        barrier.snapshot(follower.account_binding_ref).flat_proof_ref  # type: ignore[union-attr]
        for follower in followers
    }
    assert len(proof_refs) == 1

    summary = main._recover_durable_account_halts_once()

    assert summary["individual_operations"] == 2
    assert summary["recovered"] == 2
    assert summary["pending"] == 0
    assert all(
        main.COPY_TRADE_SERVICE.get_follower(follower.follower_id).status == "stopped"
        for follower in followers
    )


def test_global_halt_recovery_preserves_cancel_only_intent(monkeypatch, tmp_path: Path) -> None:
    barrier, _followers, venues = _install(monkeypatch, tmp_path)
    response, _audit_result, _error = main._execute_durable_user_halt(
        "alice",
        close_positions=False,
        action_name="kill_switch",
    )
    assert response["halt"]["complete"] is False
    assert len(venues[0].positions) == 1

    summary = main._recover_durable_account_halts_once()

    assert summary["global_operations"] == 1
    assert summary["recovered"] == 0
    assert summary["pending"] == 1
    assert summary["failures"] == 1
    assert len(venues[0].positions) == 1
    assert barrier.snapshot("exchange_account_uid_a").state == "halting"  # type: ignore[union-attr]


def test_global_halt_recovery_completes_persisted_close_intent(monkeypatch, tmp_path: Path) -> None:
    barrier, _followers, venues = _install(monkeypatch, tmp_path)
    barrier.begin_halt_many(
        "alice",
        ["exchange_account_uid_a"],
        halt_ref="crashed-close-request",
        action_name="emergency_close_all",
        close_positions=True,
    )

    summary = main._recover_durable_account_halts_once()

    assert summary["global_operations"] == 1
    assert summary["recovered"] == 1
    assert summary["pending"] == 0
    assert venues[0].positions == []
    assert barrier.snapshot("exchange_account_uid_a").state == "halted"  # type: ignore[union-attr]


def test_legacy_global_halt_without_intent_never_infers_market_close(monkeypatch, tmp_path: Path) -> None:
    barrier, _followers, venues = _install(monkeypatch, tmp_path)
    barrier.begin_halt_many(
        "alice",
        ["exchange_account_uid_a"],
        halt_ref="legacy-opaque-halt",
    )

    summary = main._recover_durable_account_halts_once()

    assert summary["recovered"] == 0
    assert summary["pending"] == 1
    assert summary["failures"] == 1
    assert len(venues[0].positions) == 1
    assert barrier.snapshot("exchange_account_uid_a").state == "halting"  # type: ignore[union-attr]


def test_legacy_individual_halt_without_intent_never_calls_venue(
    monkeypatch,
    tmp_path: Path,
) -> None:
    barrier, followers, venues = _install(monkeypatch, tmp_path)
    draining = replace(followers[0], status="draining")
    snapshot = barrier.begin_account_halt(
        draining.account_binding_ref,
        draining.user_id,
        halt_ref="legacy-individual-halt",
        action_name="copy_trade_unsubscribe",
        close_positions=True,
    )
    conn = sqlite3.connect(tmp_path / "account-halt.sqlite3")
    try:
        conn.execute(
            "UPDATE account_halt_state "
            "SET halt_action_name=NULL, halt_close_positions=NULL "
            "WHERE account_binding_ref=?",
            (draining.account_binding_ref,),
        )
        conn.commit()
    finally:
        conn.close()
    monkeypatch.setattr(main, "COPY_TRADE_SERVICE", _FollowerStateService((draining,)))

    summary = main._recover_durable_account_halts_once()

    assert summary["individual_operations"] == 1
    assert summary["recovered"] == 0
    assert summary["pending"] == 1
    assert summary["failures"] == 1
    assert venues[0].cancel_started.is_set() is False
    assert len(venues[0].positions) == 1
    current = barrier.snapshot(draining.account_binding_ref)
    assert current is not None and current.state == "halting"
    assert current.epoch == snapshot.epoch


def test_individual_halt_recovery_requires_a_fresh_lease_redrain(monkeypatch, tmp_path: Path) -> None:
    barrier, followers, _venues = _install(monkeypatch, tmp_path)
    draining = replace(followers[0], status="draining")
    snapshot = barrier.begin_account_halt(
        draining.account_binding_ref,
        draining.user_id,
        halt_ref="crashed-individual-unsubscribe",
        action_name="copy_trade_unsubscribe",
        close_positions=True,
    )
    monkeypatch.setattr(
        main,
        "COPY_TRADE_SERVICE",
        SimpleNamespace(
            list_subscriptions=lambda _owner: (draining,),
            list_draining_mainnet_followers=lambda: (draining,),
        ),
    )
    monkeypatch.setattr(
        barrier,
        "drain_account_fences",
        lambda _refs: ((), (draining.account_binding_ref,)),
    )
    continuation_called = False

    def forbidden_continuation(*_args):
        nonlocal continuation_called
        continuation_called = True
        return True

    monkeypatch.setattr(main, "_continue_mainnet_unsubscribe", forbidden_continuation)

    summary = main._recover_durable_account_halts_once()

    assert summary["individual_operations"] == 1
    assert summary["pending"] == 1
    assert summary["failures"] == 1
    assert continuation_called is False
    assert barrier.snapshot(draining.account_binding_ref).epoch == snapshot.epoch  # type: ignore[union-attr]


def test_recovery_finishes_halted_account_with_persisted_draining_follower(
    monkeypatch,
    tmp_path: Path,
) -> None:
    barrier, followers, venues = _install(monkeypatch, tmp_path)
    draining = replace(followers[0], status="draining")
    snapshot = barrier.begin_account_halt(
        draining.account_binding_ref,
        draining.user_id,
        halt_ref="unsubscribe-before-crash",
        action_name="copy_trade_unsubscribe",
        close_positions=True,
    )
    venues[0].positions = []
    barrier.finalize_account_halt(
        draining.account_binding_ref,
        draining.user_id,
        expected_epoch=snapshot.epoch,
        flat_proof_ref=_record_flat(barrier, snapshot),
    )
    state = {"follower": draining}

    def finalize_stop(_owner: str, _master: str) -> bool:
        state["follower"] = replace(state["follower"], status="stopped")
        return True

    monkeypatch.setattr(
        main,
        "COPY_TRADE_SERVICE",
        SimpleNamespace(
            list_draining_mainnet_followers=lambda: (
                (state["follower"],) if state["follower"].status == "draining" else ()
            ),
            list_subscriptions=lambda _owner: (state["follower"],),
            finalize_stop=finalize_stop,
            get_follower=lambda _follower_id: state["follower"],
        ),
    )

    summary = main._recover_durable_account_halts_once()

    assert summary["individual_operations"] == 1
    assert summary["recovered"] == 1
    assert summary["pending"] == 0
    assert state["follower"].status == "stopped"


def test_generic_pause_false_does_not_resume_a_halted_account(monkeypatch, tmp_path: Path) -> None:
    barrier, followers, _venues = _install(monkeypatch, tmp_path)
    snapshots = barrier.begin_halt_many(
        "alice",
        [followers[0].account_binding_ref],
        halt_ref="pause-test-halt",
    )
    barrier.finalize_halt_many(
        "alice",
        {ref: snapshot.epoch for ref, snapshot in snapshots.items()},
        flat_proof_ref=barrier.record_flat_proof(
            "alice",
            halt_ref="pause-test-halt",
            close_positions=True,
            account_epochs={ref: snapshot.epoch for ref, snapshot in snapshots.items()},
            results={ref: _zero_exposure_result() for ref in snapshots},
        ),
    )
    pause_calls: list[bool] = []
    monkeypatch.setattr(
        main,
        "COPY_TRADE_SERVICE",
        SimpleNamespace(
            get_follower=lambda _ref: followers[0],
            pause_subscription=lambda *_args, **kwargs: pause_calls.append(kwargs["paused"]),
        ),
    )
    with pytest.raises(HTTPException) as caught:
        main.ct_pause(
            followers[0].master_id,
            {"paused": False},
            SimpleNamespace(user_id="alice"),
        )
    assert caught.value.status_code == 409
    assert pause_calls == []


def test_health_never_flattens_reconciler_item_failures_to_ok(monkeypatch) -> None:
    monkeypatch.setattr(main, "_COPY_TRADE_RECONCILE_THREAD", SimpleNamespace(is_alive=lambda: True))
    monkeypatch.setattr(
        main,
        "_COPY_TRADE_RECONCILE_HEALTH",
        {
            "status": "degraded",
            "cycles": 3,
            "last_started_at_utc": "2026-01-01T00:00:00+00:00",
            "last_completed_at_utc": "2026-01-01T00:00:01+00:00",
            "last_error": "2 reconciliation item(s) failed",
            "last_summary": {"failures": 2},
        },
    )

    result = main.health()

    assert result["status"] == "degraded"
    assert result["copy_trade_reconciler"]["thread_alive"] is True
    assert result["copy_trade_reconciler"]["status"] == "degraded"
    assert result["copy_trade_reconciler"]["last_summary"]["failures"] == 2


def test_mainnet_reconciler_ready_requires_live_recent_clean_cycle(monkeypatch) -> None:
    monkeypatch.setattr(
        main,
        "_COPY_TRADE_RECONCILE_THREAD",
        SimpleNamespace(is_alive=lambda: True),
    )
    monkeypatch.setattr(
        main,
        "_COPY_TRADE_RECONCILE_STOP",
        SimpleNamespace(is_set=lambda: False),
    )
    monkeypatch.setattr(
        main,
        "_COPY_TRADE_RECONCILE_HEALTH",
        {
            "status": "healthy",
            "cycles": 1,
            "last_started_at_utc": None,
            "last_completed_at_utc": main._dt.datetime.now(main._dt.UTC).isoformat(),
            "last_error": None,
            "last_summary": {"failures": 0},
        },
    )

    assert main._copy_trade_mainnet_reconciler_ready() is True


@pytest.mark.parametrize(
    "health_patch",
    (
        {"status": "degraded"},
        {"cycles": 0},
        {"cycles": True},
        {"last_error": "reconciliation failed"},
        {"last_summary": {"failures": 1}},
        {"last_summary": {"failures": False}},
        {"last_completed_at_utc": "2026-01-01T00:00:00+00:00"},
        {"last_completed_at_utc": "not-a-timestamp"},
    ),
)
def test_mainnet_reconciler_ready_fails_closed_on_unhealthy_evidence(
    monkeypatch,
    health_patch,
) -> None:
    health = {
        "status": "healthy",
        "cycles": 1,
        "last_started_at_utc": None,
        "last_completed_at_utc": main._dt.datetime.now(main._dt.UTC).isoformat(),
        "last_error": None,
        "last_summary": {"failures": 0},
    }
    health.update(health_patch)
    monkeypatch.setattr(
        main,
        "_COPY_TRADE_RECONCILE_THREAD",
        SimpleNamespace(is_alive=lambda: True),
    )
    monkeypatch.setattr(
        main,
        "_COPY_TRADE_RECONCILE_STOP",
        SimpleNamespace(is_set=lambda: False),
    )
    monkeypatch.setattr(main, "_COPY_TRADE_RECONCILE_HEALTH", health)

    assert main._copy_trade_mainnet_reconciler_ready() is False


def test_reconcile_cycle_records_degraded_and_healthy_outcomes(monkeypatch) -> None:
    health = {
        "status": "starting",
        "cycles": 0,
        "last_started_at_utc": None,
        "last_completed_at_utc": None,
        "last_error": None,
        "last_summary": None,
    }
    monkeypatch.setattr(main, "_COPY_TRADE_RECONCILE_HEALTH", health)

    main._record_copy_trade_reconcile_cycle({"accounts": 2, "failures": 1})
    assert health["status"] == "degraded"
    assert health["cycles"] == 1
    assert health["last_error"] == "1 reconciliation item(s) failed"

    main._record_copy_trade_reconcile_cycle({"accounts": 2, "failures": 0})
    assert health["status"] == "healthy"
    assert health["cycles"] == 2
    assert health["last_error"] is None
    with pytest.raises(ValueError, match="exact failure count"):
        main._record_copy_trade_reconcile_cycle({"failures": True})
