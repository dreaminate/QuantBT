---
uuid: f11f8c4c87594a05ad4da74f61ebec9b
title: Settings editable Data Connector field mapping and PIT wizard
status: done
owner: dreaminate
assigned_by: dreaminate
review_status: 0
priority: P1
area: research-os-settings-data-onboarding-ui
source: goal-gap
source_ref: GOAL §4 Data Onboarding Settings wizard; GOAL §11 PIT/bitemporal data semantics
depends_on: [8ba1997f78de4699a74b477bb85a3924]
completed_at: 2026-06-27
---

# Settings editable Data Connector field mapping and PIT wizard

## Scope [必填]
把 Settings Security 的 Data Connectors panel 从固定默认字段映射/PIT payload 升级为可编辑 UI：用户能基于 schema probe 明确选择每个 source column 的 canonical role、event/known/effective/symbol time axes 和 PIT policy，再调用现有 Settings 后端 endpoint 记录 FieldMapping/PIT rule。

## 上下文 / 动机 [按需]
`8ba1997f` 已把 one-shot onboarding 暴露到前端，但 GOAL §4 仍要求 Settings/Agent 辅助完成字段映射、PIT 和双时态配置。旧 UI 的 `Record mapping` / `PIT rules` 只从列名硬推断，遇到非标准字段时不能让用户修正，只能失败或走后端 one-shot 的默认推断。

## 接线点（file:line，实现时复核）[必填]
| 文件 | 改什么 |
|---|---|
| `app/frontend/src/pages/SettingsSecurityPage.tsx` | Data Connectors panel 新增 editable mapping/PIT controls；提交 payload 使用 UI state；保留 backend validator fail-closed |
| `app/frontend/src/pages/SettingsSecurityPage.test.tsx` | 覆盖用户手动映射非标准列、PIT policy 提交、bad PIT policy 422 显示、secret 不回显 |
| `dev/state/dreaminate/state.md` / `dev/research/TRACE.md` / `dev/log/dreaminate/log.md` | 落档 Settings editable field mapping/PIT wizard、本地测试和边界 |

## 对抗测试设计（种已知 bug，门必抓）[必填]
1. 非标准列名不能只靠自动推断；用户选择后 payload 必须带用户选的 `source_to_canonical` 和 time axes。
2. 用户显式标记 ignored 的列必须进入 `unmapped_columns`，不能静默遗漏。
3. PIT rule 的 `asof_join_policy` / time policies 必须来自 UI state，并由后端 validator 拒绝 unsafe policy。
4. UI 必须显示 422 失败原因，不把后端拒绝包装成成功。
5. UI 不展示 SecretValue、raw provider payload 或 venue payload。

## 红线 [按需]
- 不复制后端 validator 逻辑成前端真理；前端只是构造 payload，最后裁决仍在 backend。
- 不绕过 `data_connector_field_mappings` / `pit_bitemporal_rules` endpoint。
- 不声称真实 provider 实网连通、全资产自动同步或下游 strategy auto-injection。

## 非目标 [按需]
不实现 OAuth/device-code/account auth、生产 keyring/HSM、完整 provider catalog、real provider network proof、scheduler、全资产自动同步、下游 strategy auto-injection、CI 或线上部署。

## 验收一句话 [必填]
Settings Data Connectors panel 可手动编辑字段映射和 PIT policy，并把用户选择通过现有 backend endpoint 记录；失败保持 backend 422 可见。

## 完成记录
- Data Connectors panel 新增 field mapping wizard：按 schema probe columns 渲染 canonical role select，支持手动选择 `event_time` / `instrument_id` / OHLCV 等 canonical field，ignored column 写入 `unmapped_columns`。
- Data Connectors panel 新增 time-axis selectors：`event_time_column`、`known_at_column`、`effective_at_column`、`symbol_column` 从 UI state 进入 `data_connector_field_mappings` payload；空 known/effective/symbol 以 null 提交。
- Data Connectors panel 新增 PIT rule controls：event/known/effective columns、known/effective policies、as-of policy、restatement policy 和 timezone 从 UI state 进入 `pit_bitemporal_rules` payload。
- 继续复用现有 backend validators；unsafe as-of policy / bad mapping 仍由 backend 422 裁决，UI 显示失败原因，不包装成功。
- 验证：`SettingsSecurityPage.test.tsx` **1 file / 3 tests passed**；frontend full **27 files / 303 tests passed**；frontend build **PASS**（保留既有 chunk-size warning）。
- 边界：这是 Settings editable field mapping/PIT UI seam，不是真实 provider 实网连通、完整 provider catalog、生产 scheduler、下游 strategy auto-injection、CI、线上或用户验收。
