# 29 · LLM 引导的因子/alpha 生成（look-ahead/记忆污染陷阱）

> 机构级 Agent OS 成品环节深挖 · 全程 Opus 4.8 · 对抗式核查已降权 · 重心=前沿研究+概念级推荐 · 不含 file:line 代码接线
> 簇 E

## 1. 一句话定位

本环节回答一个对「资产无关中低频 + 流程即信任」系统极其凶险、且正在快速恶化的问题：**让 LLM 去「想出」公式因子 / alpha（Alpha-GPT、AlphaAgent、QuantaAlpha、Hubble 一类 formula-alpha miner），看起来生产力暴增，但它带来一类传统回测护栏抓不到的新泄露——参数记忆泄露（parametric-memory leakage）：模型在预训练语料里「已经见过」未来的价格、新闻、研报与异象，于是它「发现」的因子在训练截止日之前的样本里 IC/Sharpe 漂亮，越过截止日就坍塌**。最硬的实证锚点是《Profit Mirage》（arXiv 2510.07920）：一批 LLM 交易 agent 在训练截止后 Sharpe 衰减约 51%–62%（**重要降权见 §7：原 JSON 写「9 agents、FinMem worst」两处不准——出现衰减的是 5 个具名 LLM agent；「9」是 FactFin 的九个 baseline；且 Sharpe 维度的「最差」是 FinCON 62.23%、与 FinMem 并列，FinMem 仅在『总收益』衰减 71.85% 上单独最差**）。第二根锚点是 Gao-Jiang-Yan（CUHK）《A Test of Lookahead Bias in LLM Forecasts》（arXiv 2512.23847）：其 look-ahead 指标在样本内「materially positive」，越过截止日「collapses essentially to zero」（**重要降权见 §7：原 JSON 把它误挂在 Glasserman 名下、并报了 0.41→1e-6 这种来源里查不到的精确数字，属张冠李戴 + 杜撰精度**）。第三根是《All Leaks Count》（arXiv 2602.17234）：**prompt 层面的约束（「请不要使用你训练截止后的知识」）系统性失败**——这是本环节最关键、对工程最有指导性的一条。

**核心命题是被支撑的，但必须去掉夸大**：LLM 引导的因子生成确实存在真实的训练截止后衰减，且只靠 prompt 约束不够——这一条由 Profit Mirage、All Leaks Count、Gao-Jiang-Yan LAP 三篇共同支撑。但同一份研究自己引的 Glasserman-Lin（arXiv 2309.17322）恰恰是一条**部分反证**：他们发现「干扰效应（distraction，匿名化标的反而更准）」占主导，而**样本外的 look-ahead bias「不是问题（not a concern）」**——这与「污染无处不在且毁灭性」的警报式框定相抵（见 §7）。因此本环节的诚实定位是：**记忆泄露是一类真实、但程度与边界都被高估/未充分外推的风险；它对「资产无关、英文语料覆盖薄的 A股中文新闻 + 24/7 加密」的可迁移性，几乎全部证据缺位（见 §8 外部效度缺口）。**

**对一个「流程即信任、人只出经济判断」的 Agent OS，本环节的产品价值不在「我们也能用 LLM 挖因子」，而在于把这类生成天然的两道杀手做成 agent 默认强制门**：(1) **严格时间隔离 + 程序化污染门**（prompt 约束已被证伪，必须是代码层的硬隔离）；(2) **选择偏误控制**（Deflated Sharpe / CSCV-PBO / 新颖性+复杂度门）——**但 §7 明确：(2) 解决的是『多重检验/回测过拟合』，不是记忆泄露；DSR 是尺度/选择修正，无法救回一个 edge 纯粹来自记忆的策略；把 CSCV/DSR 和 MemGuard 式成员推断并列成『解决同一问题』是混淆两种失效模式。**

## 2. 前沿 SOTA 与代表系统

