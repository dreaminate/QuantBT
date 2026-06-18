"""安全门 deny-by-default + 交易所侧硬墙的【对抗式】测试（T-018 / spine 06 §5）。

种已知坏门必抓。覆盖 T1-T18 + 5-lens 复核确认的硬化项：deny-by-default 真锁（cap 默认 0=deny、
名义额只信撮合价非自报、未声明杠杆=违规）/ 实盘强制 nonce / capability 绑定本门 / attestation 不从
order.extra 取 / 注入取不到 key / 四路径同判 / 措辞 + TCB 诚实。
"""

from __future__ import annotations

import random
from unittest.mock import Mock

import pytest
from pydantic import ValidationError

from app.execution.base import Order, OrderAck
from app.security.gate import (
    Attestation,
    CapabilityToken,
    KeyBroker,
    NonceLedger,
    OrderGated,
    OrderGuard,
    PolicyGate,
    TrustTier,
    classify,
    evaluate,
    gate_hash,
    isolated_ingest,
    sanity_check,
)
from app.security.gate.policy import _BANNED_WORDS


class _FakeVenue:
    def __init__(self):
        self.placed: list[Order] = []

    def place_order(self, order: Order, lease=None) -> OrderAck:   # 接受 lease（唯一 key 通道）
        self.placed.append(order)
        return OrderAck(order_id="ok", client_order_id=order.client_order_id)


class _FakeKeystore:
    def __init__(self):
        self.fetched = 0

    def fetch(self, name):
        self.fetched += 1
        return {"api_key": "PUBLICKEY", "api_secret": "SUPERSECRET_DO_NOT_LEAK"}


def _order(symbol="BTCUSDT", notional=5000.0, leverage=2.0, qty=1.0):
    # 名义额走【撮合价 price】（非 PAPER 只信它，不信自报 extra），price = notional/qty。
    return Order(venue="binance_um", symbol=symbol, side="buy", quantity=qty,
                 price=(notional / qty if qty else None), leverage=leverage)


def _testnet_gate(**over):
    base = dict(tier=TrustTier.CRYPTO_TESTNET, symbol_whitelist=frozenset({"BTCUSDT"}),
                max_notional_per_order_usdt=10000.0, max_leverage=2.0, daily_turnover_cap=1e9)
    base.update(over)
    return PolicyGate(**base)


def _live_gate(**over):
    base = dict(tier=TrustTier.CRYPTO_LIVE, symbol_whitelist=frozenset({"BTCUSDT"}),
                max_notional_per_order_usdt=10000.0, max_leverage=2.0, daily_turnover_cap=1e9)
    base.update(over)
    return PolicyGate(**base)


def _paper_gate(**over):
    base = dict(tier=TrustTier.PAPER, symbol_whitelist=frozenset({"BTCUSDT"}),
                max_notional_per_order_usdt=10000.0, max_leverage=3.0)
    base.update(over)
    return PolicyGate(**base)


# ── T1 · 注入绕过策略门（核心命门）：被拒单永不取 key ─────────────────────────────
def test_injection_cannot_reach_key():
    broker = Mock()
    venue = _FakeVenue()
    cap = CapabilityToken(cap_id="c", action="request_live_order", gate_ref="x",
                          keystore_name="binance", expires_at_utc="2099-01-01T00:00:00+00:00", sig="")
    guard = OrderGuard.wrap(venue, gate=_testnet_gate(), broker=broker, capability=cap)
    with pytest.raises(OrderGated) as ei:
        guard.place_order(_order(notional=50000.0))
    assert ei.value.decision.allow is False
    assert any("max_notional" in v for v in ei.value.decision.violations)
    broker.issue.assert_not_called()       # 命门：被拒单永不取 key
    assert venue.placed == []


