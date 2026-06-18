# 12 · 验证官：独立验证 / 有效挑战（SR 11-7）

> 机构级 Agent OS 成品环节深挖 · 全程 Opus 4.8 · 对抗式核查已降权 · 重心=前沿研究+概念级推荐 · 不含 file:line 代码接线
> 簇 B

## 1. 一句话定位

验证官是整个 Agent OS 的**信任脊柱**：一个与研究/生成 agent **硬隔离、有权 block** 的独立有效挑战者（effective challenger）——LLM 只负责"对抗式挑战与漏洞发现"，所有 go/no-go 数值裁决交给确定性统计闸（PBO/CSCV、Deflated Sharpe、forking-paths 门槛），让每次否决都可复算、可审计、可对小白解释。

---

## 2. 前沿 SOTA 与代表系统

| 系统 / 范式 | 它是什么 · 对本环节意味着什么 | URL |
|---|---|---|
| **SR 26-2 Interagency Model Risk Management Guidance**（Fed/OCC/FDIC, 2026-04-17） | SR 11-7 的现行继任者。保留 effective challenge 与验证独立性为**原则**，但改为风险分级/比例原则（"模型用途×模型敞口=模型重要性"），只对 material 模型要求更严格独立验证；"独立"措辞演进为 *sufficient independence to maintain objectivity*。**明确把生成式/agentic AI 排除适用范围**（视为新颖快速演进）。对本环节=把它当"分级+客观性"现代化补丁，但 LLM 验证仍需自建标准。 | https://www.federalreserve.gov/supervisionreg/srletters/SR2602.htm |
| **Champion/Challenger model governance**（FICO 等决策管理实践） | 金融业成熟范式：现役 champion 与多个 challenger 在同一进流数据上并行评测，challenger 持续胜出才替换。可直接映射为"现役策略 vs 候选策略"的影子运行 + 统一指标对比，是验证官"有权 block 升级"的工业化载体。 | https://www.fico.com/blogs/benefits-championchallenger-testing-decision-management |
| **NIST AI RMF 1.0 + TEVV/ARIA（Measure 功能）** | 美国 AI 风险框架，把 Test-Evaluation-Verification-Validation 与独立/第三方评估、红队作为 Measure 功能核心；高影响用例建议独立复核。给**非银行场景**的"独立验证"提供资产无关、可对外解释的话术与结构。 | https://www.nist.gov/ai-test-evaluation-validation-and-verification-tevv |
| **LLM Jury / panel-of-judges + Jury-on-Demand（可靠性加权自适应陪审团）** | 用多模型陪审替代单一 judge；前沿做法是按每个 judge 在该实例上的预测可靠性**动态加权**（Jury-on-Demand），并强调跨家族（Anthropic/OpenAI/Google）混合以抵消各家系统性怪癖。是 cross-provider verifier 的直接 SOTA 落点。 | https://arxiv.org/pdf/2512.01786 |
| **Open Source Asset Pricing（Chen-Zimmermann）+ Deflated Sharpe Ratio 工具线** | 独立再现的"金标准"参照：提供数据+代码可复现近全部横截面预测因子；配合 DSR/PBO 作为统计闸。示范了"验证=可复算的独立再现+多重检验折扣"，而非主观打分。 | https://www.openassetpricing.com/ |

---

## 3. 关键论文（每条带 URL）

1. **... and the Cross-Section of Expected Returns**（Harvey, Liu, Zhu, RFS 2016 / NBER w20592）
   对约 296 个已发表因子做多重检验，主张新因子需 **t>3.0**（而非常规 2.0）；按聚合数据窥探校正，约 1/3 到 1/2 的已发表因子可能是假阳性。给验证官提供"抬高显著性门槛以对抗数据挖掘"的数值依据。
   ⚠️ **核查更正**：研究稿原写"316 个里仅约 9 个幸存"是**数量级级别的事实错误**——HLZ 的实际结论是约 148–197 个"幸存"（即假阳性比例约 1/3–1/2），不是 9 个。下文第 7 节详述。
   https://www.nber.org/system/files/working_papers/w20592/w20592.pdf

