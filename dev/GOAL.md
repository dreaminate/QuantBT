# GOAL · 项目完整最终形态（目标台）

> 终态契约。所有实现、任务、状态、验证都对照本文。
> 来源：原始 GOAL、现有 dossier、`decisions/`（R1-R29/S1-S4/D-QRO-CANVAS），以及新目标：所有公开二级市场、Agent-native 多台 OS、Research Asset RAG、全资产生命周期、市场联动、数据接入、Ingestion Skill 生命周期、LLM Provider/Auth/Gateway、Mathematical Spine、Theory-to-Implementation Consistency、用户方法学放权。
> 每节新增或改动后，同步 `research/TRACE.md`，保留对应 finding、decision、task、验收关系。
> `RunDetailPage` 继续冻结：只允许排版、显示逻辑、加字段。

<!-- 格式·防跑偏 | 结构型：固定节序 §0 北极星 → §1 统一对象模型 → §2 多台工作系统 → §3 生命周期与资产库 → §4 Data Onboarding / Settings / Skill → §5 Research Asset RAG → §6 Research / Document Intelligence / Mathematical Research Layer → §7 Agent Shell / Multi-Agent Research OS → §8 治理脊柱 → §9 因子、模型、信号、策略边界 → §10 方法学与验证 → §11 数据层与标的接入 → §12 执行边界 → §13 信任层 → §14 功能平台 M1-M21 → §15 模型治理 → §16 工程标准 → §17 交付标准。
每节包含终态主张、决策、可证伪验收；改节内容同步 research/TRACE.md。 -->

## 0. 北极星

QuantBT 是面向**所有公开二级市场标的**的 **Agent-native / canvas-native / governance-first Institutional Quant Research-to-Execution OS**。

覆盖股票、指数、ETF、基金、债券、利率、外汇、期货、商品、期权、加密现货、加密永续、加密期权、宏观数据、链上数据、另类数据、用户自定义数据。IPO、一级市场、私募、非公开交易在主范围之外。系统定位为中低频研究到执行 OS，范围边界排除 HFT、做市、延迟套利。

QuantBT 提供对象模型、数据接入、Settings/Integrations/Secrets、LLM Provider Registry、LLM Gateway、Model Routing、资产库、Research Asset RAG、Mathematical Spine、研究编译、验证、回测、执行边界、安全门和生命周期。市场判断、因子定义、模型定义、信号定义、StrategyBook 由 user 或常驻 Agent 产出，作为受治理资产进入系统。

数学贯穿整条流程。数据时间语义、因子、标签、模型、信号、组合、执行、成本、回测估计、归因、监控、降级和退役，只要使用方法、公式、估计器、约束、成本模型、风险度量或触发器，就能形成数学对象、推导、适用域、反例、验证绑定和实现一致性记录。

方法学松紧、是否走某个流程、是否继续推进，由 user 决定。QuantBT 负责摆出选项、代价、推荐路径、证据缺口和责任边界。User 选择放宽或跳过某流程时，系统记录 `MethodologyChoiceRecord` 与 `ResponsibilityDisclosureRecord`，继续交付对应可达环境内的产物。任何被 user 放宽的产物都按真实状态展示，不升级成 proof-backed、evidence sufficient 或 production-ready。

QuantBT 是 Agent-native OS。Agent 常驻每个台，始终带上下文，能观察、建议、执行、生成、验证。User 可以手动完成所有流程。动作来源统一记录为：

```text
user_manual
agent
user_confirmed_agent
scheduled_agent
```

四类动作共享同一套 QRO、Research Graph、资产生命周期、权限门、证据账本和 Research Delivery Package。

“可上线”定义：

```text
能装
能用
能从 Chat / Canvas / API / IDE / Scheduler 产生 QRO
能由 user 或 Agent 完整走完研究链路
能判断证据充分 / 不足 / 适用域 / 未验证残余
能导出开放格式 Research Delivery Package
能按权限进入 paper / testnet / live ladder
能监控、降级、回滚、退役
```

**决策**：R1-R29 / S1-S4 / D-QRO-CANVAS。

**可证伪验收**：

```text
任一入口绕过 Research Graph → 拒
任一正式结论缺 evidence_ref → 拒
任一生产结果走 silent mock fallback → 拒
任一状态把 definition/evidence/governance/runtime 混成单绿灯 → 拒
声称数学证明或机构级方法但缺 TheoryImplementationBinding → 拒
user 放宽方法学后被包装成强证据或系统背书 → 拒
```

## 1. 统一对象模型

所有正式入口进入同一条链：

```text
Quant Intent
→ Typed Canvas / Command
→ QRO
→ Research Graph
→ Governed Compiler
→ Deterministic Run
→ Evidence Verdict
→ Promotion / Approval
→ Runtime
→ Monitor / Retire
```

QRO 覆盖：

```text
Dataset
Observable
DataSourceAsset
IntegrationConfig
SecretRef
TokenRef
IngestionSkill
DatasetVersion
FreshnessStatus
SchemaDriftEvent
TheorySpec
MathematicalRequirement
TheoryImplementationBinding
ConsistencyCheck
MethodologyChoiceRecord
ResponsibilityDisclosureRecord
LLMProvider
LLMProviderAuth
LLMCredentialPool
LLMModelProfile
ModelRoutingPolicy
LLMCallRecord
ProviderHealth
ProviderQuotaStatus
Factor
Label
Model
Forecast
Signal
StrategyBook
PortfolioPolicy
RiskPolicy
ExecutionPolicy
Experiment
BacktestRun
ValidationDossier
ResearchReport
DeskHandoff
MarketCapabilityMatrix
MathematicalArtifact
DocumentArtifact
```

各对象共享。这些必须包含，可以添加新内容：

```text
identity
version
owner / actor
typed input/output contract
market / universe / horizon / frequency
event_time / known_at / effective_at
lineage
implementation hash
assumptions
known_limits
failure_modes
validation_plan
evidence_refs
mathematical_refs
methodology_choice_ref
responsibility_boundary
theory_implementation_binding
consistency_verdict
verdict
permission
approval
allowed_environment
monitor / alert / retire rules
```

语义边界：

```text
模型本体进入 Model Registry
模型输出进入 Signal Contract
因子在 Factor Library 创建和管理
策略通过 StrategyBook 表达
组合、风控、执行分别作为 Policy 资产管理
SecretRef 是受控引用，明文 secret 只存在 Settings / Secrets 安全后端
LLMProvider / LLMProviderAuth / TokenRef 进入 Settings 和 QRO，role agent 只能通过 LLM Gateway 调用模型
API key 明文、OAuth token、device code token、CLI credential 明文只存在 Settings / Secrets 安全后端
TheorySpec / MathematicalArtifact / TheoryImplementationBinding 进入 Research Graph，任何声称按理论实现的代码、运行、报告必须引用它们
MethodologyChoiceRecord 记录 user 选择的松紧、跳过项、代价提示和责任边界
```

状态轴分离：

```text
definition: draft / specified / implemented
theory: not_required / required / drafted / derived / challenged / accepted / user_waived
consistency: not_applicable / unbound / checked / mismatch / accepted / waived_for_exploratory
evidence: untested / exploratory / challenged / sufficient / insufficient / unverified_residual
governance: unreviewed / approved / rejected / revoked
runtime: offline / paper / testnet / live / suspended / retired
```

