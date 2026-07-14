from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.agent.agent_runtime import AgentRuntime, AgentStep, AgentTurn
from app.agent.llm_client import DevLocalLLM, LLMResponse
from app.research_os import (
    AssetRAGDocument,
    ActorSource,
    DefinitionStatus,
    PersistentCompilerIRStore,
    PersistentGoalEntrypointCoverageRegistry,
    PersistentGoalValidationReceiptRegistry,
    PersistentResearchAssetRAGIndex,
    QRORecord,
    QROType,
    RAGPermission,
    ResearchGraphCommand,
    ResearchGraphStore,
)
from app.research_os.entrypoint_evidence import PersistentEntrypointEvidenceRegistry
from app.research_os.goal_proof_ledger import GoalProofLedger
from app.research_os.ref_resolution import build_real_ref_resolver
from conftest import build_test_agent_gateway


def _patch_route_gateway(main, monkeypatch, client) -> None:  # noqa: ANN001
    monkeypatch.setattr(
        main,
        "_current_agent_gateway",
        lambda run_id=None: build_test_agent_gateway(
            client,
            seal_secret=main.LLM_CALL_RECORD_STORE.seal_secret,
        ),
    )


class _ToolThenFinalLLM:
    def __init__(self) -> None:
        self.calls = 0

    def chat(self, messages, *, tools=None, model=None, temperature=0.2):  # noqa: ANN001, ARG002
        self.calls += 1
        if self.calls == 1:
            return LLMResponse(
                content="",
                tool_calls=[
                    {
                        "id": "call_strategy_goal",
                        "name": "strategy_goal.create",
                        "arguments": '{"market":"crypto","secret":"SHOULD_NOT_ENTER_QRO"}',
                    }
                ],
            )
        return LLMResponse(content="done")


class _StrategyGoalThenFinalLLM:
    def __init__(self) -> None:
        self.calls = 0

    def chat(self, messages, *, tools=None, model=None, temperature=0.2):  # noqa: ANN001, ARG002
        self.calls += 1
        if self.calls == 1:
            return LLMResponse(
                content="",
                tool_calls=[
                    {
                        "id": "call_strategy_goal_real",
                        "name": "strategy_goal.create",
                        "arguments": (
                            '{"asset_class":"crypto_perp","objective":"max_calmar",'
                            '"horizon":"daily","secret":"SHOULD_NOT_ENTER_GRAPH_AUDIT"}'
                        ),
                    }
                ],
            )
        return LLMResponse(content="goal created")


class _CapturingLLM:
    def __init__(self) -> None:
        self.messages = []

    def chat(self, messages, *, tools=None, model=None, temperature=0.2):  # noqa: ANN001, ARG002
        self.messages = list(messages)
        return LLMResponse(content="answer grounded in candidate context")


class _RejectingTranslator:
    status = "schema_invalid"
    reason = "bad schema"

    def translate(self, _tool_calls):  # noqa: ANN001
        return self


def _source_value(value) -> str:
    return value.value if hasattr(value, "value") else str(value)


def _patch_goal_coverage_stores(main, tmp_path, monkeypatch) -> None:  # noqa: ANN001
    proof_ledger = GoalProofLedger(tmp_path / "goal_proof_ledger")
    graph = ResearchGraphStore()
    compiler = PersistentCompilerIRStore(
        tmp_path / "compiler_ir.jsonl",
        proof_ledger=proof_ledger,
        legacy_read_only=True,
    )
    validation = PersistentGoalValidationReceiptRegistry(
        tmp_path / "goal_validation_receipts.jsonl",
        proof_ledger=proof_ledger,
        legacy_read_only=True,
    )
    evidence = PersistentEntrypointEvidenceRegistry(
        tmp_path / "entrypoint_evidence.jsonl",
        research_graph_store=graph,
        compiler_store=compiler,
        validation_receipt_registry=validation,
        proof_ledger=proof_ledger,
        legacy_read_only=True,
    )
    coverage = PersistentGoalEntrypointCoverageRegistry(
        tmp_path / "goal_entrypoint_coverage.jsonl",
        proof_ledger=proof_ledger,
        legacy_read_only=True,
    )
    coverage.set_ref_resolver(
        build_real_ref_resolver(
            research_graph_store=graph,
            lifecycle_registry=None,
            governance_registry=None,
            rag_index=None,
            spine_chain_registry=None,
            compiler_store=compiler,
            goal_validation_receipt_registry=validation,
            platform_source_evidence_registry=evidence,
        )
    )
    monkeypatch.setattr(main, "RESEARCH_GRAPH_STORE", graph)
    monkeypatch.setattr(main, "COMPILER_IR_STORE", compiler)
    monkeypatch.setattr(main, "GOAL_VALIDATION_RECEIPT_REGISTRY", validation)
    monkeypatch.setattr(main, "ENTRYPOINT_EVIDENCE_REGISTRY", evidence)
    monkeypatch.setattr(
        main,
        "GOAL_ENTRYPOINT_COVERAGE_REGISTRY",
        coverage,
    )


