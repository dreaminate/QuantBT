from __future__ import annotations

import os
import multiprocessing
import sqlite3
import stat
import threading
import time
from pathlib import Path
from typing import Any

import pytest

from app.security import InMemoryKeystore, KeystoreRecord, SecureKeystore
from app.security.gate.account_halt import AccountHaltError, PersistentAccountHaltBarrier
from app.security.gate.broker import KeyBroker


def _hold_cross_process_live_lease(path: str, ready, release, outcomes) -> None:
    try:
        barrier = PersistentAccountHaltBarrier(path, drain_timeout_seconds=5.0)
        keystore = SecureKeystore(InMemoryKeystore())
        keystore.store(KeystoreRecord(name="alice-key", api_key="K", api_secret="S"))
        broker = KeyBroker(
            keystore,
            hmac_key=b"h" * 32,
            account_halt_barrier=barrier,
        )
        cap = broker.issue_capability(
            action="request_live_order",
            gate_ref="gate-live",
            keystore_name="alice-key",
            account_identity_ref="exchange_account_uid_alice",
            owner_user_id="alice",
            requires_halt_fence=True,
        )
        lease = broker.issue(cap)
        ready.set()
        if not release.wait(timeout=5):
            raise TimeoutError("parent did not release cross-process lease")
        broker.revoke(lease)
        outcomes.put("ok")
    except BaseException as exc:  # noqa: BLE001 - child reports exact failure to parent.
        outcomes.put(f"{type(exc).__name__}: {exc}")


def _activate_cross_process(path: str, account_ref: str, outcomes) -> None:
    try:
        barrier = PersistentAccountHaltBarrier(path, drain_timeout_seconds=5.0)
        barrier.activate(account_ref, "alice")
        outcomes.put("ok")
    except BaseException as exc:  # noqa: BLE001
        outcomes.put(f"{type(exc).__name__}: {exc}")


def _runtime(tmp_path: Path, *, timeout: float = 2.0):
    barrier = PersistentAccountHaltBarrier(
        tmp_path / "security" / "account_halt.sqlite3",
        drain_timeout_seconds=timeout,
    )
    keystore = SecureKeystore(InMemoryKeystore())
    keystore.store(KeystoreRecord(name="alice-key", api_key="K", api_secret="S"))
    broker = KeyBroker(
        keystore,
        hmac_key=b"h" * 32,
        account_halt_barrier=barrier,
    )
    barrier.activate("exchange_account_uid_alice", "alice")
    return barrier, broker


def _live_capability(broker: KeyBroker):
    return broker.issue_capability(
        action="request_live_order",
        gate_ref="gate-live",
        keystore_name="alice-key",
        account_identity_ref="exchange_account_uid_alice",
        owner_user_id="alice",
        requires_halt_fence=True,
    )


def _wait_for_state(
    barrier: PersistentAccountHaltBarrier,
    account_ref: str,
    state: str,
    *,
    timeout: float = 1.0,
) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        snapshot = barrier.snapshot(account_ref)
        if snapshot is not None and snapshot.state == state:
            return
        time.sleep(0.005)
    raise AssertionError(f"account did not reach {state}")


def _zero_exposure_result() -> dict[str, object]:
    return {
        "ok": True,
        "normal_open_order_refs": [],
        "algo_open_order_refs": [],
        "open_positions": [],
    }


def _record_flat(
    barrier: PersistentAccountHaltBarrier,
    *,
    owner: str,
    halt_ref: str,
    snapshots: dict[str, Any],
) -> str:
    epochs = {ref: snapshot.epoch for ref, snapshot in snapshots.items()}
    return barrier.record_flat_proof(
        owner,
        halt_ref=halt_ref,
        close_positions=True,
        account_epochs=epochs,
        results={ref: _zero_exposure_result() for ref in epochs},
    )


def test_halt_evidence_resolves_exact_owner_scoped_durable_operation(tmp_path: Path) -> None:
    barrier, _broker = _runtime(tmp_path)
    halt_ref = "account_halt_platform_m20"
    barrier.begin_halt_many(
        "alice",
        ["exchange_account_uid_alice"],
        halt_ref=halt_ref,
        action_name="kill_switch",
        close_positions=True,
    )

    evidence = barrier.halt_evidence(halt_ref, owner_user_id="alice")
    assert evidence.halt_ref == halt_ref
    assert evidence.owner_user_id == "alice"
    assert evidence.owner_state == "halting"
    assert evidence.account_binding_refs == ("exchange_account_uid_alice",)
    with pytest.raises(KeyError):
        barrier.halt_evidence(halt_ref, owner_user_id="bob")
    with pytest.raises(KeyError):
        barrier.halt_evidence("account_halt_never_committed", owner_user_id="alice")

    reopened = PersistentAccountHaltBarrier(
        tmp_path / "security" / "account_halt.sqlite3"
    )
    assert reopened.halt_evidence(halt_ref, owner_user_id="alice") == evidence


