---
uuid: 2d7a91c3a25d45a0a7f9621dfb4939a0
title: Settings ingestion schema probe registry and drift gate
status: done
owner: dreaminate
assigned_by: dreaminate
review_status: 0
priority: P1
area: research-os-data-onboarding-schema
source: goal-gap
source_ref: GOAL §4 schema scanner; GOAL §11 DatasetVersion schema semantics; GOAL §3 lifecycle drift control
depends_on: [e6f2b8a4b3c64e7db0e719b4cfbe6c21]
completed_at: 2026-06-27
---

# Settings ingestion schema probe registry and drift gate

## Scope [必填]
把 `schema_probe_ref` 从 ingestion run metadata 里的裸 ref 升级为 Settings append-only schema probe record。每次 Settings IngestionSkill run 必须生成 `DataConnectorSchemaProbeRecord`，记录 columns/dtypes/signature、row_count、connector_check_ref、dataset_version_ref 和 drift_status；若检测到 schema signature 变化，必须提供 schema drift event 与 downstream impact refs，否则 fail-closed 且不写 parquet、DatasetVersion 或 update。

## 上下文 / 动机 [按需]
`e6f2b8a4` 已让注入式 runner 产出 DatasetVersion 文件并自动写 IngestionSkillUpdate，但 schema probe 只是一串 ref/hash，没有可 replay 的 schema scanner 记录，也没有 schema drift gate。GOAL §4/§11 要求数据接入必须能审计 schema、字段变化和下游影响。

## 接线点（file:line，实现时复核）[必填]
| 文件 | 改什么 |
|---|---|
| `app/backend/app/research_os/onboarding_gateway.py` | 新增 `DataConnectorSchemaProbeRecord`、validator、PersistentOnboardingRegistry event/replay/accessors |
| `app/backend/app/research_os/__init__.py` | 导出 schema probe record/validator |
| `app/backend/app/main.py` | ingestion run 生成并预校验 schema probe，drift gate 在写文件前触发；summary 返回 schema probe totals/list |
| `app/backend/tests/test_onboarding_gateway.py` | 覆盖 schema probe validator/replay、run 自动记录 schema probe、schema drift no-write |
| `app/frontend/src/pages/SettingsSecurityPage.tsx` | Data Connectors panel 显示 schema probe count、latest probe/drift/columns |
| `app/frontend/src/pages/SettingsSecurityPage.test.tsx` | 覆盖 summary 渲染 schema probe refs 且不泄露 raw key |
| `dev/state/dreaminate/state.md` / `dev/research/TRACE.md` / `dev/log/dreaminate/log.md` | 落档本地证据与边界 |

## 对抗测试设计（种已知 bug，门必抓）[必填]
1. Schema probe 缺 columns/dtypes/signature 或含明文 secret 字段名 -> validator 拒。
2. Schema probe 绑定的 skill/source/check 不匹配或 check 非 ok -> validator 拒。
3. `drift_status=changed/drifted` 但缺 previous probe、schema drift event 或 downstream impact refs -> validator 拒。
4. Ingestion run 第一次 schema 写 probe；第二次 schema signature 变化且 runner 未给 drift refs -> 422，且不写新 parquet、DatasetVersion、schema probe 或 lifecycle update。
5. Settings summary/前端只展示 schema refs/signature/count，不展示 raw data rows。

## 红线 [按需]
- 不把 schema probe 当成字段映射 wizard 或完整 PIT/bitemporal 推导。
- 不保存 raw rows、raw connector payload、API key、OAuth token、password。
- 不把 drift refs 缺失时的失败说成成功更新。

## 非目标 [按需]
不实现自动字段映射、语义类型推断、PIT/effective-time 规则生成、全资产自动同步、真实 connector adapter、生产 scheduler 或外部 provider 实网连通。

## 验收一句话 [必填]
每次 Settings ingestion run 必须把 observed schema 写成可 replay 的 schema probe record；schema signature 变化且没有 drift event/downstream impact refs 时，必须在写 DatasetVersion 文件前失败。

## 完成记录
- 新增 `DataConnectorSchemaProbeRecord`、`validate_data_connector_schema_probe()` 和 `data_connector_schema_probe_recorded` append-only event；`PersistentOnboardingRegistry` 可 replay/access/list schema probes。
- ingestion run 会计算 columns/dtypes 的 `schema_signature_hash`，按 skill/source 查 latest probe；首次 `none`，相同 schema `unchanged`，不同 schema 强制 `changed/drifted` gate。
- drift schema 若缺 `schema_drift_event_ref` 或 `downstream_impact_refs`，endpoint 422，且不写 parquet、DatasetVersion、schema probe 或 IngestionSkillUpdate。
- Settings summary 返回 `data_connector_schema_probe_total` 和 `data_connector_schema_probes`；Settings 安全页 Data Connectors panel 展示 schema probe ref、drift status、columns count。
- 验证：`tests/test_onboarding_gateway.py` **30 passed / 2 warnings**；asset/onboarding scoped **38 passed / 2 warnings**；asset/onboarding/LLM/market-data/spine/data_quality adjacent **89 passed / 2 warnings**；targeted compileall **PASS**；Settings frontend scoped **1 file / 1 test passed**；frontend full **27 files / 301 tests passed**；frontend build **PASS**（保留既有 chunk-size warning）。
- 边界：这是可 replay schema scanner record + drift gate，不是自动字段映射、语义类型推断、PIT/bitemporal 自动生成、真实 connector adapter、全资产自动同步、生产 scheduler 或外部 provider 实网连通证明。
