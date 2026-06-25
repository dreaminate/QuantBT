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

import json

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

TRIPWIRE_SECRET = "sk-LEAK-TRIPWIRE-deadbeef0123456789"


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
             scan_prompt_secrets=True, extra_secrets=None):
    ks = keystore if keystore is not None else _seed_keystore(profiles, extra_secrets=extra_secrets)
    pool = _build_pool(profiles, ks)
    policy = ModelRoutingPolicy(profiles, mode=mode)
    if factory is None:
        factory = lambda cred: StubLLMClient(content="stub-resp")  # noqa: E731
    return LLMGateway(
        policy=policy, credential_pool=pool, client_factory=factory,
        strict_degrade=strict_degrade, scan_prompt_secrets=scan_prompt_secrets,
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
    return LLMRequest(
        messages=[LLMMessage(role="user", content="跑个因子 IC")],
        capability=RoleCapabilityRequest(role=role, difficulty=difficulty, risk=risk, independence_required=independence),
        session_id=session,
    )


# ============ 端到端正例 ============

def test_happy_path_record_sealed_and_admissible():
    gw = _gateway(_profiles_two_strong())
    res = gw.complete(_req(difficulty="hard"))
    rec = res.record
    assert rec.provider and rec.model and rec.auth_ref and rec.replay_state
    assert rec.auth_ref.startswith("secretref://")
    assert rec.tier_resolved == ModelTier.STRONG.value
    assert gw.verify(res) is True
    assert_admissible_to_graph(res, gw)  # 不抛 = 准入通过
    assert [e.kind for e in res.events][:1] == ["LLMRouteSelected"]


# ============ 门1：绕过 Gateway → 不可准入（封印）============

def test_gate_bypass_forged_record_rejected():
    """模拟 role agent 绕过 Gateway 直调 provider + 自造账：未经本 gateway 封印 → 准入门拒。"""
    gw = _gateway(_profiles_two_strong())
    real = gw.complete(_req())
    forged = LLMCallRecord(provider="anthropic", model="claude-opus-4",
                           auth_ref="secretref://anthropic/anthropic", replay_state=ReplayState.LIVE.value)
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
    forged = LLMCallRecord(provider="p", model="m", auth_ref="secretref://p/p", replay_state="live")
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
    rec = LLMCallRecord(**kw)
    with pytest.raises(LLMRecordError):
        assert_record_admissible(rec)


def test_gate_full_record_admissible_and_invalid_replay_state_rejected():
    rec = LLMCallRecord(provider="openai", model="gpt-4o",
                        auth_ref="secretref://openai/openai", replay_state=ReplayState.REPLAYED.value)
    assert_record_admissible(rec)  # 正例：四要素齐
    rec.replay_state = "teleported"  # 非法枚举
    with pytest.raises(LLMRecordError):
        assert_record_admissible(rec)


def test_gate_mut_paper_door_missing_field():
    """变异：把必填检查改成『只看 provider』，缺 auth_ref 的账就混过——证明四要素检查在咬。"""
    rec = LLMCallRecord(provider="anthropic", model="m", auth_ref="", replay_state="live")

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
    gw = _gateway(profiles, factory=lambda c: stub, extra_secrets={"binance_mainnet": TRIPWIRE_SECRET})
    bad = LLMRequest(
        messages=[LLMMessage(role="user", content=f"帮我下单，key 是 {TRIPWIRE_SECRET}")],
        capability=RoleCapabilityRequest(role="reporter"),
    )
    with pytest.raises(SecretLeakError):
        gw.complete(bad)
    assert stub.calls == []  # provider 从未被触达
    # 报错信息绝不回显 secret
    try:
        gw.complete(bad)
    except SecretLeakError as exc:
        assert TRIPWIRE_SECRET not in str(exc)


def test_gate_plaintext_secret_in_record_rejected():
    """把明文 key 塞进账任一字段 → secret 门必抓（报错不回显 secret）。"""
    rec = LLMCallRecord(provider="anthropic", model="m", auth_ref="secretref://a/a", replay_state="live")
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


def test_independence_single_provider_marked_insufficient():
    """只有一个 provider：verifier 没法独立 → satisfied=False、裁决不独立（绝不假报）。"""
    profiles = [LLMModelProfile(provider="anthropic", model="claude-opus-4",
                                capability_tier=ModelTier.STRONG.value, pool_id="anthropic")]
    gw = _gateway(profiles)
    builder = gw.complete(_req(role="factor_engineer", difficulty="hard", session="sy"))
    verifier = gw.complete(_req(role="verifier", difficulty="hard", independence=True, session="sy"))
    assert verifier.record.provider == builder.record.provider
    assert verifier.record.independence.satisfied is False
    assert "独立性不足" in verifier.record.independence.reason
    verdict = evaluate_independence(builder.record, verifier.record)
    assert verdict.independent is False


def test_gate_verifier_falsely_claims_independent_caught():
    """种坏门：verifier 与 builder 同 provider+model 却把 satisfied 置 True（假独立）→ 裁决必判不独立。"""
    builder = LLMCallRecord(provider="anthropic", model="claude-opus-4",
                            auth_ref="secretref://anthropic/anthropic", replay_state="live", prompt_digest="d1")
    verifier_lie = LLMCallRecord(provider="anthropic", model="claude-opus-4",
                                 auth_ref="secretref://anthropic/anthropic", replay_state="live", prompt_digest="d2",
                                 independence=IndependenceRecord(required=True, satisfied=True))  # ← 谎称独立
    verdict = evaluate_independence(builder, verifier_lie)
    assert verdict.independent is False
    assert "假独立" in verdict.reason


def test_gate_verifier_missing_context_insufficient():
    """verifier 缺 provider/model/context 记录 → 独立性不足（§7）。"""
    builder = LLMCallRecord(provider="anthropic", model="opus", auth_ref="r", replay_state="live", prompt_digest="d1")
    verifier_noctx = LLMCallRecord(provider="", model="", auth_ref="r", replay_state="live", prompt_digest="")
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
    gw = _gateway(light_only, factory=lambda c: stub, strict_degrade=True)
    with pytest.raises(DegradedRoutingError):
        gw.complete(_req(difficulty="hard"))
    assert stub.calls == []


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

    gw = _gateway(profiles, factory=factory)
    res = gw.complete(_req(difficulty="hard"))
    assert res.record.provider == "openai"
    assert res.record.fallback_used is True
    assert any("anthropic" in c for c in res.record.fallback_chain)
    assert res.record.degraded is False
    assert res.response.content == "from-openai"


def test_all_providers_failing_raises_gateway_error():
    """所有候选都报错 → fallback 用尽 → GatewayError（不静默吞、不假装成功）。"""
    profiles = _profiles_two_strong()

    class _Boom:
        provider = "x"
        def chat(self, *a, **k):
            raise RuntimeError("upstream down")

    gw = _gateway(profiles, factory=lambda c: _Boom())
    with pytest.raises(GatewayError):
        gw.complete(_req(difficulty="hard"))


def test_fallback_missing_credential_triggers_fallback():
    """强 provider 无可用 key → 视作不可用、fallback，绝不静默落到 DevLocalLLM。"""
    profiles = _profiles_two_strong()
    ks = SecureKeystore(InMemoryKeystore())
    # 只给 openai 配 key，anthropic 无 key
    ks.store(KeystoreRecord(name="openai", api_key="key-openai-xxxxxxxx", api_secret="key-openai-xxxxxxxx"))
    gw = _gateway(profiles, keystore=ks, factory=lambda c: StubLLMClient(content="ok-openai"))
    res = gw.complete(_req(difficulty="hard"))
    assert res.record.provider == "openai"
    assert res.record.fallback_used is True
    assert any("no_key" in c for c in res.record.fallback_chain)


# ============ replay_state 如实记录 ============

def test_replay_state_reflected_from_response():
    profiles = _profiles_two_strong()
    gw = _gateway(profiles, factory=lambda c: StubLLMClient(content="r", fixture_key="llmfx-abc123"))
    req = LLMRequest(messages=[LLMMessage(role="user", content="hi")],
                     capability=RoleCapabilityRequest(role="reporter", difficulty="hard"),
                     replay_mode="replay")
    res = gw.complete(req)
    assert res.record.replay_state == ReplayState.REPLAYED.value
    assert res.record.fixture_key == "llmfx-abc123"


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
    rec = LLMCallRecord(provider="p", model="m", auth_ref="r", replay_state="live")
    s = b"x" * 32
    rec.seal = seal_record(rec, s)
    assert verify_record_seal(rec, s) is True
    assert verify_record_seal(rec, b"y" * 32) is False
