# 15 · 多重检验 + honest-N（White RC/Hansen SPA/HLZ/FDR/N_eff）

> 机构级 Agent OS 成品环节深挖 · 全程 Opus 4.8 · 对抗式核查已降权 · 重心=前沿研究+概念级推荐 · 不含 file:line 代码接线
> 簇 C

## 1. 一句话定位

把「为了找到一个好策略，到底试了多少次」如实记账（honest-N），并据此对单策略显著性做**多重检验校正**——回答「这个 Sharpe / alpha 是真信号，还是在 N 次试验里抽到的运气」。核心三件事：(a) 把名义试验数折算成**有效独立试验数 N_eff**（多数回测高度相关，不能直接用次数）；(b) 用 bootstrap 类检验（White RC / Hansen SPA / Romano-Wolf StepM / MCS）判定「最优策略相对基准是否真超越」，用 FDR（BH/BY）控制「我挑出的这批因子里假阳性占比」；(c) 用 Deflated / Probabilistic Sharpe 把 N_eff、样本长度、偏度峰度一并纳入。最终对用户兑现的，是「流程即信任」的一句承诺——**任何策略卡都能回答「你为得到我试了多少次」**——而非给小白一个虚假精确的 `t>3` 红线。

## 2. 前沿 SOTA 与代表系统

下表覆盖「时序/单策略多重检验 → 截面/因子 FDR 校准基准 → N_eff 折算 → PSR/DSR/PBO 实现」四层：

| 系统 | 角色 | 要点 | URL |
|---|---|---|---|
| **arch（Python, Kevin Sheppard）`bootstrap.multiple_comparison`** | 时序多重检验首选依赖 | 工业级、维护良好的 White RC / Hansen **SPA** / Romano-Wolf **StepM** / **MCS** 实现，内置 stationary / circular / moving-block bootstrap 与 studentize。可直接判定「多个候选策略相对基准是否真超越」。 | https://bashtage.github.io/arch/multiple-comparison/multiple-comparison_examples.html |
| **Open Source Asset Pricing（Chen-Zimmermann, OpenSourceAP/CrossSection）** | 已发表 N / FDR / 门槛的事实校准基准 | 约 200+ 截面因子可复现数据与代码（Python 造信号 + R 造组合），自带每因子相对原论文的 t 值与复现质量标注。是检验我们 N_eff / FDR 估计是否合理的外部锚点。 | https://github.com/OpenSourceAP/CrossSection |
| **mlfinlab / Machine-Learning-for-Asset-Managers（López de Prado 配套）** | N_eff 折算 + 虚假策略检测 | 实现 **ONC**（Optimal Number of Clusters）从相关矩阵聚类估 N_eff，并衔接 PSR/DSR 的虚假策略检测流程。**注**：ONC→N_eff 是作者自营、缺乏独立第三方复现、对超参敏感的启发式（见 §7）。 | https://www.mlfinlab.com/en/latest/clustering/onc.html |
| **pypbo（esvhd）+ rubenbriones/Probabilistic-Sharpe-Ratio** | PBO / PSR / DSR 轻量参考实现 | PBO（CSCV 组合对称交叉验证）、PSR、DSR 的轻量 Python 实现与示例 notebook，适合做参考实现与交叉校验。 | https://github.com/esvhd/pypbo |
| **rwolf2（Clarke-Romano-Wolf, Stata）** | Romano-Wolf StepM 标准实现 | 逐步降幅多重假设校正标准实现（算法可移植到 Python），用 studentized bootstrap 隐式估计检验相关结构控 FWER，比 Bonferroni/Holm 更有 power。 | https://github.com/damiancclarke/rwolf2 |
| **Hou-Xue-Zhang global-q.org / openassetpricing.com** | 异象复现的事实标准数据 | 452 异象用 NYSE 断点 + 市值加权复现的可信度事实标准（vs 旧式 t=1.96 等权全样本）；提供「多数异象不可复现」一侧的实证数据。 | https://www.openassetpricing.com/data/ |

## 3. 关键论文（每条带 URL）

- **A Reality Check for Data Snooping**（White, 2000, Econometrica）—— 用 bootstrap 检验「在全部被搜索过的规则里，最优规则相对基准是否真有超额预测力」，首次把「试了多少次」纳入显著性判定。**注**：RC 在 least-favorable 配置 + 被无用规则稀释时**过度保守**（低 power，可能把真规则判死）；其在技术规则上的实证结论高度依赖样本期/市场/规则集/基准（见 §7，「多数最优规则不再显著」属过度概括）。
  https://econweb.rutgers.edu/nswanson/papers/corradi_swanson_whitefest_1108_2011_09_06.pdf

