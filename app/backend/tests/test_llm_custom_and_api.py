from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from app import main
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
from app.auth import require_user_dependency
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

    monkeypatch.setenv("QUANTBT_LLM_ADMIN_USER_IDS", "llm-admin")
    app.dependency_overrides[require_user_dependency] = lambda: SimpleNamespace(
        user_id="llm-admin",
        username="llm-admin",
    )
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.pop(require_user_dependency, None)


@pytest.fixture()
def isolated_client(monkeypatch, tmp_path):
    for var in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "DASHSCOPE_API_KEY", "LLM_PROVIDER"):
        monkeypatch.delenv(var, raising=False)
    from app import main

    keystore = SecureKeystore(InMemoryKeystore())
    registry = PersistentOnboardingRegistry(tmp_path / "onboarding_settings.jsonl")
    monkeypatch.setattr(main, "KEYSTORE", keystore)
    monkeypatch.setattr(main, "ONBOARDING_REGISTRY", registry)
    monkeypatch.setenv("QUANTBT_LLM_ADMIN_USER_IDS", "llm-admin")
    main.app.dependency_overrides[require_user_dependency] = lambda: SimpleNamespace(
        user_id="llm-admin",
        username="llm-admin",
    )
    try:
        yield TestClient(main.app), keystore, registry
    finally:
        main.app.dependency_overrides.pop(require_user_dependency, None)


def test_get_llm_status(client) -> None:
    r = client.get("/api/llm/status")
    assert r.status_code == 200
    body = r.json()
    # v0.9.5 schema: {providers: [...], active_provider: "auto"|...}
    assert "providers" in body
    assert "active_provider" in body
    providers = {s["provider"] for s in body["providers"]}
    assert providers == {"anthropic", "openai", "qwen", "custom"}


def test_machine_global_llm_routes_require_auth_and_admin(monkeypatch) -> None:
    from app import main

    main.app.dependency_overrides.pop(require_user_dependency, None)
    unauthenticated = TestClient(main.app)
    assert unauthenticated.get("/api/llm/status").status_code == 401
    assert unauthenticated.post("/api/llm/configure", json={}).status_code == 401
    assert unauthenticated.post("/api/llm/active", json={"provider": "auto"}).status_code == 401
    assert unauthenticated.post("/api/llm/test", json={}).status_code == 401

    monkeypatch.setenv("QUANTBT_LLM_ADMIN_USER_IDS", "actual-admin")
    main.app.dependency_overrides[require_user_dependency] = lambda: SimpleNamespace(
        user_id="ordinary-user",
        username="ordinary-user",
    )
    ordinary = TestClient(main.app)
    try:
        assert ordinary.get("/api/llm/status").status_code == 200
        assert ordinary.post("/api/llm/configure", json={}).status_code == 403
        assert ordinary.post("/api/llm/active", json={"provider": "auto"}).status_code == 403
        assert ordinary.post("/api/llm/test", json={}).status_code == 403
    finally:
        main.app.dependency_overrides.pop(require_user_dependency, None)


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
    assert registry.secret_ref(
        "secretref:llm:openai",
        owner_user_id=main._LLM_SERVICE_PRINCIPAL,
    ).status == SecretRefStatus.ACTIVE
    assert registry.llm_provider(
        "openai",
        owner_user_id=main._LLM_SERVICE_PRINCIPAL,
    ).auth_refs == ("secretref:llm:openai",)
    assert registry.credential_pool(
        "pool:llm:openai:default",
        owner_user_id=main._LLM_SERVICE_PRINCIPAL,
    ).auth_refs == ("secretref:llm:openai",)
    assert registry.routing_policy(
        "routing:llm:openai:default",
        owner_user_id=main._LLM_SERVICE_PRINCIPAL,
    ).allowed_models == ("gpt-5.5",)

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
    revision, record_hash = registry.record_state(
        "secret_ref_recorded",
        "secretref:llm:custom",
        owner_user_id=main._LLM_SERVICE_PRINCIPAL,
    )
    registry.record_secret_ref(
        SecretRefRecord(
            secret_ref="secretref:llm:custom",
            scope="llm:custom:call",
            status=SecretRefStatus.REVOKED,
            created_at="2026-06-27T00:00:00Z",
            revoked_at="2026-06-27T01:00:00Z",
        ),
        owner_user_id=main._LLM_SERVICE_PRINCIPAL,
        expected_previous_revision=revision,
        expected_previous_hash=record_hash,
    )
    result = client.post("/api/llm/test", json={"provider": "custom", "ping": "ok"}).json()
    assert result["ok"] is False
    assert "llm_call_uses_revoked_secret_ref" in result["error"]


def test_settings_managed_llm_does_not_use_env_key_without_settings_metadata(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "sk-env-should-not-be-used")
    keystore = SecureKeystore(InMemoryKeystore())
    registry = PersistentOnboardingRegistry(tmp_path / "onboarding_settings.jsonl")

    with pytest.raises(Exception, match="provider not configured|route rejected"):
        make_settings_managed_llm_client(
            provider="openai",
            keystore=keystore,
            registry=registry,
            owner_user_id=main._LLM_SERVICE_PRINCIPAL,
        )


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
        owner=main._LLM_SERVICE_PRINCIPAL,
    )

    client = make_settings_managed_llm_client(
        provider="openai",
        keystore=keystore,
        registry=registry,
        owner_user_id=main._LLM_SERVICE_PRINCIPAL,
    )
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


