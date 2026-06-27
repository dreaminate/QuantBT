---
uuid: 8f2d4b0ca419429799a93c35b57e3908
title: Execution order intent QRO write-through
status: done
owner: dreaminate
assigned_by: dreaminate
review_status: 1
priority: P1
area: research-os-execution-boundary
source: goal-gap
source_ref: GOAL §9/§12 order intent QRO write-through
depends_on: [5e1d0a777342f902770f47ddad15a947]
completed_at: 2026-06-27
---

# Execution order intent QRO write-through

## Scope [必填]
把 `/api/research-os/execution/order_intents` 成功记录的 typed order intent 同步写入 `ResearchGraphStore`，生成 `QROType.EXECUTION_POLICY` 和 `upsert_qro` command；这只把 order intent 接进 QRO/Research Graph 审计主线，不下单、不调 venue、不动钱。

## 上下文 / 动机 [按需]
`5e1d0a77` 已新增 `ExecutionOrderIntentRecord` / JSONL registry / API，但成功路径只落 order-intent audit file，尚未进入 GOAL §1/§9/§12 要求的 QRO/Research Graph 主路径。本卡补 write-through，让 portfolio/signal→order intent 至少有可查的 ExecutionPolicy QRO。

## 接线点（file:line，实现时复核）[必填]
| 文件 | 改什么 |
|---|---|
| `app/backend/app/main.py` | order intent API 成功记录后调用 `_record_execution_order_intent_qro()`，写 `QROType.EXECUTION_POLICY` + `ResearchGraphCommand(upsert_qro)` |
| `app/backend/tests/test_execution_boundary_contract.py` | 覆盖 API 成功路径返回 `qro_id` / `research_graph_command_id`，并确认 QRO output contract 仍为 `place_order_called=false` |

## 对抗测试设计（种已知 bug，门必抓）[必填]
1. 成功记录 order intent 后必须能从 `ResearchGraphStore.qro(qro_id)` 读回 `QROType.EXECUTION_POLICY`。
2. QRO `output_contract` 必须保留 `place_order_called=false`。
3. QRO `output_contract` 不得包含 raw quantity、raw_order、price、notional、secret 等下单/凭据材料。
4. API 带 raw quantity 的拒绝路径不得写 order intent，也不得写 QRO command。

## 红线 [按需]
- 不调用 `place_order`。
- 不新增 broker connector、venue client、资金动作或 live order emission。
- 不保存 raw quantity/price/notional、API key、secret、token 或 venue raw payload。
- 不把 QRO write-through 说成交易已执行。

## 非目标 [按需]
不实现 order emission，不实现 testnet/live connector，不接 broker ack/fill/reconcile，不改变 `ExecutionOrderIntentRecord` 的安全门。

## 验收一句话 [必填]
Order intent record API 成功路径现在写入 ExecutionPolicy QRO 和 ResearchGraph command；审计图能看到 intent，但系统仍明确没有下单。

## 完成记录（2026-06-27）
- `/api/research-os/execution/order_intents` 成功路径已返回 `qro_id` 与 `research_graph_command_id`。
- 写入的 QRO 带 `market/universe/horizon/frequency/lineage/implementation_hash`，可被 Research Graph replay/projection 消费。
- QRO output contract 只记录执行策略、风控、venue/permission/guard/audit/kill-switch/SecretRef/responsibility refs，并保留 `place_order_called=false`。
- 本地验证：
  - `python -m pytest app/backend/tests/test_execution_boundary_contract.py -q` -> 12 passed / 2 warnings。
  - `python -m pytest app/backend/tests/test_execution_boundary_contract.py app/backend/tests/test_portfolio_promote_api.py app/backend/tests/test_factor_strategy_boundary.py app/backend/tests/test_realmoney_audit_killswitch.py app/backend/tests/test_entrypoint_gate_coverage.py app/backend/tests/test_engineering_standards.py -q` -> 59 passed / 2 warnings。
  - `python -m pytest app/backend/tests/test_execution_boundary_contract.py app/backend/tests/test_portfolio_promote_api.py app/backend/tests/test_factor_strategy_boundary.py app/backend/tests/test_factor_lab_endpoints.py app/backend/tests/test_model_governance.py app/backend/tests/test_research_os_spine.py app/backend/tests/test_entrypoint_gate_coverage.py app/backend/tests/test_goal_coverage.py app/backend/tests/test_platform_coverage.py app/backend/tests/test_engineering_standards.py app/backend/tests/test_realmoney_audit_killswitch.py -q` -> 126 passed / 2 warnings。
  - `python -m compileall app/backend/app` -> PASS。
  - `python dev/scripts/validate_dev.py` -> 49 ✅ / 0 ❌ / 0 ⚠️（DAG 158）。
