"""LLM Gateway · 凭据池（LLMCredentialPool + SecretRef）。

GOAL §1：明文 API key / OAuth token / device code token / CLI credential **只存在
Settings/Secrets 安全后端**（本仓 = `security.SecureKeystore`）；Gateway 只持 **SecretRef 引用**，
role agent 只能通过 Gateway 拿模型结果，**绝不直接读 credential**。

本模块的边界设计：
- `SecretRef` / `CredentialDescriptor` —— role-agent 可见层，**永不含明文**（repr 也不泄露）。
- `MaterializedCredential` —— gateway 内部短命凭据，明文只在此对象、调用后即丢，repr 打码。
- 物化只在 `_materialize(...)`，且要求 gateway capability：role agent 即便 import 到本类，
  没有 gateway 在构造时领到的 capability 也物化不出明文。

诚实限界：同进程里没法在语言层「绝对禁止」别的代码 fetch keystore——capability 抓的是
「没拿到 gateway 私有 nonce 就别想从池里物化」这条**可测边界**，配合 gateway 封印 + 准入门，
共同实现 GOAL 真正要的「绕过治理的凭据使用对 Research Graph 不可准入」。
"""

from __future__ import annotations

import hmac
import secrets
from dataclasses import dataclass, field
from typing import Any

from ..security import KeystoreError, SecureKeystore

# 复用现有 provider→keystore 名映射（agent.llm_providers.KEYSTORE_NAMES），不另造一套命名。
_DEFAULT_KEYSTORE_NAMES: dict[str, str] = {
    "anthropic": "llm_anthropic",
    "openai": "llm_openai",
    "qwen": "llm_qwen",
    "custom": "llm_custom",
}


class CredentialError(RuntimeError):
    pass


@dataclass(frozen=True)
class SecretRef:
    """受控引用：指向 Settings/Secrets 安全后端的一条记录，**绝不含明文**。"""

    keystore_name: str               # SecureKeystore 里的记录名，如 "llm_anthropic"（subscription_cli 为空）
    provider: str                    # anthropic / openai / qwen / custom / oauth_proxy / dev_local
    auth_kind: str = "api_key"       # api_key | oauth_proxy | token | none | subscription_cli
    label: str = ""

    @property
    def ref(self) -> str:
        return f"secretref://{self.provider}/{self.keystore_name}"

    def __repr__(self) -> str:  # 防明文：repr 永不暴露任何 secret（这里本就不持明文）
        return (
            f"SecretRef(provider={self.provider!r}, keystore_name={self.keystore_name!r}, "
            f"auth_kind={self.auth_kind!r})"
        )


@dataclass(frozen=True)
class CredentialDescriptor:
    """role-agent 可见视图：provider/auth 元数据，无明文。"""

    pool_id: str
    provider: str
    auth_kind: str
    auth_ref: str                    # = SecretRef.ref
    base_url_redacted: str
    default_model: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "pool_id": self.pool_id,
            "provider": self.provider,
            "auth_kind": self.auth_kind,
            "auth_ref": self.auth_ref,
            "base_url_redacted": self.base_url_redacted,
            "default_model": self.default_model,
        }


class MaterializedCredential:
    """gateway 内部短命凭据：明文只在此对象、调用后丢弃。repr / str 永不泄露明文。"""

    __slots__ = ("api_key", "base_url", "model", "provider", "auth_kind", "auth_ref")

    def __init__(
        self,
        *,
        api_key: str,
        base_url: str,
        model: str,
        provider: str,
        auth_kind: str,
        auth_ref: str,
    ) -> None:
        self.api_key = api_key
        self.base_url = base_url
        self.model = model
        self.provider = provider
        self.auth_kind = auth_kind
        self.auth_ref = auth_ref

    @property
    def has_usable_key(self) -> bool:
        """非 dev_local / 非 oauth_proxy / 非 subscription_cli 的 api_key 档，必须真有 key 才算可用。

        subscription_cli（跨厂商切模型 S5）：凭据在厂商 CLI 自己的安全存储，gateway 不持 key、
        api_key 恒空——认作 keyless-but-authenticated（可用），否则 gateway 会误判 no_key 而 fallback。
        订阅是否真登录由 build 期 subscription_auth_status 门控（deny-by-default 不弱化）。
        """
        if self.provider == "dev_local" or self.auth_kind in (
            "none", "oauth_proxy", "subscription_cli",
        ):
            return True
        return bool(self.api_key)

    def base_url_redacted(self) -> str:
        """base_url 一般非密；但仍走 helper 以便统一打码本地代理端口等。"""

        return self.base_url or ""

    def __repr__(self) -> str:
        return (
            f"MaterializedCredential(provider={self.provider!r}, auth_kind={self.auth_kind!r}, "
            f"api_key=<redacted>)"
        )

    __str__ = __repr__


class GatewayCapability:
    """gateway 持有的物化令牌——拿不到池子的私有 nonce 就构造不出有效令牌。"""

    __slots__ = ("_token",)

    def __init__(self, token: bytes) -> None:
        self._token = token

    def matches(self, expected: bytes) -> bool:
        return hmac.compare_digest(self._token, expected)


@dataclass
class _PoolEntry:
    secret_ref: SecretRef
    base_url: str = ""
    default_model: str = ""


