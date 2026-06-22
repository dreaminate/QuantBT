---
uuid: b9af7c82ef4c4ea6bfd1e3b6fc4d9219
title: 共享画布引擎 — GraphCanvas / NodeCard / EdgeLayer / MiniMap（pan·zoom·连线·框选）
status: done
owner: dreaminate
assigned_by: dreaminate
review_status: 1
priority: P0
area: frontend-foundation
source: interaction
source_ref: 2026-06-21 epic cfb0fea9 拆分（策略台 DAG + Model 构建台 draw.io 共用）
depends_on: [d11d1426c2a14372a12e655fcd459871]
---

# 共享画布引擎 — GraphCanvas / NodeCard / EdgeLayer / MiniMap（pan·zoom·连线·框选）

## Scope [必填]
建 `components/desk/canvas/` 共享节点图引擎，供策略台 DAG（满配）+ Model 构建台 draw.io 图编辑器复用：GraphCanvas（`transform translate(panX,panY) scale(zoom)` + 点阵网格 + 框选 marquee + Undo/Redo 栈）/ NodeCard（head 色点+标题+lock+state 脉冲点 / body 行+badge / 进出端口）/ NodePort（pointer 连线 + 兼容性着色）/ EdgeLayer（SVG 贝塞尔 + ghost 边 + 流动 dash）/ MiniMap（缩略图+视口框）/ CanvasControls（zoom/适应/自动布局）/ CanvasBanner（diff/血缘浮层）。坐标系：节点存世界坐标，屏幕↔世界换算 + 端口锚点几何。**不做**：不写策略台/Model台的具体节点定义与业务逻辑（各台卡负责），引擎只提供受控（props/回调）的通用画布。

## 上下文 / 动机 [按需]
策略台是节点图工作台核心（16 节点/19 连线 DAG），Model 构建台是 draw.io 式图编辑器——两台共用同一画布交互范式（pan/zoom/拖拽/连线/框选/MiniMap/自动布局），抽成引擎避免两套实现漂移。是 S1/M1 的前置。

## 接线点（file:line，实现时复核）[必填]
| 文件 | 位置 | 改什么(扩展不替换) |
|---|---|---|
| app/frontend/src/components/desk/canvas/ | 新建 | GraphCanvas/NodeCard/NodePort/EdgeLayer/MiniMap/CanvasControls/CanvasBanner |
| app/frontend/src/components/desk/canvas/geometry.ts | 新建 | 世界↔屏幕换算 `_s2w`、端口锚点 `_anchorIn/Out`、贝塞尔 `_path` |

## 对抗测试设计（种已知 bug，门必抓）[必填]
1. 坐标几何：种「pan/zoom 后端口锚点/连线/框选命中错位」→ 几何单测必抓（世界↔屏幕往返一致）。
2. Undo 完整：种「拖拽/连线/删除某类操作漏入 undo 栈」→ 抓（栈深 60、快照深拷贝）。
3. locked 不可删：种「Del 删掉 locked 节点（如 Final Gate）」→ 抓（删除门跳过 locked）。

## 复用 [按需]
`charts/EvalCharts.tsx`（SVG PALETTE/scale/PAD 自绘范式可借）；G1 的 token/StatusDot/Pill。

## 红线 [按需]
扩展不替换；引擎纯受控（治理强制如 Final Gate 不可删由消费台传入规则，引擎不内置业务）。

## 非目标 [按需]
不内置任何台的节点 Registry/校验规则/codegen（属 S1/M1）；不做后端持久化。

## Open Questions（已决 1/1）[按需]
- [已决] 引擎受控化：节点/边/选中/校验规则全由 props 传入 + 回调上抛，引擎不持业务状态（策略台 vs Model台节点语义不同）。

## 验收一句话 [必填]
pan/zoom/连线/框选/MiniMap/Undo 几何与交互正确、locked 不可删；种坐标错位/Undo 漏项/删 locked 门必抓；策略台与 Model 构建台可共用同一引擎。
