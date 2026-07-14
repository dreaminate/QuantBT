from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
import os
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from app.execution import Order, Position
from app.execution.binance_client import (
    BinanceClient,
    BinanceCredentials,
    BinanceWithdrawPermissionError,
)
from app.execution.binance_spot import BinanceSpotVenue, SymbolFilters
from app.execution.binance_um_futures import BinanceUMFuturesVenue, FuturesSymbolFilters
from app.risk import EquitySnapshot, KillSwitch, PreTradeError, RiskLimits, RiskMonitor
import app.security.keystore as keystore_module
from app.security import (
    InMemoryKeystore,
    KeystoreError,
    KeystoreRecord,
    SecureKeystore,
    open_runtime_keystore,
)


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


def test_keystore_fernet_file_is_private_and_concurrent_writes_are_not_lost(tmp_path: Path) -> None:
    path = tmp_path / "private" / "store.bin"

    def write(index: int) -> None:
        store = SecureKeystore.open(
            prefer="fernet_file",
            fernet_path=path,
            master_password="concurrent-master",
        )
        store.store(
            KeystoreRecord(
                name=f"record-{index}",
                api_key=f"key-{index}",
                api_secret=f"secret-{index}",
            )
        )

    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(write, range(8), timeout=20))

    restarted = SecureKeystore.open(
        prefer="fernet_file",
        fernet_path=path,
        master_password="concurrent-master",
    )
    assert restarted.list_names() == [f"record-{index}" for index in range(8)]
    assert path.parent.stat().st_mode & 0o777 == 0o700
    assert path.stat().st_mode & 0o777 == 0o600
    assert path.with_name(path.name + ".lock").stat().st_mode & 0o777 == 0o600


def test_keystore_fernet_failed_replace_preserves_old_disk_and_memory_state(
    tmp_path: Path,
    monkeypatch,
) -> None:
    path = tmp_path / "private" / "store.bin"
    store = SecureKeystore.open(
        prefer="fernet_file",
        fernet_path=path,
        master_password="atomic-master",
    )
    store.store(KeystoreRecord(name="stable", api_key="old-key", api_secret="old-secret"))
    original_replace = os.replace

    def fail_replace(_source, _target):
        raise OSError("injected replace failure")

    monkeypatch.setattr(os, "replace", fail_replace)
    with pytest.raises(OSError, match="replace failure"):
        store.store(KeystoreRecord(name="stable", api_key="new-key", api_secret="new-secret"))
    monkeypatch.setattr(os, "replace", original_replace)

    assert store.fetch("stable").api_secret == "old-secret"
    restarted = SecureKeystore.open(
        prefer="fernet_file",
        fernet_path=path,
        master_password="atomic-master",
    )
    assert restarted.fetch("stable").api_key == "old-key"


def test_runtime_keystore_selection_is_explicit_and_never_falls_back(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("QUANTBT_KEYSTORE_BACKEND", "memory")
    monkeypatch.setenv("QUANTBT_RUNTIME_MODE", "production")
    with pytest.raises(KeystoreError, match="test or development"):
        open_runtime_keystore(tmp_path)

    monkeypatch.setenv("QUANTBT_RUNTIME_MODE", "test")
    assert open_runtime_keystore(tmp_path).backend_name == "memory"

    monkeypatch.setenv("QUANTBT_KEYSTORE_BACKEND", "keyring")
    monkeypatch.setattr(
        keystore_module,
        "KeyringBackend",
        lambda **_kwargs: (_ for _ in ()).throw(RuntimeError("no keyring")),
    )
    with pytest.raises(KeystoreError, match="unavailable"):
        open_runtime_keystore(tmp_path)


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
    client = _client(network="mainnet", session=session)
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
        "enableReading": True,
        "enableWithdrawals": False,
        "enableInternalTransfer": False,
        "permitsUniversalTransfer": False,
        "enableSpotAndMarginTrading": True,
    }
    perms_resp.raise_for_status.return_value = None

    def side_effect(method, url, **_):
        return time_resp if "time" in url else perms_resp

    session.request.side_effect = side_effect
    session.get.return_value = time_resp
    client = _client(network="mainnet", session=session)
    info = client.assert_safe_startup()
    assert info["ok"]
    assert info["network"] == "mainnet"
    request_url = session.request.call_args.args[1]
    assert request_url == "https://api.binance.com/sapi/v1/account/apiRestrictions"


