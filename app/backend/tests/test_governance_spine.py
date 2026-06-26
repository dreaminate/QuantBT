"""治理脊柱 · §8 硬不变量统一核查门的【对抗式】测试（GOAL §8 · RULES §2）。

验收不是「函数跑通」，是「**种一个已知坏门，统一核查门必抓，否则门是纸做的**」。七条硬不变量
各种坏（MUT·绝不 git checkout·全在测试内造坏 evidence）+ 正路径不误伤 + 聚合裁定 + 诚实层：

  ① CanvasMutation 未落 canonical command（绕命令通道直写图）→ 拒（收编 A-CMD assert_single_channel）
  ② AgentAction 越权派发（scoped permission 破）/ 暴露面夹带在册明文 secret → 拒
  ③ AgentPlan 缺 todo/deps/acceptance gates（维持 draft）→ 拒
  ④ AgentCodeChange 缺 diff/test/rollback → 拒
  ⑤ RoleAgentAction 无可见事件 / 有可见事件但无 audit record → 拒
  ⑥ SecretPlaintext 漏出 Settings（进 LLMCallRecord/导出/日志面）→ 拒
  ⑦ AgentDataAccess 持明文 key（非 SecretRef）/ 随行偷渡明文 secret → 拒
  ⑧ 七条全齐 → 放行（正路径不误伤）；任一违反 → 统一裁定 allowed=False + 点名 clause
  ⑨ 诚实层：收编登记恰好覆盖七条 + delegated/mixed 标注 + 拒绝口径无越权正向断言（自检）
"""

from __future__ import annotations

import pytest

from app.agent.orchestrator.events import EV_ROLE_AGENT_DISPATCHED, WorkflowEvent
from app.agent.orchestrator.governance import (
    GovernedToolDispatcher,
    ToolCallRecord,
    ToolPermissionError,
)
from app.agent.orchestrator.plan import AcceptanceGate, AgentPlan, AgentTodo
from app.command.canonical_command import (
    ACTION_CREATE_ASSET,
    ORIGIN_CANVAS,
    CommandBus,
    CommandIntent,
    manual_provenance,
)
from app.graph.research_graph import (
    CMD_CREATE_NODE,
    DESK_FACTOR,
    DESK_STRATEGY,
    CanonicalCommand,
    ResearchGraph,
)
from app.llm.call_record import LLMCallRecord
from app.llm.credential_pool import SecretRef
from app.qro.envelope import (
    ACTOR_AGENT,
    ACTOR_USER_MANUAL,
    OBJ_FACTOR,
    OBJ_STRATEGY_BOOK,
    QualifiedResearchObject,
)

from app.governance import (
    CLAUSES,
    ENFORCEMENT_BINDINGS,
    INV_AGENT_ACTION,
    INV_AGENT_CODE_CHANGE,
    INV_AGENT_DATA_ACCESS,
    INV_AGENT_PLAN,
    INV_CANVAS_MUTATION,
    INV_ROLE_AGENT_ACTION,
    INV_SECRET_PLAINTEXT,
    AgentActionEvidence,
    CodeChangeEvidence,
    DataAccessEvidence,
    GovernanceSpineGate,
    GovernanceSpineViolation,
    RoleActionEvidence,
    SecretSurfaceEvidence,
    SpineEvidence,
    check_agent_action,
    check_agent_code_change,
    check_agent_data_access,
    check_agent_plan,
    check_canvas_mutation,
    check_role_agent_action,
    check_secret_plaintext,
)
from app.governance.spine_invariants import STATUS_DELEGATED, STATUS_MIXED, BANNED_IN_REJECTION

# 一条够长（≥ MIN_SECRET_SCAN_LEN=8）的假「在册明文 secret」——绝非真 key，仅测扫描门。
SECRET = "sk-LIVEKEY-9f8e7d6c5b4a3210"
GOOD_REF = "secretref://anthropic/llm_anthropic"


# ─────────────────────────── 公共 fixture 工厂 ───────────────────────────
def _factor_qro(nk: str = "mom@v1") -> QualifiedResearchObject:
    return QualifiedResearchObject(object_type=OBJ_FACTOR, natural_key=nk, actor=ACTOR_USER_MANUAL)


