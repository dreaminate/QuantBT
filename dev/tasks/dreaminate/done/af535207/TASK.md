---
uuid: af5352077a974dd68adec1024cbb2eaf
title: Research Graph read-only canvas projection API
status: done
owner: dreaminate
assigned_by: dreaminate
review_status: 1
priority: P1
area: research-os-graph
source: goal-gap
source_ref: GOAL §2 canvas projection engine gap
depends_on: [7ba4a8b9cdce4d57b95d78406a57f129, 4e7a2c10605f4c5da7121d78f87e40bb]
---

# Research Graph read-only canvas projection API

## Scope [必填]
新增只读 Research Graph→GraphCanvas projection API。它从 QRO projection index 派生 GraphCanvas 兼容的 `nodes` / `edges`，每条 QRO command 投影为 command node → QRO node 的 locked read-only 视图。该 API 不持独立业务状态，不做 canvas mutation，不返回 raw input/output contract 值。

## 接线点（file:line，实现时复核）[必填]
| 文件 | 改什么 |
|---|---|
| `app/backend/app/main.py` | 新增 `/api/research-os/graph/canvas_projection`、QRO type→canvas category/status 映射、GraphCanvas nodes/edges 派生 |
| `app/backend/tests/test_research_graph_persistence.py` | 覆盖 canvas projection shape、locked read-only、edge port wiring、filter 和 raw contract 不泄露 |

## 对抗测试设计（种已知 bug，门必抓）[必填]
1. Canvas projection 必须从 QRO projection index 过滤结果派生，不能返回未命中 filter 的 QRO。
2. 返回节点必须 `locked=true`，避免把 read model 伪装成可直接写的 canvas mutation engine。
3. command node out port 与 QRO node in port 必须由 edge 正确连接。
4. response 不得包含 raw prompt、strategy ref 或 output contract 原值。

## 验收一句话 [必填]
Research Graph 现在能输出第一版只读 GraphCanvas view model；这仍不是 canvas mutation engine、前端接线或完整 graph database。

## 完成记录（2026-06-27）
- 新增 `GET /api/research-os/graph/canvas_projection`，复用 projection index 的过滤参数。
- 每条 QRO projection 派生两个 locked 节点：Research Graph command node 与 QRO node；边为 command→QRO。
- QRO type 映射到现有 GraphCanvas `NodeCat`，status axes 映射到 `NodeState`。
- 已验证：
  - `cd app/backend && python -m pytest tests/test_research_graph_persistence.py -q` -> 3 passed / 2 warnings。
  - `python -m compileall -q app/backend/app/main.py app/backend/tests/test_research_graph_persistence.py` -> success.
  - `cd app/backend && python -m pytest tests/test_research_graph_persistence.py tests/test_desk_projection.py tests/test_research_os_spine.py tests/test_governed_compiler.py tests/test_agent_runtime_research_graph.py tests/test_ds2_strategy_goal_persist.py tests/test_strategy_console_s2.py -q` -> 72 passed / 2 warnings。
  - `cd app/backend && python -m pytest -q` -> 1531 passed / 13 skipped / 283 warnings。
- 边界：这不是 canvas mutation engine、前端 GraphCanvas 数据接线、完整 graph database 或 production graph query service。
