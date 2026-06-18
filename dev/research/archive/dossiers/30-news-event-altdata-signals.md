# 30 · 新闻/事件/另类数据信号（情绪/PEAD/链上/A股基本面；中低频）

> 机构级 Agent OS 成品环节深挖 · 全程 Opus 4.8 · 对抗式核查已降权 · 重心=前沿研究+概念级推荐 · 不含 file:line 代码接线
> 簇 E

## 1. 一句话定位

本环节回答一个对「资产无关中低频 + 流程即信任」系统极重要、却最容易被花哨数字带偏的问题：**新闻/事件/另类数据这类 alpha，在「毛收益、样本内」普遍亮眼，但在「净收益、样本外、拥挤后」普遍快速衰减——而且衰减正被 LLM/AI 的普及显著加速**。最硬的实证锚点是 Lopez-Lira & Tang《Can ChatGPT Forecast Stock Price Movements?》：GPT-4 对新闻头条的「好/坏」判断能预测后续漂移，但策略年化 Sharpe 从 2021Q4 的 6.54 一路衰减到 2022 的 3.68、2023 的 2.33、2024 年 1–5 月的 1.22，作者明确归因「LLM 采用率上升→定价效率提高」（**重要降权见 §7：该文是 JFE forthcoming/在审，原 JSON 三处误称 Journal of Finance 接收；且 6.54 是日频约 190% 换手的毛 Sharpe，作者明言 20bp 单边成本下即不盈利——它从来不是可净交易的 alpha**）。这与 McLean & Pontiff（2016, JF）的经典结论（发表后 long-short 收益缩水——精确为**发表后低 58%、样本外低 26%**，机制分解为数据挖掘上界 26% + 套利学习 32%；原 JSON 笼统写「约 50%」损失了精度，见 §7）一脉相承。

**中低频边界对本项目有利且必须写成硬约束**：本环节只锁定「事件日 → 数日到一季度的漂移持有」（PEAD 典型持有约一季度/约 60 交易日、季度调仓、长腿为主、收益集中在小盘与高摩擦标的）与「日频/周频情绪指数 → 次日到数日方向」，**明确不碰 HFT 头条延迟套利（3–8 秒级延迟竞争，非本项目战场）**。相对耐久的子信号是：(1) **PEAD**（最稳健的异象之一，但已衰减、小盘/低流动驱动→实盘可交易性需单独验证；ML+历史盈余序列可部分复活——**但对抗核查发现 ML 复活版的 edge 恰在大盘股最强，与「仅小盘可交易」框定相抵，见 §7**）；(2) **分析师预期修正/盈利调整事件**（A股华泰 2024.12 研报确认「业绩超预期+盈利调整」两维仍有效，「一致预期」维度已现失效风险）；(3) **经 SHAP 可解释的宏观新闻情绪**（FinBERT+GDELT+XGBoost，但 Sharpe>3 的数字需对样本/过拟合高度警惕）。最弱、争议最大的是**社媒情绪**（毛 Sharpe 可达 3 但极依赖数据对齐、扣成本后多半归零）与**加密 on-chain**（证据混杂，且原 JSON 引的核心 on-chain 论文预测区间是日内 1–6 小时、属 horizon 错配，见 §7）。

对一个「流程即信任、人只出经济判断」的资产无关 Agent OS，本环节的产品价值**不在于「我们有多酷的另类信号」，而在于把这类信号天然的三大杀手——PIT 时间戳泄露、扣成本后归零、发表/拥挤后衰减——做成 agent 默认强制的护栏与诚实披露**；机构合规维度（SEC 2020 另类数据/MNPI、NIST GenAI Profile 幻觉/提示注入、SR 11-7 式模型风险治理）应内建为流程门而非事后补丁。

## 2. 前沿 SOTA 与代表系统

| 系统 / 范式 | 角色 | 要点 | URL |
|---|---|---|---|
| **Lopez-Lira & Tang — GPT-4 新闻头条 → 收益漂移** | 学术 SOTA 基准 + 「信号被自己普及杀死」最硬实证 | 个股头条喂 GPT-4 判「好/坏」→显著预测后续漂移，尤其小盘+负面新闻；空头腿 Sharpe(2.01)远高于多头腿(0.78)→扣成本后多头侧脆弱。日频策略年化（毛）Sharpe 6.54(2021Q4)→3.68(2022)→2.33(2023)→1.22(2024.1–5)，作者归因 LLM 普及→定价效率提升。**【降权见 §7：JFE 非 JF；6.54 是约190%日换手的毛 Sharpe，20bp 成本下即不盈利，从非可净交易 alpha】** | https://arxiv.org/abs/2304.07619 |
| **FinBERT + GDELT + XGBoost 宏观新闻情绪** | 可解释 ML 范式（资产无关+日频+SHAP） | GDELT 全球新闻经 FinBERT 打分→日度情绪指数(均值tone/离散度/事件冲击)→XGBoost 预测 EUR/USD、USD/JPY、10Y 美债次日方向，SHAP 归因。范式对本项目高度可借鉴。**【降权见 §7：报的 OOS Sharpe 5.87/4.65 实为「含交易成本」（FX 0.02%/ZN 0.05% 单边往返），非毛收益；真正该打的点是过拟合/低交易笔数(215–1158 笔/8 年)/单一未评审预印本/跨 3 标的选择，而非成本】** | https://arxiv.org/abs/2505.16136 |
| **RavenPack（现 Bigdata.com）** | 机构级新闻/事件情绪商业标准 | Event Sentiment Score(ESS) 等专家标注的新闻/事件情绪与实体识别，是买方最常用的商业新闻 alpha 数据源，提供事件级带时间戳的结构化输出。机构事实标准，但「人人可得」→差异化受限，本身是 alpha 衰减的结构性原因之一。 | https://www.bigdata.com/ |
| **FinRL-DeepSeek / Janus-Q / InvestorBench** | LLM+RL 事件驱动 agent 研究前沿 | 把 LLM 情绪/事件理解注入 RL 交易 agent（FinRL-DeepSeek 风险敏感 RL；Janus-Q 层级门控奖励端到端事件驱动；InvestorBench 为 LLM agent 决策基准）。代表方向，**但多为研究原型、缺净成本与实盘验证，不应作为生产范式直接照搬**。 | https://arxiv.org/pdf/2502.07393 |