- **A Test for Superior Predictive Ability**（Hansen, 2005, JBES）—— 指出 White RC 因 least-favorable configuration + 被无用模型稀释而损失 power；SPA 用 studentized 统计量并仅纳入相关模型提升 power。是「RC 太保守」这一**已确证缺陷**的标准修正。
  https://bashtage.github.io/arch/multiple-comparison/multiple-comparison_examples.html

- **Stepwise Multiple Testing as Formalized Data Snooping**（Romano & Wolf, 2005, Econometrica）—— StepM 逐步检验给出「哪些模型超越基准」的集合并控 FWER，通过 bootstrap 估计检验间相关、不需 subset pivotality，比 Bonferroni/Holm 更有 power。
  http://www-stat.wharton.upenn.edu/~steele/Courses/956/Resource/MultipleComparision/RomanoWolf05.pdf

- **… and the Cross-Section of Expected Returns**（Harvey, Liu, Zhu, 2016, RFS）—— 对约 316 个已发表因子做 Bonferroni/Holm/BHY 校正（含允许检验相关与缺失数据的模型），得出新因子「t 需 > 约 3.0」的经验门槛，是「因子动物园需更高门槛」的奠基文献。**注**：这条「t>3」的对立框架已被同一作者群 2026 年新作部分推翻（见 §7、§3 末条 Harvey 2026）。
  https://people.duke.edu/~charvey/Research/Published_Papers/P118_and_the_cross.PDF

- **Replicating Anomalies**（Hou, Xue, Zhang, 2020, RFS）—— 用 NYSE 断点 + 市值加权复现 452 异象：约 **65%** 连 t=1.96 都过不了；加多重检验门槛 t≈2.78 失败率升至 **82.1%**；trading-frictions 类 **96%** 失败。强烈支持「多数异象不可复现 / 源于微盘与等权」一侧。
  https://global-q.org/uploads/1/2/2/6/122679606/houxuezhang2020rfs.pdf

- **The Deflated Sharpe Ratio**（Bailey & López de Prado, 2014, SSRN 2460551）—— DSR = Φ((SR−SR0)·√(T−1)/√(1−γ₃·SR+(γ₄−1)/4·SR²))，期望最大 Sharpe `SR0` 随试验数 N 与试验 Sharpe 方差上升（含 Euler-Mascheroni 项）。把 N、样本长度、偏度峰度一并纳入。**注**：DSR 本质是**选择偏倚/标度门槛修正**（scale/threshold correction），非对 Sharpe 系统性偏差的根本修复；仍依赖对零分布的正态近似，且**循环依赖于本环节最不稳健的 N_eff 估计**——不应被定位成「最终裁决」（见 §7）。
  https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2460551

- **Detection of False Investment Strategies Using Unsupervised Learning**（López de Prado & Lewis, 2019）—— 提出从回测相关矩阵聚类（ONC）估「有效独立试验数 N_eff」再喂入 DSR/虚假策略概率，解决「回测高度相关、不能直接用次数当 N」的核心难题。**注**：主要在作者自家合成/示例数据上展示，缺乏独立第三方在真实多策略生命周期上的稳健性复现（见 §7）。
  https://codemacher.com/wp-content/uploads/2021/02/Detection-of-false-investment-strategies-using-unsupervised-learning-methods_M.LopezDePrado_and_M.Lewis_2018.pdf

- **Do t-Statistic Hurdles Need to be Raised?**（Chen, 2023, Management Science）—— 反方关键证据：「提高 t 门槛」是**弱可识别**的——失败试验未被观测，校准更高门槛必须外推缺失结果而不可靠；据此有效门槛仅约 t≈1.8–2.0。**对抗核查重要补正**：Chen 自己的 π_F（假因子占比）90% 置信区间是 **0%–70%**，故「有效门槛≈1.8–2.0」**本身也是弱可识别下的点估计**，同样不应当作可信单点；Chen 真正证明的是「门槛不可被可靠抬高」，不等于「门槛应该是 1.8–2.0」（见 §7）。
  https://arxiv.org/abs/2204.10275

- **Most Claimed … Cross-Sectional Return Predictability Are Likely True**（Chen, 2022）—— 给 FDR 下界，估计已发表截面预测里 ≥75%（最紧 ≥91%）为真。与「多数异象是假」的叙事直接对立，必须并列呈现。
  https://arxiv.org/abs/2206.15365