2. **Do t-Statistic Hurdles Need to Be Raised?**（Chen, Management Science；及 Publication Bias 系列 / Chen-Zimmermann）
   **对 HLZ 的直接学术对立**：由于未达门槛的结果不可观测、需外推，修订后的 t 门槛是"弱识别（weakly identified）"的；并给出 t 门槛为 0 时 FDR 仅约 12%、门槛 1.8 即可控制多重检验。Open Source Asset Pricing 显示"对原文显著的特征，约 98% 可复现 t>1.96"——**关键在先严格归类原文显著性再复现**，提示验证官的正确动作是独立再现（replicate）而非简单再跑或一票否决。
   https://www.openassetpricing.com/

3. **The Probability of Backtest Overfitting**（Bailey, Borwein, López de Prado, Zhu, 2015）
   提出 PBO 与组合对称交叉验证（CSCV）：model-free、非参数地估计某回测过拟合的概率；指出标准 hold-out 在回测语境下不可靠。是验证官"独立切片复算"的方法论核心。
   https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2326253

4. **The Deflated Sharpe Ratio**（Bailey & López de Prado, 2014）
   对选择偏差 + 非正态校正 Sharpe：用有效独立试验数 N=ρ+(1−ρ)M（经聚类估 ρ）折扣业绩。Sharpe 1.0 但试了 100 次 < Sharpe 0.6 但几乎没调参。验证官应**索取"试了多少次"并据此折扣**。
   https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2460551

5. **Forking Paths in Financial Economics**（Coqueret, 2024）
   研究者自由度（"garden of forking paths"）每多一个，t 统计平均区间扩 ≥30%；在分叉路径下异象显著门槛抬到 ≥8.2（远高于 bootstrap 的 4.5）。支撑"验证官必须考察整条 multiverse，而非单一 winner 路径"。
   https://arxiv.org/abs/2401.08606

6. **LLM Evaluators Recognize and Favor Their Own Generations**（Panickssery, Bowman, Feng, NeurIPS 2024）
   LLM 能以非平凡准确率识别自己的输出；自我识别能力与自我偏好偏差强度呈线性相关。
   ⚠️ **核查限定**：该线性关系是通过**微调人为放大**自我识别后才观测到，并非开箱即用的自然强相关；原文同时指出"much of this self-preference aligns with objectively superior performance"——部分自我偏好其实是真实质量差异而非偏差。结论方向（异模型更稳妥）仍成立，但**证据强度被研究稿夸大**。
   https://proceedings.neurips.cc/paper_files/paper/2024/hash/7f1f0218e45f5414c79c0679633e47bc-Abstract-Conference.html

7. **LLM Judges Are Unreliable**（Collective Intelligence Project, blog 2025）
   实测多种脆弱性：8 模型偏好"Response B"约 61%；同内容 1–5 量表均分 1.68 vs A–E 量表 3.17（差 89%）；模糊样本改模板 100% 翻转分类；ELO 排名随提示模板大幅重排。明确警告"共享系统性偏差的集成会放大而非抵消"。
   ⚠️ **核查限定**：数字与原文相符，但**属 blog 等级证据**，多数实验未充分披露样本量（文中自陈"限制了可复现性评估"）；方向可信，把单一未充分披露样本量的 blog 数字当"实测铁证"属于**轻度夸大**。
   https://www.cip.org/blog/llm-judges-are-unreliable

8. **Judging with Many Minds: Bias Amplification vs Resistance in Multi-Agent LLM-as-Judge**（EMNLP'25 Findings, arXiv:2505.19477）
   多 agent 辩论在首轮后会急剧放大 position/verbosity/CoT/bandwagon 四类偏差并持续；meta-judge 比 debate 更稳健。约束了"多 agent=更可靠"的天真假设。
   ⚠️ **核查限定**："Condorcet 独立性崩塌 / 共享预训练流形导致相关误差"是研究稿自加的**理论诠释 gloss**，不是该论文用实验证明的核心机制——属**轻度过度归因**（结论稳健，归因来源被拔高）。
   https://arxiv.org/pdf/2505.19477

9. **Shrinking the Generation-Verification Gap with Weak Verifiers (Weaver)**（Stanford Scaling Intelligence, arXiv:2506.18203）
   验证比生成更容易（不对称）是 verifier 价值来源；单个弱验证器噪声/有偏，需用弱监督式加权组合多个弱验证器、估计各自潜在可靠性来逼近强验证。
   ⚠️ **核查限定**：结果在 MATH500/GPQA Diamond/MMLU-Pro 等**有可验证标准答案的封闭推理任务**上取得，其不对称性高度依赖"存在 ground-truth 可对照"；金融策略验证恰恰**没有即时 ground-truth**（真实盈亏要等未来且被市场反身性污染）——属**未经验证的跨域外推**，须打证据等级标签。
   https://scalingintelligence.stanford.edu/pubs/weaver.pdf

