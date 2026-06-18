"""v0.8.1 · copy_trade master + follower + signal relay。"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from app.auth import AuthService
from app.copy_trade import CopyTradeError, CopyTradeService, SignalRelayer
from app.copy_trade.beta import CopyTradeBetaService
from app.execution.base import OrderAck
from app.security import InMemoryKeystore, KeystoreRecord, SecureKeystore


@pytest.fixture()
def auth(tmp_path: Path) -> AuthService:
    return AuthService(tmp_path / "c.db")


@pytest.fixture()
def ct(tmp_path: Path) -> CopyTradeService:
    return CopyTradeService(tmp_path / "c.db")


@pytest.fixture()
def keystore() -> SecureKeystore:
    ks = SecureKeystore(InMemoryKeystore())
    ks.store(KeystoreRecord(name="follower_btc", api_key="K", api_secret="S", note="follower test"))
    return ks


# ---- Master ----

def test_register_master(auth: AuthService, ct: CopyTradeService) -> None:
    u = auth.register("alice", "passw0rd")
    m = ct.register_master(u.user_id, "Alice 阿尔法", asset_class="crypto_perp", profit_share_pct=0.15)
    assert m.master_id.startswith("master-")
    assert m.user_id == u.user_id
    assert m.profit_share_pct == 0.15
    assert m.is_invite_only is False
    assert m.invite_code == ""


def test_register_master_invite_only_generates_code(auth: AuthService, ct: CopyTradeService) -> None:
    u = auth.register("alice", "passw0rd")
    m = ct.register_master(u.user_id, "Alice", is_invite_only=True)
    assert m.is_invite_only is True
    assert len(m.invite_code) > 8


def test_register_master_validates(auth: AuthService, ct: CopyTradeService) -> None:
    u = auth.register("alice", "passw0rd")
    with pytest.raises(CopyTradeError):
        ct.register_master(u.user_id, "x", asset_class="commodity")
    with pytest.raises(CopyTradeError):
        ct.register_master(u.user_id, "x", profit_share_pct=0.99)


def test_register_master_one_per_user(auth: AuthService, ct: CopyTradeService) -> None:
    u = auth.register("alice", "passw0rd")
    ct.register_master(u.user_id, "Alice")
    with pytest.raises(CopyTradeError, match="已经是 master"):
        ct.register_master(u.user_id, "Alice2")


def test_update_master_only_by_owner(auth: AuthService, ct: CopyTradeService) -> None:
    a = auth.register("alice", "passw0rd")
    b = auth.register("bob", "passw0rd")
    m = ct.register_master(a.user_id, "Alice")
    with pytest.raises(PermissionError):
        ct.update_master(m.master_id, b.user_id, description="hack")
    ct.update_master(m.master_id, a.user_id, description="updated")
    refreshed = ct.get_master(m.master_id)
    assert refreshed and refreshed.description == "updated"


def test_rotate_invite_code(auth: AuthService, ct: CopyTradeService) -> None:
    u = auth.register("alice", "passw0rd")
    m = ct.register_master(u.user_id, "Alice", is_invite_only=True)
    original = m.invite_code
    new_code = ct.rotate_invite_code(m.master_id, u.user_id)
    assert new_code != original
    refreshed = ct.get_master(m.master_id)
    assert refreshed and refreshed.invite_code == new_code


def test_list_masters_by_followers(auth: AuthService, ct: CopyTradeService) -> None:
    a = auth.register("alice", "passw0rd")
    b = auth.register("bob", "passw0rd")
    c = auth.register("carol", "passw0rd")
    m_a = ct.register_master(a.user_id, "A")
    m_b = ct.register_master(b.user_id, "B")
    # B 收 2 个 follower，A 收 1 个
    ct.subscribe(c.user_id, m_b.master_id, invest_amount=100, binance_keystore_name="x")
    ct.subscribe(a.user_id, m_b.master_id, invest_amount=100, binance_keystore_name="y")
    ct.subscribe(c.user_id, m_a.master_id, invest_amount=100, binance_keystore_name="z")
    top = ct.list_masters(sort_by="followers")
    assert top[0].master_id == m_b.master_id


# ---- Subscribe / 私域 ----

def test_subscribe_basic(auth: AuthService, ct: CopyTradeService) -> None:
    a = auth.register("alice", "passw0rd")
    b = auth.register("bob", "passw0rd")
    m = ct.register_master(a.user_id, "A")
    f = ct.subscribe(b.user_id, m.master_id, invest_amount=200, binance_keystore_name="bob_binance")
    assert f.follower_id == f"{b.user_id}::{m.master_id}"
    assert f.status == "active"
    refreshed = ct.get_master(m.master_id)
    assert refreshed and refreshed.follower_count == 1


def test_subscribe_self_rejected(auth: AuthService, ct: CopyTradeService) -> None:
    a = auth.register("alice", "passw0rd")
    m = ct.register_master(a.user_id, "A")
    with pytest.raises(CopyTradeError, match="跟单自己"):
        ct.subscribe(a.user_id, m.master_id, invest_amount=100, binance_keystore_name="x")


def test_subscribe_invite_only_requires_redeem(auth: AuthService, ct: CopyTradeService) -> None:
    a = auth.register("alice", "passw0rd")
    b = auth.register("bob", "passw0rd")
    m = ct.register_master(a.user_id, "A", is_invite_only=True)
    with pytest.raises(CopyTradeError, match="私域"):
        ct.subscribe(b.user_id, m.master_id, invest_amount=100, binance_keystore_name="x")
    # 错的 code
    with pytest.raises(CopyTradeError, match="invite_code"):
        ct.redeem_invite(b.user_id, m.master_id, "WRONG")
    # 对的 code
    assert ct.redeem_invite(b.user_id, m.master_id, m.invite_code)
    f = ct.subscribe(b.user_id, m.master_id, invest_amount=100, binance_keystore_name="x")
    assert f.status == "active"


def test_subscribe_requires_keystore_name(auth: AuthService, ct: CopyTradeService) -> None:
    a = auth.register("alice", "passw0rd")
    b = auth.register("bob", "passw0rd")
    m = ct.register_master(a.user_id, "A")
    with pytest.raises(CopyTradeError, match="keystore"):
        ct.subscribe(b.user_id, m.master_id, invest_amount=100, binance_keystore_name="")


def test_unsubscribe_drops_follower_count(auth: AuthService, ct: CopyTradeService) -> None:
    a = auth.register("alice", "passw0rd")
    b = auth.register("bob", "passw0rd")
    m = ct.register_master(a.user_id, "A")
    ct.subscribe(b.user_id, m.master_id, invest_amount=100, binance_keystore_name="x")
    assert ct.unsubscribe(b.user_id, m.master_id)
    refreshed = ct.get_master(m.master_id)
    assert refreshed and refreshed.follower_count == 0


def test_pause_subscription(auth: AuthService, ct: CopyTradeService) -> None:
    a = auth.register("alice", "passw0rd")
    b = auth.register("bob", "passw0rd")
    m = ct.register_master(a.user_id, "A")
    ct.subscribe(b.user_id, m.master_id, invest_amount=100, binance_keystore_name="x")
    assert ct.pause_subscription(b.user_id, m.master_id, paused=True)
    active = ct.list_followers(m.master_id, active_only=True)
    assert len(active) == 0
    all_followers = ct.list_followers(m.master_id, active_only=False)
    assert len(all_followers) == 1 and all_followers[0].status == "paused"


# ---- Signal ----

def test_publish_signal(auth: AuthService, ct: CopyTradeService) -> None:
    a = auth.register("alice", "passw0rd")
    m = ct.register_master(a.user_id, "A")
    sig = ct.publish_signal(
        m.master_id, a.user_id,
        symbol="BTCUSDT", side="buy", quantity=0.5, price=30000, order_type="limit",
    )
    assert sig.symbol == "BTCUSDT" and sig.status == "live"
    refreshed = ct.get_master(m.master_id)
    assert refreshed and refreshed.total_signals == 1


def test_publish_signal_only_by_owner(auth: AuthService, ct: CopyTradeService) -> None:
    a = auth.register("alice", "passw0rd")
    b = auth.register("bob", "passw0rd")
    m = ct.register_master(a.user_id, "A")
    with pytest.raises(PermissionError):
        ct.publish_signal(m.master_id, b.user_id, symbol="BTCUSDT", side="buy", quantity=1)


def test_publish_signal_validates(auth: AuthService, ct: CopyTradeService) -> None:
    a = auth.register("alice", "passw0rd")
    m = ct.register_master(a.user_id, "A")
    with pytest.raises(CopyTradeError):
        ct.publish_signal(m.master_id, a.user_id, symbol="BTCUSDT", side="hold", quantity=1)  # type: ignore[arg-type]
    with pytest.raises(CopyTradeError):
        ct.publish_signal(m.master_id, a.user_id, symbol="BTC", side="buy", quantity=0)
    with pytest.raises(CopyTradeError):
        ct.publish_signal(m.master_id, a.user_id, symbol="BTC", side="buy", quantity=1, order_type="limit")  # 缺 price


def test_cancel_signal(auth: AuthService, ct: CopyTradeService) -> None:
    a = auth.register("alice", "passw0rd")
    m = ct.register_master(a.user_id, "A")
    sig = ct.publish_signal(m.master_id, a.user_id, symbol="BTC", side="buy", quantity=1)
    assert ct.cancel_signal(sig.signal_id, a.user_id)
    refreshed = ct.get_signal(sig.signal_id)
    assert refreshed and refreshed.status == "canceled"


# ---- Relay (mock venue) ----

def test_relay_signal_dispatches_to_active_followers(auth: AuthService, ct: CopyTradeService, keystore: SecureKeystore) -> None:
    a = auth.register("alice", "passw0rd")
    b = auth.register("bob", "passw0rd")
    c = auth.register("carol", "passw0rd")
    m = ct.register_master(a.user_id, "A")
    ct.subscribe(b.user_id, m.master_id, invest_amount=100, binance_keystore_name="follower_btc",
                  per_order_max_usdt=10_000_000)  # 高上限避免 risk 拒
    ct.subscribe(c.user_id, m.master_id, invest_amount=100, binance_keystore_name="follower_btc",
                  per_order_max_usdt=10_000_000)
    ct.pause_subscription(c.user_id, m.master_id, paused=True)
    sig = ct.publish_signal(m.master_id, a.user_id, symbol="BTCUSDT", side="buy", quantity=0.1, price=30000, order_type="limit")

    placed: list[str] = []
    def mock_venue_factory(follower, ks):
        v = MagicMock()
        v.name = "mock_binance"
        v.place_order = MagicMock(return_value=OrderAck(order_id=f"ord-{follower.user_id}", client_order_id="c", status="filled"))
        placed.append(follower.user_id)
        return v

    relayer = SignalRelayer(ct, keystore, mock_venue_factory)
    results = relayer.relay(sig)
    assert len(results) == 1  # 只有 bob (active)，carol 已 paused
    assert results[0]["follower_id"] == f"{b.user_id}::{m.master_id}"
    assert results[0]["status"] == "filled"
    assert placed == [b.user_id]
    # execution record
    execs = ct.list_executions(signal_id=sig.signal_id)
    assert len(execs) == 1 and execs[0].status == "filled"


def test_relay_skips_when_keystore_missing(auth: AuthService, ct: CopyTradeService, keystore: SecureKeystore) -> None:
    a = auth.register("alice", "passw0rd")
    b = auth.register("bob", "passw0rd")
    m = ct.register_master(a.user_id, "A")
    ct.subscribe(b.user_id, m.master_id, invest_amount=100, binance_keystore_name="never_set")
    sig = ct.publish_signal(m.master_id, a.user_id, symbol="BTCUSDT", side="buy", quantity=0.1)

    def mock_factory(follower, ks):
        return MagicMock()  # 不应该调到这里

    relayer = SignalRelayer(ct, keystore, mock_factory)
    results = relayer.relay(sig)
    assert results[0]["status"] == "skipped"
    assert results[0]["reason"] == "keystore_miss"
    execs = ct.list_executions(signal_id=sig.signal_id)
    assert execs[0].status == "skipped"


def test_relay_rejects_when_risk_fails(auth: AuthService, ct: CopyTradeService, keystore: SecureKeystore) -> None:
    a = auth.register("alice", "passw0rd")
    b = auth.register("bob", "passw0rd")
    m = ct.register_master(a.user_id, "A")
    ct.subscribe(b.user_id, m.master_id, invest_amount=100, binance_keystore_name="follower_btc",
                  per_order_max_usdt=10)  # 单笔上限 10 USDT
    sig = ct.publish_signal(m.master_id, a.user_id, symbol="BTCUSDT", side="buy",
                             quantity=1.0, price=30000, order_type="limit")  # 30000 USDT 远超上限

    def mock_factory(follower, ks):
        v = MagicMock()
        v.name = "mock_binance"
        return v

    relayer = SignalRelayer(ct, keystore, mock_factory)
    results = relayer.relay(sig)
    assert results[0]["status"] == "rejected"
    assert "单笔" in results[0]["reason"]


def test_relay_failed_when_venue_throws(auth: AuthService, ct: CopyTradeService, keystore: SecureKeystore) -> None:
    a = auth.register("alice", "passw0rd")
    b = auth.register("bob", "passw0rd")
    m = ct.register_master(a.user_id, "A")
    ct.subscribe(b.user_id, m.master_id, invest_amount=100, binance_keystore_name="follower_btc",
                  per_order_max_usdt=1_000_000)
    sig = ct.publish_signal(m.master_id, a.user_id, symbol="BTCUSDT", side="buy", quantity=0.1, price=100)

    def mock_factory(follower, ks):
        v = MagicMock()
        v.name = "mock"
        v.place_order = MagicMock(side_effect=RuntimeError("upstream 500"))
        return v

    relayer = SignalRelayer(ct, keystore, mock_factory)
    results = relayer.relay(sig)
    assert results[0]["status"] == "failed"
    execs = ct.list_executions(signal_id=sig.signal_id)
    assert execs[0].status == "failed"
    assert "500" in (execs[0].error or "")


# ---- v0.8.9 实盘安全护栏：幂等 + 杠杆硬截断（GOAL §8 M17） ----

def test_idempotency_blocks_duplicate(
    auth: AuthService, ct: CopyTradeService, keystore: SecureKeystore, tmp_path: Path
) -> None:
    """同一 signal 对同一 follower relay 两次：第二次绝不重复下单。"""
    beta = CopyTradeBetaService(tmp_path / "beta.db")
    a = auth.register("alice", "passw0rd")
    b = auth.register("bob", "passw0rd")
    m = ct.register_master(a.user_id, "A")
    ct.subscribe(b.user_id, m.master_id, invest_amount=100, binance_keystore_name="follower_btc",
                 per_order_max_usdt=10_000_000)
    sig = ct.publish_signal(m.master_id, a.user_id, symbol="BTCUSDT", side="buy",
                             quantity=0.1, price=30000, order_type="limit")

    place_mocks: list[MagicMock] = []

    def mock_factory(follower, ks):
        v = MagicMock()
        v.name = "mock"
        v.place_order = MagicMock(return_value=OrderAck(order_id="ord-1", client_order_id="c", status="filled"))
        place_mocks.append(v.place_order)
        return v

    relayer = SignalRelayer(ct, keystore, mock_factory, beta=beta)
    r1 = relayer.relay(sig)
    assert r1[0]["status"] == "filled"

    r2 = relayer.relay(sig)
    assert r2[0]["status"] == "skipped"
    assert r2[0]["reason"] == "duplicate"

    # venue.place_order 只被真正调用一次（第二次在幂等门处就短路，未建 venue）
    assert sum(pm.call_count for pm in place_mocks) == 1
    # dispatch 幂等表只有一条
    assert len(beta.list_dispatches(f"{b.user_id}::{m.master_id}")) == 1
    # 真实成交 execution 只有一条；第二次是 skipped
    execs = ct.list_executions(signal_id=sig.signal_id)
    assert len([e for e in execs if e.status == "filled"]) == 1
    assert any(e.status == "skipped" and "duplicate" in (e.error or "") for e in execs)


def test_leverage_cap_enforced(
    auth: AuthService, ct: CopyTradeService, keystore: SecureKeystore, tmp_path: Path
) -> None:
    """master 发 10x 信号，follower cap 2x → 实际下单杠杆被硬截断到 2x。"""
    beta = CopyTradeBetaService(tmp_path / "beta.db")
    a = auth.register("alice", "passw0rd")
    b = auth.register("bob", "passw0rd")
    m = ct.register_master(a.user_id, "A", asset_class="crypto_perp")
    ct.subscribe(b.user_id, m.master_id, invest_amount=100, binance_keystore_name="follower_btc",
                 per_order_max_usdt=10_000_000, max_leverage=2.0)
    sig = ct.publish_signal(m.master_id, a.user_id, symbol="BTCUSDT", side="buy",
                             quantity=0.1, price=30000, order_type="limit", leverage=10.0)

    captured: dict[str, float | None] = {}

    def mock_factory(follower, ks):
        v = MagicMock()
        v.name = "mock"

        def place(order):
            captured["leverage"] = order.leverage  # 落到 venue 的实际杠杆
            return OrderAck(order_id="ord-1", client_order_id="c", status="filled")

        v.place_order = MagicMock(side_effect=place)
        return v

    relayer = SignalRelayer(ct, keystore, mock_factory, beta=beta)
    results = relayer.relay(sig)
    assert results[0]["status"] == "filled"

    # 实际下单参数被截断到 follower 上限，而非 master 的 10x
    assert captured["leverage"] == 2.0
    assert results[0]["leverage_clamped"] is True

    # dispatch 审计：master 10x / applied 2x / clamped
    disp = beta.list_dispatches(f"{b.user_id}::{m.master_id}")
    assert len(disp) == 1
    assert disp[0].master_leverage == 10.0
    assert disp[0].follower_applied_leverage == 2.0
    assert disp[0].clamped is True
