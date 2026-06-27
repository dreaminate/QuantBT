---
uuid: 378bb0b9d1db4b2aa1195ed3d19a3f42
title: RDP deployment health and rollback proof registry
status: done
owner: dreaminate
assigned_by: dreaminate
review_status: 1
priority: P1
area: research-os-rdp-deployment-health
source: goal-gap
source_ref: GOAL §17 Deployment / monitor / rollback / retire checklist; TRACE §17 online health and rollback proof residual
depends_on: [bf94fd9d84e8412384d6a45a3810bf4f]
created_at: 2026-06-28
completed_at: 2026-06-28
---

# RDP deployment health and rollback proof registry

## Scope [必填]
新增 RDP post-deployment health/rollback proof append-only registry/API：在 deployment attestation 已存在后，记录 refs/hash-only health check、monitor、rollback readiness、rollback drill、retire plan 证明，并让坏状态 fail-closed 不写 partial record。

## 上下文 / 动机 [按需]
`bf94fd9d` 已有 configurable deployment runner seam，但 GOAL §17 明确要求交付物包含 Deployment / monitor / rollback / retire 清单。当前 deployment attestation 只能证明 deployment ref 被登记，不能单独证明 post-deploy health、rollback readiness 或 retire plan evidence。直接做真实线上探活/rollback 会越过外部平台凭据和生产变更治理。本卡只落本地 refs/hash-only proof registry。

## 接线点（file:line，实现时复核）[必填]
| 文件 | 改什么 |
|---|---|
| `app/backend/app/research_os/rdp.py` | 新增 `RDPDeploymentHealthCheckRecord` 与 persistent registry，绑定 deployment attestation hash、monitor/rollback/retire refs |
| `app/backend/app/main.py` | 新增 store、response helper、`POST /deployment_health_checks` endpoint |
| `app/backend/tests/test_research_os_rdp_deployment_attestation.py` | 覆盖成功记录、缺/unknown deployment attestation、unhealthy/bad rollback/raw secret fail-closed |
| `dev/research/TRACE.md`、`dev/state/dreaminate/state.md`、`dev/log/dreaminate/log.md` | 记录已建证据、验证和边界 |

## 对抗测试设计（种已知 bug，门必抓）[必填]
1. 缺 `deployment_attestation_hash`、unknown hash 或 hash 不属于 package 时 422，health registry 不写记录。
2. `health_status != healthy`、缺 health check refs、缺 monitor refs、缺 rollback readiness / drill / retire plan refs 均 422。
3. health/rollback/evidence refs 带 token/secret/password、raw response/log/payload 字段或 plaintext secret marker 时 422，且不写 partial record。
4. deployment attestation 的 `deployment_ref` 必须匹配 payload/manifest，mismatch 422。
5. 成功记录只保存 refs/hash/status/evidence，不保存 raw health response、raw logs、provider payload、token 或 secret。

## 红线 [按需]
- 不接真实 Vercel/Fly/Render/Kubernetes/SSH health API、prod traffic probe、rollback execution、canary 或外部 monitor。
- 不把本地 health/rollback proof record 说成真实线上健康检查、真实 rollback 可执行、线上发布或用户验收。

## 非目标 [按需]
不实现真实 post-deploy monitor、real canary、rollback execution、production rollout、provider credential adapter、CI 或线上验收。

## 验收一句话 [必填]
RDP API 可在 deployment attestation 后记录 refs/hash-only deployment health/rollback proof；缺上游 attestation、bad health、bad rollback 或 raw/secret payload 均 fail-closed。

## 完成记录
- `app/backend/app/research_os/rdp.py` 新增 `RDPDeploymentHealthCheckRecord` 与 `PersistentRDPDeploymentHealthCheckStore`，JSONL append-only/replay，记录 `deployment_attestation_hash`、health refs、monitor refs、rollback plan/readiness/drill refs、retire plan ref 和 evidence refs。
- `app/backend/app/main.py` 新增 `RDP_DEPLOYMENT_HEALTH_CHECK_STORE` 与 `POST /api/research-os/rdp/manifests/{package_id}/deployment_health_checks`；endpoint 先查 manifest 和已登记 deployment attestation，再写 health proof。
- API payload allowlist 只接受 refs/hash/status/evidence 字段；`raw_health_response`、raw log、provider payload、kubeconfig、SSH key、stdout/stderr、token/secret、plaintext secret 和非标量 ref payload fail-closed。
- `health_status` 必须是 `healthy`；`health_check_refs`、`monitor_refs`、`rollback_plan_ref`、`rollback_readiness_ref`、`rollback_drill_ref`、`retire_plan_ref`、`evidence_refs` 都必须存在，并且 monitor/rollback/retire refs 必须覆盖或匹配 manifest。
- 缺 `deployment_attestation_hash`、unknown hash、hash 不属于 package、deployment ref mismatch、bad health、bad rollback 或 raw/secret payload 均 422，不写 partial record。

## 验证
- `python -m compileall -q app/backend/app`：PASS。
- `python -m pytest app/backend/tests/test_research_os_rdp_deployment_attestation.py -q`：22 passed / 2 warnings。
- `python -m pytest app/backend/tests/test_research_os_rdp.py app/backend/tests/test_research_os_rdp_persistence.py app/backend/tests/test_research_os_rdp_materializer.py app/backend/tests/test_research_os_rdp_source_bundle.py app/backend/tests/test_research_os_rdp_deployment_attestation.py app/backend/tests/test_research_os_rdp_archive_export.py app/backend/tests/test_research_os_rdp_source_run_integrity.py app/backend/tests/test_research_os_rdp_publish.py app/backend/tests/test_goal_coverage.py -q`：106 passed / 2 warnings。
- `python -m pytest app/backend/tests -q`：1900 passed / 13 skipped / 283 warnings。

## 边界
这是本地 refs/hash-only deployment health/rollback proof registry，不是真实 Vercel/Fly/Render/Kubernetes/SSH health API、prod traffic probe、real canary、rollback execution、production rollout、线上发布或用户验收。
