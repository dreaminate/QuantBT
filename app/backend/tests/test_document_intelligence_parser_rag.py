from __future__ import annotations

from types import SimpleNamespace

from fastapi.testclient import TestClient

from app import main
from app.auth import require_user_dependency
from app.research_os import PersistentDocumentIntelligenceStore, PersistentResearchAssetRAGIndex
from app.research_os import document_intelligence as di


def _client_with_parser(tmp_path, monkeypatch):
    doc_store = PersistentDocumentIntelligenceStore(tmp_path / "audit" / "document_intelligence.jsonl")
    rag_index = PersistentResearchAssetRAGIndex(tmp_path / "audit" / "research_asset_rag.jsonl")
    monkeypatch.setattr(main, "DOCUMENT_INTELLIGENCE_STORE", doc_store)
    monkeypatch.setattr(main, "RESEARCH_ASSET_RAG_INDEX", rag_index)
    monkeypatch.setattr(main, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(main, "DATA_ROOT", tmp_path / "runtime")
    main.app.dependency_overrides[require_user_dependency] = lambda: SimpleNamespace(
        username="u1",
        user_id="u1",
    )
    return TestClient(main.app), doc_store, rag_index


def _write_doc(root, relative_path: str, text: str) -> None:
    path = root / relative_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _write_pdf(root, relative_path: str, lines: list[str]) -> None:
    from reportlab.pdfgen import canvas

    path = root / relative_path
    path.parent.mkdir(parents=True, exist_ok=True)
    pdf = canvas.Canvas(str(path))
    y = 760
    for line in lines:
        pdf.drawString(72, y, line)
        y -= 18
    pdf.save()


def _write_scanned_pdf(root, relative_path: str) -> None:
    from PIL import Image, ImageDraw

    path = root / relative_path
    path.parent.mkdir(parents=True, exist_ok=True)
    image = Image.new("RGB", (900, 240), "white")
    draw = ImageDraw.Draw(image)
    draw.text((40, 90), "Scanned PDF momentum evidence", fill="black")
    image.save(path, "PDF")


def _payload(**overrides) -> dict:
    payload = {
        "source_path": "docs/paper.md",
        "license_rights_ref": "license:rights:user_supplied_local",
        "asset_ref": "qro:research:momentum-paper",
        "desk": "research",
        "permission_tags": ["research.read"],
    }
    payload.update(overrides)
    return payload


def test_parse_local_markdown_records_spans_and_indexes_research_rag(tmp_path, monkeypatch):
    _write_doc(
        tmp_path,
        "docs/paper.md",
        """# Momentum note

Cross sectional momentum signal uses twelve month returns and skips the latest month.

Validation should use CPCV and span support verification before confirmatory use.
""",
    )
    client, doc_store, _rag_index = _client_with_parser(tmp_path, monkeypatch)
    try:
        parsed = client.post("/api/research-os/documents/parse_local", json=_payload())
        assert parsed.status_code == 200
        body = parsed.json()
        assert body["source_ref"].startswith("source_doc:")
        assert body["source_hash"].startswith("sha256:")
        assert body["doc_version_id"].startswith("doc_version:")
        assert body["parser_run_id"].startswith("parser_run:")
        assert len(body["span_refs"]) >= 2
        assert len(body["rag_document_ids"]) == len(body["span_refs"])
        assert "text" not in body["blocks"][0]

        reloaded = PersistentDocumentIntelligenceStore(doc_store.path)
        assert reloaded.source(body["source_ref"]).no_network_parser is True
        assert [span.span_ref for span in reloaded.spans()] == body["span_refs"]
        assert all(span.verified for span in reloaded.spans())

        retrieved = client.post(
            "/api/research-os/rag/retrieve",
            json={
                "query": "momentum CPCV validation",
                "desk": "research",
                "visible_asset_refs": ["qro:research:momentum-paper"],
                "permission_tags": ["research.read"],
                "projections": ["ResearchRAG"],
            },
        )
        assert retrieved.status_code == 200
        hits = retrieved.json()["hits"]
        assert hits
        assert hits[0]["source_id"] in body["span_refs"]
        assert hits[0]["version"] == body["doc_version_id"]
        assert hits[0]["context_role"] == "candidate_context"
    finally:
        main.app.dependency_overrides.pop(require_user_dependency, None)


def test_parse_local_pdf_records_page_anchored_spans_and_rag_context(tmp_path, monkeypatch):
    _write_pdf(
        tmp_path,
        "docs/paper.pdf",
        [
            "PDF momentum evidence span",
            "CPCV validation belongs in the evidence record",
        ],
    )
    client, doc_store, _rag_index = _client_with_parser(tmp_path, monkeypatch)
    try:
        parsed = client.post(
            "/api/research-os/documents/parse_local",
            json=_payload(source_path="docs/paper.pdf"),
        )
        assert parsed.status_code == 200
        body = parsed.json()
        assert body["mime_magic_check_ref"] == "mime:application/pdf:suffix:.pdf:magic:%PDF"
        assert body["blocks"]
        assert {block["page"] for block in body["blocks"]} == {1}
        assert "text" not in body["blocks"][0]
        assert body["blocks"][0]["layout_kind"] == "pdf_text_block"
        assert isinstance(body["blocks"][0]["layout_block_index"], int)
        assert len(body["blocks"][0]["layout_bbox"]) == 4

        reloaded = PersistentDocumentIntelligenceStore(doc_store.path)
        assert reloaded.source(body["source_ref"]).parser_sandbox_ref == (
            "parser_sandbox:local_pdf_pymupdf_layout_no_network_v1"
        )
        assert [span.page for span in reloaded.spans()] == [1]

        retrieved = client.post(
            "/api/research-os/rag/retrieve",
            json={
                "query": "PDF momentum CPCV",
                "desk": "research",
                "visible_asset_refs": ["qro:research:momentum-paper"],
                "permission_tags": ["research.read"],
                "projections": ["ResearchRAG"],
            },
        )
        assert retrieved.status_code == 200
        assert retrieved.json()["hits"][0]["source_id"] in body["span_refs"]
    finally:
        main.app.dependency_overrides.pop(require_user_dependency, None)


def test_parse_scanned_pdf_uses_tesseract_ocr_fallback_without_raw_text(tmp_path, monkeypatch):
    _write_scanned_pdf(tmp_path, "docs/scanned.pdf")
    monkeypatch.setattr(di.shutil, "which", lambda name: "/usr/bin/tesseract" if name == "tesseract" else None)
    monkeypatch.setattr(di, "_run_tesseract_ocr", lambda image_path: "Scanned PDF momentum evidence\n")
    client, doc_store, _rag_index = _client_with_parser(tmp_path, monkeypatch)
    try:
        parsed = client.post(
            "/api/research-os/documents/parse_local",
            json=_payload(source_path="docs/scanned.pdf"),
        )
        assert parsed.status_code == 200, parsed.text
        body = parsed.json()
        assert body["blocks"]
        assert "text" not in body["blocks"][0]
        assert body["blocks"][0]["layout_kind"] == "pdf_ocr_page"
        assert body["blocks"][0]["layout_block_index"] == 0

        reloaded = PersistentDocumentIntelligenceStore(doc_store.path)
        assert reloaded.source(body["source_ref"]).parser_sandbox_ref == (
            "parser_sandbox:local_pdf_tesseract_ocr_no_network_v1"
        )

        retrieved = client.post(
            "/api/research-os/rag/retrieve",
            json={
                "query": "scanned momentum evidence",
                "desk": "research",
                "visible_asset_refs": ["qro:research:momentum-paper"],
                "permission_tags": ["research.read"],
                "projections": ["ResearchRAG"],
            },
        )
        assert retrieved.status_code == 200
        assert retrieved.json()["hits"][0]["source_id"] in body["span_refs"]
    finally:
        main.app.dependency_overrides.pop(require_user_dependency, None)


def test_parse_local_html_snapshot_records_visible_text_and_indexes_rag(tmp_path, monkeypatch):
    _write_doc(
        tmp_path,
        "docs/snapshot.html",
        """<!doctype html>
<html>
  <head>
    <title>Web momentum note</title>
    <style>.secret { display: none; }</style>
    <script>const hidden = "script text should not enter rag";</script>
  </head>
  <body>
    <article>
      <h1>Web momentum evidence</h1>
      <p>CPCV validation and covariance shrinkage are visible web evidence.</p>
    </article>
  </body>
</html>
""",
    )
    client, doc_store, _rag_index = _client_with_parser(tmp_path, monkeypatch)
    try:
        parsed = client.post(
            "/api/research-os/documents/parse_local",
            json=_payload(
                source_path="docs/snapshot.html",
                source_url="https://example.com/research/momentum",
                allowed_url_hosts=["example.com"],
            ),
        )
        assert parsed.status_code == 200, parsed.text
        body = parsed.json()
        assert body["source_url"] == "https://example.com/research/momentum"
        assert body["mime_magic_check_ref"].startswith("mime:text/html:suffix:.html:utf8_no_nul:url_host:example.com")
        assert body["blocks"]
        assert "text" not in body["blocks"][0]

        reloaded = PersistentDocumentIntelligenceStore(doc_store.path)
        source = reloaded.source(body["source_ref"])
        assert source.no_network_parser is True
        assert source.parser_sandbox_ref == "parser_sandbox:local_html_snapshot_no_network_v1"

        retrieved = client.post(
            "/api/research-os/rag/retrieve",
            json={
                "query": "web evidence CPCV covariance",
                "desk": "research",
                "visible_asset_refs": ["qro:research:momentum-paper"],
                "permission_tags": ["research.read"],
                "projections": ["ResearchRAG"],
            },
        )
        assert retrieved.status_code == 200
        hits = retrieved.json()["hits"]
        assert hits
        assert "script text should not enter rag" not in str(hits)
        assert hits[0]["source_id"] in body["span_refs"]
    finally:
        main.app.dependency_overrides.pop(require_user_dependency, None)


def test_parse_local_html_snapshot_rejects_non_allowlisted_host_before_writing(tmp_path, monkeypatch):
    _write_doc(tmp_path, "docs/snapshot.html", "<html><body>Visible research note</body></html>")
    client, doc_store, rag_index = _client_with_parser(tmp_path, monkeypatch)
    try:
        rejected = client.post(
            "/api/research-os/documents/parse_local",
            json=_payload(
                source_path="docs/snapshot.html",
                source_url="https://evil.example/research",
                allowed_url_hosts=["example.com"],
            ),
        )
        assert rejected.status_code == 422
        assert "allowed_url_hosts" in rejected.json()["detail"]
        assert not doc_store.path.exists()
        assert not rag_index.path.exists()
    finally:
        main.app.dependency_overrides.pop(require_user_dependency, None)


def test_parse_local_html_snapshot_rejects_tokenized_url_before_writing(tmp_path, monkeypatch):
    _write_doc(tmp_path, "docs/snapshot.html", "<html><body>Visible research note</body></html>")
    client, doc_store, rag_index = _client_with_parser(tmp_path, monkeypatch)
    try:
        rejected = client.post(
            "/api/research-os/documents/parse_local",
            json=_payload(
                source_path="docs/snapshot.html",
                source_url="https://example.com/research?api_key=sk-live-123",
                allowed_url_hosts=["example.com"],
            ),
        )
        assert rejected.status_code == 422
        assert "tokens" in rejected.json()["detail"]
        assert not doc_store.path.exists()
        assert not rag_index.path.exists()
    finally:
        main.app.dependency_overrides.pop(require_user_dependency, None)


def test_parse_local_batch_records_mixed_documents_atomically(tmp_path, monkeypatch):
    _write_doc(tmp_path, "docs/one.md", "Batch markdown momentum CPCV evidence.")
    _write_doc(
        tmp_path,
        "docs/two.html",
        "<html><body><h1>Batch web evidence</h1><p>Covariance shrinkage visible text.</p></body></html>",
    )
    client, doc_store, _rag_index = _client_with_parser(tmp_path, monkeypatch)
    try:
        parsed = client.post(
            "/api/research-os/documents/parse_local_batch",
            json={
                "license_rights_ref": "license:rights:user_supplied_batch",
                "desk": "research",
                "permission_tags": ["research.read"],
                "items": [
                    {
                        "source_path": "docs/one.md",
                        "asset_ref": "qro:research:batch-one",
                    },
                    {
                        "source_path": "docs/two.html",
                        "source_url": "https://example.com/research/two",
                        "allowed_url_hosts": ["example.com"],
                        "asset_ref": "qro:research:batch-two",
                    },
                ],
            },
        )
        assert parsed.status_code == 200, parsed.text
        body = parsed.json()
        assert body["parsed_count"] == 2
        assert body["span_count"] >= 2
        assert body["rag_document_count"] == body["span_count"]
        assert len(body["sources"]) == 2

        reloaded = PersistentDocumentIntelligenceStore(doc_store.path)
        assert len(reloaded.sources()) == 2
        assert len(reloaded.spans()) == body["span_count"]
    finally:
        main.app.dependency_overrides.pop(require_user_dependency, None)


def test_parse_local_batch_rejects_bad_second_item_without_partial_writes(tmp_path, monkeypatch):
    _write_doc(tmp_path, "docs/good.md", "Good batch evidence.")
    _write_doc(
        tmp_path,
        "docs/leaky.md",
        "The leaked credential is api_key=sk-live-1234567890abcdef and must not enter RAG.",
    )
    client, doc_store, rag_index = _client_with_parser(tmp_path, monkeypatch)
    try:
        rejected = client.post(
            "/api/research-os/documents/parse_local_batch",
            json={
                "license_rights_ref": "license:rights:user_supplied_batch",
                "asset_ref": "qro:research:batch",
                "items": [
                    {"source_path": "docs/good.md"},
                    {"source_path": "docs/leaky.md"},
                ],
            },
        )
        assert rejected.status_code == 422
        assert "plaintext secret" in rejected.json()["detail"]
        assert not doc_store.path.exists()
        assert not rag_index.path.exists()
    finally:
        main.app.dependency_overrides.pop(require_user_dependency, None)


def test_parse_local_batch_rejects_duplicate_source_path_before_writing(tmp_path, monkeypatch):
    _write_doc(tmp_path, "docs/one.md", "Duplicate batch evidence.")
    client, doc_store, rag_index = _client_with_parser(tmp_path, monkeypatch)
    try:
        rejected = client.post(
            "/api/research-os/documents/parse_local_batch",
            json={
                "license_rights_ref": "license:rights:user_supplied_batch",
                "asset_ref": "qro:research:batch",
                "items": [
                    {"source_path": "docs/one.md"},
                    {"source_path": "docs/one.md"},
                ],
            },
        )
        assert rejected.status_code == 422
        assert "duplicate" in rejected.json()["detail"]
        assert not doc_store.path.exists()
        assert not rag_index.path.exists()
    finally:
        main.app.dependency_overrides.pop(require_user_dependency, None)


def test_parse_upload_markdown_records_spans_and_indexes_research_rag(tmp_path, monkeypatch):
    client, doc_store, _rag_index = _client_with_parser(tmp_path, monkeypatch)
    try:
        parsed = client.post(
            "/api/research-os/documents/parse_upload",
            files={
                "file": (
                    "upload.md",
                    b"Uploaded momentum note with CPCV validation evidence.",
                    "text/markdown",
                )
            },
            data={
                "license_rights_ref": "license:rights:user_supplied_upload",
                "asset_ref": "qro:research:uploaded-note",
                "desk": "research",
                "permission_tags": "research.read,internal",
            },
        )
        assert parsed.status_code == 200, parsed.text
        body = parsed.json()
        assert body["upload_ref"].startswith("document_upload:")
        assert body["source_path"].startswith("document_uploads/")
        assert body["source_hash"].startswith("sha256:")
        assert body["span_refs"]
        assert len(body["rag_document_ids"]) == len(body["span_refs"])
        assert "raw_document" not in body
        assert (main.DATA_ROOT / body["source_path"]).exists()

        reloaded = PersistentDocumentIntelligenceStore(doc_store.path)
        assert reloaded.source(body["source_ref"]).parser_sandbox_ref == (
            "parser_sandbox:local_text_markdown_no_network_v1"
        )

        retrieved = client.post(
            "/api/research-os/rag/retrieve",
            json={
                "query": "uploaded CPCV momentum",
                "desk": "research",
                "visible_asset_refs": ["qro:research:uploaded-note"],
                "permission_tags": ["research.read", "internal"],
                "projections": ["ResearchRAG"],
            },
        )
        assert retrieved.status_code == 200
        assert retrieved.json()["hits"][0]["source_id"] in body["span_refs"]
    finally:
        main.app.dependency_overrides.pop(require_user_dependency, None)


def test_parse_upload_requires_rights_and_cleans_quarantine_file(tmp_path, monkeypatch):
    client, doc_store, rag_index = _client_with_parser(tmp_path, monkeypatch)
    try:
        rejected = client.post(
            "/api/research-os/documents/parse_upload",
            files={"file": ("upload.md", b"Uploaded note without rights.", "text/markdown")},
            data={
                "license_rights_ref": " ",
                "asset_ref": "qro:research:uploaded-note",
            },
        )
        assert rejected.status_code == 422
        assert "license_rights_ref" in rejected.json()["detail"]
        assert not doc_store.path.exists()
        assert not rag_index.path.exists()
        upload_root = main.DATA_ROOT / "document_uploads"
        assert not upload_root.exists() or not list(upload_root.rglob("*.*"))
    finally:
        main.app.dependency_overrides.pop(require_user_dependency, None)


def test_parse_upload_rejects_secret_bearing_body_without_document_write(tmp_path, monkeypatch):
    client, doc_store, rag_index = _client_with_parser(tmp_path, monkeypatch)
    try:
        rejected = client.post(
            "/api/research-os/documents/parse_upload",
            files={
                "file": (
                    "leaky.md",
                    b"The leaked provider credential is api_key=sk-live-1234567890abcdef.",
                    "text/markdown",
                )
            },
            data={
                "license_rights_ref": "license:rights:user_supplied_upload",
                "asset_ref": "qro:research:uploaded-note",
            },
        )
        assert rejected.status_code == 422
        assert "plaintext secret" in rejected.json()["detail"]
        assert not doc_store.path.exists()
        assert not rag_index.path.exists()
        upload_root = main.DATA_ROOT / "document_uploads"
        assert not upload_root.exists() or not list(upload_root.rglob("*.*"))
    finally:
        main.app.dependency_overrides.pop(require_user_dependency, None)


def test_parse_upload_rejects_filename_path_separators_before_write(tmp_path, monkeypatch):
    client, doc_store, rag_index = _client_with_parser(tmp_path, monkeypatch)
    try:
        rejected = client.post(
            "/api/research-os/documents/parse_upload",
            files={"file": ("../escape.md", b"Path escape upload.", "text/markdown")},
            data={
                "license_rights_ref": "license:rights:user_supplied_upload",
                "asset_ref": "qro:research:uploaded-note",
            },
        )
        assert rejected.status_code == 422
        assert "path separators" in rejected.json()["detail"]
        assert not doc_store.path.exists()
        assert not rag_index.path.exists()
    finally:
        main.app.dependency_overrides.pop(require_user_dependency, None)


def test_sync_local_directory_records_supported_documents_atomically(tmp_path, monkeypatch):
    _write_doc(tmp_path, "docs/library/one.md", "Directory sync momentum evidence.")
    _write_doc(tmp_path, "docs/library/two.txt", "Directory sync CPCV validation.")
    _write_doc(tmp_path, "docs/library/skip.csv", "symbol,value\nBTC,1\n")
    client, doc_store, _rag_index = _client_with_parser(tmp_path, monkeypatch)
    try:
        synced = client.post(
            "/api/research-os/documents/sync_local_directory",
            json={
                "base_path": "docs/library",
                "license_rights_ref": "license:rights:user_supplied_directory",
                "asset_ref": "qro:research:directory-sync",
                "desk": "research",
                "permission_tags": ["research.read"],
            },
        )
        assert synced.status_code == 200, synced.text
        body = synced.json()
        assert body["parsed_count"] == 2
        assert body["rag_document_count"] == body["span_count"]
        assert body["skipped_paths"] == ["docs/library/skip.csv"]

        reloaded = PersistentDocumentIntelligenceStore(doc_store.path)
        assert len(reloaded.sources()) == 2

        retrieved = client.post(
            "/api/research-os/rag/retrieve",
            json={
                "query": "directory sync CPCV momentum",
                "desk": "research",
                "visible_asset_refs": ["qro:research:directory-sync"],
                "permission_tags": ["research.read"],
                "projections": ["ResearchRAG"],
            },
        )
        assert retrieved.status_code == 200
        assert retrieved.json()["hits"]
    finally:
        main.app.dependency_overrides.pop(require_user_dependency, None)


def test_sync_local_directory_rejects_secret_file_without_partial_writes(tmp_path, monkeypatch):
    _write_doc(tmp_path, "docs/library/good.md", "Directory sync good evidence.")
    _write_doc(
        tmp_path,
        "docs/library/leaky.md",
        "The leaked provider credential is api_key=sk-live-1234567890abcdef.",
    )
    client, doc_store, rag_index = _client_with_parser(tmp_path, monkeypatch)
    try:
        rejected = client.post(
            "/api/research-os/documents/sync_local_directory",
            json={
                "base_path": "docs/library",
                "license_rights_ref": "license:rights:user_supplied_directory",
                "asset_ref": "qro:research:directory-sync",
            },
        )
        assert rejected.status_code == 422
        assert "plaintext secret" in rejected.json()["detail"]
        assert not doc_store.path.exists()
        assert not rag_index.path.exists()
    finally:
        main.app.dependency_overrides.pop(require_user_dependency, None)


def test_sync_local_directory_rejects_hidden_or_sensitive_paths(tmp_path, monkeypatch):
    _write_doc(tmp_path, "docs/library/good.md", "Directory sync good evidence.")
    _write_doc(tmp_path, "docs/library/.env", "TOKEN=secret")
    client, doc_store, rag_index = _client_with_parser(tmp_path, monkeypatch)
    try:
        rejected = client.post(
            "/api/research-os/documents/sync_local_directory",
            json={
                "base_path": "docs/library",
                "license_rights_ref": "license:rights:user_supplied_directory",
                "asset_ref": "qro:research:directory-sync",
            },
        )
        assert rejected.status_code == 422
        assert "hidden or sensitive" in rejected.json()["detail"]
        assert not doc_store.path.exists()
        assert not rag_index.path.exists()
    finally:
        main.app.dependency_overrides.pop(require_user_dependency, None)


def test_parse_local_rejects_path_escape_without_partial_persistence(tmp_path, monkeypatch):
    client, doc_store, rag_index = _client_with_parser(tmp_path, monkeypatch)
    try:
        rejected = client.post(
            "/api/research-os/documents/parse_local",
            json=_payload(source_path="../outside.md"),
        )
        assert rejected.status_code == 422
        assert not doc_store.path.exists()
        assert not rag_index.path.exists()
    finally:
        main.app.dependency_overrides.pop(require_user_dependency, None)


def test_parse_local_rejects_fake_pdf_before_writing(tmp_path, monkeypatch):
    path = tmp_path / "docs" / "fake.pdf"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"not a real pdf")
    client, doc_store, rag_index = _client_with_parser(tmp_path, monkeypatch)
    try:
        rejected = client.post(
            "/api/research-os/documents/parse_local",
            json=_payload(source_path="docs/fake.pdf"),
        )
        assert rejected.status_code == 422
        assert "magic check failed" in rejected.json()["detail"]
        assert not doc_store.path.exists()
        assert not rag_index.path.exists()
    finally:
        main.app.dependency_overrides.pop(require_user_dependency, None)


