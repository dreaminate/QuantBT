"""LLM 模型目录(S1,跨厂商切模型)测试——纯 mock、零网络、不烧任何厂商额度。

区别于 test_model_catalog.py(那测 ML/DL 训练模型目录 app.models.catalog);本文件测
app.llm.model_catalog（LLM 可选模型清单源）。

钉死不变量(findings/dreaminate/model-switch-crossvendor-design-20260715.md · S1)：
- live 拉取加固：禁 redirect、限 body、非 200 fail-closed、allow_redirects=False。
- live ≠ chat-capable：非聊天模型展示但 selectable=false。
- 订阅 curated：supports_tools=false（K3），source 正确标注。
- auth 门控：未认证厂商零 live 请求、模型不可选。
- 缓存：命中不重拉；invalidate 后重拉；config_revision 变（换 base/model/订阅态）重拉。
- 凭据零触碰：api_key 只进请求 header，不进返回体/缓存。
"""

from __future__ import annotations

import json

import pytest
import requests

from app.llm import model_catalog as mc


class _FakeResponse:
    def __init__(self, status_code=200, body=None, headers=None, raw_content=None):
        self.status_code = status_code
        self.headers = headers or {}
        if raw_content is not None:
            self.content = raw_content
        else:
            self.content = json.dumps(body if body is not None else {"data": []}).encode("utf-8")
        self.closed = False

    def close(self):
        self.closed = True


class _FakeSession:
    """记录 get 调用(url/headers/allow_redirects);按 url 返回预置响应。"""

    def __init__(self, responses=None, default=None):
        self.responses = responses or {}
        self.default = default
        self.calls = []

    def get(self, url, headers=None, timeout=None, allow_redirects=None):
        self.calls.append({"url": url, "headers": headers or {}, "allow_redirects": allow_redirects})
        resp = self.responses.get(url, self.default)
        if resp is None:
            resp = _FakeResponse(200, {"data": []})
        if isinstance(resp, Exception):
            raise resp
        return resp


class _Clock:
    def __init__(self, t=1000.0):
        self.t = t

    def __call__(self):
        return self.t

    def advance(self, dt):
        self.t += dt


# ---------- fetch_live_models 加固 ----------

def test_fetch_live_parses_data_ids():
    sess = _FakeSession(default=_FakeResponse(200, {"data": [{"id": "gpt-4o"}, {"id": "gpt-3.5-turbo"}]}))
    ids = mc.fetch_live_models("openai", "https://api.openai.com/v1", "sk-x", session=sess)
    assert ids == ["gpt-4o", "gpt-3.5-turbo"]


def test_fetch_live_appends_models_to_base_not_v1():
    sess = _FakeSession(default=_FakeResponse(200, {"data": [{"id": "claude-x"}]}))
    mc.fetch_live_models("anthropic", "https://api.anthropic.com/v1/", "k", session=sess)
    # base 已含 /v1,只补 /models(不再加一次 /v1),尾斜杠归一
    assert sess.calls[0]["url"] == "https://api.anthropic.com/v1/models"


def test_fetch_live_never_follows_redirect_flag():
    sess = _FakeSession(default=_FakeResponse(200, {"data": []}))
    mc.fetch_live_models("openai", "https://api.openai.com/v1", "sk-x", session=sess)
    assert sess.calls[0]["allow_redirects"] is False


def test_fetch_live_rejects_redirect():
    sess = _FakeSession(default=_FakeResponse(302, {"data": [{"id": "x"}]}))
    with pytest.raises(mc.LiveModelsError, match="redirect"):
        mc.fetch_live_models("openai", "https://api.openai.com/v1", "sk-x", session=sess)


def test_fetch_live_rejects_non_200():
    sess = _FakeSession(default=_FakeResponse(401, {"error": "bad key"}))
    with pytest.raises(mc.LiveModelsError, match="HTTP 401"):
        mc.fetch_live_models("openai", "https://api.openai.com/v1", "sk-x", session=sess)


def test_fetch_live_rejects_oversized_declared_length():
    big = str(mc.MAX_MODELS_BODY_BYTES + 1)
    sess = _FakeSession(default=_FakeResponse(200, {"data": []}, headers={"Content-Length": big}))
    with pytest.raises(mc.LiveModelsError, match="超上限"):
        mc.fetch_live_models("openai", "https://api.openai.com/v1", "sk-x", session=sess)


def test_fetch_live_rejects_oversized_actual_body():
    raw = b'{"data":[]}' + b" " * (mc.MAX_MODELS_BODY_BYTES + 10)
    sess = _FakeSession(default=_FakeResponse(200, raw_content=raw))
    with pytest.raises(mc.LiveModelsError, match="超上限"):
        mc.fetch_live_models("openai", "https://api.openai.com/v1", "sk-x", session=sess)


