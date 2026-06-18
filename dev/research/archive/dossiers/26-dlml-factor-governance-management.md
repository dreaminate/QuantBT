# 26 · DL/ML 该不该进"因子库"·前沿机构怎么分 + 模型护照/MLOps

> 机构级 Agent OS 成品环节深挖 · 全程 Opus 4.8 · 对抗式核查已降权 · 重心=前沿研究+概念级推荐 · 不含 file:line 代码接线
> 簇 E

## 1. 一句话定位

DL/ML 模型**本体不该进因子库**——这是范畴错误。正确分法是**两层 + 一份契约**：**因子/特征库**只做因子的"定义与值"的记录系统（公式因子与 ML/DL 输出同居一处），**模型注册表**存"产物"（`.pkl`/`.pt`、超参、训练快照、模型护照、升级闸与监控）；二者由一份**稳定的信号契约**（instrument×time×score + shift + PIT + 输出指纹 + 模型版本反向引用）解耦。换句话说：**模型输出登记为信号进因子库，模型本体进注册表**。这一分法直接锚定在 Microsoft Qlib 的"因子定义 vs Model Zoo"边界、MLflow 的阶段化升级、Feast 的特征注册表分离上；其工程红线——"把 `.pt` 当一个因子塞进因子库会逼着因子库背上版本/血缘/重训的重量"——是个真正有价值的洞。本项目的 **v3 `backtest_bridge` 输出本身就近似是这份契约**：信号序列入因子库、模型本体入注册表。RL/GNN/LLM 因子对因子库而言因此**都只是"一种信号"**，下游零改动，与"资产无关、贯穿全程"的北极星一致。**核心价值在那份窄契约的语义正确性 + 统计闸的硬约束，不在堆一套企业级治理机器。**

---

## 2. 前沿 SOTA 与代表系统

| 系统 / 范式 | 它是什么 · 对本环节意味着什么 | URL |
|---|---|---|
| **Microsoft Qlib** | 数据层 + 表达式引擎（因子定义）+ Model Zoo + `qrun`：**最接近本项目目标架构**的开源参照，因子 / 模型 / 信号边界清晰可借。 | https://github.com/microsoft/qlib |
| **MLflow Model Registry**（开源, Linux Foundation） | 模型产物治理事实标准：版本、阶段（staging/production/archived）、闸控升级、回滚、过渡历史——可作模型注册表底座，阶段流转天然对应"研究→paper/shadow→实盘"闸。 | https://mlflow.org/docs/latest/ml/model-registry/ |
| **Weights & Biases Registry** | "一切皆版本化产物"：血缘、别名、审计历史、治理——其 artifact 模型契合模型护照的逐版本刷新需求。 | https://docs.wandb.ai/models/registry |
| **Feast / Tecton 特征库** | 特征/因子注册表与模型注册表分离、FTI（feature-training-inference）管线三分——即本环节"两层"分法在 MLOps 侧的直接同构。 | https://mlopsplatforms.com/posts/feature-store-comparison-2026/ |
| **WorldQuant BRAIN** | alpha factory，业界传说为"存信号抽象而非模型本体"。⚠️ **核查降权**：见第 7 节——所引来源是第三方爬虫，**不记录 BRAIN 内部架构**，此"先例"不可倚重。 | https://github.com/zhutoutoutousan/worldquant-miner |
| **Alpha Capture System（Marshall Wace TOPS, 2002 起）** | 成熟买方"信号清册"范式。⚠️ **核查降权**：见第 7 节——alpha capture 是众包卖方交易想法，与"把 ML 模型**输出**登记为信号"只是**修辞类比、非架构先例**，且所引为 2021 综述非 2002 一手。当背景色，别当直接先例。 | https://papers.ssrn.com/sol3/papers.cfm?abstract_id=3873884 |

> ⚠️ **核查降权汇总**：本表中**承重的两层架构论点站得住，靠的是 Qlib / MLflow / Feast**；WorldQuant 与 Alpha Capture 两行是**修辞性 / 未被其所引来源支撑**的"先例"，不应作为"该模式已被证明有效"的证据。

---

## 3. 关键论文（每条带 URL）

