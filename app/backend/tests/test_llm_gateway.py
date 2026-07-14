"""LLM Gateway 对抗测试（A-AGENT-GW · GOAL §7/§1 · D-LLM-ROUTING）。

「种一个已知的坏，门必须抓住，否则门是纸做的」（RULES §2）。五道可证伪验收，每道配
正例（well-formed 过）+ 反例（种坏门必抓）+ 关键门的变异测试（MUT：把门拆了，测试必红）：

  门1 绕过 Gateway（未封印/篡改账）→ 不可准入
  门2 LLMCallRecord 缺 provider/model/auth_ref/replay_state → 拒
  门3 明文 secret 进 prompt / 进账 / 进导出 → 拒（只 SecretRef）
  门4 Verifier 独立挑战缺独立性 / 假报独立 → 标独立性不足
  门5 混合自适应：难任务走强模型、绝不静默降质（误路由轻模型 → 必标 / strict 拒）
"""

from __future__ import annotations

import copy
import json
from itertools import count

import pytest

from app.agent.llm_client import LLMMessage, LLMResponse
from app.llm import (
    CallStatus,
    DegradedRoutingError,
    GatewayCapability,
    GatewayError,
    IndependenceRecord,
    LLMCallRecord,
    LLMCredentialPool,
    LLMGateway,
    LLMModelProfile,
    LLMRecordError,
    LLMRequest,
    ModelRoutingPolicy,
    ModelTier,
    ReplayState,
    RiskLevel,
    RoleCapabilityRequest,
    RoutingMode,
    SecretLeakError,
    SecretRef,
    TaskDifficulty,
    assert_admissible_to_graph,
    assert_no_plaintext_secret,
    assert_record_admissible,
    evaluate_independence,
    seal_record,
    verify_record_seal,
)
from app.security import InMemoryKeystore, KeystoreRecord, SecureKeystore
from app.llm.gateway import EV_CALL_FINISHED

TRIPWIRE_SECRET = "sk-LEAK-TRIPWIRE-deadbeef0123456789"
_INVOCATIONS = count(1)
_AUDIT_SEAL = b"llm-gateway-audit-test-key-0001" * 2


# ============ 测试夹具 / 桩 ============

class StubLLMClient:
    """不打网络的 LLMClient 桩：记录调用、回固定响应。"""

    provider = "stub"

    def __init__(self, content: str = "ok", *, tool_calls=None, fixture_key=None, raw=None) -> None:
        self._content = content
        self._tool_calls = tool_calls or []
        self._fixture_key = fixture_key
        self._raw = raw or {}
        self.calls: list[dict] = []

    def chat(self, messages, *, tools=None, model=None, temperature=0.2):
        self.calls.append({"messages": messages, "model": model, "tools": tools})
        r = LLMResponse(content=self._content, tool_calls=list(self._tool_calls), raw=dict(self._raw))
        if self._fixture_key:
            r.fixture_key = self._fixture_key
        return r


def _seed_keystore(profiles, *, extra_secrets=None) -> SecureKeystore:
    ks = SecureKeystore(InMemoryKeystore())
    for p in profiles:
        if p.provider == "dev_local":
            continue
        ks.store(KeystoreRecord(name=p.pool_id, api_key=f"key-{p.pool_id}-xxxxxxxx", api_secret=f"key-{p.pool_id}-xxxxxxxx"))
    for name, val in (extra_secrets or {}).items():
        ks.store(KeystoreRecord(name=name, api_key=val, api_secret=val))
    return ks


def _build_pool(profiles, keystore) -> LLMCredentialPool:
    pool = LLMCredentialPool(keystore)
    for p in profiles:
        if pool.has_pool(p.pool_id):
            continue
        if p.provider == "dev_local":
            pool.register(p.pool_id, SecretRef(keystore_name="", provider="dev_local", auth_kind="none"))
        else:
            pool.register(
                p.pool_id,
                SecretRef(keystore_name=p.pool_id, provider=p.provider, auth_kind="api_key"),
                default_model=p.model,
            )
    return pool


def _gateway(profiles, *, keystore=None, factory=None, strict_degrade=True, mode=RoutingMode.HYBRID_ADAPTIVE,
             scan_prompt_secrets=True, extra_secrets=None, record_sink=None, seal_secret=None):
    ks = keystore if keystore is not None else _seed_keystore(profiles, extra_secrets=extra_secrets)
    pool = _build_pool(profiles, ks)
    policy = ModelRoutingPolicy(profiles, mode=mode)
    if factory is None:
        factory = lambda cred: StubLLMClient(content="stub-resp")  # noqa: E731
    return LLMGateway(
        policy=policy, credential_pool=pool, client_factory=factory,
        strict_degrade=strict_degrade, scan_prompt_secrets=scan_prompt_secrets,
        record_sink=record_sink,
        seal_secret=seal_secret or (_AUDIT_SEAL if record_sink is not None else None),
    )


def _profiles_two_strong():
    return [
        LLMModelProfile(provider="anthropic", model="claude-opus-4", capability_tier=ModelTier.STRONG.value, pool_id="anthropic"),
        LLMModelProfile(provider="openai", model="gpt-4o", capability_tier=ModelTier.STRONG.value, pool_id="openai"),
    ]


def _profiles_mixed():
    return [
        LLMModelProfile(provider="anthropic", model="claude-opus-4", capability_tier=ModelTier.STRONG.value, pool_id="anthropic"),
        LLMModelProfile(provider="openai", model="gpt-4o-mini", capability_tier=ModelTier.LIGHT.value, pool_id="openai"),
        LLMModelProfile(provider="qwen", model="qwen-plus", capability_tier=ModelTier.NORMAL.value, pool_id="qwen"),
    ]


def _req(role="reporter", difficulty="normal", risk="normal", independence=False, session="s1"):
    invocation = f"inv-{next(_INVOCATIONS)}"
    return LLMRequest(
        messages=[LLMMessage(role="user", content="跑个因子 IC")],
        capability=RoleCapabilityRequest(role=role, difficulty=difficulty, risk=risk, independence_required=independence),
        session_id=session,
        owner_user_id="owner-test",
        workflow_id=session,
        invocation_id=invocation,
    )


