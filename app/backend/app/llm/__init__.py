"""LLM Gateway 治理层（GOAL §7 Agent Shell / §1 LLM 对象 · 决策 D-LLM-ROUTING）。

全仓 LLM 调用的【唯一入口】+ 混合自适应路由 + SecretRef 凭据池 + 可审计调用账。
role agent 绝不直接调 provider / 读 key——只通过 `LLMGateway.complete(...)` 拿
`(LLMResponse, LLMCallRecord)`，且结果须过 `assert_admissible_to_graph` 才可准入 Research Graph。

wrap 现有 `app/agent/llm_client.py` + `llm_providers.py`（不重建）：它们成 gateway 后端 adapter。

四件套：
- gateway.py        —— 唯一入口 + 健康/配额 fallback + prompt secret guard + 封印 + 准入门
- routing.py        —— ModelRoutingPolicy（混合自适应，绝不静默降质难任务）
- credential_pool.py —— SecretRef + capability 物化（明文只在门后，role agent 拿不到）
- call_record.py    —— LLMCallRecord（provider/model/auth_ref/replay_state）+ 必填/secret/封印/独立性门
"""

from __future__ import annotations

from .call_record import (
    CallStatus,
    IndependenceRecord,
    IndependenceVerdict,
    LLMCallRecord,
    LLMRecordError,
    ReplayState,
    SecretLeakError,
    assert_no_plaintext_secret,
    assert_record_admissible,
    evaluate_independence,
    make_call_id,
    scan_messages_for_secret,
    seal_record,
    verify_record_seal,
)
from .credential_pool import (
    CredentialDescriptor,
    CredentialError,
    GatewayCapability,
    LLMCredentialPool,
    MaterializedCredential,
    SecretRef,
)
from .gateway import (
    DegradedRoutingError,
    GatewayError,
    GatewaySealedResult,
    LLMGateway,
    LLMGatewayEvent,
    LLMRequest,
    ProviderHealth,
    QuotaStatus,
    assert_admissible_to_graph,
)
from .routing import (
    LLMModelProfile,
    ModelRoutingPolicy,
    ModelTier,
    RiskLevel,
    RoleCapabilityRequest,
    RoutingDecision,
    RoutingError,
    RoutingMode,
    TaskDifficulty,
    infer_capability_tier,
    tier_rank,
)

__all__ = [
    # call_record
    "CallStatus",
    "IndependenceRecord",
    "IndependenceVerdict",
    "LLMCallRecord",
    "LLMRecordError",
    "ReplayState",
    "SecretLeakError",
    "assert_no_plaintext_secret",
    "assert_record_admissible",
    "evaluate_independence",
    "make_call_id",
    "scan_messages_for_secret",
    "seal_record",
    "verify_record_seal",
    # credential_pool
    "CredentialDescriptor",
    "CredentialError",
    "GatewayCapability",
    "LLMCredentialPool",
    "MaterializedCredential",
    "SecretRef",
    # gateway
    "DegradedRoutingError",
    "GatewayError",
    "GatewaySealedResult",
    "LLMGateway",
    "LLMGatewayEvent",
    "LLMRequest",
    "ProviderHealth",
    "QuotaStatus",
    "assert_admissible_to_graph",
    # routing
    "LLMModelProfile",
    "ModelRoutingPolicy",
    "ModelTier",
    "RiskLevel",
    "RoleCapabilityRequest",
    "RoutingDecision",
    "RoutingError",
    "RoutingMode",
    "TaskDifficulty",
    "infer_capability_tier",
    "tier_rank",
]