| 系统 / 范式 | 角色 | 要点 | URL |
|---|---|---|---|
| **Alpha-GPT / AlphaAgent / QuantaAlpha / Hubble** | LLM formula-alpha miner（生成式因子挖掘的代表谱系） | 用 LLM（或 LLM+进化搜索）生成公式型 alpha 表达式并迭代。**【降权见 §7：原 JSON 把四者笼统打成「comparable LLM formula-alpha miners + 一律 weak on contamination」属过度概括——四者严谨度差异巨大。QuantaAlpha(2602.07085) 报了 IC 0.1501、4 年累计超额 160%/137% 这类本评审未独立核验的亮眼数字，恰是最该被记忆泄露质疑、却被原 JSON 既未引也未审的样本内/迁移声明。一个「weak on contamination」标签抹平了真实差异】** | https://arxiv.org/abs/2502.16789 |
| **Hubble** | 较新、且较诚实地自承局限的 formula-alpha 系统 | 在 501 只 S&P 500 标的、840 个样本内交易日上挖因子。**【降权见 §7：原 JSON「admits no walk-forward；weak on contamination」半真但略去关键语境——Hubble 确实自承「尚无完整 walk-forward OOS 协议」（字面成立），但它**确实有**一个 195 交易日的单切分 held-out OOS 窗口（2025-06 至 2026-03）。说成「完全没有 OOS 测试」夸大了其弱点。「weak on contamination」公允——Hubble 自承其数据层隔离抓不到 LLM 的时间/元知识泄露】** | https://arxiv.org/abs/2604.09601 |
| **AlphaForge** | 深度学习「动态组合」式因子挖掘 | 生成-预测网络挖掘公式因子并做动态加权组合（非 LLM 生成，属对照基准）。代表 DL 路线的因子动态组合方向。 | https://arxiv.org/abs/2406.18394 |
| **RD-Agent（Qlib / 微软）** | 生产级 factor-loop 的工程参照 | 把「研究-开发」做成可自动迭代的 factor/model loop，是目前最接近「生产级 agent 因子流水线」的开源参照系，工程化程度最高，适合作为本项目 agent 编排的对照（而非信号源）。 | https://github.com/microsoft/RD-Agent |
| **FinMem / QuantAgent / FinAgent / FinCON / TradingAgents** | LLM 交易 agent 谱系（Profit Mirage 的衰减研究对象） | 记忆增强 / 多 agent 的 LLM 交易框架。**【降权见 §7：原 JSON「FinMem(2311.13743) worst OOS degradation」属引用洗白/论点移植——「最差 OOS 衰减」是 Profit Mirage(2510.07920) 对 FinMem 的评判，不是 FinMem 自己 2311.13743 论文的主张（该文把 FinMem 作为记忆增强 agent 正面呈现）；把批评挂到 FinMem 自己的 arXiv ID 上是曲解该引用所述，且「最差」是指标依赖的（总收益成立、Sharpe 与 FinCON 并列）】** | https://arxiv.org/abs/2311.13743 |

## 3. 关键论文（每条带 URL）

- **Profit Mirage（arXiv 2510.07920）**——LLM 交易 agent 在训练截止后普遍出现 Sharpe / 总收益衰减，是本环节「记忆泄露真实存在」的最硬实证。诚实数据点：**Sharpe 衰减区间约 51.48%（QuantAgent）到 62.23%（FinCON）；总收益衰减 FinMem 最差（71.85%）。** **【medium 降权见 §7：原 JSON「9 agents；post-cutoff Sharpe down 51 to 62 percent, FinMem worst」两处不准——(1) 出现衰减的 Sharpe/收益表覆盖的是 5 个具名 LLM agent（QuantAgent、TradingAgents、FinMem、FinAgent、FinCON），「9」指 FactFin 的九个 baseline（含非 LLM 金融模型与单 agent 系统），把「对比的 baseline 数」当成「出现泄露衰减的 agent 数」；(2)「FinMem worst」只在『总收益』维度无歧义成立，在『Sharpe』维度 FinMem 与 FinCON 并列 62.23%，论文原文把 Sharpe 区间表述为「51.48%(QuantAgent) 到 62.23%(FinCON)」——就本句点名的指标(Sharpe)而言，「最差」应是 FinCON 或「FinMem/FinCON 并列」，而非「FinMem worst」】**
  https://arxiv.org/abs/2510.07920

- **A Test of Lookahead Bias in LLM Forecasts（Gao, Jiang, Yan / CUHK, arXiv 2512.23847）**——构造 LAP（look-ahead 指标），样本内「materially positive」，越过训练截止日「collapses essentially to zero」。本环节「时间隔离必须按训练截止线切」的直接证据。**【high 降权见 §7：原 JSON 把它误归到 Glasserman 名下（「Glasserman LAP」），且报了「0.41 to 1e-6 at cutoff」这种在该文摘要里查不到的精确数字——作者是 Gao、Jiang、Yan（CUHK），不是 Glasserman；Glasserman 的实际论文是另一篇 2309.17322（与 Lin 合作）。两位作者/两篇论文被熔成一条，且 0.41 起点与 1e-6 地板属二手/杜撰精度，源文只说 LAP 样本内显著为正、过截止日后基本归零】**
  https://arxiv.org/abs/2512.23847

- **Glasserman & Lin — GPT-sentiment look-ahead（arXiv 2309.17322）**——本应作为**部分反证**呈现而非支持证据。其关键结论是：**干扰效应（distraction，匿名化标的标识反而更准）占主导，而样本外 look-ahead bias「不是问题（not a concern）」**——匿名化头条甚至跑赢样本内。**【medium 降权见 §7：原 JSON 把它列为「污染无处不在且毁灭性」叙事的支持证据，实际它部分反驳了警报式框定。文案引用时必须把它定位为 nuancing 的对立案例，而非佐证】**
  https://arxiv.org/abs/2309.17322

