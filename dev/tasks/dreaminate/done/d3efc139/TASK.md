---
uuid: d3efc139064c48f0a9befa72234fe8b3
title: Methodology runtime drill producer API and UI
status: done
owner: dreaminate
assigned_by: dreaminate
review_status: 1
priority: P1
area: research-os-methodology-runtime-drills
source: goal-gap
source_ref: GOAL §10 fault injection and recovery drill producer seam
depends_on: [b6bf792ce773409b812fea2011441d97, d3983386340b4fd797850c809356adfe, 33a8a56e214a4f70adadd6c28ddf0ff2]
completed_at: 2026-06-27
---

# Methodology runtime drill producer API and UI

## Scope [必填]
新增 §10 runtime drill producer seam：后端记录 fault injection / recovery drill refs、guard/recovery evidence refs、drill mode、venue/scenario 和 source hash；提供 append-only registry、summary 和 API；研究执行台 Methodology tab 可提交 runtime drill，并把返回的 `fault_injection_ref` / `recovery_drill_ref` 回填到 ValidationDepthRecord 表单。

## 上下文 / 动机 [按需]
`b6bf792c` 要求 runtime candidate 的 ValidationDepthRecord 绑定 fault injection / recovery drill refs，`33a8a56e` 已有 UI 但只能手填 refs。本卡补 producer/API/UI seam，让 refs 可由受控 runtime drill record 生成。该 producer 明确限制为 `simulation` / `paper` / `testnet`，拒绝 `live` / `production` drill mode，避免把本地演练冒充真实实盘/真钱故障演练。

## 接线点（file:line，实现时复核）[必填]
| 文件 | 改什么 |
|---|---|
| `app/backend/app/research_os/methodology_validation.py` | 新增 `RuntimeDrillRecord`、validator、producer、JSONL registry/replay |
| `app/backend/app/main.py` | 新增 `METHODOLOGY_RUNTIME_DRILL_REGISTRY`、`POST /api/research-os/methodology/runtime_drills`、summary runtime drill totals |
| `app/backend/app/research_os/__init__.py` | 导出 runtime drill 类型/helper/registry |
| `app/backend/tests/test_methodology_validation.py` | 覆盖 refs/hash/replay、unsafe mode、guard mismatch、silent mock no-write、API summary |
| `app/frontend/src/pages/workshop/agent-workbench/MethodologyValidationPanel.tsx` | 新增 Runtime drills 表单、summary 展示、fault/recovery refs 回填 validation-depth draft |
| `app/frontend/src/pages/workshop/agent-workbench/MethodologyValidationPanel.test.tsx` | 覆盖 runtime drill payload、summary 刷新、fault/recovery refs 回填 |

## 对抗测试设计（种已知 bug，门必抓）[必填]
1. `drill_mode=live` 或其他非 safe mode 必须 422/no-write。
2. `observed_guard_ref` 与 `expected_guard_ref` 不一致必须拒绝。
3. silent mock fallback 必须拒绝，registry 文件不写。
4. Summary 只返回 refs/hash/verdict/mode，不返回 raw logs / traceback。
5. 前端提交 runtime drill 后必须刷新 summary，并回填 validation-depth 的 fault/recovery refs。

## 红线 [按需]
- 不声称该 seam 已接真实 broker/venue API 或真钱故障演练。
- 不允许 live/production drill mode 通过这个安全 producer。
- 不保存 raw execution log、traceback、secret 或 provider payload。

## 非目标 [按需]
不实现真实 broker/venue fault runner、venue-native fault injection、production scheduler、live deployment drill、CI 或线上验收。

## 验收一句话 [必填]
§10 现在有 safe-mode runtime drill producer，可生成可 replay 的 fault injection / recovery drill refs，并可从 Methodology UI 回填到 ValidationDepthRecord。

## 完成记录（2026-06-27）
- 新增 `RuntimeDrillRecord`、`validate_runtime_drill()`、`record_runtime_drill()` 和 `PersistentMethodologyRuntimeDrillRegistry`。
- 新增 `/api/research-os/methodology/runtime_drills`；summary 返回 `runtime_drill_total` 与 `runtime_drills` 摘要。
- Methodology UI 新增 Runtime drills 表单；成功记录后自动回填 fault/recovery refs 到 validation-depth draft。
- 本地验证：
  - `python -m pytest app/backend/tests/test_methodology_validation.py -q` -> 19 passed / 2 warnings。
  - `python -m pytest app/backend/tests/test_methodology_validation.py app/backend/tests/test_goal_coverage.py app/backend/tests/test_governed_compiler.py app/backend/tests/test_research_os_spine.py app/backend/tests/test_trust_layer.py app/backend/tests/test_research_os_rdp.py -q` -> 85 passed / 2 warnings。
  - `python -m pytest app/backend/tests -q` -> 1838 passed / 13 skipped / 283 warnings。
  - `python -m compileall -q app/backend/app` -> PASS。
  - `cd app/frontend && npm test -- MethodologyValidationPanel.test.tsx --run` -> 5 passed。
  - `cd app/frontend && npm test -- agentWorkbench.test.tsx MethodologyValidationPanel.test.tsx RDPExportPanel.test.tsx ResearchRAGPanel.test.tsx --run` -> 4 files / 62 tests passed。
  - `cd app/frontend && npm test -- --run` -> 29 files / 316 tests passed。
  - `cd app/frontend && npm run build` -> PASS（保留既有 Vite chunk-size warning）。
  - `python dev/scripts/validate_dev.py` -> PASS（49 ✅ / 0 ❌ / 0 ⚠️；239 cards）。
  - `git diff --check` -> PASS。
