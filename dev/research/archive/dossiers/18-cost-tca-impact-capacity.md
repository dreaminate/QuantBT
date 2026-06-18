# 18 · 成本 / TCA / 市场冲击 / 容量

> 机构级 Agent OS 成品环节深挖 · 全程 Opus 4.8 · 对抗式核查已降权 · 重心=前沿研究+概念级推荐 · 不含 file:line 代码接线
> 簇 C

## 1. 一句话定位

把"真实成本与容量计提"做成**中低频、资产无关、可审计的计提层**——而不是一个写死参数的滑点函数：**显式费用（佣金/印花税/点差/资金费/借贷）按交易所与监管规则精确计提（确证）**，**隐性成本（市场冲击、容量）一律作为带不确定性区间的模型估计（保守、强制敏感性、永远显示假设来源）**。

## 2. 前沿 SOTA 与代表系统

| 系统 / 框架 | 它是什么 | 对本项目的意义 |
|---|---|---|
| **AQR 实盘成本模型（Frazzini-Israel-Moskowitz 2018）** | 用 1.7 万亿美元真实成交校准的平方根冲击模型，以 %DTV（日成交量占比）为自变量、按市场条件 + 个股特征 + 交易规模分层；在样本外（券商成本、指数基金实现成本）跑赢 TAQ 派生模型。 | "真实成本远低于学术估计"的代表——但**低成本主要源于耐心挂限价单的执行方式**，不可直接用于需要快速建仓的策略（见第 7 节"AQR 陷阱"）。 |
| **CFM / Bouchaud 学派 LLOB 潜在订单簿框架** | 用"局部线性潜在订单簿"(LLOB) 从机理上推导平方根律，量化线性→平方根的交叉，主张冲击主要是机械的（机械性 vs 信息性之争）。 | 当前学术界对冲击机理的 SOTA 理解；是平方根律"为何成立"的理论根。 |
| **Talos 加密市场冲击模型 (TMI)** | 机构级 crypto 执行成本估计：平方根律 + sigmoid 调整指数（按参与率 π），三分量=点差成本 + 物理冲击（参与率、日内波动 σ）+ 时间风险；在 50+ 场所、5 万+ 母单、60 个现货/永续上校准，专门处理 24/7、场所碎片化、极低/极高参与率下平方根失效。 | crypto 侧最贴近本项目（Binance）的工程参考——注意它自己也说**平方根（ϕp=0.5）在中段区间工作良好**，只在 <0.5% 参与率才需 sigmoid 调整。 |
| **Almgren-Chriss 最优执行框架** | 把大单执行建模为随机控制：最小化 U = E[IS] + λ·Var[IS]，分永久冲击与临时冲击，给出风险厌恶下的最优清算轨迹（高风险厌恶→前快后慢）。 | TCA / 执行调度的行业标准基线，常与平方根冲击共用。 |

## 3. 关键论文（每条带 URL）

1. **Trading Costs（Frazzini, Israel, Moskowitz, 2018）** — 1.7 万亿美元真实成交（21 市场 / 9543 股 / 1998–2016）。真实成本比文献"低一个数量级"；关键陷阱：**自家数据原始拟合指数仅约 0.35（log-log R²≈95%），为避免过拟合 + 对齐文献才取整到 0.5**——即便支持平方根的证据，原始 δ 都 < 0.5；低成本高度依赖耐心挂限价单。
   - SSRN 3229719 — https://papers.ssrn.com/sol3/papers.cfm?abstract_id=3229719
   - （注：具体两位小数 6.18/8.63/15.14/16.06/32.34/223.31/0.35 见第 7 节，标为"二手未核实"。可核实二手摘要给"市场冲击平均略低于 9bps、约 85% 为永久、10% 典型成交量约 40bps"——与研究宣称的 32.34bps **不一致**。）
2. **Beyond the Square Root: Evidence for Logarithmic Dependence of Market Impact on Size *and Participation Rate*（Zarinelli, Treccani, Farmer, Lillo, 2014）** — 美股 2007–09 元订单。论证平方根律只在约 2 个数量级上拟合好，对数函数在近 5 个数量级上更优；提出含执行时长 + 参与率的"冲击曲面"。
   - arXiv:1412.2152 — https://arxiv.org/abs/1412.2152
3. **Crossover from Linear to Square-Root Market Impact（Bucci, Benzaquen, Lillo, Bouchaud, 2018）** — 800 万笔机构交易。证明存在"线性→平方根"交叉：小元订单冲击近似线性，平方根只对大订单成立。含义：**对中低频小单照搬 δ=0.5 会高估冲击**。
   - arXiv:1811.05230 — https://arxiv.org/abs/1811.05230
