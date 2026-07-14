from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from fastapi.testclient import TestClient

from app.agent.agent_runtime import AgentRAGContext
from app.agent.conversations import ChatService
from app.agent.llm_client import LLMResponse
from app.agent.orchestrator.events import PersistentWorkflowEventLedger
from app.llm.call_record_store import LLMCallRecordStore
from app.research_os import (
    PersistentEntrypointEvidenceRegistry,
    PersistentCompilerIRStore,
    PersistentGoalEntrypointCoverageRegistry,
    PersistentGoalValidationReceiptRegistry,
    ResearchGraphStore,
)
from app.research_os.goal_proof_ledger import GoalProofLedger
from app.research_os.ref_resolution import build_real_ref_resolver
from conftest import build_test_agent_gateway


PROMPT_TRIPWIRE = "route-prompt-plaintext-MUST-NOT-PERSIST-3b82"
OUTPUT_TRIPWIRE = "route-output-plaintext-MUST-NOT-PERSIST-45a1"


def _patch_goal_proof_stores(main, tmp_path: Path, monkeypatch, *, graph=None) -> None:  # noqa: ANN001
    graph = graph if graph is not None else ResearchGraphStore()
    proof_ledger = GoalProofLedger(tmp_path / "goal_proof_ledger")
    compiler = PersistentCompilerIRStore(
        tmp_path / "compiler_ir.jsonl",
        proof_ledger=proof_ledger,
        legacy_read_only=True,
    )
    validations = PersistentGoalValidationReceiptRegistry(
        tmp_path / "goal_validation_receipts.jsonl",
        proof_ledger=proof_ledger,
        legacy_read_only=True,
    )
    evidence = PersistentEntrypointEvidenceRegistry(
        tmp_path / "entrypoint_evidence.jsonl",
        research_graph_store=graph,
        compiler_store=compiler,
        validation_receipt_registry=validations,
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
            goal_validation_receipt_registry=validations,
            platform_source_evidence_registry=evidence,
        )
    )
    monkeypatch.setattr(main, "RESEARCH_GRAPH_STORE", graph)
    monkeypatch.setattr(main, "COMPILER_IR_STORE", compiler)
    monkeypatch.setattr(main, "GOAL_VALIDATION_RECEIPT_REGISTRY", validations)
    monkeypatch.setattr(main, "ENTRYPOINT_EVIDENCE_REGISTRY", evidence)
    monkeypatch.setattr(main, "GOAL_ENTRYPOINT_COVERAGE_REGISTRY", coverage)


class _OfflineRouteClient:
    provider = "offline-test"

    def __init__(self) -> None:
        self.calls = 0
        self.messages = []
        self.tool_schemas = []

    def chat(self, messages, *, tools=None, model=None, temperature=0.2):  # noqa: ANN001, ARG002
        self.calls += 1
        self.messages.append(list(messages))
        self.tool_schemas.append(list(tools or []))
        return LLMResponse(content=OUTPUT_TRIPWIRE)


class _FailingRouteClient:
    provider = "offline-failure"

    def chat(self, messages, *, tools=None, model=None, temperature=0.2):  # noqa: ANN001, ARG002
        raise RuntimeError("offline provider unavailable")


def _sse_payloads(raw: str, event_kind: str) -> list[dict]:
    out = []
    for block in raw.split("\n\n"):
        lines = block.splitlines()
        if f"event: {event_kind}" not in lines:
            continue
        data_line = next(line for line in lines if line.startswith("data: "))
        out.append(json.loads(data_line.removeprefix("data: ")))
    return out


def _schema_names(rows: list[dict]) -> set[str]:
    return {
        str(row.get("name") or row.get("function", {}).get("name") or "")
        for row in rows
    }