**决策**：R1/R2/R5/R7/R8/R9/R11/R12/R17/R28 + S1-S4 + D-QRO-CANVAS。

**可证伪验收**：

```text
模型文件作为因子入库 → 拒
Signal 未绑定 Signal Contract → 拒
StrategyBook 声称引用资产但 run config 未注入 → 拒
Secret 明文进入 LLM / RAG / 日志 / 导出包 → 拒
role agent 直接调用 provider SDK 或读取 provider token → 拒
LLMCallRecord 缺 provider/model/auth_ref/replay_state → 拒
声称 implementation follows theory 但 consistency=mismatch/unbound → 拒
user_waived theory 的资产进入 proof-backed / evidence sufficient / production-ready → 拒
```

## 2. 多台工作系统

QuantBT 是共享 Research Graph 的多台工作系统。每个台都有：

```text
常驻 Agent Shell
当前台 Typed Canvas
当前台 RAG projection
当前台 Mathematical Spine projection
当前台资产列表 / inspector
当前台工具权限
```

底层事实源：

```text
Research Graph
Asset Libraries
Lifecycle State
Evidence Ledger
Permission / Approval Records
Settings / Integrations / SecretRefs
```

各台职责：

```text
数据台：数据源注册、Integration 配置、连接测试、字段映射、PIT、bitemporal、数据质量、DatasetVersion、IngestionSkill、freshness、schema drift、数据时间语义数学定义
因子台：创建、编辑、验证、分类、保存、退役因子，绑定公式、方向、适用域和失效条件
模型台：训练、验证、登记、模型卡、模型护照、模型晋级，绑定损失函数、估计器、识别假设和训练/验证一致性
信号台：定义 Signal Contract，把 factor/model output 转成信号，绑定变换、方向、置信度、过期、异常值处理
策略台：创建 StrategyBook、组合意图、多腿 long/short、约束、成本、回测计划，绑定 payoff、hedge ratio、资本账和风险度量
回测/验证台：实验、PBO/DSR/CPCV/bootstrap、归因、反证、verdict，绑定估计量、抽样、置信区间和多重检验数学
执行/风控台：paper/testnet/live ladder、risk gate、kill switch、监控、退役，绑定执行成本、滑点、冲击、保证金、kill trigger 和降级规则数学
研究台：论文、研报、网页、代码、数学定义、证据抽取、RDP
设置台：Integrations、Data Sources、LLM Providers、Secrets / API Keys / OAuth Tokens、Credential Pools、Model Routing、权限范围、连接测试、撤销与轮换
```

Agent 能力全局完整，写权限按台隔离。策略台引用 factor id / factor set / signal id / model id；因子台负责因子的创建和编辑。跨台需求通过 DeskHandoff 连接。

DeskHandoff。这些必须包含，可以添加新内容：

```text
handoff_id
from_desk
to_desk
requested_asset
reason
blocking_dependency
status
produced_ref
evidence_refs
created_by
resolved_by
```

每个台的 Canvas 都是同一 Research Graph 的 typed projection。当前台决定节点、边、状态、证据、操作按钮和可编辑资产类型。

User 手动画布、表单、IDE、API 改动都落 canonical command，与 Agent 动作进入同一 audit、lineage、lifecycle。

**决策**：D-QRO-CANVAS / R11 / R12 / R24-R27。

**可证伪验收**：

```text
策略台直接写 Factor formula → 拒
任一台维护独立真相状态 → 拒
user 手动改动未落 canonical command → 拒
DeskHandoff 完成后缺 produced_ref → 拒
当前台声称机构级方法但 Canvas 无 math/consistency projection → 拒
```

## 3. 生命周期与资产库

QuantBT 管理所有核心对象生命周期：

```text
Research Lifecycle
DataSource / Integration / IngestionSkill Lifecycle
Dataset / Observable Lifecycle
Mathematical Spine Lifecycle
TheoryImplementationBinding Lifecycle
LLM Provider / Auth / ModelRoutingPolicy Lifecycle
Factor Lifecycle
Model Lifecycle
Signal Lifecycle
StrategyBook Lifecycle
Portfolio / Risk / Execution Policy Lifecycle
Experiment / Run Lifecycle
```

受治理资产库：

```text
Data / Observable Library
DataSource Registry
IngestionSkill Registry
MathematicalArtifact Library
TheorySpec Registry
TheoryImplementationBinding Ledger
ConsistencyCheck Ledger
MethodologyChoice Ledger
LLM Provider Registry
LLM Credential Pool Registry
ModelRoutingPolicy Registry
LLM Call Ledger
Factor Library
Model Registry
Signal Library
StrategyBook Library
PortfolioPolicy Library
RiskPolicy Library
ExecutionPolicy Library
Research Evidence Library
Experiment / Run Ledger
```

每个资产至少包含。这些必须包含，可以添加新内容：

```text
identity / version / category / tags / owner
definition / intended_use / economic_rationale
applicable_assets / assumptions / known_limits
dependencies / evidence_refs / validation_plan
verdict / lifecycle_state / uses / used_by
promotion_history / retire_reason
```

资产类型分层：

```text
example
template
demo
tutorial
user_asset
production_asset
```

StrategyBook 生命周期：

```text
idea
→ draft StrategyBook
→ specified legs / universe / constraints / costs
→ linked factors / models / signals
→ backtest candidate
→ validation dossier
→ paper / testnet candidate
→ approved runtime version
→ monitored runtime version
→ suspended / demoted / retired
→ fork / clone / archive
```

Research 生命周期：

```text
research question
→ source intake
→ evidence extraction
→ hypothesis / counter-hypothesis
→ math definition
→ experiment plan
→ data lock
→ implementation
→ run
→ validation / challenge
→ claim / no-claim
→ Research Delivery Package
→ asset promotion / rejection
→ later review / contradiction / retirement
```

DataSource / Integration / IngestionSkill 生命周期：

```text
source discovery
→ source type classification
→ Settings integration requirement
→ user fills secret in Settings
→ connection test
→ schema / profile scan
→ field mapping
→ time semantics: ts / known_at / effective_at
→ IngestionSkill generation
→ dry-run
→ data quality tests
→ DatasetVersion
→ DataSourceAsset registration
→ manual / scheduled / event-triggered refresh
→ freshness / schema drift monitoring
→ repair / revoke / retire
```

IngestionSkill 支持版本、测试、修复、手动运行、定时运行、事件触发运行、停用、回滚、退役。

Mathematical Spine 生命周期：

```text
research / asset / run intent
→ mathematical requirement detection
→ MethodologyChoiceRecord
→ TheorySpec / MathematicalArtifact
→ assumptions / definitions / derivation / proof sketch / counterexample
→ ImplementationSpec
→ code generation / user code binding
→ unit / property / simulation / numerical check
→ TheoryImplementationBinding
→ ConsistencyCheck
→ used_by data/factor/model/signal/StrategyBook/policy/run/report/monitor
→ revision / waive / retire
```

MethodologyChoiceRecord 支持：

```text
strict institution-grade path
exploratory path
user-waived proof path
user-waived validation path
custom methodology path
```

User 选择放宽时，系统继续产出，并把状态限制在对应可达环境。放宽记录必须进入证据、报告、RAG 和 RDP。

LLM Provider / Auth / ModelRoutingPolicy 生命周期：

