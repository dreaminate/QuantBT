---
uuid: f85dc4996c2842909b7f6118d8e4995a
title: Document Intelligence persistent evidence store and backend API
status: done
owner: dreaminate
assigned_by: dreaminate
review_status: 1
priority: P1
area: research-os-document-intelligence
source: goal-gap
source_ref: dev/GOAL.md §6 + dev/research/TRACE.md §6 + dev/state/dreaminate/state.md Document Intelligence row
depends_on: [9c5e2a6de5144515aefdeea85bbcc39d, 3f1dd2ded6564acaa3e788ff2e5c8ed0]
---

# Document Intelligence persistent evidence store and backend API

## Scope [必填]
Turn the GOAL §6 Document Intelligence contract from pure validators into a
durable evidence store and backend API. The store must persist
`SourceDocumentIntakeRecord`, `EvidenceSpanRecord`, `ExtractedResearchClaim`,
and `PrivilegedToolUseRequest` records through JSONL replay. Writes must reuse
the existing validators and fail closed on unsafe source intake, missing span
anchors, confirmatory claims over unverified spans, and direct document payload
use by privileged tools.

This is not a full PDF/web parser, UI, vector index, or automatic RAG ingestion.
It creates the persistent evidence plane those later paths must use.

## 接线点（file:line，实现时复核）[必填]
| 文件 | 改什么 |
|---|---|
| `app/backend/app/research_os/document_intelligence.py` | Add JSONL-backed `PersistentDocumentIntelligenceStore` |
| `app/backend/app/main.py` | Add app-level document intelligence store and `/api/research-os/documents/*` endpoints |
| `app/backend/tests/test_document_intelligence_store.py` | Prove persistence, validation, fail-closed history, and HTTP write guards |

## 对抗测试设计（种已知 bug，门必抓）[必填]
1. Safe source intake + verified EvidenceSpan + confirmatory claim persists
   across store restart.
2. Source intake with network parser or missing sandbox/hash/rights returns 422
   and does not write to the JSONL file.
3. Confirmatory extracted claim referencing an unverified span is rejected.
4. Direct document payload use in a privileged tool request is rejected.
5. Malformed persisted history fails closed at startup.

## 验收一句话 [必填]
Document Intelligence has a durable schema-constrained evidence store and API
with the same safety gates as the contract validators; full parser/UI/RAG
ingestion remains explicitly separate.

## 完成记录
- Runtime: `PersistentDocumentIntelligenceStore` now appends/replays safe `SourceDocumentIntakeRecord`, `EvidenceSpanRecord`, `ExtractedResearchClaim`, and `PrivilegedToolUseRequest` events through JSONL, validates each write through the existing contract gates, requires non-empty record refs, and fails closed on malformed persisted rows.
- API: `app/backend/app/main.py` now owns `DOCUMENT_INTELLIGENCE_STORE` at `DATA_ROOT/audit/document_intelligence.jsonl` and exposes `/api/research-os/documents/sources`, `/evidence_spans`, `/extracted_claims`, `/tool_requests`, and `/summary`.
- Tests: added `app/backend/tests/test_document_intelligence_store.py` for restart replay, HTTP write path, unsafe source rejection, unverified confirmatory claim rejection, direct document payload rejection, empty ref rejection, and malformed history rejection.
- Validation: `python -m pytest tests/test_document_intelligence_contract.py tests/test_document_intelligence_store.py -q` -> `13 passed, 2 warnings`.
- Validation: Research OS scoped group -> `51 passed, 2 warnings`.
- Validation: full backend `python -m pytest -q` -> `1443 passed, 13 skipped, 278 warnings`.
- Boundary: this does not implement the PDF/web parser pipeline, frontend document search UI, vector search, or automatic Research Asset RAG ingestion.
