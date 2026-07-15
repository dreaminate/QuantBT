"""LLM 模型目录——唯一「有哪些可选模型」清单源（S1，跨厂商切模型特性）。

逐 provider 枚举可选模型：
- api-key 厂商(anthropic/openai/qwen/custom)：live 拉 `{base}/models`（base 已含 /v1，只补 `/models`）。
- 订阅 CLI 厂商(anthropic/openai)：CLI 无干净列模型命令 → `CURATED_MODELS` 兜底（source=curated）。

不变量（对齐 findings/dreaminate/model-switch-crossvendor-design-20260715.md）：
- **auth 门控**：未 auth 的厂商不发 live 请求、其模型 `selectable=false`。
- **live ≠ chat-capable**：厂商 /models 会返回非聊天模型（embedding/tts/…）；展示但 `selectable=false`。
- **订阅 supports_tools=false**：订阅 adapter 拒 tools（K3），订阅模型只用于无工具通用对话。
- **凭据零触碰**：api_key 只即时用于请求 header，**绝不返回/缓存/日志**；缓存只存模型清单，key 由端点层即时取。
- **加固 live 拉取**：禁 redirect（防 SSRF/凭据外泄到重定向目标）、限响应体、短 timeout。

本模块是纯函数核（parse/assemble 可零网络测）+ 可注入 `requests.Session` 的 live 拉取 + TTL 缓存。
"""

from __future__ import annotations

import json
import threading
import time
from dataclasses import asdict, dataclass, field
from hashlib import sha256
from typing import Any, Callable, Optional
from urllib.parse import urlsplit

import requests

# provider → 精选模型 id（订阅路径兜底 / live 失败兜底）。订阅 CLI 无干净列模型命令时用这个。
CURATED_MODELS: dict[str, tuple[str, ...]] = {
    "anthropic": ("claude-opus-4-8", "claude-sonnet-4-5", "claude-haiku-4-5"),
    "openai": ("gpt-5.6-sol", "gpt-5", "o1"),
    "qwen": ("qwen-max", "qwen-plus"),
}

# 各 provider 已知「聊天可用」模型 id 前缀（live /models 会混入非聊天模型）。
_CHAT_PREFIXES: dict[str, tuple[str, ...]] = {
    "anthropic": ("claude-",),
    "openai": ("gpt-", "o1", "o3", "o4", "chatgpt-"),
    "qwen": ("qwen",),
    # custom：端点未知，交给用户（_is_chat_model 对空前缀返回 True）
}

_STRONG_KEYS = ("opus", "gpt-5", "o1", "o3", "sonnet-4", "qwen-max")
_LIGHT_KEYS = ("haiku", "mini", "nano", "small", "flash", "lite")

_REDIRECT_CODES = frozenset({301, 302, 303, 307, 308})

MAX_MODELS_BODY_BYTES = 1_000_000
LIVE_TTL_SECONDS = 300.0
NEGATIVE_TTL_SECONDS = 15.0
DEFAULT_TIMEOUT_SECONDS = 8.0


class LiveModelsError(RuntimeError):
    """live 拉取 /models 失败（非 200 / redirect / 超限 / 解析不出）。fail-closed，不伪造清单。"""


def _tier(model_id: str) -> str:
    m = (model_id or "").lower()
    if any(k in m for k in _LIGHT_KEYS):
        return "light"
    if any(k in m for k in _STRONG_KEYS):
        return "strong"
    return "normal"


def _is_chat_model(provider: str, model_id: str) -> bool:
    prefixes = _CHAT_PREFIXES.get(provider, ())
    if not prefixes:
        return True  # custom/未知：不擅判为非聊天
    mid = (model_id or "").lower()
    return any(mid.startswith(p) for p in prefixes)


def _auth_headers(provider: str, api_key: str) -> dict[str, str]:
    if provider == "anthropic":
        return {"x-api-key": api_key, "anthropic-version": "2023-06-01"}
    return {"Authorization": f"Bearer {api_key}"}


def _parse_model_ids(provider: str, body: Any) -> list[str]:
    """anthropic 与 OpenAI 兼容端点均返回 {"data":[{"id":...}, ...]}。抽 id 列表。"""
    if not isinstance(body, dict):
        raise LiveModelsError(f"{provider} /models 响应非对象")
    data = body.get("data")
    if not isinstance(data, list):
        raise LiveModelsError(f"{provider} /models 响应缺 data[]")
    ids: list[str] = []
    for item in data:
        if isinstance(item, dict) and isinstance(item.get("id"), str) and item["id"].strip():
            ids.append(item["id"].strip())
    return ids