# ── T2 · 白名单 deny-by-default ────────────────────────────────────────────────
def test_empty_whitelist_denies_all():
    d = evaluate(_testnet_gate(symbol_whitelist=frozenset()), _order(symbol="DOGEUSDT"))
    assert d.allow is False and any("symbol_not_whitelisted" in v for v in d.violations)


# ── T3 · 提币默认禁（类型级 + action allow-list）────────────────────────────────
def test_withdraw_denied():
    with pytest.raises(ValidationError):
        PolicyGate(tier=TrustTier.CRYPTO_LIVE, withdraw="allow")
    assert evaluate(_testnet_gate(), _order(), action="withdraw").allow is False
    assert evaluate(_testnet_gate(), _order(), action="transfer_out").allow is False   # transfer 也拒
    assert "action_not_allowed" in " ".join(evaluate(_testnet_gate(), _order(), action="read_dataset").violations)


# ── T4 · 杠杆上限不被中继/直连绕过（M17）──────────────────────────────────────
def test_leverage_cap_both_paths():
    gate = _testnet_gate(max_leverage=2.0)
    for _ in range(2):
        venue = _FakeVenue()
        with pytest.raises(OrderGated) as ei:
            OrderGuard.wrap(venue, gate=gate).place_order(_order(leverage=10.0))
        assert any("max_leverage" in v for v in ei.value.decision.violations)
        assert venue.placed == [], "10x 单越过门到达 venue（门没接全，门坏）"
    venue = _FakeVenue()
    OrderGuard.wrap(venue, gate=gate).place_order(_order(leverage=2.0))
    assert venue.placed[0].leverage <= 2.0


# ── T5 · 重放：同 nonce 两次 ────────────────────────────────────────────────────
def test_replay_rejected(tmp_path):
    nl = NonceLedger(tmp_path)
    guard = OrderGuard.wrap(_FakeVenue(), gate=_live_gate(), nonce_ledger=nl)
    guard.place_order(_order(), nonce="n-1")
    with pytest.raises(OrderGated) as ei:
        guard.place_order(_order(), nonce="n-1")
    assert "replay_rejected" in ei.value.decision.violations
    assert nl.is_consumed("n-1")


# ── 复核 #4/#16 · CRYPTO_LIVE 缺 nonce → 强制 BLOCK（fail-closed）──────────────────
def test_live_requires_nonce(tmp_path):
    nl = NonceLedger(tmp_path)
    # 无 ledger
    with pytest.raises(OrderGated) as e1:
        OrderGuard.wrap(_FakeVenue(), gate=_live_gate()).place_order(_order(), nonce="n")
    assert "nonce_required_on_live" in e1.value.decision.violations
    # 有 ledger 但无 nonce
    with pytest.raises(OrderGated) as e2:
        OrderGuard.wrap(_FakeVenue(), gate=_live_gate(), nonce_ledger=nl).place_order(_order(), nonce=None)
    assert "nonce_required_on_live" in e2.value.decision.violations


# ── T6 · 密钥永不泄 ─────────────────────────────────────────────────────────────
def test_capability_carries_no_key():
    ks = _FakeKeystore()
    broker = KeyBroker(ks)
    cap = broker.issue_capability(action="request_live_order", gate_ref="g1", keystore_name="binance")
    blob = cap.model_dump_json()
    assert "SUPERSECRET" not in blob and "api_secret" not in blob
    assert ks.fetched == 0
    lease = broker.issue(cap)
    assert lease.record["api_secret"] == "SUPERSECRET_DO_NOT_LEAK" and ks.fetched == 1
    broker.revoke(lease)
    with pytest.raises(PermissionError):
        _ = lease.record


def test_invalid_capability_refused():
    broker = KeyBroker(_FakeKeystore())
    forged = CapabilityToken(cap_id="cap-x", action="request_live_order", gate_ref="g",
                             keystore_name="binance", expires_at_utc="2099-01-01T00:00:00+00:00", sig="forged")
    with pytest.raises(PermissionError):
        broker.issue(forged)


