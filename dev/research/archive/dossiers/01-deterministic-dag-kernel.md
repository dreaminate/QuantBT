# 01 · 确定性工作流 DAG 内核 + checkpoint/replay/fork/rollback

> 机构级 Agent OS 成品环节深挖 · 全程 Opus 4.8 · 对抗式核查已降权 · 重心=前沿研究+概念级推荐 · 不含 file:line 代码接线
> 簇 A

## 1. 一句话定位

把研究/回测/实盘的整条 Agent 工作流建模为**确定性的有向无环图（DAG）内核**，节点身份 = `hash(结构, 输入, 上游)`，从而获得三件事：(a) 可寻址工件 + 血缘即审计轨迹；(b) **持久化执行（durable execution）**——重放时复用已落盘的节点输出而不是重跑；(c) checkpoint / replay / fork（what-if）/ rollback 的可控语义。**核心纪律：LLM 永远在节点内部，绝不当控制器；控制器是确定性的图调度器。**

但有一条贯穿全文的硬边界必须先立起来：**“确定性 DAG 内核”交付的是 durable execution（复用日志），不是 reproducible execution（重新推导出逐位相同的输出）。** 这两者在带 LLM 节点、又带真实券商副作用（真钱）的量化场景里，差别是致命的——后面第 5、7、8 节会反复回到这条边界。

## 2. 前沿 SOTA 与代表系统

| 系统 | 它解决什么 | 对内核的启示 | 来源性质（重要） |
|---|---|---|---|
| **Temporal** | Log/replay 持久执行引擎；重放时复用已记录的 activity 结果；通过任务队列租约（lease）、sticky execution、心跳、超时实现交付保证。**workflow 逻辑 exactly-once，activity at-least-once**。需要确定性代码 + 显式版本管理。重量级集群。 | 行业标准的“重放复用日志”范式 + 租约/超时模型；activity 必须幂等。 | 厂商博客/官方文档（自利） |
| **DBOS Transact** | 把持久执行做成一个 **Postgres 库**；与业务写在同一个 Postgres 事务里的 step 写入 = 事务性 exactly-once。最适合单租户、Postgres 为中心的 Agent OS。 | 若 Agent OS 本就以 Postgres 为底，可用同库事务拿到 step 的 exactly-once，避免引入独立集群。 | 厂商文档（自利） |
| **LangGraph** | Checkpointer 在节点之间持久化状态；`get_state_history` 做 time-travel；`update_state` 做 fork。**但官方明确警告：replay 是重新执行节点、不是读缓存，可能发散；无节点内持久化；租约与 exactly-once 要你自己做。** | 给了 checkpoint/time-travel/fork 的成熟 API 形态，但暴露了“重放即重跑、可能发散”的真实坑——这正是要靠工件寻址去补的缺口。 | 官方文档（中立、且自曝其短） |
| **Magentic-One (AutoGen)** | 双环：外环 Task Ledger（事实/猜测/计划），内环 Progress Ledger + stall 计数器触发 replan。确定性 supervisor 下的有界节点内自治。 | “LLM 在节点内、被 Progress Ledger + stall 计数器约束”这一模式的代表实现。 | 研究论文 |
| **Restate / Dapr Workflows / Azure Durable Functions** | 其它 log/replay 持久运行时。Dapr 1.18 加了 workflow 历史的签名/证明，每个 await = 一个 checkpoint。 | 提供 checkpoint 粒度与历史完整性（签名/证明）的工程参照。 | 含厂商竞争性定位材料（见第 7 节） |
| **Resonate** | 基于 promise/object 的持久执行；恢复时从持久 promise 拉取，但**对无序 promise 不像 Temporal 那样按日志强制步序**——是否发散是**开发者责任的设计权衡**，不是“从不强制步序”的硬缺陷。 | 反例：promise/object 语义比顺序日志更松，提醒我们“强制步序”是要主动设计的属性。 | 单一厂商博客 |

## 3. 关键论文（每条带 URL）

1. **From Agent Loops to Deterministic Graphs**（arXiv 2605.06365, 2026）— 与本环节论点高度同构：可寻址工件；节点身份 = `hash(结构, 输入, 上游)`；身份不变则重放复用已落盘输出；fork = 保留 provenance 的 what-if；通过 seeds + IO 归一化追求确定性。报告 **~30x 更少 token**。
   <https://arxiv.org/abs/2605.06365> · <https://arxiv.org/html/2605.06365v1>
   **降权见第 7 节：该 30x 是单一场景、非同行评审的厂商白皮书（ThruWire, Inc.），近乎输入 token 的恒等式产物，须当“示意”而非“证据”。**