---

## 4. 机构最佳实践 / 标准

- **Effective challenge（有效挑战）**：独立、有专业能力与组织权威、能对结果产生实际影响的批判性复核——而非橡皮图章。验证者与开发者无汇报关系。这是 SR 11-7 的"指导性原则"。
  来源：SR 11-7 Supervisory Guidance on Model Risk Management（Fed/OCC, 2011） — https://www.federalreserve.gov/supervisionreg/srletters/sr1107.htm
  ⚠️ **核查更正**：研究稿称 SR 11-7 把"验证者薪酬与验证质量挂钩"列为**强制机制**——**这是杜撰**。SR 11-7 仅把 *incentives / competence / influence* 列为支撑 effective challenge 的**软性因素**，从未把薪酬挂钩规定为强制条款。

- **风险分级/比例原则**："模型用途×模型敞口=模型重要性"；immaterial 模型仅需识别+监控，material 模型才需更全面严格的独立验证。把验证强度按风险伸缩，而非一刀切。
  来源：SR 26-2 Revised Interagency Guidance（2026-04-17）— https://www.sullcrom.com/insights/memo/2026/April/OCC-Fed-FDIC-Issue-Revised-Guidance-Model-Risk-Management

- **独立性现代化**：SR 26-2 把"独立"措辞演进为 *appropriate expertise + sufficient independence to permit objectivity + organizational standing/influence*，并明确把生成式/agentic AI 排除适用范围——**监管不提供 LLM 验证现成处方，需机构自建**。这是表述演进，**不是**废除某个薪酬强制机制（见上）。
  来源：Sia Partners / Baker Tilly SR 11-7 vs SR 26-2 对比 — https://www.sia-partners.com/en/insights/publications/sr-11-7-vs-sr-26-2-model-risk-management-modernization

- **TEVV + 独立/第三方评估 + 红队**：把测试-评估-验证-确认作为 AI 生命周期 Measure 功能；高影响用例建议独立复核与对抗性红队。资产无关、可对外解释。
  来源：NIST AI RMF 1.0（NIST AI 100-1）+ CISA AI Red Teaming as TEVV — https://nvlpubs.nist.gov/nistpubs/ai/nist.ai.100-1.pdf

- **计算可复现性最低要件**：超参数、预处理流水线、数据版本、模型检查点、软件栈、硬件配置全部记录，使独立方能脱离原始基础设施重新执行并核验（MLflow/ModelDB/PROV 等 lineage 工具）。
  来源：ML in Production (CMU) — Versioning, Provenance, and Reproducibility — https://mlip-cmu.github.io/book/24-versioning-provenance-and-reproducibility.html

---

## 5. 对 QuantBT 这套架构的推荐方向（概念级）

> 仅概念级方向，不点 file:line、不排实施计划。

1. **验证官 = 硬隔离的独立角色，而非生成 agent 的一个 self-check 步骤。**
   不同模型 + 不同供应商/家族 + 不同随机种子 + 不同数据切片（OOS / 时间后段 / walk-forward），并**禁止 verifier 看到 generator 的中间推理与提示**，以保留"验证比生成易"的不对称优势。

2. **分工铁律：LLM 只做"对抗式挑战与漏洞发现"，数值裁决交给确定性统计闸。**
   LLM 负责质疑假设、找数据泄露、提反例、问"你试了多少次"；所有 go/no-go 由 PBO/CSCV、Deflated Sharpe、forking-paths 门槛、t>3 类硬阈裁决，让流程可复算、可审计、可对小白解释。
   ⚠️ 注意 t>3 是**有学术争议的一方主张**（HLZ↔Chen 对立），见第 7 节——不应作为"客观真理"硬编码，宜可配置并标注立场。

3. **用 SR 11-7 的 effective challenge 当信任脊柱原则、SR 26-2 的"用途×敞口=重要性"当分级旋钮。**
   低风险（A股 paper）走轻量验证；高风险（Binance 实盘）触发最严格独立再现 + 多重检验折扣 + 实盘前 champion/challenger 影子运行。验证强度随真金白银伸缩。