def test_parse_local_requires_license_rights_before_writing(tmp_path, monkeypatch):
    _write_doc(tmp_path, "docs/paper.md", "A local research note.")
    client, doc_store, rag_index = _client_with_parser(tmp_path, monkeypatch)
    try:
        rejected = client.post(
            "/api/research-os/documents/parse_local",
            json=_payload(license_rights_ref=""),
        )
        assert rejected.status_code == 422
        assert "license_rights_ref" in rejected.json()["detail"]
        assert not doc_store.path.exists()
        assert not rag_index.path.exists()
    finally:
        main.app.dependency_overrides.pop(require_user_dependency, None)


def test_parse_local_rejects_binary_text_before_writing(tmp_path, monkeypatch):
    path = tmp_path / "docs" / "bad.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"\xff\xfe\x00\x00")
    client, doc_store, rag_index = _client_with_parser(tmp_path, monkeypatch)
    try:
        rejected = client.post(
            "/api/research-os/documents/parse_local",
            json=_payload(source_path="docs/bad.md"),
        )
        assert rejected.status_code == 422
        assert not doc_store.path.exists()
        assert not rag_index.path.exists()
    finally:
        main.app.dependency_overrides.pop(require_user_dependency, None)


def test_parse_local_rejects_secret_bearing_rag_body_before_document_write(tmp_path, monkeypatch):
    _write_doc(
        tmp_path,
        "docs/leaky.md",
        "The leaked provider credential is api_key=sk-live-1234567890abcdef and must not enter RAG.",
    )
    client, doc_store, rag_index = _client_with_parser(tmp_path, monkeypatch)
    try:
        rejected = client.post(
            "/api/research-os/documents/parse_local",
            json=_payload(source_path="docs/leaky.md"),
        )
        assert rejected.status_code == 422
        assert "plaintext secret" in rejected.json()["detail"]
        assert not doc_store.path.exists()
        assert not rag_index.path.exists()
    finally:
        main.app.dependency_overrides.pop(require_user_dependency, None)
