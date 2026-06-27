from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app import main
from app.auth import require_user_dependency
from app.research_os import AssetRAGError, DENSE_EMBEDDING_MODEL_REF, PersistentResearchAssetRAGIndex


def _client_with_rag(tmp_path, monkeypatch):
    index = PersistentResearchAssetRAGIndex(tmp_path / "research_asset_rag.jsonl")
    monkeypatch.setattr(main, "RESEARCH_ASSET_RAG_INDEX", index)
    main.app.dependency_overrides[require_user_dependency] = lambda: SimpleNamespace(
        username="u1",
        user_id="u1",
    )
    return TestClient(main.app), index


def _doc_payload(**overrides):
    payload = {
        "source_id": "secretref:binance",
        "version": "v1",
        "title": "Binance SecretRef status",
        "body": "SecretRef exists for market data, scope=read_market_data, last_test=ok.",
        "projection": "DataRAG",
        "asset_ref": "qro:btc-momentum",
        "permission": {
            "allowed_desks": ["data"],
            "allowed_assets": ["qro:btc-momentum"],
            "permission_tags": ["research.read"],
        },
        "applicability": "connection metadata only; no plaintext credential",
        "source_kind": "SecretRefStatus",
        "metadata": {
            "secret_ref": "sec_binance",
            "scope": "read_market_data",
            "last_test": "ok",
        },
        "evidence_label": "candidate_context",
    }
    payload.update(overrides)
    return payload


def test_persistent_rag_api_replays_documents_and_filters_permissions(tmp_path, monkeypatch):
    client, index = _client_with_rag(tmp_path, monkeypatch)
    try:
        add = client.post("/api/research-os/rag/documents", json=_doc_payload())
        assert add.status_code == 200
        assert add.json()["source_id"] == "secretref:binance"

        authorized = client.post(
            "/api/research-os/rag/retrieve",
            json={
                "query": "SecretRef market data",
                "desk": "data",
                "visible_asset_refs": ["qro:btc-momentum"],
                "permission_tags": ["research.read"],
                "projections": ["DataRAG"],
            },
        )
        assert authorized.status_code == 200
        hits = authorized.json()["hits"]
        assert len(hits) == 1
        assert hits[0]["source_id"] == "secretref:binance"
        assert hits[0]["version"] == "v1"
        assert hits[0]["context_role"] == "candidate_context"
        assert "sec_binance" not in hits[0]["snippet"]

        denied = client.post(
            "/api/research-os/rag/retrieve",
            json={
                "query": "SecretRef market data",
                "desk": "strategy",
                "visible_asset_refs": ["qro:btc-momentum"],
                "permission_tags": ["research.read"],
                "projections": ["DataRAG"],
            },
        )
        assert denied.status_code == 200
        assert denied.json()["hits"] == []

        reloaded = PersistentResearchAssetRAGIndex(index.path)
        replayed = reloaded.retrieve(
            "SecretRef market data",
            context=main.RAGQueryContext(
                user_id="u1",
                desk="data",
                visible_asset_refs=("qro:btc-momentum",),
                permission_tags=("research.read",),
            ),
            projections=("DataRAG",),
        )
        assert [hit.source_id for hit in replayed] == ["secretref:binance"]
    finally:
        main.app.dependency_overrides.pop(require_user_dependency, None)


def test_rag_api_rejects_plaintext_secret_without_persisting(tmp_path, monkeypatch):
    client, index = _client_with_rag(tmp_path, monkeypatch)
    try:
        rejected = client.post(
            "/api/research-os/rag/documents",
            json=_doc_payload(metadata={"api_key_plaintext": "sk-live-1234567890abcdef"}),
        )
        assert rejected.status_code == 422
        assert not index.path.exists()
    finally:
        main.app.dependency_overrides.pop(require_user_dependency, None)


