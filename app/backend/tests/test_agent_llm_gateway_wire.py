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
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from itertools import count

import pytest

from app.agent import AgentRuntime, LLMMessage, LLMResponse, NoLLMConfigured
from app.llm import (
    GatewayBackedLLMClient,
    GatewayError,
    LLMRecordError,
    PersistentLLMUseBindingStore,
    SecretLeakError,
    assert_admissible_to_graph,
    assert_record_admissible,
    build_agent_llm_gateway,
    make_call_id,
    make_gateway_backed_agent_llm,
    seal_record,
)
from app.lineage.ids import canonical_json
from app.llm.call_record_store import LLMCallRecordStore
from app.security import InMemoryKeystore, KeystoreRecord, SecureKeystore

TRIPWIRE_TRADING_SECRET = "sk-LEAK-binance-mainnet-deadbeef0123456789"
_TEST_SEAL = b"wire-test-seal-key" * 2
_INVOCATIONS = count(1)

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


def _client(gw, *, record_sink=None, session_id="agent", owner_user_id="owner-wire") -> GatewayBackedLLMClient:
    return GatewayBackedLLMClient(
        gw,
        session_id=session_id,
        owner_user_id=owner_user_id,
        workflow_id=session_id,
        invocation_id_factory=lambda: f"wire-inv-{next(_INVOCATIONS)}",
        record_sink=record_sink,
    )


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
    gw = build_agent_llm_gateway(ks, client_factory=factory, seal_secret=_TEST_SEAL)
    client = _client(gw, record_sink=records.append)

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
    assert [r.record_kind for r in records] == ["attempt", "terminal"]
    assert records[-1] is rec


def test_gateway_record_sink_persists_and_resolves_for_promote_assembly(tmp_path) -> None:
    """LLMCallRecord durable sink：gateway 产封印账 → JSONL 落盘 → promote assembler 按 run_id 读回。"""

    ks = _keystore_with_provider("anthropic")
    stub, factory = _stub_factory("分析完成")
    store = LLMCallRecordStore(tmp_path / "audit" / "llm_call_records.jsonl")
    gw = build_agent_llm_gateway(ks, client_factory=factory, seal_secret=store.seal_secret)
    client = _client(gw, session_id="run::llm-audit", record_sink=store.append)

    client.chat([LLMMessage(role="user", content="PROMPT_TEXT_MUST_NOT_PERSIST")], tools=None)
    assert stub.calls
    rows = store.llm_records_for("run::llm-audit", owner_user_id="owner-wire")
    assert [row.record_kind for row in rows] == ["attempt", "terminal"]
    assert rows[-1].call_id == client.last_record.call_id
    assert all(row.seal for row in rows)
    assert "PROMPT_TEXT_MUST_NOT_PERSIST" not in store.path.read_text(encoding="utf-8")


def test_agent_gateway_factory_binds_only_configured_runtime_provider(tmp_path) -> None:
    ks = _keystore_with_provider("anthropic")
    stub, factory = _stub_factory("bound")
    call_store = LLMCallRecordStore(tmp_path / "audit" / "llm_call_records.jsonl")
    binding_store = PersistentLLMUseBindingStore(
        tmp_path / "audit" / "llm_gateway_use_bindings.jsonl",
        seal_secret=call_store.seal_secret,
        terminal_record_resolver=call_store.resolve_terminal_record,
    )
    gateway = build_agent_llm_gateway(
        ks,
        client_factory=factory,
        seal_secret=call_store.seal_secret,
        use_binding_sink=binding_store.append,
        service_principal_ref="service:local-llm-gateway",
        credential_pool_refs={
            "anthropic": "pool:llm:anthropic:default",
            "openai": "pool:llm:openai:default",
        },
        routing_policy_refs={
            "anthropic": "routing:llm:anthropic:default",
            "openai": "routing:llm:openai:default",
        },
    )
    client = _client(gateway, record_sink=call_store.append)

    assert client.chat([LLMMessage(role="user", content="safe binding request")]).content == "bound"
    binding = binding_store.binding_for_terminal(
        client.last_record.call_id,
        owner_user_id="owner-wire",
    )
    assert binding.provider_ref == "anthropic"
    assert binding.credential_pool_ref == "pool:llm:anthropic:default"
    assert binding.routing_policy_ref == "routing:llm:anthropic:default"
    assert binding.service_principal_ref == "service:local-llm-gateway"
    assert stub.calls


