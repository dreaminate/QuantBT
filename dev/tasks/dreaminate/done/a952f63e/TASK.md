---
uuid: a952f63e019644bcacd1c319dfbe4be4
title: External expert review registry API and Trust UI
status: done
owner: dreaminate
assigned_by: dreaminate
review_status: 1
priority: P1
area: research-os-trust-expert-review
source: goal-gap
source_ref: GOAL §13 Trust Layer external expert workflow; GOAL §17 RDP release approval evidence
depends_on: [4c8e476bd1424fd4939c8e109d4dd656, bab2b1484d994a72ab0eaf5b1c382750]
completed_at: 2026-06-27
---

# External expert review registry API and Trust UI

## Scope [必填]
新增 §13 external expert review record：后端可记录外部专家审查的 reviewer、independence、artifact、protocol、verdict、evidence、veto reason 和 signed attestation refs；append-only registry 可 replay；Trust tab 可查看 summary 并新增 expert review。

## 上下文 / 动机 [按需]
Trust release gate 和 release check suite 已能登记本地 refs，但 TRACE §13 仍明确缺真实外部专家工作流。当前不能假装接入了外部组织系统，所以本卡先做真实 evidence record 面：只有用户/系统拿到外部专家证据 refs 后，才能登记 expert review；agent/self/system reviewer、approved 缺 signed attestation、veto 缺 reason、silent mock 均拒绝。

## 接线点（file:line，实现时复核）[必填]
| 文件 | 改什么 |
|---|---|
| `app/backend/app/research_os/trust_layer.py` | 新增 `ExternalExpertReviewRecord`、validator、producer、from_dict、disclosure registry replay |
| `app/backend/app/main.py` | 新增 `/api/research-os/trust/expert_reviews` 和 trust summary expert totals/records |
| `app/backend/app/research_os/__init__.py` | 导出 expert review 类型/helper/validator |
| `app/backend/tests/test_trust_layer.py` | 覆盖 producer、validator、registry replay/no-write、API summary/fail-closed |
| `app/frontend/src/pages/workshop/agent-workbench/TrustDisclosurePanel.tsx` | Trust tab 新增 expert review summary 与表单 |
| `app/frontend/src/pages/workshop/agent-workbench/TrustDisclosurePanel.test.tsx` | 覆盖 expert review payload、summary 刷新、approved 缺 signed attestation 前端阻断 |

## 对抗测试设计（种已知 bug，门必抓）[必填]
1. `reviewer_ref=agent:*` / system / self / generic user 必须拒绝。
2. approved expert review 缺 `signed_attestation_ref` 必须拒绝。
3. vetoed / needs_revision 缺 `veto_reason_refs` 必须拒绝。
4. 缺 evidence refs 或 silent mock fallback 必须拒绝且 no-write。
5. API summary 只能回 refs/hash/verdict，不保存 raw notes 或 raw reviewer transcript。
6. 前端 approved 缺 signed attestation 不调用后端。

## 红线 [按需]
- 不声称已经有外部专家系统、组织流程系统或 CI release。
- 不让 agent/self/system 伪装外部专家。
- 不保存 raw prompt、raw response、raw transcript、secret 或外部审查原文。

## 非目标 [按需]
不实现外部专家账号体系、电子签平台、组织审批流、自动 agent 压力测试 runner、CI release、线上 release approval 或外部 publish。

## 验收一句话 [必填]
Trust tab 现在能登记外部专家审查 refs；后端只接受带独立性证据、artifact/protocol/evidence 和签名/否决理由的审查记录。

## 完成记录（2026-06-27）
- 新增 `ExternalExpertReviewRecord`、`validate_external_expert_review()`、`record_external_expert_review()` 和 `external_expert_review_from_dict()`。
- `PersistentTrustDisclosureRegistry` 新增 `external_expert_review_recorded` event replay 和 query methods。
- 新增 `/api/research-os/trust/expert_reviews`；trust summary 返回 `expert_review_total` 与 `expert_reviews`。
- Trust tab 新增 expert review summary 和 Record expert review 表单。
- 本地验证（截至建卡时）：
  - `python -m pytest app/backend/tests/test_trust_layer.py -q` -> 24 passed / 2 warnings。
  - `python -m pytest app/backend/tests/test_trust_layer.py app/backend/tests/test_research_os_rdp_publish.py app/backend/tests/test_goal_coverage.py -q` -> 45 passed / 2 warnings。
  - `python -m compileall -q app/backend/app` -> PASS。
  - `cd app/frontend && npm test -- TrustDisclosurePanel.test.tsx --run` -> 1 file / 3 tests passed。
  - `cd app/frontend && npm test -- agentWorkbench.test.tsx MethodologyValidationPanel.test.tsx RDPExportPanel.test.tsx ResearchRAGPanel.test.tsx TrustDisclosurePanel.test.tsx --run` -> 5 files / 69 tests passed。
  - `cd app/frontend && npm test -- --run` -> 30 files / 323 tests passed。
  - `cd app/frontend && npm run build` -> PASS（保留既有 Vite chunk-size warning）。
  - `python -m pytest app/backend/tests -q` -> 1849 passed / 13 skipped / 283 warnings。
  - `python dev/scripts/validate_dev.py` -> PASS（49 ✅ / 0 ❌ / 0 ⚠️；243 cards）。
  - `git diff --check` -> PASS。
