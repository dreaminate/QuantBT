---
uuid: 4b6f55dccf2748b692ebe43493979eff
title: Agent strategy synthesis requires MarketDataUse validation
status: done
owner: dreaminate
assigned_by: dreaminate
review_status: 0
priority: P1
area: research-os-entrypoint-wiring
source: goal-gap
source_ref: GOAL §11 market data use gate -> Agent backtest.run strategy synthesis entrypoint
depends_on: [e29078914b9a448ba631837c548a4a16, 84b1d0c60c2648bbb7a1436f1d151f93]
completed_at: 2026-06-27
---

# Agent strategy synthesis requires MarketDataUse validation

## Scope [必填]
让 Agent business tool `backtest.run` 的 strategy synthesis 分支（`_synth_and_promote`）在 LLM/code synthesis、sample read、sandbox run、promote 落盘之前强制要求 accepted/no-violation `market_data_use_validation_refs`。缺 refs、unknown ref、未 accepted ref 或 violation ref 都必须 fail-closed，且不调用 LLM、不创建 run artifacts、不落 `RUN_ROOT`。

## 上下文 / 动机 [按需]
IDE save/run 已接 MarketDataUse gate，但 Agent 的陌生人 chat→backtest 入口仍能从 StrategyGoal/组装意图合成策略并跑 sandbox。这个路径是实际 strategy builder：它会生成策略代码、读取捆绑样本、promote 成 run。如果不先引用 accepted MarketDataUse validation，就会绕过 §11 数据使用门。

## 接线点（file:line，实现时复核）[必填]
| 文件 | 改什么 |
|---|---|
| `app/backend/app/agent/business_tools.py` | `_synth_and_promote` 开头校验 `market_data_use_validation_refs`；`register_business_tools` 注入 `market_data_registry`；成功响应返回 refs |
| `app/backend/app/main.py` | `_agent_runtime` 注册 business tools 时传入 `MARKET_DATA_REGISTRY` |
| `app/backend/app/agent/tool_schema.py` | `backtest.run` schema 声明 `market_data_use_validation_refs` 必填 |
| `app/backend/tests/test_ds1_run_id_spine.py` | 覆盖缺 ref、unknown、unaccepted、violation ref no-write；正向 DS-1 路径带 accepted refs |
| `app/backend/tests/test_ds2_strategy_goal_persist.py` / `app/backend/tests/test_delivery_slice_e2e.py` | chat→goal→backtest 与 delivery e2e 带 accepted refs |
| `dev/state/dreaminate/state.md` / `dev/research/TRACE.md` / `dev/log/dreaminate/log.md` | 落档本地证据与边界 |

## 对抗测试设计（种已知 bug，门必抓）[必填]
1. Agent `backtest.run` 缺 `market_data_use_validation_refs` -> 返回 error/no_write，不调用 LLM/code synthesis，不创建 run artifacts。
2. Agent `backtest.run` 引用 unknown MarketDataUse validation -> error/no_write，不创建 run artifacts。
3. Agent `backtest.run` 引用 `accepted=false` validation -> error/no_write，不创建 run artifacts。
4. Agent `backtest.run` 引用 `accepted=true` 但带 `violation_codes` validation -> error/no_write，不创建 run artifacts。
5. Agent `backtest.run` 引用 accepted/no-violation validation -> 合成、sandbox、promote 成真 run，响应返回 refs。

## 红线 [按需]
- 不触网、不拉行情、不生成或发送真实 order。
- 不把 MarketDataUse validation 说成真实 connector、live permission 或 sandbox code 对数据行消费的强证明。
- 不改变旧 `run.json["assembly_inputs"]` shape；MarketDataUse refs 不塞进 assembly metadata。

## 非目标 [按需]
不实现真实 connector、行情下载、live provider permission proof、真实 venue permission check、order emission、完整 strategy code generator、自动组合注入或 sandbox code 对具体数据行的强证明。

## 验收一句话 [必填]
Agent `backtest.run` strategy synthesis 必须先引用 accepted/no-violation MarketDataUse validation；否则 fail-closed 且不发生 LLM/codegen/sample/sandbox/run artifact 副作用。

## 完成记录
- `_synth_and_promote` 新增 `market_data_use_validation_refs` hard gate；缺 refs、非 list/string、空 refs、unknown ref、未 accepted ref、validation 带 violation 均返回 error/no_write。
- gate 早于 LLM/code synthesis、sample read、sandbox run 和 promote；缺 refs 测试证明 LLM `complete()` 未被调用，且不创建 `artifacts/experiments`。
- `_agent_runtime` 把 `MARKET_DATA_REGISTRY` 注入 `register_business_tools`；`backtest.run` tool schema 声明 refs 必填。
- 正向 DS-1、DS-2 和 delivery-slice e2e 路径补 accepted refs，成功响应返回 `market_data_use_validation_refs`；旧 `run.json["assembly_inputs"]` shape 保持不变。
- 验证：DS-1/DS-2/delivery focused **26 passed / 2 warnings**；Agent/tool focused **38 passed / 2 warnings**；Agent/DS/Chat adjacent **97 passed / 2 warnings**；market-data/IDE/portfolio/execution adjacent **143 passed / 2 warnings**；`PYTHONPATH=app/backend python -m compileall -q app/backend/app` PASS。
- 边界：这是 Agent `backtest.run` strategy synthesis 的 refs-only MarketDataUse hard gate，不是真实 connector、行情下载、live provider permission proof、真实 venue permission check、order emission、完整 strategy code generator、自动组合注入或 sandbox code 对数据行消费的强证明。
