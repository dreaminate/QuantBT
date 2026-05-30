---
key: extra_trees
family: ml
display_name: 极端随机树
tasks:
- classification
- regression
description: Extra-Trees：分裂阈值也随机，比随机森林方差更低、更快。
pros:
- 比 RF 更快、方差更低
- 抗过拟合
- 零调参可用
cons:
- 偏差可能略高
- 精度一般不及 GBDT
- 外推弱
tuning_tip: 同随机森林：n_estimators 多即可；max_depth/min_samples_leaf 控过拟合。
default_params:
  n_estimators: 200
param_schema:
  n_estimators:
    type: int
    default: 200
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
- sklearn_rf
---

## L1 · 定位
Extra-Trees：分裂阈值也随机，比随机森林方差更低、更快。

## L2 · 优缺点 & 适用
**✅ 优点**
- 比 RF 更快、方差更低
- 抗过拟合
- 零调参可用

**⚠️ 缺点**
- 偏差可能略高
- 精度一般不及 GBDT
- 外推弱

**适用**：想要比 RF 更快的稳健基线。
**不适用**：追求最高精度。

## L3 · 调参 & 数据要求
**调参策略**：同随机森林：n_estimators 多即可；max_depth/min_samples_leaf 控过拟合。

| 超参 | 作用 | 默认 | 范围 |
|---|---|---|---|
| `n_estimators` | 树的数量 | 200 | 10–1000 |
| `max_depth` | 树深，0 不限 | 0 | 0–64 |
| `min_samples_leaf` | 叶最小样本 | 1 | 1–50 |

**数据要求**：无需标准化；NaN 需先处理。

## L4 · 保存本体 & 评价
**保存本体**：model.pkl（pickle/joblib）；reload→.predict；注意 pin 库版本避免跨版本反序列化失败。
**评价图**：特征重要度、ROC/PR、预测-实际/残差
**算力**：CPU 即可
**可训练**：✅ 已实现训练模板，可直接训练。