## 3. 关键论文（每条带 URL）

- **Can ChatGPT Forecast Stock Price Movements? Return Predictability and Large Language Models（Lopez-Lira & Tang, 2023）**——GPT-4 新闻判断预测后续漂移，集中于小盘+负面新闻（支持 limits-to-arbitrage 解释）。最重要的诚实数据点：年化（毛）Sharpe 6.54(2021Q4)→3.68(2022)→2.33(2023)→1.22(2024.1–5)，空头腿(2.01)≫多头腿(0.78)。**【high 降权见 §7：该文为 *Journal of Financial Economics*（JFE）forthcoming/在审，arXiv v6(2025-10-28) 未标注正式接收；原 JSON 三处误称「JF（Journal of Finance）接收」。且 6.54 是约 190% 日换手的毛 Sharpe，作者明确指出 20bp 单边往返成本下策略即转为不盈利——即起点本身就几乎不可净交易】**
  https://arxiv.org/abs/2304.07619

- **Does Academic Research Destroy Stock Return Predictability?（McLean & Pontiff, 2016, JF）**——97 个预测因子，**发表后 long-short 收益低 58%、样本外低 26%**；机制分解为数据挖掘上界 26% + 发表后套利学习 32%(=58%−26%)。本环节所有「新发现信号」都应被默认按此打折。**【low 降权见 §7：原 JSON 多处写「约 50%」是 58% 与 26% 的笼统折中，既非任一原始数字，也模糊了「数据挖掘 vs 套利学习」的量化分解；作为定标系数应用 58%（或分场景 26%/58%）】**
  https://jhfinance.web.unc.edu/wp-content/uploads/sites/12369/2016/02/Alpha-Decay.pdf

- **AI-Driven Alpha Decay: Algorithmic Homogenization, Reflexive Signal Erosion（Meng & Chen, 2026 预印本）**——理论模型：AI 投资者从共同数据环境提取相关信号→交易侵蚀自身 alpha；信号半衰期随 AI 采用率凸递减，当前水平约 18 个月 vs AI 前 5–7 年。**【medium 降权见 §7：纯理论闭式模型 h(φ)=ln2/[θ+δ(φ)] 在假设参数(φ≈0.7、ρ≈0.6)下推出，无实证标定、无同行评审、2026 年新挂、零被引复现；18 个月应标注为「模型输出」而非实测，不得与 McLean-Pontiff 这类实证「一脉相承」式并列】**
  https://arxiv.org/abs/2605.23905

- **Beyond the Last Surprise: Reviving PEAD with Machine Learning and Historical Earnings（Kaczmarek & Zaremba, 2025, *Finance Research Letters* Vol.86, 108751）**——用 12 季历史盈余序列（而非仅「最近一次惊喜」）+elastic net 强化 PEAD，**Sharpe 接近翻倍，且收益在大盘股最强**（因近期惊喜被快速定价）。**【medium 降权见 §7：原 JSON 称「正文付费墙(403)、结论摘要级、强度未独立核验」有误——摘要公开可得；更关键是其核心发现（大盘股最强）直接削弱了本研究反复强调的「PEAD 仅在小盘/高摩擦→不可交易」的悲观框定，属选择性引用/未充分核验】**
  https://www.sciencedirect.com/science/article/abs/pii/S1544612325020057

- **Backtesting Sentiment Signals for Trading（2025）**——DJ30 新闻情绪三模型 28 个月均正收益（回归模型 50.63%）、优于买入持有。**关键缺陷：摘要/方法未充分处理交易成本、信号衰减、look-ahead——典型「毛收益好看、净收益存疑」样本，是「需强制扣成本门」的内置反面教材**。
  https://arxiv.org/abs/2507.03350

