"""LLM Gateway · 所有 LLM 调用的【唯一入口】（GOAL §7 Orchestrator→LLM Gateway→role dispatch）。

唯一入口规则（§7 / §1）：
- role agent **绝不**直接调 provider SDK / 读 API key——只交「能力需求 + 上下文」，拿回
  `(LLMResponse, LLMCallRecord)`。明文凭据只在 gateway 内物化、调用后即丢、绝不落账/日志。
- 每次调用按 ModelRoutingPolicy（混合自适应）选 provider/model/credential_pool，逐 attempt 与 terminal 落 LLMCallRecord
  （provider/model/auth_ref/replay_state + 路由档 + 独立性 + 健康/配额/fallback），可审计 · 进 RDP。
- gateway 给每条账盖封印；下游 `assert_admissible_to_graph` 只认封印过的账——**绕过 Gateway 的
  LLM 结果对 Research Graph 不可准入**（§7「AgentLLMCall 绕过 LLM Gateway → 拒」的可落地形态）。

本卡边界（诚实残余）：只建 Gateway 核 + 路由 + 凭据池 + 调用账 + 健康/fallback。
Agent Orchestrator 全栈 + 12 role + 23 事件**投影**到 user 工作流 = 另卡；本模块只把 LLM 相关事件
（LLMRouteSelected / CredentialPoolSelected / LLMCallStarted / LLMCallFinished / ProviderFallbackUsed）
作为**数据**挂到结果上，供 Orchestrator 卡去投影。

**wrap 现有 agent/llm_client.py + llm_providers.py（不重建）**：默认 client 工厂走 `make_llm_client`，
现有 provider adapter 成 gateway 后端。record/replay truth 由外部受验证 fixture seam 持有；本 provider
gateway 不把 caller flag 或 provider response attribute 当作 replay 证据。
"""

from __future__ import annotations

import logging
import math
import secrets
import threading
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from typing import Any

from ..agent.llm_client import LLMClient, LLMMessage, LLMResponse, NoLLMConfigured
from .call_record import (
    CallRecordKind,
    CallStatus,
    IndependenceRecord,
    LLMCallRecord,
    LLMRecordError,
    ReplayState,
    SecretLeakError,
    assert_no_plaintext_secret,
    assert_record_admissible,
    make_call_id,
    reported_cost_evidence,
    response_ref_from_digest,
    scan_messages_for_secret,
    seal_record,
    unavailable_cost_evidence,
    verify_record_seal,
)
from .credential_pool import LLMCredentialPool, MaterializedCredential, SecretRef
from .model_identity import has_independent_model_route
from .routing import (
    LLMModelProfile,
    ModelRoutingPolicy,
    ModelTier,
    RoleCapabilityRequest,
    RoutingDecision,
    RoutingError,
    RoutingMode,
    infer_capability_tier,
)
from .use_binding import (
    LLMGatewayUseBindingRecord,
    LLMUseBindingError,
    make_llm_gateway_use_binding,
)

logger = logging.getLogger(__name__)  # 注意：本模块绝不 log 明文 secret / 原始 prompt。


# ============ provider 健康 / 配额 ============

@dataclass
class ProviderHealth:
    provider: str
    healthy: bool = True
    consecutive_failures: int = 0
    last_error: str = ""
    state: str = "healthy"          # healthy / degraded / down

    def to_dict(self) -> dict[str, Any]:
        return {
            "provider": self.provider,
            "healthy": self.healthy,
            "consecutive_failures": self.consecutive_failures,
            "last_error": self.last_error,
            "state": self.state,
        }


@dataclass
class QuotaStatus:
    provider: str
    exhausted: bool = False
    remaining: int | None = None
    reset_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "provider": self.provider,
            "exhausted": self.exhausted,
            "remaining": self.remaining,
            "reset_at": self.reset_at,
        }


# ============ 事件（数据 only · 投影是另卡）============

# §7 可见事件类型里 LLM 相关那几枚。
EV_ROUTE_SELECTED = "LLMRouteSelected"
EV_CREDENTIAL_SELECTED = "CredentialPoolSelected"
EV_CALL_STARTED = "LLMCallStarted"
EV_CALL_FINISHED = "LLMCallFinished"
EV_FALLBACK_USED = "ProviderFallbackUsed"


@dataclass
class LLMGatewayEvent:
    kind: str
    data: dict[str, Any]


# ============ 请求 / 结果 ============

@dataclass
class LLMRequest:
    messages: list[LLMMessage]
    capability: RoleCapabilityRequest
    tools: list[dict[str, Any]] | None = None
    temperature: float = 0.2
    session_id: str = "default"
    owner_user_id: str = ""
    workflow_id: str = ""
    invocation_id: str = ""
    replay_mode: str = "live"        # caller hint only；replay 未经 fixture seam 证明即拒绝，不作为证据


@dataclass
class GatewaySealedResult:
    response: LLMResponse
    record: LLMCallRecord
    events: list[LLMGatewayEvent] = field(default_factory=list)
    audit_records: list[LLMCallRecord] = field(default_factory=list)
    use_binding: LLMGatewayUseBindingRecord | None = None


# ============ 异常 ============

class GatewayError(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        record: LLMCallRecord | None = None,
        records: list[LLMCallRecord] | None = None,
    ) -> None:
        super().__init__(message)
        self.record = record
        self.records = list(records or (() if record is None else (record,)))
        self.events: list[LLMGatewayEvent] = []


class DegradedRoutingError(GatewayError):
    """strict_degrade 模式下，难任务（HARD/不可逆）被迫降到不适配轻模型 → 拒绝调用（绝不静默降质）。"""


# ============ 默认 client 工厂（wrap 现有 provider 栈）============

def _default_client_factory(cred: MaterializedCredential) -> Any:
    """用现有 `make_llm_client` 把物化凭据接到既有 provider adapter（不重建 provider）。

    deny-by-default（GOAL §8）：只有【显式】登记的 `dev_local` 档才返回 DevLocalLLM；
    provider 为空/None（misconfiguration）→ 抛 `GatewayError`，**绝不**把缺配置静默当成 mock。
    """

    from ..agent.llm_client import DevLocalLLM
    from ..agent.llm_providers import make_llm_client

    if cred.provider == "dev_local":
        return DevLocalLLM()  # 显式 dev_local 档（非静默兜底）——routing 主动选到它才会走这里。
    if cred.auth_kind == "subscription_cli":
        # 跨厂商切模型 S5：订阅账号经厂商官方 CLI（claude/codex）调模型——不伪装 oauth_proxy/custom。
        # 凭据在 CLI 自己的安全存储，此处不持 key；provider 恒真（anthropic/openai）。
        from ..agent.subscription_cli_llm import make_subscription_cli_client
        return make_subscription_cli_client(cred.provider, model=cred.model or None)
    if not cred.provider:
        raise GatewayError(
            "物化凭据缺 provider —— deny-by-default 拒绝静默落 DevLocalLLM（GOAL §8 no-silent-mock）"
        )
    prov = "custom" if (cred.auth_kind == "oauth_proxy" or cred.provider == "custom") else cred.provider
    return make_llm_client(
        provider=prov,  # type: ignore[arg-type]
        api_key=cred.api_key or None,
        base_url=cred.base_url or None,
        model=cred.model or None,
    )


