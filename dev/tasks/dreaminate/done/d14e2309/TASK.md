---
uuid: d14e23097b7f45e99209c382710b620d
title: RDP publish source-run and live deployment attestation gate
status: done
owner: dreaminate
assigned_by: dreaminate
review_status: 0
priority: P1
area: research-os-rdp
source: goal-gap
source_ref: GOAL §13 trust layer release gate; GOAL §17 Research Delivery Package publish standard
depends_on: [31ccd0028ff4446b9508e9b30f0ea7d9, d5f0ff4114314ca0a1afb1d1ee243bdb, e9c58149730a40109bc11eea5758f108, 31870f62e76940199bc06a23328e1a69]
completed_at: 2026-06-27
---

# RDP publish source-run and live deployment attestation gate

## Scope [必填]
让 RDP local publish 在 trust release gate 之外，还必须确认已登记 source-run integrity；live RDP publish 还必须确认 deployment attestation 覆盖声明的 deployment refs。

## 上下文 / 动机 [按需]
`31ccd002` 已有 source-to-run integrity attestation，`d5f0ff41` 已有 deployment attestation，`e9c58149` 已让 publish 要求 trust release gate，`31870f62` 已让 manifest 要求 upstream compiler/math/coverage refs。剩余缺口是 publish 终端动作可以只凭 archive + trust gate 发布，未强制要求 source bundle 已经和 run artifacts 绑定。

## 接线点（file:line，实现时复核）[必填]
| 文件 | 改什么 |
|---|---|
| `app/backend/app/main.py` | `/api/research-os/rdp/manifests/{package_id}/publish` 在 archive export 后、copy publish 前检查 source-run integrity；live runtime 额外检查 deployment attestation |
| `app/backend/tests/test_research_os_rdp_publish.py` | publish 成功路径先登记 source-run integrity；缺 source-run integrity 422 no-write；external channel test 先满足 integrity 后仍被 channel gate 拒绝 |
| `app/frontend/src/pages/workshop/agent-workbench/RDPExportPanel.tsx` | local publish 前端前置检查 source-run integrity，避免明知后端会拒还发 publish 请求 |
| `app/frontend/src/pages/workshop/agent-workbench/RDPExportPanel.test.tsx` | 覆盖缺 source-run integrity 时不调用 publish endpoint |
| `dev/state/dreaminate/state.md` / `dev/research/TRACE.md` / `dev/log/dreaminate/log.md` | 落档 publish 终端 gate 和剩余边界 |

## 对抗测试设计（种已知 bug，门必抓）[必填]
1. API publish 在 source bundle 和 trust gate 都存在但 source-run integrity 缺失时必须 422，且不写 publication。
2. 成功 publish 必须先有 matching manifest hash + artifact hash 的 source-run integrity record。
3. external channel 拒绝仍保留，不因新增 source-run gate 掩盖 channel gate。
4. live manifest publish 必须能被 deployment attestation gate 拦住缺 deployment attestation 的状态。

## 红线 [按需]
- 不把 archive export 成功等同于 source-run integrity。
- 不把 trust release gate 成功等同于源代码/运行产物一致性。
- 不声称外部 publish、CI、线上或 live deployment 已验证。

## 非目标 [按需]
不实现外部 object-store publish、live deployment runner、release gate 管理 UI、自动生成 source-run integrity、真实 provider/broker attestation。

## 验收一句话 [必填]
RDP local publish 现在必须先有 source-run integrity attestation；live publish 还必须先有 deployment attestation 覆盖声明 deployment refs。

## 完成记录
- 新增 `_validate_rdp_publish_attestations()`，按 manifest hash + artifact hash 校验 source-run integrity 覆盖 `run_refs`。
- live runtime publish 额外校验 deployment attestation 覆盖 manifest `deployment_refs`。
- publish API 在 archive export 后、copy publish 前执行 attestation gate；失败不写 publication。
- `RDPExportPanel` 在有 source refs 且未完成 source-run integrity 时阻断 local publish 请求并显示错误。
- 验证：`pytest app/backend/tests/test_research_os_rdp_publish.py -q` -> **8 passed / 2 warnings**；`npm test -- --run src/pages/workshop/agent-workbench/RDPExportPanel.test.tsx` -> **1 file / 7 tests passed**；`npm run build` -> **PASS**（保留既有 chunk-size warning）。
