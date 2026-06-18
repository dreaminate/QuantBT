# 16 · 交叉验证（Purged k-fold + Embargo / CPCV / Walk-forward）

> 机构级 Agent OS 成品环节深挖 · 全程 Opus 4.8 · 对抗式核查已降权 · 重心=前沿研究+概念级推荐 · 不含 file:line 代码接线
> 簇 C

## 1. 一句话定位

本环节回答一个看似技术、实则决定「整套 Agent 是否在自欺」的问题：**当标签带时间跨度（triple-barrier 等）、训练/测试样本时间重叠时，怎样切样本才不会把未来信息泄回训练？** 范式全部源自 López de Prado《Advances in Financial Machine Learning》(2018) 第 7 章（CV）与第 12 章（CPCV/多路径回测）——标准随机 k-fold 在金融序列上严重泄漏 → 用 **purging**（剔除标签区间与测试集重叠的训练样本）+ **embargo**（测试集之后再设一段缓冲，挡住延迟市场反应导致的串行相关泄漏）修复 → **CPCV** 进一步把数据切成 N 个连续组、每次取 k 组做测试、共 C(N,k) 种组合，从而把 OOS 绩效（Sharpe、回撤、PBO）变成一个**分布**而非单点。本项目的诚实立场是**双轨并行**：把 CPCV 定位为「**更强的统计默认**」（产出 OOS 分布 + 喂给 deflated Sharpe / PBO），把 Walk-Forward 定位为「**部署现实性校验**」（最贴近实盘滚动上线的单条历史路径），两者互为交叉检验。

## 2. 前沿 SOTA 与代表系统

| 系统 / 范式 | 角色 | 要点 | URL |
|---|---|---|---|
| **López de Prado AFML 验证范式（PurgedKFold + Embargo + CPCV）** | 防泄漏 CV 的事实标准 | 出自 AFML(2018) 第 7 章与第 12 章。定义 purging（剔标签重叠训练样本）、embargo（测试集后缓冲）、CPCV（C(N,k) 组合产生多条 OOS 路径）。几乎所有后续工具与论文都以此为基线。 | https://www.wiley.com/en-us/Advances+in+Financial+Machine+Learning-p-9781119482086 |
| **CPCV + Deflated Sharpe Ratio + PBO 三件套** | 机构级「最强统计默认」 | CPCV 产出 OOS 绩效分布 → PBO（回测过拟合概率，经 CSCV 估计）量化「最优 IS 策略 OOS 跌破中位数」的概率 → Deflated Sharpe Ratio 按试验次数/偏度/峰度/样本长度惩罚 Sharpe 显著性。把「多重检验」惩罚做进验证环节，是与单点 Sharpe 的本质区别。 | https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2460551 |
| **Walk-Forward Analysis（anchored/expanding 与 rolling/sliding）** | 行业「部署现实性」默认 | 严格只用过去训练、按真实再平衡节奏滚动、把各 OOS 段拼成单条连续净值，最贴近实盘上线方式；rolling/sliding 窗口被认为最像真实部署。缺点是只有一条历史路径、测试集少、绩效估计方差高。商用如 TradeStation Walk-Forward Optimizer 已产品化。**注**：在 López de Prado 阵营里 WF 恰恰是被批评对象（单路径、易过拟合、假发现率高），「行业默认」是散户/商用平台口径而非机构共识（见 §7）。 | https://blog.quantinsti.com/walk-forward-optimization-introduction/ |
| **skfolio CombinatorialPurgedCV / WalkForward** | 「CPCV+WF 双轨」落地参考实现 | sklearn 生态内（BSD 许可）的两类 model_selection（含 purging、embargo、多路径 OOS 分布），组合优化导向，是 API 设计范本，且可商用——优于已闭源的 mlfinlab（见 §7）。 | https://skfolio.org/generated/skfolio.model_selection.CombinatorialPurgedCV.html |

## 3. 关键论文（每条带 URL）

