---
uuid: 9112dbc69e394f76b90d9003b305649a
title: Canvas GOAL entrypoint coverage producer
status: done
owner: dreaminate
assigned_by: dreaminate
review_status: 1
priority: P0
area: goal-entrypoint-coverage
source: goal
source_ref: GOAL §2 canvas-native typed projection; finding goal-0-17-gap-matrix-2026-06-28
depends_on: [2b1706f19b714040b93e37b23f82dcf8]
created_at: 2026-06-28
---

# Canvas GOAL entrypoint coverage producer

## Scope [必填]
把 canvas mutation/layout/QRO-node edit 成功路径接到 `entry_source=canvas` GOAL coverage；不改变现有 GraphCanvas 行为语义。

## 接线点（file:line，实现时复核）[必填]
| 文件 | 改什么 |
|---|---|
| `app/backend/app/main.py` | canvas mutation/layout/QRO asset mutation endpoints 写 coverage |
| `app/backend/tests/test_research_graph_persistence.py`、desk/frontend tests | 覆盖 canvas coverage refs 和坏 payload 拒绝 |

## 对抗测试设计（种已知 bug，门必抓）[必填]
1. canvas mutation 成功但未生成 compiler refs → 不写 coverage。
2. raw canvas payload 进入 coverage record → fail-closed。
3. direct graph mutation bypass permission → fail-closed。

## 验收一句话 [必填]
Canvas 操作成功后有 `entry_source=canvas` QRO→Graph→Compiler→Evidence coverage；raw payload/silent mock 不落账。

## 完成证据
- 新增 `_record_canvas_goal_entrypoint_coverage()`，把 canvas 产生/更新的 QRO 编译为 Governed Compiler IR/pass，并写 `entry_source=canvas` 的 GOAL entrypoint coverage。
- 已接 `canvas_asset_mutations`、`canvas_layouts`、`canvas_parameter_values`、`patch_applications` 成功路径；响应返回 `compiler_ir_ref`、`compiler_pass_ref`、`entrypoint_coverage_ref`。
- `canvas_asset_mutations` 写 `entrypoint_ref=canvas:asset_mutation`；`canvas_layouts` 写 `entrypoint_ref=canvas:layout`；parameter/patch 路径分别写 `canvas:parameter_value`、`canvas:graph_patch_application`。
- 旧 audit-only `/api/research-os/graph/canvas_mutations` 仍只记 canonical mutation command，不额外伪造 QRO 或 coverage。
- coverage/IR/pass/QRO 只保存 refs/hash/count/status；raw canvas payload、layout raw projection、patch body、secret/token 不进入 coverage。

## 验证
- `python -m compileall -q app/backend/app/main.py app/backend/tests/test_research_graph_persistence.py`
- `python -m pytest app/backend/tests/test_research_graph_persistence.py app/backend/tests/test_goal_coverage.py -q` → **45 passed / 2 warnings**
- `python -m pytest app/backend/tests/test_research_graph_persistence.py app/backend/tests/test_research_os_spine.py app/backend/tests/test_strategy_console_s2.py -q` → **83 passed / 2 warnings**

## 边界
- 这是 canonical canvas QRO update / layout / parameter / patch producer，不是旧 audit-only mutation 的 QRO 伪造。
- 不改变 GraphCanvas 投影语义，不新增 raw payload persistence。
- 这仍只覆盖 GOAL `§0/§1/§7/§8` entrypoint wiring，不是 §0-§17 full product implementation proof、CI、线上或用户验收。
