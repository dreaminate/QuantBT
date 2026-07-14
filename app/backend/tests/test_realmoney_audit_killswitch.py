"""T-025 · 真钱执行路径审计 + 急停/kill 控件收尾 + GenericVenue 接活——对抗测试。

种已知坏门必抓：
1. 绕门不变量：全 app `place_order` 调用点 ⊆ {门后路径}；新增门外调用点 → 必红（+ 探针自检非 no-op）。
2. kill_switch 端点鉴权：缺 IP/密码 → 403。
3. relay 向后兼容陷阱：enforce_gate=False 下真钱(mainnet)单 → 拒、venue 绝不被调。
4. emergency / kill 真执行：真调 venue cancel/close（非空 log）。
5. generic 接活 deny-by-default：空白名单/不在白名单 → 拒；guarded_generic_venue 经 OrderGuard + CRYPTO_LIVE fail-closed。
6. kill 重放幂等：连发两次不报错（fail-open）。
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

import app as app_pkg
from app.auth import AuthService, require_user_dependency
from app.copy_trade import CopyTradeService, SignalRelayer
from app.execution.base import Order, OrderAck, Position
from app.execution.generic_trading import (
    GenericTradingConfig,
    GenericTradingVenue,
    guarded_generic_venue,
)
from app.main import app
from app.risk import EquitySnapshot, KillSwitch, RiskLimits, RiskMonitor
from app.security import InMemoryKeystore, KeystoreRecord, SecureKeystore
from app.security.gate.enforcer import OrderGuard
from app.security.gate.policy import OrderGated, PolicyGate, TrustTier
from app.security.mainnet_guards import MainnetGuardConfig, MainnetGuardsService
from app.security.gate.account_halt import PersistentAccountHaltBarrier

APP_ROOT = Path(app_pkg.__file__).resolve().parent
# 门后路径（唯一允许直发 venue.place_order 的文件）：
#   leased_binance.py = S4 lease 后现造 venue 提交；executor.py = relay（门后 guarded + 受守的向后兼容）。
# OrderGuard 自身经 `inner(order)` 别名调用，非 `.place_order(` 文本，不在扫描命中内（=门本体）。
_ALLOWLIST = {"execution/leased_binance.py", "copy_trade/executor.py"}
_CALL_PAT = re.compile(r"\.place_order\s*\(")


def _scan_place_order_callsites(root: Path) -> dict[str, list[tuple[int, str]]]:
    hits: dict[str, list[tuple[int, str]]] = {}
    for path in root.rglob("*.py"):
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except Exception:  # noqa: BLE001
            continue
        for i, line in enumerate(lines, 1):
            s = line.strip()
            if s.startswith("#") or "def place_order" in s:
                continue
            if _CALL_PAT.search(line):
                hits.setdefault(str(path.relative_to(root)), []).append((i, s))
    return hits


# ── 1. 绕门审计不变量 ──────────────────────────────────────────────────────
def test_no_ungated_place_order_callsites():
    hits = _scan_place_order_callsites(APP_ROOT)
    offenders = {f for f in hits if f not in _ALLOWLIST}
    assert not offenders, f"发现门外 place_order 调用点（绕门风险）：{offenders}；必须在 {_ALLOWLIST}"
    # 防 scan 退化成空集而假绿：必须真扫到已知门后调用点。
    assert _ALLOWLIST & set(hits), f"scan 未命中任何已知门后调用点，疑似 scan 失效；hits={set(hits)}"


def test_audit_probe_catches_ungated_callsite(tmp_path):
    """探针自检（变异）：种一个门外直发 place_order → scan 必抓（证明 #1 不是 no-op）。"""
    (tmp_path / "rogue.py").write_text("def f(venue, order):\n    return venue.place_order(order)\n")
    hits = _scan_place_order_callsites(tmp_path)
    assert "rogue.py" in hits


