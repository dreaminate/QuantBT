# 34 · 文献→策略抽取（RAG/引用锚定/防摄入注入/复现已发表异象）

> 机构级 Agent OS 成品环节深挖 · 全程 Opus 4.8 · 对抗式核查已降权 · 重心=前沿研究+概念级推荐 · 不含 file:line 代码接线
> 簇 F

## 1. 一句话定位

用户上传论文/笔记/网页后，系统在治理流水线下抽取出**逐字段带证据锚点（exact source span + doc id + page/paragraph）、可溯源、抗摄入注入、并对"已发表 ≠ 真实"保持诚实**的预注册声明（claim）——其骨架是"SourceDocument → EvidenceSpan → ExtractedSpec"的三段式不可绕过门禁，安全底座是架构级隔离（数据永远是数据、绝不直接触发工具或训练），统计底座是复现率/衰减先验的护栏；但所有统计门槛与衰减数字都必须降级为**显示但标注争议的区间，而非伪装成定论的硬闸门**（见第 7 节降权）。

## 2. 前沿 SOTA 与代表系统

环节 34 横跨四条互证的脉络：科学文献的 grounded-RAG/声明抽取、带 source-span 的结构化抽取、复现已发表异象的金融实证、以及防御被摄入文档的注入攻击。

- **PaperQA2 / WikiCrow / ContraCrow（FutureHouse）** — 开源 grounded-RAG-over-science 的代表实现，跨文献矛盾检测。**重要限定（见第 7 节）："superhuman / 超越人类"是 FutureHouse 厂商自评的营销框架、单厂商自测、且严格限定在生物医学文献检索；LitQA2 准确率仅 66.0%（precision 85.2%），即"在一个基准上胜过 PhD baseline"而非普遍可靠；ContraCrow 更新、独立验证更少；将其外推到量化金融论文（含表格/公式/再平衡规则）是未经验证的外推。** <https://github.com/Future-House/paper-qa>
- **Elicit / Consensus / SciSpace** — 商业科学助手，结构化抽取较强。**重要限定（见第 7 节）："只能 document-level 不能 span-level"系无引用来源的断言，工具能力在变化、部分已能给句/片段级证据，此泛化可能已过时，仅作设计动机不可作事实。** <https://elicit.com>
- **Google DeepMind CaMeL** — 架构级注入防御代表：控制流/数据流分离，使不可信数据永不改变程序流。**重要限定（见第 7 节）："ASR near zero / 攻击成功率近零"是被夸大的笼统结论——按原论文，CaMeL 仅解出 AgentDojo 77% 任务 vs 无防御 84%（约 7pt 的效用税），ASR 归零是模型特定（如 GPT-4o）且依赖用户自定义安全策略；作者本人列出"依赖人工撰写策略 + 用户批准疲劳"为失效模式，并称其"不是完美方案"。** <https://arxiv.org/abs/2503.18813>
- **Dual-LLM 与 Microsoft spotlighting** — 可部署的注入防御：隔离的 reader（仅吐 schema 约束的摘要）+ 特权 tool-holder（永不读原文），加 datamarking/encoding。**重要限定（见第 7 节）：spotlighting/dual-LLM 在自适应攻击下仍可被绕过——Microsoft 自己办 LLMail-Inject 挑战赛正因为 spotlighting 可被绕过；叠加这些防御不构成可证明的安全。** <https://arxiv.org/abs/2403.14720>
- **LangExtract / Instructor / Outlines** — 通过约束解码做 source-span-grounded 的类型化抽取，是 EvidenceSpan→ExtractedSpec 的构件。**重要限定（见第 7 节）：约束解码可产出 schema 合法但语义错误的 EvidenceSpan——模型编造一个通过类型检查、却并不支撑该字段的 span 偏移；"有锚点"作为硬约束并不保证锚点说的就是字段所声明的内容。** <https://github.com/google/langextract>
- **从文献挖 alpha（QuantaAlpha / AlphaAgent / Chain-of-Alpha）** — 从论文抽因子并回测，AlphaAgent 加 alpha-decay 正则；最接近本环节但治理薄弱。<https://dl.acm.org/doi/10.1145/3711896.3736838>
- **AgentDojo / InjecAgent** — agent 注入鲁棒性基准；指标为 benign utility、utility under attack、ASR。**注意（见第 7 节）：静态 ASR 数字不能为自适应攻击者的风险设上界。** <https://github.com/ethz-spylab/agentdojo>