4. **A Million Metaorder Analysis of Market Impact on the Bitcoin（Donier & Bonart, 2015）** — 重建 100 万+ 元订单（MtGox **现货** BTC/USD）。证实平方根律（δ≈0.5）横跨约 4 个数量级成立，整条冲击轨迹（非仅峰值）都服从平方根；Y 前因子可对 BTC 独立标定。
   - arXiv:1412.4503 — https://arxiv.org/abs/1412.4503
   - （注：研究把"BTC/USD 期货 δ≈0.59"挂到此文名下属张冠李戴——本文给的是 0.5，0.59 来自独立的 BTC 期货研究。见第 7 节。）
5. **Optimal Execution of Portfolio Transactions（Almgren & Chriss, 2000）** — 奠基性最优执行：IS 的均值-方差权衡 U = E + λV，分永久/临时冲击，闭式最优轨迹。
   - https://www.smallake.kr/wp-content/uploads/2016/03/optliq.pdf
6. **Continuous Auctions and Insider Trading（Kyle, 1985）** — 提出 Kyle's lambda λ：价格变动对净订单流的敏感度，1/λ 衡量市场深度/流动性；可由价格变动对带符号成交量回归估计。线性冲击与流动性度量的理论根。
   - https://www.jstor.org/stable/1913210
7. **（对抗核查补充）Universality of the square-root impact law（Sato & Kanazawa, 2024）** — 用整个东京证券交易所完整数据论证平方根律的"严格普适性"（单一普适指数横跨全交易所）。**2024 年大规模、近期、直接重申 δ=0.5 普适性**——研究原文未引，导致争议被夸大（见第 7 节）。
   - arXiv:2411.13965 — https://arxiv.org/pdf/2411.13965

## 4. 机构最佳实践 / 标准

- **平方根冲击默认公式** `I(Q) = Y · σ · √(Q / V_daily)`，σ=日波动、V=日成交量、Q=元订单总量、Y 为无量纲前因子。成熟市场（股票/期货）经验 Y 量级为 1（Almgren / Tóth / Bouchaud 学派与多家卖方共用的事实标准）。
  - BSIC 综述 — https://bsic.it/modelling-transaction-costs-and-market-impact/
  - Bouchaud Substack "Square-Root Law" — https://bouchaud.substack.com/p/the-square-root-law-of-market-impact
- **实现缺口（Implementation Shortfall, Perold 1988）** 作为总成本口径，Wagner/Edwards 瀑布分解为：延迟成本 + 交易/冲击成本 + 机会成本（未成交）+ 显式费用（佣金/点差/税）。
  - https://www.pm-research.com/content/iijtrade/1/3/6
- **最佳执行 / TCA 监管化（MiFID II）**：要求"最佳可能结果"（价格 + 成本 + 速度 + 成交概率）；成本分析须作为流程而非单笔最优。（注：RTS 28 年报披露义务自 2024-02 起已取消。）
  - https://www.esma.europa.eu/sites/default/files/library/esma35-43-3088_final_report_review_of_mifid_ii_framework_on_best_execution_reports.pdf
- **模型风险治理（美联储 SR 11-7）**：成本/冲击模型属"模型"，须独立验证（概念健全性 + 结果分析 + 持续监控），做基准对比与敏感性分析；数据不足/方法弱时采用保守假设与安全边际。**直接支持"默认保守 + 强制敏感性"。**
  - https://www.federalreserve.gov/supervisionreg/srletters/sr1107.htm
- **A 股印花税（确证硬数字）**：2023-08-28 起证券交易印花税由卖方 0.1% 减半为 **0.05%（买方免征）**；另有券商佣金、过户费须分项计提。
  - https://english.www.gov.cn/policies/policywatch/202308/28/content_WS64ec5513c6d0868f4e8dee23.html
- **Binance 显式成本（确证硬数字）**：U 本位合约基础 maker 0.02% / taker 0.05%（VIP9、BNB 抵扣再减）；永续资金费每 8 小时结算（**00/08/16 UTC**，时区已核实正确），Funding = Premium Index + clamp(利率 − Premium, ±0.05%)，**BTC/ETH 等默认利率 0.03%/日 = 0.01%/8h**（ETHBTC 等部分合约利率为 0%，非全币种统一——见第 7 节）。
  - https://www.binance.com/en/support/faq/introduction-to-binance-futures-funding-rates-360033525031

