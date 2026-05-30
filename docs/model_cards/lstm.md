---
key: lstm
family: dl
display_name: LSTM 序列模型
tasks:
- regression
- classification
- forecasting
description: LSTM 序列回归/分类（纯 torch 自实现）。建模时序依赖，DL 入门基线。
pros:
- 建模时序依赖/记忆
- 比 TFT 轻、上手快
- 原始序列可直接喂
cons:
- 需较多数据、易过拟合金融噪声
- 训练慢、GPU 更顺
- 可解释性弱、对非平稳敏感
tuning_tip: lr 先调(1e-3)→ hidden_size/num_layers 定容量 → lookback 贴预测视野 → dropout 正则；按 symbol 分组建窗防串味；早停看
  val_loss。
default_params:
  hidden_size: 32
  num_layers: 1
  dropout: 0.1
  max_epochs: 20
  learning_rate: 0.001
  batch_size: 64
  lookback: 20
param_schema:
  hidden_size:
    type: int
    default: 32
    help: 隐藏维度
    min: 8
    max: 256
  num_layers:
    type: int
    default: 1
    help: LSTM 层数
    min: 1
    max: 4
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
- gru
- alstm
- tcn
---

## L1 · 定位
LSTM 序列回归/分类（纯 torch 自实现）。建模时序依赖，DL 入门基线。

## L2 · 优缺点 & 适用
**✅ 优点**
- 建模时序依赖/记忆
- 比 TFT 轻、上手快
- 原始序列可直接喂

**⚠️ 缺点**
- 需较多数据、易过拟合金融噪声
- 训练慢、GPU 更顺
- 可解释性弱、对非平稳敏感

**适用**：单/多标的时序，有足够历史，想建模时间依赖。
**不适用**：纯截面、小样本（用 GBDT）。

## L3 · 调参 & 数据要求
**调参策略**：lr 先调(1e-3)→ hidden_size/num_layers 定容量 → lookback 贴预测视野 → dropout 正则；按 symbol 分组建窗防串味；早停看 val_loss。

| 超参 | 作用 | 默认 | 范围 |
|---|---|---|---|
| `hidden_size` | 隐藏维度 | 32 | 8–256 |
| `num_layers` | LSTM 层数 | 1 | 1–4 |
| `max_epochs` | 训练轮数（demo 用小值跑 CPU） | 20 | 1–500 |
| `learning_rate` | 学习率（先调） | 0.001 | 1e-05–0.1 |
| `batch_size` | 批大小 | 64 | 8–1024 |
| `lookback` | 回看窗口长度（贴预测视野） | 20 | 5–120 |
| `dropout` | dropout 正则 | 0.1 | 0.0–0.6 |

**数据要求**：需足够长序列；特征建议标准化；按 symbol 分组建窗。

## L4 · 保存本体 & 评价
**保存本体**：model.pt（state_dict + arch config）；reload 按 config 重建网络再 load_state_dict。
**评价图**：学习曲线(train/val loss)、预测-实际/残差、TensorBoard 训练过程
**算力**：GPU 推荐(cuda/mps)，CPU 可小规模
**可训练**：✅ 已实现训练模板，可直接训练。
