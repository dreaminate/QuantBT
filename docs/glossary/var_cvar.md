---
term: var_cvar
display: "在险价值 / 条件在险价值 (VaR / CVaR)"
aliases:
  - var_cvar
  - var
  - cvar
  - value at risk
  - conditional value at risk
  - expected shortfall
  - es
  - 在险价值
  - 条件在险价值
  - 风险价值
  - 预期损失
  - 预期短缺
level: intermediate
category: risk
formula_latex: "VaR_\\alpha = \\inf\\{x : P(L \\le x) \\ge \\alpha\\}, \\quad CVaR_\\alpha = E[L \\mid L \\ge VaR_\\alpha]"
unit: "货币金额或收益率（同持仓口径）"
typical_range: null
sources:
  - "Jorion (2007) Value at Risk: The New Benchmark for Managing Financial Risk, 3rd ed., McGraw-Hill"
  - "Artzner, Delbaen, Eber, Heath (1999) Coherent Measures of Risk, Mathematical Finance 9(3)"
  - "Rockafellar, Uryasev (2000) Optimization of Conditional Value-at-Risk, J. of Risk 2(3)"
  - "Basel Committee on Banking Supervision (2019) Minimum capital requirements for market risk (FRTB)"
related:
  - tail_risk
  - volatility
  - max_drawdown
  - kelly_fraction
---

## L1 一句话

给定置信度下的最大亏损与超出后的平均亏损。

## L2 公式与例子

记 $L$ 为持仓在持有期内的**损失**（亏损为正），置信水平 $\alpha$（如 0.95、0.99）。

$$
VaR_\alpha = \inf\{x : P(L \le x) \ge \alpha\}, \qquad CVaR_\alpha = E\big[L \mid L \ge VaR_\alpha\big]
$$

- **VaR（在险价值，Value at Risk）**：α 分位点处的损失门槛——"有 α 概率亏损不超过这个数"。
- **CVaR（条件在险价值，Conditional VaR；又称预期短缺 Expected Shortfall, ES）**：**一旦突破 VaR 门槛**，平均亏多少。CVaR 看的是尾巴里的均值，VaR 只看尾巴的入口。恒有 $CVaR_\alpha \ge VaR_\alpha$。

> 约定提示：上式在「$L$ 为损失（正值）、分位水平取 $\alpha$」的口径下成立，VaR 不带负号。若改用收益／盈亏 $X$（负值表亏损）描述，则需取 $1-\alpha$ 分位并加负号：$VaR_\alpha = -\inf\{x : P(X \le x) \ge 1-\alpha\}$。负号只是变量口径的转换，不改变报告出来的损失为正数。

**算例 A（参数法 · 正态假设）**：持仓 100 万元，日收益均值 $\mu=0$、日波动 $\sigma=2\%$。
正态分位数 $z_{0.95}=1.645$，$z_{0.99}=2.326$；ES 系数 $\phi(z_\alpha)/(1-\alpha)$ 在 95% 为 2.063、99% 为 2.665。
$VaR_{95} = 1.645 \times 0.02 \times 100\text{万} = 3.29\text{万元}$；
$CVaR_{95} = 2.063 \times 0.02 \times 100\text{万} = 4.13\text{万元}$。
（同法得 $VaR_{99}\approx4.65$ 万、$CVaR_{99}\approx5.33$ 万。）

**算例 B（历史模拟法）**：取最近 100 个交易日的实际日盈亏，按损失从大到小排序。
95% VaR = **第 5 大**的那笔损失（5% 的尾部入口）；95% CVaR = **最差 5 笔损失的平均**。
若最差 5 笔损失为 12、9、7、6、5 万元，则 $VaR_{95}=5\text{万元}$（第 5 大），$CVaR_{95}=(12+9+7+6+5)/5=7.8\text{万元}$。历史法不假设分布，但完全受样本窗口里有没有发生过极端日子的支配。

## L3 业界阈值与误区

VaR/CVaR **没有跨策略通用的"好/坏"阈值**——它是绝对金额（或收益率），数值大小取决于持仓规模、杠杆、置信度与持有期，所以本条 `typical_range` 标为 `null`。有意义的是**口径与方法**这张参照表：

