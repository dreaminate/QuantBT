---
uuid: 4c8e476bd1424fd4939c8e109d4dd656
title: Trust disclosure registry API and workbench UI
status: done
owner: dreaminate
assigned_by: dreaminate
review_status: 1
priority: P1
area: research-os-trust-disclosure-ui
source: goal-gap
source_ref: GOAL §13 Trust Layer disclosure records and global UI
depends_on: [2f4c8e91b1db463db4dd19e1ce89e7d0, a8e03245b9d244cc92d98dc5fe29d9c3]
completed_at: 2026-06-27
---

# Trust disclosure registry API and workbench UI

## Scope [必填]
把 §13 Trust Layer 的三类已有 validator 接成持久 runtime surface：TrustClaimRecord、FunctionalIndependenceDisclosure、UserAutonomyRecord 可写入 append-only registry，可经 API 记录/汇总，并在研究执行台 Trust tab 中查看和新增。

## 上下文 / 动机 [按需]
`2f4c8e91` 已有 trust claim、functional independence、user autonomy 的 validator，但没有 registry/API/UI。`a8e03245` 补了 release check producer，仍未让用户在工作台记录“什么 claim 是强证据、如何披露单用户 functional independence、方法学选择是谁最终拍板”。本卡补 disclosure 面，不把单用户披露说成组织级专家独立验证。

## 接线点（file:line，实现时复核）[必填]
| 文件 | 改什么 |
|---|---|
| `app/backend/app/research_os/trust_layer.py` | 新增三类 record_from_dict、`PersistentTrustDisclosureRegistry`、append-only replay/no-write |
| `app/backend/app/main.py` | 新增 `TRUST_DISCLOSURE_REGISTRY`、三类 POST API、trust summary disclosure totals |
| `app/backend/app/research_os/__init__.py` | 导出 disclosure registry/from_dict helpers |
| `app/backend/tests/test_trust_layer.py` | 覆盖 registry replay/no-write 和三类 API summary/fail-closed |
| `app/frontend/src/pages/workshop/agent-workbench/TrustDisclosurePanel.tsx` | 新增 Trust tab 面板，展示 summary 并记录 claim/independence/autonomy |
| `app/frontend/src/pages/workshop/agent-workbench/TrustDisclosurePanel.test.tsx` | 覆盖三类 POST payload 和 strong claim 缺 evidence 前端阻断 |
| `app/frontend/src/pages/workshop/agent-workbench/AgentWorkbenchPage.tsx` | 接入 Trust workspace tab |

## 对抗测试设计（种已知 bug，门必抓）[必填]
1. strong claim 缺 evidence refs 必须拒绝且 no-write。
2. 单用户 mode 声称 organizational independence 或缺 functional independence refs 必须拒绝。
3. agent made final user methodology/risk choice 必须拒绝。
4. 三类 disclosure API 成功后 summary 必须能回查记录。
5. 前端 strong claim 缺 evidence refs 时不调用 `/api/research-os/trust/claims`。

## 红线 [按需]
- 不把单用户 `FunctionalIndependenceDisclosure` 包装成组织级独立验证。
- 不让 agent 替用户写最终方法学/风险选择。
- 不保存 raw prompt、raw response、secret 或外部专家伪证据。

## 非目标 [按需]
不实现真实外部专家工作流、组织流程系统、自动压力测试 runner、CI release、线上 release approval 或用户验收。

## 验收一句话 [必填]
Trust Layer 的 claim、functional independence、user autonomy 不再只有纯 validator；现在有可 replay 的 registry/API 和研究执行台 Trust UI。

## 完成记录（2026-06-27）
- 新增 `PersistentTrustDisclosureRegistry`，统一记录 trust claim、functional independence disclosure、user autonomy record。
- 新增 `/api/research-os/trust/claims`、`/independence_disclosures`、`/user_autonomy`；trust summary 返回三类 totals 和 records。
- Agent Workbench 新增 `Trust` tab，提供 summary、Record trust claim、Record independence disclosure、Record user autonomy 三组表单。
- 本地验证：
  - `python -m pytest app/backend/tests/test_trust_layer.py -q` -> 19 passed / 2 warnings。
  - `python -m pytest app/backend/tests/test_trust_layer.py app/backend/tests/test_research_os_rdp_publish.py app/backend/tests/test_goal_coverage.py -q` -> 40 passed / 2 warnings。
  - `python -m compileall -q app/backend/app` -> PASS。
  - `cd app/frontend && npm test -- TrustDisclosurePanel.test.tsx --run` -> 1 file / 2 tests passed。
  - `cd app/frontend && npm test -- agentWorkbench.test.tsx MethodologyValidationPanel.test.tsx RDPExportPanel.test.tsx ResearchRAGPanel.test.tsx TrustDisclosurePanel.test.tsx --run` -> 5 files / 66 tests passed。
  - `cd app/frontend && npm test -- --run` -> 30 files / 320 tests passed。
  - `cd app/frontend && npm run build` -> PASS（保留既有 Vite chunk-size warning）。
  - `python -m pytest app/backend/tests -q` -> 1844 passed / 13 skipped / 283 warnings。
  - `python dev/scripts/validate_dev.py` -> PASS（49 ✅ / 0 ❌ / 0 ⚠️；241 cards）。
