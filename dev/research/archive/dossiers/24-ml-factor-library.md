# 24 · ML 因子库（横截面机器学习）

> 机构级 Agent OS 成品环节深挖 · 全程 Opus 4.8 · 对抗式核查已降权 · 重心=前沿研究+概念级推荐 · 不含 file:line 代码接线
> 簇 E

## 1. 一句话定位

本环节回答一个看似「再加一个模型」、实则决定「库是否纯净、信号是否可复现、小白是否被噪声骗」的问题：**当一个 ML 模型对截面预期收益给出预测时，怎样把它当成「一个原子因子/信号」纳入因子库——而不是在库里就把它和别的信号揉成超级因子？** 核心立场是 **「ML 因子是信号生产者，库保持纯净」**：库里每个 ML 因子只存「单一原子信号（每个 ID×日期一个分数）+ 它的完整出身证书（模型权重快照哈希 / 训练数据切片 + PIT 时点 / 特征清单 / 标签定义 / 依赖库版本哈希）」，绝不在库内做组合——组合（多 ML 输出、ML+传统因子）一律推迟到下游组合环节。方法学骨架来自 Gu-Kelly-Xiu (2020, RFS)：树与神经网络因捕捉**非线性交互**最优、价值加权多空十分位样本外年化 Sharpe **1.35**、所有方法收敛到**动量/流动性/波动率族**；三大硬约束是 (1) R²_oos 用「不去均值的超额收益平方和」作分母（个股历史均值噪声极大，用它当基准会人为降门槛），(2) 严格时间顺序 train/val/test + 逐年向前滚动重估、绝不打乱时间，(3) 变量重要性=「置零某变量后面板预测 R² 的下降量」、且作者明确声明解释目标是「modest」。但本项目的诚实立场是：**统计显著 ≠ 可交易、可持续的经济收益**——可复现性危机（HXZ vs JKP/Chen-Zimmermann）尚未定论、发表后/拥挤衰减真实存在（McLean-Pontiff）、版本耦合让 ML 因子比公式因子脆得多，这些必须用流程（DSR/PBO + walk-forward + PIT 红线 + 衰减告警 + IPCA 对照锚）对冲，而非靠单边乐观假设写死进产品。

## 2. 前沿 SOTA 与代表系统

| 系统 / 范式 | 角色 | 要点 | URL |
|---|---|---|---|
| **Gu-Kelly-Xiu 经验资产定价 ML 范式** | 本环节奠基石 | ~900 预测变量、CRSP 全样本上比较 OLS/惩罚线性/PCR-PLS/RF/GBRT/NN：树与 NN 最优，增益源于非线性交互；价值加权多空十分位样本外年化 Sharpe **1.35**（约线性基准两倍，等权口径更高至 2.45——本研究审慎取 1.35）；所有方法收敛到动量/流动性/波动率族。三大方法学硬约束（见 §1）。**注**：1.35 是 **gross、未扣交易成本**，ML 因子普遍高换手，净 Sharpe 可能被吃光（见 §7）。 | https://academic.oup.com/rfs/article/33/5/2223/5758276 |
| **JKP Global Factor Data（Bryan Kelly Lab / AQR）** | 最权威可复现因子基准库 | 153 个特征/因子、聚为 13 个主题、覆盖 93 国，统一口径构建长短组合。可作本产品因子库的**对照锚 + 冷启动种子**——任何 ML 因子先与之对照，看是否只是已知主题换皮。代码见 ReplicationCrisis 仓库。 | https://jkpfactors.com/ |
| **Open Source Asset Pricing（Chen & Zimmermann）** | 「ML 因子是否旧异象换皮」的基准面板 | 复现学术界横截面信号：仓库 README 表述为 "about 300 or so signals"，论文层面 319 个 characteristics 中约 161 个原文显著、其中 98% 复现 t>1.96。提供个股层信号 + 多种组合实现，Python/R 包可直接拉取。 | https://www.openassetpricing.com/ |
| **Microsoft Qlib** | 「Agent 出全部工程」最贴近的 ML 因子流水线骨架 | 面向 AI 的开源量化平台：高性能 point-in-time 时序数据库 + 表达式引擎（加速因子计算）+ 数据→特征→训练→回测→评估→上线全工作流。 | https://github.com/microsoft/qlib |
| **Alphalens** | ML 因子入库前的标准化体检套件 | 因子绩效分析标准工具：IC、分层收益、换手、衰减（decay）分析。统一「原子因子」的评估口径。**注**：Quantopian 已倒闭，仓库为社区维护、活跃度低，集成前需核实当前维护状态。 | https://github.com/quantopian/alphalens |
| **bkelly-lab/ipca（Instrumented PCA）** | ML 黑箱因子的「有经济结构、可解释」对照锚 | IPCA(Kelly-Pruitt-Su) 把观测特征映射为时变因子暴露或异象截距，提供有经济结构的条件因子模型。当 ML 因子的增益其实只是已知特征的线性/低阶组合时，IPCA 能暴露它「无新增量」。 | https://github.com/bkelly-lab/ipca |

