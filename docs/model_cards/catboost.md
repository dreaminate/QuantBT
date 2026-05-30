---
key: catboost
family: ml
display_name: CatBoost
tasks:
- classification
- regression
description: 梯度提升树（ordered boosting + 对称树）。对类别特征友好、默认参数就很稳，抗过拟合好。
pros:
- 默认参数即强、调参负担小
- ordered boosting 抗过拟合（小样本友好）
- 对类别特征原生支持
- 确定性好
cons:
- 训练比 LGBM 慢
- 模型体积大
- 极大数据上不如 LGBM 快
tuning_tip: 多数情况默认即可；要调先 depth(4–10) + learning_rate(0.03–0.1) + l2_leaf_reg(1–10)；iterations 高 + 早停。
default_params:
  iterations: 300
  learning_rate: 0.05
  depth: 6
param_schema:
  iterations:
    type: int
    default: 300
    help: 迭代次数
    min: 50
    max: 3000
  learning_rate:
    type: float
    default: 0.05
    help: 学习率
    min: 0.005
    max: 0.3
  depth:
    type: int
    default: 6
    help: 对称树深度
    min: 3
    max: 12
  l2_leaf_reg:
    type: float
    default: 3.0
    help: L2 正则
    min: 1.0
    max: 30.0
needs_dl: false
tensorboard: false
requires_import: catboost
runnable: true
compute: cpu
persistence: model.pkl（pickle/joblib）；reload→.predict；注意 pin 库版本避免跨版本反序列化失败。
related:
- lgbm
- xgboost
---

## L1 · 定位
梯度提升树（ordered boosting + 对称树）。对类别特征友好、默认参数就很稳，抗过拟合好。

## L2 · 优缺点 & 适用
**✅ 优点**
- 默认参数即强、调参负担小
- ordered boosting 抗过拟合（小样本友好）
- 对类别特征原生支持
- 确定性好

**⚠️ 缺点**
- 训练比 LGBM 慢
- 模型体积大
- 极大数据上不如 LGBM 快

**适用**：小到中样本、想少调参拿稳基线、类别特征多。
**不适用**：超大数据要极致速度（用 LGBM）。

## L3 · 调参 & 数据要求
**调参策略**：多数情况默认即可；要调先 depth(4–10) + learning_rate(0.03–0.1) + l2_leaf_reg(1–10)；iterations 高 + 早停。

| 超参 | 作用 | 默认 | 范围 |
|---|---|---|---|
| `iterations` | 迭代次数 | 300 | 50–3000 |
| `learning_rate` | 学习率 | 0.05 | 0.005–0.3 |
| `depth` | 对称树深度 | 6 | 3–12 |
| `l2_leaf_reg` | L2 正则 | 3.0 | 1.0–30.0 |

**数据要求**：无需标准化；NaN/类别原生处理。

## L4 · 保存本体 & 评价
**保存本体**：model.pkl（pickle/joblib）；reload→.predict；注意 pin 库版本避免跨版本反序列化失败。
**评价图**：特征重要度、ROC/PR(分类)、预测-实际/残差(回归)
**算力**：CPU 即可
**可训练**：✅ 已实现训练模板，可直接训练。
