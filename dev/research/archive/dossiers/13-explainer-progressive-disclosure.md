# 13 · 解释官：渐进披露 / 经济翻译 / 可解释 AI

> 机构级 Agent OS 成品环节深挖 · 全程 Opus 4.8 · 对抗式核查已降权 · 重心=前沿研究+概念级推荐 · 不含 file:line 代码接线
> 簇 B

## 1. 一句话定位

解释官是 Agent OS 的「翻译阀」：把全流程里那些冷冰冰的统计闸门（夏普、PBO、CSCV、OOS 衰减、换手、回撤、暴露）按受众分层（L1 小白 → L4 复核者）翻成可懂、可行动、可被反驳的经济叙事。它的最大风险不是「说不清」，而是**「说得太顺」**——把一个本质不确定的统计闸门翻成流畅的经济故事，会系统性诱发**过度依赖**而非校准信任。因此本环节的诚实定性分三层：**渐进披露 + 受众分层 = 成熟可落地的组织原则**；**「经济翻译提升决策」有模糊痕迹理论（FTT）与叙事金融的间接支撑，但缺乏稳健因果实证**；而**强证据反复显示解释易制造盲信**——尤其在「让 LLM 当解释官」这一动作上踩中多个已知雷区（CoT 不忠实、解释深度的幻觉、对话式 XAI 放大过度依赖）。

## 2. 前沿 SOTA 与代表系统

学界与产业把「面向人的可解释」拆成两条主线：**受众分层 + 渐进披露**（组织原则，已成熟），与**解释是否真改善决策**（实证战场，远未定论）。

- **CFA Institute — Explainable AI in Finance: Addressing the Needs of Diverse Stakeholders（2025-08）** — 金融业受众分层 XAI 的权威报告，本环节 L1–L4 分层最直接的行业对标。核心问 **"explainable to whom?"**，分析六类利益相关者（信贷员 / 组合经理 / 监管 / 合规 / 终端消费者 / 开发者）的差异化解释需求；明确指出**当前 XAI 工具几乎全为技术用户设计，对业务用户 / 监管 / 客户严重缺位**（这正是本产品的目标人群）。区分 ante-hoc（内生可解释）与 post-hoc（SHAP/LIME/反事实）。<https://rpc.cfainstitute.org/research/reports/2025/explainable-ai-in-finance>
- **Conversational XAI assistant（He, Aishwarya, Gadiraju — IUI 2025）** — 与本环节对话式架构最贴近的 SOTA 实验，也是最直接的警示。对话式 XAI 比 dashboard 带来**更好理解与更高信任**，但两者都引发明显**过度依赖**，**LLM agent 增强版放大过度依赖**；归因为「**解释深度的幻觉（illusion of explanatory depth）**」。代码开源（delftcrowd/IUI2025_ConvXAI）。<https://arxiv.org/abs/2501.17546>
- **NIST IR 8312 — Four Principles of Explainable AI** — 事实上的 XAI 治理基线：Explanation（给依据）、Meaningful（对该用户可懂）、**Explanation Accuracy（忠实反映过程）**、**Knowledge Limits（越界 / 低置信即停）**。后两条对本环节尤其关键——解释官必须在统计闸门「超出适用域」（样本太短 / regime 漂移 / 数据缺失）时**沉默或降级**，而非硬翻成自信故事。<https://nvlpubs.nist.gov/nistpubs/ir/2021/nist.ir.8312.pdf>
- **Federal Reserve SR 26-2（2026-04，取代 SR 11-7 / SR 21-8）** — 美最新模型风险监管：从「每年重验」转为**按模型重要性的风险比例监管**；保留「有效挑战」与文档可追溯原则；但**明确把 generative / agentic AI 列为「范围之外」**、要求机构沿用既有治理判定控制。对 agent 驱动产品是直接警示：**监管尚未为本类系统背书**。<https://www.federalreserve.gov/supervisionreg/srletters/SR2602.htm>
- **EU AI Act Art.13/14/4（透明 / 人类监督 / AI 素养）** — 高风险 AI 须「足够透明」使部署者能**正确解读输出**（Art.13）、能被自然人**有效监督**并理解能力与局限（Art.14）、并要求 **AI 素养**（Art.4）。把「解释要让人能正确解读并监督」写成了法律义务，可作为解释官的合规验收标尺。<https://artificialintelligenceact.eu/article/13/>

## 3. 关键论文（每条带 URL）

