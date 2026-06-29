"""M14b · 真实 LLM 客户端三档（Anthropic / OpenAI / Qwen）+ 工厂。

设计原则（对齐 GOAL §M14 + §6.5 安全 + §8 no-silent-mock）：
- 所有 provider 走同一份 `LLMClient` 接口（消息往返 + tool calls 同构）
- API key 永远从 `SecureKeystore` 取，绝不入 YAML / 日志
- **deny-by-default**：无可用 provider/key → 抛 `NoLLMConfigured`（明确错误·fail-closed），
  **绝不静默落 `DevLocalLLM`**（GOAL §8：任一生产结果走 silent mock fallback → 拒）。
  开发期要 mock 须**显式**构造 `DevLocalLLM()`，绝不由工厂在缺配置时悄悄替换。
- HTTP 客户端用 `requests`（同步，不引 anthropic/openai SDK 减依赖体积）

provider 选择优先级：
1. caller 显式指定
2. `LLM_PROVIDER` 环境变量
3. keystore 第一个匹配名（`llm_anthropic` / `llm_openai` / `llm_qwen`）
4. 都未配 → 抛 `NoLLMConfigured`（deny-by-default，绝不静默落 DevLocalLLM）
"""

from __future__ import annotations

import json
import logging
import os
from datetime import UTC, datetime
from typing import Any, Literal

import requests

from ..research_os import (
    LLMCredentialPoolRecord,
    LLMGatewayCallRequest,
    LLMProviderRecord,
    ModelRoutingPolicyRecord,
    PersistentOnboardingRegistry,
    SecretRefRecord,
    SecretRefStatus,
    validate_llm_gateway_call,
)
from ..security import KeystoreError, SecureKeystore
from .llm_client import LLMClient, LLMMessage, LLMResponse, NoLLMConfigured


logger = logging.getLogger(__name__)


ProviderName = Literal["anthropic", "openai", "qwen", "custom", "dev_local"]


# ============ Anthropic ============

