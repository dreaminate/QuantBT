# 22 · 机构模型治理（SR 11-7/SR 26-2/NIST AI RMF/CFA/模型清册）

> 机构级 Agent OS 成品环节深挖 · 全程 Opus 4.8 · 对抗式核查已降权 · 重心=前沿研究+概念级推荐 · 不含 file:line 代码接线
> 簇 D

## 1. 一句话定位

机构模型治理是**最能直接迁移**到本项目 Agent OS 的成熟实践体——因为两者解决同一个核心问题：**一个做决策的产物（模型 / agent）必须被没参与构建它的人信任**。其骨架是 SR 11-7 的"三支柱"（稳健开发实施 + 通过独立验证的有效挑战 + 董事会问责的模型清册），但**2026-04-17 已由 SR 26-2 取代**——SR 26-2 的四个转向（收窄"模型"定义、风险分级而非按日历重检、功能性而非结构性独立、**显式把生成式/agentic AI 排除适用范围**）几乎一一对应到 Agent OS 的设计张力。配上 NIST AI RMF（Govern/Map/Measure/Manage）+ GenAI/Agentic Profile 补 SR 26-2 故意留白的部分，再把 PBO/CSCV + Deflated Sharpe 作为量化失效模式（过拟合回测）的非旁路闸——这构成"流程即信任"流水线里最自然的治理脊柱。**核心价值在真正的有效挑战，不在生产合规文档。**

---

## 2. 前沿 SOTA 与代表系统

| 系统 / 范式 | 它是什么 · 对本环节意味着什么 | URL |
|---|---|---|
| **ValidMind** | 专建的模型风险管理 / 模型验证平台：追踪模型清册与生命周期、自动生成文档、跑验证测试套件、捕捉 developer↔validator 的有效挑战工作流、产出可审计的验证报告与审批；映射 SR 11-7 / SS1/23。2026 年起明确主打 agentic-AI 治理。是**最接近 Agent OS 所需治理层的商业类比**。 | https://validmind.com/platform/ai-model-risk-management/ |
| **ModelOp** | 企业级 AI/模型治理平台，围绕模型清册、生命周期管控、SR 11-7 / NIST AI RMF 合规映射；维护"监管→控制"交叉表（crosswalk）。 | https://www.modelop.com/ai-governance/ai-regulations-standards/sr-11-7 |
| **Yields.io** | MRM 套件，带显式的模型风险分类/分级引擎（重要性、复杂度、相互依赖）与 SR 26-2 过渡指引；是"如何把风险分级落成可操作验证节奏"的有用参照。 | https://www.yields.io/blog/model-risk-classification-in-the-yields-mrm-platform/ |
| **AAGATE + Janus Shadow-Monitor**（CSA Agentic AI RMF Profile 参考架构） | Kubernetes 原生的自治 agent 运行时治理架构：agent 作为非人身份（DID/SPIFFE）、单一"Tool-Gateway Chokepoint"在基础设施层强制工具风险策略（被入侵的模型也无法绕过）、委托链监控、内嵌独立"shadow-monitor" agent 做执行前行为红队。是治理端到端 agentic 流水线的**概念模板**。 | https://labs.cloudsecurityalliance.org/agentic/agentic-nist-ai-rmf-profile-v1/ |
| **MLflow Model Registry**（开源, Linux Foundation） | 模型血缘、版本、阶段流转、实验追踪的事实标准开源方案；可作"机器可读模型清册"的实际底座，阶段流转（staging/production/archived）天然对应验证闸。 | https://mlflow.org/ |

> ⚠️ **核查降权**：上表 AAGATE + Janus 行的"概念模板"措辞已较保守。研究稿原把它作为"battle-tested structure / direct conceptual template"，证据强度被夸大——见第 7 节。它是 CSA/学术**参考架构提案**（arXiv 2510.25863, CSA 2025-12），**非已部署或经独立评测的系统**，不应当作"该模式已被证明有效"的证据，只能当作"该模式已被提出"。

---

## 3. 关键论文（每条带 URL）

1. **SR 26-2: Supervisory Guidance on Model Risk Management**（Fed/OCC/FDIC 跨机构）
   一手来源，2026-04-17 发布，取代 SR 11-7（及 SR 21-8）。收窄"模型"定义（排除简单电子表格/确定性规则软件；模型须运用统计/经济/金融理论且"复杂"）；以**风险分级节奏**替代默认年度重检；从结构性独立转向**功能性独立**。最相关于 >$300 亿美元资产的银行，以下按比例适用。**显式把生成式与 agentic AI 排除**为"新颖且快速演进"，但声明原则仍适用、机构须自建治理。
   https://www.federalreserve.gov/supervisionreg/srletters/SR2602.htm

