---
uuid: ce49ca21854f4d3e9861bb87d33f327a
title: Settings data connector one-shot onboarding run
status: done
owner: dreaminate
assigned_by: dreaminate
review_status: 0
priority: P1
area: research-os-data-onboarding-pipeline
source: goal-gap
source_ref: GOAL §4 Data Onboarding Settings pipeline; GOAL §11 MarketDataUse gate
depends_on: [a6dcb50f085e4af79dbd013c578dc2fc]
completed_at: 2026-06-27
---

# Settings data connector one-shot onboarding run

## Scope [必填]
把 Settings Data Connector 链路从散端点收成一个可验证 pipeline：一次请求串起 connection check、ingestion run、field mapping、PIT/bitemporal rule、DatasetSemantics、InstrumentSpec、CapabilityMatrix 和 MarketDataUseValidation。

## 上下文 / 动机 [按需]
`e65a6e96` 已让 Settings 链路能逐步闭合到 accepted MarketDataUseValidation；`4b7e2c19` / `adf0c2a4` / `a6dcb50f` 已补 SecretValue、Tushare adapter、Binance public no-auth adapter。GOAL §4 仍要求 Agent 在数据台辅助 user 完整完成 onboarding，而不是让用户或 UI 手写一串 API 调用。新卡补第一条后端 one-shot run seam。

## 接线点（file:line，实现时复核）[必填]
| 文件 | 改什么 |
|---|---|
| `app/backend/app/main.py` | 新增 `POST /api/research-os/settings/data_connector_onboarding_runs`，复用既有 validated endpoint 逻辑按 step 串联；新增 conservative field-mapping auto inference |
| `app/backend/tests/test_onboarding_gateway.py` | 覆盖 one-shot 成功写到 MarketDataUseValidation，以及坏 field mapping 在该 step fail-closed、不写 PIT/market-data 后续记录 |
| `dev/state/dreaminate/state.md` / `dev/research/TRACE.md` / `dev/log/dreaminate/log.md` | 落档 pipeline proof、测试数和边界 |

## 对抗测试设计（种已知 bug，门必抓）[必填]
1. Pipeline 必须复用现有 validators，不能绕过 field mapping/PIT/market-data gates。
2. 成功路径必须写 DatasetVersion、IngestionSkillUpdate、FieldMapping、PIT rule、DatasetSemantics、InstrumentSpec、CapabilityMatrix、MarketDataUseValidation。
3. 未显式传 mapping 时只能做常见时间/symbol/OHLCV 字段的保守自动映射，并把其余 observed columns 标为 unmapped。
4. 坏 mapping 必须停在 `field_mapping`，返回 `failed_step` 和已完成 step，不写 PIT 或 market-data 后续记录。
5. response 不能回显 plaintext secret；pipeline 不能触发 strategy builder、venue execution 或 live permission proof。

## 红线 [按需]
- 不把 partial pipeline failure 写成完整 onboarding 成功。
- 不把 fake checker/runner seam 说成真实 provider 实网连通。
- 不自动生成 live/testnet 权限证明、策略消费证明或交易执行证明。
- 不新增第二套 validator 或绕过 Settings/MarketData registries。

## 非目标 [按需]
不实现完整前端 wizard、OAuth/device-code/account auth、生产 keyring/HSM、完整 connector/provider catalog、全资产自动同步、scheduler、真实 Binance/Tushare 网络 proof、downstream strategy auto-injection 或 CI/线上验证。

## 验收一句话 [必填]
Settings 一次 onboarding run 能从已登记 skill 产出 accepted MarketDataUseValidation；坏 mapping 在 field_mapping step fail-closed 且不写后续 market-data 记录。

## 完成记录
- 新增 `POST /api/research-os/settings/data_connector_onboarding_runs`，按 step 串联 connection check、ingestion run、field mapping、PIT/bitemporal rule、DatasetSemantics、InstrumentSpec、CapabilityMatrix 和 MarketDataUseValidation。
- Pipeline 复用既有 endpoint/validator 逻辑；每步响应进入 step ledger，失败返回 `failed_step`、`completed_steps` 和 sanitized error。
- 新增 conservative auto mapping：常见 event_time/symbol/OHLCV/amount/market/interval 字段会映射，其余 observed columns 进入 `unmapped_columns`，并标记 `mapping_method=agent_suggested`。
- 验证：`tests/test_onboarding_gateway.py` **43 passed / 2 warnings**；connectors + asset/onboarding/LLM/market-data/spine/data_quality adjacent **114 passed / 2 warnings**；targeted compileall **PASS**；`validate_dev` **49 ✅ / 0 ❌ / 0 ⚠️ PASS**。
- 边界：这是后端 one-shot onboarding seam 和 fake checker/runner proof，不是真实 provider 实网连通、完整 Settings wizard、下游 strategy auto-injection、venue execution、CI、线上或用户验收。
