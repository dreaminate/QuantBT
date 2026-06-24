---
term: ic_ir
display: "IC 信息率 (IC-IR)"
aliases:
  - ic_ir
  - ic ir
  - icir
  - 信息率
  - ic 信息率
  - ic 信息比率
  - 因子信息率
level: intermediate
category: factor
formula_latex: "ICIR = \\frac{\\overline{IC}}{\\sigma(IC)}"
unit: "无量纲（截面 IC 序列的均值/标准差）"
typical_range: [-1, 1]
sources:
  - "Grinold, Kahn (2000) Active Portfolio Management, 2nd ed., McGraw-Hill"
  - "Qian, Hua, Sorensen (2007) Quantitative Equity Portfolio Management, Chapman & Hall/CRC"
related:
  - ic
  - rank_ic
  - alpha101_concept
---

## L1 一句话

因子预测能力的稳定性：IC 均值除以 IC 波动。

## L2 公式与例子

$$
ICIR = \frac{\overline{IC}}{\sigma(IC)}
$$

- $IC_t$：第 $t$ 期的截面信息系数（information coefficient），即该期因子值与下一期收益在横截面上的相关系数（普通 IC 用 Pearson，Rank IC 用 Spearman）
- $\overline{IC} = \frac{1}{N}\sum_{t=1}^{N} IC_t$：$N$ 期 IC 序列的均值，衡量"预测平均有多准"
- $\sigma(IC)$：同一 IC 序列的标准差，衡量"预测准不准很不稳定吗"
- 与组合层信息比率（[[information_ratio]]）同名同构，但这里 IC-IR 度量的是**因子信号本身的稳定性**，不是组合超额收益；分母 $\sigma(IC)$ 是 IC 的逐期波动，而非组合跟踪误差

注：分母用**总体标准差**（除以 $N$）还是**样本标准差**（除以 $N-1$）业界两种写法都有，本例取总体标准差，结论需标明口径方可跨表比较。

**算例**：某因子连续 5 期的 Rank IC 序列为 $0.04,\ 0.06,\ 0.02,\ 0.05,\ 0.03$。

- 均值 $\overline{IC} = (0.04+0.06+0.02+0.05+0.03)/5 = 0.20/5 = 0.04$
- 各期对均值的偏差 $0,\ 0.02,\ -0.02,\ 0.01,\ -0.01$；平方和 $= 0.0010$
- 总体方差 $= 0.0010/5 = 0.0002$，故 $\sigma(IC) = \sqrt{0.0002} \approx 0.0141$
- $ICIR = 0.04 / 0.0141 \approx 2.83$

解读：单期 IC 仅 0.04（横截面相关性很弱），但 5 期都为正、波动很小，IC-IR 高达 2.83，说明这个弱信号非常**稳定**。低而稳的因子常优于高而飘的因子——这正是 IC-IR 要捕捉的维度，单看 IC 均值看不出来。

## L3 业界阈值与误区

**阈值参考**（针对**月频、多期滚动**的 IC-IR；样本越短越易虚高，下表为长样本经验区间）：

| IC-IR（月频长样本） | 解读 |
|---|---|
| < 0 | 因子方向与收益反向，信号无效或需反号 |
| 0 ~ 0.3 | 弱，可能与噪声不可区分 |
| 0.3 ~ 0.5 | 可用，多见于单因子（Qian, Hua & Sorensen, 2007 视 0.5 左右为较好单因子量级） |
| 0.5 ~ 1.0 | 较强，通常需多因子合成或较优信号才达到 |
| > 1.0 | 罕见；裸样本出现时**优先怀疑过拟合 / 前视 / 样本过短**，而非真有此强信号 |

> 阈值随频率、市场、样本长度大幅漂移，上表仅为月频长样本的量级参照，**不可**当作硬性合格线。日频 IC-IR 因观测数多、单期 IC 更碎，数值口径与月频不可直接比较。

主动管理基本定律（Fundamental Law of Active Management, Grinold & Kahn, 2000）给出 $IR \approx IC \cdot \sqrt{BR}$，其中 $IC$ 为信息系数、$BR$ 为独立下注次数（breadth）。注意此处 $BR$ 与上文 $N$（IC 时序期数）是完全不同的量：$N$ 数的是 IC 序列有多少**期**观测，$BR$ 数的是组合里有多少**独立下注**，二者不可混为一谈。IC-IR 把"IC 这个输入到底稳不稳"单独拎出来度量——基本定律假设 IC 是个可靠常数，而 IC-IR 正是检验该假设是否成立的工具。

**常见误区**：

1. **把单期高 IC 当作因子好，忽略稳定性** — 单期 IC 受样本噪声影响极大，某一期 IC=0.15 很可能只是运气。Grinold & Kahn (2000) 的基本定律强调，真正驱动主动收益的是 IC 的**期望与稳定性**叠加足够 breadth，而非某一期的高 IC 峰值；评估因子应看多期 IC-IR 而非挑出来的单期 IC。
2. **样本期太短导致 IC-IR 虚高** — IC-IR 是均值/标准差，样本期 $N$ 越短，$\sigma(IC)$ 估计越不稳、越易偏小，IC-IR 越容易冲到不合理的高位。López de Prado (2018, AFML) 反复强调任何"均值除以波动"型比率在短样本下都被向上偏，且多次试验（multiple testing）会进一步抬高最优因子的表观 IC-IR；须配合 deflated 类多重检验校正或更长样本才可信。
3. **IC 计算混入前视偏差使 IC-IR 整体虚高** — IC 是"本期因子"对"下一期收益"的截面相关。若对齐时把未来信息（未来财报、未来价格、未公布的指数调整）误算进当期因子，或用了带幸存者偏差（survivorship bias）的成分股，每一期 IC 都被系统性抬高，整条序列连带 IC-IR 全部失真。López de Prado (2018) 把这类对齐/泄漏错误列为回测可信度的首要杀手。
4. **未区分普通 IC 与 Rank IC 口径就比较 IC-IR** — 普通 IC（Pearson）对异常值与非线性敏感，Rank IC（Spearman）更稳健，两者量级不同。Qian, Hua & Sorensen (2007) 在因子评估中明确区分二者；跨研究比较 IC-IR 时若不统一口径（Pearson vs Spearman、总体 vs 样本标准差、是否年化），数字不可比。

## L4 延伸阅读

- **[[ic]]** — IC-IR 的分子来源：IC 是单期截面相关，度量"某一期预测多准"；IC-IR 在其上加了一层"跨期稳不稳"的除法。只看 IC 均值会漏掉稳定性。
- **[[rank_ic]]** — 用 Spearman 秩相关替代 Pearson 的 IC 变体，对异常值更稳健；实务中 IC-IR 常基于 Rank IC 计算，口径须与阈值表一致。
- **[[alpha101_concept]]** — WorldQuant 式批量公式化因子体系，产出大量候选因子；IC-IR 正是从中筛选与排序、剔除"看着好但不稳"信号的核心评估指标之一。

参考文献：
- Grinold, R. C., & Kahn, R. N. (2000). *Active Portfolio Management* (2nd ed.). McGraw-Hill.
- Qian, E. E., Hua, R. H., & Sorensen, E. H. (2007). *Quantitative Equity Portfolio Management*. Chapman & Hall/CRC.
- López de Prado, M. (2018). *Advances in Financial Machine Learning*. Wiley.
