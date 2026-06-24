---
term: sortino_ratio
display: "索提诺比率 (Sortino Ratio)"
aliases:
  - sortino
  - sortino ratio
  - 索提诺
  - 索提诺比
  - 下行夏普
level: beginner
category: metric
formula_latex: "Sortino = \\frac{E[R_p] - MAR}{\\sigma_d} \\cdot \\sqrt{T}, \\quad \\sigma_d = \\sqrt{\\frac{1}{N}\\sum_{i=1}^{N}\\min(0, R_i - MAR)^2}"
unit: "无量纲（年化）"
typical_range: [-2, 5]
sources:
  - "Sortino, Price (1994) Performance Measurement in a Downside Risk Framework, J. of Investing 3(3)"
  - "Sortino, van der Meer (1991) Downside Risk, J. of Portfolio Management 17(4)"
related:
  - sharpe_ratio
  - calmar_ratio
  - max_drawdown
  - volatility
---

## L1 一句话

只罚下行波动的夏普比，对厚尾更稳。

## L2 公式与例子

$$
Sortino = \frac{E[R_p] - MAR}{\sigma_d} \cdot \sqrt{T}, \quad \sigma_d = \sqrt{\frac{1}{N}\sum_{i=1}^{N}\min(0,\, R_i - MAR)^2}
$$

- $MAR$（Minimum Acceptable Return，最低可接受收益）：下行的"门槛线"，常取 0 或无风险利率；A 股可取 1 年国债 ≈ 2.5%，加密策略多取 0。
- $\sigma_d$（downside deviation，下行偏差）：**只对跌破 $MAR$ 的收益**计平方，再除以**全部 $N$**（Sortino & Price 1994 约定，非只除负样本数），最后开方。
- $T$：年化系数（月频 12，日频 252）。

**算例**：5 个月收益 $[+4\%, -2\%, +3\%, -6\%, +5\%]$，$MAR=0$。
均值 $E[R_p] = 0.008$；只有 $-2\%$、$-6\%$ 是下行，平方和 $=(-0.02)^2+(-0.06)^2 = 0.004$。
$\sigma_d = \sqrt{0.004 / 5} = \sqrt{0.0008} \approx 0.0283$。
单期 $Sortino = 0.008 / 0.0283 \approx 0.28$，年化 $\times\sqrt{12} \approx 0.98$。
（对比：同序列的夏普单期仅 $0.008/0.0417 \approx 0.19$——因为夏普把 $+5\%$ 这种"好波动"也算进了分母。）

## L3 业界阈值与误区

**阈值参考**（仅对**未经多次试验筛选**的单一回测，$MAR=0$ 年化）：

| Sortino 区间 | 解读 |
|---|---|
| < 1.0 | 偏弱，下行风险相对收益偏高 |
| 1.0 ~ 2.0 | 可用 |
| 2.0 ~ 3.0 | 较好 |
| > 3.0 | 须警惕过拟合 / 样本太短，对照夏普与 PBO 复核 |

注：业内常引用 "Sortino > 2 为良好" 的经验线（Sortino & Price, 1994 框架下的实务用法），但该阈值**强依赖 $MAR$ 取值与频率**，跨策略横比前必须对齐这两项。

**常见误区**：

1. **$\sigma_d$ 的分母错用样本数** — 正确做法是平方和除以**全部观测数 $N$**，而非只除"下行样本数"（Sortino & Price, 1994）。若错除负样本数，下行少时 $\sigma_d$ 被严重低估、Sortino 虚高。这是开源实现里最常见的口径分歧。
2. **$MAR$ 不一致就横比** — Sortino 对 $MAR$ 高度敏感：同一策略取 $MAR=0$ 与取 $MAR=R_f$ 数值可差一截。Sortino & van der Meer (1991) 强调下行风险须相对一个明确目标定义；跨策略比较前必须统一 $MAR$ 与年化频率。
3. **样本太短时下行点过少** — 若回测里跌破 $MAR$ 的点只有寥寥几个，$\sigma_d$ 由极少数样本主导、极不稳定，Sortino 会随单个坏点剧烈跳动。Bailey & López de Prado (2014) 关于短样本下风险调整指标偏差膨胀的论述同样适用：短样本的高 Sortino 不可信。
4. **误当成尾部风险指标** — Sortino 只惩罚"低于 $MAR$ 的波动幅度"，并不刻画**最大回撤深度或回撤持续时间**。下行偏差相同的两条曲线，最大回撤可以是 −10% 或 −40%。要管尾部须另看 max drawdown 与 Calmar（Young, 1991 提出 Calmar 即用最大回撤作分母）。

## L4 延伸阅读

- **[[sharpe_ratio]]** — 母概念；夏普用总波动 $\sigma_p$ 作分母，Sortino 只用下行偏差 $\sigma_d$，故对"向上的大波动"不再惩罚，对厚尾/偏态收益更贴合直觉。
- **[[calmar_ratio]]** — 同为下行视角，但 Calmar 用**最大回撤**作分母（一个极端点），Sortino 用**下行波动的均方**（整段分布），前者更怕"最深那一刀"。
- **[[max_drawdown]]** — Sortino 衡量下行波动的"幅度均值"，max drawdown 衡量下行的"最坏单次深度"；两者互补，Sortino 高不代表回撤浅。
- **[[volatility]]** — Sortino 把波动率拆成上行/下行两半、只罚下行那半；理解 volatility（总标准差）是理解下行偏差的前提。

参考文献：
- Sortino, F. A., & van der Meer, R. (1991). Downside Risk. *Journal of Portfolio Management* 17(4).
- Sortino, F. A., & Price, L. N. (1994). Performance Measurement in a Downside Risk Framework. *Journal of Investing* 3(3).
- Young, T. W. (1991). Calmar Ratio: A Smoother Tool. *Futures* 20(1).
- Bailey, D. H., & López de Prado, M. (2014). The Deflated Sharpe Ratio. *Journal of Portfolio Management* 40(5).
