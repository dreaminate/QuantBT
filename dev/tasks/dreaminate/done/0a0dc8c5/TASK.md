---
uuid: 0a0dc8c5e3fa4276a2f5ed1bb14a6b27
title: Portfolio promote requires MarketDataUse validation
status: done
owner: dreaminate
assigned_by: dreaminate
review_status: 0
priority: P1
area: research-os-portfolio-gate
source: goal-gap
source_ref: GOAL §11 market data use gate -> portfolio production promote
depends_on: [e29078914b9a448ba631837c548a4a16]
completed_at: 2026-06-27
---

# Portfolio promote requires MarketDataUse validation

## Scope [必填]
让 `/api/portfolios/{portfolio_id}/promote` 在消耗 honest-N 和写 gate record 前强制要求 `market_data_use_validation_refs`。每个 portfolio symbol 必须被 accepted `MarketDataUseValidationRecord.instrument_refs` 覆盖；缺 ref、unknown ref、未 accepted ref、validation 自带 violation 或 symbol 不覆盖都 422 且不记账。

## 上下文 / 动机 [按需]
`ba59fb7b` 已把 portfolio production promote 接成 `record=True` 一本账；`2c9f4e11` 已要求 portfolio 声明 signal_refs 时匹配 accepted signal validation；`e2907891` 已把 MarketDataUse gate 落成 registry/API/QRO。当前 promote 仍只校验 `dataset_version` 字符串和收益序列结构，未验证这些收益/标的有 accepted MarketDataUse validation。

## 接线点（file:line，实现时复核）[必填]
| 文件 | 改什么 |
|---|---|
| `app/backend/app/main.py` | portfolio promote 新增 MarketDataUse validation gate，返回 `market_data_use_validation_refs` |
| `app/backend/tests/test_portfolio_promote_api.py` | fixture 提供 accepted MarketDataUse validation；覆盖缺 ref、unknown ref、unaccepted ref、symbol mismatch no-write |
| `dev/state/dreaminate/state.md` / `dev/research/TRACE.md` / `dev/log/dreaminate/log.md` | 落档本地证据与边界 |

## 对抗测试设计（种已知 bug，门必抓）[必填]
1. production promote 缺 `market_data_use_validation_refs` -> 422，honest-N 不增加。
2. unknown MarketDataUse validation ref -> 422，honest-N 不增加。
3. MarketDataUse validation `accepted=false` 或带 `violation_codes` -> 422，honest-N 不增加。
4. MarketDataUse validation 不覆盖 portfolio symbol -> 422，honest-N 不增加。
5. accepted MarketDataUse validation 覆盖全部 symbols -> promote 通过并返回 refs。

## 红线 [按需]
- 不触网、不拉行情、不生成或发送真实 order。
- 不把 MarketDataUse validation 说成真实数据已下载、真实 connector 已验证或 live permission 已验证。
- 不保存 raw data rows、raw payload、quantity、price、notional 或 secret。

## 非目标 [按需]
不修改 StrategyBook validator，不修改 IDE strategy save/run，不实现 strategy builder 全入口接线，不实现真实 connector 或 venue permission check。

## 验收一句话 [必填]
Portfolio production promote 必须在 record=True 记账前引用 accepted MarketDataUse validation 覆盖所有 portfolio symbols；否则 fail-closed 且 honest-N 不变。

## 完成记录
- `/api/portfolios/{portfolio_id}/promote` 新增 `market_data_use_validation_refs` hard gate；缺 refs、unknown ref、未 accepted ref、validation 带 violation、symbol 不覆盖均在 `gate_portfolio` 与 honest-N 消耗前 422。
- gate 通过后 response 返回 `market_data_use_validation_refs`，并继续保持 `boundary` 为 no order / no money movement / no stage flip。
- `app/backend/tests/test_portfolio_promote_api.py` fixture 默认提供 accepted MarketDataUse validation；新增缺 ref、unknown ref、unaccepted ref、symbol mismatch no-write 覆盖。
- 验证：`PYTHONPATH=app/backend pytest -q app/backend/tests/test_portfolio_promote_api.py` -> 12 passed / 2 warnings；market-data/factor/portfolio/model/Graph/entrypoint adjacent scoped -> 124 passed / 2 warnings。
- 边界：这是 portfolio production promote 的 refs-only MarketDataUse hard gate，不是 strategy builder 全入口接线、IDE strategy save/run 接线、真实 connector、行情下载、live provider permission proof、真实 venue permission check 或 order emission。
