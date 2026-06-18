# 09 · 数据工程官（bitemporal/PIT/数据可信门）

> 机构级 Agent OS 成品环节深挖 · 全程 Opus 4.8 · 对抗式核查已降权 · 重心=前沿研究+概念级推荐 · 不含 file:line 代码接线
> 簇 B

## 1. 一句话定位

数据工程官是整个机构级 Agent OS 的**信任地基**：它要保证「研究时看到的数据 = 当时真实可知的数据 = 实盘时同源产出的数据」这一条不可回退的等式，靠三块拼成——**bitemporal 双时间轴**（事实何时生效 × 何时被系统知道）、**PIT 正确性**（反 look-ahead / 反 survivorship 的工程实现）、**数据可信门**（数据合约 + 质量门 + 研究/实盘同源）。

## 2. 前沿 SOTA 与代表系统

全球前沿在这一环上已高度收敛。下列系统覆盖「存储底座 → PIT 数据范式 → 同源特征 → 质量门 → 可观测性 → as-of 原语」六层：

| 系统 | 角色 | 要点 | URL |
|---|---|---|---|
| **ArcticDB**（Man Group + Bloomberg，开源） | 存储底座候选 | 为 Python 数据科学打造的高性能 DataFrame DB，版本化修改 + time-travel，可回到任一历史版本。Pandas-in/Pandas-out，十亿行级。**注意**：它给的是「数据何时被写入/改版」的版本化 time-travel，是否在经典意义上独立建模 valid-time / known_at 业务轴，公开文档无法确认（见 §7 降级）。 | https://github.com/man-group/ArcticDB |
| **Compustat Point-in-Time (S&P) + IBES + CRSP** | PIT 数据范式参照 | 机构基本面 PIT 的概念范式：同时保存「最初申报值」与后续「重述值」，可还原任意月末「当时所见」；CRSP 提供 survivor-bias-free 库与退市收益合并算法。**边界**：Compustat PIT 仅自 1987 起、只覆盖北美（见 §7）。 | https://www.crsp.org/research/crsp-survivor-bias-free-us-mutual-funds/ |
| **Feast / Tecton / Vertex AI Feature Store** | 同源特征架构 | 用 offline store 的 point-in-time correct join 从架构上消除 training-serving skew；同一特征变换定义编译到批训练与低延迟服务两端。我们的特征层可借鉴其 PIT-join 与「同源代码」范式（即便不引入完整 feature store）。 | https://docs.feast.dev/ |
| **Great Expectations / dbt tests + dbt-expectations / Soda(SodaCL)** | 声明式质量门 | 数据可信门的 SOTA 开源栈：GE 做校验套件 + checkpoint；dbt tests/contracts 做模型层断言与 schema 合约；Soda 用人类可读 YAML 做 freshness/null/重复/阈值并落地「数据合约」。可实现为 hard/soft/threshold/quarantine 多档闸。 | https://greatexpectations.io/ |
| **Monte Carlo / Soda（数据可观测性）** | 被动监控 | ML 驱动的 freshness、schema 变更、体量与分布异常监控，把「数据宕机（data downtime）」当一等故障 SLA 化。适合作为主动断言之外的被动监控补充。 | https://www.montecarlodata.com/ |
| **XTDB（bitemporal 数据库）** | bitemporal 查询语义参考 | 为高效、全局一致的 point-in-time 查询优化，显式用 (transaction-time, valid-time) 一对时间戳。是 bitemporal 查询语义的清晰实现参考。 | https://v1-docs.xtdb.com/concepts/bitemporality/ |
| **pandas merge_asof / Polars join_asof** | as-of join 原语 | 「取 ≤t 的最近一行」连接，是 PIT 特征对齐的最小可用算子。可作为我们 PIT join 的底层语义基准与回归测试 oracle。 | https://pandas.pydata.org/docs/reference/api/pandas.merge_asof.html |

## 3. 关键论文（每条带 URL）