def test_halt_commits_before_waiting_for_pre_halt_lease_and_blocks_new_lease(tmp_path: Path) -> None:
    barrier, broker = _runtime(tmp_path)
    pre_halt_capability = _live_capability(broker)
    lease = broker.issue(pre_halt_capability)
    assert lease.record.api_key == "K"

    completed = threading.Event()
    outcome: dict[str, object] = {}

    def halt() -> None:
        try:
            outcome["snapshots"] = barrier.begin_halt_many(
                "alice",
                ["exchange_account_uid_alice"],
                halt_ref="halt-request-1",
            )
        except BaseException as exc:  # noqa: BLE001 - assertion captures worker failure.
            outcome["error"] = exc
        finally:
            completed.set()

    worker = threading.Thread(target=halt)
    worker.start()
    _wait_for_state(barrier, "exchange_account_uid_alice", "halting")
    assert not completed.is_set(), "HALT returned before the old lease drained"

    with pytest.raises(PermissionError, match="HALT"):
        _live_capability(broker)
    with pytest.raises(PermissionError, match="HALT"):
        broker.issue(pre_halt_capability)
    with pytest.raises(PermissionError, match="owner"):
        barrier.activate("exchange_account_uid_new", "alice")

    broker.revoke(lease)
    worker.join(timeout=2)
    assert completed.is_set()
    assert "error" not in outcome
    assert barrier.snapshot("exchange_account_uid_alice").state == "halting"  # type: ignore[union-attr]


def test_halt_finalize_resume_rejects_stale_capability(tmp_path: Path) -> None:
    barrier, broker = _runtime(tmp_path)
    stale = _live_capability(broker)
    snapshots = barrier.begin_halt_many(
        "alice",
        ["exchange_account_uid_alice"],
        halt_ref="halt-request-2",
    )
    halted = barrier.finalize_halt_many(
        "alice",
        {ref: snapshot.epoch for ref, snapshot in snapshots.items()},
        flat_proof_ref=_record_flat(
            barrier,
            owner="alice",
            halt_ref="halt-request-2",
            snapshots=snapshots,
        ),
    )
    assert halted["exchange_account_uid_alice"].state == "halted"

    resumed = barrier.resume(
        "exchange_account_uid_alice",
        "alice",
        authorization_ref="two-person-resume-approval",
    )
    assert resumed.state == "running"
    assert resumed.execution_enabled is False
    assert resumed.epoch > stale.account_halt_epoch  # type: ignore[operator]
    with pytest.raises(PermissionError, match="not enabled|epoch/state changed"):
        broker.issue(stale)

    barrier.enable("exchange_account_uid_alice", "alice")
    current = _live_capability(broker)
    lease = broker.issue(current)
    broker.revoke(lease)


def test_individual_and_multi_account_resume_are_reachable_but_disabled_by_default(
    tmp_path: Path,
) -> None:
    barrier, _broker = _runtime(tmp_path)
    barrier.activate("exchange_account_uid_second", "alice")
    first = barrier.begin_account_halt(
        "exchange_account_uid_alice",
        "alice",
        halt_ref="individual-stop",
        action_name="copy_trade_unsubscribe",
        close_positions=True,
    )
    barrier.finalize_account_halt(
        "exchange_account_uid_alice",
        "alice",
        expected_epoch=first.epoch,
        flat_proof_ref=_record_flat(
            barrier,
            owner="alice",
            halt_ref="individual-stop",
            snapshots={first.account_binding_ref: first},
        ),
    )
    assert barrier.owner_state("alice") == "running"
    resumed_first = barrier.resume(
        "exchange_account_uid_alice",
        "alice",
        authorization_ref="individual-reattestation",
    )
    assert resumed_first.state == "running"
    assert resumed_first.execution_enabled is False

    barrier.enable("exchange_account_uid_alice", "alice")
    halted = barrier.begin_halt_many(
        "alice",
        ["exchange_account_uid_alice", "exchange_account_uid_second"],
        halt_ref="global-stop",
    )
    barrier.finalize_halt_many(
        "alice",
        {ref: snapshot.epoch for ref, snapshot in halted.items()},
        flat_proof_ref=_record_flat(
            barrier,
            owner="alice",
            halt_ref="global-stop",
            snapshots=halted,
        ),
    )
    assert barrier.owner_state("alice") == "halted"
    for account_ref in ("exchange_account_uid_alice", "exchange_account_uid_second"):
        snapshot = barrier.resume(
            account_ref,
            "alice",
            authorization_ref=f"reattest-{account_ref}",
        )
        assert snapshot.state == "running"
        assert snapshot.execution_enabled is False
    assert barrier.owner_state("alice") == "running"