```text
provider discovery
→ provider type classification
→ auth method selection
→ Settings provider wizard
→ user completes API key / OAuth / device code / existing CLI credential / enterprise gateway setup
→ SecretRef / TokenRef
→ connection test
→ model profile scan
→ credential pool registration
→ cost / quota / retention policy
→ ModelRoutingPolicy
→ role-agent binding
→ health / quota monitoring
→ rotation / revoke / retire
```

**决策**：R13/R15/R16/R17/R18/R19/R21/R22/R28 + D-QRO-CANVAS。

**可证伪验收**：

```text
正式资产缺 category / lifecycle_state / evidence_refs → 拒
demo/template 进入 production_asset 无 promotion record → 拒
IngestionSkill 更新数据缺 DatasetVersion → 拒
退役资产仍被新 run 默认引用 → 拒
声称 proof-backed 但缺 ConsistencyCheck → 拒
user-waived methodology 缺责任边界记录 → 拒
```

## 4. Data Onboarding / Settings / Skill

数据台支持：

```text
official connector
Generic REST
user upload
local CSV / Parquet
local folder
local SQLite / DuckDB
Postgres / MySQL / ClickHouse / Mongo
remote database
third-party API key source
crawler-produced wide table
custom connector
```

QuantBT 内置 Settings / Integrations / Secrets 管理：

```text
Settings
→ Integrations
→ Data Sources
→ Secrets / API Keys
→ Connection Test
→ Permission / Scope
→ SecretRef
```

Agent 在数据台辅助 user 完成：

```text
识别数据源类型
生成接入计划
说明 Settings 需要填写的字段
调用已注册 SecretRef 做连接测试
扫描 schema
生成字段映射
生成 PIT / bitemporal 规则
生成 IngestionSkill
运行 dry-run
生成数据质量检查
排查更新失败
监控 freshness 与 schema drift
```

User 可以在 Settings 里手动新增、编辑、测试、撤销、轮换 API key。Agent 使用 SecretRef 调用后端 connector。明文 secret 只进入 Secrets 安全后端。

IngestionSkill 记录。这些必须包含，可以添加新内容：

```text
skill_id
source_type
source_ref
connector_config
schema_mapping
secret_refs
refresh_mode: manual / scheduled / event_triggered
data_quality_tests
PIT / bitemporal rules
output_dataset_id
owner
version
lifecycle_state
last_run
last_success
freshness_status
drift_alerts
failure_reason
permission_scope
dependency_lock
schedule_owner
rollback_plan
```

Skill 运行安全：

```text
sandbox
dependency lock
permission scope
dry-run diff
rollback plan
failed-run quarantine
downstream impact preview
schedule ownership
```

每次数据更新记录。这些必须包含，可以添加新内容：

```text
source_ref
ingestion_skill_version
secret_ref
checksum
dataset_version
known_at / effective_at
quality_verdict
lineage
freshness_status
schema_drift_status
```

Secret 管理记录。这些必须包含，可以添加新内容：

```text
secret_ref
scope
created_at
last_test
last_used
rotation_record
access_audit
stale_warning
connector_scope_review
revoked_at
affected_skills
```

撤销 SecretRef 后，相关 skill 自动降级、暂停或进入待修复状态。

DataSourceAsset 记录。这些必须包含，可以添加新内容：

```text
license
redistribution_rights
rate_limit
ToS constraints
commercial_use_status
retention_policy
source_owner
source_url_or_path
```

LLM Provider / Auth / Gateway 管理：

```text
Settings
→ LLM Providers
→ Auth Method
→ SecretRef / TokenRef
→ Credential Pool
→ Model Profile
→ LLM Gateway
→ ModelRoutingPolicy
→ LLMCallRecord
```

支持的 provider 接入形态：

```text
OpenAI account auth / OpenAI API key
Anthropic account auth / Anthropic API key / existing Claude Code credential
OpenRouter / model gateway
enterprise gateway
OpenAI-compatible custom endpoint
local model endpoint
```

支持的 auth method：

```text
API key
OAuth / account auth
device code
existing CLI credential import
custom endpoint credential
enterprise managed credential
local endpoint without external credential
```

涉及明文 secret、OAuth consent、device code 确认时，系统把 user 带到 Settings 的指定字段或授权入口。Agent 在授权完成后只拿 SecretRef / TokenRef 调用后端能力。

Agent 在设置台辅助 user 完成：

```text
识别 provider 类型
生成接入计划
说明 Settings 需要填写的字段
引导 user 完成 API key / OAuth / device code / CLI credential import
调用 SecretRef / TokenRef 做连接测试
扫描 model capability
生成 LLMModelProfile
建立 LLMCredentialPool
生成 ModelRoutingPolicy
绑定 role agent 的模型策略
排查认证、额度、限流、模型不可用
监控 provider health 与 quota status
```

User 可以在 Settings 里手动新增、编辑、测试、撤销、轮换 LLM provider credential。Agent 使用 LLM Gateway 和 SecretRef / TokenRef 调用模型。明文 provider credential 只进入 Settings / Secrets 安全后端。

LLMProvider 记录。这些必须包含，可以添加新内容：

```text
provider_id
provider_type
auth_methods
base_url
model_profiles
capability_tags
context_window
tool_calling_support
structured_output_support
cost_model
rate_limits
data_retention_policy
region / residency
allowed_roles
allowed_desks
health_status
quota_status
```

LLMCredentialPool 记录。这些必须包含，可以添加新内容：

```text
pool_id
provider_id
auth_refs
priority
rotation_policy
fallback_policy
rate_limit_policy
quota_policy
owner
last_test
last_used
revoked_refs
affected_role_agents
```

ModelRoutingPolicy 记录。这些必须包含，可以添加新内容：

```text
routing_policy_id
role_agent
desk
task_type
required_capabilities
allowed_providers
allowed_models
credential_pool_ref
fallback_order
cost_limit
latency_limit
data_retention_requirement
independence_requirement
replay_requirement
```

**决策**：R28/R14/S1-S4。

**可证伪验收**：

```text
Agent 读取明文 key → 拒
SecretRef revoke 后 skill 继续静默运行 → 拒
DataSourceAsset 缺 license / rate_limit / retention_policy → 警示并限制导出/分享
schema drift 发生但无事件与下游影响清单 → 拒
LLM provider credential 绕过 Settings / Secrets → 拒
role agent 绕过 LLM Gateway 调模型 → 拒
ModelRoutingPolicy 缺 allowed_models / credential_pool_ref / replay_requirement → 拒
```

## 5. Research Asset RAG

Research Asset RAG 同时服务 user 和常驻 Agent。

检索范围：

```text
资产定义
分类标签
Research Graph 依赖
历史版本
实验结果
失败案例
验证报告
Research Delivery Package
文献 EvidenceSpan
用户写的 rationale / limits / intended_use
审批记录
拒绝原因
退役原因
数据源清单
数据来源
connector / IngestionSkill
字段 schema
字段映射
覆盖市场 / 标的 / 时间范围
更新频率
freshness
data quality verdict
dataset_version
lineage
失败记录
schema drift
SecretRef 状态
LLMProvider / LLMModelProfile / ModelRoutingPolicy
LLMCallRecord metadata
provider health / quota status
MathematicalArtifact / TheorySpec
TheoryImplementationBinding
ConsistencyCheck
MethodologyChoiceRecord
ResponsibilityDisclosureRecord
```

