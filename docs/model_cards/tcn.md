---
key: tcn
family: dl
display_name: TCN 时序卷积
tasks:
- regression
- forecasting
description: 因果膨胀卷积网络（纯 torch）。并行训练快，长感受野，时序强基线。
pros:
- 并行快（卷积）
- 膨胀卷积长感受野
- 训练稳定、梯度好
cons:
- 感受野受层数/核限制
- 需调结构
- 需较多数据
tuning_tip: num_layers 决定感受野(2^L)；kernel_size 3–5；lr 先调；dropout 正则；早停。
default_params:
  hidden_size: 32
  num_layers: 2
  kernel_size: 3
  dropout: 0.1
  max_epochs: 20
  learning_rate: 0.001
  batch_size: 64
  lookback: 20
param_schema:
  hidden_size:
    type: int
    default: 32
    help: 通道数
    min: 8
    max: 256
  num_layers:
    type: int
    default: 2
    help: 卷积层数(感受野 2^L)
    min: 1
    max: 6
  kernel_size:
    type: int
    default: 3
    help: 卷积核
    min: 2
    max: 7
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
- transformer
---

## L1 · 定位
因果膨胀卷积网络（纯 torch）。并行训练快，长感受野，时序强基线。

## L2 · 优缺点 & 适用
**✅ 优点**
- 并行快（卷积）
- 膨胀卷积长感受野
- 训练稳定、梯度好

**⚠️ 缺点**
- 感受野受层数/核限制
- 需调结构
- 需较多数据

**适用**：时序建模、想要比 RNN 快且稳定。
**不适用**：纯截面、小样本。

## L3 · 调参 & 数据要求
**调参策略**：num_layers 决定感受野(2^L)；kernel_size 3–5；lr 先调；dropout 正则；早停。

| 超参 | 作用 | 默认 | 范围 |
|---|---|---|---|
| `hidden_size` | 通道数 | 32 | 8–256 |
| `num_layers` | 卷积层数(感受野 2^L) | 2 | 1–6 |
| `kernel_size` | 卷积核 | 3 | 2–7 |
| `max_epochs` | 训练轮数（demo 用小值跑 CPU） | 20 | 1–500 |
| `learning_rate` | 学习率（先调） | 0.001 | 1e-05–0.1 |
| `batch_size` | 批大小 | 64 | 8–1024 |
| `lookback` | 回看窗口长度（贴预测视野） | 20 | 5–120 |
| `dropout` | dropout 正则 | 0.1 | 0.0–0.6 |

**数据要求**：需足够长序列；特征标准化；按 symbol 分组。

## L4 · 保存本体 & 评价
**保存本体**：model.pt（state_dict + arch config）；reload 按 config 重建网络再 load_state_dict。
**评价图**：学习曲线、预测-实际/残差、TensorBoard
**算力**：GPU 推荐(cuda/mps)，CPU 可小规模
**可训练**：✅ 已实现训练模板，可直接训练。
