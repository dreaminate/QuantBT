---
uuid: ddec60c2118e4ed193b69e0e73444a0a
title: StrategyConsole Research Graph edge relation write-back
status: done
owner: dreaminate
assigned_by: dreaminate
review_status: 1
priority: P1
area: research-graph-canvas-writeback
source: goal-gap
source_ref: GOAL §1/§2/§7/§8/§16 GraphCanvas relation write-back
depends_on: [25023514a44a4c08bec71bc64e79850c]
completed_at: 2026-06-27
---

# StrategyConsole Research Graph edge relation write-back

## Scope [必填]
把 StrategyConsole 真实 Research Graph projection 中已选中的连线接到 canonical QRO asset mutation。用户选中真实投影边后可记录 relation ref，前端调用 `/api/research-os/graph/canvas_asset_mutations` 写 `output_contract.canvas_edge_ref/hash`，成功后重拉 `/api/research-os/graph/canvas_projection`。

## 上下文 / 动机 [按需]
`25023514` 已闭合 QRO 节点 exact layout replay，但 state/TRACE 仍把 GraphCanvas 连线、删除、参数/Ghost/Auto 写回列为画布真实性残余。本卡推进“连线 relation write-back”的第一条缝；不声称已经实现任意新连线手势、删除、参数/Ghost/Auto 全写回。

## 接线点（file:line，实现时复核）[必填]
| 文件 | 改什么 |
|---|---|
| `app/frontend/src/pages/StrategyConsolePage.tsx` | 新增 edge inspector，选中真实 projection edge 后可记录 Graph 连线；payload 只发 `canvas_edge_ref/hash`、canonical/audit refs 和 evidence refs |
| `app/frontend/src/pages/strategy/strategyConsole.test.tsx` | 覆盖 edge mutation 调用、projection 重拉、body 不含 `from`/`to`/`raw_value` |
| `app/backend/tests/test_research_graph_persistence.py` | 覆盖 `output_contract.canvas_edge_ref/hash` 写入 QRO 版本且 projection audit 不泄露 edge ref/hash |

## 对抗测试设计（种已知 bug，门必抓）[必填]
1. 选中真实投影边后必须真打 `/api/research-os/graph/canvas_asset_mutations`，不能只改前端 SVG 状态。
2. payload 必须写 `output_contract.canvas_edge_ref`，并只传 ref/hash，不传 edge `from`/`to` raw payload。
3. 成功后必须重拉 `/api/research-os/graph/canvas_projection`，不能停留在本地 optimistic state。
4. 后端 projection audit 只能显示 contract keys/hash，不泄露 `canvas_edge_ref` 或 `canvas_edge_hash` 的值。

## 红线 [按需]
- 不允许把画布边 raw endpoint payload 当 canonical asset。
- 不允许在 production/live QRO 上前端静默改边；live QRO 仍由后端 existing guard 拒绝。
- 不允许把这张卡包装成完整 GraphCanvas 手势体系。

## 非目标 [按需]
不实现自由拖拽建边手势，不实现删除写回，不实现参数/Ghost/Auto 写回，不实现完整 graph database，不实现 strategy codegen。

## 验收一句话 [必填]
StrategyConsole 真实投影边能被记录成 QRO 的 canonical edge relation ref/hash，前端和后端测试都能抓住 raw edge payload 泄漏与只改本地画布的假写回。

## 完成记录（2026-06-27）
- StrategyConsole 新增 selected edge inspector；真实投影边可点“记录连线”。
- 前端调用 `canvas_asset_mutations` 写 `output_contract.canvas_edge_ref/hash`，带 canonical/audit/evidence refs，成功后重拉 projection。
- 后端测试确认 `canvas_edge_ref/hash` 会生成 QRO v2，projection audit 不泄露 ref/hash 值。
- 本地验证：
  - `cd app/frontend && npm test -- --run src/pages/strategy/strategyConsole.test.tsx` -> 1 file / 30 tests passed。
  - `cd app/backend && python -m pytest tests/test_research_graph_persistence.py -q` -> 14 passed / 2 warnings。
  - `cd app/backend && python -m pytest tests/test_research_graph_persistence.py tests/test_governed_compiler.py tests/test_strategy_console_s2.py tests/test_engineering_standards.py -q` -> 65 passed / 2 warnings。
  - `cd app/frontend && npm test -- --run` -> 26 files / 293 tests passed。
  - `cd app/frontend && npm run build` -> `tsc && vite build` PASS，保留既有 chunk size warning。
- 边界：这是 Research Graph projection edge relation write-back 的第一条闭合，不是完整 GraphCanvas 连线创建、删除、参数/Ghost/Auto 写回、完整 graph database、完整 compiler pass、CI 或线上部署证明。
