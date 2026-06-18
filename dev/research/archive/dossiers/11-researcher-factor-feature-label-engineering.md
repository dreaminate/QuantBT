# 11 · 研究官：因子/特征/标签工程（防泄露）

> 机构级 Agent OS 成品环节深挖 · 全程 Opus 4.8 · 对抗式核查已降权 · 重心=前沿研究+概念级推荐 · 不含 file:line 代码接线
> 簇 B

## 1. 一句话定位

研究官是 Agent OS 的「特征/标签工厂」：把澄清官产出的良构假设，转译成一组**带 provenance、防泄露可审计、资产无关**的特征与标签——并把「防泄露」从一句口号降维成一套**机器可检查的工程契约**（每个特征/标签声明其 as-of 决议时间、可见性/可成交窗口、所引用未来信息=0 的证明）。这一环节**不缺零件**（AFML 五大支柱 + Qlib/Alphalens/fracdiff 等开源算法齐备），缺的是把零件焊成「对小白可信、可审计、把 A 股 T+1/T+2、停牌/ST/退市、point-in-time 财报、survivorship 固化进契约」的乐器。它的核心张力在 §7-§8 暴露：**最相关的合规叙事骨架（SR 11-7）已于 2026-04 被取代且把 agentic AI 划出范围；而 agent 自动批量造因子下「有效试验数 N」在数学上近乎不可数，使整套多重检验治理可能无法诚实落地。**

## 2. 前沿 SOTA 与代表系统

本环节的「事实标准」由 Marcos López de Prado（AFML 2018、《ML for Asset Managers》2020）的知识体主导。**注意（见 §7 降权）：把 AFML 体系定性为成熟「事实标准 / institutional default」略有夸大——triple-barrier 的竖直屏障是任意超参（arbitrary）、fracdiff 的 d、purged+embargo 的 embargo 长度都是需调参的设计选择而非被独立验证的定律；其有效性证据多来自其著作 + 商业方 Hudson & Thames（利益相关）+ 碎片化博客，缺独立大规模随机对照复现。**

**AFML 五大支柱（已确证的方法体，但复现支撑见 §7）**

- **标签工程** — triple-barrier（按波动率动态设上/下/竖直三道屏障，标签由「先触碰哪道」决定）取代固定时间窗 labeling（后者忽略路径、止盈止损、变持仓期）；trend-scanning 作无方向先验的替代；meta-labeling 把「方向 side」与「下注大小 size」解耦——一级模型出方向、二级 ML 只学「该不该信这笔/下多大」，专门压低假阳性、改善精确率/Sharpe/回撤。
- **特征平稳化** — fractional differentiation（分数阶差分 d∈[0,1]）在保留长记忆的同时达平稳，反对「整数阶差分(收益率)=系统性过度差分、抹掉全部记忆」。**注意（见 §7）：fracdiff 实证上相对简单收益率/对数差分的下游预测增益常很小甚至不显著（多为作者圈外质疑），且 d 的在线/滚动估计会引入自身前视风险——把它设为不可商量的默认值缺乏独立增益证据。**
- **样本权重** — 金融样本因标签重叠而非 IID，需按 concurrency/uniqueness 加权 + sequential bootstrap 去偏，可按收益绝对值加权；**严格区分「信息唯一性权重」与「收益权重」**两个旋钮，混淆会导致预测崩溃或过度交易。
- **防泄露 CV** — purged k-fold + embargo 切断训练/测试集间因序列相关与标签重叠产生的泄露；CPCV（组合式 purged CV）给多条回测路径；配合 PBO(CSCV)、Deflated Sharpe、最小回测长度做多重检验校正。
- **特征重要性** — MDI/MDA 在共线/替代效应（substitution effects）下不稳健，需 Clustered Feature Importance（先聚类再簇级评估）。

**代表系统**