2. **SR 11-7: Supervisory Guidance on Model Risk Management**（Fed/OCC）
   已被取代但仍是人人引用的概念基岩 2011 框架。三支柱：开发/实施、通过独立验证（概念稳健性 + 结果分析 + 持续监控）的有效挑战、董事会问责的模型清册。"有效挑战 = 由有客观立场、有专业知识的各方做的批判性分析，他们能识别模型局限并促成相应变更。"
   https://www.federalreserve.gov/supervisionreg/srletters/sr1107.htm

3. **AI Risk Management Framework 1.0（NIST AI 100-1）+ Generative AI Profile（NIST AI 600-1）**
   自愿性框架，组织为四个互锁功能——Govern（横切的文化/政策/问责）、Map（情境与影响）、Measure（定量+定性风险评估）、Manage（优先级与应对）。2024 GenAI Profile 增加 12 类 GenAI 专属风险（幻觉、数据泄露、虚构等）并给出 Govern/Map/Measure/Manage 建议动作——这正是 SR 26-2 故意留白处的自然补充。
   https://www.nist.gov/itl/ai-risk-management-framework

4. **The Probability of Backtest Overfitting**（Bailey, Borwein, López de Prado, Zhu）
   提出组合对称交叉验证（CSCV）估计某回测配置过拟合的概率。证明：随试验次数 N 增大，无论真实技能如何，选中过拟合策略的概率趋于 1。是允许用户多策略迭代的流水线的严谨闸门。
   https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2326253

5. **The Deflated Sharpe Ratio**（Bailey & López de Prado, 2014）
   在多重检验、样本长度、非正态（偏度/峰度）下校正 Sharpe 的选择偏差，给出一个在"试了多少次"约束下可辩护的统计显著性检验——一个具体的重检/升级闸。
   ⚠️ **核查降权**：DSR 是在假定零分布下的**尺度/选择偏差校正**（对偏度/峰度修正的正态近似），需选定 N（试验次数）与最大 Sharpe 的假定分布；它讲的是**统计可信度，不是经济稳健性**，对短回测或病态分布脆弱。已知陷阱：DSR 是校正多重检验的"标准化"，**不能根治系统性 Sharpe 高估**，可通过**少报 N 被博弈**。把它当"硬闸"夸大了一个其输出**只与喂给它的试验次数一样诚实**的工具——而这恰是热心的对话式 agent 最不擅长追踪的量。
   https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2460551

6. **Replicating Anomalies（Hou, Xue, Zhang, 2020）& Is There a Replication Crisis in Finance?（Jensen, Kelly, Pedersen, 2023）**
   记录金融的复现危机：Hou-Xue-Zhang 对 447 个异象给出约 35% 的复现率（在其方案下 64–85% 不显著）；Jensen-Kelly-Pedersen 与 Chen-Zimmermann 反驳，认为方法一致时复现率很高。
   ⚠️ **核查降权**：64% 与 85% 的区间来自 HXZ 自家方案里**两个不同 t 门槛**（5% 水平 vs t>3 截断）；该头条数被 Jensen-Kelly-Pedersen 与 Chen-Zimmermann 质疑为 HXZ 的微盘/价值加权方案选择所致的伪象。**这个活跃辩论本身才是教训**：要把它当"有争议"呈现，而非把单一吓人数字当既定事实——应先讲"有争议"再给数字，而非反过来。
   https://www.nber.org/system/files/working_papers/w23394/w23394.pdf

7. **Forking Paths in Financial Economics**（Coqueret, 2024）
   量化研究者自由度：每多一个分析选择，平均 t 统计区间扩 ≥30%；多重检验感知的异象显著门槛是 ≥8.2（而 bootstrap 给约 4.5），远高于常用阈值。主张应**遍历决策树**而非塌缩到单一路径，才能让结论可信。
   https://arxiv.org/abs/2401.08606

8. **Model Cards for Model Reporting（Mitchell et al.）& Datasheets for Datasets（Gebru et al.）**
   标准化、人机皆可读的文档产物：model card 记录预期用途、评测、局限；datasheet 记录数据集动机、构成、采集、预期/禁忌用途、维护。是自动生成、由 agent 产出的模型/数据 dossier 的透明度模板。
   https://arxiv.org/pdf/1810.03993

9. **Lessons From Model Risk Management in Financial Institutions for Academic Research**（Alaghmandan & Streltchenko, 2024）
   主张把 MRM 机器（项目清册、基于影响的风险评级、作为有效挑战的独立再现、指定 owner、完备文档、持续监控）移植到学术研究以对抗不可复现——几乎是把 MRM 移植到 agent 驱动研究流水线的完美类比。指出同行评审"达不到金融机构验证所需的最低标准"。
   ⚠️ **核查降权**：此为 **preprint**（已被 Journal of Risk Model Validation 提及），非正式发表的同行评审定论。
   https://arxiv.org/html/2406.14776v1

