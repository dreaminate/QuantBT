"""RecordingLLMClient · 包住任意 LLMClient 的 record/replay 装饰器（T-016 / spine 02 §3.3）。

命门（R11）：**replay 模式命中即从 fixture 读、未命中 `raise ReplayMiss`——绝不回退打真 API**。
record 模式未命中才真调 inner，过受控翻译层后落不可变 fixture。三模式：record | replay | passthrough。
依赖倒置：它本身是个 `LLMClient`，从 main.py 注入即生效，AgentRuntime 那行 `self._llm.chat(...)` 无感。
"""

from __future__ import annotations

from typing import Any

from ..llm_client import LLMClient, LLMMessage, LLMResponse
from .fixture import FixtureKey, LLMFixture, ModelPin, prompt_digest
from .repro import ReproLevel
from .store import FixtureStore, ReplayMiss
from .translation import ControlledTranslator

_GENESIS = "genesis"


def _messages_to_jsonable(messages: list[LLMMessage]) -> list[dict[str, Any]]:
    out = []
    for m in messages:
        out.append({"role": m.role, "content": m.content, "tool_calls": m.tool_calls,
                    "tool_call_id": m.tool_call_id, "name": m.name})
    return out


def _response_to_dict(r: LLMResponse) -> dict[str, Any]:
    return {"content": r.content, "tool_calls": r.tool_calls, "raw": r.raw,
            "model_id": r.model_id, "system_fingerprint": r.system_fingerprint}


class RecordingLLMClient(LLMClient):
    def __init__(
        self,
        inner: LLMClient,
        store: FixtureStore,
        *,
        mode: str = "record",                 # record | replay | passthrough
        run_id: str = "run-anon",
        run_index: int = 0,
        translator: ControlledTranslator | None = None,
        repro_level: ReproLevel = ReproLevel.DECISION,
    ) -> None:
        if mode not in ("record", "replay", "passthrough"):
            raise ValueError(f"非法 mode={mode!r}")
        self._inner = inner
        self._store = store
        self._mode = mode
        self._run_id = run_id
        self._run_index = run_index
        self._translator = translator
        self._repro_level = repro_level
        self.provider = f"recording[{getattr(inner, 'provider', '?')}]"
        self._step = 0
        self._upstream = _GENESIS

    def _fixture_key(self, messages: list[LLMMessage], tools: Any, model: str | None,
                     temperature: float) -> tuple[str, ModelPin, dict[str, Any]]:
        msgs = _messages_to_jsonable(messages)
        pin = ModelPin(
            provider=getattr(self._inner, "provider", "?"),
            model_id=model or getattr(self._inner, "default_model", "") or "unknown",
            system_fingerprint=None,
            params={"temperature": temperature},
        )
        fk = FixtureKey(
            node_pos=f"{self._run_id}:{self._step}",
            prompt_digest=prompt_digest(msgs, tools),
            model_pin_digest=pin.requested_digest(),
            upstream_digest=self._upstream,
            run_index=self._run_index,
        )
        return fk.compute(), pin, {"messages": msgs, "tools": tools}

    def chat(
        self,
        messages: list[LLMMessage],
        *,
        tools: list[dict[str, Any]] | None = None,
        model: str | None = None,
        temperature: float = 0.2,
    ) -> LLMResponse:
        key, pin, request = self._fixture_key(messages, tools, model, temperature)

        hit = self._store.get_optional(key) if self._mode != "passthrough" else None
        if hit is not None:
            self._step += 1
            self._upstream = key
            return self._from_fixture(hit)

        if self._mode == "replay":
            # R11 命门：未命中绝不打真 API。
            raise ReplayMiss(f"replay 未命中 fixture_key={key}，拒绝回退打真 API（R11）")

        # record / passthrough miss → 真调 inner。
        resp = self._inner.chat(messages, tools=tools, model=model, temperature=temperature)
        # 实际模型版本/指纹（供应商若回传）记进 fixture（不进 key）。
        actual_pin = ModelPin(provider=pin.provider, model_id=resp.model_id or pin.model_id,
                              system_fingerprint=resp.system_fingerprint, params=pin.params)
        tr = self._translator.translate(resp.tool_calls) if self._translator else None
        status = tr.status if tr else "ok"
        tool_calls = resp.tool_calls

        if self._mode == "record":
            fixture = LLMFixture(
                fixture_key=key, run_id=self._run_id, repro_level=self._repro_level.value,
                model_pin=actual_pin.to_dict(), request=request,
                response=_response_to_dict(resp), tool_calls=tool_calls,
                translation_status=status,
            )
            self._store.put(fixture)

        resp.fixture_key = key
        resp.repro_level = self._repro_level.value
        resp.model_id = actual_pin.model_id
        resp.system_fingerprint = actual_pin.system_fingerprint
        # human_confirm 时不把 tool_calls 透出去派发（交 AgentRuntime 翻译门处理）。
        resp.translation_status = status  # type: ignore[attr-defined]
        self._step += 1
        self._upstream = key
        return resp

    def _from_fixture(self, fx: LLMFixture) -> LLMResponse:
        r = fx.response or {}
        resp = LLMResponse(
            content=r.get("content", ""),
            tool_calls=list(fx.tool_calls or r.get("tool_calls") or []),
            raw=r.get("raw", {}),
        )
        resp.model_id = r.get("model_id")
        resp.system_fingerprint = r.get("system_fingerprint")
        resp.fixture_key = fx.fixture_key
        resp.repro_level = fx.repro_level
        resp.translation_status = fx.translation_status  # type: ignore[attr-defined]
        return resp


__all__ = ["RecordingLLMClient"]