def _redact_url(url: str) -> str:
    """Persist only the endpoint origin; userinfo/path/query/fragment never enter audit rows."""

    if not url:
        return ""
    from urllib.parse import urlsplit

    try:
        parsed = urlsplit(url)
        if not parsed.scheme or not parsed.hostname:
            return ""
        host = parsed.hostname
        if ":" in host and not host.startswith("["):
            host = f"[{host}]"
        port = f":{parsed.port}" if parsed.port is not None else ""
        return f"{parsed.scheme.lower()}://{host}{port}"
    except (TypeError, ValueError):
        return ""


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _is_verifier(role: str) -> bool:
    r = (role or "").lower()
    return "verifier" in r or "critic" in r


def _controlled_ref(value: str) -> bool:
    return (
        bool(value)
        and value == value.strip()
        and len(value) <= 256
        and value.isascii()
        and all(char.isalnum() or char in "._:@/+=-" for char in value)
    )


def _extract_usage(resp: LLMResponse) -> dict[str, Any]:
    raw = getattr(resp, "raw", None) or {}
    usage = raw.get("usage") if isinstance(raw, dict) else None
    if not isinstance(usage, dict):
        return {}
    # Provider-controlled text is never audit metadata. Keep only finite numeric
    # counters so a response/error marker cannot hitch a ride into the journal.
    clean: dict[str, Any] = {}
    for key, value in usage.items():
        if type(value) is int:
            clean[str(key)] = value
        elif type(value) is float and math.isfinite(value):
            clean[str(key)] = value
    return clean


def _extract_cost_evidence(resp: LLMResponse | None, *, failure_stage: str) -> dict[str, Any]:
    """Keep provider-reported USD cost or an explicit unavailable reason.

    Token counts are never multiplied by a local price table: that would turn
    an estimate into provider evidence and would drift as prices change.
    """

    if resp is not None:
        raw = getattr(resp, "raw", None) or {}
        usage = raw.get("usage") if isinstance(raw, dict) else None
        if isinstance(usage, dict):
            for key, source in (
                ("cost_usd", "provider_usage_cost_usd"),
                ("total_cost_usd", "provider_usage_total_cost_usd"),
            ):
                amount = usage.get(key)
                if type(amount) in (int, float) and math.isfinite(amount) and amount >= 0:
                    return reported_cost_evidence(amount, source=source)
        return unavailable_cost_evidence("provider_cost_not_reported")
    if failure_stage in {"prompt_guard", "replay", "routing"}:
        return unavailable_cost_evidence("pre_route_no_provider_response")
    if failure_stage in {"credential", "degrade"}:
        return unavailable_cost_evidence("provider_not_called")
    return unavailable_cost_evidence("provider_cost_not_reported")


def _messages_text(messages: list[LLMMessage], tools: list[dict[str, Any]] | None) -> str:
    import json as _json

    parts: list[str] = []
    for m in messages:
        parts.append(str(m.content or ""))
        if m.tool_calls:
            parts.append(_json.dumps(m.tool_calls, ensure_ascii=False, default=str))
        if m.name:
            parts.append(str(m.name))
    if tools:
        parts.append(_json.dumps(tools, ensure_ascii=False, default=str))
    return "".join(parts)


def _messages_jsonable(messages: list[LLMMessage]) -> list[dict[str, Any]]:
    return [
        {"role": m.role, "content": m.content, "tool_calls": m.tool_calls,
         "tool_call_id": m.tool_call_id, "name": m.name}
        for m in messages
    ]


# ============ Gateway ============

