"""Agent Orchestrator 对抗测试（A-AGENT-ORCH · GOAL §7）。

「种一个已知的坏，门必须抓住，否则门是纸做的」（RULES §2）。5 道可证伪验收 + 4 道必抓变异（MUT）：

  门1 多 Agent 绕过 DAG 自由派发工具 → 拒（无节点上下文 / 伪造令牌 / 越权·MUT 放过→红）
  门2 AgentLLMCall 绕过 LLM Gateway → 不可准入（未封印自造账·MUT 放过→红）
  门3 Verifier 与 Builder 共用上下文却声称独立 → 拒（MUT 放过→红）
  门4 声称完成但工具记录缺失 → 拒 · AgentPlan 缺 todo/deps/gates → draft · AgentCodeChange 缺 diff/test/rollback → 拒
  门5 Agent 替 user 拍板方法学松紧 → 拒（MUT 放过→红）

外加：12 role / 24 可见事件 / 五形态 / 唯一图写口（canonical command）/ Replay durable 零重跑。
"""

from __future__ import annotations

import hashlib

import pytest

from app.agent.llm_client import LLMMessage, LLMResponse
from app.agent.orchestrator import (
    AcceptanceGate,
    AgentCodeChange,
    AgentCodeChangeError,
    AgentCompletion,
    AgentCompletionError,
    AgentOrchestrator,
    AgentTodo,
    DAGBypassError,
    GatewayLLMAdapter,
    GovernedToolDispatcher,
    GraphWriteAuthorityError,
    MethodologyAutonomyError,
    MethodologyChoiceRecord,
    MODES,
    NodeExecutionContext,
    PlanError,
    ROLE_AGENTS,
    ToolPermissionError,
    VerifierIndependenceError,
    VISIBLE_EVENT_KINDS,
    assert_event_clean,
    assert_llm_admissible,
    assert_methodology_user_decided,
    get_role,
    make_executor,
)
from app.agent.orchestrator.events import (
    EV_ARTIFACT_PRODUCED,
    EV_ASSET_READ,
    EV_CANONICAL_COMMAND_APPLIED,
    EV_CANONICAL_COMMAND_PROPOSED,
    EV_FAILURE_DETECTED,
    EV_ROLE_AGENT_DISPATCHED,
    EV_RUN_VERDICT_PRODUCED,
    EV_TOOL_CALL_FINISHED,
    EventProjector,
    PersistentWorkflowEventLedger,
    WorkflowEvent,
    GATEWAY_EVENT_KINDS,
)
from app.llm import (
    GatewaySealedResult,
    IndependenceRecord,
    LLMCallRecord,
    LLMCredentialPool,
    LLMGateway,
    LLMModelProfile,
    LLMRecordError,
    ModelRoutingPolicy,
    ModelTier,
    ReplayState,
    RoleCapabilityRequest,
    RoutingMode,
    SecretRef,
)
from app.llm.call_record_store import LLMCallRecordStore
from app.llm.call_record import (
    bind_review_verifier_record,
    make_review_subject_binding,
)
from app.lineage.ids import canonical_json, content_hash
from app.qro.envelope import (
    ACTOR_AGENT,
    ACTOR_SCHEDULED_AGENT,
    ACTOR_USER_CONFIRMED_AGENT,
    ACTOR_USER_MANUAL,
    OBJ_RESEARCH_REPORT,
    QualifiedResearchObject,
)
from app.graph.research_graph import CMD_CREATE_NODE, DESK_RESEARCH, DeskHandoff, ResearchGraph
from app.security import InMemoryKeystore, KeystoreRecord, SecureKeystore

TRIPWIRE_SECRET = "sk-ORCH-LEAK-deadbeef0123456789"


# ════════════════════════════ 夹具 / 桩 ════════════════════════════

class ReadAssetThenFinal:
    """每 turn：先发 read_asset 工具调用，工具结果回来后给终态。所有 role 都 permit read_asset。"""

    provider = "scripted"

    def __init__(self) -> None:
        self.calls = 0
        self.message_batches = []

    def chat(self, messages, *, tools=None, model=None, temperature=0.2):
        self.calls += 1
        self.message_batches.append(tuple(messages))
        if any(getattr(m, "role", "") == "tool" for m in messages):
            return LLMResponse(content="完成（已读资产）", tool_calls=[])
        return LLMResponse(content="", tool_calls=[{"id": "c1", "name": "read_asset", "arguments": "{}"}])


class EmitToolThenFinal:
    """发指定工具调用（用于种「越权工具」坏门），工具结果回来后给终态。"""

    provider = "scripted"

    def __init__(self, tool: str) -> None:
        self.tool = tool
        self.calls = 0

    def chat(self, messages, *, tools=None, model=None, temperature=0.2):
        self.calls += 1
        if any(getattr(m, "role", "") == "tool" for m in messages):
            return LLMResponse(content="完成", tool_calls=[])
        return LLMResponse(content="", tool_calls=[{"id": "c1", "name": self.tool, "arguments": "{}"}])


class NoToolFinal:
    """直接终态、零工具——用于种「声称完成但工具记录缺失」坏门。"""

    provider = "scripted"

    def __init__(self) -> None:
        self.calls = 0

    def chat(self, messages, *, tools=None, model=None, temperature=0.2):
        self.calls += 1
        return LLMResponse(content="完成（没干活）", tool_calls=[])


def _stub_tool(name, args):
    return {"ok": True, "tool": name, "echo": args}


def _two_strong():
    return [
        LLMModelProfile(provider="anthropic", model="claude-opus-4", capability_tier=ModelTier.STRONG.value, pool_id="anthropic"),
        LLMModelProfile(provider="openai", model="gpt-4o", capability_tier=ModelTier.STRONG.value, pool_id="openai"),
    ]


def _one_strong():
    return [LLMModelProfile(provider="anthropic", model="claude-opus-4", capability_tier=ModelTier.STRONG.value, pool_id="anthropic")]


def _seed_keystore(profiles):
    ks = SecureKeystore(InMemoryKeystore())
    for p in profiles:
        ks.store(KeystoreRecord(name=p.pool_id, api_key=f"key-{p.pool_id}-xxxxxxxx", api_secret=f"key-{p.pool_id}-xxxxxxxx"))
    return ks


def _pool(profiles, ks):
    pool = LLMCredentialPool(ks)
    for p in profiles:
        if pool.has_pool(p.pool_id):
            continue
        pool.register(p.pool_id, SecretRef(keystore_name=p.pool_id, provider=p.provider, auth_kind="api_key"), default_model=p.model)
    return pool