def test_binance_client_testnet_permission_check_fails_closed_without_undocumented_endpoint() -> None:
    client = _client(product="usdm_futures", network="testnet")
    with pytest.raises(PermissionError, match="no documented API-key permission endpoint"):
        client.assert_safe_startup()
    client._http.request.assert_not_called()


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


def test_binance_um_execution_reports_are_source_identified_and_cumulative(monkeypatch) -> None:
    client = _client(product="usdm_futures")

    def signed(_method, path, _params):
        if path == "/fapi/v1/order":
            return {
                "orderId": 77,
                "clientOrderId": "client-77",
                "symbol": "BTCUSDT",
                "origQty": "0.01",
                "executedQty": "0.01",
                "side": "BUY",
                "status": "FILLED",
                "updateTime": 1_700_000_001_000,
            }
        if path == "/fapi/v1/userTrades":
            return [
                {
                    "id": 2,
                    "orderId": 77,
                    "qty": "0.006",
                    "price": "10010",
                    "commission": "0.02",
                    "commissionAsset": "USDT",
                    "realizedPnl": "-0.25",
                    "time": 1_700_000_001_000,
                },
                {
                    "id": 1,
                    "orderId": 77,
                    "qty": "0.004",
                    "price": "10000",
                    "commission": "0.01",
                    "commissionAsset": "USDT",
                    "realizedPnl": "0",
                    "time": 1_700_000_000_000,
                },
            ]
        raise AssertionError(path)

    monkeypatch.setattr(client, "signed", signed)
    reports = BinanceUMFuturesVenue(client).execution_reports_for_order(
        "BTCUSDT",
        order_id="77",
        client_order_id="client-77",
    )

    assert [report.status for report in reports] == ["partially_filled", "filled"]
    assert [report.cumulative_filled_qty for report in reports] == [0.004, 0.01]
    assert all(report.client_order_id == "client-77" for report in reports)
    assert len({report.source_event_ref for report in reports}) == 2
    assert all(report.raw_event_hash.startswith("sha256:") for report in reports)
    assert [report.realized_pnl_delta for report in reports] == [0.0, -0.25]
    assert all(report.realized_pnl_complete for report in reports)


def test_binance_um_zero_fill_canceled_order_has_terminal_observation(monkeypatch) -> None:
    client = _client(product="usdm_futures")

    def signed(_method, path, _params):
        if path == "/fapi/v1/order":
            return {
                "orderId": 88,
                "clientOrderId": "client-88",
                "symbol": "BTCUSDT",
                "origQty": "0.01",
                "executedQty": "0",
                "side": "BUY",
                "status": "CANCELED",
                "updateTime": 1_700_000_002_000,
            }
        if path == "/fapi/v1/userTrades":
            return []
        raise AssertionError(path)

    monkeypatch.setattr(client, "signed", signed)
    observation, reports = BinanceUMFuturesVenue(client).execution_bundle_for_order(
        "BTCUSDT",
        order_id="88",
        client_order_id="client-88",
    )

    assert reports == []
    assert observation.status == "canceled"
    assert observation.cumulative_filled_qty == 0
    assert observation.source_event_ref.startswith("binance_order_observation_")
    assert observation.raw_event_hash.startswith("sha256:")


def test_binance_um_order_observation_rejects_trade_sum_mismatch(monkeypatch) -> None:
    client = _client(product="usdm_futures")

    def signed(_method, path, _params):
        if path == "/fapi/v1/order":
            return {
                "orderId": 89,
                "clientOrderId": "client-89",
                "symbol": "BTCUSDT",
                "origQty": "0.01",
                "executedQty": "0.006",
                "side": "BUY",
                "status": "CANCELED",
                "updateTime": 1_700_000_003_000,
            }
        if path == "/fapi/v1/userTrades":
            return [
                {
                    "id": 1,
                    "orderId": 89,
                    "qty": "0.004",
                    "price": "10000",
                    "commission": "0.01",
                    "commissionAsset": "USDT",
                    "realizedPnl": "0",
                    "time": 1_700_000_002_000,
                }
            ]
        raise AssertionError(path)

    monkeypatch.setattr(client, "signed", signed)
    with pytest.raises(ValueError, match="do not cover the authoritative executed quantity"):
        BinanceUMFuturesVenue(client).execution_bundle_for_order(
            "BTCUSDT",
            order_id="89",
            client_order_id="client-89",
        )


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


