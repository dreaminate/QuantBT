# 36 · 冷启动（N=1）+ 按用户风格个性化

> 机构级 Agent OS 成品环节深挖 · 全程 Opus 4.8 · 对抗式核查已降权 · 重心=前沿研究+概念级推荐 · 不含 file:line 代码接线
> 簇 F

## 1. 一句话定位

漏斗第一天的两个交汇难题：(A) 当只有**一条候选策略、无 challenger 历史、无成败先例**时，如何做"流程即信任"的**诚实评估**而不是给小白一个虚高的 Sharpe；(B) 如何从**近乎零的交互**里推断用户风格/风险偏好并据此个性化，同时**绝不让个性化松动治理刚性**。核心立场：个性化只允许作用于**呈现层 / 优先级 / 沟通风格**，治理闸门（统计显著性门槛、风险/杠杆上限、PIT/无泄露护栏）对所有用户保持**资产无关的统一刚性**；冷启动第一天的诚实表态应表现为**显式的不确定性**（"证据不足，暂不可信"）而非一个被假设掩盖的精确数字。

---

## 2. 前沿 SOTA 与代表系统

| 系统 / 方法 | 它是什么 · 对本环节意味着什么 | URL |
|---|---|---|
| **Probabilistic / Deflated Sharpe Ratio + Minimum Track Record Length（Bailey & López de Prado）** | 针对"单条策略、样本短、可能非正态、有多重测试选择偏差"给出严谨显著性判定与"还需多少观测才可信"的 MinTRL。**⚠️ 核查关键（见 §7）：DSR 本质是"多重检验校正"——它把拒绝阈值按有效试验数 N 上调；当真正 N=1、无 challenger 时 DSR 退化为 PSR、不提供额外信息，把 DSR 当 N=1 治理工具是范畴误用。真正适用单策略的只有 PSR / MinTRL。** 且 PSR/MinTRL 建立在**收益平稳且遍历**假设上——冷启动第一天恰是平稳性最不成立、regime 依赖最强之时。 | https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2460551 |
| **Amazon 产品搜索 Empirical Bayes 冷启动** | 用经验贝叶斯把非行为信号（主题相关性）做先验估计新品后验，解决排序冷启动；50M query A/B 显示新品曝光 +13.53%、新品购买 +11.14%、总购买 +0.08%。"用信息先验补数据缺失"的大规模落地范例。**⚠️ 核查降权（见 §7）：这是产品搜索的曝光/转化提升，与"单条策略能否被信任"几乎无共同成功度量；+0.08% 总购买提升极小，且为推荐系统域（容错高、反馈快、损失对称），不可直接外推到投资治理域。** | https://www.amazon.science/publications/addressing-cold-start-in-product-search-via-empirical-bayes |
| **Black-Litterman / Bayes-Stein 收缩（组合估计）** | 把估计往均衡/先验收缩以降估计误差，是金融界"小数据下用信息先验"的标准范式；arXiv 2308.09264 把 BL + 贝叶斯收缩 + 因子模型统一为同一贝叶斯更新框架。是"信息先验工程化"在金融域**同域**的可靠参照（区别于推荐系统跨域外推）。 | https://arxiv.org/abs/2308.09264 |
| **Thompson Sampling / 上下文老虎机冷启动** | 贝叶斯后验采样从第一次交互起同时探索与利用，无需预先囤数据即可缓解新用户冷启动。**⚠️ 核查降权（见 §7）：源自推荐系统排序/曝光场景，ε-探索在高后果金融域不可照搬（给小白展示其会拒绝甚至亏钱的选项的探索成本无法对称对冲）。** | https://dl.acm.org/doi/10.1145/3554819 |
| **MAML 类元学习冷启动推荐（MeLU/MAMO/AdaMO/CMML）** | 元学习出好的初始化参数，再用新用户极少交互快速梯度适配；2023-24 的 AdaMO/任务相似性聚类按任务特征定制初始化。提供"warm-start 用户画像"的**概念骨架**。**⚠️ 同属推荐系统域，迁移须降权。** | https://www.sciencedirect.com/science/article/abs/pii/S0925231224001887 |
| **LLM 作为 near-cold-start 推荐器（Sanner et al., RecSys'23）** | 证明 LLM 在纯语言偏好（无历史 item 交互）的近冷启动场景下，零样本/少样本即有竞争力——支撑"对话式引导用户风格"路线。**⚠️ 核查漏点（见 §8）：LLM 漏斗式提问本身有 framing effect + 幻觉性归纳，在风险偏好这种已知易受框架影响的构念上会放大测量误差，与 CFA 信度/效度门槛冲突。** | https://ssanner.github.io/papers/recsys23_llmrec.pdf |

**开源 / 工具线**

