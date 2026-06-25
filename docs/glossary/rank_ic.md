---
term: rank_ic
display: "排序信息系数 (Rank IC · Spearman IC)"
aliases:
  - rank_ic
  - rank ic
  - spearman ic
  - 排序ic
  - 排序信息系数
  - 秩相关ic
level: intermediate
category: factor
formula_latex: "RankIC_t = \\rho_{Spearman}\\big(rank(f_{t}),\\, rank(r_{t+1})\\big) = 1 - \\frac{6 \\sum_{i=1}^{n} d_i^2}{n(n^2 - 1)}"
unit: "相关系数 [-1, 1]（无单位）"
typical_range: [-0.15, 0.15]
sources:
  - "Grinold, Kahn (2000) Active Portfolio Management, 2nd ed., McGraw-Hill, Ch. 6"
  - "Spearman (1904) The Proof and Measurement of Association between Two Things, American J. of Psychology 15(1)"
related:
  - ic
  - ic_ir
  - alpha101_concept
---

## L1 一句话

因子值与未来收益的秩相关系数。

## L2 公式与例子

Rank IC 是把每期横截面的**因子值排名**与**下一期收益排名**做 Spearman 秩相关（Spearman rank correlation）。它等价于"对两组排名做 Pearson 相关"。当横截面内无并列（no ties）时可用简化式：

$$
RankIC_t = 1 - \frac{6 \sum_{i=1}^{n} d_i^2}{n(n^2 - 1)}
$$

- $n$：当期横截面股票数
- $d_i$：第 $i$ 只股票的「因子排名 − 下期收益排名」之差
- $f_t$：$t$ 期末因子值；$r_{t+1}$：$t \to t+1$ 的前向收益（forward return）

**算例**（$n=5$，某期 5 只股票）：

| 股票 | 因子值 | 因子排名 | 下期收益 | 收益排名 | $d_i$ | $d_i^2$ |
|---|---|---|---|---|---|---|
| A | 0.8 | 4 | +4% | 3 | 1 | 1 |
| B | 0.3 | 3 | +1% | 2 | 1 | 1 |
| C | -0.2 | 2 | +5% | 4 | -2 | 4 |
| D | 1.5 | 5 | +6% | 5 | 0 | 0 |
| E | -0.9 | 1 | -5% | 1 | 0 | 0 |

$\sum d_i^2 = 6$，$n(n^2-1) = 5 \times 24 = 120$，代入：

$$
RankIC = 1 - \frac{6 \times 6}{120} = 1 - 0.30 = 0.70
$$

误差几乎全来自 C（因子排名低却跑出高收益）。注意单期 $n=5$ 仅为演示，实盘要求 $n$ 足够大（见 L3 误区 2）。把每期 $RankIC_t$ 在时间上排成序列，其**均值**衡量因子方向性强度，**标准差**衡量稳定性，二者之比即 [[ic_ir]]。

## L3 业界阈值与误区

**阈值参考**（针对**单期 Rank IC 时序均值**，月频/周频股票多因子场景）：

| 平均 Rank IC（绝对值） | 解读 |
|---|---|
| < 0.02 | 接近噪声，难以单独支撑组合 |
| 0.02 ~ 0.05 | 弱但可用，需进 IC-IR / 多因子合成判断 |
| 0.05 ~ 0.10 | 业界视为"较好"的单因子水平 |
| > 0.10 | 偏高，应先排查前视偏差 / 数据问题再相信 |

阈值口径依赖频率、票池与去极值方式，跨研究不可直接比较。Grinold & Kahn (2000) 的「Fundamental Law of Active Management」给出 $IR \approx IC \times \sqrt{breadth}$，说明即便单期 IC 仅 0.03，在足够独立的 breadth 下仍能累积出可观信息率——这也是低 IC 因子仍有价值的根据。

**常见误区**：

1. **把 Rank IC 当 Pearson IC 比较**。普通 [[ic]] 是因子值与收益的 Pearson 相关，对离群值与厚尾敏感；Rank IC 只用排名，对离群点更稳健（outlier-robust），同时因只依赖单调序而非线性关系，更能捕捉单调非线性。同一因子两者数值通常不同，混用阈值会误判。Spearman (1904) 即把相关定义在秩上以降低分布假设依赖。
2. **横截面样本太小**。$n$ 很小时单期 Rank IC 方差极大：$n=5$ 时即便因子完全无效，$|RankIC|>0.5$ 也常见（自由度仅 $n-2=3$）。机构通常要求每期 $n \geq 30$ 才看单期值，更看时序均值与 t 统计量。这是 Spearman 相关在小样本下的标准抽样性质（见 Hollander, Wolfe & Chicken 2014《Nonparametric Statistical Methods》第 8 章秩相关分布）。
3. **未对齐前向收益 / 引入前视偏差**。$f_t$ 必须严格用 $t$ 期末可得信息，$r_{t+1}$ 是其后收益。若不慎用了同期或含未来调整的数据，Rank IC 会被人为抬高——这正是 [[look_ahead_bias]] 在因子检验上的典型表现。López de Prado (2018)《Advances in Financial Machine Learning》第 7 章强调因子标签必须时序无泄漏。
4. **只看均值不看符号稳定性**。两个因子均值同为 0.05，一个每期稳定为正、一个在 ±0.3 间剧烈翻号，前者远更可用。单看均值会漏掉这层信息——稳定性应交给 [[ic_ir]] 度量。
5. **忽视并列处理**。横截面有大量并列值（如离散打分因子）时，简化式 $1 - 6\sum d^2 / n(n^2-1)$ 不再精确，须用带 tie 修正的 Spearman 公式或直接对排名取 Pearson 相关，否则系统性偏差。

## L4 延伸阅读

- **[[ic]]** — 普通 IC 用 Pearson 相关（因子原始值），Rank IC 用 Spearman（排名）。本条对离群值更稳健、对单调非线性关系更能捕捉，但损失了幅度信息。
- **[[ic_ir]]** — 把本条的时序均值除以时序标准差，得 IC 信息率，衡量"方向对得稳不稳"；本条只给单期方向强度。
- **[[alpha101_concept]]** — Alpha101 类公式化因子常以 Rank IC 作为横截面有效性的首要筛选指标；本条是评估那类因子的标准量尺之一。

参考文献：

- Spearman, C. (1904). The Proof and Measurement of Association between Two Things. *American Journal of Psychology* 15(1): 72–101.
- Grinold, R. C., & Kahn, R. N. (2000). *Active Portfolio Management* (2nd ed.). McGraw-Hill. Chapter 6 (Information Coefficient) & Chapter 5 (Fundamental Law of Active Management).
- Hollander, M., Wolfe, D. A., & Chicken, E. (2014). *Nonparametric Statistical Methods* (3rd ed.). Wiley. Chapter 8 (The Spearman Rank Correlation Coefficient).
- López de Prado, M. (2018). *Advances in Financial Machine Learning*. Wiley. Chapter 7 (Cross-Validation and Labeling).
