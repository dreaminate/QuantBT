---
uuid: 312893389d0f4356bf8a6503cb8bfebb
title: 冷启动 gate/UI 接 MinTRL：DSR=N/A + PSR + "需 N 期"渐进披露（R25/R27 呈现层）
status: todo
owner: wait
assigned_by:
review_status: 0
priority: P2
area: eval-methodology
source: goal-gap
source_ref: 卡 6acbb499（MinTRL）消费侧残余；多透镜评审 CEO「残余写了未 mint 卡」+ R27/R25 呈现层
depends_on: [6acbb499f5b94fe3b77c4de79bb43982]
---

# 冷启动 gate/UI 接 MinTRL

> **状态（2026-06-25）**：**gate 投影侧 ✅ done**（卡 b1e4efdf·project_overfit 加 cold_start 证据充分性字段）；**UI 裁决卡呈现 ✅ done**（done 卡 c5960022·RunVerdictCard + LiveRunVerdictCard 真闭环「业绩期」格，不假绿灯：证据不足非绿/充分中性/缺数据不渲染，MUT-cs 验证有牙）。**剩**：DSR=N/A + PSR 渐进披露的更细 UI（如需）留池。

## Scope [必填]
MinTRL 数学（`dsr.py`）已建并验证，但冷启动判定未接 gate/UI。本卡合拢 R27 呈现层：
① gate/裁决层在 N 小时把 DSR 标 **N/A**（N=1 DSR 退化 PSR=范畴误用）、给 PSR 显著性 + MinTRL；
② RunVerdictCard 渐进披露（R25）：n_observed / ⌈MinTRL⌉ / 还需期数 / never_significant / insufficient 三态，
显式"证据不足、按当前估计还需 N 期"而非只"样本太短"；③ 隐性 champion + 标"先验断言未经数据检验"（R27）。

## 上下文 / 动机 [按需]
卡 6acbb499 立住 MinTRL 数学/命门，但 CEO 评审指出价值闭环停在数学层（无生产消费者）。R27/R25：冷启动是呈现层（不动治理），把诚实"证据不足 + 需 N 期"送到用户首屏。RunDetailPage 冻结，新页/卡承载。

## 接线点（file:line，实现复核）[必填]
| 文件 | 位置 | 接什么 |
|---|---|---|
| app/eval/dsr.py | 已建 | 复用 minimum_track_record_length |
| 裁决/gate 层 | N 小时 | DSR=N/A + PSR + MinTRL；冷启动判 sufficient |
| 前端裁决卡（RunDetail 冻结不动，新卡） | 渐进披露 | n/⌈MinTRL⌉/还需期数/三态，弱点一等呈现（R25） |

## 对抗测试设计（种已知 bug，门必抓）[必填]
1. N=1/短样本 → UI 显"证据不足、需 N 期" + DSR=N/A（绝不渲染成达标绿灯）。
2. never_significant（SR≤SR*）→ 显"不超基准、任何样本不显著"（非"再等等"）。
3. 治理不动（R27）：呈现分层不改一套最严闸门。

## 验收一句话 [必填]
冷启动用户在 Run 首屏看到"证据不足、按当前估计还需 N 期"（DSR=N/A + PSR + MinTRL 三态渐进披露），治理层不动、不假绿灯。