---

## 4. 机构最佳实践 / 标准

- **风险分级（Tier 1/2/3）按重要性 = 用途 × 敞口 × 内在风险 × 依赖**；分级至少年度并在重大变更时重评。验证深度/节奏随分级伸缩，重大变更（方法学变化、输出显著漂移）触发临时重检。
  来源：行业 MRM 实践 / Journal of Risk Model Validation；被 SR 26-2 法典化 — https://www.risk.net/journal-of-risk-model-validation/6710566/model-risk-tiering-an-exploration-of-industry-practices-and-principles
  ⚠️ **核查降权（MEDIUM）**：研究稿原给出的精确数字——"低分级 2-3 周工作量 / 顶级约 6 周"、"高风险年度、中等约 2 年、低约 3 年"、"重大变更（>5-10% 输出漂移）触发临时重检"——**在所引 Risk.net 分级文章中查无此说**；它们是被赋予虚假精度、且挂到一个并不陈述这些数字的来源上的二手数字。更糟的是，所引文献**反驳**了该映射：它描述的是高分级全面验证"每两到三年"**外加**对所有分级的年度环境复核——即多种并存惯例，而非已settled 的"高=年度、低=3年"模式。**应作为"多种惯例之一"呈现、剥掉具体数字，或改引一个真正包含这些数字的来源。**

- **有效挑战**：由独立、有专业知识、被赋权、且有动机/能力/影响力去强制变更的各方实施——SR 11-7 的核心，SR 26-2 保留。SR 26-2 把独立性重述为审查的**功能性严谨**而非强制组织分离，允许 validator 嵌入开发（"治理左移")同时保持客观。
  来源：Fed/OCC SR 11-7 §V；SR 26-2 — https://www.federalreserve.gov/supervisionreg/srletters/sr1107.htm

- **董事会问责的完备模型清册**作为记录系统：每个模型（现在是每个 agent）都登记 owner、用途、分级、验证状态、局限、供应商/血缘、重检触发条件。SR 26-2 收窄了"模型"定义，使清册**精确而非臃肿**。
  来源：SR 11-7 / SR 26-2；OCC press release NR-2026-29 — https://www.occ.treas.gov/news-issuances/news-releases/2026/nr-occ-2026-29.html

- **持续应用的三个验证组件**：(1) 概念稳健性（设计/理论是否合理）、(2) 持续监控（在生产中是否仍有效——回测、对标、结果分析）、(3) 结果分析（输出对比实际）。SR 26-2 逐字保留。
  来源：SR 11-7 §V；SR 26-2 — https://www.federalreserve.gov/supervisionreg/srletters/SR2602.htm

- **供应商/第三方模型问责**：使用机构对其未构建的模型（含有限透明度的供应商模型）仍负验证与治理之责。SR 26-2 未变，在 ML/基础模型时代愈发突出。
  来源：SR 11-7 §VII；SR 26-2 — https://www.sullcrom.com/insights/memo/2026/April/OCC-Fed-FDIC-Issue-Revised-Guidance-Model-Risk-Management

- **Agentic-AI 治理控制（SR 26-2 留白处）**：自治分级 + 升级式监督、工具使用风险建模（后果范围 × 不可逆性 × 授权）、单一 tool-gateway chokepoint、agent 身份作为非人身份带审计轨、把每个动作链回责任人的委托/问责登记册、以运行时行为遥测替代周期审计、kill-switch 收敛、独立 shadow/红队监控——"agent 不该验证自己的工作"。
  来源：CSA NIST AI RMF Agentic Profile v1（2026）；Singapore Model AI Governance Framework for Agentic AI（2026-01）— https://labs.cloudsecurityalliance.org/agentic/agentic-nist-ai-rmf-profile-v1/

- **买方适配**：CFA Institute "Investment Model Validation: A Guide for Practitioners" 把 SR 11-7 移植到投资模型；CFA 道德准则 V(A) 要求"合理而充分的依据"，含理解模型假设与局限——是投资决策 agent 的职业操守锚点。
  来源：CFA Institute Research & Policy Center — https://rpc.cfainstitute.org/sites/default/files/-/media/documents/article/rf-brief/investment-model-validation.pdf

---

## 5. 对 QuantBT 这套架构的推荐方向（概念级）

> 仅概念级方向，不点 file:line、不排实施计划。

