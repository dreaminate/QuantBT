---
uuid: d0e5d2088bb94b8c87e1178b8611b1d8
title: 监控→自动降级/退役/问责 尾部闭环接线（T-033 核验 gap 升级）
status: todo
owner: wait
assigned_by:
review_status: 0
priority: P2
area: monitor
source: research
source_ref: 2026-06-20 T-033 诚实残余核验（gap: monitor_loop）
depends_on: []
---

# 监控→自动降级/退役/问责 尾部闭环接线

## Scope [必填]
补「监控→自动降级/退役→问责」尾部闭环：当前构件齐全且各有单测，但无调度接线、漂移不驱动任何动作（T-033 核验坐实 gap，非假绿）。

## 上下文 / 动机 [按需]
T-033 核验：`compute_weekly_cost_drift`/`retire`/`LifecycleManager.evaluate` 零生产调用方；`cost_drift.py:127` 漂移>0.30 仅 append-note 后 return，不驱动 stop_rule/降级/退役；`Scheduler.tick` 生产无实例化。

## 接线点（file:line，实现时复核）[必填]
| 文件 | 位置 | 改什么(扩展不替换) |
|---|---|---|
| app/backend/app/dag/engine.py | 301-330 Scheduler.tick | 生产实例化 + weekly cron 真 tick |
| app/backend/app/monitor/cost_drift.py | 69/127-129 | 漂移>阈 → 发结构化告警事件 + 动作矩阵 |
| app/backend/app/hypothesis/store.py | 207 retire | 持续 N 周超阈自动调 retire + 落 PROV |
| app/backend/app/factor_factory/lifecycle.py | 147 evaluate | 挂周节点喂 IC 报告 |

## 对抗测试设计（种已知 bug，门必抓）[必填]
1. 种应退役卡（连续 2 周 WARNING / cost_drift 连续超阈）→ 闭环自动 status→retired + 落 PROV；故意断开调度接线 → 测试必红。
2. 漂移 >30% → 降级动作被调用（spy）而非仅 notes。

## 验收一句话 [必填]
漂移超阈 → 自动降级/退役被真正触发 + 问责落 PROV；断调度必红；不破基线。
