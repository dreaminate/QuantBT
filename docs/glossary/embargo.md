---
term: embargo
display: "禁运期 (Embargo)"
aliases:
  - embargo
  - embargo period
  - 禁运期
  - 禁运
  - 隔离期
level: advanced
category: model
formula_latex: "h = \\lceil \\eta \\cdot T \\rceil, \\quad \\text{drop } [t_{1}^{\\text{test,end}},\\ t_{1}^{\\text{test,end}} + h]"
unit: "样本数（或时间跨度）"
typical_range: [0, 0.05]
sources:
  - "López de Prado (2018) Advances in Financial Machine Learning, Wiley, Chapter 7.4 (Embargo)"
related:
  - purged_kfold
  - triple_barrier
  - walk_forward
---

## L1 一句话

测试集后再砍一段训练样本防泄漏

## L2 公式与例子

净化（purging）只删掉训练标签与测试标签**时间重叠**的样本，但金融序列还有**序列相关**：测试期刚结束那几天的训练样本，其特征仍受测试期信息影响（如滚动均值、波动率窗口跨越了边界）。禁运（embargo）的作用是：在测试集**结束之后**额外丢弃 $h$ 个训练样本，切断这条泄漏通道。

$$
h = \lceil \eta \cdot T \rceil, \qquad \text{丢弃区间 } \big[\,t_{1}^{\text{test,end}},\ t_{1}^{\text{test,end}} + h\,\big]
$$

- $T$：样本总数
- $\eta$：禁运比例（embargo fraction），López de Prado 2018 §7.4 取约 0.01
- $h$：被禁运的训练样本数；只对**测试集之后**的训练样本生效（之前的由 purging 处理）

**算例**：日频策略，$T = 1000$ 根 K 线，测试折覆盖第 601~700 天。取 $\eta = 0.01$：

$$
h = \lceil 0.01 \times 1000 \rceil = 10 \text{ 天}
$$

→ 除了 purging 删除标签与测试期重叠的训练样本外，再把第 701~710 天这 10 个训练样本一并 embargo 丢弃。最终训练集 = 第 1~600 天（经 purging）+ 第 711~1000 天，测试集 = 第 601~700 天，中间留出 10 天硬隔离带。

## L3 业界阈值与误区

**阈值参考**（López de Prado 2018 §7.4 / 业界经验）：

| $\eta$（禁运比例） | 适用场景 |
|---|---|
| 0（不禁运） | 标签无重叠且特征无跨界窗口（极少见，多数金融特征不满足） |
| ~0.01 | López de Prado 2018 给出的基准取值，日频常用 |
| 0.01 ~ 0.05 | 标签持有期长 / 特征窗口长（如 60 日动量）时按窗口长度放大 |
| > 0.05 | 训练样本损失过大，需重新审视特征窗口设计而非一味加大 $h$ |

经验法则：$h$ 至少应 $\geq$ 「特征最长回看窗口 + 标签最长持有期」，否则隔离带不足以切断序列相关。

**常见误区**：

1. **只做 purging 不做 embargo**。Purging 只处理标签时间区间与测试集**重叠**的样本，但测试期结束后紧邻的训练样本，其特征（滚动统计量、技术指标）的计算窗口仍可能跨越测试边界而吸收了测试期信息。López de Prado 2018 §7.4 明确指出 purging 不足以消除这种"邻接泄漏"，必须叠加 embargo。

2. **embargo 加在测试集两侧**。Embargo 在原始定义中**只加在测试集之后**（向未来方向），测试集之前的泄漏由 purging 解决。误把两侧都按 $h$ 砍会无谓损失训练样本（López de Prado 2018 §7.4 的实现 `getEmbargoTimes` 只对测试后区间生效）。

3. **$\eta$ 与持有期 / 特征窗口脱钩**。直接套用 0.01 而不看自己标签的最长持有期和特征的最长回看窗口。当标签由 triple-barrier 给出且垂直障碍设得很长（如 20 日），或特征含 60 日波动率时，$h$ 必须随之放大，否则隔离带形同虚设（López de Prado 2018 §7.1、§7.4）。

4. **以为 embargo 能替代 walk-forward 的时序约束**。Embargo 是 k-fold 内部消除单折泄漏的手段；它不保证整体"只用过去预测未来"的方向性。跨折仍可能出现"用未来折训练、预测过去折"的情况，方向性需靠 walk-forward / 时序 split 保证（López de Prado 2018 §7.4 vs §11/12 walk-forward 讨论）。

## L4 延伸阅读

- **[[purged_kfold]]** — 净化交叉验证是 embargo 的母方法：purging 删"标签时间重叠"的样本，embargo 是它之后再砍一段，二者配套使用，单独 purging 不够。
- **[[triple_barrier]]** — 三重障碍法决定标签的**持有期长度**，而持有期直接决定 embargo 需要多大的 $h$；标签重叠越长，禁运带越宽。
- **[[walk_forward]]** — Walk-forward 保证整体时序方向性（只用过去预测未来），embargo 保证单折内部无邻接泄漏；前者管"折之间方向"，后者管"折之内隔离"，互补不替代。

参考文献：

- López de Prado, M. (2018). *Advances in Financial Machine Learning*. Wiley. Chapter 7.4 (Embargo) 与 Chapter 7.1 (The Problem with K-Fold Cross-Validation).