def test_owner_latch_discovers_every_account_and_finalization_is_atomic(tmp_path: Path) -> None:
    barrier, _broker = _runtime(tmp_path)
    barrier.activate("exchange_account_uid_second", "alice")
    snapshots = barrier.begin_halt_many(
        "alice",
        ["exchange_account_uid_alice"],
        halt_ref="halt-all",
    )
    assert set(snapshots) == {
        "exchange_account_uid_alice",
        "exchange_account_uid_second",
    }
    assert {snapshot.state for snapshot in snapshots.values()} == {"halting"}

    incomplete = {
        "exchange_account_uid_alice": snapshots["exchange_account_uid_alice"]
    }
    with pytest.raises(PermissionError, match="not every owned account"):
        barrier.finalize_halt_many(
            "alice",
            {"exchange_account_uid_alice": snapshots["exchange_account_uid_alice"].epoch},
            flat_proof_ref=_record_flat(
                barrier,
                owner="alice",
                halt_ref="halt-all",
                snapshots=incomplete,
            ),
        )
    assert barrier.snapshot("exchange_account_uid_alice").state == "halting"  # type: ignore[union-attr]
    assert barrier.snapshot("exchange_account_uid_second").state == "halting"  # type: ignore[union-attr]

    finalized = barrier.finalize_halt_many(
        "alice",
        {ref: snapshot.epoch for ref, snapshot in snapshots.items()},
        flat_proof_ref=_record_flat(
            barrier,
            owner="alice",
            halt_ref="halt-all",
            snapshots=snapshots,
        ),
    )
    assert {snapshot.state for snapshot in finalized.values()} == {"halted"}


def test_global_halt_operation_intent_is_persisted_and_reopened_exactly(tmp_path: Path) -> None:
    path = tmp_path / "halt.sqlite3"
    barrier = PersistentAccountHaltBarrier(path)
    barrier.activate("exchange_account_uid_alice", "alice")
    barrier.begin_halt_many(
        "alice",
        ["exchange_account_uid_alice"],
        halt_ref="cancel-only-request",
        action_name="kill_switch",
        close_positions=False,
    )

    reopened = PersistentAccountHaltBarrier(path)
    operation = reopened.owner_halt_operation("alice")
    assert operation.halt_ref == "cancel-only-request"
    assert operation.action_name == "kill_switch"
    assert operation.close_positions is False
    with pytest.raises(Exception, match="intent changed"):
        reopened.begin_halt_many(
            "alice",
            ["exchange_account_uid_alice"],
            halt_ref="cancel-only-request",
            action_name="kill_switch",
            close_positions=True,
        )


