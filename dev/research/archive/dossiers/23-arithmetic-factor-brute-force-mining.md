# 23 · 算术因子暴力遍历挖掘 + 多重检验耦合

> 机构级 Agent OS 成品环节深挖 · 全程 Opus 4.8 · 对抗式核查已降权 · 重心=前沿研究+概念级推荐 · 不含 file:line 代码接线
> 簇 E

## 1. 一句话定位

公式因子暴力遍历（gplearn / RL / LLM 生成表达式树）的本质，是「用海量候选去换一个表面亮眼的回测」——只要候选数 N 足够大，即便全是噪声，被选中的「最优」也几乎必然在样本内出色。因此本环节的全部工程价值**不在挖得多快，而在挖完之后能否诚实地把绝大多数候选判死**。产品定位应是「诚实-N 守门人 + 经济先验过滤器」：暴力遍历只是廉价候选生成器，真正的护城河是把 honest-N → DSR/PBO/CSCV → Harvey-Liu haircut → FDR(BH/BY) 强制串进流程、生成器与守门器严格解耦、守门用嵌套 walk-forward OOS 在最后一次性裁决、且不可被用户绕过。但本环节有一条贯穿全文的对抗式红线（见 §7）：**这套守门工具自身也有模型风险**——t 门槛在发表偏误下统计上不可识别、honest-N 的聚类口径是新的可博弈旋钮、DSR 依赖噪声点估计——所以决不能把高不确定的判决渲染成给小白的「这个因子有多大概率只是运气」绿/红灯单点数字，那会用一个看似客观的统计闸门制造新的过度信任。

## 2. 前沿 SOTA 与代表系统

下表覆盖「DSL/搜索空间定义 → 候选生成器（GP/RL/LLM）→ 挖掘-组合解耦 → 多维体检 → 已知因子先验库」五层：

| 系统 | 角色 | 要点 | URL |
|---|---|---|---|
| **WorldQuant 101 Formulaic Alphas（Kakushadze, 2016）** | 公式 DSL / 算子词表的事实标准 | 公开 101 条真实生产用公式因子与算子（rank, ts_*, delta, correlation, decay_linear, scale, signedpower 等），定义暴力遍历的搜索空间与「已知拥挤因子」去重参照库。**注：平均持有期 0.6–6.4 天属实，但这是典型短线/高换手统计套利型 alpha（日内到数日级），不是本产品定位的中低频——直接拿 101 当中低频基准会系统性低估交易成本闸门（见 §7）。** | https://arxiv.org/pdf/1601.00991 |
| **gplearn（+时序算子扩展）** | 符号回归候选生成器（最轻量起点） | 第一个被广泛用于公式因子挖掘的遗传编程框架；以表达式树为个体、IC/RankIC 为适应度。开源、轻量、可穷举性强。**已知短板：强烈过拟合、易生成无经济含义的复杂表达式，需配 OOS 评估 / 复杂度正则 / 早停。** | https://github.com/trevorstephens/gplearn |
| **AlphaGen（RL, KDD 2023, RL-MLDM/alphagen）** | RL 候选生成器（协同因子集） | PPO（带 action masking）在算子序列空间搜索，优化「协同因子集合对下游组合模型的贡献」而非单因子 IC；接 Qlib/BaoStock。**已知短板：固定权重组合、文档未含正式多重检验 / walk-forward 校正——是过拟合风险的典型来源，须在外层补守门。** | https://github.com/RL-MLDM/alphagen/ |
| **AlphaForge（AAAI 2025）** | 挖掘-组合解耦 SOTA 方向 | 两阶段「生成-预测」网络挖因子 + 动态组合：每个时间切片按因子近期表现动态调权（对比 AlphaGen 固定权重），声称更能适应市场漂移、保持多样性。代表「挖掘」与「组合」解耦方向。 | https://arxiv.org/abs/2406.18394 |
| **AutoAlpha（层次化进化算法）** | 多样性导向进化搜索 | 分层进化搜索公式因子，用新颖性距离压制候选间相关、间接降低有效试验数膨胀。**注：正文为二进制 PDF 未能逐字提取，描述基于摘要与二手综述（见 §7）。** | https://arxiv.org/pdf/2002.08245 |
| **AlphaAgent / Alpha-GPT / Navigating-the-Alpha-Jungle（LLM+MCTS）** | 最贴近本产品形态的 LLM 智能体挖掘 | AlphaAgent（KDD 2025）三智能体（Idea/Factor/Eval）闭环 + 三类显式正则：AST 子树相似度去重、LLM 经济假设一致性对齐、符号长度/参数数/表达式规模复杂度控制，以对抗因子拥挤与 alpha 衰减。**短板：未用正式多重检验 / walk-forward——正是本环节要补的缺口。** | https://arxiv.org/html/2502.16789v2 |
| **AlphaEval（回测无关多维评估, 2025）** | 多维体检卡蓝本 | 针对「过度依赖单一 IC」的批评，提出可并行、免回测的五维评估：预测力、稳定性、鲁棒性、金融逻辑（可解释性）、多样性。可作给小白的因子体检卡蓝本。 | https://www.arxiv.org/abs/2508.13174 |
| **Open Source Asset Pricing（Chen-Zimmermann）+ Qlib Alpha158/360** | 已知因子先验库 + 增量对照基线 | OSAP 提供 200+ 横截面预测因子的可复现数据/代码（权威先验库）；Qlib Alpha158/360 是工程化算子-因子库与回测/数据基座。共同构成「新挖出的因子相对已知因子是否真有增量」的对照基线。 | https://www.openassetpricing.com/ |

