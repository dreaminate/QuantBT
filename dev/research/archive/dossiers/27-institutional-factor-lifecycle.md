# 27 · 机构级因子生命周期（衰减/拥挤/容量/因子族/监控）

> 机构级 Agent OS 成品环节深挖 · 全程 Opus 4.8 · 对抗式核查已降权 · 重心=前沿研究+概念级推荐 · 不含 file:line 代码接线
> 簇 E

## 1. 一句话定位

把「因子」当成**有生命周期、会衰减、会拥挤、有容量上限的独立资产**来治理——而不是策略附属的一段代码。核心是给三库（A股到 paper / 加密到 Binance 实盘 / 通用）各维护一张**因子族登记表（factor registry）**，每个因子是带状态机（候选→纸面验证→影子→在产→冻结/减配→退役）的一等实体；用一组**晋升/退役闸门**判定它能否推进或必须退役。但本环节的本质张力是：**每一道闸门背后都踩着一场尚未和解的学术战争**——衰减的成因（数据挖掘偏差 vs 投资者学习/套利）、净收益是否≈0、要不要做 factor timing、t 门槛该多高——所以闸门必须诚实地把「已确证」与「争议/外推」标进状态里，输出「把握度区间 + 经济语言解释」，而**不是给小白一条确定性红线**。「流程即信任」在这里兑现为：每张因子状态卡都能回答「为什么这个看起来很强的因子，我们只给它打折用 / 把它冻结 / 让它退役」。

> 与本仓其它环节的分工：晋升闸门的统计学机制（DSR/PBO/honest-N/多重检验）已在 §14（overfitting）、§15（multiple-testing honest-N）、§16（CPCV purged）深挖，本环节**不重复造轮子**，只把它们作为「生命周期闸门」的一关引用；容量/TCA/冲击在 §18 深挖，本环节只接其结论；治理骨架（SR 11-7 / NIST AI RMF）在 §22 深挖，本环节只做「因子状态机 1:1 映射」的引申。本环节的独有增量是：**衰减作为可观测生命周期事件 + 拥挤作为横向风险层 + 退役/去重作为一等流程 + 三库因子族不可共用**。

## 2. 前沿 SOTA 与代表系统

下表覆盖「拥挤监测 → 因子风险/正交化 → 容量与净收益的买方实务 → factor timing 的对立两极」四层。**注意：sota_systems 里 AQR 与 Research Affiliates 在容量、净收益、factor timing 三件事上立场针锋相对，必须并陈，不能只引一方当定论。**

| 系统 | 角色 | 要点 | URL |
|---|---|---|---|
| **MSCI Integrated Factor Crowding Model** | 拥挤变成可监控量的事实标准范式 | 五信号合成相对拥挤分：估值价差（valuation spread）/做空兴趣价差（short-interest spread）/多空组合成对相关（pairwise correlation）/因子波动（factor volatility）/近期因子表现（trailing performance）；各信号 z-score 化后合成。**注**：白皮书未公开精确权重（等权合成属常规推断）；并非纯相对——MSCI 自家材料给出整合分约 ±1 即视为显著拥挤/不拥挤的**事实参考阈值**（见 §7，原研究略夸大其「无绝对阈值」）。 | https://www.msci.com/research-and-insights/blog-post/eyeing-the-crowds-from-multiple-perspectives |
| **Barra (MSCI) USE4 / Axioma (SimCorp) 因子风险模型** | 因子族/正交化增量 + 组合风险归因的工业参照 | 横截面回归估风格因子暴露，提供因子协方差矩阵 + 特异风险；内置因子正交化（如 Non-Linear Size 对 Size 正交）。Axioma 提供 fundamental 与 statistical(PCA) 两类、市值平方根加权 WLS。可作「相对既有因子族的正交化增量贡献」的概念参照。 | https://www.top1000funds.com/wp-content/uploads/2011/09/USE4_Methodology_Notes_August_2011.pdf |
| **AQR 因子框架（Trading Costs / Factor Timing / 复制危机）** | 买方「乐观锚」+「保守择时」立场 | 用近万亿（实为约 1.7 万亿美元）真实成交估容量（成本远低于学界估计）、主张 factor timing 极难（只能 sin a little）、并以贝叶斯方法论证因子可复制。**注**：低成本/大容量结论建立在 AQR 自家成交上，带自选择/最优执行偏差，且与平方根冲击律的非线性约束冲突——不可直接外推为通用容量上限（见 §7）。 | https://www.aqr.com/Insights/Research/Working-Paper/Trading-Costs-of-Asset-Pricing-Anomalies |
| **Research Affiliates 因子择时/估值框架** | factor timing「正方」+ 拥挤崩盘警示 | 主张用估值价差监测因子是否昂贵、警示 revaluation alpha 反转与 smart beta 拥挤崩盘；其三步因子筛选（只收顶刊长期辩论过的因子 → 剔除跨子期/跨国不稳健者 → 评估实施成本/容量/拥挤）是成熟的「晋升闸门」买方模板。与 AQR 形成必须并陈的争议双方。 | https://www.researchaffiliates.com/publications/articles/595-forecasting-factor-and-smart-beta-returns |

## 3. 关键论文（每条带 URL）

- **Does Academic Research Destroy Stock Return Predictability?**（McLean & Pontiff, 2016, Journal of Finance 71(1):5-32）—— 本领域**奠基且引用最广的确证实证**：约 97 个已发表横截面预测因子，组合收益**样本外平均降 26%、发表后平均降 58%**；26% 视为数据挖掘偏差上界，额外 ~32pp 归因投资者学习/套利。发表后交易量/换手/波动/做空兴趣上升，且与其它已发表因子**共动性上升**（=拥挤直接证据）；高样本内收益、低套利成本的因子衰减更猛。直接论证「被发表」应触发预期收益下调。
  https://onlinelibrary.wiley.com/doi/abs/10.1111/jofi.12365

