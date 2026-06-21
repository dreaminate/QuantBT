"""P2 模拟台后端接真 · /api/paper/* 端点 + 治理对抗测试。

对抗（种已知坏门必抓）：
- 对抗#1 A股 live 下单端点必拒（致命错误防线：A股永不 live）。
- 对抗#2 晋级裸翻必拒（INV-5：无背书 / 自审 / 不可跳级 都拒）。
- 对抗#3 风险门会话内改必拒，且被拒事件入哈希链（会话外不可改 · 防篡改证据）。
不破基线：端点正常读路径（status/positions/fills/equity_log/promotion）返 200 + 合理结构。
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.auth import require_user_dependency
from app.execution.base import Order
from app.main import PAPER_DESK, app
from app.paper.desk import (
    AShareLiveForbidden,
    PaperDeskService,
    RiskGateMutationForbidden,
    aggregate_promotion_checks,
)


@pytest.fixture
def client():
    app.dependency_overrides[require_user_dependency] = lambda: SimpleNamespace(user_id="tester")
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.pop(require_user_dependency, None)


# ════════════════ 基线：正常读路径 ════════════════
def test_runs_list_and_status(client):
    runs = client.get("/api/paper/runs").json()["runs"]
    assert len(runs) >= 1
    ids = {r["id"] for r in runs}
    assert "weekly_cn_multifactor" in ids
    st = client.get("/api/paper/runs/weekly_cn_multifactor/status")
    assert st.status_code == 200
    body = st.json()
    assert body["run_id"] == "weekly_cn_multifactor"
    assert "config" in body and "balance" in body and "positions" in body


def test_status_404_unknown_run(client):
    assert client.get("/api/paper/runs/__nope__/status").status_code == 404


def test_book_endpoints_shape(client):
    rid = "weekly_cn_multifactor"
    assert client.get(f"/api/paper/runs/{rid}/positions").status_code == 200
    bal = client.get(f"/api/paper/runs/{rid}/balance").json()
    assert "total_equity" in bal and "cash" in bal
    fills = client.get(f"/api/paper/runs/{rid}/fills").json()["fills"]
    assert isinstance(fills, list)
    eq = client.get(f"/api/paper/runs/{rid}/equity_log").json()["equity_log"]
    assert isinstance(eq, list)


def test_fills_derived_from_audit_log():
    """成交回报从 ExecutionAuditLog(paper_fill) 派生，不另存第二份。"""

    svc = PaperDeskService()
    rec = svc.register_run(
        run_id="t1", name="t1", origin="o", market="crypto", symbols=["BTCUSDT"],
        bench="BTC", creator="c", equity_log_path=_tmp_eqlog("t1"),
    )
    rec.venue.place_order(Order(venue="paper", symbol="BTCUSDT", side="buy", quantity=1.0))
    rec.venue.feed_bar({"symbol": "BTCUSDT", "open": 100, "high": 101, "low": 99, "close": 100})
    fills = svc.fills("t1")
    assert len(fills) == 1 and fills[0]["symbol"] == "BTCUSDT" and fills[0]["status"] == "filled"


# ════════════════ 对抗#1 · A股 live 下单恒拒 ════════════════
def test_ashare_live_order_always_rejected(client):
    r = client.post("/api/paper/runs/weekly_cn_multifactor/live_order",
                    json={"symbol": "600519", "side": "buy", "quantity": 100})
    assert r.status_code == 403
    assert r.json()["detail"]["a_share_live_forbidden"] is True


def test_ashare_live_order_records_violation_in_chain(client):
    """A股 live 下单被拒 → 事件入风险违规哈希链（审计留痕）。"""

    before = client.get("/api/paper/runs/weekly_cn_multifactor/risk_gate").json()["violation_count"]
    client.post("/api/paper/runs/weekly_cn_multifactor/live_order", json={"symbol": "600519"})
    after = client.get("/api/paper/runs/weekly_cn_multifactor/risk_gate").json()["violation_count"]
    assert after == before + 1


def test_ashare_live_never_reaches_venue():
    """服务层：A股 attempt_live_order 永不下到 venue（key 路径不可达）。"""

    svc = PaperDeskService()
    svc.register_run(run_id="cn1", name="cn1", origin="o", market="equity_cn",
                     symbols=["600519"], bench="500", creator="c",
                     equity_log_path=_tmp_eqlog("cn1"))
    with pytest.raises(AShareLiveForbidden):
        svc.attempt_live_order("cn1", {"symbol": "600519", "side": "buy", "quantity": 100})
    # venue 无任何 paper_place（更别说 live）——证明未进下单路径
    assert svc.fills("cn1") == []


# ════════════════ 对抗#2 · 晋级裸翻必拒（INV-5）════════════════
def test_promotion_naked_flip_without_endorsement_rejected(client):
    """无验证背书（endorsement_ref）直接审批 → 422 裸翻必拒。"""

    gate = client.post("/api/paper/runs/weekly_cn_multifactor/promotion/open",
                       json={"creator": "alice"}).json()
    r = client.post(f"/api/paper/promotion/{gate['gate_id']}/approve",
                    json={"approver": "bob", "reason": "looks good"})  # 缺 endorsement_ref
    assert r.status_code == 422
    assert r.json()["detail"]["endorsement_or_reason_missing"] is True
    # 未晋级
    assert client.get("/api/paper/runs/weekly_cn_multifactor/promotion").json()["promoted"] is False


def test_promotion_self_approve_rejected(client):
    """approver == creator（自审）→ 422（生成≠验证不可自我满足）。"""

    gate = client.post("/api/paper/runs/weekly_cn_multifactor/promotion/open",
                       json={"creator": "alice"}).json()
    r = client.post(f"/api/paper/promotion/{gate['gate_id']}/approve",
                    json={"approver": "alice", "endorsement_ref": "verdict_x", "reason": "ok"})
    assert r.status_code == 422
    assert r.json()["detail"]["approver_equals_creator"] is True


def test_promotion_cannot_skip_gates(client):
    """4 门未全过的 run（dividend_lowvol_cn：14天<28 且超额<0）→ 即便有背书也拒（不可跳级）。"""

    gate = client.post("/api/paper/runs/dividend_lowvol_cn/promotion/open",
                       json={"creator": "alice"}).json()
    assert gate["eligible"] is False
    r = client.post(f"/api/paper/promotion/{gate['gate_id']}/approve",
                    json={"approver": "bob", "endorsement_ref": "verdict_x", "reason": "ok"})
    assert r.status_code == 422
    assert r.json()["detail"]["gate_not_eligible"] is True


def test_promotion_proper_human_approval_succeeds(client):
    """合规人工审批（approver≠creator + 背书 + 4 门全过 + 理由）→ 晋级成功。"""

    gate = client.post("/api/paper/runs/crypto_perp_mom/promotion/open",
                       json={"creator": "alice"}).json()
    assert gate["eligible"] is True
    r = client.post(f"/api/paper/promotion/{gate['gate_id']}/approve",
                    json={"approver": "bob", "endorsement_ref": "verdict_crypto_1",
                          "reason": "异模型对账一致，超额稳定"})
    assert r.status_code == 200
    body = r.json()
    assert body["decision"] == "approved" and body["approver"] == "bob"
    assert body["endorsement_ref"] == "verdict_crypto_1"


def test_promotion_aggregation_4_gates():
    """判定聚合恰 4 门：天数 / 超额 / 0违规 / 衰减。"""

    svc = PaperDeskService()
    rec = svc.register_run(run_id="agg", name="agg", origin="o", market="crypto",
                           symbols=["BTCUSDT"], bench="BTC", creator="c",
                           equity_log_path=_tmp_eqlog("agg"),
                           days_running=30, paper_excess_return=0.02,
                           backtest_annual=0.2, paper_annual=0.18)
    checks, eligible = aggregate_promotion_checks(rec, svc.risk)
    assert [c["key"] for c in checks] == ["days", "excess", "zero_violation", "decay"]
    assert eligible is True
    # 种坏门：注入一条违规 → 0违规门翻红 → 不合格
    svc.risk.record_violation("agg", title="x", detail="触线")
    _checks, elig2 = aggregate_promotion_checks(rec, svc.risk)
    assert elig2 is False


# ════════════════ 对抗#3 · 风险门会话内改必拒 + 入哈希链 ════════════════
def test_risk_gate_mutation_forbidden(client):
    """会话内改门请求 → 409（会话外不可改），绝不真改门。"""

    r = client.post("/api/paper/runs/weekly_cn_multifactor/risk_gate/mutate",
                    json={"leverage": 5.0})
    assert r.status_code == 409
    assert r.json()["detail"]["risk_gate_frozen"] is True


def test_risk_gate_mutation_logged_to_chain():
    """被拒的改门请求入 append-only 哈希链（防篡改证据），链完整。"""

    svc = PaperDeskService()
    svc.register_run(run_id="rg", name="rg", origin="o", market="crypto",
                     symbols=["BTCUSDT"], bench="BTC", creator="c",
                     equity_log_path=_tmp_eqlog("rg"))
    n0 = len(svc.risk.chain("rg"))
    with pytest.raises(RiskGateMutationForbidden):
        svc.risk.attempt_mutation("rg", {"leverage": 99}, actor="agent")
    chain = svc.risk.chain("rg")
    assert len(chain) == n0 + 1
    assert chain[-1]["kind"] == "gate_mutation_denied"
    assert svc.risk.verify_chain("rg") is True


def test_risk_gate_frozen_hash_stable():
    """门限发布即冻结哈希；同输入复发布哈希一致（内容寻址单一源）。"""

    svc = PaperDeskService()
    svc.register_run(run_id="fz", name="fz", origin="o", market="crypto",
                     symbols=["BTCUSDT"], bench="BTC", creator="c",
                     equity_log_path=_tmp_eqlog("fz"))
    h1 = svc.risk.frozen_hash("fz")
    assert h1 and len(h1) == 16  # 全库 16 位哈希不变量
    h2 = svc.risk.publish("fz", svc.risk._limits["fz"])  # noqa: SLF001
    assert h2 == h1


def test_chain_tamper_detected():
    """种坏门：篡改链中一条 → verify_chain 必抓（断链）。"""

    svc = PaperDeskService()
    svc.register_run(run_id="tp", name="tp", origin="o", market="crypto",
                     symbols=["BTCUSDT"], bench="BTC", creator="c",
                     equity_log_path=_tmp_eqlog("tp"))
    svc.risk.record_violation("tp", title="a", detail="d1")
    svc.risk.record_violation("tp", title="b", detail="d2")
    assert svc.risk.verify_chain("tp") is True
    # 直接改内部链的历史条目 detail（模拟篡改）
    svc.risk._chain["tp"][0]["detail"] = "篡改后的内容"  # noqa: SLF001
    assert svc.risk.verify_chain("tp") is False


# ---- helper ----
def _tmp_eqlog(name: str):
    import tempfile
    from pathlib import Path

    return Path(tempfile.mkdtemp()) / f"{name}_equity.jsonl"