> 编辑判断说明：把 AlphaAgent 称作「最贴近本产品形态的 SOTA」是可辩护的编辑判断而非可证伪事实——它确实是少数把对话式智能体 + 经济假设对齐 + 原创性去重缝在一起的公开工作，但其有效性证据有限（81% 是消融内部 hit ratio 而非外部命中率，见 §7）。

## 3. 关键论文（每条带 URL）

- **101 Formulaic Alphas**（Kakushadze, 2016, Wilmott / arXiv:1601.00991）—— 公开 101 条真实生产用公式因子与算子，定义公式 DSL 事实标准搜索空间。**确证：平均持有期 0.6–6.4 天属实；但据此归类为「中低频、契合本产品」是错的——这是短线/高换手 alpha（论文自陈低相关、与波动率强相关、对换手不敏感的统计套利型），换手/成本/容量约束与中低频差一个量级（见 §7）。**
  https://arxiv.org/pdf/1601.00991

- **The Deflated Sharpe Ratio: Correcting for Selection Bias, Backtest Overfitting and Non-Normality**（Bailey & López de Prado, 2014, J. Portfolio Mgmt / SSRN 2460551）—— 把观察 SR 与「N 次试验下零技能假设的期望最大 SR」比较：E[max]≈(1−γ)Z⁻¹[1−1/N]+γZ⁻¹[1−1/(Ne)]，并用偏度 S、峰度 K、样本长度 T 修正 SR 标准误。**注：DSR 本质是选择偏误/标度门槛修正，假设各 trial 同一零分布、依赖偏度/峰度/有效 N 的点估计——当这些估计本身有噪声（加密短样本尤甚）时判决置信度被高估（见 §7）。**
  https://www.davidhbailey.com/dhbpapers/deflated-sharpe.pdf

- **The Probability of Backtest Overfitting（PBO / CSCV）**（Bailey, Borwein, López de Prado, Zhu / SSRN 2326253）—— 估计「样本内最优配置在样本外排名跌入下半区」的概率；PBO 随配置数增长趋近 1，不论是否存在真实预测力——量化「你试得越多，越可能是过拟合」。
  https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2326253

- **… and the Cross-Section of Expected Returns**（Harvey, Liu, Zhu, 2016, RFS 29(1):5–68 / NBER w20592）—— 在多重检验框架下新因子 t 门槛应升至约 3.0（而非惯例 2.0），给出 1967 至今历史显著性临界值时间序列，允许检验间相关与缺失数据。**重大注记：把 t>3 当作可供小白选择的稳固保守档是错的——其自身引用的 Chen (2022) 明确论证该门槛在发表偏误下统计上「不可识别」（见 §7、§3 末条 Chen 2022）。**
  https://www.nber.org/system/files/working_papers/w20592/w20592.pdf

- **Backtesting（SR haircut 解析框架）**（Harvey & Liu, 2015, J. Portfolio Mgmt 42(1):13–28）—— 反对「一律砍 50% SR」的拍脑袋做法，给出基于多重检验（Bonferroni/Holm/BHY）的 SR haircut 解析框架——同一回测 SR，试验数越多、相关性越低应扣得越狠。Duke 官网提供可复现代码，可直接移植为「SR 折损 / t 门槛」计算件。
  https://people.duke.edu/~charvey/backtesting/

- **Replicating Anomalies**（Hou, Xue, Zhang, 2020, RFS 33(5):2019–2133 / NBER w23394）—— 复制 447 个异象：NYSE 断点 + 市值加权下 64% 在 5% 水平不显著，t>3 时升至 85%；93% 流动性变量失效。悲观派核心证据：因子文献被 p-hacking 严重污染、市场比想象更有效。
  https://www.nber.org/system/files/working_papers/w23394/w23394.pdf