- **All Leaks Count（arXiv 2602.17234）**——本环节对工程最有指导性的一篇：**prompt 层面的约束（要求模型「不要使用截止后知识」）系统性失败**。这是「时间隔离必须是程序化代码门、不能靠提示词」的直接依据。
  https://arxiv.org/abs/2602.17234

- **MemGuard-Alpha（arXiv 2603.26797）**——成员推断（membership inference）/ 跨模型分歧式的污染检测方向。**【降权见 §7 + §8 构念效度缺口：成员推断/预训练数据检测方法在大模型上有公认的高假阳率、弱校准；把它当作「检测已解决」会让基于不可靠 MIA 的污染门要么误杀真 alpha（假阳），要么放行被记忆的信号（假阴）。MemGuard 与 LAP 不应被当作已落地的可信门】**
  https://arxiv.org/abs/2603.26797

- **Look-Ahead-Bench（arXiv 2601.13770）**——look-ahead 偏差的基准/评测集方向。**【缺口见 §8：每个污染检测器与其基准一旦发表，就会进入下一代模型的训练语料——本身是移动靶；「干净」的过截止窗会对下一代模型变脏，这个自毁式动态没有任何被引远程解决】**
  https://arxiv.org/abs/2601.13770

- **AlphaAgent（arXiv 2502.16789）**——LLM 因子挖掘代理的代表作之一（formula-alpha 谱系入口）。
  https://arxiv.org/abs/2502.16789

- **QuantaAlpha（arXiv 2602.07085）**——LLM+进化搜索式因子挖掘，报 IC 0.1501、4 年累计超额 160%/137%。**【降权见 §7：这些是本评审未独立核验的亮眼 headline，恰是最该被记忆泄露质疑的样本内/迁移声明，原 JSON 既未引也未审；且用的是闭源商业模型(GPT-5.x)，其权重/RLHF/静默版本滚动会改变「截止线」本身——见 §8 非确定性缺口】**
  https://arxiv.org/abs/2602.07085

- **AlphaForge（arXiv 2406.18394）**——DL 动态组合式因子挖掘（非 LLM 生成，列为对照基准）。
  https://arxiv.org/abs/2406.18394

- **Bailey & López de Prado — PBO via CSCV（SSRN 2326253）/ Deflated Sharpe Ratio（SSRN 2460551）**——回测过拟合概率（CSCV-PBO）与去膨胀 Sharpe（DSR），是选择偏误控制的标准工具。**【medium 降权见 §7：真实且归属正确，但**范畴漂移**——它们针对的是选择偏误/多重检验/回测过拟合，**不是**本环节真正主题的 LLM 参数记忆泄露；它们是必要但不充分，且检测不了记忆。按本项目自有的雷区清单：DSR 是尺度/选择修正，不修正系统性低估，更无法救回一个 edge 纯属记忆的策略。把 CSCV/DSR 与 MemGuard 式成员推断并列成「解决同一问题」会模糊两种不同的失效模式】**
  https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2326253

## 4. 机构最佳实践 / 标准

- **严格时间隔离须是代码层硬门，不是 prompt（All Leaks Count 的工程含义）**：因子生成的全链路——LLM 看到的上下文、检索增强（RAG）的语料、特征构造的 as-of 截断——都必须按「数据时间戳 ≤ 决策时点」做程序化裁剪；任何「请勿使用未来知识」的提示词都视为无效护栏。这是本环节区别于「普通因子挖掘」的硬约束。

- **选择偏误控制是 SR 11-7 / DSR / PBO 谱系的标准动作（呼应簇 C）**：对 LLM 生成的每个候选因子，默认计入「实际尝试次数 N」（生成式搜索的 N 极大），用 DSR / CSCV-PBO 做去膨胀与过拟合概率，并加新颖性门（与既有因子库的相关性/表达式去重）与复杂度门（防止 LLM 拟合出过拟合的复杂表达式）。**但须显式标注：这一族只治选择偏误，不治记忆泄露（见 §7）。**

- **训练截止线（training cutoff）是隔离协议的锚，但对 API 模型是「模糊且供应商控制」的边界**：闭源商业模型的权重、RLHF、静默版本滚动会改变截止线本身。机构做法应是：优先用**已知截止日、版本可钉死、可自托管**的开源模型做因子生成的「时间敏感」部分；对必须用商业 API 的部分，记录调用时点与模型版本快照，并把「截止线不可信」当作隔离协议的已知漏洞披露（见 §8）。