- **Publication Bias and the Cross-Section of Stock Returns**（Chen & Zimmermann, 2020, RFS）—— publication-bias 调整后收益仅比样本内小约 **12.3%**，离散度太大无法用数据挖掘噪声解释——支持「信号大体真实、但 t 值有上偏（shrinkage）」。佐证「收缩是强可识别、门槛抬高是弱可识别」的两分。
  https://www.federalreserve.gov/econres/feds/publication-bias-and-the-cross-section-of-stock-returns.htm

- **The Control of the FDR in Multiple Testing under Dependency**（Benjamini & Yekutieli, 2001, Ann. Stat.）—— BY 在任意相关下控制 FDR，校正因子 c(m)=Σ1/j（≈ln m），比 BH 更保守。提供「检验相关时仍能控 FDR」的理论基础；**BH 显著而 BY 不显著即提示检验高度相关**。
  https://projecteuclid.org/journals/annals-of-statistics/volume-29/issue-4/The-control-of-the-false-discovery-rate-in-multiple-testing/10.1214/aos/1013699998.full

- **What Threshold Should be Applied to Tests of Factor Models?**（Harvey, Sancetta, Zhao, 2026, NBER w34898）—— **对抗核查补入的 2026 最新反向文献**：HLZ 核心作者 Harvey 本人重新论证 t≥3.0 是有效显著性门槛的**下界**，并明确采用 **local FDR**（即 Chen 一派主张的强可识别 FDR 机制）。两派在 FDR 工具上已**部分趋同**，而非简单对立——直接争议「t>3 已被证伪」的叙事（见 §7）。
  https://www.nber.org/papers/w34898

## 4. 机构最佳实践 / 标准

- **SR 11-7 模型风险管理三支柱**（概念健全性 / 持续监控·基准比对 / 结果分析含 out-of-sample back-testing）：多重检验 / N-记账可类比对应「概念健全性」与「结果分析」。**注**：本研究引用源是供应商营销页（modelop.com）而非一手 Fed/OCC 文件；且「SR 11-7 对应 N-记账」是**研究自身的引申解读**，原文并未提及多重检验校正或试验数记账——应降级为「可类比/可借鉴的治理框架」，并以一手文件为准（见 §7）。
  https://www.modelop.com/ai-governance/ai-regulations-standards/sr-11-7

- **行业经验法则（López de Prado / Bailey）**：5 年日频数据下尝试超过约 **45 个**配置即极可能过拟合。**对抗核查重要补正**：原文（Minimum Backtest Length / DSR）说的是 45 个**独立（independent）配置**——即对有效独立试验数 N_eff 的上限，**不是 45 个「策略变体」或原始网格次数**。实际可能跑数百个高相关网格才折算出 45 个独立试验。把它转述成「跑 45 个网格就过拟合」恰好犯了 N vs N_eff 混淆（见 §7）。
  https://academic.oup.com/jrssig/article/18/6/22/7038278

- **不报告试验数 N 等同于一种「选择偏倚式误导」**：行业共识把「公开有效 N + 多重检验校正后指标」当作诚实回测报告的最低标准。

- **学术复现标准的实际收紧**：顶级期刊（RFS）与复现项目（HXZ global-q、Chen-Zimmermann OpenSourceAP）已把「市值加权 + NYSE 断点 + 多重检验门槛」作为异象可信度的事实标准，而非旧式 t=1.96 等权全样本。
  https://www.openassetpricing.com/data/

## 5. 对 QuantBT 这套架构的推荐方向（概念级）

> 概念级方向，不点 file:line、不排实施计划。

1. **把 N 当一等公民、贯穿全生命周期自动记账**：给每个用户 / 每个研究主题维护一本「试验账本」，凡 agent 跑过的回测、参数扫描、选股变体、特征切换都自动 +1 并落盘（加密，符合 D2 真隔离）。账本应 **append-only + 执行即记账 + 删除留痕**——类比 §8 M17 跟单杠杆护栏曾被中继绕过的教训，若 N 计数能被某条研究路径绕过（换 session 重跑不计、手动洗掉失败试验），整个信任链失效。「流程即信任」的具体兑现就是：任何策略卡都能回答「你为得到我试了多少次」。

2. **严格区分「名义 N」与「有效 N_eff」**：直接用回测次数会严重高估 N（多数试验高度相关，把 100 个近乎相同的网格当 100 次独立试验是过度惩罚）；只报告「最终那一次」则严重低估 N（选择偏倚式误导）。概念上对候选策略收益序列做相关聚类取簇数当 N_eff。**但务必如实披露**：N_eff 折算（ONC/层次/谱）是本环节**最不稳健**的估计量，对距离度量/聚类算法/相关矩阵估计窗口都敏感，缺乏独立复现——应**报告对 N 的敏感性区间而非单点**（见 §7）。