def _strategy_qro(nk: str = "strat1") -> QualifiedResearchObject:
    return QualifiedResearchObject(object_type=OBJ_STRATEGY_BOOK, natural_key=nk, actor=ACTOR_AGENT)


def _good_bus() -> CommandBus:
    """合法 bus：一条经命令通道铸入的 canonical command（图账 ⊆ 通道账）。"""

    bus = CommandBus()
    bus.submit(CommandIntent(
        action=ACTION_CREATE_ASSET, target_desk=DESK_FACTOR,
        provenance=manual_provenance(ORIGIN_CANVAS), args={"qro": _factor_qro()},
    ))
    return bus


def _bypass_bus() -> CommandBus:
    """坏 bus（MUT）：绕命令通道直接 graph.apply（canvas mutation 未落 canonical command 通道·账无此命令）。"""

    graph = ResearchGraph()
    bus = CommandBus(graph)
    bus.submit(CommandIntent(
        action=ACTION_CREATE_ASSET, target_desk=DESK_FACTOR,
        provenance=manual_provenance(ORIGIN_CANVAS), args={"qro": _factor_qro()},
    ))
    rogue = CanonicalCommand(
        command_type=CMD_CREATE_NODE, actor=ACTOR_AGENT, target_desk=DESK_STRATEGY,
        payload={"qro": _strategy_qro()}, origin="rogue",
    )
    graph.apply(rogue)  # 绕通道直写图
    return bus


def _good_dispatcher(node_id: str = "n1") -> GovernedToolDispatcher:
    disp = GovernedToolDispatcher()
    disp.register("read_asset", lambda name, args: {"ok": True})
    ctx = disp.enter_node(node_id=node_id, task_id=node_id, role="data_engineer",
                          permitted_tools=frozenset({"read_asset"}))
    disp.dispatch("read_asset", {}, node_ctx=ctx)
    disp.exit_node(ctx)
    return disp


def _good_plan() -> AgentPlan:
    return AgentPlan(
        goal="build factor",
        todos=[AgentTodo(todo_id="t1", description="define factor", role="factor_engineer")],
        dependencies={"t1": []},
        acceptance_gates=[AcceptanceGate(gate_id="g1", description="IC>0", falsifiable_check="IC<=0 → 拒")],
    )


def _role_event(role: str = "data_engineer", node_id: str = "n1") -> WorkflowEvent:
    return WorkflowEvent(kind=EV_ROLE_AGENT_DISPATCHED, role=role, node_id=node_id)


def _audit_record(node_id: str = "n1") -> ToolCallRecord:
    return ToolCallRecord(tool="read_asset", node_id=node_id, task_id=node_id, role="data_engineer", ok=True)


# ═══════════════ ① CanvasMutation ⇒ canonical versioned command ═══════════════
def test_canvas_mutation_good_passes():
    res = check_canvas_mutation(_good_bus())
    assert res.passed and res.checked
    assert res.enforcement_status == STATUS_DELEGATED  # 收编 A-CMD·全权已 enforce


def test_canvas_mutation_bypass_rejected():
    """★ 卡点 MUT：绕命令通道直写图（canvas mutation 未落 canonical command）→ 统一门必抓。"""

    res = check_canvas_mutation(_bypass_bus())
    assert not res.passed
    assert res.clause == INV_CANVAS_MUTATION
    assert "未落 canonical" in res.violation


# ═══════════════ ② AgentAction ⇒ scoped permission + tool record + no secret ═══════════════
def test_agent_action_good_passes():
    res = check_agent_action(dispatcher=_good_dispatcher("n1"), node_id="n1")
    assert res.passed
    assert res.enforcement_status == STATUS_MIXED  # 收编派发闸 + 本门补 no-secret 缺口


def test_agent_action_unpermitted_tool_rejected():
    """★ MUT：节点派发越权工具（scoped permission 破）→ 派发闸留 violation → 统一门必抓。"""

    disp = GovernedToolDispatcher()
    ctx = disp.enter_node(node_id="n9", task_id="n9", role="data_engineer",
                          permitted_tools=frozenset({"read_asset"}))
    with pytest.raises(ToolPermissionError):
        disp.dispatch("forbidden_tool", {}, node_ctx=ctx)  # 越权 → 抛 + 记 violation
    res = check_agent_action(dispatcher=disp, node_id="n9")
    assert not res.passed
    assert "scoped permission 破" in res.violation