- **Anomalies Across the Globe: Once Public, No Longer Existent?（Jacobs & Müller, 2020, JFE）**——241 个横截面异象、39 国：**仅美国有可靠的发表后 long-short 收益下降，其他国家发表后未显著衰减**。**【low 降权见 §7：原文作者的主解释明确偏向「套利障碍造成市场分割→异象代表错误定价(mispricing)而非数据挖掘」；原 JSON 把它对称化为「也可能是更深的数据挖掘偏差」，加重了原文未主张的数据挖掘读法，属轻度过度解读。对 A股「本土异象可能更耐久」的推论应按原文倾向（错误定价）而非中性偏悲观二次解读呈现】**
  https://www.sciencedirect.com/science/article/abs/pii/S0304405X19301618

- **华泰金工《博采众长：分析师预期类因子初探》（2024.12）**——A股分析师预期数据中「业绩超预期」与「盈利调整」两维仍是有效 alpha 来源，但「一致预期」维度近期呈失效风险。**A股本环节最可操作的中低频事件信号方向（研报/预期修正）及其衰减的本土实证。**
  https://finance.sina.com.cn/stock/stockzmt/2024-12-06/doc-incynmey9130907.shtml

- **Return and Volatility Forecasting Using On-Chain Flows in Cryptocurrency Markets（2024）**——USDT 从钱包流入交易所正向预测 BTC/ETH 收益；但 **BTC 净流入对收益普遍无预测力（仅 4 小时例外）、对波动率为负相关**。佐证 on-chain 证据混杂、指标高度异质、不可一概而论。**【medium 降权见 §7：该文预测区间为日内 1–6 小时（覆盖 2017–2023），属日内/短频，被原 JSON 误置于「中低频：事件日→数日至一季度」环节作证据，属 horizon 错配——USDT 流入的正向预测力在 1–6h 与在数日-季度持有上能否成立完全是两回事】**
  https://arxiv.org/pdf/2411.06327

## 4. 机构最佳实践 / 标准

- **SEC 审查重点（2020 OCIE/EXAMS 另类数据）**：另类数据使用须有书面政策审查是否含 **MNPI**、对数据供应商做入职与持续尽调、对网络抓取的合规/合同/同意链建立控制。**MNPI 是首要法律风险**。对本项目=数据来源合规门应是 agent 默认流程的一部分。
  https://www.akingump.com/en/insights/alerts/sec-division-of-examinations-finally-speaks-on-alternative-data

- **另类数据/网络抓取的 MNPI 与第三方权利风险（HFLR 路线图）**：合法另类数据须「合法获取且不构成因违反信义义务而来的 MNPI」；卫星图/聚合消费数据/政府公开备案/社媒为合法类。基金应区分公开 vs 非公开来源、留存数据获取链审计文档。
  https://www.hflawreport.com/2554036/a-fund-managers-roadmap-to-big-data-mnpi-web-scraping-and-data-quality-parttwo-of-three.thtml

- **NIST AI RMF GenAI Profile（2024.7）**：针对 LLM/生成式系统列 12 类风险（含**幻觉、提示注入、数据投毒**）、200+ 建议动作，映射 Govern/Map/Measure/Manage 四功能。对「用 LLM 读新闻出信号」的本项目=幻觉与提示注入须被当作模型风险显式治理，并保留 human-in-the-loop。
  https://www.nist.gov/itl/ai-risk-management-framework

- **Point-in-Time（PIT）数据纪律**：真正的 PIT 库须保留「首次发布值」并以独立字段记录修订值与修订日期；新闻/盈余/宏观数据常被事后重述，回测若用修订后值即引入未来信息。**新闻信号尤其要锁定「文章首次时间戳」而非抓取/索引时间。**【注：原 JSON 的 PIT 讨论全程是 Refinitiv/盈余重述这类美股语境，未落到 A股可执行口径——见 §8 缺口】
  https://perspectives.refinitiv.com/future-of-investing-trading/how-to-use-point-in-time-data-to-avoid-bias-in-backtesting/

- **GenAI in 金融服务普遍做法**：91% 企业 AI 政策含显式幻觉缓解协议、76% 含 human-in-the-loop 错误拦截。提示对 LLM 新闻信号，「人审/规则护栏 + 幻觉缓解」**已是行业基线而非加分项**。
  https://arxiv.org/pdf/2504.20086

## 5. 对 QuantBT 这套架构的推荐方向（概念级）

> 概念级方向，不点 file:line、不排实施计划。

1. **「信号纯度三连」设为本环节 agent 默认强制门，缺一不可出结论**：(1) **PIT/时间戳门**——新闻信号一律用「文章首次发布时间戳」而非抓取/索引时间，盈余/宏观用首发值+修订字段，agent 默认 shift≥1、明确禁止用事件日内未来信息；(2) **扣成本门**——任何情绪/事件信号默认先报净收益（含换手、冲击成本、A股印花税/过户费、加密 taker 费与滑点），毛 Sharpe 只能作辅助；用 Backtesting Sentiment 这类「毛好净存疑」案例做内置反面教材；(3) **衰减门**——默认做发表前/发表后、滚动窗口的 Sharpe 衰减曲线，对「近年 Sharpe 单调下行」（如 GPT 新闻 6.54→1.22）自动告警。**【修正：用 GPT 新闻案例时务必同时声明 6.54 也是扣成本前、约190%日换手、不可净交易——这恰是扣成本门应先击穿的，否则会暗示其曾是可实现 alpha，见 §7】**