- **Open Source Cross-Sectional Asset Pricing / Publication Bias in Asset Pricing**（Chen & Zimmermann / arXiv:2209.13623）—— 乐观派反证：161 个明确显著因子中 98% 复制出 t>1.96；发表偏误收缩仅约一成多、FDR 个位数、因子样本外持续且彼此弱相关。**注：原文收缩区间是 8–17%（HLZ 基线 13%）、FDR 在 HLZ 基线 6.3%——研究里「10–15%」「<6%」是往有利方向收窄/取整，应按原文标注区间（见 §7）。**
  https://arxiv.org/pdf/2209.13623

- **Do t-Statistic Hurdles Need to be Raised?**（Chen, 2022/2023, arXiv:2204.10275）—— **对抗核查重点补入的关键反驳**：t>3 门槛在统计上「不可识别」——发表偏误下未观测结果须靠外推，控制 FDR 在 5% 的 t 门槛 bootstrap 90% 置信区间横跨 0 到 3.0，标准误宽到「无法判断门槛该升、该不变、还是该降」（原文：raising the t-hurdle may be difficult to justify empirically）。**因此 t>3 不是「另一种合理口径」，而是被其引用的乐观派文献认定为缺乏识别力的数字——把它做成可选档位 = 产品化一个统计上无法支撑的精度幻觉（见 §7、§8）。**
  https://arxiv.org/html/2204.10275

- **A Reality Check for Data Snooping（White, 2000）+ SPA Test（Hansen, 2005）**—— White RC 用 bootstrap 检验「最优策略相对基准是否显著」并控制全体策略；Hansen SPA 修正 RC 的保守性（剔除最不利配置假设）并给 stepwise 扩展。多重检验在交易规则选择上的奠基性工具。
  https://www.researchgate.net/publication/4896389_A_Reality_Check_for_Data_Snooping

- **Is There a Replication Crisis in Finance?**（Jensen, Kelly, Pedersen, 2023, Journal of Finance 78(5)）—— 用贝叶斯/分层模型对 153 个因子在 93 国重估，结论偏乐观：多数因子可复现、加多重检验后大部分仍存活。是与 Hou-Xue-Zhang 对冲的关键文献，凸显「结论依赖方法论选择」。
  https://onlinelibrary.wiley.com/doi/full/10.1111/jofi.13249

- **AlphaAgent: LLM-Driven Alpha Mining with Regularized Exploration**（2025, KDD / arXiv:2502.16789）—— 三智能体闭环 + 三类正则（AST 子树相似度去重 / LLM 经济假设一致性对齐 / 符号长度·参数数·表达式规模复杂度惩罚）对抗 alpha 衰减。**注：「命中率提升 81%」是消融实验里『加因子建模约束 vs 不加』的 hit ratio 对比（0.29 vs 0.16），是相对自身消融基线的内部提升，不是相对其他 SOTA 或实盘命中率（见 §7）。** 坦承未用正式多重检验 / walk-forward——正是本环节要补的缺口。
  https://arxiv.org/html/2502.16789v2

## 4. 机构最佳实践 / 标准

- **SR 11-7 模型风险管理三支柱**（概念合理性 conceptual soundness + 结果分析 outcome analysis + 持续监控，覆盖开发/实现/使用全生命周期）：对自动因子发现的含义——暴力遍历产物不能直接上线，须经与生成器解耦的独立验证层（honest-N/PBO/DSR 守门 + 经济合理性审查 + 上线后监控），全程留痕可审计。**关键延伸：SR 11-7 同样要求「对验证模型本身做验证」——守门器（DSR/PBO/honest-N）自己也是模型、也有模型风险，不能被当作免检的客观真相（见 §7）。**
  https://www.federalreserve.gov/supervisionreg/srletters/sr1107.htm

- **诚实地报告试验数 N + 多重检验披露**：Harvey-Liu-Zhu 与 López de Prado 共同主张——报告业绩时必须同时披露「共试了多少配置 / 有效独立试验 N 是多少」，并据此扣减 SR / 抬高 t 门槛。机构最佳实践是把 N 计入而非隐藏。**注：López de Prado《Backtesting》标准结论是『5 年数据下最多只能试约 45 个独立配置』，且年数越多能容忍的试验数越大——研究原稿『10 年回测 3 次独立试验造假策略』是对此的实质性误述，已在 §7 high 级降权订正。**
  https://people.duke.edu/~charvey/backtesting/

- **有效独立试验数 honest-N 的估计**：候选高度相关时 N_eff << N_actual；López de Prado (2018) 用无监督聚类（ONC/层次聚类）或相关矩阵特征值谱估计有效簇数作为保守 N，避免把 5000 条强相关公式当 5000 次独立试验（否则过度惩罚把真信号也杀掉）。**但聚类引入研究者自由度：簇数对距离度量/linkage/阈值高度敏感，是新的可博弈旋钮（见 §7）。**
  https://en.wikipedia.org/wiki/Deflated_Sharpe_ratio

