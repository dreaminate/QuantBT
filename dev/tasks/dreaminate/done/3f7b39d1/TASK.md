---
uuid: 3f7b39d1e4c841f69850eb4cd50c2fda
title: Document Intelligence explicit batch parser-to-RAG ingestion
status: done
owner: dreaminate
assigned_by: dreaminate
review_status: 1
priority: P1
area: document-intelligence
source: goal-gap
source_ref: GOAL §5/§6 · 全资产批量 ingestion gap
depends_on: [79b5e52607174c039fb6397c3828d1f0, 038d2c8b36aa480da154dcdc592bd8f3, f27c07fbe24a46648cf540aaed963d8f, 6f5cad5c38ec43239a488be2285a5356]
---

# Document Intelligence explicit batch parser-to-RAG ingestion

## Scope [必填]
新增显式 item list 的批量 document parser-to-RAG ingestion。入口接受 `items[]`，每个 item 复用单文档 parser 的 text/Markdown/PDF/HTML snapshot 安全门、rights、URL allowlist 和 RAG permission。批量必须 atomic：任何 item 失败时，Document store 与 RAG index 都不写 partial。

## 接线点（file:line，实现时复核）[必填]
| 文件 | 位置 | 改什么 |
|---|---|---|
| app/backend/app/main.py | Document Intelligence API | 新增 `POST /api/research-os/documents/parse_local_batch`，复用单文档 parser/RAG builder，先全量 prepare 后写入 |
| app/backend/tests/test_document_intelligence_parser_rag.py | parser tests | 覆盖 mixed markdown+HTML success、失败 item atomic no partial、duplicate source path rejected |

## 对抗测试设计（种已知 bug，门必抓）[必填]
1. markdown + HTML snapshot 批量成功 → 两个 SourceDocument、多组 EvidenceSpan、多条 RAG docs 一次返回。
2. 第二个 item 含 secret-bearing body → endpoint 422，第一项也不能写入 Document store/RAG index。
3. 同批重复 `source_path` + `source_url` → 422，防重复 ingestion 在一次 batch 内造成假双计。

## 验收一句话 [必填]
显式批量 ingestion 可安全解析多文档进 EvidenceSpan + RAG，并保证失败无 partial persistence、重复输入不双计。