## 3. 关键论文（每条带 URL）

- **Empirical Asset Pricing via Machine Learning**（Gu, Kelly & Xiu, 2020, *RFS* 33:2223-2273）——本环节奠基石。~900 预测变量上比较多种 ML，树与 NN 最优、增益源于非线性交互；多空十分位样本外年化 Sharpe **1.35**（约线性基准两倍）；所有方法收敛到动量/流动性/波动率族。三大方法学硬约束：R²_oos 用**不去均值的超额收益平方和**作分母；严格时间顺序 train/val/test + 逐年滚动重估；变量重要性=置零某变量后面板 R² 下降量，且作者明确声明解释目标是「modest」。**注**：1.35 是 gross 口径，未扣成本/换手。
  https://academic.oup.com/rfs/article/33/5/2223/5758276

- **Asset Pricing and Machine Learning: A Critical Review**（Bagnara, 2024, *Journal of Economic Surveys* 38(1):27-56）——系统性批判综述，把 ML 资产定价分为正则化/降维/树-随机森林/神经网络/比较分析五类。核心警告：ML 灵活性带来高预测精度但**强烈偏离传统计量经济学**，需特别小心可解释性、过拟合与经济解释；低信噪比下 return 预测尤其危险。
  https://onlinelibrary.wiley.com/doi/10.1111/joes.12532

- **Replicating Anomalies**（Hou, Xue & Zhang, 2020, *RFS*）——统一口径复现近 200 个因子：**65% 过不了 t>1.96；加多重检验校正（t>2.78）后 82% 失败**。主张多数异象不达当代实证标准、因子动物园主要由 p-hacking 驱动。**注**：t>2.78 处方本身有已发表的「弱识别」反驳（见 §7）。
  https://www.nber.org/papers/w23394

- **Is There a Replication Crisis in Finance?**（Jensen, Kelly & Pedersen, 2023, *Journal of Finance* 78(5):2465-2518）——HXZ 的反方。用层级贝叶斯因子复现模型 + 93 国数据，主张多数因子**可复现、可聚成 13 主题、样本外成立**，且因子数量多反而**强化**（而非削弱）证据。**这是与 HXZ 对立的活跃争议，本产品不应预设任何一方为定论。**
  https://onlinelibrary.wiley.com/doi/full/10.1111/jofi.13249

- **Does Academic Research Destroy Stock Return Predictability?**（McLean & Pontiff, 2016, *Journal of Finance*）——异象组合收益**发表后衰减**：精确值为样本外低 **26%**、发表后低 **58%**（发表后增量约 32%；样本外衰减≈数据挖掘偏误，发表后进一步衰减≈投资者学习/套利）。对「让小白产出 ML 因子」是头号外推风险：统计显著 ≠ 可持续可交易 alpha。**注**：本研究早前以「约 50%」概括，属对 58% 的二手取整，应还原为 26%/58% 双口径（见 §7）。
  https://onlinelibrary.wiley.com/doi/10.1111/jofi.12365

- **The 10 Reasons Most Machine Learning Funds Fail**（López de Prado, 2018, *JPM* 44(6)）——列出 ML 量化十大病灶：用回测做研究（research-through-backtesting）、链式/时点交叉验证泄露、固定时窗标注、用回测调参致 PBO 等。解药：Purged/Combinatorial Purged CV、Deflated Sharpe Ratio、用特征重要性（MDA/MDI/聚类）而非回测来筛信号。
  https://papers.ssrn.com/sol3/papers.cfm?abstract_id=3104816

- **The Deflated Sharpe Ratio**（Bailey & López de Prado, 2014）——在多重检验下校正**选择偏误 + 非正态 + 样本长度**，给出「考虑了试了多少策略后」噪声产生 ≥ 观测 Sharpe 的概率。配套 PBO/CPCV。**注**：DSR 是针对「选择偏误」这一项的概率/标度修正，**不**修复 Sharpe 对最大回撤、尾部崩盘、收益时序顺序的不敏感——不是全面过拟合/风险体检（见 §7）。
  https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2460551

