# 05 · 可证伪假设卡 + 预注册 + 反 HARKing

> 机构级 Agent OS 成品环节深挖 · 全程 Opus 4.8 · 对抗式核查已降权 · 重心=前沿研究+概念级推荐 · 不含 file:line 代码接线
> 簇 A

## 1. 一句话定位

把"在看最终数据前，把一个可证伪的策略假设连同其证伪条件、停机规则与试验计数冻结成一张只读、带时间戳、内容哈希的卡"，作为任何策略触碰最终 OOS 之前的**结构性门禁**——其制度蓝本是元科学的预注册/registered reports，统计后端是量化金融的多重检验校正（Deflated Sharpe / PBO），但所有自动门槛都必须降级为**可调、需人工判断、带信心标注的启发式**，而非伪装成统计学确定性的硬闸门。

## 2. 前沿 SOTA 与代表系统

环节 05 在三条脉络上互证：元科学的预注册基础设施、量化金融的过拟合/多重检验工具、以及因果优先的尽调框架。

- **OSF Registries / OSF Preregistration（Center for Open Science）** — 事实标准的预注册基础设施：把研究计划存为带时间戳、只读、不可变的注册快照；提供多种模板（AsPredicted / Prereg / RR）、活动日志（谁/何时/改了什么）、可程序化访问的 OSF API。直接对应"假设卡冻结 = 时间戳 + 只读快照 + 审计轨迹"。<https://www.cos.io/products/osf-registries>
- **Registered Reports（COS 倡议，Stage-1/Stage-2 + In-Principle-Acceptance）** — 在看结果前对"问题+设计+分析计划"做同行评审并给出原则性接受；结果是否显著不影响发表。已被 300+ 期刊采纳（注：研究发现原稿写"200+"为偏保守的二手数字，方向是低估，不损害论点）。可作为 Agent OS"假设卡需通过门禁评审才能进入回测"的制度蓝本。<https://www.cos.io/initiatives/registered-reports>
- **AsPredicted（9 问预注册模板）** — 极简 9 问：数据是否已采、主假设、关键因变量（如何度量）、条件、确切分析、异常值/剔除规则、样本量（即 stop rule）、其它。最贴近"一张可证伪假设卡"的最小字段集，适合非技术用户对话式填写。<https://aspredicted.org>
- **AEA RCT Registry / 经济学 PAP 实践（J-PAL, World Bank DIME）** — 经济学预注册登记处 + PAP 模板（McKenzie/Ganimian checklist）。核心实践：PAP 与最终论文分离、用"populated PAP"逐条对照、明确标注 confirmatory vs exploratory、偏离需文档化。是资产无关、面向观察性/准实验数据的最贴近参考。<https://www.povertyactionlab.org/resource/pre-analysis-plans>
- **Deflated Sharpe Ratio / PBO（Bailey & López de Prado 工具族）** — 把"试验次数 N、偏度、峰度、样本长度"纳入显著性门槛，量化选择偏倚下的过拟合概率（PBO）与最小回测长度。**注意：是标度修正而非万能门禁**（见第 7 节降权）。<https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2460551>
- **DoWhy / DAGitty / causal-learn（PC, LiNGAM, GES）+ DVC** — 因果图构建/可识别性检验（do-calculus、backdoor/frontdoor/IV）与 refutation 测试的开源栈，配合 DVC 做数据/计划的不可变版本化。**注意：因果发现在观察性金融时序上的可靠性高度存疑**（见第 7 节降权）。<https://www.pywhy.org/dowhy/>

辅助工具栈：

- **OSF API / OSF Registrations** — 程序化创建只读、时间戳化、不可变的注册快照与活动日志，可作为"假设卡冻结"的外部可信时间戳锚点或设计范本。<https://developer.osf.io/>
- **DVC（Data Version Control）+ Git** — 把"冻结的假设卡 + 锁定的 OOS 数据切片 + 试验计数 N"绑定为单一可审计提交。<https://dvc.org/>
- **mlfinlab / 《Advances in Financial ML》配套实现** — Purged/Combinatorial-Purged K-Fold CV、Deflated Sharpe、PBO、最小回测长度的开源实现。<https://github.com/hudson-and-thames/mlfinlab>
- **specr / multiverse（R）** — specification curve / multiverse analysis：系统化枚举"所有合理设定"并展示结果分布（Simonsohn/Gelman 的 garden of forking paths），可在卡里把"被探索过的设定空间"显式化以反向估计 N。<https://github.com/masurp/specr>
- **Apéritif（预注册→分析代码脚手架，CHI 2022）** — 把结构化预注册自动生成分析代码与方法描述的研究原型，对"对话式假设卡 → 机器可读确认性分析"这一产品形态有直接启发。<https://dl.acm.org/doi/fullHtml/10.1145/3491102.3517707>

