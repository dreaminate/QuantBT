from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app import main
from app.auth import require_user_dependency
from app.research_os.document_intelligence import (
    EvidenceSpanRecord,
    ExtractedResearchClaim,
    PersistentDocumentIntelligenceStore,
    PrivilegedToolUseRequest,
    SourceDocumentIntakeRecord,
)


def _client_with_store(tmp_path, monkeypatch):
    store = PersistentDocumentIntelligenceStore(tmp_path / "document_intelligence.jsonl")
    monkeypatch.setattr(main, "DOCUMENT_INTELLIGENCE_STORE", store)
    main.app.dependency_overrides[require_user_dependency] = lambda: SimpleNamespace(
        username="u1",
        user_id="u1",
    )
    return TestClient(main.app), store


def _source(**overrides) -> SourceDocumentIntakeRecord:
    data = {
        "source_ref": "source:paper:001",
        "quarantine_ref": "quarantine:001",
        "parser_sandbox_ref": "sandbox:parser",
        "mime_magic_check_ref": "magic:pdf",
        "source_hash": "sha256:paper",
        "license_rights_ref": "license:ok",
        "no_network_parser": True,
        "untrusted_data_boundary_ref": "boundary:document_untrusted",
    }
    data.update(overrides)
    return SourceDocumentIntakeRecord(**data)


def _span(**overrides) -> EvidenceSpanRecord:
    data = {
        "span_ref": "span:001",
        "source_id": "source:paper:001",
        "doc_version_id": "doc_version:001",
        "parser_run_id": "parser_run:001",
        "block_id": "block:42",
        "page": 7,
        "quoted_excerpt_hash": "sha256:quote",
        "parser_confidence": 0.91,
        "span_support_verification_ref": "span_support:001",
        "verified": True,
    }
    data.update(overrides)
    return EvidenceSpanRecord(**data)


def _claim(**overrides) -> ExtractedResearchClaim:
    data = {
        "claim_ref": "claim:strategy:001",
        "claim_kind": "ExtractedStrategySpec",
        "evidence_span_refs": ("span:001",),
        "confirmatory_use": True,
    }
    data.update(overrides)
    return ExtractedResearchClaim(**data)


def _tool_request(**overrides) -> PrivilegedToolUseRequest:
    data = {
        "request_ref": "tool:strategy:001",
        "source_document_ref": "source:paper:001",
        "direct_document_payload": False,
        "schema_constrained_artifact_ref": "extracted_strategy_spec:001",
    }
    data.update(overrides)
    return PrivilegedToolUseRequest(**data)


def _source_payload(**overrides) -> dict:
    payload = _source().__dict__.copy()
    payload.update(overrides)
    return payload


def _span_payload(**overrides) -> dict:
    payload = _span().__dict__.copy()
    payload.update(overrides)
    return payload


def _claim_payload(**overrides) -> dict:
    payload = _claim().__dict__.copy()
    payload["evidence_span_refs"] = list(payload["evidence_span_refs"])
    payload.update(overrides)
    return payload


def _tool_request_payload(**overrides) -> dict:
    payload = _tool_request().__dict__.copy()
    payload.update(overrides)
    return payload


def test_persistent_document_store_replays_verified_evidence_flow(tmp_path):
    path = tmp_path / "document_intelligence.jsonl"
    store = PersistentDocumentIntelligenceStore(path)

    store.record_source(_source())
    store.record_span(_span())
    store.record_claim(_claim())
    store.record_tool_request(_tool_request())

    reloaded = PersistentDocumentIntelligenceStore(path)
    assert reloaded.source("source:paper:001").source_hash == "sha256:paper"
    assert reloaded.span("span:001").verified is True
    assert reloaded.claim("claim:strategy:001").evidence_span_refs == ("span:001",)
    assert reloaded.tool_request("tool:strategy:001").schema_constrained_artifact_ref == "extracted_strategy_spec:001"