| 工具 | 说明 | URL |
|---|---|---|
| **PerformanceAnalytics (R) — MinTrackRecord / ProbSharpeRatio** | 现成实现 PSR 与 MinTRL，可直接把"这条策略还需多少观测/当前置信几何"量化输出。 | https://rpkg.net/packages/PerformanceAnalytics/reference/MinTrackRecord.ob |
| **Portfolio Optimizer (portfoliooptimizer.io) — PSR/MinTRL 文档与 API** | 对 PSR 偏差校正、置信区间、假设检验、两策略 Sharpe 差的 MinTRL 有清晰公式与服务化实现，可作评估层参考。 | https://portfoliooptimizer.io/blog/the-probabilistic-sharpe-ratio-bias-adjustment-confidence-intervals-hypothesis-testing-and-minimum-track-record-length/ |
| **skfolio — Prior Estimator（含 Black-Litterman / 收缩）** | Python 组合库，把收缩与 BL 视图统一为 prior estimator 接口，是"把信息先验工程化"的现成抽象。 | https://skfolio.org/user_guide/prior.html |
| **mlfinlab / "Machine Learning for Trading"（Jansen）多重测试章节** | 开源教学实现 DSR、最小回测长度与多重测试校正，适合把多重测试治理接入回测桥（注意：DSR 适用于"多策略择优"场景，非 N=1）。 | https://stefan-jansen.github.io/machine-learning-for-trading/08_ml4t_workflow/01_multiple_testing/ |

---

## 3. 关键论文（每条带 URL）

1. **The Deflated Sharpe Ratio: Correcting for Selection Bias, Backtest Overfitting and Non-Normality**（Bailey & López de Prado, 2014）
   单条策略评估时，样本长度、非正态、多重测试选择偏差都会膨胀 Sharpe；DSR 把这些折算进显著性。
   ⚠️ 核查限定（见 §7）：DSR = PSR where the rejection threshold is adjusted to reflect the multiplicity of trials。**它的全部价值来自存在多个被择优的候选；在真正 N=1、无 challenger 时退化为 PSR、不提供任何额外信息。** "无 challenger 历史"≠"可放松证据标准"，但把 DSR 当 N=1 的治理工具是范畴误用。
   ref: SSRN 2460551 — https://www.davidhbailey.com/dhbpapers/deflated-sharpe.pdf

2. **The Sharpe Ratio Efficient Frontier / Probabilistic Sharpe Ratio & Minimum Track Record Length**（Bailey & López de Prado, 2012）
   PSR 给出"真 Sharpe 超过阈值的概率"，MinTRL 给出"还需多少观测才能以给定置信度认定策略有效"——把"N=1 第一天该说多有把握"量化为可表态的数字。
   ⚠️ 核查限定（见 §7）：建立在**收益平稳且遍历（stationary & ergodic）**假设上，原文不显式处理序列相关/非平稳。冷启动第一天恰是样本最短、平稳性最不可检验、regime 依赖最强之时——把 MinTRL 输出当"诚实的可表态数字"会给出**被假设掩盖的虚假精确（false precision）**，它只在 IID/平稳成立时才诚实。
   ref: SSRN 1821643 — https://www.davidhbailey.com/dhbpapers/sharpe-frontier.pdf

3. **Financial Risk Tolerance: A Psychometric Review**（CFA Institute Research Foundation, Klement ed., 2017/2018）
   风险承受度测量须 Cronbach α≥0.70（优≥0.90）；单/三题问卷不可信；问卷常混淆 risk capacity 与 tolerance、构念效度低；分数只应作"起点"而非定论。是用户风格个性化的机构级信度/效度门槛。
   ref: CFA Institute RF — https://rpc.cfainstitute.org/research/foundation/2017/financial-risk-tolerance

4. **User Cold-start Problem in Multi-armed Bandits: When the First Recommendations Guide the User's Experience**（ACM TORS, 2023）
   第一批推荐会塑造用户整条体验轨迹（路径依赖）——冷启动期的探索/初始化策略决定长期画像。提醒：漏斗第一天的个性化是**高杠杆且有锁定风险**的。
   ref: ACM TORS 3554819 — https://dl.acm.org/doi/10.1145/3554819

5. **High-Stakes Personalization: Rethinking LLM Customization for Individual Investor Decision-Making**（arXiv 2604.04300）
   ⚠️ 核查标注：此为**概念框架（无实证）**。个性化既能提升对齐又会固化用户既有行为偏差、产生不可审计黑箱建议；新投资者缺历史时易在稀疏数据上过拟合。明确个性化≠更好结果，治理/透明/去偏不可缺。**关键：本文恰恰指出投资域"没有固定标签集、结果随机且延迟"使标准（推荐系统式）个性化范式失效——这与"推荐系统冷启动方法可落地迁移"的乐观叙述张力很大。**
   ref: arXiv 2604.04300 — https://arxiv.org/pdf/2604.04300

