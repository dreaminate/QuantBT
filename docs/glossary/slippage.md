---
term: slippage
display: "滑点 (Slippage)"
aliases:
  - slippage
  - 滑点
  - 成交滑点
  - 执行滑点
  - 价格滑移
level: intermediate
category: execution
formula_latex: "S_{\\text{bps}} = \\text{side} \\cdot \\frac{P_{\\text{fill}} - P_{\\text{decision}}}{P_{\\text{decision}}} \\cdot 10^{4}"
unit: "基点 (bps, 1bp = 0.01%)"
typical_range: null
sources:
  - "Perold (1988) The Implementation Shortfall: Paper versus Reality, J. of Portfolio Management 14(3)"
  - "Almgren, Chriss (2000) Optimal Execution of Portfolio Transactions, J. of Risk 3(2)"
  - "Kissell (2013) The Science of Algorithmic Trading and Portfolio Management, Academic Press"
related:
  - funding_rate
  - walk_forward
  - look_ahead_bias
---

## L1 一句话

决策价与实际成交价之间的差。

## L2 公式与例子

滑点 (slippage) 衡量**下单决策那一刻看到的价格**与**实际成交价**的偏离，通常以基点 (bps，1bp = 0.01%) 表示，并按买卖方向取号——使你"吃亏"的方向记为正。

$$
S_{\text{bps}} = \text{side} \cdot \frac{P_{\text{fill}} - P_{\text{decision}}}{P_{\text{decision}}} \cdot 10^{4}
$$

- $P_{\text{decision}}$：信号/决策时刻的参考价（常用决策时的 mid 或上一收盘）
- $P_{\text{fill}}$：实际成交均价（多笔分批则为成交量加权均价 VWAP）
- $\text{side}$：买入取 $+1$、卖出取 $-1$，使"买更贵 / 卖更便宜"都为正滑点

这是 Perold (1988) 提出的**执行落差 (implementation shortfall)** 的核心成分：纸上组合用 $P_{\text{decision}}$ 成交，真实组合用 $P_{\text{fill}}$ 成交，差额即滑点（外加手续费、未成交的机会成本）。

**算例**：决策时某币 mid 价 $P_{\text{decision}} = 100.00$，发市价买单，分三笔吃掉盘口，成交均价 $P_{\text{fill}} = 100.06$。

$$
S_{\text{bps}} = (+1)\cdot\frac{100.06 - 100.00}{100.00}\cdot 10^{4} = +6\ \text{bps}
$$

即每笔交易先亏 6bp。若策略月换手 20 倍（双边累计名义 = 20×本金），仅滑点一项年化拖累约 $6\ \text{bp} \times 20 \times 12 = 14400\ \text{bp} = 144\%$——足以把一个回测里 SR=2 的高频策略实盘打成负收益。

## L3 业界阈值与误区

**滑点量级参考**（按资产流动性，单边、单笔常规规模；数量级共识见 Kissell 2013 第 3、5 章交易成本分解，及 Frazzini-Israel-Moskowitz 2018 大样本实测）：

| 市场 / 工具 | 单边滑点量级 | 出处 / 说明 |
|---|---|---|
| 大盘股、主力期货（流动） | 1 ~ 10 bps | Frazzini, Israel & Moskowitz (2018) 万亿美元真实成交：大盘冲击远低于学界假设 |
| 中小盘股 / 流动性差时段 | 10 ~ 50+ bps | Kissell (2013) §5：冲击随 ADV 占比与波动率非线性上升 |
| 加密主流币现货（BTC/ETH） | 1 ~ 15 bps | 取决于交易所深度与下单规模占盘口比例 |
| 加密山寨币 / 薄盘口 | 数十 ~ 数百 bps | 盘口稀薄，市价单极易穿价 |

