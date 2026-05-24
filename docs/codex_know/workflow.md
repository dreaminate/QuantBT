# Workflow

status: pending_review

review_status: 0

confirmed_by:

confirmed_at:

## Research Flow

1. 定义研究问题和任务卡。
2. 固定数据范围：market、universe、timeframe、data_kind、start/end、数据版本。
3. 生成 FeatureSet，并记录特征代码、窗口和数据依赖。
4. 生成预测、规则信号或模型输出，并映射到 DecisionSnapshot。
5. 选择优化器和风险约束，生成仓位或 no-trade 决策。
6. 运行 perpetual-aware backtest，处理费用、funding、滑点、杠杆和强平距离。
7. 输出 BacktestRun artifact 到 `data/artifacts/experiments/{run_id}/`。
8. 用 Web/Notebook 查看详情、对比、日志、策略代码和报告。
9. 做 ablation、walk-forward、regime-wise evaluation 和失败模式记录。

## Review Gates

| 阶段 | 进入条件 | 阻塞条件 |
|---|---|---|
| rules | harness 文件存在且 metadata 合法 | review_status 不合法 |
| alignment | codex_know 已 review 且无占位符 | open question 阻塞、事实源未确认 |
| implementation | 任务卡和版本快照已 review，Git 仓库存在 | stale、任务未注册、验收矩阵缺失 |
| ci | implementation 同等规则 | 测试或校验失败 |

## Platform Flow

现有平台读取 run artifact 展示结果。新增研究能力应先保证 artifact 可导出，再考虑前端新增页面。