6. **Robo-Advisors Beyond Automation: Principles and Roadmap for AI-Driven Financial Planning**（arXiv 2509.09922）
   主张超越静态问卷转向动态/持续行为评估；trust 是地基，采用分阶段（先透明说明能力边界 → 用可解释建议证明胜任 → 渐进放权）而非一上来全自动；个性化与护栏本质对立，需平衡用户自主与保护机制。
   ref: arXiv 2509.09922 — https://arxiv.org/pdf/2509.09922

7. **Robo-advising: Learning Investors' Risk Preferences via Portfolio Choices**（arXiv 1911.02067）
   从用户对组合的实际选择（**揭示偏好**）反推风险偏好，而非只靠问卷自述——支撑"用 agent 建议的接受/拒绝行为推断用户风格"的揭示偏好路线。
   ⚠️ 核查关联（见 §7）：揭示偏好存在**供给集污染/自我实现回路**——agent 只展示它自己偏好的选项，用户的"选择"被供给集污染，推断出的"用户风格"其实是 agent 风格的回声。
   ref: arXiv 1911.02067 — https://arxiv.org/pdf/1911.02067

8. **Filter Bubbles in Recommender Systems: Fact or Fallacy — A Systematic Review**（arXiv 2307.01221）
   过度个性化导致 filter bubble/echo chamber 的经验证据**混合且有争议**——各文定义不同、结论不可比。应把它当**规范性风险**防范，不可当已证实因果机制宣称。
   ⚠️ 核查降权（见 §7）：该综述摘要实际结论偏向**确认** filter bubble 存在（"our review reveals evidence of filter bubbles... highlighting several biases that contribute to their existence"），用它来支撑"证据混合且有争议"与该文自身立场**不完全吻合**——属引用与论点轻微错位（非致命）；"证据混合/定义不可比"的更强支撑应另找。
   ref: arXiv 2307.01221 — https://arxiv.org/pdf/2307.01221

9. **Degenerate Feedback Loops in Recommender Systems**（Jiang et al., arXiv 1902.10730）
   把用户兴趣建模为动力系统，给出"兴趣极端化/退化"的充分条件——冷启动初始化 + 持续个性化可能把用户推向退化点。需主动注入多样性/探索打破反馈环。
   ref: arXiv 1902.10730 — https://arxiv.org/pdf/1902.10730

10. **Asking Clarifying Questions for Preference Elicitation With Large Language Models**（arXiv 2510.12015）
    LLM 学会"漏斗式"澄清问题（先泛后专）来快速建立用户画像——为对话式冷启动偏好引导提供可操作模式。
    ⚠️ 核查漏点（见 §8）："问到何时停"本身需要主动学习/价值-of-information 取舍：问得过多拖垮 onboarding（小白流失），问得过少又欠采样——不是越多越好。
    ref: arXiv 2510.12015 — https://arxiv.org/pdf/2510.12015

11. **Cold-Start Recommendation towards the Era of LLMs: A Comprehensive Survey and Roadmap**（arXiv 2501.01945）
    系统梳理冷启动方法族：profile-based 初始化、上下文建模、元学习、主动偏好引导，并讨论 LLM 时代的新范式。可作冷启动技术全景图。
    ref: arXiv 2501.01945 — https://arxiv.org/pdf/2501.01945

---

## 4. 机构最佳实践 / 标准

| 实践 / 标准 | 内容 · 对 N=1 与个性化的含义 | 来源 / URL |
|---|---|---|
| **SR 11-7 模型风险管理** | 任何支撑实质业务决策的模型须经独立验证（概念健全性 + 结果分析 + 持续监控）；backtest 属结果分析，须用开发未用过的样本、频率匹配预测期。对 N=1 的含义："无历史"不豁免独立验证，反而要靠**概念健全性（先验/参照类合理性）与持续监控**补位。**⚠️ 核查瑕疵（见 §7）：研究发现引用的是厂商博客 modelop.com 为一手联邦法规背书（二手来源），建议替换为 Fed/OCC 原文。实质内容核对正确。** | Federal Reserve / OCC, SR 11-7 (2011) — https://www.modelop.com/ai-governance/ai-regulations-standards/sr-11-7 |
| **NIST AI RMF（含 GenAI Profile 600-1）** | GOVERN/MAP/MEASURE/MANAGE 四功能；要求审批闸门、人类监督、按系统特征做个性化治理、持续 MANAGE 循环。支撑"个性化作用于呈现层、治理闸门统一刚性"的分层设计。 | NIST AI RMF 1.0 + AI 600-1 (2024) — https://www.nist.gov/itl/ai-risk-management-framework |
| **CFA Institute 风险画像最佳实践** | 要求测试发布信度系数（α≥0.70）、用标准测量误差（SEM）给分数置信区间、把问卷结果当"规划起点"并结合更广泛风险画像讨论；警惕下跌后测得偏好被低估。 | CFA Institute RF — Risk Profiling and Tolerance (Klement, 2018) — https://rpc.cfainstitute.org/sites/default/files/-/media/documents/book/rf-publication/2018/risk_compilation_2018.pdf |
| **Champion/Challenger + Shadow mode 工程惯例** | 任一时刻只有一个 champion 服务全部流量，challenger 在影子模式并行评估，KPI 胜出才晋升。对"N=1 无 challenger"：可让新策略先跑影子/纸面、以一个保守 default/参照类策略作**隐性 champion** 做对照，避免无对照即上线。 | DataRobot MLOps / FICO 决策管理 — https://www.datarobot.com/blog/introducing-mlops-champion-challenger-models/ |

