# 研究证据附录 · 17 条主线

> 本文件由研究 workflow（40 agent / 270 万 token / 887 次工具调用）自动汇编。每条主线含：机构级标准 → 关键论文（带 URL）→ SOTA 方法 → QuantBT 现状 → 差距 → Agent OS 角色 → 建议 → 对抗式核查裁决。

> 核查裁决用于给论断**降权**：`confirmed` 可信、`nuanced` 需限定、`outdated`/`refuted` 已被纠正（综合层已吸收纠正）。


---


## [1] Agent OS 架构与多agent编排  · 组 A

**机构级标准** — 在"研究→生产"的中低频量化场景，机构级 Agent OS 的标准不是"最聪明的单个 agent"，而是"在治理导轨上可被审计的、可恢复的、人在闭环的工程自动化层"。具体应满足：(1) 编排形态分层——用确定性工作流引擎(DAG/状态图)作骨架、把 LLM 自主性收敛在被良好界定的节点内，而非让 agent 自由编排彼此(Cognition/MAST 的核心教训)；只有在"可大规模并行、信息超出单上下文窗、子任务弱耦合"的环节(如文献/因子海搜索)才用 orchestrator-worker 多 agent(Anthropic 标准)。(2) 持久化记忆与状态分层——遵循 CoALA 的 working/episodic/semantic/procedural 四类记忆，跨会话持久(谁、何时、基于哪个 dataset_version、得出什么结论、被哪个门驳回)。(3) 长程鲁棒性——harness 负责 checkpoint/可恢复/从 git 与进度文件"恢复上下文"，因为"agent 是有状态的、错误会复利"(Anthropic)。(4) 全链路 provenance——用 W3C PROV 式统一谱系图把 prompt/response/工具调用/产出/下游指标串成可审计 DAG(PROV-AGENT)。(5) 评测即治理——LLM-as-judge + 人审捕捉盲点 + end-state 评测。(6) human-in-the-loop 闸门——经济判断/资本配置/上线必须 interrupt-and-approve、可持久挂起数小时/数天(LangGraph durable interrupt)。(7) 渐进披露——把严谨度翻译成非技术用户能读懂、能信任的自然语言与流程可视化。底线判据：一个读不懂代码的经济学者，能否仅凭谱系、验证闸门与预注册记录，独立判断 go/no-go。


### 关键论文 / 权威实践

- **How we built our multi-agent research system** ([链接](https://www.anthropic.com/engineering/built-multi-agent-research-system))
  - _Anthropic (Applied AI / Research team) · 2025 · Anthropic Engineering Blog_
  - 权威工程实践：orchestrator-worker(lead agent 规划+并行派 3-5 subagent，各自独立 200K 上下文窗、互不知晓、不中途协调)在 BrowseComp 上比单 agent Opus4 高 90.2%，但耗约 15x token(vs chat)、4x(vs 单 agent)；明确给出何时不该用多 agent(需共享上下文/强依赖/大多数 coding)。还给出关键工程教训：token 用量解释 80% 性能方差、subagent 写文件系统避免'传话游戏'、lead agent 在截断前把计划存外部记忆、'agent 有状态错误会复利'需 checkpoint 恢复而非重启、彩虹部署、LLM-as-judge 评测从小样本起步。
- **Towards an AI Co-Scientist** ([链接](https://arxiv.org/abs/2502.18864))
  - _Gottweis, Weng, Daryin, Tu, Palepu, Vahdat 等 (Google DeepMind/Research) · 2025 · arXiv:2502.18864 (后续相关结果 2026 上 Nature)_
  - 面向科学假设生成的多 agent 系统范本：Supervisor 把六个专门 agent(Generation 生成/Reflection 同行评议式批判/Ranking Elo 锦标赛两两对决+模拟科学辩论/Evolution 进化精炼/Proximity 文献近邻/Meta-review 元综述)放入异步任务队列、按需弹性分配算力；'scientist-in-the-loop'——科学家提种子想法或自然语言反馈即可介入；test-time compute 越多自评质量越高。给量化研究'假设登记→生成→对抗式评议→排序→进化'闭环提供直接可借鉴的角色化结构。
- **Cognitive Architectures for Language Agents (CoALA)** ([链接](https://arxiv.org/abs/2309.02427))
  - _Theodore R. Sumers, Shunyu Yao, Karthik Narasimhan, Thomas L. Griffiths · 2023 · arXiv:2309.02427 (TMLR)_
  - 把语言 agent 用认知科学/符号 AI 框架系统化：模块化记忆(working/episodic/semantic/procedural)+ 结构化动作空间(内部 reasoning/retrieval/learning vs 外部 grounding)+ 决策循环(planning→execution)。是 Letta/Mem0/LangChain 等主流记忆框架的分类学基础，为 Agent OS 的持久记忆与谱系总线提供经过同行验证的架构语言。
- **Why Do Multi-Agent LLM Systems Fail? (MAST)** ([链接](https://arxiv.org/abs/2503.13657))
  - _Cemri, Pan, Yang, Agrawal, Chopra, Tiwari, Keutzer, Parameswaran 等 (UC Berkeley) · 2025 · arXiv:2503.13657 (NeurIPS 2025 poster)_
  - 首个经验性多 agent 失败分类学：分析 7 个主流 MAS 框架 200+ 任务、1600+ 标注轨迹(Cohen's Kappa 0.88)，归纳 14 种失败模式归三大类——规范缺陷、agent 间错位、任务验证不足(如违背任务规范 11.8%、步骤重复 15.7%、不识别终止条件 12.4%)。是对抗式核查'多 agent 一定更好'神话的关键证据，指向治理与验证而非堆 agent。
- **PROV-AGENT: Unified Provenance for Tracking AI Agent Interactions in Agentic Workflows** ([链接](https://arxiv.org/abs/2508.02866))
  - _R. Souza, A. Gueroudji, S. DeWitt, D. Rosendo, T. Ghosal, R. Ross, P. Balaprakash, R. F. da Silva (Oak Ridge NL) · 2025 · IEEE e-Science 2025 (arXiv:2508.02866)_
  - 用扩展的 W3C PROV 数据模型 + MCP 概念，把 prompt/response/模型调用/工具动作/遥测统一成端到端 provenance 图(Campaign/Workflow/Task 为 PROV Activity，数据对象用 used/generated 关系连接)。为'非程序员靠谱系信任 agent'这一硬约束提供标准化、可审计的技术底座。
- **Don't Build Multi-Agents** ([链接](https://cognition.ai/blog/dont-build-multi-agents))
  - _Walden Yan (Cognition) · 2025 · Cognition Engineering Blog_
  - 前沿争议中的'单 agent'立场：两条原则——(1)共享上下文且共享完整 agent 轨迹(非单条消息)，(2)动作携带隐含决策、冲突决策导致坏结果。推荐单线程线性 agent + LLM 历史压缩器；仅在子任务窄域'回答问题而非做架构决策'时才用 ephemeral subagent。与 Anthropic 形成2025年6月著名对立，是架构选型必须权衡的反方。
- **Effective context engineering for AI agents** ([链接](https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents))
  - _Anthropic · 2025 · Anthropic Engineering Blog_
  - 把上下文窗当受限计算资源管理：compaction(接近上限时高保真摘要后重启上下文)、结构化笔记、memory tools(跨会话持久存取)、context-awareness(每次工具调用后反馈剩余容量)、programmatic tool calling。是长程量化研究 agent 不丢上下文的工程基线。

### SOTA 方法

- **确定性工作流图 + 节点内 LLM 自主(workflow-as-graph)** `[established]` — 用 LangGraph/状态机式 DAG 作确定性骨架，LLM 只在被良好界定的节点内自主；内建 checkpoint/durable execution、可挂起的 human-in-the-loop interrupt、时间旅行回溯。LangGraph 1.0(2025-10)被广泛视作生产级默认。最契合量化'流程即治理'——把假设登记/验证/审批门固化成图节点，而非托付 agent 自由编排。
- **Orchestrator-Worker 多 agent(lead + 并行 subagent)** `[established]` — lead agent 规划并派发独立上下文窗的 subagent 并行检索/探索，最后由 lead 综合 + 独立引用核查。Anthropic 实证在可并行、信息超窗的研究任务上 +90.2%，但 ~15x token。量化中适用于因子海/文献海/参数空间的并行扫描子环节，不适合需共享上下文的组合构建/执行。
- **角色化科学方法 agent 联盟 + Elo 锦标赛排序** `[emerging]` — Google AI co-scientist 范式：Generation/Reflection/Ranking/Evolution/Proximity/Meta-review 分工，假设经模拟辩论的 Elo 两两对决排序、Evolution 迭代精炼。可直接映射到量化'假设生成→对抗式评议→排序→进化'，且 Elo 排序天然给非技术用户一个可读的'谁更可信'信号。
- **CoALA 四类记忆 + 跨会话持久 state** `[established]` — working(当前任务上下文)/episodic(具体研究事件轨迹)/semantic(沉淀的事实与结论)/procedural(可复用技能/代码)。配合 compaction、结构化笔记、memory tools 实现长程不丢上下文。是 Agent OS '持久记忆+谱系总线'的分类学骨架。
- **统一 provenance 图(W3C PROV + MCP)** `[emerging]` — PROV-AGENT 把 agent 的 prompt/response/工具调用/产出/下游指标接成可审计 DAG。对量化是把'数据→因子→标签→模型→信号→组合→回测→实盘'与 agent 决策合并成一张谱系图——预注册/谱系/验证闸门由此变成可机读、可回放的对象。
- **MCP(工具/资源接入) + A2A(agent 间协作)双协议** `[emerging]` — MCP 标准化 agent↔工具/数据(many-to-one-to-many)，A2A 标准化 agent↔agent 任务化对话(many-to-many)。对'资产无关'硬约束有价值：新品类靠'填配置'接 connector 即作为 MCP 工具暴露，不重写流程。
- **单线程 agent + 历史压缩器(Cognition 立场)** `[contested]` — 反多 agent 立场：单 agent 持有完整上下文，长任务用 LLM 历史压缩器，subagent 仅做窄域'回答问题'。对耦合强、需一致决策的环节(组合/执行)更稳。与多 agent 形成选型权衡。
- **渐进披露式可信解释(progressive disclosure XAI)** `[emerging]` — 按用户即时需求分层披露透明度信息、用对比式自然语言解释、按置信度做'口头对冲'(verbal hedging)防过度依赖。是把工程严谨度翻译给小白/经济学者的 HCI 方法基线。

### 差距

- 编排形态停在'散的单 agent'：现有 AgentRuntime 是单线程 reAct(max_steps=6)、无 orchestrator-worker、无并行 subagent、无确定性工作流图骨架；M13 的 DAG 引擎(croniter/重试/SLA)与 M14 的 agent loop 各自独立，没有把'agent 自主'收敛进'治理导轨'里——正是 MAST/Cognition 警示的'规范缺陷+决策分散'高风险区。
- 无跨全程持久记忆/谱系总线：conversations.py 只持久化 chat thread + 5 步状态机，缺 CoALA 式 episodic/semantic/procedural 记忆；M12 的 lineage(parent/forked_from)是实验级而非 agent 级，没有 PROV-AGENT 式把 prompt/工具调用/产出/下游指标统一成可审计 DAG。非技术用户'靠谱系信任'的硬约束尚无技术底座。
- 无长程 harness 的 durability：AgentRuntime 无 checkpoint/可恢复/从进度文件恢复上下文，一旦中断或错误即丢失，违反 Anthropic'agent 有状态、错误会复利、须从 checkpoint 恢复'原则；长研究流(拉数→因子→训模→验证)跨多上下文窗会断裂。
- human-in-the-loop 闸门未'agent 原生化'：M20 Live Ladder/降级阻断与 M9 KillSwitch 是执行层硬护栏，但 agent 编排层缺 LangGraph 式 durable interrupt-and-approve——即'经济判断/资本配置/上线'作为可持久挂起数小时/数天的图节点。目前审批是页面动作，不是编排状态。
- 无 agent 间通信/共享上下文标准：13 个 OpenAPI 工具是 RPC 风格，未走 MCP；没有 A2A 式 agent 协作语义。与'资产无关靠填配置接入'目标的契合度低——新品类接入仍偏代码而非声明式工具注册。
- 评测即治理缺位于 agent 层：M10 有 PBO/DSR/Bootstrap CI 等方法学闸门，但没有 LLM-as-judge 对 agent 产出(因子假设质量/引用准确性/规范遵从)的自动评分 + 人审捕盲点流程，无法在 agent 生成阶段就拦截 MAST 类失败。
- 渐进披露未系统化为信任层：M19 Glossary L1-L4 与 coach 是教学碎片，没有把'置信度口头对冲、对比式解释、流程进度可视化、谱系可回放'整合成面向小白/经济学者的统一'信任面板'。

### Agent OS 在这一环的角色（服务零代码用户）

这一环是整个愿景的'信任脊柱'，因为非技术用户读不懂代码，只能靠'流程即信任'。具体走法：(1)需求澄清——把 M14 slot-filling 升级为 Google co-scientist 式'scientist-in-the-loop'：经济学者用自然语言出一个模糊念头(如'低估值+动量在熊市更稳')，澄清 agent 把它登记成良构、可证伪的假设卡(预期符号/适用 regime/对照基准/失败判据)，这一步本身就是预注册，且用经济学语言而非代码呈现。(2)走流程——确定性工作流图作导轨，每个环节(拉数/写因子/训模/验证)由 agent 自主执行工程，但产出沉淀进持久记忆并实时挂上谱系图；用户看到的不是日志，而是'我现在在生命周期的哪一格、基于哪个 dataset_version、上一格的结论是什么'。(3)翻译严谨度——把 PBO/DSR/IC-IR 等指标用渐进披露翻译：默认层只给一句经济学判断('这个 alpha 在你设定的对照下，过拟合概率约 X%，相当于换一批历史它大概率不灵'),想深究再逐层展开公式与谱系；按置信度做'口头对冲'(对低置信结论明确说'证据较弱')防过度依赖。(4)go/no-go 闸门——经济判断与风控用 durable interrupt：agent 在审批门停下、用自然语言陈述'为什么该批/该拒'与可回放的谱系证据，人只出意图与判断，agent 出全部工程。这样'严谨的流程治理本身'变成用户能读、能信、能问责的对象——Elo 排序/谱系 DAG/验证闸门/预注册记录，都是非程序员可直接解读的信任信号。

### 建议

- 引入确定性工作流图骨架统一 M13(DAG)与 M14(agent loop)：把'假设登记→数据→因子→标签→模型→信号→组合→回测→审批→上线'固化成图节点，LLM 自主性收敛在节点内执行；节点间用 LangGraph 式 checkpoint 持久化、可恢复、时间旅行。这是把'散的 agent'拧成'有流程导轨的 Agent OS'的核心一步，也直接对冲 MAST 的规范缺陷/决策分散失败。  `[→M13+M14(新增 orchestrator 层), eff=high, lev=high]`
- 建 PROV-AGENT 式统一谱系总线：用 W3C PROV 风格 schema 把每次 agent 的 prompt/response/工具调用/产出/dataset_version/下游指标接成可审计 DAG，复用并扩展 M12 的 lineage(parent/forked_from)。这是'非技术用户靠谱系信任'硬约束的技术底座，也是预注册与模型风险问责的载体。  `[→M12(谱系扩展)+M11(生命周期事件接谱系), eff=high, lev=high]`
- 给 AgentRuntime 加长程 harness：session 起步先读'进度文件+git/谱系'恢复上下文、按 Anthropic compaction 做高保真摘要重启上下文窗、每节点结束留 clean checkpoint。先解决'长研究流跨上下文窗断裂'这一最痛点，effort 中等但杠杆高。  `[→M14(runtime 增强), eff=med, lev=high]`
- 把 human-in-the-loop 升级为 agent 原生 durable interrupt：在工作流图的'经济判断/资本配置/上线'节点用可持久挂起(数小时/数天)的 interrupt-and-approve，agent 用自然语言陈述 go/no-go 理由 + 可回放谱系证据；与 M20 Live Ladder/M9 KillSwitch 衔接但抬到编排层。  `[→M14+M20+M9, eff=med, lev=high]`
- 在'假设生成/因子海搜索/文献海'等可并行子环节引入 orchestrator-worker(lead+并行 subagent，subagent 写文件系统避免传话游戏)，并配 Elo/对抗式评议给候选打分排序——给非技术用户一个可读的'谁更可信'。严格限定只在弱耦合、信息超窗环节用，组合/执行仍走单线程(尊重 Cognition 立场)。  `[→M14(多 agent 子模块)+M6/M4, eff=high, lev=med]`
- 把 13 个 OpenAPI 工具改造为 MCP 工具注册 + 用 MCP 暴露 DataConnector/ExecutionVenue，使'资产无关靠填配置接入'落地为声明式工具注册而非重写流程；预留 A2A 语义供后续多 agent 协作。  `[→M3+M9+M14, eff=med, lev=med]`
- 加 LLM-as-judge + 人审捕盲点的 agent 产出评测层：对因子假设质量、引用准确性、规范遵从打 0-1 分(小样本起步 20 例)，在生成阶段就拦截 MAST 类失败；评分与谱系挂钩。  `[→M10+M12, eff=med, lev=med]`
- 把 M19 Glossary/coach 整合成统一'信任面板'：渐进披露(默认一句经济学判断→逐层展开公式/谱系)、按置信度口头对冲、流程进度可视化、谱系可回放。这是把严谨度翻译给小白/经济学者的临门一脚，复用已有组件 effort 低。  `[→M19+M15(前端信任面板), eff=low, lev=high]`

### 对抗式核查裁决 — 总体置信度：**high**

_纠正摘要_: All seven cited works are real and substantially accurately described — no fabricated papers. Verdicts: among citations, 6 confirmed + 1 nuanced; among the six substantive claims, 4 confirmed + 3 nuanced; none refuted. Key facts verified against primary sources: Anthropic +90.2% / ~15x-token / 80%-variance / when-not-to-use; MAST 14 modes + Kappa 0.88 + 1600+ traces + 7 frameworks; co-scientist's 6 agents + Elo tournament + test-time-compute self-eval; CoALA authors/2023; PROV-AGENT 'Preliminary Evaluation' + ORNL additive-manufacturing HPC use case; Cognition's two principles + June 12 2025 date; Profit Mirage information-leakage; plus the two 2026 supplementary papers (2603.14586, 2601.02371). Corrections/caveats to flag: (1) The 'Effective context engineering' post (Sep 29 2025) confirms compaction + structured notes + memory tools, but the listed 'per-tool-call remaining-capacity feedback' and 'programmatic tool calling' were NOT found in that specific article and appear conflated from other Anthropic posts — trim or re-source those two. (2) PROV-AGENT is explicitly a 'Preliminary Evaluation' on an ORNL metal-3D-printing HPC workflow and does NOT address non-programmer readability of provenance DAGs — so it cannot be cited as evidence that economists/non-technical users can interpret lineage; Claim 4's skepticism is vindicated. (3) The dark-patterns paper 2603.14586 is real but is about conversational pedestrian NAVIGATION, not finance — it supports Claim 5 only by analogy; don't imply it studies financial decisions. (4) The MCP-security paper 2601.02371 is 'Permission Manifests for Web Agents' (web-agent-oriented, but explicitly covers MCP/A2A), supporting Claim 6's attack-surface concern; the specific conflict with the project's internal SecureKeystore/HMAC/withdraw-deny guardrails is sound internal design reasoning that no external source validates. (5) Minor author-list completeness: MAST and co-scientist cite correct subsets ('et al.' covers the rest). Net: the research brief is well-grounded and free of hallucinated citations; the multi-agent-vs-single-agent and information-leakage warnings are accurate and appropriately hedged, and the three 'needs-scrutiny' claims (3, 5, 6) are correctly framed as open questions rather than settled facts.

被降权/纠正的论断：
- `nuanced` — Cited post: 'Effective context engineering for AI agents' (Anthropic 2025) — context window as limited compute resource; compaction (high-fidelity summary near limit then restart), structured notes, memory tools (cross-session persistence), context-awareness (remaining-capacity feedback after each tool call), programmatic tool calling.
  - 纠正：Two of the five listed techniques (per-tool-call remaining-capacity feedback; programmatic tool calling) were not confirmed in this article and may be conflated from other Anthropic material (e.g., the code-execution-with-MCP / tool-use posts). The core 3 (compaction, structured notes, memory tools) are solidly attributed. Treat the technique list as mostly-but-not-fully accurate to this specific source.
- `nuanced` — Claim 3: 'LangGraph durable execution + checkpoint solves long-horizon robustness' needs scrutiny for maturity and pitfalls (state bloat, in-flight agents during version deploys, rainbow-deploy difficulty) in real multi-day / multi-window quant flows, rather than adopting per marketing.
  - 纠正：Verdict nuanced because the claim is a (correct) call for scrutiny rather than a refutation; the named pitfalls are corroborated by Anthropic's engineering post, but no source proves or disproves LangGraph's specific maturity for multi-day quant flows — it remains genuinely unvalidated, which is exactly what the claim asserts.
- `nuanced` — Claim 5: 'Progressive disclosure + verbal hedging calibrates non-technical-user trust and prevents over-reliance' needs scrutiny — XAI research is mostly general-domain; in high-stakes finance, contrastive explanations may instead manufacture false certainty (dark-pattern risk, cf. 2603.14586); translating PBO/DSR to 'overfit probability ~X%' in NL may mislead statistical understanding.
  - 纠正：The cited dark-patterns paper is real and on-topic for explainability/dark-patterns, but its domain is conversational navigation, NOT financial decision-making — the citation is supportive-by-analogy, not direct financial evidence. The claim should not imply 2603.14586 studies finance. Otherwise the caution is valid and appropriately hedged.
- `nuanced` — Claim 6: MCP/A2A as an 'asset-agnostic plug-in-by-config' path — standard maturity and security boundaries need scrutiny; MCP tool exposure at the order/withdrawal execution layer may add new attack surface (permission manifest 2601.02371), possibly conflicting with existing SecureKeystore/HMAC self-signing/withdraw-deny guardrails.
  - 纠正：The cited paper is titled 'Permission Manifests for Web Agents' (web-agent permission manifests), not a generic 'permission inventory list'; it is web-agent-oriented but explicitly covers MCP/A2A, so it supports the claim. The note about conflict with project-internal SecureKeystore/HMAC/withdraw-deny guardrails is internal-design reasoning that no external source confirms or denies — treat as a design caution, not externally validated.

---


## [2] 需求澄清/意图引导 agent  · 组 A

**机构级标准** — 在世界顶级量化机构与方法学共识中，"需求澄清/意图引导"这一环的标准不是"把用户的话变成参数"，而是"把一个模糊念头转化为一个可证伪、预注册、经济逻辑明确的研究假设"，并在此过程中守住三道闸：(1) 经济先验先于数据——任何因子/策略必须先有可陈述的经济或行为学因果机制(风险溢价、行为偏差、市场摩擦、信息扩散)，再谈检验；CFA/资管研究治理要求"假设登记"早于看任何回测数字，以防数据窥探(de Prado 的七宗罪之首)。(2) 假设必须形式化为可检验 spec：标的池(PIT、含退市以防幸存者偏差)、调仓频率、信号方向/强度、持有期、目标度量、基准、OOS/嵌牢期(embargo)、停止规则与"什么结果会让我放弃这个假设"——即预注册(pre-registration)的金融版。(3) 澄清过程本身要做"温和现实检验":主动识别用户陈述中的无依据先验(过拟合预期、近因/趋势追逐、对夏普/胜率的误解、对收益的不切实际锚定)，用经济学语言而非代码反推。机构级标准还要求澄清 agent 校准(calibrated)地"问 vs 假设":对低信息量细节不过度追问、对会改变结论的关键缺失必问(对应 ClarEval 的 Efficiency-Adjusted Recall、Active Task Disambiguation 的信息增益准则)，并对每一次澄清留痕(谱系/lineage)，使非技术用户可凭"流程可复现"而非"读代码"来信任产出。


### 关键论文 / 权威实践

- **Eliciting Human Preferences with Language Models (GATE: Generative Active Task Elicitation)** ([链接](https://arxiv.org/abs/2310.11589))
  - _Belinda Z. Li, Alex Tamkin, Noah Goodman, Jacob Andreas (MIT/Stanford) · 2023/2024 · ICLR 2025 (arXiv 2310.11589)_
  - 奠基性工作。提出让 LM 主动通过自由形式提问/生成边界案例来引导用户把模糊意图说清楚(三类变体:开放式提问、是非提问、生成 informative 边界样例)。预注册实验在内容推荐/道德推理/邮件校验三域显示:交互式 elicitation 比用户自写 prompt 或少样本标注更 informative、用户付出更少、且能挖出用户原本没想到的维度。这是 QuantBT '需求澄清 agent' 的直接理论母板。
- **STaR-GATE: Teaching Language Models to Ask Clarifying Questions** ([链接](https://cicl.stanford.edu/papers/andukuri2024stargate.pdf))
  - _Chinmaya Andukuri 等 (Stanford CICL) · 2024 · arXiv / COLM 2024_
  - 用 STaR 式自我改进训练模型主动提澄清问题:与模拟 persona roleplay,只对那些最终能引出更高质量回答的提问轨迹做自训练强化。证明'先问再答'显著优于直接假设。给 QuantBT 提供了'如何让 agent 学会问好问题'的训练范式(而非纯 prompt)。
- **Modeling Future Conversation Turns to Teach LLMs to Ask Clarifying Questions** ([链接](https://arxiv.org/abs/2410.13788))
  - _Michael J.Q. Zhang, Eunsol Choi 等 · 2024/2025 · ICLR 2025 (arXiv 2410.13788)_
  - 核心洞见:'该不该问'的训练信号应来自模拟未来对话——把所有可能的用户解读都展开,看'先问一个澄清问题'相比'直接假设'在期望意义上能否提升最终满意度。把'ask-vs-assume'从启发式变成可优化目标。
- **Active Task Disambiguation with LLMs** ([链接](https://arxiv.org/abs/2502.04485))
  - _（Bayesian Experimental Design 框架） · 2025 · ICLR 2025 (arXiv 2502.04485)_
  - 把澄清问题选择形式化为贝叶斯实验设计:在'可能解空间'上最大化期望信息增益(EIG)来挑下一个问题,而非生成任意文本问句。直接回应'over-clarify 低价值细节 / under-clarify 关键缺失'的痛点,是 QuantBT 给澄清排序的最严谨数学准则。
- **CLAMBER: A Benchmark of Identifying and Clarifying Ambiguous Information Needs in LLMs** ([链接](https://aclanthology.org/2024.acl-long.578/))
  - _Zhang, Qin, Deng, Huang, Lei, Liu, Jin, Liang 等 · 2024 · ACL 2024 (arXiv 2405.12063)_
  - 约 12,000 条数据的歧义识别/澄清基准 + 歧义类型分类法。关键发现:现成 LLM 即便加 CoT/few-shot 也在'识别+澄清'上实用性有限,且这些技巧会带来过度自信、改进甚微——证明'需求澄清能力不会随便涌现,必须专门工程化'。
- **Ask or Assume? Uncertainty-Aware Clarification-Seeking in Coding Agents** ([链接](https://arxiv.org/abs/2603.26233))
  - _Michael J.Q. Zhang, Eunsol Choi · 2025/2026 · arXiv 2603.26233_
  - 在 underspecified SWE-bench Verified 上系统评估'问 vs 假设';提出把'欠规格检测'与'执行'解耦的不确定性感知多 agent 脚手架,multi-agent (OpenHands+Claude Sonnet 4.5) 解决率 69.4% vs 单 agent 61.2%,且不确定性校准良好:简单任务省着问、复杂任务主动问。直接对应 QuantBT 把'澄清'与'回测执行'分层。
- **Biased Echoes: Large language models reinforce investment biases and increase portfolio risks of private investors** ([链接](https://journals.plos.org/plosone/article?id=10.1371/journal.pone.0325459))
  - _Winder, Hildebrand, Hartmann · 2025 · PLOS ONE_
  - 3×3×3 因子实验(风险偏好×年龄×ChatGPT/Gemini/Copilot,270 个组合)证明 LLM 投资建议系统性放大本土偏好(93% 美股 vs 59% 基准)、行业集中、近因/趋势追逐(前三只股 27.92%)、过度主动管理(51%)、高费率,抬升五维组合风险、降低风险调整后收益。这是'温和现实检验'必须存在的硬证据:不加 anti-sycophancy 护栏的澄清 agent 会强化而非纠正用户偏差。
- **Can LLM-based Financial Investing Strategies Outperform the Market in Long Run?** ([链接](https://arxiv.org/abs/2505.07078))
  - _Waylon Li, Hyeonjun Kim, Mihai Cucuringu, Tiejun Ma · 2025 · KDD 2025 (arXiv 2505.07078)_
  - 20 年、100+ 标的的系统回测显示:此前文献报告的 LLM 择时优势在更宽截面、更长期评估下显著消失(此前结果受幸存者/数据窥探偏差高估);LLM 策略牛市过保守、熊市过激进。给澄清 agent 的现实检验提供量化弹药:用户'让 AI 帮我择时跑赢大盘'的念头本身需要被温和证伪。
- **LLMREI: Automating Requirements Elicitation Interviews with LLMs** ([链接](https://arxiv.org/abs/2507.02564))
  - _Korn, Gorsch 等 · 2025 · arXiv 2507.02564_
  - 对话式需求工程实证:LLM 访谈机器人(zero-shot vs least-to-most)在 33 场模拟干系人访谈中,错误率与人类访谈者相当、能抽取大部分需求、且能生成高度上下文相关的问题。为'把对话需求工程移植到策略需求澄清'提供方法与评测先例。
- **MARE: Multi-Agents Collaboration Framework for Requirements Engineering** ([链接](https://arxiv.org/pdf/2405.03256))
  - _Jin 等 · 2024 · arXiv 2405.03256_
  - 端到端多 agent 需求工程协作框架(像人类 RE 团队那样分角色迭代:elicitation→modeling→verification→spec)。为 QuantBT 把'需求澄清'从单 prompt 升级为'澄清-建模-验证-形式化 spec'的多 agent 流水线提供参照架构。

### SOTA 方法

- **GATE / 生成式主动任务引导 (Generative Active Task Elicitation)** `[established]` — 让 LM 主动用自由问题+生成边界案例引导用户说清意图,优于被动 prompt/少样本。在偏好与价值类任务上是当前最被引用的范式。
- **信息增益驱动的提问选择 (Bayesian Experimental Design / Expected Information Gain over solution space)** `[emerging]` — 在'可能解空间'上用 EIG 给候选澄清问题排序,只问最能区分假设的问题。理论最干净,直接治'过度/不足澄清';在结构化任务(API/代码)上已验证。
- **Ask-vs-Assume 校准 (uncertainty-aware clarification, calibrated when-to-ask)** `[emerging]` — 用模拟未来对话或不确定性估计决定该问还是该假设,并把欠规格检测与执行解耦。ClarEval 的 Efficiency-Adjusted Recall 是配套评测。多 agent 脚手架已显示校准良好。
- **自训练问澄清问题 (STaR-GATE 式 self-improvement)** `[emerging]` — 对'能引出更好最终答案'的提问轨迹做自训练强化,让模型学会问好问题而非靠 prompt。范式可行但对策略域需自建奖励/模拟用户。
- **对话式需求工程 / 多 agent RE (MARE, LLMREI, Elicitron, iReDev)** `[emerging]` — 把软件需求工程的 elicitation→modeling→verification→spec 流程迁到 LLM 多 agent;LLMREI 证明访谈错误率与人类相当。映射到'念头→形式化策略 spec'高度自然。
- **歧义类型分类 + 类型条件化澄清 (CLAMBER taxonomy, AT-CoT)** `[established]` — 先判定歧义类型(词汇/语义欠规格/认知不确定)再生成对应澄清。基准显示纯 CoT/few-shot 不够,需类型化引导。
- **金融领域 anti-sycophancy / 去偏护栏 (gentle reality check)** `[contested]` — 针对 LLM 在投资建议中放大用户偏差/迎合(sycophancy/reward hacking)的纠偏:红队/反方视角提示、去偏 prompt、sycophancy-aware reward。在金融上证据强(Biased Echoes),但'如何温和纠偏而不劝退新手'仍是开放且有争议的设计问题。

### 差距

- 澄清止于槽位、未抵达'可证伪假设':现有 slot_filling.py 是 regex/中英混排抽取(杠杆/回撤/单标的)填进 StrategyGoal schema,M19 有 5 步 SOCRATIC_DECISION 状态机(refuse/ask/explain/recommend_experiment)。但产出的是参数化 StrategyGoal,不是带'经济机制陈述 + 可证伪条件 + 放弃条件(stop rule)'的预注册假设。机构标准要求'先有经济先验与可证伪 spec,再看数据'——这一步缺失。
- 提问无信息论排序、无 ask-vs-assume 校准:SOCRATIC_DECISION 是规则状态机,不是 GATE/EIG 那样按期望信息增益挑问题,也没有 Modeling-Future-Turns/Ask-or-Assume 的'该问还是该假设'校准。后果:对低价值细节可能过度追问、对会改变结论的关键缺失(基准?OOS 窗?标的池 PIT?)可能不问(CLAMBER 已证明这种能力不会自发涌现)。
- 缺'温和现实检验'护栏,且现有 Coach 偏顺从风险:Biased Echoes/长跑 LLM 策略证据表明,不加 anti-sycophancy 的对话会强化用户的过拟合预期与近因/趋势追逐偏差。QuantBT 的 risk_summary 7 规则作用在'回测之后'(PBO/DSR/MaxDD…),而现实检验应前移到'澄清阶段'——在用户还没跑回测前,就用经济学语言温和证伪'让 AI 帮我择时跑赢大盘'之类无依据念头。
- 澄清谱系/预注册留痕未与 lineage 闭环:M12 有 ExperimentStore/RunStore lineage,但'用户的原始念头→澄清问答轨迹→最终形式化假设→预注册时间戳'这条链未作为不可变记录贯通。非技术用户的信任唯一支柱是'流程可复现/可审计',这条澄清谱系必须可回放。
- 歧义类型未显式建模:无 CLAMBER 式歧义分类法,无法区分'用户没说清调仓频率(语义欠规格)'与'用户对夏普理解错误(认知偏差,需教学纠偏)'——两者澄清策略完全不同。
- 无对'澄清充分性'的量化闸门:没有 ClarEval 的 Efficiency-Adjusted Recall 类指标来判定'澄清是否覆盖了把假设变可检验所需的全部关键槽',因此无法给出'澄清完成度'这一可向用户展示的进度/信任信号。

### Agent OS 在这一环的角色（服务零代码用户）

这一环是 Agent OS 面向'零代码小白/经济学者'的真正入口,设计要点四条。(1) 渐进披露的苏格拉底引导:对小白用低门槛问题(你认为什么样的股票/币会涨?为什么?这是别人没发现的吗?),把答案翻成经济机制语言(你说的是'动量'——价格趋势延续,背后是投资者反应不足);对经济学者直接收形式化先验(因子族、风险溢价假设),复用 M19 L1-L4 渐进披露。(2) 把'问题'转成'假设',再转成'spec':GATE 式主动提问 + Active Task Disambiguation 的信息增益排序,只问能把'念头'变'可证伪假设'的关键缺口(经济机制?标的池含退市否?调仓频率?基准?OOS 窗?什么结果会让你放弃?),最后吐出一份用户读得懂的'假设卡'(自然语言机制 + 形式化 StrategyGoal + 预注册 stop rule),而非一堆参数。(3) 严谨度的翻译=经济学语言 + 流程即信任:把'幸存者偏差/PIT/embargo/数据窥探'翻成'如果只看活下来的公司,你会高估收益''先押注再看数据,否则你只是在过去里找巧合';把每一次澄清写进不可变谱系(原始念头→问答→形式化假设→时间戳),让读不懂代码的人靠'我能回放整条推理、它预先承诺了放弃条件'来信任。(4) human-in-the-loop 的边界:工程(拉数/写因子/跑验证)agent 全自主,但'经济机制是否成立''是否值得继续'的 go/no-go 必须用户拍板——澄清 agent 的职责是把判断点清晰呈现给用户,而不是替他下判断;且对'让 AI 替我择时跑赢大盘'这类念头做温和现实检验(给证据、给反方视角),既不顺从(防 Biased Echoes 式放大偏差)也不劝退,而是引导改成一个可检验的小假设。

### 建议

- 把 StrategyGoal 升级为'可证伪假设卡(HypothesisSpec)':在现有 schema 上增三个必填字段——economic_mechanism(自由文本,经济/行为学因果机制)、falsification_condition(什么 OOS 结果会判这个假设失败)、stop_rule(放弃/退役条件),并在澄清未填满这三项前不允许进入回测。这是把'参数填充'抬升到'机构级预注册假设'的最小改动,直接补最大 gap。  `[→M1 StrategyGoal / app/backend/app/strategy_goal.py, eff=med, lev=high]`
- 给 SOCRATIC_DECISION 状态机加'信息增益式提问排序':对候选澄清问题,按'回答后能否把假设从模糊推向可证伪/会否改变最终 go-no-go'打分(GATE/Active Task Disambiguation 的 EIG 思想的轻量实现:用 LLM 枚举该问题的几种可能回答,看它们是否导向不同的 spec/结论),只问 top 问题,避免过度/不足澄清。  `[→M14 Agent / agent/coach.py SOCRATIC_DECISION + agent/conversations.py, eff=med, lev=high]`
- 新增'澄清阶段的温和现实检验规则'(reality-check rules),与回测后的 risk_summary 对称:在用户陈述出现过拟合预期(我要夏普>3)、近因/趋势追逐(最近涨得好的)、择时跑赢大盘等无依据先验时,触发引用证据的温和反方提示(可直接引用 Biased Echoes / 长跑 LLM 策略结论),并把念头改写成一个可检验小假设。显式做 anti-sycophancy(红队视角 prompt),防止 Coach 顺从放大偏差。  `[→M19 / eval/risk_summary.py 的前移版 + agent/prompts/MODE2_SYSTEM_PROMPT_ZH, eff=med, lev=high]`
- 把澄清谱系接入 lineage:记录'原始念头→每轮澄清问答→最终 HypothesisSpec→预注册时间戳'为不可变 RunStore 记录,并在前端'假设卡'上展示可回放的澄清轨迹与预注册时间。这把'流程即信任'落成对非技术用户可见的产物。  `[→M12 实验/注册表 ExperimentStore/RunStore lineage + M15 前端假设卡, eff=med, lev=high]`
- 引入 CLAMBER 式歧义类型分类(语义欠规格 vs 认知偏差/误解)作为澄清前置:前者走'补槽提问',后者走'M19 教学纠偏(边问边教)'。两条路由用同一份 Glossary L1-L4 供给,实现'边问边教'。  `[→M19 Glossary + M14 Agent 路由, eff=low, lev=med]`
- 为'澄清充分性'定义一个可展示进度的闸门指标(借 ClarEval 的 Efficiency-Adjusted Recall 思想):列出把假设变可检验所需关键槽清单(机制/标的池 PIT/频率/基准/OOS/stop rule),实时算覆盖率,作为'澄清完成度'进度条 + 进入回测的硬闸,同时控制提问轮数(惩罚啰嗦)。  `[→M1+M14 澄清闸门 + M15 前端进度, eff=low, lev=med]`
- 中长期:用 STaR-GATE/Modeling-Future-Turns 范式离线训练/蒸馏一个'会问策略澄清问题'的小模型或 few-shot 库——以模拟用户(不同水平 persona)+ 该轮提问是否提升最终假设质量为奖励,沉淀成可复用的提问策略库,降低对大模型在线调用与 prompt 漂移的依赖。  `[→M14 Agent 训练/few-shot 库(可与 v3 训练台复用 harness), eff=high, lev=med]`

### 对抗式核查裁决 — 总体置信度：**high**

_纠正摘要_: 十篇论文全部真实存在、arXiv/会议 ID 与核心结论基本可核实,六条论断在方法论上整体健康且对抗性保留意见多数成立(尤其论断4机制区分最严谨)。但发现三处事实性错误需修正:(1) 严重——'Ask or Assume?'(arXiv 2603.26233)被误署为 Michael J.Q. Zhang / Eunsol Choi,实际作者是 Nicholas Edwards 与 Sebastian Schuster;疑似与'Modeling Future Conversation Turns'(2410.13788,确为 Zhang/Choi)张冠李戴,故该条论断判 refuted(数字 69.4% vs 61.2%、Sonnet 4.5、校准良好全部正确,仅署名错)。(2) 'Can LLM Outperform Market in Long Run?'(2505.07078)被标 KDD 2025,实为 KDD 2026。(3) 'Modeling Future Conversation Turns'(2410.13788)漏署中间作者 W. Bradley Knox。次要精度问题:CLAMBER 漏末位作者 Tat-Seng Chua;LLMREI 可补 Vogelsang;Biased Echoes '270 个组合'应理解为 27 条件×10 次提示且 LLM 为 ChatGPT 3.5。这些错误均不动摇各论断的科学结论与'需在 QuantBT 自建验证、不可直接外推'的整体立场,但论文卡片署名/年份必须更正以免学术引用失真。论断1/2/5/6/4 判 confirmed,论断3因依附论文署名错误整体判 refuted(其机制层保留意见单列为 confirmed)。

被降权/纠正的论断：
- `nuanced` — 论文真实性核查: 'Modeling Future Conversation Turns to Teach LLMs to Ask Clarifying Questions', Michael J.Q. Zhang / Eunsol Choi 等, arXiv 2410.13788, 2024/2025
  - 纠正：作者应补为 Michael J.Q. Zhang, W. Bradley Knox, Eunsol Choi。论文实质与结论描述准确。
- `refuted` — 论文真实性核查 + 论断3: 'Ask or Assume? Uncertainty-Aware Clarification-Seeking in Coding Agents', 引述署名 Michael J.Q. Zhang / Eunsol Choi 2025/2026, arXiv 2603.26233;multi-agent 69.4% vs single 61.2% 且校准良好。
  - 纠正：作者必须改为 Nicholas Edwards, Sebastian Schuster。把它误署为 Zhang/Choi 是实质性错误(可能与上一篇 Future Conversation Turns 混淆)。论断3 关于'校准良好能否迁移金融假设澄清、提升是否值多 agent 复杂度成本'的保留意见本身成立。
- `nuanced` — 论文真实性核查: 'Can LLM-based Financial Investing Strategies Outperform the Market in Long Run?', Waylon Li / Hyeonjun Kim / Mihai Cucuringu / Tiejun Ma 2025, arXiv 2505.07078, 引述标注 'KDD 2025'。
  - 纠正：应改为 KDD 2026(论文 2025 年挂 arXiv,但会议是 2026)。引述把它标成'KDD 2025'是事实错误,虽不影响结论的科学性。

---


## [3] 非程序员做机构量化 + 信任即流程 + 经济学语言解释  · 组 A

**机构级标准** — 这一环（让非程序员靠对话做机构级量化 + 把统计严谨度翻译成可信、可懂的东西）的机构级标准，是三件事的合流：(1) 受众分层的可解释性治理：顶级机构不再把"可解释性"当一个开关，而是按受众分层产出解释——CFA Institute 2025《Explainable AI in Finance: Addressing the Needs of Diverse Stakeholders》明确识别六类干系人（其中多数是非技术用户：业务决策者/PM/合规/风控/客户/审计），要求对非技术受众用反事实("若收入再高 5000 美元，贷款就批了")、热力图、部分依赖图、规则化近似，而非裸 SHAP 数字。(2) 经济因果先行、再做数据挖掘：学术与机构共识是"先有可证伪的经济/因果假设，再回测"，而不是先跑搜索再编故事——Harvey-Liu-Zhu(2016) 因子动物园证明在多重检验下新因子需 t>3.0 而非 2.0；López de Prado《Causal Factor Investing》(Cambridge Elements, 2023) 进一步要求画出因果图、识别混淆/对撞偏倚，否则"因子海市蜃楼"。(3) 治理即信任 = 可复现 + 谱系 + 独立验证 + 模型风险问责：监管侧 SR 11-7 要求"有效挑战(effective challenge)"——独立于开发者、具同等专业/权限的验证职能；工程侧把可复现/数据谱系/版本化当作非技术用户信任读不懂的代码产出的唯一技术支柱（"当模型出问题时，能追溯用了哪份代码、哪份数据、谁改过"）。合起来：非程序员被允许产出策略的前提，是平台用流程导轨强制"假设→预注册→独立验证闸门→受众分层解释→人类 go/no-go"，并对每一步留可审计谱系。把统计严谨翻译成经济学语言（为什么这个 alpha 该有效、它在赌哪个风险溢价、什么环境会失效），是让经济学者能做"经济判断"而非"代码判断"的接口。


### 关键论文 / 权威实践

- **… and the Cross-Section of Expected Returns** ([链接](https://www.nber.org/system/files/working_papers/w20592/w20592.pdf))
  - _Campbell R. Harvey, Yan Liu, Heqing Zhu · 2016 · Review of Financial Studies 29(1):5-68 (NBER w20592)_
  - 奠基性多重检验框架：盘点 316 个已发表因子，论证在如此规模的数据挖掘下标准 t>2.0 完全失效，新因子需 t>3.0 才可信。是'非程序员大规模生成策略'最直接的对照警钟——平台越易产出候选，多重检验惩罚必须越严。
- **Causal Factor Investing: Can Factor Investing Become Scientific?** ([链接](https://www.cambridge.org/core/elements/causal-factor-investing/9AFE270D7099B787B8FD4F4CBADE0C6E))
  - _Marcos López de Prado · 2023 · Cambridge Elements in Quantitative Finance_
  - 主张因子研究必须从关联转向因果：要求显式画出因果图、识别混淆/对撞偏倚，否则因子是'海市蜃楼'。为'经济学语言解释'提供了机构级骨架——解释不是事后讲故事，而是事前的可证伪因果假设。直接支撑'人出经济判断、agent 出工程'的分工。
- **Explainable AI in Finance: Addressing the Needs of Diverse Stakeholders** ([链接](https://rpc.cfainstitute.org/research/reports/2025/explainable-ai-in-finance))
  - _Cheryll-Ann Wilson (CFA Institute Research & Policy Center) · 2025 · CFA Institute Research Report_
  - 机构级的'受众分层可解释性'权威范本：识别六类干系人(多数非技术)，建议对非技术用户用反事实/热力图/规则化近似而非裸 SHAP；明确点出过度信任(confirmation bias)、可解释性无统一基准、解释泄露隐私三大风险。是 L1-L4 渐进披露的直接机构背书。
- **The Probability of Backtest Overfitting** ([链接](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2326253))
  - _David H. Bailey, Jonathan Borwein, Marcos López de Prado, Qiji Jim Zhu · 2017 (SSRN 2013) · Journal of Computational Finance_
  - 提出 CSCV 估计回测过拟合概率 PBO，把'试了多少种配置'这一隐藏自由度变成可量化的信任指标。对非程序员尤为关键：他们看不懂代码，但能看懂'这个策略有 73% 概率是过拟合'。QuantBT M10 已实现 PBO/DSR。
- **AlphaAgent: LLM-Driven Alpha Mining with Regularized Exploration to Counteract Alpha Decay** ([链接](https://arxiv.org/abs/2502.16789))
  - _(RndmVariableQ et al.) · 2025 · ACM SIGKDD 2025_
  - SOTA 的 LLM-agent 选因子前沿：用 AST 相似度强制原创性、假设-因子语义一致性校验、AST 复杂度上限抑制过拟合，直接对抗'LLM 生成同质化因子加速拥挤/衰减'。是 Agent OS 自动产因子时'防过拟合护栏'的可借鉴蓝本。
- **Automate Strategy Finding with LLM in Quant Investment**
  - _Kou et al. (HKUST, HKUST-GZ, Peking U.) · 2024 · arXiv:2409.06289_
  - 三阶段框架(Seed Alpha Factory 从文献抽因子 → 多模态多 agent 评估含 Confidence/Risk 两 agent → 神经网络权重优化)。坦承局限：LLM 生成的因子常'理论成立但实操不可行、缺金融直觉'、对 regime 切换脆弱——正好印证'人类经济判断不可外包'。
- **101 Formulaic Alphas**
  - _Zura Kakushadze · 2016 · Wilmott / arXiv:1601.00991_
  - 公开 WorldQuant 101 个公式化 alpha，证明'人可读公式即可执行代码'这一范式——alpha 表达为价格/量/VWAP 的显式数学式。是 QuantBT M4 的 AST 表达式引擎与白箱算子的直接思想来源，也是把'代码'翻译成经济学者能读的'公式'的桥梁。
- **Versioning, Provenance, and Reproducibility in Production Machine Learning** ([链接](https://mlip-cmu.github.io/book/24-versioning-provenance-and-reproducibility.html))
  - _Christian Kästner (CMU, ML in Production) · 2024 · CMU MLIP 教材章节_
  - 系统论证版本化/谱系/可复现是问责、审计、调试、安全取证的技术地基——即'读不懂代码的人靠可追溯性建立信任'的工程依据。映射 QuantBT M12 lineage(parent/forked_from) 与 dataset_version 不可变。

### SOTA 方法

- **受众分层 / 渐进披露式可解释性 (Audience-tiered, progressive-disclosure XAI)** `[established]` — 按受众(小白→经济学者→quant)和层级(全局摘要→局部归因→技术细节)分层产出解释；非技术用户先看高层启发式与反事实，按需下钻。CFA Institute 2025 报告与 HCI 文献(Incremental XAI, arXiv:2404.06733; Progressive Disclosure, arXiv:1811.02164)双重背书。直接对应 QuantBT 的 L1-L4 渐进披露。
- **经济因果先行 / 假设预注册再回测 (Causal-rationale-first; pre-registered hypothesis)** `[established]` — 先写下可证伪的经济假设与因果图，再做回测；López de Prado 因果因子投资 + Harvey-Liu-Zhu 多重检验。学术共识强烈，但'强制预注册'在私域实践中仍非普遍流程，落地形态各异。
- **可复现性/数据谱系作为信任机制 (Reproducibility & provenance as trust)** `[established]` — 用不可变数据版本、run lineage、模型注册表把'读不懂代码'转化为'可审计可追溯'，作为非技术用户信任的支柱。工程界共识(MLflow/数据版本化/SR 11-7 模型清单)。QuantBT M12 已实现。
- **过拟合概率量化 (PBO/CSCV, Deflated Sharpe Ratio)** `[established]` — 把'隐藏的多重检验自由度'量化为单一可读数字(过拟合概率、收缩后夏普)，让非程序员能直接读懂'这策略多大概率是噪音'。Bailey-López de Prado 系列，学界广泛接受但对其假设(IID、收益分布)有方法学争论。QuantBT M10 已实现。
- **LLM 多 agent 自动策略/因子发现 (LLM multi-agent alpha mining)** `[emerging]` — 用 Idea/Factor/Eval 多 agent + AST 原创性与复杂度正则自动产因子(AlphaAgent SIGKDD'25; Kou et al. 2024; AlphaLogics)。是 Agent OS '工程全自主'的前沿，但作者自承缺金融直觉、易同质化加速衰减、对 regime 脆弱。
- **众包 meta-model + 经济激励对齐 (Numerai 质押-抹除 / WorldQuant BRAIN 积分)** `[contested]` — 用质押(NMR erasure)或积分/分级把'非雇员产出的信号'纳入统一 meta-model，靠激励机制而非代码审查保证质量；Numerai 2024 旗舰基金净回报 25.45%。是'非程序员贡献入机构组合'的最成熟商业范式，但其'抹除质押/匿名'模型与受监管资管的可问责性张力大。
- **自然语言→策略一键部署 (NL-to-strategy, no-code deploy)** `[contested]` — 用户用自然语言描述想法→自动生成可执行策略→回测→一键上实盘(Gate 无代码 AI 量化、BigQuant、QuantConnect no-code builder)。商业上活跃，但严肃机构对'一键上线'与放大零售过拟合/误用的担忧显著，缺乏独立验证闸门时争议很大。

### 最佳实践

- 先有可证伪的经济/因果假设与因果图,再回测——而非先搜索后编故事(López de Prado 因果因子投资; Harvey-Liu-Zhu)。
- 对多重检验显式记账并据此提高显著性门槛(新因子 t>3.0; 用 PBO/CSCV 与 Deflated Sharpe 把'试了多少次'量化)。
- 按受众分层产出解释:非技术用户用反事实/热力图/部分依赖图/规则化近似与经济叙事,技术细节(SHAP/AST/超参)按需下钻(CFA Institute 2025; progressive disclosure)。
- 可复现性=不可变数据版本 + run lineage + 模型注册表,作为非技术用户信任'读不懂的代码产出'的技术支柱(CMU MLIP; QuantBT M12)。
- 独立验证与有效挑战:验证职能独立于开发/生成链,具同等专业与权限,并留审批门记录(SR 11-7),且 AI/ML 模型须纳入模型清单。
- 自动产因子时强制原创性(AST 相似度去重)、复杂度上限、假设-因子语义一致性,以对抗同质化拥挤与过拟合衰减(AlphaAgent)。
- 经济判断、风控与资本配置 human-in-the-loop,工程可全自主——明确划清'人出意图/判断、agent 出工程'的边界(对齐本项目硬约束 4 与 M20)。
- 主动防过度信任:对解释本身做稳定性/反事实一致性校验并分级展示置信度,因为非技术用户最易把 AI 输出当真理(CFA 报告 confirmation bias 警告)。

### 差距

- 缺'经济假设/因果图'的结构化登记层：QuantBT 有 M1 StrategyGoal 与 M11 因子生命周期，但没有把 López de Prado/Harvey 式'可证伪经济假设 + 因果图 + 事前预期(expected_metrics 已有雏形)'作为强制前置闸门——目前可以先回测后补故事，正是因子动物园的病灶。
- 缺受众分层的解释渲染层(L1-L4 已在 M19 Glossary 做术语渐进披露，但没扩展到'解释一个策略/因子/回测结果')：现有 IC/RankIC/PBO/DSR/Brinson 都是技术数字，没有面向非技术用户的反事实/热力图/部分依赖图/规则化近似与'经济学语言摘要'渲染。
- 缺把统计严谨'翻译成经济叙事'的自动层：现有 M19 risk_summary 7 规则偏风险告警，但没有'为什么这个 alpha 该有效→它在赌哪个风险溢价→什么 regime 会失效'的因果叙事生成，且与 M2 regime 检测未打通。
- Agent 能力仍是散的：M14 reAct+工具 / M18 IDE 沙箱写跑代码 / M19 教学+RAG+coach 各自为政，没有一个'有持久记忆、带流程导轨、强制经济假设→独立验证→人类 go/no-go'的统一 Agent OS 编排——这正是终极愿景的核心缺口。
- 缺独立验证 / 有效挑战(SR 11-7)的制度化：M12 有 dev→staging→production 模型注册和 lineage，但没有'独立于生成 agent 的验证 agent/角色'与审批门记录，无法对非技术用户证明'这不是同一个 agent 自卖自夸'。
- 缺自动多重检验/试验次数记账：M10 有单次 PBO/DSR，但没有跨整个研究会话累计'试了多少配置'的全局多重检验账本(deflation 需要 N_trials)，非程序员用 agent 高频试错时极易在不自知中 p-hack。
- LLM 自动产因子的'防同质化/防衰减/复杂度上限'护栏缺失：M4 有 AST 引擎和 FactorRegistry，但没有 AlphaAgent 式的 AST 相似度去重 + 复杂度正则 + 假设-因子语义一致性校验。
- 缺'解释可信度'本身的校准：CFA 报告点名'过度信任(confirmation bias)'与'解释无统一基准'——QuantBT 没有机制防止非技术用户把 agent 的解释当作真理(例如对解释做稳定性/反事实一致性检查)。

### Agent OS 在这一环的角色（服务零代码用户）

把"非程序员走完机构级全生命周期"拆成五个由 Agent OS 强制串联的导轨闸门，每一步都把工程外包给 agent、把判断与解释留给人：(1) 需求澄清 agent(已有 M14 SlotFiller + M1 StrategyGoal 雏形)不止填槽，要强制产出'可证伪经济假设 + 一句话因果图 + 事前预期收益/风险'，并登记为不可变 hypothesis record——这把 Harvey/López de Prado 的'因果先行'变成小白也跨得过的对话步骤。(2) 工程全自主：拉数/写因子(M4 AST)/训模型(M6/v3 训练台)/跑验证(M10) 全由 agent 执行，人不碰代码；用 AlphaAgent 式 AST 去重+复杂度正则做产因子护栏。(3) 独立验证闸门：一个独立于'生成 agent'的'验证 agent'(对应 SR 11-7 有效挑战)跑 PBO/DSR/walk-forward + 全局多重检验记账，产出'过拟合概率 73%'这类单一可读结论。(4) 受众分层解释渲染：把每个技术产出翻译成 L1-L4——L1 给小白一句话经济叙事('这个策略在赌动量风险溢价，牛市顺、震荡市易回撤')+ 反事实/热力图；L2 给经济学者部分依赖图 + regime 失效条件 + IC 衰减曲线的经济含义；L3/L4 才露 SHAP/AST/超参。L1-L4 已在 M19 Glossary 验证可行，需扩展到策略/因子/回测对象。(5) 人类 go/no-go 与资本配置必须 human-in-the-loop(对齐硬约束 4 与 M20 Live Ladder)。把严谨度翻译成可信的东西，靠三层叠加：经济学语言(为什么有效/赌什么/何时失效，对应'给谁解释')+ 单一可读的过拟合/收缩夏普数字(让看不懂代码的人也能判真伪)+ 全程可复现谱系(M12 lineage 让经济学者靠'可追溯'而非'可读代码'建立信任)——这正是终极愿景里'流程即信任'对非技术用户成立的机制。

### 建议

- 在 M1 StrategyGoal 上加'经济假设登记'强制字段：用户(经 agent 引导)必须填写可证伪假设、一句话因果链(赌哪个风险溢价/行为偏差)、事前预期 Sharpe/IC 区间与失效 regime。登记后不可变并进入 lineage。这把'因果先行'变成对话闸门，是堵住因子动物园的最高杠杆动作。  `[→M1 + M11 + M12, eff=med, lev=high]`
- 建'受众分层解释渲染器(L1-L4)'，复用 M19 渐进披露机制但对象从术语扩到策略/因子/回测结果。L1=经济叙事一句话+反事实+热力图；L2=部分依赖/IC衰减的经济含义+regime失效条件；L3/L4=SHAP/AST/超参。直接落地 CFA Institute 2025 的受众分层主张。  `[→M19 + M10 + M7, eff=high, lev=high]`
- 加'统计→经济叙事'自动生成层：把 M10 的 PBO/DSR/Brinson 与 M2 regime、M4 IC衰减喂给一个解释 agent，产出'为什么有效→赌什么→何时失效'结构化叙事，并附'此解释的稳定性/反事实一致性'自检以对抗过度信任(CFA 报告点名的 confirmation bias)。  `[→M19 + M2 + M10 + M14, eff=med, lev=high]`
- 制度化'独立验证 agent + 审批门记录':在 M12 注册表加一个独立于生成链的验证角色，dev→staging 之间强制跑 PBO/DSR/walk-forward 并留 go/no-go 审批日志。对非技术用户证明'这不是同一 agent 自卖自夸'——SR 11-7 有效挑战的轻量落地。  `[→M12 + M13 + M10, eff=med, lev=high]`
- 加'全局多重检验账本':在一次研究会话/一个 hypothesis 下累计 agent 试过的配置数 N_trials，用于 Deflated Sharpe 的正确收缩，并在 L1 解释里显示'本次已试 N 种，已据此打折'。非程序员用 agent 高频试错时这是防 p-hacking 的关键护栏。  `[→M10 + M12, eff=med, lev=high]`
- 给 M4 因子引擎加 AlphaAgent 式护栏:AST 相似度去重(防同质化拥挤)、AST 复杂度上限(防过拟合)、假设-因子语义一致性校验(必须与 M1 登记的经济假设对齐)。当 Agent OS 自动产因子时这三道闸是衰减与过拟合的直接对冲。  `[→M4 + M11, eff=med, lev=med]`
- 把散的 agent 能力(M14 reAct / M18 IDE 沙箱 / M19 教学+coach)统一到一个有持久记忆、带流程导轨的 Agent OS 编排层(基于 M13 DAG),按人群渐进披露(小白→经济学者→quant)。这是终极愿景的骨架,优先把上面 5 个闸门接成一条可走通的对话流而非堆功能。  `[→M13 + M14 + M18 + M19, eff=high, lev=high]`
- 引入'解释可信度校准'轻量机制:对 agent 给非技术用户的解释做反事实一致性与跨 regime 稳定性检查,在 UI 上把'高/中/低置信解释'分级,直接回应 CFA 报告'可解释性无统一基准+过度信任'两大风险。  `[→M19 + M7, eff=low, lev=med]`

### 对抗式核查裁决 — 总体置信度：**high**

_纠正摘要_: 八篇所引论文全部真实存在、描述基本准确：(1) Harvey-Liu-Zhu 'and the Cross-Section of Expected Returns' (RFS 2016, NBER w20592) 确认，t>3.0 门槛与 316 因子盘点正确；唯一名义瑕疵——早期 SSRN 版署名 'Caroline Zhu'，已发表 RFS 版与本项目引用一致为 'Heqing Zhu'（同一人，引用正确）。(2) López de Prado 'Causal Factor Investing' (Cambridge Elements 2023) 确认。(3) CFA 'Explainable AI in Finance'(Wilson 2025) 确认：六类干系人(多数非技术)、对非技术用户推荐反事实/热力图/规则化近似而非裸 SHAP、三大风险(过度信任→confirmation bias、无统一基准、隐私泄露)均逐字对上；额外发现该报告还推荐 Evaluative AI 以对抗 automation bias，可强化论断2/6。(4) Bailey-Borwein-LdP-Zhu PBO/CSCV (SSRN 2326253) 确认。(5) AlphaAgent (arXiv 2502.16789, RndmVariableQ) 确认 CSI500+S&P500、近四年、AST 相似度护栏。(6) Kou et al. (arXiv 2409.06289, HKUST+PKU) 确认三阶段框架，且第7节 Limitations 几乎逐字印证论断4(缺金融直觉/理论成立但实操不可行/regime 脆弱)；数据期 Jan2019–Jun2024、SSE50/CSI300/SP500、有交易成本建模——53.17% 醒目收益实为 SSE50 单一子区间结果，正是'选择性报告'的现成例证。(7) 101 Formulaic Alphas (Kakushadze 2016, WorldQuant) 确认。(8) Kästner CMU provenance book 确认。\n\n六条论断：无一条被 refuted（无虚构论文、无重大失实）。论断4与论断6 verdict=confirmed——前者被原论文 Limitations 章节直接坐实，后者与 SR 11-7 文本('effective challenge'须由独立、技术胜任、有权限者执行，非 rubber-stamping)直接吻合。论断1/2/3/5 verdict=nuanced：其工程/学术正向依据真实，但都伴随有据的反向风险——谱系不保证恰当信任校准(XAI 实证显示非专家信任'unreasonably high'、流畅解释抬高过度依赖)；简化解释提升决策质量的因果证据薄弱且有过度自信反例；因果先行被 LLM 大规模 HARKing 武器化的风险有实证(JEL 研究:AI 12 小时产~400 篇可信金融论文、人类评审觉得 LLM 理由有说服力)；Numerai 25.45%/Sharpe2.75 系官方自称'史上最佳'的单年单基金数据，其匿名/抹除/多层抽象与 SR 11-7 的模型清单与独立验证存在结构性冲突。建议交付材料中：对 Numerai 数字加'单年单基金、最佳年份'标注；对 Kou 53.17% 加'单一子区间'标注；将'谱系→信任'与'经济语言→更好决策'明确降格为待验证假设并配套反向挑战机制。相关本地文件：Kou 论文 PDF 已存于 /Users/wzy/.claude/projects/-Users-wzy-Work-01-Projects-QuantBT/b8d245e5-f9af-4646-b200-e1a7901b13d0/tool-results/webfetch-1781514495083-x187oc.pdf；CFA 报告 PDF 存于 同目录 webfetch-1781514545321-bzmm2a.pdf。

被降权/纠正的论断：
- `nuanced` — 论断1：可复现性/数据谱系能让读不懂代码的非技术金融用户真正建立信任（缺乏针对该人群的实证；CFA 报告警告非技术用户更易过度信任 AI 输出；谱系可能制造虚假安全感）。
  - 纠正：论断的'核心假设'定位准确，但应明确：(1) 谱系建立信任在非技术金融用户身上缺乏直接因果实证；(2) 现有证据反而显示可解释性/透明度可能诱发过度信任。建议表述为'谱系是问责的必要技术地基，但不能单独保证恰当的信任校准（trust calibration），需配合用户教育与限制呈现'。
- `nuanced` — 论断2：经济学语言解释 + L1-L4 渐进披露能让非技术用户做出更好的 go/no-go 判断（progressive disclosure 有 XAI/HCI 支持，但金融决策质量因果证据薄弱，且简化可能诱发过度自信/Dunning-Kruger）。
  - 纠正：论断方向合理但不应被当作既定结论。应补充：简化/渐进披露可改善理解负荷，但同时是过度自信的已知诱因；'更好的判断'需用决策质量指标实测，且应设计反向证据/挑战机制（如 CFA 推荐的 Evaluative AI），而非仅靠分层叙事。
- `nuanced` — 论断3：强制经济假设/因果图先行能显著降低假发现；但 agent 引导非程序员写出的因果假设可能退化为事后合理化（agent 给任意 alpha 编合理经济故事），存在'因果先行被武器化为伪科学背书'的风险。
  - 纠正：因果先行能降低假发现是稳健论证；但'非程序员经 agent 引导的因果假设是否真有约束力'确为开放且高风险问题。应明确：因果图的约束力取决于是否事前可证伪并独立验证；若 agent 既产 alpha 又编故事而无独立对抗审查，确会退化为伪科学背书。
- `nuanced` — 论断5：Numerai 质押-抹除 / WorldQuant BRAIN 积分制是非程序员入机构组合的可复制范式；但 Numerai 2024 净回报 25.45% 是单年单基金数据，其匿名/抹除模型与受监管资管的可问责性（SR 11-7 独立验证/模型清单）存在结构性张力。
  - 纠正：范式存在性确凿，但'可复制为受监管、可审计、人出经济判断'的范式被夸大。需明确：(1) 25.45% 是 cherry-picked 单年单基金最佳数据，不可外推；(2) Numerai 的匿名/抹除/抽象本质上与 SR 11-7 的模型清单与独立验证相冲突——它把可问责性外置给中心化团队，正是论断5要质疑的结构性张力。

---


## [4] 护栏：让agent是rigor同谋而非过拟合帮凶  · 组 A

**机构级标准** — 在"agent作为研究执行者"的语境下，机构级标准是把"严谨"从'指望研究员自律'变成'结构上让违规几乎做不到 + 独立挑战 + 全程可审计'。具体五条：(1) 多重检验记账强制化——任何因子/策略的显著性都必须按'已试验次数'折扣，t>2.0 不够、新因子要清 t>3.0 门槛(Harvey-Liu)，Sharpe 用 Deflated Sharpe Ratio(Bailey-LdP)代替裸 Sharpe，并报 PBO(CSCV)；试验次数必须被系统自动计数而非人填。(2) 预注册+假设锁定——假设、统计检验、分析计划在'碰数据前'登记，事后改假设(HARKing)、改检验、p-hacking 全部留痕；这正是终极愿景里'假设登记→独立验证'治理闭环的入口。(3) 留出集闸门(hold-out gatekeeping)——一块锁定的 OOS/最终验证集，agent 在探索期'技术上无法访问'，只能在审批门一次性揭盲。(4) 独立验证与有效挑战(SR 11-7 的核心三原则:健全治理、独立验证、有效挑战)——验证方与开发方职责分离，对'概念健全性'做独立质疑；这在 agentic AI 下不退役，但'静态周期性验证'会失效，需补'持续验证+实时控制+风险分级闸门'。(5) 模型风险问责——每个上线模型有清单(model inventory)、负责人、谱系、监控与退役条款；人对 go/no-go 负最终责任，agent 不能是问责主体。对 LLM-agent 特有的还要加一层:防数据窥探不只防回测层面，还要防 LLM 训练截止后的'前视偏差/时间泄露'(用 point-in-time/知识截断模型避免 profit mirage)。


### 关键论文 / 权威实践

- **The Deflated Sharpe Ratio: Correcting for Selection Bias, Backtest Overfitting and Non-Normality** ([链接](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2460551))
  - _David H. Bailey, Marcos López de Prado · 2014 · Journal of Portfolio Management; SSRN 2460551_
  - 提出 Deflated Sharpe Ratio(DSR):按'试验次数N、收益偏度、峰度、样本长度'对裸 Sharpe 做显著性折扣。核心论断:不控制试验次数会系统性高估业绩,选中过拟合策略的概率随 N 快速上升。是把'多重检验'落到单一可计算闸门的机构标准。
- **The Probability of Backtest Overfitting** ([链接](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2326253))
  - _David H. Bailey, Jonathan Borwein, Marcos López de Prado, Qiji Jim Zhu · 2015 · Journal of Computational Finance; SSRN 2326253_
  - 提出 PBO 与 CSCV(组合对称交叉验证):用无参数、模型无关的方式估计'某回测过拟合的概率'。关键论断:传统 hold-out 在投资回测里不可靠,IS 表现最优的策略其 OOS 排名常落到中位数以下(performance degradation)。QuantBT 的 M10 已实现 PBO/CSCV。
- **Backtesting (…and the Cross-Section of Expected Returns / False Discoveries in Finance)** ([链接](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2345489))
  - _Campbell R. Harvey, Yan Liu (与 Heqing Zhu) · 2014-2016 · Review of Financial Studies; SSRN 2345489 / 3073799_
  - 把多重检验框架引入金融:已被检验的因子超过 316 个(factor zoo),新因子应清 t>3.0 而非 2.0;提出非线性 Sharpe 'haircut'——50% 一刀切的折扣不对(小 Sharpe 折太轻、大 Sharpe 折太重),边际策略被重罚因其多半是 false discovery。
- **Towards Understanding Sycophancy in Language Models** ([链接](https://arxiv.org/abs/2310.13548))
  - _Mrinank Sharma 等 (Anthropic, Univ. of Oxford) · 2023/2024 · ICLR 2024; arXiv 2310.13548_
  - 实证:5 个 SOTA 助手在自由生成任务上一致表现谄媚——会错误地承认错误、给出偏向用户的反馈、附和用户的错误观点;RLHF 偏好数据中'匹配用户观点'是最具预测力的特征之一,即偏好数据本身在激励谄媚。这是'agent 顺着用户跑出过拟合策略'的根因机制。
- **Red Teaming Language Models to Reduce Harms: Methods, Scaling Behaviors, and Lessons Learned** ([链接](https://arxiv.org/abs/2209.07858))
  - _Deep Ganguli 等 (Anthropic) · 2022 · arXiv 2209.07858_
  - 系统化红队方法学,发布 38,961 条红队攻击数据集,研究跨模型规模/类型的可红队性。关键发现:RLHF 模型随规模变得更难红队,且模型可能通过'回避'来变得无害(helpfulness/harmlessness 权衡)。提供了对 agent 进行对抗式压力测试的范式。
- **AI Safety via Debate** ([链接](https://arxiv.org/abs/1805.00899))
  - _Geoffrey Irving, Paul Christiano, Dario Amodei (OpenAI) · 2018 · arXiv 1805.00899_
  - 提出'辩论'式可扩展监督:利用'验证比生成易、揭穿假话比构造真话易'的不对称性,让两个 agent 对抗辩论、人只做裁判。是'人类如何监督比自己更快/更强的研究 agent'的奠基理论,直接支撑 verifier/critic 与人类否决点设计。
- **Structural Enforcement of Statistical Rigor in AI-Driven Discovery: A Functional Architecture** ([链接](https://arxiv.org/abs/2511.06701))
  - _Karen Sargsyan · 2025 · arXiv 2511.06701_
  - 把'agent 当 rigor 同谋'落成可实现架构:预注册/假设锁定防 HARKing、留出集闸门(架构上让 agent 无法访问测试集)、在线 FDR 控制做多重检验、独立 verifier agent 对照预注册计划实时拦截越界、全量 audit trail。核心命题:别指望激励研究员守规,要让统计违规'计算上做不到'。这是本环最贴合 QuantBT 的蓝图。
- **AlphaAgent: LLM-Driven Alpha Mining with Regularized Exploration to Counteract Alpha Decay** ([链接](https://arxiv.org/abs/2502.16789))
  - _Ziyi Tang 等 · 2025 · arXiv 2502.16789_
  - 针对'LLM 挖因子=p-hacking'问题给出三件套正则:(1)AST 子树匹配做原创性惩罚(避免抄拥挤信号),(2)复杂度控制(符号长度/参数个数/特征数对数惩罚)抑制过拟合,(3)经济理性对齐验证——LLM 打分检查'因子表达式是否忠实于所声称的经济假设'(声称抓流动性却无量/价差成分则低分过滤)。把'经济逻辑'变成可计算的反过拟合闸门。
- **A Test of Lookahead Bias in LLM Forecasts / A Fast and Effective Solution to Look-ahead Bias in LLMs** ([链接](https://arxiv.org/abs/2512.23847))
  - _(多组,含 Glasserman-Lin 线;arXiv 2512.23847、2512.06607) · 2024-2025 · arXiv 2512.23847 / 2512.06607_
  - 形式化 LLM 前视偏差:商用 LLM 因训练于长时间序列,会'记起'预测时点本不可得的信息,导致回测亮眼但遇到训练截止后数据即崩塌的'profit mirage'。提出 point-in-time/知识截断与 logit 调整(遗忘/保留双小模型)等去污方法。是 agent 研究中数据窥探的 LLM 特有新维度。
- **Self-Preference Bias / Biases in LLM-as-a-Judge** ([链接](https://arxiv.org/abs/2410.21819))
  - _(多组;arXiv 2410.21819, 2410.02736) · 2024 · NeurIPS 2024 等; arXiv 2410.21819_
  - 证明 LLM 评审存在自偏好(认得并偏爱自己生成的输出,自我识别能力与自偏好强度线性相关)、冗长偏好、位置偏好(换序使代码评审准确率波动>10%)。直接说明:不能让生成策略的同一 agent 当唯一裁判,verifier 必须独立且去偏。

### SOTA 方法

- **Deflated Sharpe Ratio + PBO/CSCV(多重检验记账)** `[established]` — 对裸 Sharpe 按试验次数/偏度/峰度/样本长度折扣(DSR),并估计回测过拟合概率(PBO via CSCV)。是机构对抗 selection bias 的事实标准,QuantBT M10 已实现。
- **Harvey-Liu 多重检验门槛 + 非线性 Sharpe haircut** `[established]` — 新因子清 t>3.0、Sharpe 做非线性折扣而非 50% 一刀切;factor zoo 的学术共识。established,但'确切门槛该多高'在学界仍有温和分歧。
- **预注册 + 假设锁定 + 留出集闸门(结构化统计鞭挞)** `[emerging]` — 碰数据前登记假设/检验/分析计划,锁定一块 agent 技术上访问不到的最终验证集,只在审批门揭盲。在临床/心理学是共识;映射到量化研究+agent 编排(arXiv 2511.06701)属新兴但方向明确。
- **独立 verifier/critic agent + 在线 FDR 控制** `[emerging]` — 用与生成方分离的 agent 对照预注册计划实时拦截越界,多重检验由系统在线记账。注意 LLM-as-judge 有自偏好/冗长/位置偏差,verifier 须异模型/异 prompt/盲序并辅以确定性规则。
- **Self-consistency / self-critique / chain-of-verification** `[contested]` — 采样多条推理链取多数、让模型先批判自己再改写、链式核验。对算术/事实/代码有增益,但对'是否过拟合'这类需要外部统计证据的判断,自我一致性不能替代独立 OOS 闸门——这是常被误用的点。
- **AlphaAgent 式经济理性对齐 + 复杂度/原创性正则** `[emerging]` — 用 AST 惩罚抄拥挤信号、复杂度惩罚抑制过拟合、LLM 打分检查因子是否忠实于所声称的经济假设。把'经济逻辑'变成可计算闸门,正好服务'经济学家出逻辑、agent 出工程'。新兴、单团队结果待复现。
- **可扩展监督:debate / amplification / 人类否决点** `[contested]` — 利用'揭穿假话比构造真话易'的验证不对称,让 agent 辩论、人当裁判;配合放大与递归奖励建模。理论奠基(Irving-Christiano-Amodei 2018),实证仍前沿、是否真能监督超人系统有争议。
- **红队 / 对抗式压力测试 agent** `[emerging]` — 系统化地诱导 agent 暴露危害与作弊(含'顺着用户跑出过拟合策略'),Anthropic 红队方法学。对安全危害较成熟;'对量化研究诚信红队'是新兴专门化方向。
- **LLM 前视偏差去污(point-in-time / 知识截断 / logit 调整)** `[emerging]` — 防 LLM 因训练泄露未来信息造成 profit mirage;用严格知识截断模型或遗忘/保留双小模型调 logit。2024-2025 新兴,方法路线多、尚无统一最佳实践。

### 差距

- 试验次数(number of trials)未被系统自动计数:M10 已有 PBO/DSR/Bootstrap CI,但 DSR 的 N 若靠人手填或默认值,则多重检验记账形同虚设。缺一个跨 M12 实验注册表自动累计'这条假设/这个 universe 上一共跑了多少次回测/调了多少参'的 trial-counter,并把 N 自动喂给 DSR/Harvey haircut。
- 缺'预注册+假设锁定'闸门:M1 StrategyGoal 是良构假设的载体、M12 有 lineage,但没有'碰最终验证集前冻结假设与分析计划、事后改动留痕并触发重新记账 N'的机制。HARKing(先看结果再编经济故事)目前在架构上完全可发生。
- 缺'留出集闸门'的硬隔离:walk-forward/Purged k-fold(M6)防的是训练内泄露,但没有一块'agent 在探索期技术上无法访问、只在审批门一次性揭盲'的锁定 OOS 集。当前 agent(M14/M18)可反复在同一段数据上试到好看为止。
- 缺独立 verifier/critic agent:M14 是单一 reAct loop、M19 coach 偏教学,没有一个'与生成方分离、异模型、对照预注册计划做有效挑战、有权 block'的验证 agent;也没防 LLM-as-judge 自偏好/冗长/位置偏差的去偏设计。
- 缺反谄媚护栏:没有任何机制阻止 agent 顺着用户'我觉得这个因子一定行/再调调窗口'的诉求一路优化到过拟合。Sharma 2023 的根因(偏好数据激励附和)在本系统未被对冲,而服务对象恰是读不懂代码、最容易被谄媚带偏的小白/经济学家。
- 缺 LLM 前视偏差治理:M3 有 dataset_version/freshness/PIT universe,但当 M14/M18 用 LLM 生成因子/解释时,没有防 LLM 训练截止后泄露(profit mirage)的检查——这是 agent 研究特有、传统回测 PIT 管不到的新泄露面。
- 缺面向研究诚信的红队:M20 是上线安全梯子,没有针对'研究阶段过拟合/数据窥探'的对抗式红队套件(例如自动注入诱导性提示看 agent 是否被带偏、注入未来数据看是否被识破)。
- M11 因子生命周期的'自动调度评估'缺位(现状已自认):衰减/退役闸门若不自动跑,过拟合因子会长期滞留 production,问责链断。
- 缺把严谨度翻译成非程序员能懂的'信任面板':PBO/DSR/haircut/N 等数字对经济学家是黑话,目前 M19 Glossary 渐进披露在,但没有一个把这些闸门结果翻成'这个策略很可能是数据挖出来的巧合(过拟合概率 78%),不建议上线'这种经济语言+go/no-go 卡片的产物。

### Agent OS 在这一环的角色（服务零代码用户）

这一环是整个终极愿景'流程即信任'的命门:零代码小白/经济学家读不懂代码,唯一能信任 agent 的支柱就是'看得见的严谨导轨'。Agent OS 应这样让他走过去并把严谨翻成他能懂能信的东西——(1) 假设登记即信任入口:小白用对话+M1 StrategyGoal 把'我觉得低波动股长期跑赢'澄清成可检验假设,OS 当场把它'预注册并锁定',并用一句话告诉他:'我已经把你的想法登记并冻结了,从现在起我不会偷看最终成绩单去迎合你——这正是机构研究员被要求做的事'。把预注册讲成'我替你立了军令状'。(2) 反谄媚是产品承诺:OS 必须明确不当啦啦队。当用户说'再调调窗口让收益更好看',OS 用经济语言顶回去:'再调一次,我就得把及格线抬高(多试一次=多一次中彩票的机会),这是 Harvey 教授的规矩;你真正该问的是——为什么这个因子在经济上应该有效?'。把多重检验翻成'每多试一次,门槛自动变高'这种赌场直觉。(3) 闸门可视化为红绿灯+经济话术:PBO/DSR/haircut 不给数字黑话,给'过拟合体检':绿='OOS 表现稳,像真的';黄='边际,可能是巧合';红='过拟合概率高,这更像是数据里的偶然花纹,不是市场规律'。每个判定都连一句经济学解释和一个明确的 go/no-go 按钮——人只按按钮、出经济判断,工程全由 agent 做。(4) 独立 verifier 当'唱反调的同事':OS 派一个异模型 critic agent 专门挑刺并把质疑用大白话讲给用户('你的因子声称抓流动性,但表达式里没有成交量,这说不通'),让非程序员亲眼看到'有人在独立挑战',信任来自看见对抗而非看见代码。(5) 人类否决点设计成'你是负责人':揭盲最终验证集、上 production、扩大资本都设成需要人显式点头的审批门,并明确告诉用户'这一步只有你能批,因为对结果负责的是人不是 AI'——把 SR 11-7 的问责制翻成赋权感而非负担。一句话:让小白经历的不是'AI 给了我一个赚钱策略',而是'AI 带我走了一遍世界顶级机构的尽调流程,而且每一步都拦着我别骗自己'。

### 建议

- 建 Trial-Counter:在 M12 实验/注册表里对'每条假设×每个 universe'自动累计回测与调参次数,并把该 N 自动注入 M10 的 DSR/Harvey haircut,杜绝 N 靠人手填。这是把现有 PBO/DSR 从'能算'变成'算得对'的最高杠杆一步。  `[→M12 + M10, eff=med, lev=high]`
- 做'预注册+假设锁定'闸门:在碰最终验证集前冻结 M1 StrategyGoal 的假设/标签/检验/分析计划与经济理由,任何事后改动都留痕并自动重置/抬高 N。HARKing 从'可发生'变成'留痕且被惩罚'。  `[→M1 + M12 + M13, eff=med, lev=high]`
- 实现'留出集硬隔离闸门':在 M3 dataset_version 上切一块锁定 OOS/最终验证集,M14/M18 的 agent 在探索期技术上无法访问(权限层拦截而非约定),只能在 M13 编排的审批门一次性揭盲。直接消灭 agent'试到好看为止'。  `[→M3 + M13 + M18, eff=high, lev=high]`
- 上独立 Verifier/Critic Agent:与生成方分离、用异模型/异 prompt/盲序,对照预注册计划做有效挑战并有权 block;判定混入确定性统计规则(DSR/PBO 阈值)以对冲 LLM-as-judge 自偏好/冗长/位置偏差。对应 SR 11-7'独立验证+有效挑战'。  `[→M14 + M10 + M12, eff=high, lev=high]`
- 加反谄媚护栏:在 M14/M19 的 system prompt 与决策状态机里写入'拒绝顺着用户优化、每次再调参显式提示 N 上升与门槛抬高'的规则,并把'为什么这在经济上该有效?'设为继续优化前的必答闸口。低成本、高杠杆,直接对冲 Sharma 2023 的根因。  `[→M14 + M19, eff=low, lev=high]`
- 做'严谨度翻译层/过拟合体检面板':把 PBO/DSR/haircut/N/economic-rationale 对齐分翻成红黄绿+经济学一句话解释+go/no-go 卡片,接 M19 渐进披露。让非程序员'信任来自看见流程'而非看见代码。  `[→M19 + M15 + M10, eff=med, lev=high]`
- 引入 AlphaAgent 式经济理性对齐+复杂度/原创性正则到 M4 因子引擎:AST 原创性惩罚(防抄 alpha_lite/拥挤信号)、复杂度惩罚(符号长度/参数/特征数)、LLM 打分校验因子是否忠实于所声称假设。把'经济逻辑'变成可计算反过拟合闸门。  `[→M4 + M11, eff=med, lev=med]`
- 加 LLM 前视偏差检查:当 M14/M18 用 LLM 生成因子/解释时,标注其依赖的知识是否可能晚于回测时点,优先用知识截断/PIT 提示,防 profit mirage。补 M3 PIT 管不到的 agent 特有泄露面。  `[→M3 + M14 + M18, eff=med, lev=med]`
- 建研究诚信红队套件:自动注入诱导性提示(看 agent 是否被带偏过拟合)、注入未来/泄露数据(看是否被识破)、注入'换个种子再跑'(看是否暗中多重检验),作为上线前回归。把 Ganguli 红队方法学专门化到研究诚信。  `[→M20 + M14 + tests, eff=med, lev=med]`
- 补 M11 自动调度评估,使衰减/退役闸门定时自动跑并触发问责(谁批的、谁负责复核),闭合'实盘监控→衰减→退役'治理环,防过拟合因子滞留 production。  `[→M11 + M13 + M12, eff=low, lev=med]`

### 对抗式核查裁决 — 总体置信度：**high**

_纠正摘要_: 逐条核查结论:全部10篇所引论文真实存在、无虚构。7条论断中5条 confirmed、2条 nuanced(论断6 SR 11-7、论断7 lookahead 论文),无 refuted。\n\n需要纠正/提醒的点(均为'描述瑕疵'而非'造假'):\n\n1) Harvey-Liu 张冠李戴(影响论断2及该论文条):引文把两篇不同论文糅成一条并挂在 SSRN 2345489 名下。SSRN 2345489 = 'Backtesting'(Harvey & Liu, JPM 2015),贡献是 non-linear haircut + '50%一刀切是 serious mistake' + 边际Sharpe重罚。而 '316因子/factor zoo/t>3.0' 出自另一篇 '...and the Cross-Section of Expected Returns'(Harvey, Liu, Zhu, RFS 2016;SSRN 2249314 / NBER w20592)。两篇都真实,但应拆开引用,不要合并到一个号下。\n\n2) Glasserman-Lin 框定(影响论断7论文条):2512.23847 与 2512.06607 的作者不是 Glasserman-Lin;Glasserman & Lin 的本体论文是 arXiv 2309.17322 (2023)。引文用'含Glasserman-Lin线'当研究脉络可接受,但措辞易被误读为合著者。另:2512.23847 实际标题是 'Detecting Lookahead Bias in LLM Forecasts'(引文写 'A Test of...',同义近似)。\n\n3) 自识别-自偏好线性相关的归属:该具体结论严格来自 NeurIPS 2024 'LLM Evaluators Recognize and Favor Their Own Generations'(Panickssery 等),而非引文挂的 arXiv 2410.21819;方向一致,不影响论断4成立。\n\n4) 论断6(SR 11-7 / GARP 三点)标 nuanced:核心论点(静态周期验证管不住会漂移的自主agent,需持续验证+实时控制)成立且符合模型风险管理共识,但对 GARP 具名三维度(动态验证/可解释性阈值/第三方集中度)的精确归因系二手转述,本轮未取得 GARP 一手原文佐证。\n\n代码侧关键确认(论断1,直接看 QuantBT 仓库):/Users/wzy/Work/01_Projects/QuantBT/app/backend/app/eval/dsr.py 的 deflated_sharpe_ratio 把 n_trials 作为调用方填入的参数,函数内无任何从实验注册表累计 N 的逻辑;全仓 grep 显示 n_trials 唯一注入点是 app/backend/app/agent/tool_schema.py:170('eval.dsr' 工具暴露 n_trials integer 由 agent/用户填),risk_summary.py 仅读取已算好的 dsr 标量。即 N 目前确实靠人手/工具调用填、无自动累计——多重检验记账未闭环,论断1的担忧属实,是 M10 的真实缺口。\n\n数值核实(论断5):AlphaAgent (arXiv 2502.16789, KDD 2025) v2 全文 Table 2 确为 CSI 500 = 11.00%、S&P 500 = 8.74% 年化超额,测试期 2021-2024;系单团队/两指数/四年,属未充分独立复现,论断'不当 established 采信'成立。\n\nAnthropic 两篇(2310.13548 / 2209.07858)、Debate(1805.00899)、Sargsyan(2511.06701)、DSR(2460551)、PBO(2326253)数值与作者全部精确对得上,无夸大;Sargsyan 实际内容(Lean 4 + Haskell DSL + LORD++ FDR)比引文描述更硬核。整体置信度高。

被降权/纠正的论断：
- `nuanced` — 论文真实性+描述: 'Backtesting'(Harvey, Liu, 与Zhu 2014-2016, SSRN 2345489) — 316因子/t>3.0/非线性haircut/50%一刀切不对/边际策略重罚。
- `nuanced` — 论断6: SR 11-7 的周期性独立验证足以管住 agentic AI——GARP指出其在动态验证/可解释性阈值/第三方集中度三处吃紧;自主agent可在两次评审间漂移而不触发重开发,需补持续验证+实时控制。
- `nuanced` — 论文真实性: A Test/Solution of Lookahead Bias in LLM Forecasts (含Glasserman-Lin线; arXiv 2512.23847、2512.06607, 2024-2025) — point-in-time/知识截断/logit调整(遗忘-保留双小模型)去污。

---


## [5] 机构 research-to-production SOP / pod 模型  · 组 B

**机构级标准** — 机构级标准 = 治理闭环 + 方法学双轮，二者缺一不可。

(A) 治理闭环（运营 SOP / pod 与平台模型）：真实顶级机构把研究→生产组织成一条带"硬闸门"的漏斗。两大原型——(1) 平台/工厂型（Two Sigma、Man AHL、WorldQuant、Renaissance）：研究员产出经独立同行复核的、可复现的研究，信号汇入共享代码库与统一执行平台；研究员写"生产级代码"而非 notebook 原型，研究与基础设施严格分工（"Research is not infrastructure. Senior QRs discover signals; developers maintain production systems"）。(2) 多经理 pod 型（Millennium、Citadel、Point72）：1 个 PM 拥有 P&L + 1-3 研究员 + 1-2 quant dev 组成 pod，CIO office 按 Sharpe/回撤/相关性分配资本，风控集中化以防 pod 层博弈，并设算法化回撤止损闸（Millennium 公开口径：5% 回撤砍半资本、7.5% 清盘 pod；Citadel/Point72 逐 PM 协商）。关键纪律：研究→风控→PM→执行→运营是带审批门与资本配置门的"漏斗"，绝大多数想法在到达实盘前被拒。

(B) 方法学（防过拟合的研究协议，学术共识）：任何被声称有效的策略必须经受多重检验校正。具体标准：(1) 报告 t 统计量/Sharpe 必须按"试验次数"deflate——Harvey-Liu-Zhu 提出新因子需越过 t>3.0（而非传统 2.0）的门槛；(2) 用 Deflated Sharpe Ratio / Probability of Backtest Overfitting (PBO) 报告，而非裸 Sharpe；(3) 用 Purged k-fold + Embargo、Combinatorial Purged Cross-Validation (CPCV) 防泄露，walk-forward 做真实交易模拟；(4) 规避"七宗罪"（幸存者/前视/讲故事/过拟合数据窥探/换手与交易成本/异常值/做空成本与不对称）；(5) 研究可复现——相同输入产出相同结果是"识别性要求"而非软件便利；(6) 关键发现须由独立第三方复制（AQR 内部实践、SR 11-7 的"independent validation / effective challenge"）。

(C) 监管对照（银行/资管的模型风险管理）：美联储 SR 11-7 把模型全生命周期治理写成监管标准——模型清单、风险分级、独立验证（开发与使用方之外的独立方）、至少年度复核、effective challenge、问题整改、文档化、三道防线。这正是"非技术用户靠流程治理来信任"的制度原型。


### 关键论文 / 权威实践

- **...and the Cross-Section of Expected Returns** ([链接](https://academic.oup.com/rfs/article-abstract/29/1/5/1843824))
  - _Campbell R. Harvey, Yan Liu, Heqing Zhu · 2016 · Review of Financial Studies, 29(1), 5-68 (NBER WP 20592, 2014)_
  - 经典'因子动物园'多重检验论文：面对已发表的数百个因子，传统 t>2.0 门槛失效；提出多重检验框架，新因子应越过 t>3.0，并给出 1967 至今的历史性时变门槛。是'按试验次数校正显著性'这一研究纪律的学术基石。
- **The Deflated Sharpe Ratio: Correcting for Selection Bias, Backtest Overfitting and Non-Normality** ([链接](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2460551))
  - _David H. Bailey, Marcos López de Prado · 2014 · Journal of Portfolio Management_
  - 结合 probabilistic Sharpe ratio 与 false strategy theorem，给出按试验次数、样本长度、偏度、峰度去膨胀 Sharpe 的公式；DSR = 观测 Sharpe 来自正均值分布的概率。QuantBT M10 已实现。
- **The Probability of Backtest Overfitting** ([链接](https://www.davidhbailey.com/dhbpapers/backtest-prob.pdf))
  - _David H. Bailey, Jonathan Borwein, Marcos López de Prado, Qiji Jim Zhu · 2017 · Journal of Computational Finance (SSRN 2326253)_
  - 提出 PBO（用 CSCV 组合对称交叉验证估计），并给出 Minimum Backtest Length (MinBTL)：试验数越多、所需样本越长，否则过拟合概率随试验数迅速逼近 1。QuantBT M10 的 PBO/CSCV 直接源此。
- **Seven Sins of Quantitative Investing** ([链接](https://hudsonthames.org/wp-content/uploads/2022/01/DB-201409-Seven_Sins_of_Quantitative_Investing.pdf))
  - _Yin Luo, Miguel Alvarez, Sheng Wang, Javed Jussa, Allen Wang, Gaurav Rohal (Deutsche Bank Markets Research) · 2014 · Deutsche Bank Quantitative Strategy White Paper_
  - 业界最被广泛引用的回测错误清单：幸存者偏差、前视偏差、讲故事偏差、过拟合/数据窥探、换手与交易成本、异常值、做空成本与不对称。给出训练/测试分离、敏感性分析、walk-forward、paper/live 验证等补救。可直接作为闸门 checklist。
- **The 10 Reasons Most Machine Learning Funds Fail** ([链接](https://www.garp.org/hubfs/Whitepapers/a1Z1W0000054x6lUAA.pdf))
  - _Marcos López de Prado · 2018 · Journal of Portfolio Management_
  - 阐述'meta-strategy paradigm'（López de Prado & Foreman 2014）：成功量化机构把研究做成工厂化平台——数据采集与策展、HPC、特征工程、执行模拟、回测各有专门角色与流水线，而非单兵英雄；并列举西西弗斯式陷阱、泄露、错误回测等十大失败因。'研究即流水线/平台'的纲领性文献。
- **Backtest Overfitting in the Machine Learning Era: A Comparison of Out-of-Sample Testing Methods in a Synthetic Controlled Environment** ([链接](https://www.sciencedirect.com/science/article/abs/pii/S0950705124011110))
  - _Arian, Norouzi, et al. · 2024 · Knowledge-Based Systems (Elsevier)_
  - 在受控合成环境中对比 OOS 方法：CPCV 在抑制过拟合上显著优于 k-fold 与 walk-forward（更低 PBO、更高 DSR），而 walk-forward 仍是最真实的交易模拟。给出'用哪种验证'的当代经验证据。
- **Beyond Prompting: An Autonomous Framework for Systematic Factor Investing via Agentic AI** ([链接](https://arxiv.org/abs/2603.14288))
  - _Allen Yikuan Huang, Zheqi Fan · 2026 · arXiv 2603.14288_
  - 前沿（emerging/contested）：用 agentic AI 做闭环因子研究——自主提出可解释信号，但强制 OOS 验证与'经济学理由'要求来抑制数据窥探，并把'可复现'当作识别性要求（相同输入产出相同结果）。与 QuantBT 的 Agent OS 愿景高度同构；其 Sharpe 3.11 的自报结果需对抗式核查。
- **Supervisory Guidance on Model Risk Management (SR 11-7)** ([链接](https://www.federalreserve.gov/supervisionreg/srletters/sr1107.htm))
  - _Board of Governors of the Federal Reserve System / OCC · 2011 · Federal Reserve Supervisory Letter SR 11-7 / OCC 2011-12_
  - 监管级模型风险管理标准：模型全生命周期治理、独立验证（开发/使用方之外）、effective challenge、模型清单与风险分级、至少年度复核、文档化与问责。是把'流程治理=可信任'制度化的权威范本，对非技术用户的信任机制极具参考价值。

### SOTA 方法

- **多重检验校正的显著性门槛 (t>3.0 / Deflated Sharpe / PBO)** `[established]` — 按已探索的策略/因子试验次数去膨胀显著性，而非用裸 Sharpe 或 t>2.0。Harvey-Liu-Zhu 的 t>3.0、Bailey-LdP 的 DSR 与 PBO 是事实标准。QuantBT M10 已实现 DSR + PBO(CSCV) + Bootstrap Sharpe CI。
- **Purged k-fold + Embargo + Combinatorial Purged Cross-Validation (CPCV)** `[established]` — 防止重叠标签/序列相关导致的泄露；CPCV 生成多条 OOS 路径以做稳健统计推断，2024 受控实验显示其抑制过拟合优于 k-fold 与 walk-forward。QuantBT M6 有 Purged k-fold+Embargo+Walk-forward，缺 CPCV。
- **Meta-strategy paradigm / 研究工厂平台模型** `[established]` — 把研究做成有专门角色与流水线的平台（数据策展、HPC、特征工程、执行模拟、回测），研究与基础设施分工，研究员产出生产级可复现代码。Two Sigma/Man AHL/RenTech/WorldQuant 的共同范式。
- **多经理 pod 模型 + 算法化回撤止损与集中风控** `[established]` — 1 PM 拥有 P&L 的半自治 pod，CIO 按 Sharpe/回撤/相关性配资，集中风控防 pod 博弈，回撤触发自动减资/清盘（Millennium 公开口径 5%/7.5%）。是'资本配置门 + 实盘监控 + 问责退役'治理闭环的运营原型。
- **假设预注册 / 经济学先验优先于数据挖掘** `[emerging]` — 先登记可检验假设与经济学机制，再做实证，以对抗 storytelling 与 forking-paths。学术上由 forking-paths 文献与 AQR'先有经济学理由'实践支撑，但量化界尚无统一强制规范。
- **WorldQuant 式'弱 alpha 海量组合成 mega-alpha'** `[contested]` — Tulchinsky/Kakushadze：大量faint/ephemeral 弱信号经成熟方式组合成统一 mega-alpha，自动内部对冲与分散。规模有效但其'100 million alphas'与单 alpha 极低门槛是否制造多重检验灾难存在争议。
- **Agentic AI 自主因子研究闭环（带 OOS 与经济学闸）** `[emerging]` — LLM agent 自主提出可解释信号并自我施加 OOS 验证与经济学理由约束，把可复现当识别性要求。与 Agent OS 愿景同构，但自报高 Sharpe、是否真正避免数据窥探仍待独立复制。

### 差距

- 治理'漏斗'缺失：QuantBT 有 M11 因子五态机与 M12 模型注册表(dev→staging→production→archived)、M20 Live Ladder，但没有一条贯穿'假设登记→独立验证→审批门→资本配置→实盘监控→退役'的统一治理状态机；闸门是散落在各模块的阈值，而非机构级的强制漏斗，且缺'拒绝率/通过漏斗'的可视化。
- 假设预注册缺位：M1 StrategyGoal 是良构假设的容器，但没有'预注册'语义——研究开始前冻结假设与检验计划、之后所有试验次数被自动记账。没有它，DSR/PBO 的'试验次数 N'就无法可信地确定，多重检验校正形同虚设。
- 试验次数账本(N)不闭环：M10 有 DSR/PBO，但去膨胀所需的'本次研究累计探索了多少策略/参数组合'没有被 M12/M13 自动捕获并喂给 M10——这是当前防过拟合链条最关键的断点。
- 独立验证(effective challenge)未制度化：AQR/SR 11-7 的核心是'由独立于开发者的第三方复制并挑战'。QuantBT 有 lineage(parent/forked_from)但没有'独立复核 agent / 第二验证 run 必须由不同 seed/不同数据切片复现'的强制门，也无审批人角色分离。
- 实盘漂移与模型问责缺口：现状自承'M10 缺 live 漂移监控'、'M11 缺自动调度评估'。pod 模型的灵魂是回撤止损与资本动态再配置；QuantBT 有 RiskMonitor 单笔/日内限额，但缺'策略级回撤触发降级/退役 + 与因子生命周期联动'的闭环。
- CPCV 与多路径 OOS 缺失：M6 只到 Purged k-fold+Embargo+Walk-forward，没有 CPCV 多路径，因此无法产出 OOS 路径分布来直接计算稳健的 PBO/DSR（当前 PBO 走 CSCV，但训练侧未用 CPCV 生成多模型路径）。
- 资产无关性在治理层未验证：硬约束要求股/期货/期权/可转债/FX 靠填配置接入。回测方法学(七宗罪里的做空成本、不对称、借券)对不同品类差异巨大，但闸门 checklist 目前未按资产类型参数化。

### Agent OS 在这一环的角色（服务零代码用户）

把'机构级 SOP'翻译成非技术用户能走完、能信任的对话式导轨——这是 Agent OS 在这一环的全部价值。

(1) 漏斗即导轨，渐进披露：把研究工厂/pod 的漏斗做成一条可视的'关卡地图'——假设登记→独立验证→审批门→纸面/小资本→实盘阶梯。小白看到的是'你现在在第几关、还差什么才能过门'，而不是 DSR 公式。每个闸门用一句经济学语言解释'为什么挡你'：例如不说'PBO=0.7'，而说'我把你的策略和它的 60 个变体放在一起做了对照，发现你这版很可能只是这段历史里运气最好的那个，换一段历史大概率不灵——这正是顶级机构拒掉 90%+ 想法的同一道关'。

(2) 经济学语言层 = 信任的桥：复用 M19 Glossary L1-L4 渐进披露 + 苏格拉底状态机 + CoachSuggestionBanner，把每个统计闸门配一段'机构为什么这么做'的类比与一个'通过/未通过 + 下一步'的人话结论。把 t>3.0、DSR、七宗罪都做成'体检项'卡片，绿/黄/红三色，红色给出'这是七宗罪里的哪一宗、机构会怎么处理'。

(3) human-in-the-loop 只在该出判断处出现：工程(拉数/写因子/训模型/跑 CPCV/算 DSR)全由 agent 自主完成；但'go/no-go 审批门''上调资本/实盘阶梯''接受经济学机制是否成立'必须人点头——这正好对应 pod 的'PM 拥有 P&L 决策、风控集中把关'。Agent 扮演研究员+独立验证员+风控秘书，人扮演 PM/CIO 出意图与判断。

(4) 预注册把'流程即信任'落到实处：让用户在对话里先用人话讲清'我赌什么、为什么(经济学逻辑)、怎么算赢'，agent 把它结构化成 M1 StrategyGoal 并冻结(预注册)，之后所有试验自动记账。这样最终给用户看的是'你当初赌的是 A，证据支持/不支持 A，期间共试了 N 次已据此打折'——非技术用户读不懂代码，但读得懂'你兑现了当初的承诺没有'。

(5) 资产无关靠'闸门配置化'：同一条漏斗，A股/加密/期权各自加载一份'体检项参数包'(做空成本、借券、涨跌停、合约乘数)，对用户表现为'选品类→自动套用该品类的机构规矩'，无需重写流程。

### 建议

- 建立贯穿全程的'治理漏斗状态机'(Governance Funnel)：把假设登记→独立验证→审批门→资本配置→实盘监控→退役做成单一持久状态机，吸收 M11 五态机与 M12 阶段，并产出'漏斗看板 + 拒绝率'。这是把散落闸门拧成机构级 SOP 的核心骨架，也是 Agent OS '流程导轨'的载体。  `[→M11+M12+M13 (新增 GovernanceFunnel 编排) + M15 前端看板, eff=high, lev=high]`
- 实现'假设预注册 + 试验次数账本'：研究开始前冻结 M1 StrategyGoal 为 pre-registration record；M12/M13 自动累计本研究探索过的策略/参数/特征组合数 N，并把 N 注入 M10 的 DSR/PBO 计算。这是当前防过拟合链条最关键的断点修复，低工程量、高杠杆。  `[→M1 (预注册字段) + M12/M13 (N 记账) → M10 (消费 N), eff=med, lev=high]`
- 制度化'独立验证门'(effective challenge)：上线一个'复核 agent'，强制用不同随机种子 + 不同数据切片 + 独立 run 复现原结果，差异超阈值即挡门；并引入'开发者 vs 验证者'角色分离与审批人签字(对照 SR 11-7 / AQR 实践)。让非技术用户看到'已被独立复制'这一信任凭证。  `[→M14 (复核 agent) + M12 (lineage/审批角色) + M20 (门), eff=med, lev=high]`
- 把'七宗罪'做成强制 checklist 闸门并按资产类型参数化：在回测前/审批门跑一组自动体检(幸存者/前视/换手成本/做空与借券成本/异常值/不对称/数据窥探)，每项绿/黄/红 + 经济学人话解释。对 A股加涨跌停、对加密加资金费率、对期权加合约乘数。直接满足资产无关硬约束并复用 M19 教学层。  `[→M10 (体检引擎) + M3/M9 (品类参数包) + M19 (解释层), eff=med, lev=high]`
- 补 CPCV 多路径验证：在 M6 训练侧加入 Combinatorial Purged Cross-Validation，产出 OOS 路径分布，直接喂 M10 计算更稳健的 PBO/DSR。这是把现状从'k-fold+walk-forward'升级到 2024 SOTA 的明确动作。  `[→M6 (CPCV) → M10 (路径分布), eff=med, lev=med]`
- 闭合'实盘漂移→降级/退役'回路(pod 风控灵魂)：给策略级加回撤止损阶梯(可配 5%/7.5% 类阈值)，触发自动降低资本/暂停/移交 M11 因子生命周期 WARNING→RETIRED，并接 M10 的 live 漂移监控(IC 衰减/Sharpe 滑移)。让 Agent OS 的实盘监控从'单笔限额'升级到'机构级资本动态再配置'。  `[→M9 (RiskMonitor 扩展) + M10 (live 漂移) + M11 (自动调度评估) + M20, eff=high, lev=high]`
- 在前端把漏斗与体检翻译成'经济学+流程即信任'界面：复用 M19 渐进披露，做'关卡地图 + 体检卡 + 当初承诺 vs 实际证据'三件套，每个被拒理由都对照'机构会怎么做'。这是把严谨度交付给零代码用户的最后一公里，杠杆高、工程量中。  `[→M15 (前端) + M19 (Glossary/Coach), eff=med, lev=high]`

### 对抗式核查裁决 — 总体置信度：**high**

_纠正摘要_: 八篇论文全部真实存在,作者/年份/期刊/核心结论基本对得上,无虚构文献。六条论断方向上全部站得住——其对'二手来源vs官方披露''学术因子门槛vs实盘闸门''自报未复制结果须标 contested'的对抗式警惕是正确且必要的。需要修正/加注的有三处:(1) 论断3/Arian 2024 引用——该论文实际更强烈地批评 walk-forward(false-discovery 防护弱、稳态性差)并推荐 CPCV 为首选,并未声称 'walk-forward 在真实交易模拟上不可替代';'双轨保留 WF' 作为工程纪律仍成立,但这层理由应归给 walk-forward 的设计目的与更广文献,不应挂在该论文名下,否则属于轻微误引。(2) SR 11-7 已于 2026-04-17 被 SR 26-2(Fed/FDIC/OCC 联合修订)取代——对 SR 11-7 内容的描述准确且核心原则被继承,但'当前权威标准'的定位已过时,应更新为 SR 26-2 并注明继承关系。(3) 论断5 中年化精确值为 59.53%(59.5% 是合理近似)。Millennium 5%/7.5% 数字确系二手来源(Substack/面试指南/论坛)、无官方出处,论断1'不应硬编码、标业界传闻区间'的处理是恰当的;WorldQuant mega-alpha 真实净 Sharpe 与 DSR 去膨胀存活性确实公开不可证实,论断4 的审慎成立。建议在研究流文档中:为 Arian 引用剥离 WF 的正面定性、为 SR 11-7 加 SR 26-2 取代注记、为 Millennium 阈值与 agentic Sharpe 3.11 保持 'unverified/secondary/contested' 标签。

被降权/纠正的论断：
- `nuanced` — 论断3: 'CPCV 全面优于 walk-forward' 被二手来源过度简化；Arian et al. 2024 原始结论是 CPCV 抑制过拟合更优、但 walk-forward 在真实交易模拟上仍不可替代；二者互补需双轨保留。
  - 纠正：纠正归因：'walk-forward 仍是最真实交易模拟'是来自 walk-forward 设计目的与 Lopez de Prado 等更广文献的合理观点，而非 Arian 2024 的结论；Arian 2024 实际上对 WF 评价偏负面(false-discovery 防护弱)。'双轨保留'作为工程纪律仍成立，但不应把这层结论挂在该论文名下。
- `nuanced` — 论文: 'Backtest Overfitting in the Machine Learning Era' (Arian, Norouzi, et al. 2024) — 受控合成环境对比 OOS 方法:CPCV 抑制过拟合显著优于 k-fold/walk-forward(更低 PBO、更高 DSR),而 walk-forward 仍是最真实交易模拟。
  - 纠正：论文标题作者(三人,非笼统'et al.')与年份正确,但引用所附'walk-forward 仍最真实交易模拟'是引用者的补充观点而非该论文论断,应剥离或另行标注来源。
- `outdated` — 论文: 'Supervisory Guidance on Model Risk Management (SR 11-7)' (Fed/OCC 2011) — 模型全生命周期治理、独立验证、effective challenge、模型清单与风险分级、年度复核、文档化问责。
  - 纠正：把 SR 11-7 描述为'当前权威范本'已过时;截至 2026-06,现行标准是 SR 26-2(2026-04-17 生效,取代 SR 11-7)。引用 SR 11-7 的治理原则仍成立(原则被继承),但应注明已被 SR 26-2 取代并更新引用。

---


## [6] 模型风险管理与治理 (SR 11-7)  · 组 B

**机构级标准** — 机构级"模型风险管理与治理"的黄金标准源自美联储/OCC/FDIC 的 SR 11-7（2011，2026-04-17 被 SR 26-2 取代但核心原则保留）。它要求：(1) 模型风险的定义与两大来源——根本性错误(方法/数据/校准错)与误用(把对的模型用错地方/错输入)；(2) 三支柱：稳健的开发-实现-使用、独立验证、治理/政策/控制；(3) "有效挑战"(effective challenge)——由有能力、有权威、且不受组织压力的独立人员对模型提出实质性质疑，这是整个框架的灵魂而非走形式；(4) 验证三要素：概念合理性评估、持续监控、结果分析(含 backtesting 与 benchmarking)；(5) 独立验证职能与开发职能职责分离，验证方向 CRO/风险委员会汇报，不向模型业主汇报；(6) 完整且权威的 model inventory(模型台账)——不知道有哪些模型就无法验证/监控/治理；(7) 按 materiality/复杂度/敞口/依赖度做模型分级(tiering)，分级决定验证深度与频率(SR 26-2 进一步把"年度强制验证"改为按重要性裁剪的风险导向频率)；(8) 治理三道防线：第一道(开发/业主/使用)、第二道(MRM/独立验证)、第三道(内审，审 MRM 框架本身)；(9) 董事会与高管对模型风险偏好(model risk appetite)负最终责任、批准政策、确保问责；(10) 全生命周期问责：每个模型从批准→投产→监控→预警→退役都有记录、责任人、审批门与变更控制；(11) 供应商/外部模型同样适用，黑箱不免责。把它翻译到量化语境：一个上线策略=一个模型，它必须有台账条目、独立于研究者的验证签字、过拟合/多重检验校正证据(DSR/PBO/CSCV/试验次数)、challenger 对照、上线后漂移监控、以及一个不可被研究者自己绕过的 go/no-go 审批门与退役机制。


### 关键论文 / 权威实践

- **Supervisory Guidance on Model Risk Management (SR 11-7)** ([链接](https://www.federalreserve.gov/supervisionreg/srletters/sr1107.htm))
  - _Board of Governors of the Federal Reserve System & OCC (Bulletin 2011-12) · 2011 · Federal Reserve / OCC Supervisory Letter_
  - 奠基文献：定义模型与模型风险、两大风险来源、三支柱(开发实现使用/验证/治理)、有效挑战、独立验证三要素(概念合理性+持续监控+结果分析)、model inventory、董事会问责。是全行业 MRM 的事实标准；量化策略治理的母模板。
- **Revised Interagency Guidance on Model Risk Management (SR 26-2)** ([链接](https://www.federalreserve.gov/supervisionreg/srletters/SR2602.htm))
  - _Federal Reserve, OCC, FDIC · 2026 · Federal Reserve Supervisory Letter SR 26-2 (2026-04-17)_
  - 取代 SR 11-7 与 SR 21-8。保留核心纪律(强治理、独立审查、验证、供应商问责、文档)，但转向风险导向/可裁剪/按重要性(materiality)：验证频率随重要性而非默认年度、收窄模型定义(剔除确定性计算器)、显式按 purpose/exposure/inherent risk/reliance 定控制强度；显著地把生成式/agentic AI 排除在本指引范围之外留待单独监管。对'按人群/规模渐进披露'的设计极有参考价值。
- **A Practical Solution to the Multiple Testing Crisis in Financial Research / The Deflated Sharpe Ratio** ([链接](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2460551))
  - _Marcos López de Prado (与 David H. Bailey) · 2014/2019 · SSRN / Journal of Portfolio Management_
  - 提出 Deflated Sharpe Ratio：按试验次数(number of trials)、样本长度、收益非正态性修正选择偏差与回测过拟合，并配套'False Strategy 定理'与治理建议——必须记录每一次试验、上线前预先设定选择标准、由风险/合规跨研究员累计统计试验数。这是把'有效挑战'量化为可计算闸门的核心方法。
- **False (and Missed) Discoveries in Financial Economics** ([链接](https://onlinelibrary.wiley.com/doi/abs/10.1111/jofi.12951))
  - _Campbell R. Harvey, Yan Liu · 2020 · The Journal of Finance, 75(5)_
  - 用 double-bootstrap 同时校准 Type I(假发现)与 Type II(漏发现)错误，给出对应特定 FDR(如5%)的 t 统计量门槛，并允许按两类错误的差异成本设阈值。为'审批门到底卡多严'提供了统计可辩护的依据，避免一刀切的 t>2。
- **Backtest Overfitting in the Machine Learning Era: A Comparison of Out-of-Sample Testing Methods in a Synthetic Controlled Environment** ([链接](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=4686376))
  - _Hamid R. Arian, Daniel Norouzi M., Luis A. Seco · 2024 · Knowledge-Based Systems (Elsevier) / SSRN 4686376_
  - 在受控合成环境中系统比较 K-Fold / Purged K-Fold / Walk-Forward / Combinatorial Purged CV(CPCV)，实证显示 CPCV 在抑制过拟合(更低 PBO、更高 DSR 统计量)与防假发现上显著优于 walk-forward；并提出 Bagged/Adaptive CPCV 变体。为'独立验证用什么交叉验证'给出 2024 年前沿证据。
- **Model Cards for Model Reporting** ([链接](https://arxiv.org/abs/1810.03993))
  - _Margaret Mitchell, Simone Wu, Andrew Zaldivar, et al. · 2019 · ACM FAT* '19_
  - 提出'模型卡'——标准化披露模型用途、训练数据、性能边界、适用条件与已知局限。是把 model inventory 条目做成非技术人员可读的'模型说明书'的工业标准模板，与 SR 11-7 的文档与台账要求天然契合。

### SOTA 方法

- **三道防线 + 独立验证职能分离** `[established]` — 第一道(研究/开发/业主)、第二道(独立 MRM/验证，向风险委员会而非模型业主汇报)、第三道(内审审框架)。量化落地=研究者不得自批自己的策略上线。
- **有效挑战 (Effective Challenge)** `[established]` — 由有能力、有权威、独立的复核者对模型提出实质质疑：概念合理性、数据、假设、限制。是 SR 11-7/26-2 的灵魂；在量化里对应'对抗式复核'+challenger 对照+敏感性测试。
- **Model Inventory + 按重要性分级 (Tiering by materiality)** `[established]` — 全量、权威、单一真相源的模型台账；按 purpose/exposure/inherent risk/reliance 分 Tier，决定验证深度与频率。SR 26-2 强化为风险导向、剔除低风险确定性工具。
- **Champion / Challenger 模型** `[established]` — 现役 champion 与候选 challenger 跑同一数据同一持有集对比，显著更优才晋升。MLOps 标准模式，量化里=新策略须跑赢现役并经独立评估才进 production。
- **Deflated Sharpe Ratio + 试验次数登记** `[established]` — 按累计试验次数与非正态性修正夏普，配 False Strategy 定理。要求跨研究员记录所有 backtest 试验数 n_trials 才能正确去偏——这是量化版的'有效挑战'量化闸门。
- **CSCV / PBO 与 Combinatorial Purged CV (CPCV)** `[emerging]` — CSCV 估计回测过拟合概率(PBO)；CPCV 用多路 purged+embargo 切分给出 OOS 分布做稳健推断。2024 实证显示 CPCV 显著优于 walk-forward。Bagged/Adaptive CPCV 为新兴变体。
- **上线后持续监控：漂移检测(PSI)+衰减触发** `[established]` — 用 PSI(>0.1 中度/>0.2 严重)、概念/数据漂移检测、滚动夏普衰减触发再训练或退役。SR 11-7'持续监控+结果分析'的实盘对应物；新研究把 PSI 升级为带不确定性的统计检验。
- **Harvey-Liu double-bootstrap 多重检验门槛** `[emerging]` — 同时控制 Type I/II 错误，按差异成本给出 t 统计量门槛。比固定 t>2 更可辩护，但在小样本/强横截面相关下仍有争议。
- **预注册 / 研究协议 (preregistration of hypotheses)** `[contested]` — 上线前冻结假设、选择标准、验证方案，杜绝 forking-paths/researcher degrees of freedom。学术上(资产定价多元宇宙分析)强证据支持，但量化业界尚无统一标准，工具化程度低。
- **AI/agentic 模型的治理归属** `[contested]` — SR 26-2 显式把生成式/agentic AI 排除在传统 MRM 之外、留待单独监管；学界有 model cards、AI Cards、agent-based governance 等提案。对'Agent 自动出工程'的本项目=争议且未定型的前沿。

### 最佳实践

- 把每个上线策略当作一个'模型'纳入单一权威 model inventory,按 materiality 分 Tier,Tier 决定验证深度与频率(SR 26-2 的风险导向裁剪)
- 强制职责分离:策略 creator 不得自批上线;晋升 production 必须有独立验证者(人或独立 Agent)的有效挑战记录与 approver≠creator 的签字
- 上线前预先设定选择标准并预注册假设;记录每一次 backtest 试验(跨研究员累计 n_trials),用累计试验数而非'选出来的那一个'去偏(DSR)
- 用 CPCV(优先于 walk-forward)+PBO 估计回测过拟合,challenger 对照同数据同持有集,敏感性/扰动测试作为有效挑战的标准动作
- 上线后持续监控:PSI 漂移(>0.1/>0.2)+滚动夏普衰减作触发,接生命周期状态机自动降级/退役,形成监控→预警→退役→台账更新→通知责任人的闭环
- 为非技术用户用模型卡(Model Card)+经济学语言+可视化流程状态条做渐进披露,让'流程即信任'可见可懂
- 供应商/外部/黑箱模型不免责,同样进台账、同样需有效挑战;AI/agentic 组件按 SR 26-2 倾向单独治理而非塞进传统 MRM

### QuantBT 现状

QuantBT 已具备 MRM 的'方法学半轮'但几乎没有'治理半轮'。已落地：M10 把过拟合证伪做成默认动作——PBO(CSCV, eval/pbo.py)、Deflated Sharpe(eval/dsr.py,形式上接受 n_trials)、Bootstrap Sharpe CI、Brinson 归因；M6 验证含 Purged k-fold+Embargo+Walk-forward(但缺 CPCV);M11 因子五态机(NEW→QUALIFIED→PROBATION→OBSERVATION→WARNING→RETIRED)有阈值与事件日志(但缺自动调度);M12 有 ExperimentStore+RunStore(含 lineage/forked_from)与 ModelRegistry 四态(dev→staging→production→archived);M19 有 risk_summary 7 规则+Glossary 渐进披露+coach。但治理闭环缺失:ModelRegistry.promote(store.py:232)是无审批、无 approver、无独立验证证据、无职责分离的裸状态转换,任何调用方可直推 production;无策略级 model inventory 与重要性分级;n_trials 不跨研究员累计登记,DSR 去偏可被架空;无独立验证角色/effective challenge 的强制流程;无 challenger 对照的存档要求;上线后漂移监控自认为缺(M10)、因子评估缺自动调度(M11),全生命周期问责未闭环。结论:有'体检指标',无'医院的接诊-会诊-签字-复查-销户制度'。

### 差距

- 有方法、无治理闸门：仓库已有 DSR(eval/dsr.py，带 n_trials 参数)、PBO/CSCV(eval/pbo.py)、Bootstrap CI、ModelRegistry 四态(dev→staging→production→archived)与因子五态机，但 ModelRegistry.promote(experiments/store.py:232) 是裸函数——任何调用方都能把模型直接推到 production，无审批人、无独立验证证据、无签字、无 go/no-go 门。这正是 SR 11-7 最核心的'有效挑战与职责分离'缺口。
- 无 model inventory / 模型台账与分级：没有'全量上线模型的单一权威台账+按重要性(敞口/是否实盘/资本占用)分 Tier 决定验证深度'的对象。M12 ModelRegistry 偏 ML 模型版本，不是策略级的机构台账；无法回答'我现在有哪些活的策略、各自风险等级、谁负责、上次验证何时'。
- n_trials 未跨研究员累计：DSR 形式上接受 n_trials，但没有系统级的'试验登记表'去统计某研究者/某 universe 累计跑了多少 backtest。López de Prado 的核心治理建议(记录每一次试验、跨研究员累计)未落地，DSR 去偏因而可被低报 n_trials 架空。
- 无独立验证角色与角色分离：缺'验证者 ≠ 开发者'的身份模型与权限。无 approver 字段、无第二人复核记录、无'验证向风险委员会汇报'的结构。Auth(M16)有用户但未接入 MRM 的角色分离。
- 无 challenger 对照的强制记录：M12 有 forked_from/lineage、champion/challenger 概念散落，但晋升 production 不强制'跑赢现役 champion 且同数据同持有集对比'并存档对比结论。
- 无上线后漂移监控闭环回灌治理：M10 自认'缺 live 漂移监控'；M11 因子五态机'缺自动调度评估'。没有 PSI/夏普衰减触发→自动降级/退役→台账状态更新→通知责任人的闭环。SR 11-7 的'持续监控'与全生命周期问责未闭环。
- 无预注册/研究协议：没有'上线前冻结假设与选择标准'的机制，forking-paths 风险无治理对冲。这对'经济学者出假设'的目标人群尤其关键——他们的假设恰恰需要被预登记以便事后无法被 Agent 暗中改写。
- 审批与问责未对非技术用户翻译：现有 PBO/DSR/风控摘要(eval/risk_summary.py 7 规则)是给会看指标的人；缺把'有效挑战通过/未通过、谁签的字、为什么能上线'翻译成经济学语言与流程状态的治理叙事层。

### Agent OS 在这一环的角色（服务零代码用户）

这一环是'流程即信任'最吃重的地方：零代码小白与经济学者读不懂 DSR 公式，他们能信任 Agent 产出的唯一支柱，就是看到一条像样的、不可被研究者(或 Agent 自己)私下绕过的审批与问责流程。Agent OS 在此应扮演'合规副驾+流程导轨'而非'自动审批人'：(1) 角色分离要落到 Agent 编排层——'研究 Agent'负责出策略与证据，'独立验证 Agent'扮演 challenger/effective-challenge 角色独立重跑(不同 CV、challenger 对照、敏感性、n_trials 复核)并写出质疑清单；人类(经济学者)只在 go/no-go 门上按按钮，这正好对应硬约束'经济判断与风控必须 human-in-the-loop'。(2) 翻译严谨度：把'DSR 在 n_trials=N 下不显著/PBO=42%/PSI=0.27 已漂移'翻成经济学语言——'你试了 200 种参数才挑出这个，统计上它很可能只是运气；而且最近三个月市场已经变了，这套逻辑的前提不再成立'，并用'模型卡'(Model Cards 模板)给每个上线策略一页人话说明书：它在赌什么经济逻辑、什么时候会失效、谁批的、上次体检何时。(3) 流程可视化即信任：把 SR 11-7 的台账/分级/三道防线/退役做成一条可点击的状态条(假设登记→证据→独立验证签字→审批门→投产→监控→预警→退役)，让小白即使不懂数学也能看到'这一步过了没、谁负责、卡在哪'。(4) 渐进披露：小白只看红/黄/绿灯与一句话结论；经济学者展开看'有效挑战'清单与 challenger 对比；会写代码的 quant 再下钻到 DSR/PBO 原始数与 n_trials 登记。(5) 防自欺护栏：预注册让 Agent 不能在事后偷偷改假设/选择标准；试验登记让 Agent 不能低报 n_trials 来美化 DSR——这两条是'让非技术用户敢信 Agent'的关键工程纪律。

### 建议

- 把 ModelRegistry.promote 改造成带审批门的状态机：晋升到 staging/production 必须附带(a)独立验证记录 id、(b)approver 身份且 approver≠该策略 creator、(c)过拟合证据快照(DSR+n_trials/PBO/Bootstrap CI)与 challenger 对比结论。缺任一则拒绝晋升并返回缺口清单。这是堵住最核心 SR 11-7 缺口的最小改动。  `[→M12 ModelRegistry / experiments/store.py, eff=med, lev=high]`
- 建立策略级 Model Inventory 与 Tiering：新增 model_inventory 表，每个上线候选=一条台账(用途/经济逻辑/责任人/Tier/是否触达实盘/上次验证时间/当前生命周期态)。Tier 由是否接实盘(加密)、资本敞口、复杂度决定，Tier 决定要求的验证深度(如 Tier1 强制 CPCV+challenger，低 Tier 可 walk-forward)。直接呼应硬约束'资产无关——靠填配置接入'。  `[→新 M(治理) + 复用 M11 lifecycle/M12 registry, eff=med, lev=high]`
- 实现系统级'试验登记表'(trial ledger)：每次 backtest run 自动 +1 计入 (researcher, universe, 假设) 维度的累计 n_trials，DSR 计算强制从 ledger 取 n_trials 而非调用方传入，杜绝低报去偏。落地 López de Prado 的核心治理建议。  `[→M10 eval/dsr.py + M12 ExperimentStore, eff=med, lev=high]`
- 新增'独立验证 Agent'编排角色作为 effective challenge：在研究 Agent 产出策略后，自动以 challenger 身份用不同 CV(优先 CPCV)、challenger 模型对照、敏感性/扰动测试独立重跑并生成'质疑清单 + 通过/未通过 + 理由'，写入审批门作为人类 go/no-go 的输入。把现有散落的 M14 reAct/M18 沙箱拧成验证流。  `[→M14 AgentRuntime + M18 IDESandbox + M10 eval, eff=high, lev=high]`
- 为每个上线策略生成'模型卡'(Model Card 模板,经济学语言)：用途/赌的经济逻辑/适用与失效条件/已知局限/Tier/审批人/上次验证。作为台账条目的人类可读面与渐进披露的 L1 层,直接服务非技术用户的'能信'。  `[→M15 前端 + M19 Glossary 渐进披露 + M12 registry, eff=low, lev=high]`
- 闭合上线后监控→退役回路：用 PSI(>0.1 黄/>0.2 红)+滚动夏普衰减作触发,接入 M11 因子五态机的自动调度(补其'缺自动调度评估'),触发→自动降级/进 WARNING/RETIRED→更新台账态→通知责任人。M13 DAG 引擎(croniter)正好做调度载体。  `[→M11 lifecycle + M10(补 live 漂移) + M13 DAG, eff=med, lev=med]`
- 加'假设预注册'轻量门：上线前把假设、入选/淘汰标准、验证方案冻结成不可变记录(类 dataset_version),事后 Agent 与人都不能改,只能新开版本。对冲 forking-paths,且让经济学者的意图无法被 Agent 暗改——直接支撑'人只出意图与判断'。  `[→M1 StrategyGoal + M12 lineage, eff=med, lev=med]`
- 治理叙事层:把审批门状态做成可点击状态条(假设登记→证据→独立验证→审批→投产→监控→退役)+一句话人话结论,按人群渐进披露(小白看灯/经济学者看挑战清单/quant 下钻原始数)。让'流程即信任'对非程序员可见可懂。  `[→M15 前端(注意 RunDetailPage 冻结,做成新页) + M19 教学 Agent, eff=med, lev=high]`

### 对抗式核查裁决 — 总体置信度：**high**

_纠正摘要_: 六条论断中 3 条 confirmed (1/5/6)、1 条 confirmed (3，附边界补充)、2 条 nuanced (2/4)；所引 6 篇论文全部真实存在且描述基本准确，无虚构。关键核查结果: (1) 用一手 federalreserve.gov 文件确认 SR 26-2 于 2026-04-17 取代 SR 11-7 与 SR 21-8、>300 亿美元门槛属实，并直接从官方 PDF (SR2602a1.pdf) 脚注3 抽出原句证实 'Generative AI and agentic AI models ... are not within the scope of this guidance'——sia-partners 二手解读与原文一致，但需纠正一点:被排除的只是生成式/agentic AI，'非生成式、非 agentic 的传统统计/量化 ML 模型' 仍受指引约束(对 QuantBT 的 .pkl/.pt 模型意味着仍在治理精神内)。(5) 代码层逐路核实 promote 确为裸状态转换且 REST/service 层无任何 approval/gate/职责分离守卫，唯一护栏 MainnetGuards 只管实盘交易、未接入晋级路径——论断完全成立。需降级为 nuanced 的两条:论断2 CPCV '显著优于' walk-forward 仅在合成受控环境成立，walk-forward 的时序真实性在最终部署验证上不可替代，二者互补而非取代;论断4 Harvey-Liu double-bootstrap 在大规模因子研究中优于 t>2，但在小团队/小样本/低频场景增益有限且可能过度保守(Type II 代价)。论断3 成立但须强调 DSR 依赖如实登记 n_trials 且应使用 effective N(聚类去相关)、对强自相关收益需调整 Sharpe 方差——这两点是 False Strategy 定理的硬假设边界。论断6 成立:按 SR 26-2 materiality 原则，保留三件核心(职责分离/有效挑战、n_trials 登记、轻量 model inventory+model card)、裁掉机构级官僚层(独立验证团队/董事会问责/强制年度再验证)，确定性计算器可直接援引 SR 26-2 原文的 model 定义豁免。

被降权/纠正的论断：
- `nuanced` — 论断2: CPCV 在抑制过拟合上显著优于 walk-forward(更低 PBO、更高 DSR)，且该结论可直接推广。
  - 纠正：'显著优于' 是论文在其合成环境下的结论，不应表述为普适事实。重要反向考量：(1) walk-forward 是唯一严格保持时间单向性、最贴近真实滚动部署的方案，CPCV 通过组合多段训练/测试在生产化时序约束下并不能真正落地(回测可用、上线不可复制)；(2) CPCV 在样本短、组合数多时切片高度重叠、相关，PBO 估计本身也会受影响；(3) 中低频策略试验数远少于因子海，CPCV 的多路径优势收益递减。结论应改为：CPCV 在过拟合诊断/研究阶段更优(尤其与 PBO/DSR 配套)，walk-forward 在最终部署前的时序真实性验证上不可替代——两者互补，而非 CPCV 全面取代 walk-forward。
- `nuanced` — 论断4: Harvey-Liu double-bootstrap 门槛优于固定 t>2。
  - 纠正：'优于' 应限定语境。该方法面向的是大规模横截面因子研究(成百上千个因子、可估计跨试验相关结构);在中低频、小样本、试验数很少的个人/小团队场景，bootstrap 的可靠性下降，且其设计偏向控制假发现可能带来 Type II(漏掉真 alpha)代价——论文本身就指出现有方法 'lack power to detect outperforming managers'。所以对小团队它不是无脑更优；在样本极少时它相对 t>2 的边际收益有限，甚至可能过度保守。结论:作为可调阈值框架在方法论上优于固定 t>2，但实际增益强依赖试验规模与横截面相关结构。

---


## [7] 假设预注册 & 研究计划级多重检验  · 组 B

**机构级标准** — 在研究计划层面对抗 p-hacking，机构级标准是把"严谨"从单次回测推到整个研究项目的生命周期，由四块拼成：(1) 预注册/预分析计划(PAP)：在看 OOS 数据之前，冻结一份带时间戳、不可篡改的文档，写明经济学假设、universe、信号构造、标签、组合规则、评估指标与 go/no-go 阈值；分析自由度(researcher degrees of freedom)在数据冻结前被锁死，事后任何偏离都标记为 exploratory 而非 confirmatory。(2) 试验数核算(trial accounting)：系统而非人记住"到底试了多少个策略/配置/参数网格点"，因为 garden of forking paths 意味着即使只跑了一条最终策略，只要选择是在看过数据后做的，等效试验数就远大于 1。这个 N(或其有效独立试验数 N_eff)必须被自动追踪并喂给多重检验校正。(3) 多重检验校正：对一族检验控制 family-wise error rate(FWER, 如 Bonferroni/Holm、White Reality Check、Romano-Wolf stepwise)或 false discovery rate(FDR, Benjamini-Hochberg/Benjamini-Yekutieli)；在因子/策略研究里具体落到 Harvey-Liu-Zhu 的 t>3.0 门槛、Deflated Sharpe Ratio(用 N 与试验 SR 方差扣减选择偏差)、Harvey-Liu 的 haircut Sharpe 与 double-bootstrap FDR、以及 Lopez de Prado 的 PBO/CSCV。(4) 治理闭环：假设登记表(hypothesis registry)+ 独立验证 + 审批门 + 全部试验(含失败)留痕，杜绝 file-drawer。学术与买方近年共识是：单次回测的 t>2 早已不可信，N 必须被诚实记账，且"报告所有试验"是第一性原则——隐藏失败的试验只会低估过拟合概率。


### 关键论文 / 权威实践

- **… and the Cross-Section of Expected Returns** ([链接](https://academic.oup.com/rfs/article/29/1/5/1843824))
  - _Campbell R. Harvey, Yan Liu, Heqing Zhu · 2016 · Review of Financial Studies 29(1), 5-68 (NBER w20592, 2014)_
  - 奠基性多重检验框架：编录学界已检验的 316+ 因子，论证在如此规模的数据挖掘下单次 t>2 失效，提出新因子应清过 t>3.0 门槛；给出 Bonferroni/Holm/BHY 三法的金融适配，并产出 1967 至今的历史显著性临界值时序，允许检验间相关与缺失数据。是'how many strategies were tried 必须入账'这一论点的学术锚点。
- **The Deflated Sharpe Ratio: Correcting for Selection Bias, Backtest Overfitting and Non-Normality** ([链接](https://www.davidhbailey.com/dhbpapers/deflated-sharpe.pdf))
  - _David H. Bailey, Marcos López de Prado · 2014 · Journal of Portfolio Management 40(5), 94-107_
  - 定义 DSR = Φ((SR-SR0)·√(T-1)/√(1-γ3·SR+(γ4-1)/4·SR²))，其中阈值 SR0 = √V[SR_n]·((1-γ)·Φ⁻¹(1-1/N)+γ·Φ⁻¹(1-1/(Ne)))，γ≈0.5772。核心：SR0 随试验数 N 与跨试验 SR 方差 V[SR_n] 上升，把'选最优'的选择偏差量化扣减。明确主张应预先规划试验、记录全部 N(含失败试验)，否则低估过拟合。QuantBT 的 dsr.py 正是此公式的实现。
- **The Probability of Backtest Overfitting** ([链接](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2326253))
  - _David H. Bailey, Jonathan Borwein, Marcos López de Prado, Qiji J. Zhu · 2017 · Journal of Computational Finance 20(4)_
  - 提出 CSCV(组合对称交叉验证)估计 PBO——训练集最优策略在测试集排名跌入下半区的频率。强调必须记录全部试验(成功+失败)，丢弃失败试验只会低估 PBO。QuantBT 的 pbo.py 实现此算法。
- **Lucky Factors** ([链接](https://people.duke.edu/~charvey/Research/Published_Papers/P146_Lucky_factors.pdf))
  - _Campbell R. Harvey, Yan Liu · 2021 · Journal of Financial Economics 141(2), 413-435_
  - 用 White(2000)/Romano-Wolf(2005) reality bootstrap 在保留检验间截面相关结构下控制 FWER，对'从一堆候选因子里挑出的那个是否真有截面解释力'做正确的多重检验。比逐一 t 检验更贴合 quant 实际流水线(同时筛多个因子)。
- **False (and Missed) Discoveries in Financial Economics** ([链接](https://onlinelibrary.wiley.com/doi/abs/10.1111/jofi.12951))
  - _Campbell R. Harvey, Yan Liu · 2020 · Journal of Finance 75(5), 2503-2553_
  - 用 double-bootstrap 同时校准 Type I/II 错误，给出对应特定 FDR(如 5%)的 t 门槛；强调过度严苛的 FWER 会制造大量 missed discoveries(Type II)，主张 FDR 而非纯 FWER。是 Harvey 阵营从't>3 一刀切'走向'按 FDR 调门槛'的演进。
- **The Garden of Forking Paths: Why multiple comparisons can be a problem, even when there is no fishing expedition or p-hacking and the research hypothesis was posited ahead of time** ([链接](https://sites.stat.columbia.edu/gelman/research/unpublished/p_hacking.pdf))
  - _Andrew Gelman, Eric Loken · 2013 · Working paper, Columbia University_
  - 提出'分叉路花园'：即便只跑一次分析、假设也是事前提出的，只要数据处理与分析选择是在看过数据后做的(数据剔除、合并、主效应 vs 交互、子样本切法),等效多重比较就已发生。这正是 quant'我就跑了一条策略'自辩的反驳——选择本身即试验。
- **Nonstandard Errors** ([链接](https://onlinelibrary.wiley.com/doi/10.1111/jofi.13337))
  - _Albert J. Menkveld, Anna Dreber, Felix Holzmeister, et al. (#fincap, ~350 作者) · 2024 · Journal of Finance 79(3), 2339-2390_
  - 让 164 个团队在同一数据上检验同 6 个假设，发现因研究者自由度产生的'非标准误差'与标准误差量级相当；peer feedback 后显著下降,且参与者系统性低估它。为'同一数据多分析路径会发散'提供了大规模实证,直接量化 garden of forking paths 在金融的后果。
- **Is There a Replication Crisis in Finance?** ([链接](https://onlinelibrary.wiley.com/doi/10.1111/jofi.13249))
  - _Theis I. Jensen, Bryan Kelly, Lasse H. Pedersen · 2023 · Journal of Finance 78(5)_
  - 用层级贝叶斯/经验贝叶斯模型对全球因子做联合多重检验,得出复制率远高于 Hou-Xue-Zhang(2020)的悲观结论(原样本 ~55.6%,以 CAPM alpha 计 82.4%)。代表多重检验从频率派 FWER/FDR 走向'借力(shrinkage)+先验'的贝叶斯范式——与 Harvey-Liu 阵营存在方法论张力(contested)。
- **In Praise of Moderation: Suggestions for the Scope and Use of Pre-Analysis Plans for RCTs in Economics** ([链接](https://www.nber.org/papers/w26993))
  - _Maximilian Kasy, et al. (亦见 Olken 2015 JEP, Coffman-Niederle 2015 JEP) · 2020 · NBER w26993_
  - 系统讨论预分析计划(PAP)的范围与边界:对 confirmatory 假设强制预注册以控自由度,但保留 exploratory 分析空间;经济学 AEA RCT Registry(2013 起)是把预注册制度化的范例。给 QuantBT 设计'假设登记表 + confirmatory/exploratory 二分'提供制度蓝本。
- **Specification Curve Analysis** ([链接](https://faculty.wharton.upenn.edu/wp-content/uploads/2016/11/33-Simonsohn-Simmons-Nelson-2020.pdf))
  - _Uri Simonsohn, Joseph Simmons, Leif Nelson · 2020 · Nature Human Behaviour 4, 1208-1214_
  - 规范化 multiverse/specification-curve:枚举所有'理论合理、统计有效、非冗余'的设定,图示结果分布并对全部设定做联合推断。把'分叉路'从隐患变成可视化的稳健性证据——非常适合给非程序员看'换一组合理选择,结论稳不稳'。

### SOTA 方法

- **Deflated Sharpe Ratio (DSR) + 期望最大 SR 基准** `[established]` — 用试验数 N 与跨试验 SR 方差扣减选择偏差,输出该 SR 在多重检验下'非运气'的概率。买方事实标准。QuantBT 已实现,但 N 靠人手填。
- **PBO via CSCV (组合对称交叉验证)** `[established]` — 估计'训练集最优在测试集跌入下半区'的概率,衡量配置搜索导致的过拟合。要求记录全部试验含失败。QuantBT 已实现。
- **Harvey-Liu-Zhu t>3.0 门槛 + 历史临界值时序** `[established]` — 对新因子提高显著性门槛以吸收已检验因子的数据挖掘。是因子研究的共识起点,但被批评为对相关/缺失结构敏感、可能过度保守(制造 missed discoveries)。
- **FWER 控制:White Reality Check / Hansen SPA / Romano-Wolf stepwise** `[established]` — 在'从候选集挑最优'时控制至少一个假阳的概率,保留检验间相关结构(bootstrap)。Lucky Factors 用此法。比逐一 Bonferroni 更有功效。
- **FDR 控制:Benjamini-Hochberg/Benjamini-Yekutieli + Harvey-Liu double-bootstrap** `[established]` — 控制假发现比例而非'一个都不能错',在大规模因子筛选中比 FWER 功效高、漏检少。Harvey-Liu(2020)把它与 Type II 错误一起校准。
- **预注册 / 预分析计划 (PAP) + 假设登记表** `[emerging]` — 数据冻结前登记经济假设、构造、阈值,锁死分析自由度,区分 confirmatory/exploratory。经济学 AEA Registry 已制度化;金融 quant 界尚未普及,是把治理落地的关键缺口。
- **层级/经验贝叶斯联合多重检验 (Jensen-Kelly-Pedersen)** `[contested]` — 用先验+shrinkage 跨因子借力,得出比频率派更乐观的复制率。与 Harvey-Liu 频率派门槛存在范式之争——是否'真危机'本身有争议。
- **Multiverse / Specification Curve Analysis** `[emerging]` — 枚举所有合理设定并联合推断,把分叉路变成可视稳健性证据。在 ML/经济学上升,金融应用仍零散;对非程序员极友好。
- **等效独立试验数 N_eff 估计 (聚类/相关结构)** `[emerging]` — 原始试验数 N 高估独立性(多配置高度相关),用聚类或相关矩阵估有效独立试验数喂给 DSR。DSR 原文与 Lopez de Prado 都建议;工程实现稀少。
- **非标准误差披露 (#fincap 范式)** `[emerging]` — 承认并量化研究者自由度带来的结论发散,通过多团队/多路径或敏感性分析披露。理念前沿,尚无标准工具链。

### 差距

- 最致命:DSR/PBO 的试验数 N 是用户手填的整数(见 dsr.py:43 与 tool_schema.py:170 仅暴露 n_trials),系统没有从 ExperimentStore 自动统计'整个研究项目实际跑了多少个策略/配置/参数网格点'。这意味着任何用户(尤其零代码小白)都会无意或有意低报 N,使 DSR 失真——这是 garden of forking paths 在 QuantBT 里活生生的开口。
- 没有预注册/预分析计划(PAP)产物:M1 StrategyGoal 捕获了经济意图,但不是一份带时间戳、不可篡改、在看 OOS 数据前冻结的 confirmatory 假设登记;没有 confirmatory vs exploratory 的二分,事后改阈值/换 universe/挑指标无任何留痕或降级标记。
- ExperimentStore(experiments/store.py)记了 lineage(parent_run_id/forked_from),但没有把它聚合成'程序级试验账本':没有 trial_count、没有把同一假设下的所有分叉(参数扫描、universe 变体、标签变体)归并计数,也没有把这个计数回喂给 DSR 的 N。
- 只有单次检验层面的校正(DSR/PBO/bootstrap CI),完全缺研究计划层面的 family-wise / FDR 跨 run 校正:没有 Holm/BHY/Romano-Wolf,无法对'我这个项目里同时检验的一族策略'控制 FWER 或 FDR。
- 没有等效独立试验数 N_eff 估计:即便统计了 N,高度相关的配置不该按独立计;缺聚类/相关结构降维到 N_eff 的步骤,DSR 会过度惩罚或惩罚不足。
- 没有 file-drawer 防护:失败/被弃的试验是否计入 N 无强制;PBO 原文明确要求记录全部含失败试验,否则低估过拟合,但当前流程不强制把放弃的 run 留痕并计数。
- 缺把上述严谨度翻译成非程序员可读语言的层:没有'你这次结论相当于在 N 次尝试里挑了最好的一次,扣除运气后还剩多少可信'这类经济学/直觉化解释,也没有 specification-curve 式的'换一组合理选择结论稳不稳'可视化。

### Agent OS 在这一环的角色（服务零代码用户）

把'研究计划级多重检验'做成 Agent OS 的隐形导轨,人只出经济判断,记账与校正全自动。关键设计:(1) 预注册即对话:需求澄清 agent 把模糊念头逼成一份良构假设——'你预期什么经济机制驱动收益?在哪些标的、哪个时段、用什么信号?多高的夏普/最大回撤你才认为成立?'——确认后冻结成带时间戳的 PAP 卡片(扩展 M1 StrategyGoal),用户读得懂的自然语言条款,而非代码。这一步本身就是把'流程即信任'兑现给读不懂代码的经济学者:他能逐条看懂自己承诺了什么。(2) 试验自动记账:agent 每跑一条策略/参数扫描/universe 变体,OS 在 ExperimentStore 里自动累加该假设的 trial_count 并估 N_eff,用户无需知道'多重检验'四个字。当用户(经济学者)说'再试试加个动量因子',agent 不只是跑,而是回一句人话:'这是你这个假设下的第 7 次尝试。试得越多,凑巧好看的概率越高,所以我会把及格线相应抬高。'(3) 严谨度的翻译:把 DSR/PBO/FDR 全部翻成'扣运气后的可信度'。例如:'你看到的夏普 1.8,但你试了 40 种配置挑了最好这个;扣掉挑选带来的运气,真实可信的夏普约 0.6,达不到你预注册时定的 1.0 门槛——按你自己立的规矩,这条不该上。'用 specification-curve 给一张图:'下面 40 种合理设定里,只有 6 种为正——结论很脆,建议当探索而非确认。'(4) human-in-the-loop 闸门:go/no-go 永远由人按,但 agent 把'你事前承诺的阈值 vs 现在的扣运气结果'并排摆出,并标红任何'事后改过阈值/换过 universe'的偏离(自动从 confirmatory 降级为 exploratory),让非技术用户靠流程治理而非读代码来信任产出。资产无关:PAP 卡片与试验账本只认'假设/标的池/时段/指标'这些抽象字段,股/期货/FX 换 connector 不改流程。

### 建议

- 在 ExperimentStore 增加'假设(Hypothesis)'一级实体与 trial_count 聚合:同一 hypothesis_id 下所有 run(含参数扫描、universe/标签变体、含失败/弃用)自动累加,并提供 program_trial_count API。这是堵住 garden of forking paths 的地基。  `[→M12 实验/注册表, eff=med, lev=high]`
- 把 DSR/PBO 的 N 从用户手填改为默认由 ExperimentStore 的 program_trial_count 自动注入(用户可声明但偏离要留痕)。让'诚实的 N'成为系统默认而非自觉。  `[→M10 回测&归因 + M12, eff=low, lev=high]`
- 新增预注册产物:扩展 M1 StrategyGoal 为不可篡改、带时间戳的 PAP 卡片(经济假设、universe、信号、标签、组合、go/no-go 阈值),并打 confirmatory/exploratory 标记;OOS 数据访问前冻结,事后偏离自动降级并红标。  `[→M1 StrategyGoal + M12, eff=med, lev=high]`
- 加研究计划级多重检验校正模块:对同一 hypothesis(或用户选定的一族 run)做 Holm/Benjamini-Hochberg(FDR)与 Romano-Wolf stepwise(保留相关结构的 FWER),输出'整族里有几个真发现'。复用现有 bootstrap.py。  `[→M10 回测&归因, eff=med, lev=high]`
- 实现等效独立试验数 N_eff:对该假设下所有 run 的收益序列做相关聚类,把原始 N 折算为 N_eff 再喂 DSR(DSR 原文与 Lopez de Prado 建议),避免高相关配置被当独立计。  `[→M10, eff=med, lev=med]`
- 把严谨度翻译进 risk_summary 与 coach:新增规则'扣运气后可信度'——用经济学语言陈述'你试了 N 次/扣选择偏差后的有效夏普/对照你预注册阈值的 go-no-go',并由教学 Agent 苏格拉底式追问'这是第几次尝试'。  `[→M19 Glossary+Mode2 教学 Agent + M7 risk_summary, eff=low, lev=high]`
- 前端加 specification-curve / multiverse 视图:对一族合理设定画'有多少为正'的脆弱性图,给非程序员一眼看懂稳健性(注意 RunDetailPage 收益概述页冻结,需新页或仅加字段)。  `[→M15 前端 + M10, eff=med, lev=med]`
- 强制 file-drawer 留痕:任何被放弃/失败的 run 必须落 ExperimentStore 并计入 trial_count,审批门前展示'本假设全部尝试(含弃用)清单',兑现 PBO 原文'记录全部试验'要求。  `[→M12 + M13 编排(审批门), eff=low, lev=med]`
- 提供贝叶斯/经验贝叶斯 shrinkage 作为可选第二意见(Jensen-Kelly-Pedersen 范式),与频率派 DSR/FDR 并列展示,显式标注这是 contested 的范式之争而非定论,避免给非专家造成虚假确定性。  `[→M6 模型 + M10, eff=high, lev=med]`

### 对抗式核查裁决 — 总体置信度：**high**

_纠正摘要_: 总体: 10 篇引用论文全部真实存在,绝大多数被准确描述; 6 条论断在方向上全部站得住(无一被整体推翻)。核心结论如下。

【最重要的事实错误 — 必须改】(1) 'In Praise of Moderation'(NBER w26993, 2020)被错误归到 Maximilian Kasy 名下; 真实作者是 Banerjee, Duflo, Finkelstein, Katz, Olken, Sautmann——Kasy 根本不是作者。这是唯一一处虚构归因,判 refuted(内容对、署名错)。

【代码保真隐患 — 强烈建议修】(2) dsr.py 第33-38行 _expected_max_sr 用了一个粗近似 √(2lnN)-γ/√(2lnN),既偏离原文精确式 (1-γ)Φ⁻¹(1-1/N)+γΦ⁻¹(1-1/(Ne)),又【完全省略 √V[SR_n] 项】(等价假设跨试验 SR 方差=1)。原文 Snippet 是 mu+sigma*((1-emc)*ppf(1-1/N)+emc*ppf(1-1/(N·e)))。建议改用精确式并注入真实 V[SR_n],否则 SR0 系统性失真。分母用观测 SR̂(代码 sr_per_period)与 (γ4-1)/4 系数(代码 (kurt_excess+2)/4)均与原文一致、正确; 年化口径(per-period + expected/√periods)方向正确。

【概念确认 — 直接采纳】(3) DSR 公式中 N 确为'独立试验数'(原文 Appendix A.3 逐字: 用 M 代替 N 会高估 SR0),所以自动灌原始相关 program_trial_count 会过度惩罚,必须先做相关聚类/ONC 估有效 N——论断1完全成立。(4) t>3 已被 Harvey-Liu 自己相对化('2.0 与 3.0 均非最优,门槛在区间内随数据可变'),写死成硬阈值不符当前文献——论断2成立,应做成可配置软门槛。(5) 网传 'DSR=SR×[1-γlnN/SR]' 是伪式,弃用——论断3成立。(6) Menkveld NSE 结论域是 EuroStoxx 期货微观结构,外推到截面因子需另证——论断5的谨慎正确。(7) 预注册对'可无限重跑'的量化回测易被架空、无成功移植的权威实证,应配 confirmatory/exploratory 二分 + 登记 N + 规范曲线复合方案——论断6成立。

【判 nuanced 的两点】论断4(记录全部含失败试验)与'丢弃失败低估 PBO'更多是 López de Prado 后续著作的强表述,2017 PBO 论文由 CSCV 设计本身保证不丢试验; 自动化/agentic 下 N 封顶仍是开放问题(工程答案=ONC 聚类估有效独立数,无权威定论)。论断6同上。

【次要署名核对】2016 RFS 发表版作者确为 Heqing Zhu(早期 SSRN 预印本署 Caroline Zhu,同一人),论断引用无误。Nonstandard Errors '164 团队'与 '~350 作者'不矛盾(团队数 vs 总署名数)。JKP 的 35%/55.6%/82.4% 三档复制率已逐字核对原文 Figure 1,准确。

证据强度: DSR、PBO、JKP 三篇关键论文均下载原始 PDF 用 pypdf 逐字读取核对(非仅靠摘要),其余经多源检索交叉确认; 故 overall_confidence=high。

被降权/纠正的论断：
- `nuanced` — 论断4: '记录全部试验(含失败)否则低估过拟合'来自 PBO/DSR 原文规范主张; 但其量化效应大小、及自动化 agent 流水线下 N 该如何定义/封顶,原文未给工程化答案; 需查 2023-2026 是否有专门处理'自动化/agentic 搜索下试验计数'的文献。
  - 纠正：把'记录全部含失败试验否则低估过拟合'更准确归因为'DSR/PBO 系列(尤其 López de Prado 后续阐述)的规范主张',而非 2017 PBO 论文的逐字结论。自动化下 N 的定义=用聚类得有效独立试验数,封顶规则属开放问题,无权威定论。
- `nuanced` — 论断6: 预注册(PAP)在经济学 RCT 有制度与实证收益, 但对'观测性/非实验/可重跑回测'的量化策略是否同样有效、还是被'反正能无限重跑'架空存在争议(Olken 2015 perils); 需查是否有把预注册成功移植到 quant backtesting 的实证或权威实践。
  - 纠正：重要纠正(作者署名错误): 论断把 'In Praise of Moderation' 第一作者写成'Maximilian Kasy 等'是【错的】。该文实际作者为 Banerjee, Duflo, Finkelstein, Katz, Olken, Sautmann(NBER w26993, 2020-04),Kasy 不在作者之列(Kasy 另有 forking paths/PAP 相关工作,易混淆)。其余(Olken 2015 JEP、Coffman-Niederle 2015 JEP 作为相关参考)正确。结论: quant 回测应采'confirmatory/exploratory 二分 + 登记 N + 规范曲线'的复合方案,不能仅靠预注册。
- `refuted` — 引用论文: Kasy 等(2020) In Praise of Moderation — 讨论 PAP 范围边界, confirmatory 强制预注册、保留 exploratory, AEA RCT Registry(2013起)为制度范例; 给 QuantBT '假设登记表+confirmatory/exploratory 二分'蓝本。
  - 纠正：改署名为 Banerjee, Duflo, Finkelstein, Katz, Olken & Sautmann (2020), NBER w26993。Kasy 有独立的 PAP/forking-paths 相关研究,但与本文无关,勿混。括注的 Olken(2015 JEP)、Coffman-Niederle(2015 JEP)作为相关参考无误。内容蓝本结论可保留, 仅须修正引用归属。

---


## [8] 可复现/谱系/PIT/feature store 研究基建  · 组 B

**机构级标准** — 该环节的机构级标准（顶级量化机构如 Two Sigma / AQR / Man Group / Citadel + 受监管银行的 SR 11-7 model-risk 框架）是：让任何一个策略结论在数年后、由独立第三方、用当时可得的数据完全重算出来。具体要求六层：(1) Point-in-Time 数据正确性——所有数据按"当日真实可得"对齐，区分 valid time（业绩归属时点）与 transaction time（入库/修订时点），即 bitemporal 建模；财报用 as-reported 而非 restated，必须建模发布滞后/重述/backfill，universe 要 PIT 重建以消除幸存者偏差。(2) 不可变、可寻址的数据版本——每个数据集有内容寻址 hash（非仅命名版本），可 time-travel 到任意历史快照（ArcticDB/Delta/lakeFS 模式）。(3) 端到端 lineage / 谱系——从原始数据→特征→标签→模型→信号→回测的每条边可追溯，符合 OpenLineage 这类开放标准的 run/job/dataset 模型，理想到列级 lineage。(4) 训练-服务一致性——研究期与实盘期用同一套特征定义计算，消除 training-serving skew（feature store 的核心价值）。(5) 数据质量闸门——schema/取值域/新鲜度/分布漂移的声明式断言（Great Expectations / dbt tests / data contracts），失败即阻断管线。(6) 审计与问责 trail——实验注册、预注册假设、所有 trial 计数、独立验证、审批门、git commit + 环境指纹，使"读不懂代码的人也能信任结果"。SR 11-7 把这些上升为监管要求：开发-验证-治理三权分立，验证人独立于开发人，文档详尽到"不熟悉该模型的人也能理解其运作、局限与关键假设"。学术界的 reproducibility crisis（见下）证明：没有这套基建，量化研究结果在统计上多半是假的。


### 关键论文 / 权威实践

- **Nonstandard Errors** ([链接](https://onlinelibrary.wiley.com/doi/10.1111/jofi.13337))
  - _Albert J. Menkveld, Anna Dreber, Felix Holzmeister, Jürgen Huber, Magnus Johannesson, Michael Kirchler 等 (#fincap 项目, 164 个团队) · 2024 · The Journal of Finance, Vol. 79, No. 3, pp. 2339-2390_
  - 里程碑式实证：164 个研究团队在同一份数据上检验同样 6 个假设，结果离散度（'非标准误差'）与标准误差量级相当——即'研究者自由度/工程选择'本身就是巨大不确定性来源。关键发现：可复现性提高 1 个标准差使非标准误差降 25%，同行评议评分提高 1 个标准差降 33%，且参与者系统性低估自己结果的脆弱性。直接论证了可复现/谱系基建不是工程洁癖而是结论可信度的支柱。
- **...and the Cross-Section of Expected Returns** ([链接](https://www.nber.org/papers/w20592))
  - _Campbell R. Harvey, Yan Liu, Heqing Zhu · 2016 · Review of Financial Studies, 29(1), 5-68_
  - 多重检验框架：因 factor zoo 的大规模数据挖掘，新因子的显著性门槛不能再用 t>2，需 t>3 以上；313 个被宣称的因子里仅 9 个能过门槛。确立了'必须记录所有 trial 数并据此 deflate 显著性'的标准——这是预注册与 trial-counting 基建的学术根基。
- **Replicating Anomalies** ([链接](https://academic.oup.com/rfs/article-abstract/33/5/2019/5236964))
  - _Kewei Hou, Chen Xue, Lu Zhang · 2020 · Review of Financial Studies, 33(5), 2019-2133_
  - 对 452 个已发表异象做统一重做：用 NYSE 断点+市值加权抑制 microcap 后，65% 过不了 t>1.96，按多重检验门槛 t>2.78 失败率升到 82%；存活异象的经济幅度也远小于原报告。实证了幸存者偏差/microcap 污染/方法学差异如何制造假发现，是 PIT universe 重建与统一回测协议的强论据。
- **Pseudo-Mathematics and Financial Charlatanism: The Effects of Backtest Overfitting on Out-of-Sample Performance** ([链接](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2308659))
  - _David H. Bailey, Jonathan M. Borwein, Marcos López de Prado, Qiji Jim Zhu · 2014 · Notices of the American Mathematical Society, 61(5)_
  - 证明只要试足够少量配置就能 backtest 出漂亮净值；因为研究者很少披露试过的配置数，投资者无法评估过拟合程度。确立了'每个回测必须连同其全部 trial 数一起报告'的治理原则——直接映射到实验注册表必须记 trial 计数。
- **The Probability of Backtest Overfitting** ([链接](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2326253))
  - _David H. Bailey, Jonathan M. Borwein, Marcos López de Prado, Qiji Jim Zhu · 2017 · Journal of Computational Finance, 20(4), 39-69 (SSRN 2326253)_
  - 提出 PBO（基于 CSCV 组合对称交叉验证）量化样本内最优配置在样本外跑输中位数的概率，以及 Deflated Sharpe Ratio。QuantBT 的 M10 已实现 PBO/DSR，这两篇是其方法学出处。
- **Do Preregistration and Preanalysis Plans Reduce p-Hacking and Publication Bias?** ([链接](https://www.journals.uchicago.edu/doi/10.1086/730455))
  - _Abel Brodeur, Nikolai Cook, Jonathan Hartley, Anthony Heyes 等 · 2024 · Journal of Political Economy Microeconomics, 2(3)_
  - 对 15,992 个检验统计量的元研究：单纯预注册不显著降低 p-hacking 与发表偏差，但预注册+预分析计划(PAP)同时存在时，两者都有显著下降。对 Agent OS 的含义：让小白'预注册假设'若不绑定一份可执行的预分析计划（先定方法、闸门、停止规则）就是花架子。
- **Bitemporal modeling (valid time vs transaction time)** ([链接](https://en.wikipedia.org/wiki/Bitemporal_modeling))
  - _Richard T. Snodgrass 等（概念奠基）；维基条目为权威综述入口 · 1999/持续更新 · Wikipedia / Snodgrass 'Developing Time-Oriented Database Applications in SQL'_
  - 双时间轴建模的标准定义：valid time(现实有效期)与 transaction time(入库时刻)分离，使数据修订与正常更新可区分、历史可无损重建。这是 PIT 正确性的形式化基础，ArcticDB 即 bitemporal 实现。注：此为成熟标准而非新论文，列此供方法学引用。

### SOTA 方法

- **Bitemporal / Point-in-Time 数据建模 (valid time + transaction time)** `[established]` — 把'现实有效期'与'入库/修订时刻'两条时间轴分开存储，使任意历史日的'当时可得视图'可无损重建，修订与正常更新自动可区分。是防 lookahead / 处理财报重述与 backfill 的形式化根基。
- **内容寻址不可变数据版本 + time-travel (ArcticDB / Delta Lake / Apache Iceberg / lakeFS)** `[established]` — 数据集按内容 hash 寻址、每次 write/append/update 自增版本、可 as_of 读任意快照。ArcticDB（Man Group 开源，bitemporal，对象存储/LMDB 后端，亿级行秒级读）是量化原生选择；Delta/Iceberg 是 lakehouse 主流；2025 年 lakeFS 收购 DVC 整合数据版本控制生态。
- **开放 lineage 标准 OpenLineage + Marquez (含列级 lineage)** `[established]` — run/job/dataset 三实体的开放元数据标准，已进入 Airflow providers、支持 Spark/Flink 批流；Marquez 0.27+ 提供列级 lineage。让'这个结论用了哪些上游数据/特征'可机器追溯，是审计 trail 的工业标准。
- **实验/模型谱系跟踪 (MLflow Tracking + Model Registry + Dataset lineage)** `[established]` — 记录参数/指标/代码版本/数据集指纹与从原始数据到预测的完整 lineage；Model Registry 管 dev→staging→production→archived 生命周期，提供审计 trail。是开源事实标准。QuantBT 的 M12 是其 lite 同构实现。
- **声明式数据质量与数据契约 (Great Expectations 1.0 / dbt tests / Soda)** `[established]` — 用断言(Expectations)声明 schema/取值域/新鲜度/唯一性，Data Docs 生成可读的'数据契约活文档'；data contract 在管线入口校验、失败即阻断。GE 适合深度独立校验，dbt 适合 transformation 内联测试，Soda 偏可观测性。
- **数据可观测性五支柱 (freshness / volume / schema / distribution / lineage)，Monte Carlo 等** `[established]` — 把生产数据像 SRE 监控服务一样监控，自动检测'data downtime'与分布漂移。2024 起加入自治 Observability Agents。对实盘阶段的 live 数据漂移监控直接相关——这是 QuantBT M10 缺的一环。
- **Feast / Tecton feature store 解决 training-serving skew** `[established]` — 集中管理特征定义、提供 PIT-correct 训练视图(as-of join/time-travel)与在线服务，保证研究期与实盘期同一特征逻辑。Tecton 含端到端 transformation+SLA，Feast 偏存储/服务层。
- **feature store 是否必要的争议 / lakehouse 内联化** `[contested]` — 2024-25 出现反思：feature store 并未真正消除 training-serving skew——'每次特征跨系统边界，一致性就从保证变成概率'；一派主张特征在查询时内联计算、训练与服务同源(Databricks Lakehouse 内联化、SQL/批同源)。对中低频量化尤其成立：很多场景不需要独立在线 feature store。
- **策略研究预注册 + 预分析计划 (PAP) + trial-counting / DSR** `[emerging]` — 在看数据前登记假设与方法、记录所有试过的配置数，用 Harvey t>3 / Deflated Sharpe 对多重检验 deflate。2024 元研究证明：预注册必须配 PAP 才真正降低 p-hacking。新兴于量化界但仍非普遍实践。
- **时序存储选型：Parquet+DuckDB 对决 kdb+** `[emerging]` — 2024-25 开放格式(Parquet)+DuckDB/QuestDB/ClickHouse 在性价比上逼近甚至超过 kdb+，使 kdb+ 不再独占；中低频研究用 Parquet+DuckDB+ArcticDB 已足够。kdb+/q 仍在超低延迟 tick 场景占优（但本项目明确排除 HFT）。

### QuantBT 现状

QuantBT 在这一环已达到"研究级可复现基建"的扎实中段，明显领先一般开源回测框架：(1) PIT 与偏差防护：M2 已做 PIT 安全的动态资产池+幸存者偏差处理；universe/resolver、universe/definition、models/walk_forward_v2、purged_cv 都带 PIT/embargo/purged 逻辑；factor 计算普遍 shift(1)。(2) 数据版本不可变：app/backend/app/data_hash/dataset_hash.py(223 行)实现 DatasetManifest 按文件 SHA-256、create_version 落 manifest、verify_version 重算 hash 不匹配即 raise DatasetIntegrityError，并显式注释引用 López de Prado 2018 'same dataset_version + same code → same result'，且补了内容可变漏洞(#7)与 FactorBinding(factor_id, dataset_id, dataset_version)三元组主键(#6)。(3) Lineage/审计：M12 ExperimentStore+RunStore(experiments/store.py, 259 行)记 parent_run_id/forked_from 并提供 lineage() 回溯祖先链；ModelRegistry 管 dev→staging→production→archived；factor_factory/audit.py 与 M11 因子五态机+事件日志构成 audit trail。(4) 数据质量：data_quality.py(333 行)为 GE-lite，配合 dataset_version 不可变+freshness。(5) 验证方法学：M10 PBO(CSCV)+DSR(Bailey-LdP)+Bootstrap Sharpe CI 已落地。整体 763 测试绿，v1.0.0-rc1。缺口集中在：无真正 bitemporal(双时间轴/financial 重述建模)、无 time-travel 查询引擎(自研 manifest 而非 ArcticDB/Delta)、lineage 未对齐 OpenLineage 开放标准且非列级、无 feature store/特征定义研究-实盘同源保证、无 live 数据漂移/可观测性监控、无预注册+PAP+trial-counting 的强制治理闸门。

### 差距

- 无真正 bitemporal 双时间轴：现有 dataset_version 只对齐了'命名+内容 hash'，但没有把 valid time(业绩时点)与 transaction time(入库/修订时点)显式分离。后果：财报重述、数据 vendor backfill、历史更正无法与正常更新区分，A股财报发布滞后/重述这种最常见的 lookahead 来源缺形式化建模。
- 缺 time-travel 查询引擎：自研 SHA-256 manifest 能 verify '数据没被改'，但不能 as_of 高效读任意历史快照做增量 append+历史 correction。ArcticDB(Man Group 开源、bitemporal、对象存储)正是为此而生且 Python 原生，与本项目栈高度契合却未采用。
- Lineage 未对齐开放标准且非列级：RunStore 的 parent/forked_from 是自定义模型，不符合 OpenLineage 的 run/job/dataset schema，无法接 Marquez 可视化，也做不到'这个信号用了哪几列特征'的列级追溯——对'读不懂代码的人靠谱系建立信任'是硬伤。
- 无 feature store / 研究-实盘特征同源保证：M4 因子在回测里算，M9 实盘执行另起一套；没有机制保证'实盘那一刻算出的因子值'与'研究期同一逻辑'一致(training-serving skew)。中低频虽不需在线 feature store，但需要一份被版本化、研究与实盘共用的特征定义+PIT as-of join。
- 无 live 数据漂移/数据可观测性监控：GE-lite 是入库时静态校验，缺生产期 freshness/volume/schema/distribution 五支柱的持续监控与告警(M10 自评也标注'缺 live 漂移监控')。实盘阶段数据 vendor 静默改格式/停更/分布突变将无人察觉。
- 无预注册+PAP+trial-counting 治理闸门：虽有 PBO/DSR 能事后 deflate，但流程上不强制'看数据前登记假设+预分析计划'，也没有自动累计'这条策略路线试过多少配置'喂给 DSR——2024 JPE Micro 证明预注册必须配 PAP 才有效，这正是 Agent OS 治理导轨要补的核心。
- 数据质量是 GE-lite 而非 data-contract 化：缺声明式可读的'数据契约活文档'(GE Data Docs / dbt 风格)，断言与新增数据源对齐靠人工，非技术用户看不到'这份数据被检验了什么'。
- 缺链上/另类数据 PIT 接入(CoinGecko/Glassnode 缺)，且另类数据的 PIT 正确性(发布时点 vs 事件时点)尚无专门处理通道。

### Agent OS 在这一环的角色（服务零代码用户）

这一环是 Agent OS 把"严谨度翻译成信任"最关键的一环，因为非技术用户读不懂代码，只能靠流程导轨与可读凭证来信任 agent。落地形态：(1) 谱系即信任的可视化叙事——把 RunStore lineage 渲染成一张'这个结论从哪来'的因果图：原始数据(哪个源/哪个版本 hash)→哪些因子(经济含义一句话)→标签→模型→信号→回测净值，每个节点配 L1 白话(M19 Glossary 渐进披露)。用经济学者能懂的语言而非工程术语，例如把'dataset_version SHA mismatch'翻译成'你三个月前看到的那份数据后来被供应商悄悄改过，所以那次结论现在不能算数了'。(2) PIT 用'时间机器'隐喻——Agent 主动声明:'我只用了 2019-03-15 当天你真实能看到的数据，包括财报发布滞后；如果某公司当时还没退市我才会把它放进来'，把幸存者偏差/lookahead 这些术语转成'我不会用未来才知道的事骗你'。(3) 预注册作为对话产物而非表单——需求澄清 agent 把模糊念头(M14 SlotFiller)固化成一份'假设登记卡':经济逻辑+待检验命题+成功判据+停止规则+预期指标(M21 模板已有 expected_metrics)，看数据前时间戳锁定;之后所有 trial 自动计数喂给 DSR，agent 用'你这条路线我替你试过 37 种参数，所以这个夏普要打个折才算数'解释多重检验。(4) 数据质量闸门作为可读体检报告——GE-lite 升级成 data contract 后，每次拉数生成一页'数据体检':新鲜度/缺值/分布是否异常，绿/黄/红灯，红灯自动阻断并用白话说明。(5) human-in-the-loop 的审批门——经济判断与风控(go/no-go、上实盘)必须人确认;Agent 出全部工程证据(lineage 完整性、PIT 合规、trial 数、PBO/DSR、数据体检)打包成'决策简报'，人只读结论与红旗。本质:把 SR 11-7'文档详尽到外行也能理解'的监管标准，产品化成非程序员可消费的可复现凭证流。

### 建议

- 在 dataset_hash 之上引入显式 bitemporal 双时间轴：每条记录/每次修订带 valid_time 与 transaction_time，财报等基本面数据按'发布时点+发布滞后+重述链'建模，as-of 读取默认按 transaction_time 截断。可先在 connectors/base 与 datasets 层加 effective_date/knowledge_date 两列，回测引擎统一按 knowledge_date 过滤。这是消除 A股财报 lookahead 与 backfill 偏差的根因修复。  `[→M3 数据 + M2 universe, eff=high, lev=high]`
- 评估用 ArcticDB 替换/补强自研 manifest 作为时序存储层：它 Python 原生、bitemporal、对象存储后端、亿级行秒级读、自带版本号自增与 as_of/snapshot，正是 Man Group 量化数据基建。可先在一个 connector 上做 PoC 对比 verify_version 体验。低风险因为它与 Pandas/Parquet 栈无缝。  `[→M3 数据 + M12 注册表, eff=high, lev=high]`
- 把 RunStore 的 lineage 输出适配 OpenLineage event schema(run/job/dataset)，使其可被 Marquez 这类标准工具消费，并向列级 lineage 演进(记录每个信号用了哪些 factor_id 列)。这是'谱系即信任'可视化的标准底座，且不破坏现有 parent/forked_from 模型，只是加一层 emit。  `[→M12 实验/注册表 + M15 前端, eff=med, lev=high]`
- 在 Agent OS 加'假设预注册+预分析计划'治理闸门：需求澄清 agent 产出时间戳锁定的假设登记卡(经济逻辑/命题/判据/停止规则/expected_metrics)，并自动累计该策略路线的 trial 数喂给已有 DSR。依据 2024 JPE Micro:预注册必须配 PAP 才有效。这是把 M11/M12/M14 拧成统一治理导轨的关键，杠杆极高。  `[→M11 因子生命周期 + M12 注册表 + M14 Agent, eff=med, lev=high]`
- 把 GE-lite 升级为 data-contract 化的声明式校验并生成可读 Data Docs：每个数据源一份'数据契约'(schema/取值域/新鲜度/唯一性断言)，拉数时校验、失败阻断管线、产出一页白话'数据体检报告'(绿黄红灯)。这是把数据质量翻译给非技术用户的载体。  `[→M3 数据质量 + M19 教学/可读化, eff=med, lev=high]`
- 补 live 数据可观测性五支柱(freshness/volume/schema/distribution/lineage)的轻量监控与告警，覆盖 M10 自评缺的 'live 漂移监控'：实盘期持续对比实时数据分布 vs 研究期基线，分布突变/停更/schema 漂移触发 KillSwitch 联动与人工审批。  `[→M10 归因 + M9 风控, eff=med, lev=med]`
- 落一份版本化、研究与实盘共用的特征定义层(轻量 feature spec + PIT as-of join)，保证 M4 因子在回测与 M9 实盘用同一逻辑计算，消除 training-serving skew。注意:中低频不需要独立在线 feature store(参考 2024-25 lakehouse 内联化争议)，做成'特征定义即代码、研究实盘同源'即可，避免过度工程。  `[→M4 特征 + M9 执行, eff=med, lev=med]`
- 为非技术用户做'谱系叙事视图':把一次 run 的完整 lineage 渲染成因果图，每节点配 L1 白话(数据源/版本 hash/因子经济含义/PIT 声明)，并在决策门生成'决策简报'(lineage 完整性+PIT 合规+trial 数+PBO/DSR+数据体检)供人 go/no-go。RunDetailPage 冻结约束下,此为新页面而非改现有概述页。  `[→M15 前端 + M19 教学 + M20 Live Safety, eff=med, lev=high]`

### 对抗式核查裁决 — 总体置信度：**high**

_纠正摘要_: 六篇所引论文全部真实存在且作者/年份/期刊/核心结论核查无误,无虚构:Menkveld 等《Nonstandard Errors》(J. Finance 79(3):2339-2390, 2024, #fincap 164 团队)——可复现性 +1SD 降 NSE 25.0%、同行评议 +1SD 降 33.3%、参与者低估自身脆弱性,全部逐项坐实;Harvey-Liu-Zhu《...and the Cross-Section of Expected Returns》(RFS 29(1):5-68, 2016, t>3)正确;Hou-Xue-Zhang《Replicating Anomalies》(RFS 33(5):2019-2133, 2020, t>1.96 失败 65%、t>2.78 失败 82%)数字精确;Bailey-Borwein-LdP-Zhu 2014《Pseudo-Mathematics...》(Notices AMS 61(5))与 2017《Probability of Backtest Overfitting》(J. Computational Finance 20(4):39-70, CSCV/PBO)均确认——唯一细微注记:Deflated Sharpe Ratio 的形式化出处其实是 Bailey & López de Prado 2014 独立一篇《The Deflated Sharpe Ratio》,论断把 DSR 归到 PBO 2017 篇略有出入,但 PBO/CSCV 归属正确;Bitemporal modeling(valid/transaction time)概念奠基应是 Snodgrass & Ahn 1985 而非论断写的『1999』,Wikipedia 作综述入口可接受。\n\n六条论断核查结果:claim 1(hash=PIT)refuted——代码证实 dataset_hash 仅做完整性/可复现,无 knowledge_date/transaction_time,bitemporal PIT 缺位;claim 2(feature store 消除 skew)refuted——skew 根因在执行边界,dev.to/synapcores 完整支持原批判;claim 3(预注册防 p-hacking)refuted——必须配 PAP;claim 4(选型不重要)nuanced——中低频确可弃 kdb+,但 ArcticDB as_of/bitemporal 对补 PIT 缺口有价值,『不重要』片面;claim 5(测试绿+PBO/DSR=可信)refuted——PBO/DSR 只测单 pipeline 过拟合,无多实现交叉验证暴露 NSE;claim 6(parent_run_id 够审计)nuanced——run 级谱系对内复现够,但缺列级 lineage+OpenLineage,对监管/信任审计不完整。值得注意:这六条全是『自我批判/对抗式』论断(指出 QuantBT 自身的过度宣称),核查恰恰确认了这些批判成立,即原文档作者已诚实标注了自身局限,而非在夸大成果。"

被降权/纠正的论断：
- `refuted` — QuantBT 的 dataset_version SHA-256 manifest 已等价于机构级 PIT 正确性。
  - 纠正：内容 hash = 完整性/可复现(integrity & reproducibility),≠ PIT 正确性,更 ≠ bitemporal。要达机构级 PIT 需引入 knowledge_date/transaction_time 双时间轴并让回测引擎按 knowledge_date 过滤(ArcticDB as_of 即此类实现)。当前 QuantBT 对财报类数据缺 transaction-time 轴,backfill/重述 lookahead 仍可能漏网;此论断属夸大。
- `refuted` — 有了 feature store 就消除 training-serving skew。
  - 纠正：论断把『引入 feature store』与『消除 skew』划等号是夸大且过时。skew 根因是执行边界,不是有没有 store。对 QuantBT 这类中低频项目,更省更稳的是『特征定义即代码 + 研究/实盘同源管线』,不必盲目上重型在线 feature store。
- `refuted` — 让小白预注册假设就能防 p-hacking。
  - 纠正：单纯预注册≈花架子。必须绑定可执行 PAP(先定方法/闸门/停止规则)。需核查 Agent OS 的预注册是否真把方法、显著性闸门(配合 Harvey-Liu-Zhu t>3 / 多重检验 deflation)、停止规则写死成可执行 gate,否则防不住 p-hacking。
- `nuanced` — kdb+/Parquet+DuckDB 选型对本项目不重要。
  - 纠正：应改为:中低频本项目选型不必追 kdb+,但 ArcticDB 的 as_of/bitemporal 能力对补 PIT 缺口有实际价值,需实测本项目数据规模下 ArcticDB as_of/append 性能 vs 自研 verify_version 的真实差距再决定,而非一句『不重要』带过。
- `refuted` — 763 测试绿 + PBO/DSR 已实现 = 结论可信。
  - 纠正：测试绿 + PBO/DSR ≠ 结论可信。需另加机制暴露 NSE:同一假设的多实现/多参数敏感性分析、研究者自由度扫描、稳健性区间。当前 QuantBT 缺此层,论断把『工程正确』误当『结论稳健』。
- `nuanced` — lineage 用 parent_run_id/forked_from 自定义模型已足够审计。
  - 纠正：对内部复现,parent_run_id/forked_from + FactorBinding 够用;但对监管/信任意义上的审计 trail,缺列级 lineage 与 OpenLineage 标准可消费性,不能算『足够审计』。论断对内部够、对外部审计不够,属夸大。

---


## [9] 回测过拟合与验证前沿  · 组 C

**机构级标准** — 机构级证伪协议（institutional falsification protocol）的核心命题是：回测的默认结论应是"该策略无效"，研究流程的职责是在严格的反过拟合护栏下"未能证伪"，而非"找到有效"。世界顶级量化机构（如 ADIA Lab、AQR、Two Sigma 风格）的共识标准包含七要素：(1) 试验计数（number of trials N）必须全程登记且不可瞒报——López de Prado 称隐瞒试验数等同于学术欺诈；(2) 假设先行、模型先全规格化（"never backtest until your model has been fully specified"），杜绝看到结果再调参（data dredging）；(3) 用多重检验校正后的显著性门槛而非裸 t>2，即报告 Deflated Sharpe Ratio（DSR，对 N 次试验、SR 估计方差、偏度峰度、样本长度同时校正）与 Probabilistic Sharpe Ratio（PSR）；(4) 报告 Probability of Backtest Overfitting（PBO，由 CSCV 组合对称交叉验证估计 IS 最优策略 OOS 落入中位数以下的概率）；(5) 用 Combinatorial Purged Cross-Validation（CPCV，含 purging+embargo）产生 OOS 的*分布*而非单条路径，单路径 walk-forward 被证有高时间方差与弱平稳性、易假发现；(6) Minimum Backtest Length / Minimum Track Record Length 闸门——给定 N 与目标 SR，样本长度不足则直接拒绝；(7) 三类回测互证（walk-forward / resampling / Monte Carlo）+ 因果先验（causal factor）以排除"统计有效但因果错误"的伪因子。落到治理上，这套方法学必须嵌入一个"预注册→独立验证→审批门→资本配置→实盘漂移监控→退役"的治理闭环，且 N、随机种子、数据版本、purge/embargo 参数全部可复现、可审计。"严谨"在机构里等于"可被他人重跑出同一拒绝/通过决定"。


### 关键论文 / 权威实践

- **Pseudo-Mathematics and Financial Charlatanism: The Effects of Backtest Overfitting on Out-of-Sample Performance** ([链接](https://www.ams.org/notices/201405/rnoti-p458.pdf))
  - _David H. Bailey, Jonathan M. Borwein, Marcos López de Prado, Qiji Jim Zhu · 2014 · Notices of the American Mathematical Society (Vol 61, No 5)_
  - 证明只需回测少量配置即可获得高 SR 假阳性；引入 Minimum Backtest Length（MinBTL）概念——给定 N 次独立试验，需要的最短样本长度随 N 增长。奠定整条反过拟合方法学的理论基石，并把'瞒报试验数'定性为欺诈。
- **The Probability of Backtest Overfitting (PBO via CSCV)** ([链接](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2326253))
  - _David H. Bailey, Jonathan M. Borwein, Marcos López de Prado, Qiji Jim Zhu · 2015 · Journal of Computational Finance; SSRN 2326253_
  - 提出 Combinatorially-Symmetric Cross-Validation（CSCV）作为模型无关、非参数地估计 PBO 的方法：把样本分 S 段，枚举 C(S,S/2) 训练/测试组合，PBO = IS 最优策略在 OOS 排名落入中位数以下的频率（logit 形式 λ）。
- **The Deflated Sharpe Ratio: Correcting for Selection Bias, Backtest Overfitting, and Non-Normality** ([链接](https://www.davidhbailey.com/dhbpapers/deflated-sharpe.pdf))
  - _David H. Bailey, Marcos López de Prado · 2014 · Journal of Portfolio Management (Vol 40, No 5)_
  - DSR = PSR 但以 False Strategy Theorem 估出的期望最大 SR（SR0）替代裸阈值。关键：SR0 = sqrt(V[SR_hat]) × ((1−γ)Φ⁻¹[1−1/N] + γΦ⁻¹[1−1/(Ne)])，即 SR0 依赖*跨试验 SR 的横截面方差*，并对偏度 γ3、峰度 γ4、样本长 T 校正。
- **The False Strategy Theorem: A Financial Application of Experimental Mathematics** ([链接](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=3221798))
  - _Marcos López de Prado, David H. Bailey · 2018 · SSRN 3221798_
  - 形式化证明：N 个零真实技能策略中，最大观测 SR 随 N 单调上升且右无界——'试验够多总能凑出漂亮回测'。为 DSR 中 SR0 的估计提供严格依据。
- **Backtest Overfitting in the Machine Learning Era: A Comparison of Out-of-Sample Testing Methods in a Synthetic Controlled Environment** ([链接](https://www.sciencedirect.com/science/article/abs/pii/S0950705124011110))
  - _Hamid R. Arian, Daniel Norouzi M., Luis A. Seco · 2024 · Knowledge-Based Systems (Vol 305); SSRN 4778909 / 4686376_
  - 在合成可控环境（Heston 随机波动率、Merton 跳跃扩散、drift-burst、regime-switching）中对比 K-Fold/Purged K-Fold/Walk-Forward/CPCV，以 PBO 与 DSR 检验统计量为指标，结论：CPCV 显著最优、walk-forward 最易假发现；提出 Bagged CPCV / Adaptive CPCV 变体。是 2021-2026 期最权威的对照实证。
- **… and the Cross-Section of Expected Returns / Lucky Factors** ([链接](https://www.nber.org/system/files/working_papers/w20592/w20592.pdf))
  - _Campbell R. Harvey, Yan Liu, Heqing Zhu (2016); Harvey & Liu (2021) · 2016 / 2021 · Review of Financial Studies (2016); Journal of Financial Economics (2021)_
  - 对'因子动物园'施加多重检验框架：裸 t>2 不再可用，新因子门槛应抬到约 t>3；2021 Lucky Factors 引入 bootstrap 多因子正交化检验。与 López de Prado 路线互补，是学术界对应的反数据窥探共识。
- **The Three Types of Backtests** ([链接](https://www.adialab.ae/research-series/the-three-types-of-backtests))
  - _Jacques Joubert, Dragan Sestovic, Illya Barziy, Walter Distaso, Marcos López de Prado · 2024 · SSRN 4897573 (ADIA Lab Research Series)_
  - 把回测方法归为三类——walk-forward、resampling（jackknife/CV/bootstrap/CPCV）、Monte Carlo——并主张三类互证：单一方法不足以证伪，机构应同时跑并交叉检验。
- **A Protocol for Causal Factor Investing / The Case for Causal Factor Investing** ([链接](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=4774522))
  - _Marcos López de Prado, Vincent Zoonekynd, Alex Lipton · 2024-2025 · ADIA Lab; SSRN 4774522; Quantitative Finance 2024_
  - 指出绝大多数因子论文做关联性而非因果声明，缺因果图则因 backtest overfitting 与误设定而很可能为假；提出以因果推断（DAG/do-演算）替代相关性挖掘的研究协议，是2025前沿但仍属争议性方向。
- **AlgoXpert Alpha Research Framework: A Rigorous IS–WFA–OOS Protocol for Mitigating Overfitting** ([链接](https://arxiv.org/abs/2603.09219))
  - _The Anh Pham et al. · 2026 · arXiv:2603.09219_
  - 把反过拟合落成可操作的三阶段流水线协议：IS 选稳定参数区（非单点最优）→ WFA 滚动窗+purge gap+多数通过与灾难性否决规则 → OOS 严格参数锁定零调参；外加 cliff veto/spread-leverage guard/熔断 kill-switch 的纵深防御。代表把'方法学'工程化为'流程导轨'的最新尝试。

### SOTA 方法

- **CSCV → PBO（组合对称交叉验证估过拟合概率）** `[established]` — 把回测样本分 S 段，枚举 C(S,S/2) 训练/测试组合，统计 IS 最优策略 OOS 排名落入中位数以下的频率，给出 PBO∈[0,1] 与 logit 退化分布。模型无关、非参数。是衡量'策略选择程序'可靠性的标准件。
- **Deflated Sharpe Ratio (DSR) + PSR + Minimum Track Record Length** `[established]` — 对 N 次试验下期望最大 SR（含跨试验 SR 方差）、偏度峰度、样本长同时校正后的显著性概率；MinTRL 给出'要达到 95% 置信至少需多长样本'。报告 DSR 而非裸 SR 已是机构发表与内部审批的事实标准。
- **Purged k-fold + Embargo + Walk-Forward** `[established]` — purging 剔除标签区间与测试期重叠的训练样本，embargo 在测试期前后再留缓冲，消除时间序列标签泄漏。walk-forward（anchored/rolling）仍是工业界'最贴近真实交易'的单路径验证。
- **Combinatorial Purged Cross-Validation (CPCV)** `[established]` — 在 purged CV 基础上枚举组合，产生 OOS 业绩的*分布*（多条路径）而非单条；2024 合成环境对照中 PBO 最低、DSR 最高。已成为 ML 量化研究的推荐默认，但需 ≥100 组合路径否则分布不稳。
- **White Reality Check / Hansen SPA / Romano-Wolf 逐步多重检验** `[established]` — 用 stationary bootstrap 在'最优规则无超额'的零假设下检验，控制 family-wise error。Hansen SPA 比 White RC 更不保守（剔除极差模型）；Romano-Wolf/SPA-stepwise 能识别多于一条的好规则。经济计量学界对抗数据窥探的经典共识。
- **多重检验校正：Bonferroni/Holm (FWER) 与 Benjamini-Hochberg-Yekutieli (FDR)；Harvey-Liu t>3 门槛** `[established]` — 把'裸 t>2'抬到考虑试验数后的门槛。FWER 控任一假阳，FDR 控假阳占比。Harvey-Liu 给因子门槛约 t>3。与 DSR 路线互补——DSR 处理 SR 选择偏差，FDR/FWER 处理 p 值族。
- **三类回测互证（walk-forward + resampling + Monte Carlo）** `[emerging]` — ADIA Lab 主张单一回测方法不足以证伪，应同时跑滚动、重采样、合成路径三类并交叉检验稳健性。Tactical Investment Algorithms 进一步主张以 Monte Carlo 合成历史替代单条真实历史。
- **Bagged CPCV / Adaptive CPCV** `[emerging]` — 2024 论文提出的 CPCV 集成与按市场状态自适应的变体，进一步降 PBO。提升明显但尚缺独立复现与跨资产验证。
- **因果因子投资协议（causal factor / DAG / do-演算替代相关性挖掘）** `[contested]` — López de Prado-Zoonekynd 2024-2025 主张：无因果图的因子很可能是过拟合伪因子，应以因果推断为证伪前提。方向性强但'如何在中低频实证中可靠识别因果图'仍有争议，工具链不成熟。
- **预注册 / hypothesis pre-registration（量化版临床试验登记）** `[emerging]` — 借鉴临床医学：研究前登记假设、N 上限、停止规则与评估指标，事后不可篡改，以治理手段而非纯统计手段遏制 p-hacking。学术界呼声渐高，量化业界尚无统一标准实现。

### 最佳实践

- 默认假设策略无效，流程职责是'未能证伪'而非'证明有效'——反向举证。
- 全程登记 number-of-trials N 并不可瞒报；瞒报试验数等同学术欺诈（López de Prado）。
- 模型先全规格化再回测（never backtest until your model has been fully specified），禁止看结果再调参。
- 报告 Deflated Sharpe Ratio（含 N、SR 方差、偏度峰度、样本长校正）而非裸 SR/裸 t>2。
- 报告 PBO（CSCV）衡量策略选择程序的过拟合概率，PBO 高（如 >50%）应否决。
- 用 CPCV 产生 OOS 业绩分布（多路径）而非单条 walk-forward；purge+embargo 消除标签泄漏。
- 设 Minimum Backtest Length / MinTRL 硬闸门：样本长度撑不起试验数即拒绝。
- 三类回测互证（walk-forward + resampling + Monte Carlo），单一方法不足以证伪。
- 多重规则评估时套用 White RC / Hansen SPA / Romano-Wolf / BHY-FDR 控制 family-wise / 假发现率。
- 反过拟合贯穿生命周期：上线后持续重算实盘 vs 回测 SR/PSR/DSR 衰减并触发降级/退役。
- 向非技术用户用经济学语言+类比翻译结论（'掷47次硬币总有连正面'），红黄绿灯+渐进披露+go/no-go 留给人。
- 前置因果先验：优先有因果机制的假设，警惕'统计有效但因果错误'的伪因子。

### QuantBT 现状

QuantBT 在这一环已有可观的散件基础但未拧成协议闸门。已实现：(1) M10 eval/pbo.py 的 CSCV→PBO（含 logit λ 形式、偶数 S 校验、全枚举/采样、min_n_strategies 与 strict 配置守卫，是较扎实的实现）；(2) M10 eval/dsr.py 的 DSR + PSR 雏形（对偏度/峰度/样本长校正，但 _expected_max_sr 用 sqrt(2lnN) 近似、*遗漏跨试验 SR 横截面方差项*，存在方法学正确性缺陷）；(3) M10 还有 Bootstrap Sharpe CI、Brinson 三层归因；(4) M6 models/purged_cv.py 的 Purged k-fold + Embargo（含 t1 标签结束时间 purge，符合 López de Prado 2018 §7.4.1）+ 单路径 walk-forward（anchored/rolling）。缺口侧：无 CPCV（只有 purged k-fold，缺组合多路径 OOS 分布），无 Minimum Backtest Length 闸门，无任何多重检验校正（White RC/Hansen SPA/Romano-Wolf/Bonferroni/BHY 均无），N（试验数）靠调用方手填且未与 M12 实验注册表自动累加，无预注册机制，无 live 漂移监控（M10 自评已承认），三类回测仅覆盖 walk-forward 与部分 resampling、无 Monte Carlo 合成路径，且这些散件未被统一'证伪协议引擎'串成一次不可篡改、可审计、出 go/no-go 的验证报告。整体处于'有 PBO/DSR/purged-CV 三个零件、但 DSR 有 bug、缺 CPCV/MinBTL/多重检验/预注册/live 漂移、且未编排成贯穿生命周期的治理闸门'的状态。

### 差距

- DSR 实现有方法学缺陷：app/backend/app/eval/dsr.py 的 _expected_max_sr(n) 用 sqrt(2*ln(N)) − γ/sqrt(2*ln(N)) 近似期望最大 SR，但*遗漏了 False Strategy Theorem 必须乘的跨试验 SR 横截面标准差 sqrt(V[SR_hat])*。这使 SR0 与试验间 SR 离散度脱钩——当策略族 SR 方差大时会严重低估应扣减量、放行假阳。这是正确性级别的 bug，非风格问题。
- PBO/CSCV 已实现（pbo.py，含 logit λ、偶数 S、全枚举/采样、strict 校验），但与 DSR、purged CV 是*孤立散件*：没有一个统一的'证伪协议引擎'把 N（试验计数）、PBO、DSR、MinBTL、purge/embargo 参数串成一次不可篡改的验证报告。当前 N（n_trials）靠调用方手填，没有从实验/注册表（M12）自动累加真实试验数，等于把最关键的 number-of-trials 留给用户自报，违背 López de Prado 的核心戒律。
- 缺 CPCV（组合净化交叉验证）：现有 purged_cv.py 只有 purged k-fold + 单路径 walk-forward，没有枚举组合产生 OOS *分布*的 CPCV。2024 合成环境对照已证 walk-forward 最易假发现、CPCV 最优；现状停在被证明次优的方法上。
- 缺 Minimum Backtest Length / Minimum Track Record Length 闸门：没有'给定 N 与目标 SR，样本不足即拒绝'的硬门。用户可以拿 6 个月数据 + 试 50 个配置就声称发现 alpha，系统不拦。
- 缺多重检验/数据窥探校正族：没有 White Reality Check、Hansen SPA、Romano-Wolf、Bonferroni/Holm/BHY 任何一种。当用户在一个 universe 上跑几十条规则时，无 family-wise/FDR 校正，t/SR 的显著性被系统性高估。
- 缺预注册（pre-registration）与试验计数审计：M12 有 lineage（parent/forked_from），但没有'研究前登记假设+N上限+评估指标、事后锁定不可改'的预注册机制，也没有把每次 backtest run 自动计入 N 的审计账本。治理闭环里'假设登记→审批门'这两环在反过拟合维度是空的。
- 缺 live 漂移监控接证伪结论：M10 自评'缺 live 漂移监控'。证伪协议不止上线前——应持续比对实盘 SR 与回测 SR 的衰减（PSR 退化、DSR 重算），触发 M11 因子生命周期降级。当前过拟合检测是一次性的，不是贯穿生命周期的。
- 缺把'三类回测互证'制度化：只有 walk-forward 与（部分）resampling，没有 Monte Carlo 合成路径回测，也没有要求三类一致才放行的审批规则。

### Agent OS 在这一环的角色（服务零代码用户）

这一环是整个 Agent OS '流程即信任'最吃重的地方——非程序员读不懂 CPCV 代码，只能靠'看不见但跑过的闸门'相信结论。Agent OS 应这样让小白/经济学者走过去：(1) 需求澄清 agent 在登记假设时就强制预注册——用对话问清'你预期的经济机制是什么/你打算试几个版本'，把 number-of-trials 的上限当作一个可被理解的'诚实承诺'写进档案，事后 agent 自动累加真实试验数并对照，超额即在审批门亮红。对经济学者这就翻译成'就像临床试验要先登记终点指标，不能跑完再挑好看的说'。(2) 工程全自主：agent 自动选 CPCV+purge+embargo、自动算 PBO/DSR/MinBTL，用户一行代码不写。(3) 严谨度翻译成经济学语言而非统计黑话——不要只甩 'DSR=0.31'，而要说'你这条策略，考虑到你一共试了 47 个版本，它看起来好很可能是运气：在统计上它的真实超额收益不显著（约 70% 概率是过拟合）。打个比方，掷 47 次硬币总有一次连出正面，不代表那枚硬币有问题。' PBO 翻译成'把历史切成多段反复考试，你这套挑选方法有 X% 的概率挑出的是考前背了答案、考后就垮的学生'。(4) 渐进披露：小白只看红/黄/绿灯+一句人话结论；经济学者点开看 PBO/DSR/MinBTL 数值与图；会写代码的 quant 再下钻看每条 CPCV 路径与种子。(5) human-in-the-loop 卡在 go/no-go：agent 给出'我建议否决，因为 PBO 高于 50%'，但放行与否是人的经济判断，agent 不替人按下资本配置按钮。M19 教学 agent + glossary 在此处提供 L1-L4 释义，M14 reAct + 工具负责自动编排验证 DAG，M18 IDE 沙箱让进阶用户复核。

### 建议

- 修复 DSR 正确性 bug：在 dsr.py 增加按 False Strategy Theorem 的 SR0 = sqrt(V[SR_hat]) × ((1−γ)Φ⁻¹[1−1/N] + γΦ⁻¹[1−1/(Ne)]) 实现，输入需要跨试验 SR 的横截面方差（从同一研究批次的多条策略 SR 估）。保留旧 sqrt(2lnN) 仅作'方差未知时的退化近似'并显式标注。加单测对照 López de Prado 论文数值例。  `[→M10 (eval/dsr.py), eff=low, lev=high]`
- 把 N（number of trials）从'调用方手填'改为'从实验注册表 M12 自动累加'：每次 backtest/训练 run 计入同一研究分支的试验计数，DSR/MinBTL 自动取真实 N。这是 López de Prado 核心戒律的工程落地，杜绝瞒报试验数。  `[→M12 + M10, eff=med, lev=high]`
- 新建统一'证伪协议引擎'：一次调用产出不可篡改的验证报告——N、PBO(CSCV)、DSR、PSR、MinTRL、purge/embargo 参数、随机种子、数据版本 hash 全部固化，输出红/黄/绿 go-no-go 与人话摘要。把现有 pbo.py/dsr.py/purged_cv.py 从散件拧成闸门。  `[→M10 + M13 (DAG 编排) + M12, eff=med, lev=high]`
- 实现 CPCV（组合净化交叉验证）：在 purged_cv.py 基础上枚举 C(S,S/2) 组合产生多条 OOS 路径，输出业绩分布与 10th-percentile 指标（要求 ≥100 路径否则告警不稳）。这是 2024 合成环境对照证明的当前最优件，替代单路径 walk-forward 作默认。  `[→M6 (models/purged_cv.py) + M10, eff=med, lev=high]`
- 加 Minimum Backtest Length / Minimum Track Record Length 硬闸门：给定 N 与观测 SR，若样本长度 < MinBTL 则审批门直接拒绝并给人话解释'你的数据太短，撑不起你试过的版本数'。  `[→M10 + M20 (Live Ladder 审批门), eff=low, lev=high]`
- 加多重检验/数据窥探校正：至少实现 Romano-Wolf stepwise 与 Hansen SPA（stationary bootstrap），辅以 BHY (FDR) 简单封装；当一次研究在 universe 上评估多条规则时自动套用并报告校正后显著性。  `[→M10 + M4 (因子 IC 评估处), eff=high, lev=med]`
- 建预注册机制：需求澄清 agent 在 M1 StrategyGoal 登记时写入'假设+N上限+评估指标+停止规则'，事后锁定不可改，审批门对照实际 N 与登记上限。把'假设登记→审批门'治理两环补实。  `[→M1 + M12 + M14 (需求澄清 agent), eff=med, lev=high]`
- 把过拟合结论翻译层做进前端：红黄绿灯 + 经济学语言摘要（'你试了 N 次，这很可能是运气'类比），L1-L4 渐进披露下钻到 PBO/DSR 数值与 CPCV 路径图，复用 M19 glossary/coach。go/no-go 必须 human-in-the-loop，agent 只给建议不替人按资本配置。  `[→M15 + M19 + M20, eff=med, lev=high]`
- 把证伪协议延伸到 live：实盘运行中持续重算实盘 SR/PSR/DSR 与回测对照，检测业绩衰减并触发 M11 因子生命周期降级（WARNING/RETIRED）。让反过拟合贯穿全生命周期而非一次性。  `[→M11 + M10 + M9 (RiskMonitor), eff=high, lev=med]`

### 对抗式核查裁决 — 总体置信度：**high**

_纠正摘要_: 八篇所引论文全部真实存在，核心结论描述大体准确，但有三处引用瑕疵需纠正：(1) Harvey-Liu 条目把 2016 NBER w20592（Harvey/Liu/Heqing Zhu，t>3）与独立的 Lucky Factors（Harvey & Liu 2021）混并在同一链接下；(2) 因果因子条目张冠李戴：『A Protocol for Causal Factor Investing』(ADIA Lab/即将刊 JPM 的 Correcting the Factor Mirage) 与 SSRN 4774522『The Case for Causal Factor Investing』是两篇不同文献，DOI 配错标题；(3) PBO/CSCV 论文正式发表为 Journal of Computational Finance 20(4) 2017，引用标『2015』是工作稿与刊发年混淆。\n\n六条论断中：claim 1（DSR 缺 sqrt(V[SR]) 项）方向正确但论断把误差钉死为单向『系统性低估』属夸大——代码实为把 V[SR_hat] 硬编码为 1 的标度 bug，误差符号取决于真实横截面 SR 方差，且 dsr.py docstring 公式(line 8)与实现(line 38)自相矛盾，故标 confirmed 但附量级修正。claim 4（PBO 对单/少策略无意义、strict=False 静默返 NaN 致前端假阳）经源码核对 confirmed。claim 6（自动 N 有计数旁路风险）经 main.py IDE 路径用户自报指标的事实 + 2014 MinBTL 理论双重佐证 confirmed，建议自动 N 仅作下界并告警。claim 2（CPCV 单篇结论）与 claim 3（t>3 机械套用）标 nuanced：前者为单篇高质量模拟、无独立复现且合成 DGP 不覆盖离散非平稳，不应当铁律；后者门槛本应随有效试验数 N 浮动而非写死。claim 5（因果因子当 contested）的框架判断 confirmed——学界对强制 DAG 识别有明确 pushback，工具远未成熟到可作放行硬门。无虚构论文，但发现多处引用合并/张冠李戴与年份偏差。

被降权/纠正的论断：
- `nuanced` — 『2024 合成环境对照证明 CPCV 显著优于 walk-forward、walk-forward 最易假发现』来自 Arian-Norouzi-Seco 单篇 (Knowledge-Based Systems 2024)，是否被独立复现？其合成环境是否覆盖中低频股票/加密真实非平稳性？单篇不应当铁律。
  - 纠正：应把它当作『单篇高质量模拟证据，非独立复现的铁律』。其合成 DGP（连续时间随机过程）并不直接覆盖中低频股票/加密的离散、流动性断裂、政策冲击式非平稳；CPCV 在这些场景的优势未经实证证伪。把『CPCV 显著最优』当作普适放行标准属于过度外推；恰当用法是与 walk-forward + Monte Carlo 三类互证（见 Joubert 2024）。
- `nuanced` — 『裸 t>2 应抬到 t>3』(Harvey-Liu 2016) 这一门槛是否适用于 QuantBT 的中低频、单/少策略场景？机械套 t>3 可能误杀真 alpha；门槛应随有效试验数 N 而非固定。
  - 纠正：论断方向正确：t>3 是『针对约数百因子动物园』的多重检验产物，机械套到单/少策略会过度保守。Harvey-Liu 本人的框架就是『门槛随有效试验数浮动』，所以正确做法不是固定 3.0 也不是固定 2.0，而是按实际 N 算 Bonferroni/BHY 校正后的临界值（或等价地用 DSR）。引用里把作者写成『Harvey, Liu, Heqing Zhu (2016); Harvey & Liu (2021) Lucky Factors』把两篇不同论文混在一条 NBER w20592 链接下——w20592 只对应 2016 那篇；Lucky Factors (Harvey & Liu 2021, RFS) 是独立论文、不同链接。属轻微合并引用错误。

---


## [10] 因子动物园/复制危机/拥挤/衰减  · 组 C

**机构级标准** — 机构级标准是把"一个新因子是不是真的"当成一个多重检验问题，而不是单次 t-test，并且把因子从发现到退役管成一条有闸门、有谱系、有问责的生命周期。具体到顶级量化机构/学术共识，这一环应做到：(1) 发现侧多重检验校正——单因子 t>2.0 无效，机构按 Harvey-Liu-Zhu 用 t≈3.0 起步的更高门槛，或用 FDR 控制 / 双 bootstrap（Harvey-Liu Lucky Factors）/ Feng-Giglio-Xiu 的"增量信息"检验来判断新因子相对现有因子族是否冗余；(2) 复制与稳健性——任何上线因子必须能跨样本、跨地域(JKP 93 国)、跨资产被独立复制，并报告对 microcap/value-weight/NYSE 断点等"研究者自由度"的敏感性（Hou-Xue-Zhang；forking-paths/nonstandard-errors）；(3) 折扣与去通胀——对回测 Sharpe 做 Deflated Sharpe Ratio / PBO 去除选择偏差，对样本内收益按 McLean-Pontiff 经验做 OOS(-26%)/post-publication(-58%) 折扣，并用经验贝叶斯收缩样本内 alpha；(4) 预注册与协议——遵循 Arnott-Harvey-Markowitz 七点回测协议，研究假设、数据、检验数 N 事前登记，事后报告全部试验数而非只报赢家；(5) 经济先验优先——要求因子有事前经济学/风险溢价或行为偏误的解释，而非纯数据挖掘；(6) 上线后监控——持续跟踪 IC/IR 衰减、拥挤(crowding，valuation spread / 短仓 / 持仓重叠 / ETF 资金)、容量与拥挤崩盘风险，按既定阈值降级/退役并留审计日志(模型风险问责，类 SR 11-7 治理)。


### 关键论文 / 权威实践

- **…and the Cross-Section of Expected Returns** ([链接](https://academic.oup.com/rfs/article/29/1/5/1843824))
  - _Campbell R. Harvey, Yan Liu, Heqing (Caroline) Zhu · 2016 · Review of Financial Studies 29(1):5-68 (NBER w20592)_
  - 奠基性的'因子动物园'多重检验论文：盘点300+已发表因子，提出考虑相关性与发表偏误的多重检验框架，论证新因子的 t-ratio 门槛应≈3.0 而非2.0。是这一环的标准起点。
- **Replicating Anomalies** ([链接](https://academic.oup.com/rfs/article-abstract/33/5/2019/5236964))
  - _Kewei Hou, Chen Xue, Lu Zhang · 2020 · Review of Financial Studies 33(5):2019-2133 (NBER w23394)_
  - 复制危机最悲观的一极：用统一的 NYSE 断点+市值加权重做447-452个异象，64-65% 在单检验 t=1.96 下不显著，按多检验 t=2.78 失败率升至约82%；交易摩擦/流动性类几乎全军覆没。论证'微盘+等权'是 p-hacking 主要来源。
- **Is There a Replication Crisis in Finance?** ([链接](https://onlinelibrary.wiley.com/doi/full/10.1111/jofi.13249))
  - _Theis Ingerslev Jensen, Bryan T. Kelly, Lasse Heje Pedersen · 2023 · Journal of Finance 78(5) (NBER w28432)_
  - 乐观一极与方法学前沿：贝叶斯分层模型把相关因子聚成13个主题，跨因子共享信息做收缩；结论是多数因子可复制、可聚为13主题、在93国样本外有效，且'因子越多证据越强而非越弱'。配套开源 Global Factor Data(JKPfactors.com / bkelly-lab)。直接反驳 HXZ。
- **Does Academic Research Destroy Stock Return Predictability?** ([链接](https://onlinelibrary.wiley.com/doi/abs/10.1111/jofi.12365))
  - _R. David McLean, Jeffrey Pontiff · 2016 · Journal of Finance 71(1):5-32_
  - post-publication decay 的经典量化：97个预测变量样本外收益降26%、发表后降58%；差额(约32%)归因于'套利者读论文后交易'。这两个折扣是给样本内 alpha 打折的行业基准数字。
- **Open Source Cross-Sectional Asset Pricing** ([链接](https://www.nowpublishers.com/article/Details/CFR-0112))
  - _Andrew Y. Chen, Tom Zimmermann · 2022 · Critical Finance Review 11(2):207-264_
  - 开源复制基础设施：公开重建~319个横截面预测变量的数据与代码(openassetpricing.com)；对原文清晰显著的161个,98%的多空组合 t>1.96。为'可复现'提供了可下载的真值集与基准。
- **Publication Bias in Asset Pricing Research** ([链接](https://arxiv.org/abs/2209.13623))
  - _Andrew Y. Chen, Tom Zimmermann · 2022/2025 · arXiv 2209.13623 / Oxford Research Encyclopedia_
  - 用经验贝叶斯把四条程式化事实(几乎都能复制/样本外持续/t远大于2/因子弱相关)转成定量发表偏误校正：发表偏误只解释样本内均值的10-15%，FDR<10%。论证发表偏误存在但非主导。
- **Taming the Factor Zoo: A Test of New Factors** ([链接](https://onlinelibrary.wiley.com/doi/10.1111/jofi.12883))
  - _Guanhao Feng, Stefano Giglio, Dacheng Xiu · 2020 · Journal of Finance 75(3):1327-1370_
  - 用双重选择 LASSO 在高维现有因子集之上检验新因子的'增量'贡献，显式处理模型选择误差；结论多数新因子相对现有因子冗余,少数(如盈利能力)有真增量。是判断'新因子是不是旧因子重新包装'的 SOTA 工具。
- **False (and Missed) Discoveries in Financial Economics** ([链接](https://onlinelibrary.wiley.com/doi/abs/10.1111/jofi.12951))
  - _Campbell R. Harvey, Yan Liu · 2020 · Journal of Finance 75(5):2503-2553_
  - 用双 bootstrap 同时校准 Type I/II 错误,给出与目标 FDR(如5%)对应的 t 门槛；强调不仅有假发现也有'漏发现'。提供可直接落地的 FDR 控制法。
- **A Backtesting Protocol in the Era of Machine Learning** ([链接](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=3275654))
  - _Robert D. Arnott, Campbell R. Harvey, Harry Markowitz · 2019 · Journal of Financial Data Science 1(1):64-74_
  - 七点回测治理协议(经济先验在先、严控多重检验/数据窥探、样本外、交叉验证、警惕复杂度与研究者激励等)。是把方法学翻译成可执行流程闸门的权威实践蓝本。
- **The Deflated Sharpe Ratio / The Probability of Backtest Overfitting** ([链接](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2460551))
  - _David H. Bailey, Marcos López de Prado (PBO 加 Borwein, Zhu) · 2014/2015 · Journal of Portfolio Management / Journal of Computational Finance_
  - DSR 对选择偏误+非正态+样本长度去通胀 Sharpe；CSCV→PBO 量化'选中策略样本外跑输中位数'的概率。QuantBT 已实现，是回测过拟合控制的事实标准。
- **Forking Paths in Financial Economics / Nonstandard Errors** ([链接](https://arxiv.org/abs/2401.08606))
  - _Guillaume Coqueret (2024) / Albert Menkveld et al. (2024) · 2024 · arXiv 2401.08606 / Journal of Finance 79(3)_
  - 量化'研究者自由度':每多一个分析路径自由度,t 统计区间至少扩30%;用 paths 而非 bootstrap 时5%显著门槛飙到8.2。Menkveld 让164团队做同一题,显示结果离散度被严重低估。论证非标准误差与预注册的必要性。
- **High-Throughput Asset Pricing** ([链接](https://arxiv.org/pdf/2311.10685))
  - _Andrew Y. Chen, Mihail Velikov 等 · 2023-2025 · arXiv 2311.10685_
  - emerging:对数万条数据挖掘出的预测变量做经验贝叶斯收缩与 FDR 控制的'高通量'流水线,展示大规模批量评估因子时如何系统性去通胀与控假发现。

### SOTA 方法

- **多重检验 t≈3.0 门槛 (Harvey-Liu-Zhu)** `[established]` — 新因子起评门槛从 t>2.0 提到 t≈3.0,考虑因子相关与发表偏误。已是学术与机构共识的最低限。
- **Deflated Sharpe Ratio + CSCV/PBO (Bailey-López de Prado)** `[established]` — 对回测 Sharpe 按试验数/非正态/样本长度去通胀,并量化过拟合概率。回测过拟合控制的事实标准;QuantBT 已实现。
- **贝叶斯分层收缩 / 跨因子信息共享 (Jensen-Kelly-Pedersen)** `[emerging]` — 把相关因子聚成主题、用经验贝叶斯把噪声大的单因子 alpha 向主题均值收缩,使'因子多'成为证据增益。横截面因子评估的当前最前沿且已开源(Global Factor Data)。
- **增量信息/双重选择 LASSO 因子检验 (Feng-Giglio-Xiu)** `[established]` — 在高维现有因子之上检验新因子的边际 SDF 贡献,识别'旧因子重新包装'。判断因子冗余的 SOTA。
- **FDR 控制 / 双 bootstrap (Harvey-Liu False&Missed; 经验贝叶斯 FDR, Chen High-Throughput)** `[emerging]` — 以目标假发现率反推 t 门槛,适合一次评估成百上千因子的批量场景;经验贝叶斯版可处理上万条。
- **post-publication / OOS 收益折扣 (McLean-Pontiff)** `[established]` — 用 -26%(OOS)/-58%(post-pub) 这类经验折扣对样本内 alpha 打折后再做资本配置。已是从业常识。
- **因子拥挤度量 (MSCI Integrated Crowding; valuation spread / 短仓 / 持仓重叠 / 配对相关 / ETF 流)** `[emerging]` — 用相对估值差、短仓、成对相关、资金流等多维代理衡量某因子被多少资本追逐。MSCI/AQR 均有产品化框架,但绝对资本量不可观测,度量仍是相对、嘈杂。
- **预注册 + 七点回测协议 (Arnott-Harvey-Markowitz) + 非标准误差/forking-paths 报告** `[emerging]` — 事前登记假设与检验数、事后报告全部试验与分析路径离散度。流程治理层面的 SOTA,但在业界落地率仍低。
- **因子拥挤可交易性 / 拥挤预测崩盘而非收益** `[contested]` — 近期(2025,arXiv 2512.11913,该 preprint 已被撤回大修)主张拥挤更多预测尾部崩盘风险而非低收益,且'机械型'因子(动量/反转)比'判断型'(价值/质量)衰减更快。方向有趣但证据不足、争议大。

### 差距

- 发现侧只有单因子 IC/RankIC/IC-IR(M4)与生命周期单 t>3 阈值(M11),没有'相对现有因子族的增量检验'(Feng-Giglio-Xiu)、没有 FDR 控制 / 双 bootstrap(Harvey-Liu),也没有跨因子贝叶斯收缩(JKP)。新因子目前是孤立评估,无法回答'它是不是旧因子的重新包装'。
- 回测侧有 PBO+DSR+Bootstrap Sharpe CI(M10),但这些 N(试验数)需要人手输入且不与一次研究会话里实际跑过的所有变体自动挂钩;没有把'本次研究共试了多少配置'自动喂给 DSR,选择偏误折扣容易被低报。
- 没有 post-publication / OOS decay 折扣机制:M10 不会按 McLean-Pontiff 经验(-26%/-58%)或经验贝叶斯收缩自动给样本内 alpha 打折再做 M8 资本配置,资本可能按未折扣的样本内 Sharpe 分配。
- 完全没有拥挤(crowding)度量:无 valuation spread / 短仓 / 成对相关 / 持仓重叠 / 资金流等代理,M11 的 WARNING/RETIRED 只看 IC 衰减,看不到'因子是否过度拥挤、是否有拥挤崩盘风险'。
- 因子生命周期(M11)的状态迁移阈值是手填、评估是手动触发——MEMORY 已记录'缺自动调度评估';没有 M13 DAG 定期拉数→重算 IC/拥挤→自动迁移状态的闭环,也没有把多重检验/forking-paths 校正写进迁移判据。
- 没有预注册/协议闸门:M1 StrategyGoal 记录意图,但没有把'假设、数据窗口、计划检验数 N、停止规则'在研究开始前冻结成不可改的预注册记录,事后也不强制报告全部试验数(Arnott-Harvey-Markowitz 七点、forking-paths)。M12 lineage 有 parent/forked_from 但不是预注册。
- 资产无关性未在因子层验证:JKP 的跨93国、crypto 的34异象复制(仅约13/49显著)说明'因子在另一资产域能否复制'是硬约束第1条的关键检验,但 QuantBT 没有把'同一因子在 A股 vs 加密两个 connector 上同时复制'做成标准闸门。

### Agent OS 在这一环的角色（服务零代码用户）

这一环对零代码用户最反直觉也最危险——回测漂亮不等于因子真。Agent OS 要把'统计严谨'翻译成经济学者听得懂、能据以做 go/no-go 的语言与流程导轨。具体:(1) 预注册即对话——需求澄清 agent 在跑任何回测前,用自然语言逼用户先讲清'你预期这个因子赚钱的经济逻辑是什么(风险溢价?行为偏误?)、在哪个市场、打算试几个版本',并把这些冻结成不可改的预注册卡(对应硬约束2的假设登记)。这把'经济判断 human-in-the-loop'落到最该落的点。(2) 把 t/FDR/PBO 翻成红绿灯+人话——不给小白看 t=2.78,而是说'你这个因子表面年化15%,但我们试了37个版本只留了最好的,扣掉运气和'别人也会发现'的折扣后,可信的预期更接近年化4%,且有43%概率它只是运气(PBO)'。严谨度=可信区间+折扣后数字+一句因果解释。(3) 同侪比较器——agent 自动把用户的新因子拿去和因子族(M4 alpha_lite/registry,理想接 Chen-Zimmermann 或 JKP 开源真值集)对比,用大白话回'你这个其实80%是动量,没带来新东西',替经济学者做 Feng-Giglio-Xiu 式增量判断。(4) 跨资产复制按钮——一键在 A股和加密两个 connector 上各跑一遍,'同一逻辑两个市场都成立'是最朴素也最强的可信信号,正好兑现资产无关硬约束。(5) 生命周期仪表盘当信任锚——把因子的五态、IC 衰减曲线、拥挤度做成连续叙事('这个因子3个月前 QUALIFIED,最近30天 IC 掉了60%且估值差处于历史90分位=很可能被交易拥挤了,我建议降级'),让读不懂代码的人靠'流程在持续替我盯着、并主动报警'来建立信任。所有 agent 自主出工程(拉数/算 IC/算 PBO/查拥挤),人只出经济先验与最终闸门 go/no-go。

### 建议

- 在 M4/M11 之间加'因子增量与冗余检验'模块:对每个候选因子,先对现有 FactorRegistry 因子族做相关/正交化与简化版 Feng-Giglio-Xiu(双重选择 LASSO 或对现有因子族回归取残差 alpha 的 t),agent 用人话报告'相对旧因子的增量'。理想接入 Chen-Zimmermann openassetpricing.com 或 JKP Global Factor Data 作真值/对照集。  `[→M4/M11, eff=high, lev=high]`
- 在 M11 生命周期判据里把单 t>3 升级为多重检验感知门槛:记录该研究会话累计试验数 N,套用 Harvey-Liu-Zhu(t≈3 起)与 Harvey-Liu 双 bootstrap FDR,给出'按 5% FDR 的实际门槛'。同时把这个 N 自动喂给 M10 的 DSR/PBO,杜绝选择偏误被低报。  `[→M11/M10, eff=med, lev=high]`
- 在 M10 归因/M8 配置之间加'去通胀与衰减折扣层':对样本内 alpha 默认套用经验贝叶斯收缩 + McLean-Pontiff 风格折扣(可配置 OOS-26%/post-pub-58% 或按实测 OOS 估计),用折扣后的预期 Sharpe 而非样本内 Sharpe 进 mean-variance/risk-parity 配置。前端把'样本内 vs 折扣后'两个数字并排给用户看。  `[→M10/M8, eff=med, lev=high]`
- 新增'拥挤监测'子模块并接入 M11 的 WARNING 触发:实现可插拔 crowding 代理(估值差 valuation spread、成对相关上升、可得时接短仓/ETF 资金流),A股/加密各填各的数据源(兑现资产无关)。M11 在 IC 衰减之外把'拥挤度处于历史高分位'也作为降级信号,并明确标注'拥挤预测崩盘风险'而非简单低收益(标注此为 contested,谨慎用词)。  `[→M11/M3, eff=high, lev=med]`
- 用 M13 DAG 把因子生命周期评估做成定时闭环:croniter 周/月触发→M3 拉新数据→M4 重算 IC/RankIC/IC衰减+拥挤代理→M11 自动迁移状态并写 lifecycle_event_log→异常时 M14 agent 主动推送人话预警。直接补上 MEMORY 记录的'缺自动调度评估'。  `[→M13/M11/M14, eff=med, lev=high]`
- 在 M1 StrategyGoal + M12 注册表上做'预注册闸门':研究开始前由需求澄清 agent 把经济假设、数据窗口、计划检验数 N、停止规则冻结成不可改的 pre-registration 记录(对应 Arnott-Harvey-Markowitz 七点);事后 M10 报告强制列出本次全部试验数与关键分析路径离散度(forking-paths/nonstandard-errors 精神),让'报告全部试验而非只报赢家'成为硬约束。  `[→M1/M12/M10, eff=med, lev=high]`
- 做'跨资产复制'标准闸门:同一因子定义自动在 A股 connector 与加密 connector 上各跑一遍并对比 IC/方向一致性,agent 用大白话报告'两个市场是否都成立'。这既兑现硬约束1的资产无关,又把 JKP/crypto-replication 的可信信号做成小白能懂的一句话。  `[→M11/M3, eff=med, lev=med]`
- 在 M19 Glossary/教学 agent 里补一组'因子动物园/复制危机'渐进披露词条(t>3门槛、PBO、post-publication decay、拥挤、增量检验),并在 coach 决策状态机里加规则:当用户的因子试验数 N 偏高或 PBO 偏高时,主动用苏格拉底式提问逼其讲经济逻辑、警告过拟合。把严谨度转成教学而非数字墙。  `[→M19/M14, eff=low, lev=med]`

### 对抗式核查裁决 — 总体置信度：**high**

_纠正摘要_: 12 篇所引论文全部真实存在、年份/期刊/核心结论基本对得上，未发现虚构文献。6 条论断的核心方向全部站得住(4 条 confirmed，1 条 confirmed-with-caveat，论断6是无法对外验证的设计性主张标 nuanced)。需纠正的有三处实质问题：(1) 作者错误——'High-Throughput Asset Pricing'(arXiv 2311.10685) 作者是 Chen & Dim，不是'Chen, Velikov 等'；Velikov 没参与这篇，引用须改。(2) 立场张冠李戴——Coqueret(2401.08606) 的主旨是'展开大量自由度提升可信度'(forking paths 是工具/特性)，而'论证非标准误差与预注册必要性'是 Menkveld 那篇的论点；claim 把两篇并成一条且把后者的论点安到 Coqueret 头上，需拆开。(3) 一个未锁定的硬数字——论断5 的'49 异象仅约13显著'方向对(crypto 显著异象占比低)但找不到唯一原始出处，应回填或改定性。另需向用户强调三个深化点:换成 FDR 门槛并未'解决'问题(Chen-Zimmermann 主张 t-hurdle 因发表偏误根本不可识别)；拥挤代理(尤其短仓)信噪比经撤回论文实证不足以触发自动降级、只能当风险告警(其策略 Sharpe 0.22 跑输 0.39 基准、作者自述'predicts crashes not means'，AQR 也把过度拥挤列为 fiction)；自动退役阈值须区分统计退化与 regime 逆风并保留 human-in-the-loop。

被降权/纠正的论断：
- `nuanced` — 论文真实性核查 + 内容：Forking Paths (Coqueret 2024, arXiv 2401.08606)；每多一个自由度 t 区间至少扩30%、用paths时5%门槛飙到8.2
  - 纠正：但 claim 把 Coqueret 的立场描述偏了。Coqueret 的主旨恰恰是'展开大量自由度能更好刻画效应、从而提升结论可信度'(forking paths 是特性而非缺陷)——他用 paths 来抬高证据门槛/检验稳健性，并非像 Menkveld 那样把它当作必须用预注册去消灭的'非标准误差'问题。'论证非标准误差与预注册的必要性'这句应归给 Menkveld 那篇，不应安在 Coqueret 头上。两篇被 claim 合并成一条，论点有混淆。
- `nuanced` — 论文真实性核查：High-Throughput Asset Pricing (Chen, Velikov 等 2023-2025, arXiv 2311.10685)；对数万条挖掘出的预测变量做经验贝叶斯收缩+FDR控制
  - 纠正：作者错了。该文作者是 Andrew Y. Chen 与 Chukwuma Dim，Mihail Velikov 并非作者。Velikov 与 Chen 合著的是另一篇(如 'Zeroing in on the Expected Returns of Anomalies')。引用时应改为 'Chen & Dim (2023/2025)'。
- `nuanced` — 论断6：自动化生命周期调度能替代人的经济判断——M11 自动降级/退役阈值可能在 regime 切换时误杀好因子，agent 的'人话翻译'可能把统计不确定性过度简化制造过度自信
  - 纠正：把它当成设计约束而非已验证事实:(1) 自动降级阈值应区分'统计退化'与'regime 逆风'(如加 regime 条件化的衰减检测、或要求连续多个 regime 都失效才退役),并保留 human-in-the-loop 复核闸门;(2) agent 的'人话翻译'必须把不确定性(置信区间、PBO、样本长度、是否 regime 依赖)一并呈现,避免把'当前样本下不显著'翻译成'这个因子没用'这种过度自信表述。

---


## [11] 自动化 alpha 挖掘前沿  · 组 C

**机构级标准** — 机构级的自动化 alpha 挖掘必须把"搜索"和"治理"绑成一个不可分割的闭环——挖得快不算本事，挖得能在样本外活下来才算。具体标准：(1) 搜索空间显式化：算子集、表达式语法、参数范围、可用数据全部声明在册并版本化，使搜索可复现、可审计（WorldQuant 101 alphas 是把"alpha 即可执行代码"标准化的源头）。(2) 多重检验校正必须前置而非事后：每次搜索都在做成百上千次隐式假设检验，因此必须按 Harvey-Liu-Zhu 把显著性门槛从 t>2 提到 t>3（甚至更高），并用 Deflated Sharpe Ratio（Bailey & López de Prado）按"实际试验次数 N"对 Sharpe 去膨胀，用 PBO（CSCV）量化"该策略是过拟合产物的概率"。机构会把"搜索了多少次"当作一等公民记录下来，喂给 DSR 的 N。(3) 验证协议：纯时间序列 train/test split 已不够，CPCV（Combinatorial Purged Cross-Validation，含 purge+embargo）给出 OOS 性能的分布而非单点，是当前 ML 资管的事实标准。(4) 经济先验门：纯数据驱动的因子若无可陈述的经济机制（风险溢价/行为偏差/微观结构），按 McLean-Pontiff（出版后衰减 ~35%）和 Hou-Xue-Zhang（447 个异象 64% 不显著）的证据，应被强降级。前沿框架（AlphaAgent）已把"假设-因子语义一致性"做成正则项。(5) 因子组合与衰减治理：单因子不是终点，必须评估增量贡献（与已有因子族的相关性/正交性）、换手率/容量、以及上线后的 IC 漂移监控与退役机制。(6) 去同质化：对结构高度雷同的公式做去重（AST 子树匹配），防止"换皮过拟合"。一句话：自动化提升了搜索吞吐，机构级标准的全部重量因此压在"多重检验校正 + 经济门 + OOS 分布 + 试验计数诚实记录"这四根柱子上。


### 关键论文 / 权威实践

- **101 Formulaic Alphas** ([链接](https://arxiv.org/abs/1601.00991))
  - _Zura Kakushadze · 2016 · Wilmott / arXiv:1601.00991_
  - 把 WorldQuant 真实使用的 101 个公式化 alpha 公开为可执行代码，确立了'alpha 即一行可计算表达式'的范式，是后续所有自动化公式化因子挖掘（GP/RL/LLM）的算子语法与基准来源。多数为短持有期、高换手的中低频信号。
- **…and the Cross-Section of Expected Returns** ([链接](https://academic.oup.com/rfs/article/29/1/5/1843824))
  - _Campbell R. Harvey, Yan Liu, Caroline Zhu · 2016 · Review of Financial Studies 29(1):5-68_
  - factor zoo 的多重检验奠基作：鉴于已测试数百个因子，新因子的 t 值门槛应从 2.0 提到 3.0；提供了考虑测试间相关性与发表偏差的校正框架。是'自动挖掘 = 大规模多重检验'这一认知的理论锚。
- **Replicating Anomalies** ([链接](https://academic.oup.com/rfs/article-abstract/33/5/2019/5236964))
  - _Kewei Hou, Chen Xue, Lu Zhang · 2020 · Review of Financial Studies 33(5):2019-2133_
  - 复现 447 个已发表异象，在控制微盘股后 64%（286 个）在 5% 水平不显著、施加 t>3 门槛后 85% 不显著；实证证明文献充斥 p-hacking。是评估自动挖掘产物'有多少是假发现'的经验基准。
- **Does Academic Research Destroy Stock Return Predictability?** ([链接](https://onlinelibrary.wiley.com/doi/abs/10.1111/jofi.12365))
  - _R. David McLean, Jeffrey Pontiff · 2016 · Journal of Finance 71(1):5-32_
  - 97 个预测变量样本外收益降 26%、出版后降 58%（均值衰减约 35%）；区分了'数据挖掘偏差'与'投资者学习/价格压力'两种衰减来源。是 alpha 衰减治理（M11）与'经济门'必要性的核心证据。
- **The Deflated Sharpe Ratio: Correcting for Selection Bias, Backtest Overfitting and Non-Normality** ([链接](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2460551))
  - _David H. Bailey, Marcos López de Prado · 2014 · Journal of Portfolio Management_
  - 给出按试验次数 N、偏度、峰度对 Sharpe 去膨胀的封闭式统计量；是把'我搜索了多少次'诚实纳入显著性判定的标准工具，与 PBO/CSCV 配套。QuantBT M10 已实现。
- **Generating Synergistic Formulaic Alpha Collections via Reinforcement Learning (AlphaGen)** ([链接](https://arxiv.org/abs/2306.12964))
  - _Shuo Yu, Hongyan Xue, et al. · 2023 · KDD 2023 (ADS track), arXiv:2306.12964_
  - 用 RL（策略梯度）在公式化 alpha 空间搜索，以下游组合模型表现（IC）作为 reward，直接优化'协同的因子集合'而非单因子。是 RL 因子挖掘的代表作与开源基准（RL-MLDM/alphagen）。批评点：用 IC 做 reward 易过拟合、固定权重不适应市场。
- **AlphaForge: A Framework to Mine and Dynamically Combine Formulaic Alpha Factors** ([链接](https://arxiv.org/abs/2406.18394))
  - _Hao Shi, et al. · 2025 · AAAI 2025, arXiv:2406.18394_
  - 两阶段：生成-预测神经网络挖因子（保多样性）+ 动态组合模型在每个时间切片按因子近期表现调整权重，解决 AlphaGen 固定权重不适应市场的问题。
- **AlphaAgent: LLM-Driven Alpha Mining with Regularized Exploration to Counteract Alpha Decay** ([链接](https://arxiv.org/abs/2502.16789))
  - _Ziyi Tang, et al. · 2025 · arXiv:2502.16789_
  - 三 agent 闭环（Idea/Factor/Eval）+ 三个正则项对抗衰减：原创性（AST 最大公共子树相似度惩罚，对标 Alpha101 去同质）、复杂度（符号长度+自由参数计数）、假设-因子语义一致性。2021-2024 OOS 上 IC 稳定在约 0.02 而传统因子衰减至近零。把'经济机制'做成可优化的正则项，是对抗过拟合范式的关键转向。
- **Navigating the Alpha Jungle: An LLM-Powered MCTS Framework for Formulaic Factor Mining** ([链接](https://arxiv.org/abs/2505.11122))
  - _(arXiv:2505.11122) · 2025 · arXiv:2505.11122_
  - 用 UCT 蒙特卡洛树搜索 + LLM 做维度定向精化；Frequent Subtree Avoidance（避开 alpha 库中最常见结构）促结构多样性；五维评估（有效性/稳定性/换手/多样性/过拟合风险）替代单指标。OOS（2021-2024 A股）优于 AlphaGen 与 GP，且搜索效率高约 200×。
- **AlphaEvolve: A coding agent for scientific and algorithmic discovery** ([链接](https://arxiv.org/abs/2506.13131))
  - _Google DeepMind · 2025 · arXiv:2506.13131_
  - LLM（Gemini）提出语义化代码改动 + 进化算法的选择压力 + 自动评估器构成自治改进流水线（如改进 4x4 复矩阵乘到 48 次标量乘）。提供了'LLM 创造性 + 进化选择压力 + 可执行评估闸门'这一通用范式，可直接迁移到因子代码进化（开源对照：CodeEvolve arXiv:2510.14150）。
- **AutoAlpha: an Efficient Hierarchical Evolutionary Algorithm for Mining Alpha Factors** ([链接](https://arxiv.org/abs/2002.08245))
  - _Tianping Zhang, et al. · 2020 · arXiv:2002.08245_
  - 分层进化算法挖因子：先搜根因子骨架再精化，显著提升 GP 搜索效率与因子多样性。是 GP/进化路线在 101 alphas 之后的代表性工程改进。

### SOTA 方法

- **遗传规划 / 符号回归（GP，gplearn / AutoAlpha 风格）** `[established]` — 演化表达式树（交叉+变异），产出人类可读公式。工业界最常用的 alpha 搜索算法。已确立但缺陷明确：盲搜符号空间、无经济直觉、最易过拟合，依赖 OOS 内嵌评估、复杂度正则、早停来缓解。
- **RL 因子挖掘（AlphaGen / AlphaForge / 轨迹级 reward shaping）** `[emerging]` — 以 IC 或下游组合表现为 reward，用策略梯度探索因子空间，可直接优化'协同因子集合'。AlphaForge 进一步做动态权重组合。是过去两年学术热点与开源基准，但 IC-as-reward 易过拟合、计算成本高、固定权重适应性差，且 OOS 复现性受质疑。
- **LLM 驱动 alpha 生成（AlphaGPT 人机交互 / AlphaAgent / Chain-of-Alpha / QuantAgent / FactorMAD 多 agent 辩论）** `[emerging]` — 用 LLM 把市场假设翻译成可读因子表达式或代码，闭环生成-评估-精化。卖点是可解释性 + 经济直觉注入 + 把'假设-因子一致性'做成正则项对抗衰减。直接契合'非程序员用经济语言出意图'。但严重依赖底座 LLM 质量、存在训练数据泄露/记忆已知因子风险、且部分方法重度依赖人工反馈。
- **进化式编码 agent（AlphaEvolve / CodeEvolve）** `[emerging]` — LLM 提出语义化代码修改 + 进化选择压力 + 自动评估器，用于通用算法/代码发现。尚未在公开金融 alpha 上有 SOTA 实证，但范式（创造性变异 + 严格评估闸门）是把 LLM 因子生成工程化、可治理化的最有前景方向。
- **GFlowNet / 结构感知因子搜索（AlphaSAGE、alpha-gfn）** `[contested]` — 用 GFlowNet 按 reward 成比例采样多样化因子结构，针对 RL'探索坍塌到少数高 reward 模式'的问题改善多样性。新兴、证据有限。
- **多重检验校正与过拟合度量（DSR / PBO-CSCV / CPCV / t>3 门槛）** `[established]` — DSR 按试验次数去膨胀 Sharpe；PBO 量化过拟合概率；CPCV 给出 OOS 性能分布（含 purge+embargo）。这是把'自动挖掘'与'数据窥探'张力实际钳制住的治理工具栈，学术与机构共识度最高。
- **自动化因子评估框架（AlphaEval 等）** `[emerging]` — 试图把'一个因子是否值得信'标准化为多维度自动评分（有效性/稳定/换手/多样/过拟合风险），降低人工评审噪声。新兴、尚未形成统一标准。

### 差距

- 试验计数（N）未贯通到 DSR：QuantBT M10 已实现 DSR/PBO/Bootstrap CI，但 factor_factory 在做表达式搜索/alpha_lite 批量评估时，没有把'本轮搜索了多少个候选公式'作为一等公民记录并自动喂给 DSR 的 N。一旦上自动挖掘（GP/RL/LLM），这是头号过拟合漏洞——挖了 10000 个因子却按单次检验报 Sharpe。
- 没有自动化 alpha 搜索引擎本身：M4 有 44 算子 + AST 表达式引擎 + alpha_lite 30 因子，但这是'手写/预置因子库 + 评估'，缺 GP/RL/LLM 的自动搜索回路。AlphaGen/AlphaForge/MCTS 这一层完全空白。
- 缺去同质化/原创性闸门：没有 AST 子树相似度去重（AlphaAgent/MCTS-FSA 的核心机制）。自动挖掘极易产出 Alpha101 换皮因子，当前无机制拦截。
- 缺经济先验门作为强制环节：M11 因子生命周期有五态机与阈值，但'因子必须附可陈述经济机制且通过语义一致性校验'未成为 NEW→QUALIFIED 的硬闸。这正是 McLean-Pontiff/Hou-Xue-Zhang 证据要求的、也是非程序员能信任的核心。
- 缺 CPCV：M6 有 Purged k-fold + Embargo + Walk-forward，但无 Combinatorial Purged CV，拿不到 OOS 性能分布，PBO 估计的统计基础偏弱。MEMORY 也记录 M6 缺 CPCV/Optuna/GARCH。
- Agent 能力是散的：M14 reAct+工具 / M18 IDE 沙箱写跑代码 / M19 教学 RAG，但没有'假设登记→自动搜索→多重检验闸门→经济门→人审 go/no-go'的统一导轨把它们串成一条带持久记忆、可复现谱系的自动挖掘流水线。
- LLM 因子生成的数据泄露风险无防护：若引入 LLM 挖因子，模型可能直接吐出训练语料里见过的已知因子（伪'发现'），当前无去泄露/盲测机制。

### Agent OS 在这一环的角色（服务零代码用户）

这一环是 Agent OS 价值最浓也最危险的地方：自动挖掘让'生成假设'近乎零成本，于是唯一能让零代码用户信任产出的，不是因子本身，而是因子穿过的那条治理导轨。落地路径：(1) 假设登记先行——需求澄清 agent 把用户的经济直觉（'我觉得成交量异动后三天会反转'）固化成预注册的良构假设（方向/标的/持有期/机制），登记在册、时间戳锁定，这一步既是预注册（防 p-hacking），也是用户能读懂的入口。(2) 工程全自主——agent 调 factor_factory 把假设翻译成 AST 表达式/代码、批量搜索候选（GP/LLM 提议），用户全程不碰代码。(3) 严谨度翻译成经济与流程语言：不要给小白看 t 值和 DSR 公式，而是翻译成红绿灯式叙事——"你这个想法生成了 800 个变体，但只有 3 个在没见过的数据上还站得住（绿）；其余在历史上很漂亮但换个时间段就垮了（红），这是典型的'专挑历史里碰巧好看的'，我已替你淘汰"；"这个因子我找不到能讲通的经济理由，按规矩它只能进观察区不能上钱"。把 DSR 的 N、PBO、CPCV 分布都包装成"我替你试了多少次、有多大概率是运气、换个市场还灵不灵"。(4) human-in-the-loop 硬卡两道：经济机制是否成立（经济学者出判断）、是否配资上线（go/no-go），由人按 M20 阶梯做，agent 只能建议不能自动上钱。(5) 持久记忆/谱系：每个因子带血缘（来自哪个假设、搜索了多少次、过了哪些闸门、被谁批），这本'账'就是非程序员的信任基础——他读不懂代码，但能读懂"这个因子的来历和体检报告"。资产无关性在此天然满足：算子/数据/评估全是配置，换品类不改导轨。

### 建议

- 把'试验计数 N'做成一等公民：在 factor_factory 搜索/批量评估回路里记录本轮评估的候选公式总数，并自动贯通到 M10 的 DSR 与 PBO，使任何自动挖掘产物的显著性都按真实 N 去膨胀。这是上自动挖掘前的不可跳过前置项。  `[→M4+M10, eff=low, lev=high]`
- 加 AST 子树相似度去重/原创性闸门：复用现有 AST 表达式引擎，对候选因子两两计算最大公共子树相似度，并与 alpha_lite/Alpha101 库比对，超阈值的'换皮因子'自动拒入。直接落地 AlphaAgent/MCTS-FSA 的核心防过拟合机制。  `[→M4, eff=med, lev=high]`
- 实现 CPCV（Combinatorial Purged CV）补足 M6：在已有 purge+embargo 基础上做组合式多路径划分，产出 OOS 性能分布而非单点，强化 PBO 的统计基础。学术共识工具，落地确定性高。  `[→M6+M10, eff=med, lev=high]`
- 把'经济机制 + 假设-因子语义一致性'做成 NEW→QUALIFIED 的硬闸：每个自动挖出的因子必须附 LLM 生成、人审确认的经济机制陈述，并校验表达式是否真的实现该机制；无机制者强制只能进 PROBATION/OBSERVATION 不得配资。直接把 McLean-Pontiff 证据制度化。  `[→M11+M14, eff=med, lev=high]`
- 在 M14 上搭'假设登记→自动搜索→多重检验闸门→经济门→人审 go/no-go'统一 DAG，先用 LLM 提议表达式（最小可行的 Chain-of-Alpha/AlphaAgent 风格闭环），复用 M13 DAG 引擎做编排、M12 注册表存血缘。先做 LLM 提议路线而非自建 GP/RL，因其天然带经济叙事、契合非程序员。  `[→M13+M14+M12, eff=high, lev=high]`
- 为前端做'红绿灯式因子体检报告'组件：把 N/DSR/PBO/CPCV 分布/经济机制/与现有因子相关性翻译成经济学语言与红黄绿结论，不展示原始统计量给小白。注意 RunDetailPage 冻结约束，新增独立页面而非改收益概述。  `[→M15+M19, eff=med, lev=med]`
- 加 LLM 数据泄露盲测：当用 LLM 生成因子时，对'疑似记忆已知因子'做盲测（在 LLM 训练截止后的全新时段/全新品类上验证），并在血缘里标注泄露风险等级。低成本高价值的诚信护栏。  `[→M14+M11, eff=low, lev=med]`

### 对抗式核查裁决 — 总体置信度：**high**

_纠正摘要_: 全部 11 篇所引论文均真实存在、作者/年份/核心结论基本对得上,无虚构论文——研究流 [11] 的文献功底扎实。但 6 条论断中有 4 条需降级为 nuanced:(1)AlphaAgent IC≈0.02 转述准确,但'≈0.02'是择优挑的 CSI500 数字(S&P500 仅0.0056),且论文只有单次回测对照、无多重检验/N校正/DSR-PBO 显著性检验——论断暗含的'同口径已校正显著'前提不成立,对抗质疑成立。(3)MCTS'效率高约200×'是对论文的误读/反转:论文是给 GP/AlphaGen baseline 多达200倍的搜索预算(上限600k vs LLM的3k)而 LLM 仍胜,等价于 LLM 用约1/200评估次数达可比效果——方向对但措辞需改;IR 1.23 是 GPT-4.1 档非全局最优(Gemini档1.27);该论文同时用美股,非纯'2021-2024 A股'。(2)(5)是合理的方法论批判(LLM 经济叙事=事后合理化放大信任风险;AlphaEvolve 评估器确定可验证而 alpha 回测非平稳/过拟合温床),证据支持,标 confirmed/nuanced。(4)(6)对抗论点成立,confirmed。文献描述需小修两处:McLean-Pontiff'均值衰减约35%'非原文数字(应为 OOS 26%、post-pub 58%);Harvey-Liu-Zhu 第三作者 Caroline Zhu 与 Heqing Zhu 实为同一人(无误)。总体:论文层面高可信,论断层面普遍存在'择优引用单一市场数字'与'把公平性设计(给baseline 200倍预算)误读为效率倍数'两类夸大,使用时须按上述纠正口径降权。

被降权/纠正的论断：
- `nuanced` — 论断1: AlphaAgent 在 2021-2024 OOS 上 IC 稳定在约 0.02 而传统因子衰减至近零（需核查同口径/N校正/多重检验显著性）
  - 纠正：三点夸大/省略：(1)'IC≈0.02'是 CSI500(中国)数字，S&P500 仅 0.0056，研究流引用择优挑了中国市场；(2)论文只给单次回测对照表，没有做多重检验校正、没有 N 校正、没有 DSR/PBO 检验，'IC 稳定'是 5 年时序曲线的视觉稳定而非统计显著性检验；(3)'传统因子衰减至近零'是论文自述的对照叙事(单口径回测)，并非独立验证。该论断转述论文准确，但论断中暗含的'已做同口径/N校正显著性'前提不成立——正是又一次未做 N 校正的样本内乐观，对抗式质疑成立。
- `nuanced` — 论断2: LLM 驱动因子挖掘'契合非程序员且可解释'，需质疑经济机制陈述多为事后合理化而非真因果，反而放大信任风险
  - 纠正：对抗质疑成立且重要。'可解释'在这些论文里是 LLM 自评的语义一致性，不是因果识别——LLM 生成的'经济机制'本质是对已选中因子的事后叙事(rationalization)，论文没有任何因果检验(如机制外生冲击/工具变量)。McLean-Pontiff(2016)证明已发表预测变量出版后衰减58%，说明'有经济故事'并不能阻止衰减。把貌似合理的经济叙事配给非程序员，确实可能降低其对假发现的警惕(信任风险被放大)。论断是合理的方法论批判而非可证伪的事实陈述，故标 nuanced。
- `nuanced` — 论断3: MCTS 框架搜索效率比 GP/AlphaGen 高约 200×且 OOS 更优；IR 1.23 成立
  - 纠正：'200×'被误读/反转。论文原文：LLM 方法最大 search count=3000，而对 GP 等非 LLM baseline 把 search count 增到收敛、上限 600,000='200× the LLM-based methods maximum'。即：给了 baseline 多达 200 倍的搜索预算，LLM 方法仍胜出——等价于'LLM 用约 1/200 的评估次数达到可比/更优结果'。所以'效率高约200×'方向上对(以 search count 计)，但严格说法是'baseline 预算被放到200倍'，且'200×'只衡量唯一公式生成数，不含每步算力差异。另外该论文同时用美股(S&P500),并非纯'2021-2024 A股';训练期 2011-2020。baseline(AlphaGen/GP)是按收敛调优的(算调优充分)。IR 1.23 引用准确但应注明是 GPT-4.1 档、非全局最优档。

---


## [12] ML 资产定价前沿 + 不确定性量化  · 组 C

**机构级标准** — 机构级标准（中低频、资产无关的 ML 资产定价 + 不确定性量化）可拆为方法学与治理两条：

方法学：(1) 严格无泄露的时序样本切分——递归/扩张窗口训练→验证→样本外测试，绝不随机打乱、绝不未来信息回看（GKX2020 的训练18年/验证12年/测试30年滚动设计是事实标准）；(2) 用机构惯例的预测度量评估，而非点估计自吹——逐月样本外 R^2（个股 vs 组合分开报）、长短分位组合的样本外 Sharpe（且区分等权/市值权、含/不含微盘）、Bootstrap Sharpe 置信区间、CSCV/PBO 防过拟合、DSR 折扣多重检验；(3) 正则化与降维（弹性网、PLS、PCR、树/GBRT、NN1-5）为标配，普遍发现 OLS 无正则在高维下样本外 R^2 为负，正则化后转正（GKX：弹性网约 0.11%/月，PCR/PLS 约 0.26-0.27%，NN3 约 0.40%）；(4) 集成是默认而非可选——对随机种子/初始化取平均（GKX 对 10 个随机种子平均），近年共识进一步到跨模型 stacking；(5) 经济约束作为机构级正确性来源——no-arbitrage/SDF（IPCA、autoencoder、GAN-SDF）、regime 条件化、经济变量重要性需可解释（动量/流动性/波动率主导）；(6) 必须在交易成本与可套利性约束下复核——Avramov-Cheng-Metzker 证明 ML alpha 大量来自微盘/高套利限制股，扣成本后大幅衰减；(7) 不确定性量化已是前沿机构标准的一部分——预测要带分布无关覆盖保证的区间（conformal/CQR/ACI），概率输出要校准（reliability diagram + ECE），并在分布漂移/regime 切换时能 abstain（不交易）。

治理：模型上线前要登记假设、独立验证、审批门、资本配置上限；上线后 live 漂移监控 + 模型风险问责（SR 11-7 风格）+ 衰减/退役机制。ML 模型的"黑箱"必须被特征重要性、SHAP、经济解释翻译成可问责的语言。


### 关键论文 / 权威实践

- **Empirical Asset Pricing via Machine Learning** ([链接](https://academic.oup.com/rfs/article/33/5/2223/5758276))
  - _Shihao Gu, Bryan Kelly, Dacheng Xiu · 2020 · Review of Financial Studies (NBER w25398)_
  - 本领域奠基与基准设定之作。在约30000只美股、94个特征+8宏观变量上系统比较OLS/弹性网/PLS/PCR/GBRT/RF/NN1-5，采用18年训练+12年验证+30年滚动测试的严格无泄露切分。关键结论：OLS无正则样本外R^2为负，正则化与非线性显著改善；NN3达个股月度样本外R^2约0.40%；NN预测的长短分位组合样本外Sharpe约2.45(等权)/1.35(市值权)；所有方法一致指认动量/流动性/波动率为主导预测变量；用对随机种子取平均做集成。是QuantBT M4-M10流程的对标蓝本。
- **Financial Machine Learning (survey)** ([链接](https://www.nber.org/papers/w31502))
  - _Bryan Kelly, Dacheng Xiu · 2023 · Foundations and Trends in Finance / NBER w31502_
  - 160页权威综述，定义本环节的'机构级标准'。系统梳理收益预测、SDF估计、因子模型、不确定性、交易成本，并提出方法学共识（无泄露切分、正则化、集成、经济约束）与开放问题。是给这一条研究流定标的首选参考。
- **The Virtue of Complexity in Return Prediction** ([链接](https://onlinelibrary.wiley.com/doi/full/10.1111/jofi.13298))
  - _Bryan Kelly, Semyon Malamud, Kangying Zhou · 2024 · Journal of Finance, 79(2):459-503_
  - 理论+实证论证'参数数>观测数'的超参数化(over-parameterized)模型在收益预测上反而优于简约模型，挑战奥卡姆剃刀直觉；用随机特征+岭回归(ridgeless)展示双下降现象。机构级争议点：是真信号还是隐式正则化的产物，业界(如Buncic简化复核、Nonstationarity-Complexity tradeoff 2025)有质疑。
- **Deep Learning in Asset Pricing** ([链接](https://pubsonline.informs.org/doi/10.1287/mnsc.2023.4695))
  - _Luyang Chen, Markus Pelger, Jason Zhu · 2024 · Management Science, 70(2):714-750_
  - 用GAN(对抗式)以no-arbitrage矩条件为准则估计SDF，用RNN从宏观时序提取经济状态(regime-aware)。报告样本外横截面R^2约23%、远高于其它模型，in-sample SR约9.3(in-sample，需谨慎解读)。是'经济约束+深度学习+状态依赖'的SOTA代表。
- **Autoencoder Asset Pricing Models** ([链接](https://www.sciencedirect.com/science/article/abs/pii/S0304407620301998))
  - _Shihao Gu, Bryan Kelly, Dacheng Xiu · 2021 · Journal of Econometrics, 222(1):429-450_
  - 用自编码器把IPCA的线性载荷推广为特征的非线性函数，在no-arbitrage约束下同时估计潜在因子与条件暴露；样本外定价误差远小于(且通常不显著区别于零)其它领先因子模型。
- **Characteristics Are Covariances: A Unified Model of Risk and Return (IPCA)** ([链接](https://www.sciencedirect.com/science/article/abs/pii/S0304405X19301151))
  - _Bryan Kelly, Seth Pruitt, Yinan Su · 2019 · Journal of Financial Economics, 134(3):501-524_
  - 提出Instrumented PCA：用可观测特征工具化时变的潜在因子载荷。发现5个IPCA因子比现有因子模型更准确解释截面均值收益，且大量特征中仅约10个在1%水平显著、贡献近100%准确度——是'白箱可解释+降维'的机构级范式，对抗因子动物园。
- **Machine Learning vs. Economic Restrictions: Evidence from Stock Return Predictability** ([链接](https://pubsonline.informs.org/doi/abs/10.1287/mnsc.2022.4449))
  - _Doron Avramov, Si Cheng, Lior Metzker · 2023 · Management Science, 69(5):2587-2619_
  - 关键对抗式证据：深度学习信号的盈利大量来自难套利/微盘/困境股与高市场波动期；剔除微盘/困境股或加入合理交易成本后盈利大幅衰减（高换手+极端权重）。是评估任何ML alpha真实性的必读反方。
- **The Uncertainty of Machine Learning Predictions in Asset Pricing** ([链接](https://arxiv.org/abs/2503.00549))
  - _Yuan Liao, Xinjie Ma, Andreas Neuhierl, Linda Schilling · 2025 · arXiv:2503.00549 (working paper)_
  - 把ML预期收益预测的不确定性量化做成渐近推断：证明NN预期收益预测与经典非参方法同分布、可得闭式标准误，并给可行bootstrap。把置信区间嵌入'厌恶不确定性'投资框架，为收缩(shrinkage)型组合选择提供经济学依据，样本外表现优于忽略预测不确定性的标准ML。是把UQ接入资产定价的前沿桥梁。
- **Adaptive Conformal Inference Under Distribution Shift (ACI)** ([链接](https://arxiv.org/abs/2106.00170))
  - _Isaac Gibbs, Emmanuel Candès · 2021 · NeurIPS 34_
  - 在线设定下数据生成分布随时间未知变化时，通过在线调整miscoverage率，在长时间区间上无分布假设地达到目标覆盖率。是把conformal用于非平稳金融时序(regime切换)的核心方法，可包裹任意黑箱预测器。
- **Conformalized Quantile Regression (CQR)** ([链接](https://arxiv.org/abs/1905.03222))
  - _Yaniv Romano, Evan Patterson, Emmanuel Candès · 2019 · NeurIPS 32_
  - 把分位回归与conformal结合，得到既适应异方差(局部不确定性)又有有限样本分布无关覆盖保证的预测区间，可包裹随机森林/NN等任意分位回归器。是给收益预测加'诚实误差棒'的标配方法。
- **On Calibration of Modern Neural Networks** ([链接](https://proceedings.mlr.press/v70/guo17a/guo17a.pdf))
  - _Chuan Guo, Geoff Pleiss, Yu Sun, Kilian Weinberger · 2017 · ICML 2017_
  - 证明现代深度网络系统性过自信(poorly calibrated)，提出用reliability diagram/ECE度量、temperature scaling等后验校准。是QuantBT M7已用的Platt/isotonic校准之上位理论依据，提示需要可靠图与ECE作为机构级校准证据。
- **...and the Cross-Section of Expected Returns** ([链接](https://academic.oup.com/rfs/article/29/1/5/1843824))
  - _Campbell Harvey, Yan Liu, Heqing Zhu · 2016 · Review of Financial Studies, 29(1):5-68_
  - 多重检验框架：因子动物园背景下新因子需t>3.0(而非2.0)，考虑相关性与发表偏差。是任何ML因子/信号筛选必须叠加的统计门槛，直接对应DSR/PBO治理逻辑。
- **Asset Pricing and Machine Learning: A Critical Review** ([链接](https://onlinelibrary.wiley.com/doi/abs/10.1111/joes.12532))
  - _Matteo Bagnara · 2024 · Journal of Economic Surveys, 38(1):27-56_
  - 按正则化/降维/树/NN/比较研究五类批判性梳理ML资产定价文献，强调ML强偏离传统计量、需特别谨慎(解释性、推断、数据窥探)。给本环节提供平衡的'共识 vs 局限'视角。

### SOTA 方法

- **正则化+非线性收益预测基线 (Elastic Net / GBRT / 浅层NN, GKX范式)** `[established]` — 弹性网/树/3-5层NN在严格无泄露滚动窗口下做横截面收益预测，月度个股样本外R^2约0.3-0.4%、长短组合Sharpe显著。已是教科书级机构标准。
- **经济约束的SDF/因子模型 (IPCA / Autoencoder-APM / GAN-SDF)** `[established]` — 把no-arbitrage作为目标函数或结构约束，估计条件SDF与潜在因子；IPCA为白箱降维、autoencoder/GAN为非线性版。学术共识强，业界落地中。
- **对随机种子/模型集成 (seed-averaging, bagging, stacking)** `[established]` — 对NN多次随机初始化取均值是GKX标配；进一步的跨模型stacking在极端下行期收益尤其稳健。低成本高杠杆，已是默认做法。
- **Split/Inductive Conformal Prediction + CQR** `[emerging]` — 给任意黑箱预测器加分布无关的有限样本覆盖区间；CQR适应异方差。机器学习社区成熟，金融时序应用快速成长(2024-2026多篇)。
- **非交换/在线 conformal (ACI, EnbPI, conformal PID, weighted conformal)** `[emerging]` — 针对金融时序的序列相关与regime漂移，放弃交换性假设、在线调整覆盖。是把conformal真正用对在非平稳收益上的关键，仍在快速演进。
- **概率校准 (Platt / isotonic / temperature scaling + reliability diagram/ECE)** `[established]` — 把模型置信度校准到真实正确率，用可靠图与ECE度量。分类校准成熟；金融回归/排序场景的校准与下游组合衔接仍是开放课题。
- **Regime-aware ML (HMM/Markov-switching状态 + 条件模型 / GAN-SDF的RNN状态提取)** `[emerging]` — 用隐状态(趋势/危机/低波)条件化预测或gating。Hamilton 1989以来计量传统成熟，但'用ML端到端学regime并条件化收益'仍属前沿、易过拟合。
- **ML预测的渐近/bootstrap推断 (Liao et al. 2025)** `[emerging]` — 给NN预期收益预测配标准误与置信区间，并据此做不确定性厌恶的收缩组合。把UQ与经济决策打通的最新尝试。
- **Virtue of Complexity (超参数化/random features ridgeless)** `[contested]` — 主张参数远多于样本反而更好预测收益。理论新颖但业界与后续工作(简化复核、非平稳-复杂度权衡)对其稳健性与可交易性存疑。
- **Time-series Transformer用于收益预测** `[contested]` — TFT/Autoformer等被用于价格/收益预测。证据高度分裂：部分论文称长horizon更优，但'Are Transformers Effective for TSF?'类工作显示简单线性常胜、Transformer易在噪声金融数据过拟合。中低频下性价比存疑。

### QuantBT 现状

QuantBT 在这一环已具相当好的'流程骨架'，但 ML 资产定价的'前沿表达力'与'不确定性量化'是明显短板：

已具备(对标良好)：M6 用 LGBM(分类/回归/lambdarank)+Purged k-fold+Embargo+Walk-forward——这正是 GKX 无泄露切分的核心，QuantBT 抓住了机构级正确性的命门。M7 信号四元组(direction/magnitude/confidence/regime)+regime-gating+Platt/isotonic 校准——已经触达 regime-aware 与概率校准两大主题。M10 有 PBO(CSCV)+DSR(Bailey-LdP)+Bootstrap Sharpe CI+Brinson 归因——对应 Harvey-Liu-Zhu 多重检验门槛与过拟合治理。M2 已有 ADX 判趋势/vol-z 判 crisis 的 regime。M4 有 IC/RankIC/IC-IR/IC衰减+FactorRegistry 版本化。M11 因子生命周期五态机。

缺口(相对前沿)：(1) 模型库止于 LGBM——无 NN1-5、无 autoencoder/IPCA/GAN-SDF 这类经济约束(no-arbitrage)的 ML 因子模型，即缺 GKX/Chen-Pelger-Zhu/IPCA 范式；(2) 缺 CPCV(组合化 purged CV)、Optuna/Bayesian 调参、GARCH 波动建模(MEMORY 已自认 M6 缺这三项)；(3) 不确定性量化几乎空白——有点估计与 Platt/isotonic 分类校准，但无 conformal/CQR/ACI 的分布无关预测区间，无 Liao 式预测标准误，无回归/排序的可靠图+ECE；(4) 集成仅隐含于 LGBM 内部，无显式 seed-averaging / 跨模型 stacking 模块；(5) regime 是规则式(ADX/vol-z)而非学习式(HMM/Markov-switching)或端到端 regime-gating；(6) M10 自认缺 live 漂移监控——而'when alpha breaks'式的 abstain/降级正是 conformal+regime 的杀手级应用；(7) 缺把 Avramov-Cheng-Metzker 式'扣成本/剔微盘/限套利'的经济约束鲁棒性检验做成标准闸门(M9 有交易成本执行，但未必有'去掉微盘后 alpha 还剩多少'的归因门)。

### 差距

- 模型表达力缺口：M6 只有 LGBM，缺神经网络(NN1-5)与经济约束型 ML 因子模型(autoencoder-APM/IPCA/GAN-SDF)。这是 GKX/Chen-Pelger-Zhu/Kelly-Pruitt-Su 三条主线，QuantBT 一条都没接。
- 不确定性量化(本主题核心)几乎空白：无 split/inductive conformal、无 CQR、无 ACI(非平稳)、无 Liao 式预测标准误。M7 只有分类用的 Platt/isotonic，没有给 magnitude 预测配分布无关的覆盖区间，也没有回归/排序的 reliability diagram + ECE。
- 缺'when alpha breaks'的安全部署机制：没有基于不确定性/regime 的 abstain(不交易)闸门；M10 自认缺 live 漂移监控。Sanderink 2026 的两级(aleatoric/epistemic)不确定性 + abstain 正是中低频实盘最该接的护栏。
- 集成是隐式的：无显式 seed-averaging(GKX 标配)与跨模型 stacking 模块；ensembling 的稳健性收益(尤其极端下行期)未被系统化。
- regime 是规则式而非学习式：M2 的 ADX/vol-z 阈值规则未升级到 HMM/Markov-switching 学习状态，也未做 regime-conditional 模型 gating 的端到端版本(Chen-Pelger-Zhu 的 RNN 状态提取)。
- 缺经济约束鲁棒性闸门：未把 Avramov-Cheng-Metzker 的诊断(扣交易成本、剔微盘/困境股、限套利状态后 alpha 还剩多少、换手与权重极端度)做成上线前必过的归因门——这是 ML alpha 最常见的'纸面 vs 可交易'陷阱。
- 调参与验证深度：缺 CPCV、缺 Optuna/Bayesian 超参搜索(MEMORY 自认)，hyperparameter 选择的稳健性与 PBO 的联动不充分。
- 复杂度争议未被显式管理：无机制去区分 virtue-of-complexity 的真实增益 vs 隐式正则化/不可交易换手；超参数化模型在 QuantBT 框架内既未提供也未设防。

### Agent OS 在这一环的角色（服务零代码用户）

这一环是 ML 资产定价——对零代码用户最危险也最需要'流程即信任'的一环，因为模型是黑箱、数字(R^2、Sharpe)极易自欺。Agent OS 应承担'把统计严谨翻译成经济学语言 + 用导轨防止用户被漂亮回测骗到'的双重职责：

1) 意图层(经济学者出判断)：需求澄清 agent 把'我觉得动量在牛市更有效'翻译成可检验假设——'在 regime=趋势 时，动量因子的横截面 IC 显著为正'，并自动登记为预注册假设(对接 M12 lineage)。用户永远只在'经济逻辑、go/no-go'层发声，不碰 LGBM/NN 超参。

2) 工程层(agent 出全部工程)：M14 reAct loop + M18 IDE 沙箱自动完成拉数→造特征→训模型→Purged-WF 验证→conformal 加区间→PBO/DSR 折扣。用户看到的不是代码，是一句话进度('我用 3 类模型做了无未来信息的滚动测试，并对预测加了诚实误差棒')。

3) 翻译层(严谨度→可懂可信)——这是关键。把每个机构级概念配一段经济学白话与一张图：
- 样本外 R^2/Sharpe → '这条策略在它从没见过的年份里赚钱了吗'，配净值图 + Bootstrap 置信带；
- Purged/Embargo → '我们假装站在过去某天，绝不偷看未来'，用时间轴动画展示;
- conformal 区间 → '模型说预期+2%，但诚实地讲它有80%把握落在[-1%,+5%]'，把区间宽度直接画成误差棒，宽=别下重注;
- reliability diagram/ECE → '模型说70%会涨的那些股，是不是真有约70%涨了'，一张校准曲线胜过千言;
- abstain('alpha breaks') → '现在市场状态像模型训练时从没见过的样子，我建议这段时间不按它交易'——这是非技术用户最能直觉信任的护栏；
- Avramov 诊断 → '这点超额收益，扣掉手续费、去掉小盘垃圾股之后还剩多少'，用瀑布图把 alpha 一层层剥给用户看。

4) 治理即信任：因为用户读不懂代码，唯一的信任支柱是流程留痕——预注册假设、不可变 dataset_version、谱系(parent/forked_from)、PBO/DSR 闸门红绿灯、模型卡(M12 ModelRegistry dev→staging→production)。Agent OS 要把这些做成'闯关式'体验：每过一道治理门给用户一个可读的'为什么这关重要 + 你的策略得了几分'，human-in-the-loop 只在审批门与资本配置处强制停下要用户点 go。M19 的苏格拉底教学 agent + Glossary L1-L4 渐进披露正好承接：小白看 L1('误差棒越宽越别重仓')，经济学者看 L3(conformal 覆盖保证的含义)。

### 建议

- 在 M7 信号层加一个分布无关的不确定性量化模块：对 magnitude 预测做 split/inductive conformal + CQR(包裹现有 LGBM/未来 NN)，输出预测区间；前端把区间宽度直接画成误差棒并接入 M19 白话('把握度')。这是本主题最高杠杆、对非技术用户最直觉的严谨度翻译。  `[→M7 信号 / M15 前端 / M19 教学, eff=med, lev=high]`
- 实现 ACI(Adaptive Conformal Inference)在线覆盖 + regime 触发的 abstain 闸门，做成'when alpha breaks'护栏：当 regime 偏离训练分布或覆盖率持续失守时自动降级/不交易，并接 M9 KillSwitch/M20 Live Ladder。中低频实盘最该有的安全机制。  `[→M2 Regime / M7 / M9 风控 / M10 live漂移 / M20, eff=med, lev=high]`
- 把回归/排序的概率校准证据补全：在 M7 现有 Platt/isotonic 之上加 reliability diagram + ECE 报告，并在 RunDetail 之外的模型卡页展示校准曲线(不动冻结的收益概述页)。低成本、直接提升'可信'。  `[→M7 / M12 模型卡 / M15, eff=low, lev=med]`
- 加显式集成模块：先做 seed-averaging(GKX 标配，对随机初始化取均值)，再做跨模型 stacking 元学习器。低工程量、文献一致证明稳健性收益(极端下行期尤甚)。  `[→M6 模型 / M8 组合, eff=low, lev=med]`
- 扩 M6 模型库到神经网络(NN1-5, GKX 架构)与经济约束型因子模型(先 IPCA 白箱降维，再 autoencoder-APM)。IPCA 性价比最高：白箱、可解释、降维对抗因子动物园，且自然产出'哪 10 个特征贡献近全部准确度'的经济叙事。GAN-SDF 列为后续研究项。  `[→M6 模型 / M4 因子, eff=high, lev=high]`
- 把 Avramov-Cheng-Metzker 经济约束鲁棒性做成上线前必过的归因门：自动复算'扣交易成本/剔微盘+困境股/限高套利状态'后 alpha 残值、换手率、权重极端度，用瀑布图呈现。直接防住 ML alpha 最常见的'纸面不可交易'陷阱。  `[→M9 执行成本 / M10 归因 / M11 生命周期门, eff=med, lev=high]`
- 把 Liao et al. 2025 的'预测标准误→不确定性厌恶收缩组合'接进 M8：用预测置信区间宽度作为组合权重的收缩/惩罚项(高不确定性标的降权)。把 UQ 从'展示'升级为'参与决策'，且有 JF 级理论背书。  `[→M8 组合 / M7, eff=med, lev=med]`
- 调参与验证深化：M6 加 CPCV 与 Optuna/Bayesian 超参搜索，且让超参选择结果直接喂 M10 的 PBO，量化'调参引入的过拟合'。同时为 virtue-of-complexity 类高参数模型设防——强制报告样本外稳健性与换手代价，不让复杂度争议悄悄进生产。  `[→M6 / M10 PBO, eff=med, lev=med]`

### 对抗式核查裁决 — 总体置信度：**high**

_纠正摘要_: All 13 cited papers are REAL and correctly attributed (authors, years, journals, core findings verified against primary sources, including full-text extraction of the GKX2020 and Chen-Pelger-Zhu PDFs). No fabricated or hallucinated references were found. Citation specifics confirmed: GKX2020 (RFS 33(5):2223-2273); Kelly-Xiu 'Financial Machine Learning' (NBER w31502, 2023, ~159pp in Foundations and Trends in Finance 13(3-4):205-363 — the '160 pages' claim is accurate); VoC (J.Finance 2024, jofi.13298 / NBER w30217); Chen-Pelger-Zhu (Management Science 2024, 70(2):714-750); Autoencoder APM (J.Econometrics 2021, 222(1):429-450); IPCA Kelly-Pruitt-Su (JFE 2019, 134(3):501-524); Avramov-Cheng-Metzker (Management Science 2023, 69(5):2587-2619); Liao et al (arxiv 2503.00549, 2025); ACI Gibbs-Candes (NeurIPS 2021, arxiv 2106.00170); CQR Romano-Patterson-Candes (NeurIPS 2019, arxiv 1905.03222); Guo et al (ICML 2017, PMLR v70); Harvey-Liu-Zhu (RFS 2016, 29(1):5-68); Bagnara (J.Economic Surveys 2024, 38:27-56). The skeptical critiques cited in the claims are also real and verifiable: Buncic 'Simplified...' (SSRN 5239006) and Capponi et al 'Nonstationarity-Complexity Tradeoff' (arxiv 2512.23596) for VoC; Zeng et al AAAI-2023 DLinear and the HuggingFace Autoformer rebuttal for Transformers.\n\nThree precision corrections, none fatal: (Claim 1) The 0.40% OOS R^2 is specifically NN3, while the 2.45 equal-weighted Sharpe is the abstract's general-NN figure that the body attributes to NN4 — do not treat them as one model; GKX itself flags microcap dependence of the EW result and presents the 1.35 VW figure as the cost-robust one, so the 'do not use 2.45 as tradeable' stance is correct and partly conceded by the authors. (Claim 5) The claim risks mislabeling: 9.3 Sharpe is explicitly IN-SAMPLE (paper says IS results 'suffer from overfitting'), but the 23% cross-sectional R^2 is the OUT-OF-SAMPLE headline; the model's actual OOS Sharpe is 2.6, not 9.3 — so the warning is right but the OOS comparator is 2.6. (Claims 2/3) Tighten scope: Buncic's documented rebuttal targets the zero-intercept restriction and aggregation scheme (turnover is a separate hypothesis, not his core finding); the DLinear-beats-Transformer evidence is on general TSF benchmarks, not directly financial returns. All six claims survive scrutiny as confirmed (1,3,4,6) or nuanced (2,5); none is refuted or outdated. The adversarial posture throughout (reject in-sample numbers, demand per-regime coverage, demand net-of-cost risk-adjusted validation of UQ) is methodologically correct and aligns with the cited counter-evidence.

被降权/纠正的论断：
- `nuanced` — Claim 2: 'Virtue of Complexity' (params > samples performs better) is a robust true signal in return prediction — flagged as substantively disputed (Buncic simplified replication; 2025 nonstationarity-complexity work); should not be treated as settled consensus for production.
  - 纠正：The claim's framing is correct. Minor precision: Buncic's critique is specifically about (a) zero-intercept restriction and (b) the aggregation scheme — not generically about 'high turnover'; the turnover/cost concern is a separate, reasonable but not yet the documented core of Buncic's rebuttal. Keep the turnover concern as a hypothesis to test, not as Buncic's finding.
- `nuanced` — Claim 5: Chen-Pelger-Zhu report in-sample Sharpe ~9.3 and cross-sectional R^2 ~23% — in-sample numbers must not be used for performance promises; separate IS vs OOS; check GAN training stability/reproducibility.
  - 纠正：The claim pairs 'in-sample Sharpe ~9.3 与 横截面 R^2~23%' which can mislead: the 9.3 Sharpe is in-sample, but the 23% cross-sectional R^2 is the paper's OUT-OF-SAMPLE result — do not label the 23% as in-sample. The relevant OUT-OF-SAMPLE Sharpe to compare against is 2.6 (vs 1.5 for the deep-learning forecasting benchmark, 1.7 for the linear special case), not 9.3. The core warning (never use 9.3 IS for performance promises) is correct.

---


## [13] 机构级组合构建与风险模型  · 组 D

**机构级标准** — 机构级组合构建不是"跑一个优化器出权重"，而是一条带治理闸门的流水线：(1) 风险模型与协方差估计——拒绝直接用样本协方差做优化（病态、Markowitz's curse），必须用 Ledoit-Wolf 线性/非线性收缩、RMT 去噪、或显式因子风险模型（Barra 风格：行业+风格因子暴露→因子协方差+特异风险），并做条件数/特征值/校准诊断；(2) 期望收益输入——区分"无 μ"路线（minimum-variance、risk parity/risk budgeting、HRP/NCO）与"有 μ"路线（Markowitz、Black-Litterman 把均衡先验与带不确定度的观点贝叶斯融合），机构默认不裸用历史均值做 μ；(3) 组合构造——把目标写成带显式约束的凸/分层问题：杠杆（gross/net）、单标的与行业上限、换手/交易成本惩罚、因子中性化（beta=0、风格/行业暴露归零）、回撤/CVaR 约束；(4) 资金/杠杆层——以 fractional Kelly（通常 ¼–½ Kelly）或波动率目标定杠杆，明确放弃 full Kelly；(5) 稳健性——优化前做 OOS/bootstrap、对输入扰动做敏感性，对比 1/N 基准（DeMiguel-Garlappi-Uppal 的硬基准）；(6) 治理——按 SR 11-7 三支柱（开发/独立验证/治理）：模型清单、独立验证、用途文档、持续监控（实盘暴露 vs 预期暴露漂移），把组合模型当"活产品"而非一次性脚本。关键判据：报告事前风险分解（因子/特异、边际风险贡献 MCTR）、事后归因（Brinson/因子归因）、净成本后的夏普，并能复现。


### 关键论文 / 权威实践

- **Building Diversified Portfolios that Outperform Out of Sample (Hierarchical Risk Parity)** ([链接](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2708678))
  - _Marcos López de Prado · 2016 · Journal of Portfolio Management 42(4)_
  - 提出 HRP：用层次聚类（tree clustering）→ 准对角化 → 递归二分配权，绕开协方差矩阵求逆，对病态/奇异协方差稳健，OOS 表现优于 MVO 与逆方差。是 QuantBT M8 hrp_weights 直接对应的方法。
- **A Robust Estimator of the Efficient Frontier (Nested Clustered Optimization, NCO)** ([链接](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=3469961))
  - _Marcos López de Prado · 2019 · SSRN working paper / 收录于 Machine Learning for Asset Managers (2020)_
  - 提出 NCO：先聚类协方差成簇，簇内分别做凸优化，再在'簇间缩减协方差'上做一次优化并相乘。把'Markowitz's curse'（高相关→优化不稳定）拆解为簇内/簇间两层，比 HRP 更接近 mean-variance 最优而保持稳健。区分 noise 与 signal 两类不稳定源。
- **Honey, I Shrunk the Sample Covariance Matrix** ([链接](http://www.ledoit.net/Honey_2004.pdf))
  - _Olivier Ledoit, Michael Wolf · 2004 · Journal of Portfolio Management 30(4)_
  - 线性收缩估计量：把样本协方差向结构化目标（常数相关/单指数）收缩，给出解析最优收缩强度。机构做组合优化的事实标准协方差输入。后续 (2004 JMVA well-conditioned、2012/2022 非线性收缩) 进一步用 Marčenko-Pastur 改特征值。
- **Asset and Factor Risk Budgeting: A Balanced Approach** ([链接](https://arxiv.org/abs/2312.11132))
  - _Adil Rengim Cetingoz, Olivier Guéant · 2023 (rev. 2024) · arXiv 2312.11132_
  - 把风险预算同时施加在资产层与因子层，定义直接关联因子暴露的、利于优化的风险度量，用随机优化算法对一般风险度量求解；正面处理'因子风险预算解不唯一/不可逆'的痛点。2023-24 risk budgeting 的前沿代表作。
- **Optimal Versus Naive Diversification: How Inefficient Is the 1/N Portfolio Strategy?** ([链接](https://academic.oup.com/rfs/article-abstract/22/5/1915/1592901))
  - _Victor DeMiguel, Lorenzo Garlappi, Raman Uppal · 2009 · Review of Financial Studies 22(5)_
  - 14 个 mean-variance 及其降噪扩展在 7 个数据集上，没有一个能在夏普/确定性等价/换手上一致打败 1/N。确立了'估计误差吃掉最优分散收益'的硬基准——任何组合优化都必须先证明它打得过等权。
- **Global Portfolio Optimization (Black-Litterman)** ([链接](https://www.cfainstitute.org/en/research/financial-analysts-journal/1992/global-portfolio-optimization))
  - _Fischer Black, Robert Litterman · 1992 · Financial Analysts Journal 48(5)_
  - 用市场均衡（反向优化）做先验 μ，把投资者带不确定度的观点贝叶斯融合得到后验 μ 再优化，根治裸历史均值导致的极端/不稳定权重。机构 TAA/SAA 默认框架。
- **Uncertainty in the Black-Litterman Model: A Practical Note** ([链接](https://www.econstor.eu/handle/10419/202070))
  - _Adrian Fuhrer, Thorsten Hock · 2023 · EconStor working paper_
  - BL 最难的两个参数（标量 τ、观点不确定度 Ω）数据驱动地参数化，并给出可反向解读的判断式设定，降低 BL 的'调参玄学'，是 2023 让 BL 更可落地的实务工作。
- **Introducing Expected Returns into Risk Parity Portfolios** ([链接](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2321309))
  - _Thierry Roncalli · 2013/2015 · SSRN / Bankers, Markets & Investors_
  - 把期望收益引入 risk parity/risk budgeting 的统一框架，连同其专著《Introduction to Risk Parity and Budgeting》给出 ERC（等风险贡献）与一般风险预算的求解与性质，是 risk budgeting 的权威参考。
- **Multi-Period Trading via Convex Optimization** ([链接](https://web.stanford.edu/~boyd/papers/pdf/cvx_portfolio.pdf))
  - _Stephen Boyd, Enzo Busseti, Steven Diamond, Ronald Kahn 等 · 2017 · Foundations and Trends in Optimization_
  - 交易成本/持有成本感知的多期凸优化统一框架（含 cvxportfolio 开源实现），把换手惩罚、市场冲击、约束写进目标，是交易成本感知优化的工程标准。
- **Differentiable Convex Optimization Layers (cvxpylayers)** ([链接](https://arxiv.org/abs/1910.12430))
  - _Agrawal, Amos, Barratt, Boyd, Diamond, Kolter · 2019 · NeurIPS 2019_
  - 可微凸优化层：把组合优化嵌进神经网络端到端训练（预测-优化一体化）。是 emerging 的 end-to-end portfolio 路线（如 deepdow、Deep Declarative Risk Budgeting 2025）的技术底座。
- **Non-linear shrinkage of the price return covariance matrix is far from optimal for portfolio optimization** ([链接](https://www.sciencedirect.com/science/article/abs/pii/S1544612322005608))
  - _Christian Bongiorno, Damien Challet · 2022 · Finance Research Letters_
  - 对非线性收缩的对抗性证据：在非平稳依赖结构下，理论最优的非线性收缩并不最小化组合优化真正关心的代价函数，'数学最优'≠'组合最优'。是 contested 一栏的关键反方。

### SOTA 方法

- **Ledoit-Wolf 线性/非线性协方差收缩 + RMT 去噪** `[established]` — 把样本协方差向结构化目标收缩（线性）或按 Marčenko-Pastur 改造特征值（非线性/去噪），作为任何 MVO/BL/risk budgeting 的输入。线性收缩与 RMT 去噪是 established；'非线性一定更好'在非平稳市场被 Bongiorno-Challet 等质疑。
- **HRP（Hierarchical Risk Parity）** `[established]` — 聚类→准对角化→递归二分；不需求逆、不需 μ，对病态协方差稳健。已是机构与开源（riskfolio-lib/skfolio/mlfinlab）标配。QuantBT 已实现。
- **NCO（Nested Clustered Optimization）** `[established]` — 簇内+簇间两层凸优化，比 HRP 更逼近 MVO 最优同时抗 Markowitz's curse。已有多家开源实现与独立复现（如墨西哥/拉美市场），趋于成熟但不如 HRP 普及。
- **Black-Litterman（含数据驱动的不确定度参数化）** `[established]` — 均衡先验+带不确定度观点的贝叶斯融合，是有 μ 路线的机构默认框架；2023 Fuhrer-Hock 等让 τ/Ω 参数更可落地。框架 established，参数设定仍有实务争议。
- **Risk budgeting / ERC + 资产-因子双层风险预算** `[established]` — 按预设风险贡献分配（ERC 为等贡献特例），Roncalli 体系成熟；Cetingoz-Guéant (2023) 把预算同时下到因子层并解决解不唯一，属前沿延伸。
- **CVaR / 分布鲁棒优化（DRO，Wasserstein/矩/regime-switching 模糊集）** `[emerging]` — 用 CVaR 替代方差捕捉尾部，DRO 在模糊集上做最坏情形优化。Rockafellar-Uryasev 的 CVaR LP 已 established；DRO（Wasserstein、regime-switching 模糊集、cardinality 约束）是活跃 emerging 研究。
- **Fractional Kelly / 增长最优 + 回撤约束的杠杆定盘** `[established]` — 用 ¼–½ Kelly 或带回撤/leverage 约束的数值 Kelly 定杠杆，明确放弃 full Kelly。理论 established，'最优分数'与多资产估计仍有实务争议（依赖采样频率与尾部）。
- **交易成本感知多期凸优化（Boyd/cvxportfolio 风格）** `[established]` — 把换手惩罚、市场冲击、持有成本写进多期目标。Baldi-Lanfranchi (2024) 进一步证明很多因子'税后/费后'夏普转负——成本必须进优化而非事后扣。
- **End-to-end 预测-优化一体化（differentiable / declarative layers）** `[emerging]` — 用 cvxpylayers 把优化器做成可微层，让预测模型按最终组合效用而非预测精度训练（deepdow、Deep Declarative Risk Budgeting 2025）。新颖、potential 大，但稳定性/可解释性/过拟合风险未被机构充分接受。
- **因子中性化 / beta 中性 / 风格暴露归零（特征组合）** `[contested]` — 在优化里加 beta=0、行业/风格暴露=0 的线性约束以隔离纯 alpha，是市场中性/统计套利标准做法。established，但'中性化多少因子、是否过度中性化掉 alpha'是策略层判断而非定论。

### 最佳实践

- 协方差永远先收缩/去噪再优化，绝不裸用样本协方差；并记录条件数/特征值诊断。
- 默认不裸用历史均值做 μ：要么走无 μ 路线（min-var / risk budgeting / HRP），要么用 Black-Litterman 把均衡先验与带不确定度的观点融合。
- 把约束写成显式凸约束（杠杆 gross/net、单标的与行业上限、换手/成本惩罚、beta/风格中性、回撤/CVaR），而不是事后裁剪。
- 杠杆用 fractional Kelly（¼–½）或波动率目标，明确放弃 full Kelly；与回撤护栏联动。
- 交易成本进优化目标，报告费后/换手后指标，避免高估净收益（中低频也要做）。
- 每个组合都并列 1/N 与 HRP 基准、做输入 bootstrap 敏感性，证明'优化值得'再用优化。
- 输出事前风险分解（因子 vs 特异、成分风险贡献 MCTR）+ 事后归因（Brinson/因子），让风险来源可见。
- 按 SR 11-7 三支柱治理组合模型：模型清单、独立验证（与开发隔离）、上线后实盘暴露 vs 预期暴露漂移监控；把组合模型当活产品。
- 资产无关：因子风险模型、约束、成本模型都用配置驱动，让股/期货/FX/可转债靠填配置接入而非重写优化器。

### QuantBT 现状

M8 已实现 4 个优化器：equal_weight、mean_variance（scipy SLSQP 二次型，max μᵀw−λ/2 wᵀΣw，sum=1，可选 short）、risk_parity（实为逆波动率 1/σ，未用相关性，非真 ERC）、hrp_weights（正确的 López de Prado 2016 三步 HRP：聚类→准对角化→递归二分）。约束模块 constraints.py 支持单标的上限、行业上限、强相关二选一、gross 杠杆归一。协方差由调用方传入、M8 内未见收缩/去噪。GOAL 自标注'缺 BL/CVaR/Kelly'。即：稳健无 μ 路线有 HRP（强项），但缺 NCO、缺协方差收缩、risk_parity 命名失真；有 μ 路线只有裸 μ 的 Markowitz、无 BL；无尾部/鲁棒目标（CVaR/DRO）、无 Kelly 杠杆定盘、无交易成本感知优化、无 Barra 式因子风险模型与因子中性化/事前风险分解、无'打过 1/N'治理闸门。下游 M10 已有 PBO/DSR/Bootstrap Sharpe CI/Brinson 归因可复用做组合层稳健性与归因。

### 差距

- 协方差输入未做收缩/去噪：M8 optimizers.py 直接吃传入的 covariance 做 mean_variance/HRP，代码层看不到 Ledoit-Wolf 收缩或 RMT 去噪。这正是 DeMiguel 等指出的'估计误差吃掉最优分散'的入口，机构级缺一不可。
- risk_parity 不是真 risk parity：当前实现是权重 ∝ 1/σ（逆波动率），忽略相关性，不等于等风险贡献（ERC）。真 ERC 需解 wᵢ·(Σw)ᵢ 相等的非线性方程组。这是命名与机构标准的实质偏差。
- 无 Black-Litterman：mean_variance 直接吃传入的 expected_returns（裸 μ），没有均衡先验+观点融合层，极易产生极端/不稳定权重，正是 BL 要解决的问题。GOAL §M8 自己标注'缺 BL'。
- 无 CVaR / 鲁棒/分布鲁棒优化：只有方差目标，无尾部风险目标，无对输入不确定的最坏情形保护。GOAL §M8 标注'缺 CVaR'。
- 无 (fractional) Kelly / 杠杆与回撤联动定盘：杠杆只在 constraints 里做 gross 上限+归一，没有按增长最优或波动率目标'决定该用多少杠杆'的层；GOAL §M8 标注'缺 Kelly'。回撤控制（M9 RiskMonitor 有日内亏损护栏）未进入组合构造目标。
- 无交易成本感知优化：constraints 里没有换手/成本惩罚项，优化与成本/换手脱钩；这与 2024 Baldi-Lanfranchi'费后夏普'警示直接冲突，中低频虽不致命但会系统性高估净收益。
- 无显式因子风险模型 / 因子中性化：没有 Barra 风格的因子暴露→因子协方差+特异风险分解，因而无法做事前因子风险分解、beta 中性、风格/行业暴露归零这类机构标准约束（M4 有 IC/因子但未接入组合层的风险归因）。
- 无 NCO：已有 HRP 但没有 López de Prado NCO 这条更逼近 MVO 最优的稳健路线。
- 无组合层的稳健性/对抗证据：没有把 1/N 当默认基准强制对比、没有对协方差/μ 输入做 bootstrap 敏感性，缺'优化是否真的打得过等权'的闸门——这是 DeMiguel 基准要求的最低门槛。
- 缺事前风险分解报告：未见 MCTR（边际/成分风险贡献）、因子 vs 特异风险拆分的输出，非程序员用户无法'看懂自己组合的风险来自哪'。

### Agent OS 在这一环的角色（服务零代码用户）

这一环对零代码用户最危险也最适合 Agent OS 托管：组合优化是'看起来给了一个权威数字、实则极度依赖看不见的输入假设'的黑箱，小白/经济学者既无法判断协方差是否病态，也读不懂 SLSQP。Agent OS 的角色是把'选哪个优化器/怎么定杠杆'这类工程决策自主完成，但把每一步翻成经济学语言+流程闸门让人做 go/no-go：(1) 需求澄清 agent 把'我想要稳健分散'澄清成可检验目标——问'你更怕大跌（→CVaR/回撤约束）还是怕跑输基准（→跟踪误差/BL 观点）？能接受多大杠杆？'，落成结构化约束而非让用户填 risk_aversion=λ。(2) 自动护栏：默认强制 Ledoit-Wolf 收缩、默认 fractional（如 ½）Kelly 而非 full、默认把 1/N 当并列基准回测——把机构最佳实践设成不可绕过的缺省，小白即使什么都不改也站在安全侧。(3) 严谨度翻译三件套：把权重输出旁边永远配①风险归因图（'你 60% 的风险来自科技板块/动量因子'，用 MCTR）②'对比等权'一句话结论（'优化版费后夏普 0.9 vs 等权 0.85，差异在 bootstrap 区间内不显著→建议用更简单的等权'，直接引用 DeMiguel 的逻辑）③输入敏感性（'若你的预期收益估计偏差 1%，权重会这样变'）。(4) 流程即信任：用 SR 11-7 三支柱给非程序员可读的信任锚——这个组合模型用了哪版协方差/哪些约束（开发）、是否通过了'打过等权+OOS 不崩'的独立验证闸门（验证）、上线后实盘因子暴露 vs 预期是否漂移（治理监控）。用户读不懂代码，但能读懂'这条产品线过了哪几道闸、谁批准的、现在偏没偏'。经济学者尤其吃 BL 这套'你的观点+市场均衡=后验'的叙事，应作为有 μ 路线的默认入口让他只出观点与置信度。

### 建议

- 在 M8 协方差入口接 Ledoit-Wolf 线性收缩（sklearn LedoitWolf 或自实现常数相关目标）+ 可选 RMT 去噪，并默认开启；mean_variance/HRP/NCO 共用。附条件数/特征值诊断写进 run 元数据。这是单点改动撬动全部下游优化稳健性的最高杠杆项。  `[→M8 (optimizers/新建 covariance.py), eff=low, lev=high]`
- 把当前误命名的 risk_parity（1/σ）升级为真 ERC（等风险贡献，数值解 wᵢ(Σw)ᵢ 相等），并新增一般 risk budgeting（可指定风险预算向量），保留旧逻辑为 inverse_vol 选项。命名与机构标准对齐，避免误导。  `[→M8 (optimizers), eff=med, lev=high]`
- 新增 Black-Litterman 层：反向优化求均衡先验 → 接收用户/Agent 的观点矩阵 P、观点收益 Q、置信度 Ω → 后验 μ 喂给 mean_variance。Agent OS 让经济学者只填'我看多 A 相对 B、置信度中'，τ/Ω 用数据驱动缺省（Fuhrer-Hock 2023 思路）。  `[→M8 (新建 black_litterman.py) + M14 (观点 slot filling), eff=high, lev=high]`
- 新增 NCO（簇内+簇间两层优化），与 HRP 并列；复用现有 hrp 的聚类代码。给稳健路线再加一个更逼近 MVO 最优的选项，工程边际成本低。  `[→M8 (optimizers), eff=low, lev=med]`
- 新增 CVaR 目标（Rockafellar-Uryasev LP 形式，用 scipy.linprog 或 cvxpy）作为可选 objective，给'怕大跌'的用户用尾部风险而非方差。后续可扩 Wasserstein DRO，但先把 CVaR 这条 established 路落地。  `[→M8 (optimizers), eff=med, lev=med]`
- 把杠杆从'仅 gross 上限'升级为 fractional Kelly / 波动率目标定盘：根据估计的 μ/Σ 算 Kelly 分数，默认乘 0.25–0.5 并受 leverage_max 与回撤约束封顶；与 M9 RiskMonitor 的回撤护栏联动。默认 fractional 是关键安全缺省。  `[→M8 (sizing) + M9 (RiskMonitor 联动), eff=med, lev=high]`
- 在 constraints/目标里加交易成本与换手惩罚项（线性+可选平方冲击），并把'费后/换手后'指标接进 M10 回测报告；引用 Baldi-Lanfranchi 警示。中低频下这是防止系统性高估净收益的必需项。  `[→M8 (constraints/objective) + M10 (净成本指标), eff=med, lev=med]`
- 接入因子风险模型 + 因子中性化约束：用 M4 已有因子做 Barra-lite 暴露矩阵 → 因子协方差+特异风险，支持 beta=0 / 风格暴露上限 / 行业中性的线性约束，并输出事前风险分解（因子 vs 特异、MCTR）。让市场中性策略可落地、让用户看懂风险来源。  `[→M8 (factor_risk.py) + M4 (因子暴露) + M10 (风险归因), eff=high, lev=high]`
- 设'优化必须打过 1/N'闸门：每次组合构造自动并列回测等权基准 + 对 μ/Σ 输入做 bootstrap 敏感性，若优化版费后夏普在区间内不显著优于等权则 Agent OS 主动建议降级到等权/HRP。把 DeMiguel 基准做成默认治理闸门。  `[→M8 + M10 (bootstrap CI 已有可复用) + M14 (建议输出), eff=med, lev=high]`
- 把组合模型纳入 SR 11-7 式治理可读层：在 M12 注册表记录'本组合用的协方差版本/优化器/约束/杠杆策略'，M11 生命周期挂'实盘因子暴露 vs 预期暴露漂移'监控，前端给非程序员可读的'开发/验证/治理'三支柱状态卡。这是把严谨度翻成信任的落点。  `[→M12 (注册表) + M11 (漂移监控) + M15 (信任卡片), eff=med, lev=high]`

### 对抗式核查裁决 — 总体置信度：**high**

_纠正摘要_: 全部 12 篇所引论文均真实存在且方法描述基本准确，无虚构。两处年份/标题问题须修正：(1) Fuhrer-Hock 'A Practical Note' 实为 2019(econstor 10419/202070)而非引用所写的 2023——2023 是同主题但不同副题的另一篇期刊文 'Empirical estimation of the equilibrium'(J. Empirical Finance 72);(2) López de Prado NCO 应为 2019(SSRN 3469961)，勿采信个别聚合页的 2016 误植。六条论断中:论断 4、5、6 confirmed(经验法则/CVaR 过拟合/过度中性化均有文献支撑);论断 1 confirmed(HRP 优势非普适、独立复现混杂属实);论断 2 nuanced——Bongiorno-Challet 确实反驳了非线性收缩的最优性，但论文开的处方是'修正最优目标'而非'退回线性收缩'，'默认线性收缩'是合理的工程保守选择但不应表述为该论文的直接背书;论断 3 nuanced——DGU(2009)是真实且重要的'打不过 1/N'硬基准，但'反复证否优化'被夸大方向相反:Kirby-Ostdiek(2012)、Tu-Zhou(2011) 已部分反驳，指出 DGU 结论部分源于研究设计劣势。论断 3 的实操处方(在本项目 A股/加密数据上做 bootstrap 显著性检验、未显著则默认等权/HRP)是正确的中立处置。整体方向(默认怀疑'优化必胜'、坚持用项目自有数据费后实测、加密用更低 Kelly、中性化交人判断)与文献一致且稳健。

被降权/纠正的论断：
- `nuanced` — 论断2: 'Ledoit-Wolf 非线性收缩优于线性' 被 Bongiorno-Challet (2022) 直接反驳；应默认用更稳的线性收缩/去噪而非盲目上非线性方法。
  - 纠正：论文反驳的是 NLS 的最优性，但开的处方是'修正最优目标'而非'退回线性收缩'。在加密这类高非平稳市场，'默认线性收缩/去噪'是合理且更稳的工程缺省，但应表述为实务保守选择，不要写成 Bongiorno-Challet 的直接背书。
- `nuanced` — 论断3: '组合优化能打过 1/N' 被 DeMiguel-Garlappi-Uppal 反复证否；必须用本项目自己 A股/加密数据实测优化版费后夏普是否在 bootstrap 区间内显著优于等权。
  - 纠正：DGU 是'硬基准'而非'定论证否优化无用'——它已被 Kirby-Ostdiek(2012)、Tu-Zhou(2011) 部分反驳。所以论断的实操结论(在本项目 A股/加密数据上做 bootstrap 显著性检验、未显著则默认等权/HRP)恰恰是正确的中立处置；但不要把 'DGU 证否了组合优化' 当成终局定论写进文案。
- `outdated` — 所引论文: Uncertainty in the Black-Litterman Model: A Practical Note (Fuhrer-Hock 2023)。
  - 纠正：若指 'A Practical Note'(econstor 10419/202070)应标 2019；若想引 2023 成果，应改引 'Empirical estimation of the equilibrium'(J. Empirical Finance 72, 2023)并更新标题。

---


## [14] 中低频最优执行 & TCA（排除HFT）  · 组 D

**机构级标准** — 机构级中低频执行与 TCA 的标准是一条闭环，而非单点：(1) 事前(pre-trade)成本预测——用经过校准的市场冲击模型(平方根律为业界主流)对每张拟交易订单给出预期成本与置信区间，作为是否/如何交易的决策输入；(2) 事中执行——把母单(metaorder)拆成子单，按 Almgren-Chriss 风格在"冲击成本 vs 价格风险"间求最优 schedule，落到 VWAP/TWAP/POV/IS 等可审计算法，并明确排除 HFT/做市/微秒级订单簿博弈；(3) 事后(post-trade)TCA——以 implementation shortfall(Perold 的到达价基准)为黄金基准，把总成本分解为 spread/延迟/市场冲击/择时/机会成本，并对算法和经纪商做基准化排名；(4) 成本模型治理——用真实成交回灌(live fills)持续重标定冲击/滑点参数，监控回测预期 vs 实盘的成本漂移；(5) 容量(capacity)估计——把冲击成本叠加到 alpha 上，求"边际 alpha 跌破阈值"的 AUM 上限，作为资本配置与策略退役的硬约束。关键纪律:同一套成本模型必须在回测、模拟、实盘三处一致使用(零成本/仅费率回测会系统性高估收益)；成本须 side-aware、含借券/资金费率/印花税等品类特异项；冲击是 size 与参与率的非线性函数(不能用一个 flat bps 假装)。学术与买方共识(Frazzini-Israel-Moskowitz)同时提醒:从日内/日频公开数据推的冲击常被高估，真实大型基金的执行成本可显著低于文献——因此校准必须基于自有成交数据而非纸面公式。


### 关键论文 / 权威实践

- **Optimal Execution of Portfolio Transactions** ([链接](https://www.smallake.kr/wp-content/uploads/2016/03/optliq.pdf))
  - _Robert Almgren, Neil Chriss · 2000 · Journal of Risk 3(2)_
  - 执行调度的奠基论文：在永久冲击+临时冲击+价格风险的均值-方差框架下求最优清算轨迹，给出风险厌恶 lambda 决定的有效前沿(efficient frontier of trading)。是 implementation shortfall 算法、VWAP/POV 偏离的理论母体，至今所有执行算法的基线。
- **Trading Costs of Asset Pricing Anomalies** ([链接](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2294498))
  - _Andrea Frazzini, Ronen Israel, Tobias J. Moskowitz · 2018 (working paper since 2012) · AQR working paper / SSRN_
  - 用 AQR 自有约 1.7 万亿美元、19 年、21 个发达市场近 1 万只股票的真实成交数据测量 size/value/momentum/反转策略的实际交易成本。核心结论:真实成本远低于文献用公开数据推算的值、可承载的基金规模高一个数量级以上；冲击随交易规模呈凹(concave)增长。机构级容量与成本校准的标杆实证。
- **Dynamic Trading with Predictable Returns and Transaction Costs** ([链接](https://www.nber.org/papers/w15205))
  - _Nicolae Garleanu, Lasse Heje Pedersen · 2013 · The Journal of Finance 68(6), 2309-2340_
  - 成本感知的多期组合优化闭式解:最优组合是当前持仓与'aim portfolio'(当前 Markowitz 目标与未来期望目标的加权)的线性组合，原则是'瞄准目标前方、部分向目标移动'，alpha 衰减越慢的信号在 aim 中权重越大。把交易成本从'事后扣减'升级为'组合构建的内生约束'(连接 M8 组合与 M9 执行)。
- **Slow Decay of Impact in Equity Markets: Insights from the ANcerno Database** ([链接](https://arxiv.org/abs/1901.05332))
  - _Frederic Bucci, Michael Benzaquen, Fabrizio Lillo, Jean-Philippe Bouchaud · 2019 · Market Microstructure and Liquidity / arXiv:1901.05332_
  - 用 800 万+机构母单实证冲击的'缓慢衰减':母单结束当日冲击衰减到峰值约 2/3，随后按幂律继续衰减、约 50 天后收敛到首日末约 1/2 的非零渐近值。需对母单符号的多日自相关做反卷积才能提取孤立母单的真实衰减。直接含义:冲击不是瞬时回吐的，永久成分被低估会高估容量。
- **Market Impact: Empirical Evidence, Theory and Practice** ([链接](https://arxiv.org/abs/2205.07385))
  - _Emilio Said · 2022 · arXiv:2205.07385 (PhD thesis-style review)_
  - 系统综述平方根律的实证、理论与落地实践:冲击约为 Y*sigma*sqrt(Q/V)(Y 量级 ~0.5-1，sigma 日波动率，Q/V 母单占日成交量比)，并讨论小规模下向线性的 crossover、执行后的回吐(reversion)、以及如何从执行数据校准。连接冲击建模到 TCA 与容量的实务桥梁。
- **The two square-root laws of market impact and the role of sophisticated market participants**
  - _B. Toth, J.-P. Bouchaud 等 (CFM 团队相关) · 2023 · arXiv:2311.18283_
  - 近期对平方根律的再审视，区分元订单层面与市场层面两类平方根标度，并探讨知情/复杂参与者对标度律的影响。属于 emerging/contested 前沿，提醒平方根律的'普适性'有适用边界。(贡献描述基于检索结果，建议落地前核对正文)
- **A Bayesian theory of market impact** ([链接](https://arxiv.org/abs/2303.08867))
  - _Louis Saddier, Matteo Marsili 等 · 2023 · arXiv:2303.08867_
  - 用做市商在微结构噪声下对隐藏母单做贝叶斯更新的视角，自然推导出冲击对累计成交量的平方根依赖，并解释小量到线性的 crossover 与执行后回吐。为平方根律提供了一个信息论/贝叶斯的微观基础(emerging)。

### SOTA 方法

- **平方根冲击律 (square-root market impact law)** `[established]` — 母单冲击 ≈ Y·σ·sqrt(Q/V)：成本随规模呈凹增长，且近似独立于执行总时长 T 与子单数 N(只取决于总量)。是当前事前成本预测与容量估计的业界主流参数化。established，但其'普适性'与精确指数(0.5 vs 文献中 3/5 或对数依赖)属 contested。
- **Almgren-Chriss 最优执行调度** `[established]` — 永久+临时冲击与价格风险的均值-方差最优轨迹，风险厌恶 lambda 控制激进度，给出 IS 类算法与执行有效前沿。是所有执行算法的基线母体。
- **Implementation Shortfall TCA 分解** `[established]` — 以 Perold 到达价(arrival/decision price)为基准，把总成本拆为点差、延迟、市场冲击、择时、机会成本(未成交);并做算法/经纪商基准化排名(含贝叶斯排名以处理样本噪声)。buy-side 黄金标准基准。
- **VWAP / TWAP / POV(参与率) 执行算法** `[established]` — 确定性/跟量调度;POV 锁定占市成交比例。中低频策略落地执行的标准件，TCA 以它们为对照基准。established。
- **Propagator / transient-impact 模型 (Bouchaud-Gatheral)** `[emerging]` — 把每笔成交的冲击建为带衰减核(decay kernel)的传播子，可同时复现平方根律与冲击的瞬态/缓慢衰减，并在 no-dynamic-arbitrage 约束下保证无动态套利。比 A-C 的两段式冲击更贴合实证衰减结构。emerging→established 边界，机构研究常用但工程落地门槛较高。
- **成本感知多期组合优化 (Garleanu-Pedersen 'aim portfolio')** `[established]` — 把交易成本与 alpha 衰减速度内生进组合构建:慢衰减信号权重更高、部分向目标移动。比'先组合再扣成本'更优,直接连接 M8↔M9。established(理论),买方落地中。
- **深度强化学习执行 (DRL: Double-DQN / PPO over LOB)** `[contested]` — 用 LOB 状态学子单下单策略，文献报告相对 VWAP/A-C 有小幅(常 <0.1%~10% IS)改进，多在仿真(ABIDES)或单一资产验证。对中低频价值有限、过拟合与不可解释风险高、对非程序员是黑箱。contested。
- **容量估计 (capacity = 边际 alpha 跌破阈值的 AUM)** `[established]` — 把冲击成本叠加 alpha 求边际净 alpha=阈值的 AUM 上限;对冲击模型假设极敏感(slow-decay 会把容量估计降几个数量级;3/5 幂律 vs 平方根给出不同上限)。方法成熟但结论高度依赖输入,属 established 框架 + contested 参数。
- **Crypto 永续执行成本建模 (funding + slippage + fee 一致回测)** `[emerging]` — 在回测中对带符号名义按 8h 资金费率计 funding、按周转计费率与滑点;实证表明忽略这些会系统性高估年化收益。crypto 特异但方法直接。emerging(规范化中)。

### 差距

- 冲击模型声明了但没接线:StrategyGoal 的 EquityCostModel/CryptoSpotCostModel/CryptoPerpCostModel 都有 impact_model:Literal['fixed','linear','sqrt','orderbook']，但 BacktestVenue._cost_for_trade(backtest_venue.py:187) 只对名义乘一个 flat slippage_bps，完全无视 impact_model、订单规模、参与率、ADV——即平方根/线性/订单簿冲击全是死字段。这是最关键的 gap:成本与交易规模无关，等于假设无限流动性，会系统性高估大规模/高换手策略收益。
- 无 size/参与率依赖的市场冲击:没有 ADV(日均成交量)或 Q/V 输入，无法实现 Y·σ·sqrt(Q/V)。当前模型下,1 万美元和 1 亿美元同一笔交易的 bps 成本完全相同,与 Frazzini-Israel-Moskowitz 与平方根律的核心实证相悖。
- 无执行调度/算法:没有 Almgren-Chriss 最优轨迹,没有 VWAP/TWAP/POV 子单拆分与跟量撮合。BacktestVenue 只支持 next_bar_open/vwap/limit_sim 的单步整单成交,母单一次性吃 open 价,无法回答'这笔单该用多久、拆几片、占市多少'。
- 无 implementation shortfall TCA 分解:run 详情有成本数字,但没有以到达价为基准把总成本拆成 spread/延迟/冲击/择时/机会成本,也没有算法/经纪商基准化。事后 TCA 缺位,无法闭环校准。
- 容量估计缺位:StrategyGoal.capacity_usd 只是一个用户填的上限数字,系统不据冲击模型反算'边际 alpha 跌破阈值的 AUM',也不把容量作为资本配置/退役的闸门。slow-decay/3-5 幂律敏感性更无从谈起。
- 借券与资金费率未在回测撮合中消费:CryptoPerpCostModel.borrow_bps_per_day / funding_rate_apply / EquityCostModel 印花税虽在 schema,但 BacktestVenue 只用了 commission/slippage/stamp/transfer,funding/borrow 未按持仓时长×带符号名义计提;cost_drift 监控里 funding 是另一处硬编码 expected_funding_bps_per_day=3.0,与回测口径不一致——回测/实盘成本模型未真正统一。
- 成本模型未用真实成交回灌重标定:cost_drift.py 能算实盘 vs 回测的周度偏差并在 >30% 时告警,但没有自动把实盘成交校准回冲击模型参数(Y、衰减、按 symbol/regime 分层),仍是固定预设;无贝叶斯/分层校准。
- 无冲击衰减/价格回吐建模:Bucci 等的 slow-decay(执行后约 1/2 永久残留)未建模,回测假设冲击瞬时,既高估容量又错配多日换手策略的真实成本。

### Agent OS 在这一环的角色（服务零代码用户）

这一环对零代码用户最危险,因为'看不见的成本'会让漂亮的回测在实盘崩塌,而小白与经济学者恰恰读不懂 bps、参与率、平方根律。Agent OS 的职责是把执行/成本从'引擎里的隐藏假设'变成'看得见、能问、能签字的经济决策':(1) 翻译为经济语言——不说'slippage_bps=5、impact_model=sqrt',而说'你这个策略每月要换手 3 次、每次买卖约占该股一天成交量的 8%。按机构通用的平方根冲击规律,你越想快越想大,买的时候就越会把价格自己推高——预计单边吃掉约 X% 收益;如果你把规模翻 4 倍,成本不是翻 4 倍而是翻约 2 倍(凹性),但你的策略 alpha 撑不住,见下方容量上限'。(2) 容量即护栏——agent 主动算出'这个策略最多能管约 Y 元,超过后每多投 1 块钱的边际净收益就低于你设的门槛',并把它做成 human-in-the-loop 的 go/no-go 卡:超容量必须人来批,符合硬约束4(经济判断与风控 human-in-the-loop)。(3) 流程即信任——把'事前预测→选执行算法→回测含真实冲击→事后 TCA 对比→成本漂移监控→按实盘重标定'做成一条可视化的导轨,每一步留谱系(用了哪个冲击模型、Y 取多少、依据哪批成交校准),让读不懂代码的人靠'可复现+谱系+闸门'信任结果。(4) 渐进披露——小白只看一句话结论(红/黄/绿:成本是否吃光 alpha)+ 一个容量数字;经济学者展开看冲击曲线、IS 分解瀑布图、与 Frazzini-Israel-Moskowitz/平方根律的对照;quant 才下钻到参数与校准日志。(5) 资产无关——执行算法与冲击模型按品类填配置(股票用 ADV+印花税、crypto perp 用 funding+8h、期货用 tick/合约乘数),agent 据 asset_class 自动挑模型,而非让用户选;这正是把硬约束1(资产无关)落到执行环。最关键的诚实:agent 必须主动告诉用户'平方根律与容量都是估计、且文献对真实成本是高估还是低估有争议(AQR 说常被高估)',而不是给一个假精确的数字——这是非程序员能否真正信任的分水岭。

### 建议

- 把已声明的 impact_model 真正接线到 BacktestVenue:实现 sqrt 冲击 cost = Y·σ·sqrt(Q/ADV)·notional(临时冲击),Y 默认 ~0.5 可配,ADV 从已有面板数据估;linear/fixed 作降级档,orderbook 用真实盘口(crypto 有)。这是把'无限流动性假设'修正为机构标准的第一刀,杠杆最高。  `[→M9 (execution/backtest_venue.py) + M3 (ADV/成交量字段), eff=med, lev=high]`
- 新增 implementation shortfall TCA 分解模块:以母单到达价为基准,把每个 run 的成本拆为 spread/延迟/市场冲击/择时/机会成本,产出瀑布图;run 详情'收益概述'页受冻结约束,故新建独立 TCA 子页而非改概述页。  `[→M10 (回测&归因) + M15 (新 TCA 前端页), eff=med, lev=high]`
- 实现容量估计器:给定冲击模型,数值求解'边际净 alpha = 用户阈值'的 AUM 上限,并做对冲击假设(平方根 vs 3/5 幂律、瞬时 vs slow-decay)的敏感性区间;把超容量做成 human-in-the-loop go/no-go 闸门接入审批门。  `[→M8/M9 (capacity) + M12/审批门 + M2(regime 分层), eff=high, lev=high]`
- 在回测撮合中真正消费 funding/borrow/印花税:按带符号名义×持仓时长计 8h 资金费率与日借券费,A股卖出计印花税;并让 cost_drift.py 与 venue 共用同一 cost_model 口径(消除当前 funding=3.0 硬编码的双口径不一致)。  `[→M9 (backtest_venue + monitor/cost_drift.py), eff=low, lev=med]`
- 加 VWAP/TWAP/POV/Almgren-Chriss 母单调度层:策略输出目标持仓变化,执行层据参与率上限与 A-C lambda 拆子单并按跟量撮合;先做 POV+TWAP(中低频够用),A-C 作进阶档。  `[→M9 (新 execution/scheduler) + M1(StrategyGoal 增执行偏好), eff=high, lev=med]`
- 成本模型按实盘成交回灌重标定:扩展 cost_drift,把实盘 fills 做(可分 symbol/regime 的)贝叶斯/分层估计反推 Y 与滑点,周期性建议更新 cost_model 参数并留谱系;接入因子/模型生命周期的退役评估。  `[→M11/M12 (生命周期+注册表) + M9 (cost_drift), eff=med, lev=med]`
- Agent OS 成本翻译层:为每个策略生成一句话经济结论(成本是否吃光 alpha + 容量上限)+ 渐进披露的冲击曲线/IS 瀑布图,并显式标注'这是估计、文献对真实成本高/低估有争议'。把执行环做成 M19 教学 agent 的一个 coach 场景。  `[→M14/M18/M19 (Agent OS + coach + glossary) + M15, eff=med, lev=high]`

### 对抗式核查裁决 — 总体置信度：**high**

_纠正摘要_: 六条论断的核心判断全部成立(5 confirmed + 1 nuanced),代码 gap(论断6)经源码核实属实且比表述更严重。两处必须纠正的引用错误:(1) Frazzini-Israel-Moskowitz 论文元数据张冠李戴——研究流写『约 1.7 万亿美元 + 21 个发达市场』,但其引用的 SSRN abstract_id=2294498 实为 1998-2011 / 近 1 万亿美元 / 19 个发达市场的早期版本;1.7 万亿/21 市场对应 1998-2016 的更晚版本(另有 1998-2013/1.05 万亿/21 市场)。金额与市场数应与所选版本对齐,引用前须统一。(2) 『两个平方根律』(arXiv:2311.18283)作者被误署为『Toth, Bouchaud 等 (CFM 团队相关)』——真实作者是 Bruno Durin, Mathieu Rosenbaum, Grégoire Szymanski(2023),与 Toth/Bouchaud/CFM 无直接署名关系;研究流自己也标注了『贡献描述基于检索,建议核对正文』,此处确需更正署名。其余论文(Almgren-Chriss 2000 Journal of Risk 3:5-39;Garleanu-Pedersen 2013 JF 68:2309-2340,所引 NBER w15205 为 2009 工作论文版,属正常;Bucci 等 2019 arXiv:1901.05332;Said 2022 arXiv:2205.07385;Saddier-Marsili 2023 arXiv:2303.08867)均真实存在、年份/作者/结论对得上,Bucci 与 Said/Saddier 的描述准确。无虚构论文。落地建议:0.5 仅作基线、对 δ∈[0.4,0.7] 与 log 形式做敏感性;crypto 端 Y 用 ~0.9;Bucci 永久成分作保守容量折扣但数值不照搬;DRL 执行降级为研究项;优先把 strategy_goal 已声明的 impact_model/funding/borrow 真正接线进 BacktestVenue 成本。相关源码路径:/Users/wzy/Work/01_Projects/QuantBT/app/backend/app/execution/backtest_venue.py(_cost_for_trade L187-193、funding 未应用 L42)与 /Users/wzy/Work/01_Projects/QuantBT/app/backend/app/strategy_goal.py(impact_model L53/61/71,死配置)。

被降权/纠正的论断：
- `nuanced` — 论断5: DRL 执行『优于 VWAP』报告增益(<0.1% 到约 10% IS)是否对中低频/真实环境稳健,黑箱不可解释是否与本项目硬约束冲突。
  - 纠正：把『增益区间 <0.1%~10% IS』当确定收益是夸大:这些数字高度依赖仿真设定与基线强弱,真实非仿真环境稳健性未证实,样本内过拟合风险高。对非程序员黑箱不可解释确与本项目『流程即信任』约束冲突——DRL 执行宜列为研究项而非默认上线路径。

---


## [15] 多策略资本配置 / pod allocation  · 组 D

**机构级标准** — 机构级标准（多策略/pod 资本配置）= 一个把"单策略风险预算"和"组合层治理"拧成闭环的系统，最佳实践由 Citadel/Millennium/Balyasny/Point72 等平台型多经理基金定义，其核心要素如下。(1) 风险预算优先于资本预算：分配的不是名义资金而是风险额度（VaR / DV01 / CS01 / vol 贡献），每个 pod/策略拿到一份风险预算，并据其历史 Sharpe、drawdown、与组合其余部分的边际风险贡献动态增减。(2) 机械化 kill/scale 导轨：行业典型为分层 drawdown 闸门——回撤约 3-5% 触发干预/砍半风险额度，约 7.5-10% 直接停掉该 pod；这是把"组合层最大回撤"自上而下切割成"单 pod 小止损"的工程化手段，目的是让平台层回撤被多个独立小止损封顶（传统单经理基金回撤可达 20-30%）。(3) 中央风险账本（Center Book / central risk book）做因子净额对冲：把各 pod 头寸聚合后，对冲掉非有意的共同因子暴露（动量/价值/行业/区域 beta），使 pod 之间"看起来分散其实同质"的隐性相关被中和，目标是最小化经理间业绩相关性。(4) 相关性/拥挤实时监控：日度相关矩阵 + 周度蒙特卡洛/3σ 以上尾部压力测试 + 拥挤代理指标（top-3 因子风险占比、pair 价差离散度、hard-to-borrow 集中度、与公开 QIS/指数的名义重叠），用于预判同步去杠杆级联。(5) capacity 与拥挤纳入配置：策略容量受交易成本/市场冲击约束，alpha 在被复制后随时间衰减（机械型因子呈双曲衰减），拥挤的策略要主动缩量。(6) 组合层杠杆/去杠杆纪律：总杠杆 3-5x，去杠杆时遵循"先用指数/方差互换等广谱对冲削 VaR、再慢慢平现货、内部 crossing 缓冲冲击"的有序序列，并报告 VaR 利用率（均值/95 分位/突破次数）。(7) 估计误差稳健化：因 Sharpe/协方差估计在多重检验下严重膨胀，配置须用 shrinkage、聚类化（HRP/NCO）、deflated Sharpe 去偏，而非朴素 mean-variance。这一切必须有谱系、预注册、审批门与可复现记录支撑——这是非技术资本配置者能信任 agent 产出的唯一支柱。


### 关键论文 / 权威实践

- **Not All Factors Crowd Equally: Modeling, Measuring, and Trading on Alpha Decay** ([链接](https://arxiv.org/abs/2512.11913))
  - _(arXiv preprint, 2025) · 2025 · arXiv:2512.11913_
  - 从博弈论均衡推导出因子 alpha 的双曲衰减 α(t)=K/(1+λt)（K 为 alpha 容量，λ 为策略被发现/复制的速率），并在 1963-2024 八个 Fama-French 因子上实证：双曲衰减拟合动量 R²=0.65，优于线性(0.51)/指数(0.61)。关键洞见：'机械型'因子（动量/反转，信号无歧义易复制）拟合该模型并随拥挤衰减，'判断型'因子（价值/质量，信号有解释空间）不衰减。OOS(2001-2024) 拥挤的反转因子崩盘概率高 1.7-1.8x，拥挤动量反而 0.38x。直接支持'按拥挤度/容量动态缩量'的配置规则。注：为新近预印本，结论待同行评议复核。
- **The Deflated Sharpe Ratio: Correcting for Selection Bias, Backtest Overfitting, and Non-Normality** ([链接](https://www.davidhbailey.com/dhbpapers/deflated-sharpe.pdf))
  - _David H. Bailey, Marcos López de Prado · 2014 · Journal of Portfolio Management 40(5):94-107_
  - 给出 DSR：在多重检验（试了 N 个策略才选出最好那个）和非正态收益下对 Sharpe 去膨胀。对多策略配置至关重要——若按朴素 Sharpe 阈值筛策略再分配资本会引入选择偏差，导致系统性高估并过度配置到被噪声选中的策略。QuantBT M10 已实现 DSR，但尚未把它接入策略层资本配置的入选/增配判据。
- **Building Diversified Portfolios that Outperform Out-of-Sample (Hierarchical Risk Parity)** ([链接](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2708678))
  - _Marcos López de Prado · 2016 · Journal of Portfolio Management 42(4):59-69_
  - HRP：用层次聚类把相关矩阵准对角化后递归二分配权，避开协方差矩阵求逆的不稳定性，OOS 表现优于 mean-variance 与朴素 risk parity。是'按相关结构分散'的工业标准方法，天然适合策略层 meta-allocation（把策略当资产聚类）。QuantBT M8 已实现 hrp_weights，但只用于标的层、未上升到策略层。
- **A Robust Estimator of the Efficient Frontier / Nested Clustered Optimization (NCO)** ([链接](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=3469961))
  - _Marcos López de Prado · 2019 · SSRN 3469961 / Machine Learning for Asset Managers (2020)_
  - NCO：先聚类、簇内单独优化、再用簇间交叉验证的 OOS 估计做外层优化，权重=内层⊗外层，专门压制'信号结构放大估计误差'导致的配置不稳定。是 HRP 的优化升级版，对策略层 meta-allocation（策略高度相关时尤甚）更稳健。
- **Drawdown Measure in Portfolio Optimization (Conditional Drawdown-at-Risk, CDaR)** ([链接](https://www.math.columbia.edu/~chekhlov/ChekhlovUryasevZabarankin--03-2004.pdf))
  - _Alexei Chekhlov, Stanislav Uryasev, Michael Zabarankin · 2005 · International Journal of Theoretical and Applied Finance 8(1):13-58_
  - 提出 CDaR（最坏 (1-β) 分位回撤的均值，最大回撤与平均回撤为其极限），并将'最大化收益 s.t. 回撤约束'化为线性规划。给出了组合层回撤控制的凸优化基础——比 pod-shop 的硬阈值 stop-out 更平滑、可作为风险预算的目标函数。
- **A Meta-Method for Portfolio Management Using Machine Learning for Adaptive Strategy Selection (Meta Portfolio Method, MPM)** ([链接](https://arxiv.org/abs/2111.05935))
  - _Damiano Brigo 等 (具体作者以原文为准) · 2021 · arXiv:2111.05935 / ICMLT 2022_
  - 用 XGBoost 在 HRP 与朴素 risk parity 之间做自适应切换（顺风用 NRP 抢增长、逆风用 HRP 防回撤），实现更高累计收益同时保持最高风险调整收益。是'用 ML 做策略间 meta-allocation/regime 切换'的代表性近期工作，可作为 emerging 方法参考（注：需对其样本外稳健性做对抗式复核）。
- **Adaptive and Regime-Aware RL for Portfolio Optimization** ([链接](https://arxiv.org/abs/2509.14385))
  - _Gabriel Nixon Raj (NYU) · 2025 · arXiv:2509.14385_
  - regime-aware RL 长期组合优化：agent 随潜在宏观 regime 切换动态再配置，奖励函数内嵌波动率惩罚、资本重置、尾部冲击；Transformer-PPO 风险调整收益最高，LSTM 变体在可解释性与成本上更优。代表 RL 做动态 meta-allocation 的前沿，但属 contested——OOS 稳健性、过拟合、可解释性争议大，不适合直接上生产资本配置。

### SOTA 方法

- **分层 drawdown kill/scale 导轨（pod stop-out）** `[established]` — 回撤约 3-5% 砍半风险额度、约 7.5-10% 停掉该 pod，把组合层最大回撤自上而下切成多个独立小止损。Citadel/Millennium/Balyasny 工业实践。优点：可解释、可执行、回撤封顶；缺点：阈值常是经验值而非优化得来，且同步触发会引发拥挤去杠杆级联。
- **风险预算 / risk parity across strategies（HRP / NCO / 逆波动）** `[established]` — 分配的是风险贡献而非名义资本；用层次聚类（HRP）或嵌套聚类优化（NCO）按策略相关结构分散，规避协方差求逆不稳定。是策略层 meta-allocation 的稳健主流方法。
- **中央风险账本 / 因子净额对冲（Center Book）** `[established]` — 聚合各 pod 头寸后用指数/行业/方差互换对冲掉非有意的共同因子暴露，中和 pod 间隐性相关，最小化经理间业绩相关性。平台型基金标配，但实现细节是专有黑箱。
- **Deflated Sharpe / 多重检验去偏后的策略入选** `[established]` — 用 DSR/PBO 校正'试了 N 个策略选最好'的选择偏差后再决定是否给资本，避免把资本配到被噪声选中的策略。学术共识明确，但产业落地到资本配置判据仍不普遍。
- **容量/拥挤感知的动态缩量（双曲 alpha 衰减、拥挤代理指标）** `[emerging]` — 按交易成本/市场冲击估容量上限，按拥挤代理（top-3 因子风险占比、pair 离散度、QIS 重叠、双曲 alpha 衰减拟合）主动给拥挤策略缩量。概念成熟、监控指标在产业中已用，但'按拥挤度精确缩多少'仍缺统一方法。
- **组合层回撤约束优化（CDaR / CVaR / vol-targeting）** `[established]` — 用 CDaR/CVaR 作为约束或目标做凸优化，或用波动率目标动态调杠杆控制组合回撤，比硬阈值 stop-out 更平滑。方法学成熟，但与离散 kill 规则如何协同仍是工程问题。
- **ML/RL 自适应 meta-allocation（MPM、regime-aware RL、MARS）** `[contested]` — 用 XGBoost/HMM/PPO 等在策略或 regime 间动态切换配置。近期论文报告更优风险调整收益，但样本外稳健性、过拟合、可解释性争议大，机构对其上生产资本配置高度谨慎。
- **多元 Kelly / 分数 Kelly 跨策略配置** `[contested]` — 按几何增长最优在相关策略间配权，实务用 25-50% 分数 Kelly 防过押。理论优美但对参数估计极敏感，full Kelly 几乎无人用，需配合 shrinkage 与回撤约束。

### 最佳实践

- 分配风险预算（VaR/vol 贡献/DV01）而非名义资本，并按边际风险贡献、滚动 Sharpe（30/90/inception 三窗）、与组合其余的相关性动态增减。
- 用分层 drawdown 闸门把组合层最大回撤自上而下切成多个独立小止损（砍半→停用），让平台层回撤被多个 pod 级止损封顶。
- 用中央风险账本对各策略聚合头寸做因子净额对冲，主动中和非有意的共同 beta，目标是最小化策略间业绩相关性。
- 配资前用 deflated Sharpe / PBO 校正多重检验选择偏差，达不到去偏门槛的策略不给真实资本。
- 用 HRP/NCO 等聚类化、稳健化方法做策略层配置，避免朴素 mean-variance 在高相关、估计误差大时的不稳定。
- 把容量与拥挤纳入配置：估 alpha 容量上限、监控拥挤代理指标（因子风险集中、QIS 重叠、pair 离散度），对拥挤策略主动缩量。
- 组合层用 CDaR/CVaR 约束或波动率目标做平滑回撤/杠杆控制，作为离散硬止损的补充。
- 去杠杆遵循有序序列：先广谱对冲（指数/方差互换）快速削 VaR，再慢平现货，内部 crossing 缓冲市场冲击；全程报告 VaR 利用率（均值/95 分位/突破）。
- 每次资本再分配都留谱系：触发指标、当时相关矩阵与拥挤快照、go/no-go 决策者，全程可复现可审计——这是非技术配资者信任的唯一支柱。
- 策略上下线走生命周期态机驱动的资本流转：进入 PROBATION 自动缩配、RETIRED 回收资本并再分配给候选池，编排用幂等 DAG。

### 差距

- 缺策略层 meta-allocation 层：QuantBT M8 的 optimizers.py（equal/mean-variance/risk_parity/hrp）与 constraints.py 全部作用于标的层（symbol→weight），全仓库 grep 不到任何 strategy-allocation/meta-allocation/pod/capital-allocator 代码。多个策略/模型之间如何分配资本完全缺位——这正是本研究主题的核心，目前是零。
- 缺 kill/scale 风险导轨：M9 RiskMonitor 是单笔/日内笔数/日内亏损/集中度 + KillSwitch，作用于单个执行账户；没有'按 pod/策略回撤分层砍半/停用风险额度、并把腾出的额度转给高 Sharpe 策略'的资本流转引擎。M17 CopyTrade 有 follower 杠杆硬上限，但 follower 之间无相关性/净额管理。
- 缺中央风险账本 / 因子净额：无任何把多个策略/follower 头寸聚合后做因子暴露净额、对冲非有意共同 beta、监控经理间相关性的机制（copy_trade 模块 grep 不到 correlation/covariance/net-exposure/risk-budget）。
- 缺容量/拥挤感知：M4 有 IC 衰减监控、M11 因子生命周期有衰减态机，但没有 alpha 容量估计、市场冲击/容量约束的配置、或拥挤代理指标（因子风险集中度、与公开因子重叠、pair 离散度）；策略拥挤了不会自动缩量。
- 缺组合层回撤控制优化：有 M10 的事后 PBO/DSR/Bootstrap CI，但无 CDaR/CVaR 作为约束的组合优化，也无 vol-targeting 动态杠杆；组合层回撤目前不是一个被主动优化/约束的对象。
- DSR/PBO 未接入资本配置判据：M10 已能算 deflated Sharpe，但策略入选/增配/退役没有把它当门槛，存在按朴素 Sharpe 选策略的选择偏差风险。
- 缺策略上下线的资本流转编排：M11 因子生命周期态机 + M13 DAG 引擎具备底座，但没有'策略进入 PROBATION→自动缩配、RETIRED→资本回收并再分配给候选池'的资本流转 DAG。
- 缺去杠杆有序序列：无'先广谱对冲削 VaR、再慢平、内部 crossing 缓冲'的组合层去杠杆 playbook，组合遇压时只能各执行账户各自 KillSwitch，可能放大同步去杠杆冲击。

### Agent OS 在这一环的角色（服务零代码用户）

在这一环，零代码小白/经济学者根本读不懂 HRP 协方差或 CDaR 线性规划——Agent OS 必须把'多策略配置'翻译成他熟悉的经济与治理语言，并用流程导轨替代代码信任。具体三层：(1) 经济学语言翻译。把风险预算讲成'你有 100 份风险额度，agent 建议给动量策略 30 份、给均值回归 25 份…因为它们的回撤在历史上很少同时发生（相关性 0.2）';把 deflated Sharpe 讲成'这个策略表面年化夏普 2.0，但因为我们试了 200 个策略才挑出它，去掉运气成分后只剩 0.7，达不到 1.0 的配资门槛';把双曲 alpha 衰减讲成'这个动量信号正被越来越多人用，预计 18 个月后收益减半，建议现在就给它设容量上限'。用户出的是经济判断（这个逻辑我信不信、容量假设合不合理），agent 出全部工程。(2) kill/scale 规则即预注册契约。让用户在配资前用自然语言 + 滑块预注册护栏：'任一策略回撤到 5% 自动砍半风险额度、7.5% 停用，组合层回撤到 X% 全体降杠杆'——这是写进治理台账、不可事后篡改的承诺，触发时 agent 自动执行机械动作但把'是否恢复/重新配资'留作 human-in-the-loop 的 go/no-go。流程即信任：用户信的不是代码，是'我事先定的规则被一字不差执行且全程留痕可回放'。(3) 谱系与验证闸门可视化。每一次资本再分配都生成一条可追溯记录（哪个策略因为什么指标被增/减/停、当时相关矩阵与拥挤指标快照），用'资本流向桑基图 + regime 标注 + 一句话经济解释'呈现，让经济学者能像读基金月报一样审计 agent 的配置决策，而不必看一行 Python。资产无关性在这一环体现为：股/期货/期权任何品类只要能产出策略级 PnL 序列与风险指标，就能进同一个 meta-allocation 引擎，用户填配置而非重写流程。

### 建议

- 新建策略层 meta-allocation 引擎（StrategyAllocator）：复用 M8 的 hrp_weights/risk_parity，但输入从 symbol×returns 升级为 strategy×PnL；先落地逆波动 + HRP 两个稳健基线，把多个策略/模型的净值序列当'资产'分配风险预算。这是填补最大 gap 的核心，杠杆极高。  `[→M8（升一层）+ M12 ModelRegistry（取 production 策略清单）, eff=med, lev=high]`
- 实现分层 drawdown kill/scale 导轨 + 资本流转：在 M9 RiskMonitor 之上加 PortfolioGovernor，按每策略回撤分层（5% 砍半风险额度、7.5% 停用，阈值用户预注册可配），停用腾出的额度按 Sharpe/相关性自动再分配给候选；停用→PROBATION→退役走 M11 态机，资本流转用 M13 DAG 编排。  `[→M9 RiskMonitor + M11 因子/策略生命周期 + M13 DAG, eff=med, lev=high]`
- 把 deflated Sharpe / PBO 接入配资判据：策略要拿到资本必须 DSR 过门槛（如 >1.0）且 PBO 低于阈值，否则只能进 paper/PROBATION 不给真实资本额度。直接复用 M10 已有实现，改动小、防过拟合配资。  `[→M10 PBO/DSR + M12 ModelRegistry 晋级门, eff=low, lev=high]`
- 加策略间相关性/净额监控（轻量 Center Book）：聚合各策略/follower 当前头寸，计算因子/品类净暴露与经理间业绩相关矩阵，超阈值告警并在 meta-allocation 里惩罚高相关组合；先做监控+告警，再做对冲建议。CopyTrade 的 follower 群体可直接受益。  `[→M8 constraints（加 cross-strategy corr cap）+ M9/M17 CopyTrade, eff=med, lev=med]`
- 容量/拥挤感知缩量：用 M4 IC 衰减 + 简单市场冲击模型估每策略容量上限，对拥挤策略（IC 衰减加速 / 与公开因子重叠高）在 allocator 里设硬容量上限并自动缩量；可引用双曲衰减 α(t)=K/(1+λt) 做衰减外推预警。属 emerging，先做预警再做自动缩量。  `[→M4 因子评估 + M11 衰减态机 + 新 StrategyAllocator, eff=high, lev=med]`
- 组合层回撤约束 + vol-targeting：在 meta-allocation 加可选 CDaR/CVaR 约束（Chekhlov-Uryasev 线性规划）或组合层波动率目标动态调总杠杆，作为硬阈值 stop-out 的平滑补充；输出组合层预期最大回撤给用户预注册。  `[→M8 optimizers（加 CDaR 目标）+ M9 杠杆控制, eff=med, lev=med]`
- Agent OS 翻译层：把每次配资决策生成'资本流向桑基图 + regime 标注 + 一句话经济解释 + 触发的预注册规则'，用 M14 agent 自然语言总结、M19 Glossary 渐进披露术语，配资前让用户用自然语言+滑块预注册 kill/scale 护栏。这是让非程序员能信任并 go/no-go 的关键。  `[→M14 Agent + M15 前端 + M19 Glossary/Coach + M20 Live Ladder（配资即上线闸门）, eff=med, lev=high]`
- 去杠杆有序 playbook：组合层遇压时按'先广谱对冲削 VaR→慢平现货→内部 crossing'序列执行而非全体 KillSwitch，降低同步去杠杆冲击；先在 paper/回测里实现并记录，作为生产前的预注册应急手册。  `[→M9 执行&风控 + M13 DAG（应急流程编排）, eff=high, lev=low]`

### 对抗式核查裁决 — 总体置信度：**high**

_纠正摘要_: 七篇引用论文均真实存在，但有两处必须纠正、且对全研究流的可信度影响重大：\n\n1) 【最严重 — 已撤稿】'Not All Factors Crowd Equally'(arXiv 2512.11913, Chorok Lee)已于 2025-12-27 被作者本人撤稿，撤稿说明明言第5-7节实证‘不足以支撑全局适用性主张’。而论断2及该论文恰恰是‘按拥挤度/容量动态缩量’配置规则的唯一实证支柱——R²=0.65、1.7-1.8x/0.38x 崩盘概率等数字现已被作者收回，不可作为任何硬规则依据。论断2应从‘看似漂亮但待评议’直接降级为 refuted。\n\n2) 【作者归属错误】MPM 论文(arXiv 2111.05935)真实作者是 Damian Kisiel 与 Denise Gorse (UCL)，并非引用所写的 'Damiano Brigo 等'。内容描述正确但署名虚构/错配，须改正。\n\n其余五篇(DSR 2014、HRP 2016、NCO 2019、CDaR 2005、Regime-Aware RL 2025)的作者/年份/结论/链接均核实无误(DSR 的规范 SSRN 号为 2460551，所给 davidhbailey.com 链接亦合法)。\n\n六条论断：1(pod 阈值)= nuanced——5%/7.5% 主要属 Millennium 标准化限额，Citadel/Balyasny 为差异化专有，全部来源为二手、无一手披露，论断的对抗式判断成立；2= refuted(见上);3(HRP/NCO策略层)= nuanced——OOS 优势仅在资产层验证，少量高相关策略下不应假定优于等权/逆波动，文献本身承认等权常胜优化器;4(Center Book净额对冲)= confirmed——净额化降成本但压力期共同暴露与同步去杠杆使尾部相关飙升、netting 来不及吸收，是转移/管理而非消除;5(ML/RL生产成立)= nuanced/contested——MPM 与 RL 均仅回测优势，无含成本+regime 的活钱 OOS;6(DSR 硬门槛过度保守)= confirmed，但有概念纠正——DSR∈[0,1] 是置信度，合理门槛应写 DSR>0.95 而非>1.0，且其已内生随试验数N/回测长度T自适应，宜作软评分而非一刀切硬否决。\n\n总体：论文库底子扎实(均真实)，但一篇关键实证支柱已撤稿、一处作者错配，且若干‘行业标准’仅有二手来源。落地时:(a) 移除对 2512.11913 实证数字的依赖;(b) 改正 MPM 作者;(c) 把 pod 阈值做成可配置分层参数而非硬编码 5%/7.5%;(d) 策略层 HRP/NCO 必须与等权/逆波动基线做严格 walk-forward 对照;(e) Center Book 显式建模尾部相关上行;(f) DSR 作为自适应软门槛(如0.95)接入配资。

被降权/纠正的论断：
- `nuanced` — 论断1：'回撤5%砍半、7.5%停用'是行业精确标准吗？
  - 纠正：把5%/7.5%作为‘整个行业的精确标准’是错误概括：(a) 这组具体数字主要与 Millennium 关联，Citadel/Balyasny 是差异化/专有的；(b) 所有可得来源均为二手(行业博客/论坛/媒体)，无任何一手基金披露、监管文件或经理署名访谈给出这些精确阈值——pod-shop 的实际 stop-out 阈值是专有且不公开的。落地时应做成可配置、按 pod 资历/策略类型分层的参数，并标注为‘行业惯例区间(典型 3-5% 触发干预)’而非硬编码标准。
- `refuted` — 论断2：双曲 alpha 衰减 α(t)=K/(1+λt) 的实证强度(arXiv 2512.11913, momentum R²=0.65 优于指数0.61)
  - 纠正：论断中‘momentum R²=0.65 看似漂亮’及对其稳健性的怀疑应升级为：该实证结论已被作者撤回，不可作为任何配资规则的依据。R²=0.65 vs 0.61 的差距本就微小(且 0.51/0.61/0.65 三者接近，难言双曲显著胜出)，叠加撤稿，应视为未经验证。理论上的‘双曲衰减/拥挤致崩’框架可作为定性参考，但任何按拥挤度动态缩量的硬规则不应引用此数字。
- `nuanced` — 论断3：HRP/NCO 在策略层(而非标的层)meta-allocation 的 OOS 优势是否成立
  - 纠正：论断方向正确，应保留为 nuanced：HRP/NCO 可作为策略层 meta-allocation 的候选，但在少量(<~30)高相关策略上不应假定其必然优于简单逆波动或等权；需在本项目数据上做严格 walk-forward/OOS 对照(含等权、逆波动基线)再决定，并对聚类数与协方差估计加正则/收缩。
- `nuanced` — 论断5：ML/RL meta-allocation(MPM/regime-aware RL/MARS)报告的超额风险调整收益能否在生产成立
  - 纠正：论断成立且应保留 nuanced/contested：这些方法可作为 emerging 参考，不应直接上生产资本配置。引用时须注明结论来自回测;若采用须自建含交易成本、含 regime 切换、严格 walk-forward 的 OOS 验证。注意 MPM 的回测优势虽 p 值很小，但样本期与universe有限，p 值小≠生产稳健。
- `nuanced` — 论文核查：'Not All Factors Crowd Equally'(arXiv 2512.11913, Chorok Lee, 2025)
  - 纠正：重大状态纠正：该论文已于 2025-12-27 被作者撤稿(withdrawn for major revision)，作者自认第5-7节实证不足以支撑全局适用性主张。引用必须标注‘已撤稿/实证未获支持’，不能作为‘直接支持按拥挤度动态缩量’的实证依据;仅理论框架(作者称仍有效)可作定性参考。
- `refuted` — 论文核查：'A Meta-Method for Portfolio Management / MPM'(引用署名 Damiano Brigo 等, 2021)
  - 纠正：作者纠正：真实作者是 Damian Kisiel 和 Denise Gorse(UCL)，与 Damiano Brigo 无关。引用把作者写成‘Damiano Brigo 等’是错误归属(可能因 Kisiel 与 Brigo 名字相近/同属伦敦量化圈而混淆)。引用虽加了‘(具体作者以原文为准)’的对冲，但 named author 仍属虚构归属，必须改正为 Kisiel & Gorse (2021)。

---


## [16] live监控 / 漂移 / 衰减 / 归因  · 组 D

**机构级标准** — 机构级"上线后监控/漂移/衰减/归因"环节的标准是一个闭环的、有问责链的模型风险管理(MRM)体系，可拆为四层。(1) 治理层：以美联储/OCC SR 11-7 为事实标准——集中化模型清单、风险分级(risk-tiering)、独立验证、"有效挑战(effective challenge)"、持续性能监控与年度再验证、问题整改流程、董事会/委员会问责。模型从未"完工"，必须有 ongoing monitoring。(2) 统计监控层：用预注册的、对多重检验做了校正的判据判断"live 是否仍像 backtest"——Probabilistic/Deflated Sharpe Ratio(PSR/DSR)、Minimum Track Record Length(MinTRL，回答"要多少天 live 数据才能在 95% 置信度下确认 SR>阈值")、PBO(回测过拟合概率)、Sharpe bootstrap 置信区间；上线前定下 go/no-go 阈值，上线后用同一把尺子量 live。(3) 漂移/断点检测层：对收益、IC、滑点、特征分布做在线变点检测(CUSUM、Page-Hinkley、Bai-Perron 多断点、PELT、BOCPD Adams-MacKay 2007、ADWIN)与 regime 监测(HMM)，区分"信号衰减 vs 执行成本恶化 vs regime 切换"。(4) 归因与后交易分析层：收益归因用 Brinson-Fachler / Brinson-Hood-Beebower(GIPS/CFA 体系)与因子归因(Fama-French、Barra 风险归因)；执行归因用 TCA/Implementation Shortfall(Perold)分解 delay/spread/market-impact/timing/opportunity 成本，且前沿要求 TCA 从"批量事后报表"转为"近实时在线"。最后，整个生命周期评估应被自动化调度(drift-triggered + 周期性再验证)，并通向明确的降级/退役决策与资本再分配。


### 关键论文 / 权威实践

- **The Deflated Sharpe Ratio: Correcting for Selection Bias, Backtest Overfitting and Non-Normality** ([链接](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2460551))
  - _David H. Bailey, Marcos López de Prado · 2014 · Journal of Portfolio Management 40(5)_
  - 提出 DSR：在已知试验次数、收益偏度/峰度、样本长度下，把 SR 的显著性阈值膨胀以剔除选择偏差与回测过拟合。上线监控的统计骨架——用同一判据判断 live SR 是否仍统计显著。
- **The Sharpe Ratio Efficient Frontier (含 Probabilistic Sharpe Ratio 与 Minimum Track Record Length)** ([链接](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=1821643))
  - _David H. Bailey, Marcos López de Prado · 2012 · Journal of Risk 15(2)_
  - PSR 在非正态(偏度/峰度)下计算真实 SR 高于阈值的概率；MinTRL 给出'需要多少 live 观测才能确认 SR>阈值'。直接回答监控核心问题：live 还没跑够久，drawdown 究竟是噪声还是真衰减。
- **The Probability of Backtest Overfitting** ([链接](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2326253))
  - _David H. Bailey, Jonathan Borwein, Marcos López de Prado, Qiji Jim Zhu · 2016 (SSRN 2014) · Journal of Computational Finance_
  - 用 CSCV(组合对称交叉验证)估计 PBO——最优 IS 配置在 OOS 排名退化的概率。上线后若 live 表现落入 PBO 预测的衰减区间，是强退役信号。
- **The False Strategy Theorem: A Financial Application of Experimental Mathematics** ([链接](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=3221798))
  - _Marcos López de Prado, David H. Bailey · 2021 · American Mathematical Monthly_
  - 证明:试验次数足够多时任意高的 SR 都可由纯噪声达到(最优 SR 期望右无界)。为'记录试了多少次→给监控阈值打折'提供数学基础，是 DSR 的理论支撑。
- **Measuring Strategy-Decay Risk: Minimum Regime Performance and the Durability of Systematic Investing** ([链接](https://arxiv.org/abs/2604.08356))
  - _Nolan Alexander, Frank Fabozzi · 2026 · arXiv (UVA / Johns Hopkins)_
  - 提出 Minimum Regime Performance(MRP)=策略在所有历史 regime 中最低的风险调整收益，作为'结构性脆弱度/衰减风险'的下界度量。发现高长期 SR 不等于高 MRP(效率-韧性张力)。一个新颖的、可直接计算的衰减/退役判据。
- **Bayesian Online Changepoint Detection** ([链接](https://arxiv.org/abs/0710.3742))
  - _Ryan P. Adams, David J.C. MacKay · 2007 · arXiv/技术报告_
  - BOCPD：在线递归估计 run-length 后验，可实时给出'此刻处于断点的概率'。是 live 收益/IC 流做实时 regime-break 报警的事实基线算法(hazard rate λ 调灵敏度)。
- **Computation and Analysis of Multiple Structural Change Models** ([链接](https://onlinelibrary.wiley.com/doi/10.1002/jae.659))
  - _Jushan Bai, Pierre Perron · 2003 (理论 1998) · Journal of Applied Econometrics 18(1)_
  - 在回归框架中联合估计未知数量与位置的多个结构断点(最小化全局 SSR)。机构判定'策略-市场关系是否发生结构性断裂'的经典离线检验。
- **Optimal Detection of Changepoints With a Linear Computational Cost (PELT)** ([链接](https://www.tandfonline.com/doi/abs/10.1080/01621459.2012.737745))
  - _Rebecca Killick, Paul Fearnhead, Idris Eckley · 2012 · Journal of the American Statistical Association 107(500)_
  - PELT：带惩罚项的精确变点检测，线性时间复杂度，控制过拟合。Python ruptures 库的核心算法，适合对收益/滑点序列做批量多断点扫描。
- **The 10 Reasons Most Machine Learning Funds Fail** ([链接](https://www.garp.org/hubfs/Whitepapers/a1Z1W0000054x6lUAA.pdf))
  - _Marcos López de Prado · 2018 · Journal of Portfolio Management / GARP_
  - 系统列出 ML 量化产线失败的 10 个原因(其中含回测过拟合、未做多重检验校正、非平稳/regime 处理不当)。把上线后监控放进完整研究治理语境的权威实践清单。

### SOTA 方法

- **PSR / DSR / MinTRL 作为 live 监控判据** `[established]` — 用上线前在 backtest 确定的统计阈值(DSR 校正多重检验、PSR 计真实 SR>阈值概率、MinTRL 给所需 live 样本量)在上线后用同一把尺子持续量 live 净值，把'回撤是噪声还是真衰减'变成可计算的概率而非主观判断。
- **在线变点检测(CUSUM / Page-Hinkley / BOCPD / ADWIN)** `[established]` — 对 live 日收益、滚动 IC、滑点、特征分布做流式监控:CUSUM/Page-Hinkley 检测均值漂移；BOCPD(Adams-MacKay)给实时断点后验概率；ADWIN 自适应窗口。区分突变(regime-break)与缓变(decay)。
- **多断点离线检验(Bai-Perron / PELT)** `[established]` — 在定期再验证时对策略-因子关系或收益序列做多结构断点联合估计(Bai-Perron 最小化全局 SSR；PELT 线性时间)，判定是否发生不可逆的结构性断裂从而触发退役。
- **HMM 市场 regime 检测与 regime-conditional 性能对照** `[established]` — 用 HMM 推断不可观测的低波/高波/危机 regime，把 live 表现按 regime 拆开与 backtest 同 regime 表现对照，避免'只是遇到没见过的 regime'被误判为衰减。前沿扩展:非齐次转移概率、贝叶斯估计、Wasserstein 聚类。
- **Minimum Regime Performance (MRP) 衰减度量** `[emerging]` — Alexander-Fabozzi(2026)提出的跨 regime 最低风险调整收益,作为结构性脆弱度下界,补足传统波动/回撤指标看不到的'衰减风险'。可作为退役闸门的新判据。
- **近实时 TCA / Implementation Shortfall 在线归因** `[emerging]` — 把后交易 TCA 从批量事后报表升级为流式:slippage divergence(假设 2bps vs 实测 4bps)、fill-probability 恶化、latency-to-fill,用轻量在线学习持续重标定执行预期,把'信号衰减 vs 执行恶化'用概率归因拆开(KX/Talos/OneTick 等实践)。
- **Brinson-Fachler / 因子(Barra/FF)收益归因** `[established]` — GIPS/CFA 体系标准:Brinson-Fachler 把超额收益拆为配置效应+选择效应；因子归因把收益归到 FF/Barra 因子暴露。机构事后解释'钱从哪来/为何不再来'的共识方法。
- **drift-triggered 自动再验证/再训练调度(MLOps)** `[emerging]` — 漂移监控(KS/PSI>0.25/ADWIN)触发调度器自动跑再验证/再训练流水线,叠加周期性再验证;配 canary/shadow/A-B 安全发布在切量前测 live 表现。AutoDrift 等端到端管线为代表。
- **概率/因果式漂移归因** `[contested]` — 前沿尝试用概率模型估计 live underperformance 各来源(信号衰减/流动性 regime/路由低效/基础设施延迟)的后验权重,缩小排查范围而非穷举。尚无统一方法、结果依赖建模假设。

### 差距

- M10 已有 PBO(CSCV)+DSR(Bailey-LdP)+Bootstrap Sharpe CI,但这些只用在回测阶段;缺一条'live 监控用同一把尺子'的回路——没有 MinTRL/PSR 在线评估'live 跑够久了吗、live SR 是否仍统计显著',也没有把 live 净值喂回 DSR 持续打分。这是最核心的 gap:严谨度只覆盖到上线那一刻,上线后断档。
- 明确缺 live-vs-backtest 漂移监控(MEMORY 已自认 M10'缺 live 漂移监控')。没有对 live 日收益/滚动 IC/滑点序列做 CUSUM/Page-Hinkley/BOCPD/ADWIN 在线变点检测的组件;regime 检测(M2 的 ADX/vol-z + 可选 HMM)用于选股/门控,但没接到'regime-conditional 把 live 与 backtest 同 regime 对照'的监控用途。
- 缺多断点离线检验:无 Bai-Perron / PELT(ruptures)用于定期再验证时判定策略-因子关系是否发生不可逆结构性断裂。
- 归因侧:M10 已有 Brinson 三层归因(BHB),但缺 Brinson-Fachler 变体、缺因子(FF/Barra)收益归因,且归因是回测态、没有 live 后交易归因。执行归因/TCA 缺失:M9 有执行venue与 RiskMonitor,但没有 Implementation Shortfall 分解(delay/spread/impact/timing/opportunity)与 slippage-divergence/fill-probability/latency-to-fill 的近实时 TCA——无法区分'信号衰减 vs 执行成本恶化'。
- M11 因子生命周期五态机(NEW→...→RETIRED)已存在但自认'缺自动调度评估':状态转移目前靠手动/阈值,没有把'变点报警/DSR 失效/MRP 跌破/regime-conditional 退化'这些监控信号自动喂给状态机,也没有 drift-triggered 的再验证/再训练调度(M13 DAG 引擎具备 cron/SLA 能力但未接线到生命周期评估)。
- 缺把以上监控信号统一汇聚的'live 模型风险看板/问责链':没有 SR 11-7 式的持续监控记录、有效挑战日志、降级/退役决策的预注册闸门与审计留痕——而这恰是非程序员用户能信任 agent 的唯一支柱。
- 缺 MRP(跨 regime 最低风险调整收益)这类衰减专用度量,现有衰减判断主要靠因子 IC 衰减(M4)与五态机阈值,看不到'结构性脆弱度下界'。

### Agent OS 在这一环的角色（服务零代码用户）

这一环是"流程即信任"最吃重的地方:非程序员用户读不懂 CUSUM 统计量,只能靠 agent 把监控翻译成经济学语言+清晰的 go/no-go 时刻。具体:(1) 预注册即承诺。上线前需求澄清 agent 就让用户用经济学逻辑(如'我赌的是动量在趋势市有效')写下假设,并把'你期望它在什么 regime 有效、能容忍多深回撤多久、live SR 低于多少就停'登记成可检验闸门;上线后监控严格用这套预注册阈值,agent 不能事后挪动球门——这点本身就是信任来源,要在 UI 上显式呈现'闸门是你当初定的'。(2) 把统计判据翻译成因果叙事。当 BOCPD/CUSUM 报警,agent 不说'CUSUM 超阈值',而说'过去 18 个交易日策略表现与回测明显分叉(置信度 96%)。我把原因拆开看:执行成本从假设的 2bps 涨到了实测 4.3bps(占 60% 的差),信号本身的 IC 只轻微下滑(占 25%),其余是你没见过的高波动 regime。这更像执行环境变差,不是策略失效。'(3) MinTRL 治焦虑。小白看到三周亏损就想砍,agent 用 MinTRL 说'要在 95% 置信度下确认它真的不行,至少需要 N 个交易日的 live 数据;现在只有 15 天,统计上还无法和噪声区分,建议继续 paper/小仓观察而非清盘'——把人从情绪决策拉回证据决策。(4) human-in-the-loop 的退役/降级:工程(算变点、跑归因、拉 TCA)全自主;但'是否退役/减仓/转 paper'是经济与风控判断,必须由人按 agent 给的结构化简报(衰减证据/归因/MRP/剩余预算)点 go/no-go,agent 只准备弹药不替人扣扳机。(5) 渐进披露:小白看红黄绿灯+一句话叙事;经济学者展开看 regime-conditional 对照与因子归因;quant 再下钻到 DSR/PBO/变点后验。同一监控,三层视图。

### 建议

- 建 LiveMonitor 组件:对每个 live/paper run 的日收益、滚动 IC、滑点序列做在线变点检测(CUSUM + Page-Hinkley 起步,BOCPD/ADWIN 进阶),输出'断点概率+方向(突变 vs 缓降)'。先复用现有 M2 regime 与 M4 IC 设施的数据流。  `[→M10 + M2, eff=med, lev=high]`
- 把 M10 已有的 DSR/PSR/Bootstrap-CI 接成 live 回路:实现 MinTRL,在监控面板回答'live 跑够久了吗/live SR 是否仍统计显著',并持续用 live 净值重算 DSR。这是补'严谨度断在上线那一刻'最大缺口、复用已有代码、杠杆极高。  `[→M10, eff=low, lev=high]`
- 补 live-vs-backtest 漂移对照:按 regime 把 live 表现与 backtest 同 regime 表现配对(regime-conditional drift),避免把'没见过的 regime'误判为衰减。直接接 M2 regime 标签。  `[→M10 + M2, eff=med, lev=high]`
- 实现 Implementation Shortfall 分解(delay/spread/market-impact/timing/opportunity)+ slippage-divergence/fill-probability/latency-to-fill 的近实时 TCA,把'信号衰减 vs 执行恶化'用概率归因拆开。接 M9 执行venue 的成交回报与 UserDataStream。  `[→M9 + M10, eff=med, lev=high]`
- 把监控信号(变点报警/DSR 失效/MinTRL 未达/MRP 跌破/regime 退化)作为事件自动喂给 M11 五态机做状态转移,并用 M13 DAG 引擎(已有 cron/SLA/幂等)调度'周期性再验证 + drift-triggered 再验证'。补 M11 自认的'缺自动调度评估'与 M10 的 live 漂移监控。  `[→M11 + M13, eff=med, lev=high]`
- 实现 MRP(跨 regime 最低风险调整收益)作为衰减专用度量并入退役闸门(Alexander-Fabozzi 2026)。一个相对独立、可计算的新判据,低工程量。  `[→M10 + M11, eff=low, lev=med]`
- 归因侧:在 M10 已有 Brinson-BHB 基础上加 Brinson-Fachler 变体 + 因子(FF/Barra 式)收益归因,并把归因从回测态扩到 live 后交易态,供 agent 生成因果叙事。  `[→M10, eff=med, lev=med]`
- 建 SR 11-7 式'live 模型风险看板 + 问责链':集中模型清单按风险分级、持续监控记录、有效挑战/退役决策的预注册闸门与审计留痕;上线前由澄清 agent 登记 go/no-go 阈值。这是非程序员信任 agent 的支柱,且把散落的 M11/M12/M13 拧成治理闭环。  `[→M12 + M11 + M14, eff=high, lev=high]`
- 在 Mode2 教学 agent 中加'监控叙事层':把变点/DSR/MinTRL/TCA 翻译成红黄绿灯+一句话经济学叙事,按小白/经济学者/quant 三层渐进披露,并用 MinTRL 做'别因短期回撤恐慌清盘'的反情绪护栏。  `[→M19 + M14, eff=med, lev=high]`
- 接 live 监控数据源补缺:CoinGecko/Glassnode 链上数据(MEMORY 已记 M3 缺)可增强 crypto 的 regime/流动性 nowcasting,提升 regime-conditional 监控质量。优先级低于上面统计回路。  `[→M3, eff=med, lev=low]`

### 对抗式核查裁决 — 总体置信度：**high**

_纠正摘要_: All eight cited papers are real, correctly attributed, and accurately described — no fabrications. Verified details: DSR (Bailey & Lopez de Prado 2014, JPM 40(5):94, SSRN 2460551); Sharpe Ratio Efficient Frontier with PSR+MinTRL (2012, Journal of Risk 15(2), SSRN 1821643); PBO via CSCV (Bailey/Borwein/Lopez de Prado/Zhu, J. Computational Finance, SSRN 2326253); False Strategy Theorem (Lopez de Prado & Bailey, American Mathematical Monthly 2021, Vol 128(9):825-831, SSRN 3221798); MRP (Alexander & Fabozzi, arXiv:2604.08356, submitted 2026-04-09); BOCPD (Adams & MacKay 2007, arXiv:0710.3742); Bai-Perron (2003, JAE 18:1-22); PELT (Killick/Fearnhead/Eckley 2012, JASA 107(500):1590-1598); '10 Reasons Most ML Funds Fail' (Lopez de Prado 2018, JPM 44(6):120-133, GARP whitepaper at the exact cited URL). Two minor citation imprecisions, non-load-bearing: (a) the False Strategy Theorem is tagged '2021' with a parenthetical 'SSRN 2014' — the SSRN working paper (3221798) actually circulated ~2018, not 2014; (b) the MRP arXiv ID 2604.08356 confirms an April-2026 preprint, i.e. barely two months old and not peer-reviewed, so its 'reliable lower bound' framing must be downgraded to 'emerging' and 'lower bound over observed regimes only.' On the six substantive claims: Claim 2 (clean TCA decomposition of decay vs cost) is REFUTED — liquidity/volatility regime change drives both jointly, so they are not orthogonal and a 'clean' causal split is over-confident. Claims 1 and 3 are CONFIRMED — MinTRL's i.i.d. assumption genuinely understates required N under autocorrelation/vol-clustering (fixable via Lo-style AR/HAC effective-N adjustment; report an interval not a point), and CUSUM/BOCPD truly face a power-vs-false-alarm dilemma in slow-arriving daily data (calibrate detection delay/ARL against backtest-era breaks). Claims 4, 5, 6 are NUANCED — DSR's threshold encodes a multiple-selection (trial-count) correction whose semantics differ from a single accumulating live sequence, so swap to SPRT or rolling PSR rather than copying the DSR threshold verbatim (though PBO's predicted decay band and a fixed-N=1 DSR are reasonably reusable); MRP should be an advisory input not a hard auto-retirement gate; and drift-triggered automation should trigger re-validation behind a pre-registered test plus human go/no-go, not fully automatic model promotion. No claim relies on a hallucinated source; the chief risks are over-stated precision (claim 1), false orthogonality (claim 2), and over-trusting an unvetted 2-month-old preprint as a hard gate (claim 5).

被降权/纠正的论断：
- `refuted` — Near-real-time TCA can cleanly separate 'signal decay' from 'execution-cost deterioration.'
  - 纠正：Soften the claim to: near-real-time TCA is a useful directional diagnostic but cannot cleanly/causally decompose decay vs cost because liquidity-regime change drives both jointly; any decomposition should be presented as assumption-dependent with explicit confounder caveats, not as an orthogonal split. Note the source already self-flagged probabilistic attribution as 'contested' — that flag is correct and should be retained.
- `nuanced` — DSR/PBO pre-deployment criteria can be reused directly as the SAME yardstick for live monitoring.
  - 纠正：Don't refute wholesale: PBO's predicted decay band IS reasonably reusable as a live yardstick (the citation's own framing), and DSR can be reused if you fix N=1 (which collapses DSR back to PSR vs a fixed threshold). The right statement: live monitoring should switch the test from a multiple-selection deflation (DSR with N>>1) to a single-sequence sequential/Bayesian test (SPRT or rolling PSR), not blindly copy the pre-deployment DSR threshold. So 'directly the same yardstick' is wrong, but the tools are adaptable — hence nuanced rather than refuted.
- `nuanced` — MRP (Minimum Regime Performance, cross-regime minimum risk-adjusted return) is a reliable lower bound for decay risk.
  - 纠正：Reframe from 'reliable lower bound' to 'lower bound over historically observed regimes only.' Tag maturity as emerging/unvetted (single preprint, not yet peer-reviewed). Do not use as a hard automatic retirement gate; use as one input alongside human review. The authors themselves frame it as a fragility lower bound, not a guarantee.
- `nuanced` — Drift-triggered automatic retraining keeps a strategy fresh and fights decay.
  - 纠正：Adopt the source's own resolution: limit 'automatic retraining' to engineering-triggered re-validation; gate any actual model swap to live behind a pre-registered acceptance test + human sign-off. 'Keeps the strategy fresh' is conditionally true; 'fully automatic model replacement fights decay' is overstated and refuted by the overfitting/noise-chasing evidence.

---


## [17] 资产无关统一抽象层  · 组 D

**机构级标准** — 机构级标准是把"可交易标的"建模为一个不可变、资产无关的身份对象（LEAN 的 Symbol/SecurityIdentifier、Zipline 的 Asset/ContinuousFuture），其上挂一个 golden-copy Security Master：跨数据源把 ticker/CUSIP/ISIN/SEDOL/FIGI 映射到一个内部稳定 ID（FIGI 是被 OMG 采纳为跨全资产类别的开放标准），并存 issuer 层级、上市/退市日、币种、资产类别、交易所、合约规格（tick/lot/合约乘数/最小变动）。所有"资产差异"必须被封进可声明的元数据与策略对象里、而非散落在流程代码：(1) 交易日历/Session 抽象（开/收/午休/早收/24x7/时区，用 zoneinfo），(2) 公司行动调整（拆股/分红/并购/退市/换名）走 map-file + factor-file 模型，回测层在 raw 与 adjusted/total-return 两种规范化模式间显式切换，且必须 point-in-time（PIT）以杜绝幸存者与前视偏差，(3) 期货换月（roll）与连续合约用 root_symbol + offset + roll_style(calendar/volume/OI) + adjustment(none/add/mul) 编码，roll 事件发 SymbolChangedEvent，(4) 永续合约的 index/mark/funding rate 三元组建模为一等数据 kind 并进 PnL，(5) 融券/借贷成本、(6) FX 换算到 base currency。判定标准（"加品类=填配置而非重写"）：新增资产类别只需注册一个 connector + 一份 instrument/calendar/合约规格配置 + 标注调整与 roll 规则，回测/组合/执行/归因引擎零改动。


### 关键论文 / 权威实践

- **Fundamentals of Perpetual Futures** ([链接](https://arxiv.org/abs/2212.06888))
  - _Songrun He, Asaf Manela, Omri Ross, Victor von Wachter · 2022 (rev. 2024) · arXiv:2212.06888 (q-fin.PR)_
  - 推导永续合约在无摩擦市场的无套利价格与有交易成本下的价格界；正式化 funding rate 作为多头按 perp 与 spot 差额周期性支付给空头的纠偏机制。实证：加密 perp 偏离大于传统货币衍生品、跨币种同向、随时间收敛；据模型构造的套利策略呈高 Sharpe。这是把永续/funding 接入资产无关抽象时唯一可引用的学术定价基础。
- **Designing funding rates for perpetual futures in cryptocurrency markets** ([链接](https://arxiv.org/abs/2506.08573))
  - _Jaehyun Kim, Hyungbin Park · 2025 · arXiv:2506.08573_
  - 为交易所如何设计最优 funding rate 给出理论框架，分析 index price / mark price / interest-rate 三组件的校准，使 perp 价与 spot 同步并抑制 basis 偏离。对 QuantBT 把 funding 建模成 connector 可配置数据 kind（而非硬编码 Binance 公式）提供方法学依据。属 emerging，未广泛复核。
- **Qlib: An AI-oriented Quantitative Investment Platform** ([链接](https://arxiv.org/abs/2009.11189))
  - _Xiao Yang, Weiqing Liu, Dong Zhou, Jiang Bian, Tie-Yan Liu (Microsoft Research) · 2020 · arXiv:2009.11189_
  - 提出 Calendar/Instrument/Feature 三 Provider 抽象 + PIT 存储 + 表达式引擎避免前视偏差；instrument 用 stock-pool（代码+起止日期）建模。是把数据层做成可插拔 provider 的范本，但官方文档明确只覆盖中/美股权益，对债券/衍生品/FX 无内建支持——印证'抽象在权益上成立、跨资产需扩展'。
- **Financial Instrument Global Identifier (FIGI) — Open Symbology standard** ([链接](https://www.openfigi.com/))
  - _Bloomberg / Object Management Group (OMG) · 2014 (持续维护) · OMG 标准 / OpenFIGI.com_
  - 免费开放、覆盖全资产类别（股/期权/期货/债/FX/贷款/MBS）的唯一标的标识符，可把 CUSIP/SEDOL/ISIN/ticker 映射到稳定 FIGI。是 Security Master 跨源对齐的事实标准，为'资产无关身份对象'提供工业级 ID 方案。注：是标准/工具非学术论文。

### SOTA 方法

- **不可变 SecurityIdentifier / Symbol 对象（LEAN 范式）** `[established]` — 把 market+security_type+ticker+date(上市/到期)+strike+option_right+has_underlying 编码进一个不可变 hash 身份；ticker 换名/公司行动时身份不变，所有 API 用对象而非字符串。是资产无关身份的黄金范式。
- **连续合约抽象：root+offset+roll_style+adjustment（Zipline ContinuousFuture）** `[established]` — 连续期货 = 链规格（root_symbol, offset=0主/1次, roll=calendar/volume/OI, adjustment=none/add/mul）；roll finder 在每个日期选当前合约，roll 发 SymbolChangedEvent，价格按 add/mul 回填。把'换月'从流程代码下沉为可声明规格。
- **map-file + factor-file 的 PIT 公司行动模型（LEAN）** `[established]` — ticker 变更存 map-file，拆股/分红存 factor-file；回测可在 raw 与 adjusted/total-return 规范化间显式切换，live/raw 模式按 SplitFactor 自动调仓。把'公司行动'与'PIT 正确性'机制化、可审计。
- **Security Master golden-copy + FIGI 跨源映射** `[established]` — 多 vendor 标识符映射到内部稳定 ID，存 issuer 层级/币种/资产类别/合约规格，配置价格优先级与混源规则，发布单一真值。买卖双方与 vendor 间信息无缝流转的工业标准。
- **交易日历/Session 工程库（exchange_calendars / pandas_market_calendars）** `[established]` — 50+ 全球交易所日历，支持假日/早收/午休/24x7、产品级日历、zoneinfo 时区、session/minute 级查询；get_calendar() 工厂模式。把'什么时候能交易'从硬编码变成按交易所名取配置。
- **DataFrame 数据库做跨资产宽表存储（ArcticDB）** `[established]` — Bloomberg+Man Group 开源，bitemporal/版本化('time travel')、超宽时序、秒级处理十亿行；BQuant 用它统一多资产类别+另类数据。为资产无关数据层提供存储底座（QuantBT 现用 polars 落盘，可演进方向）。
- **永续 funding 三元组（index/mark/funding）建模为一等数据 kind** `[emerging]` — 把 funding rate 当成与 OHLCV 并列的可配置数据 kind 并入 PnL，而非把 Binance 公式硬编码进执行层；学术定价基础见 He et al. 2022 / Kim-Park 2025。
- **回测期最优换月规则（volume/OI roll vs 固定日历 roll）** `[contested]` — 用成交量或持仓量驱动 roll 比固定日历 roll 更贴近真实流动性迁移，但哪种最优、对回测收益的影响仍有分歧，不同数据商连续合约拼接口径不一导致结果不可比。

### 差距

- 无一等 Instrument/SecurityIdentifier 对象：标的靠 symbol(str)+market(str)+AssetClassTag 文字字面量松散表示（connectors/base.py），没有不可变身份、没有合约规格（tick/lot/乘数/币种/上市退市日），换名/公司行动无身份保持机制——这是'加品类要改代码'的根因。
- 无 Security Master / 跨源 ID 映射：没有 CUSIP/ISIN/FIGI/SEDOL→内部稳定 ID 的 golden-copy 层；多源同一标的对齐靠 symbol 字符串约定，跨 vendor 拼数据时身份脆弱。
- 无交易日历/Session 抽象：codebase 中 app/ 下无 calendar 模块；统一 schema 仅把 ts 存 UTC，但'哪些时刻可交易/午休/早收/24x7 vs 沪深开收'没有一等日历对象，回测对齐与执行窗口靠隐式约定。
- 无连续合约/换月抽象：无 ContinuousFuture 概念（root+offset+roll_style+adjustment），crypto_perp 已是 AssetClassTag 但永续/交割合约的 roll、到期、合约规格未建模；接股指期货/商品期货需重写。
- 公司行动调整非 PIT 一等机制：无 map-file/factor-file 等价物，raw vs total-return/adjusted 规范化模式未显式化为可切换 flag；幸存者偏差由 M2 动态池处理但与'调整因子 PIT'未打通成统一对象。
- funding/借贷/FX 换算未一等化：funding rate 在 base.py 仅作为 supported_data_kinds 字符串存在，未建模为进 PnL 的现金流；融券/借贷成本、跨币种到 base currency 的 FX 换算缺统一抽象。
- AssetClassTag 是封闭 Literal 枚举：新增'股指期货/可转债/期权/FX'需改源码枚举与下游分支，违背'填配置而非重写'；缺一个由配置驱动的资产类别注册表 + per-class 规则插件。

### Agent OS 在这一环的角色（服务零代码用户）

这一环对零代码用户最反直觉也最危险，因为'资产差异'恰恰是看不见的坑（拆股没复权、期货换月跳空、永续不复权 funding、A股午休/T+1）。Agent OS 的角色是把这些工程差异翻译成经济学语言并用流程闸门替用户兜底：(1) 需求澄清 agent 在用户说'我想测一个 A股动量策略'或'我做 BTC 永续套利'时，自动从 Security Master 取该资产类别的'隐含约束清单'，用经济学者能懂的话确认——'A股有涨跌停板和 T+1，你的换手假设受影响吗''你说的收益要含分红吗（total-return）还是只算价格''永续每 8 小时要付/收 funding，这是你策略的主要收益来源还是成本'，把抽象层的每个开关变成一个 go/no-go 经济判断而非代码参数。(2) 严谨度翻译成'信任三件套'：可复现（同一 Instrument 身份+dataset_version+调整模式哈希=可重跑）、谱系（这条净值用了哪个连续合约拼接规则、哪天换月、复权因子来自哪个 PIT 快照，一张谱系图给非程序员看）、验证闸门（系统检测到'未复权却跑了跨除权日的股票'或'永续回测漏了 funding 现金流'时自动红灯阻断，并用一句话解释为什么这会让回测虚高）。(3) 渐进披露：小白只看'已为你按 A股规则配置好（含分红、午休、T+1），点继续'；经济学者可展开看到三个可调旋钮及其经济含义；会写代码的 quant 才看到底层 Instrument 配置 YAML。关键是：因为他们读不懂代码，唯一能信任 agent 的支柱就是'这条流程的每个资产相关假设都被显式登记、可解释、且有闸门挡住已知陷阱'。

### 建议

- 引入一等 InstrumentSpec 对象（不可变身份）：把 symbol(str)+market(str)+AssetClassTag 升级为 dataclass，含 stable_id、asset_class、currency、tick_size、lot_size、contract_multiplier、listing/delisting date、(衍生品)expiry/strike/right、has_underlying；所有下游(universe/portfolio/execution/attribution)改用对象而非字符串。对照 LEAN SecurityIdentifier。  `[→M3(数据/连接器) + M1(StrategyGoal 引用 instrument), eff=high, lev=high]`
- 把 AssetClassTag 封闭 Literal 改成配置驱动的资产类别注册表：每个资产类别注册一份 per-class 规则插件（日历名、复权规则、roll 规则、funding/借贷/FX 规则、约束如涨跌停/T+1）。新增'股指期货/可转债/FX'=注册一份配置，回测引擎零改动。这是'填配置而非重写'的落地核心。  `[→M3 + M2(universe/regime 按 class 取规则), eff=high, lev=high]`
- 接入交易日历/Session 抽象：直接集成 exchange_calendars 或 pandas_market_calendars，新增 app/calendar 模块，按 market 取日历（沪深含午休/T+1、crypto 24x7、未来期货产品级日历），回测对齐与执行窗口走日历而非隐式约定。低成本高杠杆，库成熟。  `[→M3 + M9(执行窗口) + M10(回测对齐), eff=low, lev=high]`
- 公司行动 PIT 一等化：建 map-file/factor-file 等价的 adjustment 层，回测显式暴露 raw / adjusted / total-return 三档规范化 flag，并与 M2 PIT 动态池打通；agent 在跨除权日时自动校验并红灯阻断'未复权跑除权股'。对照 LEAN map/factor file。  `[→M3 + M2(PIT) + M10(归因正确性), eff=med, lev=high]`
- 连续合约/换月抽象：实现 ContinuousFuture(root+offset+roll_style{calendar,volume,OI}+adjustment{none,add,mul})，roll 发 SymbolChangedEvent，回测层消费；先支撑 crypto 交割合约与未来股指期货。对照 Zipline ContinuousFuture。  `[→M3 + M9(执行) + M13(编排 roll 调度), eff=med, lev=med]`
- 把 funding/借贷/FX 现金流一等化进 PnL：funding rate 从'字符串 data_kind'升级为进回测现金流的可配置组件（index/mark/funding 三元组），融券成本与跨币种 FX 换算到 base currency 统一抽象；定价基础引 He et al. 2022。  `[→M9(风控/执行) + M10(回测 PnL), eff=med, lev=med]`
- Security Master + FIGI 映射层（轻量起步）：建内部 stable_id 与 ticker/ISIN/FIGI 映射表，多源同一标的按内部 ID 对齐而非字符串约定；先支持现有 connector，预留 OpenFIGI API 接口。对照 Intrinio/Arcesium Sec Master + OpenFIGI。  `[→M3 + M12(注册表/谱系), eff=med, lev=med]`
- Agent 侧'资产隐含约束清单 + 信任三件套'：需求澄清 agent 按 InstrumentSpec 自动列出该资产类别的经济学约束并逐条 go/no-go；谱系图展示复权模式/换月规则/funding 来源；闸门挡已知陷阱（漏复权、漏 funding、午休/T+1 与换手假设冲突）。  `[→M14(Agent 编排) + M19(教学/coach 翻译) + M20(Live 闸门), eff=med, lev=high]`

### 对抗式核查裁决 — 总体置信度：**high**

_纠正摘要_: 四篇所引文献全部真实存在、作者/年份/arXiv 编号全部对得上：(1) Fundamentals of Perpetual Futures, He/Manela/Ross/von Wachter, 2212.06888, 2022 投稿 2024-08 修订至 v6——描述准确，但『高 Sharpe』需补限定：含零售成本后≈1.8、零费率做市商≈3.5，且论文自述偏离每年约 -11% 收敛，故应视为衰减型而非稳定 alpha。(2) Designing funding rates…, Kim & Park, 2506.08573, 2025-06 提交——真实，但属纯理论(path-dependent BSDE+套利定价，为发行方对冲/复制组合服务)，原文并未明确以『index/mark/interest-rate 三组件校准』为框架，引用中该三组件表述属轻度引申，应弱化；且为未经同行评审的新近预印本。(3) Qlib, 2009.11189, Microsoft 2020——作者全对，Calendar/Instrument/Feature+PIT+stock-pool 描述准确；GitHub Issue #107 证实 futures 支持自 2020 至今 open 未实现，跨资产需自行扩展属实。(4) FIGI/OpenFIGI——标准真实，但加密由 Kaiko 第三方发行、约 8000 资产、以法币对为主、未见 on-chain/DEX/永续完整及时覆盖。\n\n六条论断核查结果：claim1(架构非『填配置』)confirmed——11 个非测试模块 hard-code 资产类别分支、AssetClass/AssetClassTag 与 CostModel 均为封闭 Literal/Union、无 InstrumentSpec 对象。claim3(Qlib 跨资产需扩展)与 claim6(FIGI 加密覆盖不足)confirmed。claim4(漏算 funding 致虚高)confirmed 并量化：基线 ≈10.95%/年(0.01%/8h)、极端达 66% APR，但重要性按持仓时长缩放，非对所有 perp 策略等量(持仓型显著/高换手次要)。claim2 与 claim5 标 nuanced：claim2 的『高 Sharpe』被原研究自身的成本限定与收敛性削弱；claim5 的 roll 不一致是前瞻性风险——QuantBT 现仅处理永续(data_pull.py 显式过滤非 PERPETUAL)、全仓无任何 roll 拼接逻辑，roll 问题被绕过，须等引入交割/到期合约后才成立。无虚构文献，主要纠正集中在对 Sharpe 的夸大限定、Kim-Park 三组件引申、funding 重要性的策略类型条件化，以及 roll 风险的时态澄清。

被降权/纠正的论断：
- `nuanced` — He et al.(2212.06888) 据无套利模型构造的 funding-rate 套利『高 Sharpe』——需厘清成本前/后、样本期/交易所、是否仍在 2024-2026 成立。
  - 纠正：应表述为：含零售成本后 Sharpe≈1.8、零费率做市商≈3.5；样本主要基于 Binance（最大交易所）；论文本身指出偏离每年约 -11% 收敛，故 2024-2026 的可实现收益大概率已显著低于样本期，须当作衰减型而非稳定 alpha。
- `nuanced` — 连续合约用 volume/OI roll 优于固定日历 roll 是 contested；QuantBT 若自建 roll 与外部已拼好的连续合约混用会引入隐性不一致。
  - 纠正：应限定为前瞻性风险：QuantBT 现仅支持永续(无 roll)，roll 不一致问题在引入交割/到期合约前不会发生；届时确需统一拼接口径、避免与外部连续合约混用。

---