def test_gateway_backed_record_missing_required_field_rejected() -> None:
    """门2 复用（缺 provider/model/auth_ref/replay_state → 拒）：篡空任一必填 → assert_record_admissible 必抛。"""
    ks = _keystore_with_provider("anthropic")
    _stub, factory = _stub_factory("ok")
    gw = build_agent_llm_gateway(ks, client_factory=factory)
    client = _client(gw)
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
    client = _client(gw)

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
    client = _client(gw)

    with pytest.raises(SecretLeakError) as ei:
        client.chat([LLMMessage(role="user", content=f"帮我下单，key 是 {TRIPWIRE_TRADING_SECRET}")])
    assert stub.calls == []                                # provider 一次都不被调（secret 不进 LLM）
    assert TRIPWIRE_TRADING_SECRET not in str(ei.value)    # 报错绝不回显 secret


# ============ AgentRuntime 端到端：注入 GatewayBackedLLMClient，每 turn 产账 ============

def test_agent_runtime_through_gateway_backed_client_no_mock() -> None:
    ks = _keystore_with_provider("anthropic")
    records: list = []
    _stub, factory = _stub_factory("分析完成", tool_calls=[])
    gw = build_agent_llm_gateway(ks, client_factory=factory, seal_secret=_TEST_SEAL)
    client = _client(gw, record_sink=records.append)

    rt = AgentRuntime(client)
    turn = rt.run("你能做什么")

    assert turn.succeeded is True
    assert turn.final_message == "分析完成"
    assert len(records) >= 1
    # 每条账都是真实 provider 的封印账，绝非静默 dev_local mock
    assert all(r.provider == "anthropic" for r in records)
    assert all(r.provider != "dev_local" for r in records)
    assert all(r.seal for r in records)


def test_store_restart_owner_isolation_and_no_plaintext(tmp_path) -> None:
    path = tmp_path / "audit" / "llm.jsonl"
    store = LLMCallRecordStore(path)
    ks = _keystore_with_provider("anthropic")
    llm_key = ks.fetch("llm_anthropic").api_secret

    stub_a, factory_a = _stub_factory("OUTPUT_MARKER_MUST_NOT_PERSIST")
    gw_a = build_agent_llm_gateway(ks, client_factory=factory_a, seal_secret=store.seal_secret)
    client_a = _client(
        gw_a,
        owner_user_id="owner-a",
        session_id="workflow-shared",
        record_sink=store.append,
    )
    client_a.chat([LLMMessage(role="user", content="PROMPT_MARKER_MUST_NOT_PERSIST")])
    assert stub_a.calls
    with pytest.raises(SecretLeakError):
        client_a.chat([LLMMessage(role="user", content=f"blocked secret {llm_key}")])

    _stub_b, factory_b = _stub_factory("owner-b-output")
    gw_b = build_agent_llm_gateway(ks, client_factory=factory_b, seal_secret=store.seal_secret)
    client_b = _client(
        gw_b,
        owner_user_id="owner-b",
        session_id="workflow-shared",
        record_sink=store.append,
    )
    client_b.chat([LLMMessage(role="user", content="owner-b-prompt")])

    owner_a_rows = store.read_all(owner_user_id="owner-a")
    assert len(owner_a_rows) == 3
    assert (owner_a_rows[-1].record_kind, owner_a_rows[-1].status) == ("terminal", "refused")
    assert owner_a_rows[-1].provider == ""
    assert len(store.read_all(owner_user_id="owner-b")) == 2
    assert store.read_all(owner_user_id="owner-missing") == []
    with pytest.raises(LLMRecordError):
        store.read_all(owner_user_id="")

    restarted = LLMCallRecordStore(path)
    assert [r.call_id for r in restarted.read_all(owner_user_id="owner-a")] == [
        r.call_id for r in store.read_all(owner_user_id="owner-a")
    ]
    blob = path.read_text(encoding="utf-8")
    assert "PROMPT_MARKER_MUST_NOT_PERSIST" not in blob
    assert "OUTPUT_MARKER_MUST_NOT_PERSIST" not in blob
    assert llm_key and llm_key not in blob
    assert "base_url_redacted" not in blob
    assert "fallback_chain" not in blob

    with pytest.raises(LLMRecordError):
        LLMCallRecordStore(path, seal_secret=b"wrong-key" * 4)