- **Instrumented Principal Component Analysis / Characteristics are Covariances**（Kelly, Pruitt & Su, 2019, *JFE*）——用观测特征作为时变因子暴露的工具，把大量特征映射为 latent 因子暴露或异象截距，提供有经济结构、可解释的条件因子模型。是 ML 黑箱因子的原则性、可解释替代/对照锚。
  https://www.sciencedirect.com/science/article/abs/pii/S0304405X19301151

- **Open Source Cross-Sectional Asset Pricing**（Chen & Zimmermann, 2022, *Critical Finance Review*）——复现 319 个信号，161 个原文显著信号中 98% 复现 t>1.96，复现 t 对原始 t 回归斜率 0.88、R² 82%——为「可复现性危机」提供**偏乐观**实证，与 HXZ 对照。提供开放数据。
  https://www.openassetpricing.com/

- **Do t-Statistic Hurdles Need to be Raised?**（Andrew Chen, *Management Science*，已发表）——【对抗核查补引的釜底抽薪反方】用 10 种模型论证：在发表偏误下被拒结果不可观测，**提高 t 门槛是「弱识别」（weakly identified）——既无法证明该升、也无法证明该降**。讽刺的是 Chen 正是 Open Source Asset Pricing 的作者。这条直接削弱「t>2.78 硬约束」的稳固性（见 §7）。
  https://pubsonline.informs.org/doi/10.1287/mnsc.2023.03083

## 4. 机构最佳实践 / 标准

- **模型风险管理（Fed/OCC SR 11-7，2011）**：任何用于决策的「model」须有开发-实施-使用、**独立验证**、治理三道防线，并采用基于风险的验证频率（高风险/复杂/重大模型通常年度再验证，低风险靠持续监控+文档化复审）。ML 因子库应据此为每个 ML 因子建模型卡 + 独立验证记录 + 再验证节奏。**重要降权**：SR 11-7 是 2011 年文件，**原文从未点名 machine learning 或 AI**；「涵盖 ML」是靠其宽泛的 model 定义 + 监管/咨询业事后解释性外推，**非原始指引明文**（见 §7）。
  https://www.federalreserve.gov/supervisionreg/srletters/sr1107.htm

- **NIST AI 风险管理框架（AI RMF 1.0，Govern/Map/Measure/Manage）**：非金融专用的顶层治理骨架，适合「流程即信任」产品里 ML 因子可信度（可解释性、稳健性、漂移监控）的四功能映射。
  https://www.nist.gov/itl/ai-risk-management-framework

- **CFA Institute「AI 偏差的好坏丑」伦理与尽调框架**：数据偏差、survivorship、look-ahead、模型不透明是投资 AI 的核心风险，要求可解释与可问责——对面向非技术用户的 Agent OS 尤为相关。
  https://www.cfainstitute.org/insights/articles/good-bad-and-ugly-of-bias-in-ai

- **Point-in-time / 数据 vintage 管理（机构标配）**：用「按引用日期还原当时可见数据」的快照存储，处理财报新闻稿→正式归档→重述（restatement）的时间差与幸存者偏差，避免 ML 因子被未来信息污染。这是 ML 因子最高优先级的准入红线。
  https://perspectives.refinitiv.com/future-of-investing-trading/how-to-use-point-in-time-data-to-avoid-bias-in-backtesting/

## 5. 对 QuantBT 这套架构的推荐方向（概念级）

> 概念级方向，不点 file:line、不排实施计划。

1. **库只存原子信号、绝不在库内组合**：每个 ML 因子在库里只存单一信号（ID×日期一个分数），组合（多 ML 输出 / ML+传统因子）推迟到下游组合环节。这既保持库纯净，也让每个 ML 信号可被**独立体检、独立淘汰**。把「在库内揉超级因子」列为硬禁止——一旦揉就失去对单一信号的独立审计能力。

2. **每个 ML 因子发「出身证书/模型卡」并整体版本化**：模型权重快照哈希 + 训练数据切片（起止 + PIT 快照 ID）+ 特征清单 + 标签定义 + 依赖库版本哈希，**全部钉死**。ML 因子的数值是这一整套的函数——**版本耦合是它区别于公式因子的根本特征**，不钉死就不可复现。可直接复用项目 v3 已有的模型卡 / .pkl / .pt 版本化与 backtest_bridge（predict_with→top-N 权重 shift1→净值）。

