---
uuid: 224e986593fb424bbe406170c22f050c
title: Settings Binance public connector preset UI
status: done
owner: dreaminate
assigned_by: dreaminate
review_status: 1
priority: P1
area: settings-data-connector-ui
source: goal
source_ref: GOAL §4 Settings provider wizard residual; TRACE §4 complete Settings/connection wizard residual
depends_on: [a6dcb50f085e4af79dbd013c578dc2fc]
---

# Settings Binance public connector preset UI

## Scope [必填]
在 Settings Security 的 Data Connectors 面板新增 Binance public REST preset 登记 UI，直接写 DataSourceAsset + IngestionSkill metadata；不触发 check/run，不新增密钥表单。

## 上下文 / 动机 [按需]
`a6dcb50f` 已有 Binance public no-auth connector path，`29a670fe` 已给 Stooq 补 no-auth preset UI。GOAL §4 仍保留完整 Settings provider wizard residual；本卡补第二个具体 no-auth provider preset，让用户可以从 Settings 登记 Binance Spot/USDM public klines metadata。

## 接线点（file:line，实现时复核）[必填]
| 文件 | 位置 | 改什么(扩展不替换) |
|---|---|---|
| `app/frontend/src/pages/SettingsSecurityPage.tsx` | DataConnectorSettingsPanel | 增加 Binance public draft state、表单和 register 函数，写现有 data_sources / ingestion_skills endpoints |
| `app/frontend/src/pages/SettingsSecurityPage.test.tsx` | Settings connector tests | 覆盖 Binance preset payload、no-secret、只登记 metadata、不触发 check/run |
| `dev/research/TRACE.md` | §4 行 | 记录 Binance preset UI 已建，完整 Settings wizard 其他 provider/credential flow 仍保留 |
| `dev/state/dreaminate/state.md`、`dev/log/dreaminate/log.md` | 最新进度 | 落本地验证和边界 |

## 对抗测试设计（种已知 bug，门必抓）[必填]
1. Binance register payload：source/skill 写现有 endpoints，`connector_config.connector_name=binance_rest_spot` 或 `binance_rest_usdm`、`auth_mode=none`、`secret_refs=[]`。
2. No fake green：登记 Binance metadata 不调用 `data_connector_checks` 或 `ingestion_skill_runs`。
3. No secret UI：payload 和 rendered text 不含 api_key/token/sk-live。

## 复用 [按需]
复用 Stooq draft / Generic REST registration pattern 和现有 Settings endpoints。

## 红线 [按需]
不新增明文 secret 输入，不调用任何 live execution 或 broker path，不把 public REST metadata 登记说成真实网络连通或 ingestion 成功。

## 非目标 [按需]
不实现完整 provider marketplace、OAuth/device-code/account auth、自动 scheduler、all-asset sync、真实 health monitor、run 自动触发或 Binance testnet/live trading。

## 验收一句话 [必填]
Settings UI 可以登记 Binance public no-auth DataSourceAsset/IngestionSkill metadata；登记动作不测试连接、不运行 ingestion、不回显 plaintext secret。

## 完成记录
- `SettingsSecurityPage.tsx` 新增 Binance public REST preset 表单和 register path。
- register path 只调用 `/api/research-os/settings/data_sources` 与 `/api/research-os/settings/ingestion_skills`；Spot/USDM market 映射到 `binance_rest_spot` / `binance_rest_usdm`，payload 固定 `auth_mode=none`、`source_type=public_api`、`secret_refs=[]`。
- 对抗测试覆盖 no-secret、no-check、no-run：`SettingsSecurityPage.test.tsx` 6 passed。

## 验证
- `cd app/frontend && npm test -- SettingsSecurityPage.test.tsx --run`：1 file / 6 tests passed。
- `cd app/frontend && npm test -- --run`：30 files / 334 tests passed。
- `cd app/frontend && npm run build`：PASS（保留既有 Vite chunk-size warning）。