---

## 5. 对 QuantBT 这套架构的推荐方向（概念级）

> 仅概念级方向，不点 file:line、不排实施计划。下列方向已吸收对抗核查的降权——尤其把 DSR 从 N=1 路径剔除、显式声明 PSR/MinTRL 的平稳假设何时失效。

1. **把 N=1 评估建成"诚实贝叶斯/频率派表态层"，但工具用对。** 对单条无 challenger 历史的策略，统一用 **PSR + MinTRL**（**不用 DSR**——DSR 是多重检验校正，N=1 时退化为 PSR、不提供信息，强行用反而制造统计光环）输出三件事：(a) 当前可信度概率，(b) 还需多少观测/多长 OOS 才能达到可表态阈值，(c) 显式的"证据不足，暂不可信"状态。**关键诚实动作：每个 PSR/MinTRL 输出都必须随附其平稳/遍历假设的成立性声明——一旦检测到强 regime 依赖或序列相关，该数字应被标注为"假设不成立，置信不可靠"，而非冒充诚实的精确值。**

2. **用"信息先验/参照类"替代"空白冷启动"，但正视先验在 N=1 时的不可证伪性。** 新策略落地前，从已有同风格策略族、同 regime 基准、用户已接受过的策略里构造经验贝叶斯先验，把单点估计往参照类收缩（James-Stein / BL 思想，且这是金融**同域**实践，非推荐系统外推）。**但须诚实承认（见 §8 开放问题）：N=1、无 OOS 的第一天，先验好坏在统计上根本无法被数据检验或反驳，后验几乎完全由先验主导——"可信度概率"本质上是"先验的回声"而非证据。** 治理动作是让"用了哪个参照类先验"可见、可审计、可被用户和复核 agent 质疑，且在 UI 上明确把第一天的数字标为"先验断言、未经数据检验"。

3. **设隐性 champion 做对照，杜绝"无对照即上线"。** 即便用户只有一条策略，也用一个保守的资产无关 default（如等权/低波/纸面基准）作隐性 champion，新策略先跑影子/纸面期。漏斗第一天的产出是"新策略 vs 保守基准"的对照，而非孤立一条曲线。

4. **严格分层"个性化作用域"，做成架构级不变量。** 个性化只允许作用于呈现层（讲解深度、风险话术、默认视图、建议排序）；治理闸门（PBO/CSCV、统计显著性门槛、回撤/杠杆上限、PIT/无泄露校验）对所有用户保持统一刚性。把"个性化绝不松动证据标准"写成可对抗复核的红线——设一个独立复核视角专门检查"是否因用户风格而放宽了任何资产无关的统计/风控门槛"，与既有对抗式复核机制并轨。

5. **用"对话式漏斗引导 + 揭示偏好"双轨建用户风格，且都标注不确定性。** onboarding 用少量漏斗式澄清问题给出风格先验（带置信区间），之后持续从用户对 agent 建议的接受/拒绝里贝叶斯更新。明确把"当前风格画像"当成带不确定性的后验而非定论，并在市场剧烈波动后对新采集的偏好**打折**（对抗下跌后低估偏差）。**⚠️ 双轨各有内生偏差须防呆：对话轨有 LLM framing/幻觉（见 §8），揭示偏好轨有供给集污染回路——后者要求 agent 展示的候选集必须刻意覆盖不同风格档位，否则推断出的只是 agent 风格的回声。**

6. **对个性化主动注入"反回声"保护——但金融域不能照搬 ε-探索。** 在冷启动与持续期保留一定多样性配额，并对"用户轨迹是否在窄化/被供给集污染"做监控告警，把退化反馈环当可监测的规范性风险。**⚠️ 注意：filter bubble 有害的经验证据混合不可比（见 §7），此处作为规范性风险防范而非已证因果；且高后果金融域的探索成本（给小白展示其会亏钱的选项）无法像推荐系统那样对称对冲，"多样性"应主要体现在解释/呈现的视角多样，而非真金白银的随机化探索。**

7. **onboarding 做成"渐进信任阶梯"而非一步到位。** 对齐 SR 11-7 / NIST 的人类监督要求——第一天 agent 默认"问后再做 + 全程可解释"，随可验证的成功历史累积再逐级放权（act-and-report → 更高自治）。让自治度成为"已验证轨迹记录"的函数，而非用户一句话就开全自动；这同时与已锁定的 D3（实盘 agent 仅警告 + 规则停）一致。

