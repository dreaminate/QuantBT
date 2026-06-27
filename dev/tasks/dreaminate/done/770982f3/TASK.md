---
uuid: 770982f3c82f41e0907956b38f767c16
title: RDP external publish attestation proof
status: done
owner: dreaminate
assigned_by: dreaminate
review_status: 1
priority: P1
area: research-os-rdp-external-publish
source: goal-gap
source_ref: GOAL §17 RDP external publish/release; GOAL §13 Trust release approval hard gate
depends_on: [44ca5ea7d0a342a8ab5583bb0ac87e5b]
created_at: 2026-06-27
completed_at: 2026-06-27
---

# RDP external publish attestation proof

## Scope [必填]
新增 RDP external publish attestation/proof runtime：在 local publish 已通过 trust release gate + approved release approval + source-run integrity 后，允许登记一个外部 object-store/release 证明 record。record 必须绑定已存在 local publication hash、archive sha256、external URI digest、release approval ref、publisher identity、destination allowlist 和 immutable pointer refs；记录只保存 refs/hash，不保存 secret、token、signed URL 或 raw upload payload。

## 上下文 / 动机 [按需]
`44ca5ea7` 已把 local publish 接成 trust release approval hard gate，但 TRACE §13/§17 仍明确残留 external publish/release。直接接真实云凭据会越过 Secrets/CI/账号治理边界。本卡先落 refs-only external publish proof：外部发布动作可由 CI/人工/受控系统完成，QuantBT 只接受可验证证明并拒绝伪外部、缺本地 publication、缺 approval 或 secret-bearing pointer。

## 接线点（file:line，实现时复核）[必填]
| 文件 | 改什么 |
|---|---|
| `app/backend/app/research_os/rdp.py` | 新增 `RDPExternalPublicationProofRecord`、validator、JSONL-backed store |
| `app/backend/app/research_os/__init__.py` | 导出新 record/store/validator |
| `app/backend/app/main.py` | 新增 external publication proof registry、`POST /api/research-os/rdp/manifests/{package_id}/external_publications`、list 回显 |
| `app/backend/tests/test_research_os_rdp_publish.py` | 覆盖成功记录、缺 local publication、archive hash mismatch、secret URI、unknown approval/ref mismatch 坏门 |
| `app/frontend/src/pages/workshop/agent-workbench/RDPExportPanel.tsx` | RDP export desk 展示/录入 external publication proof，使用当前 local publication/trust approval refs |
| `app/frontend/src/pages/workshop/agent-workbench/RDPExportPanel.test.tsx` | 覆盖 external proof payload、缺 local publication 前端阻断、结果回显 |

## 对抗测试设计（种已知 bug，门必抓）[必填]
1. 没有 local publication hash 时不能登记 external proof。
2. unknown local publication hash 或 package mismatch 必须 422，且不写 record。
3. archive sha256 与 local publication 不一致必须 422。
4. external URI / immutable pointer / evidence refs 带 token、api_key、password、secret 等明文敏感片段必须拒绝。
5. `trust_release_approval_ref` 必须等于 local publication 的 approved approval ref。
6. external proof list/API/UI 必须回显 proof hash 与 external target，但不能回显 raw secret 或 token。

## 红线 [按需]
- 不接真实 cloud/object-store SDK、CI secret、signed URL 上传、网络发布或生产 release。
- 不把 external proof 说成线上生效、CI 通过或用户验收。
- 不绕过 local publish hard gate；external proof 只能引用已存在 local publication。

## 非目标 [按需]
不实现真实 object-store uploader、CI workflow、生产发布 runner、外部账号权限系统或线上可用性探测。

## 验收一句话 [必填]
RDP export desk 和 API 可以在 local publication 之后登记 refs-only external publication proof；缺 local publication、hash mismatch、approval mismatch 或 secret-bearing pointer 时 fail-closed。

## 完成记录（2026-06-27）
- 新增 `RDPExternalPublicationProofRecord` 与 `PersistentRDPExternalPublicationProofStore`，以 JSONL append-only 记录 external publish proof；record 只保存 external URI digest、immutable pointer ref、destination allowlist ref、local publish hash、archive hash、release/approval refs 和 evidence refs，不保存 raw external URI。
- 新增 `/api/research-os/rdp/manifests/{package_id}/external_publications`；必须引用已存在 local publication hash，并重新校验 trust release gate、approved release approval、archive hash 和 secret-free external pointer。
- `/api/research-os/rdp/publications` 回显 `external_total` 与 `external_publications`。
- RDP export desk 新增 external publication proof 表单；没有 local publication 时前端阻断，不打后端。
- 本地验证：
  - `python -m compileall -q app/backend/app` -> PASS。
  - `python -m pytest app/backend/tests/test_research_os_rdp_publish.py -q` -> 11 passed / 2 warnings。
  - `python -m pytest app/backend/tests/test_trust_layer.py app/backend/tests/test_research_os_rdp_publish.py app/backend/tests/test_goal_coverage.py -q` -> 60 passed / 2 warnings。
  - `cd app/frontend && npm test -- RDPExportPanel.test.tsx --run` -> 1 file / 20 tests passed。
  - `cd app/frontend && npm test -- agentWorkbench.test.tsx MethodologyValidationPanel.test.tsx RDPExportPanel.test.tsx ResearchRAGPanel.test.tsx TrustDisclosurePanel.test.tsx --run` -> 5 files / 75 tests passed。
  - `cd app/frontend && npm test -- --run` -> 30 files / 329 tests passed。
  - `cd app/frontend && npm run build` -> PASS（保留既有 Vite chunk-size warning）。
  - `python -m pytest app/backend/tests -q` -> 1864 passed / 13 skipped / 283 warnings。
  - `python dev/scripts/validate_dev.py` -> PASS（49 ✅ / 0 ❌ / 0 ⚠️；247 cards）。
  - assigned-vs-done duplicate task id check -> no output。
  - `git diff --check` -> PASS。

## 边界
这是 refs-only external publication proof，不是真实 object-store 上传、CI release、线上发布、线上可用性证明或用户验收。