- **Backtest Overfitting in the ML Era: A Comparison of OOS Testing Methods in a Synthetic Controlled Environment**（Arian, Norouzi Mobarekeh & Seco, 2024, *Knowledge-Based Systems* 305:112477）——【核实命题的核心证据】在 Heston 随机波动 / Merton 跳扩散 / drift-burst / regime-switching 等**真值已知的合成数据**上比较 KFold / PurgedKFold / WF / CPCV：CPCV 的 PBO 最低、Deflated Sharpe 检验统计量最优；WF 防假发现差、时间方差大、平稳性弱。**但标题与方法都限定在「合成受控环境」**——这正是「CPCV 仅在合成环境显著优于 WF」的来源，**不应外推为真实市场铁律（context_limited）**。还提出 Bagged CPCV / Adaptive CPCV 变体（无真实数据外部验证）。
  https://dl.acm.org/doi/abs/10.1016/j.knosys.2024.112477 ；预印本 https://papers.ssrn.com/sol3/papers.cfm?abstract_id=4686376

- **The Probability of Backtest Overfitting**（Bailey, Borwein, López de Prado & Zhu, 2015, *J. Computational Finance* / SSRN 2326253）——提出 PBO 与 CSCV（combinatorially symmetric cross-validation，CPCV 的近亲）：PBO = 最优 IS 策略 OOS 排名跌破中位数的概率。结论：hold-out 在投资回测里不可靠；CSCV 在单数据集上即可逼近大量独立样本的 PBO 估计。是 CPCV「OOS 分布→过拟合诊断」路线的理论根。**注**：PBO/CSCV 明确**不检测 look-ahead / 数据泄露 / 无效特征**，对样本外 regime 漂移盲（见 §7）。
  https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2326253

- **The Deflated Sharpe Ratio: Correcting for Selection Bias, Backtest Overfitting and Non-Normality**（Bailey & López de Prado, 2014, *J. Portfolio Management* / SSRN 2460551）——把「试验次数 N、偏度、峰度、样本长度」纳入 Sharpe 显著性阈值；并用 ONC 聚类估计「有效独立试验数」（因重叠特征致 N 实际更小）。这正是 CPCV 多路径必须配套的下游统计：多路径产生的 max Sharpe 必被选择偏差膨胀，DSR 做**向下去通胀（deflation）惩罚**——是多重检验惩罚，不是修复系统性低估。
  https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2460551

- **Leakage and the Reproducibility Crisis in Machine-Learning-based Science**（Kapoor & Narayanan, 2023, *Patterns* 4(9):100804，arXiv 2207.07048）——给出 **8 类数据泄漏分类法**，记录 **17 个领域 294 篇**受泄漏影响、结论过度乐观的论文；提出「model info sheet」强制自查。对本环节的关键提醒：purging + embargo **只治「时间重叠/串行相关」一类泄漏**，特征工程泄漏、PIT/survivorship、universe 选择、测试集分布偏移等其余各类仍需独立护栏——交叉验证不是泄漏的万能解。
  https://arxiv.org/abs/2207.07048

- **REFORMS: Reporting Standards for Machine Learning Based Science**（Kapoor et al., arXiv 2308.07832）——为基于 ML 的科学结论提供报告清单：含训练/测试干净分离、泄漏自查、数据分布是否匹配研究/部署目标——可作为 Agent OS「验证报告卡」的清单模板。
  https://arxiv.org/abs/2308.07832

- **skfolio: Portfolio Optimization in Python**（2025, arXiv 2507.04176）——提供 `CombinatorialPurgedCV` 与 `WalkForward` 的 sklearn 风格实现（含 purging/embargo、多 OOS 路径分布），是把「CPCV+WF 双轨」落进生产代码的参考实现与 API 设计范本。
  https://arxiv.org/pdf/2507.04176

## 4. 机构最佳实践 / 标准

- **模型风险管理（Fed/OCC SR 11-7）**：任何用于决策的模型须有独立验证、概念健全性检查、持续监控与文档化（**开发者≠验证者**）。把「防泄漏 CV + OOS 分布 + 过拟合诊断」纳入模型生命周期，与回测一并接受独立 effective challenge。这是把 CPCV/WF 从「技巧」升格为「治理流程」的制度依据。**注**：对单用户量化项目是「合规话术借用」而非强制约束（见 §8）。
  https://www.federalreserve.gov/supervisionreg/srletters/sr1107.htm