## 5. 对 QuantBT 这套架构的推荐方向（概念级）

1. **成本层拆两类并在 UI/对话中显式区分**：
   - 『已确证的显式费用』（A 股印花税 0.05% 卖方 / 佣金 / 过户费、Binance maker-taker、永续 8h 资金费、借贷利率）按交易所/监管规则精确计提，永不当作估计。
   - 『模型化的隐性成本』（市场冲击、容量）一律作为带不确定性区间的估计，默认保守、强制显示来源与假设。
   - 对"流程即信任"是核心——小白看到的每个成本数字都标着『确证』或『估计 + 区间』。
2. **平方根冲击采用标准式** `I(Q) = Y · σ · √(Q / V_ADV)`，把 Y 与指数 δ 都做成『带区间的可标定参数』而非硬编码默认值。**默认 δ=0.5（配窄敏感带），不要宽放到 [0.4,0.7] 制造伪不确定性**（见第 7 节降权）；Y 默认量级为 1 但显著标注为二手默认值。引擎每次出成本数同时给出 δ/Y 区间下的成本带，并把不确定性传播到结论（如"可承载多少 AUM"），而非单点数字。
3. **内置『AQR 陷阱』讲解器**：当 Agent 引用低成本（个位数 bps）时，必须向用户澄清这是『耐心挂限价单的实现成本』口径；而抓 alpha 的中低频策略若需即时建仓，更接近元订单峰值冲击口径，二者可差一个数量级。把 AQR（低）与线性模型（高）作为成本带的下/上界呈现，让经济学者用判断选口径，而非系统替他拍板。
4. **对中低频小单显式处理『线性↔平方根交叉』**：当单笔/日参与率很低时，按 Bucci 交叉模型在小单区退化到近线性（不照搬 δ=0.5 高估）。把『参与率档位』作为一等输入。这与中低频不碰 HFT 的定位天然契合——多数单子落在小参与率区。
5. **容量计提做成『边际 alpha 跌破阈值时的 AUM』曲线（effective capacity）而非单点数字**：输入策略 turnover、可投资 universe 的 ADV 分布、目标 alpha 与冲击模型，输出『AUM vs 净 alpha』曲线与盈亏平衡规模；冲击对 AUM 非线性须在曲线上体现。让用户看到"再加钱到哪一步，成本吃光超额收益"。
6. **纳入 SR 11-7 式模型治理**：每个成本模型有版本、校准数据来源、假设清单、敏感性报告与样本外验证（用回测实现成本 vs 模型预测做 outcome analysis）。Agent 交付前自动生成『成本模型卡』，对数据不足处自动加保守安全边际——把监管级模型验证翻译成小白能读懂的"为什么我相信这个成本数"。
7. **资产相关参数表驱动、与回测/实盘解耦**：A 股（印花税 0.05% 卖方 + 佣金 + 过户费 + 涨跌停/T+1 对成交概率的影响）、Binance（maker-taker + 8h 资金费曲线 + 借贷 + 24/7 无隔夜跳空但有资金费拖累）各自一张可审计参数表，随监管/交易所变更打时间戳版本化（如印花税 2023-08-28 须按日期切换）。**资产无关的是冲击/IS 框架，资产相关的是这些显式成本表。**
8. **把『成本敏感性』变成强制闸**：任何策略进入 paper/实盘前，Agent 必须展示『成本归零的乐观情形 vs 保守冲击情形』两条净值曲线，以及成本占毛 alpha 的比例；若保守情形下净 alpha 转负或容量极小，流程默认拦截并要求用户显式确认，呼应"拒绝半成品交付"的北极星。

## 6. 架构级参考（少量伪代码 / schema 草图，非代码接线）

成本计提层的概念分层（示意，不接线到现有代码）：

```text
CostLayer
├── ExplicitFees   （确证 · 按规则精确计提 · 永不当估计）
│     ├── AShare:   commission + stamp_tax(side=SELL, rate=0.0005, since=2023-08-28)
│     │             + transfer_fee
│     └── Binance:  maker/taker(0.0002/0.0005) + funding(8h, UTC 00/08/16)
│                   + borrow_rate   # 注：资金费对部分策略是 carry 收益而非成本
└── ImpliedCosts   （估计 · 带区间 · 默认保守 · 显示来源）
      └── SquareRootImpact(Q, sigma, V_adv, Y, delta)
```

