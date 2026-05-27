from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from app.execution import Order
from app.execution.binance_client import (
    BinanceClient,
    BinanceCredentials,
    BinanceWithdrawPermissionError,
)
from app.execution.binance_spot import BinanceSpotVenue, SymbolFilters
from app.execution.binance_um_futures import BinanceUMFuturesVenue, FuturesSymbolFilters
from app.risk import KillSwitch, PreTradeError, RiskLimits, RiskMonitor
from app.security import InMemoryKeystore, KeystoreError, KeystoreRecord, SecureKeystore


def _client(product: str = "spot", network: str = "testnet", session: MagicMock | None = None) -> BinanceClient:
    cred = BinanceCredentials(api_key="k", api_secret="s", network=network)  # type: ignore[arg-type]
    return BinanceClient(cred, product=product, session=session or MagicMock())  # type: ignore[arg-type]


def test_keystore_inmemory_round_trip() -> None:
    ks = SecureKeystore(InMemoryKeystore())
    ks.store(KeystoreRecord(name="binance_testnet", api_key="A" * 10, api_secret="B" * 10, note="ci"))
    rec = ks.fetch("binance_testnet")
    assert rec.api_secret == "B" * 10
    assert "binance_testnet" in ks.list_names()
    ks.delete("binance_testnet")
    with pytest.raises(KeystoreError):
        ks.fetch("binance_testnet")


def test_keystore_fernet_file_persistence(tmp_path: Path) -> None:
    ks = SecureKeystore.open(prefer="fernet_file", fernet_path=tmp_path / "store.bin", master_password="hunter2-strong")
    ks.store(KeystoreRecord(name="x", api_key="k", api_secret="s"))
    ks2 = SecureKeystore.open(prefer="fernet_file", fernet_path=tmp_path / "store.bin", master_password="hunter2-strong")
    assert ks2.fetch("x").api_secret == "s"


def test_keystore_fernet_file_wrong_password(tmp_path: Path) -> None:
    ks = SecureKeystore.open(prefer="fernet_file", fernet_path=tmp_path / "store.bin", master_password="right")
    ks.store(KeystoreRecord(name="x", api_key="k", api_secret="s"))
    with pytest.raises(Exception):  # cryptography.fernet.InvalidToken or similar
        SecureKeystore.open(prefer="fernet_file", fernet_path=tmp_path / "store.bin", master_password="wrong")


def test_binance_client_assert_safe_startup_blocks_withdraw() -> None:
    session = MagicMock()
    time_resp = MagicMock()
    time_resp.json.return_value = {"serverTime": 1_700_000_000_000}
    time_resp.raise_for_status.return_value = None
    perms_resp = MagicMock()
    perms_resp.status_code = 200
    perms_resp.json.return_value = {
        "ipRestrict": True,
        "enableWithdrawals": True,  # 危险
        "enableSpotAndMarginTrading": True,
    }
    perms_resp.raise_for_status.return_value = None

    def side_effect(method, url, **_):
        if "time" in url:
            return time_resp
        return perms_resp

    session.request.side_effect = side_effect
    session.get.return_value = time_resp
    client = _client(session=session)
    with pytest.raises(BinanceWithdrawPermissionError):
        client.assert_safe_startup()


def test_binance_client_assert_safe_startup_passes_when_no_withdraw() -> None:
    session = MagicMock()
    time_resp = MagicMock()
    time_resp.json.return_value = {"serverTime": 1_700_000_000_000}
    time_resp.raise_for_status.return_value = None
    perms_resp = MagicMock()
    perms_resp.status_code = 200
    perms_resp.json.return_value = {
        "ipRestrict": True,
        "enableWithdrawals": False,
        "enableSpotAndMarginTrading": True,
    }
    perms_resp.raise_for_status.return_value = None

    def side_effect(method, url, **_):
        return time_resp if "time" in url else perms_resp

    session.request.side_effect = side_effect
    session.get.return_value = time_resp
    client = _client(session=session)
    info = client.assert_safe_startup()
    assert info["ok"]
    assert info["network"] == "testnet"


def test_binance_spot_venue_quantizes_and_signs_order() -> None:
    session = MagicMock()
    place_resp = MagicMock()
    place_resp.json.return_value = {"orderId": 123, "status": "NEW"}
    place_resp.raise_for_status.return_value = None
    place_resp.status_code = 200
    session.request.return_value = place_resp
    client = _client(product="spot", session=session)
    venue = BinanceSpotVenue(client)
    venue._filters["BTCUSDT"] = SymbolFilters(min_qty=0.001, step_size=0.001, tick_size=0.01, min_notional=10.0)
    ack = venue.place_order(Order(venue="binance_spot", symbol="BTCUSDT", side="buy", quantity=0.00123, order_type="limit", price=10000.567))
    assert ack.order_id == "123"
    sent_params = session.request.call_args.kwargs.get("params") or session.request.call_args.kwargs.get("data")
    assert sent_params["quantity"] == 0.001  # quantized down
    assert sent_params["price"] == 10000.56  # quantized down


def test_binance_um_futures_quantize_and_leverage_guard() -> None:
    with pytest.raises(ValueError, match="20x"):
        BinanceUMFuturesVenue(_client(product="usdm_futures"), max_leverage=25)
    venue = BinanceUMFuturesVenue(_client(product="usdm_futures"), max_leverage=5)
    with pytest.raises(ValueError, match="leverage"):
        venue.configure_symbol("BTCUSDT", leverage=10)


def test_risk_monitor_pre_trade_rejects_blacklist() -> None:
    rm = RiskMonitor(RiskLimits(blacklist_symbols=("LUNA",)))
    with pytest.raises(PreTradeError, match="黑名单"):
        rm.pre_trade(Order(venue="binance_spot", symbol="LUNA", side="buy", quantity=1, order_type="market"))


def test_risk_monitor_pre_trade_rejects_overnotional() -> None:
    rm = RiskMonitor(RiskLimits(per_order_max_usdt=50))
    with pytest.raises(PreTradeError, match="单笔名义"):
        rm.pre_trade(Order(venue="binance_spot", symbol="BTC", side="buy", quantity=1, price=100, order_type="limit"))


def test_risk_monitor_pauses_after_daily_loss(monkeypatch) -> None:
    rm = RiskMonitor(RiskLimits(daily_loss_limit_pct=0.01), get_equity=lambda: 10_000)
    rm._state.starting_equity = 10_000
    rm.on_fill(realized_pnl_delta=-150)
    assert rm.paused
    assert any("PAUSE" in a["message"] for a in rm.alerts())


def test_risk_monitor_caps_daily_order_count() -> None:
    rm = RiskMonitor(RiskLimits(daily_order_count_max=2))
    o = Order(venue="binance_spot", symbol="BTC", side="buy", quantity=0.001, price=1, order_type="limit")
    rm.pre_trade(o)
    rm.on_fill()
    rm.pre_trade(o)
    rm.on_fill()
    with pytest.raises(PreTradeError):
        rm.pre_trade(o)


def test_kill_switch_calls_cancel_all_and_close_positions() -> None:
    venue = MagicMock()
    venue.name = "v1"
    venue.cancel_all_open.return_value = [{"order_id": "1"}]
    venue.get_balance.return_value = {"BTC": MagicMock(asset="BTC")}
    venue.close_position.return_value = {"closed": True}
    ks = KillSwitch([venue])
    results = ks.trigger()
    assert "v1" in results
    venue.cancel_all_open.assert_called_once()
    venue.close_position.assert_called()