# ── 2/4/6. 急停控件：鉴权 + 真执行 + 幂等 ───────────────────────────────────
class _SpyVenue:
    def __init__(self, *, owner_user_id: str = "tester", name: str = "spy") -> None:
        self.owner_user_id = owner_user_id
        self.name = name
        self.account_ref = f"account:{name}"
        self.cancelled = 0
        self.closed: list[str] = []
        self.positions = [Position(symbol="BTCUSDT", quantity=0.01)]

    def emergency_cancel_all(self):
        self.cancelled += 1
        actions = [{"cancelled_all": True}] if self.cancelled == 1 else []
        return {"ok": True, "verified_noop": not actions, "actions": actions, "error": None}

    def list_open_positions(self):
        return list(self.positions)

    def close_open_position(self, position):
        self.closed.append(position.symbol)
        self.positions = [item for item in self.positions if item.symbol != position.symbol]
        return {"closed": position.symbol, "quantity": position.quantity}

    def reconcile_emergency_actions_for_halt(self, _context):
        return ()

    def close_open_position_for_halt(self, position, _context):
        return self.close_open_position(position)

    def verify_emergency_flat(self, *, close_positions=True):
        open_positions = [
            {"symbol": position.symbol, "quantity": position.quantity}
            for position in self.positions
        ]
        return {
            "ok": not close_positions or not open_positions,
            "normal_open_order_refs": [],
            "algo_open_order_refs": [],
            "open_positions": open_positions,
        }


class _FailingCloseVenue:
    """平仓抛错的 venue（KILL_SWITCH fail-open 会把 error 塞进 results，不上抛）。"""

    name = "failspy"
    owner_user_id = "tester"
    account_ref = "account:failspy"

    def emergency_cancel_all(self):
        return {
            "ok": True,
            "verified_noop": False,
            "actions": [{"cancelled_all": True}],
            "error": None,
        }

    def list_open_positions(self):
        return [Position(symbol="BTCUSDT", quantity=0.01)]

    def close_open_position(self, position):
        raise RuntimeError("exchange 5xx on close")

    def reconcile_emergency_actions_for_halt(self, _context):
        return ()

    def close_open_position_for_halt(self, position, _context):
        return self.close_open_position(position)

    def verify_emergency_flat(self, *, close_positions=True):
        return {
            "ok": not close_positions,
            "normal_open_order_refs": [],
            "algo_open_order_refs": [],
            "open_positions": [{"symbol": "BTCUSDT", "quantity": 0.01}],
        }


class _EmptyVenue:
    name = "empty"
    owner_user_id = "tester"
    account_ref = "account:empty"

    def cancel_all_open(self):
        return []

    def get_balance(self):
        return {}


class _RejectedFlatProofVenue(_SpyVenue):
    def verify_emergency_flat(self, *, close_positions=True):
        return {
            "ok": False,
            "normal_open_order_refs": [],
            "algo_open_order_refs": [],
            "open_positions": [],
        }


class _MalformedFlatProofVenue(_SpyVenue):
    def __init__(self, quantity):
        super().__init__()
        self._proof_quantity = quantity

    def verify_emergency_flat(self, *, close_positions=True):
        return {
            "ok": True,
            "normal_open_order_refs": [],
            "algo_open_order_refs": [],
            "open_positions": [{"symbol": "BTCUSDT", "quantity": self._proof_quantity}],
        }


class _StubAuth:
    """测试替身：服务端密码校验 = 密码须等于 'pw-ok'（隔离真 auth DB，验 _verify_second_factor 真比对）。"""

    def verify_password(self, user_id, password):
        return password == "pw-ok"


class _OwnerRegistry:
    def __init__(self, venues=()):
        self._venues = tuple(venues)

    def venues_for_user(self, user_id):
        return tuple(venue for venue in self._venues if venue.owner_user_id == user_id)


def _kill_service_for_venue(venue):
    follower = SimpleNamespace(
        follower_id=f"tester::{venue.name}",
        user_id="tester",
        master_id=f"master::{venue.name}",
        status="active",
        binance_network="mainnet",
        account_binding_ref=venue.account_ref,
    )
    def begin_draining(user_id, master_id):
        if (
            user_id != follower.user_id
            or master_id != follower.master_id
            or follower.status not in {"activating", "active", "paused"}
        ):
            return False
        follower.status = "draining"
        return True

    return SimpleNamespace(
        list_subscriptions=lambda user_id: (follower,) if user_id == "tester" else (),
        begin_draining=begin_draining,
        list_draining_mainnet_followers=lambda: (
            (follower,) if follower.status == "draining" else ()
        ),
    )