def test_individual_halt_intent_is_persisted_immutable_and_cleared_on_resume(
    tmp_path: Path,
) -> None:
    path = tmp_path / "halt.sqlite3"
    barrier = PersistentAccountHaltBarrier(path)
    barrier.activate("exchange_account_uid_alice", "alice")
    first = barrier.begin_account_halt(
        "exchange_account_uid_alice",
        "alice",
        halt_ref="individual-unsubscribe",
        action_name="copy_trade_unsubscribe",
        close_positions=True,
    )

    reopened = PersistentAccountHaltBarrier(path)
    operation = reopened.account_halt_operation(
        "exchange_account_uid_alice",
        "alice",
    )
    assert operation.halt_ref == "individual-unsubscribe"
    assert operation.action_name == "copy_trade_unsubscribe"
    assert operation.close_positions is True
    with pytest.raises(AccountHaltError, match="intent changed for the same ref"):
        reopened.begin_account_halt(
            "exchange_account_uid_alice",
            "alice",
            halt_ref="individual-unsubscribe",
            action_name="copy_trade_startup_quarantine",
            close_positions=False,
        )

    preserved = reopened.begin_account_halt(
        "exchange_account_uid_alice",
        "alice",
        halt_ref="automated-quarantine-must-not-downgrade",
        action_name="copy_trade_startup_quarantine",
        close_positions=False,
    )
    assert preserved.halt_ref == "individual-unsubscribe"
    assert preserved.halt_action_name == "copy_trade_unsubscribe"
    assert preserved.halt_close_positions is True

    proof = _record_flat(
        reopened,
        owner="alice",
        halt_ref="individual-unsubscribe",
        snapshots={first.account_binding_ref: preserved},
    )
    reopened.finalize_account_halt(
        first.account_binding_ref,
        "alice",
        expected_epoch=preserved.epoch,
        flat_proof_ref=proof,
    )
    resumed = reopened.resume(
        first.account_binding_ref,
        "alice",
        authorization_ref="individual-re-attestation",
    )
    assert resumed.state == "running"
    assert resumed.halt_action_name is None
    assert resumed.halt_close_positions is None
    with pytest.raises(PermissionError, match="no incomplete HALT"):
        reopened.account_halt_operation(first.account_binding_ref, "alice")


def test_individual_cancel_only_intent_can_only_upgrade_to_explicit_unsubscribe(
    tmp_path: Path,
) -> None:
    barrier, _broker = _runtime(tmp_path)
    quarantine = barrier.begin_account_halt(
        "exchange_account_uid_alice",
        "alice",
        halt_ref="startup-quarantine",
        action_name="copy_trade_startup_quarantine",
        close_positions=False,
    )
    assert quarantine.halt_close_positions is False

    upgraded = barrier.begin_account_halt(
        "exchange_account_uid_alice",
        "alice",
        halt_ref="explicit-unsubscribe",
        action_name="copy_trade_unsubscribe",
        close_positions=True,
    )
    operation = barrier.account_halt_operation(
        "exchange_account_uid_alice",
        "alice",
    )
    assert upgraded.epoch == quarantine.epoch
    assert operation.halt_ref == "explicit-unsubscribe"
    assert operation.action_name == "copy_trade_unsubscribe"
    assert operation.close_positions is True

    with pytest.raises(ValueError, match="action_name is unsupported"):
        barrier.begin_account_halt(
            "exchange_account_uid_alice",
            "alice",
            halt_ref="unknown-operation",
            action_name="unknown_action",
            close_positions=True,
        )
    assert barrier.account_halt_operation(
        "exchange_account_uid_alice",
        "alice",
    ) == operation


def test_fresh_repeat_global_halt_reopens_owner_and_explicit_account(tmp_path: Path) -> None:
    barrier, _broker = _runtime(tmp_path)
    first = barrier.begin_halt_many(
        "alice",
        ["exchange_account_uid_alice"],
        halt_ref="first-kill",
        action_name="kill_switch",
        close_positions=True,
    )
    barrier.finalize_halt_many(
        "alice",
        {ref: snapshot.epoch for ref, snapshot in first.items()},
        flat_proof_ref=_record_flat(
            barrier,
            owner="alice",
            halt_ref="first-kill",
            snapshots=first,
        ),
    )

    second = barrier.begin_halt_many(
        "alice",
        ["exchange_account_uid_alice"],
        halt_ref="second-kill",
        action_name="kill_switch",
        close_positions=True,
    )

    assert barrier.owner_state("alice") == "halting"
    assert second["exchange_account_uid_alice"].state == "halting"
    assert second["exchange_account_uid_alice"].halt_ref == "second-kill"
    assert barrier.halting_owner_ids() == ("alice",)
    assert barrier.owner_halt_operation("alice").halt_ref == "second-kill"


def test_in_progress_close_intent_cannot_be_downgraded_to_cancel_only(tmp_path: Path) -> None:
    barrier, _broker = _runtime(tmp_path)
    barrier.begin_halt_many(
        "alice",
        ["exchange_account_uid_alice"],
        halt_ref="old-close",
        action_name="kill_switch",
        close_positions=True,
    )
    old = barrier.owner_halt_operation("alice")
    barrier.begin_halt_many(
        "alice",
        ["exchange_account_uid_alice"],
        halt_ref="new-cancel-only",
        action_name="kill_switch",
        close_positions=False,
    )

    current = barrier.owner_halt_operation("alice")
    assert current == old
    assert current.close_positions is True
    assert barrier.snapshot("exchange_account_uid_alice").halt_ref == old.halt_ref  # type: ignore[union-attr]


