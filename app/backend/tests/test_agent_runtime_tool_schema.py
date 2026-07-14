from __future__ import annotations

from app.agent.agent_runtime import AgentRuntime
from app.agent.llm_client import LLMResponse


class _CapturingLLM:
    provider = "test"

    def __init__(self) -> None:
        self.tools = None

    def chat(self, _messages, *, tools=None, model=None, temperature=0.2):  # noqa: ANN001, ARG002
        self.tools = tools
        return LLMResponse(content="done")


def test_agent_runtime_uses_explicit_role_filtered_tool_schema():
    llm = _CapturingLLM()
    schema = [{"name": "report.generate", "description": "real reporter handler"}]
    runtime = AgentRuntime(llm, tool_schema=schema)

    turn = runtime.run("summarize")

    assert turn.succeeded
    assert llm.tools == schema


def test_agent_runtime_explicit_empty_schema_advertises_no_tools():
    llm = _CapturingLLM()
    runtime = AgentRuntime(llm, tool_schema=[])

    runtime.run("answer without tools")

    assert llm.tools == []
