---
uuid: 8ba1997f78de4699a74b477bb85a3924
title: Settings Data Connector one-shot onboarding UI
status: done
owner: dreaminate
assigned_by: dreaminate
review_status: 0
priority: P1
area: research-os-settings-data-onboarding-ui
source: goal-gap
source_ref: GOAL §4 Data Onboarding Settings wizard; GOAL §11 MarketDataUse gate
depends_on: [ce49ca21854f4d3e9861bb87d33f327a]
completed_at: 2026-06-27
---

# Settings Data Connector one-shot onboarding UI

## Scope [必填]
把后端 `data_connector_onboarding_runs` 接到 Settings Security 的 Data Connectors panel，让 user/Agent 不必逐个点击 check/run/mapping/PIT/semantics/instrument/capability/use gate 才能走完第一条 Settings onboarding 链路。

## 上下文 / 动机 [按需]
`ce49ca21` 已新增后端 one-shot onboarding seam。Settings UI 仍只有一串分步按钮，且 `secret_refs=[]` 的 public no-auth connector 会被前端误禁用测试/run update。GOAL §4 要求 Settings/Agent 辅助完成数据接入，前端需要显式动作和失败 step 反馈。

## 接线点（file:line，实现时复核）[必填]
| 文件 | 改什么 |
|---|---|
| `app/frontend/src/pages/SettingsSecurityPage.tsx` | Data Connectors panel 新增 `Run onboarding` action；调用 `/api/research-os/settings/data_connector_onboarding_runs`；成功显示 run/ref/use validation/step count；失败显示 failed_step/completed_steps/error；no-auth connector 不再被 `secret_refs` 前端禁用 |
| `app/frontend/src/pages/SettingsSecurityPage.test.tsx` | 覆盖 one-shot 成功调用、no-auth public connector 按钮启用、failed_step 显示、secret 不回显 |
| `dev/state/dreaminate/state.md` / `dev/research/TRACE.md` / `dev/log/dreaminate/log.md` | 落档前端 one-shot wizard seam、本地测试和边界 |

## 对抗测试设计（种已知 bug，门必抓）[必填]
1. UI 必须调用 `data_connector_onboarding_runs`，不能继续只靠分步按钮冒充完整 onboarding。
2. 成功结果只显示 run/use-validation refs 和 steps，不回显 SecretValue。
3. no-auth public connector 的 `测试连接` / `Run update` 不能因 `secret_refs=[]` 被前端禁用。
4. 后端 422 返回 `failed_step` / `completed_steps` 时，UI 必须显示失败 step 和已完成 step。
5. UI 不声称 provider 实网连通、策略自动注入或 venue execution。

## 红线 [按需]
- 不把后端 failed_step 包装成成功。
- 不在前端展示 secret value、raw connector payload 或 venue payload。
- 不删除逐步按钮；user 仍可手动走每一步。

## 非目标 [按需]
不实现 OAuth/device-code/account auth、生产 keyring/HSM、完整 provider/connector catalog、全资产自动同步、downstream strategy auto-injection、真实 Binance/Tushare 网络 proof、CI 或线上部署。

## 验收一句话 [必填]
Settings Data Connectors panel 能一键触发后端 one-shot onboarding，能诚实显示 failed_step；public no-auth connector 不再被前端 secret_refs gate 错拦。

## 完成记录
- Data Connectors panel 新增 `Run onboarding` 按钮，调用 `/api/research-os/settings/data_connector_onboarding_runs`。
- 成功路径显示 `run_ref`、`market_data_use_validation_ref` 和 step count；失败路径显示 `failed_step`、`completed_steps` 和 sanitized error。
- 前端 `测试连接` / `Run update` 不再因为 `secret_refs=[]` 禁用，交由后端 no-auth/SecretRef gate 裁决。
- 验证：`SettingsSecurityPage.test.tsx` **1 file / 2 tests passed**；frontend full **27 files / 302 tests passed**；frontend build **PASS**（保留既有 chunk-size warning）。
- 边界：这是 Settings Data Connector one-shot UI seam，不是真实 provider 实网连通、完整 Settings wizard、下游 strategy auto-injection、venue execution、CI、线上或用户验收。
