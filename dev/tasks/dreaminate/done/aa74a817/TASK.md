---
uuid: aa74a817d0a84e05a54ac08c3ad33cd5
title: StrategyConsole Research Graph Ghost and Auto intent ref write-back
status: done
owner: dreaminate
assigned_by: dreaminate
review_status: 1
priority: P1
area: research-graph-canvas-writeback
source: goal-gap
source_ref: GOAL §1/§2/§7/§8/§16 GraphCanvas Ghost/Auto write-back
depends_on: [3a17e9405ed14681b49a3feb0a5dd440]
completed_at: 2026-06-27
---

# StrategyConsole Research Graph Ghost and Auto intent ref write-back

## Scope [必填]
把 StrategyConsole 真实 Research Graph projection 下的 Ghost proposal accept 和 Auto send 接到 canonical QRO asset mutation。真实投影下接受 Ghost proposal 写 `output_contract.canvas_ghost_ref/hash`，Auto 发送写 `output_contract.canvas_auto_ref/hash`，成功后重拉 `/api/research-os/graph/canvas_projection`。

## 上下文 / 动机 [按需]
`3a17e940` 已闭合 connect-intent ref/hash 写回，但 Ghost/Auto 在真实 projection 下仍只是“不改图”提示。本卡让 Ghost/Auto 至少进入 canonical QRO intent 账；不声称 patch 已被真正应用到 Graph topology 或 compiler input。

## 接线点（file:line，实现时复核）[必填]
| 文件 | 改什么 |
|---|---|
| `app/frontend/src/pages/StrategyConsolePage.tsx` | 新增 `recordGraphCanvasPatchMutation("ghost" | "auto")`；真实 projection 下 Ghost accept / Auto send 写 ref/hash，不直接应用本地 patch |
| `app/frontend/src/pages/strategy/strategyConsole.test.tsx` | 覆盖 Ghost accept、Auto send、projection 重拉、body 不含 raw ops / DrawdownGuard payload |
| `app/backend/tests/test_research_graph_persistence.py` | 覆盖 `output_contract.canvas_ghost_ref/hash` 与 `canvas_auto_ref/hash` 写入 QRO 版本且 projection audit 不泄露 ref/hash |

## 对抗测试设计（种已知 bug，门必抓）[必填]
1. 真实投影下接受 Ghost proposal 必须真打 `/api/research-os/graph/canvas_asset_mutations`，不能应用本地 mock patch。
2. 真实投影下 Auto send 必须写 `output_contract.canvas_auto_ref`，不能直接新增 DrawdownGuard 本地节点。
3. payload 必须只传 ref/hash，不传 proposal ops、raw generated patch、DrawdownGuard raw payload。
4. 后端 projection audit 只能显示 contract keys/hash，不泄露 `canvas_ghost_ref` / `canvas_auto_ref` 的值。

## 红线 [按需]
- 不允许把 Ghost/Auto intent 说成 patch 已真正应用到 Graph。
- 不允许把 proposal ops 或 generated patch raw payload 写入 QRO contract。
- 不允许在 production/live QRO 上前端静默改图；live QRO 仍由后端 existing guard 拒绝。

## 非目标 [按需]
不实现真实 patch application，不实现 compiler input 改写，不实现完整 agent patch lifecycle，不实现完整 graph database，不实现 strategy codegen。

## 验收一句话 [必填]
StrategyConsole 真实 projection 下的 Ghost/Auto 行为能被记录成 QRO 的 canonical intent ref/hash，前端和后端测试都能抓住 raw patch payload 泄漏与只改本地画布的假完成。

## 完成记录（2026-06-27）
- StrategyConsole 真实 projection 下 Ghost accept 写 `canvas_ghost_ref/hash`，Auto send 写 `canvas_auto_ref/hash`。
- 两条路径都带 canonical/audit/evidence refs，成功后重拉 projection，不应用本地 mock patch。
- 后端测试确认 Ghost/Auto intent refs 会生成 QRO 新版本，projection audit 不泄露 ref/hash 值。
- 本地验证：
  - `cd app/frontend && npm test -- --run src/pages/strategy/strategyConsole.test.tsx` -> 1 file / 36 tests passed。
  - `cd app/backend && python -m pytest tests/test_research_graph_persistence.py -q` -> 18 passed / 2 warnings。
  - `cd app/backend && python -m pytest tests/test_research_graph_persistence.py tests/test_governed_compiler.py tests/test_strategy_console_s2.py tests/test_engineering_standards.py -q` -> 69 passed / 2 warnings。
  - `cd app/frontend && npm test -- --run` -> 26 files / 299 tests passed。
  - `cd app/frontend && npm run build` -> `tsc && vite build` PASS，保留既有 chunk size warning。
- 边界：这是 Research Graph projection Ghost/Auto intent ref/hash write-back，不是真实 patch application、完整 agent patch lifecycle、完整 graph database、完整 compiler pass、CI 或线上部署证明。
