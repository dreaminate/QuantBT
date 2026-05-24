# Acceptance Rules

status: pending_review

review_status: 0

confirmed_by:

confirmed_at:

## Required Acceptance Items

| 项 | required 条件 | 可 N/A 条件 |
|---|---|---|
| 文档一致性 | 所有任务都 required | 不可 N/A |
| 数据契约 | 任务涉及数据读取、拉取、schema 或 artifact | 纯文档/纯 UI 且不改数据 |
| 研究接口 | 任务涉及 feature/model/signal/optimizer/risk/backtest | 纯展示或纯文档 |
| 风控约束 | 任务影响交易决策、仓位、杠杆、回测 | 纯数据目录或纯 UI |
| 回测现实性 | 任务涉及策略评估或 backtest | 不涉及历史绩效评估 |
| Artifact 导出 | 任务生成或读取实验结果 | 纯数据拉取或纯文档 |
| API/UI | 任务涉及后端 API 或前端页面 | 纯内部模块 |
| 回归测试 | 代码任务都 required | 纯文档草案可 N/A |

## Pass Criteria

- required 项必须写具体命令。
- N/A 必须给原因。
- 不能只用收益率、Sharpe 或单次样例图作为通过标准。
- 涉及 crypto perpetual 的回测必须说明 fees、funding、slippage、leverage、liquidation distance。
