---
key: lasso
family: ml
display_name: Lasso 回归
tasks:
- regression
description: L1 正则线性回归。自动特征选择（稀疏系数）。
pros:
- 自动特征选择（稀疏）
- 可解释
- 高维下抗过拟合
cons:
- 共线性下选择不稳定
- 只能线性
- 需标准化
tuning_tip: 调 alpha（越大越稀疏，0.0001–1）；特征标准化。
default_params:
  alpha: 0.001
param_schema:
  alpha:
    type: float
    default: 0.001
    help: L1 正则强度
    min: 1.0e-05
    max: 1.0
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
L1 正则线性回归。自动特征选择（稀疏系数）。

## L2 · 优缺点 & 适用
**✅ 优点**
- 自动特征选择（稀疏）
- 可解释
- 高维下抗过拟合

**⚠️ 缺点**
- 共线性下选择不稳定
- 只能线性
- 需标准化

**适用**：高维特征想自动筛选、要稀疏可解释模型。
**不适用**：特征强共线（用 ElasticNet）。

## L3 · 调参 & 数据要求
**调参策略**：调 alpha（越大越稀疏，0.0001–1）；特征标准化。

| 超参 | 作用 | 默认 | 范围 |
|---|---|---|---|
| `alpha` | L1 正则强度 | 0.001 | 1e-05–1.0 |

**数据要求**：必须标准化；NaN 需先处理。

## L4 · 保存本体 & 评价
**保存本体**：model.pkl（pickle/joblib）；reload→.predict；注意 pin 库版本避免跨版本反序列化失败。
**评价图**：预测-实际/残差、非零系数
**算力**：CPU 即可
**可训练**：✅ 已实现训练模板，可直接训练。
