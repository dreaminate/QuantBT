# 33 · 信任 UI / 治理看板（非专家对 AI 量化的信任）

> 机构级 Agent OS 成品环节深挖 · 全程 Opus 4.8 · 对抗式核查已降权 · 重心=前沿研究+概念级推荐 · 不含 file:line 代码接线
> 簇 F

## 1. 一句话定位

信任 UI / 治理看板的核心矛盾，已被 HCI 与金融两条文献线确证：**对非专家，「更多透明 = 更多信任」是错的**——正确目标不是最大化信任，而是「**恰当依赖（appropriate reliance）**」，即让人能区分 agent 对 / 错并据此采纳或驳回。三组最硬的实证支撑这个翻转：(1) 加解释往往不降反升过度依赖，因为解释本身锚定人去同意 AI，解释只有在「**显著降低核验成本**」时才真正减少过度依赖（Vasconcelos 2023 的成本-参与理性模型）；(2) 真正能压过度依赖的是「**认知强制函数**」（先让人独立判断再揭示 AI、按需展开、刻意加摩擦），但代价是用户主观评分最低、且只对高「认知需求」人群更有效——直接构成可用性 / 公平性两难（Buçinca 2021）；(3) 金融侧透明对信任是「**暧昧的 / 有调节的**」：质量差时透明救场、质量好时透明的边际信任收益小（Rühr/Berger 2021），而 Wharton/精算研究揭示了「**可解释性套利**」——模型可被改造到 PD plot 上看着公平、真实定价仍有偏，「抛光的看板让人把可解释性误当问责」。

落到这套「对话出意图、agent 出全部工程、流程即信任」的资产无关中低频 Agent OS：**治理看板不应是「展示 AI 多聪明」的橱窗，而应是一台「校准依赖的仪器」**——把回测过拟合证据（产品已有的 CSCV/PBO/Deflated Sharpe，正是 López de Prado/Bailey 主张披露的「尝试次数 / 多重检验」那类一手对抗证据）渲染成非程序员能在 15 秒做出「批 / 驳 / 升级」判断的**证据包（evidence pack）**，并在高风险节点用认知强制防过度信任。但要诚实标注两条裂缝（见 §7、§8）：HCI 强结论多来自**受控实验、众包工人、非金融领域专家、单次交互**，向「经济学者用户、跨多周期、长期反复使用、真金白银」外推**有不确定性**；且本产品已锁定 **D4 单用户**，机构级治理脚手架（独立验证、谁批了谁的审计轨、职责分离）对「既是作者又是审批人」的个人 operator **部分是表演性的**。

## 2. 前沿 SOTA 与代表系统

产业把「AI 治理 / 模型风险」做成了一类成熟产品（治理底座 + 谱系可视化），但**「为非专家校准依赖的金融研究证据包 UI」几乎是空白**——这一空白论断本身已被对抗核查降权为「假设而非已证市场缺口」（见 §7 medium），但收窄到「经济学者小白 + 金融过拟合证据 + 恰当依赖校准」这一窄切片仍是可建立的差异点。

- **Credo AI** — 专用 AI 治理平台：集中式 AI/模型注册表、标准化风险评估、可审计文档与合规工作流，原生映射 EU AI Act / NIST AI RMF / ISO 42001。对应本产品的治理漏斗 + 谱系登记，是「治理看板」的产品级参照。**定性：偏合规留痕、面向风险官，非为「非专家校准依赖」而设。** <https://www.credo.ai/>
- **IBM watsonx.governance** — 企业级模型风险管理与生命周期治理：实时监控模型 / agent、漂移与异常检测、风险评估工作流，内置全球框架支持。可参考其「**把技术输出翻译成管理层风险洞见**」的看板取向。<https://www.ibm.com/products/watsonx-governance>
- **ValidMind** — 面向 SR 11-7 模型风险管理团队的验证 + 文档自动化平台：把开发 / 验证 / 治理证据结构化，生成审计就绪文档。**对本产品「自动生成可信证据包」的工程化最贴近**（也因此削弱了「证据包 UI 全空白」的主张，见 §7）。<https://validmind.com/>
- **Monitaur** — 部署后模型监控 / 保障平台：数据漂移、概念漂移、偏差与异常实时监控。对应本产品上线后（paper / Binance 实盘）的持续监控看板维度。<https://www.monitaur.ai/>
- **Model Cards / Data Cards / Datasheets 生态** — Mitchell 2019 模型卡 + Gebru 数据表 + Google Data Cards 的结构化「营养标签」，是把「谱系 / 局限 / 评估 / 适用边界」渲染给非专家的事实标准载体；产品 v3 的 19 张模型卡已在此方向。<https://dl.acm.org/doi/10.1145/3287560.3287596>
- **OSFI E-23（监管对 ML 模型风险的扩面）** — 「模型」定义已扩到任何用数据产出输出的算法（含黑箱 / AI），全企业、按风险比例治理（**2027-05-01 全面生效**）。说明黑箱量化策略的治理看板已是监管预期，不是可选项。**但是否实际约束「个人自有资金 operator」存疑，见 §8。** <https://www.osfi-bsif.gc.ca/en/guidance/guidance-library/model-risk-management-guideline-e-23>

