# RULE-CHG-0001

status: confirmed

review_status: 1

confirmed_by: user

confirmed_at: 2026-05-11

## Reason

为量化研究平台建立第一版 Codex harness，防止后续开发在数据、模型、优化器、风控和回测层之间发生边界漂移。

## Scope

- 新增 `docs/codex_rules/README.md`
- 新增 `docs/codex_rules/scripts/validate_harness.py`
- 新增 `docs/codex_know/` 初始事实草案
- 新增 `docs/tasks/index.md`
- 新增 `docs/templates/` 初始模板

## Impact

后续任何代码实现都应先有任务卡、review 状态和验收矩阵。当前变更不修改运行代码，不改变已有 API、数据拉取或前端行为。

## Review Notes

用户已确认 rules 没问题。本变更作为第一版 harness 规则基线生效。
