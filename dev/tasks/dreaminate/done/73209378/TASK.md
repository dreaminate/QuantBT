---
uuid: 73209378c3904940b9073189804d2f56
title: Agent backtest.run existing-run projection requires MarketDataUse PIT refs
status: done
owner: dreaminate
assigned_by: dreaminate
review_status: 1
priority: P1
area: agent-backtest-existing-run-market-data-pit-gate
source: goal-gap
source_ref: GOAL §7/§9/§10/§11 Agent existing run report data timing/PIT gate
depends_on: [4b6f55dccf2748b692ebe43493979eff, b7651d5050e64c8390d0a8375bb30489]
completed_at: 2026-06-27
---

# Agent backtest.run existing-run projection requires MarketDataUse PIT refs

## Scope [必填]
把 Agent business tool `backtest.run` 的 existing-run projection 分支从“给 `run_id` 即可投影 run 摘要”升级为必须声明 `market_data_use_validation_refs`。该分支在调用 `project_verdict` / `project_overfit` 前回查 MarketDataUse registry：refs 必须 accepted、无 violation、use_context 为 backtest/confirmatory_validation，且 DatasetSemantics 具备 `known_at_ref` / `effective_at_ref` / `pit_bitemporal_rules_ref`。

## 上下文 / 动机 [按需]
`backtest.run` 无 run_id 的 strategy synthesis 分支已在 LLM/codegen/sample/sandbox/promote 前强制 MarketDataUse refs，direct RunVerdictCard endpoints 也已加门。但 `backtest.run` 若传入已有 `run_id`，handler 直接投影 verdict/overfit 摘要，绕过 schema 的 refs 要求。GOAL §10/§11 不允许这个 Agent report/summary 旁路。

## 接线点（file:line，实现时复核）[必填]
| 文件 | 改什么 |
|---|---|
| `app/backend/app/agent/business_tools.py` | `backtest.run` existing-run branch 在 projector 前调用 `_market_data_use_validation_refs(..., require_dataset_timing=True, allowed_use_contexts=(backtest, confirmatory_validation))`，成功响应回显 refs |
| `app/backend/tests/test_agent_business_tools_a4.py` | 新增缺 refs no-call test；新增成功 existing-run projection refs 回显 test |

## 对抗测试设计（种已知 bug，门必抓）[必填]
1. existing-run `backtest.run` 缺 refs 时返回 `no_write=true`。
2. 缺 refs 时不能调用 `project_verdict` 或 `project_overfit`。
3. 成功 existing-run projection 回显 refs。

## 红线 [按需]
- 不把 MarketDataUse refs 说成已逐行证明 run artifact 对每条原始行情 row 的消费。
- 不把 existing-run summary 说成新回测、RDP formal package、alpha approval、strategy promotion 或 execution permission。
- 不把本地 pytest 结果说成 CI。

## 非目标 [按需]
不改 `backtest.run` 新合成回测主路径、不实现完整 strategy assembly injection、不实现所有 Agent tools 的数据 gate。

## 验收一句话 [必填]
Agent `backtest.run` 传已有 `run_id` 投影摘要时，现在也必须先带 accepted/PIT MarketDataUse refs。

## 完成记录（2026-06-27）
- `backtest.run` existing-run projection branch 在 `project_verdict` / `project_overfit` 前强制 MarketDataUse/PIT hard gate。
- 成功响应回显 `market_data_use_validation_refs`。
- 本地验证：
  - `python -m pytest app/backend/tests/test_agent_business_tools_a4.py -q` -> 33 passed / 2 warnings。
  - `python -m pytest app/backend/tests/test_agent_business_tools_a4.py app/backend/tests/test_agent_tool_status.py app/backend/tests/test_ds1_run_id_spine.py app/backend/tests/test_delivery_slice_e2e.py app/backend/tests/test_run_verdict_card.py app/backend/tests/test_goal_coverage.py app/backend/tests/test_market_data_contract.py app/backend/tests/test_execution_boundary_contract.py -q` -> 181 passed / 2 warnings。
  - `python -m pytest app/backend/tests/test_model_governance.py -q` -> 31 passed / 2 warnings（修正 raw-payload 泄漏断言用裸 `"1.5"` 误撞时间戳的测试误报；runtime 未变）。
  - `python -m pytest app/backend/tests -q` -> 1830 passed / 13 skipped / 283 warnings。
  - `python -m compileall -q app/backend/app` -> PASS。
  - `python dev/scripts/validate_dev.py` -> 49 passed / 0 errors / 0 warnings。
  - `git diff --check` -> PASS。