## 3. 关键论文（每条带 URL）

- **Explanations Can Reduce Overreliance on AI Systems During Decision-Making** — Vasconcelos et al.（CSCW 2023，PACMHCI，DOI 10.1145/3579605）。翻转既有结论：解释能减少过度依赖，但**仅当它「显著降低核验成本」时**。提出**成本-参与理性模型**——人是策略性地决定要不要核验 AI，而非被动接受；任务越难 / 解释越复杂，人越倾向盲信。设计含义：证据 UI 的目标是把「核验 AI 是否对」的认知成本压到最低。（对抗核查：跨 5 项研究 731 名参与者，characterization 准确，无撤稿。）<https://arxiv.org/abs/2212.06823>
- **To Trust or to Think: Cognitive Forcing Functions Can Reduce Overreliance on AI** — Buçinca et al.（CSCW 2021，DOI 10.1145/3449287）。认知强制函数（先让人独立判断再看 AI、按需展开、加延迟 / 摩擦）显著优于简单 XAI 地降低过度依赖；但**用户给降依赖最强的设计打了最低主观分**，且**对高 Need-for-Cognition 人群受益更多**——可用性与公平性两难。**【对「小白失灵 / 制造不公平」的外推已被对抗核查降权，见 §7 low】** <https://arxiv.org/abs/2102.09692>
- **From Trust to Appropriate Reliance: Measurement Constructs in Human-AI Decision-Making** — Raees & Papangelis（综述，2026，arXiv:2604.23896）。系统区分 **信任（主观信念）/ 依赖（观察行为）/ 恰当依赖（能区分对错并据此行动）**；批评「只测信任」不够——高信任未必带来恰当依赖。推荐两阶段决策协议（先独立判断 → 看 AI → 可修改）与 RAIR/RSR 等逐案判别指标。（对抗核查：2604.x 的 arXiv ID 给当前日期 2026-06 是合法的、非编造；为 survey/review。）<https://arxiv.org/abs/2604.23896>
- **Should I Follow AI-based Advice? Measuring Appropriate Reliance in Human-AI Decision-Making** — Schemmer et al.（2022，arXiv:2204.06916）。定义 **RAIR（人因正确 AI 而改对）与 RSR（人正确拒绝错误 AI）**，把「互补团队表现」拆成依赖恰当性问题。给出可量化北极星：不是「用户多信任 agent」，而是「**用户能否在 agent 错时驳回、对时采纳**」。**【引用元数据已被对抗核查修正，见 §7 low：原 JSON 给的 "DOI 10.1145/3287560 系列" 实为 Model-Cards/FAccT 基础 DOI，不属于 Schemmer；"2022/2023" 混淆了 2204.06916 与另一篇 Schemmer 2023（arXiv:2302.02187）。RAIR/RSR 实质正确，仅引用句柄错。】** <https://arxiv.org/abs/2204.06916>
- **The Ambivalent Effect of Transparency on Trust in Robo-advisors** — Rühr, Berger, Hess（PACIS 2021 Proceedings 149）。金融实验：透明 × 质量存在**负向交互（替代关系）**——质量差时透明显著救信任，质量好时透明的边际信任收益小。**【对抗核查修正：透明与质量都有「显著正向主效应」，「质量好时边际小」是交互项一侧、被原 JSON 略微低估；且为单次感知 / 意向问卷、操纵刺激、非真金白银纵向，外推到「经济学者 · 跨多周期 · 真金白银」弱，见 §7 low】** <https://aisel.aisnet.org/pacis2021/149/>
- **Understanding the Effects of Miscalibrated AI Confidence on User Trust, Reliance, and Decision Efficacy** — Li et al.（CHI 2024，arXiv:2402.07632）。**误校准的 AI 置信度会损害恰当依赖且用户难以察觉**；告知用户「校准水平」能帮其识破误校准，却会降低对未校准 AI 的信任、推高 under-reliance、净决策效能无提升。提示：**展示置信度 / 不确定性必须先保证其本身被严格校准，否则适得其反。**（对抗核查：characterization 准确。）<https://arxiv.org/abs/2402.07632>
- **When AI Transparency Backfires / 可解释性套利** — Xin, Hooker, Huang（2025，*Insurance: Mathematics and Economics*；Wharton 报道）。可把模型改造到 PD plot 上看着公平（如驾驶员年龄）、真实客户预测仍不变——「**解释变了、歧视没变**」（explanation theater）。董事会 / 高管易把抛光看板误当问责。强制要求：**在真实样本与真实决策（而非合成场景）上验证，把可视化当信号而非证据。**（对抗核查：verified。）<https://knowledge.wharton.upenn.edu/article/when-ai-transparency-backfires/>
- **How Backtest Overfitting Leads to False Discoveries + Deflated Sharpe Ratio** — Bailey & López de Prado（*Significance* 2021；DSR：SSRN 2460551）。几乎所有回测都缺失的关键信息是「**尝试了多少次试验**」；不披露试验数无法评估回测。DSR 在控制样本长度 / 偏度 / 峰度 / 试验数后**校正显著性阈值**。产品已用 CSCV/PBO/DSR——这正是该渲染进证据包、面向非专家解释的一手对抗证据。**【对抗核查修正：把 DSR 输出叫「真阳性概率」属轻微夸大——它是「选择偏差 / 多重检验的紧缩（deflation）阈值校正」、需要「有效独立」试验数 N（要去相关 / 聚类，朴素的"跑了多少次回测"会高估校正），不是已校准的 TP 率、也不修正系统性低估，见 §7 low】** <https://academic.oup.com/jrssig/article/18/6/22/7038278> ｜ DSR：<https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2460551>
- **Progressive Disclosure: When, Why and How Do Users Want Algorithmic Transparency Information** — Springer & Whittaker（ACM TiiS Vol 10 No 4, 2020，DOI 10.1145/3374218）。分层 / 按需披露：高层概览（高亮 / 颜色）→ 可展开细节（置信度 / 参考）。让不同知识水平用户各取所需、避免信息过载；**前提是展开层确有实质信息，否则被忽视**。对「小白默认极简、可下钻到 PBO/谱系」的分层设计有直接支撑。（对抗核查：原 JSON 引 ResearchGate、缺 DOI/年份，minor 元数据瑕疵；实质准确。）<https://dl.acm.org/doi/10.1145/3374218>
- **Algorithm Aversion: People Erroneously Avoid Algorithms After Seeing Them Err** — Dietvorst, Simmons, Massey（J. Experimental Psychology: General, 2014）。人**在见到算法出错后**更少选择算法、对其信心下降——即便算法仍优于人类。**【对抗核查降权：支持「不对称 / 更快的信心流失」，但原 JSON 的「崩盘式厌恶 / 一次出错就弃用」属戏剧化夸大——研究测的是「选择减少 / 信心下降」，非灾难性弃用；「与初期过度信任同币两面」是研究员综合而非单一已证动态，见 §7 low】** <https://doi.org/10.1037/xge0000033>