---

## 6. 架构级参考（少量伪代码 / schema 草图，非代码接线）

> 示意草图，不接线到现有代码。

**6.1 N=1 诚实表态层输出 schema（单策略评估契约）**

```yaml
n1_verdict:
  strategy_id: str
  asof: date                          # PIT 对齐
  n_obs: int                          # 当前观测数（很可能远低于 MinTRL）
  psr: 0.0..1.0                       # 真 Sharpe > 基准阈值 的概率（PSR）
  psr_threshold_sr: float             # 基准 Sharpe（参照类/隐性 champion）
  min_track_record_len: int           # 达到可表态置信所需观测数（MinTRL）
  obs_gap: int                        # = MinTRL - n_obs（还差多少）
  stationarity_ok: bool               # ⚠ 平稳/遍历假设是否成立
  stationarity_note: "检测到强 regime 依赖 → PSR/MinTRL 数字置信不可靠"
  verdict: insufficient_evidence | tradeable_with_caveats | trusted
  # ⚠ 第一天几乎必然 = insufficient_evidence；DSR 字段刻意不存在（N=1 退化为 PSR）
  prior_used:                         # 信息先验/参照类必须可审计
    reference_class: "同风格动量族 / 同 regime 基准"
    posterior_is_prior_echo: true     # ⚠ N=1 时后验 ≈ 先验，须显式声明
  challenger:                         # 隐性 champion 对照（杜绝无对照上线）
    baseline_id: "equal_weight_paper"
    relative_curve: ref
```

**6.2 个性化作用域不变量（架构级红线，概念伪代码）**

```python
# 个性化只准改"怎么呈现"，绝不准改"怎么判定"
PRESENTATION_SCOPE = {"explain_depth", "risk_phrasing",
                      "default_view", "suggestion_ordering"}
GOVERNANCE_SCOPE   = {"psr_threshold", "pbo_cscv_gate",
                      "drawdown_cap", "leverage_cap",
                      "pit_leakage_check", "min_track_record_len"}

def apply_personalization(user_style, decision):
    # 个性化只触碰呈现层
    decision = restyle(decision, user_style, allow=PRESENTATION_SCOPE)
    # 不变量：任何治理参数不得因 user_style 改变（资产无关刚性）
    assert governance_params(decision) == GLOBAL_GOVERNANCE_PARAMS, \
        "个性化越界：试图因用户风格放宽治理门槛"  # → 对抗复核红线
    return decision
```

**6.3 用户风格画像（带不确定性的后验，双轨更新）**

```yaml
user_style_profile:
  source: conversational_funnel + revealed_preference   # 双轨
  risk_tolerance:
    point: 0.6                        # 0=保守 1=激进
    ci: [0.35, 0.78]                  # ⚠ 单/三题问卷 α<0.70 → 区间很宽
    confidence: low                   # 冷启动默认低置信
  reliability_note: "onboarding 问卷仅作起点，非定论（CFA α≥0.70 门槛）"
  post_drawdown_discount: true        # 下跌后采集的偏好打折（防系统性低估）
  framing_risk_flag: true             # ⚠ LLM 漏斗提问的 framing/幻觉偏差
  supply_set_contamination_guard:     # ⚠ 揭示偏好的回声风险
    candidate_set_must_span_styles: true   # 候选集须刻意覆盖多风格档位
  update_rule: bayesian_posterior     # 持续从接受/拒绝行为更新
```

**6.4 冷启动状态机（含退出判据占位——⚠ 阈值待定，见 §8）**

```
状态:
  COLD_START(N=1)  : 隐性 champion 对照 + 默认"问后再做" + 全程可解释
  WARMING          : 影子/纸面期累积 OOS；PSR 上升但未达表态阈值
  ESTABLISHED      : 已脱离 N=1，进入正常评估（PBO/CSCV/DSR 多策略治理全开）

迁移判据（⚠ 缺可执行阈值是当前最大半成品缺口）:
  COLD_START -> WARMING     : n_obs > 0 且隐性 champion 对照已建立
  WARMING -> ESTABLISHED    : n_obs >= MinTRL 且 PSR >= τ_psr
                              且 stationarity_ok（??? τ_psr / OOS 长度待定）
  任意 -> COLD_START（降级）: 检测到 regime 突变使既有 OOS 失效
```

---

## 7. 降权 / 争议 / 陷阱（对抗核查结论）