冲击常用平方根模型近似：$\text{impact} \approx \sigma\,\eta\sqrt{Q/V}$（$Q$ 下单量、$V$ 日成交量、$\sigma$ 波动率），即下单越大、越急、标的越波动，滑点越高（Almgren & Chriss, 2000；Almgren et al., 2005 实测平方根律）。

**常见误区**：

1. **回测假设零滑点或固定常数滑点**。直接用收盘价 $P_{\text{decision}}$ 成交、或对所有标的套同一个"5bp"，会系统性高估收益，对高换手策略尤甚。Perold (1988) 正是为揭示"纸上组合 vs 真实组合"这道落差而提出 implementation shortfall——纸面 SR 与实盘 SR 的鸿沟主要来自这里。

2. **忽略冲击的非线性与规模依赖**。把滑点当成与下单量无关的常数，违背平方根冲击律：Almgren & Chriss (2000) 与 Almgren et al. (2005) 的实证表明，冲击大致随 $\sqrt{Q/V}$ 增长，规模翻 4 倍滑点约翻倍。容量测试时按小单滑点外推大单，会严重低估真实成本。

3. **用未来信息估滑点（执行落差里的前视陷阱）**。例如用"当根 K 线的 VWAP / 收盘价"作为信号同一根的成交价，等于让模型在还没看到这根 K 线时就按它的均价成交，属于前视偏差 (look-ahead bias)。López de Prado (2018, AFML) 反复强调成交价只能用决策时点**及之后**真实可得的报价，信号 bar 与成交 bar 必须错开。

4. **只算价差、漏掉机会成本与未成交腿**。Perold (1988) 的 implementation shortfall 明确包含三块：已成交部分的价差、手续费、以及**因挂限价单没成交而错过的行情（机会成本）**。只盯成交单的价差、忽略撤单/未成交，会低估真实执行成本。

5. **把滑点、手续费、（永续）资金费率混为一谈或重复计**。三者是并列的执行成本项：滑点是成交价偏离、手续费是交易所/券商抽佣、资金费率是永续合约持仓的周期性收付。建模时应分项各自计提，既不能合并成一个"摩擦系数"糊弄，也不能在不同模块里重复扣（参见 [[funding_rate]]）。

## L4 延伸阅读

- **[[funding_rate]]** — 资金费率是**持仓**期间永续合约的周期性收付成本；滑点是**成交瞬间**的价格偏离。二者都是执行成本但触发时点不同：滑点按笔发生、资金费率按结算周期发生，需分项各计。
- **[[walk_forward]]** — walk-forward 是按时间滚动的样本外验证流程；若样本外阶段仍沿用回测里偏低的滑点假设，OOS 结果照样虚高。滑点假设的现实性直接决定 walk-forward 能否反映真实可交易性，本条是它的成本输入前提。
- **[[look_ahead_bias]]** — 前视偏差是"用了当时不可得的未来信息"这一普遍泄露；用信号同根 K 线的成交价估滑点，是它在执行环节的一个具体形态。look_ahead_bias 讲一般原理，本条讲它如何潜入成交价假设。

参考文献：
- Perold, A. F. (1988). The Implementation Shortfall: Paper versus Reality. *Journal of Portfolio Management*, 14(3): 4–9.
- Almgren, R., & Chriss, N. (2000). Optimal Execution of Portfolio Transactions. *Journal of Risk*, 3(2): 5–39.
- Almgren, R., Thum, C., Hauptmann, E., & Li, H. (2005). Direct Estimation of Equity Market Impact. *Risk*, 18(7): 58–62.
- Kissell, R. (2013). *The Science of Algorithmic Trading and Portfolio Management*. Academic Press. Chapters 3 & 5 (Transaction Cost Analysis; Market Impact).
- Frazzini, A., Israel, R., & Moskowitz, T. J. (2018). Trading Costs. *Working Paper*, AQR Capital Management.
- López de Prado, M. (2018). *Advances in Financial Machine Learning*. Hoboken, NJ: Wiley.
