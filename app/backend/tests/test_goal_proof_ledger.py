from __future__ import annotations

import hashlib
import json
import multiprocessing
import os
import sqlite3
import threading
import time
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor
from pathlib import Path

import pytest

from app.lineage.ids import canonical_json
from app.research_os.goal_proof_ledger import (
    GENESIS_HASH,
    GoalProofConflictError,
    GoalProofDependencyError,
    GoalProofLedger,
    GoalProofLedgerIntegrityError,
    GoalProofMirrorPendingError,
    InvalidationTarget,
    ProofBundle,
    ProofMember,
)


def _bundle(
    *,
    owner: str = "alice",
    subject: str = "goal:quantbt",
    a_value: int = 1,
    b_value: int = 2,
) -> ProofBundle:
    return ProofBundle(
        owner=owner,
        subject=subject,
        members=(
            ProofMember(
                logical_type="coverage",
                logical_ref="coverage:a",
                payload={"value": a_value},
            ),
            ProofMember(
                logical_type="receipt",
                logical_ref="receipt:b",
                payload={"value": b_value},
                depends_on=("coverage:a",),
            ),
        ),
        metadata={"source": "test"},
    )


def _counts(ledger: GoalProofLedger) -> dict[str, int]:
    tables = (
        "goal_proof_bundles",
        "goal_proof_events",
        "goal_proof_declarations",
        "goal_proof_dependency_edges",
        "goal_proof_current_heads",
        "goal_proof_invalidation_bundles",
        "goal_proof_invalidations",
    )
    with sqlite3.connect(ledger.db_path) as connection:
        return {
            table: int(connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
            for table in tables
        }


def _target(result, logical_ref: str) -> InvalidationTarget:
    head = next(head for head in result.heads if head.logical_ref == logical_ref)
    return InvalidationTarget.from_head(head)


def _fresh_root_process_commit(root: str, barrier_root: str) -> str:
    barrier = Path(barrier_root)
    (barrier / f"ready-{os.getpid()}").write_text("ready", encoding="utf-8")
    deadline = time.monotonic() + 30.0
    while not (barrier / "go").exists():
        if time.monotonic() >= deadline:
            return "TimeoutError:fresh-root process barrier timed out"
        time.sleep(0.01)
    try:
        ledger = GoalProofLedger(root)
        return ledger.commit(_bundle()).status
    except Exception as exc:  # pragma: no cover - returned for exact parent assertion.
        return f"{type(exc).__name__}:{exc}"


def test_sqlite_source_of_truth_enforces_wal_full_and_foreign_keys(tmp_path):
    ledger = GoalProofLedger(tmp_path / "ledger")

    assert ledger.journal_mode() == "wal"
    connection = ledger._connect()
    try:
        assert connection.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
        assert connection.execute("PRAGMA synchronous").fetchone()[0] == 2
        assert connection.execute("PRAGMA foreign_keys").fetchone()[0] == 1
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
    finally:
        connection.close()


def test_exact_commit_is_atomic_current_and_idempotent(tmp_path):
    ledger = GoalProofLedger(tmp_path / "ledger")
    bundle = _bundle()

    committed = ledger.commit(bundle)
    retried = ledger.commit(bundle)
    snapshot = ledger.current(owner="alice", subject="goal:quantbt")

    assert committed.status == "committed"
    assert retried.status == "idempotent"
    assert retried.bundle_id == committed.bundle_id
    assert tuple(head.logical_ref for head in snapshot.heads) == (
        "coverage:a",
        "receipt:b",
    )
    assert tuple(head.generation for head in snapshot.heads) == (1, 1)
    assert snapshot.heads[1].depends_on == ("coverage:a",)
    assert snapshot.heads[1].dependency_event_ids == (
        snapshot.heads[0].declaration_event_id,
    )
    assert snapshot.mirror_synced is True
    counts = _counts(ledger)
    assert counts["goal_proof_bundles"] == 1
    assert counts["goal_proof_events"] == 2
    assert counts["goal_proof_declarations"] == 2
    assert counts["goal_proof_dependency_edges"] == 1
    assert counts["goal_proof_current_heads"] == 2
    assert ledger.verify().ok is True


def test_repeated_current_uses_verified_state_cache_and_returns_defensive_payloads(
    tmp_path,
    monkeypatch,
):
    ledger = GoalProofLedger(tmp_path / "ledger")
    ledger.commit(_bundle())
    first = ledger.current(owner="alice")
    first.heads[0].payload["value"] = 999

    verify_calls = 0
    original_verify_sqlite = ledger._verify_sqlite

    def counted_verify_sqlite(connection):
        nonlocal verify_calls
        verify_calls += 1
        return original_verify_sqlite(connection)

    monkeypatch.setattr(ledger, "_verify_sqlite", counted_verify_sqlite)
    snapshots = [ledger.current(owner="alice") for _index in range(25)]

    assert verify_calls == 0
    assert all(snapshot.heads[0].payload["value"] == 1 for snapshot in snapshots)


def test_empty_wal_inode_churn_does_not_change_current_state_token(
    tmp_path,
    monkeypatch,
):
    ledger = GoalProofLedger(tmp_path / "ledger")
    ledger.commit(_bundle())
    real_file_state = ledger._file_state
    empty_wal_inode = 100

    def file_state_with_empty_wal_inode_churn(path):
        nonlocal empty_wal_inode
        if str(path).endswith("-wal"):
            empty_wal_inode += 1
            return (1, empty_wal_inode, 0, empty_wal_inode, empty_wal_inode)
        return real_file_state(path)

    monkeypatch.setattr(ledger, "_file_state", file_state_with_empty_wal_inode_churn)

    first = ledger._current_state_token_unlocked()
    second = ledger._current_state_token_unlocked()

    assert first is not None
    assert first == second


def test_current_cache_invalidates_after_external_ledger_commit(tmp_path):
    root = tmp_path / "ledger"
    reader = GoalProofLedger(root)
    reader.commit(_bundle())
    cached = reader.current(owner="alice")
    assert tuple(head.logical_ref for head in cached.heads) == (
        "coverage:a",
        "receipt:b",
    )

    writer = GoalProofLedger(root)
    writer.commit(
        ProofBundle(
            owner="alice",
            subject="goal:quantbt",
            members=(ProofMember("aggregate", "aggregate:c", {"value": 3}),),
        )
    )

    refreshed = reader.current(owner="alice")
    assert tuple(head.logical_ref for head in refreshed.heads) == (
        "aggregate:c",
        "coverage:a",
        "receipt:b",
    )


def test_current_cache_invalidates_after_same_instance_sqlite_tamper(tmp_path):
    ledger = GoalProofLedger(tmp_path / "ledger")
    ledger.commit(_bundle())
    ledger.current(owner="alice")
    with sqlite3.connect(ledger.db_path) as connection:
        connection.execute(
            "UPDATE goal_proof_current_heads SET owner='mallory' "
            "WHERE logical_ref='coverage:a'"
        )
        connection.commit()

    with pytest.raises(GoalProofLedgerIntegrityError, match="current head.*owner"):
        ledger.current(owner="alice")


def test_current_cache_invalidates_after_same_instance_mirror_tamper(tmp_path):
    ledger = GoalProofLedger(tmp_path / "ledger")
    ledger.commit(_bundle())
    ledger.current(owner="alice")
    rows = [
        json.loads(line)
        for line in ledger.mirror_path.read_text(encoding="utf-8").splitlines()
    ]
    rows[0]["owner"] = "malic"
    ledger.mirror_path.write_text(
        "".join(canonical_json(row) + "\n" for row in rows),
        encoding="utf-8",
    )

    with pytest.raises(GoalProofLedgerIntegrityError, match="diverges from SQLite"):
        ledger.current(owner="alice")


def test_current_does_not_cache_recombined_post_verification_file_state(
    tmp_path,
    monkeypatch,
):
    ledger = GoalProofLedger(tmp_path / "ledger")
    ledger.commit(_bundle())
    verified = False
    tampered = False
    original_verify_sqlite = ledger._verify_sqlite
    original_logical_token = ledger._current_logical_state_token

    def observed_verify_sqlite(connection):
        nonlocal verified
        result = original_verify_sqlite(connection)
        verified = True
        return result

    def tamper_after_verified_logical_sample(connection):
        nonlocal tampered
        token = original_logical_token(connection)
        if verified and not tampered:
            with sqlite3.connect(ledger.db_path) as writer:
                writer.execute(
                    "UPDATE goal_proof_events SET payload_hash=? WHERE seq=1",
                    ("0" * 64,),
                )
                writer.commit()
            tampered = True
        return token

    monkeypatch.setattr(ledger, "_verify_sqlite", observed_verify_sqlite)
    monkeypatch.setattr(
        ledger,
        "_current_logical_state_token",
        tamper_after_verified_logical_sample,
    )

    first = ledger.current(owner="alice")
    assert first.heads[0].payload["value"] == 1
    assert tampered is True
    with pytest.raises(GoalProofLedgerIntegrityError, match="payload hash mismatch"):
        ledger.current(owner="alice")


def test_commit_refuses_payload_collision_and_unknown_dependency_without_rows(tmp_path):
    ledger = GoalProofLedger(tmp_path / "ledger")
    unknown = ProofBundle(
        owner="alice",
        subject="goal:quantbt",
        members=(
            ProofMember(
                logical_type="receipt",
                logical_ref="receipt:orphan",
                payload={"value": 1},
                depends_on=("coverage:missing",),
            ),
        ),
    )

    with pytest.raises(GoalProofDependencyError, match="not current"):
        ledger.commit(unknown)
    assert _counts(ledger)["goal_proof_events"] == 0

    ledger.commit(_bundle())
    with pytest.raises(GoalProofConflictError, match="different payload, bundle, or event"):
        ledger.commit(_bundle(a_value=99))
    assert _counts(ledger)["goal_proof_events"] == 2


def test_precommit_failure_rolls_back_bundle_members_heads_and_outbox(tmp_path):
    def fail(cutpoint: str) -> None:
        if cutpoint == "before_sqlite_commit":
            raise RuntimeError("injected before commit")

    ledger = GoalProofLedger(tmp_path / "ledger", fault_injector=fail)

    with pytest.raises(RuntimeError, match="injected before commit"):
        ledger.commit(_bundle())

    counts = _counts(ledger)
    assert counts["goal_proof_bundles"] == 0
    assert counts["goal_proof_events"] == 0
    assert counts["goal_proof_declarations"] == 0
    assert counts["goal_proof_current_heads"] == 0
    assert not ledger.mirror_path.exists()


def test_invalidation_is_exact_bundle_generation_and_redeclare_is_generation_two(
    tmp_path,
):
    ledger = GoalProofLedger(tmp_path / "ledger")
    first = ledger.commit(_bundle())

    invalidated = ledger.invalidate(
        owner="alice",
        operation_id="invalidate-receipt-generation-1",
        targets=(_target(first, "receipt:b"),),
        reason="receipt superseded",
        subject="goal:quantbt",
    )

    assert invalidated.affected_refs == ("coverage:a", "receipt:b")
    assert set(invalidated.target_declaration_event_ids) == {
        head.declaration_event_id for head in first.heads
    }
    assert ledger.current(owner="alice").heads == ()
    after_invalidation = _counts(ledger)
    assert after_invalidation["goal_proof_declarations"] == 2
    assert after_invalidation["goal_proof_events"] == 4
    assert after_invalidation["goal_proof_current_heads"] == 0

    second = ledger.commit(_bundle(a_value=3, b_value=4))
    assert tuple(head.generation for head in second.heads) == (2, 2)
    assert not {
        head.declaration_event_id for head in first.heads
    }.intersection(head.declaration_event_id for head in second.heads)
    final_counts = _counts(ledger)
    assert final_counts["goal_proof_declarations"] == 4
    assert final_counts["goal_proof_invalidations"] == 2
    assert final_counts["goal_proof_events"] == 6
    assert ledger.verify().ok is True


def test_invalidation_refuses_server_derived_external_inbound_dependency(tmp_path):
    ledger = GoalProofLedger(tmp_path / "ledger")
    base = ledger.commit(_bundle())
    ledger.commit(
        ProofBundle(
            owner="alice",
            subject="goal:quantbt",
            members=(
                ProofMember(
                    logical_type="aggregate",
                    logical_ref="aggregate:c",
                    payload={"value": 3},
                    depends_on=("receipt:b",),
                ),
            ),
        )
    )

    with pytest.raises(GoalProofDependencyError, match="external dependents.*aggregate:c"):
        ledger.invalidate(
            owner="alice",
            operation_id="invalidate-base-with-inbound",
            targets=(_target(base, "coverage:a"),),
            reason="base invalid",
        )

    assert tuple(head.logical_ref for head in ledger.current(owner="alice").heads) == (
        "aggregate:c",
        "coverage:a",
        "receipt:b",
    )
    assert _counts(ledger)["goal_proof_invalidations"] == 0


def test_invalidation_retry_binds_subject(tmp_path):
    ledger = GoalProofLedger(tmp_path / "ledger")
    committed = ledger.commit(_bundle())
    target = _target(committed, "coverage:a")
    first = ledger.invalidate(
        owner="alice",
        operation_id="invalidate-exact-bundle",
        targets=(target,),
        reason="invalidate exact bundle",
        subject="goal:quantbt",
    )

    retried = ledger.invalidate(
        owner="alice",
        operation_id="invalidate-exact-bundle",
        targets=(target,),
        reason="invalidate exact bundle",
        subject="goal:quantbt",
    )
    assert retried.status == "idempotent"
    assert retried.invalidation_bundle_id == first.invalidation_bundle_id

    with pytest.raises(GoalProofConflictError, match="operation identity"):
        ledger.invalidate(
            owner="alice",
            operation_id="invalidate-exact-bundle",
            targets=(target,),
            reason="invalidate exact bundle",
            subject="goal:wrong",
        )


def test_hash_chained_mirror_is_append_only_and_matches_same_transaction_outbox(
    tmp_path,
):
    ledger = GoalProofLedger(tmp_path / "ledger")
    ledger.commit(_bundle())
    prefix = ledger.mirror_path.read_bytes()
    ledger.commit(
        ProofBundle(
            owner="bob",
            subject="goal:other",
            members=(ProofMember("coverage", "coverage:bob", {"value": 1}),),
        )
    )
    raw = ledger.mirror_path.read_bytes()

    assert raw.startswith(prefix)
    rows = [json.loads(line) for line in raw.decode("utf-8").splitlines()]
    previous = GENESIS_HASH
    for expected_seq, row in enumerate(rows, start=1):
        assert row["seq"] == expected_seq
        assert row["prev_hash"] == previous
        row_without_hash = dict(row)
        observed_hash = row_without_hash.pop("row_hash")
        expected_hash = hashlib.sha256(
            canonical_json(row_without_hash).encode("utf-8")
        ).hexdigest()
        assert observed_hash == expected_hash
        previous = observed_hash
    with sqlite3.connect(ledger.db_path) as connection:
        connection.row_factory = sqlite3.Row
        events = connection.execute(
            "SELECT seq,event_id,payload_hash,mirrored FROM goal_proof_events ORDER BY seq"
        ).fetchall()
    assert len(events) == len(rows)
    assert all(int(event["mirrored"]) == 1 for event in events)
    assert [str(event["event_id"]) for event in events] == [
        row["event_id"] for row in rows
    ]


def test_committed_but_mirror_pending_is_explicit_and_sync_repairs(tmp_path):
    armed = {"value": True}

    def fail(cutpoint: str) -> None:
        if armed["value"] and cutpoint == "after_sqlite_commit":
            armed["value"] = False
            raise RuntimeError("injected committed crash")

    ledger = GoalProofLedger(tmp_path / "ledger", fault_injector=fail)

    with pytest.raises(GoalProofMirrorPendingError, match="committed in SQLite") as caught:
        ledger.commit(_bundle())

    assert caught.value.operation == "commit"
    assert caught.value.result.mirror_pending is True
    assert _counts(ledger)["goal_proof_events"] == 2
    with sqlite3.connect(ledger.db_path) as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM goal_proof_events WHERE mirrored=0"
        ).fetchone()[0] == 2

    repaired = ledger.sync()
    assert repaired.appended == 2
    assert repaired.sqlite_event_count == repaired.mirror_event_count == 2
    assert ledger.verify().ok is True


