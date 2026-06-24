---
term: walk_forward
display: "滚动样本外测试 (Walk-Forward)"
aliases:
  - walk_forward
  - walk forward
  - walk-forward analysis
  - WFA
  - 滚动样本外
  - 滚动窗口测试
  - 前推分析
  - 向前滚动测试
level: advanced
category: model
formula_latex: "\\text{for } k=1..K:\\ \\text{train on } [t_{k}^{\\text{tr},0},\\, t_{k}^{\\text{tr},1}],\\ \\text{test on } [t_{k}^{\\text{te},0},\\, t_{k}^{\\text{te},1}],\\ \\text{with } t_{k}^{\\text{tr},1} \\le t_{k}^{\\text{te},0}"
unit: "无量纲（窗口数 K 为正整数）"
typical_range: null
sources:
  - "Pardo (2008) The Evaluation and Optimization of Trading Strategies, 2nd ed., Wiley, Chapter 11 (Walk-Forward Analysis)"
  - "López de Prado (2018) Advances in Financial Machine Learning, Wiley, Chapter 7 (Cross-Validation in Finance)"
related:
  - purged_kfold
  - embargo
  - pbo
  - deflated_sharpe
---

## L1 一句话

按时间单向前推、永远用过去训练去测未来。

## L2 公式与例子

滚动样本外测试（walk-forward analysis，WFA）把历史切成一串**时间上前后相接**的窗口：每一步在一段过去数据上拟合/调参，再在**紧随其后、模型从未见过**的一段上测试，然后整体向前滚动一格，重复到数据末尾。核心约束是训练区间的终点不晚于测试区间的起点：

$$
\text{for } k = 1 \dots K:\quad \text{train on } [t_{k}^{\text{tr},0},\, t_{k}^{\text{tr},1}],\ \ \text{test on } [t_{k}^{\text{te},0},\, t_{k}^{\text{te},1}],\quad \text{s.t. } t_{k}^{\text{tr},1} \le t_{k}^{\text{te},0}
$$

把所有测试窗口的结果**首尾拼接**，得到一条不复用未来信息的样本外净值曲线。两种常见模式：

- **滑动窗口（rolling/sliding）**：训练集长度固定，整段窗口往前平移（旧数据滚出）。
- **锚定窗口（anchored/expanding）**：训练集起点不动，终点随时间外扩（训练集越来越长）。

**算例**（锚定窗口，月度再训练）：2015–2020 共 72 个月日频数据。设训练初窗 24 个月、测试窗 3 个月、步长 3 个月：

- 第 1 步：训练 2015-01 ~ 2016-12（24 月），测试 2017-01 ~ 2017-03。
- 第 2 步：训练 2015-01 ~ 2017-03（27 月，锚定外扩），测试 2017-04 ~ 2017-06。
- 依此每次训练集 +3 月、测试窗后移 3 月……到末尾共 $(72 - 24)/3 = 16$ 个不重叠的样本外测试窗口。

把这 16 段测试期收益拼起来 = 48 个月连续样本外业绩。注意：若标签跨多期（如未来 5 日收益），训练集末尾要按 [[purged_kfold]] 的逻辑净化、并对测试集前加 [[embargo]] 禁运缓冲，否则窗口交界处仍有泄漏。

## L3 业界阈值与误区

**参数与判读参考**：

| 项目 | 取值参考 | 依据 |
|---|---|---|
| 训练:测试窗口比 | 常用 3:1 ~ 4:1（如训 24 月 / 测 6~8 月） | Pardo (2008) Chapter 11 给出的实践经验区间 |
| 再训练步长 | 等于或小于测试窗（不留断点） | Pardo (2008) Chapter 11 |
| 窗口数 K | 越多越稳；K 过小则样本外统计不可信 | López de Prado (2018) Chapter 7 |
| 交界缓冲 | embargo 取持仓期 1–5%（占总样本） | López de Prado (2018) §7.4.2 |
| 效率比 walk-forward efficiency | OOS 与 IS 业绩之比，越接近 1 越稳健 | Pardo (2008) Chapter 11 |