def test_all_production_agent_routes_use_orchestrator_and_owner_scoped_events(
    tmp_path: Path,
    monkeypatch,
):
    import app.main as main

    llm_store = LLMCallRecordStore(tmp_path / "audit" / "llm-calls.jsonl")
    event_ledger = PersistentWorkflowEventLedger(
        tmp_path / "audit" / "workflow-events.jsonl"
    )
    kernel_root = tmp_path / "kernel" / "agent-orchestrator"
    graph = ResearchGraphStore()
    offline_client = _OfflineRouteClient()
    rag_calls: list[str] = []

    monkeypatch.setattr(main, "LLM_CALL_RECORD_STORE", llm_store)
    monkeypatch.setattr(main, "AGENT_WORKFLOW_EVENT_LEDGER", event_ledger)
    monkeypatch.setattr(main, "AGENT_ORCHESTRATOR_ROOT", kernel_root)
    _patch_goal_proof_stores(main, tmp_path / "audit", monkeypatch, graph=graph)
    monkeypatch.setattr(main, "CHAT_SERVICE", ChatService(tmp_path / "chat.db"))
    monkeypatch.setattr(
        main,
        "_current_agent_gateway",
        lambda run_id=None: build_test_agent_gateway(
            offline_client,
            seal_secret=llm_store.seal_secret,
        ),
    )
    monkeypatch.setattr(
        main,
        "_current_agent_llm",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("production routes must not call _current_agent_llm")
        ),
    )

    def rag_provider_factory(_payload, _user):  # noqa: ANN001
        def provide(query: str) -> AgentRAGContext:
            rag_calls.append(query)
            return AgentRAGContext(prompt_context="")

        return provide

    monkeypatch.setattr(main, "_agent_shell_rag_context_provider", rag_provider_factory)
    main.app.dependency_overrides[main.require_user_dependency] = lambda: SimpleNamespace(
        username="u1",
        user_id="u1",
    )
    client = TestClient(main.app)
    workflow_ids: list[str] = []
    try:
        chat = client.post(
            "/api/agent/chat",
            json={"message": PROMPT_TRIPWIRE, "request_id": "req-chat-route"},
        )
        assert chat.status_code == 200, chat.text
        chat_body = chat.json()
        assert chat_body["final_message"] == OUTPUT_TRIPWIRE
        assert chat_body["request_id"] == "req-chat-route"
        assert chat_body["live_output_available"] is True
        workflow_ids.append(chat_body["workflow_id"])

        calls_after_first = offline_client.calls
        retry = client.post(
            "/api/agent/chat",
            json={"message": PROMPT_TRIPWIRE, "request_id": "req-chat-route"},
        )
        assert retry.status_code == 200, retry.text
        assert retry.json()["reused"] is True
        assert retry.json()["live_output_available"] is False
        assert retry.json()["final_message"] == ""
        assert offline_client.calls == calls_after_first

        conflict = client.post(
            "/api/agent/chat",
            json={"message": "different input", "request_id": "req-chat-route"},
        )
        assert conflict.status_code == 409, conflict.text
        assert offline_client.calls == calls_after_first

        with client.stream(
            "GET",
            "/api/agent/workbench/stream",
            params={
                "q": PROMPT_TRIPWIRE,
                "permission_mode": "auto",
                "request_id": "req-workbench-route",
            },
        ) as response:
            assert response.status_code == 200
            workbench_raw = "".join(response.iter_text())
        workbench_done = _sse_payloads(workbench_raw, "done")[-1]
        assert workbench_done["final_message"] == OUTPUT_TRIPWIRE
        assert workbench_done["request_id"] == "req-workbench-route"
        assert "event: AgentPlanCreated" in workbench_raw
        assert "event: RoleAgentDispatched" in workbench_raw
        assert workbench_raw.index("event: AgentPlanCreated") < workbench_raw.index(
            "event: done"
        )
        workflow_ids.append(workbench_done["workflow_id"])

        thread = client.post("/api/agent/chat/start", json={})
        assert thread.status_code == 200, thread.text
        thread_id = thread.json()["thread_id"]
        legacy = client.post(
            f"/api/agent/chat/{thread_id}/message",
            json={"content": PROMPT_TRIPWIRE, "request_id": "req-legacy-post"},
        )
        assert legacy.status_code == 200, legacy.text
        assert legacy.json()["content"] == OUTPUT_TRIPWIRE
        assert legacy.json()["request_id"] == "req-legacy-post"
        workflow_ids.append(legacy.json()["workflow_id"])

        with client.stream(
            "GET",
            f"/api/agent/chat/{thread_id}/stream",
            params={"q": PROMPT_TRIPWIRE, "request_id": "req-legacy-stream"},
        ) as response:
            assert response.status_code == 200
            legacy_raw = "".join(response.iter_text())
        legacy_done = _sse_payloads(legacy_raw, "done")[-1]
        assert OUTPUT_TRIPWIRE in legacy_raw
        assert legacy_done["request_id"] == "req-legacy-stream"
        workflow_ids.append(legacy_done["workflow_id"])

        assert offline_client.calls == 4
        assert rag_calls == [PROMPT_TRIPWIRE] * 4
        assert len(set(workflow_ids)) == 4
        assert all(workflow_id.startswith("agentwf_") for workflow_id in workflow_ids)

        for workflow_id in workflow_ids:
            events_response = client.get(f"/api/agent/workflows/{workflow_id}/events")
            assert events_response.status_code == 200, events_response.text
            events = events_response.json()["events"]
            assert events
            assert {event["owner_user_id"] for event in events} == {"u1"}
            assert {event["workflow_id"] for event in events} == {workflow_id}
            assert "RoleAgentDispatched" in {event["kind"] for event in events}

        restarted = PersistentWorkflowEventLedger(event_ledger.path)
        assert restarted.events(owner_user_id="u1", workflow_id=workflow_ids[0])

        main.app.dependency_overrides[main.require_user_dependency] = lambda: SimpleNamespace(
            username="u2",
            user_id="u2",
        )
        isolated = client.get(f"/api/agent/workflows/{workflow_ids[0]}/events")
        assert isolated.status_code == 200
        assert isolated.json()["events"] == []
    finally:
        main.app.dependency_overrides.pop(main.require_user_dependency, None)

    advertised = set().union(*(_schema_names(rows) for rows in offline_client.tool_schemas))
    assert advertised == {"strategy_goal.create", "hypothesis.create", "code.replicate"}
    assert "backtest.run" not in advertised

    scan_paths = [event_ledger.path, event_ledger.head_path, llm_store.path]
    scan_paths.extend(path for path in kernel_root.rglob("*") if path.is_file())
    assert scan_paths
    for path in scan_paths:
        payload = path.read_bytes()
        assert PROMPT_TRIPWIRE.encode() not in payload, path
        assert OUTPUT_TRIPWIRE.encode() not in payload, path