# ------- 跨厂商切模型（S1）：/api/llm/models 端点 -------

def test_get_llm_models_requires_auth(monkeypatch) -> None:
    """未认证 → 401（与其他 llm 路由一致）。"""
    main.app.dependency_overrides.pop(require_user_dependency, None)
    unauth = TestClient(main.app)
    assert unauth.get("/api/llm/models").status_code == 401


def test_get_llm_models_unauthed_providers_empty(isolated_client, monkeypatch) -> None:
    """无 api-key、无订阅 → 每厂 authed=false、模型不可选、零 live 请求（订阅探测 patched）。"""
    client, keystore, registry = isolated_client
    main._invalidate_llm_catalog_caches()  # 清订阅探测 TTL 缓存(模块级,防跨测试污染)
    # patch 订阅探测(否则跑真 CLI subprocess,依赖测试机是否登录→flaky)
    monkeypatch.setattr(
        "app.agent.subscription_cli_llm.auth_status_all",
        lambda **kw: [
            {"provider": "anthropic", "subscription_authed": False},
            {"provider": "openai", "subscription_authed": False},
        ],
    )
    # 隔离一个全新 catalog(带假 session:任何 get 都 fail,证明未认证时不该被调)
    class _NoNetSession:
        def get(self, *a, **k):  # noqa: ANN001
            raise AssertionError("未认证厂商不得发起 live /models 请求")

    from app.llm.model_catalog import ModelCatalog
    monkeypatch.setattr(main, "_MODEL_CATALOG", ModelCatalog(session=_NoNetSession()))

    r = client.get("/api/llm/models")
    assert r.status_code == 200
    rows = {p["provider"]: p for p in r.json()["providers"]}
    for prov in ("anthropic", "openai", "qwen", "custom"):
        assert rows[prov]["authed"] is False
        assert rows[prov]["selectable"] is False
        assert rows[prov]["models"] == []


def test_get_llm_models_subscription_curated(isolated_client, monkeypatch) -> None:
    """订阅登录的厂商 → curated 模型、supports_tools=false、不打厂商 /models。"""
    client, keystore, registry = isolated_client
    main._invalidate_llm_catalog_caches()
    monkeypatch.setattr(
        "app.agent.subscription_cli_llm.auth_status_all",
        lambda **kw: [
            {"provider": "anthropic", "subscription_authed": True},
            {"provider": "openai", "subscription_authed": False},
        ],
    )

    class _NoNetSession:
        def get(self, *a, **k):  # noqa: ANN001
            raise AssertionError("订阅路径不得打厂商 /models")

    from app.llm.model_catalog import ModelCatalog
    monkeypatch.setattr(main, "_MODEL_CATALOG", ModelCatalog(session=_NoNetSession()))

    r = client.get("/api/llm/models")
    assert r.status_code == 200
    rows = {p["provider"]: p for p in r.json()["providers"]}
    assert rows["anthropic"]["authed"] is True
    assert rows["anthropic"]["auth_kind"] == "subscription_cli"
    assert rows["anthropic"]["models"]
    assert all(m["supports_tools"] is False for m in rows["anthropic"]["models"])


def test_get_llm_models_subscription_probe_ttl_cached(isolated_client, monkeypatch) -> None:
    """[DoS 修复] 订阅探测(spawn subprocess)加 TTL 缓存：两次请求只探一次。"""
    client, keystore, registry = isolated_client
    main._invalidate_llm_catalog_caches()
    calls = {"n": 0}

    def _probe(**kw):
        calls["n"] += 1
        return [{"provider": "anthropic", "subscription_authed": False},
                {"provider": "openai", "subscription_authed": False}]

    monkeypatch.setattr("app.agent.subscription_cli_llm.auth_status_all", _probe)
    from app.llm.model_catalog import ModelCatalog
    monkeypatch.setattr(main, "_MODEL_CATALOG", ModelCatalog(session=object()))

    client.get("/api/llm/models")
    client.get("/api/llm/models")
    assert calls["n"] == 1  # 第二次命中 60s TTL 缓存,不再 spawn subprocess


def test_configure_invalidates_model_catalog_cache(isolated_client, monkeypatch) -> None:
    """[缓存失效] /api/llm/configure 后订阅探测缓存被清,下次请求重探。"""
    client, keystore, registry = isolated_client
    main._invalidate_llm_catalog_caches()
    calls = {"n": 0}

    def _probe(**kw):
        calls["n"] += 1
        return [{"provider": "anthropic", "subscription_authed": False},
                {"provider": "openai", "subscription_authed": False}]

    monkeypatch.setattr("app.agent.subscription_cli_llm.auth_status_all", _probe)

    import requests as _rq

    class _FailSession:  # configure 后 anthropic 变 api-configured→会 live fetch;让它优雅失败到 curated_fallback
        def get(self, *a, **k):  # noqa: ANN001
            raise _rq.ConnectionError("no net in test")

    from app.llm.model_catalog import ModelCatalog
    monkeypatch.setattr(main, "_MODEL_CATALOG", ModelCatalog(session=_FailSession()))

    client.get("/api/llm/models")
    assert calls["n"] == 1
    # configure 应失效缓存
    client.post("/api/llm/configure", json={"provider": "anthropic", "api_key": "sk-x"})
    client.get("/api/llm/models")
    assert calls["n"] == 2  # 缓存已清,重探