def test_store_exact_retry_collision_call_id_and_sequence_gates(tmp_path) -> None:
    store = LLMCallRecordStore(tmp_path / "audit" / "llm.jsonl")
    ks = _keystore_with_provider("anthropic")
    _stub, factory = _stub_factory("ok")
    gw = build_agent_llm_gateway(ks, client_factory=factory, seal_secret=store.seal_secret)
    client = _client(gw, session_id="sequence-workflow", record_sink=store.append)
    client.chat([LLMMessage(role="user", content="safe prompt")])
    rows = store.read_all(owner_user_id="owner-wire")
    assert len(rows) == 2

    before = store.path.read_text(encoding="utf-8")
    assert store.append(rows[0]).call_id == rows[0].call_id
    assert store.path.read_text(encoding="utf-8") == before

    divergent = replace(
        rows[0],
        prompt_digest="fedcba9876543210",
        prompt_hash="fedcba9876543210",
    )
    divergent.seal = seal_record(divergent, store.seal_secret)
    with pytest.raises(LLMRecordError, match="collision"):
        store.append(divergent)

    bad_id = replace(rows[0], call_id="0" * 16)
    bad_id.seal = seal_record(bad_id, store.seal_secret)
    with pytest.raises(LLMRecordError, match="call_id"):
        store.append(bad_id)

    out_of_order = replace(
        rows[0],
        invocation_id="new-invocation",
        attempt_no=2,
        call_id=make_call_id(
            prompt_digest="", provider="", model="", role="", session_id="", seq=2,
            owner_user_id=rows[0].owner_user_id,
            workflow_id=rows[0].workflow_id,
            invocation_id="new-invocation",
            record_kind="attempt",
            attempt_no=2,
        ),
    )
    out_of_order.seal = seal_record(out_of_order, store.seal_secret)
    with pytest.raises(LLMRecordError, match="contiguous"):
        store.append(out_of_order)


def test_store_checkpoint_rejects_valid_prefix_rollback(tmp_path) -> None:
    path = tmp_path / "audit" / "rollback.jsonl"
    store = LLMCallRecordStore(path)
    ks = _keystore_with_provider("anthropic")
    _stub, factory = _stub_factory("ok")
    gw = build_agent_llm_gateway(ks, client_factory=factory, seal_secret=store.seal_secret)
    _client(gw, session_id="rollback-workflow", record_sink=store.append).chat(
        [LLMMessage(role="user", content="safe")]
    )

    lines = path.read_bytes().splitlines(keepends=True)
    assert len(lines) == 2
    path.write_bytes(b"".join(lines[:-1]))

    with pytest.raises(LLMRecordError, match="checkpoint"):
        LLMCallRecordStore(path)

    store.checkpoint_path.unlink()
    with pytest.raises(LLMRecordError, match="missing its durable checkpoint"):
        LLMCallRecordStore(path)


@pytest.mark.parametrize("failed_fsync_call", [1, 2])
def test_store_append_fsync_failure_rolls_back_without_partial_record(
    tmp_path,
    monkeypatch,
    failed_fsync_call,
) -> None:
    import app.llm.call_record_store as store_module

    path = tmp_path / "audit" / f"fsync-{failed_fsync_call}.jsonl"
    store = LLMCallRecordStore(path)
    before_journal = path.read_bytes()
    before_checkpoint = store.checkpoint_path.read_bytes()
    ks = _keystore_with_provider("anthropic")
    stub, factory = _stub_factory("provider-output")
    gw = build_agent_llm_gateway(ks, client_factory=factory, seal_secret=store.seal_secret)
    client = _client(
        gw,
        session_id="fsync-workflow",
        record_sink=lambda record: store.append(record),
    )
    real_fsync = store_module.os.fsync
    calls = 0

    def injected_fsync(fd):
        nonlocal calls
        calls += 1
        if calls == failed_fsync_call:
            raise OSError("injected fsync failure")
        return real_fsync(fd)

    monkeypatch.setattr(store_module.os, "fsync", injected_fsync)
    with pytest.raises(OSError, match="injected fsync failure"):
        client.chat([LLMMessage(role="user", content="safe")])

    assert len(stub.calls) == 1
    assert path.read_bytes() == before_journal
    assert store.checkpoint_path.read_bytes() == before_checkpoint
    assert store.read_all(owner_user_id="owner-wire") == []