1. **把产品的信任叙事锚在 SR 26-2（2026-04），而非 SR 11-7。**
   它是现行指引，三大转向是给 Agent OS 的礼物：精确（收窄）的"受治理模型"定义、风险分级而非按日历的重检、功能性而非结构性的独立。但**显式注明 SR 26-2 把生成式/agentic AI 排除适用范围**——所以产品处于监管空白带，应**自愿可见地采纳这些原则**，传达"虽无人要求，我们仍以银行标准自律"。
   ⚠️ 见第 7 节降权：SR 26-2 是**非约束性**、**仅限 >$300 亿资产银行**、且**显式排除本产品的核心技术**。它提供的是**类比结构，不是"借来的信誉"**；声称对齐一个显式排除你系统的标准在修辞上是弱的，且有"SR-26-2 washing"过度声称之险。可迁移价值是**有效挑战这个概念**，不是监管背书。

2. **把"有效挑战"当作中心组织概念，实现为一个结构上独立的 VALIDATOR agent（或验证层），禁止它同时是 BUILDER。**
   遵循 agentic-profile 格言"agent 不该验证自己的工作 / 由独立编排层统一治理所有参与者"。这一选择把"流程即信任"从口号变机制。这里的独立是**功能性的**（不同情境、不同目标、不能编辑 builder 的输出），而非另设公司部门。

3. **把模型/策略 INVENTORY 做成一等记录系统对象，而非副产物。**
   用户共创的每个策略都有一条记录：owner（人类的经济意图）、用途、分级、血缘（数据源、代码、模型产物）、验证状态、已知局限、显式重检触发条件。这是非技术用户、审计者或"未来的你"一眼读懂并信任整个资产组合的产物。

4. **实现风险分级重检，而非固定时间表。**
   按重要性给每个策略分级（在险资本、实盘 vs paper、regime 敏感度、依赖），让分级驱动 validator 重新挑战的频率/深度，外加事件触发（regime 切换、回撤击穿、数据 schema 变更、>X% 输出漂移）。**加密币到 Binance 实盘的策略天然比 A股到 paper 的处于更高分级——把这种不对称编码进去。**

5. **把量化专属失效模式直接做进验证闸：PBO（CSCV）与 Deflated Sharpe 作为自动、不可旁路的检查，并显式核算用户试了多少个策略变体。**
   因为对话式 Agent OS 让批量生成候选变得极易，多重检验/选择偏差风险结构性地**比手工作坊更高**——把试验次数当成显式受治理量并据此折扣显著性。配以强制 OOS / walk-forward 与"分叉路径"意识。
   ⚠️ 见第 7/8 节：DSR/PBO 是**选择偏差闸**，**不**捕捉幸存者偏差、delisting 偏差、look-ahead/PIT 完整性、交易成本与市场冲击、regime 非平稳性。一个策略可通过 DSR/PBO 却仍是在幸存者偏差宇宙上的纯数据窥探。"不可旁路闸"框架有**虚假安心**之险。

6. **用 NIST AI RMF 的 Govern/Map/Measure/Manage 心智模型作为 agent 带用户走的生命周期脊柱，把 Govern 当横切（常开的政策/问责）而非一个阶段。**
   用 GenAI 与 Agentic Profile 补 SR 26-2 不覆盖的部分：自治分级、对任何有真实后果动作（尤其实盘下单）的 tool-gateway chokepoint、运行时行为遥测、kill-switch/收敛、把每个 agent 动作链回人类已陈述意图的委托/问责登记册。

7. **把文档 dossier 自动生成为标准化、人类可读的产物（model-card + datasheet 风格：预期用途、数据出处、假设、局限、验证证据、禁忌用途）。**
   让非技术经济学家拿到一份易读的"为何可信"叙事——把合规文档从开销变成产品的**信任 UX 核心**。生成正是 agent 擅长的；人类负责复核/审批而非撰写。

8. **内化诚实批判以避免建成合规剧场。**
   文献显示 MRM 常退化为打勾、三道防线的独立性常空心、模型被用来给已定决策背书。设计上要让 validator 的挑战能真正**block 升级到实盘**（硬闸，带一个本身被记录为问责的人类 override 日志），并让人类提供真实经济判断而非橡皮图章。差异化在**真有效挑战，不在产出文档的体量**。

9. **把比例原则当 UX 原则，呼应 SR 26-2 收窄的模型定义。**
   别为琐碎/管道步骤淹没用户于治理之中——把重量级有效挑战、DSR/PBO 闸与完整文档保留给达到"这是有真实敞口的真策略/模型"门槛的对象。让小账户 A股 paper 实验体验轻盈，同时对在险资本的加密实盘保持最大严谨。

---

## 6. 架构级参考（少量伪代码 / schema 草图，非代码接线）

> 示意草图，不接线到现有代码。

**6.1 模型/策略清册条目 schema（记录系统）**

