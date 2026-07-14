from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app import main
from app.auth import require_user_dependency
from app.copy_trade import CopyTradeService
from app.security import (
    InMemoryKeystore,
    KeystoreError,
    KeystoreRecord,
    PersistentTradingCredentialRegistry,
    SecureKeystore,
)
from app.security.gate.broker import KeyBroker
from app.security.mainnet_guards import MainnetGuardConfig, MainnetGuardsService


def _client(monkeypatch, tmp_path):
    keystore = SecureKeystore(InMemoryKeystore())
    registry = PersistentTradingCredentialRegistry(tmp_path / "trading-credentials.sqlite3")
    service = CopyTradeService(tmp_path / "copy-trade.sqlite3")
    current = {"user_id": "alice"}
    monkeypatch.setattr(main, "KEYSTORE", keystore)
    monkeypatch.setattr(main, "TRADING_CREDENTIALS", registry)
    monkeypatch.setattr(
        main,
        "ORDER_BROKER",
        KeyBroker(
            keystore,
            hmac_key=b"t" * 32,
            credential_owner_validator=registry.is_owned,
            credential_binding_resolver=registry.binding_ref,
        ),
    )
    monkeypatch.setattr(main, "COPY_TRADE_SERVICE", service)
    main.app.dependency_overrides[require_user_dependency] = lambda: SimpleNamespace(**current)
    return TestClient(main.app), current, keystore, service


def test_keystore_list_and_write_require_authentication():
    client = TestClient(main.app)
    assert client.get("/api/security/keystore").status_code in (401, 403)
    assert client.post(
        "/api/security/keystore",
        json={"name": "binance_mainnet", "api_key": "K", "api_secret": "S"},
    ).status_code in (401, 403)
    assert client.post("/api/security/reload_secrets").status_code in (401, 403)


def test_same_alias_is_physically_isolated_by_authenticated_owner(monkeypatch, tmp_path):
    client, current, keystore, _service = _client(monkeypatch, tmp_path)
    try:
        first = client.post(
            "/api/security/keystore",
            json={"name": "binance_mainnet", "api_key": "ALICE", "api_secret": "AS"},
        )
        assert first.status_code == 200
        current["user_id"] = "bob"
        second = client.post(
            "/api/security/keystore",
            json={"name": "binance_mainnet", "api_key": "BOB", "api_secret": "BS"},
        )
        assert second.status_code == 200

        alice_ref = main._user_keystore_ref("alice", "binance_mainnet")
        bob_ref = main._user_keystore_ref("bob", "binance_mainnet")
        assert alice_ref != bob_ref
        assert keystore.fetch(alice_ref).api_key == "ALICE"
        assert keystore.fetch(bob_ref).api_key == "BOB"
        assert client.get("/api/security/keystore").json()["names"] == ["binance_mainnet"]

        current["user_id"] = "alice"
        assert client.get("/api/security/keystore").json()["names"] == ["binance_mainnet"]
    finally:
        main.app.dependency_overrides.pop(require_user_dependency, None)


def test_active_mainnet_alias_cannot_be_overwritten(monkeypatch, tmp_path):
    client, current, keystore, service = _client(monkeypatch, tmp_path)
    try:
        initial = client.post(
            "/api/security/keystore",
            json={"name": "binance_mainnet", "api_key": "ORIGINAL", "api_secret": "S"},
        )
        assert initial.status_code == 200
        ref = main._user_keystore_ref("alice", "binance_mainnet")
        master = service.register_master("master", "Master", asset_class="crypto_perp")
        service.subscribe(
            user_id="alice",
            master_id=master.master_id,
            invest_amount=1000.0,
            binance_keystore_name=ref,
            binance_network="mainnet",
            per_order_max_usdt=100.0,
                account_binding_ref="exchange_account_uid_alice",
                runtime_promotion_ref="runtime_promotion_alice",
                user_risk_choice_ref="user_risk_choice_alice",
        )

        overwrite = client.post(
            "/api/security/keystore",
            json={"name": "binance_mainnet", "api_key": "SWAPPED", "api_secret": "S2"},
        )
        assert overwrite.status_code == 409
        assert keystore.fetch(ref).api_key == "ORIGINAL"
    finally:
        main.app.dependency_overrides.pop(require_user_dependency, None)