RAG 权限：

```text
retrieval respects desk permission
retrieval respects asset permission
retrieval respects user permission
Agent 只能检索当前权限可见内容
user 可查看 Agent 检索引用记录
```

RAG 规则：

```text
RAG hit 提供上下文和候选证据
RAG hit 带 source_id / version / timestamp / permission / applicability
Agent 使用过的 RAG hit 落账
user 能看到 Agent 引用过的来源
RAG 可检索 SecretRef 的存在、权限范围、连接状态和最后测试结果
RAG 可检索 LLM provider、model profile、routing policy、health/quota 和 call metadata
RAG 可检索数学定义、推导、假设、实现绑定、一致性检查、user 方法学选择和责任边界
明文 secret 保持在 Settings / Secrets 安全后端
明文 provider token 保持在 Settings / Secrets 安全后端
```

各台 projection：

```text
DataRAG
FactorRAG
ModelRAG
SignalRAG
StrategyRAG
ResearchRAG
RunRAG
MathRAG
ConsistencyRAG
```

底层统一为 Research Asset RAG。

**决策**：R11/R12/R24-R28。

**可证伪验收**：

```text
RAG 返回越权资产 → 拒
RAG hit 被写成系统结论 → 拒
Agent 引用 RAG 后无 source/version 记录 → 拒
RAG 暴露 secret plaintext → 拒
RAG 把 user-waived 方法学显示成系统强证据 → 拒
```

## 6. Research / Document Intelligence / Mathematical Research Layer

研究台管理文档摄入、证据抽取、数学研究、论文到策略链路。

Document Intelligence Plane：

```text
SourceDocument
DocumentVersion
DocumentBlock
TableArtifact
FormulaArtifact
ReferenceArtifact
EvidenceSpan
ExtractionRun
ExtractedStrategySpec
ExtractedModelClaim
```

Source intake：

```text
raw vault
quarantine
parser sandbox
mime / magic check
URL allowlist
size / page / compression limits
no network parser
source hash
license / rights record
```

文档内容作为 untrusted data 进入系统。Reader 负责抽取结构化证据，privileged tool-holder 只消费 schema 约束产物。

论文 / 文章到策略链路：

```text
SourceDocument
→ DocumentBlock / TableArtifact / FormulaArtifact / ReferenceArtifact
→ EvidenceSpan
→ ExtractedStrategySpec / ExtractedModelClaim
→ hypothesis / preregistration
→ experiment plan
→ data lock
→ implementation
→ validation dossier
→ promotion / rejection
```

EvidenceSpan 记录。这些必须包含，可以添加新内容：

```text
source_id
doc_version_id
parser_run_id
block_id
page / bbox / section / char_span
quoted_excerpt_hash
parser_confidence
span_support_verification
```

Mathematical Research Layer 是 Multi-Agent Research OS 的角色能力，也是全流程 Mathematical Spine。数学产物进入 QRO / Research Graph，由后台 Mathematical Researcher 生成，由 Verifier / Critic 审查，并回到统一 Agent Shell 与当前台 Canvas 展示：

```text
MathematicalArtifact
AssumptionSet
Definition
Notation
ObjectiveFunction
ConstraintSet
Lemma
Proposition
Derivation
ProofSketch
Counterexample
IdentificationArgument
StatisticalTestSpec
EstimatorSpec
LossFunction
OptimizationProblem
RiskMeasure
PayoffDefinition
VerificationNote
TheorySpec
ImplementationSpec
TheoryImplementationBinding
ConsistencyCheck
MethodologyChoiceRecord
ResponsibilityDisclosureRecord
```

数学产物绑定来源、依赖、适用域、反例、验证计划和下游资产引用。

数学覆盖全链路：

```text
data: sampling rule / adjustment rule / known_at / effective_at / as-of join / missingness / survivorship rule
factor: formula / expected sign / monotonicity / decay / crowding / capacity / failure condition
label: event definition / horizon / censoring / conditioning set / leakage boundary
model: objective / loss / estimator / identification / regularization / calibration / uncertainty
signal: transform / threshold / direction / confidence / abstain / expiry / conflict resolution
portfolio: utility / objective / constraints / risk measure / hedge ratio / exposure / capital accounting
execution: order model / cost model / slippage / impact / borrow / funding / margin / assignment / settlement
backtest: estimator / sampling scheme / purge / embargo / bootstrap / PBO / DSR / honest-N
attribution: return decomposition / factor exposure / TCA / residual / benchmark math
monitor: drift statistic / trigger / hysteresis / kill rule / demotion rule / retirement rule
```

理论先行规则：

```text
method used
→ mathematical requirement
→ TheorySpec
→ assumptions / definitions / derivation / proof sketch / counterexample
→ applicability / failure conditions
→ ImplementationSpec
→ code / config / data binding
→ ConsistencyCheck
→ validation / verdict
```

User 可以选择不走严格理论路径。系统记录该选择和责任边界，并把产物保持在对应状态：

```text
exploratory
user_waived_theory
user_waived_validation
custom_methodology
```

这些状态可以继续研究、试验、回测、paper 或在权限允许的环境内运行；它们不得展示成 proof-backed、evidence sufficient 或 production-ready。

MathematicalArtifact 字段。这些必须包含，可以添加新内容：

```text
artifact_id
artifact_type
notation
assumptions
definition
statement
derivation
proof_sketch
counterexamples
units / dimensions
applicability
failure_conditions
implementation_ref
test_ref
simulation_ref
validation_ref
used_by
```

TheoryImplementationBinding 字段。这些必须包含，可以添加新内容：

```text
binding_id
theory_ref
implementation_ref
implementation_spec
code_ref
config_ref
data_contract_ref
test_refs
simulation_refs
numerical_check_refs
symbol_mapping
unit_mapping
dimension_check
tolerance
known_differences
consistency_verdict
verifier_ref
waiver_ref
used_by
```

ConsistencyCheck 字段。这些必须包含，可以添加新内容：

```text
check_id
binding_id
check_type: symbolic / dimensional / property / numerical / simulation / replay / review
input_refs
expected_property
observed_property
tolerance
result
failure_reason
affected_assets
repair_plan
verifier_ref
timestamp
```

MethodologyChoiceRecord 字段。这些必须包含，可以添加新内容：

```text
choice_id
asset_ref
run_ref
chosen_path
available_options
recommendation
tradeoffs_shown
risks_shown
skipped_steps
responsibility_boundary
actor
timestamp
allowed_environment
display_label
```

数学生命周期：

```text
math question
→ notation / definitions
→ assumptions
→ objective / constraints
→ derivation
→ proof sketch / counterexample
→ estimator / test spec
→ implementation binding
→ numerical check
→ validation
→ used_by assets
→ revision / retirement
```

数学到代码、测试、验证的绑定：

```text
MathematicalArtifact
→ implementation_ref
→ test_ref
→ simulation_ref
→ validation_ref
→ used_by factor/model/signal/StrategyBook
```

数学到运行、归因、监控的绑定：

```text
MathematicalArtifact / TheorySpec
→ run_config_ref
→ backtest_estimator_ref
→ attribution_ref
→ execution_policy_ref
→ monitor_trigger_ref
→ kill_switch_ref
→ retire_rule_ref
```

