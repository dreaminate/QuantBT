"""v0.8.6 · Mode 2 多轮对话 + RAG 测试。"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from conftest import build_test_agent_gateway

from app.agent.conversations import ChatError, ChatService, VALID_MARKET_MODES
from app.agent.llm_client import LLMResponse
from app.agent.rag import format_rag_context, format_run_context, retrieve
from app.glossary import GlossaryRegistry, load_glossary_dir
from app.main import app
from app.research_os import (
    AssetRAGDocument,
    PersistentCompilerIRStore,
    PersistentEntrypointEvidenceRegistry,
    PersistentGoalEntrypointCoverageRegistry,
    PersistentGoalValidationReceiptRegistry,
    PersistentResearchAssetRAGIndex,
    RAGPermission,
    ResearchGraphStore,
)
from app.research_os.goal_proof_ledger import GoalProofLedger
from app.research_os.ref_resolution import build_real_ref_resolver


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


def _patch_route_gateway(main, monkeypatch, client) -> None:  # noqa: ANN001
    monkeypatch.setattr(
        main,
        "_current_agent_gateway",
        # 跨厂商切模型 S3b：_current_agent_gateway 新增 model_pin kwarg;stub 接受并忽略(本组测试不设 pin)。
        lambda run_id=None, *, model_pin=None: build_test_agent_gateway(
            client,
            seal_secret=main.LLM_CALL_RECORD_STORE.seal_secret,
        ),
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
    svc.update_state(t.thread_id, "RETRIEVE_CONTEXT", owner_user_id="u1")
    assert svc.get_thread(t.thread_id, owner_user_id="u1").state == "RETRIEVE_CONTEXT"
    with pytest.raises(ChatError):
        svc.update_state(t.thread_id, "BOGUS_STATE", owner_user_id="u1")


# ---------- 跨厂商切模型 S3b-1：每对话 llm_selection 持久化 ----------

def test_llm_selection_pinned_roundtrip(svc: ChatService):
    t = svc.start_thread(user_id="u1")
    # 默认无 pin → auto
    assert svc.get_llm_selection(t.thread_id, owner_user_id="u1") == {"mode": "auto"}
    saved = svc.update_llm_selection(
        t.thread_id, {"mode": "pinned", "provider": "openai", "model": "gpt-5.6-sol"},
        owner_user_id="u1",
    )
    assert saved["mode"] == "pinned" and saved["provider"] == "openai" and saved["model"] == "gpt-5.6-sol"
    got = svc.get_llm_selection(t.thread_id, owner_user_id="u1")
    assert got["provider"] == "openai" and got["model"] == "gpt-5.6-sol"


def test_llm_selection_auto_clears_pin(svc: ChatService):
    t = svc.start_thread(user_id="u1")
    svc.update_llm_selection(t.thread_id, {"mode": "pinned", "provider": "anthropic", "model": "claude-opus-4-8"}, owner_user_id="u1")
    svc.update_llm_selection(t.thread_id, {"mode": "auto"}, owner_user_id="u1")
    assert svc.get_llm_selection(t.thread_id, owner_user_id="u1") == {"mode": "auto"}
    assert "llm_selection" not in svc.get_thread(t.thread_id, owner_user_id="u1").metadata


def test_llm_selection_missing_provider_or_model_is_auto(svc: ChatService):
    t = svc.start_thread(user_id="u1")
    # pinned 但缺 model → 规范化为 auto(不存半残 pin)
    svc.update_llm_selection(t.thread_id, {"mode": "pinned", "provider": "openai"}, owner_user_id="u1")
    assert svc.get_llm_selection(t.thread_id, owner_user_id="u1") == {"mode": "auto"}


def test_llm_selection_owner_scoped(svc: ChatService):
    t = svc.start_thread(user_id="alice")
    # 别的 owner 读/写 alice 的对话 → thread not found(与不存在同形,不泄漏)
    with pytest.raises(ChatError):
        svc.update_llm_selection(t.thread_id, {"mode": "pinned", "provider": "openai", "model": "gpt-4o"}, owner_user_id="mallory")
    with pytest.raises(ChatError):
        svc.get_llm_selection(t.thread_id, owner_user_id="mallory")


def test_llm_selection_per_conversation_isolation(svc: ChatService):
    a = svc.start_thread(user_id="u1")
    b = svc.start_thread(user_id="u1")
    svc.update_llm_selection(a.thread_id, {"mode": "pinned", "provider": "openai", "model": "gpt-4o"}, owner_user_id="u1")
    svc.update_llm_selection(b.thread_id, {"mode": "pinned", "provider": "anthropic", "model": "claude-opus-4-8"}, owner_user_id="u1")
    assert svc.get_llm_selection(a.thread_id, owner_user_id="u1")["provider"] == "openai"
    assert svc.get_llm_selection(b.thread_id, owner_user_id="u1")["provider"] == "anthropic"


def test_llm_selection_unknown_thread_raises(svc: ChatService):
    with pytest.raises(ChatError):
        svc.update_llm_selection("thr_nope", {"mode": "pinned", "provider": "openai", "model": "gpt-4o"}, owner_user_id="u1")


def test_add_message_basic(svc: ChatService):
    t = svc.start_thread(user_id="u1")
    m = svc.add_message(t.thread_id, "user", "hi", owner_user_id="u1")
    assert m.role == "user"
    assert m.content == "hi"
    msgs = svc.list_messages(t.thread_id, owner_user_id="u1")
    assert len(msgs) == 1


def test_add_message_rejects_invalid_role(svc: ChatService):
    t = svc.start_thread(user_id="u1")
    with pytest.raises(ChatError):
        svc.add_message(t.thread_id, "evil_role", "x", owner_user_id="u1")


def test_add_message_updates_thread_timestamp(svc: ChatService):
    t = svc.start_thread(user_id="u1")
    orig = t.updated_at_utc
    import time as _t
    _t.sleep(1.01)
    svc.add_message(t.thread_id, "user", "hi", owner_user_id="u1")
    t2 = svc.get_thread(t.thread_id, owner_user_id="u1")
    assert t2.updated_at_utc >= orig


def test_compress_history(svc: ChatService):
    t = svc.start_thread(user_id="u1")
    for i in range(10):
        svc.add_message(t.thread_id, "user", f"msg {i}", owner_user_id="u1")
        svc.add_message(t.thread_id, "assistant", f"reply {i}", owner_user_id="u1")
    h = svc.compress_history(
        t.thread_id,
        owner_user_id="u1",
        max_messages=4,
        max_chars=400,
    )
    # 4 条且 ≤400 字
    assert len(h) <= 400
    # newest 几条应该在里面
    assert "msg 9" in h or "reply 9" in h


def test_update_active_context(svc: ChatService):
    t = svc.start_thread(user_id="u1")
    svc.update_active_context(
        t.thread_id,
        owner_user_id="u1",
        active_run_id="r1",
        active_strategy_id="s1",
    )
    t2 = svc.get_thread(t.thread_id, owner_user_id="u1")
    assert t2.active_run_id == "r1"
    assert t2.active_strategy_id == "s1"


def test_thread_owner_isolation_survives_reopen(tmp_path: Path):
    db_path = tmp_path / "chat-owner.db"
    service = ChatService(db_path)
    thread = service.start_thread(user_id="owner-a")
    service.add_message(
        thread.thread_id,
        "user",
        "owner-only",
        owner_user_id="owner-a",
    )

    for operation in (
        lambda: service.get_thread(thread.thread_id, owner_user_id="owner-b"),
        lambda: service.list_messages(thread.thread_id, owner_user_id="owner-b"),
        lambda: service.add_message(
            thread.thread_id,
            "assistant",
            "foreign-write",
            owner_user_id="owner-b",
        ),
        lambda: service.update_state(
            thread.thread_id,
            "FOLLOW_UP_UPDATE",
            owner_user_id="owner-b",
        ),
        lambda: service.update_active_context(
            thread.thread_id,
            owner_user_id="owner-b",
            active_run_id="foreign-run",
        ),
    ):
        with pytest.raises(ChatError, match="^thread not found$"):
            operation()

    reopened = ChatService(db_path)
    with pytest.raises(ChatError, match="^thread not found$"):
        reopened.get_thread(thread.thread_id, owner_user_id="owner-b")
    owned = reopened.get_thread(thread.thread_id, owner_user_id="owner-a")
    messages = reopened.list_messages(thread.thread_id, owner_user_id="owner-a")
    assert owned.state == "ENTER_THREAD"
    assert owned.active_run_id is None
    assert [message.content for message in messages] == ["owner-only"]


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
def client(tmp_path: Path, monkeypatch):  # noqa: ANN001
    import app.main as main

    monkeypatch.setattr(main, "CHAT_SERVICE", ChatService(tmp_path / "api_chat.db"))
    _patch_goal_proof_stores(main, tmp_path, monkeypatch)
    _patch_route_gateway(main, monkeypatch, _Mode2CapturingLLM())
    main.app.dependency_overrides[main.require_user_dependency] = lambda: SimpleNamespace(
        username="u1",
        user_id="u1",
    )
    try:
        yield TestClient(app)
    finally:
        main.app.dependency_overrides.pop(main.require_user_dependency, None)


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

    def chat(self, messages, *, tools=None, model=None, temperature=0.2):  # noqa: ANN001, ARG002
        self.messages = list(messages)
        return LLMResponse(content="streamed legacy answer")


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


def test_api_chat_foreign_owner_cannot_read_write_or_stream(client: TestClient):
    import app.main as main

    created = client.post(
        "/api/agent/chat/start",
        json={"market_mode": "ashare_research"},
    )
    assert created.status_code == 200
    thread_id = created.json()["thread_id"]

    main.app.dependency_overrides[main.require_user_dependency] = lambda: SimpleNamespace(
        username="u2",
        user_id="u2",
    )
    assert client.get(f"/api/agent/chat/{thread_id}").status_code == 404
    assert client.post(
        f"/api/agent/chat/{thread_id}/message",
        json={"content": "foreign write"},
    ).status_code == 404
    assert client.get(
        f"/api/agent/chat/{thread_id}/stream",
        params={"q": "foreign stream"},
    ).status_code == 404
    assert client.get("/api/agent/chat/threads").json() == []

    main.app.dependency_overrides[main.require_user_dependency] = lambda: SimpleNamespace(
        username="u1",
        user_id="u1",
    )
    owner_view = client.get(f"/api/agent/chat/{thread_id}")
    assert owner_view.status_code == 200
    assert owner_view.json()["messages"] == []


def test_api_chat_run_binding_rejects_path_escape_and_foreign_or_ownerless_run(
    client: TestClient,
    tmp_path: Path,
    monkeypatch,
):
    from app import run_detail_core

    run_root = tmp_path / "runs"
    run_root.mkdir()
    monkeypatch.setattr(run_detail_core, "RUN_ROOT", run_root)

    def write_run(run_id: str, **manifest_overrides) -> Path:
        path = run_root / run_id
        path.mkdir()
        manifest = {
            "run_id": run_id,
            "status": "completed",
            "metrics": {"sharpe": 1.23},
            **manifest_overrides,
        }
        (path / "run.json").write_text(json.dumps(manifest), encoding="utf-8")
        return path

    write_run("owner-a-run", owner_user_id="u1")
    write_run("owner-b-run", owner_user_id="u2")
    write_run("ownerless-run")
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "run.json").write_text(
        json.dumps({"run_id": "outside", "metrics": {"sharpe": 9.99}}),
        encoding="utf-8",
    )

    for active_run_id in (
        str(outside),
        "../outside",
        "owner-b-run",
        "ownerless-run",
    ):
        response = client.post(
            "/api/agent/chat/start",
            json={"active_run_id": active_run_id},
        )
        assert response.status_code == 404
        assert response.json()["detail"] == "run not found"

    accepted = client.post(
        "/api/agent/chat/start",
        json={"active_run_id": "owner-a-run"},
    )
    assert accepted.status_code == 200, accepted.text
    assert accepted.json()["active_run_id"] == "owner-a-run"
    threads = client.get("/api/agent/chat/threads").json()
    assert [thread["active_run_id"] for thread in threads] == ["owner-a-run"]


def test_api_send_message_devLocal_round_trip(client: TestClient):
    """完整 round-trip: start → send message → 拿到 assistant 回复（DevLocal LLM fallback）。"""
    r1 = client.post("/api/agent/chat/start", json={"market_mode": "ashare_research"})
    tid = r1.json()["thread_id"]
    r2 = client.post(f"/api/agent/chat/{tid}/message", json={"content": "夏普比率是什么"})
    assert r2.status_code == 200
    assistant = r2.json()
    assert assistant["role"] == "assistant"
    assert len(assistant["content"]) > 0
    metadata = assistant["metadata"]
    assert metadata["rag_hits"] == []
    assert metadata["legacy_rag_not_injected"] is True
    assert metadata["legacy_rag_disclosure"]["reason"] == "missing_required_provenance_and_strict_usage"


def test_api_send_message_records_chat_goal_coverage(client: TestClient, monkeypatch):
    import app.main as main

    _patch_route_gateway(main, monkeypatch, _Mode2CapturingLLM())
    secret = "SECRET_SHOULD_NOT_ENTER_LEGACY_GOAL_COVERAGE"
    r1 = client.post("/api/agent/chat/start", json={"market_mode": "ashare_research"})
    tid = r1.json()["thread_id"]
    r2 = client.post(f"/api/agent/chat/{tid}/message", json={"content": f"夏普比率是什么 {secret}"})

    assert r2.status_code == 200, r2.text
    metadata = r2.json()["metadata"]
    assert len(metadata["compiler_ir_refs"]) == 1
    assert len(metadata["compiler_pass_refs"]) == 1
    assert len(metadata["entrypoint_coverage_refs"]) == 1
    coverages = main.GOAL_ENTRYPOINT_COVERAGE_REGISTRY.records()
    assert {(record.entry_source, record.entrypoint_ref) for record in coverages} == {
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
    index.add_for_owner(_legacy_rag_doc(), owner_user_id="u1")
    store = ResearchGraphStore()
    llm = _Mode2CapturingLLM()
    monkeypatch.setattr(main, "RESEARCH_ASSET_RAG_INDEX", index)
    _patch_goal_proof_stores(main, tmp_path, monkeypatch, graph=store)
    _patch_route_gateway(main, monkeypatch, llm)
    main.app.dependency_overrides[main.require_user_dependency] = lambda: SimpleNamespace(username="u1", user_id="u1")
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
        main.app.dependency_overrides.pop(main.require_user_dependency, None)

    assert response.status_code == 200, response.text
    assistant = response.json()
    metadata = assistant["metadata"]
    assert metadata["rag_hits"] == []
    assert metadata["legacy_rag_not_injected"] is True
    canonical_hit = metadata["research_asset_rag_hits"][0]
    assert canonical_hit["source_id"] == "doc:legacy-mode2"
    assert canonical_hit["evidence_ref"] == "rag:doc:legacy-mode2@v1:qro:legacy-risk"
    for field in ("source_id", "version", "timestamp", "permission", "applicability"):
        assert canonical_hit[field]
    assert metadata["research_asset_rag_usage_ids"]
    usages = [
        index.strict_usage_for_owner(usage_id, owner_user_id="u1")
        for usage_id in metadata["research_asset_rag_usage_ids"]
    ]
    assert all(
        index.validate_current_usage(usage.usage_id, owner_user_id="u1").accepted
        for usage in usages
    )
    assert any(
        document.source_id == "doc:legacy-mode2"
        for usage in usages
        for document in usage.returned_documents
    )

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
    index.add_for_owner(_legacy_rag_doc(), owner_user_id="u1")
    llm = _Mode2CapturingLLM()
    monkeypatch.setattr(main, "RESEARCH_ASSET_RAG_INDEX", index)
    _patch_goal_proof_stores(main, tmp_path, monkeypatch)
    _patch_route_gateway(main, monkeypatch, llm)
    main.app.dependency_overrides[main.require_user_dependency] = lambda: SimpleNamespace(username="u1", user_id="u1")
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
        main.app.dependency_overrides.pop(main.require_user_dependency, None)

    assert response.status_code == 200, response.text
    metadata = response.json()["metadata"]
    assert metadata["rag_hits"] == []
    assert metadata["legacy_rag_not_injected"] is True
    assert metadata["research_asset_rag_hits"] == []
    assert metadata["research_asset_rag_usage_ids"] == []
    assert index.strict_usage_records(owner_user_id="u1") == []
    prompt_text = "\n".join(message.content for message in llm.messages)
    assert "These hits are permission-filtered candidate context" not in prompt_text
    assert "covariance covariance shrinkage portfolio risk PBO legacy mode2" not in prompt_text


def test_api_send_message_never_injects_unversioned_glossary_or_run_context(
    client: TestClient,
    monkeypatch,
):
    import app.main as main

    llm = _Mode2CapturingLLM()
    _patch_route_gateway(main, monkeypatch, llm)
    start = client.post("/api/agent/chat/start", json={"market_mode": "ashare_research"})
    thread_id = start.json()["thread_id"]
    main.CHAT_SERVICE.update_active_context(
        thread_id,
        owner_user_id="u1",
        active_run_id="owner-run-with-unversioned-summary",
    )
    monkeypatch.setattr(
        main,
        "_require_chat_run_access",
        lambda run_id, user: run_id,
    )
    monkeypatch.setattr(
        main,
        "_chat_run_response_for_user",
        lambda run_id, user: {
            "metrics": {"sharpe": "RAW_LEGACY_RUN_CONTEXT_SECRET"},
            "jq_overview_metrics": {},
            "risk_summary": {},
        },
    )
    legacy_hits = retrieve("PBO 0.7 这个策略可信吗", glossary=main.GLOSSARY)
    assert legacy_hits

    response = client.post(
        f"/api/agent/chat/{thread_id}/message",
        json={"content": "PBO 0.7 这个策略可信吗"},
    )

    assert response.status_code == 200, response.text
    metadata = response.json()["metadata"]
    prompt_text = "\n".join(message.content for message in llm.messages)
    assert metadata["rag_hits"] == []
    assert metadata["legacy_rag_not_injected"] is True
    assert metadata["legacy_rag_disclosure"]["canonical_path"] == "research_asset_rag"
    assert metadata["active_run_bound"] is True
    assert metadata["had_run_context"] is False
    assert "RAW_LEGACY_RUN_CONTEXT_SECRET" not in prompt_text
    assert "RAW_LEGACY_RUN_CONTEXT_SECRET" not in str(metadata)
    assert all(hit.snippet not in prompt_text for hit in legacy_hits)


def test_api_chat_stream_retrieves_research_asset_rag_when_visible_assets_supplied(tmp_path, monkeypatch):
    import app.main as main

    index = PersistentResearchAssetRAGIndex(tmp_path / "legacy_stream_rag.jsonl")
    index.add_for_owner(
        _legacy_rag_doc(source_id="doc:legacy-mode2-stream"),
        owner_user_id="u1",
    )
    llm = _Mode2StreamingLLM()
    monkeypatch.setattr(main, "RESEARCH_ASSET_RAG_INDEX", index)
    _patch_goal_proof_stores(main, tmp_path, monkeypatch)
    _patch_route_gateway(main, monkeypatch, llm)
    main.app.dependency_overrides[main.require_user_dependency] = lambda: SimpleNamespace(username="u1", user_id="u1")
    client = TestClient(main.app)
    try:
        start = client.post("/api/agent/chat/start", json={"market_mode": "ashare_research"})
        tid = start.json()["thread_id"]
        main.CHAT_SERVICE.update_active_context(
            tid,
            owner_user_id="u1",
            active_run_id="owner-run-with-unversioned-stream-summary",
        )
        monkeypatch.setattr(
            main,
            "_require_chat_run_access",
            lambda run_id, user: run_id,
        )
        monkeypatch.setattr(
            main,
            "_chat_run_response_for_user",
            lambda run_id, user: {
                "metrics": {"sharpe": "RAW_LEGACY_STREAM_RUN_CONTEXT_SECRET"},
                "jq_overview_metrics": {},
                "risk_summary": {},
            },
        )
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
        main.app.dependency_overrides.pop(main.require_user_dependency, None)

    assert "event: rag" in raw
    assert "legacy_rag_not_injected" in raw
    assert "event: research_rag" in raw
    assert "rag:doc:legacy-mode2-stream@v1:qro:legacy-risk" in raw
    assert "research_asset_rag_usage_ids" in raw
    assert "entrypoint_coverage_refs" in raw
    usages = index.strict_usage_records(owner_user_id="u1")
    assert all(
        index.validate_current_usage(usage.usage_id, owner_user_id="u1").accepted
        for usage in usages
    )
    assert any(
        document.source_id == "doc:legacy-mode2-stream"
        for usage in usages
        for document in usage.returned_documents
    )
    prompt_text = "\n".join(message.content for message in llm.messages)
    assert "Research Asset RAG candidate context" in prompt_text
    assert "covariance covariance shrinkage" in prompt_text
    legacy_hits = retrieve("covariance shrinkage PBO risk", glossary=main.GLOSSARY)
    assert all(hit.snippet not in prompt_text for hit in legacy_hits)
    assert "RAW_LEGACY_STREAM_RUN_CONTEXT_SECRET" not in prompt_text
    assert "RAW_LEGACY_STREAM_RUN_CONTEXT_SECRET" not in raw

    assistant_messages = [m for m in thread.json()["messages"] if m["role"] == "assistant"]
    metadata = assistant_messages[-1]["metadata"]
    assert len(metadata["qro_ids"]) == 3
    assert len(metadata["research_graph_command_ids"]) == 3
    assert len(metadata["compiler_ir_refs"]) == 1
    assert len(metadata["compiler_pass_refs"]) == 1
    assert len(metadata["entrypoint_coverage_refs"]) == 1
    coverages = main.GOAL_ENTRYPOINT_COVERAGE_REGISTRY.records()
    assert {(record.entry_source, record.entrypoint_ref) for record in coverages} == {
        ("chat", "chat:legacy_mode2.chat.stream")
    }
    assert metadata["research_asset_rag_hits"][0]["source_id"] == "doc:legacy-mode2-stream"
    assert metadata["rag_hits"] == []
    assert metadata["legacy_rag_not_injected"] is True
    assert metadata["active_run_bound"] is True
    assert metadata["had_run_context"] is False
    assert metadata["research_asset_rag_usage_ids"]
    assert {usage.usage_id for usage in usages} == set(metadata["research_asset_rag_usage_ids"])


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