1. **Model Cards for Model Reporting（Mitchell et al., 2019）**
   九段式标准文档（预期用途、评测、局限、定量分析等）；是"模型护照"概念的源头。九节结构经核实**准确**。
   https://arxiv.org/pdf/1810.03993

2. **The 10 Reasons Most Machine Learning Funds Fail（López de Prado, 2018）**
   "西西弗斯范式"（孤狼研究者手工迭代）vs 工业化元策略生产链；点名 CV 泄露、回测过拟合是主导失效。是"工业化 ML 信号生产"叙事的源头，**也是"ML 失败是常态"的源头**——见第 8 节这对张力。
   https://papers.ssrn.com/sol3/papers.cfm?abstract_id=3104816

3. **The Probability of Backtest Overfitting (PBO/CSCV) & The Deflated Sharpe Ratio（Bailey, López de Prado 等）**
   升级闸必须执行的统计闸：CSCV 估计某回测配置的过拟合概率，DSR 按试验次数对 Sharpe 做选择偏差校正。
   ⚠️ **核查降权**：DSR 是假定零分布下的**尺度/选择偏差校正**（讲统计可信度、不讲经济稳健性），**只与喂给它的试验次数 N 一样诚实**，可通过**少报 N 被博弈**；CSCV/PBO 有**已记录的弱点**（相关 OOS 折叠会抬高其评估质量），**仅在合成/受控设定下明显优于 walk-forward**。别把 PBO 当"干净闸"。
   https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2326253

4. **Empirical Asset Pricing via Machine Learning（Gu, Kelly, Xiu, 2020）**
   ML 在资产定价有正面证据，但**浅层胜过深层**（约 3 层达峰）；低频小样本里"更深≠更好"。结论经核实**准确**。
   ⚠️ 见第 8 节：该证据为**美国大盘已发表研究**，自身受发表偏差影响，**不可直接外推**到 A股 T+1/涨跌停/散户主导的微结构。
   https://www.nber.org/system/files/working_papers/w25398/w25398.pdf

5. **Is There a Replication Crisis in Finance?（Jensen, Kelly, Pedersen, 2023）**
   反驳复现危机：**"大多数（the majority）因子可复现"**，方法一致时复现率高；主张把因子复现当真争议、**用统一统计闸**而非预设结论选边。
   ⚠️ **核查降权**：论文**头条措辞是"the majority"，不是精确的"~82%"**；82% 是**论文内一个特定切口**（Chen-Zimmermann 预测变量在其门槛下的美国复现率），随定义/门槛/地区而变。把精确数字当头条传达了**超出论文所声明的精度**——这是**精度/框架降权，非实质降权**，方向（因子大体可复现、当争议处理）成立。
   https://onlinelibrary.wiley.com/doi/full/10.1111/jofi.13249

6. **Spurious Predictability in Financial ML（2026 preprint）**
   自适应搜索 + 泄露共同制造伪可预测性；背书无泄露 walk-forward。
   ⚠️ **核查降权**：**二手/preprint**，非同行评审定论。
   https://arxiv.org/html/2604.15531v1

7. **AI Model Passport（CSBJ, 2025）+ 开源 AIPassport**
   成文的"模型护照"生命周期框架，含机器可读清单实现。
   ⚠️ **核查降权**：该文**是健康/生物医学 AI 可追溯框架**（CSBJ = Computational and Structural Biotechnology Journal，"健康领域透明 AI"）。把它当量化交易护照蓝图是**跨域移植**——正是研究自身 pitfalls 警告的"整套搬运重监管模板"。可作**结构灵感**，不应当作"领域契合的蓝图"。
   https://www.sciencedirect.com/science/article/pii/S2001037025004015

---

## 4. 机构最佳实践 / 标准

- **两层分治：模型产物治理 vs 信号登记。** 模型本体进模型注册表；模型输出（逐标的分数）作为一个信号、与公式因子同居于因子库。RL/GNN/LLM 因子对因子库都只是"一种信号"。
  来源：WorldQuant alpha 抽象（⚠️ 见第 7 节，弱）、Qlib、Feast/MLflow — https://github.com/microsoft/qlib

