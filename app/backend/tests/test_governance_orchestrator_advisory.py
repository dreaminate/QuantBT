"""§8 GovernanceSpineGate → AgentOrchestrator advisory wiring tests."""

from __future__ import annotations

import json

import pytest

from app.agent.llm_client import LLMResponse
from app.agent.orchestrator import (
    AcceptanceGate,
    AgentOrchestrator,
    AgentTodo,
    GOVERNANCE_ADVISORY_SOURCE,
    GovernanceAdvisory,
    make_executor,
    run_governance_advisory,
)
from app.agent.orchestrator.events import (
    EV_FAILURE_DETECTED,
    EV_ROLE_AGENT_DISPATCHED,
    EV_VERIFIER_CHALLENGE_RAISED,
    EventProjector,
    WorkflowEvent,
)
from app.agent.orchestrator.governance import GovernedToolDispatcher, ToolCallRecord
from app.command.canonical_command import (
    ACTION_CREATE_ASSET,
    ORIGIN_CANVAS,
    CommandBus,
    CommandIntent,
    manual_provenance,
)
from app.governance import (
    INV_AGENT_CODE_CHANGE,
    INV_AGENT_DATA_ACCESS,
    INV_AGENT_PLAN,
    INV_ROLE_AGENT_ACTION,
    INV_SECRET_PLAINTEXT,
    AgentActionEvidence,
    CodeChangeEvidence,
    DataAccessEvidence,
    RoleActionEvidence,
    SecretSurfaceEvidence,
    SpineEvidence,
)
from app.graph.research_graph import DESK_FACTOR
from app.llm import (
    LLMCredentialPool,
    LLMGateway,
    LLMModelProfile,
    ModelRoutingPolicy,
    ModelTier,
    RoutingMode,
    SecretLeakError,
    SecretRef,
)
from app.qro.envelope import ACTOR_USER_MANUAL, OBJ_FACTOR, QualifiedResearchObject
from app.security import InMemoryKeystore, KeystoreRecord, SecureKeystore

TRIPWIRE_SECRET = "sk-GOVADVISORY-LEAK-deadbeef0123456789"
GOOD_REF = "secretref://anthropic/llm_anthropic"


def _good_bus() -> CommandBus:
    bus = CommandBus()
    bus.submit(
        CommandIntent(
            action=ACTION_CREATE_ASSET,
            target_desk=DESK_FACTOR,
            provenance=manual_provenance(ORIGIN_CANVAS),
            args={
                "qro": QualifiedResearchObject(
                    object_type=OBJ_FACTOR,
                    natural_key="mom@v1",
                    actor=ACTOR_USER_MANUAL,
                )
            },
        )
    )
    return bus


def _good_dispatcher(node_id: str = "n1") -> GovernedToolDispatcher:
    disp = GovernedToolDispatcher()
    disp.register("read_asset", lambda name, args: {"ok": True})
    ctx = disp.enter_node(
        node_id=node_id,
        task_id=node_id,
        role="data_engineer",
        permitted_tools=frozenset({"read_asset"}),
    )
    disp.dispatch("read_asset", {}, node_ctx=ctx)
    disp.exit_node(ctx)
    return disp


def _good_plan():
    from app.agent.orchestrator.plan import AgentPlan

    return AgentPlan(
        goal="build factor",
        todos=[AgentTodo(todo_id="t1", description="define factor", role="factor_engineer")],
        dependencies={"t1": []},
        acceptance_gates=[
            AcceptanceGate(gate_id="g1", description="IC>0", falsifiable_check="IC<=0 -> reject")
        ],
    )


def _bad_plan_missing_gates():
    from app.agent.orchestrator.plan import AgentPlan

    return AgentPlan(
        goal="g",
        todos=[AgentTodo(todo_id="t1", description="x", role="factor_engineer")],
        dependencies={"t1": []},
        acceptance_gates=[],
    )