class LLMGateway:
    """所有 LLM 调用的唯一入口。"""

    def __init__(
        self,
        *,
        policy: ModelRoutingPolicy,
        credential_pool: LLMCredentialPool,
        client_factory: Callable[[MaterializedCredential], Any] | None = None,
        strict_degrade: bool = True,
        scan_prompt_secrets: bool = True,
        seal_secret: bytes | None = None,
        record_sink: Callable[[LLMCallRecord], None] | None = None,
        use_binding_sink: Callable[[LLMGatewayUseBindingRecord], Any] | None = None,
        service_principal_ref: str = "",
        credential_pool_refs: Mapping[str, str] | None = None,
        routing_policy_refs: Mapping[str, str] | None = None,
        default_pin: tuple[str, str] | None = None,
    ) -> None:
        self._policy = policy
        self._pool = credential_pool
        # 跨厂商切模型 S3：用户对本对话手选的 (provider, model)。在 complete() 里对**非独立**请求盖章成
        # hard pin——覆盖真实主链两条消费路径(GatewayLLMAdapter + GatewayBackedLLMClient,均汇入 complete)，
        # 不依赖任一 adapter 传 model。独立审查请求(verifier)永不盖章 → dual-model 门物理免疫(见 complete)。
        self._default_pin = (
            (str(default_pin[0]), str(default_pin[1])) if default_pin else None
        )
        self._cap = credential_pool.issue_capability()  # 唯一物化令牌，握在 gateway 内
        self._client_factory = client_factory or _default_client_factory
        self._strict_degrade = strict_degrade
        self._scan_prompt = scan_prompt_secrets
        if seal_secret is not None and len(seal_secret) < 32:
            raise ValueError("LLM gateway seal_secret must contain at least 32 bytes")
        self._seal_secret = bytes(seal_secret) if seal_secret is not None else secrets.token_bytes(32)
        self._durable_seal_key = seal_secret is not None
        self._record_sink = record_sink
        self._use_binding_sink = use_binding_sink
        self._service_principal_ref = str(service_principal_ref or "").strip()
        self._credential_pool_refs = {
            str(key): str(value or "").strip()
            for key, value in dict(credential_pool_refs or {}).items()
        }
        self._routing_policy_refs = {
            str(key): str(value or "").strip()
            for key, value in dict(routing_policy_refs or {}).items()
        }
        if use_binding_sink is not None:
            if not callable(use_binding_sink):
                raise TypeError("LLM use_binding_sink must be callable")
            if not self._durable_seal_key:
                raise ValueError(
                    "LLM use_binding_sink requires an explicitly injected stable seal_secret"
                )
            if (
                not _controlled_ref(self._service_principal_ref)
                or not self._service_principal_ref.startswith("service:")
            ):
                raise ValueError("LLM use_binding_sink requires service_principal_ref")
            pool_ids = {profile.pool_id for profile in self._policy.profiles}
            if (
                set(self._credential_pool_refs) != pool_ids
                or set(self._routing_policy_refs) != pool_ids
                or not all(
                    _controlled_ref(key) and _controlled_ref(value)
                    for key, value in self._credential_pool_refs.items()
                )
                or not all(
                    _controlled_ref(key) and _controlled_ref(value)
                    for key, value in self._routing_policy_refs.items()
                )
            ):
                raise ValueError(
                    "LLM use_binding_sink requires exact credential-pool and routing-policy "
                    "refs for every runtime pool"
                )
        self._health: dict[str, ProviderHealth] = {}
        self._quota: dict[str, QuotaStatus] = {}
        self._builder_sig: dict[str, tuple[str, str, str]] = {}  # session -> (provider, model, call_id)
        self._invocation_lock = threading.Lock()
        self._claimed_invocations: dict[tuple[str, str, str], str] = {}

    # —— 健康 / 配额（可被外部按 provider 响应更新）——

    def health(self, provider: str) -> ProviderHealth:
        return self._health.setdefault(provider, ProviderHealth(provider=provider))

    def quota(self, provider: str) -> QuotaStatus:
        return self._quota.setdefault(provider, QuotaStatus(provider=provider))

    def mark_quota_exhausted(self, provider: str, *, reset_at: str = "") -> None:
        q = self.quota(provider)
        q.exhausted = True
        q.reset_at = reset_at

    def _mark_ok(self, provider: str) -> None:
        h = self.health(provider)
        h.healthy = True
        h.consecutive_failures = 0
        h.state = "healthy"
        h.last_error = ""

    def _mark_fail(self, provider: str, kind: str) -> None:
        h = self.health(provider)
        h.consecutive_failures += 1
        h.last_error = kind  # kind = 异常类名 / 原因，绝不含 secret
        h.healthy = h.consecutive_failures < 1  # 一次失败即视为本轮不健康
        h.state = "down" if h.consecutive_failures >= 2 else "degraded"

    def _unavailable_providers(self) -> set[str]:
        bad = {p for p, h in self._health.items() if not h.healthy}
        bad |= {p for p, q in self._quota.items() if q.exhausted}
        return bad

    # —— 唯一入口 ——

    def complete(
        self,
        request: LLMRequest,
        *,
        record_sink: Callable[[LLMCallRecord], None] | None = None,
    ) -> GatewaySealedResult:
        events: list[LLMGatewayEvent] = []
        audit_records: list[LLMCallRecord] = []
        sink = record_sink if record_sink is not None else self._record_sink
        if sink is not None and not self._durable_seal_key:
            raise LLMRecordError(
                "durable LLM record_sink requires an explicitly injected stable seal_secret"
            )
        if self._use_binding_sink is not None and sink is None:
            raise LLMUseBindingError(
                "LLM use binding requires a durable terminal call record_sink"
            )
        req = request.capability
        # 跨厂商切模型 S3：构造期注入的 default_pin 在此盖章成 hard pin——**仅**当请求非独立审查
        # (not independence_required) 且本身未带 pin。verifier/critic 带 independence_required=True →
        # 跳过盖章 → dual-model 独立门物理免疫用户手选(叠加 routing.resolve 里同款闸,双层)。
        if (
            self._default_pin is not None
            and not req.independence_required
            and not _is_verifier(req.role)  # 纵深:role 是 verifier/critic 也不盖章(即便漏设 independence 标志)
            and not req.pin_provider
        ):
            req = replace(req, pin_provider=self._default_pin[0], pin_model=self._default_pin[1])
        owner, workflow, invocation_id = self._request_scope(request)
        started = _now_iso()
        t0 = time.perf_counter()
        prompt_digest = self._prompt_digest(request)
        self._claim_invocation(
            owner_user_id=owner,
            workflow_id=workflow,
            invocation_id=invocation_id,
            prompt_digest=prompt_digest,
            sink=sink,
        )

        # 0) prompt secret guard —— 真打前先扫：在册明文 secret（含实盘 key）绝不随 prompt 出门。
        try:
            if self._scan_prompt:
                self._guard_prompt(request)
        except SecretLeakError as exc:
            record = self._build_outcome_record(
                request=request,
                decision=None,
                cred=None,
                resp=None,
                started=started,
                finished=_now_iso(),
                latency_ms=round((time.perf_counter() - t0) * 1000.0, 3),
                fallback_used=False,
                fallback_chain=[],
                builder_full=None,
                invocation_id=invocation_id,
                prompt_digest=prompt_digest,
                record_kind=CallRecordKind.TERMINAL.value,
                attempt_no=1,
                status=CallStatus.REFUSED.value,
                error_kind="prompt_secret_refusal",
                failure_stage="prompt_guard",
            )
            self._emit_audit_record(record, audit_records, sink=sink, events=events)
            exc.record = record  # type: ignore[attr-defined]
            exc.records = list(audit_records)  # type: ignore[attr-defined]
            exc.events = list(events)  # type: ignore[attr-defined]
            raise

        # A caller-declared replay flag is not replay evidence. The verified
        # FixtureStore/RecordingLLMClient seam owns replay hits; this provider
        # gateway must never call a live provider while claiming "replayed".
        if str(request.replay_mode or "live").strip().lower() == "replay":
            record = self._build_outcome_record(
                request=request,
                decision=None,
                cred=None,
                resp=None,
                started=started,
                finished=_now_iso(),
                latency_ms=round((time.perf_counter() - t0) * 1000.0, 3),
                fallback_used=False,
                fallback_chain=[],
                builder_full=None,
                invocation_id=invocation_id,
                prompt_digest=prompt_digest,
                record_kind=CallRecordKind.TERMINAL.value,
                attempt_no=1,
                status=CallStatus.REFUSED.value,
                error_kind="unverified_replay_request",
                failure_stage="replay",
            )
            self._emit_audit_record(record, audit_records, sink=sink, events=events)
            error = GatewayError(
                "replay request lacks a verified replay outcome; live provider access refused",
                record=record,
                records=audit_records,
            )
            error.events = list(events)  # type: ignore[attr-defined]
            raise error

        # 1) 路由（混合自适应）+ 独立性排除 builder 签名。
        builder_sig = self._builder_sig.get(request.session_id)
        builder_signature = (builder_sig[0], builder_sig[1]) if builder_sig else None
        try:
            decision = self._policy.resolve(
                req,
                unavailable_providers=self._unavailable_providers(),
                builder_signature=builder_signature,
            )
        except RoutingError as exc:
            record = self._build_outcome_record(
                request=request,
                decision=None,
                cred=None,
                resp=None,
                started=started,
                finished=_now_iso(),
                latency_ms=round((time.perf_counter() - t0) * 1000.0, 3),
                fallback_used=False,
                fallback_chain=[],
                builder_full=builder_sig,
                invocation_id=invocation_id,
                prompt_digest=prompt_digest,
                record_kind=CallRecordKind.TERMINAL.value,
                attempt_no=1,
                status=CallStatus.ERROR.value,
                error_kind=type(exc).__name__,
                failure_stage="routing",
            )
            self._emit_audit_record(record, audit_records, sink=sink, events=events)
            error = GatewayError(
                f"路由失败：{type(exc).__name__}",
                record=record,
                records=audit_records,
            )
            error.events = list(events)  # type: ignore[attr-defined]
            raise error from None
        events.append(
            LLMGatewayEvent(
                EV_ROUTE_SELECTED,
                {
                    **self._route_event(decision),
                    "invocation_id": invocation_id,
                    "attempt_no": 1,
                },
            )
        )
        try:
            self._enforce_strict_degrade(decision, req)
        except DegradedRoutingError as exc:
            record = self._build_outcome_record(
                request=request,
                decision=decision,
                cred=None,
                resp=None,
                started=started,
                finished=_now_iso(),
                latency_ms=round((time.perf_counter() - t0) * 1000.0, 3),
                fallback_used=False,
                fallback_chain=[],
                builder_full=builder_sig,
                invocation_id=invocation_id,
                prompt_digest=prompt_digest,
                record_kind=CallRecordKind.TERMINAL.value,
                attempt_no=1,
                status=CallStatus.REFUSED.value,
                error_kind="strict_degrade_refusal",
                failure_stage="degrade",
            )
            self._emit_audit_record(record, audit_records, sink=sink, events=events)
            exc.record = record
            exc.records = list(audit_records)
            exc.events = list(events)  # type: ignore[attr-defined]
            raise

        # 2) 调用（带健康/配额 fallback）。
        resp, decision, cred, fallback_used, fallback_chain, attempt_no = self._invoke_with_fallback(
            request,
            decision,
            events,
            builder_signature,
            effective_capability=req,  # 盖章后的 capability(含 default_pin)——贯穿 fallback,防 pin 蒸发
            started=started,
            t0=t0,
            invocation_id=invocation_id,
            prompt_digest=prompt_digest,
            builder_full=builder_sig,
            audit_records=audit_records,
            sink=sink,
        )

        # 3) 组账。
        finished = _now_iso()
        latency_ms = round((time.perf_counter() - t0) * 1000.0, 3)
        record = self._build_outcome_record(
            request=request,
            decision=decision,
            cred=cred,
            resp=resp,
            started=started,
            finished=finished,
            latency_ms=latency_ms,
            fallback_used=fallback_used,
            fallback_chain=fallback_chain,
            builder_full=builder_sig,
            invocation_id=invocation_id,
            prompt_digest=prompt_digest,
            record_kind=CallRecordKind.TERMINAL.value,
            attempt_no=attempt_no,
            status=CallStatus.OK.value,
            error_kind="",
            failure_stage="",
        )
        # 4/5) secret/admission/seal + durable sink。
        self._emit_audit_record(
            record,
            audit_records,
            sink=sink,
            materialized=cred,
            events=events,
        )
        use_binding = self._emit_use_binding(record, decision)

        # 6) 独立性簿记：builder 调用更新 session 签名（verifier 不更新）。
        if not _is_verifier(req.role):
            self._builder_sig[request.session_id] = (record.provider, record.model, record.call_id)

        # cred（含明文）随函数返回出作用域被回收；绝不外泄、绝不日志。
        return GatewaySealedResult(
            response=resp,
            record=record,
            events=events,
            audit_records=list(audit_records),
            use_binding=use_binding,
        )

    # —— 下游准入门（bypass gate）——

    def verify(self, result: GatewaySealedResult) -> bool:
        """这条账是否由持同一受控 seal key 的 gateway 封印。"""

        return verify_record_seal(result.record, self._seal_secret)

    def assert_record_secret_clean(
        self,
        record: LLMCallRecord,
        *,
        materialized: MaterializedCredential | None = None,
    ) -> None:
        """断言 record 不含任一在册明文 secret（含本次实际物化的 key）。"""

        secret_values = list(self._pool.known_secret_values())
        if materialized is not None and materialized.api_key:
            secret_values.append(materialized.api_key)
        assert_no_plaintext_secret(record, secret_values)

    # —— 内部 ——

    @staticmethod
    def _request_scope(request: LLMRequest) -> tuple[str, str, str]:
        owner = str(request.owner_user_id or "").strip()
        workflow = str(request.workflow_id or "").strip()
        invocation = str(request.invocation_id or "").strip()
        if not owner:
            raise LLMRecordError("LLM request owner_user_id is required")
        if not workflow:
            raise LLMRecordError("LLM request workflow_id is required")
        if not invocation:
            raise LLMRecordError("LLM request invocation_id is required")
        return owner, workflow, invocation

    @staticmethod
    def _prompt_digest(request: LLMRequest) -> str:
        from ..lineage.ids import content_hash

        return content_hash({
            "messages": _messages_jsonable(request.messages),
            "tools": request.tools or [],
            "temperature": request.temperature,
            "capability": {
                "role": request.capability.role,
                "difficulty": request.capability.difficulty,
                "risk": request.capability.risk,
                "independence_required": request.capability.independence_required,
            },
        })

    def _claim_invocation(
        self,
        *,
        owner_user_id: str,
        workflow_id: str,
        invocation_id: str,
        prompt_digest: str,
        sink: Callable[[LLMCallRecord], None] | None,
    ) -> None:
        """Fail closed on a reused caller idempotency envelope before provider access."""

        key = (owner_user_id, workflow_id, invocation_id)
        with self._invocation_lock:
            previous = self._claimed_invocations.get(key)
            if previous is not None:
                detail = "same request" if previous == prompt_digest else "different request"
                raise LLMRecordError(
                    f"LLM invocation_id was already claimed by a {detail}; provider access refused"
                )

            # A bound durable-store append exposes a durable pre-provider claim.
            # This closes restart/process retries for the canonical direct sink
            # without teaching the gateway about a concrete store implementation.
            sink_owner = getattr(sink, "__self__", None) if sink is not None else None
            claim = getattr(sink, "claim_invocation", None) if sink is not None else None
            if not callable(claim):
                claim = getattr(sink_owner, "claim_invocation", None)
            if callable(claim):
                claim(
                    owner_user_id=owner_user_id,
                    workflow_id=workflow_id,
                    invocation_id=invocation_id,
                    prompt_digest=prompt_digest,
                )
                self._claimed_invocations[key] = prompt_digest
                return
            lookup = getattr(sink, "invocation_records", None) if sink is not None else None
            if not callable(lookup):
                lookup = getattr(sink_owner, "invocation_records", None)
            if callable(lookup):
                existing = lookup(
                    owner_user_id=owner_user_id,
                    workflow_id=workflow_id,
                    invocation_id=invocation_id,
                )
                if existing:
                    raise LLMRecordError(
                        "LLM invocation_id already has durable audit evidence; provider access refused"
                    )
            self._claimed_invocations[key] = prompt_digest

    @staticmethod
    def _safe_error_kind(value: str) -> str:
        raw = str(value or "unknown_error")
        safe = "".join(ch if (ch.isalnum() or ch in "._-") else "_" for ch in raw)
        return safe[:96] or "unknown_error"

    def _routing_policy_evidence(
        self,
        decision: RoutingDecision | None,
    ) -> tuple[str, str]:
        """Return server-derived routing evidence for the exact runtime policy."""

        if decision is None:
            return "", "unresolved_pre_route"
        configured = self._routing_policy_refs.get(decision.profile.pool_id, "")
        if _controlled_ref(configured):
            return configured, "configured_ref"
        from ..lineage.ids import content_hash

        profiles = sorted(
            (
                {
                    "provider": profile.provider,
                    "model": profile.model,
                    "capability_tier": profile.capability_tier,
                    "pool_id": profile.pool_id,
                    "supports_tools": profile.supports_tools,
                    "context_window": profile.context_window,
                }
                for profile in self._policy.profiles
            ),
            key=lambda item: (
                item["provider"], item["model"], item["pool_id"], item["capability_tier"]
            ),
        )
        digest = content_hash({
            "schema": "llm_runtime_routing_policy.v1",
            "mode": self._policy.mode.value,
            "profiles": profiles,
        })
        return f"routing:runtime:{digest}", "runtime_digest"

    def _emit_audit_record(
        self,
        record: LLMCallRecord,
        audit_records: list[LLMCallRecord],
        *,
        sink: Callable[[LLMCallRecord], None] | None,
        materialized: MaterializedCredential | None = None,
        events: list[LLMGatewayEvent] | None = None,
    ) -> None:
        """Seal/persist first, then expose the matching sanitized finish event."""

        self.assert_record_secret_clean(record, materialized=materialized)
        assert_record_admissible(record)
        record.seal = seal_record(record, self._seal_secret)
        if sink is not None:
            sink(record)
        audit_records.append(record)
        if events is not None and (
            record.record_kind == CallRecordKind.TERMINAL.value
            or record.status in {CallStatus.ERROR.value, CallStatus.REFUSED.value}
        ):
            events.append(
                LLMGatewayEvent(
                    EV_CALL_FINISHED,
                    {
                        "call_id": record.call_id,
                        "provider": record.provider,
                        "model": record.model,
                        "status": record.status,
                        "replay_state": record.replay_state,
                        "latency_ms": record.latency_ms,
                        "invocation_id": record.invocation_id,
                        "attempt_no": record.attempt_no,
                        "record_kind": record.record_kind,
                        "failure_stage": record.failure_stage,
                        "error_kind": record.error_kind,
                    },
                )
            )

    def _emit_use_binding(
        self,
        terminal_record: LLMCallRecord,
        decision: RoutingDecision,
    ) -> LLMGatewayUseBindingRecord | None:
        """Persist the server-derived selection only after terminal audit durability."""

        if self._use_binding_sink is None:
            return None
        runtime_pool_id = decision.profile.pool_id
        credential_pool_ref = self._credential_pool_refs.get(runtime_pool_id, "")
        routing_policy_ref, routing_policy_state = self._routing_policy_evidence(decision)
        if terminal_record.provider != decision.profile.provider:
            raise LLMUseBindingError(
                "terminal provider does not match the gateway routing decision"
            )
        if (
            terminal_record.routing_policy_ref != routing_policy_ref
            or terminal_record.routing_policy_state != routing_policy_state
        ):
            raise LLMUseBindingError(
                "terminal routing policy evidence does not match the gateway runtime policy"
            )
        binding = make_llm_gateway_use_binding(
            terminal_record,
            service_principal_ref=self._service_principal_ref,
            credential_pool_ref=credential_pool_ref,
            routing_policy_ref=routing_policy_ref,
            seal_secret=self._seal_secret,
        )
        persisted = self._use_binding_sink(binding)
        if persisted != binding:
            raise LLMUseBindingError(
                "LLM use binding sink did not confirm the exact persisted evidence"
            )
        return binding

    def _build_outcome_record(
        self,
        *,
        request: LLMRequest,
        decision: RoutingDecision | None,
        cred: MaterializedCredential | None,
        resp: LLMResponse | None,
        started: str,
        finished: str,
        latency_ms: float,
        fallback_used: bool,
        fallback_chain: list[str],
        builder_full: tuple[str, str, str] | None,
        invocation_id: str,
        prompt_digest: str,
        record_kind: str,
        attempt_no: int,
        status: str,
        error_kind: str,
        failure_stage: str,
    ) -> LLMCallRecord:
        from ..lineage.ids import content_hash

        req = request.capability
        owner, workflow, scoped_invocation = self._request_scope(request)
        if invocation_id != scoped_invocation:
            raise LLMRecordError("LLM invocation scope changed during completion")

        provider = ""
        model = ""
        auth_ref = ""
        if decision is not None:
            profile = decision.profile
            provider = profile.provider or ""
            model = profile.model or "unknown"
            try:
                descriptor = self._pool.describe(profile.pool_id)
            except Exception:  # noqa: BLE001 -- descriptor failure is represented by safe sentinels.
                descriptor = None
            if descriptor is not None:
                provider = descriptor.provider or provider
                model = profile.model or descriptor.default_model or model
                auth_ref = descriptor.auth_ref or auth_ref
        if cred is not None:
            provider = cred.provider or provider
            model = (decision.profile.model if decision is not None else "") or cred.model or model
            auth_ref = cred.auth_ref or auth_ref

        if decision is not None:
            independence = self._build_independence(
                req,
                provider=provider,
                model=model,
                builder_full=builder_full,
            )
            tier_requested = decision.tier_requested
            tier_resolved = decision.tier_resolved
            degraded = decision.degraded
            degrade_reason = decision.degrade_reason
        else:
            independence = IndependenceRecord(
                required=bool(req.independence_required),
                satisfied=False,
                reason="",
            )
            tier_requested = ""
            tier_resolved = ""
            degraded = False
            degrade_reason = ""

        routing_policy_ref, routing_policy_state = self._routing_policy_evidence(decision)

        replay_state, fixture_key = self._detect_replay_state(request, resp)
        response_digest = ""
        if resp is not None:
            response_digest = content_hash({
                "content": resp.content,
                "tool_calls": resp.tool_calls,
            })
        response_ref = response_ref_from_digest(response_digest)
        tool_schema_hash = content_hash(request.tools or [])
        call_id = make_call_id(
            prompt_digest=prompt_digest,
            provider=provider,
            model=model,
            role=req.role,
            session_id=request.session_id,
            seq=attempt_no,
            owner_user_id=owner,
            workflow_id=workflow,
            invocation_id=invocation_id,
            record_kind=record_kind,
            attempt_no=attempt_no,
        )
        if not provider:
            provider_health = "unknown"
            quota_state = "unknown"
        else:
            provider_health = self.health(provider).state
            quota_state = "exhausted" if self.quota(provider).exhausted else "ok"
        repro = str(getattr(resp, "repro_level", "decision") or "decision") if resp is not None else "decision"
        if repro not in {"decision", "token", "exact"}:
            repro = "decision"
        return LLMCallRecord(
            provider=provider,
            model=model,
            auth_ref=auth_ref,
            replay_state=replay_state,
            owner_user_id=owner,
            workflow_id=workflow,
            invocation_id=invocation_id,
            record_kind=record_kind,
            attempt_no=attempt_no,
            role=req.role,
            task_difficulty=req.difficulty,
            risk_level=req.risk,
            tier_requested=tier_requested,
            tier_resolved=tier_resolved,
            degraded=degraded,
            degrade_reason="",
            routing_policy_ref=routing_policy_ref,
            routing_policy_state=routing_policy_state,
            independence=independence,
            provider_health=provider_health,
            quota_state=quota_state,
            fallback_used=fallback_used,
            fallback_chain=[],
            call_id=call_id,
            session_id=request.session_id,
            prompt_digest=prompt_digest,
            prompt_hash=prompt_digest,
            tool_schema_hash=tool_schema_hash,
            response_digest=response_digest,
            response_ref=response_ref,
            base_url_redacted="",
            fixture_key=fixture_key,
            started_at=started,
            finished_at=finished,
            latency_ms=latency_ms,
            usage=_extract_usage(resp) if resp is not None else {},
            cost=_extract_cost_evidence(resp, failure_stage=failure_stage),
            status=status,
            error_kind="" if status == CallStatus.OK.value else self._safe_error_kind(error_kind),
            failure_stage=failure_stage,
            repro_level=repro,
        )

    def _guard_prompt(self, request: LLMRequest) -> None:
        text = _messages_text(request.messages, request.tools)
        hit = scan_messages_for_secret(text, self._pool.known_secret_values())
        if hit is not None:
            # 致命红线：实盘 key/secret 进 LLM prompt。绝不回显 secret。
            raise SecretLeakError(
                f"prompt 夹带在册明文 secret（len={len(hit)}）——拒发：实盘 key/secret 不进 LLM/RAG（GOAL §1 红线）"
            )

    def _enforce_strict_degrade(self, decision: RoutingDecision, req: RoleCapabilityRequest) -> None:
        if not self._strict_degrade or not decision.degraded:
            return
        if decision.tier_requested == ModelTier.STRONG.value:
            raise DegradedRoutingError(
                "难任务（HARD/不可逆）无强模型可用，strict_degrade 拒绝静默降到轻模型"
                f"（{decision.degrade_reason}）。可显式 strict_degrade=False 接受降质并留账。",
            )

    def _invoke_with_fallback(
        self,
        request: LLMRequest,
        decision: RoutingDecision,
        events: list[LLMGatewayEvent],
        builder_signature: tuple[str, str] | None,
        *,
        effective_capability: RoleCapabilityRequest,
        started: str,
        t0: float,
        invocation_id: str,
        prompt_digest: str,
        builder_full: tuple[str, str, str] | None,
        audit_records: list[LLMCallRecord],
        sink: Callable[[LLMCallRecord], None] | None,
    ) -> tuple[LLMResponse, RoutingDecision, MaterializedCredential, bool, list[str], int]:
        # 跨厂商切模型 S3a 命门修复：用**盖章后**的 effective_capability(含 default_pin)驱动
        # degrade 校验 + _refallback 重 resolve——否则 fallback 会重读原始未盖章 capability、
        # pin 蒸发 → 静默跨厂商泄漏(S3a skeptic CRITICAL-1)。record 仍读原始 request.capability 保诚实。
        req = effective_capability
        excluded: set[tuple[str, str]] = set()
        fallback_chain: list[str] = []
        fallback_used = False
        current = decision
        attempt_no = 0

        def build_record(
            *,
            target: RoutingDecision,
            credential: MaterializedCredential | None,
            record_kind: str,
            status: str,
            error_kind: str,
            failure_stage: str,
            response: LLMResponse | None = None,
        ) -> LLMCallRecord:
            return self._build_outcome_record(
                request=request,
                decision=target,
                cred=credential,
                resp=response,
                started=started,
                finished=_now_iso(),
                latency_ms=round((time.perf_counter() - t0) * 1000.0, 3),
                fallback_used=fallback_used,
                fallback_chain=fallback_chain,
                builder_full=builder_full,
                invocation_id=invocation_id,
                prompt_digest=prompt_digest,
                record_kind=record_kind,
                attempt_no=attempt_no,
                status=status,
                error_kind=error_kind,
                failure_stage=failure_stage,
            )

        while True:
            # strict_degrade 单点 enforce（C-S7 Gap1 补修 · GOAL §8）：唯一执行点在 while 顶，
            # 永在任何 except / fallback 分支的活跃异常上下文【之外】——fallback 落「降级强档」时
            # 抛的 DegradedRoutingError 绝不隐式 chain 上一轮 provider 异常（其 str()/traceback
            # 可能夹明文 → 经 ERROR_REPORTER 落 errors.jsonl 即泄）。complete() 入口已先校验初始
            # decision；此处再校验每个 fallback 目标（同决策幂等、无副作用、不破降级语义）。
            attempt_no += 1
            try:
                self._enforce_strict_degrade(current, req)
            except DegradedRoutingError as exc:
                terminal = build_record(
                    target=current,
                    credential=None,
                    record_kind=CallRecordKind.TERMINAL.value,
                    status=CallStatus.REFUSED.value,
                    error_kind="strict_degrade_refusal",
                    failure_stage="degrade",
                )
                self._emit_audit_record(
                    terminal, audit_records, sink=sink, events=events
                )
                exc.record = terminal
                exc.records = list(audit_records)
                exc.events = list(events)  # type: ignore[attr-defined]
                raise
            profile = current.profile
            cred: MaterializedCredential | None = None
            try:
                cred = self._pool.materialize(profile.pool_id, capability=self._cap)
            except Exception as exc:  # noqa: BLE001 -- persist only the exception type.
                failure_kind = type(exc).__name__
                failure_category = "credential"
            else:
                failure_kind = ""
                failure_category = ""

            if cred is None:
                self._mark_fail(profile.provider, failure_kind)
                excluded.add(profile.signature)
                fallback_chain.append(
                    f"{profile.provider}/{profile.model}:credential_{self._safe_error_kind(failure_kind)}"
                )
                attempt = build_record(
                    target=current,
                    credential=None,
                    record_kind=CallRecordKind.ATTEMPT.value,
                    status=CallStatus.ERROR.value,
                    error_kind=failure_kind,
                    failure_stage="credential",
                )
                self._emit_audit_record(
                    attempt, audit_records, sink=sink, events=events
                )
            else:
                events.append(LLMGatewayEvent(EV_CREDENTIAL_SELECTED, {
                    "pool_id": profile.pool_id, "provider": cred.provider,
                    "auth_kind": cred.auth_kind, "auth_ref": cred.auth_ref,
                    "invocation_id": invocation_id, "attempt_no": attempt_no,
                }))

                # api_key 档却无 key → 本次 credential attempt 失败并触发 fallback。
                if not cred.has_usable_key:
                    failure_kind = "no_usable_credential"
                    failure_category = "credential"
                    self._mark_fail(profile.provider, failure_kind)
                    excluded.add(profile.signature)
                    fallback_chain.append(f"{profile.provider}/{profile.model}:no_key")
                    attempt = build_record(
                        target=current,
                        credential=cred,
                        record_kind=CallRecordKind.ATTEMPT.value,
                        status=CallStatus.ERROR.value,
                        error_kind=failure_kind,
                        failure_stage="credential",
                    )
                    self._emit_audit_record(
                        attempt,
                        audit_records,
                        sink=sink,
                        materialized=cred,
                        events=events,
                    )
                else:
                    events.append(LLMGatewayEvent(EV_CALL_STARTED, {
                        "provider": cred.provider, "model": profile.model, "tier": profile.capability_tier,
                        "invocation_id": invocation_id, "attempt_no": attempt_no,
                    }))
                    try:
                        client = self._client_factory(cred)
                        resp = client.chat(
                            request.messages,
                            tools=request.tools,
                            model=profile.model or cred.model or None,
                            temperature=request.temperature,
                        )
                    except Exception as exc:  # noqa: BLE001 -- persist only the exception type.
                        failure_kind = type(exc).__name__
                        failure_category = "provider"
                    else:
                        self._mark_ok(profile.provider)
                        success_attempt = build_record(
                            target=current,
                            credential=cred,
                            record_kind=CallRecordKind.ATTEMPT.value,
                            status=CallStatus.OK.value,
                            error_kind="",
                            failure_stage="",
                            response=resp,
                        )
                        self._emit_audit_record(
                            success_attempt,
                            audit_records,
                            sink=sink,
                            materialized=cred,
                            events=events,
                        )
                        return resp, current, cred, fallback_used, fallback_chain, attempt_no

                    self._mark_fail(profile.provider, failure_kind)
                    excluded.add(profile.signature)
                    fallback_chain.append(
                        f"{profile.provider}/{profile.model}:{self._safe_error_kind(failure_kind)}"
                    )
                    attempt = build_record(
                        target=current,
                        credential=cred,
                        record_kind=CallRecordKind.ATTEMPT.value,
                        status=CallStatus.ERROR.value,
                        error_kind=failure_kind,
                        failure_stage="provider",
                    )
                    self._emit_audit_record(
                        attempt,
                        audit_records,
                        sink=sink,
                        materialized=cred,
                        events=events,
                    )

            # This block is deliberately outside provider/credential exception
            # handlers. No raw exception context can be chained into audit/error
            # reporting from here.
            try:
                nxt, ok = self._refallback(
                    req,
                    excluded,
                    builder_signature,
                    events,
                    invocation_id=invocation_id,
                    from_attempt_no=attempt_no,
                )
            except Exception as exc:  # noqa: BLE001 -- retain only a sanitized type name.
                refallback_kind = type(exc).__name__
            else:
                refallback_kind = ""
            if refallback_kind:
                terminal = build_record(
                    target=current,
                    credential=cred,
                    record_kind=CallRecordKind.TERMINAL.value,
                    status=CallStatus.ERROR.value,
                    error_kind=f"refallback_{refallback_kind}",
                    failure_stage="fallback",
                )
                self._emit_audit_record(
                    terminal,
                    audit_records,
                    sink=sink,
                    materialized=cred,
                    events=events,
                )
                error = GatewayError(
                    f"fallback 路由失败：{self._safe_error_kind(refallback_kind)}",
                    record=terminal,
                    records=audit_records,
                )
                error.events = list(events)  # type: ignore[attr-defined]
                raise error from None
            if not ok or nxt is None:
                terminal_kind = (
                    "all_credentials_unavailable"
                    if failure_category == "credential"
                    else "all_providers_failed"
                )
                terminal = build_record(
                    target=current,
                    credential=cred,
                    record_kind=CallRecordKind.TERMINAL.value,
                    status=CallStatus.ERROR.value,
                    error_kind=terminal_kind,
                    failure_stage=failure_category,
                )
                self._emit_audit_record(
                    terminal,
                    audit_records,
                    sink=sink,
                    materialized=cred,
                    events=events,
                )
                error = GatewayError(
                    f"所有可用 LLM 路由均已失败（{self._safe_error_kind(failure_kind)}）",
                    record=terminal,
                    records=audit_records,
                )
                error.events = list(events)  # type: ignore[attr-defined]
                raise error from None
            fallback_used = True
            current = nxt
            continue

    def _refallback(
        self,
        req: RoleCapabilityRequest,
        excluded: set[tuple[str, str]],
        builder_signature: tuple[str, str] | None,
        events: list[LLMGatewayEvent],
        *,
        invocation_id: str,
        from_attempt_no: int,
    ) -> tuple[RoutingDecision | None, bool]:
        try:
            nxt = self._policy.resolve(
                req,
                unavailable_providers=self._unavailable_providers(),
                exclude_signatures=excluded,
                builder_signature=builder_signature,
            )
        except RoutingError:
            return None, False
        events.append(LLMGatewayEvent(EV_FALLBACK_USED, {
            "to_provider": nxt.profile.provider, "to_model": nxt.profile.model,
            "tier_resolved": nxt.tier_resolved, "degraded": nxt.degraded,
            "invocation_id": invocation_id,
            "from_attempt_no": from_attempt_no,
            "to_attempt_no": from_attempt_no + 1,
        }))
        return nxt, True

    def _build_independence(
        self,
        req: RoleCapabilityRequest,
        *,
        provider: str,
        model: str,
        builder_full: tuple[str, str, str] | None,
    ) -> IndependenceRecord:
        if not req.independence_required:
            return IndependenceRecord(required=False, satisfied=False)
        if builder_full is None:
            # 没有 builder 基准（首调即 verifier）：独立性无从相对建立，诚实标不满足。
            return IndependenceRecord(
                required=True, satisfied=False, distinct_provider=False, distinct_model=False,
                builder_call_id=None,
                reason="",
            )
        # The record's resolved credential-backed identity is authoritative;
        # route profile labels are not execution evidence.
        distinct_provider = provider != builder_full[0]
        distinct_model = model != builder_full[1]
        # 不把同一 GPT/Claude 家族的版本、别名或转售 provider 伪装成双模型独立。
        satisfied = has_independent_model_route(
            builder_provider=builder_full[0],
            builder_model=builder_full[1],
            verifier_provider=provider,
            verifier_model=model,
        )
        return IndependenceRecord(
            required=True,
            satisfied=satisfied,
            distinct_provider=distinct_provider,
            distinct_model=distinct_model,
            builder_call_id=builder_full[2],
            reason="",
        )

    def _detect_replay_state(
        self,
        _request: LLMRequest,
        _resp: LLMResponse | None,
    ) -> tuple[str, str | None]:
        # Reaching this method means the provider gateway itself is producing
        # the outcome. Caller flags and provider-controlled response attributes
        # are not proof that the FixtureStore served or recorded anything.
        return ReplayState.LIVE.value, None

    def _route_event(self, decision: RoutingDecision) -> dict[str, Any]:
        return {
            "provider": decision.profile.provider,
            "model": decision.profile.model,
            "tier_requested": decision.tier_requested,
            "tier_resolved": decision.tier_resolved,
            "degraded": decision.degraded,
            "degrade_reason": decision.degrade_reason,
            "mode": decision.mode,
            "rationale": decision.rationale,
        }


