"""LeasedBinanceVenue（INV-3 lease-唯一-key venue）的【对抗式】测试（T-022 / spine 06 §4）。

种已知坏门必抓：构造不持 key / 无 lease 下单 fail-closed / creds 只从 lease 现造 /
公共 mark 端点无需 key / 取价失败 fail-safe。
"""

from __future__ import annotations

import pytest

from app.execution.base import Order
from app.execution.binance_client import BinanceClient
from app.execution.leased_binance import LeasedBinanceVenue
from app.security import KeystoreRecord
from app.security.gate.broker import Lease


def _lease(api_key="K-LIVE", api_secret="S-LIVE"):
    rec = KeystoreRecord(name="follower_btc", api_key=api_key, api_secret=api_secret, note="t")
    return Lease("lease-test", rec)


# ── T1 · 构造时不持任何 key（移除 self-fetch）──────────────────────────────────────
def test_no_creds_at_construction():
    v = LeasedBinanceVenue(product="usdm_futures", network="mainnet")
    # 实例属性里不存在任何 api key/secret 字段（结构上装不下 key）
    blob = repr(vars(v))
    assert "api_key" not in blob and "api_secret" not in blob
    assert not hasattr(v, "_cred") and not hasattr(v, "_client")


# ── T2 · 无 lease 下单 → fail-closed（INV-3：无 lease=无 key=不下单）─────────────────
def test_place_order_without_lease_fail_closed():
    v = LeasedBinanceVenue(product="usdm_futures", network="mainnet")
    order = Order(venue="v", symbol="BTCUSDT", side="buy", quantity=0.001, price=100, leverage=2.0)
    with pytest.raises(PermissionError, match="lease"):
        v.place_order(order)                 # 无 lease
    with pytest.raises(PermissionError):
        v.get_position("BTCUSDT")            # 私有端点同样无 lease 不可用
    with pytest.raises(PermissionError):
        v.get_balance()


# ── T3 · creds 只从 lease 现造（key 此刻才现身）──────────────────────────────────────
def test_creds_built_from_lease_only():
    v = LeasedBinanceVenue(product="usdm_futures", network="mainnet")
    kernel = v._kernel(_lease(api_key="AK", api_secret="SK"))
    # 内核 client 的 creds 来自 lease.record，而非 venue 构造
    assert kernel._client._cred.api_key == "AK"
    assert kernel._client._cred.api_secret == "SK"
    assert kernel._client.network == "mainnet"


def test_spot_product_kernel():
    v = LeasedBinanceVenue(product="spot", network="testnet")
    kernel = v._kernel(_lease())
    assert kernel.name == "binance_spot"


# ── T4 · 公共 mark 端点无需 key（lease 之前就能核名义额，保 T-021 fix B）──────────────
def test_get_mark_price_keyless(monkeypatch):
    captured = {}
    def fake_public(self, method, path, params=None):
        captured["path"] = path
        return {"markPrice": "100.5"}
    monkeypatch.setattr(BinanceClient, "public", fake_public)
    v = LeasedBinanceVenue(product="usdm_futures", network="mainnet")
    assert v.get_mark_price("BTCUSDT") == 100.5
    assert "premiumIndex" in captured["path"]       # 公共 mark 端点


def test_get_mark_price_spot_ticker(monkeypatch):
    monkeypatch.setattr(BinanceClient, "public", lambda self, m, p, params=None: {"price": "42.0"})
    v = LeasedBinanceVenue(product="spot", network="mainnet")
    assert v.get_mark_price("BTCUSDT") == 42.0


# ── T5 · 取价失败 / 无价 → None（fail-safe，交给门 deny-by-default）──────────────────
def test_get_mark_price_failure_returns_none(monkeypatch):
    monkeypatch.setattr(BinanceClient, "public", lambda self, m, p, params=None: (_ for _ in ()).throw(RuntimeError("net")))
    v = LeasedBinanceVenue(product="usdm_futures", network="mainnet")
    assert v.get_mark_price("BTCUSDT") is None
    monkeypatch.setattr(BinanceClient, "public", lambda self, m, p, params=None: {"markPrice": "0"})
    assert v.get_mark_price("BTCUSDT") is None       # 0 → None


# ── T6 · place_order 带 lease → 委托内核（用 monkeypatch 避免真网络）──────────────────
def test_place_order_with_lease_delegates(monkeypatch):
    from unittest.mock import MagicMock
    from app.execution.base import OrderAck
    v = LeasedBinanceVenue(product="usdm_futures", network="mainnet")
    inner = MagicMock()
    inner.place_order = MagicMock(return_value=OrderAck(order_id="ok", client_order_id="c"))
    monkeypatch.setattr(v, "_kernel", lambda lease: inner)
    order = Order(venue="v", symbol="BTCUSDT", side="buy", quantity=0.001, price=100, leverage=2.0)
    ack = v.place_order(order, lease=_lease())
    assert ack.order_id == "ok"
    inner.place_order.assert_called_once_with(order)
