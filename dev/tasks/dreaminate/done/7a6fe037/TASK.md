---
uuid: 7a6fe037011e474baefb67c99eee26c9
title: Document Intelligence frontend source summary browser
status: done
owner: dreaminate
assigned_by: dreaminate
review_status: 1
priority: P1
area: document-intelligence
source: goal-gap
source_ref: GOAL §6 SourceDocument browsing gap
depends_on: [038d2c8b36aa480da154dcdc592bd8f3, edf31a24216b4c87a13340f50b8cb4bb]
---

# Document Intelligence frontend source summary browser

## Scope [必填]
把已验证的 `/api/research-os/documents/summary` 接到研究执行台 `RAG` tab。用户点击 `Load` 后只读加载 SourceDocument 摘要，展示 source/span/claim 计数、`source_ref`、`parser_sandbox_ref` 和 `mime_magic_check_ref`。不展示 raw document payload，不做 parser 上传，不做资产库扫描。

## 接线点（file:line，实现时复核）[必填]
| 文件 | 改什么 |
|---|---|
| `app/frontend/src/pages/workshop/agent-workbench/ResearchRAGPanel.tsx` | 新增 Document evidence 只读摘要区，调用 documents summary endpoint |
| `app/frontend/src/pages/workshop/agent-workbench/ResearchRAGPanel.test.tsx` | 覆盖 summary 加载、source metadata 展示和 raw payload 不展示 |
| `app/frontend/src/pages/workshop/agent-workbench/RDPExportPanel.test.tsx` | 修复 detail async race，等待 source map/run/download 控件渲染后再操作 |

## 对抗测试设计（种已知 bug，门必抓）[必填]
1. `Document evidence` 加载必须调用 `/api/research-os/documents/summary`，不得走 parser/upload 端点。
2. UI 只展示 source metadata 和计数，不展示 `raw_document`。
3. RDP export 测试不能只等 manifest summary 文案；必须等 detail controls ready 后再触发 materialize/download/attest。

## 验收一句话 [必填]
研究执行台现在能只读浏览 Document Intelligence SourceDocument 摘要；parser 上传 UI 仍未实现。

## 完成记录（2026-06-27）
- `ResearchRAGPanel` 增加 `Document evidence` 区块，点击 `Load` 后读取 documents summary，展示 sources/spans/claims 计数和 source metadata。
- 修正 `RDPExportPanel.test.tsx` 的异步等待点，避免全量并发下 detail 尚未加载就读取控件。
- 验证：
  - `cd app/frontend && npm test -- --run src/pages/workshop/agent-workbench/RDPExportPanel.test.tsx src/pages/workshop/agent-workbench/ResearchRAGPanel.test.tsx src/pages/workshop/agent-workbench/agentWorkbench.test.tsx` -> 3 files / 50 tests passed。
  - `cd app/frontend && npm test -- --run` -> 25 files / 278 tests passed。
  - `cd app/frontend && npm run build` -> tsc + vite build PASS（保留既有 chunk size warning）。
- 边界：这不是 parser upload UI，不展示 raw document，不是 OCR/scanned PDF extraction，不是真实资产库自动扫描/全库同步，也不是 dense embedding/vector DB。
