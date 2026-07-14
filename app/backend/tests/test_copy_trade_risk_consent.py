from __future__ import annotations

import copy
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.copy_trade.consent import PersistentUserRiskConsentStore, RiskConsentError
from app.copy_trade.formal_execution import (
    build_user_risk_choice,
    copy_trade_risk_disclosure_profile,
    runtime_requirements_for_follower,
)
from app.lineage.ids import content_hash
from app.research_os.execution_boundary import (
    PersistentConsentBackedUserRiskChoiceRegistry,
    user_risk_choice_from_dict,
)
from app.research_os.goal_coverage import (
    PersistentGoalEntrypointCoverageRegistry,
    RiskConsentEntrypointCoverageRegistry,
)


def _profile_content(profile: dict) -> dict:
    return {
        key: profile[key]
        for key in (
            "asset_class",
            "selected_risk_path",
            "disclosures",
            "failure_modes",
            "recommendation",
            "responsibility_boundary",
            "waiver_effect",
        )
    }


def _issued(tmp_path: Path):
    store = PersistentUserRiskConsentStore(
        tmp_path / "community.db",
        integrity_key=b"c" * 32,
    )
    profile = copy_trade_risk_disclosure_profile()
    source_hash = store.source_ip_hash("127.0.0.1")
    follower = SimpleNamespace(
        follower_id="user-1::master-1",
        user_id="user-1",
        master_id="master-1",
        account_binding_ref="exchange_account_uid_1",
        binance_network="mainnet",
        invest_amount=1_000.0,
        per_order_max_usdt=100.0,
        daily_loss_limit_pct=0.05,
        max_positions=3,
        max_leverage=2.0,
    )
    choice_record = build_user_risk_choice(
        follower,
        owner_user_id="user-1",
        selected_risk_path="small_live",
        risk_disclosure_profile_ref=profile["profile_ref"],
    )
    requirements = runtime_requirements_for_follower(
        follower,
        risk_choice=choice_record,
    )
    choice = choice_record.to_dict()
    payload = {
        "risk_profile": profile,
        "required_acknowledgement_refs": profile["required_acknowledgement_refs"],
        "normalized_risk_limits": {
            "invest_amount": 1_000.0,
            "per_order_max_usdt": 100.0,
            "daily_loss_limit_pct": 0.05,
            "max_positions": 3,
            "max_leverage": 2.0,
        },
        "binance_keystore_name": "credential-ref-1",
        "proposed_user_risk_choice": choice,
    }
    challenge = store.issue_challenge(
        owner_user_id="user-1",
        follower_id="user-1::master-1",
        master_id="master-1",
        account_binding_ref="exchange_account_uid_1",
        credential_binding_ref="exchange_credential_1",
        subject_ref=requirements.subject_ref,
        runtime_request_ref=requirements.request_ref,
        risk_profile_ref=profile["profile_ref"],
        source_ip_hash=source_hash,
        payload=payload,
    )
    return store, profile, source_hash, challenge, choice


def _consume(store, profile, source_hash, challenge, choice):
    return store.consume_challenge(
        challenge_ref=challenge.challenge_ref,
        owner_user_id="user-1",
        user_risk_choice_ref=choice["choice_ref"],
        user_risk_choice=choice,
        acknowledged_item_refs=profile["required_acknowledgement_refs"],
        source_ip_hash=source_hash,
        password_verified=True,
        totp_verified=False,
    )


def test_profile_v2_binds_every_readable_risk_item() -> None:
    profile = copy_trade_risk_disclosure_profile()
    assert profile["disclosures"]
    assert profile["failure_modes"]
    assert all(item["text"] for item in profile["failure_modes"].values())
    assert profile["recommendation"]["text"]
    assert all(profile["responsibility_boundary"]["parties"].values())
    assert profile["profile_content_hash"] == content_hash(_profile_content(profile))
    assert profile["profile_ref"].endswith(profile["profile_content_hash"])
    changed = copy.deepcopy(_profile_content(profile))
    changed["failure_modes"]["venue_unavailable"]["text"] += " changed"
    assert content_hash(changed) != profile["profile_content_hash"]