## 3. 关键论文（每条带 URL）

- **HARKing: Hypothesizing After the Results are Known（Kerr, 1998）** — 提出 HARKing 定义：把事后假设伪装成事先假设。指出文献中大量"被先验假设预测"的效应实为多重未校正探索性检验/p-hacking 的产物，因而更难复现。这正是假设卡要在"触碰数据前冻结假设"所要阻断的核心病理。*Personality and Social Psychology Review, 1998。* <https://journals.sagepub.com/doi/abs/10.1207/s15327957pspr0203_4>
- **The Preregistration Revolution（Nosek, Ebersole, DeHaven, Mellor, 2018, PNAS）** — 系统论证 prediction(confirmatory) vs postdiction(exploratory) 的区分为何决定假阳性率：同一数据既生成又检验假设会失去对 Type-1 错误的控制。预注册建立时间戳证据让他人透明评估检验严格度（severity），但不应禁止探索。*PNAS 115(11):2600-2606。* <https://www.pnas.org/doi/10.1073/pnas.1708274114>
- **Do Pre-registration and Pre-analysis Plans Reduce p-Hacking and Publication Bias?（Brodeur, Cook, Hartley, Heyes, 2024）** — 分析 15,992 个经济学 RCT 检验统计量。**重要限定（见第 7 节）：该文主分析结论是"预注册与非预注册研究的检验统计量分布没有有意义差异"，即预注册整体几乎无效；"只有带完整 PAP 才显著降 p-hacking"是作者列为 suggestions for improvement 的二级/条件性发现，非稳健主结果，不宜作产品门禁的硬背书。** *Journal of Political Economy Microeconomics, 2024（IZA DP 15476 / SSRN 4180594）。* <https://papers.ssrn.com/sol3/papers.cfm?abstract_id=4180594> · <https://www.journals.uchicago.edu/doi/10.1086/730455>
- **Promises and Perils of Pre-Analysis Plans（Olken, 2015, JEP）** — 给出 PAP 可含字段（变量、清洗、回归设定、多重推断校正、子组）与收益（大幅减少 data-mining），但坦诚成本：经济学论文要解释"机制"而非仅治疗效应，完整事先指定近乎不可能；后加分析应明确标为 exploratory。支持"卡分确认/探索两层 + 偏离机制"。*JEP 29(3):61-80。* <https://dspace.mit.edu/handle/1721.1/104069>
- **…and the Cross-Section of Expected Returns（Harvey, Liu, Zhu, 2016, RFS）** — 已发表 316 个"预测股票收益"的因子；在该规模数据挖掘下，t>2.0 常规门槛失效，新因子需 t>3.0。**重要限定（见第 7 节）：t>3.0 与"多数因子为假"在金融计量界存在实质争议，被 Chen-Zimmermann(2020) / Chen(2022) 直接挑战，学界无共识，应作可调护栏而非经典定论。** *RFS 29(1):5-68。* <https://academic.oup.com/rfs/article-abstract/29/1/5/1843824>
- **The Deflated Sharpe Ratio（Bailey & López de Prado, 2014）+ The Probability of Backtest Overfitting（Bailey, Borwein, López de Prado, Zhu, 2014）** — 选择偏倚下反复试验会系统性夸大最大 Sharpe，即使所有候选都是纯噪声；DSR 按试验数/偏度/峰度/样本长度修正显著性，PBO 估计"选中过拟合策略"的概率随试验数迅速上升。*SSRN 2460551 / 2326253；JPM；Notices of the AMS。* <https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2460551>
- **All that Glitters Is Not Gold（Wiecki, Campbell, Lent, Stauth — Quantopian, 2016）** — 888 个真实算法策略实测。**重要限定（见第 7 节）：R²<0.025 仅是线性、单变量用回测 Sharpe 预测 OOS 的结果；同文指出高阶矩/对冲等组合构造特征有显著预测力，非线性 ML 多特征可把 OOS 预测 R² 提升到 0.17。"回测几乎无 OOS 预测力"是断章取义。** *SSRN 2745220。* <https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2745220>
- **Causal Factor Investing / Causality and Factor Investing: A Primer（López de Prado；+Zoonekynd, Lipton — CFA Research Foundation, 2023–2025）** — 提出"factor mirage"：一个 p-hacking-free 且统计"有效"的模型仍可能因 confounder/collider 误设而虚假；多数因子文献只做关联声明而不识别因果图。给出 5 步因果尽调清单（变量选择→因果发现→因果调整→因果解释/预测力→因果组合）。*Cambridge Univ. Press (Elements)；CFA Institute Research Foundation Brief；SSRN 4205613 / 4774522。* <https://rpc.cfainstitute.org/sites/default/files/docs/research-reports/rf_lopezdeprado_causalityprimer_online.pdf>
- **Methods Matter: p-Hacking and Publication Bias in Causal Analysis in Economics（Brodeur, Cook, Heyes, 2020, AER）** — 对 25 家顶刊 21,000+ 检验做 caliper/randomization 检验，发现 p-hacking/发表偏倚程度按方法差异巨大（IV、其次 DID 最严重）。**重要限定（见第 7 节）：被 comment 实质部分推翻——Kranz-Pütz 修正舍入误差后 DID 证据消失、IV 仍在；引用时应整体降级为"部分结论(IV)成立、部分(DID)被推翻"。** *AER 110(11):3634-3660（+ Comment/Reply）。* <https://www.aeaweb.org/articles?id=10.1257/aer.20190687>
- **Preregistration does not improve the transparent evaluation of severity… when deviations are allowed（van Dongen et al., 2024, arXiv）** — 批评/边界：从 Popper 严格检验视角，允许"基于样本的有效性增强型偏离"会以未知方式抬高 Type-1 错误率；含糊预注册 + 事后偏离会侵蚀预注册核心价值。提醒"偏离必须受限且全记录，否则冻结形同虚设"。*arXiv:2408.12347。* <https://arxiv.org/pdf/2408.12347>

