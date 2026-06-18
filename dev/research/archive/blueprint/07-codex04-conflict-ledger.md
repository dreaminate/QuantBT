# 07 · Codex-04 整合稿 与 Claude 研究包 冲突账本

> **定位**：本文不取代、不修改 [04-codex-claude-reconciliation.md](04-codex-claude-reconciliation.md)（Codex 的整合裁决稿）。这是一份**可审计的冲突账本**——独立 workflow 产出（14 agent / 157 万 token，逐节核对 04 + 架构稿 + 05-paper vs Claude 研究包 01/02/03/06/99，对抗式确认每条是真冲突还是措辞）。
>
> **核查状态**：核查统计 **15 真冲突 / 15 部分成立(nuanced) / 2 已调和 / 1 仅措辞**；完备性复核**独立把所有代码锚点又验了一遍**（`dsr.py` n_trials 无聚类、`_cost_for_trade` L187-193 只乘线性 bps、`impact_model` 死字段、`experiments/store.py` 全程 append、无 `InstrumentSpec`/`calendar`/`StrategyAllocator`/`agent_os` 目录）——Claude 的代码现状论断全部属实。
>
> 每条标 `严重度 · 核查状态`，并给 **裁断** + **处理动作**（改 04 哪节 / 改 Claude 哪节 / 待用户拍）。

---

## 0. 总结论

**04 是高忠实度整合稿**——大命题上干净采纳了 Claude（安全前移、LLM 可回放、流程即信任→可证伪假设、data-trust 第一闸门、lineage 8 条硬缺口、撤稿源软监控、pod 阈值不硬编码）。**真冲突不在"要不要做"**，而集中在 **3 类系统性偏差 + 1 个贯穿根因 + 4 处路线/自相矛盾**：

- **A 类 · 裁对了但落地降权**：口头采纳、却没进 §8 P0–P6 roadmap（红队套件、honest-N、双速通道、冷启动 N=1）。
- **B 类 · 替 Codex 把硬结论软化为"程度问题"**：DSR 裸分、N_eff 单字段、FDR 平列、成本/容量/AQR。
- **C 类 · 丢配套机制 / 诚实警示**：OOS 揭盲整套通道、RBAC 单人不可强制警示、闸门疲劳干预、编排成本经济学。
- **贯穿根因**：单机开放架构下，04 系统性地把"应用层 policy"冒充成"enforcement"。
- **自相矛盾**：kernel 双账本、Agent 角色 vs 确定性 gate、InstrumentSpec 依赖倒序、05/04 路线打架。

---

## 1. 先说 04 哪里对（忠实采纳，别误伤）

这些是 04 对 Claude **最干净的采纳，不是冲突**：①安全模型前移（§3.2 自评"Claude 胜出"，prompt-injection/tool-abuse/data-poisoning/privilege-confusion/secret 全列 P0/P1）；②LLM 可回放 `LLMCallRecord` 前移 P0 + strict replay 不重采样（§3.1）；③"流程即信任"降级为可证伪 `TrustHypothesis` + 预注册 + falsification + measurement（§3.3，且 target_user_group 已含 risk_pm/quant 全 4 类人群）；④data-trust 第一闸门（§3.4/§4.3）+ field/column-level lineage + §5 八条 lineage 硬缺口（RegistryDatasetSource 取 latest / DatasetManifest 强校验 / t1 传 purged_kfold / RunProvenance / promote gate / JSONL 不静默跳过）；⑤Falsification Gate 全家桶（White RC/Hansen SPA/Romano-Wolf/BHY/MinBTL/MinTRL/Bootstrap CI）+ CPCV/WF 双轨 + Live Monitoring 用 rolling PSR/CUSUM/Page-Hinkley（live≠pre-prod 阈值）；⑥§9#1 撤稿源软监控、§9#2 pod 阈值不硬编码；⑦05-paper 在"文章是受治理证据源非代码燃料、模型默认 runnable:false、安全测试放 §12 P0 第一阶"与 Claude 高度一致。

---

## 2. 头号贯穿根因（完备性复核最锐的补充）

> **04 系统性地把"应用层 policy"冒充成"enforcement"——但单机开放 Parquet/DuckDB 架构根本没有真实权限边界：只要进程能读文件，就能旁路 holdout、旁路角色分离。**

OOS 揭盲(rank4) + RBAC approver≠creator(rank6) + privilege-confusion 是**同一根因的三个面**。要么诚实承认治理是 **tamper-evident（违规可被独立审计检出）而非 tamper-proof（不可能违规）**，要么这套治理在单机上是 theater。**这应被提为 04 的 #1 P0 诚实警示。**


