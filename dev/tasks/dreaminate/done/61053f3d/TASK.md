---
uuid: 61053f3d5f1f407baf3218808795a6eb
title: Forecast typed 对象 + StrategyBook typed——模型输出→Signal Contract / payoff·constraints·capital accounting（§9）
status: done
owner: dreaminate
assigned_by: dreaminate
review_status: 1
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

## 实现落账（done · 2026-06-26 · 第七波 wave7/forecast-strategybook）

**新增（纯 additive·扩展不替换·只动 strategy/）**
- `app/backend/app/strategy/forecast.py` — `Forecast`(pydantic typed：symbol/model_ref/source_lib/output_kind/horizon/value/unit/direction/confidence/event_time/effective_at/valid_until/leakage/signal_contract_id) + `bind_forecast_to_signal()` 四道门 + `Forecast.register_contract()`(复用 SignalContractRegistry 登记·不重造)。
- `app/backend/app/strategy/strategy_book.py` — `StrategyBook` typed + `StrategyLeg`/`PayoffSpec`/`CapitalAccount`/`ShortExecutionRequirement`；`assert_promotable()`(payoff/资本账/linked_assets 晋级门) + `assert_runtime_executable()`(short intent≠可执行 short 执行门，A股 short 硬拒 R13)。
- `app/backend/app/strategy/__init__.py` — additive 导出(保留 candidate_pool)。
- `app/backend/tests/test_forecast_strategybook_goal.py` — 21 对抗+正路径测试。

**复用不改**：`factor_factory/signal_contract`(SignalContractRegistry/compute_signal_id/LeakageDeclaration·Forecast→Signal 绑定走它) · `signals/core`(Signal/FactorAttribution) · `lineage/ids.content_hash`(book_id 单一哈希族) · `strategy_goal.Constraints`(约束单一源·不另造第三个 Constraints)。

**契约路径**：Forecast →(register_contract 经 Signal Contract 三门：范畴/血统/泄露声明 R18)→ signal_contract_id →(bind_forecast_to_signal 四门：裸输出/孤儿/伪绑定/过期)→ `signals.core.Signal`。裸 Forecast 直进信号层 = 拒。

**测试汇总**：`app/backend/tests/test_forecast_strategybook_goal.py` → **21 passed (1.33s)**；reuse 上游(signal_contract 消费者 r18/qro/factor_lab + signals + strategy_goal)合跑 **140/36 passed** 未破。全量 collect-only **2306**(= main 基线 2285 + 本卡 21·无 collection 破坏)。

**MUT 变异验证（绝不 git checkout·Edit 种坏门→看红→Edit 还原）**：
- MUT-A 删 `bind_forecast_to_signal` 门1(裸输出门)→ `test_bare_forecast_unbound_rejected` 红(AttributeError≠ForecastError)→ 还原回绿。
- MUT-B 删 `ShortExecutionRequirement.missing()` 的 borrow 检查 → `test_short_intent_missing_each_requirement_rejected[borrow]` 红(borrow 不再入 missing) → 还原回绿。
两道核心红门均"种坏必抓"，非纸门。

**红线合规**：Signal 必经 Signal Contract(裸 Forecast 拒·门1) · short intent≠可执行(缺 borrow/margin/venue/instrument/regulation 逐项拒·A股 short 硬拒 R13) · OrderGuard 唯一下单不绕(本卡只 typed 守门·不下单·诚实标注 runtime 接线另卡) · 复用 signal_contract 不另造 · 扩展不替换 · 无新公式不造 MathematicalArtifact(仅留 PayoffSpec.theory_binding_ref 前向槽)。

**诚实残余**：① runtime 真实执行接线(StrategyBook short → OrderGuard/venue/borrow 真检查)是另一张卡，本卡 `assert_runtime_executable` 只做 typed 守门、过门≠已下单。② `InstrumentSpec` 全库尚无 typed 类(§11 概念)，本卡用 `ShortExecutionRequirement.instrument_spec_ref` 承载引用，待 InstrumentSpec 本体卡建后回填。③ 测试文件落 `app/backend/tests/`(全仓 testpaths 唯一惯例)，非 strategy/ 内——属交付本卡可证伪验收必需的 additive 新文件，未改任何既有测试。