- **Microsoft Qlib（Alpha158 / Alpha360 + 表达式引擎）** — 内置人工特征/原始量价数据集与表达式因子引擎、point-in-time 数据层、20+ 模型基准。其标签刻意写成 `Ref($close,-2)/Ref($close,-1)-1`（T+1→T+2）以契合 A 股 T+1 买入/T+2 卖出制度、避免不可成交泄露——是**资产制度感知防泄露**的可借鉴范式。<https://github.com/microsoft/qlib>
- **Alphalens / alphalens-reloaded** — 因子评估事实标准：从因子值+价格自动产出 IC/RankIC、分位数收益、换手率、alpha decay、按行业分解 tear sheet。**注意（见 §7）：原 quantopian/alphalens 已随 Quantopian 关闭停更；实际活跃维护的是 stefan-jansen/alphalens-reloaded（2025-06 仍发版 v0.4.6、2026 仍有 issue）。** <https://github.com/stefan-jansen/alphalens-reloaded>
- **MlFinLab（Hudson & Thames）** — AFML 全流程参考实现。**注意（见 §7）：MlFinLab 已转商业/闭源许可（proprietary，默认仅限非商业使用，商业需购买），不能直接当 MIT 依赖；mlfinpy 为 MIT 开源替代、社区另有历史开源快照。** <https://github.com/hudson-and-thames/mlfinlab> ｜ 开源替代 <https://github.com/baobach/mlfinpy>
- **ML for Trading（Stefan Jansen）配套库** — 把 AFML 防泄露/多重检验（purged CV、最小回测长度、Deflated SR）与因子工程串成端到端、可教学的开源 pipeline，适合作「机器可执行流程」蓝本。<https://github.com/stefan-jansen/machine-learning-for-trading>

## 3. 关键论文（每条带 URL）

- **Advances in Financial Machine Learning (AFML)** — López de Prado, Wiley 2018。本环节母体：triple-barrier、meta-labeling、fractional differentiation、concurrency/uniqueness 样本权重、sequential bootstrap、purged k-fold + embargo、CPCV、MDI/MDA。是 SOTA「institutional default」**但属作者主导、缺独立大规模复现（见 §7）**。<https://www.wiley.com/en-us/Advances+in+Financial+Machine+Learning-p-9781119482086>
- **The 10 Reasons Most Machine Learning Funds Fail** — López de Prado 2018。把反模式编号成 10 个 pitfall：#4 整数阶差分（过度差分抹记忆）、#5 固定时间窗 labeling、#6 同时学 side+size、#7 非 IID 样本不加权、#8 交叉验证泄露（序列相关 X + 重叠标签 Y → 跨折泄露）。是 design 评审清单现成骨架。<https://papers.ssrn.com/sol3/papers.cfm?abstract_id=3104816>
- **Meta-Labeling: Theory and Framework** — Joubert, JFDS 2022。把 meta-labeling 形式化为三组件（信息优势 / 假阳性建模 / 头寸 sizing）并做受控实验。**注意：作者来自商业方 Hudson & Thames，存在利益相关（见 §7）。** <https://papers.ssrn.com/sol3/papers.cfm?abstract_id=4032018>
- **Does Meta-Labeling Add to Signal Efficacy?** — Singh & Joubert（Hudson & Thames）2022。条件性有效的（弱）佐证：meta-labeling 大幅改善分类指标（均值回归案例 OOS 准确率 17%→63%），但对真实策略收益提升更温和，且需一级模型本身有 alpha——「算法差则只减少下行」。**注意（见 §7 高优先降权）：同案例 precision 仅 0.17→0.20，准确率跃升主要来自把大量样本判为负类（类别不平衡下 accuracy 极易虚高，与「改善精确率」叙事相反）；原文明确无法比较两策略收益/Sharpe/回撤（数据集来自完全不同时间段）；证据来自商业利益相关方自身、非独立第三方、非 RCT。应表述为弱证据。** <https://hudsonthames.org/does-meta-labeling-add-to-signal-efficacy-triple-barrier-method/>
- **The Probability of Backtest Overfitting (PBO via CSCV)** — Bailey, Borwein, López de Prado, Zhu 2014/2017。组合对称交叉验证估计回测过拟合概率；与 DSR 配合把「重复在同一数据上试错=科学造假」量化。<https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2326253>
- **The Deflated Sharpe Ratio** — Bailey & López de Prado 2014。在多重试验、非正态收益下校正 Sharpe 显著性；输入需「试验次数 N」。**注意（见 §7 降级表述）：DSR 修正的是「从 N 个里挑最好」带来的上偏，而非修复任何系统性低估；强烈依赖 N 与试验独立性的正确估计，真实因子搜索中 N 与试验相关性往往不可知或被低估，落地时易被操纵或失真。** <https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2460551>
- **Leakage and the Reproducibility Crisis in ML-based Science** — Kapoor & Narayanan, Patterns/Cell 2023（arXiv:2207.07048）。跨 17 学科 294 篇论文的泄露 taxonomy（8 类，含时序泄露、训练测试非独立、预处理/特征选择跨集泄露），提出 model info sheets；civil-war 预测复现案例显示纠错后复杂 ML 不优于数十年前的逻辑回归。**这是把「防泄露契约」升格为通用科学标准的权威外部背书（非金融圈，可信度高，已核实属实）。** <https://arxiv.org/abs/2207.07048>
- **…and the Cross-Section of Expected Returns** — Harvey, Liu, Zhu, RFS 2016。factor zoo 多重检验：新因子需 t>3.0 才算数，「多数金融经济学研究发现可能是假的」。把瓶颈从单点泄露提升到发表偏差/数据挖掘层面。<https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2249314>
- **Is There a Replication Crisis in Finance?** — Jensen, Kelly, Pedersen, JoF 2023。争议另一面：多数因子可复现、聚为 13 主题、93 国样本外有效、证据随因子数增多而增强、「复现危机被夸大」。与 Harvey 形成对立——**本产品应呈现两派立场而非单押一方**。<https://onlinelibrary.wiley.com/doi/full/10.1111/jofi.13249>
- **Do t-Statistic Hurdles Need to be Raised?** — Chen 2022（及 Chen & Zimmermann）。**研究漏列的更直接反方（见 §7）：Harvey 等给出的 t-hurdle 在发表偏误下属弱识别（weak identification）——未观测的「未发表失败结果」必须外推，导致 t-门槛标准误极宽、「几乎无法判断门槛该升还是该降」，且发表偏误调整后收益仅比样本内小约 12%。把 t>3.0 当可直接固化进 agent 的硬门槛，是把一个本身识别不牢的阈值当成定论。** <https://arxiv.org/pdf/2204.10275>
- **Clustered Feature Importance** — López de Prado 2020（见《ML for Asset Managers》）。MDI/MDA 在替代效应/共线下不可靠；先聚相似特征再簇级评估，对线性与非线性替代均稳健。直接关系到 agent 自动选因子的可信度。<https://papers.ssrn.com/sol3/papers.cfm?abstract_id=3517595>

