---
uuid: e6f2b8a4b3c64e7db0e719b4cfbe6c21
title: Settings IngestionSkill runner produces DatasetVersion files
status: done
owner: dreaminate
assigned_by: dreaminate
review_status: 0
priority: P1
area: research-os-data-onboarding-dataset-version
source: goal-gap
source_ref: GOAL §4 Data Onboarding / IngestionSkill; GOAL §11 DatasetVersion file generation; GOAL §3 asset lifecycle
depends_on: [aa10b25c5ac04c3180b6e6e6fa130ea2, addd2e4e472c4bc1882beef259597f49]
completed_at: 2026-06-27
---

# Settings IngestionSkill runner produces DatasetVersion files

## Scope [必填]
把 Settings 里的 IngestionSkill 从“只登记 metadata / 绑定已有 DatasetVersion”推进到受控 connector run producer：新增注入式 `DATA_CONNECTOR_INGESTION_RUNNER` 和 `POST /api/research-os/settings/ingestion_skill_runs`。endpoint 必须先证明 active IngestionSkill、active SecretRef、ok DataConnectorConnectionCheck，再接受 runner 返回的 `FetchResult`，重新校验 row_count/checksum/secret，原子写本地 parquet，登记 `DatasetRegistry`，并自动写 `IngestionSkillUpdateRecord`。

## 上下文 / 动机 [按需]
`aa10b25c` 已有 Settings DataSource/IngestionSkill/ConnectorCheck；`addd2e4e` 已要求 update 绑定真实 DatasetVersion/checksum/time axes。但数据更新仍需人工预置 DatasetVersion，没有 runtime producer 负责把 connector 结果写成不可变文件和 registry version。本卡补 §4→§11→§3 的第一条受控生产链。

## 接线点（file:line，实现时复核）[必填]
| 文件 | 改什么 |
|---|---|
| `app/backend/app/main.py` | 新增 disabled ingestion runner seam、run payload/parser、ok connector check gate、FetchResult 校验、parquet 落盘、DatasetVersion + IngestionSkillUpdate 自动写入 API |
| `app/backend/tests/test_onboarding_gateway.py` | 覆盖成功生成 DatasetVersion/update、缺 ok check 不调用 runner、disabled runner no-write、checksum mismatch no-write、plaintext frame no-write |
| `app/frontend/src/pages/SettingsSecurityPage.tsx` | Data Connectors panel 增加 Run update 按钮，使用最新 ok connector check 调 ingestion run endpoint |
| `app/frontend/src/pages/SettingsSecurityPage.test.tsx` | 覆盖 connector check 与 run update payload 都是 refs-only，页面不泄露 raw key |
| `dev/state/dreaminate/state.md` / `dev/research/TRACE.md` / `dev/log/dreaminate/log.md` | 落档本地证据与边界 |

## 对抗测试设计（种已知 bug，门必抓）[必填]
1. 没有 ok DataConnectorConnectionCheck 时，endpoint 422，runner 不被调用，不写 DatasetVersion/update。
2. 默认 runner disabled 时，endpoint 422，不写 parquet、DatasetRegistry 或 lifecycle update。
3. runner 返回的 sha256 与 frame 内容不匹配时，endpoint 422，不写 parquet、DatasetVersion 或 update。
4. runner frame 含明文 API key / secret 文本时，endpoint 422，不写 parquet、DatasetVersion 或 update。
5. 成功路径只返回 refs/hash/path/row_count，不返回 raw rows 或 secret。

## 红线 [按需]
- 默认不触网、不拉行情、不调用真实 provider；只有注入 runner 才能产生 DatasetVersion。
- 不保存 raw connector payload、API key、OAuth token、password。
- 不把 fake runner 测试说成真实 provider adapter 已接通。
- 不新增 A股 live 下单路径，不接券商网关。

## 非目标 [按需]
不实现内置真实 connector adapter、真实 Secret value storage、OAuth/device-code/account auth、字段映射 wizard、PIT/bitemporal 自动推导、全资产自动同步、live provider permission proof 或生产 scheduler。

## 验收一句话 [必填]
Settings ingestion run API 必须在 active skill/SecretRef/ok check 全成立后，将 runner `FetchResult` 原子写成本地 parquet + `DatasetVersion`，并自动写绑定该 version 的 `IngestionSkillUpdateRecord`；任一坏门失败都不产生文件或 registry/update 记录。

## 完成记录
- 新增 `DATA_CONNECTOR_INGESTION_RUNNER`，默认 disabled，`POST /api/research-os/settings/ingestion_skill_runs` 在默认状态下 422 且 no-write。
- endpoint 强制 active IngestionSkill、active SecretRef、ok DataConnectorConnectionCheck；connector check 可显式指定，也可取最新 ok check。
- runner 返回的 `FetchResult` 会被重新计算 checksum/row_count/coverage；checksum mismatch、空数据、明文 secret frame/metadata、dataset_id mismatch 均 422。
- 成功路径写 `DATA_ROOT/datasets/ingestion/<dataset_id>/<sha12>.parquet`，再登记 `DatasetRegistry`，metadata 带 source、skill、connector_check、schema_probe、permission、PIT refs；随后自动写 `IngestionSkillUpdateRecord`。
- Settings 安全页 Data Connectors panel 新增 `Run update`，用最新 ok `connector_check_ref` 调用 ingestion run endpoint，展示 DatasetVersion ref、row_count、update_ref。
- 验证：`tests/test_onboarding_gateway.py` **28 passed / 2 warnings**；asset/onboarding scoped **36 passed / 2 warnings**；asset/onboarding/LLM/market-data/spine/data_quality adjacent **87 passed / 2 warnings**；targeted compileall **PASS**；Settings frontend scoped **1 file / 1 test passed**；frontend full **27 files / 301 tests passed**；frontend build **PASS**（保留既有 chunk-size warning）。
- 边界：这是注入式 runner seam + 本地 DatasetVersion 文件生成 + update audit，不是内置真实 connector adapter、真实行情下载、字段映射 wizard、PIT/bitemporal 自动推导、全资产自动同步、live provider permission proof、生产 scheduler 或外部 provider 实网连通证明。
