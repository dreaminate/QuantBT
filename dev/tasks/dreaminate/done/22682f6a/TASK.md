---
uuid: 22682f6a8e5844cbb13300d350f046b2
title: Settings PIT bitemporal rule registry and UI
status: done
owner: dreaminate
assigned_by: dreaminate
review_status: 0
priority: P1
area: research-os-data-onboarding-pit-bitemporal
source: goal-gap
source_ref: GOAL §4 Data Onboarding generates PIT/bitemporal rules; GOAL §11 confirmatory validation requires PIT semantics
depends_on: [b7d0708bab0949bcbd50c00804272387]
completed_at: 2026-06-27
---

# Settings PIT bitemporal rule registry and UI

## Scope [必填]
把字段映射后的 PIT/bitemporal 规则升级为 Settings-managed append-only runtime record。规则必须绑定已记录的 IngestionSkill、DataSourceAsset、DataConnectorFieldMapping 和 DataConnectorSchemaProbe，固定 event_time、known_at、effective_at、as-of join policy、timezone、calendar、lookahead guard、restatement policy 和 deterministic rule_hash；Settings summary/UI 必须能显示和生成规则。

## 上下文 / 动机 [按需]
`b7d0708b` 已让 schema probe 后的字段映射可 replay，但 `pit_bitemporal_rules_ref` 仍只是 IngestionSkill 上的裸字符串。GOAL §4 要求字段映射后生成 PIT/bitemporal rules，GOAL §11 的 `DatasetSemanticsRecord` 在 confirmatory validation 时要求 `known_at_ref`、`effective_at_ref` 和 `pit_bitemporal_rules_ref` 同时存在。没有规则本体时，下游只能看到 ref，不能审计 as-of 语义。

## 接线点（file:line，实现时复核）[必填]
| 文件 | 改什么 |
|---|---|
| `app/backend/app/research_os/onboarding_gateway.py` | 新增 `DataConnectorPITBitemporalRuleRecord`、hash helper、validator、PersistentOnboardingRegistry event/replay/accessors |
| `app/backend/app/research_os/__init__.py` | 导出 PIT/bitemporal rule record/hash/validator |
| `app/backend/app/main.py` | 新增 PIT/bitemporal rule payload parser、`POST /api/research-os/settings/pit_bitemporal_rules`、summary totals/list |
| `app/backend/tests/test_onboarding_gateway.py` | 覆盖 validator 坏门、registry replay、API no-partial-write 和 summary |
| `app/frontend/src/pages/SettingsSecurityPage.tsx` | Data Connectors panel 显示 latest PIT rule，并可基于 field mapping 生成一版 PIT rule payload |
| `app/frontend/src/pages/SettingsSecurityPage.test.tsx` | 覆盖 PIT rule summary 渲染和 POST body |
| `dev/state/dreaminate/state.md` / `dev/research/TRACE.md` / `dev/log/dreaminate/log.md` | 落档本地证据与边界 |

## 对抗测试设计（种已知 bug，门必抓）[必填]
1. PIT rule skill/source/field_mapping/schema_probe scope 不匹配 -> validator 拒。
2. rule_ref 不等于 IngestionSkill `pit_bitemporal_rules_ref` -> validator 拒。
3. event_time_column 未在 schema probe 中或不等于 field mapping event axis -> validator 拒。
4. as-of policy 使用 current snapshot / full history / latest 这类非 PIT-safe 策略 -> validator 拒。
5. 缺 field_mapping_ref 和 schema_probe_ref evidence -> validator 拒。
6. rule_hash 与内容不一致 -> validator/API 拒。
7. API 拒绝坏规则时不写 partial PIT/bitemporal rule record。

## 红线 [按需]
- 不把规则 record 当成 confirmatory validation 已通过。
- 不保存 raw connector rows、raw payload、API key、OAuth token、password。
- 不允许 `current_snapshot` / `full_history` / unconstrained latest 这类前视 as-of policy。

## 非目标 [按需]
不实现完整 PIT 推导 wizard、语义类型推断、实际 DatasetSemantics 自动登记、真实 connector adapter、全资产自动同步、生产 scheduler、live provider permission check 或下游全入口强制引用。

## 验收一句话 [必填]
Settings 里的 field mapping 之后，必须能写入可 replay 的 PIT/bitemporal rule record；危险 as-of policy、未知时间列、缺 evidence 或 hash 篡改必须 fail-closed 且不写 partial。

## 完成记录
- 新增 `DataConnectorPITBitemporalRuleRecord`、`data_connector_pit_bitemporal_rule_hash()`、`validate_data_connector_pit_bitemporal_rule()` 和 `data_connector_pit_bitemporal_rule_recorded` append-only event；`PersistentOnboardingRegistry` 可 record/replay/access/list PIT/bitemporal rules。
- 新增 `POST /api/research-os/settings/pit_bitemporal_rules`，绑定 recorded IngestionSkill/DataSourceAsset/FieldMapping/SchemaProbe；缺 field_mapping_ref 时取该 skill 最新 mapping；endpoint 从 field mapping 推导 event/known/effective time axes 和 PIT-safe as-of policy，生成 deterministic `rule_hash`。
- Settings summary 返回 `data_connector_pit_bitemporal_rule_total` 和 `data_connector_pit_bitemporal_rules`。
- Settings 安全页 Data Connectors panel 展示 latest PIT rule，并在 field mapping 存在时可记录一版 PIT/bitemporal rule payload。
- 验证：`tests/test_onboarding_gateway.py` **33 passed / 2 warnings**；asset/onboarding/LLM/market-data/spine/data_quality adjacent **92 passed / 2 warnings**；targeted compileall **PASS**；Settings frontend scoped **1 file / 1 test passed**；frontend full **27 files / 301 tests passed**；frontend build **PASS**（保留既有 chunk-size warning）。
- 边界：这是可 replay Settings PIT/bitemporal rule record/API/UI，不是完整 PIT 推导 wizard、语义类型推断、实际 DatasetSemantics 自动登记、真实 connector adapter、全资产自动同步、生产 scheduler、live provider permission proof 或 confirmatory validation proof。