- **Explanations Can Reduce Overreliance on AI Systems During Decision-Making** — Vasconcelos, Jörke, Grunde-McLaughlin, Gerstenberg, Bernstein, Krishna（CSCW 2023）。**【方向性已被对抗核查修正，见 §7 high】** 论文标题与一手结论是：**解释 CAN 减少过度依赖，且恰恰在「验证成本高 / 难任务」条件下减少**——因为人工验证更费力时，读解释相对更省力、更划算。机制是成本收益：人按「读解释的相对成本」策略性地决定是否真读解释。**正确的设计含义是：对难决策（是否上线 / 加杠杆）更应提供「可低成本验证」的解释，而非加摩擦。** <https://cicl.stanford.edu/papers/vasconcelos2023explanations.pdf>
- **Stop Explaining Black Box ML Models for High Stakes Decisions and Use Interpretable Models Instead** — Rudin（Nature Machine Intelligence 2019）。事后解释对原模型只能「猜测」，**永不完全保真**（若完全保真，解释即等于模型本身）；用事后解释包装黑箱会延续坏实践、酿成灾害。主张高风险场景直接用内生可解释模型。映射：中低频策略的统计闸门本就多为可解释指标，应优先保留**内生可解释链路**，而非让 LLM 事后编故事。<https://arxiv.org/abs/1811.10154>
- **Language Models Don't Always Say What They Think: Unfaithful Explanations in Chain-of-Thought** — Turpin, Michael, Perez, Bowman（NeurIPS 2023）。LLM 自解释 / CoT 常与其真实推理不一致——可产出 **plausible 但 unfaithful** 的理由（加偏置特征致准确率掉最多 36%、模型不提偏置）。直接含义：用 LLM 当「经济翻译官」存在**系统性不忠实风险**，叙事可能与底层统计闸门的真实逻辑脱节，须把翻译锚定在可校验的数值 / 规则上而非让模型自由发挥。**【引用 URL 已被对抗核查修正，见 §7 medium：正确 ID 为 arXiv:2305.04388】** <https://arxiv.org/abs/2305.04388>
- **Fuzzy-Trace Theory: gist communication and decision making** — Reyna & Brainerd；Reyna（PNAS 2020 等）。人靠 **gist（底线含义）** 而非 **verbatim（精确数字）** 决策，且 gist 常产生比逐字更合逻辑的决策——「最精确的逐字表征反而可能导致更不合逻辑的判断」。为「把统计闸门翻成经济底线叙事」提供**认知科学正面依据**；但强调**必须传递正确的 gist**，否则错误 gist 危害更大。<https://www.pnas.org/doi/10.1073/pnas.1912441117>
- **Testing the effectiveness of consumer financial disclosure: Experimental evidence from savings accounts** — Adams, Hunt, Palmer, Zaliauskas（Journal of Financial Economics 2021）。现场 RCT（12.4 万储蓄账户）：**无论披露如何设计，换户行为都极少**（$190/年潜在收益 + 约 15 分钟成本仍不动）；「**悲观信念驱动的不注意**」压制披露效力。冷峻地证明：把信息说清楚 ≠ 改变决策——不能假定「翻得好用户就会用」，要直面注意力与动机的真实约束。<https://www.sciencedirect.com/science/article/abs/pii/S0304405X21000829>
- **The Inconsistent Effects of Plain English Disclosures on Nonprofessional Investors' Risk Judgments**（IJFS/MDPI 2018）。Plain English 对非专业投资者风险判断的影响**不一致、并非稳定改进**。提醒：经济翻译必须做**框架中性与双向呈现**。**【对 Loughran-McDonald 的「双向放大 / 武器化」外推已被对抗核查降权，见 §7 medium】** <https://www.mdpi.com/2227-7072/6/1/25>
- **On the failings / inadequacy of Shapley values for explainability** — Huang & Marques-Silva（2023–2024）。理论证明 SHAP 可把**可证无关特征赋最大 Shapley 值**、给关键特征赋零重要性；叠加「**disagreement problem**」（LIME 与 SHAP 连符号方向都会分歧）。直接含义：**不要把单一 SHAP 归因直接翻成「因为因子 X 所以…」的因果经济叙事**——归因不稳且可误导。**【对抗核查标注：这些反驳依赖对抗式构造的布尔分类器 / 规则解释场景，并非典型 ML 模型上的普遍现象，实务普遍性有争议，见 §7 low；两篇被并条、主 URL 配错，refutation 实为 arXiv:2309.03041】** <https://arxiv.org/pdf/2302.08160>
- **Algorithmic Transparency Affects the Perceived Trustworthiness of Automated Decision-Making** — Grimmelikhuijsen（Public Administration Review 2023）。过程透明（可及性 + 可解释性）提升**感知**可信度，且 explainability 的效应强于 accessibility；未充分解释、不可质询的决策降低信任。为「流程即信任」命题提供实证支撑——但**这是「感知信任」而非「决策质量」**，且原文自陈效应在不同决策情境下**并不稳健（not robust across decision contexts）**（见 §7 low）。<https://onlinelibrary.wiley.com/doi/full/10.1111/puar.13483>
- **Beyond Explainable AI (XAI): An Overdue Paradigm Shift and Post-XAI Research Directions**（2026，arXiv:2602.24176，49 作者）。跨学科综述主张从「静态特征归因解释」转向：**交互式验证**（让用户测试 / 质疑 / 实时验证模型）、**以可行动性为中心**、面向非专家、并以「**实测决策质量与信任校准改善**」为验收标准。与本环节对话式 agent 方向吻合，但要求把「能否改善决策」当成**必测指标而非默认**。<https://arxiv.org/pdf/2602.24176>

