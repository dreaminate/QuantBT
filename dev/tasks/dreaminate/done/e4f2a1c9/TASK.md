---
uuid: e4f2a1c9a0c54e0fb624b1dcb8a0c4d7
title: Rejected Model Registry promotion writes Model QRO
status: done
owner: dreaminate
assigned_by: dreaminate
review_status: 1
priority: P1
area: research-os-model-entrypoint
source: goal-gap
source_ref: GOAL §1/§7/§8/§14/§15/§16 rejected Model Registry promotion writes QRO / Research Graph
depends_on: [6c3d8f21c6f14d2d8f7f4c2b9a6e1d42]
completed_at: 2026-06-27
---

# Rejected Model Registry promotion writes Model QRO

## Scope [必填]
把旧 `ModelRegistry` staging/production 晋级被 approval gate 拒绝的路径接入 Research Graph。`POST /api/models/{model_id}/promote` 仍返回 422，但 `detail` 里带 `qro_id` / `research_graph_command_id`，Graph 中写一条 rejected `Model` QRO。

## 上下文 / 动机 [按需]
`6c3d8f21` 已覆盖 promotion pending gate 和 approve success。被三角证据、honest-N 或验证官缺口拒绝的 promotion gate 也是治理事实；GOAL §15 的 PromotionRecord 不应只记录成功路径。本卡闭合 rejected gate 审计，不把失败缺口正文、verdict 文案或 raw evidence 复制进 QRO。

## 接线点（file:line，实现时复核）[必填]
| 文件 | 改什么 |
|---|---|
| `app/backend/app/main.py` | `GateRejection` 分支查回 stored gate，写 rejected Model QRO；QRO output 只加 `gap_count` / `gaps_hash` / `verdict_hash` |
| `app/backend/tests/test_model_governance.py` | 覆盖 rejected promotion 422 返回 QRO refs，QRO/audit 不泄露 raw gap/verdict/evidence |

## 对抗测试设计（种已知 bug，门必抓）[必填]
1. 三角证据不同向的 promotion 仍必须 422。
2. 422 detail 必须带 `qro_id` / `research_graph_command_id`，方便审计下钻。
3. rejected QRO 输出 `promotion_gate_rejected`、`gap_count`、`gaps_hash`、`verdict_hash`。
4. QRO 不复制“证据不足/三角不同向”等缺口正文，也不复制 DSR/PBO/champion raw evidence。

## 红线 [按需]
- 不允许为了写 QRO 放行 rejected gate。
- 不允许把 rejected gate 说成 pending/approved。
- 不允许把 raw gap 文本、raw verdict 文案或 raw evidence 放进 QRO contract/audit。
- 不允许改弱 ModelPassport / ValidationDossier / approval gate 现有门。

## 非目标 [按需]
不实现 runtime serving，不实现独立 sandbox artifact inspection process，不实现 remote artifact store，不实现 runtime auto-promotion，不实现 live model serving 或所有模型相关 API 入口贯通。

## 验收一句话 [必填]
Model Registry promotion 被 gate 拒绝时仍返回 422，但同一失败事实会写 rejected `Model` QRO；Graph audit 只暴露 refs/hash/count，不暴露 raw evidence、gap 或 verdict 文案。

## 完成记录（2026-06-27）
- `_record_model_promotion_request_qro` 支持 rejected gate，输出 `gap_count` / `gaps_hash` / `verdict_hash`。
- `GateRejection` 端点分支查回 stored gate，写 rejected Model QRO，并把 QRO refs 放进 422 detail。
- 本地验证：
  - `python -m pytest app/backend/tests/test_model_governance.py -q` -> 20 passed / 2 warnings。
  - `python -m pytest app/backend/tests/test_training_api.py app/backend/tests/test_training_service.py app/backend/tests/test_model_governance.py app/backend/tests/test_model_desk_m2.py app/backend/tests/test_research_graph_persistence.py app/backend/tests/test_agent_runtime_research_graph.py app/backend/tests/test_entrypoint_gate_coverage.py app/backend/tests/test_research_os_spine.py app/backend/tests/test_goal_coverage.py app/backend/tests/test_platform_coverage.py app/backend/tests/test_engineering_standards.py -q` -> 127 passed / 2 warnings。
  - `python -m compileall app/backend/app` -> PASS。
  - `python dev/scripts/validate_dev.py` -> 49 ✅ / 0 ❌ / 0 ⚠️；DAG 149 卡。
