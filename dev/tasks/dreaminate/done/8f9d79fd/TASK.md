---
uuid: 8f9d79fd5d73410283a7f9184bfb4ed4
title: 因子收益归因消费侧——per-period 因子收益 provider + ts 对齐器（数学岛接真实物料）
status: done
owner: dreaminate
assigned_by: dreaminate
review_status: 1
priority: P2
area: eval-methodology
source: audit-finding
source_ref: 方法学消费侧 correctness 审计（workflow wm8x329vn）#2 发现（lev 7）；池卡 e4496023（归因接消费侧）的 provider + 对齐前置
depends_on: [ff286f80af1546bfaaea9ce0a6feb9b2]
---

# 因子收益归因消费侧——per-period provider + ts 对齐器

## Scope [必填]
`eval/attribution.py`（done ff286f80·加总恒等式命门）是**纯 math 件、无真实因子收益物料**——审计 #2 指出
若硬接而 factor_returns 由用户/测试手搓，命门恒等式对任意输入恒真，会产出『绿』归因报告但 β/contrib 对应**合成**
因子收益、无外部效度（数学对·输入假=假绿灯）。本卡补**纯工程**两件，把岛接上真实物料（不替用户选因子集）：
① `factor_return_series`：单因子 per-period 多空收益时序 F_t（复用 layered 分位机制，系统真能产因子收益）；
② `attribution_from_series`：ts 键对齐器（消除调用方手工位置对齐的 misalign 假绿灯）。

## 数学先行（F_t 定义 + 对齐正确性 + leak-free）[必填]
- **单因子收益**：F_{k,t} = (1/|QN_t|)Σ_{i∈QN_t} r_{i,t+h} − (1/|Q1_t|)Σ_{i∈Q1_t} r_{i,t+h}
  = 在截面 t 按因子值排序、做多顶分位/做空底分位（组内等权）所得的多空组合 per-period 收益（Grinold-Kahn 分位价差）。
- **leak-free**：r_{i,t+h}=forward_return_h{h} 只经 `attach_forward_returns`（close.shift(−h) 单一滞后源）；分位用
  当期截面因子值（point-in-time）定桶。复用抽出的 `_binned_factor_panel`（与 layered_backtest 同源）→ 杜绝两路口径漂移。
- **对齐正确性**：归因模型 r_t = α + Σ_k β_k F_{k,t} + ε_t 要求逐期 r_t 与 F_{k,t} **同期对齐**。`attribution_from_series`
  按 ts 键取公共期（inner join）、排序后对组合 + 所有因子用**同一 ts 列表**查值 → 行 i 必为同一 ts（OLS 行序无关，但
  跨序列必须同序）；手工 zip 各自插入顺序 = misalign（本卡对齐器根除）。
- **诚实边界（h>1 重叠窗）**：forward 窗重叠 → F_t 序列自相关，归因 β 的**统计精度**打折（标准误低估）；加总恒等式
  与点分解不受影响。收益口径(excess/raw)/回归窗/因子集选择 = 用户方法学，不替拍。

## 治理（护栏·correctness / 不替用户拍板）[必填]
- **不替用户选因子集**：本卡只做「系统能产单因子收益时序 + ts 对齐喂归因」纯工程；选哪些因子进归因集、收益口径、
  回归窗 = 用户方法学（池卡 e4496023 ③ 留）。
- **不假绿灯**：F_t 仅两端分位齐备的截面才出（缺一端不补 0=无价差≠零价差）；诊断口径（无费用/冲击/容量）非可下注业绩，
  与 layered 同源披露。公共 ts<K+2 → 底层 insufficient（不出假 β）。
- **扩展不替换**：`_binned_factor_panel` 是 layered_backtest 的**行为保持**抽取（real-data 回归测试守住），新增函数 additive。

