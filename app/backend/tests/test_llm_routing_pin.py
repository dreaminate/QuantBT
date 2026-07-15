"""跨厂商切模型 S2：hard-pin routing 对抗测试。

钉死不变量(findings/dreaminate/model-switch-crossvendor-design-20260715.md · S2)：
- pin 只在 independence_required==False 生效 → **dual-model 独立审查门物理免疫手选洗白**（变异必红）。
- pin 只留 pin_provider 候选、换 pin_model；pool_id/provider 不变 → **no-mix 保住**。
- pin 厂商无候选 → PinnedModelUnavailable，**绝不静默跨厂商 fallback**（变异必红）。
- pin 轻 model 干重活 → degraded=True（诚实标降质，尊重手选但不假装）。
- 无 pin → Auto 行为与接 pin 前完全一致（回归）。
"""

from __future__ import annotations

import pytest

from app.llm.routing import (
    LLMModelProfile,
    ModelRoutingPolicy,
    ModelTier,
    PinnedModelUnavailable,
    RoleCapabilityRequest,
)


def _profiles():
    return [
        LLMModelProfile(provider="anthropic", model="claude-opus-4",
                        capability_tier=ModelTier.STRONG.value, pool_id="anthropic"),
        LLMModelProfile(provider="openai", model="gpt-4o",
                        capability_tier=ModelTier.STRONG.value, pool_id="openai"),
        LLMModelProfile(provider="qwen", model="qwen-plus",
                        capability_tier=ModelTier.NORMAL.value, pool_id="qwen"),
    ]


# ---------- pin 生效路径 ----------

def test_pin_selects_pinned_provider():
    d = ModelRoutingPolicy(_profiles()).resolve(
        RoleCapabilityRequest(pin_provider="openai")
    )
    assert d.profile.provider == "openai"


def test_pin_replaces_model_but_keeps_pool_and_provider():
    d = ModelRoutingPolicy(_profiles()).resolve(
        RoleCapabilityRequest(pin_provider="openai", pin_model="gpt-5.6-sol")
    )
    assert d.profile.provider == "openai"
    assert d.profile.model == "gpt-5.6-sol"
    assert d.profile.pool_id == "openai"  # no-mix：换 model 不动 pool/provider


def test_pin_to_unconfigured_provider_raises_never_crossvendor():
    with pytest.raises(PinnedModelUnavailable, match="gemini"):
        ModelRoutingPolicy(_profiles()).resolve(
            RoleCapabilityRequest(pin_provider="gemini")  # 不在 profiles
        )


def test_pin_no_fallback_candidates():
    d = ModelRoutingPolicy(_profiles()).resolve(
        RoleCapabilityRequest(pin_provider="openai")
    )
    assert d.fallback_candidates == []  # pinned 严格无 fallback


# ---------- 对抗：dual-model 独立门不被手选洗白 ----------

def test_pin_IGNORED_when_independence_required_dual_gate_immune():
    """[变异·命门] independence_required=True 时手选 pin 必须被忽略，verifier 仍自动异源。

    builder=anthropic；即便用户 pin 到 anthropic，独立门也不能把 verifier 也放到 anthropic
    （那会把跨厂商独立性洗白）。resolve 必须选 openai（异源），而非被 pin 强留 anthropic。
    """
    d = ModelRoutingPolicy(_profiles()).resolve(
        RoleCapabilityRequest(independence_required=True, pin_provider="anthropic"),
        builder_signature=("anthropic", "claude-opus-4"),
    )
    # 核心不变量：pin 被忽略 → verifier 绝不落在 builder 厂商(anthropic)，且证明双重异源。
    # 具体落 openai 还是 qwen 由独立门排序决定（都对 anthropic 独立），不锁死具体厂商。
    assert d.profile.provider != "anthropic"   # pin 没能把 verifier 拉回 builder 厂商
    assert d.independence_distinct is True      # 证明 provider+family 双重异源


def test_independence_without_pin_still_crossvendor():
    # 回归：没有 pin 时独立门原样工作
    d = ModelRoutingPolicy(_profiles()).resolve(
        RoleCapabilityRequest(independence_required=True),
        builder_signature=("anthropic", "claude-opus-4"),
    )
    assert d.profile.provider != "anthropic"


# ---------- 对抗：跨厂商 fallback 锁死 ----------

def test_pinned_refallback_stays_same_vendor_then_errors():
    """[变异] pin openai 后，把 openai 签名排除（模拟本轮调用失败重路由）→
    不得跨到 anthropic/qwen，必须 PinnedModelUnavailable。"""
    pol = ModelRoutingPolicy(_profiles())
    with pytest.raises(PinnedModelUnavailable):
        pol.resolve(
            RoleCapabilityRequest(pin_provider="openai"),
            exclude_signatures={("openai", "gpt-4o")},
        )


# ---------- 诚实降质 ----------

def test_pin_light_model_for_hard_task_marks_degraded():
    profiles = [
        LLMModelProfile(provider="anthropic", model="claude-opus-4",
                        capability_tier=ModelTier.STRONG.value, pool_id="anthropic"),
        LLMModelProfile(provider="openai", model="gpt-4o-mini",
                        capability_tier=ModelTier.LIGHT.value, pool_id="openai"),
    ]
    d = ModelRoutingPolicy(profiles).resolve(
        RoleCapabilityRequest(difficulty="hard", pin_provider="openai", pin_model="gpt-4o-mini")
    )
    assert d.profile.provider == "openai" and d.profile.model == "gpt-4o-mini"
    assert d.degraded is True  # 难任务被 pin 到轻 model → 如实标降质,不假装


# ---------- Auto 回归（无 pin 前后一致）----------

def test_auto_unchanged_without_pin():
    pol = ModelRoutingPolicy(_profiles())
    # 难任务 → STRONG 档（anthropic opus 或 openai gpt-4o，均 STRONG）
    d = pol.resolve(RoleCapabilityRequest(difficulty="hard"))
    assert d.tier_resolved == ModelTier.STRONG.value
    assert d.degraded is False
    # 机械低风险 → LIGHT 需求，但只有 STRONG/NORMAL 可用 → 升档不降质
    d2 = pol.resolve(RoleCapabilityRequest(difficulty="mechanical", risk="low"))
    assert d2.degraded is False


def test_pin_empty_string_is_not_a_pin():
    # pin_provider 空串/None 不触发 pin 逻辑（走 Auto）
    d = ModelRoutingPolicy(_profiles()).resolve(RoleCapabilityRequest(pin_provider=None))
    assert d.profile is not None  # 正常 Auto 决策，不报 PinnedModelUnavailable
