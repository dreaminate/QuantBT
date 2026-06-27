---
uuid: 229e195ddfb5487784c3f6c88f522d0f
title: Document Intelligence layout-aware PDF text parser metadata
status: done
owner: dreaminate
assigned_by: dreaminate
review_status: 1
priority: P1
area: document-intelligence
source: goal-gap
source_ref: GOAL §6 PDF layout-aware parser gap
depends_on: [038d2c8b36aa480da154dcdc592bd8f3]
---

# Document Intelligence layout-aware PDF text parser metadata

## Scope [必填]
把本地 PDF parser 从纯 page text extraction 升级为 PyMuPDF layout-aware text block extraction。PDF 仍走 no-network local parser，保留 magic check、encrypted reject、page limit、path/secret/rights guard；每个 EvidenceSpan block 增 `layout_bbox`、`layout_block_index`、`layout_kind`，RAG metadata 和 API block metadata 暴露这些定位信息，但不返回 raw text。

## 接线点（file:line，实现时复核）[必填]
| 文件 | 改什么 |
|---|---|
| `app/backend/app/research_os/document_intelligence.py` | 新增 PyMuPDF layout block parser；pypdf 仅作库缺失回退；block/span support hash 纳入 layout metadata |
| `app/backend/app/main.py` | RAG metadata 与 parse_local response block metadata 暴露 layout refs |
| `app/backend/tests/test_document_intelligence_parser_rag.py` | PDF parser 测试断言 layout parser id、bbox、block index、no raw text |

## 对抗测试设计（种已知 bug，门必抓）[必填]
1. PDF parse response 的 `blocks[]` 必须包含 `layout_bbox`、`layout_block_index`、`layout_kind=pdf_text_block`，但不得包含 raw `text`。
2. Document store source 的 `parser_sandbox_ref` 必须是 `parser_sandbox:local_pdf_pymupdf_layout_no_network_v1`。
3. 已有 fake PDF、encrypted/non-text、path escape、secret-bearing RAG body 和 batch atomic guard 继续由现有 parser tests 覆盖。

## 验收一句话 [必填]
本地 PDF source 现在能以 PyMuPDF layout-aware text blocks 进入 EvidenceSpan + ResearchRAG metadata；这仍不是 OCR。

## 完成记录（2026-06-27）
- 新增 parser id `local_pdf_pymupdf_layout_no_network_v1` 和 fallback id `local_pdf_pypdf_text_no_network_v1`。
- `LocalDocumentBlock` 增 layout metadata；span support verification hash、RAG metadata 和 API block metadata 均包含 layout refs。
- 验证：
  - `cd app/backend && python -m pytest tests/test_document_intelligence_parser_rag.py -q` -> 13 passed / 7 warnings。
  - `cd app/backend && python -m pytest tests/test_document_intelligence_contract.py tests/test_document_intelligence_store.py tests/test_document_intelligence_parser_rag.py tests/test_research_asset_rag.py tests/test_research_asset_rag_persistence.py -q` -> 37 passed / 7 warnings。
  - `cd app/backend && python -m pytest -q` -> 1519 passed / 13 skipped / 283 warnings.
- 边界：这不是 OCR/scanned PDF extraction，不是 external PDF service，不是 parser upload UI，也不是真实资产库自动同步。