> 对抗核查总判：**这是一份质量明显高于平均、且罕见地自我设防的研究发现**——11 篇引用 + 4 项机构实践全部核实存在（含两篇 2026/2025 未来日期的 arXiv 2604.04300、2509.09922 均真实），数字（Amazon +13.53%/+11.14%/+0.08%、50M query；CFA α≥0.70）核对无误，且研究主动把 filter-bubble 证据标为"混合争议"、把 2604.04300 标为"概念无实证"、把"个性化不得松动证据标准"立为红线——这些都堵住了常见雷区，**不应被罚**。但仍有可被攻破的实质夸大，集中在**工具适配与跨域外推**而非编造。**结论：方向正确、引用扎实、自我设防到位，但把"有严谨工具可用"夸大成了"N=1 第一天已有干净工程化答案"。**

**MEDIUM 严重度**

- ⚠️【范畴误用 / 工具错配】**将 PSR/DSR/MinTRL 三件套并列为"单条策略无 challenger"N=1 第一天的统一治理基座/最佳实践基石**——概念错配。DSR（Deflated Sharpe Ratio）本质是**多重检验校正**，它把拒绝阈值按有效试验数 N 上调（Bailey & López de Prado 自己的定义：DSR = PSR where the rejection threshold is adjusted to reflect the multiplicity of trials）。当真正只有 1 条策略、N=1、无 challenger 历史时，**DSR 退化为 PSR、不提供任何额外信息**；把 DSR 当成 N=1 场景的治理工具是范畴误用。真正适用单策略的只有 PSR/MinTRL。López de Prado 明确说多重检验应"事先规划试验数"，N 不可在事后对孤立策略反推。研究把"无 challenger=可放松证据标准"反过来论证用 DSR 是对的，但**选错了工具**——DSR 的全部价值恰恰来自存在多个被择优的候选，与 N=1 前提自相矛盾。**落地必须把 DSR 从 N=1 路径剔除。**

- ⚠️【假设省略 / 虚假精确（false precision）】**PSR/MinTRL 能在第一天把"还需多少观测才可信"量化为可表态的诚实数字**——省略了关键假设与已知局限。PSR/MinTRL 建立在**收益平稳且遍历（stationary & ergodic）**假设上，原始论文"不显式处理序列相关/非平稳过程"。而 N=1 的第一天恰恰是样本最短、平稳性最不可检验、regime 依赖最强的时刻——研究自身在别处强调 regime 切换，这与 PSR 的平稳前提直接冲突。把 MinTRL 输出当成"诚实的可表态数字"会给出一个**被假设掩盖的虚假精确**：它只在 IID/平稳成立时才是诚实的，而那正是冷启动最不成立的条件。**落地必须显式声明 PSR/MinTRL 的平稳假设何时失效。**

- ⚠️【过度概括 + 跨域外推】**全球前沿对小样本/N=1 评估"高度一致地收敛到贝叶斯框架"，且在推荐系统、组合管理上"已确证、可落地"**——(1)"高度一致地收敛"是**修辞夸张**：贝叶斯收缩只是众多小样本方法之一，频率派的多重检验校正、稳健统计、保守 default 同样主流，把整个前沿描述成单一收敛框架抹平了真实分歧。(2)更重要的是**跨域外推**：Amazon 经验贝叶斯、Thompson sampling、MAML/AdaMO 都是**推荐系统排序/曝光**场景的结果——目标是参与度/点击/购买，容错高、反馈快、损失对称。把它们直接搬到**投资策略的信任评估/治理**（后果不对称、反馈延迟数周数月、错误代价高、还要资产无关刚性）是**领域错配**。研究自己引用的 arXiv 2604.04300 恰恰指出投资域"没有固定标签集、结果随机且延迟"使标准个性化范式失效——与"推荐系统冷启动方法可落地迁移"的乐观叙述张力很大。

**LOW 严重度**

- ⚠️【相关性夸大 / 不可比领域背书】**Amazon 经验贝叶斯冷启动 A/B（新品曝光 +13.53%、新品购买 +11.14%、总购买 +0.08%、50M query）是"用信息先验补数据缺失"的已确证大规模落地范例**——数字本身核对无误（与论文一致），但作为本环节论据**被夸大其相关性**。这是产品搜索排序的曝光/转化提升，与"单条交易策略在 N=1 第一天能否被信任"几乎无共同的成功度量；且 +0.08% 的总购买提升极小（主要是把曝光重分配给新品），并非证明经验贝叶斯能提升"决策质量/真实参与度估计准确性"。把它当成本环节（策略评估治理）"已确证可落地"的范例，是借用了一个不可比领域的成功来给金融治理背书。

- ⚠️【引用与论点轻微错位】**诚实地把 filter bubble/echo chamber 经验证据标注为"混合且有争议"，引 arXiv 2307.01221 系统综述支撑**——方向值得肯定（研究确实做了诚实标注，这点**不应被罚**），但引用的 2307.01221 摘要实际结论是"our review reveals evidence of filter bubbles... highlighting several biases that contribute to their existence"——它倾向于**确认** filter bubble 存在，而非中立地说"证据混合不可比"。研究用这篇来支撑"混合且有争议"的论点，与该文自身的偏 confirm 立场不完全吻合；"证据混合/定义不可比"的更强支撑应另找。属引用与论点轻微错位，非致命。

