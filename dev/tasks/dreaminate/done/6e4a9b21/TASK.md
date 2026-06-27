---
uuid: 6e4a9b21a419429799a93c35b57e3908
title: Execution reconciliation action QRO API
status: done
owner: dreaminate
assigned_by: dreaminate
review_status: 1
priority: P1
area: research-os-execution-boundary
source: goal-gap
source_ref: GOAL §12 reconciliation monitor action path
depends_on: [0c4d71a9a419429799a93c35b57e3908]
completed_at: 2026-06-27
---

# Execution reconciliation action QRO API

## Scope [必填]
新增 execution reconciliation action record/API：对 `action_required=true` 的 reconciliation 记录 follow-up action refs，并写入 ExecutionPolicy QRO。它只记录治理动作，不自动执行 remediation、不调用 venue、不发单、不移动资金。

## 上下文 / 动机 [按需]
`0c4d71a9` 已能把已记录 venue events 批量转成 reconciliation records/QRO，但 GOAL §12 还要求 monitor/action path 不能停在“发现问题”。本卡补第一版 refs-only action record，使 missing reconcile、terminal conflict、venue mismatch 等状态能进入可审计的 follow-up 队列。

## 接线点（file:line，实现时复核）[必填]
| 文件 | 改什么 |
|---|---|
| `app/backend/app/research_os/execution_boundary.py` | 新增 `ExecutionReconciliationActionRecord`、parser、validator、`PersistentExecutionReconciliationActionRegistry` |
| `app/backend/app/research_os/__init__.py` | 导出 reconciliation action runtime objects |
| `app/backend/app/main.py` | 新增 app-level `EXECUTION_RECONCILIATION_ACTIONS` JSONL registry、`/api/research-os/execution/reconciliation_actions` record/summary API、ExecutionPolicy QRO write-through |
| `app/backend/tests/test_execution_boundary_contract.py` | 覆盖 action_required reconciliation 生成 action/QRO、clean reconciliation 不允许生成 action |

## 对抗测试设计（种已知 bug，门必抓）[必填]
1. `needs_reconcile/action_required=true` 才能生成 follow-up action，且 QRO 标明 action kind/status。
2. `reconciled/action_required=false` 不能被强行创建 action，失败不写 JSONL/Graph。
3. action payload 必须 refs-only，不能出现 raw order/fill/venue payload。
4. API 和 QRO 必须标明 `record_only=true`、`api_place_order_called=false`、`api_venue_call_called=false`。

## 红线 [按需]
- 不调用交易所、不新增 broker connector、不移动资金。
- 不新增裸 `place_order`。
- 不保存 raw order、raw venue payload、filled_qty、fill_price、commission 或明文 secret。
- 不把 action record 说成自动 remediation、长期 scheduler、venue API 连通或真实成交对账闭环。

## 非目标 [按需]
不实现真实 order emission，不实现部署级长期调度，不自动 HALT/恢复，不接 Binance testnet/live key。

## 验收一句话 [必填]
execution reconciliation 的异常状态现在能进入 refs-only follow-up action registry/QRO；干净 reconciliation 会被拒绝创建 action，避免制造假问题或假治理。

## 完成记录（2026-06-27）
- `ExecutionReconciliationActionRecord` / `PersistentExecutionReconciliationActionRegistry` 已落 runtime。
- `/api/research-os/execution/reconciliation_actions` 成功路径写 `DATA_ROOT/audit/execution_reconciliation_actions.jsonl` 和 `QROType.EXECUTION_POLICY` / `upsert_qro` command。
- `/api/research-os/execution/reconciliation_actions/summary` 只返回 action refs/status/owner/evidence refs，不返回 raw venue/order material。
- 本地验证：
  - `python -m pytest app/backend/tests/test_execution_boundary_contract.py -q` -> 25 passed / 2 warnings。
  - `python -m pytest app/backend/tests/test_execution_boundary_contract.py app/backend/tests/test_portfolio_promote_api.py app/backend/tests/test_factor_strategy_boundary.py app/backend/tests/test_realmoney_audit_killswitch.py app/backend/tests/test_entrypoint_gate_coverage.py app/backend/tests/test_engineering_standards.py -q` -> 72 passed / 2 warnings。
  - `python -m pytest app/backend/tests/test_execution_boundary_contract.py app/backend/tests/test_portfolio_promote_api.py app/backend/tests/test_factor_strategy_boundary.py app/backend/tests/test_factor_lab_endpoints.py app/backend/tests/test_model_governance.py app/backend/tests/test_research_os_spine.py app/backend/tests/test_entrypoint_gate_coverage.py app/backend/tests/test_goal_coverage.py app/backend/tests/test_platform_coverage.py app/backend/tests/test_engineering_standards.py app/backend/tests/test_realmoney_audit_killswitch.py -q` -> 139 passed / 2 warnings。
  - `python -m compileall app/backend/app` -> PASS。
  - `python dev/scripts/validate_dev.py` -> 49 ✅ / 0 ❌ / 0 ⚠️（DAG 163）。