- **When Anomalies Are Publicized Broadly, Do Institutions Trade Accordingly?**（Calluzzo, Moneta & Topaloglu, 2019, Management Science 65(10):4555-4574）—— 用机构持仓数据为衰减补上**中间机制**：发表 + 数据可得后机构（尤其高换手对冲基金）加仓套利，并把加仓直接关联到发表后收益衰减；套利成本高的因子衰减更少（限制套利保护错误定价）。把「拥挤→衰减」从相关性推进到机制证据。
  https://afajof.org/management/viewp.php?n=46984

- **Zeroing In on the Expected Returns of Anomalies**（Chen & Velikov, 2023, JFQA 58(3):968-1004）—— 在 204 个异象上同时扣有效买卖价差 + 发表后效应 + 现代交易技术后，平均异象净期望收益仅 **~4 bps/月**，最强者扣数据挖掘后 ~10 bps，组合方法 ~20 bps。**强（但有争议）结论**：扣完成本后绝大多数因子可投资 alpha 接近零。**注**：依赖其成本/数据挖掘假设，FIM 真实成交数据给出明显更乐观的反例（见 §7）。
  https://papers.ssrn.com/sol3/papers.cfm?abstract_id=3073681

- **Trading Costs of Asset Pricing Anomalies**（Frazzini, Israel & Moskowitz, 2018 wp, AQR）—— 用约 1.7 万亿美元真实机构成交（19 个发达市场，1998-2011）估容量：真实交易成本不到学界估计的 1/10，可承载规模大一个数量级；价值/动量比规模更可承载，短期反转最受成本约束。与 Chen-Velikov 形成关于「净收益是否≈0」的核心分歧。**注**：基于 AQR 自家成交，含自选择/最优执行偏差；平方根冲击律对「大一个数量级」的线性外推构成独立反驳（见 §7）。
  https://www.aqr.com/Insights/Research/Working-Paper/Trading-Costs-of-Asset-Pricing-Anomalies

- **Replicating Anomalies**（Hou, Xue & Zhang, 2020, RFS 33(5):2019-2133）—— 复制 447 个异象：**64% 在 5% 水平不显著**；用 t>3 门槛后 **85% 不显著**（流动性类 **93% 阵亡**）。代表「复制危机」悲观派。**注**：这组数字是 NYSE 断点 + 市值加权 + 原始收益的**方法学产物**，非中性事实，JKP 已从方法学层面反驳（市值加权淹没微盘信号、原始收益混淆风险溢价与 alpha）；不应据此搭一个市值加权 + t>3 的固化闸门（见 §7）。
  https://www.nber.org/system/files/working_papers/w23394/w23394.pdf

- **Is There a Replication Crisis in Finance?**（Jensen, Kelly & Pedersen, 2023, Journal of Finance 78(5):2465-2518）—— 对悲观派的**强力反驳**：用贝叶斯分层模型证明多数因子可复制、可聚成 13 个主题（多数进切线组合）、在 93 国新数据样本外有效，且「因子数量多本身**强化**而非削弱证据」。晋升闸门须同时尊重多重检验与跨市场样本外，而非简单粗暴抬 t 门槛。
  https://onlinelibrary.wiley.com/doi/full/10.1111/jofi.13249

- **… and the Cross-Section of Expected Returns**（Harvey, Liu & Zhu, 2016, RFS 29(1):5-68）—— 提出因子显著性应满足 **t>3.0**（而非 1.96）以应对数百因子的多重检验。**注**：t>3 门槛本身有实质争议——Chen 一派论证「发表偏误使未达门槛结果不可观测 → t-hurdle 弱识别、抬高门槛经验上难证成」，是对 t>3 闸门**釜底抽薪的第三方立场**，原研究遗漏；不可把 t>3 硬编进闸门（见 §7、§3 末两条）。
  https://academic.oup.com/rfs/article/29/1/5/1843824

- **Do t-Statistic Hurdles Need to be Raised? / Publication Bias and the Cross-Section of Stock Returns**（Chen, 2023 arXiv 2204.10275；Chen & Zimmermann）—— **对抗核查补入的关键第三方立场**：发表偏误使失败结果系统性不可观测，t-hurdle **弱识别（weakly identified，无法从数据可靠估出）**；其 Open Source Asset Pricing 数据显示「原文清晰显著」的 161 个因子中 **98% 复现 t>1.96**。直接质疑「t>3 是必须抬高的门槛」这一框架。**注**：Chen 真正证明的是「门槛不可被可靠抬高」，并不等于「门槛应是 1.96」——同为弱可识别（见 §15 已对此做对称降权）。
  https://arxiv.org/pdf/2204.10275

- **The Deflated Sharpe Ratio**（Bailey & López de Prado, 2014, JPM 40(5):94-107）—— 按尝试次数 N、收益偏度/峰度对夏普「打折」，回答「这个夏普在试了 N 次后是否仍显著」。是把「honest-N + 过拟合校正」变成可计算闸门指标的核心方法之一。**注**：DSR 是**标度/选择偏差修正**，不修复系统性偏差、也无法独立验证 N 是否诚实（garbage-N in, garbage-DSR out）；其有效性完全取决于人喂进去的 N——应定位为「多指标之一」而非自动兜底（见 §7、§14、§15）。
  https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2460551

- **The Probability of Backtest Overfitting (PBO via CSCV)**（Bailey, Borwein, López de Prado & Zhu, 2017, Journal of Computational Finance）—— 用组合对称交叉验证（CSCV）估「样本内最优策略在样本外跑输中位数的概率」，模型无关、非参数；与 DSR 互补。**注**：CPCV/CSCV 相对 walk-forward 的优势仅在**合成受控环境**被证明（2024 ScienceDirect），walk-forward 仍是真实交易模拟工业标准；PBO 本身对前视偏差/数据泄露/样本未覆盖的 regime **完全盲**——这恰是 A股/加密最易踩的坑（见 §7、§16）。
  https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2326253