- ⚠️【二手来源给一手法规背书】**SR 11-7 模型风险管理的机构实践引用**——内容核对正确（概念健全性 + 结果分析 + 持续监控三活动、backtest 用开发未用样本、频率匹配、独立验证均属实）。唯一瑕疵：引用的是厂商博客 modelop.com 作为一份联邦储备/OCC 原始监管文件的来源（二手来源给一手法规背书）。建议替换为 Fed/OCC 原文链接。实质无误，仅来源层级问题。

**通用陷阱清单（设计须规避）**

- **把"N=1 无 challenger 历史"误当成"可放松证据标准"。** 恰恰相反：样本越短越要用 PSR/MinTRL 诚实折算显著性，并显式声明"当前观测不足以表态"，而非给一个虚高的 Sharpe 让小白误信。
- **第一批推荐/第一个被接受的策略会塑造用户整条轨迹（路径依赖、退化反馈环）。** 冷启动期的个性化是高杠杆且会锁定的——若早期就重度迎合，可能把用户推向其行为偏差的极端。
- **个性化越界。** 让个性化渗入证据/评估层（为"激进型"用户放宽 PBO/回撤门槛）会制造不可审计黑箱并固化偏差。个性化应只作用于呈现/优先级/沟通风格，治理闸门对所有用户资产无关地统一刚性。
- **过信风险问卷。** 单/三题问卷信度不足（α<0.70）、混淆 risk capacity 与 tolerance、且在市场下跌后测得偏好被系统性低估。把一次问卷当成稳定的用户风格定论是错误的。
- **"filter bubble/over-personalization 有害"被当成已证实因果**——实则系统综述证据混合、定义不可比。应作为规范性风险主动防范（注入多样性/探索），但不可在产品话术里把它当铁证。
- **信息先验/参照类选得不当 = 把偏见当先验。** 经验贝叶斯收缩的质量取决于"收缩到哪个先验"；若参照类（同风格策略族/同 regime 基准）选错，会把新策略系统性拉偏，且因隐蔽更难被发现。
- **对话式偏好引导问得过多会拖垮 onboarding（小白流失），问得过少又欠采样。** "问到何时停"本身需要主动学习/价值-of-information 取舍，不是越多越好。
- **用揭示偏好反推风格时存在自我实现回路**：agent 只展示了它自己偏好的选项，用户的"选择"被供给集污染，推断出的"用户风格"其实是 agent 风格的回声。

---

## 8. 开放问题

> 以下为对抗核查指出的、研究发现未正面处理的漏点，是落地前必须补齐的硬缺口。

1. **N=1 时贝叶斯先验本身不可证伪（最深的认识论漏洞）。** 研究把"选错参照类先验=把偏见当先验"列为 pitfall，但没正视更深的问题——在 N=1、无 OOS 的第一天，先验的好坏在统计上**根本无法被数据检验或反驳**，后验几乎完全由先验主导。这意味着"诚实贝叶斯表态层"输出的可信度概率在第一天其实是"**先验的回声**"而非证据；审计可见参照类**并不能解决其不可证伪性**。需要明确：第一天的数字在 UI 与文档里必须标为"先验断言、未经数据检验"。

2. **缺少任何定量门槛。** 整个设计方向停留在"用 PSR/MinTRL 输出可信度 + 所需观测数 + 证据不足状态"，但没说在**多少 Sharpe / 多长 OOS / 什么 PSR 阈值**下才允许从"证据不足"升级到"可表态"。对一个声称"流程即信任""拒绝半成品"的项目，缺少可执行阈值=仍是半成品蓝图（见 §6.4 状态机里的 `??? τ_psr / OOS 长度待定` 占位）。

3. **A股市场结构对 PSR/MinTRL 的破坏性未被讨论。** A股 T+1、涨跌停、频繁停牌、强 regime 切换会**系统性违反 PSR 的 IID/平稳假设**，使 MinTRL 估计失真。在加密 + A股双市场项目里推 PSR/MinTRL 却未讨论这一在地化失效，属外推过度，须显式标注 PSR/MinTRL 在 A股的适用边界。

4. **冷启动期合规/适当性（suitability）责任归属未处理。** 在 N=1 且用户是小白时，给出任何带数字的"可信度概率"都可能被理解为投资建议。研究强调 SR 11-7/NIST 治理，却没讨论"证据不足暂不可信"状态如何与监管适当性义务、免责声明、谁担责对齐——这对"到 Binance 实盘/到 paper"的落地是**硬约束**。

5. **"揭示偏好供给集污染"缺可操作破解。** 研究正确指出自我实现回路，但只笼统说"注入探索/多样性配额"，没说如何在 N=1 时把探索成本（给小白展示其会拒绝甚至亏钱的选项）与用户流失/损失对冲——在高后果金融域，推荐系统式的 ε-探索**并不能照搬**。

