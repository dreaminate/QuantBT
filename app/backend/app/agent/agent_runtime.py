"""M14 · Agent 状态机 / reAct loop。

简化设计：
1. user 发一条消息 → AgentTurn.start
2. 把 user message + tool_schema 发给 LLMClient
3. 拿到 LLMResponse：
   - 有 tool_calls → 派发到 ToolDispatcher，把结果作为 tool message 写回，loop 回到步骤 2
   - 否则当作终态回复给 user
4. 步数上限避免死循环
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from typing import Any, Callable

from .llm_client import LLMClient, LLMMessage, LLMResponse
from .tool_schema import TOOL_SCHEMA


ToolHandler = Callable[[str, dict[str, Any]], dict[str, Any]]


@dataclass
class AgentStep:
    role: str
    content: str
    timestamp_utc: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    tool_call_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class AgentTurn:
    user_input: str
    steps: list[AgentStep] = field(default_factory=list)
    final_message: str = ""
    succeeded: bool = False


class AgentRuntime:
    def __init__(
        self,
        llm: LLMClient,
        tools: dict[str, ToolHandler] | None = None,
        max_steps: int = 6,
        system_prompt: str = "You are QuantBT Agent — 一个量化全栈助手。",
    ) -> None:
        self._llm = llm
        self._tools = tools or {}
        self._max_steps = max_steps
        self._system = system_prompt

    def register_tool(self, name: str, handler: ToolHandler) -> None:
        self._tools[name] = handler

    def run(self, user_input: str) -> AgentTurn:
        turn = AgentTurn(user_input=user_input)
        messages: list[LLMMessage] = [
            LLMMessage(role="system", content=self._system),
            LLMMessage(role="user", content=user_input),
        ]
        turn.steps.append(AgentStep(role="user", content=user_input))
        for _ in range(self._max_steps):
            response = self._llm.chat(messages, tools=TOOL_SCHEMA)
            messages.append(
                LLMMessage(role="assistant", content=response.content, tool_calls=response.tool_calls)
            )
            turn.steps.append(
                AgentStep(role="assistant", content=response.content, tool_calls=response.tool_calls)
            )
            if not response.tool_calls:
                turn.final_message = response.content
                turn.succeeded = True
                return turn
            tool_results: list[LLMMessage] = []
            for call in response.tool_calls:
                tool_name = call.get("name") or call.get("function", {}).get("name", "")
                arguments_raw = call.get("arguments") or call.get("function", {}).get("arguments") or "{}"
                if isinstance(arguments_raw, str):
                    try:
                        arguments = json.loads(arguments_raw)
                    except Exception:  # noqa: BLE001
                        arguments = {"_raw": arguments_raw}
                else:
                    arguments = arguments_raw
                handler = self._tools.get(tool_name)
                if handler is None:
                    payload = {"error": f"未注册工具 {tool_name}"}
                else:
                    try:
                        payload = handler(tool_name, arguments)
                    except Exception as exc:  # noqa: BLE001
                        payload = {"error": f"{type(exc).__name__}: {exc}"}
                tool_results.append(
                    LLMMessage(
                        role="tool",
                        content=json.dumps(payload, ensure_ascii=False),
                        tool_call_id=call.get("id"),
                        name=tool_name,
                    )
                )
                turn.steps.append(
                    AgentStep(
                        role="tool",
                        content=json.dumps(payload, ensure_ascii=False),
                        tool_call_id=call.get("id"),
                    )
                )
            messages.extend(tool_results)
        turn.final_message = "（达到最大步数仍未结束。建议拆解任务再试。）"
        return turn


__all__ = ["AgentRuntime", "AgentStep", "AgentTurn", "ToolHandler"]