4. **若用多模型陪审，默认跨家族 + 可靠性加权（Jury-on-Demand 思路），并显式监控 inter-judge 方差与相关性。**
   警惕同源集成放大偏差，把"是否独立"当成**可度量量**而非假设。

5. **把"独立再现"做成一等公民。**
   verifier 在异基础设施上凭 provenance（数据版本/超参/种子/软件栈）重算净值，与 generator 结果对账；对不齐即 block。借鉴 OSAP 的"先严格归类再复现"纪律，避免把"未对齐"与"真失效"混为一谈。
   ⚠️ 需配套**容差阈值与对账口径**，区分浮点/库版本/数据快照差异这类"实现差异"与真正的"策略失效"（见第 8 节开放问题）。

6. **验证官的否决必须可问责。**
   输出结构化拒绝理由（触发了哪条闸、哪个切片/种子失败、选择偏差折扣后的有效显著性），并提供向人类经济判断升级的申诉通道——把"流程即信任"落到"每个 block 都能被复算和质询"。

7. **对 LLM 评判结果做去脆弱化。**
   固定/中性化标签与量表、用 pointwise 而非 pairwise、对提示模板做敏感性自检，把"同一判断在扰动下是否稳定"作为验证官自身的**元质量门（meta-judge）**，不稳定即降权或转人工。

---

## 6. 架构级参考（少量伪代码 / schema 草图，非代码接线）

> 示意草图，不接线到现有代码。

**6.1 验证裁决 schema（结构化、可复算、可申诉）**

```yaml
verdict:
  candidate_id: str
  decision: PASS | BLOCK | ESCALATE        # 三态，非二元
  materiality: low | medium | high          # SR 26-2 风格：用途×敞口
  deterministic_gates:                       # 数值裁决=确定性代码，非 LLM
    - gate: PBO_CSCV
      value: 0.42
      threshold: 0.50
      pass: true
    - gate: DeflatedSharpe
      value: 0.31
      n_effective_trials: 87                 # "你试了多少次"必填
      pass: false                            # ← 触发 BLOCK 的具体闸
    - gate: forking_paths_t
      observed_t: 2.9
      threshold: 8.2                          # Coqueret 分叉路径门槛
      pass: false
    - gate: independent_replication
      netval_mismatch_bps: 140
      tolerance_bps: 50                       # 容差口径需显式定义
      pass: false
  llm_challenges:                            # LLM 仅产出"挑战/漏洞"，不打分
    - "训练窗与回测窗在 2023Q4 有 11 天重叠，疑似前视泄露"
    - "动量信号未做 T+1 / 涨跌停可成交性校验（A股特殊性）"
  appeal_channel: human_economic_review       # 升级通道
  reproducible: true                          # 拒绝依据可被独立复算
```

**6.2 跨供应商陪审 + 可靠性加权（概念伪代码）**

```python
def jury_challenge(candidate, jurors):       # jurors 跨家族、异种子、异切片
    challenges = []
    for j in jurors:                          # 禁止 juror 看 generator 推理
        c = j.find_holes(candidate.public_artifacts_only)
        w = reliability_weight(j, candidate)  # Jury-on-Demand: 实例级加权
        challenges.append((c, w))
    # 关键: LLM 只聚合"挑战/质疑", 不聚合"分数"
    inter_juror_corr = measure_correlation(challenges)  # 同源放大偏差预警
    if inter_juror_corr > CORR_CEILING:
        flag("陪审独立性不足, 误差相关——降权或换家族")
    return dedup_and_rank(challenges)         # 交确定性闸去裁决数值
```

**6.3 分级旋钮（按 materiality 伸缩验证强度）**

```
A股 paper (low)      → 轻量: 单 OOS 切片 + PBO 闸
Binance 实盘 (high)  → 完整: 跨供应商陪审 + walk-forward 多切片
                       + DSR/forking-paths 折扣 + 独立再现对账
                       + 上线前 champion/challenger 影子运行
```

---

## 7. 降权 / 争议 / 陷阱（对抗核查结论）