## 3. 关键论文（每条带 URL）

- **Attribution / Citation / Quotation Survey 2025** — 分类学：pre-hoc vs post-hoc、span vs document-level；指标 citation precision/recall、ALCE、AIS；失效模式：幻觉引用、support gap、over-citation。*arXiv 2508.15396。* <https://arxiv.org/pdf/2508.15396>
- **RARR（ACL 2023, Gao et al.）** — Post-hoc attribution：先找证据再 post-edit 未被支撑的内容；可作"回填层"验证抽取字段是否被支撑。**注意（见第 7 节）：RARR 本身也会幻觉，"anchored-but-unsupported（已锚定但不被支撑）"威胁仍未被充分解决。** <https://arxiv.org/abs/2210.08726>
- **SciFact / SciFact-Open（Wadden et al. 2020）** — 生物医学声明带 support/refute 标签与 rationale 句；SciFact-Open 把证据扩到 50 万摘要；标准的 claim→evidence 锚定任务。<https://arxiv.org/abs/2004.14974>
- **PoisonedRAG（Zou et al. 2024）** — 首个 RAG 语料投毒攻击：每问 5 条恶意文本即达约 90% 攻击成功率。**重要限定（见第 7 节）：90% 是另一种威胁模型——对一个百万级知识库做语料投毒（攻击者控制可检索的 5/百万条），与"用户上传一篇论文"场景不同，定量数字不可直接外推；定性结论（上传文本不可信）成立。** *arXiv 2402.07867。* <https://arxiv.org/abs/2402.07867>
- **Replicating Anomalies（Hou, Xue, Zhang, RFS 2020）** — 452 个异象中 65% 过不了 t>1.96；在 t>2.78 的 hurdle 下约 82% 失败。已发表 ≠ 真实。*RFS 33(5)。* <https://academic.oup.com/rfs/article-abstract/33/5/2019/5236964>
- **Is There a Replication Crisis in Finance?（Jensen, Kelly, Pedersen / JKP, JF 2023）** — 对立面：贝叶斯模型发现 82.4% 复现、13 个主题、横跨 93 国 OOS 稳健，开放 Global Factor Data。**重要限定（见第 7 节）：82.4% 是相对 CAPM alpha 的复现率（特定判据），并非单一头条数字；JKP 整体框架是"多数复现"且因判据不同而异；把 82.4% 当扁平"复现率"是二手/不精确，且挑了产生最干净反 HXZ 结论的判据。** *JF 78(5)。* <https://onlinelibrary.wiley.com/doi/10.1111/jofi.13249>
- **McLean & Pontiff（JF 2016）** — 异象收益 OOS 下降约 26%、发表后下降约 58%；可作抽取声明的经验衰减先验。*JF 71(1)。* <https://onlinelibrary.wiley.com/doi/10.1111/jofi.12365>
- **…and the Cross-Section of Expected Returns（Harvey, Liu, Zhu, 2016）** — 测过 316+ 因子；新因子应过 t>3.0 而非 2.0。**重要限定（见第 7 节）：被本研究自己引用的来源——Chen & Zimmermann（arXiv 2204.10275 / 2209.13623）——直接反驳：publication-bias 调整后的 t-hurdle 弱可识别/不可识别、Benjamini-Yekutieli 基础"过度保守"，约 81% 被 3.0 门槛判为"不显著"的发现其实是真预测因子。学界无共识，应作可调护栏。** *RFS 29(1)。* <https://academic.oup.com/rfs/article/29/1/5/1843824>
- **Deflated Sharpe Ratio 与 PBO（Bailey & López de Prado）** — 在多次试验下校正选择偏倚、样本长度、非正态（DSR）+ PBO。**重要限定（见第 7 节）：DSR 是模型化 null 下的"选择偏倚/多重检验标度修正"（假定 SR 分布、偏度/峰度近似、且需选定试验数 N），不是对系统性向下偏倚的修复、也不是通用"复现"检验；对短回测/病态分布脆弱；把它当解决"必须复现且不过拟合"的干净可计算门槛，夸大了一个噪声大、假设重、关键输入 N（有效独立性）在文献抽取场景通常未知的估计量。** *SSRN 2460551。* <https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2460551>
- **Do t-Statistic Hurdles Need to be Raised?（Chen & Zimmermann）** — 论证 publication-bias 调整后的 t-hurdle 弱可识别、信息量低、且 BY 基础过度保守。是对 HLZ t>3.0 的核心反方文献。*arXiv 2204.10275（另见 2209.13623 Publication Bias in Asset Pricing Research）。* <https://arxiv.org/pdf/2204.10275>
- **Open Source Cross-Sectional Asset Pricing（Chen & Zimmermann 2022）** — 复现几乎所有截面预测因子：98% 复现 t>1.96；斜率 0.90、R² 83%。可作"已复现异象基线库"。*Critical Finance Review。* <https://www.openassetpricing.com/>

