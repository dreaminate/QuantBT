---
uuid: 4c0d9e1f2d7043fd950a7c35e8a42a6b
title: Model prediction emits typed signal contract
status: done
owner: dreaminate
assigned_by: dreaminate
review_status: 1
priority: P1
area: research-os-factor-signal-boundary
source: goal-gap
source_ref: GOAL §9 model output to signal contract semantics
depends_on: [0f6a1d2e7c884f18a3e0cbb8b521aa49]
completed_at: 2026-06-27
---

# Model prediction emits typed signal contract

## Scope [必填]
把 governed model prediction seam 接到 §9 Signal Contract 边界：`/api/models/{model_id}/versions/{version}/predict` 支持可选 `signal_contract` payload，只有在 OOF/purge/embargo、train/test lock、honest-N、forecast time、horizon、unit、direction semantics、confidence、expiry refs 全部存在时才登记 `SignalContractRegistry` 并返回 `signal_ref`。

## 上下文 / 动机 [按需]
`0f6a1d2e` 已能在 staging/production 模型上做受控本地预测，但模型输出仍只是数值数组。GOAL §9 要求模型输出进入明确 forecast/signal contract，并带时间、单位、方向、置信度、过期等语义。本卡补这条接线；不把模型本体塞进因子库，也不绕开既有 R17/R18 信号门。

## 接线点（file:line，实现时复核）[必填]
| 文件 | 改什么 |
|---|---|
| `app/backend/app/research_os/factor_strategy_boundary.py` | `SignalProtocolRecord` 新增 forecast/horizon/unit/direction/confidence/expiry refs，并在 validator 中强制模型信号具备这些 typed semantics |
| `app/backend/app/main.py` | `/api/models/{model_id}/versions/{version}/predict` 可选登记 signal contract，先通过 `validate_signal_protocol` 再写 `SIGNAL_CONTRACTS` |
| `app/backend/tests/test_factor_strategy_boundary.py` | 覆盖 typed signal semantics 缺失会被 boundary validator 拒绝 |
| `app/backend/tests/test_model_governance.py` | 覆盖 prediction 成功登记 signal contract，缺 expiry/direction 等 typed refs 时 422 且不写 serving invocation |

## 对抗测试设计（种已知 bug，门必抓）[必填]
1. 模型信号缺 `expires_at_ref` 或 `direction_semantics_ref` 必须拒绝。
2. `/predict` 传 incomplete `signal_contract` 必须 422，不能写 serving invocation。
3. `/predict` 成功登记的 `signal_ref` 必须出现在 `/api/factors/signal_contracts`。
4. 信号登记仍走既有 `SignalContractRegistry`，model_ref 回指模型 artifact，本体不能直接进因子库。

## 红线 [按需]
- 不允许把模型本体当因子库条目。
- 不允许缺 OOF/purge/embargo/lock/honest-N 就登记模型信号。
- 不允许缺 forecast time、horizon、unit、direction、confidence、expiry 语义就登记模型信号。
- 不允许把 signal contract 登记说成 alpha 有效或可交易。

## 非目标 [按需]
不实现自动 portfolio construction，不实现 order emission，不实现 signal performance validation，不实现 live trading，不实现持久化 SignalContractRegistry。

## 验收一句话 [必填]
模型预测入口可在完整 typed signal semantics 存在时登记 `signal_ref`；缺任何关键语义会 422，且不写 serving invocation 或假装信号可交易。

## 完成记录（2026-06-27）
- `SignalProtocolRecord` 增加 forecast time / horizon / unit / direction / confidence / expiry refs，并纳入 validator。
- `/api/models/{model_id}/versions/{version}/predict` 支持可选 `signal_contract`，通过 `validate_signal_protocol` 后登记 `SIGNAL_CONTRACTS` 并返回 `signal_ref`。
- 本地验证：
  - `python -m pytest app/backend/tests/test_factor_strategy_boundary.py -q` -> 8 passed。
  - `python -m pytest app/backend/tests/test_model_governance.py -q` -> 31 passed / 2 warnings。
  - `python -m pytest app/backend/tests/test_training_api.py app/backend/tests/test_training_service.py app/backend/tests/test_model_governance.py app/backend/tests/test_model_desk_m2.py app/backend/tests/test_factor_strategy_boundary.py app/backend/tests/test_research_graph_persistence.py app/backend/tests/test_agent_runtime_research_graph.py app/backend/tests/test_entrypoint_gate_coverage.py app/backend/tests/test_research_os_spine.py app/backend/tests/test_goal_coverage.py app/backend/tests/test_platform_coverage.py app/backend/tests/test_engineering_standards.py -q` -> 147 passed / 2 warnings。
  - `python -m compileall app/backend/app` -> PASS。
  - `python dev/scripts/validate_dev.py` -> 49 ✅ / 0 ❌ / 0 ⚠️；DAG 153 卡。