def fetch_live_models(
    provider: str,
    base_url: str,
    api_key: str,
    *,
    session: requests.Session | None = None,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
) -> list[str]:
    """GET {base}/models（加固：禁 redirect、限 body、短 timeout）→ model id 列表。

    调用方从 keystore 即时取 api_key 传入；本函数只用于请求 header，**绝不返回/缓存 key**。
    非 200 / redirect / 超限 / 解析不出 → LiveModelsError（fail-closed）。
    """
    base = (base_url or "").rstrip("/")
    if not base:
        raise LiveModelsError(f"provider {provider} 无 base_url，无法 live 列模型")
    if not (api_key or "").strip():
        raise LiveModelsError(f"provider {provider} 无 api_key，跳过 live 列模型")
    url = f"{base}/models"
    sess = session or requests.Session()
    resp = sess.get(
        url,
        headers=_auth_headers(provider, api_key),
        timeout=timeout,
        allow_redirects=False,  # 禁 redirect：3xx 直接拒，绝不把凭据 header 跟到重定向目标
    )
    try:
        status = int(getattr(resp, "status_code", 0) or 0)
        if status in _REDIRECT_CODES:
            raise LiveModelsError(f"{provider} /models 返回 redirect {status}（拒，防凭据外泄）")
        if status != 200:
            raise LiveModelsError(f"{provider} /models HTTP {status}")
        headers = getattr(resp, "headers", {}) or {}
        declared = 0
        try:
            declared = int(headers.get("Content-Length") or 0)
        except (TypeError, ValueError):
            declared = 0
        if declared > MAX_MODELS_BODY_BYTES:
            raise LiveModelsError(f"{provider} /models 响应声明 {declared}B 超上限（拒）")
        content = resp.content or b""
        if len(content) > MAX_MODELS_BODY_BYTES:
            raise LiveModelsError(f"{provider} /models 响应 {len(content)}B 超上限（拒）")
        try:
            body = json.loads(content.decode("utf-8"))
        except (ValueError, UnicodeDecodeError) as exc:
            raise LiveModelsError(f"{provider} /models 响应非合法 JSON") from exc
    finally:
        close = getattr(resp, "close", None)
        if callable(close):
            close()
    return _parse_model_ids(provider, body)


@dataclass(frozen=True)
class ModelEntry:
    provider: str
    model: str
    source: str          # live | curated | curated_fallback
    auth_kind: str       # api_key | subscription_cli | none
    supports_tools: bool
    selectable: bool
    tier: str = "normal"
    unavailable_reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def assemble_live_entries(provider: str, live_ids: list[str]) -> list[ModelEntry]:
    """api-key live 结果 → ModelEntry。非聊天模型展示但 selectable=false。"""
    out: list[ModelEntry] = []
    for mid in live_ids:
        chat = _is_chat_model(provider, mid)
        out.append(ModelEntry(
            provider=provider, model=mid, source="live", auth_kind="api_key",
            supports_tools=True, selectable=chat, tier=_tier(mid),
            unavailable_reason="" if chat else "非聊天模型（厂商目录返回，当前 adapter 不用于对话）",
        ))
    return out


def assemble_curated_entries(
    provider: str,
    *,
    auth_kind: str,
    source: str,
    curated: tuple[str, ...] | None = None,
) -> list[ModelEntry]:
    """curated 兜底 → ModelEntry。订阅(subscription_cli)→supports_tools=false（K3）。"""
    ids = curated if curated is not None else CURATED_MODELS.get(provider, ())
    supports_tools = auth_kind == "api_key"  # 订阅路径拒 tools
    reason = "" if supports_tools else "订阅模型仅限无工具通用对话（当前订阅 adapter 拒 tools）"
    return [
        ModelEntry(
            provider=provider, model=mid, source=source, auth_kind=auth_kind,
            supports_tools=supports_tools, selectable=True, tier=_tier(mid),
            unavailable_reason=reason,
        )
        for mid in ids
    ]


@dataclass
class _CacheSlot:
    expires_at: float
    entries: tuple[ModelEntry, ...]


def _config_revision(configured: bool, base_url: str, model: str, sub_authed: bool) -> str:
    raw = f"{int(configured)}|{base_url}|{model}|{int(sub_authed)}"
    return sha256(raw.encode("utf-8")).hexdigest()[:12]


def _redacted_base(base_url: str) -> str:
    try:
        return urlsplit(base_url).netloc or "?"
    except ValueError:
        return "?"


