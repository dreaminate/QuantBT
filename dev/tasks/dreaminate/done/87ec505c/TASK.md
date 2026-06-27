---
uuid: 87ec505c3b6d4687b3ffe2fd3bfbb0b3
title: Research Graph first-class QRO-to-QRO edge creation
status: done
owner: dreaminate
assigned_by: dreaminate
review_status: 1
priority: P1
area: research-graph-canvas-writeback
source: goal-gap
source_ref: GOAL §1/§2/§7/§8/§16 GraphCanvas true Graph edge creation
depends_on: [aa74a817d0a84e05a54ac08c3ad33cd5]
completed_at: 2026-06-27
---

# Research Graph first-class QRO-to-QRO edge creation

## Scope [必填]
把 StrategyConsole 真实 Research Graph projection 下的两步端口连接，从 `canvas_connect_ref/hash` intent 写回推进为第一版真实 Research Graph edge command。用户从一个 QRO 输出端口连接到另一个 QRO 输入端口时，前端调用 `/api/research-os/graph/edges`，后端记录可 JSONL replay 的 `ResearchGraphEdgeRecord`，并在 `/api/research-os/graph/canvas_projection` 中投影为 `canvas_edge:graph:*` QRO-to-QRO edge。

## 上下文 / 动机 [按需]
`aa74a817` 之后，StrategyConsole 已有 QRO 参数、删除意图、连接意图、Ghost/Auto 意图 ref/hash 写回，但真实 Graph topology 仍没有第一类边对象。本卡先做最小真实拓扑切片：edge command 入 Research Graph store、可持久化重放、projection 可见；不声称完整 graph database 或完整 writable canvas engine 已完成。

## 接线点（file:line，实现时复核）[必填]
| 文件 | 改什么 |
|---|---|
| `app/backend/app/research_os/spine.py` | 新增 `ResearchGraphEdgeRecord`、`record_graph_edge` command serialization/replay、`ResearchGraphStore.graph_edges()` |
| `app/backend/app/main.py` | 新增 `POST /api/research-os/graph/edges`；`canvas_projection` 追加可见 QRO-to-QRO graph edges |
| `app/frontend/src/pages/strategy/api.ts` | 新增 `GraphEdgeRequest/Response` 与 `recordResearchGraphEdge` |
| `app/frontend/src/pages/StrategyConsolePage.tsx` | 真实 projection 两步连接只允许不同 QRO 节点，成功创建 first-class Graph edge 后重拉 projection |
| `app/backend/tests/test_research_graph_persistence.py` | 覆盖 edge command replay、API raw payload 拒绝、projection edge 显示、raw contract 不泄露 |
| `app/frontend/src/pages/strategy/strategyConsole.test.tsx` | 覆盖 QRO-to-QRO 端口连接打 `/api/research-os/graph/edges`，不提交 canvas node/port raw endpoint object |

## 对抗测试设计（种已知 bug，门必抓）[必填]
1. `record_graph_edge` 必须在 source/target QRO 已存在时才入 store；不存在 QRO 时 fail-closed。
2. `/api/research-os/graph/edges` 不能接受 `raw_value`、`payload` 等 raw value 字段。
3. projection 只能展示 QRO-to-QRO edge id/ports，不能泄露 input/output contract 原值。
4. 前端两步连接不能提交 `canvas_node:*`、`port`、`from`/`to` raw endpoint object。
5. 非 QRO 或同一个 QRO 的连接不能伪造成 Graph edge。

## 红线 [按需]
- 不允许把旧 `canvas_connect_ref/hash` intent 说成真实 Graph edge。
- 不允许把前端本地线条作为完成证据；必须有 store command、API、projection 和 tests。
- 不允许在 live QRO topology 上直接写 edge；后端仍要求 fork draft/offline asset。

## 非目标 [按需]
不实现真实 QRO tombstone / Graph topology deletion，不实现 Ghost/Auto patch application，不实现自由参数 value save，不实现完整 graph database，不实现完整 graph query language，不实现 scheduler/API 全入口 write-back，不实现 compiler input rewrite。

## 验收一句话 [必填]
StrategyConsole 真实 projection 下的 QRO-to-QRO 连线能落为可 replay 的 Research Graph edge command，并在 canvas projection 中作为真实 QRO-to-QRO edge 出现；请求和投影都不泄露 raw contract 或 canvas endpoint object。

## 完成记录（2026-06-27）
- `ResearchGraphEdgeRecord` 已纳入 `PersistentResearchGraphStore` JSONL command schema，store replay 后可恢复 `graph_edges()`。
- 新增 `POST /api/research-os/graph/edges`：要求 canonical/audit/evidence refs，拒绝 raw value 字段、未知 QRO、same-QRO edge、live QRO topology edit。
- `GET /api/research-os/graph/canvas_projection` 会把当前选中 projection 中两端都可见的 edge 渲染为 `canvas_edge:graph:{edge_ref}`。
- StrategyConsole 真实 projection 两步连接改为 QRO-to-QRO edge creation；command-node→QRO 这类 projection 内部边不再被伪装成用户 Graph edge。
- 本地验证：
  - `python -m pytest app/backend/tests/test_research_graph_persistence.py -q` -> 20 passed / 2 warnings。
  - `python -m pytest app/backend/tests/test_research_os_spine.py app/backend/tests/test_desk_projection.py app/backend/tests/test_research_graph_persistence.py app/backend/tests/test_agent_runtime_research_graph.py app/backend/tests/test_governed_compiler.py app/backend/tests/test_strategy_console_s2.py app/backend/tests/test_agent_business_tools_a4.py app/backend/tests/test_chat_conversations.py app/backend/tests/test_ds2_strategy_goal_persist.py -q` -> 142 passed / 2 warnings。
  - `npm --prefix app/frontend run test:run -- src/pages/strategy/strategyConsole.test.tsx` -> 1 file / 36 tests passed。
  - `npm --prefix app/frontend run test:run` -> 26 files / 299 tests passed。
  - `npm --prefix app/frontend run build` -> `tsc && vite build` PASS，保留既有 chunk size warning。
- 边界：这是 first-class QRO-to-QRO edge creation，不是真实 Graph deletion、Ghost/Auto patch application、完整 graph database、完整 compiler pass、CI 或线上部署证明。
