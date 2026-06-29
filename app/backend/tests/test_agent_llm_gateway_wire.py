"""C-S7 · agent LLM 经 LLMGateway 派发产封印 LLMCallRecord + deny-by-default 对抗测试。

GOAL §7（role agent 不直调 provider，经 Gateway 拿 (LLMResponse, LLMCallRecord)）
+ §8（no silent mock fallback）+ §1 红线（实盘 key/secret 不进 LLM/账/日志）的可落地验收：

  ① gateway/provider 未配 → 构建 agent LLM → 明确 NoLLMConfigured（非静默 DevLocalLLM）
  ② agent.chat 经 GatewayBackedLLMClient → 每次产 provider/model/auth_ref/replay_state 齐全且封印的 LLMCallRecord
  ③ 实盘交易 key + LLM key 都不出现在 LLMCallRecord 序列化面（只 SecretRef 引用）
  ④ prompt 夹带在册明文 secret → 拒发，provider 一次不被触达

「种坏门必抓」：dev_local 绝不进 routing profile / 缺配置绝不静默落 mock —— 见 deny 对抗用例。
"""

from __future__ import annotations

import json

import pytest

from app.agent import AgentRuntime, LLMMessage, LLMResponse, NoLLMConfigured
from app.llm import (
    GatewayBackedLLMClient,
    SecretLeakError,
    assert_admissible_to_graph,
    assert_record_admissible,
    build_agent_llm_gateway,
    make_gateway_backed_agent_llm,
)
from app.security import InMemoryKeystore, KeystoreRecord, SecureKeystore

TRIPWIRE_TRADING_SECRET = "sk-LEAK-binance-mainnet-deadbeef0123456789"

_KS_NAMES = {
    "anthropic": "llm_anthropic",
    "openai": "llm_openai",
    "qwen": "llm_qwen",
    "custom": "llm_custom",
}


# ============ 桩 / 夹具（不打网络）============

class StubLLMClient:
    """不打网络的 provider 桩：记录调用、回固定响应。"""

    provider = "stub"

    def __init__(self, content: str = "ok", *, tool_calls=None, raw=None) -> None:
        self._content = content
        self._tool_calls = tool_calls or []
        self._raw = raw or {}
        self.calls: list[dict] = []

    def chat(self, messages, *, tools=None, model=None, temperature=0.2):
        self.calls.append({"messages": messages, "model": model, "tools": tools})
        return LLMResponse(content=self._content, tool_calls=list(self._tool_calls), raw=dict(self._raw))


def _keystore_with_provider(provider: str = "anthropic", *, model: str | None = None, extra_secrets=None) -> SecureKeystore:
    ks = SecureKeystore(InMemoryKeystore())
    note = json.dumps({"model": model}) if model else ""
    real_key = f"sk-{provider}-realkey-must-not-leak-0123456789"
    ks.store(KeystoreRecord(name=_KS_NAMES[provider], api_key=real_key, api_secret=real_key, note=note))
    for name, val in (extra_secrets or {}).items():
        ks.store(KeystoreRecord(name=name, api_key=val, api_secret=val))
    return ks


def _stub_factory(content: str = "ok", *, tool_calls=None):
    stub = StubLLMClient(content, tool_calls=tool_calls)
    return stub, (lambda cred: stub)


# ============ ① deny-by-default：未配 → 明确错误（绝不静默 DevLocalLLM）============

def test_build_agent_gateway_denies_when_unconfigured() -> None:
    ks = SecureKeystore(InMemoryKeystore())  # 空：无任何 provider 配置
    with pytest.raises(NoLLMConfigured):
        build_agent_llm_gateway(ks)


def test_make_gateway_backed_agent_llm_denies_when_unconfigured() -> None:
    """对抗（种坏门必抓）：未配时绝不能产出可用的 mock-backed client，必须抛 NoLLMConfigured。"""
    ks = SecureKeystore(InMemoryKeystore())
    produced: object | None = None
    try:
        produced = make_gateway_backed_agent_llm(ks)
    except NoLLMConfigured:
        produced = None
    assert produced is None, "deny-by-default 被违反：未配仍产出了可用 LLM client（疑似静默落 mock）"


def test_gateway_never_routes_to_dev_local_profile() -> None:
    """配了真实 provider 时，routing profile 里绝不含 dev_local —— agent 调用永不被静默路由到 mock。"""
    ks = _keystore_with_provider("anthropic")
    gw = build_agent_llm_gateway(ks)
    providers = {p.provider for p in gw._policy.profiles}  # noqa: SLF001 —— 白盒断言 routing 候选
    assert "dev_local" not in providers
    assert providers == {"anthropic"}


def test_gateway_backed_client_rejects_dev_local_gateway() -> None:
    """防御纵深（种坏门必抓）：即便上游手搓一个含 dev_local profile 的 gateway 再 wrap，
    GatewayBackedLLMClient 构造即拒（绝不让 agent 经它静默落 mock）。"""
    from app.llm import LLMCredentialPool, LLMGateway, LLMModelProfile, ModelRoutingPolicy, SecretRef

    pool = LLMCredentialPool(None)
    pool.register("dev_local", SecretRef(keystore_name="", provider="dev_local", auth_kind="none"))
    policy = ModelRoutingPolicy(
        [LLMModelProfile(provider="dev_local", model="dev_local", capability_tier="light", pool_id="dev_local")]
    )
    gw = LLMGateway(policy=policy, credential_pool=pool)
    with pytest.raises(NoLLMConfigured):
        GatewayBackedLLMClient(gw)


