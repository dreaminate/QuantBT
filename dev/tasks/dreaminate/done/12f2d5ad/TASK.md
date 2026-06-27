---
uuid: 12f2d5adfb3b49e9aad30627e95a5494
title: GOAL §9 factor/model/signal/strategy boundary contract
status: done
owner: dreaminate
assigned_by: dreaminate
review_status: 1
priority: P1
area: research-os-factor-strategy-boundary
source: goal-loop
source_ref: dev/GOAL.md §9 因子、模型、信号、策略边界
depends_on: []
---

# GOAL §9 factor/model/signal/strategy boundary contract

## Scope [必填]
Add a runtime boundary validator for GOAL §9 without replacing existing
`factor_factory` mechanics. The validator must cover the explicit §9 bad gates:
gate metrics in generator fitness, model bodies inside the factor library,
short intent used as executable short without venue/borrow/margin checks,
retired factors adopted by default, and strategy math refs missing run_config
bindings.

## 接线点（file:line，实现时复核）[必填]
| 文件 | 改什么 |
|---|---|
| `app/backend/app/research_os/factor_strategy_boundary.py` | Add generator, factor, signal, StrategyBook, short-leg, and math-binding validators |
| `app/backend/app/research_os/__init__.py` | Export §9 boundary types |
| `app/backend/tests/test_factor_strategy_boundary.py` | Add adversarial tests for the §9 rejection gates |

## 对抗测试设计（种已知 bug，门必抓）[必填]
1. Gate metrics entering generator fitness -> reject.
2. ML/DL model body registered as factor-library entry -> reject.
3. StrategyBook short intent missing venue/borrow/margin/regulation/permission checks -> reject.
4. Retired factor adopted by default by a new strategy -> reject.
5. StrategyBook math refs missing theory/run_config binding -> reject.
6. ML/DL signal usage missing OOF/purge/embargo/train-test lock/honest-N -> reject.

## 完成记录
- Added `app/backend/app/research_os/factor_strategy_boundary.py`.
- Added `app/backend/tests/test_factor_strategy_boundary.py`.
- Exported §9 boundary types from `app.research_os`.
- Scoped validation:
  - `cd app/backend && python -m pytest tests/test_factor_strategy_boundary.py -v` -> 7 passed.
  - `cd app/backend && python -m pytest tests/test_factor_lab_endpoints.py tests/test_factor_strategy_boundary.py -v` -> 22 passed.

## 验收一句话 [必填]
GOAL §9 now has a tested boundary validator for factor/model/signal/StrategyBook
contracts. It is not yet wired into every production factor/model/strategy
endpoint.
