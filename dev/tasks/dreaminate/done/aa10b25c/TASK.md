---
uuid: aa10b25c5ac04c3180b6e6e6fa130ea2
title: Settings-managed Data Connector checks
status: done
owner: dreaminate
assigned_by: dreaminate
review_status: 0
priority: P1
area: research-os-settings-data-onboarding
source: goal-gap
source_ref: GOAL §4 Data Onboarding / Settings / Skill; GOAL §11 data layer connector proof
depends_on: [73e78014c06047de8e645db65904def5, e29078914b9a448ba631837c548a4a16]
completed_at: 2026-06-27
---

# Settings-managed Data Connector checks

## Scope [必填]
把 §4 DataSourceAsset / IngestionSkill 从只存在 validator 扩成 Settings append-only metadata registry/API，并新增 SecretRef-backed data connector connection check seam。连接测试必须在 checker 调用前确认 skill/source/SecretRef 都来自 Settings registry；revoked SecretRef、plaintext payload、checker 返回明文或悬空 refs 都必须 fail-closed。默认 checker disabled，只能记录诚实失败，不能声称 provider 已连通。

## 上下文 / 动机 [按需]
`73e78014` 已建立 SecretRef/LLMProvider/CredentialPool/ModelRoutingPolicy registry/API，但数据连接器只停留在 `validate_data_source_asset` 和 `validate_ingestion_skill_run`。GOAL §4 要求 Settings 能登记数据源、调用已注册 SecretRef 做连接测试、生成/管理 IngestionSkill；§11 仍缺真实 connector/provider permission proof。本卡补第一条可审计 connection-check seam。

## 接线点（file:line，实现时复核）[必填]
| 文件 | 改什么 |
|---|---|
| `app/backend/app/research_os/onboarding_gateway.py` | 新增 `DataConnectorConnectionCheckRecord`、connector check validator、DataSource/IngestionSkill/ConnectorCheck append-only event replay |
| `app/backend/app/research_os/__init__.py` | 导出新 connector check record/validator |
| `app/backend/app/main.py` | 新增 disabled checker seam、data source / ingestion skill / data connector check Settings API、summary 字段 |
| `app/backend/tests/test_onboarding_gateway.py` | 覆盖 registry replay、成功 check、default disabled、revoked SecretRef no-checker-call、plaintext payload/result no-write |
| `app/frontend/src/pages/SettingsSecurityPage.tsx` | Settings 安全页新增 Data Connectors summary 和按 skill_id 测试连接按钮 |
| `app/frontend/src/pages/SettingsSecurityPage.test.tsx` | 覆盖前端 summary 渲染、button 调用 data_connector_checks、页面不泄露 raw key |
| `dev/state/dreaminate/state.md` / `dev/research/TRACE.md` / `dev/log/dreaminate/log.md` | 落档本地证据与边界 |

## 对抗测试设计（种已知 bug，门必抓）[必填]
1. SecretRef revoked，即使 IngestionSkill 已 paused，也不得调用 connector checker，不写 ConnectorCheck。
2. Settings payload 出现 `api_key` / `sk-...` 明文，422 且不写任何 DataSource/ConnectorCheck 记录。
3. checker result 出现明文 secret，422 且不写 ConnectorCheck。
4. 默认 checker disabled 时返回 `status=disabled` / `health_status=disabled` / `ok=false`，不声称真实连通。
5. fake checker 成功时只写 `check_ref`、status、capability/schema refs、sanitized `response_hash`，summary 不出现 raw key。

## 红线 [按需]
- 不触网、不拉行情、不调用真实 provider，不读取/保存明文 API key。
- 不把 disabled checker 或 fake checker 结果说成真实 provider 连通。
- 不把 DataSourceAsset/ConnectorCheck metadata 写成数据行消费证明。
- 不新增 A股 live 下单路径，不接券商网关。

## 非目标 [按需]
不实现真实 secret value storage、OAuth/device-code/account auth、生产 keystore backend、所有 connector/provider adapters、全资产自动同步、live provider permission proof、行情下载、schema scanner、DatasetVersion 写入、PIT/bitemporal 自动生成或真实 venue permission check。

## 验收一句话 [必填]
Settings API 可以持久化 DataSourceAsset/IngestionSkill，并通过 SecretRef-backed checker seam 记录可审计 data connector connection check；坏 SecretRef/明文/悬空 refs 均 fail-closed，默认 disabled 不冒充连通。

## 完成记录
- `PersistentOnboardingRegistry` 新增 DataSourceAsset / IngestionSkill / DataConnectorConnectionCheck 三类 append-only event，可 JSONL replay。
- 新增 `POST /api/research-os/settings/data_sources`、`/ingestion_skills`、`/data_connector_checks`；summary 返回 `data_sources`、`ingestion_skills`、`data_connector_checks` 及 totals。
- `DATA_CONNECTOR_CONNECTION_CHECKER` 默认 disabled；API 会把 disabled 记录成 `ok=false` 的审计 check，不声称外部 provider 已连通。
- checker 调用前验证 skill/source/SecretRef 已登记且 SecretRef 未 revoked；checker result 若含明文 secret 则 422 且不写 ConnectorCheck。
- Settings 安全页新增 Data Connectors panel，可读取 summary 并按 `skill_id` 触发连接测试，页面只展示 SecretRef/refs/status，不展示 raw key。
- 验证：`pytest app/backend/tests/test_onboarding_gateway.py` **20 passed / 2 warnings**；`pytest app/backend/tests/test_onboarding_gateway.py app/backend/tests/test_llm_custom_and_api.py` **36 passed / 2 warnings**；onboarding/LLM/market-data/spine adjacent **61 passed / 2 warnings**；`python -m compileall app/backend/app/research_os/onboarding_gateway.py app/backend/app/main.py` **PASS**；frontend scoped **2 files / 10 tests passed**；frontend full **27 files / 301 tests passed**；frontend build **tsc + vite PASS**（保留既有 chunk-size warning）。
- 边界：这是 Settings-managed connector metadata + refs-only connection-check seam，不是真实 connector adapter、真实 secret value storage、OAuth/device-code/account auth、行情下载、schema scanner、DatasetVersion 写入、全资产自动同步、live provider permission proof 或 sandbox code 对真实数据行消费的强证明。
