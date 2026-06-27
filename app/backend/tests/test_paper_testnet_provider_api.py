from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app import main
from app.auth import require_user_dependency
from app.paper import (
    BUNDLED_SAMPLE_SOURCE,
    TESTNET_REALTIME_SOURCE,
    TESTNET_UNAVAILABLE_SOURCE,
    make_binance_testnet_provider,
)
from app.security import InMemoryKeystore, KeystoreRecord, SecureKeystore


class _FakeBinanceClient:
    def __init__(self) -> None:
        self.public_calls: list[tuple[str, str, dict | None]] = []

    def assert_safe_startup(self) -> dict:
        return {"ok": True, "network": "testnet", "warnings": []}

    def public(self, method: str, path: str, params: dict | None = None):
        self.public_calls.append((method, path, params))
        if path.endswith("/klines"):
            return [[1710000000000, "100.0", "106.0", "99.0", "105.0", "123.4"]]
        if path.endswith("/premiumIndex"):
            return {"markPrice": "106.5"}
        return {"price": "106.5"}


class _FakePaperProvider:
    source = TESTNET_REALTIME_SOURCE

    def __init__(self, symbols: list[str]) -> None:
        self._symbols = symbols
        self._cursor = {symbol: 0 for symbol in symbols}

    def reset(self) -> None:
        for symbol in self._symbols:
            self._cursor[symbol] = 0

    def first_price(self, symbol: str) -> float:
        return 105.0

    def next_bar(self, symbol: str) -> dict:
        self._cursor[symbol] += 1
        close = 105.0 + self._cursor[symbol]
        return {
            "symbol": symbol,
            "open": close - 1,
            "high": close + 1,
            "low": close - 2,
            "close": close,
            "ts": f"fake-{self._cursor[symbol]}",
            "source": TESTNET_REALTIME_SOURCE,
        }

    def current_marks(self, symbols: list[str]) -> dict[str, float]:
        return {symbol: 106.0 for symbol in symbols}


@pytest.fixture
def client():
    main.app.dependency_overrides[require_user_dependency] = lambda: SimpleNamespace(
        user_id="tester", username="tester"
    )
    try:
        yield TestClient(main.app)
    finally:
        main.app.dependency_overrides.pop(require_user_dependency, None)


def test_testnet_provider_fetches_bar_and_mark_without_status_secret() -> None:
    store = SecureKeystore(InMemoryKeystore())
    store.store(KeystoreRecord(name="binance_testnet", api_key="AK_TEST", api_secret="SK_TEST"))
    fake = _FakeBinanceClient()

    provider, status = make_binance_testnet_provider(
        symbols=["BTCUSDT"],
        keystore=store,
        key_name="binance_testnet",
        client_factory=lambda _record, _product: fake,
    )

    assert provider is not None
    assert status["connected"] is True
    assert status["active_provider"] == TESTNET_REALTIME_SOURCE
    assert "AK_TEST" not in repr(status)
    assert "SK_TEST" not in repr(status)
    bar = provider.next_bar("BTCUSDT")
    assert bar is not None
    assert bar["source"] == TESTNET_REALTIME_SOURCE
    assert bar["close"] == pytest.approx(105.0)
    assert provider.current_marks(["BTCUSDT"])["BTCUSDT"] == pytest.approx(106.5)


def test_testnet_provider_missing_key_returns_fallback_status() -> None:
    store = SecureKeystore(InMemoryKeystore())

    provider, status = make_binance_testnet_provider(
        symbols=["BTCUSDT"],
        keystore=store,
        key_name="missing",
    )

    assert provider is None
    assert status["connected"] is False
    assert status["active_provider"] == TESTNET_UNAVAILABLE_SOURCE
    assert status["fallback_reason"] == "testnet_key_not_found"


def test_paper_run_testnet_request_without_key_falls_back_honestly(client) -> None:
    run_id = "testnet_missing_key_run"
    response = client.post(
        "/api/paper/runs",
        json={
            "run_id": run_id,
            "name": run_id,
            "market": "crypto",
            "symbols": ["BTCUSDT"],
            "bench": "BTC",
            "provider": "testnet",
            "testnet_keystore_name": "missing_key",
        },
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["run"]["simulated_source"] == BUNDLED_SAMPLE_SOURCE
    status = body["run"]["provider_status"]
    assert status["requested_provider"] == TESTNET_REALTIME_SOURCE
    assert status["connected"] is False
    assert status["fallback_reason"] == "testnet_key_not_found"


def test_paper_run_testnet_provider_override_feeds_testnet_source(client, monkeypatch) -> None:
    def _fake_factory(*, symbols, keystore, key_name, product="usdm_futures", interval="1m"):
        return _FakePaperProvider(list(symbols)), {
            "requested_provider": TESTNET_REALTIME_SOURCE,
            "active_provider": TESTNET_REALTIME_SOURCE,
            "connected": True,
            "credential_configured": True,
            "permission_checked": True,
        }

    monkeypatch.setattr(main, "make_binance_testnet_provider", _fake_factory)
    run_id = "testnet_fake_provider_run"
    response = client.post(
        "/api/paper/runs",
        json={
            "run_id": run_id,
            "name": run_id,
            "market": "crypto",
            "symbols": ["BTCUSDT"],
            "bench": "BTC",
            "provider": "testnet",
            "testnet_keystore_name": "configured_ref",
        },
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["run"]["simulated_source"] == TESTNET_REALTIME_SOURCE
    assert body["run"]["provider_status"]["connected"] is True
    assert body["register"]["bars_fed"] > 0