2. **StateFlow**（arXiv 2403.11322）— 状态机把“流程接地（process grounding）”与“子任务求解”分离；在两个基准上相对 ReAct **+13–28%**、成本 **低 3–5x**。
   <https://arxiv.org/abs/2403.11322>
   **降权见第 7 节：仅 GPT-3.5、仅 2 个基准（InterCode SQL / ALFWorld）、2024 年结果；“可迁移到 DAG 内核”是未经证实的外推。**

3. **Magentic-One**（arXiv 2411.04468）— Task + Progress Ledger + stall 计数器再规划；移除 ledger 在 GAIA 上相对掉约 **31%**；强制要求人类监督 + 沙箱；高 LLM 成本。
   <https://arxiv.org/abs/2411.04468>
   **降权见第 7 节：同一消融里移除 FileSurfer 掉 39%、移除 Coder/Executor 掉 21%——ledger 并非唯一承重件；且全系统仅“与既有 SOTA 统计上相当”，不是夺冠。**

4. **AAGATE**（arXiv 2510.25863）— 把 agentic 治理映射到 NIST AI RMF；提供 ledger / 审计轨迹证据 + agent 问责登记册。
   <https://arxiv.org/pdf/2510.25863>
   **降权见第 7 节：这是 Kubernetes 原生治理控制面的框架映射提案，没有“审计被监管接受”的实证；用它支撑“flow 即审计轨迹”是借用制度合法性、属过度声称。**

5.（相邻预印本，须自查）**The Log is the Agent: Event-Sourced Reactive Graphs for Auditable, Forkable Agentic Systems**（arXiv 2605.21997，与 2605.06365 同期出现于检索）— 覆盖同一“可 fork / 可审计日志”论点。**漏点见第 8 节：是否佐证或竞争 2605.06365 未核实；仅靠单篇 2026 startup 预印本会削弱“SOTA 收敛”叙事。**

## 4. 机构最佳实践 / 标准

- **Temporal 官方与社区共识：activity 必须幂等**——因为 workflow 逻辑 exactly-once、activity at-least-once。这一条对“节点重放/重试”是硬约束。
  <https://docs.temporal.io/develop/python/best-practices/error-handling>
- **DBOS：同一 Postgres 事务内的 step 写入 = 事务性 exactly-once**（厂商文档，已核实准确）。
  <https://www.dbos.dev/blog/why-postgres-durable-execution>
- **LangGraph 官方明确告诫**：“Replay 是重新执行节点——它不是从缓存读……可能返回不同结果。” 这是把“持久 ≠ 可复现”写进了官方文档的权威背书。
  <https://docs.langchain.com/oss/python/langgraph/use-time-travel>
- **治理对齐 NIST AI RMF（经 AAGATE 中介）**：ledger / 审计轨迹 / 问责登记册是可对齐的治理证据——但仅是“可映射”，非“已被审计接受”。
- **持久执行运行时的运维税（行业常识，须主动正视）**：Temporal 的 workflow 版本管理 / 部署即非确定性 是著名痛点；运行 Temporal 集群本身是“重量级”运维负担；DBOS 在高 fan-out 下 Postgres 可能成为瓶颈。这些是“何时不该用”的负面证据，第 7 节再展开。

## 5. 对 QuantBT 这套架构的推荐方向（概念级）

> 仅给方向，不点 file:line、不排实施计划。

1. **把两个保证拆开，分别拥有。** “确定性 DAG 内核”（节点身份、血缘、调度顺序）与“持久执行”（重放复用日志、租约、超时、exactly-once）是两层正交的保证，不要混在一个抽象里。内核先成立，持久执行作为可替换的执行后端接进来。

2. **LLM 永远在节点内、绝不当控制器；用 Progress Ledger + stall 计数器有界自治。** 这是两条核心设计方向之一，方向本身稳健。但要**预算成本**：双 ledger（Magentic-One）模式意味着每步更多 LLM 调用（重评 progress ledger、stall 检测、replan），Magentic-One 论文自己就标注“高 LLM 成本”——这套设计继承了一个它从未量化的成本问题，QuantBT 必须自己定 stall 阈值与 ledger 评估频率，并把它当成可调旋钮。

3. **明确选边 durable，而不是奢望 reproducible。** 对 LLM 节点，承诺的语义应是“重放复用已落盘输出”（durable），而**不是**“重新跑会得到逐位相同结果”（reproducible）。原因见第 7 节：商用 LLM API 在 temp=0 也不保证逐位可复现。因此节点身份哈希里，LLM 输出应作为**被寻址、被缓存的工件**，重放路径默认读工件、绝不默认重跑 LLM。

