from __future__ import annotations

import json
import os
import sqlite3
import stat
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest

import app.copy_trade.risk_state as risk_module
from app.copy_trade.risk_state import CopyTradeRiskError, PersistentFollowerRiskStateStore
from app.cross_process_lock import CrossProcessLockTimeout, acquire_exclusive_fd
from app.execution.base import (
    ExecutionReport,
    Order,
    OrderExecutionObservation,
    canonical_raw_event_hash,
)
from app.execution.emergency import AccountExecutionObservation
from app.research_os import ExecutionVenueEventRecord, reconcile_execution_venue_events
from app.risk import RiskLimits


def test_risk_database_and_integrity_key_are_private(tmp_path: Path) -> None:
    path = tmp_path / "risk.sqlite3"
    PersistentFollowerRiskStateStore(path)

    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert stat.S_IMODE(path.with_name(path.name + ".hmac.key").stat().st_mode) == 0o600
    for suffix in ("-wal", "-shm", "-journal"):
        sidecar = path.with_name(path.name + suffix)
        if sidecar.exists():
            assert stat.S_IMODE(sidecar.stat().st_mode) == 0o600


def test_risk_store_rejects_existing_broad_integrity_key_permissions(
    tmp_path: Path,
) -> None:
    path = tmp_path / "risk.sqlite3"
    PersistentFollowerRiskStateStore(path)
    key_path = path.with_name(path.name + ".hmac.key")
    key_path.chmod(0o644)

    with pytest.raises(ValueError, match="mode must be 0600"):
        PersistentFollowerRiskStateStore(path)


def test_risk_store_rejects_symlinked_or_hardlinked_integrity_key(
    tmp_path: Path,
) -> None:
    target = tmp_path / "target.key"
    target.write_bytes(b"k" * 32)
    target.chmod(0o600)

    symlink_db = tmp_path / "symlink.sqlite3"
    symlink_key = symlink_db.with_name(symlink_db.name + ".hmac.key")
    symlink_key.symlink_to(target)
    with pytest.raises(ValueError, match="non-symlink"):
        PersistentFollowerRiskStateStore(symlink_db)

    hardlink_db = tmp_path / "hardlink.sqlite3"
    hardlink_key = hardlink_db.with_name(hardlink_db.name + ".hmac.key")
    os.link(target, hardlink_key)
    with pytest.raises(ValueError, match="additional hard links"):
        PersistentFollowerRiskStateStore(hardlink_db)


def test_risk_store_rejects_symlinked_database_path(tmp_path: Path) -> None:
    target = tmp_path / "target.sqlite3"
    target.write_bytes(b"")
    target.chmod(0o600)
    path = tmp_path / "risk.sqlite3"
    path.symlink_to(target)

    with pytest.raises(ValueError, match="regular file"):
        PersistentFollowerRiskStateStore(path)


def test_risk_store_repairs_existing_database_permissions_before_open(
    tmp_path: Path,
) -> None:
    path = tmp_path / "risk.sqlite3"
    PersistentFollowerRiskStateStore(path)
    path.chmod(0o644)

    PersistentFollowerRiskStateStore(path)

    assert stat.S_IMODE(path.stat().st_mode) == 0o600


def test_integrity_key_creation_handles_short_writes_atomically(
    tmp_path: Path,
    monkeypatch,
) -> None:
    key_path = tmp_path / "risk.sqlite3.hmac.key"
    real_write = risk_module.os.write

    def short_write(fd, data):
        return real_write(fd, data[:3])

    monkeypatch.setattr(risk_module.os, "write", short_write)
    key = PersistentFollowerRiskStateStore._load_or_create_integrity_key(key_path)

    assert len(key) == 32
    assert key_path.read_bytes() == key
    assert stat.S_IMODE(key_path.stat().st_mode) == 0o600
    assert not tuple(tmp_path.glob(".risk.sqlite3.hmac.key.*.tmp"))


def test_integrity_key_creation_failure_leaves_no_partial_published_key(
    tmp_path: Path,
    monkeypatch,
) -> None:
    key_path = tmp_path / "risk.sqlite3.hmac.key"
    real_write = risk_module.os.write
    calls = 0

    def fail_after_partial(fd, data):
        nonlocal calls
        calls += 1
        if calls == 1:
            return real_write(fd, data[:4])
        raise OSError("key-write-tripwire")

    monkeypatch.setattr(risk_module.os, "write", fail_after_partial)
    with pytest.raises(OSError, match="key-write-tripwire"):
        PersistentFollowerRiskStateStore._load_or_create_integrity_key(key_path)

    assert not key_path.exists()
    assert not tuple(tmp_path.glob(".risk.sqlite3.hmac.key.*.tmp"))


def test_integrity_key_replace_ack_loss_leaves_one_complete_restartable_key(
    tmp_path: Path,
    monkeypatch,
) -> None:
    key_path = tmp_path / "risk.sqlite3.hmac.key"
    real_replace = risk_module.os.replace

    def replace_then_raise(source, target):
        real_replace(source, target)
        raise OSError("key-replace-ack-loss")

    monkeypatch.setattr(risk_module.os, "replace", replace_then_raise)
    with pytest.raises(OSError, match="key-replace-ack-loss"):
        PersistentFollowerRiskStateStore._load_or_create_integrity_key(key_path)

    assert len(key_path.read_bytes()) == 32
    assert key_path.stat().st_nlink == 1
    assert not tuple(tmp_path.glob(".risk.sqlite3.hmac.key.*.tmp"))

    monkeypatch.setattr(risk_module.os, "replace", real_replace)
    replayed = PersistentFollowerRiskStateStore._load_or_create_integrity_key(key_path)
    assert replayed == key_path.read_bytes()