**常见误区**：

1. **把"一次切分的训练/测试"当成滚动样本外，只测了一段未来**。单段 holdout 的样本外结论高度依赖那一段市场环境，统计量方差极大。Pardo (2008, Chapter 11) 强调 WFA 的价值正在于**多个连续前推窗口**覆盖不同市场状态，单窗口结论不具代表性。

2. **在滚动循环里反复回看同一段 OOS 调参，把样本外悄悄变成样本内**。每次看到 OOS 结果不好就回去改参数再跑，等于对测试集做了多次选择——这正是回测过拟合（backtest overfitting）的来源。López de Prado (2018, Chapter 7) 与 Bailey, Borwein, López de Prado & Zhu (2014) 指出，多重试验下样本外 Sharpe 会被系统性高估，必须用 [[pbo]]、[[deflated_sharpe]] 这类多重检验校正，而非靠"反复跑 WFA 直到好看"。

3. **窗口交界处不做净化/禁运，仍有信息泄漏**。当标签跨多根 K 线（如未来 N 日收益），训练集末尾样本的标签区间会伸进测试窗，造成前视泄漏。López de Prado (2018, §7.4.1–7.4.2) 指出必须对训练集做 purge、对测试集前缘加 embargo，否则 WFA 的"样本外"是名义上的。

4. **以为 WFA 比净化 k 折一定更可信，于是放弃过拟合校正**。WFA 严格单向、不复用未来确实更保守，但窗口少、且若在多组超参数上挑选，依然会过拟合。Bailey et al. (2014) 警告：任何回测优化流程（含 WFA）都可能产出"看起来好的"伪策略，结论强度取决于试验次数与多重检验校正，而非切分方式本身。

5. **anchored 与 rolling 不分场景乱用**。锚定窗口假设旧关系长期有效（训练集只增不减），在结构发生漂移（regime shift）的市场会被陈旧数据拖累；滑动窗口更能跟随漂移但样本量少、方差大。Pardo (2008, Chapter 11) 提示应结合策略是否依赖长期稳定关系来选窗口模式。

## L4 延伸阅读

- **[[purged_kfold]]** — 净化 k 折轮流把每折当测试集、数据被反复复用（样本效率高但仍可能过拟合）；本条严格按时间单向前推、测试集永远在训练集之后、不复用未来（更保守、样本利用率低）。二者是金融时序交叉验证的两条主路线。
- **[[embargo]]** — 禁运期是 WFA 窗口交界处的"安全缓冲"：在测试窗起点前剔掉一段训练样本，挡住因序列相关从训练集渗向测试集的泄漏。WFA 不加 embargo 时交界处仍漏。
- **[[pbo]]** — 过拟合概率（PBO）衡量"在多组配置里挑出的最佳策略其实是噪声"的概率；它正是用来校正在 WFA 上反复调参/挑参带来的乐观偏差，二者配套使用。
- **[[deflated_sharpe]]** — 折减夏普把多次试验数与非正态性折进显著性判断；WFA 跑出的高 Sharpe 应先经 DSR 折减，才知道是否真实有效，而非靠"前推测试通过"就背书。

参考文献：

- Pardo, R. (2008). *The Evaluation and Optimization of Trading Strategies* (2nd ed.). Wiley. Chapter 11 (Walk-Forward Analysis).
- López de Prado, M. (2018). *Advances in Financial Machine Learning*. Wiley. Chapter 7 (Cross-Validation in Finance), §7.4.1–7.4.2.
- Bailey, D. H., Borwein, J., López de Prado, M., & Zhu, Q. J. (2014). Pseudo-Mathematics and Financial Charlatanism: The Effects of Backtest Overfitting on Out-of-Sample Performance. *Notices of the American Mathematical Society* 61(5): 458–471.
