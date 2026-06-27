---
uuid: 199d3c002cc74b0a8866f0e5f803c556
title: legacy Mode2 chat thread 自动接入 Research Asset RAG
status: done
owner: dreaminate
assigned_by: dreaminate
review_status: 1
priority: P1
area: agent-rag
source: goal-gap
source_ref: GOAL §5/§6/§7 · state/TRACE legacy chat RAG gap
depends_on: [6f5cad5c38ec43239a488be2285a5356, d1b14723d44949b5870f3f3b922e5484, 29a283af9fa440d1b687de1aba8183b2]
---

# legacy Mode2 chat thread 自动接入 Research Asset RAG

## Scope [必填]
把旧 Mode2 chat thread 入口接入已有 Research Asset RAG：`POST /api/agent/chat/{thread_id}/message` 和 `GET /api/agent/chat/{thread_id}/stream` 在 caller 显式提供 `visible_asset_refs` 时，按 current user / desk / asset / permission tag 检索 RAG candidate context，写 `AgentRAGUsage`，并把命中/usage 作为 metadata 或 SSE event 返回。旧 glossary RAG 保留，不替换。

## 接线点（file:line，实现时复核）[必填]
| 文件 | 位置 | 改什么 |
|---|---|---|
| app/backend/app/main.py | legacy chat send/stream | 复用 `_agent_shell_rag_context_provider`，显式 visible assets 才检索；non-stream 走 AgentRuntime RAG refs；stream 注入 Mode2 prompt 并发 `research_rag` event |
| app/backend/tests/test_chat_conversations.py | legacy chat API tests | 覆盖 non-stream/stream 命中、usage、metadata、旧 glossary RAG 保留、无 visible assets 不自动检索 |

## 对抗测试设计（种已知 bug，门必抓）[必填]
1. 显式 `visible_asset_refs` + 权限匹配 → legacy non-stream 命中 Research Asset RAG，metadata 有 `research_asset_rag_hits` / `research_asset_rag_usage_ids`，Research Graph command evidence refs 有 `rag:<source>@<version>:<asset>` 和 `rag_usage:<id>`。
2. 未传 `visible_asset_refs` → 不自动检索，不写 usage，不把 candidate context 注入 prompt。
3. legacy stream 命中 → SSE 发 `event: research_rag`，assistant metadata 保留命中/usage；旧 `event: rag` glossary 预告仍存在。

## 验收一句话 [必填]
legacy Mode2 chat thread 的 non-stream 和 stream 两条入口都能在显式资产上下文下检索 Research Asset RAG，并保留权限过滤、usage 记录、旧 glossary RAG 和无 visible assets 不检索的边界。