## 4. 机构最佳实践 / 标准

- **SR 11-7「有效挑战（effective challenge）」** — 解释必须充分到让胜任、独立、有动机与权限的一方能批判性识别模型的局限与假设。映射：**每个 tier 的解释应让该 tier 用户「有能力反驳」**，而非只是被动接受。**注意：SR 11-7 的「独立」指组织上独立的人 / 团队；且 SR 26-2 已将其取代并把 genAI/agentic 置于范围外（见 §2、§7）。** <https://www.federalreserve.gov/supervisionreg/srletters/sr1107.htm>
- **NIST IR 8312「Knowledge Limits」** — 系统只在设计适用域内、且置信足够时输出；否则应声明不确定 / 拒答。映射：统计闸门超出适用域（样本太短 / regime 漂移 / 数据缺失）时，解释官应**降级或沉默，绝不硬翻成自信的经济故事**。<https://nvlpubs.nist.gov/nistpubs/ir/2021/nist.ir.8312.pdf>
- **SEC — A Plain English Handbook** — 主动语态、短句、避免术语、具体而非抽象、信息分层与可视化，是受众分层语言的操作手册。**但配套实证（见 §3 MDPI 2018）显示「plain English ≠ 更好决策」**，须与框架中性、双向呈现合用。<https://www.sec.gov/pdf/handbook.pdf>
- **Spiegelhalter et al. — Communicating uncertainty about facts, numbers and science（Royal Society Open Science 2019）** — 不确定性沟通准则：**多格式并用**（数字 + 图形如 fan chart / icon array）、**避免单向框架**、显式承认局限；并**区分「范围宽度」与「置信度」**（外行常混淆）。映射：经济翻译要给**区间与置信**而非点估计，且图文并茂。<https://royalsocietypublishing.org/doi/10.1098/rsos.181870>
- **EU AI Act Art.14 人类监督 + Art.4 AI 素养** — 解释须使自然人能正确解读输出并有效监督；部署方须保障使用者具备相应 AI 素养。映射：小白用户场景下，解释官还要承担「**素养提升**」职能，且系统须支持人对每个闸门的**复核与否决**。<https://artificialintelligenceact.eu/article/14/>

## 5. 对 QuantBT 这套架构的推荐方向（概念级）

> 仅给概念级方向，不点 file:line、不排实施计划。

