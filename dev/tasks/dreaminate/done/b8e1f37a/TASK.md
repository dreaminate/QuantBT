---
uuid: b8e1f37a4925459db7fb7b978a09d9ac
title: GOAL §7 Agent OS visible workflow contract
status: done
owner: dreaminate
assigned_by: dreaminate
review_status: 1
priority: P1
area: research-os-agent-os
source: goal-loop
source_ref: dev/GOAL.md §7 Agent Shell / Multi-Agent Research OS
depends_on: []
---

# GOAL §7 Agent OS visible workflow contract

## Scope [必填]
Add a runtime contract for visible Agent workflow events, AgentPlan sections,
RoleAgent dispatch through LLM Gateway and permission refs, verifier independence
records, Agent code-change diff/test/rollback records, schema-valid tool calls,
and completion claims backed by tools, validation, and artifacts.

## 接线点（file:line，实现时复核）[必填]
| 文件 | 改什么 |
|---|---|
| `app/backend/app/research_os/agent_os.py` | Add visible event, plan, dispatch, code change, tool call, and completion validators |
| `app/backend/app/research_os/__init__.py` | Export §7 Agent OS types |
| `app/backend/tests/test_agent_os_contract.py` | Add adversarial tests for Agent OS workflow honesty |

## 对抗测试设计（种已知 bug，门必抓）[必填]
1. Workflow event not visible/audited -> reject.
2. AgentPlan missing todo/dependencies/acceptance gates/rollback -> reject.
3. Role agent bypasses LLM Gateway or reads credentials -> reject.
4. Verifier challenge lacks provider/model/context or reuses builder context -> reject.
5. Agent code change missing diff/test/rollback/permission -> reject.
6. Schema-invalid tool call dispatched -> reject.
7. Agent completion claim without tool/validation/artifact records -> reject.

## 完成记录
- Added `app/backend/app/research_os/agent_os.py`.
- Added `app/backend/tests/test_agent_os_contract.py`.
- Exported Agent OS contract types from `app.research_os`.
- Scoped validation:
  - `cd app/backend && python -m pytest tests/test_agent_os_contract.py -v` -> 8 passed.

## 验收一句话 [必填]
GOAL §7 now has a tested Agent OS visible workflow contract. It is not yet
enforced across every existing chat/agent/tool endpoint.
