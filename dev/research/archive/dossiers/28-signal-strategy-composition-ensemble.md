# 28 · 信号层/策略层的组合与集成（防 stacking 泄露）

> 机构级 Agent OS 成品环节深挖 · 全程 Opus 4.8 · 对抗式核查已降权 · 重心=前沿研究+概念级推荐 · 不含 file:line 代码接线
> 簇 E

## 1. 一句话定位

本环节回答一个「既是升维、又最容易爆雷」的问题：**当因子库保持纯净、把排列组合上移到信号/策略层去做组合与集成时，怎样既享受组合带来的研究自由度，又不让 stacking 泄露和组合搜索过拟合把夏普做成假的？** 学界与机构的共识可压缩成三条主轴——(1) **stacking 的 meta-learner 只能在 base 模型的 out-of-fold(OOF) 预测上训练**（Wolpert 1992 的定义性要求、van der Laan 的 Super Learner），且金融时序里普通 k-fold 的 OOF 仍因标签重叠泄露未来，必须叠加 López de Prado 的 **purging + embargo + 时间因果**；(2) **「学习型最优权重越复杂越好」在金融里多半是幻觉**——forecast-combination puzzle（50 年综述确认）表明简单等权常胜过估计的「最优权重」，故 meta-layer 默认应偏等权/收缩/受限权重，stacking 是需要额外证据才解锁的升级档；(3) **把排列组合上移会制造「组合搜索」，每多一个 base 集合/权重方案/regime 划分/阈值都要计入全局多重检验预算 N**，并用 Deflated Sharpe / CSCV-PBO 作为出闸硬闸门。本项目的诚实立场：机构级做法**不是提供更强的 stacking 算子，而是把 OOF+purge+embargo、N 自动累计、Deflated Sharpe/PBO 闸门做成不可绕过的流程护栏**，默认组合器设为等权/收缩，「流程即信任」= 泄露与多重检验由系统强制，而非靠用户自律。

## 2. 前沿 SOTA 与代表系统

| 系统 / 范式 | 角色 | 要点 | URL |
|---|---|---|---|
| **scikit-learn StackingClassifier / StackingRegressor** | 工业标准 OOF-stacking | 内部用 `cross_val_predict` 生成 base 模型 OOF 预测来训练 `final_estimator`，机制上避免 meta 看到 in-sample base 预测。**但默认 cv 是普通 KFold，对金融时序不防标签重叠泄露**，需替换为时间感知 / purged 的 cv splitter。 | https://scikit-learn.org/stable/modules/generated/sklearn.ensemble.StackingClassifier.html |
| **mlxtend StackingCVClassifier / StackingCVRegressor** | 显式 OOF stacking 参考 | 显式以 k-fold OOF 喂二层模型（对照其朴素 `StackingClassifier` 会在同一训练集拟合一二层、易过拟合），文档直接点名「用 OOF 防 overfitting」。同样需自带时序 cv 才能用于金融。 | https://rasbt.github.io/mlxtend/user_guide/classifier/StackingCVClassifier/ |
| **skfolio CombinatorialPurgedCV** | 「组合搜索→回测分布→PBO/Deflated SR」落地零件 | BSD 开源组合优化库，内置 CPCV：purging+embargo+多测试路径（p>1），可生成回测分布做过拟合分析，直接对应 López de Prado AFML。**注**：CPCV 相对 walk-forward 的「优越性」主要在合成受控环境确立，真实交易仿真仍以 WF 为行业标准（见 §7）。 | https://skfolio.org/generated/skfolio.model_selection.CombinatorialPurgedCV.html |
| **Super Learner（van der Laan / SuperLearner R 包）** | 「OOF 上学组合权重」最严谨理论原型 | 基于 V-fold CV 学习候选学习器的最优凸组合，带 oracle 不等式（渐近不劣于库中事后最优组合）。**注**：保证为渐近 / IID / 有界损失框架，低信噪比、非平稳、有成本的中低频实盘不满足前提，迁移需自证（见 §7）。 | https://biostats.bepress.com/ucbbiostat/paper222/ |
| **AutoGluon 多层 stacking / 2511.15350 时序多层 stack** | 多层 stack 自动化范式 | 给出时间感知 OOF 生成（meta 训练样本只来自更早数据训练的 base），并实证多层 stacking 在其基准上优于简单平均。**注**：评测集全为 Monash / GIFT-Eval / M4 / M5 通用高信噪比预测基准，**不含金融 / 中低频交易数据**，证据等级在本语境被高估（见 §7）。 | https://arxiv.org/abs/2511.15350 |