def assert_admissible_to_graph(result: GatewaySealedResult, gateway: LLMGateway) -> None:
    """下游准入唯一门（§7「绕过 Gateway → 拒」的落地）：

    1. 封印校验——证明这条账确由本 gateway 铸出（绕过 gateway 自造的账验不过）。
    2. typed scope/status/provider-evidence 门。
    3. 明文 secret 门（防落账面泄露）。

    种坏门必抓：把一条**未经 gateway 封印**的伪造账拿来准入 → 此门必抛（tests::test_gate_bypass_*）。
    """

    if not gateway.verify(result):
        raise LLMRecordError(
            "LLM 结果未经本 Gateway 封印——绕过 Gateway 的调用对 Research Graph 不可准入（GOAL §7）"
        )
    assert_record_admissible(result.record)
    gateway.assert_record_secret_clean(result.record)


# ============ agent 注入适配器（§7 唯一入口落地：agent.chat → gateway.complete 产封印账）============

class GatewayBackedLLMClient(LLMClient):
    """把 `LLMGateway` 包成 agent 可直接注入的 `LLMClient`（§7：role agent 不直调 provider/读 key）。

    agent 的 `self._llm.chat(...)` → `gateway.complete(...)`：每个 provider attempt 与 terminal
    outcome 都产一条封印账（typed scope/status + prompt/账 secret 门 + durable sink）。
    record 经 `record_sink` 回传调用方（main.py 落 RDP）。本类绝不 log 明文 secret / 原始 prompt。

    deny-by-default：底层 gateway 由 `build_agent_llm_gateway` 装配——无真实 provider 即 `NoLLMConfigured`，
    且 dev_local 绝不进 routing profile → agent 调用永不被静默路由到 mock（GOAL §8 no-silent-mock）。
    """

    provider = "gateway"

    def __init__(
        self,
        gateway: LLMGateway,
        *,
        role: str = "agent",
        difficulty: str = "normal",
        risk: str = "normal",
        session_id: str = "agent",
        owner_user_id: str = "",
        workflow_id: str = "",
        invocation_id_factory: Callable[[], str] | None = None,
        replay_mode: str = "live",
        record_sink: Callable[[LLMCallRecord], None] | None = None,
    ) -> None:
        # deny-by-default 硬门（GOAL §8 no-silent-mock）：拒绝绑定含 dev_local routing profile 的 gateway——
        # 即便上游手搓了一个 dev_local gateway 再 wrap，agent 调用也绝不静默落 mock（防御纵深）。
        if any(p.provider == "dev_local" for p in gateway._policy.profiles):
            raise NoLLMConfigured(
                "GatewayBackedLLMClient 拒绝绑定含 dev_local routing profile 的 gateway——"
                "agent 调用绝不静默落 mock（GOAL §8 no-silent-mock）。"
            )
        self._gateway = gateway
        self._role = role
        self._difficulty = difficulty
        self._risk = risk
        self._session_id = session_id
        self._owner_user_id = str(owner_user_id or "").strip()
        self._workflow_id = str(workflow_id or "").strip()
        self._invocation_id_factory = invocation_id_factory
        self._replay_mode = replay_mode
        self._record_sink = record_sink
        self.last_result: GatewaySealedResult | None = None

    @property
    def last_record(self) -> LLMCallRecord | None:
        return self.last_result.record if self.last_result is not None else None

    def chat(
        self,
        messages: list[LLMMessage],
        *,
        tools: list[dict[str, Any]] | None = None,
        model: str | None = None,  # noqa: ARG002 —— 档位/model 由 gateway 路由决定，不由 caller 钉
        temperature: float = 0.2,
    ) -> LLMResponse:
        if not self._owner_user_id or not self._workflow_id or self._invocation_id_factory is None:
            raise LLMRecordError(
                "GatewayBackedLLMClient requires explicit owner_user_id, workflow_id, "
                "and invocation_id_factory"
            )
        invocation_id = str(self._invocation_id_factory() or "").strip()
        if not invocation_id:
            raise LLMRecordError("invocation_id_factory returned an empty invocation_id")
        request = LLMRequest(
            messages=list(messages),
            capability=RoleCapabilityRequest(role=self._role, difficulty=self._difficulty, risk=self._risk),
            tools=tools,
            temperature=temperature,
            session_id=self._session_id,
            owner_user_id=self._owner_user_id,
            workflow_id=self._workflow_id,
            invocation_id=invocation_id,
            replay_mode=self._replay_mode,
        )
        result = self._gateway.complete(
            request,
            record_sink=self._record_sink,
        )  # 路由+物化+secret门+组账+封印+durable sink 全在此（§7）
        # 落账边界再核一次：被路由到 dev_local mock 的账绝不回给 agent（防 policy 运行期被改写）。
        if result.record.provider == "dev_local":
            raise NoLLMConfigured(
                "agent LLM 调用被路由到 dev_local mock —— deny-by-default 拒绝（GOAL §8 no-silent-mock）"
            )
        self.last_result = result
        return result.response

    def stream_chat(self, messages, *, model=None, temperature=0.2):  # noqa: ARG002
        # 逐 token 过 gateway 较重；先一次性 complete 产账，再按基类语义分块（replay/secret 门已生效）。
        resp = self.chat(messages, model=model, temperature=temperature)
        text = resp.content or ""
        for i in range(0, len(text), 20):
            yield text[i:i + 20]