def test_concurrent_first_integrity_key_creators_converge_on_one_private_key(
    tmp_path: Path,
) -> None:
    key_path = tmp_path / "risk.sqlite3.hmac.key"

    with ThreadPoolExecutor(max_workers=16) as pool:
        keys = list(
            pool.map(
                lambda _index: PersistentFollowerRiskStateStore._load_or_create_integrity_key(
                    key_path
                ),
                range(64),
            )
        )

    assert len(set(keys)) == 1
    assert key_path.read_bytes() == keys[0]
    assert stat.S_IMODE(key_path.stat().st_mode) == 0o600
    lock_path = key_path.with_name(f".{key_path.name}.create.lock")
    assert stat.S_IMODE(lock_path.stat().st_mode) == 0o600


def test_integrity_key_creation_lock_times_out_instead_of_hanging(
    tmp_path: Path,
    monkeypatch,
) -> None:
    key_path = tmp_path / "risk.sqlite3.hmac.key"
    lock_path = key_path.with_name(f".{key_path.name}.create.lock")
    lock_fd = os.open(lock_path, os.O_RDWR | os.O_CREAT, 0o600)
    held = acquire_exclusive_fd(lock_fd, timeout_seconds=0.0)
    monkeypatch.setattr(risk_module, "_KEY_CREATION_LOCK_TIMEOUT_SECONDS", 0.01)
    try:
        with pytest.raises(CrossProcessLockTimeout, match="timed out"):
            PersistentFollowerRiskStateStore._load_or_create_integrity_key(key_path)
    finally:
        held.release()
        os.close(lock_fd)

    assert not key_path.exists()


def _follower(*, follower_id: str = "follower-1", max_positions: int = 5):
    return SimpleNamespace(
        follower_id=follower_id,
        account_binding_ref="account-1",
        invest_amount=1_000.0,
        max_positions=max_positions,
        max_leverage=2.0,
    )


def _observation(at: datetime, *, account_ref: str = "account-1") -> AccountExecutionObservation:
    return AccountExecutionObservation(
        account_ref=account_ref,
        observed_at_utc=at.isoformat(),
        source_ref="snapshot-" + at.isoformat(),
        equity=10_000.0,
        positions=(),
        mark_price=10_000.0,
        bid_price=9_999.0,
        ask_price=10_001.0,
        maker_fee_bps=2.0,
        taker_fee_bps=4.0,
        funding_rate_bps=1.0,
        credential_check_ref="credential-check",
        ip_allowlist_ref="ip-allowlist",
        withdrawal_disabled_ref="withdrawal-disabled",
        hmac_replay_protection_ref="nonce-ledger",
        health_check_ref="health-check",
        rate_limit_ref="rate-limit",
        account_identity_source="fapi_v2_balance.accountAlias",
        position_mode="one_way",
        can_trade=True,
        multi_assets_margin=False,
    )


def _order(symbol: str, notional: float, *, client_order_id: str) -> Order:
    return Order(
        venue="leased",
        symbol=symbol,
        side="buy",
        quantity=notional / 10_000.0,
        price=10_000.0,
        leverage=2.0,
        client_order_id=client_order_id,
    )


def _fill(
    *,
    filled_qty: float,
    cumulative_filled_qty: float,
    status: str,
    timestamp_utc: str,
    realized_pnl_delta: float = 0.0,
    realized_pnl_complete: bool = False,
) -> ExecutionReport:
    source_ref = (
        "source-event-"
        + str(filled_qty)
        + "-"
        + str(cumulative_filled_qty)
        + "-"
        + status
    )
    raw = {"fixture_event_ref": source_ref}
    return ExecutionReport(
        order_id="venue-order-1",
        symbol="BTCUSDT",
        side="buy",
        filled_qty=filled_qty,
        cumulative_filled_qty=cumulative_filled_qty,
        fill_price=10_000.0,
        commission=0.01,
        commission_asset="USDT",
        status=status,
        realized_pnl_delta=realized_pnl_delta,
        realized_pnl_complete=realized_pnl_complete,
        timestamp_utc=timestamp_utc,
        client_order_id="client-fill",
        source_event_ref=source_ref,
        raw=raw,
        raw_event_hash=canonical_raw_event_hash(raw),
    )


def _terminal_observation(
    *,
    status: str,
    cumulative_filled_qty: float,
    observed_at_utc: str,
    source_ref: str,
) -> OrderExecutionObservation:
    raw = {"fixture_event_ref": source_ref}
    return OrderExecutionObservation(
        order_id="venue-order-1",
        client_order_id="client-fill",
        symbol="BTCUSDT",
        side="buy",
        status=status,  # type: ignore[arg-type]
        requested_qty=0.01,
        cumulative_filled_qty=cumulative_filled_qty,
        observed_at_utc=observed_at_utc,
        source_event_ref=source_ref,
        raw=raw,
        raw_event_hash=canonical_raw_event_hash(raw),
    )


def _start(store: PersistentFollowerRiskStateStore, reservation) -> None:
    store.mark_order_request_started(
        reservation,
        runtime_promotion_ref="runtime-promotion-fixture",
        order_intent_ref="order-intent-fixture",
        order_materialization_ref="order-materialization-fixture",
        venue_capability_ref="venue-capability-fixture",
        submit_request_ref="submit-request-fixture",
    )


class _VenueEventStore:
    def __init__(self, records) -> None:
        self._records = {record.venue_event_ref: record for record in records}

    def event(self, ref: str):
        if ref not in self._records:
            raise KeyError(ref)
        return self._records[ref]


class _ReconciliationStore:
    def __init__(self, record) -> None:
        self._record = record

    def reconciliation(self, ref: str):
        if ref != self._record.reconciliation_ref:
            raise KeyError(ref)
        return self._record


