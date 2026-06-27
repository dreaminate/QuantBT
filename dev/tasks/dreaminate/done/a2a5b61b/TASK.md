---
uuid: a2a5b61bf5e245cd8179f4fd6854d7ce
title: IDE strategy run writes BacktestRun QRO
status: done
owner: dreaminate
assigned_by: dreaminate
review_status: 1
priority: P1
area: research-os-entrypoint-wiring
source: goal-gap
source_ref: dev/GOAL.md §0/§1/§7/§8/§9/§10/§14 + dev/state/dreaminate/state.md 头号 gap #1
depends_on: [b1b48097341547f09d84b6509acf778f]
---

# IDE strategy run writes BacktestRun QRO

## Scope [必填]
Wire the IDE sandbox run entrypoint into Research Graph as a `BacktestRun` QRO.
`POST /api/ide/strategies/{name}/run` still executes through `IDEService.run_strategy`;
after an actual run record exists, the endpoint appends a graph command and
returns `qro_id` / `research_graph_command_id`. The QRO stores strategy/run
identity, source hashes, run status, timing, exit code, and result-key count,
but never raw source code, stdout, stderr, result payloads, or result key names.
This does not cover IDE promote, AI complete, Canvas, Scheduler, Settings,
training, execution, Graph persistence, or governed compiler passes.

## 接线点（file:line，实现时复核）[必填]
| 文件 | 改什么 |
|---|---|
| `app/backend/app/main.py` | Add `_record_ide_run_qro(...)`, BacktestRun audit fields, and refs in IDE run response |
| `app/backend/tests/test_strategy_console_s2.py` | Add HTTP tests for ok run, failed run, no log/result leakage, and unknown strategy no-QRO |

## 对抗测试设计（种已知 bug，门必抓）[必填]
1. Run a strategy that prints a secret marker and emits a user result with a sensitive key; graph audit must expose only hashes/counts and not leak the marker or result key name.
2. Run a strategy that raises a secret-bearing exception; the response may contain stderr, but graph audit must not leak it, and the QRO evidence axis must be `insufficient`.
3. Run an unknown strategy; endpoint must return 404 and not add a Research Graph command.

## 完成记录
- Added `BacktestRun` QRO recording for actual IDE sandbox runs.
- QRO status axes are honest: successful sandbox runs are `evidence=exploratory`, failed/timeout runs are `evidence=insufficient`; all remain `runtime=offline` and `governance=unreviewed`.
- Graph audit allowlist exposes run metadata without stdout/stderr/result payloads/result key names.
- Scoped validation:
  - `cd app/backend && python -m pytest tests/test_strategy_console_s2.py -q` -> 24 passed / 2 warnings.
  - `cd app/backend && python -m pytest tests/test_ide.py tests/test_agent_runtime_research_graph.py tests/test_ds2_strategy_goal_persist.py tests/test_research_os_spine.py -q` -> 44 passed / 2 warnings.
  - `cd app/backend && python -m pytest -q` -> 1426 passed / 13 skipped / 278 warnings.
- Runtime artifact check after full suite: no files under `data/artifacts/strategy_goals`, `data/ide_runs`, `data/artifacts/llm_fixtures`, or `data/verification` from this run.

## 验收一句话 [必填]
IDE strategy run now writes a sanitized `BacktestRun` QRO after real sandbox
execution; IDE promote/AI complete and the remaining non-IDE entrypoints still
need their own QRO / Research Graph wiring before GOAL §0–§17 can be called
complete.
