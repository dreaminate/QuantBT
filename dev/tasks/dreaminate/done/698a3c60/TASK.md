---
uuid: 698a3c60c1af4ea8bc0b038acedcd91b
title: 监控调度 driver 接线——补缺失的生产 tick loop，让 weekly cron 真 fire（修复端到端假绿灯）
status: done
owner: dreaminate
assigned_by: dreaminate
review_status: 1
priority: P1
area: monitor
source: audit-finding
source_ref: 方法学消费侧 correctness 审计（workflow wm8x329vn）#1 发现（lev 8）；done 卡 d0e5d208（监控尾部闭环）暴露的调度器活性缺口
depends_on: [d0e5d2088bb94b8c87e1178b8611b1d8]
---

# 监控调度 driver 接线——补缺失的生产 tick loop

## Scope [必填]
`main._start_production_monitor_scheduler()` 在 startup **注册** weekly 监控 DAG（cron `0 9 * * 1`）并 log「已启动」，
但 `Scheduler.tick()` 是**轮询式**（`scheduled_at<=now` 才 fire，dag/engine.py:302 docstring 明载「调用方在 loop 里
every N seconds 调 tick()」）——而生产**无任何 driver** 去 tick → cron 永不到点触发、退役闭环空转。本卡补那个缺失的
生产调用方：一个 daemon 线程周期 `PRODUCTION_SCHEDULER.tick()`，让注册的 weekly DAG 真 fire。

## 数学/活性先行（为何是真假绿灯·守不变量）[必填]
- **活性不变量**：注册的 cron job 必须有驱动器使其在 `scheduled_at ≤ now` 时 fire。engine.py 的 Scheduler 不是自驱定时器、
  是轮询器——`tick()` 不被周期调用 ⇒ `_jobs` 里的 `next_fire` 永不被检验 ⇒ cron 形同虚设。
- **假绿灯证据**：端到端测试 `test_scheduler_dag_wiring_fires_op_and_severing_does_not`（test_monitor_closure.py:187）
  靠**手动** `sched._jobs[name]=(def, datetime(2000,1,1))` 强制到期 + **手动** `sched.tick()` 证「tick 时 op 会跑」——
  完全绕过 cron 门 + 绕过「谁来 tick」。`main.startup_event` 只构造 scheduler + log「已启动」（误导运维以为周一 9 点自动退役），
  实则 scheduler 静止。这是教科书级端到端假绿灯（声称 vs 实际不符）。
- **范畴守恒（不动治理）**：weekly DAG op 是 `kind="pure"`（production.py:174，不触券商/资金、只改 registry 状态 + 落 PROV），
  故 driver 让它 fire **不涉动钱/不可逆**；M-AUTHORITY=A1 退役只接绩效/成本漂移轴（绝不接 gate verdict），本卡不碰该红线。

## 治理（护栏·correctness / 不替用户拍板）[必填]
- **不替用户拍「是否自动跑」松紧**：`QUANTBT_MONITOR_DRIVER`（默认开）env 可关——关则 scheduler 仍注册但不自动 tick，
  由运维外部 cron 调 `run_production_monitor_cycle`。`QUANTBT_MONITOR_TICK_SECONDS`（默认 60）周期可调。
- **修复的是 correctness（活性假绿灯）非新设门**：driver 激活的是系统**既已注册+已声称启动**的意图，不是新增治理闸。
- **诚实残余（不假绿灯·🟡 未验证≠✅ 已验证）**：driver 解的是「scheduler 静止」这一层。production.py:18-26 自陈的另两层
  仍是残余——① 生产无真实周期 per-factor IC 源（observation 恒 None）；② `_observations` 内存级不落盘跨重启清空。
  故即便 driver 接上，自动退役在真数据上仍受掣肘（成本漂移轴可动、绩效 IC 轴待数据源）。这两层另开卡（见 follow-on）。

## 接线点（file:line，实现复核）[必填]
| 文件 | 位置 | 改什么(扩展不替换) |
|---|---|---|
| app/backend/app/main.py | +`_monitor_driver_loop`/`_start_monitor_driver`/`stop_monitor_driver` + driver 全局 | 新增 |
| app/backend/app/main.py | startup_event +`_start_monitor_driver()`；新增 shutdown_event 调 `stop_monitor_driver` | additive |
| app/backend/tests/test_monitor_driver.py | 新建 4 对抗测试 | 新增 |

## 对抗测试设计（种已知 bug，门必抓）+ 变异 [必填]
1. **driver 真 tick**：起 driver(0.02s) + 强制到期 job → 有界等待内必 fire → MUT-1（`_monitor_driver_loop` 改 pass 不 tick）→ 超时红 ✓
2. **startup 真接 driver**：`startup_event()` 后 driver 线程必活 → MUT-2（startup 删 `_start_monitor_driver()`）→ 红 ✓
3. **env 关生效**：QUANTBT_MONITOR_DRIVER=0 → 不起 driver、返 None（不替用户拍松紧）。
4. **幂等**：多次 startup 复用同一线程（多 TestClient 不泄漏线程）。

## 验收一句话 [必填]
生产 startup 真起一个 daemon driver 周期 tick PRODUCTION_SCHEDULER，让注册的 weekly cron 真到点 fire（此前空转=假绿灯已修复）；
daemon+默认 60s 不误触发测试、env 可关不替拍、幂等防泄漏；MUT-1/2 双变异全抓；全量后端 1623 passed / 0 failed。

## 完成记录（2026-06-25 · autonomous-loop / D-MONITOR-DRIVER）
- **审计驱动选片**：只读 correctness 审计 workflow（wm8x329vn·7 域并行+对抗证伪·24 agent）排出 16 真缺口，#1（lev 8·不卡用户）
  即本卡——经对抗 verifier 确认「确无生产消费者」（startup 只注册+log，无后台 driver；tick 轮询无人调）。框架经原文+代码复核坐实
  （engine.py:302/328 + main.py:445-468 + production.py:174）。
- **实现（additive·daemon 线程）**：`_monitor_driver_loop`（`_MONITOR_DRIVER_STOP.wait(interval)` 周期 tick·异常吞续跑·读全局
  scheduler 句柄）+ `_start_monitor_driver`（幂等·env QUANTBT_MONITOR_DRIVER 可关·QUANTBT_MONITOR_TICK_SECONDS 周期）+
  `stop_monitor_driver`（shutdown/测试隔离）；startup_event 接 driver、新增 shutdown_event 停。daemon+默认 60s ⇒ 秒级测试永不误触发 weekly op。
- **对抗 + 变异**：`test_monitor_driver` 4 测试。MUT-1（driver 不 tick）→ 真-tick 测试超时红；MUT-2（startup 不接 driver）→ 接线测试红；
  双变异定点反向 edit 验证后还原（**绝不 git checkout 带未提交改动**）。
- **验证**：driver+closure 19 passed；**全量后端 1623 passed / 13 skipped / 0 failed / 180s**（基线 1619，净 +4）。driver 不破任何既有测试、无挂。
- **诚实残余 → follow-on 卡 554cdcf2**：监控闭环另两层（生产 per-factor IC 真源 + 观测落盘跨重启）+ 审计 #3（4 个绩效 drift 检测器
  rolling-PSR/CUSUM/PH 未接 run_weekly_monitor_pass→monitor_tick 的 perf_drift）——这些是绩效轴真正能在真数据上退役的前置，留池。
- **本轮 loop「commit 和 push 自动进行」→ 本地 commit + push 分支**（land main 仍仅用户·分支续 land-ready）。