## 4. 机构最佳实践 / 标准

- **模型风险管理监管指引（合规骨架的语言来源——但已过时，见 §7 高优先降权）** — 历史上常被引为骨架的 SR 11-7（Fed/OCC 2011）要求模型满足「概念健全性（设计/理论与公开研究一致、假设有据）+ 数据适用性与相关性 + 独立验证 + 模型清册/审批/持续监控」三支柱，可映射为 agent 自动产出的「特征/标签验证档案」骨架。**但 SR 11-7 已于 2026-04-17 被 SR 26-2《Revised Guidance on Model Risk Management》正式 supersede 并 replace（连同 SR 21-8），且 SR 26-2 明确把 generative/agentic AI 排除在范围外（carveout，要求沿用既有风险管理实践）——这直接冲击本产品「贯穿全程 Agent OS」的定位。且其适用对象是受监管银行（SR 26-2 重点针对总资产 >300 亿美元机构），并不直接适用单用户零售对话式产品。**当前最相关的反而是新指引把 agentic AI 划出范围这一治理空白。<https://www.federalreserve.gov/supervisionreg/srletters/SR2602.htm>
- **NIST AI RMF 1.0（2023）** — Map/Measure/Manage/Govern 四功能，强调数据来源/可追溯性、有效性与可靠性、文档化——为「防泄露契约 + provenance」提供通用治理语言，适合非银行机构与对话式产品的合规叙事。**比已被取代的银行监管文件更适合作本产品骨架。** <https://www.nist.gov/itl/ai-risk-management-framework>
- **点对点制度感知防泄露（A 股）** — 固化 T+1 买入/T+2 卖出时滞、停牌/ST/退市、涨跌停不可成交、point-in-time 财报对齐、survivorship-free 成分股；Qlib 以标签 `Ref($close,-2)/Ref($close,-1)-1` 实现该原则。<https://github.com/microsoft/qlib/blob/main/examples/benchmarks/README.md>
- **横截面因子预处理标准流水线（BARRA/USE 风格行业惯例）** — winsorize（常见 1%/99% 或 MAD）→ 截面 z-score 标准化 → 行业/市值中性化（对行业哑变量与 log 市值回归取残差）；零截面方差时 z=0 视为中性暴露。**所有统计量必须按 as-of 截面计算，严禁用未来截面。**

## 5. 对 QuantBT 这套架构的推荐方向（概念级）

> 仅给概念级方向，不点 file:line、不排实施计划。