3. **两层校正、各司其职**：截面/因子选择层用 **FDR**（BH；检验明显相关时用 BY）做「我挑出的这批因子里假阳性占比可控」；时序/单策略相对基准层用 **SPA/StepM/MCS**（bootstrap，保留相关结构）做「最优策略是否真超越基准」。单策略最终显著性用 Deflated/Probabilistic Sharpe **作为多个相互校验指标之一**（而非「最终裁决」），把 N_eff、样本长度、偏度峰度一并纳入，而不是裸 t 值或裸 Sharpe。

4. **诚实呈现「门槛本身不确定」——不给小白一个虚假精确的 `t>3` 红线**：必须把 HLZ（t>3）、Harvey 2026（用 local FDR 重新论证 t≥3 为下界）、Chen（弱可识别、点估计 1.8–2.0 同样不可信）、HXZ（多数异象不过关）与 Chen 2022（多数发表为真）这组**未完全和解**的证据，翻译成「区间 + 置信度」而非单点裁决。建议输出「谨慎/标准/宽松」三档门槛及各自统计含义。**关键护栏**：三档门槛选择本身是一层可被 p-hacking 的自由度（用户可换档直到心仪策略过关），故档位应**预注册/锁定**于研究开始前，而非把放水权交给最有动机的用户（见 §7、§8）。

5. **把 N-记账与发表偏倚（shrinkage）分开报告**：Chen-Zimmermann 证明「已发表 t 上偏/收缩」是**强可识别**的，而「该把门槛抬多高」是弱可识别的。对应到产品——对策略 Sharpe 做收缩（给出「去偏后的现实预期」）可信、应默认开；把不确定的「更高门槛」伪装成铁律则应避免。对外部引入的因子（如来自 aiquantclaw 方法论或公开因子）默认套用收缩 + 发表偏倚提示。

6. **为「资产无关、中低频」裁剪 bootstrap**：必须用 **block/stationary bootstrap** 保留自相关（日/周频收益有序列相关），而非 iid 重抽（iid 会低估方差、高估显著性）。**但 block size 选择本身是又一层未记账的研究者自由度**（arch 默认 √T 是任意的），应预注册或给敏感性区间（见 §8）。A股（到 paper）与加密（到 Binance 实盘）样本长度、非正态程度差异大，DSR 的偏度/峰度校正与 T 必须按资产实估——**加密尤其危险**：山寨/早期 Binance 样本极短 + 幸存者偏差 + 制度突变，T 太小会让 DSR 渐近正态近似与偏峰校正彻底失效，给出「披着统计严谨外衣的虚假精确 p 值」（见 §7、§8）。

7. **把多重检验做成生命周期「闸门」而非事后报告，但明确闸门的边界**：在「研究→候选→纸面/实盘」每道关卡前用当前累计 N_eff 重算 SPA/DSR 判定，未过闸不允许推进（实盘 agent 仅警告 + 规则停，符合 D3）。**但须向用户披露闸门有原理性盲区**：(a) 闸门只管统计显著性，不碰交易成本/容量/拥挤/可实现性——一个统计真的信号扣除 A股印花税/涨跌停/停牌、加密滑点与资金费率后可能净值为负（HXZ 自己发现 trading-frictions 类 96% 失败正说明很多异象死在摩擦上）；(b) 非平稳/regime shift 才是中低频策略 OOS 失效主因，过了统计闸门 ≠ 会赚钱。不能让用户误以为「过了闸门 = 安全」（见 §8）。

## 6. 架构级参考（少量伪代码 / schema 草图，非代码接线）

> 示意，非接线到现有代码。

**试验账本（append-only，执行即记账）：**

```
trial_ledger(
  trial_id        text,          -- 与回测执行强绑定，执行即写入
  user_id         text,
  research_topic  text,          -- 维护每主题独立 N
  asset_class     text,          -- a_share | crypto（DSR 偏峰/T 按此分资产估）
  kind            text,          -- backtest | param_sweep | universe_variant | feature_switch
  return_series   blob,          -- 用于 N_eff 相关聚类
  sharpe          numeric,
  config_hash     text,
  created_at      timestamptz,   -- append-only
  -- 删除/重置必须留痕，不可静默清零
  superseded_by   text,          -- 软删除指针，原行不物理删除
  audit_reason    text
)
-- 铁律：换 session 重跑同 config_hash 仍计入；手动"洗掉失败试验"=留审计痕迹的 supersede，不是 delete
```

**名义 N → 有效 N_eff（相关聚类，报敏感性区间而非单点）：**