2. **「中低频边界」写成 agent 硬约束与对话护栏**：本环节只接受「事件日→数日至一季度持有」（PEAD/预期修正型）与「日/周频情绪指数→次日至数日方向」两类时标；对用户提出的「抢新闻秒级反应/延迟套利」类意图，agent 应主动识别为越界（HFT）并解释为何不做——既守北极星（不碰 HFT），也是诚实的能力边界声明。**【新增护栏：on-chain 证据须按其 horizon 归位——日内 1–6h 的 on-chain 预测力（如 2411.06327）不得当作数日-季度持有的证据，见 §7】**

3. **对「信号天然脆弱性」做诚实分级披露（置信标签）而非一视同仁**：把 PEAD、分析师预期修正/盈利调整列为「**较稳健但已衰减**」（小盘/高摩擦驱动→实盘可交易性需单独验证；**注：PEAD-ML 复活版 edge 在大盘最强，分级时不应一刀切写「仅小盘」，见 §7**）；把宏观新闻情绪（可解释 ML）列为「**中等、强依赖样本期与拥挤假设、Sharpe>3 默认怀疑**」；把社媒情绪与多数 on-chain 指标列为「**弱/争议**」（数据对齐敏感、扣成本多半归零、跨标的不可移植）。让非技术用户在对话里直接看到每类信号的置信标签。

4. **对「用 LLM 读新闻出信号」内建 GenAI 治理而非事后补**：把幻觉、提示注入、数据投毒当作显式模型风险——LLM 情绪输出强制配 FinBERT/规则基线做对照与漂移监控，保留 human-in-the-loop 审阅关键事件判断，并**优先自托管（FinGPT/FinBERT）以避免把敏感标的头条发往外部 API**。对应 NIST GenAI Profile 与金融业幻觉缓解基线。

5. **「另类数据合规」做成获取阶段的流程门**：agent 在引入任一新闻/社媒/链上/抓取数据源时，默认走「来源合法性+MNPI+第三方权利/同意链」的结构化尽调清单（对标 SEC 2020 审查与 HFLR 路线图），并留存数据来源与时间戳的审计记录——契合「流程即信任」，也保护到 Binance 实盘/A股 paper 的真实可上线性。

6. **默认面向「信号组合与正交化」而非单一信号崇拜**：鉴于单信号（尤其社媒/单一 on-chain 指标）脆弱且跨币种/跨市场不可移植，引导用户把本环节产出当作「与价量/基本面正交的增量因子」，强制做相关性/拥挤度检查与按市场分段（A股 vs 加密、大盘 vs 小盘）的稳健性切片，而非把某个高毛 Sharpe 数字直接当成可上线策略。**【缺口见 §8：原 JSON 未指定用什么统计量判定「增量」——应明确为对价量+基本面因子的事后 t、IC 衰减、拥挤度的 valuation spread/持仓集中度代理】**

7. **把「幸存者/选择偏误折扣」单列为环节门（缺口补全）**：被写进论文/研报的信号本身已是大量尝试中的幸存者（file-drawer + 多重检验），本环节充斥 3–6 的预印本 Sharpe，对其尤其致命。agent 对引入的每个外部信号应默认做多重检验/选择偏误折扣（呼应簇 C 第 15 环节 t-hurdle/PBO/DSR），不能只引 McLean-Pontiff 的数据挖掘上界却不落到强制折扣。

8. **A股侧空头腿不可落地须写成硬约束（缺口补全）**：PEAD/GPT-news 的 alpha 集中在小盘+负面新闻+空头腿，而 **A股做空近乎不可行（融券池极小、T+1、涨跌停），意味着本环节在 A股几乎只能纯多头弱腿**——agent 对 A股事件信号应默认禁用「负面新闻/超预期下修→做空」侧并诚实声明，不得把美股可做空的 alpha 数字外推给 A股。

## 6. 架构级参考（少量伪代码 / schema 草图，非代码接线）

> 示意，非接线到现有代码。

**信号纯度三连门（PIT / 扣成本 / 衰减，默认不可关）：**

```
# (1) PIT/时间戳门：新闻用"首次发布时间戳"，禁抓取/索引时间；盈余/宏观用首发值
ts = event.first_published_ts          # 禁用 scrape_ts / index_ts
assert ts is not None and shift_bars >= 1
features = build(asof=ts)              # as-of 截断，禁事件日内未来信息

# (2) 扣成本门：默认先报净收益，毛 Sharpe 只作辅助标注
net = backtest(signal, costs=cost_model[market])   # 见下方 cost_model
report.primary = net.sharpe_net        # 主口径
report.gross_sharpe = net.sharpe_gross # 仅辅助；若 gross≫net 自动加"不可净交易"标
# 反面教材内置：Backtesting-Sentiment 50% 毛收益类案例

# (3) 衰减门：发表前/后 + 滚动窗 Sharpe 曲线，单调下行自动告警
curve = rolling_sharpe(signal, by="quarter")
if monotonic_decreasing(curve):        # 如 GPT-news 6.54→3.68→2.33→1.22
    alert("signal_decay: 疑似拥挤/被普及侵蚀")
# 注：引用 6.54 时强制附注"毛 Sharpe / ~190%日换手 / 20bp成本下不盈利"
```

