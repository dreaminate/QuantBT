from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest

from app.agent import (
    AnthropicLLM,
    DevLocalLLM,
    LLMMessage,
    OpenAILLM,
    QwenLLM,
    make_llm_client,
)
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


def test_make_llm_client_fallback_to_dev_local(monkeypatch) -> None:
    monkeypatch.delenv("LLM_PROVIDER", raising=False)
    for env_var in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "DASHSCOPE_API_KEY"):
        monkeypatch.delenv(env_var, raising=False)
    client = make_llm_client()
    assert isinstance(client, DevLocalLLM)


def test_make_llm_client_explicit_provider_with_explicit_key() -> None:
    client = make_llm_client(provider="anthropic", api_key="sk-ant-explicit")
    assert isinstance(client, AnthropicLLM)