def test_partial_mirror_crash_tail_is_repaired_only_from_exact_sqlite_event(tmp_path):
    armed = {"value": True}

    def fail(cutpoint: str) -> None:
        if armed["value"] and cutpoint == "mirror_after_partial_write":
            armed["value"] = False
            raise RuntimeError("injected partial mirror write")

    ledger = GoalProofLedger(tmp_path / "ledger", fault_injector=fail)

    with pytest.raises(GoalProofMirrorPendingError, match="mirror is pending"):
        ledger.commit(_bundle())
    assert ledger.mirror_path.read_bytes()
    assert not ledger.mirror_path.read_bytes().endswith(b"\n")

    repaired = ledger.sync()
    assert repaired.repaired_partial_tail is True
    assert repaired.appended == 2
    assert ledger.mirror_path.read_bytes().endswith(b"\n")
    assert ledger.verify().ok is True


def test_truncation_after_mirrored_event_fails_closed(tmp_path):
    root = tmp_path / "ledger"
    ledger = GoalProofLedger(root)
    ledger.commit(_bundle())
    raw = ledger.mirror_path.read_bytes()
    ledger.mirror_path.write_bytes(raw[:-7])

    with pytest.raises(
        GoalProofLedgerIntegrityError, match="truncated after a mirrored event"
    ):
        GoalProofLedger(root)