**[rank4] OOS 承诺-揭盲：04 把整套'被治理/计次/留痕'通道丢成'signed manifest + policy enforcement'八字**  `严重度:high · 核查:high — 03 盲点(6)/高风险依赖表确认单机 Parquet 无真实权限边界;06 §2.3 自标硬隔离措辞应丢弃、降级为可审计检出`
> Codex 架构稿 §6/§8 与 04 §9#5 在'硬隔离不可达、诚实降级'结论上采纳了 Claude,但只剩 signed holdout manifest+policy enforcement。Claude(06 §2.3/§4[3])配套的整套机制——read_holdout side-effect class(默认拒绝)+HoldoutAccessAttempted/HoldoutRevealed 事件+访问计数 k 入 gate(接 Thresholdout)——被丢失。
- **裁断**：Claude 对。结论层一致但丢了唯一能兑现承诺的替代物;做不到密码学硬隔离时,'计次+揭盲审批门+违规可审计检出'是兑现 OOS 闸门的唯一方式,丢了它闸门退化为纯文档约定。04 §3.4/§5 与架构稿 §6/§8 须把这三件补回作 P0 一等内容。
- **动作**：OOS 揭盲(改 04 §3.4/§5+架构稿 §6/§8):把 read_holdout side-effect class(默认拒绝)+HoldoutAccessAttempted/HoldoutRevealed 事件+访问计数 k 入 gate(接 Thresholdout)补回作 P0 一等内容(06 §4[3]);强度承诺诚实降级为'违规可被独立审计检出'。

**[rank6] RBAC：04 删掉了'单人多角色下 approver≠creator 物理不可强制'的核心诚实警示**  `严重度:high · 核查:high — 03 盲点(5)/(8)与 06 §2.6/§2.6 末尾 ⚠️ 框确认;本项目单机 DuckDB/Parquet+很可能单人是承重假设`
> 04 §1 RBAC 行采纳方向对(承认需 Claude 补机制)但写成泛泛'角色与授权设计',未把 06 §2.6 的 kernel 级 actor.id!=run.creator_id 校验写进 schema/§8(P0 只有 ToolPolicyProxy、无 roles 表/promote actor 校验);且完全删除了'单机本地优先、很可能单人使用的产品里 approver≠creator 物理上无法强制、须外部第二人'这条最承重警示。
- **裁断**：Claude 对,04 低估并丢弃。04 在 §9 对 OOS 同型张力做了诚实降级却独漏 RBAC 这条同构问题,是不均匀的用词纪律(03 盲点8 点名)。04 §1 RBAC 行应补 06 §2.6 kernel 校验规格+单人不可强制警示。
- **动作**：RBAC(改 04 §1 RBAC 行+§8 P0):补 06 §2.6 kernel 校验规格 actor.role==approver && actor.id!=run.creator_id+roles 表+promote actor 校验进 P0;补回'单机本地优先/很可能单人使用下 approver≠creator 物理不可强制、须外部第二人'诚实警示(对齐 §9 OOS 同型降级的用词纪律)。


---

## 3. 路线分歧 / 04 内部自相矛盾

**[rank3] 新建并行 agent_os kernel vs 提升现有 M12/M13——04 用'不冲突'掩盖路线分歧+双账本风险**  `严重度:high · 核查:high — 代码核查:experiments/store.py 是独立 JSONL append(runs.jsonl);agent_os 目录尚不存在(仍是设计期);arch §3 schema 确为独立 agent_os_* 表`
> Codex 架构稿 §3-4 新建 agent_os_runs/events/steps 全套表为事实源、把 experiments 吸收为 adapter；Claude(01)要把现有 dag/engine.py+agent_runtime.py'焊接提升'成治理 DAG、复用 M12 lineage。04 §1 表判'不冲突:kernel 是事实源、DAG 是其上执行图'。
- **裁断**：真冲突,04 软化。综合取 Codex durable kernel 形态作脊柱(durability/可回放确强于 Claude 偏轻的'给 dag 加 approve'),但必须强约束:run/strategy/model 级 lineage 归一到提升后的 experiments/store,agent_os 只新增 step/checkpoint/approval/gate 这类 experiments 没有的维度,而非另起平行账本。04 §1 Lineage 行只谈 Dataset/Feature 合并、没裁 run 级账本归一。
- **动作**：kernel 路线(改 04 §1 表+§5):把'不冲突'改为'路线分歧,最终取 Codex durable kernel 形态作脊柱,但强约束:run/strategy/model 级 lineage 归一到提升后的 experiments/store(非另起 agent_os 平行账本),agent_os 只新增 step/checkpoint/approval/gate';§5 显式裁定 run 级账本归一,避免双账本。

