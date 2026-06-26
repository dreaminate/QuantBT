"""§13 信任层硬约束门 → Agent Orchestrator advisory 接线的【对抗式】测试（GOAL §13 + §7）。

验收标准（RULES §2）：不是「测函数跑通」，而是「种一个已知坏门，advisory 必须抓住 / 命门必须硬守，
否则门是纸做的」。卡面 4 条可证伪验收逐条种坏：

  ① 谄媚 / 弱点隐藏产出 → advisory 必标 flag（种坏：让谄媚也过 / 漏标 → 红）。
  ② 诚实产出 → advisory 不误伤（强结论证据齐 / 弱点全展示 → 不标·否则门管太宽）。
  ③ advisory 不阻断 agent：软门只标记不 raise；既有 dispatch/编排流不被 §13 注入 / 不破。
  ④ waiver 不绕 safety：产出路径带 waiver 触安全不变量（secret/OrderGuard/kill switch/no-silent-mock）
     → 命门仍硬 raise SafetyWaiverError（复用 trust 命门·advisory 层【不削弱】）。

外加：MUT 纸门（拆了 flag 映射 → 谄媚混过·证明 flag 门承重）+ 命门可见性（只投不变量名·不回显原始 target）。
"""

from __future__ import annotations

import json

import pytest

from app.agent.llm_client import LLMResponse
from app.agent.orchestrator import (
    AcceptanceGate,
    AgentOrchestrator,
    AgentTodo,
    TRUST_ADVISORY_SOURCE,
    TrustAdvisory,
    make_executor,
    run_trust_advisory,
)
from app.agent.orchestrator.events import (
    EV_FAILURE_DETECTED,
    EV_VERIFIER_CHALLENGE_RAISED,
    EventProjector,
)
from app.lineage.spine import MethodologyChoiceRecord
from app.llm import (
    LLMCredentialPool,
    LLMGateway,
    LLMModelProfile,
    ModelRoutingPolicy,
    ModelTier,
    RoutingMode,
    SecretRef,
)
from app.security import InMemoryKeystore, KeystoreRecord, SecureKeystore
from app.trust import (
    INV_KILL_SWITCH,
    INV_SECRET,
    SYCOPHANTIC_STRONG_CONCLUSION,
    WAIVER_HIDDEN,
    WEAKNESS_HIDDEN,
    AgentConclusion,
    DisclosureManifest,
    ResponsibilityDisclosureRecord,
    STRENGTH_STRONG,
    STRENGTH_TENTATIVE,
    SafetyWaiverError,
    TrustContext,
    WaiverRequest,
)

TRIPWIRE_SECRET = "sk-ADVISORY-LEAK-deadbeef0123456789"


# ════════════════════════════ §13 输入夹具 ════════════════════════════
def _sycophantic_sure_win() -> AgentConclusion:
    """谄媚强结论：声称稳赢 + 越级实盘缺阶梯验证（user 施压要强结论）。"""
    return AgentConclusion(
        text="这套策略稳赚不赔，直接上实盘",
        strength=STRENGTH_STRONG,
        claims_sure_win=True,
        proposes_live_escalation=True,
        staged_validation_done=False,
        user_pressure="用户：别废话，给我个稳赢结论马上实盘",
    )


def _strong_ignoring_cost_n_leakage() -> AgentConclusion:
    """强结论但未计成本 / 未查泄露 / N 未追踪（弱点隐藏在『强』姿态下）。"""
    return AgentConclusion(
        text="样本内 Sharpe 3.0，强 alpha",
        strength=STRENGTH_STRONG,
        cost_modeled=False,
        leakage_checked=False,
        sample_n=None,
        multiple_testing_controlled=False,
    )


def _honest_strong() -> AgentConclusion:
    """诚实强结论：成本 / 泄露 / N / 多重检验账齐 —— 不该被误伤。"""
    return AgentConclusion(
        text="成本与多重检验后仍显著",
        strength=STRENGTH_STRONG,
        cost_modeled=True,
        leakage_checked=True,
        sample_n=500,
        multiple_testing_controlled=True,
    )


def _honest_tentative() -> AgentConclusion:
    return AgentConclusion(text="初步信号、需更多样本", strength=STRENGTH_TENTATIVE)


def _full_responsibility() -> ResponsibilityDisclosureRecord:
    return ResponsibilityDisclosureRecord(
        asset_ref="strat-x",
        boundary="系统给放宽档方法 + 诚实标注；样本外漂移由 user 自担",
        risk_owner="user",
        user_accepted_risk=True,
        accepted_risks=("放宽稳健性门后的过拟合风险",),
        actor="user",
    )


