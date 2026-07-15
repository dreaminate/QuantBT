"""跨厂商切模型 S5：订阅账号接进 gateway（credential_pool + client_factory 层）。

钉死：
- subscription_cli 凭据无 api_key 但认作可用（keyless-but-authenticated），否则 gateway 误判 no_key fallback。
- deny-by-default 不被放宽：api_key 档无 key 仍不可用。
- client_factory 把 subscription_cli 路由到厂商 CLI adapter（不伪装 custom/oauth_proxy）。
"""

from __future__ import annotations

import pytest

from app.agent import subscription_cli_llm as scl
from app.llm.credential_pool import MaterializedCredential
from app.llm.gateway import _default_client_factory


def _cred(provider: str, auth_kind: str, *, api_key: str = "", model: str = "claude-sonnet-4-5"):
    return MaterializedCredential(
        api_key=api_key, base_url="", model=model, provider=provider,
        auth_kind=auth_kind, auth_ref="",
    )


def test_subscription_cli_credential_is_keyless_usable():
    # 订阅凭据无 api_key 但认作可用——否则 gateway 会误判 no_key 而 fallback。
    assert _cred("anthropic", "subscription_cli", api_key="").has_usable_key is True
    assert _cred("openai", "subscription_cli", api_key="").has_usable_key is True


def test_api_key_credential_without_key_still_not_usable():
    # 对照:api_key 档无 key → 不可用(subscription 分支不放宽 deny-by-default)。
    assert _cred("anthropic", "api_key", api_key="").has_usable_key is False


def test_client_factory_routes_subscription_to_cli_adapter(monkeypatch):
    monkeypatch.setattr(scl.shutil, "which", lambda name: f"/usr/bin/{name}")  # CLI "已装"
    c = _default_client_factory(_cred("anthropic", "subscription_cli", model="claude-opus-4-8"))
    assert isinstance(c, scl.ClaudeSubscriptionLLM) and c.provider == "anthropic"
    o = _default_client_factory(_cred("openai", "subscription_cli", model="gpt-5.6-sol"))
    assert isinstance(o, scl.CodexSubscriptionLLM) and o.provider == "openai"


def test_client_factory_subscription_not_disguised_as_custom(monkeypatch):
    # subscription_cli 不被当成 custom/oauth_proxy 走 make_llm_client——是真订阅 CLI adapter。
    monkeypatch.setattr(scl.shutil, "which", lambda name: f"/usr/bin/{name}")
    c = _default_client_factory(_cred("anthropic", "subscription_cli"))
    assert type(c).__name__ == "ClaudeSubscriptionLLM"
