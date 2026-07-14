from __future__ import annotations

import json
import sqlite3

import pytest

from app.agent.agent_runtime import AgentRAGContext, AgentRAGContextHit
from app.agent.llm_client import LLMResponse
from app.agent.orchestrator import (
    AcceptanceGate,
    AgentOrchestrator,
    AgentTodo,
    make_executor,
)
from app.agent.orchestrator.orchestrator import AgentRuntimeContext
from app.agent.orchestrator.events import (
    EV_FAILURE_DETECTED,
    PersistentWorkflowEventLedger,
)
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
from app.research_os import ActorSource, EntrySource, ResearchGraphStore


PROMPT_TRIPWIRE = "prompt-ORCH-DURABLE-PRIVACY-4d63fa"
OUTPUT_TRIPWIRE = "output-ORCH-DURABLE-PRIVACY-d8492b"
SECRET_TRIPWIRE = "secret-ORCH-DURABLE-PRIVACY-b78711"
TOOL_RESULT_TRIPWIRE = "tool-result-ORCH-DURABLE-PRIVACY-75cf09"
RAG_CONTEXT_TRIPWIRE = "rag-context-ORCH-DURABLE-PRIVACY-b15b62"
SYSTEM_PROMPT_TRIPWIRE = "system-prompt-ORCH-DURABLE-PRIVACY-871bd1"


@pytest.mark.parametrize(
    ("override", "message"),
    [
        ({"source_id": ""}, "source_id"),
        ({"version": ""}, "version"),
        ({"timestamp": "2026-07-13T00:00:00"}, "timezone-aware"),
        ({"permission": {"allowed_users": ()}}, "permission snapshot"),
        ({"applicability": ""}, "applicability"),
        ({"context_role": "system_conclusion"}, "candidate_context"),
    ],
)
def test_agent_rag_context_hit_rejects_incomplete_provenance(override, message):
    payload = {
        "source_id": "source:complete",
        "version": "v1",
        "timestamp": "2026-07-13T00:00:00+00:00",
        "permission": {
            "allowed_users": ("u1",),
            "allowed_desks": ("research",),
            "allowed_assets": ("asset:complete",),
            "permission_tags": ("research.read",),
        },
        "applicability": "candidate context only",
        "asset_ref": "asset:complete",
        "projection": "ResearchRAG",
        "title": "Complete provenance",
        "evidence_label": "candidate_context",
        "context_role": "candidate_context",
        "score": 1.0,
    }
    with pytest.raises(ValueError, match=message):
        AgentRAGContextHit(**(payload | override))


class _SuccessClient:
    provider = "scripted"

    def chat(self, messages, *, tools=None, model=None, temperature=0.2):
        if any(getattr(message, "role", "") == "tool" for message in messages):
            return LLMResponse(content=OUTPUT_TRIPWIRE, tool_calls=[])
        return LLMResponse(
            content="",
            tool_calls=[
                {
                    "id": "privacy-call",
                    "name": "read_asset",
                    "arguments": json.dumps({"credential": SECRET_TRIPWIRE}),
                }
            ],
        )


class _FailureClient:
    provider = "scripted"

    def chat(self, messages, *, tools=None, model=None, temperature=0.2):
        if any(getattr(message, "role", "") == "tool" for message in messages):
            raise RuntimeError(f"{OUTPUT_TRIPWIRE}:{SECRET_TRIPWIRE}")
        return LLMResponse(
            content="",
            tool_calls=[
                {
                    "id": "privacy-failure-call",
                    "name": "read_asset",
                    "arguments": json.dumps({"credential": SECRET_TRIPWIRE}),
                }
            ],
        )


class _RuntimeContextClient:
    provider = "scripted"

    def __init__(self) -> None:
        self.message_snapshots = []
        self.tool_snapshots = []

    def chat(self, messages, *, tools=None, model=None, temperature=0.2):
        self.message_snapshots.append(list(messages))
        self.tool_snapshots.append(list(tools or []))
        if any(getattr(message, "role", "") == "tool" for message in messages):
            return LLMResponse(content=OUTPUT_TRIPWIRE, tool_calls=[])
        return LLMResponse(
            content="",
            tool_calls=[
                {
                    "id": "context-report-call",
                    "name": "report.generate",
                    "arguments": "{}",
                }
            ],
        )


class _PassingTranslator:
    status = "ok"
    reason = ""

    def __init__(self) -> None:
        self.calls = 0

    def translate(self, _tool_calls):
        self.calls += 1
        return self


