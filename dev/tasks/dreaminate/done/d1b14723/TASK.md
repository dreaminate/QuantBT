---
uuid: d1b14723d44949b5870f3f3b922e5484
title: Agent Shell automatic Research Asset RAG retrieval
status: done
owner: dreaminate
assigned_by: dreaminate
review_status: 1
priority: P1
area: research-os-agent-rag
source: goal-gap
source_ref: dev/GOAL.md §5/§6/§7 + dev/research/TRACE.md §5-§7 + dev/state/dreaminate/state.md Research Asset RAG row
depends_on: [3f1dd2ded6564acaa3e788ff2e5c8ed0, 6f5cad5c38ec43239a488be2285a5356, 5ac0a71ef35f49e7a7f63f55a9e2db14]
---

# Agent Shell automatic Research Asset RAG retrieval

## Scope [必填]
Wire `/api/agent/chat` into Research Asset RAG so an authenticated Agent Shell
turn can retrieve permission-filtered candidate context before LLM dispatch,
record Agent RAG usage, and attach source/version/usage refs to Research Graph
commands. This does not implement a frontend document search UI, dense embedding
provider, web/OCR parser, or multi-role orchestrator.

## 接线点（file:line，实现时复核）[必填]
| 文件 | 改什么 |
|---|---|
| `app/backend/app/agent/agent_runtime.py` | Add optional RAG context provider, user-visible citation step, and QRO evidence refs |
| `app/backend/app/main.py` | Build permission-filtered Research Asset RAG context for `/api/agent/chat` when current user and visible assets are present |
| `app/backend/tests/test_agent_runtime_research_graph.py` | Prove authorized Agent Shell auto retrieval records source/version usage and unauthorized desk does not inject context |

## 对抗测试设计（种已知 bug，门必抓）[必填]
1. Authorized Agent Shell turn over an indexed ResearchRAG document must inject
   candidate context into the LLM prompt, return source/version refs, record
   `agent_usage`, and attach RAG refs to Research Graph commands.
2. Unauthorized desk over the same visible asset and query must not inject RAG
   context into the LLM prompt and must not record usage.
3. QRO contracts must keep plaintext user input and retrieved snippets out of
   input/output contracts; only hashes and refs may be recorded.

## 复用 [按需]
Reuse `PersistentResearchAssetRAGIndex.retrieve/vector_search`, `RAGQueryContext`,
`AgentRAGUsage`, and `AgentRuntime` QRO/Research Graph command wiring.

## 红线 [按需]
RAG hit remains candidate context, not a verdict. Agent does not read secrets and
does not bypass user/desk/asset/tag permissions.

## 非目标 [按需]
No dense vector DB, no external embedding call, no frontend search UI, no
web/OCR/layout-aware parser, no multi-agent scheduler.

## 验收一句话 [必填]
Seed authorized and unauthorized RAG contexts through `/api/agent/chat`: the
authorized path must cite source/version/usage refs; the unauthorized path must
produce no injected context or usage record without breaking existing Agent
Shell/QRO tests.