def test_in_progress_cancel_only_intent_can_only_upgrade_to_close(tmp_path: Path) -> None:
    barrier, _broker = _runtime(tmp_path)
    barrier.begin_halt_many(
        "alice",
        ["exchange_account_uid_alice"],
        halt_ref="old-cancel-only",
        action_name="kill_switch",
        close_positions=False,
    )
    old = barrier.owner_halt_operation("alice")

    upgraded = barrier.begin_halt_many(
        "alice",
        ["exchange_account_uid_alice"],
        halt_ref="new-close",
        action_name="emergency_close_all",
        close_positions=True,
    )

    current = barrier.owner_halt_operation("alice")
    assert current.halt_ref == "new-close"
    assert current.close_positions is True
    assert upgraded["exchange_account_uid_alice"].halt_ref == "new-close"
    with pytest.raises(PermissionError, match="recovery intent changed"):
        barrier.begin_halt_many(
            "alice",
            ["exchange_account_uid_alice"],
            halt_ref=old.halt_ref,
            action_name=old.action_name,
            close_positions=old.close_positions,
            expected_owner_epoch=old.epoch,
        )


def test_missing_account_state_denies_live_capability_without_key_fetch(tmp_path: Path) -> None:
    barrier = PersistentAccountHaltBarrier(tmp_path / "halt.sqlite3")

    class CountingKeystore:
        fetched = 0

        def fetch(self, _name: str):
            self.fetched += 1
            return {"api_key": "K", "api_secret": "S"}

    keystore = CountingKeystore()
    broker = KeyBroker(
        keystore,
        hmac_key=b"h" * 32,
        account_halt_barrier=barrier,
    )
    with pytest.raises(PermissionError, match="owner latch is missing"):
        broker.issue_capability(
            action="request_live_order",
            gate_ref="g",
            keystore_name="key",
            account_identity_ref="missing-account",
            owner_user_id="alice",
            requires_halt_fence=True,
        )
    assert keystore.fetched == 0


def test_live_fence_requirement_cannot_degrade_when_barrier_is_absent(tmp_path: Path) -> None:
    keystore = SecureKeystore(InMemoryKeystore())
    keystore.store(KeystoreRecord(name="key", api_key="K", api_secret="S"))
    broker = KeyBroker(keystore, hmac_key=b"h" * 32)
    with pytest.raises(PermissionError, match="requires an available account HALT barrier"):
        broker.issue_capability(
            action="request_live_order",
            gate_ref="g",
            keystore_name="key",
            account_identity_ref="exchange_account_uid_alice",
            owner_user_id="alice",
            requires_halt_fence=True,
        )

    # The signed compatibility path remains available for non-mainnet tests.
    cap = broker.issue_capability(
        action="request_live_order",
        gate_ref="g",
        keystore_name="key",
        requires_halt_fence=False,
    )
    lease = broker.issue(cap)
    broker.revoke(lease)


def test_missing_state_can_only_be_synthesized_as_halting_for_emergency(tmp_path: Path) -> None:
    barrier = PersistentAccountHaltBarrier(tmp_path / "halt.sqlite3")
    with pytest.raises(PermissionError, match="owner latch is missing"):
        barrier.begin_halt_many(
            "alice",
            ["exchange_account_uid_alice"],
            halt_ref="halt-missing",
        )
    snapshots = barrier.begin_halt_many(
        "alice",
        ["exchange_account_uid_alice"],
        halt_ref="halt-missing",
        allow_missing=True,
    )
    assert snapshots["exchange_account_uid_alice"].state == "halting"
    with pytest.raises(PermissionError, match="owner state=halting"):
        barrier.running_epoch("exchange_account_uid_alice", "alice")


def test_empty_global_halt_latches_owner_and_blocks_late_activation(tmp_path: Path) -> None:
    barrier = PersistentAccountHaltBarrier(tmp_path / "halt.sqlite3")
    batch = barrier.begin_halt_many_partial(
        "alice",
        [],
        halt_ref="empty-kill",
        allow_missing=True,
        action_name="kill_switch",
        close_positions=True,
    )
    assert batch.snapshots == {}
    assert barrier.owner_state("alice") == "halting"
    owner_proof = barrier.record_flat_proof(
        "alice",
        halt_ref="empty-kill",
        close_positions=True,
        account_epochs={},
        results={},
    )
    barrier.finalize_owner_halt_if_complete("alice", proof_ref=owner_proof)
    assert barrier.owner_state("alice") == "halted"
    with pytest.raises(PermissionError, match="owner"):
        barrier.activate("exchange_account_uid_late", "alice")


