---
uuid: 2b9b76fbbecf468598e0b2f7d43bb075
title: Training job backtests require MarketDataUse refs and compile into coverage
status: done
owner: dreaminate
assigned_by: dreaminate
review_status: 1
priority: P1
area: training-backtest-market-data-pit-coverage
source: goal-gap
source_ref: GOAL §9/§10/§11/§14 training backtest dataset timing/PIT gate and BacktestRun QRO coverage
depends_on: [03dcb87d8dc3431184e0644cb19c9833, 54b60744f2564ecc8fd9ef8733b26810, ed548b5cd527410fb2227acc1acd1c73, 173405ef47f942ba9929a4c356483d07, 9d175460a9f24650964a250304c44d83]
completed_at: 2026-06-27
---

# Training job backtests require MarketDataUse refs and compile into coverage

## Scope [必填]
把 `/api/training/jobs/{job_id}/backtest` 从“训练成功后可直接回测任意内置 dataset”改成回测 dataset 也必须被 accepted/no-violation `MarketDataUseValidationRecord` 覆盖；同时把回测结果登记为 refs/hash-only `BacktestRun` QRO，并接入 Research Graph、Governed Compiler IR/pass 和 GOAL entrypoint coverage。训练台前端评价面板提供 backtest refs 输入，跨集回测可显式传 refs。

## 上下文 / 动机 [按需]
`03dcb87d` 已让训练提交绑定 data timing/PIT refs，但训练后的回测端点仍可换 `dataset_id` 做跨集 OOS，而没有校验回测 dataset 自身的 MarketDataUse refs，也没有把这个 backtest evidence 写入 QRO/Graph/Compiler/Coverage。GOAL §9/§11 要求 estimator/backtest 与 data timing/PIT 绑定，§14 要求入口级 coverage。

## 接线点（file:line，实现时复核）[必填]
| 文件 | 改什么 |
|---|---|
| `app/backend/app/main.py` | `_training_market_data_use_validation_refs` 支持 fallback refs + dataset label；`training_job_backtest` 校验回测 dataset refs；新增 `_record_training_job_backtest_qro` 写 BacktestRun QRO/Graph/compiler/coverage |
| `app/backend/tests/conftest.py` | 增加可在同一 temporary MarketData registry 内登记多个 training/backtest dataset refs 的 fixture |
| `app/backend/tests/test_backtest_bridge.py` | 断言同集回测继承训练 refs；跨集回测缺覆盖 refs 时 422；成功回测返回 BacktestRun/Graph/compiler/coverage refs，QRO 不保存 raw metrics/equity/artifact path |
| `app/frontend/src/pages/models/TrainingBenchPage.tsx` | 评价图面板新增 backtest MarketDataUse refs 输入，回测 payload 显式传 refs |
| `app/frontend/src/pages/models/TrainingBenchPage.test.tsx` | 断言训练台回测 POST payload 带去重后的 backtest refs |

## 对抗测试设计（种已知 bug，门必抓）[必填]
1. 同 dataset 回测可以继承训练 job request 内的 accepted refs。
2. 跨 dataset 回测如果只继承训练 dataset refs，必须 422，错误指出 refs 不覆盖 backtest dataset。
3. 跨 dataset 回测显式传覆盖目标 dataset 的 accepted refs 才能成功。
4. 成功回测必须返回 `backtest_run_ref`、`qro_id`、`research_graph_command_id`、`compiler_ir_ref`、`compiler_pass_ref`、`entrypoint_coverage_ref`。
5. BacktestRun QRO/Compiler 只保存 refs/hash/count，不保存 raw `metrics`、`equity_curve`、`artifact_dir` 或 `artifact_path`。

## 红线 [按需]
- 不把 MarketDataUse refs 说成真实行情 rows 已被模型/回测代码逐行消费。
- 不把训练 job backtest QRO 说成 alpha proof、promotion approval、live serving readiness 或 execution permission。
- 不把本地 pytest/npm 结果说成 CI、线上或用户验收。

## 非目标 [按需]
不实现完整交易成本模型、CPCV/conformal/TCA 计算器、所有 backtest/report consumer 全域 gate、真实 provider 实网连通、线上训练/回测集群、runtime auto-promotion 或 live order path。

## 验收一句话 [必填]
训练 job 回测入口现在要求 refs 覆盖回测 dataset，跨集 OOS 不再能拿训练集 refs 混过；成功回测会生成 refs/hash-only BacktestRun QRO、Research Graph command、compiler IR/pass 与 GOAL entrypoint coverage。

## 完成记录（2026-06-27）
- `POST /api/training/jobs/{job_id}/backtest` 复用训练 refs 作为同集 fallback；跨集回测必须显式提供覆盖回测 dataset 的 accepted/no-violation refs。
- 新增 `_record_training_job_backtest_qro`，成功回测写 BacktestRun QRO、Research Graph command、compiler IR/pass 和 `api:training.jobs.backtest` coverage。
- 训练台评价面板新增 backtest refs 输入，payload 按空白/逗号拆分去重。
- 本地验证：
  - `python -m compileall -q app/backend/app` -> PASS。
  - `pytest app/backend/tests/test_backtest_bridge.py app/backend/tests/test_training_api.py -q` -> 29 passed / 2 warnings。
  - `pytest app/backend/tests/test_backtest_bridge.py app/backend/tests/test_training_api.py app/backend/tests/test_training_service.py app/backend/tests/test_model_governance.py app/backend/tests/test_market_data_contract.py app/backend/tests/test_goal_coverage.py app/backend/tests/test_governed_compiler.py app/backend/tests/test_research_os_spine.py -q` -> 138 passed / 2 warnings。
  - `pytest app/backend/tests -q` -> 1805 passed / 13 skipped / 283 warnings。
  - `npm run test:run -- TrainingBenchPage.test.tsx` -> 1 file / 2 tests passed。
  - `npm run test:run -- TrainingBenchPage.test.tsx modelApi.test.tsx modelDesk.test.tsx` -> 3 files / 26 tests passed。
  - `npm run test:run` -> 28 files / 308 tests passed。
  - `npm run build` -> `tsc && vite build` PASS。
