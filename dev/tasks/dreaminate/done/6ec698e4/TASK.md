---
uuid: 6ec698e44ac348ab9ba35c2e0bfbbd1f
title: RDP CI release runner seam
status: done
owner: dreaminate
assigned_by: dreaminate
review_status: 1
priority: P1
area: research-os-rdp-ci-release-runner
source: goal
source_ref: GOAL §17 RDP release proof; TRACE §17 CI provider adapter/external workflow trigger residual
depends_on: [b793f3a7f0214db1829a5ea430fcabee]
completed_at: 2026-06-28
---

# RDP CI release runner seam

## Scope [必填]
新增 RDP CI release runner 接缝：在 local publication 和 external publication proof 已存在后，可由配置的后端 runner 触发/收集 CI refs/hash 并复用既有 CI release attestation store 记录；不接真实 CI 凭据、不下载 raw artifact、不把未配置 runner 说成已跑 CI。

## 上下文 / 动机 [按需]
`b793f3a7` 已落 refs/hash-only CI release attestation 记录面，但 TRACE §17 仍把真实 CI provider adapter / external workflow trigger 列为残余。直接接 GitHub/GitLab/CircleCI 密钥需要外部账号、Secrets 和部署权限。本卡先落 provider adapter 的 fail-closed seam：默认未配置时拒绝且不写记录；测试中用 fake runner 证明接缝能把 runner 返回的 refs/hash 变成同一类 attestation，并拒绝 raw log、secret、failed/skipped/missing checks。

## 接线点（file:line，实现时复核）[必填]
| 文件 | 位置 | 改什么(扩展不替换) |
|---|---|---|
| `app/backend/app/main.py` | RDP CI attestation endpoint 附近 | 增加 configurable `RDP_CI_RELEASE_RUNNER`、runner result sanitizer 和 `/ci_release_attestations/run` endpoint |
| `app/backend/tests/test_research_os_rdp_publish.py` | CI release attestation tests 附近 | 覆盖 runner 未配置不写、fake runner 成功、runner raw/secret/failed/skipped/missing 结果拒绝 |
| `app/frontend/src/pages/workshop/agent-workbench/RDPExportPanel.tsx` | CI release attestation 表单 | 增加 run seam 按钮，复用当前 publication/external proof 和 CI draft，调用 `/ci_release_attestations/run` |
| `app/frontend/src/pages/workshop/agent-workbench/RDPExportPanel.test.tsx` | RDP export CI tests 附近 | 覆盖 run seam payload、缺 external proof 前端阻断、结果回显 |
| `dev/research/TRACE.md` | §17 行 | 收窄残余：记录 provider adapter seam 已建，真实 provider/外部 workflow 仍未接 |
| `dev/state/dreaminate/state.md`、`dev/log/dreaminate/log.md` | 最新进度 | 落本地验证和边界 |

## 对抗测试设计（种已知 bug，门必抓）[必填]
1. 未配置 runner：调用 `/run` → 422，`RDP_CI_RELEASE_ATTESTATION_STORE` 不新增记录。
2. Fake runner 成功：返回 passed refs/hash → endpoint 调同一 store 写 `RDPCIReleaseAttestationRecord`，summary 不回显 raw payload。
3. Runner 泄露 raw log/artifact：返回 `raw_ci_log` 或 `raw_artifact_payload` → 422 且不写 partial record。
4. Runner 返回 secret/token：任一 refs/hash/evidence 中含 token/api_key/password/secret → 422 且不写 partial record。
5. Runner 失败状态：`ci_status != passed` 或 failed/skipped/missing checks 非空 → 422 且不写 partial record。

## 复用 [按需]
复用 `PersistentRDPCIReleaseAttestationStore.record_attestation()` 的 publication/external proof/approval/archive/check/secret gates；runner endpoint 只负责触发/收集 refs/hash 和 sanitize，不另造第二套 CI release record。

## 红线 [按需]
- 不让 CI provider token、OAuth token、device code token、raw CI log、raw artifact payload 进入 LLM/RAG/log/export。
- 不绕过 local publish hard gate、external publication proof、trust release approval gate。

## 非目标 [按需]
不实现真实 GitHub Actions/GitLab/CircleCI credential adapter、外部 workflow trigger、object-store uploader、deployment runner、线上健康检查、线上发布或用户验收。

## 验收一句话 [必填]
RDP API/UI 可以通过配置的 runner seam 生成同一类 CI release attestation；runner 未配置、缺 publication/proof、返回 raw/secret payload 或失败 checks 时 fail-closed 且不写记录。

## 完成记录（2026-06-28）
- 新增 configurable `RDP_CI_RELEASE_RUNNER`，默认 `None`；`POST /api/research-os/rdp/manifests/{package_id}/ci_release_attestations/run` 在未配置 runner 时返回 422，且不写 CI attestation record。
- 新 endpoint 先查真实 manifest、local publication hash、external proof hash、trust release gate 和 approved release approval，再把 refs/hash-only request 交给 runner。
- runner result 必须是 allowlisted refs/hash/status/check/evidence dict；`raw_ci_log`、`artifact_payload`、`stdout/stderr`、token/secret key、plaintext secret、非标量 ref payload 均 422。
- runner 成功结果复用 `PersistentRDPCIReleaseAttestationStore.record_attestation()` 写同一类 `RDPCIReleaseAttestationRecord`，不新增第二套 CI release record。
- RDP export desk 新增 `Run CI` 按钮；手工 `Record CI attestation` 仍要求完整 CI refs/hash，`Run CI` 只要求 runner request 所需的 system/workflow/source commit/check/evidence refs，允许 runner 产物字段先为空。
- 本地验证：
  - `python -m compileall -q app/backend/app` -> PASS。
  - `python -m pytest app/backend/tests/test_research_os_rdp_publish.py -q` -> 20 passed / 2 warnings。
  - `python -m pytest app/backend/tests/test_trust_layer.py app/backend/tests/test_research_os_rdp_publish.py app/backend/tests/test_goal_coverage.py -q` -> 72 passed / 2 warnings。
  - `cd app/frontend && npm test -- RDPExportPanel.test.tsx --run` -> 1 file / 22 tests passed。
  - `cd app/frontend && npm test -- agentWorkbench.test.tsx MethodologyValidationPanel.test.tsx RDPExportPanel.test.tsx ResearchRAGPanel.test.tsx TrustDisclosurePanel.test.tsx --run` -> 5 files / 77 tests passed。
  - `cd app/frontend && npm test -- --run` -> 30 files / 332 tests passed。
  - `cd app/frontend && npm run build` -> PASS（保留既有 Vite chunk-size warning）。
  - `python -m pytest app/backend/tests -q` -> 1876 passed / 13 skipped / 283 warnings。
  - `python dev/scripts/validate_dev.py` -> PASS（49 ✅ / 0 ❌ / 0 ⚠️；250 cards）。
  - assigned-vs-done duplicate task id check -> no output。
  - `git diff --check` -> PASS。

## 边界
这是本地 configurable runner seam 和 fake-runner 验证，不是真实 GitHub Actions/GitLab/CircleCI credential adapter、真实外部 workflow execution、object-store uploader、deployment runner、线上发布、线上健康检查或用户验收。
