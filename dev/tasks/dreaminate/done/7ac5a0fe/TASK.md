---
uuid: 7ac5a0fe981e4677ab88d34df5733c81
title: BacktestVenue.cost_summary —— per-fill 成本归因收口到 run 级
status: done
owner: dreaminate
assigned_by: dreaminate
review_status: 1
priority: P2
area: execution-cost
source: goal-gap
source_ref: done 卡 6e264c59（per-fill cost_breakdown）的 run 级收口；run_detail_core:150 已读 manifest cost_breakdown 但无 producer
depends_on: [6e264c59f82043fe9934eb913324a6f4]
---

# BacktestVenue.cost_summary（per-fill → run 级成本归因）

## Scope [必填]
slice 成本逐成分归因（done 卡 6e264c59）只到 **per-fill**；`run_detail_core:150` 已读 run 级
`manifest.cost_breakdown` 但**无 producer**（恒空 {}）。本卡建 `BacktestVenue.cost_summary()`：聚合本 venue
所有成交的 per-fill `cost_breakdown` → run 级总额（commission/slippage/stamp_duty/transfer/impact/total + n_fills），
impact 单列、不淹没在 commission。供 paper/run 详情/TCA 消费。

## 治理（命门·不假绿灯）[必填]
- **run 级加总恒等式**：`total` 走「Σ 各 fill.total」**独立路径**（非 Σ 各成分），使 total==Σ成分有真牙（聚合漏成分/错累加即崩，MUT-cs2 验证）。
- **不假绿灯**：非有限成分跳过；无成交 → 全 0、n_fills=0（不编造）；只聚合 kind=='fill' 且有 cost_breakdown 的记录。

## 接线点（file:line，实现复核）[必填]
| 文件 | 位置 | 改什么(扩展不替换) |
|---|---|---|
| app/execution/backtest_venue.py | +`cost_summary()` 聚合 audit fills | additive |

## 对抗测试设计（种已知 bug，门必抓）[必填]
1. run 级聚合 == Σ 各 fill cost_breakdown（逐成分 + total + n_fills）；run 加总恒等式 total==Σ成分（MUT-cs2 聚合漏 impact→崩，有牙）。
2. impact 单列 run 级可见（>0、不淹没 commission）。
3. 无成交 → 全 0、n_fills=0。

## 验收一句话 [必填]
BacktestVenue.cost_summary 把 per-fill 成本归因收口到 run 级（impact 单列·run 加总恒等式有牙·无成交全 0），
MUT-cs2 验证聚合漏成分被抓；全量后端 1596 passed/0 failed。

## 完成记录（2026-06-25 · autonomous-loop / D-COST-RUN-SUMMARY）
- **per-fill→run 级收口**：`cost_summary()` 聚合 audit fills 的 cost_breakdown → run 级各成分 + total + n_fills；total 走独立 Σfill.total 路径 → run 加总恒等式有真牙（MUT-cs2「聚合漏 impact」→ 测试崩）。
- **验证**：`test_sqrt_impact_cost.py` 25 passed（+2 cost_summary）；**全量后端 1596 passed / 13 skipped / 0 failed / 128s**（基线 1594，净 +2）。
- **follow-on（诚实残余）**：`run_detail_core:150` 消费者已在，但 backtest→manifest 写入处把 venue.cost_summary() 落进 manifest.cost_breakdown 的 producer wiring 待接（IDE sandbox 回测是否产 per-fill 待确认）——非本卡范围、建后续 mint；本卡提供可用聚合 API。
- **本轮 loop「commit 和 push 自动进行」→ 本地 commit + push 分支**（land main 仍仅用户）。