def _gateway(client) -> LLMGateway:
    profile = LLMModelProfile(
        provider="anthropic",
        model="claude-opus-4",
        capability_tier=ModelTier.STRONG.value,
        pool_id="anthropic",
    )
    keystore = SecureKeystore(InMemoryKeystore())
    keystore.store(
        KeystoreRecord(
            name="anthropic",
            api_key="test-key-anthropic-xxxxxxxx",
            api_secret="test-key-anthropic-xxxxxxxx",
        )
    )
    pool = LLMCredentialPool(keystore)
    pool.register(
        "anthropic",
        SecretRef(
            keystore_name="anthropic",
            provider="anthropic",
            auth_kind="api_key",
        ),
        default_model=profile.model,
    )
    return LLMGateway(
        policy=ModelRoutingPolicy([profile], mode=RoutingMode.HYBRID_ADAPTIVE),
        credential_pool=pool,
        client_factory=lambda _credential: client,
        strict_degrade=False,
    )


def _plan(orchestrator: AgentOrchestrator):
    return orchestrator.plan(
        PROMPT_TRIPWIRE,
        todos=[
            AgentTodo(
                todo_id="privacy-task",
                description=PROMPT_TRIPWIRE,
                role="factor_engineer",
            )
        ],
        dependencies={"privacy-task": []},
        acceptance_gates=[
            AcceptanceGate(
                gate_id="privacy-gate",
                description="metadata-only durable artifact",
                falsifiable_check="disk scan contains no tripwire",
            )
        ],
    )


def _tool_handler(_name: str, args: dict[str, object]) -> dict[str, object]:
    assert args["credential"] == SECRET_TRIPWIRE
    return {
        "result": TOOL_RESULT_TRIPWIRE,
        "credential_echo": args["credential"],
    }


def _assert_tripwires_absent_from_disk(root) -> None:
    tripwires = (
        PROMPT_TRIPWIRE.encode(),
        OUTPUT_TRIPWIRE.encode(),
        SECRET_TRIPWIRE.encode(),
        TOOL_RESULT_TRIPWIRE.encode(),
        RAG_CONTEXT_TRIPWIRE.encode(),
        SYSTEM_PROMPT_TRIPWIRE.encode(),
    )
    scanned = []
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        payload = path.read_bytes()
        scanned.append(path)
        for tripwire in tripwires:
            assert tripwire not in payload, f"plaintext tripwire persisted in {path}"
    assert scanned


def _orchestrator(tmp_path, client):
    ledger = PersistentWorkflowEventLedger(tmp_path / "audit" / "workflow-events.jsonl")
    orchestrator = AgentOrchestrator(
        gateway=_gateway(client),
        event_ledger=ledger,
        owner_user_id="privacy-owner",
        workflow_id="privacy-workflow",
        secret_values=(
            PROMPT_TRIPWIRE,
            OUTPUT_TRIPWIRE,
            SECRET_TRIPWIRE,
            TOOL_RESULT_TRIPWIRE,
            RAG_CONTEXT_TRIPWIRE,
            SYSTEM_PROMPT_TRIPWIRE,
        ),
    )
    return orchestrator, ledger


def test_live_turn_is_ephemeral_and_durable_artifact_is_metadata_only(tmp_path):
    orchestrator, _ledger = _orchestrator(tmp_path, _SuccessClient())
    plan = _plan(orchestrator)
    executor = make_executor(tmp_path / "kernel")

    result = orchestrator.dispatch(
        plan,
        executor=executor,
        instructions={"privacy-task": PROMPT_TRIPWIRE},
        tool_handlers={"factor_engineer": {"read_asset": _tool_handler}},
    )

    assert result.succeeded is True
    assert result.live_final_message_for("privacy-task") == OUTPUT_TRIPWIRE
    live_turn = result.live_turns["privacy-task"]
    assert live_turn.user_input == PROMPT_TRIPWIRE
    assert TOOL_RESULT_TRIPWIRE in json.dumps(
        [step.to_dict() for step in live_turn.steps], ensure_ascii=False
    )

    durable_artifact = result.node_artifacts["privacy-task"]
    assert durable_artifact["artifact_schema"] == "agent_role_metadata_v1"
    assert durable_artifact["status"] == "succeeded"
    assert durable_artifact["tool_call_count"] >= 1
    assert durable_artifact["llm_call_count"] >= 1
    assert len(durable_artifact["final_message_digest"]) == 64
    assert len(durable_artifact["turn_digest"]) == 64
    assert "final_message" not in durable_artifact
    assert "tool_records" not in durable_artifact
    assert "task_id" not in durable_artifact

    database = sqlite3.connect(tmp_path / "kernel" / "artifacts.sqlite")
    try:
        rows = database.execute("SELECT blob FROM artifacts").fetchall()
    finally:
        database.close()
    assert len(rows) == 1
    assert json.loads(rows[0][0]) == durable_artifact

    replayed = orchestrator.replay(
        plan,
        executor=executor,
        instructions={"privacy-task": PROMPT_TRIPWIRE},
        tool_handlers={"factor_engineer": {"read_asset": _tool_handler}},
    )
    assert replayed.succeeded is True
    assert replayed.kernel_result.node("privacy-task").reused is True
    assert replayed.live_turns == {}
    assert replayed.live_final_message_for("privacy-task") is None
    assert replayed.node_artifacts["privacy-task"] == durable_artifact

    _assert_tripwires_absent_from_disk(tmp_path)


