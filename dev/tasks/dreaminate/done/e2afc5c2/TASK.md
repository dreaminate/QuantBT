---
uuid: e2afc5c239fa46c3a56a0bdfc730a48e
title: 三档成本预设接 sqrt-impact 默认 + 成交报告 impact 成本归因拆字段
status: done
owner: dreaminate
assigned_by: dreaminate
review_status: 0
priority: P2
area: execution-cost
source: goal-gap
source_ref: 卡 7179ba36（sqrt-impact）消费侧残余；评审 CEO「对的东西没接到用户」+ eng 成本归因
depends_on: [7179ba36278e4091a8e29b4d58336525]
---

# 三档成本预设接 sqrt-impact 默认 + impact 成本归因拆字段

> **状态（2026-06-26 · 本卡收口 done）**：
> - **② 成本归因拆字段 ✅ done（前置已 land）**：done 卡 6e264c59 / commit c7a56be（已进 origin/main）。
>   `cost_breakdown` impact 单列、commission=total 向后兼容、求和守恒、MUT-C 有牙。本轮**复跑验证仍绿**
>   （test_sqrt_impact_cost.py 26 passed），**未改其代码**（byte-identical to HEAD）。
> - **① 三档预设接 sqrt-impact ✅ done（做成 opt-in·默认不翻）**：新建 `execution/cost_presets.py` 把 §M1 三档
>   声明式预设 → 引擎 `BacktestCostModel`，把 R18 平方根冲击做成**显式 opt-in**：**生产默认仍关**（impact_model
>   默认 'linear'→冲击恒 0、逐位不变），启用须用户**两个显式动作**（预设 impact_model='sqrt' + 调用方传 Y）。
>   **不替用户拍方法学**：Y 无万能默认、绝不烤死；δ=0.5 文献默认随转换流入。
> - **拍板项（摆代价不替拍）**：三档预设是否**默认**翻 size-aware = 用户方法学决策（GOAL §10「方法学松紧=用户」），
>   本卡**只建 opt-in 路、默认不动**，代价见下「拍板项」节。

## Scope [必填]
卡 7179ba36 的 sqrt-impact 默认关、需用户显式启用。本卡：① 把 size-aware 平方根冲击接进**三档成本预设**
（GOAL §M9.2），让生产回测**可以** size-aware（大资金不再系统性过优）；② 成交报告里成本拆**结构化字段**
（commission/slippage/stamp/transfer/impact 分列或 cost_breakdown 子字典），保留 commission 合计向后兼容，
让 impact 可单独归因（现并入 commission 字段，下游按字段名归因会误读）。

## 上下文 / 动机 [按需]
评审 CEO：sqrt-impact 数学/命门已立但默认关、未接生产预设 → 用户用不到。eng：fill 报告 impact 并入 commission 字段、下游误读。依赖 P2 卡 0f696e56（无泄露自估）先落，生产默认启用才安全。

## 接线点（file:line，实现复核）[必填]
| 文件 | 位置 | 接什么 |
|---|---|---|
| app/execution/backtest_venue.py | _cost_breakdown / fill 报告 | 成本拆结构化字段（含 impact 列）·**②·c7a56be 已落·本轮未改** |
| app/execution/cost_presets.py（**新建·本卡 ①**） | `to_backtest_cost_model` / `backtest_cost_model_for` | 三档预设 → `BacktestCostModel`，sqrt 冲击 opt-in（默认关·Y 调用方给） |
| 三档成本预设（strategy_goal.py·GOAL §M9.2） | EquityCostModel/CryptoSpotCostModel/CryptoPerpCostModel | 本卡**不改其 pydantic schema**（避 YAML/OpenAPI 面变动）；桥读其 impact_model + 透传 Y |

## 对抗测试设计（种已知 bug，门必抓）[必填]
1. fill 报告含 impact 分列；commission 合计向后兼容（旧消费者不破）。**②·test_sqrt_impact_cost.py 26 passed**。
2. 三档预设 opt-in size-aware：大资金回测冲击成本显著 > 小资金（成本归因可见）。**①·test_cost_presets_bridge.py**。
3. 接生产前依赖 0f696e56 无泄露自估已落（否则生产默认带前视）。**✅ 前置已满足（done 卡 d9bf88b1）**。

## 验收一句话 [必填]
size-aware 平方根冲击接进三档成本预设（**opt-in·默认关·不替拍生产默认**）+ 成交报告成本拆字段可归因，不破基线与向后兼容。

---

## 完成记录（2026-06-26 · deep-opus 隔离 worktree 线 · wave6/cost-fields）

### ② 成本归因拆字段 — 复核确认 done（前置 land·未动其代码）
- done 卡 **6e264c59** / commit **c7a56be**（已在 origin/main）：`_cost_breakdown` 逐成分 + total、impact **单列**
  绝不并入 commission；fill 报告 additive 加 `cost_breakdown`，顶层 `commission`=total 仅向后兼容；`cost_summary`
  run 级聚合（total 走独立 Σfill.total 路 → 加总恒等式有牙）。
- 本轮**只复跑验证、未改代码**：`test_sqrt_impact_cost.py` **26 passed**；`backtest_venue.py`/`impact.py`
  **byte-identical to HEAD**（git diff 空）。