def _bind_terminal_proof(
    store: PersistentFollowerRiskStateStore,
    observation: OrderExecutionObservation,
    *,
    partial: bool,
) -> tuple[str, str]:
    terminal = ExecutionVenueEventRecord(
        order_intent_ref="order-intent-fixture",
        runtime_promotion_ref="runtime-promotion-fixture",
        submission_ref="submission-1",
        venue_ref="venue-fixture",
        event_kind=observation.status,
        status=observation.status,
        audit_record_ref="terminal-audit-fixture",
        order_guard_ref="order-guard-fixture",
        idempotency_key="idempotency-fixture",
        venue_order_ref=observation.order_id,
        client_order_ref=observation.client_order_id,
        raw_event_hash=observation.raw_event_hash,
        evidence_refs=(observation.source_event_ref, observation.raw_event_hash),
        recorded_by="fixture",
        created_at_utc=observation.observed_at_utc,
    )
    events = [terminal]
    if partial:
        events.insert(
            0,
            ExecutionVenueEventRecord(
                order_intent_ref="order-intent-fixture",
                runtime_promotion_ref="runtime-promotion-fixture",
                submission_ref="submission-1",
                venue_ref="venue-fixture",
                event_kind="partially_filled",
                status="partially_filled",
                audit_record_ref="partial-audit-fixture",
                order_guard_ref="order-guard-fixture",
                idempotency_key="idempotency-fixture",
                venue_order_ref=observation.order_id,
                client_order_ref=observation.client_order_id,
                raw_event_hash=canonical_raw_event_hash({"fixture": "partial"}),
                evidence_refs=("source-partial",),
                recorded_by="fixture",
                created_at_utc=observation.observed_at_utc,
            ),
        )
    reconciliation = reconcile_execution_venue_events(
        order_intent_ref="order-intent-fixture",
        runtime_promotion_ref="runtime-promotion-fixture",
        submission_ref="submission-1",
        venue_order_ref=observation.order_id,
        audit_record_ref="reconciliation-audit-fixture",
        events=tuple(events),
        evidence_refs=tuple(event.venue_event_ref for event in events),
        recorded_by="fixture",
    )
    store.bind_formal_proof_stores(
        reconciliation_store=_ReconciliationStore(reconciliation),
        venue_event_store=_VenueEventStore(events),
    )
    return reconciliation.reconciliation_ref, terminal.venue_event_ref


def _bind_fill_proof(
    store: PersistentFollowerRiskStateStore,
    report: ExecutionReport,
    *,
    submission_ref: str,
) -> tuple[str, str]:
    event = ExecutionVenueEventRecord(
        order_intent_ref="order-intent-fixture",
        runtime_promotion_ref="runtime-promotion-fixture",
        submission_ref=submission_ref,
        venue_ref="venue-fixture",
        event_kind=report.status,
        status=report.status,
        audit_record_ref="fill-audit-fixture",
        order_guard_ref="order-guard-fixture",
        idempotency_key="idempotency-fixture",
        venue_order_ref=report.order_id,
        client_order_ref=report.client_order_id,
        fill_ref=report.source_event_ref,
        quantity_ref="fill-quantity-fixture",
        price_ref="fill-price-fixture",
        fee_ref="fill-fee-fixture",
        raw_event_hash=report.raw_event_hash,
        evidence_refs=(report.source_event_ref, report.raw_event_hash),
        recorded_by="fixture",
        created_at_utc=report.timestamp_utc,
    )
    reconciliation = reconcile_execution_venue_events(
        order_intent_ref="order-intent-fixture",
        runtime_promotion_ref="runtime-promotion-fixture",
        submission_ref=submission_ref,
        venue_order_ref=report.order_id,
        audit_record_ref="fill-reconciliation-audit-fixture",
        events=(event,),
        evidence_refs=(event.venue_event_ref,),
        recorded_by="fixture",
    )
    store.bind_formal_proof_stores(
        reconciliation_store=_ReconciliationStore(reconciliation),
        venue_event_store=_VenueEventStore((event,)),
    )
    return reconciliation.reconciliation_ref, event.venue_event_ref


@pytest.mark.parametrize(
    "outcome",
    ("submission_accepted", "submission_unknown", "venue_reject", "definitive_reject"),
)
def test_verified_formal_submission_binding_covers_all_outcome_states(
    tmp_path: Path,
    outcome: str,
) -> None:
    now = datetime.now(UTC)
    store = PersistentFollowerRiskStateStore(tmp_path / f"risk-{outcome}.sqlite3")
    reservation = store.reserve(
        follower=_follower(),
        signal_id=f"signal-{outcome}",
        order=_order("BTCUSDT", 100.0, client_order_id=f"client-{outcome}"),
        observation=_observation(now),
        limits=RiskLimits(per_order_max_usdt=500.0, single_symbol_position_pct_max=1.0),
    )
    if outcome != "definitive_reject":
        _start(store, reservation)
    submission_ref = f"submission-{outcome}"
    if outcome == "submission_accepted":
        store.mark_submitted(
            reservation,
            submission_ref=submission_ref,
            venue_order_ref="venue-order",
            ack_ref="ack-ref",
        )
    elif outcome == "submission_unknown":
        store.mark_submission_unknown(
            reservation,
            reason_ref="timeout-ref",
            submission_ref=submission_ref,
        )
    elif outcome == "venue_reject":
        store.mark_venue_reject(
            reservation,
            reason_ref="venue-reject-ref",
            submission_ref=submission_ref,
            venue_order_ref=None,
            ack_ref="ack-ref",
            actor="tester",
        )
    else:
        store.mark_definitive_reject(
            reservation,
            reason_ref="definitive-reject-ref",
            submission_ref=submission_ref,
            ack_ref="ack-ref",
        )

    binding = store.verified_formal_submission_binding(submission_ref)
    assert binding is not None
    assert binding.outcome_state == outcome
    assert binding.reservation_ref == reservation.reservation_ref
    assert binding.follower_id == reservation.follower_id
    assert binding.account_binding_ref == reservation.account_binding_ref
    assert binding.client_order_id == reservation.client_order_id
    if outcome == "definitive_reject":
        assert binding.order_request_context == {}
    else:
        assert binding.order_request_context["submit_request_ref"] == "submit-request-fixture"