def test_failed_role_emits_sanitized_durable_failure_without_plaintext(tmp_path):
    orchestrator, ledger = _orchestrator(tmp_path, _FailureClient())
    plan = _plan(orchestrator)

    result = orchestrator.dispatch(
        plan,
        executor=make_executor(tmp_path / "kernel"),
        instructions={"privacy-task": PROMPT_TRIPWIRE},
        tool_handlers={"factor_engineer": {"read_asset": _tool_handler}},
    )

    assert result.succeeded is False
    assert result.kernel_result.node("privacy-task").status == "failed"
    assert result.live_turns == {}
    durable_events = ledger.events(
        owner_user_id="privacy-owner", workflow_id="privacy-workflow"
    )
    failures = [event for event in durable_events if event.kind == EV_FAILURE_DETECTED]
    assert failures
    assert failures[-1].data["reason"] == "role_node_failed"
    assert failures[-1].data["error_kind"]
    assert set(failures[-1].data) == {
        "reason",
        "error_kind",
        "call_id",
        "llm_status",
        "failure_stage",
        "llm_error_kind",
    }
    assert len(failures[-1].data["call_id"]) == 16
    int(failures[-1].data["call_id"], 16)
    assert failures[-1].data["llm_status"] == "error"
    assert failures[-1].data["failure_stage"]
    assert failures[-1].data["llm_error_kind"] == "all_providers_failed"

    database = sqlite3.connect(tmp_path / "kernel" / "artifacts.sqlite")
    try:
        assert database.execute("SELECT COUNT(*) FROM artifacts").fetchone()[0] == 0
    finally:
        database.close()

    _assert_tripwires_absent_from_disk(tmp_path)