def test_challenge_requires_exact_acknowledgements_and_is_single_use(tmp_path: Path) -> None:
    store, profile, source_hash, challenge, choice = _issued(tmp_path)
    required = profile["required_acknowledgement_refs"]

    with pytest.raises(RiskConsentError, match="acknowledgement refs"):
        store.consume_challenge(
            challenge_ref=challenge.challenge_ref,
            owner_user_id="user-1",
            user_risk_choice_ref=choice["choice_ref"],
            user_risk_choice=choice,
            acknowledged_item_refs=required[:-1],
            source_ip_hash=source_hash,
            password_verified=True,
            totp_verified=False,
        )

    event = store.consume_challenge(
        challenge_ref=challenge.challenge_ref,
        owner_user_id="user-1",
        user_risk_choice_ref=choice["choice_ref"],
        user_risk_choice=choice,
        acknowledged_item_refs=required,
        source_ip_hash=source_hash,
        password_verified=True,
        totp_verified=False,
    )
    retry = store.consume_challenge(
        challenge_ref=challenge.challenge_ref,
        owner_user_id="user-1",
        user_risk_choice_ref=choice["choice_ref"],
        user_risk_choice=choice,
        acknowledged_item_refs=required,
        source_ip_hash=source_hash,
        password_verified=True,
        totp_verified=False,
    )
    assert retry == event

    changed = dict(choice, runtime_request_ref="request-2")
    with pytest.raises(RiskConsentError):
        store.consume_challenge(
            challenge_ref=challenge.challenge_ref,
            owner_user_id="user-1",
            user_risk_choice_ref=choice["choice_ref"],
            user_risk_choice=changed,
            acknowledged_item_refs=required,
            source_ip_hash=source_hash,
            password_verified=True,
            totp_verified=False,
        )


def test_two_process_style_consumers_resolve_one_immutable_event(tmp_path: Path) -> None:
    store, profile, source_hash, challenge, choice = _issued(tmp_path)
    second = PersistentUserRiskConsentStore(
        tmp_path / "community.db",
        integrity_key=b"c" * 32,
    )

    def consume(target: PersistentUserRiskConsentStore) -> str:
        return target.consume_challenge(
            challenge_ref=challenge.challenge_ref,
            owner_user_id="user-1",
            user_risk_choice_ref=choice["choice_ref"],
            user_risk_choice=choice,
            acknowledged_item_refs=profile["required_acknowledgement_refs"],
            source_ip_hash=source_hash,
            password_verified=True,
            totp_verified=False,
        ).consent_event_ref

    with ThreadPoolExecutor(max_workers=2) as pool:
        refs = list(pool.map(consume, (store, second)))
    assert len(set(refs)) == 1
    conn = sqlite3.connect(tmp_path / "community.db")
    try:
        assert conn.execute("SELECT COUNT(*) FROM ct_user_risk_consent_events").fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM ct_user_risk_consent_decisions").fetchone()[0] == 1
    finally:
        conn.close()


def test_event_timestamp_or_payload_tamper_is_rejected(tmp_path: Path) -> None:
    store, profile, source_hash, challenge, choice = _issued(tmp_path)
    event = store.consume_challenge(
        challenge_ref=challenge.challenge_ref,
        owner_user_id="user-1",
        user_risk_choice_ref=choice["choice_ref"],
        user_risk_choice=choice,
        acknowledged_item_refs=profile["required_acknowledgement_refs"],
        source_ip_hash=source_hash,
        password_verified=False,
        totp_verified=True,
    )
    conn = sqlite3.connect(tmp_path / "community.db")
    try:
        conn.execute(
            "UPDATE ct_user_risk_consent_events SET acknowledged_at_utc='2099-01-01T00:00:00+00:00' "
            "WHERE consent_event_ref=?",
            (event.consent_event_ref,),
        )
        conn.commit()
    finally:
        conn.close()
    with pytest.raises(RiskConsentError, match="identity mismatch|integrity seal"):
        store.event_for_owner(event.consent_event_ref, "user-1")


def test_valid_but_unpresented_choice_is_rejected(tmp_path: Path) -> None:
    store, profile, source_hash, challenge, choice = _issued(tmp_path)
    substituted = replace(
        user_risk_choice_from_dict(choice),
        choice_ref="",
        created_at_utc=(datetime.now(UTC) + timedelta(seconds=1)).isoformat(),
    ).to_dict()
    with pytest.raises(RiskConsentError, match="differs from the presented choice"):
        store.consume_challenge(
            challenge_ref=challenge.challenge_ref,
            owner_user_id="user-1",
            user_risk_choice_ref=substituted["choice_ref"],
            user_risk_choice=substituted,
            acknowledged_item_refs=profile["required_acknowledgement_refs"],
            source_ip_hash=source_hash,
            password_verified=True,
            totp_verified=False,
        )


