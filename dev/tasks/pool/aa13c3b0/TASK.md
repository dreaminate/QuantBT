---
uuid: aa13c3b08fec47d1a827b40ddb61f238
title: 因子机构级度量接 lifecycle 状态机/sizing 生产路径
status: todo
owner: wait
assigned_by:
review_status: 0
priority: P2
area: factor-lifecycle
source: goal-gap
source_ref: 卡 b12de4f5（§3 度量库）完成后的消费侧残余；CEO 评审「度量未接状态机/sizing」
depends_on: [b12de4f59b744065895c4c6bc9f06df7]
---

# 因子机构级度量接 lifecycle 状态机/sizing 生产路径

> **状态（2026-06-25）**：**① 衰减半衰期 → lifecycle 状态机 ✅ done**（done 卡 1b83a5c5·`decay_diagnostic` perf 轴 advisory、unstable/no_decay 不硬退役、M-AUTHORITY 守、MUT-S/MUT-M 验证有牙）。**修正**：`ic_decay_half_life` 是 IC **持久性**（自相关）半衰期、≠ 现有转移测的 IC **水平衰减**——两者不同概念，故 decay 作 **advisory 不并入硬转移**（避免数学↔实现混淆），硬退役阈值是用户方法学决策。
> **② 容量/拥挤 → sizing 生产路径 留池待做**：方法学决策（如何按容量缩仓、Y 占位）+ 需 sizing 生产模块接线。

## Scope [必填]
§3 度量库（`lifecycle_metrics.py`）已建并验证（衰减/容量/因子族/拥挤 + 命门），但**度量层与状态机/sizing 未接**。本卡合拢：
① **衰减半衰期** → 喂 lifecycle 退役判定（半衰期短/status=ok 才作硬退役依据；unstable/no_decay 只告警不硬退役）；
② **容量** → 喂 sizing 上限（AUM 不超容量；Y 占位时只示意不硬卡）；
③ **因子族** → 喂组合层「独立 bet」计数（同族因子不重复计独立性，接 honest-N/组合三角）；
④ **拥挤** → 仅呈现层咨询（绝不接 sizing 自动减仓，结构已隔离）。

## 上下文 / 动机 [按需]
卡 b12de4f5 把 4 件度量的数学/命门立住，但 CEO 评审指出价值闭环停在度量层。接生产路径时须守：退役只用 status=ok 的半衰期（unstable 不硬退役）、容量 Y 占位诚实标、拥挤绝不自动减仓。

## 接线点（file:line，实现复核）[必填]
| 文件 | 位置 | 接什么 |
|---|---|---|
| app/factor_factory/lifecycle_metrics.py | 已建 | 复用 |
| app/factor_factory/lifecycle.py | evaluate_transition/状态机 | 半衰期 status=ok 作退役输入之一 |
| app/monitor/closure.py | monitor_tick（绩效轴） | 衰减/容量可作绩效轴附证（非 gate verdict，守 M-AUTHORITY） |
| 组合层 | 独立 bet 计数 | 因子族数接 honest-N/组合三角 |

## 对抗测试设计（种已知 bug，门必抓）[必填]
1. 退役只采 status=ok 的半衰期；种 unstable（随机游走）→ 不触发硬退役（绝不对弱识别发退役）。
2. 容量 Y 占位 → sizing 只示意不硬卡 + 诚实标；真 Y → 硬上限。
3. 拥挤接呈现层 → 绝不进 sizing 减仓路径（类型层守，同 §3 隔离）。
4. 因子族数接组合独立性 → 同族因子不重复计 independent bet。

## 验收一句话 [必填]
4 件度量真接进 lifecycle 退役/sizing/组合独立性生产路径（半衰期 unstable 不硬退役、容量 Y 占位诚实、拥挤绝不自动减仓），不破基线与现有闸门。