- **FDR 而非仅 FWER**：因子/规则筛选中，Benjamini-Hochberg（独立或正相关）与更保守的 Benjamini-Yekutieli（任意相关）控制错误发现率，比 Bonferroni 在大规模候选下保留更高功效——适合「几千条公式」量级的筛选。
  https://abfer.org/media/abfer-events-2018/annual-conference/investment-finance/AC18P3001_Anomalies-and-Multiple.pdf

- **经济先验优先于统计显著**：CFA / aiquantclaw 方法论与 AlphaAgent 的「假设对齐」一致——要求每个候选因子先有可陈述的经济/行为学理由再谈统计；纯数据挖掘出的无经济含义表达式应被降权或拒绝（对抗 HARKing）。
  https://arxiv.org/html/2502.16789v2

## 5. 对 QuantBT 这套架构的推荐方向（概念级）

> 概念级方向，不点 file:line、不排实施计划。

1. **把本环节定位为「诚实-N 守门人」而非「挖矿机」**：暴力遍历（gplearn/RL/LLM）只是廉价候选生成器，产品真正的差异化与信任来自不可绕过的统计守门层（honest-N → DSR/PBO/CSCV → Harvey-Liu haircut → FDR(BH/BY)）。生成与守门严格解耦、守门用嵌套 walk-forward OOS、最后一次性裁决。**这与簇 C 的 14/15/16 环节是同一套骨架的下游应用——本环节是「批量候选生成」喂给那套守门器，须复用而非另起炉灶的 N-记账与多重检验逻辑。**

2. **试验预算做成跨会话、不可重置的一等公民**：在对话里持续累计「本因子族至今试了多少配置 / 有效独立试验 N_eff / 扣完多重检验后 SR 折损与 t 门槛」，每次重跑/改参/换 universe 时累加而非清零。这是把「流程即信任」落到本环节的核心机制，也直接回应 SR 11-7 可审计要求。**关键护栏（类比 §8 M17 跟单杠杆护栏曾被中继绕过的教训）：朴素的「跨会话累加计数器」很容易被绕过——用户换 universe、改频率、换数据源、甚至换一个语义等价但 AST 不同的公式都能重置或低估 N。真正需要的是基于因子语义/收益相关性的去重式计数，而非单纯加一个计数器（见 §7）。**

3. **honest-N 用聚类/特征值谱估计，而非字面计数——但如实披露它是可博弈旋钮**：对几千条候选先做相关聚类（ONC/层次聚类）或相关矩阵特征值谱得有效簇数作保守 N，同时展示 N_actual 与 N_eff。**但必须如实标注：簇数对距离度量/linkage/阈值高度敏感，且 N_eff 直接决定 SR 折损——低报簇数就能放水，这同时是防过度惩罚的良方与新的过拟合/博弈入口。应报告对 N 的敏感性区间而非单点，并把聚类口径预注册/锁定于研究开始前（见 §7）。**

4. **经济先验作为前置闸门（对齐本产品「人出意图与经济判断」的定位）**：要求每个候选先挂一条可陈述的经济/行为假设（由用户或 agent 给出），再用类 AlphaAgent 的「假设-描述-公式一致性」打分与 AST 相似度去重；无经济含义或与已知因子（Alpha101/OSAP）高度同构的候选自动降权。这把小白的「经济判断」变成真正起作用的过滤器，而非装饰，并对抗工业化 HARKing。

5. **多维体检卡取代单一 IC 排名（借鉴 AlphaEval）——但每个数字都带不确定性带**：给非技术用户呈现预测力/稳定性/鲁棒性/经济逻辑/多样性 + 换手·成本·容量·样本外衰减的多维卡片，明确标注每一维是独立闸门（IC 高 ≠ 可交易）。**红线：决不能把 PBO/DSR/FDR 包装成「这个因子有多大概率只是运气」的单一确定性数字/绿红灯——这与 Chen (2022)「门槛不可识别」直接冲突，会对非专业用户制造新的虚假精确感与过度信任（见 §7、§8）。通俗翻译可以，但必须同时呈现判决的不确定性区间。IC 0.05–0.1「算强」、>0.15「通常是过拟合信号」只是 Grinold-Kahn 体系的经验区间（rule-of-thumb），不是定律，写进守门逻辑会误伤真实强信号（见 §7）。**

6. **主动呈现学术争议而非伪装客观真相——但门槛本身要带置信区间**：在裁决界面同时给出悲观派（Harvey-Liu-Zhu t>3、Hou-Xue-Zhang）与乐观派（Chen-Zimmermann、Jensen-Kelly-Pedersen）的门槛与口径，让用户理解「结论对方法论敏感」。**但研究主张『让小白在保守/中性档之间选 t 门槛』本身就在兜售精度幻觉——Chen (2022) 证明 FDR 控制所需 t 门槛 90% CI 含 0 到 3.0。诚实做法是展示门槛的置信区间/不确定性带，而非给一个看似客观的数字档位；档位若保留也须预注册/锁定，避免把放水权交给最有动机的用户（见 §7、§8）。** 风险偏好选择契合 D3「实盘仅警告 + 规则停」。

