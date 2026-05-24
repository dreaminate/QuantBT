# 量化研究平台调研

status: draft

review_status: 0

collected_at: 2026-05-11

## Scope

本文收集主流量化研究平台、开源回测框架和交易执行框架的公开官方资料，目标是为本项目的“量化研究基座”提供参考。重点不是复刻某个平台的页面，而是抽象出专业平台共同具备的能力边界：

- 数据接入、数据集版本、证券主数据、交易日历和市场适配。
- 研究环境、Notebook、策略编辑、参数化实验和批量扫描。
- 策略 API、生命周期函数、事件驱动或向量化执行模式。
- 回测撮合、费用、滑点、成交约束、风控、组合和风险模型。
- 实验归档、绩效报告、参数扫描、对比、仿真和实盘桥接。

## Survey Matrix

| 平台/框架 | 类型 | 覆盖重点 | 公开资料里体现的架构形态 | 对本项目的借鉴 |
|---|---|---|---|---|
| JoinQuant / 聚宽 | 云端研究与回测平台 | A 股等股票研究、策略、回测、模拟 | `initialize` / `handle_data` / 调度函数、`get_price` / `history` 数据 API、手续费和复权等回测选项 | 借鉴易用的研究 API、策略生命周期、回测配置和 artifact 详情页体验 |
| RiceQuant / RQAlpha | 平台 + 开源框架 | 股票、期货、多证券回测与模拟 | RQAlpha 从数据、算法交易、回测、模拟、实盘到分析；通过 Mod Hook 扩展账户、分析器、风控、撮合和交易费用 | 借鉴可扩展插件边界，尤其是账户、风险、撮合、分析器拆分 |
| 掘金量化 / MyQuant | 终端 + SDK + 交易平台 | A 股、期货、ETF、可转债、期权、模拟和实盘 | 本地/终端策略开发，Jupyter 研究，回测绩效、仿真、实盘、监控、风控、组合交易 | 借鉴“研究-回测-仿真-实盘监控”完整链路，但本项目近期不进入真实实盘 |
| BigQuant | AI 量化平台 | AI 策略、数据、因子、模型、回测 | 策略开发空间、AI 策略、BigTrader 回测引擎、因子/模型/回测组合 | 借鉴 feature/model/backtest 管线和 AI 策略工作流，但先定义接口，避免先堆模型 |
| FMZ Quant | 多交易所量化交易平台 | Crypto、期货、跨交易所、机器人 | 支持多交易所、Python/C++/JavaScript、Docker/托管、回测、模拟交易所、市场 API 和交易 API | 借鉴交易所适配层和 Crypto 特殊约束，不让 Crypto 污染股票市场通用契约 |
| QuantConnect / LEAN | 云端 + 开源多资产平台 | 多资产、研究、回测、优化、实盘 | Algorithm Framework：Universe Selection -> Alpha -> Portfolio Construction -> Risk Management -> Execution；LEAN 可本地运行 | 最适合作为模块边界参考：Universe、Alpha、Portfolio、Risk、Execution 分层清晰 |
| QuantRocket | 本地 Docker + Jupyter 研究平台 | 美股/IBKR/数据采集/研究/回测/实盘 | JupyterLab 为主要 UI，建议将数据采集和实盘部署与研究回测部署分离；Moonshot 支持回测和参数扫描 | 借鉴本地优先、Jupyter 优先、研究部署与实盘部署隔离 |
| Microsoft Qlib | AI-oriented 研究框架 | 数据层、特征、模型、记录器、回测 | 数据准备、Data API、Data Loader、Data Handler、Dataset、Cache；配置化 workflow 和 PortAnaRecord | 借鉴数据层与实验记录层，适合未来 ML 因子/排序模型 |
| Backtrader | 开源事件驱动框架 | 回测、live feed、策略、broker、analyzer | `Cerebro` 汇聚 Data Feeds、Strategies、Observers、Analyzers、Writers、Broker，并驱动事件循环 | 借鉴最小可运行事件驱动引擎结构和 analyzer/report 插件 |
| VectorBT | 向量化研究框架 | 大规模参数扫描、信号矩阵、组合回测 | 基于 Pandas/NumPy/Numba 的向量化 backtest，可快速扫大量参数和资产 | 借鉴 research batch / parameter sweep，不替代事件驱动撮合 |
| Zipline Reloaded | 开源事件驱动框架 | Algorithm API、数据 bundle、pipeline | `run_algorithm` 接收 start/end、initialize、handle_data、capital_base、bundle；bundle 包含价格、复权和资产数据库 | 借鉴数据 bundle、交易日历、可复现实验输入 |
| vn.py / VeighNa | 开源交易系统 | 国内期货/股票/期权 gateway、CTA、回测、实盘 | 交易 Gateway、CTA 策略、回测引擎、参数优化、生命周期管理 | 借鉴执行侧网关和本地交易系统分层，近期只保留接口预留 |

