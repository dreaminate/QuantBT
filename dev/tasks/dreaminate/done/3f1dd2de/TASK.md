---
uuid: 3f1dd2ded6564acaa3e788ff2e5c8ed0
title: Research Asset RAG persistent index and backend API
status: done
owner: dreaminate
assigned_by: dreaminate
review_status: 1
priority: P1
area: research-os-rag
source: goal-gap
source_ref: dev/GOAL.md §5 + dev/research/TRACE.md §5 + dev/state/dreaminate/state.md Research Asset RAG row
depends_on: [377298205a7a4abbb044aaf046d7c24d, 5bb5d9da2f75469580ebbc74edf456fd]
---

# Research Asset RAG persistent index and backend API

## Scope [必填]
Turn the GOAL §5 Research Asset RAG contract from a pure in-memory validator
into a durable JSONL-backed index with backend write/retrieve/agent-usage
surfaces. Preserve the existing invariants: user/desk/asset/tag permission
filtering, candidate-context hits only, SecretRef metadata allowed but plaintext
secret rejected, and user-waived methodology never shown as strong evidence.

This does not implement the frontend RAG UI, automatic Agent Shell retrieval,
Document parser/store, or a vector database. It gives those paths a real
persistent backend seam instead of another in-memory contract.

## 接线点（file:line，实现时复核）[必填]
| 文件 | 改什么 |
|---|---|
| `app/backend/app/research_os/asset_rag.py` | Add JSONL persistence for documents and agent usage |
| `app/backend/app/main.py` | Add app-level RAG index and `/api/research-os/rag/*` endpoints |
| `app/backend/tests/test_research_asset_rag_persistence.py` | Prove restart recovery, permission filtering, secret fail-closed, and agent usage records |

## 对抗测试设计（种已知 bug，门必抓）[必填]
1. Persist a SecretRef metadata document, reload the index, and retrieve only
   for an authorized user/desk/asset/tag context; unauthorized contexts must
   return no hit.
2. Try indexing plaintext credential material through the API and assert it is
   rejected without writing to the persistent file.
3. Agent-mode retrieval must write source/version usage records inspectable by
   the user.
4. Malformed persisted RAG history must fail closed at startup.

## 验收一句话 [必填]
Research Asset RAG has a durable backend index and query surface with the same
permission and secret-boundary rules as the contract tests; frontend/Agent
Shell automatic usage remains a separate wiring gap.

## 完成记录
- Added `PersistentResearchAssetRAGIndex`, a JSONL-backed Research Asset RAG
  event log for indexed documents and Agent usage records. Startup replays
  persisted rows and malformed history fails closed.
- Added backend endpoints:
  - `POST /api/research-os/rag/documents`
  - `POST /api/research-os/rag/retrieve`
  - `GET /api/research-os/rag/agent_usage`
- The API defaults indexed documents to the current user, keeps user/desk/asset/tag
  filtering, rejects plaintext credential material, records Agent-mode source
  usage with `user_id`, and exposes usage only for the current user.
- Scoped validation:
  - `cd app/backend && python -m pytest tests/test_research_asset_rag.py tests/test_research_asset_rag_persistence.py -q` -> 10 passed / 2 warnings.
  - Research OS contract group -> 122 passed / 2 warnings.
  - `cd app/backend && python -m pytest -q` -> 1436 passed / 13 skipped / 278 warnings.

## 边界
This closes the persistent backend index/query seam for Research Asset RAG.
It does not implement frontend RAG UI, automatic Agent Shell retrieval,
Document parser/store, vector search, or source ingestion from every asset
registry.