def test_agent_rag_retrieval_records_source_version_usage(tmp_path, monkeypatch):
    client, _index = _client_with_rag(tmp_path, monkeypatch)
    try:
        assert client.post("/api/research-os/rag/documents", json=_doc_payload()).status_code == 200
        response = client.post(
            "/api/research-os/rag/retrieve",
            json={
                "query": "SecretRef status",
                "desk": "data",
                "visible_asset_refs": ["qro:btc-momentum"],
                "permission_tags": ["research.read"],
                "projections": ["DataRAG"],
                "actor": "agent",
                "agent_id": "agent:data",
                "purpose": "connection review",
            },
        )
        assert response.status_code == 200
        assert response.json()["agent_usage_ids"]

        usage = client.get("/api/research-os/rag/agent_usage", params={"source_id": "secretref:binance"})
        assert usage.status_code == 200
        item = usage.json()["usage"][0]
        assert item["source_id"] == "secretref:binance"
        assert item["version"] == "v1"
        assert item["agent_id"] == "agent:data"
        assert item["user_id"] == "u1"

        main.app.dependency_overrides[require_user_dependency] = lambda: SimpleNamespace(
            username="u2",
            user_id="u2",
        )
        denied = client.get("/api/research-os/rag/agent_usage", params={"source_id": "secretref:binance"})
        assert denied.status_code == 200
        assert denied.json()["usage"] == []
    finally:
        main.app.dependency_overrides.pop(require_user_dependency, None)


def test_sparse_vector_search_ranks_authorized_hits_and_records_agent_usage(tmp_path, monkeypatch):
    client, _index = _client_with_rag(tmp_path, monkeypatch)
    try:
        risk_doc = _doc_payload(
            source_id="doc:risk-parity",
            version="v1",
            title="Risk parity covariance shrinkage note",
            body="risk parity covariance covariance shrinkage portfolio construction",
            projection="ResearchRAG",
            asset_ref="qro:portfolio-risk",
            permission={
                "allowed_desks": ["research"],
                "allowed_assets": ["qro:portfolio-risk"],
                "permission_tags": ["research.read"],
            },
            applicability="candidate research evidence for portfolio risk",
            source_kind="EvidenceSpan",
        )
        momentum_doc = _doc_payload(
            source_id="doc:momentum",
            version="v1",
            title="Momentum breakout note",
            body="momentum breakout trend following validation plan",
            projection="ResearchRAG",
            asset_ref="qro:portfolio-risk",
            permission={
                "allowed_desks": ["research"],
                "allowed_assets": ["qro:portfolio-risk"],
                "permission_tags": ["research.read"],
            },
            applicability="candidate research evidence for signals",
            source_kind="EvidenceSpan",
        )
        assert client.post("/api/research-os/rag/documents", json=risk_doc).status_code == 200
        assert client.post("/api/research-os/rag/documents", json=momentum_doc).status_code == 200

        response = client.post(
            "/api/research-os/rag/vector_search",
            json={
                "query": "covariance shrinkage risk portfolio",
                "desk": "research",
                "visible_asset_refs": ["qro:portfolio-risk"],
                "permission_tags": ["research.read"],
                "projections": ["ResearchRAG"],
                "actor": "agent",
                "agent_id": "agent:research",
                "purpose": "portfolio risk review",
            },
        )
        assert response.status_code == 200
        body = response.json()
        assert [hit["source_id"] for hit in body["hits"]][:2] == ["doc:risk-parity", "doc:momentum"]
        assert body["hits"][0]["score"] > body["hits"][1]["score"]
        assert body["hits"][0]["context_role"] == "candidate_context"
        assert body["agent_usage_ids"]

        usage = client.get("/api/research-os/rag/agent_usage", params={"source_id": "doc:risk-parity"})
        assert usage.status_code == 200
        assert usage.json()["usage"][0]["agent_id"] == "agent:research"

        denied = client.post(
            "/api/research-os/rag/vector_search",
            json={
                "query": "covariance shrinkage risk portfolio",
                "desk": "data",
                "visible_asset_refs": ["qro:portfolio-risk"],
                "permission_tags": ["research.read"],
                "projections": ["ResearchRAG"],
            },
        )
        assert denied.status_code == 200
        assert denied.json()["hits"] == []
    finally:
        main.app.dependency_overrides.pop(require_user_dependency, None)