- **闸控升级（gated promotion）**：阈值→阶段→审批，prod 前加集成/影子/业务复审，保留过渡历史以便回滚；映射"研究→paper/shadow→小资金→实盘"。
  来源：MLflow Model Registry workflow — https://mlflow.org/docs/latest/ml/model-registry/workflow/

- **champion-challenger + 影子部署**：新模型与在产 champion 在同一数据上并行，**记录但不动钱**；契合 A股→paper / 加密→Binance 实盘。
  ⚠️ **核查降权**：所引 Wallaroo/DataRobot/FICO 是**厂商营销页**，非一手/同行评审；实践本身是标准 MLOps，引用仅作示例、非权威出处。
  来源：Wallaroo、DataRobot、FICO — https://wallaroo.ai/ai-production-experiments-the-art-of-a-b-testing-and-shadow-deployments/

- **模型护照作为一等信任产物**：以 Mitchell 九节为骨架、AIPassport 为生命周期框（⚠️ 健康域、见第 3/7 节）、CycloneDX ML-BOM 为机器可读清单；agent 在 train/bridge/promote 自动填（训练数据指纹、OOS 方案、DSR/PBO、容量/衰减、相关性、漂移阈值、退役条件），让外行或审计 agent **仅凭护照即可判信任**。
  来源：CycloneDX ML-BOM v1.5+ — https://cyclonedx.org/capabilities/mlbom/

- **SR 11-7 三支柱**：概念稳健性、结果分析、持续监控；按风险定验证频率；对黑箱做有效挑战；ML/AI 经**解释**纳入模型定义。
  ⚠️ **核查降权**：SR 11-7（2011）**早于 ML 时代、文本从未显式提 ML/AI**；其宽泛模型定义是**被后续指引解读**为覆盖 ML。"2011 文本本身把 ML 纳入定义"的措辞**夸大了显式性**（精神上可辩护，字面上过陈述）。
  来源：US Fed/OCC SR 11-7 — https://www.federalreserve.gov/supervisionreg/srletters/sr1107.htm

- **NIST AI RMF 四功能 Govern/Map/Measure/Manage** 迭代应用、Govern 绑定其余——作 agent 治理动作编排骨干。
  来源：NIST AI RMF 1.0（2023）— https://airc.nist.gov/airmf-resources/airmf/5-sec-core/

- **CycloneDX ML-BOM**：架构、训练数据、配置、指标、偏差评估、人类监督的机器可读清单；外部引用可挂 model-card；可验证指纹，呼应文档化精神。
  来源：CycloneDX ML-BOM — https://cyclonedx.org/capabilities/mlbom/

- **研究 alpha vs 生产 alpha 分离 + 多闸验证**（IC/换手/成本、多 regime OOS、容量、衰减、相关性、regime 稳定性）。
  ⚠️ **核查降权**：所引把"衰减半衰期缩至 ~12-24 月"当既定机构事实——**二手（Substack 综述）+ 部分依赖一篇被标记为 RETRACTED 的 arXiv 2512.11913**；经典因子衰减文献报告的是**以年计**的半衰期。见第 7 节，**别把 12-24 月当固定节奏硬编进护照**。
  来源：量化信号生命周期综述 — https://youngandcalculated.substack.com/p/how-quant-hedge-funds-actually-build

> **关于 EU AI Act 的特别说明**：研究稿把"EU AI Act 自 2026-08-02 强制 Art.11/12/14、可作模型护照模板"当成已定、迫近、适用的合规事实——这是**本环节最强的过度声称，已整体降权**，详见第 7 节。**本文不把 EU AI Act 列为承重的合规锚。**

---

## 5. 对 QuantBT 这套架构的推荐方向（概念级）

> 仅概念级方向，不点 file:line、不排实施计划。

1. **采纳两层 + 一份契约，把它当产品的脊柱。** 因子/特征库 = 因子定义与值的记录系统（公式因子与 ML/DL 输出同居）；模型注册表 = 产物（`.pkl`/`.pt`）、超参、训练快照、护照、闸控/监控；中间一份**稳定的信号契约**（instrument×time×score + shift + PIT + 输出指纹 + 模型版本反向引用）解耦二者。把 v3 `backtest_bridge` 的输出**正式承认为这份契约**。

