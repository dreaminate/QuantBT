---
uuid: d4c9a2f0a419429799a93c35b57e3908
title: Execution reconciliation action producer API
status: done
owner: dreaminate
assigned_by: dreaminate
review_status: 1
priority: P1
area: research-os-execution-boundary
source: goal-gap
source_ref: GOAL §12 reconciliation monitor action producer
depends_on: [6e4a9b21a419429799a93c35b57e3908]
completed_at: 2026-06-27
---

# Execution reconciliation action producer API

## Scope [必填]
新增 execution reconciliation action producer API：扫描已记录 reconciliation records，把 `action_required=true` 的异常对账结果幂等转成默认 follow-up actions，并写入 ExecutionPolicy QRO。它是 API-triggered producer，不是部署级长期 scheduler。

## 上下文 / 动机 [按需]
`6e4a9b21` 已能手动记录 reconciliation follow-up action；§12 剩余缺口是 action producer 不能完全靠人逐条创建。本卡补第一版 pending producer，使 `needs_reconcile` 自动映射到 `request_missing_reconcile`，conflict/mismatch 映射到 `escalate_manual_review`，其他 open/missing 映射到 `investigate`。

## 接线点（file:line，实现时复核）[必填]
| 文件 | 改什么 |
|---|---|
| `app/backend/app/main.py` | 新增 `/api/research-os/execution/reconciliation_actions/run_pending`，扫描 action_required reconciliations，幂等生成 action records + QRO |
| `app/backend/tests/test_execution_boundary_contract.py` | 覆盖 action producer 首次创建和重复调用 skip |

## 对抗测试设计（种已知 bug，门必抓）[必填]
1. `needs_reconcile` pending reconciliation 必须生成 `request_missing_reconcile` action。
2. 重复运行 producer 必须 skip 已有 open/acknowledged action，不能重复写 QRO。
3. producer 响应必须标明 `record_only=true`、`api_place_order_called=false`、`api_venue_call_called=false`。
4. QRO 不得包含 raw order/fill/venue payload。

## 红线 [按需]
- 不调用交易所、不新增 broker connector、不移动资金。
- 不新增裸 `place_order`。
- 不保存 raw order、raw venue payload、filled_qty、fill_price、commission 或明文 secret。
- 不把 API-triggered producer 说成部署级长期 scheduler、自动 remediation、venue API 连通或真实成交闭环。

## 非目标 [按需]
不实现真实 order emission，不实现系统常驻 scheduler，不自动 HALT/恢复，不接 Binance testnet/live key。

## 验收一句话 [必填]
action_required reconciliation 现在能被 refs-only producer 幂等转成 follow-up action/QRO；重复运行不会重复写，不会触碰真实下单或交易所 API。

## 完成记录（2026-06-27）
- `/api/research-os/execution/reconciliation_actions/run_pending` 已落地。
- 默认映射：`needs_reconcile` -> `request_missing_reconcile`；`terminal_conflict` / `venue_order_mismatch` -> `escalate_manual_review`；其他 pending -> `investigate`。
- producer 按 `(reconciliation_ref, action_kind)` 对 open/acknowledged action 幂等 skip。
- 本地验证：
  - `python -m pytest app/backend/tests/test_execution_boundary_contract.py -q` -> 26 passed / 2 warnings。
  - `python -m pytest app/backend/tests/test_execution_boundary_contract.py app/backend/tests/test_portfolio_promote_api.py app/backend/tests/test_factor_strategy_boundary.py app/backend/tests/test_realmoney_audit_killswitch.py app/backend/tests/test_entrypoint_gate_coverage.py app/backend/tests/test_engineering_standards.py -q` -> 73 passed / 2 warnings。
  - `python -m pytest app/backend/tests/test_execution_boundary_contract.py app/backend/tests/test_portfolio_promote_api.py app/backend/tests/test_factor_strategy_boundary.py app/backend/tests/test_factor_lab_endpoints.py app/backend/tests/test_model_governance.py app/backend/tests/test_research_os_spine.py app/backend/tests/test_entrypoint_gate_coverage.py app/backend/tests/test_goal_coverage.py app/backend/tests/test_platform_coverage.py app/backend/tests/test_engineering_standards.py app/backend/tests/test_realmoney_audit_killswitch.py -q` -> 140 passed / 2 warnings。
  - `python -m compileall app/backend/app` -> PASS。
  - `python dev/scripts/validate_dev.py` -> 49 ✅ / 0 ❌ / 0 ⚠️（DAG 164）。
