---
uuid: 61053f3d5f1f407baf3218808795a6eb
title: Forecast typed 对象 + StrategyBook typed——模型输出→Signal Contract / payoff·constraints·capital accounting（§9）
status: in_progress
owner: dreaminate
assigned_by: dreaminate
review_status: 0
priority: P1
area: strategy
source: goal
source_ref: GOAL §9 因子/模型/信号/策略边界(行 1454-1542·模型输出登记为 Signal 通过 Signal Contract·StrategyBook 管理组合意图/多腿 long·short/约束/成本/回测计划·绑 payoff/hedge ratio/资本账/风险度量·可证伪:Signal 未绑定 Signal Contract→拒/StrategyBook short intent 被 runtime 当可执行 short 缺 borrow·margin·venue→拒)
depends_on: []
---

# Forecast typed 对象 + StrategyBook typed（§9·typed contract）

## Scope [必填·先读 GOAL §9]
建 §9 两个 typed 对象（A-QRO-2 已在 QRO 层判归属·本卡建本体 typed 契约）：① **Forecast**——模型输出 typed 对象，**经 Signal Contract** 转成 Signal（Forecast→Signal 绑定·非裸输出·量纲/方向/置信度/过期 typed）② **StrategyBook typed**——组合意图/多腿 long·short/约束/成本/回测计划，绑 payoff/hedge ratio/资本账/风险度量；**short intent ≠ runtime 可执行 short**（runtime 须 InstrumentSpec/venue/borrow/margin/regulation 检查·缺则拒）。

## 领地（只动·扩展不替换）
扩 `app/backend/app/strategy/`（forecast.py Forecast typed + strategy_book.py StrategyBook typed·strategy/ 已有 candidate_pool）。**复用** factor_factory/signal_contract（Signal Contract·Forecast→Signal 绑定·不改）、signals/core。**绝不碰** main.py、execution 下单路(OrderGuard 红线)、其他在飞线、signal_contract 实现(只复用)。

## 可证伪验收（种坏门必抓·§9）
1. 模型输出(Forecast)未绑 Signal Contract 进信号层 → 拒（对抗：裸 Forecast→必拒；MUT 放过→红）。
2. StrategyBook short intent 被 runtime 当可执行 short 且缺 borrow/margin/venue 检查 → 拒（red-line·short ≠ 自动可执行）。
3. StrategyBook 缺 payoff/资本账绑定 → 不可晋级（typed 契约完整性）。
4. 正路径：Forecast→Signal Contract→Signal·StrategyBook 带完整 typed 契约 → 放行不误伤。

## 红线 [按需]
Signal 必经 Signal Contract·short intent≠可执行(缺 borrow/margin/venue→拒)·OrderGuard 唯一下单不绕·复用 signal_contract 不另造·扩展不替换·先读 GOAL §9 再动手。无新公式→不强造 MathematicalArtifact。

## 非目标 [按需]
不接真下单(OrderGuard 红线·runtime 执行另卡)；不接 main.py；不建前端。本卡只 Forecast/StrategyBook typed 对象 + Signal Contract 绑定 + short intent 守门。