def test_decision_insert_failure_rolls_back_event_choice_and_challenge(tmp_path: Path) -> None:
    store, profile, source_hash, challenge, choice = _issued(tmp_path)
    conn = sqlite3.connect(tmp_path / "community.db")
    try:
        conn.execute(
            "CREATE TRIGGER fail_risk_consent_decision BEFORE INSERT "
            "ON ct_user_risk_consent_decisions BEGIN "
            "SELECT RAISE(ABORT, 'forced decision failure'); END"
        )
        conn.commit()
    finally:
        conn.close()

    with pytest.raises(sqlite3.IntegrityError, match="forced decision failure"):
        _consume(store, profile, source_hash, challenge, choice)

    conn = sqlite3.connect(tmp_path / "community.db")
    try:
        assert conn.execute("SELECT COUNT(*) FROM ct_user_risk_consent_events").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM ct_user_risk_consent_decisions").fetchone()[0] == 0
        row = conn.execute(
            "SELECT status,consumed_event_ref FROM ct_user_risk_consent_challenges "
            "WHERE challenge_ref=?",
            (challenge.challenge_ref,),
        ).fetchone()
        assert row == ("issued", None)
    finally:
        conn.close()
    choice_view = PersistentConsentBackedUserRiskChoiceRegistry(store)
    with pytest.raises(KeyError):
        choice_view.choice(choice["choice_ref"])


def test_restart_resolves_owner_scoped_choice_and_source_coverage(tmp_path: Path) -> None:
    store, profile, source_hash, challenge, choice = _issued(tmp_path)
    event = _consume(store, profile, source_hash, challenge, choice)
    restarted = PersistentUserRiskConsentStore(
        tmp_path / "community.db",
        integrity_key=b"c" * 32,
    )
    decision = restarted.decision_for_event(event.consent_event_ref, "user-1")
    choice_view = PersistentConsentBackedUserRiskChoiceRegistry(restarted)
    assert choice_view.choice_for_owner(choice["choice_ref"], "user-1").to_dict() == choice
    with pytest.raises(PermissionError):
        choice_view.choice_for_owner(choice["choice_ref"], "user-2")
    with pytest.raises(PermissionError, match="atomic risk-consent boundary"):
        choice_view.record_choice(choice_view.choice(choice["choice_ref"]))

    delegate = PersistentGoalEntrypointCoverageRegistry(tmp_path / "goal_coverage.jsonl")
    coverage_view = RiskConsentEntrypointCoverageRegistry(
        delegate,
        restarted,
        entrypoint_ref="api:copy_trade.risk_consents.confirm",
    )
    coverage = coverage_view.coverage(
        decision.source_coverage.coverage_ref,
        owner="user-1",
    )
    assert coverage_view.validate_real_backing(coverage).accepted
    assert coverage.canonical_command_refs == (choice["choice_ref"],)
    assert event.consent_event_ref in coverage.evidence_refs
    with pytest.raises(KeyError):
        coverage_view.coverage(coverage.coverage_ref, owner="user-2")


def test_source_coverage_becomes_stale_after_newer_exact_decision(tmp_path: Path) -> None:
    store, profile, source_hash, challenge, choice = _issued(tmp_path)
    first_event = _consume(store, profile, source_hash, challenge, choice)
    first = store.decision_for_event(first_event.consent_event_ref, "user-1")

    replacement = replace(
        user_risk_choice_from_dict(choice),
        choice_ref="",
        created_at_utc=(datetime.now(UTC) + timedelta(seconds=1)).isoformat(),
    ).to_dict()
    second_challenge = store.issue_challenge(
        owner_user_id="user-1",
        follower_id=choice["follower_id"],
        master_id=choice["master_id"],
        account_binding_ref=choice["account_binding_ref"],
        credential_binding_ref="exchange_credential_1",
        subject_ref=choice["subject_ref"],
        runtime_request_ref=choice["runtime_request_ref"],
        risk_profile_ref=profile["profile_ref"],
        source_ip_hash=source_hash,
        payload={
            "risk_profile": profile,
            "required_acknowledgement_refs": profile["required_acknowledgement_refs"],
            "proposed_user_risk_choice": replacement,
        },
    )
    second_event = _consume(
        store,
        profile,
        source_hash,
        second_challenge,
        replacement,
    )
    second = store.decision_for_event(second_event.consent_event_ref, "user-1")
    assert not store.validate_source_coverage(first.source_coverage).accepted
    assert store.validate_source_coverage(second.source_coverage).accepted