## 4. 机构最佳实践 / 标准

- **OWASP Top 10 for LLM Apps 2025** — LLM01 Prompt Injection 与 LLM08 Vector and Embedding Weaknesses；为摄入流水线提供威胁分类与缓解清单。**重要限定（见第 7 节）："LLM01（indirect ranked first）/ 间接注入单独排第一"系不精确——LLM01 Prompt Injection 整体排 #1，同时覆盖 direct 与 indirect，indirect 是子类，并非单独排第一；此误读可能误导清单实施者。** <https://owasp.org/www-project-top-10-for-large-language-model-applications/assets/PDF/OWASP-Top-10-for-LLMs-v2025.pdf>
- **NIST AI RMF + Generative AI Profile（AI 600-1, 2024）** — §2.9 prompt injection 与 data poisoning、§2.12 供应链完整性；Data BOM 记录 RAG 语料 provenance/license/PII；红队；事件披露。<https://www.nist.gov/itl/ai-risk-management-framework>
- **CFA Institute** — Standard V(A) reasonable basis 历史上意味可复现性，但 LLM 随机性破坏它，故须披露 AI 使用；Standards II/III 要求非 MNPI 数据与保密。**注意（见第 7 节合规陷阱）：无固定种子/provenance/披露时输出不可审计。** <https://www.cfainstitute.org/insights/articles/why-ethical-decision-frameworks-are-critical-for-ai-in-investment-management>
- **Microsoft MSRC 间接注入防御** — spotlighting（delimiting / datamarking / encoding）+ 分层防御 + LLMail-Inject 自适应攻击挑战赛。<https://www.microsoft.com/en-us/msrc/blog/2025/07/how-microsoft-defends-against-indirect-prompt-injection-attacks>

## 5. 对 QuantBT 这套架构的推荐方向（概念级）

> 以下均为概念级方向，不点 file:line、不排实施计划。所有自动门槛在落地时均应降级为可调、需人工判断、带信心标注的启发式。

1. **抽取=不可绕过的治理流水线，三段式类型化 SourceDocument → EvidenceSpan → ExtractedSpec。** 每个 ExtractedSpec 字段至少携带一个 EvidenceSpan（精确源 span + doc id + page/paragraph）；无锚点的字段**不得进入预注册**——把引用锚定做成硬的数据结构约束，而非事后合规。

2. **信任分层 + "数据不是指令"隔离作为第一原则。** 上传文本一律视为不可信，永不直接驱动控制流、永不触发工具、永不触发训练。借 CaMeL 控制/数据流分离与 dual-LLM（隔离 reader 仅吐 schema 约束摘要、特权 tool-holder 永不读原文）+ spotlighting + 最小权限。**保留架构隔离论点为本环节的核心交付，但承认（见第 7/8 节）：这些防御在自适应攻击下可被绕过、不构成可证明安全；静态 ASR 不为自适应风险设上界。**