### ① 三档预设接 sqrt-impact — 新建 opt-in 桥（默认不翻·不替拍）
- **新建** `app/backend/app/execution/cost_presets.py`（**扩展不替换**：纯新增、0 改动既有文件）：
  - `to_backtest_cost_model(preset, *, impact_coef=None, impact_adv=None, impact_sigma=None)`：§M1 三档预设
    （Equity/CryptoSpot/CryptoPerp）→ 引擎 `BacktestCostModel`。
  - `backtest_cost_model_for(asset_class, *, impact_model=None, impact_coef=None, ...)`：便捷入口（取该档默认预设
    →转，**单一默认源**、不复制默认值）。
  - **opt-in 合同（诚实·不静默·不假绿灯）**：
    - 默认预设（impact_model='linear'、impact_coef=None）→ **impact_coef=0.0=冲击关**（生产默认逐位不变）。
    - impact_model='sqrt' **且**传正 Y → 启用 R18 平方根冲击；δ=0.5 文献默认（`impact.IMPACT_DELTA`）随转换流入。
    - impact_model='sqrt' 却**没给 Y** → **raise**（否则静默 0 冲击=假绿灯）。
    - **给了 Y 却预设非 sqrt** → **raise**（诚实拒绝口径不一致，不偷塞冲击进没声明 sqrt 的预设）。
    - 无效 Y（0/负/非有限）→ raise。
  - **费率口径（保守·诚实）**：加密用 **taker** 作 commission（默认市价撮合=taker、更保守），spot 按 bnb_discount 折让；
    perp 的 **funding/borrow 是持仓成本、不属 per-fill**（且 `funding_bps_per_8h` 当前 `_cost_breakdown` 未消费）→
    **不伪造 funding 数、置 0**。A股 commission/stamp(卖)/transfer/slippage 直传。
  - **无新公式**：复用已建 `square_root_impact_fraction`（R18）；**不碰** look-ahead 自估路（d9bf88b1），只透传无泄露 ADV/σ。
- **新建** `app/backend/tests/test_cost_presets_bridge.py`：**19 tests**（默认关向后兼容逐位相等 / opt-in 真 size-aware /
  数值=单一公式源 / impact 单列不混 commission / 四道 raise 门 / 费率映射 / 便捷入口 dispatch）。

### 验证（scoped·带 timeout·凭真汇总行）
- `test_cost_presets_bridge.py + test_sqrt_impact_cost.py` → **45 passed**（19 新 + 26 ②）。
- 邻接面 `test_execution.py + test_strategy_goal.py + test_methodology_invariants.py` → **78 passed**（import/领地无破）。
- `--collect-only` 全量 → **2209 collected · 0 collection error**（新增 +19 additive；仅一条与本卡无关的既有
  testnet_mark warning）。

### 对抗测试 MUT（种坏门必抓 · 手工 revert·绝不 git checkout）
- **MUT-1 静默吞 opt-in**（把桥的 `impact_coef=resolved_coef` 改成恒 `0.0` = 死字段没接通）→ **5 gates RED**
  （opt-in 启用/size-aware/数值/impact 单列/便捷入口）；raise 门与默认关 14 gates 仍绿 → 证 opt-in 接通有牙。
- **MUT-2 impact 混入 commission**（`_cost_breakdown` 把 impact 折进 commission 成分）→ **2 gates RED**（①桥路 +
  ②原测，commission 虚高 33.5=impact 量被抓）→ 证归因诚实门有牙。
- 两 MUT 均**手工 Edit 复原**；复原后 `backtest_venue.py`/`impact.py` byte-identical to HEAD、scoped 45 passed。

### 红线合规（逐条）
- **扩展不替换**：2 新文件、**0 改既有文件**（含 backtest_venue.py 未动）。
- **向后兼容**：默认预设经桥 → 与直接构造平成本模型**逐位相等**（test 钉死）；生产默认不翻。
- **impact 单列不淹没 commission**：①桥路 + ②原测双门钉死、MUT-2 有牙。
- **look-ahead 自估路不碰**：桥只透传 ADV/σ，不改 d9bf88b1 自估逻辑。
- **生产成本默认=用户方法学不替拍**：见拍板项。
- **🟡≠✅**：以上均**实跑真汇总行**为准（非 exit code）。

### 拍板项（工程取舍·摆代价不替拍 → 留给 leader/用户）
**三档预设是否把默认翻成 size-aware（impact_model 默认改 'sqrt' + 配一个标定 Y）= 用户方法学决策（GOAL §10）。**
本卡**坚持不翻默认**、只建 opt-in 路。代价两面摆清：
- **保持默认关（现状）**：大资金回测**系统性过优**（无冲击成本）；优点=零前视/零标定风险、向后兼容、不替用户假设。
- **翻成默认开**：须先有**可信 Y 标定**（无万能默认、须按标的/市场/容量校准）+ 无泄露 ADV/σ 数据管线；否则把一个
  没校准的冲击假设当生产默认 = 另一种不诚实。**翻默认须用户显式拍**。

### 诚实残余（不过 claim）
- **生产 run 管线尚未消费三档预设 → BacktestVenue**：grep `BacktestVenue(` 仅 `backtest_venue.py` 自身构造；
  主 run 管线（main.py/ide/paper）当前**不**把 StrategyGoal 成本预设接到回测引擎（cost_drift 用硬编码 bps）。
  本桥是**库级 opt-in seam**，producer wiring（接进真实 run 管线）是**另一条线 / follow-on**（碰 main.py/qro/portfolio
  超本卡领地）。**不暗示已被生产 run 详情消费**。
- impact_model ∈ {fixed/linear/orderbook} 在本仓库无对应冲击实现，桥对它们产平成本（不静默假装有线性/常数冲击）。
- 与 `cost_summary` 同款残余：run 详情 manifest 的 `cost_breakdown` 是另一套 schema（fee/funding/net），本成分归因
  尚未写进该 manifest（producer wiring 待接）。