## 4. 机构最佳实践 / 标准

- **SR 11-7（美联储/OCC 模型风险管理）** — 验证三支柱：(1) 概念稳健性（评估理论、方法、假设是否适配用途，明确要求审查支撑变量选择的经验证据，而非只看历史拟合）；(2) 结果分析（在未用于开发的样本上做 backtesting）；(3) 持续监控（性能恶化触发加速复核）；且验证须由**独立于开发团队者**执行。映射：假设卡的 economic_mechanism = 概念稳健性留痕；stop_rule = 持续监控触发器；冻结 OOS = 结果分析的样本独立性。**注意：第 7 节将质疑"同一 LLM 既生成又复核"是否满足 SR 11-7 的组织独立性。** <https://www.federalreserve.gov/supervisionreg/srletters/sr1107.htm>
- **NIST AI RMF 的 MAP 函数** — 要求记录每个 AI 系统的预期用途、用户、利益相关者、假设、约束、收益与已知风险，并识别所有假设与依赖；GOVERN 贯穿全程提供治理与审计。映射：假设卡即 MAP 阶段的"意图/假设/约束"结构化留痕，Agent OS 的流程门禁即 GOVERN。*NIST AI 100-1, 2023。* <https://www.nist.gov/itl/ai-risk-management-framework>
- **AEA RCT Registry + J-PAL/World Bank DIME 的 PAP 工作流** — 看数据前公开登记带时间戳的 PAP；用 populated PAP 逐条对照实际分析；明确分确认性/探索性；偏离需文档化（何时/何地/为何）并仅在指定里程碑发布新版本。映射：假设卡的版本化、偏离日志、两层标注。<https://www.socialscienceregistry.org/>
- **Critical Finance Review 的批判性复现倡议（Ivo Welch, 2019）** — 把"独立的怀疑性复现/重做"确立为金融实证常规；区分 reproduction（同数据同码）与 replication（同方法异数据）。映射：假设卡通过后，Agent 可在异数据/异时段自动做 replication 作为反 HARKing 二次防线。<https://cfr.ivo-welch.info/>
- **RFS / PBFJ 在金融领域试点 registered reports** — **注意（见第 7 节降权）：研究发现原稿"已制度化采纳"为夸大。RFS 的 registered reports 实为 2017–2019 一次性 FinTech 特刊征文竞赛，并非常设通用投稿通道；金融观察性数据使 RR 极难常规落地。这削弱而非支撑"门禁评审可作金融蓝本"的强论点。** <https://academic.oup.com/rfs/article-abstract/32/5/1647/5427782>