1. **把「防泄露」做成机器可检查的一等公民——leakage contract。** 每个特征/标签强制声明 (a) as-of 决议时间、(b) 可见性/可成交窗口、(c) 所引用未来信息=0 的证明。agent 生成因子时填这张契约，系统在编译期/运行期校验时间对齐，任何「标签决议时间 < 某特征 as-of」即硬失败。把 AFML/Kapoor-Narayanan 的泄露条款从靠人自觉变成流水线护栏——直接服务「流程即信任」。
2. **默认强制 purged + embargo CV，CPCV 作可选而非默认更优。** 把「为什么不能用普通交叉验证」翻译成给经济学者看的一句话因果解释；随机 k-fold 在金融数据上应被产品级禁用或需显式越权。**清醒前提（见 §7）：CPCV「显著优于 walk-forward」的核心实证只在合成受控环境（Heston 等）得出，真实市场外部效度未验证；walk-forward 仍是贴近可成交现实的行业标准。CPCV 应标注「优势主要见于合成环境」而非当普适默认。**
3. **标签层提供「三选一向导」（triple-barrier / trend-scanning / 固定窗），按用户意图推荐。** 择时 vs 选股、趋势 vs 反转走不同分支，默认按波动率自适应设屏障；side/size 解耦（meta-labeling）做成可选的「信号过滤+下注」二级层，但**明确标注其为「条件性增益、非万能」**，避免对小白过度承诺（meta-labeling 正面证据来自商业利益相关方、非独立 RCT，见 §7）。
4. **特征平稳化默认提供 fractional differentiation，但不设为不可商量的默认值。** 在训练期搜最小充分 d（ADF 检验）、把「保留记忆 vs 平稳」的取舍可视化给用户，而非黑箱。**保留（见 §7）：fracdiff 相对收益率的下游增益常不显著、d 的滚动估计有自身前视风险——应作可选项并标注独立增益证据不足，而非默认凌驾收益率。**
5. **样本权重默认按 concurrency/uniqueness 计算并接入训练（可选 sequential bootstrap），把「非 IID」内建为缺省。** 严格区分「唯一性权重」与「收益权重」两个旋钮，防止二者混淆导致病态行为。
6. **把多重检验治理贯穿始终，但把「N 可数性」当 P0 风险而非工程小事。** 产出 PBO(CSCV) + Deflated Sharpe + IC/RankIC/ICIR/换手/半衰期 的统一「因子体检报告」，同时呈现 Harvey 与 Jensen（及 Chen-Zimmermann 弱识别）多派立场而非单押。**核心保留（见 §8）：一个会自适应、分支、复用中间结果的 LLM agent 产生的「有效试验数 N」在数学上几乎不可数（每次 prompt、每个被丢弃的中间因子都算试验），使 DSR/PBO/FDR 在 agentic 设定下可能根本无法诚实计算 N；t>3.0 本身弱识别，不可固化为硬门槛。**
7. **因子重要性默认用 clustered feature importance（先聚类再簇级评估），输出对小白可读的「因子族」解释而非裸特征排名。** 规避替代效应导致的「谁重要说不清」，呼应 aiquantclaw 因子族方法论。
8. **横截面预处理（winsorize→截面 z-score→行业/市值中性化）做成只在训练折拟合统计量、对测试折 transform 的可复用算子，杜绝预处理跨集泄露；制度约束固化进数据契约层。** A 股 T+1/T+2、停牌/涨跌停/ST/退市、PIT 财报、survivorship-free universe 作所有特征/标签的前置不可绕过条件。**并补可成交性建模（见 §8）：triple-barrier「屏障被触碰但当日涨跌停/停牌无法成交」必须建模，否则中低频扣费后因子虚高。**
9. **用 NIST AI RMF（而非已被取代的 SR 11-7）语言自动生成「特征验证档案」。** 概念健全性、数据适用性、可追溯性、持续监控作审计轨迹。**重定位（见 §7）：监管叙事须按 SR 26-2 重写——最新银行指引把 agentic AI 划出范围，本产品应改以 NIST AI RMF + 自建领域治理为骨架，而非外推银行监管条文到单用户零售产品。**

## 6. 架构级参考（少量伪代码 / schema 草图，非代码接线）

> 仅示意，不接线到现有代码。

**6.1 leakage contract / 特征 provenance schema 草图**

