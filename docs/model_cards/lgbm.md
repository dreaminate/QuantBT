---
key: lgbm
family: ml
display_name: LightGBM
tasks:
- classification
- regression
- lambdarank
description: 梯度提升树（leaf-wise）。默认主力模型，速度快、表格/截面数据强基线。
pros:
- 训练快、内存省
- 表格/截面数据强基线
- 原生处理缺失值与类别
- 特征重要度可解释
- 支持排序任务(lambdarank)
cons:
- 小样本高噪声易过拟合（量化收益预测正是如此）
- 不建模时序依赖
- num_leaves/depth 调不好易过拟合
tuning_tip: 先 n_estimators 设高 + 早停；再调 learning_rate(0.01–0.1) 与 num_leaves(7–255) 定容量；过拟合看 train-val 裂口
  + PBO。
default_params:
  n_estimators: 100
  learning_rate: 0.05
  num_leaves: 31
param_schema:
  n_estimators:
    type: int
    default: 100
    help: 树的数量
    min: 10
    max: 2000
  learning_rate:
    type: float
    default: 0.05
    help: 学习率
    min: 0.001
    max: 0.5
  num_leaves:
    type: int
    default: 31
    help: 叶子数（控复杂度）
    min: 7
    max: 255
  max_depth:
    type: int
    default: -1
    help: 树深，-1 不限
    min: -1
    max: 32
needs_dl: false
tensorboard: false
requires_import: lightgbm
runnable: true
compute: cpu
persistence: model.pkl（pickle/joblib）；reload→.predict；注意 pin 库版本避免跨版本反序列化失败。
related:
- xgboost
- catboost
---

## L1 · 定位
梯度提升树（leaf-wise）。默认主力模型，速度快、表格/截面数据强基线。

## L2 · 优缺点 & 适用
**✅ 优点**
- 训练快、内存省
- 表格/截面数据强基线
- 原生处理缺失值与类别
- 特征重要度可解释
- 支持排序任务(lambdarank)

**⚠️ 缺点**
- 小样本高噪声易过拟合（量化收益预测正是如此）
- 不建模时序依赖
- num_leaves/depth 调不好易过拟合

**适用**：横截面选股打分、中低频、特征已工程化；需要排序(lambdarank)时首选。
**不适用**：原始序列直接喂（交给 LSTM/TFT）、极小样本。

## L3 · 调参 & 数据要求
**调参策略**：先 n_estimators 设高 + 早停；再调 learning_rate(0.01–0.1) 与 num_leaves(7–255) 定容量；过拟合看 train-val 裂口 + PBO。

| 超参 | 作用 | 默认 | 范围 |
|---|---|---|---|
| `n_estimators` | 树的数量 | 100 | 10–2000 |
| `learning_rate` | 学习率 | 0.05 | 0.001–0.5 |
| `num_leaves` | 叶子数（控复杂度） | 31 | 7–255 |
| `max_depth` | 树深，-1 不限 | -1 | -1–32 |

**数据要求**：无需标准化；NaN 原生处理；截面对齐；样本越多越稳。

## L4 · 保存本体 & 评价
**保存本体**：model.pkl（pickle/joblib）；reload→.predict；注意 pin 库版本避免跨版本反序列化失败。
**评价图**：特征重要度(gain)、ROC/PR(分类)、预测-实际/残差(回归)、分fold IC
**算力**：CPU 即可
**可训练**：✅ 已实现训练模板，可直接训练。
