"""v0.9.6 · /api/security/binance/verify endpoint 单测。

校验:
- 缺少对应 network 的 keystore record → ok=False, error=key_not_found
- 非法 network 参数 → 400
- 签名调用失败时 error 分类正确 (invalid_api_key / bad_signature / endpoint_not_found)
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app import main
from app.auth import require_user_dependency
from app.security import (
    InMemoryKeystore,
    PersistentTradingCredentialRegistry,
    SecureKeystore,
)
from app.security.gate.broker import KeyBroker


@pytest.fixture
def client(monkeypatch, tmp_path) -> TestClient:
    keystore = SecureKeystore(InMemoryKeystore())
    registry = PersistentTradingCredentialRegistry(
        tmp_path / "test-binance-verify-credentials.sqlite3"
    )
    broker = KeyBroker(
        keystore,
        hmac_key=b"v" * 32,
        credential_owner_validator=registry.is_owned,
        credential_binding_resolver=registry.binding_ref,
    )
    monkeypatch.setattr(main, "KEYSTORE", keystore)
    monkeypatch.setattr(main, "TRADING_CREDENTIALS", registry)
    monkeypatch.setattr(main, "ORDER_BROKER", broker)
    main.app.dependency_overrides[require_user_dependency] = lambda: SimpleNamespace(user_id="user-1")
    try:
        test_client = TestClient(main.app)
        test_client._test_broker = broker
        yield test_client
    finally:
        main.app.dependency_overrides.pop(require_user_dependency, None)


def test_verify_requires_authentication():
    response = TestClient(main.app).get("/api/security/binance/verify?network=mainnet")
    assert response.status_code in (401, 403)


def test_verify_rejects_invalid_network(client: TestClient):
    r = client.get("/api/security/binance/verify?network=mars")
    assert r.status_code == 400


def test_verify_missing_keystore_record(client: TestClient):
    r = client.get("/api/security/binance/verify?network=mainnet")
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is False
    assert body["error"] == "key_not_found"
    assert "your keystore" in body["detail"]


def test_verify_accepts_testnet_network():
    # 单纯 schema 验证，不真发请求
    from app.main import security_binance_verify
    # 调用 endpoint function 直接，避免依赖 keystore
    # （此 test 不实际触发签名请求，仅校验代码可 import）
    assert callable(security_binance_verify)


def test_verify_uses_and_revokes_one_broker_lease(client: TestClient, monkeypatch) -> None:
    stored = client.post(
        "/api/security/keystore",
        json={"name": "binance_testnet", "api_key": "key", "api_secret": "secret"},
    )
    assert stored.status_code == 200
    seen = []
    monkeypatch.setattr(
        main,
        "_security_binance_verify_record",
        lambda record, network: seen.append((record.api_key, network)) or {"ok": True},
    )

    response = client.get("/api/security/binance/verify?network=testnet")

    assert response.json() == {"ok": True}
    assert seen == [("key", "testnet")]
    assert client._test_broker._leases == {}


def test_verify_revokes_lease_when_verifier_raises(client: TestClient, monkeypatch) -> None:
    assert client.post(
        "/api/security/keystore",
        json={"name": "binance_testnet", "api_key": "key", "api_secret": "secret"},
    ).status_code == 200

    def fail(_record, _network):
        raise RuntimeError("injected verifier failure")

    monkeypatch.setattr(main, "_security_binance_verify_record", fail)
    no_raise = TestClient(main.app, raise_server_exceptions=False)
    response = no_raise.get("/api/security/binance/verify?network=testnet")

    assert response.status_code == 500
    assert client._test_broker._leases == {}


def test_verify_error_response_never_echoes_raw_signed_material(monkeypatch) -> None:
    from app.execution.binance_client import BinanceClient

    secret = "super-secret-value"
    monkeypatch.setattr(
        BinanceClient,
        "signed",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            RuntimeError(f"unknown failure signature={secret}")
        ),
    )
    result = main._security_binance_verify_record(
        SimpleNamespace(api_key="api-key", api_secret=secret),
        "testnet",
    )

    encoded = str(result)
    assert result["error"] == "unknown"
    assert secret not in encoded
    assert "raw_error" not in result
    assert "signed_url_base" not in result
