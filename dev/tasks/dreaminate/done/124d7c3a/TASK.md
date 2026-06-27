---
uuid: 124d7c3a8a89420da3347d698778f57e
title: IDE GOAL entrypoint coverage producer
status: done
owner: dreaminate
assigned_by: dreaminate
review_status: 1
priority: P0
area: goal-entrypoint-coverage
source: goal
source_ref: GOAL §7/§8 IDE and Agent code-change governance; finding goal-0-17-gap-matrix-2026-06-28
depends_on: [2b1706f19b714040b93e37b23f82dcf8]
created_at: 2026-06-28
---

# IDE GOAL entrypoint coverage producer

## Scope [必填]
把 IDE save/run/promote/AI complete 的成功路径接到 `entry_source=ide` GOAL coverage；不重写 IDE sandbox/promote 业务逻辑。

## 接线点（file:line，实现时复核）[必填]
| 文件 | 改什么 |
|---|---|
| `app/backend/app/main.py` | IDE strategy save/run/promote/AI complete coverage producer |
| `app/backend/tests/test_ide.py`、`test_goal_coverage.py` | 覆盖 IDE coverage 写入和坏 refs 拒绝 |

## 对抗测试设计（种已知 bug，门必抓）[必填]
1. IDE run 成功但缺 validation/evidence refs → coverage 不写。
2. AI complete 把 raw LLM output 当 compiler IR → fail-closed。
3. promote path 使用 silent mock fallback → coverage 拒绝。

## 验收一句话 [必填]
IDE 成功入口写 `entry_source=ide` coverage；缺 compiler/evidence/replay refs 或 raw LLM output-as-IR 必红。

## 完成证据
- IDE save/run/promote/AI complete 已通过 `_record_ide_strategy_qro()`、`_record_ide_run_qro()`、`_record_ide_promote_qro()`、`_record_ide_ai_complete_qro()` 写 QRO、Research Graph command、Compiler IR/pass 和 GOAL entrypoint coverage。
- entrypoint refs 分别为 `ide:strategy.save`、`ide:strategy.run`、`ide:run.promote`、`ide:ai_complete`，均为 `entry_source=ide`。
- QRO/Compiler/Coverage 只保存 code/prompt/context/output/description 的 hash、refs、count、status，不保存 raw strategy code、raw LLM prompt、raw editor context、raw LLM output、token 或 secret。
- 新增 API-level 回归测试覆盖四条成功路径的 coverage refs、coverage registry 内容、raw payload 不落账，以及 unknown MarketDataUse ref 在写 QRO/Compiler/Coverage 前 422。

## 验证
- `python -m compileall -q app/backend/tests/test_ide.py app/backend/app/main.py`
- `python -m pytest app/backend/tests/test_ide.py app/backend/tests/test_goal_coverage.py -q` → **43 passed / 2 warnings**

## 边界
- 这是 IDE save/run/promote/AI complete producer 和测试补强，不是 canvas、scheduler、chat/agent_shell producer。
- IDE sandbox/promote 业务逻辑未重写；MarketDataUse gate 仍是上游前置条件。
- 这仍只覆盖 GOAL `§0/§1/§7/§8` entrypoint wiring，不是 §0-§17 full product implementation proof、CI、线上或用户验收。