def _setup_kill_app(tmp_path, monkeypatch, venue):
    guards = MainnetGuardsService(tmp_path / "guards.db")
    guards.upsert_config(MainnetGuardConfig(user_id="tester", trusted_ips=["1.2.3.4"],
                                            require_password_per_order=True))
    monkeypatch.setattr("app.main.MAINNET_GUARDS", guards)
    monkeypatch.setattr("app.main.KILL_SWITCH", KillSwitch())
    halt_barrier = PersistentAccountHaltBarrier(tmp_path / "account-halt.sqlite3")
    halt_barrier.activate(venue.account_ref, "tester")
    monkeypatch.setattr("app.main.ACCOUNT_HALT_BARRIER", halt_barrier)
    monkeypatch.setattr("app.main.COPY_TRADE_SERVICE", _kill_service_for_venue(venue))
    monkeypatch.setattr(
        "app.main.FOLLOWER_RISK_STATE",
        SimpleNamespace(has_open_reservations=lambda *_args: False),
    )
    monkeypatch.setattr("app.main.ACTIVE_EMERGENCY_VENUES", _OwnerRegistry((venue,)))
    monkeypatch.setattr(
        "app.main.RISK_MONITOR",
        RiskMonitor(
            RiskLimits(),
            get_equity=lambda: EquitySnapshot(
                equity=1000.0,
                observed_at_utc=datetime.now(UTC).isoformat(),
                source_ref="account:test:equity",
            ),
        ),
    )
    monkeypatch.setattr("app.main.AUTH_SERVICE", _StubAuth())
    app.dependency_overrides[require_user_dependency] = lambda: SimpleNamespace(user_id="tester")
    # source_ip 由服务端从连接派生（_client_ip）—— 用 client= 设真实来源 IP（已加白）。
    return TestClient(app, client=("1.2.3.4", 12345)), guards


@pytest.fixture
def kill_client(tmp_path, monkeypatch):
    guards = MainnetGuardsService(tmp_path / "guards.db")
    guards.upsert_config(MainnetGuardConfig(user_id="tester", trusted_ips=["1.2.3.4"],
                                            require_password_per_order=True))
    spy = _SpyVenue()
    monkeypatch.setattr("app.main.MAINNET_GUARDS", guards)
    monkeypatch.setattr("app.main.KILL_SWITCH", KillSwitch())
    halt_barrier = PersistentAccountHaltBarrier(tmp_path / "account-halt.sqlite3")
    halt_barrier.activate(spy.account_ref, "tester")
    monkeypatch.setattr("app.main.ACCOUNT_HALT_BARRIER", halt_barrier)
    monkeypatch.setattr("app.main.COPY_TRADE_SERVICE", _kill_service_for_venue(spy))
    monkeypatch.setattr(
        "app.main.FOLLOWER_RISK_STATE",
        SimpleNamespace(has_open_reservations=lambda *_args: False),
    )
    monkeypatch.setattr("app.main.ACTIVE_EMERGENCY_VENUES", _OwnerRegistry((spy,)))
    monkeypatch.setattr(
        "app.main.RISK_MONITOR",
        RiskMonitor(
            RiskLimits(),
            get_equity=lambda: EquitySnapshot(
                equity=1000.0,
                observed_at_utc=datetime.now(UTC).isoformat(),
                source_ref="account:test:equity",
            ),
        ),
    )
    monkeypatch.setattr("app.main.AUTH_SERVICE", _StubAuth())
    app.dependency_overrides[require_user_dependency] = lambda: SimpleNamespace(user_id="tester")
    try:
        # source_ip 由服务端从连接派生 —— client= 设真实来源 IP（1.2.3.4 已加白）。
        yield TestClient(app, client=("1.2.3.4", 12345)), spy
    finally:
        app.dependency_overrides.pop(require_user_dependency, None)


