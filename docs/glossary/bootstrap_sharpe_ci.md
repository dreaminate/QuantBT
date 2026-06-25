---
term: bootstrap_sharpe_ci
display: "自助法夏普置信区间 (Bootstrap SR CI)"
aliases:
  - bootstrap_sharpe_ci
  - bootstrap sharpe
  - sharpe confidence interval
  - 自助法夏普
  - 夏普置信区间
  - 夏普比区间估计
level: intermediate
category: metric
formula_latex: "CI_{1-\\alpha}(SR) = \\left[\\, Q_{\\alpha/2}\\!\\left(\\{SR^{*}_b\\}_{b=1}^{B}\\right),\\; Q_{1-\\alpha/2}\\!\\left(\\{SR^{*}_b\\}_{b=1}^{B}\\right) \\right]"
unit: "无量纲（与夏普同尺度，年化）"
typical_range: null
sources:
  - "Efron, Tibshirani (1993) An Introduction to the Bootstrap, Chapman & Hall"
  - "Lo (2002) The Statistics of Sharpe Ratios, Financial Analysts Journal 58(4)"
  - "Ledoit, Wolf (2008) Robust Performance Hypothesis Testing with the Sharpe Ratio, J. of Empirical Finance 15(5)"
related:
  - sharpe_ratio
  - deflated_sharpe
  - volatility
  - walk_forward
---

## L1 一句话

用重抽样估出夏普比的不确定区间。

## L2 公式与例子

夏普比（Sharpe Ratio）是一个**点估计**：算出 1.5 不代表真值就是 1.5。自助法（Bootstrap）把这条收益序列**有放回地重抽样** $B$ 次，每次重算一个夏普 $SR^{*}_b$，用这 $B$ 个值的经验分位数（percentile）围出置信区间：

$$
CI_{1-\alpha}(SR) = \left[\, Q_{\alpha/2}\!\left(\{SR^{*}_b\}_{b=1}^{B}\right),\; Q_{1-\alpha/2}\!\left(\{SR^{*}_b\}_{b=1}^{B}\right) \right]
$$

- $\{SR^{*}_b\}$：$B$ 次重抽样各自算出的夏普（$B$ 常取 1000~10000）
- $Q_p(\cdot)$：经验分布的第 $p$ 分位数；$\alpha$ 为显著性水平，95% 区间取 $\alpha=0.05$
- 一次重抽样 = 从原始收益里**有放回**地抽同样长度的新序列，再按原口径年化重算夏普

**算例**：某月频策略 36 个月，月度夏普 $SR_m=0.30$，年化 $SR = 0.30\sqrt{12} \approx 1.04$。
对这 36 个月收益做 $B=10000$ 次自助重抽样，每次重算年化夏普，排序后取第 2.5% 与 97.5% 分位数，得到约 **[0.63, 1.44]** 的 95% 置信区间。
对照 Lo (2002) 在 IID 正态假设下的解析标准误 $SE(SR)=\sqrt{(1+\tfrac12 SR^2)/T}=\sqrt{(1+0.5\cdot1.04^2)/36}\approx0.21$，正态近似区间 $1.04\pm1.96\times0.21\approx[0.63,1.44]$——两者吻合，说明此例收益接近正态；一旦收益厚尾/有自相关，bootstrap 区间会比解析公式更宽、更诚实。

## L3 业界阈值与误区

**判读参考**（区间宽度是核心信号，非固定阈值）：

| 95% CI 形态 | 解读 |
|---|---|
| 下界 > 0 且明显大于 0 | 夏普"显著为正"的频率派证据较强 |
| 下界跨过 0（如 [-0.2, 1.8]） | **无法在 95% 置信下断言策略赚钱**，多半样本太短 |
| 区间极宽（跨度 > 1.5） | 估计不稳，$T$ 不足或收益厚尾，慎用点估计 |
| 自相关/厚尾下仍只用 IID bootstrap | 区间被**低估**，需改用 block bootstrap |

经验上 $T$ 越短、收益越厚尾，区间越宽：Lo (2002) 指出在 IID 正态下 $SE(SR)\approx\sqrt{(1+0.5\,SR^2)/T}$，要把年化夏普 1 的标准误压到 0.2 以下，约需 $T\ge30$ 个月度观测。

**常见误区**：

1. **对自相关收益用 IID bootstrap**：朴素自助法假设每个收益独立可换序。但带杠杆/动量/趋势的策略收益有正自相关，逐点重抽样会**打散自相关结构、低估方差**，把区间算得过窄。Ledoit & Wolf (2008) 主张对这类序列用 **circular block bootstrap**（按块重抽样以保留时序依赖），并给出基于此的稳健夏普差异检验。

2. **把 bootstrap 区间当成"扣过偏差"**：自助区间只刻画**单条样本路径的抽样不确定性**，它**不修正多重试验/选择偏差**。你试了 200 组参数挑出最好那条，再对它做 bootstrap，区间依旧偏乐观——多重试验的过拟合要靠 [[deflated_sharpe]]（Bailey & López de Prado, 2014）或 PBO 处理，二者不可互相替代。

3. **$B$ 太小或不报告**：$B$ 决定分位数的蒙特卡洛误差。$B=100$ 时 2.5% 分位数只由极少数尾部点决定，区间端点抖动很大。Efron & Tibshirani (1993) 建议置信区间类用途 $B\ge1000$（尾部分位更敏感时取更大）；报告时应注明 $B$ 与抽样方式（IID / block）。

4. **年化口径前后不一致**：重抽样在原频率（如日/月）上做，但年化因子 $\sqrt{T}$ 必须每次对重抽样序列重算后再统一年化；若先年化点估计再缩放，会引入与 Lo (2002) 解析式不一致的偏差。

5. **区间含 0 却仍上线**：下界跨 0 等价于"无法在该置信水平拒绝夏普=0"。把这种策略当作已验证收益，是把**样本不足**误读成**真实 alpha**。

## L4 延伸阅读

- **[[sharpe_ratio]]** — 本条是夏普的区间估计版：夏普给点值，bootstrap CI 给这个点值的不确定带宽。
- **[[deflated_sharpe]]** — DSR 修正的是**多重试验选择偏差**（你试了多少次），bootstrap CI 刻画的是**单条样本的抽样波动**；维度不同、互补使用。
- **[[volatility]]** — 区间宽度本质由收益波动与样本长度共同决定；理解波动率是理解夏普标准误的前提。
- **[[walk_forward]]** — 样本内 bootstrap 区间窄、样本外（walk-forward）实测夏普却落在区间外，通常意味着过拟合或结构漂移，bootstrap 假设的"同分布重抽样"已不成立。

参考文献：
- Efron, B., & Tibshirani, R. J. (1993). *An Introduction to the Bootstrap*. Chapman & Hall/CRC.
- Lo, A. W. (2002). The Statistics of Sharpe Ratios. *Financial Analysts Journal* 58(4): 36–52.
- Ledoit, O., & Wolf, M. (2008). Robust Performance Hypothesis Testing with the Sharpe Ratio. *Journal of Empirical Finance* 15(5): 850–859.
- Bailey, D. H., & López de Prado, M. (2014). The Deflated Sharpe Ratio: Correcting for Selection Bias, Backtest Overfitting, and Non-Normality. *Journal of Portfolio Management* 40(5): 94–107.
