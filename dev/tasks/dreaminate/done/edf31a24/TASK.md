---
uuid: edf31a24216b4c87a13340f50b8cb4bb
title: Research Asset RAG frontend candidate-context search UI
status: done
owner: dreaminate
assigned_by: dreaminate
review_status: 1
priority: P1
area: research-asset-rag
source: goal-gap
source_ref: GOAL §5/§6 frontend RAG UI gap
depends_on: [3f1dd2ded6564acaa3e788ff2e5c8ed0, 6f5cad5c38ec43239a488be2285a5356]
---

# Research Asset RAG frontend candidate-context search UI

## Scope [必填]
把已验证的 Research Asset RAG backend query seam 接到研究执行台前端。新增工作区 `RAG` tab，用户必须显式输入 `query`、`desk`、`visible_asset_refs`、`permission_tags` 和 `top_k`；UI 可在 lexical 与 deterministic sparse-vector search 间切换，调用 `/api/research-os/rag/retrieve` 或 `/api/research-os/rag/vector_search`，展示 `source_id`、`version`、`asset_ref`、`projection`、`score`、`context_role`、`evidence_label`、`applicability` 和 snippet。命中只显示为 `candidate_context`，不升级为 verdict/proof。

## 接线点（file:line，实现时复核）[必填]
| 文件 | 改什么 |
|---|---|
| `app/frontend/src/pages/workshop/agent-workbench/ResearchRAGPanel.tsx` | 新增 Research Asset RAG 查询面板 |
| `app/frontend/src/pages/workshop/agent-workbench/AgentWorkbenchPage.tsx` | 工作区新增 `RAG` tab，并标记为 Backend |
| `app/frontend/src/pages/workshop/agent-workbench/agentMock.ts` | 扩展 `WorkspaceTab` 类型 |
| `app/frontend/src/pages/workshop/agent-workbench/ResearchRAGPanel.test.tsx` | 增前端对抗测试 |

## 对抗测试设计（种已知 bug，门必抓）[必填]
1. 缺 `visible_asset_refs` 时前端直接报错，不请求后端，防止隐式全库检索。
2. sparse-vector 模式请求 `/api/research-os/rag/vector_search`，body 必须包含显式 `visible_asset_refs`、`permission_tags`、`projections:["ResearchRAG"]`、`actor:"user"` 和 `top_k`。
3. lexical 模式请求 `/api/research-os/rag/retrieve`，`top_k` 本地 clamp 到 1–20。
4. 后端 422 显示错误，不伪造命中或成功状态。

## 验收一句话 [必填]
研究执行台已有真实后端 Research Asset RAG candidate-context 查询 UI；无显式资产不检索，命中不包装成证据充分或结论。

## 完成记录（2026-06-27）
- 新增 `ResearchRAGPanel`，挂入 agent-workbench 产物工作区 `RAG` tab。
- UI 默认 actor 为 `user`，不写 agent usage；只读检索显式资产范围内的 candidate context。
- 验证：
  - `cd app/frontend && npm test -- --run src/pages/workshop/agent-workbench/ResearchRAGPanel.test.tsx src/pages/workshop/agent-workbench/RDPExportPanel.test.tsx` -> 9 passed。
  - `cd app/frontend && npm test -- --run src/pages/workshop/agent-workbench/agentWorkbench.test.tsx` -> 40 passed。
  - `cd app/frontend && npm test -- --run` -> 25 files / 277 tests passed。
  - `cd app/frontend && npm run build` -> tsc + vite build PASS（保留既有 chunk size warning）。
- 边界：这不是 dense embedding/vector DB，不是 OCR/layout-aware PDF parser，不是 parser 上传 UI，也不是真实资产库自动扫描/全库同步。
