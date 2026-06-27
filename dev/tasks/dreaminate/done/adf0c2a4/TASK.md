---
uuid: adf0c2a4771f4db8b776edaa1af6da52
title: Settings registry-backed data connector adapter
status: done
owner: dreaminate
assigned_by: dreaminate
review_status: 0
priority: P1
area: research-os-settings-data-connectors
source: goal-gap
source_ref: GOAL §4 Data Onboarding connector adapter; GOAL §11 dataset connector path
depends_on: [4b7e2c19b17d42f5a5346f7dd5c0379a]
completed_at: 2026-06-27
---

# Settings registry-backed data connector adapter

## Scope [必填]
把 Settings Data Connector check/run 从“只能注入 fake/disabled”推进到内置 connector registry adapter：默认 connection checker 用已有 connector `health_check()`，默认 ingestion runner 用同一 connector `fetch()` 产 `FetchResult`，继续走现有 DatasetVersion/schema probe/update 管线。

## 上下文 / 动机 [按需]
`4b7e2c19` 已让 SecretRef value 进入 `SecureKeystore`，但 Settings runner 仍需要外部注入 fake runner 才能产出 DatasetVersion。GOAL §4/§11 还要求内置真实 connector/provider adapter；仓库已有 `TushareConnector`、`BinanceRESTConnector` 和 connector registry，本卡把它们接进 Settings。

## 接线点（file:line，实现时复核）[必填]
| 文件 | 改什么 |
|---|---|
| `app/backend/app/main.py` | 新增 Settings connector-name 推断、keystore-backed connector 实例化、FetchRequest 构造、`SettingsRegistryDataConnectorConnectionChecker`、`SettingsRegistryDataConnectorIngestionRunner`，并设为默认 checker/runner |
| `app/backend/tests/test_onboarding_gateway.py` | 覆盖 Tushare adapter 从 keystore token 做 health check；默认 runner 用 fake Tushare SDK 拉数据并写 DatasetVersion/update |
| `dev/state/dreaminate/state.md` / `dev/research/TRACE.md` / `dev/log/dreaminate/log.md` | 落档本地证据与边界 |

## 对抗测试设计（种已知 bug，门必抓）[必填]
1. Settings adapter 必须从 `SecureKeystore` 取 Tushare token，不读 env 绕过 Settings。
2. connection check 只返回 sanitized status/capability/hash，不回显 token。
3. ingestion runner 必须返回 `FetchResult` 并复用现有 row_count/checksum/plaintext-frame gate。
4. 缺 SecretValue、revoked SecretRef、bad connector result 仍由已有 gate fail-closed。
5. fake SDK 测试不声称外部 Tushare/Binance 实网连通。

## 红线 [按需]
- 不把 adapter seam 说成真实 provider 连通证明。
- 不把 fake Tushare SDK 测试说成已拉真实行情。
- 不在 check/run response、DatasetVersion metadata 或 UI 中回显 token。
- 不绕过现有 DatasetVersion/checksum/schema probe/update gate。

## 非目标 [按需]
不实现 OAuth/device-code/account auth，不选择生产 keyring/HSM backend，不做完整字段映射/PIT wizard，不做全资产自动同步，不证明外部 provider 网络连通。

## 验收一句话 [必填]
Settings 默认 connector check/run 能通过内置 connector registry 和 keystore-backed Tushare adapter 产出 sanitized check 和 DatasetVersion；失败仍不写 partial。

## 完成记录
- 新增 registry-backed Settings connector checker/runner，并设为默认 `DATA_CONNECTOR_CONNECTION_CHECKER` / `DATA_CONNECTOR_INGESTION_RUNNER`。
- Tushare adapter 从 SecretRef declared keystore value 实例化 `TushareConnector(token=...)`；Binance/public connectors 继续走 connector registry。
- Runner 从 skill/request 构造 `FetchRequest`，connector `fetch()` 产 `FetchResult` 后复用现有 DatasetVersion/schema probe/IngestionSkillUpdate 管线。
- 验证：`tests/test_onboarding_gateway.py` **39 passed / 2 warnings**；connectors + asset/onboarding/LLM/market-data/spine/data_quality adjacent **110 passed / 2 warnings**；targeted compileall **PASS**。
- 边界：这是内置 connector registry adapter seam 和 fake SDK 证明，不是外部 Tushare/Binance 实网连通、完整 connector/provider adapter 覆盖、OAuth/device-code/account auth、生产 keyring/HSM 选择、CI、线上或用户验收。
