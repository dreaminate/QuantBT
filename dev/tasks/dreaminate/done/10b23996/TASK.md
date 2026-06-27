---
uuid: 10b2399615a8495c9e2c569919a92a25
title: Monitor weekly scheduler tick writes Observable QRO
status: done
owner: dreaminate
assigned_by: dreaminate
review_status: 1
priority: P1
area: research-os-scheduler-entrypoint
source: goal-gap
source_ref: GOAL §0/§7/§8/§10/§14/§16 Scheduler entrypoint writes QRO / Research Graph
depends_on: [9a6db34e0fe0f3d27e91d6a0cda27051]
completed_at: 2026-06-27
---

# Monitor weekly scheduler tick writes Observable QRO

## Scope [必填]
把 production weekly monitor tick 接入 Research Graph。`/api/monitor/weekly_tick` 成功后写 `Observable` QRO；真实 DAG scheduler op 通过 `configure_monitor_runtime(..., result_recorder=...)` 使用同一 recorder 写 QRO。

## 上下文 / 动机 [按需]
GOAL §0 明确 Chat / Canvas / API / IDE / Scheduler 都要能产生 QRO。此前 Agent/API/IDE/Canvas 已有多片接线，weekly monitor scheduler 仍只返回业务结果，不进 Research Graph。本卡先闭合真实 monitor scheduler seam，不声称所有 scheduler/API/execution 入口完成。

## 接线点（file:line，实现时复核）[必填]
| 文件 | 改什么 |
|---|---|
| `app/backend/app/monitor/production.py` | `MonitorRuntime` 增加可选 `result_recorder`；DAG op 成功后把 `WeeklyMonitorResult` 交给 recorder |
| `app/backend/app/main.py` | 新增 `_record_weekly_monitor_qro` / `_record_weekly_monitor_qro_from_scheduler`；startup monitor runtime 绑定 recorder；`/api/monitor/weekly_tick` 成功路径返回 QRO refs |
| `app/backend/tests/test_monitor_production.py` | 覆盖 endpoint 成功写 Scheduler QRO、拒绝 gate verdict 时不写 Graph、DAG op 成功写 Graph |

## 对抗测试设计（种已知 bug，门必抓）[必填]
1. endpoint 成功后必须产生 `Observable` QRO，`input_contract.entry_source=scheduler`，响应返回 `qro_id` / `research_graph_command_id`。
2. QRO/audit 不得复制 factor id、`cost_drift_report`、actions 或 factor observation payload，只保存 result hash 和计数。
3. `factor_observations` 带 DSR/PBO/gate verdict 被拒绝时不得写 Research Graph command。
4. DAG op 配置 recorder 后必须写 QRO，不能只让手动 HTTP 有 Graph。

## 红线 [按需]
- 不允许把 monitor result 整包塞进 QRO contract。
- 不允许把 weekly monitor QRO 说成 live broker 连通、生产部署证明或 alpha evidence。
- 不允许用 QRO 写入掩盖 monitor 输入校验失败。

## 非目标 [按需]
不实现所有 scheduler/API/execution 入口 QRO 化，不实现完整 graph database，不实现 runtime promotion gate，不实现 CI/线上 scheduler 证明，不实现真实 broker/live monitor 连通证明。

## 验收一句话 [必填]
weekly monitor endpoint 和 DAG scheduler op 成功 tick 后都会写 `Observable` QRO；Graph audit 只暴露 scheduler 路由元数据、result hash 和计数，不暴露 raw monitor payload。

## 完成记录（2026-06-27）
- `MonitorRuntime` 增加 `result_recorder` hook；`_weekly_monitor_op` 成功后追加 recorder 返回的 Graph refs。
- `main.py` 新增 weekly monitor QRO helper，写 `QROType.OBSERVABLE`，`EntrySource.SCHEDULER`，`ActorSource.SCHEDULED_AGENT` 或 `USER_MANUAL`，只保存 result hash / counts / scheduler refs。
- `/api/monitor/weekly_tick` 成功响应新增 `qro_id`、`research_graph_command_id`、`research_graph_result_hash`。
- QRO audit allowlist 增加安全 scheduler 元数据和 monitor summary 字段。
- 本地验证：
  - `python -m pytest app/backend/tests/test_monitor_production.py -q` -> 6 passed / 2 warnings。
  - `python -m pytest app/backend/tests/test_monitor_production.py app/backend/tests/test_monitor_closure.py app/backend/tests/test_research_graph_persistence.py app/backend/tests/test_agent_runtime_research_graph.py app/backend/tests/test_entrypoint_gate_coverage.py -q` -> 49 passed / 2 warnings。
  - `python -m pytest app/backend/tests/test_monitor_production.py app/backend/tests/test_monitor_closure.py app/backend/tests/test_research_graph_persistence.py app/backend/tests/test_agent_runtime_research_graph.py app/backend/tests/test_entrypoint_gate_coverage.py app/backend/tests/test_research_os_spine.py app/backend/tests/test_goal_coverage.py app/backend/tests/test_platform_coverage.py app/backend/tests/test_engineering_standards.py -q` -> 74 passed / 2 warnings。
  - `python -m compileall app/backend/app` -> PASS。
  - `python dev/scripts/validate_dev.py` -> 49 ✅ / 0 ❌ / 0 ⚠️；DAG 146 卡。