3. **「严格无泄露的时间感知评估」设为 Agent 默认强制流程、而非可选项**：expanding/rolling walk-forward 重估、用不去均值超额收益平方和作 R²_oos 分母（GKX 口径），并默认产出 Deflated Sharpe Ratio 与 PBO。这与项目 v3 OOS 桥（跨数据集/时间后段/train_fraction walk-forward）天然对齐，可作入库门槛。**但**：Purged/Combinatorial Purged CV 的优越性主要来自合成受控环境，外推到真实非平稳市场缺同等证据——CPCV 应作为「更强统计默认」呈现，**不可宣传为「总是优于 walk-forward」**（见 §7）；walk-forward 仍是部署现实性的标准。

4. **「发表后/拥挤衰减」与「非平稳 regime 漂移」升格为一等公民告警**：对每个 ML 因子持续跑滚动 IC/衰减曲线与 regime 条件表现，设漂移阈值触发「建议复审/退役」。对让非技术用户产出策略的产品，这是把 McLean-Pontiff 衰减（26%/58% 双口径）变成流程护栏的关键，呼应「流程即信任」。**缺口诚实标注**：目前缺少可信的**拥挤度量方法论**（唯一沾边的近期 crowding 论文已撤稿，见 §7），衰减/漂移阈值若拍脑袋会失真——需要可计算的判据（滚动 IC 衰减的统计显著性、PSI/特征分布漂移、CUSUM、与 regime 标签的条件回归），「设个阈值」不是落地方案。

5. **可解释性走双轨且诚实标注边界**：用 GKX 式「变量置零后 R² 下降」做模型级重要性、用 SHAP/MDA 做特征级归因——但在面向小白的对话里明确声明这些是**关联性内省、非因果，且对相关特征会失真**。把「主导信号是否仍是动量/流动性/波动率族」作合理性自检；偏离已知经济直觉的 ML 因子让经济学者用户介入判断（人出经济判断，Agent 出工程）。

6. **给 ML 黑箱因子配有经济结构的对照锚（IPCA/条件因子模型）**：当 ML 因子的预测增益其实只是已知特征的线性/低阶组合时，对照锚暴露它「无新增量」，帮助库剔除换皮异象，也给非技术用户一个可理解的经济解释面。同时用 JKP（13 主题）/ Chen-Zimmermann（约 300 信号）作基准面板，检验 ML 因子是否只是旧异象换皮。

7. **治理层套 SR 11-7/NIST AI RMF 的轻量化骨架，但诚实点破「伪独立」张力**：每个 ML 因子带开发记录 + 独立验证 + 基于风险的再验证节奏；高风险（高换手/高杠杆/实盘加密）因子更频繁再验证。**但**：SR 11-7 的独立验证要求**验证方独立于开发方**；让同一个 Agent 既当开发者又扮「独立验证者」在治理意义上**并非真正的第二道防线（self-validation）**——这恰是机构合规最不接受的安排。应诚实标注为「伪独立」，或在高风险因子上要求**人类/异模型介入**做真独立验证（见 §7、§8）。

8. **严守 PIT 与泄露防线作为入库红线**：特征工程一律 PIT；处理财报新闻稿→归档→重述时间差与幸存者偏差；Agent 入库前自动做泄露体检（未来信息检测、训练/验证时间重叠检测、标签构造泄露检测）。**特别强调标签层**：forward-return 窗口、去极值/标准化是否用了未来信息、行业/市值中性化的时点，都是高频泄露源，应作为独立体检项（López de Prado triple-barrier/meta-labeling 的「固定时窗标注危害」不应一笔带过）。一个被泄露污染的 ML 因子在小白手里会产生灾难性虚假信心。

9. **A股 / 加密特化作为一等设计变量、不可直接搬美股结论**：所有引用资产（GKX/HXZ/Chen-Zimmermann/IPCA/Qlib 默认）都是美股横截面。**A股**有涨跌停板、T+1、停牌复牌、ST 制度、散户主导、强政策市 regime、行业轮动剧烈，且数据 vintage / 披露规则（中国会计准则、业绩预告/快报/正式报）不同于美股新闻稿→归档→重述链；**加密**则 7×24 无收盘、无财报基本面、币种生命周期短（上市/退市/分叉）、幸存者偏差极端、交易所数据质量参差。「资产无关」的库设计必须为加密**明确标签定义（用什么作 forward return）、universe 构建（如何处理几千个垃圾币）与 PIT**，为 A股明确停牌/涨跌停如何进入 PIT 与泄露判定。这是产品落地的头号内容缺口（见 §8）。