**[rank9] 多 agent 边界：04 说'Claude 更严'但架构稿 §7 把组合/执行/风控也建成独立 Agent 角色，与 04 §2 自相矛盾**  `严重度:medium · 核查:high — arch §7 L48-49(RiskOptimizerAgent/ComplianceExecutionAgent)/L320-322 与 04 §2 L64 直接核对属实`
> 04 §1 标'Claude 更严'方向对,但采纳的架构稿 §7 把组合/执行/风控实例化为 RiskOptimizerAgent/ComplianceExecutionAgent,而 Claude(01 第3点)要求组合/执行保持单线程、不 agent 化、应是确定性 DAG 节点。04 §2 又写'组合/执行/promotion/capital allocation 只走确定性 gate+approval'——与 §7 角色清单自相矛盾。
- **裁断**：裁断偏 Claude,且 04 有内部矛盾未消解。应明确区分'LLM-backed specialist agent'(仅限弱耦合探索:假设/因子海/文献海/对抗复核)与'确定性节点'(组合/执行/配资/promotion,由代码执行、agent 只读结果)。04 §7 措辞把确定性环节叙述成 agent 弱化了 Claude 单线程约束。
- **动作**：多 agent 边界(改 04 §7+消解 §2/§7 矛盾):明确区分 LLM-backed specialist agent(仅弱耦合探索:假设/因子海/文献海/对抗复核)vs 确定性节点(组合/执行/配资/promotion 由代码执行、agent 只读);架构稿 §7 把 RiskOptimizer/ComplianceExecution 从 Agent 角色改叙述为确定性 gate 节点。

**[rank7] InstrumentSpec 排到 P4 但成本模型(P2/P4)隐式依赖合约规格/日历——04 内部排序自相矛盾**  `严重度:high · 核查:high — 代码核查确认无 InstrumentSpec 类、无 app/calendar 目录、_cost_for_trade L187-190 只乘 slippage_bps、impact_model 字段是死字段`
> 04 §P2 切片要求 deterministic backtest adapter 写 sqrt 冲击 I(Q)=Y·σ·√(Q/ADV),却把 InstrumentSpec 排到 §P4,且只当'domain schema 回写项';Claude(02 P2 ⚠️/06 §4[5])指 sqrt 冲击需 ADV/tick/lot/multiplier/日历对齐,依赖排在被依赖者之后。
- **裁断**：Claude 对,04 自身不自洽。InstrumentSpec/calendar/ADV 最小子集(stable_id/asset_class/tick/lot/multiplier/listing-delisting+exchange_calendars)须与成本模型同批或更前,不能整包压 P4。06 已抓到要求前移,04 主裁决未吸收。
- **动作**：InstrumentSpec 前移(改 04 §P2/§P4+对齐维度6 rank,02/06 一致):InstrumentSpec/calendar/ADV 最小子集(stable_id/asset_class/currency/tick/lot/multiplier/listing-delisting/funding 来源+exchange_calendars)从 §P4 前移到 §P2 首切片,与成本模型同批或更前;消解'依赖排在被依赖者之后'的内部矛盾。

**[rank11] 05-paper 子路线图与 04/02 冲突：gated promotion 排 P4(应 P0)、trial 入账未接 N_eff、extractor 未继承 LLMCallRecord 钉定**  `严重度:medium · 核查:high — 05 §12/§7.4/§7.1 与 04 §8/06 §2.4 文本核对属实`
> 05 §12 把 Gated Promotion/Approval Inbox 排 P4、ModelPassport 排 P3,与 04 主路线图 P0'model promotion approval gate'、Claude 02 P0 矛盾;05 §7.4 trial 入账只提 failed/cancelled 计数、未折算 N_eff;05 §3.1/§7.1 extractor 是 LLM 节点只记 prompt/model/tool-schema hash、未要求 06 §2.4 的不可变模型版本 id(禁裸别名)+system_fingerprint+ReplayDiverged 阻断。
- **裁断**：Claude 对。把'裸 promote 降级为 primitive+gated 包装'作全局 P0(一次性改 store.py/main.py),05 论文链路复用该成果而非到 05-P4 才独立实现;05 须显式继承 04 P0 的 LLMCallRecord 钉定字段+honest-N 双字段,否则论文链路成为绕过 N_eff 的新 garden-of-forking-paths。05 在'模型默认 runnable:false/文章是受治理证据源/安全 P0'方向与 Claude 高度一致(忠实)。
- **动作**：05/04 路线对齐(改 05 §12+04 §8):把'裸 promote 降级为 primitive+gated 包装'作全局 P0(一次性改 store.py/main.py),05 论文链路复用而非 05-P4 独立实现;05 §7.4 trial 入账显式接 N_eff 双字段折算;05 §7.1 extractor 的 LLMCallRecord 继承 04 P0 钉定字段(不可变模型版本 id 禁裸别名+system_fingerprint+ReplayDiverged)。


