"""M14 · Agent 状态机 / reAct loop。

简化设计：
1. user 发一条消息 → AgentTurn.start
2. 把 user message + tool_schema 发给 LLMClient
3. 拿到 LLMResponse：
   - 有 tool_calls → 派发到 ToolDispatcher，把结果作为 tool message 写回，loop 回到步骤 2
   - 否则当作终态回复给 user
4. 步数上限避免死循环

脊柱内核 01 接线（T-023，复用不重造）：每个 reAct turn 的「LLM 输出落 fixture / replay 读 fixture
不重跑 LLM」由注入的 `RecordingLLMClient`（T-016 / spine 02）透明承担——它本身是个 `LLMClient`，
从 main.py 注入即生效，本文件这行 `self._llm.chat(...)` 无感。fixture 内容寻址身份（fixture_key =
node_id 的 llmfx- 别名）出自唯一身份源 `lineage/ids.py`，**绝不在 agent 侧另造第二套 store/身份**
（C5/C7/C8 单一源红线）。故 replay 模式下整个 turn 重放零 LLM 真调用（spy 断言 chat==0 次，见
`tests/test_kernel_wiring.py`）；R11：未命中绝不回退打真 API（由 RecordingLLMClient 抛 ReplayMiss）。
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from typing import Any, Callable, Literal

from ..lineage.ids import content_hash
from ..research_os.spine import (
    ActorSource,
    DefinitionStatus,
    EntrySource,
    EvidenceStatus,
    GovernanceStatus,
    QRORecord,
    QROType,
    ResearchGraphCommand,
    ResearchGraphStore,
)
from .llm_client import LLMClient, LLMMessage, LLMResponse
from .tool_schema import TOOL_SCHEMA


ToolHandler = Callable[[str, dict[str, Any]], dict[str, Any]]
AgentRAGContextProvider = Callable[[str], "AgentRAGContext | None"]


@dataclass(frozen=True)
class AgentRAGContextHit:
    source_id: str
    version: str
    asset_ref: str
    projection: str
    title: str
    evidence_label: str
    context_role: str
    score: float

    @property
    def evidence_ref(self) -> str:
        return f"rag:{self.source_id}@{self.version}:{self.asset_ref}"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self) | {"evidence_ref": self.evidence_ref}


@dataclass(frozen=True)
class AgentRAGContext:
    prompt_context: str
    hits: tuple[AgentRAGContextHit, ...] = ()
    usage_ids: tuple[str, ...] = ()

    @property
    def evidence_refs(self) -> tuple[str, ...]:
        return tuple(hit.evidence_ref for hit in self.hits) + tuple(
            f"rag_usage:{usage_id}" for usage_id in self.usage_ids
        )

    def step_summary(self) -> str:
        refs = ", ".join(hit.evidence_ref for hit in self.hits)
        usage = ", ".join(self.usage_ids)
        if usage:
            return f"[Research Asset RAG] candidate_context refs: {refs}; usage: {usage}"
        return f"[Research Asset RAG] candidate_context refs: {refs}"


# T-027 / D-PERM：工具副作用分级。none=无外部副作用（回测/IC/PBO/报告，本地可重置）；
# external=有外部副作用（如 testnet 真发单，假钱但真打交易所）；realmoney=动钱/晋级（永不注册给 agent）。
ToolSideEffect = Literal["none", "external", "realmoney"]


def permission_gate(mode: str, side_effect: str) -> str:
    """权限三态 × 副作用 → 'execute' | 'confirm'。

    权限轴 ⟂ 治理轴（D-PERM）：权限模式只调「要不要停下确认」，绝不跳治理门——
    realmoney 在【任何】模式（含 bypass）都 confirm（agent 永不自动执行动钱/晋级，纵深防御）。
    none：ask 每步确认、auto/bypass 自动；external：仅 bypass 自动、ask/auto 需确认。
    """
    if side_effect == "realmoney":
        return "confirm"  # 治理正交：bypass 也不跳
    if side_effect == "external":
        return "execute" if mode == "bypass" else "confirm"
    return "confirm" if mode == "ask" else "execute"


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
    qro_ids: list[str] = field(default_factory=list)
    research_graph_command_ids: list[str] = field(default_factory=list)
    compiler_ir_refs: list[str] = field(default_factory=list)
    compiler_pass_refs: list[str] = field(default_factory=list)
    entrypoint_coverage_refs: list[str] = field(default_factory=list)
    rag_hits: list[dict[str, Any]] = field(default_factory=list)
    rag_usage_ids: list[str] = field(default_factory=list)


class AgentRuntime:
    def __init__(
        self,
        llm: LLMClient,
        tools: dict[str, ToolHandler] | None = None,
        max_steps: int = 6,
        system_prompt: str = "You are QuantBT Agent — 量化研究执行层。",
        translator: Any | None = None,
        permission_mode: str = "auto",
        research_graph: ResearchGraphStore | None = None,
        entry_source: EntrySource | str = EntrySource.AGENT_SHELL,
        actor: str = "agent_runtime",
        owner: str = "agent_runtime",
        rag_context_provider: AgentRAGContextProvider | None = None,
    ) -> None:
        self._llm = llm
        self._tools = tools or {}
        self._max_steps = max_steps
        self._system = system_prompt
        # 受控翻译门（T-016，可选）：LLM 输出 schema 合规但语义越界（如越权杠杆）→ 不派发、挂起。
        self._translator = translator
        # 权限三态（T-027 / D-PERM）：ask|auto|bypass，只调「要不要停下确认」、绝不跳治理门。
        self._permission_mode = permission_mode
        self._side_effects: dict[str, str] = {}
        self._research_graph = research_graph
        self._entry_source = entry_source
        self._actor = actor
        self._owner = owner
        self._rag_context_provider = rag_context_provider

    def register_tool(self, name: str, handler: ToolHandler, side_effect: ToolSideEffect = "none") -> None:
        self._tools[name] = handler
        self._side_effects[name] = side_effect

    def _append_step(
        self,
        turn: AgentTurn,
        step: AgentStep,
        *,
        actor_source: ActorSource | str,
        evidence_refs: tuple[str, ...] = (),
        tool_record_refs: tuple[str, ...] = (),
    ) -> None:
        turn.steps.append(step)
        if self._research_graph is None:
            return
        step_index = len(turn.steps) - 1
        step_hash = content_hash(step.to_dict())
        qro = QRORecord(
            qro_type=QROType.RESEARCH_REPORT,
            owner=self._owner,
            actor=actor_source,
            input_contract={
                "entry_source": str(
                    self._entry_source.value if isinstance(self._entry_source, EntrySource) else self._entry_source
                ),
                "turn_input_hash": content_hash({"user_input": turn.user_input}),
                "step_index": step_index,
                "role": step.role,
            },
            output_contract={
                "step_hash": step_hash,
                "content_hash": content_hash({"content": step.content}),
                "tool_call_count": len(step.tool_calls),
                "tool_call_id": step.tool_call_id,
            },
            market="unspecified",
            universe="unspecified",
            horizon="event",
            frequency="event",
            lineage=("agent_runtime", step.role, f"step:{step_index}"),
            implementation_hash="agent_runtime:" + step_hash,
            assumptions=("Agent Shell step captured as a Research OS entrypoint event.",),
            known_limits=(
                "Captured chat/tool metadata is not evidence sufficient by itself.",
                "Plaintext message content is held in AgentTurn, not copied into QRO contracts.",
            ),
            failure_modes=("LLM/tool output may be incomplete, unsafe, or require downstream validation.",),
            validation_plan=("Validate downstream claims through Research Graph evidence and promotion gates.",),
            definition_status=DefinitionStatus.IMPLEMENTED,
            evidence_status=EvidenceStatus.UNTESTED,
            governance_status=GovernanceStatus.UNREVIEWED,
            event_time=step.timestamp_utc,
            known_at=step.timestamp_utc,
            effective_at=step.timestamp_utc,
            evidence_refs=evidence_refs,
            permission=f"agent_permission_mode:{self._permission_mode}",
        )
        command = ResearchGraphCommand(
            source=self._entry_source,
            command_type="upsert_qro",
            actor_source=actor_source,
            actor=self._actor,
            payload={"qro": qro},
            evidence_refs=evidence_refs,
            tool_record_refs=tool_record_refs,
        )
        command_id = self._research_graph.apply(command)
        turn.qro_ids.append(qro.qro_id)
        turn.research_graph_command_ids.append(command_id)

    def run(self, user_input: str) -> AgentTurn:
        turn = AgentTurn(user_input=user_input)
        messages: list[LLMMessage] = [LLMMessage(role="system", content=self._system)]
        rag_context = self._rag_context_provider(user_input) if self._rag_context_provider is not None else None
        rag_evidence_refs = rag_context.evidence_refs if rag_context is not None and rag_context.hits else ()
        if rag_context is not None and rag_context.hits:
            messages.append(LLMMessage(role="system", content=rag_context.prompt_context))
            turn.rag_hits.extend(hit.to_dict() for hit in rag_context.hits)
            turn.rag_usage_ids.extend(rag_context.usage_ids)
        messages.append(LLMMessage(role="user", content=user_input))
        self._append_step(turn, AgentStep(role="user", content=user_input), actor_source=ActorSource.USER_MANUAL)
        if rag_context is not None and rag_context.hits:
            self._append_step(
                turn,
                AgentStep(role="system", content=rag_context.step_summary()),
                actor_source=ActorSource.AGENT,
                evidence_refs=rag_evidence_refs,
            )
        for _ in range(self._max_steps):
            response = self._llm.chat(messages, tools=TOOL_SCHEMA)
            messages.append(
                LLMMessage(role="assistant", content=response.content, tool_calls=response.tool_calls)
            )
            self._append_step(
                turn,
                AgentStep(role="assistant", content=response.content, tool_calls=response.tool_calls),
                actor_source=ActorSource.AGENT,
                evidence_refs=rag_evidence_refs,
            )
            if not response.tool_calls:
                turn.final_message = response.content
                turn.succeeded = True
                return turn
            # 受控翻译门（T-016，复核 #11）：任何【非 ok】状态都不派发——
            # human_confirm_required（语义越界，挂审批门）与 schema_invalid（结构非法，拒/退回）都拦住，
            # 绝不让 schema_invalid 漏到派发（否则非法 tool_call 仍被执行）。
            if self._translator is not None:
                tr = self._translator.translate(response.tool_calls)
                if tr.status != "ok":
                    self._append_step(
                        turn,
                        AgentStep(role="system", content=f"[翻译门拦截/{tr.status}] {tr.reason}"),
                        actor_source=ActorSource.AGENT,
                        evidence_refs=rag_evidence_refs,
                    )
                    turn.final_message = (
                        f"该操作需人工确认，未自动执行：{tr.reason}"
                        if tr.status == "human_confirm_required"
                        else f"LLM 输出未通过结构校验，未派发：{tr.reason}"
                    )
                    turn.succeeded = False
                    return turn
            # 权限三态门（T-027 / D-PERM）：按 (mode, side_effect) 决定执行/挂起确认。
            # 治理正交：realmoney 在任何模式（含 bypass）都挂起——权限轴绝不跳治理门。
            for call in response.tool_calls:
                tname = call.get("name") or call.get("function", {}).get("name", "")
                se = self._side_effects.get(tname, "none")
                if permission_gate(self._permission_mode, se) == "confirm":
                    self._append_step(
                        turn,
                        AgentStep(
                            role="system",
                            content=f"[权限门/{self._permission_mode}] 工具 {tname}（{se}）需确认，未自动执行",
                        ),
                        actor_source=ActorSource.AGENT,
                        evidence_refs=rag_evidence_refs,
                    )
                    turn.final_message = f"该操作（{tname}）在 {self._permission_mode} 模式下需你确认后执行。"
                    turn.succeeded = False
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
                tool_call_id = call.get("id")
                tool_record_refs = (f"tool_call:{tool_call_id}",) if tool_call_id else ()
                self._append_step(
                    turn,
                    AgentStep(
                        role="tool",
                        content=json.dumps(payload, ensure_ascii=False),
                        tool_call_id=tool_call_id,
                    ),
                    actor_source=ActorSource.AGENT,
                    evidence_refs=tool_record_refs + rag_evidence_refs,
                    tool_record_refs=tool_record_refs,
                )
            messages.extend(tool_results)
        turn.final_message = "（达到最大步数仍未结束。建议拆解任务再试。）"
        return turn


__all__ = [
    "AgentRAGContext",
    "AgentRAGContextHit",
    "AgentRAGContextProvider",
    "AgentRuntime",
    "AgentStep",
    "AgentTurn",
    "ToolHandler",
    "ToolSideEffect",
    "permission_gate",
]