4. **为交易副作用单设“不可幂等边界”。** 这是 QuantBT 区别于所有通用系统的领域地雷：fork（what-if）/ rollback / replay 一旦碰到**已经下到券商的真实订单、持仓、资金**，就不再是干净的 what-if，而是灾难。建议把节点显式分类：纯计算节点（可自由重放/fork）vs 带外部副作用的执行节点（必须经幂等键 / 客户端订单 ID / 对账闸门保护，且 fork/rollback 在此边界处**截断**而非透传）。所有被引用的系统都是通用目的、都没回答金融事务幂等，这个洞要 QuantBT 自己补。

5. **血缘即审计轨迹，但别过度声称合规。** DAG 执行血缘做内部可追溯、可解释、可复盘是合适的；但不要据 AAGATE 就宣称“满足监管审计要求”——那是框架映射，无审计接受实证。对外口径应是“可对齐 NIST AI RMF 的审计证据”，留出验证空间。

6. **正视运维税，按规模选后端。** 单用户 / Postgres 为中心（已是 QuantBT 现状）→ 倾向 DBOS 式同库事务，避免引入 Temporal 集群的重量级运维与版本管理痛点；只有在高并发 / 多租户 / 真正需要分布式租约时，才考虑 Temporal 级别的引擎。

## 6. 架构级参考（少量伪代码 / schema 草图，非代码接线）

> 仅示意，不接线到现有代码。

**节点身份与工件寻址（durable，非 reproducible）**

```text
node_id = hash(
    structure   = 节点类型 + 版本 + 配置schema,
    inputs      = 规整化后的输入(IO normalized),
    upstream    = sorted([上游 node_id...])      # 上游身份进哈希 → 内容寻址
)

artifact = store.get(node_id)
if artifact.exists and not force_rerun:
    return artifact.output          # durable: 复用日志，绝不重跑 LLM
else:
    out = run_node(...)             # 仅此处真正执行
    store.put(node_id, out, lineage=upstream)
    return out
```

**节点契约：纯计算 vs 带副作用（交易边界）**

```text
Node:
  kind: "pure" | "effectful"
  # pure:      可自由 replay / fork / rollback
  # effectful: 触达券商/资金, 必须带幂等键
  idempotency_key: Optional[str]    # effectful 节点必填, 形如 client_order_id
  replay_policy:
    pure:      REUSE_ARTIFACT       # 重放复用工件
    effectful: HALT_AT_BOUNDARY     # fork/rollback 在此截断, 触发对账而非重发单
```

**Progress Ledger + stall 计数器（LLM 在节点内、被约束）**

```text
inner_loop(node):
  task_ledger  = {facts, guesses, plan}      # 外环, 确定性 supervisor 维护
  stall = 0
  while not done and stall < STALL_MAX:       # STALL_MAX 为可调旋钮(成本预算)
    progress = llm_eval_progress(task_ledger) # 注意: 每轮一次 LLM 调用 → 成本
    if progress.no_advance: stall += 1
    else: stall = 0
    if stall >= STALL_MAX: trigger_replan()   # 受控再规划, 控制器仍是确定性的
```

**fork / rollback 的 provenance 语义（what-if）**

```text
fork(from_node_id):
  new_branch = clone_lineage(from_node_id)    # 保留 provenance
  for n in downstream(from_node_id):
    if n.kind == "effectful":
        n.replay_policy = HALT_AT_BOUNDARY    # 真钱节点不在 what-if 里重发
  return new_branch                            # 纯计算下游可自由 what-if
```

## 7. 降权 / 争议 / 陷阱（对抗核查结论）

> 以下限定词**原样保留**：夸大 / 争议 / 二手 / 不可外推 / 厂商自利 / 上下文剥离 / 非同行评审 / 近乎恒等式 / 折算为“示意”。

- **【高 · 夸大 + 厂商自利 + 非同行评审 + 近乎恒等式】arXiv 2605.06365 的 “~30x 更少 token”被严重当作头条结果夸大。** 这个 30.5x 来自**单一特定场景**（“无关分支更新”任务：382 vs ~11.7k 输入 token），**不是普遍结果**。评测是 **n=3 重复、两个受控 policy-memo 更新任务、单一领域、单一模型家族**。论文自己明确声明这是“**一项受控机制研究，而非全面基准**”，且结果“**不应被解读为对一般文章质量优越性的主张**”。关键：这是 **ThruWire, Inc. 的厂商论文（两位同姓作者，2026 年 5 月），未经同行评审、未被独立复现**。把它称作“mirror 本论点的工作”是**循环论证**——它是一家初创公司在为正被提议的同一架构背书。该 token 缩减还是“重放缓存分支 vs 重跑循环”的**输入 token 恒等式产物，近乎同义反复，不是涌现发现**。→ 折算为**示意性、非证据性**。

