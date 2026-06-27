---
uuid: 4f4eab2a60344f47bcdd70de71b10b17
title: IDE AI complete writes LLMCallRecord QRO
status: done
owner: dreaminate
assigned_by: dreaminate
review_status: 1
priority: P1
area: research-os-entrypoint-wiring
source: goal-gap
source_ref: dev/GOAL.md §0/§1/§4/§7/§8/§14/§16 + dev/state/dreaminate/state.md 头号 gap #1
depends_on: [18bb49e730a3488199892f3b31eef6d5]
---

# IDE AI complete writes LLMCallRecord QRO

## Scope [必填]
Wire the IDE AI complete entrypoint into Research Graph as an `LLMCallRecord`
QRO. `POST /api/ide/ai_complete` still returns generated text to the user; the
QRO stores only mode, provider, prompt hash, context hash, output hash, output
character count, and market. It never copies prompt text, editor context, or
generated code/explanation into the graph audit surface. This does not cover
Graph persistence, LLM Gateway hard routing, Canvas, Scheduler, Settings,
training, execution, or governed compiler passes.

## 接线点（file:line，实现时复核）[必填]
| 文件 | 改什么 |
|---|---|
| `app/backend/app/main.py` | Add `_record_ide_ai_complete_qro(...)`, LLM audit fields, and refs in AI complete response |
| `app/backend/tests/test_strategy_console_s2.py` | Add HTTP tests for prompt/context/output leakage guard and empty-prompt no-QRO |

## 对抗测试设计（种已知 bug，门必抓）[必填]
1. Call AI complete with secret-bearing prompt and editor context; fake LLM returns secret-bearing generated code. The endpoint may return generated code to the user, but graph audit must expose hashes/counts only.
2. Empty prompt returns 400 and must not add a Research Graph command.

## 完成记录
- Added `LLMCallRecord` QRO recording after successful IDE AI complete calls.
- QRO status axes are honest: `definition=implemented`, `evidence=untested`, `governance=unreviewed`, `runtime=offline`.
- Graph audit allowlist exposes prompt/context/output hashes without raw text.
- Scoped validation:
  - `cd app/backend && python -m pytest tests/test_strategy_console_s2.py -q` -> 28 passed / 2 warnings.
  - `cd app/backend && python -m pytest tests/test_ide_promote.py tests/test_ide.py tests/test_agent_runtime_research_graph.py tests/test_ds2_strategy_goal_persist.py tests/test_research_os_spine.py -q` -> 54 passed / 2 warnings.
  - `cd app/backend && python -m pytest -q` -> 1430 passed / 13 skipped / 278 warnings.
- Runtime artifact check: no git-visible changes under `data/artifacts/experiments`, `data/ide_runs`, `data/artifacts/strategy_goals`, `data/artifacts/llm_fixtures`, or `data/verification`.

## 验收一句话 [必填]
IDE AI complete now writes a sanitized `LLMCallRecord` QRO after successful LLM
calls; non-IDE entrypoints, Graph persistence, and hard LLM Gateway routing
still need their own QRO / Research Graph wiring before GOAL §0–§17 can be
called complete.