## 接线点（file:line，实现复核）[必填]
| 文件 | 位置 | 改什么(扩展不替换) |
|---|---|---|
| app/backend/app/factor_factory/layered.py | 抽 `_binned_factor_panel`（layered_backtest 改调它·行为保持）+ 加 `_per_period_long_short` + `factor_return_series` | additive+重构 |
| app/backend/app/eval/attribution.py | +`attribution_from_series`（ts 键对齐 → factor_return_attribution） | additive |
| app/backend/tests/test_factor_return_series.py | 新建 5 测试 | 新增 |
| app/backend/tests/test_attribution.py | +4 测试（aligner） | additive |

## 对抗测试设计（种已知 bug，门必抓）+ 变异 [必填]
1. **per-period 多空精确**：合成 binned → F_t=QN_t−Q1_t 逐期已知值 → MUT-A（top 取底分位）→ known_values 红 ✓
2. **缺一端不臆造**：某 ts 只一端分位 → inner join 丢弃（不补 0）。
3. **provider 端到端**：factor_return_series → attribution_from_series 自归因 β≈1、加总恒等式闭合（真数据·equity_cn）。
4. **aligner ts 对齐有牙**：组合逆序+因子乱序插入 → 结果须等 ts-排序基准 → MUT-B'（各自独立顺序取值）→ β 偏离基准、红 ✓
5. **inner join / tuple 序列 / 公共 ts<K+2→insufficient**。
6. **layered 重构行为保持**：test_layered_backtest_buckets real-data 回归绿。

## 验收一句话 [必填]
系统真能产单因子 per-period 多空收益时序 F_t（leak-free·复用 layered 分位）+ ts 键对齐器把归因从「手搓输入」接到真实物料
（消除 misalign 假绿灯·不替用户选因子集）；MUT-A/B' 双变异抓；全量后端 1635 passed / 0 failed。

## 完成记录（2026-06-25 · autonomous-loop / D-ATTRIB-PROVIDER）
- **审计驱动**：correctness 审计 workflow（wm8x329vn）#2——attribution 纯岛、factor_returns 必手搓=输入假绿灯。verifier 确认物料已存在
  （layered 分位权重 + ic.py forward returns），provider 物化是纯工程闭环、不需先定因子集。
- **数学先行**：F_t=分位多空价差（Grinold-Kahn）·leak-free（单一滞后源+point-in-time 分桶）；对齐器按 ts 键对齐根除 misalign。
- **实现（additive+行为保持重构）**：`_binned_factor_panel`（抽取·layered_backtest 改调·real-data 回归守）+ `_per_period_long_short`（纯·
  inner join 仅两端齐备截面）+ `factor_return_series`；`attribution_from_series`（ts 键 inner-join 对齐 → factor_return_attribution）。
- **对抗 + 变异**：provider 5（含纯合成 binned 已知值 + 真数据集成 + 端到端自归因）+ aligner 4。MUT-A（top 取底分位）→ known_values 红；
  MUT-B'（aligner 各自独立顺序）→ ts-对齐 teeth 红（β 偏 1.0+）；均定点反向 edit 后还原（**绝不 git checkout 带未提交改动**）。
  教训：初版 MUT-B（sorted→同列表插入序）未被抓——因 y/factor 用同一 ts 列表、OLS 行序无关=等价变换非 bug；真 misalign 是两侧**各自独立**顺序，
  据此加强测试（组合逆序+因子乱序）才咬住真 bug。
- **验证**：layered 回归 + provider 5 + aligner 4 passed；**全量后端 1635 passed / 13 skipped / 0 failed / 149s**（基线 1626，净 +9）。
  （首跑机器负载高，已知 flaky `test_effect_ledger_concurrent_same_key` 触 120s 兜底——隔离单跑 1.12s 绿、改动不碰 DAG/ledger，证非回归；复跑机器转闲 149s 全绿。）
- **e4496023 残（③·用户方法学）**：组合台/归因报告端点 + 前端贡献瀑布/R²/abstain UI + 因子集选择/收益口径——池卡留。
- **本轮 loop「commit 和 push 自动进行」→ 本地 commit + push 分支**（land main 仍仅用户）。
