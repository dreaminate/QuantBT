# TASK-0000

status: pending_review

review_status: 0

confirmed_by:

confirmed_at:

id: TASK-0000
version: v1
depends_on:
layer:

## Scope

说明本任务覆盖的单一能力单元。

## Inputs

列出数据、配置、上游接口、用户输入。

## Outputs

列出输出 artifact、API response、模型输出、优化结果或文档。

## Interfaces

列出 Python 函数、HTTP API、文件协议或前端契约。

## State Changes

说明是否改变任务状态、实验状态、数据目录、run artifact。

## Acceptance Matrix

| 项 | 状态 | 命令 | 通过标准 |
|---|---|---|---|
| 文档一致性 | required | python docs/codex_rules/scripts/validate_harness.py --stage rules | harness 基础结构通过 |
| 数据契约 | N/A + 原因 | 无 | 说明原因 |
| 研究接口 | N/A + 原因 | 无 | 说明原因 |
| 风控约束 | N/A + 原因 | 无 | 说明原因 |
| 回测现实性 | N/A + 原因 | 无 | 说明原因 |
| Artifact 导出 | N/A + 原因 | 无 | 说明原因 |
| API/UI | N/A + 原因 | 无 | 说明原因 |
| 回归测试 | N/A + 原因 | 无 | 说明原因 |

## Allowed Files

列出允许修改的路径。

## Open Questions

列出进入实现前必须关闭的问题。
