---
uuid: f509953e8b224ff8b4054d6600dd271a
title: Research Graph edge tombstone deletion
status: done
owner: dreaminate
assigned_by: dreaminate
review_status: 1
priority: P1
area: research-graph-canvas-writeback
source: goal-gap
source_ref: GOAL §1/§2/§7/§8/§16 GraphCanvas true Graph topology deletion
depends_on: [87ec505c3b6d4687b3ffe2fd3bfbb0b3]
completed_at: 2026-06-27
---

# Research Graph edge tombstone deletion

## Scope [必填]
在 `87ec505c` 的 first-class QRO-to-QRO edge creation 之后，补第一版真实 Graph edge deletion。删除不是从历史里抹掉 edge，而是写 `delete_graph_edge` tombstone command；`ResearchGraphStore.graph_edges()` 默认只返回 active edges，`graph_edges(include_deleted=True)` 仍保留审计历史，`canvas_projection` 不再显示 tombstoned edge。

## 上下文 / 动机 [按需]
此前 delete 路径只是 `output_contract.canvas_delete_ref/hash` intent 写回；这能留审计意图，但不会改变 Graph topology。本卡把 QRO-to-QRO edge 删除推进到 canonical Graph command，并保留 append-only 审计。

## 接线点（file:line，实现时复核）[必填]
| 文件 | 改什么 |
|---|---|
| `app/backend/app/research_os/spine.py` | 新增 `ResearchGraphEdgeDeletionRecord`、`delete_graph_edge` command serialization/replay、active edge filtering |
| `app/backend/app/main.py` | 新增 `POST /api/research-os/graph/edge_deletions`，复用 live QRO topology guard |
| `app/frontend/src/pages/strategy/api.ts` | 新增 `GraphEdgeDeletionRequest/Response` 与 `deleteResearchGraphEdge` |
| `app/frontend/src/pages/StrategyConsolePage.tsx` | 选中 `canvas_edge:graph:*` 后 Delete/Inspector 删除走 tombstone endpoint；旧 command→QRO edge 仍走 delete-intent write-back |
| `app/backend/tests/test_research_graph_persistence.py` | 覆盖 deletion replay、raw payload 拒绝、projection edge 消失、历史 edge 保留 |
| `app/frontend/src/pages/strategy/strategyConsole.test.tsx` | 覆盖真实 graph edge 删除不提交 `canvas_node`、`port`、`from`/`to` raw endpoint object |

## 对抗测试设计（种已知 bug，门必抓）[必填]
1. `delete_graph_edge` 必须要求 edge 已存在；不存在 edge 不可静默成功。
2. deletion command replay 后 active `graph_edges()` 为空，但 `include_deleted=True` 仍可看到原 edge。
3. `/api/research-os/graph/edge_deletions` 不能接受 `raw_value`、`payload` 等 raw value 字段。
4. projection 不再显示 `canvas_edge:graph:{edge_ref}`，也不泄露 QRO raw contract。
5. 前端 graph edge deletion body 只提交 `edge_ref` 和 canonical/audit/evidence refs，不提交 UI endpoint object。

## 红线 [按需]
- 不允许物理删除 command log 历史。
- 不允许把旧 delete-intent ref/hash 写回说成真实 Graph topology deletion。
- 不允许在 live QRO topology 上删除 edge；后端仍要求 fork draft/offline asset。

## 非目标 [按需]
不实现 QRO node tombstone，不实现 Graph node deletion，不实现 Ghost/Auto patch application，不实现自由参数 value save，不实现完整 graph database，不实现 graph query language，不实现 scheduler/API 全入口 write-back。

## 验收一句话 [必填]
选中真实 `canvas_edge:graph:*` 后删除会写 append-only `delete_graph_edge` command；projection 不再显示该 edge，审计历史仍可 replay。

## 完成记录（2026-06-27）
- `ResearchGraphEdgeDeletionRecord` 已纳入 `PersistentResearchGraphStore` JSONL command schema。
- `ResearchGraphStore.graph_edges()` 默认过滤 tombstoned edge，`include_deleted=True` 保留历史 edge。
- 新增 `POST /api/research-os/graph/edge_deletions`：要求 canonical/audit/evidence refs，拒绝 raw value、未知 edge 和 live QRO topology edit。
- StrategyConsole 选中 `canvas_edge:graph:*` 的 Delete/Inspector 删除走 edge tombstone endpoint；旧 projection 内部 command→QRO edge 仍走 delete-intent ref/hash write-back。
- 本地验证：
  - `python -m pytest app/backend/tests/test_research_graph_persistence.py -q` -> 22 passed / 2 warnings。
  - `python -m pytest app/backend/tests/test_research_os_spine.py app/backend/tests/test_desk_projection.py app/backend/tests/test_research_graph_persistence.py app/backend/tests/test_agent_runtime_research_graph.py app/backend/tests/test_governed_compiler.py app/backend/tests/test_strategy_console_s2.py app/backend/tests/test_agent_business_tools_a4.py app/backend/tests/test_chat_conversations.py app/backend/tests/test_ds2_strategy_goal_persist.py -q` -> 144 passed / 2 warnings。
  - `npm --prefix app/frontend run test:run -- src/pages/strategy/strategyConsole.test.tsx` -> 1 file / 37 tests passed。
  - `npm --prefix app/frontend run test:run` -> 26 files / 300 tests passed。
  - `npm --prefix app/frontend run build` -> `tsc && vite build` PASS，保留既有 chunk size warning。
- 边界：这是 first-class edge tombstone deletion，不是 QRO node tombstone、Graph node deletion、Ghost/Auto patch application、完整 graph database、完整 compiler pass、CI 或线上部署证明。