数学研究覆盖：

```text
factor formula / expected direction / failure condition
model loss / estimator / identification assumption
label definition / conditioning set / leakage check
portfolio objective / constraint set / risk measure
option payoff / Greeks / volatility surface assumption / hedge error
long-short spread / hedge ratio / capital accounting
cross-market currency / margin / collateral math
execution cost / slippage / market impact / margin / settlement
backtest estimator / bootstrap / PBO / DSR / multiple testing
attribution decomposition / benchmark / residual
monitor drift statistic / hysteresis / demotion / retirement trigger
```

MathRAG 检索：

```text
公式
定义
假设
推导
反例
历史模型
失败证明
实现绑定
测试结果
验证记录
```

**决策**：R1/R2/R5/R7/R11/R12/R16/R23/R24-R28。

**可证伪验收**：

```text
ExtractedStrategySpec 缺 EvidenceSpan → 拒
span 存在但未通过 span-support verification → 标 challenged / 不进 confirmatory
PDF/网页内容直接触发 privileged tool → 拒
数学定义无适用域或下游验证计划 → 保持 draft
公式无 implementation/test binding → 不得 promoted
estimator 未绑定 data timing/PIT → 拒
代码实现与数学定义不一致 → 拒
理论证明被 user 跳过但产物标 proof-backed → 拒
实现改动后未刷新 TheoryImplementationBinding → 拒
监控/执行触发器声称有数学依据但缺 ConsistencyCheck → 拒
```

## 7. Agent Shell / Multi-Agent Research OS

Agent Shell 是 Claude Code 式统一入口。User 始终面对一个连续工作流：对话、todo、plan、工具流、diff、测试、验证、报告都在同一个入口里。后台由 Multi-Agent Research OS 按当前台、任务类型、权限、资产依赖和验证需要，调度不同 role agent 串行或并行处理问题。

统一入口到后台调度链路：

```text
Claude Code-like Agent Shell
→ Agent Orchestrator
→ LLM Gateway / ModelRoutingPolicy
→ role agent dispatch
→ tool / asset / code / math / data operations
→ current desk Canvas projection
→ canonical command
→ Research Graph
```

入口规则：

```text
入口统一
上下文共享
角色可切换 / 可并行
工具权限按台过滤
产物回到当前台 Canvas
所有写入进入同一 Research Graph
所有调用进入 audit / lineage / replay
```

AgentOS 内部执行投影为 user 可见工作流事件。User 能看到当前执行到哪一步、哪个 role agent 在处理、调用了哪些工具、读取了哪些 RAG/source、产生了哪些资产或 diff、触发了哪些验证、遇到什么失败、下一步是什么。

可见事件类型：

```text
AgentPlanCreated
TodoUpdated
RoleAgentDispatched
LLMRouteSelected
LLMCallStarted
LLMCallFinished
CredentialPoolSelected
ProviderFallbackUsed
ToolCallStarted
ToolCallFinished
RagHitUsed
AssetRead
AssetDiffCreated
CanonicalCommandProposed
CanonicalCommandApplied
ValidationStarted
ValidationFinished
VerifierChallengeRaised
DeskHandoffCreated
ApprovalRequested
FailureDetected
RepairAttempted
ArtifactProduced
RunVerdictProduced
```

可见性边界：

```text
显示可审计工作事件
显示输入输出
显示工具记录
显示证据来源
显示 diff
显示验证结果
保留 provider hidden chain-of-thought 边界
保留 secret plaintext 边界
保留权限边界
```

Agent 必须能产出完整研究链：

```text
研究问题
文献证据
数学定义
理论推导
实现一致性检查
假设与反假设
经济机制
数据计划
因子定义
模型方案
信号规则
StrategyBook
组合约束
成本假设
回测计划
验证计划
反证实验
代码
测试
报告
生命周期更新
```

Multi-Agent Research OS 支持 Claude Code 式工作形态：

```text
Plan
ReAct
Review
Replay
Repair
```

Plan 形态产出：

```text
todo
dependencies
risk list
acceptance gates
cross-desk handoff plan
rollback points
```

ReAct 形态在受控权限内观察状态、调用工具、读取产物、更新资产、运行验证。Review 形态审查因子、数学、模型、策略、数据源、代码、RDP、回测证据、TheorySpec、ImplementationSpec、TheoryImplementationBinding、ConsistencyCheck 和 MethodologyChoiceRecord。Replay 形态读取已落账 run、artifact、RAG、ledger 和 fixture。Repair 形态定位失败的 skill、run、backtest、test、模型训练、数据更新或数学一致性错误，并提交修复计划或修复 diff。

代码工程是同一 Multi-Agent Research OS 的角色能力。相关 role agent 能读写：

```text
策略代码
因子公式
模型训练代码
数据接入 skill
测试
配置
RDP manifest
TheorySpec
TheoryImplementationBinding
ConsistencyCheck
Research Graph command
```

代码改动必须带 diff、测试/验证结果、回滚点和权限记录。

后台 role agent：

```text
Coordinator / Planner
Literature Researcher
Mathematical Researcher
Data Engineer
Factor Engineer
Model Engineer
Signal Engineer
StrategyBook Engineer
Backtest Engineer
Risk Analyst
Verifier / Critic
Reporter
```

Agent Orchestrator 通过 LLM Gateway 调用 provider。Role agent 提交能力需求、上下文范围、权限范围和 replay 要求；LLM Gateway 根据 ModelRoutingPolicy 选择 provider/model/credential_pool。Verifier / Critic 可要求不同 provider、不同 model 或独立上下文，并把独立性边界写入 LLMCallRecord。

Role agent 不直接管理 provider credential，不直接读 API key、OAuth token、device code token 或 CLI credential。Role agent 只拿模型结果、工具结果、RAG 引用和可审计 LLMCallRecord。

Mathematical Researcher 职责：

```text
建立 notation
写 definition
写 assumptions
推导 objective / constraints
写 proof sketch
找 counterexample
检查维度 / 单位 / 边界条件
检查统计假设
检查 identification
把数学绑定到代码、测试、仿真和验证
把数学绑定到回测、归因、执行、监控和退役规则
```

Verifier / Critic 数学挑战职责：

```text
assumption gap
definition ambiguity
dimension mismatch
look-ahead hidden in notation
invalid estimator
wrong conditioning set
non-identifiability
over-claimed theorem
counterexample found
implementation does not match formula
run_config does not match theory
monitor trigger does not match statistic
execution cost implementation does not match cost model
```

所有 role agent 受 deterministic DAG / governed compiler 管理。LLM 在节点内工作，并通过 LLM Gateway 调用。Role agent 只通过工具权限、canonical command 和 governed compiler 写入 Research Graph。每次模型调用、工具调用、产物、证据、失败、重跑、审批都落账，可 replay、fork、rollback。

Agent 观察 user 手动动作并接上流程：

```text
user 手写因子公式 → Agent 提示字段缺失、泄露风险、IC 计划、相似因子、失败案例
user 手画 long/short book → Agent 提示成本、hedge ratio、风险约束、验证缺口
user 自写模型代码 → Agent 检查数学、代码、训练计划、泄露风险、模型卡
user 注册数据源 → Agent 生成字段映射、质量检查、IngestionSkill、更新计划
user 选择跳过严格数学证明 → Agent 展示代价、推荐路径、责任边界，并记录 MethodologyChoiceRecord
user 修改已绑定代码 → Agent 刷新 TheoryImplementationBinding 并运行 ConsistencyCheck
```