@pytest.fixture(autouse=True)
def _authenticated_agent_api():
    """These graph tests exercise authenticated agent entrypoints, not auth itself."""

    import app.main as main

    main.app.dependency_overrides[main.require_user_dependency] = lambda: SimpleNamespace(
        username="u1",
        user_id="u1",
    )
    try:
        yield
    finally:
        main.app.dependency_overrides.pop(main.require_user_dependency, None)


def test_agent_runtime_records_chat_steps_as_qro_graph_commands_without_plaintext_content():
    store = ResearchGraphStore()
    runtime = AgentRuntime(DevLocalLLM(), research_graph=store)

    turn = runtime.run("你能做什么 SECRET_SHOULD_NOT_ENTER_QRO")

    assert turn.succeeded
    assert len(turn.qro_ids) == len(turn.steps) == 2
    assert len(turn.research_graph_command_ids) == 2
    commands = store.commands()
    assert [command.command_type for command in commands] == ["upsert_qro", "upsert_qro"]
    assert _source_value(commands[0].actor_source) == ActorSource.USER_MANUAL.value
    assert _source_value(commands[1].actor_source) == ActorSource.AGENT.value
    first_qro = store.qro(turn.qro_ids[0])
    assert first_qro.input_contract["entry_source"] == "agent_shell"
    assert first_qro.input_contract["role"] == "user"
    assert first_qro.status_axes()["definition"] == "implemented"
    qro_contract_text = str(first_qro.input_contract) + str(first_qro.output_contract)
    assert "你能做什么" not in qro_contract_text
    assert "SECRET_SHOULD_NOT_ENTER_QRO" not in qro_contract_text


def test_agent_runtime_records_tool_result_qro_and_tool_record_refs_without_payload_leakage():
    store = ResearchGraphStore()
    called: list[dict] = []

    def handler(_name, args):  # noqa: ANN001
        called.append(args)
        return {"ok": True, "secret": "SHOULD_NOT_ENTER_QRO"}

    runtime = AgentRuntime(
        _ToolThenFinalLLM(),
        tools={"strategy_goal.create": handler},
        research_graph=store,
    )

    turn = runtime.run("加密永续 趋势")

    assert turn.succeeded
    assert called and called[0]["secret"] == "SHOULD_NOT_ENTER_QRO"
    assert [step.role for step in turn.steps] == ["user", "assistant", "tool", "assistant"]
    assert len(turn.qro_ids) == 4
    commands = store.commands()
    assert len(commands) == 4
    tool_commands = [command for command in commands if command.tool_record_refs]
    assert len(tool_commands) == 1
    assert tool_commands[0].tool_record_refs == ("tool_call:call_strategy_goal",)
    tool_qro = store.qro(turn.qro_ids[2])
    qro_contract_text = str(tool_qro.input_contract) + str(tool_qro.output_contract)
    assert "SHOULD_NOT_ENTER_QRO" not in qro_contract_text


def test_agent_runtime_rejected_tool_call_records_gate_event_without_tool_result():
    store = ResearchGraphStore()
    called: list[dict] = []

    def handler(_name, args):  # noqa: ANN001
        called.append(args)
        return {"ok": True}

    runtime = AgentRuntime(
        _ToolThenFinalLLM(),
        tools={"strategy_goal.create": handler},
        translator=_RejectingTranslator(),
        research_graph=store,
    )

    turn = runtime.run("加密永续 趋势")

    assert not turn.succeeded
    assert called == []
    assert [step.role for step in turn.steps] == ["user", "assistant", "system"]
    assert len(turn.qro_ids) == 3
    assert all(not command.tool_record_refs for command in store.commands())


