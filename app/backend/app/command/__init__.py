"""CanonicalCommand 全栈（GOAL §1 统一对象链 · §2 多台工作系统）——写 Research Graph 的唯一治理通道。

A-GRAPH-1（`graph/`）落了命令最小信封 + 图写口 `ResearchGraph.apply`；本包（A-CMD）在写口**之前**建
CanonicalCommand 全栈：① typed 命令层（`CommandBus`·唯一写通道）② 语义翻译（intent/canvas action →
typed command）③ 全栈校验（actor 四类 / 目标台 / 内容寻址 / payload schema）④ provenance（来源面 +
同一本 audit/lineage 账·user 手动与 agent 同链）。详见 `canonical_command.py` 模块 docstring。

**收编只读** graph/research_graph（typed command + 图写口）、qro/envelope（actor 四类）、lineage/ids
（内容寻址身份）——绝不另造命令类型 / 身份哈希 / 第二套审计账。**不建** Governed Compiler（A-COMPILER）。
"""

from __future__ import annotations

from .canonical_command import (
    ACTION_CREATE_ASSET,
    ACTION_FULFILL_HANDOFF,
    ACTION_LINK_ASSETS,
    ACTION_REQUEST_HANDOFF,
    ACTION_TO_COMMAND,
    ACTION_UPDATE_ASSET,
    ACTIONS,
    ACTOR_AGENT,
    ACTOR_SCHEDULED_AGENT,
    ACTOR_SURFACE_ALLOWED,
    ACTOR_USER_CONFIRMED_AGENT,
    ACTOR_USER_MANUAL,
    HUMAN_MANUAL_SURFACES,
    LINK_EDGE_TYPES,
    ORIGIN_AGENT_RUNTIME,
    ORIGIN_API,
    ORIGIN_CANVAS,
    ORIGIN_FORM,
    ORIGIN_IDE,
    ORIGIN_SCHEDULER,
    ORIGIN_SURFACES,
    ChannelBypassViolation,
    CommandBus,
    CommandError,
    CommandIntent,
    CommandLedger,
    CommandReceipt,
    CommandTranslationError,
    CommandValidationError,
    ContentAddressViolation,
    LedgerEntry,
    PayloadSchemaError,
    Provenance,
    ProvenanceError,
    agent_provenance,
    assert_actor_surface_coherent,
    assert_content_addressed,
    manual_provenance,
    translate_intent,
    validate_intent,
)

__all__ = [
    # 来源面 ④
    "ORIGIN_CANVAS",
    "ORIGIN_FORM",
    "ORIGIN_IDE",
    "ORIGIN_API",
    "ORIGIN_AGENT_RUNTIME",
    "ORIGIN_SCHEDULER",
    "ORIGIN_SURFACES",
    "HUMAN_MANUAL_SURFACES",
    "ACTOR_SURFACE_ALLOWED",
    # actor
    "ACTOR_USER_MANUAL",
    "ACTOR_AGENT",
    "ACTOR_USER_CONFIRMED_AGENT",
    "ACTOR_SCHEDULED_AGENT",
    # 语义动作 ②
    "ACTION_CREATE_ASSET",
    "ACTION_UPDATE_ASSET",
    "ACTION_LINK_ASSETS",
    "ACTION_REQUEST_HANDOFF",
    "ACTION_FULFILL_HANDOFF",
    "ACTIONS",
    "ACTION_TO_COMMAND",
    "LINK_EDGE_TYPES",
    # 数据类
    "Provenance",
    "CommandIntent",
    "LedgerEntry",
    "CommandLedger",
    "CommandReceipt",
    "CommandBus",
    # 门 / 校验 / 翻译
    "assert_actor_surface_coherent",
    "validate_intent",
    "translate_intent",
    "assert_content_addressed",
    # 便捷构造器
    "manual_provenance",
    "agent_provenance",
    # 异常族
    "CommandError",
    "CommandValidationError",
    "ProvenanceError",
    "PayloadSchemaError",
    "CommandTranslationError",
    "ContentAddressViolation",
    "ChannelBypassViolation",
]
