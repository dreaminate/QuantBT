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
