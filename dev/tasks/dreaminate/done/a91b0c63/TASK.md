---
uuid: a91b0c63a419429799a93c35b57e3908
title: Weekly monitor execution reconciliation action producer wiring
status: done
owner: dreaminate
assigned_by: dreaminate
review_status: 1
priority: P1
area: research-os-execution-boundary
source: goal-gap
source_ref: GOAL §12 reconciliation scheduler wiring
depends_on: [d4c9a2f0a419429799a93c35b57e3908]
completed_at: 2026-06-27
---

# Weekly monitor execution reconciliation action producer wiring

## Scope [必填]
把 execution reconciliation action producer 接入现有 production weekly monitor tick 路径：手动 `/api/monitor/weekly_tick` 和 DAG result recorder 在记录 monitor QRO 后触发一次 refs-only reconciliation action producer。它是本地 weekly tick 接线，不是线上常驻 scheduler 运行证明。

## 上下文 / 动机 [按需]
`d4c9a2f0` 已有 `/api/research-os/execution/reconciliation_actions/run_pending`，但 §12 剩余缺口仍包括 scheduler 接线。现有 `monitor.weekly_tick` 已是 production monitor 的本地调度路径，本卡把 pending reconciliation action producer 接进去，使 weekly tick 不只处理 factor lifecycle，也能把 execution reconciliation 异常推进治理 action 队列。

## 接线点（file:line，实现时复核）[必填]
| 文件 | 改什么 |
|---|---|
| `app/backend/app/main.py` | 抽出 `_run_pending_execution_reconciliation_actions()` helper；weekly monitor endpoint 和 `_record_weekly_monitor_qro_from_scheduler()` 调用该 helper |
| `app/backend/tests/test_monitor_production.py` | 隔离 execution reconciliation registries；覆盖 weekly monitor endpoint 触发 action producer，并验证重复 tick 幂等 skip |

## 对抗测试设计（种已知 bug，门必抓）[必填]
1. weekly monitor tick 遇 pending reconciliation 必须创建 `request_missing_reconcile` action。
2. 第二次 weekly tick 必须 skip 已有 open action，不能重复写 QRO。
3. monitor QRO 仍不泄露 factor/cost payload；execution action QRO 仍不泄露 raw order/fill/venue payload。
4. 测试必须把 execution registries patch 到 tmp_path，不能碰真实 `DATA_ROOT`。

## 红线 [按需]
- 不调用交易所、不新增 broker connector、不移动资金。
- 不新增裸 `place_order`。
- 不保存 raw order、raw venue payload、filled_qty、fill_price、commission 或明文 secret。
- 不把本地 weekly tick 接线说成线上长期 scheduler、自动 remediation、venue API 连通或真实成交闭环。

## 非目标 [按需]
不实现真实 order emission，不证明部署级长期进程已运行，不自动 HALT/恢复，不接 Binance testnet/live key。

## 验收一句话 [必填]
weekly monitor tick 现在会触发 execution reconciliation action producer，把 pending reconciliation 变成 refs-only follow-up action/QRO；重复 tick 不重复写。

## 完成记录（2026-06-27）
- `_run_pending_execution_reconciliation_actions()` 抽成单一 helper，API endpoint 和 weekly monitor 共用。
- `/api/monitor/weekly_tick` 返回 `execution_reconciliation_action_producer` 摘要。
- `_record_weekly_monitor_qro_from_scheduler()` 在 DAG result_recorder 中也触发 action producer。
- 本地验证：
  - `python -m pytest app/backend/tests/test_monitor_production.py app/backend/tests/test_execution_boundary_contract.py -q` -> 33 passed / 2 warnings。
  - `python -m pytest app/backend/tests/test_execution_boundary_contract.py app/backend/tests/test_monitor_production.py app/backend/tests/test_portfolio_promote_api.py app/backend/tests/test_factor_strategy_boundary.py app/backend/tests/test_realmoney_audit_killswitch.py app/backend/tests/test_entrypoint_gate_coverage.py app/backend/tests/test_engineering_standards.py -q` -> 80 passed / 2 warnings。
  - `python -m pytest app/backend/tests/test_execution_boundary_contract.py app/backend/tests/test_monitor_production.py app/backend/tests/test_portfolio_promote_api.py app/backend/tests/test_factor_strategy_boundary.py app/backend/tests/test_factor_lab_endpoints.py app/backend/tests/test_model_governance.py app/backend/tests/test_research_os_spine.py app/backend/tests/test_entrypoint_gate_coverage.py app/backend/tests/test_goal_coverage.py app/backend/tests/test_platform_coverage.py app/backend/tests/test_engineering_standards.py app/backend/tests/test_realmoney_audit_killswitch.py -q` -> 147 passed / 2 warnings。
  - `python -m compileall app/backend/app` -> PASS。
  - `python dev/scripts/validate_dev.py` -> 49 ✅ / 0 ❌ / 0 ⚠️（DAG 165）。