def _record(**overrides):
    prompt_hash = "1111111111111111"
    response_digest = "0123456789abcdef"
    values = {
        "provider": "anthropic",
        "model": "claude-opus-4",
        "auth_ref": "secretref://anthropic/anthropic",
        "replay_state": ReplayState.LIVE.value,
        "owner_user_id": "owner-test",
        "workflow_id": "workflow-test",
        "invocation_id": f"record-{next(_INVOCATIONS)}",
        "routing_policy_ref": "routing:test:policy:v3",
        "routing_policy_state": "configured_ref",
        "prompt_digest": prompt_hash,
        "prompt_hash": prompt_hash,
        "tool_schema_hash": "2222222222222222",
        "response_digest": response_digest,
        "response_ref": f"llm_response:{response_digest}",
        "latency_ms": 0.0,
        "cost": {
            "status": "unavailable",
            "currency": "USD",
            "amount": None,
            "source": "none",
            "reason": "provider_cost_not_reported",
        },
    }
    values.update(overrides)
    if values["replay_state"] == ReplayState.REPLAYED.value:
        values.setdefault("routing_policy_state", "replay_origin")
        if "routing_policy_state" not in overrides:
            values["routing_policy_state"] = "replay_origin"
    return LLMCallRecord(**values)


# ============ 端到端正例 ============

def test_happy_path_record_sealed_and_admissible():
    persisted = []
    gw = _gateway(_profiles_two_strong(), record_sink=persisted.append)
    res = gw.complete(_req(difficulty="hard"))
    rec = res.record
    assert rec.provider and rec.model and rec.auth_ref and rec.replay_state
    assert rec.schema_version == 3
    assert rec.routing_policy_state == "runtime_digest"
    assert rec.routing_policy_ref.startswith("routing:runtime:")
    assert rec.prompt_hash == rec.prompt_digest
    assert len(rec.tool_schema_hash) == 16
    assert rec.response_ref == f"llm_response:{rec.response_digest}"
    assert rec.cost == {
        "status": "unavailable",
        "currency": "USD",
        "amount": None,
        "source": "none",
        "reason": "provider_cost_not_reported",
    }
    assert rec.latency_ms is not None
    assert rec.auth_ref.startswith("secretref://")
    assert rec.tier_resolved == ModelTier.STRONG.value
    assert gw.verify(res) is True
    assert_admissible_to_graph(res, gw)  # 不抛 = 准入通过
    assert [e.kind for e in res.events][:1] == ["LLMRouteSelected"]
    assert [(r.record_kind, r.status) for r in persisted] == [
        ("attempt", "ok"), ("terminal", "ok")
    ]


def test_v3_uses_configured_routing_ref_and_provider_reported_cost():
    profiles = _profiles_two_strong()
    pool = _build_pool(profiles, _seed_keystore(profiles))
    gw = LLMGateway(
        policy=ModelRoutingPolicy(profiles),
        credential_pool=pool,
        client_factory=lambda cred: StubLLMClient(
            content="costed",
            raw={"usage": {"input_tokens": 10, "cost_usd": 0.0125}},
        ),
        routing_policy_refs={"anthropic": "routing:configured:anthropic:v9"},
    )

    rec = gw.complete(_req(difficulty="hard")).record

    assert rec.routing_policy_ref == "routing:configured:anthropic:v9"
    assert rec.routing_policy_state == "configured_ref"
    assert rec.cost == {
        "status": "reported",
        "currency": "USD",
        "amount": 0.0125,
        "source": "provider_usage_cost_usd",
        "reason": "",
    }


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("routing_policy_ref", ""),
        ("routing_policy_state", "unresolved_pre_route"),
        ("prompt_hash", "ffffffffffffffff"),
        ("tool_schema_hash", ""),
        ("response_ref", "llm_response:ffffffffffffffff"),
        ("cost", {}),
        ("latency_ms", None),
    ],
)
def test_v3_mutated_required_evidence_is_rejected(field, value):
    rec = copy.deepcopy(_gateway(_profiles_two_strong()).complete(_req(difficulty="hard")).record)
    setattr(rec, field, value)

    with pytest.raises(LLMRecordError):
        assert_record_admissible(rec)


def test_sealed_legacy_v2_record_cannot_enter_current_graph():
    gw = _gateway(_profiles_two_strong())
    legacy = LLMCallRecord(
        provider="anthropic",
        model="claude-opus-4",
        auth_ref="secretref://anthropic/anthropic",
        replay_state="live",
        schema_version=2,
        owner_user_id="owner-test",
        workflow_id="legacy-workflow",
        invocation_id="legacy-invocation",
        prompt_digest="1111111111111111",
        response_digest="2222222222222222",
        latency_ms=0.0,
    )
    legacy.seal = seal_record(legacy, gw._seal_secret)  # noqa: SLF001 - migration gate probe.
    from app.llm import GatewaySealedResult

    wrapped = GatewaySealedResult(response=LLMResponse(content="legacy"), record=legacy)
    assert gw.verify(wrapped) is True
    with pytest.raises(LLMRecordError, match="schema_version"):
        assert_admissible_to_graph(wrapped, gw)


# ============ 门1：绕过 Gateway → 不可准入（封印）============

def test_gate_bypass_forged_record_rejected():
    """模拟 role agent 绕过 Gateway 直调 provider + 自造账：未经本 gateway 封印 → 准入门拒。"""
    gw = _gateway(_profiles_two_strong())
    real = gw.complete(_req())
    forged = _record()
    from app.llm import GatewaySealedResult
    forged_res = GatewaySealedResult(response=LLMResponse(content="x"), record=forged, events=[])
    assert gw.verify(forged_res) is False
    with pytest.raises(LLMRecordError):
        assert_admissible_to_graph(forged_res, gw)


def test_gate_bypass_tampered_seal_detected():
    """封印绑定账内容：盖完封印后再改任一字段 → 校验必失败（防篡改证据）。"""
    gw = _gateway(_profiles_two_strong())
    res = gw.complete(_req())
    assert gw.verify(res) is True
    res.record.model = "claude-haiku"  # 偷偷把强模型改记成弱模型
    assert gw.verify(res) is False
    with pytest.raises(LLMRecordError):
        assert_admissible_to_graph(res, gw)


