---
uuid: 554cdcf251804a19bfb81dbbebbdf5f1
title: 监控绩效轴真闭环——4 个 drift 检测器接 run_weekly_monitor_pass + per-factor IC 真源 + 观测落盘（审计残余）
status: todo
owner: wait
assigned_by:
review_status: 0
priority: P2
area: monitor
source: audit-finding
source_ref: 方法学消费侧 correctness 审计（workflow wm8x329vn）#3 发现（lev 7）+ production.py:18-26 诚实残余；done 卡 698a3c60（driver 接线）的下游前置
depends_on: [698a3c60c1af4ea8bc0b038acedcd91b]
---

# 监控绩效轴真闭环——drift 检测器接生产 + IC 真源 + 观测落盘

## Scope [必填]
done 卡 698a3c60 补了 driver（scheduler 真 tick、weekly op 真跑），但绩效轴**在真数据上仍无法退役**——三层残余：
① **4 个统计 drift 检测器零生产调用方**（审计 #3）：`rolling_psr_drift`/`cusum_drift`/`page_hinkley_drift`/
   `population_stability_index`（monitor/drift.py）在生产从未被求值；`monitor_tick` 已接 `perf_drift` 形参
   （closure.py:70/95-111 production-ready），但唯一生产入口 `run_weekly_monitor_pass`（production.py:88-94）调 monitor_tick
   时**只传 drift_pct（成本轴），从不传 perf_drift（绩效轴）** → 绩效轴主告警三件套在生产从未跑。
② **生产无真实周期 per-factor IC 源**（production.py:18-22）：`Factor.ic_summary` 仅注册期写一次，无人按周重算
   → `observation` 恒 None；须建周度 IC 重算管道（`ic_provider` 钩子已留）。
③ **观测不落盘跨重启清空**（production.py:25-26）：`LifecycleManager._observations` 内存级 → WARNING→RETIRED 需连续
   2 周负观测，进程重启则历史清空、退役不触发；须持久化。

## 治理（命门·范畴红线）[必填]
- **M-AUTHORITY=A1 范畴守恒**：drift 检测器喂 `monitor_tick` 的只能是**绩效/成本漂移轴**（IC/PSR/CUSUM/PH/drift_pct），
  **绝不**传 gate verdict/PBO/DSR/overfit（晋级期过拟合闸接成运营退役触发器=范畴错误，违 GOAL §5 + closure.py:14-16）。
- **rolling-PSR 不变量**：breach ⇔ PSR(SR*;n,γ3,γ4) < psr_floor，sr_benchmark 固定、**绝不暴露 n_trials**（否则退化为
  DSR=晋级闸，违「绝不把 DSR 搬实盘单策略」）。CUSUM/PH：μ0/σ0 取晋级期 OOS 冻结基准、仅看下降侧、绝不用监控窗自身均值（温水煮青蛙不变量）。
- **方法学松紧=用户**：psr_floor/CUSUM h/PH δ,λ 等阈值是用户方法学决策——摆代价 + 默认值，不替拍。
- **不假绿灯**：无真 IC 源时 observation=None，绝不把注册期陈旧 IC 伪装成「本周观测」。

## 对抗测试设计（种已知 bug，门必抓）[必填]
1. 断接线：run_weekly_monitor_pass 不传 perf_drift → 绩效退役不触发（证 perf 轴接线真生效，非套套逻辑）。
2. 范畴红线：监控路径绝不能把任何 gate/pbo/dsr 字段喂进 monitor_tick（机器钉死断言）。
3. rolling-PSR 不暴露 n_trials（种「传 n_trials→退化 DSR」→ 红）。
4. 观测落盘：写 2 周负观测 → 模拟重启（重载 manager）→ 第 2 周仍触发 RETIRED（证持久化真生效）。

## 验收一句话 [必填]
绩效轴 drift 检测器（rolling-PSR/CUSUM/PH）真接 run_weekly_monitor_pass→monitor_tick 的 perf_drift + per-factor IC 真源 + 观测落盘，
使监控在真数据上能真退役（范畴红线守 A1、阈值=用户方法学、不假绿灯），不破基线。
