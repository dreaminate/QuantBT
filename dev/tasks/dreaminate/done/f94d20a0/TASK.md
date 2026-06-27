---
uuid: f94d20a094704dee98162ee706fe7ac6
title: Trust pressure runner producer API and RDP UI
status: done
owner: dreaminate
assigned_by: dreaminate
review_status: 1
priority: P1
area: research-os-trust-pressure-runner
source: goal-gap
source_ref: GOAL §13 Trust Layer automatic pressure runner; GOAL §17 RDP release approval evidence
depends_on: [bab2b1484d994a72ab0eaf5b1c382750, a952f63e019644bcacd1c319dfbe4be4]
completed_at: 2026-06-27
---

# Trust pressure runner producer API and RDP UI

## Scope [必填]
新增 §13 Trust pressure runner：后端接收 release、runner mode、六类 pressure scenarios、runner evidence refs 和 validation result refs，先完整校验六类检查覆盖、scenario refs、expected/observed behavior、evidence refs、validation refs、失败 scenario 和 silent mock，再复用 release check suite producer 生成 six checks + one release gate，并追加一条 runner record；RDP export desk 可提交 runner scenarios 并回填 release gate draft。

## 上下文 / 动机 [按需]
`bab2b148` 已能一次提交六类 release checks，但仍是人工提交 suite。GOAL §13/§17 的残余缺口明确写着自动 agent 压力测试 runner。当前不能伪装 CI、真实外部专家、真实 agent 长程执行或线上发版，所以本卡落的是本地 deterministic / test harness runner record：runner 输入必须带 evidence/validation refs，失败 scenario 或 silent mock 不写 partial record。

## 接线点（file:line，实现时复核）[必填]
| 文件 | 改什么 |
|---|---|
| `app/backend/app/research_os/trust_layer.py` | 新增 `TrustPressureRunRecord`、`validate_trust_pressure_run()`、`record_trust_pressure_run()`、from_dict 和 `PersistentTrustPressureRunRegistry` |
| `app/backend/app/research_os/__init__.py` | 导出 pressure runner 类型/helper/registry |
| `app/backend/app/main.py` | 新增 `POST /api/research-os/trust/pressure_runs`，summary 返回 pressure run totals/records |
| `app/backend/tests/test_trust_layer.py` | 覆盖 producer、validator、registry replay/no-write、API summary/fail-closed |
| `app/frontend/src/pages/workshop/agent-workbench/RDPExportPanel.tsx` | 新增 pressure runs summary/list/scenario JSON 表单，成功后刷新 summary 并回填 release gate draft |
| `app/frontend/src/pages/workshop/agent-workbench/RDPExportPanel.test.tsx` | 覆盖 pressure run payload、六类 scenario、summary refresh、gate field backfill、invalid JSON 前端阻断 |

## 对抗测试设计（种已知 bug，门必抓）[必填]
1. runner mode 只允许 `local_deterministic` / `test_harness`，未知 mode 必须拒绝。
2. 任一 scenario expected/observed behavior mismatch、带 outcome flag、缺 refs 或 silent mock 必须拒绝。
3. 缺任一 required check kind 或重复 check kind 必须拒绝，check/gate/run registry 都不写 partial record。
4. 成功 pressure run 必须写 6 条 `TrustReleaseCheckRecord`、1 条 `TrustReleaseGateRecord` 和 1 条 `TrustPressureRunRecord`。
5. 前端 scenarios JSON 非数组或非法 JSON 时不调用后端。

## 红线 [按需]
- 不声称这是 CI release、线上 release 或外部专家真实审批。
- 不声称本地 deterministic/test harness runner 等于真实 autonomous agent 长程压力测试。
- 不允许失败 scenario 或 silent mock 写 release gate。

## 非目标 [按需]
不实现真实 CI runner、真实 autonomous agent execution、外部专家账号/签名系统、外部 object store publish、live deployment runner、生产发布证明或线上验收。

## 验收一句话 [必填]
RDP export desk 现在可以提交六类 pressure scenarios；后端只有在本地 runner evidence/validation refs 和六类 scenario 全部通过时才写 checks、release gate 与 pressure run record，失败不落半成品。

## 完成记录（2026-06-27）
- 新增 `TrustPressureRunRecord`、`validate_trust_pressure_run()`、`record_trust_pressure_run()` 和 `PersistentTrustPressureRunRegistry`。
- 新增 `/api/research-os/trust/pressure_runs`；成功返回 pressure run、release gate、six release checks 和 kind->check_ref map，并在 trust summary 回显 pressure runs。
- RDP export desk 新增 pressure runs 列表和 scenarios JSON 表单；成功后刷新 trust summary，填 `trust_release_ref`，并把 returned release gate 写入 gate draft。
- 本地验证（截至建卡时）：
  - `python -m pytest app/backend/tests/test_trust_layer.py -q` -> 30 passed / 2 warnings。
  - `python -m pytest app/backend/tests/test_trust_layer.py app/backend/tests/test_research_os_rdp_publish.py app/backend/tests/test_goal_coverage.py -q` -> 51 passed / 2 warnings。
  - `python -m compileall -q app/backend/app` -> PASS。
  - `cd app/frontend && npm test -- RDPExportPanel.test.tsx --run` -> 1 file / 16 tests passed。
  - `cd app/frontend && npm test -- agentWorkbench.test.tsx MethodologyValidationPanel.test.tsx RDPExportPanel.test.tsx ResearchRAGPanel.test.tsx TrustDisclosurePanel.test.tsx --run` -> 5 files / 71 tests passed。
  - `cd app/frontend && npm test -- --run` -> 30 files / 325 tests passed。
  - `cd app/frontend && npm run build` -> PASS（保留既有 Vite chunk-size warning）。
  - `python -m pytest app/backend/tests -q` -> 1855 passed / 13 skipped / 283 warnings。
  - `python dev/scripts/validate_dev.py` -> PASS（49 ✅ / 0 ❌ / 0 ⚠️；244 cards）。
  - `git diff --check` -> PASS。
