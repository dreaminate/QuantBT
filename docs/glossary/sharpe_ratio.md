---
term: sharpe_ratio
display: "夏普比率 (Sharpe Ratio)"
aliases:
  - sharpe
  - sharpe ratio
  - 夏普
  - 夏普比
level: beginner
category: metric
formula_latex: "SR = \\frac{E[R_p - R_f]}{\\sigma_p} \\cdot \\sqrt{T}"
unit: "无量纲（年化）"
typical_range: [-2, 4]
sources:
  - "Sharpe (1966) Mutual Fund Performance, J. of Business 39(1)"
  - "Lo (2002) The Statistics of Sharpe Ratios, Financial Analysts Journal"
related:
  - sortino_ratio
  - information_ratio
  - deflated_sharpe
  - max_drawdown
---

## L1 一句话

单位风险下的超额收益，衡量"赚得稳不稳"。

## L2 公式与例子

$$
SR = \frac{E[R_p - R_f]}{\sigma_p} \cdot \sqrt{T}
$$

- $R_p$：策略收益序列；$R_f$：无风险利率（A股取 1 年国债收益率 ≈ 2.5%，加密策略一般取 0）
- $\sigma_p$：策略收益标准差
- $T$：年化系数（日频 252，小时频 252×24，等）

**算例**：日收益 60 个点，均值 0.0008、标准差 0.012、$R_f=0$。
$SR = (0.0008 / 0.012) \cdot \sqrt{252} \approx 1.06$。

## L3 业界阈值与误区

**阈值参考**（仅对**未经多次试验筛选**的单一回测）：

| SR 区间 | 解读 |
|---|---|
| < 0.5 | 不可用 |
| 0.5 ~ 1.0 | 一般，需检查 PBO |
| 1.0 ~ 2.0 | 较好 |
| > 2.0 | 优秀，但**强烈怀疑过拟合**，必看 Deflated Sharpe |

**常见误区**：

1. **多次试验偏差** — 试 100 组参数挑最好的，SR=2 没意义。这是 Bailey-Lopez de Prado (2014) 提出 Deflated Sharpe (DSR) 的原因。诊断台看到 SR > 1.5 且无 DSR 数据应主动追问。
2. **频率单位不对齐** — 日频 SR 和小时频 SR 不能直接比较。年化系数 $\sqrt{T}$ 必须匹配收益序列频率。
3. **正态假设失效** — SR 隐含收益正态分布；加密永续夜间黑天鹅事件下，SR 会高估稳定性。配 Sortino Ratio 看下行专属波动更稳。
4. **杠杆不变性的误解** — 理论上加杠杆不变 SR，但实际成交滑点/资金费率会拖低 SR；从纸面 SR 到实盘 SR 通常打 70%~80% 折扣。

## L4 延伸阅读

- **[[sortino_ratio]]** — 同概念但只看下行波动，对厚尾收益更鲁棒。
- **[[information_ratio]]** — SR 的"相对版"：以 benchmark 为参考的超额风险调整收益。
- **[[deflated_sharpe]]** — Bailey-Lopez de Prado 2014，校正多次试验导致的 SR 膨胀。**任何 SR > 1 的回测都应配 DSR 同时报告**。
- **[[max_drawdown]]** — SR 不反映尾部风险；同一 SR 下 max drawdown -10% 和 -50% 体验天差地别。

参考文献：
- Sharpe, W. F. (1966). Mutual Fund Performance. *J. of Business* 39(1).
- Lo, A. W. (2002). The Statistics of Sharpe Ratios. *Financial Analysts Journal*.
- Bailey, D. H., & Lopez de Prado, M. (2014). The Deflated Sharpe Ratio. *J. of Portfolio Management* 40(5).