10. **纸面 Sharpe ≠ 净 Sharpe：成本/换手/容量约束内建**：GKX 的 1.35 是 gross、价值加权十分位多空、未扣交易成本；ML 因子普遍**高换手**（预测信号每期重排），实盘净 alpha 可能被吃光。任何 ML 因子入库体检都应默认附「换手率 + 估算交易成本后净 Sharpe + 容量衰减」一栏，避免小白拿到纸面 Sharpe 当可交易收益（见 §7）。

## 6. 架构级参考（少量伪代码 / schema 草图，非代码接线）

> 示意，非接线到现有代码。

**ML 因子「出身证书 / 模型卡」（schema 草图，整体版本化、PIT 钉死）：**

```yaml
ml_factor_card:
  factor_id: ...
  signal: atomic                      # 库内只存单一原子信号（ID×日期一个分数），禁止库内组合
  provenance:                         # 版本耦合 = ML 因子的根本特征，全部钉死
    model_weights_hash: ...           # 模型权重快照哈希（.pkl / .pt）
    train_slice: {start, end, pit_snapshot_id}   # 训练数据切片 + PIT 快照 ID
    feature_list: [...]               # 特征清单
    label_def: ...                    # 标签定义（forward-return 窗口 / triple-barrier ...）
    deps_version_hash: ...            # 依赖库版本哈希（数值随库版本漂移）
  asset_class: <a_share | crypto>     # 资产特化：日历/停牌/涨跌停 vs 7x24/无基本面
  reproducible: true                  # 上述任一漂移 → 历史值不可复算
```

**入库前的强制无泄露评估 + 过拟合 + 衰减体检（schema 草图）：**

```yaml
ml_factor_admission:
  walk_forward:                       # 与 v3 OOS 桥对齐（跨数据集/时间后段/train_fraction）
    mode: rolling                     # expanding | rolling，严格只用过去训练
    r2_oos_denominator: excess_return_sum_sq   # GKX 口径：不去均值超额收益平方和
  overfitting:
    deflated_sharpe: 0.xx             # 针对「选择偏误」这一项的标度修正——非全面风险体检
    pbo: 0.xx                         # 回测过拟合概率
    n_trials: T                       # 累计试过的模型/特征/CV 配置（含对验证方法的元过拟合）
  cpcv:                               # 「更强统计默认」，标注合成环境局限，禁宣传为总是更优
    enabled: <true|false>
  leakage_audit:                      # PIT 红线 + 标签层泄露独立项
    feature_engineering_pit: <checked>
    label_uses_future: <checked>      # forward-return 窗口 / 去极值 / 中性化时点
    train_val_time_overlap: <checked>
    survivorship: <checked>
  cost_capacity:                      # 纸面 != 净：ML 因子高换手，gross Sharpe 会被吃光
    turnover: 0.xx
    net_sharpe_after_cost: 0.xx
    capacity_decay: ...
  decay_monitor:                      # McLean-Pontiff 26%/58% → 一等告警
    rolling_ic_curve: [...]
    regime_conditional_perf: {...}
    drift_threshold_trigger: <suggest_review | retire>
  benchmark_anchor:                   # 是否只是旧异象换皮 / 已知特征低阶组合
    jkp_theme_overlap: ...            # 对照 JKP 13 主题
    ipca_residual_gain: ...           # IPCA 条件因子模型残差增量
  independent_validation:
    validator: <agent_self | human | cross_model>
    # 警示：agent_self = 伪独立，非 SR 11-7 第二道防线；高风险因子要求 human/cross_model
```

## 7. 降权 / 争议 / 陷阱（对抗核查结论）

> 以下限定词（夸大/时代错置/选择性引用/不可外推/二手取整/伪独立/撤稿/活跃争议 等）**原样保留**；凡涉「明确涵盖/硬约束/真实显著性/约 50%」等强确定性或不精确措辞均已按对抗核查降级。任何对用户的承诺或文案，必须采用降级后的表述。

- **【medium · 夸大 / 时代错置】「SR 11-7『明确将算法与机器学习应用纳入模型定义』/『明确涵盖 AI/ML』」**——夸大、时代错置。SR 11-7 是 **2011 年 4 月**发布的，**原文从未点名 machine learning 或 AI**（2011 年 ML 在金融业尚未主流化）。把 ML 纳入是靠其宽泛的「model」定义 + 监管机构事后的解释性外推（GARP/咨询业 2024-2026 的二次叙述），**而非原始指引的明文**。写成「明确涵盖」属于把后期行业解读回填进原文，误导读者以为有现成合规明文可援引。准确表述：**SR 11-7 的宽 model 定义在原则上可涵盖 ML，但需结合后续监管解释，原文无 AI/ML 明文**。
  https://www.federalreserve.gov/supervisionreg/srletters/sr1107.htm

