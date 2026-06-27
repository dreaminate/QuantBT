---
uuid: 0c4d71a9a419429799a93c35b57e3908
title: Execution reconciliation batch worker API
status: done
owner: dreaminate
assigned_by: dreaminate
review_status: 1
priority: P1
area: research-os-execution-boundary
source: goal-gap
source_ref: GOAL §12 reconciliation batch worker
depends_on: [4a7d2e90a419429799a93c35b57e3908]
completed_at: 2026-06-27
---

# Execution reconciliation batch worker API

## Scope [必填]
新增 execution reconciliation batch worker API：扫描已记录的 venue event refs，按 order intent/runtime promotion/venue order 分组，生成 append-only reconciliation records，并写入 ExecutionPolicy QRO。它只处理已落库事件，不调用 venue、不发单、不移动资金。

## 上下文 / 动机 [按需]
`4a7d2e90` 已有单笔 reconciliation record/API/QRO，但 §12 仍缺批量 worker 入口来处理 pending venue events。GOAL 要求执行边界可对 HALT/截断后的事件做对账，不能依赖人工逐笔补 record。

## 接线点（file:line，实现时复核）[必填]
| 文件 | 改什么 |
|---|---|
| `app/backend/app/research_os/execution_boundary.py` | 新增 `ExecutionReconciliationRecord` builder/validator/JSONL registry，支持按 venue event refs 生成 reconciliation 状态 |
| `app/backend/app/research_os/__init__.py` | 导出 reconciliation runtime objects |
| `app/backend/app/main.py` | 新增 `/api/research-os/execution/reconciliations/run_pending`，复用 registry + QRO write-through，按已记录 venue events 分组批量产 reconciliation |
| `app/backend/tests/test_execution_boundary_contract.py` | 覆盖 batch worker 创建记录和重复调用幂等跳过 |

## 对抗测试设计（种已知 bug，门必抓）[必填]
1. batch worker 必须只扫描 `EXECUTION_VENUE_EVENTS` 已记录 refs，不能调用 venue 或 place order。
2. 同一组事件重复 run 必须 idempotent skip，不能重复写 reconciliation/QRO。
3. 缺 order intent/runtime promotion 的组必须跳过，不写 partial。
4. 响应必须标明 `record_only=true`、`api_place_order_called=false`、`api_venue_call_called=false`。

## 红线 [按需]
- 不调用交易所、不新增 broker connector、不移动资金。
- 不新增裸 `place_order`。
- 不保存 raw order、raw venue payload、filled_qty、fill_price、commission 或明文 secret。
- 不把 batch worker 说成生产长期 scheduler、venue API 连通或真实成交对账已闭合。

## 非目标 [按需]
不实现真实 order emission，不接 Binance testnet/live key，不实现部署级长期调度，不改变 copy-trade relay 路径。

## 验收一句话 [必填]
已落库的 venue events 现在可被 refs-only batch worker 幂等转成 reconciliation records/QRO；重复执行不会重复写，仍不触碰真实下单或交易所 API。

## 完成记录（2026-06-27）
- `/api/research-os/execution/reconciliations/run_pending` 已落地，按 `(order_intent_ref, runtime_promotion_ref, venue_order_ref)` 分组处理 venue events。
- worker 先确认 upstream order intent/runtime promotion 存在，再生成 reconciliation record；已存在同 event refs 的 reconciliation 会 skip。
- 成功路径写 `DATA_ROOT/audit/execution_reconciliations.jsonl` 和 `QROType.EXECUTION_POLICY` / `upsert_qro` command。
- 本地验证：
  - `python -m pytest app/backend/tests/test_execution_boundary_contract.py -q` -> 23 passed / 2 warnings。
  - `python -m pytest app/backend/tests/test_execution_boundary_contract.py app/backend/tests/test_portfolio_promote_api.py app/backend/tests/test_factor_strategy_boundary.py app/backend/tests/test_realmoney_audit_killswitch.py app/backend/tests/test_entrypoint_gate_coverage.py app/backend/tests/test_engineering_standards.py -q` -> 70 passed / 2 warnings。
  - `python -m pytest app/backend/tests/test_execution_boundary_contract.py app/backend/tests/test_portfolio_promote_api.py app/backend/tests/test_factor_strategy_boundary.py app/backend/tests/test_factor_lab_endpoints.py app/backend/tests/test_model_governance.py app/backend/tests/test_research_os_spine.py app/backend/tests/test_entrypoint_gate_coverage.py app/backend/tests/test_goal_coverage.py app/backend/tests/test_platform_coverage.py app/backend/tests/test_engineering_standards.py app/backend/tests/test_realmoney_audit_killswitch.py -q` -> 137 passed / 2 warnings。
  - `python -m compileall app/backend/app` -> PASS。
  - `python dev/scripts/validate_dev.py` -> 49 ✅ / 0 ❌ / 0 ⚠️（DAG 162）。