冲击估计 + 不确定性传播（示意伪代码）：

```python
def impact_bps(Q, sigma_daily, V_adv, *, Y=1.0, delta=0.5):
    eta = Q / V_adv                      # 参与率
    if eta < ETA_CROSSOVER:              # Bucci 交叉：小单退化到近线性
        return Y * sigma_daily * eta * LINEAR_K
    return Y * sigma_daily * (eta ** delta)  # 平方根区

def cost_band(order):
    # δ 默认 0.5，仅配【窄】敏感带，不宽放制造伪不确定性
    lo = impact_bps(..., delta=0.45)
    mid = impact_bps(..., delta=0.50)
    hi = impact_bps(..., delta=0.55)     # crypto 可设 0.59 档
    return Band(lo, mid, hi, source="square-root(Y order-1, 二手默认值)")
```

成本模型卡 schema 草图（SR 11-7 式治理，示意）：

```yaml
cost_model_card:
  model_id: square_root_impact
  version: "2026-06"
  asset_class: [a_share, binance_perp]
  calibration_source: "二手默认 Y~1; 待用回测实现成本本地标定"
  assumptions:
    - "δ=0.5（默认，配窄敏感带 0.45–0.55）"
    - "σ=日波动；V=ADV —— 时间尺度一致性见 open_questions"
    - "永久冲击约占 85%（长持仓不可逆）"
  sensitivity: {delta: [0.45, 0.55], Y: [0.8, 1.2]}
  out_of_sample_validation: "回测实现成本 vs 模型预测 outcome analysis"
  conservatism_margin: "数据不足处自动加保守边际"
  asset_specific_flags:
    a_share: [涨跌停→成交概率<1, T+1, 停复牌]
    binance: [funding_rate_by_symbol(BTC/ETH=0.01%/8h, altcoin/ETHBTC 不统一)]
```

容量曲线（概念，非单点）：

```text
输出 = AUM-vs-净alpha 曲线
横轴 AUM ↑ → turnover×ADV 参与率 ↑ → 冲击非线性 ↑ → 净 alpha ↓
盈亏平衡规模 = 净 alpha 跌破阈值时的 AUM
（须叠加同池拥挤项：多策略 + 跟单中继共享有效 V —— 见第 8 节）
```

## 7. 降权 / 争议 / 陷阱（对抗核查结论）

> 以下原样保留对抗核查的限定词（夸大 / 争议 / 二手未核实 / 张冠李戴 / 伪精确 / 不可外推等）。