2. **保持两库纯净。** 因子库只认那个窄契约接口；产物、日志、checkpoint、评测报告全住模型注册表，靠指纹交叉引用。这样 RL/GNN/LLM 因子**都只是因子库眼里的"一种信号"，下游零改动**，对齐资产无关北极星。

3. **把模型护照做成一等信任产物，但保持单用户可承受的最小可行子集。** 以 Mitchell 九节为骨、ML-BOM 为机器可读清单；agent 自动填训练数据指纹、OOS 方案、DSR/PBO、容量/衰减、相关性、漂移阈值、退役条件。
   ⚠️ 见第 7/8 节：**别整套搬 MLflow + W&B + Feast/Tecton + ML-BOM + NIST AI RMF + SR 11-7 的企业级机器**——对单用户（D4）A股→paper / 加密→Binance，**护照不该比被治理的交易系统更重**。CSBJ AIPassport 是健康域、当结构灵感而非领域蓝图。

4. **信号升级做成显式分级闸，统计闸优先于复杂度。** 研究信号→paper/shadow（champion-challenger、不动钱）→小资金→实盘，每级都执行**无泄露 walk-forward + DSR/PBO + 容量/衰减/相关性**。把本项目"可选的"无泄露 walk-forward OOS**焊成硬约束**；对 DL/ML 按试验次数 deflate Sharpe。
   ⚠️ 见第 8 节：DSR 只与诚实的试验计数 N 一样可信；PBO 在真实（相关 OOS）数据上不是干净闸。**别把"不可旁路闸"当虚假安心。**

5. **默认怀疑 + 内建退役。** 给每个实盘信号配漂移监控（PSI/KL/预测分布）与基于规则的自动停（对齐已拍板的 D3），配显式衰减再评估节奏与"净新增信号"看板，把退役条件硬编进护照。
   ⚠️ 见第 7/8 节：**别把再评估节奏锚到"~12-24 月"这个二手/部分撤稿来源的数字**；低频小样本下 PSI/KL 噪声大，自动停若接在噪声漂移信号上会**抖动/在最坏时点 de-risk**——需阈值、滞回（hysteresis）、对误报的治理。

6. **先硬化研究真正跳过的难处，而非堆治理。** 优先级应是：(a) 信号契约的**泄露语义**——PIT 正确性、shift/embargo 约定、label/feature 窗口重叠、公司行动/幸存者处理、**输出指纹到底哈希了哪些输入、数据修订如何令其失效**；(b) **诚实的全研究环路试验计数**（含被放弃的配置、超参扫描、特征实验），否则 DSR 是剧场；(c) **闸与"自动填护照的 agent"的独立性**——别让生产信号的同一自动化又给它签字背书，这违背有效挑战的全部要义（见第 8 节职责分离漏点）；(d) **A股专属容量/衰减**，不可从美国研究移植；(e) **DL 产物的可复现性清单**（GPU/cuDNN/seed/库版本/混合精度的非确定性），护照需环境/确定性清单，不只是模型版本反向引用。

---

## 6. 架构级参考（少量伪代码 / schema 草图，非代码接线）

> 示意草图，不接线到现有代码。

**6.1 信号契约（两库之间唯一的窄接口）**

```yaml
signal_contract:                  # 因子库只认这一接口; 这就是 v3 backtest_bridge 的产物
  signal_id: str
  values: instrument × time → score   # 唯一被因子库当"因子值"摄入的东西
  shift: int                      # 防前视的滞后 (e.g. predict@T → trade@T+1)
  pit_asof: timestamp             # point-in-time 戳; 用哪个数据修订版本生成
  embargo: int                    # 训练/评估折叠间的禁带, 抗 label/feature 窗口重叠
  output_fingerprint: sha256      # ⚠️ 见第8节: 须明确哈希了哪些输入,
                                  #   及数据修订如何令指纹失效 (难处, 研究跳过)
  model_ref:                      # 反向引用模型注册表里的本体, 而非内联模型
    model_id: str
    model_version: str
  # 注: 模型本体 (.pt/.pkl)、权重、checkpoint 一律不入此契约 → 它们住注册表
```

**6.2 模型注册表条目（产物 + 护照住这里）**

