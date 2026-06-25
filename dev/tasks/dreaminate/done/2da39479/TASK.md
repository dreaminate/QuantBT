---
uuid: 2da39479226c45d7a303f0046db25071
title: CPCV 作 cv_scheme 产 per-path OOS 指标分布（report-only · 命门最深件 ①）
status: done
owner: dreaminate
assigned_by: dreaminate
review_status: 1
priority: P2
area: models-methodology
source: pool-card
source_ref: 池卡 861182e6 ①（CPCV 接 promote/overfit gate + 双轨 report）的 cv_scheme 产路径分布部分
depends_on: []
---

# CPCV 作 cv_scheme 产 per-path OOS 指标分布

## Scope [必填]
做池卡 **861182e6 ①**。R4 CPCV 库（`models/cpcv.py`）已建（splits/paths/分布），但**纯孤岛、训练层零消费**
（前 3 轮 loop 判为「需独立 Plan」延后）。本卡落地消费侧 ①：`cpcv_oos_metric_distribution`——CPCV φ 路径
上模型 OOS 主指标的分布，**report-only**（不接 gate、不替方法学拍板）。

## 数学先行（finding cpcv.md「消费侧 ①」）
φ=C(N-1,k-1) 条路径各覆盖全样本一次；每路径算模型 OOS r2 → 分布 mean/std/**q05**/min/median/max/frac_below_0。
**q05/路径方差 = 过拟合脆弱度**：q05≪mean 或方差大 = OOS 表现高度依赖切分（split-fragile，过拟合嫌疑）。

## 治理（命门·行为不变/不假绿灯/report-only）[必填]
- **行为不变抽取**：从 train_model 主循环抽 `_fit_predict_fold`（lambdarank group + classification proba 分支原样），train_model 与 CPCV 共用 = fit/predict 单一源；全训练测试随全量套件绿（行为保持）。
- **判别器命门**：强信号→r2 高稳、噪声→r2≈0/负；路径重组对齐才成立——MUT「预测 test 段内反序(misalign)」→ 强信号 r2 崩到 -0.87 → 判别器红（证 assemble_cpcv_paths 重组正确）。
- **不假绿灯**：regression-only（非回归→unsupported_task 不伪造 r2）；样本/组数不足→insufficient；非有限路径剔除；确定性（random_state 固定）。
- **report-only**：不接 gate、不替拍板（q05→gate 阈值、Sharpe/DSR 口径=用户方法学 follow-on）。

## 接线点（file:line，实现复核）[必填]
| 文件 | 位置 | 改什么(扩展不替换) |
|---|---|---|
| app/models/training.py | +`_fit_predict_fold`(抽出·行为不变) + `cpcv_oos_metric_distribution` | additive·主循环改调 helper |
| app/models/cpcv.py | 复用 cpcv_splits/assemble_cpcv_paths | 不改 |

## 对抗测试设计（种已知 bug，门必抓）[必填]
1. **判别器**：强信号→mean>0.5/q05>0.3/frac_below_0=0；噪声→mean<0.1/q05<0.05；强≫噪声（MUT 预测 misalign→崩，有牙）。
2. n_paths==φ=C(N-1,k-1)（跨 (6,2)/(5,2)/(8,3)）；分位序 min≤q05≤median≤max。
3. 非回归→unsupported_task 不伪造；样本不足→insufficient；确定性 + JSON-safe。
4. _fit_predict_fold 抽取行为不变（31 训练测试 + 全量套件绿）。

## 验收一句话 [必填]
CPCV 作消费产 per-path OOS r2 分布（report-only·q05 脆弱度·regression-only 诚实 abstain），_fit_predict_fold
抽取行为不变，判别器 MUT「预测 misalign」验证路径重组正确有牙；CPCV 7 测 + 全量后端 1603 passed/0 failed。

## 完成记录（2026-06-25 · autonomous-loop / D-CPCV-CONSUME）
- **啃下最深命门件**：CPCV（前 3 轮判「需独立 Plan」）经充分勘察（assemble_cpcv_paths 通用可复用于 predictions、组合序一致）后落地消费侧 ①。`_fit_predict_fold` 行为不变抽出（train_model/CPCV 单一源）；`cpcv_oos_metric_distribution` φ 路径 OOS r2 分布。
- **判别器有真牙**：MUT「预测 test 段内反序」→ 强信号 r2 崩 -0.87 → 判别器 + 强信号测试双红（证路径重组对齐正确，非纸糊）。
- **避方法学纠缠**：用模型自身 r2（非 Sharpe/DSR，后者需 prediction→收益转换=用户方法学）→ report-only、regression-only、不替拍板。
- **验证**：`test_cpcv_oos_distribution.py` 7 + 训练 31 passed；**全量后端 1603 passed / 13 skipped / 0 failed / 124s**（基线 1596，净 +7）。
- **follow-on（861182e6 ②③）**：q05 接 gate（阈值/口径=用户）+ Sharpe/DSR（收益转换=用户方法学）+ 分类/排序任务——池卡留。
- **本轮 loop「commit 和 push 自动进行」→ 本地 commit + push 分支**（land main 仍仅用户）。
