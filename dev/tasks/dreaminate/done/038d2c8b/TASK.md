---
uuid: 038d2c8b36aa480da154dcdc592bd8f3
title: Document Intelligence local PDF text parser ingestion
status: done
owner: dreaminate
assigned_by: dreaminate
review_status: 1
priority: P1
area: research-os-document-intelligence
source: goal-gap
source_ref: dev/GOAL.md §6 + dev/research/TRACE.md §6 + dev/state/dreaminate/state.md Document Intelligence row
depends_on: [79b5e52607174c039fb6397c3828d1f0]
---

# Document Intelligence local PDF text parser ingestion

## Scope [必填]
Extend the local no-network document parser from UTF-8 text/Markdown to local
PDF text extraction. The parser must accept only safe relative project paths,
verify PDF magic bytes, reject encrypted or non-text PDFs, produce page-anchored
`EvidenceSpanRecord` rows, and optionally index those spans into Research Asset
RAG as candidate context.

This is not a visual layout verifier, web parser, OCR pipeline, frontend
document UI, dense embedding system, or external PDF service.

## 接线点（file:line，实现时复核）[必填]
| 文件 | 改什么 |
|---|---|
| `app/backend/app/research_os/document_intelligence.py` | Add local PDF text extraction path using installed `pypdf` |
| `app/backend/app/main.py` | Route `/api/research-os/documents/parse_local` through the generalized parser |
| `app/backend/tests/test_document_intelligence_parser_rag.py` | Add generated-PDF success and fake-PDF fail-closed tests |

## 对抗测试设计（种已知 bug，门必抓）[必填]
1. Generated local PDF parses into page-anchored verified EvidenceSpans and
   ResearchRAG candidate context.
2. Fake `.pdf` without `%PDF-` magic is rejected before any Document/RAG write.
3. The response still does not return raw extracted document text.
4. Existing text/Markdown parser and secret/path/binary guards remain green.

## 验收一句话 [必填]
Safe local PDFs can enter Document Intelligence evidence spans and ResearchRAG
candidate context through no-network text extraction; fake/encrypted/non-text
PDFs fail closed, and layout/OCR/web/UI/dense-vector work remains explicit.

## 完成记录
- Runtime: generalized local parsing through `parse_local_document` while
  keeping `parse_local_text_document` compatible; `.pdf` sources now require
  `%PDF-` magic bytes, are parsed with installed `pypdf`, reject encrypted PDFs,
  enforce `max_pages`, and produce page-anchored `LocalDocumentBlock` /
  verified `EvidenceSpanRecord` rows.
- API: `POST /api/research-os/documents/parse_local` now routes through the
  generalized parser and accepts local PDF sources under the same safe relative
  path, rights, no-network, Document store, and RAG candidate-context guards as
  text/Markdown.
- Tests: extended `app/backend/tests/test_document_intelligence_parser_rag.py`
  with generated-PDF success and fake-PDF magic fail-closed coverage.
- Validation: parser scoped `7 passed, 2 warnings`; §5/§6 adjacent scoped
  `31 passed, 2 warnings`; Research OS scoped `191 passed, 2 warnings`;
  backend full `1507 passed, 13 skipped, 278 warnings`.
- Boundary: this is text extraction from local PDFs. It is not OCR, web parsing,
  visual layout verification, frontend document UI, dense embeddings, or an
  external PDF service.