def test_verified_formal_submission_binding_revalidates_hmac_chain(tmp_path: Path) -> None:
    now = datetime.now(UTC)
    path = tmp_path / "risk-tamper.sqlite3"
    store = PersistentFollowerRiskStateStore(path)
    reservation = store.reserve(
        follower=_follower(),
        signal_id="signal-tamper",
        order=_order("BTCUSDT", 100.0, client_order_id="client-tamper"),
        observation=_observation(now),
        limits=RiskLimits(per_order_max_usdt=500.0, single_symbol_position_pct_max=1.0),
    )
    _start(store, reservation)
    store.mark_submission_unknown(
        reservation,
        reason_ref="timeout-ref",
        submission_ref="submission-tamper",
    )
    with sqlite3.connect(path) as conn:
        conn.execute(
            "UPDATE ct_risk_events SET account_binding_ref='forged-account' "
            "WHERE event_kind='submission_unknown'"
        )
    with pytest.raises(ValueError, match="integrity failure"):
        store.verified_formal_submission_binding("submission-tamper")


def test_pending_reservation_counts_toward_position_limit(tmp_path: Path) -> None:
    now = datetime.now(UTC)
    store = PersistentFollowerRiskStateStore(tmp_path / "risk.sqlite3")
    follower = _follower(max_positions=1)
    limits = RiskLimits(per_order_max_usdt=500.0, single_symbol_position_pct_max=1.0)
    store.reserve(
        follower=follower,
        signal_id="signal-btc",
        order=_order("BTCUSDT", 100.0, client_order_id="btc"),
        observation=_observation(now),
        limits=limits,
    )

    with pytest.raises(CopyTradeRiskError, match="projected position count"):
        store.reserve(
            follower=follower,
            signal_id="signal-eth",
            order=_order("ETHUSDT", 100.0, client_order_id="eth"),
            observation=_observation(now),
            limits=limits,
        )


def test_pending_reservation_counts_toward_symbol_concentration(tmp_path: Path) -> None:
    now = datetime.now(UTC)
    store = PersistentFollowerRiskStateStore(tmp_path / "risk.sqlite3")
    follower = _follower(max_positions=5)
    limits = RiskLimits(per_order_max_usdt=500.0, single_symbol_position_pct_max=0.30)
    store.reserve(
        follower=follower,
        signal_id="signal-one",
        order=_order("BTCUSDT", 200.0, client_order_id="one"),
        observation=_observation(now),
        limits=limits,
    )

    with pytest.raises(CopyTradeRiskError, match="symbol concentration"):
        store.reserve(
            follower=follower,
            signal_id="signal-two",
            order=_order("BTCUSDT", 200.0, client_order_id="two"),
            observation=_observation(now),
            limits=limits,
        )


def test_daily_loss_is_measured_against_follower_allocation_not_full_account(
    tmp_path: Path,
) -> None:
    now = datetime.now(UTC)
    store = PersistentFollowerRiskStateStore(tmp_path / "risk.sqlite3")
    follower = _follower()
    limits = RiskLimits(
        per_order_max_usdt=500.0,
        daily_loss_limit_pct=0.05,
        single_symbol_position_pct_max=1.0,
    )
    baseline = store.reserve(
        follower=follower,
        signal_id="signal-baseline",
        order=_order("BTCUSDT", 100.0, client_order_id="baseline"),
        observation=_observation(now),
        limits=limits,
    )
    store.mark_definitive_reject(baseline, reason_ref="baseline-only")

    lower = replace(
        _observation(now + timedelta(seconds=1)),
        equity=9_900.0,
        source_ref="snapshot-allocation-loss",
    )
    with pytest.raises(CopyTradeRiskError, match="allocation drawdown"):
        store.reserve(
            follower=follower,
            signal_id="signal-after-loss",
            order=_order("BTCUSDT", 100.0, client_order_id="after-loss"),
            observation=lower,
            limits=limits,
        )


def test_outcome_unknown_reservation_survives_day_rollover(tmp_path: Path, monkeypatch) -> None:
    first = datetime(2026, 7, 11, 23, 59, tzinfo=UTC)
    second = first + timedelta(minutes=2)
    clock = {"now": first}
    monkeypatch.setattr(risk_module, "_now", lambda: clock["now"])
    store = PersistentFollowerRiskStateStore(tmp_path / "risk.sqlite3")
    follower = _follower(max_positions=1)
    limits = RiskLimits(per_order_max_usdt=300.0, single_symbol_position_pct_max=1.0)
    reservation = store.reserve(
        follower=follower,
        signal_id="signal-before-midnight",
        order=_order("BTCUSDT", 200.0, client_order_id="before"),
        observation=_observation(first),
        limits=limits,
    )
    _start(store, reservation)
    store.mark_submission_unknown(reservation, reason_ref="timeout")

    clock["now"] = second
    replayed = PersistentFollowerRiskStateStore(tmp_path / "risk.sqlite3")
    with pytest.raises(CopyTradeRiskError, match="daily turnover cap"):
        replayed.reserve(
            follower=follower,
            signal_id="signal-after-midnight",
            order=_order("BTCUSDT", 200.0, client_order_id="after"),
            observation=_observation(second),
            limits=limits,
        )


