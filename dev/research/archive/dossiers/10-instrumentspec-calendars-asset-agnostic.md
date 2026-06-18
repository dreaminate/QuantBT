# 10 · 资产无关声明式接入（InstrumentSpec/交易日历/合约规格）

> 机构级 Agent OS 成品环节深挖 · 全程 Opus 4.8 · 对抗式核查已降权 · 重心=前沿研究+概念级推荐 · 不含 file:line 代码接线
> 簇 B

## 1. 一句话定位

把"资产是什么"从代码里的 `if market == 'crypto'` 分支，彻底改写成一份**可版本化、可校验、可被 Agent 读取的声明式数据契约（InstrumentSpec）**——身份只押在我们自己铸造一次、永不复用的内部 ID 上，所有外部符号（ticker / FIGI / ISIN / 交易所挂牌号 / CCXT 统一符号）都退化为带生效期的"可选 enrichment 辐条"，交易日历/会话/最小变动价位/手数/合约乘数/结算币种/线性-反向/到期-永续资金费/续约策略全部变成"可声明的字段"，并从第一天就内建双时态（valid-time + knowledge-time），让 A股现货与 Binance 永续在同一引擎下做到"流程即信任"的资源无关正确性。这正是"让非技术用户靠描述就能加一个资产"的真正护城河——**声明式本身就是壁垒**。

---

## 2. 前沿 SOTA 与代表系统

| 系统 | 它强在哪 | 对 QuantBT 的可迁移点 |
|---|---|---|
| **QuantConnect LEAN — Symbol / SecurityIdentifier (SID)** | 最强的开源"声明式不可变身份"参考。SID 把 market + 证券类型 + ticker + 到期 + 行权价 + 期权风格/方向编码进一个紧凑、自包含、**无需数据库查询**的不可变哈希，资产整个生命周期内恒定；可变的时点 ticker 存放在独立的 `Value` 字段，ticker 变更通过 `mapping_resolve_date` 解析（如 ATHN→HLGN，2021-12-31）；期权/期货用 `SID|underlyingSID` 复合哈希。 | "把资产指纹化以致不需要查表"这一范式；持久 SID 与可变时点 ticker 的分离正是我们要复刻的 InstrumentId/display-ticker 切分。URL: https://www.quantconnect.com/docs/v2/writing-algorithms/key-concepts/security-identifiers |
| **CCXT — 统一市场结构 & 符号语法** | 横跨 100+ 加密交易所、久经实战的资源无关合约模型。字段：id/symbol/base/quote/settle(+Id)/type/spot/margin/swap/future/option/active/contract/linear/inverse/taker/maker/contractSize/expiry/expiryDatetime/strike/optionType/precision/limits/info。确定性的统一符号语法（现货 `BASE/QUOTE`、永续 `BASE/QUOTE:SETTLE`、定期期货 `BASE/QUOTE:SETTLE-YYMMDD`），显式建模线性 vs 反向、contractSize、结算币种。 | 直接用于统一 A股现货与 Binance 永续的合约规格字段。**注意**：CCXT 统一符号本身跨版本不稳定（见 §7），可作为 enrichment 辐条但不应作为内部主键。URL: https://github.com/ccxt/ccxt/blob/master/doc/manual.rst |
| **exchange_calendars（gerrymanoim，quantopian/trading_calendars 的维护继任者）** | 事实标准的 Python 交易日历库，开箱 50+ 交易所，社区 PR 维护，只建模常规会话（盘前/盘后/集合竞价=休市）、午休、半日市；v4 起 session 改为时区朴素（tz-naive）。原 quantopian/trading_calendars 已无人维护——重要的来源沿革事实。 | 权益侧日历的事实来源；加密建模为 24/7。配合 exchange_calendars_extensions 取额外会话元数据。**但** A股（XSHG/XSHE）的未来年度准确性/更新时效不保证，需配陈旧检测（见 §7）。URL: https://github.com/gerrymanoim/exchange_calendars |
| **CRSP PERMNO** | 学术金标准：永久、永不重用的证券身份，跨越 ticker 变更、并购、退市；是做"无幸存者偏差、可时点重建"研究的前提。 | 验证核心论点：拥有内部永久 ID、保留退市标的、永不回收 ID。URL: https://www.crsp.org/seeing-through-the-fog-of-market-history/ |
| **OpenFIGI 映射 API（Bloomberg，OMG/ANSI-X9 标准）** | 免费公开 API，把 ticker/CUSIP/ISIN→FIGI（交易所/复合/股份类三级），加密 FIGI 与 Kaiko 合作发行（2024 年约 8,000 个资产）。 | 作为**可选的跨厂商对账/enrichment 辐条**，而非主身份。URL: https://www.openfigi.com/ |