## 3. 关键论文（每条带 URL）

- **Stacked Generalization（Wolpert, 1992, *Neural Networks* 5(2)）**——提出 stacking：二层泛化器在「用部分训练集训练一层、去猜剩余部分」得到的预测上学习——即 **OOF 是 stacking 的定义性要求，而非可选项**。后续所有「防 stacking 泄露」都源于此。
  https://www.sciencedirect.com/science/article/abs/pii/S0893608005800231

- **Super Learner（van der Laan, Polley, Hubbard, 2007, *Statistical Applications in Genetics and Molecular Biology*）**——用 V-fold CV 在候选学习器上学最优组合权重，证明 oracle 不等式：渐近上与库中事后最优组合一样好。给「在 OOF 上学组合」提供理论正当性，**但属渐近、损失基、IID 框架，低信噪比金融需谨慎外推**。
  https://biostats.bepress.com/ucbbiostat/paper222/

- **Forecast Combinations: An Over 50-Year Review（Wang, Hyndman, Li, Kang, 2022, arXiv:2205.04216，后发 IJF）**——系统确认 **forecast-combination puzzle**：简单等权常胜过估计的「最优权重」，因估计误差 / 方差盖过理论收益；复杂权重仅在样本大、环境稳、分量误差结构确有差异时才占优。直接支持「meta-layer 默认偏等权 / 收缩」。
  https://arxiv.org/pdf/2205.04216

- **The Probability of Backtest Overfitting（Bailey, Borwein, López de Prado, Zhu, 2017, *J. Computational Finance* / SSRN 2326253）**——提出 CSCV（组合对称交叉验证），以模型无关、非参方式估计 **PBO**——把「我在组合层试了很多配置」量化为过拟合概率与样本外性能退化，是组合搜索治理的核心可操作指标。
  https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2326253

- **The Deflated Sharpe Ratio（Bailey & López de Prado, 2014, *J. Portfolio Management* / SSRN 2460551）**——按试验数 N、偏度、峰度、样本长度 deflate 夏普；关键实务点：**相关试验要折算为 effective N**（150 个高度同向配置的有效 N 远小于 150）。组合 / 排列搜索必须把每个 base 集合 / 权重方案 / regime 划分计入 N。
  https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2460551

- **…and the Cross-Section of Expected Returns（Harvey, Liu, Zhu, 2016, *Review of Financial Studies* 29(1) / NBER w20592）**——因海量已测因子，主张新发现需把 t 门槛抬到 ~3.0（并考虑相关性与发表偏倚）。**注**：该论文「多数金融实证发现可能是假」的强论断在文献中被实质性反驳（Chen-Zimmermann，见 §7），t>3 作为多重检验提醒可保留，但强论断已下调。
  https://www.nber.org/system/files/working_papers/w20592/w20592.pdf

- **The Garden of Forking Paths（Gelman & Loken, 2013, working paper）**——即便只跑一条分析、假设事先设定，数据依赖的处理 / 分析选择等价于海量隐性多重比较——解释了为何「组合层不自报 N 也会过拟合」。Agent OS 应把这些隐性分叉显式计入预算。
  https://sites.stat.columbia.edu/gelman/research/unpublished/p_hacking.pdf

- **Does Academic Research Destroy Stock Return Predictability?（McLean & Pontiff, 2016, *J. Finance* 71(1) / SSRN 2156623）**——97 个预测变量样本外收益低 **26%**、发表后低 **58%**。组合出的 alpha 会显著衰减——这是对「组合层堆出高夏普」最该写进用户预期的诚实前提。数值核实准确。
  https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2156623

- **When Alpha Disappears: A One-Switch Benchmark for Decision-Time Leakage in Financial Backtests（2026, arXiv:2605.23959，University of Tokyo / HKUST-GZ，2026-05-12）**——跨 2 个日频股票面板、6 类模型、2016–2024 年度测试：**泄露高度「选择性」**——居中时序特征、同日开盘执行带入开盘后日内信息会稳定、大幅抬高预测与交易指标。提醒组合 / 执行接缝处的决策时点泄露同样致命，CV 干净不等于赢。
  https://arxiv.org/abs/2605.23959

- **Advances in Financial Machine Learning（López de Prado, 2018, Wiley）**——系统化 **purged k-fold + embargo** 防标签重叠泄露，及 **meta-labeling**（一层定方向、二层定下注大小 / 过滤假阳）。**注**：meta-labeling 的增量价值在文献中两极、未稳健复现（见 §7），作为「策略层组合限制 ML 自由度」的结构范式可提，但不作稳妥默认推荐。
  https://en.wikipedia.org/wiki/Purged_cross-validation

