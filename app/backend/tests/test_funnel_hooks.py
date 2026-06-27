"""v0.9.x · funnel 事件埋点 hooks 端到端测试。

确保 6 个关键 endpoint 触发对应 events：
- user_registered  (POST /api/auth/register)
- safekey_check_completed (POST /api/trading/safety/safekey_check)
- kill_switch_triggered (POST /api/trading/safety/ladder/demote)
- testnet_order_e2e_completed (POST /api/trading/safety/matrix_attempt_e2e)
"""

from __future__ import annotations

import secrets

import pytest
from fastapi.testclient import TestClient

from app.main import EVENT_SERVICE, app


def _uniq(prefix: str) -> str:
    return f"{prefix}_{secrets.token_hex(4)}"


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


def test_register_emits_user_registered(client: TestClient):
    before = EVENT_SERVICE.count("user_registered")
    r = client.post("/api/auth/register", json={
        "username": _uniq("funnel_register"),
        "password": "abc123",
        "display_name": "Funnel",
        "persona_hint": "p0_ashare",
    })
    assert r.status_code == 200, r.json()
    after = EVENT_SERVICE.count("user_registered")
    assert after == before + 1


def test_safekey_check_emits_event(client: TestClient):
    # 先注册 + login 拿 token (unique user)
    uname = _uniq("funnel_safekey")
    r = client.post("/api/auth/register", json={"username": uname, "password": "abc123"})
    token = r.json().get("token")
    assert token, r.json()

    before = EVENT_SERVICE.count("safekey_check_completed")
    r = client.post(
        "/api/trading/safety/safekey_check",
        headers={"authorization": f"Bearer {token}"},
        json={
            "key_id_hash": "test_hash",
            "enable_withdrawals": False,
            "enable_futures": True,
            "ip_restricted": True,
            "venue": "binance_um_futures",
        },
    )
    assert r.status_code == 200
    after = EVENT_SERVICE.count("safekey_check_completed")
    assert after == before + 1


def test_demote_emits_kill_switch_event(client: TestClient):
    uname = _uniq("funnel_demote")
    r = client.post("/api/auth/register", json={"username": uname, "password": "abc12345"})
    token = r.json().get("token")
    assert token
    h = {"authorization": f"Bearer {token}"}

    # 先 SafeKey + 升 level_1 才能 demote
    client.post("/api/trading/safety/safekey_check", headers=h, json={
        "key_id_hash": "h", "enable_withdrawals": False,
    })
    client.post("/api/trading/safety/ladder/promote", headers=h)

    before = EVENT_SERVICE.count("kill_switch_triggered")
    r = client.post("/api/trading/safety/ladder/demote", headers=h, json={
        "reason": "test_kill_switch",
        "severity": "critical",
    })
    assert r.status_code == 200
    after = EVENT_SERVICE.count("kill_switch_triggered")
    assert after == before + 1


def test_matrix_e2e_emits_testnet_order_event(client: TestClient):
    uname = _uniq("funnel_matrix")
    r = client.post("/api/auth/register", json={"username": uname, "password": "abc12345"})
    token = r.json().get("token")
    assert token
    h = {"authorization": f"Bearer {token}"}

    before = EVENT_SERVICE.count("testnet_order_e2e_completed")
    r = client.post("/api/trading/safety/matrix_attempt_e2e", headers=h, json={
        "order_type": "limit",
        "side": "buy",
        "place_ok": True,
        "query_ok": True,
        "cancel_ok": True,
        "reconcile_ok": True,
        "symbol": "BTC-USDT",
        "latency_ms": 230,
    })
    assert r.status_code == 200
    after = EVENT_SERVICE.count("testnet_order_e2e_completed")
    assert after == before + 1


# ============================================================
# Mode 2 DevLocalLLM fallback
# ============================================================


def test_devllm_mode2_refuses_a_share_live():
    from app.agent.llm_client import DevLocalLLM, LLMMessage
    llm = DevLocalLLM()
    reply = llm.chat([
        LLMMessage(role="system", content="你是 QuantBT 的 Mode 2 研究诊断，负责研究诊断 + 风险复核"),
        LLMMessage(role="user", content="我该买入哪只 a股实盘"),
    ])
    assert "拒答" in reply.content or "不能" in reply.content


def test_devllm_mode2_explains_pbo():
    from app.agent.llm_client import DevLocalLLM, LLMMessage
    llm = DevLocalLLM()
    reply = llm.chat([
        LLMMessage(role="system", content="Mode 2 研究诊断"),
        LLMMessage(role="user", content="pbo 是什么"),
    ])
    assert "PBO" in reply.content or "过拟合" in reply.content
    # 应该含阈值数字
    assert "0.2" in reply.content or "0.6" in reply.content


def test_devllm_mode2_explains_dsr():
    from app.agent.llm_client import DevLocalLLM, LLMMessage
    llm = DevLocalLLM()
    reply = llm.chat([
        LLMMessage(role="system", content="Mode 2 教学"),
        LLMMessage(role="user", content="dsr 怎么算"),
    ])
    assert "DSR" in reply.content or "Sharpe" in reply.content


def test_devllm_mode2_socratic_on_credibility_question():
    from app.agent.llm_client import DevLocalLLM, LLMMessage
    llm = DevLocalLLM()
    reply = llm.chat([
        LLMMessage(role="system", content="Mode 2 研究诊断"),
        LLMMessage(role="user", content="这个策略可信吗"),
    ])
    # 应该是提问式复核，而不是直接给答案
    assert "?" in reply.content or "？" in reply.content


def test_devllm_mode2_recommends_experiment_on_improve_question():
    from app.agent.llm_client import DevLocalLLM, LLMMessage
    llm = DevLocalLLM()
    reply = llm.chat([
        LLMMessage(role="system", content="Mode 2 研究诊断"),
        LLMMessage(role="user", content="我该怎么改进这个策略"),
    ])
    assert "实验" in reply.content or "变量" in reply.content or "label" in reply.content.lower()


def test_devllm_non_mode2_context_unchanged():
    """非 Mode 2 上下文不应被 mode2 template 拦截。"""
    from app.agent.llm_client import DevLocalLLM, LLMMessage
    llm = DevLocalLLM()
    reply = llm.chat([
        LLMMessage(role="user", content="A股 周频 选股"),
    ])
    # 命中 _strategy_template (因为 system prompt 不含 Mode 2 特征)
    assert reply.tool_calls  # strategy_template 会返 tool_calls