class AnthropicLLM(LLMClient):
    provider = "anthropic"

    def __init__(
        self,
        api_key: str,
        default_model: str = "claude-sonnet-4-5",
        base_url: str = "https://api.anthropic.com/v1",
        session: requests.Session | None = None,
    ) -> None:
        if not api_key:
            raise NoLLMConfigured("AnthropicLLM 需要 api_key")
        self._key = api_key
        self._model = default_model
        self._base = base_url.rstrip("/")
        self._http = session or requests.Session()

    def chat(
        self,
        messages: list[LLMMessage],
        *,
        tools: list[dict[str, Any]] | None = None,
        model: str | None = None,
        temperature: float = 0.2,
    ) -> LLMResponse:
        # Anthropic Messages API：system 单独，user/assistant 在 messages
        system_parts = [m.content for m in messages if m.role == "system"]
        chat_messages: list[dict[str, Any]] = []
        for m in messages:
            if m.role == "system":
                continue
            if m.role == "tool":
                # Anthropic tool_result 走 user 包装
                chat_messages.append({
                    "role": "user",
                    "content": [{
                        "type": "tool_result",
                        "tool_use_id": m.tool_call_id or "",
                        "content": m.content,
                    }],
                })
                continue
            content: Any = m.content
            if m.tool_calls:
                content = []
                if m.content:
                    content.append({"type": "text", "text": m.content})
                for c in m.tool_calls:
                    args = c.get("arguments")
                    if isinstance(args, str):
                        try:
                            args = json.loads(args)
                        except Exception:  # noqa: BLE001
                            args = {"_raw": args}
                    content.append({
                        "type": "tool_use",
                        "id": c.get("id", ""),
                        "name": c.get("name", ""),
                        "input": args or {},
                    })
            chat_messages.append({"role": m.role, "content": content})

        payload: dict[str, Any] = {
            "model": model or self._model,
            "max_tokens": 4096,
            "temperature": temperature,
            "messages": chat_messages,
        }
        if system_parts:
            payload["system"] = "\n\n".join(system_parts)
        if tools:
            payload["tools"] = [
                {
                    "name": t["name"],
                    "description": t.get("description", ""),
                    "input_schema": t.get("parameters", {"type": "object"}),
                }
                for t in tools
            ]

        r = self._http.post(
            f"{self._base}/messages",
            json=payload,
            headers={
                "x-api-key": self._key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            timeout=120,
        )
        r.raise_for_status()
        data = r.json()
        text_chunks: list[str] = []
        tool_calls: list[dict[str, Any]] = []
        for block in data.get("content", []):
            if block.get("type") == "text":
                text_chunks.append(block.get("text", ""))
            elif block.get("type") == "tool_use":
                tool_calls.append({
                    "id": block.get("id", ""),
                    "name": block.get("name", ""),
                    "arguments": json.dumps(block.get("input", {}), ensure_ascii=False),
                })
        return LLMResponse(content="\n".join(text_chunks), tool_calls=tool_calls, raw=data)


# ============ OpenAI ============

class OpenAILLM(LLMClient):
    provider = "openai"

    def __init__(
        self,
        api_key: str,
        default_model: str = "gpt-4o",
        base_url: str = "https://api.openai.com/v1",
        session: requests.Session | None = None,
    ) -> None:
        if not api_key:
            raise NoLLMConfigured("OpenAILLM 需要 api_key")
        self._key = api_key
        self._model = default_model
        self._base = base_url.rstrip("/")
        self._http = session or requests.Session()

    def chat(
        self,
        messages: list[LLMMessage],
        *,
        tools: list[dict[str, Any]] | None = None,
        model: str | None = None,
        temperature: float = 0.2,
    ) -> LLMResponse:
        oai_messages: list[dict[str, Any]] = []
        for m in messages:
            entry: dict[str, Any] = {"role": m.role, "content": m.content}
            if m.role == "tool":
                entry["tool_call_id"] = m.tool_call_id
                if m.name:
                    entry["name"] = m.name
            if m.tool_calls:
                entry["tool_calls"] = [
                    {
                        "id": c.get("id"),
                        "type": "function",
                        "function": {
                            "name": c.get("name"),
                            "arguments": c.get("arguments") or "{}",
                        },
                    }
                    for c in m.tool_calls
                ]
            oai_messages.append(entry)

        payload: dict[str, Any] = {
            "model": model or self._model,
            "messages": oai_messages,
            "temperature": temperature,
        }
        if tools:
            payload["tools"] = [
                {
                    "type": "function",
                    "function": {
                        "name": t["name"],
                        "description": t.get("description", ""),
                        "parameters": t.get("parameters", {"type": "object"}),
                    },
                }
                for t in tools
            ]

        # 5xx / timeout 自动指数退避重试（上游代理偶发抽风）
        import time as _time
        last_exc: Exception | None = None
        for attempt in range(3):
            try:
                r = self._http.post(
                    f"{self._base}/chat/completions",
                    json=payload,
                    headers={"Authorization": f"Bearer {self._key}", "content-type": "application/json"},
                    timeout=120,
                )
                if 500 <= r.status_code < 600:
                    raise requests.HTTPError(f"{r.status_code} {r.reason}", response=r)
                r.raise_for_status()
                break
            except (requests.Timeout, requests.ConnectionError, requests.HTTPError) as exc:
                last_exc = exc
                if attempt >= 2:
                    raise
                _time.sleep(2 ** attempt)
        else:
            if last_exc:
                raise last_exc
        data = r.json()
        choice = (data.get("choices") or [{}])[0]
        message = choice.get("message", {})
        tool_calls_raw = message.get("tool_calls") or []
        tool_calls: list[dict[str, Any]] = [
            {
                "id": tc.get("id"),
                "name": tc.get("function", {}).get("name"),
                "arguments": tc.get("function", {}).get("arguments", "{}"),
            }
            for tc in tool_calls_raw
        ]
        return LLMResponse(content=message.get("content") or "", tool_calls=tool_calls, raw=data)

    def stream_chat(self, messages, *, model=None, temperature=0.2):
        """v0.9.8 · 真 OpenAI SSE streaming (chat.completions.stream=True)."""
        import json as _json

        oai_messages: list[dict[str, Any]] = []
        for m in messages:
            entry: dict[str, Any] = {"role": m.role, "content": m.content}
            if m.role == "tool":
                entry["tool_call_id"] = m.tool_call_id
                if m.name:
                    entry["name"] = m.name
            oai_messages.append(entry)

        payload = {
            "model": model or self._model,
            "messages": oai_messages,
            "temperature": temperature,
            "stream": True,
        }
        with self._http.post(
            f"{self._base}/chat/completions",
            json=payload,
            headers={"Authorization": f"Bearer {self._key}", "content-type": "application/json"},
            stream=True,
            timeout=120,
        ) as r:
            r.raise_for_status()
            for raw_line in r.iter_lines():
                if not raw_line:
                    continue
                line = raw_line.decode("utf-8", errors="replace").strip()
                if not line.startswith("data: "):
                    continue
                payload_str = line[6:].strip()
                if payload_str == "[DONE]":
                    return
                try:
                    chunk = _json.loads(payload_str)
                except _json.JSONDecodeError:
                    continue
                choices = chunk.get("choices") or []
                if not choices:
                    continue
                delta = choices[0].get("delta", {}) or {}
                token = delta.get("content")
                if token:
                    yield token


# ============ Qwen (DashScope) ============

class QwenLLM(LLMClient):
    """阿里百炼 / DashScope OpenAI 兼容端点。"""

    provider = "qwen"

    def __init__(
        self,
        api_key: str,
        default_model: str = "qwen-max",
        base_url: str = "https://dashscope.aliyuncs.com/compatible-mode/v1",
        session: requests.Session | None = None,
    ) -> None:
        if not api_key:
            raise NoLLMConfigured("QwenLLM 需要 api_key")
        # 复用 OpenAI 客户端（DashScope 提供 OpenAI 兼容协议）
        self._inner = OpenAILLM(api_key=api_key, default_model=default_model, base_url=base_url, session=session)

    def chat(
        self,
        messages: list[LLMMessage],
        *,
        tools: list[dict[str, Any]] | None = None,
        model: str | None = None,
        temperature: float = 0.2,
    ) -> LLMResponse:
        return self._inner.chat(messages, tools=tools, model=model, temperature=temperature)


# ============ Custom / Generic OpenAI-Compatible ============

class OpenAICompatibleLLM(LLMClient):
    """任意 OpenAI 协议端点 —— 本地 ollama / vLLM / 第三方代理 / 私有 LLM 都行。"""

    provider = "custom"

    def __init__(
        self,
        api_key: str,
        base_url: str,
        default_model: str,
        session: requests.Session | None = None,
    ) -> None:
        if not base_url:
            raise NoLLMConfigured("OpenAICompatibleLLM 需要 base_url（任意 OpenAI 兼容端点）")
        if not default_model:
            raise NoLLMConfigured("OpenAICompatibleLLM 需要 model")
        self._inner = OpenAILLM(
            api_key=api_key or "no-key",
            default_model=default_model,
            base_url=base_url,
            session=session,
        )

    def chat(
        self,
        messages: list[LLMMessage],
        *,
        tools: list[dict[str, Any]] | None = None,
        model: str | None = None,
        temperature: float = 0.2,
    ) -> LLMResponse:
        return self._inner.chat(messages, tools=tools, model=model, temperature=temperature)

    def stream_chat(self, messages, *, model=None, temperature=0.2):
        yield from self._inner.stream_chat(messages, model=model, temperature=temperature)


# ============ 工厂 + 优雅 fallback ============

KEYSTORE_NAMES: dict[ProviderName, str] = {
    "anthropic": "llm_anthropic",
    "openai": "llm_openai",
    "qwen": "llm_qwen",
    "custom": "llm_custom",
    "dev_local": "",
}


_DEFAULT_MODELS: dict[str, str] = {
    "anthropic": "claude-sonnet-4-5",
    "openai": "gpt-4o",
    "qwen": "qwen-max",
}

_DEFAULT_BASE_URLS: dict[str, str] = {
    "anthropic": "https://api.anthropic.com/v1",
    "openai": "https://api.openai.com/v1",
    "qwen": "https://dashscope.aliyuncs.com/compatible-mode/v1",
}

_PROVIDER_TYPES: dict[str, str] = {
    "anthropic": "anthropic_api",
    "openai": "openai_api",
    "qwen": "dashscope_openai_compatible",
    "custom": "openai_compatible_custom_endpoint",
}

_PROVIDER_CAPABILITIES: dict[str, tuple[str, ...]] = {
    "anthropic": ("tool_calling", "structured_output", "long_context"),
    "openai": ("tool_calling", "structured_output"),
    "qwen": ("tool_calling", "structured_output"),
    "custom": ("openai_compatible",),
}

_PROVIDER_CONTEXT_WINDOWS: dict[str, int] = {
    "anthropic": 200_000,
    "openai": 128_000,
    "qwen": 128_000,
    "custom": 0,
}


def _env_key(provider: ProviderName) -> str | None:
    env_map = {
        "anthropic": "ANTHROPIC_API_KEY",
        "openai": "OPENAI_API_KEY",
        "qwen": "DASHSCOPE_API_KEY",
    }
    var = env_map.get(provider)
    return os.environ.get(var) if var else None


def _keystore_extras(record_note: str) -> dict[str, str]:
    """secrets_loader 把 base_url + model 塞进 keystore.note 的 json string。"""

    if not record_note:
        return {}
    try:
        data = json.loads(record_note)
        if isinstance(data, dict):
            return {k: str(v) for k, v in data.items() if v}
    except Exception:  # noqa: BLE001
        pass
    return {}


def llm_secret_ref(provider: ProviderName) -> str:
    if provider not in ("anthropic", "openai", "qwen", "custom"):
        raise NoLLMConfigured(f"provider {provider!r} cannot use Settings SecretRef")
    return f"secretref:llm:{provider}"


def llm_credential_pool_ref(provider: ProviderName) -> str:
    if provider not in ("anthropic", "openai", "qwen", "custom"):
        raise NoLLMConfigured(f"provider {provider!r} cannot use Settings credential pool")
    return f"pool:llm:{provider}:default"


def llm_routing_policy_ref(provider: ProviderName) -> str:
    if provider not in ("anthropic", "openai", "qwen", "custom"):
        raise NoLLMConfigured(f"provider {provider!r} cannot use Settings routing policy")
    return f"routing:llm:{provider}:default"


def _effective_model(provider: ProviderName, model: str | None) -> str:
    if model:
        return model
    if provider == "custom":
        return ""
    return _DEFAULT_MODELS.get(provider, "")


def _record_if_missing(callable_obj, lookup, key: str, record: Any, *, replace: bool) -> Any:
    if not replace:
        try:
            return lookup(key)
        except KeyError:
            pass
    return callable_obj(record)


def ensure_settings_managed_llm_provider(
    *,
    registry: PersistentOnboardingRegistry,
    provider: ProviderName,
    base_url: str | None = None,
    model: str | None = None,
    owner: str = "settings",
    created_at: str | None = None,
    replace_secret: bool = False,
) -> dict[str, str]:
    """Create the Settings metadata required before a role agent can use an LLM provider.

    The actual secret value stays in SecureKeystore under ``llm_<provider>``.
    This function only records SecretRef / Provider / CredentialPool /
    ModelRoutingPolicy metadata and never receives plaintext credentials.
    """

    if provider not in ("anthropic", "openai", "qwen", "custom"):
        raise NoLLMConfigured(f"unknown settings-managed provider: {provider}")
    selected_model = _effective_model(provider, model)
    if provider == "custom" and not selected_model:
        raise NoLLMConfigured("custom provider requires model before Settings route can be recorded")
    now = created_at or datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    secret_ref = llm_secret_ref(provider)
    pool_ref = llm_credential_pool_ref(provider)
    policy_ref = llm_routing_policy_ref(provider)
    effective_base_url = base_url or _DEFAULT_BASE_URLS.get(provider, "")
    secret = SecretRefRecord(
        secret_ref=secret_ref,
        scope=f"llm:{provider}:call",
        status=SecretRefStatus.ACTIVE,
        created_at=now,
        access_audit=(f"keystore:{KEYSTORE_NAMES[provider]}",),
        connector_scope_review=f"provider:{provider}",
    )
    _record_if_missing(registry.record_secret_ref, registry.secret_ref, secret_ref, secret, replace=replace_secret)
    provider_record = LLMProviderRecord(
        provider_id=provider,
        provider_type=_PROVIDER_TYPES[provider],
        auth_methods=("api_key",) if provider != "custom" else ("api_key", "local_endpoint_without_external_credential"),
        base_url=effective_base_url,
        model_profiles=(selected_model,),
        capability_tags=_PROVIDER_CAPABILITIES[provider],
        context_window=_PROVIDER_CONTEXT_WINDOWS[provider],
        tool_calling_support=provider != "custom",
        structured_output_support=provider != "custom",
        cost_model_ref=f"cost:{provider}:settings",
        rate_limits="provider-managed",
        data_retention_policy="settings-managed",
        region_residency="provider-managed",
        allowed_roles=("coordinator", "researcher", "verifier", "role_agent", "agent"),
        allowed_desks=("agent", "research", "strategy", "factor", "model", "paper", "settings"),
        health_status="configured",
        quota_status="unknown",
        auth_refs=(secret_ref,),
    )
    _record_if_missing(registry.record_llm_provider, registry.llm_provider, provider, provider_record, replace=True)
    pool_record = LLMCredentialPoolRecord(
        pool_id=pool_ref,
        provider_id=provider,
        auth_refs=(secret_ref,),
        priority=(secret_ref,),
        rotation_policy="settings-managed-rotation",
        fallback_policy="no-cross-provider-without-routing-policy",
        rate_limit_policy="respect-provider",
        quota_policy="stop-at-budget",
        owner=owner,
    )
    _record_if_missing(registry.record_credential_pool, registry.credential_pool, pool_ref, pool_record, replace=True)
    policy_record = ModelRoutingPolicyRecord(
        routing_policy_id=policy_ref,
        role_agent="role_agent",
        desk="all",
        task_type="llm_chat",
        required_capabilities=(),
        allowed_providers=(provider,),
        allowed_models=(selected_model,),
        credential_pool_ref=pool_ref,
        fallback_order=(selected_model,),
        cost_limit="settings-managed",
        latency_limit="settings-managed",
        data_retention_requirement="settings-managed",
        independence_requirement="record-if-verifier",
        replay_requirement="decision-level",
    )
    _record_if_missing(registry.record_routing_policy, registry.routing_policy, policy_ref, policy_record, replace=True)
    return {
        "secret_ref": secret_ref,
        "credential_pool_ref": pool_ref,
        "routing_policy_ref": policy_ref,
        "model": selected_model,
        "base_url": effective_base_url,
    }


def _registered_gateway_records(
    *,
    registry: PersistentOnboardingRegistry,
    provider: ProviderName,
) -> tuple[SecretRefRecord, LLMProviderRecord, LLMCredentialPoolRecord, ModelRoutingPolicyRecord]:
    secret_ref = llm_secret_ref(provider)
    pool_ref = llm_credential_pool_ref(provider)
    policy_ref = llm_routing_policy_ref(provider)
    return (
        registry.secret_ref(secret_ref),
        registry.llm_provider(provider),
        registry.credential_pool(pool_ref),
        registry.routing_policy(policy_ref),
    )


def _gateway_rejection(decision) -> str:
    return ", ".join(v.code for v in decision.violations) or "settings_route_rejected"


def make_llm_client(
    provider: ProviderName | None = None,
    *,
    keystore: SecureKeystore | None = None,
    api_key: str | None = None,
    base_url: str | None = None,
    model: str | None = None,
    allow_env: bool = True,
) -> LLMClient:
    """按优先级解析 provider + api_key + base_url + model。

    deny-by-default（GOAL §8 no-silent-mock）：解析不出任何可用真实 provider →
    抛 `NoLLMConfigured`（明确错误），**绝不**静默返回 `DevLocalLLM`。要 mock 走显式 `DevLocalLLM()`。
    """

    explicit = provider or (os.environ.get("LLM_PROVIDER", "").lower() or None)
    candidates: list[ProviderName] = (
        [explicit]  # type: ignore[list-item]
        if explicit in ("anthropic", "openai", "qwen", "custom")
        else ["anthropic", "openai", "qwen", "custom"]
    )
    for cand in candidates:
        key = api_key or (_env_key(cand) if allow_env else None)
        extras: dict[str, str] = {}
        if keystore is not None:
            try:
                record = keystore.fetch(KEYSTORE_NAMES[cand])
                extras = _keystore_extras(record.note or "")
                if not key:
                    key = record.api_secret or record.api_key
            except KeystoreError:
                pass
        eff_base_url = base_url or extras.get("base_url") or os.environ.get(f"LLM_{cand.upper()}_BASE_URL", "")
        eff_model = model or extras.get("model") or os.environ.get(f"LLM_{cand.upper()}_MODEL", "")
        if cand == "custom":
            if not eff_base_url or not eff_model:
                continue
            try:
                return OpenAICompatibleLLM(api_key=key or "no-key", base_url=eff_base_url, default_model=eff_model)
            except Exception as exc:  # noqa: BLE001
                logger.warning("LLM custom 初始化失败：%s", exc)
                continue
        if not key:
            continue
        try:
            if cand == "anthropic":
                return AnthropicLLM(
                    api_key=key,
                    default_model=eff_model or _DEFAULT_MODELS["anthropic"],
                    base_url=eff_base_url or "https://api.anthropic.com/v1",
                )
            if cand == "openai":
                return OpenAILLM(
                    api_key=key,
                    default_model=eff_model or _DEFAULT_MODELS["openai"],
                    base_url=eff_base_url or "https://api.openai.com/v1",
                )
            if cand == "qwen":
                return QwenLLM(
                    api_key=key,
                    default_model=eff_model or _DEFAULT_MODELS["qwen"],
                    base_url=eff_base_url or "https://dashscope.aliyuncs.com/compatible-mode/v1",
                )
        except Exception as exc:  # noqa: BLE001
            logger.warning("LLM provider %s 初始化失败：%s", cand, exc)
            continue
    # deny-by-default（GOAL §8）：没有任何可用真实 provider → 明确报错，绝不静默落 DevLocalLLM。
    raise NoLLMConfigured(
        "无可用 LLM provider：env/keystore 未配置任何 anthropic/openai/qwen/custom 凭据。"
        "deny-by-default —— 拒绝静默落 DevLocalLLM（GOAL §8 no-silent-mock）。"
        "开发期请显式构造 DevLocalLLM()，生产请在 Settings 配置 provider + key。"
    )


def make_settings_managed_llm_client(
    provider: ProviderName | None = None,
    *,
    keystore: SecureKeystore,
    registry: PersistentOnboardingRegistry,
    role_agent: str = "role_agent",
    desk: str = "agent",
    task_type: str = "llm_chat",
    model: str | None = None,
    replay_record_ref: str | None = None,
) -> LLMClient:
    """Resolve a role-agent LLM client through Settings metadata and LLM Gateway.

    Env keys are intentionally ignored here. A role agent can use real provider
    credentials only after the key exists in SecureKeystore and the matching
    SecretRef / provider / pool / routing policy records validate.
    """

    explicit = provider or (os.environ.get("LLM_PROVIDER", "").lower() or None)
    candidates: list[ProviderName] = (
        [explicit]  # type: ignore[list-item]
        if explicit in ("anthropic", "openai", "qwen", "custom")
        else ["anthropic", "openai", "qwen", "custom"]
    )
    rejection: str | None = None
    for cand in candidates:
        try:
            record = keystore.fetch(KEYSTORE_NAMES[cand])
        except KeystoreError:
            continue
        extras = _keystore_extras(record.note or "")
        selected_model = model or extras.get("model") or _DEFAULT_MODELS.get(cand, "")
        if cand == "custom" and not selected_model:
            rejection = "custom_missing_model"
            continue
        try:
            ensure_settings_managed_llm_provider(
                registry=registry,
                provider=cand,
                base_url=extras.get("base_url"),
                model=selected_model,
                owner="runtime-bootstrap",
                replace_secret=False,
            )
            secret, provider_record, pool, policy = _registered_gateway_records(registry=registry, provider=cand)
        except (KeyError, ValueError, NoLLMConfigured) as exc:
            rejection = str(exc)
            if explicit:
                raise NoLLMConfigured(f"LLM Gateway settings route missing for {cand}: {exc}") from exc
            continue
        if selected_model and selected_model not in policy.allowed_models:
            selected_model = policy.allowed_models[0] if policy.allowed_models else selected_model
        request = LLMGatewayCallRequest(
            role_agent=role_agent,
            desk=desk,
            task_type=task_type,
            provider_id=provider_record.provider_id,
            model_id=selected_model,
            routing_policy_ref=policy.routing_policy_id,
            credential_pool_ref=pool.pool_id,
            auth_ref=secret.secret_ref,
            via_gateway=True,
            replay_record_ref=replay_record_ref,
        )
        decision = validate_llm_gateway_call(
            request,
            policy=policy,
            credential_pool=pool,
            secrets={secret.secret_ref: secret},
        )
        if not decision.accepted:
            rejection = _gateway_rejection(decision)
            if explicit:
                raise NoLLMConfigured(f"LLM Gateway route rejected for {cand}: {rejection}")
            continue
        return make_llm_client(
            provider=cand,
            keystore=keystore,
            base_url=extras.get("base_url"),
            model=selected_model,
            allow_env=False,
        )
    if explicit:
        detail = rejection or "provider not configured in Settings/Secrets"
        raise NoLLMConfigured(f"LLM Gateway route rejected for {explicit}: {detail}")
    # deny-by-default（GOAL §8）：未显式指定且无任何就绪的 Settings-managed provider →
    # 明确报错，绝不静默落 DevLocalLLM（旧行为是 silent mock fallback，§8 拒）。
    detail = rejection or "no Settings-managed LLM provider configured in Settings/Secrets"
    raise NoLLMConfigured(
        f"LLM Gateway route unavailable: {detail}. deny-by-default —— 拒绝静默落 DevLocalLLM"
        "（GOAL §8 no-silent-mock）。请在 Settings 配置 provider 并完成 SecretRef/路由登记。"
    )


def list_llm_status(
    keystore: SecureKeystore | None,
    onboarding_registry: PersistentOnboardingRegistry | None = None,
) -> list[dict[str, Any]]:
    """供 UI 系统设置页用：列出每个 provider 当前是否就绪（不回显 key）。"""

    out: list[dict[str, Any]] = []
    for cand in ("anthropic", "openai", "qwen", "custom"):
        info: dict[str, Any] = {
            "provider": cand,
            "configured": False,
            "base_url": "",
            "model": "",
            "default_model": _DEFAULT_MODELS.get(cand, ""),
            "has_env_key": bool(_env_key(cand)),  # type: ignore[arg-type]
        }
        if keystore is not None:
            try:
                record = keystore.fetch(KEYSTORE_NAMES[cand])  # type: ignore[index]
                extras = _keystore_extras(record.note or "")
                info["configured"] = bool(record.api_key)
                info["base_url"] = extras.get("base_url", "")
                info["model"] = extras.get("model", "")
            except KeystoreError:
                pass
        if onboarding_registry is not None:
            secret_ref = llm_secret_ref(cand)  # type: ignore[arg-type]
            pool_ref = llm_credential_pool_ref(cand)  # type: ignore[arg-type]
            policy_ref = llm_routing_policy_ref(cand)  # type: ignore[arg-type]
            info["settings_managed"] = False
            info["secret_ref"] = secret_ref
            info["credential_pool_ref"] = pool_ref
            info["routing_policy_ref"] = policy_ref
            try:
                secret = onboarding_registry.secret_ref(secret_ref)
                onboarding_registry.llm_provider(cand)
                onboarding_registry.credential_pool(pool_ref)
                onboarding_registry.routing_policy(policy_ref)
                info["settings_managed"] = True
                info["auth_status"] = secret.status.value if hasattr(secret.status, "value") else str(secret.status)
            except KeyError:
                info["auth_status"] = "missing"
        out.append(info)
    return out


__all__ = [
    "AnthropicLLM",
    "KEYSTORE_NAMES",
    "OpenAICompatibleLLM",
    "OpenAILLM",
    "ProviderName",
    "QwenLLM",
    "ensure_settings_managed_llm_provider",
    "list_llm_status",
    "llm_credential_pool_ref",
    "llm_routing_policy_ref",
    "llm_secret_ref",
    "make_llm_client",
    "make_settings_managed_llm_client",
]
