---
uuid: 1b83a5c5f82e4c78919a7c253efbf6c9
title: IC 持久性 AR(1) 半衰期接进 lifecycle 状态机（perf 轴·advisory）
status: done
owner: dreaminate
assigned_by: dreaminate
review_status: 1
priority: P2
area: factor-lifecycle
source: pool-card
source_ref: 池卡 aa13c3b0「因子机构级度量接 lifecycle 状态机/sizing」的 lifecycle 状态机部分
depends_on: []
---

# IC 持久性 AR(1) 半衰期接进 lifecycle 状态机

## Scope [必填]
做池卡 **aa13c3b0** 的「接 lifecycle 状态机」部分。已建 `lifecycle_metrics.ic_decay_half_life`（slice-4，
AR(1) 持久性半衰期）**lifecycle 状态机零消费** → 价值闭环开口。本卡把它作 **additive·perf 轴·advisory 诊断**
接进 `LifecycleManager`（现 OBSERVATION→WARNING 是 crude 单点比较）。

## 数学先行（复用 slice-4 finding）
h=ln(0.5)/ln(ρ)，ρ=AR(1) 持久系数（IC_t=c+ρ·IC_{t-1}+ε）。near-unit-root 弱识别（local-to-unity）→ OLS ρ̂
向下偏、CI 跨 0/1 → status='unstable'：**机器绝不对随机游走发 'ok'/硬持久结论**。这是「持久性」≠「水平衰减」
（现有转移测的是 IC 水平下降）——两者不同概念，故 decay **不并入硬转移、只作 advisory**（避免数学↔实现混淆）。

## 治理（命门·M-AUTHORITY/不假绿灯/advisory）[必填]
- **advisory 绝不硬退役**（slice-4 自律 + 用户方法学护栏）：decay 仅供人工/UI/监控自判，**不进 `evaluate_transition` 硬转移**；硬转移阈值是用户那摊。
- **M-AUTHORITY A1**：lifecycle 硬转移**只吃 perf 轴 IC 观测**，绝不接 gate verdict（DSR/PBO/color）——注入 gate verdict 到 observation.extra 不改判（机器可检测试守）。
- **诚实 status**：unstable/reversal/insufficient 如实标，绝不渲染成 'ok' 硬结论。
- **单一源**：decay_diagnostic 复用 `ic_decay_half_life`、绝不重实现（多 ρ 区间扫描守一致）。

## 接线点（file:line，实现复核）[必填]
| 文件 | 位置 | 改什么(扩展不替换) |
|---|---|---|
| app/factor_factory/lifecycle.py | +import + `LifecycleManager.decay_diagnostic` + `evaluate()` advisory 注解 | additive；硬转移逻辑不动 |

## 对抗测试设计（种已知 bug，门必抓）[必填]
1. **单一源**：decay_diagnostic == ic_decay_half_life **逐字段·扫 ρ∈{0.3,0.6,0.9,0.97}+reversal**（MUT-S clip ρ>0.9 验证有牙；单点 ρ 会漏）。
2. **advisory 不硬退役**：水平稳定但非持久（快均值回复）因子 decay 标非持久、**不被退役/降级**（种坏：decay 当硬触发→误退）。
3. **诚实 status**：随机游走（ρ≈1）→ 'unstable'/'no_decay'、绝不 'ok'（不假绿灯）。
4. **M-AUTHORITY A1**：注入 gate verdict 到 extra 不改转移（MUT-M 偷看 gate_color 验证有牙）。
5. 样本不足→'insufficient'；无观测→None。

## 验收一句话 [必填]
ic_decay_half_life 接进 lifecycle 状态机（perf 轴·advisory·诚实 status·单一源），advisory 绝不硬退役、
转移守 M-AUTHORITY perf 轴；MUT-S/MUT-M 双 mutation 验证单一源与 M-AUTHORITY 有牙；全量后端绿、基线不破。

## 完成记录（2026-06-25 · autonomous-loop / D-LIFECYCLE-DECAY-ADVISORY）
- **价值闭环**：ic_decay_half_life（slice-4 建、lifecycle 状态机零消费）→ `LifecycleManager.decay_diagnostic`（perf 轴 advisory）+ evaluate() 事件 advisory 注解；硬转移逻辑零改（advisory 不改判）。
- **meta 教训应用 + 验证**：单一源测试初版只测 ρ=0.6 一点 → MUT-S（clip ρ>0.9）**逃逸**（正是「测单点 happy-path 不扫判别区间」盲区）→ 强化为多 ρ 区间扫描后 MUT-S 必抓。M-AUTHORITY 测试 MUT-M（转移偷看 gate_color）验证有牙。
- **验证**：`test_lifecycle_decay_advisory.py` 5 + test_alpha_lite_and_lifecycle 7 passed；**全量后端 1579 passed / 13 skipped / 0 failed / 180s**（基线 1574，净 +5）。
- **aa13c3b0 剩余**：capacity/crowding → **sizing 生产路径**未做（方法学决策——如何按容量/拥挤度缩仓是用户那摊）；池卡留该部分。
- **本轮 loop「commit 和 push 自动进行」→ 本地 commit + push 分支**（land main 仍仅用户）。
