---
uuid: b793f3a7f0214db1829a5ea430fcabee
title: RDP CI release attestation proof
status: done
owner: dreaminate
assigned_by: dreaminate
review_status: 1
priority: P1
area: research-os-rdp-ci-release
source: goal-gap
source_ref: GOAL §17 RDP CI release proof; TRACE §17 CI release/live deployment proof residual
depends_on: [770982f3c82f41e0907956b38f767c16, 4143d1ccce7546bdb70c7d7791baa43f]
created_at: 2026-06-28
completed_at: 2026-06-28
---

# RDP CI release attestation proof

## Scope [必填]
新增 RDP CI release attestation proof runtime：在 local publication、external publication proof、trust release gate 和 approved release approval 已存在后，允许登记 CI/release workflow 的 refs/hash 证明。record 必须绑定 package、manifest hash、local publication hash、external proof hash、archive hash、release approval ref、CI workflow/run/commit refs、artifact digest、test report refs/hash 和 evidence refs；summary/API/UI 只回显 refs/hash，不保存 raw CI log、secret、token、signed URL 或 raw artifact payload。

## 上下文 / 动机 [按需]
`770982f3` 已能登记 refs-only external publication proof，但 TRACE §17 仍把 CI release/live deployment runner/线上发版证明列为残余。直接接真实 CI 凭据会越过 Secrets、外部账号和部署权限边界。本卡先落可 replay 的 CI release attestation record：CI 可由外部系统完成，QuantBT 只接受可验证 refs/hash，并拒绝缺 local publication、缺 external proof、approval mismatch、archive mismatch、failed/skipped checks 或 secret-bearing evidence。

## 接线点（file:line，实现时复核）[必填]
| 文件 | 改什么 |
|---|---|
| `app/backend/app/research_os/rdp.py` | 新增 `RDPCIReleaseAttestationRecord`、validator、JSONL-backed store |
| `app/backend/app/research_os/__init__.py` | 导出 CI release attestation record/store |
| `app/backend/app/main.py` | 新增 `/api/research-os/rdp/manifests/{package_id}/ci_release_attestations`，publications list 回显 |
| `app/backend/tests/test_research_os_rdp_publish.py` | 覆盖成功记录、缺 local publication、缺 external proof、archive mismatch、approval mismatch、failed/skipped checks、secret refs 坏门 |
| `app/frontend/src/pages/workshop/agent-workbench/RDPExportPanel.tsx` | RDP export desk 展示/录入 CI release attestation，复用当前 local publication/external proof refs |
| `app/frontend/src/pages/workshop/agent-workbench/RDPExportPanel.test.tsx` | 覆盖 CI attestation payload、缺 external proof 前端阻断、结果回显 |

## 对抗测试设计（种已知 bug，门必抓）[必填]
1. 没有 local publication hash 时不能登记 CI release attestation。
2. 没有 matching external publication proof 时不能登记 CI release attestation。
3. archive sha256 与 local publication/external proof 不一致必须拒绝。
4. release approval ref 必须等于 local publication/external proof 的 approved approval ref。
5. CI status 不是 `passed` 或 required checks 有 failed/skipped/missing 时必须拒绝。
6. CI refs/evidence/test report/build log/artifact digest 中出现 token、api_key、password、secret 等明文敏感片段必须拒绝。
7. summary/API/UI 不能回显 raw CI log、raw artifact payload、secret 或 token。

## 红线 [按需]
- 不接真实 GitHub Actions/GitLab/CircleCI credentials，不触发外部 workflow，不下载 raw artifacts。
- 不把 CI attestation 说成 CI 已由本地跑通、线上部署成功、live deployment runner 或用户验收。
- 不绕过 local publish hard gate 或 external publication proof。

## 非目标 [按需]
不实现真实 CI provider adapter、deployment runner、cloud uploader、线上健康检查、证书链、外部账号权限系统或用户验收。

## 验收一句话 [必填]
RDP API/UI 可以在 local publication 和 external proof 后登记 refs/hash-only CI release attestation；缺 publication/proof、approval mismatch、archive mismatch、failed checks 或 secret-bearing refs 时 fail-closed。

## 完成记录（2026-06-28）
- 新增 `RDPCIReleaseAttestationRecord` 与 `PersistentRDPCIReleaseAttestationStore`，以 JSONL append-only 记录 RDP CI release attestation。
- 新增 `/api/research-os/rdp/manifests/{package_id}/ci_release_attestations`；endpoint 先查已登记 local publication、external publication proof、trust release gate 和 approved release approval，再写 CI attestation record。
- `record_attestation()` 要求 package/local/external proof/approval/archive 一致，`ci_status=passed`，required checks 非空，failed/skipped/missing checks 为空；CI refs/evidence/test report/build log/artifact digest 里的 plaintext secret/token fail-closed。
- `/api/research-os/rdp/publications` 新增 `ci_release_total` 与 `ci_release_attestations`，只回显 refs/hash/status，不回显 raw CI log、raw artifact payload、secret 或 token。
- RDP export desk 新增 CI release attestation 表单；必须先有 local publication 和 external publication proof，否则前端阻断，不打后端。
- 本地验证：
  - `python -m compileall -q app/backend/app` -> PASS。
  - `python -m pytest app/backend/tests/test_research_os_rdp_publish.py -q` -> 14 passed / 2 warnings。
  - `python -m pytest app/backend/tests/test_trust_layer.py app/backend/tests/test_research_os_rdp_publish.py app/backend/tests/test_goal_coverage.py -q` -> 66 passed / 2 warnings。
  - `cd app/frontend && npm test -- RDPExportPanel.test.tsx --run` -> 1 file / 21 tests passed。
  - `cd app/frontend && npm test -- agentWorkbench.test.tsx MethodologyValidationPanel.test.tsx RDPExportPanel.test.tsx ResearchRAGPanel.test.tsx TrustDisclosurePanel.test.tsx --run` -> 5 files / 77 tests passed。
  - `cd app/frontend && npm test -- --run` -> 30 files / 331 tests passed。
  - `cd app/frontend && npm run build` -> PASS（保留既有 Vite chunk-size warning）。
  - `python -m pytest app/backend/tests -q` -> 1870 passed / 13 skipped / 283 warnings。
  - `python dev/scripts/validate_dev.py` -> PASS（49 ✅ / 0 ❌ / 0 ⚠️；249 cards）。
  - assigned-vs-done duplicate task id check -> no output。
  - `git diff --check` -> PASS。

## 边界
这是 refs/hash-only CI release attestation 记录面，不是真实 CI provider adapter、GitHub Actions/GitLab/CircleCI 凭据接入、外部 workflow 触发、deployment runner、线上健康检查、线上发布或用户验收。
