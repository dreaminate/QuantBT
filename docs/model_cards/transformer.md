---
key: transformer
family: dl
display_name: Transformer 编码器
tasks:
- regression
- forecasting
description: 自注意力编码器（纯 torch）。全局依赖建模强，数据足时上限高。
pros:
- 自注意力捕捉全局依赖
- 并行训练
- 数据足时上限高
cons:
- 数据需求最大、最易过拟合
- 训练最重、强烈需 GPU
- 超参敏感
tuning_tip: n_heads 整除 hidden_size；lr 小(1e-3~1e-4)+warmup 心态；dropout 大些；早停严格；务必 Purged 切分。
default_params:
  hidden_size: 32
  num_layers: 2
  n_heads: 4
  dropout: 0.1
  max_epochs: 20
  learning_rate: 0.001
  batch_size: 64
  lookback: 20
param_schema:
  hidden_size:
    type: int
    default: 32
    help: 模型维度(需被 n_heads 整除)
    min: 16
    max: 256
  num_layers:
    type: int
    default: 2
    help: 编码层数
    min: 1
    max: 6
  n_heads:
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
- alstm
- tft
---

## L1 · 定位
自注意力编码器（纯 torch）。全局依赖建模强，数据足时上限高。

## L2 · 优缺点 & 适用
**✅ 优点**
- 自注意力捕捉全局依赖
- 并行训练
- 数据足时上限高

**⚠️ 缺点**
- 数据需求最大、最易过拟合
- 训练最重、强烈需 GPU
- 超参敏感

**适用**：数据充足的时序、需要全局依赖建模。
**不适用**：小样本（必过拟合）、纯截面。

## L3 · 调参 & 数据要求
**调参策略**：n_heads 整除 hidden_size；lr 小(1e-3~1e-4)+warmup 心态；dropout 大些；早停严格；务必 Purged 切分。

| 超参 | 作用 | 默认 | 范围 |
|---|---|---|---|
| `hidden_size` | 模型维度(需被 n_heads 整除) | 32 | 16–256 |
| `num_layers` | 编码层数 | 2 | 1–6 |
| `n_heads` | 注意力头数 | 4 | 1–8 |
| `max_epochs` | 训练轮数（demo 用小值跑 CPU） | 20 | 1–500 |
| `learning_rate` | 学习率（先调） | 0.001 | 1e-05–0.1 |
| `batch_size` | 批大小 | 64 | 8–1024 |
| `lookback` | 回看窗口长度（贴预测视野） | 20 | 5–120 |
| `dropout` | dropout 正则 | 0.1 | 0.0–0.6 |

**数据要求**：数据量需求大；特征标准化；按 symbol 分组。

## L4 · 保存本体 & 评价
**保存本体**：model.pt（state_dict + arch config）；reload 按 config 重建网络再 load_state_dict。
**评价图**：学习曲线、注意力图、预测-实际、TensorBoard
**算力**：GPU 推荐(cuda/mps)，CPU 可小规模
**可训练**：✅ 已实现训练模板，可直接训练。
