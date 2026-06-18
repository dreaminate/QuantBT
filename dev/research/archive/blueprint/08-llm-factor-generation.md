# 08 · LLM 方向引导因子生成 — 前沿研究与对我们 loop 的接线

> **来源**：一次研究 workflow（13 agent / 93 万 token，6 主线并行 + 逐流对抗式核查，论文与源码逐条核实）。最终综合 agent 因 API 过载失败，本文由 Claude 从 6 条已核查主线综合。
>
> **服务对象**：[06-divergence-deepdive.md](06-divergence-deepdive.md) 与本系列设计的「研究节点引导式探索 loop」——用户给方向+中心思想 → LLM 按字段语义+中心思想剪枝生成因子 → 训练/检验 → 反思/精炼 → 循环；每轮试错计入 honest-N，留出集加密不可见，最终候选过独立验证+假设卡冻结。
>
> **一句话结论**：这件事**已是 2023–2026 一个拥挤的子领域，我们的 loop 设计被同行评审工作背书**；但「LLM 生成的因子真能 OOS 赚钱」**证据很弱**——漂亮结果多被 LLM 记忆/look-ahead 污染，去偏后常塌到接近统计零。**所有现有系统的共同盲区（不做 DSR/PBO/honest-N）正是我们的差异化。**

---

## 1. 代表系统（按与我们设计的对齐度 + 可信度）

