---
uuid: 29258b77505143668f267d60eb51b483
title: conformal 校准区间 + OOS 真留出覆盖接进模型台 UI（能信·不假绿灯）
status: done
owner: dreaminate
assigned_by: dreaminate
review_status: 1
priority: P2
area: frontend-trust
source: pool-card
source_ref: 池卡 92a2182f ②「前端渐进披露区间 + abstain UI」的模型台部分
depends_on: [d4a324ae663d440b9099df64b3efe103]
---

# conformal 校准区间接进模型台 UI

## Scope [必填]
做池卡 **92a2182f ②** 的模型台部分。`training_job_eval` 已返 `conformal_interval`（卡 d4a324ae 建·OOS 真
留出覆盖），但 `TrainingBenchPage` 只读 `body.charts`、**conformal_interval 前端零呈现** → 又一个「数学对、
用户看不见」。本卡建纯组件 `ConformalIntervalCard` + 接进 TrainingBenchPage 真闭环（读 conformal_interval → 渲染）。

## 治理（命门·不假绿灯在 UI / R23 / 真闭环）[必填]
- **不假绿灯（核心）**：① abstained（calib 不足）→「证据不足·未给校准区间」警示色，**绝不渲染假区间/假覆盖**（band/coverage=null 不显数值）；② 单次留出覆盖率是**带噪估计**（二项抽样 + exchangeability，后端 note 已述）→ **中性色、绝不上成功绿当达标**；③ interval 缺省/null（非回归/无 OOS）→ **不渲染**（不编造）。
- **合规说明单一源**：渲染后端 `note`（含「单次含噪、跨多次取均值方判校准」caveat），不在 UI 重拼措辞。
- **真闭环**：TrainingBenchPage `/eval` 响应 → `setConformal(body.conformal_interval ?? null)` → ConformalIntervalCard。

## 接线点（file:line，实现复核）[必填]
| 文件 | 位置 | 改什么(扩展不替换) |
|---|---|---|
| components/charts/ConformalIntervalCard.tsx | 新建纯组件（--cc-* token 对齐模型台） | 新增 |
| pages/models/TrainingBenchPage.tsx | +conformal state + openEval 读 conformal_interval + EvalCharts 旁渲染 | additive |

## 对抗测试设计（种已知 bug，门必抓）[必填]
1. 正常→渲半宽/目标/留出实测覆盖 + 后端 note；**留出覆盖中性色非成功绿**（MUT-cf 覆盖渲绿→FAIL，有牙）。
2. abstained→「证据不足」警示色、**绝不出假区间/假覆盖数字**；note 仍渲。
3. interval null/undefined→不渲染（container 空，不编造）。band=null 未 abstain 边角→N/A 不崩。

## 验收一句话 [必填]
conformal 校准区间 + OOS 真留出覆盖接进模型台（ConformalIntervalCard + TrainingBenchPage 真闭环），不假绿灯
（abstained 不造假区间/单次覆盖中性非绿/缺数据不渲染），MUT-cf 验证覆盖渲绿有牙；tsc + 前端 293 passed + build 三门绿。

## 完成记录（2026-06-25 · autonomous-loop / D-CONFORMAL-UI）
- **价值闭环（能信）**：conformal_interval（卡 d4a324ae 建于 model_eval、UI 零呈现）→ `ConformalIntervalCard` 纯组件 + TrainingBenchPage openEval 真映射。用户看见「±半宽·目标覆盖·留出实测覆盖 + caveat」或「证据不足」。
- **不假绿灯在 UI**：abstained 不造假区间、单次覆盖中性色非绿、缺数据不渲染。MUT-cf（覆盖渲成功绿）验证有牙。
- **验证**：tsc 无错；`ConformalIntervalCard.test` 5 passed；**全前端 293 passed / 24 文件**（基线 288，净 +5）；vite build ✓。
- **92a2182f ② 剩余**：信号层 abstain 的 UI 呈现 + 时序 ACI 在线维覆盖留池（如需）。
- **本轮 loop「commit 和 push 自动进行」→ 本地 commit + push 分支**（land main 仍仅用户）。
