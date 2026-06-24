---
term: purged_kfold
display: "净化交叉验证 (Purged k-fold)"
aliases:
  - purged_kfold
  - purged k-fold
  - purged cross-validation
  - 净化交叉验证
  - 净化 k 折
  - 净化 K 折交叉验证
level: advanced
category: model
formula_latex: "\\text{purge: drop } i \\in \\text{train if } [t_{i,0}, t_{i,1}] \\cap [t_{j,0}, t_{j,1}] \\neq \\varnothing \\text{ for some } j \\in \\text{test}"
unit: "无量纲（折数 k 为正整数）"
typical_range: null
sources:
  - "López de Prado (2018) Advances in Financial Machine Learning, Wiley, Chapter 7 (Cross-Validation in Finance)"
related:
  - embargo
  - walk_forward
  - triple_barrier
---

## L1 一句话

剔除与测试集时间重叠的训练样本再交叉验证。

## L2 公式与例子

标准 k 折交叉验证（k-fold cross-validation）假设样本独立同分布（IID）。但金融标签往往**跨多根 K 线计算**（比如持有 5 天的收益、三重障碍标签 [[triple_barrier]] 触障前的整段路径），相邻样本的标签区间**互相重叠**。直接做 k 折会让"未来信息"从测试集渗进训练集——这就是泄漏（leakage）。

**净化（purge）**：对测试折里每个样本 $j$，其标签覆盖时间区间 $[t_{j,0}, t_{j,1}]$（$t_{j,0}$ 为特征观测时点，$t_{j,1}$ 为标签实现时点）。训练集里凡标签区间与任一测试样本区间相交的样本 $i$ 一律剔除：

$$
\text{drop } i \in \text{train} \quad \text{if} \quad [t_{i,0},\, t_{i,1}] \cap [t_{j,0},\, t_{j,1}] \neq \varnothing \ \ \text{for some } j \in \text{test}
$$

**算例**：日频策略，标签为"未来 5 个交易日收益"（即每个样本 $t_{i,1} = t_{i,0} + 5$ 天）。5 折，每折约 50 个交易日。取第 3 折为测试集，覆盖第 101–150 交易日。
- 训练样本第 96–100 日：其标签区间向后延伸 5 天 → 落在第 101–105 日，**与测试集重叠** → 净化剔除（5 条）。
- 测试样本第 146–150 日：标签延伸到第 151–155 日，可能渗进紧随其后的训练折 → 这一侧用**禁运期** [[embargo]] 额外剔除测试集**之后** $h$ 根样本。
- 取禁运比例 1%（López de Prado 2018 §7.4.2 建议 1–5%）：总样本 250 日 × 1% ≈ 3 日，故测试集后再砍 3 条训练样本。

净化处理"测试集之前"的重叠，禁运处理"测试集之后"的序列相关溢出，两者配合才堵住双向泄漏。

## L3 业界阈值与误区

**参数参考**（López de Prado 2018, Chapter 7）：

| 参数 | 取值参考 | 依据 |
|---|---|---|
| 折数 k | 常用 5 或 10 | 与传统 CV 一致；k 越大训练集越大但折越小、方差越高 |
| 禁运比例 embargo | 持仓期长度的 1–5%（占总样本） | López de Prado 2018 §7.4.2 |
| 净化条件 | 标签区间相交即剔除 | López de Prado 2018 §7.4.1（`getTrainTimes`） |
| 适用前提 | 标签跨多期 / 样本非 IID | 单期 IID 标签无需净化 |

**常见误区**：

1. **以为 k 折在金融上"开箱即用"**。标准 CV 的 IID 假设在金融时间序列上几乎总不成立：重叠标签 + 序列相关使测试集与训练集信息泄漏，导致样本外（OOS）Sharpe 被系统性高估。López de Prado (2018, Chapter 7) 把这列为"为什么金融机器学习失败"的首要原因之一。

2. **只净化、忘了禁运**。很多实现只剔除"测试集之前与之重叠"的训练样本，却忽略测试集**之后**因序列相关而泄漏的样本。López de Prado (2018, §7.4.2) 明确指出，若特征本身有持续记忆（如用移动平均、波动率估计构造），必须叠加 embargo；否则泄漏仍在。

3. **把净化等同于滚动样本外**。净化 k 折仍是**多折轮流做测试**（数据被反复复用），而 [[walk_forward]] 是严格按时间单向前推、测试集永远在训练集之后。Bailey, Borwein, López de Prado & Zhu (2014) 警告：CV（含净化版）因数据复用仍可能助长回测过拟合，需配合 PBO/DSR 这类多重检验校正，不能单凭一次净化 CV 的高分就上线。

4. **禁运比例拍脑袋**。embargo 长度应由标签跨期与特征记忆长度决定，不是固定 1%。持仓 20 天、特征含 60 日均线的策略，1% 远不够；应按特征+标签的最大记忆长度反推（López de Prado 2018, §7.4.2）。

## L4 延伸阅读

- **[[embargo]]** — 禁运期是净化的"另一半"：净化剔测试集**之前**的重叠样本，禁运剔测试集**之后**的序列相关样本。两者同属一套防泄漏机制。
- **[[walk_forward]]** — 滚动样本外严格单向前推、不复用数据；净化 k 折轮流做测试、复用数据但用净化堵泄漏。前者更保守、样本利用率低，后者样本效率高但仍有过拟合风险。
- **[[triple_barrier]]** — 三重障碍标签是产生"跨多期、互相重叠"标签的典型来源，正是净化交叉验证要处理的对象；二者通常配套使用。

参考文献：
- López de Prado, M. (2018). *Advances in Financial Machine Learning*. Wiley. Chapter 7 (Cross-Validation in Finance), §7.4.1–7.4.2.
- Bailey, D. H., Borwein, J., López de Prado, M., & Zhu, Q. J. (2014). Pseudo-Mathematics and Financial Charlatanism: The Effects of Backtest Overfitting on Out-of-Sample Performance. *Notices of the American Mathematical Society* 61(5): 458–471.
