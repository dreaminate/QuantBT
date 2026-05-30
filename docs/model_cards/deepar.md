---
key: deepar
family: dl
display_name: DeepAR
tasks:
- regression
- forecasting
description: 自回归 RNN 概率预测：LSTM 输出 μ/σ 分布参数（点预测用 μ，σ 头保留供区间预测），适合带不确定性的多序列预测。
pros:
- 概率预测（给区间/分位数）
- 多序列联合学习
- 适合不确定性度量
cons:
- 训练较慢
- 需较多数据
- 点估计未必优于判别模型
tuning_tip: hidden_size/num_layers 定容量；lr 1e-3；early stop。（当前实现点预测用 μ 头。）
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
- tft
---

## L1 · 定位
自回归 RNN 概率预测：LSTM 输出 μ/σ 分布参数（点预测用 μ，σ 头保留供区间预测），适合带不确定性的多序列预测。

## L2 · 优缺点 & 适用
**✅ 优点**
- 概率预测（给区间/分位数）
- 多序列联合学习
- 适合不确定性度量

**⚠️ 缺点**
- 训练较慢
- 需较多数据
- 点估计未必优于判别模型

**适用**：需要预测区间/风险度量、多序列。
**不适用**：只要点估计且追求最高精度。

## L3 · 调参 & 数据要求
**调参策略**：hidden_size/num_layers 定容量；lr 1e-3；early stop。（当前实现点预测用 μ 头。）

| 超参 | 作用 | 默认 | 范围 |
|---|---|---|---|
| `hidden_size` | 隐藏维度 | 32 | 8–256 |
| `num_layers` | LSTM 层数 | 1 | 1–4 |
| `max_epochs` | 训练轮数（demo 用小值跑 CPU） | 20 | 1–500 |
| `learning_rate` | 学习率（先调） | 0.001 | 1e-05–0.1 |
| `batch_size` | 批大小 | 64 | 8–1024 |
| `lookback` | 回看窗口长度（贴预测视野） | 20 | 5–120 |
| `dropout` | dropout 正则 | 0.1 | 0.0–0.6 |

**数据要求**：多序列；足够历史。

## L4 · 保存本体 & 评价
**保存本体**：model.pt（state_dict + arch config）；reload 按 config 重建网络再 load_state_dict。
**评价图**：学习曲线、预测区间、覆盖率校准
**算力**：GPU 推荐(cuda/mps)，CPU 可小规模
**可训练**：✅ 已实现训练模板，可直接训练。
