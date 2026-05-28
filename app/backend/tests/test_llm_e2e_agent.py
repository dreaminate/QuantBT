"""task 35 · 真 LLM 多轮 Agent 对话端到端（用 mock 锁定协议契约）。

锁定行为：
1. 第一轮 LLM 返回 tool_call → AgentRuntime 派发 → tool 返回结果
2. 第二轮把 tool result 喂回 LLM → LLM 给最终终态回答
3. 重试：504 / timeout 自动指数退避（最多 3 次）
4. 协议结构：assistant.content + tool_calls；tool.content（json string）
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest
import requests

from app.agent import AgentRuntime, LLMMessage, OpenAILLM


def _resp(payload: dict, status: int = 200) -> MagicMock:
    r = MagicMock()
    r.status_code = status
    r.reason = "OK" if status == 200 else "Server Error"
    r.json.return_value = payload
    return r


def test_real_llm_multi_turn_e2e_with_tool_dispatch() -> None:
    """模拟 highway/anthropic 代理两轮对话：第一轮 tool_call → 第二轮终态文本。"""

    session = MagicMock()
    first = _resp({
        "choices": [{
            "message": {
                "role": "assistant",
                "content": "好的，我先建 StrategyGoal。",
                "tool_calls": [{
                    "id": "call_1",
                    "type": "function",
                    "function": {
                        "name": "strategy_goal.create",
                        "arguments": json.dumps({
                            "name": "A股周频选股",
                            "asset_class": "equity_cn",
                            "horizon": "weekly",
                        }),
                    },
                }],
            }
        }]
    })
    second = _resp({
        "choices": [{
            "message": {
                "role": "assistant",
                "content": "✅ StrategyGoal 已落库。下一步建议拉沪深 300 数据 + 跑 alpha_lite 5 因子 IC。",
            }
        }]
    })
    session.post.side_effect = [first, second]
    llm = OpenAILLM(api_key="sk-mock", session=session)

    calls_seen: list[dict] = []

    def _fake_strategy_goal_tool(_name, args):
        calls_seen.append(args)
        return {"strategy_goal_id": "sg-1", "echo": args}

    runtime = AgentRuntime(llm, tools={"strategy_goal.create": _fake_strategy_goal_tool})
    turn = runtime.run("我想做 A股 周频 选股")

    assert turn.succeeded
    assert "StrategyGoal" in turn.final_message
    assert len(calls_seen) == 1
    assert calls_seen[0]["asset_class"] == "equity_cn"
    # 至少应有：user → assistant(w/ tool_call) → tool → assistant(终态)
    roles = [s.role for s in turn.steps]
    assert roles == ["user", "assistant", "tool", "assistant"]
    # 协议契约：tool step 的 content 是 json
    tool_step = turn.steps[2]
    parsed = json.loads(tool_step.content)
    assert parsed["strategy_goal_id"] == "sg-1"


def test_real_llm_5xx_auto_retry() -> None:
    session = MagicMock()
    err = _resp({"error": "upstream timeout"}, status=504)
    err.raise_for_status.side_effect = requests.HTTPError("504", response=err)
    good = _resp({"choices": [{"message": {"role": "assistant", "content": "ok"}}]})
    # 第一次 504，第二次 200
    session.post.side_effect = [err, good]
    llm = OpenAILLM(api_key="sk-mock", session=session)
    resp = llm.chat([LLMMessage(role="user", content="hi")])
    assert resp.content == "ok"
    assert session.post.call_count == 2


def test_real_llm_timeout_auto_retry() -> None:
    session = MagicMock()
    good = _resp({"choices": [{"message": {"role": "assistant", "content": "yeah"}}]})
    session.post.side_effect = [requests.Timeout("read timeout"), good]
    llm = OpenAILLM(api_key="sk-mock", session=session)
    resp = llm.chat([LLMMessage(role="user", content="hi")])
    assert resp.content == "yeah"
    assert session.post.call_count == 2


def test_real_llm_eventually_fails_after_3_retries() -> None:
    session = MagicMock()
    err = _resp({}, status=503)
    err.raise_for_status.side_effect = requests.HTTPError("503", response=err)
    session.post.return_value = err
    llm = OpenAILLM(api_key="sk-mock", session=session)
    with pytest.raises(requests.HTTPError):
        llm.chat([LLMMessage(role="user", content="hi")])
    assert session.post.call_count == 3
