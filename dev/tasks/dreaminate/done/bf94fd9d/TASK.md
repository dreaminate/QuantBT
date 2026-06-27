---
uuid: bf94fd9d84e8412384d6a45a3810bf4f
title: RDP deployment runner seam
status: done
owner: dreaminate
assigned_by: dreaminate
review_status: 1
priority: P1
area: research-os-rdp-deployment
source: goal-gap
source_ref: GOAL §17 RDP live deployment runner residual; TRACE §17 live deployment runner residual
depends_on: [d5f0ff4114314ca0a1afb1d1ee243bdb]
created_at: 2026-06-28
completed_at: 2026-06-28
---

# RDP deployment runner seam

## Scope [必填]
新增 RDP deployment configurable runner seam：对已物化并完成 source bundle 的 live RDP package，允许注入 deployment runner 产出 refs/hash-only 部署证明，然后复用现有 `PersistentRDPDeploymentAttestationStore` 写 deployment attestation record。

## 上下文 / 动机 [按需]
`d5f0ff41` 已有手工 deployment attestation record，`d14e2309` 已让 live publish 要求 deployment attestation 覆盖 `deployment_refs`。TRACE §17 仍保留 live deployment runner 残余。直接接真实 Vercel/Fly/Kubernetes/SSH 或云凭据会越过 Secrets、CI、审批和线上变更治理。本卡只落可注入 runner seam：默认未配置时 422，不写 partial；配置 fake/受控 runner 时只接受 refs/hash/status/evidence 输出。

## 接线点（file:line，实现时复核）[必填]
| 文件 | 改什么 |
|---|---|
| `app/backend/app/main.py` | 新增 `RDP_DEPLOYMENT_RUNNER`、runner request/result allowlist、`POST /deployment_attestations/run` |
| `app/backend/tests/test_research_os_rdp_deployment_attestation.py` | 覆盖默认未配置、fake runner 成功、raw/secret/bad status 坏结果 fail-closed |
| `dev/research/TRACE.md`、`dev/state/dreaminate/state.md`、`dev/log/dreaminate/log.md` | 记录已建证据、验证和边界 |

## 对抗测试设计（种已知 bug，门必抓）[必填]
1. runner 默认未配置时 `/deployment_attestations/run` 返回 422，deployment attestation store 不写记录。
2. fake runner request 只能收到 package id、manifest hash、deployment ref、target runtime、approval/monitor/rollback/retire refs、source file refs、run refs；不含 raw deploy payload、kubeconfig、SSH key、token、stdout/stderr 或本地 package path。
3. runner result 只能含 `deployment_ref`、`deployment_status`、`deployment_event_ref`、`deployment_artifact_digest`、`monitor_refs`、`rollback_plan_ref`、`retire_plan_ref`、`evidence_refs`；包含 raw manifest/package payload、stdout/stderr、token/secret 字段必须 422。
4. `deployment_status != deployed`、deployment ref mismatch、secret-bearing refs 必须拒绝，且不写 partial attestation。
5. 手工 `/deployment_attestations` 保持现有一致性证明路径，不被 runner seam 破坏。

## 红线 [按需]
- 不接真实部署平台 SDK、Kubernetes/SSH、云账号、CI secret、生产 release 或线上流量切换。
- 不把 deployment runner seam 说成真实线上部署、线上健康检查、rollback 可用、CI 通过或用户验收。
- 不向 runner request/result 暴露 raw package、raw deployment payload、kubeconfig、SSH key、secret/token/stdout/stderr。

## 非目标 [按需]
不实现真实 Vercel/Fly/Render/Kubernetes/SSH runner、provider credential setup、production rollout、health check、rollback execution、canary 或线上验收。

## 验收一句话 [必填]
RDP deployment API 可运行可注入 deployment runner seam；成功结果写入现有 deployment attestation，未配置或 raw/secret/bad-status 结果 fail-closed。

## 完成记录
- `app/backend/app/main.py` 新增 configurable `RDP_DEPLOYMENT_RUNNER` 和 `/api/research-os/rdp/manifests/{package_id}/deployment_attestations/run`；默认未配置 runner 时 422，且不写 deployment attestation record。
- runner request 只包含 package id、manifest hash、deployment ref、target runtime、approval/monitor/rollback/retire refs、source file refs 和 source-run refs；不传 raw deploy payload、本地 package path、kubeconfig、SSH key、token、stdout/stderr 或 secret。
- runner result allowlist 只接受 `deployment_ref`、`deployment_status`、`deployment_event_ref`、`deployment_artifact_digest`、`monitor_refs`、`rollback_plan_ref`、`retire_plan_ref`、`evidence_refs`；raw manifest/package payload、stdout/stderr、token/secret、plaintext secret、非标量 ref payload 和非 `deployed` status fail-closed。
- `app/backend/app/research_os/rdp.py` 扩展 `RDPDeploymentAttestationRecord` 与 store：保留 v1 hash/replay 兼容；runner 产出的 deployment event/artifact/evidence refs 写 v2 attestation。
- 手工 `/deployment_attestations` 仍走原有一致性证明路径；runner seam 只负责受控 runner 调用和结果净化，不替代真实 deployment provider。

## 验证
- `python -m compileall -q app/backend/app`：PASS。
- `python -m pytest app/backend/tests/test_research_os_rdp_deployment_attestation.py -q`：14 passed / 2 warnings。
- `python -m pytest app/backend/tests/test_research_os_rdp.py app/backend/tests/test_research_os_rdp_persistence.py app/backend/tests/test_research_os_rdp_materializer.py app/backend/tests/test_research_os_rdp_source_bundle.py app/backend/tests/test_research_os_rdp_deployment_attestation.py app/backend/tests/test_research_os_rdp_archive_export.py app/backend/tests/test_research_os_rdp_source_run_integrity.py app/backend/tests/test_research_os_rdp_publish.py app/backend/tests/test_goal_coverage.py -q`：98 passed / 2 warnings。
- `python -m pytest app/backend/tests -q`：1892 passed / 13 skipped / 283 warnings。

## 边界
这是本地 configurable deployment runner seam 和 fake-runner 验证，不是真实 Vercel/Fly/Render/Kubernetes/SSH credential adapter、production rollout、线上健康检查、rollback 执行、线上发布或用户验收。
