---
uuid: cb463286839c40e2b396f3f68bbe4375
title: DS-5 §3 假绿灯修——乐观假成功改诚实失败（correctness）
status: todo
owner: dreaminate
assigned_by: dreaminate
review_status: 1
priority: P1
area: frontend
source: developer-claude
source_ref: 2026-06-22 D-DELIVERY-SLICE · audit blocker #8 + 跨站假绿灯
depends_on: []
---

# DS-5 §3 假绿灯修

## Scope [必填]
修跨站「乐观假成功」假绿灯（§3 不假绿灯，correctness 非松紧档）：① paper 晋级 catch 分支不再乐观 `setPromoted(true)`，失败显式报错（缺背书/未审批），晋级表单 endorsement_ref/reason 必填（后端 INV-5 必拒空，前端不能伪成功）；② handoff 失败不再显示「（mock 回执）已提交」；③ 空壳净值不盖「LIVE 已接真」绿角标（与 DS-4 真实 bars_fed>0 绑定）。陌生人最易被误导，优先修。

## 接线点（file:line，实现时复核）[必填]
| 文件 | 位置 | 改什么 |
|---|---|---|
| app/frontend/.../PaperDeskPage.tsx | 150,159-160 catch setPromoted(true) | 失败显错、不伪成功 |
| app/frontend/.../AgentWorkbenchPage.tsx | 368-379 handoff 失败显已提交 | 失败显错 |

## 对抗测试设计（种已知 bug，门必抓）[必填]
1. 晋级缺背书/网络失败 → 前端显式失败（非 promoted=true）；前端测试断言失败态不渲染绿/成功。
2. 空 bars → 不显「LIVE 已接真」绿标。

## 验收一句话 [必填]
失败/mock 绝不渲染成成功绿（§3）；陌生人看到诚实状态；不破基线。