def test_kill_switch_requires_login():
    """没登录 → require_user_dependency 拦截（绝非裸放）。"""
    client = TestClient(app)
    r = client.post("/api/risk/kill_switch", json={})
    assert r.status_code in (401, 403)


def test_kill_switch_rejects_untrusted_ip(kill_client):
    _client, _spy = kill_client  # 复用 fixture 的 guards/auth override（trusted=1.2.3.4）
    untrusted = TestClient(app, client=("9.9.9.9", 1))  # 真实来源 IP 未加白
    r = untrusted.post("/api/risk/kill_switch", json={"password": "pw-ok"})
    assert r.status_code == 403  # 服务端按真实连接 IP 拒绝（非看 body）


def test_kill_switch_body_source_ip_cannot_spoof_whitelist(kill_client):
    """加固回归：body 塞一个已加白的 source_ip 也旁路不了——IP 以服务端连接为准（防伪造）。"""
    _client, _spy = kill_client
    untrusted = TestClient(app, client=("9.9.9.9", 1))  # 真实来源未加白
    r = untrusted.post("/api/risk/kill_switch",
                       json={"source_ip": "1.2.3.4", "password": "pw-ok"})  # 伪造已加白 IP
    assert r.status_code == 403  # body 伪造无效，仍按真实 9.9.9.9 拒绝


def test_kill_switch_rejects_without_password(kill_client):
    client, _spy = kill_client  # 真实来源 1.2.3.4 已加白
    r = client.post("/api/risk/kill_switch", json={})  # IP 过，但无二次鉴权凭据 → 403
    assert r.status_code == 403


def test_kill_switch_rejects_wrong_password(kill_client):
    """升级回归：密码服务端真校验——错密码（IP 已加白）仍 403。"""
    client, _spy = kill_client
    r = client.post("/api/risk/kill_switch", json={"password": "wrong-pw"})
    assert r.status_code == 403


def test_kill_switch_self_attested_bool_no_longer_bypasses(kill_client):
    """升级回归（核心）：旧自证 password_verified=true 已废弃——光给 bool、无真密码 → 403。"""
    client, _spy = kill_client  # IP 已加白，唯一缺的就是真凭据
    r = client.post("/api/risk/kill_switch", json={"password_verified": True})
    assert r.status_code == 403  # 自证 bool 不再被信任，必须服务端真校验密码/TOTP


@pytest.mark.parametrize("malformed", ("false", 1, 0, None, {}, []))
def test_kill_switch_rejects_non_boolean_close_intent_before_halt(kill_client, malformed):
    client, spy = kill_client
    response = client.post(
        "/api/risk/kill_switch",
        json={"password": "pw-ok", "close_positions": malformed},
    )
    assert response.status_code == 400
    assert spy.cancelled == 0
    assert spy.closed == []


@pytest.mark.parametrize(
    "path",
    ("/api/risk/kill_switch", "/api/security/mainnet/emergency_close_all"),
)
def test_totp_only_kill_audit_records_the_actual_factor(path, tmp_path, monkeypatch):
    client, guards = _setup_kill_app(tmp_path, monkeypatch, _SpyVenue())
    monkeypatch.setattr(
        guards,
        "verify_totp",
        lambda user_id, code: user_id == "tester" and code == "123456",
    )
    try:
        response = client.post(path, json={"totp_code": "123456"})
        assert response.status_code == 200
        audit = guards.list_audit_log("tester")
        assert audit
        assert audit[0]["totp_verified"] == 1
        assert audit[0]["password_verified"] == 0
    finally:
        app.dependency_overrides.pop(require_user_dependency, None)


