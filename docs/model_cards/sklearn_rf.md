---
key: sklearn_rf
family: ml
display_name: 随机森林
tasks:
- classification
- regression
description: Bagging 决策树集成。抗过拟合稳健基线，几乎不用调参。
pros:
- 几乎不用调参、稳健
- 抗过拟合（bagging 平均）
- 可并行、可解释重要度
cons:
- 精度通常不如 GBDT
- 外推能力弱（树模型通病）
- 模型大、预测慢
tuning_tip: n_estimators 越多越稳（100–500）；max_depth/min_samples_leaf 控过拟合；通常默认即可。
default_params:
  n_estimators: 100
param_schema:
  n_estimators:
    type: int
    default: 100
    help: 树的数量
    min: 10
    max: 1000
  max_depth:
    type: int
    default: 0
    help: 树深，0 不限
    min: 0
    max: 64
  min_samples_leaf:
    type: int
    default: 1
    help: 叶最小样本
    min: 1
    max: 50
needs_dl: false
tensorboard: false
requires_import: sklearn
runnable: true
compute: cpu
persistence: model.pkl（pickle/joblib）；reload→.predict；注意 pin 库版本避免跨版本反序列化失败。
related:
- extra_trees
- lgbm
---

## L1 · 定位
Bagging 决策树集成。抗过拟合稳健基线，几乎不用调参。

## L2 · 优缺点 & 适用
**✅ 优点**
- 几乎不用调参、稳健
- 抗过拟合（bagging 平均）
- 可并行、可解释重要度

**⚠️ 缺点**
- 精度通常不如 GBDT
- 外推能力弱（树模型通病）
- 模型大、预测慢

**适用**：想要零调参的稳健对照基线。
**不适用**：追求最高精度（用 GBDT）、需外推。

## L3 · 调参 & 数据要求
**调参策略**：n_estimators 越多越稳（100–500）；max_depth/min_samples_leaf 控过拟合；通常默认即可。

| 超参 | 作用 | 默认 | 范围 |
|---|---|---|---|
| `n_estimators` | 树的数量 | 100 | 10–1000 |
| `max_depth` | 树深，0 不限 | 0 | 0–64 |
| `min_samples_leaf` | 叶最小样本 | 1 | 1–50 |

**数据要求**：无需标准化；NaN 需先处理。

## L4 · 保存本体 & 评价
**保存本体**：model.pkl（pickle/joblib）；reload→.predict；注意 pin 库版本避免跨版本反序列化失败。
**评价图**：特征重要度、ROC/PR、预测-实际/残差
**算力**：CPU 即可
**可训练**：✅ 已实现训练模板，可直接训练。