1. **双轨架构：把「解释」拆成 verbatim 锚点层 + gist 叙事层。** 底层永远是可校验、可追溯到原始统计闸门的数值 / 规则（忠实保真），上层才是面向 L1–L4 的经济 gist 叙事。**叙事必须由锚点确定性生成（模板 / 规则约束），禁止让 LLM 自由编因果**，以规避 CoT 不忠实（Turpin）与解释深度的幻觉。
2. **把「主动降低验证成本」当作一等设计目标**（对应 Vasconcelos 已修正的成本收益机制）。每条经济结论旁边一键展开「这句话基于哪个闸门、原始数字多少、阈值多少、若不通过会怎样」。让用户用极低成本验证，是把解释从「制造盲信」转为「校准信任」的关键开关。**清醒前提（见 §8）**：对真小白（L1/L2），「一键展开到原始夏普 / PBO」这一动作本身验证成本极高——他无能力判断 PBO=0.6 是否可信，可验证锚点对他**不可验证**，故此目标在 L1 层需配合素养脚手架，而非孤立成立。
3. **反过度依赖即默认。** 鉴于对话式 / LLM 解释会**放大**过度依赖，解释官应内置「摩擦」与「唱反调」——主动呈现反事实、反方证据、与该闸门的历史失败案例，并在高不确定 / 越适用域时**强制降级口吻**（NIST Knowledge Limits）。把「让用户停下来质疑」设计进流程。**注意（见 §7 high 修正）**：此「加摩擦」是针对 LLM 叙事放大盲信的对冲，**不应再以「难任务上解释帮倒忙」为论据**——Vasconcelos 恰恰说难任务上可验证的解释是有益的；摩擦的正确形态是**可验证锚点 + 降级口吻**，而非藏起解释。
4. **L1–L4 不是同一内容的四种措辞，而是四种「决策可行动单元」。** L1 给底线 gist + 一个行动（上 / 下线、加 / 不加）；L2 给关键权衡与区间（置信、潜在回撤）；L3 给闸门清单与通过 / 未通过及阈值；L4 给完整数值、方法、可复现追溯。每层都要满足 SR 11-7「有效挑战」——该层用户有能力**在该层**反驳（L1 层这一条近乎不可实现，见 §8，须直面而非口号化）。
5. **框架中性与双向呈现作为硬约束。** 鉴于 plain-English / 高可读性效果不一致、框架效应可双向放大判断，经济翻译必须同时给出乐观 / 悲观两面、给区间而非点估计、并做语言审计防止情绪化框架。把「**可读性**」与「**中立性**」分开度量。
6. **不确定性是头等公民，且要可视化。** 按 Spiegelhalter 准则，经济叙事默认带置信与区间、用 fan chart / icon array 等多格式，显式承认局限，并区分「范围宽度」与「置信度」。中低频策略的统计闸门（PBO/CSCV/OOS 衰减）天然带强不确定，翻译时不可抹平成确定结论。
7. **优先内生可解释、慎用事后包装（Rudin）。** 中低频闸门多为本就可解释的指标（夏普、PBO、换手、回撤、暴露），解释官应直接翻译这些可解释量；把事后归因（SHAP/CF）限定在确需黑箱（DL 模型卡）处，并对归因做**多方法一致性检查**后才叙事化，避免把不稳定归因讲成因果故事。
8. **把「流程即信任」落成可审计的解释账本而非话术。** 借鉴程序透明 / 有效挑战与 EU Art.14，每个闸门的解释、所依数值、用户的复核 / 否决都进**只读审计轨**；信任来自「可被回看与质询的过程」，不是来自叙事的流畅度。这也直接对接产品既有的 Run 详情与审计设施（并须接上 D2 加密落盘，见 §8）。
9. **把「解释是否真的改善决策」当成必测 KPI（post-XAI 范式）。** 不要默认经济翻译有效。设计内置 A/B 与校准指标——解释前后的决策质量、**过度依赖率**（用户接受错误建议的比例）、**信任校准**（信任与真实可靠度的相关）。没有实测改善的解释形态应被淘汰，而非保留。**对抗核查提示（见 §7 low）**：本环节大多反向证据来自众包 / 通用决策任务，并非中低频量化上线决策的本域实证，故此条应**前置为总基调**——所有方向都是「方向性提示，需在本场景做 A/B 验证」。
10. **面向小白要承担「素养脚手架」而非仅翻译。** 对不懂统计的经济学者 / 小白，L1–L2 之外提供可选的「为什么这个指标重要」的渐进教育层（progressive disclosure 的纵深用法），但**与决策叙事解耦**，避免把教学塞进决策瞬间增加认知负荷。

## 6. 架构级参考（少量伪代码 / schema 草图，非代码接线）

> 仅示意，不接线到现有代码。

**6.1 双轨解释对象 schema 草图（verbatim 锚点层 ∪ gist 叙事层）**

