---
uuid: 9ea22292e2b84522b04195c35e8029d0
title: RDP external publication uploader seam
status: done
owner: dreaminate
assigned_by: dreaminate
review_status: 1
priority: P1
area: research-os-rdp-external-publish
source: goal-gap
source_ref: GOAL §17 RDP external publish/release; TRACE §17 RDP residual
depends_on: [770982f3c82f41e0907956b38f767c16]
created_at: 2026-06-28
completed_at: 2026-06-28
---

# RDP external publication uploader seam

## Scope [必填]
新增 RDP external publication configurable uploader seam：在 local publication、trust release approval、archive hash 都已存在后，允许注入 uploader 产出 refs/hash-only external publication proof，并复用现有 `PersistentRDPExternalPublicationProofStore` 写 proof record。

## 上下文 / 动机 [按需]
`770982f3` 已有手工登记 external publication proof，`6ec698e4` 已有 CI release runner seam。TRACE §17 仍保留 object-store uploader / release runner 残余。直接接真实 cloud SDK 或凭据会越过 Secrets、CI、账号权限和线上发布治理。本卡只落可注入 uploader seam：默认未配置时 422，不写 partial；配置 fake/受控 uploader 时只接受 refs/hash/status/evidence 输出。

## 接线点（file:line，实现时复核）[必填]
| 文件 | 改什么 |
|---|---|
| `app/backend/app/research_os/rdp.py` | 为外部 proof store 增加从已验证 URI digest 记录 proof 的内部路径，保持手工 raw URI 路径不变 |
| `app/backend/app/main.py` | 新增 `RDP_EXTERNAL_PUBLICATION_UPLOADER`、runner request/result allowlist、`POST /external_publications/run` |
| `app/backend/tests/test_research_os_rdp_publish.py` | 覆盖默认未配置、fake uploader 成功、raw/secret/bad status 坏结果 fail-closed |
| `app/frontend/src/pages/workshop/agent-workbench/RDPExportPanel.tsx` | external publication proof 区增加 Run external publish 按钮，复用 publication/trust refs |
| `app/frontend/src/pages/workshop/agent-workbench/RDPExportPanel.test.tsx` | 覆盖 run endpoint payload、缺 local publication 前端阻断、runner 成功回显 |
| `dev/research/TRACE.md`、`dev/state/dreaminate/state.md`、`dev/log/dreaminate/log.md` | 记录已建证据、验证和边界 |

## 对抗测试设计（种已知 bug，门必抓）[必填]
1. uploader 默认未配置时 `/external_publications/run` 返回 422，proof store 不写记录。
2. fake uploader 只能收到 package id、publish hash、archive hash、release/approval refs、destination allowlist ref、source/run refs；request 不含 raw external URI、published archive path、artifact bytes、secret 或 token。
3. uploader result 只能含 `external_channel`、`external_uri_digest`、`immutable_pointer_ref`、`destination_allowlist_ref`、`publication_status`、`evidence_refs`；包含 raw URI、stdout/stderr、payload、token/secret 字段必须 422。
4. `publication_status != published`、archive hash mismatch、approval mismatch、secret-bearing refs 必须拒绝，且不写 partial proof。
5. 手工 `/external_publications` 仍保持现有 raw URI 输入和 digest-only 存储，不被 runner seam 破坏。

## 红线 [按需]
- 不接真实 object-store SDK、云账号、CI secret、signed URL 上传、网络发布或生产 release。
- 不把 uploader seam 说成真实外部上传、线上发布、CI 通过、线上健康检查或用户验收。
- 不向 runner request/result 暴露 raw artifact、raw upload payload、raw external URI、published local path、secret/token/stdout/stderr。

## 非目标 [按需]
不实现真实 S3/GCS/R2 uploader、provider credential setup、GitHub Actions workflow dispatch、deployment runner、production release、线上可用性探测或发布后 rollback。

## 验收一句话 [必填]
RDP export API/UI 可在 local publication 后运行可注入 external publication uploader seam；成功结果写入 refs/hash-only external publication proof，未配置或 raw/secret/bad-status 结果 fail-closed。

## 完成记录
- `app/backend/app/main.py` 新增 configurable `RDP_EXTERNAL_PUBLICATION_UPLOADER` 和 `/api/research-os/rdp/manifests/{package_id}/external_publications/run`；默认未配置时 422，不写 external proof。
- uploader request 只包含 package id、manifest hash、local publish hash、archive hash、trust release/approval refs、source/run refs、external channel、destination allowlist/immutable pointer/evidence refs；不传 raw external URI、published archive path 或 raw artifact。
- uploader result allowlist 只接受 `external_channel`、`external_uri_digest`、`immutable_pointer_ref`、`destination_allowlist_ref`、`publication_status`、`evidence_refs`；raw URI、stdout/stderr、payload、token/secret、plaintext secret、非标量 ref payload 和非 `published` status fail-closed。
- `app/backend/app/research_os/rdp.py` 新增 `record_proof_from_digest()`，手工 `/external_publications` 仍走 raw URI 输入并只存 digest，runner path 走已验证 digest 写同一 proof store。
- `RDPExportPanel` 新增 `Run external publish` 按钮；runner payload 不包含 `external_uri`，结果回填现有 external proof 状态。

## 验证
- `python -m compileall -q app/backend/app`：PASS。
- `python -m pytest app/backend/tests/test_research_os_rdp_publish.py -q`：26 passed / 2 warnings。
- `python -m pytest app/backend/tests/test_trust_layer.py app/backend/tests/test_research_os_rdp_publish.py app/backend/tests/test_goal_coverage.py -q`：78 passed / 2 warnings。
- `python -m pytest app/backend/tests -q`：1885 passed / 13 skipped / 283 warnings。
- `cd app/frontend && npm test -- RDPExportPanel.test.tsx --run`：1 file / 24 tests passed。
- `cd app/frontend && npm test -- --run`：30 files / 336 tests passed。
- `cd app/frontend && npm run build`：PASS（保留既有 Vite chunk-size warning）。
- `python dev/scripts/validate_dev.py`：PASS（49 ✅ / 0 ❌ / 0 ⚠️；254 cards）。
- assigned-vs-done duplicate task id check：no output。
- `git diff --check`：PASS。

## 边界
这是本地 configurable uploader seam 和 fake-uploader 验证，不是真实 S3/GCS/R2 credential adapter、云端实际上传、CI release、deployment runner、线上发布、线上健康检查或用户验收。
