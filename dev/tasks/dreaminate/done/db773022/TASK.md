---
uuid: db7730220c2d4efe9b291b054f602652
title: RDP frontend export panel——研究执行台交付包导出入口
status: done
owner: dreaminate
assigned_by: dreaminate
review_status: 1
priority: P1
area: research-os-rdp
source: goal-gap
source_ref: dev/GOAL.md §17 + dev/state/dreaminate/state.md Research Delivery Package gap
depends_on: [31ccd0028ff4446b9508e9b30f0ea7d9]
---

# RDP frontend export panel

## Scope [必填]
在研究执行台产物工作区增加 RDP 导出面板：读取后端 manifest registry，展示交付包证据状态，允许用户按 manifest 声明 materialize、补 source_map bundle、记录 source-to-run integrity attestation，并下载 archive zip。

## 上下文 / 动机 [按需]
RDP 后端已有 manifest registry/API、open materializer、source-file content bundler/API、deployment attestation/API、archive export/API、source-to-run integrity attestation/API；`dev/state/dreaminate/state.md` 仍明确缺前端导出 UI。GOAL §17 要求 Research Delivery Package 是用户可导出的开放格式交付物。

## 接线点（file:line，实现时复核）[必填]
| 文件 | 位置 | 改什么(扩展不替换) |
|---|---|---|
| `app/frontend/src/pages/workshop/agent-workbench/RDPExportPanel.tsx` | 新组件 | manifest list/detail、materialize、bundle source map、source-run attestation、archive 下载 UI |
| `app/frontend/src/pages/workshop/agent-workbench/RDPExportPanel.test.tsx` | 新测试 | 覆盖成功路径、缺 manifest、archive 422、unsafe arbitrary source path 不得自动注入 |
| `app/frontend/src/pages/workshop/agent-workbench/AgentWorkbenchPage.tsx` | Workspace tab | 增加 RDP.zip 产物 tab |
| `app/frontend/src/pages/workshop/agent-workbench/agentMock.ts` | WorkspaceTab type | 增加 `rdp` tab |

## 对抗测试设计（种已知 bug，门必抓）[必填]
1. manifest registry 为空 → UI 明确显示无可导出包，不出现下载按钮。
2. 只点下载 archive 时后端 422（缺 materialize/source bundle）→ 显示错误，不伪造 zip 或成功。
3. source bundle 只能由 manifest `source_file_refs` 生成 mapping 输入；UI 不自动写绝对路径或 `../` 路径。
4. source-run attestation 必须要求 run_id；空 run_id 不发请求。
5. archive 下载使用后端 `application/zip` response，并展示 `X-RDP-Archive-SHA256`，不把本地下载等同 live publish。

## 非目标 [按需]
不实现 live publish、公网/对象存储上传、外部部署、自动 parser/RAG ingestion、重新运行回测或绕过后端 RDP guard。

## 验收一句话 [必填]
研究执行台出现真实 RDP 导出入口；用户能从 manifest registry 选择包、按声明补 source map、调后端 materialize/bundle/source-run/archive；错误和缺口诚实显示；Vitest 覆盖前端坏门。

## 完成记录（2026-06-26）
- 新增 `RDPExportPanel`，挂到研究执行台产物工作区 `RDP.zip` tab；默认读取 `/api/research-os/rdp/manifests`，选择 package 后读 manifest detail。
- UI 可调用 materialize、bundle_sources、source_run_integrity_attestations 和 archive 下载；archive 下载展示后端 `X-RDP-Archive-SHA256` / file count，不声明 live publish。
- `source_map` 默认只从 manifest `source_file_refs` 推导安全相对路径；`../`、绝对路径和空 run_id 在前端先拦，后端 guard 仍是权威。
- 新增 `RDPExportPanel.test.tsx`，覆盖空 registry、完整 materialize→bundle→attest→archive、archive 422 诚实报错、unsafe source ref 不自动映射、空 run_id 不发 attestation。
- 验证：`cd app/frontend && npm test -- RDPExportPanel.test.tsx` → 5 passed；`cd app/frontend && npm test -- agentWorkbench.test.tsx` → 40 passed；`cd app/frontend && npm run build` → tsc + vite build PASS（保留 chunk size warning）。
- 边界：未实现 live package publish、公网/对象存储上传、外部部署、自动 parser/RAG ingestion 或重新运行回测。