```yaml
inventory_entry:
  strategy_id: str
  owner_intent: str               # 人类的经济意图, 非技术 owner
  purpose: str
  is_governed_model: bool         # SR 26-2 收窄定义: 运用统计/经济理论且"复杂"=true;
                                  #   纯算术/管道步骤=false → 不进重量级治理
  tier: low | medium | high       # = 用途 × 敞口 × 内在风险 × 依赖
  exposure: paper | live          # Binance live 自动抬级
  lineage:
    data_sources: [tushare@snapshot, binance@snapshot]
    code_commit: sha
    model_artifacts: [ml/*.pkl | dl/*.pt]
    agent_stack_models:           # ⚠️ 见第8节: agent 自身的 LLM 也是
      builder: claude-opus-4-8    #   "有限透明度供应商模型", 须当受治理依赖追踪
      validator: <异家族/异版本>
  validation_status: pending | passed | blocked | overridden
  known_limitations: [...]
  recert_triggers:                # 事件触发, 非按日历
    - regime_shift
    - drawdown_breach
    - data_schema_change
    - output_drift > X%
```

**6.2 风险分级重检节奏（概念，非固定时间表）**

```
A股 paper (low)      → 轻量: 单 OOS 切片 + PBO 闸 + 精简 model-card
Binance live (high)  → 完整: walk-forward 多切片 + DSR/forking-paths 折扣
                       + 独立 validator agent 有效挑战 + 完整 dossier
                       + 上线前 champion/challenger 影子运行
事件触发 (任意分级)  → regime 切换 / 回撤击穿 / schema 变更 / 输出漂移 → 临时重检
# ⚠️ 重检触发用"事件"驱动; SR 26-2 PDF 中并无"年度"默认 (见第7节)
```

**6.3 有效挑战裁决 + 可问责 override（概念伪代码）**

```python
def effective_challenge(candidate, validator):   # validator: 异家族、不能编辑 builder 输出
    gates = run_deterministic_gates(candidate)    # PBO/CSCV, DSR(N=显式试验数), forking-paths
    challenges = validator.find_holes(            # LLM 仅产"挑战/漏洞", 不打数值分
        candidate.public_artifacts_only)          # 禁看 builder 中间推理 → 保功能性独立
    decision = "BLOCK" if any(g.failed for g in gates) else "PASS"
    if decision == "BLOCK" and human_overrides():
        audit_log.record(                         # override 本身即问责记录
            who="user", reason=..., gate_failed=...,
            # ⚠️ 单用户场景下此 log 自服务、无第三方问责 (见第8节)
            #   应配硬仓位上限 + 冷静期, 用户不可单方撤销
        )
        decision = "OVERRIDDEN"
    return Verdict(decision, gates, challenges, reproducible=True)
```

---

## 7. 降权 / 争议 / 陷阱（对抗核查结论）

> 对抗核查总判：**对抗式审查下异常扎实**——承载性监管论点经一手来源审查后仍成立，部分甚至逐字确认（罕见）。SR 26-2 真实（2026-04-17，Fed/OCC/FDIC）、确实取代 SR 11-7/SR 21-8，其四个头条特征（收窄模型定义、功能性而非结构性独立、风险分级比例、显式生成式+agentic AI 排除且原则仍适用）均对照 PDF 确认，多为近逐字。量化引用（Coqueret 8.2-vs-4.5、PBO/CSCV、DSR、HXZ vs JKP）准确，且诚实标注了复现辩论而非择樱桃。AAGATE/Janus、Singapore MGF、BPI 游说、Alaghmandan-Streltchenko 类比论文均核实。**未发现撤稿或杜撰来源。可辩护的批评都是 FRAMING 与 PRECISION 问题，非事实问题。**

**MEDIUM 严重度**

- ⚠️【二手数字 + 虚假精度，与所引来源相悖】**机构分级具体数字**——"低分级 2-3 周 / 顶级约 6 周"、"高风险年度、中等约 2 年、低约 3 年"、">5-10% 输出漂移触发临时重检"，挂到 Risk.net Journal of Risk Model Validation。直接检索该来源**无法浮现** 6 周/2-3 周、5-10% 输出漂移、年度/2年/3年这些数字；它们是被赋予虚假精度、且钉在一个**不陈述这些数字**的来源上的二手数字。更糟：所引文献**反驳**了该映射——它描述高分级全面验证"每两到三年" + 对所有分级的年度环境复核，即**多种并存惯例**，而非 settled 的"高=年度、低=3年"模式。应作"多种惯例之一"呈现、剥掉具体数字，或改引真正含这些数字的来源。（已在第 4 节就地降权。）