6. **冷启动期与正常期的明确切换判据缺失。** 何时认为已脱离 N=1 冷启动、可以从"保守隐性 champion 对照"过渡到正常评估？缺少这个状态机定义，会导致系统永远停在过度保守或过早放权两端之一。

7. **LLM 作为对话式偏好引导器的幻觉/诱导性提问偏差只字未提。** 用 LLM 漏斗式澄清问题建用户画像，LLM 本身会以提问框架诱导答案（framing effect），且可能编造对用户风格的归纳——这在风险偏好这种已知易受框架影响的构念上会**放大测量误差**，与 CFA 强调的信度/效度门槛直接冲突。

---

## 9. 参考文献（URL）

1. Probabilistic / Deflated Sharpe Ratio + MinTRL（Bailey & López de Prado, DSR 2014） — https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2460551
2. The Deflated Sharpe Ratio（Bailey & López de Prado, 2014, PDF） — https://www.davidhbailey.com/dhbpapers/deflated-sharpe.pdf
3. The Sharpe Ratio Efficient Frontier / PSR & MinTRL（Bailey & López de Prado, 2012, PDF） — https://www.davidhbailey.com/dhbpapers/sharpe-frontier.pdf
4. Addressing Cold-Start in Product Search via Empirical Bayes（Amazon Science） — https://www.amazon.science/publications/addressing-cold-start-in-product-search-via-empirical-bayes
5. Black-Litterman + 贝叶斯收缩 + 因子模型统一框架（arXiv 2308.09264） — https://arxiv.org/abs/2308.09264
6. User Cold-start Problem in Multi-armed Bandits（ACM TORS, 2023） — https://dl.acm.org/doi/10.1145/3554819
7. 元学习冷启动推荐综述 / AdaMO（Neurocomputing 2024） — https://www.sciencedirect.com/science/article/abs/pii/S0925231224001887
8. LLM 作为 near-cold-start 推荐器（Sanner et al., RecSys'23） — https://ssanner.github.io/papers/recsys23_llmrec.pdf
9. Financial Risk Tolerance: A Psychometric Review（CFA Institute RF, Klement 2017） — https://rpc.cfainstitute.org/research/foundation/2017/financial-risk-tolerance
10. CFA Risk Profiling and Tolerance（Klement 2018, PDF） — https://rpc.cfainstitute.org/sites/default/files/-/media/documents/book/rf-publication/2018/risk_compilation_2018.pdf
11. High-Stakes Personalization: Rethinking LLM Customization for Individual Investor Decision-Making（arXiv 2604.04300, 概念无实证） — https://arxiv.org/pdf/2604.04300
12. Robo-Advisors Beyond Automation（arXiv 2509.09922） — https://arxiv.org/pdf/2509.09922
13. Robo-advising: Learning Investors' Risk Preferences via Portfolio Choices（arXiv 1911.02067） — https://arxiv.org/pdf/1911.02067
14. Filter Bubbles in Recommender Systems: Fact or Fallacy — A Systematic Review（arXiv 2307.01221，引用与论点轻微错位） — https://arxiv.org/pdf/2307.01221
15. Degenerate Feedback Loops in Recommender Systems（Jiang et al., arXiv 1902.10730） — https://arxiv.org/pdf/1902.10730
16. Asking Clarifying Questions for Preference Elicitation With LLMs（arXiv 2510.12015） — https://arxiv.org/pdf/2510.12015
17. Cold-Start Recommendation towards the Era of LLMs: Survey and Roadmap（arXiv 2501.01945） — https://arxiv.org/pdf/2501.01945
18. SR 11-7 模型风险管理（二手来源，建议替换为 Fed/OCC 原文） — https://www.modelop.com/ai-governance/ai-regulations-standards/sr-11-7
19. NIST AI RMF 1.0 + AI 600-1 GenAI Profile — https://www.nist.gov/itl/ai-risk-management-framework
20. DataRobot MLOps Champion/Challenger — https://www.datarobot.com/blog/introducing-mlops-champion-challenger-models/
21. PerformanceAnalytics (R) — MinTrackRecord / ProbSharpeRatio — https://rpkg.net/packages/PerformanceAnalytics/reference/MinTrackRecord.ob
22. Portfolio Optimizer — PSR/MinTRL 文档 — https://portfoliooptimizer.io/blog/the-probabilistic-sharpe-ratio-bias-adjustment-confidence-intervals-hypothesis-testing-and-minimum-track-record-length/
23. skfolio — Prior Estimator（BL/收缩） — https://skfolio.org/user_guide/prior.html
24. ML for Trading（Jansen）多重测试章节 — https://stefan-jansen.github.io/machine-learning-for-trading/08_ml4t_workflow/01_multiple_testing/
