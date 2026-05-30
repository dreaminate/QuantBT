---
key: ridge
family: ml
display_name: 岭回归
tasks:
- regression
description: L2 正则线性回归。共线性下稳定的可解释基线。
pros:
- 共线性下稳定
- 可解释、训练极快
- 闭式解、无随机性
cons:
- 只能线性
- 不做特征选择（系数不为0）
- 需标准化
tuning_tip: 只调 alpha（L2 强度，0.01–100）；特征务必标准化。
default_params:
  alpha: 1.0
param_schema:
  alpha:
    type: float
    default: 1.0
    help: L2 正则强度
    min: 0.001
    max: 100.0
needs_dl: false
tensorboard: false
requires_import: sklearn
runnable: true
compute: cpu
persistence: model.pkl（pickle/joblib）；reload→.predict；注意 pin 库版本避免跨版本反序列化失败。
related:
- lasso
- elastic_net
---

## L1 · 定位
L2 正则线性回归。共线性下稳定的可解释基线。

## L2 · 优缺点 & 适用
**✅ 优点**
- 共线性下稳定
- 可解释、训练极快
- 闭式解、无随机性

**⚠️ 缺点**
- 只能线性
- 不做特征选择（系数不为0）
- 需标准化

**适用**：线性回归基线、特征共线性强。
**不适用**：需稀疏/特征选择（用 Lasso）、强非线性。

## L3 · 调参 & 数据要求
**调参策略**：只调 alpha（L2 强度，0.01–100）；特征务必标准化。

| 超参 | 作用 | 默认 | 范围 |
|---|---|---|---|
| `alpha` | L2 正则强度 | 1.0 | 0.001–100.0 |

**数据要求**：必须标准化；NaN 需先处理。

## L4 · 保存本体 & 评价
**保存本体**：model.pkl（pickle/joblib）；reload→.predict；注意 pin 库版本避免跨版本反序列化失败。
**评价图**：预测-实际/残差、系数权重
**算力**：CPU 即可
**可训练**：✅ 已实现训练模板，可直接训练。