- **What Happened to the Quants in August 2007?**（Khandani & Lo, 2011, Journal of Financial Markets 14(1):1-46）—— 拥挤尾部风险的教科书案例：相似构造的量化市场中性组合因某基金强平触发**连锁去杠杆与踩踏**，多个因子同周巨亏。证明拥挤风险不是缓慢均值回归而是「相似组合**同时反转**的流动性事件」，监控须能预警群体性协同拥挤而非仅单因子均值回归。
  http://web.mit.edu/~alo/www/Papers/august07b_2.pdf

- **Contrarian Factor Timing is Deceptively Difficult**（Asness, Chandra, Ilmanen & Israel, 2017, JPM Special Issue）—— AQR 对 factor timing 的代表性反方：价值类择时与价值因子本身高度重叠、长短组合换手高使长期可预测性更弱、无稳健证据表明估值择时能跑赢。结论「sin a little」（只能极轻度择时）。支撑「默认做离散生命周期决策而非连续 timing」。
  https://www.aqr.com/Insights/Research/Journal-Article/Contrarian-Factor-Timing-is-Deceptively-Difficult

- **How Can 'Smart Beta' Go Horribly Wrong? / Forecasting Factor Returns**（Arnott, Beck, Kalesnik & West, 2016, Research Affiliates）—— factor timing「正方」：近期因子收益被估值上行（revaluation alpha）虚高、至少同样可能反转；性能追逐 + 拥挤可致 smart beta 崩盘；历史外推预测因子收益「比无用更糟」。是把拥挤/估值价差作退役护栏信号的概念来源（须与 AQR 反方并陈）。
  https://www.researchaffiliates.com/insights/publications/articles/442_how_can_smart_beta_go_horribly_wrong

- **Factor Momentum and the Momentum Factor**（Ehsani & Linnainmaa, 2022, Journal of Finance 77(3):1877-1919）—— 因子收益在一阶滞后上显著正自相关（因子动量），个股动量很大程度源于因子动量；但效应过去五十年平均偏弱。提示因子状态本身有短期持续性，可纳入监控时序特征，但不可过度依赖。
  https://onlinelibrary.wiley.com/doi/abs/10.1111/jofi.13131

- **Common Risk Factors in Cryptocurrency**（Liu, Tsyvinski & Wu, 2022, Journal of Finance 77(2):1133-1177）—— 加密有自己的三因子（市场/规模/动量），捕获横截面预期收益。意味着三库不能共用同一套因子族定义与拥挤基线，加密因子衰减/容量须独立校准。**注**：LTW 实际是把股票市场的价量类预测变量逐一构造出加密对应物、发现 size/momentum「概念」在加密同样成立——更准确表述是「加密有自有因子载荷与基线、需独立校准」，而非「股票因子概念不适用」（原研究表述略强于原文，见 §7）。
  https://onlinelibrary.wiley.com/doi/abs/10.1111/jofi.13119

- **Forking Paths in Financial Economics / The Garden of Forking Paths**（Gelman & Loken, 2013；Coqueret, 2024, arXiv:2401.08606）—— 即便不刻意 p-hacking，研究者自由度（变量构造/样本/过滤的分叉）也会膨胀有效检验数 → 直接警示 DSR 里的 honest-N 极易被低估、须 HITL 把关。**注**：finance arXiv 工作论文称用 paths 而非 bootstrap 会把显著阈值从 ~4.5 抬到 ~8.2——**此具体数字为单篇未充分复现的二手数据，谨慎对待，不应当定论**（见 §7）。
  https://arxiv.org/abs/2401.08606

## 4. 机构最佳实践 / 标准

- **SR 11-7 模型生命周期治理（开发→实施→持续监控→变更管理→退役/decommissioning 五段）**：要求模型清册（inventory）、独立验证、结果分析（含 back-testing）、以及「不再适用即主动退役」的明确触发流程。几乎可 1:1 映射为因子状态机的状态、闸门与退役条件——**退役是一等公民而非事后清理**。**注**：「因子状态机对应 SR 11-7」是本研究的**引申解读**，SR 11-7 原文针对模型不针对因子（§22 已就 SR 11-7 一手文件深挖），应以「可借鉴的治理框架」呈现，不当成监管要求。
  https://www.federalreserve.gov/supervisionreg/srletters/sr1107.htm

- **NIST AI RMF 四功能 GOVERN/MAP/MEASURE/MANAGE + 持续监控回路**：GOVERN 建风险文化与清册、MAP 界定用例与数据血缘、MEASURE 定评估/阈值/owner、MANAGE 做持续处置与事件响应。给「agent 出工程、人出判断」的治理骨架（对应 HITL 闸门）。
  https://www.nist.gov/itl/ai-risk-management-framework

- **MSCI 五信号拥挤监测**（估值价差/做空兴趣价差/成对相关/因子波动/近期表现）合成相对拥挤分，按历史分位 + ±1 参考阈值预警因子拥挤与潜在反转。是把拥挤变成可监控量、纳入退役护栏的事实标准范式。**注**：精确权重未公开（合成方式属推断）。
  https://www.msci.com/research-and-insights/blog-post/eyeing-the-crowds-from-multiple-perspectives

- **Research Affiliates 三步因子筛选**：①只收在顶刊经长期辩论/检验的因子 ②剔除跨子期/跨国不稳健或不显著者 ③评估实施成本/容量/拥挤。是「晋升闸门」的成熟买方实务模板，强调「不会有多少因子能通过」。
  https://www.researchaffiliates.com/en_us/publications/journal-papers/373_a_framework_for_assessing_factors_and_implementing_smart_beta_strategies.html

- **FTSE Russell 指数构造实务**：按因子衰减速度设定再平衡频率（动量衰减最快需高频再平衡，规模/低波/流动性较慢）。提示状态机的「再校准/监控频率」应按因子半衰期**分层**，而非一刀切。
  https://www.lseg.com/content/dam/ftse-russell/en_us/documents/other/factor-exposures-of-smart-beta-indexes.pdf

