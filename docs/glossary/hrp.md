---
term: hrp
display: "层次风险平价 (Hierarchical Risk Parity · HRP)"
aliases:
  - hrp
  - hierarchical risk parity
  - 层次风险平价
  - 分层风险平价
  - 层级风险平价
level: intermediate
category: portfolio
formula_latex: "w_i \\propto \\frac{1}{\\sigma_i}, \\quad \\alpha = 1 - \\frac{\\tilde{V}_{1}}{\\tilde{V}_{1} + \\tilde{V}_{2}}, \\quad \\tilde{V}_{k} = \\tilde{w}_{k}^{\\top} V_{k} \\tilde{w}_{k}"
unit: "权重向量（和为 1，无量纲）"
typical_range: null
sources:
  - "López de Prado (2016) Building Diversified Portfolios that Outperform Out of Sample, J. of Portfolio Management 42(4): 59–69"
  - "López de Prado (2018) Advances in Financial Machine Learning, Wiley, Chapter 16"
related:
  - mean_variance
  - risk_parity
  - max_drawdown
  - bootstrap_sharpe_ci
---

## L1 一句话

用相关性聚类分层分配风险的配置法。

## L2 公式与例子

HRP（Hierarchical Risk Parity，层次风险平价）不求逆协方差矩阵，分三步：① 用相关性距离对资产做层次聚类（tree clustering）；② 按聚类顺序重排协方差矩阵，使相似资产相邻（quasi-diagonalization，拟对角化）；③ 自上而下递归二分（recursive bisection），每次按两个子簇的逆方差把风险预算劈开。

每一步二分时，先在簇内按逆方差给临时权重 $\tilde{w}_k$（inverse-variance portfolio），再算子簇的组合方差 $\tilde{V}_k$，最后用下式决定左/右两簇各拿多少：

$$
\tilde{V}_{k} = \tilde{w}_{k}^{\top} V_{k} \tilde{w}_{k}, \qquad
\alpha = 1 - \frac{\tilde{V}_{1}}{\tilde{V}_{1} + \tilde{V}_{2}}
$$

左簇权重整体乘 $\alpha$，右簇乘 $(1-\alpha)$，方差大的簇拿到的因子更小。

**算例**（3 资产，年化波动率 $\sigma_A=10\%,\ \sigma_B=10\%,\ \sigma_C=40\%$；设 A、B 高度相关先聚成一簇，C 单独一簇）：

1. 第一次二分，簇 1 = {A, B}，簇 2 = {C}。簇内逆方差权重：A、B 各 0.5，C 为 1.0。
2. 簇方差：A、B 相关系数取 0.9 时，$\tilde{V}_1 = 0.5^2(0.01+0.01) + 2(0.5)(0.5)(0.9)(0.1)(0.1) = 0.0095$；$\tilde{V}_2 = 0.40^2 = 0.16$。
3. $\alpha = 1 - \dfrac{0.0095}{0.0095+0.16} = 0.944$ → 簇 {A,B} 共拿 94.4%，C 拿 5.6%。
4. 簇内再二分，A、B 平分 → $w_A=w_B=0.472,\ w_C=0.056$。

对比朴素逆方差法（全体按 $1/\sigma_i^2$ 归一）只给 C 约 3.0%——它把高度相关的 A、B 当成两个独立分散来源，于是过度向 {A,B} 倾斜。HRP 因为先把 A、B 聚成一簇再在簇间分配，给 C 的 5.6% 更接近"两个独立风险源各半"的直觉。资产越多、相关结构越复杂，这一差异越显著，是 HRP 与逐资产逆方差的本质区别。

## L3 业界阈值与误区

HRP 没有"夏普 > 2 才合格"这类单一阈值，它是配置**方法**而非评分指标。下表汇总各方法的可比口径（基于 López de Prado 2016 蒙特卡洛实验的定性结论，非保证数字）：

