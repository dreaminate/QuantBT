---
uuid: e9c58149730a40109bc11eea5758f108
title: Trust release gate registry for RDP publish
status: done
owner: dreaminate
assigned_by: dreaminate
review_status: 0
priority: P1
area: research-os-trust-rdp-release
source: goal-gap
source_ref: GOAL §13 trust layer release gate; GOAL §17 Research Delivery Package publish standard
depends_on: []
completed_at: 2026-06-27
---

# Trust release gate registry for RDP publish

## Scope [必填]
新增 §13 trust release gate append-only registry/API，并让 RDP local publish 必须引用已登记的 trust release gate ref；发布记录持久化 `trust_release_ref`，summary/publications 回显该 ref。

## 上下文 / 动机 [按需]
现有 `TrustReleaseGateRecord` 只在纯 contract 测试里验证，RDP local publish 可不经过反谄媚、多轮施压、专家否决、弱点折叠、mock honesty、cold-start honesty 检查。GOAL §13 要求发版门禁，§17 要求正式 Research Delivery Package 绑定验证/审批/监控和诚实边界。本卡把 gate 接到 publish 流水线。

## 接线点（file:line，实现时复核）[必填]
| 文件 | 改什么 |
|---|---|
| `app/backend/app/research_os/trust_layer.py` | 新增 `PersistentTrustReleaseGateRegistry` 与 `trust_release_gate_record_from_dict()` |
| `app/backend/app/research_os/rdp.py` | `RDPPackagePublishRecord` 增加 `trust_release_ref`；新 `RDPLocalPackagePublisher.publish()` 要求 gate ref |
| `app/backend/app/research_os/__init__.py` | 导出 trust release gate registry/helper |
| `app/backend/app/main.py` | 新增 `TRUST_RELEASE_GATE_REGISTRY`、`/api/research-os/trust/release_gates`、`/api/research-os/trust/summary`；RDP publish 前解析已登记 gate |
| `app/backend/tests/test_trust_layer.py` / `app/backend/tests/test_research_os_rdp_publish.py` | 覆盖 registry/API、RDP publish gate 要求和 failure no-write |
| `app/frontend/src/pages/workshop/agent-workbench/RDPExportPanel.tsx` | local publish UI 增加 `trust_release_ref` 输入并随 publish payload 提交 |
| `app/frontend/src/pages/workshop/agent-workbench/RDPExportPanel.test.tsx` | 覆盖 publish payload 带 gate ref、空 ref 不打后端 |

## 对抗测试设计（种已知 bug，门必抓）[必填]
1. release gate 缺 expert veto / cold-start / mock honesty 等任一检查 ref，registry/API 必须拒绝且不写 JSONL。
2. RDP publish payload 缺 `trust_release_ref` 必须 422，不写 publish record。
3. RDP publish payload 引用 unknown trust release ref 必须 422，不写 publish record。
4. 成功 publish 的 `RDPPackagePublishRecord` 和 publications summary 必须携带 `trust_release_ref`。
5. 旧 publish JSONL 没有 `trust_release_ref` 时 replay 不被新 hash 字段打断；新写入必须带 gate ref。

## 红线 [按需]
- 不把 RDP local publish 说成外部发版或线上发布。
- 不声称 trust pressure tests 已实际运行；registry 只记录已有检查 refs。
- 不允许 publish 绕过已登记 release gate。

## 非目标 [按需]
不实现专家工作流、自动压力测试生成器、外部 object-store publish、CI/线上验证或用户验收；前端只补已有 local publish 面的 `trust_release_ref` 输入，不实现完整 release gate 管理 UI。

## 验收一句话 [必填]
RDP local publish 现在必须引用已登记 trust release gate，缺 gate 或 unknown gate 不写发布记录。

## 完成记录
- 新增 `PersistentTrustReleaseGateRegistry`，以 JSONL append-only 保存/replay `TrustReleaseGateRecord`，缺任一 §13 release gate check 会拒绝。
- 新增 `/api/research-os/trust/release_gates` 和 `/api/research-os/trust/summary`，summary 只返回 release gate refs。
- `RDPPackagePublishRecord` 新增 `trust_release_ref`；新 publish 调用缺该 ref 会拒绝，历史无该字段记录仍可 replay。
- `/api/research-os/rdp/manifests/{package_id}/publish` 在 export/publish 前要求 `trust_release_ref` 已登记；缺 ref 或 unknown ref 422 且不写 publish record。
- `RDPExportPanel` local publish 表单新增 `trust_release_ref` 输入；publish payload 带 `{ channel: "local_registry", trust_release_ref }`，空 ref 前端阻断，不打后端。
- 验证：`pytest app/backend/tests/test_trust_layer.py app/backend/tests/test_research_os_rdp_publish.py -q` → **20 passed / 2 warnings**；RDP/trust adjacent **47 passed / 2 warnings**；`python -m compileall -q app/backend/app` → PASS；`cd app/frontend && npm test -- RDPExportPanel.test.tsx --run` → **1 file / 6 tests passed**；RDP/agent-workbench frontend scoped → **2 files / 46 tests passed**；`cd app/frontend && npm run build` → PASS（保留既有 chunk-size warning）。
