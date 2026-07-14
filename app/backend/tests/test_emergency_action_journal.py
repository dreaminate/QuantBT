from __future__ import annotations

import json
import sqlite3
import threading
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

import app.execution.emergency_journal as emergency_journal_module
from app.execution.emergency_journal import (
    EmergencyActionError,
    EmergencyActionJournal,
)
from app.security.gate.account_halt import AccountHaltError, PersistentAccountHaltBarrier


def _journal(tmp_path: Path) -> EmergencyActionJournal:
    return EmergencyActionJournal(
        tmp_path / "emergency.sqlite3",
        mirror_path=tmp_path / "emergency.jsonl",
        integrity_key_path=tmp_path / "emergency.hmac.key",
    )


def _prepare(journal: EmergencyActionJournal):
    return journal.prepare(
        owner_user_id="alice",
        halt_ref="halt-1",
        owner_epoch=3,
        account_ref="exchange-account-1",
        account_epoch=7,
        credential_binding_ref="credential-1",
        symbol="btcusdt",
        side="sell",
        quantity=0.25,
    )


def _flat() -> dict:
    return {
        "ok": True,
        "normal_open_order_refs": [],
        "algo_open_order_refs": [],
        "open_positions": [],
        "source": "fresh-venue-snapshot",
    }


def _observed_at() -> str:
    return datetime.now(UTC).isoformat(timespec="microseconds")


def _downgrade_action_table_to_legacy_check(journal: EmergencyActionJournal) -> None:
    columns = ",".join(journal._ACTION_DB_FIELDS)
    conn = sqlite3.connect(journal.path, isolation_level=None)
    try:
        conn.execute("PRAGMA foreign_keys=OFF")
        conn.execute("BEGIN IMMEDIATE")
        conn.execute(
            journal._action_table_ddl(
            "emergency_close_actions__v2_new",
            if_not_exists=False,
            include_filled_residual=False,
            include_manual_unknown_flat=False,
            )
        )
        conn.execute(
            "INSERT INTO emergency_close_actions__v2_new ("
            + columns
            + ") SELECT "
            + columns
            + " FROM emergency_close_actions"
        )
        conn.execute("DROP TABLE emergency_close_actions")
        conn.execute(
            "ALTER TABLE emergency_close_actions__v2_new "
            "RENAME TO emergency_close_actions"
        )
        indexes = journal._index_ddls(
            if_not_exists=False,
            include_manual_unknown_flat=False,
        )
        for name in (
            "idx_emergency_actions_halt",
            "idx_emergency_one_active_symbol_action",
            "idx_emergency_one_active_account_epoch_symbol",
        ):
            conn.execute(indexes[name])
        conn.execute("DROP INDEX idx_emergency_unknown_resolution_action")
        conn.execute("DROP TABLE emergency_unknown_submission_resolutions")
        conn.execute("PRAGMA user_version=0")
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _downgrade_indexes_to_v3(journal: EmergencyActionJournal) -> None:
    with sqlite3.connect(journal.path) as conn:
        conn.execute("BEGIN IMMEDIATE")
        indexes = journal._index_ddls(
            if_not_exists=False,
            include_resolution=True,
            include_manual_unknown_flat=False,
        )
        for name in (
            "idx_emergency_one_active_symbol_action",
            "idx_emergency_one_active_account_epoch_symbol",
        ):
            conn.execute(f"DROP INDEX {name}")
            conn.execute(indexes[name])
        conn.execute("PRAGMA user_version=3")
        conn.commit()


def _downgrade_action_table_to_v2(journal: EmergencyActionJournal) -> None:
    columns = ",".join(journal._ACTION_DB_FIELDS)
    conn = sqlite3.connect(journal.path, isolation_level=None)
    try:
        conn.execute("PRAGMA foreign_keys=OFF")
        conn.execute("BEGIN IMMEDIATE")
        conn.execute(
            journal._action_table_ddl(
                "emergency_close_actions__v2_new",
                if_not_exists=False,
                include_filled_residual=True,
                include_manual_unknown_flat=False,
            )
        )
        conn.execute(
            "INSERT INTO emergency_close_actions__v2_new ("
            + columns
            + ") SELECT "
            + columns
            + " FROM emergency_close_actions"
        )
        conn.execute("DROP TABLE emergency_close_actions")
        conn.execute(
            "ALTER TABLE emergency_close_actions__v2_new "
            "RENAME TO emergency_close_actions"
        )
        indexes = journal._index_ddls(
            if_not_exists=False,
            include_resolution=False,
            include_manual_unknown_flat=False,
        )
        for name in (
            "idx_emergency_actions_halt",
            "idx_emergency_one_active_symbol_action",
            "idx_emergency_one_active_account_epoch_symbol",
        ):
            conn.execute(indexes[name])
        conn.execute("DROP INDEX idx_emergency_unknown_resolution_action")
        conn.execute("DROP TABLE emergency_unknown_submission_resolutions")
        conn.execute("PRAGMA user_version=2")
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def test_prepare_is_concurrent_idempotent_and_uses_wal_with_durable_mirror(tmp_path: Path):
    journal = _journal(tmp_path)
    refs: list[str] = []
    errors: list[BaseException] = []
    barrier = threading.Barrier(5)

    def worker() -> None:
        try:
            barrier.wait(timeout=5)
            refs.append(_prepare(journal).action_ref)
        except BaseException as exc:  # noqa: BLE001 - test captures thread failures.
            errors.append(exc)

    threads = [threading.Thread(target=worker) for _ in range(5)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=10)

    assert errors == []
    assert len(set(refs)) == 1
    action = journal.action(refs[0])
    assert action.status == "prepared"
    assert action.client_order_id.startswith("qbt-kill-")
    assert len(action.client_order_id) <= 36
    with sqlite3.connect(journal.path) as conn:
        assert conn.execute("PRAGMA journal_mode").fetchone()[0].lower() == "wal"
        assert conn.execute("SELECT COUNT(*) FROM emergency_close_actions").fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM emergency_close_action_events").fetchone()[0] == 1
    mirror_rows = [json.loads(line) for line in journal.mirror_path.read_text().splitlines()]
    assert len(mirror_rows) == 1
    assert mirror_rows[0]["event_ref"] == action.last_event_ref

    reopened = _journal(tmp_path)
    assert reopened.action(action.action_ref) == action
    assert reopened.sync_mirror() == 0


