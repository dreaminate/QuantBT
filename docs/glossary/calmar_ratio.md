---
term: calmar_ratio
display: "卡玛比率 (Calmar Ratio)"
aliases:
  - calmar
  - calmar ratio
  - 卡玛
  - 卡玛比
  - 卡尔玛比率
  - drawdown ratio
level: beginner
category: metric
formula_latex: "Calmar = \\frac{R_{\\text{ann}}}{\\lvert MDD \\rvert}"
unit: "无量纲（年化收益 ÷ 最大回撤）"
typical_range: [-1, 5]
sources:
  - "Young (1991) Calmar Ratio: A Smoother Tool, Futures Magazine, October 1991"
  - "Bacon (2008) Practical Portfolio Performance Measurement and Attribution, 2nd ed., Wiley, Chapter 4"
related:
  - max_drawdown
  - sharpe_ratio
  - sortino_ratio
---

## L1 一句话

年化收益除以最大回撤的回报风险比。

## L2 公式与例子

卡玛比率（Calmar Ratio）把**年化收益**摊到**最大回撤（Max Drawdown, MDD）**这一根「最痛的亏损」上，回答一句话：为了赚到这些钱，历史上你最深要忍受多大的浮亏。原始定义（Young, 1991）用过去 36 个月数据，但实务中常按回测全样本年化口径计算。

$$
Calmar = \frac{R_{\text{ann}}}{\lvert MDD \rvert}
$$

- $R_{\text{ann}}$：年化收益率（几何年化，CAGR）
- $MDD$：最大回撤，取绝对值（最深峰到谷的累计跌幅）

**算例**：某策略 3 年把净值从 1.00 做到 1.91，期间最深一次从高点回撤 30%。

- 年化收益 $R_{\text{ann}} = 1.91^{1/3} - 1 \approx 0.24$（即 24%）
- 最大回撤 $\lvert MDD \rvert = 0.30$（30%）
- $Calmar = 0.24 / 0.30 = 0.80$

结果 0.80 < 1，意味着年化赚的（24%）还不够覆盖你曾经要扛的最深亏损（30%）；要等回撤过去、净值刷新高点，按这个速度还得熬一段时间。

## L3 业界阈值与误区

**阈值参考**（CTA / 对冲基金实务常用经验区间，非硬标准；口径见下方误区）：

| Calmar 区间 | 解读 |
|---|---|
| > 3 | 很高；多见于短样本或杠杆放大，须先查回测期长度与 MDD 是否被「样本太短」低估 |
| 1 ~ 3 | 实务中较为健康，CTA / 趋势策略长期常落在此带（Bacon, 2008, Ch.4） |
| 0.5 ~ 1 | 一般；年化收益尚不足以盖过一次最深回撤 |
| < 0.5 | 偏弱；为赚这点钱要忍受过大浮亏 |
| < 0 | 年化收益为负，比率失去意义（见误区 3） |

**常见误区**：

1. **拿不同样本长度直接比 Calmar**：MDD 是路径极值，样本越长越容易刷出更深的回撤，分母变大、Calmar 变小。Young（1991）原始定义刻意固定用「过去 36 个月」正是为了让不同策略在**同一时间窗**下可比。把一个跑了 1 年的策略（MDD 还没充分暴露）和一个跑了 10 年的策略比 Calmar，等于拿没经历过完整熊市的样本占便宜，是典型的伪高分。

2. **只盯单一最深回撤、忽略回撤的「形状」**：Calmar 分母只取**一个**最深点，对回撤持续多久、多频繁完全不敏感。两个 Calmar 都等于 1 的策略，一个是「跌 30% 三个月就收复」，另一个是「跌 30% 拖了三年没回本」，体验天差地别。Bacon（2008, Ch.4）因此建议 Calmar 要与回撤持续期（drawdown duration）、Sterling/Burke 等「多回撤聚合」指标并看，而非单独下结论。

3. **年化收益为负时硬算比率**：当 $R_{\text{ann}} < 0$，Calmar 变成「负数 ÷ 正数 = 负」，绝对值大小已无风险调整含义；此时应直接看「亏多少 + 回撤多深」，不要把 −0.8 当成「比 −0.3 更差」去排序——分子分母两个方向都在动，符号外的数值不可比。

4. **把 Calmar 和 MAR 混为一谈**：MAR 比率（Managed Account Reports）与 Calmar 公式同形（年化收益 ÷ MDD），但 MAR 用**自基金成立以来的全部历史**，Calmar 用**滚动近 36 个月**（Young, 1991）。引用别人报的数字前先问清用的是哪种窗口，否则等于在比两个不同口径的指标。

## L4 延伸阅读

- **[[max_drawdown]]** — Calmar 的分母。MDD 只描述「最深亏多少」这一个纯风险数字；Calmar 在它之上除以年化收益，变成「单位最深回撤换来多少收益」的回报风险比。
- **[[sharpe_ratio]]** — 同为风险调整收益比，但分母不同：夏普用**波动率**（全程上下波动），Calmar 用**最大回撤**（单次最深下行）。夏普惩罚所有波动（含向上），Calmar 只惩罚那一根最痛的下行路径，更贴近散户「最多能扛多少浮亏」的真实痛感。
- **[[sortino_ratio]]** — 索提诺用**下行波动率**做分母，是介于夏普与 Calmar 之间的折中：它惩罚所有下行波动（不只最深那次），而 Calmar 只看最深一次。三者从「全部波动 → 全部下行 → 最深下行」逐级聚焦到极端亏损。

参考文献：

- Young, T. W. (1991). Calmar Ratio: A Smoother Tool. *Futures Magazine*, October 1991.
- Bacon, C. R. (2008). *Practical Portfolio Performance Measurement and Attribution* (2nd ed.). Wiley. Chapter 4 (Risk-adjusted Return).