- **Seven Sins of Quantitative Investing**（Luo et al., Deutsche Bank Markets Research, 2014）—— 机构界关于回测偏差的标准引用。Sin#1 survivorship、Sin#2 look-ahead 直接相关；关键技术点：组合收益若用 `w_t·r_t` 计算即犯 look-ahead（权重用到 t 时点信息，收益却是 t-1 执行），须对权重 shift。我们栈里已对齐（predict→top-N→shift1）。注：PDF 本体二进制不可解析，内容由多份二手源交叉佐证。
  https://hudsonthames.org/wp-content/uploads/2022/01/DB-201409-Seven_Sins_of_Quantitative_Investing.pdf

- **The Deflated Sharpe Ratio**（Bailey & López de Prado, 2014, SSRN 2460551）—— 在多次试验（选择偏差）+ 回测过拟合 + 非正态下，对被多重检验抬高的 Sharpe 做「标度去通胀」。与本环节互补：数据门保证「数据可信」，DSR 保证「结论可信」。
  https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2460551

- **The Probability of Backtest Overfitting**（Bailey, Borwein, López de Prado, Zhu, SSRN 2326253）—— 提出 PBO，用 CSCV（组合对称交叉验证）估计「所选策略其实是过拟合」的概率；试验次数越多，过拟合概率上升越快。支撑「试验计数追踪」应是 Agent OS 一等公民。**注**：PBO/CSCV 明确不检测 look-ahead/泄露（见 §7）。
  https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2326253

- **Adjusted Prices Without Look-Ahead Bias**（Portfolio Optimizer，技术博文）—— 论证后复权以「最后一日」为锚，任一历史日复权价隐含其后所有拆股/分红（给出 SPY 2021-01-04 复权价随 2022 年分红被回溯改写的实例）。**但该博文自承社区对其实际显著性有争议**，且推荐解法是前复权（见 §7）。
  https://portfoliooptimizer.io/blog/adjusted-prices-without-look-ahead-bias/

- **Dealing with Delistings**（Alpha Architect，综述 Beaver-McNichols-Price）—— 退市收益若不并入会系统性高估账面类异象收益；给出把 CRSP 退市信息合理并入最终收益库的算法。直接指导 PIT universe 应保留退市标的至最后交易日并赋予退市收益。
  https://alphaarchitect.com/dealing-with-delistings-a-critical-aspect-for-stock-selection-research/

- **CRSP Survivor-Bias-Free 数据 / 长样本存活缺口** —— 可信量级锚点：CRSP 美股 1926–2001 存活无偏年化约 7.4% vs 有偏约 9.0%，约 **1.6%/年** 缺口。**注**：该具体数对多为二手转引，且有反向警示文献（Jorion-Goetzmann、Schwert《The Myth of 1926》）质疑 1926 起点本身的幸存性（见 §7）。
  https://www.crsp.org/research/crsp-survivor-bias-free-us-mutual-funds/

- **Rules of Machine Learning（Zinkevich, Google）— Rule #32「尽量共享训练/服务的变换代码」** —— training-serving skew 的权威工程准则：训练与服务应通过同一段代码/同一 feature-store 变换计算特征，offline 用 point-in-time join 防时间泄露。是「研究=实盘同源」最被引用的一手出处。
  https://developers.google.com/machine-learning/guides/rules-of-ml

- **Survivorship and Delisting Bias in Cryptocurrency Markets**（University of St. Gallen）—— 加密退市偏差的**同行评审学术锚点**，应优先于 CoinMarketCap/StratBase 等 vendor 口径用于支撑加密侧论点（对抗核查指出的漏点，已补入）。
  https://www.alexandria.unisg.ch/bitstreams/2bc8397d-47dd-4f66-8467-9004b2c9d212/download

## 4. 机构最佳实践 / 标准

- **SQL:2011 双时间轴标准**：system-versioned 表（`PERIOD FOR SYSTEM_TIME`，自动维护 = transaction/记录时间）+ application-time period 表（= valid/生效时间），两者组合即 bitemporal；配 `CONTAINS`/`OVERLAPS`/`PRECEDES` 等时间谓词。把「knowledge_date / transaction_time」落到工业标准词汇上。
  https://en.wikipedia.org/wiki/SQL:2011

