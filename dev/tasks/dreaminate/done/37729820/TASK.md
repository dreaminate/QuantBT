---
uuid: 377298205a7a4abbb044aaf046d7c24d
title: GOAL §5 Research Asset RAG runtime contract
status: done
owner: dreaminate
assigned_by: dreaminate
review_status: 1
priority: P0
area: research-os-rag
source: goal-gap
source_ref: 2026-06-26 /goal implement GOAL §5
depends_on: [1d16328c71914babb772fa899b753c07]
---

# GOAL §5 Research Asset RAG runtime contract

## 完成记录
- 新增 `app/backend/app/research_os/asset_rag.py`，提供 `AssetRAGDocument`、`RAGPermission`、`RAGQueryContext`、`ResearchAssetRAGIndex` 与 Agent usage ledger。
- 新增 `app/backend/tests/test_research_asset_rag.py`，覆盖权限过滤、source/version/timestamp/permission/applicability、SecretRef 明文阻断、user-waived overclaim、Agent hit usage 落账、projection filter。
- 验证：`cd app/backend && python -m pytest tests/test_research_asset_rag.py -v` → 6 passed；`cd app/backend && python -m pytest tests/test_research_os_spine.py tests/test_research_os_rdp.py tests/test_research_asset_rag.py -v` → 19 passed。

## Scope [必填]
建立 Research Asset RAG 的第一版运行时契约：同一底层 index 支持 DataRAG / FactorRAG / ModelRAG / SignalRAG / StrategyRAG / ResearchRAG / RunRAG / MathRAG / ConsistencyRAG 投影；retrieval 必须尊重 user/desk/asset/permission scope；每个 hit 必带 source_id / version / timestamp / permission / applicability；Agent 使用过的 hit 落账供 user 查；SecretRef 只允许状态/范围/last_test 元数据，明文 key/token/password 拒绝；user-waived 方法学不能显示成 evidence_sufficient / proof_backed。

## 接线点（file:line，实现时复核）[必填]
| 文件 | 位置 | 改什么 |
|---|---|---|
| app/backend/app/research_os/asset_rag.py | 新模块 | AssetRAGDocument / RAGPermission / RAGQueryContext / ResearchAssetRAGIndex / usage ledger |
| app/backend/tests/test_research_asset_rag.py | 新测试 | 权限过滤、source/version 元数据、SecretRef 明文阻断、waiver overclaim 阻断、agent usage 落账、projection |

## 对抗测试设计（种已知 bug，门必抓）[必填]
1. RAG 返回越权 user/desk/asset/tag 文档 → 测试红。
2. RAG 文档或 metadata 暴露 plaintext key/token/password → 拒。
3. Agent 使用 hit 后无 source/version 记录 → 拒。
4. user-waived methodology 被标成 evidence_sufficient/proof_backed → 拒。
5. desk projection 过滤不应分叉底层真相；MathRAG / RunRAG 从同一 index 过滤。

## 验收一句话 [必填]
GOAL §5 不再只是教学 RAG；资产级 RAG 有运行时权限、引用、SecretRef、waiver 和 usage 账门。
