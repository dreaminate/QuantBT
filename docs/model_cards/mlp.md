---
key: mlp
family: dl
display_name: MLP（多层感知机）
tasks:
- regression
- classification
description: 把回看窗摊平喂全连接网络（纯 torch）。不建模时序顺序，作 DL 基线/对照。
pros:
- 简单、训练快
- 可吃任意特征
- DL 入门对照
cons:
- 不建模时序顺序（摊平）
- 对噪声敏感
- 可解释性弱
tuning_tip: lr 先调 → hidden_size/dropout 控容量；lookback 小一点即可；早停。
default_params:
  hidden_size: 64
  dropout: 0.1
  max_epochs: 20
  learning_rate: 0.001
  batch_size: 64
  lookback: 20
param_schema:
  hidden_size:
    type: int
    default: 64
    help: 隐藏维度
    min: 16
    max: 512
  max_epochs:
    type: int
    default: 20
    help: 训练轮数（demo 用小值跑 CPU）
    min: 1
    max: 500
  learning_rate:
    type: float
    default: 0.001
    help: 学习率（先调）
    min: 1.0e-05
    max: 0.1
  batch_size:
    type: int
    default: 64
    help: 批大小
    min: 8
    max: 1024
  lookback:
    type: int
    default: 20
    help: 回看窗口长度（贴预测视野）
    min: 5
    max: 120
  dropout:
    type: float
    default: 0.1
    help: dropout 正则
    min: 0.0
    max: 0.6
needs_dl: true
tensorboard: true
requires_import: torch
runnable: true
compute: gpu
persistence: model.pt（state_dict + arch config）；reload 按 config 重建网络再 load_state_dict。
related:
- lstm
---

## L1 · 定位
把回看窗摊平喂全连接网络（纯 torch）。不建模时序顺序，作 DL 基线/对照。

## L2 · 优缺点 & 适用
**✅ 优点**
- 简单、训练快
- 可吃任意特征
- DL 入门对照

**⚠️ 缺点**
- 不建模时序顺序（摊平）
- 对噪声敏感
- 可解释性弱

**适用**：DL 基线对照、特征本身已含时序信息。
**不适用**：强时序依赖（用 LSTM/TCN）。

## L3 · 调参 & 数据要求
**调参策略**：lr 先调 → hidden_size/dropout 控容量；lookback 小一点即可；早停。

| 超参 | 作用 | 默认 | 范围 |
|---|---|---|---|
| `hidden_size` | 隐藏维度 | 64 | 16–512 |
| `max_epochs` | 训练轮数（demo 用小值跑 CPU） | 20 | 1–500 |
| `learning_rate` | 学习率（先调） | 0.001 | 1e-05–0.1 |
| `batch_size` | 批大小 | 64 | 8–1024 |
| `lookback` | 回看窗口长度（贴预测视野） | 20 | 5–120 |
| `dropout` | dropout 正则 | 0.1 | 0.0–0.6 |

**数据要求**：特征标准化；lookback 摊平。

## L4 · 保存本体 & 评价
**保存本体**：model.pt（state_dict + arch config）；reload 按 config 重建网络再 load_state_dict。
**评价图**：学习曲线、预测-实际/残差、TensorBoard
**算力**：GPU 推荐(cuda/mps)，CPU 可小规模
**可训练**：✅ 已实现训练模板，可直接训练。
