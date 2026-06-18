# 03 · 谱系/溯源总线（PROV / OpenLineage / MLflow lineage）

> 机构级 Agent OS 成品环节深挖 · 全程 Opus 4.8 · 对抗式核查已降权 · 重心=前沿研究+概念级推荐 · 不含 file:line 代码接线
> 簇 A

## 1. 一句话定位

把 prompt / response / 工具调用 / 产出 / dataset_version / 下游指标接成一条**可审计、可重现、可归因**的 DAG，作为机构级 Agent OS 的 **P0 脊柱**——但它只负责"这是怎么来的、能否重现、错在哪一步"，**绝不等于"结论可信"**；信任必须由独立的校准证据（OOS / CSCV / PBO / 持续性能反馈 / regime 健壮性）承载。这一"谱系≠信任"的解耦是本环节最核心、且经人因文献核实成立的诚实判断。

## 2. 前沿 SOTA 与代表系统

技术上，"agent 工作流溯源"正从三个成熟领域快速收敛：数据工程（OpenLineage / Marquez / DataHub）、科学工作流溯源（W3C PROV / RO-Crate / Flowcept）、LLM 可观测（OTel GenAI / OpenInference / Langfuse / Phoenix）。代表系统：

- **PROV-AGENT + Flowcept**（最对口的开源 agentic 溯源栈）。Flowcept 是分布式溯源框架（Redis/Kafka/SQLite/对象存储 broker + 中央汇聚）；PROV-AGENT 在其上用装饰器 `@flowcept_agent_tool` 把 MCP 工具包成 PROV Activity、用 `FlowceptLLM` 捕获 prompt/response/模型元数据，扩展 W3C PROV 成 `AIAgent / AgentTool / AIModelInvocation / Prompt / ResponseData` 等类，兼容 CrewAI/LangChain/OpenAI。直接对应本项目"prompt/response/工具/产出接成 DAG"的需求。**重要限定见第 7 节：仅在单一 ORNL HPC 工作流上做 preliminary 演示，不可直接外推到金融 agentic 场景。** <https://arxiv.org/abs/2508.02866>
- **OpenLineage + Marquez**（数据/作业谱系的产业事实标准）。OpenLineage 是 lineage 事件规范（Run/Job/Dataset 三实体 + START/COMPLETE/FAIL/ABORT 生命周期 + 可插拔 facets：schema/dataSource/version/columnLineage/dataQualityAssertions）；Marquez 是其参考实现与可视化后端。生产者含 Airflow/dbt/Spark/Great Expectations。适合承载 `dataset_version` 与下游指标的谱系。<https://openlineage.io/docs/spec/object-model/>
- **MLflow 3（dataset + model lineage）**。每个注册模型版本回链到产出它的 run、代码版本、参数、数据集（Dataset 抽象 + DatasetSource 回链原始数据）。MLflow 3（2025）扩展到 GenAI tracing、agent 评估、支持 OpenTelemetry GenAI semconv 摄取。本项目已有 ML/.pkl + DL/.pt 模型与回测桥，MLflow 风格的 model→run→data→metric 回链可直接复用。<https://mlflow.org/docs/latest/ml/dataset/>
- **OpenTelemetry GenAI semconv / OpenInference**（agent 运行时事件发射的趋同标准）。词汇表覆盖 prompt/response/token/tool 调用/provider 元数据，`create_agent`/`execute_tool` 等 span；LangChain/CrewAI/AutoGen 原生发射，Datadog/Honeycomb/New Relic 已支持。是"输入层"，与 PROV/OpenLineage 的"持久审计层"互补。**限定见第 7 节：agent-span 部分截至 2026 仍为 Development/experimental，未冻结为 stable，"标准"一词略夸大成熟度。** <https://opentelemetry.io/docs/specs/semconv/gen-ai/gen-ai-agent-spans/>
- **Langfuse / Arize Phoenix**（开源 LLM/agent 可观测平台）。Phoenix 基于 OpenInference/OTLP，开箱支持 Claude Agent SDK、OpenAI Agents SDK、LangGraph、CrewAI、DSPy 自动埋点；Langfuse（MIT）可自托管、OTel 原生、含 prompt 版本管理与成本追踪。可作为"捕获 prompt/response/tool 调用"的现成前端，再把 span 导出到持久谱系存储。Langfuse 尤其契合 D2（真隔离/加密落盘）的单用户强隐私要求。<https://github.com/Arize-ai/phoenix>
- **DataHub / OpenMetadata / Egeria**（通用元数据目录/谱系消费端）。三者都能摄取 OpenLineage 事件，提供列级谱系与影响分析（impact analysis）。**对单用户中低频系统可能偏重**，仅作企业级"查询/治理层"参考。<https://datahub.com/blog/open-source-data-lineage/>
- **RO-Crate Workflow Run / Provenance Run profile**（可移植可重现的"运行包"标准）。把一次工作流运行的输入/输出/代码/参数/PROV 关系打包成"研究对象包"（基于 Schema.org、对齐 W3C PROV），已被多个工作流系统实现。对本项目"让回测/训练 run 可被冷启动重现并交叉比较"直接可借鉴。<https://www.researchobject.org/workflow-run-crate/profiles/0.5/workflow_run_crate/>