def test_disabled_account_under_halted_owner_has_dedicated_reattestation_path(tmp_path: Path) -> None:
    barrier = PersistentAccountHaltBarrier(tmp_path / "halt.sqlite3")
    snapshot, created = barrier.provision("exchange_account_uid_disabled", "alice")
    assert created is True and snapshot.execution_enabled is False
    barrier.begin_halt_many(
        "alice",
        [],
        halt_ref="owner-kill-disabled-only",
        action_name="kill_switch",
        close_positions=True,
    )
    owner_proof = barrier.record_flat_proof(
        "alice",
        halt_ref="owner-kill-disabled-only",
        close_positions=True,
        account_epochs={},
        results={},
    )
    barrier.finalize_owner_halt_if_complete("alice", proof_ref=owner_proof)

    resumed = barrier.resume(
        "exchange_account_uid_disabled",
        "alice",
        authorization_ref="new-user-reattestation",
    )
    assert resumed.state == "running"
    assert resumed.execution_enabled is False
    assert barrier.owner_state("alice") == "running"


def test_empty_halted_owner_reattestation_atomically_provisions_disabled_account(
    tmp_path: Path,
) -> None:
    barrier = PersistentAccountHaltBarrier(tmp_path / "halt.sqlite3")
    barrier.begin_halt_many(
        "alice",
        [],
        halt_ref="empty-owner-kill",
        allow_missing=True,
        action_name="kill_switch",
        close_positions=True,
    )
    owner_proof = barrier.record_flat_proof(
        "alice",
        halt_ref="empty-owner-kill",
        close_positions=True,
        account_epochs={},
        results={},
    )
    barrier.finalize_owner_halt_if_complete("alice", proof_ref=owner_proof)

    staged = barrier.provision_after_owner_resume(
        "exchange_account_uid_new",
        "alice",
        authorization_ref="fresh-user-risk-choice",
    )

    assert barrier.owner_state("alice") == "running"
    assert staged.state == "running"
    assert staged.execution_enabled is False
    with pytest.raises(PermissionError, match="not enabled"):
        barrier.running_epoch(staged.account_binding_ref, "alice")
    barrier.begin_halt_many(
        "alice",
        [],
        halt_ref="disabled-account-owner-kill",
        action_name="kill_switch",
        close_positions=True,
    )
    second_owner_proof = barrier.record_flat_proof(
        "alice",
        halt_ref="disabled-account-owner-kill",
        close_positions=True,
        account_epochs={},
        results={},
    )
    barrier.finalize_owner_halt_if_complete("alice", proof_ref=second_owner_proof)
    with pytest.raises(PermissionError, match="account-specific resume"):
        barrier.provision_after_owner_resume(
            "exchange_account_uid_other",
            "alice",
            authorization_ref="another-choice",
        )


def test_empty_scope_flat_proof_cannot_replay_across_owner_epochs(tmp_path: Path) -> None:
    barrier = PersistentAccountHaltBarrier(tmp_path / "halt.sqlite3")
    fixed_halt_ref = "reused-empty-ref"
    barrier.begin_halt_many(
        "alice",
        [],
        halt_ref=fixed_halt_ref,
        allow_missing=True,
        action_name="kill_switch",
        close_positions=True,
    )
    first_proof = barrier.record_flat_proof(
        "alice",
        halt_ref=fixed_halt_ref,
        close_positions=True,
        account_epochs={},
        results={},
    )
    first_payload = barrier.flat_proof(first_proof)
    barrier.finalize_owner_halt_if_complete("alice", proof_ref=first_proof)
    barrier.provision_after_owner_resume(
        "exchange_account_uid_disabled",
        "alice",
        authorization_ref="fresh-reattestation",
    )
    barrier.begin_halt_many(
        "alice",
        [],
        halt_ref=fixed_halt_ref,
        action_name="kill_switch",
        close_positions=True,
    )
    second_proof = barrier.record_flat_proof(
        "alice",
        halt_ref=fixed_halt_ref,
        close_positions=True,
        account_epochs={},
        results={},
    )
    second_payload = barrier.flat_proof(second_proof)

    assert second_payload["owner_epoch"] > first_payload["owner_epoch"]
    assert second_proof != first_proof
    with pytest.raises(PermissionError, match="stale owner epoch"):
        barrier.finalize_owner_halt_if_complete("alice", proof_ref=first_proof)
    assert barrier.owner_state("alice") == "halting"
    barrier.finalize_owner_halt_if_complete("alice", proof_ref=second_proof)
    assert barrier.owner_state("alice") == "halted"


