# Architecture Decisions

status: pending_review

review_status: 0

confirmed_by:

confirmed_at:

## ADR-0001: File Artifact First

当前平台已有文件驱动的 run artifact 协议。第一阶段新增研究能力优先输出到 `data/artifacts/experiments/{run_id}/`，让现有 Web/Notebook 能直接读取。

## ADR-0002: Backend Research Core Before UI Expansion

先实现数据、特征、模型输出接口、优化器、风控、回测和导出，再扩展前端页面。前端不能倒逼未稳定的数据模型。

## ADR-0003: Crypto Perpetual Constraints Are First-Class

加密永续合约研究默认必须考虑 funding、open interest、basis、fees、slippage、leverage、liquidation distance。无法实现时必须在任务中写明 N/A 原因。

## ADR-0004: Standard Decision Interface

模型输出需要映射到标准决策接口，优化器只消费该接口或任务卡声明的扩展字段，避免模型和仓位逻辑耦合。
