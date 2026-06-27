---
uuid: 6bbfa5aca26a454bb307c1ad6d275b71
title: Chat and Agent Shell GOAL entrypoint coverage producer
status: done
owner: dreaminate
assigned_by: dreaminate
review_status: 1
priority: P0
area: goal-entrypoint-coverage
source: goal
source_ref: GOAL §0/§1/§7/§8 all-entrypoint wiring; finding goal-0-17-gap-matrix-2026-06-28
depends_on: [2b1706f19b714040b93e37b23f82dcf8]
created_at: 2026-06-28
---

# Chat and Agent Shell GOAL entrypoint coverage producer

## Scope [必填]
把 chat / agent_shell 成功入口接到 GOAL entrypoint coverage：成功路径必须有 QRO、Research Graph command、Compiler IR/pass、Evidence、Permission、Replay refs；不补 canvas/IDE/scheduler。

## 接线点（file:line，实现时复核）[必填]
| 文件 | 改什么 |
|---|---|
| `app/backend/app/agent/agent_runtime.py` | Agent Shell turn/QRO 成功路径写 coverage |
| `app/backend/app/main.py` | `/api/agent/chat`、workbench/legacy chat 相关成功路径汇总或调用 coverage helper |
| `app/backend/tests/test_agent_runtime_research_graph.py`、`test_chat_conversations.py` | 覆盖 coverage 写入与缺 refs fail-closed |

## 对抗测试设计（种已知 bug，门必抓）[必填]
1. chat 成功但缺 compiler_pass_refs → 不写 coverage。
2. agent_shell step 带 silent mock fallback → coverage 422 / 不落账。
3. raw prompt/message payload 被直接存入 coverage → fail-closed。

## 验收一句话 [必填]
chat / agent_shell 成功入口可写 `entry_source=chat|agent_shell` coverage；缺 QRO/Graph/Compiler/Evidence 任一 ref 时不写 partial。

## 完成证据
- `AgentTurn` 增加 `compiler_ir_refs`、`compiler_pass_refs`、`entrypoint_coverage_refs`，成功 turn 可把 QRO/Research Graph command 编译到 GOAL entrypoint coverage。
- `/api/agent/chat` 成功路径写两条 coverage：`agent_shell:api.agent.chat` 与 `chat:api.agent.chat`。
- `/api/agent/workbench/stream` 成功路径写两条 coverage：`agent_shell:agent.workbench.stream` 与 `chat:agent.workbench.stream`；coverage 失败时发 error，不发 done。
- legacy `/api/agent/chat/{thread_id}/message` 成功 AgentRuntime turn 写 `agent_shell:legacy_mode2.chat.message` 与 `chat:legacy_mode2.chat.message` coverage；失败 turn 或 LLM error 不写成功 coverage。
- legacy `/api/agent/chat/{thread_id}/stream` 没有 AgentRuntime turn，只写真实的 `chat:legacy_mode2.chat.stream` QRO/IR/coverage；coverage 写入失败时不保存 assistant success message。
- coverage/IR/pass/QRO 只保存 refs/hash/count/status，不保存 raw user prompt、assistant text、tool payload、token 或 secret。

## 验证
- `python -m compileall -q app/backend/app app/backend/tests/test_agent_runtime_research_graph.py app/backend/tests/test_chat_conversations.py`
- `python -m pytest app/backend/tests/test_agent_runtime_research_graph.py app/backend/tests/test_chat_conversations.py -q` → **36 passed / 2 warnings**
- `python -m pytest app/backend/tests/test_goal_coverage.py app/backend/tests/test_agent_runtime_research_graph.py app/backend/tests/test_chat_conversations.py app/backend/tests/test_research_os_spine.py -q` → **66 passed / 2 warnings**
- `python -m pytest app/backend/tests -q` → **1910 passed / 13 skipped / 283 warnings**

## 边界
- 这是 chat / agent_shell entrypoint coverage producer，不是 canvas、IDE、scheduler producer。
- 这仍只覆盖 GOAL entrypoint sections `§0/§1/§7/§8` 的 runtime wiring；不是 §0-§17 full product implementation proof。
- 未声明 CI、线上、真实 provider、用户验收。