**信号脆弱性诚实分级 + 中低频/horizon 边界（对话护栏）：**

```yaml
signal_confidence_card:
  horizon_policy:
    accepted: ["event_day -> days..one_quarter", "daily/weekly_sentiment -> next_days"]
    rejected: ["sub_second_headline_latency_arb"]   # HFT 越界，主动拒绝并解释
    onchain_horizon_guard: "日内1-6h证据不得当数日-季度证据"  # 见 §7 horizon 错配
  tiers:
    robust_but_decayed:                # 较稳健但已衰减
      - PEAD                           # 注: ML复活版 edge 在大盘最强, 勿一刀切写"仅小盘"
      - analyst_revision_earnings_adjustment   # A股华泰: 超预期+盈利调整有效, 一致预期失效风险
    medium_crowding_sensitive:         # 中等, Sharpe>3 默认怀疑
      - macro_news_sentiment_explainable_ml    # FinBERT+GDELT+XGBoost
    weak_disputed:                     # 弱/争议
      - social_media_sentiment         # 数据对齐敏感, 扣成本多半归零
      - most_onchain_indicators        # 跨币种不可移植, BTC净流入基本无预测力
  a_share_constraints:
    short_leg: disabled                # 融券池小/T+1/涨跌停 → 近乎纯多头弱腿
    note: "美股可做空的alpha数字禁外推给A股"
```

**成本模型与多重检验/选择偏误折扣 schema 草图：**

```yaml
cost_model:                            # 缺口: 原JSON只断言不参数化, 须按真实参数化
  a_share: {stamp_tax: .., transfer_fee: .., impact: <by_adv>, t_plus_1: true,
            price_limit: "10%/20%/ST"}
  crypto_binance: {taker_fee: .., funding: .., slippage: <by_market_cap>}  # 小市值山寨币拖累显著
selection_discount:                    # 幸存者/file-drawer/多重检验折扣 (呼应簇C-15)
  external_signal_haircut: required    # 引入的每个外部信号默认折扣
  feed_to: [deflated_sharpe, pbo]
genai_governance:                      # NIST GenAI Profile + 金融业幻觉缓解基线
  llm_sentiment_must_pair_baseline: finbert_or_rules   # 对照 + 漂移监控
  human_in_the_loop: key_event_review
  self_host_preferred: [fingpt, finbert]               # 避免敏感头条发往外部API
  risks_tracked: [hallucination, prompt_injection, data_poisoning]
alt_data_compliance_gate:              # SEC 2020 + HFLR 获取阶段流程门
  checklist: [source_legality, mnpi_screen, third_party_rights, consent_chain]
  audit_log: [source, first_published_ts]
```

## 7. 降权 / 争议 / 陷阱（对抗核查结论）

> 以下限定词（事实错误/呈现性夸大/外推过度/二手/选择性引用/horizon 错配/精度损失/过度解读 等）**原样保留**；凡涉「JF 接收/已确证/扣成本前/一脉相承/仅小盘不可交易」等强确定性或与原文相抵的措辞均已按对抗核查降级。任何对用户的承诺或文案，必须采用降级后的表述。

- **【low · 事实错误·期刊张冠李戴】「Lopez-Lira & Tang《Can ChatGPT Forecast…》JF（Journal of Finance）接收」（summary / sota_systems / key_papers 三处）**——**事实错误**。该文是 *Journal of Financial Economics*（JFE）forthcoming/在审，**不是** Journal of Finance（JF）。arXiv 2304.07619 最新 v6(2025-10-28) 页面甚至未标注正式接收，仅「previously posted in SSRN」。这是本环节「最硬实证锚点」的引用，期刊张冠李戴说明研究在它最依赖的证据上未做精确核对。结论方向不受影响（JFE 与 JF 同为顶刊），但削弱「最确凿锚点」的可信外观。
  https://arxiv.org/abs/2304.07619

- **【medium · 呈现性夸大】GPT 新闻策略「年化 Sharpe 6.54→3.68→2.33→1.22」在 summary 中以「年化 Sharpe」直接呈现**——**数字本身经二手源（Swedroe）核实无误，但语境被淡化**：这是一个「每日再平衡、约 190% 日换手」策略的**毛 Sharpe**，作者明确指出「在 20bp/单边往返成本下策略即转为不盈利」。即 6.54 这个亮眼起点本身就几乎不可净交易。研究把 6.54→1.22 当作衰减叙事的支柱，却未在 summary 主线突出「6.54 也是扣成本前、不可净交易」——这恰恰是研究自己倡导的「扣成本门」应当先击穿的。属呈现性夸大（数字真，但暗示其曾是可实现 alpha）。
  https://arxiv.org/abs/2304.07619

