---
uuid: 6b1d3f20ea0640538260c102ac0f8d64
title: GOAL §3 asset lifecycle contract
status: done
owner: dreaminate
assigned_by: dreaminate
review_status: 1
priority: P1
area: research-os-asset-lifecycle
source: goal-loop
source_ref: dev/GOAL.md §3 生命周期与资产库
depends_on: []
---

# GOAL §3 asset lifecycle contract

## Scope [必填]
Add a runtime contract for governed asset category/lifecycle/evidence,
demo/template-to-production promotion history, IngestionSkill update DatasetVersion
and lineage, retired-asset default-use blocking, runtime lifecycle transition
promotion/approval/evidence, proof-backed ConsistencyCheck, and user methodology
responsibility boundaries.

## 接线点（file:line，实现时复核）[必填]
| 文件 | 改什么 |
|---|---|
| `app/backend/app/research_os/asset_lifecycle.py` | Add governed asset, ingestion update, retired use, and transition validators |
| `app/backend/app/research_os/__init__.py` | Export §3 lifecycle types |
| `app/backend/tests/test_asset_lifecycle.py` | Add adversarial tests for lifecycle and asset-library gates |

## 对抗测试设计（种已知 bug，门必抓）[必填]
1. Formal asset missing category/lifecycle/evidence -> reject.
2. Demo/template promoted to production without promotion history -> reject.
3. IngestionSkill update missing DatasetVersion/checksum/lineage -> reject.
4. Retired asset used by default in a new run -> reject.
5. Runtime transition missing promotion/approval/evidence -> reject.
6. Proof-backed or user-waived asset missing ConsistencyCheck/responsibility -> reject.

## 完成记录
- Added `app/backend/app/research_os/asset_lifecycle.py`.
- Added `app/backend/tests/test_asset_lifecycle.py`.
- Exported lifecycle contract types from `app.research_os`.
- Scoped validation:
  - `cd app/backend && python -m pytest tests/test_desk_projection.py tests/test_asset_lifecycle.py -v` -> 13 passed.

## 验收一句话 [必填]
GOAL §3 now has a tested governed lifecycle and asset-library contract. It is
not yet wired into every asset registry write path.
