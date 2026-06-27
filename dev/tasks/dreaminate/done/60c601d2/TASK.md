---
uuid: 60c601d2a11d4383b901f8ff1e1142f8
title: RDP deployment proof UI wiring
status: done
owner: dreaminate
assigned_by: dreaminate
review_status: 1
priority: P1
area: research-os-rdp-deployment-ui
source: goal-gap
source_ref: GOAL §17 Deployment / monitor / rollback / retire checklist; TRACE §17 RDP deployment proof surfaces
depends_on: [378bb0b9d1db4b2aa1195ed3d19a3f42]
created_at: 2026-06-28
completed_at: 2026-06-28
---

# RDP deployment proof UI wiring

## Scope [必填]
把 RDP export desk 接到已存在的 deployment attestation、deployment runner 和 deployment health/rollback proof APIs，让用户能从前端记录或运行 deployment proof，并登记 post-deploy health/rollback refs。

## 上下文 / 动机 [按需]
`bf94fd9d` 已新增 deployment runner seam/API，`378bb0b9` 已新增 deployment health/rollback proof registry/API，但 RDP export desk 还没有操作入口。GOAL §17 的交付链需要用户可见、可操作的 Deployment / monitor / rollback / retire 清单记录面。

## 接线点（file:line，实现时复核）[必填]
| 文件 | 改什么 |
|---|---|
| `app/frontend/src/pages/workshop/agent-workbench/RDPExportPanel.tsx` | 新增 deployment attestation / runner / health proof draft、按钮、结果展示 |
| `app/frontend/src/pages/workshop/agent-workbench/RDPExportPanel.test.tsx` | 覆盖 run payload、health proof payload、缺上游 attestation 前端阻断、runner 不提交 raw payload |
| `dev/research/TRACE.md`、`dev/state/dreaminate/state.md`、`dev/log/dreaminate/log.md` | 记录 UI 接线、验证和边界 |

## 对抗测试设计（种已知 bug，门必抓）[必填]
1. 点击 `Run deployment` 时 payload 只含 refs/status 配置，不含 raw deployment payload、本地 package path、kubeconfig、SSH key、token 或 secret。
2. 未有 deployment attestation 时点击 `Record health proof` 前端阻断，且不打 `/deployment_health_checks`。
3. health proof payload 必须包含 deployment attestation hash、health refs、monitor refs、rollback plan/readiness/drill refs、retire plan ref 和 evidence refs。
4. 缺 health/monitor/rollback/retire/evidence refs 时前端阻断，避免发空壳 proof。

## 红线 [按需]
- 不在前端收集云凭据、kubeconfig、SSH key、token、raw health response、raw deployment payload 或日志。
- 不把 UI 按钮说成真实 deployment provider、真实线上健康检查或 rollback execution。

## 非目标 [按需]
不实现真实 deployment provider、真实 monitor/canary、rollback execution、production rollout、线上验收或 backend 新语义。

## 验收一句话 [必填]
RDP export desk 可记录/运行 deployment attestation，并可基于 attestation hash 记录 refs-only health/rollback proof；缺上游或空 refs 时前端不打后端。

## 完成记录
- `RDPExportPanel` 新增 deployment proof 区：`Record deployment` 调 `/deployment_attestations`，`Run deployment` 调 `/deployment_attestations/run`，`Record health proof` 调 `/deployment_health_checks`。
- deployment runner payload 只提交 `deployment_ref` 与 `source_bundle_required`，不提交 raw deployment payload、package path、kubeconfig、SSH key、token 或 secret。
- health proof payload 使用当前 deployment attestation hash，并提交 health refs、monitor refs、rollback plan/readiness/drill refs、retire plan ref 与 evidence refs。
- 前端会在缺 deployment attestation、缺 health refs、缺 monitor refs、缺 rollback/retire/evidence refs 时阻断，不打 health proof 后端。
- 结果面新增 deployment attestation hash、deployment event/artifact digest、deployment health proof hash、health status、rollback drill ref 与 retire plan ref。

## 验证
- `cd app/frontend && npm test -- RDPExportPanel.test.tsx --run`：1 file / 26 tests passed。
- `cd app/frontend && npm test -- --run`：30 files / 338 tests passed。
- `cd app/frontend && npm run build`：PASS（保留既有 Vite chunk-size warning）。

## 边界
这是 RDP export desk 的本地 UI 接线，不是真实 deployment provider、真实线上健康检查、real canary、rollback execution、production rollout、线上发布或用户验收。