def test_agent_chat_endpoint_returns_research_graph_and_goal_coverage_refs(tmp_path, monkeypatch):
    import app.main as main

    _patch_goal_coverage_stores(main, tmp_path, monkeypatch)
    _patch_route_gateway(main, monkeypatch, DevLocalLLM())
    before = len(main.RESEARCH_GRAPH_STORE.commands())
    secret = "SECRET_SHOULD_NOT_ENTER_GOAL_COVERAGE"
    response = TestClient(main.app).post("/api/agent/chat", json={"message": f"你能做什么 {secret}"})

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["qro_ids"]
    assert body["research_graph_command_ids"]
    assert len(body["compiler_ir_refs"]) == 1
    assert len(body["compiler_pass_refs"]) == 1
    assert len(body["entrypoint_coverage_refs"]) == 1
    assert len(body["qro_ids"]) == len(body["steps"])
    assert len(main.RESEARCH_GRAPH_STORE.commands()) >= before + len(body["qro_ids"])
    qro = main.RESEARCH_GRAPH_STORE.qro(body["qro_ids"][0])
    assert qro.input_contract["entry_source"] == "chat"
    assert qro.input_contract["role"] == "user"
    coverages = main.GOAL_ENTRYPOINT_COVERAGE_REGISTRY.records()
    assert {(record.entry_source, record.entrypoint_ref) for record in coverages} == {
        ("chat", "chat:api.agent.chat"),
    }
    for record in coverages:
        assert record.qro_refs
        assert record.research_graph_command_refs
        assert record.compiler_ir_refs
        assert record.compiler_pass_refs
        assert record.evidence_refs
        assert record.permission_refs
        assert record.replay_refs
    persisted = str(coverages)
    for ir_ref in body["compiler_ir_refs"]:
        persisted += str(main.COMPILER_IR_STORE.ir(ir_ref))
    for pass_ref in body["compiler_pass_refs"]:
        persisted += str(main.COMPILER_IR_STORE.compiler_pass(pass_ref))
    assert secret not in persisted
    assert "你能做什么" not in persisted


def test_research_graph_commands_endpoint_returns_audit_summary_without_plaintext(tmp_path, monkeypatch):
    import app.main as main

    _patch_goal_coverage_stores(main, tmp_path, monkeypatch)
    _patch_route_gateway(main, monkeypatch, DevLocalLLM())
    client = TestClient(main.app)
    secret = "SECRET_SHOULD_NOT_ENTER_GRAPH_AUDIT"
    chat = client.post("/api/agent/chat", json={"message": f"你能做什么 {secret}"})

    assert chat.status_code == 200, chat.text
    command_ids = set(chat.json()["research_graph_command_ids"])

    audit = client.get("/api/research-os/graph/commands", params={"limit": len(command_ids)})

    assert audit.status_code == 200, audit.text
    body = audit.json()
    commands = body["commands"]
    assert command_ids.issubset({command["command_id"] for command in commands})
    assert secret not in str(body)
    assert "你能做什么" not in str(body)
    qro_payloads = [command["payload"]["qro"] for command in commands if "qro" in command["payload"]]
    assert qro_payloads
    assert qro_payloads[0]["input_contract"]["entry_source"] == "chat"
    assert qro_payloads[0]["status_axes"]["definition"] == "implemented"
    assert "content_hash" in qro_payloads[0]["output_contract"]


def test_agent_turn_goal_coverage_rejects_missing_graph_refs_without_partial_write(tmp_path, monkeypatch):
    import app.main as main

    _patch_goal_coverage_stores(main, tmp_path, monkeypatch)
    turn = AgentTurn(user_input="SECRET_SHOULD_NOT_ENTER_GOAL_COVERAGE")
    turn.succeeded = True
    turn.steps.append(AgentStep(role="assistant", content="ok"))
    turn.qro_ids.append("qro_missing_graph_ref")

    with pytest.raises(ValueError, match="qro_ids and research_graph_command_ids"):
        main._record_agent_turn_goal_entrypoint_coverage(
            turn,
            endpoint_ref="api.agent.chat",
            actor="test_agent",
            permission_mode="auto",
        )

    assert main.GOAL_ENTRYPOINT_COVERAGE_REGISTRY.records() == []
    assert main.COMPILER_IR_STORE.irs() == []
    assert main.COMPILER_IR_STORE.passes() == []


