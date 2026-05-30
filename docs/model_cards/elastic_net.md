---
key: elastic_net
family: ml
display_name: ElasticNet
tasks:
- regression
description: L1+L2 混合正则线性回归。兼顾稀疏与共线性稳定。
pros:
- 兼顾特征选择与共线性稳定
- 高维稳健
- 可解释
cons:
- 多一个 l1_ratio 要调
- 只能线性
- 需标准化
tuning_tip: 调 alpha（总强度）+ l1_ratio（0=岭，1=Lasso，常 0.5）；特征标准化。
default_params:
  alpha: 0.001
  l1_ratio: 0.5
param_schema:
  alpha:
    type: float
    default: 0.001
    help: 总正则强度
    min: 1.0e-05
    max: 1.0
  l1_ratio:
    type: float
    default: 0.5
    help: L1 占比(0岭/1Lasso)
    min: 0.0
    max: 1.0
needs_dl: false
tensorboard: false
requires_import: sklearn
runnable: true
compute: cpu
persistence: model.pkl（pickle/joblib）；reload→.predict；注意 pin 库版本避免跨版本反序列化失败。
related:
- ridge
- lasso
---

## L1 · 定位
L1+L2 混合正则线性回归。兼顾稀疏与共线性稳定。

## L2 · 优缺点 & 适用
**✅ 优点**
- 兼顾特征选择与共线性稳定
- 高维稳健
- 可解释

**⚠️ 缺点**
- 多一个 l1_ratio 要调
- 只能线性
- 需标准化

**适用**：高维 + 共线性特征的线性基线。
**不适用**：强非线性。

## L3 · 调参 & 数据要求
**调参策略**：调 alpha（总强度）+ l1_ratio（0=岭，1=Lasso，常 0.5）；特征标准化。

| 超参 | 作用 | 默认 | 范围 |
|---|---|---|---|
| `alpha` | 总正则强度 | 0.001 | 1e-05–1.0 |
| `l1_ratio` | L1 占比(0岭/1Lasso) | 0.5 | 0.0–1.0 |

**数据要求**：必须标准化；NaN 需先处理。

## L4 · 保存本体 & 评价
**保存本体**：model.pkl（pickle/joblib）；reload→.predict；注意 pin 库版本避免跨版本反序列化失败。
**评价图**：预测-实际/残差、系数权重
**算力**：CPU 即可
**可训练**：✅ 已实现训练模板，可直接训练。
