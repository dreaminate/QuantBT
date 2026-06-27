"""v0.8.6 · Mode 2 多轮对话 + RAG 测试。"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.agent.conversations import ChatError, ChatService, VALID_MARKET_MODES
from app.agent.llm_client import LLMResponse
from app.agent.rag import format_rag_context, format_run_context, retrieve
from app.glossary import GlossaryRegistry, load_glossary_dir
from app.main import app
from app.research_os import (
    AssetRAGDocument,
    PersistentCompilerIRStore,
    PersistentGoalEntrypointCoverageRegistry,
    PersistentResearchAssetRAGIndex,
    RAGPermission,
    ResearchGraphStore,
)


@pytest.fixture
def svc(tmp_path: Path) -> ChatService:
    return ChatService(tmp_path / "chat.db")


# ============================================================
# ChatService CRUD
# ============================================================


def test_start_thread_basic(svc: ChatService):
    t = svc.start_thread(user_id="u1", market_mode="ashare_research")
    assert t.thread_id.startswith("thr_")
    assert t.user_id == "u1"
    assert t.market_mode == "ashare_research"
    assert t.state == "ENTER_THREAD"


def test_start_thread_rejects_invalid_market_mode(svc: ChatService):
    with pytest.raises(ChatError):
        svc.start_thread(user_id="u1", market_mode="random_mode")


def test_list_threads_filters_by_user(svc: ChatService):
    svc.start_thread(user_id="a")
    svc.start_thread(user_id="a")
    svc.start_thread(user_id="b")
    assert len(svc.list_threads("a")) == 2
    assert len(svc.list_threads("b")) == 1


def test_update_state_validation(svc: ChatService):
    t = svc.start_thread(user_id="u1")
    svc.update_state(t.thread_id, "RETRIEVE_CONTEXT")
    assert svc.get_thread(t.thread_id).state == "RETRIEVE_CONTEXT"
    with pytest.raises(ChatError):
        svc.update_state(t.thread_id, "BOGUS_STATE")


def test_add_message_basic(svc: ChatService):
    t = svc.start_thread(user_id="u1")
    m = svc.add_message(t.thread_id, "user", "hi")
    assert m.role == "user"
    assert m.content == "hi"
    msgs = svc.list_messages(t.thread_id)
    assert len(msgs) == 1


def test_add_message_rejects_invalid_role(svc: ChatService):
    t = svc.start_thread(user_id="u1")
    with pytest.raises(ChatError):
        svc.add_message(t.thread_id, "evil_role", "x")


def test_add_message_updates_thread_timestamp(svc: ChatService):
    t = svc.start_thread(user_id="u1")
    orig = t.updated_at_utc
    import time as _t
    _t.sleep(1.01)
    svc.add_message(t.thread_id, "user", "hi")
    t2 = svc.get_thread(t.thread_id)
    assert t2.updated_at_utc >= orig


def test_compress_history(svc: ChatService):
    t = svc.start_thread(user_id="u1")
    for i in range(10):
        svc.add_message(t.thread_id, "user", f"msg {i}")
        svc.add_message(t.thread_id, "assistant", f"reply {i}")
    h = svc.compress_history(t.thread_id, max_messages=4, max_chars=400)
    # 4 条且 ≤400 字
    assert len(h) <= 400
    # newest 几条应该在里面
    assert "msg 9" in h or "reply 9" in h


def test_update_active_context(svc: ChatService):
    t = svc.start_thread(user_id="u1")
    svc.update_active_context(t.thread_id, active_run_id="r1", active_strategy_id="s1")
    t2 = svc.get_thread(t.thread_id)
    assert t2.active_run_id == "r1"
    assert t2.active_strategy_id == "s1"


# ============================================================
# RAG retrieval
# ============================================================


def test_retrieve_glossary_hit():
    glossary = load_glossary_dir(Path(__file__).resolve().parents[3] / "docs" / "glossary")
    hits = retrieve("夏普 是什么", glossary=glossary)
    assert len(hits) >= 1
    assert any(h.slug == "sharpe_ratio" for h in hits)


def test_retrieve_pbo_hit():
    glossary = load_glossary_dir(Path(__file__).resolve().parents[3] / "docs" / "glossary")
    hits = retrieve("PBO 0.7 这个策略可信吗", glossary=glossary)
    assert any(h.slug == "pbo" for h in hits)


def test_retrieve_empty_query_returns_empty():
    glossary = load_glossary_dir(Path(__file__).resolve().parents[3] / "docs" / "glossary")
    assert retrieve("", glossary=glossary) == []


def test_retrieve_named_term_ranks_first_over_family_siblings():
    # 回归门：词条补全后正文变长 + "夏普"散落到 sharpe 家族多个词条（自助法夏普/折减夏普…），
    # 若无"别名整体点名"的 boost，canonical 词条会被同族稀释挤出 top-1。
    # 种坏门：谁删了 rag.retrieve 的 named-boost，本测试必红。
    glossary = load_glossary_dir(Path(__file__).resolve().parents[3] / "docs" / "glossary")
    # "夏普" 是 sharpe_ratio 的 standalone 别名，应排第一（而非 bootstrap_sharpe_ci/deflated_sharpe）。
    hits = retrieve("夏普 是什么", glossary=glossary)
    assert hits and hits[0].slug == "sharpe_ratio"
    # 同族其它词条仍可出现在后续位次，但不得盖过被点名者。
    sortino = retrieve("索提诺", glossary=glossary)
    assert sortino and sortino[0].slug == "sortino_ratio"


def test_format_run_context_extracts_key_fields():
    run = {"run_id": "r1", "sharpe": 1.5, "pbo": 0.7, "unknown_field": 42}
    s = format_run_context(run)
    assert "run_id" in s
    assert "sharpe" in s
    assert "pbo" in s
    assert "unknown_field" not in s  # 只挑白名单字段


def test_format_run_context_empty():
    assert "无 active run" in format_run_context(None)


def test_format_rag_context_no_hits():
    assert "无 RAG 命中" in format_rag_context([])


def test_format_rag_context_with_hits():
    from app.agent.rag import RagHit
    hits = [RagHit(kind="glossary", slug="sharpe_ratio", title="Sharpe", snippet="一句话", score=0.8)]
    s = format_rag_context(hits)
    assert "sharpe_ratio" in s
    assert "一句话" in s


# ============================================================
# API endpoints
# ============================================================


@pytest.fixture
def client(tmp_path: Path, monkeypatch) -> TestClient:  # noqa: ANN001
    import app.main as main

    monkeypatch.setattr(main, "CHAT_SERVICE", ChatService(tmp_path / "api_chat.db"))
    monkeypatch.setattr(main, "RESEARCH_GRAPH_STORE", ResearchGraphStore())
    monkeypatch.setattr(main, "COMPILER_IR_STORE", PersistentCompilerIRStore(tmp_path / "compiler_ir.jsonl"))
    monkeypatch.setattr(
        main,
        "GOAL_ENTRYPOINT_COVERAGE_REGISTRY",
        PersistentGoalEntrypointCoverageRegistry(tmp_path / "goal_entrypoint_coverage.jsonl"),
    )
    return TestClient(app)


class _Mode2CapturingLLM:
    provider = "test"

    def __init__(self) -> None:
        self.messages = []

    def chat(self, messages, *, tools=None, model=None, temperature=0.2):  # noqa: ANN001, ARG002
        self.messages = list(messages)
        return LLMResponse(content="legacy mode2 answer")


class _Mode2StreamingLLM:
    provider = "test"

    def __init__(self) -> None:
        self.messages = []

    def stream_chat(self, messages, *, model=None, temperature=0.2):  # noqa: ANN001, ARG002
        self.messages = list(messages)
        yield "streamed legacy answer"


def _legacy_rag_doc(**overrides) -> AssetRAGDocument:
    payload = {
        "source_id": "doc:legacy-mode2",
        "version": "v1",
        "title": "Legacy Mode2 covariance shrinkage note",
        "body": "covariance covariance shrinkage portfolio risk PBO legacy mode2",
        "projection": "ResearchRAG",
        "asset_ref": "qro:legacy-risk",
        "permission": RAGPermission(
            allowed_users=("u1",),
            allowed_desks=("research",),
            allowed_assets=("qro:legacy-risk",),
            permission_tags=("research.read",),
        ),
        "applicability": "candidate research context for legacy mode2 chat",
        "source_kind": "EvidenceSpan",
        "evidence_label": "candidate_context",
    }
    payload.update(overrides)
    return AssetRAGDocument(**payload)


def test_api_chat_start(client: TestClient):
    r = client.post("/api/agent/chat/start", json={"market_mode": "ashare_research"})
    assert r.status_code == 200
    data = r.json()
    assert data["thread_id"].startswith("thr_")
    assert data["state"] == "ENTER_THREAD"


def test_api_chat_start_rejects_bad_market_mode(client: TestClient):
    r = client.post("/api/agent/chat/start", json={"market_mode": "evil"})
    assert r.status_code == 400


def test_api_chat_get_thread_404(client: TestClient):
    r = client.get("/api/agent/chat/thr_nonexistent")
    assert r.status_code == 404


def test_api_send_message_devLocal_round_trip(client: TestClient):
    """完整 round-trip: start → send message → 拿到 assistant 回复（DevLocal LLM fallback）。"""
    r1 = client.post("/api/agent/chat/start", json={"market_mode": "ashare_research"})
    tid = r1.json()["thread_id"]
    r2 = client.post(f"/api/agent/chat/{tid}/message", json={"content": "夏普比率是什么"})
    assert r2.status_code == 200
    assistant = r2.json()
    assert assistant["role"] == "assistant"
    assert len(assistant["content"]) > 0
    # 应该 RAG 命中 sharpe_ratio
    assert any(h["slug"] == "sharpe_ratio" for h in (assistant["metadata"].get("rag_hits") or []))


def test_api_send_message_records_chat_and_agent_shell_goal_coverage(client: TestClient, monkeypatch):
    import app.main as main

    monkeypatch.setattr(main, "_current_agent_llm", lambda run_id=None: _Mode2CapturingLLM())
    secret = "SECRET_SHOULD_NOT_ENTER_LEGACY_GOAL_COVERAGE"
    r1 = client.post("/api/agent/chat/start", json={"market_mode": "ashare_research"})
    tid = r1.json()["thread_id"]
    r2 = client.post(f"/api/agent/chat/{tid}/message", json={"content": f"夏普比率是什么 {secret}"})

    assert r2.status_code == 200, r2.text
    metadata = r2.json()["metadata"]
    assert len(metadata["compiler_ir_refs"]) == 2
    assert len(metadata["compiler_pass_refs"]) == 2
    assert len(metadata["entrypoint_coverage_refs"]) == 2
    coverages = main.GOAL_ENTRYPOINT_COVERAGE_REGISTRY.records()
    assert {(record.entry_source, record.entrypoint_ref) for record in coverages} == {
        ("agent_shell", "agent_shell:legacy_mode2.chat.message"),
        ("chat", "chat:legacy_mode2.chat.message"),
    }
    persisted = str(coverages)
    for ir_ref in metadata["compiler_ir_refs"]:
        persisted += str(main.COMPILER_IR_STORE.ir(ir_ref))
    for pass_ref in metadata["compiler_pass_refs"]:
        persisted += str(main.COMPILER_IR_STORE.compiler_pass(pass_ref))
    assert secret not in persisted
    assert "夏普比率是什么" not in persisted


def test_api_send_message_retrieves_research_asset_rag_when_visible_assets_supplied(tmp_path, monkeypatch):
    import app.main as main

    index = PersistentResearchAssetRAGIndex(tmp_path / "legacy_rag.jsonl")
    index.add(_legacy_rag_doc())
    store = ResearchGraphStore()
    llm = _Mode2CapturingLLM()
    monkeypatch.setattr(main, "RESEARCH_ASSET_RAG_INDEX", index)
    monkeypatch.setattr(main, "RESEARCH_GRAPH_STORE", store)
    monkeypatch.setattr(main, "COMPILER_IR_STORE", PersistentCompilerIRStore(tmp_path / "compiler_ir.jsonl"))
    monkeypatch.setattr(
        main,
        "GOAL_ENTRYPOINT_COVERAGE_REGISTRY",
        PersistentGoalEntrypointCoverageRegistry(tmp_path / "goal_entrypoint_coverage.jsonl"),
    )
    monkeypatch.setattr(main, "_current_agent_llm", lambda run_id=None: llm)
    main.app.dependency_overrides[main.current_user_dependency] = lambda: SimpleNamespace(username="u1", user_id="u1")
    client = TestClient(main.app)
    try:
        start = client.post("/api/agent/chat/start", json={"market_mode": "ashare_research"})
        tid = start.json()["thread_id"]
        response = client.post(
            f"/api/agent/chat/{tid}/message",
            json={
                "content": "Explain covariance shrinkage PBO risk",
                "desk": "research",
                "visible_asset_refs": ["qro:legacy-risk"],
                "permission_tags": ["research.read"],
                "projections": ["ResearchRAG"],
                "rag_search": "vector",
            },
        )
    finally:
        main.app.dependency_overrides.pop(main.current_user_dependency, None)

    assert response.status_code == 200, response.text
    assistant = response.json()
    metadata = assistant["metadata"]
    assert any(h["slug"] == "pbo" for h in metadata["rag_hits"])
    assert metadata["research_asset_rag_hits"][0]["source_id"] == "doc:legacy-mode2"
    assert metadata["research_asset_rag_hits"][0]["evidence_ref"] == "rag:doc:legacy-mode2@v1:qro:legacy-risk"
    assert metadata["research_asset_rag_usage_ids"]
    assert index.agent_usage(source_id="doc:legacy-mode2", user_id="u1")

    prompt_text = "\n".join(message.content for message in llm.messages)
    assert "Research Asset RAG candidate context" in prompt_text
    assert "covariance covariance shrinkage" in prompt_text
    graph_refs = {
        ref
        for command in store.commands()
        if command.command_id in set(metadata["research_graph_command_ids"])
        for ref in command.evidence_refs
    }
    assert "rag:doc:legacy-mode2@v1:qro:legacy-risk" in graph_refs
    assert any(ref.startswith("rag_usage:") for ref in graph_refs)


def test_api_send_message_does_not_auto_retrieve_research_asset_rag_without_visible_assets(tmp_path, monkeypatch):
    import app.main as main

    index = PersistentResearchAssetRAGIndex(tmp_path / "legacy_rag.jsonl")
    index.add(_legacy_rag_doc())
    llm = _Mode2CapturingLLM()
    monkeypatch.setattr(main, "RESEARCH_ASSET_RAG_INDEX", index)
    monkeypatch.setattr(main, "RESEARCH_GRAPH_STORE", ResearchGraphStore())
    monkeypatch.setattr(main, "COMPILER_IR_STORE", PersistentCompilerIRStore(tmp_path / "compiler_ir.jsonl"))
    monkeypatch.setattr(
        main,
        "GOAL_ENTRYPOINT_COVERAGE_REGISTRY",
        PersistentGoalEntrypointCoverageRegistry(tmp_path / "goal_entrypoint_coverage.jsonl"),
    )
    monkeypatch.setattr(main, "_current_agent_llm", lambda run_id=None: llm)
    main.app.dependency_overrides[main.current_user_dependency] = lambda: SimpleNamespace(username="u1", user_id="u1")
    client = TestClient(main.app)
    try:
        start = client.post("/api/agent/chat/start", json={"market_mode": "ashare_research"})
        tid = start.json()["thread_id"]
        response = client.post(
            f"/api/agent/chat/{tid}/message",
            json={
                "content": "Explain covariance shrinkage PBO risk",
                "desk": "research",
                "permission_tags": ["research.read"],
                "projections": ["ResearchRAG"],
            },
        )
    finally:
        main.app.dependency_overrides.pop(main.current_user_dependency, None)

    assert response.status_code == 200, response.text
    metadata = response.json()["metadata"]
    assert metadata["research_asset_rag_hits"] == []
    assert metadata["research_asset_rag_usage_ids"] == []
    assert index.agent_usage(source_id="doc:legacy-mode2", user_id="u1") == []
    prompt_text = "\n".join(message.content for message in llm.messages)
    assert "Research Asset RAG candidate context" not in prompt_text


def test_api_chat_stream_retrieves_research_asset_rag_when_visible_assets_supplied(tmp_path, monkeypatch):
    import app.main as main

    index = PersistentResearchAssetRAGIndex(tmp_path / "legacy_stream_rag.jsonl")
    index.add(_legacy_rag_doc(source_id="doc:legacy-mode2-stream"))
    llm = _Mode2StreamingLLM()
    monkeypatch.setattr(main, "RESEARCH_ASSET_RAG_INDEX", index)
    monkeypatch.setattr(main, "RESEARCH_GRAPH_STORE", ResearchGraphStore())
    monkeypatch.setattr(main, "COMPILER_IR_STORE", PersistentCompilerIRStore(tmp_path / "compiler_ir.jsonl"))
    monkeypatch.setattr(
        main,
        "GOAL_ENTRYPOINT_COVERAGE_REGISTRY",
        PersistentGoalEntrypointCoverageRegistry(tmp_path / "goal_entrypoint_coverage.jsonl"),
    )
    monkeypatch.setattr(main, "_current_agent_llm", lambda run_id=None: llm)
    main.app.dependency_overrides[main.current_user_dependency] = lambda: SimpleNamespace(username="u1", user_id="u1")
    client = TestClient(main.app)
    try:
        start = client.post("/api/agent/chat/start", json={"market_mode": "ashare_research"})
        tid = start.json()["thread_id"]
        with client.stream(
            "GET",
            f"/api/agent/chat/{tid}/stream",
            params=[
                ("q", "covariance shrinkage PBO risk"),
                ("desk", "research"),
                ("visible_asset_refs", "qro:legacy-risk"),
                ("permission_tags", "research.read"),
                ("projections", "ResearchRAG"),
                ("rag_search", "vector"),
            ],
        ) as stream:
            assert stream.status_code == 200
            raw = "".join(chunk for chunk in stream.iter_text())
        thread = client.get(f"/api/agent/chat/{tid}")
    finally:
        main.app.dependency_overrides.pop(main.current_user_dependency, None)

    assert "event: rag" in raw
    assert "event: research_rag" in raw
    assert "rag:doc:legacy-mode2-stream@v1:qro:legacy-risk" in raw
    assert "research_asset_rag_usage_ids" in raw
    assert "entrypoint_coverage_refs" in raw
    assert index.agent_usage(source_id="doc:legacy-mode2-stream", user_id="u1")
    prompt_text = "\n".join(message.content for message in llm.messages)
    assert "Research Asset RAG candidate context" in prompt_text
    assert "covariance covariance shrinkage" in prompt_text

    assistant_messages = [m for m in thread.json()["messages"] if m["role"] == "assistant"]
    metadata = assistant_messages[-1]["metadata"]
    assert len(metadata["qro_ids"]) == 1
    assert len(metadata["research_graph_command_ids"]) == 1
    assert len(metadata["compiler_ir_refs"]) == 1
    assert len(metadata["compiler_pass_refs"]) == 1
    assert len(metadata["entrypoint_coverage_refs"]) == 1
    coverages = main.GOAL_ENTRYPOINT_COVERAGE_REGISTRY.records()
    assert {(record.entry_source, record.entrypoint_ref) for record in coverages} == {
        ("chat", "chat:legacy_mode2.chat.stream")
    }
    assert metadata["research_asset_rag_hits"][0]["source_id"] == "doc:legacy-mode2-stream"
    assert metadata["research_asset_rag_usage_ids"]


def test_api_send_message_empty_content_400(client: TestClient):
    r1 = client.post("/api/agent/chat/start", json={})
    tid = r1.json()["thread_id"]
    r2 = client.post(f"/api/agent/chat/{tid}/message", json={"content": ""})
    assert r2.status_code == 400


def test_api_thread_history_persists(client: TestClient):
    r1 = client.post("/api/agent/chat/start", json={})
    tid = r1.json()["thread_id"]
    client.post(f"/api/agent/chat/{tid}/message", json={"content": "你好"})
    client.post(f"/api/agent/chat/{tid}/message", json={"content": "夏普比率是什么"})
    r = client.get(f"/api/agent/chat/{tid}")
    assert r.status_code == 200
    messages = r.json()["messages"]
    # 应该有 2 个 user + 2 个 assistant
    user_msgs = [m for m in messages if m["role"] == "user"]
    assistant_msgs = [m for m in messages if m["role"] == "assistant"]
    assert len(user_msgs) == 2
    assert len(assistant_msgs) == 2