- **【medium · 选择性引用 / 回避已发表反驳】「把 HXZ『提高 t 门槛到 2.78』当作机构级硬约束/共识」**——选择性引用、回避已发表的直接反驳。Andrew Chen《Do t-Statistic Hurdles Need to be Raised?》(*Management Science*，已发表) 用 10 种模型证明：在发表偏误下被拒结果不可观测，提高 t 门槛是「**弱识别**」（weakly identified）——既无法证明该升、也无法证明该降。讽刺的是这位 Chen 正是本研究力荐的开源资产（Open Source Asset Pricing）作者。研究在「争议未定论」里提了 HXZ vs JKP 的分裂，**却漏掉了针对 t-hurdle 本身「不可识别」这一更釜底抽薪的反方**，使「t>2.78 硬约束」显得比实际更稳固。
  https://pubsonline.informs.org/doi/10.1287/mnsc.2023.03083

- **【medium · 外推过度 / 不可外推】「把 Purged/Combinatorial Purged CV(CPCV) 设为 Agent 对每个 ML 因子的『默认强制流程/入库门槛』」**——外推过度。CPCV 相对 walk-forward 的显著优势，主要实证来自 2024《Backtest overfitting in the machine learning era》在「**合成受控环境（synthetic controlled environment）**」里的比较——即数据生成过程已知、信噪可控的人造环境。在真实非平稳市场上 CPCV 优于 walk-forward **缺乏同等强度证据**，且业界仍以 walk-forward 作为真实交易模拟的标准。把一个「合成环境里被验证」的方法升格为**强制**入库门槛，继承了其外部效度局限——应标注此边界，定位为「更强统计默认」而非铁律。
  https://www.sciencedirect.com/science/article/abs/pii/S0950705124011110

- **【low · 措辞夸大 DSR 功能】「Deflated Sharpe Ratio 被描述为 ML 因子入库前必跑的『过拟合体检』『真实显著性』」**——措辞夸大 DSR 的功能。DSR 校正的是「多重检验下的选择偏误 + 非正态 + 样本长度」——本质是对「试了多少次」做标度/概率修正（给出 noise 产生 ≥ 观测 SR 的概率）。它**不**修复 Sharpe 比率本身的系统性缺陷：对最大回撤/尾部崩盘风险不敏感、对收益时序顺序不敏感。把它说成「真实显著性」体检会让小白以为过了 DSR 就安全，而它对 regime 切换处的尾部脆断毫无防护。准确表述：**DSR 是针对「选择偏误」这一项的标度修正，非全面过拟合或风险体检**。

- **【low · 二手取整】「McLean-Pontiff『异象 alpha 发表后约衰减 50%』」**——二手化的近似数字。原文精确值是**样本外低 26%、发表后低 58%**（发表后增量约 32%）。「约 50%」是对 58% 的粗略口径，偏低且模糊；当成单一「50%」记忆点反复使用会在产品默认告警阈值里固化一个不精确的数字。方向正确但数值应**还原为 26%/58% 双口径**，避免二手取整。
  https://onlinelibrary.wiley.com/doi/10.1111/jofi.12365

- **【low · 轻微夸大可用规模 / 口径混用】「Open Source Asset Pricing『复现 319 个信号』作为可直接拉取的因子库基准」**——轻微夸大可用规模。仓库 README 实际表述为「**about 300 or so signals**」；319 是论文层面研究的 characteristics 总数（其中约 161 个原文显著、98% 复现 t>1.96）。把 319 当成现成可拉取的「信号面板」规模略有拔高，实际可直接用的组合数与论文统计口径不完全等同。属小幅口径混用，不影响主结论。
  https://www.openassetpricing.com/

- **【参照 · confirmed】核心数字几乎全部经一手核实无误、不降级**：GKX 价值加权多空十分位样本外年化 Sharpe=**1.35**（且研究审慎地选了 1.35 而非更亮眼的等权 2.45）、HXZ **65%/82%** 失败率、Chen-Zimmermann 161 个显著信号中 **98%** 复现 t>1.96、JKP **153 特征/13 主题/93 国**、IPCA 与 Bagnara 的题名卷期、López de Prado JPM 2018 venue——均与权威源一致。研究在「可复现性危机」上做到了**双边呈现**（HXZ vs JKP/Chen-Zimmermann）并明确标注「未定论」，且**正确地未引用已撤稿的 arXiv 2512.11913 拥挤论文**——这点值得肯定。