```
corr        = correlation_matrix(all_trials.return_series)   # 样本有限时估计噪声大
clusters    = cluster(corr, method ∈ {ONC, hierarchical, spectral})
N_eff       = num_clusters(clusters)
# 不稳健：N_eff 对 method / 距离度量 / 窗口敏感 → 输出 [N_eff_low, N_eff_high]
# 而非单点；下游 DSR 用区间端点各算一遍做敏感性
```

**两层校正（各司其职）：**

```
# 截面/因子层：FDR
reject_set  = BH(pvals, q=0.05)         # 默认
if BH_significant and not BY_significant(pvals, q=0.05):
    flag("检验高度相关 → 改用 BY 或谨慎解读")  # FDR 控的是"被拒集合里假阳性比例"，非单假设可信度

# 时序/单策略 vs 基准层：bootstrap（保留序列相关）
verdict     = SPA(losses, block_size=?, bootstrap='stationary')   # block_size 本身是未记账自由度 → 预注册
# 优先 SPA/StepM（RC 过度保守，低 power 会把真策略判死）
```

**Deflated Sharpe 作为「多指标之一」（非最终裁决）：**

```
SR0 = expected_max_sharpe(N_eff_interval, var_trial_sharpe)   # 循环依赖 N_eff（本环节最不稳健量）
DSR = Phi((SR - SR0) * sqrt(T-1) / sqrt(1 - g3*SR + (g4-1)/4 * SR**2))
# g3/g4/T 按 asset_class 实估；加密短样本 → 渐近近似可能失效 → 标注"统计精确度存疑"
# 产品判定 = {DSR, SPA verdict, PBO, 收缩后预期} 交叉校验，不让单一 DSR 拍板
```

**生命周期闸门（带边界披露）：**

```yaml
gate: promote_research_to_paper
preregistered:
  threshold_tier: standard        # 谨慎/标准/宽松三档须研究开始前锁定，防换档 p-hacking
  bootstrap_block_size: sqrt_T    # 同样预注册
checks:
  - rule: dsr_pass(N_eff_interval, tier)   # 用区间端点，不用单点
    on_fail: block_promotion
disclosures:                       # 不可关闭的诚实披露，随判定一起呈现给用户
  - "闸门只管统计显著性，未计交易成本/容量/拥挤/可实现性"
  - "过闸 ≠ 会赚钱：regime shift / 非平稳才是中低频 OOS 失效主因"
  - "honest-N 只记本系统内 N，无法记跨研究者/全网累积窥探"
```

## 7. 降权 / 争议 / 陷阱（对抗核查结论）

> 以下限定词（夸大/争议/撤稿/二手/不可外推/单源/弱可识别/被最新文献争议/选择性引用 等）原样保留，凡涉「已验证/已确证/最终裁决/既定标准」的强确定性措辞均已按对抗核查降级；任何对用户的承诺或文案，必须采用降级后的表述。

- **【high · 被最新文献争议 disputed_by_newer_work】「将 HLZ（t>3）与 Chen（有效门槛≈1.8–2.0）并列为一组未和解的对立证据，暗示 t>3 缺乏数据支撑、是可疑的『虚假精确红线』」**——这个对立框架**已过时**。HLZ 核心作者 Harvey 本人在 2026 年 NBER 工作论文 **w34898**《What Threshold Should be Applied to Tests of Factor Models?》（Harvey-Sancetta-Zhao）中重新论证 **t≥3.0 是有效显著性门槛的『下界』**，并明确采用 **local FDR**——即 Chen 一派主张的强可识别 FDR 机制。两派在 FDR 工具上**已部分趋同，而非简单对立**。原研究文献版图停在 2016/2022/2023，遗漏了直接反驳「t>3 已被证伪」叙事的 2026 最新文献，把一个仍在演进、且最新一轮由 HLZ 作者亲自用 FDR 重新支持 t≥3 的争论，呈现成了 Chen 单方面占上风的定论。**文案禁止暗示「t>3 已被推翻」**。
  https://www.nber.org/papers/w34898

- **【high · 选择性引用 / 弱可识别 self_undercutting】「援引 Chen(2023) 得出『真正强可识别的有效门槛仅约 t≈1.8–2.0』并以此质疑 HLZ」**——对 Chen 自己的数字**缺乏同等对抗审视**。Chen(2023) 的核心结论恰恰是 π_F（假因子占比）**弱可识别**——其 bootstrap 估计的 **90% 置信区间是 0%–70%**。既然门槛随 π_F 强烈变化而 π_F 几乎不可识别，那么「有效门槛≈1.8–2.0」**本身也是从一个弱可识别参数里抽出的点估计**，同样不应被当作可信单点。原研究用 Chen 的弱可识别论批 HLZ，却没把同一把尺子用在 Chen 给出的 1.8–2.0 上，属选择性引用。**诚实表述应是：Chen 证明的是「门槛不可被可靠抬高」，不等于「门槛应该是 1.8–2.0」**。
  https://arxiv.org/abs/2204.10275