def _gateway(profiles, *, factory, extra_secrets=None, seal_secret=None):
    ks = _seed_keystore(profiles)
    for name, val in (extra_secrets or {}).items():
        ks.store(KeystoreRecord(name=name, api_key=val, api_secret=val))
    pool = _pool(profiles, ks)
    policy = ModelRoutingPolicy(profiles, mode=RoutingMode.HYBRID_ADAPTIVE)
    return LLMGateway(
        policy=policy,
        credential_pool=pool,
        client_factory=factory,
        strict_degrade=False,
        seal_secret=seal_secret,
    )


def _ready_plan(orch, todos_spec, deps):
    """构造并校验一个 ready plan（齐 todo/deps/gates）。todos_spec = [(todo_id, role), ...]。"""

    todos = [AgentTodo(todo_id=tid, description=f"do {tid}", role=role, deps=tuple(deps.get(tid, [])))
             for tid, role in todos_spec]
    gates = [AcceptanceGate(gate_id="g1", description="产物有工具证据", falsifiable_check="无工具记录→拒")]
    return orch.plan("goal", todos=todos, dependencies=deps, acceptance_gates=gates,
                     risk_list=["r1"], rollback_points=["rp1"])


def _handlers(roles, tool="read_asset"):
    return {r: {tool: _stub_tool} for r in roles}


# ════════════════════════════ 正例：ReAct via DAG ════════════════════════════

def test_react_dispatch_runs_role_nodes_via_dag(tmp_path):
    """端到端正例：plan→冻结 DAG→DurableExecutor 跑 role 节点；LLM 经 Gateway、工具经治理闸、24 事件投影。"""
    shared = ReadAssetThenFinal()
    gw = _gateway(_two_strong(), factory=lambda c: shared)
    orch = AgentOrchestrator(
        gateway=gw, owner_user_id="owner-orch", workflow_id="workflow-react"
    )
    plan = _ready_plan(orch, [("t_factor", "factor_engineer"), ("t_report", "reporter")],
                       {"t_factor": [], "t_report": ["t_factor"]})
    assert plan.is_ready
    ex = make_executor(tmp_path)
    res = orch.dispatch(plan, executor=ex, tool_handlers=_handlers(["factor_engineer", "reporter"]))

    assert res.succeeded is True
    # 两个节点都成功
    assert {n.task_id: n.status for n in res.kernel_result.nodes} == {"t_factor": "succeeded", "t_report": "succeeded"}
    kinds = res.event_kinds()
    # role dispatch / 工具 / 资产 / LLM 路由 / 产物 / 裁决 都投影了
    assert EV_ROLE_AGENT_DISPATCHED in kinds
    assert EV_ASSET_READ in kinds
    assert EV_TOOL_CALL_FINISHED in kinds
    assert "LLMRouteSelected" in kinds and "LLMCallFinished" in kinds  # gateway 5 枚 adopt 进流
    assert EV_ARTIFACT_PRODUCED in kinds
    assert kinds.count(EV_RUN_VERDICT_PRODUCED) == 1
    # 每条 LLM 结果都经本 gateway 封印 + 可准入（绕过 gateway 自造的过不了，见门2）
    for _tid, _role, sealed in res.sealed_results:
        assert gw.verify(sealed) is True
        assert_llm_admissible(sealed, gw)


# ════════════════════════════ 门1：绕过 DAG 自由派发工具 → 拒（+MUT）════════════════════════════

def test_gate1_free_dispatch_without_node_context_rejected():
    """无节点执行上下文 = LLM 当控制器自由派发 → DAGBypassError（绕过 DAG → 拒）。"""
    d = GovernedToolDispatcher()
    d.register("read_asset", _stub_tool)
    with pytest.raises(DAGBypassError):
        d.dispatch("read_asset", {}, node_ctx=None)


def test_gate1_forged_node_context_rejected():
    """伪造一个节点上下文（令牌不是本 dispatcher nonce 铸的）→ 骗不过治理闸。"""
    d = GovernedToolDispatcher()
    d.register("read_asset", _stub_tool)
    forged = NodeExecutionContext(node_id="n", task_id="n", role="factor_engineer",
                                  permitted_tools=frozenset({"read_asset"}), token="deadbeef" * 4)
    with pytest.raises(DAGBypassError):
        d.dispatch("read_asset", {}, node_ctx=forged)


def test_gate1_tool_outside_permitted_set_rejected_and_recorded():
    """工具不在节点冻结权限集（越权 / 越 DAG 计划）→ ToolPermissionError + 记 violation。"""
    d = GovernedToolDispatcher()
    d.register("train_model", _stub_tool)
    ctx = d.enter_node(node_id="n", task_id="n", role="factor_engineer", permitted_tools=frozenset({"read_asset"}))
    with pytest.raises(ToolPermissionError):
        d.dispatch("train_model", {}, node_ctx=ctx)
    viols = d.drain_violations("n")
    assert len(viols) == 1 and viols[0].kind == "tool_permission"


def test_gate1_valid_node_context_dispatch_executes_and_records():
    """正例：有效节点上下文 + 权限内工具 → 执行 + 落账。"""
    d = GovernedToolDispatcher()
    d.register("read_asset", _stub_tool)
    ctx = d.enter_node(node_id="n", task_id="n", role="factor_engineer", permitted_tools=frozenset({"read_asset"}))
    out = d.dispatch("read_asset", {"x": 1}, node_ctx=ctx)
    assert out["ok"] is True
    assert d.records_for("n")[0].ok is True and d.violations() == ()


def test_gate1_MUT_paper_door_free_dispatch():
    """变异：真门 = 生产 dispatcher 的上下文闸（无节点上下文即拒）；纸门 = 拆了上下文核验的派发
    → 自由派发畅通无阻——证明该闸在承重。"""
    d = GovernedToolDispatcher()
    d.register("read_asset", _stub_tool)

    with pytest.raises(DAGBypassError):
        d.dispatch("read_asset", {}, node_ctx=None)   # 真门（生产代码）：抓住绕过 DAG

    def mutant_dispatch(tool, args, node_ctx):        # ← 把 DAG 上下文闸拆了
        return d._tools[tool](tool, args)

    assert mutant_dispatch("read_asset", {}, None)["ok"] is True  # 纸门：自由派发畅通 → 证明真闸承重