class LLMCredentialPool:
    """凭据池：登记 SecretRef，按 pool_id 物化（仅限持 capability 的 gateway）。"""

    def __init__(self, keystore: SecureKeystore | None = None) -> None:
        self._keystore = keystore
        self._pools: dict[str, _PoolEntry] = {}
        # 每个池实例一把私有 nonce：gateway 构造时 issue_capability() 领走，物化时核对。
        self._cap_secret = secrets.token_bytes(16)

    # —— 登记 ——

    def register(
        self,
        pool_id: str,
        secret_ref: SecretRef,
        *,
        base_url: str = "",
        default_model: str = "",
    ) -> None:
        self._pools[pool_id] = _PoolEntry(secret_ref=secret_ref, base_url=base_url, default_model=default_model)

    def register_dev_local(self, pool_id: str = "dev_local") -> str:
        """开发期 / 无 key 兜底池：provider=dev_local，无 secret。"""

        self.register(pool_id, SecretRef(keystore_name="", provider="dev_local", auth_kind="none", label="dev"))
        return pool_id

    def register_from_keystore_defaults(self) -> list[str]:
        """按 KEYSTORE_NAMES 自动登记 keystore 里已配置的 provider，外加 dev_local 兜底。

        note 里的 base_url/model（secrets_loader 写入）一并取出登记。绝不在此回读/打印明文。
        """

        registered: list[str] = []
        if self._keystore is not None:
            import json as _json

            for provider, ks_name in _DEFAULT_KEYSTORE_NAMES.items():
                try:
                    record = self._keystore.fetch(ks_name)
                except KeystoreError:
                    continue
                if not (record.api_key or record.api_secret):
                    continue
                extras: dict[str, str] = {}
                if record.note:
                    try:
                        parsed = _json.loads(record.note)
                        if isinstance(parsed, dict):
                            extras = {k: str(v) for k, v in parsed.items() if v}
                    except Exception:  # noqa: BLE001
                        extras = {}
                auth_kind = "oauth_proxy" if provider == "custom" else "api_key"
                self.register(
                    provider,
                    SecretRef(keystore_name=ks_name, provider=provider, auth_kind=auth_kind, label=provider),
                    base_url=extras.get("base_url", ""),
                    default_model=extras.get("model", ""),
                )
                registered.append(provider)
        registered.append(self.register_dev_local())
        return registered

    # —— role-agent 安全视图（无明文）——

    def has_pool(self, pool_id: str) -> bool:
        return pool_id in self._pools

    def describe(self, pool_id: str) -> CredentialDescriptor:
        entry = self._require(pool_id)
        return CredentialDescriptor(
            pool_id=pool_id,
            provider=entry.secret_ref.provider,
            auth_kind=entry.secret_ref.auth_kind,
            auth_ref=entry.secret_ref.ref,
            base_url_redacted=entry.base_url,
            default_model=entry.default_model,
        )

    def list_pools(self) -> list[CredentialDescriptor]:
        return [self.describe(pid) for pid in self._pools]

    # —— gateway 专用：领令牌 + 物化 ——

    def issue_capability(self) -> GatewayCapability:
        """gateway 构造时领走唯一令牌。role agent 拿不到 self._cap_secret，构造不出有效令牌。"""

        return GatewayCapability(self._cap_secret)

    def materialize(self, pool_id: str, *, capability: GatewayCapability) -> MaterializedCredential:
        """物化明文凭据——仅限持本池 capability 的 gateway。明文绝不落账、绝不日志。"""

        if not isinstance(capability, GatewayCapability) or not capability.matches(self._cap_secret):
            raise CredentialError(
                "凭据物化需 gateway capability——role agent 不得直取明文 credential（GOAL §1/§7）"
            )
        entry = self._require(pool_id)
        ref = entry.secret_ref
        api_key = ""
        if self._keystore is not None and ref.auth_kind != "none" and ref.keystore_name:
            try:
                record = self._keystore.fetch(ref.keystore_name)
                api_key = record.api_secret or record.api_key
            except KeystoreError:
                api_key = ""
        return MaterializedCredential(
            api_key=api_key,
            base_url=entry.base_url,
            model=entry.default_model,
            provider=ref.provider,
            auth_kind=ref.auth_kind,
            auth_ref=ref.ref,
        )

    def known_secret_values(self) -> list[str]:
        """供 gateway secret 泄露门用：当前 keystore 全部在册明文（含交易 key）——临时取、不落账、不打印。

        gateway 用它逐字断言「这些 secret 没漏进 prompt / 账 / 导出」。本方法是安全边界内的受控读取。
        """

        values: list[str] = []
        if self._keystore is not None:
            for name in self._keystore.list_names():
                try:
                    record = self._keystore.fetch(name)
                except KeystoreError:
                    continue
                if record.api_key:
                    values.append(record.api_key)
                if record.api_secret:
                    values.append(record.api_secret)
        # 去重 + 过滤空
        return sorted({v for v in values if v})

    # —— 内部 ——

    def _require(self, pool_id: str) -> _PoolEntry:
        entry = self._pools.get(pool_id)
        if entry is None:
            raise CredentialError(f"未登记的 pool_id={pool_id!r}")
        return entry


__all__ = [
    "CredentialDescriptor",
    "CredentialError",
    "GatewayCapability",
    "LLMCredentialPool",
    "MaterializedCredential",
    "SecretRef",
]