def test_document_api_records_summary_without_raw_payload(tmp_path, monkeypatch):
    client, _store = _client_with_store(tmp_path, monkeypatch)
    try:
        source = client.post("/api/research-os/documents/sources", json=_source_payload())
        assert source.status_code == 200
        assert source.json() == {"source_ref": "source:paper:001", "recorded_by": "u1"}

        span = client.post("/api/research-os/documents/evidence_spans", json=_span_payload())
        assert span.status_code == 200
        assert span.json()["span_ref"] == "span:001"

        claim = client.post("/api/research-os/documents/extracted_claims", json=_claim_payload())
        assert claim.status_code == 200
        assert claim.json()["claim_kind"] == "ExtractedStrategySpec"

        tool = client.post("/api/research-os/documents/tool_requests", json=_tool_request_payload())
        assert tool.status_code == 200
        assert tool.json()["source_document_ref"] == "source:paper:001"

        summary = client.get("/api/research-os/documents/summary")
        assert summary.status_code == 200
        body = summary.json()
        assert body["user"] == "u1"
        assert body["sources"][0]["source_ref"] == "source:paper:001"
        assert "raw_document" not in body["sources"][0]
    finally:
        main.app.dependency_overrides.pop(require_user_dependency, None)


def test_document_api_rejects_unsafe_source_without_persisting(tmp_path, monkeypatch):
    client, store = _client_with_store(tmp_path, monkeypatch)
    try:
        rejected = client.post(
            "/api/research-os/documents/sources",
            json=_source_payload(no_network_parser=False),
        )
        assert rejected.status_code == 422
        assert not store.path.exists()
    finally:
        main.app.dependency_overrides.pop(require_user_dependency, None)


def test_document_api_rejects_confirmatory_claim_on_unverified_span(tmp_path, monkeypatch):
    client, store = _client_with_store(tmp_path, monkeypatch)
    try:
        assert client.post("/api/research-os/documents/sources", json=_source_payload()).status_code == 200
        unverified = _span_payload(
            span_ref="span:unverified",
            span_support_verification_ref=None,
            verified=False,
        )
        assert client.post("/api/research-os/documents/evidence_spans", json=unverified).status_code == 200

        rejected = client.post(
            "/api/research-os/documents/extracted_claims",
            json=_claim_payload(evidence_span_refs=["span:unverified"], confirmatory_use=True),
        )
        assert rejected.status_code == 422

        reloaded = PersistentDocumentIntelligenceStore(store.path)
        assert [claim.claim_ref for claim in reloaded.claims()] == []
    finally:
        main.app.dependency_overrides.pop(require_user_dependency, None)


def test_document_api_rejects_direct_document_tool_payload(tmp_path, monkeypatch):
    client, store = _client_with_store(tmp_path, monkeypatch)
    try:
        assert client.post("/api/research-os/documents/sources", json=_source_payload()).status_code == 200
        rejected = client.post(
            "/api/research-os/documents/tool_requests",
            json=_tool_request_payload(direct_document_payload=True, schema_constrained_artifact_ref=None),
        )
        assert rejected.status_code == 422

        reloaded = PersistentDocumentIntelligenceStore(store.path)
        assert [request.request_ref for request in reloaded.tool_requests()] == []
    finally:
        main.app.dependency_overrides.pop(require_user_dependency, None)


def test_persistent_document_store_rejects_empty_record_refs(tmp_path):
    store = PersistentDocumentIntelligenceStore(tmp_path / "document_intelligence.jsonl")

    with pytest.raises(ValueError, match="source_ref is required"):
        store.record_source(_source(source_ref=""))

    store.record_source(_source())
    with pytest.raises(ValueError, match="span_ref is required"):
        store.record_span(_span(span_ref=""))


def test_persistent_document_store_rejects_malformed_history(tmp_path):
    path = tmp_path / "document_intelligence.jsonl"
    path.write_text(
        '{"schema_version":1,"event_type":"source_intake_recorded","source":{"source_ref":"source:bad"}}\n',
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="invalid persisted Document Intelligence row"):
        PersistentDocumentIntelligenceStore(path)