**通用陷阱清单（工程红线）：**

- **把「统计显著」误当「可交易 alpha」**：低信噪比 + 多重检验下，绝大多数 ML 因子的样本内表现是过拟合假象。HXZ 口径下加多重检验校正后 82% 因子失败；不跑 DSR/PBO 就入库等于把噪声当信号。
- **回测过拟合（PBO）与「用回测做研究」**：反复用同一回测调 ML 超参/选特征，会系统性挑出样本外为负（非零）的策略（López de Prado）。链式/时点交叉验证泄露是最隐蔽的杀手。
- **版本耦合不可复现**：ML 因子数值同时依赖模型权重快照 + 训练切片 + 特征工程 + 库版本，任一漂移都让历史信号无法复算。不整体版本化 + PIT 钉死，因子库的历史值就是不可信的。
- **非平稳/regime 漂移**：昨天有效的 ML 因子今天可能反向，且 ML 比线性因子更容易在 regime 切换处脆断；静态入库、不持续监控衰减 = 慢性失效。**且**：目前缺可信的拥挤度量方法论（唯一沾边的近期论文已撤稿），漂移/衰减阈值需可计算判据，不能拍脑袋。
- **发表后/拥挤衰减（McLean-Pontiff 26%/58%）**：面向大众的 Agent OS 若把已知异象包装成「新 ML 因子」，用户实际拿到的是已被套利侵蚀的残值；必须显式告警而非沉默。
- **point-in-time / look-ahead 泄露**：财报新闻稿→正式归档→重述的时间差、幸存者偏差、特征/标签里混入未来信息——任何一处泄露都制造虚假 ML 因子，在非技术用户手里尤其危险。**标签层（forward-return 窗口/去极值/中性化时点）是高频泄露源，需独立体检**。
- **可解释性陷阱**：SHAP/特征重要性是**关联性、非因果**，且对相关特征归因失真；GKX 自己强调解释目标是 modest。把 SHAP 排名当经济因果讲给小白会制造错误信心。
- **在库内做组合污染纯净性**：若把多个 ML 输出或 ML+传统因子在库内揉成一个「超级因子」，就失去对单一信号的独立体检与淘汰能力，违背「库保持纯净、原子因子」原则。
- **可复现性争议未定论**：HXZ（危机）与 JKP/Chen-Zimmermann（无危机）结论相反且都活跃；任何把单边结论写死进产品默认假设（无论乐观或悲观）都是**过度外推**，应让证据与用户经济判断共同决定。
- **「Agent 自验证」是伪独立**：让同一 Agent 既开发又扮独立验证者，**不构成 SR 11-7 的第二道防线**；高风险因子应要求人类/异模型介入做真独立验证。
- **纸面 Sharpe ≠ 净 Sharpe**：GKX 1.35 是 gross；ML 因子高换手，扣成本后净 alpha 可能被吃光——入库体检必须含换手/成本/容量栏。
- **美股结论不可直接搬到 A股/加密**：涨跌停/T+1/ST/披露规则（A股）与无基本面/极端幸存者偏差/币种短生命周期（加密）使多数引用结论失真——需资产特化的标签/universe/PIT。

## 8. 开放问题

- **加密横截面 ML 因子几乎无文献支撑也无开源基准**：所有引用资产都是股票横截面。加密 7×24 无收盘、无财报基本面、币种生命周期短（上市/退市/分叉）、幸存者偏差极端、交易所数据质量参差——「资产无关」的库需明确加密因子的**标签定义（用什么作 forward return）、universe 构建（如何处理几千个垃圾币）与 PIT**，这些综述只字未提。这是产品 GOAL（加密到 Binance 实盘）的关键空白。
- **A股特化的 PIT 与泄露判定如何精确落地**：涨跌停（成交但价格被钉死）、T+1、长期停牌、ST 制度、业绩预告/快报/正式报的 vintage 链如何进入 PIT 与泄露体检，待具体机制。
- **缺可用的拥挤度量方法论**：产品要把「拥挤衰减」做成一等告警，却没有可信的拥挤度量（唯一沾边的近期论文已撤稿），只能停在 McLean-Pontiff（样本截至更早）；漂移/衰减阈值的可计算判据（滚动 IC 显著性、PSI、CUSUM、regime 条件回归）待确定。
- **「小白靠对话产出策略」与 SR 11-7 三道防线的根本张力**：让同一 Agent 既开发又扮独立验证者是 self-validation、伪独立——是否在高风险因子上强制人类/异模型介入？治理层用机构光环镀金前须明确其对单用户项目无强制力。
- **CPCV × 模型重训成本的乘积效应**：每条路径都要重训，DL 模型（v3 训练平台 .pt）下重训次数 = C(N,k)，CPCV 的「统计默认」地位可能因成本站不住——是否对 DL 因子默认退化为 walk-forward + 少数折？
- **IPCA 对照锚的资产无关性**：IPCA 在 A股/加密上的特征工具有效性、与中低频中性化口径的兼容性，是否需重新标定？
- **标签构造（triple-barrier/meta-labeling）在横截面 ML 因子上的适配**：López de Prado 的标签方法多为时序单标的，移植到截面 forward-return 排序信号时的泄露与去极值时点处理待展开。