def test_agent_turn_goal_coverage_rejects_silent_mock_without_partial_proof_write(
    tmp_path,
    monkeypatch,
):
    import app.main as main

    _patch_goal_coverage_stores(main, tmp_path, monkeypatch)
    qro = QRORecord(
        qro_type=QROType.RESEARCH_REPORT,
        owner="test_agent",
        actor=ActorSource.AGENT,
        input_contract={"entry_source": "agent_shell", "role": "assistant"},
        output_contract={"content_hash": "hash:assistant"},
        market="unspecified",
        universe="test",
        horizon="event",
        frequency="event",
        lineage=("test_agent", "silent_mock"),
        implementation_hash="test_agent:silent_mock",
        assumptions=("test qro",),
        known_limits=("test only",),
        failure_modes=("silent fallback",),
        validation_plan=("coverage validator rejects silent fallback",),
        definition_status=DefinitionStatus.IMPLEMENTED,
        evidence_refs=("evidence:test_agent:silent_mock",),
        permission="agent_permission_mode:auto",
        mock_profile="silent",
    )
    command = ResearchGraphCommand(
        source="agent_shell",
        command_type="upsert_qro",
        actor_source=ActorSource.AGENT,
        actor="test_agent",
        payload={"qro": qro},
        evidence_refs=qro.evidence_refs,
    )
    command_id = main.RESEARCH_GRAPH_STORE.apply(command)
    turn = AgentTurn(user_input="SECRET_SHOULD_NOT_ENTER_GOAL_COVERAGE")
    turn.succeeded = True
    turn.steps.append(AgentStep(role="assistant", content="ok"))
    turn.qro_ids.append(qro.qro_id)
    turn.research_graph_command_ids.append(command_id)

    with pytest.raises(ValueError) as caught:
        main._record_agent_turn_goal_entrypoint_coverage(
            turn,
            endpoint_ref="api.agent.chat",
            actor="test_agent",
            permission_mode="auto",
        )

    assert "goal_entrypoint_silent_mock_fallback" in str(caught.value)
    assert main.GOAL_ENTRYPOINT_COVERAGE_REGISTRY.records() == []
    assert main.COMPILER_IR_STORE.irs() == []
    assert main.COMPILER_IR_STORE.passes() == []
    receipts = main._compiler_receipts_for_subject(
        owner_user_id="test_agent",
        qro_ref=qro.qro_id,
        graph_command_ref=command_id,
    )
    assert receipts == {}


def test_agent_strategy_goal_tool_writes_quant_intent_qro_visible_in_audit(tmp_path, monkeypatch):
    import app.main as main
    from app.strategy_goal_store import StrategyGoalStore

    _patch_route_gateway(main, monkeypatch, _StrategyGoalThenFinalLLM())
    monkeypatch.setattr(main, "STRATEGY_GOAL_STORE", StrategyGoalStore(tmp_path / "goals"))
    _patch_goal_coverage_stores(main, tmp_path, monkeypatch)
    client = TestClient(main.app)
    before = len(main.RESEARCH_GRAPH_STORE.commands())

    chat = client.post("/api/agent/chat", json={"message": "建一个加密永续日频卡玛目标"})

    assert chat.status_code == 200, chat.text
    audit = client.get("/api/research-os/graph/commands", params={"limit": 20})
    assert audit.status_code == 200, audit.text
    body = audit.json()
    new_commands = body["commands"][-(len(main.RESEARCH_GRAPH_STORE.commands()) - before):]
    quant_intent = [
        command["payload"]["qro"]
        for command in new_commands
        if command["payload"].get("qro", {}).get("qro_type") == "QuantIntent"
    ]
    assert quant_intent
    qro = quant_intent[0]
    assert qro["input_contract"]["entry_source"] == "agent_shell"
    assert qro["input_contract"]["tool_name"] == "strategy_goal.create"
    assert qro["output_contract"]["strategy_goal_id"].startswith("goal_")
    assert qro["output_contract"]["asset_class"] == "crypto_perp"
    assert "SHOULD_NOT_ENTER_GRAPH_AUDIT" not in str(body)

    coverages = main.GOAL_ENTRYPOINT_COVERAGE_REGISTRY.records()
    strategy_goal_coverages = [
        coverage
        for coverage in coverages
        if coverage.entry_source == "agent_shell"
        and coverage.entrypoint_ref == "agent_shell:strategy_goal.create"
    ]
    assert strategy_goal_coverages
    coverage = strategy_goal_coverages[0]
    assert qro["qro_id"] in coverage.qro_refs
    assert coverage.compiler_ir_refs
    ir = main.COMPILER_IR_STORE.ir(coverage.compiler_ir_refs[0])
    compiler_pass = main.COMPILER_IR_STORE.compiler_pass(coverage.compiler_pass_refs[0])
    assert ir.source_qro_refs == (qro["qro_id"],)
    assert compiler_pass.entry_source == "agent_shell"
    assert "SHOULD_NOT_ENTER_GRAPH_AUDIT" not in str(ir) + str(compiler_pass) + str(coverage)