- **【medium · 二手错转 misquoted_secondhand】「5 年日频数据下尝试超过约 45 个『策略变体』即极可能过拟合」**——**二手数字且被错误转述**。Bailey-López de Prado 原文（Minimum Backtest Length / DSR）说的是 45 个**独立（independent）配置**，是对有效独立试验数 N_eff 的上限，**不是 45 个「策略变体」或原始回测/网格次数**。原研究在别处反复强调名义 N 与 N_eff 必须区分，却在这条经验法则里恰恰犯了把「独立配置」偷换成「策略变体」的错——会向用户传递「跑 45 个网格就过拟合」的错误锚点（实际可能跑数百个高相关网格才折算出 45 个独立试验）。
  https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2460551

- **【medium · 定位抬高 / 循环依赖 mischaracterized】「把 Deflated/Probabilistic Sharpe 当作 honest-N 后单策略显著性的『最终裁决』指标」**——对 DSR 的定位**略有夸大、且存在循环依赖**。DSR 本质是对显著性门槛/标度的修正（scale/threshold correction），**不是对 Sharpe 系统性偏差的根本修复**：它仍依赖对零分布的正态近似（仅偏峰校正）、依赖「试验间 Sharpe 服从某分布」的假设。更关键的循环：DSR 必须先有 N_eff 才能算，而 **N_eff 正是本环节最难、最不稳健的估计量**。把「终判指标」建立在一个需要先解决另一个未解难题（N_eff）的公式上，与 pitfalls 里「DSR 对 N_eff 敏感、聚类不稳健会动摇结论」的警示**自相矛盾**——应降格为「**多个相互校验指标之一**」。
  https://en.wikipedia.org/wiki/Deflated_Sharpe_ratio

- **【medium · 未经独立复现 / 超参敏感 weak_empirical_validation】「ONC 从相关矩阵估 N_eff，作为 honest-N 把回测次数折算为有效 N 的『标准方法』」**——把一个**未经独立大规模复现、对超参敏感的启发式**当成既定标准。López de Prado-Lewis(2019) 的 ONC→N_eff 流程主要在**作者自家合成/示例数据**上展示，缺乏来自独立第三方在真实多策略生命周期上的稳健性复现。簇数 N_eff 对距离度量、聚类算法、相关矩阵估计窗口都敏感，且「策略相关矩阵」本身在样本有限时估计噪声很大。与 mlfinlab 生态整体被批评为「作者自营、缺乏外部同行复现」的背景一致。**应标注其经验验证薄弱、结果不稳健，输出区间而非单点**。

- **【low · 二手营销源 / 自我引申 secondary_source】「SR 11-7 三支柱作为把 N-记账写成『验证证据』的治理框架锚点」**——引用源是**供应商营销页（modelop.com）而非一手监管文件**（Federal Reserve SR 11-7 / OCC 2011-12 Bulletin）。SR 11-7 三要素是真实的，但「多重检验/N-记账天然对应概念健全性与结果分析」是**研究自己的引申解读**——SR 11-7 原文并未提及多重检验校正或试验数记账。容易给用户造成「监管已要求 N-记账」的过度印象，应降级为「可类比/可借鉴的治理框架」并引一手文件。

- **【low · 过度概括 overgeneralized】「White RC『后续实证显示校正数据窥探后，多数市场上最优规则不再显著』」**——**过度概括**。RC/SPA 在技术交易规则上的实证（Sullivan-Timmermann-White、Hansen 等）结论高度依赖样本期、市场、规则集与基准选择，并非普适的「多数市场最优规则不再显著」。同时 RC 因 least-favorable + 被无用规则稀释而**过度保守**——所以「不再显著」里有一部分是 RC 把真规则也判死的**低 power 假阴性**，不能简单读作「规则本就是噪声」。该句把一个条件性、方法依赖的实证结果说成了普遍定论。

