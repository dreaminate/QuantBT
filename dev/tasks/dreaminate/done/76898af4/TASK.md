---
uuid: 76898af4d7454e469dd62179ad18110e
title: Settings Stooq public market-data connector
status: done
owner: dreaminate
assigned_by: dreaminate
review_status: 1
priority: P1
area: settings-data-connector
source: goal
source_ref: GOAL §4/§11 data onboarding/provider adapter residual; TRACE §4/§11 more real connector/provider adapter coverage
depends_on: [0fca8ad65f93414eb4ec9d3ea6407d5b]
completed_at: 2026-06-28
---

# Settings Stooq public market-data connector

## Scope [必填]
新增 Stooq no-auth public daily OHLCV connector，并接入 Settings registry-backed connector checker/runner；不接付费账号、不接 live venue、不把公开数据接入说成全资产自动同步。

## 上下文 / 动机 [按需]
TRACE §4/§11 仍保留“更多真实 connector/provider adapter 覆盖”和“全资产自动同步/下游自动注入”残余。现有 Settings runner 已支持 Tushare token、Binance public 和 Generic REST YAML。本卡增加一个具体公开市场数据 adapter：Stooq CSV daily bars，作为 no-auth、read-only、可健康检查/可 fetch 的内置 connector。

## 接线点（file:line，实现时复核）[必填]
| 文件 | 位置 | 改什么(扩展不替换) |
|---|---|---|
| `app/backend/app/connectors/stooq_connector.py` | 新文件 | 实现 `StooqConnector`：describe、health_check、fetch daily OHLCV CSV |
| `app/backend/app/connectors/__init__.py` | default registry | 注册 `stooq` connector 并导出 |
| `app/backend/app/main.py` | Settings connector inference | 允许 `stooq` 从 skill/source/request 推断并走 registry |
| `app/backend/tests/test_onboarding_gateway.py` | Settings connector tests | 覆盖 Stooq no-secret check/run、HTTP fake、DatasetVersion/update 写入、secret 不回显 |
| `dev/research/TRACE.md` | §4/§11 行 | 记录 Stooq public adapter 已建，真实自动同步/更多 provider 仍保留 |
| `dev/state/dreaminate/state.md`、`dev/log/dreaminate/log.md` | 最新进度 | 落本地验证和边界 |

## 对抗测试设计（种已知 bug，门必抓）[必填]
1. No-secret check：Stooq skill `auth_mode=none` 且无 `secret_refs` → connection check 成功时 `secret_refs=[]`，response 不含 token/secret。
2. Fetch/run：fake HTTP 返回 CSV daily bars → ingestion runner 写 DatasetVersion、schema probe、IngestionSkillUpdate，`secret_ref` 使用 `secret:none:stooq`。
3. Unsupported interval：非 `1d`/daily interval → connector fetch 拒绝，不写 DatasetVersion。
4. Secret leakage：Stooq response/detail 若含 plaintext secret marker → checker/runner summary 不回显 secret。

## 复用 [按需]
复用 `DataConnector` / `FetchRequest` / `make_wide_fetch_result`、Settings `SettingsRegistryDataConnectorConnectionChecker`、`SettingsRegistryDataConnectorIngestionRunner` 和现有 DataConnector/IngestionSkillUpdate validators。

## 红线 [按需]
- 只读公开市场数据；不新增交易执行、broker gateway、A股 live 或 order path。
- 不保存 raw credential，不让 token/secret 进入 logs/RAG/export。

## 非目标 [按需]
不实现全资产自动同步、scheduler crawling、商业数据授权判断自动化、live venue permission checks、下游自动注入、真实生产 health monitor 或 UI wizard 新页面。

## 验收一句话 [必填]
Settings 可用内置 `stooq` no-auth connector 完成 check/run；unsupported interval、secret-bearing detail 或 runner failure fail-closed，不写假 DatasetVersion。

## 完成记录（2026-06-28）
- 新增 `app/backend/app/connectors/stooq_connector.py`，实现 `StooqConnector.describe()`、`health_check()` 和 daily OHLCV CSV `fetch()`；只支持 no-auth daily bars，非 daily interval 直接拒绝。
- `app/backend/app/connectors/__init__.py` 注册 `stooq` connector 并导出 `StooqConnector`。
- Settings connector inference 现在能从 skill/source/request 识别 `stooq`，继续走 `SettingsRegistryDataConnectorConnectionChecker` 和 `SettingsRegistryDataConnectorIngestionRunner`，不新增并行 Settings API。
- 测试覆盖：Stooq CSV parser/unsupported interval、Settings no-secret connection check、Settings ingestion run 写 DatasetVersion/schema probe/IngestionSkillUpdate，no-auth update 使用 `secret:none:stooq` 占位且不回显 plaintext token/API key。
- 本地验证：
  - `python -m compileall -q app/backend/app` -> PASS。
  - `python -m pytest app/backend/tests/test_onboarding_gateway.py -q` -> 48 passed / 2 warnings。
  - `python -m pytest app/backend/tests/test_onboarding_gateway.py app/backend/tests/test_asset_lifecycle.py app/backend/tests/test_market_data_contract.py app/backend/tests/test_goal_coverage.py -q` -> 86 passed / 2 warnings。
  - `python -m pytest app/backend/tests -q` -> 1879 passed / 13 skipped / 283 warnings。
  - `python dev/scripts/validate_dev.py` -> PASS（49 ✅ / 0 ❌ / 0 ⚠️；251 cards）。
  - assigned-vs-done duplicate task id check -> no output。
  - `git diff --check` -> PASS。

## 边界
这是 Stooq public daily CSV no-auth connector 和 Settings registry-backed check/run 接线，不是全资产自动同步、scheduler crawling、商业授权自动判断、live venue permission check、下游自动注入、生产 health monitor、线上验收或用户验收。
