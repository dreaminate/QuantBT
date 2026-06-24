---
term: mean_variance
display: "均值方差优化 (Markowitz Mean-Variance)"
aliases:
  - mean_variance
  - mean variance optimization
  - mvo
  - markowitz
  - 马科维茨
  - 均值方差
  - 现代投资组合理论
  - mpt
level: intermediate
category: portfolio
formula_latex: "\\max_{w}\\; w^\\top \\mu - \\frac{\\lambda}{2}\\, w^\\top \\Sigma\\, w \\quad \\text{s.t.}\\; \\mathbf{1}^\\top w = 1"
unit: "权重向量（无量纲，sum=1）"
typical_range: null
sources:
  - "Markowitz (1952) Portfolio Selection, J. of Finance 7(1)"
  - "Michaud (1989) The Markowitz Optimization Enigma: Is 'Optimized' Optimal?, Financial Analysts Journal 45(1)"
related:
  - risk_parity
  - hrp
  - kelly_fraction
  - sharpe_ratio
---

## L1 一句话

给定风险下求收益最大的权重组合。

## L2 公式与例子

均值方差优化 (mean-variance optimization, MVO) 把组合选择写成：在期望收益 $\mu$ 与协方差矩阵 $\Sigma$ 已知下，找权重向量 $w$ 使「收益减去风险惩罚」最大，$\lambda$ 是风险厌恶系数。

$$
\max_{w}\; w^\top \mu - \frac{\lambda}{2}\, w^\top \Sigma\, w
\quad \text{s.t.}\; \mathbf{1}^\top w = 1
$$

- $w$：各资产权重（$\mathbf{1}^\top w = 1$ 即满仓）
- $\mu$：各资产期望收益向量
- $\Sigma$：收益协方差矩阵；$w^\top \Sigma\, w$ 是组合方差
- $\lambda$：风险厌恶系数，越大越保守

特例 $\lambda \to \infty$（只压风险、不看收益）得**最小方差组合** (global minimum-variance, GMV)，两资产闭式解为 $w_A = \dfrac{\sigma_B^2 - \sigma_{AB}}{\sigma_A^2 + \sigma_B^2 - 2\sigma_{AB}}$。

**算例**（两资产 GMV）：资产 A 年化波动 $\sigma_A = 10\%$，资产 B $\sigma_B = 20\%$，相关系数 $\rho = 0$（故 $\sigma_{AB}=0$）。
代入：$w_A = \dfrac{0.20^2}{0.10^2 + 0.20^2} = \dfrac{0.04}{0.05} = 0.80$，$w_B = 0.20$。
组合波动 $\sigma_p = \sqrt{0.8^2\cdot0.1^2 + 0.2^2\cdot0.2^2} = \sqrt{0.008} \approx 8.94\%$。
→ 8.94% **低于 A 单独的 10%**，也低于 50/50 等权的 11.18%——这就是分散化（diversification）把组合风险压到任一成分以下的核心结论。

## L3 业界阈值与误区

**阈值参考**（经验区间，非硬规则，出处见下）：

| 参数 / 现象 | 参考区间 | 解读 |
|---|---|---|
| 风险厌恶 $\lambda$（年化收益/方差刻度） | 1 ~ 10 | 机构常用 2~4；散户偏保守取更大 |
| 权重上限约束 | 单标的 ≤ 5%~10% | 不加约束时 MVO 易把权重全堆到少数标的 |
| 估计期长度 vs 资产数 N | T ≫ N（如 T > 10N） | T 不足时 $\Sigma$ 几乎不可逆、解极不稳 |
| 输入误差对权重的放大 | $\mu$ 误差 ≈ 10× $\Sigma$ 误差影响 | 故业界多固定 $\mu$、只优化风险 |

**常见误区**：

1. **误差最大化机** (error-maximization)：MVO 对输入估计误差极度敏感，会把权重集中到「估计期里恰好显得高收益低相关」的标的上，本质是在放大噪声。Michaud (1989) 直接称 MVO 为「estimation-error maximizer」，并指出未约束的 MVO 解常在样本外表现差于等权。
2. **$\mu$ 几乎无法估准**：Best & Grauer (1991) 证明最优权重对期望收益输入高度敏感——$\mu$ 的微小变动可使权重剧烈翻转甚至变号。这是 risk_parity / HRP 等「不依赖 $\mu$」方法兴起的直接动因。
3. **协方差矩阵不可逆 / 病态**：当资产数 N 接近或超过样本期 T，样本协方差 $\Sigma$ 估计噪声主导，求逆 $\Sigma^{-1}$ 放大噪声。Ledoit & Wolf (2004) 提出收缩估计 (shrinkage) 把样本 $\Sigma$ 向结构化目标拉，作为标准缓解手段。
4. **把历史均值当期望收益**：直接用回测期样本均值做 $\mu$ 是典型 look-ahead / 过拟合来源；样本均值的估计误差极大，几乎注定样本外失效。
5. **忽略交易成本与换手**：MVO 每期重算会产生高换手；不在目标函数里加换手/成本惩罚，纸面有效前沿（efficient frontier）在扣费后大幅缩水。

## L4 延伸阅读

- **[[risk_parity]]** — 风险平价完全不用 $\mu$，按风险贡献均摊；正是为绕开 MVO 对期望收益的敏感而生。
- **[[hrp]]** — HRP 用层次聚类替代 $\Sigma^{-1}$ 求逆，回避 MVO 的协方差病态问题，López de Prado 证其样本外更稳。
- **[[kelly_fraction]]** — Kelly 优化的是对数财富长期增长率，与 MVO 的单期均值方差权衡目标不同；二者在对数正态近似下相关但非等价。
- **[[sharpe_ratio]]** — 有效前沿上与无风险资产相切的「切线组合」(tangency portfolio) 正是最大化 Sharpe 比率的组合，是 MVO 与 Sharpe 的连接点。

参考文献：
- Markowitz, H. (1952). Portfolio Selection. *Journal of Finance* 7(1): 77–91.
- Michaud, R. O. (1989). The Markowitz Optimization Enigma: Is "Optimized" Optimal? *Financial Analysts Journal* 45(1): 31–42.
- Best, M. J., & Grauer, R. R. (1991). On the Sensitivity of Mean-Variance-Efficient Portfolios to Changes in Asset Means. *Review of Financial Studies* 4(2): 315–342.
- Ledoit, O., & Wolf, M. (2004). Honey, I Shrunk the Sample Covariance Matrix. *Journal of Portfolio Management* 30(4): 110–119.