```yaml
feature_or_label:
  id: "mom_20d_zscore_industry_neutral"
  kind: feature | label
  provenance:
    as_of: "决议时间戳（该值在此刻方可见）"
    visibility_window: "输入数据的可见性窗口 [t0, t_asof]"
    tradable_window: "可成交窗口（A股 T+1买/T+2卖；停牌/涨跌停不可成交）"
    future_info_used: 0        # 必须可证明为 0，否则编译期硬失败
  label_resolution_rule:        # 仅 kind==label
    method: triple_barrier | trend_scanning | fixed_horizon
    barriers: {up: ..., down: ..., vertical: ...}   # 竖直屏障为 arbitrary 超参，须留痕
    resolution_time: "决议时间 ≥ 所有引用特征的 as_of"   # 否则=时序泄露
  preprocessing:                # 统计量只在训练折拟合
    winsorize: {pct: [0.01, 0.99], fit_on: train_fold_only}
    cross_section_zscore: {fit_on: train_fold_only}
    neutralize: {against: [industry_dummies, log_mktcap], fit_on: train_fold_only}
  institutional_constraints:    # 数据契约层前置不可绕过
    universe: survivorship_free
    point_in_time_fundamentals: true
    halt_st_delist_aware: true
  status: draft | locked        # locked 后改动触发重新声明 + 重算试验预算
```

**6.2 防泄露 CV 选择与「N 记账」伪代码（含可计算性诚实标注）**

```
# 1) 产品级禁用随机 k-fold；默认 purged+embargo，CPCV 标注"合成环境优势"
cv = PurgedKFold(embargo=embargo_len)        # 默认
# cv = CPCV(...)  # 可选；UI 须标注"显著优于 walk-forward 仅见于合成环境，外部效度未定"

# 2) 多重检验记账 —— 但在 agentic 自动造因子下 N 可能不可数（P0 风险）
trial_ledger.append(every_factor_tried)       # 含被丢弃的中间因子、每次 prompt 分支
N_effective = estimate_independent_trials(trial_ledger)   # 高度不确定，常被低估
# 警告：自适应/分支/复用中间结果的 LLM agent 使 N_effective 在数学上近乎不可数
#       => DSR/PBO 输入失真风险，须把"N 不可数"作为产品级显式风险披露，不可假装精确

dsr = deflated_sharpe(sr, N=N_effective, skew, kurt)   # 修正"从N个挑最好"的上偏，非修复低估
pbo = cscv_pbo(returns_matrix)
```

**6.3 因子体检报告（统一输出，含中低频扣费摩擦）**

```
report = {
  ic: {ic, rank_ic, icir, rank_icir},          # 时间稳定性
  quantile_returns: ...,
  turnover: ...,                                # RankIC 高 ≠ 可交易：必看换手
  alpha_decay_halflife: ...,                    # 中低频扣费后能否存活的决定项
  multiple_testing: {pbo, dsr, N_effective, N_caveat: "agentic下不可数"},
  positions_two_sided: {harvey_t_gt_3, jensen_replicable, chen_weak_identification},
  classification_metrics: {pr_auc, precision_at_k},  # 三屏障类别不平衡 => 别用 accuracy
  feature_importance: clustered_FI(...),        # 簇级，规避替代效应
  validation_dossier: nist_ai_rmf_skeleton(...),# 非 SR 11-7（已被取代/排除agentic）
}
```

## 7. 降权 / 争议 / 陷阱（对抗核查结论）

> 原样保留对抗核查的降权词（**过时/已被取代 / 适用范围外推过度 / 夸大 / 二手 / 利益相关 / 淡化关键限定 / 弱识别 / 不可外推 / 选择性呈现**）。