def build_agent_llm_gateway(
    keystore: Any,
    *,
    mode: RoutingMode | str = RoutingMode.HYBRID_ADAPTIVE,
    strict_degrade: bool = True,
    client_factory: Callable[[MaterializedCredential], Any] | None = None,
    seal_secret: bytes | None = None,
    use_binding_sink: Callable[[LLMGatewayUseBindingRecord], Any] | None = None,
    service_principal_ref: str = "",
    credential_pool_refs: Mapping[str, str] | None = None,
    routing_policy_refs: Mapping[str, str] | None = None,
    default_pin: tuple[str, str] | None = None,
) -> LLMGateway:
    """从 keystore 已配置的【真实】provider 装配 agent LLMGateway（deny-by-default · 复用现有原语不另造）。

    - 只为真有可用 key（custom 为 base_url+model）的 provider 建 routing profile + 凭据池。
    - **dev_local 绝不进 routing profile**：agent 调用永不被静默路由到 mock。
    - 一个真实 provider 都没配 → 抛 `NoLLMConfigured`（GOAL §8：拒绝静默落 DevLocalLLM）。

    `client_factory` 仅供测试注入桩（默认 = 真 provider adapter `_default_client_factory`）。
    """

    from ..agent.llm_providers import KEYSTORE_NAMES, _DEFAULT_MODELS, _keystore_extras
    from ..security import KeystoreError

    pool = LLMCredentialPool(keystore)
    profiles: list[LLMModelProfile] = []
    for provider in ("anthropic", "openai", "qwen", "custom"):
        ks_name = KEYSTORE_NAMES[provider]
        try:
            record = keystore.fetch(ks_name)
        except KeystoreError:
            continue
        extras = _keystore_extras(record.note or "")
        base_url = extras.get("base_url", "")
        model = extras.get("model", "") or _DEFAULT_MODELS.get(provider, "")
        has_key = bool(record.api_secret or record.api_key)
        if provider == "custom":
            if not base_url or not model:
                continue  # 本地/自定义端点至少要 base_url + model
            auth_kind = "oauth_proxy"
        else:
            if not has_key:
                continue
            auth_kind = "api_key"
        pool.register(
            provider,
            SecretRef(keystore_name=ks_name, provider=provider, auth_kind=auth_kind, label=provider),
            base_url=base_url,
            default_model=model,
        )
        profiles.append(
            LLMModelProfile(
                provider=provider,
                model=model,
                capability_tier=infer_capability_tier(model),
                pool_id=provider,
            )
        )
    if not profiles:
        raise NoLLMConfigured(
            "未配置任何可用 LLM provider —— deny-by-default：agent LLMGateway 拒绝构建，"
            "绝不静默落 DevLocalLLM（GOAL §8 no-silent-mock）。请在 Settings 配置 provider + key。"
        )
    policy = ModelRoutingPolicy(profiles, mode=mode)
    runtime_pool_ids = {profile.pool_id for profile in profiles}
    selected_credential_pool_refs = (
        {
            pool_id: str((credential_pool_refs or {}).get(pool_id) or "")
            for pool_id in runtime_pool_ids
        }
        if use_binding_sink is not None
        else credential_pool_refs
    )
    selected_routing_policy_refs = (
        {
            pool_id: str((routing_policy_refs or {}).get(pool_id) or "")
            for pool_id in runtime_pool_ids
        }
        if use_binding_sink is not None
        else routing_policy_refs
    )
    return LLMGateway(
        policy=policy,
        credential_pool=pool,
        client_factory=client_factory,
        strict_degrade=strict_degrade,
        seal_secret=seal_secret,
        use_binding_sink=use_binding_sink,
        service_principal_ref=service_principal_ref,
        credential_pool_refs=selected_credential_pool_refs,
        routing_policy_refs=selected_routing_policy_refs,
        default_pin=default_pin,
    )