```yaml
gate_explanation:
  gate_id: "pbo_oos_decay"          # 对应某个统计闸门
  verbatim_anchor:                   # 忠实保真层（永远可追溯）
    metric: PBO
    raw_value: 0.62
    threshold: 0.50
    sample_window: "2018-01..2024-12"
    passed: false
    applicability:                   # NIST Knowledge Limits
      in_domain: true
      confidence: low|medium|high
      degrade_reason: null | "sample_too_short" | "regime_drift" | "missing_data"
  gist_narrative:                    # 面向 L1-L4 的经济叙事层
    generation: template_constrained # 禁止 LLM 自由编因果
    framing: neutral                 # 必须双向呈现
    optimistic_side: "..."
    pessimistic_side: "..."
    interval_not_point: true         # 给区间+置信，非点估计
  audience_units:                    # 四种"决策可行动单元"，非四种措辞
    L1: {gist: "...", action: go|no_go|hold}
    L2: {tradeoffs: [...], confidence_band: [...], potential_drawdown: [...]}
    L3: {gate_checklist: [...], pass_fail: [...], thresholds: [...]}
    L4: {full_numbers: {...}, method: "...", reproducible_trace_ref: "..."}
  verify_cost_reduction:             # Vasconcelos：主动降低验证成本
    one_click_drilldown: true        # 展开到原始数字/阈值/反事实
  literacy_scaffold:                 # 与决策叙事解耦的可选教育层
    why_this_matters: "..."
```

**6.2 解释生成回路（锚点确定性 → 模板约束叙事 → 越界降级）伪代码**

```
anchor = compute_verbatim_anchor(gate)          # 直接读统计闸门，可追溯

# NIST Knowledge Limits：越界即降级/沉默，绝不硬翻成自信故事
if not anchor.applicability.in_domain or anchor.confidence == "low":
    return degraded_explanation(anchor, tone="uncertain", action=None)

# 内生可解释优先；仅黑箱(DL)才走事后归因，且需多法一致性检查
if gate.kind == "interpretable_metric":          # 夏普/PBO/换手/回撤/暴露
    drivers = anchor                              # 直接翻译可解释量
else:
    attrs = [shap(), lime(), captum()]            # 多方法
    if disagreement(attrs) > EPS:                 # 不一致则不叙事化因果
        return drivers_unstable_explanation(anchor)
    drivers = consensus(attrs)

# 叙事由锚点确定性生成（模板/规则约束），禁止 LLM 自由编因果
gist = template_render(anchor, drivers, framing="neutral", both_sides=True)
units = project_to_audience_units(anchor, gist)   # L1-L4 = 可行动单元
log_to_explanation_ledger(anchor, gist, units)    # 只读审计轨 (D2 加密)
return units
```

**6.3 解释有效性回归门槛（post-XAI 必测 KPI，示意）**

```
suite = labeled_decision_tasks_with_ground_truth()  # 本域自建，非众包通用
metrics = {
  overreliance_rate:  rate(用户接受了"错误建议"),       # 目标下降
  trust_calibration:  corr(用户信任, 真实可靠度),       # 目标趋近 1
  verify_cost:        median(展开到锚点所需步数/时间),   # 目标下降
  framing_neutrality: |optimistic_lean - pessimistic_lean|,  # 目标 ≈ 0
  decision_quality:   Δ(有解释 vs 无解释 的决策质量),    # 必须 > 0 才保留
}
assert metrics.decision_quality > 0          # 没有实测改善的解释形态淘汰
assert metrics.overreliance_rate <= THRESHOLD
```

## 7. 降权 / 争议 / 陷阱（对抗核查结论）

> 原样保留对抗核查的降权词（**方向倒置 / 张冠李戴 / 外推过度 / 片面取正面 / 选择性引用 / 证据强度被拉平 / 不可外推 / 过度一般化**）。