def _role_event(role: str = "data_engineer", node_id: str = "n1") -> WorkflowEvent:
    return WorkflowEvent(kind=EV_ROLE_AGENT_DISPATCHED, role=role, node_id=node_id)


def _audit_record(node_id: str = "n1") -> ToolCallRecord:
    return ToolCallRecord(
        tool="read_asset",
        node_id=node_id,
        task_id=node_id,
        role="data_engineer",
        ok=True,
    )


def _all_good_evidence() -> SpineEvidence:
    return SpineEvidence(
        canvas_mutation=_good_bus(),
        agent_action=AgentActionEvidence(dispatcher=_good_dispatcher("n1"), node_id="n1"),
        agent_plan=_good_plan(),
        agent_code_change=CodeChangeEvidence(
            diff="--- a\n+++ b",
            test_result="pytest 12 passed",
            rollback_point="rev abc",
        ),
        role_agent_action=RoleActionEvidence(
            events=(_role_event(),),
            role="data_engineer",
            node_id="n1",
            audit_records=(_audit_record(),),
        ),
        secret_plaintext=SecretSurfaceEvidence(
            surface={"clean": "x"},
            secret_values=(TRIPWIRE_SECRET,),
        ),
        agent_data_access=DataAccessEvidence(auth_ref=GOOD_REF),
    )


def test_advisory_flags_plan_missing_acceptance_gates():
    p = EventProjector()
    adv = run_governance_advisory(SpineEvidence(agent_plan=_bad_plan_missing_gates()), p)

    assert isinstance(adv, GovernanceAdvisory)
    assert adv.flagged is True and adv.allowed is False
    assert INV_AGENT_PLAN in adv.violated_clauses

    ev = p.of_kind(EV_VERIFIER_CHALLENGE_RAISED)[-1]
    assert ev.data["challenge_source"] == GOVERNANCE_ADVISORY_SOURCE
    assert ev.data["flagged"] is True
    assert INV_AGENT_PLAN in ev.data["violated_clauses"]


def test_advisory_flags_code_change_missing_rollback():
    p = EventProjector()
    evidence = SpineEvidence(
        agent_code_change=CodeChangeEvidence(diff="--- a\n+++ b", test_result="ok", rollback_point="")
    )
    adv = run_governance_advisory(evidence, p)

    assert adv.flagged is True
    assert INV_AGENT_CODE_CHANGE in adv.violated_clauses


def test_advisory_flags_role_action_no_visible_event():
    p = EventProjector()
    evidence = SpineEvidence(
        role_agent_action=RoleActionEvidence(
            events=(),
            role="data_engineer",
            node_id="n1",
            audit_records=(_audit_record(),),
        )
    )
    adv = run_governance_advisory(evidence, p)

    assert adv.flagged is True
    assert INV_ROLE_AGENT_ACTION in adv.violated_clauses


def test_advisory_flags_data_access_plaintext_key_without_echoing_key():
    p = EventProjector(secret_values=[TRIPWIRE_SECRET])
    adv = run_governance_advisory(
        SpineEvidence(agent_data_access=DataAccessEvidence(auth_ref=TRIPWIRE_SECRET)),
        p,
    )

    assert adv.flagged is True
    assert INV_AGENT_DATA_ACCESS in adv.violated_clauses
    event_data = p.of_kind(EV_VERIFIER_CHALLENGE_RAISED)[-1].data
    assert TRIPWIRE_SECRET not in json.dumps(event_data, ensure_ascii=False)
    assert TRIPWIRE_SECRET not in json.dumps(adv.to_dict(), ensure_ascii=False)


def test_advisory_only_marks_does_not_raise_for_multiple_violations():
    p = EventProjector()
    evidence = SpineEvidence(
        agent_plan=_bad_plan_missing_gates(),
        agent_code_change=CodeChangeEvidence(diff="d", test_result="ok", rollback_point=""),
        role_agent_action=RoleActionEvidence(
            events=(),
            role="data_engineer",
            node_id="n1",
            audit_records=(),
        ),
    )

    adv = run_governance_advisory(evidence, p)

    assert adv.flagged is True
    assert len(adv.violated_clauses) >= 3
    assert adv.advisory is True


