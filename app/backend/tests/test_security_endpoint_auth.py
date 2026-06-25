"""端点鉴权对抗测试（安全审计 pass3 #2/#4：补未披露的 unauthed 数据泄露端点）。

门必抓：
- copy_trade signals/executions + data export 端点**匿名必 401**（绝不未登录拉数据）。
- copy_trade signals/executions **按归属过滤**：跨租户看不到他人下单意图/执行；自己看得到自己的。
"""

from __future__ import annotations

from types import SimpleNamespace

from fastapi.testclient import TestClient

from app import main
from app.auth import require_user_dependency
from app.copy_trade.service import CopyTradeService


def _client() -> TestClient:
    main.app.dependency_overrides.pop(require_user_dependency, None)  # 确保无残留 override（测匿名）
    return TestClient(main.app)


def test_unauthed_data_leak_endpoints_blocked():
    """**数据泄露门**：4 个端点匿名访问 → 401（MUT：去掉 Depends → 200，断言崩）。"""
    client = _client()
    for path in (
        "/api/copy_trade/signals",
        "/api/copy_trade/executions",
        "/api/data/export/size",
        "/api/data/export",
    ):
        r = client.get(path)
        assert r.status_code == 401, f"{path} 匿名可访问（未鉴权数据泄露）：得 {r.status_code}"


def test_copy_trade_signals_owner_filtered(monkeypatch, tmp_path):
    """**跨租户门**：user A（无关）看不到 user B master 的信号（下单意图+note）；user B 看得到自己的。

    MUT（去掉归属过滤·退回 list_signals(master_id=...)）→ A 看到 B 的信号，断言崩。
    """
    svc = CopyTradeService(tmp_path / "ct.db")
    m_b = svc.register_master("userB", "B")
    svc.publish_signal(m_b.master_id, "userB", symbol="BTCUSDT", side="buy", quantity=1.0, note="私有下单意图")
    monkeypatch.setattr(main, "COPY_TRADE_SERVICE", svc)
    client = TestClient(main.app)
    try:
        main.app.dependency_overrides[require_user_dependency] = lambda: SimpleNamespace(user_id="userA")
        rA = client.get("/api/copy_trade/signals")
        assert rA.status_code == 200 and rA.json() == [], "跨租户泄露：A 看到了 B 的信号"
        main.app.dependency_overrides[require_user_dependency] = lambda: SimpleNamespace(user_id="userB")
        rB = client.get("/api/copy_trade/signals")
        assert rB.status_code == 200 and len(rB.json()) == 1 and rB.json()[0]["symbol"] == "BTCUSDT"
        # 越权指定他人 master_id → 403（A 指 B 的 master）
        main.app.dependency_overrides[require_user_dependency] = lambda: SimpleNamespace(user_id="userA")
        r403 = client.get(f"/api/copy_trade/signals?master_id={m_b.master_id}")
        assert r403.status_code == 403
    finally:
        main.app.dependency_overrides.pop(require_user_dependency, None)


def test_copy_trade_executions_owner_filtered(monkeypatch, tmp_path):
    """executions 跨租户门：无关 user A 看不到他人执行（无 master/订阅 → 空集）。"""
    svc = CopyTradeService(tmp_path / "ct2.db")
    monkeypatch.setattr(main, "COPY_TRADE_SERVICE", svc)
    client = TestClient(main.app)
    try:
        main.app.dependency_overrides[require_user_dependency] = lambda: SimpleNamespace(user_id="userA")
        r = client.get("/api/copy_trade/executions")
        assert r.status_code == 200 and r.json() == []   # 无关用户无任何可见执行
    finally:
        main.app.dependency_overrides.pop(require_user_dependency, None)
