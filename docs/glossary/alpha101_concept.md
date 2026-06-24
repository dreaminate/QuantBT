---
term: alpha101_concept
display: "WorldQuant Alpha101 体系 (Alpha101)"
aliases:
  - alpha101
  - alpha 101
  - 101 alphas
  - 101 formulaic alphas
  - 公式化因子
  - 阿尔法101
level: intermediate
category: factor
formula_latex: "\\text{Alpha\\#101} = \\frac{close - open}{(high - low) + 0.001}"
unit: "无量纲（横截面排序后的相对强弱）"
typical_range: null
sources:
  - "Kakushadze (2016) 101 Formulaic Alphas, Wilmott Magazine 2016(84): 72–81"
  - "López de Prado (2018) Advances in Financial Machine Learning, Wiley"
related:
  - rank_ic
  - ic
  - ic_ir
  - pbo
---

## L1 一句话

用价量公式批量造的横截面选股信号。

## L2 公式与例子

Alpha101 指 Kakushadze (2016) 公开的 101 条**公式化因子（formulaic alpha）**，每条都是只用日内开高低收量（OHLCV）+ 简单算子（排序 `rank`、滞后 `delay`、相关 `correlation`、时序最值等）拼出的表达式。它们不是单一公式，而是一套**因子构造范式**：每条因子在每个交易日对全市场股票算出一个值，再做横截面排序，得到当日的多空打分。

最简单的 Alpha#101 原文定义：

$$
\text{Alpha\#101} = \frac{close - open}{(high - low) + 0.001}
$$

分母加 $0.001$ 是为防止当日 `high == low`（一字板/停牌）时除零。它度量"当日实体相对全幅的方向占比"——收盘远高于开盘且振幅不大 → 接近 $+1$（强多头）；反之接近 $-1$。

**算例**（某股票当日）：$open=10.00$，$close=10.30$，$high=10.40$，$low=9.95$。

$$
\text{Alpha\#101} = \frac{10.30 - 10.00}{(10.40 - 9.95) + 0.001} = \frac{0.30}{0.451} \approx 0.665
$$

该股当日因子值 $0.665$。把全市场每只股票都算一遍，再按值横截面排序：排名前 N 做多、后 N 做空，即得一个市值/行业中性前的原始多空组合。单条 Alpha101 的预测力很弱（见 L3），实践是把上百条这样的弱信号正交、加权合成。

## L3 业界阈值与误区

**阈值参考**（评估单条公式化因子的横截面预测力，依据 Kakushadze 2016 原文报告与因子研究通行口径）：

| 指标（单条 Alpha101，日频，去成本前） | 量级 | 解读 |
|---|---|---|
| 单期 Rank IC 均值 | 0.01 ~ 0.05 | 公式化因子的常见区间；单条 0.03 已属可用 |
| IC_IR（年化） | 0.3 ~ 0.5 | Kakushadze 2016 报告 101 条等权组合 Sharpe ≈ 2，靠的是数量而非单条强度 |
| 单条因子年化夏普 | < 0.5（多数） | 单看一条几乎不可交易，须组合 |
| 因子间平均相关 | 原文报告 101 条平均成对相关 ≈ 0.064 | 低相关是其价值核心：弱但分散 |

（IC / Rank IC / IC_IR 的定义与阈值见对应词条。）

**常见误区**：

1. **把单条因子当可交易策略**。Kakushadze (2016) 明确指出 101 条**等权组合**年化 Sharpe 约 2，但任意单条因子的 Sharpe 通常远低于 1、去成本后多为负。误把某条"回测好看"的 Alpha 单独上线，几乎必然失败——它的统计意义只在与其余 100 条**正交合成**时才成立。

2. **忽略短持有期带来的换手与冲击成本**。原文这些因子多数持有期极短（数日内），换手率高。López de Prado (2018) 反复强调：未计入交易成本与冲击成本（见 [[slippage]] 概念族）的回测毛收益不可信，公式化因子尤甚——高频短周期信号的毛 Sharpe 在扣成本后可能整体翻负。

3. **101 条 ≈ 101 次试验，过拟合偏差被低估**。从大量价量算子组合里挑出"有效"公式，本质是大规模数据挖掘。López de Prado (2018) 指出试验次数 N 越大，靠运气达到给定回测夏普的概率越高；必须用 PBO / Deflated Sharpe 折减（见 [[pbo]]）。直接拿原始回测 Sharpe 宣称有效，是典型的回测过拟合（backtest overfitting）误区。

4. **直接套用美股因子到 A 股而不重算**。原文因子在美股全市场截面上拟合，A 股的涨跌停板、T+1、停牌机制会破坏 `rank`/`correlation` 等算子的分布假设；López de Prado (2018) 提醒任何跨市场迁移都需重新做样本外验证（见 [[ic]] 的 OOS 评估），照搬系数等于无验证上线。

## L4 延伸阅读

- **[[rank_ic]]** — 评估单条 Alpha101 预测力的首选指标：公式化因子对极端值与非线性敏感，Spearman 秩相关（Rank IC）比 Pearson IC 更稳健。本条是"信号生成"，Rank IC 是"信号体检"。
- **[[ic]]** — IC 是 Rank IC 的 Pearson 版本，衡量因子值与未来收益的线性相关；用于判断单条 Alpha101 是否值得纳入合成池。区别：本条产出因子，IC 度量因子好坏。
- **[[ic_ir]]** — IC_IR = IC 均值 / IC 标准差，衡量因子预测的"稳定性"。Alpha101 的价值正是"单条 IC 低但 IC 稳"，IC_IR 是量化这种稳定性的指标。
- **[[pbo]]** — 从上百条公式里挑因子是大规模试验，过拟合概率高；PBO（过拟合概率）量化"挑出的组合在样本外失效"的频率，是 Alpha101 必须配套的防破产检验。

参考文献：

- Kakushadze, Z. (2016). 101 Formulaic Alphas. *Wilmott Magazine*, 2016(84): 72–81. (亦见 SSRN/arXiv 预印本 arXiv:1601.00991)
- López de Prado, M. (2018). *Advances in Financial Machine Learning*. Hoboken, NJ: Wiley. (Chapters on backtest overfitting, feature importance, and transaction costs.)