def test_store_rejects_unsafe_provider_model_auth_ref_and_bad_terminal(tmp_path) -> None:
    source = LLMCallRecordStore(tmp_path / "audit" / "source.jsonl")
    ks = _keystore_with_provider("anthropic")
    _stub, factory = _stub_factory("ok")
    gw = build_agent_llm_gateway(ks, client_factory=factory, seal_secret=source.seal_secret)
    _client(gw, session_id="source-workflow", record_sink=source.append).chat(
        [LLMMessage(role="user", content="safe")]
    )
    attempt, terminal = source.read_all(owner_user_id="owner-wire")

    for field, value, match in (
        ("provider", "https://evil.example/v1", "provider"),
        ("model", "https://evil.example/model", "model"),
        ("auth_ref", "sk-PLAINTEXT-SECRET-1234567890", "SecretRef"),
    ):
        unsafe_store = LLMCallRecordStore(
            tmp_path / "audit" / f"unsafe-{field}.jsonl",
            seal_secret=source.seal_secret,
        )
        changed = replace(attempt, invocation_id=f"unsafe-{field}", **{field: value})
        changed.call_id = make_call_id(
            prompt_digest="", provider="", model="", role="", session_id="", seq=1,
            owner_user_id=changed.owner_user_id,
            workflow_id=changed.workflow_id,
            invocation_id=changed.invocation_id,
            record_kind=changed.record_kind,
            attempt_no=changed.attempt_no,
        )
        changed.seal = seal_record(changed, source.seal_secret)
        with pytest.raises(LLMRecordError, match=match):
            unsafe_store.append(changed)

    sequence_store = LLMCallRecordStore(
        tmp_path / "audit" / "bad-terminal.jsonl",
        seal_secret=source.seal_secret,
    )
    sequence_store.append(attempt)
    contradictory = replace(
        terminal,
        status="error",
        error_kind="synthetic_error",
        failure_stage="provider",
        response_digest="",
        response_ref="",
    )
    contradictory.seal = seal_record(contradictory, source.seal_secret)
    with pytest.raises(LLMRecordError, match="successful provider attempt"):
        sequence_store.append(contradictory)


def test_store_bound_gateway_restart_rejects_duplicate_before_provider(tmp_path) -> None:
    store = LLMCallRecordStore(tmp_path / "audit" / "restart-idempotency.jsonl")
    ks = _keystore_with_provider("anthropic")
    first_stub, first_factory = _stub_factory("first")
    first_gateway = build_agent_llm_gateway(
        ks,
        client_factory=first_factory,
        seal_secret=store.seal_secret,
    )
    first_client = GatewayBackedLLMClient(
        first_gateway,
        owner_user_id="owner-wire",
        workflow_id="restart-workflow",
        invocation_id_factory=lambda: "stable-invocation",
        record_sink=store.append,
    )
    first_client.chat([LLMMessage(role="user", content="safe")])
    assert len(first_stub.calls) == 1

    second_stub, second_factory = _stub_factory("second")
    second_gateway = build_agent_llm_gateway(
        ks,
        client_factory=second_factory,
        seal_secret=store.seal_secret,
    )
    second_client = GatewayBackedLLMClient(
        second_gateway,
        owner_user_id="owner-wire",
        workflow_id="restart-workflow",
        invocation_id_factory=lambda: "stable-invocation",
        record_sink=store.append,
    )
    with pytest.raises(LLMRecordError, match="durable audit evidence"):
        second_client.chat([LLMMessage(role="user", content="safe")])
    assert second_stub.calls == []
    assert len(store.read_all(owner_user_id="owner-wire")) == 2