## 4. 机构最佳实践 / 标准

> 通用警示（见 §8）：以下「监管脊柱」均为机构 / 受监管实体语境，**是否在法律上约束「个人自有资金 operator」存疑**——应作为「最严谨流程的设计骨架与北极星」引用，而非默认合规义务，避免 compliance cargo-culting。

- **SR 11-7（美联储 / OCC 模型风险管理）** — 维护全企业模型清单（用途 / 负责人 / 验证状态 / 风险分级 / 上次验证日 / 已知局限与补偿性控制），三支柱 = 稳健开发 + 独立验证 + 治理。看板应把「**技术输出翻译成管理层风险洞见**」。**注意：「独立验证」预设组织内有职责分离的第二双眼睛——D4 单用户下此前提不成立（见 §8）。** <https://www.federalreserve.gov/supervisionreg/srletters/sr1107.htm>
- **NIST AI RMF 1.0（NIST AI 100-1）** — 七项可信特征（有效可靠 / 安全 / 安保韧性 / 可问责且透明 / 可解释可诠释 / 隐私增强 / 公平）；透明 = 「关于系统及其输出的信息对交互者的可得程度」。**GOVERN + MAP + MEASURE + MANAGE** 四职能可作为治理漏斗骨架。<https://nvlpubs.nist.gov/nistpubs/ai/nist.ai.100-1.pdf>
- **EU AI Act 第 14 条「有意义的人类监督」** — 高风险系统须使监督者能**理解其能力与局限、警觉自动化偏误、正确诠释输出、可决定不用或中止**，含「系统自身不能覆盖」的内置操作约束。直接对应本产品实盘 agent 的「仅警告 + 规则停」与不可绕过的护栏。**注意：个人 / 单用户量化工具是否属其「高风险」范围是开放问题（见 §8）。** <https://artificialintelligenceact.eu/article/14/>
- **CFA Institute（2025 报告 + 道德准则）** — 把**可解释性升格为对客户的伦理披露义务**——「黑箱」与披露重大事实 / 有合理依据 / 清晰沟通的责任冲突；部分客户没有高可解释性就不能投资。面向非专家的信任 UI 是合规交付物，不是锦上添花。**注意：CFA 准则约束持证人对客户的行为，单用户自营场景不直接落入。** <https://www.cfainstitute.org/about/press-room/2025/explainable-ai-in-finance-2025>
- **企业级 HITL 审批模式** — 按风险分级路由（低风险直通 / 中风险快验 / 高风险给专家配富上下文）；关键是给审批人「**证据包**」——决定「15 秒批 vs 15 分钟查」的差别就在证据包；全程不可变审计轨迹（谁 / 何时 / 批驳 / 批注）。<https://www.moxo.com/blog/human-in-the-loop-automation-software>
- **OSFI E-23（2027-05-01 全面生效）** — 「模型」扩面到任何用数据产出输出的算法（含黑箱 / AI），按风险比例全企业治理。印证黑箱量化策略的治理看板已成监管预期。<https://www.osfi-bsif.gc.ca/en/guidance/guidance-library/model-risk-management-guideline-e-23>

## 5. 对 QuantBT 这套架构的推荐方向（概念级）

> 仅给概念级方向，不点 file:line、不排实施计划。