def test_fetch_live_rejects_bad_json():
    sess = _FakeSession(default=_FakeResponse(200, raw_content=b"not json <html>"))
    with pytest.raises(mc.LiveModelsError, match="JSON"):
        mc.fetch_live_models("openai", "https://api.openai.com/v1", "sk-x", session=sess)


def test_fetch_live_anthropic_uses_xapikey_header():
    sess = _FakeSession(default=_FakeResponse(200, {"data": [{"id": "claude-x"}]}))
    mc.fetch_live_models("anthropic", "https://api.anthropic.com/v1", "secret-key-123", session=sess)
    hdrs = sess.calls[0]["headers"]
    assert hdrs.get("x-api-key") == "secret-key-123"
    assert "anthropic-version" in hdrs


def test_fetch_live_missing_base_or_key_fails_closed():
    sess = _FakeSession(default=_FakeResponse(200, {"data": []}))
    with pytest.raises(mc.LiveModelsError, match="base_url"):
        mc.fetch_live_models("openai", "", "sk-x", session=sess)
    with pytest.raises(mc.LiveModelsError, match="api_key"):
        mc.fetch_live_models("openai", "https://api.openai.com/v1", "", session=sess)
    assert sess.calls == []  # 缺前置条件时根本不发请求


# ---------- assemble：非聊天不可选 / 订阅无工具 ----------

def test_assemble_live_marks_non_chat_not_selectable():
    entries = mc.assemble_live_entries(
        "openai", ["gpt-4o", "text-embedding-3-large", "o1", "dall-e-3", "whisper-1"]
    )
    by = {e.model: e for e in entries}
    assert by["gpt-4o"].selectable is True and by["gpt-4o"].supports_tools is True
    assert by["o1"].selectable is True
    assert by["text-embedding-3-large"].selectable is False
    assert by["dall-e-3"].selectable is False
    assert by["whisper-1"].selectable is False
    assert by["text-embedding-3-large"].unavailable_reason  # 有说明


def test_assemble_curated_subscription_no_tools():
    entries = mc.assemble_curated_entries("anthropic", auth_kind="subscription_cli", source="curated")
    assert entries and all(e.supports_tools is False for e in entries)
    assert all(e.source == "curated" and e.selectable for e in entries)
    assert all(e.auth_kind == "subscription_cli" for e in entries)


def test_assemble_curated_apikey_fallback_keeps_tools():
    entries = mc.assemble_curated_entries("openai", auth_kind="api_key", source="curated_fallback")
    assert entries and all(e.supports_tools is True for e in entries)
    assert all(e.source == "curated_fallback" for e in entries)


# ---------- list_models 编排 ----------

def _status(provider, configured=False, base_url="", model=""):
    return {"provider": provider, "configured": configured, "base_url": base_url, "model": model}


def test_list_models_unauthed_provider_no_live_request():
    sess = _FakeSession(default=_FakeResponse(200, {"data": [{"id": "gpt-4o"}]}))
    cat = mc.ModelCatalog(session=sess, now=_Clock())
    out = cat.list_models(
        providers_status=[_status("openai", configured=False)],
        subscription_status={"openai": False},
        key_lookup=lambda p: "should-not-be-used",
    )
    row = {r["provider"]: r for r in out}["openai"]
    assert row["authed"] is False and row["selectable"] is False and row["models"] == []
    assert sess.calls == []  # 未认证：零 live 请求


def test_list_models_subscription_only_curated():
    sess = _FakeSession(default=_FakeResponse(200, {"data": [{"id": "should-not-fetch"}]}))
    cat = mc.ModelCatalog(session=sess, now=_Clock())
    out = cat.list_models(
        providers_status=[_status("anthropic", configured=False)],
        subscription_status={"anthropic": True},
        key_lookup=lambda p: "",
    )
    row = {r["provider"]: r for r in out}["anthropic"]
    assert row["authed"] is True and row["auth_kind"] == "subscription_cli"
    assert row["source"] == "curated"
    assert row["models"] and all(m["supports_tools"] is False for m in row["models"])
    assert sess.calls == []  # 订阅路径不打厂商 /models


