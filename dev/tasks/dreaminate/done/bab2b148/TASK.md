---
uuid: bab2b1484d994a72ab0eaf5b1c382750
title: Trust release check suite producer API and RDP UI
status: done
owner: dreaminate
assigned_by: dreaminate
review_status: 1
priority: P1
area: research-os-trust-release-suite-producer
source: goal-gap
source_ref: GOAL §13 Trust Layer release checks; GOAL §17 RDP publish release gate
depends_on: [a8e03245b9d244cc92d98dc5fe29d9c3, 4c8e476bd1424fd4939c8e109d4dd656]
completed_at: 2026-06-27
---

# Trust release check suite producer API and RDP UI

## Scope [必填]
新增 §13 Trust Release Check Suite producer：后端一次性接收六类 release checks，先完整校验 check kind 覆盖、重复项、expected/observed behavior、evidence refs、validation refs 和 silent mock，再生成 matching Trust Release Gate 并写入 check/gate registries；RDP export desk 可提交 suite payload 并回填 release gate draft。

## 上下文 / 动机 [按需]
`a8e03245` 已有单条 release check producer，但 release gate 仍要人工逐条生成六个 check ref 后再记录 gate。GOAL §13/§17 的缺口写着自动压力测试 runner / release workflow。当前不能伪造外部专家或 CI，所以本卡只做本地 refs-only suite producer：一次请求要求六类检查全部存在并通过，不声称外部工作流已发生。

## 接线点（file:line，实现时复核）[必填]
| 文件 | 改什么 |
|---|---|
| `app/backend/app/research_os/trust_layer.py` | 新增 `record_trust_release_check_suite()` 和 check-kind 到 gate-field 映射；缺项、重复项、坏 payload fail-closed |
| `app/backend/app/main.py` | 新增 `POST /api/research-os/trust/release_check_suites`，全部校验通过后写 six checks + one gate |
| `app/backend/app/research_os/__init__.py` | 导出 suite producer |
| `app/backend/tests/test_trust_layer.py` | 覆盖 suite pure producer、API success、missing/duplicate no partial write |
| `app/frontend/src/pages/workshop/agent-workbench/RDPExportPanel.tsx` | 新增 release check suite JSON array 表单，成功后刷新 summary 并回填 release gate draft |
| `app/frontend/src/pages/workshop/agent-workbench/RDPExportPanel.test.tsx` | 覆盖 suite payload、六类 check、gate 回填、invalid JSON 前端阻断 |

## 对抗测试设计（种已知 bug，门必抓）[必填]
1. suite 缺任一 required check kind 必须拒绝，check/gate registry 都不写。
2. suite 重复 check kind 必须拒绝，check/gate registry 都不写。
3. 任一 check 的 expected/observed behavior mismatch、缺 refs 或 silent mock 走单条 check validator 拒绝。
4. 成功 suite 必须写 6 条 `TrustReleaseCheckRecord` 和 1 条 `TrustReleaseGateRecord`。
5. 前端 checks JSON 非数组或非法 JSON 时不调用后端。

## 红线 [按需]
- 不声称 suite producer 是真实外部专家工作流。
- 不声称 suite producer 已跑 CI release、线上发布或用户验收。
- 不允许缺项 suite 写半条 check 或半条 gate。

## 非目标 [按需]
不实现真实外部专家工作流、自动 agent 多轮压力测试 runner、CI release、线上 release approval、外部 object store publish 或生产发布证明。

## 验收一句话 [必填]
RDP export desk 现在可以一次提交六类 release checks；后端只有在六类全部通过时才写入 checks 与 release gate，失败不落半成品。

## 完成记录（2026-06-27）
- 新增 `record_trust_release_check_suite()`，用六类 check kind 组装 matching `TrustReleaseGateRecord`。
- 新增 `/api/research-os/trust/release_check_suites`；成功返回 release gate、six release checks 和 kind->check_ref map。
- RDP export desk 新增 release check suite JSON array 表单；成功后刷新 trust summary，填 `trust_release_ref`，并把 returned release gate 写入 gate draft。
- 本地验证（截至建卡时）：
  - `python -m pytest app/backend/tests/test_trust_layer.py -q` -> 22 passed / 2 warnings。
  - `python -m pytest app/backend/tests/test_trust_layer.py app/backend/tests/test_research_os_rdp_publish.py app/backend/tests/test_goal_coverage.py -q` -> 43 passed / 2 warnings。
  - `python -m compileall -q app/backend/app` -> PASS。
  - `cd app/frontend && npm test -- RDPExportPanel.test.tsx --run` -> 1 file / 14 tests passed。
  - `cd app/frontend && npm test -- agentWorkbench.test.tsx MethodologyValidationPanel.test.tsx RDPExportPanel.test.tsx ResearchRAGPanel.test.tsx TrustDisclosurePanel.test.tsx --run` -> 5 files / 68 tests passed。
  - `cd app/frontend && npm test -- --run` -> 30 files / 322 tests passed。
  - `cd app/frontend && npm run build` -> PASS（保留既有 Vite chunk-size warning）。
  - `python -m pytest app/backend/tests -q` -> 1847 passed / 13 skipped / 283 warnings。
  - `python dev/scripts/validate_dev.py` -> PASS（49 ✅ / 0 ❌ / 0 ⚠️；242 cards）。
  - `git diff --check` -> PASS。