1. **把北极星指标从「信任」改成「恰当依赖」。** 看板的成功标准不是用户多信任 agent，而是用户能在 agent 给出弱策略时**驳回**、给出强策略时**采纳**（RAIR/RSR）。可用两阶段协议（先让用户用自己的话写下经济判断 / 预期 → 再揭示 agent 结论与证据 → 记录其是否改判）作为产品内依赖校准机制，并沉淀成可观测治理指标。**清醒前提（见 §8）**：live trading 不给「per-case ground truth」，RAIR/RSR 的「正确与否」标签**事前不可知、事后有噪 / 单路径**——本场景下「恰当依赖」是可借鉴的设计范式，但**不是可直接照搬的度量**，需用代理指标（如「用户改判 → 后续是否触发护栏 / 回撤」）近似而非声称严格 RAIR/RSR。
2. **证据包优先于解释。** 每个待批节点渲染成一份「**15 秒可判**」的证据包，而非一堆图表。把已有对抗证据（CSCV/PBO/Deflated Sharpe、尝试次数 / 多重检验、OOS walk-forward 无泄露证明）做成首屏「红 / 黄 / 绿 + 一句话为什么」，细节按需下钻——遵循成本-参与模型：核验成本越低、过度依赖越少。**但要直面 §8 的张力**：把多重检验 / 过拟合判决压成红绿灯本身是有损抽象，可能误导（如「绿 DSR 但有效 N 极小 / 策略没见过的 regime」）——红绿灯必须**一键暴露其有效 N、试验聚类、适用域**，否则就成了它自己列为陷阱的「解释剧场」。
3. **在高风险闸口刻意加认知摩擦（认知强制函数），低风险直通。** 批准上 paper 的策略可轻量；批准走 Binance 实盘、或杠杆 / 风险敞口跨阈值时，强制用户先**独立陈述经济理由**再看 agent 结论，并默认折叠 agent 的「推荐答案」。但要意识到这会降低主观满意度且对不同用户不均等（Buçinca）——**用风险分级而非全局施加**。**清醒前提（见 §8）**：在 Binance 实时行情下，强制摩擦不只是「满意度低」——它可能**延迟 kill-switch、构成操作不安全**；高风险摩擦应区分「**事前研究闸口**（可慢）」与「**实时干预闸口**（不可加延迟）」，后者用规则护栏 + 事后复核，而非把人卡在摩擦里。
4. **谱系即证据，杜绝「解释剧场」。** 看板上每一项数字 / 结论都必须可一键回溯到真实样本与真实决策（数据源 → 因子 → 参数 → 回测窗口 → 实盘成交），而非合成场景的漂亮图。把「这是在真实数据上、不是在挑出来的窗口上」作为显式可信标记。对置信度 / 不确定性展示，**先保证其本身被严格校准**，否则按 Li 2024 反而有害。**比例性提醒（见 §8）**：对 D4 单用户，全套不可变 lineage（OpenLineage/Marquez/Croissant）是重工程——应先做「足够轻的 provenance 日志」满足「可回溯真实样本」，把企业级谱系基建当可选增强而非默认。
5. **自适应披露深度，而非一刀切透明。** 依据 Rühr/Berger 的暧昧效应——**策略证据弱时反而要更主动、更坦诚地披露弱点**（透明在质量差时最能救信任）；证据强时可精简。把「诚实暴露局限 / 失败模式 / 未复现风险」做成一等公民，而非埋在脚注。**修正口径（见 §7 low）**：Rühr/Berger 的透明主效应仍是正向，「质量好时边际小」是替代 / 交互项——故「证据强就少披露」要克制，宁可「证据强时把披露做轻、但不抹掉关键风险信号」。
6. **治理漏斗显式三态可视化。** 用监管脊柱（SR 11-7 清单 / 分级 / 独立验证 · NIST GOVERN-MAP-MEASURE-MANAGE · EU AI Act 第 14 条人类监督 · CFA 对客户可解释性披露）作为漏斗阶段骨架，每个策略在漏斗中的位置、卡在哪一关、缺什么证据一目了然——把「流程即信任」落成一条**可见、可审计、不可绕过**的轨道，护栏由系统强制、agent 不能自我覆盖。**口径修正（见 §4、§8）**：这些框架作为「最严谨流程骨架」引用，**不宣称「符合 X 监管」**；尤其「独立验证」「谁批了谁」在单用户下是过程仪式（帮自我复核），不是真职责分离。
7. **为「经济学者小白」设计，而非为审计员设计。** 现有治理平台（Credo AI/ValidMind/watsonx.governance）都偏合规留痕、面向风险官。差异化空白点是「让非程序员经济学者把经济直觉转成可信决策」的证据包 UI——用**经济语言**（这条策略赚的是什么风险溢价、在什么市场状态会失效）而非统计黑话作为顶层，统计严谨性（PBO/DSR）作为可下钻的支撑层。**【「几乎空白」已被对抗核查降权为假设，见 §7 medium——把它当差异化方向，不当已证市场缺口。】**
8. **把不可变审计轨迹与可问责性做成信任基座。** 谁（人 / agent）在何时基于哪份证据做了批 / 驳 / 改，全程留痕且对用户可见。这既对接 EU AI Act/SR 11-7 的问责精神，也是非专家建立「系统对我负责、我能复盘」这一**过程性信任**的关键——契合「流程即信任」。但在 D4 下其价值主要是「**个人对自己过去判断的可复盘**」，而非组织问责。
9. **设计「错误后的信任修复」路径。** 算法厌恶与过度信任是同一硬币两面：同一非专家可能初期盲信、见 agent 出错一次后又转向回避（Dietvorst 的不对称信心流失）。信任 UI 需**同时防过度信任与防一次性错误导致的回避**——出错后主动展示「这次错在哪、属哪类已知失败模式、护栏是否按预期触发」，把单次错误转成校准信号而非弃用诱因。**【「崩盘式厌恶」措辞已被对抗核查降权为戏剧化，见 §7 low——修复路径合理但本身是推测性建议，应做成可 A/B 的假设。】**