## 4. 机构最佳实践 / 标准

- **Federal Reserve / OCC SR 11-7（模型风险管理指引）**：组合 / 集成模型也必须由独立于开发者的人 / 流程做 effective challenge，验证其机制（不只拟合），并以 challenger 基准对照、持续监控。对 Agent OS 即「组合器要有可独立复核的留痕与基准对照」。**注**：对单用户量化项目是治理骨架借用而非强制约束（见 §8）。
  https://www.federalreserve.gov/supervisionreg/srletters/sr1107.htm

- **Federal Reserve / OCC / FDIC SR 26-2（2026-04-17 替代 SR 11-7，三机构联合发布，核实属实）**：从「每年重验」转为按模型重要性 / 材料性分级的风险导向监督；inherent risk 显式包含复杂度、假设数量、数据质量、可解释性——方向上支持「stacking 默认更高门槛、需更强证据解锁」。**注**：原文为原则性而非逐条点名某技术，「稀疏数据上的深度学习集成被点名为高固有风险」应读作**对一般 MRM 原则的合理解读 / 二手转述**，非标准明文（见 §7）。
  https://www.federalreserve.gov/supervisionreg/srletters/SR2602.htm

- **CFA Institute Research Foundation, Ch.4 Ensemble Learning in Investment (2025)**：投资场景用 bagging / boosting / stacking 需要「纪律化的验证切分、泄露控制、性能监控」（governance requires disciplined validation splits, leakage control, and performance monitoring），并适用 no-free-lunch（集成非普适更优，要权衡速度 / 精度 / 复杂度），且需 SHAP 等可解释性以备合规辩护。
  https://rpc.cfainstitute.org/research/foundation/2025/chapter-4-ensemble-learning-investment

- **NIST AI Risk Management Framework（AI RMF 1.0，Govern / Map / Measure / Manage）**：把「可信赖性度量 + 全生命周期治理」制度化，适合作为 Agent OS 给非技术用户出具「组合层是否可信」结论的外部对齐框架（有效性可靠性、可问责、可解释）。
  https://www.nist.gov/itl/ai-risk-management-framework

> **诚实标注（贯穿全节）**：CFA / SR 11-7 / SR 26-2 讲的是治理原则（独立验证、概念健全性、challenger、泄露控制、按重要性分级），**并未给「组合层该计多少 N」「夏普该 deflate 多少」的量化处方**——本环节的量化阈值是从一般 MRM 原则到本环节的**合理外推**，落地阈值需团队自定并留痕，**别假托标准明文**。

## 5. 对 QuantBT 这套架构的推荐方向（概念级）

> 概念级方向，不点 file:line、不排实施计划。

1. **OOF + purged + embargo + 时间因果设为组合 / 集成层不可绕过的默认管线**：在信号 / 策略层做任何 stacking / blending 时，meta 训练数据只能来自**更早数据训练**的 base 模型的 OOF 预测，且标签时间窗与测试集重叠的样本被 purge、其后缓冲被 embargo。用户对话里不暴露这些旋钮，系统强制执行，并用一句经济学者能懂的话解释（「不能让裁判提前看到考卷答案」）。这与簇 C 第 16 环节的 purge/embargo 脊柱**共用同一套由 label horizon + 资产日历推导的时间跨度**，避免组合层另起一套泄露口径。

2. **默认组合器 = 等权 / 收缩 / 受限权重，而非自由 stacking**：基于 forecast-combination puzzle，把「升级到学习型 meta-weights / 多层 stacking」设为需要额外证据（更长样本、稳定性检验、OOS 一致性、Deflated SR 通过）才解锁的进阶档。当小白选「要不要更聪明地组合」时，Agent 默认劝阻并解释估计误差风险。**补强（对抗核查漏点）**：在「等权 ↔ 学习型 stacking」两端之间，显式提供机构常用的**无监督风险型中间档**——风险平价 / 波动率倒数加权 / 层次风险平价（HRP）/ 最小相关组合。它们既避开 forecast-combination puzzle 的估计误差，又比朴素等权更稳，且**不引入 meta-learner 泄露面**，应作为「比等权聪明、但不开 stacking」的安全默认升级路径。