def test_gate_bypass_mut_paper_door():
    """变异测试（门是不是纸做的）：把准入门里的封印校验摘掉（mut），伪造账就混进来——证明该校验在咬。"""
    gw = _gateway(_profiles_two_strong())
    forged = _record(provider="p", model="m", auth_ref="secretref://p/p")
    from app.llm import GatewaySealedResult
    forged_res = GatewaySealedResult(response=LLMResponse(content="x"), record=forged, events=[])

    def admit_with_seal_check(result):
        if not gw.verify(result):
            raise LLMRecordError("未封印")
        assert_record_admissible(result.record)

    def admit_mutant_no_seal_check(result):  # ← 把封印门拆了
        assert_record_admissible(result.record)

    with pytest.raises(LLMRecordError):
        admit_with_seal_check(forged_res)        # 真门：抓住
    admit_mutant_no_seal_check(forged_res)       # 纸门：放过（无异常）→ 证明封印校验是承重门


# ============ 门2：缺必填四要素 → 拒 ============

@pytest.mark.parametrize("field", ["provider", "model", "auth_ref", "replay_state"])
def test_gate_missing_required_field_rejected(field):
    kw = dict(provider="anthropic", model="claude-opus-4",
              auth_ref="secretref://anthropic/anthropic", replay_state=ReplayState.LIVE.value)
    kw[field] = ""  # 种坏门：抽掉一个必填
    rec = _record(**kw)
    with pytest.raises(LLMRecordError):
        assert_record_admissible(rec)


def test_gate_full_record_admissible_and_invalid_replay_state_rejected():
    rec = _record(provider="openai", model="gpt-4o",
                  auth_ref="secretref://openai/openai", replay_state=ReplayState.REPLAYED.value)
    assert_record_admissible(rec)  # 正例：四要素齐
    rec.replay_state = "teleported"  # 非法枚举
    with pytest.raises(LLMRecordError):
        assert_record_admissible(rec)


def test_gate_mut_paper_door_missing_field():
    """变异：把必填检查改成『只看 provider』，缺 auth_ref 的账就混过——证明四要素检查在咬。"""
    rec = _record(provider="anthropic", model="m", auth_ref="")

    def real_check(r):
        missing = [f for f in ("provider", "model", "auth_ref", "replay_state") if not getattr(r, f)]
        if missing:
            raise LLMRecordError(str(missing))

    def mutant_check(r):  # ← 只查 provider
        if not r.provider:
            raise LLMRecordError("no provider")

    with pytest.raises(LLMRecordError):
        real_check(rec)
    mutant_check(rec)  # 纸门放过 → 证明 auth_ref 那条必填在承重


# ============ 门3：明文 secret 不进 prompt / 账 / 导出 ============

def test_gate_plaintext_secret_in_prompt_blocked():
    """实盘/在册 key 夹在 prompt 里 → 拒发，且 provider 一次都不被调（红线：secret 不进 LLM）。"""
    profiles = _profiles_two_strong()
    stub = StubLLMClient()
    persisted = []
    gw = _gateway(
        profiles,
        factory=lambda c: stub,
        extra_secrets={"binance_mainnet": TRIPWIRE_SECRET},
        record_sink=persisted.append,
    )
    bad = LLMRequest(
        messages=[LLMMessage(role="user", content=f"帮我下单，key 是 {TRIPWIRE_SECRET}")],
        capability=RoleCapabilityRequest(role="reporter"),
        owner_user_id="owner-test",
        workflow_id="prompt-guard",
        invocation_id=f"inv-{next(_INVOCATIONS)}",
    )
    with pytest.raises(SecretLeakError) as ei:
        gw.complete(bad)
    assert stub.calls == []  # provider 从未被触达
    assert TRIPWIRE_SECRET not in str(ei.value)
    assert len(persisted) == 1
    assert persisted[0].record_kind == "terminal"
    assert persisted[0].status == "refused"
    assert persisted[0].failure_stage == "prompt_guard"
    assert persisted[0].provider == persisted[0].model == persisted[0].auth_ref == ""
    assert persisted[0].routing_policy_ref == ""
    assert persisted[0].routing_policy_state == "unresolved_pre_route"
    assert persisted[0].prompt_hash == persisted[0].prompt_digest
    assert persisted[0].cost["status"] == "unavailable"
    assert persisted[0].cost["reason"] == "pre_route_no_provider_response"
    finished = [event for event in ei.value.events if event.kind == EV_CALL_FINISHED]
    assert len(finished) == 1
    assert finished[0].data["call_id"] == persisted[0].call_id
    assert finished[0].data["status"] == "refused"
    assert finished[0].data["failure_stage"] == "prompt_guard"


def test_gate_plaintext_secret_in_record_rejected():
    """把明文 key 塞进账任一字段 → secret 门必抓（报错不回显 secret）。"""
    rec = _record(provider="anthropic", model="m", auth_ref="secretref://a/a")
    rec.error_kind = f"boom {TRIPWIRE_SECRET}"  # 种坏门：明文漏进账
    with pytest.raises(SecretLeakError) as ei:
        assert_no_plaintext_secret(rec, [TRIPWIRE_SECRET])
    assert TRIPWIRE_SECRET not in str(ei.value)


def test_real_call_record_carries_no_plaintext_key():
    """真路由到带 key 的 provider：物化的明文绝不出现在落账/导出序列化面，只留 SecretRef。"""
    profiles = _profiles_two_strong()
    ks = _seed_keystore(profiles)
    # anthropic pool 的真 key
    real_key = ks.fetch("anthropic").api_secret
    gw = _gateway(profiles, keystore=ks, factory=lambda c: StubLLMClient(content="ok"))
    res = gw.complete(_req(difficulty="hard"))
    blob = json.dumps(res.record.to_dict(), ensure_ascii=False)
    assert real_key and real_key not in blob
    assert res.record.auth_ref == "secretref://anthropic/anthropic"
    # gateway 自带的落账前 secret 门也不应抛（正例）
    gw.assert_record_secret_clean(res.record)


