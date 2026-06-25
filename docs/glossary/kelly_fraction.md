---
term: kelly_fraction
display: "Kelly 仓位 (Kelly Fraction · Kelly Criterion)"
aliases:
  - kelly_fraction
  - kelly criterion
  - kelly
  - 凯利公式
  - 凯利准则
  - 凯利仓位
  - 半凯利
level: intermediate
category: portfolio
formula_latex: "f^* = \\frac{bp - q}{b} \\qquad f^* = \\frac{\\mu}{\\sigma^2}"
unit: "占资本比例（可 > 1 表示杠杆）"
typical_range: [0, 1]
sources:
  - "Kelly (1956) A New Interpretation of Information Rate, Bell System Technical Journal 35(4)"
  - "Thorp (2006) The Kelly Criterion in Blackjack, Sports Betting, and the Stock Market (Handbook of Asset and Liability Management, Vol. 1)"
  - "MacLean, Thorp, Ziemba (2011) The Kelly Capital Growth Investment Criterion, World Scientific"
related:
  - mean_variance
  - risk_parity
  - max_drawdown
  - volatility
---

## L1 一句话

让长期复利增长最快的下注比例。

## L2 公式与例子

Kelly 给的是使**对数财富期望**（即长期几何增长率）最大的单次投入比例，而不是最大化单期算术收益。

离散赌局形式（赢概率 $p$、输概率 $q=1-p$、净赔率 $b$，即每投 1 单位赢则得 $b$）：

$$
f^* = \frac{bp - q}{b} = p - \frac{q}{b}
$$

连续投资形式（Thorp 2006，超额收益均值 $\mu$、方差 $\sigma^2$，近似正态）：

$$
f^* = \frac{\mu}{\sigma^2}
$$

**算例 1（赌局）**：胜率 $p=0.55$，$q=0.45$，赔率 $b=1$（一赔一）。
$f^* = (1 \times 0.55 - 0.45)/1 = 0.10$ → 每次押本金的 **10%**。
押更多（如 20%）长期几何增长率反而下降，押 100% 则迟早归零。

**算例 2（投资）**：某资产年化超额收益 $\mu=8\%$、年化波动 $\sigma=20\%$（$\sigma^2=0.04$）。
$f^* = 0.08 / 0.04 = 2.0$ → 全 Kelly 要求 **2 倍杠杆**。
这暴露了 Kelly 的危险：单资产 Sharpe 仅 $0.08/0.20=0.4$，全 Kelly 却要上 2x，回撤会非常剧烈，故业界普遍用「半 Kelly」（见 L3）。

## L3 业界阈值与误区

**阈值参考**（下注比例相对全 Kelly $f^*$）：

| 投入档位 | 几何增长率 | 波动 / 回撤 | 适用场景 |
|---|---|---|---|
| 全 Kelly ($f^*$) | 最高（理论最优） | 最大 | 仅当 $\mu,\sigma$ 估得极准 |
| 半 Kelly ($0.5f^*$) | 约为最优的 **75%** | 约为全 Kelly 波动的 **50%** | 业界主流默认 |
| 1/4 Kelly ($0.25f^*$) | 约为最优的 **44%** | 更低 | 参数不确定性大时 |
| 超 Kelly ($>f^*$) | **下降** | 暴涨，长期破产概率→1 | 应禁止 |

半 Kelly「保住约 3/4 增长、砍掉一半波动」来自对数增长曲线在 $f^*$ 附近近似二次、关于 $f^*$ 对称的性质（MacLean, Thorp & Ziemba, 2011）。

**常见误区**：

1. **把参数当已知真值（estimation error 致命）**。$f^*=\mu/\sigma^2$ 对 $\mu$ 的估计误差极敏感：$\mu$ 高估一倍，$f^*$ 就翻倍，直接把人推到「超 Kelly」破产区。这是实务里用半/1-4 Kelly 而非全 Kelly 的首要原因（MacLean, Thorp & Ziemba, 2011，引言对 over-betting 风险的论述）。

2. **误以为 Kelly 最大化期望收益**。Kelly 最大化的是 $E[\ln(\text{财富})]$（长期几何增长），不是单期算术期望 $E[\text{收益}]$。最大化算术期望会把你导向全押单一最高期望标的，方差吃掉复利、长期反而更穷（Kelly, 1956；Samuelson 对此有长期争论，但「最大化对数财富 ≠ 最大化算术期望」这一区分本身无争议）。

3. **在重尾 / 非正态分布下硬套 $\mu/\sigma^2$**。$f^*=\mu/\sigma^2$ 是对数效用 + 近正态下的近似；当收益厚尾、负偏（如加密、卖期权策略）时，方差严重低估真实毁灭风险，按公式算出的 $f^*$ 会系统性偏高（Thorp, 2006 明确指出该式为局部近似，重尾下需直接对实际分布做对数财富最优化）。

4. **忽略「同时下多注」的相关性**。多策略 / 多资产并行时不能各自独立套 Kelly 再相加；正确做法是对组合联合分布求多元 Kelly（等价于均值方差里加一项），高相关持仓会让独立加总严重超注（MacLean, Thorp & Ziemba, 2011）。

5. **把 $f^*>1$ 当成「信号强、随便上杠杆」**。$f^*>1$ 只说明在你（很可能高估的）$\mu,\sigma$ 下数学最优是杠杆，并未计入融资成本、爆仓线、流动性与跳空；真钱里 $f^*>1$ 应视为「该重新质疑参数估计」的警报，而非加杠杆的许可。

## L4 延伸阅读

- **[[mean_variance]]** — 均值方差最大化「均值 − λ·方差」的单期效用；Kelly 最大化对数财富的长期几何增长。二者在近正态下数学相通（半 Kelly ≈ 某个风险厌恶 λ 下的 MV 解），但 Kelly 的目标是多期复利而非单期权衡。
- **[[risk_parity]]** — 风险平价按风险贡献等分配，不依赖 $\mu$ 估计；Kelly 高度依赖 $\mu$。当你不信自己的收益预测时风险平价更稳，信时 Kelly 给的是增长最优。
- **[[max_drawdown]]** — Kelly 的核心代价就在回撤：全 Kelly 的理论最大回撤可逼近 50% 量级，半 Kelly 是用「砍一半增长波动」换更浅回撤。看 Kelly 档位选择时必须连着看 MDD。
- **[[volatility]]** — 连续形式 $f^*=\mu/\sigma^2$ 里 $\sigma$ 是分母关键项；波动估计偏差会平方级放大到仓位上，是 Kelly 实务失败的主要来源之一。

参考文献：
- Kelly, J. L. (1956). A New Interpretation of Information Rate. *Bell System Technical Journal* 35(4): 917–926.
- Thorp, E. O. (2006). The Kelly Criterion in Blackjack, Sports Betting, and the Stock Market. In *Handbook of Asset and Liability Management*, Vol. 1, North-Holland: 385–428.
- MacLean, L. C., Thorp, E. O., & Ziemba, W. T. (Eds.). (2011). *The Kelly Capital Growth Investment Criterion: Theory and Practice*. World Scientific.
