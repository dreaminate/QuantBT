---
uuid: 5f8d8f7ca9a64a7b9e31c29be7ed8de0
title: Research Asset RAG local dense vector index
status: done
owner: dreaminate
assigned_by: dreaminate
review_status: 1
priority: P1
area: research-asset-rag-dense-vector-index
source: goal-gap
source_ref: GOAL §5 Research Asset RAG dense embedding/vector DB gap
depends_on: [3f1dd2ded6564acaa3e788ff2e5c8ed0, 6f5cad5c38ec43239a488be2285a5356]
completed_at: 2026-06-27
---

# Research Asset RAG local dense vector index

## Scope [必填]
在现有 Research Asset RAG lexical / sparse token vector 检索外，新增本地 deterministic dense vector index。文档入库时写入 `dense_embedding_indexed` JSONL 事件；重启 replay 后可用同一 dense index 检索。查询 API 走同一 user/desk/asset/permission-tag 可见性过滤，Agent 查询仍记录 source/version usage。

## 上下文 / 动机 [按需]
TRACE §5 仍把 `dense embedding/vector DB` 标成待实现。当前 `/api/research-os/rag/vector_search` 实际是 token-count cosine sparse seam，不能把它说成 dense embedding/vector DB。先补一个可验证的本地 dense vector store，后续外部 embedding provider 或生产级 vector DB 再单独接入。

## 接线点（file:line，实现时复核）[必填]
| 文件 | 改什么 |
|---|---|
| `app/backend/app/research_os/asset_rag.py` | 新增 `AssetRAGDenseVector`、`local_hash_dense_v1` embedding、dense index、JSONL `dense_embedding_indexed` replay |
| `app/backend/app/main.py` | 新增 `/api/research-os/rag/dense_vector_search`；Agent Shell `rag_search=dense` 走 dense index |
| `app/backend/tests/test_research_asset_rag_persistence.py` | 覆盖 dense event persist/replay、权限过滤、排序、Agent usage |

## 对抗测试设计（种已知 bug，门必抓）[必填]
1. dense search 不绕过 allowed desk / visible asset / permission tags。
2. dense search 的 hit 仍是 `candidate_context`，不升级成 verdict。
3. Agent 模式 dense search 必须写 agent usage source/version 账本。
4. JSONL replay 后 dense index 仍可检索，不靠进程内临时状态。
5. plaintext secret 拒绝仍由文档入库 gate 把住，不进入 dense vector event。

## 红线 [按需]
- 不把 `local_hash_dense_v1` 说成语义 embedding 模型。
- 不把 JSONL local dense index 说成生产级向量数据库。
- 不把本地 pytest 说成 CI、线上或用户验收。

## 非目标 [按需]
不接外部 embedding provider、ANN/HNSW/FAISS、Postgres/pgvector、跨 registry/provider/scheduler 自动同步或生产 vector DB 运维。

## 验收一句话 [必填]
Research Asset RAG 现在有可 replay 的本地 dense vector index 和 API，权限、candidate-context 边界与 Agent usage 账本不变。

## 完成记录（2026-06-27）
- `AssetRAGDocument` 入库时生成 `AssetRAGDenseVector`，持久化 `dense_embedding_indexed` 事件；旧 document-only 历史仍可 replay 并补建内存 dense vector。
- `/api/research-os/rag/dense_vector_search` 返回 `embedding_model_ref=local_hash_dense_v1`、hits 和 agent usage ids；Agent Shell 支持 `rag_search=dense`。
- 本地验证：
  - `python -m pytest app/backend/tests/test_research_asset_rag.py app/backend/tests/test_research_asset_rag_persistence.py -q` -> 12 passed / 2 warnings。
  - `python -m pytest app/backend/tests/test_research_asset_rag.py app/backend/tests/test_research_asset_rag_persistence.py app/backend/tests/test_document_intelligence_parser_rag.py app/backend/tests/test_agent_runtime_research_graph.py app/backend/tests/test_agent_business_tools_a4.py app/backend/tests/test_chat_conversations.py -q` -> 99 passed / 7 warnings。
  - `python -m pytest app/backend/tests -q` -> 1832 passed / 13 skipped / 283 warnings。
  - `python -m compileall -q app/backend/app` -> PASS。
  - `python dev/scripts/validate_dev.py` -> PASS（49 ✅ / 0 ❌ / 0 ⚠️）。
  - `git diff --check` -> PASS。
