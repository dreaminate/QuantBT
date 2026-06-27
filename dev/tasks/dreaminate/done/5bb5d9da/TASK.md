---
uuid: 5bb5d9da2f75469580ebbc74edf456fd
title: Research Graph persistent command store
status: done
owner: dreaminate
assigned_by: dreaminate
review_status: 1
priority: P1
area: research-os-entrypoint-wiring
source: goal-gap
source_ref: dev/GOAL.md §0/§1/§8 + dev/state/dreaminate/state.md 头号 gap #1
depends_on: [4f4eab2a60344f47bcdd70de71b10b17]
---

# Research Graph persistent command store

## Scope [必填]
Replace the process-only `ResearchGraphStore` used by real entrypoints with a
durable JSONL-backed command store. Every already-wired QRO command must still
go through the same command contract, but commands and QRO summaries survive a
store restart. This closes only the Graph persistence gap for currently wired
command types. It does not wire Canvas, Scheduler, Settings/connectors,
provider adapters, training, execution, RAG index persistence, or compiler
passes.

## 接线点（file:line，实现时复核）[必填]
| 文件 | 改什么 |
|---|---|
| `app/backend/app/research_os/spine.py` | Add JSONL snapshot serialization and `PersistentResearchGraphStore` |
| `app/backend/app/main.py` | Instantiate process graph store with a data-root path |
| `app/backend/tests/test_research_graph_persistence.py` | Prove restart recovery and corrupt-line fail-closed behavior |

## 对抗测试设计（种已知 bug，门必抓）[必填]
1. Apply a QRO command through a persistent store, create a new store from the
   same path, and assert commands plus QRO audit fields survive restart.
2. Seed a malformed JSONL command file and assert startup fails loudly instead
   of silently dropping audit history.

## 验收一句话 [必填]
Research Graph commands for current QRO entrypoints persist across store
restart; malformed persistence state fails closed; existing in-memory tests and
QRO audit leakage guards stay green.

## 完成记录
- Added `PersistentResearchGraphStore`, a JSONL-backed command log with startup
  replay and fail-closed malformed-row handling.
- Wired the app-level `RESEARCH_GRAPH_STORE` to
  `DATA_ROOT/audit/research_graph_commands.jsonl`, keeping all existing
  entrypoints on the same command contract.
- Scoped validation:
  - `cd app/backend && python -m pytest tests/test_research_graph_persistence.py -q` -> 2 passed.
  - `cd app/backend && python -m pytest tests/test_research_os_spine.py -q` -> 8 passed.
  - `cd app/backend && python -m pytest tests/test_agent_runtime_research_graph.py tests/test_ds2_strategy_goal_persist.py tests/test_strategy_console_s2.py tests/test_research_graph_persistence.py -q` -> 44 passed / 2 warnings.

## 边界
This closes command/QRO persistence for currently wired command types only.
It does not implement a full graph database, RAG index persistence, Canvas
canonical mutation routing, Scheduler, Settings/connectors/provider adapters,
training, execution, CI/benchmark, or compiler passes.
