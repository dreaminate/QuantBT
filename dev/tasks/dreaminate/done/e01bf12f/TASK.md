---
uuid: e01bf12fcac34eadb1bd048e218cbe45
title: 回测/训练引擎消费 as_of_known——PIT 双时态全域闭合第一段（B-PIT-1）
status: done
owner: dreaminate
assigned_by: dreaminate
review_status: 1
priority: P0
area: data-pit
source: goal
source_ref: GOAL §11 数据层 + §8/§16（无 PIT 进 confirmatory→拒）+ 施工图 LINE-B W2 + 头号 gap #6
depends_on: []
---

# 回测/训练引擎消费 as_of_known（B-PIT-1）

## Scope [必填]
R28 双时态机制（`field_catalog`/`universe/resolver` 的 `load_panel(as_of_known)`）已建，但**回测/训练引擎零消费**（`codegen.py:25` 直读 raw parquet）= PIT 泄露洞。本卡纯接线：回测/训练面板入口从 raw parquet 切到 `catalog.load_panel(as_of_known=回测时点)`，让 train 段只见 train 时点已知数据。**不重建 PIT 机制**（已 done），只接线 + 对抗证明泄露被堵。

## 文件领地（owner·并发隔离）
`training/backtest_bridge.py` `training/codegen.py` `training/service.py` `main.py:1279`(面板入口透传)。**LINE-B·与 C-CONTRACT(训练出口产 Forecast) 同 codegen 不同函数→B-PIT 先（上游装载入口）**。

## 接线点（file:line·实现复核）[必填]
| 文件 | 位置 | 改什么(扩展不替换) |
|---|---|---|
| `app/backend/app/training/codegen.py:25` | raw `QUANTBT_PANEL_PATH` parquet 注入 | 改 `catalog.load_panel(as_of_known=回测/训练时点)` |
| `app/backend/app/training/backtest_bridge.py` | 面板装载 | 接 PIT as_of 入口 |
| `app/backend/app/main.py:1279` | 面板入口 | 透传 as_of_known |

## 对抗测试设计（种坏门必抓）[必填]
1. **命门**：种 `known_at` 晚于回测 bar 的基本面行喂回测 → 必被剔除（现状直读 raw 会泄露·种坏门必抓）。
2. train 段注入 `known_at` 在 train 窗后的行 → 必剔。
3. 重述点查 2024-02 不能读到 2024-04 修正（resolver 已 done·此处验接线后端到端）。

## 复用 [按需]
`field_catalog.catalog.load_panel(as_of_known=...)`（已 done·**不另建**）· `universe/resolver`（双轴）。

## 红线 [按需]
look-ahead 泄露/未复权价喂成交层即停 · 扩展不替换 · 单一 PIT 机制源不另造。

## 非目标 [按需]
不改 PIT resolver 机制（已 done）；不做多资产 InstrumentSpec（B-INST 另卡）。

## 完成记录（2026-06-26·第一波整合 land·中心 orchestrator）
- 实现 commit `49f8f0b`（分支 `wave1/w2-pit-wiring`）→ 中心 merge `b5cc396`。
- `training/codegen.py` 新 load_pit_panel + 透传 as_of_known 进生成训练脚本（ML/DL 两路），复用 `resolver.as_of_bound` 单一边界·镜像 catalog 折叠语义；向后兼容 None/列缺失 = 逐字裸读。
- 对抗：`test_training_pit_wiring.py` 11 passed·MUT-1（旁路 as-of 守卫退裸读）/MUT-2（不透传 as_of_known）双抓泄露·e2e 真子进程证 codegen→脚本→loader 全链。
- **诚实状态：codegen + POST /codegen 路 ✅；service 层全链 🟡**——本卡接线点列的 `service.py`/`main.py:1279` 全链激活未做（`TrainingRequest` 缺 as_of_known 字段·`_train_ml` 进程内路 PIT 由调用方建 panel 解决）= **follow-on P2**。核心 PIT 消费 seam 已通且对抗证明无泄露。