# ── 复核 #3 · capability 必须绑定本门：用别门签的 cap 取不到 key ──────────────────
def test_capability_must_match_gate(tmp_path):
    ks = _FakeKeystore()
    broker = KeyBroker(ks)
    gate = _testnet_gate()
    wrong_cap = broker.issue_capability(action="request_live_order", gate_ref="WRONG_GATE", keystore_name="binance")
    guard = OrderGuard.wrap(_FakeVenue(), gate=gate, broker=broker, capability=wrong_cap)
    with pytest.raises(OrderGated) as ei:
        guard.place_order(_order())            # 合规单，但 cap 绑的是别的门
    assert "capability_gate_mismatch" in ei.value.decision.violations
    assert ks.fetched == 0, "门不匹配却取了 key（门坏）"
    # 正确绑定 → 放行取 key
    right_cap = broker.issue_capability(action="request_live_order", gate_ref=gate_hash(gate), keystore_name="binance")
    OrderGuard.wrap(_FakeVenue(), gate=gate, broker=broker, capability=right_cap).place_order(_order())
    assert ks.fetched == 1


# ── 复核 #15 · attestation 不从 order.extra 取（注入单自报已授权无效）──────────────
def test_attestation_not_from_order_extra():
    gate = _live_gate(require_validation_attestation=True)
    poisoned = _order()
    poisoned.extra = {"attestation_ok": True, "action": "request_live_order"}   # 注入单自报
    d = evaluate(gate, poisoned, attestation_ok=False)   # evaluate 只信入参，不读 extra
    assert d.allow is False and "missing_attestation" in d.violations


# ── 复核 #6/#17 · 实盘 cap 默认 0 = deny-all（非「无限制」）────────────────────────
def test_zero_cap_is_deny_on_live():
    d = evaluate(_live_gate(max_notional_per_order_usdt=0.0), _order(notional=100.0), attestation_ok=True)
    assert d.allow is False and "notional_cap_unset" in d.violations


# ── 复核 #7 · 名义额只信撮合价，不信自报 extra.notional ─────────────────────────
def test_notional_from_price_not_self_report():
    o = Order(venue="x", symbol="BTCUSDT", side="buy", quantity=1.0, price=50000.0, leverage=2.0,
              extra={"notional_usdt": 100.0})   # 自报 100，实则 50000
    d = evaluate(_testnet_gate(max_notional_per_order_usdt=10000.0), o)
    assert d.allow is False and any("max_notional_exceeded" in v for v in d.violations)


# ── 复核 #8 · 实盘未声明 leverage = 违规（venue 会用账户默认高杠杆）──────────────
def test_unspecified_leverage_denied_on_live():
    d = evaluate(_testnet_gate(), _order(leverage=None))
    assert d.allow is False and "leverage_unspecified" in d.violations


# ── T7 · 决策值语义投毒 ────────────────────────────────────────────────────────
def test_decision_value_poison_flagged():
    res = isolated_ingest({"signal_score": 99})
    assert "poison_suspect" in res.anomaly_flags and res.can_drive_go_live is False
    assert sanity_check({"signal_score": 1.5}) == []


# ── T8 · CRYPTO_LIVE 大额缺 attestation 必 BLOCK ────────────────────────────────
def test_crypto_live_missing_attestation_blocks():
    gate = _live_gate(require_dual_control_above_usdt=1000.0)
    d = evaluate(gate, _order(notional=5000.0), attestation_ok=False)
    assert d.escalate_to_human is True and d.allow is False and "missing_attestation" in d.violations
    d2 = evaluate(gate, _order(notional=5000.0), attestation_ok=True)
    assert d2.allow is True and d2.escalate_to_human is True


# ── T9 · 正常单放行（抓误杀）───────────────────────────────────────────────────
def test_normal_order_allowed():
    d = evaluate(_paper_gate(), _order(notional=5000.0, leverage=2.0))
    assert d.allow is True and d.escalate_to_human is False and d.violations == []