## 6. 架构级参考（少量伪代码 / schema 草图，非代码接线）

> 仅示意，不接线到现有代码。

**6.1 证据包对象 schema 草图（首屏红绿灯 + 可下钻锚点 + 适用域）**

```yaml
evidence_pack:
  gate_id: "go_live_binance_lev2x"        # 待批节点
  verdict: "yellow"                        # red/yellow/green = 15 秒可判
  economic_headline: "赚的是横截面动量溢价；在低分散度/急速反转 regime 会失效"
  one_line_why: "OOS 夏普稳健，但有效试验数偏小、未见过 2020-03 式崩盘"
  drilldown:                               # 按需展开（降低核验成本，非装饰）
    - metric: PBO
      raw: 0.41; threshold: 0.50; passed: true
    - metric: Deflated_Sharpe
      raw_SR: 1.8
      effective_N_trials: 7                # 关键：去相关/聚类后的有效 N，非朴素回测次数
      deflated_threshold: 1.3
      note: "DSR=选择偏差紧缩的阈值校正，非'真阳性概率'"   # §7 low 修正口径
    - metric: OOS_walk_forward
      leakage_proof: true
      regimes_seen: ["trend","chop"]
      regimes_unseen: ["crisis_2020Q1"]    # 显式暴露适用域空洞，杜绝解释剧场
  provenance_ref: "lineage://real_sample/..."   # 必须指向真实样本/真实成交
  synthetic_or_cherry_picked: false              # 显式可信标记
  calibration_checked: true                      # 置信度先校准再展示(Li 2024)
```

**6.2 两阶段恰当依赖协议（认知强制，仅高风险闸口；示意）**

```python
def high_risk_gate(strategy, user, risk_tier):
    if risk_tier == "low":                 # 上 paper：轻量直通
        return show_pack_and_approve(strategy)

    # 实时干预闸口：禁止加延迟摩擦（§5.3 / §8）——走规则护栏
    if risk_tier == "live_intervention":
        return rule_guardrail_then_post_review(strategy)  # 人不被卡在摩擦里

    # 事前研究闸口（实盘/加杠杆审批）：可加认知强制
    user_thesis = elicit_independent_economic_thesis(user)  # 先独立判断
    pack = build_evidence_pack(strategy)                    # 后揭示
    pack.collapse_recommendation_by_default()               # 默认折叠"推荐答案"
    decision = user.decide(pack)
    # 代理依赖指标：本域无 per-case ground truth，用代理而非声称严格 RAIR/RSR
    log_appropriate_reliance_proxy(user_thesis, decision, pack)
    audit_trail.append(who=user, when=now(), evidence=pack.id, action=decision)
    return decision
```

**6.3 自适应披露深度（按证据强度，而非一刀切；示意）**

```
strength = evidence_strength(strategy)        # PBO/DSR/OOS 综合
if strength == "weak":
    disclosure = MORE_PROACTIVE               # 质量差时透明最救场(Rühr/Berger)
    surface_failure_modes_first()             # 弱点做成一等公民、不埋脚注
else:                                          # 证据强
    disclosure = LIGHTER                       # 边际收益小→做轻
    keep_key_risk_signals()                    # 但不抹掉关键风险信号(§5.5 修正)
# 反例自检：红绿灯不得掩盖有效 N / 适用域空洞，否则即"解释剧场"
assert pack.exposes(effective_N) and pack.exposes(regimes_unseen)
```

## 7. 降权 / 争议 / 陷阱（对抗核查结论）

> 原样保留对抗核查的降权词（**夸大 / 争议 / 撤稿 / 二手 / 不可外推 / 引用张冠李戴 / 假设而非已证 / 戏剧化 / 片面取正面**）。

