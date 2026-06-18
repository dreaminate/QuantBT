# Codex / Claude Agent OS 研究分歧裁决

日期：2026-06-15  
范围：对比 `docs/plans/agent-os-technical-architecture.zh.md` 与 `docs/institutional-agent-os/*`，给出最终合成方案、真实分歧、优先级修正和需要回写到实现的 schema/gate/UI。

## 0. 总裁决

两份研究不是互相推翻，而是层级不同。

- `docs/plans/agent-os-technical-architecture.zh.md` 是 **可实现的 Agent OS kernel 蓝图**：它把 durable kernel、SQLite WAL event store、Typed Multi-Agent Protocol、ToolPolicyProxy、checkpoint/replay/rollback、API、UI、测试和 8 阶路线写成工程合同。
- `docs/institutional-agent-os/*` 是 **机构级治理与方法学审计**：它把“为什么这些 gate 必须存在”、现有代码有哪些硬洞、LLM 非确定性/安全/成本/RBAC/OOS 隔离/HITL 疲劳等承重风险讲得更完整。

最终方案应采用：

```text
Codex 的自有 AgentOSKernel 作为实现脊柱
+ Claude 的确定性治理 DAG 作为流程形态
+ Claude 的机构级量化方法学作为 gate 内容
+ Claude 的风险降权作为路线修正
+ Codex 的 API/schema/test/UI 合同作为落地表面
```

一句话：**Codex 是骨架，Claude 是机构级韧带和风控神经。**

---

> ## 🔒 用户拍板裁定（2026-06-15）—— 与下方原文冲突时以此为准
>
> 以下由用户拍板（D1–D9 + 2 条新增）。完整冲突账本见 [07-codex04-conflict-ledger.md](07-codex04-conflict-ledger.md)，操作级落地见 [06-divergence-deepdive.md](06-divergence-deepdive.md)。
>
> 1. **D1 架构=折中**：取 Codex durable kernel 形态作脊柱，但 **run/model/strategy 级 lineage 归一到提升后的现有 `experiments/store`（M12），不另起平行账本**；`agent_os` 只新增 step/checkpoint/approval/gate 这类 M12 没有的维度。（修订 §1「架构主张」行的"不冲突"）
> 2. **D2 真隔离（边界=agent）**：holdout/OOS 分区**加密落盘**（复用 `SecureKeystore` Fernet AES），解密密钥**不在探索/研究 agent 进程可达**、**仅在显式 HITL 揭盲事件释放**——对 agent 是**密码学级真隔离**（非仅 policy）；用户自己持密钥可手动解（不隔离人，符合本地优先）。配 `read_holdout` side-effect class（揭盲前默认拒绝）+ `HoldoutAccessAttempted`/`HoldoutRevealed` 事件 + 访问计数入 gate。（**取代 §9#5**）
> 3. **D3 确定性节点 + 实盘 agent 边界**：组合/执行/风控/promotion/capital allocation 由**确定性代码**执行、agent 只读结果（§2 已对）；**agent 只参与策略开发/研究**；**实盘里 agent 只①提交警告 ②达预设规则后停止策略**，无任何自主 live 动作。→ 架构稿 §7 把 RiskOptimizer/ComplianceExecution 实例化为 Agent 角色须改叙述为**确定性 gate 节点**。
> 4. **D4 单用户 RBAC**：`approver≠creator` 由 kernel 校验，但单机/单用户下**物理不可强制**——UI 必须诚实标注"独立验证需外部第二人"。
> 5. **D5 FDR=辅助证据**（不升主判据）：支撑升级的 Chen 2024 引用经一手核查为 mischaracterized（同作者 build-on Chen-Zimmermann、非反驳；"强识别"是对统计量而非决策阈值，阈值原文称 subjective）。
> 6. **D6 PBO 硬拒绝线=0.05**（依 BBLZ §3.1 Neyman-Pearson "customary approach"，标"习惯做法非定理"）+ 可配 profile，探索沙盒用更松 flag。**§1/§4/§10 里把 PBO 0.5/0.3 当拒绝线是误读——0.5 是 PBO 定义内部 N/2 中位边界、非拒绝阈值。**
> 7. **D7 DSR 删裸分**：删 §10 的 DSR≥0.6/0.8 裸分 cutoff，改"DSR<约定显著性（默认 0.90 paper / 0.95 prod，可配）触发人审"+ 强制暴露 N_eff/T/skew/kurt + 区间（DSR 是 [0,1] 概率、已内生这些，再叠裸分=双重计数+语义错）。
> 8. **honest-N 双字段**：`n_trials_total`（审计、反偷删、Verifier 核对）+ `n_eff`（喂 DSR/PBO，ONC 聚类估、按最保守 k 判定、`n_total<~20` 降级回 N_total）。N_eff 估计器**标开放可配**（按 canonical ONC：K-means + angular dist `sqrt(0.5(1-ρ))` + k 上界 `floor(N/2)` + silhouette），**不写"LdP2019 规范"**（LdP2019 把 ONC 委托给 LdP&Lewis2018，原文无此具体配方）。
> 9. **D8 排期**：本文头 4 条高严重度已就地修订（§1 两行 + §8 P0 + §9#5），其余裁定见 07；随后转 P0 实现。
>
> **新增 scope / 原则**：① **DL/ML 模型管理是一等子系统**——用户会贴讲策略 / 讲 DL·ML 模型的各种论文文章，不只拆策略还要整套模型管理（见 [05-paper-to-strategy-and-model-management.md](05-paper-to-strategy-and-model-management.md)，审查中）；② **个性化原则**：gate 阈值 / profile / 披露层级 / 工作流由 **agent 辅助用户按各自偏好调整**，非全局硬真理（不仅限阈值）。