- **Held-out OOS 不等于「时间隔离」——两者必须分开做（Hubble 的教训）**：单切分 held-out OOS（如 Hubble 的 195 日窗）能抓「过拟合」，但**抓不到** LLM 的时间/元知识泄露（模型在预训练里已见过该 OOS 窗的真实结果）。机构应同时跑：(a) 标准 purged/embargoed walk-forward（防数据泄露），与 (b) 「过训练截止日」的 LAP 式污染探针（防记忆泄露）——二者正交，缺一不可。

- **污染检测器本身是移动靶，须有「基准失效/再校准」机制**：LAP / MemGuard / Look-Ahead-Bench 一旦发表即进入下一代训练语料，检测有效性会随模型代际衰减；机构应把污染门视为需周期性重新标定的对象，而非一次性接入的固定阈值（见 §8 自毁动态）。

## 5. 对 QuantBT 这套架构的推荐方向（概念级）

> 概念级方向，不点 file:line、不排实施计划。

1. **把「LLM 因子生成」默认接进**程序化污染门 + 严格时间隔离**，而非 prompt 护栏**：依据 All Leaks Count——任何「请勿用未来知识」的提示词一律当作无效。隔离必须落在代码层：LLM 上下文、RAG 语料、特征 as-of 截断全部按数据时间戳硬裁剪。这是本环节相对其他因子环节（簇 E 第 23/24/25）的唯一新增护栏，应作为 agent 默认不可关的门。

2. **把「时间隔离」和「过拟合控制」做成两道正交门，并诚实标注各自只治一种病**：(a) purged/embargoed walk-forward（呼应簇 C 第 16）治数据泄露；(b) DSR / CSCV-PBO + 新颖性/复杂度门（呼应簇 C 第 14/15）治选择偏误。**关键诚实声明：(b) 解决不了记忆泄露，DSR 救不回 edge 纯属记忆的策略——agent 文案不得把「过了 DSR/PBO」当作「无记忆泄露」的证据（见 §7）。** 记忆泄露需要单独的「过训练截止日」探针。

3. **对「记忆泄露」做诚实的『真实但程度/边界未定』分级，而非警报式一刀切**：把 Profit Mirage / All Leaks / LAP 列为「**真实存在的过截止衰减**」证据；同时**强制把 Glasserman-Lin 的反证（OOS look-ahead『不是问题』、干扰效应占主导）并列呈现**，让用户看到这是一个有对立证据的风险，而非「污染无处不在且毁灭性」。避免把相对衰减（51%–62%）当成绝对结论——衰减后是否仍 >0、扣成本后是否可交易，决定了结论完全不同（见 §8 base-rate 缺口）。

4. **污染门若上线，必须配「假阳/假阴」披露与人审兜底，不得当作已解决**：成员推断/MemGuard 式检测在大模型上假阳率高、校准弱——一个基于不可靠 MIA 的硬门会误杀真 alpha 或放行被记忆信号。建议把污染门定位为「告警 + 置信标签 + human-in-the-loop 复核」，而非自动通过/否决的黑箱判官。

5. **优先自托管 + 钉死模型版本，把「训练截止线」当作可信度变量披露**：对因子生成的时间敏感部分，优先用已知截止日、可自托管的开源模型；用商业 API 时记录调用时点与版本快照，并在因子卡上把「截止线模糊/供应商控制」当作已知局限标注——这同时呼应 §8 的非确定性/可复现性缺口。

6. **把「污染门的算力/成本」当作可行性变量先评估，再决定门的形态**：在进化搜索式因子挖掘（QuantaAlpha 风格）里对每个候选因子跑成员推断 + 跨模型分歧，可能在因子挖掘规模上算力上不可行。建议默认「轻量探针先筛、重检测仅对进入候选池的少数因子做」，而非对全搜索空间无差别开重门（缺口见 §8）。

7. **A股/加密外部效度先验声明（缺口补全，列为硬约束）**：本环节几乎所有证据是美股 / 英文新闻情绪驱动。**look-ahead/记忆泄露的量级能否外推到中文 A股新闻、A股 regime、英文语料覆盖薄的 24/7 加密，是完全未测的**——agent 默认对「LLM 生成因子在 A股/加密上的泄露程度」标注「外部效度未知、不可照搬美股数字」，并优先用本土数据做独立的过截止探针，而非引用 Profit Mirage 的衰减幅度对中文标的下结论。

8. **把「幸存者/发表偏误」上提到 SOTA 列表本身（缺口补全）**：本环节只引到已发表、正结果的 LLM-alpha 框架（Alpha-GPT/AlphaAgent/QuantaAlpha/Hubble/AlphaForge），失败/零结果的尝试不可见，使该领域的表观能力被高估——这是研究自己警告的选择偏误的元层翻版。agent 引入任一外部 LLM-alpha 范式时，应默认对其 headline 数字（如 QuantaAlpha 的 IC 0.1501/160%）打「未独立复现 + file-drawer」折扣。

