---
uuid: 6c3d8f21c6f14d2d8f7f4c2b9a6e1d42
title: Model Registry promotion writes Model QRO
status: done
owner: dreaminate
assigned_by: dreaminate
review_status: 1
priority: P1
area: research-os-model-entrypoint
source: goal-gap
source_ref: GOAL §1/§7/§8/§14/§15/§16 Model Registry promotion writes QRO / Research Graph
depends_on: [a2f46b22ca554d12a226159b5f6c8dbb]
completed_at: 2026-06-27
---

# Model Registry promotion writes Model QRO

## Scope [必填]
把旧 `ModelRegistry` staging/production 晋级开门和审批成功路径接入 Research Graph。`POST /api/models/{model_id}/promote` 成功返回 pending gate 时写 `Model` QRO；`POST /api/models/{model_id}/gates/{gate_id}/approve` 成功真翻 stage 后再写审批 `Model` QRO，并在响应里返回 `qro_id` / `research_graph_command_id`。

## 上下文 / 动机 [按需]
训练成功已能写 Model QRO，但 Model Registry promotion 仍只停在 approval gate / ModelVersion store。GOAL §15 明确需要 `PromotionRecord` 进入模型治理链路；本卡闭合“模型版本晋级请求/审批 → Model QRO”这条 runtime seam，不把 pending gate 说成 approval，不把 approval 说成 live serving 或执行许可。

## 接线点（file:line，实现时复核）[必填]
| 文件 | 改什么 |
|---|---|
| `app/backend/app/main.py` | 新增 Model promotion request / approval QRO helpers；模型晋级和审批端点返回 Graph refs；QRO audit allowlist 增加 gate/stage/ref/hash 字段 |
| `app/backend/tests/test_model_governance.py` | 覆盖晋级开门 QRO、审批 QRO，以及 QRO/audit 不泄露 raw evidence 或审批 reason |

## 对抗测试设计（种已知 bug，门必抓）[必填]
1. promotion pending gate 必须写 `QROType.MODEL`，并保留 `gate_id`、`model_version_ref`、`model_passport_ref`、`validation_dossier_ref`。
2. promotion request QRO 只保存 `evidence_hash`，不能复制 DSR/PBO/champion_challenger/delta_sharpe 原始证据。
3. approval QRO 只保存 `reason_hash` / `risk_restated_hash`，不能复制审批理由正文。
4. approval 成功后必须真翻 ModelRegistry stage，并把 `side_effect_ref` 写入 QRO。

## 红线 [按需]
- 不允许把 pending promotion gate 说成 approval。
- 不允许把 Model promotion approval 说成 live serving readiness、safe loading approval 或执行许可。
- 不允许把 raw evidence、raw approval reason、metrics 明细或 artifact path 放进 QRO contract/audit。
- 不允许为了写 Graph 改弱 ModelPassport / ValidationDossier / approval gate 现有门。

## 非目标 [按需]
不实现 rejected gate QRO，不实现 runtime serving，不实现独立 sandbox artifact inspection process，不实现 remote artifact store，不实现 runtime auto-promotion，不实现 live model serving 或所有模型相关 API 入口贯通。

## 验收一句话 [必填]
Model Registry promotion 成功开门和成功审批都会写 `Model` QRO；响应返回 QRO refs，Graph audit 只暴露 refs/hash，不暴露 raw evidence 或审批 reason。

## 完成记录（2026-06-27）
- `_record_model_promotion_request_qro` 记录 promotion request / pending gate，保存 ModelVersion/ApprovalGate/ModelPassport/ValidationDossier refs 与 evidence hash。
- `_record_model_promotion_approval_qro` 记录审批成功和 stage side effect，保存 reason/risk hashes 与 side effect ref。
- `/api/models/{model_id}/promote` 和 `/api/models/{model_id}/gates/{gate_id}/approve` 成功响应返回 `qro_id` / `research_graph_command_id`。
- 本地验证：
  - `python -m pytest app/backend/tests/test_model_governance.py -q` -> 19 passed / 2 warnings。
  - `python -m pytest app/backend/tests/test_training_api.py app/backend/tests/test_training_service.py app/backend/tests/test_model_governance.py app/backend/tests/test_model_desk_m2.py app/backend/tests/test_research_graph_persistence.py app/backend/tests/test_agent_runtime_research_graph.py app/backend/tests/test_entrypoint_gate_coverage.py app/backend/tests/test_research_os_spine.py app/backend/tests/test_goal_coverage.py app/backend/tests/test_platform_coverage.py app/backend/tests/test_engineering_standards.py -q` -> 126 passed / 2 warnings。
  - `python -m compileall app/backend/app` -> PASS。
  - `python dev/scripts/validate_dev.py` -> 49 ✅ / 0 ❌ / 0 ⚠️；DAG 148 卡。
