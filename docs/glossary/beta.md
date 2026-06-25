---
term: beta
display: "市场 Beta (Market Beta · β)"
aliases:
  - beta
  - market beta
  - 贝塔
  - 市场贝塔
  - 系统性风险系数
level: beginner
category: metric
formula_latex: "\\beta_i = \\frac{\\mathrm{Cov}(R_i, R_m)}{\\mathrm{Var}(R_m)} = \\rho_{i,m}\\,\\frac{\\sigma_i}{\\sigma_m}"
unit: "无量纲（斜率）"
typical_range: [-0.5, 2]
sources:
  - "Sharpe (1964) Capital Asset Prices: A Theory of Market Equilibrium under Conditions of Risk, J. of Finance 19(3)"
  - "Fama, French (1992) The Cross-Section of Expected Stock Returns, J. of Finance 47(2)"
  - "Frazzini, Pedersen (2014) Betting Against Beta, J. of Financial Economics 111(1)"
related:
  - alpha
  - volatility
  - sharpe_ratio
  - mean_variance
---

## L1 一句话

资产收益相对大盘波动的敏感度。

## L2 公式与例子

Beta（贝塔，β）是资产收益 $R_i$ 对市场收益 $R_m$ 做回归得到的斜率，衡量市场每涨跌 1%、该资产平均跟着动多少：

$$
\beta_i = \frac{\mathrm{Cov}(R_i, R_m)}{\mathrm{Var}(R_m)} = \rho_{i,m}\,\frac{\sigma_i}{\sigma_m}
$$

- $\mathrm{Cov}(R_i, R_m)$：资产与市场收益的协方差
- $\mathrm{Var}(R_m)$：市场收益方差
- $\rho_{i,m}$：资产与市场的相关系数；$\sigma_i, \sigma_m$：各自波动率

**算例**：某股票月收益与大盘月收益，相关系数 $\rho = 0.6$，股票月波动率 $\sigma_i = 8\%$，大盘月波动率 $\sigma_m = 4\%$。
$$
\beta = 0.6 \times \frac{8\%}{4\%} = 0.6 \times 2 = 1.2
$$
解读：β=1.2 表示大盘每涨 1%，该股票平均涨 1.2%（系统性部分）；大盘跌 1% 平均跌 1.2%。注意 β 只解释了波动里相关的那一块——本例 $\rho^2 = 0.36$，即仅 36% 的方差由市场驱动，其余 64% 是个股特有（非系统性）风险，可被分散掉。

## L3 业界阈值与误区

**阈值参考**（教科书与实证共识）：

| β 区间 | 解读 |
|---|---|
| β > 1 | 进攻型：波动放大于大盘（多数高科技/小盘成长股） |
| β ≈ 1 | 与大盘同步（宽基指数本身、大盘蓝筹） |
| 0 < β < 1 | 防御型：波动小于大盘（公用事业、必需消费） |
| β ≈ 0 | 与大盘几乎不相关（市场中性策略、现金类） |
| β < 0 | 反向：与大盘负相关（黄金、做空头寸、部分避险资产） |

**常见误区**：

1. **把 β 当"总风险"**。β 只度量**系统性**（不可分散）风险，不含个股特有风险。低 β 资产仍可能因公司基本面剧烈波动；衡量总波动应看 $\sigma$（见 [[volatility]]）。CAPM 框架下只有系统性风险被定价 (Sharpe, 1964)。

2. **以为高 β 必然带来高收益**。CAPM 预言 β 与预期收益正相关，但 Frazzini & Pedersen (2014) 的"Betting Against Beta"实证发现 SML（证券市场线）实际比理论**更平**：高 β 资产风险调整后收益反而偏低，低 β 资产 alpha 为正。这是杠杆约束导致的市场异象，不是教科书自动成立。

3. **β 不稳定却当常数用**。单一历史窗口估出的 β 有估计误差且随市场状态漂移；Blume (1971) 实证显示个股 β 随时间向 1 均值回归，故业界常用 Blume 调整 $\beta_{adj} = 0.67\,\beta_{raw} + 0.33$。直接拿一段样本 β 外推到未来会高估极端 β 的持续性。

4. **基准选错使 β 失真**。β 是相对某个市场组合算的；用沪深 300 算的 β 不能直接套到以中证 500 或全球指数为基准的场景。CAPM 理论上的"市场组合"是全部可投资资产，实证只能用代理指数，这是 Roll (1977) 批判的核心。

5. **混淆 β 与相关系数**。β = $\rho \cdot \sigma_i / \sigma_m$，相关系数 $\rho \in [-1, 1]$ 只衡量方向与紧密度，β 还乘了波动比，可远大于 1。两者不可互换。

## L4 延伸阅读

- **[[alpha]]** — Alpha 是回归截距（剥离 β 暴露后的超额收益），Beta 是斜率（市场暴露）。同一个 $R_i = \alpha + \beta R_m + \epsilon$ 回归的两个产物：β 是你"承担市场风险拿的报酬"，α 是"超出风险补偿的本事"。
- **[[volatility]]** — 波动率 $\sigma$ 是资产**总**风险（系统性+特有），β 只截取与市场相关的系统性那部分；$\beta = \rho \cdot \sigma_i / \sigma_m$ 把两者联系起来。
- **[[sharpe_ratio]]** — Sharpe 用总波动 $\sigma$ 做分母（适合衡量整体组合），CAPM/Treynor 用 β 做分母（适合衡量已分散组合中单资产的贡献）。分母选谁取决于该资产的特有风险能否被分散。
- **[[mean_variance]]** — CAPM（β 的理论来源）是均值-方差最优化在市场出清均衡下的推论：所有人持有切点组合时，单资产的均衡预期收益就由它对市场组合的 β 决定。

参考文献：
- Sharpe, W. F. (1964). Capital Asset Prices: A Theory of Market Equilibrium under Conditions of Risk. *Journal of Finance* 19(3): 425–442.
- Fama, E. F., & French, K. R. (1992). The Cross-Section of Expected Stock Returns. *Journal of Finance* 47(2): 427–465.
- Blume, M. E. (1971). On the Assessment of Risk. *Journal of Finance* 26(1): 1–10.
- Roll, R. (1977). A Critique of the Asset Pricing Theory's Tests, Part I. *Journal of Financial Economics* 4(2): 129–176.
- Frazzini, A., & Pedersen, L. H. (2014). Betting Against Beta. *Journal of Financial Economics* 111(1): 1–25.