def test_typed_runtime_context_preserves_live_graph_rag_and_filters_tool_schema(tmp_path):
    client = _RuntimeContextClient()
    orchestrator, _ledger = _orchestrator(tmp_path, client)
    graph = ResearchGraphStore()
    translator = _PassingTranslator()
    handler_calls: list[str] = []

    def rag_context_provider(user_input: str) -> AgentRAGContext:
        assert user_input == PROMPT_TRIPWIRE
        return AgentRAGContext(
            prompt_context=RAG_CONTEXT_TRIPWIRE,
            hits=(
                AgentRAGContextHit(
                    source_id="source-context",
                    version="v1",
                    timestamp="2026-07-13T00:00:00+00:00",
                    permission={
                        "allowed_users": ("privacy-owner",),
                        "allowed_desks": ("research",),
                        "allowed_assets": ("asset-context",),
                        "permission_tags": ("research.read",),
                    },
                    applicability="candidate context for the report workflow",
                    asset_ref="asset-context",
                    projection=RAG_CONTEXT_TRIPWIRE,
                    title=RAG_CONTEXT_TRIPWIRE,
                    evidence_label="candidate",
                    context_role="candidate_context",
                    score=0.91,
                ),
            ),
            usage_ids=("usage-context",),
        )

    def report_handler(name: str, _args: dict[str, object]) -> dict[str, object]:
        handler_calls.append(name)
        return {"result": TOOL_RESULT_TRIPWIRE}

    def unauthorized_handler(_name: str, _args: dict[str, object]) -> dict[str, object]:
        raise AssertionError("unauthorized handler must not be registered or called")

    plan = orchestrator.plan(
        PROMPT_TRIPWIRE,
        todos=[
            AgentTodo(
                todo_id="context-task",
                description=PROMPT_TRIPWIRE,
                role="reporter",
            )
        ],
        dependencies={"context-task": []},
        acceptance_gates=[
            AcceptanceGate(
                gate_id="context-gate",
                description="typed runtime context reaches the live turn",
                falsifiable_check="missing graph/RAG/tool evidence fails",
            )
        ],
    )
    runtime_context = AgentRuntimeContext(
        translator=translator,
        permission_mode="bypass",
        research_graph=graph,
        entry_source=EntrySource.CHAT,
        actor="runtime-context-actor",
        owner="privacy-owner",
        rag_context_provider=rag_context_provider,
        system_prompt=SYSTEM_PROMPT_TRIPWIRE,
    )
    executor = make_executor(tmp_path / "kernel")
    handlers = {
        "reporter": {
            "report.generate": report_handler,
            # Registered but not reporter-permitted. It must not enter AgentRuntime.
            "backtest.run": unauthorized_handler,
        }
    }

    result = orchestrator.dispatch(
        plan,
        executor=executor,
        tool_handlers=handlers,
        runtime_context=runtime_context,
    )

    assert result.succeeded is True
    assert handler_calls == ["report.generate"]
    assert translator.calls == 1
    assert client.tool_snapshots
    assert {
        schema.get("name") for schema in client.tool_snapshots[0]
    } == {"report.generate"}
    first_messages = client.message_snapshots[0]
    assert first_messages[0].content == SYSTEM_PROMPT_TRIPWIRE
    assert any(message.content == RAG_CONTEXT_TRIPWIRE for message in first_messages)

    live_turn = result.live_turns["context-task"]
    assert live_turn.final_message == OUTPUT_TRIPWIRE
    assert [step.role for step in live_turn.steps] == [
        "user",
        "system",
        "assistant",
        "tool",
        "assistant",
    ]
    assert live_turn.rag_hits[0]["evidence_ref"] == (
        "rag:source-context@v1:asset-context"
    )
    assert live_turn.rag_hits[0]["timestamp"] == "2026-07-13T00:00:00+00:00"
    assert live_turn.rag_hits[0]["permission"]["allowed_users"] == (
        "privacy-owner",
    )
    assert live_turn.rag_hits[0]["applicability"] == (
        "candidate context for the report workflow"
    )
    assert live_turn.rag_hits[0]["context_role"] == "candidate_context"
    assert live_turn.rag_usage_ids == ["usage-context"]
    assert len(live_turn.qro_ids) == len(live_turn.steps)
    assert len(live_turn.research_graph_command_ids) == len(live_turn.steps)

    commands = graph.commands()
    assert {command.actor for command in commands} == {"runtime-context-actor"}
    assert {
        command.source.value if isinstance(command.source, EntrySource) else command.source
        for command in commands
    } == {EntrySource.CHAT.value}
    assert {
        command.actor_source.value
        if isinstance(command.actor_source, ActorSource)
        else command.actor_source
        for command in commands
    } == {ActorSource.USER_MANUAL.value, ActorSource.AGENT.value}
    assert {graph.qro(qro_id).owner for qro_id in live_turn.qro_ids} == {
        "privacy-owner"
    }
    assert {graph.qro(qro_id).permission for qro_id in live_turn.qro_ids} == {
        "agent_permission_mode:bypass"
    }

    replayed = orchestrator.replay(
        plan,
        executor=executor,
        tool_handlers=handlers,
        runtime_context=runtime_context,
    )
    assert replayed.succeeded is True
    assert replayed.kernel_result.node("context-task").reused is True
    assert replayed.live_turns == {}
    assert replayed.live_final_message_for("context-task") is None

    _assert_tripwires_absent_from_disk(tmp_path)


def test_runtime_context_owner_cannot_cross_orchestrator_identity(tmp_path):
    orchestrator, _ledger = _orchestrator(tmp_path, _SuccessClient())
    plan = _plan(orchestrator)

    try:
        orchestrator.dispatch(
            plan,
            executor=make_executor(tmp_path / "kernel"),
            runtime_context=AgentRuntimeContext(owner="different-owner"),
        )
    except ValueError as exc:
        assert "must match the orchestrator owner_user_id" in str(exc)
    else:
        raise AssertionError("cross-owner runtime context was accepted")
