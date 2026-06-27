---
uuid: 84c728cb7ed74e63b7194b791ebd7eac
title: Factor layered backtest producer compiles into entrypoint coverage
status: done
owner: dreaminate
assigned_by: dreaminate
review_status: 1
priority: P1
area: research-os-factor-entrypoint-coverage
source: goal-gap
source_ref: GOAL §1/§8/§9/§10/§14 Factor layered BacktestRun QRO -> Graph -> Compiler -> Coverage
depends_on: [67a5e97c681b41a3a92327cb10d0b629, b9c3dc4b68614d079801e750e3071fee, 173405ef47f942ba9929a4c356483d07, 9d175460a9f24650964a250304c44d83]
completed_at: 2026-06-27
---

# Factor layered backtest producer compiles into entrypoint coverage

## Scope [必填]
把 `POST /api/factors/{factor_id}/layered_backtest` 分层回测成功路径接到 BacktestRun QRO、Research Graph command、governed compiler IR/pass 和 GOAL entrypoint coverage。不改分层回测算法、forward-return 口径、FactorRegistry 或 promotion/execution 语义。

## 上下文 / 动机 [按需]
`67a5e97c` 已让因子注册进入 Factor QRO；`b9c3dc4b` 已让因子 audit 进入 ValidationDossier QRO。剩余缺口是 factor layered backtest 仍只返回诊断报告，没有把它作为 GOAL §9/§10 的 BacktestRun producer 写入统一链路。

## 接线点（file:line，实现时复核）[必填]
| 文件 | 改什么 |
|---|---|
| `app/backend/app/main.py` | 新增 `_record_factor_layered_backtest_qro`；`factor_layered_backtest` 成功后写 BacktestRun QRO，并返回 `backtest_run_ref`、QRO/Graph/compiler/coverage refs |
| `app/backend/tests/test_factor_desk_f2.py` | 分层回测成功路径隔离 Graph/Compiler/Coverage store；断言 `api:factors.layered_backtest` coverage、BacktestRun QRO、公式原文和 raw bucket/return payload 不进 Graph/Compiler；invalid quantiles 失败路径不写 partial record |

## 对抗测试设计（种已知 bug，门必抓）[必填]
1. 成功 layered backtest 必须返回 `qro_id`、`research_graph_command_id`、`compiler_ir_ref`、`compiler_pass_ref`、`entrypoint_coverage_ref`、`backtest_run_ref`。
2. Coverage entrypoint 必须是 `api:factors.layered_backtest`，QRO 类型必须是 `BacktestRun`。
3. QRO/Compiler 只能保存 formula hash、report hash、quantile/sample summary 和 refs，不保存公式原文、bucket mean returns、long-short spread、raw returns 或 secret marker。
4. `n_quantiles < 2` 必须 422，且不写 Graph/Compiler/Coverage partial record。

## 红线 [按需]
- 不把 layered diagnostic 说成 alpha approval。
- 不把 monotonic / long-short spread 说成 cost-aware strategy performance、portfolio promotion、runtime permission、order emission 或 live trading。
- 不把本地测试说成 CI、线上或用户验收。

## 非目标 [按需]
不做 factor correlation QRO、preview validate QRO、自动 signal contract、strategy assembly、portfolio construction、runtime promotion、真实下单、CI、线上或用户验收。

## 验收一句话 [必填]
`POST /api/factors/{factor_id}/layered_backtest` 成功后会生成 BacktestRun QRO、Research Graph command、governed compiler IR/pass 与 GOAL entrypoint coverage，且公式原文和 raw layered payload 不进入 Graph/Compiler。

## 完成记录（2026-06-27）
- 新增 `_record_factor_layered_backtest_qro`，只把 formula/report hash、quantile/sample summary 和 refs 写入 QRO/Compiler。
- `POST /api/factors/{factor_id}/layered_backtest` 成功响应新增 `backtest_run_ref`、QRO/Graph/compiler/coverage refs；endpoint 现在通过 `require_user_dependency` 记录真实 actor。
- `n_quantiles < 2` 失败路径保持 422，并新增 no partial Graph/Compiler/Coverage 断言。
- 本地验证：
  - `python -m compileall -q app/backend/app` -> PASS。
  - `pytest app/backend/tests/test_factor_desk_f2.py -q` -> 30 passed / 2 warnings。
  - `pytest app/backend/tests/test_factor_desk_f2.py app/backend/tests/test_factor_lab_endpoints.py app/backend/tests/test_factor_strategy_boundary.py app/backend/tests/test_portfolio_promote_api.py app/backend/tests/test_goal_coverage.py app/backend/tests/test_governed_compiler.py app/backend/tests/test_market_data_contract.py app/backend/tests/test_execution_boundary_contract.py -q` -> 204 passed / 2 warnings.
  - `pytest app/backend/tests -q` -> 1803 passed / 13 skipped / 283 warnings.