- **bitemporal 在金融/审计的合规驱动**：可同时重建报表「当时所见」与「事后更正后应如何」。Dodd-Frank 等监管是银行最早大规模采用 bitemporality 的主因——为「流程即信任」提供机构话术。
  https://en.wikipedia.org/wiki/Bitemporal_modeling

- **基本面 PIT**：同时保留「初次申报值」与「后续重述值」，按月末快照还原「当时所见」；季度数据滞后约 3 个月、年度约 6 个月以反映披露滞后。A股侧对应：用 Tushare `f_ann_date`（实际/正式公告日）而非 `end_date` 对齐，并保留 disclosure_date 的计划/实际/修订日。**注**：美股滞后经验值不可直接套到 A股（见 §7、§8）。
  https://www.tushare.pro/document/2?doc_id=162

- **数据质量门的四档闸**：hard gate（关键校验失败即阻断管线）、soft gate（放行但隔离到 quarantine 表）、threshold gate（错误率低于容忍度才放行），并把「dbt tests 通过才允许开训」作为防止用坏数据训练的自动门。
  https://www.ataccama.com/blog/the-shift-left-playbook-data-contracts-data-quality-gates-and-feedback-loops

- **模型风险治理三支柱**（独立验证 / 持续监控 / 文档化），将数据质量、血缘、可复现纳入模型风险评估；NIST AI RMF 与 CDMC+ 把「数据与模型作为一对资产共同治理」。**注**：SR 11-7 是美国银行业模型风险监管，对单用户量化项目是「合规话术借用」而非强制约束（见 §7）。
  https://www.modelop.com/ai-governance/ai-regulations-standards/sr-11-7

- **研究→实盘同源**：统一数据层用同一组 API / 同一段特征变换贯穿回测与实盘；feature store 用 offline point-in-time join 保证训练标签对齐其「当时可见」的特征行（周一 10:00 预测 → join ≤ 周一 10:00 可见的画像行）。
  https://developers.google.com/machine-learning/guides/rules-of-ml

## 5. 对 QuantBT 这套架构的推荐方向（概念级）

> 概念级方向，不点 file:line、不排实施计划。

1. **把 `knowledge_date`（第一次可知时点）立为整库第一公民**：核心事实表落 bitemporal 双轴（valid/事件轴 + knowledge/记录轴），Agent 产出的每一份特征/标签强制带 `known_at`；A股基本面以 `f_ann_date` + 披露滞后入轴，价格以「未复权 + 事件流」入轴。对用户只暴露一句话契约——「回测只会看到当天真实可知的数据」——工程全在轴上保证。**必要性分级**（吸收对抗核查的过度工程警示）：并非所有表都需双轴，部分只需 as-of 单轴 + 落库时间戳即可，双轴成本应按表分级，而非全库一刀切。

2. **数据可信门做成「编译期 + 运行期」双层**：把反 look-ahead / 反 survivorship / 复权方向 / 同源这几条铁律编译成不可关闭的硬门（hard gate，失败即拦截并隔离到 quarantine），再叠加 GE/dbt/Soda 风格的可配置软门（freshness/null/分布漂移）。门的判定与原因用 SodaCL 式人类可读语言呈现给非技术用户——直接服务「流程即信任」。

3. **PIT 正确性要有专门的「时点重放测试」，而非只靠通用质量门**：通用质量门（GE/dbt）默认查 null/range/uniqueness，不会自动发现「复权泄露」「沿错轴 join」。用 as-of join（merge_asof 语义）作 oracle，对任一历史日断言「此刻可见集合 = 当时真实可知集合」，并对复权方向、universe 存活、权重 shift 做对抗式回归。把这套测试作为数据集发布的准入条件。

4. **研究=实盘同源做成架构约束而非约定**：特征/标签的变换只允许有一份代码，回测与实盘共用；杜绝「研究一套、上线一套」。借鉴 feature store 的 offline PIT join + 同源变换思想，即便不引入完整 feature store，也应把「同一段 transform、两端复用」设为不可绕过的接线。