def test_store_cross_process_same_invocation_calls_provider_once(tmp_path) -> None:
    import multiprocessing
    import os

    if "fork" not in multiprocessing.get_all_start_methods():
        pytest.skip("same-invocation process race probe requires fork")
    path = tmp_path / "audit" / "process-idempotency.jsonl"
    marker = tmp_path / "provider.calls"
    LLMCallRecordStore(path)

    def worker() -> None:
        store = LLMCallRecordStore(path)
        ks = _keystore_with_provider("anthropic")

        class MarkerClient:
            def chat(self, *args, **kwargs):
                fd = os.open(marker, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
                try:
                    os.write(fd, b"called\n")
                    os.fsync(fd)
                finally:
                    os.close(fd)
                return LLMResponse(content="ok")

        gateway = build_agent_llm_gateway(
            ks,
            client_factory=lambda cred: MarkerClient(),
            seal_secret=store.seal_secret,
        )
        client = GatewayBackedLLMClient(
            gateway,
            owner_user_id="owner-wire",
            workflow_id="process-workflow",
            invocation_id_factory=lambda: "same-process-invocation",
            record_sink=store.append,
        )
        try:
            client.chat([LLMMessage(role="user", content="safe")])
        except LLMRecordError:
            pass

    context = multiprocessing.get_context("fork")
    processes = [context.Process(target=worker) for _ in range(8)]
    for process in processes:
        process.start()
    for process in processes:
        process.join(10)

    assert [process.exitcode for process in processes] == [0] * len(processes)
    assert marker.read_text(encoding="utf-8").splitlines() == ["called"]
    rows = LLMCallRecordStore(path).read_all(owner_user_id="owner-wire")
    assert [(row.record_kind, row.status) for row in rows] == [
        ("attempt", "ok"),
        ("terminal", "ok"),
    ]


def test_store_checkpoint_hmac_modes_and_symlinks(tmp_path) -> None:
    import stat

    path = tmp_path / "audit" / "secure.jsonl"
    store = LLMCallRecordStore(path)
    key_path = path.with_name("." + path.name + ".seal.key")
    lock_path = path.with_name(path.name + ".lock")
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert stat.S_IMODE(store.checkpoint_path.stat().st_mode) == 0o600
    assert stat.S_IMODE(key_path.stat().st_mode) == 0o600
    assert stat.S_IMODE(lock_path.stat().st_mode) == 0o600

    checkpoint = json.loads(store.checkpoint_path.read_text(encoding="utf-8"))
    checkpoint["size"] = 1
    store.checkpoint_path.write_text(
        canonical_json(checkpoint) + "\n",
        encoding="utf-8",
    )
    with pytest.raises(LLMRecordError, match="HMAC"):
        LLMCallRecordStore(path)

    target = tmp_path / "target"
    target.write_text("x", encoding="utf-8")
    journal_link = tmp_path / "journal-link.jsonl"
    journal_link.symlink_to(target)
    with pytest.raises(LLMRecordError, match="non-symlink"):
        LLMCallRecordStore(journal_link)

    key_link_journal = tmp_path / "key-link.jsonl"
    key_link = key_link_journal.with_name("." + key_link_journal.name + ".seal.key")
    key_link.symlink_to(target)
    with pytest.raises(LLMRecordError, match="seal key"):
        LLMCallRecordStore(key_link_journal)


def test_store_concurrent_first_key_creation_and_v1_quarantine(tmp_path) -> None:
    path = tmp_path / "audit" / "concurrent.jsonl"

    def open_store(_: int) -> bytes:
        return LLMCallRecordStore(path).seal_secret

    with ThreadPoolExecutor(max_workers=8) as pool:
        keys = list(pool.map(open_store, range(16)))
    assert len(set(keys)) == 1
    assert len(keys[0]) >= 32

    legacy_path = tmp_path / "audit" / "legacy.jsonl"
    legacy_path.write_text(
        canonical_json({
            "provider": "anthropic",
            "model": "legacy-model",
            "auth_ref": "secretref://anthropic/legacy",
            "replay_state": "live",
        }) + "\n",
        encoding="utf-8",
    )
    reopened = LLMCallRecordStore(legacy_path)
    assert reopened.quarantined_legacy_rows == 1
    assert reopened.read_all(owner_user_id="owner-a") == []
    assert reopened.checkpoint_path.exists()


def test_store_all_fail_sanitizes_exception_text(tmp_path) -> None:
    path = tmp_path / "audit" / "failure.jsonl"
    store = LLMCallRecordStore(path)
    ks = _keystore_with_provider("anthropic")

    class Boom:
        def chat(self, *args, **kwargs):
            raise RuntimeError("EXCEPTION_MARKER_MUST_NOT_PERSIST sk-RAW-ERROR-SECRET")

    gw = build_agent_llm_gateway(
        ks,
        client_factory=lambda cred: Boom(),
        seal_secret=store.seal_secret,
    )
    client = _client(gw, session_id="failure-workflow", record_sink=store.append)
    with pytest.raises(GatewayError) as ei:
        client.chat([LLMMessage(role="user", content="safe")])
    rows = store.read_all(owner_user_id="owner-wire")
    assert [(r.record_kind, r.status) for r in rows] == [
        ("attempt", "error"), ("terminal", "error")
    ]
    assert ei.value.records == rows
    blob = path.read_text(encoding="utf-8")
    assert "EXCEPTION_MARKER_MUST_NOT_PERSIST" not in blob
    assert "sk-RAW-ERROR-SECRET" not in blob
