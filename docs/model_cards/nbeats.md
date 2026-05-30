---
key: nbeats
family: dl
display_name: N-BEATS
tasks:
- regression
- forecasting
description: 纯前馈残差堆叠的时序预测网络，可分解趋势/季节。单变量预测强。
pros:
- 单变量预测 SOTA 级
- 趋势/季节可分解可解释
- 不需循环、训练快
cons:
- 原版偏单变量
- 协变量支持需扩展
- 需较多数据
tuning_tip: num_blocks/hidden_size 定容量；lookback 取预测长度数倍；early stop。
default_params:
  hidden_size: 64
  num_blocks: 3
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
  num_blocks:
    type: int
    default: 3
    help: 残差块数
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
- nhits
- tft
---

## L1 · 定位
纯前馈残差堆叠的时序预测网络，可分解趋势/季节。单变量预测强。

## L2 · 优缺点 & 适用
**✅ 优点**
- 单变量预测 SOTA 级
- 趋势/季节可分解可解释
- 不需循环、训练快

**⚠️ 缺点**
- 原版偏单变量
- 协变量支持需扩展
- 需较多数据

**适用**：单序列多步预测、要可分解解释。
**不适用**：强多变量交互（用 TFT）。

## L3 · 调参 & 数据要求
**调参策略**：num_blocks/hidden_size 定容量；lookback 取预测长度数倍；early stop。

| 超参 | 作用 | 默认 | 范围 |
|---|---|---|---|
| `hidden_size` | 隐藏维度 | 64 | 16–512 |
| `num_blocks` | 残差块数 | 3 | 1–8 |
| `max_epochs` | 训练轮数（demo 用小值跑 CPU） | 20 | 1–500 |
| `learning_rate` | 学习率（先调） | 0.001 | 1e-05–0.1 |
| `batch_size` | 批大小 | 64 | 8–1024 |
| `lookback` | 回看窗口长度（贴预测视野） | 20 | 5–120 |
| `dropout` | dropout 正则 | 0.1 | 0.0–0.6 |

**数据要求**：单变量序列为主；足够历史。

## L4 · 保存本体 & 评价
**保存本体**：model.pt（state_dict + arch config）；reload 按 config 重建网络再 load_state_dict。
**评价图**：学习曲线、趋势/季节分解、预测-实际
**算力**：GPU 推荐(cuda/mps)，CPU 可小规模
**可训练**：✅ 已实现训练模板，可直接训练。