def test_rotation_creates_new_immutable_version_and_keeps_old_secret(monkeypatch, tmp_path):
    client, _current, keystore, _service = _client(monkeypatch, tmp_path)
    try:
        first = client.post(
            "/api/security/keystore",
            json={"name": "binance_mainnet", "api_key": "VERSION1", "api_secret": "S1"},
        )
        assert first.status_code == 200 and first.json()["version"] == 1
        ref_v1 = main._user_keystore_ref("alice", "binance_mainnet")

        second = client.post(
            "/api/security/keystore",
            json={"name": "binance_mainnet", "api_key": "VERSION2", "api_secret": "S2"},
        )
        assert second.status_code == 200 and second.json()["version"] == 2
        ref_v2 = main._user_keystore_ref("alice", "binance_mainnet")
        assert ref_v2 != ref_v1
        assert keystore.fetch(ref_v1).api_key == "VERSION1"
        assert keystore.fetch(ref_v2).api_key == "VERSION2"
    finally:
        main.app.dependency_overrides.pop(require_user_dependency, None)


def test_broker_detects_physical_secret_swap_against_signed_binding(monkeypatch, tmp_path):
    client, _current, keystore, _service = _client(monkeypatch, tmp_path)
    try:
        assert client.post(
            "/api/security/keystore",
            json={"name": "binance_mainnet", "api_key": "ORIGINAL", "api_secret": "S1"},
        ).status_code == 200
        ref = main._user_keystore_ref("alice", "binance_mainnet")
        cap = main.ORDER_BROKER.issue_capability(
            action="verify_account_identity",
            gate_ref="identity-check",
            keystore_name=ref,
            owner_user_id="alice",
        )
        keystore.store(KeystoreRecord(name=ref, api_key="SWAPPED", api_secret="S2"))
        with pytest.raises(PermissionError, match="immutable binding"):
            main.ORDER_BROKER.issue(cap)
    finally:
        main.app.dependency_overrides.pop(require_user_dependency, None)


@pytest.mark.parametrize("owner", ["alice", main._LLM_SERVICE_PRINCIPAL])
@pytest.mark.parametrize("reserved_ref", ["trading_credential_deadbeef", "usercred_deadbeef"])
def test_settings_secret_values_cannot_target_trading_namespace(reserved_ref, owner):
    with pytest.raises(ValueError, match="reserved trading credential namespace"):
        main._settings_secret_value_from_payload(
            {
                "secret_ref": "secret:reserved-trading-test",
                "secret_value": "K",
                "api_secret": "S",
                "keystore_ref": reserved_ref,
                "scope": "test",
            },
            owner_user_id=owner,
        )


def test_disabling_per_order_password_requires_trusted_ip_second_factor_and_statement(
    monkeypatch,
    tmp_path,
):
    guards = MainnetGuardsService(tmp_path / "guards.sqlite3")
    guards.upsert_config(
        MainnetGuardConfig(
            user_id="alice",
            trusted_ips=["127.0.0.1"],
            require_password_per_order=True,
        )
    )
    monkeypatch.setattr(main, "MAINNET_GUARDS", guards)
    monkeypatch.setattr(main, "_verify_second_factor_result", lambda *_args: (True, False))
    main.app.dependency_overrides[require_user_dependency] = lambda: SimpleNamespace(user_id="alice")
    client = TestClient(main.app, client=("127.0.0.1", 9000))
    try:
        missing_statement = client.post(
            "/api/security/mainnet/config",
            json={"require_password_per_order": False, "password": "pw"},
        )
        assert missing_statement.status_code == 400
        accepted = client.post(
            "/api/security/mainnet/config",
            json={
                "require_password_per_order": False,
                "password": "pw",
                "standing_authorization_statement": "我授权自动跟单",
            },
        )
        assert accepted.status_code == 200
        assert accepted.json()["require_password_per_order"] is False
        assert guards.list_audit_log("alice")[0]["operation"] == "standing_auto_copy_authorization"
    finally:
        main.app.dependency_overrides.pop(require_user_dependency, None)


