---
term: deflated_sharpe
display: "折减夏普比 (Deflated Sharpe Ratio · DSR)"
aliases:
  - dsr
  - deflated sharpe
  - deflated sharpe ratio
  - 折减夏普
  - 折扣夏普
level: advanced
category: metric
formula_latex: "DSR = \\Phi\\left(\\frac{(SR - SR_0)\\sqrt{T-1}}{\\sqrt{1 - \\gamma_3 SR + \\frac{\\gamma_4 - 1}{4}SR^2}}\\right)"
unit: "概率 [0, 1]"
typical_range: [0, 1]
sources:
  - "Bailey, López de Prado (2014) The Deflated Sharpe Ratio, J. of Portfolio Management 40(5)"
  - "López de Prado (2018) Advances in Financial Machine Learning, Wiley, Chapter 11"
related:
  - sharpe_ratio
  - pbo
  - bootstrap_sharpe_ci
  - walk_forward
---

## L1 一句话

校正多次试验偏差后的 SR 真实有效概率。

## L2 公式与例子

DSR 把原始 Sharpe 转换成一个**概率值** ∈ [0, 1]：在考虑试验次数 N、收益分布偏度/峰度后，这个 SR 真有效（不是侥幸）的置信度。

$$
DSR = \Phi\left(\frac{(SR - SR_0)\sqrt{T-1}}{\sqrt{1 - \gamma_3 SR + \frac{\gamma_4 - 1}{4}SR^2}}\right)
$$

- $SR$：观测到的 Sharpe（年化）
- $SR_0 = \sqrt{2\ln N}$ 近似 + Euler 修正：N 次试验下"靠运气也能达到"的预期最大 SR
- $T$：观测期长度（日数）
- $\gamma_3$：returns 偏度；$\gamma_4$：超额峰度
- $\Phi$：标准正态 CDF

**算例**：策略 SR=1.5（年化），T=504 日（2 年），N=100 次参数搜索，returns 偏度 -0.5、峰度 8（厚尾负偏）。
$SR_0 \approx \sqrt{2\ln 100} = 3.03$，扣除 Euler 修正 ≈ 2.85 后还是远高于观测 SR=1.5。
→ $DSR \approx 0.18$。这意味着只有 18% 概率这个 1.5 的 Sharpe 是真有效，82% 是运气。

## L3 业界阈值与误区

**阈值参考**（Bailey-López de Prado 2014 / 业界共识）：

| DSR 区间 | 解读 |
|---|---|
| > 0.95 | 强证据：试验次数无法解释这个 SR |
| 0.80 ~ 0.95 | 较强，但应再做 walk-forward 验证 |
| 0.50 ~ 0.80 | 模糊；试验次数偏差可能解释一半 |
| < 0.50 | **不可信**，SR 多半是过拟合产物 |
| < 0.20 | 几乎可肯定是噪声 |

**常见误区**：

1. **不报告 N**：很多 Sharpe 论文 / 因子卖家不公开"做了多少次参数试验"。N 是 DSR 的核心输入，**没 N 就没法算 DSR**。任何不带 N 的 SR 都应该按 N ≥ 100 保守估计。
2. **N 估计过低**：用户自己写策略时 mentally try 过的参数也算试验，包括"我试了几个窗口长度感觉 20 最好"。López de Prado 2018 §11.4 强调"hidden N"通常是显式 N 的 10× 以上。
3. **忽略偏度峰度**：用 SR 而不带 $\gamma_3, \gamma_4$ 时，公式分母简化为 $\sqrt{1}$，DSR 退化为标准化的 t 检验。加密策略夜间黑天鹅（高峰度 + 负偏）下，简化版会**高估** DSR 30-50%。
4. **T 单位错配**：T 必须与 returns 序列频率匹配。日频策略 T=252 ≠ 月频策略 T=12。
5. **混淆 DSR 与 PBO**：DSR 是单策略经折减后的 SR 概率；PBO 是策略选择程序的过拟合频率。两者并用而非替代。

## L4 延伸阅读

- **[[sharpe_ratio]]** — DSR 的输入。任何报告 Sharpe > 1 都应同时给 DSR；López de Prado 2018 称"无 DSR 的 SR 是无效报告"。
- **[[pbo]]** — PBO 衡量"策略选择程序"，DSR 衡量"单策略最终值"。互补关系。
- **[[bootstrap_sharpe_ci]]** — Bootstrap SR 给的是分布置信区间（频率视角），DSR 给的是单值修正。两者方法论不同但目的一致。
- **[[walk_forward]]** — 高 DSR + 低 walk-forward OOS Sharpe 通常意味着 DSR 估计中 N 严重低估。

参考文献：
- Bailey, D. H., & López de Prado, M. (2014). The Deflated Sharpe Ratio: Correcting for Selection Bias, Backtest Overfitting, and Non-Normality. *Journal of Portfolio Management* 40(5): 94–107.
- López de Prado, M. (2018). *Advances in Financial Machine Learning*. Wiley. Chapter 11.4 (The Deflated Sharpe Ratio).