- **【medium · 外推过度·二手数字】《AI-Driven Alpha Decay》(arXiv 2605.23905) 信号半衰期「从 AI 前 5–7 年压缩到当前约 18 个月」**——**真实预印本（2026-03-23, Meng & Chen），但研究已自承「理论模型+外推」，须进一步降权**：18 个月 vs 5–7 年完全由其闭式半衰期公式 h(φ)=ln2/[θ+δ(φ)] 在假设参数（φ≈0.7、ρ≈0.6）下推出，**无实证标定、无同行评审、2026 年新挂、零被引复现**。把它与 McLean-Pontiff（实证）「一脉相承」并列，会让读者误以为 18 个月有实测支撑。属外推过度+二手数字风险——文案须标注为「模型输出」而非实测。
  https://arxiv.org/abs/2605.23905

- **【medium · 选择性引用·未充分核验】PEAD「小盘/低流动驱动→实盘可交易性存疑」+ 把 Kaczmarek & Zaremba《Beyond the Last Surprise》正文称「付费墙(403)、结论摘要级、强度未独立核验」**——**内部矛盾+核验不足**。该文（FRL Vol.86, 108751, 2025）摘要可公开获取，明确结论是：用 12 季历史盈余+elastic net 使 Sharpe「接近翻倍」，且**「收益在大盘股最强」（因近期惊喜被快速定价）**。这直接削弱研究自己反复强调的「PEAD 只在小盘/高摩擦→不可交易」的悲观框定——ML 复活版的 edge 恰在大盘。研究引用了该文却漏读其与自身论点相抵的核心发现。属未充分核验+选择性引用。
  https://www.sciencedirect.com/science/article/abs/pii/S1544612325020057

- **【medium · horizon 错配】on-chain 证据（arXiv 2411.06327）被纳入「中低频（数日到一季度）」环节作 on-chain 信号证据**——**horizon 错配**。该文的预测区间是 **intraday 1–6 小时**（覆盖 2017–2023），属日内/短频，而非研究自定义的「中低频：事件日→数日至一季度」。把一个 1–6 小时预测力的混杂结果当作中低频 on-chain 信号的证据，违反研究自己设定的时标边界；USDT 流入的「正向预测力」在 1–6h 与在数日-季度持有上能否成立完全是两回事。属证据-结论 horizon 不匹配。
  https://arxiv.org/abs/2411.06327

- **【medium · 定性错误+怀疑用错理由】FinBERT+GDELT+XGBoost「OOS Sharpe 5.87/4.65」被研究归类为「扣成本前」毛收益陷阱之一**——**两点需修正**。(1) 定性错误：该文（arXiv 2505.16136）Sharpe 5.87/4.65 实际是「**含交易成本**」（FX 0.02%、ZN 0.05% 单边往返），并非毛收益——把它与社媒 3.17、回测 50% 等真·毛收益并列为「扣成本前」案例是事实不准。(2) 真正该打的点研究反而没点透：8 年 OOS 但每标的仅 215–1158 笔交易、单一未评审预印本、跨 3 标的选择、TimeSeriesSplit 跨折调参导致的过拟合风险、无拥挤分析——日频宏观方向 Sharpe 5.87 的不可信来自**样本/过拟合/选择**，而非成本。研究的怀疑方向（「扣成本归零」）用错了理由。
  https://arxiv.org/html/2505.16136

- **【low · 精度损失】McLean & Pontiff（2016）「发表后 alpha 缩水约 50%」/「-50%」（summary / key_papers / pitfalls 多处）**——**精度损失**。原文精确数字是：样本外低 26%、发表后低 58%，并据此分解为数据挖掘上界（26%）与发表后套利学习（32%=58%−26%）。「约 50%」是把 58% 和 26% 笼统折中，既非任一原始数字，也模糊了研究自己想强调的「数据挖掘 vs 套利学习」两机制的量化分解。结论方向对，但作为「所有新信号默认打折」的定标系数，用 58%（或分场景 26%/58%）比「50%」更准确。
  https://onlinelibrary.wiley.com/doi/abs/10.1111/jofi.12365

- **【low · 过度解读】Jacobs & Müller（2020）：美国外异象发表后未显著衰减，研究框定为「双刃：既是机会也是数据挖掘风险」**——**框定偏置**。原文作者的主解释明确偏向「套利障碍造成市场分割→异象代表错误定价（mispricing）而非数据挖掘」。研究把它对称化为「也可能是更深的数据挖掘偏差」，实际上加重了原文未主张的数据挖掘读法。对 A股「本土异象可能更耐久」的推论，研究给的是中性偏悲观的二次解读，与原文倾向不完全一致。属轻度过度解读。
  https://www.sciencedirect.com/science/article/abs/pii/S0304405X19301618

**通用陷阱清单（工程红线）：**

