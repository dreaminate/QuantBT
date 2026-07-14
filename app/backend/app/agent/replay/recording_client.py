"""RecordingLLMClient · 包住任意 LLMClient 的 record/replay 装饰器（T-016 / spine 02 §3.3）。

命门（R11）：**replay 模式命中即从 fixture 读、未命中 `raise ReplayMiss`——绝不回退打真 API**。
record 模式未命中才真调 inner，过受控翻译层后落不可变 fixture。三模式：record | replay | passthrough。
依赖倒置：它本身是个 `LLMClient`，从 main.py 注入即生效，AgentRuntime 那行 `self._llm.chat(...)` 无感。
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from ...lineage.ids import content_hash
from ...llm.call_record import (
    CallRecordKind,
    CallStatus,
    LLMCallRecord,
    LLMRecordError,
    ReplayState,
    assert_record_admissible,
    make_call_id,
    response_ref_from_digest,
    seal_record,
    unavailable_cost_evidence,
    verify_record_seal,
)
from ..llm_client import LLMClient, LLMMessage, LLMResponse
from .fixture import (
    FixtureKey,
    LLMFixture,
    ModelPin,
    attach_gateway_audit_metadata,
    extract_gateway_audit_metadata,
    owner_scope_ref,
    prompt_digest,
)
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
        owner_user_id: str | None = None,
        workflow_id: str | None = None,
        invocation_id_factory: Callable[[], str] | None = None,
        record_sink: Callable[[LLMCallRecord], Any] | None = None,
        seal_secret: bytes | None = None,
        translator: ControlledTranslator | None = None,
        repro_level: ReproLevel = ReproLevel.DECISION,
    ) -> None:
        if mode not in ("record", "replay", "passthrough"):
            raise ValueError(f"非法 mode={mode!r}")
        owner = str(owner_user_id or "").strip()
        if mode in ("record", "replay") and not owner:
            raise ValueError("owner_user_id is required for record/replay persisted operations")
        self._inner = inner
        self._store = store
        self._mode = mode
        self._run_id = run_id
        self._run_index = run_index
        self._owner_user_id = owner
        self._workflow_id = str(workflow_id or "").strip()
        self._invocation_id_factory = invocation_id_factory
        self._record_sink = record_sink
        self._seal_secret = bytes(seal_secret) if seal_secret is not None else None
        if self._seal_secret is not None and len(self._seal_secret) < 32:
            raise ValueError("seal_secret must contain at least 32 bytes")
        if mode == "replay":
            self._require_replay_audit_config()
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
        owner_key_scope = (
            owner_scope_ref(self._owner_user_id)
            if self._owner_user_id
            else "ownerref:passthrough-not-persisted"
        )
        fk = FixtureKey(
            # owner 摘要进内容寻址键：即使 run_id/prompt 相同，不同 owner 也不共享 key。
            node_pos=f"{owner_key_scope}:{self._run_id}:{self._step}",
            prompt_digest=prompt_digest(msgs, tools),
            model_pin_digest=pin.requested_digest(),
            upstream_digest=self._upstream,
            run_index=self._run_index,
        )
        return fk.compute(), pin, {"messages": msgs, "tools": tools}

    def _require_replay_audit_config(self) -> None:
        missing: list[str] = []
        if not self._workflow_id:
            missing.append("workflow_id")
        if self._invocation_id_factory is None:
            missing.append("invocation_id_factory")
        if self._record_sink is None:
            missing.append("record_sink")
        if self._seal_secret is None:
            missing.append("seal_secret")
        if missing:
            raise ValueError(
                "persisted replay requires explicit " + ", ".join(missing)
            )

    def _next_invocation_id(self) -> str:
        self._require_replay_audit_config()
        assert self._invocation_id_factory is not None
        invocation = str(self._invocation_id_factory() or "").strip()
        if not invocation:
            raise LLMRecordError("invocation_id_factory returned an empty replay invocation_id")
        return invocation

    @staticmethod
    def _response_digest(response: LLMResponse) -> str:
        return content_hash({
            "content": response.content,
            "tool_calls": response.tool_calls,
        })

    def _verified_gateway_audit(
        self,
        response: LLMResponse,
    ) -> dict[str, str] | None:
        """Extract only evidence from a matching, sealed gateway terminal."""

        origin = getattr(self._inner, "last_record", None)
        if not isinstance(origin, LLMCallRecord):
            return None
        if self._seal_secret is None:
            return None
        if not verify_record_seal(origin, self._seal_secret):
            raise LLMRecordError("recorded fixture origin lacks a valid LLM audit seal")
        assert_record_admissible(origin)
        if (
            origin.owner_user_id != self._owner_user_id
            or origin.record_kind != CallRecordKind.TERMINAL.value
            or origin.status != CallStatus.OK.value
            or origin.replay_state != ReplayState.LIVE.value
            or origin.response_digest != self._response_digest(response)
        ):
            raise LLMRecordError("recorded fixture origin does not match its gateway terminal")
        return {
            "provider": origin.provider,
            "model": origin.model,
            "auth_ref": origin.auth_ref,
            "origin_call_ref": origin.call_id,
        }

    def _verified_replay_audit(
        self,
        fixture: LLMFixture,
        response: LLMResponse,
    ) -> tuple[dict[str, str] | None, str]:
        """Resolve fixture metadata back to its durable sealed live terminal."""

        audit = extract_gateway_audit_metadata(fixture.model_pin)
        if audit is None:
            return None, "fixture_audit_metadata_missing"
        sink_owner = getattr(self._record_sink, "__self__", None)
        if sink_owner is None or not hasattr(sink_owner, "read_all"):
            return None, "fixture_audit_origin_unverified"
        try:
            rows = sink_owner.read_all(owner_user_id=self._owner_user_id)
        except Exception:  # noqa: BLE001 - replay fails closed; raw storage errors still propagate below.
            raise
        origin = next(
            (row for row in rows if row.call_id == audit["origin_call_ref"]),
            None,
        )
        if not isinstance(origin, LLMCallRecord):
            return None, "fixture_audit_origin_unverified"
        assert self._seal_secret is not None
        if not verify_record_seal(origin, self._seal_secret):
            return None, "fixture_audit_origin_unverified"
        try:
            assert_record_admissible(origin)
        except LLMRecordError:
            return None, "fixture_audit_origin_unverified"
        if not (
            origin.owner_user_id == self._owner_user_id
            and origin.record_kind == CallRecordKind.TERMINAL.value
            and origin.status == CallStatus.OK.value
            and origin.replay_state == ReplayState.LIVE.value
            and origin.provider == audit["provider"]
            and origin.model == audit["model"]
            and origin.auth_ref == audit["auth_ref"]
            and origin.response_digest == self._response_digest(response)
        ):
            return None, "fixture_audit_origin_unverified"
        return {
            **audit,
            "routing_policy_ref": origin.routing_policy_ref,
        }, ""

    def _persist_replay_terminal(
        self,
        *,
        invocation_id: str,
        request_digest: str,
        tool_schema_hash: str,
        fixture_key: str,
        status: str,
        replay_state: str,
        response: LLMResponse | None = None,
        audit: dict[str, str] | None = None,
        error_kind: str = "",
    ) -> LLMCallRecord:
        self._require_replay_audit_config()
        now = datetime.now(UTC).isoformat()
        provider = audit["provider"] if audit is not None else ""
        model = audit["model"] if audit is not None else ""
        auth_ref = audit["auth_ref"] if audit is not None else ""
        routing_policy_ref = audit["routing_policy_ref"] if audit is not None else ""
        response_digest = self._response_digest(response) if response is not None else ""
        record = LLMCallRecord(
            provider=provider,
            model=model,
            auth_ref=auth_ref,
            replay_state=replay_state,
            owner_user_id=self._owner_user_id,
            workflow_id=self._workflow_id,
            invocation_id=invocation_id,
            record_kind=CallRecordKind.TERMINAL.value,
            attempt_no=1,
            routing_policy_ref=routing_policy_ref,
            routing_policy_state=("replay_origin" if audit is not None else "unresolved_pre_route"),
            call_id=make_call_id(
                prompt_digest="",
                provider="",
                model="",
                role="",
                session_id="",
                seq=1,
                owner_user_id=self._owner_user_id,
                workflow_id=self._workflow_id,
                invocation_id=invocation_id,
                record_kind=CallRecordKind.TERMINAL.value,
                attempt_no=1,
            ),
            prompt_digest=request_digest,
            prompt_hash=request_digest,
            tool_schema_hash=tool_schema_hash,
            response_digest=response_digest,
            response_ref=response_ref_from_digest(response_digest),
            fixture_key=fixture_key,
            started_at=now,
            finished_at=now,
            latency_ms=0.0,
            cost=unavailable_cost_evidence(
                "replay_no_provider_cost"
                if response is not None
                else "pre_route_no_provider_response"
            ),
            status=status,
            error_kind=error_kind,
            failure_stage="" if status == CallStatus.OK.value else "replay",
            repro_level=(
                str(getattr(response, "repro_level", self._repro_level.value))
                if response is not None
                else self._repro_level.value
            ),
        )
        assert_record_admissible(record)
        assert self._seal_secret is not None
        record.seal = seal_record(record, self._seal_secret)
        assert self._record_sink is not None
        persisted = self._record_sink(record)
        return persisted if isinstance(persisted, LLMCallRecord) else record

    def chat(
        self,
        messages: list[LLMMessage],
        *,
        tools: list[dict[str, Any]] | None = None,
        model: str | None = None,
        temperature: float = 0.2,
    ) -> LLMResponse:
        key, pin, request = self._fixture_key(messages, tools, model, temperature)
        request_digest = prompt_digest(request["messages"], request["tools"])
        tool_schema_hash = content_hash(request["tools"] or [])

        hit = (
            self._store.get_optional(key, owner_user_id=self._owner_user_id)
            if self._mode != "passthrough"
            else None
        )
        if hit is not None:
            if self._mode in ("record", "replay"):
                invocation_id = self._next_invocation_id()
                replayed = self._from_fixture(hit)
                audit, refusal_kind = self._verified_replay_audit(hit, replayed)
                if audit is None:
                    self._persist_replay_terminal(
                        invocation_id=invocation_id,
                        request_digest=request_digest,
                        tool_schema_hash=tool_schema_hash,
                        fixture_key=key,
                        status=CallStatus.REFUSED.value,
                        replay_state=ReplayState.REPLAYED.value,
                        error_kind=refusal_kind,
                    )
                    self._store.record_replay_event(
                        "replay_hit",
                        owner_user_id=self._owner_user_id,
                        fixture_key=key,
                        run_id=self._run_id,
                    )
                    raise ReplayMiss(
                        f"fixture_key={key} 缺 verified gateway audit origin，拒绝重放"
                    )
                self._persist_replay_terminal(
                    invocation_id=invocation_id,
                    request_digest=request_digest,
                    tool_schema_hash=tool_schema_hash,
                    fixture_key=key,
                    status=CallStatus.OK.value,
                    replay_state=ReplayState.REPLAYED.value,
                    response=replayed,
                    audit=audit,
                )
            self._store.record_replay_event(
                "replay_hit",
                owner_user_id=self._owner_user_id,
                fixture_key=key,
                run_id=self._run_id,
            )
            self._step += 1
            self._upstream = key
            return replayed if self._mode in ("record", "replay") else self._from_fixture(hit)

        if self._mode == "replay":
            # R11 命门：未命中绝不打真 API。
            invocation_id = self._next_invocation_id()
            self._persist_replay_terminal(
                invocation_id=invocation_id,
                request_digest=request_digest,
                tool_schema_hash=tool_schema_hash,
                fixture_key=key,
                status=CallStatus.REFUSED.value,
                replay_state=ReplayState.LIVE.value,
                error_kind="replay_fixture_miss",
            )
            self._store.record_replay_event(
                "replay_miss",
                owner_user_id=self._owner_user_id,
                fixture_key=key,
                run_id=self._run_id,
            )
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
            model_pin = actual_pin.to_dict()
            audit = self._verified_gateway_audit(resp)
            if audit is not None:
                model_pin = attach_gateway_audit_metadata(model_pin, **audit)
            fixture = LLMFixture(
                fixture_key=key, run_id=self._run_id, repro_level=self._repro_level.value,
                model_pin=model_pin, request=request,
                response=_response_to_dict(resp), tool_calls=tool_calls,
                translation_status=status, owner_ref=owner_scope_ref(self._owner_user_id),
            )
            self._store.put(fixture, owner_user_id=self._owner_user_id)

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