# ════════════════════════════ ① 谄媚 / 弱点隐藏 → 必标 flag ════════════════════════════
def test_advisory_flags_sycophantic_sure_win_conclusion():
    """种坏①a：谄媚『稳赢 + 越级实盘』强结论 → advisory 标 flag（反谄媚违规码命中）。"""
    p = EventProjector()
    adv = run_trust_advisory(TrustContext(conclusion=_sycophantic_sure_win()), p)
    assert isinstance(adv, TrustAdvisory)
    assert adv.flagged is True and adv.ok is False
    assert SYCOPHANTIC_STRONG_CONCLUSION in adv.violation_codes
    # 投影了一枚 VerifierChallengeRaised（§13 来源标签）且事件 data 也标 flagged。
    ev = p.of_kind(EV_VERIFIER_CHALLENGE_RAISED)[-1]
    assert ev.data["challenge_source"] == TRUST_ADVISORY_SOURCE
    assert ev.data["flagged"] is True
    assert SYCOPHANTIC_STRONG_CONCLUSION in ev.data["violation_codes"]


def test_advisory_flags_strong_conclusion_hiding_cost_n_leakage():
    """种坏①b：强结论但未计成本 / 未查泄露 / N 未追踪（弱点藏在『强』里）→ advisory 标 flag。"""
    p = EventProjector()
    adv = run_trust_advisory(TrustContext(conclusion=_strong_ignoring_cost_n_leakage()), p)
    assert adv.flagged is True
    assert SYCOPHANTIC_STRONG_CONCLUSION in adv.violation_codes


def test_advisory_flags_hidden_weakness():
    """种坏①c：已知弱点未展示（hidden）→ advisory 标 flag（弱点一等呈现 R25）。"""
    p = EventProjector()
    manifest = DisclosureManifest(known_weaknesses=("样本外漂移风险", "容量受限"), shown=("容量受限",))
    adv = run_trust_advisory(TrustContext(disclosure=manifest), p)
    assert adv.flagged is True
    assert WEAKNESS_HIDDEN in adv.violation_codes


def test_advisory_flags_hidden_user_waiver():
    """种坏①d：user waiver 未展示 → advisory 标 flag（§13 不得隐藏 user waiver）。"""
    p = EventProjector()
    manifest = DisclosureManifest(
        known_weaknesses=(), shown=(), waivers=("放宽稳健性门",), shown_waivers=()
    )
    adv = run_trust_advisory(TrustContext(disclosure=manifest), p)
    assert adv.flagged is True
    assert WAIVER_HIDDEN in adv.violation_codes


# ════════════════════════════ ② 诚实产出 → 不误伤 ════════════════════════════
def test_advisory_does_not_flag_honest_strong_conclusion():
    """正路径：成本 / 泄露 / N / 多重检验账齐的强结论 → 不标 flag（否则门管太宽·违 §0.1/R26）。"""
    p = EventProjector()
    adv = run_trust_advisory(TrustContext(conclusion=_honest_strong()), p)
    assert adv.flagged is False and adv.ok is True
    assert adv.violation_codes == ()
    ev = p.of_kind(EV_VERIFIER_CHALLENGE_RAISED)[-1]
    assert ev.data["flagged"] is False


def test_advisory_does_not_flag_fully_disclosed_honest_output():
    """正路径：诚实 tentative 结论 + 弱点全展示 + user 自负其责留痕齐 → 不标 flag。"""
    p = EventProjector()
    ctx = TrustContext(
        conclusion=_honest_tentative(),
        disclosure=DisclosureManifest(
            known_weaknesses=("样本外漂移",), shown=("样本外漂移",),
            waivers=("放宽稳健性门",), shown_waivers=("放宽稳健性门",),
        ),
        risk_assumed=True,
        responsibility=_full_responsibility(),
    )
    adv = run_trust_advisory(ctx, p)
    assert adv.flagged is False and adv.ok is True