def test_prior_process_pre_submit_orphan_is_released_after_grace(
    tmp_path: Path,
    monkeypatch,
) -> None:
    started = datetime(2026, 7, 11, 10, 0, tzinfo=UTC)
    clock = {"now": started}
    monkeypatch.setattr(risk_module, "_now", lambda: clock["now"])
    path = tmp_path / "risk.sqlite3"
    first = PersistentFollowerRiskStateStore(path)
    first.reserve(
        follower=_follower(),
        signal_id="signal-orphan",
        order=_order("BTCUSDT", 100.0, client_order_id="orphan-client"),
        observation=_observation(started),
        limits=RiskLimits(per_order_max_usdt=500.0, single_symbol_position_pct_max=1.0),
    )

    clock["now"] = started + timedelta(seconds=61)
    restarted = PersistentFollowerRiskStateStore(path)
    assert restarted.recover_pre_submit_orphans(min_age_s=60) == 1
    assert restarted.state("follower-1", "account-1").open_reservation_refs == ()


def test_started_order_request_is_never_released_as_pre_submit_orphan(
    tmp_path: Path,
    monkeypatch,
) -> None:
    started = datetime(2026, 7, 11, 10, 0, tzinfo=UTC)
    clock = {"now": started}
    monkeypatch.setattr(risk_module, "_now", lambda: clock["now"])
    path = tmp_path / "risk.sqlite3"
    first = PersistentFollowerRiskStateStore(path)
    reservation = first.reserve(
        follower=_follower(),
        signal_id="signal-started",
        order=_order("BTCUSDT", 100.0, client_order_id="client-fill"),
        observation=_observation(started),
        limits=RiskLimits(per_order_max_usdt=500.0, single_symbol_position_pct_max=1.0),
    )
    first.mark_order_request_started(
        reservation,
        runtime_promotion_ref="promotion-1",
        order_intent_ref="intent-1",
        order_materialization_ref="materialization-1",
        venue_capability_ref="capability-1",
        submit_request_ref="request-1",
    )

    clock["now"] = started + timedelta(hours=1)
    restarted = PersistentFollowerRiskStateStore(path)
    assert restarted.recover_pre_submit_orphans(min_age_s=60) == 0
    assert restarted.state("follower-1", "account-1").open_reservation_refs
    assert restarted.submission_binding_for_reservation(reservation.reservation_ref)["state"] == (
        "order_request_started"
    )


def test_unknown_transition_cannot_be_released_as_definitive_reject(tmp_path: Path) -> None:
    now = datetime.now(UTC)
    store = PersistentFollowerRiskStateStore(tmp_path / "risk.sqlite3")
    reservation = store.reserve(
        follower=_follower(),
        signal_id="signal-1",
        order=_order("BTCUSDT", 100.0, client_order_id="client-1"),
        observation=_observation(now),
        limits=RiskLimits(per_order_max_usdt=500.0, single_symbol_position_pct_max=1.0),
    )
    _start(store, reservation)
    store.mark_submission_unknown(reservation, reason_ref="timeout")

    with pytest.raises(CopyTradeRiskError, match="cannot become a definitive reject"):
        store.mark_definitive_reject(reservation, reason_ref="late-local-error")


def test_exact_transition_retry_is_idempotent_but_conflict_rejects(tmp_path: Path) -> None:
    now = datetime.now(UTC)
    store = PersistentFollowerRiskStateStore(tmp_path / "risk.sqlite3")
    reservation = store.reserve(
        follower=_follower(),
        signal_id="signal-1",
        order=_order("BTCUSDT", 100.0, client_order_id="client-1"),
        observation=_observation(now),
        limits=RiskLimits(per_order_max_usdt=500.0, single_symbol_position_pct_max=1.0),
    )
    _start(store, reservation)
    kwargs = {"submission_ref": "submission-1", "venue_order_ref": "order-1", "ack_ref": "ack-1"}
    store.mark_submitted(reservation, **kwargs)
    store.mark_submitted(reservation, **kwargs)

    with pytest.raises(CopyTradeRiskError, match="identity collision"):
        store.mark_submitted(reservation, **{**kwargs, "ack_ref": "ack-other"})


def test_submission_cannot_skip_durable_order_request_boundary(tmp_path: Path) -> None:
    now = datetime.now(UTC)
    store = PersistentFollowerRiskStateStore(tmp_path / "risk.sqlite3")
    reservation = store.reserve(
        follower=_follower(),
        signal_id="signal-no-boundary",
        order=_order("BTCUSDT", 100.0, client_order_id="client-no-boundary"),
        observation=_observation(now),
        limits=RiskLimits(per_order_max_usdt=500.0, single_symbol_position_pct_max=1.0),
    )

    with pytest.raises(CopyTradeRiskError, match="order-request boundary"):
        store.mark_submitted(
            reservation,
            submission_ref="submission-no-boundary",
            venue_order_ref="venue-order-no-boundary",
            ack_ref="ack-no-boundary",
        )
    assert store.state("follower-1", "account-1").open_reservation_refs == (
        reservation.reservation_ref,
    )


def test_replay_rejects_payload_mutation(tmp_path: Path) -> None:
    path = tmp_path / "risk.sqlite3"
    now = datetime.now(UTC)
    store = PersistentFollowerRiskStateStore(path)
    store.reserve(
        follower=_follower(),
        signal_id="signal-1",
        order=_order("BTCUSDT", 100.0, client_order_id="client-1"),
        observation=_observation(now),
        limits=RiskLimits(per_order_max_usdt=500.0, single_symbol_position_pct_max=1.0),
    )
    with sqlite3.connect(path) as conn:
        row = conn.execute(
            "SELECT seq,payload_json FROM ct_risk_events WHERE event_kind='pretrade_reserved'"
        ).fetchone()
        payload = json.loads(row[1])
        payload["notional_usdt"] = 0
        conn.execute(
            "UPDATE ct_risk_events SET payload_json=? WHERE seq=?",
            (json.dumps(payload, sort_keys=True), row[0]),
        )

    with pytest.raises(ValueError, match="integrity failure"):
        PersistentFollowerRiskStateStore(path)


