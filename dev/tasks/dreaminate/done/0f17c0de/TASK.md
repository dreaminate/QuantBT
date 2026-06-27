---
uuid: 0f17c0de7a81483fab30f736b6f8a91d
title: GOAL §0-§17 coverage manifest contract
status: done
owner: dreaminate
assigned_by: dreaminate
review_status: 1
priority: P1
area: research-os-goal-coverage
source: goal-loop
source_ref: dev/GOAL.md §0-§17
depends_on: []
---

# GOAL §0-§17 coverage manifest contract

## Scope [必填]
Add a runtime manifest validator that requires every GOAL section from §0 to §17
to declare contract, test, task, and evidence refs. The validator also prevents
reporting contract coverage as full product implementation unless every section
has explicit full-entrypoint wiring refs.

## 接线点（file:line，实现时复核）[必填]
| 文件 | 改什么 |
|---|---|
| `app/backend/app/research_os/goal_coverage.py` | Add GOAL §0-§17 coverage manifest validators |
| `app/backend/app/research_os/__init__.py` | Export GOAL coverage types |
| `app/backend/tests/test_goal_coverage.py` | Add adversarial tests for missing sections and overclaiming full wiring |

## 对抗测试设计（种已知 bug，门必抓）[必填]
1. Section coverage missing contract/test/task/evidence refs -> reject.
2. Coverage manifest missing any §0-§17 section -> reject.
3. Contract-only manifest reported as full product implementation -> reject.
4. Full implementation claim without entrypoint wiring refs -> reject.

## 完成记录
- Added `app/backend/app/research_os/goal_coverage.py`.
- Added `app/backend/tests/test_goal_coverage.py`.
- Exported GOAL coverage contract types from `app.research_os`.
- Scoped validation:
  - `cd app/backend && python -m pytest tests/test_goal_coverage.py -v` -> 5 passed.
  - `cd app/backend && python -m pytest tests/test_research_os_spine.py tests/test_research_os_rdp.py tests/test_research_asset_rag.py tests/test_model_governance.py tests/test_factor_strategy_boundary.py tests/test_onboarding_gateway.py tests/test_market_data_contract.py tests/test_execution_boundary_contract.py tests/test_trust_layer.py tests/test_desk_projection.py tests/test_asset_lifecycle.py tests/test_document_intelligence_contract.py tests/test_methodology_validation.py tests/test_agent_os_contract.py tests/test_platform_coverage.py tests/test_engineering_standards.py tests/test_goal_coverage.py -q` -> 116 passed.

## 验收一句话 [必填]
GOAL §0-§17 now has a tested coverage manifest gate. It proves contract/test/task
coverage and blocks overclaiming full product implementation without entrypoint
wiring refs.