---

## 4. A 类 · 裁对了但落地降权（口头采纳、roadmap 丢弃）

**[rank5] 红队回归套件前移：04 裁决文字'Claude 胜出·前移 P0/P1'但 §8 路线图静默漏排，底稿仍钉 Phase 8**  `严重度:high · 核查:high — 04 §8 与 arch §16 文本直接核对属实;privilege-confusion 项还需标注'强制的是 ToolPolicyProxy.read_holdout policy 而非物理隔离'(接 OOS 张力)`
> 04 §1/§3.2 判'Claude 胜出'并把四类威胁列入 P0/P1;但 §8 P0 roadmap 只有 security baseline、无'red-team regression suite';架构稿 §16 仍把红队套件钉在 Phase 8(最后一阶)。Claude(03 盲点4)要求与 verifier 同期。
- **裁断**：Claude 对——裁决正确但落地降权。04 §8 P0/P1 应显式列'red-team regression suite + prompt-injection/tool-abuse/data-poisoning/privilege-confusion 回归测试',与 verifier 同期;并回写架构稿 §16 把最小集拆出前移到 Phase 1-3。05-paper §12 P0 反而做对(prompt injection/SSRF/路径穿越第一阶),可作回写模板——04 主路线图与 05 子路线图自相矛盾。
- **动作**：红队前移(改 04 §8 P0/P1+架构稿 §16):§8 显式列'red-team regression suite+prompt-injection/tool-abuse/data-poisoning/privilege-confusion 回归测试',与 verifier 同期;架构稿 §16 把最小集从 Phase 8 拆出前移 Phase 1-3(与 ToolPolicyProxy 同批);以 05-paper §12 P0 为回写模板;privilege-confusion 项标注'强制 ToolPolicyProxy.read_holdout policy 非物理隔离'。

**[rank10] quant 逃生舱/双速通道：04 仅表里一词，未进 P0-P6 roadmap，且漏带 n_trials 防后门前置硬约束**  `严重度:medium · 核查:high — 代码核查 dsr.py 无 n_trials 计数器、确为 spec 承诺非实现(06 §2.6 🚧 属实);03 盲点(5)/(7e)确认`
> 04 §1 表承认 quant 逃生舱是'必需产品机制'但压缩成一个词、未进 roadmap;Claude(06 §2.6)给出双速分叉 EXPLORATORY_SANDBOX↔RESEARCH_REGISTERED+4 护栏,并标'n_trials 诚实计数必须在沙盒开放前先落地,否则探索通道=p-hacking 后门'。
- **裁断**：Claude 对(under-weight 非矛盾)。双速通道应作 P0/P1 一等条目进 roadmap,且 n_trials 全程累加这条前置依赖顺序必须随之带入——04 完全没提。冷启动 N=1 降级路径(与 N_eff 小样本降级同处)也须排期。
- **动作**：双速通道(改 04 §8 P0/P1):双速通道 EXPLORATORY_SANDBOX↔RESEARCH_REGISTERED+冷启动 N=1 降级路径+HITL 疲劳批处理/委派/反向校准排进 P0/P1;带入前置硬约束'n_trials 全程累加诚实计数必须在沙盒开放前先落地'(06 §2.6 🚧,改 dsr.py 增计数器);A股 ComplianceReadinessCard(informational,绝不进 hard-fail)。


---

## 5. B 类 · 替 Codex 把硬结论软化为「程度问题」

**[rank2] N_eff/honest-N：04 §4.4 单字段口径与 §9#4 自承认深统计内部不自洽，且仍排在 P0 低工程量批**  `严重度:high · 核查:high — 代码核查 dsr.py:43 n_trials 为可信标量入参、无聚类/n_eff;99:754 确认 N 全程登记是反作弊;Chen-Zimmermann 发表偏误下不可识别(99:942)使朴素 N 危险`
> 04 §4.4 立单一 N='所有 trial 计入'直接喂 DSR/PBO 且把 honest-N 放 P0'低工程量高杠杆'批；§9#4 又自承认'N_eff 是会静默击穿校正的深统计问题'——正面打架。Claude(06 §2.1/§4[1])要双字段:n_trials_total(审计,不可退)+n_eff(喂 DSR,聚类估)、按 k 最保守端判定、小样本(<~20)降级回 N_total、叠 White RC/Hansen SPA 第二门。
- **裁断**：Claude 对且 04 自身不自洽。采双字段;估计器(ONC/linkage/k)配方不写死、标'开放问题'(06 §3.4 自纠);按深方法学/基建风险重排期。审计要不要全计入(反偷删失败 trial)Codex 治理意图对、保留。
- **动作**：N_eff(改 04 §4.4+§8 P0):Trial Ledger Gate 改双字段 n_trials_total(审计,不可退,反偷删)+n_eff(喂 DSR/PBO,聚类估,按 k 最保守端判定,<~20 降级回 N_total);honest-N 从 P0'低工程量'重分类为深方法学/基建风险;估计器配方落可配参数标'开放问题'(06 §3.4)。同步改 dsr.py 增 n_eff/聚类入口。