def test_advisory_does_not_flag_all_good_evidence():
    p = EventProjector(secret_values=[TRIPWIRE_SECRET])
    adv = run_governance_advisory(_all_good_evidence(), p)

    assert adv.flagged is False and adv.allowed is True
    assert adv.violated_clauses == ()
    assert len(adv.checked_clauses) == 7 and adv.skipped_clauses == ()
    assert p.of_kind(EV_VERIFIER_CHALLENGE_RAISED)[-1].data["flagged"] is False


def test_advisory_empty_evidence_is_explicit_unverified_residual_not_green_light():
    p = EventProjector()
    adv = run_governance_advisory(SpineEvidence(), p)

    assert adv.flagged is False
    assert adv.checked_clauses == ()
    assert len(adv.skipped_clauses) == 7
    assert "未提供任何 evidence" in adv.verdict_text
    assert "verdict_text" not in adv.to_dict()


def test_secret_clause_flagged_and_projection_has_no_secret():
    p = EventProjector(secret_values=[TRIPWIRE_SECRET])
    evidence = SpineEvidence(
        secret_plaintext=SecretSurfaceEvidence(
            surface={"api_key": TRIPWIRE_SECRET},
            secret_values=(TRIPWIRE_SECRET,),
        )
    )

    adv = run_governance_advisory(evidence, p)

    assert adv.flagged is True and adv.allowed is False
    assert INV_SECRET_PLAINTEXT in adv.violated_clauses
    serialized_events = json.dumps([e.to_dict() for e in p.events], ensure_ascii=False)
    assert TRIPWIRE_SECRET not in serialized_events
    assert TRIPWIRE_SECRET not in json.dumps(adv.to_dict(), ensure_ascii=False)


def test_secret_command_gate_returns_verdict_not_raise():
    p = EventProjector(secret_values=[TRIPWIRE_SECRET])
    evidence = SpineEvidence(
        secret_plaintext=SecretSurfaceEvidence(
            surface={"k": TRIPWIRE_SECRET},
            secret_values=(TRIPWIRE_SECRET,),
        )
    )

    adv = run_governance_advisory(evidence, p)

    assert adv.flagged is True
    secret_clause = adv.verdict.clause(INV_SECRET_PLAINTEXT)
    assert secret_clause is not None and secret_clause.checked and not secret_clause.passed


class _RaisingSecretGate:
    def evaluate(self, evidence: SpineEvidence):
        raise SecretLeakError(f"secret leaked: {TRIPWIRE_SECRET}")


def test_secret_command_gate_defense_in_depth_reraises_without_echo():
    p = EventProjector()

    with pytest.raises(SecretLeakError):
        run_governance_advisory(SpineEvidence(), p, gate=_RaisingSecretGate())

    fd = p.of_kind(EV_FAILURE_DETECTED)[-1]
    assert fd.data["reason"] == "secret_plaintext_hard_stop"
    assert fd.data["advisory"] is False
    assert fd.data["refused_invariants"] == [INV_SECRET_PLAINTEXT]
    assert TRIPWIRE_SECRET not in json.dumps(fd.data, ensure_ascii=False)


def test_orchestrator_advise_governance_flags_and_projects():
    gw = _gateway(factory=lambda c: _ReadAssetThenFinal())
    orch = AgentOrchestrator(gateway=gw)

    adv = orch.advise_governance(SpineEvidence(agent_plan=_bad_plan_missing_gates()), node_ref="strat-x")

    assert adv.flagged is True
    assert INV_AGENT_PLAN in adv.violated_clauses
    ev = orch.projector.of_kind(EV_VERIFIER_CHALLENGE_RAISED)[-1]
    assert ev.data["challenge_source"] == GOVERNANCE_ADVISORY_SOURCE
    assert ev.data["node_ref"] == "strat-x"