def test_durable_credential_survives_restart_with_exact_full_material_binding(tmp_path):
    security = tmp_path / "security"
    keystore_path = security / "credentials.enc"
    registry_path = security / "trading-credentials.sqlite3"
    broker_key_path = security / "broker.key"
    keystore = SecureKeystore.open(
        prefer="fernet_file",
        fernet_path=keystore_path,
        master_password="restart-master",
    )
    registry = PersistentTradingCredentialRegistry(registry_path)
    pending = registry.begin_version("alice", "binance_mainnet")
    keystore.store(
        KeystoreRecord(
            name=pending.credential_ref,
            api_key="restart-key",
            api_secret="restart-secret",
        )
    )
    broker = KeyBroker(
        keystore,
        hmac_key_path=broker_key_path,
        credential_owner_validator=registry.is_owned,
        credential_binding_resolver=registry.binding_ref,
    )
    binding = broker.credential_binding_ref(pending.credential_ref, owner_user_id="alice")
    registry.activate(pending.credential_ref, binding)

    restarted_keystore = SecureKeystore.open(
        prefer="fernet_file",
        fernet_path=keystore_path,
        master_password="restart-master",
    )
    restarted_registry = PersistentTradingCredentialRegistry(registry_path)
    restarted_broker = KeyBroker(
        restarted_keystore,
        hmac_key_path=broker_key_path,
        credential_owner_validator=restarted_registry.is_owned,
        credential_binding_resolver=restarted_registry.binding_ref,
    )
    capability = restarted_broker.issue_capability(
        action="verify_account_identity",
        gate_ref="restart-proof",
        keystore_name=pending.credential_ref,
        owner_user_id="alice",
    )
    lease = restarted_broker.issue(capability)
    try:
        assert lease.record.api_secret == "restart-secret"
    finally:
        restarted_broker.revoke(lease)
    assert restarted_registry.current("alice", "binance_mainnet").credential_binding_ref == binding
    assert registry_path.stat().st_mode & 0o777 == 0o600


def test_startup_recovery_deletes_stranded_pending_material_before_marking_failed(
    tmp_path,
    monkeypatch,
):
    keystore = SecureKeystore(InMemoryKeystore())
    registry = PersistentTradingCredentialRegistry(tmp_path / "credentials.sqlite3")
    pending = registry.begin_version("alice", "binance_mainnet")
    keystore.store(
        KeystoreRecord(name=pending.credential_ref, api_key="key", api_secret="secret")
    )
    monkeypatch.setattr(main, "KEYSTORE", keystore)
    monkeypatch.setattr(main, "TRADING_CREDENTIALS", registry)

    main._recover_incomplete_trading_credentials()

    assert registry.credential(pending.credential_ref).status == "failed"
    with pytest.raises(KeystoreError):
        keystore.fetch(pending.credential_ref)


def test_startup_recovery_fails_before_status_change_when_material_delete_fails(
    tmp_path,
    monkeypatch,
):
    keystore = SecureKeystore(InMemoryKeystore())
    registry = PersistentTradingCredentialRegistry(tmp_path / "credentials.sqlite3")
    pending = registry.begin_version("alice", "binance_mainnet")
    keystore.store(
        KeystoreRecord(name=pending.credential_ref, api_key="key", api_secret="secret")
    )
    monkeypatch.setattr(main, "KEYSTORE", keystore)
    monkeypatch.setattr(main, "TRADING_CREDENTIALS", registry)
    monkeypatch.setattr(
        keystore,
        "delete",
        lambda _name: (_ for _ in ()).throw(OSError("injected delete failure")),
    )

    with pytest.raises(RuntimeError, match="could not be removed"):
        main._recover_incomplete_trading_credentials()
    assert registry.credential(pending.credential_ref).status == "pending"