- **【medium · 空白市场主张属假设而非已证（whitespace-overclaim / 难以证伪）】「为非专家校准依赖的金融研究证据包 UI 几乎是空白——这正是你们可建立的差异点」。** 「几乎空白」是**断言、未经竞品扫描证实**；研究自己就列了 ValidMind（SR 11-7 证据包）、watsonx.governance（把技术输出翻译成管理层风险洞见）、Credo AI、Monitaur——它们已在做结构化证据打包和部分面向非专家的风险翻译。真正新颖的切片很窄（「经济学者小白 + 金融过拟合证据 + 恰当依赖校准」），但「几乎空白」有在**未验证的市场缺口上立差异化论点**的风险。**按假设处理，不当 finding（§5.7 已据此弱化口径）。**
- **【low · 引用元数据张冠李戴】Schemmer RAIR/RSR 原引 "Schemmer et al., 2022/2023"、alt 标题 + "DOI 10.1145/3287560 系列"。** RAIR/RSR 定义于 **arXiv:2204.06916**（2022，*Should I Follow AI-based Advice? Measuring Appropriate Reliance in Human-AI Decision-Making*）。原引的 DOI 10.1145/3287560 实为 **Mitchell Model Cards 的 FAccT-2019 基础 DOI**（研究在 sota_systems 里对 Model Cards 用 10.1145/3287560.3287596 是对的）——它**不属于 Schemmer**；"2022/2023" 与 alt 标题还混淆了另一篇 Schemmer 2023（*Appropriate Reliance on AI Advice: Conceptualization and the Effect of Explanations*，arXiv:2302.02187）。**RAIR/RSR 实质正确，仅引用句柄错**（§3 已改用正确 ID）。
- **【low · 轻微夸大 / 已知地雷】Deflated Sharpe Ratio「在控制样本长度 / 偏度 / 峰度 / 试验数后给出『真阳性』概率」。** DSR 是**选择偏差 / 多重检验的紧缩（deflation）**：它针对「N 个（有效、可能聚类的）试验中的**最大**夏普」、偏度、峰度调整显著性阈值，返回在该选择下真实 SR > 0 的概率。把它叫「**真阳性概率（true-positive probability）**」**轻微夸大**——它是阈值 / 紧缩校正，不是已校准的 TP 率、也**不修正系统性低估**；且 N 是「**有效独立**」试验数（需去相关 / 聚类），朴素的「跑了多少次回测」会**高估**校正。方向正确，措辞需收紧（§3、§6.1 已收紧口径）。
- **【low · 片面取正面 / 把暧昧讲成主效应小】Rühr/Berger「质量好时透明的边际信任收益小」→ 用来论证「证据强就别一刀切披露」。** PACIS-2021 实际报告**透明与质量都有强正向主效应**，外加一个**负向（替代）交互**。研究的「质量好时边际 / 暧昧」读法**只取了交互项**、低估了透明的正主效应。故「证据强时透明买不到多少」是边际 / 替代故事，而非「透明中性」。自适应披露的设计含义站得住，但**实证主张比原文软**。另：单次感知 / 意向问卷、操纵刺激、非真金白银纵向——外推到「经济学者 · 跨多周期 · 真金白银」**弱**（研究已诚实标注）。§5.5 已修正口径。
- **【low · 外推过度（是研究员推断、非 Buçinca 发现）】「认知强制只对高 Need-for-Cognition 人群有效」→「对小白经济学者可能失灵 / 制造不公平」。** 方向忠实，但**外推是研究员的推断、不是 Buçinca 的发现**。论文显示 CFF 让高 NFC 参与者**受益更多**、且最强去偏设计主观评分 / 偏好最低（可用性权衡）。它**并未确立** CFF 对低 NFC 用户在金融任务上「失灵」，也未确立效应能迁移到「反复使用的领域专家」（被试为众包工人、单次、非金融）。「对小白失灵 / 制造不公平」是**可信假设、但被以高于证据所允许的确定性陈述**。§5.3 保留为「需 A/B 的设计权衡」。
- **【low · 戏剧化】算法厌恶被讲成「见一次 agent 出错后又骤然弃用……崩盘式厌恶（error-driven trust collapse）」。** Dietvorst et al. 2014 显示人**在见到算法出错后**更少选择 / 更不信任算法——即便算法仍优于人。这支持「不对称 / 更快的信心流失」，但「**崩盘式**」与「一次出错 → 弃用」**夸大了量级**；研究测的是「选择减少 / 信心下降」，非灾难性弃用；「与初期过度信任同币两面」是研究员综合、非单一已证动态。「错误后信任修复」建议合理但**推测性**（§5.9 标注为可 A/B 假设）。
- **【low · 二手 / 未证实，按存疑排除】「动态置信度显示降低飞行员自动化偏误」（航空）。** 研究**已正确标注为二手、未取得一手出处（"存疑"）**。核查确认：无干净一手来源浮现，它作为二手综合流传（如被一篇 2025 临床 DSS 论文转引、而非航空一手研究）。**仅在此背书既有降权——绝不可作为设计依据引用。** 参见转引出处：<https://arxiv.org/pdf/2501.16693>
- **总评（对抗核查 verdict 摘录）**：对一次对抗 pass 而言异常扎实——**每篇论文、系统、监管都真实且实质准确，无撤稿、无编造 arXiv ID**（2604.x 给 2026-06 合法），研究已诚实自标其两条最弱链（航空飞行员条 "存疑"、HCI 向经济学者 / 多周期 / 真金白银的外推鸿沟）。可辩护的批评是**措辞与触及范围、非真伪**：(1) Schemmer 引用交叉污染；(2) DSR 轻微夸大为「真阳性概率」；(3) Rühr/Berger 透明主效应正向、「质量好时边际小」被低估；(4) Buçinca「对小白失灵 / 不公平」与 Dietvorst「崩盘式」推断的确定性高于实验所允许；(5) 「金融证据包 UI 几乎空白」是断言、未对其自列工具（ValidMind/watsonx）证实。**最重要的遗漏是领域契合、非引用问题**（见 §8）。

