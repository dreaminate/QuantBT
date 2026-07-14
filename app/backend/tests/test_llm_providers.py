from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest

from app.agent import (
    AnthropicLLM,
    DevLocalLLM,
    LLMMessage,
    NoLLMConfigured,
    OpenAILLM,
    QwenLLM,
    make_llm_client,
    make_settings_managed_llm_client,
)
from app.research_os import PersistentOnboardingRegistry
from app.security import InMemoryKeystore, KeystoreRecord, SecureKeystore


def _mock_session(json_payload: dict) -> MagicMock:
    session = MagicMock()
    resp = MagicMock()
    resp.json.return_value = json_payload
    resp.raise_for_status.return_value = None
    resp.status_code = 200
    session.post.return_value = resp
    return session


def test_anthropic_llm_calls_messages_endpoint_with_tools() -> None:
    session = _mock_session(
        {
            "content": [
                {"type": "text", "text": "好的，我先建 StrategyGoal。"},
                {"type": "tool_use", "id": "tu_1", "name": "strategy_goal.create", "input": {"name": "x", "asset_class": "equity_cn"}},
            ]
        }
    )
    llm = AnthropicLLM(api_key="sk-ant-mock", session=session)
    tools = [{"name": "strategy_goal.create", "description": "build", "parameters": {"type": "object"}}]
    resp = llm.chat(
        [LLMMessage(role="system", content="be brief"), LLMMessage(role="user", content="A股 周频")],
        tools=tools,
    )
    assert "StrategyGoal" in resp.content
    assert resp.tool_calls and resp.tool_calls[0]["name"] == "strategy_goal.create"
    args = json.loads(resp.tool_calls[0]["arguments"])
    assert args["asset_class"] == "equity_cn"
    sent = session.post.call_args
    assert "messages" in sent.kwargs["json"]
    assert sent.kwargs["headers"]["x-api-key"] == "sk-ant-mock"


def test_openai_llm_handles_tool_calls() -> None:
    session = _mock_session(
        {
            "choices": [
                {
                    "message": {
                        "role": "assistant",
                        "content": "执行中",
                        "tool_calls": [
                            {
                                "id": "call_1",
                                "type": "function",
                                "function": {"name": "factor.run_ic", "arguments": "{\"factor_ids\":\"a,b\"}"},
                            }
                        ],
                    }
                }
            ]
        }
    )
    llm = OpenAILLM(api_key="sk-mock", session=session)
    resp = llm.chat([LLMMessage(role="user", content="hi")])
    assert resp.tool_calls[0]["name"] == "factor.run_ic"
    assert resp.tool_calls[0]["arguments"] == '{"factor_ids":"a,b"}'


def test_qwen_proxies_through_openai_protocol() -> None:
    session = _mock_session(
        {"choices": [{"message": {"role": "assistant", "content": "hello"}}]}
    )
    llm = QwenLLM(api_key="qwen-mock", session=session)
    resp = llm.chat([LLMMessage(role="user", content="hi")])
    assert resp.content == "hello"
    sent = session.post.call_args
    assert "dashscope" in sent.args[0]


def test_make_llm_client_uses_keystore_when_no_env(monkeypatch) -> None:
    monkeypatch.delenv("LLM_PROVIDER", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("DASHSCOPE_API_KEY", raising=False)
    ks = SecureKeystore(InMemoryKeystore())
    ks.store(KeystoreRecord(name="llm_anthropic", api_key="sk-ant-mock", api_secret="sk-ant-mock"))
    client = make_llm_client(keystore=ks)
    assert isinstance(client, AnthropicLLM)


def test_make_llm_client_respects_env(monkeypatch) -> None:
    monkeypatch.setenv("LLM_PROVIDER", "openai")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-openai-mock")
    client = make_llm_client()
    assert isinstance(client, OpenAILLM)


def test_make_llm_client_denies_when_unconfigured(monkeypatch) -> None:
    """deny-by-default（GOAL §8 no-silent-mock）：未配任何 provider → 抛 NoLLMConfigured，
    绝不静默落 DevLocalLLM。

    行为变更（诚实更新）：旧 `test_make_llm_client_fallback_to_dev_local` 断言 fallback→DevLocalLLM；
    用户已拍板「彻底移除静默 DevLocalLLM 兜底」，故本测试翻为断言明确报错（非偷削覆盖）。
    """
    monkeypatch.delenv("LLM_PROVIDER", raising=False)
    for env_var in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "DASHSCOPE_API_KEY"):
        monkeypatch.delenv(env_var, raising=False)
    with pytest.raises(NoLLMConfigured):
        make_llm_client()


def test_make_llm_client_deny_never_returns_devlocal(monkeypatch) -> None:
    """对抗（种坏门必抓）：未配时即便不抛、也绝不能产出 DevLocalLLM 这种 mock client。

    若有人把静默兜底加回来（`return DevLocalLLM()`），本测试会拿到 DevLocalLLM 实例而非异常 → 必红。
    """
    monkeypatch.delenv("LLM_PROVIDER", raising=False)
    for env_var in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "DASHSCOPE_API_KEY"):
        monkeypatch.delenv(env_var, raising=False)
    ks = SecureKeystore(InMemoryKeystore())  # 空 keystore：无任何 provider 配置
    produced: object | None = None
    try:
        produced = make_llm_client(keystore=ks)
    except NoLLMConfigured:
        produced = None
    assert not isinstance(produced, DevLocalLLM), "deny-by-default 被违反：缺配置仍静默落 DevLocalLLM"
    assert produced is None


def test_make_settings_managed_denies_when_unconfigured(tmp_path, monkeypatch) -> None:
    """deny-by-default：未显式指定 provider 且无任何就绪 Settings-managed provider →
    抛 NoLLMConfigured（旧行为是静默落 DevLocalLLM，§8 拒）。
    """
    monkeypatch.delenv("LLM_PROVIDER", raising=False)
    for env_var in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "DASHSCOPE_API_KEY"):
        monkeypatch.delenv(env_var, raising=False)
    ks = SecureKeystore(InMemoryKeystore())
    registry = PersistentOnboardingRegistry(tmp_path / "onboarding_settings.jsonl")
    with pytest.raises(NoLLMConfigured):
        make_settings_managed_llm_client(
            keystore=ks,
            registry=registry,
            owner_user_id="service:test-llm-gateway",
        )


def test_make_llm_client_explicit_provider_with_explicit_key() -> None:
    client = make_llm_client(provider="anthropic", api_key="sk-ant-explicit")
    assert isinstance(client, AnthropicLLM)