7. **资产分档的门槛与非正态修正，加密线须有可操作细则而非口号**：A股（到 paper）与加密（到 Binance 实盘）用不同的样本长度 T、偏度/峰度修正与有效-N 口径，加密因结构性断点与极端非正态须更高 DSR 门槛，绝不复用 A股临界值。**但「门槛更高」只是口号——加密线需要可操作细则：分叉/上新/退市的结构性断点破坏 DSR 同分布假设；幸存者偏差（已退市/归零币种在多数数据源里根本不存在）让候选池天然向上偏；永续资金费率、交易所停机/插针使偏度峰度极端化到 DSR 的 Cornish-Fisher 型修正可能失效。这些比「不复用 A股临界值」具体得多，直接关系到 Binance 实盘最高风险线（见 §7、§8）。**

8. **严防验证集泄露与前视污染贯穿全程**：守门指标永不进入生成循环的适应度（否则等于对验证集再过拟合一次 = 验证集泄露）；算子时序窗口、universe 成分、停复牌/退市、缺值/dtype 全部 PIT 化（复用项目 M2 经验），把「未来函数自检」作为提交前硬门，否则整批几千条因子全部作废。

## 6. 架构级参考（少量伪代码 / schema 草图，非代码接线）

> 仅示意守门骨架与试验账本形态，**非接线到现有代码**。

```
# 守门管线（生成器与守门器解耦，守门只在最后一次性裁决）
candidates  = generator.run(dsl=Alpha101_ops, prior_required=True)  # gplearn/RL/LLM 仅生成
candidates  = dedup_by_economic_prior(candidates)        # 无经济假设 / 与 OSAP 同构 → 降权或拒
N_actual    = len(candidates)
N_eff       = effective_n(candidates,                    # 聚类/特征值谱，报区间而非单点
                          method="ONC|hierarchical|eigval",
                          locked_config=preregistered)   # 聚类口径预注册，防放水
# 守门指标用嵌套 walk-forward OOS 计算，绝不进入 generator 的 fitness
verdict     = gate(candidates,
                   dsr  = deflated_sharpe(N_eff, T, skew, kurt),
                   pbo  = pbo_cscv(returns_matrix),
                   fdr  = bh_or_by(pvals, dependent=True),
                   haircut = harvey_liu(sr, N_eff))
report      = multidim_card(verdict)   # 5 维 + 换手/成本/容量/衰减，每维独立闸门
```

```yaml
# 试验账本 schema 草图：append-only、跨会话不可重置、去重式计数
trial_ledger:
  research_theme_id: str            # 因子族/主题维度累计，非按 session
  trials:
    - trial_id: str
      timestamp: iso8601
      expr_ast_hash: str            # 语义去重锚点，防换等价公式重置 N
      return_series_corr_cluster: int   # 折算 N_eff 的簇 id
      universe / freq / data_source: str   # 任一变化都累加而非清零
      economic_hypothesis: str|null  # 无 → 前置闸门拒
      gate_outcome: {dsr, pbo, fdr_q, sr_haircut, verdict}
  N_actual: int
  N_eff: {point: int, ci_low: int, ci_high: int}   # 区间而非单点
  threshold_band: {conservative, neutral}           # 预注册/锁定，不可事后调
  gate_model_risk_disclosure: str   # SR 11-7：守门器自身也是模型，须声明局限
```

## 7. 降权 / 争议 / 陷阱（对抗核查结论）

> 以下为对抗核查的原样保留结论（夸大/争议/二手/不可外推/未核验等限定词不删减）。

**【high】「10 年回测 3 次独立试验造假策略」是对原始文献的实质性误述。** Lopez de Prado《Backtesting》的标准结论是：**5 年数据下最多只能试约 45 个独立配置**，否则几乎必然得到样本内 SR=1、样本外 SR=0 的假策略（已核实，people.duke.edu / SSRN 2606462）。**年数越多能容忍的试验数越大，而非越小；10 年应允许更多试验，不是 3 次。** 研究里的「3」疑似从无关的另一例子（Wikipedia DSR 条目：观测 SR*=0.95 需约 3 年日收益才能在 95% 置信度拒绝 H0:SR=0）**串台**来的——那是样本长度，不是「3 次试验造假策略」。这个核心张力的量化锚点是错的，落地前必须按原文订正。

