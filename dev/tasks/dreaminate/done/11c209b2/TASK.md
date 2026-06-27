---
uuid: 11c209b2f4d34b0aba1fb5dbe830e74b
title: GOAL §11 market data / InstrumentSpec / capability contract
status: done
owner: dreaminate
assigned_by: dreaminate
review_status: 1
priority: P1
area: research-os-market-data-contract
source: goal-loop
source_ref: dev/GOAL.md §11 数据层与标的接入
depends_on: []
---

# GOAL §11 market data / InstrumentSpec / capability contract

## Scope [必填]
Add a runtime contract for GOAL §11 market data and instrument semantics:
DatasetSemantics, InstrumentSpec, MarketCapabilityMatrix, cross-currency capital
records, and data-transformation math bindings.

## 接线点（file:line，实现时复核）[必填]
| 文件 | 改什么 |
|---|---|
| `app/backend/app/research_os/market_data_contract.py` | Add dataset, instrument, capability, cross-currency, and transformation validators |
| `app/backend/app/research_os/__init__.py` | Export §11 market-data types |
| `app/backend/tests/test_market_data_contract.py` | Add adversarial tests for §11 bad gates |

## 对抗测试设计（种已知 bug，门必抓）[必填]
1. Dataset without PIT semantics entering confirmatory validation -> reject.
2. Cross-currency strategy without base currency / FX conversion -> reject.
3. Option strategy missing expiry/strike/multiplier/settlement -> reject.
4. Live attempt without MarketCapabilityMatrix live permission -> reject; A-share live remains forbidden.
5. Data transformation claiming theory correctness without formula/unit/timing binding -> reject.

## 完成记录
- Added `app/backend/app/research_os/market_data_contract.py`.
- Added `app/backend/tests/test_market_data_contract.py`.
- Exported market-data contract types from `app.research_os`.
- Scoped validation:
  - `cd app/backend && python -m pytest tests/test_market_data_contract.py -v` -> 6 passed.
  - `cd app/backend && python -m pytest tests/test_data_contract.py tests/test_universe.py tests/test_paper_desk_api.py tests/test_market_data_contract.py -v` -> 61 passed.

## 验收一句话 [必填]
GOAL §11 now has a tested contract for PIT dataset semantics, InstrumentSpec,
MarketCapabilityMatrix, cross-currency capital records, option semantics, and
data-transformation math bindings. It is not yet wired into every dataset,
connector, strategy builder, or execution path.
