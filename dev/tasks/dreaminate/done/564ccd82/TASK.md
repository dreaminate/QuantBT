---
uuid: 564ccd82acd740f68f8660a239e5d2df
title: Scheduler GOAL entrypoint coverage producer
status: done
owner: dreaminate
assigned_by: dreaminate
review_status: 1
priority: P0
area: goal-entrypoint-coverage
source: goal
source_ref: GOAL §7/§8 scheduler and scheduled_agent wiring; finding goal-0-17-gap-matrix-2026-06-28
depends_on: [2b1706f19b714040b93e37b23f82dcf8]
created_at: 2026-06-28
---

# Scheduler GOAL entrypoint coverage producer

## Scope [必填]
把 weekly tick / scheduled producer 成功路径接到 `entry_source=scheduler` GOAL coverage；不引入部署级长期后台进程。

## 接线点（file:line，实现时复核）[必填]
| 文件 | 改什么 |
|---|---|
| `app/backend/app/monitor/production.py`、`app/backend/app/main.py` | weekly tick / scheduler result recorder 写 coverage |
| `app/backend/tests/test_monitor_production.py`、`test_goal_coverage.py` | 覆盖 scheduler coverage 和幂等 |

## 对抗测试设计（种已知 bug，门必抓）[必填]
1. scheduler tick 无 compiler pass refs → 不写 coverage。
2. 重复 tick 不重复污染 coverage。
3. failed tick 或 silent mock tick 不写成功 coverage。

## 验收一句话 [必填]
scheduler 成功入口写 `entry_source=scheduler` coverage；失败、mock、缺 refs 时不写 partial。

## 完成证据
- 已有 `_record_weekly_monitor_qro()` 在 weekly tick 成功路径写 `QROType.OBSERVABLE`，`ResearchGraphCommand(source=EntrySource.SCHEDULER)` 和 hash-only monitor result refs。
- 已有 `_compile_weekly_monitor_qro()` 把 scheduler QRO 编译为 Governed Compiler IR/pass，并通过 `_goal_entrypoint_coverage_from_compiler_records()` 写 `entry_source=scheduler`、`entrypoint_ref=scheduler:monitor.weekly_tick` 的 GOAL entrypoint coverage。
- `/api/monitor/weekly_tick` 手动触发路径和 `build_weekly_monitor_dag(... result_recorder=_record_weekly_monitor_qro_from_scheduler)` scheduled path 复用同一记录/编译路径；scheduled path 的 compiler pass `actor_source=scheduled_agent`。
- 失败/坏输入路径在记录 QRO/Compiler/Coverage 前拒绝；monitor QRO/IR/pass/coverage 只保存 refs/hash/count/status，不保存 raw factor payload、action payload、cost drift report 或 secret。

## 验证
- `python -m compileall -q app/backend/app/monitor app/backend/app/main.py`
- `python -m pytest app/backend/tests/test_monitor_production.py app/backend/tests/test_goal_coverage.py -q` → **24 passed / 2 warnings**
- `python -m pytest app/backend/tests -q` → **1910 passed / 13 skipped / 283 warnings**

## 边界
- 这是 weekly tick / scheduled producer 的 `entry_source=scheduler` coverage 核验落档，不新增部署级长期后台进程。
- 不是 canvas、IDE、chat/agent_shell producer，也不是 §0-§17 full product implementation proof。
- 未声明 CI、线上、真实 scheduler daemon 长期运行或用户验收。
