# Glossary

status: pending_review

review_status: 0

confirmed_by:

confirmed_at:

| 术语 | 定义 | 边界 |
|---|---|---|
| data layer | 负责拉取、存储、索引和预览行情/衍生数据 | 不负责产生交易建议 |
| feature layer | 把原始数据转换成可复现特征 | 不直接输出仓位 |
| predictive layer | 模型或统计方法输出收益、概率、波动、尾部风险、情景或 regime | 不直接下仓位 |
| signal layer | 把模型输出和规则过滤组合成候选交易意图 | 可建议 long/short/no-trade，但不越过风控 |
| optimizer layer | 在约束下决定仓位、杠杆、组合暴露或风险预算 | 依赖预测/风险输入，不制造原始预测 |
| risk layer | 负责单笔、日内、组合、杠杆、强平和 kill-switch 约束 | 对信号和优化器有否决权 |
| backtest layer | 复现历史交易过程和费用/资金费率/滑点/杠杆假设 | 不篡改输入数据 |
| artifact | 可被平台读取的实验输出文件 | 必须可追溯到实验配置 |
| decision interface | 模型/信号到优化器之间的标准输出对象 | 不要求所有模型内部结构一致 |
| crypto perpetual | 加密永续合约 | 必须考虑 funding、leverage、liquidation distance |
| timing | 入场、减仓、退出、加仓时机判断 | 不等于组合分配 |
| coin selection | 分层币池中的候选标的筛选和排序 | 不等于最终仓位 |
| CVaR | 条件在险价值，用于尾部风险约束或优化目标 | 对样本和情景质量敏感 |
| fractional Kelly | Kelly 仓位的保守缩放 | 输入胜率/赔率不稳定时必须限幅 |
| risk budgeting | 按风险贡献分配仓位 | 需要可靠波动和相关性估计 |