def test_mainnet_bootstrap_quarantines_invalid_account_without_hiding_valid_emergency_handle(
    monkeypatch,
):
    followers = (
        SimpleNamespace(
            follower_id="valid",
            user_id="alice",
            master_id="master-valid",
            status="active",
            binance_network="mainnet",
            binance_keystore_name="credential-valid",
            account_binding_ref="account-valid",
            credential_binding_ref="binding:credential-valid",
            runtime_promotion_ref="promotion-valid",
            user_risk_choice_ref="choice-valid",
            user_risk_consent_event_ref="consent-valid",
            activation_ref="activation-valid",
        ),
        SimpleNamespace(
            follower_id="invalid",
            user_id="alice",
            master_id="master-invalid",
            status="paused",
            binance_network="mainnet",
            binance_keystore_name="credential-invalid",
            account_binding_ref="account-invalid",
            credential_binding_ref="binding:credential-invalid",
            runtime_promotion_ref="promotion-invalid",
            user_risk_choice_ref="choice-invalid",
            user_risk_consent_event_ref="consent-invalid",
            activation_ref="activation-invalid",
        ),
    )
    draining: list[str] = []
    follower_by_id = {follower.follower_id: follower for follower in followers}

    def begin_draining(user_id, master_id):
        draining.append(f"{user_id}:{master_id}")
        for follower in followers:
            if follower.user_id == user_id and follower.master_id == master_id:
                follower.status = "draining"
        return True

    service = SimpleNamespace(
        list_masters=lambda limit: (
            SimpleNamespace(master_id="master-valid"),
            SimpleNamespace(master_id="master-invalid"),
        ),
        list_followers=lambda master_id, active_only=False: tuple(
            follower for follower in followers if follower.master_id == master_id
        ),
        unfinished_mainnet_activations=lambda: (),
        begin_draining=begin_draining,
        get_follower=lambda follower_id: follower_by_id.get(follower_id),
        mainnet_capability_account_status=lambda _owner, account_ref, *_args, **_kwargs: (
            "active" if account_ref == "account-valid" else None
        ),
        risk_consents=SimpleNamespace(validate_event=lambda **_kwargs: None),
    )
    active = SimpleNamespace(registered=[], register=lambda handle: active.registered.append(handle))
    credentials = SimpleNamespace(
        credential=lambda ref: SimpleNamespace(
            status="active",
            owner_user_id="alice",
            credential_binding_ref=f"binding:{ref}",
        )
    )
    monkeypatch.setattr(main, "COPY_TRADE_SERVICE", service)
    monkeypatch.setattr(main, "ACTIVE_EMERGENCY_VENUES", active)
    monkeypatch.setattr(main, "TRADING_CREDENTIALS", credentials)
    monkeypatch.setattr(main, "KEYSTORE", SimpleNamespace(is_durable=True))
    monkeypatch.setattr(main, "USER_RISK_CHOICES", SimpleNamespace(
        refresh=lambda: None,
        choice_for_owner=lambda ref, _owner: SimpleNamespace(
            choice_ref=ref,
            risk_disclosure_profile_ref="profile-valid",
        ),
    ))
    monkeypatch.setattr(main, "RUNTIME_PROMOTIONS", SimpleNamespace(
        refresh=lambda: None,
        promotion=lambda ref: SimpleNamespace(runtime_promotion_ref=ref),
    ))
    monkeypatch.setattr(main, "validate_user_risk_choice_for_follower", lambda *_args: None)
    monkeypatch.setattr(
        main,
        "runtime_requirements_for_follower",
        lambda *_args, **_kwargs: SimpleNamespace(request_ref="request-valid"),
    )
    monkeypatch.setattr(main, "validate_live_runtime_promotion", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        main,
        "ORDER_BROKER",
        SimpleNamespace(credential_binding_ref=lambda ref, **_kwargs: f"binding:{ref}"),
    )
    monkeypatch.setattr(
        main,
        "_emergency_handle_for_follower",
        lambda follower: object() if follower.follower_id == "valid" else None,
    )
    halt_states = {follower.account_binding_ref: "running" for follower in followers}

    def begin_halt(account_ref, _owner, **_kwargs):
        halt_states[account_ref] = "halting"
        return SimpleNamespace(state="halting")

    monkeypatch.setattr(
        main,
        "ACCOUNT_HALT_BARRIER",
        SimpleNamespace(
            validate_account=lambda account_ref, _owner: SimpleNamespace(
                state=halt_states[account_ref],
                execution_enabled=halt_states[account_ref] == "running",
            ),
            begin_account_halt=begin_halt,
        ),
    )
    monkeypatch.setattr(main, "MAINNET_GUARDS", SimpleNamespace(log_operation=lambda *_args, **_kwargs: None))

    main._bootstrap_active_emergency_venues()

    assert len(active.registered) == 1
    assert draining == ["alice:master-invalid"]
    assert halt_states == {"account-valid": "running", "account-invalid": "halting"}
    assert any(issue["follower_id"] == "invalid" for issue in main._COPY_TRADE_BOOTSTRAP_ISSUES)
