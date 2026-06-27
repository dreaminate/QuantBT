---
uuid: b32dbcd8fb7e4ec6911c33290f5f0e09
title: StrategyGoal direct API writes QuantIntent QRO
status: done
owner: dreaminate
assigned_by: dreaminate
review_status: 1
priority: P1
area: research-os-entrypoint-wiring
source: goal-gap
source_ref: dev/GOAL.md §0/§1/§7/§8/§14 + dev/state/dreaminate/state.md 头号 gap #1
depends_on: [5937228569cf41298c7724f2c937f34a]
---

# StrategyGoal direct API writes QuantIntent QRO

## Scope [必填]
Add a direct API entrypoint for StrategyGoal / Quant Intent creation and wire it
into the same Research Graph path as Agent Shell. `POST /api/strategy_goals`
uses `StrategyGoalStore.create_from_args(..., research_graph=...)` with
`entry_source=api`, writes a `QuantIntent` QRO on success, and rejects missing
slots without fabricating a business QRO. This does not cover Canvas, IDE,
Scheduler, Settings, training, execution, or Graph persistence.

## 接线点（file:line，实现时复核）[必填]
| 文件 | 改什么 |
|---|---|
| `app/backend/app/main.py` | Add `POST /api/strategy_goals`, `GET /api/strategy_goals`, and `GET /api/strategy_goals/{goal_id}` |
| `app/backend/tests/test_ds2_strategy_goal_persist.py` | Add API tests for successful Graph write and missing-slot rejection |
| `app/backend/tests/test_agent_runtime_research_graph.py` | Use a temp StrategyGoalStore in Agent Shell Graph tests so tests do not write runtime YAML into `data/artifacts` |

## 对抗测试设计（种已知 bug，门必抓）[必填]
1. API create with natural-language text containing a secret marker must write a `QuantIntent` QRO and audit view must not expose the marker or raw prompt text.
2. API create with missing `asset_class` / `description` must return 422, write no goal file, and not add a Research Graph command.
3. Agent Shell StrategyGoal Graph tests must not leave `data/artifacts/strategy_goals` test files behind.

## 完成记录
- Added direct StrategyGoal API create/list/get endpoints.
- API success path records `entry_source=api`, `actor_source=user_manual`, and the same sanitized `QuantIntent` QRO used by the Agent tool path.
- HTTP failures return 422 with missing-slot detail and no business QRO.
- Scoped validation:
  - `cd app/backend && python -m pytest tests/test_ds2_strategy_goal_persist.py tests/test_agent_runtime_research_graph.py -v` -> 14 passed.
  - `cd app/backend && python -m pytest tests/test_agent.py tests/test_agent_tool_status.py tests/test_agent_business_tools_a4.py tests/test_agent_permission_tristate.py tests/test_agent_runtime_research_graph.py tests/test_chat_conversations.py tests/test_ds2_strategy_goal_persist.py -q` -> 89 passed.
  - `cd app/backend && python -m pytest -q` -> 1421 passed / 13 skipped / 278 warnings.
- Runtime artifact check after full suite: no files under `data/artifacts/strategy_goals`.

## 验收一句话 [必填]
StrategyGoal now has both Agent Shell and direct API Graph-writing paths for
`QuantIntent`; Canvas, IDE, Scheduler, Settings, training, execution, Graph
persistence, and compiler passes remain separate unfinished entrypoints.
