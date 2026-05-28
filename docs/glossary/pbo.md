---
term: pbo
display: "回测过拟合概率 (PBO / CSCV)"
aliases:
  - pbo
  - probability of backtest overfitting
  - cscv
  - combinatorially symmetric cross-validation
  - 过拟合概率
  - 回测过拟合
level: intermediate
category: risk
formula_latex: "PBO = \\Pr\\left[\\text{rank}_{OOS}(\\text{best}_{IS}) \\leq \\frac{N}{2}\\right]"
unit: "概率 [0, 1]"
typical_range: [0, 1]
sources:
  - "Bailey, Borwein, López de Prado, Zhu (2017) The Probability of Backtest Overfitting, J. of Computational Finance"
  - "López de Prado (2018) Advances in Financial Machine Learning, Wiley, Chapter 11-12"
related:
  - deflated_sharpe
  - sharpe_ratio
  - walk_forward
  - purged_kfold
---

## L1 一句话

样本内最优策略在样本外掉到中位数以下的概率。

## L2 公式与例子

CSCV (Combinatorially Symmetric Cross-Validation) 算法：

1. 把 returns 矩阵（行=时间，列=N 个策略/参数配置）按时间切成 S 段（S 必须为偶数，常用 S=16）
2. 枚举所有从 S 段中选 S/2 段当 IS 的组合，共 $C(S, S/2)$ 个（S=16 时为 12,870）
3. 每个组合下：在 IS 选 Sharpe 最高的策略，记录它在剩余 S/2 段（OOS）的排名
4. $PBO = \Pr[\text{OOS rank of IS best} \leq N/2]$

$$
PBO = \frac{1}{|C|} \sum_{c \in C} \mathbb{1}\left[\lambda_c \leq 0\right], \quad \lambda_c = \log\frac{\bar{\omega}_c}{1 - \bar{\omega}_c}
$$

其中 $\bar{\omega}_c$ 是 IS 最优策略在 OOS 的相对排名 (0 到 1)。

**算例**：N=100 个参数组合 × 252 日 returns，S=16。算出 PBO=0.55 → 样本内最优策略**有 55% 概率**在样本外跑赢一半都不到。这是过拟合的强信号。

## L3 业界阈值与误区

**阈值参考**（Bailey & López de Prado 2017 / 业界共识）：

| PBO 区间 | 解读 |
|---|---|
| < 0.2 | 过拟合概率低，可信 |
| 0.2 ~ 0.4 | 警惕，建议补充 walk-forward |
| 0.4 ~ 0.6 | 过拟合显著，慎用 |
| > 0.6 | **强烈过拟合，应该拒绝该策略** |

**常见误区**：

1. **单策略仍计算 PBO**：PBO 的输入**必须**是多策略 performance matrix（N ≥ 10 个不同参数/标的/规则的对比）。对单一回测算 PBO 是概念错误。López de Prado 2018 §11 明确指出 PBO 衡量的是 "策略选择程序" 的可靠性，不是 "单个策略" 的可靠性。
2. **S 取奇数**：CSCV 要求 S 必须为偶数（才能均分 IS/OOS）。一些实现允许 S=15 静默运行，结果不可信。**审计点：S=16 必须看到 $C(16,8)=12870$ 这个组合数被正确枚举**。
3. **采样组合而非枚举**：原论文是"对称枚举所有 $C(S,S/2)$ 组合"。一些实现采样 1000 个组合以加速，但这破坏对称性，PBO 会偏差。
4. **混淆 PBO 与 p-value**：PBO 不是统计学意义上的过拟合假设检验 p-value，而是基于试验次数的频率估计。两者数值不可互换。
5. **N 太小**：N < 10 时 PBO 估计噪声极大；建议 N ≥ 50 个策略变体。

## L4 延伸阅读

- **[[deflated_sharpe]]** — DSR 是 PBO 的"指标版"姊妹工具，校正多次试验导致的 SR 膨胀。PBO 给概率，DSR 给折减后的 SR。两者应并用：高 SR + 低 PBO + 高 DSR 才算证据完整。
- **[[walk_forward]]** — Walk-forward 是 PBO 的"前瞻验证"补充：PBO 是后视统计推断，walk-forward 是滚动 OOS 真测。两者结论不一致时优先 walk-forward。
- **[[purged_kfold]]** — Purged k-fold + Embargo 是数据切分层防过拟合，PBO 是结果层。前者预防，后者诊断。
- **[[sharpe_ratio]]** — 任何 SR > 1 的回测都应同时报告 PBO；只看 SR 是 López de Prado 2018 反复批评的"业余做法"。

参考文献：
- Bailey, D. H., Borwein, J. M., López de Prado, M., & Zhu, Q. J. (2017). The Probability of Backtest Overfitting. *Journal of Computational Finance* 20(4): 39–69.
- López de Prado, M. (2018). *Advances in Financial Machine Learning*. Wiley. Chapter 11 (Backtest Statistics) + Chapter 12 (Backtesting Through Cross-Validation).
