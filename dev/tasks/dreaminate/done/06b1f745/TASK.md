---
uuid: 06b1f745e7d74bf38c76d77392338915
title: IDE strategy save requires MarketDataUse validation
status: done
owner: dreaminate
assigned_by: dreaminate
review_status: 0
priority: P1
area: research-os-entrypoint-wiring
source: goal-gap
source_ref: GOAL §11 market data use gate -> IDE strategy save entrypoint
depends_on: [e29078914b9a448ba631837c548a4a16, b1b48097341547f09d84b6509acf778f]
completed_at: 2026-06-27
---

# IDE strategy save requires MarketDataUse validation

## Scope [必填]
让 `POST /api/ide/strategies` 在保存策略草稿和写 StrategyBook QRO 前强制要求 `market_data_use_validation_refs`。每个 ref 必须 resolve 到 accepted `MarketDataUseValidationRecord`，且不能带未解决 violation；缺 ref、unknown ref、未 accepted ref 或 violation ref 都必须 422，且不保存 IDE strategy、不写 Research Graph command。

## 上下文 / 动机 [按需]
`e2907891` 已把 MarketDataUse gate 落成 registry/API/QRO；`0f977f03`、`2cee6b45`、`0a0dc8c5` 已分别把它接到 ExecutionOrderIntent、StrategyBook validator、portfolio promote。IDE strategy save 仍能写 StrategyBook QRO，但没有把策略草稿绑定到 accepted MarketDataUse validation，导致 IDE 入口与 §11 数据使用门之间断开。

## 接线点（file:line，实现时复核）[必填]
| 文件 | 改什么 |
|---|---|
| `app/backend/app/main.py` | `ide_save_strategy` 保存前校验 `market_data_use_validation_refs`；StrategyBook QRO input/output/lineage/summary 记录 refs |
| `app/backend/tests/test_strategy_console_s2.py` | HTTP fixture 提供 accepted MarketDataUse validation；覆盖缺 ref、unknown ref、unaccepted ref、violation ref no-write |
| `app/frontend/src/pages/workshop/IDEPage.tsx` | IDE 保存表单显式填写 MarketDataUse refs，保存 payload 带 refs；自动 run 在保存失败时停止 |
| `dev/state/dreaminate/state.md` / `dev/research/TRACE.md` / `dev/log/dreaminate/log.md` | 落档本地证据与边界 |

## 对抗测试设计（种已知 bug，门必抓）[必填]
1. IDE save 缺 `market_data_use_validation_refs` -> 422，不保存 strategy，不写 Graph command。
2. IDE save 引用 unknown MarketDataUse validation -> 422，不保存 strategy，不写 Graph command。
3. IDE save 引用 `accepted=false` validation -> 422，不保存 strategy，不写 Graph command。
4. IDE save 引用 `accepted=true` 但带 `violation_codes` validation -> 422，不保存 strategy，不写 Graph command。
5. IDE save 引用 accepted/no-violation validation -> 保存成功，返回 refs，StrategyBook QRO audit summary 暴露 refs 且不泄露 code/description。

## 红线 [按需]
- 不触网、不拉行情、不生成或发送真实 order。
- 不把 MarketDataUse validation 说成真实数据已下载、IDE run 已消费 refs、真实 connector 已验证或 live permission 已验证。
- 不保存 raw data rows、raw code、raw description、quantity、price、notional 或 secret 到 QRO audit summary。

## 非目标 [按需]
不修改 IDE service schema，不让 IDE run 自动继承或强制 MarketDataUse refs，不实现 strategy builder 全入口接线，不实现真实 connector、行情下载、live provider permission proof 或 venue permission check。

## 验收一句话 [必填]
IDE strategy save 必须在持久化策略草稿和写 StrategyBook QRO 前引用 accepted/no-violation MarketDataUse validation；否则 fail-closed 且不产生 strategy/Graph 副作用。

## 完成记录
- `POST /api/ide/strategies` 新增 `market_data_use_validation_refs` hard gate；缺 refs、非 list、空 ref、unknown ref、未 accepted ref、validation 带 violation 均在 `IDEService.save_strategy` 前 422。
- StrategyBook QRO input/output contract、lineage 和 implementation hash 绑定 `market_data_use_validation_refs`；Graph audit allowlist 暴露该 refs 字段，但仍不暴露 raw code 或 description。
- IDE 页面新增 MarketDataUse refs 输入，保存 payload 带 refs；`run()` 自动保存失败时不继续调用 run endpoint，且新策略首次 run 使用 save 返回的真实策略名。
- 验证：`PYTHONPATH=app/backend pytest -q app/backend/tests/test_strategy_console_s2.py` -> 32 passed / 2 warnings；market-data/portfolio/Graph/Agent adjacent scoped -> 97 passed / 2 warnings；`PYTHONPATH=app/backend python -m compileall -q app/backend/app` PASS；`npm --prefix app/frontend run build` PASS（保留既有 chunk size warning）。
- 边界：这是 IDE strategy save 的 refs-only MarketDataUse hard gate，不是 IDE run 强制 gate、strategy builder 全入口接线、真实 connector、行情下载、live provider permission proof、真实 venue permission check 或 order emission。