## 9. 参考文献（URL）

- Gu, Kelly & Xiu (2020), *RFS* 33:2223-2273（奠基石，Sharpe 1.35 为 gross）：https://academic.oup.com/rfs/article/33/5/2223/5758276
- Bagnara (2024), *Journal of Economic Surveys* 38(1):27-56（批判综述）：https://onlinelibrary.wiley.com/doi/10.1111/joes.12532 ；SSRN 3950568：https://papers.ssrn.com/sol3/papers.cfm?abstract_id=3950568
- Hou, Xue & Zhang (2020), *RFS*《Replicating Anomalies》（65%/82% 失败）：https://www.nber.org/papers/w23394
- Jensen, Kelly & Pedersen (2023), *JoF*《Is There a Replication Crisis in Finance?》（HXZ 反方，活跃争议）：https://onlinelibrary.wiley.com/doi/full/10.1111/jofi.13249
- McLean & Pontiff (2016), *JoF*（发表后衰减 26%/58% 双口径）：https://onlinelibrary.wiley.com/doi/10.1111/jofi.12365
- López de Prado (2018), *JPM* 44(6)《The 10 Reasons Most ML Funds Fail》：https://papers.ssrn.com/sol3/papers.cfm?abstract_id=3104816
- Bailey & López de Prado (2014)《The Deflated Sharpe Ratio》（针对选择偏误的标度修正，非全面风险体检）：https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2460551
- Kelly, Pruitt & Su (2019), *JFE*《Characteristics are Covariances / IPCA》：https://www.sciencedirect.com/science/article/abs/pii/S0304405X19301151
- Chen & Zimmermann (2022), *CFR*《Open Source Cross-Sectional Asset Pricing》（约 300 信号，偏乐观）：https://www.openassetpricing.com/
- Andrew Chen《Do t-Statistic Hurdles Need to be Raised?》(*Management Science*，t-hurdle 弱识别反方)：https://pubsonline.informs.org/doi/10.1287/mnsc.2023.03083
- JKP Global Factor Data（153 特征/13 主题/93 国）：https://jkpfactors.com/ ；代码 ReplicationCrisis：https://github.com/bkelly-lab/ReplicationCrisis
- Open Source Asset Pricing 仓库（CrossSection）：https://github.com/OpenSourceAP/CrossSection
- Microsoft Qlib（PIT 时序库 + ML 工作流）：https://github.com/microsoft/qlib
- Alphalens（因子绩效体检，社区维护，需核实维护状态）：https://github.com/quantopian/alphalens
- bkelly-lab/ipca（IPCA 官方实现，对照锚）：https://github.com/bkelly-lab/ipca
- SHAP（事后特征归因，关联性非因果、对相关特征失真）：https://github.com/shap/shap
- Backtest overfitting in the ML era（CPCV 优势限于合成环境，不可外推）：https://www.sciencedirect.com/science/article/abs/pii/S0950705124011110
- SR 11-7（Fed/OCC 模型风险管理，原文无 AI/ML 明文）：https://www.federalreserve.gov/supervisionreg/srletters/sr1107.htm
- NIST AI RMF 1.0：https://www.nist.gov/itl/ai-risk-management-framework
- CFA Institute《The Good, Bad and Ugly of Bias in AI》：https://www.cfainstitute.org/insights/articles/good-bad-and-ugly-of-bias-in-ai
- Refinitiv/LSEG: point-in-time data to avoid bias in backtesting：https://perspectives.refinitiv.com/future-of-investing-trading/how-to-use-point-in-time-data-to-avoid-bias-in-backtesting/
- 【已撤稿登记 · 无污染】arXiv 2512.11913《Not All Factors Crowd Equally》——作者于 2025-12-27 撤稿（v2 withdrawn），本研究未引用，处理正确：https://arxiv.org/abs/2512.11913
