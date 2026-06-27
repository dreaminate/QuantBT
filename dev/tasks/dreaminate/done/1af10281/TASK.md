---
uuid: 1af102812f6fc8f33cf481fb20a18397
title: Research Graph Ghost/Auto patch application
status: done
owner: dreaminate
assigned_by: dreaminate
review_status: 1
priority: P1
area: research-graph-canvas-writeback
source: goal-gap
source_ref: GOAL §1/§2/§7/§8/§16 GraphCanvas Ghost/Auto patch application
depends_on: [7070feed6f4d1709d62bd5457ea7c420]
completed_at: 2026-06-27
---

# Research Graph Ghost/Auto patch application

## Scope [必填]
在 Ghost/Auto 只写 intent ref/hash 之后，补第一版可审计 Graph patch application。接受 Ghost 或 Auto 不直接把 raw ops/DrawdownGuard 节点发到后端，而是写 `apply_graph_patch` command、生成 `GraphPatchApplication` QRO，并从目标 QRO 建一条 first-class graph edge。

## 上下文 / 动机 [按需]
此前 `aa74a817` 只证明 StrategyConsole 能把 Ghost/Auto intent 记录进 QRO output contract；projection 不会体现 patch 已被应用。本卡把“已应用”落到 Research Graph 的 command/QRO/edge 三件套，但仍保持 raw patch payload 不跨信任边界。

## 接线点（file:line，实现时复核）[必填]
| 文件 | 改什么 |
|---|---|
| `app/backend/app/research_os/spine.py` | 新增 `GraphPatchApplicationRecord`、`apply_graph_patch` command serialization/replay、target QRO guard |
| `app/backend/app/main.py` | 新增 `POST /api/research-os/graph/patch_applications`，写 patch command、patch QRO、graph edge |
| `app/frontend/src/pages/strategy/api.ts` | 新增 `GraphPatchApplicationRequest/Response` 与 `applyResearchGraphPatch` |
| `app/frontend/src/pages/StrategyConsolePage.tsx` | Ghost accept / Auto send 调用 patch application endpoint，成功后重拉 projection |
| `app/backend/tests/test_research_graph_persistence.py` | 覆盖 patch replay、raw ops 拒绝、patch QRO + edge projection |
| `app/frontend/src/pages/strategy/strategyConsole.test.tsx` | 覆盖 Ghost/Auto 应用 Graph patch 且不提交 raw ops/DrawdownGuard |

## 对抗测试设计（种已知 bug，门必抓）[必填]
1. `apply_graph_patch` 必须要求 target QRO 已存在且 active；未知或 tombstoned target 不可静默成功。
2. live QRO 不可被 patch application 修改 topology；必须 fork draft/offline asset。
3. `/api/research-os/graph/patch_applications` 不能接受 `ops`、`diff`、`node`、`edge`、`params`、`raw_value` 等 raw patch fields。
4. 成功应用后 active projection 必须出现 `GraphPatchApplication` QRO 和 `canvas_edge:graph:*`。
5. projection 不泄露 patch_ref、patch_hash、target QRO raw contract 或 proposal raw text。

## 红线 [按需]
- 不允许把前端 mock proposal ops 直接当后端事实。
- 不允许只写 intent ref/hash 后声称 patch 已应用。
- 不允许把 GraphPatchApplication QRO 说成完整 operation-level patch replay 或完整 agent patch lifecycle。

## 非目标 [按需]
不实现 operation-level raw patch artifact store，不实现 patch restore/revert，不实现自由参数值级保存，不实现完整 graph database，不实现完整 agent patch lifecycle，不实现策略代码生成。

## 验收一句话 [必填]
Ghost accept / Auto send 会写 `apply_graph_patch` command，新增 `GraphPatchApplication` QRO 和 first-class graph edge；前端请求不提交 raw ops/DrawdownGuard，projection 重拉后显示 patch QRO。

## 完成记录（2026-06-27）
- `GraphPatchApplicationRecord` 已纳入 `PersistentResearchGraphStore` JSONL command schema。
- 新增 `POST /api/research-os/graph/patch_applications`：要求 target QRO、patch kind/ref/hash、canonical/audit/evidence refs，拒绝 raw patch fields、未知 target 和 live target。
- endpoint 成功后写三条 command：`apply_graph_patch`、patch QRO `upsert_qro`、`record_graph_edge`。
- StrategyConsole Ghost accept / Auto send 从 intent write-back 改为 patch application endpoint；成功后重拉 `/api/research-os/graph/canvas_projection`，显示 `GraphPatchApplication` QRO。
- 本地验证：
  - `python -m pytest app/backend/tests/test_research_graph_persistence.py -q` -> 26 passed / 2 warnings。
  - `python -m pytest app/backend/tests/test_research_os_spine.py app/backend/tests/test_desk_projection.py app/backend/tests/test_research_graph_persistence.py app/backend/tests/test_agent_runtime_research_graph.py app/backend/tests/test_governed_compiler.py app/backend/tests/test_strategy_console_s2.py app/backend/tests/test_agent_business_tools_a4.py app/backend/tests/test_chat_conversations.py app/backend/tests/test_ds2_strategy_goal_persist.py -q` -> 148 passed / 2 warnings。
  - `npm --prefix app/frontend run test:run -- src/pages/strategy/strategyConsole.test.tsx` -> 1 file / 37 tests passed。
  - `npm --prefix app/frontend run test:run` -> 26 files / 300 tests passed。
  - `npm --prefix app/frontend run build` -> tsc + vite PASS；仍有既有 chunk size warning。
