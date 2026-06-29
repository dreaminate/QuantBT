"""LLM Gateway · 所有 LLM 调用的【唯一入口】（GOAL §7 Orchestrator→LLM Gateway→role dispatch）。

唯一入口规则（§7 / §1）：
- role agent **绝不**直接调 provider SDK / 读 API key——只交「能力需求 + 上下文」，拿回
  `(LLMResponse, LLMCallRecord)`。明文凭据只在 gateway 内物化、调用后即丢、绝不落账/日志。
- 每次调用按 ModelRoutingPolicy（混合自适应）选 provider/model/credential_pool，落 LLMCallRecord
  （provider/model/auth_ref/replay_state + 路由档 + 独立性 + 健康/配额/fallback），可审计 · 进 RDP。
- gateway 给每条账盖封印；下游 `assert_admissible_to_graph` 只认封印过的账——**绕过 Gateway 的
  LLM 结果对 Research Graph 不可准入**（§7「AgentLLMCall 绕过 LLM Gateway → 拒」的可落地形态）。

本卡边界（诚实残余）：只建 Gateway 核 + 路由 + 凭据池 + 调用账 + 健康/fallback。
Agent Orchestrator 全栈 + 12 role + 23 事件**投影**到 user 工作流 = 另卡；本模块只把 LLM 相关事件
（LLMRouteSelected / CredentialPoolSelected / LLMCallStarted / LLMCallFinished / ProviderFallbackUsed）
作为**数据**挂到结果上，供 Orchestrator 卡去投影。

**wrap 现有 agent/llm_client.py + llm_providers.py（不重建）**：默认 client 工厂走 `make_llm_client`，
现有 provider adapter 成 gateway 后端，record/replay 处境从既有 RecordingLLMClient 的回传里如实读。
"""

from __future__ import annotations

import logging
import secrets
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from ..agent.llm_client import LLMClient, LLMMessage, LLMResponse, NoLLMConfigured
from .call_record import (
    CallStatus,
    IndependenceRecord,
    LLMCallRecord,
    LLMRecordError,
    ReplayState,
    SecretLeakError,
    assert_no_plaintext_secret,
    assert_record_admissible,
    make_call_id,
    scan_messages_for_secret,
    seal_record,
    verify_record_seal,
)
from .credential_pool import LLMCredentialPool, MaterializedCredential, SecretRef
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
    replay_mode: str = "live"        # live / record / replay / passthrough（如实记录处境，不在此造 store）


@dataclass
class GatewaySealedResult:
    response: LLMResponse
    record: LLMCallRecord
    events: list[LLMGatewayEvent] = field(default_factory=list)


# ============ 异常 ============

class GatewayError(RuntimeError):
    def __init__(self, message: str, *, record: LLMCallRecord | None = None) -> None:
        super().__init__(message)
        self.record = record


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
    """去掉 url userinfo（user:pass@host）——base_url 一般非密，但万一夹凭据也不外泄。"""

    if not url or "@" not in url:
        return url or ""
    head, _, tail = url.partition("//")
    if "@" in tail:
        tail = tail.split("@", 1)[1]
    return f"{head}//{tail}" if head else url


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _is_verifier(role: str) -> bool:
    r = (role or "").lower()
    return "verifier" in r or "critic" in r