def test_dense_vector_search_persists_local_embedding_index_and_records_usage(tmp_path, monkeypatch):
    client, index = _client_with_rag(tmp_path, monkeypatch)
    try:
        risk_doc = _doc_payload(
            source_id="doc:risk-parity-dense",
            version="v1",
            title="Risk parity covariance shrinkage note",
            body="risk parity covariance covariance shrinkage portfolio construction",
            projection="ResearchRAG",
            asset_ref="qro:portfolio-risk",
            permission={
                "allowed_desks": ["research"],
                "allowed_assets": ["qro:portfolio-risk"],
                "permission_tags": ["research.read"],
            },
            applicability="candidate research evidence for portfolio risk",
            source_kind="EvidenceSpan",
        )
        momentum_doc = _doc_payload(
            source_id="doc:momentum-dense",
            version="v1",
            title="Momentum breakout note",
            body="momentum breakout trend following validation plan",
            projection="ResearchRAG",
            asset_ref="qro:portfolio-risk",
            permission={
                "allowed_desks": ["research"],
                "allowed_assets": ["qro:portfolio-risk"],
                "permission_tags": ["research.read"],
            },
            applicability="candidate research evidence for signals",
            source_kind="EvidenceSpan",
        )
        assert client.post("/api/research-os/rag/documents", json=risk_doc).status_code == 200
        assert client.post("/api/research-os/rag/documents", json=momentum_doc).status_code == 200
        assert "dense_embedding_indexed" in index.path.read_text(encoding="utf-8")
        assert {vector.embedding_model_ref for vector in index.dense_vectors()} == {DENSE_EMBEDDING_MODEL_REF}

        response = client.post(
            "/api/research-os/rag/dense_vector_search",
            json={
                "query": "covariance shrinkage risk portfolio",
                "desk": "research",
                "visible_asset_refs": ["qro:portfolio-risk"],
                "permission_tags": ["research.read"],
                "projections": ["ResearchRAG"],
                "actor": "agent",
                "agent_id": "agent:research",
                "purpose": "portfolio risk dense retrieval",
            },
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["embedding_model_ref"] == DENSE_EMBEDDING_MODEL_REF
        assert [hit["source_id"] for hit in body["hits"]][:2] == ["doc:risk-parity-dense", "doc:momentum-dense"]
        assert body["hits"][0]["score"] > body["hits"][1]["score"]
        assert body["hits"][0]["context_role"] == "candidate_context"
        assert body["agent_usage_ids"]

        reloaded = PersistentResearchAssetRAGIndex(index.path)
        replayed = reloaded.dense_vector_search(
            "covariance shrinkage risk portfolio",
            context=main.RAGQueryContext(
                user_id="u1",
                desk="research",
                visible_asset_refs=("qro:portfolio-risk",),
                permission_tags=("research.read",),
            ),
            projections=("ResearchRAG",),
        )
        assert [hit.source_id for hit in replayed][:2] == ["doc:risk-parity-dense", "doc:momentum-dense"]

        denied = client.post(
            "/api/research-os/rag/dense_vector_search",
            json={
                "query": "covariance shrinkage risk portfolio",
                "desk": "data",
                "visible_asset_refs": ["qro:portfolio-risk"],
                "permission_tags": ["research.read"],
                "projections": ["ResearchRAG"],
            },
        )
        assert denied.status_code == 200
        assert denied.json()["hits"] == []
    finally:
        main.app.dependency_overrides.pop(require_user_dependency, None)


def test_persistent_rag_index_rejects_malformed_history(tmp_path):
    path = tmp_path / "research_asset_rag.jsonl"
    path.write_text('{"schema_version":1,"event_type":"document_added","document":{"source_id":"x"}}\n', encoding="utf-8")

    with pytest.raises(AssetRAGError, match="invalid persisted Research Asset RAG row"):
        PersistentResearchAssetRAGIndex(path)
