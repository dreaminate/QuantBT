---
uuid: 4e7a2c10605f4c5da7121d78f87e40bb
title: GOAL §2 multi-desk projection contract
status: done
owner: dreaminate
assigned_by: dreaminate
review_status: 1
priority: P1
area: research-os-desk-projection
source: goal-loop
source_ref: dev/GOAL.md §2 多台工作系统
depends_on: []
---

# GOAL §2 multi-desk projection contract

## Scope [必填]
Add a runtime contract for shared-Research-Graph desk projections, per-desk
write scopes, Typed Canvas/RAG/Math/Inspector/permission refs, DeskHandoff
completion evidence, and canonical command/audit requirements for user and Agent
canvas mutations.

## 接线点（file:line，实现时复核）[必填]
| 文件 | 改什么 |
|---|---|
| `app/backend/app/research_os/desk_projection.py` | Add DeskProjection, DeskHandoff, CanvasMutation validators |
| `app/backend/app/research_os/__init__.py` | Export §2 desk projection types |
| `app/backend/tests/test_desk_projection.py` | Add adversarial tests for desk truth and write boundaries |

## 对抗测试设计（种已知 bug，门必抓）[必填]
1. Desk projection without shared Research Graph -> reject.
2. Desk maintaining independent truth state -> reject.
3. Strategy desk writes Factor formula -> reject.
4. Manual/Agent mutation without canonical command or audit -> reject.
5. Completed DeskHandoff without produced_ref/evidence -> reject.
6. Institutional method canvas without math/consistency projection -> reject.

## 完成记录
- Added `app/backend/app/research_os/desk_projection.py`.
- Added `app/backend/tests/test_desk_projection.py`.
- Exported desk projection contract types from `app.research_os`.
- Scoped validation:
  - `cd app/backend && python -m pytest tests/test_desk_projection.py tests/test_asset_lifecycle.py -v` -> 13 passed.

## 验收一句话 [必填]
GOAL §2 now has a tested multi-desk projection and handoff contract. It is not
yet enforced on every existing frontend canvas mutation or desk endpoint.