- **【high · 事实方向倒置】Vasconcelos（CSCW 2023）被讲反了——「难任务下解释反而增加过度依赖」与一手来源相反。** 论文摘要与 Stanford HAI 解读明确：解释 **CAN 减少过度依赖，且恰恰在 HARD task condition 下减少**（"explanations reduce overreliance for difficult tasks, where manual verification is effortful and so verifying the XAI explanation is less relative effort"），easy/medium 无差异。机制是成本收益：难任务下人工验证更贵 → 读解释相对更划算 → 更可能采纳正确解释。原 JSON 把**正向结论（对难决策更应给可验证解释）错引成反向（对难决策要加摩擦）**，且该错误传导到「难任务上解释最帮倒忙」。**这是全篇唯一影响设计取舍的实质性事实错误，已在 §3、§5 修正**——难决策（是否上线 / 加杠杆）正是本产品核心场景，方向倒置会误导设计取舍。来源：<https://arxiv.org/abs/2212.06823> 摘要、<https://cicl.stanford.edu/papers/vasconcelos2023explanations.pdf>
- **【medium · 引用 URL 张冠李戴】Turpin et al.（2023）原引 URL = arxiv.org/pdf/2307.13702 指向错误论文。** 2307.13702 实为 Lanham et al.（Anthropic）《Measuring Faithfulness in Chain-of-Thought Reasoning》，而 Turpin 那篇真实 ID 是 **arXiv:2305.04388**（NeurIPS 2023）。标题 / 作者 / finding 都对应 Turpin，但 URL 张冠李戴。Turpin 的实证本身真实可靠；问题仅是可追溯性 / 引用卫生——**但在一个主打「verbatim 锚点可追溯」的环节里，引文自身不可追溯是讽刺性瑕疵**。§3 已改用正确 ID。
- **【low · 两篇被并条 + 主 URL 配错 + 过度一般化】Shapley 失效（Huang & Marques-Silva 2023–2024）原引 arXiv:2302.08160。** 2302.08160 是《The Inadequacy of Shapley Values for Explainability》，而被命名为「Refutation」的实际是 **arXiv:2309.03041**（2023-09 提交、2024-02 修订）。核心论断（可把可证无关特征赋最大 Shapley 值）属实。但更该补的诚实性：这些「反驳」**依赖对抗式构造的布尔分类器 / 规则解释场景，并非典型 ML 模型上的普遍现象**，且 SHAP/Shapley 社区对其实务相关性有争议——把它当作「SHAP 不可用」的硬证据**有过度一般化之嫌**，宜标注「在构造性反例中成立，实务普遍性有争议」（§3 已标注）。
- **【medium · 对一手发现的解读外推过度】「Loughran-McDonald 发现高可读性会放大投资者对披露的（双向）依赖……简化语言可被框架效应武器化」。** Loughran-McDonald（2014, JF）的实际结论是「**更好的可读性降低股价波动、提升公司价值**」，并批评 Fog Index 在金融文本中设定不当；**并没有「高可读性双向放大投资者依赖、可被武器化」这一因果论断**。「武器化 / 双向放大」是研究员叠加的**解释性推断**，不是 L-M 的实证结果。框架效应可双向放大判断这点本身有文献支撑，但不应挂在 L-M 名下当作其发现。§3、§5 仅保留「框架中性 / 双向呈现」这一站得住的设计约束。
- **【medium · 把「暧昧 / 条件性」实证讲成「显著正向」】「Robo-advisor 实验显示高透明 + 混合（人可介入）显著降低算法厌恶、提升信任与采用」。** 与之最贴近的 SOTA（Rühr & Berger et al., PACIS 2021）标题就叫《The **Ambivalent** Effect of Transparency on Trust in Robo-advisors》，发现透明与质量是**替代关系（substitutive）**、透明主要在低质量时才提升信任、且存在**负向交互**。「显著降低算法厌恶」是**片面取了正面一侧**，掩盖了 SOTA 的核心警告（透明并非单调有益）。这恰好与本环节「解释不必然改善」的诚实基调一致，故本 dossier **未把它作为「透明=好」的支柱**。
- **【low · 选择性引用】「程序 / 过程透明确实提升信任与感知公平（Grimmelikhuijsen 2023）……explainability 比 accessibility 对信任影响更大」。** 结论本身成立，但呈现得比原文更干净。Grimmelikhuijsen（2023, PAR）**同时明确报告「transparency 的效应在不同决策情境下并不稳健（not robust across decision contexts）」**，且已有 2025 年 Fang 复制研究（Public Administration）对其稳健性再检验。原 JSON 只引正面、漏掉作者自陈的情境不稳健性，且「**感知信任 ≠ 决策质量**」的边界须前置——§3、§4 已补稳健性与复制状态。
- **【low · 证据强度被拉平 / 不可外推】把环节 13 的全部「反向证据」当作可直接落地的设计约束（design_directions 10 条 + pitfalls 10 条）。** 多数 XAI 过度依赖 / 不忠实结论来自**众包 / 通用决策任务**（maze、BIG-Bench、信贷），并非中低频量化策略上线决策这一特定场景的实证；FTT/gist 对「经济翻译提升决策」只有**间接理论支撑**（summary 自己也承认「缺乏稳健因果实证」）。把这些跨域结论当成对本产品的强约束属**外推**——结论方向可信，但「强证据」标签宜下调为「**方向性提示，需在本场景做 A/B 验证**」。本 dossier 已把 §5 第 9 条前置为总基调。

**通用陷阱清单（pitfalls）**