3. **把「组合搜索」纳入全局多重检验预算 N**：每多一个 base 模型集合、每个权重方案、每种 regime 划分、每条阈值，都自动累加进 N（对高相关试验折算 effective N），最终用 Deflated Sharpe / CSCV-PBO 作组合层成果出闸的硬闸门。这把「排列组合上移到信号层」从过拟合温床变成可治理的资产。**诚实张力（对抗核查漏点）**：effective N 的估计**本身是未解难题**——它依赖试验间相关矩阵，而该矩阵在 walk-forward / 在线探索下既难观测又随时间漂移。落地时不可把「N 由系统记账」当成已解护栏，须显式标注 effective N 的估计方法、误差与对闸门阈值的**敏感性**，并对 N 计数采用保守上界而非精确点估。

4. **为非技术用户产出「诚实预期」与「组合层可信度结论」**：默认展示 OOS / 发表后 / 计成本后的衰减预期（引 McLean-Pontiff 的 26% / 58% 量级作先验区间）、PBO 概率、Deflated SR 是否显著，并把「**简单等权 baseline vs 复杂组合**」的对照作为强制 challenger（对齐 SR 11-7 / SR 26-2 的 challenger 与按重要性分级）。「流程即信任」落在「系统替你算多重检验与泄露，并据此给红绿灯」。

5. **对中低频、资产无关定位做结构化降风险**：可考虑 meta-labeling 式分层（一层定方向、二层只定 size / 过滤假阳）与 regime-conditional 组合，因其天然限制 ML 自由度、可解释性更好。**降权（对抗核查）**：meta-labeling 的实证收益**有争议、未稳健复现**（有报告提升、亦有报告无效甚至变差），**不得作为稳妥默认推荐**，只置于「实验性、需自证增量」开关后。

6. **net-of-cost / 换手 / 容量护栏与 OOF/embargo 同级（对抗核查漏点）**：中低频资产无关实盘里，组合 / 集成最常见的「假赢」来自**多个 base 信号组合后净换手爆炸**——gross 夏普漂亮、net 归零。仅用 McLean-Pontiff 26%/58% 作笼统衰减先验不够，须把「组合层必须做 net-of-cost、容量加权、换手预算」写成与 OOF/embargo 同级的不可绕过护栏，对接簇 C 第 18 环节（TCA / impact / capacity）。

7. **regime 组合的「推荐 vs 雷区」取舍判据（对抗核查漏点）**：regime-conditional 组合既是降风险手段，又是泄露与 N 膨胀双重温床。调和判据：(a) **只用因果 / 在线可得的 regime**（避免 in-sample 拟合的 HMM/GMM 状态用到未来信息）；(b) **regime 数本身纳入 N**（换一种 regime 划分 = 一次隐性试验）；(c) **regime 切换点设 embargo**。不满足前两条的 regime 组合默认不解锁。

8. **交互式探索的人在回路 N 记账（对抗核查漏点）**：Agent OS 里用户反复对话、看一次 OOS 结果再调下一步，构成 Gelman forking paths 的人在回路版本，N 会随交互次数无声膨胀——这比「组合层零件」更根本。需对**交互式探索本身**记账：会话级 N 上限 / 试验配额 / 关键决策前的轻量预注册（对接簇 C 第 05 环节可证伪假设预注册），而非只盯组合层的显式排列组合。

9. **闸门防 Goodhart 博弈（对抗核查漏点）**：一旦 PBO / Deflated SR / N 闸门成为强制红绿灯，用户或 Agent 自身会学会迎合闸门（刻意降低试验间相关以压低 effective N、挑选能压低 PBO 的回测路径划分）。对策：闸门参数对用户不可见且可随机化、全程留痕审计、challenger 由**独立流程**跑——把「流程即信任」延伸到「闸门本身不可被研究者博弈」。

## 6. 架构级参考（少量伪代码 / schema 草图，非代码接线）

> 示意，非接线到现有代码。

**时间因果 OOF 生成（meta 样本只来自更早数据训练的 base）：**

```
# 铁律：meta_X[t] 只能来自「截至 t 之前的数据」训练出的 base 模型的 OOF 预测
for fold in time_ordered_folds(data):           # 严格按时间，禁止随机洗牌
    train_idx = purge_then_embargo(              # 复用第 16 环节同一套时间跨度
        earlier_than(fold), test=fold,
        purge_span=label_max_horizon, embargo_span=embargo_pct * n_obs)
    base.fit(train_idx)                          # base 只见更早数据
    meta_X[fold] = base.predict_oof(fold)        # OOF 预测喂二层
# 禁止：用 in-sample base 预测、或普通 k-fold OOF（标签重叠仍泄露未来）
```

