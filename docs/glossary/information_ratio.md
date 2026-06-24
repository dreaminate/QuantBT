---
term: information_ratio
display: "信息比率 (Information Ratio · IR)"
aliases:
  - information_ratio
  - information ratio
  - ir
  - 信息比率
  - 信息比
related:
  - sharpe_ratio
  - alpha
  - ic_ir
  - brinson_attribution
  - beta
level: intermediate
category: metric
formula_latex: "IR = \\frac{E[R_p - R_b]}{\\sigma(R_p - R_b)} \\cdot \\sqrt{T}"
unit: "无量纲（年化）"
typical_range: [-1, 1.5]
sources:
  - "Grinold, Kahn (2000) Active Portfolio Management, 2nd ed., McGraw-Hill"
  - "Goodwin (1998) The Information Ratio, Financial Analysts Journal 54(4)"
---

## L1 一句话

单位主动风险下的超额收益。

## L2 公式与例子

$$
IR = \frac{E[R_p - R_b]}{\sigma(R_p - R_b)} \cdot \sqrt{T}
$$

- $R_p$：策略收益序列；$R_b$：基准（benchmark）收益序列，如沪深300、BTC 买入持有
- $R_p - R_b$：主动收益（active return），其均值即年化 alpha
- $\sigma(R_p - R_b)$：主动收益的标准差，即跟踪误差（tracking error，亦称主动风险）
- $T$：年化系数（日频 252，小时频 252×24）

与夏普比率（Sharpe Ratio）的唯一区别：分母从"绝对波动 $\sigma_p$"换成"相对基准的跟踪误差"，无风险利率换成基准收益。基准取无风险利率时，IR 退化为 SR。

**算例**：60 个交易日，策略日均收益 0.0010、基准日均收益 0.0006，主动日收益序列标准差 0.005。

- 主动收益均值 $= 0.0010 - 0.0006 = 0.0004$
- 日频 IR $= 0.0004 / 0.005 = 0.08$
- 年化 IR $= 0.08 \cdot \sqrt{252} \approx 1.27$

> 注意：此处年化 1.27 仅为演示 $\sqrt{T}$ 年化换算的算术过程，**并非理想或正常水平**。1.27 已落入下方 L3 阈值表的可疑带（> 1.0），且此例仅 60 个交易日、为裸回测值。实盘出现此量级的年化 IR，应优先警惕基准选错或过拟合，而非视为优秀（详见 L3）。

## L3 业界阈值与误区

**阈值参考**（来自 Grinold & Kahn, 2000，针对机构主动管理人**年化、扣费后**的水平，非单次回测裸值）：

| 年化 IR | 解读（Grinold & Kahn, 2000） |
|---|---|
| < 0 | 跑输基准，主动管理为负贡献 |
| ~0.5 | 较好（good） |
| ~0.75 | 很好（very good） |
| ~1.0 | 卓越（exceptional），实盘长期能稳住者极少 |
| > 1.0 | 罕见；裸回测出现时**强烈怀疑过拟合或基准选错** |

Grinold & Kahn 给出的"主动管理基本定律"（Fundamental Law of Active Management）把 IR 拆为：$IR \approx IC \cdot \sqrt{N}$，其中 IC 为信息系数、$N$ 为独立下注次数（breadth）——即"预测得多准"乘以"下注得多广"。

**常见误区**：

1. **基准（benchmark）选错使 IR 失真** — IR 完全相对于所选基准。拿股票策略对比无风险利率、或加密多头策略对比"全 0 现金"基准，会把市场 beta 收益误算成 alpha，IR 虚高。Goodwin (1998) 强调 IR 的可比性前提是基准与策略风格匹配；基准须事前确定，不可事后挑一个让 IR 最好看的。
2. **跟踪误差被人为压低则 IR 虚高** — 分母是主动风险。若策略大部分仓位复制基准、只在边缘做小幅偏离，跟踪误差极小，少量 alpha 也能算出很高 IR，但这种"伪主动"（closet indexing）实际承担风险有限、可扩展性差。López de Prado (2018, AFML) 提醒任何风险调整比率都需配合多次试验偏差检验，单看高 IR 不足为信。
3. **把 IR 当 SR 跨频率/跨基准直接比较** — 不同基准、不同频率下的 IR 不可直接排序。年化系数 $\sqrt{T}$ 必须匹配收益频率（Sharpe, 1994 对夏普类比率的频率换算同样适用于 IR）；且两个策略若基准不同，IR 高者未必更优。
4. **样本内 IR 当作实盘预期** — 裸回测 IR 隐含正态、无成本假设。扣除滑点（slippage）、资金费率与交易成本后，主动收益均值会被侵蚀而跟踪误差几乎不变，实盘 IR 通常显著低于纸面值（López de Prado, 2018）。

## L4 延伸阅读

- **[[sharpe_ratio]]** — IR 的"绝对版"：分母用总波动而非跟踪误差、参照无风险利率而非基准。基准取无风险利率时两者相等。
- **[[alpha]]** — IR 的分子（年化主动收益均值）正是 alpha；IR 等于"每单位主动风险换来多少 alpha"。
- **[[ic_ir]]** — 因子研究里的同名 IR：IC 的均值 / IC 的标准差，是基本定律 $IR \approx IC \cdot \sqrt{N}$ 中 IC 维度的稳定性度量，与组合层 IR 同源不同层。
- **[[brinson_attribution]]** — 把 IR 的分子（主动收益）按配置/选股归因拆解，回答"超额收益来自哪"，与 IR 的"超额收益值多少风险"互补。
- **[[beta]]** — IR 的隐含前提是已剥离市场 beta；若基准未覆盖策略的市场暴露，残留 beta 收益会污染 IR 的 alpha 解释。

参考文献：
- Grinold, R. C., & Kahn, R. N. (2000). *Active Portfolio Management* (2nd ed.). McGraw-Hill.
- Goodwin, T. H. (1998). The Information Ratio. *Financial Analysts Journal* 54(4).
- Sharpe, W. F. (1994). The Sharpe Ratio. *J. of Portfolio Management* 21(1).
- López de Prado, M. (2018). *Advances in Financial Machine Learning*. Wiley.