@pytest.mark.parametrize("column", ["owner_epoch", "created_at_utc"])
def test_flat_proof_owner_epoch_or_timestamp_tamper_fails_closed(
    tmp_path: Path,
    column: str,
) -> None:
    path = tmp_path / f"halt-{column}.sqlite3"
    barrier = PersistentAccountHaltBarrier(path)
    barrier.begin_halt_many(
        "alice",
        [],
        halt_ref=f"tamper-{column}",
        allow_missing=True,
        action_name="kill_switch",
        close_positions=True,
    )
    proof = barrier.record_flat_proof(
        "alice",
        halt_ref=f"tamper-{column}",
        close_positions=True,
        account_epochs={},
        results={},
    )
    conn = sqlite3.connect(path)
    try:
        if column == "owner_epoch":
            conn.execute(
                "UPDATE account_halt_flat_proofs SET owner_epoch=owner_epoch+2 "
                "WHERE flat_proof_ref=?",
                (proof,),
            )
        else:
            conn.execute(
                "UPDATE account_halt_flat_proofs "
                "SET created_at_utc='2099-01-01T00:00:00+00:00' "
                "WHERE flat_proof_ref=?",
                (proof,),
            )
        conn.commit()
    finally:
        conn.close()

    with pytest.raises(AccountHaltError, match="identity does not match"):
        barrier.flat_proof(proof)
    with pytest.raises(AccountHaltError, match="identity does not match"):
        barrier.finalize_owner_halt_if_complete("alice", proof_ref=proof)
    assert barrier.owner_state("alice") == "halting"


def test_flat_proof_missing_mismatched_or_tampered_rejects_atomically(tmp_path: Path) -> None:
    path = tmp_path / "halt.sqlite3"
    barrier = PersistentAccountHaltBarrier(path)
    barrier.activate("exchange_account_uid_alice", "alice")
    snapshot = barrier.begin_account_halt(
        "exchange_account_uid_alice",
        "alice",
        halt_ref="strict-proof-halt",
        action_name="copy_trade_unsubscribe",
        close_positions=True,
    )

    with pytest.raises(PermissionError, match="proof is missing"):
        barrier.finalize_account_halt(
            snapshot.account_binding_ref,
            "alice",
            expected_epoch=snapshot.epoch,
            flat_proof_ref="arbitrary-nonempty-ref",
        )
    assert barrier.snapshot(snapshot.account_binding_ref).state == "halting"  # type: ignore[union-attr]

    wrong_operation = barrier.record_flat_proof(
        "alice",
        halt_ref="different-halt",
        close_positions=True,
        account_epochs={snapshot.account_binding_ref: snapshot.epoch},
        results={snapshot.account_binding_ref: _zero_exposure_result()},
    )
    with pytest.raises(PermissionError, match="different HALT operation"):
        barrier.finalize_account_halt(
            snapshot.account_binding_ref,
            "alice",
            expected_epoch=snapshot.epoch,
            flat_proof_ref=wrong_operation,
        )

    valid = _record_flat(
        barrier,
        owner="alice",
        halt_ref="strict-proof-halt",
        snapshots={snapshot.account_binding_ref: snapshot},
    )
    conn = sqlite3.connect(path)
    try:
        conn.execute(
            "UPDATE account_halt_flat_proofs SET results_json=? WHERE flat_proof_ref=?",
            (
                '{"exchange_account_uid_alice":{"ok":true,'
                '"normal_open_order_refs":[],"algo_open_order_refs":[],'
                '"open_positions":[{"symbol":"BTCUSDT","quantity":1}]}}',
                valid,
            ),
        )
        conn.commit()
    finally:
        conn.close()
    with pytest.raises(Exception, match="zero venue exposure|identity"):
        barrier.flat_proof(valid)
    with pytest.raises(Exception, match="zero venue exposure|identity"):
        barrier.finalize_account_halt(
            snapshot.account_binding_ref,
            "alice",
            expected_epoch=snapshot.epoch,
            flat_proof_ref=valid,
        )
    assert barrier.snapshot(snapshot.account_binding_ref).state == "halting"  # type: ignore[union-attr]


