---
uuid: 7ba4a8b9cdce4d57b95d78406a57f129
title: Research Graph QRO projection index API
status: done
owner: dreaminate
assigned_by: dreaminate
review_status: 1
priority: P1
area: research-os-graph
source: goal-gap
source_ref: GOAL §1/§2/§7/§8/§14/§16 projection index gap
depends_on: [5bb5d9da2f75469580ebbc74edf456fd, 1668fc7c3c2a4471a743107fd44e024d, 62fdfebdbd764c8f84ce527fed458e71]
---

# Research Graph QRO projection index API

## Scope [必填]
给 Research Graph 增加 QRO projection index read model。它必须从 `upsert_qro` command 派生，随 persistent command log replay 自动重建；查询面按 QRO type、owner、market、universe、status axes 和 lineage token 过滤。它不是第二套真相源，不存 raw input/output contracts，只暴露 contract keys、contract hashes、状态轴、lineage 和 refs。

## 接线点（file:line，实现时复核）[必填]
| 文件 | 改什么 |
|---|---|
| `app/backend/app/research_os/spine.py` | 新增 `ResearchGraphProjectionRecord`、`ResearchGraphStore.projection_index()`，在 `upsert_qro` apply/replay 时派生索引 |
| `app/backend/app/main.py` | 新增 `GET /api/research-os/graph/projection_index` 只读 API |
| `app/backend/tests/test_research_graph_persistence.py` | 覆盖 replay 后 projection index 恢复、过滤和 raw contract 不泄露 |
| `app/backend/app/research_os/__init__.py` | 导出 projection record 类型 |

## 对抗测试设计（种已知 bug，门必抓）[必填]
1. Persistent command log reload 后，projection index 必须仍能按 `qro_type` / evidence status 找到 QRO。
2. API 按 `qro_type` + evidence/runtime status 过滤时，不得混入其他 QRO 类型或状态。
3. Projection response 不得包含 raw prompt、strategy ref、tool payload 或 contract 原值；只允许 keys/hash/refs/status。
4. 既有 command audit、Agent Shell QRO refs、Compiler IR store 不能被 projection index 改坏。

## 验收一句话 [必填]
Research Graph 现在有第一版可过滤 QRO projection index read model；这仍不是完整 graph database / canvas projection engine / full compiler implementation。

## 完成记录（2026-06-27）
- 新增 `ResearchGraphProjectionRecord`，从 `ResearchGraphCommand(command_type="upsert_qro")` + `QRORecord` 派生。
- `ResearchGraphStore.apply()` 写 QRO 时同步维护 projection index；`PersistentResearchGraphStore` replay command log 时自动重建该索引。
- 新增 `GET /api/research-os/graph/projection_index`，支持 `qro_type`、`owner`、`market`、`universe`、definition/evidence/runtime status、`lineage_token` 和 `limit`。
- API 只返回 QRO identity/status/refs/contract keys/hash，不返回 raw contract 值。
- 已验证：
  - `cd app/backend && python -m pytest tests/test_research_graph_persistence.py tests/test_research_os_spine.py tests/test_agent_runtime_research_graph.py tests/test_governed_compiler.py -q` -> 27 passed / 2 warnings。
  - `python -m compileall -q app/backend/app/research_os/spine.py app/backend/app/main.py app/backend/app/research_os/__init__.py` -> success.
  - `cd app/backend && python -m pytest tests/test_research_graph_persistence.py tests/test_research_os_spine.py tests/test_agent_runtime_research_graph.py tests/test_governed_compiler.py tests/test_ds2_strategy_goal_persist.py tests/test_strategy_console_s2.py -q` -> 63 passed / 2 warnings。
  - `cd app/backend && python -m pytest -q` -> 1528 passed / 13 skipped / 283 warnings。
- 边界：这不是完整 graph database、canvas mutation/projection engine、全入口 compiler wiring、完整 compiler pass implementation 或 production graph query service。
