---
uuid: 5d93d82e6e844f7db3403931c62054d8
title: Settings market data use and onboarding compile into entrypoint coverage
status: done
owner: dreaminate
assigned_by: dreaminate
review_status: 1
priority: P1
area: research-os-data-onboarding-entrypoint
source: goal-gap
source_ref: GOAL §1/§4/§7/§8/§11 Settings MarketDataUse and onboarding QRO -> Graph -> Compiler -> Coverage
depends_on: [e65a6e9664d94103bcab30cf9ebd0996, ce49ca21854f4d3e9861bb87d33f327a, 8ba1997f78de4699a74b477bb85a3924, 173405ef47f942ba9929a4c356483d07, 9d175460a9f24650964a250304c44d83]
completed_at: 2026-06-27
---

# Settings market data use and onboarding compile into entrypoint coverage

## Scope [必填]
把 Settings `market_data_use_validations` 和 `data_connector_onboarding_runs` 的成功路径接到 Governed Compiler 与 GOAL entrypoint coverage；不实现真实 provider 实网连通、下游 strategy auto-injection 或 venue execution。

## 上下文 / 动机 [按需]
`e65a6e96` 已让 Settings 自动生成 accepted `MarketDataUseValidationRecord` 与 MarketDataUse QRO；`ce49ca21` / `8ba1997f` 已让 Data Connector one-shot onboarding 串起 Settings 数据接入链路。GOAL §1/§7/§8 的下一层缺口是这些 Settings/data onboarding 入口必须继续进入 QRO -> Graph -> Compiler -> Coverage，而不是停在 QRO/Graph。

## 接线点（file:line，实现时复核）[必填]
| 文件 | 改什么 |
|---|---|
| `app/backend/app/main.py` | `_record_market_data_use_validation_qro` 写 Research Graph 后自动调用 `_compile_market_data_use_validation_qro`；one-shot onboarding 成功后为 `api:research_os.settings.data_connector_onboarding_runs` 生成单独 entrypoint coverage |
| `app/backend/tests/test_onboarding_gateway.py` | 隔离 compiler/coverage stores；断言 direct MarketDataUse 和 one-shot onboarding coverage 绑定同一 QRO/Graph command，且不复制 raw rows / symbol / secret |
| `app/frontend/src/pages/SettingsSecurityPage.test.tsx` | 同步 one-shot response `compiler_coverage` step count |
| `dev/state/dreaminate/state.md` / `dev/research/TRACE.md` / `dev/log/dreaminate/log.md` | 落档 Settings data onboarding compiler coverage 和剩余边界 |

## 对抗测试设计（种已知 bug，门必抓）[必填]
1. Direct MarketDataUseValidation 成功后必须返回 `compiler_ir_ref`、`compiler_pass_ref`、`entrypoint_coverage_ref`，coverage entrypoint 是 `api:research_os.settings.market_data_use_validations`。
2. One-shot onboarding 成功后必须追加 `compiler_coverage` step，并返回顶层 compiler/coverage refs，coverage entrypoint 是 `api:research_os.settings.data_connector_onboarding_runs`。
3. Direct 和 one-shot coverage 都必须绑定最终 MarketDataUse QRO 与 Research Graph command。
4. Compiler/coverage audit 不得复制 raw row value、instrument symbol、plaintext secret、strategy builder payload 或 venue payload。

## 红线 [按需]
- 不把 accepted MarketDataUseValidation 说成真实 connector 已全资产同步、下游策略已消费、venue 权限已通过或线上已运行。
- 不把 one-shot fake checker/runner proof 说成外部 provider 实网连通。
- 不把 raw data rows、schema rows、secret、strategy source 或 venue payload 放进 compiler/coverage。

## 非目标 [按需]
不做完整 provider catalog、OAuth/device-code/account auth、生产 scheduler、全资产自动同步、strategy auto-injection、venue execution、CI 或线上验收。

## 验收一句话 [必填]
Settings MarketDataUseValidation 和 Data Connector one-shot onboarding 成功路径现在都会自动生成 governed compiler IR/pass 与 GOAL entrypoint coverage；失败路径仍 fail-closed，不泄露 raw rows 或 secret。

## 完成记录（2026-06-27）
- 新增 `_compile_market_data_use_validation_qro`，复用 `_compile_qro_payload`、compiler store 和 coverage registry。
- `POST /api/research-os/settings/market_data_use_validations` 返回 compiler/coverage refs。
- `POST /api/research-os/settings/data_connector_onboarding_runs` 返回 one-shot 顶层 compiler/coverage refs，并在 `completed_steps` 追加 `compiler_coverage`。
- 本地验证：
  - `pytest app/backend/tests/test_onboarding_gateway.py -q` -> 45 passed / 2 warnings。
  - `pytest app/backend/tests/test_onboarding_gateway.py app/backend/tests/test_asset_lifecycle.py app/backend/tests/test_market_data_contract.py app/backend/tests/test_goal_coverage.py app/backend/tests/test_governed_compiler.py -q` -> 103 passed / 2 warnings。
  - `cd app/frontend && npm test -- SettingsSecurityPage.test.tsx` -> 1 file / 4 tests passed。
  - `python -m compileall -q app/backend/app` -> PASS。
