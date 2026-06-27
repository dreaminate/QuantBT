---
uuid: 8f9d53ace28d46c6b1c00967ce889a5f
title: Agent report.generate requires MarketDataUse PIT refs before report projection
status: done
owner: dreaminate
assigned_by: dreaminate
review_status: 1
priority: P1
area: agent-report-market-data-pit-gate
source: goal-gap
source_ref: GOAL §11/§13/§17 non-RDP report data timing/PIT gate
depends_on: [48f70fa3e9af4caebdffca604ea3df6f, 5ba64e4f8fd84834964da8c8afefbdf2]
completed_at: 2026-06-27
---

# Agent report.generate requires MarketDataUse PIT refs before report projection

## Scope [必填]
把 Agent Shell 的 `report.generate` 从“给 run_id 即可投影 markdown 报告”升级为必须声明 `market_data_use_validation_refs`。handler 在调用 `project_verdict` / `project_overfit` / `project_cost_sensitivity` 前先回查 MarketDataUse registry：每个 ref 必须存在、accepted、无 violation、use_context 为 `backtest` 或 `confirmatory_validation`，且其 DatasetSemantics 必须有 `known_at_ref`、`effective_at_ref`、`pit_bitemporal_rules_ref`。

## 上下文 / 动机 [按需]
RDP formal package 已有 MarketDataUse/PIT gate，但 Agent `report.generate` 仍是非 RDP 报告入口。它虽然不写文件，但会把 run 解释为报告；如果没有数据使用 refs，报告面仍可能绕开 event/known/effective time 证据。

## 接线点（file:line，实现时复核）[必填]
| 文件 | 改什么 |
|---|---|
| `app/backend/app/agent/business_tools.py` | 通用 `_market_data_use_validation_refs` 支持 operation 名、use_context 白名单和 DatasetSemantics timing refs；`report.generate` 在投影前调用该 gate，成功返回/markdown 显示 refs |
| `app/backend/app/agent/tool_schema.py` | `report.generate` schema 增加并 require `market_data_use_validation_refs` |
| `app/backend/tests/test_agent_business_tools_a4.py` | 增加 schema、缺 refs、unknown/rejected/violation/wrong context/timing 缺失 no-write 和成功路径测试 |

## 对抗测试设计（种已知 bug，门必抓）[必填]
1. 缺 `market_data_use_validation_refs` 时不调用报告投影函数。
2. unknown / rejected / violation / wrong use_context 的 refs 均返回 `no_write=true`，不投影报告。
3. DatasetSemantics 缺 PIT/bitemporal timing refs 时返回 `no_write=true`。
4. 成功路径 markdown 与返回体都包含 MarketDataUse refs。
5. tool schema 要求 `run_id` 和 `market_data_use_validation_refs`。

## 红线 [按需]
- 不把 MarketDataUse refs 说成报告已逐行验证 run 使用了每一条行情 row。
- 不把 Agent markdown 报告说成 RDP formal package、外部 publish、CI release 或线上验收。
- 不把本地 pytest 结果说成 CI。

## 非目标 [按需]
不实现 RDP 之外所有报告入口、所有回测入口、完整 report artifact persistence、外部发布、CI release 或真实 provider 实网连通。

## 验收一句话 [必填]
Agent `report.generate` 现在必须先带 accepted/PIT MarketDataUse refs，才能投影 run 报告；坏 refs 在报告投影前 fail-closed。

## 完成记录（2026-06-27）
- `report.generate` schema 与 handler 均要求 `market_data_use_validation_refs`。
- 报告投影前回查 accepted/no-violation refs、use_context 和 DatasetSemantics timing refs。
- 成功报告返回体与 markdown 显示 MarketDataUse refs。
- 本地验证：
  - `python -m compileall -q app/backend/app` -> PASS。
  - `python -m pytest app/backend/tests/test_agent_business_tools_a4.py app/backend/tests/test_agent_tool_status.py -q` -> 37 passed / 2 warnings。
  - `python -m pytest app/backend/tests/test_ds1_run_id_spine.py app/backend/tests/test_delivery_slice_e2e.py app/backend/tests/test_agent_runtime_research_graph.py app/backend/tests/test_chat_conversations.py -q` -> 51 passed / 2 warnings。
  - `python -m pytest app/backend/tests/test_agent_business_tools_a4.py app/backend/tests/test_agent_tool_status.py app/backend/tests/test_ds1_run_id_spine.py app/backend/tests/test_delivery_slice_e2e.py app/backend/tests/test_agent_runtime_research_graph.py app/backend/tests/test_chat_conversations.py app/backend/tests/test_market_data_contract.py app/backend/tests/test_goal_coverage.py -q` -> 118 passed / 2 warnings。
  - `python -m pytest app/backend/tests -q` -> 1820 passed / 13 skipped / 283 warnings.
  - `python dev/scripts/validate_dev.py` -> 49 passed / 0 errors / 0 warnings.
  - `git diff --check` -> PASS。
