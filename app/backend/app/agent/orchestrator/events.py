"""Agent Orchestrator · user 可见工作流事件投影（GOAL §7「可见事件类型」+「可见性边界」）。

GOAL §7 把 AgentOS 内部执行**投影**为 user 可见工作流：user 看到执行到哪一步、哪个 role agent、
调了哪些工具、读了哪些 RAG/source、产了哪些资产/diff、触发哪些验证、遇到什么失败、下一步是什么。

诚实点名（GOAL-FIRST·与卡面措辞的差异）：GOAL §7「可见事件类型」**逐条列了 24 个**事件名
（AgentPlanCreated … RunVerdictProduced）。卡面摘要写「23 可见事件」——按 GOAL-FIRST 以 GOAL 原文
为契约，这里**实现 24 个全集**（少实现一个 = 自造契约）。计数差异作为诚实残余上报中心。

LLM 相关那 5 枚（LLMRouteSelected / CredentialPoolSelected / LLMCallStarted / LLMCallFinished /
ProviderFallbackUsed）**不另造**——直接复用 LLM Gateway（A-AGENT-GW 已建）`gateway.py` 里的同名
常量与其 `LLMGatewayEvent` 数据，由本投影层 adopt 进统一事件流（单一源·防漂）。

可见性边界（GOAL §7）落地为两道结构门：
- secret plaintext 边界：投影事件序列化面若夹带在册明文 secret → 拒（复用 call_record 的扫描）。
- provider hidden chain-of-thought 边界：事件 data 禁带 `chain_of_thought` / `reasoning_raw` /
  `hidden_reasoning` / 明文 `api_key` 等键——只投影可审计的结构化元数据，绝不投影 provider 内部思维链。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Iterable

from ...llm.call_record import scan_messages_for_secret
from ...llm.gateway import (
    EV_CALL_FINISHED,
    EV_CALL_STARTED,
    EV_CREDENTIAL_SELECTED,
    EV_FALLBACK_USED,
    EV_ROUTE_SELECTED,
    LLMGatewayEvent,
)

# ── GOAL §7「可见事件类型」全 24 枚（顺序照 GOAL 原文）──────────────────────────
EV_AGENT_PLAN_CREATED = "AgentPlanCreated"
EV_TODO_UPDATED = "TodoUpdated"
EV_ROLE_AGENT_DISPATCHED = "RoleAgentDispatched"
# —— 下 5 枚 = LLM Gateway 同名常量复用（单一源，import 自 gateway.py，不另立字符串）——
EV_LLM_ROUTE_SELECTED = EV_ROUTE_SELECTED
EV_LLM_CALL_STARTED = EV_CALL_STARTED
EV_LLM_CALL_FINISHED = EV_CALL_FINISHED
EV_CREDENTIAL_POOL_SELECTED = EV_CREDENTIAL_SELECTED
EV_PROVIDER_FALLBACK_USED = EV_FALLBACK_USED
# —— 工具 / 资产 / RAG ——
EV_TOOL_CALL_STARTED = "ToolCallStarted"
EV_TOOL_CALL_FINISHED = "ToolCallFinished"
EV_RAG_HIT_USED = "RagHitUsed"
EV_ASSET_READ = "AssetRead"
EV_ASSET_DIFF_CREATED = "AssetDiffCreated"
# —— canonical command / 图写入 ——
EV_CANONICAL_COMMAND_PROPOSED = "CanonicalCommandProposed"
EV_CANONICAL_COMMAND_APPLIED = "CanonicalCommandApplied"
# —— 验证 / 挑战 ——
EV_VALIDATION_STARTED = "ValidationStarted"
EV_VALIDATION_FINISHED = "ValidationFinished"
EV_VERIFIER_CHALLENGE_RAISED = "VerifierChallengeRaised"
# —— 交接 / 审批 ——
EV_DESK_HANDOFF_CREATED = "DeskHandoffCreated"
EV_APPROVAL_REQUESTED = "ApprovalRequested"
# —— 失败 / 修复 ——
EV_FAILURE_DETECTED = "FailureDetected"
EV_REPAIR_ATTEMPTED = "RepairAttempted"
# —— 产物 / 裁决 ——
EV_ARTIFACT_PRODUCED = "ArtifactProduced"
EV_RUN_VERDICT_PRODUCED = "RunVerdictProduced"

# GOAL §7 全集（24）——顺序与 GOAL 原文逐行对应；count == 24 是 import 期不变量（见下）。
VISIBLE_EVENT_KINDS: tuple[str, ...] = (
    EV_AGENT_PLAN_CREATED,
    EV_TODO_UPDATED,
    EV_ROLE_AGENT_DISPATCHED,
    EV_LLM_ROUTE_SELECTED,
    EV_LLM_CALL_STARTED,
    EV_LLM_CALL_FINISHED,
    EV_CREDENTIAL_POOL_SELECTED,
    EV_PROVIDER_FALLBACK_USED,
    EV_TOOL_CALL_STARTED,
    EV_TOOL_CALL_FINISHED,
    EV_RAG_HIT_USED,
    EV_ASSET_READ,
    EV_ASSET_DIFF_CREATED,
    EV_CANONICAL_COMMAND_PROPOSED,
    EV_CANONICAL_COMMAND_APPLIED,
    EV_VALIDATION_STARTED,
    EV_VALIDATION_FINISHED,
    EV_VERIFIER_CHALLENGE_RAISED,
    EV_DESK_HANDOFF_CREATED,
    EV_APPROVAL_REQUESTED,
    EV_FAILURE_DETECTED,
    EV_REPAIR_ATTEMPTED,
    EV_ARTIFACT_PRODUCED,
    EV_RUN_VERDICT_PRODUCED,
)
VISIBLE_EVENT_SET: frozenset[str] = frozenset(VISIBLE_EVENT_KINDS)

# import 期自检（fail-fast·非 assert·-O 不剥）：GOAL §7 列 24 枚，去重后必须仍是 24
# （任何复制粘贴重复 / 漏一枚都在此响亮失败，防「投影了 23 个就当全」）。
if len(VISIBLE_EVENT_SET) != 24 or len(VISIBLE_EVENT_KINDS) != 24:
    raise RuntimeError(
        f"VISIBLE_EVENT_KINDS 必须恰好覆盖 GOAL §7 列举的 24 枚可见事件"
        f"（实得 kinds={len(VISIBLE_EVENT_KINDS)} unique={len(VISIBLE_EVENT_SET)}）"
    )

# LLM Gateway 已产的 5 枚（投影层 adopt·不重造）。
GATEWAY_EVENT_KINDS: frozenset[str] = frozenset(
    {
        EV_LLM_ROUTE_SELECTED,
        EV_LLM_CALL_STARTED,
        EV_LLM_CALL_FINISHED,
        EV_CREDENTIAL_POOL_SELECTED,
        EV_PROVIDER_FALLBACK_USED,
    }
)

# 可见性边界（GOAL §7）：事件 data 绝不允许出现的键（provider 隐藏思维链 / 明文凭据面）。
FORBIDDEN_EVENT_KEYS: frozenset[str] = frozenset(
    {
        "chain_of_thought",
        "reasoning_raw",
        "hidden_reasoning",
        "raw_prompt",
        "prompt_plaintext",
        "api_key",
        "secret",
        "secret_plaintext",
        "token_plaintext",
    }
)


class EventProjectionError(RuntimeError):
    """事件投影撞可见性边界（夹带明文 secret / 投影了 provider 隐藏思维链）→ 拒（GOAL §7）。"""


@dataclass
class WorkflowEvent:
    """投影到 user 工作流的一枚可见事件（GOAL §7）。

    `data` 只装**可审计结构化元数据**（call_id / provider / model / tool 名 / verdict …），
    绝不装原始 prompt、provider 隐藏思维链、明文 secret——可见性边界由 `assert_event_clean` 兜底。
    """

    kind: str
    data: dict[str, Any] = field(default_factory=dict)
    role: str = ""
    desk: str = ""
    node_id: str = ""
    at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "data": self.data,
            "role": self.role,
            "desk": self.desk,
            "node_id": self.node_id,
            "at": self.at,
        }


def _walk_keys(obj: Any) -> Iterable[str]:
    if isinstance(obj, dict):
        for k, v in obj.items():
            yield str(k)
            yield from _walk_keys(v)
    elif isinstance(obj, (list, tuple)):
        for v in obj:
            yield from _walk_keys(v)


def _serialize(data: dict[str, Any]) -> str:
    import json

    return json.dumps(data, ensure_ascii=False, default=str, sort_keys=True)


def assert_event_clean(event: WorkflowEvent, secret_values: Iterable[str] = ()) -> None:
    """可见性边界落地门（GOAL §7）：

    1. provider 隐藏思维链 / 明文凭据键边界：event.data 任一层 key ∈ FORBIDDEN_EVENT_KEYS → 拒。
    2. secret plaintext 边界：序列化面夹带在册明文 secret → 拒（绝不回显 secret）。

    种坏门必抓：把 `chain_of_thought` 或在册明文 key 塞进 event.data → 此门必抛。
    """

    bad = [k for k in _walk_keys(event.data) if k in FORBIDDEN_EVENT_KEYS]
    if bad:
        raise EventProjectionError(
            f"投影事件 {event.kind!r} 夹带禁投影键 {sorted(set(bad))}——"
            "保留 provider 隐藏思维链 / secret 明文边界（GOAL §7 可见性边界）"
        )
    secret_list = [s for s in secret_values if s]
    if secret_list:
        hit = scan_messages_for_secret(_serialize(event.data), secret_list)
        if hit is not None:
            raise EventProjectionError(
                f"投影事件 {event.kind!r} 序列化面夹带在册明文 secret（len={len(hit)}）——"
                "致命可见性边界：secret plaintext 绝不投影（GOAL §7）"
            )


class EventProjector:
    """统一事件流投影器（GOAL §7）——收集 orchestrator 各步事件 + adopt LLM Gateway 事件。

    单一源：LLM 相关 5 枚直接从 `LLMGatewayEvent` adopt（kind 同名），不在 orchestrator 侧重造。
    每枚 emit 都过 `assert_event_clean`（可见性边界）——夹带 secret/隐藏思维链当场拒。
    """

    def __init__(self, *, secret_values: Iterable[str] = ()) -> None:
        self._events: list[WorkflowEvent] = []
        self._secret_values = tuple(s for s in secret_values if s)

    def emit(
        self,
        kind: str,
        data: dict[str, Any] | None = None,
        *,
        role: str = "",
        desk: str = "",
        node_id: str = "",
    ) -> WorkflowEvent:
        if kind not in VISIBLE_EVENT_SET:
            raise EventProjectionError(
                f"未知事件类型 {kind!r} ∉ GOAL §7 可见事件 24 枚（不投影库外事件·防伪可见性）"
            )
        ev = WorkflowEvent(kind=kind, data=dict(data or {}), role=role, desk=desk, node_id=node_id)
        assert_event_clean(ev, self._secret_values)
        self._events.append(ev)
        return ev

    def adopt_gateway_events(
        self,
        gw_events: Iterable[LLMGatewayEvent],
        *,
        role: str = "",
        desk: str = "",
        node_id: str = "",
    ) -> list[WorkflowEvent]:
        """把 LLM Gateway 产的 `LLMGatewayEvent`（5 枚之一）adopt 进统一流（单一源·不重造 kind）。"""

        out: list[WorkflowEvent] = []
        for ge in gw_events:
            if ge.kind not in GATEWAY_EVENT_KINDS:
                raise EventProjectionError(
                    f"非 LLM Gateway 事件 {ge.kind!r} 不应经 adopt_gateway_events 进流"
                )
            out.append(self.emit(ge.kind, dict(ge.data), role=role, desk=desk, node_id=node_id))
        return out

    @property
    def events(self) -> tuple[WorkflowEvent, ...]:
        return tuple(self._events)

    def kinds(self) -> list[str]:
        return [e.kind for e in self._events]

    def of_kind(self, kind: str) -> list[WorkflowEvent]:
        return [e for e in self._events if e.kind == kind]

    def to_list(self) -> list[dict[str, Any]]:
        return [e.to_dict() for e in self._events]


__all__ = [
    "EV_AGENT_PLAN_CREATED",
    "EV_TODO_UPDATED",
    "EV_ROLE_AGENT_DISPATCHED",
    "EV_LLM_ROUTE_SELECTED",
    "EV_LLM_CALL_STARTED",
    "EV_LLM_CALL_FINISHED",
    "EV_CREDENTIAL_POOL_SELECTED",
    "EV_PROVIDER_FALLBACK_USED",
    "EV_TOOL_CALL_STARTED",
    "EV_TOOL_CALL_FINISHED",
    "EV_RAG_HIT_USED",
    "EV_ASSET_READ",
    "EV_ASSET_DIFF_CREATED",
    "EV_CANONICAL_COMMAND_PROPOSED",
    "EV_CANONICAL_COMMAND_APPLIED",
    "EV_VALIDATION_STARTED",
    "EV_VALIDATION_FINISHED",
    "EV_VERIFIER_CHALLENGE_RAISED",
    "EV_DESK_HANDOFF_CREATED",
    "EV_APPROVAL_REQUESTED",
    "EV_FAILURE_DETECTED",
    "EV_REPAIR_ATTEMPTED",
    "EV_ARTIFACT_PRODUCED",
    "EV_RUN_VERDICT_PRODUCED",
    "VISIBLE_EVENT_KINDS",
    "VISIBLE_EVENT_SET",
    "GATEWAY_EVENT_KINDS",
    "FORBIDDEN_EVENT_KEYS",
    "EventProjectionError",
    "EventProjector",
    "WorkflowEvent",
    "assert_event_clean",
]