**总体核实结论（verdict 摘要）**：证据基础总体扎实——HXZ（65%/82%/96%）、HLZ（316 因子、t>3）、Chen 2022（FDR≤25% 即 ≥75% 为真、最紧 ≥91%）、Chen-Zimmermann（去偏后仅小约 12.3%）、DSR 公式、以及 arch 包（SPA/StepM/MCS + stationary/block bootstrap + studentize）等关键论断经核实**全部正确，未发现撤稿或事实性错误**。引用诚实度高于平均，但对反方（尤其 2026 最新的「t>3 回归」与 Chen 自身门槛的弱可识别）呈现不足，并在 N_eff/DSR 的成熟度与可达成度上存在**系统性乐观**。建议把所有显著性裁决降格为「区间 + 多指标交叉校验 + 档位预注册」，并明确向用户披露 honest-N 存在原理性天花板。

**撤稿雷区核查**：arXiv **2512.11913**（拥挤缩量）为已知撤稿论文——本研究**未引用，未踩雷**（not_cited_clean）。

**通用陷阱清单（工程红线）：**

- 把回测次数直接当 N 用——绝大多数试验高度相关，名义 N 远大于 N_eff，会过度惩罚漏掉真信号；反之只报告「最终那一次」严重低估 N（选择偏倚式误导，等同隐瞒）。
- 误以为提高 t 门槛（如 HLZ t>3）是数据严格支持的铁律——Chen(2023) 证明它**弱可识别**，门槛依赖对「未被观测的失败试验」的外推；但**反过来**把 Chen 的 1.8–2.0 当确定红线也错（同为弱可识别点估计）。两边都不是铁律。
- White RC **过度保守**：least-favorable + 被无用规则稀释时 power 很低，可能把真策略判死——应优先 Hansen SPA / StepM。
- Bonferroni/Holm 在检验高度相关时过度保守；BH（独立或正相关）与 BY（任意相关，更保守）选错会系统性偏松/偏紧——先判检验相关结构（**BH 显著而 BY 不显著 = 高度相关信号**）。
- Deflated Sharpe **仍是模型化的**：依赖对 Sharpe 零分布的正态近似（仅偏峰校正）且对 N（及 N_eff 估计）敏感；N_eff 聚类不稳健会直接动摇结论——报敏感性而非单点。
- 用 **iid bootstrap** 处理有序列相关的中低频收益会低估方差、高估显著性——必须用 block/stationary bootstrap；**但 block size 选择本身是新的 p-hacking 自由度**（见 §8）。
- 「多数异象是假」（HXZ）与「多数发表为真」（Chen）两派结论**都被严肃文献支持且未完全和解**——只引一派会给用户错误确定感；须并列并解释分歧来源（加权方式、样本、是否含微盘、识别假设）。
- FDR 控的是「被拒绝集合里的假阳性比例」**而非单个假设的可信度**——把 FDR 误讲成「这个策略有 95% 是真的」是**概念错误**。
- N 账本若能被绕过（换 session 重跑不计、手动删失败试验）则形同虚设——必须 append-only + 执行即记账 + 删除留痕，否则重蹈跟单护栏被中继绕过的覆辙。

## 8. 开放问题

- **数据窥探的「社会化/累积」维度——honest-N 的原理性天花板**：White RC / SPA / DSR 都假设 N 是「本次研究/本系统内」可数的试验数。但因子动物园的真正过拟合来自**跨研究者、跨数十年在同一（高度重叠的）CRSP / A股 / Binance 历史上的累积窥探**。Agent OS 的「试验账本」只能记本系统内的 N，对「整个学术界 + 全网量化社区已把这段历史窥探过千万次」这一最大的 N 来源**无能为力**。这是 honest-N 概念上的天花板——不能把它当成靠记账就能解决的工程问题，必须如实向用户披露。
- **bootstrap block size 是又一座 garden of forking paths**：SPA/StepM 结论对 block_size 敏感（arch 默认 √T 是任意的）。在 honest-N 语境下 bootstrap 超参选择本身就构成**未记账的试验**——是否需要把 block size 也预注册或给敏感性区间？
- **加密短样本肥尾让 DSR 渐近近似失效**：加密（尤其山寨/早期 Binance）样本极短 + 大量幸存者偏差（退市/归零币种）+ 制度突变（分叉、监管、交易所事件），T 太小会让 DSR 的渐近正态近似与偏峰校正彻底失效。在如此短的肥尾序列上 DSR/SPA 的 p 值可能给出**虚假精确度，比裸 Sharpe 更危险**（披着统计严谨的外衣）。加密侧是否应直接禁用 DSR 单点裁决、只做定性警示？
- **统计闸门 ≠ 经济可实现——交易成本/容量/拥挤的盲区**：FDR/多重检验全针对「预测性显著（t/Sharpe）」，完全没碰扣除 A股印花税/涨跌停/停牌、加密滑点与资金费率后的净值。HXZ 自己发现 trading-frictions 类 96% 失败正说明很多异象死在摩擦上而非统计上。闸门只设在统计显著性会放行一批「统计真、经济假」的策略——如何把经济可实现性纳入闸门？
- **方法论本身的「元过拟合」/档位 p-hacking**：用户可在多重检验框架内继续挑选——换 SPA vs StepM vs MCS、换 BH vs BY、换谨慎/标准/宽松三档、换 N_eff 聚类方法——直到某档让心仪策略过关。「三档门槛 + 让用户用经济判断选档」恰恰是又一层可被 p-hack 的自由度。需要**档位预注册/锁定**，而非把档位选择权交给最有动机放水的用户——这与原研究把它当「诚实特性」相矛盾，须解决。
- **honest-N 如何处理「失败后的合法迭代」**：科学研究本就需试错，把每次合理调试都 +1 会导致 N 爆炸性虚高、所有策略都过不了闸（过度惩罚）。append-only 防绕过的同时，**如何在不鼓励洗数据的前提下区分诚实迭代与盲目搜索**？这是 honest-N 落地最难的产品/治理张力。
- **非平稳/regime shift vs 多重检验**：所有这些校正都假设存在一个稳定的零分布。但中低频策略失效更多源于市场结构变化而非纯粹的多重检验假阳性——一个策略可能样本内是真信号、过了所有 DSR/SPA 闸门，仍因 regime 改变而 OOS 失效。把信任几乎全押在多重检验校正上，会让用户误以为「过了统计闸门 = 会赚钱」，而真正的杀手往往是非平稳。

