# Quant Research Harness

状态：confirmed

review_status: 1

confirmed_by: user

confirmed_at: 2026-05-11

本文定义 Codex 参与本量化研究平台开发时的规则、事实源、任务拆分、验收和防漂移约束。平台业务事实写入 `docs/codex_know/`，具体开发任务写入 `docs/tasks/`，已有接口和结果协议文档仍保留在 `docs/` 根目录。

## 1. 工具分层

| 工具/目录 | 角色 | 记录内容 | 禁止内容 |
|---|---|---|---|
| `docs/codex_rules/` | Codex 开发规则 | 工具边界、流程、冲突处理、分阶段校验 | 具体策略有效性结论 |
| `docs/codex_know/` | 已对齐事实源 | 平台定位、术语、研究流程、领域模型、架构决策 | 未验证交易想法 |
| `docs/tasks/` | 执行入口 | 单个任务卡、接口、依赖、验收标准、允许改动范围 | 长篇聊天记录 |
| `docs/tasks/index.md` | 任务总账 | 任务ID、版本、状态、依赖版本、stale、review 状态 | 任务细节全文 |
| `docs/templates/` | 文档模板 | 任务卡、变更单、规则变更、研究实验、开放问题模板 | 项目事实结论 |
| `docs/codex_rules/changes/` | 规则变更记录 | 规则修改原因、影响范围、review 状态 | 业务任务变更 |
| `docs/codex_rules/scripts/validate_harness.py` | 本地校验器 | review 状态、任务总账、任务目录、验收矩阵检查 | 自动修改文件 |
| `app/backend/` | 后端服务 | API、数据拉取、研究/回测/导出模块 | 未经任务卡确认的实验性改写 |
| `app/frontend/` | 前端服务 | 回测列表、对比、数据中心、详情页 | 先于后端契约的功能扩张 |
| `data/` | 本地数据与实验产物 | 行情数据、回测结果、研究导出 artifact | 手工改写的绩效结论 |
| Git | 版本记录 | diff、提交、回滚点 | 业务原因的完整解释 |

## 2. 基础约定

1. 平台目标是量化研究从数据到实验归档的端到端研究基座，必须能支持 A 股、港股、美股和 Crypto；任何单一市场只能作为适配场景，不能把平台基座锁死到该市场。
2. 后端和研究契约先行：先稳定数据协议、特征协议、模型输出接口、优化器接口、风险约束、回测产物，再做前端增强。
3. 事实源优先级：`review_status: 1` 的 `docs/codex_know` > `review_status: 1` 的当前任务卡 > 现有代码 > 聊天上下文。
4. 没有已确认任务卡，不进入代码实现；没有验收标准，不声明任务完成。
5. Codex 可以创建和更新草案；进入 `docs/codex_know/` 的最终事实必须经过人工 review。
6. `review_status = 0` 表示未 review，`review_status = 1` 表示已 review。Codex 默认只能写 0；只有用户明确说明已 review，Codex 才能代改为 1。
7. `status: pending_review` 时 `review_status` 必须为 0；`review_status: 1` 必须同时填写 `confirmed_by` 和 `confirmed_at`。
8. 当前任务相关 `open_questions` 未关闭时，禁止进入实现。
9. 进入代码实现前必须确认工作区是 Git 仓库；未初始化 Git 时，只允许写文档草案、任务草案和 harness 工具。
10. 每个研究能力必须明确所属层级：data、feature、model、signal、optimizer、risk、backtest、artifact、api、ui。

## 3. 量化研究防漂移规则

| 规则 | 内容 |
|---|---|
| 预测和优化分离 | 预测层只输出概率、收益、波动、尾部风险、置信度或情景；优化层才输出仓位、杠杆、暴露、是否交易 |
| 信号和风控分离 | 信号允许建议交易，风控拥有否决权；任何风控绕过都必须写入任务卡并 review |
| 特征不可神化 | 技术指标、Fibonacci、Gann 只能作为可编码 feature、filter 或 support/resistance candidate；不得作为默认有效结论 |
| 数据版本可追溯 | 每个实验必须记录 market、symbol universe、timeframe、data_kind、时间范围、数据版本或文件快照 |
| 模型输出标准化 | 新模型必须映射到标准决策接口，或在任务卡说明为何保留模型私有输出 |
| 优化器假设显式化 | CVaR、risk budgeting、Kelly、robust optimization、MPC 等必须记录目标函数、输入、约束、失败模式 |
| 多层风险 | 任务必须说明 trade-level loss、daily drawdown、portfolio risk、leverage、liquidation distance 是否 required 或 N/A |
| 回测现实性 | 手续费、资金费率、滑点、成交约束、杠杆和强平距离必须被显式处理或写明 N/A 原因 |
| 不以后验收益替代验收 | 验收优先检查协议、可复现性、边界条件、稳健性；收益表现只能作为研究指标，不能单独作为通过标准 |
| 小团队可维护性 | 4x5090 算力可用但不是默认复杂化理由；第一代系统优先规则/统计/轻模型/清晰优化器 |

## 4. 调用流程

1. 读取规则：先读 `docs/codex_rules/README.md`。
2. 读取事实：读 `docs/codex_know/` 中与当前任务相关的文件。
3. 读取总账：读 `docs/tasks/index.md`，确认当前任务版本、状态、依赖、stale 和 review 状态。
4. 读取任务：读 `docs/tasks/TASK-xxxx/TASK.md` 与最新 `versions/v*.md`；没有任务卡则先生成任务卡草案。
5. 阻塞检查：open question、stale、版本不一致或 review_status 为 0 时停止等待确认。
6. 契约先行：先写数据/特征/模型/优化/风控/回测接口和验收标准，再实现。
7. 后端实现：只改任务卡允许的文件范围。
8. 验收执行：运行任务卡中的验收命令，记录结果。
9. 结果归档：研究或回测输出必须写入现有 `data/artifacts/experiments/{run_id}/` 协议，或在任务中定义新 artifact 协议。
10. Git 检查：查看 diff，确认无无关改动；只有收到明确指令才 commit。