**通用陷阱清单（pitfalls）**

- **「更多透明 = 更多信任」是被证伪的**：加解释常不降反升过度依赖，因为解释锚定人去同意 AI（Vasconcelos 2023）。解释只有在显著降低核验成本时才有效，否则就是装饰。
- **解释剧场 / 可解释性套利**：模型可被调到 PD plot 等可视化上看着公平 / 合理、真实决策仍有偏；抛光看板让决策者把「可解释性」误当「问责」（Wharton 2025）。**必须在真实样本与真实决策上验证。**（本环节自身风险：把 CSCV/PBO/DSR 压成红绿灯就是有损抽象，可能成为它自己的解释剧场——见 §5.2、§8。）
- **认知强制函数的双重代价**：最能降过度依赖的设计用户主观评分最低（招致弃用 / 绕过风险），且对高认知需求人群受益更多、对小白可能不均等（Buçinca 2021）。**不能全局施加。**
- **展示未经校准的置信度 / 不确定性会反噬**：误校准的 AI 置信度损害恰当依赖且用户难察觉；告知校准水平虽能帮识破却会推高 under-reliance（Li 2024）。**先校准再展示。**
- **只测 / 只优化「信任」是错的指标**：高信任可与过度依赖共存。应转向恰当依赖（RAIR/RSR）等逐案判别指标（2026 综述）——但 live trading 无 per-case ground truth，须用代理而非声称严格 RAIR/RSR（见 §8）。
- **透明的暧昧 / 反向效应**：质量好时多披露边际收益小，盲目堆披露还可能稀释关键信号（Rühr/Berger 2021）。**需自适应而非一刀切。**
- **证据外推的诚实边界**：上述 HCI 强结论多来自受控实验、众包工人、非金融领域专家、单次交互；向「经济学者用户、跨多周期、长期反复使用、真金白银」外推**有不确定性，需自建用户研究验证**。
- **二手 / 未证实数字按存疑处理**：如「动态置信度显示让飞行员减少自动化偏误」为搜索结果转述、未取得一手出处，**不应作为设计依据直接引用**。
- **算法厌恶与过度信任是同一硬币两面**：同一非专家可能初期盲信、见一次出错后又转向回避（Dietvorst）。信任 UI 需同时防两端，设计「错误后的信任修复」路径（**"崩盘式" 措辞已降权为戏剧化，见 §7 low**）。

## 8. 开放问题

> 以下为对抗核查点出的、设计方向乐观一带而过的迁移鸿沟与盲区。

1. **Crypto/Binance 实时 regime 下的「摩擦即操作不安全」未闭环。** 几乎所有被引 HCI 证据都是**异步单次决策的实验室任务**。paper/Binance 速度的实时治理看板面临**时间压力**——此时认知强制摩擦不只是「满意度低」，**可能延迟 kill-switch、构成操作不安全**。研究从未正面处理「高风险闸口强制摩擦」在快市场中的延迟 / 紧迫性权衡（§5.3 已区分事前 / 实时闸口，但这是缓解、非解决）。
2. **D4 单用户现实掏空了进口的机构脚手架。** 整套信任 / 治理 / 审计轨装置（SR 11-7 模型清单、独立验证、三道防线、HITL 审批路由）都**预设一个有职责分离的组织**。对「既是作者又是审批人」的单经济学者 operator，「独立验证」与「谁批了谁」的审计轨**部分是表演性的**——第二双眼睛不存在。研究进口了机构脚手架却未处理这一点（§5.6/§5.8 已改口径为「自我复盘」而非「组织问责」，但本质张力仍开放）。
3. **RAIR/RSR 的构念效度在事前不可知 ground truth 下崩塌。** RAIR/RSR 需要知道 AI「是否正确」才能评「依赖是否恰当」。**live trading 事前不知道一条策略好坏（事后也有噪 / 单路径）。**「恰当依赖」在有已知答案的实验室任务里定义良好；研究把它**移植到无干净正确标签、无 per-case ground truth 的领域**——这是它从未处理的**根本可度量性鸿沟**。§5.1 改为「用代理指标近似」，但代理指标本身的有效性未验证。
4. **两阶段协议会被重复单用户「玩坏」（adversarial habituation）。** 「强制用户先陈述经济论点再看 agent」**预设善意参与**。一个反复的单用户会很快学会**随手敲一句废话论点来解锁 agent 答案**（摩擦退化成减速带仪式）。HCI 研究测的是**首次接触的众包工人**、非「天天玩同一套」的对抗性习惯化；一旦同一用户每天「玩坏」它，RAIR/RSR 式校准指标如何退化，无讨论。
5. **把 CSCV/PBO/DSR 压成「15 秒红绿灯」与「禁止解释剧场」自相矛盾。** 把多重检验 / 过拟合判决压成红绿灯给非程序员，本身是**有损抽象、可能误导**（如「绿 DSR 但有效 N 极小 / 策略没见过的 regime」）。研究一边警告「抛光看板冒充问责」，一边推荐恰恰要建一个抛光的红绿灯层——**这一矛盾未被审视**（§5.2/§6.3 加了「红绿灯须暴露有效 N / 适用域空洞」的自检作为缓解，但缓解是否够，开放）。
6. **未处理责任 / 监管适用性范围界定。** SR 11-7（美国银行监管）、OSFI E-23（加拿大 FRFI）、EU AI Act 第 14 条（EU 高风险 + 个人 / 单用户量化工具是否在范围内的悬而未决问题）、CFA 准则（约束持证人对客户）被当作统一「监管脊柱」引用，但**没有一条直接约束「运营自有资金的单个个人」**。研究把合规框架当设计北极星却**没核查它们是否真适用于本部署**——有 compliance cargo-culting 风险（§4 已加范围警示，但「对单用户究竟哪些适用」仍需法律 / 产品判断）。
7. **为单用户建 / 维护谱系骨架的成本 vs 回报。** 「每个数字可回溯到真实样本 / 真实决策（谱系）」经 OpenLineage/Marquez/Croissant 落地是**大工程承诺**。对单用户研究工具，研究**没权衡完整不可变 lineage 是否值得 vs 更轻的 provenance 日志**——它进口了企业级治理工具却**没给出比例性论证**（讽刺的是这正违反了 E-23 自己倡导的「按风险比例」原则）。§5.4 已建议「先做足够轻的 provenance」，但临界点未定。