- ⚠️【证据成熟度披露不足，参考架构被卖得太接近"已验证"】**AAGATE + Janus Shadow-Monitor 被当作"battle-tested structure / direct conceptual template"**，其模式（不可绕过的 tool-gateway chokepoint、执行前 shadow 红队）被当成已验证的设计胜利。证实为真但**未充分披露成熟度**：AAGATE 是 CSA/学术**参考架构**（arXiv 2510.25863, CSA 2025-12）——一个 Kubernetes 原生控制面**提案**，**非已部署或经独立评测的系统**。**无任何已发表证据**表明其"不可绕过 chokepoint"或 Janus 执行前监控真能以宣称的命中率在生产中捕捉目标操纵/幻觉利用。与对 PROV-AGENT 所标的同一外部效度警示适用：单作者/单组织参考设计不应被引为该模式有效的证据，只能引为该模式已被提出。（已在第 2 节就地降权。）

**LOW 严重度**

- ⚠️【框架叙事过度，把行业惯例误归于监管文本】**"SR 26-2 以风险分级节奏替代默认年度重检"**（summary + 把 SR 11-7 框为"默认年度"的 pitfall）。对照 SR 26-2 一手 PDF 核实：'annual'、'revalidate'、'cadence'、'calendar'、'schedule'、'interval' 出现**零次**。SR 26-2 讲的是"与重要性相称"的严谨、"周期性复审相关性"——它**从未**设定或移除年度默认。SR 11-7 本身的文本**也从未**强制年度重检；年度是**行业惯例/解读**，非监管文本（经 Risk.net/Domino 分析确认）。所以"SR 26-2 把金融业从一个监管的年度默认中解放出来"这个干净故事是**过度简化**：SR 11-7 在原则上本就风险分级，是实践把它僵化了。**实质（风险分级节奏）正确；"从年度转向"的叙事把行业习惯误归于指引文本。**

- ⚠️【过度推销为硬闸】**Deflated Sharpe Ratio 被当"可辩护的统计显著性检验"与"具体的重检/升级闸"**。DSR 是假定零分布下的尺度/选择偏差校正（对偏度/峰度修正的正态近似），需选定 N（试验次数）与最大 Sharpe 的假定分布——它讲**统计可信度，不是经济稳健性**，对短回测或病态分布脆弱。已知陷阱（DSR 是校正多重检验的"标准化"，**不能根治系统性 Sharpe 高估**）意味着可通过**少报 N 被博弈**。把它当硬、可辩护的"闸"夸大了一个其输出**只与喂给它的试验次数一样诚实**的工具——而这恰是热心的对话式 agent 最不擅长追踪的量。（已在第 3 节就地降权。）

- ⚠️【过度倚重非约束性标准换"借来的信誉"】**把 SR 26-2 框为"2026 产品更重要的参照"、给 Agent OS"借来的信誉"与"银行标准"自律**。研究稿自己的 pitfalls 部分覆盖了这点，但 summary/设计方向仍**过度倚重**。SR 26-2 (a) **显式非约束**（机构声明单凭不合规不触发批评）、(b) **仅限 >$300 亿资产银行**管理信贷/资本/AML 决策模型、(c) **显式把生成式与 agentic AI 排除**——即它否认了产品所建之上的那项技术。所以该文档提供的是**类比结构，不是"借来的信誉"**；声称对齐一个显式排除你系统的标准在修辞上弱、且有"SR-26-2 washing"过度声称之险。可迁移价值是**有效挑战这个概念，不是监管背书**。

- ⚠️【复现率头条框架先吓人后 caveat】**复现率头条（"447 个异象中 64-85% 不显著"、"约 35% 复现率"）**。数字准确引自 Hou-Xue-Zhang，且研究稿**确实标注了辩论（好）**。但 64% vs 85% 的区间来自 HXZ 自家方案里**两个不同 t 门槛**（5% 水平 vs t>3 截断），且头条被 Jensen-Kelly-Pedersen 与 Chen-Zimmermann 质疑为 HXZ 微盘/价值加权方案选择所致的伪象（Chen-Zimmermann：在发表偏差下 t 门槛甚至不可识别）。研究稿大体处理了这点，但 summary 仍**先抛吓人数字再给 caveat**——应**先讲"有争议"**。（已在第 6 条论文就地降权。）

**通用陷阱清单（设计须规避）**

