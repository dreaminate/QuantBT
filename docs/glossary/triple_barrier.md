---
term: triple_barrier
display: "三重障碍标签 (Triple Barrier)"
aliases:
  - triple_barrier
  - triple barrier method
  - 三重障碍
  - 三重栅栏
  - 三障碍法
level: advanced
category: model
formula_latex: "y_i = \\begin{cases} +1 & \\tau^{+}_i < \\min(\\tau^{-}_i,\\, t_i + h) \\\\ -1 & \\tau^{-}_i < \\min(\\tau^{+}_i,\\, t_i + h) \\\\ 0 & \\text{otherwise (vertical)} \\end{cases}"
unit: "类别标签 {-1, 0, +1}"
typical_range: null
sources:
  - "López de Prado (2018) Advances in Financial Machine Learning, Wiley, Chapter 3"
related:
  - purged_kfold
  - embargo
  - look_ahead_bias
  - walk_forward
---

## L1 一句话

按先触哪道障碍给样本打方向标签。

## L2 公式与例子

三重障碍法 (triple barrier method) 给每个入场样本设三道障碍：上轨 (profit-take，止盈)、下轨 (stop-loss，止损)、以及一道垂直障碍 (vertical barrier，最长持有期 $h$)。**最先被触碰的那道障碍决定标签**。

记样本 $i$ 在 $t_i$ 入场，$\tau^{+}_i$、$\tau^{-}_i$ 分别为价格首次触上轨、下轨的时刻：

$$
y_i = \begin{cases}
+1 & \tau^{+}_i < \min(\tau^{-}_i,\, t_i + h) \\
-1 & \tau^{-}_i < \min(\tau^{+}_i,\, t_i + h) \\
0 & \text{otherwise (先到垂直障碍)}
\end{cases}
$$

上下轨通常按**入场点动态波动率**的倍数设定，而非固定百分比：

$$
\text{上轨} = p_{t_i}\,(1 + u\,\sigma_{t_i}), \qquad \text{下轨} = p_{t_i}\,(1 - l\,\sigma_{t_i})
$$

其中 $\sigma_{t_i}$ 是 $t_i$ 时点的滚动收益率波动率估计，$u, l$ 是障碍宽度乘数（López de Prado 2018 §3.4 示例代码取 $u=l=1$）。

**算例**：入场价 $p_{t_i}=100$，该时点日波动率 $\sigma_{t_i}=2\%$，取 $u=l=2$，最长持有 $h=5$ 日。
- 上轨 $=100\times(1+2\times0.02)=104$；下轨 $=100\times(1-2\times0.02)=96$。
- 假设其后 5 日收盘价为 `[101, 103, 105, 104, 102]`：第 3 日触及 105 > 104，先穿上轨。
- 因 $\tau^{+}$（第 3 日）< $\min(\tau^{-},\, t_i+5)$，故 $y_i = +1$。
- 若 5 日内既没破 104 也没破 96，则到第 5 日垂直障碍收口，$y_i = 0$。

## L3 业界阈值与误区

**障碍参数参考**（López de Prado 2018 §3.4–§3.6；§3.6 习题给出常用取值区间）：

| 参数 | 常用取值 | 说明 |
|---|---|---|
| 障碍乘数 $u, l$ | 1 ~ 2 倍 $\sigma_{t_i}$ | 对称 $u=l$ 是中性起点；带方向预测时可不对称（顺势放宽止盈）|
| 波动率窗口 | 50 ~ 100 根 K 线的指数加权 | 太短噪声大、太长滞后（AFML §3.1 用 EWM span≈100）|
| 垂直障碍 $h$ | 1 ~ 10 个 bar | 由策略持有期决定，不是越长越好 |
| 标签去重权重 | 按事件重叠度降权 | 重叠样本不独立，需 average uniqueness 调整（§4）|

**常见误区**：

1. **用未来信息设障碍 → look-ahead bias**。障碍宽度若用**整段样本的全局波动率**而非入场时点 $\sigma_{t_i}$，等于把未来波动泄进当下，是典型的前视偏差 (look-ahead bias)。López de Prado (2018) §3.1 明确要求波动率只用 $t_i$ 及之前的数据估计。

2. **重叠标签当独立样本喂模型**。三重障碍的标签区间 $[t_i, \tau_i]$ 常相互重叠，同一段未来价格被多个样本共享，违反 IID 假设。López de Prado (2018) §4 指出必须配合 **purged k-fold**（清除训练/验证集间重叠样本）+ **embargo**（在验证集后留禁区），否则交叉验证会系统性高估泛化能力。直接用普通 k-fold 会假绿灯。

3. **只用方向标签、丢掉持有期信息**。仅取 $\text{sign}(\text{return})$ 而忽略"先触哪道障碍"，会把"5 日后才小涨"和"当天就冲上止盈"混为一类。López de Prado (2018) §3.4 的 `getBins` 强调标签必须由**首触障碍**决定，而非区间末端收益符号。

4. **垂直障碍样本（$y=0$）处理粗糙**。到期未触横轨的样本，按原始收益符号强行归到 $\pm1$ 会引入噪声标签；López de Prado (2018) §3.7 建议要么保留三分类，要么在 meta-labeling 框架里把 $y=0$ 视作"不交易"。

5. **混淆 primary 标签与 meta-label**。三重障碍产出的是**初级标签**（方向 / 是否触障）；元标签 (meta-labeling, §3.6) 是在已有方向信号上再训一个二级模型预测"该不该下注 + 下多大"。两者层级不同，不能互相替代。

## L4 延伸阅读

- **[[purged_kfold]]** — 三重障碍产生重叠标签，purged k-fold 是其配套的交叉验证法，清除与验证集重叠的训练样本；本条管"怎么打标签"，purged k-fold 管"打完标签怎么不泄露地验证"。
- **[[embargo]]** — embargo 在 purged k-fold 之上，对验证集**之后**的一小段训练样本再设禁区；本条产生的标签区间越长，需要的 embargo 越宽。
- **[[look_ahead_bias]]** — 障碍宽度若用全局波动率即触发前视偏差；look_ahead_bias 是更一般的"未来信息泄露"概念，本条是它在标签构造环节的一个具体陷阱。
- **[[walk_forward]]** — walk-forward 是按时间滚动的样本外验证流程；三重障碍标签 + purged k-fold 解决"单次划分"内的泄露，walk-forward 解决"跨时段稳健性"，两者正交互补。

参考文献：
- López de Prado, M. (2018). *Advances in Financial Machine Learning*. Hoboken, NJ: Wiley. Chapter 3 (Labeling: The Triple-Barrier Method & Meta-Labeling), §3.1–§3.7; Chapter 4 (Sample Weights & Uniqueness).
