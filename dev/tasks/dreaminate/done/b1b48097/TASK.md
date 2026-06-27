---
uuid: b1b48097341547f09d84b6509acf778f
title: IDE strategy save writes StrategyBook QRO
status: done
owner: dreaminate
assigned_by: dreaminate
review_status: 1
priority: P1
area: research-os-entrypoint-wiring
source: goal-gap
source_ref: dev/GOAL.md §0/§1/§7/§8/§9/§14 + dev/state/dreaminate/state.md 头号 gap #1
depends_on: [b32dbcd8fb7e4ec6911c33290f5f0e09]
---

# IDE strategy save writes StrategyBook QRO

## Scope [必填]
Wire the IDE strategy-save entrypoint into Research Graph as a `StrategyBook`
QRO. `POST /api/ide/strategies` still uses `IDEService.save_strategy` as the
fact source; only successful saves append a graph command. The QRO stores
strategy identity, asset class, source hash, description hash, content hash, and
timestamps, but never raw Python code or description text. This does not cover
IDE run, promote, AI complete, Canvas, Scheduler, Settings, training, execution,
Graph persistence, or governed compiler passes.

## 接线点（file:line，实现时复核）[必填]
| 文件 | 改什么 |
|---|---|
| `app/backend/app/main.py` | Add `_record_ide_strategy_qro(...)`, audit allowlist fields, and return `qro_id` / `research_graph_command_id` from successful IDE save |
| `app/backend/tests/test_strategy_console_s2.py` | Add HTTP tests for StrategyBook QRO write, source/description leakage guard, and failure path no-QRO |

## 对抗测试设计（种已知 bug，门必抓）[必填]
1. Save an IDE strategy whose code and description include a secret marker; graph audit must show `StrategyBook` QRO refs and hashes, but not the marker, raw code, or raw description text.
2. Save with invalid `asset_class`; endpoint must return 400, create no strategy, and not add a Research Graph command.
3. Existing IDE graph validate, version, fork, and live snapshot tests must still pass.

## 完成记录
- Added `StrategyBook` QRO recording for successful IDE strategy saves.
- QRO status axes are honest: `definition=implemented`, `evidence=untested`, `governance=unreviewed`, `runtime=offline`.
- Graph audit allowlist exposes stable hash/identity metadata for IDE saves without raw source or description text.
- Scoped validation:
  - `cd app/backend && python -m pytest tests/test_strategy_console_s2.py -q` -> 21 passed / 2 warnings.
  - `cd app/backend && python -m pytest tests/test_ide.py tests/test_agent_runtime_research_graph.py tests/test_ds2_strategy_goal_persist.py tests/test_research_os_spine.py -q` -> 44 passed / 2 warnings.
  - `cd app/backend && python -m pytest -q` -> 1423 passed / 13 skipped / 278 warnings.
- Runtime artifact check after full suite: no files under `data/artifacts/strategy_goals`, `data/ide_runs`, `data/artifacts/llm_fixtures`, or `data/verification` from this run.

## 验收一句话 [必填]
IDE strategy save now writes a sanitized `StrategyBook` QRO on successful saves;
IDE run/promote/AI complete and the remaining non-IDE entrypoints still need
their own QRO / Research Graph wiring before GOAL §0–§17 can be called complete.
