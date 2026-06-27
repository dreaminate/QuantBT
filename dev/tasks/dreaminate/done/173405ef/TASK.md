---
uuid: 173405ef47f942ba9929a4c356483d07
title: GOAL entrypoint spine coverage registry and API
status: done
owner: dreaminate
assigned_by: dreaminate
review_status: 0
priority: P1
area: research-os-goal-entrypoint-coverage
source: goal-gap
source_ref: GOAL §0 north star; GOAL §1 unified object model; GOAL §7 Agent Shell; GOAL §8 governance spine
depends_on: []
completed_at: 2026-06-27
---

# GOAL entrypoint spine coverage registry and API

## Scope [必填]
新增 entrypoint coverage record、append-only JSONL registry 和 API summary，用 refs-only 方式记录 Chat / Canvas / API / IDE / Scheduler / Agent Shell 是否已走 QRO -> Research Graph -> Governed Compiler -> Evidence/Validation；并让 `compile_qro` 和 direct compiler pass 成功路径自动写 coverage record。

## 上下文 / 动机 [按需]
`GoalSectionCoverageRecord` 已能阻止把 §0-§17 contract coverage 误报成 full product implementation，但没有持久化账本证明每个入口已经接到 QRO -> Graph -> Compiler -> Evidence。GOAL §0/§1/§7/§8 的当前硬 gap 是“全入口单一路径”，本卡先补可验证覆盖账本和 no-write gate，不声称所有入口 producer 已完成改造。

## 接线点（file:line，实现时复核）[必填]
| 文件 | 改什么 |
|---|---|
| `app/backend/app/research_os/goal_coverage.py` | 新增 `GoalEntrypointCoverageRecord`、validator、manifest validator、JSONL registry 和 dict parser |
| `app/backend/app/research_os/__init__.py` | 导出 entrypoint coverage record/registry/validator |
| `app/backend/app/main.py` | 新增 `GOAL_ENTRYPOINT_COVERAGE_REGISTRY`、`POST /api/research-os/goal/entrypoint_coverage_records`、summary endpoint；`compile_qro` 和 `/compiler/passes` 成功后自动写 coverage |
| `app/backend/tests/test_goal_coverage.py` / `app/backend/tests/test_governed_compiler.py` | 覆盖缺 QRO/Graph/Compiler/Evidence/permission/replay refs、unknown source、silent mock、raw payload、registry replay/no-write、API actor override、`compile_qro` 与 direct compiler pass coverage producer |
| `dev/state/dreaminate/state.md` / `dev/research/TRACE.md` / `dev/log/dreaminate/log.md` | 落档 §0/§1/§7/§8 推进和剩余边界 |

## 对抗测试设计（种已知 bug，门必抓）[必填]
1. entrypoint coverage 缺 QRO、Research Graph command、Compiler IR/pass、evidence、validation、permission 或 replay refs 必须拒绝。
2. unknown EntrySource 或 unknown GOAL section 必须拒绝。
3. `silent_mock_fallback_used=true` 必须拒绝。
4. `raw_payload_persisted=true` 必须拒绝，coverage 只能记录 refs/hash。
5. all-entrypoints-wired claim 缺 Chat / Canvas / API / IDE / Scheduler / Agent Shell 任一入口必须拒绝。
6. API 写入必须用当前 user 覆盖 payload 里的 `recorded_by`，避免客户端伪造 actor。
7. `compile_qro` 成功路径必须写 entrypoint coverage；unknown QRO 或缺 evidence 时不得写 coverage。
8. `/api/research-os/compiler/passes` 成功路径必须写 entrypoint coverage；silent mock IR 的 coverage 失败时不得写 compiler pass 或 coverage。

## 红线 [按需]
- 不声称所有入口 producer 已全部改造。
- 不把 coverage registry 说成 runtime execution proof、compiler 完整实现、CI 或线上验证。
- 不允许 raw user/tool payload 或 silent mock fallback 进入 coverage 证明。

## 非目标 [按需]
不实现所有入口自动 producer 接线、不实现完整 compiler pass、strategy code generator、完整 graph database、前端 coverage 管理 UI、CI/线上验证或用户验收。

## 验收一句话 [必填]
入口覆盖现在可以作为 append-only refs record 写入/replay；缺 QRO/Graph/Compiler/Evidence/permission/replay/validation refs、unknown source、silent mock 或 raw payload 时 fail-closed。

## 完成记录
- 新增 `GoalEntrypointCoverageRecord`，覆盖 `entry_source`、`entrypoint_ref`、GOAL sections、QRO refs、Research Graph command refs、Compiler IR/pass refs、evidence/validation refs、permission refs、replay refs 和可选 canonical/lifecycle/RDP refs。
- 新增 `validate_goal_entrypoint_coverage()` 与 `validate_goal_entrypoint_coverage_manifest()`；all-entrypoints-wired claim 必须覆盖 Chat / Canvas / API / IDE / Scheduler / Agent Shell。
- 新增 `PersistentGoalEntrypointCoverageRegistry`，以 JSONL append-only 记录 `goal_entrypoint_coverage_recorded` event，可 replay；无效记录不写文件。
- 新增 `/api/research-os/goal/entrypoint_coverage_records` 和 `/api/research-os/goal/entrypoint_coverage/summary`；API 以当前 user 覆盖 `recorded_by`，summary 返回 present/missing entry sources。
- `POST /api/research-os/compiler/compile_qro` 成功记录 Compiler IR/pass 后，会自动写 `GoalEntrypointCoverageRecord` 并返回 `entrypoint_coverage_ref`；unknown QRO、缺 evidence 和 silent mock coverage 失败路径不写 compiler/coverage partial record。
- `POST /api/research-os/compiler/passes` 成功记录 CompilerPass 后，会基于已记录 IR + pass 自动写 `GoalEntrypointCoverageRecord` 并返回 `entrypoint_coverage_ref`；silent mock IR 的 coverage 失败路径不写 pass/coverage partial record。
- 验证：`pytest app/backend/tests/test_goal_coverage.py -q` -> **13 passed / 2 warnings**；goal/compiler scoped -> **31 passed / 2 warnings**；goal/compiler/spine/methodology/trust adjacent -> **70 passed / 2 warnings**；`python -m compileall -q app/backend/app` -> PASS。