def test_unknown_submission_resolution_is_atomic_sealed_and_non_retryable(
    tmp_path: Path,
) -> None:
    journal = _journal(tmp_path)
    action = journal.mark_submitting(_prepare(journal).action_ref)
    terminal, resolution = journal.resolve_unknown_submission(
        action.action_ref,
        owner_user_id="alice",
        resolving_halt_ref="halt-1",
        resolving_owner_epoch=3,
        account_ref="exchange-account-1",
        account_epoch=7,
        operator_user_id="alice",
        operator_auth_audit_ref="mainnet_audit_v1_authorized",
        lookup_code=-2013,
        lookup_observed_at_utc=_observed_at(),
        flat_verification=_flat(),
        flat_observed_at_utc=_observed_at(),
        expected_action_event_ref=action.last_event_ref,
    )

    assert terminal.status == "manual_unknown_flat"
    assert terminal.terminal_status == "submission_unknown_manual_only"
    assert terminal.verified_flat is True
    assert resolution.historical_submission_outcome == "unknown"
    assert resolution.historical_fill_state == "unknown"
    assert resolution.automatic_retry_permitted is False
    assert resolution.expected_action_event_ref == action.last_event_ref
    assert terminal.observation_ref == resolution.resolution_ref
    assert (
        journal.unknown_submission_resolution(
            action.action_ref,
            owner_user_id="alice",
        )
        == resolution
    )
    binding = journal.build_flat_proof_binding(
        owner_user_id="alice",
        halt_ref="halt-1",
        owner_epoch=3,
        account_ref="exchange-account-1",
        account_epoch=7,
        flat_verification=_flat(),
    )
    assert journal.validate_flat_proof_binding(
        binding,
        owner_user_id="alice",
        halt_ref="halt-1",
        owner_epoch=3,
        account_ref="exchange-account-1",
        account_epoch=7,
        flat_verification=_flat(),
    ) == binding
    journal.validate_replay()

    reopened = _journal(tmp_path)
    assert reopened.action(action.action_ref) == terminal
    assert reopened.unknown_submission_resolution(
        action.action_ref,
        owner_user_id="alice",
    ) == resolution
    assert _prepare(reopened).action_ref == action.action_ref
    with pytest.raises(EmergencyActionError, match="cannot transition"):
        reopened.mark_submitting(action.action_ref)


def test_unknown_submission_resolution_head_cas_failure_rolls_back(tmp_path: Path) -> None:
    journal = _journal(tmp_path)
    action = journal.mark_submitting(_prepare(journal).action_ref)

    with pytest.raises(EmergencyActionError, match="head changed"):
        journal.resolve_unknown_submission(
            action.action_ref,
            owner_user_id="alice",
            resolving_halt_ref="halt-1",
            resolving_owner_epoch=3,
            account_ref="exchange-account-1",
            account_epoch=7,
            operator_user_id="alice",
            operator_auth_audit_ref="mainnet_audit_v1_authorized",
            lookup_code=-2013,
            lookup_observed_at_utc=_observed_at(),
            flat_verification=_flat(),
            flat_observed_at_utc=_observed_at(),
            expected_action_event_ref="emergency_event_sha256_" + "0" * 64,
        )

    assert journal.action(action.action_ref).status == "submitting"
    with sqlite3.connect(journal.path) as conn:
        assert conn.execute(
            "SELECT COUNT(*) FROM emergency_unknown_submission_resolutions"
        ).fetchone()[0] == 0


def test_unknown_submission_exact_retry_must_match_persisted_resolution(
    tmp_path: Path,
) -> None:
    journal = _journal(tmp_path)
    action = journal.mark_submitting(_prepare(journal).action_ref)
    lookup_at = _observed_at()
    flat_at = _observed_at()
    journal.resolve_unknown_submission(
        action.action_ref,
        owner_user_id="alice",
        resolving_halt_ref="halt-1",
        resolving_owner_epoch=3,
        account_ref="exchange-account-1",
        account_epoch=7,
        operator_user_id="alice",
        operator_auth_audit_ref="mainnet_audit_v1_authorized",
        lookup_code=-2013,
        lookup_observed_at_utc=lookup_at,
        flat_verification=_flat(),
        flat_observed_at_utc=flat_at,
        expected_action_event_ref=action.last_event_ref,
    )

    with pytest.raises(EmergencyActionError, match="exact retry differs"):
        journal.resolve_unknown_submission(
            action.action_ref,
            owner_user_id="alice",
            resolving_halt_ref="different-halt",
            resolving_owner_epoch=999,
            account_ref="exchange-account-1",
            account_epoch=7,
            operator_user_id="alice",
            operator_auth_audit_ref="different-audit",
            lookup_code=-2013,
            lookup_observed_at_utc=_observed_at(),
            flat_verification=_flat(),
            flat_observed_at_utc=_observed_at(),
            expected_action_event_ref="emergency_event_sha256_" + "f" * 64,
        )


