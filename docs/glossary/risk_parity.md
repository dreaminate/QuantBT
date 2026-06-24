---
term: risk_parity
display: "风险平价 (Risk Parity)"
aliases:
  - risk_parity
  - risk parity
  - 风险平价
  - 风险均衡
  - equal risk contribution
  - erc
  - 等风险贡献
level: intermediate
category: portfolio
formula_latex: "RC_i = w_i \\frac{(\\Sigma w)_i}{\\sqrt{w^\\top \\Sigma w}}, \\quad RC_i = RC_j \\; \\forall i,j"
unit: "权重（无量纲，∑w=1）"
typical_range: null
sources:
  - "Maillard, Roncalli, Teïletche (2010) The Properties of Equally Weighted Risk Contribution Portfolios, J. of Portfolio Management 36(4)"
  - "Qian (2005) Risk Parity Portfolios: Efficient Portfolios Through True Diversification, PanAgora Asset Management"
  - "Roncalli (2013) Introduction to Risk Parity and Budgeting, Chapman & Hall/CRC"
related:
  - mean_variance
  - hrp
  - kelly_fraction
---

## L1 一句话

让每个资产贡献相同的组合风险。

## L2 公式与例子

风险平价（Risk Parity，又称等风险贡献 Equal Risk Contribution / ERC）按"风险预算"而非资金比例配权：每个资产对组合波动率的边际贡献相等。

组合波动率 $\sigma_p = \sqrt{w^\top \Sigma w}$（$w$ 为权重向量，$\Sigma$ 为协方差矩阵）。资产 $i$ 的**风险贡献**（risk contribution）为：

$$
RC_i = w_i \frac{(\Sigma w)_i}{\sqrt{w^\top \Sigma w}}, \qquad \sum_i RC_i = \sigma_p
$$

风险平价的目标是令所有 $RC_i$ 相等：$RC_i = \sigma_p / N$。

**算例（两资产，可手算）**：股票波动率 $\sigma_A = 20\%$、债券 $\sigma_B = 8\%$，相关系数 $\rho = 0$。
逆波动率（inverse-volatility）配权：$w_A = \frac{1/0.20}{1/0.20 + 1/0.08} = \frac{5}{5+12.5} = 0.286$，$w_B = 0.714$。
组合波动率 $\sigma_p = \sqrt{0.286^2 \cdot 0.20^2 + 0.714^2 \cdot 0.08^2} = \sqrt{0.00327 + 0.00327} = 0.0808$（8.1%）。
两资产风险贡献各 $0.0404$，即 $50\%$ : $50\%$ —— 风险被对半切开，而资金是 28.6% : 71.4%。
（注：仅在两资产时逆波动率恰好等于 ERC；相关时与多资产时需迭代数值求解，见 L3。）

## L3 业界阈值与误区

风险平价没有像 Sharpe 那样的"好/坏阈值"，关键是**诊断量**——查组合是否真的风险均摊，以及杠杆/敞口是否过界：

| 诊断量 | 参考 | 依据 |
|---|---|---|
| 单资产风险贡献 $RC_i / \sigma_p$ | 目标 $\approx 1/N$，偏离 > 5pct 说明未收敛 | Maillard et al. (2010) |
| 60/40 组合中股票的风险贡献 | 约 90% 左右（"伪分散"） | Qian (2005) |
| 达到目标波动率所需杠杆 | 全债型 RP 常需 1.5–3× 杠杆 | Roncalli (2013) |
| 协方差估计窗口 | 月频常用 36–60 个月滚动 | Roncalli (2013) |

**常见误区**：

1. **把逆波动率配权当成真正的风险平价**。逆波动率（$w_i \propto 1/\sigma_i$）只在资产两两不相关、或恰好两资产时等于 ERC；一旦有相关性且资产数 > 2，二者就分叉。例：股/债/黄金三资产带相关性时，逆波动率给出 32%/29%/39% 的风险贡献，而真正的 ERC 解是 33%/33%/33%（需迭代求解）。Maillard, Roncalli & Teïletche (2010) 正是为区分这两者而定义 ERC。
2. **以为风险平价天然低风险**。它只是"风险来源更均衡"，绝对波动率可以很低，因此机构常加杠杆把波动率拉到目标值（如 10%）。Roncalli (2013) 指出全债占比高的 RP 组合常需 1.5–3 倍杠杆，叠加融资成本与强平风险——2013 年"缩减恐慌"（taper tantrum）中加杠杆 RP 基金回撤显著放大，正是杠杆而非配权方法本身的代价。
3. **忽视协方差矩阵的估计误差**。$\Sigma$ 由历史数据估计，高维下极不稳定，且相关性在危机中趋近 1（分散失效）。López de Prado (2016) 提出层次风险平价（HRP，见 [[hrp]]）正是为缓解 $\Sigma$ 求逆的数值不稳定。直接对噪声协方差做 ERC 会得到看似精确实则脆弱的权重。
4. **把"等风险贡献"误读为"等收益贡献"**。RP 完全不看预期收益，隐含假设是各资产**风险调整后收益（夏普）相近**。若该假设不成立（如某资产长期负夏普），RP 会系统性地把资金配给低效资产。这是 RP 相对均值-方差（见 [[mean_variance]]）放弃 alpha 信息的结构性代价。

## L4 延伸阅读

- **[[mean_variance]]** — 均值-方差需要预期收益输入并最大化夏普；风险平价完全不用预期收益，只按协方差均摊风险，因而对估计误差更稳健但放弃了 alpha 信息。
- **[[hrp]]** — 层次风险平价是风险平价的改良：先用聚类把资产分层、再递归二分配权，避免对协方差矩阵求逆，缓解本条误区 3 的数值不稳定。
- **[[kelly_fraction]]** — 凯利公式按预期收益与方差决定**单一头寸**的最优下注比例（追求长期增长率）；风险平价决定**多资产间**的相对权重（追求风险均摊），二者关注的维度不同。

参考文献：
- Maillard, S., Roncalli, T., & Teïletche, J. (2010). The Properties of Equally Weighted Risk Contribution Portfolios. *Journal of Portfolio Management* 36(4): 60–70.
- Qian, E. (2005). *Risk Parity Portfolios: Efficient Portfolios Through True Diversification*. PanAgora Asset Management White Paper.
- Roncalli, T. (2013). *Introduction to Risk Parity and Budgeting*. Chapman & Hall/CRC Financial Mathematics Series.
- López de Prado, M. (2016). Building Diversified Portfolios that Outperform Out of Sample. *Journal of Portfolio Management* 42(4): 59–69. (HRP)