## 9. 参考文献（URL）

- Vasconcelos et al. — Explanations Can Reduce Overreliance（CSCW 2023，DOI 10.1145/3579605）：<https://arxiv.org/abs/2212.06823>
- Buçinca et al. — To Trust or to Think: Cognitive Forcing Functions（CSCW 2021，DOI 10.1145/3449287）：<https://arxiv.org/abs/2102.09692>
- Raees & Papangelis — From Trust to Appropriate Reliance（综述，2026，arXiv:2604.23896）：<https://arxiv.org/abs/2604.23896>
- Schemmer et al. — Should I Follow AI-based Advice?（RAIR/RSR，2022，arXiv:2204.06916；§7 low 引用修正）：<https://arxiv.org/abs/2204.06916> ｜ 相关 Schemmer 2023（arXiv:2302.02187）：<https://arxiv.org/abs/2302.02187>
- Rühr, Berger, Hess — The Ambivalent Effect of Transparency on Trust in Robo-advisors（PACIS 2021 Proc. 149；§7 low）：<https://aisel.aisnet.org/pacis2021/149/>
- Li et al. — Miscalibrated AI Confidence（CHI 2024，arXiv:2402.07632）：<https://arxiv.org/abs/2402.07632>
- Xin, Hooker, Huang — When AI Transparency Backfires / 可解释性套利（2025，Insurance: Math & Economics；Wharton 报道）：<https://knowledge.wharton.upenn.edu/article/when-ai-transparency-backfires/>
- Bailey & López de Prado — Backtest Overfitting / Number of Trials（Significance 2021）：<https://academic.oup.com/jrssig/article/18/6/22/7038278> ｜ Deflated Sharpe Ratio（SSRN 2460551；§7 low 口径修正）：<https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2460551>
- Springer & Whittaker — Progressive Disclosure（ACM TiiS Vol 10 No 4, 2020，DOI 10.1145/3374218）：<https://dl.acm.org/doi/10.1145/3374218>
- Dietvorst, Simmons, Massey — Algorithm Aversion（JEP: General 2014；§7 low）：<https://doi.org/10.1037/xge0000033>
- 航空「动态置信度显示降低飞行员自动化偏误」（**二手 / 未证实，按存疑排除，转引出处仅供溯源**）：<https://arxiv.org/pdf/2501.16693>
- SR 11-7（美联储 / OCC 模型风险管理）：<https://www.federalreserve.gov/supervisionreg/srletters/sr1107.htm>
- NIST AI RMF 1.0（NIST AI 100-1）：<https://nvlpubs.nist.gov/nistpubs/ai/nist.ai.100-1.pdf>
- EU AI Act 第 14 条（有意义的人类监督）：<https://artificialintelligenceact.eu/article/14/>
- CFA Institute — Explainable AI in Finance 2025（+ Code & Standards）：<https://www.cfainstitute.org/about/press-room/2025/explainable-ai-in-finance-2025>
- OSFI Guideline E-23（2027-05-01 生效）：<https://www.osfi-bsif.gc.ca/en/guidance/guidance-library/model-risk-management-guideline-e-23>
- 企业级 HITL 审批模式（行业综述）：<https://www.moxo.com/blog/human-in-the-loop-automation-software>
- Credo AI：<https://www.credo.ai/> ｜ IBM watsonx.governance：<https://www.ibm.com/products/watsonx-governance> ｜ ValidMind：<https://validmind.com/> ｜ Monitaur：<https://www.monitaur.ai/>
- Mitchell et al. — Model Cards（FAccT 2019，DOI 10.1145/3287560.3287596）：<https://dl.acm.org/doi/10.1145/3287560.3287596>
- Model Card Toolkit（Google）：<https://github.com/tensorflow/model-card-toolkit> ｜ Croissant（MLCommons）：<https://github.com/mlcommons/croissant>
- OpenLineage / Marquez：<https://openlineage.io/> ｜ Captum：<https://github.com/pytorch/captum> ｜ SHAP：<https://github.com/shap/shap> ｜ AIF360：<https://github.com/Trusted-AI/AIF360>
