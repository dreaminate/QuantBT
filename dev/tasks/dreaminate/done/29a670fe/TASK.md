---
uuid: 29a670fe9e8c4a91a590ce17ba8cc36b
title: Settings Stooq public connector preset UI
status: done
owner: dreaminate
assigned_by: dreaminate
review_status: 1
priority: P1
area: settings-data-connector-ui
source: goal
source_ref: GOAL §4 Settings provider wizard residual; TRACE §4 complete Settings/connection wizard residual
depends_on: [76898af4d7454e469dd62179ad18110e]
---

# Settings Stooq public connector preset UI

## Scope [必填]
在 Settings Security 的 Data Connectors 面板新增 Stooq public daily bars preset 登记 UI，直接写 DataSourceAsset + IngestionSkill metadata；不触发 check/run 假绿，不新增密钥表单。

## 上下文 / 动机 [按需]
`76898af4` 已有后端 `stooq` no-auth connector，但用户仍需要手工构造 Settings metadata 才能使用。GOAL §4 要求 Settings provider wizard 支持新增/测试 provider，本卡补一个具体 no-auth preset：Stooq daily OHLCV metadata registration。

## 接线点（file:line，实现时复核）[必填]
| 文件 | 位置 | 改什么(扩展不替换) |
|---|---|---|
| `app/frontend/src/pages/SettingsSecurityPage.tsx` | DataConnectorSettingsPanel | 增加 Stooq draft state、表单和 register 函数，写现有 data_sources / ingestion_skills endpoints |
| `app/frontend/src/pages/SettingsSecurityPage.test.tsx` | Settings connector tests | 覆盖 Stooq preset payload、no-secret、只登记 metadata、不触发 check/run |
| `dev/research/TRACE.md` | §4 行 | 记录 Stooq preset UI 已建，完整 Settings wizard 其他 provider/credential flow 仍保留 |
| `dev/state/dreaminate/state.md`、`dev/log/dreaminate/log.md` | 最新进度 | 落本地验证和边界 |

## 对抗测试设计（种已知 bug，门必抓）[必填]
1. Stooq register payload：source/skill 写现有 endpoints，`connector_config.connector_name=stooq`、`auth_mode=none`、`secret_refs=[]`。
2. No fake green：登记 Stooq metadata 不调用 `data_connector_checks` 或 `ingestion_skill_runs`。
3. No secret UI：payload 和 rendered text 不含 api_key/token/sk-live。

## 复用 [按需]
复用 Generic REST draft 的 Settings registration pattern 和现有 `postJson()` / `refresh()`。

## 红线 [按需]
不新增明文 secret 输入，不调用任何 live execution 或 broker path。

## 非目标 [按需]
不实现完整 provider marketplace、OAuth/device-code/account auth、自动 scheduler、all-asset sync、真实 health monitor 或 run 自动触发。

## 验收一句话 [必填]
Settings UI 可以登记 Stooq no-auth DataSourceAsset/IngestionSkill metadata；登记动作不测试连接、不运行 ingestion、不回显 plaintext secret。

## 完成记录
- `SettingsSecurityPage.tsx` 新增 Stooq public daily bars preset 表单和 register path。
- register path 只调用 `/api/research-os/settings/data_sources` 与 `/api/research-os/settings/ingestion_skills`；payload 固定 `connector_name=stooq`、`auth_mode=none`、`source_type=public_csv`、`secret_refs=[]`。
- 对抗测试覆盖 no-secret、no-check、no-run：`SettingsSecurityPage.test.tsx` 5 passed。

## 验证
- `cd app/frontend && npm test -- SettingsSecurityPage.test.tsx --run`：1 file / 5 tests passed。
- `cd app/frontend && npm test -- --run`：30 files / 333 tests passed。
- `cd app/frontend && npm run build`：PASS（保留既有 Vite chunk-size warning）。
