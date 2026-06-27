---
uuid: 499980c81d4640efb90ad3d738618173
title: Agent backtest.run strategy synthesis requires PIT DatasetSemantics refs
status: done
owner: dreaminate
assigned_by: dreaminate
review_status: 1
priority: P1
area: agent-backtest-synthesis-market-data-pit-gate
source: goal-gap
source_ref: GOAL §7/§9/§10/§11 Agent strategy synthesis data timing/PIT gate
depends_on: [4b6f55dccf2748b692ebe43493979eff, 73209378c3904940b9073189804d2f56]
completed_at: 2026-06-27
---

# Agent backtest.run strategy synthesis requires PIT DatasetSemantics refs

## Scope [必填]
把 Agent `backtest.run` 无 `run_id` 的 strategy synthesis 主路径从“只要求 accepted/no-violation MarketDataUse refs”升级为必须绑定 PIT/bitemporal DatasetSemantics timing refs。`_synth_and_promote` 在 LLM/codegen/sample/sandbox/promote 前要求 refs 已记录、accepted、无 violation，use_context 为 `strategy_builder_backtest` / `backtest` / `confirmatory_validation`，且每个 dataset ref 都有 `known_at_ref` / `effective_at_ref` / `pit_bitemporal_rules_ref`。

## 上下文 / 动机 [按需]
`4b6f55dc` 已阻止 Agent strategy synthesis 在没有 MarketDataUse refs 时读样本和产 run，但该 gate 还没有要求 DatasetSemantics timing refs。GOAL §10/§11 要求回测 estimator 绑定 event time / availability time / effective time；`backtest.run` 是真实回测入口，不能停在 accepted/no-violation。

## 接线点（file:line，实现时复核）[必填]
| 文件 | 改什么 |
|---|---|
| `app/backend/app/agent/business_tools.py` | `_synth_and_promote` 调 `_market_data_use_validation_refs` 时开启 `require_dataset_timing=True` 并限制 allowed use contexts |
| `app/backend/tests/test_ds1_run_id_spine.py` | MarketDataUse registry fake 增加 DatasetSemantics；新增缺 PIT timing no-write case |
| `app/backend/tests/test_delivery_slice_e2e.py` | delivery slice fake use_context 同步为 `backtest`，并补 DatasetSemantics timing fake |

## 对抗测试设计（种已知 bug，门必抓）[必填]
1. 缺 refs 时仍在 LLM/codegen/sample/sandbox 前 no-write。
2. unknown/rejected/violation refs 不创建 run artifacts。
3. accepted 但 DatasetSemantics 缺 `pit_bitemporal_rules_ref` 时 no-write，不创建 run artifacts。
4. 正常 DS-1 合成回测仍产真 run，并可被 `project_verdict` / `project_overfit` 消费。

## 红线 [按需]
- 不把 refs-only PIT gate 说成已证明 sandbox 策略逐行消费每条原始行情 row。
- 不把 Agent template synthesis 说成完整 strategy assembly injection。
- 不把本地 pytest 结果说成 CI。

## 非目标 [按需]
不实现完整 strategy codegen、factor/model/signal assembly injection、真实 provider 实网连通或线上回测集群。

## 验收一句话 [必填]
Agent `backtest.run` 真实合成回测现在必须先带 accepted 且具备 PIT/bitemporal timing refs 的 MarketDataUse refs，才会进入 LLM/codegen/sample/sandbox/promote。

## 完成记录（2026-06-27）
- `_synth_and_promote` strategy synthesis gate 开启 DatasetSemantics PIT/bitemporal timing refs 校验。
- delivery slice、DS-1 和 DS-2 测试替身同步真实 timing contract；DS2 旧 `strategy_goal_to_backtest` fake context 改为正式 `backtest`，并补 `dataset()` timing refs。
- 本地验证：
  - `python -m pytest app/backend/tests/test_ds1_run_id_spine.py -q` -> 16 passed。
  - `python -m pytest app/backend/tests/test_ds2_strategy_goal_persist.py -q` -> 8 passed / 2 warnings。
  - `python -m pytest app/backend/tests/test_ds1_run_id_spine.py app/backend/tests/test_ds2_strategy_goal_persist.py app/backend/tests/test_agent_business_tools_a4.py app/backend/tests/test_agent_tool_status.py app/backend/tests/test_delivery_slice_e2e.py app/backend/tests/test_chat_conversations.py app/backend/tests/test_agent_runtime_research_graph.py app/backend/tests/test_run_verdict_card.py app/backend/tests/test_goal_coverage.py app/backend/tests/test_market_data_contract.py -q` -> 145 passed / 2 warnings。
  - `python -m pytest app/backend/tests -q` -> 1831 passed / 13 skipped / 283 warnings。
  - `python -m compileall -q app/backend/app` -> PASS。
  - `python dev/scripts/validate_dev.py` -> PASS（49 ✅ / 0 ❌ / 0 ⚠️）。
  - `git diff --check` -> PASS。
