---
uuid: 7f4823d4cbce402a9bce1ebc62d64c8c
title: M1-M21 platform coverage real manifest registry
status: done
owner: dreaminate
assigned_by: dreaminate
review_status: 1
priority: P1
area: platform-coverage
source: goal
source_ref: GOAL §14 M1-M21 platform coverage; finding goal-0-17-gap-matrix-2026-06-28
depends_on: [2b1706f19b714040b93e37b23f82dcf8]
created_at: 2026-06-28
---

# M1-M21 platform coverage real manifest registry

## Scope [必填]
把 M1-M21 platform coverage 从 synthetic validator 扩成真实 refs manifest registry/API：每行必须有 QRO、Research Graph、lifecycle、governance、RAG、Mathematical Spine 和专项 refs；不把测试构造数据当完成证明。

## 接线点（file:line，实现时复核）[必填]
| 文件 | 改什么 |
|---|---|
| `app/backend/app/research_os/platform_coverage.py` | 新增 persistent registry/materializer 或 real manifest loader |
| `app/backend/app/main.py` | 新增 platform coverage summary/API |
| `app/backend/tests/test_platform_coverage.py` | 增加真实 manifest 持久化、缺 row/ref fail-closed 测试 |

## 对抗测试设计（种已知 bug，门必抓）[必填]
1. M14 缺 `llm_gateway_ref` / `model_routing_policy_ref` / `credential_pool_ref` / `theory_implementation_binding_ref` → 拒。
2. M21 缺 mock_label 或 asset_category → 拒。
3. 只传 synthetic refs 且没有对应 registry/audit backing → 不允许标 full platform coverage。

## 验收一句话 [必填]
M1-M21 真实 manifest 缺任一 common/specific ref 必红；只有可回查 refs 的 manifest 才能计入 §14 证据。

## 实现记录
- `app/backend/app/research_os/platform_coverage.py` 新增 `PersistentPlatformCoverageRegistry`、manifest JSONL replay、dict materializer、real-manifest validator。
- real-manifest validator 不再把旧 synthetic `_complete_manifest()` 当 §14 证据：`qro_ref`、`research_graph_ref`、`lifecycle_ref`、`governance_ref`、`rag_ref`、`math_spine_ref` 必须使用对应 registry/audit ref prefix；evidence/specific refs 拒绝 synthetic、fixture、test-only、`:001` 占位。
- specific refs 按 key 校验 registry/audit prefix：M14 的 LLM gateway / model routing policy / credential pool / theory binding，M21 的 mock label / asset category 都有独立坏门。
- `app/backend/app/main.py` 新增 `/api/research-os/platform/coverage_manifest` 与 `/api/research-os/platform/coverage_summary`，summary 按 `M1-M21` 顺序返回 present rows。
- payload 和 registry event 中的 `records` 必须是对象列表；非对象不再静默跳过。

## 验证
- `python -m compileall -q app/backend/app/research_os/platform_coverage.py app/backend/app/research_os/__init__.py app/backend/app/main.py app/backend/tests/test_platform_coverage.py` PASS。
- `python -m pytest app/backend/tests/test_platform_coverage.py -q` → **11 passed / 2 warnings**。
- `python -m pytest app/backend/tests/test_platform_coverage.py app/backend/tests/test_goal_coverage.py -q` → **28 passed / 2 warnings**。
- `python -m pytest app/backend/tests -q` → **1918 passed / 13 skipped / 283 warnings**。

## 边界
- 这是本地 append-only platform coverage manifest registry/API 与 fail-closed 测试；它拒绝 synthetic/placeholder refs，不是 CI、线上、真实 provider、生产 audit 数据已全量登记或用户验收。