## Common Architecture Pattern

成熟量化平台通常不是单个“回测函数”，而是下面这条可审计链路：

```text
Data Source / Broker / Exchange
  -> MarketAdapter
  -> Security Master / Calendar / Corporate Actions
  -> MarketDataset / Data Bundle / Cache
  -> Research Workspace / Notebook / Strategy Editor
  -> FeatureSet / Factor / Label / Prediction
  -> Signal / Alpha / Insight
  -> Portfolio Construction / Optimizer
  -> Risk Management / Pre-trade Checks
  -> Backtest Simulator / Matching / Cost / Slippage
  -> Experiment Artifact / Metrics / Report / Compare
  -> Paper Trading / Live Execution Bridge
```

本项目当前已有 `data/artifacts/experiments/{run_id}/` 和 JoinQuant 风格的回测详情页。因此下一步不应先改前端，而应让后端和研究层输出更标准的 artifact，使现有详情页成为研究结果的稳定观察窗口。

## Platform Lessons

### 1. 聚宽的核心不是页面，而是“低摩擦研究 API”

聚宽文档显示，策略通过生命周期函数和数据 API 组合运行，回测时选择股票池、时间、初始资金、调仓频率等配置；`get_price`、`history` 等函数负责屏蔽数据细节。对本项目来说，聚宽风格应转化为：

- `MarketDataset` 屏蔽 A/H/US/Crypto 的数据源差异。
- `StrategyContext` 或 `ResearchContext` 屏蔽账户、时间、持仓、费用、市场规则。
- 研究者面向统一 API 写策略，但底层由 market adapter 决定交易日历、复权、停牌、T+1、涨跌停、funding、杠杆和强平规则。

### 2. QuantConnect/LEAN 的模块边界最适合做基座参考

LEAN Algorithm Framework 将策略拆成 Universe Selection、Alpha、Portfolio Construction、Risk Management、Execution。这个分层可以映射到本项目：

| LEAN 概念 | 本项目候选概念 |
|---|---|
| Universe Selection | Universe / MarketDataset / SymbolFilter |
| Alpha / Insight | Signal / DecisionSnapshot |
| Portfolio Construction | OptimizerRun / PortfolioTarget |
| Risk Management | RiskDecision / RiskRuleSet |
| Execution | BacktestExecution / PaperExecution / LiveExecution |

这套分层的关键价值是：预测不直接等于仓位，仓位不直接等于下单，风控有独立否决权。

### 3. 专业平台都把数据层独立出来

RQAlpha、Qlib、Zipline、QuantRocket 都把数据作为独立层处理。区别只是实现方式：

- RQAlpha 通过 RQData 和 Mod 扩展接数据、账户、风控和分析器。
- Qlib 将 Data API、Data Loader、Data Handler、Dataset、Cache 拆成明确层级。
- Zipline 使用 data bundle 承载价格、复权和资产数据库。
- QuantRocket 强调本地数据采集、Jupyter 研究和部署隔离。

本项目必须先建立 `MarketAdapter` 和 `MarketDataset` 契约，再谈模型和优化器。否则 A 股停牌/复权/T+1、美股公司行动/盘前盘后、港股交易日历/CNH/HKD、Crypto 资金费率/24x7/杠杆会混在策略代码里。

### 4. 回测引擎需要同时支持事件驱动和批量研究

事件驱动适合真实撮合、订单生命周期、风控、逐 bar 逻辑；向量化适合快速扫参数、因子和组合假设。

- Backtrader、Zipline、RQAlpha 更偏事件驱动。
- VectorBT 更偏向量化矩阵研究。
- Qlib 更偏 ML workflow 和配置化实验。

本项目基座应同时保留两条路径：

```text
ResearchBatch: MarketDataset -> FeatureSet -> VectorizedBacktest -> Artifact
EventBacktest: MarketDataset -> StrategyContext -> BrokerSimulator -> Artifact
```

两条路径都必须输出兼容现有 run artifact 的结果，方便同一个详情页和对比页查看。

### 5. 风控和现实撮合是平台质量分水岭

