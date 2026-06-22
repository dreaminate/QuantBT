---
uuid: 82120b9c60814566beea2d6b210ef31e
title: agent 窗口前端核心（Web）——对话流 + 工具可视化 + 权限模式切换
status: done
owner: dreaminate
assigned_by: dreaminate
review_status: 1
priority: P2
area: frontend
source: interaction
source_ref: 2026-06-20 T-035 epic 拆分（leader 领）+ D-PERM + 设计图
depends_on: [edc1e32623674b1f870b264119db2421]
---

# agent 窗口前端核心（Web）——对话流 + 工具可视化 + 权限模式切换

## Scope [必填]
仿 Claude Code 的 agent 窗口前端核心组件（Web 挂载 `Mode2ChatPage` 扩展）：对话流 + 工具调用可视化（默认可折叠摘要；red/真钱/血统治理弱点默认展开、全部可下钻）+ 顶栏权限模式切换（ask/auto/bypass per-session + 单动作临时 override）。后端权限三态（T-027）+ 工具状态（T-028）已就绪。

## 接线点（file:line，实现时复核）[必填]
| 文件 | 位置 | 改什么(扩展不替换) |
|---|---|---|
| app/frontend/src/pages/workshop/Mode2ChatPage.tsx | 对话页 | 扩展为工具可视化窗口 + 模式切换 |
| 后端 | /api/agent/chat(permission_mode) + /api/agent/tools(tool_status) | 对接 T-027/T-028 |

## 对抗测试设计（种已知 bug，门必抓）[必填]
1. 窗口不绕治理门：种"窗口直调真钱/晋级端点跳门" → 必抓（沿用 T-029）。
2. 治理弱点默认展开：种"red/血统默认折叠藏起" → 抓（R25）。
3. 默认不导向实盘：种"窗口默认建议直接上实盘" → 抓（D-PERM）。

## 验收一句话 [必填]
窗口行为与权限三态+治理正交一致、治理弱点默认展开；不破基线。

## 实装说明（epic cfb0fea9 纳入）
- 对话流 + 工具可视化 + 权限三态由 AgentWorkbenchPage（pages/workshop/agent-workbench/）实现，含 7 型 block、权限三态 SegmentedControl、gate 弹窗；A1/A2/A3 补产物工作区/里程碑/D-PERM 反例+self-approve。31 对抗测试绿（含 5 条 D-PERM 红线）。leader 2026-06-21 self-review 置 1 + 落档。
