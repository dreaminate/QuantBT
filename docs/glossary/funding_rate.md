---
term: funding_rate
display: "资金费率 (Funding Rate, 永续)"
aliases:
  - funding_rate
  - funding rate
  - funding
  - 资金费率
  - 资金费
  - 永续资金费率
level: intermediate
category: execution
formula_latex: "F = P + \\mathrm{clamp}\\left(I - P,\\ -c,\\ +c\\right), \\quad \\text{Payment} = N \\cdot F"
unit: "每结算周期百分比（如每 8 小时），常以 bps 计"
typical_range: [-0.0075, 0.0075]
sources:
  - "Binance (2024) Perpetual Futures Contracts Specification & Funding Rate Methodology, Binance Futures Documentation"
  - "BitMEX (2016) Perpetual Contracts Guide: Funding, BitMEX Documentation"
  - "Alexander, C., Chen, D., & Imeraj, A. (2023) Perpetual Futures Pricing, arXiv:2310.11771"
related:
  - slippage
  - walk_forward
---

## L1 一句话

永续合约多空之间的周期性持仓利息。

## L2 公式与例子

永续合约（perpetual swap）没有到期日，靠**资金费率**把合约价格锚到现货：当合约价高于现货（多头拥挤），费率为正，多头付钱给空头；反之空头付多头。交易所每个结算周期（多数为每 8 小时）按下式收付，**资金费不进交易所口袋，是持仓双方互转**：

$$
F = P + \mathrm{clamp}\left(I - P,\ -c,\ +c\right), \qquad \text{Payment} = N \cdot F
$$

- $F$：本周期资金费率（一个百分比，按结算周期计，不是年化）
- $P$：溢价指数（premium index），度量合约相对现货标记价的偏离
- $I$：利率成分（interest rate），主流交易所默认约 0.01%/8h（即多空借贷利差的固定项）
- $c$：clamp 边界（如 ±0.05%），把 $I-P$ 夹在区间内，避免极端值
- $N$：持仓名义价值（notional）= 合约张数 × 标记价
- 正 $F$：多头付空头；负 $F$：空头付多头

**算例**：账户持有 BTC 永续多头，名义价值 $N=50{,}000$ USDT，本结算期资金费率 $F=+0.01\%$（即 0.0001），结算周期每 8 小时一次。
- 单次资金费 = $50{,}000 \times 0.0001 = 5$ USDT（多头**付出** 5 USDT）。
- 一天结算 3 次，若费率不变：$5 \times 3 = 15$ USDT/日。
- 年化持仓成本 ≈ $0.0001 \times 3 \times 365 = 10.95\%$。仅这一项就吞掉约 11%/年，对长期裸多头是结构性拖累。

## L3 业界阈值与误区

**阈值参考**（主流 USDT 永续，单次费率，业内常见档位）：

| 单次费率（每 8h） | 年化等价（×3×365） | 解读 |
|---|---|---|
| ±0.01% | ±10.95% | 中性基准；多数交易所利率默认项即此量级（Binance/BitMEX 文档） |
| +0.05% ~ +0.10% | +54.75% ~ +109.5% | 多头明显拥挤；触及 clamp 上限附近，常见于单边上涨末段 |
| > +0.10% | > +109.5% | 极端多头杠杆，历史上多伴随后续急跌去杠杆 |
| 负值 | 空头付多头 | 现货折价 / 空头拥挤；可做正向 cash-and-carry 套利的信号 |

注：clamp 上下限与结算频率因交易所而异（BitMEX 历史用 ±0.375% 上限，部分高波动合约每 4h 或每 1h 结算），上表年化系数需按实际结算次数重算。

**常见误区**：

1. **把单次费率当年化读**：0.01% 看着微不足道，但每 8h 一次 ×365 天 ≈ 11%/年。Binance 与 BitMEX 文档都明确资金费率是**按结算周期**报价、非年化；回测里若按"日费率"或"年化"口径错配 frequency，持仓成本会算错 3 倍或几十倍。

2. **忽略资金费导致回测系统性高估收益**：永续合约策略若只算价格 PnL、不扣资金费，等于免费持仓。BitMEX (2016) 文档指出资金费是永续区别于交割合约的核心机制；机构回测必须把每个结算时点的 $N\cdot F$ 计入现金流，否则长期多头策略的 Sharpe 被系统性虚高。

3. **混淆资金费率与利率/借贷成本**：资金费率是多空之间的转移支付，反映的是**合约相对现货的供需偏离**，不是交易所向你收的费，也不等于现货保证金借贷利率。Alexander, Chen & Imeraj (2023) 在永续合约定价框架中把资金支付（funding payment）与无套利持有成本分开建模——把二者混为一谈会错判套利空间。

4. **假设费率恒定外推**：资金费率随市场情绪剧烈波动且可正可负，不能用当前值线性外推未来持仓成本。极端行情下连续多期高正费率会触发去杠杆，反而预示价格反转，本身是一种拥挤度信号。

5. **忽略标记价（mark price）与结算时点**：资金费按**结算快照时刻**的标记价和名义价值计算，不是按你的开仓价。开/平仓刚好跨过结算时点会被收/免一整期费用；高频或网格策略对此尤其敏感。

## L4 延伸阅读

- **[[slippage]]** — 滑点是单次成交的价格冲击（一次性），资金费率是持仓期间的周期性现金流（随时间累积）。两者都是 execution 层成本，但一个按笔、一个按时间，回测需分别建模。
- **[[walk_forward]]** — 资金费率体制（正/负、高/低）随市场阶段切换，把它当成本或信号的策略必须用滚动前推（walk-forward）验证跨体制稳健性，避免在单一资金费环境上过拟合。

参考文献：
- Binance. (2024). *Perpetual Futures Contracts Specification & Funding Rate Methodology*. Binance Futures Documentation.
- BitMEX. (2016). *Perpetual Contracts Guide: Funding*. BitMEX Documentation.
- Alexander, C., Chen, D., & Imeraj, A. (2023). *Perpetual Futures Pricing*. arXiv:2310.11771.