## 5. 对 QuantBT 这套架构的推荐方向（概念级）

> 以下均为概念级方向，不点 file:line、不排实施计划。所有自动门槛在落地时均应降级为可调、需人工判断、带信心标注的启发式。

1. **假设卡=强制门禁产物，而非可选文档。** 在 Agent OS 中，任何策略进入"触碰最终 OOS"阶段前，必须存在一张已冻结（只读 + 时间戳 + 内容哈希）的假设卡。这对应 registered reports 的 in-principle-acceptance，是反 HARKing 的结构性闸门，而非事后自律。

2. **卡的字段要"可证伪到统计层"而非文字层——但不夸大其确定性。** Brodeur 等(2024) 的方向性提示与 Lakens 的批评都指向"含糊预注册等于没注册"。因此 economic_mechanism / falsification_condition / stop_rule 应尽量落到可机器执行的判据（具体指标、阈值、样本/时段、决策规则），理想形态是"卡 == 可运行的确认性分析脚本的声明式前身"。**但须注意：Brodeur 主结果是"预注册整体几乎无效"，因此本方向只能作为"PAP 优于裸时间戳"的方向性主张，不能宣称为统计学硬证据。**

3. **显式区分 confirmatory vs exploratory 两层，把探索结果降级而非禁止。** 借 Nosek/Olken/Lakens 的分层（主假设/次假设/探索）。允许小白自由探索市场数据，但任何探索出的新关系若想升级为"可下注的确认性结论"，必须重新开一张冻结卡，并在"未被探索污染的数据"上检验——把 HARKing 从"诱惑"变成"流程上不可能"。

4. **economic_mechanism 走因果优先、内建反驳测试——但承认因果发现在金融上不成熟。** 吸收 López de Prado 的 factor mirage 与 CFA 5 步清单：引导用户先回答"为什么应该有效（因果故事/混杂与对撞担忧）"并转成可检验声明（占位因果图 + 至少一个"若 X 则该效应应消失/反号"的反驳条件）。**但 PC/LiNGAM/GES 等因果发现算法在观察性金融时序上不可靠（见第 7 节）；应把因果字段定位为"引导用户写出可证伪的经济故事 + 人工审阅"，而非自动跑因果发现算法生成"机器可检验因果图"。**

5. **把"试验计数 N"作为一等状态贯穿生命周期，但承认 N 不可观测。** 自动累计该假设（及其家族）被回测/调参的次数，触碰 OOS 时按 Deflated Sharpe/PBO 与 Harvey-Liu 的精神动态抬高门槛。**关键诚实边界（见第 7 节）：有效独立试验数 N 极难估计（高度相关的变体其有效 N 远小于配置数），跨会话/跨用户/跨家族几乎无法统一计数；DSR 纠正的是"夸大"而非"低估"。因此 N 计数应作为"提示风险的软信号 + 人工判断输入"，而非自动统计门禁。**

6. **为"偏离"设计受限且强制留痕的通道，而非允许/禁止两极。** van Dongen(2024) 与实证显示"未披露偏离"会抽空预注册价值，而 Olken 指出完全不许偏离不现实。设计应：偏离必须在触碰 OOS 前提交、带"何时/何地/为何 + 对检验严格度的影响评估"、并自动把该结论从 confirmatory 降级标记——让透明成本低于偷改成本。

7. **面向观察性市场数据调适预注册形态。** 金融多为档案/观察性数据（RFS 公认障碍），没有"数据采集前"这一自然冻结点。替代锚点应是"冻结一段从未被该假设触碰过的最终 OOS 切片（时间后段/跨资产/跨市场）"，由系统强制隔离与一次性消费。**注意（见第 8 节开放问题）：CPCV 防泄露的优越性证据仅来自合成环境，A 股 regime 断裂使冻结 OOS 格外脆弱，且"一次性消费 OOS"与实盘持续再训练根本冲突——这三项须单列适用性评估，不可直接照搬元科学一次性实验范式。**

