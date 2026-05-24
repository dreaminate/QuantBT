# Project Alignment

status: pending_review

review_status: 0

confirmed_by:

confirmed_at:

## Platform Goal

本项目目标是搭建个人/小团队可维护的量化研究平台，覆盖数据拉取、数据质量检查、特征工程、模型输出、信号生成、优化决策、风控约束、回测、实验归档和结果分析。

## Current Baseline

- 已有 `qb` 本地 App：回测列表、对比分析、数据中心、回测详情。
- 后端使用 FastAPI，前端使用 React/Vite。
- 回测 artifact 目前以文件协议驱动：`run.json`、`portfolio.csv`、`trades.csv`、`positions.csv`、`report.md`、`strategy.py`、`backtest.log`。
- 数据层已有 Tushare 与 Binance USDM/Vision 拉取雏形。
- 当前还没有统一 feature store、model output interface、optimizer layer、risk engine、walk-forward 实验治理。

## First Build Direction

第一阶段优先打造 market-agnostic 量化研究基座，不能锁定某一个具体市场。基座必须能覆盖：

- A 股：日频、分钟频、指数/行业/财务数据、T+1、涨跌停、停复牌、交易成本。
- 港股：日频、分钟频、交易日历、币种、印花税/交易费、港股通或普通港股差异。
- 美股：日频、分钟频、复权、退市/幸存者偏差、盘前盘后、公司行动。
- Crypto：spot/perpetual，1h/4h/1d 等多周期，funding、open interest、basis、杠杆和强平风险。

第一条实现主线应先抽象共同基座：MarketDataset、FeatureSet、DecisionSnapshot、OptimizerRun、RiskDecision、BacktestRun、ArtifactExport。具体市场适配器作为插件或配置进入基座。

## Non Goals

- 不先做全自动交易执行。
- 不把单次回测收益当作任务完成标准。
- 不把技术指标、Fibonacci、Gann 作为未经验证的确定性规律。
- 不在没有任务卡和 review 的情况下扩张前端功能。
- 不为使用 4x5090 而过早引入不可维护的深度模型体系。
- 不把 crypto perpetual 的 funding/强平/杠杆约束硬编码成所有市场都必须具备的字段；股票市场不适用字段必须能 N/A 并给出原因。

## Drift Guards

- 新能力必须落在 data、feature、model、signal、optimizer、risk、backtest、artifact、api、ui 中的一个或多个明确层级。
- 每个实验必须说明数据版本、特征版本、模型输出、优化器假设、风控约束、回测现实性和 artifact 导出。
- 预测、信号、优化、风控、执行必须解耦，禁止混在一个不可测试函数里。
