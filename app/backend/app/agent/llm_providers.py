"""M14b · 真实 LLM 客户端三档（Anthropic / OpenAI / Qwen）+ 工厂。

设计原则（对齐 GOAL §M14 + §6.5 安全）：
- 所有 provider 走同一份 `LLMClient` 接口（消息往返 + tool calls 同构）
- API key 永远从 `SecureKeystore` 取，绝不入 YAML / 日志
- 无可用 key 时优雅 fallback 到 `DevLocalLLM`，让 Agent 永远能跑
- HTTP 客户端用 `requests`（同步，不引 anthropic/openai SDK 减依赖体积）

provider 选择优先级：
1. caller 显式指定
2. `LLM_PROVIDER` 环境变量
3. keystore 第一个匹配名（`llm_anthropic` / `llm_openai` / `llm_qwen`）
4. fallback 到 DevLocalLLM
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any, Literal

import requests

from ..security import KeystoreError, SecureKeystore
from .llm_client import DevLocalLLM, LLMClient, LLMMessage, LLMResponse, NoLLMConfigured


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
    """任意 OpenAI 协议端点 —— 本地 ollama / vLLM / 第三方代理 / 私有 LLM 都行。

    用户在 secrets.yaml `llm.custom` 段填 base_url + model + api_key (本地服务可填随便)，
    或在 UI 工坊→系统设置直接填表单。
    """

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


def make_llm_client(
    provider: ProviderName | None = None,
    *,
    keystore: SecureKeystore | None = None,
    api_key: str | None = None,
    base_url: str | None = None,
    model: str | None = None,
) -> LLMClient:
    """按优先级解析 provider + api_key + base_url + model；失败 fallback DevLocalLLM。"""

    explicit = provider or (os.environ.get("LLM_PROVIDER", "").lower() or None)
    candidates: list[ProviderName] = (
        [explicit]  # type: ignore[list-item]
        if explicit in ("anthropic", "openai", "qwen", "custom")
        else ["anthropic", "openai", "qwen", "custom"]
    )
    for cand in candidates:
        key = api_key or _env_key(cand)
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
    logger.info("无可用真实 LLM provider，回退到 DevLocalLLM")
    return DevLocalLLM()


def list_llm_status(keystore: SecureKeystore | None) -> list[dict[str, Any]]:
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
        out.append(info)
    return out


__all__ = [
    "AnthropicLLM",
    "KEYSTORE_NAMES",
    "OpenAICompatibleLLM",
    "OpenAILLM",
    "ProviderName",
    "QwenLLM",
    "list_llm_status",
    "make_llm_client",
]