- **【medium · 争议被更新证据反超】** 研究称指数 δ≈0.5『被广泛争议/有争议』（以 Zarinelli 2014 对数拟合、Bucci 2018 线性→平方根交叉、AQR 原始 δ=0.35 为据），**框架单边且已过时**。**Sato & Kanazawa 2024（arXiv:2411.13965）用整个东京证券交易所完整数据论证平方根律的"严格普适性"**（单一普适指数横跨全交易所）；2023『double square-root law / 机械起源』(arXiv:2311.18283) 亦支持。Bouchaud 自家 Substack 与 Tóth 综述都说该律"对股票/期货/期权/比特币、跨地域跨时期都成立"；连研究引为反例的 Talos 模型自己也明说平方根(ϕp=0.5)"在中段区间工作良好"、只在 <0.5% 参与率才需 sigmoid 调整——**反而支持 δ=0.5 作为工作默认值**。研究把『需做敏感性区间』(合理工程建议) 与『δ=0.5 学术上有争议』(已被新证据削弱) 混为一谈，**夸大了争议程度**。**落地建议：δ 默认收回到 0.5（配窄敏感带，而非宽放 [0.4,0.7] 制造伪不确定性）。**
- **【medium · 二手未核实 / 伪精确】** AQR 一串两位小数（中位 MI 6.18bps / IS 8.63bps、价值加权均值 15.14/16.06bps、10% DTV 时平方根模型 32.34bps vs 线性 TAQ 模型 223.31bps、原始拟合指数 0.35）**无法独立核实**。可核实的二手摘要只给"市场冲击平均略低于 9bps、约 85% 为永久、10% 典型成交量约 40bps"——其中『约 40bps』与研究宣称的『32.34bps』**不一致（研究偏低）**。SSRN/AQR 原文因 403 无法直读验证；**凡无法溯源到一手表格的两位小数都降级为『未核实的伪精确』，不可作为计提层硬数字直接采信。**
- **【low · 伪精确二手收窄】** 前因子『成熟市场 Y≈0.9~1』：文献只说 Y 是『order 1 / 量级为 1 的齐次化常数』(Bouchaud、Tóth)，**并未给出『0.9~1』这个收窄区间**。研究把模糊的『量级为 1』改写成精确的『0.9~1』，制造了文献并不支持的**伪精确**；研究自己在 pitfalls 里也承认是跨二手综述传抄——**自相矛盾**。
- **【low · 张冠李戴】** 研究把『BTC/USD 期货 δ≈0.59』挂到 Donier & Bonart(2015, arXiv:1412.4503) 名下。后者研究的是 **MtGox 现货** BTC/USD，结论是平方根律 **δ≈0.5**——**他们并没给 0.59**。0.59 来自另一项 BTC/USD **期货**（5 秒重采样）独立研究。两者数据集/口径/指数都不同，**合并陈述构成轻度张冠李戴**。
- **【low · 引用精度瑕疵】** (a) sota_systems 把『LLOB 潜在订单簿框架』指向 arXiv:1811.05230，但该号是 Bucci 等的 crossover 实证论文，**不是 LLOB 理论奠基文**（LLOB 机理出自 Donier-Bonart-Lillo-Bouchaud 2015 等），URL 与所述系统不完全对应。(b) Zarinelli 实际标题含关键的『*and Participation Rate*』，研究略去。**均削弱可审计性，不改结论。**（本文第 3 节已修正标题。）
- **【low · 口径不一致 / 夸大幅度】** 『AQR 真实成本比文献低一个数量级』这一耸动表述**高度依赖与被作者本人当作上界稻草人的线性 TAQ 模型对比（223 vs 32 那条）**；与同口径的平方根模型相比差距远没有"一个数量级"。把对稻草人模型的对比包装成普适的"文献都高估了一个数量级"，**本身就是研究警告读者要防的『二手数字陷阱』**——研究在 summary 顶层却又复述了这个夸张幅度，口径不一致。
- **【low · 部分正确但漏条件】** 永续资金费默认利率『0.03%/日 = 0.01%/8h』**对 BTC/ETH 类正确**（结算 00/08/16 UTC、clamp ±0.05% 均确证，**研究时区正确、未踩 UTC+8 二手误传**，这点要肯定）。但官方明确：**ETHBTC 等部分合约利率为 0%，非 BTC/ETH 标的利率假设并不统一**。把单一默认利率当全币种普适计提，会对一篮子 altcoin 永续算错持仓成本。**落地：资金费按 BTC/ETH vs altcoin 分档。**
- **【陷阱 · 不可外推】误把 AQR 低成本当『冲击律被推翻』**：AQR 测的是耐心挂限价单的实现成本(provide liquidity)，元订单平方根律测的是 demand liquidity 的峰值冲击。**两者口径不同、可差一个数量级，不可互换**；直接用 AQR 数字给需要快速建仓的策略计提会系统性低估成本。
- **【陷阱】忽略永久冲击**：AQR 估永久冲击约占 85%，对长期/高 turnover 策略，永久部分是不可逆的真实成本，只算临时冲击/点差会严重低估对净 alpha 的侵蚀。
- **【陷阱】回测里用固定 bps 滑点而非随 ADV 参与率变化的冲击模型**：大单策略在回测中看似可扩容，实盘冲击非线性放大后**容量被严重高估——容量陷阱**。
- **【陷阱】用全样本数据校准再在同期回测**：违反 SR 11-7 样本外验证原则，制造『回测好、实盘崩』的过拟合。

## 8. 开放问题