## 3. 关键论文（每条带 URL）

- **PROV-AGENT: Unified Provenance for Tracking AI Agent Interactions in Agentic Workflows**（IEEE e-Science 2025，ORNL）。扩展 W3C PROV + 引入 MCP，把 prompt/response/工具/模型调用接成端到端可查询 DAG，演示"回溯决策到原始输入 / 定位幻觉 prompt / 追踪误差传播 / 根因分析"等查询。**诚实 caveat（作者自标）：评估为 Preliminary，无开销/规模化数据，真实 live 数据连接 still under development，且只 assert 而未实证"溯源能提升信任或降低幻觉危害"——属"已发表但未充分验证"，不可当成定论。** Souza, Gueroudji, DeWitt, Rosendo, Ghosal, Ross, Balaprakash, Ferreira da Silva。<https://arxiv.org/abs/2508.02866>
- **How transparency modulates trust in artificial intelligence**（Patterns/Cell 2022, PMC9023880）。"透明度→恰当信任"的核心反证：更多透明度不自动改善信任校准；特征重要性解释会诱发"自动化自满"、过量透明可致信息过载使人在模型出错时仍盲从；置信数值常超认知负荷；多数实验任务过简、生态效度存疑。**引用归属更正（见第 7 节）：实际作者为 Zerilli, Bhatt & Weller（PubMed 35465233），非研究原稿误标的"Schmidt et al."。** <https://pmc.ncbi.nlm.nih.gov/articles/PMC9023880/>
- **Measuring and Understanding Trust Calibrations for Automated Systems**（CHI 2023，Bach, Khan, Hallock, Beltrão, Sousa）。从 1000+ 文献筛出 96 篇实证研究的系统综述：透明度干预（不确定性/置信/可靠性更新）有用但非万灵药，会增加 workload，解释类结果混杂（有正有零）；低可靠性运行的元信息可能反而诱发过度信任；**持续（而非累计）性能反馈才更能校准信任**。提示本项目应把"校准证据"与"谱系"分离，优先用持续性能反馈而非堆砌溯源细节。<https://dl.acm.org/doi/fullHtml/10.1145/3544548.3581197>
- **Reproducibility in machine-learning-based research: Overview, Barriers and Drivers**（Semmelrock et al., AI Magazine 2025 / arXiv:2406.14325）。系统梳理 ML 可重现性危机：缺失数据出处是模型不可重现的主因之一，但**谱系元数据是必要不充分**——还需完整 train/val/test split、预处理、环境与标准化报告。大规模分析显示仅约 **14% 可精确重现**（14.03% score-pair 精确匹配、59.2% 复现更差）。<https://arxiv.org/html/2406.14325v2>
- **Fine-Grained Traceability for Transparent ML Pipelines**（Chen, Liu, Fayek，2026-01，arXiv:2601.14971，已被 ACM Web Conference 2026 收录，DOI 10.1145/3774904.3793005）。把可追溯下沉到样本级（哪些训练样本影响了输出），用哈希函数+承诺方案做可验证（防篡改）追踪，CIFAR-10 上验证。**代价：样本级追踪的计算开销——对中低频策略多半是 gold-plating。** <https://arxiv.org/abs/2601.14971>
- **Workflow provenance in the lifecycle of scientific machine learning**（Souza et al., Concurrency and Computation 2022 / arXiv:2010.00330）。奠基性综述：工作流溯源如何贯穿科学 ML 生命周期以支撑可重现性、可解释性与实验理解，是 PROV-AGENT/Flowcept 的方法论根基，论证"端到端工作流溯源"相对孤立日志的价值。<https://arxiv.org/pdf/2010.00330>
- **Recording provenance of workflow runs with RO-Crate**（Leo et al., PLOS ONE 2024, PMC11386446 / arXiv:2312.07852）。提出 Workflow Run / Provenance Run RO-Crate profile：不同粒度记录工作流运行的 PROV、打包输入/输出/代码、对齐 W3C PROV，支持跨异构系统的运行比较。为"可移植可重现 run 包"提供标准。<https://www.ncbi.nlm.nih.gov/pmc/articles/PMC11386446/>