- **毛收益陷阱**：本环节几乎所有亮眼数字（社媒 Sharpe 3.17、情绪回测 50%、宏观情绪 Sharpe 5.87、GPT 6.54）都是扣成本前/样本内/外推；中低频高换手新闻信号扣成本后常大幅缩水甚至归零。务必默认净收益口径。**（注：5.87/4.65 实为含成本，怀疑应改打过拟合/低交易笔数；6.54 是毛 Sharpe 且 20bp 下不盈利——见上）**
- **发表/拥挤衰减且正被 AI 加速**：McLean-Pontiff 发表后低 58%（非「约 50%」）；GPT 新闻策略毛 Sharpe 三年内 6.54→1.22；理论上信号半衰期从 5–7 年压到约 18 个月（**纯理论外推，非实测**）。任何「最新 SOTA 信号」都应假定正在快速失效。
- **Look-ahead/PIT 泄露是头号技术坑**：新闻「抓取/索引时间」≠「首次发布时间」；盈余/宏观数据被事后重述。用修订值或晚到时间戳回测=偷看未来，会系统性高估 alpha。**（缺口：A股「业绩预告/快报/正式年报」三阶段披露、停复牌、公告日 vs 报告期 vs 实际可得日错位未处理，见 §8）**
- **小盘/高摩擦驱动→可交易性幻觉**：PEAD 与 GPT 新闻 alpha 集中在小盘、负面新闻、低流动标的与空头腿，这些恰是冲击成本最高、A股/加密最难做空或有涨跌停/借券约束之处，纸面 alpha 难落地。**（注：PEAD-ML 复活版 edge 在大盘最强，分级勿一刀切；A股空头腿近乎不可落地——见 §5 第 8 条、§8）**
- **数据质量坑**：GDELT 关键字段准确率约 55%、约 20% 冗余，直接喂模型会污染信号，使用前必须纠错去重；社媒情绪对「数据对齐方式」极敏感，对齐不当会产生虚假预测力（spurious）。
- **on-chain 证据混杂且不可移植**：realized/unrealized value、稳定币流入交易所有边际预测力，但 BTC 净流入对收益基本无预测力，且对某币有效的指标换币即失效——不可把单指标当通用 alpha。**（注：相关证据多为日内 1–6h，horizon 须归位，见上）**
- **MNPI/合规尾部风险**：网络抓取或某些另类数据可能构成 MNPI 或触发第三方权利主张，是 SEC 重点审查对象；一次合规事故的代价远超信号本身的边际 alpha。
- **LLM 特有风险**：用 LLM 读新闻会引入幻觉/提示注入/对头条措辞过度敏感；把敏感标的头条发往外部 API 还有信息泄露与可复现性问题。**（缺口：GPT 类新闻文章普遍受「训练数据截止 vs 新闻时间戳泄露」「不同 GPT 版本/API 时点不可复现」质疑——研究在 pitfalls 提了 LLM 泄露，却没把这盆冷水泼到它最依赖的 Lopez-Lira 锚点本身：~90% 初始反应命中率有多大比例来自模型预训练已见过该新闻，未被质疑，见 §8）**
- **二手数字与未复现**：不少惊人 Sharpe 来自工作论文/预印本未经独立复现；Jacobs-Müller 显示「发表即死」有地域性（**且原文倾向错误定价解释，非数据挖掘——见上**），提示美国外异象的稳健性既可能是机会也可能是更深的数据挖掘风险。

## 8. 开放问题

- **A股 PIT/数据落地的具体硬障碍未触及**：研究把 PIT 当通用流程门，但 **A股特有的「业绩预告/快报/正式年报」三阶段披露、停复牌、ST/涨跌停、Tushare 等数据源的财报「公告日 vs 报告期 vs 实际可得日」错位**，才是 A股事件信号 look-ahead 的真实雷区；研究全程用 Refinitiv/盈余重述这类美股语境的 PIT 讨论，没有落到 A股可执行口径。
- **A股空头腿近乎不可落地未正面处理**：研究反复说 PEAD/GPT-news alpha「集中在小盘+空头腿」→不可交易，却没处理 A股做空几乎不可行（融券池极小、T+1、涨跌停）这一致命约束——意味着 A股侧本环节最大的「负面新闻/超预期下修→做空」价值在制度上基本被锁死，只剩多头侧弱腿。这个「A股近乎纯多头、空头腿无法落地」的结论本应是 design_directions 的硬约束，却缺席（已在 §5 第 8 条补为推荐）。
- **缺少对自身核心叙事的反证文献**：研究单边采信「LLM 普及→alpha 被自己杀死」，但未纳入与之冲突的近期工作（如 LLM 信号在不同 prompt/模型/对齐下结果高度不稳、复现性争议；以及「新闻反应不足是行为性持久异象」一派认为 PEAD 类漂移有结构性而非纯套利学习成因）。一面倒引用衰减派，缺对立证据的对抗呈现。
- **Lopez-Lira 已知的可复现性/数据泄露争议未提**：GPT 类新闻预测文章普遍受「训练数据截止 vs 新闻时间戳泄露」「不同 GPT 版本/API 时点不可复现」质疑——即该锚点的初始反应约 90% 命中率有多大比例来自模型预训练已见过该新闻，研究未质疑（研究在 pitfalls 提了通用 LLM 泄露，却没泼到它最依赖的锚点本身）。
- **成本模型对 A股/加密的量级缺乏校准**：研究列了印花税/过户费/taker 费，但没给中低频换手下的量级感（如季度调仓 PEAD 的实际年化换手与冲击成本区间、加密 Binance taker+滑点在中小市值山寨币上的真实拖累），使「扣成本门」停留在口号而非可参数化的门限。
- **幸存者/选择偏误未作为独立门**：研究强调发表后衰减，但没把「被写进论文/研报的信号本身已是大量尝试中的幸存者」（file-drawer + 多重检验）单列为环节门——这与 t-hurdle/PBO/DSR 同源，且对二手 Sharpe（本环节充斥 3–6 的预印本数字）尤其致命；研究引了 McLean-Pontiff 的数据挖掘上界，却没要求 agent 对引入的每个外部信号做多重检验/选择偏误折扣（已在 §5 第 7 条补为推荐）。
- **「信号正交化/组合」方向缺可证伪的检验设计**：design_directions 提倡把另类信号当「正交增量因子」并做相关性/拥挤检查，但没指定用什么统计量判定「增量」（如对价量+基本面因子的事后 t、信息系数衰减、因子拥挤度的 valuation spread/对冲基金持仓集中度代理），停留在理念层。

