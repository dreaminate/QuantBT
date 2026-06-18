"""copy_trade relay 接 OrderGuard 的【对抗式】测试（T-021 / spine 06 §4/§5）。

种已知坏门必抓：
  T1 M17 命门·杠杆不被中继绕过（relay 截断 + 直连注入都被夹）/ T2 deny-by-default 白名单 /
  T3 单笔名义额上限（门内二次防线）/ T4 真钱档 nonce 台缺失→fail-closed / T5 真钱档防重放 /
  T6 testnet fail-open（依赖缺失仍评估、不硬阻）/ T7 门拒时 venue.place_order 绝不被调（key 永不用）/
  T8 向后兼容（enforce_gate=False 不接门）/ T9 四路径同一门（同违规同判）。
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from app.auth import AuthService
from app.copy_trade import CopyTradeService, SignalRelayer
from app.copy_trade.beta import CopyTradeBetaService
from app.copy_trade.gate_binding import follower_gate, follower_tier
from app.execution.base import Order, OrderAck
from app.security import InMemoryKeystore, KeystoreRecord, SecureKeystore
from app.security.gate.enforcer import OrderGuard
from app.security.gate.nonce import NonceLedger
from app.security.gate.policy import OrderGated, TrustTier, evaluate


@pytest.fixture()
def auth(tmp_path: Path) -> AuthService:
    return AuthService(tmp_path / "c.db")


@pytest.fixture()
def ct(tmp_path: Path) -> CopyTradeService:
    return CopyTradeService(tmp_path / "c.db")


@pytest.fixture()
def keystore() -> SecureKeystore:
    ks = SecureKeystore(InMemoryKeystore())
    ks.store(KeystoreRecord(name="follower_btc", api_key="K", api_secret="S", note="t"))
    return ks


def _recording_factory(captured: list, *, mark: float | None = None):
    def factory(follower, ks):
        v = MagicMock()
        v.name = "mock_binance"
        def _place(order, **kw):
            captured.append(order)
            return OrderAck(order_id="ord-1", client_order_id="c", status="filled")
        v.place_order = MagicMock(side_effect=_place)
        # 可信 mark：市价单名义额核验入参来源（venue 侧，T-022 起走 lease-free 公共端点 get_mark_price）。
        # None → 取不到 mark → _trusted_mark 返 None → 门 notional_unverifiable。
        v.get_mark_price = MagicMock(return_value=mark)
        return v
    return factory


def _setup(auth, ct, *, network="testnet", max_leverage=None, per_order_max_usdt=100.0,
           asset_class="crypto_perp"):
    a = auth.register("alice", "passw0rd")
    b = auth.register("bob", "passw0rd")
    m = ct.register_master(a.user_id, "A", asset_class=asset_class)
    ct.subscribe(b.user_id, m.master_id, invest_amount=1000, binance_keystore_name="follower_btc",
                 binance_network=network, max_leverage=max_leverage, per_order_max_usdt=per_order_max_usdt)
    return a, b, m


# ── T1 · M17 命门：杠杆上限不被中继绕过（relay 截断 + 直连注入都被夹）────────────────
def test_m17_relay_clamps_leverage(auth, ct, keystore, tmp_path):
    a, b, m = _setup(auth, ct, network="testnet", max_leverage=2.0, per_order_max_usdt=1e9)
    sig = ct.publish_signal(m.master_id, a.user_id, symbol="BTCUSDT", side="buy",
                            quantity=0.001, price=100, order_type="limit", leverage=10.0)  # master 10x
    captured: list[Order] = []
    relayer = SignalRelayer(ct, keystore, _recording_factory(captured),
                            enforce_gate=True, nonce_ledger=NonceLedger(tmp_path / "n"))
    res = relayer.relay(sig)
    assert res[0]["status"] in ("placed", "filled"), res
    assert captured and captured[0].leverage <= 2.0, "relay 必须把 master 10x 截到 follower 2x"


def test_m17_direct_injection_denied(auth, ct, tmp_path):
    """绕过 relay 截断、直接对【门后】venue 注入 leverage=10 → 门拦截（证明门接全、不止靠 relay）。"""
    _, b, m = _setup(auth, ct, network="mainnet", max_leverage=2.0, per_order_max_usdt=1e9)
    f = ct.list_followers(m.master_id, active_only=True)[0]
    sig = ct.publish_signal(m.master_id, m.user_id, symbol="BTCUSDT", side="buy",
                            quantity=0.001, price=100, leverage=2.0)
    gate = follower_gate(f, sig, tier=TrustTier.CRYPTO_LIVE)
    inner = MagicMock()
    inner.place_order = MagicMock(return_value=OrderAck(order_id="x", client_order_id="c"))
    guarded = OrderGuard.wrap(inner, gate=gate, nonce_ledger=NonceLedger(tmp_path / "n"))
    bad = Order(venue="v", symbol="BTCUSDT", side="buy", quantity=0.001, price=100, leverage=10.0)
    with pytest.raises(OrderGated) as ei:
        guarded.place_order(bad, nonce="n1")        # 过 S1 防重放，触 S2 杠杆门
    assert any("max_leverage_exceeded" in v for v in ei.value.decision.violations)
    inner.place_order.assert_not_called()           # 门拒 → 真 venue 永不被调


# ── T2 · deny-by-default 白名单（whitelist={signal.symbol}，他标的全拒）──────────────
def test_deny_by_default_whitelist(auth, ct):
    _, b, m = _setup(auth, ct, network="mainnet", max_leverage=5.0)
    f = ct.list_followers(m.master_id, active_only=True)[0]
    sig = ct.publish_signal(m.master_id, m.user_id, symbol="BTCUSDT", side="buy", quantity=0.001, price=100, leverage=2.0)
    gate = follower_gate(f, sig, tier=TrustTier.CRYPTO_LIVE)
    assert gate.symbol_whitelist == frozenset({"BTCUSDT"})
    other = Order(venue="v", symbol="DOGEUSDT", side="buy", quantity=1, price=1, leverage=2.0)
    d = evaluate(gate, other, action="request_live_order")
    assert not d.allow and any("symbol_not_whitelisted" in v for v in d.violations)


# ── T3 · 单笔名义额上限（门内二次防线，独立于 RiskMonitor）──────────────────────────
def test_notional_cap_at_gate(auth, ct):
    _, b, m = _setup(auth, ct, network="mainnet", max_leverage=5.0, per_order_max_usdt=50.0)
    f = ct.list_followers(m.master_id, active_only=True)[0]
    sig = ct.publish_signal(m.master_id, m.user_id, symbol="BTCUSDT", side="buy", quantity=0.001, price=100, leverage=2.0)
    gate = follower_gate(f, sig, tier=TrustTier.CRYPTO_LIVE)
    over = Order(venue="v", symbol="BTCUSDT", side="buy", quantity=1.0, price=100, leverage=2.0)  # 100 USDT > 50
    d = evaluate(gate, over, action="request_live_order")
    assert not d.allow and any("max_notional_exceeded" in v for v in d.violations)


# ── T4 · 真钱档 nonce 台缺失 → fail-closed（绝不裸放真钱单）──────────────────────────
def test_live_fail_closed_without_nonce_ledger(auth, ct, keystore):
    a, b, m = _setup(auth, ct, network="mainnet", max_leverage=2.0)
    sig = ct.publish_signal(m.master_id, a.user_id, symbol="BTCUSDT", side="buy",
                            quantity=0.001, price=100, leverage=2.0)
    captured: list[Order] = []
    relayer = SignalRelayer(ct, keystore, _recording_factory(captured),
                            enforce_gate=True, nonce_ledger=None)   # 真钱档但无防重放台
    res = relayer.relay(sig)
    assert res[0]["status"] == "rejected"
    assert "live_deps_unavailable_fail_closed" in res[0]["reason"]
    assert not captured, "fail-closed 时 venue 绝不被调"


# ── T5 · 真钱档防重放：同一单第二次被拒（截获 relay 重打打不进）───────────────────────
def test_live_replay_rejected(auth, ct, keystore, tmp_path):
    a, b, m = _setup(auth, ct, network="mainnet", max_leverage=2.0, per_order_max_usdt=1e9)
    sig = ct.publish_signal(m.master_id, a.user_id, symbol="BTCUSDT", side="buy",
                            quantity=0.001, price=100, leverage=2.0)
    captured: list[Order] = []
    # 不注入 beta（否则 is_dispatched 先挡）→ 直验 nonce 防重放层
    relayer = SignalRelayer(ct, keystore, _recording_factory(captured),
                            enforce_gate=True, nonce_ledger=NonceLedger(tmp_path / "n"))
    r1 = relayer.relay(sig)
    r2 = relayer.relay(sig)
    assert r1[0]["status"] in ("placed", "filled")
    assert r2[0]["status"] == "rejected" and "replay_rejected" in r2[0]["reason"]
    assert len(captured) == 1, "重放单绝不二次到达 venue"


# ── T6 · testnet fail-open：依赖缺失仍评估门、不硬阻（假钱不过度工程化）──────────────
def test_testnet_fail_open(auth, ct, keystore):
    a, b, m = _setup(auth, ct, network="testnet", max_leverage=2.0, per_order_max_usdt=1e9)
    sig = ct.publish_signal(m.master_id, a.user_id, symbol="BTCUSDT", side="buy",
                            quantity=0.001, price=100, leverage=2.0)
    captured: list[Order] = []
    relayer = SignalRelayer(ct, keystore, _recording_factory(captured),
                            enforce_gate=True, nonce_ledger=None)   # 无 nonce 台
    res = relayer.relay(sig)
    assert res[0]["status"] in ("placed", "filled"), res   # testnet 不因缺 nonce 台 fail-closed
    assert captured and captured[0].leverage <= 2.0


def test_testnet_still_gated_leverage(auth, ct, keystore):
    """testnet fail-open 不等于不设门：超杠杆仍被夹（截断到 cap）。"""
    a, b, m = _setup(auth, ct, network="testnet", max_leverage=2.0, per_order_max_usdt=1e9)
    sig = ct.publish_signal(m.master_id, a.user_id, symbol="BTCUSDT", side="buy",
                            quantity=0.001, price=100, leverage=50.0)
    captured: list[Order] = []
    relayer = SignalRelayer(ct, keystore, _recording_factory(captured),
                            enforce_gate=True, nonce_ledger=None)
    relayer.relay(sig)
    assert captured and captured[0].leverage <= 2.0


# ── T7 · 门拒时 venue 永不被调（已在 T2/T4 覆盖；此处补 relay 路径）──────────────────
def test_gate_deny_blocks_venue_on_relay(auth, ct, keystore, tmp_path):
    # mainnet + follower 无 max_leverage（→门 max_leverage=1.0）+ master 5x → 截断到 1x≤1 通过；
    # 改用名义额超限触发门拒：per_order_max=10，单 100 USDT。但 RiskMonitor 会先拒——这里直验 relay 经门即可。
    a, b, m = _setup(auth, ct, network="mainnet", max_leverage=2.0, per_order_max_usdt=1e9)
    # 用提币类动作无法经 signal 触发；改注入 leverage 不声明：mainnet 未声明 leverage → 门拒
    sig = ct.publish_signal(m.master_id, a.user_id, symbol="BTCUSDT", side="buy",
                            quantity=0.001, price=100)  # 无 leverage（master None）→ follower applied=None
    captured: list[Order] = []
    relayer = SignalRelayer(ct, keystore, _recording_factory(captured),
                            enforce_gate=True, nonce_ledger=NonceLedger(tmp_path / "n"))
    res = relayer.relay(sig)
    assert res[0]["status"] == "rejected" and "leverage_unspecified" in res[0]["reason"]
    assert not captured, "实盘未声明杠杆 → 门拒 → venue 不被调"


# ── T8 · 向后兼容：enforce_gate=False（默认）不接门 ──────────────────────────────────
def test_backward_compat_no_gate(auth, ct, keystore):
    a, b, m = _setup(auth, ct, network="mainnet", max_leverage=2.0)
    sig = ct.publish_signal(m.master_id, a.user_id, symbol="BTCUSDT", side="buy", quantity=5.0, price=100000)  # 巨单
    captured: list[Order] = []
    relayer = SignalRelayer(ct, keystore, _recording_factory(captured))  # enforce_gate 默认 False
    # RiskMonitor 仍在（per_order_max_usdt 默认 100），但门不接——验证默认路径不经门（与既有 23 测试一致）
    relayer.relay(sig)
    # 不断言下单成功（RiskMonitor 可能拒）；只断言没有门相关 reason
    res = relayer.relay(sig)
    assert all("gate:" not in (r.get("reason") or "") for r in res)


# ── T9 · 四路径同一门：同一违规单在不同 tier 下判定一致（证明是一个会话外门）──────────
def test_same_gate_logic_across_tiers(auth, ct):
    _, b, m = _setup(auth, ct, network="mainnet", max_leverage=2.0)
    f = ct.list_followers(m.master_id, active_only=True)[0]
    sig = ct.publish_signal(m.master_id, m.user_id, symbol="BTCUSDT", side="buy", quantity=0.001, price=100, leverage=2.0)
    bad = Order(venue="v", symbol="ETHUSDT", side="buy", quantity=1, price=1, leverage=99.0)  # 双违规：白名单+杠杆
    for tier in (TrustTier.PAPER, TrustTier.CRYPTO_TESTNET, TrustTier.CRYPTO_LIVE):
        gate = follower_gate(f, sig, tier=tier)
        d = evaluate(gate, bad, action="request_live_order")
        assert not d.allow
        assert any("symbol_not_whitelisted" in v for v in d.violations)
        assert any("max_leverage_exceeded" in v for v in d.violations)


# ── 复核回归 A · 现货实盘单不再因 leverage_unspecified 全拒（现货显式 1x）──────────────
def test_live_spot_order_allowed(auth, ct, keystore, tmp_path):
    a, b, m = _setup(auth, ct, network="mainnet", asset_class="crypto_spot", per_order_max_usdt=1e9)
    # 现货信号无 leverage（None）、带价（limit 便于核名义额）
    sig = ct.publish_signal(m.master_id, a.user_id, symbol="BTCUSDT", side="buy",
                            quantity=0.001, price=100, order_type="limit")  # leverage 默认 None
    captured: list[Order] = []
    relayer = SignalRelayer(ct, keystore, _recording_factory(captured),
                            enforce_gate=True, nonce_ledger=NonceLedger(tmp_path / "n"))
    res = relayer.relay(sig)
    assert res[0]["status"] in ("placed", "filled"), res   # 现货实盘单不再被 leverage_unspecified 全拒
    assert captured and captured[0].leverage == 1.0        # 现货显式 1x


# ── 复核回归 B · 市价实盘单用【可信 venue mark】核名义额（不读自报价）──────────────────
def test_live_market_order_with_trusted_mark_allowed(auth, ct, keystore, tmp_path):
    a, b, m = _setup(auth, ct, network="mainnet", max_leverage=2.0, per_order_max_usdt=1e9)
    sig = ct.publish_signal(m.master_id, a.user_id, symbol="BTCUSDT", side="buy",
                            quantity=0.001, order_type="market", leverage=2.0)  # price=None
    captured: list[Order] = []
    relayer = SignalRelayer(ct, keystore, _recording_factory(captured, mark=100.0),
                            enforce_gate=True, nonce_ledger=NonceLedger(tmp_path / "n"))
    res = relayer.relay(sig)
    assert res[0]["status"] in ("placed", "filled"), res
    assert captured and captured[0].price is None          # 市价单 order.price 不被污染（venue 不收到 price）


def test_live_market_order_without_mark_denied(auth, ct, keystore, tmp_path):
    """取不到可信 mark → 门 deny-by-default（fail-safe），绝不放无法证伪名义额的真钱市价单。"""
    a, b, m = _setup(auth, ct, network="mainnet", max_leverage=2.0, per_order_max_usdt=1e9)
    sig = ct.publish_signal(m.master_id, a.user_id, symbol="BTCUSDT", side="buy",
                            quantity=0.001, order_type="market", leverage=2.0)
    captured: list[Order] = []
    relayer = SignalRelayer(ct, keystore, _recording_factory(captured, mark=None),  # get_position 抛
                            enforce_gate=True, nonce_ledger=NonceLedger(tmp_path / "n"))
    res = relayer.relay(sig)
    assert res[0]["status"] == "rejected" and "notional_unverifiable" in res[0]["reason"]
    assert not captured


def test_live_market_mark_notional_cap_enforced(auth, ct, keystore, tmp_path):
    """可信 mark 真用于名义额上限：mark 高到超 cap → 拒（证明不是绕过、是真核）。"""
    a, b, m = _setup(auth, ct, network="mainnet", max_leverage=2.0, per_order_max_usdt=50.0)
    sig = ct.publish_signal(m.master_id, a.user_id, symbol="BTCUSDT", side="buy",
                            quantity=1.0, order_type="market", leverage=2.0)  # 1 * mark
    captured: list[Order] = []
    relayer = SignalRelayer(ct, keystore, _recording_factory(captured, mark=100.0),  # 100 USDT > 50
                            enforce_gate=True, nonce_ledger=NonceLedger(tmp_path / "n"))
    res = relayer.relay(sig)
    assert res[0]["status"] == "rejected" and "max_notional_exceeded" in res[0]["reason"]
    assert not captured


# ── T-022 集成 · INV-3 命门：真 key 只在门放行后(S4)物化，门拒则永不物化 ─────────────
def test_inv3_key_materialized_only_after_gate_passes(auth, ct, keystore, tmp_path):
    from app.security.gate.broker import KeyBroker
    a, b, m = _setup(auth, ct, network="mainnet", max_leverage=2.0, per_order_max_usdt=1e9)
    broker = KeyBroker(keystore)
    fetched: list[str] = []
    orig = keystore.fetch
    keystore.fetch = lambda name: (fetched.append(name), orig(name))[1]   # spy: 何时物化 key
    captured: list = []

    def factory(follower, ks):
        v = MagicMock()
        v.name = "leased"
        v.get_mark_price = MagicMock(return_value=100.0)
        def _place(order, *, lease=None):
            assert lease is not None, "lease-only：必经 JIT lease 通道"
            captured.append(lease.record.api_key)         # venue 拿到的是 lease 里的 key
            return OrderAck(order_id="ok", client_order_id="c", status="filled")
        v.place_order = MagicMock(side_effect=_place)
        return v

    relayer = SignalRelayer(ct, keystore, factory, enforce_gate=True,
                            nonce_ledger=NonceLedger(tmp_path / "n"), broker=broker)
    # 放行单：key 在 S4 被 fetch 恰一次
    ok = ct.publish_signal(m.master_id, a.user_id, symbol="BTCUSDT", side="buy",
                           quantity=0.001, price=100, leverage=2.0, order_type="limit")
    r1 = relayer.relay(ok)
    assert r1[0]["status"] in ("placed", "filled")
    assert fetched == ["follower_btc"], "真 key 只在门放行后(S4)物化恰一次"
    assert captured == ["K"], "venue 经 lease 拿到 key（非构造自取）"
    # 门拒单（实盘未声明杠杆）：key 永不物化
    fetched.clear()
    bad = ct.publish_signal(m.master_id, a.user_id, symbol="BTCUSDT", side="buy",
                            quantity=0.001, price=100)   # 无 leverage → leverage_unspecified
    r2 = relayer.relay(bad)
    assert r2[0]["status"] == "rejected"
    assert fetched == [], "门拒 → 真 key 永不物化（INV-3 命门）"


def test_lease_accepting_venue_typeerror_surfaces_unmasked(keystore, tmp_path):
    """补洞回归：lease-接受型 venue 提交期内部抛 TypeError 必须【原样上抛】，绝不能被旧的
    `except TypeError: 退化自取` 吞掉、再无-lease 重试——否则真 bug 被掩盖，且对 lease-only 生产
    venue 触发误导性 PermissionError（交易所侧此刻可能已有真实持仓）。且 place_order 恰被调一次。"""
    from app.security.gate.broker import KeyBroker
    from app.security.gate.policy import PolicyGate, gate_hash

    gate = PolicyGate(
        tier=TrustTier.CRYPTO_LIVE,
        symbol_whitelist=frozenset({"BTCUSDT"}),
        max_notional_per_order_usdt=1e9,
        max_leverage=5.0,
        daily_turnover_cap=1e9,
    )
    broker = KeyBroker(keystore)
    cap = broker.issue_capability(action="request_live_order", gate_ref=gate_hash(gate),
                                  keystore_name="follower_btc")

    class BuggyLeaseVenue:
        """lease-接受型 venue，且像生产 LeasedBinanceVenue 一样【无 lease 即 fail-closed】。
        旧代码会吞掉带-lease 调用的 TypeError、再无-lease 重试 → 撞上 PermissionError，
        既掩盖真 bug 又下调用两次。"""

        name = "buggy_leased"

        def __init__(self) -> None:
            self.calls = 0

        def place_order(self, order, *, lease=None):     # lease-接受型签名（显含 'lease' 形参）
            self.calls += 1
            if lease is None:
                raise PermissionError("lease-only: 无 lease 不下单")  # 无-lease 重试会撞上这条
            raise TypeError("bug")                       # 提交期内部真实 bug（如 POST 后 None 下标）

    venue = BuggyLeaseVenue()
    guard = OrderGuard.wrap(venue, gate=gate, broker=broker, capability=cap,
                            nonce_ledger=NonceLedger(tmp_path / "n"))
    order = Order(venue="v", symbol="BTCUSDT", side="buy", quantity=0.001, price=100, leverage=2.0)
    with pytest.raises(TypeError, match="bug"):          # 原始 TypeError 上抛，非 PermissionError
        guard.place_order(order, nonce="n1")
    assert venue.calls == 1, "lease-接受型 venue 的 place_order 恰被调一次（绝不无-lease 重试）"


def test_has_key_does_not_materialize_key(keystore):
    """存在性预检只查名字、不 fetch 本体（INV-3：预检不物化 key）。"""
    from app.security.gate.broker import KeyBroker
    broker = KeyBroker(keystore)
    fetched: list[str] = []
    orig = keystore.fetch
    keystore.fetch = lambda name: (fetched.append(name), orig(name))[1]
    assert broker.has_key("follower_btc") is True
    assert broker.has_key("nonexistent") is False
    assert fetched == [], "has_key 绝不 fetch key 本体"


def test_follower_tier_mapping(auth, ct):
    a, b, m = _setup(auth, ct, network="mainnet")
    f_live = ct.list_followers(m.master_id, active_only=True)[0]
    assert follower_tier(f_live) == TrustTier.CRYPTO_LIVE
    c = auth.register("carol", "passw0rd")
    ct.subscribe(c.user_id, m.master_id, invest_amount=100, binance_keystore_name="follower_btc",
                 binance_network="testnet")
    f_test = next(x for x in ct.list_followers(m.master_id, active_only=True) if x.user_id == c.user_id)
    assert follower_tier(f_test) == TrustTier.CRYPTO_TESTNET