def make_gateway_backed_agent_llm(
    keystore: Any,
    *,
    role: str = "agent",
    difficulty: str = "normal",
    risk: str = "normal",
    session_id: str = "agent",
    owner_user_id: str = "",
    workflow_id: str = "",
    invocation_id_factory: Callable[[], str] | None = None,
    replay_mode: str = "live",
    record_sink: Callable[[LLMCallRecord], None] | None = None,
    mode: RoutingMode | str = RoutingMode.HYBRID_ADAPTIVE,
    strict_degrade: bool = True,
    client_factory: Callable[[MaterializedCredential], Any] | None = None,
    seal_secret: bytes | None = None,
    use_binding_sink: Callable[[LLMGatewayUseBindingRecord], Any] | None = None,
    service_principal_ref: str = "",
    credential_pool_refs: Mapping[str, str] | None = None,
    routing_policy_refs: Mapping[str, str] | None = None,
) -> GatewayBackedLLMClient:
    """便捷工厂：装配 agent LLMGateway 并包成可注入 `AgentRuntime` 的 `LLMClient`（每次 chat 产封印账）。

    deny-by-default：keystore 无任何真实 provider → 透传 `build_agent_llm_gateway` 的 `NoLLMConfigured`。
    """

    gateway = build_agent_llm_gateway(
        keystore,
        mode=mode,
        strict_degrade=strict_degrade,
        client_factory=client_factory,
        seal_secret=seal_secret,
        use_binding_sink=use_binding_sink,
        service_principal_ref=service_principal_ref,
        credential_pool_refs=credential_pool_refs,
        routing_policy_refs=routing_policy_refs,
    )
    return GatewayBackedLLMClient(
        gateway,
        role=role,
        difficulty=difficulty,
        risk=risk,
        session_id=session_id,
        owner_user_id=owner_user_id,
        workflow_id=workflow_id,
        invocation_id_factory=invocation_id_factory,
        replay_mode=replay_mode,
        record_sink=record_sink,
    )


__all__ = [
    "DegradedRoutingError",
    "EV_CALL_FINISHED",
    "EV_CALL_STARTED",
    "EV_CREDENTIAL_SELECTED",
    "EV_FALLBACK_USED",
    "EV_ROUTE_SELECTED",
    "GatewayBackedLLMClient",
    "GatewayError",
    "GatewaySealedResult",
    "LLMGateway",
    "LLMGatewayEvent",
    "LLMRequest",
    "ProviderHealth",
    "QuotaStatus",
    "assert_admissible_to_graph",
    "build_agent_llm_gateway",
    "make_gateway_backed_agent_llm",
]
