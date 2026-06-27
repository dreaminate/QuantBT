---
uuid: 9a6db34e0fe0f3d27e91d6a0cda27051
title: Research Graph canvas parameter value save
status: done
owner: dreaminate
assigned_by: dreaminate
review_status: 1
priority: P1
area: research-graph-canvas-writeback
source: goal-gap
source_ref: GOAL §1/§2/§7/§8/§16 GraphCanvas free parameter value save
depends_on: [1af102812f6fc8f33cf481fb20a18397]
completed_at: 2026-06-27
---

# Research Graph canvas parameter value save

## Scope [必填]
把 StrategyConsole 真实 Research Graph QRO 参数保存从“只写 `canvas_param_ref/hash` intent”推进到 value-level append-only record。后端写 `set_canvas_parameter` command，保存 `param_key/param_value` 到 `CanvasParameterValueRecord`，再把 QRO output contract 更新为 parameter ref/hash。

## 上下文 / 动机 [按需]
此前 `a63af9d7` 只记录参数 intent ref/hash，没有保存用户实际要改的参数值。本卡把参数名/值作为受控业务字段进入后端，但 projection/QRO audit 面仍不泄露具体值。

## 接线点（file:line，实现时复核）[必填]
| 文件 | 改什么 |
|---|---|
| `app/backend/app/research_os/spine.py` | 新增 `CanvasParameterValueRecord`、`set_canvas_parameter` command serialization/replay、target QRO guard |
| `app/backend/app/main.py` | 新增 `POST /api/research-os/graph/canvas_parameter_values`，保存 value record 并 upsert QRO ref/hash |
| `app/frontend/src/pages/strategy/api.ts` | 新增 `CanvasParameterValueRequest/Response` 与 `saveResearchGraphCanvasParameterValue` |
| `app/frontend/src/pages/StrategyConsolePage.tsx` | Inspector 增加参数名/参数值输入；“记录参数”走 value-level endpoint |
| `app/backend/tests/test_research_graph_persistence.py` | 覆盖 parameter value replay、raw wrapper 拒绝、projection 不泄露值 |
| `app/frontend/src/pages/strategy/strategyConsole.test.tsx` | 覆盖参数名/值提交、raw node wrapper 不提交 |

## 对抗测试设计（种已知 bug，门必抓）[必填]
1. `set_canvas_parameter` 必须要求 target QRO 已存在且 active；未知/tombstoned target 不可静默成功。
2. target_asset_type 必须匹配 QRO 类型，否则不能写错资产。
3. live QRO 不可保存参数；必须 fork draft/offline asset。
4. endpoint 不能接受 `raw_value`、`payload`、`params`、`node` 等 wrapper raw payload。
5. projection 不泄露 `param_value`、parameter_ref 或 value_hash，只暴露 contract keys/hash。

## 红线 [按需]
- 不允许把 node.params 整包提交后端。
- 不允许把参数值塞进 GraphCanvas projection 原文。
- 不允许明文 credential material 作为参数值保存。

## 非目标 [按需]
不实现完整参数 schema/类型系统，不实现参数 diff UI，不实现所有节点/边布局，不实现 secret 参数存储，不实现 operation-level patch replay/revert，不实现完整 graph database。

## 验收一句话 [必填]
在真实 Research Graph projection 下填写参数名/值并点击“记录参数”会写 `set_canvas_parameter` command，QRO 更新 parameter ref/hash；请求不提交 raw node wrapper，projection 不泄露具体参数值。

## 完成记录（2026-06-27）
- `CanvasParameterValueRecord` 已纳入 `PersistentResearchGraphStore` JSONL command schema。
- 新增 `POST /api/research-os/graph/canvas_parameter_values`：要求 target QRO、target asset type、param key/value、canonical/audit/evidence refs，拒绝 raw wrapper fields、secret-like value、未知 target 和 live target。
- endpoint 成功后写两条 command：`set_canvas_parameter`、QRO `upsert_qro`；QRO output contract 只保存 `canvas_param_value_ref/hash` 和 `canvas_param_key`。
- StrategyConsole Inspector 新增参数名/参数值输入；“记录参数”改为 value-level endpoint，成功后重拉 `/api/research-os/graph/canvas_projection`。
- 本地验证：
  - `python -m pytest app/backend/tests/test_research_graph_persistence.py -q` -> 28 passed / 2 warnings。
  - `python -m pytest app/backend/tests/test_research_os_spine.py app/backend/tests/test_desk_projection.py app/backend/tests/test_research_graph_persistence.py app/backend/tests/test_agent_runtime_research_graph.py app/backend/tests/test_governed_compiler.py app/backend/tests/test_strategy_console_s2.py app/backend/tests/test_agent_business_tools_a4.py app/backend/tests/test_chat_conversations.py app/backend/tests/test_ds2_strategy_goal_persist.py -q` -> 150 passed / 2 warnings。
  - `npm --prefix app/frontend run test:run -- src/pages/strategy/strategyConsole.test.tsx` -> 1 file / 37 tests passed。
  - `npm --prefix app/frontend run test:run` -> 26 files / 300 tests passed。
  - `npm --prefix app/frontend run build` -> tsc + vite PASS；仍有既有 chunk size warning。