def test_risk_monitor_readiness_requires_fresh_source_bound_snapshot() -> None:
    assert RiskMonitor(RiskLimits(), get_equity=lambda: 1000.0).active is False
    stale = EquitySnapshot(
        equity=1000.0,
        observed_at_utc=(datetime.now(UTC) - timedelta(minutes=5)).isoformat(),
        source_ref="account:test",
    )
    assert RiskMonitor(RiskLimits(), get_equity=lambda: stale, max_snapshot_age_s=30).active is False
    fresh = EquitySnapshot(
        equity=1000.0,
        observed_at_utc=datetime.now(UTC).isoformat(),
        source_ref="account:test",
    )
    assert RiskMonitor(RiskLimits(), get_equity=lambda: fresh).active is True


def test_risk_monitor_initializes_daily_drawdown_baseline_on_first_pretrade() -> None:
    snapshot = EquitySnapshot(
        equity=1234.0,
        observed_at_utc=datetime.now(UTC).isoformat(),
        source_ref="account:test",
    )
    monitor = RiskMonitor(RiskLimits(), get_equity=lambda: snapshot)
    monitor.pre_trade(Order(venue="paper", symbol="BTC", side="buy", quantity=1, price=1))
    assert monitor.state.starting_equity == 1234.0


def test_kill_switch_calls_cancel_all_and_close_positions() -> None:
    venue = MagicMock()
    venue.name = "v1"
    venue.emergency_cancel_all.return_value = {
        "ok": True,
        "verified_noop": False,
        "actions": [{"order_id": "1"}],
        "error": None,
    }
    position = Position(symbol="BTCUSDT", quantity=0.1)
    venue.list_open_positions.return_value = [position]
    venue.close_open_position.return_value = {"closed": True}
    venue.verify_emergency_flat.return_value = {
        "ok": True,
        "normal_open_order_refs": [],
        "algo_open_order_refs": [],
        "open_positions": [],
    }
    ks = KillSwitch([venue])
    results = ks.trigger()
    assert "v1" in results
    assert results["v1"]["ok"] is True
    venue.emergency_cancel_all.assert_called_once()
    venue.list_open_positions.assert_called_once()
    venue.close_open_position.assert_called_once_with(position)
    venue.verify_emergency_flat.assert_called_once_with(close_positions=True)


def test_futures_emergency_contract_discovers_and_reduce_only_closes_without_network() -> None:
    client = _client(product="usdm_futures")
    position_reads = 0

    def signed(method, path, params):
        nonlocal position_reads
        if path == "/fapi/v1/positionSide/dual":
            return {"dualSidePosition": False}
        if path == "/fapi/v2/account":
            return {"canTrade": True, "multiAssetsMargin": False}
        if path == "/fapi/v2/positionRisk":
            position_reads += 1
            if position_reads > 1:
                return []
            return [
                {
                    "symbol": "BTCUSDT",
                    "positionSide": "BOTH",
                    "positionAmt": "0.25",
                    "entryPrice": "100",
                    "markPrice": "101",
                    "unRealizedProfit": "0.25",
                    "leverage": "2",
                },
                {"symbol": "ETHUSDT", "positionSide": "BOTH", "positionAmt": "0"},
            ]
        if path == "/fapi/v1/order":
            assert method == "POST"
            return {
                "orderId": 7,
                "clientOrderId": params["newClientOrderId"],
                "symbol": "BTCUSDT",
                "side": "SELL",
                "type": "MARKET",
                "positionSide": "BOTH",
                "reduceOnly": True,
                "closePosition": False,
                "status": "FILLED",
                "origQty": "0.25",
                "executedQty": "0.25",
                "updateTime": 1_800_000_000_000,
            }
        raise AssertionError(path)

    client.signed = MagicMock(side_effect=signed)
    venue = BinanceUMFuturesVenue(client)
    positions = venue.list_open_positions()
    assert [(position.symbol, position.quantity) for position in positions] == [("BTCUSDT", 0.25)]
    venue.close_open_position(positions[0])
    method, path, params = next(
        call.args for call in client.signed.call_args_list if call.args[1] == "/fapi/v1/order"
    )
    assert (method, path) == ("POST", "/fapi/v1/order")
    assert params["side"] == "SELL"
    assert params["quantity"] == 0.25
    assert params["reduceOnly"] == "true"
    assert params["positionSide"] == "BOTH"
    assert params["newOrderRespType"] == "RESULT"
    assert "closePosition" not in params