5. **把「数据信任」与「结论信任」串成链，但不夸大其闭合性**：数据门（本环节）→ 试验计数追踪 → PBO/DSR 去通胀，统一记入每个 run 的不可篡改审计元数据（数据快照版本 / knowledge_date 截点 / 门禁结果 / 试验次数）。**注意**：PBO/CSCV 不检测泄露、对 regime 漂移盲，不能替数据门兜底——它只覆盖「同一份数据上多次试验的选择偏差」这一维度（见 §7）。

6. **为加密侧单独建「静默下架/死币」防线**：把交易所下架、流动性枯竭、价格归零都当显式事件入 universe，保留至最后可交易日；对「现存币种」口径的回测默认打 survivorship 警示。A股侧对称处理 ST/退市与停牌。两侧共用同一套 PIT-universe 抽象，兑现「资产无关」。

7. **把已知坏数据源沉淀为「已知缺陷登记 + 入库适配器层强制校验」**：在采集边界用「行数对账、NULL 显式化、参数语义校验」拦住静默截断，绝不让不报错的坏数据穿过可信门。**注**：对抗核查指出，本项目栈里真实存在的静默失败模式是 backfill 路径上「`df.empty` 时不落盘」与「`except` 吞异常只计数」这类静默吞错（而非 §7 中被证伪的 namechange 缺陷）——这才是该适配器层优先要盯的真实模式。

## 6. 架构级参考（少量伪代码 / schema 草图，非代码接线）

> 示意，非接线到现有代码。

**bitemporal 事实行（双轴 schema 草图）：**

```
fact_fundamental(
  symbol            text,
  field             text,
  value             numeric,
  -- valid / 事件轴：事实在现实世界中生效的时点
  valid_from        date,        -- e.g. 财报期末 end_date
  valid_to          date,        -- NULL = 至今
  -- knowledge / 记录轴：数据第一次「可知」的时点（PIT join 锚点）
  known_at          timestamptz, -- A股 = f_ann_date + 披露滞后；理想为 first-seen 落库时间
  source_revision   text,        -- 区分初次申报 vs 重述
  ingest_run_id     text         -- 审计血缘
)
-- 铁律：所有 PIT join 沿 known_at（"第一次可知"），绝不沿 valid_from/end_date
```

**PIT as-of join（merge_asof 语义，作为 oracle）：**

```
features_at(decision_ts) =
    merge_asof(
        left  = decisions[decision_ts],
        right = facts.sort_by(known_at),
        on    = known_at,
        direction = 'backward'        # 仅取 known_at <= decision_ts 的最近行
    )
# 断言：result.known_at <= decision_ts  对每一行成立
```

**价格入轴（未复权 + 事件流，避免后复权回溯泄露）：**

```
price_raw(symbol, dt, close_unadjusted)            # 回测当下只见未复权价
corp_action(symbol, ex_date, type, ratio, known_at)# 拆股/分红作为事件
# 复权仅在"因子/收益计算"层用截至当下已发生的事件构造，
# 回测成交价层不触碰未来事件
```

**质量门四档闸（声明式草图）：**

```yaml
gate: fundamental_publish
checks:
  - rule: no_lookahead          # 硬门：known_at <= as_of 对每行成立
    on_fail: block
  - rule: universe_survival     # 硬门：退市标的保留至最后交易日
    on_fail: block
  - rule: adjustment_direction  # 硬门：禁止后复权价直接入回测成交层
    on_fail: block
  - rule: freshness < 36h       # 软门
    on_fail: warn
  - rule: null_rate < 2%        # 阈值门
    on_fail: quarantine         # 隔离到 quarantine 表，不阻断
  - rule: row_count_reconcile   # 拦"静默丢行/隐式过滤/NULL 当 FALSE"
    on_fail: block
```

## 7. 降权 / 争议 / 陷阱（对抗核查结论）

> 以下限定词（夸大/争议/撤稿/二手/不可外推/单源营销/被代码证伪 等）原样保留，凡涉「已验证/已确证/原生/完整链」的强确定性措辞均已按对抗核查降级；任何对用户的承诺或文案，必须采用降级后的表述。