8. **用 SR 11-7 / NIST AI RMF 的语言包装信任叙事，但不假装组织独立性。** 假设卡 = 概念稳健性留痕（SR 11-7）与 MAP 阶段的意图/假设/约束（NIST）；stop_rule = 持续监控触发器。**关键诚实边界（见第 7 节）：同一 LLM 既帮用户生成假设又当复核者，不满足 SR 11-7 的组织独立性要求（独立性是制度安排，不是角色扮演）。应明确承认"Agent 复核 ≠ 组织独立验证"，把它定位为"一致性/规范检查"而非合规级独立验证。**

9. **诚实呈现局限，避免把预注册当银弹。** 在产品话术里明确：预注册不保证正确、只保证可被严格评估（severity）；探索仍有价值但需独立复现；把 Critical Finance Review 式的"异数据/异时段自动复现"作为冻结之外的第二道反 HARKing 防线。

## 6. 架构级参考（少量伪代码 / schema 草图，非代码接线）

> 以下为示意草图，用于沟通概念形状，**不接线到现有代码**。

可证伪假设卡（最小可证伪字段集，融合 AsPredicted 9 问 + PAP + 因果优先 + 多重检验）：

```yaml
# hypothesis_card.schema (示意)
HypothesisCard:
  card_id: uuid
  status: enum[draft, frozen, deviated, retired]   # frozen 后只读
  layer: enum[confirmatory, secondary, exploratory] # 反 HARKing 分层
  frozen_at: timestamp                              # 冻结时间戳锚点
  content_hash: sha256                              # 内容不可变指纹
  parent_card_id: uuid?                             # 探索→确认升级时指向源卡

  # —— 因果优先：可证伪的经济故事，不强制自动因果发现 ——
  economic_mechanism:
    causal_story: text                              # 为什么应该有效
    confounder_concerns: [text]                     # 混杂/对撞担忧
    refutation_condition: text                      # "若 X 则该效应应消失/反号"（人工审阅）

  # —— 主假设与度量（AsPredicted 风格）——
  primary_hypothesis: text
  outcome_metric: { name, how_measured, sample, time_window }
  exact_analysis: text                              # 确切分析规范
  outlier_rule: text                                # 异常值/剔除规则

  # —— 停机规则 + 多重检验（软护栏，带信心标注）——
  stop_rule:
    metric_threshold: { metric, value, confidence_note } # 非硬常数
  multiplicity:
    trial_count_N: int                              # 软信号，非自动门禁
    N_estimation_note: "有效独立 N 不可观测；此为下界提示"
    significance_floor: { rule: "DSR/PBO 精神", adjustable: true }

  # —— 受限偏离日志（强制留痕，自动降级）——
  deviations:
    - { when, where, why, severity_impact, auto_downgrade: true }

  # —— 冻结的最终 OOS 切片（数据访问层一次性消费）——
  frozen_oos:
    slice_ref: dvc_hash
    consumed: bool                                  # 触碰即标记，禁止二次
```

门禁伪逻辑（结构性闸门，但门槛可调 + 需人工判断）：

```
def can_touch_final_oos(card):
    assert card.status == "frozen"            # 必须已冻结(只读+哈希+时间戳)
    assert card.layer == "confirmatory"       # 探索层不得直接触碰最终 OOS
    assert card.economic_mechanism.refutation_condition is not None
    assert not card.frozen_oos.consumed       # 一次性消费

    # 软护栏：不自动 pass/fail，而是产出风险提示 + 要求人工裁决
    warnings = []
    if card.multiplicity.trial_count_N > soft_threshold:
        warnings.append("N 偏高，DSR/PBO 精神下显著性门槛应抬高（人工判断）")
    # Agent 复核 = 一致性/规范检查，NOT 组织独立验证（不假装满足 SR 11-7）
    return GateDecision(allow=True, warnings=warnings, needs_human_review=True)
```

## 7. 降权 / 争议 / 陷阱（对抗核查结论）

> 本节原样保留对抗核查的降权词（夸大/断章取义/争议/二手/不可外推/外推过度等限定）。

**降权项（来自对抗核查）：**

- **[medium] Brodeur(2024)"只有带 PAP 才有效"被选择性强化。** 核实属实但**被过度承重**：该论文**主分析(primary specification)结论是"预注册与非预注册研究的检验统计量分布没有有意义差异"**——即预注册整体无效。"带 PAP 才有效"是作者本人列为 suggestions for improvement 的**二级/条件性发现**，非稳健主结果。把一个**观察性、二级**的子样本对比当成"直接证明假设卡必须可执行到统计层"的因果背书，属对单篇论文的过度承重。它支持"PAP 比裸时间戳好"这个方向性主张，但不足以作为产品门禁设计的硬证据。