def test_futures_execution_snapshot_uses_margin_balance_not_wallet_balance() -> None:
    client = _client(product="usdm_futures")
    client.assert_safe_startup = MagicMock(
        return_value={
            "permission_state": {"enableFutures": True, "enableWithdrawals": False},
            "ip_restricted": True,
            "warnings": [],
        }
    )

    def signed(_method, path, _params):
        if path == "/fapi/v1/positionSide/dual":
            return {"dualSidePosition": False}
        if path == "/fapi/v2/account":
            return {
                "canTrade": True,
                "multiAssetsMargin": False,
                "totalMarginBalance": "1050.0",
                "totalWalletBalance": "1000.0",
            }
        if path == "/fapi/v2/balance":
            return [
                {"accountAlias": "venue-account-123", "asset": "USDT", "balance": "1000.0"},
                {"accountAlias": "venue-account-123", "asset": "USDC", "balance": "50.0"},
            ]
        if path == "/fapi/v2/positionRisk":
            return []
        if path == "/fapi/v1/commissionRate":
            return {"makerCommissionRate": "0.0002", "takerCommissionRate": "0.0004"}
        raise AssertionError(path)

    client.signed = MagicMock(side_effect=signed)

    def public(_method, path, _params):
        if path == "/fapi/v1/premiumIndex":
            return {"markPrice": "100", "lastFundingRate": "0.0001"}
        if path == "/fapi/v1/ticker/bookTicker":
            return {"bidPrice": "99", "askPrice": "101"}
        raise AssertionError(path)

    client.public = MagicMock(side_effect=public)
    snapshot = BinanceUMFuturesVenue(client).execution_account_snapshot("BTCUSDT")
    assert snapshot["equity"] == 1050.0
    assert snapshot["account_uid"] == "venue-account-123"
    assert snapshot["account_identity_source"] == "fapi_v2_balance.accountAlias"
    assert snapshot["position_mode"] == "one_way"


def test_futures_execution_snapshot_rejects_hedge_mode() -> None:
    client = _client(product="usdm_futures")
    client.assert_safe_startup = MagicMock(return_value={})
    client.signed = MagicMock(return_value={"dualSidePosition": True})

    with pytest.raises(PermissionError, match="Hedge Mode"):
        BinanceUMFuturesVenue(client).execution_account_snapshot("BTCUSDT")
    assert client.signed.call_args.args[1] == "/fapi/v1/positionSide/dual"


def test_futures_execution_snapshot_rejects_inconsistent_account_aliases() -> None:
    client = _client(product="usdm_futures")
    client.assert_safe_startup = MagicMock(return_value={})

    def signed(_method, path, _params):
        if path == "/fapi/v1/positionSide/dual":
            return {"dualSidePosition": False}
        if path == "/fapi/v2/account":
            return {
                "canTrade": True,
                "multiAssetsMargin": False,
                "totalMarginBalance": "1",
            }
        if path == "/fapi/v2/balance":
            return [
                {"accountAlias": "alias-a", "asset": "USDT"},
                {"accountAlias": "alias-b", "asset": "USDC"},
            ]
        raise AssertionError(path)

    client.signed = MagicMock(side_effect=signed)
    with pytest.raises(ValueError, match="one consistent accountAlias"):
        BinanceUMFuturesVenue(client).execution_account_snapshot("BTCUSDT")


def test_spot_venue_without_position_mapping_cannot_report_killswitch_success() -> None:
    client = _client(product="spot")
    client.signed = MagicMock(return_value=[])
    result = KillSwitch([BinanceSpotVenue(client)]).trigger()["binance_spot"]
    assert result["cancel"]["verified_noop"] is True
    assert result["position_discovery"]["ok"] is False
    assert result["ok"] is False