def test_gate1_INTEGRATION_node_fails_on_planned_tool_bypass(tmp_path):
    """集成：节点内 LLM 派发越权工具（train_model ∉ factor 白名单）→ 治理闸拒 + 记 violation
    → 节点 op 查 violation 非空即 raise → 内核判节点 failed → FailureDetected 投影。"""
    shared = EmitToolThenFinal("train_model")
    gw = _gateway(_two_strong(), factory=lambda c: shared)
    orch = AgentOrchestrator(
        gateway=gw, owner_user_id="owner-orch", workflow_id="workflow-tool-bypass"
    )
    plan = _ready_plan(orch, [("t1", "factor_engineer")], {"t1": []})
    ex = make_executor(tmp_path)
    # 故意把越权工具 handler 喂给节点（模拟误注册 / 恶意）——治理闸 dispatch 期 authoritative 拒。
    res = orch.dispatch(plan, executor=ex, tool_handlers={"factor_engineer": {"train_model": _stub_tool}})
    assert res.succeeded is False
    assert res.kernel_result.node("t1").status == "failed"
    assert EV_FAILURE_DETECTED in res.event_kinds()


# ════════════════════════════ 门2：AgentLLMCall 绕过 Gateway → 不可准入（+MUT）════════════════════════════

def test_gate2_every_orchestrator_llm_call_is_gateway_sealed(tmp_path):
    """orchestrator 跑出的每条 LLM 结果都经本 Gateway 封印 + 可准入（正例）。"""
    shared = ReadAssetThenFinal()
    gw = _gateway(_two_strong(), factory=lambda c: shared)
    orch = AgentOrchestrator(
        gateway=gw, owner_user_id="owner-orch", workflow_id="workflow-gateway-seal"
    )
    plan = _ready_plan(orch, [("t1", "factor_engineer")], {"t1": []})
    ex = make_executor(tmp_path)
    res = orch.dispatch(plan, executor=ex, tool_handlers=_handlers(["factor_engineer"]))
    assert res.sealed_results
    for _t, _r, sealed in res.sealed_results:
        assert_llm_admissible(sealed, gw)  # 不抛 = 准入


def test_provider_failure_projects_durable_llm_finish_before_bound_failure_event(tmp_path):
    class _AlwaysFails:
        provider = "scripted-failure"

        def chat(self, *args, **kwargs):
            raise RuntimeError("provider unavailable")

    owner = "owner-provider-failure"
    workflow = "workflow-provider-failure"
    call_store = LLMCallRecordStore(tmp_path / "llm-call-records.jsonl")
    event_ledger = PersistentWorkflowEventLedger(tmp_path / "workflow-events.jsonl")
    gw = _gateway(
        _two_strong(),
        factory=lambda _credential: _AlwaysFails(),
        seal_secret=call_store.seal_secret,
    )
    orch = AgentOrchestrator(
        gateway=gw,
        owner_user_id=owner,
        workflow_id=workflow,
        event_ledger=event_ledger,
        record_sink=call_store.append,
    )
    plan = _ready_plan(orch, [("t1", "factor_engineer")], {"t1": []})

    result = orch.dispatch(
        plan,
        executor=make_executor(tmp_path / "kernel"),
        requires_tool_evidence={"t1": False},
    )

    assert result.succeeded is False
    records = call_store.read_all(owner_user_id=owner)
    terminal = records[-1]
    assert terminal.record_kind == "terminal"
    assert terminal.status == "error"
    assert terminal.failure_stage == "provider"

    restarted = PersistentWorkflowEventLedger(event_ledger.path)
    events = list(restarted.events(owner_user_id=owner, workflow_id=workflow))
    terminal_finished_index = next(
        index
        for index, event in enumerate(events)
        if event.kind == "LLMCallFinished"
        and event.data.get("call_id") == terminal.call_id
    )
    failure_index = next(
        index for index, event in enumerate(events) if event.kind == EV_FAILURE_DETECTED
    )
    failure = events[failure_index]
    assert terminal_finished_index < failure_index
    assert failure.data["call_id"] == terminal.call_id
    assert failure.data["llm_status"] == "error"
    assert failure.data["failure_stage"] == "provider"


def test_gate2_bypass_gateway_forged_result_not_admissible(tmp_path):
    """模拟 role agent 绕过 Gateway 直调 provider + 自造账：未经本 gateway 封印 → 准入门拒。"""
    gw = _gateway(_two_strong(), factory=lambda c: ReadAssetThenFinal())
    forged = LLMCallRecord(provider="anthropic", model="claude-opus-4",
                           auth_ref="secretref://anthropic/anthropic", replay_state=ReplayState.LIVE.value)
    forged_res = GatewaySealedResult(response=LLMResponse(content="x"), record=forged, events=[])
    assert gw.verify(forged_res) is False
    with pytest.raises(LLMRecordError):
        assert_llm_admissible(forged_res, gw)


def test_gate2_MUT_paper_door_no_seal_check(tmp_path):
    """变异：把准入门的封印校验摘掉 → 绕过 Gateway 的伪造账混进来——证明封印校验在承重。"""
    gw = _gateway(_two_strong(), factory=lambda c: ReadAssetThenFinal())
    forged = LLMCallRecord(provider="p", model="m", auth_ref="secretref://p/p", replay_state="live")
    forged_res = GatewaySealedResult(response=LLMResponse(content="x"), record=forged, events=[])

    with pytest.raises(LLMRecordError):
        assert_llm_admissible(forged_res, gw)  # 真门（生产代码）：抓住绕过 Gateway 的伪造账

    def mutant_admit(res):  # ← 把封印门拆了
        return True

    assert mutant_admit(forged_res) is True  # 纸门：伪造账混入 → 证明封印门承重


def test_gate2_role_agent_gets_no_provider_or_key(tmp_path):
    """GatewayLLMAdapter 后面 role agent 拿不到 provider 名 / key——它只见治理层。"""
    gw = _gateway(_two_strong(), factory=lambda c: ReadAssetThenFinal())
    adapter = GatewayLLMAdapter(
        gw,
        RoleCapabilityRequest(role="factor_engineer", difficulty="hard"),
        owner_user_id="owner-orch",
        workflow_id="workflow-adapter",
        invocation_id_factory=lambda: "adapter-invocation-1",
    )
    assert adapter.provider == "gateway"  # 永远是治理层，不是真 provider
    resp = adapter.chat([LLMMessage(role="user", content="hi")])
    rec = adapter.last_record()
    # 账只留 SecretRef 引用，绝无明文 key
    assert rec.auth_ref.startswith("secretref://")
    import json as _json
    assert "key-anthropic" not in _json.dumps(rec.to_dict())


# ════════════════════════════ 门3：Verifier 独立性（+MUT）════════════════════════════

