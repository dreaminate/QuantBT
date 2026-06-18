# 论文/文章到策略抽取 + DL/ML 模型管理系统

日期：2026-06-15  
范围：把用户上传的论文、研报、博客、网页、代码仓库说明、模型论文与各种策略材料，纳入 QuantBT Agent OS 的机构级研究-训练-验证-晋升链路。  
研究输入：本轮综合 8 个并行/补充 agent 的只读研究结论，覆盖文档解析、策略抽取、DL/ML 模型管理、模型目录、lineage、工程落地、安全合规、非技术用户信任界面；并对照当前仓库代码、既有 Claude 研究包、Codex Agent OS 技术架构稿和外部前沿资料。

---

> ## 🔒 Claude 审查裁定（2026-06-15）—— 与下方原文冲突时以此为准
>
> 本稿经 Claude 独立审查（9 agent，对源码逐条核实，详见 [07-codex04-conflict-ledger.md](07-codex04-conflict-ledger.md) 同源方法）。**总评：四份稿里安全做得最对**——§0/§1.2/§8.3"不可信输入不驱动 privileged tool"、§8.2 ToolPolicyProxy side-effect 分级、§2.3 SSRF/zip-slip/magic-mismatch 防护、§12 P0 安全测试第一阶（可作其它稿的回写模板）、新模型默认 `runnable:false`、SR 26-2 锚点——**这些勿误伤、保留**。
>
> **🔴 #1 critical（P0 必修，已 shipped 违规）**：`models/lib.py:59` 裸 `pickle.load`、`lib.py:96` `torch.load(..., weights_only=False)`、`training.py:245` `pickle.dump`——**违反本稿 §5.5 自己定的红线**，加载用户上传/论文附带的 `.pt`/`.pkl` = **任意代码执行**。§12 把 artifact safe-load 排到 P3 是错排：**提到 P0，与 ToolPolicyProxy 同批**（外来 `.pt` 强制 `weights_only=True`/转 SafeTensors、外来 `.pkl/.joblib` 默认 blocked、自产 pickle 限 producer-run+hash+sandbox）。
>
> **三簇高危缺口（全部代码核实 confirmed）**：
> 1. **治理脊柱"记录-钉定-折算"三件套零接线**：extractor/model-intake 是 LLM 节点但只记 `extractor_model/prompt_hash`（§3.1），未继承全局 **LLMCallRecord 钉定**（不可变 model_version id 禁裸别名 + system_fingerprint + ReplayDiverged）；trial 入账只到 failed/cancelled 计数（§7.4），未接 **honest-N 双字段**（`n_trials_total` 审计 + `n_eff` 喂 DSR，否则论文链路=绕过 N_eff 的新 garden-of-forking-paths）；PBO/DSR 只当 checklist 词，未写 **D6(PBO≤0.05)/D7(DSR 删裸分,<显著性触发人审)/D5(FDR 辅助)** 的口径。
> 2. **排序与账本冲突（违 D1）**：gated promotion + Approval Inbox 排 P4，但 `store.py:232 promote()` 是裸 `v.stage=stage`——**提到 P0、复用全局 gated promote**（04 §8/02 P0），不在 05 独立实现；§5.4 的 10 段 stage 梯与 M12 `ModelStage`（4 段）未映射、passport/event/alias 须**归一到提升后的 `experiments/store`**，`research_ingest` 只持 SourceDocument→Extraction→EvidenceSpan 这类 M12 没有的维度，**不另起平行账本**。
> 3. **两条机构级硬缺口缺席**：① holdout **真隔离(D2)** 零接线（OOS 仅 `oos_fraction` 切日期，无加密落盘/`read_holdout`/`HoldoutRevealed` 揭盲）；② **DL 不确定性量化/conformal/abstain**（99 §12 机构级核心）与 **model-as-feature 因子族增量检验(FGX)** 两个暗道未点名。
>
> **其余 confirmed 缺口**（详见 07 同源审查报告，按 P0/P1 回写）：独立验证门 creator≠verifier + approver≠creator(D4)、模型 recertification(SR 26-2)、训练门强制 t1+CPCV/WF 双轨、TrainingRequest 携带 dataset_id/version/research_lineage、跨资产复制验证、risk_tier→验证深度 materiality 联动、compiler 锁死"不进假设卡不得 materialize"、暂缓层模型 leakage_hazards 结构化。
>
> **接线原则（统一治理生命周期）**：**05 不另造任何治理原语，全部复用全局节点**（假设卡→数据→因子/模型→独立验证→审批→上线→监控→退役）；`research_ingest` 只新增 05 特有的"来源/抽取"维度（SourceDocument/EvidenceSpan/ExtractedSpec）。实盘 agent 仅"提交警告+达规则停"(D3)；A股永不 live；gate 阈值/profile 按 `risk_tier` 个性化（硬闸不动）。

## 0. 总裁决

这条能力不能设计成“上传 PDF 后让 agent 帮你写代码跑一下”。

正确形态是新增一条贯穿 Agent OS 的研究来源与模型治理脊柱：

```text
SourceDocument
  -> DocumentBlock / TableArtifact / FormulaArtifact / ReferenceArtifact
  -> EvidenceSpan
  -> ExtractedStrategySpec / ExtractedModelClaim
  -> Human Clarification + PreRegistration
  -> ExperimentPlan
  -> DataLock + FeatureSpec + LabelSpec
  -> TrainingRun
  -> TrainedModelPassport / ModelVersion
  -> BacktestRun + ValidationDossier
  -> PaperRun
  -> LiveDeployment
  -> MonitoringSnapshot / DemotionDecision
```

核心原则：