class ModelCatalog:
    """带 TTL 缓存的模型目录。缓存只存 ModelEntry 清单，**从不存 key**；配置变了(config_revision 变)自动失效。

    端点每次调 `list_models`：传 list_llm_status 结果 + 订阅 auth 表 + 即时 key 取用回调。
    """

    def __init__(
        self,
        *,
        session: requests.Session | None = None,
        now: Callable[[], float] = time.monotonic,
        live_ttl: float = LIVE_TTL_SECONDS,
        negative_ttl: float = NEGATIVE_TTL_SECONDS,
    ) -> None:
        self._session = session
        self._now = now
        self._live_ttl = live_ttl
        self._negative_ttl = negative_ttl
        self._cache: dict[str, _CacheSlot] = {}
        self._lock = threading.Lock()

    def invalidate(self) -> None:
        """configure / revoke / 订阅登录成功后调，强制下次重拉。"""
        with self._lock:
            self._cache.clear()

    def _provider_entries(
        self,
        provider: str,
        *,
        api_configured: bool,
        base_url: str,
        model: str,
        sub_authed: bool,
        key_lookup: Callable[[str], Optional[str]],
    ) -> tuple[list[ModelEntry], bool, bool]:
        """→ (entries, authed, live_ok)。api-key 优先；订阅补 api-key 缺位的厂（no-mix 单路由）。"""
        authed = api_configured or sub_authed
        if not authed:
            return [], False, False
        if api_configured:
            # api-key 路径优先：live 拉；失败 → curated_fallback（supports_tools 仍 True）
            try:
                api_key = key_lookup(provider) or ""
                live_ids = fetch_live_models(
                    provider, base_url or "", api_key, session=self._session,
                )
                return assemble_live_entries(provider, live_ids), True, True
            except (LiveModelsError, requests.RequestException):
                fallback = assemble_curated_entries(
                    provider, auth_kind="api_key", source="curated_fallback",
                )
                return fallback, True, False
        # 仅订阅：curated（supports_tools=false）
        return (
            assemble_curated_entries(provider, auth_kind="subscription_cli", source="curated"),
            True,
            False,
        )

    def list_models(
        self,
        *,
        providers_status: list[dict[str, Any]],
        subscription_status: dict[str, bool],
        key_lookup: Callable[[str], Optional[str]],
    ) -> list[dict[str, Any]]:
        """主入口。providers_status=list_llm_status 输出；subscription_status=provider→authed 表。"""
        result: list[dict[str, Any]] = []
        by_provider = {str(p.get("provider")): p for p in providers_status}
        # 覆盖 api-key 四家 + 订阅两家的并集
        providers = list(dict.fromkeys(
            [str(p.get("provider")) for p in providers_status]
            + [p for p in subscription_status]
        ))
        for provider in providers:
            info = by_provider.get(provider, {})
            api_configured = bool(info.get("configured"))
            base_url = str(info.get("base_url") or "") or _default_base(provider)
            model = str(info.get("model") or "")
            sub_authed = bool(subscription_status.get(provider))
            authed = api_configured or sub_authed
            auth_kind = "api_key" if api_configured else ("subscription_cli" if sub_authed else "none")
            rev = _config_revision(api_configured, base_url, model, sub_authed)
            cache_key = f"{provider}|{auth_kind}|{_redacted_base(base_url)}|{rev}"

            entries: list[ModelEntry]
            live_ok = False
            if not authed:
                entries = []
            else:
                slot = self._get_slot(cache_key)
                if slot is not None:
                    entries = list(slot.entries)
                    live_ok = auth_kind == "api_key"
                else:
                    entries, _authed, live_ok = self._provider_entries(
                        provider,
                        api_configured=api_configured,
                        base_url=base_url,
                        model=model,
                        sub_authed=sub_authed,
                        key_lookup=key_lookup,
                    )
                    ttl = self._live_ttl if live_ok else self._negative_ttl
                    self._put_slot(cache_key, tuple(entries), ttl)

            result.append({
                "provider": provider,
                "auth_kind": auth_kind,
                "authed": authed,
                "selectable": authed and any(e.selectable for e in entries),
                "source": ("live" if live_ok else ("curated" if authed else "none")),
                "catalog_revision": rev,
                "models": [e.to_dict() for e in entries],
            })
        return result

    def _get_slot(self, key: str) -> _CacheSlot | None:
        with self._lock:
            slot = self._cache.get(key)
            if slot is None:
                return None
            if slot.expires_at <= self._now():
                self._cache.pop(key, None)
                return None
            return slot

    def _put_slot(self, key: str, entries: tuple[ModelEntry, ...], ttl: float) -> None:
        with self._lock:
            self._cache[key] = _CacheSlot(expires_at=self._now() + ttl, entries=entries)


def _default_base(provider: str) -> str:
    # 避免从 llm_providers import 造循环；与 _DEFAULT_BASE_URLS 对齐（base 已含 /v1）。
    return {
        "anthropic": "https://api.anthropic.com/v1",
        "openai": "https://api.openai.com/v1",
        "qwen": "https://dashscope.aliyuncs.com/compatible-mode/v1",
    }.get(provider, "")


__all__ = [
    "CURATED_MODELS",
    "LiveModelsError",
    "ModelCatalog",
    "ModelEntry",
    "assemble_curated_entries",
    "assemble_live_entries",
    "fetch_live_models",
]