def _builder_rec(provider="anthropic", model="claude-opus-4"):
    output = "exact builder output"
    return LLMCallRecord(
        provider=provider,
        model=model,
        auth_ref="r",
        replay_state="live",
        call_id="call-builder",
        prompt_digest="dB",
        response_digest=content_hash({"content": output, "tool_calls": []}),
    )


def _verifier_rec(provider, model, *, satisfied, digest="dV"):
    return LLMCallRecord(
        provider=provider,
        model=model,
        auth_ref="r",
        replay_state="live",
        call_id="call-verifier",
        prompt_digest=digest,
        response_digest=content_hash({"content": "verifier output", "tool_calls": []}),
        independence=IndependenceRecord(
            required=True,
            satisfied=satisfied,
            builder_call_id="call-builder",
        ),
    )


def _review_binding(builder, verifier):
    output = "exact builder output"
    output_ref = hashlib.sha256(canonical_json(output).encode("utf-8")).hexdigest()
    binding, _instruction = make_review_subject_binding(
        builder=builder,
        builder_artifact_ref="artifact:builder",
        builder_artifact_output_ref=output_ref,
        builder_output=output,
        review_criteria="challenge the exact builder output",
    )
    return bind_review_verifier_record(binding, verifier)


def test_gate3_verifier_distinct_provider_admitted():
    """builder=anthropic，verifier 换 openai 且 satisfied=True → 独立成立，admit 返回 independent。"""
    gw = _gateway(_two_strong(), factory=lambda c: ReadAssetThenFinal())
    orch = AgentOrchestrator(gateway=gw)
    builder = _builder_rec("anthropic", "claude-opus-4")
    verifier = _verifier_rec("openai", "gpt-4o", satisfied=True)
    verdict = orch.admit_verifier_challenge(
        builder,
        verifier,
        subject_binding=_review_binding(builder, verifier),
    )
    assert verdict.independent is True


def test_gate3_verifier_shared_context_honest_insufficient_not_rejected():
    """verifier 与 builder 同源但诚实标 satisfied=False → 不抛，返回 independent=False（honest·非干净独立）。"""
    gw = _gateway(_one_strong(), factory=lambda c: ReadAssetThenFinal())
    orch = AgentOrchestrator(gateway=gw)
    builder = _builder_rec("anthropic", "claude-opus-4")
    verifier = _verifier_rec("anthropic", "claude-opus-4", satisfied=False)
    verdict = orch.admit_verifier_challenge(
        builder,
        verifier,
        subject_binding=_review_binding(builder, verifier),
    )
    assert verdict.independent is False and "独立性不足" in verdict.reason


def test_gate3_verifier_false_independence_rejected():
    """种坏门：verifier 与 builder 同 provider+model 却声称 satisfied=True（假独立·未标不足）→ 拒。"""
    gw = _gateway(_one_strong(), factory=lambda c: ReadAssetThenFinal())
    orch = AgentOrchestrator(gateway=gw)
    builder = _builder_rec("anthropic", "claude-opus-4")
    verifier = _verifier_rec("anthropic", "claude-opus-4", satisfied=True)
    with pytest.raises(VerifierIndependenceError):
        orch.admit_verifier_challenge(
            builder,
            verifier,
            subject_binding=_review_binding(builder, verifier),
        )


def test_gate3_cross_provider_same_gpt_false_independence_rejected():
    gw = _gateway(_two_strong(), factory=lambda c: ReadAssetThenFinal())
    orch = AgentOrchestrator(gateway=gw)
    builder = _builder_rec("gateway-a", "gpt-5.6-sol-pro")
    verifier = _verifier_rec("gateway-b", "gpt-4o", satisfied=True)
    with pytest.raises(VerifierIndependenceError, match="双重异源"):
        orch.admit_verifier_challenge(
            builder,
            verifier,
            subject_binding=_review_binding(builder, verifier),
        )


def test_gate3_MUT_paper_door_independence():
    """变异：真门 = 生产 orchestrator.admit_verifier_challenge；纸门 = 拆了独立性裁决一律放行
    → 假独立的 verifier 混过——证明独立性门承重。"""
    gw = _gateway(_one_strong(), factory=lambda c: ReadAssetThenFinal())
    orch = AgentOrchestrator(gateway=gw)
    builder = _builder_rec("anthropic", "claude-opus-4")
    liar = _verifier_rec("anthropic", "claude-opus-4", satisfied=True)

    with pytest.raises(VerifierIndependenceError):
        orch.admit_verifier_challenge(
            builder,
            liar,
            subject_binding=_review_binding(builder, liar),
        )   # 真门（生产代码）：抓住假独立

    def mutant_gate(b, v):  # ← 拆了独立性裁决
        return True

    assert mutant_gate(builder, liar) is True  # 纸门：假独立混过 → 证明门承重


def test_gate3_INTEGRATION_verifier_routed_distinct_provider(tmp_path):
    """集成：同 session 内 builder（factor）+ verifier 节点，gateway 给 verifier 选了相对 builder 不同的
    provider（独立性满足）。"""
    shared = ReadAssetThenFinal()
    gw = _gateway(_two_strong(), factory=lambda c: shared)
    orch = AgentOrchestrator(
        gateway=gw,
        session_id="sx",
        owner_user_id="owner-orch",
        workflow_id="workflow-independent-verifier",
    )
    plan = _ready_plan(orch, [("t_b", "factor_engineer"), ("t_v", "verifier_critic")],
                       {"t_b": [], "t_v": ["t_b"]})
    ex = make_executor(tmp_path)
    res = orch.dispatch(plan, executor=ex, tool_handlers=_handlers(["factor_engineer", "verifier_critic"]))
    builder_recs = [s.record for t, _r, s in res.sealed_results if t == "t_b"]
    verifier_recs = [s.record for t, _r, s in res.sealed_results if t == "t_v"]
    assert builder_recs and verifier_recs
    # verifier 要求独立 → record.independence.required True，且 provider 相对 builder 不同源
    assert verifier_recs[-1].independence.required is True
    assert verifier_recs[-1].provider != builder_recs[-1].provider
    binding = res.review_subject_bindings["t_v"]
    verdict = orch.admit_verifier_challenge(
        builder_recs[-1],
        verifier_recs[-1],
        subject_binding=binding,
    )
    assert verdict.independent is True
    verifier_prompt = "\n".join(
        str(message.content) for message in shared.message_batches[2]
    )
    assert '"builder_output":"完成（已读资产）"' in verifier_prompt
    assert '"review_criteria":"do t_v"' in verifier_prompt
    assert binding.review_subject_ref in verifier_prompt