**【high】把 Harvey-Liu-Zhu 的 t>3 当作可供用户选择的稳固保守档，回避了其自身引用的 Chen (2022) 的关键反驳。** Chen (2022, arXiv:2204.10275，已核实摘要) 明确论证 t>3 这个门槛在统计上「不可识别」——发表偏误下未观测结果必须靠外推，控制 FDR 在 5% 的 t 门槛 bootstrap 90% 置信区间横跨 0 到 3.0，标准误宽到「无法判断门槛该升、该不变、还是该降」。也就是说 **t>3 不是「另一种合理口径」，而是其引用的乐观派文献认定为缺乏识别力的数字**。研究把它当作可让用户在「保守/中性档」之间选的稳固锚点，等于把一个被点名为不可识别的阈值产品化。原文核实语句：raising the t-hurdle may be difficult to justify empirically；empirical estimates say little about whether hurdles should be raised, stay the same, or even be lowered。

**【medium】WorldQuant 101「平均持有期 0.6–6.4 天——中低频，契合本产品」分类错误。** 持有期数字 0.6–6.4 天已核实属实（arXiv:1601.00991），但归类为「中低频、契合本产品」是错的。0.6 天是日内/隔夜级别，6.4 天也只是数日级——这是**典型短线/高换手 alpha**（论文自陈低相关、与波动率强相关、对换手不敏感的统计套利型），不是项目定位的中低频。这类因子的换手、成本、容量约束与中低频差一个量级，直接拿 101 当中低频基准会**系统性低估交易成本闸门**，与研究自己列的「换手/成本是独立闸门」自相矛盾。

**【low】Chen-Zimmermann「发表偏误只占 10–15% 收缩、FDR<6%、98%/161」轻微过度精确。** 方向和数量级正确、可作支撑，但：收缩区间原文是 **8–17%**（HLZ 基线模型 13%），不是 10–15%；FDR 在 HLZ 基线是 **6.3%**，写成「<6%」是把临界值往有利方向取整。98%/161（t>1.96）已核实属实（Open Source Cross-Sectional Asset Pricing, CFR 2022）。整体可信，但精确数字应按原文标注区间而非收窄。

**【low】AlphaAgent「命中率提升 81%」语境被省略。** 数字对但语境缺失。已核实（arXiv:2502.16789v2 §4.5）：81% 是**消融实验**里「加了因子建模约束 vs 不加」的 hit ratio 对比（0.29 vs 0.16），hit ratio 定义为「每轮生成的 alpha 中达到超额收益的比例」——是**相对自身消融基线的内部提升，不是相对其他 SOTA 方法的命中率提升，也不是实盘命中率**。作为产品论据引用时若不带消融语境，会被读成更强的外部声称。

**【low】「IC 0.05–0.1 已算强、>0.15 通常是过拟合信号」是 rule-of-thumb 非定律。** 这是 Grinold-Kahn 体系下的经验分级（0.05 moderate / 0.1 good / 0.15 exceptional），属行业经验法则而非科学阈值。业界普遍表述是「>0.15 极罕见、会引发是否过拟合的疑问」，而非「>0.15 通常=过拟合」。把启发式当硬判据写进守门逻辑会**误伤真实强信号**（尤其低频/小样本横截面），应标注为经验区间而非定律。

**【low】多处 arXiv 编号（260x.* / 2602.* / 2603.* / 2512.*）的存疑性质需澄清。** 研究已自我标注存疑，态度正确，但需澄清：检索中独立浮现的 2603.20319（Implementation Risk in Portfolio Backtesting）、2603.20247（AlphaLogics）、2512.12924（Walk-Forward 微结构）等**并非凭空捏造的占位符，而是搜索引擎对 2026 年新预印本的真实返回**（当前为 2026-06）。问题不是「编号是假的」，而是这些 2026 新论文均未逐字核验正文、可能尚未同行评审。**结论：降级理由从「占位/未来日期可疑」改为「新近未经核验、不可作确证引用」更准确。**

**【missing angle / 漏点】以下角度在原研究中缺失或被弱化，列为对抗核查补入：**

- **t 门槛的「不可识别性」本身应作为产品一等公民呈现，而非藏在悲观/乐观对称叙事里。** 任何让小白「在保守/中性档之间选 t 门槛」的 UI 都在兜售一个统计上无法支撑的精度幻觉。诚实做法是展示门槛的置信区间/不确定性带，而不是给一个看似客观的数字档位。

- **DSR/PBO 这整套守门工具自身的局限完全没被批判性对待（逻辑缺口）。** DSR 假设各 trial 服从同一零分布、依赖对偏度/峰度/有效 N 的点估计；当这些估计有噪声（加密短样本尤甚）时 DSR 判决置信度被高估。研究把 DSR/PBO/CSCV 描述为「不可绕过的护城河」，却没说明**守门器自己也有模型风险**（SR 11-7 同样要求对验证模型做验证）。

- **honest-N 的聚类是新的过拟合/博弈入口。** 簇数对距离度量、linkage、阈值高度敏感，等于把一个「可被调松以少扣分」的旋钮交给想过关的用户/agent；尤其当 N_eff 直接决定 SR 折损时，低报簇数就能放水。研究把它列为防过度惩罚良方，却没识别它同时是博弈入口。