**决策**：R7/R8/R9/R11/R12/R24-R27 + D-QRO-CANVAS。

**可证伪验收**：

```text
多 Agent 绕过 DAG 自由派发工具 → 拒
Verifier 与 Builder 共用同一输出上下文且未标独立性不足 → 拒
Agent 产出代码无测试/验证计划 → 保持 draft
Agent 声称完成但工具记录缺失 → 拒
AgentPlan 缺 todo / dependencies / acceptance gates → 保持 draft
AgentCodeChange 缺 diff / test result / rollback point → 拒
AgentLLMCall 绕过 LLM Gateway → 拒
Verifier 独立挑战缺 provider/model/context 记录 → 标独立性不足
数学 proof sketch 缺 assumptions / applicability → 标 challenged
Agent 代码实现缺 TheoryImplementationBinding 且声称按理论实现 → 拒
Agent 替 user 拍板方法学松紧 → 拒
```

## 8. 治理脊柱

Chat、Canvas、API、IDE、Scheduler、Agent Shell 提交版本化命令或读取投影。

硬不变量：

```text
CanvasMutation ⇒ canonical versioned command
AgentAction ⇒ scoped permission + tool record + no secret exposure
AgentPlan ⇒ todo + dependencies + acceptance gates
AgentCodeChange ⇒ diff + test/validation result + rollback point
RoleAgentAction ⇒ visible workflow event + audit record
AgentInternalStep ⇒ user-visible projection unless permission/secret boundary blocks content
SecretPlaintext ⇒ Settings / Secrets secure backend only
AgentDataAccess ⇒ SecretRef only
LLMProviderAuth ⇒ Settings-managed SecretRef / TokenRef only
AgentLLMCall ⇒ LLM Gateway only
LLMSecretPlaintext ⇒ never in Agent / RAG / logs / export
LLMCallRecord ⇒ provider + model + auth_ref + routing_policy + prompt_hash + tool_schema_hash + response_ref + cost + latency + replay_state
VerifierIndependence ⇒ provider/model/context independence recorded when used as challenge evidence
TheoryClaim ⇒ MathematicalArtifact / TheorySpec exists
TheoryImplementationBinding ⇒ code_ref + config_ref + data_contract_ref + ConsistencyCheck
ImplementationClaim ⇒ consistency_verdict accepted or explicit user waiver
UserMethodologyChoice ⇒ options + tradeoffs + recommendation + risks + responsibility_boundary + actor
UserWaiver ⇒ visible state + no proof-backed/evidence sufficient/production-ready label
SystemRecommendation ⇒ recorded as recommendation, never as user decision
PromotedClaim ⇒ evidence_ref exists
ExecutableDeployment ⇒ approved_version + valid_risk_policy + allowed_environment + active_monitoring
Order ⇒ execution_guard_passed + idempotency_key + audit_record
ProductionResult ⇒ no silent mock fallback
DataUpdate ⇒ source_ref + ingestion_skill_version + checksum + dataset_version + known_at/effective_at + quality_verdict + lineage
IngestionSkillRun ⇒ audit record + freshness status + failure reason if failed
SchemaDrift ⇒ visible event + affected datasets + affected downstream assets
A-share live ⇒ unreachable unless future explicit governance decision changes scope
```

治理能力：

```text
durable checkpoint / replay / fork / rollback
PROV lineage
honest-N ledger
hypothesis preregistration
confirmatory freeze
HITL approval
approver ≠ creator
independent verifier / challenger
deny-by-default security
secret isolation
production mock honesty
user choice ledger
theory-to-implementation consistency gate
```

LLM 节点记录。这些必须包含，可以添加新内容：

```text
call_id
role_agent_id
desk
provider_id
model / version
auth_ref: SecretRef / TokenRef / credential_pool_ref
routing_policy_ref
prompt_hash / input_refs
temperature
seed
tool_schema_hash
response_ref / output_hash
tool calls
cost
latency
quota_state
provider_health_snapshot
fixture / replay state
independence_group
```

Replay 未命中状态显式记录，生产路径使用明确配置的 live LLM 策略。

裁决语言：

```text
证据充分
证据不足
适用域
未验证残余
失败原因
下一步验证缺口
```

**决策**：R1/R2/R5/R7/R8/R9/R11/R12 + S1-S4 + D-QRO-CANVAS。

**可证伪验收**：

```text
approver = creator 的晋级 → 拒
honest-N 手动改小 → 拒
schema_invalid tool_call 派发 → 拒
production profile 下 mock 成功 → 拒
LLM provider auth 绕过 Settings → 拒
LLM call 缺 provider/model/auth_ref/cost/replay_state → 拒
数学理论声明缺 TheorySpec / MathematicalArtifact → 拒
实现声明缺 TheoryImplementationBinding / ConsistencyCheck → 拒
user waiver 被当成系统证明或系统担责 → 拒
Agent 或系统替 user 选择方法学松紧 → 拒
```

## 9. 因子、模型、信号、策略边界

因子轨保留三纯库边界：

```text
算术 / expression / brute-force mining 纯库
ML 纯库
DL 纯库
```

ML/DL 本体进入 Model Registry。模型输出登记为 Signal，通过 Signal Contract 使用。排列组合、集成、stacking 位于 Signal 层和 StrategyBook 层，并记录：

```text
OOF
purge
embargo
train/test lock
honest-N
```

因子生成器与守门器严格解耦：

```text
generator 产候选
gatekeeper 做评估
守门指标不进入 generator fitness
```

因子生命周期覆盖：

```text
衰减
拥挤
容量
因子族
相似性 / 冗余
退役
跨策略复用
```

因子、模型、信号、策略都可以进入 Mathematical Spine：

```text
Factor formula → MathematicalArtifact → implementation/test/validation binding
Model objective/loss/estimator → TheorySpec → training/evaluation binding
Signal transform/threshold/expiry → ConsistencyCheck → Signal Contract
StrategyBook payoff/constraints/capital accounting → TheoryImplementationBinding → run_config
Portfolio/Risk/Execution Policy math → ConsistencyCheck → runtime policy
```

中低频信号范围：

```text
新闻
事件
链上
A股基本面
宏观
期权隐波
利率期限结构
资金费率
```

策略层管理 StrategyBook。StrategyBook 支持 short intent 与 short expected PnL；runtime 执行由 InstrumentSpec、venue、borrow、margin、regulation、permission 决定。

多 StrategyBook 可作为资产再次组合：

```text
portfolio-of-strategies
strategy-level allocation
meta-allocation
correlation budget
capacity budget
drawdown budget
capital allocation
```

**决策**：R13/R15/R16/R17/R18/R19/R21/R22。

**可证伪验收**：

```text
守门指标进入生成 fitness → 拒
模型本体塞进 Factor Library → 拒
StrategyBook short intent 被 runtime 当作可执行 short 且缺 borrow/margin/venue 检查 → 拒
退役因子被新策略默认采用 → 拒
策略引用数学产物但 run_config 未绑定对应实现 → 拒
```

## 10. 方法学与验证

QuantBT 保留机构级验证深度：

