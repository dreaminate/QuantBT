---
uuid: 200435a6977e41eebd567673a2822c48
title: Document Intelligence scanned PDF OCR fallback
status: done
owner: dreaminate
assigned_by: dreaminate
review_status: 1
priority: P1
area: document-intelligence
source: goal-gap
source_ref: GOAL §6 OCR/scanned PDF extraction gap
depends_on: [229e195ddfb5487784c3f6c88f522d0f, b1514408ca2a49d1a3f53f13724921aa]
---

# Document Intelligence scanned PDF OCR fallback

## Scope [必填]
在本地 PDF parser 中增加 scanned PDF OCR fallback。普通 text PDF 仍优先走 PyMuPDF layout text blocks；只有 PDF 无可抽取文本时，才用 PyMuPDF 渲染页面到临时 PNG，并调用本机 `tesseract ... stdout` 产生 OCR text blocks。OCR blocks 进入同一套 EvidenceSpan + ResearchRAG metadata，仍不返回 raw text。

## 接线点（file:line，实现时复核）[必填]
| 文件 | 改什么 |
|---|---|
| `app/backend/app/research_os/document_intelligence.py` | 新增 `local_pdf_tesseract_ocr_no_network_v1` parser id、tesseract CLI wrapper、PDF no-text fallback |
| `app/backend/tests/test_document_intelligence_parser_rag.py` | 新增 image-only scanned PDF 测试，stub OCR 输出，断言 parser id/layout_kind/RAG/no raw text |

## 对抗测试设计（种已知 bug，门必抓）[必填]
1. Text PDF 继续走 `local_pdf_pymupdf_layout_no_network_v1`，不被 OCR fallback 抢路。
2. Image-only scanned PDF 在 PyMuPDF 无 text blocks 时走 `local_pdf_tesseract_ocr_no_network_v1`。
3. OCR block metadata 必须带 `layout_kind=pdf_ocr_page`，parse response 仍不得返回 raw `text`。
4. OCR span 必须能作为 ResearchRAG candidate context 检索。

## 验收一句话 [必填]
Document Intelligence 现在有本机 tesseract OCR fallback，可处理无文字层 scanned PDF；OCR 质量不保证，仍需后续人工/验证层判断。

## 完成记录（2026-06-27）
- 新增 `local_pdf_tesseract_ocr_no_network_v1`；PDF text extraction 无结果时才进入 OCR fallback。
- OCR 通过 PyMuPDF 渲染临时 PNG，再调用本机 `tesseract stdout`；临时图片随 `TemporaryDirectory` 清理。
- 验证：
  - `cd app/backend && python -m pytest tests/test_document_intelligence_parser_rag.py -q` -> 18 passed / 7 warnings。
  - 本机 tesseract smoke 调用 `_run_tesseract_ocr` 成功返回文本，但把 `PDF` 识别成 `POF`，所以只证明管线可调用，不证明 OCR 质量。
  - `cd app/backend && python -m pytest tests/test_document_intelligence_contract.py tests/test_document_intelligence_store.py tests/test_document_intelligence_parser_rag.py tests/test_research_asset_rag.py tests/test_research_asset_rag_persistence.py -q` -> 42 passed / 7 warnings。
  - `python -m compileall -q app/backend/app/research_os/document_intelligence.py app/backend/app/main.py` -> success.
  - `cd app/backend && python -m pytest -q` -> 1524 passed / 13 skipped / 283 warnings。
- 边界：这不是 OCR 质量保证、表格/版面理解、联网 OCR 服务、完整 graph database、真实资产库自动扫描/全库同步或 dense embedding/vector DB。