- **CPCV vs walk-forward 的证据边界未界定。** 研究（明智地）选了嵌套 walk-forward，但其推崇的 CPCV 类工具优越性主要在 Arian et al. (2024) 的**合成受控环境**（Heston/Merton/regime-switching 模拟）中被证明——是合成数据下的结论，对真实 A股/加密的**可外推性未知**。若后续引入 CPCV 作卖点须明确这一外推边界。

- **交易成本/容量这一「独立闸门」被列出但没给可落地方法，且底层市场冲击模型本身有争议。** 平方根冲击律近年受到对数依赖（arXiv:1412.2152）、线性→平方根 crossover、以及 AQR/Frazzini 实测成本比线性模型小一个量级等多方挑战。对小订单、对加密、对中低频再平衡，套错冲击模型会让容量/成本闸门给出系统性偏差——它本身是一个**开放的、资产相关的建模难题**，不是已解决的独立闸门。

- **加密资产统计守门几乎只停留在「门槛更高」口号，缺可操作细则。** 分叉/上新/退市的结构性断点破坏 DSR 同分布假设；幸存者偏差（已退市/归零币种在多数加密数据源里根本不存在）使候选池天然向上偏；永续资金费率、交易所停机/插针使偏度峰度极端化到 DSR 的 Cornish-Fisher 型修正**可能失效**。这些直接关系到 Binance 实盘这条最高风险线。

- **「试验预算跨会话累计」在工程上如何防绕过未被量化。** 用户换 universe、改频率、换数据源、甚至换一个语义等价但 AST 不同的公式，都会让朴素的 N 计数失真或被刻意重置。需要的是**基于因子语义/收益相关性的去重式计数**，而非仅「跨会话累加一个计数器」——后者很容易被「重开一局」之外更隐蔽的手法绕过。

- **把统计守门包装成「这个因子有多大概率只是运气」的单一数字，本身可能制造新的虚假精确感与过度信任。** 这与 Chen (2022)「门槛不可识别」直接冲突——把不确定性极大的判决渲染成确定性绿/红灯，是一种新的、面向非专业用户的误导风险，应作为**设计红线单列**。

**总评（verdict）：** 这份研究文献骨架扎实、引用诚实度高于平均——核心论文的存在性/版次/会议（Kakushadze 101 持有期 0.6–6.4 天、HLZ t>3、HXZ 64%/85%/93% 流动性、AlphaGen KDD2023、AlphaForge AAAI2025、AlphaAgent 三智能体三正则、Chen-Zimmermann 98%/161 复制）经核实基本全部属实，且主动标注了存疑 arXiv 编号与未逐字核验项，方向判断（生成器/守门器解耦、honest-N、悲观/乐观两派并存）站得住。**但两处 high 级硬伤必须降级订正：**(1)「10 年回测 3 次独立试验造假策略」是对 Lopez de Prado 标准结论（5 年≤45 试验）的实质性误述、方向与量级都错，疑为串台 Wikipedia 的「SR*=0.95 需~3 年样本」例子；(2) 把 HLZ 的 t>3 当作可供用户选择的稳固保守档，回避了 Chen (2022) 的关键反驳——t 门槛在发表偏误下统计上不可识别。另有若干中低级过度精确/语境缺失。**最关键漏角：研究把 DSR/PBO/honest-N 当作「不可绕过的客观护城河」，却没批判性对待守门器自身的模型风险（点估计噪声、聚类自由度成新博弈旋钮、CPCV 优越性仅合成环境验证、把高不确定判决渲染成绿/红灯对小白的误导），而加密实盘线的统计守门仍停在「门槛更高」口号。结论：可作方向性蓝图采纳，但凡涉及具体阈值数字（t>3、3 次试验、IC 0.15、收缩%）的论断在落地前须按原文订正并改为带不确定性区间的呈现，且必须把「守门器也有模型风险、阈值不可识别」作为对用户的一等可见信息，否则会用一个看似客观的统计闸门制造新的过度信任。**

## 8. 开放问题

1. **门槛的不确定性如何在 UI 上诚实呈现而不让小白瘫痪？** Chen (2022) 证明 t 门槛 90% CI 含 0 到 3.0。展示「区间 + 置信度」是诚实的，但非技术用户可能既要简单结论又被不确定性带困惑——「谨慎/标准」档位是把这层不确定性产品化还是掩盖它？档位若保留如何预注册/锁定，使其不成为新的 p-hacking 自由度？

2. **honest-N 的聚类口径如何锁定才能既防过度惩罚又防放水？** 簇数对距离度量/linkage/阈值敏感，且 N_eff 直接决定 SR 折损。是预注册单一口径，还是报告一组口径下的 N_eff 敏感性区间并取最保守？谁有权设定/修改这个口径？

