---
uuid: d6c4a2b85d084d51a614913ceac8e799
title: IDE promote requires MarketDataUse validation
status: done
owner: dreaminate
assigned_by: dreaminate
review_status: 0
priority: P1
area: research-os-entrypoint-wiring
source: goal-gap
source_ref: GOAL §11 market data use gate -> IDE promote entrypoint
depends_on: [84b1d0c60c2648bbb7a1436f1d151f93, b7c35c8294df484e847b71e33f2ee181]
completed_at: 2026-06-27
---

# IDE promote requires MarketDataUse validation

## Scope [必填]
让 `POST /api/ide/runs/{run_id}/promote` 在读取 sandbox result、写正式 Run artifact、写 BacktestRun QRO 和 Research Graph command 前强制要求 accepted/no-violation `market_data_use_validation_refs`。promote 可继承 sandbox run 记录上的 refs，也可显式传 refs；缺 refs、unknown ref、未 accepted ref 或 violation ref 都必须 422，且不写 promoted run、不写 QRO、不写 Graph command。

## 上下文 / 动机 [按需]
IDE save、run、AI complete 和 Agent strategy synthesis 已接 MarketDataUse gate，但 IDE promote 仍是 sandbox run 进入正式 Run 的入口。若 promote 只检查 `IDERun.status == ok` 和 result shape，旧 run 或无 refs run 仍可能绕过 §11 数据使用门进入正式 Run。

## 接线点（file:line，实现时复核）[必填]
| 文件 | 改什么 |
|---|---|
| `app/backend/app/ide/service.py` | `i_runs` schema/dataclass 持久化 `market_data_use_validation_refs`，旧 SQLite 库自动补列，run 默认继承保存策略 refs |
| `app/backend/app/main.py` | `ide_promote_run` 在读取 result/promote 前复用 IDE MarketDataUse refs validator；promote QRO input/output/lineage/hash 记录 refs |
| `app/backend/tests/test_ide.py` | 覆盖 run refs 持久化与 list/get replay |
| `app/backend/tests/test_strategy_console_s2.py` | 覆盖 promote 成功 QRO refs，以及缺 refs、unknown、unaccepted、violation ref no-promote/no-QRO |
| `app/frontend/src/pages/workshop/IDEPage.tsx` | IDE promote payload 带 `market_data_use_validation_refs` |
| `dev/state/dreaminate/state.md` / `dev/research/TRACE.md` / `dev/log/dreaminate/log.md` | 落档本地证据与边界 |

## 对抗测试设计（种已知 bug，门必抓）[必填]
1. 旧 sandbox run 没有 `market_data_use_validation_refs` -> promote 422，不创建 promoted run 目录，不写 Graph command。
2. promote payload 引用 unknown MarketDataUse validation -> 422，不创建 promoted run 目录，不写 Graph command。
3. promote payload 引用 `accepted=false` validation -> 422，不创建 promoted run 目录，不写 Graph command。
4. promote payload 引用 `accepted=true` 但带 `violation_codes` validation -> 422，不创建 promoted run 目录，不写 Graph command。
5. accepted/no-violation validation -> 写正式 Run，响应和 promoted BacktestRun QRO input/output contract 记录 refs，仍不泄露 source、equity curve、trades、gate verdict 详情或 record name。

## 红线 [按需]
- 不触网、不拉行情、不生成或发送真实 order。
- 不把 MarketDataUse validation 说成 sandbox code 已消费了对应真实 rows。
- 不保存 raw source、equity curve、trades、quantity、price、notional、gate verdict 详情、record name 或 secret 到 promote QRO audit summary。

## 非目标 [按需]
不实现真实 connector、行情下载、live provider permission proof、真实 venue permission check、真实 order emission、完整 strategy code generator 验证、自动组合注入或 sandbox code 对具体数据行的强证明。

## 验收一句话 [必填]
IDE promote 必须在正式 Run artifact 和 promoted BacktestRun QRO 写入前引用 accepted/no-violation MarketDataUse validation；否则 fail-closed 且不产生 promoted run/Graph 副作用。

## 完成记录
- `i_runs` 新增 `market_data_use_validation_refs` 字段，旧 SQLite 库自动补列；`IDEService.run_strategy()` 默认继承 saved strategy refs，也可显式传 refs。
- `POST /api/ide/runs/{run_id}/promote` 在读取 result 和调用 `promote_ide_run()` 前校验 refs；缺 refs、unknown ref、未 accepted ref、violation ref 均 422。
- Promoted BacktestRun QRO input/output contract、lineage、implementation hash 和 assumptions 绑定 `market_data_use_validation_refs`，仍不复制 source、equity curve、trades、gate verdict 详情或 record name。
- IDE 页面 promote payload 优先使用 active run refs，兼容旧 run 时使用当前 refs 输入框。
- 验证：`pytest app/backend/tests/test_ide.py app/backend/tests/test_strategy_console_s2.py` **66 passed / 2 warnings**；market-data/portfolio/execution/delivery/DS adjacent **133 passed / 2 warnings**；`python -m compileall app/backend/app` **PASS**；frontend build **tsc + vite PASS**（保留既有 chunk size warning）。
- 边界：这是 IDE promote 的 refs-only MarketDataUse hard gate，不是真实 connector、行情下载、live provider permission proof、真实 venue permission check、order emission、完整 strategy code generator 验证、自动组合注入或 sandbox code 对真实数据行消费的强证明。