- **【high · 过时/已被取代 + 适用范围外推过度】用 SR 11-7（2011）作现行模型风险管理监管骨架。** SR 11-7 已于 **2026-04-17 被联储/OCC/FDIC 联合发布的 SR 26-2《Revised Guidance on Model Risk Management》正式 supersede 并 replace**（连同 SR 21-8），研究把已废止的 2011 年文件当成现行依据，属**过时论断**（今日为 2026-06）。更致命的是 SR 26-2 明确把 **generative 和 agentic AI 排除在本指引范围之外（carveout，要求机构沿用既有风险管理实践）**——这恰好正面冲击本产品「贯穿全程 Agent OS」的定位：最新监管指引把 agentic AI 划出了这套框架。此外 SR 11-7/SR 26-2 适用对象是受监管银行（SR 26-2 重点针对总资产 >300 亿美元的银行机构），并不直接适用于单用户零售对话式产品；把它当合规骨架是**适用范围的外推过度**。**修正动作：监管叙事须按 SR 26-2 重写，改以 NIST AI RMF + 自建领域治理为骨架。** <https://www.federalreserve.gov/supervisionreg/srletters/SR2602.htm>
- **【medium · 被淡化关键限定 + 二手/利益相关】meta-labeling 17%→63% 准确率作为正面「独立佐证」。** 数字本身在 H&T 原文可核实，但有两处被淡化的关键限定使该佐证价值大打折扣：(1) **同案例 precision 仅从 0.17 升到 0.20**——准确率的戏剧性跃升主要来自把大量样本判为负类（**类别不平衡下 accuracy 极易虚高，与「改善精确率」叙事相反**）；(2) 原文明确指出**无法比较两策略的收益/Sharpe/回撤**，因两数据集来自完全不同时间段（"we don't compare … because the two data sets are from very different time periods"），且缺 bet-sizing 组件。因此把 17%→63% 列为「独立佐证」本身就是**二手且利益相关**（H&T 自家、商业推广方）、且「独立性」存疑——它既非独立第三方也非 RCT。应表述为**弱证据**。 <https://hudsonthames.org/does-meta-labeling-add-to-signal-efficacy-triple-barrier-method/>
- **【medium · 外推过度】CPCV 显著优于 walk-forward、PBO/DSR 把过拟合量化。** 现有支持 CPCV「显著优于 walk-forward」的核心实证（ScienceDirect 2024 等）是在**合成受控环境（Heston 等模型生成数据）**中得出，并非真实市场数据的随机对照。真实交易仿真上 **walk-forward 仍是行业标准且更贴近可成交现实**。把 CPCV 当作普适更优而不标注「**优势主要见于合成环境、外部效度未定**」属外推过度。 <https://www.sciencedirect.com/science/article/abs/pii/S0950705124011110>
- **【medium · 弱识别 / 对单一数字的过度采信】Harvey-Liu-Zhu t>3.0 门槛固化进 agent。** 研究虽诚实呈现了 Jensen-Kelly-Pedersen 反方，但漏掉了更直接的方法论反驳：Chen & Zimmermann（及 Chen 2022《Do t-Statistic Hurdles Need to be Raised?》）指出 Harvey 等给出的 t-hurdle 在发表偏误下属**弱识别（weak identification）**——未观测到的「未发表失败结果」必须外推，导致 t-门槛的标准误**极宽**，「几乎无法判断门槛该升还是该降」，且其估计的发表偏误调整后收益仅比样本内小约 12%。把 t>3.0 当作可直接固化进 agent 的硬门槛，是**把一个本身识别不牢的阈值当成定论，属对单一数字的过度采信**。 <https://arxiv.org/pdf/2204.10275>
- **【low · 需降级表述 / 输入敏感性被低估】DSR 把「重复试错=科学造假」量化。** 方向正确但需降级：DSR 是在给定 N 与试验间相关结构（有效独立试验数，常靠聚类估计）假设下对 Sharpe 的「**标度/选择偏差修正**」，它修正的是「从 N 个里挑最好」带来的上偏，**而非修复任何系统性低估**；其结论强烈依赖 N 与试验独立性的正确估计，而真实因子搜索中 N 和试验相关性往往不可知或被低估，使 **DSR 在落地时易被操纵或失真**。研究把它描述为干净的「量化工具」，低估了其输入敏感性与假设脆弱性。
- **【low · 略有夸大】LdP/AFML 是该环节「事实标准 / institutional default」。** 研究已诚实标注「作者主导、缺独立大规模复现」，但仍以「事实标准/institutional default」定性，**略有夸大**：triple-barrier 的竖直屏障选择本质是**任意超参（arbitrary）**，fracdiff 的 d、purged+embargo 的 embargo 长度等都是**需调参的设计选择而非被独立验证的定律**；其「有效性证据多来自其著作 + 商业方 H&T + 碎片化博客」研究自己也承认。称其为成熟「事实标准」**高估了独立复现支撑**。
- **【low · 来源链接与论断不匹配的小错】Alphalens-reloaded「社区维护分支仍活跃」。** 结论（活跃维护）正确——stefan-jansen/alphalens-reloaded 2025-06 仍发版、2026 仍有 issue 活动；但研究为该条目挂的 URL 指向**已停更的 quantopian/alphalens 原始仓库**，而非实际活跃的 stefan-jansen/alphalens-reloaded，属**来源链接与论断不匹配的小错**（本文档 §2/§9 已更正为正确 URL）。 <https://github.com/stefan-jansen/alphalens-reloaded>

**通用陷阱清单（pitfalls）**

