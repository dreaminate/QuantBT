---
uuid: 8c774e192a5e4cc198b90b69d0a3dee6
title: Settings Generic REST connector draft UI
status: done
owner: dreaminate
assigned_by: dreaminate
review_status: 0
priority: P1
area: research-os-settings-data-onboarding-connectors
source: goal-gap
source_ref: GOAL §4 Data Onboarding Settings connector wizard; GOAL §11 data source extensibility
depends_on: [0fca8ad65f93414eb4ec9d3ea6407d5b]
completed_at: 2026-06-27
---

# Settings Generic REST connector draft UI

## Scope [必填]
在 Settings Security 的 Data Connectors panel 增加 Generic REST source/skill draft 表单，让用户可录入 source metadata、skill metadata 和 `generic_rest_yaml`，并通过现有 `/api/research-os/settings/data_sources` 与 `/api/research-os/settings/ingestion_skills` endpoint 登记，不新增后端旁路。

## 上下文 / 动机 [按需]
`0fca8ad6` 已让后端 Settings resolver 从 `IngestionSkill.connector_config.generic_rest_yaml` 构造 `GenericRESTConnector`，但前端还没有创建该类 DataSource/IngestionSkill 的入口。只靠手写 API payload 会让 Settings wizard 的 §4/§11 闭合不完整。

## 接线点（file:line，实现时复核）[必填]
| 文件 | 改什么 |
|---|---|
| `app/frontend/src/pages/SettingsSecurityPage.tsx` | 增加 Generic REST draft state、表单、payload builder 和 register 动作 |
| `app/frontend/src/pages/SettingsSecurityPage.test.tsx` | 覆盖前端提交 source/skill 两个既有 endpoint，payload 不回显 secret，不走 connection check/run 假绿 |
| `dev/state/dreaminate/state.md` / `dev/research/TRACE.md` / `dev/log/dreaminate/log.md` | 落档 UI seam、本地测试和边界 |

## 对抗测试设计（种已知 bug，门必抓）[必填]
1. 表单必须同时写 DataSource 和 IngestionSkill；DataSource 成功但 Skill 失败时 UI 要显示失败，不能说已接入成功。
2. `connector_config.connector_name` 必须是 `generic_rest`，YAML 放入 `generic_rest_yaml`，`auth_mode=none`，`secret_refs=[]`。
3. 默认 payload 必须有 source/license/rate_limit/retention、schema mapping、PIT ref、dataset id、permission scope 和 rollback/dependency refs。
4. UI 不接收或回显 SecretValue；Generic REST YAML 中若用户塞 secret，由后端 plaintext/static_value gate 拦截。
5. 这只是登记 metadata，不自动调用 check/run/onboarding，也不声称 provider 已连通。

## 红线 [按需]
- 不在前端解析/执行 YAML。
- 不把 UI 登记成功说成连接成功。
- 不新增绕过 Settings validators 的 endpoint。

## 非目标 [按需]
不实现 OAuth/device-code/account auth、生产 keyring/HSM、provider marketplace、真实外网连通、scheduler、全资产自动同步、下游 strategy auto-injection、CI 或线上部署。

## 验收一句话 [必填]
Settings UI 能登记一个 Generic REST YAML-backed DataSource + IngestionSkill，后续可走已有 test/run/onboarding 链路。

## 完成记录
- Settings Data Connectors panel 新增 Generic REST YAML draft 表单，登记 source metadata、skill metadata、dataset/schema/PIT refs、symbol/market/interval/start/end 和 YAML。
- 表单提交先调用 `/api/research-os/settings/data_sources`，成功后调用 `/api/research-os/settings/ingestion_skills`；第二步失败时显示失败并标明 source 已登记，不说成接入成功。
- IngestionSkill payload 固定 `source_type=generic_rest_api`、`connector_config.connector_name=generic_rest`、`auth_mode=none`、`generic_rest_yaml=<textarea>`、`secret_refs=[]`，后续 test/run/onboarding 仍走现有后端 gates。
- 新增前端测试覆盖 DataSource + IngestionSkill 两个 endpoint payload，确认不触发 connection check/run，不回显 `sk-live`。
- 验证：`cd app/frontend && npm test -- SettingsSecurityPage.test.tsx --run` → **1 file / 4 tests passed**；`cd app/frontend && npm run test:run` → **27 files / 304 tests passed**；`cd app/frontend && npm run build` → PASS（保留既有 chunk-size warning）。