## 1. 真实冲突与裁决

| 维度 | Codex 研究稿 | Claude 研究包 | 裁决 |
|---|---|---|---|
| 架构主张 | 自建 `agent_os/*` durable kernel，SQLite WAL 为事实源。见 `agent-os-technical-architecture.zh.md` §3-4。 | 确定性 DAG 骨架 + 节点内有界 LLM + 弱耦合环节才 fan-out。见 `01-agent-os-design.md` §架构选择。 | 🔒**路线分歧（D1，见上方裁定块）**：取 Codex durable kernel 形态作脊柱，但 run/model/strategy 级 lineage **归一到提升后的 `experiments/store`、不另起平行账本**，`agent_os` 只新增 step/checkpoint/approval/gate。原"不冲突"掩盖了双账本风险。 |
| 多 agent 边界 | 完整 role registry 与 handoff contract。 | 警惕自由编排，组合/执行/promotion 不能自由 agent 化。 | Claude 更严。只允许 Orchestrator 调度，specialist 不互聊；fan-out 仅限文献海、因子海、候选假设生成等弱耦合任务。 🔒**D3 加严**：组合/执行/风控/promotion 是**确定性代码节点**（agent 只读）；**实盘 agent 仅"提交警告 + 达规则停"**；架构稿 §7 的 RiskOptimizer/ComplianceExecution**不得**实例化为 LLM-agent，须改叙述为确定性 gate 节点。 |
| 可回放 | Codex 定义 strict replay：重放记录过的 LLM/tool outputs。 | 指出 LLM 节点非确定性会破坏“确定性 DAG 可回放”承诺。 | Claude 补强。必须记录 prompt hash、model id、provider、temperature、seed、tool schema version、response cache hash；strict replay 不重新采样 LLM。 |
| 安全顺序 | 安全与 red-team 在 Phase 7/8 比较靠后。 | prompt injection、tool abuse、data poisoning、权限混淆必须前移 P0/P1。 | Claude 胜出。任何能接触交易 key、外部文本、工具调用的 Agent OS，安全模型必须进入第一批 contract。 |
| “流程即信任” | 默认把可审计流程作为信任基础。 | 指出该论断本身未被预注册、未验证。 | Claude 胜出。把“流程即信任”作为产品假设，加入可证伪指标和用户研究代理。 |
| Gate 阈值 | PBO/DSR/t-stat 等给出静态默认阈值。 | 要求随 materiality、N_eff、研究族、FDR/FWER、live/paper 阶段调整。 | 以 Codex 阈值作默认 profile，但不能硬编码为普遍真理；gate policy 必须 materiality-aware。 |
| Lineage | 给出 Dataset/Feature/Label/Experiment/RunProvenance schema，禁止 `latest`。 | 补 bitemporal、OpenLineage、column-level lineage、data contract、PIT/freshness。 | 合并。Codex schema 是最小合同；Claude lineage 要求进入 P0/P1 hardening。 |
| 组合/执行/配资/资产抽象 | 只写了 capacity/slippage/monitoring 级别的通用 gate。 | 展开为 Ledoit-Wolf/RMT/BL/HRP/NCO、TCA/IS、meta-allocation、InstrumentSpec。 | Claude 是必要 domain depth，应回写为 domain schemas/gates/UI，但不能绕过 Codex approval boundary。 |
| UI | 组件/API 清楚：Lifecycle Rail、Evidence Drawer、Approval Inbox、TrustReport。 | 强调决策语义：假设卡、可证伪条件、L1-L4、反事实、go/no-go 卡片。 | 合并。Codex 做界面骨架，Claude 定义每个界面块必须承载的经济判断。 |
| RBAC / HITL 疲劳 | 有 approval interrupt。 | 强调 `creator != verifier != approver`、闸门疲劳、批处理/委派、quant 逃生舱。 | Claude 补必需产品机制。Approval 不是按钮表，而是角色、疲劳与授权设计。 |