**开源工具 / 校准基线：**

- **Open Source Asset Pricing（Chen & Zimmermann, OpenSourceAP/CrossSection）**——开源复现约 200+（文档称 319 候选、161 清晰显著）横截面股票因子的信号 + 多空组合数据 + 代码；复现 t 值对原始 t 值回归斜率 **0.88、R² 82%**。可作通用库「已知因子动物园」基线与正交化/增量检验对照集。**注**：同一批作者也是 t>3 闸门最直接的质疑方（见 §7）。 https://github.com/OpenSourceAP/CrossSection
- **Chen-Velikov 复制代码（velikov-mihail/Chen-Velikov）**——复现 204 异象扣交易成本 + 发表后效应后的净收益，可作「净收益/容量闸门」的成本扣减方法学参照。 https://github.com/velikov-mihail/Chen-Velikov
- **alphalens（及社区维护 alphalens-reloaded）**——分位组合收益、IC（信息系数）及其衰减（IC decay/turnover）、换手与最大回撤分析。可直接产出 IC、IC 半衰期、换手等监控指标。 https://github.com/quantopian/alphalens
- **PBO / CSCV 实现（CRAN `pbo` 包 + López de Prado 示例代码）**——CSCV 估 PBO 与 DSR 计算的现成算法骨架。 https://cran.r-project.org/web/packages/pbo/readme/README.html

## 5. 对 QuantBT 这套架构的推荐方向（概念级）

> 概念级方向，不点 file:line、不排实施计划。

1. **把因子建模为「有生命周期的独立资产」而非策略附属物**：三库（A股/加密/通用）各维护一张因子族登记表，每个因子是带状态、owner、来源、honest-N（所有试过的变体计数，见 §15）、半衰期、容量估计、拥挤分、与既有因子族正交化增量贡献的**一等实体**。离散状态机（候选→纸面验证→影子运行→在产→冻结/减配→退役）对标 SR 11-7 五段（§22），**退役是一等流程而非事后清理**。

2. **「被发表/被广泛知晓」作为可观测生命周期事件，触发预期收益下调（而非维持）**：依据 McLean-Pontiff（发表后 −58%）与 Calluzzo 等的机构套利机制，任何来源是公开学术/广为人知异象的因子，默认在预期收益上打折（样本外 ~26%、若已广泛交易再加折），并在状态卡显式标注「此为已知公开因子，衰减预期已内置」。让小白看到「为什么这个看似很强的因子我们只给它打折用」。**关键**：衰减是**持续过程而非一次性折扣**——高样本内收益因子衰减更猛（高收益因子最该被怀疑而非最该上线），系统应持续重估而非上线时打一次折就锁定。对外部引入因子（如来自 aiquantclaw 方法论的公开因子）默认套用此折扣。

3. **晋升闸门做成「多关卡且与争议并陈」，输出区间而非二值**：①IC 与 IC 半衰期（alphalens 范式）②honest-N 校正后的 DSR + PBO/CSCV（把「试了多少次」诚实计入，见 §14/§15；这是**最易作弊处**，N 必须 HITL 显式确认）③相对既有因子族的正交化增量 t/增量夏普（只有边际新信息才放行，防因子族冗余）④跨子期/跨市场样本外。**关键护栏：t 门槛不可硬编为 t>3**——必须把 HLZ（t>3）、Chen-Zimmermann（t-hurdle 弱识别、不可靠抬高）、JKP（因子族互相强化）这组**未和解证据**翻译成「通过的把握度区间 + 经济语言解释」，输出「谨慎/标准/宽松」三档及其统计含义，而非单点裁决。档位须**预注册/锁定**于研究开始前，防换档 p-hacking（与 §15 一致）。

4. **拥挤监控做成独立的横向风险层，且区分「缓慢均值回归」与「协同踩踏」两类风险**：借 MSCI 五信号（估值价差/做空兴趣价差/成对相关/因子波动/近期表现）做单因子拥挤分，**按库可得数据降级**（加密多半只能用价格类信号）；另叠一层跨因子/跨策略的协同拥挤预警（Khandani-Lo 教训：相似组合的同时反转），触发「冻结/减配」护栏。**拥挤分上行 → 自动建议降低该因子敞口或进入观察，而非自动加减仓**（保守单向护栏，不做激进双向择时）。

5. **容量/净收益闸门必须按库分别校准、用真实成交而非学术毛收益**：并陈 Chen-Velikov（净收益≈0 的悲观锚）与 FIM（成本远低、容量大的乐观锚），让系统对每个因子给出「净收益**区间**」。A股（到 paper）用纸面/历史成本模型 + A股摩擦（印花税/涨跌停/停牌）；加密（到 Binance 实盘）用真实滑点/费率/资金费率回灌校准（接 §18 TCA/容量的结论）。短期反转类因子默认标「低容量、慎用」。**关键披露**：FIM 的乐观锚带 AQR 自家执行的自选择偏差，且容量随规模是**凹增**（平方根冲击律）而非线性——状态卡须显式标注这两条对其外推性的限制（见 §7），不能用学术毛收益拍板上线。

6. **对 factor timing 采取「保守默认 + 可解释例外」**：架构默认做离散生命周期决策（晋升/冻结/退役）而非连续择时（尊重 Asness「sin a little」）；把估值价差/拥挤分仅用作「减配/冻结/退役」的**单向护栏信号**。若用户（经济学者）坚持要轻度估值择时，把 Arnott vs Asness 的争议作为 **HITL 决策卡**显式呈现，让人出经济判断、agent 只执行并记录理由（对应 D3：实盘 agent 仅警告 + 规则停）。

7. **加密库因子族与拥挤基线必须独立、不可与股票共用**：依据 Liu-Tsyvinski-Wu，加密用其自有市场/规模/动量族；承认加密拥挤数据（做空兴趣、机构持仓、估值）稀疏，五信号拥挤模型在加密上显式**降级为可得信号子集**，并在状态卡标注「加密拥挤信号置信度较低」。**更硬的现实**（见 §8）：加密缺可靠做空兴趣/机构持仓/估值数据，且交易所自成交/wash trading 污染量价信号——「加密拥挤分」可能根本达不到可用于「冻结/减配」护栏的置信度，而不仅是「置信度较低」。

