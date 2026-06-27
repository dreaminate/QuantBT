---
uuid: d6bbdb2e3d0a49389008d0c48aa31f2e
title: Weekly monitor scheduler compiles Observable QRO into entrypoint coverage
status: done
owner: dreaminate
assigned_by: dreaminate
review_status: 1
priority: P1
area: research-os-scheduler-entrypoint
source: goal-gap
source_ref: GOAL §0/§1/§7/§8 Scheduler entrypoint QRO -> Graph -> Compiler -> Evidence coverage
depends_on: [10b2399615a8495c9e2c569919a92a25, 173405ef47f942ba9929a4c356483d07, 9d175460a9f24650964a250304c44d83]
completed_at: 2026-06-27
---

# Weekly monitor scheduler compiles Observable QRO into entrypoint coverage

## Scope [必填]
把已接入 Research Graph 的 production weekly monitor tick 继续接到 Governed Compiler 和 GOAL entrypoint coverage。`/api/monitor/weekly_tick` 与 DAG scheduler op 成功写 `Observable` QRO 后，必须同步生成 compiler IR/pass，并记录 `entry_source=scheduler` 的 coverage refs。

## 上下文 / 动机 [按需]
`10b23996` 已证明 weekly monitor scheduler tick 会写 Observable QRO，但 GOAL §0/§1/§7/§8 的入口链要求是 QRO -> Research Graph -> Governed Compiler -> Evidence/Validation。此前 weekly monitor 只到 QRO/Graph，仍需自动产出 compiler refs 和 entrypoint coverage，不能只依赖人工调用 `/api/research-os/compiler/compile_qro`。

## 接线点（file:line，实现时复核）[必填]
| 文件 | 改什么 |
|---|---|
| `app/backend/app/main.py` | `_record_weekly_monitor_qro` 写 Graph 后调用 `_compile_weekly_monitor_qro`；生成 deterministic run plan/env/validation refs；写 `COMPILER_IR_STORE` 和 `GOAL_ENTRYPOINT_COVERAGE_REGISTRY` |
| `app/backend/tests/test_monitor_production.py` | 隔离 compiler/coverage store；覆盖 endpoint 和 DAG path 自动生成 `compiler_ir_ref` / `compiler_pass_ref` / `entrypoint_coverage_ref`；拒绝 bad observation 时不写 partial |
| `dev/state/dreaminate/state.md` / `dev/research/TRACE.md` / `dev/log/dreaminate/log.md` | 落档 scheduler compiler coverage 和剩余边界 |

## 对抗测试设计（种已知 bug，门必抓）[必填]
1. weekly monitor endpoint 成功响应必须返回 `compiler_ir_ref`、`compiler_pass_ref`、`entrypoint_coverage_ref`。
2. compiler IR/pass/coverage 必须绑定同一个 QRO 和 Research Graph command；manual endpoint 的 actor_source 是 `user_manual`，DAG path 是 `scheduled_agent`。
3. compiler refs 和 coverage 不得复制 factor id、`cost_drift_report`、actions 或 raw monitor payload。
4. `factor_observations` 带 DSR/PBO/gate verdict 被拒绝时不得写 Research Graph、compiler IR 或 entrypoint coverage partial record。
5. DAG scheduler op 成功 tick 后必须写 compiler/coverage，不能只有 HTTP endpoint 接线。

## 红线 [按需]
- 不允许把 compiler coverage 说成完整 scheduler/CI/线上运行证明。
- 不允许把 monitor result 整包塞进 QRO、compiler IR、compiler pass 或 coverage。
- 不允许把 weekly monitor compiler pass 说成完整策略代码生成器。

## 非目标 [按需]
不实现所有 scheduler、CI、线上 cron 证明、完整 compiler pass implementation、strategy codegen、live broker connectivity 或真实 deployment monitor。

## 验收一句话 [必填]
weekly monitor endpoint 和 DAG scheduler op 的成功 tick 现在都会从 Observable QRO 自动生成 governed compiler IR/pass 和 scheduler entrypoint coverage；非法 monitor observation 仍在 Graph/Compiler/Coverage 写入前失败。

## 完成记录（2026-06-27）
- `_record_weekly_monitor_qro` 写入 Research Graph 后调用 `_compile_weekly_monitor_qro`，返回 `compiler_ir_ref`、`compiler_pass_ref`、`entrypoint_coverage_ref`。
- `_compile_weekly_monitor_qro` 复用既有 `_compile_qro_payload` 和 coverage validator，绑定 scheduler DAG/op、result hash、permission、validation、environment lock 和 replay refs。
- monitor tests 对 endpoint 与 DAG path 均 patch 独立 compiler/coverage store，避免污染真实 `DATA_ROOT/audit`。
- 本地验证：
  - `pytest app/backend/tests/test_monitor_production.py -q` -> 7 passed / 2 warnings。
