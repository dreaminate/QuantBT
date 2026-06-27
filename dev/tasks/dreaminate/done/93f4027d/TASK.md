---
uuid: 93f4027d982d4cd0af59b8e76c9aa5ee
title: Research Graph canonical canvas asset mutation executor
status: done
owner: dreaminate
assigned_by: dreaminate
review_status: 1
priority: P1
area: research-os-canvas
source: goal-loop
source_ref: GOAL §1/§2/§8 frontend edit wiring + canonical asset mutation executor gap
depends_on: [8a0a6102c8c54022a93f955458dbc98c, ef1f3f6126754b4eaba7ab69f47787e6]
---

# Research Graph canonical canvas asset mutation executor

## Scope [必填]
Close the next writable-canvas gap without creating a second truth store. The
existing `/api/research-os/graph/canvas_mutations` endpoint records mutation
audit only; this card adds an execution path that records the mutation and
upserts a new QRO version with reference/hash-only edits.

## 接线点（file:line，实现时复核）[必填]
| 文件 | 改什么 |
|---|---|
| `app/backend/app/research_os/canvas_executor.py` | New canonical Canvas asset mutation executor |
| `app/backend/app/main.py` | New `POST /api/research-os/graph/canvas_asset_mutations` endpoint |
| `app/backend/tests/test_research_graph_persistence.py` | Tests for QRO version update and live-QRO rejection |
| `app/frontend/src/pages/strategy/api.ts` | Frontend API wrapper for canonical canvas asset mutation |
| `app/frontend/src/pages/StrategyConsolePage.tsx` | Inspector action that writes a selected QRO node through the canonical endpoint and reloads projection |
| `app/frontend/src/pages/strategy/strategyConsole*.test.tsx` | API + page tests for endpoint call, no raw value, projection reload |

## 对抗测试设计（种已知 bug，门必抓）[必填]
1. Canvas asset mutation against an existing StrategyBook/PortfolioPolicy QRO must record two Research Graph commands: `record_canvas_mutation` then `upsert_qro`.
2. Updated QRO must keep the same `qro_id`, increment `version`, expose only contract keys/hash in projection, and not leak raw refs through projection audit.
3. Live QRO mutation must reject; edit requires a draft/offline asset.
4. Strategy desk cross-write to Factor formula remains rejected through the existing desk projection validator.
5. Frontend write path must POST to `/api/research-os/graph/canvas_asset_mutations`, send no `raw_value`, and reload `/canvas_projection`.

## 完成记录
- Added `execute_canvas_asset_mutation()` in Research OS.
- Added `POST /api/research-os/graph/canvas_asset_mutations` with authenticated actor binding.
- The executor validates desk mutation rules, target QRO existence, QRO type match, live runtime rejection, and `_ref` / `_hash` contract-field boundaries.
- StrategyConsole now exposes a QRO-node inspector action that records a canonical edit through the backend and reloads the Research Graph projection.
- Scoped validation so far:
  - `cd app/backend && python -m pytest tests/test_research_graph_persistence.py tests/test_desk_projection.py -q` -> 14 passed / 2 warnings.
  - `cd app/backend && python -m pytest tests/test_research_graph_persistence.py tests/test_desk_projection.py tests/test_governed_compiler.py tests/test_strategy_console_s2.py -q` -> 58 passed / 2 warnings.
  - `cd app/frontend && npm test -- --run src/pages/strategy/strategyConsole.test.tsx src/pages/strategy/strategyConsoleApi.test.tsx` -> 2 files / 41 tests passed.
  - `cd app/frontend && npm run build` -> `tsc && vite build` PASS, with existing chunk size warning.
  - `cd app/backend && python -m pytest -q` -> 1559 passed / 13 skipped / 283 warnings.

## 边界
- This is the first canonical asset mutation executor for QRO-backed canvas edits.
- It does not make every GraphCanvas gesture writable.
- It does not implement a full graph database.
- It does not generate strategy code.
- It does not wire every desk/API/scheduler edit path through this executor yet.

## 验收一句话 [必填]
StrategyConsole can now trigger a canonical Research Graph asset mutation for a
selected QRO node; the backend records mutation audit and upserts a new QRO
version without raw payload.
