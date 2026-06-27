---
uuid: 0f6a1d2e7c884f18a3e0cbb8b521aa49
title: Governed model prediction serving seam
status: done
owner: dreaminate
assigned_by: dreaminate
review_status: 1
priority: P1
area: research-os-model-governance
source: goal-gap
source_ref: GOAL §15 runtime serving boundary
depends_on: [0e5c2a9db4f94c9fb7d1a6e2c83f5170]
completed_at: 2026-06-27
---

# Governed model prediction serving seam

## Scope [必填]
新增受控模型预测入口 `/api/models/{model_id}/versions/{version}/predict`，让 staging/production ModelVersion 能在 ModelPassport、artifact inspection、MonitoringProfile 均存在时执行本地预测，并把调用事实写成 `ModelServingInvocationRecord`。治理记录只存 request/prediction hash、row_count、feature refs 和相关治理 refs，不存 raw rows 或 raw prediction payload。

## 上下文 / 动机 [按需]
`0e5c2a9d` 已让模型 artifact inspection 可执行、可记录。§15 仍缺 runtime serving 边界。本卡先打通 offline/staging prediction seam，让模型被调用前必须经过 stage、passport、inspection、monitoring 四道门；这不是 live broker serving，也不自动晋级。

## 接线点（file:line，实现时复核）[必填]
| 文件 | 改什么 |
|---|---|
| `app/backend/app/research_os/model_governance.py` | 新增 `ModelServingInvocationRecord`、append-only replay、serving invocation gate |
| `app/backend/app/research_os/__init__.py` | 导出 serving invocation 类型与 parser |
| `app/backend/app/main.py` | 新增 governed prediction endpoint，并扩展 model governance summary |
| `app/backend/tests/test_model_governance.py` | 覆盖 staging prediction success、dev stage fail-closed、summary 不保存 raw rows/predictions |

## 对抗测试设计（种已知 bug，门必抓）[必填]
1. dev stage 模型不能走 prediction serving。
2. prediction serving 必须要求 recorded ModelPassport。
3. prediction serving 必须要求 accepted artifact inspection。
4. prediction serving 必须要求 matching MonitoringProfile。
5. serving invocation registry 只记录 hash/row_count/refs，不记录 raw rows 或 raw prediction payload。

## 红线 [按需]
- 不允许把 dev 模型当 serving 模型。
- 不允许绕过 validation dossier / artifact inspection / monitoring profile。
- 不允许把 raw feature rows 或 raw predictions 写入 governance registry。
- 不允许把此入口说成 live trading、broker serving、runtime auto-promotion 或生产部署。

## 非目标 [按需]
不实现 live broker serving，不实现 remote artifact store，不实现 runtime auto-promotion，不实现外部监控系统回路，不实现容器级/内核级 sandbox。

## 验收一句话 [必填]
模型预测入口只在 staging/production + passport + artifact inspection + monitoring profile 全部满足时执行，调用事实落 `ModelServingInvocationRecord`，raw rows/predictions 不进治理日志。

## 完成记录（2026-06-27）
- 新增 `ModelServingInvocationRecord`，registry 可 append-only replay。
- 新增 `/api/models/{model_id}/versions/{version}/predict`，要求 staging/production、passport、accepted artifact inspection、monitoring profile。
- Prediction response 返回预测给调用方；governance summary 只返回 row_count、feature_refs、request_hash、prediction_hash 和 refs。
- 本地验证：
  - `python -m pytest app/backend/tests/test_model_governance.py -q` -> 30 passed / 2 warnings。
  - `python -m pytest app/backend/tests/test_training_api.py app/backend/tests/test_training_service.py app/backend/tests/test_model_governance.py app/backend/tests/test_model_desk_m2.py app/backend/tests/test_research_graph_persistence.py app/backend/tests/test_agent_runtime_research_graph.py app/backend/tests/test_entrypoint_gate_coverage.py app/backend/tests/test_research_os_spine.py app/backend/tests/test_goal_coverage.py app/backend/tests/test_platform_coverage.py app/backend/tests/test_engineering_standards.py -q` -> 138 passed / 2 warnings。
  - `python -m compileall app/backend/app` -> PASS。
  - `python dev/scripts/validate_dev.py` -> 49 ✅ / 0 ❌ / 0 ⚠️；DAG 152 卡。