## 6. 架构级参考（少量伪代码 / schema 草图，非代码接线）

> 示意，非接线到现有代码。

**两道正交门：时间隔离（治泄露）⊥ 过拟合控制（治选择偏误），各自只标自己治的病：**

```
# 门 A — 程序化时间隔离（代码层，prompt 约束视为无效）
ctx       = clip_by_ts(llm_context, asof=decision_ts)   # LLM 上下文按时间戳硬裁剪
rag_docs  = clip_by_ts(retrieve(query), asof=decision_ts)
features  = build(asof=decision_ts)                     # as-of 截断, 禁未来信息
# ⚠ 任何 "请勿使用截止后知识" 的提示词都不计入护栏 (依据 All Leaks Count 2602.17234)

# 门 B — 选择偏误控制 (呼应簇C-14/15/16); 注: 只治过拟合, 不治记忆泄露
dsr = deflated_sharpe(cand, n_trials=N_search)   # N=生成式搜索的真实尝试数(极大)
pbo = cscv_pbo(cand)
novelty = 1 - max_corr(cand, factor_library)     # 新颖性门: 与既有因子去相关/表达式去重
complexity_ok = expr_complexity(cand) <= K       # 复杂度门: 防LLM拟合过拟合表达式
# ⚠ 诚实标注: 过了 dsr/pbo ≠ 无记忆泄露; DSR 救不回 edge 纯属记忆的策略
```

**记忆泄露探针：过训练截止日的 LAP 式坍塌检测（与 held-out OOS 正交）：**

```
# 依据 Gao-Jiang-Yan LAP (2512.23847) + Profit Mirage (2510.07920)
in_sample_perf  = eval(cand, window="< model_training_cutoff")
post_cutoff_perf= eval(cand, window=">= model_training_cutoff")  # 真·过截止
if in_sample_perf >> post_cutoff_perf:           # 样本内强、过截止坍塌
    flag("suspected_memory_leak")                # 告警, 非自动否决 (见门定位)
# ⚠ cutoff 对 API 模型是模糊/供应商控制的边界 → 记录模型版本快照 (见 §8)
# ⚠ 同时必须呈现反证: Glasserman-Lin(2309.17322) OOS look-ahead "not a concern"
```

**污染门的诚实卡片 + 门定位（告警/标签/人审，非黑箱判官）：**

```yaml
contamination_gate:
  posture: warn_label_review          # 非 auto-pass/auto-reject
  detectors:
    lap_collapse: { source: "2512.23847", note: "过截止坍塌探针" }
    membership_inference:
      source: "MemGuard-Alpha 2603.26797"
      caveat: "大模型上高假阳/弱校准 → 误杀真alpha 或 放行被记忆信号"   # §7构念效度
  scope_guard:
    selection_bias_tools: [deflated_sharpe, cscv_pbo]
    explicit_note: "DSR/PBO 只治选择偏误, 不检测记忆泄露 (两种失效模式)"   # §7范畴漂移
  detector_is_moving_target: true     # 检测器+基准发表后进入下一代训练语料 → 周期再标定
  cost_feasibility:                   # 缺口: 进化搜索下逐因子重检测可能不可行
    policy: "轻量探针先筛 + 重检测仅对候选池少数因子"

model_provenance:                     # 训练截止线 = 模糊/供应商控制的可信度变量
  prefer_self_hosted: true            # 时间敏感部分优先开源+可钉版本
  api_model: { record_call_ts: true, version_snapshot: true, cutoff_trust: low }

external_validity:                    # 缺口: 证据几乎全是美股/英文
  evidence_market: us_equity_english
  a_share_crypto: { leakage_magnitude: unknown, do_not_extrapolate_us_numbers: true }

survivorship_discount:                # SOTA列表本身的发表/file-drawer偏误
  headline_haircut: required          # QuantaAlpha IC0.1501/160% 等默认折扣
  applies_to: [alpha_gpt, alphaagent, quantaalpha, hubble, alphaforge]
```

## 7. 降权 / 争议 / 陷阱（对抗核查结论）

> 以下限定词（事实错误/张冠李戴/杜撰精度/引用洗白/论点移植/选择性引用/范畴漂移/构念效度/外推过度/二手 等）**原样保留**；凡涉「FinMem worst / 9 agents / 0.41→1e-6 / 污染无处不在且毁灭性 / CSCV-DSR 解决记忆泄露」等强确定性或与原文相抵的措辞均已按对抗核查降级。任何对用户的承诺或文案，必须采用降级后的表述。