**[rank1] DSR 0.6/0.8 裸分阈值：04 当 default profile 保留，Claude 证据是语义错必须删**  `严重度:high · 核查:high — 99:1448 确认 DSR∈[0,1] 是置信度、合理门槛应写 >0.95 软评分非硬否；arch 稿 §10 L462 确认裸分写死`
> Codex 架构稿 §10 写死 DSR≥0.6 paper/≥0.8 prod 四档裸分 cutoff，04 §1/§4.5 把它当随 materiality 浮动的 default profile 保留；Claude(06 §2.2)指 DSR 本身是 [0,1] 概率已内生吃掉 N/T/skew/kurt，再叠裸分是双重计数、且 0.6/0.8 无文献锚。
- **裁断**：Claude 对，04 替 Codex 软化。删裸分、改 DSR<显著性(默认 0.90 paper/0.95 prod，且可配)触发人审、强制暴露 N_eff/T/skew/kurt+区间。04 §4.5 停在'浮动 profile'未走到'框架语义错'。
- **动作**：DSR 裸分(改 04 §1/§4.5+架构稿 §10 L462):删 DSR≥0.6/0.8/0.5/0.2 裸分,改'DSR<显著性(默认 0.90 paper/0.95 prod,可配)触发人审'+强制暴露 N_eff/T/skew/kurt+区间;Falsification Gate 行回写一句'DSR 是标度修正概率非铁律'。

**[rank13] FDR 在 04 §4.5/架构稿被与 t>3.0 平列为合法主判据，未降级为辅助证据**  `严重度:medium · 核查:high — 99:942 确认 Chen-Zimmermann t-hurdle 不可识别、'换 FDR 并未解决问题';arch §10 L463 平列属实`
> 04 §4.5+架构稿 §10 L463 把 FDR/q-value 写成可与 t>3.0 互替的 production 判据;Claude 全线(README/roadmap P4 ⚠️)立场是'FDR 不解决发表偏误、只作辅助证据'。
- **裁断**：以 Claude/roadmap 为准——发表偏误下 t-hurdle 不可识别(Chen-Zimmermann)是已知硬边界,FDR 当主闸会误导。但两边都诚实:Claude 自己想反向升 FDR 的 Chen 2024 引用也未过核查(06 §3.1)。综合:FDR 作 family-wise 外辅助证据保留,主判据仍 White RC/Hansen SPA+DSR+t>3.0(t>3.0 按 99:905 应可配软门)。04 应回写一句降级标注。
- **动作**：FDR 降级(改 04 §4.5+架构稿 §10 L463):回写一句'FDR/q-value 作 family-wise 之外的辅助证据,非可与 t>3.0 互替的唯一主判据(发表偏误下 t-hurdle 不可识别)';主判据仍 White RC/Hansen SPA+DSR+t>3.0(t>3.0 按 99:905 标可配软门)。

**[rank14] 成本模型 §9.3'平方根律有 AQR 争议'误述：真争议不是函数形式而是 Y 标定二手/单笔≠策略级/δ 偏离 0.5**  `严重度:medium · 核查:high — 99 流14 确认 AQR 自己用平方根、把过度拥挤列为 fiction(99:942)`
> 04 §9.3 把 AQR 写成对平方根律本身的争议来源(会让人以为该律要降权);AQR(Frazzini-Israel-Moskowitz)恰恰自己用平方根律,其贡献是'公开数据推的冲击常被高估'。Claude(06 §3.2/§5)给出最小改写。
- **裁断**：Claude 对(under-weight/mischaracterize 非路线冲突)。两边落地动作一致(保留平方根默认+敏感性区间+δ 随 asset_class 浮动)。采纳 06 §5 对 04 §9.3 的最小改写:函数形式是共识、争议在 Y 标定/单笔 metaorder≠策略级净成本/δ 偏离;显示 Y∈[0.3,1.5]+区分 temporary/permanent。'函数形式有争议'会误导实现者去换模型形式。
- **动作**：AQR 措辞(改 04 §9.3,采纳 06 §5 最小改写):函数形式是 SOTA 共识(AQR 自己也用平方根),争议在 ① Y 标定二手 ② 单笔 metaorder≠策略级净成本 ③ δ 偏离 0.5;显示 Y∈[0.3,1.5]+δ 随 asset_class 浮动+区分 temporary/permanent。