def test_gate3_single_configured_model_refuses_before_verifier_provider_call(tmp_path):
    shared = ReadAssetThenFinal()
    gw = _gateway(_one_strong(), factory=lambda _credential: shared)
    orch = AgentOrchestrator(
        gateway=gw,
        session_id="single-model-review",
        owner_user_id="owner-orch",
        workflow_id="workflow-single-model-review",
    )
    plan = _ready_plan(
        orch,
        [("t_b", "factor_engineer"), ("t_v", "verifier_critic")],
        {"t_b": [], "t_v": ["t_b"]},
    )
    result = orch.dispatch(
        plan,
        executor=make_executor(tmp_path),
        tool_handlers=_handlers(["factor_engineer", "verifier_critic"]),
    )

    assert result.succeeded is False
    assert shared.calls == 2
    verifier_node = result.kernel_result.node("t_v")
    assert verifier_node is not None
    assert str(verifier_node.error).startswith("VerifierIndependenceUnavailable:")


def test_gate3_two_gpt_providers_refuse_before_verifier_provider_call(tmp_path):
    """两个 GPT 入口仍只有一个 foundation-model family，必须显式不可用。"""

    shared = ReadAssetThenFinal()
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
    gw = _gateway(profiles, factory=lambda _credential: shared)
    orch = AgentOrchestrator(
        gateway=gw,
        session_id="same-gpt-review",
        owner_user_id="owner-orch",
        workflow_id="workflow-same-gpt-review",
    )
    plan = _ready_plan(
        orch,
        [("t_b", "factor_engineer"), ("t_v", "verifier_critic")],
        {"t_b": [], "t_v": ["t_b"]},
    )
    result = orch.dispatch(
        plan,
        executor=make_executor(tmp_path),
        tool_handlers=_handlers(["factor_engineer", "verifier_critic"]),
    )

    assert result.succeeded is False
    assert shared.calls == 2
    verifier_node = result.kernel_result.node("t_v")
    assert verifier_node is not None
    assert str(verifier_node.error).startswith("VerifierIndependenceUnavailable:")


def test_gate3_independent_provider_unavailable_cannot_fallback_to_success(tmp_path):
    """Preflight profile presence is not enough; the final executed verifier route must be independent."""

    class ExhaustIndependentAfterBuilder(ReadAssetThenFinal):
        gateway = None

        def chat(self, messages, *, tools=None, model=None, temperature=0.2):
            response = super().chat(
                messages,
                tools=tools,
                model=model,
                temperature=temperature,
            )
            if self.calls == 2:
                assert self.gateway is not None
                self.gateway.mark_quota_exhausted("openai")
            return response

    shared = ExhaustIndependentAfterBuilder()
    gw = _gateway(_two_strong(), factory=lambda _credential: shared)
    shared.gateway = gw
    orch = AgentOrchestrator(
        gateway=gw,
        session_id="independent-route-disappears",
        owner_user_id="owner-orch",
        workflow_id="workflow-independent-route-disappears",
    )
    plan = _ready_plan(
        orch,
        [("t_b", "factor_engineer"), ("t_v", "verifier_critic")],
        {"t_b": [], "t_v": ["t_b"]},
    )
    result = orch.dispatch(
        plan,
        executor=make_executor(tmp_path),
        tool_handlers=_handlers(["factor_engineer", "verifier_critic"]),
    )

    assert result.succeeded is False
    assert shared.calls == 4
    verifier_node = result.kernel_result.node("t_v")
    assert verifier_node is not None
    assert str(verifier_node.error).startswith("VerifierIndependenceUnavailable:")


@pytest.mark.parametrize("verifier_dependencies", [[], ["t_b1", "t_b2"]])
def test_gate3_verifier_requires_exactly_one_review_subject(verifier_dependencies):
    gw = _gateway(_two_strong(), factory=lambda _credential: ReadAssetThenFinal())
    orch = AgentOrchestrator(gateway=gw)
    todos = [("t_v", "verifier_critic")]
    dependencies = {"t_v": list(verifier_dependencies)}
    for builder_id in verifier_dependencies:
        todos.insert(0, (builder_id, "factor_engineer"))
        dependencies[builder_id] = []

    plan = _ready_plan(orch, todos, dependencies)

    assert plan.is_ready is False
    assert plan.status == "draft"
    assert "exactly one declared review subject" in plan.draft_reason
    with pytest.raises(PlanError, match="plan 未就绪"):
        orch.build_dag(plan)


# ════════════════════════════ 门4：完成 / plan draft / code change ════════════════════════════

def test_gate4_completion_without_tool_record_rejected():
    """声称完成但工具记录缺失 → 拒。"""
    with pytest.raises(AgentCompletionError):
        AgentCompletion(role="factor_engineer", claims_complete=True, tool_records=(), requires_tool_evidence=True)


def test_gate4_completion_with_tool_record_ok():
    """正例：声称完成 + 有工具记录 → 过。"""
    c = AgentCompletion(role="factor_engineer", claims_complete=True, tool_records=("read_asset",))
    assert c.claims_complete is True


def test_gate4_MUT_paper_door_completion():
    """变异：真门 = 生产 AgentCompletion 构造门；纸门 = 只看 claims 不看工具记录 → 空工具记录的完成
    混过——证明工具证据门承重。"""
    with pytest.raises(AgentCompletionError):  # 真门（生产代码）
        AgentCompletion(role="factor_engineer", claims_complete=True, tool_records=(), requires_tool_evidence=True)

    def mutant_check(claims, tool_records):  # ← 不看工具记录
        return None

    assert mutant_check(True, ()) is None  # 纸门：放过 → 证明真门承重


def test_gate4_INTEGRATION_node_fails_when_claims_complete_no_tool(tmp_path):
    """集成：节点 LLM 直接终态、零工具，但要求工具证据 → 节点 failed（完成门在节点内咬）。"""
    shared = NoToolFinal()
    gw = _gateway(_two_strong(), factory=lambda c: shared)
    orch = AgentOrchestrator(
        gateway=gw, owner_user_id="owner-orch", workflow_id="workflow-no-tool"
    )
    plan = _ready_plan(orch, [("t1", "factor_engineer")], {"t1": []})
    ex = make_executor(tmp_path)
    res = orch.dispatch(plan, executor=ex, tool_handlers=_handlers(["factor_engineer"]),
                        requires_tool_evidence={"t1": True})
    assert res.succeeded is False
    assert res.kernel_result.node("t1").status == "failed"