- **【high · 张冠李戴 + 杜撰精度】「Glasserman… 'LAP 0.41 to 1e-6 at cutoff'」（key_papers 将 Glasserman LAP / GPT-sentiment / Look-Ahead-Bench 归并于 2512.23847 / 2309.17322 / 2601.13770）**——**misattribution + fabricated precision**。arXiv 2512.23847《A Test of Lookahead Bias in LLM Forecasts》作者是 **Gao、Jiang、Yan（CUHK），不是 Glasserman**；Glasserman 的实际论文是 2309.17322（与 Lin 合作），是独立的另一篇工作。该 finding 把两位作者/两篇论文熔成了一条。更糟的是 headline 数字「0.41 to 1e-6」**未出现在 2512.23847 的摘要中**——摘要只说 LAP 样本内「materially positive」、过截止后「collapses essentially to zero」；具体的 0.41 起点与 1e-6 地板是**二手/杜撰精度，源里无法核验**。
  https://arxiv.org/abs/2512.23847

- **【medium · 计数错误 + 「最差」不精确】Profit Mirage：「9 agents；post-cutoff Sharpe down 51 to 62 percent, FinMem worst.」**——**两处错误**。(1) Agent 计数：Sharpe/收益衰减表覆盖的是 **5 个具名 LLM 交易 agent**（QuantAgent、TradingAgents、FinMem、FinAgent、FinCON）；「9」指 FactFin 的**九个 baseline**（含非 LLM 金融模型与单 agent 系统），把「对比的 baseline 数」与「出现泄露衰减的 agent 数」混为一谈。(2)「FinMem worst」只在**总收益（total return）衰减 71.85%** 上无歧义成立；就 **Sharpe** 衰减而言 FinMem 与 FinCON **并列 62.23%**，论文原文把 Sharpe 区间表述为「51.48%(QuantAgent) 到 62.23%(FinCON)」——就本句点名的指标(Sharpe)，「最差」应是 FinCON 或「FinMem/FinCON 并列」，而非「FinMem worst」。
  https://arxiv.org/abs/2510.07920

- **【medium · 引用洗白 / 论点移植】sota_systems：「FinMem (2311.13743) worst OOS degradation.」**——**citation-laundering / 论点移植**。「最差 OOS 衰减」是 Profit Mirage（2510.07920）**对** FinMem 的发现，**不是** FinMem 自己 2311.13743 论文的主张（该文把 FinMem 作为记忆增强 agent 正面呈现）。把这条批评挂到 FinMem 自己的 arXiv ID 上曲解了该引用所述；且如上，「最差」是指标依赖的（总收益成立，Sharpe 与 FinCON 并列）。
  https://arxiv.org/abs/2311.13743

- **【low · 半真 / 略去关键语境】sota_systems：「Hubble admits no walk-forward；weak on contamination.」**——**half-true, omits material context**。Hubble（2604.09601）确实自承「does not yet include a full walk-forward out-of-sample protocol」——故「admits no walk-forward」字面成立。**但** finding 略去了 Hubble **确实跑了一个单切分 held-out OOS 窗口**（195 交易日，2025-06 至 2026-03，覆盖 501 只 S&P 500 标的、840 个样本内交易日）。把它说成「完全没有 OOS 测试」夸大了其弱点。「weak on contamination」是公允的——Hubble 自承其数据层隔离抓不到 LLM 的时间/元知识泄露。
  https://arxiv.org/abs/2604.09601

- **【medium · 警报式框定 / 埋掉反证】design_directions 与 key_papers 把 look-ahead/记忆污染框定为「普遍、已验证的 OOS 威胁」（警报式『记忆污染』腔调）**——**cherry-picks 警报方向、埋掉了 finding 自己引用的最强反证**。Glasserman-Lin（2309.17322）实际发现**干扰效应（distraction，匿名化标识）占主导，且样本外 look-ahead bias「不是问题（not a concern）」**——匿名化头条甚至跑赢样本内。这是对「污染无处不在且毁灭性」论点的**部分反驳**，而 finding 却把该论文列为支持证据而非 nuancing 的反例。
  https://arxiv.org/abs/2309.17322

- **【medium · 范畴漂移 + DSR 已知告诫】key_papers：「PBO via CSCV and Deflated Sharpe」被捆绑为 LLM 污染/泄露的解药**——**category drift + 已知 DSR 告诫**。PBO/CSCV（SSRN 2326253）与 DSR（SSRN 2460551）真实且归属正确，但它们针对**选择偏误 / 多重检验 / 回测过拟合**——**不是**本环节真正主题的 LLM 参数记忆泄露。它们必要但不充分，且检测不了记忆。按本项目自有的雷区清单：DSR 是**尺度/选择修正**，不修正系统性低估，更**无法救回一个 edge 纯属记忆的策略**。把 CSCV/DSR 与 MemGuard 式成员推断并列成「解决同一问题」会模糊两种不同的失效模式。
  https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2460551