8. **HITL 把关点对齐 NIST AI RMF 与「流程即信任」**：honest-N 的诚实计数、因子退役的最终拍板、factor timing 例外、「公开因子衰减折扣」的设定，都设为人（出意图/经济判断）必过的闸门；agent 出全部统计工程与解释，**但不得自行宣称 N 的诚实性或自动批准退役/择时**——把「统计学家会作弊的地方」（honest-N、档位选择）交给人，把「人算不动的地方」（聚类、bootstrap、IC 衰减估计）交给 agent。

## 6. 架构级参考（少量伪代码 / schema 草图，非代码接线）

> 示意，非接线到现有代码。统计闸门细节（DSR/PBO/N_eff）见 §14/§15/§16；此处只示意「生命周期治理」这一层独有的 schema。

**因子族登记表（每库一张，因子是一等实体）：**

```
factor_registry(
  factor_id        text,
  library          text,          -- a_share | crypto | universal（三库不共用因子族定义/拥挤基线）
  family           text,          -- 主题聚类：value/momentum/size/...（加密用自有族，见 §5.7）
  state            text,          -- candidate | paper_verified | shadow | live | frozen_derisk | retired
  owner            text,          -- HITL 责任人（退役/择时例外的最终拍板人）
  provenance       text,          -- discovered_internal | public_known（=触发衰减折扣）
  honest_n         int,           -- 所有试过的变体计数；HITL 显式确认（见 §15），不可由 agent 自称诚实
  half_life_est    interval,      -- 半衰期 → 决定再校准/监控频率（FTSE Russell：动量衰减最快）
  capacity_range   numrange,      -- 净收益区间端点：Chen-Velikov 悲观锚 ↔ FIM 乐观锚（见 §18）
  crowding_score   numeric,       -- MSCI 五信号合成（按库降级）；加密标 confidence_low
  orthogonal_gain  numeric,       -- 相对既有族的增量 t/增量夏普；冗余则不放行
  decay_discount   numeric,       -- public_known 因子的预期收益折扣，持续重估非一次性
  created_at       timestamptz,
  retired_at       timestamptz,
  retire_reason    text           -- 退役留痕，append-only
)
```

**晋升闸门（多关卡 + 三档预注册 + 输出区间，非二值）：**

```yaml
gate: promote_candidate_to_paper
preregistered:
  threshold_tier: standard          # 谨慎/标准/宽松三档须研究开始前锁定，防换档 p-hacking
checks:
  - rule: ic_and_half_life(alphalens)
  - rule: dsr_and_pbo(honest_n_HITL_confirmed)     # honest-N 见 §15；DSR/PBO 见 §14
  - rule: orthogonal_increment(factor_family) > min_marginal_signal
  - rule: out_of_sample(cross_subperiod, cross_market)
output: confidence_interval          # 输出"通过的把握度区间"而非 pass/fail
disclosures:                          # 不可关闭，随判定呈现给小白
  - "t 门槛非铁律：HLZ t>3 / Chen 弱识别 / JKP 因子族强化 三派未和解，门槛不硬编"
  - "净收益按真实成本估，毛收益≠可投资 alpha；短期反转默认低容量"
  - "本闸门只管统计+成本显著性，未碰非平稳/regime shift（OOS 失效主因）"
```

**拥挤监控（横向风险层，区分缓慢回归 vs 协同踩踏）：**

```
# 单因子拥挤分（按库可得信号降级）
signals = {valuation_spread, short_interest_spread, pairwise_corr, factor_vol, trailing_perf}
available = signals ∩ library_available_signals    # 加密多半只剩 price-based 子集
crowding_score = combine(zscore(s) for s in available)   # 权重未公开 → 等权推断
# MSCI 自家 ±1 为事实参考阈值（非纯相对）

# 跨因子协同拥挤（Khandani-Lo 2007 教训：相似组合同时反转）
co_crowd = pairwise_corr_across_live_factors_and_strategies()
if co_crowd > regime_threshold:
    raise alert("协同拥挤踩踏风险 → 建议冻结/减配")   # 单向护栏，不自动加减仓
```

**退役 + 去重闭环（一等流程，防因子动物园内部复活）：**

```
# 因子若衰减/拥挤触发退役，须有去重判据，否则会以变体形式被"重新发现"、honest-N 失真
def is_same_factor(new_candidate, retired_factor):
    # 操作定义（开放问题，见 §8）：正交化残差相关阈值？同主题聚类？
    resid_corr = corr(orthogonalize(new, against=retired), retired.returns)
    return resid_corr > dedup_threshold     # 阈值本身需 HITL/预注册，避免成为新自由度
```

## 7. 降权 / 争议 / 陷阱（对抗核查结论）

> 以下限定词（夸大/争议/撤稿/二手/不可外推/单源/弱识别/方法学产物/自选择偏差/选择性引用 等）**原样保留**，凡涉「已验证/已确证/最终裁决/既定标准/无绝对阈值」的强确定性措辞均已按对抗核查降级；任何对用户的承诺或文案，必须采用降级后的表述。
>
> **总体核实结论（verdict 摘要）**：研究**总体可信、诚实度高于一般稿**——所有可核实关键数字均准确（McLean-Pontiff 26%/58%、Chen-Velikov 4/10/20 bps、HXZ 64%/85%/93%、OSAP 319/161/slope 0.88/R² 82%、Ehsani-Linnainmaa 6bps/51bps、Calluzzo-Moneta-Topaloglu Mgmt Sci 65(10) 14 异象），引用与期刊基本无误；且主动规避雷区（forking-paths 4.5→8.2 标为「单篇 arXiv 未充分复现二手数字」、MSCI 五信号权重标为「推断」、Chen-Velikov 净收益≈0 标为「有 FIM 反例的争议结论」，全程未引用已撤回的 arXiv 2512.11913）。**不存在伪造或重大失实，真正的问题集中在 framing 失衡而非夸大**。