**默认组合器谱系（等权 → 风险型 → 受额外证据门槛的 stacking）：**

```
combiner_ladder:
  - tier: equal_weight            # 默认起点（forecast-combination puzzle）
  - tier: risk_based              # 无监督中间档：inverse-vol / risk-parity / HRP / min-corr
                                  #   不引入 meta-learner 泄露面
  - tier: shrinkage_weights       # 受限/收缩权重
  - tier: learned_stacking        # 仅在通过 unlock_gate 后解锁
    unlock_gate:
      requires: [longer_sample, stability_check, oos_consistency, deflated_sharpe_pass]
```

**组合层多重检验记账 + 出闸闸门（schema 草图）：**

```yaml
composition_card:
  search_budget:
    n_trials: T                      # 累计：base 集合 + 权重方案 + regime 划分 + 阈值
    n_interactive: T_session         # 人在回路：交互式探索次数（forking paths）
    effective_n: T_eff               # < T；标注 estimation_method 与 sensitivity（未解难题）
    effective_n_caveat: "依赖试验相关矩阵，WF/在线下漂移，取保守上界"
  gates:                             # 硬闸门，gross 与 net 各跑一遍
    deflated_sharpe: 0.xx            # 按 T_eff/偏度/峰度/样本长度向下去通胀
    pbo: 0.xx                        # CSCV 估计
    challenger_baseline:             # 强制对照：等权/HRP vs 复杂组合
      equal_weight_sharpe: ...
      complex_combiner_sharpe: ...
      verdict: <complex_beats_baseline_after_deflation? yes|no>
  honest_expectation:                # 写进用户预期
    oos_decay_prior: "-26%"          # McLean-Pontiff
    post_publication_decay_prior: "-58%"
    net_of_cost: <pass|fail>         # 与 OOF/embargo 同级护栏：换手预算/容量加权
  regime_block:                      # 推荐 vs 雷区调和判据
    regime_source: <causal_online|in_sample>   # 仅 causal_online 默认解锁
    regime_count_in_n: true                     # 计入 T
    switch_point_embargo: true
  leakage_audit:
    base_pred_is_oof: true
    time_causal_oof: true
    decision_time_leakage_checked: <yes|no>     # 组合/执行接缝（arXiv 2605.23959）
  anti_goodhart:
    gate_params_hidden_from_user: true
    challenger_run_by_independent_flow: true
    audit_trail: [...]
# stacking 默认劝阻；闸门未过 → 退回 equal_weight/risk_based 档
```

## 7. 降权 / 争议 / 陷阱（对抗核查结论）

> 以下限定词（夸大 / 争议 / 撤稿 / 二手 / 不可外推 / 单源 / 笔误 / 未复现 等）**原样保留**；凡涉「已验证 / 已确证 / 总是更优 / 多数发现为假」的强确定性措辞均已按对抗核查降级。任何对用户的承诺或文案，必须采用降级后的表述。

- **【medium · 单边引用 / 强论断需下调】「引 Harvey-Liu-Zhu(2016) 把 t 门槛抬到 ~3.0，并断言『多数声称的金融实证发现可能是假的』」**——这是**已知雷区**：把一个**有重大争议**的论断当成既定共识陈述。Andrew Chen & Tom Zimmermann 的系列工作（*Publication Bias and the Cross-Section of Stock Returns* / *Do t-Statistic Hurdles Need to Be Raised?*，后者发于 *Management Science*）用元研究给出四条相反 stylized facts：几乎所有发现可复现、可预测性 OOS 持续、实证 t 远大于 2.0、预测因子弱相关；经验贝叶斯估计发表偏误仅解释 in-sample 均值收益的 **10–15%**，假发现率 **<6%**，并论证 p-hacking 单独无法解释 factor zoo。研究单边引 HLZ 而完全不提这条已发表的反方文献，**把『t>3 / 多数发现为假』呈现为定论是夸大**。t>3 门槛本身作为多重检验提醒可保留，但「多数发现为假」的强论断应下调。
  https://pubsonline.informs.org/doi/10.1287/mnsc.2023.03083