- **【low · 过度概括】sota_systems 把 Alpha-GPT、AlphaAgent、QuantaAlpha、Hubble 笼统打成 comparable「LLM formula-alpha miners」并一律贴「weak on contamination」**——**over-generalization**。四者严谨度差异巨大：QuantaAlpha（2602.07085）报了强但本评审未独立核验的 headline（IC 0.1501、4 年累计超额 160%/137%），finding 既未引也未审——这恰是最易受本环节所讨论泄露影响的样本内/迁移声明。单一「weak on contamination」标签抹平了真实差异，并跳过了这组里最该核验的性能声明。
  https://arxiv.org/abs/2602.07085

**通用陷阱清单（工程红线）：**

- **prompt 约束失效是头号工程坑**：要求 LLM「不要使用训练截止后的知识」系统性失败（All Leaks Count 2602.17234）；时间隔离必须是代码层硬门（上下文/RAG/特征 as-of 全裁剪），任何提示词护栏都视为无效。
- **「过了 DSR/PBO」≠「无记忆泄露」**：CSCV/DSR 治选择偏误、不治记忆；DSR 是尺度/选择修正，救不回 edge 纯属记忆的策略。记忆泄露需单独的「过训练截止日」探针（LAP 式坍塌检测），与选择偏误门正交。
- **held-out OOS 抓不到记忆泄露**：单切分 held-out OOS（如 Hubble 的 195 日窗）能抓过拟合，但抓不到「模型预训练已见过该 OOS 窗真实结果」的元知识泄露——必须另跑过截止探针。
- **污染检测器本身是移动靶（自毁动态）**：LAP / MemGuard / Look-Ahead-Bench 一旦发表即进入下一代训练语料，「干净」的过截止窗对下一代模型会变脏——没有任何被引远程解决这个自毁式动态，使「严格时间隔离」作为持久原则被削弱。
- **MIA/成员推断的构念效度**：成员推断/预训练数据检测在大模型上**高假阳率、弱校准**；基于不可靠 MIA 的污染门要么误杀真 alpha（假阳）、要么放行被记忆信号（假阴）——finding 把 MemGuard/LAP 当「检测已解决」呈现，未标这一点。
- **训练截止线对 API 模型是模糊/供应商控制的**：闭源商业模型（如 QuantaAlpha 用的 GPT-5.x）的权重/RLHF/静默版本滚动会改变截止线本身——任何把「截止线」硬编码成清晰可知边界的方法学都被削弱。优先自托管 + 钉版本，并记录调用时点快照。
- **base-rate / 经济显著性缺位**：「过截止 Sharpe 衰减 51–62%」听着灾难性，但 finding 从未报过截止后的绝对 Sharpe 水平、是否在现实交易成本/容量/A股+加密摩擦后仍 >0。样本内 Sharpe 3 打 60% 折与 0.6 打 60% 折是完全不同的结论；相对衰减本身不是决策相关量。
- **幸存者/发表偏误（元层）**：只引到已发表、正结果的 LLM-alpha 框架，失败/零结果不可见 → 领域表观能力被高估，是 finding 自己警告的选择偏误的元层翻版；外部 headline 数字（QuantaAlpha IC0.1501/160%）须默认打「未独立复现 + file-drawer」折扣。
- **外部效度：A股/加密未测**——几乎全部证据是美股/英文新闻情绪驱动，泄露量级能否外推到中文 A股新闻、A股 regime、英文语料覆盖薄的 24/7 加密**完全未测、且可能很不同**；不得用美股数字对中文标的下结论。
- **污染门的算力可行性**：在进化搜索式因子挖掘里对每个候选因子跑成员推断 + 跨模型分歧可能算力上不可行；design_directions 断言门「必要」却从未谈在因子挖掘规模上是否可行。

## 8. 开放问题