def test_orchestrator_advise_governance_good_evidence_not_flagged():
    gw = _gateway(factory=lambda c: _ReadAssetThenFinal())
    orch = AgentOrchestrator(gateway=gw, secret_values=(TRIPWIRE_SECRET,))

    adv = orch.advise_governance(_all_good_evidence())

    assert adv.flagged is False and adv.allowed is True


def test_existing_dispatch_unaffected_by_governance_advisory(tmp_path):
    gw = _gateway(factory=lambda c: _ReadAssetThenFinal())
    orch = AgentOrchestrator(
        gateway=gw,
        owner_user_id="owner-governance-advisory",
        workflow_id="workflow-governance-dispatch",
    )
    plan = _ready_orch_plan(orch, [("t1", "factor_engineer")], {"t1": []})
    executor = make_executor(tmp_path)

    result = orch.dispatch(
        plan,
        executor=executor,
        tool_handlers={"factor_engineer": {"read_asset": _stub_tool}},
    )

    assert result.succeeded is True
    for ev in result.events:
        assert ev.data.get("challenge_source") != GOVERNANCE_ADVISORY_SOURCE


def test_MUT_paper_door_governance_flag():
    p = EventProjector()
    bad = SpineEvidence(agent_plan=_bad_plan_missing_gates())

    adv = run_governance_advisory(bad, p)
    assert adv.flagged is True

    def mutant_advisory(_evidence, _projector):
        return False

    assert mutant_advisory(bad, p) is False


class _ReadAssetThenFinal:
    provider = "scripted"

    def __init__(self) -> None:
        self.calls = 0

    def chat(self, messages, *, tools=None, model=None, temperature=0.2):
        self.calls += 1
        if any(getattr(m, "role", "") == "tool" for m in messages):
            return LLMResponse(content="done", tool_calls=[])
        return LLMResponse(content="", tool_calls=[{"id": "c1", "name": "read_asset", "arguments": "{}"}])


def _stub_tool(name, args):
    return {"ok": True, "tool": name, "echo": args}


def _profiles():
    return [
        LLMModelProfile(
            provider="anthropic",
            model="claude-opus-4",
            capability_tier=ModelTier.STRONG.value,
            pool_id="anthropic",
        ),
        LLMModelProfile(
            provider="openai",
            model="gpt-4o",
            capability_tier=ModelTier.STRONG.value,
            pool_id="openai",
        ),
    ]


def _gateway(*, factory):
    profiles = _profiles()
    keystore = SecureKeystore(InMemoryKeystore())
    for profile in profiles:
        keystore.store(
            KeystoreRecord(
                name=profile.pool_id,
                api_key=f"key-{profile.pool_id}-xxxxxxxx",
                api_secret=f"key-{profile.pool_id}-xxxxxxxx",
            )
        )
    pool = LLMCredentialPool(keystore)
    for profile in profiles:
        if not pool.has_pool(profile.pool_id):
            pool.register(
                profile.pool_id,
                SecretRef(
                    keystore_name=profile.pool_id,
                    provider=profile.provider,
                    auth_kind="api_key",
                ),
                default_model=profile.model,
            )
    policy = ModelRoutingPolicy(profiles, mode=RoutingMode.HYBRID_ADAPTIVE)
    return LLMGateway(policy=policy, credential_pool=pool, client_factory=factory, strict_degrade=False)


def _ready_orch_plan(orch, todos_spec, deps):
    todos = [
        AgentTodo(todo_id=tid, description=f"do {tid}", role=role, deps=tuple(deps.get(tid, [])))
        for tid, role in todos_spec
    ]
    gates = [AcceptanceGate(gate_id="g1", description="tool evidence", falsifiable_check="no tool record -> reject")]
    return orch.plan(
        "goal",
        todos=todos,
        dependencies=deps,
        acceptance_gates=gates,
        risk_list=["r1"],
        rollback_points=["rp1"],
    )
