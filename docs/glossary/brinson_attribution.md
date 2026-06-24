---
term: brinson_attribution
display: "Brinson 归因 (Brinson Attribution)"
aliases:
  - brinson_attribution
  - brinson attribution
  - brinson model
  - bhb
  - bf
  - brinson 归因
  - 业绩归因
  - 收益归因
  - 配置选股归因
level: intermediate
category: portfolio
formula_latex: "R_p - R_b = \\sum_i (w_{p,i} - w_{b,i}) R_{b,i} + \\sum_i w_{b,i} (R_{p,i} - R_{b,i}) + \\sum_i (w_{p,i} - w_{b,i})(R_{p,i} - R_{b,i})"
unit: "收益率分解（与超额收益同单位，百分比）"
typical_range: null
sources:
  - "Brinson, Hood, Beebower (1986) Determinants of Portfolio Performance, Financial Analysts Journal 42(4)"
  - "Brinson, Fachler (1985) Measuring Non-US Equity Portfolio Performance, J. of Portfolio Management 11(3)"
related:
  - information_ratio
  - alpha
  - mean_variance
  - risk_parity
---

## L1 一句话

把超额收益拆成配置、选股、交互三部分。

## L2 公式与例子

Brinson 归因把组合相对基准的超额收益 $R_p - R_b$ 按分组（行业 / 资产类别）逐项拆解。经典 BHB（Brinson-Hood-Beebower 1986）三项分解为：

$$
R_p - R_b = \underbrace{\sum_i (w_{p,i} - w_{b,i}) R_{b,i}}_{\text{配置 Allocation}} + \underbrace{\sum_i w_{b,i} (R_{p,i} - R_{b,i})}_{\text{选股 Selection}} + \underbrace{\sum_i (w_{p,i} - w_{b,i})(R_{p,i} - R_{b,i})}_{\text{交互 Interaction}}
$$

- $w_{p,i}, w_{b,i}$：组合 / 基准在第 $i$ 组的权重
- $R_{p,i}, R_{b,i}$：组合 / 基准在第 $i$ 组的分组收益
- **配置**：你在某行业超配 / 低配带来的贡献（用基准收益计价）
- **选股**：你在该行业内选的股比基准好 / 差带来的贡献（用基准权重计价）
- **交互**：超配 × 选股的耦合项（常被并入选股）

**算例**（两行业，金额按百分比小数）：

| 组 $i$ | $w_{b,i}$ | $w_{p,i}$ | $R_{b,i}$ | $R_{p,i}$ |
|---|---|---|---|---|
| 科技 | 0.50 | 0.70 | 0.10 | 0.12 |
| 公用 | 0.50 | 0.30 | 0.04 | 0.04 |

- 基准收益 $R_b = 0.5\times0.10 + 0.5\times0.04 = 0.07$
- 组合收益 $R_p = 0.7\times0.12 + 0.3\times0.04 = 0.096$，超额 $= 0.026$（2.6%）
- 配置 $= (0.70-0.50)\times0.10 + (0.30-0.50)\times0.04 = 0.020 - 0.008 = 0.012$
- 选股 $= 0.50\times(0.12-0.10) + 0.50\times(0.04-0.04) = 0.010 + 0 = 0.010$
- 交互 $= (0.20)\times(0.02) + (-0.20)\times(0) = 0.004$
- 合计 $0.012 + 0.010 + 0.004 = 0.026$ ✓ 与超额 2.6% 吻合

结论：2.6% 超额里，配置贡献 1.2%、选股 1.0%、交互 0.4%——这只组合"会配（超配涨得多的科技）也会选（科技内选股 +2%）"。

## L3 业界阈值与误区

Brinson 归因输出的是**贡献分解**而非单一打分，因此没有"夏普 > 2"式的阈值表；其行业标准在于**口径合规性**。下表是 CFA Institute GIPS 与 Bacon (2008) 给出的方法学判定基准：