- **【中 · 上下文剥离】Magentic-One 的 “移除 ledger 掉 ~31%” 被脱离上下文引用。** GAIA 验证集上的 31% 相对下降是真的，**但两条实质性限定被丢掉**：(1) 同一消融里**移除 FileSurfer 掉 39%、移除 Coder/Executor 掉 21%**——ledger **并非唯一承重件**，只是若干同等重要组件之一；(2) Magentic-One 在 GAIA/AssistantBench 上仅取得“**与既有 SOTA 统计上相当**”——它**匹配、并未击败**先前系统，且用 GPT-4o/o1 高成本。原 finding 两次把它当权威设计验证，却未提它**不是基准夺冠者**、且是个**明确要求 Docker 沙箱 + 人类监督的研究框架、非生产就绪**。

- **【中 · 不可外推】StateFlow 的 “+13–28% / 便宜 3–5x” 范围风险被低估。** 数字已核实但**范围窄**：增益是 **仅 GPT-3.5**、**恰好两个基准**（InterCode SQL: +13%/便宜 5x；ALFWorld: +28%/便宜 3x）。原 finding 自带的“单篇论文”注脚是诚实的，但把 2024 GPT-3.5 时代结果配上自信的“+13–28%”区间，**有暗示其稳健性的风险**——现代模型与 agent 框架（以及 ReAct 本身）已大幅演进。“framing 可迁移到 DAG 内核”是**未经证实的外推**：SQL/具身任务上的状态机结果**不能经验性地迁移**到量化/Agent-OS 的持久执行 DAG 内核。

- **【低 · 二手 + 压平权衡】Resonate “不强制步序”。** 方向正确，但一手来源（Resonate 自家 journal）比“不强制步序”更**有微妙差别**：它把这描述为 object/promise-set 语义，无序 promise 不像 Temporal 的有序 step 那样被“从日志拉取”，因此**发散仅在开发者不了解重放机制时才可能**——这是一个**开发者责任的设计权衡**（“deterministic to make your use-case happy”），不是“步序从不被强制”的硬声称。原 summary 把一个设计权衡**压平成了缺陷**。另注：此为**单一厂商博客，非独立分析**。

- **【低 · 厂商竞争性定位被当中立】“Dapr 是 Diagrid 对 agent-checkpointing 缺口的持久答案”。** 事实机制（Dapr 1.18 workflow 历史签名/证明、每个 await = 一个 checkpoint）核对无误，但承重的“checkpoints 不够用”framing 来自 **Diagrid 自家营销博客**——Diagrid 是销售基于 Dapr 的持久运行时的商业厂商，是**针对该 finding 同时也在推荐的 LangGraph checkpointer 的自利来源**。原 finding 把一篇**厂商竞争性定位文章当作中立技术教条**，未标注利益冲突。

- **【低 · 无出处的民间历史】Azure Durable Functions “开创了大量陷阱教条”。** 这是一个**无出处、含糊的历史归因被当成事实陈述**。虽然 Azure Durable Functions 文档确实记录了确定性约束与代码版本管理陷阱，但“它**开创**了持久执行陷阱教条”是**无引用的民间历史断言**；确定性重放约束早于它（经典确定性重放文献、Orleans、各类工作流引擎）。轻微，但属**未经佐证的来源归因**。

**贯穿性结论（最严重的单一遗漏）：** finding 从未正面承认 **LLM 节点在商用 API 上即使 temp=0 也不保证逐位可复现**（批处理、硬件、MoE 路由、静默模型更新）。“身份 = hash(结构,输入,上游)；重放复用已落盘输出”这套前提**只在你永不真正重跑 LLM 时成立**——即它是 **durable execution（复用日志），不是 reproducible execution（重新推导出相同输出）**。finding 把这两者当作“seeds 已解决”而**混为一谈**。此外，**厂商来源高度集中**（ThruWire、Resonate、Diagrid、Temporal、DBOS 全在为各自架构背书），被当成**收敛的独立证据**，实为营销塑形的倡导。