**[rank15] 容量/TCA：04 §4 gate8 保留静态阈值但未升级为'冲击模型反算 AUM 上限'的一等估计器、未逐条标'行业惯例非临界点'**  `严重度:medium · 核查:high — 代码核查 strategy_goal.py:99 capacity_usd 确为用户填的数字、系统不反算`
> 两边都保留 impact≤25%/参与率≤5%ADV/AUM≤80% 作默认(不冲突);04 主稿 §4 没把容量从'用户填的上限数字'升级为'据冲击模型反算 AUM 上限的一等估计器'、未逐条标'行业惯例非临界点'、未要求按敏感性悲观端判定。Claude(06 §2.5)已补全且与 04 不矛盾。
- **裁断**：Claude/06 更完整,04 主稿欠这层(under-weight)。采纳 06 §2.5 容量护栏(反算估计器+敏感性悲观端+逐条标注+超容量 HITL),04 §4/§9 据此细化。
- **动作**：容量估计器(改 04 §4 gate8/§9,采纳 06 §2.5):把 capacity 从用户填数字升级为'据冲击模型反算 AUM 上限的一等估计器'+逐条标'保守治理缓冲、行业惯例非临界点'+gate 按敏感性悲观端判定+超容量 HITL。同步改 strategy_goal.py capacity_usd 接反算。

**[rank12] PBO 阈值性质：04 笼统降权为 default profile，未触及'硬线取 0.5 还是 0.05'的政策分歧**  `严重度:medium · 核查:med — 06 §3.3 自标 Neyman-Pearson 引用 360KB 附录 0 命中、不能当已核实`
> 04 把 PBO 阈值当随 materiality 浮动的 default profile(这层不矛盾);漏掉更细一层:PBO>0.5 硬 block vs 学究式 PBO>0.05 线的实质分歧。Claude(06 §3.3)诚实标注支撑 PBO>0.05 的 Neyman-Pearson 引用未过附录核查。
- **裁断**：倾向 Claude 但保留不确定:维持 PBO>0.5 block/>0.6 quarantine 作默认(与 04 一致),把 0.05 线列为待核实开放项、不升 schema 硬线,直到引用被定向核查。04 的'漏'属没展开非错,中等严重度。
- **动作**：PBO 0.05 线(待用户拍):维持 PBO>0.5 block/>0.6 quarantine 默认(04 不改),把'PBO>0.05 决策线'列为待核实开放项、不升 schema 硬线;待定向核查 Neyman-Pearson 引用(06 §3.3)后再议。

**[rank21] CPCV：04 双轨措辞已采纳'互补非取代'，但未承认 CPCV>WF 仅在合成环境成立这一核查降级**  `严重度:low · 核查:high — 02 roadmap P2 ⚠️'CPCV 是更强默认非唯一最优铁律'确认`
> 04(Gate5/P3)与 Claude(roadmap P2/99:544)双轨表述一致、都拒绝 CPCV 取代 WF(收敛点);唯一缺口:04 未把'CPCV>WF 仅在合成环境成立'这条核查降级写出,可能让读者以为 CPCV 是单纯升级。
- **裁断**：基本不冲突——04 用双轨已吸收 Claude 核心。建议 04 Gate5 CPCV 行补一句限定即可,不构成路线分歧。低严重度。
- **动作**：CPCV(改 04 Gate5):补一句限定'CPCV>walk-forward 仅在合成环境成立、实证为互补非取代',不构成路线分歧。


---

## 6. C 类 · 丢配套机制 / 诚实警示

**[rank17] 闸门疲劳：04 §3.3 列 approval_fatigue 为测量项，丢了 Claude 的主动干预机制(反向校准/强制暂停/批处理委派)**  `严重度:medium · 核查:high — 06 §2.8 与 03 盲点(5)确认;06 §2.8 自带弱代理限定属实`
> 04 §3.3 进口 fatigue/over-trust 作可证伪指标(忠实),但 Claude(03(5)/06 §2.8)承重结论是'解释/证据展示可靠提升采纳却常增加 over-reliance'——光测量不修复,须 forced pause/counter-evidence 主动反制+低风险审批批处理/委派。04 把干预机制都只留在 §1 表一句话、未落 roadmap。
- **裁断**：Claude 对,04 把'测量'当'解决'。TrustHypothesis measurement(04 已对)应配 06 §2.8 反向校准干预(高风险档秒批+不展开证据+高采纳三联征触发 counter-evidence+forced pause)+批处理/委派设计。06 §2.8 自标残留不确定(金融 ground-truth 滞后使 RAIR/AoR 退化为弱代理)这条限定 04 也没保留。
- **动作**：闸门疲劳干预(改 04 §3.3+§8):measurement 配 06 §2.8 反向校准干预(高风险档秒批<3s+不展开证据+高采纳三联征→注入 counter-evidence+forced pause)+低风险审批批处理/委派,排进 roadmap;保留 06 §2.8'金融 ground-truth 滞后使 RAIR/AoR 退化为弱代理'限定。