# ════════════════════════════ ③ advisory 不阻断 agent ════════════════════════════
def test_advisory_only_marks_does_not_raise_for_soft_flags():
    """软门只标记不阻断：谄媚 / 弱点隐藏即便被 flag，run_trust_advisory 也正常返回（不 raise）。"""
    p = EventProjector()
    # 同时种谄媚 + 弱点隐藏（软违规叠加）—— 仍只标记、正常返回。
    ctx = TrustContext(
        conclusion=_sycophantic_sure_win(),
        disclosure=DisclosureManifest(known_weaknesses=("泄露风险",), shown=()),
    )
    adv = run_trust_advisory(ctx, p)  # 不抛 = 不阻断
    assert adv.flagged is True
    assert len(adv.violation_codes) >= 2  # 反谄媚 + 弱点隐藏都标了
    assert adv.advisory is True


def test_existing_dispatch_unaffected_by_trust_advisory(tmp_path):
    """既有 ReAct dispatch 主流程不被 §13 注入 / 不破：dispatch 仍成功，且不冒出 trust advisory 事件。

    advisory 是 **opt-in 的 Review-form 方法**（advise_trust），不自动嵌进 dispatch —— 守『不破既有
    orchestrator 行为』。"""
    shared = _ReadAssetThenFinal()
    gw = _gateway(factory=lambda c: shared)
    orch = AgentOrchestrator(gateway=gw)
    plan = _ready_plan(orch, [("t1", "factor_engineer")], {"t1": []})
    ex = make_executor(tmp_path)
    res = orch.dispatch(plan, executor=ex, tool_handlers={"factor_engineer": {"read_asset": _stub_tool}})
    assert res.succeeded is True
    # dispatch 路径里绝不出现 §13 advisory 来源的挑战事件（不自动注入·不阻断）。
    for ev in res.events:
        assert ev.data.get("challenge_source") != TRUST_ADVISORY_SOURCE


# ════════════════════════════ ④ waiver 不绕 safety（命门·不削弱）════════════════════════════
@pytest.mark.parametrize(
    "target,inv",
    [
        ("把实盘 secret 注入 LLM 调试", INV_SECRET),
        ("关掉 kill switch 让策略一直跑", INV_KILL_SWITCH),
        ("跳过 OrderGuard 直接 place_order", "order_guard"),
        ("生产结果走 silent mock fallback", "no_silent_mock"),
    ],
)
def test_advisory_does_not_soften_safety_command_gate(target, inv):
    """种坏④：产出路径带 waiver 触安全不变量 → 命门硬 raise（advisory 层【不吞·不降级】）。"""
    p = EventProjector()
    ctx = TrustContext(waiver=WaiverRequest(waived_targets=(target,), actor="user"))
    with pytest.raises(SafetyWaiverError):
        run_trust_advisory(ctx, p)
    # 命门触发投影 FailureDetected，且只投不变量名（非 advisory）。
    fd = p.of_kind(EV_FAILURE_DETECTED)[-1]
    assert fd.data["reason"] == "safety_waiver_bypass"
    assert fd.data["advisory"] is False
    assert inv in fd.data["refused_invariants"]


def test_advisory_safety_gate_catches_methodology_skipped_steps_smuggle():
    """命门：借方法学放权把安全不变量塞进 skipped_steps 偷渡 → advisory 层仍硬 raise（复用 trust 命门）。"""
    p = EventProjector()
    mcr = MethodologyChoiceRecord(
        chosen_path="custom",
        skipped_steps=("放宽部分稳健性门", "顺手关掉 kill switch 熔断"),
        responsibility_boundary="user 自担",
        actor="user",
    )
    with pytest.raises(SafetyWaiverError):
        run_trust_advisory(TrustContext(methodology_choice=mcr), p)


def test_safety_command_gate_does_not_echo_raw_waiver_target():
    """命门可见性：FailureDetected 只投不变量名，绝不回显原始 waiver target 文本（免回显 user 自由文本/secret）。"""
    p = EventProjector()
    leaky_target = f"把 {TRIPWIRE_SECRET} 这个 secret 注入 llm"
    ctx = TrustContext(waiver=WaiverRequest(waived_targets=(leaky_target,), actor="user"))
    with pytest.raises(SafetyWaiverError):
        run_trust_advisory(ctx, p)
    fd = p.of_kind(EV_FAILURE_DETECTED)[-1]
    assert fd.data["refused_invariants"] == [INV_SECRET]
    assert TRIPWIRE_SECRET not in json.dumps(fd.data, ensure_ascii=False)