def test_decision_tamper_is_rejected(tmp_path: Path) -> None:
    store, profile, source_hash, challenge, choice = _issued(tmp_path)
    event = _consume(store, profile, source_hash, challenge, choice)
    conn = sqlite3.connect(tmp_path / "community.db")
    try:
        conn.execute(
            "UPDATE ct_user_risk_consent_decisions SET decision_hash='tampered' "
            "WHERE consent_event_ref=?",
            (event.consent_event_ref,),
        )
        conn.commit()
    finally:
        conn.close()
    with pytest.raises(RiskConsentError, match="payload hash mismatch"):
        store.decision_for_event(event.consent_event_ref, "user-1")


def test_early_one_decision_per_choice_schema_migrates_without_row_loss(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "community.db"
    conn = sqlite3.connect(db_path)
    try:
        conn.executescript(
            """
            CREATE TABLE ct_user_risk_consent_decisions (
                seq INTEGER PRIMARY KEY AUTOINCREMENT,
                decision_ref TEXT NOT NULL UNIQUE,
                challenge_ref TEXT NOT NULL UNIQUE,
                consent_event_ref TEXT NOT NULL UNIQUE,
                user_risk_choice_ref TEXT NOT NULL UNIQUE,
                source_coverage_ref TEXT NOT NULL UNIQUE,
                owner_user_id TEXT NOT NULL,
                follower_id TEXT NOT NULL,
                master_id TEXT NOT NULL,
                runtime_request_ref TEXT NOT NULL,
                decision_json TEXT NOT NULL,
                decision_hash TEXT NOT NULL,
                integrity_key_version TEXT NOT NULL,
                integrity_seal TEXT NOT NULL,
                committed_at_utc TEXT NOT NULL
            );
            INSERT INTO ct_user_risk_consent_decisions VALUES (
                1,'decision-1','challenge-1','event-1','choice-1','coverage-1',
                'owner-1','follower-1','master-1','runtime-1','{}','hash-1',
                'user-risk-consent-hmac-v1','seal-1','2026-01-01T00:00:00+00:00'
            );
            """
        )
        conn.commit()
    finally:
        conn.close()

    PersistentUserRiskConsentStore(db_path, integrity_key=b"c" * 32)
    conn = sqlite3.connect(db_path)
    try:
        assert conn.execute(
            "SELECT decision_ref,user_risk_choice_ref "
            "FROM ct_user_risk_consent_decisions"
        ).fetchall() == [("decision-1", "choice-1")]
        unique_choice_indexes = []
        for index in conn.execute(
            "PRAGMA index_list('ct_user_risk_consent_decisions')"
        ).fetchall():
            if not index[2]:
                continue
            columns = tuple(
                row[2]
                for row in conn.execute(
                    f"PRAGMA index_info('{index[1]}')"
                ).fetchall()
            )
            if columns == ("user_risk_choice_ref",):
                unique_choice_indexes.append(index[1])
        assert unique_choice_indexes == []
    finally:
        conn.close()


def test_missing_integrity_key_fails_when_evidence_exists(tmp_path: Path) -> None:
    key_path = tmp_path / "consent.key"
    store = PersistentUserRiskConsentStore(
        tmp_path / "community.db",
        integrity_key_path=key_path,
    )
    profile = copy_trade_risk_disclosure_profile()
    store.issue_challenge(
        owner_user_id="user-1",
        follower_id="user-1::master-1",
        master_id="master-1",
        account_binding_ref="account-1",
        credential_binding_ref="credential-1",
        subject_ref="subject-1",
        runtime_request_ref="request-1",
        risk_profile_ref=profile["profile_ref"],
        source_ip_hash=store.source_ip_hash("127.0.0.1"),
        payload={"required_acknowledgement_refs": profile["required_acknowledgement_refs"]},
    )
    key_path.unlink()
    with pytest.raises(RuntimeError, match="integrity key is missing"):
        PersistentUserRiskConsentStore(
            tmp_path / "community.db",
            integrity_key_path=key_path,
        )