- **NIST AI 风险管理框架（AI RMF 1.0，Govern/Map/Measure/Manage）**：要求对评估方法本身的有效性、数据泄漏与分布偏移、以及「测试集是否代表真实部署分布」做显式度量与记录。直接对应本环节的 leakage / embargo / 部署现实性话题。
  https://www.nist.gov/itl/ai-risk-management-framework

- **CFA Institute GIPS 业绩呈报标准**：强调防选择偏差、防 cherry-picking、净值连续可复核——与「用 deflated Sharpe / PBO 惩罚多重检验、保留完整 OOS 分布而非只报最优路径」的精神一致。**注**：GIPS 主要规范业绩呈报、非 CV 方法，本条为相关性映射而非直接适用。
  https://www.cfainstitute.org/en/ethics-standards/codes/gips-standards

- **REFORMS 报告清单**：为 ML 科学结论提供报告模板（训练/测试干净分离、泄漏自查、数据分布匹配研究/部署目标），可直接作为本项目「验证报告卡」的字段来源。
  https://arxiv.org/abs/2308.07832

## 5. 对 QuantBT 这套架构的推荐方向（概念级）

> 概念级方向，不点 file:line、不排实施计划。

1. **双轨为默认、CPCV 为「更强统计默认」而非铁律**：Agent 默认同时跑 CPCV（产出 OOS 绩效分布 + PBO + deflated Sharpe）与 Walk-Forward（单条部署现实性路径），在「信任报告」里并排呈现两者结论。当二者背离（CPCV 漂亮但 WF 衰减）时，**默认采信更保守的一方**，并用经济语言向用户解释「为什么这可能是过拟合而非真 alpha」。务必把 CPCV 的优越性表述为「在合成受控环境中被一篇研究支持、无相反真实市场证据」，**不可在文案里宣传为「总是更优」**（见 §7）。

2. **把「防泄漏」做成不可绕过的流程脊柱**：purge + embargo 的时间跨度自动由标签 horizon（如 triple-barrier 的最大持有期）+ 资产交易日历推导，用户不需要也无法手动关掉。A股与加密各自的日历/停牌/7×24 由数据平台 PIT 字段驱动，embargo 含义随资产自适应。**关键修正**：embargo 的规范定义是「观测数的一个小百分比」（常用 ~1%），purge 长度由 label horizon 决定，二者是**两个不同量**，不存在跨频率通用的「≈21 交易日/一个月」天数默认（见 §7）；落地时应按「资产日历的有效交易日」而非自然观测计数，A股长期停牌段尤甚。

3. **泄漏护栏分层、显式声明**：在 CV 之外单设「泄漏体检」（对照 Kapoor-Narayanan 8 类与 REFORMS 清单），覆盖特征泄漏、PIT/survivorship、universe 选择、target 未来信息。每条用一句经济学者能懂的话告诉用户「这一类已挡住/未涉及」，让「流程即信任」可被非技术用户读懂——明确告知 purge/embargo **只解时间重叠一类**，不替其余各类兜底。

4. **多重检验惩罚内建、记录试验次数**：Agent 自动累计本次研究里尝试过的策略/参数/CV 配置数，喂给 deflated Sharpe 与 PBO；在结论里明确「扣除你试过 N 次后，这个 Sharpe 还显著吗」。把「**对验证方法本身的元过拟合**」也纳入计数——防止研究者偷偷调 N/k/embargo/label horizon 直到 OOS 漂亮。

5. **正确解读 CPCV 分布、不夸大独立性**：CPCV 的 C(N,k) 条路径**共享大量训练数据、彼此强相关**，直接用路径分布算标准差/置信区间会**低估方差、夸大「独立 OOS 路径数」**。在 UI/报告里把多路径明确标注为「**相关路径下的情景分布**」而非「独立样本」，并用 DSR 的有效独立试验数做方差校正；给非技术用户呈现为「在多种可能的历史走法下，这个策略的表现区间」，而非伪精确的置信区间。**诚实张力**：若路径强相关致分布方差不可信，则「分布优于单点」的卖点本身被削弱，不能两头都拿满分（见 §7）。