def test_kill_switch_real_execution_and_idempotent(kill_client):
    client, spy = kill_client
    body = {"password": "pw-ok"}  # 服务端真校验密码；IP 由连接派生(1.2.3.4 已加白)
    r1 = client.post("/api/risk/kill_switch", json=body)
    assert r1.status_code == 200
    assert spy.cancelled == 1 and spy.closed == ["BTCUSDT"]  # 真撤单 + 真平仓
    assert r1.json()["ok"] is True and r1.json()["action_ok"] is True
    assert r1.json()["results"]["spy"]["ok"] is True
    # 重放：连发第二次不报错（fail-open 幂等，门坏也要能救命平仓）。
    r2 = client.post("/api/risk/kill_switch", json=body)
    assert r2.status_code == 200
    assert r2.json()["ok"] is True and r2.json()["action_ok"] is True
    assert r2.json()["results"]["spy"]["cancel"]["verified_noop"] is True
    assert r2.json()["results"]["spy"]["position_discovery"]["verified_noop"] is True


def test_kill_switch_executes_only_authenticated_users_venues(tmp_path, monkeypatch):
    alice = _SpyVenue(owner_user_id="tester", name="alice-venue")
    bob = _SpyVenue(owner_user_id="other-user", name="bob-venue")
    client, _guards = _setup_kill_app(tmp_path, monkeypatch, alice)
    monkeypatch.setattr("app.main.ACTIVE_EMERGENCY_VENUES", _OwnerRegistry((alice, bob)))
    try:
        response = client.post("/api/risk/kill_switch", json={"password": "pw-ok"})
        assert response.status_code == 200
        assert set(response.json()["results"]) == {"alice-venue"}
        assert alice.cancelled == 1 and alice.closed == ["BTCUSDT"]
        assert bob.cancelled == 0 and bob.closed == []
    finally:
        app.dependency_overrides.pop(require_user_dependency, None)


def test_kill_switch_empty_venue_set_never_reports_ok(tmp_path, monkeypatch):
    client, _guards = _setup_kill_app(tmp_path, monkeypatch, _SpyVenue())
    monkeypatch.setattr("app.main.ACTIVE_EMERGENCY_VENUES", _OwnerRegistry())
    try:
        response = client.post("/api/risk/kill_switch", json={"password": "pw-ok"})
        assert response.status_code == 200
        assert response.json()["ok"] is False
        assert response.json()["action_ok"] is False
        assert response.json()["status"] == "unavailable"
    finally:
        app.dependency_overrides.pop(require_user_dependency, None)


def test_kill_switch_empty_action_results_never_report_ok(tmp_path, monkeypatch):
    client, _guards = _setup_kill_app(tmp_path, monkeypatch, _EmptyVenue())
    try:
        response = client.post("/api/risk/kill_switch", json={"password": "pw-ok"})
        assert response.status_code == 200
        assert response.json()["ok"] is False
        assert response.json()["status"] == "failed"
    finally:
        app.dependency_overrides.pop(require_user_dependency, None)


def test_kill_switch_does_not_relabel_rejected_clean_proof_as_verified_noop():
    result = KillSwitch([_RejectedFlatProofVenue()]).trigger()
    stage = result["spy"]["flat_verification"]
    assert stage["ok"] is False
    assert stage["verified_noop"] is False
    assert result["spy"]["ok"] is False


@pytest.mark.parametrize("quantity", [True, float("nan")])
def test_kill_switch_rejects_non_numeric_or_nonfinite_position_proof(quantity):
    result = KillSwitch([_MalformedFlatProofVenue(quantity)]).trigger()
    stage = result["spy"]["flat_verification"]
    assert stage["ok"] is False
    assert "invalid open_positions" in stage["error"]


def test_kill_switch_inactive_monitor_never_reports_ok(tmp_path, monkeypatch):
    client, _guards = _setup_kill_app(tmp_path, monkeypatch, _SpyVenue())
    monkeypatch.setattr("app.main.RISK_MONITOR", RiskMonitor(RiskLimits()))
    try:
        response = client.post("/api/risk/kill_switch", json={"password": "pw-ok"})
        assert response.status_code == 200
        assert response.json()["ok"] is False
        assert response.json()["action_ok"] is True
        assert response.json()["status"] == "unavailable"
    finally:
        app.dependency_overrides.pop(require_user_dependency, None)