def test_credential_pool_blocks_role_agent_materialize():
    """role agent 即便 import 到池：没有 gateway capability，物化不出明文。"""
    profiles = _profiles_two_strong()
    ks = _seed_keystore(profiles)
    pool = _build_pool(profiles, ks)
    from app.llm import CredentialError
    with pytest.raises(CredentialError):
        pool.materialize("anthropic", capability=GatewayCapability(b"forged-token-guess"))
    # 安全视图不含明文
    desc = pool.describe("anthropic")
    assert ks.fetch("anthropic").api_secret not in json.dumps(desc.to_dict())


def test_materialized_credential_repr_redacts_key():
    profiles = _profiles_two_strong()
    ks = _seed_keystore(profiles)
    pool = _build_pool(profiles, ks)
    cap = pool.issue_capability()
    cred = pool.materialize("anthropic", capability=cap)
    assert cred.api_key  # 门后真有明文
    assert cred.api_key not in repr(cred)  # 但 repr 打码
    assert "redacted" in repr(cred)


# ============ 门4：Verifier 独立性 ============

def test_independence_distinct_provider_satisfied():
    """builder 用 anthropic，verifier 要独立 → 路由到 openai，satisfied=True 且裁决独立成立。"""
    profiles = _profiles_two_strong()
    gw = _gateway(profiles)
    builder = gw.complete(_req(role="factor_engineer", difficulty="hard", session="sx"))
    verifier = gw.complete(_req(role="verifier", difficulty="hard", independence=True, session="sx"))
    assert builder.record.provider != verifier.record.provider
    assert verifier.record.independence.required is True
    assert verifier.record.independence.satisfied is True
    assert verifier.record.independence.distinct_provider is True
    verdict = evaluate_independence(builder.record, verifier.record)
    assert verdict.independent is True


def test_independence_same_gpt_family_across_providers_is_insufficient():
    """换 API/provider 和 GPT 版本仍是同一家族，不能冒充双模型独立。"""

    profiles = [
        LLMModelProfile(
            provider="gateway_a",
            model="gpt-5.6-sol-pro",
            capability_tier=ModelTier.STRONG.value,
            pool_id="gateway_a",
        ),
        LLMModelProfile(
            provider="gateway_b",
            model="gpt-4o",
            capability_tier=ModelTier.STRONG.value,
            pool_id="gateway_b",
        ),
    ]
    gw = _gateway(profiles)
    builder = gw.complete(_req(role="factor_engineer", difficulty="hard", session="same-gpt"))
    verifier_request = _req(
        role="verifier", difficulty="hard", independence=True, session="same-gpt"
    )
    verifier_request.capability.prefer_provider = "gateway_b"
    verifier = gw.complete(verifier_request)

    assert builder.record.provider == "gateway_a"
    assert verifier.record.provider == "gateway_b"
    assert verifier.record.independence.distinct_provider is True
    assert verifier.record.independence.distinct_model is True
    assert verifier.record.independence.satisfied is False
    verdict = evaluate_independence(builder.record, verifier.record)
    assert verdict.independent is False


def test_independence_different_families_on_same_provider_is_insufficient():
    """共享 provider/operator 也不能满足双重异源的独立性门。"""

    builder = _record(provider="aggregator", model="gpt-5")
    verifier = _record(
        provider="aggregator",
        model="claude-opus-4",
        prompt_digest="different-context",
        independence=IndependenceRecord(required=True, satisfied=True),
    )
    verdict = evaluate_independence(builder, verifier)
    assert verdict.independent is False
    assert "假独立" in verdict.reason


def test_independence_unknown_model_families_fail_closed():
    builder = _record(provider="vendor-a", model="opaque-alpha")
    verifier = _record(
        provider="vendor-b",
        model="opaque-beta",
        prompt_digest="different-context",
        independence=IndependenceRecord(required=True, satisfied=True),
    )
    verdict = evaluate_independence(builder, verifier)
    assert verdict.independent is False
    assert "假独立" in verdict.reason


def test_independence_prefers_independent_higher_tier_over_exact_alias():
    profiles = [
        LLMModelProfile(
            provider="anthropic",
            model="claude-sonnet-4",
            capability_tier=ModelTier.NORMAL.value,
            pool_id="anthropic",
        ),
        LLMModelProfile(
            provider="openai",
            model="gpt-5",
            capability_tier=ModelTier.STRONG.value,
            pool_id="openai",
        ),
    ]
    decision = ModelRoutingPolicy(profiles).resolve(
        RoleCapabilityRequest(independence_required=True),
        builder_signature=("anthropic", "claude-sonnet-4"),
    )

    assert decision.profile.provider == "openai"
    assert decision.profile.model == "gpt-5"
    assert decision.independence_distinct is True
    assert decision.tier_resolved == ModelTier.STRONG.value
    assert decision.degraded is False


def test_independence_uses_credential_backed_provider_not_route_label():
    """Route labels cannot hide that both calls execute through one provider identity."""

    profiles = [
        LLMModelProfile(
            provider="profile-a",
            model="gpt-5",
            capability_tier=ModelTier.STRONG.value,
            pool_id="pool-a",
        ),
        LLMModelProfile(
            provider="profile-b",
            model="claude-opus-4",
            capability_tier=ModelTier.STRONG.value,
            pool_id="pool-b",
        ),
    ]
    keystore = SecureKeystore(InMemoryKeystore())
    pool = LLMCredentialPool(keystore)
    for pool_id, model in (("pool-a", "gpt-5"), ("pool-b", "claude-opus-4")):
        keystore.store(
            KeystoreRecord(
                name=pool_id,
                api_key=f"key-{pool_id}-xxxxxxxx",
                api_secret=f"key-{pool_id}-xxxxxxxx",
            )
        )
        pool.register(
            pool_id,
            SecretRef(
                keystore_name=pool_id,
                provider="shared-gateway",
                auth_kind="api_key",
            ),
            default_model=model,
        )
    gateway = LLMGateway(
        policy=ModelRoutingPolicy(profiles),
        credential_pool=pool,
        client_factory=lambda _credential: StubLLMClient(),
    )

    builder = gateway.complete(
        _req(role="factor_engineer", difficulty="hard", session="credential-provider")
    )
    verifier = gateway.complete(
        _req(
            role="verifier",
            difficulty="hard",
            independence=True,
            session="credential-provider",
        )
    )

    assert builder.record.provider == "shared-gateway"
    assert verifier.record.provider == "shared-gateway"
    assert verifier.record.model == "claude-opus-4"
    assert verifier.record.independence.distinct_provider is False
    assert verifier.record.independence.satisfied is False
    assert evaluate_independence(builder.record, verifier.record).independent is False