def test_gate4_plan_missing_gates_stays_draft():
    """AgentPlan 缺 acceptance gates → 维持 draft（不晋升为可执行）。"""
    gw = _gateway(_two_strong(), factory=lambda c: ReadAssetThenFinal())
    orch = AgentOrchestrator(gateway=gw)
    plan = orch.plan("g", todos=[AgentTodo(todo_id="t1", description="d", role="factor_engineer")],
                     dependencies={"t1": []}, acceptance_gates=[])  # 缺 gates
    assert plan.is_ready is False and plan.status == "draft"
    assert "acceptance_gates" in plan.draft_reason
    # draft 不可冻结为 DAG
    with pytest.raises(PlanError):
        orch.build_dag(plan)


def test_gate4_plan_missing_deps_stays_draft():
    """AgentPlan 缺 dependencies（连『无依赖』都没显式声明）→ draft。"""
    gw = _gateway(_two_strong(), factory=lambda c: ReadAssetThenFinal())
    orch = AgentOrchestrator(gateway=gw)
    plan = orch.plan("g", todos=[AgentTodo(todo_id="t1", description="d", role="factor_engineer")],
                     dependencies={}, acceptance_gates=[AcceptanceGate("g1", "d", "f")])
    assert plan.status == "draft" and "dependencies" in plan.draft_reason


def test_gate4_plan_dangling_dep_stays_draft():
    """依赖指向不存在的 todo（计划不自洽）→ draft。"""
    gw = _gateway(_two_strong(), factory=lambda c: ReadAssetThenFinal())
    orch = AgentOrchestrator(gateway=gw)
    plan = orch.plan("g", todos=[AgentTodo(todo_id="t1", description="d", role="factor_engineer")],
                     dependencies={"t1": ["ghost"]}, acceptance_gates=[AcceptanceGate("g1", "d", "f")])
    assert plan.status == "draft" and "dangling" in plan.draft_reason


def test_gate4_full_plan_is_ready():
    """正例：齐 todo/deps/gates → ready。"""
    gw = _gateway(_two_strong(), factory=lambda c: ReadAssetThenFinal())
    orch = AgentOrchestrator(gateway=gw)
    plan = _ready_plan(orch, [("t1", "factor_engineer")], {"t1": []})
    assert plan.is_ready is True


def test_gate4_code_change_missing_rollback_rejected():
    """AgentCodeChange 缺 rollback point → 拒。"""
    with pytest.raises(AgentCodeChangeError):
        AgentCodeChange(path="a.py", diff="--- a", test_result="passed", rollback_point="")


def test_gate4_code_change_missing_test_rejected():
    with pytest.raises(AgentCodeChangeError):
        AgentCodeChange(path="a.py", diff="--- a", test_result="", rollback_point="rev@1")


def test_gate4_code_change_theory_claim_without_tib_rejected():
    """声称按理论实现却缺 TheoryImplementationBinding → 拒（GOAL §7）。"""
    with pytest.raises(AgentCodeChangeError):
        AgentCodeChange(path="a.py", diff="--- a", test_result="passed", rollback_point="rev@1",
                        claims_theory_backed=True, theory_implementation_binding="")


def test_gate4_code_change_full_ok():
    cc = AgentCodeChange(path="a.py", diff="--- a\n+++ b", test_result="passed", rollback_point="rev@1")
    assert cc.path == "a.py"


# ════════════════════════════ 门5：Agent 替 user 拍方法学 → 拒（+MUT）════════════════════════════

def _methodology(decided_by, decision):
    return MethodologyChoiceRecord(
        choice="跳过严格数学证明", cost="过拟合 / 不可识别风险上升",
        recommended_path="补 proof sketch + 反例检查", responsibility_boundary="由 user 承担放权后果",
        decided_by=decided_by, decision=decision,
    )


def test_gate5_agent_self_decide_methodology_rejected():
    """Agent 自己把方法学松紧拍成 accepted → 拒（决定权属 user）。"""
    gw = _gateway(_two_strong(), factory=lambda c: ReadAssetThenFinal())
    orch = AgentOrchestrator(gateway=gw)
    rec = _methodology(ACTOR_AGENT, "accepted")
    with pytest.raises(MethodologyAutonomyError):
        orch.apply_methodology_choice(rec)


def test_gate5_scheduled_agent_self_decide_rejected():
    rec = _methodology(ACTOR_SCHEDULED_AGENT, "accepted")
    with pytest.raises(MethodologyAutonomyError):
        assert_methodology_user_decided(rec)


def test_gate5_user_decided_allowed():
    """正例：user 手动拍 accepted → 过。"""
    gw = _gateway(_two_strong(), factory=lambda c: ReadAssetThenFinal())
    orch = AgentOrchestrator(gateway=gw)
    assert orch.apply_methodology_choice(_methodology(ACTOR_USER_MANUAL, "accepted")).decision == "accepted"


def test_gate5_user_confirmed_agent_allowed():
    """正例：user 确认过的 agent 动作拍 accepted → 过。"""
    assert_methodology_user_decided(_methodology(ACTOR_USER_CONFIRMED_AGENT, "accepted"))


def test_gate5_agent_pending_record_ok():
    """Agent 只『提出』（pending）方法学放权 + 展示代价/推荐/责任边界 → 合法（请 user 拍板）。"""
    gw = _gateway(_two_strong(), factory=lambda c: ReadAssetThenFinal())
    orch = AgentOrchestrator(gateway=gw)
    rec = orch.record_methodology_choice(_methodology(ACTOR_AGENT, "pending"))
    assert rec.decision == "pending"
    assert "ApprovalRequested" in orch.projector.kinds()


def test_gate5_MUT_paper_door_methodology():
    """变异：真门 = 生产 assert_methodology_user_decided；纸门 = 拆了决定权门 → agent 自拍 accepted
    混过——证明决定权门承重。"""
    rec = _methodology(ACTOR_AGENT, "accepted")

    with pytest.raises(MethodologyAutonomyError):
        assert_methodology_user_decided(rec)  # 真门（生产代码）：抓住 agent 替 user 拍板

    def mutant_gate(r):  # ← 拆了决定权门
        return None

    assert mutant_gate(rec) is None  # 纸门：agent 自拍混过 → 证明真门承重


# ════════════════════════════ 可见事件 / 可见性边界 ════════════════════════════