- **交叉验证泄露（AFML #8）**：标准 k-fold/随机切分在金融上必然泄露——序列相关特征 X_t≈X_{t+1} 且重叠标签 Y_t≈Y_{t+1}，把相邻样本分到不同折=把答案抄给测试集。必须 purged CV + embargo；agent 默认绝不能用 sklearn 原生随机 CV。
- **预处理/特征选择跨集泄露**（Kapoor-Narayanan 8 类之一）：winsorize 阈值、z-score 的 μ/σ、特征选择若在全样本（含测试期）上拟合就泄露。所有 fit 必须只用训练折再 transform 测试折——这点最易被「方便起见」破坏。
- **标签信息已含未来而不自知**：triple-barrier 竖直屏障 + 路径触碰天然向前看；若特征窗口与标签窗口时间重叠（label horizon 覆盖到特征 as-of 之后但被错误对齐）即构成时序泄露。须为每个标签声明其「决议时间」≥ 所有特征 as-of。
- **整数阶差分=系统性过度差分（#4）**：直接用收益率抹掉长记忆；但反向风险是 d 选太低导致非平稳。需对 d 做 ADF 检验下的最小充分差分，且 d 的选择只能在训练期估计。
- **把样本当 IID 加权（#7）**：标签重叠→等权训练等于把同一信息学多遍，in-sample 虚高、live 亏损。但混淆「唯一性权重」与「收益权重」又会导致预测崩溃或过度交易——两者须分开。
- **多重检验/数据挖掘（factor zoo）**：agent 自动批量造因子极易「撞出」伪 alpha；不记录试验次数 N 就无法算 DSR/PBO。须全程记账 N 并做 FDR/t 门槛——**但见 §8：agentic 设定下 N 近乎不可数。**
- **幸存者偏差与非 PIT 数据**：用当前成分股回溯、用修订后（restated）财报、忽略退市/停牌——会让因子凭空变好。属数据契约层，常被特征工程阶段默认忽略。
- **二手数字与利益相关来源**：meta-labeling 的正面证据大量来自其商业推广方（Hudson & Thames）与作者本人著作，缺独立 RCT 级复现；应表述为「条件性有效」而非已证实万能。
- **A 股制度时滞泄露**：用 T 日收盘价生成可在 T 日成交的标签是泄露（T+1 才能买、T+2 才能卖）；涨跌停/停牌日的「可成交」假设也会虚高。须把交易制度写进标签的可成交性约束。
- **RankIC 高 ≠ 可交易**：IC/RankIC 不计换手率与成本；高 IC 但高换手的因子在中低频扣费后可能为负。评估须同时看 alpha decay/半衰期与换手。
- **分类指标选择本身的误导**：三屏障标签天然类别不平衡，用 accuracy 评估极易误导（meta-labeling 案例 accuracy 17%→63% 而 precision 仅 0.17→0.20 即明证）；应看 PR-AUC / precision@k 而非裸 accuracy。

## 8. 开放问题

> 以下为对抗核查点出的、设计方向乐观一带而过的迁移鸿沟与盲区。

1. **监管时效与 agentic AI 碎片化。** 研究完全没意识到 SR 11-7 已被 SR 26-2（2026-04）取代、且新指引把 agentic/generative AI 划出范围。这不仅是引用过时，更意味着本产品「Agent OS 出验证档案对接监管语言」的合规叙事需重新定位——当前最相关的反而是新指引的「agentic AI 用既有实践治理」这一**空白**。用 NIST AI RMF 还是自建领域治理作骨架？
2. **三大算法的独立复现证据缺口未量化。** 研究指出 LdP 体系缺独立复现，但未给出任何**正面的独立第三方复现尝试（成功或失败）**的检索结果。对小白可信的产品，应明确告知用户 triple-barrier/meta-labeling/fracdiff 在公开文献里**几乎没有作者圈以外的严肃随机对照复现**——这是比「利益相关」更硬的证据缺口。是否应在产品里向用户披露这一点？
3. **成本/换手/容量与中低频落地的真实摩擦。** 虽提到 RankIC≠可交易，但未触及：triple-barrier 的事件驱动采样会**显著抬高换手**；meta-labeling 过滤后**样本量骤减导致二级模型本身过拟合**；A 股 T+1/涨跌停下「屏障被触碰但当日无法成交」的**可成交性建模**。这些才是中低频扣费后因子能否活下来的决定性摩擦，设计方向里只点到为止。
4. **fractional differentiation 在实践中的争议。** 研究把 fracdiff 当默认优选，但漏掉两点反方：(a) 实证上 fracdiff 特征相对简单收益率/对数差分，**对下游预测增益常常很小甚至不显著**（多为作者圈外质疑）；(b) d 的在线/滚动估计会引入**自身的前视风险与不稳定**，FFD 固定宽度实现也有窗口截断偏差。把它设为不可商量的默认值缺乏独立增益证据。
5. **「agent 自动批量造因子」与多重检验的内在矛盾未正视（P0）。** 产品设想 agent 大规模生成因子，但 PBO/DSR/FDR 都要求准确的试验次数 N 与试验独立性；一个会自适应、分支、复用中间结果的 LLM agent 产生的「**有效试验数 N 在数学上几乎不可数**」（每次 prompt、每个被丢弃的中间因子都算试验）。这使整套多重检验治理在 agentic 设定下**可能根本无法诚实计算 N**——研究把记账 N 当成可解决的工程问题，**低估了其在 agent 自动搜索下的根本性困难**。建议作为新的 P0 风险单列。
6. **triple-barrier 标签的类别不平衡与评估指标陷阱。** meta-labeling 案例里 accuracy 17%→63% 而 precision 仅 0.17→0.20 暴露了普遍问题——三屏障标签天然类别不平衡，用 accuracy 评估极易误导。是否把「分类指标选择本身的误导」（应看 PR-AUC/precision@k）固化进体检报告默认值？
7. **与本仓库既有 CSCV/PBO 实现的衔接缺口。** MEMORY 显示项目已落地 CSCV/PBO（aiquantclaw 方法论、数据平台 v2）。本研究作为纯外部前沿调研，**完全没有对照本仓库已有什么、缺什么**，无法告诉决策者哪些是「重复造轮子」、哪些是真缺口——对一个「拒绝半成品、要可上线」的产品这是关键落地角度，须在进入实施前补一次代码现状盘点。

