---
uuid: a00ed3d6bf2648f4b1299da0d3df1309
title: Signal and portfolio producers compile into entrypoint coverage
status: done
owner: dreaminate
assigned_by: dreaminate
review_status: 1
priority: P1
area: research-os-signal-portfolio-entrypoint-coverage
source: goal-gap
source_ref: GOAL §1/§8/§9/§14/§15 signal -> portfolio QRO -> Graph -> Compiler -> Coverage
depends_on: [c8e2f4a0d6bb4d75b6d8e0127f5e1a2c, b7c6d8a9ccce2a6a53904b97ab02303a, 2c9f4e11035a9911d9814c9ab8fb77a2, 5d93d82e6e844f7db3403931c62054d8, 173405ef47f942ba9929a4c356483d07, 9d175460a9f24650964a250304c44d83]
completed_at: 2026-06-27
---

# Signal and portfolio producers compile into entrypoint coverage

## Scope [必填]
把已有 SignalContract 登记、SignalPerformanceValidation 登记和 portfolio production promote gate 成功路径接到 Research Graph QRO、governed compiler IR/pass 和 GOAL entrypoint coverage。不改 signal alpha 计算、portfolio gate 算法、honest-N 账本语义、真实下单或 stage flip。

## 上下文 / 动机 [按需]
`c8e2f4a0` 已让 SignalContract 可持久化，`b7c6d8a9` 已让 SignalPerformanceValidation 可登记并被 StrategyBook gate 消费，`2c9f4e11` 已让 portfolio promote 强制 accepted signal validation。剩余缺口是这些入口只停在 registry/gate/honest-N，缺 QRO→Graph→Compiler→Coverage 的入口证据。

## 接线点（file:line，实现时复核）[必填]
| 文件 | 改什么 |
|---|---|
| `app/backend/app/main.py` | 新增 `_record_signal_contract_qro`、`_record_signal_validation_qro`、`_record_portfolio_promote_qro`；三个成功入口返回 `qro_id`、`research_graph_command_id`、`compiler_ir_ref`、`compiler_pass_ref`、`entrypoint_coverage_ref` |
| `app/backend/tests/test_factor_lab_endpoints.py` | SignalContract / SignalValidation 成功路径隔离 Graph/Compiler/Coverage store，并断言 entrypoint coverage 与 no raw payload |
| `app/backend/tests/test_portfolio_promote_api.py` | Portfolio promote 成功路径断言 PortfolioPolicy QRO、compiler coverage、honest-N 保持、收益序列不进 Graph/Compiler |

## 对抗测试设计（种已知 bug，门必抓）[必填]
1. SignalContract 成功响应必须返回 compiler/coverage refs，entrypoint 是 `api:factors.signal_contracts`。
2. SignalPerformanceValidation 成功响应必须返回 compiler/coverage refs，entrypoint 是 `api:research_os.signal_validations`。
3. Portfolio promote 成功响应必须返回 PortfolioPolicy QRO 与 compiler/coverage refs，entrypoint 是 `api:portfolios.promote`。
4. Compiler/coverage 只能保存 refs/hash/summary，不保存 raw predictions、raw returns、`asset_returns` 明细、模型本体路径或 secret marker。

## 红线 [按需]
- 不把 SignalContract 说成 alpha proof。
- 不把 SignalPerformanceValidation 说成 order emission proof。
- 不把 portfolio promote gate 说成 stage flip、真钱执行、venue order 或 live trading。
- 不把本地测试说成 CI、线上或用户验收。

## 非目标 [按需]
不做 signal alpha 计算器、自动组合构建、完整 model→forecast→signal→portfolio 全域 producer、execution 下单、CI、线上或用户验收。

## 验收一句话 [必填]
SignalContract、SignalPerformanceValidation 和 portfolio production promote gate 的成功路径现在都会生成 QRO/Research Graph command、governed compiler IR/pass 与 GOAL entrypoint coverage，且 raw predictions/returns 不进 Graph/Compiler。

## 完成记录（2026-06-27）
- `POST /api/factors/signal_contracts` 成功后写 Signal QRO，并生成 `api:factors.signal_contracts` coverage。
- `POST /api/research-os/signal_validations` 成功后写 Signal QRO，并生成 `api:research_os.signal_validations` coverage。
- `POST /api/portfolios/{portfolio_id}/promote` 成功后写 PortfolioPolicy QRO，并生成 `api:portfolios.promote` coverage；honest-N/gate 语义不变。
- 本地验证：
  - `python -m compileall -q app/backend/app` -> PASS。
  - `pytest app/backend/tests/test_factor_lab_endpoints.py app/backend/tests/test_portfolio_promote_api.py -q` -> 30 passed / 2 warnings。
  - `pytest app/backend/tests/test_factor_lab_endpoints.py app/backend/tests/test_factor_strategy_boundary.py app/backend/tests/test_portfolio_promote_api.py app/backend/tests/test_goal_coverage.py app/backend/tests/test_governed_compiler.py app/backend/tests/test_market_data_contract.py app/backend/tests/test_execution_boundary_contract.py -q` -> 174 passed / 2 warnings。