3. **统计门槛从硬门禁降级为"显示但标注争议的区间"。** 这是相对原研究方向的关键修正：**不要**把 Harvey-Liu-Zhu t>3.0 + McLean-Pontiff 衰减硬编码为"预注册不可绕过的门禁"。因为本研究自引的 Chen & Zimmermann 直接论证该 hurdle 弱可识别/可能不可识别/过度保守（约 81% 被判"不显著"者实为真因子）。落地应：给原始 t、HLZ t>3.0 视角下的 t、以及 DSR 视角下的 t **作为多个并列区间呈现**，并显式标注"复现是争议性议题、给区间不给单点"，由人判断；任何把单一争议侧当硬闸门都会系统性 false-negative 真因子。

4. **每条声明附复现 dossier + 衰减先验，但作为"待核对的提示"而非自动裁决。** 自动标注原始样本期/市场/统计 hurdle；把 McLean-Pontiff 量级的发表后衰减作为**默认显示的保守先验之一**，让人看到去过拟合、去乐观后的版本。**诚实边界（见第 7 节）：约 58% 的 McLean-Pontiff 先验是争议数字、不应对所有声明统一施加；向非专家展示单一"衰减调整后数字"恰是本研究别处警告的"单点不给区间"反模式——应给区间并标注先验来源与不确定性。**

5. **复现已发表异象=自动对账，但诚实限定到基线库真实覆盖的范围。** 把抽取的因子映射到已复现基线库（Chen-Zimmermann CrossSection、JKP Global Factor Data），报告 reproduced-t vs original-t 与 OOS；未匹配者标"未独立复现"，要求严格无泄露 walk-forward OOS。**关键漏点（见第 7/8 节）：这些基线库是美/全球股票截面库；本项目范围含 A 股与加密——A 股/加密文献抽出的异象没有对账基线，"自动对账"对项目相当大一部分宇宙实际上不适用，必须诚实标注"此机制仅在已复现库存在处生效"，不可作为通用机制呈现。**

6. **预注册=冻结 + 防篡改。** 对每条预注册声明做 hash-freeze（spec + 锚点 + hurdle + 衰减先验）；下游回测/训练只引用冻结版本；任何"看了 OOS 再改抽取"都被记录并触发多重检验 deflation 惩罚。

7. **证据级引用质量门 + 矛盾检测。** RARR 式 post-hoc 验证确认每个字段引用确实支撑该字段（防 support gap / 幻觉引用 / over-citation）；ContraCrow 式跨文献矛盾检测把冲突浮现给人判断，**不自动调和**（自动选边会剥夺用户的经济判断）。**注意（见第 7 节）：RARR 本身会幻觉，需补一道"独立的 span-support 验证"，并把约束解码产出的 span 视为"可能 schema 合法但语义错误"。**

8. **注入鲁棒性与抽取质量作为交付级回归 eval 的门。** 一套金融文献摄入红队集，对 AgentDojo/InjecAgent ASR + PoisonedRAG 式投毒样本测试；引用质量用 ALCE 式 precision/recall；以 NIST GenAI Profile Data BOM + OWASP LLM01/LLM08 缓解清单作为治理证据链。**诚实边界：把 PoisonedRAG 的约 90% 当本上传场景的定量威胁是过度外推；红队集应面向"单文档上传"威胁模型自建，而非搬运语料投毒数字。**

9. **面向非技术用户的 claim-card 层。** 每条预注册声明是一张卡：一行经济直觉、可点回原文的 source-evidence span、复现状态徽章、**衰减调整后的保守期望（应以区间呈现并标注争议）**、以及哪些下游环节消费它。**诚实边界（见第 7 节）：单一"衰减调整数字"对非专家会制造伪精确，须以区间 + 先验来源呈现，避免成为 UX 诚实失败。**

10. **A 股 / 加密适用性单列评估（项目特异）。** 因复现基线库为美/全球股票，A 股/加密无对账基线；应明确把"无基线 → 不能自动对账 → 必须靠严格无泄露 walk-forward OOS + 人工经济判断"作为这部分宇宙的默认路径，不让"自动对账"在无库处静默失效。