- 把 SR 11-7 当现行 → 它已于 2026-04-17 被 SR 26-2 取代；SR 26-2 当一手参照，SR 11-7 当历史/基础。
- 以为银行级框架能干净映射 → SR 26-2 仅限 >$300 亿资产银行、关乎银行决策模型（信贷/资本/AML）、**显式排除生成式与 agentic AI**；对面向散户的量化 Agent OS **无法律约束力**。其价值是借来的可信度与久经考验的结构，**非合规义务**。**不要过度声称"SR-26-2 合规"。**
- 合规剧场之险 → 产出华丽却没人读、也从不 block 坏策略的验证文档。证据（Risk.net "model risk manager 的孤独"、BPI 推动废除 SR 11-7）显示这是 MRM 实践中**主导**失效模式——有产物无牙齿。
- 假独立 → 与 builder 共享情境/提示/激励的 validator agent 不是有效挑战，它会合理化。独立须功能性，且 validator 必须能真正 block。
- 多重检验盲区 → 让生成策略变体无摩擦的对话式界面会大幅膨胀选择偏差/回测过拟合；朴素 Sharpe 或单次回测会系统性高估。复现危机与分叉路径文献显示连资深研究者都会自欺——除非追踪试验次数并折扣显著性，热心的 agent 只会更糟。
- 三道防线 cargo-cult → 该模型因二线独立性弱、保证割裂、缺口/重复、抑制正当冒险的防御姿态而被广泛批评。**借职责分离的理念，别借官僚机器。**
- 过宽的"一切皆受治理模型"范围（SR-26-2 前的错误）→ 把每个电子表格/工具当模型会膨胀清册、稀释对真正重要策略的注意力。SR 26-2 故意收窄了这点；镜像该比例原则。
- 二手数字 → 复现率数字（35% vs 64-85% 不显著）来自不同方案的竞争研究、且**正被激烈争论**（HXZ vs JKP vs Chen-Zimmermann）。**把辩论呈现出来，别把单一头条当 settled 事实。**
- 把周期（年度）审计当自治 agent 足够 → agentic 治理文献明确：agent 发起动作与人类观察之间的时间差是新风险维度，需**运行时遥测与执行前检查**，而非事后复核——尤其在任何 Binance 实盘下单之前。

---

## 8. 开放问题

> 以下为对抗核查指出的**漏点（missing angles）**，研究稿完全缺席或仅一句带过，是落地前必须回答的。

1. **EU AI Act 完全缺席——而它是真正具约束力的制度。** 不同于自愿性的 SR 26-2 与 Singapore MGF，EU AI Act 把许多金融决策/信用评分 AI 系统归为高风险，自 2026 起强制风险管理、日志、人类监督与上市后监控义务。对触及 A股与 Binance 用户的产品，**硬法制度比一封非约束性的美国银行信件是更实质的治理锚**，却完全缺席。

2. **实际用户的辖区错配。** 产品瞄准中国 A股与加密币到 Binance，但所引治理制度全是美国（SR 26-2、NIST）、新加坡或美国学术。缺失：中国的算法/AI 治理规则（CAC 算法推荐规定、生成式 AI 暂行办法）与任何加密/VASP 行为预期（EU 的 MiCA、Binance-邻近资金流的 MAS）。**治理脚手架借自错误辖区。**

3. **单用户、单供应商 agent 产品独有的利益冲突/自我交易失效模式未处理。** 银行里有效挑战之所以有效，部分因 validator 的职业与 builder 的盈亏独立。在一个单用户 Agent OS 中，同一供应商构建 builder 与 validator 两个 agent 并从用户参与/交易中获利——**两个来自同一实验室、共享同一基础模型的 agent 之间的"功能性独立"比研究稿承认的结构性更弱**：共享的基础模型会共享同样的盲点/过拟合先验，从而击穿整个设计赖以成立的独立性。

4. **回测过拟合工具不完整。** CSCV/PBO 与 DSR 是选择偏差闸，但研究稿遗漏了加密/A股散户情境里更深更难的问题——universe 的幸存者偏差与 delisting 偏差、look-ahead/point-in-time 数据完整性（已是项目既有关切）、交易成本与市场冲击建模、regime 非平稳性。**一个策略可通过 DSR/PBO 却仍是在幸存者偏差 universe 上的纯数据窥探。**"不可旁路闸"框架有虚假安心之险。

5. **在对话式产品中运行结构上独立的 validator agent + shadow-monitor + 每策略自动 dossier 的成本/延迟/UX 未分析。** 银行 MRM 机器假设每模型多周、多 FTE 预算；把它移植到一个"让批量生成候选变得极易"的聊天界面，可能让每次迭代慢/贵——研究稿当作风险的那个无摩擦性，也让所提治理在经济上很重。比例原则方向触及了这点，但**没有 breakeven 在哪的估计**。

6. **责任与"记录的人类 override"设计。** 研究稿提议带记录人类 override 作为问责的硬闸，却未处理：对散户用户，这条 override 日志是**自服务的**（用户 override 自己的 validator、交易自己的钱），它**不提供**银行审计轨那样的第三方问责。问责登记册概念借自多方机构场景，在单用户场景下可能是剧场——除非系在有牙齿的东西上（如用户不可单方撤销、需冷静期的硬仓位上限）。

