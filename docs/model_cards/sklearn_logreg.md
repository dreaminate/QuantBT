---
key: sklearn_logreg
family: ml
display_name: 逻辑回归
tasks:
- classification
description: 线性分类基线，可解释、训练快。用于对照复杂模型是否真有增益。
pros:
- 可解释（系数即权重）
- 训练快、稳定
- 概率输出校准好
cons:
- 只能线性边界
- 需特征标准化
- 对共线性敏感
tuning_tip: 主要调 C（正则强度倒数，0.01–10）；特征先标准化；类别不平衡用 class_weight。
default_params:
  C: 1.0
  max_iter: 300
param_schema:
  C:
    type: float
    default: 1.0
    help: 正则强度倒数
    min: 0.001
    max: 100.0
  max_iter:
    type: int
    default: 300
    help: 最大迭代
    min: 50
    max: 5000
needs_dl: false
tensorboard: false
requires_import: sklearn
runnable: true
compute: cpu
persistence: model.pkl（pickle/joblib）；reload→.predict；注意 pin 库版本避免跨版本反序列化失败。
related:
- ridge
- elastic_net
---

## L1 · 定位
线性分类基线，可解释、训练快。用于对照复杂模型是否真有增益。

## L2 · 优缺点 & 适用
**✅ 优点**
- 可解释（系数即权重）
- 训练快、稳定
- 概率输出校准好

**⚠️ 缺点**
- 只能线性边界
- 需特征标准化
- 对共线性敏感

**适用**：二分类基线、要可解释、对照复杂模型。
**不适用**：强非线性关系。

## L3 · 调参 & 数据要求
**调参策略**：主要调 C（正则强度倒数，0.01–10）；特征先标准化；类别不平衡用 class_weight。

| 超参 | 作用 | 默认 | 范围 |
|---|---|---|---|
| `C` | 正则强度倒数 | 1.0 | 0.001–100.0 |
| `max_iter` | 最大迭代 | 300 | 50–5000 |

**数据要求**：建议标准化；NaN 需先处理。

## L4 · 保存本体 & 评价
**保存本体**：model.pkl（pickle/joblib）；reload→.predict；注意 pin 库版本避免跨版本反序列化失败。
**评价图**：ROC/PR、混淆矩阵、系数权重
**算力**：CPU 即可
**可训练**：✅ 已实现训练模板，可直接训练。