公开资料里成熟平台都会显式处理手续费、滑点、成交时点、撮合方式、账户、持仓和风险。对本项目来说，第一版 risk/backtest 约束矩阵至少要覆盖：

| 约束 | A 股 | 港股 | 美股 | Crypto |
|---|---|---|---|---|
| 交易日历 | required | required | required | 24x7 required |
| 复权/公司行动 | required | required | required | N/A 或交易所事件 |
| 停牌/缺失 bar | required | required | required | required |
| T+1 / 卖出限制 | required | market-specific | N/A | N/A |
| 涨跌停 | required | N/A 或 market-specific | N/A | N/A |
| 手续费/印花税/交易费 | required | required | required | required |
| 滑点/冲击成本 | required | required | required | required |
| 融资融券/保证金 | optional/market-specific | optional | optional | required for futures/perp |
| funding rate | N/A | N/A | N/A | required for perpetual |
| liquidation distance | N/A | N/A | N/A | required when leveraged |

## Recommended Base Design For This Repo

TASK-0001 不应写成某个市场的策略任务，而应落成第一版“研究基座契约”。建议核心对象如下：

| 对象 | 职责 |
|---|---|
| `MarketAdapter` | 封装市场规则、交易日历、合约/证券标识、费用、复权、撮合限制 |
| `MarketDataset` | 可复现数据切片，记录 market、universe、interval、data_kind、start/end、version |
| `Instrument` | 统一证券/合约主数据，兼容股票、ETF、期货、期权、Crypto spot/perp |
| `FeatureSet` | 特征定义、输入数据版本、窗口、代码引用和输出 schema |
| `PredictionSet` | 模型或规则预测输出，不能直接代表仓位 |
| `DecisionSnapshot` | 标准信号接口，承载 expected_return、probability、volatility、tail_risk、confidence、regime |
| `PortfolioTarget` | 优化器输出的目标仓位/暴露 |
| `RiskDecision` | 风控层是否放行、降杠杆、拒单或触发 kill-switch |
| `BacktestEngine` | 事件驱动或批量研究回测入口 |
| `BacktestAssumptionSet` | 手续费、滑点、成交、资金费率、杠杆、强平等假设 |
| `ExperimentArtifact` | 对现有 `run.json`、`portfolio.csv`、`trades.csv`、`positions.csv`、`report.md` 的扩展 |

## Near-Term Task Impact

1. 保持现有 JoinQuant 风格前端和回测详情页不动。
2. 将本调研作为 TASK-0001 的参考输入，而不是直接替代已 review 规则。
3. 更新 `docs/codex_know/domain_model.md` 时，应把对象分为：数据层、研究层、决策层、优化层、风控层、回测层、artifact 层。
4. TASK-0001 的验收重点应是契约完整性：A/H/US/Crypto 都能表达，且每个市场的特殊字段能 required 或 N/A。
5. 代码实现应在 review 后从 `app/backend/app/research/` 开始，先做 schema/dataclass 和 artifact 扩展，不先做复杂模型。

## Sources

- JoinQuant Guide: https://www.joinquant.com/guide
- JoinQuant API PDF: https://cdn.joinquant.com/help/img/JoinQuantAPI.pdf
- RiceQuant 回测文档: https://rqopen.ricequant.com/doc/quant/backtest.html
- RQAlpha GitHub: https://github.com/ricequant/rqalpha
- 掘金量化新手指引: https://www.myquant.cn/docs/guide/guide
- BigQuant 文档: https://bigquant.com/doc/
- BigQuant 回测模块: https://bigquant.com/wiki/topic/8a799dd96d
- FMZ Quant: https://www.mathquant.com/
- FMZ API Docs: https://fmz-docs.readthedocs.io/en/latest/
- QuantConnect Algorithm Framework: https://www.quantconnect.com/docs/v2/writing-algorithms/algorithm-framework/overview
- QuantConnect Algorithm Engine: https://www.quantconnect.com/docs/v2/writing-algorithms/key-concepts/algorithm-engine
- QuantRocket Docs: https://www.quantrocket.com/docs/
- Qlib Docs: https://qlib.readthedocs.io/
- Backtrader Cerebro: https://www.backtrader.com/docu/cerebro/
- VectorBT Docs: https://vectorbt.dev/
- Zipline Reloaded API: https://zipline.ml4trading.io/api-reference.html
- Zipline Data Bundles: https://zipline.ml4trading.io/bundles.html
- vn.py Documentation: https://www.vnpy.com/docs/cn/community/app/cta_strategy.html
