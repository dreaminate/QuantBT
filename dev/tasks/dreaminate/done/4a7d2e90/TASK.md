---
uuid: 4a7d2e90a419429799a93c35b57e3908
title: Execution reconciliation worker QRO API
status: done
owner: dreaminate
assigned_by: dreaminate
review_status: 1
priority: P1
area: research-os-execution-boundary
source: goal-gap
source_ref: GOAL §12 HALT/reconcile execution evidence closure
depends_on: [3b6e9c12a419429799a93c35b57e3908]
completed_at: 2026-06-27
---

# Execution reconciliation worker QRO API

## Scope [必填]
新增 execution reconciliation worker/API：读取已记录的 venue event refs，生成 append-only reconciliation record，并写入 ExecutionPolicy QRO。它只对账已记录事件，不调用 venue、不发单、不移动资金。

## 上下文 / 动机 [按需]
`3b6e9c12` 已把 submitted/accepted/rejected/fill/cancel/reconciled 事件以 refs/hash 进入 audit/QRO，但 §12 仍缺把这些事件汇总成 reconciliation 状态的 worker。GOAL 明确要求 HALT / 截断进入对账流程，不能把 fill 后缺 reconcile 说成干净完成。

## 接线点（file:line，实现时复核）[必填]
| 文件 | 改什么 |
|---|---|
| `app/backend/app/research_os/execution_boundary.py` | 新增 `ExecutionReconciliationRecord`、`PersistentExecutionReconciliationRegistry`、`reconcile_execution_venue_events`、`validate_execution_reconciliation` |
| `app/backend/app/research_os/__init__.py` | 导出 reconciliation runtime objects |
| `app/backend/app/main.py` | 新增 app-level `EXECUTION_RECONCILIATIONS` JSONL registry、`/api/research-os/execution/reconciliations` record/summary API、reconciliation ExecutionPolicy QRO write-through |
| `app/backend/tests/test_execution_boundary_contract.py` | 覆盖 reconciled 闭合、missing reconcile 记 action_required、unknown order intent 不写 partial |

## 对抗测试设计（种已知 bug，门必抓）[必填]
1. filled + reconciled events 必须产 `status=reconciled` 且 `action_required=false`。
2. filled 但没有 reconciled event 必须产 `status=needs_reconcile` 且 `action_required=true`，不能假绿。
3. unknown order intent / runtime promotion 必须 422，且不写 JSONL/Graph。
4. API 和 QRO 必须标明 `api_place_order_called=false`、`api_venue_call_called=false`。

## 红线 [按需]
- 不调用 venue、不请求交易所、不移动资金。
- 不新增 `place_order` 调用点。
- 不保存 raw order、raw fill、filled_qty、fill_price、commission 或明文 secret。
- 不把 reconciliation worker 说成真实 connector 已接通。

## 非目标 [按需]
不实现真实 order emission，不接 Binance testnet/live key，不实现后台调度循环，不改变 copy-trade relay 路径。

## 验收一句话 [必填]
Execution venue events 现在能被 refs-only worker 汇总成 reconciliation 状态并写 QRO；缺 reconcile 的 fill 会被记录成待处理，不会假装闭合。

## 完成记录（2026-06-27）
- `ExecutionReconciliationRecord` / `PersistentExecutionReconciliationRegistry` 已落 runtime。
- `/api/research-os/execution/reconciliations` 成功路径读取既有 venue events，写 JSONL registry + ExecutionPolicy QRO/ResearchGraph command。
- `/api/research-os/execution/reconciliations/summary` 只返回 refs/status/action_required，不返回 raw venue/order material。
- 本地验证：
  - `python -m pytest app/backend/tests/test_execution_boundary_contract.py -q` -> 22 passed / 2 warnings。
  - `python -m pytest app/backend/tests/test_execution_boundary_contract.py app/backend/tests/test_portfolio_promote_api.py app/backend/tests/test_factor_strategy_boundary.py app/backend/tests/test_realmoney_audit_killswitch.py app/backend/tests/test_entrypoint_gate_coverage.py app/backend/tests/test_engineering_standards.py -q` -> 69 passed / 2 warnings。
  - `python -m pytest app/backend/tests/test_execution_boundary_contract.py app/backend/tests/test_portfolio_promote_api.py app/backend/tests/test_factor_strategy_boundary.py app/backend/tests/test_factor_lab_endpoints.py app/backend/tests/test_model_governance.py app/backend/tests/test_research_os_spine.py app/backend/tests/test_entrypoint_gate_coverage.py app/backend/tests/test_goal_coverage.py app/backend/tests/test_platform_coverage.py app/backend/tests/test_engineering_standards.py app/backend/tests/test_realmoney_audit_killswitch.py -q` -> 136 passed / 2 warnings。
  - `python -m compileall app/backend/app` -> PASS。
  - `python dev/scripts/validate_dev.py` -> 49 ✅ / 0 ❌ / 0 ⚠️（DAG 161）。