def test_independence_single_provider_marked_insufficient():
    """只有一个 provider：verifier 没法独立 → satisfied=False、裁决不独立（绝不假报）。"""
    profiles = [LLMModelProfile(provider="anthropic", model="claude-opus-4",
                                capability_tier=ModelTier.STRONG.value, pool_id="anthropic")]
    gw = _gateway(profiles)
    builder = gw.complete(_req(role="factor_engineer", difficulty="hard", session="sy"))
    verifier = gw.complete(_req(role="verifier", difficulty="hard", independence=True, session="sy"))
    assert verifier.record.provider == builder.record.provider
    assert verifier.record.independence.satisfied is False
    assert verifier.record.independence.reason == ""  # free text is excluded from durable evidence
    verdict = evaluate_independence(builder.record, verifier.record)
    assert verdict.independent is False


def test_gate_verifier_falsely_claims_independent_caught():
    """种坏门：verifier 与 builder 同 provider+model 却把 satisfied 置 True（假独立）→ 裁决必判不独立。"""
    builder = _record(prompt_digest="d1")
    verifier_lie = _record(prompt_digest="d2",
                           independence=IndependenceRecord(required=True, satisfied=True))  # ← 谎称独立
    verdict = evaluate_independence(builder, verifier_lie)
    assert verdict.independent is False
    assert "假独立" in verdict.reason


def test_gate_verifier_missing_context_insufficient():
    """verifier 缺 provider/model/context 记录 → 独立性不足（§7）。"""
    builder = _record(provider="anthropic", model="opus", auth_ref="r", prompt_digest="d1")
    verifier_noctx = _record(provider="", model="", auth_ref="r", prompt_digest="")
    verdict = evaluate_independence(builder, verifier_noctx)
    assert verdict.independent is False
    assert "独立性不足" in verdict.reason


# ============ 门5：混合自适应路由 · 绝不静默降质 ============

def test_routing_hard_task_gets_strong():
    pol = ModelRoutingPolicy(_profiles_mixed())
    d = pol.resolve(RoleCapabilityRequest(difficulty="hard"))
    assert d.tier_resolved == ModelTier.STRONG.value
    assert d.degraded is False


def test_routing_mechanical_gets_light():
    pol = ModelRoutingPolicy(_profiles_mixed())
    d = pol.resolve(RoleCapabilityRequest(difficulty="mechanical", risk="low"))
    assert d.tier_resolved == ModelTier.LIGHT.value


def test_routing_irreversible_forces_strong_even_if_mechanical():
    pol = ModelRoutingPolicy(_profiles_mixed())
    d = pol.resolve(RoleCapabilityRequest(difficulty="mechanical", risk="irreversible"))
    assert d.tier_requested == ModelTier.STRONG.value
    assert d.tier_resolved == ModelTier.STRONG.value


def test_gate_hard_task_only_light_flags_degraded():
    """只有轻模型时，难任务被迫降质 → 必标 degraded（绝不静默），非 strict 模式返回带标的账。"""
    light_only = [LLMModelProfile(provider="openai", model="gpt-4o-mini",
                                  capability_tier=ModelTier.LIGHT.value, pool_id="openai")]
    pol = ModelRoutingPolicy(light_only)
    d = pol.resolve(RoleCapabilityRequest(difficulty="hard"))
    assert d.tier_requested == ModelTier.STRONG.value
    assert d.tier_resolved == ModelTier.LIGHT.value
    assert d.degraded is True
    assert d.degrade_reason  # 非空说明

    gw = _gateway(light_only, strict_degrade=False)
    res = gw.complete(_req(difficulty="hard"))
    assert res.record.degraded is True
    assert res.record.tier_resolved == ModelTier.LIGHT.value


def test_gate_hard_task_strict_degrade_refuses():
    """strict_degrade（默认）下，难任务无强模型 → 拒绝静默降质，provider 不被调。"""
    light_only = [LLMModelProfile(provider="openai", model="gpt-4o-mini",
                                  capability_tier=ModelTier.LIGHT.value, pool_id="openai")]
    stub = StubLLMClient()
    persisted = []
    gw = _gateway(
        light_only,
        factory=lambda c: stub,
        strict_degrade=True,
        record_sink=persisted.append,
    )
    with pytest.raises(DegradedRoutingError) as caught:
        gw.complete(_req(difficulty="hard"))
    assert stub.calls == []
    assert [(r.record_kind, r.status, r.failure_stage) for r in persisted] == [
        ("terminal", "refused", "degrade")
    ]
    finished = [event for event in caught.value.events if event.kind == EV_CALL_FINISHED]
    assert [event.data["call_id"] for event in finished] == [persisted[0].call_id]
    assert finished[0].data["failure_stage"] == "degrade"


def test_gate_mut_paper_door_degrade_not_silenced():
    """变异：若 required_tier 对 HARD 错返 LIGHT（静默降质 bug），强模型不变量测试必红——此处反向自证。"""
    pol = ModelRoutingPolicy(_profiles_mixed())
    # 真策略：HARD → STRONG
    assert pol.required_tier(RoleCapabilityRequest(difficulty="hard")) == ModelTier.STRONG
    # 模拟 mut：把判定换成永远 LIGHT
    def mutant_required_tier(_req):
        return ModelTier.LIGHT
    assert mutant_required_tier(RoleCapabilityRequest(difficulty="hard")) != ModelTier.STRONG  # 纸门 → 难任务静默走轻


# ============ fallback / 健康 ============