## 6. 架构级参考（少量伪代码 / schema 草图，非代码接线）

> 以下为示意草图，用于沟通概念形状，**不接线到现有代码**。

三段式抽取链与"无锚点不得预注册"的硬约束：

```yaml
# extraction_pipeline.schema (示意)
SourceDocument:
  doc_id: uuid
  trust_tier: enum[untrusted]      # 上传文本恒为 untrusted；永不驱动控制流/工具/训练
  origin: enum[upload_pdf, note, web]
  license_status: enum[unknown, copyrighted, open]   # 版权/再分发风险留痕(见第8节)
  raw_blob_ref: uri                # 原文只读，仅供隔离 reader 取证

EvidenceSpan:
  span_id: uuid
  doc_id: uuid
  locator: {page: int?, paragraph: int?, char_start: int, char_end: int}
  quoted_text: text                # 精确源 span（逐字）
  span_support_verified: bool      # 独立验证：该 span 是否真支撑所锚字段(非仅"存在")
  parse_provenance: enum[text_layer, ocr, table, formula]  # 标记 OCR/表格/公式来源(脆弱)

ExtractedSpec:
  spec_id: uuid
  field: enum[factor_def, rebalance_freq, universe, horizon, original_t, sample_period, market]
  value: any
  anchors: [span_id, ...]          # 至少 1 个；为空则 reject_preregistration
  # —— 复现 dossier + 衰减先验：作为"显示但标注争议的区间"，非硬门禁 ——
  replication:
    matched_baseline: enum[chen_zimmermann, jkp, none]     # A股/加密多为 none(见第5/7节)
    reproduced_t: float?
    original_t: float?
    hurdle_views:                  # 多个并列区间，不选单一侧
      - {name: "raw_t", value: float}
      - {name: "HLZ_t>3.0(争议)", note: "Chen-Zimmermann 反驳，弱可识别"}
      - {name: "DSR(需未知N,争议)", note: "标度修正，非通用复现检验"}
    decay_prior:                   # 区间 + 来源，非单点
      view: enum[mclean_pontiff_~58%(争议), none]
      as_range: {low: float, high: float}
  contradiction_flags: [conflicting_spec_id, ...]          # 浮现给人判断，不自动调和
```

预注册冻结与防篡改门（概念伪代码）：

```python
# pre_registration_gate (示意，非接线)
def try_preregister(spec: ExtractedSpec) -> Decision:
    if not spec.anchors:
        return reject("no_evidence_span")                 # 硬数据结构约束
    if not all(span.span_support_verified for span in spec.anchors):
        return needs_review("anchored_but_unsupported")   # RARR+独立验证仍存幻觉风险
    if any(s.parse_provenance in {OCR, TABLE, FORMULA} for s in spec.anchors):
        flag("span_may_be_misaligned")                    # false-provenance 比无锚更危险
    frozen = freeze(spec)                                 # hash + timestamp, 只读
    # 统计门槛=显示但标注争议的区间，不作 pass/fail 闸门
    attach(frozen, hurdle_views=spec.replication.hurdle_views, contested=True)
    return frozen   # 下游只引用 frozen；看 OOS 后改抽取 → 记录 + 触发 deflation 惩罚
```

数据流隔离（dual-LLM / 数据不是指令，概念形状）：

```text
[untrusted SourceDocument]
        │ (仅原文)
        ▼
  Quarantined Reader LLM ──► 仅输出 schema 约束的 EvidenceSpan/ExtractedSpec（数据）
        │ (永不返回自由文本指令)
        ▼
  Privileged Orchestrator ──► 永不读原文；只消费 schema 数据；工具调用受最小权限+人审门
                              （CaMeL 控制/数据流分离；spotlighting/datamarking 为辅助层，
                               承认自适应攻击下可被绕过，不构成可证明安全）
```

## 7. 降权 / 争议 / 陷阱（对抗核查结论）

> 本节原样保留对抗核查的限定词（夸大/争议/撤稿/二手/不可外推等）。综合判定：**这是一份扎实、来源良好的调研——多数头条数字（HXZ 65%/82%、PoisonedRAG ~90%、McLean-Pontiff 26%/58%、JKP、PaperQA2 LitQA2）转录准确，无所引论文被撤稿。但研究犯了它自己警告的错。**