## 2. 最终采用的 Agent OS 架构

### 2.1 控制平面

```text
/agent-os UI
  -> AssistantShell
  -> AgentOSKernel
    -> Deterministic Governance DAG
    -> SQLite WAL Event Store
    -> Checkpoint / Replay / Fork / Rollback
    -> ToolPolicyProxy
    -> Approval Queue
    -> Artifact + Lineage Ledger
    -> Governance Gate Engine
```

### 2.2 执行策略

- QuantBT 自己的 SQLite WAL / event ledger 是审计事实源。
- DBOS/Temporal/LangGraph 只能作为 durable executor / persistence 模式参考，不能替代 QuantBT 的业务 ledger。
- LLM 只在 DAG 节点内做有界任务。
- 节点间流转必须是结构化 state transition，不允许 agent 群聊式自由编排。
- fan-out subagent 只用于高价值、弱耦合、信息量超过单上下文的问题，例如文献海、因子海、候选假设生成、对抗式复核。
- 组合、执行、promotion、live trading、capital allocation 只能走确定性 gate + approval。

外部依据：

- [StateFlow](https://openreview.net/forum?id=3nTbuygoop) 支持 state-driven workflow，说明复杂 LLM task 应把 process grounding 与子任务求解分开。
- [Magentic-One](https://www.microsoft.com/en-us/research/articles/magentic-one-a-generalist-multi-agent-system-for-solving-complex-tasks/) 支持 Orchestrator + Task/Progress Ledger，但不意味着可以自由群聊。
- [OpenAI Agents SDK HITL](https://openai.github.io/openai-agents-python/human_in_the_loop/) 支持审批中断和 run state resume。
- [LangGraph persistence](https://docs.langchain.com/oss/python/langgraph/persistence) 支持 checkpoint/time travel/HITL 的工程模式。
- [Temporal durable execution](https://temporal.io/blog/idempotency-and-durable-execution) 和 [DBOS Agents SDK integration](https://docs.dbos.dev/integrations/openai-agents) 支持 durable execution/idempotency 的工程边界。

## 3. 必须前移的 P0/P1 修正

Claude 研究包中这些不是“后续增强”，而是 Agent OS 成立前的必要前提。

### 3.1 LLM 可回放合同

新增 `LLMCallRecord`：

```text
llm_call_id
run_id
step_id
provider
model
model_version
temperature
seed
system_prompt_hash
developer_prompt_hash
user_prompt_hash
tool_schema_hash
retrieval_context_hash
response_text_hash
response_json_hash
usage
created_at_utc
cache_policy
```

规则：

- strict replay 使用缓存响应，不重新调用 LLM。
- live_llm replay 只能作为调查模式，不能声明等价复现。
- prompt/model/tool schema 未记录完整时，run 只能是 audit-only，不可进入 production promotion。

### 3.2 安全模型前移

P0/P1 必须覆盖：

- prompt injection，经外部文献/新闻/网页/用户文件进入。
- tool abuse，尤其任何可能写 artifact、promote、下单、改 registry 的工具。
- data poisoning，尤其因子海、文献海、外部数据源。
- privilege confusion，尤其探索 agent 与 OOS/holdout 的边界。
- secret handling，尤其交易 key 不进入 serialized run state。
- least privilege tool scopes。
- side-effect approval。
- red-team regression suite。

外部依据：[OWASP LLM01](https://genai.owasp.org/llmrisk/llm01-prompt-injection/) 明确要求隔离外部内容、最小权限、格式验证、高风险 human review 和对抗测试。

### 3.3 “流程即信任”自证

这不是实现细节，是产品假设。需要预注册：

```text
TrustHypothesis:
  target_user_group: beginner | economist | risk_pm | quant
  claim: workflow evidence improves calibrated trust
  falsification_condition:
    - user approves high-risk strategy despite visible red gate
    - user cannot explain why gate blocked
    - user over-trusts strategy after seeing lineage graph
  measurement:
    - calibration score
    - correct go/no-go rate
    - over-trust rate
    - approval fatigue rate
    - time-to-decision
```

这会防止“我们做了复杂流程，所以用户就会恰当信任”的自我安慰。

### 3.4 数据可信度成为第一闸门

任何因子、模型、回测之前必须先过：

- explicit dataset version lock。
- manifest hash。
- PIT universe。
- `known_at/as_of`。
- field-level provenance。
- data quality result。
- freshness by market calendar。
- no `latest` in governed runs。

## 4. 统一后的 9 层 Gate 体系

### 1. Governance Profile Gate

按 exposure、purpose、complexity、automation 定 materiality tier。SR 26-2 是当前监管锚点，不再把 SR 11-7 当主锚点。

外部依据：[Federal Reserve SR 26-2](https://www.federalreserve.gov/supervisionreg/srletters/SR2602.htm) 于 2026-04-17 发布，取代 SR 11-7 和 SR 21-8。

### 2. Pre-registration Gate

冻结：

- `economic_mechanism`
- `falsification_condition`
- `stop_rule`
- universe
- metrics
- OOS/holdout policy
- N budget
- confirmatory/exploratory 标记

### 3. Data / Lineage Gate

强制：

- dataset version，不准 `latest`。
- dataset manifest。
- feature spec。
- label spec。
- `t1`。
- PIT/as-of。
- field-level lineage。
- artifact manifest。

### 4. Trial Ledger Gate

所有 failed/cancelled/hidden/rejected trials 都计入 N。`n_trials` 不能由用户手填。

### 5. Falsification Gate

包含：

- PBO/CSCV。
- DSR/PSR。
- Bootstrap CI。
- White Reality Check。
- Hansen SPA。
- Romano-Wolf / BHY / FDR。
- CPCV + walk-forward 双轨。
- MinBTL / MinTRL。

注意：Codex 原文中的 PBO/DSR 静态阈值只能作为 default profile，不能作为全市场、全 materiality 的硬真理。

### 6. Economic Plausibility / Factor Gate

策略必须解释：

- 赌的是什么 risk premium / behavioral bias / market microstructure。
- alpha 是否被 benchmark/style/factor exposure 吃掉。
- 新因子相对现有因子族是否有增量。
- 是否跨资产/跨样本方向一致。
- 是否存在 post-publication decay / crowding 风险。

### 7. Independent Validation Gate

要求：

- creator != verifier。
- verifier/challenger 有权 block。
- validation dossier 包含独立重跑、异数据切片、异 seed/模型、证据快照。
- approver != creator。

这对应 SR 26-2 的 model inventory、validation、effective challenge、ongoing monitoring 原则。

### 8. Promotion / Production Gate

规则：

- promotion 一次只升一级。
- exception 必须 owner/reason/expiry/max_stage/recertification trigger。
- hash mismatch、lookahead/leakage、缺 PBO/DSR、active kill switch、SafeKey/testnet 失败、A 股 live 禁令不可 override。

### 9. Live Monitoring / Demotion Gate

live 阶段不能机械复用 pre-production DSR 阈值。应使用：

- rolling PSR。
- MinTRL。
- CUSUM / Page-Hinkley / BOCPD。
- live-vs-backtest regime conditional comparison。
- slippage/TCA drift。
- IC decay。
- cost drift。
- drawdown breach。
- capacity breach。

drift 触发再验证和降级/退役，不自动替换 live model。

## 5. Lineage Backbone 的硬缺口

子代理复核指出，当前代码现状与目标最直接冲突的是 lineage。

必须 P0 harden：

1. `RegistryDatasetSource` 当前取 latest；governed run 必须改为显式 `version_id`，缺 version fail。
2. `DatasetRegistry.register()` 只 append `DatasetVersion`，还没有强制写/校验 `DatasetManifest`。
3. `DatasetManifest` 需要从文件 hash 扩展到 schema hash、partition stats、source request、quality result、PIT metadata。
4. `FieldRequirement` 和 `PanelResult` 需要输出 field-level provenance：dataset id/version、raw column、file hash、schema hash、as_of。
5. Label pipeline 必须产出 `t1`；训练路径必须把 `t1` 传给 `purged_kfold`。
6. `Run.inputs` 不能继续是自由 dict；必须升级为 `RunProvenance`。
7. `ModelRegistry.promote()` 不能裸改 stage；必须接 gate evidence + approval。
8. JSONL ledger 不能静默跳过坏行；审计账本损坏应进入 explicit integrity incident。

外部依据：

- [MLflow Dataset Tracking](https://mlflow.org/docs/latest/ml/dataset/) 支持 dataset lineage/reproducibility。
- [MLflow Model Registry](https://mlflow.org/docs/latest/ml/model-registry/) 支持 model versions、aliases、tags、governance。
- [OpenLineage Facets](https://openlineage.io/docs/spec/facets/) 可作为 run/job/dataset metadata 导出标准。
- [DVC pipelines](https://doc.dvc.org/user-guide/project-structure/dvcyaml-files) 与 lockfile 模式可作为 ExperimentPlan / artifact manifest 参考。
- Delta/Iceberg 的 snapshot/manifest/schema evolution/time travel 说明：file hash 不等于完整 data versioning。

## 6. Claude 应回写到 Codex 的 Domain Schemas

### Portfolio / Risk

- `PortfolioConstructionSpec`
- `CovarianceModelSpec`
- `BlackLittermanViewSpec`
- `RiskBudgetSpec`
- `LeverageSizingSpec`
- `RiskDecompositionReport`
- `PortfolioBenchmarkComparison`

### Execution / TCA

- `TCAReport`
- `ExecutionScheduleSpec`
- `ImplementationShortfallReport`
- `CapacityEstimate`
- `CostModelCalibration`
- `ParticipationLimitPolicy`

### Capital Allocation

- `StrategyAllocationBook`
- `CapitalFlowEvent`
- `CenterBookExposure`
- `DrawdownKillScalePolicy`
- `CrossStrategyCorrelationSnapshot`

### Asset Abstraction

- `InstrumentSpec`
- `InstrumentIdentifierMap`
- `AssetClassRegistry`
- `CalendarSessionSpec`
- `CorporateActionPolicy`
- `ContinuousFutureSpec`
- `PerpFundingSpec`
- `BorrowFeeSpec`
- `FXConversionPolicy`

## 7. Claude 应回写到 UI 的金融可视化

Codex 版 UI 骨架是对的，但还需要 Claude 的“经济判断表达”。

### Lifecycle Rail

应改为：

```text
意图
-> 假设卡
-> 数据/资产假设
-> 因子/标签/模型
-> 验证
-> 组合
-> 成本/容量
-> 审批
-> paper/testnet/live
-> 监控/退役
```

### Structured Decision Workspace

需求澄清阶段必须展示：

- `economic_mechanism`
- `falsification_condition`
- `stop_rule`
- benchmark
- sample window
- OOS/embargo
- confirmatory/exploratory

### Evidence Drawer

必须放：

- lineage DAG。
- validation dossier。
- dataset manifest。
- PBO/DSR/bootstrap。
- factor attribution。
- TCA。
- capacity。
- live drift。
- approval / verifier / approver 分离状态。

### 必备图形

- 过拟合体检红黄绿。
- PBO/DSR/Bootstrap 证据卡。
- 因子风险/MCTR 分解。
- 1/N / HRP / optimized 对照。
- Implementation Shortfall 瀑布图。
- 冲击曲线与容量区间。
- 资本流向 Sankey。
- 策略相关矩阵。
- Live backtest-vs-live 区间带。
- MinTRL 进度条。
- A 股 T+1/涨跌停/复权、crypto funding/24x7、期货换月的资产隐含约束清单。

## 8. 新路线图

### P0：信任脊柱前置合同

- `HypothesisSpec`。
- `AgentOSRun/Event/Step/Checkpoint/Approval/GateVerdict`。
- `LLMCallRecord`。
- ToolPolicyProxy。
- no-live default。
- prompt injection/tool abuse/data poisoning/security baseline。
- 🔒**红队回归套件（D-安全，前移）**：prompt-injection/tool-abuse/data-poisoning/privilege-confusion 回归测试，**与 verifier 同期落地、不滞后到架构稿 §16 的 Phase 8**（以 05-paper §12 P0 为模板）。
- dataset version lock。
- manifest hash。
- `t1` gate。
- trial ledger。
- model promotion approval gate。
- TrustHypothesis instrumentation。

### P1：Durable AgentRuntime + Lineage Backbone

- wrap existing `AgentRuntime`。
- record LLM/tool calls as kernel events。
- response cache for strict replay。
- checkpoint before/after side effects。
- field-level provenance。
- data contract artifact。
- RunProvenance。
- OpenLineage export adapter。

### P2：第一条受控 Vertical Slice

```text
raw intent
-> HypothesisSpec
-> StrategyGoal
-> dataset lock
-> DataGateResult
-> deterministic backtest adapter
-> ValidationDossier
-> TrustReport
-> ApprovalQueue
-> no live trading
```

### P3：机构级验证与 promotion gate

- DSR/PBO/bootstrap 接真实 run。
- White RC / Hansen SPA / FDR family。
- CPCV + walk-forward 双轨。
- independent verifier。
- model passport。
- promotion/demotion policy。

### P4：组合、执行、配资、资产抽象

- InstrumentSpec minimal subset 前移。
- cost model 接线。
- TCA/Implementation Shortfall。
- risk decomposition。
- 1/N/HRP benchmark。
- StrategyAllocator。
- kill/scale policy。

### P5：`/agent-os` 工作台

- Lifecycle Rail。
- Structured Decision Workspace。
- Evidence Drawer。
- Approval Inbox。
- GateTimeline。
- TrustReport。
- RunReplay。
- audience disclosure switch。

### P6：Live monitoring 与退役闭环

- rolling PSR / MinTRL。
- change-point detection。
- cost drift。
- IC decay。
- drawdown/capacity breach。
- demotion/retirement HITL。

## 9. 不能直接照搬的 Claude 内容

Claude 研究包总体更全面，但有些内容必须降权：

1. 撤稿或不稳定来源不能做硬 gate，只能做 soft monitoring。
2. pod kill/scale 的 5%/7.5% 阈值不能硬编码，只能用户预注册或 profile 默认。
3. 平方根冲击律存在 AQR 争议，必须显示敏感性区间。
4. `N_eff` 不是低工程量接线，是深统计问题；估错会静默破坏所有多重检验校正。
5. 🔒**D2 已拍板=真隔离（见上方裁定块，取代本条原文）**：OOS holdout **加密落盘**（复用 `SecureKeystore` Fernet AES），解密密钥**不在探索 agent 进程可达、仅 HITL 揭盲事件释放**——对 **agent 是密码学级真隔离**（非仅 policy enforcement）；用户自己持密钥可手动解（**不隔离人**，符合本地优先 / 可独立审计导出）。配 `read_holdout`（揭盲前默认拒绝）+ `HoldoutAccessAttempted`/`HoldoutRevealed` 事件 + 访问计数入 gate。原"只能 signed manifest + policy enforcement、不能硬隔离"作废。
6. “谱系图让经济学者更信任”是待验证产品假设，不是既定事实。

## 10. 最终行动清单

应立即回写到 `docs/plans/agent-os-technical-architecture.zh.md` 的内容：

- LLM 可回放合同。
- 安全模型前移。
- TrustHypothesis instrumentation。
- `HypothesisSpec`。
- 9 层 gate。
- Lineage Backbone P0 hardening。
- InstrumentSpec minimal subset 前移。
- domain schemas/gates/UI。
- P0-P6 新路线图。

应保留在 `docs/institutional-agent-os/99-research-appendix.md` 的内容：

- 17 条主线的长论文综述。
- SOTA 列表。
- 对抗式核查裁决。
- 争议来源和降权证据。

应后续进入 Obsidian 的内容：

- 本文件作为 “Codex/Claude 分歧裁决”。
- `Agent OS 研究 MOC` 增加一条链接。
- “流程即信任”单独成为产品假设笔记。
- “Lineage Backbone” 单独成为实现约束笔记。

