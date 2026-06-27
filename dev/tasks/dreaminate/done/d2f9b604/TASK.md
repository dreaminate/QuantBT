---
uuid: d2f9b60417964ea8bd6d302fcdcb68e8
title: GOAL §14 M1-M21 platform coverage contract
status: done
owner: dreaminate
assigned_by: dreaminate
review_status: 1
priority: P1
area: research-os-platform-coverage
source: goal-loop
source_ref: dev/GOAL.md §14 功能平台 M1-M21
depends_on: []
---

# GOAL §14 M1-M21 platform coverage contract

## Scope [必填]
Add a runtime coverage manifest validator for GOAL M1-M21 rows. Each row must
declare QRO, Research Graph, lifecycle, governance, RAG, Mathematical Spine, and
evidence refs, with row-specific refs for M3, M6, M7-M8, M9, M14, M15, M18, M20,
and M21.

## 接线点（file:line，实现时复核）[必填]
| 文件 | 改什么 |
|---|---|
| `app/backend/app/research_os/platform_coverage.py` | Add M1-M21 platform coverage manifest validators |
| `app/backend/app/research_os/__init__.py` | Export §14 platform coverage types |
| `app/backend/tests/test_platform_coverage.py` | Add adversarial tests for missing rows and specific refs |

## 对抗测试设计（种已知 bug，门必抓）[必填]
1. Capability row missing common QRO/Graph/lifecycle/governance/RAG/math/evidence refs -> reject.
2. Manifest missing any M row -> reject.
3. M14 missing Gateway/Routing/CredentialPool/Math binding -> reject.
4. M21 missing mock label and asset category -> reject.

## 完成记录
- Added `app/backend/app/research_os/platform_coverage.py`.
- Added `app/backend/tests/test_platform_coverage.py`.
- Exported platform coverage contract types from `app.research_os`.
- Scoped validation:
  - `cd app/backend && python -m pytest tests/test_platform_coverage.py tests/test_engineering_standards.py -v` -> 12 passed.

## 验收一句话 [必填]
GOAL §14 now has a tested M1-M21 coverage manifest contract. It is not yet a
live dashboard over every existing product module.
