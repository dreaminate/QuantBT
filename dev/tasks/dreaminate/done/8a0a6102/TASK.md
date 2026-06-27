---
uuid: 8a0a6102c8c54022a93f955458dbc98c
title: Research Graph governed canvas mutation command
status: done
owner: dreaminate
assigned_by: dreaminate
review_status: 1
priority: P1
area: research-os-graph
source: goal-gap
source_ref: GOAL §2 writable canvas mutation engine gap
depends_on: [ef1f3f6126754b4eaba7ab69f47787e6, af5352077a974dd68adec1024cbb2eaf]
---

# Research Graph governed canvas mutation command

## Scope [必填]
新增第一条 Canvas 写回审计命令：`record_canvas_mutation`。它把前端/台面编辑意图记录为 Research Graph canonical command log 中的 `CanvasMutationRecord`，要求 `canonical_command_ref`、`audit_ref` 和 `value_ref` 或 `value_hash`；它不直接改 QRO projection index，不执行真正的资产更新，也不写 raw value。

## 接线点（file:line，实现时复核）[必填]
| 文件 | 改什么 |
|---|---|
| `app/backend/app/research_os/desk_projection.py` | 新增 `CanvasMutationRecord`，复用 `validate_canvas_mutation` 的 canonical/audit/desk-scope guard |
| `app/backend/app/research_os/spine.py` | `ResearchGraphStore` / `PersistentResearchGraphStore` 支持 `record_canvas_mutation` command 和 replay |
| `app/backend/app/main.py` | 新增 `POST /api/research-os/graph/canvas_mutations`，拒绝 raw value 字段，验证后写 Research Graph command |
| `app/backend/tests/test_research_graph_persistence.py` | 覆盖 mutation command 持久化 replay、API 成功、raw value 拒绝、缺 canonical/audit 与 strategy→Factor formula 拒绝 |

## 对抗测试设计（种已知 bug，门必抓）[必填]
1. `record_canvas_mutation` 必须能写入 JSONL 并 restart replay；不能只停留在内存。
2. mutation command 不能修改 QRO projection index，避免把 audit 记录伪装成真实资产更新。
3. API 必须拒绝 `value` / `raw_value` / `raw_payload` / `payload` 字段，只接受 `value_ref` 或 `value_hash`。
4. 缺 `canonical_command_ref` 或 `audit_ref` 必须 422，不写 partial command。
5. Strategy desk 写 Factor `formula.*` 必须 422，要求走 DeskHandoff。

## 验收一句话 [必填]
Research Graph 现在有第一条 governed Canvas mutation audit/write-back command；这仍不是完整 writable canvas engine、canonical asset updater、前端编辑 UI 或 strategy codegen。

## 完成记录（2026-06-27）
- 新增 `CanvasMutationRecord` 与 `record_canvas_mutation` command type。
- `PersistentResearchGraphStore` 可持久化并 replay canvas mutation commands；mutation audit 不进入 QRO projection index。
- 新增 `POST /api/research-os/graph/canvas_mutations`，只记录经过 validator 的 canonical/audit mutation，不接受 raw value。
- 已验证：
  - `cd app/backend && python -m pytest tests/test_research_graph_persistence.py -q` -> 6 passed / 2 warnings。
  - `python -m compileall -q app/backend/app/research_os/spine.py app/backend/app/research_os/desk_projection.py app/backend/app/research_os/__init__.py app/backend/app/main.py app/backend/tests/test_research_graph_persistence.py` -> success。
  - `cd app/backend && python -m pytest tests/test_research_graph_persistence.py tests/test_desk_projection.py tests/test_research_os_spine.py tests/test_governed_compiler.py tests/test_agent_runtime_research_graph.py tests/test_ds2_strategy_goal_persist.py tests/test_strategy_console_s2.py -q` -> 75 passed / 2 warnings。
  - `cd app/backend && python -m pytest -q` -> 1534 passed / 13 skipped / 283 warnings。
- 边界：这不是完整 writable canvas mutation engine、frontend edit wiring、canonical asset mutation executor、完整 graph database、full compiler implementation 或 strategy codegen。
