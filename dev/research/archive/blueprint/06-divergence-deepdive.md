# 05 · 分歧深挖与裁决（配套 04）

> **定位**：[04-codex-claude-reconciliation.md](04-codex-claude-reconciliation.md) 是 Codex×Claude 的**权威整合稿**，本文不取代它。本文是对其中 8 处关键分歧的**深挖裁决**——独立 workflow 产出（8 裁决 → 8 个对抗式核查 → 综合 → 完备性复核，18 agent / 127 万 token），全部裁为 `synthesis` 且核查后 `holds/high`。
>
> **与 04 的关系**：本文 8 条裁决与 04 §9"不能直接照搬"的 6 条降权**逐条对上 5 条**（撤稿→软监控、pod 阈值不硬编码、N_eff 是深统计、OOS 张力、谱系→信任待验）——两次独立推演强收敛，主要是**为 04 背书 + 补操作级深度**。
>
> **纪律**：凡"未核实/有政策争议"的，一律隔离在 [§3](#3-待裁定--待核实隔离区)，**不混进确定结论**。这是本文自己也要守的"别把启发式当硬定律"。

---

## 1. 8 条裁决总览

| # | 分歧 | 裁决倾向 | 核查 | 与 04 关系 |
|---|---|---|---|---|
| 1 | honest-N：朴素计数 vs N_eff | synthesis（偏 Claude） | holds/high | **深化** §4.4 |
| 2 | gate 阈值：写死 vs 浮动+不确定 | synthesis（强偏 Claude） | holds/high | **深化** §1/§4.5；⚠️FDR 一处见 §3 |
| 3 | OOS 完整性：硬隔离 vs 承诺-揭盲 | synthesis（强偏 Codex） | holds/high | **吻合** §9.5，补落地 |
| 4 | LLM 可复现：记录-重放 vs 真确定性 | synthesis（偏 Codex） | holds/high | **吻合** §3.1，补两层定义 |
| 5 | 成本/容量：平方根律默认 | synthesis（偏 Codex） | holds/high | ⚠️措辞张力，见 §3.2 |
| 6 | 严谨 vs 速度：单漏斗 vs 双速通道 | synthesis（强偏 Claude） | holds/high | **吻合** §1 RBAC 行，补护栏 |
| 7 | A股合规节点：paper-only 是否需要 | synthesis（偏 Codex 暂不建） | holds/high | **新增**就绪卡 |
| 8 | 流程即信任：如何仪表化 | synthesis（偏 Claude） | holds/high | **吻合** §3.3，补行为指标 |

**总裁决**：8/8 走综合但天平有明显倾斜——**Codex 几乎全程对"治理脊柱/HOW"，Claude 几乎全程对"数值层正确性/风险标注/人因/监管对齐"，没有一处某方完胜，正确动作永远是焊接而非二选一**。两类对称错误反复出现：Codex 倾向把"约定值/启发式"写成"硬定律"，Claude 倾向把"工程不可达的理想"当承诺——两类都靠"诚实降级措辞 + 可审计过程保证（而非密码学/硬件强制）+ 随上下文浮动（而非写死）"修正。

---

## 2. 已核实的操作级落地（对 04 的深化）

> 以下为核查 `confirmed` 的部分。涉及"具体配方/政策反转/新引用"的留到 [§3](#3-待裁定--待核实隔离区)。

### 2.1 honest-N → 双字段 + 喂数规则（深化 04 §4.4）
- **关键修正**：04 §4.4 说"所有 trial 计入 N、不准手填"——但**喂 DSR 的不能是这个朴素总计数**。规范做法（López de Prado 2019 算例：6385 相关 trial → 聚类 k=4 喂 DSR）是：
  - `n_trials_total`（含 failed/cancelled/hidden/rejected）= **审计/治理量**，强制持久化进 `research_lineage.json`、Verifier 核对、反"偷删失败 trial"作弊——**这一项不可退让**（Codex 的治理意图对）。
  - `n_eff`（有效独立试验数，对 trial 收益相关矩阵聚类估）= **喂 DSR/PBO 的统计量**。
- **对冲"N_eff 估小击穿校正"**：DSR 门控用 k 稳健性区间内**最保守**（N_eff 最大 → DSR 最小）那个值判定，不用最优 k。
- **冷启动/小样本**：`n_total < ~20` 或样本期过短时**降级回 N_total 喂 DSR**（顺带解决 N=1 冷启动）。
- **第二防线**：保留 White Reality Check / Hansen SPA / FDR-family 作为**不依赖 N_eff 估计精度**的 bootstrap 门，双门皆过才晋升。
- ⚠️ N_eff 的**具体估计器配方**（linkage/距离/k 区间）→ 见 [§3.4](#34-onc-配方不要写死)。

### 2.2 gate 阈值 → 3 档闸（深化 04 §1/§4.5）
把数值层重构为三档（保留 Codex 的"分层硬否决"骨架与门类清单）：
1. **真·硬数学闸**（结构性、不可配、不可 override）：bootstrap Sharpe 95% 下界 ≤ 0、minBTL 样本不足、`t1` 泄露/lookahead、hash 错配。
2. **软门槛 + 强制人工复核**（可配 profile、必带不确定性、UI 暴露）：**DSR 是 [0,1] 概率、已内生依赖 N/T/skew/kurt**，故改成"< 约定显著性（默认 0.90 paper / 0.95 prod）触发人工复核"，**删掉 0.6/0.8/0.5/0.2 这套裸分阈值**（再叠固定 cutoff 是双重计数）；必须显示输入 N_eff/T/skew/kurt + 区间。
3. **经济/容量/材料性**（人审）。
- **配置化**：新增 `gate_policy` 配置对象进 `schemas.py` + DB，每个 `strategy_passport` 绑定 gate-profile（paper/prod/custom）；`materiality_tier` 缩放"几道软门槛 + 几个人审签字"，但不动硬闸。
- **措辞护栏升为 spec 一等内容**："DSR 是标度修正非铁律""阈值跨资产/regime 不可平移（McLean-Pontiff 发表后衰减 58%）"。
- ⚠️ **PBO 硬线取 0.5 还是 0.05**、**FDR 是否升为主判据** → 见 [§3.1](#31-fdr-是主判据还是辅助证据政策决定待你拍)。

### 2.3 OOS 完整性 → 承诺-揭盲 + 访问计次（吻合并落地 04 §9.5）
- 保留 04 的"版本锁 + gate + replay hash"为根基；**丢弃"权限层技术上不可访问的硬隔离"措辞**（单机/开放 Parquet 无 TEE 即无真实边界）。
- 补 04 缺的件：**一个被治理、计次、留痕的 OOS 访问通道**——
  - dataset_version 切分时把 OOS 区段 PIT 边界/行键集合/SHA-256 写进 manifest 并 **commit（承诺）**；
  - 新增 side-effect class `read_holdout`，揭盲前对探索/researcher 角色**默认拒绝**并记 `HoldoutAccessAttempted` 事件；
  - **揭盲（reveal）= 一次性、不可撤销的显式 HITL 审批门事件** `HoldoutRevealed`；
  - OOS 访问计数 k 纳入 gate：揭盲前 `read_holdout` 计数 > 0 即 quarantine（接 Thresholdout 查询预算）。
- **强度承诺诚实降级**为"违规可被独立审计检出"，而非"技术上不可能违规"。

### 2.4 LLM 可复现 → 两层定义 + 钉定护栏（吻合并细化 04 §3.1）
- **L1 数值可复现**（回测/因子/指标/优化器）：`同代码 + 同 dataset_hash + 同 seed → ±1e-6` **硬承诺**，与 LLM 无关（GOAL §1.2 已正确把 ±1e-6 锁定在数值计算）。
- **L2 审计可复现**（clarifier/researcher/verifier 等 LLM 节点）："记录-重放等价"而非数值等价——strict replay **逐字节重现已记录输出，不重新采样**。明确写"LLM 节点可复现性由 record-and-replay 提供、不由 seed/temperature 提供"。
- **强制钉定**（不可配后浮动）：每条 `LLMCallRecord` 记 provider、**不可变模型版本 id（禁裸别名 `gpt-4o`，存 `gpt-4o-2024-08-06`）**、system_fingerprint、prompt_version_hash、完整 messages、temperature/top_p/seed、tool schema 版本。
- **缓存键** = hash(模型版本 id + 全部采样参数 + 规范化 messages + 工具定义 + 上游输入 hash)，任一变化即 `ReplayDiverged`。
- **ReplayDiverged 阈值**：结构化/裁决类输出（verifier block/pass、门控数值）**精确相等、差异即阻断 promote**；自由文本默认不参与 strict 等价。
- ⚠️ "托管 LLM 真确定性工程不可达"的**实证锚**（Thinking Machines 2025 等）→ 见 [§3.3](#33-五条新进口引用未过附录核查)。

### 2.5 成本/容量 → 平方根默认 + 全护栏（吻合 04，措辞见 §3.2）
- 保留 capacity gate + 平方根冲击律作默认引擎：`I(Q) = Y·σ·√(Q/ADV)·notional`，δ 进 `InstrumentSpec`/`AssetClassTag` 注册表、linear/fixed 作 ADV 不可得时降级档。
- **护栏**：δ 指数**随 asset_class 浮动**（默认 equity_us 0.5 / A股 0.65 / crypto_perp 0.58——这些是**默认值待标定**，非实证 CI）；Y 前因子可配（默认 0.5，crypto 0.9）+ **强制输出 [0.3,1.5] 成本带**，前端画区间非点值；区分 temporary（可回撤）vs permanent（≈峰值 2/3）；成本构成按资产浮动（A股印花税 0.05%、crypto funding/borrow 共用同一 `cost_model`）。
- capacity gate 阈值（impact≤25% 毛 alpha / participation≤5% ADV / illiquid≤2% / AUM≤80%）保留作默认，但**每条标注"保守治理缓冲、行业惯例非被证明的临界点"**，超限 → HITL go/no-go + 必须解释；gate 用敏感性区间**悲观端**判定。
- ⚠️ "AQR 争议"措辞 → 见 [§3.2](#32-aqr-措辞精化建议给-04-93)。

### 2.6 严谨 vs 速度 → 双速通道 + 4 道防后门护栏（吻合并落地 04 §1 RBAC 行）
在 Codex 单一状态机脊柱上新增 **materiality 驱动的双速通道**：`EXPLORATORY_SANDBOX`（轻 HITL、不进生产谱系）↔ `RESEARCH_REGISTERED`（全漏斗），用 4 道**不可后门化**护栏焊死：
1. **n_trials 全程累加**（探索期试错计入 DSR/PBO 不清零，堵 garden-of-forking-paths）；
2. **exploratory → confirmatory 必须显式 `PreregistrationRequested`** 冻结假设卡（economic_mechanism/falsification_condition/stop_rule）+ 快照累计 N 作 confirmatory DSR 起点；
3. **`materiality_tier` 决定验证深度与 HITL 闸门数**（T3-low：0 道挂起审批、统计闸门仅警告；T2-standard：2 道；T1-material/实盘：全 5 道逐项 + 严阈）；
4. **`approver ≠ creator` 用 RBAC 强制**（roles{creator, approver, allocator, viewer}，promote 由 kernel 校验 `actor.role==approver && actor.id!=run.creator_id`）。
- Codex"绝不为速度松硬闸门"在硬失败项（泄露/哈希错配/缺 DSR/A股实盘禁令）**完全正确并保留**；SR 26-2(2026) 为 materiality 分级背书。
- 🚧 **关键前置硬约束（待办，非已成立）**：n_trials 诚实计数捕获目前是 **spec 承诺、非实现代码**（`dsr.py` 把 n_trials 当可信传入参数、无计数器）——**在该件落地前，探索沙盒在统计上仍是 p-hacking 后门**。这是切片里优先级最高的工程待办。
- ⚠️ **单人多角色**（既 creator 又 approver）下 RBAC 形同虚设——可能需产品层承认"单人模式 approver≠creator 无法强制、须外部第二人"。

### 2.7 A股合规 → 非阻断就绪卡（新增，吻合 GOAL §6.5 + §2.1）
- 保留 Codex"A股仅 paper、不建可阻断合规执行节点"（**法律上正确**——程序化交易义务硬触发于"在交易所真实下单"，paper-only 永不触发）。
- 补一个**预置、信息性、不阻断**的 `ComplianceReadinessCard`（preflight）：A股从 paper 晋级到更高态时产出、挂进 TrustReport/GateTimeline、状态恒为 `informational`、**绝不进 hard-fail 列表**。含三块全信息性：① 报告就绪模板（五类，字段从 lineage 带出、标"模拟假设值"）；② **异常交易自检诊断**（把 300笔/秒·20000笔/日 与四类异常做回测期诊断指标，等效申报速率随策略频率/universe 实时算、不写死，触线给黄色信息提示）；③ 系统测试/应急 checklist（paper 标 N/A）。
- **核查纠正**（反向加固本裁决）：现行沪深北细则将**个人/自然人投资者**与机构并列、同样适用"先报告后交易"——这更说明就绪卡有价值。

### 2.8 流程即信任 → 预注册假设 + 行为指标（吻合并落地 04 §3.3）
- 保留 Codex 克制的 TrustReport 措辞（必要但不充分）；把"流程→恰当信任"写成**项目级可证伪、被监控的假设**（对齐 04 §3.3 `TrustHypothesis`）。
- **必装行为遥测（无需 RCT，全来自现有 event store/Approval Inbox）**：每个 gate 决策记 `{风险档, 建议方向, 证据强弱分桶, 最终决定, dwell_time, 是否展开 Evidence Drawer/RunReplay}`；据此算 **over-reliance 代理**（证据不足/高风险档仍 approve 比例）、under-reliance 代理、**acceptance-by-confidence 曲线（倒挂 = 校准失败告警）**。
- **反向校准检查**：高风险档出现"秒批（dwell<3s）+ 不展开证据 + 高采纳"三联征时，下一个同档闸门强制注入 counter-evidence 卡 + forced pause（默认 10s / crypto live 20s）；只在高门控风险闸门触发（A股 paper/低风险页不触发，避免坐实决策疲劳）。
- **验收门**：该遥测须**先于 P1 脊柱**落地；AoR 倒挂或 over-reliance 超阈 = 前提被证伪 → 触发产品复盘。
- ⚠️ **核心警示**（核查确认）：解释/证据展示**可靠提升采纳/信任，却未必提升决策质量、反而常增加 over-reliance**——即"谱系做得越漂亮越可能制造 rubber-stamp"，与决策疲劳叠加。具体行为指标的精确数值 → 见 [§3.3](#33-五条新进口引用未过附录核查)。
- 🔻 **残留不确定**：金融 ground-truth 滞后数周（gate 对错要到 OOS/live PnL 才揭晓），使 RAIR/AoR 这类实验室指标退化为**弱代理**；"不读代码经济学者读谱系图形成恰当信任"**无任何已发表实验**——故以行为指标**持续证伪**，而非默认成立。

---

## 3. ⚠️ 待裁定 / 待核实（隔离区）

> 这些**不是确定结论**。要么需要你拍政策，要么需要先把引用核实了才能写进 schema。完备性复核（它读了 04 当基准）专门抓出来的，我如实隔离。

### 3.1 FDR 是"主判据"还是"辅助证据"？（政策决定，待你拍）
- **冲突**：我的 [2] 裁决把 **FDR/q-value（q≤0.10）升为主判据**，理由引"Chen 2024 empirical-Bayes 强识别"。但 **04 文档 §4.5/§9 + README:74 + roadmap:75** 的立场是"**FDR 不解决发表偏误（Chen-Zimmermann：发表偏误下 t-hurdle 不可识别），只作辅助证据、非唯一判据**"。
- **判断**：这是真冲突，不是措辞。**默认保持 FDR 为辅助证据**（与 04/README/roadmap 一致），**除非**那条"Chen 2024 强识别"引用能被核实为**确凿推翻** Chen-Zimmermann——若能核实，则需在 README/roadmap **显式标注"推翻先前立场"并附论文**，再升为主判据。
- **行动**：⏸ 待你决定是否要我去核实那条 Chen 引用。在此之前 05/04 一律按"FDR 辅助"写。

### 3.2 AQR 措辞精化（建议给 04 §9.3）
- **非政策反转，纯措辞**：实际行动两边一致（保留平方根默认 + 敏感性区间）。分歧只在**对"争议是什么"的刻画**。
- 04 §9.3 现文："平方根冲击律存在 AQR 争议，必须显示敏感性区间。"
- **建议改为**："平方根冲击律的**函数形式是 SOTA 共识**（AQR/Frazzini-Israel-Moskowitz 自己的成本模型也是平方根）；真正的争议在 ① Y 前因子标定多为二手经验值，② **单笔 metaorder 执行成本不能外推为策略级长期净成本**（这是两个量级），③ δ 指数在 A股/crypto 偏离 0.5。**故必须显示 Y∈[0.3,1.5] 敏感性区间、δ 随资产浮动、并区分单笔执行成本与策略级净成本。**"
- **行动**：建议你采纳这条对 04 §9.3 的最小改写（见 [§5](#5-给-04-93-的最小措辞修订建议)）。我**没有**擅自改你的 04 文档。

### 3.3 五条"新进口"引用未过附录核查
我这轮最承重的几条"判谁赢"引用，grep 那份 360KB 已核查附录**全部 0 命中**——即它们**没经过和其余语料同一道对抗式核查**：
- `[4]` Thinking Machines 2025 / batch-invariant kernel / vLLM temperature=0 出数十种输出 / 1.6-2x 性能损失；
- `[2]` Chen 2024 empirical-Bayes 强识别；
- `[8]` Bansal CHI 2021 / Schemmer 2023 / RAIR-RSR 指标（29.59%→38.87% 等具体数）；
- `[2]` Neyman-Pearson PBO>0.05 决策线；
- `[1]` ONC average-linkage / 1-corr 距离配方。
- **判断**：方向多半对、且确实让裁决更锋利，但**载荷性数值不能当"已核实"写进 schema**。
- **行动**：⏸ 这几条标"待核实"。要不要我对它们再跑一轮定向核查（小 workflow），核实后才升为确定结论？

### 3.4 ONC 配方不要写死
- 我的 [1] 把 N_eff 估计器过度具体化成"ONC / average-linkage / 1-corr 距离 / k∈[2,min(10,n)]，LdP 2019 规范"。但原始来源只说"聚类/ONC"且明确标注"**N 封顶仍是开放问题、无权威定论**"。
- **判断**：**方向站得住**（喂 DSR 用 N_eff 不用 N_total），**具体配方不该写死**——这正是我指责 Codex"把启发式当硬定律"、自己却犯的毛病。
- **行动**：05 §2.1 保留方向；估计器（linkage/距离/k 区间）落为**可配参数 + 标"开放问题、默认值待标定"**，不写"规范"。

### 3.5 我这 8 条漏掉、但 04 已覆盖的分歧（指回 04，不重复）
完备性复核指出我只挑了 8 处，**漏了几处 04 已经覆盖的**——这些以 **04 为准**，05 不重复造：
- **安全/对抗模型前移**（04 §3.2，"Claude 胜出"，最高风险项：实盘 key + 能下单 agent）；
- **数据可信度作第一闸门**（04 §3.4 / §4.3，garbage-in 会击穿所有下游统计闸门）；
- **DSR 标度修正 / False Strategy Theorem 的 `var_sr_hat` 项**（`dsr.py:33-38` 实现与 docstring:8 自相矛盾——roadmap P0 已列）；
- **多 agent 编排边界**（04 §1"Claude 更严"）；
- **成本/延迟/失败经济学**（挂起数天的审批节点 + fan-out + challenger 重跑 = 无 token 预算/成本上限/API 中途宕机语义——两份都欠）。

---

## 4. 对首个垂直切片的影响（schema/阈值/通道必须第一版就定对）

首个垂直切片（04 §P2：intent→HypothesisSpec→dataset lock→DataGate→deterministic backtest→ValidationDossier→TrustReport→ApprovalQueue，no-live）命中 8 处裁决的 7 处（仅 [7] 可推后）。切片不必变大，但下面几个**schema 级决定切片第一版就要定对，否则返工代价最大**：

- **[1]** ValidationDossier 与 lineage schema 必须是**双字段** `n_trials_total` + `n_eff`；`CandidateTrial` 加 `cluster_id`；DSR gate 按区间最差 k 判定、小样本降级回 N_total。
- **[2]** `gate_policy` 配置对象进 `schemas.py` + DB，`strategy_passport` 绑定 gate-profile；DataGate 后的统计闸按 3 档落地（DSR 删裸分、改"<显著性触发人审"）。
- **[3]** dataset lock 这一步就把 OOS PIT 边界/行键/SHA-256 写进 manifest 并 commit；`ToolPolicyProxy` 新增 `read_holdout` 默认拒绝 + `HoldoutAccessAttempted`/`HoldoutRevealed` 事件。
- **[4]** 所有 LLM 节点的 `LLMCallRecord` 第一版就钉不可变模型版本 id + system_fingerprint + prompt_version_hash + 完整 messages + 采样参数；缓存键 = 全部影响输出的输入 hash。GOAL §1.2 先写入两层可复现定义。
- **[5]** deterministic backtest adapter 就把冲击引擎写成 `I(Q)=Y·σ·√(Q/ADV)·notional`，δ 进注册表、Y 可配 + 输出 [0.3,1.5] 成本带；`InstrumentSpec` 最小子集从 P4 **前移到切片**。
- **[6]** 状态机在 `HYPOTHESIS_DRAFT` 后分叉 `EXPLORATORY_SANDBOX`↔`RESEARCH_REGISTERED`；RBAC roles + promote 校验在 ApprovalQueue 接线。🚧 **n_trials 诚实计数捕获必须在沙盒开放前先实现**（否则探索通道是 p-hacking 后门）——切片里优先级最高的工程待办。
- **[8]** TrustReport→ApprovalQueue 就埋行为遥测（风险档/证据分桶/dwell_time/drawer 展开），先于 P1 脊柱落地 AoR/over-reliance 计算与倒挂告警。这是切片**自带的自我证伪仪表**。

---

## 5. 给 04 §9.3 的最小措辞修订建议

> 仅建议，**未擅改 04**。

**现文（04 第 470 行）**：
> 3. 平方根冲击律存在 AQR 争议，必须显示敏感性区间。

**建议改为**：
> 3. 平方根冲击律的**函数形式是 SOTA 共识**（AQR/Frazzini-Israel-Moskowitz 自己的成本模型也是平方根，δ≈0.5 跨股票/期货/期权/BTC 成立）。真正的争议在：① Y 前因子标定多为二手经验值；② **单笔 metaorder 执行成本 ≠ 策略级长期净成本**（两个量级，不能外推）；③ δ 指数在 A股/crypto 偏离 0.5。因此必须显示 **Y∈[0.3,1.5] 敏感性区间**、δ 随 asset_class 浮动、区分 temporary/permanent 冲击，并明确标注"单笔执行成本不代表策略级净成本"。
