---
uuid: 48f70fa3e9af4caebdffca604ea3df6f
title: Factor layered backtests require MarketDataUse PIT refs before BacktestRun evidence
status: done
owner: dreaminate
assigned_by: dreaminate
review_status: 1
priority: P1
area: factor-layered-backtest-market-data-pit-coverage
source: goal-gap
source_ref: GOAL §9/§10/§11/§14 factor layered backtest timing/PIT gate and BacktestRun QRO coverage
depends_on: [84c728cb7ed74e63b7194b791ebd7eac, ed548b5cd527410fb2227acc1acd1c73, 5d93d82e6e844f7db3403931c62054d8]
completed_at: 2026-06-27
---

# Factor layered backtests require MarketDataUse PIT refs before BacktestRun evidence

## Scope [必填]
把 `POST /api/factors/{factor_id}/layered_backtest` 从“可直接产分层诊断 BacktestRun QRO”改成先要求 accepted/no-violation `MarketDataUseValidationRecord` refs；refs 必须面向 backtest/confirmatory validation，引用的 DatasetSemantics 必须有 `known_at_ref`、`effective_at_ref`、`pit_bitemporal_rules_ref`，CapabilityMatrix 必须允许 backtest，Instrument/Capability asset_class 必须覆盖当前 market。成功后 BacktestRun QRO、Research Graph、Compiler IR/pass 和 GOAL entrypoint coverage 记录这些 refs。

## 上下文 / 动机 [按需]
`84c728cb` 已把 factor layered backtest 接成 BacktestRun QRO/compiler/coverage，但它仍属于“其他回测入口”：请求没有先绑定 MarketDataUse/PIT refs。GOAL §9/§11 要求 backtest producer 与双时态数据证据绑定，§14 要求入口 coverage 不能只记录 report hash。

## 接线点（file:line，实现时复核）[必填]
| 文件 | 改什么 |
|---|---|
| `app/backend/app/main.py` | 新增 `_factor_layered_market_data_use_validation_refs`；`factor_layered_backtest` 在运行 layered diagnostic 前校验 refs；`_record_factor_layered_backtest_qro` 把 refs 写入 QRO input/output、lineage、evidence refs 和 compiler validation refs |
| `app/backend/tests/test_factor_desk_f2.py` | 隔离 MarketData registry fixture；正常路径传 deduped refs；新增缺 refs、unknown refs、unaccepted/violation 历史脏账、market mismatch、PIT timing 缺失、invalid quantiles no-partial 断言 |

## 对抗测试设计（种已知 bug，门必抓）[必填]
1. 缺 `market_data_use_validation_refs` 时 422，且不写 Graph/Compiler/Coverage partial record。
2. unknown ref 时 422，且不写 partial record。
3. 历史脏账中未 accepted 或带 violation 的 ref 必须 fail-closed。
4. ref 的 instrument/capability asset_class 不覆盖请求 market 时 422。
5. ref 引用的 DatasetSemantics 缺 `known_at_ref` / `effective_at_ref` / `pit_bitemporal_rules_ref` 时 422。
6. 成功路径返回 deduped refs，并能从 QRO/Compiler IR 回查同一 refs；QRO/Compiler 不保存公式原文、bucket mean returns、long-short spread 或 raw returns。
7. refs 通过后，如果 `n_quantiles < 2` 仍 422 且不写 partial record。

## 红线 [按需]
- 不把 MarketDataUse refs 说成 factor layered diagnostic 已逐行消费真实行情 rows。
- 不把分层诊断 BacktestRun 说成 alpha approval、cost-aware strategy performance、portfolio promotion 或 execution permission。
- 不把本地 pytest 结果说成 CI、线上或用户验收。

## 非目标 [按需]
不实现正式报告全域 MarketDataUse gate、所有 backtest/report consumer 全域收口、真实 provider 实网连通、alpha approval、strategy promotion、组合构建或 live execution。

## 验收一句话 [必填]
factor layered backtest 现在必须先拿到覆盖当前 market 且具备 PIT/known/effective refs 的 accepted MarketDataUse validation，才会产 BacktestRun QRO/Graph/Compiler/Coverage。

## 完成记录（2026-06-27）
- `POST /api/factors/{factor_id}/layered_backtest` 新增 MarketDataUse/PIT hard gate。
- BacktestRun QRO input/output、evidence refs、lineage、Compiler IR validation refs 均记录 `market_data_use_validation_refs`。
- 本地验证：
  - `python -m compileall -q app/backend/app` -> PASS。
  - `pytest app/backend/tests/test_factor_desk_f2.py -q` -> 35 passed / 2 warnings。
  - `pytest app/backend/tests/test_factor_desk_f2.py app/backend/tests/test_factor_strategy_boundary.py app/backend/tests/test_market_data_contract.py app/backend/tests/test_goal_coverage.py app/backend/tests/test_governed_compiler.py app/backend/tests/test_strategy_console_s2.py app/backend/tests/test_portfolio_promote_api.py -q` -> 155 passed / 2 warnings。
  - `pytest app/backend/tests -q` -> 1809 passed / 13 skipped / 283 warnings。