@pytest.mark.parametrize("mutation", ("divergent", "ahead"))
def test_divergent_or_ahead_mirror_fails_closed(tmp_path, mutation):
    root = tmp_path / "ledger"
    ledger = GoalProofLedger(root)
    ledger.commit(_bundle())
    if mutation == "divergent":
        rows = [
            json.loads(line)
            for line in ledger.mirror_path.read_text(encoding="utf-8").splitlines()
        ]
        rows[0]["owner"] = "mallory"
        ledger.mirror_path.write_text(
            "".join(canonical_json(row) + "\n" for row in rows),
            encoding="utf-8",
        )
        expected = "diverges from SQLite"
    else:
        with ledger.mirror_path.open("a", encoding="utf-8") as handle:
            handle.write(canonical_json({"uncommitted": True}) + "\n")
        expected = "ahead of SQLite"

    with pytest.raises(GoalProofLedgerIntegrityError, match=expected):
        GoalProofLedger(root)


def test_event_payload_or_identity_mismatch_is_refused_before_mirror_extension(
    tmp_path,
):
    ledger = GoalProofLedger(tmp_path / "ledger")
    ledger.commit(_bundle())
    mirror_before = ledger.mirror_path.read_bytes()
    with sqlite3.connect(ledger.db_path) as connection:
        connection.execute(
            "UPDATE goal_proof_events SET payload_hash=? WHERE seq=1",
            ("0" * 64,),
        )
        connection.commit()

    with pytest.raises(GoalProofLedgerIntegrityError, match="payload hash mismatch"):
        ledger.sync()
    assert ledger.mirror_path.read_bytes() == mirror_before
    with pytest.raises(GoalProofLedgerIntegrityError, match="payload hash mismatch"):
        ledger.current(owner="alice")