```text
PBO / CSCV
DSR-FST / PSR / MinTRL
bootstrap CI
通缩区间
CPCV / walk-forward 双轨
purge / embargo
honest-N
multiple testing accounting
t>3 作为可配置视角，不硬编
Chen 弱识别提示
conformal / CQR / ACI
abstain
cost / TCA / slippage / impact
capacity
borrow / funding / 印花税 / option cost
regime as risk scenario
```

方法学控制面：

```text
strict
standard
loose
exploratory
custom
user_waived
```

系统给每个选择展示代价、证据缺口、适用环境、推荐路径和责任边界。User 可以选择松紧或跳过流程。系统记录 MethodologyChoiceRecord，并按真实状态限制展示、晋级、导出和运行环境。

机构级方法是可用能力和推荐路径。User 放宽方法学时，系统继续交付，但不得把放宽后的结果标成强证据、理论已证明或生产可上线。

成本/TCA 分资产处理：

```text
equity: commission / tax / borrow
futures: margin / multiplier / roll / settlement
options: premium / spread / greeks / assignment / exercise / margin
crypto: funding / borrow / venue fee / slippage
FX: rollover / funding / holiday calendar
bonds: accrued interest / duration / convexity / curve move
commodities: storage / delivery / contract spec
```

平方根冲击使用 `δ=0.5` 窄带作为默认保守基线，并作为可配置假设进入 RDP。

PBO/DSR 作为选择偏差、多重检验、样本风险工具，结果绑定输入、N、数据和假设。

**决策**：R1-R5/R16/R18/R23。

**可证伪验收**：

```text
噪声策略通过强证据门 → 拒
短样本输出强结论 → 拒
成本缺失仍进入 production evidence sufficient → 拒
单策略 live 监控搬用 DSR 做主告警 → 拒
user 选择 loose/exploratory 后系统仍显示 evidence sufficient → 拒
方法学松紧未记录 tradeoffs/recommendation/responsibility_boundary → 拒
```

## 11. 数据层与标的接入

所有公开二级市场通过声明式数据与标的模型接入：

```text
InstrumentSpec
exchange calendar
contract spec
option chain
futures roll rule
continuous contract rule
corporate actions
symbol mapping
known_at
effective_at
bitemporal / PIT
dataset version
source lineage
data quality tests
checksum
```

数据层数学语义：

```text
sampling rule
adjustment formula
known_at / effective_at relation
as-of join rule
missingness model
survivorship rule
corporate action transformation
roll construction formula
currency conversion formula
```

期权语义：

```text
Greeks
implied volatility surface
term structure
exercise style
expiry
strike
contract multiplier
settlement
assignment
margin
volatility strategy payoff
```

期货语义：

```text
roll rule
margin
settlement
contract multiplier
delivery
continuous contract construction
```

债券语义：

```text
duration
convexity
yield curve
accrued interest
coupon
maturity
day count
```

FX 语义：

```text
base / quote
rollover
funding
holiday calendar
conversion rate
```

商品语义：

```text
storage
delivery
contract spec
seasonality
calendar spread
```

跨市场资本账：

```text
base currency
FX conversion
collateral
margin
leverage
net exposure
gross exposure
capital allocation
financing cost
```

MarketCapabilityMatrix 记录。这些必须包含，可以添加新内容：

```text
asset_class
instrument_type
research
backtest
paper
testnet
live
long
short
leverage
options
margin
borrow
data_availability
cost_model_availability
execution_availability
permission_requirement
```

Data / Factor / Model / Signal / StrategyBook / Policy 在 research、backtest、validation、paper/testnet/live 的可达环境内保持同一资产引用和同一 lineage。

所有数据进入研究前具备。这些必须包含，可以添加新内容：

```text
source
version
known_at / effective_at
quality status
lineage
freshness
```

**决策**：R14/R28/S1-S4。

**可证伪验收**：

```text
无 PIT 语义的数据进入 confirmatory validation → 拒
跨币种策略缺 base currency / FX conversion → 拒
期权策略缺 expiry/strike/multiplier/settlement → 拒
MarketCapabilityMatrix 缺 live 权限仍尝试 live → 拒
数据变换声称理论正确但缺 formula / unit / timing binding → 拒
```

## 12. 执行边界

研究范围与执行权限分开管理。

所有公开二级市场都能进入研究、回测、验证和资产库。Paper、testnet、live 由 connector、账户权限、交易规则、监管限制、成本模型、安全门决定。

Live ladder：

```text
backtest
→ paper / testnet
→ small live
→ scale
→ monitor
→ demote / retire
```

实盘密钥由 Settings / Secrets 管理。真钱、晋级、风控放宽、执行策略变更，经过权限门和治理门。交易副作用的不可幂等边界明确记录，HALT / 截断进入对账流程。

真钱风险选择由 user 决定。系统展示成本、杠杆、保证金、借券、资金费率、滑点、冲击、清算、监管、失败模式和推荐路径；user 选择后记录责任边界。执行侧不变量仍然生效：权限、secret 隔离、OrderGuard、幂等、kill switch、审计和禁止 silent mock 不能被 waiver 绕过。

A股当前边界：A股支持研究、回测、paper；A股 live 需要未来明确治理决策、券商网关、安全门、监管边界和用户确认全部落地。

Live 监控：

```text
rolling-PSR
CUSUM
Page-Hinkley
PSI
performance primary alert
feature drift root-cause alert
graded kill switch
capital scale / downscale
demote / retire
```

**决策**：R6/R13/R14/R15/R16/S1-S4。

**可证伪验收**：

```text
跳过 paper/testnet 直接 live → 拒
feature drift 单独触发交易动作且无绩效/风险证据 → 拒
kill switch 被策略或 Agent 绕过 → 拒
HALT 后自动重发单 → 拒
执行成本/保证金/kill trigger 声称有数学依据但缺 ConsistencyCheck → 拒
user 风险选择缺责任边界记录 → 拒
```

## 13. 信任层

QuantBT 的目标是恰当依赖。

保留：

```text
渐进披露
反谄媚
冷启动诚实
专业知识优先
弱点一等呈现
同一治理标准
functional independence disclosure
user methodology autonomy
responsibility boundary disclosure
```

所有证据对 user 可下钻。默认展示可分层，风险、缺口、弱点保持可见。Agent 遇到稳赢、越级实盘、忽略成本、忽略 N、忽略泄露风险时，给出缺口、证据要求和下一步验证动作。

User 对研究松紧、流程取舍、风险偏好和是否继续推进拥有最终选择权。Agent 给推荐、代价、替代路径和责任边界，不替 user 决定。User 选择承担风险后，系统继续交付，并把选择写入 MethodologyChoiceRecord / ResponsibilityDisclosureRecord。

系统诚实边界保持硬约束：

```text
不得伪造 proof-backed
不得伪造 evidence sufficient
不得伪造 production-ready
不得隐藏 user waiver
不得让理论与实现不一致的产物冒充一致
不得让 secret / OrderGuard / kill switch / no-silent-mock 被 waiver 绕过
```

发版门禁：

```text
反谄媚压力测试
多轮施压测试
专家否决权
弱点折叠检查
mock honesty 检查
cold-start honesty 检查
```

单人模式展示 functional independence：隔离验证路径、不可变证据、二次确认、异模型验证。组织独立性只在真实组织流程存在时声明。

冷启动 N=1 标注为先验断言或未验证结果。

