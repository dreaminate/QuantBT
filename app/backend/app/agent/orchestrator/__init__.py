"""Agent Orchestrator（GOAL §7 Multi-Agent Research OS）——A-AGENT-ORCH·LINE-A-AGENT 续。

GOAL §7 链路的中段治理核：Agent Shell → **Agent Orchestrator** → LLM Gateway → role agent dispatch。
LLM Gateway（A-AGENT-GW·640b66a0）已建唯一调用入口；本包在其上建编排核：

- `AgentOrchestrator`：五形态（Plan/ReAct/Review/Replay/Repair）+ DAG 治理 dispatch + 24 可见事件投影
  + 唯一图写口（canonical command）。
- `roles`：GOAL §7 的 12 role agent + 工具权限按台过滤。
- `governance`：`GovernedToolDispatcher`——工具派发唯一闸（绕过 DAG 自由派发 → 拒）。
- `llm_adapter`：`GatewayLLMAdapter`——role agent 的 LLM 全经 LLM Gateway（绕过 Gateway → 不可准入）。
- `events`：24 可见事件 + 可见性边界（secret/隐藏思维链不投影）。
- `plan`：Plan 产物 + 完成/代码改动/方法学的可证伪门。

**wrap 现有 `agent_runtime.py`·不重建**；LLM 全经 `llm/gateway.py`；图写经 `graph/research_graph.py`
的 canonical command；DAG 治理经 `dag/kernel.py` 的 `DurableExecutor`；身份复用 `lineage/ids.py`。
"""

from __future__ import annotations

from .events import (
    GATEWAY_EVENT_KINDS,
    VISIBLE_EVENT_KINDS,
    VISIBLE_EVENT_SET,
    EventProjectionError,
    EventProjector,
    WorkflowEvent,
    assert_event_clean,
)
from .governance import (
    DAGBypassError,
    GovernanceError,
    GovernedToolDispatcher,
    NodeExecutionContext,
    ToolCallRecord,
    ToolPermissionError,
    ToolViolation,
)
from .llm_adapter import GatewayBypassError, GatewayLLMAdapter, assert_llm_admissible
from .orchestrator import (
    MODES,
    AgentOrchestrator,
    GraphWriteAuthorityError,
    OrchestrationResult,
    OrchestratorError,
    VerifierIndependenceError,
    make_executor,
    role_node_op,
)
from .plan import (
    AcceptanceGate,
    AgentCodeChange,
    AgentCodeChangeError,
    AgentCompletion,
    AgentCompletionError,
    AgentPlan,
    AgentTodo,
    MethodologyAutonomyError,
    MethodologyChoiceRecord,
    PlanError,
    assert_methodology_user_decided,
)
from .roles import (
    ROLE_AGENTS,
    ROLE_NAMES,
    RoleAgent,
    UnknownRoleError,
    get_role,
    is_verifier,
)
from .trust_advisory import (
    TRUST_ADVISORY_SOURCE,
    TrustAdvisory,
    run_trust_advisory,
    safety_bypass_invariants,
    summarize_trust_for_event,
)

__all__ = [
    # orchestrator
    "AgentOrchestrator",
    "OrchestrationResult",
    "OrchestratorError",
    "VerifierIndependenceError",
    "GraphWriteAuthorityError",
    "MODES",
    "make_executor",
    "role_node_op",
    # events
    "VISIBLE_EVENT_KINDS",
    "VISIBLE_EVENT_SET",
    "GATEWAY_EVENT_KINDS",
    "EventProjector",
    "EventProjectionError",
    "WorkflowEvent",
    "assert_event_clean",
    # governance
    "GovernedToolDispatcher",
    "NodeExecutionContext",
    "GovernanceError",
    "DAGBypassError",
    "ToolPermissionError",
    "ToolCallRecord",
    "ToolViolation",
    # llm adapter
    "GatewayLLMAdapter",
    "GatewayBypassError",
    "assert_llm_admissible",
    # plan
    "AgentPlan",
    "AgentTodo",
    "AcceptanceGate",
    "AgentCodeChange",
    "AgentCompletion",
    "MethodologyChoiceRecord",
    "PlanError",
    "AgentCodeChangeError",
    "AgentCompletionError",
    "MethodologyAutonomyError",
    "assert_methodology_user_decided",
    # roles
    "ROLE_AGENTS",
    "ROLE_NAMES",
    "RoleAgent",
    "UnknownRoleError",
    "get_role",
    "is_verifier",
    # §13 信任层 advisory 接线（trust_advisory）
    "TrustAdvisory",
    "TRUST_ADVISORY_SOURCE",
    "run_trust_advisory",
    "summarize_trust_for_event",
    "safety_bypass_invariants",
]
