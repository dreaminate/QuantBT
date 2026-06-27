---
uuid: 2b1706f19b714040b93e37b23f82dcf8
title: GOAL §0-§17 full section coverage manifest hard gate
status: done
owner: dreaminate
assigned_by: dreaminate
review_status: 1
priority: P0
area: goal-coverage
source: goal
source_ref: GOAL §0-§17 full implementation objective; finding goal-0-17-gap-matrix-2026-06-28
depends_on: []
created_at: 2026-06-28
completed_at: 2026-06-28
---

# GOAL §0-§17 full section coverage manifest hard gate

## Scope [必填]
新增真实 GOAL §0-§17 section coverage manifest materializer/API/test：只有每节都有真实 runtime/test/task/evidence refs 和 entrypoint_wiring_refs 时，`claims_full_product_implementation=True` 才能通过；不把 contract-only coverage 包装成完整实现。

## 上下文 / 动机 [按需]
当前 `validate_goal_coverage_manifest` 只有 pure validator 和 synthetic test；本地 `goal_entrypoint_coverage.jsonl` 只覆盖 API 的 §0/§1/§7/§8。目标要求全 §0-§17 都能被 runtime/API/UI/audit/tests 支撑。

## 接线点（file:line，实现时复核）[必填]
| 文件 | 改什么 |
|---|---|
| `app/backend/app/research_os/goal_coverage.py` | 新增 section manifest persistence/materializer，复用 validator |
| `app/backend/app/main.py` | 新增 summary/API 或扩展现有 goal coverage summary，显示 full_product_implementation false/true 和缺口 |
| `app/backend/tests/test_goal_coverage.py` | 覆盖 contract-only full claim 拒绝、缺任一 § 拒绝、真实 refs 完整时通过 |
| `dev/research/findings/dreaminate/goal-0-17-gap-matrix-2026-06-28.md` | 保持矩阵与任务溯源 |

## 对抗测试设计（种已知 bug，门必抓）[必填]
1. 只传 contract/test/task/evidence refs，`claims_full_product_implementation=True` → 必须报 `goal_section_not_full_entrypoint_wired`。
2. 缺 §13 或缺任一 required ref → summary 显示缺口且不写 full claim。
3. entrypoint_wiring_refs 引用未知 coverage ref → fail-closed，不写 partial manifest。
4. `raw_payload_persisted` 或 silent mock coverage 被 section manifest 引用 → fail-closed。

## 非目标 [按需]
不一次性补完 chat/canvas/ide/scheduler/agent_shell producer；这些由依赖本卡的 entrypoint 卡实现。

## 验收一句话 [必填]
种 contract-only full implementation claim → 门必红；只有 §0-§17 每节都有真实 entrypoint_wiring_refs 时 full section manifest 才通过。

## 完成记录
- 新增 `PersistentGoalSectionCoverageRegistry` 与 `goal_section_coverage_record_from_dict()`，以 `goal_section_coverage_recorded` JSONL event 持久化 §0-§17 section coverage。
- section record 先跑 `validate_goal_section_coverage()`，再逐条回查 `entrypoint_wiring_refs` 是否存在于 `PersistentGoalEntrypointCoverageRegistry`，且对应 entrypoint record 必须覆盖同一 section。
- 新增 `/api/research-os/goal/section_coverage_records` 与 `/api/research-os/goal/section_coverage/summary`；summary 显示 required/present/missing sections、not-full-wired sections 和 `full_product_implementation`。

## 验证
- `python -m compileall -q app/backend/app`：**PASS**。
- `python -m pytest app/backend/tests/test_goal_coverage.py -q`：**17 passed / 2 warnings**。
- `python -m pytest app/backend/tests/test_goal_coverage.py app/backend/tests/test_platform_coverage.py app/backend/tests/test_governed_compiler.py app/backend/tests/test_research_os_spine.py -q`：**55 passed / 2 warnings**。
- `python -m pytest app/backend/tests -q`：**1907 passed / 13 skipped / 283 warnings**。

## 边界
这是 GOAL §0-§17 full section coverage manifest 的持久化硬门，不是 chat/canvas/IDE/scheduler/agent_shell coverage producer 本身；后续 active 卡继续补各入口真实写入。