def test_chat_endpoint_server_routes_data_factor_model_backtest_risk_and_report_roles(
    tmp_path: Path,
    monkeypatch,
):
    import app.main as main

    llm_store = LLMCallRecordStore(tmp_path / "audit" / "role-route-llm.jsonl")
    event_ledger = PersistentWorkflowEventLedger(
        tmp_path / "audit" / "role-route-events.jsonl"
    )
    offline_client = _OfflineRouteClient()
    monkeypatch.setattr(main, "LLM_CALL_RECORD_STORE", llm_store)
    monkeypatch.setattr(main, "AGENT_WORKFLOW_EVENT_LEDGER", event_ledger)
    monkeypatch.setattr(main, "AGENT_ORCHESTRATOR_ROOT", tmp_path / "role-route-kernel")
    _patch_goal_proof_stores(main, tmp_path / "audit", monkeypatch)
    monkeypatch.setattr(
        main,
        "_current_agent_gateway",
        lambda run_id=None: build_test_agent_gateway(
            offline_client,
            seal_secret=llm_store.seal_secret,
        ),
    )
    monkeypatch.setattr(
        main,
        "_agent_shell_rag_context_provider",
        lambda _payload, _user: (lambda _query: AgentRAGContext(prompt_context="")),
    )
    main.app.dependency_overrides[main.require_user_dependency] = lambda: SimpleNamespace(
        username="role-route-user",
        user_id="role-route-user",
    )
    client = TestClient(main.app)
    cases = (
        (
            "检查 dataset schema 与 PIT 约束",
            "data_engineer",
            {"data.list_sources", "data.describe_fields", "data.infer_mapping", "data.apply_mapping"},
        ),
        (
            "构造质量因子并计算 IC",
            "factor_engineer",
            {"factor.validate_columns", "factor_set.compose"},
        ),
        ("训练横截面排序模型", "model_engineer", {"model_registry.select"}),
        ("跑 walk-forward 回测", "backtest_engineer", {"backtest.run", "eval.pbo"}),
        ("检查最大回撤与风险限额", "risk_analyst", set()),
        ("写一份研究报告", "reporter", {"report.generate"}),
    )
    try:
        for index, (prompt, expected_role, expected_tools) in enumerate(cases):
            calls_before = offline_client.calls
            response = client.post(
                "/api/agent/chat",
                json={
                    "message": prompt,
                    "request_id": f"req-server-role-{index}",
                    # Caller text cannot directly assert the authoritative role.
                    "role": "verifier_critic",
                },
            )
            assert response.status_code == 200, response.text
            body = response.json()
            assert body["final_message"] == OUTPUT_TRIPWIRE
            assert offline_client.calls == calls_before + 2
            assert _schema_names(offline_client.tool_schemas[-1]) == expected_tools

            events = client.get(
                f"/api/agent/workflows/{body['workflow_id']}/events"
            ).json()["events"]
            dispatched_roles = [
                event["data"]["role"]
                for event in events
                if event["kind"] == "RoleAgentDispatched"
            ]
            assert dispatched_roles == ["coordinator_planner", expected_role]
            assert "verifier_critic" not in dispatched_roles
    finally:
        main.app.dependency_overrides.pop(main.require_user_dependency, None)