| 维度 | 行业基准 / 判定 | 出处 |
|---|---|---|
| 多期连乘残差 | 单期相加 ≠ 多期复利，必须用 Carino / GRAP 等平滑算法消除残差 | Carino (1999) |
| 配置项基准约定 | BF（Brinson-Fachler）用 $(R_{b,i}-R_b)$ 而非 $R_{b,i}$，避免"超配任何正收益行业都算赢" | Brinson, Fachler (1985) |
| 交互项归属 | 可单列或并入选股；并入须在报告中声明口径 | Bacon (2008) |
| 适用范围 | 仅适合多头、有明确分组基准的组合；不适合衍生品 / 杠杆 / 做空 | Bacon (2008) |

**常见误区**：

1. **直接相加多期单期效应**。单期 Brinson 效应**不能跨期简单相加**——组合是复利增长的，逐期相加会产生不可忽略的残差。必须用 Carino (1999) 对数平滑或 GRAP 调整因子做几何链接，残差才归零（Carino, D. R., 1999, *J. of Performance Measurement*）。把 12 个月配置效应直接加和是最常见的口径错误。
2. **误用 BHB 配置项做行业择时判断**。BHB 原始配置项 $(w_{p,i}-w_{b,i})R_{b,i}$ 中，只要超配了任何正收益行业就贡献为正，即使该行业跑输大盘。Brinson-Fachler (1985) 改用 $(w_{p,i}-w_{b,i})(R_{b,i}-R_b)$，只有超配跑赢基准的行业才算配置赢——做行业择时评价应优先用 BF 口径，否则会把"普涨行情里满仓"误判为配置能力（Brinson, Fachler, 1985, *JPM* 11(3)）。
3. **把交互项当噪声丢弃**。交互项 $(w_{p,i}-w_{b,i})(R_{p,i}-R_{b,i})$ 是超配与选股能力的真实耦合，集中持仓策略中可占超额的相当比例。Bacon (2008) 指出：交互项要么单列、要么明确并入选股并声明，**静默丢弃会使配置 + 选股之和对不上总超额**（Bacon, C. R., 2008, *Practical Portfolio Performance Measurement and Attribution*, 2nd ed., Wiley）。
4. **用错基准 / 分组与持仓不自洽**。归因结果对基准选择与分组定义极度敏感；若基准行业划分与组合实际持仓的 GICS 分类不一致，配置与选股效应会互相串味。GIPS 要求基准须事先指定且与策略一致（CFA Institute GIPS Standards）。
5. **对做空 / 杠杆组合硬套乘法分解**。Brinson 框架默认权重非负且加总为 1；含做空、衍生品或杠杆时权重定义破裂，三项分解不再可加，应改用基于持仓的多因子归因（Bacon, 2008）。

## L4 延伸阅读

- **[[information_ratio]]** — IR 衡量主动管理的总体性价比（超额 / 跟踪误差）；Brinson 归因则把这个超额**拆开**告诉你它来自配置还是选股。IR 是"赢了多少"，Brinson 是"为什么赢"。
- **[[alpha]]** — Alpha 是因子模型回归后剩下的、无法被风险因子解释的超额；Brinson 是**会计式**逐项加和分解，不做回归、不需要因子模型。两者都谈超额，但 alpha 是统计残差、Brinson 是恒等式拆分。
- **[[mean_variance]]** — 均值-方差是**事前**决定该如何配权重的优化；Brinson 是**事后**评价这些权重实际带来了多少配置 / 选股贡献。一个定策略、一个查账。
- **[[risk_parity]]** — 风险平价是一种具体的事前配权法则（按风险贡献等权）；用 Brinson 归因可事后检验风险平价组合的超额究竟来自资产配置偏离还是组内择券。

参考文献：

- Brinson, G. P., Hood, L. R., & Beebower, G. L. (1986). Determinants of Portfolio Performance. *Financial Analysts Journal* 42(4): 39–44.
- Brinson, G. P., & Fachler, N. (1985). Measuring Non-US Equity Portfolio Performance. *Journal of Portfolio Management* 11(3): 73–76.
- Carino, D. R. (1999). Combining Attribution Effects Over Time. *Journal of Performance Measurement* 3(4): 5–14.
- Bacon, C. R. (2008). *Practical Portfolio Performance Measurement and Attribution* (2nd ed.). Wiley.
