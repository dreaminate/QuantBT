---
uuid: 1668fc7c3c2a4471a743107fd44e024d
title: Research Graph audit read endpoint
status: done
owner: dreaminate
assigned_by: dreaminate
review_status: 1
priority: P1
area: research-os-entrypoint-wiring
source: goal-gap
source_ref: dev/GOAL.md §1/§7/§8 + dev/state/dreaminate/state.md 头号 gap #1
depends_on: [5ac0a71ef35f49e7a7f63f55a9e2db14]
---

# Research Graph audit read endpoint

## Scope [必填]
Expose a read-only Research Graph audit surface for the in-process Graph store so
Agent Shell QRO / command refs can be inspected through HTTP without leaking raw
prompt text or tool payloads. This adds visibility for the first wired entrypoint
family; it does not claim durable persistence, compiler passes, or full-entrypoint
coverage.

## 接线点（file:line，实现时复核）[必填]
| 文件 | 改什么 |
|---|---|
| `app/backend/app/main.py` | Add sanitized QRO / ResearchGraphCommand audit serializers and `GET /api/research-os/graph/commands` |
| `app/backend/tests/test_agent_runtime_research_graph.py` | Add endpoint test proving Agent Shell command ids are retrievable and user plaintext is not exposed |

## 对抗测试设计（种已知 bug，门必抓）[必填]
1. Send `/api/agent/chat` with a secret marker in the user prompt, then read `/api/research-os/graph/commands`; the command ids must be present and the secret / prompt text must be absent from the audit response.
2. Audit response must expose status axes and hash-level contract metadata so QRO refs are inspectable without returning raw payload fields.

## 完成记录
- Added `GET /api/research-os/graph/commands?limit=...`.
- The endpoint returns command id, source, command type, actor source, evidence refs, tool refs, QRO id/type/status axes/lineage, and allowlisted contract hash metadata.
- It intentionally does not return raw `command.payload`, raw message content, or raw tool result payload.
- Scoped validation:
  - `cd app/backend && python -m pytest tests/test_agent_runtime_research_graph.py -v` -> 5 passed.
  - `cd app/backend && python -m pytest tests/test_agent.py tests/test_agent_tool_status.py tests/test_agent_business_tools_a4.py tests/test_agent_permission_tristate.py tests/test_agent_runtime_research_graph.py tests/test_chat_conversations.py -q` -> 80 passed.

## 验收一句话 [必填]
Agent Shell Graph refs are now readable through a sanitized audit endpoint; this
improves §7 visible workflow but still leaves canvas/API/IDE/scheduler and the
other GOAL entrypoints to be wired into the same QRO / Research Graph path.