def test_workbench_failure_stream_binds_terminal_llm_call_to_failure_event(
    tmp_path: Path,
    monkeypatch,
):
    import app.main as main

    owner = "workbench-failure-user"
    llm_store = LLMCallRecordStore(tmp_path / "audit" / "failed-llm.jsonl")
    event_ledger = PersistentWorkflowEventLedger(
        tmp_path / "audit" / "failed-events.jsonl"
    )
    monkeypatch.setattr(main, "LLM_CALL_RECORD_STORE", llm_store)
    monkeypatch.setattr(main, "AGENT_WORKFLOW_EVENT_LEDGER", event_ledger)
    monkeypatch.setattr(main, "AGENT_ORCHESTRATOR_ROOT", tmp_path / "failed-kernel")
    _patch_goal_proof_stores(main, tmp_path / "audit", monkeypatch)
    monkeypatch.setattr(
        main,
        "_current_agent_gateway",
        lambda run_id=None: build_test_agent_gateway(
            _FailingRouteClient(),
            seal_secret=llm_store.seal_secret,
        ),
    )
    monkeypatch.setattr(
        main,
        "_agent_shell_rag_context_provider",
        lambda _payload, _user: (lambda _query: AgentRAGContext(prompt_context="")),
    )
    main.app.dependency_overrides[main.require_user_dependency] = lambda: SimpleNamespace(
        username=owner,
        user_id=owner,
    )
    try:
        client = TestClient(main.app)
        with client.stream(
            "GET",
            "/api/agent/workbench/stream",
            params={"q": "inspect this idea", "request_id": "req-failed-workbench"},
        ) as response:
            assert response.status_code == 200
            raw = "".join(response.iter_text())
    finally:
        main.app.dependency_overrides.pop(main.require_user_dependency, None)

    finished = _sse_payloads(raw, "LLMCallFinished")
    failures = _sse_payloads(raw, "FailureDetected")
    done = _sse_payloads(raw, "done")
    assert finished
    assert failures
    terminal_finished = next(
        event
        for event in reversed(finished)
        if event["data"]["record_kind"] == "terminal"
    )
    assert terminal_finished["data"]["status"] == "error"
    assert failures[-1]["data"]["call_id"] == terminal_finished["data"]["call_id"]
    assert failures[-1]["data"]["failure_stage"] == "provider"
    assert done[-1]["succeeded"] is False
    assert done[-1]["failure_kind"] == "GatewayError"
    assert "offline provider unavailable" not in raw
    assert raw.index("event: LLMCallFinished") < raw.index("event: FailureDetected")
    assert raw.index("event: FailureDetected") < raw.index("event: done")