## 4. 机构最佳实践 / 标准

> 注意：以下合规义务多数面向"投放市场的高风险系统"或"受监管金融机构"。**单用户个人研究系统是否真正落入这些法规适用主体范围存疑（见第 7、8 节）**——这里列出是作为设计参照与"成品上线后若进入受监管语境"的对齐框架，而非已确证对本项目硬性触发的约束。

- **EU AI Act 第 12 条（record-keeping）与第 19 条（自动日志留存）**。高风险系统须在全生命周期自动记录事件日志，捕获输入/输出/决策点以支持可追溯；**至少留存 6 个月**（属实）；2026-08-02 对高风险系统全面适用（属实）。**降权（见第 7 节）：法条本身只要求"automatically record events (logs)"，并未明文要求 cryptographic tamper-evidence / 时间戳 / 可独立验证——这些是合规分析师提出的最佳实践 gloss（SHOULD），不是法条明文义务（MUST）。** <https://artificialintelligenceact.eu/article/12/>
- **Federal Reserve SR 26-2（2026-04-17，取代 2011 年 SR 11-7）/ OCC Bulletin 2026-13**。模型风险管理仍要求文档详尽到"知情方能理解模型运作并重现/评估其结果"，数据质量与血缘控制须保证输入从源到产出可追溯，并按机构规模/复杂度做比例化（proportionality）。**重大降权（HIGH，见第 7 节）：该指引明确把 generative AI 与 agentic AI 排除在适用范围之外（理由"novel and rapidly evolving"），仅要求"apply broader risk management practices"。把它当作本项目（明确定位为 agentic Agent OS）谱系总线的硬性合规驱动属外推过度——对 agentic 部分恰恰不直接适用。** <https://www.federalreserve.gov/supervisionreg/srletters/SR2602.htm>
- **NIST AI RMF / NIST AI 100-4**。把可追溯（traceability）与文档/出处列为可信 AI 支柱；"信息完整性"议题下多数行动聚焦数据出处（data provenance）。非强制但权威的对齐框架。<https://nvlpubs.nist.gov/nistpubs/ai/NIST.AI.100-4.pdf>
- **BCBS 239（风险数据汇总与报告原则）**。要求银行具备数据血缘（lineage）能力以保证风险数据从源到报告的准确可追溯。**轻度降权：面向 G-SIB/D-SIB，对单用户（D4）中低频研究系统不构成任何法律义务；可作设计参照，但不应与"真正适用"的硬约束并列陈述为本项目合规驱动（属二手综述）。** <https://www.ovaledge.com/blog/bcbs-239-data-lineage>
- **内容/产物来源标准**。C2PA（内容凭证，Adobe/微软/BBC/Sony 等，支持嵌入与外置元数据、签名、derived-from 链）与软件供应链的 in-toto/SLSA（签名 attestation 绑定 who+claims+signature、透明日志）。结合哈希链/Merkle 根可做防篡改审计，为"产出物可签名、可验证来源"提供成熟标准件。<https://c2pa.org/>

## 5. 对 QuantBT 这套架构的推荐方向（概念级）

1. **把谱系总线定位为"可审计/可重现/可归因"的脊柱，而非"信任来源"。** 明确四层分工：(a) 发射层用 OTel GenAI/OpenInference 标准词汇捕获 prompt/response/tool 调用；(b) 语义层用 W3C PROV（Entity/Activity/Agent + used/wasGeneratedBy/wasInformedBy）把一切建模为可查询 DAG；(c) 数据谱系层用 OpenLineage facets 表达 dataset_version/job/run 与下游指标；(d) 打包层用 RO-Crate 风格 run 快照支撑冷启动重现。PROV-AGENT/Flowcept 作**参考架构而非照抄**。

