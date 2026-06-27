---
uuid: 29a283af9fa440d1b687de1aba8183b2
title: Agent workbench stream Research Asset RAG retrieval
status: done
owner: dreaminate
assigned_by: dreaminate
review_status: 1
priority: P1
area: research-os-agent-rag
source: goal-gap
source_ref: dev/GOAL.md §5/§6/§7 + dev/research/TRACE.md §5-§7 + dev/state/dreaminate/state.md Agent OS Visible Workflow row
depends_on: [d1b14723d44949b5870f3f3b922e5484, 6f5cad5c38ec43239a488be2285a5356, 5ac0a71ef35f49e7a7f63f55a9e2db14]
---

# Agent workbench stream Research Asset RAG retrieval

## Scope [必填]
Extend `/api/agent/workbench/stream` so authenticated SSE turns can use the same
permission-filtered Research Asset RAG context provider as `/api/agent/chat`.
This adds query-param wiring and structured SSE refs, not a frontend search UI,
dense vector DB, web/OCR parser, or multi-agent scheduler.

## 接线点（file:line，实现时复核）[必填]
| 文件 | 改什么 |
|---|---|
| `app/backend/app/main.py` | Add RAG query params to workbench stream and inject `_agent_shell_rag_context_provider` |
| `app/backend/tests/test_agent_business_tools_a4.py` | Prove workbench SSE emits RAG refs/usage for authorized context without changing default no-RAG stream behavior |
| `dev/state/dreaminate/state.md` / `dev/research/TRACE.md` | Update only after validation with explicit boundary |

## 对抗测试设计（种已知 bug，门必抓）[必填]
1. Workbench stream with authorized visible asset must emit a `say` frame carrying
   candidate-context refs and a `done` frame carrying `rag_usage_ids`.
2. The LLM prompt must receive only permission-filtered candidate context.
3. Existing workbench stream without visible assets must remain structured
   `user` then `done/error` and must not require RAG parameters.

## 复用 [按需]
Reuse the `d1b14723` AgentRuntime RAG context provider and Research Asset RAG
permission/usage ledger.

## 红线 [按需]
Do not infer visible assets. If the caller does not pass visible assets, do not
retrieve. RAG hits remain candidate context, never verdicts.

## 非目标 [按需]
No frontend UI, no document search page, no dense embedding provider, no
workbench tool semantics change.

## 验收一句话 [必填]
Workbench SSE can cite authorized RAG source/version/usage refs; unauthorized or
missing visible asset context still produces no RAG context and preserves the
existing structured stream contract.