降权与争议（按严重度）：

- **【高·内部自相矛盾】把 HLZ t>3.0 + McLean-Pontiff 衰减硬编码为每条声明的不可绕过预注册门禁（原 design directions #3/#4）。** 与研究自引来源**自相矛盾**：Chen & Zimmermann（arXiv 2204.10275 / 2209.13623）论证 publication-bias 调整的 t-hurdle **弱可识别（weakly identified）、信息量低**，其 Benjamini-Yekutieli 基础"过度保守（excessively conservative）"，约 81% 被 3.0 门槛判"不显著"者实为真预测因子。研究 summary 称该辩论"contested / 给区间不给单点"，具体设计却把**一个争议的、可能不可识别的 hurdle** 烤进"无它不得预注册"的门，会系统性 false-negative 真因子。研究从未解决预注册究竟强制哪个 hurdle、以及 hurdle false-negative 真因子时谁负责。**修正：降级为显示但标注争议的区间。**
- **【中·夸大】CaMeL "ASR near zero on AgentDojo"。** 笼统化夸大：按原论文（arXiv 2503.18813），CaMeL 仅解出 77% AgentDojo 任务 vs 无防御 84%（真实约 7pt 效用税），ASR 归零是**模型特定**（如 GPT-4o）且**取决于用户自定义安全策略**；作者本人把"依赖人工撰写策略 + 用户批准疲劳"列为失效模式，并称其"不是完美方案"。无这些 caveat 的"near zero"夸大了可部署性、隐藏了安全依赖正确的人写策略。
- **【中·夸大/二手营销】PaperQA2/WikiCrow/ContraCrow "superhuman / 开源 grounded-RAG SOTA"。** "Superhuman" 是 FutureHouse 厂商自评的单厂商自测营销框架，**非独立基准**；窄域限定在生物文献检索；LitQA2 准确率仅 66.0%（precision 85.2%），即"在一个基准上胜过 PhD baseline"而非普遍可靠；ContraCrow 更新、独立验证远更少；把生物医学调优工具外推到量化金融论文（表/公式/再平衡规则）是**未经验证的外推**。
- **【中·夸大】DSR/PBO "把必须复现且不过拟合变成可计算门槛"。** DSR 是模型化 null 下的**选择偏倚/多重检验标度修正**（假定 SR 分布、偏度/峰度近似、且需选定试验数 N），**不是**对系统性向下偏倚的修复、也**不是**通用"复现"检验；对短回测/病态分布脆弱（评论者已承认）。把它当解决"必须复现且不过拟合"的干净可计算门槛，夸大了一个噪声大、假设重、关键输入 N（有效独立性）在文献抽取场景通常未知的估计量。
- **【低·不可外推】PoisonedRAG "每问 5 文本劫持约 90%；上传文档是攻击面"被套到用户上传场景。** 90% 数字准确，但属**不同威胁模型**——对百万级知识库做语料投毒（攻击者控制可检索语料中的 5/百万条），与"用户上传一篇论文"场景（单文档上传、攻击者控制整篇而非 5/百万、检索动态不同）不同，**数字不可直接外推**；定性结论（上传文本不可信）成立。
- **【低·二手/不精确】JKP "82.4% replicate" 横跨 93 国（作为 pro-replication 反方）。** **二手/不精确**：82.4% 是 JKP 相对 **CAPM alpha** 的复现率（特定判据），非单一头条；JKP 整体框架是"多数复现"且随判据而异；把 82.4% 当扁平"复现"数字夸大了精度、且挑了产生最干净反 HXZ 结论的判据。
- **【低·不精确】OWASP LLM01 "Prompt Injection（indirect ranked first）/ LLM08"。** **不精确**：在 OWASP Top 10 for LLM Apps 2025，LLM01（Prompt Injection）整体排 #1 且**同时覆盖 direct 与 indirect**；indirect 是子类，并非单独"排第一"。对分类学的轻微误读可能误导清单实施者。
- **【低·未验证/可能过时】Elicit/Consensus/SciSpace "document-level 不能 span-level"。** 无引用来源；工具能力在变、部分已能给句/片段级证据。此断言貌似合理，但作为事实呈现以论证 span-level 设计时是**未验证、可能过时的泛化**。