def test_current_uses_one_snapshot_and_does_not_leak_racing_unmirrored_commit(
    tmp_path,
):
    root = tmp_path / "ledger"
    initial = GoalProofLedger(root)
    initial.commit(
        ProofBundle(
            owner="alice",
            subject="goal:quantbt",
            members=(ProofMember("coverage", "coverage:initial", {"value": 1}),),
        )
    )

    writer_preflight = threading.Event()
    allow_writer_commit = threading.Event()
    writer_committed = threading.Event()

    def writer_fault(cutpoint: str) -> None:
        if cutpoint == "after_preflight_sync":
            writer_preflight.set()
            assert allow_writer_commit.wait(timeout=10)
        elif cutpoint == "after_sqlite_commit":
            writer_committed.set()
            raise RuntimeError("leave writer event unmirrored")

    writer = GoalProofLedger(root, fault_injector=writer_fault)

    def reader_fault(cutpoint: str) -> None:
        if cutpoint == "current_after_snapshot_start":
            allow_writer_commit.set()
            assert writer_committed.wait(timeout=10)

    reader = GoalProofLedger(root, fault_injector=reader_fault)
    racing_bundle = ProofBundle(
        owner="alice",
        subject="goal:quantbt",
        members=(ProofMember("coverage", "coverage:racing", {"value": 2}),),
    )

    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(writer.commit, racing_bundle)
        assert writer_preflight.wait(timeout=10)
        snapshot = reader.current(owner="alice")
        with pytest.raises(GoalProofMirrorPendingError):
            future.result(timeout=10)

    assert snapshot.at_seq == 1
    assert tuple(head.logical_ref for head in snapshot.heads) == ("coverage:initial",)
    assert snapshot.mirror_synced is True

    reader._fault_injector = None
    repaired = reader.sync()
    assert repaired.appended == 1
    refreshed = reader.current(owner="alice")
    assert refreshed.at_seq == 2
    assert tuple(head.logical_ref for head in refreshed.heads) == (
        "coverage:initial",
        "coverage:racing",
    )