- 文献、网页、研报、模型论文都是 **不可信输入**，不能直接触发工具调用、训练、代码执行、模型加载或晋升。
- LLM 只能把来源材料变成带证据跨度的结构化提案；执行必须经过 deterministic DAG、ToolPolicyProxy、HITL 和 gate。
- 每一个抽取字段都必须能回到 `source_sha256 + parser_run_id + block_id + page/bbox/section/char_span`。
- 新策略必须先成为可证伪假设；新模型必须先成为模型类型卡，默认 `runnable:false`。
- 已训练模型不是“一个文件”，而是 `ModelVersion + TrainedModelPassport + ArtifactManifest + ValidationDossier + ApprovalEvents + MonitoringProfile`。
- 对非技术用户，界面不能只展示后台日志；主界面必须始终回答四件事：现在在哪一步、证据够不够、还缺哪个判断、下一步会产生什么后果。

一句话：**文章不是代码生成燃料，文章是受治理的研究证据源；模型不是训练产物文件，模型是带护照、谱系、验证、用途边界和退役机制的受管资产。**

## 1. 仓库现状：已有主干与硬缺口

### 1.1 已有可复用主干

QuantBT 已经有很多零件，足以承载这条新脊柱。

| 领域 | 现有资产 | 证据 |
|---|---|---|
| 策略结构 | `StrategyGoal -> Universe -> Features -> Labels -> Model -> Signals -> Portfolio -> Execution -> Eval` | `docs/strategy-dev-guide.md` |
| 训练台 | `TrainingRequest`、`TrainingService`、`spec.json/result.json`、M12 run/model 登记、训练到回测桥 | `app/backend/app/training/service.py`, `app/backend/app/training/backtest_bridge.py` |
| 模型卡 | `docs/model_cards/*.md` 作为模型目录事实源；新模型默认 `runnable:false` | `docs/plans/v3-model-cards-decisions.md`, `app/backend/app/models/card_loader.py` |
| DL/ML 目录 | 线性、树模型、LSTM/GRU/ALSTM/TCN/Transformer/TFT/NBEATS/NHITS/DeepAR 等已注册 | `app/backend/app/models/training.py`, `app/backend/app/models/dl/architectures.py` |
| 数据质量 | `DatasetVersion`、GE-lite、freshness、file hash manifest | `app/backend/app/data_quality.py`, `app/backend/app/data_hash/dataset_hash.py` |
| 实验/模型注册 | JSONL append-only `Experiment`、`Run`、`ModelVersion`、`ModelRegistry` | `app/backend/app/experiments/store.py` |
| Agent 工具 | `agent_runtime.py` + `tool_schema.py` 可扩展工具 schema 和 dispatch | `app/backend/app/agent/agent_runtime.py`, `app/backend/app/agent/tool_schema.py` |
| UI 基础 | `/agent`、`/chat`、`/workshop`、`/training`、`/models`、RunDetail 风险/证据展示 | `app/frontend/src/pages/*` |

### 1.2 当前硬缺口

这些缺口会直接决定“论文到策略/模型”是否可信。

| 缺口 | 为什么严重 | 应对 |
|---|---|---|
| 无 `SourceDocument` / `DocumentBlock` / `EvidenceSpan` | 论文结论无法回到原文证据，后续策略和模型都失去来源可审计性 | 新增 Document Intelligence Plane |
| 无 `ExtractedStrategySpec` / `ExtractedModelClaim` | LLM 抽取只能停留在自然语言摘要，不能进入治理 DAG | 新增结构化抽取 contract |
| `StrategyGoal` 缺 `economic_mechanism / falsification_condition / stop_rule` | 不能把文献观点冻结成可证伪假设 | 抬升为 Hypothesis/PreRegistration |
| `TrainingRequest` 缺显式 `dataset_id / dataset_version / research_lineage` | 训练和回测可能默认到 demo/latest，破坏 reproducibility | 训练计划必须绑定 DataLock |
| `ModelRegistry.promote()` 是裸 stage flip | 模型可以绕过 gate 进入更高阶段 | 改为 gated promotion workflow |
| `Run.inputs` 是自由 dict | 训练来源、数据、特征、标签、代码、环境无法强约束 | 引入 `RunProvenance` |
| 模型 artifact 使用 pickle / `torch.load(weights_only=False)` | 外来模型可成为 RCE 面 | artifact 安全加载策略前移 |
| 文档解析/训练 runner 缺 hardened sandbox | 非可信 PDF/网页/论文内容可能触发 tool abuse、恶意解析或本地执行 | quarantine + parser sandbox + training sandbox |
| 前端缺 Research Reading Desk | 用户上传论文后没有证据高亮、claim card、HITL 判断点 | 新增 `/agent-os` 三联工作台 |

## 2. Document Intelligence Plane

### 2.1 不能把 PDF 当普通 RAG

QuantBT 里“研报阅读”的目标不是问答摘要，而是：

```text
用户上传 PDF/MD/网页/论文
  -> Agent 抽取可验证策略命题
  -> Agent 提议复现实验
  -> 人确认经济判断与研究边界
  -> 系统进入机构级策略生命周期
```

因此文档层必须比 RAG 更严格：

- 保留 raw source，不只存 chunks。
- parser 输出要可重跑、可 diff、可版本化。
- 表格、公式、图表、脚注、参考文献都要有独立 artifact。
- 每个下游 claim 必须引用 EvidenceSpan。
- 文档内容被视为不可信数据，不能成为 agent 指令。

### 2.2 获取与不可变 raw vault

新增 `ResearchSource`：

```text
source_id
kind: pdf | html | markdown | text | image | arxiv | doi | code_repo | dataset | model_artifact
uri
uploaded_by
retrieved_at_utc
declared_license
declared_rights
content_sha256
mime_magic
raw_artifact_path
source_headers_path
warc_path_optional
trust_state: quarantined | parsed | approved | rejected
```

网页建议保存 raw HTML + headers；需要严肃追溯时保存 WARC。WARC 是常用网页归档容器，适合保留抓取上下文。

### 2.3 Preflight + Quarantine

所有来源先进入 quarantine：