def _rag_doc(**overrides):
    payload = {
        "source_id": "doc:risk-parity",
        "version": "v1",
        "title": "Risk parity covariance shrinkage note",
        "body": "covariance covariance shrinkage portfolio construction risk parity",
        "projection": "ResearchRAG",
        "asset_ref": "qro:portfolio-risk",
        "permission": RAGPermission(
            allowed_users=("u1",),
            allowed_desks=("research",),
            allowed_assets=("qro:portfolio-risk",),
            permission_tags=("research.read",),
        ),
        "applicability": "candidate research context for portfolio construction",
        "source_kind": "EvidenceSpan",
        "evidence_label": "candidate_context",
    }
    payload.update(overrides)
    return AssetRAGDocument(**payload)


def test_agent_chat_auto_retrieves_research_asset_rag_and_records_usage(tmp_path, monkeypatch):
    import app.main as main

    index = PersistentResearchAssetRAGIndex(tmp_path / "research_asset_rag.jsonl")
    index.add_for_owner(_rag_doc(), owner_user_id="u1")
    llm = _CapturingLLM()
    monkeypatch.setattr(main, "RESEARCH_ASSET_RAG_INDEX", index)
    _patch_goal_coverage_stores(main, tmp_path, monkeypatch)
    store = main.RESEARCH_GRAPH_STORE
    _patch_route_gateway(main, monkeypatch, llm)
    response = TestClient(main.app).post(
        "/api/agent/chat",
        json={
            "message": "covariance shrinkage risk portfolio",
            "desk": "research",
            "visible_asset_refs": ["qro:portfolio-risk"],
            "permission_tags": ["research.read"],
            "projections": ["ResearchRAG"],
            "rag_search": "vector",
        },
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert [step["role"] for step in body["steps"]] == ["user", "system", "assistant"]
    assert body["rag_hits"][0]["source_id"] == "doc:risk-parity"
    assert body["rag_hits"][0]["version"] == "v1"
    assert body["rag_hits"][0]["context_role"] == "candidate_context"
    assert body["rag_usage_ids"]
    assert index.strict_usage_records(owner_user_id="u1")

    prompt_text = "\n".join(message.content for message in llm.messages)
    assert "Research Asset RAG candidate context" in prompt_text
    assert "covariance covariance shrinkage" in prompt_text

    command_refs = {
        ref
        for command in store.commands()
        if command.command_id in set(body["research_graph_command_ids"])
        for ref in command.evidence_refs
    }
    assert "rag:doc:risk-parity@v1:qro:portfolio-risk" in command_refs
    assert any(ref.startswith("rag_usage:") for ref in command_refs)
    qro_contract_text = "".join(
        str(store.qro(qro_id).input_contract) + str(store.qro(qro_id).output_contract)
        for qro_id in body["qro_ids"]
    )
    assert "covariance covariance shrinkage" not in qro_contract_text


def test_agent_chat_does_not_auto_retrieve_unauthorized_rag_context(tmp_path, monkeypatch):
    import app.main as main

    index = PersistentResearchAssetRAGIndex(tmp_path / "research_asset_rag.jsonl")
    index.add_for_owner(_rag_doc(), owner_user_id="u1")
    llm = _CapturingLLM()
    monkeypatch.setattr(main, "RESEARCH_ASSET_RAG_INDEX", index)
    _patch_goal_coverage_stores(main, tmp_path, monkeypatch)
    store = main.RESEARCH_GRAPH_STORE
    _patch_route_gateway(main, monkeypatch, llm)
    response = TestClient(main.app).post(
        "/api/agent/chat",
        json={
            "message": "covariance shrinkage risk portfolio",
            "desk": "data",
            "visible_asset_refs": ["qro:portfolio-risk"],
            "permission_tags": ["research.read"],
            "projections": ["ResearchRAG"],
            "rag_search": "vector",
        },
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert [step["role"] for step in body["steps"]] == ["user", "assistant"]
    assert body["rag_hits"] == []
    assert body["rag_usage_ids"] == []
    assert index.agent_usage(source_id="doc:risk-parity", user_id="u1") == []
    prompt_text = "\n".join(message.content for message in llm.messages)
    assert "Research Asset RAG candidate context" not in prompt_text
    assert all(not ref.startswith("rag:") for command in store.commands() for ref in command.evidence_refs)
