---
term: look_ahead_bias
display: "前视偏差 (Look-ahead Bias)"
aliases:
  - look_ahead_bias
  - lookahead bias
  - look-ahead bias
  - 前视偏差
  - 前瞻偏差
  - 未来函数
  - 偷看未来
level: beginner
category: data
formula_latex: "\\hat{s}_t = f(I_t), \\quad I_t \\subseteq \\{x_\\tau : \\tau \\le t\\} \\;\\Rightarrow\\; \\text{no look-ahead}"
unit: "无量纲（缺陷有/无）"
typical_range: null
sources:
  - "López de Prado (2018) Advances in Financial Machine Learning, Wiley, Chapter 7"
  - "Bailey, Borwein, López de Prado, Zhu (2014) Pseudo-Mathematics and Financial Charlatanism, Notices of the AMS 61(5)"
related:
  - survivorship_bias
  - purged_kfold
  - embargo
  - walk_forward
---

## L1 一句话

回测用到了当时不可知的未来信息。

## L2 公式与例子

前视偏差（look-ahead bias，又称"未来函数"）指：在时刻 $t$ 做决策时，输入信息集 $I_t$ 越界用到了 $t$ 之后才公开的数据。无前视的充要条件是决策只依赖 $t$ 时点及之前已落地的信息：

$$
\hat{s}_t = f(I_t), \quad I_t \subseteq \{x_\tau : \tau \le t\} \;\Rightarrow\; \text{no look-ahead}
$$

只要 $I_t$ 里含了任何 $\tau > t$ 的 $x_\tau$（哪怕只是用了"今天收盘价"在"今天开盘"下单），回测就被未来信息污染。

**算例**：某日内策略规则是"若当日收益 > 0 则当日满仓"。某股票当日开盘 100、收盘 105。

- 含前视的回测：用当日收盘价 105 判断"涨了"，于是在当日"建仓"——但收盘价要到当日收盘才知道，开盘根本无法据此下单。该日记 +5%。
- 无前视的执行：开盘时只知前一日信息，无法预知当日涨跌；实盘该笔交易根本不会发生，收益为 0。

若一年 250 个交易日里有 130 天上涨平均 +3%、120 天下跌但被规则"完美避开"，回测年化约 $1.03^{130} - 1 \approx 4565\%$（约 46.6 倍），而无前视实盘可能接近 0。这个天文数字本身就是前视偏差的典型信号。

## L3 业界阈值与误区

**阈值/识别参考**：

| 现象 | 解读 |
|---|---|
| 回测 Sharpe > 4 且换手高 | 强烈怀疑前视污染 (López de Prado, 2018, Ch.7) |
| 回测权益曲线近乎直线、回撤极小 | 典型未来函数特征 |
| 用收盘价信号 + 同根 K 线成交 | 日内/分钟级最常见前视口子 |
| 财报/基本面用"报告期日"而非"公告日" | 滞后披露造成的前视 (López de Prado, 2018, Ch.7) |
| 标准化/填充用了全样本统计量 | 预处理阶段的隐性前视 |

注：前视偏差是结构缺陷（有或无），没有"可接受阈值"——任何泄漏都应清零，上表是**侦测信号**而非容忍带。

**常见误区**：

1. **用收盘价信号、同一根 K 线成交（最常见）**。信号由当日收盘价算出，却假设在当日就能成交。正确做法是信号 $t$ 决定，成交至少推迟到 $t+1$ 开盘。López de Prado (2018, Ch.7) 把"决策时点与信息可得时点错配"列为回测首要陷阱。

2. **预处理阶段全样本泄漏**。对特征做 z-score 标准化、缺失值填充、PCA、或拟合 scaler 时用了整段（含未来）数据的均值/方差，把未来分布信息回灌进训练期。López de Prado (2018, Ch.7) 提出 **purged k-fold + embargo** 正是为切断这类训练/测试边界处的信息渗漏；任何归一化都必须在 train 段拟合、在 test 段仅 transform。

3. **基本面数据用"报告期日"而非"公告日"**。财报数据带发布滞后，季报常在期末后数周才公告。若以报告期末日对齐信号，等于提前数周用到了尚未公开的数字。López de Prado (2018, Ch.7) 强调必须以**信息实际可得日 (point-in-time)** 对齐。

4. **指数成分/调整因子的"完成态"快照**。用今天的指数成分名单、复权因子、或拆分调整去回算历史，等于把未来才发生的成分调整/公司行为信息提前注入——这与 survivorship bias 常并发出现。

5. **把"未来收益排序"当特征**。例如用未来 5 日收益分桶后回头解释，或在打标签时让 $t$ 的标签依赖 $t+k$ 的价格却未在特征端做相同时移隔离，是 triple-barrier 类标注里隐蔽的前视来源。

## L4 延伸阅读

- **[[survivorship_bias]]** — 幸存者偏差是"样本里只剩活下来的标的"（横截面缺失），前视偏差是"时间维度上偷看了未来"（纵向越界）；二者常在用"今天的成分名单"回测时同时发生，但机理一个是选样、一个是时序对齐。
- **[[purged_kfold]]** — Purged k-fold 是消除前视的具体工程手段之一：在交叉验证中剔除与测试段标签时间重叠的训练样本，本条是它要防的"病"，purged_kfold 是"药"。
- **[[embargo]]** — Embargo 在 purge 基础上再加一段缓冲期，专门阻断序列相关导致的边界渗漏；与本条同源，是更细粒度的前视防护。
- **[[walk_forward]]** — 滚动前推 (walk-forward) 用"只在历史段拟合、在未来段验证"的流程从结构上杜绝前视；本条描述缺陷，walk_forward 描述规避缺陷的回测范式。

参考文献：

- López de Prado, M. (2018). *Advances in Financial Machine Learning*. Wiley. Chapter 7 (Cross-Validation in Finance: purging, embargo, point-in-time data).
- Bailey, D. H., Borwein, J. M., López de Prado, M., & Zhu, Q. J. (2014). Pseudo-Mathematics and Financial Charlatanism: The Effects of Backtest Overfitting on Out-of-Sample Performance. *Notices of the American Mathematical Society* 61(5): 458–471.