## 5. 任务拆分规则

TASK = 一个可独立验收的研究平台能力单元。任务粒度必须能清楚描述输入、输出、接口、状态变化和验收命令。

| 能力层 | 典型任务 |
|---|---|
| data | A 股/港股/美股/Crypto 数据拉取、目录索引、数据质量检查 |
| feature | OHLCV、基本面/财务、资金费率、open interest、basis、技术指标、Fibonacci/Gann 编码 |
| model | regime、ranking、probability forecast、volatility forecast、scenario generation |
| signal | 标准决策接口、择币、择时、置信度融合 |
| optimizer | risk budgeting、CVaR、fractional Kelly、robust optimization、MPC |
| risk | 单笔亏损、日内回撤、组合尾部风险、杠杆/保证金、强平距离或市场适用的风险口径、kill-switch |
| backtest | 股票/合约/永续等市场适配撮合、费用、资金费率、滑点、walk-forward、ablation |
| artifact | `run.json`、`portfolio.csv`、`trades.csv`、`positions.csv`、报告和日志导出 |
| api/ui | 查询、对比、数据中心、实验详情展示 |

任务目录结构：

```text
docs/tasks/TASK-000i/
  TASK.md
  versions/
    v1.md
  changes/
  assets/
    v1/
  acceptance/
```

任务卡必填字段：`id`、`version`、`status`、`review_status`、`depends_on`、`layer`、`inputs`、`outputs`、`interfaces`、`acceptance_matrix`、`allowed_files`、`confirmed_by`、`confirmed_at`。

## 6. 任务版本、变更和 stale

| 规则项 | 处理规则 |
|---|---|
| 任务版本 | `TASK-0001 v1/v2`；已 review 的版本不可原地改写 |
| 高重合变更 | 必须在旧任务上生成新版本和变更单，禁止新建任务逃避历史 |
| stale 依赖 | 上游任务接口、数据协议、验收标准变化后，下游任务写入 `stale_by` |
| 重验规则 | 先重验变更任务，再重验 stale 任务 |
| 例外规则 | 不改变输入、输出、接口、状态、验收、依赖的错字/格式修正可记录为 note |

## 7. 验收矩阵规则

每个任务必须覆盖以下验收项，状态只能是 `required` 或 `N/A + 原因`。

| 项 | 说明 |
|---|---|
| 文档一致性 | harness、codex_know、任务卡、现有 docs 是否一致 |
| 数据契约 | 数据源、目录、schema、时间范围、数据质量检查 |
| 研究接口 | feature/model/signal/optimizer/risk/backtest 接口是否清晰 |
| 风控约束 | 多层风控是否实现、显式 N/A 或有测试 |
| 回测现实性 | 费用、资金费率、滑点、杠杆、强平风险是否处理 |
| Artifact 导出 | 是否能写入或读取平台 artifact 协议 |
| API/UI | 仅在涉及前后端时 required |
| 回归测试 | pytest、构建或脚本验证 |

## 8. 校验阶段

| 阶段 | 命令 | 作用 |
|---|---|---|
| rules | `python docs/codex_rules/scripts/validate_harness.py --stage rules` | 校验 harness 基础结构、review metadata、模板、任务总账 |
| alignment | `python docs/codex_rules/scripts/validate_harness.py --stage alignment` | 校验规则和知识文件已 review、无占位符、开放问题不阻塞 |
| implementation | `python docs/codex_rules/scripts/validate_harness.py --stage implementation --task TASK-000i` | 校验 Git、任务注册、当前版本快照、验收矩阵、依赖和 stale |
| ci | `python docs/codex_rules/scripts/validate_harness.py --stage ci --task TASK-000i` | CI 阶段使用，规则同 implementation |

当前 `rules` 阶段通过只代表 harness 基础结构正确，不代表可以进入业务实现。

## 9. 开工前必须具备的文件

| 文件 | 目的 | 状态 |
|---|---|---|
| `docs/codex_rules/README.md` | Codex 开发规则 | 已 review |
| `docs/codex_rules/changes/` | 规则变更记录 | 已 review |
| `docs/codex_rules/scripts/validate_harness.py` | 本地 harness 校验器 | 已 review |
| `docs/templates/` | harness 文档模板 | 已创建，待 review |
| `docs/tasks/index.md` | 任务总账 | 已创建，待 review |
| `docs/codex_know/project_alignment.md` | 平台定位、阶段目标、禁止偏离项 | 已创建，待 review |
| `docs/codex_know/glossary.md` | 术语定义 | 已创建，待 review |
| `docs/codex_know/domain_model.md` | 核心对象和关系 | 已创建，待 review |
| `docs/codex_know/workflow.md` | 研究流程 | 已创建，待 review |
| `docs/codex_know/task_contract.md` | 任务卡字段标准 | 已创建，待 review |
| `docs/codex_know/acceptance_rules.md` | 验收规则格式 | 已创建，待 review |
| `docs/codex_know/architecture_decisions.md` | 工程决策记录 | 已创建，待 review |
| `docs/codex_know/open_questions.md` | 未确认问题 | 已创建，待 review |
| Git 仓库 | 代码版本记录 | 当前未初始化 |
