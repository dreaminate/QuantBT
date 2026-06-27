---
uuid: de764e1c65a242daa05848ad2ad0f56f
title: 监控生产调度 + 因子观测记录管道——让 monitor_tick 在生产真跑
status: done
owner: dreaminate
assigned_by: dreaminate
review_status: 1
priority: P2
area: monitor
source: goal-gap
source_ref: 2026-06-22 D-WAVE1A 残余② · M(d0e5d208) 闭环 done 后的生产编排
depends_on: [d0e5d2088bb94b8c87e1178b8611b1d8]
completed_at: 2026-06-27
---

# 监控生产调度 + 因子观测记录管道

## Scope [必填]
让 M 卡建的 `monitor.closure.monitor_tick` 闭环在**生产真跑**：① 生产实例化 `Scheduler(strict=True)` + weekly cron 节点；② 补**因子观测记录管道**（生产里 `FACTOR_LIFECYCLE.record_observation` 当前零调用方 → 权威无观测输入、tick 空转）；③ weekly job 从 `ExecutionAuditLog` 算 `compute_weekly_cost_drift` + 喂各活跃因子的 IC 观测 → `monitor_tick` 驱动 lifecycle 权威自动降级/退役。

## 上下文 / 动机 [按需]
D-WAVE1A 残余②：M 卡建了闭环机制（`monitor_tick`→lifecycle 权威 A1→单一 PROV）+ croniter 硬化，并对抗测试验证；但**生产无调用方**——关键诚实依赖是 `record_observation` 在生产零调用（grep 实证），故现在直接接 Scheduler 会 tick 空观测=paper-true 桩。本卡补观测管道 + 生产调度起点，使「监控驱动动作」在生产真生效。

## 接线点（file:line，实现时复核）[必填]
| 文件 | 位置 | 改什么(扩展不替换) |
|---|---|---|
| app/backend/app/main.py | 118 FACTOR_LIFECYCLE / 395 startup | 生产 Scheduler(strict=True) + weekly monitor op |
| app/backend/app/monitor/closure.py | monitor_tick | 复用（已建） |
| app/backend/app/factor_factory/lifecycle.py | record_observation | 生产观测记录管道（周期 IC → 喂权威） |
| app/backend/app/monitor/cost_drift.py | compute_weekly_cost_drift | 从 ExecutionAuditLog 真算 → 喂 monitor_tick |

## 对抗测试设计（种已知 bug，门必抓）[必填]
1. weekly job 真跑：种连续超阈漂移 + 衰减观测 → 活跃因子自动 retired + 落 PROV（端到端，非单测 closure）。
2. croniter 缺包 → 生产 Scheduler(strict=True) 启动响亮失败（复用 M 卡硬化）；断 job 接线 → 端到端测试红。

## 验收一句话 [必填]
生产 weekly 监控真驱动自动降级/退役 + 问责落 PROV；缺 croniter 启动响亮失败；不破基线。

## 完成记录（2026-06-24 · deliver-final）
- commit `b871c92`：`monitor/production.py`——生产 `Scheduler(strict=True)` + weekly DAG（`"0 9 * * 1"`）；观测管道 ExecutionAuditLog→`compute_weekly_cost_drift`→`monitor_tick`→lifecycle 权威自动降级/退役落单一 PROV；`croniter>=2.0` 登记真依赖（缺则启动响亮失败）。**范畴红线钉死**：`monitor_tick` 绝不接 gate verdict/pbo/dsr/overfit。
- 对抗测试 +10 + 双轴变异自检；`test_monitor_closure` 15 passed；全量后端 1357 passed / 0 failed。
- 诚实残余（建议 mint 新卡，未过度造）：① 生产周度 per-factor IC 重算源未建（`observation=None`，退役暂由 cost-drift 驱动）② §5 漂移检测器 PSR/CUSUM/PSI 真未写（诚实标残余，未投机造桩）③ 观测内存级跨进程重启不持久。
## 完成记录（2026-06-27）

- 新增 `app/backend/app/monitor/production.py`：`monitor.weekly_tick` DAG op、`build_weekly_monitor_scheduler(strict=True)`、`run_weekly_monitor_tick()`、active factor 筛选、`ExecutionAuditLog`→`compute_weekly_cost_drift`→`monitor_tick` 桥接。
- `main.py` 新增全局 `EXECUTION_AUDIT_LOG`，copy-trade `LeasedBinanceVenue` factory 复用同一个 audit log；startup 配置 monitor runtime 并实例化 weekly `Scheduler(strict=True)`，缺 `croniter` 仍会响亮失败。
- 新增 `POST /api/monitor/weekly_tick` 手动触发同一条 production weekly tick：从全局 `ExecutionAuditLog` 算本周成本漂移，可接收 active factor IC observations；观测 payload 拒绝 `pbo` / `dsr` / `gate_verdict` / overfit 字段，避免把晋级 gate verdict 接成 live monitor。
- 对抗验证：WARNING 因子在连续两次超阈成本漂移后自动 `RETIRED` 并只落一条 lifecycle PROV；factor IC observation 会进入 `LifecycleManager.history`；DAG op 使用已配置 runtime；strict scheduler 可构造；gate verdict 字段 422 且不写 history。
- 本地验证：
  - `python -m pytest app/backend/tests/test_monitor_closure.py app/backend/tests/test_cost_drift.py app/backend/tests/test_monitor_production.py app/backend/tests/test_alpha_lite_and_lifecycle.py -q` → 21 passed / 2 warnings。
  - `python -m pytest app/backend/tests/test_monitor_production.py app/backend/tests/test_monitor_closure.py app/backend/tests/test_cost_drift.py app/backend/tests/test_factor_desk_f2.py app/backend/tests/test_factor_lab_endpoints.py app/backend/tests/test_copy_trade_gate.py app/backend/tests/test_realmoney_audit_killswitch.py -q` → 94 passed / 2 warnings。
  - `python -m compileall -q app/backend/app/monitor/production.py app/backend/app/monitor/__init__.py app/backend/app/main.py app/backend/tests/test_monitor_production.py` → PASS。
- 边界：这证明本地 production wiring 和 weekly DAG/op/endpoint 可驱动生命周期动作；不等于外部部署进程已经长期运行，也不等于交易所真实 fill 已在生产环境持续进入该 audit log。