| 维度 | 均值方差 (MVO) | 朴素风险平价 (RP) | HRP |
|---|---|---|---|
| 是否求逆协方差 | 是（病态时不稳） | 否（仅用对角/迭代） | 否 |
| 需要预期收益 | 需要 | 不需要 | 不需要 |
| 利用相关性结构 | 全矩阵 | 仅方差/总风险贡献 | 层次聚类 |
| OOS 方差稳定性 | 最差（对噪声敏感） | 居中 | 实验中最稳 |
| 计算复杂度 | $O(N^3)$ 求逆 | 迭代 | $O(N^2)$ 聚类 + 递归 |

**常见误区**：

1. **把 HRP 当"必然更高夏普"的升级版**。López de Prado (2016) 的核心论点是**样本外方差更低、对估计误差更鲁棒**，而非样本内夏普更高——样本内 MVO 一定在均值方差有效前沿上（理论最优），HRP 不是。误把"OOS 更稳"读成"收益更高"是过度推销。

2. **协方差估计才是真瓶颈，被聚类步骤掩盖**。HRP 回避了求逆，但聚类、拟对角化、递归二分全部喂入同一个估计协方差矩阵 $V$。若 $V$ 由短样本估计（$T < N$ 时甚至奇异），聚类结构本身就不稳定。López de Prado (2018, Ch.16) 与 Ledoit & Wolf (2004) 都强调：先做 shrinkage（协方差收缩）再聚类，否则换一批样本聚类树会大变。

3. **链接法（linkage method）与距离度量随手选**。HRP 默认用相关性距离 $d_{ij}=\sqrt{\tfrac{1}{2}(1-\rho_{ij})}$ 加 single linkage，但 single linkage 易产生"链式效应"（chaining），把弱相关资产串成一长链。换 ward/complete linkage 会得到不同权重。这是 HRP 的隐藏自由度，调它等于在做隐式参数搜索，应纳入过拟合预算（见 [[bootstrap_sharpe_ci]] 思路对配置法做重采样稳定性检验）。

4. **拿单条历史回测当"OOS 更稳"的证据**。HRP 的优势是在**重复抽样/蒙特卡洛**下方差更小的统计结论；单条历史路径上 MVO 偶尔会赢。要复现"更稳"必须做 walk-forward 或 bootstrap 多次重估，看权重与回撤分布，而非比一次回测的终值。

5. **忽略换手与交易成本**。聚类树会随相关结构漂移，相关性突变（如危机期 correlation → 1）时 HRP 权重可能整簇平移，换手率上升。López de Prado 原文为说明方法未计成本；落地需自行加换手约束或权重平滑。

## L4 延伸阅读

- **[[mean_variance]]** — Markowitz 均值方差是 HRP 要替代的基准：MVO 求逆协方差、需预期收益、样本内最优但对估计误差极敏感；HRP 不求逆、不需预期收益，牺牲样本内最优换样本外稳健。
- **[[risk_parity]]** — 朴素风险平价按总风险贡献均摊、把资产当扁平列表；HRP 在风险平价基础上加了**层次聚类**，先分组再在组间/组内分配风险，避免把一组高度相关资产误当独立分散源。
- **[[max_drawdown]]** — HRP 的卖点常以"样本外最大回撤更小/更稳"呈现；最大回撤是验证这一主张的关键 OOS 指标，应在 walk-forward 下比较 HRP 与 MVO 的回撤分布而非单点。
- **[[bootstrap_sharpe_ci]]** — HRP "更稳"是统计性结论，需用 bootstrap/蒙特卡洛重采样估配置法的权重与绩效分布；同一思路可用来检验 HRP 在不同 linkage/距离选择下的稳定性。

参考文献：
- López de Prado, M. (2016). Building Diversified Portfolios that Outperform Out of Sample. *Journal of Portfolio Management* 42(4): 59–69.
- López de Prado, M. (2018). *Advances in Financial Machine Learning*. Wiley. Chapter 16 (Machine Learning Asset Allocation).
- Ledoit, O., & Wolf, M. (2004). A Well-Conditioned Estimator for Large-Dimensional Covariance Matrices. *Journal of Multivariate Analysis* 88(2): 365–411.
- Markowitz, H. (1952). Portfolio Selection. *Journal of Finance* 7(1): 77–91.