- **最大陷阱：把解释流畅度当成正确性信号。** 研究反复显示流畅 / 详尽的解释本身就抬高盲信（illusion of explanatory depth + 解释作为能力线索），对话式 LLM 解释更甚。让 LLM 当「解释官」恰好踩中这个雷——会系统性诱发过度依赖而非校准信任。
- **假定「说清楚就会改善决策」。** 12.4 万账户 RCT 与 plain-English 不一致效应表明：注意力与动机才是瓶颈，信息清晰度的边际效用有限甚至为零。不要把「翻得好」等同于「决策更好」。
- **LLM 自解释 / CoT 不忠实**：叙事可能 plausible 但与底层闸门真实逻辑脱节（Turpin），构造用户错误心智模型。绝不可让模型自由生成因果性经济故事。
- **SHAP/LIME 归因不稳且会互相矛盾（disagreement problem）**，理论上可把无关特征排在关键特征前。把单次归因直接翻成「因为因子 X 上涨所以…」是高风险误导（**但注意此结论本身的构造性 / 普遍性争议，见上 low 条**）。
- **plain English / 高可读性效果不一致、且框架效应可双向放大判断**，可被（无意或有意）用作框架武器。缺乏框架中性审计的经济翻译会扭曲决策。（**注意：「武器化」不应挂在 Loughran-McDonald 名下，见上 medium 条**）
- **事后解释永不完全保真（Rudin）**：用解释包装黑箱可能延续坏实践；高风险中低频决策应尽量用内生可解释链路而非事后故事。
- **受众分层若做成「同一内容四种措辞」而非「四种可行动单元」**，则只增加维护成本、不增加决策价值；且降层简化时极易丢失不确定性与局限，把概率结论抹成确定结论。
- **监管尚未为 agent 驱动解释背书**：SR 26-2（2026）明确把 genAI/agentic AI 置于范围之外、要求沿用既有治理；**不能宣称「符合模型风险监管」**。EU AI Act 则把「可正确解读 + 人类有效监督」设为硬义务，降层解释不得削弱可监督性。
- **过度依赖在难任务上最严重**——而是否上线 / 是否加杠杆恰是难任务。**此处对策是「可低成本验证的解释 + 降级口吻」而非藏起解释**（已按 §7 high 修正方向）。
- **把不确定性沟通做成单点估计或单向框架**，会让用户混淆「范围宽度」与「置信度」（已知外行常见错误），在 PBO/OOS 衰减等强不确定闸门上尤其危险。

## 8. 开放问题

> 以下为对抗核查点出的、设计方向乐观一带而过的迁移鸿沟与盲区。

1. **验证成本悖论未闭环。** §5 第 2 条援引「降低验证成本」作头等目标，却没意识到对小白（L1/L2），「一键展开到原始夏普 / PBO / 阈值」这一动作本身**验证成本极高**——小白无能力判断 PBO=0.6 是否可信。对低 AI 素养用户，「降低验证成本」与「素养脚手架」是**矛盾的**：你给的可验证锚点对他不可验证。SR 11-7「有效挑战」映射（每 tier 用户能在该 tier 反驳）在 **L1 层近乎不可实现**，需直面而非口号化。
2. **本环节核心动作（LLM 当经济翻译官）与它列出的最强反证构成产品级悖论。** Turpin 不忠实 + illusion of explanatory depth + 对话式 XAI 放大过度依赖——三者叠加意味着「让 LLM 解释」本身可能是错的方向，但缺少**「若证据成立则该不该做 LLM 解释官」的红线判断**。「模板 / 规则约束生成、禁止 LLM 自由编因果」是缓解，但**模板化叙事是否还算「解释」、是否反而牺牲 gist 的有效性，未论证**。
3. **完全缺失非英语 / 中文用户与 A 股散户语境。** 所有披露实证（Adams JFE 英国储户、SEC Plain English、Loughran-McDonald 美股 10-K）都在英美监管文本语境，gist 翻译的**文化 / 语言可迁移性**、中文金融术语的可读性度量（Fog Index 等对中文无效）未提——而本产品明确含 **A 股散户**。
4. **缺少「解释作为合规证据 vs 解释作为决策辅助」的张力。** EU AI Act Art.13/14 要求的「可正确解读 + 可监督」是**合规验收**，与「真的改善决策」是两套指标，可能**彼此冲突**（为合规而堆叠的解释会增加认知负荷、降低决策质量）。研究把两者并列引用却没指出二者可能对立。
5. **未触及对抗性 / 操纵风险。** 反事实工具（DiCE）只一句「可被操纵（Slack et al. 2021）」；更大的产品级风险是——若解释官能被用户 / 策略作者**反向利用**（知道哪个 gist 叙事最能让闸门「看起来通过」），解释层会成为**粉饰过拟合策略的通道**。本环节面向「让小白走完最严谨流程」，解释被用来合理化坏策略的攻击面缺席。
6. **缺少成本 / 延迟 / 可靠性工程视角。** OmniXAI/SHAP/Captum 多方法一致性检查（disagreement check）在每个闸门上跑、再加 LLM 叙事生成，**计算与延迟成本**、以及**解释服务本身的故障模式**（解释挂了是否阻断决策）未评估；「解释账本只读审计轨」的存储 / 隐私（**D2 加密落盘**）也没接上既有决策。
7. **对「渐进披露提升决策」本身缺反证。** §1 诚实说它是组织原则非因果证据，但没引 progressive disclosure 在高风险信息（医疗知情同意、风险披露）上可能因「**藏起关键风险在下一层**」而被批评的文献——**分层本身可被用来把不利信息降权**，这与 framing 武器化是同一风险的另一面，值得单列。

