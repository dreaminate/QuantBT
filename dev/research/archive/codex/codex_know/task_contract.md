# Task Contract

status: pending_review

review_status: 0

confirmed_by:

confirmed_at:

## Required Fields

| 字段 | 说明 |
|---|---|
| id | `TASK-0001` 格式 |
| version | `v1` 格式 |
| status | draft、confirmed、in_progress、done |
| review_status | 0 或 1 |
| depends_on | 依赖任务版本，如 `TASK-0001@v1` |
| layer | data、feature、model、signal、optimizer、risk、backtest、artifact、api、ui |
| inputs | 数据、配置、上游接口 |
| outputs | artifact、API、模型输出、优化结果 |
| interfaces | Python、HTTP、文件协议或 UI 契约 |
| allowed_files | 本任务允许修改的路径 |
| acceptance_matrix | 分项验收命令和通过标准 |
| confirmed_by | review 人 |
| confirmed_at | review 日期 |

## Implementation Rule

任务未 review 前只能写草案。任务进入代码实现前，`TASK.md`、当前 `versions/v*.md` 和相关知识文件必须为 `review_status: 1`。
