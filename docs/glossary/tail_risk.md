---
term: tail_risk
display: "尾部风险 (Tail Risk)"
aliases:
  - tail_risk
  - tail risk
  - 尾部风险
  - 尾端风险
  - 厚尾风险
  - fat tail
level: intermediate
category: risk
formula_latex: "P(R \\le -k\\sigma) \\quad\\text{以及}\\quad \\xi > 0 \\ \\text{(GPD 形状参数)}\\,:\\; P(X > u + y \\mid X > u) = \\left(1 + \\frac{\\xi y}{\\beta}\\right)^{-1/\\xi}"
unit: "概率（无量纲）或损失幅度（与收益同单位）"
typical_range: null
sources:
  - "Mandelbrot (1963) The Variation of Certain Speculative Prices, J. of Business 36(4)"
  - "Taleb (2007) The Black Swan, Random House"
  - "McNeil, Frey, Embrechts (2015) Quantitative Risk Management, Princeton, Chapter 5 (EVT)"
related:
  - var_cvar
  - volatility
  - max_drawdown
---

## L1 一句话

极端罕见损失发生的概率与幅度。

## L2 公式与例子

尾部风险刻画的是收益分布**左尾**（极端亏损区）的概率质量与厚度。两种常用刻画：

（1）正态假设下，损失超过 $k$ 倍标准差的概率为

$$
P(R \le -k\sigma) = \Phi(-k)
$$

（2）现实里收益厚尾，超阈值部分用极值理论（Extreme Value Theory, EVT）的广义帕累托分布（Generalized Pareto Distribution, GPD）拟合，形状参数 $\xi$（读作 xi）决定尾厚：

$$
P(X > u + y \mid X > u) = \left(1 + \frac{\xi\,y}{\beta}\right)^{-1/\xi}
$$

其中 $u$ 是阈值，$\beta>0$ 是尺度参数，$\xi>0$ 表示厚尾（幂律），$\xi=0$ 退化为指数尾（正态/薄尾邻域）。$\xi$ 越大，极端损失衰减越慢。

**算例（正态 vs 厚尾的差距）**：某日频策略日波动 $\sigma=1.5\%$，假设零均值。
- 正态下，单日跌幅超过 $5\sigma=7.5\%$ 的概率 $\Phi(-5)\approx 2.87\times10^{-7}$，约等于每 1 万年一遇（$1/(2.87\times10^{-7})/252\approx1.4$ 万年）。
- 但 1987 年 10 月 19 日美股单日跌约 20%，对当时日波动是 $-20\sigma$ 级事件——正态下概率 $<10^{-88}$，宇宙年龄内都不该发生一次。
- 用 $\xi=0.3$ 的 GPD 拟合实际尾部，同样的 $5\sigma$ 损失概率会被放大到 $10^{-3}\sim10^{-4}$ 量级（具体值依拟合而定），即“百年一遇”而非“万年一遇”。

结论：尾部风险的核心不是“能不能算出一个数”，而是**用错分布会把极端损失低估几个数量级**。

## L3 业界阈值与误区

**阈值参考**（经典文献 / 业内共识）：

| 指标 | 参考阈值 | 含义 | 出处 |
|---|---|---|---|
| 超额峰度 $\gamma_4-3$ | > 0（常见 3~10+） | 正态为 0；金融日收益普遍正超额峰度 = 厚尾 | Cont (2001) |
| GPD 形状 $\xi$ | $\xi>0$ 即厚尾；股指日收益常 0.2~0.4 | $\xi\ge 0.5$ 时方差发散，$\ge1$ 时均值发散 | McNeil et al. (2015) §5 |
| 偏度 $\gamma_3$ | < 0（左偏） | 风险资产多左偏：大跌比大涨更频繁 | Cont (2001) |

（注：尾部风险无单一“典型区间”数值，故 frontmatter `typical_range` 设为 null；应分指标看，见上表。）

**常见误区**：

1. **用波动率/正态 VaR 代替尾部度量**。波动率是二阶矩，对称且只刻画“中心区”波动；正态 VaR 把 $\xi$ 隐含设为 0，系统性低估极端损失。López de Prado (2018, AFML §尾部部分) 与 McNeil et al. (2015, §5) 都强调风险资产应改用 CVaR / EVT 而非正态 VaR。（出处：McNeil, Frey, Embrechts 2015）

2. **把“几千年一遇”当“不会发生”**。Taleb (2007, *The Black Swan*) 指出，正态外推得到的极小概率本身就是错的——黑天鹅频繁出现恰恰说明模型尾部太薄；1987 崩盘、2008、2020-03 都属此类。（出处：Taleb 2007）

3. **样本期太短就宣称“尾部已知”**。极端事件本就稀少，几年回测里可能一次都没出现，于是把无尾误当薄尾。Mandelbrot (1963) 早已指出投机价格服从厚尾（稳定分布族），样本内未见 ≠ 不存在。（出处：Mandelbrot 1963）

4. **忽视尾部相关性（tail dependence）**。平时低相关的资产在崩盘时一起跌，分散化在最需要时失效；这是 2008 的核心教训。EVT 的 copula / 尾相关系数专门刻画此现象，单看普通相关系数会漏掉。（出处：McNeil, Frey, Embrechts 2015, §7 copula）

## L4 延伸阅读

- **[[var_cvar]]** — VaR 给出某置信度下的损失分位点，CVaR（条件 VaR / Expected Shortfall）取该分位点之外的平均损失，正是尾部风险的一个**点估计**；本条更广，涵盖整条左尾的形状（$\xi$、峰度）而不止一个分位数。
- **[[volatility]]** — 波动率是对称的二阶矩，只描述中心波动幅度；尾部风险关注的是分布**末端**的厚度与极端损失，二者不可互相替代（高波动 ≠ 厚尾，反之亦然）。
- **[[max_drawdown]]** — 最大回撤是尾部风险**实际兑现**后在净值曲线上的事后痕迹（路径依赖、已发生的最坏区间）；本条是事前的概率/分布刻画，回撤是其在历史路径上的一次实现。

参考文献：
- Mandelbrot, B. (1963). The Variation of Certain Speculative Prices. *Journal of Business* 36(4): 394–419.
- Cont, R. (2001). Empirical Properties of Asset Returns: Stylized Facts and Statistical Issues. *Quantitative Finance* 1(2): 223–236.
- Taleb, N. N. (2007). *The Black Swan: The Impact of the Highly Improbable*. Random House.
- McNeil, A. J., Frey, R., & Embrechts, P. (2015). *Quantitative Risk Management: Concepts, Techniques and Tools* (Revised ed.). Princeton University Press. Chapters 5 (EVT) and 7 (copulas).
- López de Prado, M. (2018). *Advances in Financial Machine Learning*. Wiley.
