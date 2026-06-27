---
uuid: 5e1d0a777342f902770f47ddad15a947
title: Execution order intent registry API
status: done
owner: dreaminate
assigned_by: dreaminate
review_status: 1
priority: P1
area: research-os-execution-boundary
source: goal-gap
source_ref: GOAL §9/§12 order typed contract
depends_on: [2c9f4e11035a9911d9814c9ab8fb77a2]
completed_at: 2026-06-27
---

# Execution order intent registry API

## Scope [必填]
新增 execution order intent 的 first-class append-only record/API，把 portfolio/signal 到 order 的下一段做成可验证的 typed intent contract；只记录 refs，不下单、不调用 venue、不动钱。

## 上下文 / 动机 [按需]
`2c9f4e11` 已让 portfolio promote 声明 signal 时必须绑定 accepted signal validation；§9/§12 仍缺 portfolio/signal→order 的 typed contract。直接接真钱下单会跨越安全红线，本卡先补 order intent audit object 和 hard gate，为后续 execution transition 接线提供单一路径。

## 接线点（file:line，实现时复核）[必填]
| 文件 | 改什么 |
|---|---|
| `app/backend/app/research_os/execution_boundary.py` | 新增 `ExecutionOrderIntentRecord`、`PersistentExecutionOrderIntentRegistry`、`validate_execution_order_intent` |
| `app/backend/app/research_os/__init__.py` | 导出 order intent runtime objects |
| `app/backend/app/main.py` | 新增 app-level `EXECUTION_ORDER_INTENTS` JSONL registry 和 `/api/research-os/execution/order_intents` record/summary API |
| `app/backend/tests/test_execution_boundary_contract.py` | 覆盖 order intent invariant、registry replay、API no-place-order、raw quantity no-write |

## 对抗测试设计（种已知 bug，门必抓）[必填]
1. live A股 order intent 必须拒。
2. testnet/live order intent 缺 OrderGuard/permission/idempotency/audit/kill-switch/SecretRef/responsibility refs 必须拒。
3. API payload 带 raw `quantity` / `price` / `notional` / `secret` / `raw_order` 必须拒，且不写 JSONL。
4. API 成功路径必须返回 `place_order_called=false`，并且 summary 不含 raw quantity/raw order。

## 红线 [按需]
- 不调用 `place_order`。
- 不把 order intent 说成订单已发、交易已执行或资金已动。
- 不保存 raw quantity/price/notional、API key、secret、token 或 venue raw payload。
- 不放开 A股 live。

## 非目标 [按需]
不实现 order emission，不实现 live trading，不实现 broker connector，不改 OrderGuard，不改变组合 gate 算法。

## 验收一句话 [必填]
Order intent 可作为 typed execution contract 记录和重放；testnet/live intent 必须绑定执行不变量，API 不接受 raw 下单材料且不会下单。

## 完成记录（2026-06-27）
- `ExecutionOrderIntentRecord` / `PersistentExecutionOrderIntentRegistry` 已落 runtime。
- `/api/research-os/execution/order_intents` 只记录 refs，返回 `place_order_called=false`。
- `/api/research-os/execution/order_intents/summary` 只返回 order intent refs，不返回 raw quantity/raw order。
- 本地验证：
  - `python -m pytest app/backend/tests/test_execution_boundary_contract.py -q` -> 12 passed / 2 warnings。
  - `python -m pytest app/backend/tests/test_execution_boundary_contract.py app/backend/tests/test_portfolio_promote_api.py app/backend/tests/test_factor_strategy_boundary.py app/backend/tests/test_realmoney_audit_killswitch.py app/backend/tests/test_entrypoint_gate_coverage.py app/backend/tests/test_engineering_standards.py -q` -> 59 passed / 2 warnings。
  - `python -m pytest app/backend/tests/test_execution_boundary_contract.py app/backend/tests/test_portfolio_promote_api.py app/backend/tests/test_factor_strategy_boundary.py app/backend/tests/test_factor_lab_endpoints.py app/backend/tests/test_model_governance.py app/backend/tests/test_research_os_spine.py app/backend/tests/test_entrypoint_gate_coverage.py app/backend/tests/test_goal_coverage.py app/backend/tests/test_platform_coverage.py app/backend/tests/test_engineering_standards.py app/backend/tests/test_realmoney_audit_killswitch.py -q` -> 126 passed / 2 warnings。
  - `python -m compileall app/backend/app` -> PASS。
  - `python dev/scripts/validate_dev.py` -> 49 ✅ / 0 ❌ / 0 ⚠️（DAG 157）。
