---
uuid: 2cee6b45f2304a63ac54855708d5ffbd
title: StrategyBook requires MarketDataUse validation
status: done
owner: dreaminate
assigned_by: dreaminate
review_status: 0
priority: P1
area: research-os-factor-strategy-boundary
source: goal-gap
source_ref: GOAL §11 market data use gate -> §9 StrategyBook boundary
depends_on: [e29078914b9a448ba631837c548a4a16]
completed_at: 2026-06-27
---

# StrategyBook requires MarketDataUse validation

## Scope [必填]
让 `StrategyBookContract` 可携带 `market_data_use_validation_refs`，并在 `validate_strategy_book(..., require_market_data_use_validation=True)` 时强制每个 leg 的 instrument 至少有一个 accepted MarketDataUse validation 覆盖。缺 ref、unknown ref、rejected ref 或 instrument 不匹配都必须 fail-closed。

## 上下文 / 动机 [按需]
`e2907891` 已把 MarketDataUse gate 落成 registry/API/QRO，`0f977f03` 已把它强制接到 ExecutionOrderIntent。StrategyBook 仍可在 §9 层只引用 factor/signal/leg，不引用数据使用验证，导致 strategy assembly 与后续 execution data gate 之间存在断点。

## 接线点（file:line，实现时复核）[必填]
| 文件 | 改什么 |
|---|---|
| `app/backend/app/research_os/factor_strategy_boundary.py` | `StrategyBookContract` 增加 `market_data_use_validation_refs`；`validate_strategy_book` 增加 `market_data_use_validations` / `require_market_data_use_validation` gate |
| `app/backend/tests/test_factor_strategy_boundary.py` | 覆盖 accepted ref success、missing ref、unknown ref、instrument mismatch、not accepted |
| `dev/state/dreaminate/state.md` / `dev/research/TRACE.md` / `dev/log/dreaminate/log.md` | 落档本地证据与边界 |

## 对抗测试设计（种已知 bug，门必抓）[必填]
1. `require_market_data_use_validation=True` 且 StrategyBook 缺 `market_data_use_validation_refs` -> 拒。
2. StrategyBook 引用 unknown MarketDataUse validation -> 拒。
3. StrategyBook 引用 accepted validation 但 validation 的 `instrument_refs` 不覆盖 leg instrument -> 拒。
4. StrategyBook 引用 `accepted=false` 或 `decision_status!=accepted` validation -> 拒。
5. accepted validation 覆盖所有 leg instrument -> 通过。

## 红线 [按需]
- 不触网、不拉行情、不生成或发送真实 order。
- 不把 MarketDataUse validation 说成真实数据已下载、真实 connector 已验证或 live permission 已验证。
- 不保存 raw data rows、raw payload、quantity、price、notional 或 secret。

## 非目标 [按需]
不修改 portfolio promote API，不修改 IDE strategy save/run，不实现 strategy builder 全入口接线，不实现真实 connector 或 venue permission check。

## 验收一句话 [必填]
StrategyBook 在开启 market-data-use hard gate 时必须引用 accepted MarketDataUse validation，且该 validation 覆盖策略 leg instruments；否则 fail-closed。

## 完成记录
- `StrategyBookContract` 新增 `market_data_use_validation_refs`，保持默认空 tuple，未开启 hard gate 的既有调用不变。
- `validate_strategy_book` 新增 `market_data_use_validations` 与 `require_market_data_use_validation`；开启后每个 StrategyBook leg instrument 必须被 accepted `MarketDataUseValidationRecord.instrument_refs` 覆盖。
- validator 会拒 unknown validation ref、未 accepted validation、validation 自身 violation 和 instrument 不覆盖；错误码包括 `missing_market_data_use_validation_record`、`market_data_use_not_accepted`、`market_data_use_has_violations`、`missing_market_data_use_validation`。
- 测试覆盖：accepted ref success、缺 ref、unknown ref、instrument mismatch、not accepted。
- 验证：`PYTHONPATH=app/backend pytest -q app/backend/tests/test_factor_strategy_boundary.py` -> 16 passed；market-data/factor-lab/portfolio/model adjacent scoped -> 90 passed / 2 warnings。
- 边界：这是 StrategyBook runtime validator 的 MarketDataUse hard gate，不是 portfolio promote API 接线、IDE strategy save/run 接线、strategy builder 全入口接线、真实 connector、行情下载或 live provider permission proof。
