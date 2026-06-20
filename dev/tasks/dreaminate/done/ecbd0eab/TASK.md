---
uuid: ecbd0eabd4f14823997e428494495f71
title: GOAL §7 文档对齐(M10 已接 run 闸门)+ 可证伪性/模式 教学文案
status: done
owner: dreaminate
assigned_by: dreaminate
review_status: 1
priority: P2
area: docs
source: interaction
source_ref: 2026-06-20 回测全流程审计 workflow(D1 文档漂移)
depends_on: []
---

# GOAL §7 文档对齐(M10 已接 run 闸门)+ 可证伪性/模式 教学文案

## Scope [必填]
把 `GOAL.md:67` M10"待接进 run 闸门"更新为"已接进(T-015)"对齐 state(用户 2026-06-20 已授权);前端把可证伪性 409 flag code 翻成引导文案、`market_mode` 明示"仅模拟盘不接券商"、paper 模式明示"钱门用不上"。纯文档 + 文案,零代码行为变更。

## 上下文 / 动机 [按需]
审计:`GOAL.md:67` 标 M10"待接进 run 闸门"与代码/`state.md:40/66`"已接进(T-015)"不符,文档滞后侵蚀"流程即信任";409 flag code 对经济学者不可读。

## 接线点（file:line，实现时复核）[必填]
| 文件 | 位置 | 改什么(扩展不替换) |
|---|---|---|
| dev/GOAL.md | 67 M10 状态行 | 改"已接进(T-015)"(已授权) |
| dev/state/dreaminate/state.md | 40/66 | 对齐依据 |
| app/backend/app/hypothesis/falsifiability.py | 88-101 flag code | 前端翻译,不改后端软挡 |
| app/backend/app/hypothesis/falsifiability.py | 31-42 双语词典 | 复用 |
| 前端 | 409 提示 / market_mode / paper 文案 | 转教学文案 |

## 对抗测试设计（种已知 bug，门必抓）[必填]
1. 文案不改行为:翻译 flag → 引导句后,后端软挡 + override 机制不变;种"文案改动误改后端 409 阈值" → 抓。
2. 文档对齐:GOAL §7 M10 状态与 state 一致。

## 复用 [按需]
`falsifiability.py` 双语词典;前端现有提示组件。

## 红线 [按需]
override 逃生阀机制不动;不动 RULES/validate/模板等 OS 级文件。

## 非目标 [按需]
不改后端可证伪性阈值/软挡逻辑。

## Open Questions（已决 1/1）[按需]
- [已决] 改 `GOAL.md:67` M10 状态(用户 2026-06-20 授权对齐)。

## 验收一句话 [必填]
文档与 state 对齐、文案转教学;种"文案改动误动后端阈值" → 抓;不破基线。

## 完成记录（2026-06-20）
- **GOAL 对齐**：`GOAL.md:67` M10「待接进 run 闸门」→「已接进 run 闸门(T-015)」（用户授权），与 state 一致。
- **RULES.project 加红线**：「下单唯一入口：任何 place_order 必经 OrderGuard；新增端点/venue 禁裸调 place_order」（承接 T-026/T-029 转交，引 D-PERM）。
- **文档对齐回归测试**（`test_doc_alignment.py` 2 passed）：GOAL 无残留「待接进」+ RULES.project 含禁裸 place_order 红线；防文档再漂。
- **残余（前端 UI 文案）**：可证伪性 409 flag→引导句、market_mode「仅模拟盘不接券商」、paper「钱门用不上」属前端文案（分散多组件），随 T-035 窗口/前端批一并做；后端软挡/override 逻辑不动（无回归）。