def test_fallback_on_provider_error_same_tier_no_degrade():
    """强 provider A 报错 → fallback 到同档强 provider B：换 provider 成功、不降质。"""
    profiles = _profiles_two_strong()

    def factory(cred):
        if cred.provider == "anthropic":
            class _Boom:
                provider = "anthropic"
                def chat(self, *a, **k):
                    raise RuntimeError("503 upstream")
            return _Boom()
        return StubLLMClient(content="from-openai")

    persisted = []
    gw = _gateway(profiles, factory=factory, record_sink=persisted.append)
    res = gw.complete(_req(difficulty="hard"))
    assert res.record.provider == "openai"
    assert res.record.fallback_used is True
    assert [(r.record_kind, r.provider, r.status) for r in res.audit_records] == [
        ("attempt", "anthropic", "error"),
        ("attempt", "openai", "ok"),
        ("terminal", "openai", "ok"),
    ]
    assert res.record.degraded is False
    assert res.response.content == "from-openai"
    assert persisted == res.audit_records


def test_all_providers_failing_raises_gateway_error():
    """所有候选都报错 → fallback 用尽 → GatewayError（不静默吞、不假装成功）。"""
    profiles = _profiles_two_strong()

    class _Boom:
        provider = "x"
        def chat(self, *a, **k):
            raise RuntimeError("upstream down")

    persisted = []
    gw = _gateway(profiles, factory=lambda c: _Boom(), record_sink=persisted.append)
    with pytest.raises(GatewayError) as ei:
        gw.complete(_req(difficulty="hard"))
    assert [(r.record_kind, r.status) for r in persisted] == [
        ("attempt", "error"), ("attempt", "error"), ("terminal", "error")
    ]
    assert ei.value.records == persisted
    finished = [event for event in ei.value.events if event.kind == EV_CALL_FINISHED]
    assert [event.data["call_id"] for event in finished] == [
        record.call_id for record in persisted
    ]
    assert [event.data["record_kind"] for event in finished] == [
        "attempt",
        "attempt",
        "terminal",
    ]


def test_durable_sink_requires_stable_key_before_provider_access():
    stub = StubLLMClient(content="must-not-run")
    gw = _gateway(_profiles_two_strong(), factory=lambda cred: stub)
    with pytest.raises(LLMRecordError, match="stable seal_secret"):
        gw.complete(_req(difficulty="hard"), record_sink=lambda record: None)
    assert stub.calls == []


def test_sink_failure_prevents_successful_response_return():
    stub = StubLLMClient(content="provider-produced-output")

    def broken_sink(record):
        raise OSError("disk unavailable")

    gw = _gateway(
        _profiles_two_strong(),
        factory=lambda cred: stub,
        record_sink=broken_sink,
    )
    with pytest.raises(OSError, match="disk unavailable"):
        gw.complete(_req(difficulty="hard"))
    assert len(stub.calls) == 1


def test_credential_materialization_errors_are_typed_and_persisted(monkeypatch):
    persisted = []
    gw = _gateway(_profiles_two_strong(), record_sink=persisted.append)

    def materialize_boom(*args, **kwargs):
        raise ValueError("CREDENTIAL_EXCEPTION_TEXT_MUST_NOT_PERSIST")

    monkeypatch.setattr(gw._pool, "materialize", materialize_boom)  # noqa: SLF001
    with pytest.raises(GatewayError) as ei:
        gw.complete(_req(difficulty="hard"))
    assert [(r.record_kind, r.status, r.failure_stage) for r in persisted] == [
        ("attempt", "error", "credential"),
        ("attempt", "error", "credential"),
        ("terminal", "error", "credential"),
    ]
    assert all(r.error_kind in {"ValueError", "all_credentials_unavailable"} for r in persisted)
    assert "CREDENTIAL_EXCEPTION_TEXT_MUST_NOT_PERSIST" not in json.dumps(
        [r.to_dict() for r in persisted], ensure_ascii=False
    )
    assert ei.value.records == persisted


def test_missing_credential_descriptor_still_persists_attempt_and_terminal():
    profile = LLMModelProfile(
        provider="anthropic",
        model="claude-opus-4",
        capability_tier=ModelTier.STRONG.value,
        pool_id="missing-pool",
    )
    pool = LLMCredentialPool(_seed_keystore([profile]))
    persisted = []
    gw = LLMGateway(
        policy=ModelRoutingPolicy([profile]),
        credential_pool=pool,
        client_factory=lambda cred: pytest.fail("provider client must not be built"),
        seal_secret=_AUDIT_SEAL,
        record_sink=persisted.append,
    )

    with pytest.raises(GatewayError) as caught:
        gw.complete(_req(difficulty="hard"))

    assert [(r.record_kind, r.status, r.failure_stage) for r in persisted] == [
        ("attempt", "error", "credential"),
        ("terminal", "error", "credential"),
    ]
    assert persisted[0].provider == "anthropic"
    assert persisted[0].model == "claude-opus-4"
    assert persisted[0].auth_ref == ""
    assert caught.value.records == persisted


def test_reused_invocation_fails_before_second_provider_access():
    stub = StubLLMClient(content="stable")
    persisted = []
    gw = _gateway(
        _profiles_two_strong(),
        factory=lambda cred: stub,
        record_sink=persisted.append,
    )
    request = _req(difficulty="hard")
    first = gw.complete(request)

    with pytest.raises(LLMRecordError, match="already claimed"):
        gw.complete(request)

    assert len(stub.calls) == 1
    assert len(persisted) == 2
    assert first.record is persisted[-1]


def test_fallback_missing_credential_triggers_fallback():
    """强 provider 无可用 key → 视作不可用、fallback，绝不静默落到 DevLocalLLM。"""
    profiles = _profiles_two_strong()
    ks = SecureKeystore(InMemoryKeystore())
    # 只给 openai 配 key，anthropic 无 key
    ks.store(KeystoreRecord(name="openai", api_key="key-openai-xxxxxxxx", api_secret="key-openai-xxxxxxxx"))
    persisted = []
    gw = _gateway(
        profiles,
        keystore=ks,
        factory=lambda c: StubLLMClient(content="ok-openai"),
        record_sink=persisted.append,
    )
    res = gw.complete(_req(difficulty="hard"))
    assert res.record.provider == "openai"
    assert res.record.fallback_used is True
    assert res.audit_records[0].provider == "anthropic"
    assert res.audit_records[0].error_kind == "no_usable_credential"
    assert [r.record_kind for r in res.audit_records] == ["attempt", "attempt", "terminal"]
    assert persisted == res.audit_records


