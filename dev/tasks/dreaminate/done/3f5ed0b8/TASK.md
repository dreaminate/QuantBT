---
uuid: 3f5ed0b803be4ffea95e92aec8f33ac5
title: agent 客户端窗口 epic(仿 Claude Code)——权限模式切换 + 工具可视化 + 审批弹窗
status: done
owner: dreaminate
assigned_by: dreaminate
review_status: 1
priority: P2
area: frontend-epic
source: interaction
source_ref: 2026-06-20 用户拍板立 epic + 3 形态项 + D-PERM + 设计图(权限三态映射 widget)
depends_on: [edc1e32623674b1f870b264119db2421]
---

# agent 客户端窗口 epic(仿 Claude Code)——权限模式切换 + 工具可视化 + 审批弹窗

## Scope [必填]
仿 Claude Code 客户端的 agent 窗口:**一套 React 组件两处挂载**(Web 路由如 `Mode2ChatPage` + Tauri 桌面窗口);对话流 + 工具调用可视化(**默认可折叠摘要;red/真钱/血统等治理弱点默认展开、全部可下钻**)+ 权限模式切换(**per-session 默认 + 单动作可临时 override**,入口窗口顶栏)+ 审批/血统警告弹窗。后端能力依赖 T-027。epic 占位,3 形态项已决(下),进实现时拆子卡。

## 上下文 / 动机 [按需]
用户 2026-06-20 拍板:仿 Claude Code 做 agent 窗口,让"人出意图、agent 出工程"在一个界面走完;权限三态(D-PERM)是核心交互轴。形态 3 项同日拍板(见 Open Questions)。

## 接线点（file:line，实现时复核）[必填]
| 文件 | 位置 | 改什么(扩展不替换) |
|---|---|---|
| app/frontend/src/pages/workshop/Mode2ChatPage.tsx | 现有 agent 对话页 | 扩展为工具可视化窗口(Web 挂载) |
| app/frontend/ | agent 窗口组件(一套复用) | 模式切换 + 工具卡(折叠/展开)+ 弹窗 |
| app/desktop/(src-tauri) | 桌面壳 | 同一组件挂成桌面窗口 |
| app/backend/app/main.py | T-027 权限三态 API | 前端对接 |

## 对抗测试设计（种已知 bug，门必抓）[必填]
1. UI 不绕治理门:种"窗口直接调真钱/晋级端点跳过治理门" → 必抓(沿用 T-029 入口×门矩阵)。
2. 默认止于模拟盘:种"窗口默认/自动建议直接上实盘" → 必抓(D-PERM,文案/默认不诱导实盘)。
3. 治理弱点不淡化:red/真钱/血统警告默认展开;种"治理弱点被默认折叠藏起" → 抓(R25)。
4. 模式呈现一致:bypass 模式真钱动作仍显示"治理门拦·需审批"。

## 复用 [按需]
`Mode2ChatPage.tsx` 现有对话;T-027 权限三态后端;T-029 入口×门矩阵作 UI 回归;Tauri 壳已建。

## 红线 [按需]
窗口任何模式都不绕治理门(D-PERM);默认止于模拟盘、不诱导直接实盘;治理弱点默认展开(R25);RunDetailPage 冻结边界。

## 非目标 [按需]
不重造后端能力(归 T-027);epic 拆子卡后逐项进实现,不一锅端。

## Open Questions（已决 3/3）[按需]
- [已决] 窗口形态:一套 React 组件两处挂载(先 Web 跑通,再挂 Tauri 桌面窗口)。
- [已决] 可视化粒度:可折叠摘要为主,治理弱点(red/真钱/血统)默认展开、全部可下钻。
- [已决] 模式切换:per-session 默认 + 单动作可临时 override,入口窗口顶栏。

## 验收一句话 [必填]
种"窗口绕治理门 / 默认诱导直接实盘 / 治理弱点被折叠藏起" → 必抓;窗口行为与权限三态+治理正交一致;拆子卡后逐项进实现。

## 完成记录（2026-06-20 · epic 拆分，leader 领）
epic 方向 + 3 形态已决，拆为 4 张可实装子卡并分配 dreaminate（leader 领）：
- **T-040 `82120b9c`** 前端窗口核心（Web：对话流 + 工具可视化 + 权限模式切换）· 依赖 T-027
- **T-041 `3d95e0f6`** 弹窗 + 教学文案（整合 T-028/T-032/T-034 前端残余）· 依赖 T-040
- **T-042 `bc21c7c1`** Tauri 桌面挂载（一套组件两处挂载）· 依赖 T-040
- **T-043 `3bb62d7d`** 无副作用工具接真引擎（agent 一句话真跑回测，T-027 残余，P1）· 依赖 T-027
epic 本卡工作（规划 + 形态拍板 + 拆子卡）完成；实装由 4 子卡承接。