- 文件大小、页数、压缩层数、MIME magic、扩展名一致性检查。
- 拒绝加密/密码文档、宏、嵌入脚本、嵌入文件、路径穿越、压缩炸弹。
- URL 摄入只允许 HTTP(S) allowlist，禁止 localhost、私网、metadata IP、`file://`、重定向到非 allowlist。
- parser 进程禁网、限 CPU/RAM/运行时间、只读 raw vault、只写 job dir。
- 文档中的 prompt-like 指令只作为文本，不得传给 privileged agent。

现有 `app/backend/app/ide/sandbox.py` 可作为原型参考，但不能承担 hardened document/training sandbox 的安全边界。

### 2.4 Parser Cascade

解析应做级联而不是单 parser：

| 来源类型 | 推荐路径 | 说明 |
|---|---|---|
| arXiv/学术论文 | arXiv source/TeX 优先；PDF 走 GROBID | GROBID 面向科学出版物，把 PDF 重构为 XML/TEI |
| 普通研报/复杂 PDF | Docling 主解析；Marker/Unstructured 交叉校验 | Docling 支持表格、公式、阅读顺序、OCR 等 |
| 扫描件 | OCR + layout；保留 page bbox 和 OCR confidence | 不把 OCR 低置信字段直接转为 confirmed |
| 网页/博客 | Trafilatura/Readability + raw HTML/WARC | 抽正文同时保留原始上下文 |
| 表格 | Table artifact 单独落 CSV/Parquet/cell bbox | 跨页表格必须标注 parser confidence |
| 公式 | TeX source 优先；无 source 时用 OCR/VLM 候选 | 公式默认 candidate，需人工或 verifier 确认 |

外部参考：

