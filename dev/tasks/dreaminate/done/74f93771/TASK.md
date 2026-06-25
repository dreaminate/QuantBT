---
uuid: 74f93771c3bc415a86dac76cbf09bc77
title: CPCV 路径分布 opt-in 集成进 train_model（cpcv_distribution 入 TrainResult·report-only）
status: done
owner: dreaminate
assigned_by: dreaminate
review_status: 1
priority: P2
area: models-methodology
source: extension
source_ref: done 卡 2da39479/c43c6301（CPCV 消费函数）的训练管线集成；池卡 861182e6 ①
depends_on: [2da39479226c45d7a303f0046db25071]
---

# CPCV 路径分布 opt-in 集成进 train_model

## Scope [必填]
`cpcv_oos_metric_distribution`（done 卡 2da39479/c43c6301）此前是孤立可调函数、训练管线零集成。本卡把它
**opt-in 集成**进 train_model：spec.compute_cpcv=True → 训练后产 CPCV 路径分布写进 `TrainResult.cpcv_distribution`
→ 随 result.json 流到 verdict/UI。**默认关**=零行为/成本变更。

## 治理（命门·护栏/不假绿灯/additive）[必填]
- **默认关·不替方法学拍板**（护栏）：compute_cpcv 默认 False → cpcv_distribution=None（未算≠已算·不假绿灯）；开启=用户自负额外 C(N,k) 拟合成本；阈值/接 gate 仍属用户（卡 861182e6 ②）。本字段只产 report-only 分布。
- **additive 零回归**：ModelSpec/TrainResult 加 default 字段（向后兼容）、train_model 加默认关分支（行为不变）；49 训练测试 + 全量套件绿。

## 接线点（file:line，实现复核）[必填]
| 文件 | 位置 | 改什么(扩展不替换) |
|---|---|---|
| app/models/training.py | ModelSpec +compute_cpcv/cpcv_n_groups/cpcv_k_test(默认关)；TrainResult +cpcv_distribution(None)；train_model opt-in 计算 | additive |

## 对抗测试设计（种已知 bug，门必抓）[必填]
1. 默认关 → TrainResult.cpcv_distribution is None（不算、不假绿灯）。
2. opt-in → 产分布（status ok·metric r2·n_paths==φ）；asdict(result) JSON-safe（含 cpcv_distribution）。
3. additive：49 训练测试 + 全量套件不破（schema 加字段向后兼容）。

## 验收一句话 [必填]
CPCV 路径分布 opt-in 集成进 train_model（默认关零行为变更·开启产 report-only 分布入 TrainResult·JSON-safe），
additive 不破 49 训练测试；全量后端 1610 passed/0 failed。

## 完成记录（2026-06-25 · autonomous-loop / D-CPCV-TRAIN-INTEGRATE）
- **集成进训练生命周期**：CPCV 从孤立函数 → opt-in 集成进 train_model（spec.compute_cpcv），分布写进 TrainResult.cpcv_distribution 随 result.json 流转。默认关=零行为/成本变更（护栏：不替方法学拍板、用户自负开启）。
- **验证**：`test_cpcv_oos_distribution.py` 12 passed（+1 opt-in 集成：默认关→None、开启→分布·JSON-safe）；49 训练测试不破；**全量后端 1610 passed / 13 skipped / 0 failed / 124s**（基线 1609，净 +1）。
- **follow-on（861182e6 ②）**：result.cpcv_distribution → verdict/run_detail UI 呈现 + q05 接 gate（阈值=用户方法学）池卡留。
- **本轮 loop「commit 和 push 自动进行」→ 本地 commit + push 分支**（land main 仍仅用户·分支续 land-ready）。
