---
uuid: a6dcb50f085e4af79dbd013c578dc2fc
title: Settings Binance public connector adapter coverage
status: done
owner: dreaminate
assigned_by: dreaminate
review_status: 0
priority: P1
area: research-os-settings-data-connectors
source: goal-gap
source_ref: GOAL §4 Data Onboarding connector adapter; GOAL §11 multi-market data connector path
depends_on: [adf0c2a4771f4db8b776edaa1af6da52]
completed_at: 2026-06-27
---

# Settings Binance public connector adapter coverage

## Scope [必填]
把 Settings registry-backed connector adapter 从 Tushare SecretRef path 扩到 Binance public REST path：Settings 能通过 `binance_rest_spot` / `binance_rest_usdm` 做 sanitized connection check，并通过同一 runner 拉 OHLCV/funding `FetchResult` 写 DatasetVersion/update。

## 上下文 / 动机 [按需]
`adf0c2a4` 已证明 Tushare adapter 能从 Settings keystore token 走 `health_check()` / `fetch()`。GOAL §4/§11 仍要求完整 connector/provider adapter 覆盖；下一条硬证据应覆盖 public no-auth connector，确认 no-secret connector 不被 SecretValue gate 错拦，也不默认触网冒充实网证明。

## 接线点（file:line，实现时复核）[必填]
| 文件 | 改什么 |
|---|---|
| `app/backend/app/research_os/onboarding_gateway.py` | 新增显式 no-auth connector 判定，只有 `auth_mode=none/no_auth/public` 且无 SecretRef 时允许 empty `secret_refs` check |
| `app/backend/app/main.py` | Settings connector resolver 对 `binance_rest_spot` / `binance_rest_usdm` 构造 `BinanceRESTConnector`；no-auth ingestion update 写 `secret:none:<connector>` 审计占位 |
| `app/backend/tests/test_onboarding_gateway.py` | 用 fake Binance connector method 覆盖 Settings connection check + ingestion run + DatasetVersion/update |
| `dev/state/dreaminate/state.md` / `dev/research/TRACE.md` / `dev/log/dreaminate/log.md` | 落档 Binance public adapter 的本地 proof 与边界 |

## 对抗测试设计（种已知 bug，门必抓）[必填]
1. Binance public connector 不需要 SecretValue，不应被 declared-keystore gate 错拦。
2. Settings check/run 必须走 connector `health_check()` / `fetch()`，不能回落 fake success。
3. fake Binance response 不得被写成外部 provider 实网连通证明。
4. run 必须复用 DatasetVersion/checksum/schema probe/update gate。
5. response、DatasetVersion metadata 和 QRO summary 不能回显 API key/secret 或 raw venue payload。

## 红线 [按需]
- 不把 fake method 测试说成真实 Binance REST 网络连通。
- 不新增 live trading、broker connector、venue submit 或 A股 live path。
- 不绕过 existing connector registry、DatasetVersion gate 或 secret/no-secret gate。

## 非目标 [按需]
不实现完整 provider catalog、OAuth/device-code/account auth、生产 keyring/HSM、真实 Binance testnet key 连通、venue permission proof、全资产自动同步或完整 connection wizard。

## 验收一句话 [必填]
Settings 默认 adapter 能对 Binance public REST connector 做 sanitized check 和 ingestion run，写入 DatasetVersion/update；测试只证明本地 fake method seam，不证明实网连通。

## 完成记录
- 新增 `ingestion_skill_allows_no_secret_connector()`，只在 `auth_mode=none/no_auth/public`、无 `auth_ref`、无 `secret_refs` 时允许 no-auth connector check。
- Settings connector resolver 显式支持 `binance_rest_spot` / `binance_rest_usdm`，构造 `BinanceRESTConnector` 后走 `health_check()` / `fetch()`。
- no-auth ingestion update 写 `secret:none:<connector_name>`，保留 `IngestionSkillUpdateRecord.secret_ref` 审计字段，同时不要求真实 SecretRef。
- 验证：`tests/test_onboarding_gateway.py` **41 passed / 2 warnings**；connectors + asset/onboarding/LLM/market-data/spine/data_quality adjacent **112 passed / 2 warnings**；targeted compileall **PASS**。
- 边界：这是 Binance public connector no-auth seam 和 fake method proof，不是真实 Binance REST 实网连通、真实 Binance testnet key、venue permission proof、完整 provider adapter catalog、CI、线上或用户验收。