- **【high · 被代码库证伪 refuted_by_codebase】「用户自己栈里的 Tushare `namechange` 接口存在『日期参数硬映射到 ann_date + NULL 行被静默丢弃』的已验证缺陷」**——经代码核查**查无实据**。整个 backend 中 `namechange` 仅出现在一处接口注册表（market-scope 直通拉取），**既无「日期参数硬映射到 ann_date」也无「NULL 行静默丢弃」逻辑**，tushare_provider 不含 `namechange`，亦无任何测试引用。该「已验证缺陷」的具体机制在当前代码里不存在，属于把假设性风险包装成「用户栈里已证实」的过度断言。**真正存在的静默行为是另一回事**：backfill 路径上 `df.empty` 时不落盘、`except` 吞异常只计数——这才是「静默坏数据 > 显式报错」的真实实例，应把火力对准它。
  https://www.tushare.pro/document/2?doc_id=161

- **【medium · 夸大】「ArcticDB『原生 bitemporal』，是最贴近 knowledge_date 时间旅行的存储底座」**——ArcticDB 的「bitemporal」是**版本化 time-travel**（回到某 transaction/系统时间点的历史版本 + as-of 取版本），官方 FAQ 用了 bitemporal 一词，但公开文档**无法确认它在经典意义上独立建模了 valid-time / known_at 业务轴**。它给的是「数据何时被写入/改版」，不等于「事实何时第一次可知」。把它当「knowledge_date 时间旅行底座」夸大了其能力——两轴需使用者自己在 schema 上显式建模，ArcticDB 不会自动替你对齐 ann_date + 披露滞后。

- **【medium · 争议 disputed】「后复权价泄露未来已『已确证/已被独立证实』，前复权是正确解（Portfolio Optimizer 博文）」**——方向正确但**确定性被拔高**。(1) Portfolio Optimizer 博文本身在结尾**自承社区对其实际显著性有争议**（引用 StackExchange「是否真把它当 look-ahead 还有分歧」），并非「已确证」铁律。(2) CRSP——本研究奉为标准的同一机构——**恰恰推荐以最后一日为锚做复权**，与「后复权=泄露」强结论直接张力。(3) 该博文推荐的解法是**前复权**，并未推荐研究归到它名下的「未复权价+事件流」方案——研究把自己偏好的方案安到了来源头上。(4) 研究自己在陷阱里也承认前复权有代价（早期价失真）。应降级为「**方向公认、量级与必要性视频率/用途而定、有争议**」。
  https://portfoliooptimizer.io/blog/adjusted-prices-without-look-ahead-bias/

- **【medium · 单源营销 single_source_marketing】「加密 ~58% 代币已死（CoinMarketCap 估算）/ 回测 ~4x 虚高（StratBase）」**——两个数字都是**单源厂商口径，定义松散**。58% 的「死」判据是 Twitter 失活/低流动性/低成交（营销级口径，非严谨退市定义；同口径下另有 53.2%、近三分之二等互相打架的版本）；4x 来自单篇 vendor 博客（非同行评审）。研究已自我标注存疑（诚实），但仍写进 summary/pitfalls 作论据底色，**建议进一步弱化**。可引的同行评审锚点是 University of St. Gallen《Survivorship and Delisting Bias in Cryptocurrency Markets》（见 §3）。
  https://www.alexandria.unisg.ch/bitstreams/2bc8397d-47dd-4f66-8467-9004b2c9d212/download

- **【low · 过时 outdated】「CRSP SBF 共同基金库含 6.4 万只、其中 3.1 万只已退市」**——**数字已过时**。CRSP 2025-01 季度更新显示总数约 **73,474**、已退市（inactive）约 **43,358 个 class**（对应约 20,943 unique funds）。属「陈旧」而非「错误」，方向（退市占比可观）仍成立，但对用户呈现的精确量级应更新，否则被反驳为引用旧快照。
  https://www.crsp.org/wp-content/uploads/mf_202501.pdf

- **【low · 二手转引】「CRSP 美股 1926–2001 存活无偏 7.4% vs 有偏 9.0%、约 1.6%/年缺口」**——该具体数对的**一手出处薄弱**：本轮检索能定位到它的多是二手博客转引，而非 CRSP 原始出版物清晰页码。更要紧的是存在**直接反向警示**——Jorion-Goetzmann 与 Schwert《The Myth of 1926》质疑我们对美股长期收益究竟知道多少、1926 起点本身可能有幸存性问题。把 1.6%/年 当「确凿可写进文案」的硬锚应标注为**二手转引、量级随样本与方法变动**。

