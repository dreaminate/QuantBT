---
key: xgboost
family: ml
display_name: XGBoost
tasks:
- classification
- regression
description: 梯度提升树（level-wise）。与 LightGBM 互为对照，正则更强。排序任务暂交给 LightGBM。
pros:
- 正则手段多（gamma/min_child_weight/L1L2）抗过拟合可控
- 截面特征上开箱即强
- 原生处理缺失值
- 确定性好（固定 seed）
cons:
- 超参多、调不好易翻车
- 不建模时序
- 类别极不平衡需调 scale_pos_weight
tuning_tip: ①n_estimators 高 + 早停 → ②定容量(learning_rate + max_depth 3–8) → ③抗过拟合(subsample/colsample 0.7–0.9)
  → ④精修(min_child_weight/gamma/reg_lambda)。
default_params:
  n_estimators: 200
  learning_rate: 0.05
  max_depth: 6
param_schema:
  n_estimators:
    type: int
    default: 200
    help: 树的数量
    min: 10
    max: 2000
  learning_rate:
    type: float
    default: 0.05
    help: 学习率
    min: 0.001
    max: 0.5
  max_depth:
    type: int
    default: 6
    help: 树深
    min: 1
    max: 16
  subsample:
    type: float
    default: 1.0
    help: 行采样比例
    min: 0.3
    max: 1.0
  colsample_bytree:
    type: float
    default: 1.0
    help: 列采样比例
    min: 0.3
    max: 1.0
needs_dl: false
tensorboard: false
requires_import: xgboost
runnable: true
compute: cpu
persistence: model.pkl（pickle/joblib）；reload→.predict；注意 pin 库版本避免跨版本反序列化失败。
related:
- lgbm
- catboost
---

## L1 · 定位
梯度提升树（level-wise）。与 LightGBM 互为对照，正则更强。排序任务暂交给 LightGBM。

## L2 · 优缺点 & 适用
**✅ 优点**
- 正则手段多（gamma/min_child_weight/L1L2）抗过拟合可控
- 截面特征上开箱即强
- 原生处理缺失值
- 确定性好（固定 seed）

**⚠️ 缺点**
- 超参多、调不好易翻车
- 不建模时序
- 类别极不平衡需调 scale_pos_weight

**适用**：横截面选股、与 LightGBM 做模型对照、需要更强正则时。
**不适用**：原始序列、极小样本。

## L3 · 调参 & 数据要求
**调参策略**：①n_estimators 高 + 早停 → ②定容量(learning_rate + max_depth 3–8) → ③抗过拟合(subsample/colsample 0.7–0.9) → ④精修(min_child_weight/gamma/reg_lambda)。

| 超参 | 作用 | 默认 | 范围 |
|---|---|---|---|
| `n_estimators` | 树的数量 | 200 | 10–2000 |
| `learning_rate` | 学习率 | 0.05 | 0.001–0.5 |
| `max_depth` | 树深 | 6 | 1–16 |
| `subsample` | 行采样比例 | 1.0 | 0.3–1.0 |
| `colsample_bytree` | 列采样比例 | 1.0 | 0.3–1.0 |

**数据要求**：无需标准化；NaN 原生处理；截面对齐。

## L4 · 保存本体 & 评价
**保存本体**：model.pkl（pickle/joblib）；reload→.predict；注意 pin 库版本避免跨版本反序列化失败。
**评价图**：特征重要度(gain)、ROC/PR(分类)、预测-实际/残差(回归)、分fold IC
**算力**：CPU 即可
**可训练**：✅ 已实现训练模板，可直接训练。
