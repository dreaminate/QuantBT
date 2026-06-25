---
uuid: c43c630186034782819d7820aecb2e76
title: CPCV per-path 分布扩到二分类（roc_auc · proba 路径重组）
status: done
owner: dreaminate
assigned_by: dreaminate
review_status: 1
priority: P2
area: models-methodology
source: extension
source_ref: done 卡 2da39479（CPCV 消费 regression-only）的任务扩展；池卡 861182e6 ①
depends_on: [2da39479226c45d7a303f0046db25071]
---

# CPCV per-path 分布扩到二分类

## Scope [必填]
`cpcv_oos_metric_distribution`（done 卡 2da39479）原 regression-only（r2）。本卡 additive 扩**二分类**：重组
proba 路径 → per-path roc_auc 分布。技术扩展（非方法学门控——指标=模型自身 OOS roc_auc）。

## 治理（命门·不假绿灯/additive）[必填]
- **任务白名单**：regression→r2(baseline 0)、二分类→roc_auc(baseline 0.5)；多分类/lambdarank/无 predict_proba → unsupported_task（绝不发假指标）。
- **proba 路径重组**：分类同时重组 pred（_evaluate_split 二类校验）+ proba（roc_auc 输入）路径；判别器有牙——MUT「proba misalign」→ 强分类器 auc 崩到 0.4999、强 vs 噪声判别器红。
- **additive**：regression 路径不变（baseline=0.0、frac_below_0 不变）；分类是新分支。report-only 不接 gate。

## 接线点（file:line，实现复核）[必填]
| 文件 | 位置 | 改什么(扩展不替换) |
|---|---|---|
| app/models/training.py | `cpcv_oos_metric_distribution` 任务分派 + proba 路径重组 + baseline 字段 | additive 分类分支 |

## 对抗测试设计（种已知 bug，门必抓）[必填]
1. 强二分类器 → roc_auc 分布高（mean>0.8/q05>0.65/min≥0.5/max≤1）、metric=roc_auc、baseline=0.5、n_paths==φ。
2. **判别器**：噪声 label → auc≈0.5；强≫噪声（MUT proba misalign→强 auc 崩 0.4999→红，有牙）。
3. 多分类 → unsupported_task（不发假 auc）；regression baseline==0.0 不变。

## 验收一句话 [必填]
CPCV per-path 分布扩二分类（roc_auc·proba 路径重组·baseline 0.5·多分类 unsupported 诚实），MUT proba misalign
验证判别器有牙、regression 路径不变；全量后端 1609 passed/0 failed。

## 完成记录（2026-06-25 · autonomous-loop / D-CPCV-CLF）
- **任务扩展**：CPCV 消费从 regression-only 扩到二分类（roc_auc）；proba 路径用 assemble_cpcv_paths 重组（与 pred 同机制）；baseline 字段（r2:0 / auc:0.5）供脆弱度判读。多分类/lambdarank/无 proba 诚实 unsupported_task。
- **判别器有牙**：MUT「proba misalign」→ 强分类器 auc 崩 0.4999 → 强 vs 噪声判别器 + 强信号高 auc 双红（证 proba 重组对齐正确）。
- **验证**：`test_cpcv_oos_distribution.py` 11 passed（+4 分类）；**全量后端 1609 passed / 13 skipped / 0 failed / 124s**（基线 1605，净 +4）。
- **本轮 loop「commit 和 push 自动进行」→ 本地 commit + push 分支**（land main 仍仅用户·分支续 land-ready）。