| 维度 | 常见取值 | 出处 / 用途 |
|---|---|---|
| 置信度 α | 95% / 99% | 风控日常用 95%，资本计提历史上用 99% |
| 监管标准（市场风险） | **97.5% ES** 取代 99% VaR | Basel FRTB (BCBS, 2019) |
| 持有期 | 1 日（交易台） / 10 日（监管） | Jorion (2007) |
| 报告搭配 | VaR 与 CVaR 同时报 | CVaR 才约束尾部厚度 |

**常见误区**：

1. **VaR 不是"最大可能亏损"** —— VaR 只说"95% 的日子亏不超过它"，对**剩下 5%** 里到底亏多惨闭口不谈。两个策略 VaR 相同，尾部却可能一个 -6%、一个 -50%。这正是 CVaR/ES 被引入来补盲区的原因，也是 Basel FRTB 从 99% VaR 改用 97.5% ES 的核心动机（BCBS, 2019）。

2. **VaR 不满足次可加性，不是相干风险度量** —— 组合的 VaR 可能**大于**各部分 VaR 之和，即分散化反而"增加"了 VaR，这会误导风险预算与优化。Artzner et al. (1999) 证明 VaR 一般违反次可加性、不是相干风险度量（coherent measure），而 CVaR/ES 满足相干性四公理。要做风险优化优先用 CVaR（Rockafellar & Uryasev, 2000 给出其可凸优化的线性规划形式）。

3. **正态参数法系统性低估尾部** —— 算例 A 的正态假设在金融收益的厚尾（fat tails）面前会**低估** VaR 与 CVaR，加密永续夜间瀑布、A股跌停联动这类肥尾事件下尤甚。Jorion (2007) 强调正态 VaR 仅适用于近似正态、低杠杆情形；厚尾下应改用历史模拟、EVT 或 t 分布。

4. **历史模拟受窗口绑架，且回测期未必含危机** —— 算例 B 的历史法不假设分布，但**样本里没发生过的极端日子，VaR/CVaR 一概看不见**；若回测窗口恰好平静，估值会乐观失真。Jorion (2007) 指出历史 VaR 对窗口长度和是否覆盖压力期高度敏感，需配压力测试（stress test）补足。

## L4 延伸阅读

- **[[tail_risk]]** —— 尾部风险是"分布尾巴有多厚"的总称；VaR/CVaR 是把尾部风险**量化成一个金额**的具体工具，CVaR 尤其直接刻画尾部均值。
- **[[volatility]]** —— 波动率是全分布的二阶矩（对称看上下波动）；VaR/CVaR 只盯**下行尾部**。正态假设下两者可由 $\sigma$ 互推（见算例 A），但厚尾下 VaR/CVaR 携带波动率丢失的尾部信息。
- **[[max_drawdown]]** —— 最大回撤是**路径相关**的历史峰谷损失，已实现且单点；VaR/CVaR 是**单期、概率性**的前瞻估计。二者互补：MDD 答"历史最惨亏过多少"，VaR/CVaR 答"下一期大概率/极端情形亏多少"。
- **[[kelly_fraction]]** —— 凯利公式从增长最优角度定仓位；VaR/CVaR 从尾部损失约束定仓位上限。实务常用 VaR/CVaR 给凯利建议的激进仓位**封顶**，防尾部破产。

参考文献：

- Jorion, P. (2007). *Value at Risk: The New Benchmark for Managing Financial Risk* (3rd ed.). McGraw-Hill.
- Artzner, P., Delbaen, F., Eber, J.-M., & Heath, D. (1999). Coherent Measures of Risk. *Mathematical Finance*, 9(3), 203-228.
- Rockafellar, R. T., & Uryasev, S. (2000). Optimization of Conditional Value-at-Risk. *Journal of Risk*, 2(3), 21-41.
- Basel Committee on Banking Supervision. (2019). *Minimum capital requirements for market risk* (FRTB). Bank for International Settlements.