def test_concurrent_exact_retry_creates_one_bundle_and_one_event_set(tmp_path):
    ledger = GoalProofLedger(tmp_path / "ledger")
    bundle = _bundle()

    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(lambda _index: ledger.commit(bundle), range(16)))

    assert {result.bundle_id for result in results} == {results[0].bundle_id}
    assert sum(result.status == "committed" for result in results) == 1
    assert sum(result.status == "idempotent" for result in results) == 15
    counts = _counts(ledger)
    assert counts["goal_proof_bundles"] == 1
    assert counts["goal_proof_events"] == 2
    assert counts["goal_proof_declarations"] == 2
    assert ledger.verify().ok is True


def test_stale_invalidation_operation_replay_does_not_revoke_generation_two(tmp_path):
    ledger = GoalProofLedger(tmp_path / "ledger")
    first = ledger.commit(_bundle())
    operation = {
        "owner": "alice",
        "operation_id": "operation-r-generation-1",
        "targets": (_target(first, "coverage:a"),),
        "reason": "operation-r",
        "subject": "goal:quantbt",
    }
    original = ledger.invalidate(**operation)
    second = ledger.commit(_bundle(a_value=3, b_value=4))

    replay = ledger.invalidate(**operation)

    assert replay.status == "idempotent"
    assert replay.invalidation_bundle_id == original.invalidation_bundle_id
    snapshot = ledger.current(owner="alice")
    assert {head.declaration_event_id for head in snapshot.heads} == {
        head.declaration_event_id for head in second.heads
    }
    assert not {
        head.declaration_event_id for head in first.heads
    }.intersection(head.declaration_event_id for head in snapshot.heads)

    with pytest.raises(GoalProofConflictError, match="operation identity"):
        ledger.invalidate(
            owner="alice",
            operation_id="operation-r-generation-1",
            targets=(_target(second, "coverage:a"),),
            reason="operation-r",
            subject="goal:quantbt",
        )
    with pytest.raises(GoalProofConflictError, match="expected targets are stale"):
        ledger.invalidate(
            owner="alice",
            operation_id="operation-r-stale-new-id",
            targets=(_target(first, "coverage:a"),),
            reason="operation-r",
            subject="goal:quantbt",
        )
    generation_two = ledger.invalidate(
        owner="alice",
        operation_id="operation-r-generation-2",
        targets=(_target(second, "coverage:a"),),
        reason="operation-r",
        subject="goal:quantbt",
    )
    assert generation_two.status == "committed"