> 编辑判断说明：把 LEAN SID 称作"最强/最规范"的开源参考，是可辩护的编辑判断而非可证伪的事实——PERMNO、Intrinio hub-and-spoke、OpenFIGI 三级层级在各自的层面同样规范（此点已在 §7 按"低"严重度降权）。

---

## 3. 关键论文（每条带 URL）

1. **Financial Data Engineering Series (3/n): Financial Identifiers — Tamer Khraisha**
   定义健全标的标识符的六大属性（uniqueness / permanence / immutability / completeness / accessibility / authenticity）；论证 ticker 依赖交易所/国家、必须用交易所限定；铺陈 FIGI 三级层级（交易所 / 复合-国家 / 股份类-全球），并对比不可变的 ISIN 与"可变"的 CFI——核心设计规则是：分类绝不能进入身份。
   *注：Medium 系列，非同行评审、作者立场带行业色彩（见 §7）。*
   URL: https://tamer-khraisha.medium.com/financial-data-engineering-series-3-n-financial-identifiers-99a32a6eb321

2. **Continuous Futures Contracts Methodology for Backtesting — Vojtko & Padysak（SSRN 3517736）**
   原始期货合约的拼接会注入人工跳空、表现为假的 P&L；加法（Panama）后向调整引入漂移、可变负、破坏百分比收益；**后向比例（ratio）调整是推荐默认**，因为保留百分比表现。这是任何合成连续序列的告诫模板（A股现货与永续都不需要，但规定了 OS 该如何对待"连续性"）。
   *注：SSRN 工作论文，出自商业策略厂商 Quantpedia，非同行评审（见 §7）。*
   URL: https://papers.ssrn.com/sol3/papers.cfm?abstract_id=3517736

3. **Modern Security Master Architecture: Unifying Ticker, CUSIP, ISIN and FIGI at Scale — Intrinio**
   具体的 hub-and-spoke 范式：生成你自己的内部主键；所有外部 ID 通过交叉引用表映射到它；记录每次标识符变更的**生效日期**而非覆写（从而任意历史符号体系可重建）；存储带每记录来源/入库时间/转换血缘的版本化快照。
   *注：厂商工程博客，立场带利益相关性（见 §7）。*
   URL: https://intrinio.com/blog/modern-security-master-architecture-unifying-ticker-cusip-isin-and-figi-data-at-scale

4. **Using point-in-time data to avoid bias in backtesting — Refinitiv / LSEG**
   前视偏差源于使用历史上当时并不可得的信息（报告滞后、数据修订、追溯性的指数/标识符变更）；解法是把**所有**参考数据——包括标识符映射与挂牌状态——都按 as-of 查询，对符号体系而言意味着一个双时态的映射存储。
   *注：厂商/数据商博客（见 §7）。*
   URL: https://perspectives.refinitiv.com/future-of-investing-trading/how-to-use-point-in-time-data-to-avoid-bias-in-backtesting/

5. **The Identifier Challenge / FIGI vs ISIN 之争 — OpenFIGI, FinOps, WatersTechnology, IOSCO filings**
   记录了真实、未决的治理之争：FIGI 经 ANSI/ASC X9 获认证为美国标准（2021）且是带免费 API 的 OMG 开放标准，对阵 ANNA 的 ISO 6166 ISIN（EU/ESMA 背书）及 DSB 发行的 ISIN+ISO 4914 UPI（用于 OTC 衍生品）。FIGI 的核心批评是"Bloomberg 是注册机构"的治理问题，而非 schema 缺陷。诚实含义：身份不要押在任何一个外部方案上。
   URL: https://www.openfigi.com/insights/all/2017/10/2/the-identifier-challenge-attributes-of-mi-fid-ii-that-cannot-be-ignored

---

## 4. 机构最佳实践 / 标准

1. **Hub-and-spoke 证券主数据**：铸造一个内部不可变主键；把每个外部标识符（ticker / FIGI / ISIN / CUSIP / 交易所挂牌号）以**生效/失效日期**映射到它，而非覆写——任意历史日期的符号体系都可重建。
   来源：Intrinio — Modern Security Master Architecture。URL: https://intrinio.com/blog/modern-security-master-architecture-unifying-ticker-cusip-isin-and-figi-data-at-scale