# ── T10 · 四路径同判（M17）：一个会话外门 ───────────────────────────────────────
def test_four_paths_same_verdict():
    gate = _testnet_gate()
    bad = _order(symbol="DOGEUSDT", notional=99999.0, leverage=20.0)
    decisions = []
    for _ in ("paper", "binance_um", "generic", "relay"):
        try:
            OrderGuard.wrap(_FakeVenue(), gate=gate).place_order(bad)
        except OrderGated as e:
            decisions.append(sorted(e.decision.violations))
    assert len(decisions) == 4 and all(v == decisions[0] for v in decisions)


# ── T11 · tier 单调 ────────────────────────────────────────────────────────────
def test_tier_monotonic_attestation():
    order = _order(notional=5000.0)
    live = evaluate(_live_gate(require_dual_control_above_usdt=1000.0), order, attestation_ok=False)
    paper = evaluate(_paper_gate(), order)
    assert live.allow is False and paper.allow is True


# ── T12 · 收紧门不放水 ──────────────────────────────────────────────────────────
def test_tightening_gate_flips_to_deny():
    order = _order(notional=8000.0)
    assert evaluate(_testnet_gate(max_notional_per_order_usdt=10000.0), order).allow is True
    assert evaluate(_testnet_gate(max_notional_per_order_usdt=5000.0), order).allow is False


# ── T13 · 双实现对账 1000 单 ────────────────────────────────────────────────────
def _reference_allow(gate: PolicyGate, order: Order) -> bool:
    if order.symbol not in gate.symbol_whitelist:
        return False
    if order.leverage is None:           # 非 PAPER 未声明杠杆 = 拒（与硬化后一致）
        return gate.tier == TrustTier.PAPER
    if order.leverage > gate.max_leverage:
        return False
    notional = abs(order.quantity * (order.price or 0))
    if gate.max_notional_per_order_usdt > 0 and notional > gate.max_notional_per_order_usdt:
        return False
    return True


def test_dual_implementation_reconcile():
    rng = random.Random(42)
    gate = _testnet_gate(max_notional_per_order_usdt=10000.0, max_leverage=3.0)
    for _ in range(1000):
        n = rng.choice([100.0, 8000.0, 50000.0])
        o = Order(venue="x", symbol=rng.choice(["BTCUSDT", "DOGEUSDT", "ETHUSDT"]), side="buy",
                  quantity=1.0, price=n, leverage=rng.choice([1.0, 2.0, 5.0]))
        assert evaluate(gate, o).allow == _reference_allow(gate, o), \
            f"双实现对账不一致：{o.symbol} lev={o.leverage} notional={n}"


# ── T14 · 验证官 attestation 非组织独立（R7）────────────────────────────────────
def test_verifier_wording_not_independent():
    passed, text = Attestation(passed=True, verdict_id="v1", checker_model="other-model").consume()
    assert passed is True and "非组织独立" in text and "consistency_check" in text
    assert "independent validation" not in text.lower()


# ── T17 · 裁决措辞 + TCB 诚实 ───────────────────────────────────────────────────
def test_verdict_wording_and_tcb_honesty():
    for d in (evaluate(_testnet_gate(), _order(notional=50000.0)),
              evaluate(_paper_gate(), _order(notional=5000.0, leverage=2.0))):
        assert "证据" in d.verdict_text and "适用域" in d.verdict_text and "未验证" in d.verdict_text
        assert "防篡改证据" in d.verdict_text
        for w in _BANNED_WORDS:
            assert w not in d.verdict_text


# ── 分级 classify：A股永远 paper ────────────────────────────────────────────────
def test_classify_a_share_never_live():
    assert classify("equity_cn", is_live=True) == TrustTier.PAPER
    assert classify("crypto_perp", is_live=True) == TrustTier.CRYPTO_LIVE
    assert classify("crypto_perp", is_live=False) == TrustTier.CRYPTO_TESTNET
