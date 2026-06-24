---
term: alpha
display: "詹森阿尔法 (Jensen's Alpha)"
aliases:
  - alpha
  - jensen alpha
  - jensens alpha
  - jensen's alpha
  - 阿尔法
  - 詹森阿尔法
  - 超额收益
level: intermediate
category: metric
formula_latex: "\\alpha_p = R_p - \\left[R_f + \\beta_p (R_m - R_f)\\right]"
unit: "收益率（与输入同频，常年化为 %）"
typical_range: [-0.2, 0.2]
sources:
  - "Jensen (1968) The Performance of Mutual Funds in the Period 1945-1964, J. of Finance 23(2)"
  - "Sharpe (1964) Capital Asset Prices: A Theory of Market Equilibrium under Conditions of Risk, J. of Finance 19(3)"
related:
  - beta
  - information_ratio
  - sharpe_ratio
  - brinson_attribution
---

## L1 一句话

扣掉 Beta 风险后超出市场的那部分收益。

## L2 公式与例子

詹森阿尔法 (Jensen's Alpha) 衡量组合**实际收益**与 CAPM (Capital Asset Pricing Model，资本资产定价模型) **理论应得收益**之差。把组合承担的市场风险（用 $\beta_p$ 度量）对应的报酬先扣掉，剩下的才算"主动管理真本事"。

$$
\alpha_p = R_p - \left[R_f + \beta_p (R_m - R_f)\right]
$$

- $R_p$：组合（portfolio）期内收益率
- $R_f$：无风险利率（risk-free rate）
- $R_m$：市场基准（market）收益率
- $\beta_p$：组合相对市场的 Beta（见 [[beta]]）
- 方括号内 $R_f + \beta_p (R_m - R_f)$ 即 CAPM 给出的"该赚的期望收益"

**算例**：某组合年化收益 $R_p = 12\%$，无风险利率 $R_f = 3\%$，市场收益 $R_m = 10\%$，组合 $\beta_p = 1.2$。
- CAPM 应得收益 $= 3\% + 1.2 \times (10\% - 3\%) = 3\% + 1.2 \times 7\% = 3\% + 8.4\% = 11.4\%$
- $\alpha_p = 12\% - 11.4\% = 0.6\%$

结论：组合跑赢市场 2 个百分点（12% vs 10%），但其中绝大部分来自加了 1.2 倍杠杆式的市场暴露；真正"无法用 Beta 解释"的主动超额只有 **0.6%**。这正是 Jensen (1968) 与单看原始收益的本质区别。

## L3 业界阈值与误区

**阈值参考**（年化 α，主动管理语境；阈值为经验/文献参考，非硬标准）：

| 年化 α 区间 | 解读 |
|---|---|
| > 5% | 罕见且需高度警惕过拟合/数据问题；先做样本外验证 |
| 2% ~ 5% | 较强主动能力，但须确认统计显著（看 t 值 / 标准误） |
| 0% ~ 2% | 多数主动基金的现实区间；常被费用与交易成本吃掉 |
| ≈ 0 或为负 | 与 CAPM 一致或跑输；扣费后多数主动基金落此区（Jensen 1968） |
| < -2% | 持续为负应考虑停用或改为被动 |

**常见误区**：

1. **把 α 当统计显著来用，不看标准误**。α 是回归截距的点估计，本身有抽样误差。Jensen (1968) 原文核心结论正是：1945-1964 年绝大多数共同基金扣费后 α 不显著异于零，跑赢市场的样本无法与运气区分。报告 α 必须同时给 t 值或置信区间，否则不可解读。
2. **α 数值随基准与 Beta 估计漂移，却假装它客观唯一**。同一组合换市场基准（如全市场指数 vs 风格指数）或换 Beta 估计窗口，α 会显著变化；Fama & French (1993) 证明很多"正 α"在加入规模、价值因子后被解释掉、缩水甚至转负——即所谓单因子 CAPM 的"遗漏因子"问题。CAPM α ≠ 多因子 α。
3. **忽略费用、交易成本与生存者偏差，高估 α**。教科书 α 常用毛收益算；真实可投资 α 要扣管理费、佣金、冲击成本（见 [[slippage]]）。同时若样本只含存活基金，会系统性高估 α（见 [[survivorship_bias]]）；Carhart (1997) 在控制动量与费用后，基金持续正 α 的证据进一步削弱。
4. **混淆 α（风险调整超额）与原始超额收益 $R_p - R_m$**。上文算例里原始超额 2%、α 仅 0.6%，差额全是 Beta 报酬。直接用 $R_p - R_m$ 当"主动能力"会把杠杆/高 Beta 暴露误记为本事。

## L4 延伸阅读

- **[[beta]]** — α 是 CAPM 回归的截距，β 是斜率；β 度量你承担的市场风险，α 度量扣掉这份风险报酬后剩下的部分。没有 β 就算不出 α。
- **[[information_ratio]]** — IR = α / 主动风险（跟踪误差），是 α 的"性价比"版本：把 α 标准化为每单位主动风险的超额，比裸 α 更可比。
- **[[sharpe_ratio]]** — Sharpe 用总风险（总波动）做分母、不区分市场与主动来源；Jensen α 只针对 β 解释不了的那部分，二者风险口径不同。
- **[[brinson_attribution]]** — Brinson 把超额收益按资产配置/选股逐项拆解（会计式归因）；Jensen α 是单因子回归式归因。前者答"超额从哪几块来"，后者答"扣掉市场风险后还剩多少"。

参考文献：
- Jensen, M. C. (1968). The Performance of Mutual Funds in the Period 1945–1964. *Journal of Finance* 23(2): 389–416.
- Sharpe, W. F. (1964). Capital Asset Prices: A Theory of Market Equilibrium under Conditions of Risk. *Journal of Finance* 19(3): 425–442.
- Fama, E. F., & French, K. R. (1993). Common Risk Factors in the Returns on Stocks and Bonds. *Journal of Financial Economics* 33(1): 3–56.
- Carhart, M. M. (1997). On Persistence in Mutual Fund Performance. *Journal of Finance* 52(1): 57–82.