> 对抗核查总判：**总体可信但有若干硬伤**。监管层（SR 11-7/SR 26-2）、LLM-judge 不可靠（Panickssery/CIP/2505.19477/Weaver/Jury-on-Demand）、统计闸（PBO/DSR/Coqueret 8.2）等论断的存在性与大方向**基本属实**，URL 与 arXiv ID 多数可核验（2512.01786 不是已撤稿的 2512.11913）。但研究在三类上**系统性夸大**。**设计方向（异模型/异供应商/确定性裁决/可问责 block）本身稳健，不受这些 downgrade 动摇。**

**HIGH 严重度**

- ⚠️【事实错误，差约一个数量级】**Harvey-Liu-Zhu「316 因子中按 t>3.0 仅约 9 个幸存」**——HLZ(2016) 实际说的是：对约 296 个已发表因子，按聚合数据窥探校正后约有 1/3 到 1/2 是假阳性（即约 148–197 个"幸存"），而非 9 个。"9"疑似把"随机预期约 16 个偶然显著"之类记串。这是全篇最严重的硬性数据错误，已在第 3 节论文 1 更正。

- ⚠️【自相矛盾的引用 / 学术对立被包装成互补】**把 HLZ「t>3.0 硬门槛」与 Chen-Zimmermann「98% 可复现」并列为相互补充**——二者在学术上是**对立而非互补**。Chen（*Do t-Statistic Hurdles Need to Be Raised?*）明确论证：修订后的 t 门槛是**弱识别（weakly identified）**的，门槛 0 时 FDR 仅约 12%、门槛 1.8 即可控多重检验——这是直接**反对** HLZ 抬到 3.0 的核心主张。研究稿把两篇当"一个给硬阈、一个给安抚"使用，**掩盖了"门槛该不该抬根本没有共识"这一关键争议**。验证官若照搬 t>3 硬阈，等于站队一方而不自知。

**MEDIUM 严重度**

- ⚠️【二手数字 + 量级与性质双重夸大】**「90%+ 学术策略实盘失效」是验证官存在的根本理由**——虽然研究稿加了"应标注为业界常引、非严格统计"的 hedge（值得肯定），但仍把这个未经证实的二手数字放在论证主导位置。真正可核验的一手证据（McLean-Pontiff 2016, 97 个预测器）给出的是 post-sample 约 26%、post-publication 约 58% 的**收益衰减**，而非 90% 的**完全失效**；其中相当一部分被解释为发表后投资者学习/套利，而非纯粹过拟合假阳性。把"50–58% 衰减"升级成"90% 失效"在**量级与性质（衰减≠失效）上都夸大**。

- ⚠️【杜撰具体性】**SR 26-2 把 SR 11-7「把验证者薪酬与验证质量挂钩的强制机制」放宽**——SR 11-7 中**并不存在**这一强制机制。它仅把 incentives/competence/influence 列为软性因素。研究稿为凸显 SR 26-2"放宽了什么"，给 SR 11-7 安了一个具体而虚构的硬性条款。已在第 4 节更正。

- ⚠️【裁剪关键限定，证据强度被夸大】**Panickssery「自我识别与自我偏好线性相关」⇒「生成 agent 不能当自己的 verifier」**——裁剪了原文限定：(1) 该线性关系是经**微调人为放大**自我识别后才观测到，并非开箱即用的自然强相关；(2) 原文同时指出"much of this self-preference aligns with objectively superior performance"——部分自我偏好其实是真实质量差异而非偏差。研究只取"自偏=偏差"的一半。**结论方向（异模型更稳妥）仍成立**，但证据强度被夸大。

- ⚠️【过度外推域，未经验证的跨域外推】**Weaver 弱验证器加权聚合被列为金融策略验证的 SOTA 落点**——Weaver(arXiv:2506.18203) 的结果在 MATH500/GPQA Diamond/MMLU-Pro 等**有可验证标准答案的封闭推理任务**上取得；其"验证比生成易"的不对称性高度依赖"存在 ground-truth 可对照"。金融策略验证恰恰**没有即时 ground-truth**（真实盈亏要等未来、且被市场反身性污染）。把封闭推理域结论平移到开放、无标签、非平稳的金融策略验证，是**未经验证的跨域外推**，研究稿未对此域差异作任何标注。

**LOW 严重度**

