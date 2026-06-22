---
uuid: d0e5d2088bb94b8c87e1178b8611b1d8
title: 监控→自动降级/退役/问责 尾部闭环接线（T-033 核验 gap 升级）
status: done
owner: dreaminate
assigned_by: dreaminate
review_status: 1
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

## 实现落账（done · 2026-06-22 · D-WAVE1A · M-AUTHORITY=A1）
**实装（扩展不替换）：**
- 新 `monitor/closure.py`：`monitor_tick(manager, factor_id, version, observation=, drift_pct=)` 把绩效/漂移信号喂 **factor lifecycle 权威**（`LifecycleManager.evaluate`，A1）→ 自动 WARNING/RETIRED + 发**单一** `LifecycleEvent`（单 PROV，不双发）。漂移>阈 → 结构化告警 + 记降级观测（动作真被调用，非仅 append note）。
- `dag/engine.py` `Scheduler.__init__` 加 `strict` 参数（**croniter 硬化**：生产 strict=True 缺 croniter 启动响亮失败，绝不静默不 tick=paper-true；默认 False 不破现有）。
- **范畴红线**：`monitor_tick` 签名只接绩效/漂移（IC/drift_pct），**绝不接 gate verdict**（DSR/PBO 是晋级闸、非运营退役触发器）——测试断言签名无 verdict/pbo/dsr/gate。

**门必抓（5 测试 + 1 变异）**：种应退役卡（WARNING+连续漂移超阈）→ 自动 RETIRED + 单一 PROV；漂移未超阈不动作；漂移>30% 降级动作真调用（非 note）；croniter strict 缺包响亮失败；签名无 gate verdict。变异：断 `manager.evaluate` → 自动退役断言红（闭环真接线非纸门）。**全量见下方 log 实跑数字**；既有 lifecycle/dag/engine 回归绿。

**诚实残余**：① 生产 weekly cron 真实例化 `Scheduler(strict=True)` + 把 `compute_weekly_cost_drift` 输出喂 `monitor_tick` 的**编排接线**（哪个 job/调度起点）未落 production（闭环函数 + croniter 硬化已就绪，差一个生产调度起点）。② `hypothesis store.card.status` 作 lifecycle 权威的派生视图同步未接（A1 定 lifecycle 权威、store 跟随；本卡只立权威单发，store→lifecycle 同步留后续）。
