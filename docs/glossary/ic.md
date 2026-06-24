---
term: ic
display: "信息系数 (Information Coefficient · IC)"
aliases:
  - ic
  - information coefficient
  - pearson ic
  - 信息系数
  - 因子预测力
level: intermediate
category: factor
formula_latex: "IC_t = \\mathrm{corr}\\left(f_{t},\\; r_{t \\to t+1}\\right) = \\frac{\\sum_{i=1}^{N}(f_{i,t}-\\bar{f}_t)(r_{i,t+1}-\\bar{r}_{t+1})}{\\sqrt{\\sum_{i=1}^{N}(f_{i,t}-\\bar{f}_t)^2}\\sqrt{\\sum_{i=1}^{N}(r_{i,t+1}-\\bar{r}_{t+1})^2}}"
unit: "相关系数 [-1, 1]（无量纲）"
typical_range: [-0.1, 0.1]
sources:
  - "Grinold, Kahn (2000) Active Portfolio Management, 2nd ed., McGraw-Hill, Chapter 6"
  - "López de Prado (2018) Advances in Financial Machine Learning, Wiley, Chapter 8"
related:
  - rank_ic
  - ic_ir
  - information_ratio
  - alpha101_concept
---

## L1 一句话

因子值与下期收益的横截面相关系数。

## L2 公式与例子

IC（Information Coefficient，信息系数）衡量在同一个时间截面上，因子值排序能多大程度预测**下一期**收益。它就是因子值 $f_t$ 与前瞻收益 $r_{t\to t+1}$ 的 Pearson 相关系数，逐个截面算出一个 IC，再看时序均值。

$$
IC_t = \mathrm{corr}\left(f_{t},\; r_{t \to t+1}\right) = \frac{\sum_{i=1}^{N}(f_{i,t}-\bar{f}_t)(r_{i,t+1}-\bar{r}_{t+1})}{\sqrt{\sum_{i=1}^{N}(f_{i,t}-\bar{f}_t)^2}\sqrt{\sum_{i=1}^{N}(r_{i,t+1}-\bar{r}_{t+1})^2}}
$$

- $f_{i,t}$：第 $i$ 只标的在 $t$ 时刻的因子值；$\bar{f}_t$：该截面因子均值
- $r_{i,t+1}$：第 $i$ 只标的从 $t$ 到 $t+1$ 的前瞻收益；$\bar{r}_{t+1}$：该截面收益均值
- $N$：该截面标的数；用 Pearson 相关即"普通 IC"，换成 Spearman 秩相关即 [[rank_ic]]

**算例**（单截面，5 只标的，因子已对齐到下期收益）：

| 标的 | 因子值 $f$ | 下期收益 $r$ |
|---|---|---|
| A | 2 | 3% |
| B | 1 | 1% |
| C | 0 | 0% |
| D | -1 | -2% |
| E | -2 | -2% |

$\bar{f}=0$，$\bar{r}=0\%$。分子 $\sum (f-\bar f)(r-\bar r)=2(0.03)+1(0.01)+0+(-1)(-0.02)+(-2)(-0.02)=0.06+0.01+0.02+0.04=0.13$。
$\sqrt{\sum(f-\bar f)^2}=\sqrt{4+1+0+1+4}=\sqrt{10}=3.162$；$\sqrt{\sum(r-\bar r)^2}=\sqrt{0.0009+0.0001+0+0.0004+0.0004}=\sqrt{0.0018}=0.04243$。
$IC = 0.13/(3.162\times0.04243)=0.13/0.1342 \approx \mathbf{0.969}$ —— 接近完美正相关（因子排序几乎完全对应收益排序）。真实股票截面单期 IC 极少这么高，通常在 ±0.1 内。

## L3 业界阈值与误区

**阈值参考**（均指因子时序的**平均 IC**，月频股票截面；非单期值）：

| 平均 IC（绝对值） | 解读 |
|---|---|
| > 0.10 | 罕见，多为偶然/数据问题/前视，需重查 |
| 0.05 ~ 0.10 | 强因子；Grinold-Kahn (2000) 视 0.05+ 为有实战价值 |
| 0.02 ~ 0.05 | 一般有效因子，靠组合分散与 breadth 放大 |
| 0.00 ~ 0.02 | 弱/可疑，单独难盈利 |
| < 0 | 反向；可考虑取负或剔除 |

注：IC 的统计显著性要看 [[ic_ir]]（IC 均值/IC 标准差，即 IC 的信息率），而非单看 IC 大小。

**常见误区**：

1. **拿单期 IC 下结论**。单截面 IC 噪声极大，方差约 $1/(N-1)$（López de Prado 2018, Ch. 8 论因子重要性时强调横截面统计量的样本依赖）。必须看多期 IC 序列的均值与稳定性（即 IC-IR），单期 0.3 可能纯属运气。

2. **用 Pearson IC 而忽视厚尾与离群值**。Pearson IC 对极端因子值/收益敏感，少数离群股可主导整个相关系数。业界普遍优先报告 Spearman 秩相关的 [[rank_ic]]，对单调非线性关系与离群更稳健（Grinold & Kahn, 2000, Ch. 6 讨论 IC 时即建议用排序口径降低对异常值的依赖）。

3. **前视偏差（look-ahead）污染 IC**。把 $t$ 时刻还拿不到的数据（未来财报、当日收盘后才公布的指标）算进 $f_t$，会把"已实现收益"泄进因子，IC 被人为抬高。这是回测 IC 远高于实盘的头号原因（López de Prado, 2018, Ch. 7-8 关于信息泄漏）。任何异常高的 IC（>0.1）应先排查时间对齐。

4. **混淆 IC 与 IR（信息比率）**。IC 是因子预测力（相关系数），[[information_ratio]] 是组合超额收益/跟踪误差。二者通过"基本面法则"$IR \approx IC\sqrt{BR}$ 关联（Grinold & Kahn, 2000：$BR$ 为独立下注次数/breadth），但不可互相替代——高 IC 若 breadth 太小，IR 仍可能很低。

5. **不区分 IC 符号与因子方向**。IC 为负只说明因子与收益反向，不代表因子无效；取负方向即可用。判定"有没有用"要看 $|IC|$ 与其稳定性，不是看正负。

## L4 延伸阅读

- **[[rank_ic]]** — 本条用 Pearson（线性相关）；Rank IC 用 Spearman 秩相关，对离群值与单调非线性更稳健，业界默认口径。
- **[[ic_ir]]** — 本条是单期/平均相关系数的"强度"；IC-IR 是 IC 均值除以 IC 标准差，衡量该预测力的"稳定性/显著性"，比 IC 大小更决定能否实战。
- **[[information_ratio]]** — IC 是因子层面的预测力；IR 是组合层面的超额收益风险比，二者经基本面法则 $IR \approx IC\sqrt{BR}$ 连接，但层级不同。
- **[[alpha101_concept]]** — Alpha101 是一批具体因子表达式；IC 是评判任一这类 alpha 是否有预测力的标准指标。

参考文献：

- Grinold, R. C., & Kahn, R. N. (2000). *Active Portfolio Management: A Quantitative Approach for Producing Superior Returns and Controlling Risk* (2nd ed.). McGraw-Hill. Chapter 6 (Information Analysis) & 基本面法则 $IR=IC\sqrt{BR}$.
- López de Prado, M. (2018). *Advances in Financial Machine Learning*. Wiley. Chapters 7–8 (Cross-Validation in Finance; Feature Importance).
