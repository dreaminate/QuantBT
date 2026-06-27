---
uuid: 79b5e52607174c039fb6397c3828d1f0
title: Document Intelligence local parser to RAG ingestion
status: done
owner: dreaminate
assigned_by: dreaminate
review_status: 1
priority: P1
area: research-os-document-intelligence
source: goal-gap
source_ref: dev/GOAL.md §5/§6 + dev/research/TRACE.md §5/§6 + dev/state/dreaminate/state.md Document Intelligence row
depends_on: [f85dc4996c2842909b7f6118d8e4995a, 3f1dd2ded6564acaa3e788ff2e5c8ed0]
---

# Document Intelligence local parser to RAG ingestion

## Scope [必填]
Add the first real source ingestion seam for GOAL §6: a no-network local
text/Markdown parser that accepts only safe relative project paths, records
`SourceDocumentIntakeRecord` and `EvidenceSpanRecord` through the existing
Document Intelligence store, and optionally indexes each span into the existing
Research Asset RAG backend as candidate context.

This is not the full PDF parser, web fetcher, frontend document search UI,
vector database, or Agent Shell automatic retrieval. It closes the
`Document source ingestion` gap for local UTF-8 text/Markdown sources and keeps
the wider parser/UI/vector work explicit.

## 接线点（file:line，实现时复核）[必填]
| 文件 | 改什么 |
|---|---|
| `app/backend/app/research_os/document_intelligence.py` | Add deterministic safe local text/Markdown parser and span builder |
| `app/backend/app/main.py` | Add `/api/research-os/documents/parse_local` wiring to Document store + RAG index |
| `app/backend/tests/test_document_intelligence_parser_rag.py` | Prove parser ingestion, RAG retrieval, and fail-closed guards |

## 对抗测试设计（种已知 bug，门必抓）[必填]
1. Safe Markdown source with explicit rights record parses into source + spans,
   persists in Document Intelligence, and retrieves through ResearchRAG with
   source/version candidate-context metadata.
2. Path escape or hidden/sensitive path is rejected before any Document/RAG
   write.
3. Missing `license_rights_ref` is rejected before any write.
4. Binary/non-UTF-8/unsupported extension is rejected before any write.
5. Plaintext secret material in a parsed block is rejected by RAG ingestion
   before any Document Intelligence rows persist.

## 验收一句话 [必填]
Local UTF-8 text/Markdown documents can enter Document Intelligence evidence
spans and Research Asset RAG candidate context through a no-network safe parser;
unsafe paths, missing rights, binary files, and secret-bearing RAG bodies fail
closed without partial persistence.

## 完成记录
- Runtime: added `parse_local_text_document`, a deterministic no-network local
  UTF-8 text/Markdown parser that rejects absolute paths, `..` traversal,
  symlinks, hidden/sensitive paths, unsupported suffixes, empty files, oversized
  files, NUL bytes, and non-UTF-8 content before producing
  `SourceDocumentIntakeRecord` + verified `EvidenceSpanRecord` rows.
- API: added `POST /api/research-os/documents/parse_local`; it records parsed
  source/span rows through `DOCUMENT_INTELLIGENCE_STORE` and, when
  `ingest_to_rag=true`, indexes each span as `ResearchRAG` candidate context in
  `RESEARCH_ASSET_RAG_INDEX` with source/version/permission metadata.
- Safety: RAG document construction happens before Document Intelligence
  persistence, so plaintext secret material rejected by the RAG guard does not
  leave partial Document Intelligence JSONL rows.
- Tests: added `app/backend/tests/test_document_intelligence_parser_rag.py`
  covering successful Markdown parse + RAG retrieval, path escape rejection,
  missing rights rejection, binary rejection, and secret-bearing RAG body
  rejection without partial persistence.
- Validation: parser + Document/RAG persistence scoped
  `16 passed, 2 warnings`; §5/§6 adjacent scoped `28 passed, 2 warnings`;
  Research OS scoped `188 passed, 2 warnings`; backend full
  `1504 passed, 13 skipped, 278 warnings`.
- Boundary: this is local text/Markdown source ingestion only. Full PDF/web
  parser pipeline, frontend document search UI, vector search, and Agent Shell
  automatic retrieval remain explicit gaps.
