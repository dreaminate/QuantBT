---
uuid: ff19c992d58c4713ba1bd01ba89d56f7
title: 拆「未复权价喂回测/成交层」停工红线地雷——Tushare runtime 复权真乘进 OHLC（源感知防双重复权）
status: done
owner: dreaminate
assigned_by: dreaminate
review_status: 1
priority: P1
area: data-layer
source: audit-finding
source_ref: 第二轮 correctness 审计（workflow wnbmpeqiv）#1（复权·lev 7·RULES 停工红线）；池卡 fc79b911 的 ① 复权部分
depends_on: []
---

# 拆「未复权价喂成交层」停工红线地雷——runtime 复权真乘进 OHLC

## Scope [必填]
`tushare_provider._merge_runtime_adjustment_factor`（:2137）此前只 `price.join(adj, how="left")` 把 adj_factor 作**悬空列**
贴上、**从不乘进 OHLC**；`_RUNTIME_PRICE_SOURCE_CANDIDATES["stocks_cn"]=("daily","pro_bar")` 首取原始未复权 `daily`
→ 落盘未复权连续价。除权除息日价格跳变被当真实收益（分红送股日假暴跌）→ IC/回测/成交全失真。
**RULES.project『未复权价喂回测成交层…出现即停工』**。本卡把复权真乘进 OHLC，拆此地雷。

## 潜伏性核实（为何修而非停工报告）[必填]
活跃 IC/回测/layered 走 `panel_source.load_market_panel → load_sample`（**合成已复权样本**·docstring 明示「真实数据接入时
本函数是唯一复权落点」），**不消费** provider runtime bars → 此路径**休眠**（今日无活跃假收益），属**接真 Tushare 即引爆的
预装地雷**非现行致命错误。故修复（不触发停工报告），并补机器守点防复发。

## 数学先行（qfq·recent-preserving + 防双重复权）[必填]
- **后复权连续价 qfq**：每 symbol 按 timestamp 升序，qfq(t)=adj_factor(t)/adj_factor(T)，T=最新交易日；
  P_adj=P_raw·qfq（open/high/low/close）；volume 反向 V_adj=V_raw/qfq（守 P·V 值不变）。
- **不变量**：除权日 r_adj(t)=P_adj(t)/P_adj(t-1)−1 **不含纯股本结构跳变**（分红送股不产生收益）→ IC/回测收益=纯价格 alpha。
- **防双重复权（新增 correctness 守点）**：**源感知**——仅原始未复权源（`_RAW_PRICE_SOURCES`={daily,pro_bar,hk_daily,us_daily}）
  才乘 adj；已复权源（us_daily_adj·名含 _adj）`apply_adjustment=False` **绝不再乘**（否则双重复权=新 bug）。
- **缺 adj 红线**：原始未复权源 + adj_frame 空 → **raise**（绝不写未复权价·不假绿）；adj 覆盖不全 → symbol 内 forward/backward fill（累积因子事件间稳定）。

## 接线点（file:line，实现复核）[必填]
| 文件 | 位置 | 改什么(扩展不替换) |
|---|---|---|
| tushare_provider.py:93 | +`_RAW_PRICE_SOURCES` frozenset | 新增 |
| tushare_provider.py:_merge_runtime_adjustment_factor | join→真乘 qfq + apply_adjustment 源感知 + 缺 adj raise + 覆盖不全 fill | 重写(行为修正) |
| tushare_provider.py:_materialize_tushare_runtime_assets | 调用方按 price_source∈_RAW_PRICE_SOURCES 传 apply_adjustment | additive |
| app/backend/tests/test_tushare_adjustment.py | 新建 6 测试 | 新增 |

## 对抗测试设计（种已知 bug，门必抓）+ 变异 [必填]
1. **除权跳变消除**：raw[10,11,5.5,5.5]+adj[1,1,2,2]→P_adj[5,5.5,5.5,5.5]；day3 拆股(原始-50%)复权后 ret≈0、day2 真实+10% 保留；sentinel 原始 day3 ret=-0.5 → MUT-1（qfq=1 不复权）→ 红 ✓
2. **volume 反除**：V_adj=V/qfq=[200,200,100,100]（守值）。
3. **缺 adj raise**：原始源+adj 空 → raise → MUT-2（缺 adj 不 raise 写未复权）→ 红 ✓
4. **防双重复权**：apply_adjustment=False（已复权源）→ 原样返回不乘 adj。
5. adj 覆盖不全 → 前向填充无 null 价。
6. 源感知集含原始源、不含 us_daily_adj。

## 验收一句话 [必填]
Tushare runtime 复权真乘进 OHLC（qfq·除权跳变归一·真实收益保留）+ 源感知防双重复权 + 缺 adj raise，拆掉「未复权价喂成交层」
停工红线地雷；MUT-1/2 双变异抓；全量后端 1649 passed / 0 failed。

## 完成记录（2026-06-25 · autonomous-loop / D-ADJ-FACTOR）
- **审计驱动（第二轮 #1·lev 7·RULES 停工红线）**：复权 factor join 进价却从不乘进 OHLC + stocks_cn 首取未复权 daily。读 provider 原文 + panel_source 消费链复核：活跃路径走合成样本、provider runtime 休眠 → 潜伏地雷非现行致命，可修。
- **关键 correctness 警示（自查纠偏）**：不能「有 adj 就乘」——us_daily_adj 等已复权源再乘=双重复权新 bug；故实现**源感知**（_RAW_PRICE_SOURCES 判据）。
- **实现（行为修正 + additive）**：_merge_runtime_adjustment_factor join→真乘 qfq（P_adj=P_raw·adj/adj_last·volume 反除）+ apply_adjustment 源感知 + 缺 adj raise + 覆盖不全 symbol 内 fill；caller 按 price_source∈_RAW_PRICE_SOURCES 传 apply_adjustment。
- **对抗 + 变异**：6 测试。MUT-1（qfq=1 不复权）→ 除权跳变/volume 测试红；MUT-2（缺 adj 不 raise）→ 红线门测试红；定点反向 edit 后还原（**绝不 git checkout 带未提交改动**）。
- **验证**：复权 6 passed；**全量后端 1649 passed / 13 skipped / 0 failed / 170s**（基线 1643，净 +6）；休眠路径改动不破活跃测试。
- **fc79b911 残（②③）**：停牌 suspend_d 无消费者 + 涨跌停 stk_limit 孤儿（真数据可成交性轴）——池卡留（接 universe/panel）。
- **本轮 loop「commit 和 push 自动进行」→ 本地 commit + push 分支**（land main 仍仅用户）。