6. **跨 regime 压力作为第三视角**：除 CPCV/WF 外，默认追加一次按 regime 标注的跨 regime 留出检验（在一种市场状态训练、另一种状态测试），把非平稳衰减显式化——这是中低频资产无关策略最现实的脆弱点；任何 CV 在训练-测试同处一个 regime 时都会因「regime 式相似」而偏乐观。

7. **可复现与可审计**：固定随机种子、记录每条路径的训练/测试索引、purge/embargo 实际剔除量、试验计数与最终 PBO/DSR，生成可复核的验证卡（对齐 SR 11-7 独立验证与 GIPS 防 cherry-picking 精神），供 agent 之间互相 effective challenge。

8. **新变体保守对待 + 真开源优先**：Bagged/Adaptive CPCV 等仅置于「实验性」开关后，默认不启用，文案诚实标注「目前仅有合成环境证据、缺真实市场外部验证」。参考实现优先选 **skfolio（BSD）/ timeseriescv** 这类真开源；**mlfinlab 已完全闭源、All-Rights-Reserved，不可直接用于商业产品**（见 §7）。

## 6. 架构级参考（少量伪代码 / schema 草图，非代码接线）

> 示意，非接线到现有代码。

**purge + embargo 的时间跨度自动推导（由 label horizon + 资产日历驱动）：**

```
purge_span   = label_max_horizon(strategy)        # triple-barrier 最大持有期等
embargo_span = ceil(embargo_pct * n_observations)  # 规范：观测数的~1%（非固定天数）
# 二者是不同量；落地按「资产日历有效交易日」计数：
#   A股：跳过停牌段、按交易日历折算；加密：7×24 连续 bar
# 铁律：purge/embargo 由系统推导，用户不可手动关闭
```

**CPCV 多路径（情景分布，非独立样本）：**

```
groups = split_contiguous(data, N)                 # N 个连续组
for combo in combinations(groups, k):              # 共 C(N,k) 个组合
    test  = combo
    train = purge_then_embargo(groups - combo, test, purge_span, embargo_span)
    fit(train); record_oos(predict(test))
total_paths = (k / N) * C(N, k)                    # φ = 总回测路径数（注：非"单观测参与数"）
# 输出：OOS 绩效"情景分布"——UI 标注为"相关路径"，禁止当独立样本算置信区间
```

**双轨 + 多重检验惩罚 → 验证卡（schema 草图）：**

```yaml
validation_card:
  cpcv:
    n_groups: N
    k_test: k
    total_paths: phi               # (k/N)*C(N,k)
    oos_sharpe_distribution: [...]  # 标注 correlated_paths: true
    pbo: 0.xx                       # CSCV 估计
  walk_forward:
    mode: rolling                   # anchored | rolling
    oos_equity_curve: [...]         # 单条部署现实性路径
    n_oos_segments: m
  multiple_testing:
    n_trials: T                     # 累计试过的 策略/参数/CV 配置 数（含元过拟合）
    deflated_sharpe: 0.xx           # 按 T/偏度/峰度/样本长度向下去通胀
    effective_independent_trials: T_eff   # < T，因重叠/相关
  leakage_audit:                    # 对照 Kapoor-Narayanan 8 类 / REFORMS
    temporal_overlap: handled_by_purge_embargo
    feature_leakage: <checked|n/a>
    pit_survivorship: <checked|n/a>
    universe_selection: <checked|n/a>
    target_uses_future: <checked|n/a>
  regime_holdout:                   # 第三视角：跨 regime 压力
    train_regime: bull
    test_regime: bear
    decay_observed: <yes|no>
  reproducibility:
    seed: ...
    per_path_train_test_index: [...]
    purge_embargo_dropped_count: ...
# 当 cpcv 漂亮但 walk_forward 衰减 → 默认采信更保守一方并解释
```