def test_emergency_close_all_real_execution(kill_client):
    """emergency 从空壳→真调 KILL_SWITCH（非空 log）。"""
    client, spy = kill_client
    r = client.post("/api/security/mainnet/emergency_close_all",
                    json={"password": "pw-ok"})  # 服务端真校验密码；IP 由连接派生(1.2.3.4 已加白)
    assert r.status_code == 200
    assert spy.cancelled == 1 and spy.closed == ["BTCUSDT"]
    assert r.json()["ok"] is True
    assert r.json()["results"].get("spy")  # 真平仓结果，非「仅记录意图」空壳


def test_emergency_close_all_rejects_untrusted_ip(kill_client):
    _client, _spy = kill_client
    untrusted = TestClient(app, client=("9.9.9.9", 1))  # 真实来源未加白
    r = untrusted.post("/api/security/mainnet/emergency_close_all",
                       json={"password": "pw-ok"})
    assert r.status_code == 403


def test_emergency_close_all_partial_failure_not_reported_ok(tmp_path, monkeypatch):
    """5-lens HIGH：含平仓失败 → 绝不报 ok:True、审计绝不记 result='ok'（真钱面不假绿灯）。"""
    client, guards = _setup_kill_app(tmp_path, monkeypatch, _FailingCloseVenue())
    try:
        r = client.post("/api/security/mainnet/emergency_close_all",
                        json={"password": "pw-ok"})  # 服务端真校验密码；IP 由连接派生(1.2.3.4 已加白)
        assert r.status_code == 200
        body = r.json()
        assert body["ok"] is False                       # 平仓失败 → 不报 ok
        assert body["status"] in ("partial", "failed")
        audit = guards.list_audit_log("tester")
        assert audit and audit[0]["result"] in ("partial", "failed")  # 审计如实，非 'ok'
        assert audit[0]["error"]
    finally:
        app.dependency_overrides.pop(require_user_dependency, None)


def test_kill_switch_partial_failure_not_reported_ok(tmp_path, monkeypatch):
    """5-lens HIGH 同源：kill_switch 含平仓失败 → ok:False + 审计非 'ok'。"""
    client, guards = _setup_kill_app(tmp_path, monkeypatch, _FailingCloseVenue())
    try:
        r = client.post("/api/risk/kill_switch",
                        json={"password": "pw-ok"})  # 服务端真校验密码；IP 由连接派生(1.2.3.4 已加白)
        assert r.status_code == 200
        assert r.json()["ok"] is False and r.json()["status"] in ("partial", "failed")
        assert guards.list_audit_log("tester")[0]["result"] in ("partial", "failed")
    finally:
        app.dependency_overrides.pop(require_user_dependency, None)


# ── 3. relay 向后兼容陷阱：enforce_gate=False 真钱单 → 拒 ─────────────────────
def _recording_factory(captured: list):
    def factory(follower, ks):  # noqa: ARG001
        v = MagicMock()
        v.name = "mock_binance"
        v.get_mark_price = MagicMock(return_value=None)

        def _place(order, **kw):  # noqa: ARG001
            captured.append(order)
            return OrderAck(order_id="o", client_order_id="c", status="filled")

        v.place_order = MagicMock(side_effect=_place)
        return v
    return factory


def test_relay_backward_compat_realmoney_rejected(tmp_path):
    auth = AuthService(tmp_path / "c.db")
    ct = CopyTradeService(tmp_path / "c.db")
    ks = SecureKeystore(InMemoryKeystore())
    ks.store(KeystoreRecord(name="follower_btc", api_key="K", api_secret="S", note="t"))
    a = auth.register("alice", "passw0rd")
    b = auth.register("bob", "passw0rd")
    m = ct.register_master(a.user_id, "A", asset_class="crypto_perp")
    ct.subscribe(b.user_id, m.master_id, invest_amount=1000, binance_keystore_name="follower_btc",
                 binance_network="mainnet", per_order_max_usdt=100.0,
                 account_binding_ref="exchange_account_uid_test",
                 runtime_promotion_ref="runtime_promotion_test",
                 user_risk_choice_ref="user_risk_choice_test")  # mainnet=真钱→CRYPTO_LIVE
    sig = ct.publish_signal(m.master_id, a.user_id, symbol="BTCUSDT", side="buy",
                            quantity=0.001, price=100, order_type="limit", leverage=1.0)
    captured: list[Order] = []
    relayer = SignalRelayer(ct, ks, _recording_factory(captured), enforce_gate=False)  # 向后兼容直发
    res = relayer.relay(sig)
    assert res[0]["status"] == "rejected"          # 真钱不走裸直发
    assert "fail_closed" in res[0]["reason"]
    assert not captured                            # venue.place_order 绝不被调（key 不取出）