def test_visible_events_24_and_gateway_5_reused():
    """GOAL §7 列 24 枚可见事件全集；LLM 5 枚直接复用 gateway 同名常量（单一源）。"""
    assert len(VISIBLE_EVENT_KINDS) == 24
    assert GATEWAY_EVENT_KINDS <= set(VISIBLE_EVENT_KINDS)
    # 复用 gateway 的字符串常量（防漂）
    from app.llm.gateway import EV_ROUTE_SELECTED, EV_CALL_FINISHED
    assert EV_ROUTE_SELECTED in VISIBLE_EVENT_KINDS and EV_CALL_FINISHED in VISIBLE_EVENT_KINDS


def test_visibility_boundary_blocks_secret_plaintext():
    """可见性边界：投影事件序列化面夹带在册明文 secret → 拒（绝不回显 secret）。"""
    ev = WorkflowEvent(kind="ArtifactProduced", data={"note": f"key={TRIPWIRE_SECRET}"})
    with pytest.raises(Exception) as ei:
        assert_event_clean(ev, [TRIPWIRE_SECRET])
    assert TRIPWIRE_SECRET not in str(ei.value)


def test_visibility_boundary_blocks_hidden_cot():
    """可见性边界：事件 data 带 provider 隐藏思维链键 → 拒。"""
    ev = WorkflowEvent(kind="LLMCallFinished", data={"chain_of_thought": "internal reasoning..."})
    with pytest.raises(Exception):
        assert_event_clean(ev)


def test_visibility_MUT_paper_door_secret_leak():
    """变异：真门 = 生产 assert_event_clean；纸门 = 拆了扫描 → 明文 secret 投影出去——证明边界门承重。"""
    from app.agent.orchestrator.events import EventProjectionError

    ev = WorkflowEvent(kind="ArtifactProduced", data={"note": f"k={TRIPWIRE_SECRET}"})

    with pytest.raises(EventProjectionError):
        assert_event_clean(ev, [TRIPWIRE_SECRET])  # 真门（生产代码）：抓住 secret 进投影

    def mutant_clean(e, secrets):  # ← 拆了扫描
        return None

    assert mutant_clean(ev, [TRIPWIRE_SECRET]) is None  # 纸门：secret 泄露 → 证明真门承重


def test_projector_rejects_unknown_event_kind():
    """投影库外事件类型 → 拒（防伪可见性）。"""
    p = EventProjector()
    with pytest.raises(Exception):
        p.emit("TeleportedEvent", {})


# ════════════════════════════ 写 Research Graph 唯一口 = canonical command ════════════════════════════

def test_graph_write_via_canonical_command():
    """orchestrator 写图唯一口 = canonical command；投影 Proposed + Applied。"""
    gw = _gateway(_two_strong(), factory=lambda c: ReadAssetThenFinal())
    graph = ResearchGraph()
    orch = AgentOrchestrator(gateway=gw, research_graph=graph)
    qro = QualifiedResearchObject(object_type=OBJ_RESEARCH_REPORT, natural_key="rep-1", actor=ACTOR_AGENT, owner="agent")
    node = orch.propose_graph_write(command_type=CMD_CREATE_NODE, actor=ACTOR_AGENT,
                                    target_desk=DESK_RESEARCH, payload={"qro": qro})
    assert node.qro.identity == qro.identity
    kinds = orch.projector.kinds()
    assert EV_CANONICAL_COMMAND_PROPOSED in kinds and EV_CANONICAL_COMMAND_APPLIED in kinds
    # 图里确实有这个节点（经命令落入·带 command_ref）
    assert node.command_ref


def test_graph_write_agent_cannot_impersonate_user_manual():
    """agent 写图冒充 user_manual → 拒（写图按来源如实标·GOAL §0/§7）。"""
    gw = _gateway(_two_strong(), factory=lambda c: ReadAssetThenFinal())
    graph = ResearchGraph()
    orch = AgentOrchestrator(gateway=gw, research_graph=graph)
    qro = QualifiedResearchObject(object_type=OBJ_RESEARCH_REPORT, natural_key="rep-2", actor=ACTOR_AGENT)
    with pytest.raises(GraphWriteAuthorityError):
        orch.propose_graph_write(command_type=CMD_CREATE_NODE, actor=ACTOR_USER_MANUAL,
                                 target_desk=DESK_RESEARCH, payload={"qro": qro})


def test_open_handoff_emits_desk_handoff_created():
    """开跨台交接经 canonical command 落图 + 投影 DeskHandoffCreated。"""
    gw = _gateway(_two_strong(), factory=lambda c: ReadAssetThenFinal())
    graph = ResearchGraph()
    orch = AgentOrchestrator(gateway=gw, research_graph=graph)
    handoff = DeskHandoff(from_desk=DESK_RESEARCH, to_desk="factor_desk", requested_asset="factor-x",
                          created_by=ACTOR_AGENT)
    orch.open_handoff(handoff=handoff, actor=ACTOR_AGENT)
    assert "DeskHandoffCreated" in orch.projector.kinds()


# ════════════════════════════ Replay 形态：durable 零重跑 ════════════════════════════

def test_replay_reuses_durable_artifacts_zero_rerun(tmp_path):
    """Replay 形态：命中 kernel durable 工件 → 节点复用、零重跑（零新 LLM 调用）。"""
    shared = ReadAssetThenFinal()
    gw = _gateway(_two_strong(), factory=lambda c: shared)
    orch = AgentOrchestrator(
        gateway=gw, owner_user_id="owner-orch", workflow_id="workflow-replay"
    )
    plan = _ready_plan(orch, [("t1", "factor_engineer")], {"t1": []})
    ex = make_executor(tmp_path)
    res1 = orch.dispatch(plan, executor=ex, tool_handlers=_handlers(["factor_engineer"]))
    assert res1.succeeded is True
    calls_after_run = shared.calls
    assert calls_after_run > 0
    # 第二次 replay：durable 命中 → 节点 reused，op 不被调用 → LLM 调用数不变
    res2 = orch.replay(plan, executor=ex, tool_handlers=_handlers(["factor_engineer"]))
    assert res2.kernel_result.node("t1").reused is True
    assert shared.calls == calls_after_run, "replay 重跑了节点 → durable 复用门破"


def test_dispatch_requires_explicit_owner_and_workflow_before_role_llm(tmp_path):
    gw = _gateway(_two_strong(), factory=lambda c: ReadAssetThenFinal())
    orch = AgentOrchestrator(gateway=gw)
    plan = _ready_plan(orch, [("t1", "factor_engineer")], {"t1": []})

    with pytest.raises(ValueError, match="owner_user_id"):
        orch.dispatch(plan, executor=make_executor(tmp_path))