```yaml
registry_entry:
  model_id: str
  version: str
  artifact: ml/*.pkl | dl/*.pt    # 本体在此, 不进因子库 (避免范畴错误)
  hyperparams: {...}
  train_snapshot:
    data_fingerprint: sha256
    code_commit: sha
  env_manifest:                   # ⚠️ 见第8节: DL 非确定性 → 仅存 .pt+指纹不足以 bit 级复现
    gpu_cudnn: str
    lib_versions: {...}
    seeds: {...}
    mixed_precision: bool
  passport:                       # Mitchell 9节 骨架, 逐版本刷新, 漂移/重训时重填
    intended_use / limitations / oos_scheme / dsr_pbo / capacity_decay
    correlation / drift_thresholds / retirement_conditions
  lifecycle_stage: research | paper_shadow | small_capital | live
  promotion_history: [...]        # 闸控升级 + 回滚轨
```

**6.3 升级闸 + 独立性（概念伪代码）**

```python
def promote(model, signal, trial_count_N):       # trial_count_N: 全环路诚实计数 (含放弃配置)
    gates = [
        leak_free_walk_forward(signal),          # 焊成硬约束, 非可选
        deflated_sharpe(signal, N=trial_count_N), # 只与诚实的 N 一样可信
        pbo_cscv(signal),                         # ⚠️ 真实相关 OOS 上不是干净闸
        capacity_decay_corr(signal, asset="A股"), # A股容量不可从美国研究移植
    ]
    if any(g.failed for g in gates):
        return Verdict("BLOCK", gates)
    # ⚠️ 见第8节: 填护照的 agent 不得同时给护照签字 → 需独立闸,
    #   否则"生产信号的自动化又认证它"违背有效挑战
    return Verdict(stage_up(model.lifecycle_stage), gates)
```

**6.4 漂移监控 + 带滞回的退役（概念）**

```
PSI/KL on prediction-dist  → 低频小样本噪声大
  → 需阈值 + 滞回(hysteresis) + 对误报的治理, 否则自动停会抖动
连续 N 期越阈 → 触发再评估(非单期即停)
再评估节奏: 显式可配, 不硬编 "~12-24 月" (二手/部分撤稿来源, 见第7节)
退役条件 → 硬编进护照, 而非散落各处
```

---

## 7. 降权 / 争议 / 陷阱（对抗核查结论）

> 对抗核查总判：**核心架构论点稳健且有据**——两层（因子/特征库存定义+值；模型注册表存产物/护照/闸控）由稳定信号契约解耦、本体进注册表、输出登记为信号，正确锚定在 Qlib 因子-vs-模型边界、MLflow 闸控升级、Feast 特征库分离上；"把 `.pt` 当因子是范畴错误"是真洞。"统计闸优先于复杂度"（无泄露 walk-forward + DSR/PBO 当硬闸、按试验数 deflate）与对因子复现争议的平衡读法（统计性 gate、不选边）都可辩护、有据。已核实事实：Gu-Kelly-Xiu"浅层胜深层"准确、Mitchell Model Cards = 九节准确、DSR 被正确刻画为选择偏差/多重检验的"尺度校正"而非低估的修复、JKP 与 spurious-predictability preprint 存在且被诚实标注。**提案在审查下不崩。但携带若干须先降权再行动的夸大。**

**HIGH 严重度**

- ⚠️【日期失效 + 适用性过陈述，借了不适用制度的权威】**EU AI Act "自 2026-08-02 强制 Art.11/12/14、可作模型护照模板"被当成已定、迫近、适用的合规事实。** 两个问题：(1) **日期在变动中**——Council/Parliament 的 "Digital Omnibus" 协议（2026-05-07 达成）把独立的 Annex III 高风险义务**推迟到约 2027-12-02**；截至今日（2026-06）2026-08-02 这个日期**有争议/很可能已被取代**，非硬事实。(2) **相关性被过陈述**——Annex III 里**唯一**的金融条目是对自然人的信用度/信用评分（欺诈检测被豁免）；一个低频自营 A股/加密信号系统**几乎肯定不是该法案下的高风险系统**，故 Art.11-14 **不约束它**。把该法案当"合规模板"是**借了一个不适用于本系统的制度的权威**——恰是研究自身警告的"整套搬运重监管模板"陷阱。

