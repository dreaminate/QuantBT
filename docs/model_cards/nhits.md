---
key: nhits
family: dl
display_name: N-HiTS
tasks:
- regression
- forecasting
description: N-BEATS 的多尺度升级：分层池化 + 多频率，长程预测更快更准。
pros:
- 长程预测准、比 N-BEATS 省算力
- 多尺度分层
- 训练快
cons:
- 单变量为主
- 实现较复杂
- 需较多数据
tuning_tip: hidden_size 定容量；lookback 取长一些以利多尺度池化；early stop。
default_params:
  hidden_size: 64
  max_epochs: 20
  learning_rate: 0.001
  batch_size: 64
  lookback: 30
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
    default: 30
    help: 回看窗口
    min: 5
    max: 200
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
- nbeats
---

## L1 · 定位
N-BEATS 的多尺度升级：分层池化 + 多频率，长程预测更快更准。

## L2 · 优缺点 & 适用
**✅ 优点**
- 长程预测准、比 N-BEATS 省算力
- 多尺度分层
- 训练快

**⚠️ 缺点**
- 单变量为主
- 实现较复杂
- 需较多数据

**适用**：长程多步预测。
**不适用**：强多变量交互。

## L3 · 调参 & 数据要求
**调参策略**：hidden_size 定容量；lookback 取长一些以利多尺度池化；early stop。

| 超参 | 作用 | 默认 | 范围 |
|---|---|---|---|
| `hidden_size` | 隐藏维度 | 64 | 16–512 |
| `max_epochs` | 训练轮数（demo 用小值跑 CPU） | 20 | 1–500 |
| `learning_rate` | 学习率（先调） | 0.001 | 1e-05–0.1 |
| `batch_size` | 批大小 | 64 | 8–1024 |
| `lookback` | 回看窗口 | 30 | 5–200 |
| `dropout` | dropout 正则 | 0.1 | 0.0–0.6 |

**数据要求**：单变量为主；长历史。

## L4 · 保存本体 & 评价
**保存本体**：model.pt（state_dict + arch config）；reload 按 config 重建网络再 load_state_dict。
**评价图**：学习曲线、多尺度分解、预测-实际
**算力**：GPU 推荐(cuda/mps)，CPU 可小规模
**可训练**：✅ 已实现训练模板，可直接训练。