- **【medium · 证据等级被高估 / 范围越界】「把 arXiv 2511.15350 当作『多层 stacking 在时序上实证优于简单平均』的 SOTA 实证证据」**——论文真实（已被 PMLR v293 / Amazon Science 收录，无撤稿），**但其评测集是 Monash / GIFT-Eval / M4 / M5 等通用时序预测基准，完全不含金融 / 中低频交易数据**。这些 M-竞赛序列信噪比远高于金融收益，恰恰是研究自己背书的 forecast-combination puzzle 预测「复杂权重可能取胜」的高 SNR / 大样本 regime。研究虽加了「迁移到中低频实盘需自证」的诚实标注，但**没点破真正的机制张力**：它一边用 2511.15350 论证 stacking 能赢、一边用 forecast-combination puzzle 论证默认应等权，而二者的分水岭（信噪比 / 样本量）正是把 M-竞赛 regime 与金融区分开的关键。**在金融语境下，该证据等级被高估**，不可作为「stacking 作为可解锁升级」的实证背书。
  https://arxiv.org/abs/2511.15350

- **【low · 未稳健复现 / 不作稳妥默认】「meta-labeling（一层定方向、二层定 size / 过滤假阳）天然限制 ML 自由度、可解释性更好、更易通过 MRM 验证，作为优先推荐的降风险范式」**——meta-labeling 的实证收益**有争议、而非已确证**。公开证据两极：有研究 / Hudson & Thames 报告其在 triple-barrier 上提升 signal efficacy，也有从业与社区报告在已较好的分类器之上叠加 meta model 反而显著变差、并非普适。研究把它作为优先推荐的降风险结构，**却未标注「其增量价值取决于具体实现、可能无效甚至有害」这一已知限制**——属于把一个未稳健复现的技巧呈现为稳妥默认。已在 §3/§5 改为「可提、需自证增量、置于实验性开关后」。
  https://hudsonthames.org/does-meta-labeling-add-to-signal-efficacy-triple-barrier-method/

- **【low · 外推过度 / 省略关键 caveat】「把 skfolio 的 CombinatorialPurgedCV(CPCV) + PBO/Deflated SR 直接当作组合层成果出闸的『现成零件 / 硬闸门』，隐含 CPCV 优于 walk-forward 是普适既定事实」**——`skfolio.CombinatorialPurgedCV` 真实存在（purging+embargo+多路径，BSD）。但 **CPCV 相对 walk-forward 的「优越性」主要在合成受控环境中被确立**（代表性证据 *Knowledge-Based Systems* S0950705124011110，标题即含 "in a synthetic controlled environment"）；连支持 CPCV 的来源也指出「walk-forward 仍是贴近真实交易仿真的行业标准」。把 CPCV 包装成可直接落地的生产闸门而未带「合成环境下显著、真实环境下仍需 WF 仿真」的限定，**属外推过度**。落地应 CPCV / WF 双轨并行，背离时采信更保守一方。
  https://www.sciencedirect.com/science/article/abs/pii/S0950705124011110

- **【low · 二手解读 / 非标准明文】「SR 26-2 点名『稀疏数据上的深度学习集成为高固有风险』，以支撑 stacking 默认更高门槛」**——SR 26-2（2026-04-17 三机构联合发布、替代 SR 11-7）与「从年度重验转向按模型重要性 / 材料性的风险导向监督」方向**核实属实，这部分不夸大**。但「稀疏数据上的深度学习集成被点名为高固有风险」这类**具体措辞更像二手解读**（咨询 / 厂商博客转述 inherent risk 含复杂度 / 假设数 / 可解释性的口径），**原文是原则性而非逐条点名某技术**。该具体点名已降级为「对一般 MRM 原则的合理解读」，与既有诚实标注一致，避免读成标准明文。
  https://www.federalreserve.gov/supervisionreg/srletters/SR2602.htm

- **【low · 引用笔误 / 不影响论点】2605.23959 在原 ref 字段被误写为 2606.23959**——论文《When Alpha Disappears: A One-Switch Benchmark for Decision-Time Leakage》真实存在（**arXiv 2605.23959，2026-05-12 提交，University of Tokyo / HKUST-GZ**），其「泄露高度选择性、居中时序特征 + 同日开盘执行稳定抬高指标」的结论核实无误，作为「决策时点泄露」论据成立。仅编号 2605 vs 2606 不一致，已在本 dossier 全文更正为 2605.23959。
  https://arxiv.org/abs/2605.23959

- **【参照 · confirmed，不降级】**：Wolpert(1992) stacking 的 OOF / 交叉验证分区为**定义性要求**、Super Learner oracle 不等式属**渐近 / IID / 有界损失 / V-fold 框架**、sklearn StackingRegressor 用 `cross_val_predict` 且默认普通 5 折 KFold、文档不警告时序泄露、forecast-combination puzzle、McLean-Pontiff 26% / 58%、SR 26-2 替代 SR 11-7——均经核实**作者署名 / 年份 / 期刊 / 数值准确、属实**。

