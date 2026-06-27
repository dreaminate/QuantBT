---
uuid: 7e101b36cdf54d749171f9860a161e46
title: RDP local package publish registry——本机交付包发布账本/API/UI
status: done
owner: dreaminate
assigned_by: dreaminate
review_status: 1
priority: P1
area: research-os-rdp
source: goal-gap
source_ref: dev/GOAL.md §17 + dev/state/dreaminate/state.md Research Delivery Package live package publish gap
depends_on: [db7730220c2d4efe9b291b054f602652]
---

# RDP local package publish registry

## Scope [必填]
为 RDP open package 增加本机 publish registry：只有已经通过 archive export guard 的 package 才能发布到本地 `published` registry，并写 append-only publish audit；前端 RDP.zip 面板增加 publish 按钮和结果展示。

## 上下文 / 动机 [按需]
后端已有 manifest registry、materialize、source bundle、deployment/source-run attestation、archive export 和前端导出 UI；state 仍记录 live package publish 未实现。当前没有对象存储/公网目标配置，因此本卡只实现本机 registry publish，不声称外部发布或生产部署。

## 接线点（file:line，实现时复核）[必填]
| 文件 | 位置 | 改什么(扩展不替换) |
|---|---|---|
| `app/backend/app/research_os/rdp.py` | RDP archive/publish helpers | 新增 publish record、local publisher、append-only store |
| `app/backend/app/main.py` | RDP endpoints | 新增 `POST /api/research-os/rdp/manifests/{package_id}/publish` 和 publish summary |
| `app/backend/app/research_os/__init__.py` | exports | 导出 publish types/store |
| `app/backend/tests/test_research_os_rdp_publish.py` | 新测试 | 覆盖 local publish 成功、缺 archive prerequisites、channel guard、restart replay、API 404/422 |
| `app/frontend/src/pages/workshop/agent-workbench/RDPExportPanel.tsx` | RDP.zip UI | 增加 local publish action/result |
| `app/frontend/src/pages/workshop/agent-workbench/RDPExportPanel.test.tsx` | 前端测试 | 覆盖 publish success 和 external channel 不被 UI 使用 |

## 对抗测试设计（种已知 bug，门必抓）[必填]
1. 未 materialize / 未 source bundle 的 package 不能 publish；不得只凭 manifest 过。
2. archive sha 与文件内容不一致 → 拒，publish registry 不写。
3. channel 只允许本机 registry 标签，不接受 external/object-storage/http URL。
4. publish 结果必须写 append-only audit，restart replay 后可见。
5. 前端 publish 只能调本机 publish endpoint，不能直接上传或构造外部 URL。

## 非目标 [按需]
不接公网、对象存储、CI release、生产部署、实盘运行、重新回测或绕过 archive/source bundle guard。

## 验收一句话 [必填]
RDP package 能在本机 registry 中发布并留下可重放审计记录；缺 archive prerequisites、tampered archive、external channel 都被测试抓住；前端 RDP.zip 面板能触发 local publish 且不外发。

## 完成记录（2026-06-26）
- 新增 `RDPPackagePublishRecord` / `RDPLocalPackagePublisher` / `PersistentRDPPackagePublishStore`，把 archive guard 已通过的 RDP zip 复制到本机 `_published/<package_id>/` registry，并写 append-only JSONL publish audit。
- 新增 `POST /api/research-os/rdp/manifests/{package_id}/publish`，只支持 `channel=local_registry`；endpoint 先跑 `RDPPackageArchiveExporter.export()`，再 publish 和落审计。新增 `GET /api/research-os/rdp/publications` 只读列表。
- `RDPExportPanel` 增加 `Publish local` action，前端固定发送 `{channel:"local_registry"}`，不接受外部 URL 或对象存储目标。
- 对抗测试覆盖：local publish 成功 + replay、tampered archive 拒绝、缺 source bundle 拒绝、external channel 拒绝、API publish/list、unknown manifest 404；前端覆盖 publish success + local registry body。
- 验证：`tests/test_research_os_rdp_publish.py -q` → 6 passed / 2 warnings；RDP package group → 53 passed / 2 warnings；Research OS scoped group → 185 passed / 2 warnings；`cd app/frontend && npm test -- RDPExportPanel.test.tsx` → 5 passed；`cd app/frontend && npm test -- agentWorkbench.test.tsx` → 40 passed；`cd app/frontend && npm run build` → tsc + vite build PASS（chunk size warning 保留）；`cd app/backend && python -m pytest -q` → 1499 passed / 13 skipped / 278 warnings。
- 边界：未接公网、对象存储、CI release、生产部署、实盘运行、重新回测或外部发布目标；这是本机 registry publish。