## 9. 参考文献（URL）

- Advances in Financial Machine Learning（AFML, López de Prado 2018）：<https://www.wiley.com/en-us/Advances+in+Financial+Machine+Learning-p-9781119482086>
- The 10 Reasons Most Machine Learning Funds Fail：<https://papers.ssrn.com/sol3/papers.cfm?abstract_id=3104816>
- Meta-Labeling: Theory and Framework（Joubert, JFDS 2022）：<https://papers.ssrn.com/sol3/papers.cfm?abstract_id=4032018>
- Does Meta-Labeling Add to Signal Efficacy?（H&T 2022；见 §7 弱证据降权）：<https://hudsonthames.org/does-meta-labeling-add-to-signal-efficacy-triple-barrier-method/>
- The Probability of Backtest Overfitting (PBO via CSCV)：<https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2326253>
- The Deflated Sharpe Ratio：<https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2460551>
- Leakage and the Reproducibility Crisis in ML-based Science（Kapoor & Narayanan）：<https://arxiv.org/abs/2207.07048>
- …and the Cross-Section of Expected Returns（Harvey, Liu, Zhu）：<https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2249314>
- Is There a Replication Crisis in Finance?（Jensen, Kelly, Pedersen, JoF 2023）：<https://onlinelibrary.wiley.com/doi/full/10.1111/jofi.13249>
- Do t-Statistic Hurdles Need to be Raised?（Chen 2022；弱识别反方，见 §7）：<https://arxiv.org/pdf/2204.10275>
- Clustered Feature Importance（López de Prado 2020）：<https://papers.ssrn.com/sol3/papers.cfm?abstract_id=3517595>
- SR 26-2 Revised Guidance on Model Risk Management（2026-04，取代 SR 11-7；见 §7 高优先降权）：<https://www.federalreserve.gov/supervisionreg/srletters/SR2602.htm>
- NIST AI RMF 1.0（2023）：<https://www.nist.gov/itl/ai-risk-management-framework>
- CPCV vs walk-forward 实证（合成环境，ScienceDirect 2024；见 §7 外推过度）：<https://www.sciencedirect.com/science/article/abs/pii/S0950705124011110>
- Microsoft Qlib（Alpha158/360 + PIT 数据层 + 制度感知标签）：<https://github.com/microsoft/qlib> ｜ 标签约定 README：<https://github.com/microsoft/qlib/blob/main/examples/benchmarks/README.md>
- Alphalens-reloaded（活跃维护分支，更正自原 quantopian/alphalens）：<https://github.com/stefan-jansen/alphalens-reloaded>
- MlFinLab（已转商业/闭源许可）：<https://github.com/hudson-and-thames/mlfinlab> ｜ MIT 开源替代 mlfinpy：<https://github.com/baobach/mlfinpy>（许可说明 <https://mlfinpy.readthedocs.io/>）
- H&T meta-labeling 研究代码库：<https://github.com/hudson-and-thames/meta-labeling>
- ML for Trading（Stefan Jansen）配套库：<https://github.com/stefan-jansen/machine-learning-for-trading>
- fracdiff（高性能分数阶差分库）：<https://github.com/fracdiff/fracdiff>
- timeseriescv（PurgedKFold/CPCV）：<https://github.com/sam31415/timeseriescv>