## 9. 参考文献（URL）

- CFA Institute — Explainable AI in Finance: Diverse Stakeholders（2025）：<https://rpc.cfainstitute.org/research/reports/2025/explainable-ai-in-finance>
- Conversational XAI assistant（He, Aishwarya, Gadiraju — IUI 2025）：<https://arxiv.org/abs/2501.17546> ｜ 代码：<https://github.com/delftcrowd/IUI2025_ConvXAI>
- NIST IR 8312 — Four Principles of Explainable AI：<https://nvlpubs.nist.gov/nistpubs/ir/2021/nist.ir.8312.pdf>
- Federal Reserve SR 26-2（2026-04，取代 SR 11-7/SR 21-8）：<https://www.federalreserve.gov/supervisionreg/srletters/SR2602.htm>
- Federal Reserve SR 11-7（被取代，仍为有效挑战概念锚）：<https://www.federalreserve.gov/supervisionreg/srletters/sr1107.htm>
- EU AI Act Art.13（透明）：<https://artificialintelligenceact.eu/article/13/> ｜ Art.14（人类监督）：<https://artificialintelligenceact.eu/article/14/>
- Vasconcelos et al. — Explanations Can Reduce Overreliance（CSCW 2023；§7 high 方向修正）：<https://arxiv.org/abs/2212.06823> ｜ PDF：<https://cicl.stanford.edu/papers/vasconcelos2023explanations.pdf>
- Rudin — Stop Explaining Black Box ML Models（Nature MI 2019）：<https://arxiv.org/abs/1811.10154>
- Turpin et al. — Unfaithful Explanations in CoT（NeurIPS 2023；§7 medium 引用修正，正确 ID 2305.04388）：<https://arxiv.org/abs/2305.04388>
- Reyna — Fuzzy-Trace Theory / gist communication（PNAS 2020）：<https://www.pnas.org/doi/10.1073/pnas.1912441117>
- Adams et al. — Consumer Financial Disclosure RCT（JFE 2021）：<https://www.sciencedirect.com/science/article/abs/pii/S0304405X21000829>
- The Inconsistent Effects of Plain English Disclosures（IJFS/MDPI 2018）：<https://www.mdpi.com/2227-7072/6/1/25>
- Huang & Marques-Silva — Inadequacy of Shapley Values（2023；§7 low）：<https://arxiv.org/pdf/2302.08160> ｜ Refutation（2023-09/2024-02）：<https://arxiv.org/abs/2309.03041>
- Grimmelikhuijsen — Algorithmic Transparency & Perceived Trustworthiness（PAR 2023；§7 low 稳健性保留）：<https://onlinelibrary.wiley.com/doi/full/10.1111/puar.13483>
- Beyond Explainable AI — Post-XAI Research Directions（2026）：<https://arxiv.org/pdf/2602.24176>
- SEC — A Plain English Handbook：<https://www.sec.gov/pdf/handbook.pdf>
- Spiegelhalter et al. — Communicating uncertainty（Royal Society Open Science 2019）：<https://royalsocietypublishing.org/doi/10.1098/rsos.181870>
- SHAP：<https://github.com/shap/shap> ｜ InterpretML（EBM）：<https://github.com/interpretml/interpret> ｜ Alibi：<https://github.com/SeldonIO/alibi> ｜ DiCE：<https://github.com/interpretml/DiCE> ｜ Captum：<https://github.com/pytorch/captum> ｜ OmniXAI：<https://github.com/salesforce/OmniXAI>
