"""Agent Orchestrator · 让 role agent 的 LLM 调用全经 LLM Gateway（GOAL §7「AgentLLMCall 绕过 Gateway → 拒」）。

GOAL §7：Agent Orchestrator 通过 **LLM Gateway** 调 provider；role agent 不直接调 provider/读 key，
只拿模型结果 + 可审计 LLMCallRecord。本模块把这条兑现为一个 `LLMClient` 适配器：

- `GatewayLLMAdapter` 实现既有 `LLMClient` 接口（`chat`）——于是能**直接注入被 wrap 的 AgentRuntime**
  （runtime 那行 `self._llm.chat(...)` 无感·扩展不替换）。但它内部把每次调用翻译成 `LLMRequest`，
  经 `gateway.complete(...)` 出门：选路由、物化凭据（明文只在 gateway 内）、落 `LLMCallRecord`、盖封印。
- 每次调用后把 `GatewaySealedResult`（含 record + 5 枚 LLM 事件）交给 sink（orchestrator 收集、投影、
  做图准入）。并就地 `gateway.verify(...)` 自证封印——本路径产的结果**永远**是 gateway 亲铸。
- `assert_llm_admissible(...)` = 直接复用 gateway 的 `assert_admissible_to_graph`：任何**未经本 gateway
  封印**的 LLM 结果（绕过 Gateway 自造）对 Research Graph 不可准入——这就是「绕过 Gateway → 拒」。

role agent 在本适配器后面**拿不到**任何 provider client / api key：它只调 `chat`，回 `LLMResponse`。
"""

from __future__ import annotations

from typing import Any, Callable

from ..llm_client import LLMClient, LLMMessage, LLMResponse
from ...llm.call_record import LLMRecordError
from ...llm.gateway import (
    GatewaySealedResult,
    LLMGateway,
    LLMGatewayEvent,
    LLMRequest,
    assert_admissible_to_graph,
)
from ...llm.routing import RoleCapabilityRequest


class GatewayBypassError(LLMRecordError):
    """LLM 结果未经本 Gateway 封印（绕过 Gateway 自造）→ 对 Research Graph 不可准入（GOAL §7）。"""


class GatewayLLMAdapter(LLMClient):
    """把 LLM Gateway 包成 `LLMClient`：role agent 经它调 LLM，全程经 Gateway、绝不直触 provider。

    注入进 AgentRuntime 即让 runtime 的 reAct loop 每步 LLM 调用都走 Gateway（封印 + 落账 + 投影）。
    `provider` 标 `gateway`——role agent 看到的「provider」永远是治理层，不是真 provider 名/凭据。
    """

    provider = "gateway"

    def __init__(
        self,
        gateway: LLMGateway,
        capability: RoleCapabilityRequest,
        *,
        session_id: str = "default",
        replay_mode: str = "live",
        temperature: float = 0.2,
        on_sealed: Callable[[GatewaySealedResult], None] | None = None,
        owner_user_id: str,
        workflow_id: str,
        invocation_id_factory: Callable[[], str],
        record_sink: Callable[[Any], None] | None = None,
    ) -> None:
        self._gateway = gateway
        self._capability = capability
        self._session_id = session_id
        self._replay_mode = replay_mode
        self._temperature = temperature
        self._on_sealed = on_sealed
        self._owner_user_id = str(owner_user_id or "").strip()
        self._workflow_id = str(workflow_id or "").strip()
        self._invocation_id_factory = invocation_id_factory
        self._record_sink = record_sink
        if not self._owner_user_id or not self._workflow_id:
            raise LLMRecordError(
                "GatewayLLMAdapter requires explicit owner_user_id and workflow_id"
            )
        self._sealed_results: list[GatewaySealedResult] = []
        self._failure_events: list[LLMGatewayEvent] = []
        self._failure_records: list[Any] = []

    def chat(
        self,
        messages: list[LLMMessage],
        *,
        tools: list[dict[str, Any]] | None = None,
        model: str | None = None,
        temperature: float | None = None,
    ) -> LLMResponse:
        """经 Gateway 出门——绝不在此直触 provider / 读 key。

        `model` 参数被**忽略**：模型选择是 Gateway 的 ModelRoutingPolicy 职责（混合自适应·不可逆/难
        任务不降档），role agent 不在此越过路由钦点模型。
        """

        invocation_id = str(self._invocation_id_factory() or "").strip()
        if not invocation_id:
            raise LLMRecordError("GatewayLLMAdapter invocation_id_factory returned empty id")
        req = LLMRequest(
            messages=list(messages),
            capability=self._capability,
            tools=tools,
            temperature=self._temperature if temperature is None else temperature,
            session_id=self._session_id,
            owner_user_id=self._owner_user_id,
            workflow_id=self._workflow_id,
            invocation_id=invocation_id,
            replay_mode=self._replay_mode,
        )
        try:
            sealed = self._gateway.complete(req, record_sink=self._record_sink)
        except Exception as exc:
            # Gateway persists sanitized failure records before attaching these
            # events. Keep them available to the orchestrator even though there
            # is no successful GatewaySealedResult to return.
            self._failure_events.extend(
                event
                for event in tuple(getattr(exc, "events", ()) or ())
                if isinstance(event, LLMGatewayEvent)
            )
            failure_records = tuple(getattr(exc, "records", ()) or ())
            self._failure_records.extend(failure_records)
            record = getattr(exc, "record", None)
            if record is not None and not failure_records:
                self._failure_records.append(record)
            raise
        # 自证：本路径产的结果永远经本 gateway 封印（绕过路径产的结果验不过这一步）。
        if not self._gateway.verify(sealed):
            raise GatewayBypassError(
                "Gateway 适配器拿到未封印结果——本不该发生；绕过 Gateway 的 LLM 结果不可准入（GOAL §7）"
            )
        self._sealed_results.append(sealed)
        if self._on_sealed is not None:
            self._on_sealed(sealed)
        return sealed.response

    @property
    def sealed_results(self) -> tuple[GatewaySealedResult, ...]:
        return tuple(self._sealed_results)

    def last_record(self):
        return self._sealed_results[-1].record if self._sealed_results else None

    @property
    def failure_events(self) -> tuple[LLMGatewayEvent, ...]:
        return tuple(self._failure_events)

    @property
    def last_failure_record(self):
        return self._failure_records[-1] if self._failure_records else None


def assert_llm_admissible(sealed: GatewaySealedResult, gateway: LLMGateway) -> None:
    """LLM 结果准入 Research Graph 的唯一门（GOAL §7「AgentLLMCall 绕过 Gateway → 拒」）。

    直接复用 gateway 的 `assert_admissible_to_graph`：封印校验 + 必填四要素 + 明文 secret 门。
    种坏门必抓：拿一条**未经本 gateway 封印**的伪造 sealed result 来准入 → 此门必抛。
    """

    assert_admissible_to_graph(sealed, gateway)


__all__ = [
    "GatewayBypassError",
    "GatewayLLMAdapter",
    "assert_llm_admissible",
]