1. **A 股微结构对冲击律本身的证伪（研究低估）**：涨跌停(±10%/±20%/ST ±5%)、T+1、停复牌使『可成交量』内生于价格，平方根律（假设连续可成交）在涨停封板/一字板时根本不适用——此时冲击不是 √Q 而是『成交概率→0』的机会成本黑洞。研究在 pitfalls 提了 T+1/涨跌停的 IS 机会成本项，但 design_directions 仍把"资产无关的冲击/IS 框架"当核心。**应把『涨跌停→成交概率』列为一等风险项。**
2. **多策略同池拥挤 / 冲击自相关（研究只字未提）**：本项目是多策略 + 跟单中继，多个策略/用户同时交易同一 universe 时，有效 V 被同侪占用、永久冲击叠加，单策略标定会失效；容量框架若只看单策略 turnover×ADV、不计同池拥挤，会在实盘把合并冲击算少。**与项目自身『跟单中继漂移』风险同源，应被点名。**
3. **尺度一致性拷问**：`I = Y·σ·√(Q/V)` 中 σ 用日波动还是执行时长波动、V 用 ADV 还是执行窗口内成交量，会让同一笔单的冲击估计差数倍。**『时间尺度选择』应列为与 δ/Y 同级的不确定性源**，研究把 σ/V 当确定输入。
4. **成本的方差/尾部（研究只谈均值）**：SR 11-7 式治理不仅要点估计 + 敏感性，更要看实现成本分布尾部（execution shortfall 的最坏 5%）；中低频策略的容量陷阱常发生在波动放大、流动性枯竭的尾部日（冲击与 σ、与 1/V 同时恶化），用均值冲击算容量曲线会系统性低估尾部容量崩塌。
5. **资金费的方向性收益（研究口径偏保守失真）**：永续资金费对持有方向与市场偏向同向时是成本、反向时是收入(carry)；套利/中性策略可能净赚资金费。研究在 pitfalls 把资金费一律写成『主成本』『年化~11% 拖累』，忽略了它对部分策略是 **alpha 来源而非摩擦**。
6. **开源工具落地适用性（研究存在『有现成轮子』的隐性乐观）**：tcapy 自承『侧重 FX 现货』、blotter 是 R、backtrader/zipline 自承默认滑点过简——**没有一个开箱即用支持带 ADV 参与率的平方根冲击 + A 股印花税方向性 + 永续 8h 资金费曲线**；列为"参考实现"却没说明落地到本项目（A 股 + Binance）需几乎全部自建。

## 9. 参考文献（URL）

- Frazzini, Israel & Moskowitz (2018), *Trading Costs*, SSRN 3229719 — https://papers.ssrn.com/sol3/papers.cfm?abstract_id=3229719
- AlphaArchitect 二手摘要（"约 40bps / 约 85% 永久"） — https://alphaarchitect.com/the-best-research-paper-ever-written-on-trading-costs/
- Zarinelli, Treccani, Farmer & Lillo (2014), *Beyond the Square Root…and Participation Rate*, arXiv:1412.2152 — https://arxiv.org/abs/1412.2152
- Bucci, Benzaquen, Lillo & Bouchaud (2018), *Crossover from Linear to Square-Root Market Impact*, arXiv:1811.05230 — https://arxiv.org/abs/1811.05230
- Donier & Bonart (2015), *A Million Metaorder Analysis…Bitcoin*, arXiv:1412.4503 — https://arxiv.org/pdf/1412.4503
- Almgren & Chriss (2000), *Optimal Execution of Portfolio Transactions* — https://www.smallake.kr/wp-content/uploads/2016/03/optliq.pdf
- Kyle (1985), *Continuous Auctions and Insider Trading*, Econometrica — https://www.jstor.org/stable/1913210
- Sato & Kanazawa (2024), *Universality of the square-root impact law*, arXiv:2411.13965 — https://arxiv.org/pdf/2411.13965
- BSIC, *Modelling Transaction Costs and Market Impact* — https://bsic.it/modelling-transaction-costs-and-market-impact/
- Bouchaud Substack, *The Square-Root Law of Market Impact* — https://bouchaud.substack.com/p/the-square-root-law-of-market-impact
- Talos, *Understanding Market Impact in Crypto Trading (TMI)* — https://www.talos.com/insights/understanding-market-impact-in-crypto-trading-the-talos-model-for-estimating-execution-costs
- Perold (1988) / Expanded IS — https://www.pm-research.com/content/iijtrade/1/3/6
- ESMA, MiFID II Best Execution review — https://www.esma.europa.eu/sites/default/files/library/esma35-43-3088_final_report_review_of_mifid_ii_framework_on_best_execution_reports.pdf
- Federal Reserve SR 11-7, *Model Risk Management* — https://www.federalreserve.gov/supervisionreg/srletters/sr1107.htm
- 中国 gov.cn 印花税公告（2023-08-28） — https://english.www.gov.cn/policies/policywatch/202308/28/content_WS64ec5513c6d0868f4e8dee23.html
- Binance Futures Funding Rates FAQ — https://www.binance.com/en/support/faq/introduction-to-binance-futures-funding-rates-360033525031
- tcapy (cuemacro) — https://github.com/cuemacro/tcapy
- braverock/blotter — https://github.com/braverock/blotter
- Backtrader — https://github.com/mementum/backtrader
- CoinGlass 资金费数据 — https://www.coinglass.com/FundingRate