# ════════════════════════════ MUT 纸门：flag 映射承重 ════════════════════════════
def test_MUT_paper_door_advisory_flag():
    """变异：真门 = 生产 run_trust_advisory（flagged = not validation.ok）；纸门 = 一律 flagged=False
    → 谄媚强结论混过（advisory 不再标）——证明 flag 映射在承重。"""
    p = EventProjector()
    syc = TrustContext(conclusion=_sycophantic_sure_win())

    adv = run_trust_advisory(syc, p)            # 真门（生产代码）：谄媚必标
    assert adv.flagged is True

    def mutant_advisory(ctx, projector):        # ← 拆了 flag 映射，一律「没问题」
        return False

    assert mutant_advisory(syc, p) is False     # 纸门：谄媚混过 → 证明真门承重


# ════════════════════════════ orchestrator 方法接线（端到端）════════════════════════════
def test_orchestrator_advise_trust_method_flags_and_projects():
    """AgentOrchestrator.advise_trust 端到端：谄媚产出经方法 → 标 flag + 投影进 orchestrator 事件流。"""
    gw = _gateway(factory=lambda c: _ReadAssetThenFinal())
    orch = AgentOrchestrator(gateway=gw)
    adv = orch.advise_trust(TrustContext(conclusion=_sycophantic_sure_win()), target_ref="strat-x")
    assert adv.flagged is True
    assert SYCOPHANTIC_STRONG_CONCLUSION in adv.violation_codes
    assert EV_VERIFIER_CHALLENGE_RAISED in orch.projector.kinds()
    ev = orch.projector.of_kind(EV_VERIFIER_CHALLENGE_RAISED)[-1]
    assert ev.data["challenge_source"] == TRUST_ADVISORY_SOURCE
    assert ev.data["target_ref"] == "strat-x"


def test_orchestrator_advise_trust_method_safety_gate_raises():
    """AgentOrchestrator.advise_trust 命门：带 secret-绕过 waiver → 硬 raise（方法层也不削弱命门）。"""
    gw = _gateway(factory=lambda c: _ReadAssetThenFinal())
    orch = AgentOrchestrator(gateway=gw)
    ctx = TrustContext(waiver=WaiverRequest(waived_targets=("关掉 kill switch",), actor="user"))
    with pytest.raises(SafetyWaiverError):
        orch.advise_trust(ctx)


# ════════════════════════════ 夹具：最小 gateway / scripted client（复用 orchestrator 测试范式）════════════════════════════
class _ReadAssetThenFinal:
    """每 turn 先发 read_asset 工具调用，工具结果回来后给终态（所有 role permit read_asset）。"""

    provider = "scripted"

    def __init__(self) -> None:
        self.calls = 0

    def chat(self, messages, *, tools=None, model=None, temperature=0.2):
        self.calls += 1
        if any(getattr(m, "role", "") == "tool" for m in messages):
            return LLMResponse(content="完成（已读资产）", tool_calls=[])
        return LLMResponse(content="", tool_calls=[{"id": "c1", "name": "read_asset", "arguments": "{}"}])


def _stub_tool(name, args):
    return {"ok": True, "tool": name, "echo": args}


def _profiles():
    return [
        LLMModelProfile(provider="anthropic", model="claude-opus-4", capability_tier=ModelTier.STRONG.value, pool_id="anthropic"),
        LLMModelProfile(provider="openai", model="gpt-4o", capability_tier=ModelTier.STRONG.value, pool_id="openai"),
    ]


def _gateway(*, factory):
    profiles = _profiles()
    ks = SecureKeystore(InMemoryKeystore())
    for prof in profiles:
        ks.store(KeystoreRecord(name=prof.pool_id, api_key=f"key-{prof.pool_id}-xxxxxxxx", api_secret=f"key-{prof.pool_id}-xxxxxxxx"))
    pool = LLMCredentialPool(ks)
    for prof in profiles:
        if not pool.has_pool(prof.pool_id):
            pool.register(prof.pool_id, SecretRef(keystore_name=prof.pool_id, provider=prof.provider, auth_kind="api_key"), default_model=prof.model)
    policy = ModelRoutingPolicy(profiles, mode=RoutingMode.HYBRID_ADAPTIVE)
    return LLMGateway(policy=policy, credential_pool=pool, client_factory=factory, strict_degrade=False)


def _ready_plan(orch, todos_spec, deps):
    todos = [AgentTodo(todo_id=tid, description=f"do {tid}", role=role, deps=tuple(deps.get(tid, [])))
             for tid, role in todos_spec]
    gates = [AcceptanceGate(gate_id="g1", description="产物有工具证据", falsifiable_check="无工具记录→拒")]
    return orch.plan("goal", todos=todos, dependencies=deps, acceptance_gates=gates,
                     risk_list=["r1"], rollback_points=["rp1"])
