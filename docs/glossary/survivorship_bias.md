---
term: survivorship_bias
display: "幸存者偏差 (Survivorship Bias)"
aliases:
  - survivorship_bias
  - survivorship bias
  - 幸存者偏差
  - 生存者偏差
  - 存活偏差
level: beginner
category: data
formula_latex: "\\text{Bias} = \\bar{R}_{\\text{survivors}} - \\bar{R}_{\\text{all listed}} = \\bar{R}_{\\text{survivors}} - \\big[(1-d)\\bar{R}_{\\text{survivors}} + d\\,\\bar{R}_{\\text{dead}}\\big]"
unit: "收益率差（年化，百分点）"
typical_range: [0, 4]
sources:
  - "Brown, Goetzmann, Ibbotson, Ross (1992) Survivorship Bias in Performance Studies, Review of Financial Studies 5(4)"
  - "Elton, Gruber, Blake (1996) Survivorship Bias and Mutual Fund Performance, Review of Financial Studies 9(4)"
  - "López de Prado (2018) Advances in Financial Machine Learning, Wiley, Chapter 1"
related:
  - look_ahead_bias
  - walk_forward
  - pbo
---

## L1 一句话

只用活下来的样本算收益、系统性高估。

## L2 公式与例子

幸存者偏差是指：样本池只保留"活到今天"的标的（仍在上市的股票、未清盘的基金），把中途退市/破产/清盘的死亡样本悄悄删掉，于是回测看到的平均收益**被向上抬高**。偏差大小约等于"幸存样本均值"减去"含死亡样本的全体均值"：

$$
\text{Bias} = \bar{R}_{\text{survivors}} - \big[(1-d)\,\bar{R}_{\text{survivors}} + d\,\bar{R}_{\text{dead}}\big] = d\,\big(\bar{R}_{\text{survivors}} - \bar{R}_{\text{dead}}\big)
$$

其中 $d$ 为样本期内的死亡率（退市/清盘占比），$\bar{R}_{\text{dead}}$ 为死亡样本在退出前的（通常很低或为负的）平均收益。

**算例**：某市场 1000 只股票，10 年内 200 只退市（$d = 0.2$）。活下来的 800 只年化 12%（$\bar{R}_{\text{survivors}} = 12\%$），退市的 200 只在退出前年化 −18%（$\bar{R}_{\text{dead}} = -18\%$）。

- 含死亡样本的全体真实均值 $= 0.8 \times 12\% + 0.2 \times (-18\%) = 9.6\% - 3.6\% = 6.0\%$。
- 只看幸存者得 12.0%。
- 偏差 $= d \,(\bar{R}_{\text{survivors}} - \bar{R}_{\text{dead}}) = 0.2 \times (12\% - (-18\%)) = 0.2 \times 30\% = 6.0$ 个百分点。

即"剔除退市股"这一步无声地给策略凭空加了 6 个百分点的年化收益——全是假的。

## L3 业界阈值与误区

**偏差量级参考**（不同资产/样本期，量级随死亡率与样本质量变化，须结合自身数据核对）：

| 场景 | 幸存者偏差年化量级 | 出处 |
|---|---|---|
| 美国共同基金（剔除清盘基金） | 约 0.5 ~ 1.0 个百分点 | Elton, Gruber, Blake (1996); Carhart et al. (2002) |
| 对冲基金数据库（自报 + 清盘退库） | 约 1.5 ~ 3 个百分点 | Brown, Goetzmann, Ibbotson, Ross (1992); Fung & Hsieh (2000) |
| 个股长样本回测（含退市/破产/并购退出） | 视市场与时段差异大，可达数个百分点 | López de Prado (2018), Ch.1；Shumway (1997) |

**常见误区**：

1. **用"当前成分股"回看历史**：拿今天的沪深 300 / 标普 500 成分股名单往回测十年，等于默认"现在的成员当年也都在、且没被踢出"。被剔除的弱者已被剔除，回测自然偏强。López de Prado (2018) Ch.1 把"point-in-time（时点正确）数据"列为避免此类偏差的首要前提，必须用**当时实际有效的成分名单**而非最新名单。

2. **数据库只留活样本（dead-stock 缺失）**：很多免费/自报数据源会在标的退市或基金清盘后直接删除其历史记录。Brown, Goetzmann, Ibbotson, Ross (1992) 与 Fung & Hsieh (2000) 指出，对冲基金数据库因清盘基金退库带来的偏差可达年化 1.5~3 个百分点；只有保留 dead 记录的数据库才可信。

3. **退市收益记为缺失而非真实损失**：股票破产退市那一刻的 −60%~−100% 常被标成 NaN 后丢弃，于是最惨的一段收益从样本中消失。Shumway (1997) 证明，正确做法是把退市当期收益按实际清算价（常接近 −100%）计入，否则会系统性高估收益、低估风险。

4. **基金"孵化期偏差"叠加**：Evans (2010) 指出基金公司常孵化多只小基金、只把跑赢的公开发售。这与幸存者偏差同源——只展示活下来/跑出来的那批，回测/榜单据此选基会被双重高估。

## L4 延伸阅读

- **[[look_ahead_bias]]** — 同为数据层偏差，但前视偏差是"用了当时还不知道的未来信息"（时间维度泄漏），幸存者偏差是"样本池里少了已死亡的成员"（截面/样本维度泄漏）；两者常同时存在，都要靠 point-in-time 数据修。
- **[[walk_forward]]** — 走查/滚动样本外检验只解决"参数过拟合"，并不能修正样本池本身的幸存者偏差；若底层数据已剔除死亡样本，再严格的 walk-forward 也是在偏差数据上做的，OOS 同样虚高。
- **[[pbo]]** — PBO 衡量"策略选择程序"的过拟合概率；幸存者偏差是数据输入端的系统性偏差。即使 PBO 很低（选择程序不过拟合），偏差数据仍会让整套结论失真，两者属于不同环节、需各自把关。

参考文献：
- Brown, S. J., Goetzmann, W., Ibbotson, R. G., & Ross, S. A. (1992). Survivorship Bias in Performance Studies. *Review of Financial Studies* 5(4): 553–580.
- Elton, E. J., Gruber, M. J., & Blake, C. R. (1996). Survivorship Bias and Mutual Fund Performance. *Review of Financial Studies* 9(4): 1097–1120.
- Fung, W., & Hsieh, D. A. (2000). Performance Characteristics of Hedge Funds and Commodity Funds: Natural vs. Spurious Biases. *Journal of Financial and Quantitative Analysis* 35(3): 291–307.
- Shumway, T. (1997). The Delisting Bias in CRSP Data. *Journal of Finance* 52(1): 327–340.
- Evans, R. B. (2010). Mutual Fund Incubation. *Journal of Finance* 65(4): 1581–1611.
- López de Prado, M. (2018). *Advances in Financial Machine Learning*. Wiley. Chapter 1.
