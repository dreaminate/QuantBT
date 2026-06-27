---
uuid: c4f3ac027ff1433eb51852c6589ef236
title: Document Intelligence safe local directory sync API
status: done
owner: dreaminate
assigned_by: dreaminate
review_status: 1
priority: P1
area: document-intelligence
source: goal-gap
source_ref: GOAL §5/§6 Research Asset RAG asset-library ingestion gap
depends_on: [3f7b39d1e4c841f69850eb4cd50c2fda, b1514408ca2a49d1a3f53f13724921aa, 200435a6977e41eebd567673a2822c48]
---

# Document Intelligence safe local directory sync API

## Scope [必填]
新增显式本地目录同步 API，把安全目录下的 text/Markdown/RST/PDF 文件批量送入现有 no-network Document Intelligence parser，并可进入同一套 Research Asset RAG candidate-context index。同步必须要求显式 `asset_ref` / rights，禁止路径逃逸、隐藏/敏感路径、symlink、plaintext secret 和 partial writes。unsupported 文件只报告为 `skipped_paths`，不伪装已解析。

## 接线点（file:line，实现时复核）[必填]
| 文件 | 改什么 |
|---|---|
| `app/backend/app/main.py` | 新增 `POST /api/research-os/documents/sync_local_directory`、安全 base path resolver、目录扫描 guard、atomic prepare-then-write |
| `app/backend/tests/test_document_intelligence_parser_rag.py` | 覆盖支持文件批量写入、unsupported skip、secret fail-closed、hidden/sensitive fail-closed 和 RAG retrieval |

## 对抗测试设计（种已知 bug，门必抓）[必填]
1. 目录里有 `.md` / `.txt` / unsupported `.csv` 时，只解析支持文件，unsupported 文件必须出现在 `skipped_paths`。
2. 任一支持文件含 plaintext secret 时，endpoint 422，Document store 和 RAG index 都不得产生 partial JSONL。
3. 目录包含 hidden/sensitive 文件名时，endpoint 422，且不得 partial write。
4. 成功同步后的 document spans 必须能作为 ResearchRAG candidate context 被显式 `visible_asset_refs` 检索。

## 验收一句话 [必填]
Document Intelligence 现在可以把显式安全本地目录批量同步进 SourceDocument/EvidenceSpan/RAG；这不是跨 registry/provider/scheduler 的真实资产库全域自动同步。

## 完成记录（2026-06-27）
- 新增 `POST /api/research-os/documents/sync_local_directory`，支持 `root=project|data`、显式 `base_path`、`asset_ref`、rights、desk、permission tags、projection、max bytes/pages/files。
- 目录扫描只接受 `.md` / `.markdown` / `.txt` / `.rst` / `.pdf`；跳过 unsupported 文件并返回相对路径；拒绝隐藏/敏感路径、symlink、路径逃逸和空目录。
- endpoint 先对所有支持文件 prepare parser/RAG documents，再写 Document store 与 RAG index；任一文件失败时不产生 partial Document/RAG records。
- 验证：
  - `cd app/backend && python -m pytest tests/test_document_intelligence_parser_rag.py -q` -> 21 passed / 7 warnings。
  - `cd app/backend && python -m pytest tests/test_document_intelligence_contract.py tests/test_document_intelligence_store.py tests/test_document_intelligence_parser_rag.py tests/test_research_asset_rag.py tests/test_research_asset_rag_persistence.py -q` -> 45 passed / 7 warnings。
  - `python -m compileall -q app/backend/app/main.py app/backend/app/research_os/document_intelligence.py` -> success.
  - `cd app/backend && python -m pytest -q` -> 1527 passed / 13 skipped / 283 warnings。
- 边界：这不是 HTML crawler、跨 registry/provider/scheduler 的真实资产库全域自动同步、dense embedding/vector DB、完整 graph database 或表格/版面理解。
