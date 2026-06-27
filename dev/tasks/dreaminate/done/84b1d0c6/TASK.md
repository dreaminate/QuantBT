---
uuid: 84b1d0c60c2648bbb7a1436f1d151f93
title: IDE strategy run requires MarketDataUse validation
status: done
owner: dreaminate
assigned_by: dreaminate
review_status: 0
priority: P1
area: research-os-entrypoint-wiring
source: goal-gap
source_ref: GOAL §11 market data use gate -> IDE strategy run entrypoint
depends_on: [06b1f745e7d74bf38c76d77392338915, a2a5b61bf5e245cd8179f4fd6854d7ce]
completed_at: 2026-06-27
---

# IDE strategy run requires MarketDataUse validation

## Scope [必填]
让 `POST /api/ide/strategies/{name}/run` 在进入 sandbox run 和写 BacktestRun QRO 前强制要求 accepted/no-violation `market_data_use_validation_refs`。run payload 可显式传 refs；未显式传时可继承已保存策略的 refs。缺 ref、unknown ref、未 accepted ref 或 violation ref 都必须 422，且不生成 `i_runs`、不写 Research Graph command。

## 上下文 / 动机 [按需]
`06b1f745` 已把 MarketDataUse hard gate 接到 IDE strategy save，但保存后的策略仍可能被旧数据或直接 run 请求绕过 run 前门。IDE run 是 BacktestRun QRO 的入口，必须和 save 一样绑定 accepted MarketDataUse validation，避免“策略可保存合规、运行时无数据使用证明”的断层。

## 接线点（file:line，实现时复核）[必填]
| 文件 | 改什么 |
|---|---|
| `app/backend/app/ide/service.py` | IDE strategy 记录持久化 `market_data_use_validation_refs`，SQLite 旧库自动补列，fork 继承 refs |
| `app/backend/app/main.py` | `ide_run_strategy` 在 sandbox 前校验 refs；BacktestRun QRO input/output/lineage/summary 记录 refs |
| `app/backend/tests/test_ide.py` | 覆盖 IDE service 保存/读取 refs |
| `app/backend/tests/test_strategy_console_s2.py` | 覆盖 run 显式/继承 refs 成功路径，以及缺 ref、unknown、unaccepted、violation ref no-write |
| `app/frontend/src/pages/workshop/IDEPage.tsx` | IDE run payload 带 `market_data_use_validation_refs` |
| `dev/state/dreaminate/state.md` / `dev/research/TRACE.md` / `dev/log/dreaminate/log.md` | 落档本地证据与边界 |

## 对抗测试设计（种已知 bug，门必抓）[必填]
1. IDE run 既没有 payload refs，也没有 saved strategy refs -> 422，不写 `i_runs`，不写 Graph command。
2. IDE run 引用 unknown MarketDataUse validation -> 422，不写 `i_runs`，不写 Graph command。
3. IDE run 引用 `accepted=false` validation -> 422，不写 `i_runs`，不写 Graph command。
4. IDE run 引用 `accepted=true` 但带 `violation_codes` validation -> 422，不写 `i_runs`，不写 Graph command。
5. IDE run 引用 accepted/no-violation validation -> sandbox 后写 BacktestRun QRO，响应和 QRO audit summary 暴露 refs 且不泄露 stdout/stderr/result/source。

## 红线 [按需]
- 不触网、不拉行情、不生成或发送真实 order。
- 不把 MarketDataUse validation 说成 sandbox code 已消费了对应真实 rows。
- 不保存 raw data rows、raw code、stdout、stderr、result payload、quantity、price、notional 或 secret 到 QRO audit summary。

## 非目标 [按需]
不实现 strategy builder 全入口接线，不实现真实 connector、行情下载、live provider permission proof、真实 venue permission check、真实 order emission 或 sandbox code 对具体数据行的强证明。

## 验收一句话 [必填]
IDE strategy run 必须在 sandbox 执行和 BacktestRun QRO 写入前引用 accepted/no-violation MarketDataUse validation；否则 fail-closed 且不产生 run/Graph 副作用。

## 完成记录
- `POST /api/ide/strategies/{name}/run` 新增 `market_data_use_validation_refs` hard gate；缺 refs、非 list、空 ref、unknown ref、未 accepted ref、validation 带 violation 均在 `IDEService.run_strategy` 前 422。
- `IDEService` 持久化策略级 `market_data_use_validation_refs`，旧 SQLite 库自动补列；run 可继承 saved refs 或使用显式 payload refs，fork 继承 parent refs。
- BacktestRun QRO input/output contract、lineage、implementation hash 和 audit summary 绑定 `market_data_use_validation_refs`；Graph audit summary 仍不暴露 stdout、stderr、result payload 或 raw source。
- IDE 页面 run payload 带 MarketDataUse refs。
- 验证：`PYTHONPATH=app/backend pytest -q app/backend/tests/test_ide.py app/backend/tests/test_strategy_console_s2.py` -> 59 passed / 2 warnings；market-data/IDE/portfolio/Graph/Agent adjacent scoped -> 124 passed / 2 warnings；`PYTHONPATH=app/backend python -m compileall -q app/backend/app` PASS；`npm --prefix app/frontend run build` PASS（保留既有 chunk size warning）。
- 边界：这是 IDE strategy run 的 refs-only MarketDataUse hard gate，不是 strategy builder 全入口接线、真实 connector、行情下载、live provider permission proof、真实 venue permission check、真实 order emission 或 sandbox code 对数据行消费的强证明。
