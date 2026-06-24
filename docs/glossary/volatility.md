---
term: volatility
display: "波动率 (Volatility, 年化)"
aliases:
  - volatility
  - vol
  - 波动率
  - 年化波动
  - 历史波动率
  - annualized volatility
level: intermediate
category: risk
formula_latex: "\\sigma_{ann} = \\sigma_{period} \\cdot \\sqrt{T}, \\quad \\sigma_{period} = \\sqrt{\\frac{1}{N-1}\\sum_{i=1}^{N}(r_i - \\bar{r})^2}"
unit: "年化标准差（小数，如 0.20 = 20%）"
typical_range: [0.05, 0.8]
sources:
  - "Hull (2018) Options, Futures, and Other Derivatives, 10th ed., Pearson, Ch.15"
  - "Andersen, Bollerslev, Diebold, Labys (2003) Modeling and Forecasting Realized Volatility, Econometrica 71(2)"
related:
  - sharpe_ratio
  - var_cvar
  - sortino_ratio
  - max_drawdown
---

## L1 一句话

收益波动的年化标准差，衡量价格起伏。

## L2 公式与例子

$$
\sigma_{ann} = \sigma_{period} \cdot \sqrt{T}, \quad
\sigma_{period} = \sqrt{\frac{1}{N-1}\sum_{i=1}^{N}(r_i - \bar{r})^2}
$$

- $r_i$：单周期收益率（日频常用对数收益 $\ln(P_i/P_{i-1})$ 或简单收益）
- $\sigma_{period}$：单周期收益的样本标准差（除 $N-1$，无偏估计）
- $T$：年化系数 = 每年周期数。日频股票 $T=252$（交易日），加密日频 $T=365$，小时频 $T=8760$

**算例**：5 个交易日的日收益 $[2\%, -1\%, 1.5\%, -0.5\%, 1\%]$。
均值 $\bar{r} = 0.6\%$；偏差平方和 $\sum(r_i-\bar{r})^2 = 0.00067$。
样本方差 $= 0.00067 / (5-1) = 0.0001675$，故 $\sigma_{period} = \sqrt{0.0001675} \approx 1.294\%$。
年化（股票 $T=252$，$\sqrt{252}\approx 15.875$）：$\sigma_{ann} = 0.01294 \times 15.875 \approx 0.205$，即 **20.5%**。

## L3 业界阈值与误区

**年化波动率参考区间**（无单一"正确值"，随资产类别差异巨大，仅作量级锚点）：

| 资产 / 策略类型 | 年化波动率量级 | 说明 |
|---|---|---|
| 投资级债券 / 货币型 | < 5% | 低波，对应低预期收益 |
| 大盘股指（如沪深300、标普500） | 15% ~ 25% | 长期历史区间，标普500长期年化波动约 15%-20%（Hull, 2018） |
| 单一成长股 / 主动选股策略 | 25% ~ 50% | 个股特质波动放大 |
| 加密资产（BTC/ETH） | 50% ~ 100%+ | BTC 年化波动长期显著高于股票（Liu & Tsyvinski, 2021） |

**常见误区**：

1. **年化系数与频率不匹配** — $\sqrt{T}$ 缩放（square-root-of-time rule）默认收益独立同分布、无自相关。用日频 $T=252$ 缩放后再去和小时频 $T=8760$ 缩放的结果直接比较，或对存在动量/均值回复（收益自相关 $\neq 0$）的序列硬套 $\sqrt{T}$，都会系统性高估或低估真实年化波动（Hull, 2018, Ch.15；Diebold et al., 1997, "Converting 1-Day Volatility to h-Day Volatility"）。
2. **把波动率当全部风险** — 波动率是二阶矩，对称看待上涨和下跌，且**完全不反映尾部厚度**。同样 20% 年化波动，正态分布与厚尾分布的极端亏损概率天差地别；2008、312 这类事件的杀伤在 VaR/CVaR 与尾部风险里，不在波动率里（López de Prado, 2018, AFML, Ch.3 论尾部）。须配 [[var_cvar]]、[[max_drawdown]] 共看。
3. **历史波动 ≠ 未来波动，且存在聚集性** — 波动率有"聚类"（volatility clustering）：大波动后倾向跟随大波动，平静后跟随平静（Mandelbrot, 1963 首次记录；Engle, 1982 ARCH 模型据此建模）。用一段平静期的历史波动率外推到下一段，会在 regime 切换时严重失真——这正是 GARCH/已实现波动率（realized volatility, Andersen et al., 2003）要建模的对象。
4. **滚动窗口长度敏感** — 用 20 日窗口算的波动率与 252 日窗口算的，数值与稳定性完全不同：短窗反应快但噪声大、易突刺，长窗平滑但滞后。报告波动率却不写窗口长度与频率，等于没有报告（Hull, 2018, Ch.15）。

## L4 延伸阅读

- **[[sharpe_ratio]]** — 波动率是夏普比率的分母；夏普衡量"单位波动换多少超额收益"，波动率本身只量风险不看收益。
- **[[sortino_ratio]]** — 索提诺只用**下行波动**（下行标准差）替代本条的总波动，对厚尾、收益不对称的策略更贴近真实痛感。
- **[[var_cvar]]** — VaR/CVaR 直接给出"某置信度下的最大/期望亏损金额"，捕捉波动率忽略的尾部损失幅度。
- **[[max_drawdown]]** — 最大回撤是路径依赖的实际亏损峰谷，波动率是分布的二阶矩；同一波动率下回撤可天差地别。

参考文献：
- Hull, J. C. (2018). *Options, Futures, and Other Derivatives* (10th ed.), Pearson. Ch.15.
- Andersen, T. G., Bollerslev, T., Diebold, F. X., & Labys, P. (2003). Modeling and Forecasting Realized Volatility. *Econometrica* 71(2).
- Engle, R. F. (1982). Autoregressive Conditional Heteroscedasticity with Estimates of the Variance of United Kingdom Inflation. *Econometrica* 50(4).
- Mandelbrot, B. (1963). The Variation of Certain Speculative Prices. *J. of Business* 36(4).
- López de Prado, M. (2018). *Advances in Financial Machine Learning*, Wiley.
- Liu, Y., & Tsyvinski, A. (2021). Risks and Returns of Cryptocurrency. *Review of Financial Studies* 34(6).