# ============ secret 不经异常链 / traceback 漏出（C-S7 Gap1 · GOAL §8 红线）============

# 明文 secret tripwire：夹在 base_url userinfo / Authorization 里，模拟 provider 异常回显配置明文。
_FACTORY_LEAK = "https://admin:sk-FACTORY-LEAK-deadbeef9876@host.internal/v1"
_CHAT_LEAK = "Authorization: Bearer sk-CHAT-LEAK-feedface5566"


def test_factory_construction_error_no_plaintext_leak():
    """种坏门（Finding2 ①②）：provider 构造（client_factory）抛含明文 secret 的异常
    （如 custom base_url 夹 user:pass@host）→ 工厂调用已纳入 sanitized try、终态 GatewayError 用
    `from None` 切链 → message / traceback / 真 ERROR_REPORTER 落盘面都只剩 type-name，绝不带出明文。

    变异三态（手动验，见卡）：把工厂移出 try → 裸 ValueError 漏出（pytest.raises(GatewayError) 红）；
    恢复 `from exc` → traceback.format_exception 带出明文（assert 明文不在 红）。
    """
    import traceback as _tb

    profiles = _profiles_two_strong()

    def exploding_factory(cred):
        # 模拟 make_llm_client 对夹了 userinfo 的 base_url 校验失败、把明文 url 回显进异常。
        raise ValueError(f"invalid base_url for provider {cred.provider}: {_FACTORY_LEAK}")

    gw = _gateway(profiles, factory=exploding_factory)
    with pytest.raises(GatewayError) as ei:        # ① 工厂异常被收敛成 GatewayError（非裸 ValueError 漏出）
        gw.complete(_req(difficulty="hard"))
    exc = ei.value

    # ② GatewayError message 绝不回显明文
    assert _FACTORY_LEAK not in str(exc)
    assert "sk-FACTORY-LEAK" not in str(exc)
    # ③ 完整异常链（= ERROR_REPORTER 用的 traceback.format_exception）不含明文（from None 切链）
    formatted = "".join(_tb.format_exception(exc))
    assert _FACTORY_LEAK not in formatted
    assert "sk-FACTORY-LEAK" not in formatted
    # ④ 仍保留够调试的 type-name（ValueError 出现在 fallback_chain，定位失败 provider）
    assert "ValueError" in str(exc)

    # ⑤ 喂真 ErrorReporter（生产落 data/audit/errors.jsonl 的同一序列化路径）：落盘 payload 不含明文
    import tempfile
    from pathlib import Path as _Path

    from app.observability.errors import ErrorReporter, LocalErrorLog

    with tempfile.TemporaryDirectory() as td:
        rep = ErrorReporter(local_log=LocalErrorLog(path=_Path(td) / "errors.jsonl"))
        rep.report(exc, {"path": "/x"})
        blob = (_Path(td) / "errors.jsonl").read_text(encoding="utf-8")
    assert _FACTORY_LEAK not in blob
    assert "sk-FACTORY-LEAK" not in blob


def test_terminal_gateway_error_does_not_chain_provider_exception():
    """正常 provider 失败（chat 抛错）→ 终态 GatewayError（type-name 够调试、不泄）：
    即便 provider 异常 str() 夹明文，`from None` 也保证 traceback.format_exception 不带出（chat 路径同护）。"""
    import traceback as _tb

    profiles = _profiles_two_strong()

    class _BoomLeak:
        provider = "x"

        def chat(self, *a, **k):
            raise RuntimeError(f"upstream 401 ({_CHAT_LEAK})")

    gw = _gateway(profiles, factory=lambda c: _BoomLeak())
    with pytest.raises(GatewayError) as ei:
        gw.complete(_req(difficulty="hard"))
    exc = ei.value
    formatted = "".join(_tb.format_exception(exc))
    assert _CHAT_LEAK not in str(exc)
    assert _CHAT_LEAK not in formatted
    assert "sk-CHAT-LEAK" not in formatted
    assert "RuntimeError" in str(exc)              # type-name 够调试（定位 provider 失败类型）


_DEGRADE_LEAK = "https://svc:sk-DEGRADE-LEAK-cafef00d@vault.internal/v1"


def test_strict_degrade_fallback_does_not_chain_provider_secret():
    """姊妹向量（C-S7 Gap1 补修 · GOAL §8 红线）：首选强档携明文异常失败 → fallback 落「降级强档」
    → strict_degrade 拒绝 → 其 DegradedRoutingError 绝不经 __context__ 链带出原始明文异常
    （否则经 ERROR_REPORTER 落 errors.jsonl 泄漏）。strict-degrade 仍真降级、只是不带明文进日志。

    变异（手验，见卡）：把 `_enforce_strict_degrade` 移回 except 块内（保留 __context__ 链）→ 本测必红。
    """
    import traceback as _tb

    # 1 强档 + 1 轻档：HARD 初路由走强档（不降级 → 过 complete() 入口 enforce），
    # 强档 factory 携明文异常失败 → fallback 只剩轻档 → 降级强档 → strict_degrade 在 while 顶 raise。
    profiles = [
        LLMModelProfile(provider="anthropic", model="claude-opus-4",
                        capability_tier=ModelTier.STRONG.value, pool_id="anthropic"),
        LLMModelProfile(provider="openai", model="gpt-4o-mini",
                        capability_tier=ModelTier.LIGHT.value, pool_id="openai"),
    ]

    def factory(cred):
        if cred.provider == "anthropic":
            # 模拟 provider 构造把夹 userinfo 的 base_url 明文回显进异常。
            raise ValueError(f"connect failed base_url={_DEGRADE_LEAK}")
        return StubLLMClient(content="should-not-reach")

    gw = _gateway(profiles, factory=factory, strict_degrade=True)
    with pytest.raises(DegradedRoutingError) as ei:        # 真降级拒绝（语义不变）
        gw.complete(_req(difficulty="hard"))
    exc = ei.value

    # 明文不在 DegradedRoutingError 的 message / 完整异常链 traceback（__context__ 未带出原始 exc）
    formatted = "".join(_tb.format_exception(exc))
    assert _DEGRADE_LEAK not in str(exc)
    assert _DEGRADE_LEAK not in formatted
    assert "sk-DEGRADE-LEAK" not in formatted
    assert exc.__context__ is None                         # 链已断（既非 suppress、根本未挂原始 exc）
    # 喂真 ErrorReporter（生产落 errors.jsonl 同一序列化路径）：落盘 payload 不含明文
    import tempfile
    from pathlib import Path as _Path

    from app.observability.errors import ErrorReporter, LocalErrorLog

    with tempfile.TemporaryDirectory() as td:
        rep = ErrorReporter(local_log=LocalErrorLog(path=_Path(td) / "errors.jsonl"))
        rep.report(exc, {"path": "/x"})
        blob = (_Path(td) / "errors.jsonl").read_text(encoding="utf-8")
    assert _DEGRADE_LEAK not in blob
    assert "sk-DEGRADE-LEAK" not in blob
    # 降级语义仍在：DegradedRoutingError 是 GatewayError 子类、message 含降级说明（够调试、不夹明文）
    assert isinstance(exc, GatewayError)
    assert "strict_degrade" in str(exc) or "降" in str(exc)