**MEDIUM 严重度**

- ⚠️【二手 + preprint + 部分撤稿，被装成机构既定事实】**"衰减缩至 ~12-24 月 / 半衰期 ~12-24 月、拥挤时被套利掉"被当作信号生命周期的既定机构事实。** 所引仅是 **Substack 综述**，非实证文献；18 个月半衰期的唯一定量支撑来自 2026 arXiv preprint（2605.23905 AI 驱动衰减；以及 **2512.11913，本简报标记为 RETRACTED**）。经典因子衰减文献报告的半衰期**以年计、非 12-24 月**；12-24 这个数字**专门编码了未经审视的 AI 拥挤假说**。把它当固定节奏、并把"~12-24 月再评估"硬编进护照，是**对一个建立在非同行评审、部分撤稿 preprint 上的数字的过度承诺**。

- ⚠️【先例未被其所引来源支撑】**WorldQuant BRAIN "存信号抽象而非模型"被引为两层架构的 SOTA 先例。** 所引 URL（github.com/zhutoutoutousan/worldquant-miner）是**第三方 alpha 挖掘爬虫**，把 BRAIN API 当黑箱，**完全不记录 BRAIN 内部架构或任何"信号抽象 vs 模型"设计**。该架构主张是**貌似合理的行业传说，但所引来源不支撑**。两层论点靠 Qlib/MLflow/Feast **自身成立**，WorldQuant"先例"**无来源、不应倚重**。

**LOW 严重度**

- ⚠️【精度过陈述】**"~82% 因子可复现"被当成 JKP(2023) 的头条发现。** JKP 摘要/头条说的是"**大多数（the majority）因子可复现**"，不是精确 82%；82% 确在论文内出现，但是 **Chen-Zimmermann 预测变量在其门槛下的美国复现率的一个特定切口**，非论文头条，且复现率随定义/门槛/地区变。把精确数字当头条传达了**超出论文所声明的精度**——这是**精度/框架降权，非实质降权**。底层方向（因子大体可复现、当真争议处理）成立。

- ⚠️【显式性过陈述】**SR 11-7 —— "ML/AI 已在模型定义里"。** SR 11-7（2011）**早于 ML 时代、文本从未显式提 ML 或 AI**；其刻意宽泛的模型定义是**被解读**为覆盖 ML，是**后续**指引澄清适用于 AI。"2011 文本本身把 ML 纳入范围"的措辞**夸大了显式性**（精神上可辩护"全力适用"，字面上过陈述）。

- ⚠️【修辞类比、非架构先例 + 二手】**Alpha Capture / Marshall Wace 被引为 SOTA："2002 起成熟买方信号清册范式"。** TOPS / 2002 起源历史佐证充分，所引 SSRN（Mirlesse & Lhabitant, 2021）真实且切题——但它是 **2021 综述、非 2002 一手**；且 alpha capture（众包卖方交易想法）与"登记 ML 模型**输出**为信号"**只是修辞类比、非架构对应**。当背景色，**别当 model-output-as-signal 设计的直接先例**。

- ⚠️【跨域移植】**AI Model Passport（CSBJ 2025）被当作"生命周期框 / 护照 schema 蓝图"。** 论文真实，但**是健康/生物医学 AI 可追溯框架**（CSBJ = Computational and Structural Biotechnology Journal）。当量化交易护照蓝图是**跨域移植**——研究自身 pitfalls 警告的同一动作。可作**结构灵感**，不应当作"领域契合蓝图"。

- ⚠️【厂商营销页非权威出处】**champion-challenger / 影子部署引自 "Wallaroo, DataRobot, FICO"。** 实践是标准 MLOps、设计方向稳健，但引用是**厂商营销页、非一手或同行评审方法学**。当示例可，**不是"机构实践"主张的权威出处**。

**通用陷阱清单（设计须规避）**