2. **永久、永不复用的发行标识符**，跨越 ticker 变更、并购、退市，且退市标的永久保留——这是无幸存者偏差时点研究的前提。
   来源：CRSP PERMNO。URL: https://www.crsp.org/seeing-through-the-fog-of-market-history/

3. **把分类码（CFI / ISO 10962）当作描述性、可变的属性**——显式**不**纳入身份；OTC 衍生品用 UPI（ISO 4914），发行实体用 LEI（ISO 17442），各作为独立参考维度。
   来源：ISO 10962 / ISO 4914 / ISO 17442（GLEIF）。URL: https://www.iso.org/standard/81140.html

4. **数据血缘与输入数据控制作为模型风险要求**：输入参考数据必须准确、完整、源到产出可追溯，每条记录携带来源 + 入库时间 + 转换；开发/验证/治理三支柱。
   *注：vocabulary "data lineage / source-to-output traceability" 是现代 MRM/厂商在 SR 11-7 之上叠加的解读，非 2011 指引原文逐字表述；实质（输入数据须准确/完整/恰当且来源有据）确在 SR 11-7（见 §7）。*
   来源：Federal Reserve / OCC SR 11-7 Model Risk Management。URL: https://www.federalreserve.gov/supervisionreg/srletters/sr1107.htm

5. **用维护中的、社区策划的交易日历库**而非手搓节假日；只建模常规会话、午休、半日市，并对照官方通知核对半日/早闭市/临时停牌；加密建模为 24/7/365、无规范收盘。
   来源：exchange_calendars 项目 + 市场时段指引。URL: https://github.com/gerrymanoim/exchange_calendars

6. **声明并持久化连续序列构造（续约日期 + 调整方法）**，默认后向比例调整以保留百分比收益；绝不硬拼接合约。
   来源：Vojtko & Padysak, SSRN；QuantPedia。URL: https://quantpedia.com/continuous-futures-contracts-methodology-for-backtesting/

---

## 5. 对 QuantBT 这套架构的推荐方向（概念级）

> 仅给概念级方向，不点 file:line、不排实施计划。

1. **身份独立成不可变、厂商中立的内核**：一个内部 `InstrumentId`，铸造一次、永不复用，与可变的展示 ticker 严格分离——对标 LEAN 的 SID/Value 切分与 CRSP 的 PERMNO。所有外部 ID（ticker / FIGI / ISIN / 交易所挂牌号 / CCXT 统一符号）都是**可选、带生效期的 enrichment 辐条**，绝不作主键。这让我们彻底置身于 FIGI-vs-ISIN 之争之外。

2. **InstrumentSpec 即数据而非代码**：每个资源无关属性——资产类别、场所、日历/会话画像、最小变动价位、手数/一手股数、乘数/contractSize、结算币种、报价约定、线性-vs-反向、到期-vs-永续资金费、续约策略——都成为一个声明的、版本化的、可校验字段。引擎读 spec；它绝不能在 `if market == 'crypto'` 上分支。这是"非技术用户靠描述加资产"的字面使能器。**务实边界（见 §7 漏点）**：T+1 vs 24/7 结算、涨跌停停牌、资金费计提等是**行为性**而非纯参数性差异，把 100% 推进数据是非平凡工程；建议先界定"最小可用身份/日历/spec 层"，再谈完整机构理想，避免镀金。

3. **采用类 FIGI 的分层身份层级**（instrument vs 场所挂牌 vs 股份类），让同一经济资产在多场所交易、或 A股双重挂牌、或多交易所永续，干净地解析而不重复身份——也让公司行动挂在正确的层级上。**YAGNI 提醒**：单用户、仅 A股现货 + Binance 永续的锁定范围下，完整 FIGI 层级/股份类身份/OTC UPI-LEI 维度多为投机性未来证明；建议保留接口、当下最小化。

4. **第一天就把双时态烤进 registry**：每个映射、挂牌状态、spec 字段都携带 valid-time + knowledge-time，所有 Agent/回测查询默认 as-of。这是"流程即信任"成真的结构性手段——从结构上杜绝符号体系前视偏差与幸存者偏差，并兼作 SR 11-7 式的数据血缘。**成本现实（见 §7 漏点）**：双时态存储索引/查询成本高、as-of-everything 默认会拖慢热回测路径，需配快照/缓存/读放大权衡，而非天真全程 as-of。

