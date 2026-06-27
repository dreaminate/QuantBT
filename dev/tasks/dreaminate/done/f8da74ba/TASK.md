---
uuid: f8da74ba3e3e4e7698787c26a8608af6
title: GOAL §12 execution boundary contract
status: done
owner: dreaminate
assigned_by: dreaminate
review_status: 1
priority: P1
area: research-os-execution-boundary
source: goal-loop
source_ref: dev/GOAL.md §12 执行边界
depends_on: []
---

# GOAL §12 execution boundary contract

## Scope [必填]
Add a runtime contract for GOAL §12 execution boundary semantics: live ladder,
A-share live exclusion, OrderGuard/kill switch/SecretRef/idempotency/audit
invariants, HALT recovery, drift-triggered actions, execution math consistency,
and user risk responsibility records.

## 接线点（file:line，实现时复核）[必填]
| 文件 | 改什么 |
|---|---|
| `app/backend/app/research_os/execution_boundary.py` | Add RuntimePromotion, DriftTriggeredAction, HaltRecovery, ExecutionMathClaim, and UserRiskChoice validators |
| `app/backend/app/research_os/__init__.py` | Export §12 execution-boundary types |
| `app/backend/tests/test_execution_boundary_contract.py` | Add adversarial tests for §12 bad gates |

## 对抗测试设计（种已知 bug，门必抓）[必填]
1. Direct live without paper/testnet evidence -> reject.
2. A-share live remains unreachable -> reject.
3. Feature drift alone triggering trading/capital action -> reject.
4. User waiver or missing refs bypassing OrderGuard/kill switch/SecretRef/audit/idempotency -> reject.
5. HALT recovery auto-resending order or missing reconcile -> reject.
6. Execution cost/margin/kill-trigger math missing ConsistencyCheck -> reject.
7. User risk choice missing disclosures/responsibility boundary -> reject.

## 完成记录
- Added `app/backend/app/research_os/execution_boundary.py`.
- Added `app/backend/tests/test_execution_boundary_contract.py`.
- Exported execution-boundary contract types from `app.research_os`.
- Scoped validation:
  - `cd app/backend && python -m pytest tests/test_execution_boundary_contract.py -v` -> 8 passed.
  - `cd app/backend && python -m pytest tests/test_security_gate_adversarial.py tests/test_dag_kernel.py tests/test_paper_desk_api.py tests/test_execution_boundary_contract.py -v` -> 82 passed.

## 验收一句话 [必填]
GOAL §12 now has a tested execution-boundary contract for live ladder,
immutability of execution invariants, HALT/reconcile, drift-triggered actions,
execution math consistency, and user risk responsibility. It is not yet wired
into every runtime transition or execution endpoint.