def test_list_models_api_key_live_source():
    url = "https://api.openai.com/v1/models"
    sess = _FakeSession(responses={url: _FakeResponse(200, {"data": [{"id": "gpt-4o"}, {"id": "text-embedding-3"}]})})
    cat = mc.ModelCatalog(session=sess, now=_Clock())
    out = cat.list_models(
        providers_status=[_status("openai", configured=True, base_url="https://api.openai.com/v1")],
        subscription_status={},
        key_lookup=lambda p: "sk-real",
    )
    row = {r["provider"]: r for r in out}["openai"]
    assert row["auth_kind"] == "api_key" and row["source"] == "live"
    ids = {m["model"]: m for m in row["models"]}
    assert ids["gpt-4o"]["selectable"] is True
    assert ids["text-embedding-3"]["selectable"] is False


def test_list_models_live_failure_falls_back_to_curated_fallback():
    sess = _FakeSession(default=requests.ConnectionError("boom"))
    cat = mc.ModelCatalog(session=sess, now=_Clock())
    out = cat.list_models(
        providers_status=[_status("openai", configured=True, base_url="https://api.openai.com/v1")],
        subscription_status={},
        key_lookup=lambda p: "sk-real",
    )
    row = {r["provider"]: r for r in out}["openai"]
    assert row["authed"] is True
    assert all(m["source"] == "curated_fallback" for m in row["models"])
    assert all(m["supports_tools"] is True for m in row["models"])  # api-key 路径仍支持 tools


def test_cache_hit_avoids_second_fetch():
    url = "https://api.openai.com/v1/models"
    sess = _FakeSession(responses={url: _FakeResponse(200, {"data": [{"id": "gpt-4o"}]})})
    clk = _Clock()
    cat = mc.ModelCatalog(session=sess, now=clk)
    args = dict(
        providers_status=[_status("openai", configured=True, base_url="https://api.openai.com/v1")],
        subscription_status={},
        key_lookup=lambda p: "sk-real",
    )
    cat.list_models(**args)
    cat.list_models(**args)
    assert len(sess.calls) == 1  # 第二次命中缓存,不重拉


def test_cache_expires_after_ttl():
    url = "https://api.openai.com/v1/models"
    sess = _FakeSession(responses={url: _FakeResponse(200, {"data": [{"id": "gpt-4o"}]})})
    clk = _Clock()
    cat = mc.ModelCatalog(session=sess, now=clk, live_ttl=300.0)
    args = dict(
        providers_status=[_status("openai", configured=True, base_url="https://api.openai.com/v1")],
        subscription_status={},
        key_lookup=lambda p: "sk-real",
    )
    cat.list_models(**args)
    clk.advance(301.0)
    cat.list_models(**args)
    assert len(sess.calls) == 2  # TTL 过期后重拉


def test_cache_invalidate_forces_refetch():
    url = "https://api.openai.com/v1/models"
    sess = _FakeSession(responses={url: _FakeResponse(200, {"data": [{"id": "gpt-4o"}]})})
    cat = mc.ModelCatalog(session=sess, now=_Clock())
    args = dict(
        providers_status=[_status("openai", configured=True, base_url="https://api.openai.com/v1")],
        subscription_status={},
        key_lookup=lambda p: "sk-real",
    )
    cat.list_models(**args)
    cat.invalidate()
    cat.list_models(**args)
    assert len(sess.calls) == 2


def test_cache_config_revision_change_refetches():
    sess = _FakeSession(default=_FakeResponse(200, {"data": [{"id": "gpt-4o"}]}))
    cat = mc.ModelCatalog(session=sess, now=_Clock())
    cat.list_models(
        providers_status=[_status("openai", configured=True, base_url="https://api.openai.com/v1", model="gpt-4o")],
        subscription_status={},
        key_lookup=lambda p: "sk-real",
    )
    # 换 model → config_revision 变 → 新缓存桶 → 重拉
    cat.list_models(
        providers_status=[_status("openai", configured=True, base_url="https://api.openai.com/v1", model="gpt-5")],
        subscription_status={},
        key_lookup=lambda p: "sk-real",
    )
    assert len(sess.calls) == 2


def test_no_api_key_in_result_or_cached_entries():
    url = "https://api.openai.com/v1/models"
    sess = _FakeSession(responses={url: _FakeResponse(200, {"data": [{"id": "gpt-4o"}]})})
    cat = mc.ModelCatalog(session=sess, now=_Clock())
    secret = "sk-super-secret-should-never-surface"
    out = cat.list_models(
        providers_status=[_status("openai", configured=True, base_url="https://api.openai.com/v1")],
        subscription_status={},
        key_lookup=lambda p: secret,
    )
    blob = json.dumps(out)
    assert secret not in blob  # 返回体不含 key
    # 缓存内部也不含 key
    for slot in cat._cache.values():
        assert secret not in json.dumps([e.to_dict() for e in slot.entries])
