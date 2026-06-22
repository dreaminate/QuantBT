---
uuid: 3d95e0f6674e43a1915bc28676c7aa73
title: agent 窗口弹窗 + 教学文案（整合 T-028/T-032/T-034 前端残余）
status: done
owner: dreaminate
assigned_by: dreaminate
review_status: 1
priority: P2
area: frontend
source: interaction
source_ref: 2026-06-20 T-035 拆分 + T-028/T-032/T-034 前端残余
depends_on: [82120b9c60814566beea2d6b210ef31e]
---

# agent 窗口弹窗 + 教学文案

## Scope [必填]
审批/血统警告/red 裁决弹窗 + 前端教学文案，整合各卡前端残余：red/yellow 一等呈现分层（T-028）、可证伪 409 引导句 + market_mode「仅模拟盘不接券商」+ paper「钱门用不上」（T-032）、实盘因子血统警告 + 知情确认弹窗（T-034）、self-approve 二次确认（T-030）。

## 接线点（file:line，实现时复核）[必填]
| 文件 | 位置 | 改什么(扩展不替换) |
|---|---|---|
| app/frontend/ | 弹窗组件 | 审批/血统/red 弹窗 + 知情确认 |
| app/backend/app/hypothesis/falsifiability.py | 88-101 flag | 前端翻译引导句（不改后端软挡） |
| 前端 | market_mode / paper 文案 | 转教学 |

## 对抗测试设计（种已知 bug，门必抓）[必填]
1. red/血统弹窗一等呈现：种"弱点弹窗被淡化/折叠" → 抓（R25）。
2. 文案不改行为：种"文案改动误动后端 409 阈值/血统判定" → 抓。

## 验收一句话 [必填]
弱点弹窗一等呈现 + 文案教学；后端逻辑不动；不破基线。

## 实装说明（epic cfb0fea9）
- gate 审批弹窗 + self-approve 二次确认由 AgentWorkbench/A3 实现；本卡残余三型教学弹窗（可证伪 409 引导 D-T024-FALS / 血统警告知情确认 D-PROVENANCE / red 裁决知情确认 R25）由 TeachingPopups.tsx 实现，软决定不死挡、文案走后端真值禁 R7 词。50 测试绿。leader 2026-06-22 self-review 置 1 + 落档。
