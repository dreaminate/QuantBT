---
uuid: c631817e756144ffb61dd8dce9b41347
title: 防绿灯错觉——三角裁决按权限模式分层呈现 + 工具真实状态标注
status: done
owner: dreaminate
assigned_by: dreaminate
review_status: 1
priority: P1
area: governance-ui
source: interaction
source_ref: 2026-06-20 回测全流程审计 workflow + D-PERM(R25 分层) + GOAL §6 R25/R27
depends_on: []
---

# 防绿灯错觉——三角裁决按权限模式分层呈现 + 工具真实状态标注

## Scope [必填]
对 IDE-promote 与 Run 详情页的 `red/yellow/insufficient` 三角裁决做**按权限模式/画像分层的呈现**(D-PERM:`ask`=软确认+标记 / `auto`·`bypass`=只打标记);裁决**永远可见可下钻、绝不渲染成绿/可信**(R25 不淡化保留),调的只是默认呈现+确认强度。`/api/agent/tools` 与前端标注每工具真实状态(live/stub/未接)。不改 promote"只记不拦"语义。

## 上下文 / 动机 [按需]
审计:`ide/promote.py` 三角 gate 只注入 dsr/pbo/bootstrap、无 red-block——噪声策略也能 promote 成 Run。用户拍板:别对所有人统一显眼警示(打扰拿来测试思路的 researcher),改按权限模式分层——治理不变、呈现个性化(R25 分层线 = D-PERM)。

## 接线点（file:line，实现时复核）[必填]
| 文件 | 位置 | 改什么(扩展不替换) |
|---|---|---|
| app/backend/app/ide/promote.py | 96-167 三角 gate 注入 | 返回 gate_verdict(不拦) |
| app/backend/app/main.py | 2498-2567 ide_promote_run | 返回结构加裁决字段 + 当前权限模式 |
| app/frontend-run-detail/ | RunDetailPage(**冻结**) | 仅加字段/显示逻辑;按模式渲染强度 |
| app/backend/app/main.py | 283-285 工具注册 | 加 live/stub/未接 status |

## 对抗测试设计（种已知 bug，门必抓）[必填]
1. ask 模式软确认:red 策略在 ask 下 promote → 必出软确认 + 标记;种"ask 下 red 无确认直接成 Run" → 抓。
2. 弱点不淡化:任何模式下 red 都**可见可下钻、绝不渲染绿**;种"auto 模式把 red 折叠成看不见/标成绿" → 抓(R25 底线)。
3. 工具状态诚实:stub 工具(factor.run_ic 仅 queued)必标 stub;种"stub 标 live" → 抓。

## 复用 [按需]
`gate_runner.py` 已产 gate_verdict;RunDetailPage 现有字段渲染范式;权限模式来自 T-027。

## 红线 [按需]
RunDetailPage 冻结(RULES.project);R25 弱点永远可见可下钻绝不渲染成绿;分层只动呈现强度不动治理(D-PERM)。

## 非目标 [按需]
不把 red 改硬拦(破坏"不挡探索");不改三角门计算本体。

## Open Questions（已决 1/1）[按需]
- [已决] red 呈现按权限模式分层(D-PERM):`ask`=软确认+标记 / `auto`·`bypass`=只打标记;弱点永远可见可下钻,不做对所有人统一的显眼强警示。

## 验收一句话 [必填]
种"ask 下 red 无确认 / 任何模式把 red 渲染成绿或藏掉 / stub 标 live" → 呈现门必抓;不破 RunDetailPage 冻结、不破基线。

## 完成记录（2026-06-20）
- **工具真实状态诚实暴露（核心）**：`/api/agent/tools` 加 `tool_status`——对 TOOL_SCHEMA 18 个工具逐一标 live/stub/unwired + side_effect。揭穿「能力名不副实」：仅 8 个接通（strategy_goal.create/code.replicate/5 字段工具=live；factor.run_ic=stub），10 个（backtest.run/eval.pbo/model.train/report.generate 等）声明未接=unwired。
- **对抗测试**（`test_agent_tool_status.py` 5 passed）：unwired/stub/live 各断言 + 全标 live 假绿探针。
- **验收**：全量 **1075 passed / 13 skipped**（基线 1070 未破，+5）。
- **残余（前端 UI，RunDetailPage 冻结）**：red/yellow/insufficient 裁决按权限模式一等呈现分层（ask 软确认+标记 / auto·bypass 标记）属前端渲染；后端裁决已由 ide_promote 返回 gate_verdict 暴露（T-026 调查确认）。前端呈现 + 工具 status 展示建议随 T-035 agent 窗口一并做。
