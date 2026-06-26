---
uuid: 0850cc54134d473ba68cb184920566d8
title: InstrumentSpec 本体 + MarketCapabilityMatrix——多资产 typed（期权 expiry/strike/期货 roll/债 duration/FX）（§11）
status: in_progress
owner: dreaminate
assigned_by: dreaminate
review_status: 0
priority: P1
area: instruments
source: goal
source_ref: GOAL §11 数据层与标的接入(行 1610-1765·InstrumentSpec·期权/期货/债券/FX/商品语义·MarketCapabilityMatrix·可证伪:期权策略缺 expiry/strike/multiplier/settlement→拒·MarketCapabilityMatrix 缺 live 权限仍尝试 live→拒·跨币种缺 base currency/FX conversion→拒)；Forecast/StrategyBook(61053f3d)用 instrument_spec_ref 承载待本体
depends_on: []
---

# InstrumentSpec 本体 + MarketCapabilityMatrix（§11·多资产 typed·解锁头号 gap）

## Scope [必填·先读 GOAL §11]
建 §11 **InstrumentSpec typed 本体 + MarketCapabilityMatrix**：① InstrumentSpec——每资产类 typed 字段（期权 expiry/strike/multiplier/settlement·期货 roll/settlement·债 duration/convexity·FX rollover/base currency·商品 contract spec）② MarketCapabilityMatrix——记录每标的/市场的能力（live 权限/可执行性/数据可得）。GOAL §11 给了每类语义·照建 typed。**A-QRO-2/Forecast(61053f3d) 已用 instrument_spec_ref 字符串承载·本卡建本体后下游回填。**

## 领地（greenfield·只动·扩展不替换）
新 `app/backend/app/instruments/`（spec.py InstrumentSpec typed per asset_class + capability.py MarketCapabilityMatrix）。**复用** lineage/ids（身份）。**绝不碰** main.py、execution 下单路(OrderGuard·A股不实盘红线)、其他在飞线、strategy/(只被引用)。

## 可证伪验收（种坏门必抓·§11）
1. 期权策略/spec 缺 expiry/strike/multiplier/settlement → 拒（MUT 放过→红）。
2. MarketCapabilityMatrix 缺 live 权限仍尝试 live → 拒（**A股 live=恒拒·RULES.project**）。
3. 跨币种缺 base currency / FX conversion → 拒。
4. 各资产类 typed 字段齐 → 正常（正路径不误伤·typed 引用可回填 Forecast/StrategyBook）。

## 红线 [按需]
单一身份源 ids.py 不另造·扩展不替换·**A股 live 恒拒(MarketCapabilityMatrix 不开 A股 live·RULES.project 永不实盘)**·OrderGuard 不绕·先读 GOAL §11 再动手·**§11 多资产范围 GOAL §0 已决(所有公开二级市场)·照建不问**。无新公式→不强造 MathematicalArtifact。

## 非目标 [按需]
不接真下单(execution·OrderGuard)；不接 main.py；不建前端。本卡只 InstrumentSpec typed 本体 + MarketCapabilityMatrix + 可证伪门。