- **【high · framing 失衡 / 被第三方立场釜底抽薪】「把 Harvey-Liu-Zhu 的 t>3.0 当作『honest-N 多重检验校正的学术起点』，直接用来抬高晋升闸门显著性门槛」**——这是研究里最实质的 framing 失衡。t>3.0 阈值本身**有争议**，而争议方恰恰是研究在开源工具里当作「因子族数据骨架」推荐的 **Chen-Zimmermann**。已核实：Chen-Zimmermann（Open Source Asset Pricing）显示「原文清晰显著」的 161 个因子里 **98% 复现 t>1.96**；Chen《Do t-Statistic Hurdles Need to be Raised?》（arXiv 2204.10275）明确论证「**抬高 t-hurdle 在经验上难以证成**」——因发表偏误使未达门槛结果不可观测，t-hurdle 是 **weakly identified（弱识别，无法从数据可靠估出）**。研究把 t>3 当「起点」、把 JKP 当「另一端」，却**完全漏掉**「t-hurdle 在发表偏误下不可识别」这一对 t>3 闸门釜底抽薪的第三方立场。**把 t>3 硬编进闸门有把一个未解的学术阵营之见当成系统规则的风险——文案禁止把 t>3 当确定红线。**
  https://arxiv.org/pdf/2204.10275

- **【medium · 方法学产物当中性事实 methodological_artifact】「Hou-Xue-Zhang 的『64% 在 5% 不显著、t>3 时 85% 阵亡、流动性类 93%』被当作复制危机的确证事实陈述」**——数字本身已核实**准确**，但它们是 HXZ 特定方法选择（**NYSE 断点 + 市值加权 + 原始收益**）的产物，**不是中性事实**。JKP 的核心反驳正是方法学层面：市值加权把携带信号的微盘股淹没、原始收益混淆风险溢价与异象 alpha，因而「机械地」压低统计功效、误杀真因子。研究把这组数字与 JKP 并陈为「两派都对」，却没点出「**64%/85% 是 value-weight + raw-return 的人为产物**」——若据此搭一个市值加权 + t>3 的晋升闸门，等于把 HXZ 有争议的方法学固化为系统策略。属「把依赖具体设定的结论当成确证衰减事实」的外推。**状态卡须标注这组数字的方法学依赖，不当作确证衰减事实。**
  https://onlinelibrary.wiley.com/doi/full/10.1111/jofi.13249

- **【medium · 自选择偏差 / 不可线性外推 self_selection + nonlinear】「把 Frazzini-Israel-Moskowitz 当作可直接用于校准容量上限的乐观锚」**——FIM 乐观结论建立在 AQR 自家约 **1.7 万亿美元**（研究写「近万亿」量级偏低）真实成交上，本身带**自选择/最优执行偏差**：AQR 耐心拆单、可能主动回避最贵的异象（尤其短期反转），其回归得出的低成本未必能外推到一个面向小白、按 top-N 权重换仓的系统。更关键：Bucci-Bouchaud 等关于市场冲击**平方根律**的工作（冲击随成交量平方根**非线性凹增**）直接挑战「容量大一个数量级」这种**线性外推**——规模一上去边际成本是凹增的。研究把 FIM 当可直接校准容量上限的乐观锚，**未标注「自家执行数据 + 平方根冲击律」这两条对其外推性的核心限制**。容量闸门须显式纳入平方根冲击律并标注 FIM 的执行偏差。
  https://papers.ssrn.com/sol3/papers.cfm?abstract_id=3229719

- **【low · 夸大其相对属性 overstated】「MSCI 五信号拥挤模型『按历史分位解读、无绝对阈值』」**——**轻微夸大其纯相对属性**。已核实 MSCI 自家材料给出可操作解读：整合分约 **±1 即视为显著拥挤/不拥挤**——即存在**事实上的参考阈值**。同时白皮书确实描述了 z-score 标准化后合成的范式（等权合成属常规做法），所以该模型比研究暗示的**更透明**——这对工程化是有利信息，被研究低估了。（精确权重未公开仍属实，合成方式属推断。）
  https://www.msci.com/research-and-insights/blog-post/eyeing-the-crowds-from-multiple-perspectives

- **【low · 表述强于原文 overstated_vs_source】「Liu-Tsyvinski-Wu：股票因子模型不适用于加密」**——**表述略强于原文**。LTW 实际做法是把股票市场的价量类预测变量逐一构造出加密对应物，发现 size/momentum 这些「概念」在加密上同样成立、并能聚成自有三因子；结论更准确的说法是「**加密有自己的因子载荷与基线，需独立校准**」，而非「股票因子概念不适用」。「三库不可共用同一套因子族定义/拥挤基线」这一设计结论本身合理、方向正确，但其论据被表述得比原文更绝对。
  https://onlinelibrary.wiley.com/doi/abs/10.1111/jofi.13119

- **【low · 定位抬高 / 循环依赖 mischaracterized】「DSR 被定位为把 honest-N + 过拟合校正变成单一可计算闸门指标的『核心方法』」**——需澄清边界（研究在 pitfalls 已自我提示，故仅 low）：DSR 是按试验次数 N、偏度峰度对夏普「打折」的**标度/选择偏差修正**，它纠正的是「多重选择 + 非正态」下的显著性夸大；它**并不修复系统性低估，也无法独立验证 N 是否诚实**——garbage-N in, garbage-DSR out。研究正确地把 honest-N 诚实性交给 HITL，但「核心可计算闸门指标」的措辞容易让人误以为 DSR 能自动兜住过拟合；其有效性**完全取决于人喂进去的 N**。应定位为「多指标之一」（与 §14/§15 一致）。