7. **agent 自身所跑基础模型的版本/漂移。** SR 26-2 的供应商模型问责点被引用，却未**反身应用**——builder/validator agent 依赖第三方 LLM（Anthropic/OpenAI），其权重与行为在无通知下变化，是 SR-26-2 意义上的不可验证、有限透明度供应商模型。模型清册应把 agent 栈自身的模型版本当受治理依赖追踪，而设计方向从未提及（已在第 6.1 节 schema 里以注释补上 `agent_stack_models` 字段）。

---

## 9. 参考文献（URL）

**监管 / 标准**
- SR 26-2 Interagency Model Risk Management Guidance（Fed/OCC/FDIC, 2026-04-17）— https://www.federalreserve.gov/supervisionreg/srletters/SR2602.htm
- SR 26-2（PDF 一手原文）— https://www.federalreserve.gov/supervisionreg/srletters/SR2602.pdf
- SR 11-7 Supervisory Guidance on Model Risk Management（Fed/OCC, 2011）— https://www.federalreserve.gov/supervisionreg/srletters/sr1107.htm
- OCC press release NR-2026-29 — https://www.occ.treas.gov/news-issuances/news-releases/2026/nr-occ-2026-29.html
- OCC/Fed/FDIC Revised Guidance 分析（Sullivan & Cromwell）— https://www.sullcrom.com/insights/memo/2026/April/OCC-Fed-FDIC-Issue-Revised-Guidance-Model-Risk-Management
- NIST AI Risk Management Framework（AI 100-1 / AI 600-1）— https://www.nist.gov/itl/ai-risk-management-framework
- NIST AI RMF Playbook — https://www.nist.gov/itl/ai-risk-management-framework/nist-ai-rmf-playbook
- CSA NIST AI RMF Agentic Profile v1（AAGATE/Janus 参考架构）— https://labs.cloudsecurityalliance.org/agentic/agentic-nist-ai-rmf-profile-v1/
- AAGATE 参考架构论文（arXiv 2510.25863）— https://arxiv.org/pdf/2510.25863
- Singapore Model AI Governance Framework for Agentic AI（IMDA, 2026-01-22）— https://www.imda.gov.sg/resources/press-releases-factsheets-and-speeches/press-releases/2026/new-model-ai-governance-framework-for-agentic-ai
- CFA Institute, Investment Model Validation: A Guide for Practitioners — https://rpc.cfainstitute.org/sites/default/files/-/media/documents/article/rf-brief/investment-model-validation.pdf

**复现危机 / 统计闸**
- Bailey, Borwein, López de Prado & Zhu, The Probability of Backtest Overfitting (PBO/CSCV) — https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2326253
- Bailey & López de Prado (2014), The Deflated Sharpe Ratio — https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2460551
- Coqueret (2024), Forking Paths in Financial Economics — https://arxiv.org/abs/2401.08606
- Hou, Xue & Zhang, Replicating Anomalies（NBER w23394）— https://www.nber.org/system/files/working_papers/w23394/w23394.pdf
- BPI says SR 11-7 should go; bank model risk chiefs say no（Risk.net）— https://www.risk.net/risk-management/7963135/bpi-says-sr-11-7-should-go-bank-model-risk-chiefs-say-no
- Model Risk Tiering: industry practices and principles（Risk.net JRMV）— https://www.risk.net/journal-of-risk-model-validation/6710566/model-risk-tiering-an-exploration-of-industry-practices-and-principles

**治理工具 / 文档产物**
- ValidMind（AI 模型风险管理平台）— https://validmind.com/platform/ai-model-risk-management/
- ValidMind Library（开源 Python SDK）— https://docs.validmind.ai/about/overview-model-risk-management.html
- ModelOp（SR 11-7 / NIST AI RMF 映射）— https://www.modelop.com/ai-governance/ai-regulations-standards/sr-11-7
- Yields.io（模型风险分级引擎）— https://www.yields.io/blog/model-risk-classification-in-the-yields-mrm-platform/
- MLflow Model Registry — https://mlflow.org/
- DVC (Data Version Control) — https://dvc.org/
- whylogs / WhyLabs（数据日志 + ML 监控）— https://github.com/whylabs/whylogs
- Mitchell et al., Model Cards for Model Reporting（arXiv:1810.03993）— https://arxiv.org/pdf/1810.03993

**MRM↔学术研究类比**
- Alaghmandan & Streltchenko (2024), Lessons From MRM for Academic Research（arXiv:2406.14776, preprint）— https://arxiv.org/html/2406.14776v1
