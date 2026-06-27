---
uuid: 74632fdf608c476c8332cc50644c3645
title: StrategyConsole QRO node drag writes canonical layout hash
status: done
owner: dreaminate
assigned_by: dreaminate
review_status: 1
priority: P1
area: research-os-canvas
source: goal-loop
source_ref: GOAL §2 GraphCanvas gesture write-back gap
depends_on: [93f4027d982d4cd0af59b8e76c9aa5ee, ef1f3f6126754b4eaba7ab69f47787e6]
---

# StrategyConsole QRO node drag writes canonical layout hash

## Scope [必填]
Move the next GraphCanvas gesture from local UI state into the canonical
Research Graph path. A real Research Graph QRO node drag in StrategyConsole now
records a governed `canvas_asset_mutations` request and upserts a new QRO
version with `output_contract.canvas_layout_hash`.

## 接线点（file:line，实现时复核）[必填]
| 文件 | 改什么 |
|---|---|
| `app/frontend/src/pages/StrategyConsolePage.tsx` | Allow QRO-node drag on Research Graph projection and persist a stable layout hash through `canvas_asset_mutations` |
| `app/frontend/src/pages/strategy/strategyConsole.test.tsx` | Assert Delete still cannot remove projected nodes, while QRO drag posts `output_contract.canvas_layout_hash` and no `raw_value` |
| `app/backend/tests/test_research_graph_persistence.py` | Add `set_hash` canvas asset mutation coverage without `value_ref` |

## 对抗测试设计（种已知 bug，门必抓）[必填]
1. Projected QRO node drag must POST to `/api/research-os/graph/canvas_asset_mutations` with `operation=set_hash` and `field_path=output_contract.canvas_layout_hash`.
2. The request must not contain `raw_value`; the layout digest is a compact hash token.
3. Delete remains blocked for Research Graph projected nodes.
4. Backend `set_hash` must upsert the same QRO id at version +1 and expose only contract keys/hash in projection audit.

## 完成记录
- Added `stableCanvasLayoutHash()` and QRO-node drag persistence in StrategyConsole.
- Research Graph command nodes and non-QRO projected nodes remain non-draggable.
- Deletion, connection, parameter edits, Ghost patch and Auto patch remain gated by the existing projection read-only path.
- Added backend coverage for `output_contract.canvas_layout_hash` with `operation=set_hash`.
- Validation:
  - `cd app/backend && python -m pytest tests/test_research_graph_persistence.py tests/test_desk_projection.py -q` -> 15 passed / 2 warnings.
  - `cd app/backend && python -m pytest tests/test_research_graph_persistence.py tests/test_desk_projection.py tests/test_governed_compiler.py tests/test_strategy_console_s2.py -q` -> 59 passed / 2 warnings.
  - `cd app/backend && python -m compileall -q app/research_os/canvas_executor.py app/main.py tests/test_research_graph_persistence.py` -> PASS.
  - `cd app/frontend && npm test -- --run src/pages/strategy/strategyConsole.test.tsx src/pages/strategy/strategyConsoleApi.test.tsx` -> 2 files / 41 tests passed.
  - `cd app/frontend && npm run build` -> `tsc && vite build` PASS, with existing chunk size warning.
  - `cd app/frontend && npm test -- --run` -> 26 files / 287 tests passed.
  - `cd app/backend && python -m pytest -q` -> 1560 passed / 13 skipped / 283 warnings.

## 边界
- This records a canonical layout hash for a QRO node drag.
- It does not implement exact coordinate replay from server projection.
- It does not make connection, deletion, parameter, Ghost, Auto or other desk canvas gestures writable.
- It does not implement a complete graph database or strategy code generator.

## 验收一句话 [必填]
Dragging a real Research Graph QRO node in StrategyConsole now writes a canonical
QRO layout-hash mutation without raw payload, while non-layout GraphCanvas
write gestures remain gated.