- [GROBID](https://grobid.readthedocs.io/en/latest/Introduction/)：面向科学出版物的 PDF -> XML/TEI 结构化抽取。
- [Docling](https://www.docling.ai/)：把复杂文档转成结构化数据，支持表格、公式、阅读顺序、OCR。
- [Unstructured](https://docs.unstructured.io/open-source/core-functionality/partitioning)：文档 partitioning 与 OCR/layout 策略。
- [Nougat](https://github.com/facebookresearch/nougat)：学术 PDF 到 markup 的 OCR/视觉解析参考。

### 2.5 统一 Block Graph

parser 输出统一成 block graph，而不是纯文本 chunks。

```text
DocumentVersion:
  doc_id
  version_id
  raw_sha256
  parser_profile
  page_count
  manifest_hash

ExtractionRun:
  run_id
  doc_version_id
  parser
  parser_version
  model_hash
  started_at_utc
  status
  quality_summary

DocumentBlock:
  block_id
  type: title | paragraph | table | figure | formula | footnote | reference | code | appendix
  section_path
  page
  bbox
  text
  markdown
  html
  confidence
  source_ref

TableArtifact:
  table_id
  block_id
  csv_path
  parquet_path
  cells
  bbox
  confidence

FormulaArtifact:
  formula_id
  block_id
  latex
  image_ref
  page
  bbox
  confidence

ReferenceArtifact:
  ref_id
  title
  authors
  venue
  year
  doi
  url
  raw_text
```

EvidenceSpan 是所有下游抽取的最小证据单位：

```text
EvidenceSpan:
  evidence_id
  doc_id
  doc_version_id
  parser_run_id
  block_id
  page
  bbox
  char_start
  char_end
  quoted_excerpt_hash
  parser_confidence
```

## 3. 文章到策略：ExtractedStrategySpec

### 3.1 抽取结果不是摘要，而是可编译 contract

顶层对象：

```text
ExtractedStrategySpec:
  extraction_id
  source_doc_ids
  extractor_model
  prompt_hash
  tool_schema_hash
  created_at_utc
  fields:
    strategy_hypothesis
    data_requirements
    feature_specs
    label_specs
    model_specs
    signal_recipe
    portfolio_spec
    execution_cost_spec
    validation_plan
    falsification_plan
  missing_info
  conflicts
  hitl_questions
  compiler_status
```

每个字段必须是同一结构：

```text
FieldExtraction:
  value
  status: confirmed | inferred | ambiguous | unsupported | incompatible
  confidence
  evidence_ids
  assumptions
  default_source: source_text | quantbt_default | user_override | verifier_inference
  questions
```

状态含义：

- `confirmed`：原文明确写出，并能指向 EvidenceSpan。
- `inferred`：原文未直接写出，但可由上下文和 QuantBT 默认规则推断；必须标推理。
- `ambiguous`：有多个解释，不能编译为唯一实验。
- `unsupported`：LLM 想补但无证据；不能进入编译。
- `incompatible`：与 QuantBT 的资产、数据、执行或安全边界冲突；必须进入 HITL 或 block。

### 3.2 策略 contract 字段

| 字段 | 必需内容 | 进入 QuantBT 的落点 |
|---|---|---|
| `StrategyHypothesis` | 名称、资产类别、经济机制、alpha claim、适用市场、频率、持有期、benchmark、容量、可证伪条件、停止规则 | `StrategyGoal` + `PreRegistration` |
| `DataRequirement` | market、interval、universe、字段、derive policy、dataset version、PIT、known_at/as_of、survivorship policy | `field_catalog`, `DatasetRegistry`, `DataLock` |
| `FeatureSpec` | factor_id、公式、lookback、normalization、winsorize/fill、dataset binding、formula hash | `factor_factory` |
| `LabelSpec` | label_type、horizon、return_basis、benchmark、barrier 参数、`t0/t1`、leakage contract | `labels` |
| `ModelSpec` | task、model、feature_cols、label_col、CV、embargo、hyperparams、seed、artifact policy | `models/training.py`, `training/service.py` |
| `SignalRecipe` | score source、direction、threshold、long/short、confidence mapping、regime gating | `signals` |
| `PortfolioSpec` | optimizer、rebalance、constraints、exposure、capacity、covariance source | `portfolio` |
| `ExecutionCostSpec` | venue、order assumptions、commission、slippage、impact、funding/borrow、ADV/capacity | `execution` |
| `ValidationPlan` | data gate、IC/RankIC/decay、purged CV/walk-forward、PBO、DSR、bootstrap、trial ledger、stress | `eval` + `ValidationDossier` |
| `FalsificationPlan` | 失败阈值、反事实测试、成本敏感性、OOS degradation、IC decay、kill/retire rule | Agent OS gate |

### 3.3 HITL 问题优先级

Agent 不应一次问一堆“请确认所有字段”。HITL 只问会改变路径的问题。

优先级：

1. 改变回测语义的问题：市场、资产、universe、benchmark、频率、持有期、目标函数、是否允许 short/leverage、资金容量。
2. 造成泄露的问题：数据是否 point-in-time、`known_at/as_of`、幸存者偏差、label horizon、overlapping labels、是否有 `t1`。
3. 实现选择：论文公式是否能映射到现有算子、缺失字段如何派生、模型是规则还是 ML、参数搜索规模和 `n_trials`。
4. 上线边界：成本模型、撮合假设、滑点/冲击、funding/borrow、A 股是否只到 paper、crypto 是否允许 testnet/live、失败后 stop/retire。

## 4. 文章到模型：ExtractedModelClaim 与模型卡准入

### 4.1 模型论文不能直接变成 runnable

用户可能上传 DL/ML 论文或文章，例如 PatchTST、TimesFM、Chronos、TabNet、GAT、FinRL、某个自定义 alpha model。处理原则：

```text
论文/文章/README
  -> ExtractedModelClaim
  -> 映射到既有 ModelTypeCard 或新增模型卡草稿
  -> 默认 runnable:false
  -> 实现 gate
  -> CPU smoke / deterministic seed / OOS leakage test
  -> runnable:true
  -> TrainingRun
  -> ModelPassport
```

### 4.2 ExtractedModelClaim

```text
ExtractedModelClaim:
  model_name
  model_family: linear | tree | boosting | sequence_dl | forecasting_dl | foundation_ts | graph | rl | ensemble | custom
  task: regression | classification | ranking | forecasting | policy_learning
  architecture
  input_shape
  target
  loss
  training_split
  hyperparams
  datasets
  reported_metrics
  baselines
  compute_requirements
  code_availability
  license
  intended_use
  out_of_scope_use
  leakage_hazards
  evidence_ids
  status
```

### 4.3 模型目录分层

| 层 | 建议 |
|---|---|
| 基础线性层 | `ridge/lasso/elastic_net/sklearn_logreg` 已有；补显式 `linear_regression` 可作为 OLS/诊断基线 |
| 树/boosting 主力层 | `sklearn_rf/extra_trees/lgbm/xgboost/catboost` 是中低频量化默认主力 |
| 经典时序 DL | `lstm/gru/alstm/tcn/transformer/tft` 已注册，可作为 sequence 模型 |
| Forecasting/概率层 | `nbeats/nhits/deepar` 适合预测型任务，但要与 alpha ranking 区分 |
| 研究候选层 | `tabnet/patchtst/timesfm/chronos` 先加卡 `runnable:false` |
| 暂缓层 | GNN/GAT/StemGNN、RL/FinRL 默认 research sandbox；无 PIT 图边/邻接版本/环境治理前不能进生产候选 |

外部参考：

- [Qlib](https://github.com/microsoft/qlib)：AI-oriented quant platform 与 benchmark 参照。
- [NeuralForecast](https://nixtlaverse.nixtla.io/neuralforecast/docs/capabilities/overview.html)：现代时序模型目录参照。
- [PatchTST](https://huggingface.co/docs/transformers/en/model_doc/patchtst)：长上下文 patch 化时序候选。
- [TimesFM](https://github.com/google-research/timesfm)、[Chronos](https://github.com/amazon-science/chronos-forecasting)：time-series foundation model 只能先作为研究候选/zero-shot baseline。
- [FinRL](https://finrl.readthedocs.io/en/latest/index.html)：DRL 交易环境，不能混入 supervised model catalog 默认路径。

## 5. DL/ML 模型管理系统

### 5.1 两层对象

QuantBT 已经在 `docs/plans/v3-model-cards-decisions.md` 里定过两层对象，本研究确认它是正确方向，但需要补完治理字段。

```text
ModelTypeCard      静态算法卡：这个模型是什么，什么时候能用，什么时候不能用。
TrainedModelPassport 训练后护照：这一次训练出的 artifact 能不能被信任、能用于哪里。
```

### 5.2 ModelTypeCard 必补字段

`docs/model_cards/<key>.md` frontmatter 建议扩展：

```yaml
owner: quantbt
risk_tier: low|medium|high|research_only
intended_use:
out_of_scope_use:
label_horizon:
feature_requirements:
minimum_data_volume:
leakage_hazards:
evaluation_protocol:
promotion_gates:
monitoring_expectations:
resource_profile:
artifact_format:
safe_load_policy:
source_refs:
```

规则：

- Agent 只能从模型卡中选择模型。
- 新模型先加卡，默认 `runnable:false`。
- `runnable:true` 只允许两种情况：ML 有 `_make_model` 分支；DL 有 `nn.Module` 注册并在 runnable registry 中。
- 不得把“本机可 import”当成产品依赖能力。
- 不得把 TimesFM/Chronos 直接标为 alpha/ranking 主力。
- GNN/RL 默认不可进入生产候选，除非先补数据结构和泄露治理。

### 5.3 TrainedModelPassport

每个训练 artifact 一张护照：

```text
TrainedModelPassport:
  passport_id
  model_id
  version
  type_card_key
  source_doc_ids
  extraction_id
  experiment_plan_id
  job_id
  source_run_id
  artifact_manifest_id
  dataset_version_id
  feature_set_version_id
  label_definition
  split_policy
  train_fraction
  oos_fraction
  hyperparams
  seed
  environment_snapshot
  metrics
  backtest_metrics
  validation_dossier_id
  limitations
  approved_use
  monitoring_profile_id
  created_by
  created_at_utc
```

### 5.4 ModelRegistry 事件化

现有 `ModelRegistry.promote()` 不应继续作为生产晋升入口。目标模型：

```text
RegisteredModel
ModelVersion
ModelAlias: champion | challenger | baseline | shadow
ModelVersionEvent
ApprovalRequest
ApprovalDecision
PromotionGateVerdict
MonitoringProfile
```

stage 建议：

```text
draft
  -> documented
  -> runnable_template
  -> trained_dev
  -> validated
  -> paper_staging
  -> live_canary
  -> production
  -> watchlist
  -> archived | retired
```

`stage` 表示生命周期；`alias` 表示使用角色，不要混在一起。

外部参考：

- [MLflow Model Registry](https://mlflow.org/docs/latest/ml/model-registry/)：registered model、versions、aliases、tags。
- [W&B Registry](https://docs.wandb.ai/models/registry)：artifact version、lineage、audit history。
- [Kubeflow Model Registry](https://www.kubeflow.org/docs/components/hub/overview/)：create、verify、package、release、deploy、monitor。
- [Model Cards](https://arxiv.org/abs/1810.03993)：intended use、evaluation、limitations、context。

### 5.5 ArtifactManifest 与安全加载

每个 training job 生成：

```text
ArtifactManifest:
  manifest_id
  files:
    - path
      kind
      sha256
      size
  model_file
  result_json
  spec_json
  train_script_hash
  tensorboard_logdir
  eval_charts
  backtest_report
  git_sha
  dirty_state
  python_version
  platform
  package_lock_hash
  torch_cuda_mps
  env_vars_allowlist
  sbom
  slsa_provenance_optional
```

安全策略：

- 外来 `.pkl/.joblib` 默认 blocked。
- PyTorch 外来 checkpoint 只允许 `weights_only=True` 或转换为 SafeTensors。
- 自产 pickle 只能在 producer run、hash、env、signature、sandbox 条件满足时加载。
- 未知来源 artifact 不能进入 backtest/promotion。
- 推荐 tensor 权重使用 SafeTensors；供应链用 SBOM + provenance。

PyTorch 官方文档明确 `torch.load` 底层涉及 unpickling，不可信来源需要限制；因此模型 artifact loader 是安全边界，不是普通 IO。

## 6. 统一 Lineage 与 OpenLineage 映射

目标 lineage graph：

```text
SourceDocument
  -> ExtractedStrategy
  -> ExperimentPlan / PreRegistration
  -> DataLock + FeatureSpec + LabelSpec
  -> TrainingRun
  -> ModelVersion
  -> BacktestRun / ValidationDossier
  -> PaperRun
  -> LiveDeployment
  -> MonitoringSnapshot / DemotionDecision
```

内部可以用 QuantBT 自有 event ledger；外部可映射到 OpenLineage：

- 每个执行节点是 `Job + Run`。
- 每个输入/输出是 `Dataset` 或 `Artifact`。
- QuantBT custom facets 记录 `strategy_hypothesis`、`dataset_manifest`、`field_lineage`、`gate_verdict`、`approval`、`model_passport`。

外部参考：

- [OpenLineage Object Model](https://openlineage.io/docs/spec/object-model/)。
- [W3C PROV-DM](https://www.w3.org/TR/prov-dm/)：Entity / Activity / Agent 的 provenance 表达。
- [MLflow Dataset Tracking](https://mlflow.org/docs/latest/ml/dataset/)：dataset digest/source/schema/profile。
- [DVC pipelines](https://doc.dvc.org/start/data-pipelines/data-pipelines)、[lakeFS](https://docs.lakefs.io/understand/model/)、[Delta Lake](https://docs.delta.io/)、[Apache Iceberg](https://iceberg.apache.org/spec/)：数据版本和 manifest 参考。

## 7. Gate 体系

### 7.1 文档到抽取 gate

必须满足：

- source hash 固定。
- parser sandbox 通过。
- 文档 license/rights 状态记录。
- 每个 claim 绑定 EvidenceSpan。
- LLM 调用记录 prompt/model/tool schema/retrieval context hash。
- 检出 prompt injection 指令时隔离，不得影响 tool call。

### 7.2 抽取到预注册 gate

必须有：

- `economic_mechanism`
- `falsification_condition`
- `stop_rule`
- benchmark
- universe
- sample window
- OOS/embargo
- `n_budget`
- confirmatory/exploratory 标记

预注册后只允许新版本，不允许覆盖。

### 7.3 预注册到训练 gate

必须有：

- explicit `dataset_id/version_id`，禁止 `latest`。
- `verify_manifest()` 通过。
- GE-lite/freshness 通过。
- field-level provenance 到 `dataset_id/version/raw_column/file_hash/schema_hash/as_of/known_at`。
- feature spec、label spec、`t1` 与 split policy 完整。
- training request 记录 `source_doc_ids/extraction_id/experiment_plan_id`。

### 7.4 训练到模型版本 gate

必须有：

- run succeeded。
- artifact hash 和 manifest。
- train/test 日期无重叠。
- seed/env/code hash 完整。
- failed/cancelled trials 入账。
- DL 有 learning curve；ML 有 OOS metrics 和 feature importance。
- model type card 存在。

### 7.5 模型到回测/验证 gate

必须有：

- OOS 或 walk-forward。
- purged/embargo。
- 回测权重 `shift(1)`。
- 成本/滑点/冲击敏感性。
- PBO/DSR/bootstrap。
- trial ledger。
- ValidationDossier。

### 7.6 回测到 paper/live gate

规则：

- A 股只能 research/backtest/paper，不能 live。
- crypto live 必须经过 SafeKey、testnet matrix、live ladder、kill switch、human approval。
- production promotion 不能调用裸 `promote()`。
- hard fail 不允许人工 override，例如 hash mismatch、lookahead、缺 OOS、缺 PBO/DSR、未授权 artifact。

### 7.7 监控与退役 gate

生产或准生产模型必须有 `MonitoringProfile`：

```text
feature_quality
data_drift
prediction_drift
realized_label_delay
performance_metrics
pnl_metrics
live_vs_backtest_gap
turnover
slippage_drift
capacity
sector/asset exposure
latency/error_rate
thresholds
alert_routes
retrain_policy
kill_switch_trigger
incident_log_refs
last_reviewed_at
```

红灯触发 demotion/retire，不自动替换模型。

## 8. 安全、版权与供应链红线

### 8.1 最大风险链

本轮安全 agent 的核心判断：

```text
非可信文档内容
  -> LLM/Agent
  -> tool call / codegen
  -> training runner 本地全权执行
  -> 模型反序列化
  -> registry/promotion/trading
```

这条链必须在 P0/P1 被切断。

### 8.2 ToolPolicyProxy 前移

任何 tool call 都要有 side-effect class：

```text
read_only
write_artifact
mutate_registry
train_model
run_backtest
paper_trade
testnet_trade
live_trade
```

策略：

- 文档阅读 agent 只能 read/extract/propose。
- 写 artifact、训练、回测、修改 registry、promotion、交易全部进入 Approval Inbox。
- tool 参数必须通过 schema + policy 校验。
- 不可信 source context 不能直接驱动 privileged tool。
- action summary 给用户看“后果”，不是原始 tool log。

外部参考：

- [OWASP LLM Prompt Injection Prevention Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/LLM_Prompt_Injection_Prevention_Cheat_Sheet.html)：tool access、least privilege、参数验证和 human review。
- [OWASP SSRF Prevention Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/Server_Side_Request_Forgery_Prevention_Cheat_Sheet.html)：URL allowlist、网络层隔离、禁私网访问。
- [SLSA](https://slsa.dev/)：artifact supply-chain provenance。

### 8.3 必须阻断

- 未授权全文入库训练。
- 大段逐字复现付费论文/书籍/报告。
- 宏、脚本、嵌入文件、加密文档。
- magic mismatch、zip slip、zip bomb、深层嵌套压缩。
- 私网/localhost/metadata IP URL。
- 不可信 `.pkl/.joblib`。
- 外来 `torch.load(weights_only=False)`。
- LLM 根据文档内容直接调用 side-effect tool。
- 文档中出现“忽略系统指令/调用工具/泄露 secret”等 prompt injection 指令时的自动执行。

### 8.4 版权策略

产品策略应比法律边界更保守：

- 允许非替代性摘要、字段抽取、证据定位。
- 不允许输出足以替代原文的大段连续内容。
- 未知授权材料不可用于模型训练或持久化训练集。
- `ResearchSource` 记录 `declared_rights`、`can_summarize`、`can_train`、verbatim 限制。

## 9. 前端：不是大聊天页，而是三联工作台

### 9.1 `/agent-os` 信息架构

```text
/agent-os
  Research Reading Desk
  Strategy Extraction Workspace
  Model Governance Center
  Approval Inbox
  Evidence Drawer
  Trust Report
```

### 9.2 Research Reading Desk

左侧：文献库、上传、URL/arXiv/DOI、解析状态。  
中间：原文阅读器，支持高亮 EvidenceSpan。  
右侧：Claim Cards。

Claim Card 只表达一件事：

- 经济机制
- 标的池
- 因子
- 标签
- 模型
- 成本
- 风险
- 复现实验

每张卡必须显示：

```text
原文位置
摘录
agent 解释
status/confidence
缺口问题
下游对象映射
```

这里不跑训练、不推广模型，只产“可确认的研究命题”。

### 9.3 Strategy Extraction Workspace

用户看到从文献证据到策略对象的 mapping diff：

```text
EvidenceSpan -> ExtractedStrategySpec -> HypothesisSpec -> StrategyGoal
```

生命周期 rail：

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

用户必须判断：

- 是否接受这篇文章的经济机制作为待验证假设。
- 失败条件和停止规则是否合理。
- benchmark、样本窗口、OOS/embargo 是否符合研究目的。
- 该策略是否值得进入复现实验。

Agent 不能替用户接受论文结论，也不能静默把论文语境改成另一个策略。

### 9.4 Model Governance Center

把 `/training` 与 `/models` 升级为模型治理中心：

- 模型类型卡。
- 新模型卡草稿。
- 训练计划。
- 训练任务。
- 评价图/TensorBoard。
- 模型护照。
- 版本 lineage。
- champion/challenger/baseline aliases。
- promotion queue。
- monitoring/demotion。

用户看到模型卡 L1-L4、优缺点、数据要求、可训练状态、算力需求、失败模式。Agent 不能凭空使用卡外模型。

### 9.5 主屏信息规则

主屏只放四类对象：

1. 现在在哪一步。
2. 证据够不够。
3. 还缺哪个判断。
4. 下一步会产生什么后果。

日志放二级页。风险语言沿用：

```text
可信
存疑
高风险
信息不足
```

“信息不足”是正常状态，不是错误。

TrustReport 的语言必须克制：只能说“证据充分/不足、风险高、需要下一次实验”，不能说“可以放心实盘”。

## 10. 工程落地架构

### 10.1 新增后端包

新增：

```text
app/backend/app/research_ingest/
  __init__.py
  schemas.py
  store.py
  parser.py
  extractor.py
  compiler.py
  model_intake.py
  api.py
  security.py
  provenance.py
  validation.py
```

职责：

| 文件 | 职责 |
|---|---|
| `schemas.py` | `ResearchSource`, `DocumentBlock`, `EvidenceSpan`, `StrategyExtraction`, `FeatureSpec`, `LabelSpec`, `TrainingPlan`, `ValidationDossier`, `ModelPassport`, `PromotionDecision` |
| `store.py` | append-only JSONL + content-addressed raw/parsed/extractions/passports |
| `parser.py` | P0 支持 text/Markdown/HTML；P1/P2 接 PDF parser cascade |
| `extractor.py` | 调 LLMClient，强制 structured output + evidence span |
| `compiler.py` | `ExtractedStrategySpec -> HypothesisSpec/StrategyGoal/TrainingPlan` |
| `model_intake.py` | `ExtractedModelClaim -> ModelTypeCard draft` |
| `api.py` | `APIRouter` 暴露 `/api/research/*` |
| `security.py` | quarantine、SSRF、文件检查、prompt injection flags |
| `provenance.py` | SourceDocument -> Run/Model lineage |
| `validation.py` | gate verdict 与 dossier 汇总 |

### 10.2 REST API

```text
POST /api/research/sources
POST /api/research/sources/{doc_id}/parse
POST /api/research/sources/{doc_id}/extract
POST /api/research/extractions/{id}/materialize
POST /api/research/training_plans/{id}/submit
POST /api/research/jobs/{job_id}/validate
POST /api/research/model_passports/{id}/promote

GET  /api/research/sources
GET  /api/research/sources/{doc_id}
GET  /api/research/extractions/{id}
GET  /api/research/model_passports/{id}
```

### 10.3 Agent tools

```text
research.ingest_document
research.parse_document
research.extract_strategy_claims
research.extract_model_claims
research.draft_strategy_passport
research.draft_model_card
research.create_training_plan
research.submit_training_job
research.run_validation_dossier
research.request_model_promotion
```

注意：`research.request_model_promotion` 只能创建审批请求，不能直接改 stage。

### 10.4 与现有模块连接

```text
research_ingest -> model_cards:
  新模型先生成 docs/model_cards/<key>.md 草稿，默认 runnable:false。

research_ingest -> training:
  TrainingPlan 生成 TrainingRequest，同时必须携带 dataset_id/version、feature_lineage、label_spec、research_lineage。

research_ingest -> data_quality:
  训练前检查 dataset version、GE-lite、freshness、manifest hash。

research_ingest -> experiments:
  extraction/materialization/training 写 Run tags:
    kind=research_ingest
    source_doc_id
    extraction_id
    experiment_plan_id

research_ingest -> backtest_bridge:
  训练成功后生成 OOS backtest 与 ValidationDossier。

research_ingest -> model_registry:
  禁止裸 promote，走 gated promotion。
```

## 11. 测试矩阵

### 11.1 文档解析与 store

新增：

- `app/backend/tests/test_research_ingest_parser.py`
- `app/backend/tests/test_research_ingest_store.py`
- `app/backend/tests/test_research_ingest_api.py`

覆盖：

- text/Markdown/HTML chunk 稳定性。
- PDF fixture 后续加入：text PDF、扫描 PDF、跨页表格、公式、脚注、白字 prompt injection。
- content hash 幂等。
- path traversal、超大文件、magic mismatch 拒绝。
- parser run 产生 block graph 和 EvidenceSpan。

### 11.2 策略抽取

新增：

- `app/backend/tests/test_research_ingest_extractor.py`
- `app/backend/tests/test_research_strategy_compiler.py`

覆盖：

- 每条 claim 必须引用 EvidenceSpan。
- 无证据 claim 不能进入 compiler。
- `confirmed/inferred/ambiguous/unsupported/incompatible` 状态正确传播。
- 缺 benchmark/universe/OOS/embargo 生成 HITL 问题。
- prompt injection 文本不改变系统规则。
- 抽取产物能生成 StrategyGoal/TrainingPlan。

### 11.3 模型卡与模型护照

新增：

- `app/backend/tests/test_research_model_intake.py`
- `app/backend/tests/test_model_passport.py`

覆盖：

- 新模型卡默认 `runnable:false`。
- 不在模型卡中的模型不能训练。
- `ModelCard` 保留 `source_doc_ids/evidence_ids/research_refs`。
- `TrainedModelPassport` 绑定 source、extraction、dataset、feature、label、run、artifact。
- artifact hash mismatch 阻止 backtest/promotion。

### 11.4 训练与验证桥

新增：

- `app/backend/tests/test_research_training_bridge.py`
- `app/backend/tests/test_research_validation_dossier.py`

覆盖：

- training plan 必须带 dataset lineage。
- 缺 dataset/version 返回 400。
- 训练成功后生成 eval/backtest/OOS/gate 结果。
- PBO/DSR/bootstrap 缺失阻止 promotion。
- failed/cancelled trials 入账。

### 11.5 安全

新增：

- `app/backend/tests/test_research_security.py`
- `app/backend/tests/test_artifact_safe_load.py`
- `app/backend/tests/test_agent_research_tools.py`

覆盖：

- PDF 正文/脚注/metadata/表格/base64 中出现 tool injection，不产生 tool call。
- EICAR、ZIP slip、zip bomb、PDF JS/embedded file、DOCM macro、加密文档拒绝。
- SSRF：`127.0.0.1`、`localhost`、`169.254.169.254`、私网 IPv4/IPv6、redirect、`file://`。
- 恶意 pickle/joblib blocked。
- `.pt` 外来权重必须 safe mode。
- `TOOL_SCHEMA` 与 runtime handler 同步。
- side-effect tool 进入 Approval Inbox。

## 12. 实施路线

### P0：安全与最小证据脊柱

目标：先阻断最危险链路。

- 加 `research_ingest/schemas.py`、`store.py`、`security.py`。
- 支持 text/Markdown/HTML/粘贴文本入库。
- raw vault + content hash + DocumentBlock + EvidenceSpan。
- ToolPolicyProxy side-effect 分类前置。
- 文档 agent 只允许 read/extract/propose。
- 测试 prompt injection、SSRF、路径穿越、magic mismatch。

交付：可以上传/粘贴文本，得到带证据 span 的 claim cards，但不能训练。

### P1：策略抽取与预注册

目标：把文章观点转成可证伪策略资产。

- `ExtractedStrategySpec`。
- 字段状态 `confirmed/inferred/ambiguous/unsupported/incompatible`。
- HITL question generator。
- `HypothesisSpec/PreRegistration`。
- `ExtractedStrategySpec -> StrategyGoal/TrainingPlan` compiler。
- UI：Research Reading Desk + Strategy Extraction Workspace 首版。

交付：用户能从论文生成假设卡和待审批复现实验计划。

### P2：模型卡摄入与训练计划

目标：把 DL/ML 论文纳入模型目录，而不是直接训练。

- `ExtractedModelClaim`。
- `model_intake.py` 生成模型卡草稿。
- `ModelCard` 扩展 `research_refs/source_doc_ids/evidence_ids`。
- `TrainingRequest` 扩展 `dataset_id/dataset_version/research_lineage`。
- 新模型默认 `runnable:false`。

交付：用户上传模型论文后，Agent 能生成模型卡草稿和实现缺口清单。

### P3：模型护照与验证 dossier

目标：训练产物成为受管资产。

- `ArtifactManifest`。
- `TrainedModelPassport`。
- `RunProvenance`。
- 接 `data_quality`、`data_hash`、`backtest_bridge`、PBO/DSR/bootstrap。
- ValidationDossier 页面。
- UI：Model Governance Center 首版。

交付：训练模型能完整追溯来源、数据、特征、标签、环境、artifact、验证结果。

### P4：Gated Promotion 与 Approval Inbox

目标：停止裸 promotion。

- `ApprovalRequest/ApprovalDecision/PromotionGateVerdict`。
- `research/model_passports/{id}/promote` 只创建请求。
- 生产级 promotion gate：artifact hash、OOS、PBO/DSR/bootstrap、监控计划、rollback。
- Approval Inbox 显示 action summary、args diff、side effect、policy reason。

交付：模型进入 paper/live 前必须有 gate evidence 和人类审批。

### P5：高级解析、批量文献库与监控

目标：扩大覆盖面，但不牺牲治理。

- GROBID/Docling/Marker/Unstructured parser cascade。
- OCR、表格、公式、图表候选抽取。
- NLI/factuality verifier。
- 批量研报库与版本变化监控。
- MonitoringProfile、drift、live-vs-backtest gap、demotion。

交付：QuantBT 成为可持续阅读文献、复现策略、治理模型、监控退役的 Agent OS。

## 13. 必须回写到既有 Agent OS 主线的结论

这份研究对前面 Agent OS 蓝图的修正是：

1. Document Intelligence Plane 是 Agent OS P0/P1，不是后续 RAG 增强。
2. ToolPolicyProxy 和 quarantine schema 必须早于论文解析上线。
3. `SourceDocument -> ExtractedStrategy -> ExperimentPlan` 是策略生命周期第一段，不能省略。
4. 模型治理不是 MLflow UI，而是 ModelTypeCard + TrainedModelPassport + ArtifactManifest + ApprovalEvents + MonitoringProfile。
5. 新模型默认 `runnable:false` 应继续作为硬规则。
6. `TrainingRequest` 必须接 dataset/version/research_lineage，否则严格 OOS 的语义仍会被污染。
7. `ModelRegistry.promote()` 必须降级为内部 primitive，由 gated promotion 包装。
8. 前端新增 `/agent-os` 三联工作台，而不是再做一个大聊天页。
9. 对非技术用户，证据高亮和 HITL 判断点是主界面，不是附属日志。
10. SR 26-2 / OCC Bulletin 2026-13 已是 2026-06-15 的当前模型风险管理参考锚点；但它是参考，不是对 QuantBT 的法律结论。

## 14. 外部来源索引

截至 2026-06-15，本研究引用和核验的主要外部来源：

- [Federal Reserve SR 26-2: Revised Guidance on Model Risk Management](https://www.federalreserve.gov/supervisionreg/srletters/SR2602.htm)
- [OCC Bulletin 2026-13: Model Risk Management Revised Guidance](https://www.occ.gov/news-issuances/bulletins/2026/bulletin-2026-13.html)
- [GROBID Documentation](https://grobid.readthedocs.io/en/latest/Introduction/)
- [Docling](https://www.docling.ai/)
- [Unstructured Partitioning](https://docs.unstructured.io/open-source/core-functionality/partitioning)
- [Nougat](https://github.com/facebookresearch/nougat)
- [MLflow Model Registry](https://mlflow.org/docs/latest/ml/model-registry/)
- [MLflow Dataset Tracking](https://mlflow.org/docs/latest/ml/dataset/)
- [W&B Registry](https://docs.wandb.ai/models/registry)
- [Kubeflow Model Registry](https://www.kubeflow.org/docs/components/hub/overview/)
- [Model Cards for Model Reporting](https://arxiv.org/abs/1810.03993)
- [OpenLineage Object Model](https://openlineage.io/docs/spec/object-model/)
- [W3C PROV-DM](https://www.w3.org/TR/prov-dm/)
- [OWASP LLM Prompt Injection Prevention Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/LLM_Prompt_Injection_Prevention_Cheat_Sheet.html)
- [OWASP SSRF Prevention Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/Server_Side_Request_Forgery_Prevention_Cheat_Sheet.html)
- [PyTorch torch.load](https://docs.pytorch.org/docs/stable/generated/torch.load.html)
- [SLSA](https://slsa.dev/)
- [Qlib](https://github.com/microsoft/qlib)
- [FinRL](https://finrl.readthedocs.io/en/latest/index.html)
- [NeuralForecast](https://nixtlaverse.nixtla.io/neuralforecast/docs/capabilities/overview.html)
- [PatchTST in Hugging Face Transformers](https://huggingface.co/docs/transformers/en/model_doc/patchtst)
- [TimesFM](https://github.com/google-research/timesfm)
- [Chronos](https://github.com/amazon-science/chronos-forecasting)