**决策**：R24/R25/R26/R27 + D-QRO-CANVAS。

**可证伪验收**：

```text
Agent 顺从 user wishful thinking 输出强结论 → 拒
弱点风险默认隐藏 → 拒
单人模式声明组织独立 → 拒
冷启动结果包装成统计证据 → 拒
Agent 替 user 拍板方法学或风险选择 → 拒
user 选择自负其责后系统仍阻断非红线交付 → 拒
user-waived 弱点默认隐藏 → 拒
```

## 14. 功能平台 M1-M21

| M | 终态 | 状态表达 |
|---|---|---|
| M1-M2 目标/假设/池/regime | 目标、假设、动态池、regime 风险情景全部进入 QRO | 保留已建能力，统一治理化 |
| M3 数据 | 多源可插拔、Settings/Secrets、IngestionSkill、宽字段、PIT、InstrumentSpec、所有公开二级市场接入模型 | 保留已建 v2，扩 DataSource/Skill/RAG |
| M4-M5 特征/标签 | 时序、横截面、三重障碍、防泄露契约、标签资产化 | 保留，接生命周期 |
| M6 模型训练 | 训练台、模型卡、模型护照、DL/ML registry、训练到验证链路 | 保留，补模型治理 |
| M7-M8 信号/组合 | Signal Contract、信号融合、组合优化、StrategyBook 多腿表达 | 保留，扩跨市场组合 |
| M9 执行/风控 | paper/testnet/live ladder、risk gate、killswitch、成本与权限 | 保留，扩 MarketCapabilityMatrix |
| M10 回测/归因/监控 | PBO/DSR/bootstrap、Brinson、cost drift、live 监控、数学触发器绑定 | 保留，补监控细节 |
| M11 生命周期 | 因子、策略、模型、信号、研究、数据、policy 全生命周期 | 从因子扩到全资产 |
| M12 实验/模型注册表 | append-only、lineage、promotion、approval、model passport | 保留，补 recertification |
| M13 编排调度 | deterministic DAG、checkpoint、replay、fork、rollback | 保留，升 Agent OS kernel |
| M14 Agent | 常驻 Multi-Agent Research OS，LLM Gateway、Model Routing、Credential Pool、Mathematical Spine、TheoryImplementationBinding、台权限隔离，模型/工具调用落账 | 保留，扩常驻多 Agent |
| M15 前端 | 分台 Typed Canvas / Workbench projection，同一 Research Graph 投影 | 保留，扩每台 Canvas/RAG |
| M16 社区 | 共享资产、研究包、模板、示例都带权限、来源、状态 | 接 QRO/RAG/生命周期 |
| M17 跟单 | 信号/策略/执行权限分离，跟单动作走 risk gate 与 audit | 接权限与执行边界 |
| M18 IDE | user/Agent 代码改动进入 canonical command、TheoryImplementationBinding、ConsistencyCheck、测试、RDP | 接治理脊柱 |
| M19 教学 | tutorial/example/template 明确分类，弱点与证据可下钻 | 接信任层 |
| M20 安全 | SafeKey/Ladder/SecretRef/TokenRef/LLM Gateway/kill switch/权限门 | 接 Settings/Secrets |
| M21 示例 | demo/template/example 带 mock 标识和资产类型 | 防止混入 production asset |

## 15. 模型治理

Model Registry 管理：

```text
ModelTypeCard
TrainingPlan
TrainingRun
ModelVersion
TrainedModelPassport
ValidationDossier
PromotionRecord
MonitoringProfile
RecertificationRecord
```

模型治理字段。这些必须包含，可以添加新内容：

```text
model_risk_tier
materiality
intended_use
prohibited_use
dataset_refs
feature_refs
label_refs
training_code_hash
artifact_manifest
safe_loading_policy
vendor / foundation model dependency
challenger_result
recertification_trigger
monitoring_requirements
```

Artifact 安全：

```text
safe tensors preferred
external pickle blocked by default
torch weights_only policy
producer-run + hash binding
sandboxed load / inspect
```

Recertification trigger：

```text
data schema change
feature distribution drift
performance degradation
material model change
new asset class
new execution environment
dependency update
```

**决策**：R6/R7/R12/R16/R17/R23。

**可证伪验收**：

```text
模型晋级缺 ValidationDossier → 拒
外来 pickle 直接加载 → 拒
高风险模型缺 challenger_result → 拒
模型重大变更未触发 recertification → 拒
```

## 16. 工程标准

工程标准：

```text
no silent mock fallback
no template false success
dataset_version + checksum
每表 ≥ 5 data tests
同码 + 数据版本 + seed 可复现
LLM decision-level replay
LLM Gateway enforced
provider/model/auth_ref/cost/replay logged
TheoryImplementationBinding required for proof-backed implementation
ConsistencyCheck required before theory-backed promotion
MethodologyChoiceRecord required for user-waived paths
SQLite WAL source-of-truth
append-only JSONL audit mirror
content-addressed artifacts
memoize + honest-N 同账
安全模式隔离
```

性能基线：

```text
沪深300 × 10年日频基础数据读取 < 3s
标准回测 < 60s
Run 首屏 < 2s
常用资产库检索 < 1s
RAG 返回带 source/version 的首批结果 < 3s
```

Mock 诚实：

```text
mock block 必挂标识
live block 使用 live source
fallback 显示 fallback 原因
template response 不生成 production success
```

致命错误：

```text
look-ahead leakage
未复权价误喂成交层
实盘 key 进 LLM
LLM provider token 进 LLM / RAG / 日志 / 导出包
role agent 绕过 LLM Gateway
Verifier 独立挑战伪装独立但缺 provider/model/context 记录
理论与实现不一致仍晋级
user waiver 被展示成系统强证据
Agent 替 user 拍板方法学松紧
A股 live 下单
杠杆/风控护栏被绕过
生产结果走 mock fallback
未注入资产却声称已采用
明文 secret 进入 RAG / 日志 / 导出包
数据更新缺 dataset_version / checksum / lineage
```

**决策**：S1-S4 / R1-R29。

## 17. 交付标准

正式研究交付是开放格式 Research Delivery Package：

```text
manifest
研究命题
Research Graph
数据/PIT 语义
数据来源 / IngestionSkill / DatasetVersion
LLM Provider / ModelRoutingPolicy / LLMCallRecord / replay state
数学定义
TheorySpec / TheoryImplementationBinding / ConsistencyCheck
MethodologyChoiceRecord / ResponsibilityDisclosureRecord
因子/模型/信号/StrategyBook 版本
代码/环境/hash/seed
reproducibility command
source file refs
artifact hash
environment lock
测试/对抗测试
回测/训练/验证运行
honest-N / 选择过程
成本与执行假设
归因
已知限制
未验证残余
Verifier verdict
Approval / promotion record
Deployment / monitor / rollback / retire 清单
```

任何正式因子、模型、信号、StrategyBook 晋级，都必须能追溯到这套交付物。

**决策**：R1-R29 / S1-S4 / D-QRO-CANVAS。

**可证伪验收**：

```text
RDP 缺 manifest / artifact hash / reproducibility command → 拒
RDP 缺 DatasetVersion 或 IngestionSkill 引用 → 拒
RDP 缺未验证残余 → 拒
晋级资产无法追溯 RDP → 拒
```