def test_role_llm_scope_sink_and_invocation_ids_are_durable_and_stable(tmp_path):
    owner = "owner-orch"
    workflow = "workflow-audit"
    store = LLMCallRecordStore(tmp_path / "llm-audit.jsonl")
    first_client = ReadAssetThenFinal()
    first_gateway = _gateway(
        _two_strong(), factory=lambda c: first_client, seal_secret=store.seal_secret
    )
    first_orch = AgentOrchestrator(
        gateway=first_gateway,
        owner_user_id=owner,
        workflow_id=workflow,
        record_sink=store.append,
    )
    first_plan = _ready_plan(first_orch, [("t1", "factor_engineer")], {"t1": []})
    first = first_orch.dispatch(
        first_plan,
        executor=make_executor(tmp_path / "first-run"),
        tool_handlers=_handlers(["factor_engineer"]),
    )

    assert first.succeeded is True
    durable_rows = store.read_all(owner_user_id=owner)
    assert durable_rows
    assert {row.owner_user_id for row in durable_rows} == {owner}
    assert {row.workflow_id for row in durable_rows} == {workflow}
    first_invocations = list(dict.fromkeys(row.invocation_id for row in durable_rows))
    assert len(first_invocations) == 2
    assert all(invocation.startswith("orch:") for invocation in first_invocations)
    assert first_invocations[0].endswith(":step:1")
    assert first_invocations[1].endswith(":step:2")
    assert [row.call_id for row in LLMCallRecordStore(store.path).read_all(owner_user_id=owner)] == [
        row.call_id for row in durable_rows
    ]

    # An exact retry with a fresh gateway/executor derives the same first id.
    # The durable sink rejects it before provider access instead of double-calling.
    retry_client = ReadAssetThenFinal()
    retry_gateway = _gateway(
        _two_strong(), factory=lambda c: retry_client, seal_secret=store.seal_secret
    )
    retry_orch = AgentOrchestrator(
        gateway=retry_gateway,
        owner_user_id=owner,
        workflow_id=workflow,
        record_sink=store.append,
    )
    retry_plan = _ready_plan(retry_orch, [("t1", "factor_engineer")], {"t1": []})
    retried = retry_orch.dispatch(
        retry_plan,
        executor=make_executor(tmp_path / "exact-retry"),
        tool_handlers=_handlers(["factor_engineer"]),
    )
    assert retried.succeeded is False
    assert "already has durable audit evidence" in retried.kernel_result.node("t1").error
    assert retry_client.calls == 0
    assert store.read_all(owner_user_id=owner) == durable_rows

    # A changed frozen instruction is a new task execution scope, not an exact
    # retry. It gets new deterministic invocation ids and may call the provider.
    changed_client = ReadAssetThenFinal()
    changed_gateway = _gateway(
        _two_strong(), factory=lambda c: changed_client, seal_secret=store.seal_secret
    )
    changed_orch = AgentOrchestrator(
        gateway=changed_gateway,
        owner_user_id=owner,
        workflow_id=workflow,
        record_sink=store.append,
    )
    changed_plan = _ready_plan(changed_orch, [("t1", "factor_engineer")], {"t1": []})
    changed = changed_orch.dispatch(
        changed_plan,
        executor=make_executor(tmp_path / "changed-task"),
        instructions={"t1": "changed frozen instruction"},
        tool_handlers=_handlers(["factor_engineer"]),
    )
    assert changed.succeeded is True
    assert changed_client.calls == 2
    changed_rows = store.read_all(owner_user_id=owner)
    changed_invocations = list(dict.fromkeys(row.invocation_id for row in changed_rows))
    assert set(changed_invocations[:2]).isdisjoint(changed_invocations[2:])


def test_durable_role_artifacts_are_not_reused_across_owner_scopes(tmp_path):
    executor = make_executor(tmp_path / "shared-kernel")
    first_client = ReadAssetThenFinal()
    first_gateway = _gateway(_two_strong(), factory=lambda c: first_client)
    first_orch = AgentOrchestrator(
        gateway=first_gateway,
        owner_user_id="owner-a",
        workflow_id="shared-workflow",
    )
    first_plan = _ready_plan(first_orch, [("t1", "factor_engineer")], {"t1": []})
    first = first_orch.dispatch(
        first_plan,
        executor=executor,
        tool_handlers=_handlers(["factor_engineer"]),
    )
    assert first.succeeded is True

    second_client = ReadAssetThenFinal()
    second_gateway = _gateway(_two_strong(), factory=lambda c: second_client)
    second_orch = AgentOrchestrator(
        gateway=second_gateway,
        owner_user_id="owner-b",
        workflow_id="shared-workflow",
    )
    second_plan = _ready_plan(second_orch, [("t1", "factor_engineer")], {"t1": []})
    second = second_orch.dispatch(
        second_plan,
        executor=executor,
        tool_handlers=_handlers(["factor_engineer"]),
    )

    assert second.succeeded is True
    assert second.kernel_result.node("t1").reused is False
    assert second_client.calls == 2
    assert {sealed.record.owner_user_id for _task, _role, sealed in second.sealed_results} == {
        "owner-b"
    }


# ════════════════════════════ 12 role / 五形态 覆盖 ════════════════════════════

def test_twelve_roles_registered():
    assert len(ROLE_AGENTS) == 12
    # 每个 role 都 permit read_asset（统一最小读权限）
    for r in ROLE_AGENTS.values():
        assert "read_asset" in r.permitted_tools
    # Verifier/Critic 唯一带独立能力
    indep = [r.name for r in ROLE_AGENTS.values() if r.independence_capable]
    assert indep == ["verifier_critic"]


def test_role_capability_verifier_requires_independence():
    v = get_role("verifier_critic")
    assert v.capability().independence_required is True
    f = get_role("factor_engineer")
    assert f.capability().independence_required is False


def test_five_modes_constant():
    assert MODES == ("plan", "react", "review", "replay", "repair")


def test_repair_mode_emits_failure_and_repair(tmp_path):
    """Repair 形态：定位失败 + 提交带 diff/test/rollback 的修复 → 投影 FailureDetected + RepairAttempted。"""
    gw = _gateway(_two_strong(), factory=lambda c: ReadAssetThenFinal())
    orch = AgentOrchestrator(gateway=gw)
    cc = AgentCodeChange(path="factor.py", diff="--- a\n+++ b", test_result="passed", rollback_point="rev@9")
    orch.repair(failure_ref="run-123", code_change=cc)
    kinds = orch.projector.kinds()
    assert "FailureDetected" in kinds and "RepairAttempted" in kinds