**通用陷阱清单（工程红线）：**

- **最致命也最隐蔽：用 in-sample base 预测（或普通 k-fold 的 OOF）训练 meta-model**。金融时序里普通 OOF 仍因标签重叠泄露未来——必须 purged + embargo + 时间因果，否则 meta-layer 夏普是假的。
- **组合层是隐形的多重检验放大器**：排列组合上移会爆炸式增加试验数却常不被计入 N。Garden of forking paths 表明即便「只跑一条」也等价于海量隐性比较——**不自动记账就必然乐观偏倚**。
- **迷信「学习型最优权重」**：forecast-combination puzzle 表明估计权重的方差 / 估计误差常盖过理论收益，复杂 meta-weights 在小样本 / 非平稳金融里往往不如等权——**默认上 stacking 是反模式**。
- **把 Super Learner 的 oracle 保证当实盘承诺**：那是渐近、IID、损失基框架下的，低信噪比 / 非平稳 / 有交易成本的中低频实盘不满足前提，**迁移需自证**。
- **只看 in-sample / gross 组合夏普，不计 OOS 衰减与成本**：McLean-Pontiff（OOS −26% / 发表后 −58%）与 ML-net-of-cost 之争说明组合出的 alpha 会显著缩水；**不向用户披露 = 不诚实交付**。
- **regime-switching 组合的双重陷阱**：(a) regime 标签本身可能用到未来信息（in-sample 拟合的 HMM/GMM 状态）造成泄露；(b)「换一种 regime 划分」是一次隐性试验，须计入 N。
- **把机构标准当量化处方**：SR 11-7 / SR 26-2 / CFA 给的是治理原则，**并未规定「组合层该计多少 N 或夏普该 deflate 多少」**——这部分是合理外推，落地阈值需团队自定并留痕，别假托标准明文。
- **决策时点泄露在组合 / 执行接缝处复现**：如 arXiv 2605.23959 所示，居中时序特征、同日开盘带入开盘后信息会稳定抬高指标。**组合层即便 CV 干净，若执行假设穿越信息仍会假赢**。
- **effective N 估计本身是未解难题**：它依赖试验相关矩阵，而该矩阵在 WF / 在线探索下既难观测又漂移——「N 由系统记账」**不是已解护栏**，须取保守上界并标注敏感性。
- **闸门可被 Goodhart 博弈**：用户或 Agent 会学会迎合闸门（压低 effective N、挑能压低 PBO 的路径划分）；闸门参数须对用户不可见 / 可随机化、留痕审计、challenger 独立流程跑。

## 8. 开放问题

- **effective N 到底怎么可信地估出来？** DSR 的有效试验数依赖试验间相关矩阵，而该矩阵在 walk-forward / 在线交互探索下既难观测又随时间漂移。在没有可靠 effective N 估计的前提下，「N 由系统记账、用户改不了也无需懂」这个护栏的地基是空的——需要明确估计方法、误差棒、以及对闸门阈值的敏感性，否则闸门是「精确的错」。
- **交互式探索 / 回测循环的人在回路 N 如何记账？** 用户反复对话、看一次 OOS 再调下一步，是 Gelman forking paths 的人在回路版本，N 随交互次数无声膨胀。预注册？会话级 N 上限？试验配额？这比「组合层零件」更根本，目前无成熟范式。
- **net-of-cost / 换手 / 容量护栏与统计闸门谁先谁后？** 多个 base 信号组合后净换手常爆炸，gross 漂亮 net 归零。换手预算 / 容量加权应作为与 OOF/embargo 同级的硬约束，但其与 PBO/DSR 的执行顺序、以及 A股（到 paper）vs 加密（到 Binance 实盘）两套成本模型如何统一进闸门，待定。
- **CPCV 在多资产 + DL 模型下的算力可行性？** 每条路径都要重训，C(N,k) × 模型重训成本对 DL 策略（项目 v3 训练平台已有 .pt 模型）可能站不住；组合层是否对 DL 默认退化为 WF + 少数折？
- **风险型无监督组合器（HRP / 风险平价）应占什么默认地位？** 它是「比等权聪明、不开 stacking」的机构常用中间档，但其参数（如 HRP 的聚类、协方差估计窗）本身也是隐性试验——是否也要计入 N？
- **Chen-Zimmermann vs Harvey-Liu-Zhu 之争对本项目门槛的实际影响**：若发表偏误只解释 10–15%、FDR <6%，则把 t 门槛硬抬到 3.0 可能过严、扼杀真发现。本项目该取哪一档显著性门槛，需团队拍板并留痕，不可单边假托 HLZ。
- **闸门被博弈后的失效模式与监测**：闸门参数随机化 / 隐藏 / 独立 challenger 是对策方向，但如何在「流程即信任」与「闸门不可被研究者迎合」之间取得可审计的平衡，仍是开放治理问题。
- **机构标准对单用户量化项目的真实约束力**：SR 11-7 / SR 26-2 / NIST AI RMF / CFA 是治理骨架借用而非强制约束；作骨架时须明确其无强制力，避免用机构光环给方案镀金。