# ── 5. GenericTradingVenue 接活：deny-by-default + OrderGuard ────────────────
def _generic_cfg(**over) -> GenericTradingConfig:
    base = dict(venue_name="dex", base_url="http://example.invalid",
                place_order={"path": "/p"}, cancel_order={"path": "/c"},
                get_balance={"path": "/b"}, get_position={"path": "/pos"})
    base.update(over)
    return GenericTradingConfig(**base)


def test_generic_venue_deny_by_default_empty_whitelist():
    venue = GenericTradingVenue(_generic_cfg(deny_by_default=True, allowed_symbols=[]))
    with pytest.raises(PermissionError, match="deny-by-default"):
        venue.place_order(Order(venue="dex", symbol="BTC", side="buy", quantity=1, order_type="market"))


def test_generic_venue_deny_by_default_offwhitelist():
    venue = GenericTradingVenue(_generic_cfg(deny_by_default=True, allowed_symbols=["ETH"]))
    with pytest.raises(PermissionError, match="deny-by-default"):
        venue.place_order(Order(venue="dex", symbol="BTC", side="buy", quantity=1, order_type="market"))


def test_generic_venue_backward_compat_no_deny_by_default():
    """向后兼容：deny_by_default=False（默认）→ 不启用白名单（既有黑名单语义不变）。"""
    session = MagicMock()
    resp = MagicMock()
    resp.json.return_value = {"order_id": "o1", "status": "new"}
    resp.raise_for_status.return_value = None
    session.request.return_value = resp
    venue = GenericTradingVenue(_generic_cfg(), http=session)  # deny_by_default 默认 False
    ack = venue.place_order(Order(venue="dex", symbol="BTC", side="buy", quantity=1, price=10, order_type="limit"))
    assert ack.order_id == "o1"  # 未被 deny-by-default 挡（旧行为保留）


def test_guarded_generic_venue_through_orderguard_fail_closed():
    """接活进真钱面：guarded_generic_venue 返 OrderGuard 包裹的 deny-by-default venue；
    CRYPTO_LIVE 缺 nonce 台 → 同一道门 fail-closed（与 relay/lease 一致）。"""
    gate = PolicyGate(tier=TrustTier.CRYPTO_LIVE, symbol_whitelist=frozenset(),
                      max_notional_per_order_usdt=100, max_leverage=1.0, daily_turnover_cap=1000)
    session = MagicMock()
    permission_response = MagicMock()
    permission_response.json.return_value = {"can_trade": True, "can_withdraw": False}
    permission_response.raise_for_status.return_value = None
    session.request.return_value = permission_response
    guarded = guarded_generic_venue(
        _generic_cfg(permission_check={"path": "/permissions", "method": "GET"}),
        gate=gate,
        http=session,
    )  # 无 nonce_ledger
    assert isinstance(guarded, OrderGuard)
    assert guarded._inner._cfg.deny_by_default is True  # 接活恒 deny-by-default
    with pytest.raises(OrderGated):
        guarded.place_order(
            Order(venue="dex", symbol="BTC", side="buy", quantity=1, price=10, order_type="limit", leverage=1.0)
        )


def test_guarded_generic_venue_rejects_missing_permission_probe_before_wrap():
    gate = PolicyGate(tier=TrustTier.CRYPTO_LIVE, symbol_whitelist=frozenset(),
                      max_notional_per_order_usdt=100, max_leverage=1.0, daily_turnover_cap=1000)

    with pytest.raises(PermissionError, match="permission_check"):
        guarded_generic_venue(_generic_cfg(), gate=gate)