## 7. 降权 / 争议 / 陷阱（对抗核查结论）

> 以下限定词（夸大/争议/撤稿/二手/不可外推/单源/技术口误/闭源 等）**原样保留**；凡涉「已验证/已确证/直接证实/总是更优」的强确定性措辞均已按对抗核查降级。任何对用户的承诺或文案，必须采用降级后的表述。

- **【low · 夸大措辞】「CPCV 仅在合成受控环境显著优于 WF —— 这一命题得到『直接证实』」**——命题本身**正确且经核实**（Arian, Norouzi Mobarekeh & Seco 2024, *Knowledge-Based Systems* 305:112477，确为 Heston/Merton 跳扩散/drift-burst/regime-switching 合成数据，标题即限定 "Synthetic Controlled Environment"，无真实市场验证）。但「**直接证实**」措辞**轻微夸大**：这是**单篇论文、单一研究组**（且 CPCV 提出者 López de Prado 阵营之外的独立大样本复现缺失）的结论。准确表述应为「**有一篇限定于合成环境的实证支持，且无相反真实市场证据**」，而非「直接证实」暗示的多源稳健结论。
  https://www.sciencedirect.com/science/article/abs/pii/S0950705124011110

- **【medium · 二手/不精确】「常见 embargo = purge ≈ 21 交易日 ≈ 一个月，为经验值」**——这是**二手、不精确数字**。AFML 原书与主流实现（skfolio/Wikipedia/quantinsti）对 embargo 的规范定义是「**观测数的一个小百分比**」（常用 ~1%，例：1000 观测 → 10 或 50 观测），而非固定「21 交易日/一个月」。embargo 的绝对长度完全取决于样本观测数与 bar 频率，「21 交易日」只在特定日频、特定样本长度下才约等于 1%。把它写成「常见经验天数默认」会误导读者以为存在一个**跨频率通用**的天数。purge 长度由 label horizon 决定，与 embargo 是**两个不同量**，二者「≈相等」也**无普遍依据**。
  https://en.wikipedia.org/wiki/Purged_cross-validation

- **【low · 技术口误】「每个观测参与 φ=(k/N)·C(N,k) 条回测路径」**——**公式与归属对象错配**。φ[N,k]=(k/N)·C(N,k) 是「**总回测路径数**」，**不是「每个观测参与的路径数」**。每个观测落在 C(N,k) 个组合中 k/N 比例的测试集里；它「参与的路径数」是另一个量（与穿过该点的路径计数有关），不等于总路径数 φ。把总路径数说成单观测参与数是一个具体的技术口误，虽不影响大方向，但属会被审稿挑出的精确性错误。已在 §6 伪代码中标注更正。
  https://en.wikipedia.org/wiki/Purged_cross-validation

- **【low · 过度乐观 / 内在张力】「CPCV 多路径相互高度重叠、强相关 → 方差被低估、独立路径数被夸大」**——方向正确，研究员已自我降级为「公开文献讨论不充分、属推断/二手关切」。但需进一步点破：它与同时主张的「CPCV 给出 OOS 分布、是更强统计默认」**存在内在张力**——若路径强相关致分布方差不可信，则「分布优于单点」的卖点也被削弱，**不能两头都拿满分**。设计上须把多路径明确标注为「相关情景分布而非独立样本」（已落 §5 第 5 条 / §6），定位语不得无保留推荐 CPCV。

- **【medium · 闭源 / 反向夸大可用性】「mlfinlab『注意后期版本商业化/许可证变化，集成前需核实当前授权』」**——方向对但**严重程度被低估**。经核实 mlfinlab 现已是**完全闭源、All-Rights-Reserved 的专有库**，student license 明确**禁止任何商业用途且不得用于创建竞品**，商用须购买商业授权。把它写成温和的「许可证变化、需核实」会让读者误以为仍是可商用的开源参考实现。对一个「可上线成品为北极星」的项目，应直接标注为「**不可直接用于商业产品**」，并改荐 skfolio（BSD）/ timeseriescv 等真开源实现。
  https://github.com/hudson-and-thames/mlfinlab/blob/master/LICENSE.txt