## 9. 参考文献（URL）

- Can ChatGPT Forecast Stock Price Movements?（Lopez-Lira & Tang, 2023；**JFE forthcoming/在审，非 JF；6.54 为毛 Sharpe、20bp 成本下不盈利**）：https://arxiv.org/abs/2304.07619
- Does Academic Research Destroy Stock Return Predictability?（McLean & Pontiff, 2016, JF；**发表后低 58%/样本外低 26%，非「约 50%」**）：https://jhfinance.web.unc.edu/wp-content/uploads/sites/12369/2016/02/Alpha-Decay.pdf
- McLean & Pontiff 2016（Wiley 官方页）：https://onlinelibrary.wiley.com/doi/abs/10.1111/jofi.12365
- AI-Driven Alpha Decay（Meng & Chen, 2026 预印本；**纯理论外推，18 个月非实测，无评审/复现**）：https://arxiv.org/abs/2605.23905
- Beyond the Last Surprise: Reviving PEAD with ML（Kaczmarek & Zaremba, 2025, FRL 108751；**摘要公开可得，ML 复活版 edge 在大盘最强**）：https://www.sciencedirect.com/science/article/abs/pii/S1544612325020057
- Backtesting Sentiment Signals for Trading（2025；**毛收益好、净收益存疑的反面教材**）：https://arxiv.org/abs/2507.03350
- Anomalies Across the Globe: Once Public, No Longer Existent?（Jacobs & Müller, 2020, JFE；**原文倾向错误定价解释，非数据挖掘**）：https://www.sciencedirect.com/science/article/abs/pii/S0304405X19301618
- FinBERT+GDELT+XGBoost 宏观新闻情绪（arXiv 2505.16136；**Sharpe 5.87/4.65 为含成本，真问题是过拟合/低交易笔数/单预印本**）：https://arxiv.org/html/2505.16136
- On-Chain Flows return/vol forecasting（arXiv 2411.06327；**预测区间为日内 1–6h，属 horizon 错配**）：https://arxiv.org/pdf/2411.06327
- FinRL-DeepSeek / 事件驱动 LLM+RL agent（研究原型，无净成本/实盘验证）：https://arxiv.org/pdf/2502.07393
- 华泰金工《博采众长：分析师预期类因子初探》（2024.12；A股研报/预期修正本土实证）：https://finance.sina.com.cn/stock/stockzmt/2024-12-06/doc-incynmey9130907.shtml
- SEC Division of Examinations on Alternative Data（2020；MNPI 首要风险）：https://www.akingump.com/en/insights/alerts/sec-division-of-examinations-finally-speaks-on-alternative-data
- HFLR · Big Data: MNPI, Web Scraping and Data Quality（获取阶段尽调路线图）：https://www.hflawreport.com/2554036/a-fund-managers-roadmap-to-big-data-mnpi-web-scraping-and-data-quality-parttwo-of-three.thtml
- NIST AI RMF · Generative AI Profile（幻觉/提示注入/数据投毒 12 类风险）：https://www.nist.gov/itl/ai-risk-management-framework
- Refinitiv · Using Point-in-Time Data to Avoid Bias in Backtesting：https://perspectives.refinitiv.com/future-of-investing-trading/how-to-use-point-in-time-data-to-avoid-bias-in-backtesting/
- Understanding and Mitigating Risks of Generative AI in Financial Services（arXiv 2504.20086；91% 幻觉缓解/76% HITL 基线）：https://arxiv.org/pdf/2504.20086
- RavenPack / Bigdata.com（机构级新闻/事件情绪商业标准）：https://www.bigdata.com/
- FNSPID（KDD2024 时间对齐新闻+价格数据集，开源回测底座）：https://github.com/Zdong104/FNSPID_Financial_News_Dataset
- FinBERT（Prosus/ProsusAI，开源情绪基线）：https://finbert.org/
- GDELT Project（全球新闻事件/情绪，含中文；**关键字段准确率约 55%、约 20% 冗余，须纠错去重**）：https://www.gdeltproject.org/
- FinGPT / FinNLP（AI4Finance，可自托管 LLM 金融 NLP，规避外部 API 泄露）：https://github.com/AI4Finance-Foundation/FinGPT
- CryptoQuant（on-chain 指标商业源，可与 Glassnode 交叉校验；**跨币种不可移植**）：https://cryptoquant.com/
