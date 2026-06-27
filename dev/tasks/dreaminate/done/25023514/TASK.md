---
uuid: 25023514a44a4c08bec71bc64e79850c
title: StrategyConsole QRO node drag replays exact canonical layout
status: done
owner: dreaminate
assigned_by: dreaminate
review_status: 1
priority: P1
area: research-os-canvas
source: goal-loop
source_ref: GOAL §2 GraphCanvas complete coordinate layout replay gap
depends_on: [74632fdf608c476c8332cc50644c3645]
---

# StrategyConsole QRO node drag replays exact canonical layout

## Scope [必填]
Replace the previous hash-only QRO node drag with an exact, persisted layout
record in the Research Graph command log. StrategyConsole QRO-node drag now
posts exact x/y/w to `/api/research-os/graph/canvas_layouts`; the backend writes
`record_canvas_layout`, binds `output_contract.canvas_layout_ref/hash` through
the canonical QRO asset mutation executor, and `canvas_projection` replays exact
server coordinates after command-log reload.

## 接线点（file:line，实现时复核）[必填]
| 文件 | 改什么 |
|---|---|
| `app/backend/app/research_os/canvas_layout.py` | Add canonical `CanvasLayoutRecord` construction/validation and layout ref/hash derivation |
| `app/backend/app/research_os/spine.py` | Persist/replay `record_canvas_layout` commands inside `PersistentResearchGraphStore` |
| `app/backend/app/main.py` | Add `/api/research-os/graph/canvas_layouts`; replay bound layout coords in `/canvas_projection`; reject missing layout refs and live QRO edits |
| `app/backend/app/research_os/canvas_executor.py` | When setting a `*_ref` with `value_hash`, update sibling `*_hash` in the QRO output contract |
| `app/frontend/src/pages/StrategyConsolePage.tsx` | Send exact QRO-node x/y/w to the layout endpoint and reinstall the server projection |
| `app/frontend/src/pages/strategy/api.ts` | Add typed `recordResearchGraphCanvasLayout()` client wrapper |
| `app/backend/tests/test_research_graph_persistence.py` | Cover exact layout write, restart replay, missing bound layout fail-closed, live QRO reject |
| `app/frontend/src/pages/strategy/strategyConsole*.test.tsx` | Cover frontend exact layout request and server-coordinate replay |

## 对抗测试设计（种已知 bug，门必抓）[必填]
1. Frontend-made layout hash only -> no longer accepted as the drag path; drag must call `/canvas_layouts` with `node_id/x/y/w` and no raw payload.
2. Missing `canvas_layout_ref` record in the command log -> projection returns 422 instead of silently falling back to local coordinates.
3. QRO runtime `live` -> layout endpoint returns 422 and appends no command.
4. Store reload -> projection still uses exact persisted coordinates from `record_canvas_layout`.
5. `set_ref` layout mutation -> QRO binds both `output_contract.canvas_layout_ref` and sibling `output_contract.canvas_layout_hash`.

## 完成记录
- Added `CanvasLayoutRecord` with deterministic `canvas_layout:<qro_id>:<hash>` refs and coordinate validation.
- Added persistent `record_canvas_layout` command replay to `ResearchGraphStore`.
- Added authenticated `/api/research-os/graph/canvas_layouts` endpoint.
- Updated canvas projection to use exact layout only when the current QRO binds the layout ref.
- Updated StrategyConsole QRO-node drag to call the exact layout endpoint and reload the projection.
- Validation:
  - `python -m pytest app/backend/tests/test_research_graph_persistence.py app/backend/tests/test_desk_projection.py -q` -> 19 passed / 2 warnings.
  - `python -m pytest app/backend/tests/test_research_graph_persistence.py app/backend/tests/test_desk_projection.py app/backend/tests/test_governed_compiler.py app/backend/tests/test_strategy_console_s2.py -q` -> 63 passed / 2 warnings.
  - `python -m compileall -q app/backend/app/research_os/canvas_layout.py app/backend/app/research_os/spine.py app/backend/app/research_os/canvas_executor.py app/backend/app/main.py` -> PASS.
  - `cd app/frontend && npm test -- --run src/pages/strategy/strategyConsole.test.tsx src/pages/strategy/strategyConsoleApi.test.tsx` -> 2 files / 42 tests passed.
  - `cd app/frontend && npm run build` -> `tsc && vite build` PASS, with existing chunk size warning.
  - `cd app/frontend && npm test -- --run` -> 26 files / 288 tests passed.
  - `cd app/backend && python -m pytest -q` -> 1564 passed / 13 skipped / 283 warnings.

## 边界
- This closes exact coordinate replay for StrategyConsole Research Graph QRO node drag.
- It does not implement GraphCanvas connection write-back, deletion write-back, parameter/Ghost/Auto asset writes, other desks, full graph database, full compiler pass implementation, or production graph query service.
- Projection read model still exposes only canvas node coordinates/status/contract keys, not raw QRO contract payload, layout refs, layout hashes, prompts, or tool payloads.

## 验收一句话 [必填]
Dragging a real Research Graph QRO node writes exact x/y/w into the Research
Graph command log, QRO binds layout ref/hash, projection replays server
coordinates after reload, and live/missing-layout paths fail closed.
