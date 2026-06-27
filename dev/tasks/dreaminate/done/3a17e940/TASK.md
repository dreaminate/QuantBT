---
uuid: 3a17e9405ed14681b49a3feb0a5dd440
title: StrategyConsole Research Graph connect intent ref write-back
status: done
owner: dreaminate
assigned_by: dreaminate
review_status: 1
priority: P1
area: research-graph-canvas-writeback
source: goal-gap
source_ref: GOAL §1/§2/§7/§8/§16 GraphCanvas connection write-back
depends_on: [fbab2819dc2849eb903d334ad12e23e0]
completed_at: 2026-06-27
---

# StrategyConsole Research Graph connect intent ref write-back

## Scope [必填]
把 StrategyConsole 真实 Research Graph projection 的端口连接操作接到 canonical QRO asset mutation。用户先点真实投影输出端口，再点输入端口，前端调用 `/api/research-os/graph/canvas_asset_mutations` 写 `output_contract.canvas_connect_ref/hash`，成功后重拉 `/api/research-os/graph/canvas_projection`。

## 上下文 / 动机 [按需]
`fbab2819` 已闭合 delete-intent ref/hash 写回，但 GraphCanvas 自由建边仍没有 canonical QRO 记录。本卡只记录 connect intent ref/hash；不声称已经真正新增 Research Graph edge、改 graph topology、或实现完整连线交互引擎。

## 接线点（file:line，实现时复核）[必填]
| 文件 | 改什么 |
|---|---|
| `app/frontend/src/pages/StrategyConsolePage.tsx` | `onConnect` 在真实 projection 下变成两步端口连接；输出端口暂存，输入端口写 `canvas_connect_ref/hash`，成功后重拉 projection |
| `app/frontend/src/pages/strategy/strategyConsole.test.tsx` | 覆盖输出端口→输入端口两步连接、projection 重拉、body 不含 `from`/`to` raw endpoint object |
| `app/backend/tests/test_research_graph_persistence.py` | 覆盖 `output_contract.canvas_connect_ref/hash` 写入 QRO 版本且 projection audit 不泄露 connect ref/hash |

## 对抗测试设计（种已知 bug，门必抓）[必填]
1. 真实投影端口连接必须真打 `/api/research-os/graph/canvas_asset_mutations`，不能只画本地临时边。
2. payload 必须写 `output_contract.canvas_connect_ref`，并只传 ref/hash，不传 `{from,to}` raw endpoint object。
3. 成功后必须重拉 `/api/research-os/graph/canvas_projection`，不能停留在本地 optimistic edge。
4. 后端 projection audit 只能显示 contract keys/hash，不泄露 `canvas_connect_ref` 或 `canvas_connect_hash` 的值。

## 红线 [按需]
- 不允许把 connect intent 说成 Research Graph edge 已真正新增。
- 不允许把 endpoint raw object 写入 QRO contract。
- 不允许在 production/live QRO 上前端静默建边；live QRO 仍由后端 existing guard 拒绝。

## 非目标 [按需]
不实现真实 graph topology mutation，不实现完整连线预览，不实现 QRO tombstone，不实现 Ghost/Auto patch 写回，不实现完整 graph database，不实现 strategy codegen。

## 验收一句话 [必填]
StrategyConsole 真实投影端口连接能被记录成 QRO 的 canonical connect-intent ref/hash，前端和后端测试都能抓住 raw endpoint payload 泄漏与只改本地画布的假建边。

## 完成记录（2026-06-27）
- StrategyConsole 真实 projection 下 `onConnect` 支持输出端口→输入端口两步 connect intent。
- 前端调用 `canvas_asset_mutations` 写 `output_contract.canvas_connect_ref/hash`，带 canonical/audit/evidence refs，成功后重拉 projection。
- 后端测试确认 `canvas_connect_ref/hash` 会生成 QRO v2，projection audit 不泄露 ref/hash 值。
- 本地验证：
  - `cd app/frontend && npm test -- --run src/pages/strategy/strategyConsole.test.tsx` -> 1 file / 34 tests passed。
  - `cd app/backend && python -m pytest tests/test_research_graph_persistence.py -q` -> 17 passed / 2 warnings。
  - `cd app/backend && python -m pytest tests/test_research_graph_persistence.py tests/test_governed_compiler.py tests/test_strategy_console_s2.py tests/test_engineering_standards.py -q` -> 68 passed / 2 warnings。
  - `cd app/frontend && npm test -- --run` -> 26 files / 297 tests passed。
  - `cd app/frontend && npm run build` -> `tsc && vite build` PASS，保留既有 chunk size warning。
- 边界：这是 Research Graph projection connect-intent ref/hash write-back，不是真实 Graph edge 创建、完整连线预览、Ghost/Auto 写回、完整 graph database、完整 compiler pass、CI 或线上部署证明。