| 系统 | 成熟度 | 方向怎么给 | 反过拟合 | 与我们对齐 |
|---|---|---|---|---|
| **AlphaAgent** `arXiv 2502.16789` · KDD 2025 · [开源](https://github.com/RndmVariableQ/AlphaAgent) | ⭐ 同行评审+开源 | 人给 seed 方向 h0 → Idea/Factor/Eval 三 agent **自演化**；假设四要素(观察/知识/论证/规范) | AST 子树相似度去重(对 Alpha101) + 复杂度罚(符号长度/自由参数) + 假设-因子语义一致性 + 20 trial×5 round + t 检验 | **最对齐**——几乎就是我们的 loop |
| **RD-Agent(Q)** `arXiv 2505.15155` · NeurIPS 2025 · [开源](https://github.com/microsoft/RD-Agent) | ⭐⭐ 最可复现/工业 | 结构化假设(hypothesis+reason+预期) + Co-STEER 代码 agent + bandit 调度选方向 | IC≥0.99 去重；2008-14训/15-16验/17-20测时间切；"少 70% 因子" | 工业蓝本（Research/Development/Analysis 三段闭环） |
| **Navigating the Alpha Jungle (LLM+MCTS)** `arXiv 2505.11122` | 预印本 | LLM 先写"alpha 投资逻辑画像"再转公式；MCTS 用回测反馈引导 | **语义剪枝：仅搜 1000-3000 候选 vs GP/RL 60 万** + Overfitting-Risk 维度 + Frequent Subtree Avoidance + 严格 OOS | **印证"非暴力遍历"** |
| **From Hypotheses to Factors**（加密） `arXiv 2604.26747` | 预印本 | 可证伪假设 + 经济理由 + DSL 配方（自然语言+约束模板两手） | **纪律最干净**：严格三段时间切(选因子只用训练期)、**评估器 session 内冻结**、全 25 因子 append-only 审计轨 | loop 纪律最佳单篇蓝本 |
| **Alpha-GPT 1.0 / 2.0**（IDEA） `2308.00016` / `2402.09746` · EMNLP 2025 demo | demo/预印本·闭源 | **人给自然语言交易想法**（最纯人在环） | 弱/几乎无（不计 trial、无正交化、无 OOS 协议披露） | 方向输入的早期范式；人在环本身会泄露留出集 |
| **QuantaAlpha** `arXiv 2602.07085` | 预印本 | 经济假设隐式注入 | 复杂度硬约束 + AST 去重 + 语义一致性；但 **IC 0.15 偏高**、无多重检验、单切分 | ⚠️ 高 IC 需警惕记忆/前视 |
| **Chain-of-Alpha** `arXiv 2508.06312` | 预印本 | LLM 自主(弱经济先验) | **固定试验预算（≤1000 候选取 top100）**——少见的试验数对齐；但无 DSR/PBO | honest-N 的近似先例 |
| **CogAlpha** `arXiv 2511.18850` | 预印本 | 分层 agent 各编码一类经济机制 | 时间切 + Quality Checker 查泄露 + 五指标适应度门；但无去重/正交化 | factor-zoo 风险高 |
| **FunSearch**（DeepMind, Nature）/ **AlphaEvolve**（白皮书） | Nature / 工业白皮书 | 人给骨架程序 + evaluator | 进化**"产生因子的规则"而非答案** + island model 多样性；数学域泛化极好 | **loop 元范式**（⚠️ 金融域"可证明正确"消失，evaluator=回测本身是过拟合源） |
| GP/RL 基线：**AlphaGen**(KDD'23, [开源](https://github.com/RL-MLDM/alphagen))、**AutoAlpha**(`2002.08245`)、**AlphaForge**(AAAI'25, `2406.18394`)、**QFR**(`2409.05144`) | 同行评审/预印本 | 不给方向、纯 IC/reward | 普遍无 DSR/PBO/多重检验；AlphaGen 易过拟合训练集 | LLM 反复对标对象 |

> **关键参照**：warm-start GP 实测——纯随机 GP 生成 1 万因子**仅 <3% 有效(IC>0.03)**，证明暴力遍历在因子空间几乎注定失败、必须语义/结构剪枝。这从反面支撑"非暴力遍历"。

---

## 2. 🔴 最该重视的"泼冷水"证据（也是全研究里最可信的部分）

负面结果在严格 OOS 下没有过拟合动机，且多经同行评审或严谨设计，**可信度高于任何正面 alpha 声明**：

- **Profit Mirage** `arXiv 2510.07920`：FinMem/FinAgent/QuantAgent/FinCON/TradingAgents 的回测一旦**跨过 LLM 知识截止日，Sharpe 暴跌 51-62%、总收益跌 50-72%**。记忆审计：模型在历史 QA 命中 85-93%、反事实扰动后 82% 预测不变——**它在背历史，不是预测**。
- **Look-Ahead-Bench**（Benhenda）`arXiv 2601.13770` + **MemGuard-Alpha** `arXiv 2603.26797`：标准 LLM(Llama/DeepSeek) 在训练窗内刷 44%+，移到截止后掉 ~22pp；**越大模型越靠记忆**（scaling 悖论）；做完偏差缓解后 **LLM alpha 消失、无 LLM 超越 EMH**。164 篇普查：look-ahead/survivorship/narrative/objective/cost 五类偏差无一篇全部规避。
- **FINSABER**（KDD 2026）：20 年 / 100+ 标的 OOS，FinMem Sharpe **2.679 → -0.228**，**所有 alpha p>0.34 不显著**，ARIMA/buy-and-hold 全面胜出。原报告亮眼数字多来自幸存者偏差(只测 TSLA/AMZN)+look-ahead。
- **StockBench** `arXiv 2510.02209`：contamination-free 设计（OOS 落在知识截止后），多数 LLM 打不过 buy-and-hold。
- **共同盲区**：**没有任何一个 LLM-alpha 系统做 DSR / PBO / CSCV / SPA 多重检验校正**——它们报的是几百上千候选里"挑出来的赢家"=选择性抬高的 max 统计量（Bailey-López de Prado 2014 DSR、Harvey-Liu-Zhu 2016 t>3 正是为此而生，却被全员忽略）。
- **业界现实**：WorldQuant BRAIN 核心仍是**人写因子**，"LLM 生成 BRAIN alpha"停在社区项目层、无审计业绩；Numerai 反而**故意去语义/加密特征**来防故事性过拟合；Two Sigma 2026 outlook 把 LLM 主要用于研究提效，对"GenAI 直接产 alpha"持怀疑（公开训练数据→难有市场未知的独家洞见）。

---

## 3. SOTA 架构（恰好验证我们的 loop）+ 共同盲区 = 我们的差异化

文献综合出的最佳实践架构 ≈ **我们已经设计的那条 loop**：

1. **方向输入 = 结构化假设卡**（AlphaAgent 四要素 + crypto 论文的"可证伪假设+经济理由+DSL 配方"），而非自由文本、更非只给 IC reward。
2. **生成 = LLM 经济语义驱动**（先写投资逻辑画像→公式），限定 DSL/算子集（显式禁前视特征），复杂度硬上限（符号长度/自由参数）。
3. **剪枝 = 非暴力遍历**：AST 子树相似度去重(对已有 alpha zoo) + Frequent Subtree Avoidance + 多样性/island + **best-shot 反馈**（把按分排序的历史最优候选+分数回喂 LLM）。
4. **loop = 进化"产生规则"而非答案**（FunSearch）；终止靠评估预算+分数停滞+多样性枯竭，并同步追踪 IS vs OOS 曲线，OOS 不再提升即停。
5. **生成器/评估器物理隔离**，评估规则 session 内冻结（crypto 论文）。

**而每个现有系统的共同缺口，正是我们的治理层** —— honest-N → DSR/PBO + 加密留出集 + 独立验证 + 假设卡冻结。**这不是冗余，是真差异化**：现有工作只做 AST 结构去重（结构不重复），不做经济正交化（信息不重复），更不做多重检验校正。

---

## 4. 两条**必加**设计（这轮逼出来的，已写进决策记忆）

1. **留出集不仅加密，还必须晚于所用 LLM 的知识截止日** + 加一个 **look-ahead / 记忆审计体检**（熟悉 vs 陌生时段衰减、反事实扰动测试、可选成员推断 LAP/MemGuard 式信号级污染过滤）。否则 LLM "记得"历史，OOS 也被污染——这是整条文献最致命、却被系统性忽视的问题。
2. **honest-N 必须计入 loop 内 LLM 的自我重试 / 被剪枝候选**（防它"偷偷多试"而不上报）+ 对已有因子族做**经济正交化取增量 alpha**（不只是 AST 结构去重）+ 跑 **null/置换回测**校准 deflation 惩罚强度。

---

## 5. 接线到我们的引导式探索 loop

| 我们的 loop 环节 | 借鉴谁 | 怎么接 |
|---|---|---|
| 方向+中心思想输入 | AlphaAgent 四要素 / crypto 三件套 | 落成结构化**假设卡**：{方向, 中心思想/经济机制, 可证伪命题, 预期符号, 适用 regime/universe, 候选配方 DSL}，冻结时与独立验证结果一起钉死 |
| 生成候选（语义引导·非暴力） | Alpha Jungle 画像→公式 / FieldCatalog 字段语义 | LLM 按字段语义+中心思想剪枝；限定 DSL+复杂度上限 |
| 去重/多样性 | AlphaAgent AST 相似度 / 子树避让 | 生成端就惩罚与已有因子/高频子结构雷同 + **经济正交化取残差增量** |
| loop 反馈 | FunSearch 进化规则 / best-shot | 把历史最优候选+DSR/PBO/留出业绩回喂；进化"产生因子的逻辑"而非公式串 |
| honest-N | Chain-of-Alpha 固定试验预算 / AlphaAgent 计 trial | **每轮（含 LLM 自我重试/剪枝候选）计入 n_trials_total → 喂 DSR/PBO**；这是现有系统的集体盲区=我们的差异化 |
| 留出集 | StockBench contamination-free | 加密 **+ 晚于 LLM 知识截止** + look-ahead/记忆审计体检 |
| 生成器/评估器隔离 | crypto 论文 session 冻结 | LLM 探索进程绝不触碰评估器/成本/时间切/留出集 |
| 独立验证（loop 外） | SR 11-7 有效挑战 | 确定性 verifier（非 extractor 自评）跑 CPCV/DSR/PBO + null 对照 |

---

## 6. 冷静结论（证据强度）

- **方法学成熟、我们的 loop 有同行评审背书**（AlphaAgent ≈ 我们的设计）——路对。
- 但 **"LLM 生成的因子真能 OOS 赚钱"证据很弱**：正面结果多被记忆污染 + 无多重检验；最可信的（负面）结果显示去偏后 alpha 近零。
- **LLM 相对 GP/RL 的真优势不是更高 alpha**，而是：① 语义剪枝→样本效率（千 vs 几十万候选）② 可解释 ③ 可注入人的方向/中心思想。
- **最大陷阱 = narrative overfitting**：LLM 会给任何随机因子编一个像样的经济故事；"语义一致性高分 ≠ 真经济先验"，绝不能替代 OOS 检验。

**定位（合"可上线成品"北极星）**：把 LLM 当**样本高效、可解释、人导向的候选生成器**，喂进我们严格的验证漏斗——**漏斗（治理）才是可信的来源，LLM 是前端，不是 alpha 神谕**。

---

## 7. 关键引用

- AlphaAgent — KDD 2025 · [arXiv 2502.16789](https://arxiv.org/abs/2502.16789) · [code](https://github.com/RndmVariableQ/AlphaAgent)
- RD-Agent(Q) — NeurIPS 2025 · [arXiv 2505.15155](https://arxiv.org/abs/2505.15155) · [code](https://github.com/microsoft/RD-Agent)
- Navigating the Alpha Jungle (LLM+MCTS) — [arXiv 2505.11122](https://arxiv.org/abs/2505.11122)
- From Hypotheses to Factors (crypto) — [arXiv 2604.26747](https://arxiv.org/abs/2604.26747)
- Alpha-GPT 1.0 — [arXiv 2308.00016](https://arxiv.org/abs/2308.00016)（EMNLP 2025 demo）· 2.0 — [arXiv 2402.09746](https://arxiv.org/abs/2402.09746)
- QuantaAlpha — [arXiv 2602.07085](https://arxiv.org/abs/2602.07085) · Chain-of-Alpha — [arXiv 2508.06312](https://arxiv.org/abs/2508.06312) · CogAlpha — [arXiv 2511.18850](https://arxiv.org/abs/2511.18850)
- AlphaGen — KDD 2023 · [code](https://github.com/RL-MLDM/alphagen) · AutoAlpha — [arXiv 2002.08245](https://arxiv.org/abs/2002.08245) · AlphaForge — AAAI 2025 · [arXiv 2406.18394](https://arxiv.org/abs/2406.18394) · QFR — [arXiv 2409.05144](https://arxiv.org/abs/2409.05144)
- FunSearch — Nature 2023 (DeepMind) · AlphaEvolve — DeepMind 2025 白皮书 · EvoPrompt — ICLR · [code](https://github.com/beeevita/EvoPrompt)
- **泼冷水**：Profit Mirage [arXiv 2510.07920](https://arxiv.org/abs/2510.07920) · Look-Ahead-Bench [arXiv 2601.13770](https://arxiv.org/abs/2601.13770) · MemGuard-Alpha [arXiv 2603.26797](https://arxiv.org/abs/2603.26797) · FINSABER (KDD 2026) · StockBench [arXiv 2510.02209](https://arxiv.org/abs/2510.02209)
- **方法学锚点**：Bailey & López de Prado, Deflated Sharpe Ratio (2014) · Harvey, Liu, Zhu, "...and the Cross-Section of Expected Returns" (RFS 2016)

> ⚠️ 多为 arXiv 预印本（部分 2026 新作未及第三方复现）；正面 alpha 数字在独立复现 + 去偏 OOS 前应视为**上界**。引用时保留"是否同行评审/是否开源/是否处理过拟合"的限定。