def test_agent_action_secret_in_exposed_payload_rejected():
    """★ MUT（本门补的真缺口）：action 暴露面（工具入参/结果）夹带在册明文 secret → 拒。"""

    disp = GovernedToolDispatcher()  # 无 violation·但暴露面带 secret
    res = check_agent_action(
        dispatcher=disp, node_id="n3",
        exposed_payload={"tool_arg": SECRET, "note": "leaked into asset"}, secret_values=[SECRET],
    )
    assert not res.passed
    assert "明文 secret" in res.violation
    assert SECRET not in res.violation  # 绝不回显 secret 本身


# ═══════════════ ③ AgentPlan ⇒ todo + deps + acceptance gates ═══════════════
def test_agent_plan_ready_passes():
    res = check_agent_plan(_good_plan())
    assert res.passed and res.enforcement_status == STATUS_DELEGATED


def test_agent_plan_missing_gates_rejected():
    """★ MUT：plan 缺 acceptance_gates → 维持 draft（不晋升）→ 统一门必抓。"""

    bad = AgentPlan(
        goal="g", todos=[AgentTodo(todo_id="t1", description="x", role="factor_engineer")],
        dependencies={"t1": []}, acceptance_gates=[],
    )
    res = check_agent_plan(bad)
    assert not res.passed
    assert res.clause == INV_AGENT_PLAN and "draft" in res.violation


# ═══════════════ ④ AgentCodeChange ⇒ diff + test + rollback ═══════════════
def test_agent_code_change_complete_passes():
    res = check_agent_code_change(diff="--- a\n+++ b", test_result="pytest 12 passed", rollback_point="rev abc")
    assert res.passed


def test_agent_code_change_missing_rollback_rejected():
    """★ MUT：AgentCodeChange 缺 rollback_point → AgentCodeChangeError → 统一门必抓。"""

    res = check_agent_code_change(diff="--- a\n+++ b", test_result="ok", rollback_point="")
    assert not res.passed
    assert res.clause == INV_AGENT_CODE_CHANGE


# ═══════════════ ⑤ RoleAgentAction ⇒ visible event + audit record ═══════════════
def test_role_agent_action_visible_and_audited_passes():
    res = check_role_agent_action(
        events=[_role_event()], role="data_engineer", node_id="n1", audit_records=[_audit_record()],
    )
    assert res.passed and res.enforcement_status == STATUS_MIXED


def test_role_agent_action_no_visible_event_rejected():
    """★ MUT：role 动作无任何投影到 user 的可见事件（执行黑箱）→ 拒。"""

    res = check_role_agent_action(events=[], role="data_engineer", node_id="n1", audit_records=[_audit_record()])
    assert not res.passed and "可见 workflow event" in res.violation


def test_role_agent_action_no_audit_record_rejected():
    """★ MUT：有可见事件但无 audit record（不可审计）→ 拒。"""

    res = check_role_agent_action(events=[_role_event()], role="data_engineer", node_id="n1", audit_records=[])
    assert not res.passed and "audit record" in res.violation


# ═══════════════ ⑥ SecretPlaintext ⇒ Settings only ═══════════════
def test_secret_plaintext_clean_surface_passes():
    res = check_secret_plaintext(surface={"auth_ref": GOOD_REF, "model": "claude"}, secret_values=[SECRET])
    assert res.passed


def test_secret_plaintext_leak_in_dict_rejected():
    """★ MUT：在册明文 secret 进导出/日志面 → 拒（绝不回显 secret）。"""

    res = check_secret_plaintext(surface={"api_key": SECRET}, secret_values=[SECRET])
    assert not res.passed
    assert "漏出 Settings" in res.violation and SECRET not in res.violation


def test_secret_plaintext_leak_in_llm_call_record_rejected():
    """★ MUT：明文 secret 进 LLMCallRecord 序列化面 → 收编 assert_no_plaintext_secret 抓。"""

    leaky = LLMCallRecord(provider="anthropic", model="claude", auth_ref=GOOD_REF,
                          replay_state="live", session_id=SECRET)
    res = check_secret_plaintext(surface=leaky, secret_values=[SECRET])
    assert not res.passed and SECRET not in res.violation