3. **守门器自身的模型风险如何向用户披露而不削弱「流程即信任」？** SR 11-7 要求对验证模型做验证。如何在「这是不可绕过的护城河」与「这套守门工具自己也会错」之间给出诚实但不自我消解的表述？

4. **跨会话去重式 N 计数的语义锚点怎么定？** AST hash 能挡「等价公式换写」吗（同一经济含义、不同表达式树会有不同 hash）？收益序列相关聚类是否更稳健？换 universe/频率/数据源时 N 该如何累加——全部累加是否会过度惩罚合理的稳健性检验？

5. **加密线的 DSR 偏度/峰度修正在 T 极小时如何避免「披着严谨外衣的虚假 p 值」？** 山寨/早期 Binance 样本极短 + 幸存者偏差 + 结构性断点 + 资金费率，何时应直接判定「样本不足以做统计裁决」而非强行给一个失真的 DSR？

6. **市场冲击/容量闸门用哪个模型？** 平方根律存在 AQR/Frazzini 实测争议与对数/线性替代；对中低频 A股（含涨跌停/停牌/印花税）与加密（滑点/资金费率）分别套什么冲击模型才不至系统性偏差？这是开放建模难题而非已解问题。

7. **若引入 CPCV 作卖点，如何标注其优越性仅在合成环境（Heston/Merton）验证、对真实低频市场可外推性未知的边界？**

## 9. 参考文献（URL）

- Kakushadze, 101 Formulaic Alphas (2016) — https://arxiv.org/pdf/1601.00991
- gplearn — https://github.com/trevorstephens/gplearn
- AlphaGen (RL-MLDM) — https://github.com/RL-MLDM/alphagen/
- AlphaForge (AAAI 2025) — https://arxiv.org/abs/2406.18394
- AutoAlpha（二手/未逐字核验）— https://arxiv.org/pdf/2002.08245
- AlphaAgent (KDD 2025) — https://arxiv.org/html/2502.16789v2
- AlphaEval (2025) — https://www.arxiv.org/abs/2508.13174 ；开源实现 https://github.com/LeoDingggg/AlphaEval
- Open Source Asset Pricing (Chen-Zimmermann) — https://www.openassetpricing.com/
- Microsoft Qlib (Alpha158/360) — https://github.com/microsoft/qlib
- pypbo (PBO/CSCV 参考实现) — https://github.com/esvhd/pypbo
- Harvey & Liu, Backtesting（含 Duke 官方 haircut/多重检验代码）— https://people.duke.edu/~charvey/backtesting/
- Bailey & López de Prado, Deflated Sharpe Ratio (2014) — https://www.davidhbailey.com/dhbpapers/deflated-sharpe.pdf
- Bailey, Borwein, López de Prado, Zhu, Probability of Backtest Overfitting — https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2326253
- López de Prado, Backtesting（5 年≤45 独立配置）— https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2606462
- Harvey, Liu, Zhu (2016, RFS / NBER w20592) — https://www.nber.org/system/files/working_papers/w20592/w20592.pdf
- Hou, Xue, Zhang, Replicating Anomalies (2020, NBER w23394) — https://www.nber.org/system/files/working_papers/w23394/w23394.pdf
- Chen & Zimmermann, Publication Bias (arXiv:2209.13623) — https://arxiv.org/pdf/2209.13623
- Chen (2022/2023), Do t-Statistic Hurdles Need to be Raised? (arXiv:2204.10275) — https://arxiv.org/html/2204.10275
- White (2000), A Reality Check for Data Snooping — https://www.researchgate.net/publication/4896389_A_Reality_Check_for_Data_Snooping
- Jensen, Kelly, Pedersen (2023), Is There a Replication Crisis in Finance? — https://onlinelibrary.wiley.com/doi/full/10.1111/jofi.13249
- Benjamini-Hochberg / Benjamini-Yekutieli FDR 综述（Harvey-Liu）— https://abfer.org/media/abfer-events-2018/annual-conference/investment-finance/AC18P3001_Anomalies-and-Multiple.pdf
- SR 11-7 Supervisory Guidance on Model Risk Management — https://www.federalreserve.gov/supervisionreg/srletters/sr1107.htm
- Deflated Sharpe Ratio（Wikipedia，含 N_eff/选择偏误说明）— https://en.wikipedia.org/wiki/Deflated_Sharpe_ratio
- Arian, Norouzi, Seco (2024), CPCV 合成环境评估 — https://www.sciencedirect.com/science/article/abs/pii/S0950705124011110
- 市场冲击对数依赖（arXiv:1412.2152）— https://arxiv.org/pdf/1412.2152
- 已撤稿示例 arXiv 2512.11913（本研究未引用，雷区空命中）— https://arxiv.org/abs/2512.11913
