---
uuid: b7651d5050e64c8390d0a8375bb30489
title: Direct run report endpoints require MarketDataUse PIT refs before projection
status: done
owner: dreaminate
assigned_by: dreaminate
review_status: 1
priority: P1
area: run-report-market-data-pit-gate
source: goal-gap
source_ref: GOAL §9/§10/§11 direct run report data timing/PIT gate
depends_on: [8f9d53ace28d46c6b1c00967ce889a5f, f2722491c6f6453aaf181bcc7b047cb3]
completed_at: 2026-06-27
---

# Direct run report endpoints require MarketDataUse PIT refs before projection

## Scope [必填]
把 direct RunVerdictCard 报告 API 从“可只凭 run_id 投影”升级为必须声明 `market_data_use_validation_refs`。覆盖 `GET /api/runs/{run_id}/verdict`、`/overfit`、`/cost-sensitivity` 和 `/monthly-heatmap`。endpoint 先从 run manifest 读取 market，再在生成 verdict / overfit / cost / heatmap 投影前回查 MarketData registry：accepted、无 violation、backtest/confirmatory use_context、DatasetSemantics timing refs、Instrument/Capability market coverage 和 Capability backtest permission 都必须通过。

## 上下文 / 动机 [按需]
Agent Shell `report.generate` 已经在调用 `project_verdict` / `project_overfit` / `project_cost_sensitivity` 前强制 MarketDataUse/PIT refs，但同一组 direct HTTP report endpoints 仍可被前端或其它客户端绕过 Agent tool schema 直接调用。GOAL §10/§11 要求 report/estimator 绑定 data timing/PIT，不能让 RunVerdictCard direct API 成为非 RDP 报告旁路。

## 接线点（file:line，实现时复核）[必填]
| 文件 | 改什么 |
|---|---|
| `app/backend/app/main.py` | 新增 `_run_report_market_data_use_validation_refs`；四个 run report GET endpoints 增加 query `market_data_use_validation_refs`；在调用 projectors 前执行 gate；成功响应回显 refs |
| `app/backend/tests/test_run_verdict_card.py` | fixture 登记 crypto run report MarketDataUseValidation；所有成功路径显式传 refs；新增缺 refs no-call test |

## 对抗测试设计（种已知 bug，门必抓）[必填]
1. verdict / overfit / cost-sensitivity / monthly-heatmap 缺 refs 时 422。
2. 缺 refs 时不能调用 `project_verdict`、`project_overfit`、`project_cost_sensitivity` 或 `project_monthly_heatmap`。
3. 成功路径必须回显 deduped refs。
4. missing run 仍返回 404，不被 refs gate 错改成 422。

## 红线 [按需]
- 不把 MarketDataUse refs 说成 run artifact 已逐行证明每条原始行情 row 的消费。
- 不把 RunVerdictCard report 说成 RDP formal package、alpha approval、strategy promotion 或 execution permission。
- 不把本地 pytest 结果说成 CI。

## 非目标 [按需]
不实现所有报告入口、真实 provider 实网连通、外部 RDP publish、线上或用户验收。

## 验收一句话 [必填]
Direct run verdict / overfit / cost / monthly heatmap reports 现在必须先带 accepted/PIT MarketDataUse refs，才会生成投影。

## 完成记录（2026-06-27）
- `GET /api/runs/{run_id}/verdict`、`/overfit`、`/cost-sensitivity`、`/monthly-heatmap` 在 report projector 前强制 MarketDataUse/PIT hard gate。
- 成功响应回显 `market_data_use_validation_refs`。
- 本地验证：
  - `python -m pytest app/backend/tests/test_run_verdict_card.py -q` -> 16 passed / 2 warnings。
  - `python -m pytest app/backend/tests/test_run_verdict_card.py app/backend/tests/test_agent_business_tools_a4.py app/backend/tests/test_agent_tool_status.py app/backend/tests/test_ds1_run_id_spine.py app/backend/tests/test_delivery_slice_e2e.py app/backend/tests/test_goal_coverage.py app/backend/tests/test_market_data_contract.py app/backend/tests/test_execution_boundary_contract.py -q` -> 179 passed / 2 warnings。
  - `python -m pytest app/backend/tests -q` -> 1828 passed / 13 skipped / 283 warnings。
  - `python -m compileall -q app/backend/app` -> PASS。
  - `python dev/scripts/validate_dev.py` -> 49 passed / 0 errors / 0 warnings。
  - `git diff --check` -> PASS。
