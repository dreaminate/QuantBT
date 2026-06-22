---
uuid: d5ea778c285a46e0872dba3a87ab1182
title: 共享 Agent 对话 + Inspector + Dock 组件
status: done
owner: dreaminate
assigned_by: dreaminate
review_status: 1
priority: P0
area: frontend-foundation
source: interaction
source_ref: 2026-06-21 epic cfb0fea9 拆分（策略台栏/Agent台/Model构建助手/因子构建台 共用对话）
depends_on: [d11d1426c2a14372a12e655fcd459871]
---

# 共享 Agent 对话 + Inspector + Dock 组件

## Scope [必填]
建三组共享组件，供多台复用：① `desk/agent/`（AgentChat 对话容器 / ChatBubble 角色气泡 user·think·say·patch·todos·tool·proposal-Ghost / ChatComposer 底部 `>` 输入 + 模型·mode·branch 状态行）；② `desk/inspector/`（Inspector 340 容器 / InspectorTabs 段控 / ParamRow label+tip+input）；③ `desk/dock/`（Dock 228 容器 / DockTabs）。**不做**：不接真后端 SSE/工具（各台卡接）、不内置具体台的产物卡/参数 schema（受控传入）。

## 上下文 / 动机 [按需]
Agent 对话栏出现在策略台左栏、QuantBT Agent 主台、Model 构建助手、因子台构建台；Inspector 出现在策略台 + 因子台/Model台/模拟台右侧详情；Dock 出现在策略台底部。抽成受控组件避免多台重复实现。是 S1/F1/M1/A1 的前置。

## 接线点（file:line，实现时复核）[必填]
| 文件 | 位置 | 改什么(扩展不替换) |
|---|---|---|
| app/frontend/src/components/desk/agent/ | 新建 | AgentChat/ChatBubble/ChatComposer |
| app/frontend/src/components/desk/inspector/ | 新建 | Inspector/InspectorTabs/ParamRow |
| app/frontend/src/components/desk/dock/ | 新建 | Dock/DockTabs |

## 对抗测试设计（种已知 bug，门必抓）[必填]
1. 角色气泡完整：种「治理弱点类 block（red/血统/真钱）默认折叠」→ 抓（R25 弱点一等呈现，治理 block 默认展开）。
2. 受控纯净：种「Inspector/Dock 内置某台专属字段硬编码」→ 抓（必须 props 传入）。
3. 输入安全：种「ChatComposer 把 permission_mode/side_effect 当可前端伪造的展示值」→ 抓（须从后端真值取，防 T-040 对抗#1）。

## 复用 [按需]
G1 的 SegmentedControl/Pill/token；现有 `Mode2ChatPage.tsx` 的 SSE/authFetch 逻辑（A1 接线时复用，本卡只做受控 UI 壳）。

## 红线 [按需]
扩展不替换；治理 block 默认展开不淡化（R25）；permission/side_effect 不前端伪造（D-PERM）。

## 非目标 [按需]
不实装真 SSE 流/工具 handler（属各台 + A4）；不内置产物工作区 8 卡（属 A1）。

## Open Questions（已决 1/1）[按需]
- [已决] 组件受控化：对话 blocks/inspector params/dock tabs 全 props 传入，治理弱点 block 默认展开为组件内置约束。

## 验收一句话 [必填]
对话气泡 7 型 + Inspector + Dock 受控渲染像素对齐、治理 block 默认展开；种弱点折叠/字段硬编码/伪造 side_effect 门必抓。
