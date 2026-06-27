---
uuid: 1058c62d585a4c3d8c00e42d1f67ac85
title: RDP trust release gate management UI
status: done
owner: dreaminate
assigned_by: dreaminate
review_status: 1
priority: P1
area: research-os-trust-rdp-release-ui
source: goal-gap
source_ref: GOAL §13 Trust Layer release gate management UI; GOAL §17 Research Delivery Package publish standard
depends_on: [e9c58149730a40109bc11eea5758f108]
completed_at: 2026-06-27
---

# RDP trust release gate management UI

## Scope [必填]
在 RDP export desk 内接入 Trust Release Gate 管理面。UI 读取 `/api/research-os/trust/summary`，显示已登记 release gates；可填写 §13 六类检查 refs 并调用 `/api/research-os/trust/release_gates` 记录 gate；创建或选择 gate 后把 `release_ref` 写入 local publish 的 `trust_release_ref`。

## 上下文 / 动机 [按需]
`e9c58149` 已让 RDP local publish 必须引用已登记 trust release gate，但前端只有手填 `trust_release_ref` 输入。用户无法在发布台内创建或选择 gate，TRACE 和 state 仍把完整 release gate 管理 UI 标成缺口。本卡补本地管理入口，不把检查 refs 的录入说成压力测试已经自动执行。

## 接线点（file:line，实现时复核）[必填]
| 文件 | 改什么 |
|---|---|
| `app/frontend/src/pages/workshop/agent-workbench/RDPExportPanel.tsx` | 新增 trust summary 读取、release gate 列表、Use 选择、Record gate 表单与缺字段前端阻断 |
| `app/frontend/src/pages/workshop/agent-workbench/RDPExportPanel.test.tsx` | 覆盖 summary 展示、Use 填入 publish ref、创建 gate payload/刷新、缺字段不打后端 |

## 对抗测试设计（种已知 bug，门必抓）[必填]
1. summary 返回已有 release gate 时，UI 必须展示 gate ref 和检查 refs。
2. 点击 Use 必须填入 publish `trust_release_ref`，不改 publication 记录。
3. Record gate 必须按后端 schema 提交 `release_gate` 对象，成功后刷新列表并填入 publish ref。
4. 任一 required ref 缺失时前端必须阻断，不调用 `/api/research-os/trust/release_gates`。
5. 既有 publish flow 仍要求 source-run integrity 和非空 trust release ref。

## 红线 [按需]
- 不声称 anti-flattery / multi-turn / expert veto / weakness / mock / cold-start checks 已由 UI 自动运行。
- 不把 local publish UI 说成外部 release、CI release 或线上验收。
- 不绕过后端 TrustReleaseGate validator；前端只做基础缺字段阻断。

## 非目标 [按需]
不实现专家工作流、自动压力测试生成器、外部 object-store publish、CI release、线上发布证明、全局 disclosure UI 或 release approval workflow。

## 验收一句话 [必填]
RDP export desk 现在能在同一界面查看、创建并选择 Trust Release Gate，local publish 不再只能手填未知 `trust_release_ref`。

## 完成记录（2026-06-27）
- `RDPExportPanel` 启动时读取 `/api/research-os/trust/summary`，显示 release gate 总数和已登记 gate refs。
- 新增 Record gate 表单，提交 `release_gate` 七个字段；缺字段时显示错误且不打后端。
- 成功创建 gate 后刷新 summary，并把返回的 `release_ref` 填入 publish 输入。
- 已有 gate 可点击 Use 填入 publish `trust_release_ref`；原 materialize/bundle/attest/archive/publish flow 保持。
- 本地验证：
  - `cd app/frontend && npm test -- RDPExportPanel.test.tsx --run` -> 10 passed。
  - `cd app/frontend && npm test -- --run` -> 28 files / 311 tests passed。
  - `cd app/frontend && npm run build` -> PASS（保留既有 Vite chunk-size warning）。
  - `python dev/scripts/validate_dev.py` -> PASS（49 ✅ / 0 ❌ / 0 ⚠️；237 cards）。
  - `git diff --check` -> PASS。