**[rank8] 成本/延迟/失败经济学(编排级)在 04 整体缺席**  `严重度:medium · 核查:high — 03 高风险依赖表'整个脊柱依赖 LLM 持续可用'确认无 fallback 设计`
> Claude(03 §3/高风险依赖表)把编排成本/延迟/失败列为高风险依赖(脊柱对 LLM 持续可用硬依赖、challenger 第二供应商成本失控会让独立验证退化为自评);04 既没进裁决表也没进路线图。05 §3.5 自承'两份都欠'。
- **裁断**：Claude 对——真实遗漏,不能用'两份都欠'打发。04 治理脊柱(挂起数天的 5 道 HITL+fan-out+异模型 challenger)恰恰放大这些成本/可靠性问题。04 应新增 P0/P1 合同:编排级 token/成本预算与上限、节点级部分恢复语义(含 LLM API 超时/限流/宕机降级与 fallback)、challenger 第二供应商成本与单点预案。架构稿 handoff 的 budget 字段是单步级、不覆盖累计/挂起期/供应商单点。
- **动作**：编排经济学(改 04 新增 §3.5 或 P0/P1 合同):编排级 token/成本预算与上限、节点级部分恢复语义(含 LLM API 超时/限流/宕机降级与 fallback)、challenger 第二供应商成本与单点预案;架构稿 handoff budget 从单步级扩到覆盖累计/挂起期/供应商单点。

**[rank16] 配资/meta-allocation：04 §6 列 schema 名但漏带'DSR 软门槛(>0.95 非硬否)'与'拥挤缩量先告警后自动'两条承重限定**  `严重度:medium · 核查:high — 代码核查无 StrategyAllocator/CenterBook(配资层为零);99:1448 确认 DSR>0.95 软门槛、流15 HRP/NCO 仅资产层验证 nuanced`
> 04 §9#1(撤稿源软监控)/§9#2(pod 阈值不硬编码)忠实采纳;但没把'DSR 作配资软门槛(>0.95)非硬否'写进 StrategyAllocationBook/DrawdownKillScalePolicy 入选逻辑,也没点名撤稿源软监控正是 capacity/拥挤缩量的落点。Claude(99 流15/01 资本配置官)要求 HRP/NCO 必须与等权/逆波动严格 walk-forward 对照。
- **裁断**：Claude 对,04 采纳 pod 阈值但漏另两条同等承重限定。在 04 §6 Capital Allocation schema 注记显式写'DSR 软评分(>0.95)入选、拥挤缩量先告警后自动、pod 阈值预注册可配',并纳入 HRP/NCO 对照纪律。否则会按朴素 Sharpe 选策略。
- **动作**：配资限定(改 04 §6 Capital Allocation 注记):显式写'DSR 软评分(>0.95)入选非硬否、拥挤缩量先告警后自动、pod 阈值预注册可配';纳入 HRP/NCO 必须与等权/逆波动严格 walk-forward 对照(99 流15)。

**[rank18] bitemporal 双时间轴：04 §1 表口头'合并'，却没进 §5 P0/P1 硬缺口清单与 §8 路线图**  `严重度:medium · 核查:high — 04 §5 八条缺口、§8 P0/P1 文本核对确认无 bitemporal;99:661 确认 bitemporal 标准`
> 04 §1 Lineage 行口头承诺纳 bitemporal,但 §5 八条硬缺口与 §8 路线图只保留 hash/manifest/field-level/t1 这些 Codex 已有基建的增量,bitemporal 蒸发。Claude(99:661 流要 valid_time/transaction_time;02 把一等 InstrumentSpec/日历排 P3)。
- **裁断**：Claude 对,04 低估。99 核查确认 dataset_hash≠PIT≠bitemporal 是真实缺口且作者已诚实标注;但 bitemporal 是 eff=high 深改造、非 P0 切片必须。04 §5 应显式列'bitemporal(valid_time/transaction_time)为 P1+ lineage 深化项、当前 SHA manifest 仅等价完整性非 PIT',优先级可低于 version_id/t1 但不能不写。
- **动作**：bitemporal(改 04 §5):显式列'bitemporal 双时间轴(valid_time/transaction_time)为 P1+ lineage 深化项,当前 SHA manifest 仅等价完整性非 PIT',优先级可低于 version_id/t1 但不能从落地清单消失。

