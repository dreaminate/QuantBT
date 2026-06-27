---
uuid: acd267d19c9542c08700755ffc473ed9
title: Trust release approval workflow registry API and RDP UI
status: done
owner: dreaminate
assigned_by: dreaminate
review_status: 1
priority: P1
area: research-os-trust-release-approval
source: goal-gap
source_ref: GOAL §13 Trust Layer release approval workflow; GOAL §17 RDP release approval evidence
depends_on: [f94d20a094704dee98162ee706fe7ac6, a952f63e019644bcacd1c319dfbe4be4]
completed_at: 2026-06-27
---

# Trust release approval workflow registry API and RDP UI

## Scope [必填]
新增 §13/§17 Trust release approval workflow record：后端把已登记 release gate、pressure run、external expert review、artifact、approval protocol、evidence、signature 和 verdict 合成一条 append-only approval record；RDP export desk 可查看 approval summary，并提交 approval refs。

## 上下文 / 动机 [按需]
`f94d20a0` 已能生成本地 deterministic/test harness pressure run，`a952f63e` 已能登记 external expert review evidence，但 RDP/Trust 侧仍没有一个把 gate + runner + expert review 合并为 release approval evidence 的 workflow record。本卡先落独立 approval record/API/UI，不改 RDP publish 强制门，避免把本地 record 误写成 CI/线上发布。

## 接线点（file:line，实现时复核）[必填]
| 文件 | 改什么 |
|---|---|
| `app/backend/app/research_os/trust_layer.py` | 新增 `TrustReleaseApprovalRecord`、validator、producer、from_dict、append-only registry |
| `app/backend/app/research_os/__init__.py` | 导出 release approval 类型/helper/registry/validator |
| `app/backend/app/main.py` | 新增 `/api/research-os/trust/release_approvals`，trust summary 返回 approval totals/records |
| `app/backend/tests/test_trust_layer.py` | 覆盖 producer、validator、registry replay/no-write、API success/fail-closed |
| `app/frontend/src/pages/workshop/agent-workbench/RDPExportPanel.tsx` | 新增 release approvals summary/list/form，可录 gate/pressure/expert/protocol/signature/evidence refs |
| `app/frontend/src/pages/workshop/agent-workbench/RDPExportPanel.test.tsx` | 覆盖 approval payload、summary refresh、approved 缺签名前端阻断 |

## 对抗测试设计（种已知 bug，门必抓）[必填]
1. approval 必须绑定已登记且同一 `release_ref` 的 release gate、pressure run 和 expert review。
2. approved verdict 必须有 `signed_approval_ref`，且不能带 residual blocker refs。
3. blocked / needs_revision 必须带 residual blocker refs。
4. approved approval 不能引用 needs_revision/vetoed expert review。
5. unknown gate/pressure/expert ref 或 release mismatch 不写 approval record。
6. 前端 approved 缺签名时不调用后端。

## 红线 [按需]
- 不声称 approval record 等于 CI release、线上发布、外部组织审批流或用户验收。
- 不把本卡说成 RDP publish 已强制引用 approval ref；发布门升级是下一步。
- 不允许 silent mock fallback 写 approval。

## 非目标 [按需]
不实现真实 CI runner、外部专家账号/签名系统、外部 object store publish、live deployment runner、生产发布证明、线上验收，也不在本卡升级 RDP publish hard gate。

## 验收一句话 [必填]
RDP export desk 现在可以把 release gate、pressure run 和 expert review 合成一条本地 trust release approval record；后端拒绝坏 ref、坏签名、坏专家结论和 silent mock，失败不落半成品。

## 完成记录（2026-06-27）
- 新增 `TrustReleaseApprovalRecord`、`validate_trust_release_approval()`、`record_trust_release_approval()` 和 `PersistentTrustReleaseApprovalRegistry`。
- 新增 `/api/research-os/trust/release_approvals`；API 从现有 gate/pressure/expert registries 查真实记录，成功后写 approval JSONL，summary 回显 `release_approval_total` 与 `release_approvals`。
- RDP export desk 新增 release approvals 列表、expert review ref 选择和 approval 表单；成功后刷新 trust summary 并填 publish `trust_release_ref`。
- 本地验证（截至建卡时）：
  - `python -m compileall -q app/backend/app` -> PASS。
  - `python -m pytest app/backend/tests/test_trust_layer.py -q` -> 36 passed / 2 warnings。
  - `python -m pytest app/backend/tests/test_trust_layer.py app/backend/tests/test_research_os_rdp_publish.py app/backend/tests/test_goal_coverage.py -q` -> 57 passed / 2 warnings。
  - `cd app/frontend && npm test -- RDPExportPanel.test.tsx --run` -> 1 file / 18 tests passed。
  - `cd app/frontend && npm test -- agentWorkbench.test.tsx MethodologyValidationPanel.test.tsx RDPExportPanel.test.tsx ResearchRAGPanel.test.tsx TrustDisclosurePanel.test.tsx --run` -> 5 files / 73 tests passed。
  - `cd app/frontend && npm test -- --run` -> 30 files / 327 tests passed。
  - `cd app/frontend && npm run build` -> PASS（保留既有 Vite chunk-size warning）。
  - `python -m pytest app/backend/tests -q` -> 1861 passed / 13 skipped / 283 warnings。
  - `python dev/scripts/validate_dev.py` -> PASS（49 ✅ / 0 ❌ / 0 ⚠️；245 cards）。
  - `git diff --check` -> PASS。
