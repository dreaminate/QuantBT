---
uuid: 5937228569cf41298c7724f2c937f34a
title: StrategyGoal create writes QuantIntent QRO
status: done
owner: dreaminate
assigned_by: dreaminate
review_status: 1
priority: P1
area: research-os-entrypoint-wiring
source: goal-gap
source_ref: dev/GOAL.md §1/§7/§8/§14 + dev/state/dreaminate/state.md 头号 gap #1/#4
depends_on: [5ac0a71ef35f49e7a7f63f55a9e2db14, 1668fc7c3c2a4471a743107fd44e024d]
---

# StrategyGoal create writes QuantIntent QRO

## Scope [必填]
Wire the first business object created by Agent Shell into the Research Graph:
successful `strategy_goal.create` calls now record a `QuantIntent` QRO for the
persisted StrategyGoal. The QRO stores hashes, structure fields, and refs only.
This does not claim factor/model/signal/strategy endpoint coverage or a governed
compiler pass.

## 接线点（file:line，实现时复核）[必填]
| 文件 | 改什么 |
|---|---|
| `app/backend/app/research_os/spine.py` | Add `QROType.QUANT_INTENT` for StrategyGoal / Quant Intent records |
| `app/backend/app/strategy_goal_store.py` | Add optional ResearchGraph recording on successful `create_from_args` |
| `app/backend/app/main.py` | Pass `RESEARCH_GRAPH_STORE` into the Agent Shell `strategy_goal.create` tool registration |
| `app/backend/tests/test_ds2_strategy_goal_persist.py` | Verify successful StrategyGoal creation records `QuantIntent` QRO without prompt plaintext |
| `app/backend/tests/test_agent_runtime_research_graph.py` | Verify Agent Shell tool call creates a visible `QuantIntent` QRO in Graph audit output |

## 对抗测试设计（种已知 bug，门必抓）[必填]
1. Natural-language StrategyGoal text includes a secret marker; the persisted goal may keep its YAML description, but QRO contracts must not expose the prompt text or marker.
2. Agent Shell calls `strategy_goal.create`; the Graph audit endpoint must show a `QuantIntent` QRO with `strategy_goal_id`, goal hash, asset class, objective, and horizon.
3. Missing-slot failures must not fabricate business QROs; the Agent step QRO records the failure path separately.

## 完成记录
- Added `QuantIntent` to QRO types.
- `StrategyGoalStore.create_from_args(..., research_graph=...)` records a `QRORecord(QROType.QUANT_INTENT)` only on success.
- `AgentRuntime` still records chat/tool steps; the StrategyGoal store now records the business object itself.
- Graph audit allowlist now shows StrategyGoal structural refs without raw args or prompt text.
- Scoped validation:
  - `cd app/backend && python -m pytest tests/test_ds2_strategy_goal_persist.py tests/test_agent_runtime_research_graph.py -v` -> 12 passed.
  - `cd app/backend && python -m pytest tests/test_agent.py tests/test_agent_tool_status.py tests/test_agent_business_tools_a4.py tests/test_agent_permission_tristate.py tests/test_agent_runtime_research_graph.py tests/test_chat_conversations.py tests/test_ds2_strategy_goal_persist.py -q` -> 87 passed.
  - `cd app/backend && python -m pytest tests/test_research_os_spine.py -v` -> 8 passed.

## 验收一句话 [必填]
Agent Shell now writes both interaction-step QROs and the first concrete business
object QRO (`QuantIntent` / StrategyGoal); remaining business objects and other
entrypoints still need their own QRO / Research Graph wiring before GOAL §0–§17
can be called complete.
