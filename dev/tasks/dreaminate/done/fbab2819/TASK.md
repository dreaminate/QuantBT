---
uuid: fbab2819dc2849eb903d334ad12e23e0
title: StrategyConsole Research Graph delete intent ref write-back
status: done
owner: dreaminate
assigned_by: dreaminate
review_status: 1
priority: P1
area: research-graph-canvas-writeback
source: goal-gap
source_ref: GOAL §1/§2/§7/§8/§16 GraphCanvas delete write-back
depends_on: [a63af9d75d464404b8448945b7182fac]
completed_at: 2026-06-27
---

# StrategyConsole Research Graph delete intent ref write-back

## Scope [必填]
把 StrategyConsole 真实 Research Graph projection 的节点/连线删除操作接到 canonical QRO asset mutation。用户选中真实投影 QRO 节点后按 Delete，或选中真实投影连线后点“记录删除”，前端调用 `/api/research-os/graph/canvas_asset_mutations` 写 `output_contract.canvas_delete_ref/hash`，成功后重拉 `/api/research-os/graph/canvas_projection`。

## 上下文 / 动机 [按需]
`a63af9d7` 已闭合 QRO-node parameter ref/hash 写回，但 state/TRACE 仍把 GraphCanvas 删除列为画布真实性残余。本卡只记录删除意图 ref/hash；不声称真正删除 QRO、删除 Research Graph 节点/边、或实现完整拓扑 mutation。

## 接线点（file:line，实现时复核）[必填]
| 文件 | 改什么 |
|---|---|
| `app/frontend/src/pages/StrategyConsolePage.tsx` | 真实 projection 下 Delete/Backspace 对 QRO 节点走 delete-intent write-back；edge inspector 增加“记录删除”；payload 只发 `canvas_delete_ref/hash`、canonical/audit refs 和 evidence refs |
| `app/frontend/src/pages/strategy/strategyConsole.test.tsx` | 覆盖 QRO 节点 Delete、edge 删除按钮、projection 重拉、body 不含 raw node/edge payload |
| `app/backend/tests/test_research_graph_persistence.py` | 覆盖 `output_contract.canvas_delete_ref/hash` 写入 QRO 版本且 projection audit 不泄露 delete ref/hash |

## 对抗测试设计（种已知 bug，门必抓）[必填]
1. 真实投影 QRO 节点按 Delete 必须真打 `/api/research-os/graph/canvas_asset_mutations`，不能只从本地 DOM 删除节点。
2. 真实投影连线点“记录删除”必须写 `output_contract.canvas_delete_ref`，不传 edge `from`/`to` raw payload。
3. 删除写回成功后必须重拉 `/api/research-os/graph/canvas_projection`，不能停留在本地 optimistic state。
4. 后端 projection audit 只能显示 contract keys/hash，不泄露 `canvas_delete_ref` 或 `canvas_delete_hash` 的值。

## 红线 [按需]
- 不允许把删除意图说成 QRO/Graph 节点已经被真正删除。
- 不允许把节点 params 或 edge endpoint raw payload 写入 QRO contract。
- 不允许在 production/live QRO 上前端静默删除；live QRO 仍由后端 existing guard 拒绝。

## 非目标 [按需]
不实现真实 QRO tombstone，不实现 Research Graph 拓扑删除，不实现自由建边，不实现 Ghost/Auto patch 写回，不实现完整 graph database，不实现 strategy codegen。

## 验收一句话 [必填]
StrategyConsole 真实投影 QRO 节点/连线的删除操作能被记录成 QRO 的 canonical delete-intent ref/hash，前端和后端测试都能抓住 raw payload 泄漏与只改本地画布的假删除。

## 完成记录（2026-06-27）
- StrategyConsole 在真实 projection 下把 QRO 节点 Delete/Backspace 接到 `canvas_delete_ref/hash` 写回；连线 inspector 增加“记录删除”。
- 前端调用 `canvas_asset_mutations` 写 `output_contract.canvas_delete_ref/hash`，带 canonical/audit/evidence refs，成功后重拉 projection。
- 后端测试确认 `canvas_delete_ref/hash` 会生成 QRO v2，projection audit 不泄露 ref/hash 值。
- 本地验证：
  - `cd app/frontend && npm test -- --run src/pages/strategy/strategyConsole.test.tsx` -> 1 file / 33 tests passed。
  - `cd app/backend && python -m pytest tests/test_research_graph_persistence.py -q` -> 16 passed / 2 warnings。
  - `cd app/backend && python -m pytest tests/test_research_graph_persistence.py tests/test_governed_compiler.py tests/test_strategy_console_s2.py tests/test_engineering_standards.py -q` -> 67 passed / 2 warnings。
  - `cd app/frontend && npm test -- --run` -> 26 files / 296 tests passed。
  - `cd app/frontend && npm run build` -> `tsc && vite build` PASS，保留既有 chunk size warning。
- 边界：这是 Research Graph projection delete-intent ref/hash write-back，不是真实 QRO tombstone、Graph 拓扑删除、自由建边、Ghost/Auto 写回、完整 graph database、完整 compiler pass、CI 或线上部署证明。
