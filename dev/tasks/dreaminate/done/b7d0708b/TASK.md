---
uuid: b7d0708bab0949bcbd50c00804272387
title: Settings data connector field mapping registry and UI
status: done
owner: dreaminate
assigned_by: dreaminate
review_status: 0
priority: P1
area: research-os-data-onboarding-field-mapping
source: goal-gap
source_ref: GOAL §2 data desk field mapping; GOAL §4 Data Onboarding schema -> field mapping; GOAL §11 PIT/bitemporal data semantics
depends_on: [2d7a91c3a25d45a0a7f9621dfb4939a0]
completed_at: 2026-06-27
---

# Settings data connector field mapping registry and UI

## Scope [必填]
把 schema probe 后的字段映射升级为 Settings-managed append-only runtime record。字段映射必须绑定已记录的 IngestionSkill、DataSourceAsset 和 DataConnectorSchemaProbe，覆盖 source columns、canonical fields、event_time/known_at/effective_at/symbol 候选、unmapped columns、deterministic mapping_hash 和 evidence refs；Settings summary/UI 必须能显示和提交映射。

## 上下文 / 动机 [按需]
`2d7a91c3` 已把 schema scanner 和 drift gate 做成可 replay record，但 GOAL §2/§4 要求数据台在 schema scan 后生成字段映射，再生成 PIT/bitemporal rules 和 IngestionSkill。没有字段映射 record 时，后续 PIT/time semantics 只能引用裸字符串，不能审计，也不能在 Settings 里手动复核。

## 接线点（file:line，实现时复核）[必填]
| 文件 | 改什么 |
|---|---|
| `app/backend/app/research_os/onboarding_gateway.py` | 新增 `DataConnectorFieldMappingRecord`、hash helper、validator、PersistentOnboardingRegistry event/replay/accessors |
| `app/backend/app/research_os/__init__.py` | 导出 field mapping record/hash/validator |
| `app/backend/app/main.py` | 新增 field mapping payload parser、`POST /api/research-os/settings/data_connector_field_mappings`、summary totals/list |
| `app/backend/tests/test_onboarding_gateway.py` | 覆盖 validator 坏门、registry replay、API no-partial-write 和 summary |
| `app/frontend/src/pages/SettingsSecurityPage.tsx` | Data Connectors panel 显示 latest field mapping，并可基于 schema probe 记录默认列名映射 |
| `app/frontend/src/pages/SettingsSecurityPage.test.tsx` | 覆盖 field mapping summary 渲染和 POST body |
| `dev/state/dreaminate/state.md` / `dev/research/TRACE.md` / `dev/log/dreaminate/log.md` | 落档本地证据与边界 |

## 对抗测试设计（种已知 bug，门必抓）[必填]
1. Field mapping skill/source/schema_probe 不匹配 -> validator 拒。
2. source_to_canonical 引用 schema probe 未观察到的 column -> validator 拒。
3. schema probe columns 未被 map 或显式 unmapped -> validator 拒。
4. event_time_column 缺失、未知或未映射 -> validator 拒。
5. secret-like source column/canonical field 或 plaintext secret metadata -> validator 拒。
6. mapping_hash 与内容不一致 -> validator/API 拒。
7. API 拒绝坏映射时不写 partial field mapping record。

## 红线 [按需]
- 不保存 raw connector rows、raw payload、API key、OAuth token、password。
- 不把默认列名映射说成语义推断证明或 PIT/bitemporal 规则证明。
- 不把 field mapping 存在包装成 DatasetVersion 已适合 confirmatory validation。

## 非目标 [按需]
不实现完整字段映射 wizard、语义类型推断、人机交互逐列编辑器、PIT/bitemporal 规则生成、真实 connector adapter、全资产自动同步、生产 scheduler 或 live provider permission check。

## 验收一句话 [必填]
Settings 里的 DataConnector schema probe 之后，必须能写入可 replay 的 field mapping record；未知列、缺 event_time、secret-like 字段或 hash 篡改必须 fail-closed 且不写 partial。

## 完成记录
- 新增 `DataConnectorFieldMappingRecord`、`data_connector_field_mapping_hash()`、`validate_data_connector_field_mapping()` 和 `data_connector_field_mapping_recorded` append-only event；`PersistentOnboardingRegistry` 可 record/replay/access/list field mappings。
- 新增 `POST /api/research-os/settings/data_connector_field_mappings`，绑定 recorded IngestionSkill/DataSourceAsset/SchemaProbe，缺 schema_probe_ref 时取该 skill 最新 probe；endpoint 自动生成 deterministic `mapping_hash`，显式坏 hash 会 422。
- Settings summary 返回 `data_connector_field_mapping_total` 和 `data_connector_field_mappings`。
- Settings 安全页 Data Connectors panel 展示 latest field mapping，并在 schema probe 存在时可按常见列名生成一版 Settings mapping payload。
- 验证：`tests/test_onboarding_gateway.py` **32 passed / 2 warnings**；asset/onboarding scoped **40 passed / 2 warnings**；asset/onboarding/LLM/market-data/spine/data_quality adjacent **91 passed / 2 warnings**；targeted compileall **PASS**；Settings frontend scoped **1 file / 1 test passed**；frontend full **27 files / 301 tests passed**；frontend build **PASS**（保留既有 chunk-size warning）。
- 边界：这是可 replay Settings field mapping record/API/UI，不是完整字段映射 wizard、语义类型推断、PIT/bitemporal 自动生成、真实 connector adapter、全资产自动同步、生产 scheduler、live provider permission proof 或 confirmatory validation data-semantics proof。