## 9. 参考文献（URL）

- White (2000) A Reality Check for Data Snooping（综述 PDF）：https://econweb.rutgers.edu/nswanson/papers/corradi_swanson_whitefest_1108_2011_09_06.pdf
- Hansen (2005) SPA / arch 多重检验示例：https://bashtage.github.io/arch/multiple-comparison/multiple-comparison_examples.html
- Romano & Wolf (2005) StepM：http://www-stat.wharton.upenn.edu/~steele/Courses/956/Resource/MultipleComparision/RomanoWolf05.pdf
- Harvey, Liu, Zhu (2016) … and the Cross-Section of Expected Returns：https://people.duke.edu/~charvey/Research/Published_Papers/P118_and_the_cross.PDF
- Harvey, Sancetta, Zhao (2026, NBER w34898) What Threshold …：https://www.nber.org/papers/w34898
- Hou, Xue, Zhang (2020) Replicating Anomalies：https://global-q.org/uploads/1/2/2/6/122679606/houxuezhang2020rfs.pdf
- Bailey & López de Prado (2014) The Deflated Sharpe Ratio：https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2460551
- López de Prado & Lewis (2019) Detection of False Investment Strategies：https://codemacher.com/wp-content/uploads/2021/02/Detection-of-false-investment-strategies-using-unsupervised-learning-methods_M.LopezDePrado_and_M.Lewis_2018.pdf
- Chen (2023) Do t-Statistic Hurdles Need to be Raised?：https://arxiv.org/abs/2204.10275
- Chen (2022) Most Claimed … Likely True：https://arxiv.org/abs/2206.15365
- Chen & Zimmermann (2020) Publication Bias …：https://www.federalreserve.gov/econres/feds/publication-bias-and-the-cross-section-of-stock-returns.htm
- Benjamini & Yekutieli (2001) FDR under Dependency：https://projecteuclid.org/journals/annals-of-statistics/volume-29/issue-4/The-control-of-the-false-discovery-rate-in-multiple-testing/10.1214/aos/1013699998.full
- arch（SPA/StepM/MCS 参考）：https://bashtage.github.io/arch/multiple-comparison/multiple-comparison-reference.html
- Open Source Asset Pricing（OpenSourceAP/CrossSection）：https://github.com/OpenSourceAP/CrossSection
- mlfinlab ONC：https://www.mlfinlab.com/en/latest/clustering/onc.html
- pypbo（PBO/CSCV + PSR + DSR）：https://github.com/esvhd/pypbo
- rwolf2（Romano-Wolf StepM）：https://github.com/damiancclarke/rwolf2
- Hou-Xue-Zhang / Open Asset Pricing 数据：https://www.openassetpricing.com/data/
- JRSS Significance (2021) Backtest Overfitting 经验法则：https://academic.oup.com/jrssig/article/18/6/22/7038278
- SR 11-7（二手营销页，须以一手 Fed/OCC 文件为准）：https://www.modelop.com/ai-governance/ai-regulations-standards/sr-11-7
- 撤稿雷区（未引用，留档）：https://arxiv.org/abs/2512.11913