- **把模型本体（`.pt`/`.pkl`、权重、架构）当一个因子塞进因子库 = 范畴错误**：因子库是因子**值**的记录系统；训练状态会把版本/血缘/重训强加于它、令其臃肿。本体属于模型注册表。
- **存了模型却不留信号契约指纹** → 漂移时既无法复现信号、也无法定位责任模型；"流程即信任"断裂。
- **把 DSR/PBO/无泄露 walk-forward 当可选而非硬升级闸** → DL/ML 大搜索过拟合；不按试验数 deflate Sharpe = 把选择偏差当 alpha 出货。
- **CV 与特征工程里的前视泄露**：时序上做随机 K-fold、用未来样本归一化、label/feature 窗口重叠，都制造伪可预测性。
- **以为更深更好** → Gu-Kelly-Xiu 显示浅层（约 3 层）达峰；低频小样本上深网通常样本外更差。
- **在因子复现争议里选任一极端**（全噪声 vs ~82% 可复现）→ 用统一统计闸，别预设结论。
- **忽视信号衰减与拥挤** → 拥挤时被套利掉；无再评估节奏会累积死信号。⚠️ 但**再评估节奏别锚到 12-24 月这个二手/部分撤稿数字**（见上）。
- **整套搬运银行/医疗重监管模板** → 低频自营/paper 语境是不同风险类；裁剪，别移植。EU AI Act（很可能不适用 + 日期失效）、SR 11-7（早于 ML、显式性弱）、CSBJ AIPassport（健康域）都属此类。
- **把模型护照写成一次性静态文档** → 必须逐版本、且在漂移/重训时刷新，否则误导。

---

## 8. 开放问题

> 以下为对抗核查指出的**漏点（missing angles）**，研究稿完全缺席或仅一句带过，是落地前必须回答的。

1. **单用户系统（D4）的成本/复杂度 vs 回报未问。** 立起 MLflow + W&B + Feast/Tecton + CycloneDX ML-BOM + NIST AI RMF + SR 11-7 有效挑战是**企业级治理机器**。研究从未问一个单用户 A股→paper / 加密→Binance 配置是否**需要（或能维护）**这一切，也没提**最小可行子集**。**有把治理栈做得比它治理的交易系统还重之险。**

2. **最难的是信号契约语义，不是存储拆分——而它被欠规定。** PIT 正确性、shift/embargo 约定、label/feature 窗口重叠、公司行动/幸存者处理、以及**精确的"输出指纹"哈希（哈希哪些输入、数据修订如何令其失效）**——泄露真正发生处。研究断言"v3 `backtest_bridge` 输出 IS 这份契约"，**却未审计该 bridge 是否已强制这些**，是个**未验证的假设**。

3. **谁/什么执行闸，以及 agent 自我评分的利益冲突。** "agent 自动填护照"+"审计 agent 仅凭护照判信任"造成一个环路：**产出信号的同一自动化又给它认证**。SR 11-7 的全部要义是**独立有效挑战**；一个被 agent 评分的自动填护照**不是独立的**。**未提供职责分离设计。**

4. **DSR/PBO 试验计数核算在操作上很难、未处理。** "按试验数 deflate"要求诚实地数**全部**试验（含放弃的配置、超参扫描、特征实验）——多数团队**重建不出的数字**。没有跨整个研究环路记录真实试验数的机制，DSR 是剧场。且 CSCV/PBO 有**已记录弱点**（相关 OOS 折叠抬高其评估质量），仅在合成/受控设定下明显优于 walk-forward——研究把 PBO 当干净闸了。

5. **A股专属容量/流动性。** A股微结构（T+1、10% 涨跌停板锁、停牌、散户主导流）实质影响可实现容量与衰减，与 Gu-Kelly-Xiu 和因子复现文献所建的美股语境**显著不同**。"资产无关"框架略过了这点；**容量/衰减阈值不可从美国研究移植。**

6. **DL 产物的可复现性比"存 `.pt`+指纹"难得多。** 非确定性（GPU/cuDNN、seed、库版本、混合精度）意味着存下的 checkpoint **可能无法 bit 级复现已登记信号**。护照需**环境/确定性清单**，不只是模型版本反向引用——未提及（已在第 6.2 节 `env_manifest` 字段补上）。

7. **漂移监控误报与 D3 自动停的交互。** 低频小样本下预测分布上的 PSI/KL **噪声大**；自动规则停若接在噪声漂移信号上会**抖动、或在最坏时点 de-risk**。**未讨论阈值、滞回（hysteresis）、或如何对误报治理自动退役**（已在第 6.4 节以滞回 + 连续越阈补上概念）。

