---
uuid: 2f4c8e91b1db463db4dd19e1ce89e7d0
title: GOAL §13 trust layer contract
status: done
owner: dreaminate
assigned_by: dreaminate
review_status: 1
priority: P1
area: research-os-trust-layer
source: goal-loop
source_ref: dev/GOAL.md §13 信任层
depends_on: []
---

# GOAL §13 trust layer contract

## Scope [必填]
Add a runtime contract for trust-layer honesty: strong claims require evidence,
wishful pressure cannot become strong conclusion, weaknesses and user-waived
weaknesses stay visible, cold-start N=1 stays prior/unverified, functional
independence is disclosed honestly, Agent does not make the user's methodology
or risk choice, and release gates require trust-pressure/honesty checks.

## 接线点（file:line，实现时复核）[必填]
| 文件 | 改什么 |
|---|---|
| `app/backend/app/research_os/trust_layer.py` | Add trust claim, functional independence, user autonomy, and release gate validators |
| `app/backend/app/research_os/__init__.py` | Export §13 trust-layer types |
| `app/backend/tests/test_trust_layer.py` | Add adversarial tests for §13 trust boundaries |

## 对抗测试设计（种已知 bug，门必抓）[必填]
1. Strong claim without evidence -> reject.
2. User wishful pressure producing strong conclusion -> reject.
3. Weakness or user-waived weakness hidden by default -> reject.
4. Cold-start N=1 packaged as statistical evidence -> reject.
5. Single-user mode claiming organizational independence -> reject.
6. Agent makes user's final methodology/risk choice -> reject.
7. Release gate missing pressure/honesty checks -> reject.

## 完成记录
- Added `app/backend/app/research_os/trust_layer.py`.
- Added `app/backend/tests/test_trust_layer.py`.
- Exported trust-layer contract types from `app.research_os`.
- Scoped validation:
  - `cd app/backend && python -m pytest tests/test_trust_layer.py -v` -> 10 passed.
  - `cd app/backend && python -m pytest tests/test_research_os_spine.py tests/test_research_os_rdp.py tests/test_research_asset_rag.py tests/test_model_governance.py tests/test_factor_strategy_boundary.py tests/test_onboarding_gateway.py tests/test_market_data_contract.py tests/test_execution_boundary_contract.py tests/test_trust_layer.py -q` -> 65 passed.

## 验收一句话 [必填]
GOAL §13 now has a tested trust-layer contract. It is not yet wired into every
UI disclosure surface or release pipeline.