def test_replay_rejects_tail_deletion_and_missing_key(tmp_path: Path) -> None:
    path = tmp_path / "risk.sqlite3"
    now = datetime.now(UTC)
    store = PersistentFollowerRiskStateStore(path)
    store.reserve(
        follower=_follower(),
        signal_id="signal-1",
        order=_order("BTCUSDT", 100.0, client_order_id="client-1"),
        observation=_observation(now),
        limits=RiskLimits(per_order_max_usdt=500.0, single_symbol_position_pct_max=1.0),
    )
    with sqlite3.connect(path) as conn:
        conn.execute("DELETE FROM ct_risk_events WHERE seq=(SELECT MAX(seq) FROM ct_risk_events)")

    with pytest.raises(ValueError, match="integrity head mismatch"):
        PersistentFollowerRiskStateStore(path)

    key_path = path.with_name(path.name + ".hmac.key")
    key_path.rename(tmp_path / "saved-risk-key")
    with pytest.raises(ValueError, match="integrity key is missing"):
        PersistentFollowerRiskStateStore(path)


def test_delayed_partial_and_terminal_fills_use_occurrence_day_and_close_reservation(
    tmp_path: Path,
    monkeypatch,
) -> None:
    trade_day = datetime(2026, 7, 11, 23, 50, tzinfo=UTC)
    ingestion_day = trade_day + timedelta(hours=2)
    clock = {"now": trade_day}
    monkeypatch.setattr(risk_module, "_now", lambda: clock["now"])
    store = PersistentFollowerRiskStateStore(
        tmp_path / "risk.sqlite3", allow_unsealed_test_transitions=True
    )
    reservation = store.reserve(
        follower=_follower(),
        signal_id="signal-fill",
        order=_order("BTCUSDT", 100.0, client_order_id="client-fill"),
        observation=_observation(trade_day),
        limits=RiskLimits(per_order_max_usdt=500.0, single_symbol_position_pct_max=1.0),
    )
    _start(store, reservation)
    store.mark_submitted(
        reservation,
        submission_ref="submission-1",
        venue_order_ref="venue-order-1",
        ack_ref="ack-1",
    )

    clock["now"] = ingestion_day
    store.record_fill(
        reservation,
        report=_fill(
            filled_qty=0.004,
            cumulative_filled_qty=0.004,
            status="partially_filled",
            timestamp_utc=(trade_day + timedelta(minutes=1)).isoformat(),
        ),
        submission_ref="submission-1",
        venue_event_ref="event-partial",
        normalized_cost_usdt=0.01,
        cost_conversion_ref="cost-usdt",
    )
    partial = store.state("follower-1", "account-1", day="2026-07-11")
    assert partial.filled_turnover == pytest.approx(40.0)
    assert partial.reserved_turnover == pytest.approx(60.0)
    assert partial.open_reservation_refs == (reservation.reservation_ref,)
    assert store.state("follower-1", "account-1", day="2026-07-12").filled_turnover == 0

    terminal_report = _fill(
        filled_qty=0.006,
        cumulative_filled_qty=0.01,
        status="filled",
        timestamp_utc=(trade_day + timedelta(minutes=2)).isoformat(),
    )
    store.record_fill(
        reservation,
        report=terminal_report,
        submission_ref="submission-1",
        venue_event_ref="event-terminal",
        normalized_cost_usdt=0.01,
        cost_conversion_ref="cost-usdt",
    )
    # Exact venue replay is idempotent, not a second economic fill.
    store.record_fill(
        reservation,
        report=terminal_report,
        submission_ref="submission-1",
        venue_event_ref="event-terminal",
        normalized_cost_usdt=0.01,
        cost_conversion_ref="cost-usdt",
    )
    terminal = store.state("follower-1", "account-1", day="2026-07-11")
    assert terminal.filled_turnover == pytest.approx(100.0)
    assert terminal.open_reservation_refs == ()
    assert store.has_open_reservations("follower-1", "account-1") is False


def test_fill_economics_are_owner_filtered_replay_validated_and_complete(tmp_path: Path) -> None:
    path = tmp_path / "risk.sqlite3"
    now = datetime.now(UTC)
    store = PersistentFollowerRiskStateStore(path, allow_unsealed_test_transitions=True)
    reservation = store.reserve(
        follower=_follower(),
        signal_id="signal-economics",
        order=_order("BTCUSDT", 100.0, client_order_id="client-fill"),
        observation=_observation(now),
        limits=RiskLimits(per_order_max_usdt=500.0, single_symbol_position_pct_max=1.0),
    )
    _start(store, reservation)
    store.mark_submitted(
        reservation,
        submission_ref="submission-economics",
        venue_order_ref="venue-order-1",
        ack_ref="ack-economics",
    )
    report = _fill(
        filled_qty=0.01,
        cumulative_filled_qty=0.01,
        status="filled",
        timestamp_utc=now.isoformat(),
        realized_pnl_delta=-1.25,
        realized_pnl_complete=True,
    )
    reconciliation_ref, venue_event_ref = _bind_fill_proof(
        store,
        report,
        submission_ref="submission-economics",
    )
    store.record_fill(
        reservation,
        report=report,
        submission_ref="submission-economics",
        venue_event_ref=venue_event_ref,
        normalized_cost_usdt=0.01,
        cost_conversion_ref="cost-usdt",
        reconciliation_ref=reconciliation_ref,
    )

    assert store.fill_economics_for_followers(iter(["foreign-follower"])) == ()
    records = store.fill_economics_for_followers(
        iter(["follower-1"]), signal_id="signal-economics", limit=1
    )
    assert len(records) == 1
    record = records[0]
    assert record.follower_ref == "follower-1"
    assert record.fill_price == 10_000.0
    assert record.fill_price_source == "venue_fill"
    assert record.realized_pnl_delta == -1.25
    assert record.realized_pnl_complete is True
    assert record.cost_complete is True
    assert record.fill_economics_complete is True
    assert store.state("follower-1", "account-1").realized_pnl_complete is True

    with sqlite3.connect(path) as conn:
        row = conn.execute(
            "SELECT seq,payload_json FROM ct_risk_events WHERE event_kind='fill'"
        ).fetchone()
        assert row is not None
        payload = json.loads(row[1])
        payload["fill_price"] = 1.0
        conn.execute(
            "UPDATE ct_risk_events SET payload_json=? WHERE seq=?",
            (json.dumps(payload, sort_keys=True), row[0]),
        )
    with pytest.raises(ValueError, match="integrity failure"):
        store.fill_economics_for_followers(iter(["follower-1"]))