2. **信任与谱系解耦（对应已确证的反证）。** 绝不让 UI/对话把"已生成完整 DAG"呈现为"结论可信"。信任由独立校准证据（OOS/CSCV/PBO、持续性能反馈、regime 健壮性）承载；谱系只回答"怎么来的、能否重现、错在哪一步"。为避免"透明度过载诱发过度信任"，对非技术用户默认给精炼的因果链 + 可信度旗标，细粒度 DAG 作为可下钻的次级视图。

3. **为"恰当信任"做主动的反向用途：把谱系总线设计成 agent 自检与红队的底座。** 根因回溯、定位幻觉 prompt、追踪误差跨 agent 传播——这是谱系在本项目最被证据支持的价值（工程可审计），而非"让用户更信任"。

4. **可重现性需要谱系之外的完整捕获（已确证：必要不充分）。** run 节点必须连同 dataset_version、train/val/test split、预处理、随机种子、库/环境指纹一起锁定并哈希，否则 DAG 完整也不可重现。把这些做成 PROV Entity 的强制属性。

5. **防篡改与合规内建，但按"可能适用"而非"已确证强制"来裁剪强度。** 审计日志可用哈希链/Merkle（SLSA/in-toto 思路）做 tamper-evident、产出物可签名（C2PA 思路）；落盘加密对齐 D2（真隔离）。注意这些更多是工程稳健性与未来合规预留，**而非已被法条明文强制的义务（见第 4、7 节降权）**。

6. **按比例化（proportionality）裁剪粒度。** 本项目是单用户（D4）、中低频，不需 HFT 级或样本级追踪；优先锁定决策关键节点（意图→策略假设→因子→数据集→回测/训练→风控护栏→产出），把昂贵的列级/样本级谱系列为可选下钻而非默认。

7. **谱系覆盖率与新鲜度当作一等可观测指标。** "覆盖不全 + 文档老化（血缘腐烂）"是谱系系统失败主因。让谱系随 agent 工程**自动发射（装饰器/拦截器埋点，而非人工补录）**，并对"未被谱系覆盖的执行路径"显式告警，避免审计盲区却自以为全覆盖。

8. **与现有资产（模型中心/训练台/回测桥/OOS）对齐而非新建竖井。** 复用 MLflow 风格 model→run→data→metric 回链，把回测净值/OOS 指标作为 OpenLineage 下游 Dataset/facet 挂上同一 DAG，使"训练→回测桥"天然成为谱系的一段。

## 6. 架构级参考（少量伪代码 / schema 草图，非代码接线）

> 仅为示意，**不接线到现有代码、不点 file:line**。

PROV 风格的核心实体（语义层，对齐 PROV-O `Entity/Activity/Agent`）：

```
Activity: AgentStep / ToolCall / ModelInvocation / BacktestRun / TrainRun
  - id, started_at, ended_at, status
  - used        -> [Entity ...]        # 消费的输入
  - wasInformedBy -> [Activity ...]     # 上游决策依赖

Entity:   Prompt / ResponseData / DatasetVersion / ModelArtifact / MetricSet
  - id, content_hash, created_at
  - wasGeneratedBy -> Activity
  - wasDerivedFrom -> [Entity ...]

Agent:    AIAgent(model, role) / HumanUser
  - wasAssociatedWith -> Activity
```

可重现性强制属性（挂在 `DatasetVersion` / `*Run` Entity 上，对应第 5 节第 4 点）：

```yaml
run_snapshot:        # RO-Crate 风格运行包
  dataset_version: { id, content_hash, source: { tushare|binance, asof } }
  split:           { train, val, test, scheme: walk_forward }
  preprocessing:   { steps: [...], params_hash }
  seed:            <int>
  env_fingerprint: { python, libs_lock_hash, platform }
  code_version:    { git_sha }
  # 缺任一项 -> 标记 "DAG 完整但不可重现"
```

发射层（自动埋点，避免人工补录与覆盖盲区，对应第 5 节第 7 点）：