- **【medium · 夸大闭合性】「数据门 + 试验计数 + PBO/DSR 是『完整的反过拟合链』」**——**高估了 PBO/CSCV 的角色与可移植性**。(1) PBO/CSCV **明确不检测 look-ahead/数据泄露/无效特征，对样本外 regime 漂移盲**——它只在「同一份数据上多次试验的选择偏差」维度有效，**不能替数据信任兜底**，把它和数据门并列成「完整链」夸大了闭合性。(2)「CSCV/CPCV 优于 walk-forward」的关键证据（Arian-Norouzi-Seco）是在**合成受控环境**得出，真实金融数据上 walk-forward 仍是工业标准，**不可外推为普适结论（context_limited）**。DSR 本身作为「多重检验下 Sharpe 去通胀」的表述正确、不降级；降级的是「完整反过拟合链」的闭合性主张。
  https://www.sciencedirect.com/science/article/abs/pii/S0950705124011110

- **【low · 不可直接移植】「Compustat PIT 是机构基本面 PIT 的『事实标准/参照范式』，据此指导 A股/加密侧做法」**——**可移植性被夸大**。Compustat PIT 仅自 **1987 年起、且只覆盖北美**；长样本（1987 前）与 A股、加密均无对等 PIT vendor。当「参照范式」概念上成立，但作为可直接照搬的「事实标准」对本项目资产范围（A股 + crypto）有明显的**时间/地域边界**。

- **【营销数字 · 不可作文案 unattributable】「40% 模型受 skew 影响 / 60% 项目因数据失败 / 某行 5000 万美元损失 / 加密 4x 虚高」**——检索无法定位任何可信一手来源，确属营销数字。研究已自我标注存疑（处置正确），**严禁写进对用户的承诺**；可信量级用 CRSP ~1.6%/年 这类有据（但仍为二手转引）的数字。

**通用陷阱清单（工程红线）：**

- 把后复权价直接喂回测 = 隐性 look-ahead（在「跨越未来 corporate action 的水平价比较」时发生）；但**不是非黑即白**——对仅用「截至当下因子」的口径，后复权未必泄露，把「后复权=泄露」当铁律会误伤大量合规用法（见上 disputed 条）。
- 沿错误时间轴做 as-of join（用 end_date/event_date 而非 known_at/f_ann_date）会用到尚未公布的财报；PIT join 必须沿「第一次可知」轴并叠加披露滞后。
- survivorship：universe 用「当前还活着的标的」构建即错；须保留标的至最后交易日并注入退市收益（A股 ST/退市、加密静默下架两侧对称）。
- training-serving skew：研究端与实盘端用两套特征代码/两套数据路径，offline 好看、online 退化；须共享同一段变换 + offline PIT join。
- 组合收益误用 `w_t·r_t` 即 look-ahead；必须对权重 shift（我们栈已对齐 shift1，作为不可回退红线）。
- 静默坏数据 > 显式报错：可信门必须能拦「静默丢行/隐式过滤/NULL 当 FALSE/empty 不落盘/except 吞错」这类不报错的坏数据。
- 只做 schema 校验、不做时间正确性校验：通用质量门兜不住「复权泄露」「沿错轴 join」，需专门的时点重放测试。
- 前复权也有代价：绝对水平随时间被反复改写、早期价可能极小/失真，不能直接当「当时可成交价」；最干净做法是回测层只见未复权价 + 事件流。

## 8. 开放问题