**[rank19] LLM 可回放：04 采纳但把它从'脊柱前提'降级为一条 schema 字段，且 LLMCallRecord 缺禁裸别名钉定护栏**  `严重度:low · 核查:high — 04 §3.1 LLMCallRecord 字段与 06 §2.4 核对;arch §6 有 ReplayDiverged 事件但无精确相等阈值定义`
> 04 §3.1 把 LLMCallRecord 前移 P0+strict replay 不重采样(忠实采纳)。低估:(1)Claude(01 ⚠️/03 盲点2)定位为'脊柱成立的前提依赖'(不解决就别声称可回放),04 未在 §0 总裁决里把'先解决 LLM 非确定性再建确定性图'列为顺序约束;(2)LLMCallRecord 有 model/model_version 但没写 06 §2.4'禁裸别名 gpt-4o、必须存 gpt-4o-2024-08-06+system_fingerprint+ReplayDiverged 对结构化裁决精确相等'。
- **裁断**：方向一致、属轻度软化非矛盾。06 已补齐操作级,按 06 为准即可。无需升格为高严重度。建议 04 §0 加一句顺序约束、§3.1 LLMCallRecord 补 system_fingerprint+禁裸别名+ReplayDiverged 阈值。
- **动作**：可复现(改 04 §0+§3.1+回写 GOAL §1.2):§0 加顺序约束'先解决 LLM 非确定性再声称确定性图可回放';§3.1 LLMCallRecord 补 system_fingerprint+禁裸别名(存 gpt-4o-2024-08-06)+ReplayDiverged 对结构化裁决精确相等阈值;GOAL §1.2 写入 L1 数值±1e-6/L2 record-replay 两层定义。按 06 §2.4 为准。

**[rank20] 两层可复现定义(L1 数值±1e-6 / L2 record-replay)：04 实现了机制但没写下'定义'并回写 GOAL §1.2**  `严重度:low · 核查:high — GOAL §1.2 已正确把 ±1e-6 锁定在数值计算(06 §2.4 L60 确认)`
> 04 §3.1+架构稿 §9 机制(缓存响应/strict 不重采样/live_llm 仅调查)与 Claude 完全一致(忠实);真缺的是把 03 盲点(2)核心矛盾(±1e-6 在 LLM 节点失效)显式调和成两层定义并回写 GOAL §1.2。
- **裁断**：Claude 对,属'机制采纳、定义缺位'非矛盾。保留 04 机制,按 06 §2.4 把两层定义+不可变模型版本钉定+system_fingerprint+ReplayDiverged 阈值补进 spec 并回写 GOAL §1.2。与 rank19 同源,主裁让 rank19。


---

## 7. 诚实纠正 / 降级（完备性复核对本账本自身的纠偏）

- **rank1 DSR 裸分——严重度降半档**：复核查代码确认，DSR≥0.6/0.8 裸分**只在 Codex 架构设计稿 §10**；现有 shipped 代码 `risk_summary.py` 把 DSR 当 [0,1] 置信度处理（L16 注释 dsr<0.2 不可信、L109 low_dsr_confidence），读法与 Claude **一致**；代码里的 0.6 是 **PBO 阈值**（L91 pbo>0.6）不是 DSR。→ **这是设计稿层的政策分歧，不是已落地的 bug。**
- **rank20 两层可复现定义——更像文档待办而非实质对立**：GOAL §1.2（L41）已正确把 ±1e-6 锁在数值计算；04 §3.1 + 架构稿 §9 机制（缓存/strict 不重采样）与 Claude 一致，真缺的只是"把 L1/L2 定义写下来并回写 GOAL"。
- **rank22 UI 分层——并入 rank10**：是 quant 逃生舱/双速通道在 UI 层的同一诉求投影，非独立命题对立。


---

## 8. 待你拍（政策决定，非技术可裁）

- **FDR 主判据 vs 辅助证据**（rank13）：04 §4.5 + 架构稿 §10 把 FDR 与 t≥3.0 平列为合法主判据；Claude 全线（README/roadmap）立场是"FDR 不解决发表偏误、只作辅助"。**默认按"辅助"**，除非支撑升级的 Chen 2024 引用被定向核查为确凿推翻 Chen-Zimmermann（该引用目前未过 360KB 附录核查）。
- **PBO 硬线取 0.5 还是 0.05**（rank12）：维持 PBO>0.5 block / >0.6 quarantine 作默认；支撑 PBO>0.05 决策线的 Neyman-Pearson 引用**未过附录核查**，列为待核实开放项、不升 schema 硬线。