**撤稿雷区核查**：arXiv **2512.11913**《Not All Factors Crowd Equally: Modeling, Measuring, and Trading on Alpha Decay》（Chorok Lee）已被作者**撤回（withdrawn）**——本研究**未引用，正确规避了该雷区（not_cited_clean）**。 https://arxiv.org/abs/2512.11913

**通用陷阱清单（工程红线）：**

- **honest-N 几乎不可能自动诚实**：Gelman-Loken「forking paths」表明，即便没刻意 p-hacking，变量构造/样本/过滤的分叉也会膨胀有效检验数，agent 极易低报 N 从而高估 DSR。N 必须由 HITL 显式确认，系统应记录所有试过的变体作为审计证据（见 §15）。
- **用学术毛收益评估容量/上线是头号陷阱**：Chen-Velikov 显示扣成本后平均异象净收益≈4 bps/月。任何不扣真实交易成本（尤其加密滑点/A股冲击）的晋升判断都会**系统性高估**，价值在 paper 端漂亮、实盘端蒸发。
- **把 t>3 当万能门槛会两头错**：既可能放过 HXZ 警示的 p-hacking 因子（若 N 没诚实算），又可能误杀 JKP 证明可复制的真因子（单因子 t 不足但因子族整体显著）；且 Chen 一派证明 t-hurdle 弱识别、抬高门槛难证成。门槛必须配多重检验校正 + 因子族增量 + 样本外，**不能孤立用 t、不能硬编 t>3**。
- **拥挤风险被误当缓慢均值回归**：Khandani-Lo 2007 踩踏证明拥挤尾部是「相似组合同时反转」的流动性事件。只监控单因子估值/IC 均值回归会**漏掉协同拥挤**，必须有跨因子/跨策略的相关性与共同持仓监控。
- **三库共用因子族定义会出错**：加密有自有因子载荷、股票因子模型须独立校准；直接把美股/A股因子族搬到加密会得到伪信号，且加密拥挤数据稀疏使五信号模型不可照搬。
- **factor timing 看似诱人实则危险**：Arnott 阵营的估值价差择时被 Asness 阵营证明长期可预测性弱、与价值因子重叠、换手拖累。把连续择时硬编进资产无关、面向小白的中低频系统，极可能制造「低买高卖错觉」下的隐性亏损；**默认应保守（离散生命周期决策，非连续 timing）**。
- **「已确证」与「二手/争议数字」混用会污染决策**：MSCI 五信号精确权重未公开（合成方式属推断）、「forking paths 阈值 8.2」是单篇未充分复现工作论文数字、Chen-Velikov「净收益≈0」有 FIM 真实成交数据的有力反例、HXZ 64%/85% 是方法学产物。状态卡必须**分级标注证据强度，不能把外推当规则**。
- **退役流程缺位导致因子动物园在内部复活**：若只有晋升没有 SR 11-7 式主动退役与清册回收，衰减/拥挤的旧因子会以变体形式反复被「重新发现」，honest-N 失真、因子族冗余膨胀。**退役与去重必须是状态机一等流程**（去重判据见 §8）。
- **把「发表后衰减」当一次性折扣而非持续过程**：McLean-Pontiff 衰减不归零但持续，且高样本内收益因子衰减更猛（高收益因子最该被怀疑而非最该上线）。系统应**持续重估**而非上线时打一次折就锁定。

## 8. 开放问题

- **「低频/资产无关/面向小白」定位与「机构级因子动物园治理」之间的尺度错配**：McLean-Pontiff/HXZ/JKP 几乎全部基于**美股横截面、机构换手语境**；把按尝试次数打折、因子族正交化、SR 11-7 五段治理整套搬到一个小白用、A股到 paper/加密实盘的中低频系统，存在「用机构问题的解去套零售约束」的**过度工程风险**——很多闸门（如做空兴趣价差）在目标市场根本**无数据可填**。哪些机构治理动作对本系统是必要的、哪些是 cargo-cult？
- **退役/再发现闭环缺少「同一因子的众多变体如何判定为同一因子」的操作判据**：研究正确地把退役与去重列为一等流程，但**没给出操作定义**（正交化残差相关阈值？同主题聚类？阈值取多少？）——而这恰是 honest-N 失真和因子动物园内部复活的技术症结。没有判据，退役流程会沦为口号；而判据阈值本身又是一层须预注册的自由度。
- **加密拥挤/容量校准的可行性可能被乐观带过**：研究承认加密拥挤数据稀疏、五信号要降级，但没正视更硬的问题——加密缺可靠**做空兴趣、机构持仓、估值**数据，且交易所**自成交/wash trading 污染量价信号**。这意味着「加密拥挤分」可能**根本无法达到可用于『冻结/减配』护栏的置信度**，而不仅是「置信度较低」。加密侧是否应直接禁用拥挤护栏、只做定性警示？
- **平方根市场冲击律对任何容量外推都成立的物理约束如何落地**：FIM vs Chen-Velikov 的「毛收益 vs 净收益」轴之外，还有 Almgren/Bouchaud 系的「冲击随规模凹增」这条独立物理约束——这正是把学术/纸面成本映射到 Binance 实盘滑点时最关键一环（接 §18）。如何把平方根律实测到本系统的容量闸门，而非沿用 FIM 的线性乐观外推？
- **factor timing 的「可解释例外」会不会变成放水后门**：默认保守（离散生命周期决策）+ 用户经济判断可开轻度估值择时例外——但 Arnott vs Asness 本身未和解，把例外权交给「最想让心仪因子过关」的用户，可能重蹈档位 p-hacking 覆辙（见 §15）。例外是否须连同理由预注册 + HITL 双签，而非单方开关？
- **衰减折扣（公开因子 −26%/−58%）的持续重估节奏**：衰减是持续过程而非一次性折扣，但「持续重估」需要持续的新样本，而中低频 + 短加密样本下重估的统计功效极弱。重估频率如何与因子半衰期、样本积累速度匹配，而不至于在噪声上反复横跳？
- **PBO/CSCV 对前视偏差/数据泄露/未覆盖 regime 完全盲**：晋升闸门用 PBO/CSCV 估过拟合概率，但 CPCV 优势仅在合成受控环境被证明（2024 ScienceDirect），walk-forward 仍是真实交易模拟工业标准，且这些方法对 A股/加密最易踩的前视/泄露/regime 切换**完全盲**（见 §16）。本环节是否应在因子状态卡显式标注「过了过拟合闸门 ≠ 覆盖了泄露与 regime 风险」？