**净判定（采纳原核查 verdict）：** 关于持久执行版图的核心技术声称**大体准确**且有一手文档支撑（Temporal exactly-once/at-least-once、DBOS 同库事务 exactly-once、LangGraph checkpoint/time-travel/重放发散/无节点内持久化均核对无误）；两条设计方向（“把 DAG 内核与持久执行作为两个独立保证拥有”“LLM 在节点内、被 Progress Ledger + stall 计数器约束”）**稳健可辩护**。但**用于支撑新颖性与量化收益的证据弱于呈现**：把量化结果**折算为“示意”**，把新颖性预印本**当作厂商倡导**，并在动手之前加上**“持久 ≠ 可复现”**与**“金融副作用幂等”**两条硬限定。

## 8. 开放问题

1. **成本/延迟未核算。** 推荐的双 ledger 模式带来更多 LLM 调用，finding 从未量化。QuantBT 需要自己定：stall 阈值、ledger 评估频率、每步 LLM 预算上限——否则“有界自治”可能变成成本黑洞。

2. **LLM 节点的确定性根本难题被一笔带过。** 既然商用 API temp=0 不保证逐位可复现，那么“重放是否允许重跑 LLM”必须有明确策略。若允许重跑 → 必须接受输出漂移并设容差/再核验；若不允许 → 必须保证工件永久可取且节点身份哈希稳定。这是必须先拍板的设计岔路。

3. **交易副作用下的 replay/fork/rollback 正确性（领域地雷）。** 重跑或回滚一个**已下单**的节点是灾难。需要定义：幂等键体系（client_order_id 级别）、effectful 节点在 fork/rollback 边界的截断语义、与券商对账闸门的衔接。被引用系统全是通用目的，**都不回答金融事务幂等**——这块必须 QuantBT 原创。

4. **厂商来源集中 / 发表偏差。** 承重引用多为带商业利益的厂商材料（ThruWire / Resonate / Diagrid / Temporal / DBOS），各自论证自家是答案。需要主动寻找独立、负面或同行评审来源来校准。

5. **缺“何时不该用”分析与负面结果。** 每个被引系统都被当成功案例呈现。缺失：Temporal 著名的 workflow 版本管理/部署即非确定性之痛、运行 Temporal 集群的运维重量、DBOS 在高 fan-out 下 Postgres 瓶颈。平衡的判断需要把这些运维税摆上台面。

6. **新近性 / 竞争版图缺口。** 未核实相邻预印本 **arXiv 2605.21997（“The Log is the Agent”）** 是否佐证或竞争 2605.06365——两者覆盖同一“可 fork / 可审计日志”论点。仅靠单篇 2026 startup 预印本会**削弱“SOTA 收敛”叙事**。

7. **“flow 即审计轨迹”的合规边界。** AAGATE 是框架映射、无审计接受实证。QuantBT 需明确：DAG 血缘满足的是**内部可追溯**，对外不可声称满足监管审计，除非另有验证。

## 9. 参考文献（URL）

- Temporal — What is Durable Execution: <https://temporal.io/blog/what-is-durable-execution>
- Temporal — Error handling / activities must be idempotent: <https://docs.temporal.io/develop/python/best-practices/error-handling>
- DBOS — Why DBOS: <https://docs.dbos.dev/why-dbos>
- DBOS — Why Postgres durable execution: <https://www.dbos.dev/blog/why-postgres-durable-execution>
- LangGraph — Use time travel (checkpoint/replay/fork，含“重放可能发散”告诫): <https://docs.langchain.com/oss/python/langgraph/use-time-travel>
- Magentic-One (arXiv 2411.04468): <https://arxiv.org/abs/2411.04468>
- Restate — What is durable execution: <https://www.restate.dev/what-is-durable-execution>
- Resonate — From where do deterministic constraints (单一厂商博客): <https://journal.resonatehq.io/p/from-where-do-deterministic-constraints>
- From Agent Loops to Deterministic Graphs (arXiv 2605.06365，ThruWire 厂商预印本，非同行评审): <https://arxiv.org/abs/2605.06365> · <https://arxiv.org/html/2605.06365v1>
- StateFlow (arXiv 2403.11322，仅 GPT-3.5/2 基准): <https://arxiv.org/abs/2403.11322>
- AAGATE (arXiv 2510.25863，框架映射、无审计接受实证): <https://arxiv.org/pdf/2510.25863>
- The Log is the Agent: Event-Sourced Reactive Graphs (arXiv 2605.21997，相邻预印本、待自查): <https://arxiv.org/abs/2605.21997>