## 9. 参考文献（URL）

- Stacked Generalization（Wolpert, 1992, *Neural Networks* 5(2)）：https://www.sciencedirect.com/science/article/abs/pii/S0893608005800231
- Super Learner（van der Laan, Polley, Hubbard, 2007）：https://biostats.bepress.com/ucbbiostat/paper222/
- Forecast Combinations: An Over 50-Year Review（Wang, Hyndman, Li, Kang, 2022, arXiv:2205.04216）：https://arxiv.org/pdf/2205.04216
- The Probability of Backtest Overfitting（Bailey, Borwein, López de Prado, Zhu, 2017, SSRN 2326253）：https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2326253
- The Deflated Sharpe Ratio（Bailey & López de Prado, 2014, SSRN 2460551）：https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2460551
- …and the Cross-Section of Expected Returns（Harvey, Liu, Zhu, 2016, NBER w20592）：https://www.nber.org/system/files/working_papers/w20592/w20592.pdf
- Chen & Zimmermann（反方，*Management Science*：Do t-Statistic Hurdles Need to Be Raised?）：https://pubsonline.informs.org/doi/10.1287/mnsc.2023.03083
- The Garden of Forking Paths（Gelman & Loken, 2013）：https://sites.stat.columbia.edu/gelman/research/unpublished/p_hacking.pdf
- Does Academic Research Destroy Stock Return Predictability?（McLean & Pontiff, 2016, SSRN 2156623）：https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2156623
- When Alpha Disappears: A One-Switch Benchmark for Decision-Time Leakage（2026, arXiv:2605.23959）：https://arxiv.org/abs/2605.23959
- Advances in Financial Machine Learning（López de Prado, 2018；Purged CV / Meta-Labeling 词条）：https://en.wikipedia.org/wiki/Purged_cross-validation
- Multi-layer Stack Ensembles for Time Series Forecasting（2511.15350，范围越界，非金融基准）：https://arxiv.org/abs/2511.15350
- Backtest Overfitting OOS 比较（合成受控环境，CPCV vs WF caveat）：https://www.sciencedirect.com/science/article/abs/pii/S0950705124011110
- scikit-learn StackingClassifier：https://scikit-learn.org/stable/modules/generated/sklearn.ensemble.StackingClassifier.html
- scikit-learn StackingRegressor：https://scikit-learn.org/stable/modules/generated/sklearn.ensemble.StackingRegressor.html
- mlxtend StackingCVClassifier：https://rasbt.github.io/mlxtend/user_guide/classifier/StackingCVClassifier/
- skfolio CombinatorialPurgedCV：https://skfolio.org/generated/skfolio.model_selection.CombinatorialPurgedCV.html
- meta-labeling 增量价值（两极、未稳健复现）：https://hudsonthames.org/does-meta-labeling-add-to-signal-efficacy-triple-barrier-method/
- pbo（R, mrbcuda，CSCV/PBO 实现）：https://github.com/mrbcuda/pbo
- mlfinpy（AFML 零件：purged k-fold / embargo / meta-labeling）：https://mlfinpy.readthedocs.io/en/latest/Labelling.html
- SR 11-7（Fed/OCC 模型风险管理）：https://www.federalreserve.gov/supervisionreg/srletters/sr1107.htm
- SR 26-2（2026-04-17 替代 SR 11-7，风险/重要性导向）：https://www.federalreserve.gov/supervisionreg/srletters/SR2602.htm
- CFA Institute Ch.4 Ensemble Learning in Investment (2025)：https://rpc.cfainstitute.org/research/foundation/2025/chapter-4-ensemble-learning-investment
- NIST AI RMF 1.0：https://www.nist.gov/itl/ai-risk-management-framework
