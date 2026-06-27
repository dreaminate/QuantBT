---
uuid: 44ca5ea7d0a342a8ab5583bb0ac87e5b
title: RDP local publish requires trust release approval ref
status: done
owner: dreaminate
assigned_by: dreaminate
review_status: 1
priority: P1
area: research-os-rdp-publish-approval-gate
source: goal-gap
source_ref: GOAL §17 RDP release approval hard gate; GOAL §13 Trust Layer approval workflow
depends_on: [acd267d19c9542c08700755ffc473ed9, e9c58149730a40109bc11eea5758f108]
completed_at: 2026-06-27
---

# RDP local publish requires trust release approval ref

## Scope [必填]
升级 RDP local publish hard gate：`RDPPackagePublishRecord` 保存 `trust_release_approval_ref`，local publisher 和 `/api/research-os/rdp/manifests/{package_id}/publish` 都要求 payload 同时带已登记 `trust_release_ref` 与 approved `trust_release_approval_ref`；publication summary/UI 回显 approval ref。

## 上下文 / 动机 [按需]
`acd267d1` 已新增本地 release approval evidence record，但 RDP publish 仍只要求 release gate ref。这样 approval record 会停在旁路 UI，不会真正约束 local publish。本卡把 approval record 接成 local publish 硬门，但仍不声称 CI、外部发布或线上生效。

## 接线点（file:line，实现时复核）[必填]
| 文件 | 改什么 |
|---|---|
| `app/backend/app/research_os/rdp.py` | `RDPPackagePublishRecord` 增加 `trust_release_approval_ref`；publisher 缺 approval ref 拒绝 |
| `app/backend/app/main.py` | RDP publish API 校验 `trust_release_approval_ref` 已登记、与 `trust_release_ref` 匹配且 verdict=approved；响应和 publications summary 回显 |
| `app/backend/tests/test_research_os_rdp_publish.py` | 覆盖 publisher/API success、缺 approval、unknown approval、release mismatch、其他 publish 错误不被新门误判 |
| `app/frontend/src/pages/workshop/agent-workbench/RDPExportPanel.tsx` | publish 表单增加 `trust_release_approval_ref`，approval option/use 和 create success 会回填，publish payload 下发 |
| `app/frontend/src/pages/workshop/agent-workbench/RDPExportPanel.test.tsx` | 覆盖 publish payload 带 approval ref、缺 approval 前端阻断、响应回显 |

## 对抗测试设计（种已知 bug，门必抓）[必填]
1. 缺 `trust_release_approval_ref` 必须在前端/API/publisher 阻断。
2. unknown approval ref 必须 422 且不写 publication。
3. approval release 与 `trust_release_ref` 不一致必须 422。
4. 非 approved approval 不能 release。
5. 成功 publication record/hash 和 summary 必须包含 `trust_release_approval_ref`。

## 红线 [按需]
- 不声称 local publish 等于 CI release、外部 object store publish、线上发布或用户验收。
- 不允许绕开 approved approval ref 写 publication。
- 旧 JSONL publication record 无 approval ref 可 replay；新 publish 必须提供。

## 非目标 [按需]
不实现外部 publish/release、CI runner、live deployment runner、生产发布证明、线上验收或外部签名系统。

## 验收一句话 [必填]
RDP local publish 现在必须同时引用已登记 release gate 和 matching approved trust release approval；缺失、未知或不匹配时不写 publication。

## 完成记录（2026-06-27）
- `RDPPackagePublishRecord` 新增 `trust_release_approval_ref`，参与新 publish hash；旧记录缺字段仍可 replay。
- `RDPLocalPackagePublisher.publish()` 缺 `trust_release_approval_ref` 直接拒绝。
- `/api/research-os/rdp/manifests/{package_id}/publish` 要求 `trust_release_approval_ref` 已登记、release 匹配且 verdict=approved；response 和 publications summary 回显 approval ref。
- RDP export desk publish 表单新增 `trust_release_approval_ref`，approval 创建/选择后可回填，publish payload 下发。
- 本地验证（截至建卡时）：
  - `python -m compileall -q app/backend/app` -> PASS。
  - `python -m pytest app/backend/tests/test_research_os_rdp_publish.py -q` -> 8 passed / 2 warnings。
  - `python -m pytest app/backend/tests/test_trust_layer.py app/backend/tests/test_research_os_rdp_publish.py app/backend/tests/test_goal_coverage.py -q` -> 57 passed / 2 warnings。
  - `cd app/frontend && npm test -- RDPExportPanel.test.tsx --run` -> 1 file / 19 tests passed。
  - `cd app/frontend && npm test -- agentWorkbench.test.tsx MethodologyValidationPanel.test.tsx RDPExportPanel.test.tsx ResearchRAGPanel.test.tsx TrustDisclosurePanel.test.tsx --run` -> 5 files / 74 tests passed。
  - `cd app/frontend && npm test -- --run` -> 30 files / 328 tests passed。
  - `cd app/frontend && npm run build` -> PASS（保留既有 Vite chunk-size warning）。
  - `python -m pytest app/backend/tests -q` -> 1861 passed / 13 skipped / 283 warnings。
  - `python dev/scripts/validate_dev.py` -> PASS（49 ✅ / 0 ❌ / 0 ⚠️；246 cards）。
  - `git diff --check` -> PASS。
