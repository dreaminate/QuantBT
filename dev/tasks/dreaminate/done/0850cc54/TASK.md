---
uuid: 0850cc54134d473ba68cb184920566d8
title: InstrumentSpec 本体 + MarketCapabilityMatrix——多资产 typed（期权 expiry/strike/期货 roll/债 duration/FX）（§11）
status: done
owner: dreaminate
assigned_by: dreaminate
review_status: 1
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

## 实现落账（done · 2026-06-26 · 隔离 worktree → 分支 wave8/instrument-spec）

**新建文件（greenfield·只动 instruments/ + 1 新测试，零碰禁区）：**
- `app/backend/app/instruments/spec.py` — InstrumentSpec typed 本体：基类（身份/PIT/血统/跨币种门）+ 9 个资产类 typed 子类（Equity / Bond / Future / Option / Fx / Commodity / CryptoSpot / CryptoPerp / Generic），pydantic v2 判别式联合（discriminator=spec_kind）+ `parse_instrument_spec` 工厂门 + `FxConversion` + 跨币种结算门 `assert_currency_settleable`。
- `app/backend/app/instruments/capability.py` — MarketCapabilityMatrix：`MarketCapability`（§11 全字段 typed：可达环境/能力/可得性/permission_requirement）+ `MarketCapabilityMatrix`（按 (asset_class, market) 索引，未登记 deny-by-default）+ live 门 `assert_can_execute`。
- `app/backend/app/instruments/__init__.py` — 包导出（28 个公共符号）。
- `app/backend/tests/test_instrument_spec.py` — 33 条对抗 + 正路径测试。

**单一源复用（扩展不替换·零另造）：**
- 身份：`spec_id`/`capability_id` 复用 `lineage.ids.content_hash`（单一哈希族，前缀 instr_/cap_ + 截断，沿用 strategy_book book_[:10] 先例），排除装饰字段（改名不算新标的）。
- A股 live 恒拒：**复用 `security.gate.policy.classify`**（执行权限分级的权威源）——A股/equity/CN token → 恒 PAPER。`live_forbidden()` 即 `classify(...)==PAPER`，**不另造第二本 A股账**（避免与执行门漂移）。仅读不改 policy.py。
- 下游回填：`InstrumentSpec.spec_ref`（= spec_id，非空 str）可直接填 `strategy_book.ShortExecutionRequirement.instrument_spec_ref`（已用测试验证回填后 short 腿过 runtime 执行门）；strategy_book 只被引用、未改一字。

**可证伪验收逐条（4/4 达成 · 真测试 33 passed · MUT 三门均验证抓红后手工还原）：**
1. 期权缺 expiry/strike/contract_multiplier/settlement → 构造期拒（required field + gt=0 + 工厂门统一抛 InstrumentSpecError）；MUT 把 expiry 改可选 → 2 测试转红，确认必抓。
2. 缺 live 权限仍尝试 live → 拒；A股 live 恒拒**不可被伪造 live=True + 权限齐 + execution available 绕过**（先过 live_forbidden 硬墙）；MUT 删硬墙 → 2 测试转红。`effective_live_permission()` 诚实给真相（A股声明 live → 实际 False）。
3. 跨币种缺 base currency / 缺 FX conversion / 桥接不匹配 → 拒；MUT 删缺-conversion 检查 → 1 测试转红。
4. 9 资产类 typed 齐 → 全构造成功、spec_id 唯一；crypto live（权限齐）过门、A股 paper 过门——正路径不误伤。

**红线合规：** 单一身份源不另造（复用 content_hash + classify）✓；扩展不替换（纯新增 4 文件，0 改既有）✓；A股 live 恒拒（matrix 不开 A股 live，硬墙复用 classify 单一源）✓；OrderGuard 不绕（本层仅 typed 研究/能力门，文档明示「过门≠已下单，真实下单仍只走 OrderGuard」）✓；无新公式不造 MathematicalArtifact（duration/convexity/Greeks 仅作声明值/前向 ref 槽，不推导）✓。

**基线：** collect 2460(基线·与 main 一致) → 2493(+33 新测试，未破基线)；新测试文件 33 passed；相邻既有套件（policy/gate/instrument/strategy/ashare/live/lineage 关键词）660 passed 0 failed，无回归。仅跑 scoped，未跑全量（中心负责全量 + land）。

**拍板项命中：** §11 多资产范围 = GOAL §0 已决（所有公开二级市场），照建未问；A股 live 恒拒 = RULES.project 红线，照守。本卡未撞 decisions 未覆盖的新岔路。

**诚实残余（交中心/后续卡）：**
- `instruments.AssetClass`（§0 全目录，19 token）与 `strategy_goal.AssetClass`（窄·成本派发 4 token）并存：mine 为其超集、token 兼容、已文档化关系；如需收敛成单枚举须改 strategy_goal（本卡领地外·referenced-only），留给后续整合卡。
- InstrumentSpec 只钉合约条款，不算 Greeks/IV/久期数值（定价/风险引擎是另一层）；宏观/链上/另类/自定义**数据**归 Observable/Dataset（数据层卡），本卡不为其造 spec。
- 下游回填是**能力就绪**（spec_ref 可填 instrument_spec_ref，测试已验证兼容），实际把 Forecast/StrategyBook 的字符串 ref 批量回填进库是消费侧动作，非本本体卡范围。