def test_unknown_submission_exact_retry_remains_idempotent_after_freshness_window(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    journal = _journal(tmp_path)
    action = journal.mark_submitting(_prepare(journal).action_ref)
    lookup_at = _observed_at()
    flat_at = _observed_at()
    common = {
        "owner_user_id": "alice",
        "resolving_halt_ref": "halt-1",
        "resolving_owner_epoch": 3,
        "account_ref": "exchange-account-1",
        "account_epoch": 7,
        "operator_user_id": "alice",
        "operator_auth_audit_ref": "mainnet_audit_v1_authorized",
        "lookup_code": -2013,
        "lookup_observed_at_utc": lookup_at,
        "flat_verification": _flat(),
        "flat_observed_at_utc": flat_at,
        "expected_action_event_ref": action.last_event_ref,
    }
    terminal, resolution = journal.resolve_unknown_submission(
        action.action_ref,
        **common,
    )
    real_datetime = emergency_journal_module.datetime

    class FutureDateTime(real_datetime):
        @classmethod
        def now(cls, tz=None):  # noqa: ANN001, ANN206
            return real_datetime.now(tz) + timedelta(minutes=10)

    monkeypatch.setattr(emergency_journal_module, "datetime", FutureDateTime)
    retried_action, retried_resolution = journal.resolve_unknown_submission(
        action.action_ref,
        **common,
    )

    assert retried_action == terminal
    assert retried_resolution == resolution


@pytest.mark.parametrize("mode", ("stale", "reverse", "future"))
def test_unknown_submission_rejects_nonfresh_or_reversed_evidence(
    tmp_path: Path,
    mode: str,
) -> None:
    journal = _journal(tmp_path)
    action = journal.mark_submitting(_prepare(journal).action_ref)
    now = datetime.now(UTC)
    lookup = now
    flat = now + timedelta(seconds=1)
    if mode == "stale":
        lookup = now - timedelta(minutes=10)
        flat = lookup + timedelta(seconds=1)
    elif mode == "reverse":
        flat = lookup - timedelta(seconds=1)
    else:
        lookup = now + timedelta(minutes=10)
        flat = lookup + timedelta(seconds=1)

    with pytest.raises(EmergencyActionError, match="stale|future-dated|predates"):
        journal.resolve_unknown_submission(
            action.action_ref,
            owner_user_id="alice",
            resolving_halt_ref="halt-1",
            resolving_owner_epoch=3,
            account_ref="exchange-account-1",
            account_epoch=7,
            operator_user_id="alice",
            operator_auth_audit_ref="mainnet_audit_v1_authorized",
            lookup_code=-2013,
            lookup_observed_at_utc=lookup.isoformat(),
            flat_verification=_flat(),
            flat_observed_at_utc=flat.isoformat(),
            expected_action_event_ref=action.last_event_ref,
        )


def test_manual_unknown_blocks_new_action_after_halt_scope_supersession(
    tmp_path: Path,
) -> None:
    journal = _journal(tmp_path)
    action = journal.mark_submitting(_prepare(journal).action_ref)
    journal.resolve_unknown_submission(
        action.action_ref,
        owner_user_id="alice",
        resolving_halt_ref="halt-2",
        resolving_owner_epoch=4,
        account_ref="exchange-account-1",
        account_epoch=7,
        operator_user_id="alice",
        operator_auth_audit_ref="mainnet_audit_v1_authorized",
        lookup_code=-2013,
        lookup_observed_at_utc=_observed_at(),
        flat_verification=_flat(),
        flat_observed_at_utc=_observed_at(),
        expected_action_event_ref=action.last_event_ref,
    )

    with pytest.raises(EmergencyActionError, match="prior HALT scope"):
        journal.prepare(
            owner_user_id="alice",
            halt_ref="halt-2",
            owner_epoch=4,
            account_ref="exchange-account-1",
            account_epoch=7,
            credential_binding_ref="credential-1",
            symbol="BTCUSDT",
            side="sell",
            quantity=0.25,
        )
    actions = journal.actions_for_account_epoch(
        owner_user_id="alice",
        account_ref="exchange-account-1",
        account_epoch=7,
    )
    assert len(actions) == 1
    assert actions[0].status == "manual_unknown_flat"


def test_unknown_submission_resolution_requires_exact_lookup_and_flat_proof(
    tmp_path: Path,
) -> None:
    journal = _journal(tmp_path)
    action = journal.mark_submitting(_prepare(journal).action_ref)
    common = {
        "owner_user_id": "alice",
        "resolving_halt_ref": "halt-1",
        "resolving_owner_epoch": 3,
        "account_ref": "exchange-account-1",
        "account_epoch": 7,
        "operator_user_id": "alice",
        "operator_auth_audit_ref": "mainnet_audit_v1_authorized",
        "lookup_observed_at_utc": _observed_at(),
        "flat_observed_at_utc": _observed_at(),
        "expected_action_event_ref": action.last_event_ref,
    }
    with pytest.raises(EmergencyActionError, match="exact lookup code -2013"):
        journal.resolve_unknown_submission(
            action.action_ref,
            lookup_code=-2011,
            flat_verification=_flat(),
            **common,
        )
    exposed = _flat()
    exposed["open_positions"] = [{"symbol": "BTCUSDT"}]
    with pytest.raises(EmergencyActionError, match="zero current venue exposure"):
        journal.resolve_unknown_submission(
            action.action_ref,
            lookup_code=-2013,
            flat_verification=exposed,
            **common,
        )


def test_unknown_submission_resolution_tamper_fails_replay(tmp_path: Path) -> None:
    journal = _journal(tmp_path)
    action = journal.mark_submitting(_prepare(journal).action_ref)
    journal.resolve_unknown_submission(
        action.action_ref,
        owner_user_id="alice",
        resolving_halt_ref="halt-1",
        resolving_owner_epoch=3,
        account_ref="exchange-account-1",
        account_epoch=7,
        operator_user_id="alice",
        operator_auth_audit_ref="mainnet_audit_v1_authorized",
        lookup_code=-2013,
        lookup_observed_at_utc=_observed_at(),
        flat_verification=_flat(),
        flat_observed_at_utc=_observed_at(),
        expected_action_event_ref=action.last_event_ref,
    )
    with sqlite3.connect(journal.path) as conn:
        conn.execute(
            "UPDATE emergency_unknown_submission_resolutions "
            "SET operator_auth_audit_ref='forged' WHERE action_ref=?",
            (action.action_ref,),
        )
        conn.commit()

    with pytest.raises(EmergencyActionError, match="resolution (identity|seal) is invalid"):
        journal.validate_replay()


def test_unknown_submission_resolution_insert_failure_rolls_back_whole_transaction(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    journal = _journal(tmp_path)
    action = journal.mark_submitting(_prepare(journal).action_ref)
    original_validator = journal._validated_resolution_row

    def fail_after_insert(conn, row, *, action=None):  # noqa: ANN001, ANN202
        raise EmergencyActionError("injected resolution validation failure")

    monkeypatch.setattr(journal, "_validated_resolution_row", fail_after_insert)
    with pytest.raises(EmergencyActionError, match="injected resolution"):
        journal.resolve_unknown_submission(
            action.action_ref,
            owner_user_id="alice",
            resolving_halt_ref="halt-1",
            resolving_owner_epoch=3,
            account_ref="exchange-account-1",
            account_epoch=7,
            operator_user_id="alice",
            operator_auth_audit_ref="mainnet_audit_v1_authorized",
            lookup_code=-2013,
            lookup_observed_at_utc=_observed_at(),
            flat_verification=_flat(),
            flat_observed_at_utc=_observed_at(),
            expected_action_event_ref=action.last_event_ref,
        )
    monkeypatch.setattr(journal, "_validated_resolution_row", original_validator)

    assert journal.action(action.action_ref) == action
    with sqlite3.connect(journal.path) as conn:
        assert conn.execute(
            "SELECT COUNT(*) FROM emergency_unknown_submission_resolutions"
        ).fetchone()[0] == 0
        assert conn.execute(
            "SELECT COUNT(*) FROM emergency_close_action_events WHERE action_ref=?",
            (action.action_ref,),
        ).fetchone()[0] == 2


def test_persisted_unknown_resolution_chronology_fails_before_v4_migration(
    tmp_path: Path,
) -> None:
    journal = _journal(tmp_path)
    action = journal.mark_submitting(_prepare(journal).action_ref)
    journal.resolve_unknown_submission(
        action.action_ref,
        owner_user_id="alice",
        resolving_halt_ref="halt-1",
        resolving_owner_epoch=3,
        account_ref="exchange-account-1",
        account_epoch=7,
        operator_user_id="alice",
        operator_auth_audit_ref="mainnet_audit_v1_authorized",
        lookup_code=-2013,
        lookup_observed_at_utc=_observed_at(),
        flat_verification=_flat(),
        flat_observed_at_utc=_observed_at(),
        expected_action_event_ref=action.last_event_ref,
    )
    with sqlite3.connect(journal.path) as conn:
        conn.execute(
            "UPDATE emergency_unknown_submission_resolutions "
            "SET lookup_observed_at_utc=? WHERE action_ref=?",
            ((datetime.now(UTC) + timedelta(days=1)).isoformat(), action.action_ref),
        )
        conn.execute("PRAGMA user_version=3")
        old_indexes = journal._index_ddls(
            if_not_exists=False,
            include_resolution=True,
            include_manual_unknown_flat=False,
        )
        for name in (
            "idx_emergency_one_active_symbol_action",
            "idx_emergency_one_active_account_epoch_symbol",
        ):
            conn.execute(f"DROP INDEX {name}")
            conn.execute(old_indexes[name])
        conn.commit()

    with pytest.raises(EmergencyActionError, match="chronology is invalid"):
        _journal(tmp_path)


def test_legacy_status_check_migrates_atomically_before_filled_residual(
    tmp_path: Path,
) -> None:
    journal = _journal(tmp_path)
    action = _prepare(journal)
    journal.mark_submitting(action.action_ref)
    mirror_before = journal.mirror_path.read_bytes()
    with sqlite3.connect(journal.path) as conn:
        seq_before = int(
            conn.execute("SELECT MAX(seq) FROM emergency_close_action_events").fetchone()[0]
        )
    _downgrade_action_table_to_legacy_check(journal)

    with sqlite3.connect(journal.path) as conn:
        legacy_sql = str(
            conn.execute(
                "SELECT sql FROM sqlite_master WHERE name='emergency_close_actions'"
            ).fetchone()[0]
        )
        assert "filled_residual" not in legacy_sql
        assert conn.execute("PRAGMA user_version").fetchone()[0] == 0

    reopened = _journal(tmp_path)
    assert reopened.action(action.action_ref).status == "submitting"
    assert reopened.mirror_path.read_bytes() == mirror_before
    with sqlite3.connect(reopened.path) as conn:
        current_sql = str(
            conn.execute(
                "SELECT sql FROM sqlite_master WHERE name='emergency_close_actions'"
            ).fetchone()[0]
        )
        assert "filled_residual" in current_sql
        assert conn.execute("PRAGMA user_version").fetchone()[0] == 4
        assert conn.execute(
            "SELECT 1 FROM sqlite_master "
            "WHERE type='table' AND name='emergency_unknown_submission_resolutions'"
        ).fetchone() is not None
        assert conn.execute("PRAGMA foreign_key_check").fetchall() == []
        assert {
            str(row[1])
            for row in conn.execute(
                "PRAGMA index_list(emergency_close_actions)"
            ).fetchall()
            if not str(row[1]).startswith("sqlite_autoindex")
        } == {
            "idx_emergency_actions_halt",
            "idx_emergency_one_active_symbol_action",
            "idx_emergency_one_active_account_epoch_symbol",
        }

    residual = reopened.mark_filled_residual(
        action.action_ref,
        venue_order_id="901",
        observation_ref="observation-residual",
        response_hash="sha256:" + "3" * 64,
        cumulative_filled_qty=0.25,
    )
    assert residual.status == "filled_residual"
    with sqlite3.connect(reopened.path) as conn:
        assert conn.execute("PRAGMA foreign_key_check").fetchall() == []
        assert int(
            conn.execute("SELECT MAX(seq) FROM emergency_close_action_events").fetchone()[0]
        ) == seq_before + 1

    idempotent = _journal(tmp_path)
    assert idempotent.action(action.action_ref).status == "filled_residual"
    with sqlite3.connect(idempotent.path) as conn:
        assert conn.execute(
            "SELECT 1 FROM sqlite_master "
            "WHERE name='emergency_close_actions__v2_new'"
        ).fetchone() is None


def test_v3_partial_indexes_migrate_to_v4_no_retry_constraints(
    tmp_path: Path,
) -> None:
    journal = _journal(tmp_path)
    action = _prepare(journal)
    _downgrade_indexes_to_v3(journal)
    with sqlite3.connect(journal.path) as conn:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == 3
        old_sql = str(
            conn.execute(
                "SELECT sql FROM sqlite_master "
                "WHERE name='idx_emergency_one_active_account_epoch_symbol'"
            ).fetchone()[0]
        )
        assert "manual_unknown_flat" not in old_sql

    reopened = _journal(tmp_path)
    assert reopened.action(action.action_ref) == action
    with sqlite3.connect(reopened.path) as conn:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == 4
        new_sql = str(
            conn.execute(
                "SELECT sql FROM sqlite_master "
                "WHERE name='idx_emergency_one_active_account_epoch_symbol'"
            ).fetchone()[0]
        )
        assert "manual_unknown_flat" in new_sql


def test_v2_action_schema_migrates_to_v4_with_resolution_table(
    tmp_path: Path,
) -> None:
    journal = _journal(tmp_path)
    action = journal.mark_submitting(_prepare(journal).action_ref)
    mirror_before = journal.mirror_path.read_bytes()
    _downgrade_action_table_to_v2(journal)

    with sqlite3.connect(journal.path) as conn:
        action_sql = str(
            conn.execute(
                "SELECT sql FROM sqlite_master WHERE name='emergency_close_actions'"
            ).fetchone()[0]
        )
        assert "filled_residual" in action_sql
        assert "manual_unknown_flat" not in action_sql
        assert conn.execute("PRAGMA user_version").fetchone()[0] == 2

    reopened = _journal(tmp_path)
    assert reopened.action(action.action_ref) == action
    assert reopened.mirror_path.read_bytes() == mirror_before
    with sqlite3.connect(reopened.path) as conn:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == 4
        assert conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' "
            "AND name='emergency_unknown_submission_resolutions'"
        ).fetchone() is not None
        assert conn.execute("PRAGMA foreign_key_check").fetchall() == []


def test_legacy_schema_tamper_is_rejected_before_any_migration(tmp_path: Path) -> None:
    journal = _journal(tmp_path)
    action = _prepare(journal)
    mirror_before = journal.mirror_path.read_bytes()
    _downgrade_action_table_to_legacy_check(journal)
    with sqlite3.connect(journal.path) as conn:
        conn.execute(
            "UPDATE emergency_close_actions SET integrity_seal=? WHERE action_ref=?",
            ("0" * 64, action.action_ref),
        )
        conn.commit()

    with pytest.raises(EmergencyActionError, match="failed integrity validation"):
        _journal(tmp_path)

    with sqlite3.connect(journal.path) as conn:
        sql = str(
            conn.execute(
                "SELECT sql FROM sqlite_master WHERE name='emergency_close_actions'"
            ).fetchone()[0]
        )
        assert "filled_residual" not in sql
        assert conn.execute("PRAGMA user_version").fetchone()[0] == 0
    assert journal.mirror_path.read_bytes() == mirror_before


def test_legacy_schema_migration_failure_rolls_back_ddl_and_version(
    monkeypatch,
    tmp_path: Path,
) -> None:
    journal = _journal(tmp_path)
    action = _prepare(journal)
    mirror_before = journal.mirror_path.read_bytes()
    _downgrade_action_table_to_legacy_check(journal)
    original = EmergencyActionJournal._validate_replay_conn
    calls = 0

    def fail_after_migrated_replay(self, conn):
        nonlocal calls
        calls += 1
        original(self, conn)
        if calls == 3:
            raise EmergencyActionError("injected pre-commit replay failure")

    monkeypatch.setattr(
        EmergencyActionJournal,
        "_validate_replay_conn",
        fail_after_migrated_replay,
    )
    with pytest.raises(EmergencyActionError, match="injected pre-commit"):
        _journal(tmp_path)

    with sqlite3.connect(journal.path) as conn:
        sql = str(
            conn.execute(
                "SELECT sql FROM sqlite_master WHERE name='emergency_close_actions'"
            ).fetchone()[0]
        )
        assert "filled_residual" not in sql
        assert conn.execute("PRAGMA user_version").fetchone()[0] == 0
        assert conn.execute(
            "SELECT 1 FROM sqlite_master "
            "WHERE name='emergency_close_actions__v2_new'"
        ).fetchone() is None
        assert conn.execute(
            "SELECT status FROM emergency_close_actions WHERE action_ref=?",
            (action.action_ref,),
        ).fetchone()[0] == "prepared"
    assert journal.mirror_path.read_bytes() == mirror_before


def test_reconciled_action_is_scope_and_response_hash_bound(tmp_path: Path):
    journal = _journal(tmp_path)
    action = _prepare(journal)
    submitting = journal.mark_submitting(action.action_ref)
    assert submitting.status == "submitting"
    acknowledged = journal.mark_acknowledged(
        action.action_ref,
        venue_order_id="123",
        response_hash="sha256:" + "a" * 64,
        cumulative_filled_qty=0.25,
        terminal_status="filled",
    )
    assert acknowledged.status == "acknowledged"
    reconciled = journal.mark_reconciled(
        action.action_ref,
        venue_order_id="123",
        observation_ref="observation-1",
        response_hash="sha256:" + "b" * 64,
        cumulative_filled_qty=0.25,
        terminal_status="filled",
        verified_flat=True,
    )
    assert reconciled.status == "reconciled"
    assert reconciled.verified_flat is True
    assert journal.validate_reconciled(
        action.action_ref,
        owner_user_id="alice",
        halt_ref="halt-1",
        owner_epoch=3,
        account_ref="exchange-account-1",
        account_epoch=7,
        response_hash="sha256:" + "b" * 64,
    ) == reconciled
    with pytest.raises(EmergencyActionError, match="different HALT scope"):
        journal.validate_reconciled(
            action.action_ref,
            owner_user_id="mallory",
            halt_ref="halt-1",
            owner_epoch=3,
            account_ref="exchange-account-1",
            account_epoch=7,
        )
    with pytest.raises(EmergencyActionError, match="response hash"):
        journal.validate_reconciled(
            action.action_ref,
            owner_user_id="alice",
            halt_ref="halt-1",
            owner_epoch=3,
            account_ref="exchange-account-1",
            account_epoch=7,
            response_hash="sha256:" + "c" * 64,
        )
    with pytest.raises(EmergencyActionError, match="cannot transition"):
        journal.mark_reconciled(
            action.action_ref,
            venue_order_id="forged-order",
            observation_ref="forged-observation",
            response_hash="sha256:" + "f" * 64,
            cumulative_filled_qty=0.25,
            terminal_status="filled",
            verified_flat=True,
        )
    assert journal.action(action.action_ref) == reconciled


def test_first_acknowledgement_identity_is_immutable_across_retries_and_observations(
    tmp_path: Path,
):
    journal = _journal(tmp_path)
    action = _prepare(journal)
    journal.mark_submitting(action.action_ref)
    first = journal.mark_acknowledged(
        action.action_ref,
        venue_order_id="123",
        response_hash="sha256:" + "a" * 64,
        cumulative_filled_qty=0.25,
        terminal_status="filled",
    )
    assert journal.mark_acknowledged(
        action.action_ref,
        venue_order_id="123",
        response_hash="sha256:" + "a" * 64,
        cumulative_filled_qty=0.25,
        terminal_status="filled",
    ) == first

    with pytest.raises(EmergencyActionError, match="cannot transition"):
        journal.mark_acknowledged(
            action.action_ref,
            venue_order_id="999",
            response_hash="sha256:" + "b" * 64,
            cumulative_filled_qty=0.25,
            terminal_status="filled",
        )
    with pytest.raises(EmergencyActionError, match="cannot transition"):
        journal.mark_acknowledged(
            action.action_ref,
            venue_order_id="123",
            response_hash="sha256:" + "c" * 64,
            cumulative_filled_qty=0.25,
            terminal_status="filled",
        )
    with pytest.raises(EmergencyActionError, match="venue_order_id cannot change"):
        journal.mark_reconciled(
            action.action_ref,
            venue_order_id="999",
            observation_ref="observation-forged",
            response_hash="sha256:" + "d" * 64,
            cumulative_filled_qty=0.25,
            terminal_status="filled",
            verified_flat=True,
        )
    assert journal.action(action.action_ref) == first


def test_scope_retry_with_changed_quantity_fails_closed(tmp_path: Path):
    journal = _journal(tmp_path)
    _prepare(journal)
    with pytest.raises(EmergencyActionError, match="different semantics"):
        journal.prepare(
            owner_user_id="alice",
            halt_ref="halt-1",
            owner_epoch=3,
            account_ref="exchange-account-1",
            account_epoch=7,
            credential_binding_ref="credential-1",
            symbol="BTCUSDT",
            side="sell",
            quantity=0.3,
        )


def test_submission_boundary_has_exactly_one_concurrent_winner(tmp_path: Path):
    journal = _journal(tmp_path)
    action = _prepare(journal)
    winners: list[str] = []
    errors: list[BaseException] = []
    barrier = threading.Barrier(2)

    def claim() -> None:
        try:
            barrier.wait(timeout=5)
            winners.append(journal.mark_submitting(action.action_ref).action_ref)
        except BaseException as exc:  # noqa: BLE001 - test captures the losing CAS.
            errors.append(exc)

    threads = [threading.Thread(target=claim) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=10)

    assert winners == [action.action_ref]
    assert len(errors) == 1
    assert isinstance(errors[0], EmergencyActionError)
    assert journal.action(action.action_ref).status == "submitting"


def test_terminal_zero_failure_advances_to_new_attempt_and_client_id(tmp_path: Path):
    journal = _journal(tmp_path)
    first = _prepare(journal)
    journal.mark_submitting(first.action_ref)
    failed = journal.mark_failed(
        first.action_ref,
        venue_order_id="12",
        observation_ref="observation-rejected",
        response_hash="sha256:" + "d" * 64,
        cumulative_filled_qty=0,
        terminal_status="rejected",
    )
    assert failed.status == "failed"
    second = journal.prepare(
        owner_user_id="alice",
        halt_ref="halt-1",
        owner_epoch=3,
        account_ref="exchange-account-1",
        account_epoch=7,
        credential_binding_ref="credential-1",
        symbol="BTCUSDT",
        side="sell",
        quantity=0.2,
    )
    assert second.attempt_no == 2
    assert second.action_ref != first.action_ref
    assert second.client_order_id != first.client_order_id


def test_terminal_partial_advances_only_fresh_residual_to_new_attempt(tmp_path: Path):
    journal = _journal(tmp_path)
    first = _prepare(journal)
    journal.mark_submitting(first.action_ref)
    partial = journal.mark_partial_terminal(
        first.action_ref,
        venue_order_id="13",
        observation_ref="observation-partial",
        response_hash="sha256:" + "e" * 64,
        cumulative_filled_qty=0.1,
        terminal_status="canceled",
    )
    assert partial.status == "terminal_partial"
    second = journal.prepare(
        owner_user_id="alice",
        halt_ref="halt-1",
        owner_epoch=3,
        account_ref="exchange-account-1",
        account_epoch=7,
        credential_binding_ref="credential-1",
        symbol="BTCUSDT",
        side="sell",
        quantity=0.15,
    )
    assert second.attempt_no == 2
    assert second.quantity_text == "0.15"
    assert second.client_order_id != first.client_order_id


def test_sqlite_or_mirror_tamper_and_missing_key_fail_closed(tmp_path: Path):
    journal = _journal(tmp_path)
    action = _prepare(journal)
    with sqlite3.connect(journal.path) as conn:
        conn.execute(
            "UPDATE emergency_close_actions SET quantity_text='9' WHERE action_ref=?",
            (action.action_ref,),
        )
    with pytest.raises(EmergencyActionError, match="identity|integrity"):
        journal.action(action.action_ref)

    clean_path = tmp_path / "clean"
    clean_path.mkdir()
    clean = _journal(clean_path)
    _prepare(clean)
    rows = clean.mirror_path.read_text().splitlines()
    payload = json.loads(rows[0])
    payload["event_kind"] = "forged"
    clean.mirror_path.write_text(json.dumps(payload) + "\n")
    with pytest.raises(EmergencyActionError, match="differs from SQLite"):
        clean.sync_mirror()

    clean.mirror_path.unlink()
    (clean_path / "emergency.hmac.key").unlink()
    with pytest.raises(EmergencyActionError, match="key is missing"):
        _journal(clean_path)


def test_same_process_historical_event_tamper_blocks_flat_proof_read(tmp_path: Path):
    journal = _journal(tmp_path)
    action = _prepare(journal)
    journal.mark_pre_submit_superseded(action.action_ref)
    with sqlite3.connect(journal.path) as conn:
        first_event = conn.execute(
            "SELECT event_ref FROM emergency_close_action_events "
            "WHERE action_ref=? ORDER BY seq LIMIT 1",
            (action.action_ref,),
        ).fetchone()[0]
        conn.execute(
            "UPDATE emergency_close_action_events SET event_kind='forged' "
            "WHERE event_ref=?",
            (first_event,),
        )

    with pytest.raises(EmergencyActionError, match="event identity is invalid"):
        journal.build_flat_proof_binding(
            owner_user_id="alice",
            halt_ref="halt-1",
            owner_epoch=3,
            account_ref="exchange-account-1",
            account_epoch=7,
            flat_verification={
                "ok": True,
                "normal_open_order_refs": [],
                "algo_open_order_refs": [],
                "open_positions": [],
            },
        )


def test_historical_sqlite_event_tamper_cannot_commit_later_transition(tmp_path: Path):
    journal = _journal(tmp_path)
    action = _prepare(journal)
    submitting = journal.mark_submitting(action.action_ref)
    with sqlite3.connect(journal.path) as conn:
        before_count = conn.execute(
            "SELECT COUNT(*) FROM emergency_close_action_events WHERE action_ref=?",
            (action.action_ref,),
        ).fetchone()[0]
        first_event = conn.execute(
            "SELECT event_ref FROM emergency_close_action_events "
            "WHERE action_ref=? ORDER BY seq LIMIT 1",
            (action.action_ref,),
        ).fetchone()[0]
        conn.execute(
            "UPDATE emergency_close_action_events SET event_kind='forged' "
            "WHERE event_ref=?",
            (first_event,),
        )

    with pytest.raises(EmergencyActionError, match="mirror event differs|event identity"):
        journal.mark_acknowledged(
            action.action_ref,
            venue_order_id="123",
            response_hash="sha256:" + "a" * 64,
            cumulative_filled_qty=0.25,
            terminal_status="filled",
        )
    with sqlite3.connect(journal.path) as conn:
        row = conn.execute(
            "SELECT status FROM emergency_close_actions WHERE action_ref=?",
            (action.action_ref,),
        ).fetchone()
        after_count = conn.execute(
            "SELECT COUNT(*) FROM emergency_close_action_events WHERE action_ref=?",
            (action.action_ref,),
        ).fetchone()[0]
    assert row[0] == submitting.status
    assert after_count == before_count


def test_sqlite_tamper_cannot_be_copied_into_missing_mirror_suffix(tmp_path: Path):
    journal = _journal(tmp_path)
    action = _prepare(journal)
    journal.mark_submitting(action.action_ref)
    mirror_rows = journal.mirror_path.read_text(encoding="utf-8").splitlines()
    assert len(mirror_rows) == 2
    journal.mirror_path.write_text(mirror_rows[0] + "\n", encoding="utf-8")
    with sqlite3.connect(journal.path) as conn:
        second_event = conn.execute(
            "SELECT event_ref FROM emergency_close_action_events "
            "WHERE action_ref=? ORDER BY seq DESC LIMIT 1",
            (action.action_ref,),
        ).fetchone()[0]
        conn.execute(
            "UPDATE emergency_close_action_events SET event_kind='forged' "
            "WHERE event_ref=?",
            (second_event,),
        )

    with pytest.raises(EmergencyActionError, match="event identity"):
        journal.sync_mirror()
    assert journal.mirror_path.read_text(encoding="utf-8").splitlines() == [
        mirror_rows[0]
    ]


def test_mirror_tamper_cannot_commit_later_transition(tmp_path: Path):
    journal = _journal(tmp_path)
    action = _prepare(journal)
    rows = journal.mirror_path.read_text(encoding="utf-8").splitlines()
    forged = json.loads(rows[0])
    forged["event_kind"] = "forged"
    journal.mirror_path.write_text(json.dumps(forged) + "\n", encoding="utf-8")

    with pytest.raises(EmergencyActionError, match="differs from SQLite"):
        journal.mark_submitting(action.action_ref)
    with sqlite3.connect(journal.path) as conn:
        status = conn.execute(
            "SELECT status FROM emergency_close_actions WHERE action_ref=?",
            (action.action_ref,),
        ).fetchone()[0]
        event_count = conn.execute(
            "SELECT COUNT(*) FROM emergency_close_action_events WHERE action_ref=?",
            (action.action_ref,),
        ).fetchone()[0]
    assert status == "prepared"
    assert event_count == 1


@pytest.mark.parametrize("tamper", ["reordered", "duplicated"])
def test_mirror_sequence_tamper_cannot_commit_later_transition(
    tmp_path: Path,
    tamper: str,
):
    journal = _journal(tmp_path)
    action = _prepare(journal)
    submitting = journal.mark_submitting(action.action_ref)
    rows = journal.mirror_path.read_text(encoding="utf-8").splitlines()
    assert len(rows) == 2
    if tamper == "reordered":
        tampered_rows = list(reversed(rows))
    else:
        tampered_rows = [rows[0], rows[0], rows[1]]
    journal.mirror_path.write_text("\n".join(tampered_rows) + "\n", encoding="utf-8")

    with pytest.raises(
        EmergencyActionError,
        match="ordered SQLite prefix|more events than SQLite",
    ):
        journal.mark_acknowledged(
            action.action_ref,
            venue_order_id="123",
            response_hash="sha256:" + "a" * 64,
            cumulative_filled_qty=0.25,
            terminal_status="filled",
        )
    with sqlite3.connect(journal.path) as conn:
        status = conn.execute(
            "SELECT status FROM emergency_close_actions WHERE action_ref=?",
            (action.action_ref,),
        ).fetchone()[0]
        event_count = conn.execute(
            "SELECT COUNT(*) FROM emergency_close_action_events WHERE action_ref=?",
            (action.action_ref,),
        ).fetchone()[0]
    assert status == submitting.status
    assert event_count == 2


def test_torn_final_mirror_append_is_rebuilt_from_sqlite(tmp_path: Path):
    journal = _journal(tmp_path)
    action = _prepare(journal)
    with journal.mirror_path.open("ab") as mirror:
        mirror.write(b'{"partial_event":')
        mirror.flush()
    reopened = _journal(tmp_path)
    assert reopened.action(action.action_ref) == action
    rows = [json.loads(line) for line in reopened.mirror_path.read_text().splitlines()]
    assert [row["event_ref"] for row in rows] == [action.last_event_ref]


def test_account_halt_flat_proof_requires_exact_journal_binding(tmp_path: Path):
    journal = _journal(tmp_path)
    barrier = PersistentAccountHaltBarrier(tmp_path / "halt.sqlite3")
    journal.bind_account_halt_barrier(barrier)
    barrier.bind_emergency_action_journal(journal)
    barrier.activate("exchange-account-1", "alice")
    snapshot = barrier.begin_account_halt(
        "exchange-account-1",
        "alice",
        halt_ref="halt-bound",
        action_name="copy_trade_unsubscribe",
        close_positions=True,
    )
    owner_epoch = barrier.owner_epoch("alice")
    action = journal.prepare(
        owner_user_id="alice",
        halt_ref="halt-bound",
        owner_epoch=owner_epoch,
        account_ref="exchange-account-1",
        account_epoch=snapshot.epoch,
        credential_binding_ref="credential-1",
        symbol="BTCUSDT",
        side="sell",
        quantity=0.25,
    )
    journal.mark_submitting(action.action_ref)
    journal.mark_acknowledged(
        action.action_ref,
        venue_order_id="901",
        response_hash="sha256:" + "1" * 64,
        cumulative_filled_qty=0.25,
        terminal_status="filled",
    )
    journal.mark_reconciled(
        action.action_ref,
        venue_order_id="901",
        observation_ref="observation-901",
        response_hash="sha256:" + "2" * 64,
        cumulative_filled_qty=0.25,
        terminal_status="filled",
        verified_flat=True,
    )
    flat = {
        "ok": True,
        "normal_open_order_refs": [],
        "algo_open_order_refs": [],
        "open_positions": [],
    }
    binding = journal.build_flat_proof_binding(
        owner_user_id="alice",
        halt_ref="halt-bound",
        owner_epoch=owner_epoch,
        account_ref="exchange-account-1",
        account_epoch=snapshot.epoch,
        flat_verification=flat,
    )
    with pytest.raises(AccountHaltError, match="binding failed validation"):
        barrier.record_flat_proof(
            "alice",
            halt_ref="halt-bound",
            close_positions=True,
            account_epochs={"exchange-account-1": snapshot.epoch},
            results={"exchange-account-1": flat},
        )
    forged = {**binding, "actions": [{**binding["actions"][0], "attempt_no": 999}]}
    with pytest.raises(AccountHaltError, match="binding failed validation"):
        barrier.record_flat_proof(
            "alice",
            halt_ref="halt-bound",
            close_positions=True,
            account_epochs={"exchange-account-1": snapshot.epoch},
            results={
                "exchange-account-1": {
                    **flat,
                    "emergency_action_binding": forged,
                }
            },
        )
    proof_ref = barrier.record_flat_proof(
        "alice",
        halt_ref="halt-bound",
        close_positions=True,
        account_epochs={"exchange-account-1": snapshot.epoch},
        results={
            "exchange-account-1": {
                **flat,
                "emergency_action_binding": binding,
            }
        },
    )
    finalized = barrier.finalize_account_halt(
        "exchange-account-1",
        "alice",
        expected_epoch=snapshot.epoch,
        flat_proof_ref=proof_ref,
    )
    assert finalized.state == "halted"


def test_account_finalize_fences_concurrent_stale_journal_prepare(
    monkeypatch,
    tmp_path: Path,
) -> None:
    journal = _journal(tmp_path)
    barrier = PersistentAccountHaltBarrier(tmp_path / "halt.sqlite3")
    journal.bind_account_halt_barrier(barrier)
    barrier.bind_emergency_action_journal(journal)
    barrier.activate("exchange-account-1", "alice")
    snapshot = barrier.begin_account_halt(
        "exchange-account-1",
        "alice",
        halt_ref="finalize-race",
        action_name="copy_trade_unsubscribe",
        close_positions=True,
    )
    owner_epoch = barrier.owner_epoch("alice")
    flat = {
        "ok": True,
        "normal_open_order_refs": [],
        "algo_open_order_refs": [],
        "open_positions": [],
    }
    binding = journal.build_flat_proof_binding(
        owner_user_id="alice",
        halt_ref="finalize-race",
        owner_epoch=owner_epoch,
        account_ref="exchange-account-1",
        account_epoch=snapshot.epoch,
        flat_verification=flat,
    )
    proof_ref = barrier.record_flat_proof(
        "alice",
        halt_ref="finalize-race",
        close_positions=True,
        account_epochs={"exchange-account-1": snapshot.epoch},
        results={
            "exchange-account-1": {
                **flat,
                "emergency_action_binding": binding,
            }
        },
    )

    action_entered_fence = threading.Event()
    outcomes: list[BaseException | None] = []
    workers: list[threading.Thread] = []
    original_fence = barrier.emergency_action_fence
    original_require = barrier._require_flat_proof

    @contextmanager
    def observed_fence(**kwargs):
        action_entered_fence.set()
        with original_fence(**kwargs):
            yield

    def concurrent_prepare() -> None:
        try:
            journal.prepare(
                owner_user_id="alice",
                halt_ref="finalize-race",
                owner_epoch=owner_epoch,
                account_ref="exchange-account-1",
                account_epoch=snapshot.epoch,
                credential_binding_ref="credential-1",
                symbol="BTCUSDT",
                side="sell",
                quantity=0.25,
            )
        except BaseException as exc:  # noqa: BLE001 - thread assertion handoff.
            outcomes.append(exc)
        else:
            outcomes.append(None)

    def require_with_concurrent_prepare(conn, ref, **kwargs):
        worker = threading.Thread(target=concurrent_prepare)
        workers.append(worker)
        worker.start()
        assert action_entered_fence.wait(timeout=5)
        return original_require(conn, ref, **kwargs)

    monkeypatch.setattr(barrier, "emergency_action_fence", observed_fence)
    monkeypatch.setattr(barrier, "_require_flat_proof", require_with_concurrent_prepare)

    finalized = barrier.finalize_account_halt(
        "exchange-account-1",
        "alice",
        expected_epoch=snapshot.epoch,
        flat_proof_ref=proof_ref,
    )
    workers[0].join(timeout=5)

    assert finalized.state == "halted"
    assert not workers[0].is_alive()
    assert len(outcomes) == 1
    assert isinstance(outcomes[0], PermissionError)
    assert "HALT account scope changed" in str(outcomes[0])
    assert journal.actions_for_account_epoch(
        owner_user_id="alice",
        account_ref="exchange-account-1",
        account_epoch=snapshot.epoch,
    ) == ()
    assert barrier.flat_proof(proof_ref)["flat_proof_ref"] == proof_ref


def test_multi_account_finalize_fences_concurrent_stale_journal_prepare(
    monkeypatch,
    tmp_path: Path,
) -> None:
    journal = _journal(tmp_path)
    barrier = PersistentAccountHaltBarrier(tmp_path / "halt.sqlite3")
    journal.bind_account_halt_barrier(barrier)
    barrier.bind_emergency_action_journal(journal)
    account_refs = ("exchange-account-1", "exchange-account-2")
    for account_ref in account_refs:
        barrier.activate(account_ref, "alice")
    snapshots = barrier.begin_halt_many(
        "alice",
        list(account_refs),
        halt_ref="global-finalize-race",
        action_name="emergency_close_all",
        close_positions=True,
    )
    owner_epoch = barrier.owner_epoch("alice")
    flat = {
        "ok": True,
        "normal_open_order_refs": [],
        "algo_open_order_refs": [],
        "open_positions": [],
    }
    results = {}
    for account_ref in account_refs:
        binding = journal.build_flat_proof_binding(
            owner_user_id="alice",
            halt_ref="global-finalize-race",
            owner_epoch=owner_epoch,
            account_ref=account_ref,
            account_epoch=snapshots[account_ref].epoch,
            flat_verification=flat,
        )
        results[account_ref] = {
            **flat,
            "emergency_action_binding": binding,
        }
    proof_ref = barrier.record_flat_proof(
        "alice",
        halt_ref="global-finalize-race",
        close_positions=True,
        account_epochs={
            account_ref: snapshots[account_ref].epoch
            for account_ref in account_refs
        },
        results=results,
    )

    action_entered_fence = threading.Event()
    outcomes: list[BaseException | None] = []
    workers: list[threading.Thread] = []
    original_fence = barrier.emergency_action_fence
    original_require = barrier._require_flat_proof

    @contextmanager
    def observed_fence(**kwargs):
        action_entered_fence.set()
        with original_fence(**kwargs):
            yield

    def concurrent_prepare() -> None:
        account_ref = account_refs[-1]
        try:
            journal.prepare(
                owner_user_id="alice",
                halt_ref="global-finalize-race",
                owner_epoch=owner_epoch,
                account_ref=account_ref,
                account_epoch=snapshots[account_ref].epoch,
                credential_binding_ref="credential-2",
                symbol="ETHUSDT",
                side="sell",
                quantity=0.5,
            )
        except BaseException as exc:  # noqa: BLE001 - thread assertion handoff.
            outcomes.append(exc)
        else:
            outcomes.append(None)

    def require_with_concurrent_prepare(conn, ref, **kwargs):
        worker = threading.Thread(target=concurrent_prepare)
        workers.append(worker)
        worker.start()
        assert action_entered_fence.wait(timeout=5)
        return original_require(conn, ref, **kwargs)

    monkeypatch.setattr(barrier, "emergency_action_fence", observed_fence)
    monkeypatch.setattr(barrier, "_require_flat_proof", require_with_concurrent_prepare)

    finalized = barrier.finalize_halt_many(
        "alice",
        {
            account_ref: snapshots[account_ref].epoch
            for account_ref in account_refs
        },
        flat_proof_ref=proof_ref,
    )
    workers[0].join(timeout=5)

    assert {snapshot.state for snapshot in finalized.values()} == {"halted"}
    assert not workers[0].is_alive()
    assert len(outcomes) == 1
    assert isinstance(outcomes[0], PermissionError)
    assert "HALT account scope changed" in str(outcomes[0])
    for account_ref in account_refs:
        assert journal.actions_for_account_epoch(
            owner_user_id="alice",
            account_ref=account_ref,
            account_epoch=snapshots[account_ref].epoch,
        ) == ()