```python
@provenance_tool          # 装饰器把工具调用包成 PROV Activity
def run_backtest(strategy, dataset_version): ...

# OTel GenAI span -> 拦截 prompt/response/tool -> 转 PROV Entity/Activity
# 未被装饰/未发射的执行路径 -> coverage 监控显式告警
```

下游指标挂同一 DAG（OpenLineage facet 思路，对应第 5 节第 8 点）：

```
BacktestRun --wasGeneratedBy--> MetricSet{ oos_sharpe, pbo, cscv_flag }
  facet: dataQualityAssertions / version / dataSource
  # 信任旗标来自 MetricSet（独立校准证据），不来自 DAG 是否完整
```

防篡改（可选，工程稳健性预留，非法条明文强制 —— 见第 7 节）：

```
audit_log[n].prev_hash = H(audit_log[n-1])   # 哈希链 / Merkle
artifact.signature      = sign(content_hash)  # C2PA / in-toto 思路
```

## 7. 降权 / 争议 / 陷阱（对抗核查结论）

> 本节原样保留对抗核查的降权词与限定。

**降权项（按严重度）：**

- **【HIGH】SR 26-2（2026-04-17）/ OCC Bulletin 2026-13 作为本项目 agentic 谱系总线"合规驱动"——属实质性外推过度。** 经一手与权威二手核实（Federal Reserve SR2602；Sullivan & Cromwell 2026-04 memo；OCC Bulletin 2026-13）：该指引**明确把 generative AI 与 agentic AI 排除在适用范围之外**（理由"novel and rapidly evolving"），仅要求"apply broader risk management practices"。它还把"简单算术/确定性规则"移出 model 定义、取消年度强制 revalidation 改为风险比例化，方向是**减负**，与"更详尽谱系=合规"的暗示有张力。日期与取代关系属实（verified-real-but-misapplied）。<https://www.occ.gov/news-issuances/bulletins/2026/bulletin-2026-13.html>

- **【HIGH】EU AI Act 第 12/19 条"tamper-evident / 带时间戳 / 可独立验证"——把分析师 SHOULD 升格为法条 MUST，夸大了硬约束强度。** 核实条文与多解读来源（Help Net Security 2026-04；FireTail）：Article 12 只要求"automatically record events (logs) over the lifetime"，Article 19/26 要求"至少留存 6 个月"。法条本身**未明文要求**密码学防篡改/时间戳/可独立验证——这是合规分析师的解释性 gloss（overstated）。"6 个月留存""2026-08-02 高风险全面适用"属实。<https://www.firetail.ai/blog/article-12-and-the-logging-mandate-what-the-eu-ai-act-actually-requires>

- **【MEDIUM】核心反证论文作者张冠李戴（citation-error）。** "How transparency modulates trust in AI"（Patterns 2022, PMC9023880）实际作者为 **Zerilli, Bhatt & Weller**（PubMed 35465233），作者列表**根本没有 Schmidt**。实质结论方向无误，但归属错误损害可核查性，且暗示"两篇独立证据"而实为一篇被错标。<https://pubmed.ncbi.nlm.nih.gov/35465233/>

- **【MEDIUM】"PROV-AGENT 跑通五类查询=本项目脊柱"——把单一 ORNL HPC 工作流外推到金融 agentic 场景，属可外推性未经证实。** 论文 v3 全文：评估明确自标 **Preliminary**（§IV-B），仅在**一个 ORNL 增材制造（additive manufacturing）HPC 工作流**上演示，传感器-仿真的真实 live 数据连接 **still under development**，无任何开销/规模化数据，**未实证溯源提升信任或降低幻觉危害**。应明确：这是"单用例、preliminary、不可直接外推到金融 agentic"，而非"跑通=可移植蓝图"。<https://arxiv.org/abs/2508.02866>

- **【LOW】OTel GenAI / OpenInference 称"标准"——partially-overstated。** agent/framework spans 截至 2026 仍为 **Development/experimental** 状态（属性名仍可能变动，需 `OTEL_SEMCONV_STABILITY_OPT_IN` 双发），未冻结为 stable。它是事实趋同方向与产业广泛采用，但把它当作"可长期依赖的持久审计输入层契约"有轻微高估风险。"发射层 vs 审计层分层"判断本身正确。<https://opentelemetry.io/docs/specs/semconv/gen-ai/gen-ai-agent-spans/>

