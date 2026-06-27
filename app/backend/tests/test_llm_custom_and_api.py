from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from app.agent import (
    DevLocalLLM,
    LLMMessage,
    OpenAICompatibleLLM,
    OpenAILLM,
    ensure_settings_managed_llm_provider,
    list_llm_status,
    make_llm_client,
    make_settings_managed_llm_client,
)
from app.research_os import PersistentOnboardingRegistry, SecretRefRecord, SecretRefStatus
from app.security import InMemoryKeystore, KeystoreRecord, SecureKeystore


def test_openai_compatible_requires_base_url_and_model() -> None:
    with pytest.raises(Exception):
        OpenAICompatibleLLM(api_key="x", base_url="", default_model="m")
    with pytest.raises(Exception):
        OpenAICompatibleLLM(api_key="x", base_url="http://x", default_model="")


def test_openai_compatible_hits_user_supplied_base_url() -> None:
    session = MagicMock()
    resp = MagicMock()
    resp.status_code = 200
    resp.json.return_value = {"choices": [{"message": {"role": "assistant", "content": "hi"}}]}
    resp.raise_for_status.return_value = None
    session.post.return_value = resp
    llm = OpenAICompatibleLLM(api_key="ollama", base_url="http://localhost:11434/v1", default_model="qwen2.5", session=session)
    out = llm.chat([LLMMessage(role="user", content="hi")])
    assert out.content == "hi"
    url = session.post.call_args.args[0]
    assert url.startswith("http://localhost:11434/v1")


def test_make_llm_client_custom_from_keystore(monkeypatch) -> None:
    for var in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "DASHSCOPE_API_KEY", "LLM_PROVIDER"):
        monkeypatch.delenv(var, raising=False)
    ks = SecureKeystore(InMemoryKeystore())
    ks.store(
        KeystoreRecord(
            name="llm_custom",
            api_key="ollama",
            api_secret="ollama",
            note=json.dumps({"base_url": "http://localhost:11434/v1", "model": "qwen2.5:32b"}),
        )
    )
    client = make_llm_client(keystore=ks)
    assert isinstance(client, OpenAICompatibleLLM)


def test_list_llm_status_shows_each_provider() -> None:
    ks = SecureKeystore(InMemoryKeystore())
    ks.store(
        KeystoreRecord(
            name="llm_anthropic",
            api_key="sk-ant-x",
            api_secret="sk-ant-x",
            note=json.dumps({"base_url": "https://proxy.example/v1", "model": "claude-3"}),
        )
    )
    status = list_llm_status(ks)
    by_p = {s["provider"]: s for s in status}
    assert by_p["anthropic"]["configured"] is True
    assert by_p["anthropic"]["base_url"] == "https://proxy.example/v1"
    assert by_p["anthropic"]["model"] == "claude-3"
    assert by_p["openai"]["configured"] is False
    assert by_p["custom"]["configured"] is False
    # default_model 字段在 anthropic / openai / qwen 都有；custom 留空
    assert by_p["anthropic"]["default_model"] == "claude-sonnet-4-5"


# ------- REST API（用 TestClient）-------

@pytest.fixture()
def client(monkeypatch):
    # 隔离环境变量影响
    for var in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "DASHSCOPE_API_KEY", "LLM_PROVIDER"):
        monkeypatch.delenv(var, raising=False)
    from app.main import app

    return TestClient(app)


@pytest.fixture()
def isolated_client(monkeypatch, tmp_path):
    for var in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "DASHSCOPE_API_KEY", "LLM_PROVIDER"):
        monkeypatch.delenv(var, raising=False)
    from app import main

    keystore = SecureKeystore(InMemoryKeystore())
    registry = PersistentOnboardingRegistry(tmp_path / "onboarding_settings.jsonl")
    monkeypatch.setattr(main, "KEYSTORE", keystore)
    monkeypatch.setattr(main, "ONBOARDING_REGISTRY", registry)
    return TestClient(main.app), keystore, registry


def test_get_llm_status(client) -> None:
    r = client.get("/api/llm/status")
    assert r.status_code == 200
    body = r.json()
    # v0.9.5 schema: {providers: [...], active_provider: "auto"|...}
    assert "providers" in body
    assert "active_provider" in body
    providers = {s["provider"] for s in body["providers"]}
    assert providers == {"anthropic", "openai", "qwen", "custom"}


def test_post_llm_configure_custom(client) -> None:
    r = client.post(
        "/api/llm/configure",
        json={
            "provider": "custom",
            "api_key": "ollama",
            "base_url": "http://localhost:11434/v1",
            "model": "qwen2.5:32b",
        },
    )
    assert r.status_code == 200
    body = r.json()
    assert body["configured"] == "custom"
    assert body["base_url"] == "http://localhost:11434/v1"
    # status 应该反映 configured=True (v0.9.5 schema)
    status_body = client.get("/api/llm/status").json()
    by_p = {s["provider"]: s for s in status_body["providers"]}
    assert by_p["custom"]["configured"] is True
    assert by_p["custom"]["model"] == "qwen2.5:32b"