- **[medium] Quantopian R²<0.025 属断章取义。** R²<0.025 仅是**线性、单变量**用回测 Sharpe 预测 OOS 的结果。同文明确指出：高阶矩（波动率、最大回撤）、对冲等组合构造特征有显著预测力，非线性 ML 分类器在多特征上可把 OOS 预测 R² 提升到 **0.17**。因此"回测几乎无 OOS 预测力"是**错误概括**——真正结论是"单看 Sharpe 没用，但回测的其他维度有用"。这反而削弱了"OOS 是唯一可信信号"的叙事。

- **[medium] Harvey-Liu-Zhu t>3.0 被当经典依据属外推过度。** HLZ 的 t>3.0 结论在金融计量界存在**实质争议**。Chen(2022, "Do t-stat Hurdles Need to be Raised?")论证 t-hurdle 在发表偏误下**弱识别/不可识别**；Chen-Zimmermann(2020, RAPS)用 156 个复现发现发表偏误调整后收益仅缩小 **12.3%**，推断**多数因子是真的**，与 HLZ"多数发现为假"**直接对立**，学界无共识。把一个被顶级期刊正面挑战的结论当"经典依据"，属**外推过度**；t>3.0 应作可调护栏而非绝对真理。

- **[medium] DSR / PBO 被当"可计算硬护栏"夸大其适用性。** DSR 是**标度修正(scaling correction)**，前提是你**知道有效独立试验数 N**。但 N 本身**极难估计**：高度相关的策略变体（如 10 窗口×5 阈值×3 逻辑=150 配置）其有效独立 N 可能远小于 150，连 López de Prado 本人都要用聚类近似。把"记录 N"说成可计算护栏，**回避了"N 不可观测/跨会话跨用户跨家族几乎无法统一计数"这一核心工程难题**。DSR 纠正的是选择偏倚下的"夸大"，不是系统性"低估"——把它当万能统计门禁是**夸大其适用性**。

- **[medium] DoWhy + causal-learn(PC/LiNGAM/GES) 因果发现属外推过度。** PC/LiNGAM/GES 对**观察性金融时间序列**的可靠性**高度存疑**：非平稳、强自相关、隐藏混杂、样本量相对维度不足，会产出不稳定、对超参敏感的因果图。López de Prado 的 Causal Factor Investing 本身也承认因果发现需大量领域知识介入、且主要在"变量已隔离"后才用。把"对话式引导小白填因果图→机器可检验"当可落地的一等字段，**远超当前因果发现在金融上的成熟度**。

- **[low] RFS/PBFJ 试点 registered reports 属二手且夸大制度化程度。** RFS 的 registered reports 实为 **2017–2019 一次性 FinTech 特刊征文竞赛(special issue)**，并非常设通用 registered-reports 投稿通道；检索未能确认其作为常规轨道在持续运行。把"金融顶刊已制度化采纳 RR"作蓝本，**高估了**金融实证界对该格式的接受度——恰恰相反，观察性数据使 RR 在金融极难落地。

- **[medium] CPCV 优于 walk-forward 属外推过度（证据仅来自合成环境）。** 支持"CPCV 显著优于 walk-forward（更低 PBO、更高 DSR）"的证据主要来自 Arian-Norouzi-Seco(2024) 的**合成受控环境(synthetic controlled environment)**——在真实市场数据上 CPCV 是否仍优于 walk-forward **并未确立**。CPCV 的组合切分会产生大量重叠/相关的训练-测试对，在真实非平稳市场可能**高估稳健性**。不可直接外推为部署级建议。

- **[low] Brodeur "Methods Matter"(2020) 应整体降级。** 已诚实标注 comment/reply 争议值得肯定，但核实确认：舍入误差修正后 **DID 的 p-hacking 证据消失**，Brodeur 等 2022 reply 承认 DID 在 5% 水平的聚集变小。凡引用该文"方法差异巨大"时应整体降级为**"部分结论(IV)成立、部分(DID)被推翻"**，而非稳健机构背书。

- **[low] "registered reports 已被 200+ 期刊采纳"为偏保守二手数字。** 实际 COS 官方为 **300+ 期刊**，方向是**低估而非夸大**，不损害论点；仅作准确性更正记录，说明二手数字未必都往有利方向取整。

