---
uuid: f3a6c8d1a4cd40f189c8e2d4c3671070
title: GOAL §16 engineering standards contract
status: done
owner: dreaminate
assigned_by: dreaminate
review_status: 1
priority: P1
area: research-os-engineering-standards
source: goal-loop
source_ref: dev/GOAL.md §16 工程标准
depends_on: []
---

# GOAL §16 engineering standards contract

## Scope [必填]
Add a runtime contract for no silent mock fallback, no template false success,
dataset version/checksum/lineage/time axes and five data tests, LLM replay and
Gateway refs, proof-backed TheoryImplementationBinding/ConsistencyCheck,
secret isolation, verifier independence record, fatal errors, and performance
baseline evidence.

## 接线点（file:line，实现时复核）[必填]
| 文件 | 改什么 |
|---|---|
| `app/backend/app/research_os/engineering_standards.py` | Add engineering standard validators |
| `app/backend/app/research_os/__init__.py` | Export §16 engineering standard types |
| `app/backend/tests/test_engineering_standards.py` | Add adversarial tests for fatal engineering redlines |

## 对抗测试设计（种已知 bug，门必抓）[必填]
1. Production profile succeeds through mock/template -> reject.
2. Data update missing dataset version/checksum/lineage/known_at/effective_at or five tests -> reject.
3. LLM call missing Gateway/provider/model/auth/cost/replay/hash refs -> reject.
4. Proof-backed implementation missing binding/consistency or using user waiver -> reject.
5. Secret plaintext, Gateway bypass, independence false claim, A-share live, production mock fallback, look-ahead leakage -> reject.
6. Performance baseline over threshold or missing evidence -> reject.

## 完成记录
- Added `app/backend/app/research_os/engineering_standards.py`.
- Added `app/backend/tests/test_engineering_standards.py`.
- Exported engineering standard contract types from `app.research_os`.
- Scoped validation:
  - `cd app/backend && python -m pytest tests/test_platform_coverage.py tests/test_engineering_standards.py -v` -> 12 passed.

## 验收一句话 [必填]
GOAL §16 now has a tested engineering-standards contract. It is not yet wired
into every CI, benchmark, provider call, and data-update path.