- ⚠️【blog 等级证据当同行评审硬事实，未做证据分级】**CIP「LLM Judges Are Unreliable」精确数字（61% 偏好 B、1.68 vs 3.17 差 89%、100% 翻转）被当稳健事实**——数字与原文相符，但 CIP 文章**未充分披露多数实验样本量**（文中自陈"限制了可复现性评估"）。方向可信，把单一未充分披露样本量的 blog 数字当"实测铁证"属**轻度夸大**。

- ⚠️【过度归因，诠释性 gloss 写成实证结论】**多 agent 辩论「Condorcet 独立性崩塌」「共享预训练流形使误差相关」被陈述为 arXiv:2505.19477 的已证机制**——该论文实测的是 debate 放大 position/verbosity/CoT/bandwagon 四类偏差、meta-judge 更稳健（这部分属实）。但"Condorcet 独立性崩塌""共享预训练流形导致相关误差"是研究自己加的**理论诠释/话术**，并非该论文用实验证明的核心机制。属**轻度过度归因**（结论稳健，归因来源被拔高）。

**通用陷阱清单（设计须规避）**

- 把生成 agent 当自己的 verifier → 必须异模型、最好异供应商/异家族。
- 以为"多 agent 辩论/陪审一定更可靠" → 同源模型误差相关，辩论会在首轮后放大偏差；共享系统性偏差的集成放大而非抵消。
- 让 LLM 直接给数值结论/最终评分 → 提示词脆弱、位置偏差、verbosity/格式偏差；数值裁决交确定性代码。
- 把"再跑一遍"当"独立验证" → 真正的有效挑战是独立再现（异切片/异种子/异实现）+ 多重检验折扣。
- 忽视"试了多少次" → 不对 forking-paths/选择偏差折扣会系统性高估。
- 盲信"90% 失效"这类二手数字 → 要标注证据等级；同时 Chen-Zimmermann 表明"大多数异象其实能复现"。
- 误把 SR 26-2 当成放松 → 它把生成式/agentic AI 排除适用范围，意味着监管不给 LLM 验证现成处方；照搬只会留下治理真空。
- verifier 与 generator 信息/工具对称会抹掉验证优势 → 刻意给 verifier 独立工具（可执行代码、独立数据、独立切片）。
- "有权 block"若无升级/申诉与可解释理由 → 沦为不可问责黑箱否决；需记录可复算的拒绝依据。

---

## 8. 开放问题

> 以下为对抗核查指出的**漏点（missing angles）**，研究稿完全缺席或仅一句带过，是落地前必须回答的。

1. **成本/延迟与算力预算完全缺席。** cross-provider jury + 可靠性加权 + verifier 独立重算净值，意味着每个候选策略要在多家供应商、多种子、多切片上重跑——对单用户（D4）项目是显著的 API 成本与时延负担。研究只谈"更可靠"，未给任何成本-收益或"何时该退化为轻量验证"的工程权衡。

2. **验证官自身的对抗鲁棒性/被博弈风险未触及。** 一旦 generator（或人类用户）知道验证官跑的是 PBO/DSR/t>3/forking-paths 这套确定性闸，就能反向优化策略去专门通过这些闸（**Goodhart 定律 / 闸门套利**）。把数值裁决固定为公开的确定性规则，反而创造了被精准规避的攻击面——研究把"确定性可复算"只当优点，未讨论其可被博弈的反面。

3. **A股市场的制度性特殊性被整套美式框架忽略。** T+1、涨跌停板、停牌、卖空与融券限制、散户主导的非平稳性，会使 PBO/CSCV（依赖可自由重排的 IS/OOS 组合）和 walk-forward 的独立性假设失真。研究把 Chen-Zimmermann（美股横截面）、HLZ（美股因子）、SR 11-7（美国银行）整套搬来，未讨论这些工具在 A股 paper 场景的**适用性边界**。

4. **DSR/PBO 自身的已知局限未作为风险列出。** DSR 依赖对 SR 零分布的形式假设、需人为选定有效独立试验数 N（经聚类估 ρ，主观性强）、且只在收益接近 i.i.d. 时校正可靠；PBO/CSCV 的优越性在多数文献中是在**合成/受控环境**里相对 walk-forward 显著，真实非平稳数据上的优势要弱得多。研究把它们当"金标准统计闸"，却未给它们自己的失效模式和参数敏感性加任何警示。

