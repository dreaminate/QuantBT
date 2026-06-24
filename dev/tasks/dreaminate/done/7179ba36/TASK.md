---
uuid: 7179ba36278e4091a8e29b4d58336525
title: R18 平方根市场冲击 回测成本项（size-aware）+ 容量交叉校验命门
status: done
owner: dreaminate
assigned_by: dreaminate
review_status: 1
priority: P1
area: execution-cost
source: goal-gap
source_ref: GOAL §4「平方根冲击 δ=0.5 窄带（R18）」+ 审计：BacktestCostModel slippage 是平 bps、无 size-aware 冲击
depends_on: []
---

# R18 平方根市场冲击 回测成本项 + 容量交叉校验命门

## Scope [必填]
回测成本模型 `BacktestCostModel` slippage 是常数 bps、随单量不变 → 大单成本被系统性低估、大资金回测过优。
补 R18 **平方根市场冲击**项（impact_frac=Y·σ·(Q/ADV)^δ，δ=0.5 锁定），扩展不替换、**默认关字节不变**。

## 治理（命门·correctness/不假绿灯/红线）[必填]
- **向后兼容**：impact_coef 默认 0=关 → 冲击项恒 0、现有回测**字节不变**（active/默认路径无任何改动）。
- **δ=0.5 锁定**（R18 窄带）；退化（participation≤0/σ≤0/coef≤0）→ 0 安全。
- **不假绿灯**：启用须 volume 列（无则 init raise）；要成交的 symbol ADV 无效（全 0/null/NaN）→ **fail-fast raise**（绝不静默当 0 冲击）；日内数据按**日**聚合 ADV（非每 bar 量，否则高估 √bars/日）。
- **命门交叉校验**：策略在 §3 容量 C 处单期冲击占 AUM 比 == 毛 alpha（绑 `strategy_capacity`，同一 sqrt-impact 物理、单一公式源 `execution/impact.py`）。
- **look-ahead 红线（§7 拍板项处置）**：自估 ADV/σ 用全样本含未来=前视泄露。处置：①default-off 路径无前视（红线在 active 行为守住）②opt-in 自估路径 emit **代码级响亮 warning**（残余文档→代码可见、标用户自负）③提供**显式点位无泄露 ADV/σ 入口**（绕开自估）④mint P2 卡 0f696e56（滚动无泄露自估）。按用户护栏「风险标清用户自负即放行、不把缓解当不交付硬条件」。

## 接线点（file:line，实现复核）[必填]
| 文件 | 位置 | 改什么(扩展不替换) |
|---|---|---|
| app/execution/impact.py | 新建 | `square_root_impact_fraction` 单一公式源 + IMPACT_DELTA=0.5 |
| app/execution/backtest_venue.py | BacktestCostModel +impact_coef/delta/adv/sigma；_precompute_impact_stats(日聚合+显式override+前视warn)；_cost_for_trade(+impact 项 fail-fast) | additive 默认关字节不变 |

## 对抗测试设计（种已知 bug，门必抓）[必填]
1. 向后兼容：impact_coef=0 → 成本与改前逐位相等（现有回测不破）+ 默认关无 warning。
2. √标度：participation×4→frac×2；线性/常数 → 抓。大单单位成本>小单。
3. 命门交叉校验：容量 C 处单期冲击==毛 alpha（绑 strategy_capacity）。
4. 不假绿灯：无 volume→raise；无效 ADV 成交→fail-fast raise；日内按日聚合 ADV。
5. 前视处置：自估 emit 前视 warning；显式 ADV/σ 入口无 warning 且生效。

## 验收一句话 [必填]
平方根冲击成本数学对齐 R18、默认关字节不变、容量交叉校验、无 volume/无效 ADV fail-fast、日内日 ADV、前视红线代码可见标用户自负 + 无泄露入口；全量后端绿、基线不破。

## 完成记录（2026-06-24 · autonomous-loop / D-SQRT-IMPACT-R18）
- **数学先行**：落 `findings/dreaminate/sqrt-impact-backtest-cost.md`（平方根冲击律 + 容量交叉校验命门）。
- **实现（扩展不替换）**：`execution/impact.py` 单一公式源（与 §3 容量同物理）；`BacktestCostModel` 加 impact_coef 默认 0=关字节不变。
- **对抗测试 + 命门**：`test_sqrt_impact_cost.py` **14 passed** + 方法学不变量 **+3**（√标度/容量 C 处==毛 alpha 交叉校验/δ 锁定）。
- **两轮独立复核全闭环**：① Stop-hook codex 顾问 **2 条 P2**（无效 ADV 静默 0→fail-fast raise / 日内 vol.mean 非日 ADV→按日聚合）；② 多透镜评审（4 透镜 + 对抗复核，12 agents）**1 confirmed HIGH**（ADV/σ 全样本前视泄露，命中红线字面但 default-off+诚实标注=§7 拍板项非 stop-work）→ 按用户「标清用户自负即放行」处置：响亮 warning + 显式无泄露入口 + P2 卡，default-off 路径红线守住；数学核心经 4 透镜独立复跑全真。
- **验证**：全量后端 **1530+ passed / 0 failed**（默认关字节不变验证），基线 1518 未破。mint **P2 卡 0f696e56**（滚动无泄露 ADV/σ）+ **e2afc5c2**（三档成本预设接 sqrt-impact + impact 成本归因拆字段）。
- **land main 待用户授权**（不擅自 push/land）。
