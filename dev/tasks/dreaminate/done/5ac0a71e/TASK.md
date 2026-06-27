---
uuid: 5ac0a71ef35f49e7a7f63f55a9e2db14
title: Agent Shell entrypoint writes QRO / Research Graph
status: done
owner: dreaminate
assigned_by: dreaminate
review_status: 1
priority: P1
area: research-os-entrypoint-wiring
source: goal-gap
source_ref: dev/GOAL.md §0/§1/§7/§8 + dev/state/dreaminate/state.md 头号 gap #1
depends_on: [0f17c0de7a81483fab30f736b6f8a91d]
---

# Agent Shell entrypoint writes QRO / Research Graph

## Scope [必填]
Wire the Agent Shell runtime into the Research OS spine so chat/workbench turns no
longer bypass QRO / Research Graph. `AgentRuntime` accepts an optional
`ResearchGraphStore`, records each user/assistant/tool/system step as a QRO
through `upsert_qro`, and FastAPI `_agent_runtime()` injects a process-level
store. Public agent chat responses and workbench done events expose QRO and
ResearchGraph command refs.

## 接线点（file:line，实现时复核）[必填]
| 文件 | 改什么 |
|---|---|
| `app/backend/app/agent/agent_runtime.py` | Add optional ResearchGraphStore wiring; record Agent Shell steps as QRO/commands without plaintext content in QRO contracts |
| `app/backend/app/main.py` | Add `RESEARCH_GRAPH_STORE`; inject it into `_agent_runtime()`; return qro/command refs from `/api/agent/chat` and workbench done events; persist refs in Mode2 chat metadata |
| `app/backend/tests/test_agent_runtime_research_graph.py` | Add unit + endpoint tests for QRO/Graph command recording and payload secrecy |

## 对抗测试设计（种已知 bug，门必抓）[必填]
1. AgentRuntime with ResearchGraphStore must record user and assistant steps as QRO commands.
2. Tool result QRO must include tool record refs but not leak tool payload secrets into QRO contracts.
3. Rejected/schema-invalid tool call must record gate event but no tool-result command refs.
4. `/api/agent/chat` must return qro_ids and research_graph_command_ids backed by the process store.

## 完成记录
- Extended `AgentTurn` with `qro_ids` and `research_graph_command_ids`.
- Added optional `research_graph`, `entry_source`, `actor`, and `owner` arguments to `AgentRuntime`.
- Added `RESEARCH_GRAPH_STORE` in `app/main.py` and injected it into `_agent_runtime()`.
- Added endpoint-visible QRO/Graph refs.
- Scoped validation:
  - `cd app/backend && python -m pytest tests/test_agent_runtime_research_graph.py -v` -> 4 passed.
  - `cd app/backend && python -m pytest tests/test_agent.py tests/test_agent_tool_status.py tests/test_agent_business_tools_a4.py tests/test_agent_permission_tristate.py tests/test_agent_runtime_research_graph.py tests/test_chat_conversations.py -q` -> 79 passed.

## 验收一句话 [必填]
Agent Shell chat/workbench now writes QRO / Research Graph refs through the
runtime spine. This wires one real entrypoint family; other entrypoints
(canvas/API/IDE/scheduler/Settings/connectors/training/execution/CI) still need
their own wiring refs before the GOAL can be called complete.
