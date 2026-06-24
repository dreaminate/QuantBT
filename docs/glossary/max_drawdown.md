---
term: max_drawdown
display: "最大回撤 (Max Drawdown · MDD)"
aliases:
  - max_drawdown
  - mdd
  - max drawdown
  - 最大回撤
  - 回撤
level: beginner
category: metric
formula_latex: "MDD = \\min_{t \\in [0, T]} \\left( \\frac{V_t}{\\max_{s \\le t} V_s} - 1 \\right)"
unit: "百分比（≤ 0）"
typical_range: [-1, 0]
sources:
  - "Magdon-Ismail, Atiya (2004) Maximum Drawdown, Risk Magazine 17(10)"
  - "Young (1991) Calmar Ratio: A Smoother Tool, Futures Magazine"
  - "Lopez de Prado (2018) Advances in Financial Machine Learning, Wiley, ch.3"
related:
  - calmar_ratio
  - volatility
  - tail_risk
  - var_cvar
  - kelly_fraction
---

## L1 一句话

从历史峰值跌到谷底的最大亏损幅度。

## L2 公式与例子

$$
MDD = \min_{t \in [0, T]} \left( \frac{V_t}{\max_{s \le t} V_s} - 1 \right)
$$

- $V_t$：$t$ 时刻的账户净值（equity）；$\max_{s \le t} V_s$：截至 $t$ 的历史最高净值（running peak，又称水位线 high-water mark）
- 回撤 (drawdown) = 当前净值 / 历史最高 − 1，恒 ≤ 0；MDD 取整段最深的那一次
- 它是**路径依赖**的：只看起止两点算不出来，必须逐点滚动峰值

**算例**：净值序列 $V = [100, 120, 90, 110, 130, 78]$。

| 时点 | 净值 $V_t$ | 滚动峰值 | 回撤 |
|---|---|---|---|
| 1 | 100 | 100 | 0% |
| 2 | 120 | 120 | 0% |
| 3 | 90 | 120 | −25.0% |
| 4 | 110 | 120 | −8.3% |
| 5 | 130 | 130 | 0% |
| 6 | 78 | 130 | **−40.0%** |

$MDD = 78 / 130 - 1 = -0.40 = -40\%$。注意第 6 点的峰值是 130（不是起点 100），所以最深回撤发生在最后一段。

## L3 业界阈值与误区

**阈值参考**（按策略类别的经验区间，非硬性合格线）：

| 策略类型 | 可接受 MDD 量级 | 备注 |
|---|---|---|
| 低波动多空 / 市场中性 | −5% ~ −15% | 超出需查杠杆与对冲失效 |
| 股票多头 / CTA 趋势 | −15% ~ −30% | 趋势策略天然在震荡市吃回撤 |
| 单一资产 buy-and-hold | −30% ~ −60% | 沪深300 2007–2008 实际回撤约 −72% |

阈值随策略与杠杆变化很大，没有跨类别的统一"安全线"，应配合恢复期与 Calmar 比率一起读 (Young, 1991)。

**常见误区**：

1. **把 MDD 当成"最坏情况已知"** — MDD 只是**已实现样本**里的最深回撤，是历史最小值的有偏估计，会随样本变长而单调变深；未来回撤可以更深。López de Prado (2018, ch.3) 强调单一回测的极值统计量不能外推为风险上界。
2. **忽略回撤持续期 (drawdown duration)** — 同样 −20% 的 MDD，3 个月回本和 3 年回本对资金方是两种体验。Magdon-Ismail & Atiya (2004) 区分了回撤"深度"与"时长"两个维度，只报深度会漏掉煎熬期风险。
3. **杠杆下的非线性放大** — MDD 不随杠杆线性缩放：2 倍杠杆遇到 −50% 回撤即触及强平归零，而非简单翻倍。这正是 Kelly (1956) 仓位框架要把回撤纳入约束、实务常用"半 Kelly"压低回撤的原因。
4. **多次试验偏差选出的小回撤** — 在上百组参数里挑 MDD 最浅的那组，回测 MDD 会被严重低估；它与夏普膨胀同源，需用 PBO / 样本外验证交叉确认，不能单看回测数字。

## L4 延伸阅读

- **[[calmar_ratio]]** — 年化收益 ÷ |MDD| 的比值；MDD 是它的分母。上例 20% 年化 ÷ 40% 回撤 = 0.5。本条是绝对幅度，Calmar 是性价比。
- **[[volatility]]** — 波动率是收益的二阶矩（对称、与路径无关），MDD 是路径依赖的单边极值；低波动策略仍可能因连续小亏累积出大回撤。
- **[[tail_risk]]** — 尾部风险刻画极端损失的整体分布，MDD 是该尾部在净值路径上的一次具体实现（最深的那次）。
- **[[var_cvar]]** — VaR/CVaR 是**单期**给定置信度的损失分位，MDD 是**跨期累计**的峰谷损失；前者问"一天最多亏多少"，后者问"这段路最深亏多少"。
- **[[kelly_fraction]]** — Kelly 给出增长最优仓位，但全 Kelly 的理论回撤极深；实务用回撤约束把仓位压到半 Kelly 以下，MDD 是这里的核心约束量。

参考文献：
- Magdon-Ismail, M., & Atiya, A. F. (2004). Maximum Drawdown. *Risk Magazine* 17(10).
- Young, T. W. (1991). Calmar Ratio: A Smoother Tool. *Futures Magazine*.
- Kelly, J. L. (1956). A New Interpretation of Information Rate. *Bell System Technical Journal* 35(4).
- López de Prado, M. (2018). *Advances in Financial Machine Learning*. Wiley, ch.3.