def test_fresh_root_twelve_processes_initialize_and_exact_retry_without_errors(tmp_path):
    root = tmp_path / "ledger"
    barrier = tmp_path / "barrier"
    barrier.mkdir()
    context = multiprocessing.get_context("spawn")
    with ProcessPoolExecutor(max_workers=12, mp_context=context) as pool:
        futures = [
            pool.submit(_fresh_root_process_commit, str(root), str(barrier))
            for _index in range(12)
        ]
        deadline = time.monotonic() + 30.0
        while len(tuple(barrier.glob("ready-*"))) < 12:
            assert time.monotonic() < deadline, "workers did not reach fresh-root barrier"
            time.sleep(0.01)
        (barrier / "go").write_text("go", encoding="utf-8")
        results = [future.result(timeout=60) for future in futures]

    assert sorted(results) == ["committed", *("idempotent" for _index in range(11))]
    ledger = GoalProofLedger(root)
    assert ledger.verify().ok is True
    assert _counts(ledger)["goal_proof_events"] == 2


@pytest.mark.parametrize(
    ("field", "tampered"),
    (
        ("owner", "mallory"),
        ("logical_ref", "coverage:forged"),
        ("subject", "goal:forged"),
        ("logical_type", "forged"),
        ("generation", 99),
        ("bundle_id", "USE_OTHER_BUNDLE"),
        ("declared_seq", 999),
        ("payload_hash", "0" * 64),
    ),
)
def test_current_head_envelope_tampering_fails_closed(tmp_path, field, tampered):
    ledger = GoalProofLedger(tmp_path / "ledger")
    ledger.commit(_bundle())
    other = ledger.commit(
        ProofBundle(
            owner="alice",
            subject="goal:quantbt",
            members=(ProofMember("other", "other:c", {"value": 3}),),
        )
    )
    value = other.bundle_id if tampered == "USE_OTHER_BUNDLE" else tampered
    with sqlite3.connect(ledger.db_path) as connection:
        connection.execute(
            f"UPDATE goal_proof_current_heads SET {field}=? "
            "WHERE declaration_event_id=("
            "SELECT declaration_event_id FROM goal_proof_declarations "
            "WHERE logical_ref='coverage:a' AND generation=1)",
            (value,),
        )
        connection.commit()

    verification = ledger.verify()
    assert verification.ok is False
    assert any(
        "current head" in issue and field in issue for issue in verification.issues
    ), verification.issues
    with pytest.raises(GoalProofLedgerIntegrityError, match="current head"):
        ledger.current(owner="alice")