def test_barrier_storage_is_private_and_reopen_preserves_halting(tmp_path: Path) -> None:
    path = tmp_path / "security" / "account_halt.sqlite3"
    barrier = PersistentAccountHaltBarrier(path)
    barrier.activate("exchange_account_uid_alice", "alice")
    barrier.begin_halt_many(
        "alice",
        ["exchange_account_uid_alice"],
        halt_ref="restart-halt",
    )
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert stat.S_IMODE(path.parent.stat().st_mode) == 0o700

    reopened = PersistentAccountHaltBarrier(path)
    assert reopened.snapshot("exchange_account_uid_alice").state == "halting"  # type: ignore[union-attr]
    with pytest.raises(PermissionError, match="state=halting"):
        reopened.running_epoch("exchange_account_uid_alice", "alice")

    os.chmod(path, 0o644)
    with pytest.raises(RuntimeError, match="0600"):
        reopened.snapshot("exchange_account_uid_alice")


def test_cross_process_flock_drains_pre_halt_lease_before_return(tmp_path: Path) -> None:
    path = tmp_path / "security" / "account_halt.sqlite3"
    barrier = PersistentAccountHaltBarrier(path, drain_timeout_seconds=5.0)
    barrier.activate("exchange_account_uid_alice", "alice")
    context = multiprocessing.get_context("spawn")
    ready = context.Event()
    release = context.Event()
    outcomes = context.Queue()
    process = context.Process(
        target=_hold_cross_process_live_lease,
        args=(str(path), ready, release, outcomes),
    )
    process.start()
    assert ready.wait(timeout=5), "child did not acquire its live lease"

    completed = threading.Event()
    failures: list[BaseException] = []

    def halt() -> None:
        try:
            barrier.begin_halt_many(
                "alice",
                ["exchange_account_uid_alice"],
                halt_ref="cross-process-halt",
            )
        except BaseException as exc:  # noqa: BLE001
            failures.append(exc)
        finally:
            completed.set()

    worker = threading.Thread(target=halt)
    worker.start()
    _wait_for_state(barrier, "exchange_account_uid_alice", "halting")
    assert not completed.is_set()
    release.set()
    worker.join(timeout=5)
    process.join(timeout=5)
    if process.is_alive():
        process.terminate()
        process.join(timeout=2)
        raise AssertionError("cross-process lease holder did not exit")
    assert process.exitcode == 0
    assert outcomes.get(timeout=1) == "ok"
    assert failures == []
    assert completed.is_set()


def test_owner_latch_serializes_cross_process_activation_before_and_after_kill(tmp_path: Path) -> None:
    context = multiprocessing.get_context("spawn")
    path = tmp_path / "before" / "account_halt.sqlite3"
    barrier = PersistentAccountHaltBarrier(path)
    barrier.activate("exchange_account_uid_a", "alice")
    outcomes = context.Queue()
    process = context.Process(
        target=_activate_cross_process,
        args=(str(path), "exchange_account_uid_b", outcomes),
    )
    process.start()
    process.join(timeout=5)
    assert process.exitcode == 0
    assert outcomes.get(timeout=1) == "ok"
    snapshots = barrier.begin_halt_many(
        "alice",
        ["exchange_account_uid_a"],
        halt_ref="activation-before-kill",
    )
    assert set(snapshots) == {"exchange_account_uid_a", "exchange_account_uid_b"}

    after_path = tmp_path / "after" / "account_halt.sqlite3"
    after = PersistentAccountHaltBarrier(after_path)
    after.activate("exchange_account_uid_a", "alice")
    after.begin_halt_many(
        "alice",
        ["exchange_account_uid_a"],
        halt_ref="kill-before-activation",
    )
    after_outcomes = context.Queue()
    rejected = context.Process(
        target=_activate_cross_process,
        args=(str(after_path), "exchange_account_uid_c", after_outcomes),
    )
    rejected.start()
    rejected.join(timeout=5)
    assert rejected.exitcode == 0
    assert after_outcomes.get(timeout=1).startswith("PermissionError:")
    assert after.snapshot("exchange_account_uid_c") is None
