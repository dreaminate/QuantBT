---
uuid: fc79b9110c3647e4bb83c6a39e7a3a72
title: 真数据可成交性 + 复权轴——接真 Tushare 前必修的预装停工地雷（复权/停牌/涨跌停）
status: todo
owner: wait
assigned_by:
review_status: 0
priority: P1
area: data-layer
source: audit-finding
source_ref: 第二轮 correctness 审计（workflow wnbmpeqiv）#1（复权·lev 7）+ #2（停牌·lev 7）+ 涨跌停（R14 同条）
depends_on: []
---

# 真数据可成交性 + 复权轴（接真 Tushare 前必修）

> **⚠ RULES.project 红线级·潜伏地雷**：当前回测/IC 走 `panel_source.load_sample` 合成已复权样本、**未消费** Tushare runtime bars
> → 今日潜伏（非活跃假绿灯）；**接真 Tushare 数据那一刻即引爆**。用户持 Tushare token（memory），真喂路打通前**必修**。

## Scope [必填]
三条「真数据可成交性/价口径」缺口（合成样本下潜伏、真数据即活跃，建议合并为「真数据可成交性轴」一并接）：
① **复权未乘入（停工红线）**：`tushare_provider._merge_runtime_adjustment_factor`（:2137）只 `price.join(adj, how="left")` 把
   adj_factor 作悬空列贴上、**从不** `close*adj/adj.last()` 归一；且 `_RUNTIME_PRICE_SOURCE_CANDIDATES["stocks_cn"]`（:88）把原始未复权
   `daily` 排在已复权 `pro_bar` 之前 → 落盘未复权连续价。除权除息日价格跳变被当真实收益 → IC/回测/成交全失真。
   **RULES.project『未复权价喂回测成交层…出现即停工』**。无任何测试验证「价被复权」（F2「未复权口径必抓」实测的是 lookahead 负 shift 门、与复权无关=误导性覆盖假象）。
② **停牌无消费者**：`suspend_d`（:515）拉了存了但**零读取**——universe/panel/backtest 无人用它把停牌日剔出/标 null →
   停牌期 close 当连续真价、停复牌一字板跳变计入收益与 IC。
③ **涨跌停（stk_limit）**：R14 同条、同样孤儿——涨跌停日不可成交却可能被当可成交真价。

## 数学/不变量先行 [必填]
- **后复权连续价**：P_adj(t)=P_raw(t)·f(t)/f(T)，f=cum_adj_factor、T=最新交易日；守 **r_adj(t) 不含纯股本结构跳变**
  （分红送股不产生收益）→ IC/回测看到的收益=纯价格 alpha。volume 反向除。adj 缺失 → raise 不假绿。
- **可成交性**：可交易集合 T(t)={s: not suspended(s,t) ∧ not limit_locked(s,t)}；收益只在连续可交易段定义
  r(s,t)=P(s,t)/P(s,t-1)−1 仅当 s∈T(t)∩T(t-1)，否则 null（停牌/涨跌停跳变绝不进 IC/回测 P&L）。

## 接线点（file:line，实现复核）[必填]
| 文件 | 位置 | 接什么 |
|---|---|---|
| tushare_provider.py:2137 | _merge_runtime_adjustment_factor | join 后对 stocks_cn 用 adj 把 OHLC 归一最新基准、volume 反除；adj 缺失 raise |
| tushare_provider.py:88 | _RUNTIME_PRICE_SOURCE_CANDIDATES | pro_bar 提首位 / 用 daily 时强制 adj_frame 非空 |
| universe/resolver.py / panel_source 真数据落点 | 接 suspend_d + stk_limit | 停牌/涨跌停行 tradable=False / 价 null → forward_return 跨窗 null |

## 对抗测试设计（种已知 bug，门必抓）[必填]
1. **复权连续**：含除权跳变样本经 _merge_runtime_adjustment_factor 后 close 相邻 |ret|<阈值（连续）；**sentinel：不复权变体必失败**（坐实 F2 假覆盖）。
2. **停牌断收益**：含停牌窗口 panel 经处理 → 停牌日不可选入池、跨停牌 forward_return 为 null（非把跳变当收益）。
3. **涨跌停不可成交**：涨跌停日 tradable=False。
4. adj 缺失 → raise（不假绿）。

## 验收一句话 [必填]
真数据路径下价被正确后复权（除权跳变不进收益·sentinel 不复权必失败）+ 停牌/涨跌停日不可成交且跨窗收益 null，
拆掉「未复权价喂成交层」停工红线地雷；不破合成样本基线。