5. **「验证官有权 block」的治理闭环只做了一半。** 研究提了申诉/升级通道，但没处理 verifier 与 generator 的 **OODA 死锁**（verifier 一直 block、generator 一直改，如何收敛？谁拍最终板？）、也没处理 verifier 自身出错（假阳性 block 掉真有效策略）的纠错与问责机制。把信任全押在 verifier 上，却没给它设 meta-验证/人类兜底的具体停损规则。

6. **实盘场景（Binance live）下「验证通过≠上线后仍有效」的持续监控缺位。** champion/challenger 影子运行被提及但只当"上线前"闸；研究未覆盖上线后的实时漂移检测、何时触发自动降级/停机（这恰是用户 D3 拍板的"实盘 agent 仅警告+规则停"核心）。验证官与运行时风控的接力**没接上**。

7. **数据/复现的现实摩擦未量化。** "异基础设施按 provenance 重算净值并对账，对不齐即 block"听起来干净，但浮点不确定性、库版本差异、数据供应商（Tushare 限流 vs Binance）快照不一致，会导致大量"非真失效"的对不齐。研究虽在 pitfall 里提了一句"别把未对齐与真失效混为一谈"，却没给**容差阈值、对账口径**或如何区分"实现差异"与"策略失效"的可操作标准。

---

## 9. 参考文献（URL）

**监管 / 标准**
- SR 26-2 Interagency Model Risk Management Guidance（Fed/OCC/FDIC, 2026-04-17）— https://www.federalreserve.gov/supervisionreg/srletters/SR2602.htm
- SR 11-7 Supervisory Guidance on Model Risk Management（Fed/OCC, 2011）— https://www.federalreserve.gov/supervisionreg/srletters/sr1107.htm
- SR 11-7 vs SR 26-2 Modernization（Sia Partners）— https://www.sia-partners.com/en/insights/publications/sr-11-7-vs-sr-26-2-model-risk-management-modernization
- OCC/Fed/FDIC Revised Guidance 分析（Sullivan & Cromwell）— https://www.sullcrom.com/insights/memo/2026/April/OCC-Fed-FDIC-Issue-Revised-Guidance-Model-Risk-Management
- NIST AI RMF 1.0（NIST AI 100-1）— https://nvlpubs.nist.gov/nistpubs/ai/nist.ai.100-1.pdf
- NIST TEVV — https://www.nist.gov/ai-test-evaluation-validation-and-verification-tevv

**复现危机 / 统计闸**
- Harvey, Liu & Zhu (2016), ... and the Cross-Section of Expected Returns — https://www.nber.org/system/files/working_papers/w20592/w20592.pdf
- Open Source Asset Pricing（Chen & Zimmermann）— https://www.openassetpricing.com/
- Bailey et al. (2015), The Probability of Backtest Overfitting (PBO/CSCV) — https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2326253
- Bailey & López de Prado (2014), The Deflated Sharpe Ratio — https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2460551
- Coqueret (2024), Forking Paths in Financial Economics — https://arxiv.org/abs/2401.08606
- Deflated Sharpe Ratio（概念参考）— https://en.wikipedia.org/wiki/Deflated_Sharpe_ratio
- pbo（CSCV 的 R 实现）— https://github.com/mrbcuda/pbo

**LLM-as-judge / verifier 可靠性**
- Panickssery, Bowman & Feng (2024, NeurIPS), LLM Evaluators Recognize and Favor Their Own Generations — https://proceedings.neurips.cc/paper_files/paper/2024/hash/7f1f0218e45f5414c79c0679633e47bc-Abstract-Conference.html
- Collective Intelligence Project, LLM Judges Are Unreliable — https://www.cip.org/blog/llm-judges-are-unreliable
- Judging with Many Minds（arXiv:2505.19477）— https://arxiv.org/pdf/2505.19477
- Weaver — Shrinking the Generation-Verification Gap（arXiv:2506.18203）— https://scalingintelligence.stanford.edu/pubs/weaver.pdf
- LLM Jury / Jury-on-Demand（arXiv:2512.01786）— https://arxiv.org/pdf/2512.01786

**工业范式 / 工程**
- Champion/Challenger testing（FICO）— https://www.fico.com/blogs/benefits-championchallenger-testing-decision-management
- Versioning, Provenance & Reproducibility（CMU ML in Production）— https://mlip-cmu.github.io/book/24-versioning-provenance-and-reproducibility.html
