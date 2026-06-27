---
uuid: 4056a87fd1064539b9272c679f017990
title: Agent API IDE QRO producers compile into entrypoint coverage
status: done
owner: dreaminate
assigned_by: dreaminate
review_status: 1
priority: P1
area: research-os-entrypoint-compiler-coverage
source: goal-gap
source_ref: GOAL §0/§1/§7/§8/§9/§14/§16 Agent/API/IDE QRO -> Graph -> Compiler -> Coverage
depends_on: [5937228569cf41298c7724f2c937f34a, b32dbcd8fb7e4ec6911c33290f5f0e09, b1b48097341547f09d84b6509acf778f, a2a5b61bf5e245cd8179f4fd6854d7ce, 18bb49e730a3488199892f3b31eef6d5, 4f4eab2a60344f47bcdd70de71b10b17, 9d175460a9f24650964a250304c44d83, 173405ef47f942ba9929a4c356483d07]
completed_at: 2026-06-27
---

# Agent API IDE QRO producers compile into entrypoint coverage

## Scope [必填]
把已有 Agent Shell `strategy_goal.create`、direct `POST /api/strategy_goals`、IDE strategy save/run/promote/AI complete QRO producer 接到 Governed Compiler IR/pass 和 GOAL entrypoint coverage；不实现完整 compiler pass、strategy code generator、CI、线上部署或所有剩余入口。

## 上下文 / 动机 [按需]
`59372285` / `b32dbcd8` / `b1b48097` / `a2a5b61b` / `18bb49e7` / `4f4eab2a` 已让这些入口写 QuantIntent、StrategyBook、BacktestRun 和 LLMCallRecord QRO。`9d175460` 和 `173405ef` 已有 compiler/coverage 基建。GOAL §0/§1/§7/§8 的当前缺口是这些高频入口不能停在 QRO/Graph，必须成功后自动生成 refs-only compiler IR/pass/entrypoint coverage。

## 接线点（file:line，实现时复核）[必填]
| 文件 | 改什么 |
|---|---|
| `app/backend/app/main.py` | 新增 `_compile_entrypoint_qro` 和 `_create_strategy_goal_with_compiler_coverage`；Agent runtime 与 direct StrategyGoal API 改走同一 compiler-aware helper；IDE save/run/promote/AI complete QRO helper 写 Graph 后自动 compile/coverage |
| `app/backend/tests/test_ds2_strategy_goal_persist.py` | 隔离 compiler/coverage stores；断言 direct API StrategyGoal coverage 绑定 QuantIntent QRO / Graph command 且不泄露自然语言/secret |
| `app/backend/tests/test_agent_runtime_research_graph.py` | 断言 Agent Shell `strategy_goal.create` 生成 agent_shell entrypoint coverage |
| `app/backend/tests/test_strategy_console_s2.py` | 隔离 compiler/coverage stores；断言 IDE save/run/failed-run/promote/AI complete 返回 compiler/coverage refs，并验证 compiler audit 不含 source/prompt/output/result secret |

## 对抗测试设计（种已知 bug，门必抓）[必填]
1. Direct StrategyGoal API 成功后必须返回 `compiler_ir_ref`、`compiler_pass_ref`、`entrypoint_coverage_ref`，coverage entrypoint 是 `api:strategy_goals`。
2. Agent Shell `strategy_goal.create` 成功后必须写 `agent_shell:strategy_goal.create` coverage。
3. IDE strategy save/run/promote/AI complete 成功路径必须返回 compiler/coverage refs，coverage entrypoint 分别是 `ide:strategy.save`、`ide:strategy.run`、`ide:run.promote`、`ide:ai_complete`。
4. IDE failed sandbox run 既保留 failed BacktestRun QRO，也写 `ide:strategy.run` coverage，不把 stderr/raw result 写进 compiler audit。
5. Compiler IR/pass/coverage 不得复制 StrategyGoal prompt、IDE code、description、stdout/stderr、result keys、LLM prompt/context/output、trade payload 或 secret markers。

## 红线 [按需]
- 不把 refs-only compiler coverage 说成完整 compiler implementation、策略代码生成、数学全链闭合、CI 通过、线上可用或用户验收。
- 不把 IDE save/run/promote/AI complete 的 MarketDataUse refs 说成真实数据行已被 sandbox 消费。
- 不把 Agent Shell step QRO 全部 claims 成已自动 compile；本卡只接 `strategy_goal.create` 业务 QRO。

## 非目标 [按需]
不做 Canvas/Chat step 全自动 compile、其他 API/scheduler、factor/model/signal/portfolio/execution 入口、真实 external publish target、operation-level replay/revert、完整参数 schema 或线上验证。

## 验收一句话 [必填]
Agent/API/IDE 的 StrategyGoal、StrategyBook、BacktestRun 和 LLMCallRecord QRO 成功路径现在都会自动生成 governed compiler IR/pass 与 GOAL entrypoint coverage，审计对象只保留 refs/hash，不复制 raw prompt/code/result/secret。

## 完成记录（2026-06-27）
- 新增 `_compile_entrypoint_qro`，复用 `_compile_qro_payload`、compiler store 和 coverage registry。
- Agent Shell `strategy_goal.create` 与 direct `POST /api/strategy_goals` 改走 `_create_strategy_goal_with_compiler_coverage`。
- IDE save/run/promote/AI complete QRO helper 写 Research Graph 后自动 compile/coverage，并把 refs 返回到 HTTP response。
- 本地验证：
  - `pytest app/backend/tests/test_ds2_strategy_goal_persist.py app/backend/tests/test_agent_runtime_research_graph.py app/backend/tests/test_strategy_console_s2.py -q` -> 58 passed / 2 warnings。
  - `python -m compileall -q app/backend/app` -> PASS。
