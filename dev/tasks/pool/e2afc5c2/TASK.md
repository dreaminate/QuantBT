---
uuid: e2afc5c239fa46c3a56a0bdfc730a48e
title: 三档成本预设接 sqrt-impact 默认 + 成交报告 impact 成本归因拆字段
status: todo
owner: wait
assigned_by:
review_status: 0
priority: P2
area: execution-cost
source: goal-gap
source_ref: 卡 7179ba36（sqrt-impact）消费侧残余；评审 CEO「对的东西没接到用户」+ eng 成本归因
depends_on: [7179ba36278e4091a8e29b4d58336525]
---

# 三档成本预设接 sqrt-impact 默认 + impact 成本归因拆字段

## Scope [必填]
卡 7179ba36 的 sqrt-impact 默认关、需用户显式启用。本卡：① 把 size-aware 平方根冲击接进**三档成本预设**
（GOAL §M9.2），让生产回测默认 size-aware（大资金不再系统性过优）；② 成交报告里成本拆**结构化字段**
（commission/slippage/stamp/transfer/impact 分列或 cost_breakdown 子字典），保留 commission 合计向后兼容，
让 impact 可单独归因（现并入 commission 字段，下游按字段名归因会误读）。

## 上下文 / 动机 [按需]
评审 CEO：sqrt-impact 数学/命门已立但默认关、未接生产预设 → 用户用不到。eng：fill 报告 impact 并入 commission 字段、下游误读。依赖 P2 卡 0f696e56（无泄露自估）先落，生产默认启用才安全。

## 接线点（file:line，实现复核）[必填]
| 文件 | 位置 | 接什么 |
|---|---|---|
| app/execution/backtest_venue.py | _cost_for_trade / fill 报告 | 成本拆结构化字段（含 impact 列） |
| 三档成本预设（GOAL §M9.2 调用方） | 预设 | size-aware 冲击接默认（依赖无泄露自估 0f696e56） |

## 对抗测试设计（种已知 bug，门必抓）[必填]
1. fill 报告含 impact 分列；commission 合计向后兼容（旧消费者不破）。
2. 三档预设默认 size-aware：大资金回测冲击成本显著 > 小资金（成本归因可见）。
3. 接生产前依赖 0f696e56 无泄露自估已落（否则生产默认带前视）。

## 验收一句话 [必填]
size-aware 平方根冲击接进三档成本预设生产默认（依赖无泄露自估）+ 成交报告成本拆字段可归因，不破基线与向后兼容。