def test_zero_fill_canceled_order_releases_accepted_reservation(tmp_path: Path) -> None:
    now = datetime.now(UTC)
    store = PersistentFollowerRiskStateStore(
        tmp_path / "risk.sqlite3", allow_unsealed_test_transitions=True
    )
    reservation = store.reserve(
        follower=_follower(),
        signal_id="signal-canceled",
        order=_order("BTCUSDT", 100.0, client_order_id="client-fill"),
        observation=_observation(now),
        limits=RiskLimits(per_order_max_usdt=500.0, single_symbol_position_pct_max=1.0),
    )
    _start(store, reservation)
    store.mark_submitted(
        reservation,
        submission_ref="submission-1",
        venue_order_ref="venue-order-1",
        ack_ref="ack-1",
    )
    observation = _terminal_observation(
        status="canceled",
        cumulative_filled_qty=0,
        observed_at_utc=now.isoformat(),
        source_ref="terminal-canceled-1",
    )
    reconciliation_ref, venue_event_ref = _bind_terminal_proof(
        store,
        observation,
        partial=False,
    )

    store.reconcile_no_effect(
        reservation,
        reconciliation_ref=reconciliation_ref,
        venue_event_ref=venue_event_ref,
        observation=observation,
    )
    store.reconcile_no_effect(
        reservation,
        reconciliation_ref=reconciliation_ref,
        venue_event_ref=venue_event_ref,
        observation=observation,
    )

    state = store.state("follower-1", "account-1")
    assert state.open_reservation_refs == ()
    assert state.reserved_turnover == 0
    assert state.filled_turnover == 0


def test_partial_fill_then_canceled_releases_only_unfilled_remainder(tmp_path: Path) -> None:
    now = datetime.now(UTC)
    store = PersistentFollowerRiskStateStore(
        tmp_path / "risk.sqlite3", allow_unsealed_test_transitions=True
    )
    reservation = store.reserve(
        follower=_follower(),
        signal_id="signal-partial-canceled",
        order=_order("BTCUSDT", 100.0, client_order_id="client-fill"),
        observation=_observation(now),
        limits=RiskLimits(per_order_max_usdt=500.0, single_symbol_position_pct_max=1.0),
    )
    _start(store, reservation)
    store.mark_submitted(
        reservation,
        submission_ref="submission-1",
        venue_order_ref="venue-order-1",
        ack_ref="ack-1",
    )
    store.record_fill(
        reservation,
        report=_fill(
            filled_qty=0.004,
            cumulative_filled_qty=0.004,
            status="partially_filled",
            timestamp_utc=now.isoformat(),
        ),
        submission_ref="submission-1",
        venue_event_ref="event-partial",
        normalized_cost_usdt=0.01,
        cost_conversion_ref="cost-usdt",
    )
    observation = _terminal_observation(
        status="canceled",
        cumulative_filled_qty=0.004,
        observed_at_utc=now.isoformat(),
        source_ref="terminal-partial-canceled-1",
    )
    reconciliation_ref, venue_event_ref = _bind_terminal_proof(
        store,
        observation,
        partial=True,
    )
    store.reconcile_partial_terminal(
        reservation,
        reconciliation_ref=reconciliation_ref,
        venue_event_ref=venue_event_ref,
        observation=observation,
    )

    state = store.state("follower-1", "account-1")
    assert state.open_reservation_refs == ()
    assert state.reserved_turnover == 0
    assert state.filled_turnover == pytest.approx(40.0)
    assert any(event["event_kind"] == "reconciled_partial_terminal" for event in store.events())


@pytest.mark.parametrize(
    ("filled_qty", "cumulative_filled_qty", "status", "message"),
    [
        (0.011, 0.011, "filled", "exceeds the reserved order quantity"),
        (0.004, 0.004, "filled", "does not cover the reserved order quantity"),
        (0.004, 0.004, "new", "partially_filled or filled"),
    ],
)
def test_fill_rejects_overfill_incomplete_terminal_and_non_fill_status(
    tmp_path: Path,
    filled_qty: float,
    cumulative_filled_qty: float,
    status: str,
    message: str,
) -> None:
    now = datetime.now(UTC)
    store = PersistentFollowerRiskStateStore(
        tmp_path / "risk.sqlite3", allow_unsealed_test_transitions=True
    )
    reservation = store.reserve(
        follower=_follower(),
        signal_id="signal-fill",
        order=_order("BTCUSDT", 100.0, client_order_id="client-fill"),
        observation=_observation(now),
        limits=RiskLimits(per_order_max_usdt=500.0, single_symbol_position_pct_max=1.0),
    )
    _start(store, reservation)
    store.mark_submitted(
        reservation,
        submission_ref="submission-1",
        venue_order_ref="venue-order-1",
        ack_ref="ack-1",
    )

    with pytest.raises(CopyTradeRiskError, match=message):
        store.record_fill(
            reservation,
            report=_fill(
                filled_qty=filled_qty,
                cumulative_filled_qty=cumulative_filled_qty,
                status=status,
                timestamp_utc=now.isoformat(),
            ),
            submission_ref="submission-1",
            venue_event_ref="event-invalid",
            normalized_cost_usdt=0.01,
            cost_conversion_ref="cost-usdt",
        )