**争议/撤稿登记（disputes & retractions）：**

- Brodeur(2020 AER) DID p-hacking 结论：**被 comment 实质（部分）推翻**。Kranz-Pütz 修正舍入后 DID 证据消失，仅 IV 仍存。AER 2022, 112(9):3137-39。<https://www.aeaweb.org/articles?id=10.1257/aer.20210121>
- HLZ "多数因子为假 / t>3.0"：**被直接争议**，Chen-Zimmermann(2020 RAPS) 调整后收益仅缩小 12.3%，与 HLZ 对立，学界无共识。<https://arxiv.org/pdf/2204.10275>
- CPCV 优于 walk-forward：**证据局限于合成环境**，真实市场未确立，不可外推为部署级建议。<https://papers.ssrn.com/sol3/papers.cfm?abstract_id=4686376>
- RFS "采纳/试点 RR 作常设格式"：**夸大制度化**，实为 2017–2019 一次性特刊。<https://academic.oup.com/rfs/article-abstract/32/5/1647/5427782>
- Brodeur(2024) "只有带 PAP 才有效"：**核实属实但为二级/条件性发现**，主分析结论是"预注册整体无有意义差异"；观察性证据，非因果，不宜作产品门禁硬背书。<https://www.journals.uchicago.edu/doi/10.1086/730455>

**陷阱（pitfalls）：**

- 预注册≠不可 p-hack：仅做时间戳而字段空泛等于装样子。
- 含糊与未披露偏离是头号杀手；允许"基于样本的有效性增强型偏离"会以未知方式抬高 Type-1 错误。
- 观察性数据没有天然冻结点；不在数据访问层强制隔离最终 OOS，"冻结"只是名义。
- 过度刚性会扼杀正当机制探索；卡过死用户会绕过或造假，需保留被明确降级的探索通道。
- "因果尽调"本身可被表演化（specification / garden-of-forking-paths）；因果字段需配多重设定枚举与外生性检验，否则只是换一种 p-hacking。
- 把 N 漏算：跨会话/跨用户/跨家族反复回测若不统一计数，DSR/PBO 门槛会被系统性低估。
- 二手证据需留余地：t>3.0、PBO 等阈值是建模约定而非物理常数，应作可调护栏。
- 把预注册当"正确性保证"营销会损害对机构用户的信任——它只保证可被严格评估 severity，不保证结论为真。

## 8. 开放问题

> 以下为对抗核查暴露的、研究**整体回避**的范式级风险，须单列评估。

1. **假设卡本身制造 meta-level 过拟合渠道。** 把 falsification_condition/stop_rule/阈值写进卡，等于固化一组超参；用户会反复重开卡直到某张卡在 OOS 通过（卡层面的 garden of forking paths）。如何对"卡的数量"本身计数与惩罚？这是把 N 计数从单策略推到"卡家族"时的**递归难题**，研究未讨论。

2. **谁来当独立验证者？** 同一个 LLM 既帮用户生成假设、又当复核者，**根本不满足 SR 11-7 的组织独立性要求**（独立性是制度安排，不是角色扮演）。把合规语言贴到一个结构上不独立的系统上属信任叙事的包装风险。

3. **A 股市场的制度特殊性未评估。** A 股的涨跌停、T+1、停牌、退市、注册制前后规则变迁、强散户结构，使"冻结一段从未触碰的最终 OOS 时间后段"极易因 regime 断裂（2015 股灾、2016 熔断、2020 注册制）失去代表性——观察性数据的"冻结 OOS"在制度突变市场比成熟市场**更脆弱**。"freeze before final OOS"落到数据访问层的方案对 A 股适用性完全未评估。

4. **低频/小样本下预注册的统计功效缺口。** 中低频策略（非 HFT）天然样本少、独立观测稀疏；DSR/PBO/最小回测长度在小样本下估计方差极大；t>3.0 在月频几十到一两百个观测上几乎不可能达到。把为高频/大样本设计的多重检验框架套到中低频，可能导致"永远无法通过门禁"或门槛被迫调松至失去意义——这个张力未触及。

5. **"OOS 只碰一次"与持续运营/再训练根本冲突。** 真实部署策略需随市场漂移再训练（v3 训练平台、walk-forward、模型再训），而"OOS 只能碰一次"与"定期再训练必然反复消费近段数据"**直接矛盾**。把 registered-reports 式一次性冻结当北极星，却没说清在一个需要持续再训练的实盘系统里"最终 OOS"如何随时间滚动而不退化为又一次 walk-forward——这是把元科学一次性实验范式生搬到运营系统的**根本范式错配**。

