---
uuid: 7070feed6f4d1709d62bd5457ea7c420
title: Research Graph QRO node tombstone deletion
status: done
owner: dreaminate
assigned_by: dreaminate
review_status: 1
priority: P1
area: research-graph-canvas-writeback
source: goal-gap
source_ref: GOAL §1/§2/§7/§8/§16 GraphCanvas true QRO node deletion
depends_on: [f509953e8b224ff8b4054d6600dd271a]
completed_at: 2026-06-27
---

# Research Graph QRO node tombstone deletion

## Scope [必填]
在 `f509953e` 的 first-class edge tombstone 之后，补第一版真实 QRO node tombstone。删除不是物理清掉 QRO 或 command log，而是写 `tombstone_qro` command；active projection 默认过滤 tombstoned QRO，历史 QRO 可通过 `include_tombstoned=True` 读取。

## 上下文 / 动机 [按需]
此前 StrategyConsole 删除 QRO node 只写 `output_contract.canvas_delete_ref/hash` intent；这能留意图，但不会改变 active Graph projection。本卡把 QRO node 删除推进到 canonical Research Graph command，并让相关 active graph edge 一并从 projection 消失。

## 接线点（file:line，实现时复核）[必填]
| 文件 | 改什么 |
|---|---|
| `app/backend/app/research_os/spine.py` | 新增 `QROTombstoneRecord`、`tombstone_qro` command serialization/replay、active QRO/edge filtering |
| `app/backend/app/main.py` | 新增 `POST /api/research-os/graph/qro_tombstones`，拒绝 raw value、未知 QRO 和 live QRO tombstone |
| `app/frontend/src/pages/strategy/api.ts` | 新增 `QROTombstoneRequest/Response` 与 `tombstoneResearchGraphQro` |
| `app/frontend/src/pages/StrategyConsolePage.tsx` | 选中真实 QRO node 后 Delete/Inspector 删除走 tombstone endpoint；旧 projection edge delete-intent 保留 |
| `app/backend/tests/test_research_graph_persistence.py` | 覆盖 QRO tombstone replay、raw payload 拒绝、active node/edge 移除、历史 QRO/edge 保留 |
| `app/frontend/src/pages/strategy/strategyConsole.test.tsx` | 覆盖真实 QRO node 删除不提交 `canvas_node`、params 或 raw value |

## 对抗测试设计（种已知 bug，门必抓）[必填]
1. tombstone 必须要求 QRO 已存在；未知 QRO 不可静默成功。
2. tombstone command replay 后 active `projection_index()` 不再返回该 QRO，但 `projection_index(include_tombstoned=True)` 仍可看到历史投影。
3. tombstoned QRO 相关 active `graph_edges()` 必须隐藏，`graph_edges(include_deleted=True)` 仍保留历史 edge。
4. `/api/research-os/graph/qro_tombstones` 不能接受 `raw_value`、`payload` 等 raw value 字段。
5. 前端 QRO node deletion body 只提交 `qro_id` 和 canonical/audit/evidence refs，不提交 `canvas_node:*`、params 或 raw node object。

## 红线 [按需]
- 不允许物理删除 command log 历史。
- 不允许把旧 delete-intent ref/hash 写回说成真实 QRO node tombstone。
- 不允许 tombstone live QRO；后端要求 fork draft/offline asset。

## 非目标 [按需]
不实现 restore command，不实现完整 graph database，不实现 Ghost/Auto patch application，不实现自由参数 value save，不实现 scheduler/API 全入口 write-back，不实现完整 compiler pass 或 strategy codegen。

## 验收一句话 [必填]
选中真实 `canvas_node:qro:*` 后删除会写 append-only `tombstone_qro` command；active projection 不再显示该 QRO 或其相关 active graph edge，历史 QRO/edge 仍可 replay。

## 完成记录（2026-06-27）
- `QROTombstoneRecord` 已纳入 `PersistentResearchGraphStore` JSONL command schema。
- `ResearchGraphStore.qro()` / `projection_index()` 默认过滤 tombstoned QRO，`include_tombstoned=True` 保留历史读取。
- `ResearchGraphStore.graph_edges()` 默认过滤 tombstoned QRO 相关 edge，`include_deleted=True` 保留历史 edge。
- 新增 `POST /api/research-os/graph/qro_tombstones`：要求 canonical/audit/evidence refs，拒绝 raw value、未知 QRO 和 live QRO tombstone。
- StrategyConsole 选中 `canvas_node:qro:*` 的 Delete/Inspector 删除走 QRO tombstone endpoint；旧 projection 内部 command→QRO edge 仍走 delete-intent ref/hash write-back。
- 本地验证：
  - `python -m pytest app/backend/tests/test_research_graph_persistence.py -q` -> 24 passed / 2 warnings。
  - `python -m pytest app/backend/tests/test_research_os_spine.py app/backend/tests/test_desk_projection.py app/backend/tests/test_research_graph_persistence.py app/backend/tests/test_agent_runtime_research_graph.py app/backend/tests/test_governed_compiler.py app/backend/tests/test_strategy_console_s2.py app/backend/tests/test_agent_business_tools_a4.py app/backend/tests/test_chat_conversations.py app/backend/tests/test_ds2_strategy_goal_persist.py -q` -> 146 passed / 2 warnings。
  - `npm --prefix app/frontend run test:run -- src/pages/strategy/strategyConsole.test.tsx` -> 1 file / 37 tests passed。
  - `npm --prefix app/frontend run test:run` -> 26 files / 300 tests passed。
  - `npm --prefix app/frontend run build` -> tsc + vite PASS；仍有既有 chunk size warning。