- **污染检测器的自毁动态没有解**：每个被引的污染检测器（LAP、Shapley-DCLR、MemGuard-Alpha）本身都是移动靶——论文与基准一旦发表就进入未来训练语料，于是「干净」的过截止窗对下一代模型会变脏。所有被引解药都没处理这个自毁式动态，它从根上削弱了「严格时间隔离」作为持久原则的有效性。
- **SOTA 列表本身的幸存者/发表偏误**：只引到已发表、正结果的 LLM-alpha 框架（Alpha-GPT/AlphaAgent/QuantaAlpha/Hubble/AlphaForge），失败/零结果的 LLM 因子挖掘尝试不可见，使该领域表观能力被高估——这是 finding 自己警告的选择偏误的元层翻版（已在 §5 第 8 条补为推荐）。
- **缺 base-rate / 经济显著性核查**：过截止 Sharpe「down 51–62%」从未给出过截止后的**绝对** Sharpe 水平、是否在现实交易成本/容量/A股-加密摩擦后仍 >0。样本内 Sharpe 3 打 60% 折 vs 0.6 打 60% 折是完全不同的结论；相对衰减不是决策相关量。
- **LLM 非确定性 / 可复现性混淆**：Profit Mirage 与同类研究用闭源商业模型（QuantaAlpha 用 GPT-5.x），其权重/RLHF/静默版本滚动会改变「截止线」本身。finding 把「训练截止」当作干净可知的边界，但对 API 模型它是模糊且供应商控制的，削弱了任何硬编码截止线时间切分的方法学。
- **LAP/成员推断检测器的构念效度未被标注**：成员推断/预训练数据检测在大模型上有公认的高假阳率、弱校准；finding 引 MemGuard-Alpha 与 LAP 时把检测当「已解决」呈现，从未提一个基于不可靠 MIA 的污染门会误杀真 alpha（假阳）或放行被记忆信号（假阴）。
- **对 QuantBT 实际栈（A股 Tushare + 加密）的相关性缺位**：几乎全部证据是美股/英文新闻情绪驱动；look-ahead-bias 量级能否迁移到中文 A股新闻、A股 regime、英文训练覆盖薄的 24/7 加密**完全未测、可能很不同**——这是 finding 未承认的外部效度缺口（已在 §5 第 7 条补为硬约束声明）。
- **「程序化污染门」的成本/延迟核算缺位**：在进化搜索式因子挖掘（QuantaAlpha 风格）里对每个候选因子跑成员推断 + 跨模型分歧（MemGuard-Alpha）可能算力上不可行；design_directions 断言门「必要」却从未处理它在因子挖掘规模上是否可行（已在 §5 第 6 条补为「轻量先筛 + 重检测仅对候选池少数」）。

## 9. 参考文献（URL）

- Profit Mirage（arXiv 2510.07920；**衰减表是 5 个具名 LLM agent，非「9」；Sharpe 区间 51.48%(QuantAgent)–62.23%(FinCON)，FinMem 仅在『总收益』71.85% 单独最差**）：https://arxiv.org/abs/2510.07920
- A Test of Lookahead Bias in LLM Forecasts（Gao, Jiang, Yan / CUHK, arXiv 2512.23847；**作者非 Glasserman；「0.41→1e-6」源里查不到、属二手/杜撰精度；源仅称样本内显著为正、过截止基本归零**）：https://arxiv.org/abs/2512.23847
- Glasserman & Lin — GPT-sentiment look-ahead（arXiv 2309.17322；**部分反证：干扰效应占主导、OOS look-ahead『not a concern』**）：https://arxiv.org/abs/2309.17322
- All Leaks Count（arXiv 2602.17234；**prompt 层约束系统性失败 → 隔离须是代码门**）：https://arxiv.org/abs/2602.17234
- MemGuard-Alpha（arXiv 2603.26797；**成员推断检测，但大模型上高假阳/弱校准，非已落地可信门**）：https://arxiv.org/abs/2603.26797
- Look-Ahead-Bench（arXiv 2601.13770；**基准本身是移动靶，发表后进入训练语料**）：https://arxiv.org/abs/2601.13770
- AlphaAgent（arXiv 2502.16789；LLM formula-alpha 谱系）：https://arxiv.org/abs/2502.16789
- QuantaAlpha（arXiv 2602.07085；**IC 0.1501/160%/137% 为本评审未独立核验 headline，须打 file-drawer 折扣；用闭源 GPT-5.x，截止线模糊**）：https://arxiv.org/abs/2602.07085
- Hubble（arXiv 2604.09601；**自承无完整 walk-forward 字面成立，但**确有**195 日单切分 held-out OOS 窗，说成「完全无 OOS」夸大**）：https://arxiv.org/abs/2604.09601
- AlphaForge（arXiv 2406.18394；DL 动态组合式因子挖掘，对照基准）：https://arxiv.org/abs/2406.18394
- FinMem（arXiv 2311.13743；**该文正面呈现 FinMem，「最差 OOS 衰减」是 Profit Mirage 对它的评判、非本文主张——属论点移植**）：https://arxiv.org/abs/2311.13743
- RD-Agent（微软 / Qlib；生产级 factor-loop 工程参照）：https://github.com/microsoft/RD-Agent
- Bailey & López de Prado — PBO via CSCV（SSRN 2326253；**治选择偏误/回测过拟合，非记忆泄露**）：https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2326253
- Bailey & López de Prado — The Deflated Sharpe Ratio（SSRN 2460551；**尺度/选择修正，救不回 edge 纯属记忆的策略**）：https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2460551
- Alpha-GPT（LLM 量化研究交互范式，formula-alpha 谱系入口，arXiv 2308.00016）：https://arxiv.org/abs/2308.00016