_REFB_LEAK = "https://u:sk-REFB-LEAK-0bada55deadbeef@host.internal/v1"


def test_refallback_resolve_nonrouting_error_no_secret_chain():
    """第三向量（codex 复审找到·结构性关闭验收 · GOAL §8）：fallback 解析 _refallback→resolve 抛
    【非 RoutingError】异常时，绝不隐式 chain 上一轮携明文的 provider 异常——因 fallback 解析已移出
    except 活跃上下文（sys.exc_info() 已复位）。异常原样冒出（不被静默吞），但 __context__ 干净。

    变异（手验，见卡）：把 fallback 解析移回 except 块内 → 该非 RoutingError 会 chain 明文 exc → 本测必红。
    """
    import traceback as _tb

    profiles = _profiles_two_strong()

    class _ResolveBoomPolicy(ModelRoutingPolicy):
        def resolve(self, req, *, unavailable_providers=None, exclude_signatures=None, builder_signature=None):
            if exclude_signatures:                       # 仅 fallback 解析（_refallback 调）抛非 RoutingError
                raise RuntimeError("policy internal boom")
            return super().resolve(
                req, unavailable_providers=unavailable_providers,
                exclude_signatures=exclude_signatures, builder_signature=builder_signature,
            )

    ks = _seed_keystore(profiles)
    pool = _build_pool(profiles, ks)
    policy = _ResolveBoomPolicy(profiles, mode=RoutingMode.HYBRID_ADAPTIVE)

    def factory(cred):
        # 首选 provider 构造即携明文异常 → 进 except → 触发 fallback 解析（resolve 抛 RuntimeError）。
        raise ValueError(f"connect base_url={_REFB_LEAK}")

    gw = LLMGateway(policy=policy, credential_pool=pool, client_factory=factory,
                    strict_degrade=True, scan_prompt_secrets=True)
    with pytest.raises(RuntimeError) as ei:              # resolve 的非 RoutingError 原样冒出（不被静默吞）
        gw.complete(_req(difficulty="hard"))
    exc = ei.value
    formatted = "".join(_tb.format_exception(exc))
    assert _REFB_LEAK not in str(exc)
    assert _REFB_LEAK not in formatted
    assert "sk-REFB-LEAK" not in formatted
    assert exc.__context__ is None                       # 关键：未挂上一轮 factory 明文异常
    import tempfile
    from pathlib import Path as _Path

    from app.observability.errors import ErrorReporter, LocalErrorLog

    with tempfile.TemporaryDirectory() as td:
        rep = ErrorReporter(local_log=LocalErrorLog(path=_Path(td) / "errors.jsonl"))
        rep.report(exc, {"path": "/x"})
        blob = (_Path(td) / "errors.jsonl").read_text(encoding="utf-8")
    assert _REFB_LEAK not in blob
    assert "sk-REFB-LEAK" not in blob


# ============ replay_state 如实记录 ============

def test_caller_declared_replay_is_refused_before_provider_access():
    profiles = _profiles_two_strong()
    stub = StubLLMClient(content="r", fixture_key="llmfx-abc123")
    persisted = []
    gw = _gateway(profiles, factory=lambda c: stub, record_sink=persisted.append)
    req = LLMRequest(messages=[LLMMessage(role="user", content="hi")],
                     capability=RoleCapabilityRequest(role="reporter", difficulty="hard"),
                     owner_user_id="owner-test", workflow_id="replay-test",
                     invocation_id=f"inv-{next(_INVOCATIONS)}",
                     replay_mode="replay")
    with pytest.raises(GatewayError, match="verified replay outcome") as caught:
        gw.complete(req)
    assert stub.calls == []
    assert [(r.record_kind, r.status, r.failure_stage) for r in persisted] == [
        ("terminal", "refused", "replay")
    ]
    assert persisted[0].replay_state == ReplayState.LIVE.value
    assert persisted[0].fixture_key is None
    assert caught.value.records == persisted


# ============ 配置：质量优先 / 成本优先 ============

def test_routing_mode_configurable_quality_vs_cost():
    cost = ModelRoutingPolicy(_profiles_mixed(), mode=RoutingMode.COST_FIRST)
    quality = ModelRoutingPolicy(_profiles_mixed(), mode=RoutingMode.QUALITY_FIRST)
    # 成本优先：普通机械活走轻；但不可逆仍被钉死强（下限不破）
    assert cost.resolve(RoleCapabilityRequest(difficulty="mechanical", risk="low")).tier_resolved == ModelTier.LIGHT.value
    assert cost.resolve(RoleCapabilityRequest(difficulty="normal", risk="irreversible")).tier_resolved == ModelTier.STRONG.value
    # 质量优先：普通活也走强
    assert quality.resolve(RoleCapabilityRequest(difficulty="normal", risk="low")).tier_resolved == ModelTier.STRONG.value


def test_seal_roundtrip_and_wrong_secret():
    rec = _record(provider="p", model="m", auth_ref="r")
    s = b"x" * 32
    rec.seal = seal_record(rec, s)
    assert verify_record_seal(rec, s) is True
    assert verify_record_seal(rec, b"y" * 32) is False
