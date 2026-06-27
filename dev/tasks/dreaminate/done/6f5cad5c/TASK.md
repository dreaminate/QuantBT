---
uuid: 6f5cad5c38ec43239a488be2285a5356
title: Research Asset RAG sparse vector search backend
status: done
owner: dreaminate
assigned_by: dreaminate
review_status: 1
priority: P1
area: research-os-rag
source: goal-gap
source_ref: dev/GOAL.md §5 + dev/research/TRACE.md §5 + dev/state/dreaminate/state.md Research Asset RAG row
depends_on: [3f1dd2ded6564acaa3e788ff2e5c8ed0, 79b5e52607174c039fb6397c3828d1f0]
---

# Research Asset RAG sparse vector search backend

## Scope [必填]
Add the first backend vector-search seam for Research Asset RAG: a deterministic
sparse token-vector cosine search over indexed RAG documents. It must reuse the
existing document index, permission filters, projection filters, hit shape, and
Agent usage ledger. It must not call external embedding providers, leak
plaintext secrets, or turn retrieval hits into system conclusions.

This is not a dense embedding model, vector database, frontend search UI, or
Agent Shell automatic retrieval. Those remain separate gaps.

## 接线点（file:line，实现时复核）[必填]
| 文件 | 改什么 |
|---|---|
| `app/backend/app/research_os/asset_rag.py` | Add permission-filtered sparse vector cosine search over existing documents |
| `app/backend/app/main.py` | Add `/api/research-os/rag/vector_search` with Agent usage recording |
| `app/backend/tests/test_research_asset_rag_persistence.py` | Add API tests for ranking, permissions, and Agent usage |

## 对抗测试设计（种已知 bug，门必抓）[必填]
1. Two authorized documents with overlapping terms: vector search ranks the
   better cosine match first and preserves `candidate_context`.
2. Unauthorized desk/asset context returns no hit.
3. Agent vector search records source/version usage visible to the current user.
4. Search reuses existing indexed document secret guard; no new body ingestion
   path bypasses RAG document validation.

## 验收一句话 [必填]
Research Asset RAG can perform permission-filtered sparse vector search over
persisted candidate-context documents, with Agent usage provenance, while dense
embeddings/vector DB/UI/automatic Agent retrieval remain explicit follow-ups.

## 完成记录
- Runtime: added `ResearchAssetRAGIndex.vector_search`, a deterministic sparse
  token-vector cosine search over existing indexed RAG documents. It reuses the
  same projection filter, `_visible()` permission gate, and `AssetRAGHit`
  candidate-context shape as lexical retrieval.
- API: added `POST /api/research-os/rag/vector_search`; Agent mode records
  source/version usage through the existing `AgentRAGUsage` ledger.
- Tests: extended `app/backend/tests/test_research_asset_rag_persistence.py`
  with ranking, unauthorized desk denial, candidate-context preservation, and
  Agent usage assertions.
- Validation: RAG scoped `11 passed, 2 warnings`; §5/§6 adjacent scoped
  `29 passed, 2 warnings`; Research OS scoped `189 passed, 2 warnings`;
  backend full `1505 passed, 13 skipped, 278 warnings`.
- Boundary: this is sparse vector search over existing text fields. It does not
  add dense embeddings, an external provider, a vector database, frontend search
  UI, or Agent Shell automatic retrieval.
