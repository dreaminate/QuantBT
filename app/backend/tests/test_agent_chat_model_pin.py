"""跨厂商切模型 S3b-2/3：per-conversation pin 穿进生产 chat 链 + selection API 端点。

钉死：
- _current_agent_gateway(model_pin) 把 default_pin 透传给 build_agent_llm_gateway（gateway 层 S3a 已验）。
- _thread_model_pin 服务端权威读 conversation 的 llm_selection（不信客户端每消息传的 model，K10）。
- PATCH /llm-selection 校验 provider gateway 可路由（api-key configured；订阅 pin 拒待 S5）+ owner-scoped。
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app import main
from app.agent.conversations import ChatService


@pytest.fixture()
def chat_client(monkeypatch, tmp_path):
    monkeypatch.setattr(main, "CHAT_SERVICE", ChatService(tmp_path / "chat.db"))
    main.app.dependency_overrides[main.require_user_dependency] = lambda: SimpleNamespace(
        user_id="u1", username="u1"
    )
    try:
        yield TestClient(main.app), main.CHAT_SERVICE
    finally:
        main.app.dependency_overrides.pop(main.require_user_dependency, None)


# ---------- _provider_is_gateway_routable（K10 校验：只认 api-key configured）----------

def test_provider_routable_only_configured_api_key(monkeypatch):
    monkeypatch.setattr(main, "list_llm_status", lambda *a, **k: [
        {"provider": "openai", "configured": True},
        {"provider": "anthropic", "configured": False},
    ])
    assert main._provider_is_gateway_routable("openai") is True
    assert main._provider_is_gateway_routable("anthropic") is False   # 未配 api-key
    assert main._provider_is_gateway_routable("gemini") is False       # 不在四家


# ---------- _thread_model_pin（服务端权威读）----------

def test_thread_model_pin_reads_conversation_selection(chat_client):
    _, svc = chat_client
    t = svc.start_thread(user_id="u1")
    user = SimpleNamespace(user_id="u1")
    assert main._thread_model_pin(t.thread_id, user) is None  # 默认 auto
    svc.update_llm_selection(t.thread_id, {"mode": "pinned", "provider": "openai", "model": "gpt-4o"}, owner_user_id="u1")
    assert main._thread_model_pin(t.thread_id, user) == ("openai", "gpt-4o")
    svc.update_llm_selection(t.thread_id, {"mode": "auto"}, owner_user_id="u1")
    assert main._thread_model_pin(t.thread_id, user) is None


# ---------- _current_agent_gateway 透传 default_pin（S3b-2 hop 1）----------

def test_current_agent_gateway_threads_default_pin(monkeypatch):
    captured = {}
    monkeypatch.setattr(main, "make_settings_managed_llm_client", lambda **k: None)  # 跳过 Settings preflight
    monkeypatch.setattr(main, "build_agent_llm_gateway", lambda ks, **kw: captured.update(kw) or "GW")
    main._current_agent_gateway(run_id="r1", model_pin=("openai", "gpt-4o"))
    assert captured["default_pin"] == ("openai", "gpt-4o")
    captured.clear()
    main._current_agent_gateway(run_id="r1")  # 无 pin → default_pin=None（Auto 基线）
    assert captured["default_pin"] is None


# ---------- PATCH/GET /api/agent/chat/{thread_id}/llm-selection ----------

def test_patch_selection_pinned_configured_then_get(chat_client, monkeypatch):
    client, svc = chat_client
    monkeypatch.setattr(main, "_provider_is_gateway_routable", lambda p: True)
    t = svc.start_thread(user_id="u1")
    r = client.patch(f"/api/agent/chat/{t.thread_id}/llm-selection",
                     json={"mode": "pinned", "provider": "openai", "model": "gpt-4o"})
    assert r.status_code == 200
    assert r.json()["llm_selection"]["provider"] == "openai"
    g = client.get(f"/api/agent/chat/{t.thread_id}/llm-selection")
    assert g.status_code == 200 and g.json()["llm_selection"]["model"] == "gpt-4o"


def test_patch_selection_unconfigured_provider_rejected(chat_client, monkeypatch):
    client, svc = chat_client
    monkeypatch.setattr(main, "_provider_is_gateway_routable", lambda p: False)  # 未配/不可路由
    t = svc.start_thread(user_id="u1")
    r = client.patch(f"/api/agent/chat/{t.thread_id}/llm-selection",
                     json={"mode": "pinned", "provider": "openai", "model": "gpt-4o"})
    assert r.status_code == 409  # 明确拒,不静默存无法路由的 pin


def test_patch_selection_missing_fields_422(chat_client, monkeypatch):
    client, svc = chat_client
    monkeypatch.setattr(main, "_provider_is_gateway_routable", lambda p: True)
    t = svc.start_thread(user_id="u1")
    r = client.patch(f"/api/agent/chat/{t.thread_id}/llm-selection", json={"mode": "pinned", "provider": "openai"})
    assert r.status_code == 422  # 缺 model


def test_patch_selection_auto_clears(chat_client, monkeypatch):
    client, svc = chat_client
    monkeypatch.setattr(main, "_provider_is_gateway_routable", lambda p: True)
    t = svc.start_thread(user_id="u1")
    client.patch(f"/api/agent/chat/{t.thread_id}/llm-selection",
                 json={"mode": "pinned", "provider": "openai", "model": "gpt-4o"})
    r = client.patch(f"/api/agent/chat/{t.thread_id}/llm-selection", json={"mode": "auto"})
    assert r.status_code == 200 and r.json()["llm_selection"] == {"mode": "auto"}
    assert main._thread_model_pin(t.thread_id, SimpleNamespace(user_id="u1")) is None


def test_patch_selection_owner_scoped(chat_client, monkeypatch):
    client, svc = chat_client
    monkeypatch.setattr(main, "_provider_is_gateway_routable", lambda p: True)
    t = svc.start_thread(user_id="someone_else")  # 别的 owner 的 thread
    r = client.patch(f"/api/agent/chat/{t.thread_id}/llm-selection",
                     json={"mode": "pinned", "provider": "openai", "model": "gpt-4o"})
    assert r.status_code == 404  # 跨 owner = 不存在,不泄漏