- **【LOW】BCBS 239 作为本项目合规底座——轻度下调。** lineage 要求属实但面向 G-SIB/D-SIB，对单用户（D4）中低频系统无法律义务（属二手综述）；作设计参照可以，不应与真正适用的硬约束并列陈述为合规驱动。

**陷阱（pitfalls）：**

- 把"谱系完整"误当"结论可信"。已确证反证：透明度/出处不是信任万灵药，过量信息会诱发自动化自满与过度信任（Patterns 2022、CHI 2023）；对非技术用户尤其危险——精美 DAG 会制造未经校准的信心。
- 引用 PROV-AGENT 时夸大其证据级别（preliminary、单用例、未实证→信任/降幻觉）。
- 以为有 dataset_version 谱系就能重现（必要不充分，缺 split/预处理/种子/环境仍不可重现，约 14% 可精确重现）。
- 低估谱系覆盖率与维护成本（"血缘腐烂"）；无自动化时谱系数周内过时，黑盒变换/遗留系统造成盲区。需自动埋点 + 未覆盖路径告警。
- 样本级/列级细粒度追踪的开销与过度工程（fine-grained traceability 有明确计算开销，对单用户中低频多半是 gold-plating）。
- 防篡改与时间戳缺位导致合规不达标——但注意此条本身建立在"EU AI Act 强制 tamper-evident"的前提上，而该前提已被降权为分析师 gloss（见上）。
- 标准选型混淆层次：OTel GenAI/OpenInference 是发射标准、不是审计 DAG；OpenLineage 是数据谱系事件、不是 catalog；PROV 是语义模型。错把其一当全栈会留缺口。
- 二手监管数字/日期未经核对（如 SR 11-7 已于 2026-04-17 被 SR 26-2 取代，需引一手来源）。

**对抗核查总评（verdict）：整体可信度中高。** 技术栈梳理与四层分层判断扎实准确；最核心的"谱系≠信任"判断经人因文献核实成立，研究对 PROV-AGENT 的 caveat 写得罕见诚实。但有上述 HIGH/HIGH/MEDIUM 三处需下调。**最大的结构性盲点**：研究通篇假定 EU AI Act/SR/BCBS 等合规义务对本项目成立，却未质疑"单用户个人研究系统是否真的落入这些面向受监管金融机构/市场投放主体的法规适用范围"——若不适用，则整段"合规驱动→P0 脊柱"的优先级论证会被显著削弱。**建议：把谱系总线的价值主张收敛到"工程可审计/可归因/可重现/agent 自检底座"（证据扎实），而非"合规强制"（适用性存疑）与"提升用户信任"（已被证伪）。**

## 8. 开放问题

1. **隐私/PII 与谱系全量捕获的根本张力（research 未触及）。** 把 prompt/response/工具/数据全部接成持久可审计 DAG，与 D2（真隔离/加密落盘）和 GDPR"被遗忘权"/数据最小化直接冲突——**tamper-evident 哈希链与"可删除某条 PII"在密码学上是对立目标**。如何在同一条 DAG 上让 EU AI Act 的日志义务与 GDPR 删除义务共存（哈希指针 vs 明文留存、可删除性 vs 不可变性）？
2. **谱系总线本身成为攻击面/被污染的风险。** 若 agent 自检与红队都建立在谱系 DAG 上，能写入/伪造谱系事件的对手（或被 prompt 注入操纵的 agent）即可制造"看似可信的虚假因果链"。**签名只保证传输后不可改，不保证记录的内容真实**（garbage-in）——这对"谱系做信任底座"是结构性弱点。
3. **对中文 / A股+加密这一具体栈的落地成本与生态缺口。** PROV-AGENT/Flowcept/OpenLineage/Marquez 全面向 HPC 科学工作流或西方数据栈；对接 Tushare/Binance、A股 PIT 数据、已有 ML/.pkl+DL/.pt 与回测桥的实际工程量，以及 Redis/Kafka/对象存储 broker 在单机单用户下是否过重，未做现实评估。
4. **"谱系≠信任"虽正确，但信任载体 OOS/CSCV/PBO 自身证据强度也存争议**（CPCV 仅在合成受控环境显著优于 walk-forward、PBO/DSR 有已知局限）。把信任全部外包给"独立校准证据"却未承认那一侧同样脆弱，存在"把问题推给隔壁环节"的风险。
5. **成本/收益量化缺位。** 在没有外部审计方、没有监管检查、单一用户既是开发者又是使用者的情形下，EU AI Act/SR 等合规义务是否真的触发（这些法规针对"投放市场/受监管金融机构"）？若整段合规驱动对本项目不适用，会动摇"P0 脊柱"的优先级定位。
6. **可重现性的"环境/种子"维度在实盘/paper 场景的特殊困难。** 实盘/paper 交易与外部市场状态强耦合、本质不可重放——对这类节点 RO-Crate 式"冷启动重现"在概念上就不成立（市场不会重演），谱系只能做事后归因而非重现。这一边界需划清。