- **【low · 口吻过强】「WF 被『普遍视为最现实的部署模拟和行业默认』」**——大体成立但带未加限定的「行业默认」口吻。WF/walk-forward optimization 在**散户/商用平台**（TradeStation 等）确为常见默认，但在 López de Prado **机构论述里恰恰是被批评的对象**（单路径、易过拟合、假发现率高）。把它无条件称为「行业默认」掩盖了「**不同机构派系对默认方法存在分歧**」这一事实。双轨结论是合理折中，但论据里 WF 的「行业默认」地位陈述得过强，已在 §2 表格加注。

- **【参照·confirmed】DSR 表述正确、不降级**：本研究把 DSR 正确理解为「按试验次数/偏度/峰度/样本长度**向下去通胀（deflation）**的多重检验惩罚」，**未踩**「DSR 是修复系统性低估」的雷。PBO/CSCV、Kapoor-Narayanan（8 类/17 领域/294 篇）、skfolio（arXiv 2507.04176）、SR 11-7、路径数公式 φ=(k/N)·C(N,k) 等其余引用经核实**作者署名/年份/期刊准确、属实**。

**通用陷阱清单（工程红线）：**

- **把合成环境结论当铁律**：CPCV 显著优于 WF 的实证只在 Heston/Merton/regime-switching 合成数据上成立（标题即限定），真实市场缺同等严谨证据；**不可外推**、勿在产品里宣传 CPCV「总是更优」。
- **CPCV 路径不独立**：C(N,k) 条路径共享大量训练数据、彼此强相关，直接用路径分布算标准差/置信区间会**低估方差、夸大独立 OOS 路径数**；必须配 DSR「有效独立试验数」校正（此为合理推断 + 二手关切，公开文献讨论不足）。
- **purge/embargo 不是泄漏万能解**：只挡「时间重叠/串行相关」型泄漏；特征工程泄漏、PIT/survivorship、universe 选择、target 用未来信息（Kapoor-Narayanan 8 类）仍会过乐观，需独立护栏。
- **对验证方法本身的元过拟合**：反复换 N/k/embargo/label horizon 直到 OOS 漂亮 = 对 CV 配置过拟合；不记录试验次数并惩罚，DSR/PBO 会失真。
- **embargo/折数无理论最优**：常见 embargo 为「观测数 ~1%」的经验值，A股（到 paper）与加密（到 Binance 实盘）的交易日历、停牌、7×24 与涨跌停差异会让同一百分比的绝对含义不同，需按资产日历自适应而非硬编码天数。
- **WF 单路径高方差**：现实性强但测试集少、对起止点敏感、绩效估计方差大；只看 WF 易被一条幸运/不幸路径误导——这正是要 CPCV 双轨补 OOS 分布的原因。
- **非平稳/regime 漂移使任何 CV 的 OOS 估计都偏乐观**：训练-测试同处一个 regime 时泄漏式相似，跨 regime 部署后衰减，需 regime 标注 + 跨 regime 留出做压力检验，而非仅靠 purge/embargo。
- **Bagged/Adaptive CPCV 等新变体仅有合成环境证据**，缺真实数据外部复现，勿作默认推荐。
- **label horizon 本身可能含数据窥探**：若 horizon 是「试了多个选最好」的结果，purge/embargo 再严也挡不住——属比 Kapoor-Narayanan 8 类更贴近本环节的泄漏。
- **CV 给的是 gross 绩效分布**：加入真实手续费、滑点、A股涨跌停/停牌与加密 7×24 后，PBO/DSR 结论可能逆转；验证方法本身不含成本模型，是必须显式点名的盲区。

## 8. 开放问题

