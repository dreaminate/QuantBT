"""M14 · Agent 运行层。

GOAL §M14 设计：用户用对话或上传代码发起研究动作。这里提供：

- `LLMClient` 抽象 + 三档实现：claude / openai / qwen + DevLocalLLM（开发期 mock）
- `tool_schema.py`：把后端所有能力翻译成 OpenAPI 描述
- `slot_filling.py`：自然语言 → StrategyGoal 槽位补全（dev-mode 用规则 + 简化模板）
- `code_replicator.py`：vnpy / backtrader / pandas 策略代码 → AST 改写到 QuantBT 标准模板
- `agent_runtime.py`：状态机 + reAct loop（开发期由 DevLocalLLM 驱动）
"""

from __future__ import annotations

from .agent_runtime import AgentRAGContext, AgentRAGContextHit, AgentRuntime, AgentStep, AgentTurn
from .code_replicator import CodeReplicator, ReplicationReport
from .llm_client import DevLocalLLM, LLMClient, LLMMessage, LLMResponse, NoLLMConfigured
from .llm_providers import (
    AnthropicLLM,
    OpenAICompatibleLLM,
    OpenAILLM,
    ProviderName,
    QwenLLM,
    ensure_settings_managed_llm_provider,
    list_llm_status,
    llm_credential_pool_ref,
    llm_routing_policy_ref,
    llm_secret_ref,
    make_llm_client,
    make_settings_managed_llm_client,
)
from .slot_filling import StrategyGoalSlotFiller
from .tool_schema import TOOL_SCHEMA, tool_openapi_skeleton

__all__ = [
    "AgentRuntime",
    "AgentRAGContext",
    "AgentRAGContextHit",
    "AgentStep",
    "AgentTurn",
    "AnthropicLLM",
    "CodeReplicator",
    "DevLocalLLM",
    "LLMClient",
    "LLMMessage",
    "LLMResponse",
    "NoLLMConfigured",
    "OpenAICompatibleLLM",
    "OpenAILLM",
    "ProviderName",
    "QwenLLM",
    "ReplicationReport",
    "StrategyGoalSlotFiller",
    "TOOL_SCHEMA",
    "ensure_settings_managed_llm_provider",
    "list_llm_status",
    "llm_credential_pool_ref",
    "llm_routing_policy_ref",
    "llm_secret_ref",
    "make_llm_client",
    "make_settings_managed_llm_client",
    "tool_openapi_skeleton",
]