5. **日历/会话建模为可插拔的、按资产类别声明的画像**：A股 倚靠 exchange_calendars（常规会话 + 午休 + 半日市，对照官方通知校验）、Binance 用独立的 24/7 画像并带永续资金费区间语义。绝不假设单一全球会话。**补强**：增设"陈旧日历检测/告警"作为一等控制——当打包日历与现实（State Council 临时假期、台风/临时停牌）漂移时能侦测。

6. **定义声明式连接器契约（schema-as-code / data-contract 风格）**：每个数据源声明它供给哪些 spec 字段、其原生符号体系、到内部 ID 的映射规则、校验/质量约束。加一个源 = 注册一份 Agent 可校验的契约，而非写定制 adapter 代码——这是反厂商锁定与"Agent 出全部工程"的杠杆。

7. **退市/到期标的永久留在 registry，状态作为时态属性**（永不删除、永不回收 ID），任意历史日期的 universe 可重建——幸存者偏差的结构性解药。

8. **任何合成连续/聚合序列都作为一等声明工件**（续约日期 + 方法，默认后向比例调整），构造被记录以保可复现——即便 A股现货与 Binance 永续当下都不需要后向调整，也为日后接定期期货留门、避免重新引入拼接/漂移偏差。

9. **公司行动 / 身份断裂规则需显式补齐（来自 §7 漏点）**：hub-and-spoke + 双时态是必要但不充分。拆股、并购、分拆、ticker 互换，以及 A股特有事件（ST/*ST 前缀、配股/送股、更名）会迫使"一个 InstrumentId 何时终结、另一个何时诞生"以及"价格复权因子如何挂接"的决策。建议显式声明"铸造新 ID vs 沿用旧 ID 穿过公司行动"的操作规则（参照 LEAN 的 mapping_resolve_date 与 CRSP 的 PERMNO/PERMCO 切分）。

10. **加密身份要单独对待（来自 §7 漏点）**：加密无发行实体/LEI、无 ISIN，同一经济"BTC"以数百个场所专属合约存在（不同结算/保证金/contractSize）；代币迁移/再计价/改名无中央 registry；CCXT 统一符号跨版本不稳定。**因此把内部 ID 绑到 CCXT 统一符号会重新引入它本要规避的厂商-版本锁定**——加密侧应以我们自己的内部 ID 为锚，CCXT 符号仅作辐条。

---

## 6. 架构级参考（少量伪代码 / schema 草图，非代码接线）

> 仅示意，不接线到现有代码。

### 6.1 身份内核与辐条（hub-and-spoke + 双时态）

```text
InstrumentId            # 内部铸造，一次，永不复用，永不删除；不含任何可变属性
  └── 仅承载身份内核（资产类别、场所、证券类型、铸造时间戳）

IdentifierSpoke (cross-ref, 双时态)
  instrument_id         # FK -> InstrumentId
  scheme                # ticker | figi | isin | cusip | exchange_listing_id | ccxt_symbol
  value                 # 如 "600519" | "BTC/USDT:USDT" | "BBG000..." 
  valid_from, valid_to  # valid-time（业务上何时生效）
  known_from, known_to  # knowledge-time（我们何时知道/记录）
  source                # 供给方
# 任意历史日期 as-of 解析：where valid_from<=d<valid_to and known_from<=k<known_to
```

### 6.2 InstrumentSpec 数据契约草图（一份 A股、一份 Binance 永续）

```yaml
# --- A股 现货示例 ---
instrument_id: QBT-0000001            # 内部不可变
asset_class: equity_spot
venue: XSHG
calendar_profile: XSHG                # exchange_calendars 键；常规会话+午休+半日市
session_model: regular_with_lunch
settlement: T+1                        # 行为性差异，需引擎语义支持（非纯参数）
price_limit: { type: pct, up: 0.10, down: 0.10 }   # 涨跌停（部分行为性）
tick_size: 0.01
board_lot: 100                         # 一手
multiplier: 1
quote_currency: CNY
settle_currency: CNY
status: { value: active, as_of: <bitemporal> }

# --- Binance 永续示例 ---
instrument_id: QBT-0000777
asset_class: crypto_perp
venue: BINANCE
calendar_profile: 24x7                 # 独立画像，无规范收盘
session_model: continuous
linear_or_inverse: linear              # USDT 本位；反向(币本位)PnL 数学不同
expiry: null                           # 永续无到期
funding: { interval_hours: 8 }         # 以资金费替代续约
contract_size: 1
tick_size: 0.10
quote_currency: USDT
settle_currency: USDT
ccxt_symbol_spoke: "BTC/USDT:USDT"     # 仅辐条，非主键（跨 CCXT 版本可能漂移）
status: { value: active, as_of: <bitemporal> }
```

### 6.3 连接器契约（schema-as-code，加一个源 = 注册一份契约）

```yaml
connector: tushare
native_symbology: { scheme: ts_code, example: "600519.SH" }
supplies_fields: [tick_size, board_lot, status, calendar_profile_hint]
mapping_rule: ts_code -> exchange_listing_id spoke -> InstrumentId
validation:
  - tick_size > 0
  - board_lot in {100, 200}
  - status in {active, delisted, suspended}
quality_constraints: { max_ingest_lag: 1d, require_source_timestamp: true }
```

### 6.4 连续序列（保留接口，默认后向比例）

```text
SyntheticContinuousSeries           # 一等声明工件（A股/永续当下不用，留门）
  roll_dates: [...]                 # 必须声明、持久化，绝不硬编码
  adjustment_method: backward_ratio # 默认；保留百分比收益（Vojtko & Padysak）
  construction_recorded: true       # 可复现
```

---

## 7. 降权 / 争议 / 陷阱（对抗核查结论）

> 以下**原样保留**对抗核查的限定词（夸大/争议/二手/不可外推/撤稿等）。

### 7.1 须修正（不只是软化）的两条

- **CFI（ISO 10962）"explicitly MUTABLE 显式可变"——【disputed - overstated；表述被夸大】**：ISO 10962 标准的实际立场恰恰相反，强调 CFI 码"normally will NOT change during the life of the instrument 通常在工具生命周期内不会改变"，反映发行时固定的特征；只有在特定公司行动下（如股东大会改变投票权/所有权限制）才可变。把它叫作"显式可变"**inverts the standard's framing 反转了标准的措辞**——正确表述是"原则上不可变、例外才可变（immutable in principle, mutable by exception）"。设计结论（CFI 不进主键）仍然成立，但支撑前提被夸大。严重度：低。来源：https://en.wikipedia.org/wiki/ISO_10962

- **"A股 6 位代码退市后被复用"作为 A股 特殊风险——【disputed - largely backwards；很大程度上是反的】**：按 SSE/SZSE/BSE 代码分配规则，A股 6 位代码"原则上不与已上市/已退市证券重复（in principle not duplicated）"，退市公司被移到**独立的三板编号区间**（如 欣泰电气 300372 → 400067），而非把 300372 回收给新发行人。所以 A股 代码比美股 ticker **更不易**被回收。一般陷阱（绝不在 ticker 上建键；ticker 因改名/重组、ST/*ST 前缀、ATHN→HLGN 而变）有效且来源充分，但这个具体的"A股 回收"例子**misleading 误导**，应删除或软化为"ticker 语义会变（ST/*ST、重组），且代码可能跨场所碰撞（codes CAN collide cross-venue）"。严重度：中。来源：https://www.bocichina.com/（北交所/全国中小企业股份转让系统 证券代码、证券简称编制指引）

### 7.2 低严重度降权（措辞/归属层面）

- **"SR 11-7 demands 'data lineage'（demands by name）"——【低；slightly anachronistic gloss 轻度时代错置的归属】**：2011 Fed/OCC SR 11-7 原文强调 "data quality" 与开发性证据；"data lineage"、"traceable source-to-output" 是现代 MRM/厂商在其上叠加的词汇，**非指引逐字表述（not verbatim from the guidance）**。实质（输入数据须准确/完整/恰当、来源有据）确在 SR 11-7，故属 framing/归属 nuance 而非事实错误——但把"data lineage"说成 SR 11-7 "demands by name" overstates the letter of the guidance 夸大了指引字面。

- **幸存者偏差 ~1.6%/yr（CRSP）——【低；已在原发现的 DISPUTED 段正确加注；dataset/period-specific 不可外推】**：1.6%/yr 只是宽广文献区间（约 0.9%–6%/yr，依数据集/周期/资产类别）中的一个估计，**must be used as motivation only, never as a calibration constant 只能作动机、绝不可当校准常数**。因 caveat 已在场且诚实，严重度低。来源：https://alphaarchitect.com/dealing-with-delistings-a-critical-aspect-for-stock-selection-research/

- **"连续期货：Binance 永续不需要（perps never expire）"——【低；scope note 范围限定】**：对 Binance **永续（PERPETUAL）**合约为真（无到期、约 8h 资金费），但 Binance 也挂**季度交割（DELIVERY）期货**（季度末最后周五到期），若交易则需续约。该断言**correct only as scoped to perps 仅在限定于永续时成立**；设计方向 #8 已为定期期货留门，但"Binance perps"易被误读为"Binance 衍生品"，宜收紧为"specifically Binance perps, not Binance quarterly delivery contracts 特指永续、非季度交割"。来源：https://www.binance.com/en-TR/support/faq/...d2a1afd5f829455c9ded23f0ca561a40

- **LEAN SID 是"strongest/canonical 最强/最规范"的开源参考——【低；superlative is opinion 此为意见而非可证伪事实】**：关于 LEAN SID 的每条事实子断言均逐字验证通过（DB-free 指纹哈希编码 market/type/expiry/strike/option-right、持久 SID vs 可变 Value 时点 ticker、mapping_resolve_date、ATHN→HLGN on 2021-12-31）。唯一软点是"最强/最规范"这个最高级——属可辩护的编辑判断而非可证伪事实（PERMNO、Intrinio hub-and-spoke、OpenFIGI 层级在各自层面同样规范）。因底层技术断言准确、最高级明属意见，严重度低。

### 7.3 漏点（asserted-away 被一笔带过，非错误而是遗漏）

- **公司行动 / 身份断裂处理 underspecified（规定不足）**：hub-and-spoke + 双时态是必要但不充分。拆股/并购/分拆/ticker 互换、A股 特有事件（ST/*ST、配股/送股、更名）迫使"一个 InstrumentId 何时终结、另一个何时诞生"与"复权因子如何挂接"的决策。发现提到药方（永不回收、保留退市）却**未给穿过公司行动时铸造 vs 沿用 ID 的操作规则**（LEAN 的 mapping_resolve_date 与 CRSP 的 PERMNO/PERMCO 切分正为此而生）。

- **加密身份本质上比所倚靠的权益模型更乱（fundamentally messier）**：无发行实体/LEI、无 ISIN，同一"BTC"以数百个场所专属合约存在（不同 settle/margin/contractSize）；代币迁移/再计价/改名无中央 registry；**CCXT "unified" 符号本身跨 CCXT 版本不稳定**（Binance/Deribit 符号约定有记录在案的破坏性变更）。把内部 ID 绑到 CCXT 统一符号**reintroduces exactly the vendor-version-lock-in the finding warns against 恰好重新引入发现本要警告的厂商-版本锁定**。此张力未被处理。

- **exchange_calendars 正确性/新鲜度作为运营风险被 glossed（一笔带过）**：发现背书其为"de facto standard"，但未标注 A股 日历依赖不定期公布的 PRC 假期（State Council 通知）、台风/临时停牌，且库对 A股（XSHG/XSHE）**未来年度**的准确性与更新时延不保证。发现自己的陷阱说"对照官方通知校验"却**未给打包日历偏离现实时的检测/告警机制**——对一个标榜"流程即信任"的系统，"陈旧日历检测/告警"是缺失的一等关切。

- **"声明式 spec 即护城河"论点是 asserted, not evidenced（断言而非举证）**："非技术用户靠描述加资产"是 aspiration 愿景；全无一份最小 InstrumentSpec 的 A股/Binance 永续工作示例（本 dossier §6.2 已补一份），也未承认 spec 表面（日历画像、tick/lot/board-lot、涨跌停、T+1、资金费区间、线性/反向、precision/limits）大到使校验与默认逻辑本身就是 substantial engineering 可观工程。"引擎绝不 `if market==crypto` 分支"是 ideal 理想；实务上某些资产类别行为（T+1 vs 24/7 结算、涨跌停停牌、资金费计提）是**behavioral, not just parametric 行为性而非纯参数性**，把 100% 推进数据 non-trivial 非平凡。

- **完整双时态的性能/规模与 as-of 查询成本被 ignored（忽略）**："每个映射/挂牌状态/spec 字段都带 valid-time+knowledge-time、所有查询默认 as-of"对正确性是对的，但有真实代价：双时态存储 notoriously hard to index/query efficiently 出名地难以高效索引/查询，as-of-everything 默认会拖慢热回测路径。**无 caching/snapshotting/读放大权衡的讨论**。

- **未与更简单/更省的替代或 YAGNI 线对话（no engagement with the YAGNI line）**：对单用户、仅 A股现货 + Binance 永续的锁定范围，完整 FIGI 层级/股份类身份/连续期货续约机制/OTC UPI-LEI 维度 largely speculative future-proofing 多为投机性未来证明。发现确实标了"永续/A股 不需要连续期货"，但**未划线区分当下真正需要的最小可用层 vs 镀金（gold-plating）**——对抗读者会要求把"最小可用身份/日历/spec 层"与"完整机构理想"分开点名。

- **多数所引"机构实践"来源为厂商博客/Medium 系列，非独立/同行评审（softer evidentiary base 证据基础更软）**：Intrinio、OpenFIGI、Refinitiv/LSEG、Khraisha 的 Medium 帖均 competent but interested or non-peer-reviewed 有能力但利益相关或非同行评审；唯一带学术色彩的引用（Vojtko & Padysak）是商业策略厂商 Quantpedia 的 SSRN 工作论文，**非同行评审**。hub-and-spoke 共识真实存在，但证据基础比"institutional consensus is unambiguous 机构共识毫不含糊"所暗示的更软。

### 7.4 核查结论（verdict 摘录）

> Mostly solid and unusually honest 大体扎实、对一份"研究发现"而言异常诚实——核心论点（拥有内部不可变 ID；把所有外部 ID 与整份 instrument spec 当版本化声明数据；烤进双时态；绝不在 (symbol,market) 上建键）正确，且每条受检的承重技术断言逐字验证通过：LEAN SID/Value + mapping_resolve_date + ATHN→HLGN、FIGI 三级 + IBM-12-FIGIs、FIGI ANSI X9.145-2021（2021-09-15）、PERMNO 永不复用、exchange_calendars 继承 + v4 tz-naive、CCXT 符号语法、Vojtko-Padysak 后向比例、Kaiko ~8,000 加密 FIGIs、ESMA-ISIN/DSB-UPI、Binance 永续无到期 + 资金费。FIGI-vs-ISIN 段落 notably balanced 明显平衡，且对其最弱的数字（1.6%/yr 幸存者偏差）已预先加注。两条须修正（非仅软化）：(1) CFI 被错误刻画为"显式可变"，而标准说它 normally does NOT change——结论存活但前提被反转；(2)"A股 6 位代码退市后被复用"largely backwards——A股 代码原则上不回收、退市发行人移至独立三板区间，故该具体例子 undercuts rather than supports（削弱而非支撑）那条（本身有效的）"绝不在 ticker 上建键"规则。除此之外，主要弱点是 omission, not error 遗漏而非错误：硬运营部分（公司行动身份断裂、加密的无 registry / CCXT 版本不稳身份、陈旧日历检测、双时态查询成本、以及把最小可用层与完整机构镀金分开的 YAGNI 线）是 asserted-away 被断言带过而非真正 engaged。争议严重度 low-to-medium；无撤稿；CFI 与 A股 措辞修正后，设计方向 as written 仍可行动。

---

## 8. 开放问题

1. **公司行动的身份断裂边界**：何种事件触发"铸造新 InstrumentId"而非"沿用旧 ID"？（A股 更名/ST、并购、分拆；加密代币迁移/改链/再计价）复权因子在哪个层级（instrument vs 挂牌）挂接？
2. **加密身份锚定**：内部 ID 如何在无 LEI/ISIN/中央 registry 且 CCXT 符号跨版本漂移的现实下保持稳定？辐条用哪些字段做交叉对账才不重新引入厂商-版本锁定？
3. **陈旧日历检测机制**：如何侦测打包 exchange_calendars 与 PRC 现实（State Council 临时假期、台风/临时停牌）的漂移并告警？校验源是什么、时效要求多少？
4. **双时态性能权衡**：哪些查询路径必须严格 as-of、哪些可走快照/缓存？热回测路径的读放大如何控制？
5. **行为性 vs 参数性差异的边界**：T+1 结算、涨跌停停牌、资金费计提这些行为，多少能被声明为数据、多少必须留在引擎语义里？"绝不 `if market==crypto`"的理想在哪里务实让步？
6. **最小可用层 vs 镀金的 YAGNI 线**：单用户 + A股现货 + Binance 永续范围内，FIGI 层级/股份类身份/连续期货机制/UPI-LEI 维度——哪些当下必做、哪些仅留接口？
7. **外部标识符校验规则**：FIGI/CUSIP/ISIN/SEDOL 的 check-digit/格式校验（可参考 figir）作为声明式 ingest 规则的覆盖面与失败处置策略？

---

## 9. 参考文献（URL）

**SOTA 系统 / 工具**
- QuantConnect LEAN — Security Identifiers（文档）: https://www.quantconnect.com/docs/v2/writing-algorithms/key-concepts/security-identifiers
- QuantConnect/Lean — Common/SecurityIdentifier.cs: https://github.com/QuantConnect/Lean/blob/master/Common/SecurityIdentifier.cs
- CCXT — Manual（统一市场结构 & 符号语法）: https://github.com/ccxt/ccxt/blob/master/doc/manual.rst
- CCXT 仓库: https://github.com/ccxt/ccxt
- exchange_calendars（gerrymanoim）: https://github.com/gerrymanoim/exchange_calendars
- CRSP — Seeing Through the Fog of Market History（PERMNO）: https://www.crsp.org/seeing-through-the-fog-of-market-history/
- OpenFIGI（映射 API）: https://www.openfigi.com/
- OpenFIGI API: https://www.openfigi.com/api
- figir (R) — FIGI/CUSIP/ISIN/SEDOL 校验: https://cran.r-project.org/web/packages/figir/figir.pdf
- GLEIF LEI（ISO 17442）开放数据: https://www.gleif.org/en/lei-data/access-and-use-lei-data

**关键论文 / 文章**
- Khraisha — Financial Identifiers（Medium，非同行评审）: https://tamer-khraisha.medium.com/financial-data-engineering-series-3-n-financial-identifiers-99a32a6eb321
- Vojtko & Padysak — Continuous Futures Contracts Methodology（SSRN 3517736，非同行评审）: https://papers.ssrn.com/sol3/papers.cfm?abstract_id=3517736
- QuantPedia — Continuous Futures Contracts Methodology: https://quantpedia.com/continuous-futures-contracts-methodology-for-backtesting/
- Intrinio — Modern Security Master Architecture（厂商博客）: https://intrinio.com/blog/modern-security-master-architecture-unifying-ticker-cusip-isin-and-figi-data-at-scale
- Refinitiv / LSEG — Point-in-time data to avoid bias（厂商博客）: https://perspectives.refinitiv.com/future-of-investing-trading/how-to-use-point-in-time-data-to-avoid-bias-in-backtesting/
- OpenFIGI — The Identifier Challenge: https://www.openfigi.com/insights/all/2017/10/2/the-identifier-challenge-attributes-of-mi-fid-ii-that-cannot-be-ignored

**标准 / 监管 / 治理**
- SR 11-7 Model Risk Management（Federal Reserve）: https://www.federalreserve.gov/supervisionreg/srletters/sr1107.htm
- ISO 10962（CFI）/ ISO 4914（UPI）/ ISO 17442（LEI）: https://www.iso.org/standard/81140.html
- FIGI ANSI/ASC X9.145-2021 公告（X9）: https://x9.org/asc-x9-publishes-u-s-standard-for-the-financial-instrument-global-identifier/
- FIGI 分配规则（OpenFIGI，三级层级）: https://www.openfigi.com/assets/local/figi-allocation-rules.pdf
- ESMA — OTC 衍生品标识符回应（ISIN/DSB-UPI）: https://www.esma.europa.eu/sites/default/files/2024-01/ESMA12-766636679-105_Response_to_EC_consultation_OTC_derivative_identifier.pdf

**对抗核查 / 降权引用**
- ISO 10962（CFI 通常不改变 — Wikipedia 摘要）: https://en.wikipedia.org/wiki/ISO_10962
- A股 证券代码编制指引（北交所/全国股转，代码原则上不重复、退市移至三板区间）: https://www.bocichina.com/file/infoAttach/20240905/
- 幸存者/退市偏差量级（区间，不可外推 — Alpha Architect）: https://alphaarchitect.com/dealing-with-delistings-a-critical-aspect-for-stock-selection-research/
- Binance 永续 vs 季度交割（永续无到期 + 资金费）: https://www.binance.com/en-TR/support/faq/what-are-perpetual-futures-and-quarterly-futures-d2a1afd5f829455c9ded23f0ca561a40
- CRSP PERMNO（研究页）: https://www.crsp.org/research/permno/
- exchange_calendars v4 tz-naive（讨论）: https://github.com/gerrymanoim/exchange_calendars/discussions/202
- CCXT 统一符号语法（issue 10931）: https://github.com/ccxt/ccxt/issues/10931
- Kaiko × Bloomberg 加密 FIGI 覆盖（~8,000 资产）: https://www.kaiko.com/news/kaiko-and-bloomberg-announce-expanded-financial-instrument-global-identifier-coverage-for-crypto-assets