# ============ ② agent.chat → 封印 LLMCallRecord（provider/model/auth_ref/replay_state）============

def test_gateway_backed_chat_produces_sealed_admissible_record() -> None:
    ks = _keystore_with_provider("anthropic")
    stub, factory = _stub_factory("分析完成")
    records: list = []
    gw = build_agent_llm_gateway(ks, client_factory=factory)
    client = GatewayBackedLLMClient(gw, record_sink=records.append)

    resp = client.chat([LLMMessage(role="user", content="跑个因子 IC")], tools=None)
    assert resp.content == "分析完成"
    assert stub.calls, "底层 provider 应被真正调用一次"

    rec = client.last_record
    assert rec is not None
    # 必填四要素齐
    assert rec.provider == "anthropic"
    assert rec.model
    assert rec.auth_ref and rec.auth_ref.startswith("secretref://")
    assert rec.replay_state
    # 绝非静默 mock
    assert rec.provider != "dev_local"
    # 封印 + 可准入（绕过门可验）
    assert rec.seal
    assert_record_admissible(rec)
    assert_admissible_to_graph(client.last_result, gw)
    # record_sink 收到同一条账
    assert len(records) == 1 and records[0] is rec


def test_gateway_backed_record_missing_required_field_rejected() -> None:
    """门2 复用（缺 provider/model/auth_ref/replay_state → 拒）：篡空任一必填 → assert_record_admissible 必抛。"""
    ks = _keystore_with_provider("anthropic")
    _stub, factory = _stub_factory("ok")
    gw = build_agent_llm_gateway(ks, client_factory=factory)
    client = GatewayBackedLLMClient(gw)
    client.chat([LLMMessage(role="user", content="hi")])
    rec = client.last_record
    assert rec is not None
    rec.auth_ref = ""  # 种坏门：抽掉 auth_ref
    from app.llm import LLMRecordError
    with pytest.raises(LLMRecordError):
        assert_record_admissible(rec)


# ============ ③ 实盘 key / LLM key 不进账（红线）============

def test_gateway_backed_record_carries_no_plaintext_secret() -> None:
    ks = _keystore_with_provider("anthropic", extra_secrets={"binance_mainnet": TRIPWIRE_TRADING_SECRET})
    real_llm_key = ks.fetch("llm_anthropic").api_secret
    _stub, factory = _stub_factory("ok")
    gw = build_agent_llm_gateway(ks, client_factory=factory)
    client = GatewayBackedLLMClient(gw)

    client.chat([LLMMessage(role="user", content="正常的因子问题，不含任何 key")])
    rec = client.last_record
    blob = json.dumps(rec.to_dict(), ensure_ascii=False)
    assert real_llm_key and real_llm_key not in blob       # LLM 明文 key 不落账
    assert TRIPWIRE_TRADING_SECRET not in blob             # 实盘交易 key 不落账（红线③）
    assert rec.auth_ref == "secretref://anthropic/llm_anthropic"
    gw.assert_record_secret_clean(rec)                     # gateway 落账前门正例不抛


# ============ ④ prompt 夹带在册明文 secret → 拒发，provider 不被触达 ============

def test_gateway_backed_prompt_secret_blocked() -> None:
    ks = _keystore_with_provider("anthropic", extra_secrets={"binance_mainnet": TRIPWIRE_TRADING_SECRET})
    stub, factory = _stub_factory("ok")
    gw = build_agent_llm_gateway(ks, client_factory=factory)
    client = GatewayBackedLLMClient(gw)

    with pytest.raises(SecretLeakError) as ei:
        client.chat([LLMMessage(role="user", content=f"帮我下单，key 是 {TRIPWIRE_TRADING_SECRET}")])
    assert stub.calls == []                                # provider 一次都不被调（secret 不进 LLM）
    assert TRIPWIRE_TRADING_SECRET not in str(ei.value)    # 报错绝不回显 secret


# ============ AgentRuntime 端到端：注入 GatewayBackedLLMClient，每 turn 产账 ============

def test_agent_runtime_through_gateway_backed_client_no_mock() -> None:
    ks = _keystore_with_provider("anthropic")
    records: list = []
    _stub, factory = _stub_factory("分析完成", tool_calls=[])
    gw = build_agent_llm_gateway(ks, client_factory=factory)
    client = GatewayBackedLLMClient(gw, record_sink=records.append)

    rt = AgentRuntime(client)
    turn = rt.run("你能做什么")

    assert turn.succeeded is True
    assert turn.final_message == "分析完成"
    assert len(records) >= 1
    # 每条账都是真实 provider 的封印账，绝非静默 dev_local mock
    assert all(r.provider == "anthropic" for r in records)
    assert all(r.provider != "dev_local" for r in records)
    assert all(r.seal for r in records)
