---
uuid: addd2e4e472c4bc1882beef259597f49
title: IngestionSkill updates require DatasetVersion binding
status: done
owner: dreaminate
assigned_by: dreaminate
review_status: 0
priority: P1
area: research-os-asset-lifecycle-data-onboarding
source: goal-gap
source_ref: GOAL §3 lifecycle; GOAL §4 data updates; GOAL §11 DatasetVersion / PIT axes
depends_on: [aa10b25c5ac04c3180b6e6e6fa130ea2]
completed_at: 2026-06-27
---

# IngestionSkill updates require DatasetVersion binding

## Scope [必填]
把 `IngestionSkillUpdateRecord` 从纯 validator 扩成 append-only lifecycle registry/API，并接到 Settings 的 IngestionSkill 与已有 `DatasetRegistry`。数据更新记录必须绑定已登记的 IngestionSkill、active SecretRef、真实 DatasetVersion、checksum、lineage、quality verdict、known_at/effective_at；任何缺项、悬空 DatasetVersion 或 checksum 不匹配都 fail-closed 且不写 update。

## 上下文 / 动机 [按需]
`aa10b25c` 已让 Settings 能登记 DataSourceAsset/IngestionSkill/ConnectorCheck，但 GOAL §4/§3/§11 仍要求“每次数据更新记录”必须有 DatasetVersion、checksum、lineage、quality_verdict、known_at/effective_at。此前 `asset_lifecycle.py` 只有 `validate_ingestion_skill_update()`，没有持久化 registry/API，也没有校验 DatasetVersion 是否真实存在。

## 接线点（file:line，实现时复核）[必填]
| 文件 | 改什么 |
|---|---|
| `app/backend/app/research_os/asset_lifecycle.py` | 扩展 `IngestionSkillUpdateRecord` 字段，新增 `PersistentAssetLifecycleRegistry` |
| `app/backend/app/research_os/__init__.py` | 导出 lifecycle registry |
| `app/backend/app/main.py` | 新增 `ASSET_LIFECYCLE_REGISTRY`、ingestion update payload/parser、DatasetVersion ref resolver、Settings ingestion update API 和 summary |
| `app/backend/tests/test_asset_lifecycle.py` | 覆盖 update time axes/SecretRef 要求与 registry replay |
| `app/backend/tests/test_onboarding_gateway.py` | 覆盖 Settings API 成功记录、unknown DatasetVersion no-write、checksum mismatch no-write |
| `app/frontend/src/pages/SettingsSecurityPage.tsx` | Data Connectors panel 显示 update count 与最新 DatasetVersion/quality/time refs |
| `app/frontend/src/pages/SettingsSecurityPage.test.tsx` | 覆盖前端显示 update refs 且不泄露 raw key |
| `dev/state/dreaminate/state.md` / `dev/research/TRACE.md` / `dev/log/dreaminate/log.md` | 落档本地证据与边界 |

## 对抗测试设计（种已知 bug，门必抓）[必填]
1. Ingestion update 缺 source/SecretRef/DatasetVersion/checksum/lineage/quality/known_at/effective_at -> validator 拒。
2. dataset_version_ref 未在 `DatasetRegistry` 中登记 -> API 422，不写 lifecycle update。
3. checksum 与 DatasetVersion `sha256` 不一致 -> API 422，不写 lifecycle update。
4. DataSource/IngestionSkill/SecretRef 未由 Settings registry 登记或 SecretRef revoked -> API 422，不写 lifecycle update。
5. 成功记录只返回 refs/checksum/status，不返回 raw rows 或 secret。

## 红线 [按需]
- 不触网、不拉行情、不生成 DatasetVersion 内容；只校验已有 `DatasetRegistry` version。
- 不把 update record 说成真实 connector 已消费了真实数据行。
- 不保存 raw rows、raw connector payload、API key、OAuth token、password。

## 非目标 [按需]
不实现真实 connector adapter、schema scanner、字段映射生成、PIT/bitemporal 自动推导、DatasetVersion 文件生成、全资产自动同步、live provider permission proof 或 quality engine 全套规则。

## 验收一句话 [必填]
Settings ingestion update API 必须在写 append-only lifecycle record 前证明 IngestionSkill、SecretRef、DatasetVersion/checksum 和 time axes 全部成立；否则 fail-closed 且不产生 update 记录。

## 完成记录
- `IngestionSkillUpdateRecord` 新增 `source_ref`、`secret_ref`、`known_at_ref`、`effective_at_ref`、freshness/schema/row_count/evidence fields，validator 要求 source、SecretRef、DatasetVersion、checksum、lineage、quality verdict、known_at、effective_at 全齐。
- 新增 `PersistentAssetLifecycleRegistry`，记录 `ingestion_skill_update_recorded` append-only JSONL，可 replay。
- 主 app 新增 `ASSET_LIFECYCLE_REGISTRY` 和 `POST /api/research-os/settings/ingestion_skill_updates`；endpoint 校验 Settings IngestionSkill、active SecretRef、DatasetVersion ref、checksum 和 row_count 后才写 update。
- Settings summary 增加 `ingestion_skill_update_total` / `ingestion_skill_updates`；Settings 安全页 Data Connectors panel 展示最新 DatasetVersion、quality verdict 和 known/effective refs。
- 验证：`tests/test_asset_lifecycle.py` **8 passed**；asset/onboarding scoped **31 passed / 2 warnings**；asset/onboarding/LLM/market-data/spine adjacent **72 passed / 2 warnings**；targeted compileall **PASS**；Settings frontend scoped **1 file / 1 test passed**；frontend build **PASS**（保留既有 chunk-size warning）。
- 边界：这是已有 DatasetVersion 的 refs/checksum 绑定和 ingestion update audit，不是真实 connector adapter、schema scanner、字段映射、PIT/bitemporal 自动生成、DatasetVersion 文件生成、全资产自动同步、live provider permission proof 或 raw data consumption proof。
