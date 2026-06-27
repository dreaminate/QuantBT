---
uuid: 03dcb87d8dc3431184e0644cb19c9833
title: Training jobs require MarketDataUse validation refs
status: done
owner: dreaminate
assigned_by: dreaminate
review_status: 1
priority: P1
area: training-market-data-pit-gate
source: goal-gap
source_ref: GOAL §9/§11/§15 estimator data timing/PIT gate for training jobs
depends_on: [e65a6e9664d94103bcab30cf9ebd0996, ed548b5cd527410fb2227acc1acd1c73, 54b60744f2564ecc8fd9ef8733b26810, aeb7832ae0f84d0198ec5e2f4762baf0]
completed_at: 2026-06-27
---

# Training jobs require MarketDataUse validation refs

## Scope [必填]
把 `/api/training/jobs` 从“dataset_id 可直接训练”改成必须引用 accepted/no-violation `MarketDataUseValidationRecord`，且 refs 必须覆盖训练 dataset。训练成功后的 request、ValidationDossier、Model QRO、Research Graph、Compiler IR/pass 和 GOAL entrypoint coverage 都记录 refs。训练台前端提供 refs 输入并随 submit payload 下发。

## 上下文 / 动机 [按需]
GOAL §9 明确 `estimator 未绑定 data timing/PIT -> 拒`，§11 明确无 PIT 语义的数据不得进入 confirmatory validation。此前 Settings/MarketDataUse 已能生成 accepted refs，训练成功路径也已有 Model QRO/compiler/coverage，但训练 submit 本身还没有把 dataset 与 MarketDataUse/PIT refs 绑定成硬门。

## 接线点（file:line，实现时复核）[必填]
| 文件 | 改什么 |
|---|---|
| `app/backend/app/main.py` | `training_submit` 先校验 `market_data_use_validation_refs`，要求 accepted/no-violation 且覆盖 `dataset_id`；训练 QRO/compiler 输入/输出/lineage/validation refs 记录这些 refs |
| `app/backend/app/training/service.py` | `TrainingRequest` 增加 `market_data_use_validation_refs`；ValidationDossier 记录 refs |
| `app/backend/tests/conftest.py` | 增加 training MarketDataUse fixture，构造 DatasetSemantics/Instrument/Capability/accepted MarketDataUseValidation |
| `app/backend/tests/test_training_api.py` | 覆盖缺 refs 422、成功训练返回 refs、QRO/compiler/coverage 保存 refs且不泄漏 metrics/artifact payload |
| `app/backend/tests/test_backtest_bridge.py` / `test_model_desk_m2.py` / `test_model_eval.py` | 现有训练 API 调用补 accepted refs，防止测试绕过新硬门 |
| `app/frontend/src/pages/models/TrainingBenchPage.tsx` | 训练台新增 MarketDataUse refs 输入，拆分去重后随 submit payload 下发；无 refs 时禁用提交 |
| `app/frontend/src/pages/models/TrainingBenchPage.test.tsx` | 断言训练台提交 payload 带去重后的 refs |

## 对抗测试设计（种已知 bug，门必抓）[必填]
1. 训练 submit 缺 `market_data_use_validation_refs` 必须 422，不能创建 job。
2. refs unknown、未 accepted、带 violation 或不覆盖 `dataset_id` 必须 fail-closed。
3. 成功训练的 `TrainingJob.request`、ValidationDossier、QRO input/output contract、Compiler IR validation refs 必须带同一组 refs。
4. QRO/Compiler/coverage 不得保存 metrics 明细、artifact path、artifact dir 或模型二进制路径。
5. 前端训练台 submit payload 必须包含用户输入 refs，并去重。

## 红线 [按需]
- 不把 MarketDataUse validation 说成真实行情 rows 已被 sandbox code 消费。
- 不把训练 submit refs 绑定说成所有 report/backtest/data consumer 已全域 PIT 闭合。
- 不把本地 pytest/npm 结果说成 CI、线上或用户验收。

## 非目标 [按需]
不实现完整数据 provider 实网连通、自动 MarketDataUse ref 发现、所有 backtest/report consumer 的全域 PIT gate、真实线上训练集群、runtime auto-promotion、真实 broker/venue order。

## 验收一句话 [必填]
训练入口现在必须引用覆盖训练 dataset 的 accepted MarketDataUse validation refs；成功训练的 request、dossier、QRO、Graph、Compiler 与 coverage 都保留 refs-only 证据，训练台 UI 也会提交这些 refs。

## 完成记录（2026-06-27）
- `POST /api/training/jobs` 新增 MarketDataUse validation refs 硬门：缺 refs、空 ref、unknown ref、未 accepted、violation 或 dataset 不覆盖均拒绝。
- `TrainingRequest` / ValidationDossier / training Model QRO / Compiler IR-pass / GOAL entrypoint coverage 绑定 `market_data_use_validation_refs`。
- 训练台新增 MarketDataUse refs 输入；submit payload 携带去重 refs，无 refs 时不允许提交。
- 本地验证：
  - `python -m compileall -q app/backend/app` -> PASS。
  - `pytest app/backend/tests/test_training_api.py app/backend/tests/test_training_service.py app/backend/tests/test_backtest_bridge.py app/backend/tests/test_model_desk_m2.py app/backend/tests/test_model_eval.py -q` -> 70 passed / 2 warnings。
  - `pytest app/backend/tests/test_model_governance.py app/backend/tests/test_market_data_contract.py app/backend/tests/test_goal_coverage.py app/backend/tests/test_governed_compiler.py app/backend/tests/test_research_os_spine.py app/backend/tests/test_ds1_run_id_spine.py app/backend/tests/test_ds2_strategy_goal_persist.py app/backend/tests/test_factor_strategy_boundary.py app/backend/tests/test_portfolio_promote_api.py -q` -> 145 passed / 2 warnings。
  - `pytest app/backend/tests -q` -> 1805 passed / 13 skipped / 283 warnings。
  - `npm run test:run -- TrainingBenchPage.test.tsx` -> 1 passed。
  - `npm run test:run -- TrainingBenchPage.test.tsx modelApi.test.tsx modelDesk.test.tsx` -> 3 files / 25 tests passed。
  - `npm run test:run` -> 28 files / 307 tests passed。
  - `npm run build` -> `tsc && vite build` PASS。