陷阱（pitfalls）：

- **把"已发表"当"已证明"**：HXZ 65-82% 过不了 hurdle、McLean-Pontiff 约 58% 衰减；逐字搬论文数字等于把死异象包装成声明。
- **但也别一刀切说"多数不可复现"**：JKP 2023 发现 82% 跨 93 国复现（注意上文对该数字的二手限定）。复现是争议性议题，**给区间**。
- **只检测的注入防御只拖慢攻击**：无架构隔离，上传文档可改变宇宙或触发下单。
- **上传文档是攻击面**：PoisonedRAG 5 文本劫持约 90%（注意威胁模型外推限定）；向量/嵌入层可被投毒。"用户上传"不等于"可信"。
- **引用幻觉与 support gap**：无 post-hoc 验证 + span 级锚定，引用锚定只是论文式合规。
- **抽取后篡改**：看了 OOS 后改定义/hurdle 使多重检验未计；须 hash-freeze 并惩罚改动。
- **document-level vs span-level**：Elicit 式工具是 document-level（注意上文限定），对需精确 provenance 的交易规则/再平衡频率不足。
- **OCR/PDF 解析噪声 + false-provenance**：数学定义与再平衡细节在表/公式/脚注中被丢/错位；span 锚点可能**自信地错（anchored-but-wrong），比无锚更危险**；设计只校验"锚点存在"而无"span 正确性"验证。
- **合规陷阱**：CFA V(A) 把 reasonable basis 当可复现性，但 LLM 随机性破坏它；无固定种子/provenance/披露则输出不可审计。
- **静默调和矛盾**：自动选边而非浮现冲突，会剥夺用户的经济判断。

## 8. 开放问题

1. **治理设计自身的内部矛盾如何收口？** directions #3/#4 把 HLZ t>3.0 + McLean-Pontiff 衰减硬编码为强制门，而 summary/pitfalls 坚称复现"contested、给区间"。流水线不能既烤进单一争议 hurdle 又保持中立。**究竟在预注册强制执行哪个 hurdle、hurdle false-negative 真因子时谁负责——研究从未解决。**
2. **治理流水线的成本/基准率从未讨论。** 一条"不可绕过"流水线要求每个 ExtractedSpec 字段带精确 EvidenceSpan + RARR 验证 + 矛盾检测 + DSR/PBO + 对账 Chen-Zimmermann 与 JKP——对单篇上传论文有巨大延迟/成本与高误拒率。**无吞吐、人审负担、以及"何处退化为剧场"的讨论。**
3. **OCR/PDF/表/公式抽取失败与"每字段带精确 span"保证如何调和？** 若数学定义与再平衡频率常驻于解析器丢/错位的表/脚注/LaTeX，span 锚点可**自信地错**——"已锚定但看似有据"的 false-provenance 比无锚更危险。设计**只验证 span 存在，无 span 正确性验证**。
4. **A 股适用性完全缺席。** 复现基线（Chen-Zimmermann CrossSection、JKP Global Factor Data）是美/全球股票截面库；项目范围含 A 股与加密。A 股/加密文献抽出的异象**无对账基线**——"自动对账已复现库"对项目相当大一部分实际宇宙**静默不适用**，却被当通用机制呈现。
5. **约束解码可产出 schema 合法但语义错误的 EvidenceSpan。** 模型编造通过类型检查、却不支撑字段的 span 偏移。设计把"有锚点"当硬约束，但除 RARR（其自身幻觉）外**无独立验证引用 span 是否真的说了字段所声明的内容**；"anchored-but-unsupported" 威胁未充分解决。
6. **防御的对抗鲁棒性是断言而非对自适应攻击者评估。** CaMeL/dual-LLM/spotlighting 在自适应攻击下均有记录在案的绕过（Microsoft 自办 LLMail-Inject 挑战赛正因 spotlighting 可绕过）；AgentDojo/InjecAgent 的**静态 ASR 不为自适应风险设上界**，叠加它们也不组合成可证明安全。
7. **摄入并存储用户上传论文的法律/许可与版权暴露未讨论。** 多数期刊 PDF 受版权保护；再分发 span/引文有限制——NIST Data BOM 方向提及但未对"持久化并再服务 source span 的系统"解决。
8. **"带衰减调整保守期望的 claim-card" 对非技术用户会制造伪精确。** 向非专家展示单一"衰减调整数字"（源自对所有声明统一施加的争议性约 58% McLean-Pontiff 先验）恰是研究别处警告的"单点不给区间"反模式——一个未被标记的 UX 诚实失败。

