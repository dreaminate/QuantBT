---
uuid: b1514408ca2a49d1a3f53f13724921aa
title: Document Intelligence parser upload API and workbench UI
status: done
owner: dreaminate
assigned_by: dreaminate
review_status: 1
priority: P1
area: document-intelligence
source: goal-gap
source_ref: GOAL §6 parser upload UI gap
depends_on: [7a6fe037011e474baefb67c99eee26c9, 038d2c8b36aa480da154dcdc592bd8f3]
---

# Document Intelligence parser upload API and workbench UI

## Scope [必填]
给 Document Intelligence 增加受限 parser upload 入口和研究执行台上传表单。上传文件只允许 text/Markdown/PDF/HTML 后缀，先做 filename/size guard，再写入 `DATA_ROOT/document_uploads/` 隔离区，随后复用现有 no-network parser、license rights、HTML URL allowlist、RAG permission 和 plaintext secret guard。失败时不写 Document/RAG records，并清理本次隔离文件。

## 接线点（file:line，实现时复核）[必填]
| 文件 | 改什么 |
|---|---|
| `app/backend/app/main.py` | 新增 `/api/research-os/documents/parse_upload`，复用 `_parse_local_document_for_rag(..., root=DATA_ROOT)` |
| `app/backend/tests/test_document_intelligence_parser_rag.py` | 覆盖 upload success、缺 rights cleanup、secret cleanup、filename path separator reject |
| `app/frontend/src/lib/auth.ts` | FormData body 不自动写 JSON content-type |
| `app/frontend/src/lib/auth.test.ts` | 覆盖 multipart boundary 不被前端 header 破坏 |
| `app/frontend/src/pages/workshop/agent-workbench/ResearchRAGPanel.tsx` | 新增 Parser upload 表单 |
| `app/frontend/src/pages/workshop/agent-workbench/ResearchRAGPanel.test.tsx` | 覆盖缺 file 不请求后端、FormData upload 和 raw payload 不展示 |

## 对抗测试设计（种已知 bug，门必抓）[必填]
1. 成功上传 Markdown 后写 SourceDocument/EvidenceSpan，并按显式 asset/desk/tags 进入 Research Asset RAG。
2. `license_rights_ref` 为空白时返回 422，不写 Document/RAG，清理本次上传文件。
3. 上传内容含 plaintext secret 时返回 422，不写 Document/RAG，清理本次上传文件。
4. upload filename 带 path separator 时在写文件前拒绝。
5. 前端 FormData 上传不得被 `authFetch` 强制设置 `content-type: application/json`。
6. 前端 parser upload 结果只展示 parser/source metadata 和计数，不展示 raw document payload。

## 验收一句话 [必填]
研究执行台已有受限 parser upload 入口；它进入同一套 Document Intelligence + ResearchRAG guard，不是绕过本地 parser 的 raw payload 通道。

## 完成记录（2026-06-27）
- 新增 `POST /api/research-os/documents/parse_upload`，接受 multipart upload + form metadata，隔离写入 `DATA_ROOT/document_uploads/` 后复用既有 no-network parser/RAG guard。
- `ResearchRAGPanel` 增加 Parser upload 表单；`authFetch` 对 FormData 不再自动设置 JSON content-type。
- 验证：
  - `cd app/backend && python -m pytest tests/test_document_intelligence_parser_rag.py -q` -> 17 passed / 7 warnings。
  - `cd app/backend && python -m pytest tests/test_document_intelligence_contract.py tests/test_document_intelligence_store.py tests/test_document_intelligence_parser_rag.py tests/test_research_asset_rag.py tests/test_research_asset_rag_persistence.py -q` -> 41 passed / 7 warnings。
  - `python -m compileall -q app/backend/app/main.py app/backend/app/research_os/document_intelligence.py` -> success.
  - `cd app/frontend && npm test -- --run src/pages/workshop/agent-workbench/RDPExportPanel.test.tsx src/pages/workshop/agent-workbench/ResearchRAGPanel.test.tsx src/pages/workshop/agent-workbench/agentWorkbench.test.tsx src/lib/auth.test.ts` -> 4 files / 53 tests passed。
  - `cd app/frontend && npm test -- --run` -> 26 files / 281 tests passed。
  - `cd app/frontend && npm run build` -> tsc + vite build PASS（保留既有 chunk size warning）。
  - `cd app/backend && python -m pytest -q` -> 1523 passed / 13 skipped / 283 warnings。
- 边界：这不是 OCR/scanned PDF extraction，不是联网 crawler，不是真实资产库自动扫描/全库同步，不是 dense embedding/vector DB，也不展示 raw document payload。
