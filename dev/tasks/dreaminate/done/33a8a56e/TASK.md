---
uuid: 33a8a56e214a4f70adadd6c28ddf0ff2
title: Methodology validation dossier UI
status: done
owner: dreaminate
assigned_by: dreaminate
review_status: 1
priority: P1
area: research-os-methodology-validation-ui
source: goal-gap
source_ref: GOAL §10 Methodology and validation dossier UI
depends_on: [b6bf792ce773409b812fea2011441d97, d3983386340b4fd797850c809356adfe]
completed_at: 2026-06-27
---

# Methodology validation dossier UI

## Scope [必填]
在研究执行台产物工作区新增 `Methodology` tab，接入 `/api/research-os/methodology/summary`、`/cpcv`、`/conformal`、`/tca` 和 `/validation_depth_records`。UI 展示 validation-depth 与 calculator 摘要，可录入 CPCV/conformal/TCA 本地 calculator inputs，也可写入 ValidationDepthRecord 所需 refs/verdict/责任边界字段。

## 上下文 / 动机 [按需]
`b6bf792c` 已有 ValidationDepthRecord registry/API，`d3983386` 已有 CPCV/conformal/TCA calculator producers，但研究执行台没有 §10 方法学验证操作面。用户只能手工调 API 或只看 backend summary，TRACE/state 仍把 validation dossier UI 标为缺口。本卡补现有后端 records 的前端入口，不把录入 refs 说成真实 broker/venue fault drill 已执行。

## 接线点（file:line，实现时复核）[必填]
| 文件 | 改什么 |
|---|---|
| `app/frontend/src/pages/workshop/agent-workbench/MethodologyValidationPanel.tsx` | 新增 Methodology summary、CPCV/conformal/TCA calculator 表单、ValidationDepthRecord 表单和前端缺字段阻断 |
| `app/frontend/src/pages/workshop/agent-workbench/MethodologyValidationPanel.test.tsx` | 覆盖 summary、CPCV payload/刷新、缺 folds 不打后端、validation-depth payload |
| `app/frontend/src/pages/workshop/agent-workbench/AgentWorkbenchPage.tsx` | 接入 `Methodology` workspace tab，标记 Backend |
| `app/frontend/src/pages/workshop/agent-workbench/agentMock.ts` | 扩展 `WorkspaceTab` 类型 |

## 对抗测试设计（种已知 bug，门必抓）[必填]
1. Summary 必须展示 backend 返回的 refs/count/摘要，不显示 raw fold/calibration/gross-return series。
2. CPCV 表单必须把 comma-separated values 解析为 number array，并提交 evidence refs / validation refs / cpcv_ref。
3. 缺 `fold_metric_values` 时必须在前端阻断，不调用 `/api/research-os/methodology/cpcv`。
4. ValidationDepthRecord 表单必须按 `{ validation_depth: ... }` 包装提交 refs/verdict/责任边界，并强制 `silent_mock_fallback_used=false`。
5. Workbench 新 tab 不能破坏原 agent workbench、RAG、RDP 测试。

## 红线 [按需]
- 不声称 UI 自动运行了真实 broker/venue fault injection 或 recovery drill。
- 不把本地 calculator 简化统计说成完整 CPCV path enumeration、walk-forward scheduler 或生产级 TCA simulator。
- 不展示 raw calculator series；前端 summary 只读 refs/count/hash/摘要。

## 非目标 [按需]
不实现真实 broker/venue fault drill、fault/recovery runner、monitor/promotion 自动 producer、CI release、线上验证或用户验收。

## 验收一句话 [必填]
研究执行台现在有 Methodology tab，可以在 UI 中查看方法学验证摘要、记录 CPCV/conformal/TCA calculator outputs，并写入 ValidationDepthRecord。

## 完成记录（2026-06-27）
- 新增 `MethodologyValidationPanel`，启动读取 `/api/research-os/methodology/summary`。
- 新增 CPCV/conformal/TCA 三个 calculator 表单，成功后刷新 summary；缺必要 refs/数值时前端阻断。
- 新增 ValidationDepthRecord 表单，提交 `{ validation_depth: ... }`，包含 dual-track、conformal/abstain、TCA/cost、leakage/fault/recovery refs、evidence/validation refs、methodology choice/responsibility refs。
- Agent Workbench 新增 `Methodology` tab，并把该 tab 标记为 Backend。
- 本地验证：
  - `cd app/frontend && npm test -- MethodologyValidationPanel.test.tsx --run` -> 4 passed。
  - `cd app/frontend && npm test -- agentWorkbench.test.tsx MethodologyValidationPanel.test.tsx RDPExportPanel.test.tsx ResearchRAGPanel.test.tsx --run` -> 4 files / 61 tests passed。
  - `cd app/frontend && npm test -- --run` -> 29 files / 315 tests passed。
  - `cd app/frontend && npm run build` -> PASS（保留既有 Vite chunk-size warning）。
  - `python dev/scripts/validate_dev.py` -> PASS（49 ✅ / 0 ❌ / 0 ⚠️；238 cards）。
  - `git diff --check` -> PASS。
