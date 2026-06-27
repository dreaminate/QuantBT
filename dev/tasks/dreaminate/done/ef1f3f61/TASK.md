---
uuid: ef1f3f6126754b4eaba7ab69f47787e6
title: Research Graph canvas projection frontend data flow
status: done
owner: dreaminate
assigned_by: dreaminate
review_status: 1
priority: P1
area: strategy-console
source: goal-gap
source_ref: GOAL §2 frontend GraphCanvas data flow gap
depends_on: [af5352077a974dd68adec1024cbb2eaf, 7ba4a8b9cdce4d57b95d78406a57f129]
---

# Research Graph canvas projection frontend data flow

## Scope [必填]
把 StrategyConsole 的 GraphCanvas 从纯 `mockGraph` 初始化推进到真实后端只读投影：页面 mount 后调用 `GET /api/research-os/graph/canvas_projection?limit=24`，成功且非空时用后端 `nodes` / `edges` 替换画布；后端失败、空投影或响应格式不完整时保留 mock fallback，并在工具条显式标明 fallback。

## 接线点（file:line，实现时复核）[必填]
| 文件 | 改什么 |
|---|---|
| `app/frontend/src/pages/strategy/api.ts` | 新增 Research Graph canvas projection type 与 `fetchResearchGraphCanvasProjection` |
| `app/frontend/src/pages/StrategyConsolePage.tsx` | mount 拉取只读投影、转换成现有 DomainNode/DomainEdge、成功态关闭 Ghost proposal、真实态显示 Research Graph source/banner、`canvasReadOnly` 禁止拖拽/连线/删除/参数写入 |
| `app/frontend/src/pages/strategy/strategyConsole.test.tsx` | 覆盖真实投影渲染、read_only 交互门、raw payload 不渲染、失败 fallback |
| `app/frontend/src/pages/strategy/strategyConsoleApi.test.tsx` | 覆盖 API helper 请求新端点与 query |

## 对抗测试设计（种已知 bug，门必抓）[必填]
1. 页面必须请求 `/api/research-os/graph/canvas_projection?limit=24`，不能继续只依赖 `mockGraph`。
2. 后端成功返回真实节点时，工具条必须标 `Research Graph`，画布只显示真实 projection 节点/边，不把 mock 误标成真。
3. `read_only=true` 时 Delete 与拖拽不能改图，Ghost patch/Auto 也不能把 mock 节点混入真实投影。
4. 后端返回额外 raw 字段也不能渲染到页面；UI 只显示 safe projection view model。
5. 后端失败时必须保留 mock fallback 并明示错误来源，不显示空白真实画布或假绿灯。

## 验收一句话 [必填]
StrategyConsole GraphCanvas 现在能消费 Research Graph 只读 projection；这仍不是 writable canvas mutation engine，也不是完整 graph database 或策略代码生成链。

## 完成记录（2026-06-27）
- 新增 `fetchResearchGraphCanvasProjection`，以 typed helper 调用 Research Graph canvas projection API。
- StrategyConsole mount 后拉取 `limit=24` projection；成功且非空时替换画布数据，失败/空/格式错时保留 mock fallback 并显示来源标签。
- 真实 projection active 时启用 `canvasReadOnly`：拖拽、连线、删除、参数编辑、Ghost patch、Auto patch 均不会改图。
- 已验证：
  - `cd app/frontend && npm test -- --run src/pages/strategy/strategyConsole.test.tsx src/pages/strategy/strategyConsoleApi.test.tsx` -> 2 files / 39 passed。
  - `cd app/frontend && npm test -- --run` -> 26 files / 285 passed。
  - `cd app/frontend && npm run build` -> `tsc && vite build` PASS；仅保留既有 chunk size warning。
- 边界：这不是 canvas mutation engine、canonical command 写回、完整 graph database、完整 compiler pass implementation 或 strategy codegen。