8. **引用集自身的幸存者偏差。** 几乎所有"ML 有用"证据（Gu-Kelly-Xiu、JKP）是**美国大盘已发表研究、受自身发表偏差影响**；研究靠它证成 ML-in-the-loop，**同时又引 López de Prado 称多数 ML 基金失败**。"工业化 ML 信号生产"与"ML 失败是常态"这对张力**只被修辞承认、未解成具体 go/no-go 门槛**。

---

## 9. 参考文献（URL）

**架构 / MLOps 平台**
- Microsoft Qlib（因子定义 + Model Zoo + qrun）— https://github.com/microsoft/qlib
- MLflow Model Registry — https://mlflow.org/docs/latest/ml/model-registry/
- MLflow Model Registry workflow（闸控升级）— https://mlflow.org/docs/latest/ml/model-registry/workflow/
- Weights & Biases Registry — https://docs.wandb.ai/models/registry
- Feast（开源特征库）— https://github.com/feast-dev/feast
- Feature store / FTI 管线对比（2026）— https://mlopsplatforms.com/posts/feature-store-comparison-2026/
- WorldQuant BRAIN 第三方爬虫（⚠️ 不记录 BRAIN 架构，见第 7 节）— https://github.com/zhutoutoutousan/worldquant-miner

**护照 / 文档产物 / 标准**
- Mitchell et al., Model Cards for Model Reporting（arXiv:1810.03993）— https://arxiv.org/pdf/1810.03993
- AI Model Passport（CSBJ 2025, ⚠️ 健康域，见第 3/7 节）— https://www.sciencedirect.com/science/article/pii/S2001037025004015
- CycloneDX ML-BOM — https://cyclonedx.org/capabilities/mlbom/
- US Fed/OCC SR 11-7（⚠️ 显式性弱，见第 4/7 节）— https://www.federalreserve.gov/supervisionreg/srletters/sr1107.htm
- NIST AI RMF 1.0 Core（Govern/Map/Measure/Manage）— https://airc.nist.gov/airmf-resources/airmf/5-sec-core/

**统计闸 / 因子复现 / ML 资产定价**
- Bailey, Borwein, López de Prado & Zhu, The Probability of Backtest Overfitting (PBO/CSCV) — https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2326253
- López de Prado, The 10 Reasons Most ML Funds Fail（2018）— https://papers.ssrn.com/sol3/papers.cfm?abstract_id=3104816
- Gu, Kelly & Xiu, Empirical Asset Pricing via Machine Learning（NBER w25398）— https://www.nber.org/system/files/working_papers/w25398/w25398.pdf
- Jensen, Kelly & Pedersen, Is There a Replication Crisis in Finance?（JoF 2023）— https://onlinelibrary.wiley.com/doi/full/10.1111/jofi.13249
- Spurious Predictability in Financial ML（2026 preprint, ⚠️ 二手/preprint）— https://arxiv.org/html/2604.15531v1

**实践示例（⚠️ 厂商页 / 综述，非权威出处）**
- champion-challenger / shadow（Wallaroo）— https://wallaroo.ai/ai-production-experiments-the-art-of-a-b-testing-and-shadow-deployments/
- 量化信号生命周期综述（Substack, ⚠️ 二手）— https://youngandcalculated.substack.com/p/how-quant-hedge-funds-actually-build
- Alpha Capture Systems: Past, Present, and Future（Mirlesse & Lhabitant, 2021, ⚠️ 综述/修辞类比）— https://papers.ssrn.com/sol3/papers.cfm?abstract_id=3873884
- 漂移监控（Evidently AI）— https://www.evidentlyai.com/ml-in-production/data-drift

**对抗核查标注的争议 / 撤稿 / 失效**
- arXiv 2512.11913（⚠️ flagged-RETRACTED；勿用作 12-24 月衰减证据）— https://arxiv.org/pdf/2512.11913
- EU AI Act Omnibus 推迟高风险至 ~2027-12（Gibson Dunn, ⚠️ contested-superseded）— https://www.gibsondunn.com/eu-ai-act-omnibus-agreement-postponed-high-risk-deadlines-and-other-key-changes/