def test_dependency_edge_owner_tampering_fails_before_invalidation_commit(tmp_path):
    ledger = GoalProofLedger(tmp_path / "ledger")
    base = ledger.commit(_bundle())
    ledger.commit(
        ProofBundle(
            owner="alice",
            subject="goal:quantbt",
            members=(
                ProofMember(
                    "aggregate",
                    "aggregate:c",
                    {"value": 3},
                    depends_on=("receipt:b",),
                ),
            ),
        )
    )
    with sqlite3.connect(ledger.db_path) as connection:
        connection.execute(
            "UPDATE goal_proof_dependency_edges SET owner='mallory' "
            "WHERE dependency_logical_ref='receipt:b'"
        )
        connection.commit()
    events_before = _counts(ledger)["goal_proof_events"]

    verification = ledger.verify()
    assert verification.ok is False
    assert any("dependency owner mismatch" in issue for issue in verification.issues)
    with pytest.raises(GoalProofLedgerIntegrityError, match="dependency owner mismatch"):
        ledger.invalidate(
            owner="alice",
            operation_id="tampered-owner-must-fail",
            targets=(_target(base, "coverage:a"),),
            reason="must not bypass aggregate",
        )
    assert _counts(ledger)["goal_proof_events"] == events_before


def test_bundle_current_projection_is_all_or_none(tmp_path):
    ledger = GoalProofLedger(tmp_path / "ledger")
    committed = ledger.commit(_bundle())
    with sqlite3.connect(ledger.db_path) as connection:
        connection.execute(
            "DELETE FROM goal_proof_current_heads WHERE declaration_event_id=?",
            (committed.heads[0].declaration_event_id,),
        )
        connection.commit()

    verification = ledger.verify()
    assert verification.ok is False
    assert any("partial current status" in issue for issue in verification.issues)


def test_self_dependency_is_rejected_but_two_member_cycle_is_bundle_atomic(tmp_path):
    with pytest.raises(ValueError, match="cannot depend on itself"):
        ProofMember("coverage", "coverage:self", {}, depends_on=("coverage:self",))

    ledger = GoalProofLedger(tmp_path / "ledger")
    cyclic = ledger.commit(
        ProofBundle(
            owner="alice",
            subject="goal:quantbt",
            members=(
                ProofMember("coverage", "cycle:a", {}, depends_on=("cycle:b",)),
                ProofMember("coverage", "cycle:b", {}, depends_on=("cycle:a",)),
            ),
        )
    )
    invalidated = ledger.invalidate(
        owner="alice",
        operation_id="invalidate-cycle-generation-1",
        targets=(_target(cyclic, "cycle:a"),),
        reason="cycle invalidates as its exact bundle",
    )
    assert invalidated.affected_refs == ("cycle:a", "cycle:b")
    assert set(invalidated.target_declaration_event_ids) == {
        head.declaration_event_id for head in cyclic.heads
    }


