---
uuid: f27c07fbe24a46648cf540aaed963d8f
title: Document Intelligence HTML/web snapshot parser-to-RAG ingestion
status: done
owner: dreaminate
assigned_by: dreaminate
review_status: 1
priority: P1
area: document-intelligence
source: goal-gap
source_ref: GOAL §6 Source intake · web parser gap
depends_on: [79b5e52607174c039fb6397c3828d1f0, 038d2c8b36aa480da154dcdc592bd8f3, 6f5cad5c38ec43239a488be2285a5356]
---

# Document Intelligence HTML/web snapshot parser-to-RAG ingestion

## Scope [必填]
在现有 `parse_local_document` 路径内新增本地 HTML/web snapshot parser。用户提供本地 `.html/.htm` 文件、`source_url` 和 `allowed_url_hosts`；parser 不联网、不执行脚本，只抽取可见文本块，落 SourceDocument/EvidenceSpan，并可写入 Research Asset RAG candidate context。URL 必须命中 allowlist，URL 不得带 token/secret/password 等凭据。

## 接线点（file:line，实现时复核）[必填]
| 文件 | 位置 | 改什么 |
|---|---|---|
| app/backend/app/research_os/document_intelligence.py | local parser | 增 HTML snapshot parser、URL allowlist、script/style skip、source_url metadata |
| app/backend/app/main.py | `/api/research-os/documents/parse_local` | 透传 `source_url` / `allowed_url_hosts`，response 返回 source_url |
| app/backend/tests/test_document_intelligence_parser_rag.py | parser tests | 覆盖 success、host 不在 allowlist、tokenized URL fail-closed |

## 对抗测试设计（种已知 bug，门必抓）[必填]
1. `.html` + allowlisted `https://example.com/...` → parser no-network，script/style 内容不进 RAG，visible body 文本可检索。
2. `.html` host 不在 `allowed_url_hosts` → 422，Document store 和 RAG index 不写 partial。
3. `source_url` query/path 带 `token`/`api_key`/`password` 等凭据 → 422，防 source URL 凭据进 metadata/RAG。

## 验收一句话 [必填]
本地 HTML/web snapshot 可按 URL allowlist 安全解析进 EvidenceSpan + RAG；不联网、不执行脚本、不泄露 URL 凭据；失败无 partial persistence。