def _extract_usage(resp: LLMResponse) -> dict[str, Any]:
    raw = getattr(resp, "raw", None) or {}
    usage = raw.get("usage") if isinstance(raw, dict) else None
    return dict(usage) if isinstance(usage, dict) else {}


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
    ) -> None:
        self._policy = policy
        self._pool = credential_pool
        self._cap = credential_pool.issue_capability()  # 唯一物化令牌，握在 gateway 内
        self._client_factory = client_factory or _default_client_factory
        self._strict_degrade = strict_degrade
        self._scan_prompt = scan_prompt_secrets
        self._seal_secret = seal_secret or secrets.token_bytes(32)
        self._health: dict[str, ProviderHealth] = {}
        self._quota: dict[str, QuotaStatus] = {}
        self._builder_sig: dict[str, tuple[str, str, str]] = {}  # session -> (provider, model, call_id)

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

    def complete(self, request: LLMRequest) -> GatewaySealedResult:
        events: list[LLMGatewayEvent] = []
        req = request.capability
        started = _now_iso()
        t0 = time.perf_counter()

        # 0) prompt secret guard —— 真打前先扫：在册明文 secret（含实盘 key）绝不随 prompt 出门。
        if self._scan_prompt:
            self._guard_prompt(request)

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
            raise GatewayError(f"路由失败：{exc}") from exc
        events.append(LLMGatewayEvent(EV_ROUTE_SELECTED, self._route_event(decision)))
        self._enforce_strict_degrade(decision, req)

        # 2) 调用（带健康/配额 fallback）。
        resp, decision, cred, fallback_used, fallback_chain = self._invoke_with_fallback(
            request, decision, events, builder_signature,
        )

        # 3) 组账。
        finished = _now_iso()
        latency_ms = round((time.perf_counter() - t0) * 1000.0, 3)
        record = self._build_record(
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
        )
        events.append(LLMGatewayEvent(EV_CALL_FINISHED, {
            "call_id": record.call_id, "provider": record.provider, "model": record.model,
            "status": record.status, "replay_state": record.replay_state, "latency_ms": latency_ms,
        }))

        # 4) 安全门（落账前最后一道）：明文 secret 绝不进账。
        self.assert_record_secret_clean(record, materialized=cred)

        # 5) 必填门 + 盖封印。
        assert_record_admissible(record)
        record.seal = seal_record(record, self._seal_secret)

        # 6) 独立性簿记：builder 调用更新 session 签名（verifier 不更新）。
        if not _is_verifier(req.role):
            self._builder_sig[request.session_id] = (record.provider, record.model, record.call_id)

        # cred（含明文）随函数返回出作用域被回收；绝不外泄、绝不日志。
        return GatewaySealedResult(response=resp, record=record, events=events)

    # —— 下游准入门（bypass gate）——

    def verify(self, result: GatewaySealedResult) -> bool:
        """这条账是不是本 gateway 实例亲手封印的。"""

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
    ) -> tuple[LLMResponse, RoutingDecision, MaterializedCredential, bool, list[str]]:
        req = request.capability
        excluded: set[tuple[str, str]] = set()
        fallback_chain: list[str] = []
        fallback_used = False
        current = decision

        while True:
            profile = current.profile
            cred = self._pool.materialize(profile.pool_id, capability=self._cap)
            events.append(LLMGatewayEvent(EV_CREDENTIAL_SELECTED, {
                "pool_id": profile.pool_id, "provider": cred.provider,
                "auth_kind": cred.auth_kind, "auth_ref": cred.auth_ref,  # 引用串，非明文
            }))

            # 凭据可用性：api_key 档却无 key → 视作 provider 不可用，触发 fallback（绝不静默落到 DevLocalLLM）。
            if not cred.has_usable_key:
                self._mark_fail(profile.provider, "no_usable_credential")
                excluded.add(profile.signature)
                fallback_chain.append(f"{profile.provider}/{profile.model}:no_key")
                nxt, ok = self._refallback(req, excluded, builder_signature, events)
                fallback_used = True
                if not ok or nxt is None:
                    raise GatewayError(
                        f"无任何带可用凭据的 provider（chain={fallback_chain}）",
                    )
                current = nxt
                self._enforce_strict_degrade(current, req)
                continue

            events.append(LLMGatewayEvent(EV_CALL_STARTED, {
                "provider": cred.provider, "model": profile.model, "tier": profile.capability_tier,
            }))
            client = self._client_factory(cred)
            try:
                resp = client.chat(
                    request.messages,
                    tools=request.tools,
                    model=profile.model or cred.model or None,
                    temperature=request.temperature,
                )
            except Exception as exc:  # noqa: BLE001  —— 唯一外部操作 = provider 调用；失败即 fallback。
                kind = type(exc).__name__
                self._mark_fail(profile.provider, kind)
                excluded.add(profile.signature)
                fallback_chain.append(f"{profile.provider}/{profile.model}:{kind}")
                nxt, ok = self._refallback(req, excluded, builder_signature, events)
                fallback_used = True
                if not ok or nxt is None:
                    raise GatewayError(f"全部 provider 调用失败（chain={fallback_chain}）") from exc
                current = nxt
                self._enforce_strict_degrade(current, req)
                continue

            self._mark_ok(profile.provider)
            return resp, current, cred, fallback_used, fallback_chain

    def _refallback(
        self,
        req: RoleCapabilityRequest,
        excluded: set[tuple[str, str]],
        builder_signature: tuple[str, str] | None,
        events: list[LLMGatewayEvent],
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
        }))
        return nxt, True

    def _build_record(
        self,
        *,
        request: LLMRequest,
        decision: RoutingDecision,
        cred: MaterializedCredential,
        resp: LLMResponse,
        started: str,
        finished: str,
        latency_ms: float,
        fallback_used: bool,
        fallback_chain: list[str],
        builder_full: tuple[str, str, str] | None,
    ) -> LLMCallRecord:
        from ..lineage.ids import content_hash

        req = request.capability
        profile = decision.profile
        provider = profile.provider
        model = profile.model or cred.model or "unknown"
        prompt_digest = content_hash(_messages_jsonable(request.messages))
        replay_state, fixture_key = self._detect_replay_state(request, resp)
        seq = len(self._builder_sig)  # 单调够用：内容寻址 call_id 仅需在 session 内可分辨。
        call_id = make_call_id(
            prompt_digest=prompt_digest, provider=provider, model=model,
            role=req.role, session_id=request.session_id, seq=seq,
        )
        independence = self._build_independence(req, decision, builder_full)
        health = self.health(provider)
        quota = self.quota(provider)
        return LLMCallRecord(
            provider=provider,
            model=model,
            auth_ref=cred.auth_ref,            # SecretRef 引用串，绝非明文
            replay_state=replay_state,
            role=req.role,
            task_difficulty=req.difficulty,
            risk_level=req.risk,
            tier_requested=decision.tier_requested,
            tier_resolved=decision.tier_resolved,
            degraded=decision.degraded,
            degrade_reason=decision.degrade_reason,
            independence=independence,
            provider_health=health.state,
            quota_state="exhausted" if quota.exhausted else "ok",
            fallback_used=fallback_used,
            fallback_chain=list(fallback_chain),
            call_id=call_id,
            session_id=request.session_id,
            prompt_digest=prompt_digest,
            base_url_redacted=_redact_url(cred.base_url),
            fixture_key=fixture_key,
            started_at=started,
            finished_at=finished,
            latency_ms=latency_ms,
            usage=_extract_usage(resp),
            status=CallStatus.OK.value,
            error_kind="",
            repro_level=str(getattr(resp, "repro_level", "decision") or "decision"),
        )

    def _build_independence(
        self,
        req: RoleCapabilityRequest,
        decision: RoutingDecision,
        builder_full: tuple[str, str, str] | None,
    ) -> IndependenceRecord:
        if not req.independence_required:
            return IndependenceRecord(required=False, satisfied=False)
        if builder_full is None:
            # 没有 builder 基准（首调即 verifier）：独立性无从相对建立，诚实标不满足。
            return IndependenceRecord(
                required=True, satisfied=False, distinct_provider=False, distinct_model=False,
                builder_call_id=None,
                reason="无 builder 基准调用，独立性无从相对建立——标独立性不足（§7）",
            )
        distinct_provider = decision.profile.provider != builder_full[0]
        distinct_model = decision.profile.model != builder_full[1]
        # satisfied 当且仅当真换了 provider 或 model（绝不在同源时假报独立）。
        satisfied = bool(distinct_provider or distinct_model)
        reason = (
            "已相对 builder 换 provider/model，独立性成立" if satisfied
            else "仅一个 provider/model 可用，无法相对 builder 独立——标独立性不足（§7）"
        )
        return IndependenceRecord(
            required=True,
            satisfied=satisfied,
            distinct_provider=distinct_provider,
            distinct_model=distinct_model,
            builder_call_id=builder_full[2],
            reason=reason,
        )

    def _detect_replay_state(self, request: LLMRequest, resp: LLMResponse) -> tuple[str, str | None]:
        fixture_key = getattr(resp, "fixture_key", None)
        mode = (request.replay_mode or "live").lower()
        if mode == "replay":
            return ReplayState.REPLAYED.value, fixture_key
        if mode == "record":
            return ReplayState.RECORDED.value, fixture_key
        if mode == "passthrough":
            return ReplayState.PASSTHROUGH.value, fixture_key
        return ReplayState.LIVE.value, fixture_key

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
    2. 必填四要素门。
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

    agent 的 `self._llm.chat(...)` → `gateway.complete(...)`：每次产一条【封印过的】LLMCallRecord
    （provider/model/auth_ref/replay_state 必填齐 + prompt/账 secret 门过 + 下游可 `assert_admissible_to_graph`）。
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
        request = LLMRequest(
            messages=list(messages),
            capability=RoleCapabilityRequest(role=self._role, difficulty=self._difficulty, risk=self._risk),
            tools=tools,
            temperature=temperature,
            session_id=self._session_id,
            replay_mode=self._replay_mode,
        )
        result = self._gateway.complete(request)  # 路由+物化+secret门+组账+封印 全在此（§7）
        # 落账边界再核一次：被路由到 dev_local mock 的账绝不回给 agent（防 policy 运行期被改写）。
        if result.record.provider == "dev_local":
            raise NoLLMConfigured(
                "agent LLM 调用被路由到 dev_local mock —— deny-by-default 拒绝（GOAL §8 no-silent-mock）"
            )
        self.last_result = result
        if self._record_sink is not None:
            self._record_sink(result.record)
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
    return LLMGateway(
        policy=policy,
        credential_pool=pool,
        client_factory=client_factory,
        strict_degrade=strict_degrade,
    )


def make_gateway_backed_agent_llm(
    keystore: Any,
    *,
    role: str = "agent",
    difficulty: str = "normal",
    risk: str = "normal",
    session_id: str = "agent",
    replay_mode: str = "live",
    record_sink: Callable[[LLMCallRecord], None] | None = None,
    mode: RoutingMode | str = RoutingMode.HYBRID_ADAPTIVE,
    strict_degrade: bool = True,
    client_factory: Callable[[MaterializedCredential], Any] | None = None,
) -> GatewayBackedLLMClient:
    """便捷工厂：装配 agent LLMGateway 并包成可注入 `AgentRuntime` 的 `LLMClient`（每次 chat 产封印账）。

    deny-by-default：keystore 无任何真实 provider → 透传 `build_agent_llm_gateway` 的 `NoLLMConfigured`。
    """

    gateway = build_agent_llm_gateway(
        keystore, mode=mode, strict_degrade=strict_degrade, client_factory=client_factory,
    )
    return GatewayBackedLLMClient(
        gateway,
        role=role,
        difficulty=difficulty,
        risk=risk,
        session_id=session_id,
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
