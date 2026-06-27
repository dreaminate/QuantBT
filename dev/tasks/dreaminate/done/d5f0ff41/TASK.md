---
uuid: d5f0ff4114314ca0a1afb1d1ee243bdb
title: RDP deployment attestation——交付包部署清单一致性证明
status: done
owner: dreaminate
assigned_by: dreaminate
review_status: 1
priority: P1
area: research-os-rdp
source: goal-gap
source_ref: GOAL §17 / TRACE §17 · deployment attestation residual after b1fdff40
depends_on: [b1fdff40b8af4ef586e3d3ded73f7c3f]
---

# RDP deployment attestation

## Scope [必填]
RDP 已有 manifest registry、open materializer 和 source-file content bundle。本卡补第一版 **deployment attestation record**：对已物化包做只读核验并写 append-only audit record，证明当前 `manifest.json`、`refs.json`、可选 `source_files_index.json` 与已登记 manifest / deployment refs / monitor refs / rollback / retire 清单一致。

安全边界：本卡不发布、不部署、不下单、不调用外部服务、不生成 live package publish。它只记录交付包准备进入部署/发布流程前的本地一致性证明。live manifest 仍必须已有 approval/deployment/monitor/rollback/retire refs；source refs 存在时默认要求 source bundle index 已存在。

## 接线点（file:line，实现时复核）[必填]
| 文件 | 位置 | 改什么 |
|---|---|---|
| app/backend/app/research_os/rdp.py | RDP source bundle 后 | 新增 `RDPDeploymentAttestationRecord` / `PersistentRDPDeploymentAttestationStore`，核验 manifest/refs/source bundle/package hash |
| app/backend/app/main.py | RDP API 区 | 新增 `RDP_DEPLOYMENT_ATTESTATION_STORE` 和 `/api/research-os/rdp/manifests/{package_id}/deployment_attestations` |
| app/backend/app/research_os/__init__.py | exports | 导出新 attestation 类型 |
| app/backend/tests/test_research_os_rdp_deployment_attestation.py | 新测试 | 对抗测试 package tamper、missing source bundle、bad deployment ref、API |

## 对抗测试设计（种已知 bug，门必抓）[必填]
1. live manifest + materialized package + source bundle + matching deployment_ref → 写 attestation JSONL，可 restart replay。
2. manifest 有 source refs 但缺 `source_files_index.json` → 默认拒。
3. `deployment_ref` 不在 manifest.deployment_refs → 拒。
4. `manifest.json` 被篡改或 package 未 materialize → 拒。
5. API unknown package 404；invalid attestation 422 且不落盘。

## 验收一句话 [必填]
RDP deployment attestation 能对本地 open package、source bundle 和 live deployment 清单做 append-only 一致性证明；篡改、缺 source bundle、错误 deployment ref、未知 package 全 fail-closed；不做 live publish。