- **A股 `f_ann_date` 自身的脏数据**：Tushare `f_ann_date` 存在缺失、回溯修订、与实际披露日不一致、修订公告日晚于首次披露日等。光说「用 f_ann_date」并不能保证 PIT 干净——是否需要落库 first-seen 时间戳（真正的 known_at）而非信任 vendor 给的 f_ann_date？
- **A股「披露滞后」的实证校准**：照搬 Compustat 经验值（季报 ~3 月、年报 ~6 月）会引入新偏差。A股 ST/特殊行业/补充更正公告的滞后分布与美股不同，需要对 A股实际披露延迟分布做实证校准，而非套用美股数。
- **bitemporal 必要性分级**：对单用户、A股（到 paper）+ 加密（到实盘）的中低频项目，全库双轴 + 每条特征强制 known_at + 编译期硬门的实现/维护成本巨大。哪些表真需要双轴、哪些只需 as-of 单轴 + 落库时间戳即可？需要做成本/收益分级以避免过度工程。
- **后复权误伤边界**：如何精确界定「后复权确实泄露」（跨越未来 corporate action 的水平价比较）与「后复权合规」（仅用截至当下因子）两类用法，让硬门只拦真泄露、不误伤合规用法？
- **加密 universe「死」的可操作判据**：摒弃 vendor 松散口径后，用什么可审计的事件（交易所下架/流动性枯竭阈值/价格归零）作为加密侧「退场」的客观、可复现定义？
- **SR 11-7 / NIST AI RMF 的真实约束力**：对单用户量化项目，这些是「合规话术借用」而非强制约束。把它当治理骨架时，须明确它对本项目无强制力，避免用机构光环给方案镀金。

## 9. 参考文献（URL）

- ArcticDB（Man Group + Bloomberg）：https://github.com/man-group/ArcticDB
- CRSP Survivor-Bias-Free：https://www.crsp.org/research/crsp-survivor-bias-free-us-mutual-funds/
- CRSP 共同基金 2025-01 更新：https://www.crsp.org/wp-content/uploads/mf_202501.pdf
- Feast 文档：https://docs.feast.dev/ ；Feast 仓库：https://github.com/feast-dev/feast
- Great Expectations：https://greatexpectations.io/
- dbt-expectations：https://github.com/calogica/dbt-expectations
- Soda / SodaCL：https://www.soda.io/
- Monte Carlo（数据可观测性）：https://www.montecarlodata.com/
- XTDB bitemporality：https://v1-docs.xtdb.com/concepts/bitemporality/
- pandas merge_asof：https://pandas.pydata.org/docs/reference/api/pandas.merge_asof.html
- pypbo（PBO/CSCV 实现）：https://github.com/esvhd/pypbo
- Seven Sins of Quantitative Investing（DB, 2014）：https://hudsonthames.org/wp-content/uploads/2022/01/DB-201409-Seven_Sins_of_Quantitative_Investing.pdf
- The Deflated Sharpe Ratio（SSRN 2460551）：https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2460551
- The Probability of Backtest Overfitting（SSRN 2326253）：https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2326253
- Adjusted Prices Without Look-Ahead Bias（Portfolio Optimizer）：https://portfoliooptimizer.io/blog/adjusted-prices-without-look-ahead-bias/
- Dealing with Delistings（Alpha Architect）：https://alphaarchitect.com/dealing-with-delistings-a-critical-aspect-for-stock-selection-research/
- Rules of Machine Learning（Google, Rule #32）：https://developers.google.com/machine-learning/guides/rules-of-ml
- Survivorship and Delisting Bias in Cryptocurrency Markets（U. of St. Gallen）：https://www.alexandria.unisg.ch/bitstreams/2bc8397d-47dd-4f66-8467-9004b2c9d212/download
- CPCV vs walk-forward（Arian-Norouzi-Seco, 合成环境，不可外推）：https://www.sciencedirect.com/science/article/abs/pii/S0950705124011110
- SQL:2011：https://en.wikipedia.org/wiki/SQL:2011
- Bitemporal modeling：https://en.wikipedia.org/wiki/Bitemporal_modeling
- Tushare 财报披露日期表：https://www.tushare.pro/document/2?doc_id=162
- Tushare namechange 接口文档：https://www.tushare.pro/document/2?doc_id=161
- Ataccama Shift-Left Playbook：https://www.ataccama.com/blog/the-shift-left-playbook-data-contracts-data-quality-gates-and-feedback-loops
- SR 11-7（ModelOp 摘要）：https://www.modelop.com/ai-governance/ai-regulations-standards/sr-11-7