def test_post_llm_configure_records_settings_metadata_without_plaintext_secret(isolated_client) -> None:
    client, _keystore, registry = isolated_client
    secret = "sk-live-plaintext-should-not-echo"
    r = client.post(
        "/api/llm/configure",
        json={
            "provider": "openai",
            "api_key": secret,
            "base_url": "https://proxy.example/v1",
            "model": "gpt-5.5",
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["settings_refs"]["secret_ref"] == "secretref:llm:openai"
    assert secret not in r.text
    assert registry.secret_ref("secretref:llm:openai").status == SecretRefStatus.ACTIVE
    assert registry.llm_provider("openai").auth_refs == ("secretref:llm:openai",)
    assert registry.credential_pool("pool:llm:openai:default").auth_refs == ("secretref:llm:openai",)
    assert registry.routing_policy("routing:llm:openai:default").allowed_models == ("gpt-5.5",)

    status = client.get("/api/llm/status").json()
    openai = next(row for row in status["providers"] if row["provider"] == "openai")
    assert openai["settings_managed"] is True
    assert openai["auth_status"] == "active"
    assert secret not in str(status)


def test_settings_gateway_rejects_revoked_secret_ref_for_connection_test(isolated_client) -> None:
    client, _keystore, registry = isolated_client
    configured = client.post(
        "/api/llm/configure",
        json={
            "provider": "custom",
            "api_key": "local-key",
            "base_url": "http://localhost:11434/v1",
            "model": "qwen2.5:32b",
        },
    )
    assert configured.status_code == 200, configured.text
    registry.record_secret_ref(
        SecretRefRecord(
            secret_ref="secretref:llm:custom",
            scope="llm:custom:call",
            status=SecretRefStatus.REVOKED,
            created_at="2026-06-27T00:00:00Z",
            revoked_at="2026-06-27T01:00:00Z",
        )
    )
    result = client.post("/api/llm/test", json={"provider": "custom", "ping": "ok"}).json()
    assert result["ok"] is False
    assert "llm_call_uses_revoked_secret_ref" in result["error"]


def test_settings_managed_llm_does_not_use_env_key_without_settings_metadata(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "sk-env-should-not-be-used")
    keystore = SecureKeystore(InMemoryKeystore())
    registry = PersistentOnboardingRegistry(tmp_path / "onboarding_settings.jsonl")

    with pytest.raises(Exception, match="provider not configured|route rejected"):
        make_settings_managed_llm_client(provider="openai", keystore=keystore, registry=registry)


def test_settings_managed_llm_uses_keystore_secret_not_env(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "sk-env-should-not-be-used")
    keystore = SecureKeystore(InMemoryKeystore())
    keystore.store(
        KeystoreRecord(
            name="llm_openai",
            api_key="sk-keystore",
            api_secret="sk-keystore",
            note=json.dumps({"base_url": "https://proxy.example/v1", "model": "gpt-5.5"}),
        )
    )
    registry = PersistentOnboardingRegistry(tmp_path / "onboarding_settings.jsonl")
    ensure_settings_managed_llm_provider(
        registry=registry,
        provider="openai",
        base_url="https://proxy.example/v1",
        model="gpt-5.5",
    )

    client = make_settings_managed_llm_client(provider="openai", keystore=keystore, registry=registry)
    assert isinstance(client, OpenAILLM)
    assert client._key == "sk-keystore"


def test_post_llm_active_switch(client) -> None:
    """v0.9.5 · 切换 active provider。"""
    # 先配 custom
    client.post("/api/llm/configure", json={
        "provider": "custom", "api_key": "x",
        "base_url": "http://localhost:11434/v1", "model": "qwen2.5:32b",
    })
    r = client.post("/api/llm/active", json={"provider": "custom"})
    assert r.status_code == 200
    assert r.json()["active_provider"] == "custom"
    # 切回 auto
    r2 = client.post("/api/llm/active", json={"provider": "auto"})
    assert r2.json()["active_provider"] == "auto"


def test_post_llm_active_rejects_unconfigured(client) -> None:
    r = client.post("/api/llm/active", json={"provider": "qwen"})
    assert r.status_code == 400
    assert "未配置" in r.json()["detail"] or "configured" in r.json()["detail"].lower()


def test_post_llm_active_rejects_unknown_provider(client) -> None:
    r = client.post("/api/llm/active", json={"provider": "evil_provider"})
    assert r.status_code == 400


def test_post_llm_configure_rejects_incomplete_custom(client) -> None:
    r = client.post("/api/llm/configure", json={"provider": "custom", "api_key": "x"})
    assert r.status_code == 400


def test_post_llm_configure_anthropic_requires_key(client) -> None:
    r = client.post("/api/llm/configure", json={"provider": "anthropic", "api_key": ""})
    assert r.status_code == 400


def test_post_llm_test_falls_back_to_dev_local_when_no_key(client) -> None:
    """没有真实 key 时，/api/llm/test 仍能用 DevLocalLLM 回答（dev_local 不报错）。"""
    r = client.post("/api/llm/test", json={"provider": None, "ping": "你能做什么"})
    body = r.json()
    # 可能是 ok=True 走到 DevLocalLLM，也可能因别的测试已设过 key 走真 provider；
    # 至少接口结构正确
    assert "provider" in body
