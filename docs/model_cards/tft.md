---
key: tft
family: dl
display_name: TFT 时序融合 Transformer
tasks:
- regression
- forecasting
description: Temporal Fusion Transformer：变量选择 + 门控残差 + 可解释多头注意力，多标的多特征时序的强模型。
pros:
- 变量选择网络可解释特征贡献
- 建模多变量+长短期依赖
- 多步预测强、带分位数
cons:
- 数据量需求大、易过拟合
- 训练最慢、必需 GPU
- 结构复杂、超参多
tuning_tip: hidden_size/attention_head_size 定容量；lr 1e-3；dropout 正则；early stop；Purged 切分防泄露。
default_params:
  hidden_size: 32
  lstm_layers: 1
  attention_head_size: 4
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
  lstm_layers:
    type: int
    default: 1
    help: LSTM 层数
    min: 1
    max: 4
  attention_head_size:
    type: int
    default: 4
    help: 注意力头数
    min: 1
    max: 8
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
- transformer
- alstm
---

## L1 · 定位
Temporal Fusion Transformer：变量选择 + 门控残差 + 可解释多头注意力，多标的多特征时序的强模型。

## L2 · 优缺点 & 适用
**✅ 优点**
- 变量选择网络可解释特征贡献
- 建模多变量+长短期依赖
- 多步预测强、带分位数

**⚠️ 缺点**
- 数据量需求大、易过拟合
- 训练最慢、必需 GPU
- 结构复杂、超参多

**适用**：多标的多特征时序、需要可解释贡献与多步预测。
**不适用**：小样本、想快速出基线。

## L3 · 调参 & 数据要求
**调参策略**：hidden_size/attention_head_size 定容量；lr 1e-3；dropout 正则；early stop；Purged 切分防泄露。

| 超参 | 作用 | 默认 | 范围 |
|---|---|---|---|
| `hidden_size` | 隐藏维度 | 32 | 8–256 |
| `lstm_layers` | LSTM 层数 | 1 | 1–4 |
| `attention_head_size` | 注意力头数 | 4 | 1–8 |
| `max_epochs` | 训练轮数（demo 用小值跑 CPU） | 20 | 1–500 |
| `learning_rate` | 学习率（先调） | 0.001 | 1e-05–0.1 |
| `batch_size` | 批大小 | 64 | 8–1024 |
| `lookback` | 回看窗口长度（贴预测视野） | 20 | 5–120 |
| `dropout` | dropout 正则 | 0.1 | 0.0–0.6 |

**数据要求**：数据量需求大；多特征；按 symbol 分组。

## L4 · 保存本体 & 评价
**保存本体**：model.pt（state_dict + arch config）；reload 按 config 重建网络再 load_state_dict。
**评价图**：学习曲线、变量选择权重、分位数预测、TensorBoard
**算力**：GPU 推荐(cuda/mps)，CPU 可小规模
**可训练**：✅ 已实现训练模板，可直接训练。