## 9. 参考文献（URL）

- PROV-AGENT（arXiv 2508.02866，IEEE e-Science 2025，Souza et al., ORNL）— <https://arxiv.org/abs/2508.02866>
- OpenLineage object model — <https://openlineage.io/docs/spec/object-model/>
- OpenLineage（规范 + SDK，GitHub）— <https://github.com/OpenLineage/OpenLineage>
- Marquez（OpenLineage 参考实现）— <https://marquezproject.ai/>
- MLflow dataset/model lineage — <https://mlflow.org/docs/latest/ml/dataset/>
- OpenTelemetry GenAI agent spans — <https://opentelemetry.io/docs/specs/semconv/gen-ai/gen-ai-agent-spans/>
- Arize Phoenix / OpenInference — <https://github.com/Arize-ai/phoenix>
- Langfuse — <https://langfuse.com/>
- DataHub open-source data lineage — <https://datahub.com/blog/open-source-data-lineage/>
- Flowcept（ORNL，GitHub）— <https://github.com/ORNL/flowcept>
- RO-Crate Workflow Run Crate profile 0.5 — <https://www.researchobject.org/workflow-run-crate/profiles/0.5/workflow_run_crate/>
- RO-Crate / runcrate — <https://www.researchobject.org/workflow-run-crate/>
- W3C PROV-O — <https://www.w3.org/TR/prov-o/>
- How transparency modulates trust in AI（Patterns 2022, PMC9023880；作者 Zerilli, Bhatt & Weller）— <https://pmc.ncbi.nlm.nih.gov/articles/PMC9023880/> · 作者核实 <https://pubmed.ncbi.nlm.nih.gov/35465233/>
- Measuring and Understanding Trust Calibrations for Automated Systems（CHI 2023）— <https://dl.acm.org/doi/fullHtml/10.1145/3544548.3581197> · <https://dl.acm.org/doi/10.1145/3544548.3581197>
- Reproducibility in ML-based research（Semmelrock et al., arXiv:2406.14325）— <https://arxiv.org/html/2406.14325v2> · <https://arxiv.org/abs/2406.14325>
- Fine-Grained Traceability for Transparent ML Pipelines（arXiv:2601.14971，ACM Web Conf 2026, DOI 10.1145/3774904.3793005）— <https://arxiv.org/abs/2601.14971>
- Workflow provenance in the lifecycle of scientific ML（arXiv:2010.00330）— <https://arxiv.org/pdf/2010.00330>
- Recording provenance of workflow runs with RO-Crate（PLOS ONE 2024, PMC11386446 / arXiv:2312.07852）— <https://www.ncbi.nlm.nih.gov/pmc/articles/PMC11386446/>
- EU AI Act Article 12 — <https://artificialintelligenceact.eu/article/12/>
- EU AI Act Article 12 logging mandate（FireTail 解读）— <https://www.firetail.ai/blog/article-12-and-the-logging-mandate-what-the-eu-ai-act-actually-requires>
- Federal Reserve SR 26-2 — <https://www.federalreserve.gov/supervisionreg/srletters/SR2602.htm>
- OCC Bulletin 2026-13 — <https://www.occ.gov/news-issuances/bulletins/2026/bulletin-2026-13.html>
- NIST AI 100-4 — <https://nvlpubs.nist.gov/nistpubs/ai/NIST.AI.100-4.pdf>
- BCBS 239 data lineage（二手综述）— <https://www.ovaledge.com/blog/bcbs-239-data-lineage>
- C2PA Content Credentials — <https://c2pa.org/>
