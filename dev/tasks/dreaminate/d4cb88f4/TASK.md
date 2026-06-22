---
uuid: d4cb88f43c824183b694eabea81b9782
title: DS-3 裁决接真——run_id 贯穿真裁决卡 + Bootstrap 第三腿前端补全
status: todo
owner: dreaminate
assigned_by: dreaminate
review_status: 1
priority: P1
area: frontend
source: developer-claude
source_ref: 2026-06-22 D-DELIVERY-SLICE · audit blocker #4/#7
depends_on: [f6bb5e8ea620412fa0c3e5a48011b74b]
---

# DS-3 裁决接真

## Scope [必填]
把 DS-1 产的真 run_id 作为 liveRunId 一路贯穿 AgentWorkbenchPage→CoworkArea→RunCard，liveRunId 存在时渲染**已真接线的** `LiveRunVerdictCard`（真接 verdict/overfit/cost 四端点）而非写死 `MOCK_AGENT_RUN`（blocker #4）；mock 卡仅显式演示模式出现。**Bootstrap 第三腿前端补全**：`OverfitResp` 接口加 `bootstrap_ci` 解析，RunVerdictCard footer 加第三格展示（后端 `overfit_gate.py` 已有 bootstrap_ci，前端不消费）（blocker #7）——兑现「多证据三角」非二元。

## 接线点（file:line，实现时复核）[必填]
| 文件 | 位置 | 改什么 |
|---|---|---|
| app/frontend/.../AgentWorkbenchPage.tsx | 1103 CoworkArea 未传 liveRunId | 贯穿真 run_id |
| app/frontend/.../CoworkCards.tsx | 547-563 RunCard else→MOCK | liveRunId 存在走 LiveRunVerdictCard |
| app/frontend/.../RunVerdictCard + OverfitResp | bootstrap_ci 不解析 | 加字段 + footer 第三格 |

## 对抗测试设计（种已知 bug，门必抓）[必填]
1. 真 run_id 贯穿 → 裁决卡渲染真 verdict（PBO/DSR 来自该 run，非写死 0.18/1.34）；无真 run_id 才 mock。
2. Bootstrap CI 第三格真渲染（前端测试断言三格皆在）。

## 验收一句话 [必填]
陌生人在裁决卡看到的是自己回测的真 PBO/DSR/Bootstrap 三角；非写死 mock；不破基线。