## 9. 参考文献（URL）

**核心论文**
- McLean & Pontiff (2016), Does Academic Research Destroy Stock Return Predictability?, JF 71(1) — https://onlinelibrary.wiley.com/doi/abs/10.1111/jofi.12365
- Calluzzo, Moneta & Topaloglu (2019), When Anomalies Are Publicized Broadly…, Management Science 65(10) — https://afajof.org/management/viewp.php?n=46984
- Chen & Velikov (2023), Zeroing In on the Expected Returns of Anomalies, JFQA 58(3) — https://papers.ssrn.com/sol3/papers.cfm?abstract_id=3073681
- Frazzini, Israel & Moskowitz (2018 wp), Trading Costs of Asset Pricing Anomalies, AQR — https://www.aqr.com/Insights/Research/Working-Paper/Trading-Costs-of-Asset-Pricing-Anomalies （SSRN: https://papers.ssrn.com/sol3/papers.cfm?abstract_id=3229719 ）
- Hou, Xue & Zhang (2020), Replicating Anomalies, RFS 33(5) — https://www.nber.org/system/files/working_papers/w23394/w23394.pdf
- Jensen, Kelly & Pedersen (2023), Is There a Replication Crisis in Finance?, JF 78(5) — https://onlinelibrary.wiley.com/doi/full/10.1111/jofi.13249
- Harvey, Liu & Zhu (2016), … and the Cross-Section of Expected Returns, RFS 29(1) — https://academic.oup.com/rfs/article/29/1/5/1843824
- Chen (2023), Do t-Statistic Hurdles Need to be Raised?, arXiv 2204.10275 — https://arxiv.org/pdf/2204.10275
- Bailey & López de Prado (2014), The Deflated Sharpe Ratio, JPM 40(5) — https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2460551
- Bailey, Borwein, López de Prado & Zhu (2017), The Probability of Backtest Overfitting (CSCV), J. Computational Finance — https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2326253
- Khandani & Lo (2011), What Happened to the Quants in August 2007?, J. Financial Markets 14(1) — http://web.mit.edu/~alo/www/Papers/august07b_2.pdf
- Asness, Chandra, Ilmanen & Israel (2017), Contrarian Factor Timing is Deceptively Difficult, JPM Special Issue — https://www.aqr.com/Insights/Research/Journal-Article/Contrarian-Factor-Timing-is-Deceptively-Difficult
- Arnott, Beck, Kalesnik & West (2016), How Can 'Smart Beta' Go Horribly Wrong? / Forecasting Factor Returns, Research Affiliates — https://www.researchaffiliates.com/insights/publications/articles/442_how_can_smart_beta_go_horribly_wrong
- Ehsani & Linnainmaa (2022), Factor Momentum and the Momentum Factor, JF 77(3) — https://onlinelibrary.wiley.com/doi/abs/10.1111/jofi.13131
- Liu, Tsyvinski & Wu (2022), Common Risk Factors in Cryptocurrency, JF 77(2) — https://onlinelibrary.wiley.com/doi/abs/10.1111/jofi.13119
- Gelman & Loken (2013) / Coqueret (2024), Forking Paths in Financial Economics, arXiv 2401.08606 — https://arxiv.org/abs/2401.08606

**SOTA 系统 / 商业模型**
- MSCI Integrated Factor Crowding Model — https://www.msci.com/research-and-insights/blog-post/eyeing-the-crowds-from-multiple-perspectives
- Barra (MSCI) USE4 Methodology Notes — https://www.top1000funds.com/wp-content/uploads/2011/09/USE4_Methodology_Notes_August_2011.pdf
- AQR 因子框架（Trading Costs / Factor Timing / 复制危机）— https://www.aqr.com/Insights/Research/Working-Paper/Trading-Costs-of-Asset-Pricing-Anomalies
- Research Affiliates 因子择时/估值框架 — https://www.researchaffiliates.com/publications/articles/595-forecasting-factor-and-smart-beta-returns

**机构实践 / 标准**
- Federal Reserve / OCC, SR 11-7 Model Risk Management — https://www.federalreserve.gov/supervisionreg/srletters/sr1107.htm
- NIST AI Risk Management Framework 1.0 — https://www.nist.gov/itl/ai-risk-management-framework
- Research Affiliates, A Framework for Assessing Factors and Implementing Smart Beta Strategies — https://www.researchaffiliates.com/en_us/publications/journal-papers/373_a_framework_for_assessing_factors_and_implementing_smart_beta_strategies.html
- FTSE Russell, Factor Exposures of Smart Beta Indexes — https://www.lseg.com/content/dam/ftse-russell/en_us/documents/other/factor-exposures-of-smart-beta-indexes.pdf

**开源工具 / 校准基线**
- Open Source Asset Pricing (Chen & Zimmermann) — https://github.com/OpenSourceAP/CrossSection
- Chen-Velikov 复制代码 — https://github.com/velikov-mihail/Chen-Velikov
- alphalens（alphalens-reloaded）— https://github.com/quantopian/alphalens
- PBO / CSCV 实现（CRAN `pbo` 包）— https://cran.r-project.org/web/packages/pbo/readme/README.html

**对抗核查 / 争议补入**
- CPCV vs walk-forward（2024 ScienceDirect）— https://www.sciencedirect.com/science/article/abs/pii/S0950705124011110
- 已撤回雷区（未引用）：arXiv 2512.11913, Not All Factors Crowd Equally — https://arxiv.org/abs/2512.11913