def test_secret_plaintext_clean_llm_call_record_passes():
    clean = LLMCallRecord(provider="anthropic", model="claude", auth_ref=GOOD_REF, replay_state="live")
    res = check_secret_plaintext(surface=clean, secret_values=[SECRET])
    assert res.passed


# ═══════════════ ⑦ AgentDataAccess ⇒ SecretRef only ═══════════════
def test_agent_data_access_secretref_passes():
    res = check_agent_data_access(auth_ref=GOOD_REF)
    assert res.passed
    # 也接受直接传 SecretRef 对象（取其 .ref）。
    res2 = check_agent_data_access(auth_ref=SecretRef(keystore_name="llm_anthropic", provider="anthropic"))
    assert res2.passed


def test_agent_data_access_plaintext_key_rejected():
    """★ MUT：数据访问持明文 key（非 secretref://）→ 拒。"""

    res = check_agent_data_access(auth_ref=SECRET)
    assert not res.passed
    assert res.clause == INV_AGENT_DATA_ACCESS
    assert SECRET not in res.violation  # 绝不整串回显（万一是真明文 key）


def test_agent_data_access_secret_smuggled_in_payload_rejected():
    """★ MUT：auth_ref 是合法 SecretRef，但随行暴露面偷渡明文 secret → 拒。"""

    res = check_agent_data_access(auth_ref=GOOD_REF, accompanying_payload={"x": SECRET}, secret_values=[SECRET])
    assert not res.passed and "偷渡" in res.violation


def test_agent_data_access_malformed_ref_rejected():
    """坏 scheme（缺 provider/name）→ round-trip 对齐单一源 SecretRef 失败 → 拒。"""

    for bad in ("secretref://", "secretref://anthropic", "secretref:///name", "http://x/y"):
        assert not check_agent_data_access(auth_ref=bad).passed


# ═══════════════ ⑧ 统一门聚合：全齐放行 / 任一违反拒绝 ═══════════════
def _all_good_evidence() -> SpineEvidence:
    return SpineEvidence(
        canvas_mutation=_good_bus(),
        agent_action=AgentActionEvidence(dispatcher=_good_dispatcher("n1"), node_id="n1"),
        agent_plan=_good_plan(),
        agent_code_change=CodeChangeEvidence(diff="d", test_result="ok", rollback_point="r"),
        role_agent_action=RoleActionEvidence(events=(_role_event(),), role="data_engineer",
                                             node_id="n1", audit_records=(_audit_record(),)),
        secret_plaintext=SecretSurfaceEvidence(surface={"clean": "x"}, secret_values=(SECRET,)),
        agent_data_access=DataAccessEvidence(auth_ref=GOOD_REF),
    )


def test_unified_all_invariants_present_allows():
    """⑧ 七条全齐 → 放行（正路径不误伤）。"""

    verdict = GovernanceSpineGate().evaluate(_all_good_evidence())
    assert verdict.allowed
    assert len(verdict.checked_clauses) == 7 and not verdict.skipped_clauses
    assert not verdict.violations
    assert "证据充分" in verdict.verdict_text


def test_unified_any_violation_rejects_and_names_clause():
    """⑧ 任一硬不变量违反 → allowed=False + 点名被违反 clause（这里破 ⑦ AgentDataAccess）。"""

    ev = _all_good_evidence()
    bad = SpineEvidence(
        canvas_mutation=ev.canvas_mutation, agent_action=ev.agent_action, agent_plan=ev.agent_plan,
        agent_code_change=ev.agent_code_change, role_agent_action=ev.role_agent_action,
        secret_plaintext=ev.secret_plaintext,
        agent_data_access=DataAccessEvidence(auth_ref=SECRET),  # 明文 key → 破 ⑦
    )
    verdict = GovernanceSpineGate().evaluate(bad)
    assert not verdict.allowed
    bad_clause = verdict.clause(INV_AGENT_DATA_ACCESS)
    assert bad_clause is not None and not bad_clause.passed
    assert "证据不足" in verdict.verdict_text and "失败原因" in verdict.verdict_text


