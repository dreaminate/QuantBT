from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest

from app.execution import BinanceUserDataStream, ExecutionReport, UserDataEvent
from app.execution.binance_client import BinanceClient, BinanceCredentials


def _client(product: str = "usdm_futures") -> BinanceClient:
    cred = BinanceCredentials(api_key="k", api_secret="s", network="testnet")
    return BinanceClient(cred, product=product, session=MagicMock())


def test_create_listen_key_futures(monkeypatch) -> None:
    client = _client(product="usdm_futures")
    monkeypatch.setattr(client, "signed", MagicMock(return_value={"listenKey": "abc123" * 10}))
    stream = BinanceUserDataStream(client)
    key = stream.create_listen_key()
    assert key.startswith("abc")
    assert stream.state.listen_key == key
    assert stream.state.last_renew_at_utc is not None


def test_create_listen_key_spot_uses_public(monkeypatch) -> None:
    client = _client(product="spot")
    monkeypatch.setattr(client, "public", MagicMock(return_value={"listenKey": "spot-key" * 5}))
    stream = BinanceUserDataStream(client)
    key = stream.create_listen_key()
    assert "spot-key" in key


def test_renew_listen_key_no_key_returns_false() -> None:
    stream = BinanceUserDataStream(_client())
    assert stream.renew_listen_key() is False


def test_renew_listen_key_updates_timestamp(monkeypatch) -> None:
    client = _client(product="usdm_futures")
    stream = BinanceUserDataStream(client)
    stream._state.listen_key = "fakekey-deadbeef"
    monkeypatch.setattr(client, "signed", MagicMock(return_value={}))
    assert stream.renew_listen_key()
    assert stream.state.last_renew_at_utc is not None


def test_on_message_dispatches_execution_report() -> None:
    captured: list[ExecutionReport] = []
    stream = BinanceUserDataStream(_client(), on_execution=captured.append)
    msg = json.dumps(
        {
            "e": "ORDER_TRADE_UPDATE",
            "o": {
                "i": 123,
                "s": "BTCUSDT",
                "S": "BUY",
                "X": "FILLED",
                "l": "0.5",
                "z": "0.5",
                "L": "30000",
                "n": "0.01",
                "N": "USDT",
            },
        }
    )
    stream._on_message(MagicMock(), msg)
    assert len(captured) == 1
    rep = captured[0]
    assert rep.order_id == "123"
    assert rep.symbol == "BTCUSDT"
    assert rep.side == "buy"
    assert rep.status == "filled"
    assert rep.cumulative_filled_qty == 0.5


def test_on_message_invalid_json_does_not_crash() -> None:
    stream = BinanceUserDataStream(_client())
    stream._on_message(MagicMock(), "not json")  # 不抛
    assert stream.state.last_message_at_utc is None  # 没被记录


def test_reconcile_detects_orphans(monkeypatch) -> None:
    client = _client(product="usdm_futures")
    stream = BinanceUserDataStream(client)
    # 远端只有 R1；本地只有 L1 + L2 → orphan_local 2 个 + orphan_remote 1 个
    monkeypatch.setattr(client, "signed", MagicMock(return_value=[{"orderId": "R1"}]))
    stream._open_orders_local = {"L1": {"status": "new"}, "L2": {"status": "new"}}
    diffs = stream.reconcile_once()
    sides = sorted(d["side"] for d in diffs)
    assert sides == ["orphan_local", "orphan_local", "orphan_remote"]
    # 对账后：本地 L1/L2 清掉，R1 加入
    assert "R1" in stream._open_orders_local
    assert "L1" not in stream._open_orders_local
    assert stream.state.reconcile_count == 1
    assert stream.state.orphan_count == 3


def test_snapshot_returns_safe_summary() -> None:
    stream = BinanceUserDataStream(_client())
    stream._state.listen_key = "deadbeef" * 4
    snap = stream.snapshot()
    assert snap["listen_key_prefix"] == "deadbeef"
    assert snap["connected"] is False


def test_close_listen_key_with_no_key_is_noop() -> None:
    stream = BinanceUserDataStream(_client())
    stream.close_listen_key()  # 不抛
