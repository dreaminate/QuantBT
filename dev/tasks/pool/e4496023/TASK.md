---
uuid: e4496023a0994583955ef00f00d319a2
title: 因子收益归因接消费侧（组合台/归因报告 + UI 呈现）
status: todo
owner: wait
assigned_by: dreaminate
review_status: 0
priority: P2
area: eval-methodology
source: goal-gap
source_ref: done 卡 ff286f80（attribution math 件）的消费侧残余
depends_on: [ff286f80af1546bfaaea9ce0a6feb9b2]
---

# 因子收益归因接消费侧

> **状态（2026-06-25）**：**provider + 对齐器 ✅ done**（done 卡 8f9d79fd·D-ATTRIB-PROVIDER·审计 #2）：
> `factor_factory.layered.factor_return_series`（单因子 per-period 多空收益时序 F_t·复用 layered 分位·leak-free·诊断口径）
> + `eval.attribution.attribution_from_series`（ts 键 inner-join 对齐器·消除手工位置 misalign 假绿灯）→ 系统真能产因子收益物料喂归因
> （此前 factor_returns 必手搓=输入假绿灯）。MUT-A（多空价差取错端）/MUT-B'（对齐各自独立顺序）双变异抓。
> **剩 follow-on（③·用户方法学）**：① 组合台/归因报告**端点**（接真组合收益 + 用户选的因子集 → attribution_from_series）；
> ② 前端贡献瀑布/堆叠 + R² + abstain 呈现；③ 因子集选择/收益口径(excess vs raw)/回归窗 = 用户方法学拍板。

## Scope [必填]
`eval/attribution.py`（done 卡 ff286f80）已建并验证（加总恒等式命门 + 诚实 abstain），但**纯 math 件、无消费侧**。
本卡合拢价值闭环：
① 组合台/归因报告：接真组合实现收益 + 因子收益矩阵 → `factor_return_attribution` → 各因子贡献 + 特异 + R²；
② 前端呈现：贡献瀑布/堆叠 + R²（因子解释占比）+ abstain（证据不足/共线）诚实呈现（不假绿灯：低 R² 不渲染成「已归因」、insufficient/collinear 显证据不足非假 β）。

## 上下文 / 动机 [按需]
**用户方法学决策（不替拍）**：因子集选哪些（风格/行业/自定义）、收益口径（excess vs raw）、回归窗（全样本 vs 滚动）—— 用户那摊；本件提供机制 + 恒等式守正确，松紧用户定。

## 接线点（file:line，实现复核）[必填]
| 文件 | 位置 | 改什么 |
|---|---|---|
| (组合台后端端点) | 取组合收益 + 因子收益 → factor_return_attribution | 新增 |
| (前端归因卡) | 贡献分解 + R² + abstain 呈现（--cc-*/--desk-* 对齐宿主） | 新增 |

## 对抗测试设计（种已知 bug，门必抓）[必填]
1. 端点输出 contrib 加总恒等式不破（绑 math 件命门）。
2. 低 R²/insufficient/collinear → UI 诚实呈现（证据不足非假 β、低解释占比不渲染成「已归因」绿）。

## 验收一句话 [必填]
因子收益归因接组合台 + 归因报告 UI（贡献分解 + R² + abstain 诚实呈现），加总恒等式端到端不破、不假绿灯。