def test_unified_assert_allowed_raises_on_violation():
    bad = SpineEvidence(agent_code_change=CodeChangeEvidence(diff="d", test_result="ok", rollback_point=""))
    with pytest.raises(GovernanceSpineViolation):
        GovernanceSpineGate().assert_allowed(bad)


def test_unified_multiple_violations_all_reported():
    """多条同时违反 → 全部进 violations（不止抓第一条）。"""

    bad = SpineEvidence(
        canvas_mutation=_bypass_bus(),
        agent_data_access=DataAccessEvidence(auth_ref=SECRET),
        secret_plaintext=SecretSurfaceEvidence(surface={"k": SECRET}, secret_values=(SECRET,)),
    )
    verdict = GovernanceSpineGate().evaluate(bad)
    assert not verdict.allowed and len(verdict.violations) == 3
    failed = {c.clause for c in verdict.clauses if c.checked and not c.passed}
    assert failed == {INV_CANVAS_MUTATION, INV_AGENT_DATA_ACCESS, INV_SECRET_PLAINTEXT}


def test_unified_secret_values_default_from_gate():
    """gate 持缺省在册 secret 集 → evidence 未自带 secret_values 时回退到它（同 EventProjector 范式）。"""

    gate = GovernanceSpineGate(secret_values=[SECRET])
    ev = SpineEvidence(secret_plaintext=SecretSurfaceEvidence(surface={"api_key": SECRET}))  # 不自带 secret_values
    verdict = gate.evaluate(ev)
    assert not verdict.allowed  # 仍抓到泄露（用了 gate 缺省 secret 集）


def test_unified_empty_evidence_is_not_a_green_light():
    """空 evidence → 七条全跳过（未验证残余）·裁决如实说「非放行结论」，不冒充全过。"""

    verdict = GovernanceSpineGate().evaluate(SpineEvidence())
    assert not verdict.checked_clauses and len(verdict.skipped_clauses) == 7
    assert "未提供任何 evidence" in verdict.verdict_text
    assert "证据充分" not in verdict.verdict_text


# ═══════════════ ⑨ 诚实层：收编登记 + 标注 + 拒绝口径无越权断言 ═══════════════
def test_enforcement_registry_covers_exactly_seven_clauses():
    assert set(ENFORCEMENT_BINDINGS) == set(CLAUSES)
    assert len(CLAUSES) == 7
    for clause, binding in ENFORCEMENT_BINDINGS.items():
        assert binding.clause == clause
        assert binding.status in {STATUS_DELEGATED, STATUS_MIXED, "aggregation"}
        assert binding.enforced_by  # 每条都钉了收编的已建件


def test_mixed_clauses_are_honestly_labeled():
    """AgentAction（no-secret 缺口）与 RoleAgentAction（join）= 本门聚合补·标 mixed；其余收编全权·标 delegated。"""

    assert ENFORCEMENT_BINDINGS[INV_AGENT_ACTION].status == STATUS_MIXED
    assert ENFORCEMENT_BINDINGS[INV_ROLE_AGENT_ACTION].status == STATUS_MIXED
    for clause in (INV_CANVAS_MUTATION, INV_AGENT_PLAN, INV_AGENT_CODE_CHANGE,
                   INV_SECRET_PLAINTEXT, INV_AGENT_DATA_ACCESS):
        assert ENFORCEMENT_BINDINGS[clause].status == STATUS_DELEGATED


def test_rejection_verdict_has_no_overclaim_terms():
    """RULES §3：拒绝口径绝不出现「可信/保证/证据充分」等越权正向断言（门自检兜底·此处显式复核）。"""

    verdict = GovernanceSpineGate().evaluate(
        SpineEvidence(agent_data_access=DataAccessEvidence(auth_ref="not-a-ref"))
    )
    assert not verdict.allowed
    for banned in BANNED_IN_REJECTION:
        assert banned not in verdict.verdict_text


def test_clause_result_carries_enforcement_provenance():
    """每条核查结果随身带「谁 enforce / 是否本门补缺口」——诚实标注可被下游读出。"""

    res = check_canvas_mutation(_good_bus())
    assert res.enforced_by and res.enforcement_status == STATUS_DELEGATED