def test_second_fill_must_advance_cumulative_quantity_exactly(tmp_path: Path) -> None:
    now = datetime.now(UTC)
    store = PersistentFollowerRiskStateStore(
        tmp_path / "risk.sqlite3", allow_unsealed_test_transitions=True
    )
    reservation = store.reserve(
        follower=_follower(),
        signal_id="signal-fill",
        order=_order("BTCUSDT", 100.0, client_order_id="client-fill"),
        observation=_observation(now),
        limits=RiskLimits(per_order_max_usdt=500.0, single_symbol_position_pct_max=1.0),
    )
    _start(store, reservation)
    store.mark_submitted(
        reservation,
        submission_ref="submission-1",
        venue_order_ref="venue-order-1",
        ack_ref="ack-1",
    )
    store.record_fill(
        reservation,
        report=_fill(
            filled_qty=0.004,
            cumulative_filled_qty=0.004,
            status="partially_filled",
            timestamp_utc=now.isoformat(),
        ),
        submission_ref="submission-1",
        venue_event_ref="event-one",
        normalized_cost_usdt=0.01,
        cost_conversion_ref="cost-usdt",
    )

    with pytest.raises(CopyTradeRiskError, match="incremental quantity conflicts"):
        store.record_fill(
            reservation,
            report=_fill(
                filled_qty=0.003,
                cumulative_filled_qty=0.008,
                status="partially_filled",
                timestamp_utc=now.isoformat(),
            ),
            submission_ref="submission-1",
            venue_event_ref="event-two",
            normalized_cost_usdt=0.01,
            cost_conversion_ref="cost-usdt",
        )


def test_unknown_submission_requires_formal_reconciliation_before_acceptance(tmp_path: Path) -> None:
    now = datetime.now(UTC)
    store = PersistentFollowerRiskStateStore(tmp_path / "risk.sqlite3")
    reservation = store.reserve(
        follower=_follower(),
        signal_id="signal-unknown",
        order=_order("BTCUSDT", 100.0, client_order_id="client-unknown"),
        observation=_observation(now),
        limits=RiskLimits(per_order_max_usdt=500.0, single_symbol_position_pct_max=1.0),
    )
    _start(store, reservation)
    store.mark_submission_unknown(reservation, reason_ref="timeout")

    with pytest.raises(CopyTradeRiskError, match="formal reconciliation"):
        store.mark_submitted(
            reservation,
            submission_ref="submission-1",
            venue_order_ref="venue-order-1",
            ack_ref="ack-1",
        )

    store.mark_submitted(
        reservation,
        submission_ref="submission-1",
        venue_order_ref="venue-order-1",
        ack_ref="ack-1",
        reconciliation_ref="execution_reconcile_v2_verified",
    )
    assert store.reservation_for_submission("submission-1") == reservation
    assert store.unresolved_reservations() == (reservation,)


def test_no_effect_release_rejects_arbitrary_reconciliation_string(tmp_path: Path) -> None:
    now = datetime.now(UTC)
    store = PersistentFollowerRiskStateStore(
        tmp_path / "risk.sqlite3", allow_unsealed_test_transitions=True
    )
    reservation = store.reserve(
        follower=_follower(),
        signal_id="signal-unknown",
        order=_order("BTCUSDT", 100.0, client_order_id="client-unknown"),
        observation=_observation(now),
        limits=RiskLimits(per_order_max_usdt=500.0, single_symbol_position_pct_max=1.0),
    )
    _start(store, reservation)
    store.mark_submission_unknown(reservation, reason_ref="timeout")

    with pytest.raises(CopyTradeRiskError, match="formal proof"):
        store.reconcile_no_effect(
            reservation,
            reconciliation_ref="execution_reconcile_v2_forged",
            venue_event_ref="venue_event_v2_forged",
            observation=replace(
                _terminal_observation(
                    status="canceled",
                    cumulative_filled_qty=0,
                    observed_at_utc=now.isoformat(),
                    source_ref="forged-terminal",
                ),
                client_order_id="client-unknown",
            ),
        )


def test_terminal_release_rejects_mutated_reservation_and_raw_payload(
    tmp_path: Path,
) -> None:
    now = datetime.now(UTC)
    store = PersistentFollowerRiskStateStore(
        tmp_path / "risk.sqlite3", allow_unsealed_test_transitions=True
    )
    reservation = store.reserve(
        follower=_follower(),
        signal_id="signal-terminal-integrity",
        order=_order("BTCUSDT", 100.0, client_order_id="client-fill"),
        observation=_observation(now),
        limits=RiskLimits(per_order_max_usdt=500.0, single_symbol_position_pct_max=1.0),
    )
    _start(store, reservation)
    store.mark_submitted(
        reservation,
        submission_ref="submission-1",
        venue_order_ref="venue-order-1",
        ack_ref="ack-1",
    )
    observation = _terminal_observation(
        status="canceled",
        cumulative_filled_qty=0,
        observed_at_utc=now.isoformat(),
        source_ref="terminal-integrity",
    )
    reconciliation_ref, venue_event_ref = _bind_terminal_proof(
        store,
        observation,
        partial=False,
    )

    with pytest.raises(CopyTradeRiskError, match="reservation content mismatch"):
        store.reconcile_no_effect(
            replace(reservation, notional_usdt=1.0),
            reconciliation_ref=reconciliation_ref,
            venue_event_ref=venue_event_ref,
            observation=observation,
        )
    with pytest.raises(CopyTradeRiskError, match="raw digest"):
        store.reconcile_no_effect(
            reservation,
            reconciliation_ref=reconciliation_ref,
            venue_event_ref=venue_event_ref,
            observation=replace(observation, raw_event_hash="sha256:" + "0" * 64),
        )

    assert store.state("follower-1", "account-1").open_reservation_refs == (
        reservation.reservation_ref,
    )