@pytest.mark.parametrize(
    ("mutation", "sql", "params"),
    (
        (
            "wrong schema_version",
            "UPDATE goal_proof_meta SET value=? WHERE key=?",
            ("1", "schema_version"),
        ),
        (
            "wrong hash_version",
            "UPDATE goal_proof_meta SET value=? WHERE key=?",
            ("sha1-v0", "hash_version"),
        ),
        (
            "wrong mirror_schema_version",
            "UPDATE goal_proof_meta SET value=? WHERE key=?",
            ("goal-proof-ledger-mirror-v0", "mirror_schema_version"),
        ),
        (
            "missing required key",
            "DELETE FROM goal_proof_meta WHERE key=?",
            ("schema_version",),
        ),
        (
            "extra key",
            "INSERT INTO goal_proof_meta(key,value) VALUES (?,?)",
            ("unexpected", "value"),
        ),
    ),
)
def test_same_instance_meta_tamper_fails_closed_before_any_mutation(
    tmp_path,
    mutation,
    sql,
    params,
):
    ledger = GoalProofLedger(tmp_path / "ledger")
    committed = ledger.commit(_bundle())
    counts_before = _counts(ledger)
    with sqlite3.connect(ledger.db_path) as connection:
        connection.execute(sql, params)
        connection.commit()

    verification = ledger.verify()
    assert verification.ok is False, mutation
    assert any("GOAL proof meta" in issue for issue in verification.issues), (
        mutation,
        verification.issues,
    )
    with pytest.raises(GoalProofLedgerIntegrityError, match="GOAL proof meta"):
        ledger.current(owner="alice")

    with pytest.raises(GoalProofLedgerIntegrityError, match="GOAL proof meta"):
        ledger.commit(
            ProofBundle(
                owner="alice",
                subject="goal:quantbt",
                members=(ProofMember("coverage", "coverage:new", {"value": 3}),),
            )
        )
    assert _counts(ledger) == counts_before

    with pytest.raises(GoalProofLedgerIntegrityError, match="GOAL proof meta"):
        ledger.invalidate(
            owner="alice",
            operation_id=f"tampered-meta-{mutation}",
            targets=(_target(committed, "coverage:a"),),
            reason="must fail before mutation",
        )
    assert _counts(ledger) == counts_before


def test_snapshot_cache_lru_bounds_size_and_evicts_oldest(tmp_path):
    # LRU 有界(原无界 dict):超上限逐最旧,size 不无界增长。
    # 种坏:超上限后旧 key 若不被逐 → size 断言红。淘汰不 stale——重查重算等价快照。
    ledger = GoalProofLedger(tmp_path / "ledger")
    ledger._current_snapshot_cache_maxsize = 2  # 缩小便于种坏

    first_a = ledger.current(owner="a")
    ledger.current(owner="b")
    assert set(ledger._current_snapshot_cache.keys()) == {("a", None), ("b", None)}

    ledger.current(owner="c")  # 触发淘汰:最旧 ("a") 被逐
    assert len(ledger._current_snapshot_cache) == 2
    assert ("a", None) not in ledger._current_snapshot_cache
    assert set(ledger._current_snapshot_cache.keys()) == {("b", None), ("c", None)}

    # 淘汰项重查:重算(不报错、不 stale),内容与首次等价
    again_a = ledger.current(owner="a")
    assert again_a.at_seq == first_a.at_seq


def test_snapshot_cache_lru_hit_promotes_recency(tmp_path):
    # 读命中 move_to_end:近用项在淘汰中存活,老项先被逐(真 LRU 非 FIFO)。
    # 种坏:若命中不提权,current("a") 第二次后 a 仍最旧 → 下轮淘汰逐 a 而非 b → 断言红。
    ledger = GoalProofLedger(tmp_path / "ledger")
    ledger._current_snapshot_cache_maxsize = 2

    ledger.current(owner="a")
    ledger.current(owner="b")
    ledger.current(owner="a")   # 命中 → a 提到最近端
    ledger.current(owner="c")   # 淘汰最旧 = b(非 a)
    assert ("b", None) not in ledger._current_snapshot_cache
    assert set(ledger._current_snapshot_cache.keys()) == {("a", None), ("c", None)}