## 9. 参考文献（URL）

- PaperQA2 / paper-qa（FutureHouse）：<https://github.com/Future-House/paper-qa>
- PaperQA2 论文（LitQA2 66%）：<https://arxiv.org/html/2409.13740v1>
- Elicit：<https://elicit.com>
- CaMeL（DeepMind）：<https://arxiv.org/abs/2503.18813> · PDF：<https://arxiv.org/pdf/2503.18813>
- Dual-LLM / spotlighting：<https://arxiv.org/abs/2403.14720>
- LangExtract：<https://github.com/google/langextract>
- AlphaAgent / 从文献挖 alpha（KDD'25）：<https://dl.acm.org/doi/10.1145/3711896.3736838>
- AgentDojo：<https://github.com/ethz-spylab/agentdojo>
- Attribution/Citation/Quotation Survey 2025：<https://arxiv.org/pdf/2508.15396>
- RARR（ACL 2023）：<https://arxiv.org/abs/2210.08726>
- SciFact / SciFact-Open：<https://arxiv.org/abs/2004.14974>
- PoisonedRAG：<https://arxiv.org/abs/2402.07867>
- Replicating Anomalies（HXZ, RFS 2020）：<https://academic.oup.com/rfs/article-abstract/33/5/2019/5236964>
- Is There a Replication Crisis in Finance?（JKP, JF 2023）：<https://onlinelibrary.wiley.com/doi/10.1111/jofi.13249>
- McLean & Pontiff（JF 2016）：<https://onlinelibrary.wiley.com/doi/10.1111/jofi.12365>
- Harvey, Liu, Zhu（2016）：<https://academic.oup.com/rfs/article/29/1/5/1843824>
- Chen & Zimmermann, Do t-Statistic Hurdles Need to be Raised?：<https://arxiv.org/pdf/2204.10275>
- Deflated Sharpe / PBO（Bailey & López de Prado）：<https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2460551>
- Open Source Cross-Sectional Asset Pricing（Chen & Zimmermann）：<https://www.openassetpricing.com/>
- OpenSourceAP CrossSection（代码）：<https://github.com/OpenSourceAP/CrossSection>
- bkelly-lab ReplicationCrisis / JKP Global Factor Data：<https://github.com/bkelly-lab/ReplicationCrisis>
- ALCE（引用质量 eval）：<https://github.com/princeton-nlp/ALCE>
- RAG 投毒防御（GMTP/FilterRAG/RevPRAG）：<https://arxiv.org/pdf/2507.18202>
- OWASP Top 10 for LLM Apps 2025：<https://owasp.org/www-project-top-10-for-large-language-model-applications/assets/PDF/OWASP-Top-10-for-LLMs-v2025.pdf> · LLM01：<https://genai.owasp.org/llmrisk/llm01-prompt-injection/>
- NIST AI RMF + GenAI Profile：<https://www.nist.gov/itl/ai-risk-management-framework>
- CFA Institute（AI 伦理框架）：<https://www.cfainstitute.org/insights/articles/why-ethical-decision-frameworks-are-critical-for-ai-in-investment-management>
- Microsoft MSRC 间接注入防御（spotlighting / LLMail-Inject）：<https://www.microsoft.com/en-us/msrc/blog/2025/07/how-microsoft-defends-against-indirect-prompt-injection-attacks>
