---
uuid: 18bb49e730a3488199892f3b31eef6d5
title: IDE promote writes promoted BacktestRun QRO
status: done
owner: dreaminate
assigned_by: dreaminate
review_status: 1
priority: P1
area: research-os-entrypoint-wiring
source: goal-gap
source_ref: dev/GOAL.md §0/§1/§7/§8/§9/§10/§14 + dev/state/dreaminate/state.md 头号 gap #1
depends_on: [a2a5b61bf5e245cd8179f4fd6854d7ce]
---

# IDE promote writes promoted BacktestRun QRO

## Scope [必填]
Wire the IDE promote entrypoint into Research Graph as a promoted `BacktestRun`
QRO. `POST /api/ide/runs/{run_id}/promote` still uses `promote_ide_run` as the
fact source and only writes a graph command after the formal run artifact is
created. The QRO stores source/promoted run ids, strategy identity/hash, metric
count, and whether a gate verdict exists, but never promoted source code,
equity curves, trades, metrics payloads, gate verdict details, or record names.
This does not cover IDE AI complete, Canvas, Scheduler, Settings, training,
execution, Graph persistence, or governed compiler passes.

## 接线点（file:line，实现时复核）[必填]
| 文件 | 改什么 |
|---|---|
| `app/backend/app/main.py` | Add `_record_ide_promote_qro(...)`, promoted-run audit fields, and refs in IDE promote response |
| `app/backend/tests/test_strategy_console_s2.py` | Add HTTP tests for successful promote, artifact/log/detail leakage guard, and PromoteError no-QRO |

## 对抗测试设计（种已知 bug，门必抓）[必填]
1. Promote a run whose source code, stdout, trades, and requested record name include a secret marker; graph audit must show refs/counts only and not leak the marker, trades, or record name.
2. Promote a run with invalid result payload; endpoint must return 400 and not add a Research Graph command.
3. HTTP promote tests must redirect promoted run output to `tmp_path`, not repository `data/`.

## 完成记录
- Added promoted `BacktestRun` QRO recording after successful IDE promote.
- QRO status axes are honest: `definition=implemented`, `evidence=exploratory`, `governance=unreviewed`, `runtime=offline`.
- Graph audit allowlist exposes promoted/source ids and counts without artifact payloads.
- Scoped validation:
  - `cd app/backend && python -m pytest tests/test_strategy_console_s2.py -q` -> 26 passed / 2 warnings.
  - `cd app/backend && python -m pytest tests/test_ide_promote.py tests/test_ide.py tests/test_agent_runtime_research_graph.py tests/test_ds2_strategy_goal_persist.py tests/test_research_os_spine.py -q` -> 54 passed / 2 warnings.
  - `cd app/backend && python -m pytest -q` -> 1428 passed / 13 skipped / 278 warnings.
- Runtime artifact check: no git-visible changes under `data/artifacts/experiments`, `data/ide_runs`, `data/artifacts/strategy_goals`, `data/artifacts/llm_fixtures`, or `data/verification`; full-suite example tests still refresh ignored demo files under `data/artifacts/experiments`.

## 验收一句话 [必填]
IDE promote now writes a sanitized promoted `BacktestRun` QRO after formal run
artifact creation; IDE AI complete and the remaining non-IDE entrypoints still
need their own QRO / Research Graph wiring before GOAL §0–§17 can be called
complete.