- **CPCV 的计算/组合爆炸成本在本项目能否落地？** C(N,k) 随 N 增长极快，真实多资产（A股全市场 + 加密）上跑完整 CPCV 的算力/时间成本可能比 WF 高数量级——「默认双轨」在工程上的关键约束，需明确 N/k 上限与降级策略。
- **CPCV × 模型重训成本的乘积效应**：每条路径都要重训，DL 模型（项目 v3 训练平台已有 .pt 模型）下重训次数 = C(N,k)，对深度学习策略 CPCV 的「统计默认」地位可能因成本而**站不住**；是否对 DL 策略默认退化为 WF + 少数折？
- **锁死的默认 N/k/embargo 配置**：既然承认无理论最优且元过拟合风险高，需要一组「锁定、用户不可调、可审计」的具体默认值（含 A股 vs 加密两套日历折算），而非只说「自动推导」。
- **A股停牌/涨跌停如何精确进入 embargo/purge**：长期停牌（可达数月）会使按观测百分比设的 embargo 在停牌段失效；按「有效交易日」而非自然观测计数的具体落地机制待定，涨跌停「成交但价格被钉死」也需进入泄漏判定。
- **Arian 2024 的独立复现现状**：该论文发表后（2024→2026）是否已有独立复现、反驳或方法缺陷指出？引用停在发表时点，需周期性复检。
- **CPCV vs WF 之外的中间方案**：是否应纳入 nested CV / 嵌套时序 CV / block bootstrap 等介于两者之间、计算更省的方案，而非框死二选一？
- **SR 11-7 / NIST AI RMF / GIPS 的真实约束力**：对单用户量化项目是「合规话术借用」而非强制约束；作治理骨架时须明确其无强制力，避免用机构光环给方案镀金。

## 9. 参考文献（URL）

- AFML（López de Prado, 2018，第 7/12 章）：https://www.wiley.com/en-us/Advances+in+Financial+Machine+Learning-p-9781119482086
- Arian, Norouzi Mobarekeh & Seco (2024), *Knowledge-Based Systems* 305:112477（合成环境，不可外推）：https://dl.acm.org/doi/abs/10.1016/j.knosys.2024.112477 ；预印本 https://papers.ssrn.com/sol3/papers.cfm?abstract_id=4686376
- The Probability of Backtest Overfitting（Bailey-Borwein-LdP-Zhu 2015, SSRN 2326253）：https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2326253
- The Deflated Sharpe Ratio（Bailey & LdP 2014, SSRN 2460551）：https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2460551
- Deflated Sharpe Ratio（概念词条）：https://en.wikipedia.org/wiki/Deflated_Sharpe_ratio
- Leakage and the Reproducibility Crisis（Kapoor & Narayanan 2023, *Patterns* 4(9):100804，arXiv 2207.07048）：https://arxiv.org/abs/2207.07048
- REFORMS 报告标准（Kapoor et al., arXiv 2308.07832）：https://arxiv.org/abs/2308.07832
- skfolio（arXiv 2507.04176）：https://arxiv.org/abs/2507.04176 ；CombinatorialPurgedCV 文档：https://skfolio.org/generated/skfolio.model_selection.CombinatorialPurgedCV.html
- Purged cross-validation（embargo 规范定义/路径数公式）：https://en.wikipedia.org/wiki/Purged_cross-validation
- Walk-Forward Optimization（QuantInsti）：https://blog.quantinsti.com/walk-forward-optimization-introduction/
- mlfinlab 许可证（已闭源 All-Rights-Reserved）：https://github.com/hudson-and-thames/mlfinlab/blob/master/LICENSE.txt
- mlfinlab CombinatorialPurgedKFold 实现：https://github.com/hudson-and-thames/mlfinlab/blob/master/mlfinlab/cross_validation/combinatorial.py
- timeseriescv（轻量 PurgedKFold / CombinatorialPurgedKFold）：https://github.com/sam31415/timeseriescv
- pbo（R, mrbcuda，CSCV/PBO 实现）：https://github.com/mrbcuda/pbo
- SR 11-7（Fed/OCC 模型风险管理）：https://www.federalreserve.gov/supervisionreg/srletters/sr1107.htm
- NIST AI RMF 1.0：https://www.nist.gov/itl/ai-risk-management-framework
- CFA Institute GIPS Standards：https://www.cfainstitute.org/en/ethics-standards/codes/gips-standards