6. **缺少反方/怀疑预注册整体价值的经验证据平衡。** 除 Lakens/van Dongen 的"执行层批评"外，存在更根本质疑（预注册是否真提高已发表研究复现率证据混杂、预注册研究效应量未必更稳）。研究的"诚实边界"集中在"执行不到位"，而非"即使完美执行，预注册对最终决策质量的提升幅度是否被高估"。

7. **对话式假设卡填写的可用性风险零评估。** 面向小白用自然语言生成机器可执行确认性分析（Apéritif 式），其失败模式（用户写出看似具体实则不可证伪的条件、Agent 幻觉出貌似严谨的 falsification_condition）未被讨论；而这恰恰会让"装样子的预注册"以更隐蔽的形式发生。

## 9. 参考文献（URL）

- COS — OSF Registries：<https://www.cos.io/products/osf-registries>
- COS — Registered Reports：<https://www.cos.io/initiatives/registered-reports>
- AsPredicted：<https://aspredicted.org>
- J-PAL — Pre-Analysis Plans：<https://www.povertyactionlab.org/resource/pre-analysis-plans>
- AEA RCT Registry / Social Science Registry：<https://www.socialscienceregistry.org/>
- Bailey & López de Prado — Deflated Sharpe Ratio (SSRN 2460551)：<https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2460551>
- PyWhy — DoWhy：<https://www.pywhy.org/dowhy/> · PyWhy 生态：<https://www.pywhy.org/>
- OSF API：<https://developer.osf.io/>
- DVC：<https://dvc.org/>
- mlfinlab：<https://github.com/hudson-and-thames/mlfinlab>
- specr：<https://github.com/masurp/specr>
- Apéritif (CHI 2022)：<https://dl.acm.org/doi/fullHtml/10.1145/3491102.3517707>
- Kerr (1998) HARKing：<https://journals.sagepub.com/doi/abs/10.1207/s15327957pspr0203_4>
- Nosek et al. (2018) Preregistration Revolution, PNAS：<https://www.pnas.org/doi/10.1073/pnas.1708274114>
- Brodeur, Cook, Hartley, Heyes (2024) Pre-registration & PAP (SSRN 4180594)：<https://papers.ssrn.com/sol3/papers.cfm?abstract_id=4180594> · JPE Micro：<https://www.journals.uchicago.edu/doi/10.1086/730455>
- Olken (2015) Promises and Perils of PAP, JEP：<https://dspace.mit.edu/handle/1721.1/104069>
- Harvey, Liu, Zhu (2016) …and the Cross-Section, RFS：<https://academic.oup.com/rfs/article-abstract/29/1/5/1843824>
- Wiecki et al. (2016) All that Glitters (SSRN 2745220)：<https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2745220>
- López de Prado — Causality and Factor Investing Primer (CFA)：<https://rpc.cfainstitute.org/sites/default/files/docs/research-reports/rf_lopezdeprado_causalityprimer_online.pdf>
- Brodeur, Cook, Heyes (2020) Methods Matter, AER：<https://www.aeaweb.org/articles?id=10.1257/aer.20190687>
- Kranz-Pütz Comment / Brodeur Reply (AER 2022)：<https://www.aeaweb.org/articles?id=10.1257/aer.20210121>
- van Dongen et al. (2024) Preregistration & severity (arXiv 2408.12347)：<https://arxiv.org/pdf/2408.12347>
- Chen (2022) Do t-stat Hurdles Need to be Raised? (arXiv 2204.10275)：<https://arxiv.org/pdf/2204.10275>
- Arian, Norouzi, Seco (2024) CPCV (SSRN 4686376)：<https://papers.ssrn.com/sol3/papers.cfm?abstract_id=4686376>
- RFS FinTech registered reports special issue：<https://academic.oup.com/rfs/article-abstract/32/5/1647/5427782>
- SR 11-7 (Federal Reserve / OCC)：<https://www.federalreserve.gov/supervisionreg/srletters/sr1107.htm>
- NIST AI RMF 1.0：<https://www.nist.gov/itl/ai-risk-management-framework>
- Critical Finance Review (Welch)：<https://cfr.ivo-welch.info/>
